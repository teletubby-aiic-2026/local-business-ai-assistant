"""CARD_GENERATORS — 이름 → 실제 함수. run_card — 카드 1장을 CardResult 1개로 합쳐 돌린다."""

import time

from shared.contracts import CARD_GENERATORS as KIND_TO_GENERATORS

from c6.reply import generate_reply_draft
from c6.notice import generate_prevention_notice
from c6.promo import generate_coupon_promo
from c6.output import CardResult

CARD_GENERATORS = {
    "reply_draft": generate_reply_draft,
    "prevention_notice": generate_prevention_notice,
    "coupon_promo": generate_coupon_promo,
}


def run_card(ctx, card, key, model="HCX-005", chosen_measures=None):
    """카드 1장에 해당하는 생성기를 모두 돌려 CardResult 하나로 합친다.

    complaint 카드는 reply_draft(답글 여러 개) + prevention_notice(공지 1개)를 함께 실행해
    drafts 에 모두 담는다. elapsed_ms 는 생성기 호출 전체를 감싼 실제 시간이고, won 은 합계다.
    """
    generator_names = KIND_TO_GENERATORS.get(card.kind, ())
    start = time.perf_counter()
    drafts = []
    won = 0.0
    basis_label = None
    reason_text = card.reason_text

    for name in generator_names:
        fn = CARD_GENERATORS[name]
        sub = fn(ctx, card, key, model=model, chosen_measures=chosen_measures)
        drafts.extend(sub.drafts)
        won += sub.won
        if sub.basis_label:
            basis_label = sub.basis_label
        if sub.reason_text and sub.reason_text != card.reason_text:
            reason_text = sub.reason_text  # 예: promo 는 reason_text 에 근거 표시를 덧붙인다

    elapsed_ms = round((time.perf_counter() - start) * 1000)

    return CardResult(
        card_id=card.card_id, kind=card.kind, reason_text=reason_text,
        basis_label=basis_label, drafts=drafts,
        chosen_measures=chosen_measures or [], elapsed_ms=elapsed_ms, won=round(won, 4),
    )
