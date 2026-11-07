"""AI planner: CLOVA reads the whole situation and chooses what to do next.

For every message the model sees the question, the recent dialogue, the saved
conditions, the data already loaded for them, Kiwi morphemes, the dictionary
matches, the rule classifier's guess and similar example sentences. It answers
with one JSON object: {"action": ..., "args": {...}}.

JSON in the reply is used instead of CLOVA function calling: on 2026-11-08
HCX-005 rejected tools together with maxTokens (40001), rejected
toolChoice "required" and a forced single function (40001, 40009), and with
toolChoice "auto" sometimes wrote "도구: rank_industries" as text instead of a
call. Code checks the JSON either way, so nothing is lost.

The model only decides. Code then checks the decision: place and industry
names must be found in the official dictionaries (codes never come from the
model), topics must be known, free text must contain no statistics. The
checked decision becomes the same classification dict that the rule
classifier produces, so the rest of the flow (conditions, fact cards,
rankings, answer checks) is unchanged. Any failure returns None and the rule
classification is used.
"""
from __future__ import annotations

from datetime import date
import json
import logging
import re

from app.assistant.answer_check import FORBIDDEN
from app.assistant.examples import similar
from app.assistant.intent import DEFAULT_TOPICS, content_morphemes, requested_count, scan_slots
from app.assistant.lexicon import similar_industries

_log = logging.getLogger("app.assistant.planner")

TOPICS = ("sales_total", "sales_weekday", "sales_time", "sales_age", "stores_count", "stores_open_close",
          "population", "change_qoq", "change_yoy")
ACTIONS = ("market_data", "rank_areas", "rank_industries", "ask_user", "small_talk", "out_of_scope", "handoff")
MAX_REPLY_CHARS = 220
_STAT = re.compile(r"\d[\d,.]*\s*(원|%|퍼센트|프로|명|개|곳|억|만|천|배)")
_JSON = re.compile(r"\{.*\}", re.S)
_EXCLUDE = re.compile(r"말고|말구|빼고|제외|아니고|대신")
# Words that ask for a list of markets. Without one, an area ranking needs the dialogue to have asked for it.
_AREA_CUE = re.compile(r"어디|어느|순위|랭킹|top|탑|상위|높은|많은|잘되는|잘 되는|잘나가|좋은|괜찮은|추천|다른 ?데|다른 ?곳|동네|지역|1등|1위"
                       r"|(무슨|어떤|몇) ?(구|동|상권|곳|데)", re.I)
_UNAVAILABLE_MAX = 30
# What the public data does not contain. An 'unavailable' note must name one of these.
_MISSING_TOPICS = re.compile(r"브랜드|상호|회사|직장인|직장 ?인구|거주|주민|임대|월세|권리금|보증금|시세|가격|단가|리뷰|별점|날씨"
                             r"|순이익|이익|마진|비용|인건비|가게 ?하나|개별 ?가게|우리 ?가게|배달|객단가|성별|남녀|외국인|관광객 ?수")

