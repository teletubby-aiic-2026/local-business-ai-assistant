"""Rule-based question classifier for the market-analysis assistant.

``classify(text)`` reads one user message and returns which domain should
answer it, what kind of turn it is, which fact-card topics are relevant, and
the location / industry / period candidates it found. It never calls a model.
When the message is too unclear for rules, ``needs_model`` is true so that the
caller can ask a model to choose among the returned candidates.

Field names follow the team convention (snake_case, null for missing values).
"""
from __future__ import annotations

from datetime import date
import re
import unicodedata

from app.assistant.lexicon import bare_place_keys, compact, industry_index, keywords, place_index
from app.assistant.morph import get_analyzer

SCHEMA = "assistant-intent-v1"
TOPIC_ORDER = ("sales_total", "sales_weekday", "sales_time", "sales_age", "stores_count",
               "stores_open_close", "population", "change_qoq", "change_yoy", "comparison", "ranking", "industry_rank")
_MORPH_TAGS = ("NN", "VV", "VA", "XR", "NP", "MM", "MA")
_COUNT = re.compile(r"(?:top|탑|상위|베스트)\s*(\d)|(\d|한|두|세|네|다섯)\s*(?:가지|개|종류|군데|순위)")
_KOREAN_COUNT = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5}
DEFAULT_TOPICS = ("sales_total", "stores_count", "change_yoy")
_DISTRIBUTION = ("sales_weekday", "sales_time", "sales_age")
_SUBJECTS = ("sales_total", *_DISTRIBUTION, "stores_count", "stores_open_close", "population")
_CHANGE = ("change_qoq", "change_yoy")


class _Text:
    """Original text, its compact form, and optional morphemes in compact offsets."""

    def __init__(self, text: str, analyzer):
        self.raw = unicodedata.normalize("NFC", text or "").strip()
        chars, raw_to_compact = [], {}
        for index, char in enumerate(self.raw):
            if char.isspace():
                continue
            raw_to_compact[index] = len(chars)
            lowered = char.lower()
            chars.append(lowered if len(lowered) == 1 else char)
        self.compact = "".join(chars)
        # Compact offsets where a whitespace-separated word (어절) begins.
        self.word_starts = {pos for raw_index, pos in raw_to_compact.items()
                            if raw_index == 0 or self.raw[raw_index - 1].isspace()}
        self.morphemes = analyzer.analyze(self.raw) if analyzer is not None else None
        self.token_starts = self.token_ends = None
        if self.morphemes is not None:
            self.token_starts = {raw_to_compact[m.start] for m in self.morphemes if m.start in raw_to_compact}
            last = [m.start + m.length - 1 for m in self.morphemes]
            self.token_ends = {raw_to_compact[i] + 1 for i in last if i in raw_to_compact}
            self.morph_positions = [raw_to_compact.get(m.start) for m in self.morphemes]

    def has(self, words) -> bool:
        return any(word and word in self.compact for word in words)

    def first(self, words):
        hits = [self.compact.find(word) for word in words if word and word in self.compact]
        return min(hits) if hits else None


def _scan(text: _Text, index: dict, reasons: list, label: str, bare_keys=frozenset()) -> list[dict]:
    """Longest-first, non-overlapping dictionary matches on the compact text.

    Short bare forms (강남, 을지로) must start a word; with Kiwi they must also
    be a whole morpheme sequence. Full names (강남역, 을지로동) may appear
    anywhere so that text typed without spaces still works.
    """
    if not index:
        return []
    max_len = max(len(key) for key in index)
    found, i, n = [], 0, len(text.compact)
    while i < n:
        hit = None
        for length in range(min(max_len, n - i), 1, -1):
            key = text.compact[i:i + length]
            if key not in index:
                continue
            if text.token_starts is not None and i not in text.token_starts:
                reasons.append(f"{label} '{key}' 무시: 형태소 경계가 아님")
                continue
            if key in bare_keys:
                if text.token_ends is not None and (i + length) not in text.token_ends:
                    reasons.append(f"{label} '{key}' 무시: 형태소 중간에서 끝남")
                    continue
                if text.token_starts is None and i not in text.word_starts:
                    reasons.append(f"{label} '{key}' 무시: 어절 중간에서 시작")
                    continue
            hit = {"text": key, "start": i, "candidates": index[key]}
            break
        if hit:
            found.append(hit)
            i += len(hit["text"])
        else:
            i += 1
    return found


