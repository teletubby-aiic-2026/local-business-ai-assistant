"""재발 방지 공지 생성기 — complaint 카드의 반복 불만에 대한 공지.

AI 는 본문만 쓴다(인사·마무리 금지, JSON 강제하지 않음 — 답글처럼 문장 그대로 받는다).
시작 인사·마무리는 코드가 답글과 같은 방식으로 조립한다(c6.style.assemble, style 문자열 그대로
공백 포함 정확히). 근거(F_리뷰id·M id)도 코드가 붙인다. AI 본문은 절대 버리지 않는다.
"""

import time
import uuid

import clova
from c6 import checks
from c6 import parsing
from c6.measures import MEASURE_FALLBACK_SENTENCES
from c6.style import assemble, few_shot_examples, insert_before_last_sentence, owner_style, tone_style_section
from c6.output import CALL_FAILED_NOTE, DraftOutput, CardResult

# AI 호출이 끝내 실패했을 때 쓰는 기본 본문 (코드가 쓴다. 첫 문장이 사과라서 공지 점검(has_apology)을 넘는다)
FALLBACK_BODY = "불편을 드려 정말 죄송해요. 같은 일이 없도록 더 신경 쓸게요."

SYSTEM_TMPL = """\
당신은 {store_name} 사장님입니다. 반복되는 고객 불만에 대한 재발 방지 공지의 "본문만" 쓰세요.
인사말이나 마무리 인사는 쓰지 마세요. 코드가 따로 붙입니다. JSON이 아니라 문장 그대로 답해도 됩니다.

## 말투
{style_section}

## 좋은 예시 (이런 느낌으로)
{examples_section}

## 본문 순서
1. 첫 문장: 불편을 드려 죄송하다는 사과 (예: "불편하셨을 텐데 정말 죄송해요")
2. 아래 리뷰들에서 빠졌던 품목을 묶어 한 줄로 짧게 인정 (예: "공깃밥·수저·계란말이가 빠지는 일이 있었어요")
3. 개선 약속: {measure_rule}
4. 다음 주문 때는 요청사항에 적어 주시면 챙기겠다고 안내

## 길이·금지
120~250자. 아래 리뷰 원문을 그대로 베끼지 말고 새로 쓸 것. 금전 보상 약속·고객 개인정보 금지.
"없을 거예요"·"절대"·"완벽" 같은 장담이나 "도입했으니"처럼 이미 끝난 일처럼 말하지 말고, "~할게요"처럼 앞으로 할 일로만 쓸 것
{measures_section}

## 반복 불만 리뷰
{review_lines}
"""


