"""광고비 점검 — 사장님이 고른 배달앱마다 건당 광고비와 건당 이익을 비교해 "손해 광고"인지
가른다. AI 호출 없음, 전부 코드.

건당 광고비 = 광고비 ÷ 주문 수. 건당 이익 = 평균 주문 금액 x 남는 비율.
건당 광고비 ≥ 건당 이익 -> "손해 광고", 이익의 50~100% -> "주의", 그 아래 -> "괜찮음".

build_adspend_table(ctx, raw) -> {title, table, todos, summary, ...}.
(이 기능은 글을 만들지 않으므로 drafts·steps 는 항상 비어 있다 — 할 일은 todos 로만 보여 준다)
"""
from __future__ import annotations

import math

AD_APPS = ("baemin", "coupangeats", "yogiyo", "ddanggyeoyo")
AD_APP_LABELS = {
    "baemin": "배민", "coupangeats": "쿠팡이츠", "yogiyo": "요기요", "ddanggyeoyo": "땡겨요",
}

MIN_SPEND_WON = 1_000

VERDICT_LOSS = "손해 광고"
VERDICT_CAUTION = "주의"
VERDICT_OK = "괜찮음"
_VERDICT_RANK = {VERDICT_OK: 0, VERDICT_CAUTION: 1, VERDICT_LOSS: 2}

TODO_LOWER_BID = "광고 관리 화면에서 노출 지역·입찰 금액 낮추기"
SCREEN_NOTE = "앱 화면은 바뀔 수 있어요"


def cost_per_order(spend_won: int, orders: int) -> int | None:
    """주문 수가 0이면 계산할 수 없다(없는 값을 만들지 않고 None)."""
    if orders <= 0:
        return None
    return round(spend_won / orders)


def profit_per_order(avg_order_won: int, margin_pct: int) -> int:
    """건당 이익 = 평균 주문 금액 x 남는 비율(재료비·포장비·수수료 빼고 남는 정도)."""
    return round(avg_order_won * margin_pct / 100)


def breakeven_orders(cost_won: int, profit_per_order_won: int) -> int | None:
    """본전 주문 수 = ceil(비용 ÷ 건당 이익). 건당 이익이 0 이하면 계산할 수 없다(None) —
    예측 문장 대신 "본전이 되려면 N건" 표현에만 쓴다(기대 효과 숫자는 만들지 않는다)."""
    if profit_per_order_won <= 0:
        return None
    return math.ceil(cost_won / profit_per_order_won)


def judge(cost_won: int | None, profit_won: int) -> str | None:
    """건당 광고비와 건당 이익을 비교해 손해/주의/괜찮음을 가른다. 건당 광고비를 모르면 None."""
    if cost_won is None:
        return None
    if cost_won >= profit_won:
        return VERDICT_LOSS
    if cost_won >= profit_won * 0.5:
        return VERDICT_CAUTION
    return VERDICT_OK


def is_valid_spend(spend_won: int) -> bool:
    return spend_won >= MIN_SPEND_WON


def is_valid_orders(orders: int) -> bool:
    return orders > 0


def _summary_line(label: str, cost_won: int, profit_won: int) -> str:
    return f"{label} 광고는 주문 1건에 {cost_won:,}원을 쓰고, 1건에 남는 돈은 약 {profit_won:,}원이에요"


def build_adspend_table(ctx, raw: dict) -> dict:
    selected = [a for a in AD_APPS if a in (raw.get("adspend_apps") or [])]
    avg_order_won = int(raw.get("adspend_avg_amount_won") or 0)
    margin_pct = int(raw.get("adspend_margin_pct") or 0)
    profit_won = profit_per_order(avg_order_won, margin_pct)

    rows = []
    for app in selected:
        spend = int(raw.get(f"adspend_{app}_spend") or 0)
        orders = int(raw.get(f"adspend_{app}_orders") or 0)
        cpo = cost_per_order(spend, orders)
        rows.append({
            "channel": app, "label": AD_APP_LABELS[app],
            "spend_won": spend, "orders": orders,
            "cost_per_order_won": cpo, "profit_per_order_won": profit_won,
            "verdict": judge(cpo, profit_won),
        })

    flagged = [r for r in rows if r["verdict"] in (VERDICT_LOSS, VERDICT_CAUTION)]
    todos = [TODO_LOWER_BID] if flagged else []

    judged = [r for r in rows if r["cost_per_order_won"] is not None]
    worst = max(
        judged, key=lambda r: (_VERDICT_RANK.get(r["verdict"], 0), r["cost_per_order_won"]), default=None,
    )
    summary = _summary_line(worst["label"], worst["cost_per_order_won"], profit_won) if worst else ""

    return {
        "title": "광고비 점검",
        "total_minutes": 0,
        "steps": [],
        "drafts": {},
        "measure": "측정: 다음 달 같은 표 비교",
        "total_cost_krw": 0,
        "table": rows,
        "todos": todos,
        "todo_note": SCREEN_NOTE if todos else "",
        "summary": summary,
        "avg_order_won": avg_order_won,
        "margin_pct": margin_pct,
        "profit_per_order_won": profit_won,
    }