def _correction_position(text: _Text, kw: dict):
    markers = kw["correction_markers"]
    if text.morphemes is None:
        return text.first(markers)
    # With morphemes, 말고/말구 must really be the verb 말다 + connective,
    # so that words such as 말고기 do not count as a correction.
    positions = []
    for word in markers:
        start = text.compact.find(word)
        if start < 0:
            continue
        if word in ("말고", "말구"):
            continue
        positions.append(start)
    for (form, tag, next_form, next_tag) in kw["correction_lemmas"]:
        for k, morpheme in enumerate(text.morphemes[:-1]):
            following = text.morphemes[k + 1]
            if (morpheme.form == form and morpheme.tag.startswith(tag)
                    and following.form in (next_form, "구") and following.tag.startswith(next_tag)):
                position = text.morph_positions[k]
                if position is not None:
                    positions.append(position)
    return min(positions) if positions else None


def _change_detected(text: _Text, kw: dict, reasons: list) -> bool:
    if text.morphemes is None:
        return text.has(kw["change_words"])
    lemmas = kw["change_lemmas"]
    for k, m in enumerate(text.morphemes):
        if m.tag.startswith("VV") and m.form in lemmas["verbs"]:
            reasons.append(f"변화 동사 '{m.form}다'")
            return True
        if m.tag.startswith("NNG") and m.form in lemmas["nouns"]:
            reasons.append(f"변화 명사 '{m.form}'")
            return True
        if m.tag.startswith("VA") and m.form in lemmas["become_adjectives"]:
            if any(n.form == "지" and n.tag.startswith("VX") for n in text.morphemes[k + 1:k + 4]):
                reasons.append(f"변화 표현 '{m.form}아지다'")
                return True
    if text.has(kw["change_words"]):
        reasons.append("변화 단어가 있으나 형태소상 변화 동사가 아님")
    return False


def _period(text: _Text, kw: dict, today: date) -> tuple[dict, tuple | None]:
    """Return the period slot and the compact span of an explicit quarter."""
    c = text.compact
    code, span = None, None
    patterns = ((r"(20\d{2})년([1-4])분기", lambda m: m.group(1)),
                (r"(올해|금년|이번년도|이번년|이번해)([1-4])분기", lambda m: str(today.year)),
                (r"(작년|지난해|전년)([1-4])분기", lambda m: str(today.year - 1)))
    for pattern, year in patterns:
        match = re.search(pattern, c)
        if match:
            code, span = year(match) + match.group(2), match.span()
            break
    rest = c if span is None else c[:span[0]] + " " + c[span[1]:]
    comparison = None
    if any(marker in rest for marker in kw["period"]["qoq_markers"]):
        comparison = "qoq"
    elif any(marker in rest for marker in kw["period"]["yoy_markers"]):
        comparison = "yoy"
    relative = "latest" if code is None and any(m in c for m in kw["period"]["relative_latest"]) else None
    return {"relative": relative, "comparison": comparison, "period_code": code}, span


_TRAILING = re.compile(r"[\s.!~,…ㅠㅜㅋㅎ^;]+$")
_FIGURE = re.compile(r"\d+(?:%|프로|퍼센트|만원|천원|원|만)|\d{2,}(?:정도|쯤|찍|나와|벌)|반토막|절반")


def _is_question(text: _Text, kw: dict) -> bool:
    if "?" in text.raw:
        return True
    tail = _TRAILING.sub("", text.compact)
    return any(tail.endswith(ending) for ending in kw["question_endings"])


