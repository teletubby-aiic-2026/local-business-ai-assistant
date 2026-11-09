# 원본: PR #13 `0f4d0fc`(주현석) services/market-analysis/app/assistant/answer_check.py 에서 복사. #13 병합 뒤 한 곳으로 합침. 이 복사본은 수정하지 않는다.
"""Check a written answer against the fact cards it was given.

A model answer is published only if every number it states appears on a card
it cites, every citation names a card from this turn, every quarter it names
(2026년 2분기) appears on a card, and it avoids phrases that turn area
statistics into claims about the owner's shop or causes.

Interpretation is allowed only on its own line that starts with "해석:"
(user decision 2026-11-08): no statistics, no talk of changes, hedged
wording such as '~일 수 있어요' or '~를 시사해요'. Causes and good/bad verdicts
stay forbidden everywhere; hedges such as '것으로 보' are forbidden on fact lines.
"""
from __future__ import annotations

import re

_CITATION = re.compile(r"\[(F\d+)\]")
_CITATION_GROUP = re.compile(r"((?:\[F\d+\]\s*)+)")
_NUMBER = re.compile(r"(?<![\w.])([+-]?\d[\d,]*(?:\.\d+)?)(%?)")
# Numbers that are labels, not statistics: 2026년, 2분기, 20대, 11~14시, 3호선 ...
_LABEL_SUFFIX = re.compile(r"^\s*(?:년|분기|대|시|월|일|호선|번|층|위|개월|가|동|~)")
# Year and quarter digits are skipped as labels above, so quarters are checked by name.
_PERIOD = re.compile(r"(\d{4})\s*년\s*([1-4])\s*분기")
# Time ranges such as 11~14시 or 11~14 are labels even when the model drops 시.
_TIME_RANGE = re.compile(r"\d{1,2}\s*~\s*\d{1,2}(?:\s*시)?")
INSIGHT = "해석:"
# Recommendation wording. Allowed only in an opinion answer, which the user asked for and which rests on the
# opinion card's criteria (user decision 2026-11-08: '자료 기반으로 의견을 내 달라').
RECOMMEND = ("추천해요", "추천합니다", "추천드", "추천할 만", "추천할만", "여시는 것을", "여는 것을")
ALWAYS_FORBIDDEN = ("사장님 가게의 매출은", "사장님 가게 매출은", "가게 매출이 오", "확실히 오", "무조건", "보장", "반드시 오",
                    "성공", "대박", "망하", "망할",
                    # Data shows sales, not where or what to open.
                    *RECOMMEND,
                    # Causes: the cards only show changes that happened in the same period.
                    "때문", "초래", "요인", "로 인해", "탓", "덕분에", "영향으로", "영향을 미", "영향을 줬", "영향을 준",
                    # Verdicts the cards do not state.
                    "좋아졌", "나빠졌", "나아졌", "악화", "호전")
# Descriptions no card can support ('개성 있는 가게들이 많아 매력적인 곳', 'HCX-005 2026-11-08 server test').
UNSUPPORTED = ("개성", "매력", "분위기", "트렌디", "핫플", "유명", "입점해", "선택의 폭", "다양한 업종", "감성",
               # Meanings read into a count ('그만큼 수요가 많은 업종이라는 뜻이기도 해요', 2026-11-08 replay).
               "수요가 많", "의미일 수", "뜻이기도",
               # The population figure is a quarterly source index, not people per day ('하루 유동 인구 35,911명').
               "하루 유동", "하루 방문", "일평균 유동", "일일 유동",
               # Nothing on the cards counts offices, homes, workers, students or tourists.
               "오피스", "거주지", "주거지", "직장인", "학생", "관광객")
# The cards hold sales; what is left after costs is on none of them, interpretation lines included.
PROFIT_WORDS = ("수익", "순이익", "수입이", "수입은")
# Hedged guesses: allowed only on an interpretation line ('직장인이 많이 찾을 것으로 예상됩니다' on a fact line,
# HCX-005 2026-11-08).
HEDGES = ("것으로 보", "가능성이 있", "가능성이 커", "가능성이 높", "예상됩", "예상돼", "예상해", "예상할", "짐작", "시사")
# What kind of place a market is: nothing on the cards says so, on any line, interpretation or not
# ('가산은 IT 위주의 산업 단지지만 … 패션 아울렛', 2026-11-08 server test).
WORLD = ("아울렛", "산업 단지", "산업단지", "IT ", "IT단지", "대학가", "관광지", "주택가", "아파트 단지", "아파트단지",
         "오피스 상권", "오피스 밀집", "유흥가", "학원가", "번화가")
FORBIDDEN = ALWAYS_FORBIDDEN + HEDGES  # the strictest set, for short replies without cards
_CHANGE_WORDS = re.compile(r"감소|증가|줄었|늘었|줄어|늘어|줄면|늘면|떨어|올랐|하락|상승|변화")


def is_insight(line: str) -> bool:
    return line.strip().startswith(INSIGHT)


# '점포 1곳당 유동인구': the 1 belongs to the name of the measure (rejected as a number, 2026-11-08 server test).
_PER_ONE = re.compile(r"\d+\s*곳\s*당")


