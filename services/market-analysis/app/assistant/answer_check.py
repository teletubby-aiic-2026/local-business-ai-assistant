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
ALWAYS_FORBIDDEN = ("사장님 가게의 매출은", "사장님 가게 매출은", "가게 매출이 오", "확실히 오", "무조건", "보장", "반드시 오",
                    # Data shows sales, not where or what to open.
                    "추천해요", "추천합니다", "추천드", "추천할 만", "추천할만", "여시는 것을", "여는 것을",
                    # Causes: the cards only show changes that happened in the same period.
                    "때문", "초래", "요인", "로 인해", "탓", "덕분에", "영향으로", "영향을 미", "영향을 줬", "영향을 준",
                    # Verdicts the cards do not state.
                    "좋아졌", "나빠졌", "나아졌", "악화", "호전")
# Hedged guesses: allowed only on an interpretation line ('직장인이 많이 찾을 것으로 예상됩니다' on a fact line,
# HCX-005 2026-11-08).
HEDGES = ("것으로 보", "가능성이 있", "예상됩", "예상돼", "예상해", "예상할", "짐작", "시사")
FORBIDDEN = ALWAYS_FORBIDDEN + HEDGES  # the strictest set, for short replies without cards
_CHANGE_WORDS = re.compile(r"감소|증가|줄었|늘었|줄어|늘어|줄면|늘면|떨어|올랐|하락|상승|변화")


def is_insight(line: str) -> bool:
    return line.strip().startswith(INSIGHT)


def statistics(segment: str, cards: list[dict]) -> list[str]:
    """Numbers in a piece of text that are statistics, not labels such as 2026년, 20대, 11~14시 or names."""
    segment = _CITATION.sub(" ", segment)
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


def _card_periods(cards) -> set:
    found = set()
    for card in cards:
        found |= _periods(card.get("text") or "")
        for value in card.get("values", []):
            if isinstance(value.get("value"), str):
                found |= _periods(value["value"])
    return found


def check_answer(text: str, cards: list[dict]) -> dict:
    by_id = {card["id"]: card for card in cards}
    names = _names(cards)
    problems = []
    known_periods = _card_periods(cards)
    for segment, _citations in _segments(text):
        for year, quarter in sorted(_periods(segment) - known_periods):
            problems.append({"type": "period_not_on_card", "detail": f"{year}년 {quarter}분기"})
    for cited in _CITATION.findall(text):
        if cited not in by_id:
            problems.append({"type": "unknown_citation", "detail": cited})
    for line in text.splitlines():
        insight = is_insight(line)
        for phrase in (ALWAYS_FORBIDDEN if insight else FORBIDDEN):
            if phrase in line:
                problems.append({"type": "forbidden_phrase", "detail": phrase})
        if insight:
            for shown in statistics(line, cards):
                problems.append({"type": "number_in_interpretation", "detail": shown, "sentence": line.strip()})
            if _CHANGE_WORDS.search(line):
                problems.append({"type": "change_in_interpretation", "sentence": line.strip()})
    for segment, citations in _segments(text):
        cited = [by_id[c] for c in citations if c in by_id]
        for name in names:
            segment = segment.replace(name, " ")
        segment = _TIME_RANGE.sub(" ", segment)
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
    return {"ok": not problems, "problems": problems}