def _last_position(text: _Text, words) -> int:
    return max((text.compact.rfind(word) for word in words if word and word in text.compact), default=-1)


def _condition_change(text: _Text, kw: dict, slots_end: set[int]) -> bool:
    """바꿔·변경 anywhere; '로 볼래'·'기준으로' only right after a place, industry or quarter."""
    if text.has(kw["condition_change_markers"]):
        return True
    for marker in kw["condition_change_after_slot"]:
        start = text.compact.find(marker)
        while start >= 0:
            # Allow one particle-like character between the slot and the marker (역삼역+으로).
            if start in slots_end or (start - 1) in slots_end:
                return True
            start = text.compact.find(marker, start + 1)
    return False


def _ordered(topics) -> list[str]:
    return [topic for topic in TOPIC_ORDER if topic in topics]


def _excluded_places(text: _Text, places: list[dict], kw: dict) -> list[dict]:
    """Places directly followed by 말고 / 빼고 / 제외: '강남 말고', '홍대 쪽은 빼고'."""
    pattern = re.compile(kw["exclude_after_place_pattern"])
    return [m for m in places if pattern.match(text.compact[m["start"] + len(m["text"]):])]


def _ranking_requested(text: _Text, kw: dict, topics: set, excluded: list, others: list) -> bool:
    """'어디가 좋아?', '매출 높은 곳 추천해줘', '카페 매출 순위', '강남 말고 다른 데'.

    Two or more places that are not excluded make it a comparison, not a ranking.
    """
    if len(others) > 1:
        return False
    c = text.compact
    if re.search(kw["ranking_where_pattern"], c):
        return True
    if re.search(kw["ranking_place_pattern"], c) and text.has(kw["ranking_request_words"]):
        return True
    # A request that ends with the place noun: '카페 잘되는 곳', '매출 높은 동네는?'
    if re.search("(" + kw["ranking_place_pattern"] + ")(은|는|이|좀|들)?$", _TRAILING.sub("", c.replace("?", ""))):
        return True
    if text.has(kw["ranking_order_words"]) and (text.has(kw["topics"]["sales"]) or "상권" in c) \
            and not topics.intersection(_DISTRIBUTION):
        return True
    return bool(excluded) and bool(re.search(kw["ranking_other_place_pattern"], c))


def _industry_recommend_requested(text: _Text, kw: dict, named_industries: list) -> bool:
    """'추천해줄 만한 업종', '여기서 뭐 하면 장사 잘 될까?', '무슨 가게 차리면 좋아?'.

    Signals come from Kiwi morphemes (추천/NNG, 업종/NNG, 뭐/NP + 하/VV, 잘/MAG)
    or, when Kiwi is off or splits a word oddly (가게 -> 가/VV + 게/EC), from the
    compact text. A named industry that is not excluded makes it a question
    about that industry instead.
    """
    if named_industries:
        return False
    morph, rules = kw["industry_recommend_morph"], kw["industry_recommend_rules"]
    forms = set()
    if text.morphemes is not None:
        forms = {m.form for m in text.morphemes if m.tag.startswith(_MORPH_TAGS)}

    def has(key):
        return bool(forms.intersection(morph[key])) or text.has(rules[key])

    strong, recommend, ask = has("strong_nouns"), has("recommend_words"), has("interrogatives")
    target, good, request = has("weak_targets"), has("qualifiers"), has("request_verbs")
    return (strong and (recommend or ask or good or request)) or (recommend and target) or (ask and target and good)


def requested_count(raw: str) -> int | None:
    match = _COUNT.search(raw.lower())
    if not match:
        return None
    value = match.group(1) or match.group(2)
    number = int(value) if value.isdigit() else _KOREAN_COUNT[value]
    return max(1, min(5, number))


