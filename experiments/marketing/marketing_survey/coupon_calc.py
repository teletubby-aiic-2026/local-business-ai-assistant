"""쿠폰 손익 계산 — 월 예산·할인액·가격·평균 주문 금액·마진율로 쿠폰 장수와 본전 주문 수를
코드 한 곳에서 계산한다. AI 호출 없음, 예측(주문 수·매출 증가) 없음 — 지금 조건으로 숫자만 보여 준다.

decide.build_coupon_strategy(쿠폰 장수)와 execute.build_plan/coupon_result.build_coupon_result_plan
(본전 주문 수)가 쓰던 계산을 이 함수로 합친다 — 건당 이익·본전 주문 수는 여전히
marketing_survey.adspend.profit_per_order/breakeven_orders 공식을 그대로 쓴다.

calc(budget_won, discount_won, price_won, avg_order_won, margin_pct) -> {
  count, max_cost_won, remaining_won, profit_per_order_won, breakeven_orders, discount_pct,
}.
"""
from __future__ import annotations

from marketing_survey.adspend import breakeven_orders, profit_per_order


def calc(budget_won: int, discount_won: int, price_won: int, avg_order_won: int, margin_pct: int) -> dict:
    budget_won = max(int(budget_won), 0)
    discount_won = max(int(discount_won), 0)
    price_won = max(int(price_won), 0)

    count = budget_won // discount_won if discount_won > 0 else 0
    max_cost_won = count * discount_won
    remaining_won = budget_won - max_cost_won
    profit_per_order_won = profit_per_order(avg_order_won, margin_pct)
    discount_pct = round(discount_won / price_won * 100) if price_won > 0 else 0

    return {
        "count": count,
        "max_cost_won": max_cost_won,
        "remaining_won": remaining_won,
        "profit_per_order_won": profit_per_order_won,
        "breakeven_orders": breakeven_orders(max_cost_won, profit_per_order_won),
        "discount_pct": discount_pct,
    }