SYSTEM_PROMPT = """너는 서울 상권 분석 챗봇의 판단 담당이다.
사용자의 [질문]을 아래 참고 자료와 함께 보고, 다음에 할 일을 하나 고른다.
답은 JSON 객체 하나만 쓴다. 설명이나 다른 글은 쓰지 않는다.
형식: {"action": "<할 일>", "args": {...}}

할 일 (action)과 args
- market_data: 한 상권의 공공 자료를 본다. 매출, 요일·시간대·연령대별 매출, 점포 수, 개업·폐업, 유동인구, 지난 분기·작년 대비, 다른 상권과 비교, 앞 답을 쉽게 다시 설명. 장소·업종·기간을 바꾸는 요청도 여기다.
  args: place(역·동·지명), industry(업종), topics(아래 주제 목록, 장소·업종·기간만 바꾸면 []), period('2025년 3분기'), compare_place(비교할 상권)
  주제: sales_total=분기 매출, sales_weekday=요일별, sales_time=시간대별, sales_age=연령대별, stores_count=점포 수·프랜차이즈, stores_open_close=개업·폐업, population=유동인구, change_qoq=지난 분기 대비, change_yoy=작년 대비
- rank_areas: 한 업종의 매출이 큰 상권 순위. '어디가 좋아', '매출 높은 곳', '어디에 차릴까'.
  args: industry, within_place(이 장소의 구 안에서만), exclude_places(뺄 장소 목록), count(1~5, 말했을 때만)
- rank_industries: 한 상권 안에서 매출이 큰 업종. 업종 추천, '무슨 장사 하면 좋을까', '뭐 차릴까'.
  args: place, exclude_industries(뺄 업종 목록), count
- handoff: 홍보 글·쿠폰·이벤트·SNS 효과는 marketing, 리뷰·답글·환불·손님 응대·클레임은 customer 기능으로 넘긴다. 이런 질문은 out_of_scope가 아니라 handoff다.
  args: domain("marketing" 또는 "customer")
- small_talk: 인사, 감사, 불만, 하소연, 챗봇 소개. args: reply
- out_of_scope: 상권 자료로 답할 수 없는 질문(가격 정하기, 임대료, 대출, 세금, 날씨, 코딩 등). args: reply
- ask_user: 무엇을 원하는지 정말 알 수 없을 때 되묻는다. args: reply

공공 자료에 있는 것: 상권·업종별 분기 추정매출(요일·시간대·연령대), 업종 전체 점포 수(일반·프랜차이즈 개수), 개업·폐업 수, 상권 유동인구(시간대·연령대).
공공 자료에 없는 것: 프랜차이즈 브랜드 이름과 브랜드별 매출, 가게 하나의 매출, 회사·직장인 수, 거주 인구, 임대료·권리금, 가격, 리뷰, 날씨.
질문의 일부가 없는 것을 물으면 market_data·rank_areas·rank_industries의 args에 unavailable("프랜차이즈 브랜드별 매출"처럼 짧은 명사구)을 넣고, 있는 자료 중 가장 가까운 것을 고른다. 예: '근처에 회사가 많아?' → {"action": "market_data", "args": {"topics": ["population", "sales_weekday", "sales_time"], "unavailable": "회사·직장인 수"}}

규칙
0. 사용자에게 직접 답하지 않는다. 인사·홍보·환불 질문이어도 반드시 JSON 객체 하나로만 답한다.
1. 질문에 장소나 업종이 빠졌으면 [최근 대화]와 [지금 조건]에서 이어 받는다. 예: 앞에서 '연남동에서 창업하고 싶다'고 했고 지금 '추천해줘'라면 {"action": "rank_industries", "args": {"place": "연남동"}}. 지금 조건이 있으면 '그거', '거기', '작년이랑도'는 그 조건에 대한 질문이다.
2. 장소와 업종은 사용자가 말했거나 [최근 대화]·[지금 조건]에 나온 이름만 쓴다. 지어내지 않는다.
3. 수치를 만들지 않는다. 숫자는 시스템이 공공 자료에서 가져온다.
4. [형태소 분석], [사전 후보], [규칙 분류기 추측], [비슷한 예문]은 참고 자료다. 문장 전체의 뜻과 대화 흐름이 다르면 따르지 않는다.
5. reply는 해요체 1~2문장으로 쓰고, 숫자를 쓰지 않으며, 상권 질문의 예를 하나 들어 이끈다.
6. 업종이 정해져 있고 '어디'를 물으면 rank_areas, 장소가 정해져 있고 '무엇·어떤 업종'을 물으면 rank_industries다. 사용자가 업종을 이미 말하고 '상권 어때'처럼 그 상권을 물으면 market_data다.
   앞 답을 '쉽게', '자세히' 다시 설명해 달라는 말은 market_data(topics: [])다.
7. '왜 줄었어', '왜 그런 거야'는 원인을 알 수는 없지만 같은 기간의 변화를 보여 줄 수 있으므로 market_data(topics: change_yoy, sales_total)다.
8. 손님을 늘리는 방법, 홍보 수단 비교(전단지·인스타)는 handoff(marketing)다.
9. '너라면 어디에 차릴 거야', '무슨 구가 좋아'처럼 의견을 물어도 의견을 만들지 않고 rank_areas로 자료를 보여 준다."""

# One fixed exchange so the model answers with JSON rather than to the user.
_SHOT_USER = """[지금 조건]
아직 정하지 않음

[최근 대화]
없음

[질문]
안녕하세요 처음 써봐요"""
_SHOT_ANSWER = '{"action": "small_talk", "args": {"reply": "반가워요! 서울 상권의 매출·점포·유동인구를 알려드려요. \'합정역 카페 매출 어때?\'처럼 물어보세요."}}'