def statistics(segment: str, cards: list[dict]) -> list[str]:
    """Numbers in a piece of text that are statistics, not labels such as 2026년, 20대, 11~14시 or names."""
    segment = _PER_ONE.sub(" ", _CITATION.sub(" ", segment))
    for name in _names(cards):
        segment = segment.replace(name, " ")
    segment = _TIME_RANGE.sub(" ", segment)
    return [m.group(0) for m in _NUMBER.finditer(segment) if not _LABEL_SUFFIX.match(segment[m.end():])]


def interpretation_line(line: str, cards: list[dict]) -> bool:
    """A hedged line with no statistics and no talk of changes or causes: it may stand as '해석:'."""
    return (any(h in line for h in HEDGES) and not statistics(line, cards) and not _CHANGE_WORDS.search(line)
            and not any(p in line for p in ALWAYS_FORBIDDEN))


def _segments(text):
    """(text, citations) pairs. Numbers belong to the citations that follow them on the same line."""
    for line in text.splitlines():
        if line.strip().startswith("참고:") or is_insight(line):
            continue  # card warnings copied verbatim, and interpretation lines checked on their own
        parts = _CITATION_GROUP.split(line)
        for index in range(0, len(parts), 2):
            following = parts[index + 1] if index + 1 < len(parts) else ""
            yield parts[index], _CITATION.findall(following)


def _card_numbers(cards) -> tuple[set, set]:
    plain, percent = set(), set()
    for card in cards:
        for value in card.get("values", []):
            for key in ("value", "share_percent"):
                number = value.get(key)
                if isinstance(number, bool) or not isinstance(number, (int, float)):
                    continue
                if key == "share_percent" or value.get("unit") == "%":
                    percent.add(round(abs(float(number)), 2))
                else:
                    plain.add(abs(float(number)))
    return plain, percent


def _names(cards) -> list[str]:
    """Market, industry and period names on the cards. Digits inside them are not statistics."""
    names = set()
    for card in cards:
        for value in card.get("values", []):
            if isinstance(value.get("value"), str) and any(ch.isdigit() for ch in value["value"]):
                names.add(value["value"])
            if isinstance(value.get("label"), str) and any(ch.isdigit() for ch in value["label"]):
                names.add(value["label"])
    return sorted(names, key=len, reverse=True)


def _periods(text: str) -> set:
    return {(year, quarter) for year, quarter in _PERIOD.findall(text)}


# One market's figures told as a whole 구's ('강남구 상권은 …' for 신논현역 alone, 2026-11-08 user test).
_DISTRICT = re.compile(r"(?<![가-힣])(종로구|중구|용산구|성동구|광진구|동대문구|중랑구|성북구|강북구|도봉구|노원구|은평구|"
                       r"서대문구|마포구|양천구|강서구|구로구|금천구|영등포구|동작구|관악구|서초구|강남구|송파구|강동구)")


# Industry words an answer may use only when the cards are about that industry: '강남역에서 한식을 파는 게
#유리할 것 같아요' was written for 커피-음료 cards (2026-11-08 server test).
_INDUSTRY_WORDS = {"한식": "한식", "중식": "중식", "일식": "일식", "양식": "양식", "치킨": "치킨", "분식": "분식",
                   "카페": "커피", "커피": "커피", "호프": "주점", "술집": "주점", "편의점": "편의점", "미용실": "미용",
                   "빵집": "제과", "베이커리": "제과"}


def _industry_problems(text: str, words: str) -> list[dict]:
    found = []
    for word, family in _INDUSTRY_WORDS.items():
        if word in text and family not in words and word not in words:
            found.append({"type": "industry_not_on_card", "detail": word})
    return found


# A figure under a name of the model's own: "'일반 음식점'(173곳)" for 일반 점포 173개 (2026-11-08 replay).
_QUOTED_FIGURE = re.compile(r"['‘\"“]([^'’\"”\n]{2,20})['’\"”]\s*\(?\s*\d")
_OTHER_INDUSTRIES = re.compile(r"다른\s*업종\s*(?:중|가운데)")
_DENIAL = re.compile(r"없(?:어요|습니다|네요|다|음|는데요)")


def _card_words(cards) -> str:
    """Every string on the cards (text, values, warnings, excluded places), for place-name checks."""
    parts = []

    def walk(item):
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            for value in item.values():
                walk(value)
        elif isinstance(item, (list, tuple)):
            for value in item:
                walk(value)

    walk(cards)
    return "\n".join(parts)


def _card_periods(cards) -> set:
    found = set()
    for card in cards:
        found |= _periods(card.get("text") or "")
        for value in card.get("values", []):
            if isinstance(value.get("value"), str):
                found |= _periods(value["value"])
    return found


