"""쿠폰 홍보글 생성기 — promo 카드의 상권 지표 기반 홍보.

AI 는 본문만 쓴다. 쿠폰 값(메뉴·할인 금액·유효기간)은 숫자이므로 코드가 글 끝에 한 줄로 붙이고,
근거(snapshot_id · coupon:메뉴)도 코드가 정한다 — AI 가 준 근거 문자열은 쓰지 않는다.
매출·하락 같은 상권 지표는 손님용 글에 넣지 않는다 — reason_text(사장님용)에만 남긴다.
"""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import clova
from c6 import checks
from c6 import parsing
from c6.style import tone_style_section
from c6.output import DraftOutput, CardResult

# 쿠폰 생성기 전용 few-shot 예시 (reply 스타일 예시는 어투가 달라 안 맞는다)
# 메뉴·리뷰와 무관한 문장으로 둔다 — AI 가 이 예시의 말투만 배우고, 메뉴·수식어는 그대로 베끼지 않도록.
PROMO_EXAMPLE = (
    "요즘 저녁 뭐 드실지 고민되시죠? 손님들이 '양이 넉넉하다'고 해 주신 메뉴, "
    "오늘도 든든하게 준비해 뒀어요 :)"
)

SYSTEM_TMPL = """\
당신은 {store_name} 사장님입니다. 손님에게 보낼 쿠폰 홍보글 본문을 작성하세요.
인사말이나 마무리 인사는 따로 안 붙여도 됩니다. JSON이 아니라 문장 그대로 답해도 됩니다.

## 말투
{style_section}

## 좋은 예시 (이런 느낌으로)
- {example}

## 대표 메뉴
{menu_section}
{praise_section}

## 규칙
1. 2~3문장, 60~160자
2. 손님용 홍보글에는 상권 지표·매출·수치를 넣지 않는다
3. "특별한 가격", "할인 혜택" 같은 막연한 말 대신, 대표 메뉴의 실제 특징(맛·구성 등)을 구체적으로 쓴다
4. 손님 반응이 있으면 그 칭찬받은 점을 손님 말투로 살짝 인용해 녹여 써도 좋다
5. 할인·가격·숫자·쿠폰·코드·반값·% 는 쓰지 않는다 (코드가 글 끝에 쿠폰 값을 따로 붙인다)
6. 메뉴판에 없는 가격·숫자를 넣지 말 것
7. 고객 개인정보 금지
8. 위 예시의 단어·수식어를 그대로 베끼지 말 것 — 예시는 말투만 참고하고, 내용은 위 대표 메뉴·손님 반응에서만 가져올 것
9. "리뷰 남기면 서비스 드려요" 처럼 정책에 없는 보상을 약속하지 말 것
10. 위 대표 메뉴에 없는 음식 이름은 쓰지 말 것
11. 마크다운 문법(**, #, ` 등)을 쓰지 말 것
"""


def _praise_reviews(ctx, n=2):
    """칭찬할 만한 리뷰. sentiment=='positive' 우선, 없으면 평점 4 이상인 것만(없는 복합을 칭찬으로 꾸미지 않는다)."""
    positive = [r for r in ctx.reviews if r.sentiment == "positive"]
    if not positive:
        positive = [r for r in ctx.reviews if (r.rating or 0) >= 4]
        positive.sort(key=lambda r: (r.rating or 0), reverse=True)
    return positive[:n]