def _fmt_example(example: dict) -> str:
    decision = json.dumps({"action": example["action"], "args": example.get("args") or {}}, ensure_ascii=False)
    context = f" (상황: {example['context']})" if example.get("context") else ""
    return f"- \"{example['text']}\"{context} → {decision}"


def build_context(question: str, *, rule: dict, conditions: dict | None, recent: list[str],
                  loaded: list[str], use_morph: bool = True) -> str:
    slots = rule.get("slots") or {}
    places = ", ".join(f"{m['text']}→" + "/".join(c["label"] for c in m["candidates"][:3])
                       for m in slots.get("locations", [])) or "없음"
    industries = ", ".join(f"{m['text']}→" + "/".join(c["name"] for c in m["candidates"][:3])
                           for m in slots.get("industries", [])) or "없음"
    period = (slots.get("period") or {}).get("period_code") or "없음"
    if conditions:
        current = (f"{conditions.get('area_name') or '상권 미정'} 상권 · {conditions.get('industry_name') or '업종 미정'} · "
                   f"{conditions.get('period_label') or '기간 미정'}")
    else:
        current = "아직 정하지 않음"
    dialogue = "\n".join(recent) or "없음"
    morphemes = " ".join(content_morphemes(question, use_morph=use_morph)) or "(형태소 분석기 꺼짐)"
    examples = "\n".join(_fmt_example(e) for e in similar(question, use_morph=use_morph)) or "없음"
    data = "\n".join(loaded[:8]) or "없음"
    return "\n\n".join([
        f"[지금 조건]\n{current}",
        f"[최근 대화]\n{dialogue}",
        f"[불러 둔 자료]\n{data}",
        f"[형태소 분석]\n{morphemes}",
        f"[사전 후보]\n장소: {places}\n업종: {industries}\n기간: {period}",
        f"[규칙 분류기 추측]\n{rule.get('turn_type')} {rule.get('topics')}",
        f"[비슷한 예문]\n{examples}",
        f"[질문]\n{question[:500]}",
        "위 [질문]에 대한 판단을 JSON 객체 하나로만 답하세요."])


def build_request(context: str) -> dict:
    return {"messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": _SHOT_USER}, {"role": "assistant", "content": _SHOT_ANSWER},
                         {"role": "user", "content": context}],
            "topP": 0.8, "topK": 0, "maxTokens": 300, "temperature": 0.1, "repetitionPenalty": 1.0, "seed": 0,
            "includeAiFilters": True}


def parse_decision(result: dict) -> tuple[str | None, dict]:
    """The model's JSON decision. A function-call reply is accepted too, should a model return one."""
    message = result.get("message") or {}
    calls = message.get("toolCalls") or []
    if calls and isinstance(calls[0], dict):
        function = calls[0].get("function") or {}
        name, args = function.get("name"), function.get("arguments") or {}
    else:
        match = _JSON.search(message.get("content") or "")
        try:
            decision = json.loads(match.group(0)) if match else {}
        except json.JSONDecodeError:
            decision = {}
        if not isinstance(decision, dict):
            return None, {}
        name, args = decision.get("action"), decision.get("args") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return (name if name in ACTIONS else None), (args if isinstance(args, dict) else {})


def safe_reply(text) -> str | None:
    """Free text the model wrote for small talk or a question back: short, no statistics, no forbidden phrases."""
    if not isinstance(text, str):
        return None
    text = " ".join(text.replace("**", "").split())
    if not text or len(text) > MAX_REPLY_CHARS or _STAT.search(text) or any(p in text for p in FORBIDDEN):
        return None
    return text