def _place_choice_needed(mentions: list[dict], comparison: bool) -> bool:
    if comparison:
        return len(mentions) < 2 or any(len(m["candidates"]) > 1 for m in mentions)
    labels = {tuple(sorted(c["label"] for c in m["candidates"])) for m in mentions}
    return any(len(m["candidates"]) > 1 for m in mentions) or len(labels) > 1


def classify(message: str, *, context: dict | None = None, today: date | None = None,
             use_morph: bool = True) -> dict:
    context = context or {}
    today = today or date.today()
    kw = keywords()
    analyzer = get_analyzer() if use_morph else None
    text = _Text(message, analyzer)
    reasons: list[str] = []

    # 1. Slots and signals ---------------------------------------------------
    places = _scan(text, place_index(), reasons, "위치", bare_place_keys())
    industries = _scan(text, industry_index(), reasons, "업종")
    all_industries = industries
    excluded = _excluded_places(text, places, kw)
    others = [m for m in places if m not in excluded]
    excluded_industries = _excluded_places(text, industries, kw)  # '카페 말고' works the same way
    named_industries = [m for m in industries if m not in excluded_industries]
    correction_at = _correction_position(text, kw)
    if correction_at is not None:
        later_places = [m for m in places if m["start"] > correction_at]
        later_industries = [m for m in industries if m["start"] > correction_at]
        if later_places or later_industries:
            # "A 말고 B": keep B. Without a new place or industry after it,
            # "우리 학원 말고 경쟁하는 데" is not a correction.
            reasons.append("정정 표현")
            places = later_places or places
            industries = later_industries or industries
        else:
            reasons.append("'말고' 등이 있으나 뒤에 새 조건이 없어 정정이 아님")
            correction_at = None
    period, period_span = _period(text, kw, today)
    change = _change_detected(text, kw, reasons)
    question = _is_question(text, kw)
    customer_words = text.has(kw["customer_words"])
    figures = bool(_FIGURE.search(text.compact))
    personal = text.has(kw["personal_words"]) or (figures and not question and not places)
    # 저희 빵집 / 동물병원인데 / 네일샵이야 -> the speaker runs that business.
    own_business = False
    for mention in all_industries:
        before = text.compact[:mention["start"]]
        after = text.compact[mention["start"] + len(mention["text"]):]
        if any(before.endswith(word) for word in kw["personal_before_industry"]) \
                or any(after.startswith(word) for word in kw["operating_after_industry"]):
            own_business = True
    if text.has(kw["planning_words"]):
        status = "planning"
    elif text.has(kw["personal_words"]) or text.has(kw["operating_words"]) or customer_words or own_business:
        status = "operating"
    else:
        status = None

    topics: set[str] = set()
    for topic in ("sales_weekday", "sales_time", "sales_age", "stores_count", "stores_open_close", "population"):
        if text.has(kw["topics"][topic]):
            topics.add(topic)
    # 미용실 수 / 치킨집 몇 개 / 분식집이랑 치킨집 중에 어느 쪽이 더 많아
    for mention in industries:
        after = text.compact[mention["start"] + len(mention["text"]):]
        if any(after.startswith(word) for word in kw["count_after_industry"]):
            topics.add("stores_count")
    if industries and text.has(kw["many_words"]) \
            and not topics.intersection(("population", "stores_open_close", *_DISTRIBUTION)) \
            and not text.has(kw["topics"]["sales"]):
        topics.add("stores_count")
    if text.has(kw["topics"]["sales"]) and not topics.intersection(_DISTRIBUTION):
        topics.add("sales_total")
    if change or period["comparison"]:
        topics.add("change_qoq" if period["comparison"] == "qoq" else "change_yoy")
        if change and "stores_count" in topics:
            topics.add("stores_open_close")
    area_comparison = text.has(kw["comparison_words"]) and (
        len(places) >= 2 or (text.has(kw["comparison_scope_words"]) and not (period["comparison"] and len(places) < 2)))
    if area_comparison:
        topics.add("comparison")
        topics.difference_update(_CHANGE if not change else ())

    has_slot = bool(places or industries or period["period_code"])
    slot_ends = {m["start"] + len(m["text"]) for m in places + industries}
    if period_span is not None:
        slot_ends.add(period_span[1])
    market_words = text.has(kw["market_words"])
    marketing_words = text.has(kw["marketing_words"]) or text.has(kw["growth_cues"])
    industry_rank = not area_comparison and len(others) <= 1 and _industry_recommend_requested(text, kw, named_industries)
    ranking = not area_comparison and not industry_rank and _ranking_requested(text, kw, topics, excluded, others)

    # 2. Domain and turn type --------------------------------------------------
    domain, turn, needs_model = "market_analysis", None, False
    if question and text.has(kw["out_of_scope_words"]):
        domain = "customer" if customer_words else "general"
        turn = "out_of_scope"
    elif customer_words and marketing_words:
        # Korean puts the request at the end, so the later keyword names the domain.
        later_marketing = max(_last_position(text, kw["marketing_words"]), _last_position(text, kw["growth_cues"]))
        domain = "marketing" if later_marketing > _last_position(text, kw["customer_words"]) else "customer"
        turn = "handoff" if domain == "customer" or text.has(kw["marketing_task_verbs"]) else "advice"
        needs_model = True
        reasons.append("고객관리와 마케팅 단어가 함께 나옴: 뒤에 나온 분야를 우선")
    elif customer_words:
        domain, turn = "customer", "handoff"
    elif marketing_words:
        domain = "marketing"
        turn = "handoff" if text.has(kw["marketing_task_verbs"]) else "advice"
    elif personal and figures and not places and not text.has(kw["personal_scope_words"]):
        turn = "personal_metric"
    elif industry_rank:
        turn = "industry_rank"
        reasons.append("업종 추천 질문: 상권 안 업종별 분기 추정매출을 코드가 정렬함")
    elif ranking:
        turn = "ranking"
        reasons.append("순위 질문: 공식 상권의 분기 추정매출을 코드가 정렬함")
        if excluded:
            reasons.append("제외할 위치: " + ", ".join(m["text"] for m in excluded))
    elif (correction_at is not None or _condition_change(text, kw, slot_ends)) and has_slot:
        turn = "condition_change"
    elif context.get("previous_topics") and (
            any(text.compact.startswith(word) for word in kw["followup_starts"])
            or (len(text.compact) <= 12 and (topics or period["comparison"] or text.has(kw["followup_reference_words"])))
            or (not has_slot and not topics.difference(_CHANGE) and text.has(kw["followup_reference_words"]))):
        turn = "followup"
        new = topics.difference(_CHANGE)
        topics = (new or set(context["previous_topics"])) | topics.intersection(_CHANGE)
        if "왜" in text.compact or "이유" in text.compact:
            needs_model = True
            reasons.append("원인 질문: 수치는 카드로, 설명은 모델이 맡되 원인을 단정하지 않음")
    elif text.has(kw["feedback_words"]) and not has_slot:
        domain, turn = "general", "smalltalk"
        reasons.append("답변에 대한 불만 표현")
    elif text.has(kw["venting_words"]) and (not question or not has_slot):
        domain, turn = "general", "smalltalk"
        reasons.append("하소연: 장소·업종·기간이 없거나 질문이 아님")
    elif topics or places or industries or area_comparison or market_words:
        turn = "data_question"
        if "왜" in text.compact:
            needs_model = True
            reasons.append("원인 질문: 수치는 카드로, 설명은 모델이 맡되 원인을 단정하지 않음")
    elif text.has(kw["smalltalk_words"]):
        domain, turn = "general", "smalltalk"
    else:
        domain, turn, needs_model = "general", "unknown", True
        reasons.append("분야와 의도를 정하지 못함")

    defaulted = False
    if domain != "market_analysis":
        topics = set()
    elif turn == "ranking":
        # Only quarterly sales can be ranked across Seoul; other topics are answered per market.
        topics = {"ranking"}
        places = others
    elif turn == "industry_rank":
        topics = {"industry_rank"}
        places, industries = others, []
    elif turn == "data_question" and not topics.intersection(_SUBJECTS) and "comparison" not in topics:
        topics |= {"sales_total", "stores_count"}
        if not topics.intersection(_CHANGE):
            topics.add("change_yoy")
        defaulted = True

    # 3. Does the user have to pick a candidate? --------------------------------
    needs_choice = False
    codes = {c["code"] for m in industries for c in m["candidates"]}
    if domain == "market_analysis" and turn in ("data_question", "condition_change", "followup"):
        needs_choice = _place_choice_needed(places, "comparison" in topics) if (places or "comparison" in topics) else False
        if "comparison" not in topics and len(codes) > 1:
            needs_choice = True
    elif turn == "ranking":
        needs_choice = len(codes) > 1

    return {
        "schema_version": SCHEMA,
        "text": text.raw,
        "domain": domain,
        "turn_type": turn,
        "topics": _ordered(topics),
        "topics_defaulted": defaulted,
        "slots": {
            "locations": [{"text": m["text"], "candidates": m["candidates"]} for m in places],
            # Only a ranking uses these: places the user asked to leave out (강남 말고).
            "excluded_locations": [{"text": m["text"], "candidates": m["candidates"]}
                                   for m in (excluded if turn == "ranking" else [])],
            "industries": [{"text": m["text"], "candidates": m["candidates"]} for m in industries],
            # Only an industry recommendation uses these two.
            "excluded_industries": [{"text": m["text"], "candidates": m["candidates"]}
                                    for m in (excluded_industries if turn == "industry_rank" else [])],
            "count": requested_count(text.raw) if turn in ("industry_rank", "ranking") else None,
            "period": period,
            "business_status": status,
        },
        "signals": {"correction": correction_at is not None, "comparison": area_comparison,
                    "personal_metric": personal, "change": change},
        "needs_user_choice": needs_choice,
        "needs_model": needs_model,
        "analyzer": analyzer.name if analyzer is not None else "rules",
        "reasons": reasons,
    }


