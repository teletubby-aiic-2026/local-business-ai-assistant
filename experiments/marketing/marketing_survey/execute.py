"""MarketingPlan 의 전략을 C6 생성기로 넘겨 실제 글(초안)을 만든다. AI 호출은 c6 쪽에서만 한다.

- fix_first 중 H_REPEAT 에서 나온 것만 card_sample_a 로 prevention_notice 를 실제로 만든다
  (H_LATE·H_STORE_ONLY 의 fix_first 는 아직 사장님 확인/운영 조치가 먼저라 글을 만들지 않는다).
- 쿠폰 계열(leftover_deal/reorder_coupon/offpeak_coupon)은 card_sample_b 로 coupon_promo 를 만든다.
  설문이 정한 할인액(discount_won)·메뉴(menu)·시간대(timing)를 c6.promo.generate_coupon_promo 의
  coupon_discount·coupon_menu·time_window 인자로 그대로 넘긴다.
- review_promo 는 card_sample_b 로 c6.promo.generate_review_promo 를 만든다(쿠폰 줄 없음).
- 그 외(H_LATE·H_STORE_ONLY 의 fix_first)는 글을 만들지 않고, "사장님 할 일" 한 줄만 남긴다.

key 가 None 이면(CLOVA_API_KEY 없음) c6.registry.run_card 를 통해 저장본(c6/replay)을 재생한다
(review_promo 는 저장본이 없어 review_promo_fallback_text 코드 템플릿을 그대로 쓴다).

build_plan(ctx, strategy, answers, key, model, today=None) -> {title, total_minutes, steps, drafts,
coupon_card, measure}. marketing_survey.playbooks.build_playbook() 이 정한 할 일(steps)마다
run_step_generator() 로 글을 실제로 만들어 drafts 에 담는다(step_id -> 글).
"""

from c6.notice import generate_prevention_notice
from c6.output import DraftOutput
from c6.promo import generate_coupon_promo, generate_review_promo, review_promo_fallback_text
from c6.registry import run_card
from c6.reply import generate_reply_draft
from marketing_survey import playbooks
from marketing_survey.decide import BUSY_TIMING
from shared.sample_scenario import SAMPLE_CARDS

NOTICE_CARD = next(c for c in SAMPLE_CARDS if c.card_id == "card_sample_a")
PROMO_CARD = next(c for c in SAMPLE_CARDS if c.card_id == "card_sample_b")

_COUPON_GENERATOR_TYPES = {"leftover_deal", "reorder_coupon", "offpeak_coupon"}
COUPON_DAYS = 14  # c6.promo.generate_coupon_promo 의 coupon_days 기본값과 같다(명시적으로 둠)


def _run_notice(ctx, key, model):
    if key is None:
        result = run_card(ctx, NOTICE_CARD, None)
    else:
        result = generate_prevention_notice(ctx, NOTICE_CARD, key, model=model)
    draft = next((d for d in result.drafts if d.generator == "prevention_notice"), None)
    return result, draft


def _run_reply(ctx, key, model):
    if key is None:
        result = run_card(ctx, NOTICE_CARD, None)
    else:
        result = generate_reply_draft(ctx, NOTICE_CARD, key, model=model)
    draft = next((d for d in result.drafts if d.generator == "reply_draft"), None)
    return result, draft


def _run_review_promo(ctx, strategy, key, model):
    if key is None:
        # review_promo 는 아직 저장본(c6/replay)이 없어, 다른 생성기처럼 run_card 재생 대신
        # AI 없이도 늘 점검을 통과하는 코드 템플릿(review_promo_fallback_text)을 그대로 쓴다.
        text = review_promo_fallback_text(ctx.store, strategy.menu or None)
        draft = DraftOutput(
            draft_id=f"d_demo_{PROMO_CARD.card_id}", card_id=PROMO_CARD.card_id,
            store_id=ctx.store.store_id, generator="review_promo", text=text,
            data_origin=ctx.store.data_origin,
        )
        return None, draft
    result = generate_review_promo(ctx, PROMO_CARD, key, model=model, menu=strategy.menu or None)
    draft = next((d for d in result.drafts if d.generator == "review_promo"), None)
    return result, draft


