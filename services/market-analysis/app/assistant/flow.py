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

from app.assistant import templates
from app.assistant.answer_check import check_answer
from app.assistant.bridge import OnboardingBridge, error_message
from app.assistant.facts import cards_from_snapshot, select_cards
from app.assistant.intent import DEFAULT_TOPICS, classify, industry_codes
from app.assistant.ranking import (INDUSTRY_COUNT, Exclusion, RankingRequest, SeoulSalesSource, areas_for_mentions,
                                   industry_rank_cards, order_markets, rank_industries, rank_sales, ranking_card)
from app.assistant.snapshot import SnapshotCache, add_comparison, build_snapshot

SCHEMA = "assistant-reply-v1"
# Short requests that only make sense as a follow-up: '추천해줘', '골라 줘', '뭐가 좋아?'.
_FOLLOW_REQUEST = re.compile(r"추천|골라|뭐가 ?좋|뭐가 ?나아|어떤 게 ?좋|알려 ?줘")
_DEFAULT_STATUS = "operating"
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
        response = self._respond(owner, bridge, cls, last)
        if cls.get("unavailable") and response["reply"].get("kind") in ("data_answer", "ranking", "industry_rank"):
            # Say first what the public data cannot answer ('프랜차이즈 브랜드별 매출'), so the numbers below are
            # not read as an answer to it.
            response["reply"]["text"] = templates.unavailable_line(cls["unavailable"]) + "\n" + response["reply"]["text"]
        self.history.add(owner, client_message_id, text, response)
        return response

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
        return self.planner.plan(text, rule=rule, conditions=_conditions(state), recent=recent, loaded=loaded,
                                 today=self.today or date.today(), after_list=last_kind == "ranking")

    def handle_action(self, owner: str, request, payload: dict) -> dict:
        last = self.history.last(owner) or {}
        pending = last.get("pending") or {}
        intent = Intent(topics=pending.get("topics") or list(DEFAULT_TOPICS),
                        location=pending.get("location"), industry_code=pending.get("industry_code"),
                        business_status=pending.get("business_status"), period_code=pending.get("period_code"),
                        comparison_hint=pending.get("comparison_hint"),
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
        intent = self._intent(cls, last)
        if isinstance(intent, dict):  # the user must choose first
            return intent
        return self._run(owner, bridge, intent)

    def _intent(self, cls: dict, last: dict):
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
        if comparison and len(mentions) >= 2:
            intent.comparison_hint = mentions[1]["candidates"][0]["name"]
            mentions = mentions[:1]
        if mentions:
            if len(mentions) > 1 or len(mentions[0]["candidates"]) > 1:
                options = [c for m in mentions for c in m["candidates"]]
                reply = templates.choose_location(mentions[0]["text"], options)
                return self._finish(reply, cls, pending=self._pending(intent, topics, cls))
            place = mentions[0]["candidates"][0]
            payload = location_payload(place)
            if payload is None:
                return self._finish(templates.district_only(place["label"]), cls,
                                    pending=self._pending(intent, topics, cls))
            intent.location, intent.location_label = payload, place["label"]
        else:
            intent.location = pending.get("location")
        codes = industry_codes(cls)
        if len(codes) > 1 and not comparison:
            rows = [c for m in cls["slots"]["industries"] for c in m["candidates"]]
            return self._finish(templates.choose_industry(rows), cls, pending=self._pending(intent, topics, cls))
        intent.industry_code = codes[0] if codes else pending.get("industry_code")
        return intent

    def _pending(self, intent: Intent, topics, cls) -> dict:
        codes = industry_codes(cls)
        return {"topics": topics, "location": intent.location,
                "industry_code": codes[0] if len(codes) == 1 else None,
                "business_status": intent.business_status, "period_code": intent.period_code,
                "comparison_hint": intent.comparison_hint, "question": cls.get("text")}

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
        industry = industry_code or (codes[0] if codes else None) or spec.get("industry_code") \
            or (profile.get("industry") or {}).get("code")
        if industry is None:
            return self._finish(templates.need_industry(), cls, state=state,
                                pending={"ranking": spec, "ranking_question": True, "topics": ["ranking"],
                                         "question": cls.get("text")})
        names = {row["code"]: row["name"] for row in rows}
        if (profile.get("industry") or {}).get("code"):
            names.setdefault(profile["industry"]["code"], profile["industry"]["name"])
        exclusion = Exclusion.from_dict(spec.get("exclusion"))
        request = RankingRequest(industry_code=industry, industry_name=names.get(industry), period=spec.get("period"),
                                 district_codes=frozenset(spec.get("district_codes") or ()),
                                 district_labels=tuple(spec.get("district_labels") or ()), exclusion=exclusion)
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
        # The buttons open one market with the ranked industry and quarter; '카페는?' re-ranks with this scope.
        after = {"topics": list(DEFAULT_TOPICS), "location": None, "industry_code": industry,
                 "business_status": cls["slots"].get("business_status") or profile.get("business_status"),
                 "period_code": result["period"], "comparison_hint": None, "question": None,
                 "ranking": {**spec, "industry_code": industry}}
        return self._finish(reply, cls, state=state, cards=[card], topics=["ranking"], pending=after)

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
        spec = {"count": count, "period": period, "excluded": excluded}
        ask = {"industry_rank": spec, "industry_rank_question": True, "topics": ["industry_rank"],
               "question": cls.get("text")}
        source = self._source()
        try:
            if area_code is None:
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
            result = rank_industries(source, area_code, period=period, limit=count, excluded_codes=excluded)
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
        try:
            state = bridge.state()
            profile = state["profile"]
            # 1. Location and industry ------------------------------------------
            if profile is None and intent.location is None:
                return self._finish(templates.need_location(), cls, pending=self._intent_pending(intent))
            if profile is None and intent.industry_code is None:
                return self._finish(templates.need_industry(), cls, pending=self._intent_pending(intent))
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
                    return self._finish(templates.choose_area(options, want_period), cls, state=state,
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
            cards = select_cards(cards_from_snapshot(snapshot), intent.topics)
            # Say the conditions again only when they are new to this conversation; the bar above the chat shows them.
            last = self.history.last(owner) or {}
            repeated = ((last.get("reply") or {}).get("kind") == "data_answer"
                        and last.get("conditions") == _conditions(state) and not intent.condition_change)
            # A changed condition is said in context ('이번에는 가산디지털단지 상권의 커피-음료 업종으로 볼게요'),
            # not as a bare '조건을 바꿨어요' (user feedback 2026-11-08).
            reply = self._write(cards, cls, show_conditions=not repeated, changed=intent.condition_change)
            return self._finish(reply, cls, state=state, cards=cards, topics=intent.topics)
        except HTTPException as error:
            if error.status_code == 409:
                return self._finish(templates.data_unavailable("다른 화면에서 조건이 바뀌었어요. 한 번 더 말씀해 주세요."), cls)
            return self._finish(templates.data_unavailable(error_message(error)), cls)

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
                hint = intent.comparison_hint
                for suffix in ("역", "동", "구"):
                    hint = hint[:-1] if hint.endswith(suffix) and len(hint) > 2 else hint
                shortlist = [area for area in areas if hint in area.get("name", "")]
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

    def _write(self, cards, cls, *, show_conditions: bool = True, changed: bool = False) -> dict:
        """Model text when it passes answer_check, otherwise the verified fixed-form answer.

        Either way the notes (card warnings) and next-question suggestions are the server's own.
        """
        fallback = templates.data_answer(cards, cls, show_conditions=show_conditions, changed=changed)
        extra, _notes, _suggestions = templates.answer_extras(cards, cls)
        if self.writer is None:
            return {**fallback, "model_used": False}
        try:
            text = self.writer(cards, cls)
        except Exception as error:  # model or network failure: never lose the verified answer
            _log.warning("model writer failed, fixed-form answer used: %s", error)
            return {**fallback, "model_used": False, "model_error": True}
        body = templates.model_body(text if isinstance(text, str) else "", cards, show_conditions=show_conditions,
                                    drop_missing_notes=bool(cls.get("unavailable")), changed=changed)
        result = check_answer(body, cards) if body else {"ok": False, "problems": [{"type": "empty_answer"}]}
        if not result["ok"]:
            # Forbidden phrases are fixed strings from answer_check, so they are safe to log; the answer text is not logged.
            phrases = sorted({p["detail"] for p in result["problems"] if p["type"] == "forbidden_phrase"})
            _log.info("model answer rejected: %s%s", sorted({problem["type"] for problem in result["problems"]}),
                      f" phrases={phrases}" if phrases else "")
            return {**fallback, "model_used": False, "model_rejected": result["problems"]}
        cited = list(dict.fromkeys(re.findall(r"\[(F\d+)\]", body)))
        return {**fallback, "text": "\n".join([body, *extra]), "cited": cited, "model_used": True}

    @staticmethod
    def _intent_pending(intent: Intent) -> dict:
        return {"topics": intent.topics, "location": intent.location, "industry_code": intent.industry_code,
                "business_status": intent.business_status, "period_code": intent.period_code,
                "comparison_hint": intent.comparison_hint, "question": intent.classification.get("text")}

    @staticmethod
    def _finish(reply: dict, cls: dict, *, state=None, cards=None, topics=None, pending=None) -> dict:
        result = {"schema_version": SCHEMA,
                  "reply": {**{key: reply.get(key) for key in ("text", "kind", "cited", "actions")},
                            "notes": reply.get("notes") or [], "suggestions": reply.get("suggestions") or []},
                  "model_used": bool(reply.get("model_used")),
                  "cards": cards or [],
                  "topics": topics if topics is not None else [],
                  "classification": {key: cls.get(key) for key in
                                     ("domain", "turn_type", "topics", "needs_user_choice", "needs_model", "analyzer")},
                  "pending": pending}
        # Only a turn that read the saved state reports conditions. A small-talk or 'unknown' reply never
        # looked, so it must not tell the page that the conditions are empty (the bar was being cleared).
        if state is not None:
            result["conditions"] = _conditions(state)
        return result