def generate_coupon_promo(ctx, card, key, model="HCX-005", chosen_measures=None,
                           coupon_menu=None, coupon_discount=1000, coupon_days=14):
    store = ctx.store
    tone = ctx.tone
    snapshots = {s.snapshot_id: s for s in ctx.snapshots}
    forbidden_phrases = list(tone.forbidden_phrases) if tone.forbidden_phrases else []

    target_snapshots = [snapshots[sid] for sid in card.snapshot_ids if sid in snapshots]

    basis_label = None
    reason_parts = [card.reason_text]
    for snap in target_snapshots:
        basis_label = snap.basis_label
        if snap.value is None:
            reason_parts.append(f"({basis_label}, 수치 확정 전)")
        else:
            reason_parts.append(f"({basis_label}, {snap.value}{snap.unit})")
    reason_text_with_basis = " ".join(reason_parts)

    needs_input: list[str] = []
    if coupon_menu is None:
        coupon_menu = next((m for m in store.menu if m in store.menu_prices), None)
    if not store.menu_prices or coupon_menu is None:
        needs_input.append("menu_prices 없음: 쿠폰 메뉴·금액을 정할 수 없어요")

    rep_menu = [m for m in store.menu if m in store.menu_prices][:2] or list(store.menu[:2])
    menu_section = "\n".join(f"- {m}" for m in rep_menu) if rep_menu else "(메뉴 정보 없음)"

    praise = _praise_reviews(ctx)
    if praise:
        praise_lines = "\n".join(f'- "{r.text}" (★{r.rating or "?"})' for r in praise)
        praise_section = f"\n## 손님 반응 (참고용, 그대로 베끼지 말고 느낌만)\n{praise_lines}"
    else:
        praise_section = ""

    system = SYSTEM_TMPL.format(
        store_name=store.name,
        style_section=tone_style_section(tone, ctx.owner_replies),
        example=PROMO_EXAMPLE,
        menu_section=menu_section,
        praise_section=praise_section,
    )

    messages = [{"role": "user", "content": "손님에게 보낼 쿠폰 홍보글 본문을 작성해 주세요."}]

    allowed_numbers = list(store.menu_prices.values())
    review_texts = [r.text for r in ctx.reviews]

    def _run_promo_checks(text):
        result = {
            "no_bad_number": not checks.has_number_not_in(text, allowed_numbers),
            "no_personal_info": not checks.personal_info(text),
            "no_coupon_invented": not checks.coupon_invented(text),
            "no_stiff_words": not checks.has_stiff_words(text),
            "no_fewshot_copy": not checks.fewshot_copied(text, store.menu, review_texts),
            "no_bad_promise": not checks.promises_not_in_policy(text, ctx.policies),
            "no_unknown_menu": not checks.mentions_unknown_menu(text, store.menu),
            "no_markdown": not checks.has_markdown(text),
            "length_ok": checks.length_ok(text, 60, 160),
        }
        if forbidden_phrases:
            result["no_forbidden_phrase"] = not checks.forbidden_phrase(text, forbidden_phrases)
        return result

    retry_exempt = ("length_ok",)

    def _check(text_):
        chk_ = _run_promo_checks(text_)
        failed_ = [k for k, v in chk_.items() if not v and k not in retry_exempt]
        return chk_, failed_

    def _score(item):
        return sum(1 for v in item[2].values() if v)

    def _call_candidate(temperature):
        resp = clova.call(key, system, messages, model=model, max_tokens=512, temperature=temperature)
        raw_ = resp.get("content", "")
        text_ = parsing.extract_body(raw_)  # JSON이든 평문이든 본문을 절대 버리지 않는다
        return text_, raw_, resp.get("won", 0)

    start = time.perf_counter()
    total_won = 0.0
    rewrites = 0

    # 후보 2개를 동시에 생성해 점검 통과 수가 많은 쪽을 쓴다
    with ThreadPoolExecutor(max_workers=2) as pool:
        candidates = [f.result() for f in [pool.submit(_call_candidate, 0.4) for _ in range(2)]]
    total_won += sum(c[2] for c in candidates)

    scored = []
    for text_, raw_, _ in candidates:
        chk_, failed_ = _check(text_)
        scored.append((text_, raw_, chk_, failed_))
    scored.sort(key=_score, reverse=True)
    text, raw, check_results, failed = scored[0]

    if failed and text:
        hints = checks.fix_hints(failed)
        retry_msg = [
            {"role": "user", "content": "손님에게 보낼 쿠폰 홍보글 본문을 작성해 주세요."},
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "수정 지시:\n" + "\n".join(f"- {h}" for h in hints)},
        ]
        resp2 = clova.call(key, system, retry_msg, model=model, max_tokens=512, temperature=0.5)
        total_won += resp2.get("won", 0)
        text2 = parsing.extract_body(resp2.get("content", ""))
        if text2:
            text = text2
            rewrites += 1
        check_results, failed = _check(text)

    if not check_results.get("no_stiff_words", True):
        text = checks.fix_stiff_words(text)
        check_results, failed = _check(text)

    # 마크다운 기호 제거·3문장까지만 자르기는 결과와 무관하게 코드가 항상 적용한다
    text = checks.strip_markdown(text)
    text = checks.truncate_sentences(text, 3)
    check_results, failed = _check(text)

    if failed:
        needs_input.append("사장님 확인 필요")

    elapsed_ms = round((time.perf_counter() - start) * 1000)

    if coupon_menu is not None:
        coupon_line = f"🎟 {coupon_menu} {coupon_discount:,}원 할인 쿠폰 · 받은 날 포함 {coupon_days}일"
        final_text = f"{text}\n{coupon_line}" if text else coupon_line
    else:
        final_text = text

    evidence_ids = [s.snapshot_id for s in target_snapshots]
    if coupon_menu is not None:
        evidence_ids.append(f"coupon:{coupon_menu}")
    if not evidence_ids:
        evidence_ids = list(card.evidence_ids)

    draft = DraftOutput(
        draft_id=f"d_{uuid.uuid4().hex[:8]}",
        card_id=card.card_id,
        store_id=store.store_id,
        generator="coupon_promo",
        text=final_text,
        evidence_ids=evidence_ids,
        checks=check_results,
        failed_reasons=checks.fix_hints(failed) if failed else [],
        rewrites=rewrites,
        needs_input=needs_input,
        model=model,
        elapsed_ms=elapsed_ms,
        data_origin=store.data_origin,
    )

    return CardResult(
        card_id=card.card_id, kind=card.kind,
        reason_text=reason_text_with_basis,
        basis_label=basis_label,
        drafts=[draft], chosen_measures=chosen_measures or [],
        elapsed_ms=elapsed_ms, won=round(total_won, 4),
    )