def run_step_generator(ctx, strategy, generator_name, key, model="HCX-005"):
    """playbooks.PlaybookStep.generator 이름 하나를 실제로 돌려 글 텍스트만 돌려준다."""
    if generator_name == "prevention_notice":
        _, draft = _run_notice(ctx, key, model)
        return draft.text if draft else None
    if generator_name == "reply_draft":
        _, draft = _run_reply(ctx, key, model)
        return draft.text if draft else None
    if generator_name == "coupon_promo":
        _, draft = _run_coupon(ctx, strategy, key, model)
        return draft.text if draft else None
    if generator_name == "review_promo":
        _, draft = _run_review_promo(ctx, strategy, key, model)
        return draft.text if draft else None
    return None


def build_plan(ctx, strategy, answers, key, model="HCX-005", today=None):
    """playbooks.build_playbook() 의 할 일마다 generator 를 실행해 글(drafts)과 쿠폰 카드를 채운다.

    출력 형식: {title, total_minutes, steps, drafts: {step_id: 글}, coupon_card, measure, strategy_type}.
    """
    plan = playbooks.build_playbook(ctx, strategy, answers, today=today)

    drafts: dict[str, str] = {}
    for step in plan["steps"]:
        generator_name = step.get("generator")
        if not generator_name:
            continue
        text = run_step_generator(ctx, strategy, generator_name, key, model=model)
        if text and step.get("max_chars"):
            text = text[: step["max_chars"]]
        if text:
            drafts[step["step_id"]] = text

    coupon_card = None
    if strategy.discount_won:
        coupon_card = {
            "menu": strategy.menu, "discount_won": strategy.discount_won, "count": strategy.count,
            "timing": strategy.timing, "days": COUPON_DAYS,
        }

    plan["drafts"] = drafts
    plan["coupon_card"] = coupon_card
    plan["strategy_type"] = strategy.type  # 화면이 카드 아이콘을 고르는 용도(사실 자체는 그대로 strategy 가 정함)
    return plan


def _run_coupon(ctx, strategy, key, model):
    if key is None:
        result = run_card(ctx, PROMO_CARD, None)
    else:
        # "상권 하락 시간대 우선"은 구체적인 시간대가 아니라, c6 쪽이 상권 지표(snapshot)에서
        # 정확한 시간대("저녁 5~9시 주문 시" 등)를 자동으로 뽑으라는 뜻이라 None(자동)으로 둔다.
        # "한가한 시간대"만 명시적으로 덮어쓴다 — 수용력이 빠듯할 때 상권 신호보다 우선하기 위해서다.
        time_window = BUSY_TIMING if strategy.timing == BUSY_TIMING else None
        result = generate_coupon_promo(
            ctx, PROMO_CARD, key, model=model,
            coupon_menu=strategy.menu or None,
            coupon_discount=strategy.discount_won or 1000,
            coupon_days=COUPON_DAYS,
            time_window=time_window,
        )
    draft = next((d for d in result.drafts if d.generator == "coupon_promo"), None)
    return result, draft


def execute_strategy(ctx, strategy, key, model="HCX-005"):
    """전략 1개 실행. (CardResult|None, DraftOutput|None, 사장님 할 일 문구|None) 를 돌려준다."""
    if strategy.type == "fix_first" and strategy.source_hypothesis == "H_REPEAT":
        result, draft = _run_notice(ctx, key, model)
        return result, draft, None
    if strategy.type in _COUPON_GENERATOR_TYPES:
        result, draft = _run_coupon(ctx, strategy, key, model)
        return result, draft, None
    if strategy.type == "review_promo":
        result, draft = _run_review_promo(ctx, strategy, key, model)
        return result, draft, None
    # 사유(strategy.reason)는 explain_strategy() 의 "왜" 줄에 이미 나오므로 여기서는 반복하지 않는다
    return None, None, f"사장님 확인 필요 — {strategy.title}"


def execute_plan(ctx, plan, key, model="HCX-005"):
    """plan.strategies 를 순서대로 실행. [(strategy, CardResult|None, DraftOutput|None, 할 일|None), ...]."""
    out = []
    for strategy in plan.strategies:
        result, draft, todo = execute_strategy(ctx, strategy, key, model=model)
        out.append((strategy, result, draft, todo))
    return out
