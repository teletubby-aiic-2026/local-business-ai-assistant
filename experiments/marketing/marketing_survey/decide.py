"""설문 + 가설 확인 결과 -> 최종 마케팅 전략(MarketingPlan). AI 호출 없음, 전부 규칙.

우선순위 (위에서부터 먼저 맞는 것 하나만 적용 — H_AREA_DROP 은 이 순서에 안 들어간다, 아래 설명)
  1. H_LATE 확인 == '예'                    -> fix_first(배달 지연 안내 공지), 쿠폰 0
  2. H_REPEAT 확인 == '예'                  -> fix_first(재발 방지 공지), 쿠폰 0
     (follow_up="reorder_coupon" 은 이 경우에만 붙는다 — 예산>0 이고 할인 가능할 때만)
  3. H_STORE_ONLY 확인 == '예'              -> fix_first(원인 점검 공지), 쿠폰 0
  4. discount_allowed == False 또는 예산(budget_won) == 0  -> review_promo(0원)
  5. 남은 예산 > 0 이면 목표별 쿠폰을 만든다 (goal 로 leftover_deal/reorder_coupon/offpeak_coupon 선택)
     - 수용력(capacity) == '빠듯함'          -> 한가한 시간대만(바쁜 시간대 제외)
     - 쿠폰을 못 만들면(메뉴 가격 없음 등)    -> needs_input 에 이유만 남김
  6. 위 어디에도 해당 안 하면                -> no_action(지금은 유지)

H_AREA_DROP (상권 저녁 매출 하락)은 "어느 전략을 고를지"가 아니라, 5번에서 쿠폰을 만들 때
"쿠폰 시간대"만 조정한다 — 확인되면 상권 하락 시간대를 우선하고 근거로 basis_label 을 reason 에
남긴다. 단 수용력이 빠듯하면 그래도 한가한 시간대가 우선이고, 그 이유를 note 에 남긴다
(수용력과 상권 신호가 충돌하면 수용력이 이긴다).

검증
  - channels: 설문에 고른 채널로 가게 채널(store.channels)을 거른다(안 쓰는 채널은 전략에 안 남음).
  - 총비용(count * discount_won)은 항상 배정 예산을 넘지 않는다(정수 나눗셈으로 보장).
  - 비용은 전부 "추정"이다 — explain.py 가 표시할 때 "추정"이라고 밝힌다.
  - 기대 효과(예상 매출 증가 등) 숫자는 여기서도, explain.py 에서도 절대 만들지 않는다.
"""

from marketing_survey.hypotheses import _area_drop_snapshot, build_hypotheses
from marketing_survey.models import MarketingPlan, Strategy

DISCOUNT_RATE = 0.3
USAGE_ASSUMPTION = "쿠폰 사용률 가정 없음 — 실제 사용률은 운영하면서 지켜봐야 해요"
TTANG_ASSUMPTION = "배달전용상품권 15% 선할인 결합 가능(서울시 발표 기준, 원문 확인 필요)"
BUSY_TIMING = "한가한 시간대(평일 오후 등)"
FULL_TIMING = "전체 시간대"
AREA_DROP_TIMING = "상권 하락 시간대 우선"


def _active_channels(store, answers) -> list[str]:
    """설문 channels 로 가게 채널을 거른다. 설문에 아무것도 안 골랐으면 가게 채널 전부를 쓴다."""
    if answers.channels:
        return [c for c in store.channels if c in answers.channels]
    return list(store.channels)


def _fix_first_strategy(title: str, reason: str, source_hypothesis: str, follow_up: str = "") -> Strategy:
    return Strategy(
        type="fix_first", title=title, reason=reason,
        budget_won=0, count=0, discount_won=0, timing="즉시", generator="prevention_notice",
        assumptions=["쿠폰 예산은 운영 문제부터 해결한다고 보고 0원으로 둠"],
        source_hypothesis=source_hypothesis, follow_up=follow_up,
    )


def _review_promo_strategy(answers, channels: list[str]) -> Strategy:
    if not answers.discount_allowed:
        reason = "할인을 지금 하기 어렵다고 하셔서 비용 없는 홍보만 가능해요"
    else:
        reason = "예산이 0원이라 비용 없는 홍보만 가능해요"
    return Strategy(
        type="review_promo", title="칭찬 리뷰 기반 홍보", reason=reason,
        budget_won=0, count=0, discount_won=0, timing="상시", generator="coupon_promo",
        assumptions=["쿠폰 없이 글만으로 홍보"], channels=channels,
    )


def _no_action_strategy() -> Strategy:
    return Strategy(
        type="no_action", title="지금은 유지",
        reason="조건에 맞는 뚜렷한 전략이 없어 할인 대신 유지해요",
        budget_won=0, count=0, discount_won=0, timing="-", generator="", assumptions=[],
    )


