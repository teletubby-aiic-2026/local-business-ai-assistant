"""CARD_GENERATORS — 이름 → 실제 함수. run_card — 카드 1장을 CardResult 1개로 합쳐 돌린다."""

import json
import time
from pathlib import Path

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

REPLAY_PATH = Path(__file__).resolve().parent / "replay" / "c6_cache_best.json"


def _replay_card(card):
    """key 없을 때 저장본(c6/replay/c6_cache_best.json)에서 card_id 가 같은 결과를 찾는다."""
    if not REPLAY_PATH.exists():
        raise RuntimeError(
            f"CLOVA_API_KEY 가 없고 저장본도 없습니다 ({REPLAY_PATH})."
            " 환경변수 CLOVA_API_KEY 를 설정하거나 저장본을 먼저 만들어 주세요."
        )
    cached = json.loads(REPLAY_PATH.read_text(encoding="utf-8"))
    for data in cached:
        if data.get("card_id") == card.card_id:
            return CardResult.from_dict(data)
    raise RuntimeError(
        f"CLOVA_API_KEY 가 없고 저장본에도 '{card.card_id}' 카드가 없습니다 ({REPLAY_PATH})."
    )


def run_card(ctx, card, key, model="HCX-005", chosen_measures=None):
    """카드 1장에 해당하는 생성기를 모두 돌려 CardResult 하나로 합친다.

    complaint 카드는 reply_draft(답글 여러 개) + prevention_notice(공지 1개)를 함께 실행해
    drafts 에 모두 담는다. elapsed_ms 는 생성기 호출 전체를 감싼 실제 시간이고, won 은 합계다.
    key 가 None 이면(CLOVA_API_KEY 없음) 실제 호출 없이 저장본(c6/replay)에서 같은 card_id 결과를 돌려준다.
    """
    if key is None:
        return _replay_card(card)

    generator_names = KIND_TO_GENERATORS.get(card.kind, ())
    start = time.perf_counter()
    drafts = []
    won = 0.0
    basis_label = None
    reason_text = card.reason_text

    for name in generator_names:
        fn = CARD_GENERATORS[name]
        kwargs = {"chosen_measures": chosen_measures}
        if name == "prevention_notice":
            # 공지가 답글들과 너무 비슷하지 않은지(notice_vs_reply) 보려고 먼저 만든 답글 글을 넘긴다
            kwargs["reply_texts"] = [d.text for d in drafts if d.generator == "reply_draft"]
        sub = fn(ctx, card, key, model=model, **kwargs)
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