# Comparisons the cards can settle. '점심이 저녁보다 잘 팔려요' was published while 저녁 was larger
# (2026-11-08 user test): the numbers were right, the sentence around them was not.
_MORE = re.compile(r"많|높|커|크게|크고|크다|큰|잘\s*(?:팔|되|돼|나가|나와)|앞서|우세|유리|넓")
_LESS = re.compile(r"적(?:어|은|게|다|고|네|지)|낮|작(?:아|은|게|다|고|네)|덜|뒤처|불리|좁|못\s*(?:미치|팔)")
_NEGATED = re.compile(r"지\s*(?:않|못)|아니")
_SENTENCES = re.compile(r"(?<=[.!?])\s+|지만|반면|는데")
_SUPERLATIVE = re.compile(r"가장|제일|최고")
# '일반 점포는 오히려 연남동이 훨씬 적고' (2026-11-08 server test): two markets, one named, a comparative word.
_COMPARATIVE = re.compile(r"더|훨씬|오히려|압도적")
_CLAUSES = re.compile(r",\s+")
# What may stand between the compared item and 보다: '저녁보다', '저녁 매출보다', '강남역 쪽보다'.
_GAP = re.compile(r"\s*(?:의\s*)?(?:매출|시간대|시간|연령대|손님|유동인구|상권|쪽|점포 수|점포)?\s*"
                  r"(?:[+-]?\d[\d,.]*\s*(?:원|명|개|곳|%)?)?\s*(?:\([^)]*\))?\s*")
TIME_WORDS = {"새벽": "00~06시", "아침": "06~11시", "오전": "06~11시", "점심": "11~14시", "오후": "14~17시",
              "저녁": "17~21시", "퇴근": "17~21시", "밤": "21~24시", "야간": "21~24시", "심야": "21~24시"}
_DAY_WORDS = {f"{day}요일": day for day in "월화수목금토일"}
_HOURS = re.compile(r"(오전|오후)?\s*(\d{1,2})\s*시?\s*(?:부터|~|-|에서)\s*(오전|오후)?\s*(\d{1,2})\s*시")
_POPULATION_WORDS = re.compile(r"사람|유동|인구|붐비|지나")
_SALES_WORDS = re.compile(r"매출|팔|벌|돈")
# Market metrics named in a sentence -> card labels, the most specific first ('점포당 매출' before '매출').
_PER_STORE = r"(?:점포|가게)\s*(?:1\s*곳|한\s*곳|하나)?\s*당"
_MARKET_METRICS = (
    (re.compile(_PER_STORE + r".{0,6}유동"), ("점포 1곳당 유동인구",)),
    (re.compile(_PER_STORE + r".{0,6}직장"), ("점포 1곳당 직장인구",)),
    (re.compile(_PER_STORE + r".{0,6}(?:상주|주민|거주)"), ("점포 1곳당 상주인구",)),
    (re.compile(_PER_STORE + r".{0,6}세대"), ("점포 1곳당 세대 수",)),
    (re.compile(_PER_STORE), ("점포당 분기 추정매출",)),
    (re.compile(r"폐업\s*(?:비율|률)"), ("최근 1년 폐업 비율", "폐업 비율")),
    (re.compile(r"변화율|증가율|성장|작년|최근\s*1년(?!\s*폐업)"), ("최근 1년 매출 변화율", "작년 같은 분기 대비 매출 변화율")),
    (re.compile(r"프랜차이즈"), ("프랜차이즈 점포",)),
    (re.compile(r"일반\s*(?:점포|가게)"), ("일반 점포",)),
    (re.compile(r"개업"), ("개업 점포",)),
    (re.compile(r"폐업"), ("최근 1년 폐업 점포", "폐업 점포")),
    (re.compile(r"매출"), ("추정매출", "분기 추정매출")),
    (re.compile(r"유동인구|사람|인구"), ("유동인구", "지역 유동인구 원천 총지표")),
    (re.compile(r"점포|가게"), ("전체 점포",)),
)


def market_aliases(name: str) -> list[str]:
    """'연남동(홍대)' -> 연남동(홍대), 연남동, 홍대; '상도역 1번' -> 상도역 1번, 상도역; '강남역' -> 강남역, 강남."""
    found = [name, name.split("(")[0].strip()]
    if "(" in name and ")" in name:
        found.append(name.split("(", 1)[1].split(")", 1)[0].strip())
    found.append(name.split(" ")[0])
    for alias in list(found):
        if alias.endswith("역") and len(alias) > 2:
            found.append(alias[:-1])
    return [alias for alias in dict.fromkeys(found) if len(alias) >= 2]


