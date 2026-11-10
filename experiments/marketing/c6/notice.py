"""재발 방지 공지 생성기 — complaint 카드의 반복 불만을 '모든 손님에게 알리는 플레이스 소식'으로 쓴다.

reply(답글)는 손님 한 명에게 해요체로 말하지만, notice(공지)는 모든 손님에게 합니다체로 알리는 글이라
구조·말투가 다르다. AI 는 본문 4문장만 쓴다(제목·시작 인사·마무리 금지, 줄바꿈으로 문장을 나눔).
제목 줄·시작 줄·마무리 줄은 코드가 조립한다(assemble_notice). 근거(F_리뷰id·M id)도 코드가 붙인다.
AI 본문은 절대 버리지 않는다.
"""

import time
import uuid

import clova
from c6 import checks
from c6 import parsing
from c6.measures import MEASURE_FALLBACK_SENTENCES
from c6.output import DraftOutput, CardResult
from common.korean import display_name, eul

NOTICE_FEWSHOT = (
    "최근 공깃밥, 수저, 계란말이가 빠진 상태로 배달된 일이 있었습니다.\n"
    "불편을 드려 죄송합니다.\n"
    "오늘부터 포장 마감 전에 주문서와 한 번 더 대조해보고 배달해드리겠습니다.\n"
    "이외에도 필요한 게 있으면 요청사항에 적어 주세요."
)

_TOPIC_LABELS = {"missing_item": "포장 누락"}
_DEFAULT_TOPIC = "운영 개선"

SYSTEM_TMPL = """\
당신은 {store_name} 사장님입니다. 반복되는 손님 불만에 대해 "모든 손님에게 알리는 공지" 본문 4문장만 쓰세요.
제목·시작 인사·마무리 인사는 쓰지 마세요. 코드가 따로 붙입니다. JSON이 아니라 문장 그대로 답해도 됩니다.

## 말투
합니다체로 쓸 것(해요체·반말 금지). "고객님"·"주문하신"처럼 손님 한 명을 가리키는 말은 쓰지 말 것 —
이 공지는 한 손님에게 보내는 답글이 아니라 모든 손님에게 알리는 글입니다.
문장마다 줄을 바꿀 것(한 줄 = 한 문장, 총 4줄).

## 좋은 예시 (이런 느낌으로, 그대로 베끼지 말 것)
{fewshot}

## 본문 순서 (4문장, 줄바꿈으로 구분)
1. 최근 있었던 일을 한 문장으로: 아래 리뷰들에서 빠졌던 품목을 묶어서, 특정 손님을 가리키지 않고 서술
2. 짧은 사과 한 문장
3. "{start_label}"로 시작해서 개선 조치를 알릴 것: {measure_rule}
4. 손님이 도와줄 수 있는 것: 다음 주문 때 요청사항에 적어 주시면 챙기겠다는 안내

## 길이·금지
한 문장(줄)마다 60자 안팎, 총 4줄. 아래 리뷰 원문을 그대로 베끼지 말고 새로 쓸 것. 금전 보상 약속·고객 개인정보 금지.
"없을 것입니다"·"절대"·"완벽" 같은 장담이나 "도입했습니다"처럼 이미 끝난 일처럼 말하지 말고,
"~하겠습니다"처럼 앞으로 할 일로만 쓸 것.
"보내드렸습니다"·"챙겨 드렸"·"환불해 드렸"·"다시 보내"·"재발송"처럼 아직 하지 않은 조치를 이미 처리한 것처럼 말하지 말 것.
{measures_section}

## 반복 불만 리뷰
{review_lines}
"""


def _notice_topic(target_reviews):
    counts: dict[str, int] = {}
    for rv in target_reviews:
        for t in (rv.negative_topics or rv.topics or []):
            counts[t] = counts.get(t, 0) + 1
    if not counts:
        return _DEFAULT_TOPIC
    top = max(counts, key=counts.get)
    return _TOPIC_LABELS.get(top, _DEFAULT_TOPIC)


def assemble_notice(title: str, start_line: str, body: str, closing: str) -> str:
    """제목 줄 + 시작 줄 + 본문(줄마다 문장) + 마무리 줄을 줄바꿈으로 조립한다."""
    body_lines = [ln.strip() for ln in body.strip().splitlines() if ln.strip()]
    if not body_lines and body.strip():
        body_lines = [body.strip()]
    return "\n".join([title, start_line, *body_lines, closing])


