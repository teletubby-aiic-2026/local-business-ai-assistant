"""Rent and key money the user tells the chat ('월세 500만 원, 권리금 5천만 원이야').

User request 2026-11-08: public data has no market-level rent or key money, so
the assistant asks and computes. Everything here is arithmetic on what the user
said and on the market's average sales per store. That average is not this
shop's expected sales, and the answer says so. No model writes this answer.

What the user said stays with the conversation (the turn's debug field), so
it disappears when the conversation is cleared.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
import math
import re

SCENARIOS = (20, 30, 40)  # shares of sales left after costs, shown as assumptions when the user gave none
MIN_AMOUNT, MAX_AMOUNT = 10_000, 100_000_000_000
_DIGITS = dict(zip("일이삼사오육칠팔구", range(1, 10)))
_SMALL = {"십": 10, "백": 100, "천": 1000}
_LARGE = {"만": 10_000, "억": 100_000_000}
_TOKEN = re.compile(r"[0-9일이삼사오육칠팔구십백천만억,.]+")
_KEYS = (("rent", re.compile(r"월\s*세|월\s*임대료|임대료|월\s*차임")), ("key_money", re.compile(r"권리금")),
         ("deposit", re.compile(r"보증금")), ("labor", re.compile(r"인건비")))
_NONE_AFTER = re.compile(r"\s*(?:은|는|이|가|도)?\s*(?:없|안\s*내|0\s*원)")
_PERCENT = re.compile(r"(원가율?|마진율?|이익률?)\s*(?:은|는|이|가|을|를)?\s*(?:약\s*)?(\d{1,2})\s*(?:%|퍼센트|프로)")
_ASKS = re.compile(r"(월\s*세|임대료|권리금|보증금).{0,14}(얼마|부담|감당|회수|계산|괜찮|맞|적당)|부담.{0,8}계산")


def _won(token: str, had_won: bool) -> int | None:
    """'500만' -> 5,000,000; '1억2천' -> 120,000,000; '오백만' -> 5,000,000; a bare '500' means 만 원."""
    text = token.replace(",", "").rstrip(".")
    total, section, number, index = 0, 0, None, 0
    while index < len(text):
        char = text[index]
        if char.isdigit() or char == ".":
            start = index
            while index < len(text) and (text[index].isdigit() or text[index] == "."):
                index += 1
            try:
                number = float(text[start:index])
            except ValueError:
                return None
            continue
        if char in _DIGITS:
            number = _DIGITS[char]
        elif char in _SMALL:
            section += (1 if number is None else number) * _SMALL[char]
            number = None
        elif char in _LARGE:
            section += number or 0
            total += (section or 1) * _LARGE[char]
            section, number = 0, None
        index += 1
    value = total + section + (number or 0)
    if not re.search(r"[만억]", text) and not had_won and value < 100_000:
        value *= 10_000  # '월세 500', '보증금 5천': people say amounts in 만 원
    value = int(value)
    return value if MIN_AMOUNT <= value <= MAX_AMOUNT else None


def _amount_after(text: str, end: int) -> int | None:
    """The amount right after a keyword, past a particle. '월세 이백만원' keeps its 이; '권리금이 3천' drops it."""
    rest = text[end:].lstrip()
    if rest[:1] in ("은", "는", "가", "도", ":", "=") or (rest[:1] == "이" and rest[1:2] in (" ", "") or re.match(r"이\s*\d", rest)):
        rest = rest[1:].lstrip()
    rest = re.sub(r"^(?:한\s*달에?|매월|월|약|대략)\s*", "", rest).lstrip()
    rest = re.sub(r"(?<=[억만천백])\s+(?=[0-9일이삼사오육칠팔구십백천])", "", rest)  # '1억 2천만원'
    match = _TOKEN.match(rest)
    if not match or not re.search(r"\d|[백천만억]", match.group(0)):
        return None
    return _won(match.group(0), rest[match.end():].lstrip().startswith("원"))


def parse(text: str | None) -> dict | None:
    """What the message says about this site's costs, or None when it gives no figure."""
    if not text:
        return None
    found = {}
    for name, pattern in _KEYS:
        for match in pattern.finditer(text):
            if name == "key_money" and _NONE_AFTER.match(text[match.end():]):
                found[name] = 0
                break
            amount = _amount_after(text, match.end())
            if amount is not None:
                found[name] = amount
                break
    percent = _PERCENT.search(text)
    if percent and 0 < int(percent.group(2)) < 100:
        found["margin"] = 100 - int(percent.group(2)) if percent.group(1).startswith("원가") else int(percent.group(2))
    return found or None


def asks(text: str | None) -> bool:
    return bool(text and _ASKS.search(text))