def _comparables(cards) -> tuple[dict, list]:
    """({group: {member: value}}, [(alias, member, kind)]) for the values a sentence may compare."""
    groups, aliases, markets = {}, [], set()
    for card in cards:
        topic = card.get("topic")
        if card.get("market"):  # a market whose card has no figures can still be named in a sentence
            markets.add(card["market"])
        for value in card.get("values", []):
            number, label = value.get("value"), value.get("label")
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not label or value.get("aggregate"):
                continue
            market = value.get("market")
            if market:
                markets.add(market)
            if topic in ("sales_time", "sales_weekday", "sales_age"):
                # One group per market (multi.py tags each market's cards), and the same label across markets.
                groups.setdefault((topic, "sales", market), {})[label] = number
                if market:
                    groups.setdefault(("market", label), {})[market] = number
            elif topic == "population" and value.get("group") in ("시간대", "연령대"):
                kind = "sales_time" if value["group"] == "시간대" else "sales_age"
                groups.setdefault((kind, "population", market), {})[label] = number
            elif market:
                if value.get("role") in ("delta", "percent"):
                    continue
                groups.setdefault(("market", label), {})[market] = number
    labels = {member for key, members in groups.items() if key[0] != "market" for member in members}
    for label in labels:
        aliases.append((label, label, "time" if label.endswith("시") else "age" if "대" in label else "day"))
        if label == "60대 이상":
            aliases.append(("60대", label, "age"))
    aliases += [(word, label, "time") for word, label in TIME_WORDS.items() if label in labels]
    aliases += [(word, day, "day") for word, day in _DAY_WORDS.items() if day in labels]
    owners = {}
    for market in markets:
        for alias in market_aliases(market):
            owners.setdefault(alias, set()).add(market)
    aliases += [(alias, next(iter(owner)), "market") for alias, owner in owners.items() if len(owner) == 1]
    return groups, sorted(aliases, key=lambda item: -len(item[0]))


def _mentions(sentence: str, aliases: list) -> list[tuple[int, int, str, str]]:
    """(start, end, member, kind) in order, longest alias first, never overlapping."""
    found, taken = [], set()
    for match in _HOURS.finditer(sentence):
        first, second = int(match.group(2)), int(match.group(4))
        if match.group(1) == "오후" and first < 12:
            first += 12
        if (match.group(3) or match.group(1)) == "오후" and second < 12 and second + 12 > first:
            second += 12
        label = f"{first:02d}~{second:02d}시"
        found.append((match.start(), match.end(), label, "time"))
        taken.update(range(match.start(), match.end()))
    for alias, member, kind in aliases:
        start = sentence.find(alias)
        while start >= 0:
            span = range(start, start + len(alias))
            if not taken.intersection(span):
                found.append((start, start + len(alias), member, kind))
                taken.update(span)
            start = sentence.find(alias, start + 1)
    return sorted(found)


def _group_for(kind: str, sentence: str, groups: dict, mentions=()):
    """The values a sentence compares. ``mentions`` settle which market's distribution ('합정역은 30대가 가장
    많아요') or which distribution label across markets ('30대 매출은 강남역이 합정역보다 많아요')."""
    markets = {m[2] for m in mentions if m[3] == "market"}
    labels = {m[2] for m in mentions if m[3] != "market"}
    if kind == "market":
        if len(labels) == 1 and ("market", next(iter(labels))) in groups:
            return "market", next(iter(labels))
        for pattern, names in _MARKET_METRICS:
            if pattern.search(sentence):
                return next((("market", name) for name in names if ("market", name) in groups), None)
        return None
    topic = {"time": "sales_time", "age": "sales_age", "day": "sales_weekday"}[kind]
    market = next(iter(markets)) if len(markets) == 1 else None

    def keys(source=None):
        found = [key for key in groups if key[0] == topic and (source is None or key[1] == source)]
        if market is not None:
            # That market's own cards; a single-market card (no market tag) is about the market being looked at.
            found = [key for key in found if key[2] == market] or [key for key in found if key[2] is None]
        return found

    for words, source in ((_POPULATION_WORDS, "population"), (_SALES_WORDS, "sales")):
        if words.search(sentence) and len(keys(source)) == 1:
            return keys(source)[0]
    return keys()[0] if len(keys()) == 1 else None


def _direction(after: str) -> int:
    more, less = _MORE.search(after), _LESS.search(after)
    if not more and not less:
        return 0
    first = min((m for m in (more, less) if m), key=lambda m: m.start())
    if _NEGATED.search(after[first.end():first.end() + 8]):
        return 0
    return 1 if first is more else -1


def _one_sided(clause: str, sentence: str, aliases: list, groups: dict, market_count: int = 0) -> dict | None:
    """'연남동이 훨씬 적고' between exactly two markets: the named one against the other."""
    named = {m[2] for m in _mentions(clause, aliases) if m[3] == "market"}
    adverb = _COMPARATIVE.search(clause)
    if len(named) != 1 or not adverb:
        return None
    found = _mentions(clause, aliases)
    group = _group_for("market", clause, groups, found) or _group_for("market", sentence, groups, found)
    values = groups.get(group) or {}
    market = next(iter(named))
    direction = _direction(clause[adverb.start():])
    if market_count >= 2 and list(values) == [market] and direction:
        # '노량진역이 훨씬 높아요' while the other market has no figure (2026-11-08 export).
        return {"type": "no_counterpart", "detail": market}
    if len(values) != 2 or market not in values:
        return None
    other = next(value for name, value in values.items() if name != market)
    if (direction > 0 and not values[market] > other) or (direction < 0 and not values[market] < other):
        return {"type": "wrong_comparison", "detail": f"{market} {values[market]} vs {other}"}
    return None