_CONTENT_TAGS = ("NNG", "NNP", "NNB", "NP", "VV", "VA", "XR", "MM", "MAG", "SN", "SL")


def content_morphemes(message: str, *, use_morph: bool = True) -> list[str]:
    """'연남동/NNP 창업/NNG 하/VV …' for the planner. Empty when Kiwi is off or not installed."""
    analyzer = get_analyzer() if use_morph else None
    if analyzer is None:
        return []
    return [f"{m.form}/{m.tag}" for m in analyzer.analyze(unicodedata.normalize("NFC", message or ""))
            if m.tag.startswith(_CONTENT_TAGS)][:40]


def scan_slots(text: str, *, use_morph: bool = True, today: date | None = None) -> dict:
    """Dictionary matches inside any short text, e.g. a place or industry the planner named.

    The planner may only point at places and industries; their codes always come
    from these dictionaries, never from the model.
    """
    analyzer = get_analyzer() if use_morph else None
    t = _Text(text, analyzer)
    reasons: list[str] = []
    places = _scan(t, place_index(), reasons, "위치", bare_place_keys())
    industries = _scan(t, industry_index(), reasons, "업종")
    period, _span = _period(t, keywords(), today or date.today())
    return {"locations": [{"text": m["text"], "candidates": m["candidates"]} for m in places],
            "industries": [{"text": m["text"], "candidates": m["candidates"]} for m in industries],
            "period": period}


def location_labels(result: dict) -> list[str]:
    return sorted({c["label"] for m in result["slots"]["locations"] for c in m["candidates"]})


def industry_codes(result: dict) -> list[str]:
    return sorted({c["code"] for m in result["slots"]["industries"] for c in m["candidates"]})