def generate_prevention_notice(ctx, card, key, model="HCX-005", chosen_measures=None):
    store = ctx.store
    tone = ctx.tone
    review_map = {r.review_id: r for r in ctx.reviews}
    target_reviews = [review_map[rid] for rid in card.review_ids if rid in review_map]
    forbidden_phrases = list(tone.forbidden_phrases) if tone.forbidden_phrases else []
    style_info = owner_style(ctx.owner_replies)
    opening = style_info.get("시작 인사") or "안녕하세요 고객님"
    closing = style_info.get("마무리") or f"{store.name} 드림"
    examples_section = few_shot_examples(ctx)

    review_lines = []
    for rv in target_reviews:
        rating = rv.rating if rv.rating is not None else "?"
        review_lines.append(f"- [{rv.review_id}] ★{rating} {rv.text}")

    if chosen_measures:
        measure_rule = "아래 '선택된 조치' 문장을 자연스럽게 한 번 그대로 포함. 다른 구체적 조치는 지어내지 말 것"
        m_lines = [f"- {m['id']}: {m['text']}" for m in chosen_measures]
        measures_section = "\n\n## 선택된 조치\n" + "\n".join(m_lines)
    else:
        measure_rule = "구체적 조치(체크리스트·절차·도입 등)를 지어내지 말고 일반적인 다짐만 쓸 것"
        measures_section = ""

    system = SYSTEM_TMPL.format(
        store_name=store.name,
        style_section=tone_style_section(tone, ctx.owner_replies),
        examples_section="\n".join(f"- {s}" for s in examples_section),
        measure_rule=measure_rule,
        measures_section=measures_section,
        review_lines="\n".join(review_lines),
    )

    def _compute_evidence():
        ev = [f"F_{rv.review_id}" for rv in target_reviews]
        for m in (chosen_measures or []):
            ev.append(m["id"])
        return ev or ["F_" + (target_reviews[0].review_id if target_reviews else card.card_id)]

    def _run_notice_checks(body, text):
        result = {
            "no_bad_promise": not checks.promises_not_in_policy(text, ctx.policies),
            "no_personal_info": not checks.personal_info(text),
            "length_ok": checks.length_ok(body, 120, 250),
            "chosen_measure_included": checks.chosen_measure_included(text, chosen_measures),
            "no_invented_measure": not checks.has_invented_measure(text, chosen_measures),
            "not_quote_review": not checks.quotes_review(body, target_reviews),
            "no_stiff_words": not checks.has_stiff_words(text),
            "no_overpromise": not checks.has_overpromise(text),
            "has_apology": checks.has_apology(body),
            "uses_opening": True,
            "uses_closing": True,
        }
        if forbidden_phrases:
            result["no_forbidden_phrase"] = not checks.forbidden_phrase(text, forbidden_phrases)
        return result

    retry_exempt = ("length_ok", "uses_opening", "uses_closing")
    evidence_ids = _compute_evidence()

    def _check(body_):
        text_ = assemble(opening, body_, closing)
        chk_ = _run_notice_checks(body_, text_)
        failed_ = [k for k, v in chk_.items() if not v and k not in retry_exempt]
        return text_, chk_, failed_

    messages = [{"role": "user", "content": f"카드 이유: {card.reason_text}"}]

    start = time.perf_counter()
    total_won = 0.0
    rewrites = 0

    resp = clova.call(key, system, messages, model=model, max_tokens=512, temperature=0.5)
    total_won += resp.get("won", 0)
    call_errors = 1 if resp.get("error") else 0
    raw = resp.get("content", "")
    body = parsing.extract_body(raw)  # JSON이든 평문이든 본문을 절대 버리지 않는다

    needs = []
    if call_errors and not body:   # 호출이 끝내 실패 → 코드가 쓴 기본 문장으로 채우고 사장님께 알린다
        body = FALLBACK_BODY
        needs.append(CALL_FAILED_NOTE)

    text, check_results, failed = _check(body)

    if failed and body and not needs:
        hints = checks.fix_hints(failed)
        retry_msg = [
            {"role": "user", "content": f"카드 이유: {card.reason_text}"},
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "수정 지시:\n" + "\n".join(f"- {h}" for h in hints)},
        ]
        resp2 = clova.call(key, system, retry_msg, model=model, max_tokens=512, temperature=0.5)
        total_won += resp2.get("won", 0)
        body2 = parsing.extract_body(resp2.get("content", ""))
        if body2:
            body = body2
            rewrites += 1
        text, check_results, failed = _check(body)

    # 딱딱한 표현이 남으면 본문에만 사전대로 단어를 바꾼다 (추가 호출 없음)
    if not check_results.get("no_stiff_words", True):
        body = checks.fix_stiff_words(body)

    # 조치 키워드가 본문에 이미 없을 때만 표준 문장을 마지막 문장(감사·사과) 바로 앞에 끼워 넣는다
    if chosen_measures and not checks.chosen_measure_included(body, chosen_measures):
        fallback = MEASURE_FALLBACK_SENTENCES.get(chosen_measures[0]["id"], chosen_measures[0]["text"])
        body = insert_before_last_sentence(body, fallback)

    # 최종 조립 = 시작 인사 + AI 본문(그대로) + (필요하면 끼워 넣은 표준 문장) + 마무리
    text, check_results, failed = _check(body)

    elapsed_ms = round((time.perf_counter() - start) * 1000)

    draft = DraftOutput(
        draft_id=f"d_{uuid.uuid4().hex[:8]}",
        card_id=card.card_id,
        store_id=store.store_id,
        generator="prevention_notice",
        text=text,
        evidence_ids=evidence_ids,
        checks=check_results,
        failed_reasons=checks.fix_hints(failed) if failed else [],
        rewrites=rewrites,
        needs_input=needs,
        model=model,
        elapsed_ms=elapsed_ms,
        data_origin=store.data_origin,
    )

    return CardResult(
        card_id=card.card_id, kind=card.kind, reason_text=card.reason_text,
        drafts=[draft], chosen_measures=chosen_measures or [],
        elapsed_ms=elapsed_ms, won=round(total_won, 4),
    )
