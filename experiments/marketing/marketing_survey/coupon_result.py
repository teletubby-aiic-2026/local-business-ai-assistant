"""쿠폰 결과 확인 — 발급·사용 장수·할인액·쿠폰 주문 평균 금액으로 사용률과 효율을 계산한다.
AI 호출 없음, 전부 코드.

usage_rate = 사용 장수 / 발급 장수. total_discount_cost = 사용 장수 x 할인액.
coupon_order_revenue = 사용 장수 x 쿠폰 주문 평균 금액. revenue_per_discount_won = 매출 / 할인 비용.

판정과 다음 쿠폰 조건도 코드가 정한다(기대 효과 숫자는 만들지 않는다 — 할인액 조정 방향만 제안):
  사용률 < 20% -> 할인액 +500원(또는 시간대 변경), 20~50% -> 같은 조건 유지, > 50% -> 할인액 -500원.

build_coupon_result_plan(raw, today=None) -> marketing_survey.execute.build_plan() 과 같은 모양
+ usage_rate, issued, used, next_condition({discount_won, delta_won, note}).
"""
from __future__ import annotations

from datetime import date

from marketing_survey import adspend
from marketing_survey.playbooks import PlaybookStep, _date_label

LOW_USAGE_THRESHOLD = 0.2
HIGH_USAGE_THRESHOLD = 0.5
DISCOUNT_STEP_WON = 500

TODO_LOW_USAGE = "할인액 500원 올리기 또는 시간대 바꾸기"
TODO_MID_USAGE = "같은 조건으로 한 번 더"
TODO_HIGH_USAGE = "할인액 500원 내려 비용 줄이기"

NOTE_LOW_USAGE = "사용률이 낮아요 — 할인액을 올리거나 쿠폰을 쓸 수 있는 시간대를 바꿔 봐요"
NOTE_MID_USAGE = "사용률이 적당해요 — 지금 조건을 그대로 유지해요"
NOTE_HIGH_USAGE = "사용률이 높아요 — 할인액을 낮춰서 비용을 줄여 봐요"


def usage_rate(issued: int, used: int) -> float | None:
    """발급 장수가 0이면 계산할 수 없다(없는 값을 만들지 않고 None)."""
    if issued <= 0:
        return None
    return used / issued


def total_discount_cost(used: int, discount_won: int) -> int:
    return used * discount_won


def coupon_order_revenue(used: int, avg_order_won: int) -> int:
    return used * avg_order_won


def revenue_per_discount_won(revenue_won: int, cost_won: int) -> float | None:
    """할인 비용이 0이면 계산할 수 없다(없는 값을 만들지 않고 None)."""
    if cost_won <= 0:
        return None
    return round(revenue_won / cost_won, 1)


def next_coupon_condition(rate: float | None, discount_won: int) -> dict | None:
    """사용률로 다음 쿠폰의 할인액 조정 방향을 정한다. 사용률을 모르면 None(제안 안 함)."""
    if rate is None:
        return None
    if rate < LOW_USAGE_THRESHOLD:
        delta, note = DISCOUNT_STEP_WON, NOTE_LOW_USAGE
    elif rate <= HIGH_USAGE_THRESHOLD:
        delta, note = 0, NOTE_MID_USAGE
    else:
        delta, note = -DISCOUNT_STEP_WON, NOTE_HIGH_USAGE
    next_discount = max(discount_won + delta, 0)
    return {"discount_won": next_discount, "delta_won": delta, "note": note}


def build_coupon_result_plan(raw: dict, today: date | None = None) -> dict:
    today = today or date.today()
    issued = int(raw.get("coupon_issued") or 0)
    used = int(raw.get("coupon_used") or 0)
    discount_won = int(raw.get("coupon_discount_won") or 0)
    avg_order_won = int(raw.get("coupon_avg_order_won") or 0)
    margin_pct = int(raw.get("coupon_margin_pct") or 0)

    rate = usage_rate(issued, used)
    cost_won = total_discount_cost(used, discount_won)
    revenue_won = coupon_order_revenue(used, avg_order_won)
    revenue_ratio = revenue_per_discount_won(revenue_won, cost_won)
    condition = next_coupon_condition(rate, discount_won)
    profit_per_order_won = adspend.profit_per_order(avg_order_won, margin_pct)
    breakeven = adspend.breakeven_orders(cost_won, profit_per_order_won)

    if rate is None:
        todo = "발급 장수를 입력해 주세요"
        tip = "발급 장수가 0이라 사용률을 계산할 수 없어요"
    elif rate < LOW_USAGE_THRESHOLD:
        todo, tip = TODO_LOW_USAGE, f"사용률 {round(rate * 100)}% — 20% 미만이에요"
    elif rate <= HIGH_USAGE_THRESHOLD:
        todo, tip = TODO_MID_USAGE, f"사용률 {round(rate * 100)}% — 20~50%예요"
    else:
        todo, tip = TODO_HIGH_USAGE, f"사용률 {round(rate * 100)}% — 50%를 넘었어요"

    step = PlaybookStep("coupon_result_todo", _date_label(today, 0), todo, "-", 5, tip=tip, cost_krw=0)
    return {
        "title": "쿠폰 결과 확인",
        "total_minutes": step.minutes,
        "steps": [step.to_dict()],
        "drafts": {},
        "measure": "측정: 다음 쿠폰 사용률과 비교",
        "total_cost_krw": 0,
        "usage_rate": rate,
        "issued": issued,
        "used": used,
        "discount_won": discount_won,
        "avg_order_won": avg_order_won,
        "margin_pct": margin_pct,
        "total_discount_cost_won": cost_won,
        "coupon_order_revenue_won": revenue_won,
        "revenue_per_discount_won": revenue_ratio,
        "profit_per_order_won": profit_per_order_won,
        "breakeven_orders": breakeven,
        "next_condition": condition,
    }