def build_coupon_strategy(ctx, answers, remaining_budget: int,
                           area_drop_confirmed: bool = False) -> tuple[Strategy | None, str | None]:
    """쿠폰형 전략 1개 + (있으면) needs_input 메모. decide() 와 follow_up(재주문 쿠폰) 양쪽에서 쓴다."""
    store = ctx.store
    menu = answers.discount_menu
    price = store.menu_prices.get(menu) if menu else None
    if not menu or not price:
        return None, "할인 메뉴 가격 정보가 없어 쿠폰 금액을 정할 수 없어요"

    discount_won = min(answers.max_discount_won, int(price * DISCOUNT_RATE))
    if discount_won <= 0:
        return None, "최대 할인 금액이 0원이라 쿠폰 금액을 정할 수 없어요"

    count = remaining_budget // discount_won
    if count <= 0:
        return None, "예산이 할인액보다 적어 쿠폰을 하나도 만들 수 없어요"

    busy_blocked = answers.capacity == "빠듯함"
    area_snap = _area_drop_snapshot(list(ctx.snapshots)) if area_drop_confirmed else None

    note = ""
    if area_snap is not None and busy_blocked:
        timing = BUSY_TIMING
        note = "수용력이 빠듯해 상권 하락 시간대보다 한가한 시간대를 우선했어요"
    elif area_snap is not None:
        timing = AREA_DROP_TIMING
    elif busy_blocked:
        timing = BUSY_TIMING
    else:
        timing = FULL_TIMING

    if answers.goal == "남는 재료 처리":
        strat_type, title, reason = "leftover_deal", f"{menu} 한정 할인", "남는 재료를 줄이고 싶다고 하셨어요"
    elif answers.goal == "재주문":
        strat_type, title, reason = "reorder_coupon", "재주문 쿠폰", "재주문을 늘리고 싶다고 하셨어요"
    else:
        strat_type, title, reason = "offpeak_coupon", "쿠폰 홍보", "새 손님·객단가를 늘리고 싶다고 하셨어요"

    if area_snap is not None:
        reason += f" (근거: {area_snap.basis_label})"

    assumptions = [USAGE_ASSUMPTION]
    if busy_blocked:
        assumptions.append("감당이 빠듯하다고 하셔서 바쁜 시간대 쿠폰은 뺌")
    if "땡겨요" in answers.apps:
        assumptions.append(TTANG_ASSUMPTION)

    strategy = Strategy(
        type=strat_type, title=title, reason=reason,
        budget_won=count * discount_won, count=count, discount_won=discount_won,
        timing=timing, generator="coupon_promo", assumptions=assumptions,
        note=note, channels=_active_channels(store, answers), menu=menu,
    )
    return strategy, None


def build_follow_up_strategy(ctx, answers) -> tuple[Strategy | None, str | None]:
    """fix_first(H_REPEAT) 승인 뒤 제안하는 재주문 쿠폰. goal 과 상관없이 늘 reorder_coupon 으로 만든다."""
    strategy, note = build_coupon_strategy(ctx, answers, answers.budget_won, area_drop_confirmed=False)
    if strategy is not None:
        strategy.type = "reorder_coupon"
        strategy.title = "재주문 쿠폰"
        strategy.reason = "공지 승인 뒤 재주문을 늘리고 싶다고 하셨어요"
    return strategy, note


def decide(ctx, answers, confirms: dict[str, str] | None = None) -> MarketingPlan:
    store = ctx.store
    hypotheses = build_hypotheses(ctx, answers)
    confirms = dict(confirms or {})

    def confirmed(hid: str) -> bool:
        return confirms.get(hid) == "예"

    needs_input: list[str] = []
    strategies: list[Strategy] = []

    if confirmed("H_LATE"):
        strategies.append(_fix_first_strategy(
            "배달 지연 안내 공지", "배달 지연 불만이 반복돼 쿠폰보다 운영 안내가 먼저예요", "H_LATE",
        ))
    elif confirmed("H_REPEAT"):
        allow_follow_up = answers.budget_won > 0 and answers.discount_allowed
        strategies.append(_fix_first_strategy(
            "재발 방지 공지", "반복된 불만을 먼저 공지로 짚어야 신뢰가 회복돼요", "H_REPEAT",
            follow_up="reorder_coupon" if allow_follow_up else "",
        ))
    elif confirmed("H_STORE_ONLY"):
        strategies.append(_fix_first_strategy(
            "원인 점검 공지", "가게만의 문제로 보여 쿠폰보다 원인 점검이 먼저예요", "H_STORE_ONLY",
        ))
    elif not answers.discount_allowed or answers.budget_won == 0:
        strategies.append(_review_promo_strategy(answers, _active_channels(store, answers)))
    else:
        coupon, note = build_coupon_strategy(
            ctx, answers, answers.budget_won, area_drop_confirmed=confirmed("H_AREA_DROP"),
        )
        if coupon is not None:
            strategies.append(coupon)
        elif note:
            needs_input.append(note)

    if not strategies:
        strategies.append(_no_action_strategy())

    used_budget = sum(s.budget_won for s in strategies)

    return MarketingPlan(
        store_id=store.store_id, answers=answers, hypotheses=hypotheses, confirms=confirms,
        strategies=strategies, total_budget=answers.budget_won, used_budget=used_budget,
        needs_input=needs_input, data_origin=store.data_origin,
    )