def comparison_problems(text: str, cards: list[dict]) -> list[dict]:
    """'A가 B보다 많아요' and 'A가 가장 많아요' that the card values contradict."""
    groups, aliases = _comparables(cards)
    if not groups:
        return []
    market_count = len({card["market"] for card in cards if card.get("market")})
    problems = []
    for line in text.splitlines():
        clean = _CITATION.sub(" ", line)
        for sentence in _SENTENCES.split(clean):
            mentions = _mentions(sentence, aliases)
            at = sentence.find("보다")
            if at > 0 and mentions:
                right = [m for m in mentions if m[1] <= at and _GAP.fullmatch(sentence[m[1]:at])]
                if right:
                    _start, _end, member_b, kind = right[-1]
                    others = [m for m in mentions if m[3] == kind and m[2] != member_b]
                    group = (_group_for(kind, sentence, groups, mentions)
                             or _group_for(kind, clean, groups, _mentions(clean, aliases)))  # the line's subject
                    direction = _direction(sentence[at + 2:])
                    if others and group and direction:
                        values = groups[group]
                        member_a = others[0][2]
                        if kind == "market" and market_count >= 2 and len(values) == 1 and {member_a, member_b} & set(values):
                            # '강남역보다 노량진역의 매출이 더 높아요' with no sales figure for 강남역.
                            problems.append({"type": "no_counterpart", "sentence": line.strip(), "detail": next(iter(values))})
                        elif member_a in values and member_b in values:
                            a, b = values[member_a], values[member_b]
                            if (direction > 0 and not a > b) or (direction < 0 and not a < b):
                                problems.append({"type": "wrong_comparison", "sentence": line.strip(),
                                                 "detail": f"{member_a} {a} vs {member_b} {b}"})
                continue
            for clause in _CLAUSES.split(sentence):
                problem = _one_sided(clause, sentence, aliases, groups, market_count)
                if problem:
                    problems.append({**problem, "sentence": line.strip()})
            top = _SUPERLATIVE.search(sentence)
            distinct = {(m[2], m[3]) for m in mentions if m[3] != "market"}
            if top and len(distinct) == 1:
                member, kind = next(iter(distinct))
                group = _group_for(kind, sentence, groups, mentions)
                direction = _direction(sentence[top.end():])
                values = groups.get(group) or {}
                if direction and member in values and len(values) > 1:
                    best = max(values.values()) if direction > 0 else min(values.values())
                    if values[member] != best:
                        problems.append({"type": "wrong_superlative", "sentence": line.strip(),
                                         "detail": f"{member} {values[member]}"})
    return problems


_ADVICE = {
    "number_not_on_card": "'{detail}'은 카드에 없는 숫자예요. 카드에 적힌 숫자만 그대로 쓰세요.",
    "uncited_number": "숫자가 있는 줄 끝에 그 숫자가 적힌 카드 번호를 붙이세요.",
    "wrong_comparison": "비교가 카드 값과 반대예요({detail}). 값이 큰 쪽을 크다고 쓰세요.",
    "wrong_superlative": "'가장'이라고 한 항목이 카드에서 가장 크거나 작은 값이 아니에요({detail}).",
    "forbidden_phrase": "'{detail}' 같은 표현은 쓰지 마세요.",
    "promised_card_left_out": "{detail} 카드의 내용도 꼭 함께 말하세요.",
    "opinion_without_numbers": "근거 줄마다 카드의 숫자를 넣으세요.",
    "denies_available_card": "자료가 있는 카드를 없다고 쓰지 마세요.",
    "place_not_on_card": "'{detail}'은 카드에 없는 장소예요. 카드의 상권 이름으로 말하세요.",
    "industry_not_on_card": "'{detail}'은 카드에 없는 업종이에요. 카드의 업종으로만 말하세요.",
    "period_not_on_card": "'{detail}'은 카드에 없는 기간이에요.",
    "unknown_citation": "{detail}은 없는 카드 번호예요.",
    "number_in_interpretation": "해석 줄에는 숫자를 쓰지 마세요.",
    "change_in_interpretation": "해석 줄에서는 증감을 말하지 마세요.",
    "empty_answer": "카드 번호를 붙여서 답하세요.",
    "answer_without_numbers": "질문에 답하는 숫자를 카드에서 한두 개 그대로 옮겨 넣으세요.",
    "verdict_mismatch": "결론이 카드의 종합 판단과 달라요. 카드의 종합 판단과 같은 방향으로 첫 줄을 쓰세요.",
    "tier_mismatch": "서울 안 위치가 카드와 달라요({detail}). 기준마다 그 기준의 구간만 쓰세요.",
    "no_counterpart": "상대 상권에는 이 자료가 없어요. '{detail}'이 더 많다거나 높다는 비교를 빼세요.",
    "term_not_on_card": "'{detail}'은 카드에 없는 항목이에요. 카드의 항목 이름과 숫자만 함께 쓰세요.",
    "industry_list_not_on_card": "다른 업종의 자료가 카드에 없어요. 이 업종 이야기만 하세요.",
    "per_store_misnamed": "'{detail}'은 점포 1곳당 값이에요. '점포당' 또는 '1곳당'이라고 밝혀서 쓰세요.",
}


