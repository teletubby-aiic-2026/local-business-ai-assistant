"""One assistant turn: classify -> settle conditions -> snapshot -> cards -> answer.

All condition changes go through the PR #12 endpoints (OnboardingBridge), so
the chat and the B1~B6 screens share one saved state per session. Numbers in
answers only come from fact cards built from PR #12 results.

A ``writer`` (clova_client.ClovaWriter when APP_MODE=live) receives the chosen
cards and the classification and returns text. The server removes "참고"
lines, puts the conditions line first if the model left it out, and publishes
the text only if answer_check passes; the warnings and next-question lines are
always the server's own. Otherwise the fixed-form answer is used.

Ranking questions ('서울에서 카페 매출 높은 곳', '강남 말고 추천해줘') are
answered by ranking.py, which sorts the B2 source's quarterly sales across
official markets; its buttons open one market through the normal flow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import logging
import re

from fastapi import HTTPException

from app.assistant import multi
from app.assistant import context as location
from app.assistant import opinion as opinions
from app.assistant import site_costs
from app.assistant import templates
from app.assistant.answer_check import check_answer
from app.assistant.answer_check import feedback as check_feedback
from app.assistant.answer_check import has_statistics, repair_citations
from app.assistant.bridge import OnboardingBridge, error_message
from app.assistant.facts import cards_from_snapshot, select_cards
from app.assistant.intent import DEFAULT_TOPICS, classify, industry_codes
from app.assistant.korean import josa, with_units
from app.assistant.overview import seoul_cards, summed_cards
from app.assistant.ranking import (ALL_INDUSTRIES_NAME, INDUSTRY_COUNT, NEAR_KM, Exclusion, RankingRequest,
                                   SeoulSalesSource, areas_for_mentions, industry_rank_cards, order_markets, period_label,
                                   rank_industries, rank_sales, ranking_card)
from app.assistant.snapshot import SnapshotCache, add_comparison, build_snapshot

SCHEMA = "assistant-reply-v1"
# Short requests that only make sense as a follow-up: '추천해줘', '골라 줘', '뭐가 좋아?'.
_FOLLOW_REQUEST = re.compile(r"추천|골라|뭐가 ?좋|뭐가 ?나아|어떤 게 ?좋|알려 ?줘")
_DEFAULT_STATUS = "operating"
_LEAVE_OUT = re.compile(r"말고|빼고|제외")
# An opinion with no candidates named ('서울에서 어느 상권이 좋다고 봐?') against one about known places.
_OPEN_WHERE = re.compile(r"어느상권|어떤상권|무슨상권|어디|서울")
# 'where should I open' is a view, however the model labelled it; '매출 높은 곳' is a list.
_ASKS_A_VIEW = re.compile(r"좋다고봐|좋을까|좋을것같|괜찮을까|창업")
_BY_FIGURE = re.compile(r"매출|순위|높은|많이팔|잘팔|무슨구|어느구|어떤구")
# The cards hold sales. What is left after costs is in no public file, so it is said first (2026-11-08 export).
_PROFIT = re.compile(r"수익|순이익|영업이익|마진|남는돈|얼마나남")
_CHOSEN = re.compile(r"둘중|두곳|두군데|두지역|두상권|두동네|어느쪽|여기|거기|이상권|이곳|그곳|이동네")
_DISTRIBUTIONS = {"sales_age", "sales_time", "sales_weekday"}
_SEOUL_TOPICS = _DISTRIBUTIONS | {"sales_total", "stores_count", "stores_open_close"}
_NOT_SUMMED = {"population": "유동인구", "change_yoy": "작년 대비 변화", "change_qoq": "지난 분기 대비 변화"}
# Replies that ask the user to name or pick a place, industry or market.
_SETUP_KINDS = ("need_location", "need_industry", "choose_location", "choose_industry", "choose_area")
# Topics a single B5 comparison cannot show, so '강남역이랑 연령대 비교' reads both markets (multi.py).
_MULTI_TOPICS = {"sales_age", "sales_time", "sales_weekday", "population", "change_yoy", "change_qoq",
                 "stores_open_close"}
_log = logging.getLogger("app.assistant.flow")


@dataclass
class Intent:
    """What this turn wants, after merging the classifier output with pending context."""
    topics: list[str]
    location: dict | None = None        # ProfileLocation fields
    location_label: str | None = None
    industry_code: str | None = None
    business_status: str | None = None
    period_code: str | None = None
    comparison_area_code: str | None = None
    comparison_hint: str | None = None  # second place name for B5
    classification: dict = field(default_factory=dict)
    condition_change: bool = False
    opinion: bool = False                # answer with the assistant's own view (opinion.py)
    area_code: str | None = None         # an official market named outright ('강남을지병원')


def location_payload(place: dict) -> dict | None:
    if place["kind"] == "station":
        return {"kind": "station", "station_id": place["station_ids"][0]}
    if place["kind"] == "neighborhood":
        return {"kind": "area", "district_code": place["district_code"], "neighborhood_code": place["code"]}
    return None


def _same_location(profile: dict | None, payload: dict | None) -> bool:
    if profile is None or payload is None:
        return payload is None
    saved = profile["location"]
    if payload["kind"] == "station":
        return saved.get("kind") == "station" and saved.get("station_id") == payload["station_id"]
    return saved.get("kind") == "area" and saved.get("neighborhood_code") == payload.get("neighborhood_code")


def _conditions(state: dict | None) -> dict | None:
    if not state or not state.get("conditions_confirmed"):
        return None
    selection, profile = state["analysis_selection"], state["profile"]
    return {"area_code": selection.get("area_code"), "area_name": selection.get("area_name"),
            "industry_code": profile["industry"]["code"], "industry_name": profile["industry"]["name"],
            "period": selection.get("period"), "period_label": selection.get("period_label"),
            "location_label": profile["location"].get("label")}


def _names_same_market(label: str | None, area_name: str | None) -> bool:
    """'상도역' and the chosen market '상도역 1번' are the same place for a follow-up question."""
    return bool(label and area_name and len(label) >= 2 and area_name.startswith(label))


# When a requested card has no data, the nearest data the same market does have.
_SUBSTITUTES = {"sales_age": ("population",), "sales_time": ("population",), "sales_weekday": ("stores_count",),
                "sales_total": ("stores_count", "population")}


def _answers(card: dict, missing_topic: str) -> bool:
    """Does this available card really stand in? Ages need age values on the population card."""
    if card.get("status") != "available":
        return False
    if missing_topic == "sales_age" and card["topic"] == "population":
        return any(value.get("group") == "연령대" for value in card.get("values", []))
    if missing_topic == "sales_time" and card["topic"] == "population":
        return any(value.get("group") == "시간대" for value in card.get("values", []))
    return True


def _with_substitutes(all_cards: list[dict], cards: list[dict], topics=()) -> tuple[list[dict], list[str], list[str]]:
    """(cards with substitutes added, missing topics, substitute topics).

    A topic is missing when it was asked for (or its card is shown) and no available card answers it, e.g.
    '연령대는?' while the whole sales file failed and only the sales_total error card exists.
    """
    shown = {card["topic"] for card in cards}
    available = {card["topic"] for card in cards if card.get("status") == "available"}
    asked = [*topics, *(card["topic"] for card in cards)]
    missing = list(dict.fromkeys(topic for topic in asked if topic in _SUBSTITUTES and topic not in available))
    if any(topic != "sales_total" for topic in missing):
        missing = [topic for topic in missing if topic != "sales_total"]  # '연령별 매출', not '연령별 매출·매출'
    added = []
    for topic in missing:
        for alternative in _SUBSTITUTES[topic]:
            if alternative in shown or alternative in added:
                continue
            if any(card["topic"] == alternative and _answers(card, topic) for card in all_cards):
                added.append(alternative)
    if not added:
        return cards, [], []
    order = {card["id"]: index for index, card in enumerate(all_cards)}
    merged = cards + [card for card in all_cards if card["topic"] in added]
    return sorted(merged, key=lambda card: order.get(card["id"], len(order))), missing, added


def _action_classification(pending: dict) -> dict:
    """A classification-shaped dict for a button press, which has no text to classify."""
    return {"domain": "market_analysis", "turn_type": "action", "topics": pending.get("topics") or [],
            "text": pending.get("question") or "", "needs_user_choice": False, "needs_model": False,
            "analyzer": None, "reasons": [],
            "slots": {"locations": [], "excluded_locations": [], "industries": [],
                      "period": {"relative": None, "comparison": None, "period_code": None},
                      "business_status": pending.get("business_status")}}


class AssistantService:
    def __init__(self, store, history, endpoint_table, *, snapshots: SnapshotCache | None = None,
                 writer=None, use_morph: bool = True, today=None, ranking_source=None, planner=None):
        self.store = store
        self.history = history
        self.table = endpoint_table
        self.snapshots = snapshots or SnapshotCache()
        self.writer = writer
        self.use_morph = use_morph
        self.today = today
        self.ranking_source = ranking_source
        self.planner = planner  # planner.Planner when APP_MODE=live; None keeps the rule classifier

    # Public entry points ---------------------------------------------------
    def handle_message(self, owner: str, request, text: str, client_message_id: str | None) -> dict:
        repeated = self.history.find(owner, client_message_id)
        if repeated is not None:
            return {**repeated, "repeated": True}
        last = self.history.last(owner) or {}
        context = {"previous_topics": last.get("topics") or []}
        cls = classify(text, context=context, today=self.today or date.today(), use_morph=self.use_morph)
        bridge = OnboardingBridge(self.table, request)
        if self.planner is not None:
            # The model decides with everything in view; the rule result is one of its references and the fallback.
            cls = self._plan(owner, bridge, text, cls) or cls
        cls = self._with_named_market(cls)
        if not cls.get("unavailable") and _PROFIT.search(re.sub(r"\s", "", cls.get("text") or "")):
            cls = {**cls, "unavailable": "수익(비용을 뺀 이익)"}
            if cls["turn_type"] == "unknown":  # '여기 수익은 얼마나 나?' with no statistic word the rules know
                cls = {**cls, "domain": "market_analysis", "turn_type": "data_question", "topics": list(DEFAULT_TOPICS),
                       "topics_defaulted": True}
        response = self._respond(owner, bridge, cls, last)
        if cls.get("unavailable") and response["reply"].get("kind") in ("data_answer", "ranking", "industry_rank",
                                                                        "seoul_overview", "opinion", "multi_market",
                                                                        "all_industries"):
            # Say first what the public data cannot answer ('프랜차이즈 브랜드별 매출'), so the numbers below are
            # not read as an answer to it.
            response["reply"]["text"] = templates.unavailable_line(cls["unavailable"]) + "\n" + response["reply"]["text"]
        self.history.add(owner, client_message_id, text, response)
        return response

    def _profile_card(self, snapshot: dict) -> dict | None:
        selection = snapshot.get("selection") or {}
        code, source = selection.get("area_code"), self._source()
        reader = getattr(source, "context_table", None)
        if reader is None:
            return None
        try:
            row = reader(selection.get("period")).get(code)
            area = source.areas().get(code) or {}
        except Exception as error:  # location figures are optional
            _log.info("area profile skipped: %s", type(error).__name__)
            return None
        if not row:
            return None
        return location.profile_card({**row, "name": selection.get("area_name"), "area_type": area.get("type")})

    def _saved_costs(self, owner) -> dict:
        """The latest costs the user gave in this conversation (they go when the conversation is cleared)."""
        for turn in reversed(self.history.recent(owner, 50)):
            costs = (turn["response"].get("debug") or {}).get("site_costs")
            if costs:
                return costs
        return {}

    def _site_costs(self, owner, bridge, cls: dict, last: dict, said: dict | None, *, industry_code: str | None = None) -> dict:
        """'월세 500만 원, 권리금 5천만 원이야': what that means against the market's average sales per store."""
        try:
            state = bridge.state()
        except HTTPException:
            state = None
        costs = {**self._saved_costs(owner), **(said or {})}
        ask = {"site_costs_question": True, "question": cls.get("text"), "topics": []}
        if not costs:
            return self._finish(templates.ask_site_costs(), cls, state=state)
        current, profile = _conditions(state), (state or {}).get("profile") or {}
        saved = {"area_code": current["area_code"], "area_name": current["area_name"]} \
            if current and current.get("area_code") else None
        mentions = [m for m in cls["slots"]["locations"][:1] if not any(c.get("kind") == "district" for c in m["candidates"])]
        source, market = self._source(), None
        if cls.get("named_market"):
            market = {"area_code": cls["named_market"]["area_code"], "name": cls["named_market"]["name"]}
        elif mentions:
            try:
                found, _missing = multi.resolve(source, mentions, saved)
            except Exception as error:
                _log.warning("site costs market failed: %s", type(error).__name__)
                found = []
            market = found[0] if found else None
        elif saved:
            market = {"area_code": saved["area_code"], "name": saved["area_name"]}
        if market is None:
            return self._finish(templates.need_location(), cls, state=state, pending=ask, site_costs=costs)
        names = {c["code"]: c["name"] for m in cls["slots"].get("industries") or [] for c in m["candidates"]}
        code = industry_code or (next(iter(names)) if len(names) == 1 else None) or (profile.get("industry") or {}).get("code")
        if code is None:
            return self._finish(templates.need_industry(repeated=True), cls, state=state, pending=ask, site_costs=costs)
        try:
            period = (current or {}).get("period") or source.periods()[-1]
            row = next((r for r in opinions.market_table(source, code, period) if r["area_code"] == market["area_code"]), None)
        except Exception as error:
            _log.warning("site costs table failed: %s", type(error).__name__)
            row = None
        if row is None or not row.get("per_store_sales"):
            return self._finish(templates.data_unavailable("이 상권·업종은 점포당 매출을 계산할 자료가 없어요."), cls, state=state,
                                site_costs=costs)
        name = names.get(code) or row.get("industry_name") or code
        numbers = site_costs.calculate(costs, row["per_store_sales"])
        card = {**site_costs.card(costs, numbers, area_name=market["name"]), "id": "F2"}
        label = period_label(period)
        conditions = {"id": "F1", "topic": "conditions", "status": "available",
                      "text": f"분석 조건은 {market['name']} 상권, {name} 업종, {label} 자료입니다.",
                      "values": [{"label": "상권", "value": market["name"], "unit": None, "code": market["area_code"]},
                                 {"label": "업종", "value": name, "unit": None, "code": code},
                                 {"label": "기간", "value": label, "unit": None, "code": period}],
                      "warnings": [], "source_ref": {"analysis": "site_costs"}}
        cards = [conditions, card]
        reply = templates.site_costs_answer(cards, site_costs.lines(costs, numbers, area_name=market["name"], industry_name=name,
                                                                    card_id="F2"))
        return self._finish(reply, cls, state=state, cards=cards, topics=["site_costs"], site_costs=costs)

    def _with_named_market(self, cls: dict) -> dict:
        """'강남을지병원' is an official market the place dictionary reads as '강남' (강남역·강남구).

        The market named outright wins, and the places that were only pieces of it, or that the model copied
        from the saved conditions, are dropped. A name the dictionary already has is left to the normal flow.
        """
        spoken = re.sub(r"\s", "", cls.get("text") or "")
        if not spoken or cls.get("domain") in ("marketing", "customer"):
            return cls
        try:
            areas = self._source().areas()
        except Exception:  # catalogue not available: the dictionary answers as before
            return cls
        found = None
        for area in sorted(areas.values(), key=lambda a: -len(a.get("name") or "")):
            name = re.sub(r"\s", "", area.get("name") or "")
            if len(name) >= 4 and name in spoken and area.get("boundary_identity_status") == "code_name_match" \
                    and area.get("neighborhood_code") and area.get("district_code"):
                found = area
                break
        if found is None:
            return cls
        name = re.sub(r"\s", "", found["name"])
        slots = cls["slots"]
        if any(m["text"].replace(" ", "") == name for m in slots.get("locations") or []):
            return cls

        def keep(mentions):
            return [m for m in mentions or [] if m["text"] not in name and m["text"].replace(" ", "") in spoken]

        result = {**cls, "named_market": {"area_code": found["area_code"], "name": found["name"],
                                          "district_code": found["district_code"],
                                          "neighborhood_code": found["neighborhood_code"]},
                  "slots": {**slots, "locations": keep(slots.get("locations"))}}
        if cls.get("user_slots"):
            result["user_slots"] = {**cls["user_slots"], "locations": keep(cls["user_slots"].get("locations"))}
        if result.get("turn_type") in ("unknown", "smalltalk", "clarify"):
            result = {**result, "turn_type": "data_question", "domain": "market_analysis",
                      "topics": result.get("topics") or list(DEFAULT_TOPICS)}
        return result

    def _plan(self, owner, bridge, text: str, rule: dict) -> dict | None:
        try:
            state = bridge.state()
        except HTTPException:
            state = None
        loaded = []
        if state and state.get("conditions_confirmed"):
            snapshot = self.snapshots.get(SnapshotCache.key(owner, state))
            if snapshot is not None:
                loaded = [f"{card['id']} ({card['topic']}) {card['text'][:140]}" for card in cards_from_snapshot(snapshot)]
        recent = []
        for turn in self.history.recent(owner, 6):  # button presses are turns too, so look a little further back
            said = turn["user_text"] or "(버튼 선택)"
            reply = " ".join(((turn["response"].get("reply") or {}).get("text") or "").split())[:120]
            recent += [f"사용자: {said}", f"상권 비서: {reply}"]
        last_kind = ((self.history.last(owner) or {}).get("reply") or {}).get("kind")
        pending = (self.history.last(owner) or {}).get("pending") or {}
        focus = None
        if pending.get("all_market"):
            focus = f"{pending['all_market']['name']} 상권의 전체 업종(업종을 합친 값)"
        elif pending.get("multi_markets"):
            focus = "·".join(market["name"] for market in pending["multi_markets"]) + " 상권 함께 보기"
        return self.planner.plan(text, rule=rule, conditions=_conditions(state), recent=recent, loaded=loaded,
                                 focus=focus,
                                 today=self.today or date.today(), after_list=last_kind == "ranking",
                                 setting_up=last_kind in _SETUP_KINDS)

    def handle_action(self, owner: str, request, payload: dict) -> dict:
        last = self.history.last(owner) or {}
        pending = last.get("pending") or {}
        intent = Intent(topics=pending.get("topics") or list(DEFAULT_TOPICS),
                        location=pending.get("location"), industry_code=pending.get("industry_code"),
                        business_status=pending.get("business_status"), period_code=pending.get("period_code"),
                        comparison_hint=pending.get("comparison_hint"), opinion=bool(pending.get("opinion")),
                        # The question that led to this choice, so the answer can still address it.
                        classification={"domain": "market_analysis", "turn_type": "action", "topics": pending.get("topics") or [],
                                        "text": pending.get("question") or ""})
        kind = payload.get("type")
        bridge = OnboardingBridge(self.table, request)
        if kind == "location":
            location = {key: payload[key] for key in ("kind", "station_id", "district_code", "neighborhood_code") if payload.get(key)}
            intent.location = {"kind": "station", **location} if location.get("kind") == "station" else {**location, "kind": "area"}
            # A market picked from a ranking also names its area and quarter (and, from an industry list, the industry).
            intent.industry_code = payload.get("industry_code") or intent.industry_code
            response = self._run(owner, bridge, intent, area_code=payload.get("area_code"), period=payload.get("period"))
        elif kind == "area" and pending.get("industry_rank_question"):
            response = self._industry_rank(owner, bridge, _action_classification(pending), last,
                                           area_code=payload.get("area_code"))
        elif kind == "industry" and pending.get("site_costs_question"):
            response = self._site_costs(owner, bridge, _action_classification(pending), last, None,
                                        industry_code=payload.get("industry_code"))
        elif kind == "industry" and pending.get("seoul_opinion"):
            response = self._seoul_opinion(owner, bridge, _action_classification(pending), last,
                                           industry_code=payload.get("industry_code"))
        elif kind == "industry" and pending.get("ranking_question"):
            response = self._ranking(owner, bridge, _action_classification(pending), last,
                                     industry_code=payload.get("industry_code"))
        elif kind == "industry":
            intent.industry_code = payload.get("industry_code")
            response = self._run(owner, bridge, intent)
        elif kind == "area":
            response = self._run(owner, bridge, intent, area_code=payload.get("area_code"),
                                 period=payload.get("period") or intent.period_code)
        elif kind == "comparison_area":
            intent.comparison_area_code = payload.get("area_code")
            if "comparison" not in intent.topics:
                intent.topics = [*intent.topics, "comparison"]
            response = self._run(owner, bridge, intent)
        elif kind == "handoff":
            response = self._finish(templates.marketing("handoff") if payload.get("domain") == "marketing"
                                    else templates.customer(), intent.classification)
        else:
            raise HTTPException(422, "알 수 없는 선택입니다.")
        self.history.add(owner, None, None, {**response, "action": payload})
        return response

    # Turn logic ------------------------------------------------------------
    def _respond(self, owner, bridge, cls: dict, last: dict) -> dict:
        turn, domain = cls["turn_type"], cls["domain"]
        if domain == "customer" and turn != "out_of_scope":
            return self._finish(templates.customer(), cls)
        if domain == "marketing":
            return self._finish(templates.marketing(turn), cls)
        costs_said, slots_now = site_costs.parse(cls.get("text")), cls.get("user_slots") or cls["slots"]
        waiting = (last.get("pending") or {}).get("site_costs_question") and (
            cls.get("named_market") or slots_now.get("locations") or slots_now.get("industries"))
        if costs_said or site_costs.asks(cls.get("text")) or waiting:
            return self._site_costs(owner, bridge, cls, last, costs_said)
        if turn in ("out_of_scope", "smalltalk", "clarify") and cls.get("ai_reply"):
            # Short text the planner wrote and planner.safe_reply checked (no statistics, no forbidden phrases).
            return self._finish({**templates.ai_text(cls["ai_reply"], turn), "model_used": True}, cls)
        if turn == "out_of_scope":
            return self._finish(templates.out_of_scope(), cls)
        if turn == "smalltalk":
            return self._finish(templates.smalltalk(cls["text"]), cls)
        if turn == "clarify":
            return self._finish(templates.unknown(), cls)
        if turn == "personal_metric":
            return self._finish(templates.personal_metric(), cls)
        said_seoul = re.sub(r"\s", "", cls.get("text") or "")
        last_kind = (last.get("reply") or {}).get("kind")
        # Only a short correction ('아니아니 서울 전체에서'), not a new question ('서울에서 카페 매출 높은 곳').
        correcting = bool(re.match(r"아니|아뇨|아냐|그게아니라|그거말고", said_seoul)) or len(said_seoul) <= 8
        earlier = last.get("pending") or {}
        if "서울" in said_seoul and len(said_seoul) <= 14 and not (cls.get("user_slots") or cls["slots"]).get("locations") \
                and (earlier.get("opinion") or last_kind == "opinion") \
                and not re.search(r"연령|시간|요일|매출|순위|업종", said_seoul):
            # '서울 전체로 생각해줘' right after an opinion question: the same opinion for all of Seoul.
            return self._seoul_opinion(owner, bridge, cls, last)
        if "서울" in said_seoul and correcting and not cls["slots"]["locations"] and \
                not (cls.get("user_slots") or cls["slots"]).get("industries") and \
                last_kind in ("industry_rank", "ranking"):
            # '아니아니 서울 전체에서' corrects the list just shown (2026-11-08 export).
            if last_kind == "industry_rank":
                return self._industry_rank(owner, bridge, {**cls, "turn_type": "followup", "topics": ["industry_rank"],
                                                           "seoul_scope": True}, last)
            return self._ranking(owner, bridge, {**cls, "turn_type": "followup", "topics": ["ranking"],
                                                 "seoul_scope": True}, last)
        if "서울" in said_seoul and correcting and not cls["slots"]["locations"] and last_kind == "seoul_compare":
            return self._seoul_compare(cls)
        if cls.get("all_industries") and not cls["slots"]["locations"] and last and                 turn in ("unknown", "followup", "data_question"):
            # '전체 업종으로 보면?' (the suggestion button): the previous ranking or answer, every industry added up.
            if (last.get("reply") or {}).get("kind") == "ranking":
                return self._ranking(owner, bridge, {**cls, "turn_type": "followup", "topics": ["ranking"]}, last)
            if turn == "unknown":
                previous = [t for t in last.get("topics") or [] if t.startswith("sales_")]
                return self._all_industries(owner, bridge, {**cls, "turn_type": "followup",
                                                            "topics": previous or ["sales_total"]}, last)
        named_nothing = not (cls.get("user_slots") or cls["slots"]).get("locations") and not cls.get("named_market")
        if turn == "unknown" and (earlier.get("seoul_opinion") or earlier.get("seoul_focus")) and named_nothing \
                and opinions.prefers(cls.get("text")):
            # '안정적인 곳 위주로 보면?' has no statistic word, so the rules cannot place it.
            return self._seoul_opinion(owner, bridge, cls, last)
        if turn == "unknown" and _FOLLOW_REQUEST.search(cls["text"] or "") and last:
            # '추천해줘' after a conversation (the rule path, e.g. when the AI planner is off or failed): continue
            # what was being discussed instead of 'I cannot answer that' (user feedback 2026-11-08).
            if (last.get("reply") or {}).get("kind") == "ranking":
                return self._ranking(owner, bridge, {**cls, "turn_type": "followup", "topics": ["ranking"]}, last)
            return self._industry_rank(owner, bridge, {**cls, "turn_type": "followup", "topics": ["industry_rank"]}, last)
        if turn == "unknown":
            return self._finish(templates.unknown(repeated=(last.get("reply") or {}).get("kind") == "unknown"), cls)
        pending = last.get("pending") or {}
        no_place = not cls["slots"]["locations"]
        if turn == "seoul_overview":
            asked = set(cls.get("user_topics", cls["topics"])) & _SEOUL_TOPICS
            # Default topics, not questions: '서울은 전반적으로 어때?'
            if "매출" not in said_seoul:
                asked.discard("sales_total")
            if not re.search(r"점포|가게|몇개|경쟁|개업|폐업", said_seoul):
                asked -= {"stores_count", "stores_open_close"}
            wide = bool(re.search(r"비교|순위", said_seoul)) or ("상권" in said_seoul and "업종" in said_seoul)
            if wide and not asked & _DISTRIBUTIONS:
                return self._seoul_compare(cls)
            if not asked:
                # The model picked ages out of habit ('서울 전체 모든 상권들과 업종들로 비교해줘', 2026-11-08 export).
                earlier_topics = [t for t in last.get("topics") or [] if t in _DISTRIBUTIONS]
                if earlier.get("opinion") or last_kind == "opinion":
                    return self._seoul_opinion(owner, bridge, cls, last)
                if not (earlier_topics or re.search(r"통계|모든곳", said_seoul)):
                    return self._seoul_compare(cls)
                cls = {**cls, "topics": earlier_topics or cls["topics"]}
            return self._overview(cls)
        said_early = cls.get("user_slots") or cls["slots"]
        if pending.get("seoul_opinion") and said_early.get("industries") and not said_early.get("locations") \
                and not cls.get("named_market") and turn in ("data_question", "followup", "condition_change", "opinion"):
            # '카페로 보면?' after a Seoul-wide opinion, or the industry it asked for.
            return self._seoul_opinion(owner, bridge, cls, last)
        if turn == "ranking" and _ASKS_A_VIEW.search(said_seoul) and not _BY_FIGURE.search(said_seoul) \
                and named_nothing and not cls["slots"]["locations"] and not cls["slots"].get("excluded_locations") \
                and not cls.get("near"):
            turn, cls = "opinion", {**cls, "turn_type": "opinion", "topics": ["opinion"]}
        if turn == "opinion":
            return self._opinion_turn(owner, bridge, cls, last)
        if cls.get("unresolved_industry") and turn in ("data_question", "condition_change", "ranking"):
            # A named industry that is in no dictionary: ask, never fall back to the saved industry silently.
            ask = None
            if turn == "ranking":
                ask = {"ranking": self._ranking_spec(cls, None), "ranking_question": True, "topics": ["ranking"],
                       "question": cls.get("text")}
            return self._finish(templates.unknown_industry(cls["unresolved_industry"]), cls, pending=ask)
        if turn == "industry_rank" or (turn == "followup" and cls["topics"] == ["industry_rank"] and no_place) \
                or (pending.get("industry_rank_question") and not no_place and turn in ("data_question", "followup")):
            # '추천 업종 3가지', a bare follow-up to it, or the place it asked for.
            return self._industry_rank(owner, bridge, cls, last)
        if turn == "ranking" or (turn == "followup" and cls["topics"] == ["ranking"] and no_place) \
                or (pending.get("ranking_question") and no_place and industry_codes(cls)):
            # '카페는?' after a ranking, or the industry the ranking asked for.
            return self._ranking(owner, bridge, cls, last)
        if {"ranking", "industry_rank"}.intersection(cls["topics"]):
            # '그럼 홍대는?' or '작년이랑 비교하면?' after a list: back to one market with what was asked.
            asked = [topic for topic in cls["topics"] if topic not in ("ranking", "industry_rank")]
            cls = {**cls, "topics": asked or list(DEFAULT_TOPICS)}
        said = cls.get("user_slots") or cls["slots"]
        quiet = not said.get("locations") and not said.get("industries") and not cls.get("named_market")
        # '그럼 평일은?' names nothing new
        if (pending.get("seoul_opinion") or pending.get("seoul_focus")) and quiet and opinions.prefers(cls.get("text")) \
                and turn != "opinion":
            # '안정적인 곳 위주로 보면?': the same Seoul-wide candidates with the weights moved.
            return self._seoul_opinion(owner, bridge, cls, last)
        focus = pending.get("seoul_focus")
        if focus and quiet and turn in ("data_question", "followup") and (
                not focus.get("from_list") or set(cls["topics"]) & _SEOUL_TOPICS):
            # '경쟁 가게는 몇 개야?' right after a Seoul-wide answer stays on Seoul. After a Seoul ranking only what
            # can be added up does: '작년이랑 비교하면?' still goes to the saved market.
            return self._seoul_follow(cls, pending["seoul_focus"])
        if pending.get("all_market") and quiet and turn in ("data_question", "followup"):
            # Continue with every industry of that market, whatever the model copied from the saved conditions.
            return self._all_industries(owner, bridge, {**cls, "slots": {**cls["slots"], "locations": []}}, last)
        if turn in ("data_question", "followup", "condition_change") and cls.get("all_industries") and (
                not industry_codes(cls) or _LEAVE_OUT.search(cls.get("text") or "")):
            return self._all_industries(owner, bridge, cls, last)
        places = self._multi_places(cls, last, bridge)
        if places is not None:
            answered = self._multi_market(owner, bridge, cls, places)
            if answered is not None:
                return answered
        intent = self._intent(cls, last, bridge)
        if isinstance(intent, dict):  # the user must choose first
            return intent
        return self._run(owner, bridge, intent)

    # Several markets in one question ------------------------------------------------
    def _multi_places(self, cls: dict, last: dict, bridge):
        """The places to read side by side, or None for the one-market flow.

        Two or more places ('합정역과 강남역의 주 고객 연령대'); one other place compared on something B5 lacks
        ('강남역이랑 연령대 비교'); or a follow-up without a place right after such an answer ('매출은?').
        """
        if cls["turn_type"] not in ("data_question", "followup", "condition_change"):
            return None
        mentions = list({m["text"]: m for m in cls["slots"]["locations"]}.values())  # 강남역 twice is one place
        if any(c.get("kind") == "district" for m in mentions for c in m["candidates"]):
            return None  # a 구 is offered as market buttons (_district_choice)
        named = cls.get("named_market")
        if named and mentions:
            return [{"text": named["name"], "candidates": [],
                     "market": {"area_code": named["area_code"], "name": named["name"]}}, *mentions]
        if len(mentions) >= 2:
            return None if self._echoes_saved_market(mentions, last, bridge) else mentions
        topics = set(cls["topics"])
        if len(mentions) == 1 and "comparison" in topics and topics & _MULTI_TOPICS:
            name = self._saved_area_name(last, bridge)
            if name and not _names_same_market(mentions[0]["text"], name):
                return [{"text": name, "candidates": []}, mentions[0]]
        markets = (last.get("pending") or {}).get("multi_markets")
        said = cls.get("user_slots") or cls["slots"]
        if markets and not said.get("locations") and not said.get("industries") and \
                cls["turn_type"] in ("followup", "data_question"):
            return [{"text": market["name"], "candidates": [], "market": market} for market in markets]
        return None

    def _saved_area_name(self, last: dict, bridge) -> str | None:
        name = (last.get("conditions") or {}).get("area_name")
        if name or bridge is None:
            return name
        try:
            return (_conditions(bridge.state()) or {}).get("area_name")
        except HTTPException:
            return None

    def _multi_market(self, owner, bridge, cls: dict, mentions: list[dict]) -> dict | None:
        """Each place's own cards, read with the saved industry and quarter; the saved conditions stay."""
        try:
            state = bridge.state()
        except HTTPException:
            return None
        if not state.get("conditions_confirmed"):
            return None  # no quarter or catalogue chosen yet: the one-market flow sets them up first
        selection, profile = dict(state["analysis_selection"]), dict(state["profile"])
        codes = industry_codes(cls)
        names = {c["code"]: c["name"] for m in cls["slots"].get("industries") or [] for c in m["candidates"]}
        if len(codes) == 1 and codes[0] != profile["industry"]["code"]:
            profile["industry"] = {"code": codes[0], "name": names[codes[0]]}
            selection["industry_code"] = codes[0]
        period = cls["slots"]["period"]["period_code"]
        if period and period != selection.get("period"):
            selection.update(period=period, period_label=period_label(period))
        saved = {"area_code": state["analysis_selection"].get("area_code"),
                 "area_name": state["analysis_selection"].get("area_name")}
        try:
            markets, missing = multi.resolve(self._source(), mentions, saved)
        except Exception as error:  # source pages missing: the one-market flow still answers
            _log.warning("multi-market places failed: %s", type(error).__name__)
            return None
        if len(markets) < 2:
            return None
        topics = [t for t in cls["topics"] if t in multi._NEEDS] or ["sales_total", "stores_count", "population"]
        cards = multi.market_cards(markets, selection, profile, topics)
        lead = [line for line in [multi.missing_line(missing), *multi.lead_lines(cards)] if line]
        no_data = multi.without_data(cards, markets, topics)
        if no_data:
            # Nothing to set against the other market: '노량진역이 훨씬 높아요' was written with no 강남역 card (2026-11-08 export).
            shown = [card for card in cards if card.get("market") not in no_data or card.get("status") == "available"]
            answer = templates.data_answer(shown, cls)
            lines = answer["text"].split("\n")
            answer["text"] = "\n".join(lines[:1] + [multi.no_data_line(no_data, profile["industry"]["name"])] + lines[1:])
            answer["suggestions"] = [f"{no_data[0]}에서는 어떤 업종 매출이 커?", *answer["suggestions"]][:3]
            return self._finish({**answer, "kind": "multi_market", "model_used": False}, cls, state=state, cards=shown, topics=topics)
        fallback = templates.data_answer(cards, cls)
        if lead:
            lines = fallback["text"].split("\n")
            fallback["text"] = "\n".join(lines[:1] + lead + lines[1:])
        reply = self._write(cards, {**cls, "multi_markets": [market["name"] for market in markets]}, fallback=fallback)
        if missing and reply.get("model_used"):
            lines = reply["text"].split("\n")
            reply["text"] = "\n".join(lines[:1] + [multi.missing_line(missing)] + lines[1:])
        reply = {**reply, "kind": "multi_market"}
        pending = {"topics": topics, "location": None, "industry_code": None, "business_status": None,
                   "period_code": None, "comparison_hint": None, "question": cls.get("text"), "opinion": False,
                   "multi_markets": markets}
        return self._finish(reply, cls, state=state, cards=cards, topics=topics, pending=pending)

    def _district_choice(self, bridge, cls: dict, place: dict, pending: dict) -> dict:
        """Markets of one 구 as buttons, those with sales for the industry first (no district total is made)."""
        try:
            state = bridge.state()
        except HTTPException:
            state = None
        profile = (state or {}).get("profile") or {}
        industry = pending.get("industry_code") or (profile.get("industry") or {}).get("code")
        names = {c["code"]: c["name"] for m in cls["slots"].get("industries") or [] for c in m["candidates"]}
        industry_name = names.get(industry) or ((profile.get("industry") or {}).get("name")
                                               if (profile.get("industry") or {}).get("code") == industry else None)
        source = self._source()
        try:
            if industry:
                result = rank_sales(source, RankingRequest(industry_code=industry, district_codes=frozenset({place["district_code"]}),
                                                           district_labels=(place["label"],), limit=12))
                markets = [item for item in result.get("items", [])]
                period = result.get("period")
                industry_name = industry_name or result.get("industry_name")
            else:
                markets = order_markets(source, [a for a in source.areas().values()
                                                 if a.get("district_code") == place["district_code"]])
                period = None
        except Exception as error:  # source pages missing: fall back to asking for a station
            _log.warning("district markets failed: %s", type(error).__name__)
            markets = []
        actions = []
        for market in markets:
            selectable = market.get("selectable", market.get("boundary_identity_status") == "code_name_match")
            if not (selectable and market.get("neighborhood_code") and market.get("district_code")):
                continue
            payload = {"type": "location", "kind": "neighborhood", "district_code": market["district_code"],
                       "neighborhood_code": market["neighborhood_code"], "area_code": market["area_code"]}
            if period:
                payload["period"] = period
            if industry:
                payload["industry_code"] = industry
            actions.append({"label": market["name"], "payload": payload})
            if len(actions) >= 6:
                break
        if not actions:
            return self._finish(templates.district_only(place["label"]), cls, state=state, pending=pending)
        return self._finish(templates.district_markets(place["label"], industry_name, actions), cls, state=state,
                            pending={**pending, "industry_code": industry})

    def _intent(self, cls: dict, last: dict, bridge=None):
        pending = last.get("pending") or {}
        comparison = "comparison" in cls["topics"]
        topics = list(cls["topics"])
        if cls["turn_type"] == "condition_change" or (cls.get("topics_defaulted") and pending.get("topics")):
            topics = pending.get("topics") or last.get("topics") or list(DEFAULT_TOPICS)
            if comparison and "comparison" not in topics:
                topics.append("comparison")
        intent = Intent(topics=topics, classification=cls, period_code=cls["slots"]["period"]["period_code"],
                        business_status=cls["slots"]["business_status"] or pending.get("business_status"),
                        condition_change=cls["turn_type"] == "condition_change")
        mentions = cls["slots"]["locations"]
        if comparison and len(mentions) == 2 and \
                mentions[0]["candidates"][0]["name"] == mentions[1]["candidates"][0]["name"]:
            mentions = mentions[1:]  # the planner put 강남역 in both place and compare_place
        if comparison and len(mentions) >= 2:
            intent.comparison_hint = mentions[1]["candidates"][0]["name"]
            mentions = mentions[:1]
        elif comparison and len(mentions) == 1 and self._market_chosen(last, bridge):
            # '강남역이랑 비교하면?' while a market is chosen: 강남역 is what to compare with, not a new base.
            intent.comparison_hint = mentions[0]["candidates"][0]["name"]
            mentions = []
        if mentions and self._echoes_saved_market(mentions, last, bridge):
            mentions = []  # the planner repeated '연남동(홍대)' while it is chosen: the same market
        if mentions:
            if len(mentions) > 1 or len(mentions[0]["candidates"]) > 1:
                options = [c for m in mentions for c in m["candidates"]]
                reply = templates.choose_location(mentions[0]["text"], options)
                return self._finish(reply, cls, pending=self._pending(intent, topics, cls))
            place = mentions[0]["candidates"][0]
            payload = location_payload(place)
            if payload is None:
                # A 구: offer its markets with data instead of asking for a station (user feedback 2026-11-08).
                return self._district_choice(bridge, cls, place, self._pending(intent, topics, cls))
            intent.location, intent.location_label = payload, place["label"]
        else:
            intent.location = pending.get("location")
        named = cls.get("named_market")
        if named:
            intent.location = {"kind": "area", "district_code": named["district_code"],
                               "neighborhood_code": named["neighborhood_code"]}
            intent.location_label, intent.area_code = named["name"], named["area_code"]
        codes = industry_codes(cls)
        if len(codes) > 1 and not comparison:
            rows = [c for m in cls["slots"]["industries"] for c in m["candidates"]]
            return self._finish(templates.choose_industry(rows), cls, pending=self._pending(intent, topics, cls))
        intent.industry_code = codes[0] if codes else pending.get("industry_code")
        return intent

    @staticmethod
    def _echoes_saved_market(mentions: list[dict], last: dict, bridge) -> bool:
        name = (last.get("conditions") or {}).get("area_name")
        if not name and bridge is not None:
            try:
                name = (_conditions(bridge.state()) or {}).get("area_name")
            except HTTPException:
                name = None
        if not name:
            return False
        if len(mentions) == 1:
            return name.startswith(mentions[0]["text"]) and len(mentions[0]["text"]) >= 2
        # Several pieces of the one name ('연남동' + '홍대' from '연남동(홍대)'); '홍대' alone may mean 홍대입구역.
        return all(len(m["text"]) >= 2 and m["text"] in name for m in mentions)

    @staticmethod
    def _market_chosen(last: dict, bridge) -> bool:
        """A market is already saved (the previous turn may have been small talk that reported no conditions)."""
        if (last.get("conditions") or {}).get("area_code"):
            return True
        if bridge is None:
            return False
        try:
            state = bridge.state()
        except HTTPException:
            return False
        return bool(state.get("conditions_confirmed") and (state.get("analysis_selection") or {}).get("area_code"))

    def _pending(self, intent: Intent, topics, cls) -> dict:
        codes = industry_codes(cls)
        return {"topics": topics, "location": intent.location,
                "industry_code": codes[0] if len(codes) == 1 else None,
                "business_status": intent.business_status, "period_code": intent.period_code,
                "comparison_hint": intent.comparison_hint, "question": cls.get("text"), "opinion": intent.opinion}

    # Ranking ------------------------------------------------------------------
    @staticmethod
    def _ranking_spec(cls: dict, previous: dict | None) -> dict:
        """Scope and exclusions from this message, or from the previous ranking for '카페는?'."""
        if cls["turn_type"] != "ranking" and previous:
            spec = dict(previous)
            if cls["slots"]["period"]["period_code"]:
                spec["period"] = cls["slots"]["period"]["period_code"]
            return spec
        districts = {}
        for mention in cls["slots"]["locations"]:
            for place in mention["candidates"]:
                if place.get("district_code"):
                    districts[place["district_code"]] = place.get("district_name") or place["district_code"]
        exclusion = Exclusion.from_mentions(cls["slots"].get("excluded_locations") or [])
        return {"district_codes": sorted(districts), "district_labels": [districts[code] for code in sorted(districts)],
                "exclusion": exclusion.to_dict() if exclusion else None,
                "period": cls["slots"]["period"]["period_code"], "industry_code": None}

    def _ranking(self, owner, bridge, cls: dict, last: dict, *, industry_code: str | None = None) -> dict:
        pending = last.get("pending") or {}
        spec = self._ranking_spec(cls, pending.get("ranking"))
        try:
            state = bridge.state()
        except HTTPException:
            state = None
        profile = (state or {}).get("profile") or {}
        rows = [c for m in cls["slots"]["industries"] for c in m["candidates"]]
        codes = list(dict.fromkeys(row["code"] for row in rows))
        if industry_code is None and len(codes) > 1:
            return self._finish(templates.choose_industry(rows), cls, state=state,
                                pending={"ranking": spec, "ranking_question": True, "topics": ["ranking"],
                                         "question": cls.get("text")})
        # Every industry when asked, or when the ranking or answer before was about every industry and no
        # industry is named now ('강남역 모든 상권의 매출' -> '주변에서 가장 높은 곳은?').
        every = bool(cls.get("all_industries")) or (
            (bool(spec.get("all_industries")) or bool(pending.get("all_market"))) and not codes and industry_code is None)
        industry = None if every else (industry_code or (codes[0] if codes else None) or spec.get("industry_code")
                                       or (profile.get("industry") or {}).get("code"))
        carried = not every and not codes and industry_code is None  # the saved industry, not the user's words
        if cls.get("seoul_scope") and not cls["slots"]["locations"] and cls["turn_type"] != "ranking":
            spec = {**spec, "near": None, "district_codes": [], "district_labels": []}
        if cls.get("near") and cls["turn_type"] == "ranking":
            near = self._near(cls, state)
            if near:
                spec = {**spec, "near": near, "district_codes": [], "district_labels": []}
        if industry is None and not every:
            return self._finish(templates.need_industry(), cls, state=state,
                                pending={"ranking": spec, "ranking_question": True, "topics": ["ranking"],
                                         "question": cls.get("text")})
        names = {row["code"]: row["name"] for row in rows}
        if (profile.get("industry") or {}).get("code"):
            names.setdefault(profile["industry"]["code"], profile["industry"]["name"])
        exclusion = Exclusion.from_dict(spec.get("exclusion"))
        request = RankingRequest(industry_code=industry, industry_name=ALL_INDUSTRIES_NAME if every else names.get(industry),
                                 period=spec.get("period"), district_codes=frozenset(spec.get("district_codes") or ()),
                                 district_labels=tuple(spec.get("district_labels") or ()), exclusion=exclusion,
                                 near=spec.get("near"))
        try:
            result = rank_sales(self._source(), request)
        except Exception as error:  # missing or unverifiable source pages: never guess a ranking
            _log.warning("sales ranking failed: %s", type(error).__name__)
            return self._finish(templates.data_unavailable("매출 순위 자료를 불러오지 못했습니다."), cls, state=state)
        if result.get("status") != "available":
            scope = "·".join(request.district_labels) or "서울 전체"
            return self._finish(templates.ranking_unavailable(result, scope, names.get(industry)), cls, state=state)
        card = ranking_card(result)
        reply = templates.ranking_answer(result, card, cls, exclusion.describe() if exclusion else "")
        if carried:
            reply["suggestions"] = ["전체 업종으로 보면?"]  # the industry came from earlier, not this question
        # The buttons open one market with the ranked industry and quarter; '카페는?' re-ranks with this scope.
        after = {"topics": list(DEFAULT_TOPICS), "location": None, "industry_code": industry,
                 "business_status": cls["slots"].get("business_status") or profile.get("business_status"),
                 "period_code": result["period"], "comparison_hint": None, "question": None,
                 "ranking": {**spec, "industry_code": industry, "all_industries": every}}
        if not spec.get("district_codes") and not spec.get("near"):
            after["seoul_focus"] = {"industry_code": industry, "industry_name": names.get(industry), "from_list": True}
        return self._finish(reply, cls, state=state, cards=[card], topics=["ranking"], pending=after)

    def _near(self, cls: dict, state) -> dict | None:
        """The market a '주변' question is around: the place named, else the saved market, with its coordinates."""
        current = _conditions(state)
        saved = {"area_code": current["area_code"], "area_name": current["area_name"]} \
            if current and current.get("area_code") else None
        target = cls["slots"]["locations"][:1] or ([{"text": saved["area_name"], "candidates": []}] if saved else [])
        if not target:
            return None
        source = self._source()
        try:
            markets, _missing = multi.resolve(source, target, saved)
        except Exception as error:  # the ranking still answers, for the district as before
            _log.info("near market skipped: %s", type(error).__name__)
            return None
        if not markets:
            return None
        area = source.areas().get(markets[0]["area_code"]) or {}
        if area.get("latitude") is None or area.get("longitude") is None:
            return None
        return {"lat": area["latitude"], "lon": area["longitude"], "km": NEAR_KM, "exclude": markets[0]["area_code"],
                "label": markets[0]["name"]}

    @staticmethod
    def _industries_card(source, market: dict, period, cls: dict, number: int) -> dict | None:
        """The market's industries by sales as one card ('커피-음료 말고 다른 분석': without 커피-음료)."""
        said = cls.get("user_slots") or cls.get("slots") or {}
        excluded = [c["code"] for m in said.get("industries") or [] for c in m["candidates"]] \
            if _LEAVE_OUT.search(cls.get("text") or "") else []
        try:
            result = rank_industries(source, market["area_code"], period=period, limit=5, excluded_codes=excluded)
        except Exception as error:
            _log.info("industries card skipped: %s", type(error).__name__)
            return None
        if result.get("status") != "available":
            return None
        card = industry_rank_cards(result)[1]
        listed = ", ".join(f"{item['industry_name']} {item['value']:,}원" for item in result["items"])
        left_out = f" {josa(', '.join(result['excluded']), '은')} 뺐습니다." if result.get("excluded") else ""
        return {**card, "id": f"F{number}",
                "text": f"업종별로는 {listed} 순으로 매출이 큽니다.{left_out}"}

    def _all_industries(self, owner, bridge, cls: dict, last: dict) -> dict:
        """'강남역 주말 모든 상권의 매출': every industry of one market added up. The saved conditions stay."""
        try:
            state = bridge.state()
        except HTTPException:
            state = None
        current = _conditions(state)
        saved = {"area_code": current["area_code"], "area_name": current["area_name"]} \
            if current and current.get("area_code") else None
        pending = last.get("pending") or {}
        mentions = [m for m in cls["slots"]["locations"][:1]
                    if not any(c.get("kind") == "district" for c in m["candidates"])]
        source = self._source()
        if mentions:
            try:
                markets, _missing = multi.resolve(source, mentions, saved)
            except Exception as error:
                _log.warning("all-industries market failed: %s", type(error).__name__)
                markets = []
            if not markets:
                return self._finish(templates.no_market_for_place(), cls, state=state)
            market = markets[0]
        elif pending.get("all_market"):
            market = pending["all_market"]
        elif saved:
            market = {"area_code": saved["area_code"], "name": saved["area_name"]}
        else:
            return self._finish(templates.need_location(), cls, state=state)
        topics = [t for t in cls["topics"] if t in _SEOUL_TOPICS] or ["sales_total"]
        period = cls["slots"]["period"]["period_code"] or (current or {}).get("period")
        try:
            cards = summed_cards(source, topics, period=period, area_code=market["area_code"], area_name=market["name"])
        except Exception as error:  # missing or unverifiable source pages: never guess a total
            _log.warning("all-industries sums failed: %s", type(error).__name__)
            return self._finish(templates.data_unavailable("이 상권의 업종별 매출 자료를 불러오지 못했어요."), cls, state=state)
        if not cards:
            return self._finish(templates.data_unavailable("이 상권에는 합칠 업종별 매출 자료가 없어요."), cls, state=state)
        if topics == ["sales_total"]:
            card = self._industries_card(source, market, period, cls, len(cards) + 1)
            if card:
                cards.append(card)
        reply = {**self._write(cards, {**cls, "all_industries": True}), "kind": "all_industries"}
        after = {"topics": topics, "location": None, "industry_code": None, "business_status": None, "period_code": None,
                 "comparison_hint": None, "question": cls.get("text"), "opinion": False, "all_market": market}
        return self._finish(reply, cls, state=state, cards=cards, topics=topics, pending=after)

    # Industries inside one market ---------------------------------------------
    def _source(self):
        if self.ranking_source is None:
            self.ranking_source = SeoulSalesSource()
        return self.ranking_source

    def _industry_rank(self, owner, bridge, cls: dict, last: dict, *, area_code: str | None = None) -> dict:
        """'추천해줄 만한 업종 3가지': industries of one market by quarterly sales and store count."""
        pending = last.get("pending") or {}
        previous = pending.get("industry_rank") or {}
        try:
            state = bridge.state()
        except HTTPException:
            state = None
        selection = (state or {}).get("analysis_selection") if (state or {}).get("conditions_confirmed") else None
        selection = selection or {}
        # A new question starts fresh; a follow-up, a button or the place it asked for keeps its count and exclusions.
        carried = previous if cls["turn_type"] != "industry_rank" else {}
        count = cls["slots"].get("count") or carried.get("count") or INDUSTRY_COUNT
        period = cls["slots"]["period"]["period_code"] or carried.get("period")
        excluded = sorted({c["code"] for m in cls["slots"].get("excluded_industries") or [] for c in m["candidates"]}) \
            or carried.get("excluded") or []
        seoul = area_code is None and not cls["slots"]["locations"] and (
            bool(cls.get("seoul_scope")) or bool(carried.get("seoul")))
        spec = {"count": count, "period": period, "excluded": excluded, "seoul": seoul}
        ask = {"industry_rank": spec, "industry_rank_question": True, "topics": ["industry_rank"],
               "question": cls.get("text")}
        source = self._source()
        try:
            if seoul:
                pass  # '서울 전체에서 매출 높은 업종': every market of Seoul added up per industry
            elif area_code is None:
                mentions = cls["slots"]["locations"]
                if mentions:
                    areas = order_markets(source, areas_for_mentions(source, mentions))
                    # The saved market, or the one picked for the previous industry list ('추천해줘' again).
                    known = {selection.get("area_code"), previous.get("area_code")} - {None}
                    saved = next((a for a in areas if a["area_code"] in known), None)
                    if saved is not None or len(areas) == 1:
                        area_code = (saved or areas[0])["area_code"]
                    elif areas:
                        actions = [{"label": f"{a['name']} ({a['district_name']})" if a.get("district_name") else a["name"],
                                    "payload": {"type": "area", "area_code": a["area_code"]}} for a in areas[:8]]
                        return self._finish(templates.choose_market(actions), cls, state=state, pending=ask)
                    else:
                        return self._finish(templates.no_market_for_place(), cls, state=state, pending=ask)
                elif previous.get("area_code") and cls["turn_type"] != "industry_rank":
                    area_code = previous["area_code"]
                elif selection.get("area_code"):
                    area_code, period = selection["area_code"], period or selection.get("period")
                else:
                    return self._finish(templates.need_location(), cls, state=state, pending=ask)
            result = rank_industries(source, None if seoul else area_code, period=period, limit=count,
                                     excluded_codes=excluded)
        except Exception as error:  # missing or unverifiable source pages: never guess a ranking
            _log.warning("industry ranking failed: %s", type(error).__name__)
            return self._finish(templates.data_unavailable("업종별 매출 자료를 불러오지 못했습니다."), cls, state=state)
        if result.get("status") != "available":
            reply = (templates.period_unavailable(result["period_label"]) if result.get("status") == "period_unavailable"
                     else templates.data_unavailable(result.get("message") or "이 상권의 업종별 추정매출 자료가 없습니다."))
            return self._finish(reply, cls, state=state)
        cards = industry_rank_cards(result)
        # Fixed wording only: in live tests HCX-005 turned this list into advice ('한식음식점을 여시는 것을 추천해요').
        reply = {**templates.industry_rank_answer(result, cards, cls), "model_used": False}
        same_market = selection.get("area_code") == area_code
        actions = []
        for item in result["items"]:
            if same_market:
                payload = {"type": "industry", "industry_code": item["industry_code"]}
            elif result.get("selectable") and result.get("neighborhood_code"):
                payload = {"type": "location", "kind": "neighborhood", "district_code": result["district_code"],
                           "neighborhood_code": result["neighborhood_code"], "area_code": area_code,
                           "period": result["period"], "industry_code": item["industry_code"]}
            else:
                continue
            actions.append({"label": f"{item['industry_name']} 자세히", "payload": payload})
        reply["actions"] = actions
        after = {"topics": list(DEFAULT_TOPICS), "location": None, "industry_code": None,
                 "business_status": cls["slots"].get("business_status"), "period_code": result["period"],
                 "comparison_hint": None, "question": None,
                 "industry_rank": {**spec, "area_code": area_code, "period": result["period"]}}
        return self._finish(reply, cls, state=state, cards=cards, topics=["industry_rank"], pending=after)

    def _run(self, owner, bridge, intent: Intent, *, area_code=None, period=None) -> dict:
        cls = intent.classification
        area_code = area_code or intent.area_code
        try:
            state = bridge.state()
            profile = state["profile"]
            before = _conditions(state)
            if (intent.location is not None and intent.location_label and before
                    and _names_same_market(intent.location_label, before.get("area_name"))):
                # '상도역 연령층은?' while 상도역 1번 상권 is chosen: the same market, not a new location.
                intent.location = None
            # 1. Location and industry ------------------------------------------
            if profile is None and intent.location is None:
                return self._finish(templates.need_location(), cls, pending=self._intent_pending(intent))
            if profile is None and intent.industry_code is None:
                asked = ((self.history.last(owner) or {}).get("reply") or {}).get("kind") == "need_industry"
                return self._finish(templates.need_industry(repeated=asked, said=cls.get("text") or ""), cls,
                                    pending=self._intent_pending(intent))
            changed_location = intent.location is not None and not _same_location(profile, intent.location)
            changed_industry = intent.industry_code is not None and (
                profile is None or profile["industry"]["code"] != intent.industry_code)
            # '그럼 카페는?' changes only the industry: keep looking at the same market if it still fits.
            keep_area = None if changed_location else (state.get("analysis_selection") or {}).get("area_code")
            if changed_location or changed_industry:
                # Changing a saved condition is announced; setting the first one is not.
                intent.condition_change = intent.condition_change or profile is not None
                status = intent.business_status or (profile or {}).get("business_status") or _DEFAULT_STATUS
                industry = intent.industry_code or profile["industry"]["code"]
                bridge.save_profile(intent.location if changed_location else None, industry, status, state["revision"])
                state = bridge.state()
            # 2. Market area and quarter -------------------------------------------
            selection = state["analysis_selection"] or {}
            want_period = period or intent.period_code
            if area_code or not state["conditions_confirmed"] or (want_period and selection.get("period") != want_period):
                options = bridge.analysis_options()
                candidates = [c for c in options.get("candidates", []) if not c.get("selection_blocked_reason")]
                if area_code:
                    chosen = next((c for c in candidates if c["area_code"] == area_code), None)
                elif state["conditions_confirmed"] and selection.get("area_code"):
                    chosen = next((c for c in candidates if c["area_code"] == selection["area_code"]), None)
                else:
                    chosen = next((c for c in candidates if keep_area and c["area_code"] == keep_area), None) \
                        or self._auto_area(candidates)
                if chosen is None:
                    if not candidates:
                        return self._finish(templates.data_unavailable(options.get("message") or "분석할 공식 상권 후보가 없습니다."), cls,
                                            state=state)
                    asked = ((self.history.last(owner) or {}).get("reply") or {}).get("kind") == "choose_area"
                    return self._finish(templates.choose_area(options, want_period, repeated=asked), cls, state=state,
                                        pending=self._intent_pending(intent))
                available = chosen.get("available_periods") or []
                if want_period and want_period not in available:
                    return self._finish(templates.period_unavailable(want_period[:4] + "년 " + want_period[4] + "분기"),
                                        cls, state=state, pending=self._intent_pending(intent))
                if not available:
                    return self._finish(templates.data_unavailable("이 상권·업종에는 확인된 자료 기간이 없습니다."), cls, state=state)
                bridge.save_selection(chosen["area_code"], want_period or max(available), state["revision"],
                                      options["catalog_version"])
                state = bridge.state()
            # 3. Snapshot, comparison, cards ---------------------------------------
            snapshot = self._snapshot(owner, bridge, state)
            if "comparison" in intent.topics:
                reply = self._comparison(bridge, snapshot, intent)
                if reply is not None:
                    return self._finish(reply, cls, state=state, pending=self._intent_pending(intent))
            if all(result.get("status") == "error" for result in snapshot["results"].values()):
                message = next(iter(snapshot["results"].values())).get("message", "자료를 불러오지 못했습니다.")
                return self._finish(templates.data_unavailable(message), cls, state=state)
            if intent.opinion:
                return self._opinion_answer(owner, snapshot, state, intent, before)
            all_cards = cards_from_snapshot(snapshot)
            if "area_profile" in intent.topics:
                profile = self._profile_card(snapshot)
                if profile is not None:
                    all_cards.append({**profile, "id": f"F{len(all_cards) + 1}"})
                elif intent.topics == ["area_profile"]:
                    return self._finish(templates.data_unavailable("이 상권의 직장인구·상주인구 자료가 아직 없어요."), cls, state=state)
            cards = select_cards(all_cards, intent.topics)
            # Missing data is never a dead end: show the nearest data this market has (user feedback 2026-11-08).
            cards, missing, substitutes = _with_substitutes(all_cards, cards, intent.topics)
            after = _conditions(state)
            # '이번에는 …' only when the chosen market, industry or quarter really changed.
            changed = before is not None and after is not None and before != after
            # Say the conditions again only when they are new to this conversation; the bar above the chat shows them.
            last = self.history.last(owner) or {}
            repeated = ((last.get("reply") or {}).get("kind") == "data_answer"
                        and last.get("conditions") == after and not changed)
            # The substitute line promises those cards, so a model text that leaves them out is not used.
            promised = [card["id"] for card in cards if card["topic"] in substitutes]
            reply = self._write(cards, cls, show_conditions=not repeated, changed=changed, required=promised)
            extra, tail = [], []
            nearby_line, nearby = self._nearby_with_sales(snapshot, cards)
            if nearby_line and any(turn["response"].get("conditions") == after and templates.NO_SALES_MARK in
                                   ((turn["response"].get("reply") or {}).get("text") or "")
                                   for turn in self.history.recent(owner, 6)):
                # Already said in this conversation about this same market: keep the buttons, point at them briefly.
                nearby_line = None
                if not any(card.get("status") == "available" for card in cards if card["topic"] != "conditions"):
                    tail.append(templates.NEARBY_POINTER)
            if nearby_line:
                extra.append(nearby_line)
            if nearby:
                reply["actions"] = [*(reply.get("actions") or []), *nearby]
            if substitutes:
                labels = {card["topic"]: templates.substitute_label(card) for card in cards if card["topic"] in substitutes}
                extra.append(templates.substitute_line(missing, substitutes, already_said=bool(nearby_line), labels=labels))
            if extra:
                lines = reply["text"].split("\n")
                at = 1 if not repeated and lines else 0  # right after the conditions sentence
                reply["text"] = "\n".join(lines[:at] + extra + lines[at:])
            if tail:
                reply["text"] = "\n".join([reply["text"], *tail])
            if "slots" in cls and cls["slots"]["locations"] and not industry_codes(cls):
                # '강남역 주말 매출은?' kept the saved industry: offer every industry right there.
                reply["suggestions"] = ["전체 업종으로 보면?", *(reply.get("suggestions") or [])][:3]
            return self._finish(reply, cls, state=state, cards=cards, topics=intent.topics)
        except HTTPException as error:
            if error.status_code == 409:
                return self._finish(templates.data_unavailable("다른 화면에서 조건이 바뀌었어요. 한 번 더 말씀해 주세요."), cls)
            return self._finish(templates.data_unavailable(error_message(error)), cls)

    # Opinions and Seoul as a whole -------------------------------------------------
    def _opinion_turn(self, owner, bridge, cls: dict, last: dict) -> dict:
        """'두 곳 중 어디가 나아?', '너라면 여기 차릴 거야?': settle the market(s), then answer with a view."""
        spoken = re.sub(r"\s", "", cls.get("text") or "")
        earlier = last.get("pending") or {}
        if (earlier.get("seoul_opinion") or earlier.get("seoul_focus")) and not cls.get("named_market") \
                and not (cls.get("user_slots") or cls["slots"]).get("locations") and opinions.prefers(cls.get("text")):
            return self._seoul_opinion(owner, bridge, cls, last)
        if not cls.get("named_market") and not (cls.get("user_slots") or cls["slots"]).get("locations") and _OPEN_WHERE.search(spoken) \
                and not _CHOSEN.search(spoken):
            # Nothing was named to choose between, whatever the model copied from the earlier turns.
            return self._seoul_opinion(owner, bridge, cls, last)
        mentions = list(cls["slots"]["locations"])[:2]
        try:
            state = bridge.state()
        except HTTPException:
            state = None
        area_name = (_conditions(state) or {}).get("area_name")
        if len(mentions) == 2 and area_name:
            # The saved market stays the base; the other one is what it is compared with.
            mentions.sort(key=lambda m: not any(_names_same_market(c.get("label") or c.get("name"), area_name)
                                                for c in m["candidates"]))
        topics = ["comparison"] if len(mentions) == 2 else list(DEFAULT_TOPICS)
        plan = {**cls, "turn_type": "data_question", "topics": topics,
                "slots": {**cls["slots"], "locations": mentions}}
        intent = self._intent(plan, last, bridge)
        if isinstance(intent, dict):  # a choice first (which 강남?); the button keeps the opinion going
            if intent.get("pending") is not None:
                intent["pending"]["opinion"] = True
            return intent
        intent.opinion = True
        previous = (last.get("pending") or {}).get("multi_markets") or []
        others = [market for market in previous if market["area_code"] != (_conditions(state) or {}).get("area_code")]
        if not mentions and len(previous) == 2 and len(others) == 1:
            # '둘 중 어디가 나아?' after '합정역과 강남역의 연령대': the saved one against the other.
            intent.comparison_area_code = others[0]["area_code"]
            intent.topics = ["comparison"]
        elif not mentions and state and state.get("conditions_confirmed"):
            snapshot = self.snapshots.get(SnapshotCache.key(owner, state))
            if snapshot and snapshot.get("comparison_area_code"):
                # '두 지역 중 어디?' right after a comparison: the two markets just compared.
                intent.comparison_area_code = snapshot["comparison_area_code"]
                intent.topics = ["comparison"]
        return self._run(owner, bridge, intent)

    def _opinion_answer(self, owner, snapshot: dict, state: dict, intent: Intent, before) -> dict:
        cls = intent.classification
        selection, industry = snapshot["selection"], snapshot["profile"]["industry"]
        figures = [opinions.figures_from_snapshot(snapshot)]
        comparison = snapshot["results"].get("comparison") or {}
        if "comparison" in intent.topics and snapshot.get("comparison_area_code") and comparison.get("status") != "error":
            figures.append(opinions.figures_from_comparison(comparison, figures[0], snapshot["comparison_area_code"]))
        opinions.add_source_figures(self._source(), figures, industry["code"], selection["period"])
        for figure in figures:
            opinions.derive(figure)
        plan = opinions.weights_for(industry["code"], cls.get("text") or "", figures)
        opinions.add_benchmarks(self._source(), figures, industry["code"], selection["period"], plan)
        card = opinions.opinion_card(figures, industry_name=industry["name"],
                                     period_label=selection.get("period_label") or selection["period"], plan=plan)
        card["id"] = "F2"
        cards = [cards_from_snapshot(snapshot)[0], card]
        after = _conditions(state)
        changed = before is not None and after is not None and before != after
        last = self.history.last(owner) or {}
        repeated = ((last.get("reply") or {}).get("kind") in ("data_answer", "opinion")
                    and last.get("conditions") == after and not changed)
        # Follow-ups ('점포 수는?') go back to one market's data, not to another comparison or opinion.
        after_pending = {**self._intent_pending(intent), "topics": list(DEFAULT_TOPICS), "comparison_hint": None,
                         "opinion": False}
        if card["status"] != "available":
            reply = templates.opinion_answer(cards, ["판단에 쓸 매출·점포 자료가 부족해서 의견을 드리기 어려워요. "
                                                     "다른 상권이나 업종으로 물어봐 주세요."], show_conditions=not repeated)
            return self._finish(reply, cls, state=state, cards=cards, topics=["opinion"], pending=after_pending)
        lines = opinions.fixed_lines(figures, card["id"], plan)
        costs = self._saved_costs(owner)
        caveat = None
        if costs.get("rent") and len(figures) == 1 and figures[0].get("per_store_sales"):
            # What the user said about this site goes into the same opinion.
            numbers = site_costs.calculate(costs, figures[0]["per_store_sales"])
            cost_card = {**site_costs.card(costs, numbers, area_name=figures[0]["name"]), "id": "F3"}
            cards.append(cost_card)
            lines.append(site_costs.rent_line(costs, numbers, card_id="F3"))
            caveat = opinions.CAVEAT_KNOWN
        said_weights = opinions.weights_key(plan)
        caveat = opinions.tail(plan, shown_before=(last.get("pending") or {}).get("said_weights") == said_weights, caveat=caveat)
        after_pending["said_weights"] = said_weights
        fallback = templates.opinion_answer(cards, lines, show_conditions=not repeated, caveat=caveat)
        question = opinions.writer_question(figures, industry["name"], cls.get("text") or "")
        reply = self._write(cards, {**cls, "turn_type": "opinion", "text": question}, show_conditions=not repeated,
                            changed=changed, required=[card["id"]], fallback=fallback, opinion=True, caveat=caveat)
        return self._finish(reply, cls, state=state, cards=cards, topics=["opinion"], pending=after_pending)

    def _seoul_opinion(self, owner, bridge, cls: dict, last: dict, *, industry_code: str | None = None) -> dict:
        """'서울에서 어느 상권이 좋다고 봐?': the markets that stand best on the four criteria, with a view."""
        try:
            state = bridge.state()
        except HTTPException:
            state = None
        pending = last.get("pending") or {}
        profile = (state or {}).get("profile") or {}
        said = cls.get("user_slots") or cls["slots"]
        names = {c["code"]: c["name"] for m in said.get("industries") or [] for c in m["candidates"]}
        code = industry_code or (next(iter(names)) if len(names) == 1 else None) or pending.get("seoul_industry") \
            or (pending.get("seoul_focus") or {}).get("industry_code") or (profile.get("industry") or {}).get("code")
        ask = {"seoul_opinion": True, "topics": [], "question": cls.get("text"), "location": None, "industry_code": None,
               "business_status": None, "period_code": None, "comparison_hint": None, "opinion": False}
        if code is None:
            return self._finish(templates.need_industry(repeated=True), cls, state=state, pending=ask)
        source = self._source()
        try:
            periods = source.periods()
            period = cls["slots"]["period"]["period_code"] or (_conditions(state) or {}).get("period") or periods[-1]
            table = opinions.market_table(source, code, period)
        except Exception as error:  # no guessed recommendation
            _log.warning("seoul opinion failed: %s", type(error).__name__)
            return self._finish(templates.data_unavailable("서울 전체 상권 자료를 불러오지 못했어요."), cls, state=state)
        plan = opinions.weights_for(code, cls.get("text") or "", table)
        top, compared = opinions.best_markets(table, plan=plan)
        name = names.get(code) or next((row["industry_name"] for row in table if row.get("industry_name")), None) \
            or (profile.get("industry") or {}).get("name") or code
        if not top:
            return self._finish(templates.data_unavailable(f"서울에서 {name} 상권을 견줄 자료가 부족해요."), cls, state=state,
                                pending={**ask, "seoul_industry": code})
        label = period_label(period)
        card = {**opinions.seoul_card(top, industry_name=name, period_label=label, compared=compared, plan=plan), "id": "F2"}
        conditions = {"id": "F1", "topic": "conditions", "status": "available",
                      "text": f"분석 조건은 서울 전체 상권, {name} 업종, {label} 자료입니다.",
                      "values": [{"label": "상권", "value": "서울 전체", "unit": None},
                                 {"label": "업종", "value": name, "unit": None, "code": code},
                                 {"label": "기간", "value": label, "unit": None, "code": period}],
                      "warnings": [], "source_ref": {"analysis": "opinion_seoul"}}
        cards = [conditions, card]
        said_weights = opinions.weights_key(plan)
        shown_before = pending.get("said_weights") == said_weights
        fallback = templates.opinion_answer(cards, opinions.seoul_fixed_lines(top, "F2", plan),
                                            caveat=opinions.tail(plan, shown_before=shown_before))
        reply = self._write(cards, {**cls, "turn_type": "opinion",
                                    "text": opinions.seoul_question(name, cls.get("text") or "")},
                            required=["F2"], fallback=fallback, opinion=True,
                            caveat=opinions.tail(plan, shown_before=shown_before, places=top))
        reply["actions"] = [{"label": f"{market['name']} 자세히",
                             "payload": {"type": "location", "kind": "neighborhood", "district_code": market["district_code"],
                                         "neighborhood_code": market["neighborhood_code"], "area_code": market["area_code"],
                                         "period": period, "industry_code": code}}
                            for market in top if market.get("neighborhood_code") and market.get("district_code")]
        others = [word for word, wanted in (("카페", "CS100010"), ("한식", "CS100001"), ("치킨", "CS100007")) if wanted != code]
        reply["suggestions"] = [f"{josa(word, '으로')} 보면?" for word in others[:2]] + ["안정적인 곳 위주로 보면?"]
        return self._finish(reply, cls, state=state, cards=cards, topics=["opinion"],
                            pending={**ask, "seoul_industry": code, "said_weights": said_weights,
                                     "seoul_focus": {"industry_code": code, "industry_name": name}})

    def _seoul_compare(self, cls: dict) -> dict:
        """'서울 전체 모든 상권들과 업종들로 비교해줘': the largest markets and industries, added up by code."""
        codes = industry_codes(cls)
        names = {c["code"]: c["name"] for m in cls["slots"].get("industries") or [] for c in m["candidates"]}
        code = codes[0] if len(codes) == 1 and not cls.get("all_industries") else None
        source = self._source()
        period = cls["slots"]["period"]["period_code"]
        try:
            markets = rank_sales(source, RankingRequest(industry_code=code, period=period,
                                                        industry_name=names.get(code) if code else ALL_INDUSTRIES_NAME))
            industries = rank_industries(source, None, period=period, limit=5) if code is None else None
        except Exception as error:  # missing or unverifiable source pages: never guess a list
            _log.warning("seoul compare failed: %s", type(error).__name__)
            return self._finish(templates.data_unavailable("서울 전체 매출 자료를 불러오지 못했어요."), cls)
        if markets.get("status") != "available":
            return self._finish(templates.data_unavailable("서울 전체로 견줄 매출 자료가 없어요."), cls)
        market_card = ranking_card(markets)
        cards = [market_card]
        industry_card = None
        if industries and industries.get("status") == "available":
            industry_card = {**industry_rank_cards(industries)[1], "id": "F2"}
            cards.append(industry_card)
        reply = templates.seoul_compare(markets, market_card, industries, industry_card)
        focus = {"industry_code": code, "industry_name": names.get(code) if code else None}
        return self._finish(reply, cls, cards=cards, topics=["ranking"], pending={"seoul_focus": focus, "question": cls.get("text")})

    def _seoul_follow(self, cls: dict, focus: dict) -> dict:
        """A follow-up with no place after a Seoul-wide answer: Seoul again, or why it cannot be added up."""
        topics = [t for t in cls["topics"] if t in _SEOUL_TOPICS]
        if not topics:
            missing = next((name for topic, name in _NOT_SUMMED.items() if topic in cls["topics"]), None)
            if missing:
                return self._finish(templates.seoul_not_summed(missing), cls, pending={"seoul_focus": focus})
            topics = ["sales_total"]
        return self._overview({**cls, "topics": topics}, focus=focus)

    def _overview(self, cls: dict, focus: dict | None = None) -> dict:
        """'서울시 모든 상권의 연령층': every market's sales added up (overview.py). The saved conditions stay."""
        codes = industry_codes(cls)
        names = {c["code"]: c["name"] for m in cls["slots"].get("industries") or [] for c in m["candidates"]}
        code = codes[0] if len(codes) == 1 else (focus or {}).get("industry_code")
        if code and focus and code == focus.get("industry_code") and focus.get("industry_name"):
            names.setdefault(code, focus["industry_name"])
        topics = [t for t in cls["topics"] if t in _SEOUL_TOPICS] or ["sales_age"]
        try:
            cards = seoul_cards(self._source(), topics, industry_code=code, industry_name=names.get(code),
                                period=cls["slots"]["period"]["period_code"])
        except Exception as error:  # missing or unverifiable source pages: never guess a total
            _log.warning("seoul overview failed: %s", type(error).__name__)
            return self._finish(templates.data_unavailable("서울 전체 매출 자료를 불러오지 못했어요."), cls)
        if not cards:
            return self._finish(templates.data_unavailable("서울 전체로 합칠 매출 자료가 없어요."), cls)
        reply = {**self._write(cards, cls), "kind": "seoul_overview"}
        # Questions Seoul as a whole can answer, not the one-market ones ('경쟁 가게는 몇 개야?').
        spoken = {"sales_age": "서울 연령대별 매출은?", "sales_time": "서울 시간대별 매출은?", "sales_weekday": "서울 요일별 매출은?"}
        reply["suggestions"] = [q for topic, q in spoken.items() if topic not in topics][:2] + ["서울 전체 점포 수는?"]
        pending = {"seoul_focus": {"industry_code": code, "industry_name": names.get(code) if code else None},
                   "topics": topics, "question": cls.get("text")}
        return self._finish(reply, cls, cards=cards, topics=topics, pending=pending)

    def _nearby_with_sales(self, snapshot: dict, cards: list[dict]) -> tuple[str | None, list[dict]]:
        """When this market has no sales for the industry: say whether other quarters have it, or offer nearby
        markets that do (same station first, then the 구's larger markets). (None, []) when sales exist."""
        sales = next((card for card in cards if card["topic"].startswith("sales_")), None)
        if sales is None or sales.get("status") == "available":
            return None, []
        selection, profile = snapshot.get("selection") or {}, snapshot.get("profile") or {}
        area_code, area_name = selection.get("area_code"), selection.get("area_name") or ""
        industry = (profile.get("industry") or {}).get("code")
        industry_name = (profile.get("industry") or {}).get("name") or "이 업종"
        if not (area_code and industry):
            return None, []
        try:
            from app.onboarding_analysis_catalog import get_area_availability

            availability = get_area_availability(area_code, industry)
            periods = [p["code"] for p in availability.get("periods", [])]
            with_sales = [p["label"] for p in availability.get("periods", [])
                          if (p.get("metrics", {}).get("sales") or {}).get("status") == "available"]
        except Exception as error:  # catalogue not built or unknown market: say nothing extra
            _log.info("availability lookup skipped: %s", type(error).__name__)
            return None, []
        if with_sales:
            return f"이 분기에는 {industry_name} 매출 자료가 없지만, {', '.join(with_sales[-3:])} 자료는 있어요.", []
        try:
            market = self._source().areas().get(area_code) or {}
            result = rank_sales(self._source(), RankingRequest(
                industry_code=industry, district_codes=frozenset({market.get("district_code")}) if market else frozenset(),
                district_labels=(market.get("district_name") or "",), limit=20))
        except Exception as error:
            _log.info("nearby markets skipped: %s", type(error).__name__)
            result = {"items": []}
        station = area_name.split(" ")[0]
        items = [item for item in result.get("items", []) if item["area_code"] != area_code and item.get("selectable")
                 and item.get("neighborhood_code")]
        items.sort(key=lambda item: (not item["name"].startswith(station), item["rank"]))
        actions = [{"label": f"{item['name']} 보기",
                    "payload": {"type": "location", "kind": "neighborhood", "district_code": item["district_code"],
                                "neighborhood_code": item["neighborhood_code"], "area_code": item["area_code"],
                                "period": result.get("period"), "industry_code": industry}} for item in items[:4]]
        return templates.no_sales_anywhere_line(area_name, industry_name, sorted(periods), bool(actions)), actions

    @staticmethod
    def _auto_area(candidates: list[dict]):
        """Pick a market without asking only when there is exactly one obvious one."""
        inside = [c for c in candidates if c.get("relation") in ("inside", "boundary")]
        if len(inside) == 1:
            return inside[0]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _snapshot(self, owner, bridge, state):
        key = SnapshotCache.key(owner, state)
        snapshot = self.snapshots.get(key)
        if snapshot is None:
            snapshot = build_snapshot(bridge, state)
            self.snapshots.put(key, snapshot)
        return snapshot

    def _comparison(self, bridge, snapshot, intent: Intent):
        if intent.comparison_area_code is None:
            options = bridge.comparison_options(snapshot["revision"])
            areas = [area for area in options.get("areas", []) if area.get("selectable")]
            shortlist = []
            if intent.comparison_hint:
                full = hint = intent.comparison_hint
                for suffix in ("역", "동", "구"):
                    hint = hint[:-1] if hint.endswith(suffix) and len(hint) > 2 else hint
                exact = [area for area in areas if area.get("name") == full]
                # '강남역': the market named exactly that, not 강남 마이스·강남개포시장 first.
                shortlist = exact or sorted((area for area in areas if hint in area.get("name", "")),
                                            key=lambda area: (not area.get("name", "").startswith(full),
                                                              not area.get("name", "").startswith(hint),
                                                              len(area.get("name", ""))))
                if len(shortlist) == 1:
                    intent.comparison_area_code = shortlist[0]["area_code"]
            if intent.comparison_area_code is None:
                if not shortlist:
                    # Same district as the saved location first; the full list has about 1,650 markets.
                    district = (snapshot["profile"]["location"] or {}).get("district_code")
                    shortlist = [area for area in areas if area.get("district_code") == district] or areas
                return templates.choose_comparison(shortlist)
        if snapshot.get("comparison_area_code") != intent.comparison_area_code:
            add_comparison(bridge, snapshot, intent.comparison_area_code)
        return None

    def _write(self, cards, cls, *, show_conditions: bool = True, changed: bool = False, required=(),
               fallback: dict | None = None, opinion: bool = False, caveat: str | None = None) -> dict:
        """Model text when it passes answer_check, otherwise the verified fixed-form answer.

        Either way the notes (card warnings) and next-question suggestions are the server's own. An opinion
        always ends with what the data lacks (rent, key money), written by the server.
        """
        fallback = fallback or templates.data_answer(cards, cls, show_conditions=show_conditions, changed=changed)
        extra, _notes, _suggestions = templates.answer_extras(cards, cls)
        if not (cls.get("text") or "").strip():
            # A market opened by a button has no question; an empty one made HCX-005 write a bare list (2026-11-08).
            values = {v.get("label"): v.get("value") for card in cards if card["topic"] == "conditions"
                      for v in card.get("values", [])}
            cls = {**cls, "text": f"{values.get('상권') or '이'} 상권의 {values.get('업종') or '이'} 업종은 어때요? "
                                  "핵심만 이야기하듯 알려 주세요."}
        if opinion:
            extra = [caveat or opinions.CAVEAT]
        if self.writer is None:
            return {**fallback, "model_used": False}
        def attempt(classification):
            text = self.writer(cards, classification)
            body = templates.model_body(text if isinstance(text, str) else "", cards, show_conditions=show_conditions,
                                        drop_missing_notes=bool(cls.get("unavailable")), changed=changed,
                                        opinion=opinion)
            body = repair_citations(body, cards)  # a right number with another card's number attached
            result = (check_answer(body, cards, opinion=opinion) if body
                      else {"ok": False, "problems": [{"type": "empty_answer"}]})
            if result["ok"] and not opinion and not has_statistics(body, cards) and any(
                    card["topic"] != "conditions" and card.get("status") == "available" and any(
                        type(v.get("value")) in (int, float) for v in card.get("values", [])) for card in cards):
                # '평일에 비해 주말 매출이 적지만, 여전히 많은 사람이 찾고 있네요' answered nothing (2026-11-08).
                result = {"ok": False, "problems": [{"type": "answer_without_numbers"}]}
            cited_ids = set(re.findall(r"\b(F\d+)\b", body or ""))
            left_out = [card_id for card_id in required if card_id not in cited_ids]
            if left_out:
                result = {"ok": False,
                          "problems": [*result["problems"], {"type": "promised_card_left_out", "detail": left_out}]}
            return text, body, result

        try:
            text, body, result = attempt(cls)
            if not result["ok"]:
                # One rewrite with the findings; the first problems are kept for the development export.
                first = result["problems"]
                text, body, result = attempt({**cls, "retry": {"previous": text if isinstance(text, str) else "",
                                                                "feedback": check_feedback(first, cards)}})
                if not result["ok"]:
                    result = {**result, "problems": [*first, *result["problems"]]}
        except Exception as error:  # model or network failure: never lose the verified answer
            _log.warning("model writer failed, fixed-form answer used: %s", error)
            return {**fallback, "model_used": False, "model_error": True}
        if not result["ok"]:
            # Forbidden phrases are fixed strings from answer_check, so they are safe to log; the answer text is not logged.
            phrases = sorted({p["detail"] for p in result["problems"] if p["type"] == "forbidden_phrase"})
            _log.info("model answer rejected: %s%s", sorted({problem["type"] for problem in result["problems"]}),
                      f" phrases={phrases}" if phrases else "")
            return {**fallback, "model_used": False, "model_rejected": result["problems"]}
        cited = list(dict.fromkeys(re.findall(r"\[(F\d+)\]", body)))
        # The interpretation line was checked as one; on screen its hedged wording is enough to mark it.
        shown = "\n".join(line[len(templates.INSIGHT_MARK):].strip() if line.startswith(templates.INSIGHT_MARK) else line
                          for line in body.split("\n"))
        return {**fallback, "text": "\n".join([shown, *extra]), "cited": cited, "model_used": True}

    @staticmethod
    def _intent_pending(intent: Intent) -> dict:
        return {"topics": intent.topics, "location": intent.location, "industry_code": intent.industry_code,
                "business_status": intent.business_status, "period_code": intent.period_code,
                "comparison_hint": intent.comparison_hint, "question": intent.classification.get("text"),
                "opinion": intent.opinion}

    @staticmethod
    def _finish(reply: dict, cls: dict, *, state=None, cards=None, topics=None, pending=None, site_costs=None) -> dict:
        # Context quarters belong to each dataset, not to the selected sales quarter.
        # Keep this evidence in the final reply even when a model omits the card's wording.
        figures = {}
        for card in cards or []:
            for value in card.get("values", []):
                source = value.get("source_ref") or {}
                if source.get("dataset") not in location.DATASETS or not source.get("period"):
                    continue
                key = (value.get("market"), source.get("requested_period"))
                figure = figures.setdefault(key, {"name": key[0], "context_requested_period": key[1],
                                                  "context_sources": {}})
                figure["context_sources"][source["dataset"]] = source
        text, notes = reply.get("text") or "", list(reply.get("notes") or [])
        for figure in figures.values():
            note = location.period_sentence(figure)
            if note not in text and templates.soften(note) not in text:
                text = "\n".join(part for part in (text, "참고: " + note) if part)
            if note not in notes:
                notes.append(note)
        reply = {**reply, "text": with_units(text), "notes": notes}
        result = {"schema_version": SCHEMA,
                  "reply": {**{key: reply.get(key) for key in ("text", "kind", "cited", "actions")},
                            "notes": reply.get("notes") or [], "suggestions": reply.get("suggestions") or []},
                  "model_used": bool(reply.get("model_used")),
                  "cards": cards or [],
                  "topics": topics if topics is not None else [],
                  "classification": {key: cls.get(key) for key in
                                     ("domain", "turn_type", "topics", "needs_user_choice", "needs_model", "analyzer")},
                  "pending": pending,
                  # Kept with the turn for the development export (export.py); the router never sends it.
                  "debug": {"planner": cls.get("planner"), "reasons": (cls.get("reasons") or [])[:4],
                            "model_rejected": reply.get("model_rejected"), "model_error": bool(reply.get("model_error")),
                            "site_costs": site_costs}}
        # Only a turn that read the saved state reports conditions. A small-talk or 'unknown' reply never
        # looked, so it must not tell the page that the conditions are empty (the bar was being cleared).
        if state is not None:
            result["conditions"] = _conditions(state)
        return result