def _ratio(part: int, whole: int) -> float:
    return float((Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def calculate(costs: dict, per_store_sales: int) -> dict:
    """Monthly average sales, the rent's share of it, and one row per assumed margin."""
    monthly = per_store_sales // 3
    rent, labor, key_money = costs.get("rent"), costs.get("labor") or 0, costs.get("key_money")
    result = {"monthly_sales": monthly, "rent_share": _ratio(rent, monthly) if rent and monthly else None, "rows": []}
    margins = [costs["margin"]] if costs.get("margin") else list(SCENARIOS)
    for margin in margins:
        left = monthly * margin // 100 - (rent or 0) - labor
        months = math.ceil(key_money / left) if key_money and left > 0 else None
        result["rows"].append({"margin": margin, "left": left, "months": months,
                               "break_even": ((rent or 0) + labor) * 100 // margin})
    return result


def card(costs: dict, numbers: dict, *, area_name: str) -> dict:
    values = [{"label": label, "value": costs[key], "unit": "원"}
              for key, label in (("rent", "말씀하신 월세"), ("key_money", "말씀하신 권리금"), ("deposit", "말씀하신 보증금"),
                                 ("labor", "말씀하신 월 인건비")) if costs.get(key) is not None]
    values.append({"label": "점포당 월 평균 추정매출", "market": area_name, "value": numbers["monthly_sales"], "unit": "원",
                   "derived": True})
    if numbers["rent_share"] is not None:
        values.append({"label": "월 평균 매출 대비 월세 비율", "value": numbers["rent_share"], "unit": "%", "derived": True})
    for row in numbers["rows"]:
        values += [{"label": f"마진 {row['margin']}%일 때 월 남는 돈", "value": abs(row["left"]), "unit": "원", "derived": True},
                   {"label": f"마진 {row['margin']}%일 때 손익분기 월매출", "value": row["break_even"], "unit": "원", "derived": True}]
        if row["months"] is not None:
            values.append({"label": f"마진 {row['margin']}%일 때 권리금 회수 기간", "value": row["months"], "unit": "개월", "derived": True})
    return {"id": None, "topic": "site_costs", "status": "available",
            "text": f"{area_name} 점포당 월 평균 추정매출과 사용자가 말한 비용으로 계산한 값입니다.", "values": values,
            "warnings": ["사용자가 말한 비용과 상권 평균으로 계산했습니다. 점포당 월 평균 매출은 그 자리의 예상 매출이 아닙니다."],
            "source_ref": {"analysis": "site_costs"}}


def rent_line(costs: dict, numbers: dict, *, card_id: str) -> str:
    """One sentence for an opinion, where no earlier line has said what the average is."""
    return (f"말씀하신 월세 {costs['rent']:,}원은 점포당 월 평균 추정매출 {numbers['monthly_sales']:,}원의 "
            f"{numbers['rent_share']:.2f}%예요. [{card_id}]")


def lines(costs: dict, numbers: dict, *, area_name: str, industry_name: str, card_id: str) -> list[str]:
    cite = f" [{card_id}]"
    found = [f"{area_name} {industry_name} 점포의 월 평균 추정매출은 {numbers['monthly_sales']:,}원이에요. "
             f"분기 매출을 3으로 나눈 상권 평균이라, 이 자리의 예상 매출은 아니에요.{cite}"]
    if numbers["rent_share"] is not None:
        found.append(f"말씀하신 월세 {costs['rent']:,}원은 그 평균의 {numbers['rent_share']:.2f}%예요.{cite}")
    elif costs.get("key_money") is not None:
        found.append(f"월세까지 알려 주시면 권리금 {costs['key_money']:,}원을 언제쯤 회수할지 더 정확히 볼 수 있어요.{cite}")
    if not costs.get("margin"):
        found.append(f"원가와 비용을 뺀 뒤 매출의 몇 %가 남는지 몰라서 세 경우로 가정해 봤어요.{cite}")
    for row in numbers["rows"]:
        head = f"- 마진 {row['margin']}%일 때: 월세 등을 감당하려면 월 매출 {row['break_even']:,}원이 필요하고"
        if row["left"] > 0:
            tail = f", 평균 매출이면 월 {row['left']:,}원이 남아요"
            tail += f". 권리금 회수에는 약 {row['months']}개월이 걸려요" if row["months"] is not None else ""
        else:
            tail = f", 평균 매출로는 월 {abs(row['left']):,}원 적자예요"
        found.append(f"{head}{tail}.{cite}")
    if costs.get("deposit"):
        found.append(f"보증금 {costs['deposit']:,}원은 돌려받는 돈이라 회수 기간에는 넣지 않았어요.{cite}")
    return found