def feedback(problems: list[dict], cards: list[dict] | None = None) -> str:
    """The checker's findings as instructions for one rewrite."""
    lines = []
    for problem in problems:
        if problem["type"] == "number_not_on_card" and cards:
            # '2,796,964,885' cited with the other market's card: say which card holds it.
            holder = _card_with_number(problem.get("detail") or "", cards)
            if holder:
                advice = f"'{problem['detail']}'은 {holder} 카드의 숫자예요. 그 숫자가 있는 줄 끝에는 [{holder}]를 붙이세요."
                if advice not in lines:
                    lines.append(advice)
                continue
        detail = problem.get("detail")
        if isinstance(detail, list):
            detail = ", ".join(map(str, detail))
        advice = _ADVICE.get(problem["type"], "카드에 있는 내용만 쓰세요.").format(detail=detail or "")
        if advice not in lines:
            lines.append(advice)
    return "\n".join(f"- {line}" for line in lines[:6])


def has_statistics(text: str, cards: list[dict]) -> bool:
    """Any statistic (not a label such as 2026년 or 20대) on a fact line."""
    return any(statistics(segment, cards) for segment, _cited in _segments(text or ""))


_TIERS = ("중상위권", "상위권", "하위권", "중간")
_HIGH_WORDS = re.compile(r"많은\s*편|높은\s*편|큰\s*편")
_LOW_WORDS = re.compile(r"적은\s*편|낮은\s*편|작은\s*편")


_POSITIVE_VERDICT = re.compile(r"해볼\s*만|괜찮아\s*보|좋아\s*보|좋다고\s*봐|추천|차려도\s*좋")
_QUALIFIED = re.compile(r"신중|섞|달라|조건|다만|하지만|중요")


def median_problems(text: str, cards: list[dict]) -> list[dict]:
    """'-2.78%로 서울 중앙값 2.41%보다 높아요' against the two values on the card (2026-11-08 server test)."""
    own, middle = {}, {}
    for card in cards:
        for value in card.get("values", []):
            label, number = value.get("label") or "", value.get("value")
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                continue
            if label.endswith(" 서울 중앙값"):
                middle[label[: -len(" 서울 중앙값")]] = number
            elif value.get("market"):
                own.setdefault(label, []).append(number)
    problems = []
    for line in text.splitlines():
        for sentence in _SENTENCES.split(_CITATION.sub(" ", line)):
            for clause in _CLAUSES.split(sentence):
                at = clause.find("중앙값")
                if at < 0:
                    continue
                names = next((names for pattern, names in _MARKET_METRICS if pattern.search(clause)), None) or \
                    next((names for pattern, names in _MARKET_METRICS if pattern.search(sentence)), ())
                label = next((name for name in names if name in middle), None)
                if label is None or len(own.get(label, [])) != 1:
                    continue
                direction = _direction(clause[at:])
                mine, median = own[label][0], middle[label]
                if (direction > 0 and not mine > median) or (direction < 0 and not mine < median):
                    problems.append({"type": "wrong_comparison", "sentence": clause.strip(), "detail": f"{label} {mine} vs 중앙값 {median}"})
    return problems


def verdict_problems(text: str, cards: list[dict]) -> list[dict]:
    """The conclusion must go the way the four criteria go: '해볼 만해요' for a market weak on all of them."""
    verdicts = [value["verdict"] for card in cards for value in card.get("values", []) if value.get("verdict")]
    if len(verdicts) != 1 or verdicts[0] == "positive":
        return []
    problems = []
    for line in text.splitlines():
        if _POSITIVE_VERDICT.search(line) and not (verdicts[0] == "mixed" and _QUALIFIED.search(line)):
            problems.append({"type": "verdict_mismatch", "detail": verdicts[0], "sentence": line.strip()})
    return problems


def tier_problems(text: str, cards: list[dict]) -> list[dict]:
    """'점포당 매출은 … 중상위권', '폐업률이 낮은 편' checked against that criterion's position on the card.

    The model put the sales-rank tier on per-store sales and judged rates with no comparison (2026-11-08 export).
    """
    tiers: dict = {}
    for card in cards:
        for value in card.get("values", []):
            if value.get("tier"):
                tiers.setdefault(value["criterion"], {})[value.get("market")] = value["tier"]
    if not tiers:
        return []
    _groups, aliases = _comparables(cards)
    problems = []

    def criterion(part: str):
        names = next((names for pattern, names in _MARKET_METRICS if pattern.search(part)), ())
        return next((name for name in names if name in tiers), None)

    for line in text.splitlines():
        clean = _CITATION.sub(" ", line)
        for sentence in _SENTENCES.split(clean):
            for clause in _CLAUSES.split(sentence):
                label = criterion(clause) or criterion(sentence)
                if label not in tiers:
                    continue
                named = {m[2] for m in _mentions(clause, aliases) if m[3] == "market"} or \
                    {m[2] for m in _mentions(sentence, aliases) if m[3] == "market"}
                by_market = tiers[label]
                if len(by_market) == 1:
                    actual = next(iter(by_market.values()))
                elif len(named) == 1 and next(iter(named)) in by_market:
                    actual = by_market[next(iter(named))]
                else:
                    continue
                said = next((tier for tier in _TIERS if tier in clause), None)
                good = (_LOW_WORDS if "폐업 비율" in label else _HIGH_WORDS).search(clause)
                poor = (_HIGH_WORDS if "폐업 비율" in label else _LOW_WORDS).search(clause)
                if (said and said != actual) or (good and actual == "하위권") or (poor and actual in ("상위권", "중상위권")):
                    problems.append({"type": "tier_mismatch", "detail": f"{label} {actual}", "sentence": clause.strip()})
    return problems