def _texts(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [v.strip() for v in value or [] if isinstance(v, str) and v.strip()][:5]


class Planner:
    """``planner.plan(question, rule=..., ...) -> classification | None``."""

    def __init__(self, client, *, use_morph: bool = True):
        self.client = client  # clova_client.ClovaWriter: shares its key and daily quota
        self.use_morph = use_morph
        self.last_failure = None  # why the last plan() returned None, for logs and the evaluation script

    def plan(self, question: str, *, rule: dict, conditions: dict | None, recent: list[str],
             loaded: list[str], today: date | None = None, after_list: bool = False) -> dict | None:
        """``after_list``: the previous answer was an area ranking, so '그럼 치킨은?' may ask for another one."""
        self.last_failure = None
        context = build_context(question, rule=rule, conditions=conditions, recent=recent, loaded=loaded,
                                use_morph=self.use_morph)
        try:
            result = self.client.complete(build_request(context), purpose="plan")
        except Exception as error:  # quota, network, API error: the rule classification answers
            self.last_failure = f"call: {error}"
            _log.warning("planner failed, rule classification used: %s", error)
            return None
        name, args = parse_decision(result)
        try:
            planned = to_classification(name, args, rule=rule, question=question, use_morph=self.use_morph,
                                        today=today, after_list=after_list)
        except Exception as error:  # an argument shape no check foresaw must never break the turn
            self.last_failure = f"check failed: {type(error).__name__}"
            _log.warning("planner decision could not be checked, rule classification used: %s", type(error).__name__)
            return None
        if planned is None:
            # Kept in memory only (never logged): the start of the reply helps tune the prompt in eval_planner.
            content = " ".join(((result.get("message") or {}).get("content") or "").split())[:60]
            self.last_failure = f"no usable decision: {content}" if name is None else f"refused action {name}"
        _log.info("planner action=%s accepted=%s rule=%s", name, planned is not None, rule.get("turn_type"))
        return planned


def _as_text(value) -> str:
    """A model value as plain text: '홍대', ['홍대', '합정'] -> '홍대 합정', anything else -> ''."""
    if isinstance(value, str):
        return value.strip()[:100]
    if isinstance(value, list):
        return " ".join(v.strip() for v in value if isinstance(v, str))[:100]
    return ""


def _mentions(text, kind: str, *, use_morph: bool, today) -> list[dict]:
    text = _as_text(text)
    if not text:
        return []
    return scan_slots(text, use_morph=use_morph, today=today)[kind]


def to_classification(name, args: dict, *, rule: dict, question: str, use_morph: bool = True,
                      today: date | None = None, after_list: bool = False) -> dict | None:
    """Check one tool call and turn it into the classifier's schema. None when it cannot be used."""
    today = today or date.today()
    slots = rule.get("slots") or {}
    base = {**rule, "text": question, "needs_model": False, "needs_user_choice": False,
            "analyzer": "clova-planner", "planner": {"action": name, "args": args},
            "reasons": [f"AI 판단: {name}"], "topics_defaulted": False, "ai_reply": None, "unresolved_industry": None,
            "signals": {**(rule.get("signals") or {}), "comparison": False}}
    new_slots = {"locations": [], "excluded_locations": [], "industries": [], "excluded_industries": [],
                 "count": None, "period": slots.get("period") or {"relative": None, "comparison": None, "period_code": None},
                 "business_status": slots.get("business_status")}
    # The count comes from the user's words only: the model once sent count=1 for '카페 말고 다른 업종은?'.
    new_slots["count"] = requested_count(question)
    # What the user asked that the public data cannot answer ('프랜차이즈 브랜드별 매출'): said first, never guessed.
    # Accepted only for things the data really lacks: the model once marked '점심, 저녁' as missing, and the
    # server then wrongly said that lunch and dinner sales were not in the data.
    unavailable = _as_text(args.get("unavailable"))
    base["unavailable"] = unavailable if (0 < len(unavailable) <= _UNAVAILABLE_MAX and not re.search(r"\d", unavailable)
                                          and _MISSING_TOPICS.search(unavailable)) else None

    def found(text, kind):
        return _mentions(text, kind, use_morph=use_morph, today=today)

    def industry_of(value) -> list:
        """Dictionary match; else official industries that look like it ('중식점' -> 중식음식점).

        A name that matches nothing is recorded, so the saved industry is never used in its place silently.
        """
        text = _as_text(value)
        mentions = found(text, "industries")
        if mentions or not text:
            return mentions
        similar = similar_industries(text)
        if similar:
            base["reasons"].append(f"'{text}'을 비슷한 공식 업종으로 연결")
            return [{"text": text, "candidates": similar}]
        base["unresolved_industry"] = text
        return []

    def or_question(planned: list, kind: str) -> list:
        """The model's names, or what the dictionaries found in the user's own words when the model gave
        none or only part of them (e.g. one of '분식집이랑 치킨집')."""
        asked = slots.get(kind) or []
        mine = {c.get("code") or c.get("label") for m in planned for c in m["candidates"]}
        theirs = {c.get("code") or c.get("label") for m in asked for c in m["candidates"]}
        return asked if asked and (not planned or mine < theirs) else planned

    if name == "market_data":
        raw_topics = args.get("topics")
        topics = [t for t in (raw_topics if isinstance(raw_topics, list) else [raw_topics]) if t in TOPICS]
        new_slots["locations"] = or_question(found(args.get("place"), "locations"), "locations")
        new_slots["industries"] = or_question(industry_of(args.get("industry")), "industries")
        period_text = _as_text(args.get("period"))
        if period_text:
            period = scan_slots(period_text, use_morph=use_morph, today=today)["period"]
            if period.get("period_code"):
                new_slots["period"] = period
        if _as_text(args.get("compare_place")):
            new_slots["locations"] = new_slots["locations"][:1] + found(args["compare_place"], "locations")[:1]
            topics.append("comparison")
            base["signals"]["comparison"] = True
        changed = bool(new_slots["locations"] or new_slots["industries"] or (period_text and
                                                                             new_slots["period"].get("period_code")))
        if not topics and changed:
            turn = "condition_change"
        elif not topics and rule.get("turn_type") == "followup":
            # '좀 더 쉽게 설명해 줘': the same topics as the previous answer, which the rule classifier carried over.
            turn, topics = "followup", [t for t in rule.get("topics", []) if t in TOPICS] or list(DEFAULT_TOPICS)
        else:
            turn = "data_question"
            if not [t for t in topics if t != "comparison"]:
                topics = [*DEFAULT_TOPICS, *topics]
                base["topics_defaulted"] = True
        return {**base, "domain": "market_analysis", "turn_type": turn, "topics": topics, "slots": new_slots}
    if name == "rank_areas" and not _AREA_CUE.search(question) and not after_list:
        # No '어디·순위·추천…' in the question: '망원동에서 분식집 하려는데 상권 어때?' is about that market
        # (live HCX-005 answered it once with rank_industries and once with rank_areas).
        return to_classification("market_data", {"place": args.get("within_place"), "industry": args.get("industry"),
                                                 "topics": list(DEFAULT_TOPICS), "unavailable": args.get("unavailable")},
                                 rule=rule, question=question, use_morph=use_morph, today=today)
    if name == "rank_areas":
        new_slots["industries"] = or_question(industry_of(args.get("industry")), "industries")
        new_slots["locations"] = found(args.get("within_place"), "locations")[:1]
        new_slots["excluded_locations"] = [m for text in _texts(args.get("exclude_places"))
                                           for m in found(text, "locations")] or slots.get("excluded_locations") or []
        return {**base, "domain": "market_analysis", "turn_type": "ranking", "topics": ["ranking"], "slots": new_slots}
    if name == "rank_industries":
        named = slots.get("industries") or []
        if named and not _EXCLUDE.search(question) and rule.get("turn_type") != "industry_rank":
            # '망원동에서 분식집 하려는데 상권 어때?' names the industry, so it is about that industry, not a list
            # of others (live HCX-005 chose rank_industries here and dropped 분식).
            about = to_classification("market_data", {"place": args.get("place"), "topics": list(DEFAULT_TOPICS),
                                                      "unavailable": args.get("unavailable")},
                                      rule=rule, question=question, use_morph=use_morph, today=today)
            return {**about, "topics_defaulted": True,
                    "reasons": [*about["reasons"], "업종을 말한 질문이라 업종 추천 대신 그 업종의 상권 자료"]}
        new_slots["locations"] = found(args.get("place"), "locations")[:1]
        # Only what the user asked to leave out ('카페 말고'), never an exclusion the model added on its own.
        excluded = _texts(args.get("exclude_industries")) if _EXCLUDE.search(question) else []
        new_slots["excluded_industries"] = [m for text in excluded for m in found(text, "industries")] \
            or slots.get("excluded_industries") or []
        return {**base, "domain": "market_analysis", "turn_type": "industry_rank", "topics": ["industry_rank"],
                "slots": new_slots}
    if name in ("ask_user", "small_talk", "out_of_scope"):
        turn = {"ask_user": "clarify", "small_talk": "smalltalk", "out_of_scope": "out_of_scope"}[name]
        return {**base, "domain": "general", "turn_type": turn, "topics": [], "slots": new_slots,
                "ai_reply": safe_reply(args.get("reply"))}
    if name == "handoff" and args.get("domain") in ("marketing", "customer"):
        return {**base, "domain": args["domain"], "turn_type": "handoff", "topics": [], "slots": new_slots}
    return None
