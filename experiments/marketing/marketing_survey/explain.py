"""MarketingPlan 의 전략 1개를 사람이 읽는 3줄로 바꾼다. 코드 템플릿만, AI 호출 없음.

3줄 = 1) 왜 이 방식인지  2) 근거 숫자·가정(비용은 전부 "추정"이라고 밝힘)
      3) 측정 지표 1개(쿠폰 사용 수 / 재주문 수 / 게시물 반응 중)
follow_up 이 있으면 4번째 줄로 "공지 먼저 → 승인 뒤 재주문 쿠폰" 을 덧붙인다.
기대 효과(예상 매출 증가 등) 숫자는 여기서 절대 만들지 않는다 — decide.py 가 안 주기 때문에 줄 수도 없다.
"""

_METRIC_BY_TYPE = {
    "fix_first": "게시물 반응",
    "review_promo": "게시물 반응",
    "reorder_coupon": "재주문 수",
    "leftover_deal": "쿠폰 사용 수",
    "offpeak_coupon": "쿠폰 사용 수",
    "no_action": "게시물 반응",
}

_FOLLOW_UP_LABELS = {
    "reorder_coupon": "공지 먼저 → 승인 뒤 재주문 쿠폰",
}


def explain_strategy(strategy) -> list[str]:
    """전략 1개를 3줄(+follow_up 있으면 4줄) 리스트로."""
    lines = [f"왜 이 방식: {strategy.reason}"]

    basis_bits: list[str] = []
    if strategy.discount_won:
        basis_bits.append(
            f"할인액 추정 {strategy.discount_won:,}원 · 수량 추정 {strategy.count}개 · "
            f"비용 추정 {strategy.budget_won:,}원"
        )
    else:
        basis_bits.append("비용 추정 0원")
    if strategy.timing:
        basis_bits.append(f"시간대: {strategy.timing}")
    if strategy.assumptions:
        basis_bits.append("가정: " + "; ".join(strategy.assumptions))
    if strategy.note:
        basis_bits.append(f"참고: {strategy.note}")
    lines.append(" / ".join(basis_bits))

    metric = _METRIC_BY_TYPE.get(strategy.type, "게시물 반응")
    lines.append(f"측정 지표: {metric}")

    if strategy.follow_up:
        lines.append(_FOLLOW_UP_LABELS.get(strategy.follow_up, strategy.follow_up))

    return lines


def explain_plan(plan) -> list[list[str]]:
    """plan.strategies 각각을 explain_strategy() 로 바꾼 목록."""
    return [explain_strategy(s) for s in plan.strategies]