def _card_with_number(shown: str, cards: list[dict]) -> str | None:
    raw = shown.rstrip("%").replace(",", "")
    try:
        number = abs(float(raw))
    except ValueError:
        return None
    for card in cards:
        plain, percent = _card_numbers([card])
        if (shown.endswith("%") and round(number, 2) in percent) or (not shown.endswith("%") and number in plain):
            return card["id"]
    return None


# '5,030억 5,832만 원', '210억', '743만 명': the model's own readings of card numbers (2026-11-08 export).
_KOREAN_AMOUNT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*조(?:\s*(\d[\d,]*)\s*억)?(?:\s*(\d[\d,]*)\s*만)?"
                            r"|(\d[\d,]*(?:\.\d+)?)\s*억(?:\s*(\d[\d,]*)\s*만)?"
                            r"|(\d[\d,]*(?:\.\d+)?)\s*만")


def _korean_value(match) -> tuple[float, float]:
    """(value, smallest unit) of one Korean-unit amount."""
    def number(text):
        return float(text.replace(",", "")) if text else 0.0

    if match.group(1):
        parts = [(match.group(1), 10 ** 12), (match.group(2), 10 ** 8), (match.group(3), 10 ** 4)]
    elif match.group(4):
        parts = [(match.group(4), 10 ** 8), (match.group(5), 10 ** 4)]
    else:
        parts = [(match.group(6), 10 ** 4)]
    used = [(text, unit) for text, unit in parts if text]
    value = sum(number(text) * unit for text, unit in used)
    smallest = used[-1][1]
    decimals = len(used[-1][0].split(".")[1]) if "." in used[-1][0] else 0
    return value, smallest / (10 ** decimals)


def _matches_korean(value: float, unit: float, cards: list[dict]) -> bool:
    plain, _percent = _card_numbers(cards)
    return any(abs(number - value) < unit for number in plain)


def _strip_korean(segment: str, cards: list[dict]) -> tuple[str, list[str]]:
    """The segment without Korean-unit amounts that match a card, and those that match none."""
    wrong = []

    def replace(match):
        value, unit = _korean_value(match)
        if not _matches_korean(value, unit, cards):
            wrong.append(match.group(0).strip())
        return " "

    return _KOREAN_AMOUNT.sub(replace, segment), wrong


def _value_entries(shown: str, cards: list[dict]) -> list[tuple[dict, dict]]:
    """(card, value) pairs whose number is the one shown ('35,911' or '4.81%')."""
    percent = shown.endswith("%")
    try:
        number = abs(float(shown.rstrip("%").replace(",", "")))
    except ValueError:
        return []
    found = []
    for card in cards:
        for value in card.get("values", []):
            for key in ("value", "share_percent"):
                raw = value.get(key)
                if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    continue
                is_percent = key == "share_percent" or value.get("unit") == "%"
                if is_percent == percent and (round(abs(float(raw)), 2) == round(number, 2) if percent
                                              else abs(float(raw)) == number):
                    found.append((card, value))
    return found


def repair_citations(text: str, cards: list[dict]) -> str:
    """Add the card that holds a number when the model cited another one ('21,093,691,228원 [F2]' for F3).

    Only when the line names no other market than that card's: a number never moves to another market.
    """
    _groups, aliases = _comparables(cards)
    out = []
    for line in (text or "").split("\n"):
        if line.strip().startswith("참고:") or is_insight(line):
            out.append(line)
            continue
        named = {m[2] for m in _mentions(_CITATION.sub(" ", line), aliases) if m[3] == "market"}
        parts = _CITATION_GROUP.split(line)
        for index in range(0, len(parts), 2):
            group = parts[index + 1] if index + 1 < len(parts) else ""
            cited = set(_CITATION.findall(group))
            add = []
            for shown in statistics(parts[index], cards):
                holders = [card for card, _value in _value_entries(shown, cards)]
                if not holders or any(card["id"] in cited for card in holders):
                    continue
                fitting = [card for card in holders if not card.get("market") or not named or card["market"] in named]
                ids = list(dict.fromkeys(card["id"] for card in fitting))
                if len(ids) >= 1 and ids[0] not in add:
                    add.append(ids[0])
            if add:
                extra = "".join(f"[{card_id}]" for card_id in add)
                if index + 1 < len(parts):
                    parts[index + 1] = group.rstrip() + extra + group[len(group.rstrip()):]
                else:
                    parts[index] = parts[index].rstrip() + " " + extra
        out.append("".join(parts))
    return "\n".join(out)


