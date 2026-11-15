"""광고비 점검 — 채널별 이번 달 광고비·주문 수로 건당 광고비를 계산한다. AI 호출 없음, 전부 코드.

건당 광고비 = 광고비 ÷ 주문 수. 대표 메뉴 가격의 15% 를 넘으면 "점검 필요"로 표시한다.
build_adspend_table(ctx, raw) -> {title, total_minutes, steps, drafts, measure, table, ...}
(steps/drafts 는 marketing_survey.execute.build_plan() 과 같은 모양을 맞추기 위한 것 — 이 기능은
글을 만들지 않으므로 drafts 는 항상 비어 있다)
"""
from __future__ import annotations

from marketing_survey.playbooks import PlaybookStep, default_menu

AD_CHANNELS = ("baemin", "coupangeats", "yogiyo")
AD_CHANNEL_LABELS = {"baemin": "배민", "coupangeats": "쿠팡이츠", "yogiyo": "요기요"}
CHECK_THRESHOLD_RATE = 0.15

TODO_REVIEW_CONDITION = "높은 채널 광고 조건 다시 보기"
TODO_MOVE_BUDGET = "예산을 낮은 채널로 옮기기(추정)"


def cost_per_order(spend_won: int, orders: int) -> int | None:
    """주문 수가 0이면 계산할 수 없다(없는 값을 만들지 않고 None)."""
    if orders <= 0:
        return None
    return round(spend_won / orders)


def build_adspend_table(ctx, raw: dict) -> dict:
    store = ctx.store
    menu = default_menu(store)
    menu_price = store.menu_prices.get(menu, 0) if menu else 0
    threshold_won = round(menu_price * CHECK_THRESHOLD_RATE)

    rows = []
    for channel in AD_CHANNELS:
        spend = int(raw.get(f"adspend_{channel}_spend") or 0)
        orders = int(raw.get(f"adspend_{channel}_orders") or 0)
        cpo = cost_per_order(spend, orders)
        needs_check = cpo is not None and menu_price > 0 and cpo > threshold_won
        rows.append({
            "channel": channel, "label": AD_CHANNEL_LABELS[channel],
            "spend_won": spend, "orders": orders,
            "cost_per_order_won": cpo, "needs_check": needs_check,
        })

    flagged = [r for r in rows if r["needs_check"]]
    todos = [TODO_REVIEW_CONDITION, TODO_MOVE_BUDGET] if flagged else []

    steps = [
        PlaybookStep(f"adspend_todo_{i}", "오늘", todo, "-", 5, cost_krw=0)
        for i, todo in enumerate(todos)
    ]
    if not steps:
        steps = [PlaybookStep("adspend_ok", "오늘", "지금은 채널별 광고 조건 유지", "-", 0, cost_krw=0)]

    return {
        "title": "광고비 점검",
        "total_minutes": sum(s.minutes for s in steps),
        "steps": [s.to_dict() for s in steps],
        "drafts": {},
        "measure": "측정: 다음 달 같은 채널 건당 광고비 비교",
        "total_cost_krw": 0,
        "table": rows,
        "todos": todos,
        "menu": menu,
        "menu_price_won": menu_price,
        "threshold_won": threshold_won,
    }