def _insert_measure_line(body: str, line: str) -> str:
    """조치 키워드가 본문에 없을 때, 마지막 줄(요청사항 안내) 바로 앞에 줄을 끼워 넣는다."""
    lines = [ln for ln in body.strip().splitlines() if ln.strip()]
    if not lines:
        return line
    if len(lines) == 1:
        return f"{lines[0]}\n{line}"
    return "\n".join(lines[:-1] + [line] + lines[-1:])


def generate_prevention_notice(ctx, card, key, model="HCX-005", chosen_measures=None,
                                reply_texts=None, start_label="오늘부터"):
    store = ctx.store
    tone = ctx.tone
    review_map = {r.review_id: r for r in ctx.reviews}
    target_reviews = [review_map[rid] for rid in card.review_ids if rid in review_map]
    forbidden_phrases = list(tone.forbidden_phrases) if tone.forbidden_phrases else []

    store_display = display_name(store.name)
    topic = _notice_topic(target_reviews)
    title = f"[안내] {topic} 관련"
    start_line = f"{store_display}{eul(store_display)} 찾아 주시는 분들께"
    closing_line = f"늘 찾아 주셔서 감사합니다. {store_display} 드림"

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
        store_name=store_display,
        fewshot=NOTICE_FEWSHOT,
        start_label=start_label,
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
            "length_ok": checks.length_ok(body, 60, 220),
            "chosen_measure_included": checks.chosen_measure_included(text, chosen_measures),
            "no_invented_measure": not checks.has_invented_measure(text, chosen_measures),
            "not_quote_review": not checks.quotes_review(body, target_reviews),
            # AI 가 쓴 본문(body)만 본다 — 코드가 붙이는 제목·시작·마무리 줄은 대상이 아니다.
            # 사전(STIFF_WORDS)에 있는 단어만 걸리고, 합니다체 자체는 딱딱함으로 보지 않는다.
            "no_stiff_words": not checks.has_stiff_words(body),
            "no_overpromise": not checks.has_overpromise(text),
            "no_claimed_action": not checks.has_claimed_action(text),
            "has_apology": "죄송" in body,
            "notice_has_start": checks.notice_has_start(body, start_label),
            "notice_not_personal": checks.notice_not_personal(text),
            "notice_formal": checks.notice_formal(body),
            "notice_vs_reply": checks.notice_vs_reply(text, reply_texts),
        }
        if forbidden_phrases:
            result["no_forbidden_phrase"] = not checks.forbidden_phrase(text, forbidden_phrases)
        return result

    retry_exempt = ("length_ok",)
    evidence_ids = _compute_evidence()

    def _check(body_):
        text_ = assemble_notice(title, start_line, body_, closing_line)
        chk_ = _run_notice_checks(body_, text_)
        failed_ = [k for k, v in chk_.items() if not v and k not in retry_exempt]
        return text_, chk_, failed_

    messages = [{"role": "user", "content": f"카드 이유: {card.reason_text}"}]

    start = time.perf_counter()
    total_won = 0.0
    rewrites = 0

    resp = clova.call(key, system, messages, model=model, max_tokens=512, temperature=0.5)
    total_won += resp.get("won", 0)
    raw = resp.get("content", "")
    body = parsing.extract_body(raw)  # JSON이든 평문이든 본문을 절대 버리지 않는다

    text, check_results, failed = _check(body)

    if failed and body:
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

    # 조치 키워드가 본문에 이미 없을 때만 표준 문장을 마지막 줄(요청사항 안내) 바로 앞에 끼워 넣는다
    if chosen_measures and not checks.chosen_measure_included(body, chosen_measures):
        fallback = MEASURE_FALLBACK_SENTENCES.get(chosen_measures[0]["id"], chosen_measures[0]["text"])
        body = _insert_measure_line(body, f"{start_label} {fallback}")

    # 최종 조립 = 제목 줄 + 시작 줄 + AI 본문(그대로, 필요하면 끼워 넣은 줄 포함) + 마무리 줄
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
        model=model,
        elapsed_ms=elapsed_ms,
        data_origin=store.data_origin,
    )

    return CardResult(
        card_id=card.card_id, kind=card.kind, reason_text=card.reason_text,
        drafts=[draft], chosen_measures=chosen_measures or [],
        elapsed_ms=elapsed_ms, won=round(total_won, 4),
    )