def check_answer(text: str, cards: list[dict], *, opinion: bool = False) -> dict:
    """``opinion``: an answer to '너라면 어디?'. Recommendation wording and reasons ('때문') are allowed there;
    every number, citation, comparison and place is checked the same way."""
    by_id = {card["id"]: card for card in cards}
    names = _names(cards)
    problems = comparison_problems(text, cards)
    if opinion:
        problems += tier_problems(text, cards) + median_problems(text, cards) + verdict_problems(text, cards)
    known_periods = _card_periods(cards)
    for segment, _citations in _segments(text):
        for year, quarter in sorted(_periods(segment) - known_periods):
            problems.append({"type": "period_not_on_card", "detail": f"{year}년 {quarter}분기"})
    for cited in _CITATION.findall(text):
        if cited not in by_id:
            problems.append({"type": "unknown_citation", "detail": cited})
    card_words = _card_words(cards)
    problems += _industry_problems(text, card_words)
    for term in _QUOTED_FIGURE.findall(text):
        if term.replace(" ", "") not in card_words.replace(" ", ""):
            problems.append({"type": "term_not_on_card", "detail": term})
    if _OTHER_INDUSTRIES.search(text) and not any(card["topic"] == "industry_rank" for card in cards):
        problems.append({"type": "industry_list_not_on_card"})
    for district in sorted(set(_DISTRICT.findall(text))):
        if district not in card_words:
            problems.append({"type": "place_not_on_card", "detail": district})
    for line in text.splitlines():
        # '연령층 정보는 없어요 [F5]' while F5 holds the ages (2026-11-08 server test): a denial of a card that has data.
        cited = [by_id[c] for c in _CITATION.findall(line) if c in by_id]
        if cited and not is_insight(line) and _DENIAL.search(line) and "폐업" not in line and all(
                card.get("status") == "available" and "없" not in (card.get("text") or "") for card in cited):
            problems.append({"type": "denies_available_card", "sentence": line.strip()})
    for line in text.splitlines():
        insight = is_insight(line)
        if opinion:
            # An opinion is a judgment by nature: hedges and reasons are its language, recommending is its job.
            phrases = [p for p in ALWAYS_FORBIDDEN if p not in RECOMMEND and p != "때문"]
        else:
            phrases = ALWAYS_FORBIDDEN if insight else FORBIDDEN
        for phrase in phrases:
            if phrase in line:
                problems.append({"type": "forbidden_phrase", "detail": phrase})
        if not insight:
            for phrase in UNSUPPORTED:
                if phrase in line and phrase not in card_words:  # '직장인구' is fine once a card has it
                    problems.append({"type": "forbidden_phrase", "detail": phrase})
        for phrase in PROFIT_WORDS:
            if phrase in line and phrase not in card_words:
                problems.append({"type": "forbidden_phrase", "detail": phrase})
        for phrase in WORLD:
            if phrase in line and phrase not in _card_words(cards):
                problems.append({"type": "forbidden_phrase", "detail": phrase.strip()})
        if insight:
            for shown in statistics(line, cards):
                problems.append({"type": "number_in_interpretation", "detail": shown, "sentence": line.strip()})
            if _CHANGE_WORDS.search(line):
                problems.append({"type": "change_in_interpretation", "sentence": line.strip()})
    for segment, citations in _segments(text):
        cited = [by_id[c] for c in citations if c in by_id]
        whole = segment
        segment = _PER_ONE.sub(" ", segment)
        for name in names:
            segment = segment.replace(name, " ")
        segment = _TIME_RANGE.sub(" ", segment)
        segment, wrong = _strip_korean(segment, cited or cards)
        for shown in wrong:
            problems.append({"type": "number_not_on_card" if cited else "uncited_number", "detail": shown,
                             "sentence": whole.strip()})
        for match in _NUMBER.finditer(segment):
            if _LABEL_SUFFIX.match(segment[match.end():]):
                continue
            raw, is_percent = match.group(1), match.group(2) == "%"
            try:
                number = abs(float(raw.replace(",", "")))
            except ValueError:
                continue
            shown = raw + match.group(2)
            if not cited:
                problems.append({"type": "uncited_number", "detail": shown, "sentence": segment.strip()})
                continue
            plain, percent = _card_numbers(cited)
            if (is_percent and round(number, 2) not in percent) or (not is_percent and number not in plain):
                problems.append({"type": "number_not_on_card", "detail": shown, "sentence": segment.strip()})
                continue
            entries = _value_entries(shown, cited)
            # The clause, not the sentence: '점포 1곳당 유동인구가 70,118명이지만 직장 인구는 41명' (2026-11-08 replay).
            clause = re.split(r"지만|하고[,\s]|이고[,\s]|이며[,\s]|며[,\s]", whole[:whole.find(shown)] if shown in whole else whole)[-1]
            if entries and "당" not in clause and all("당" in (value.get("label") or "") and value.get("unit") != "%"
                                                      for _card, value in entries):
                # '하루 유동 인구 35,911명' for 점포 1곳당 유동인구 (2026-11-08 export): a per-store value named as another.
                problems.append({"type": "per_store_misnamed", "detail": shown, "sentence": whole.strip()})
    if opinion and not any(statistics(segment, cards) for segment, _cited in _segments(text)):
        problems.append({"type": "opinion_without_numbers"})
    return {"ok": not problems, "problems": problems}
