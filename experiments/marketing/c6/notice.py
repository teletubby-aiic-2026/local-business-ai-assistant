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
from c6.reply import _missing_items
from common.korean import display_name, eul, join_item_groups, josa

_MAX_REWRITES = 2  # 답글(c6.reply) 과 같은 한도 — 이만큼 다시 써도 점검을 못 넘으면 코드 템플릿으로 바꿔 넣는다

NOTICE_FEWSHOT = (
    "최근 공깃밥, 수저, 계란말이가 빠진 상태로 배달된 일이 있었습니다.\n"
    "불편을 드려 죄송합니다.\n"
    "오늘부터 포장 마감 전에 주문서와 한 번 더 대조해보고 배달해드리겠습니다.\n"
    "이외에도 필요한 게 있으면 요청사항에 적어 주세요."
)

_TOPIC_LABELS = {"missing_item": "포장 누락"}
_DEFAULT_TOPIC = "운영 개선"

# 두 번 다시 써도 점검을 못 넘으면 쓰는 코드 템플릿 (c6.reply 의 used_fallback 과 같은 방식).
# {item}{particle} 은 리뷰 사실(F)에서 뽑은 빠진 품목 + 조사, {measure_sentence} 는 고른 조치의
# 합니다체 문장(c6.measures.MEASURE_FALLBACK_SENTENCES).
NOTICE_FALLBACK_TMPL = (
    "최근 {item}{particle} 빠진 상태로 배달된 일이 있었습니다.\n"
    "불편을 드려 죄송합니다.\n"
    "{start_label} {measure_sentence}\n"
    "이외에도 필요한 게 있으면 요청사항에 적어 주세요."
)
_NOTICE_FALLBACK_GENERIC_MEASURE = "비슷한 일이 반복되지 않도록 더 신경 쓰겠습니다."

# MEASURE_FALLBACK_SENTENCES 는 "앞으로 ~하겠습니다" 꼴이라, start_label("오늘부터")과 바로 이어 붙이면
# "오늘부터 앞으로 포장 마감 전에…"처럼 시점 표현이 겹친다. 조치 문장 앞의 이런 표현은 지우고 붙인다.
_LEADING_TIME_PHRASES = ("앞으로는", "앞으로", "다음부터는", "다음부터", "이제부터는", "이제부터")


def _drop_leading_time_phrase(sentence: str) -> str:
    s = sentence.strip()
    for phrase in _LEADING_TIME_PHRASES:
        if s.startswith(phrase):
            return s[len(phrase):].lstrip()
    return s


def _dedupe_start_label_line(body: str, start_label: str) -> str:
    """AI 가 쓴 본문에도 "{start_label} 앞으로/다음부터/이제부터 ..."처럼 시점 표현이 겹치는 줄이
    있으면 지운다(코드가 붙이는 fallback 문장은 _drop_leading_time_phrase 를 이미 직접 쓴다)."""
    if not body or not start_label:
        return body
    out_lines = []
    for ln in body.splitlines():
        stripped = ln.strip()
        if stripped.startswith(start_label):
            rest = stripped[len(start_label):].lstrip()
            new_rest = _drop_leading_time_phrase(rest)
            if new_rest != rest:
                stripped = f"{start_label} {new_rest}" if new_rest else start_label
        out_lines.append(stripped if stripped else ln)
    return "\n".join(out_lines)

SYSTEM_TMPL = """\
당신은 {store_name} 사장님입니다. 반복되는 손님 불만에 대해 "모든 손님에게 알리는 공지" 본문 4문장만 쓰세요.
제목·시작 인사·마무리 인사는 쓰지 마세요. 코드가 따로 붙입니다. JSON이 아니라 문장 그대로 답해도 됩니다.

## 말투 (반드시 지킬 것)
모든 문장을 합니다체로 쓸 것(해요체·반말 금지) — 문장 끝이 전부 "-습니다"·"-니다"·"-세요" 중 하나로 끝나야 합니다.
"고객님"·"주문하신"처럼 손님 한 명을 가리키는 말은 쓰지 말 것 —
이 공지는 한 손님에게 보내는 답글이 아니라 모든 손님에게 알리는 글입니다.
문장마다 줄을 바꿀 것(한 줄 = 한 문장, 총 4줄, 더 쪼개거나 합치지 말 것).

## 좋은 예시 (문장 수·줄바꿈·어미를 그대로 따라 쓰고, 내용만 새로 쓸 것)
{fewshot}

## 본문 순서 (4문장, 줄바꿈으로 구분) — 위 예시와 같은 구조
1. 최근 있었던 일을 한 문장으로: 아래 리뷰들에서 빠졌던 품목을 묶어서, 특정 손님을 가리키지 않고 서술. "-습니다"로 끝날 것
2. 짧은 사과 한 문장. "-습니다"로 끝날 것
3. 반드시 "{start_label}"로 시작하는 문장 1개. 개선 조치를 알릴 것: {measure_rule}. "-겠습니다"로 끝날 것
4. 손님이 도와줄 수 있는 것: 다음 주문 때 요청사항에 적어 주시면 챙기겠다는 안내. "-세요"로 끝날 것

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


def _notice_fallback_item_groups(target_reviews, menu_names):
    """공지 대상 리뷰별로 빠진 품목을 묶음으로 뽑는다(리뷰 1건 = 묶음 1개, c6.reply._missing_items 재사용).
    common.korean.join_item_groups 가 묶음 안은 '와/과', 묶음끼리는 쉼표로 잇는다."""
    return [_missing_items(rv.text, menu_names) for rv in target_reviews]


def _notice_missing_item_phrase(target_reviews, menu_names) -> tuple[str, str]:
    """공지 대상 리뷰에서 빠진 품목 목록(item)과 그 조사(particle)를 뽑는다."""
    groups = [g for g in _notice_fallback_item_groups(target_reviews, menu_names) if g]
    item = join_item_groups(groups) if groups else "포장 품목"
    return item, josa(item, "이", "가")


def _notice_first_sentence(target_reviews, menu_names) -> str:
    """공지 첫 문장은 항상 코드가 넣는다 — AI 가 품목을 빠뜨리거나 지어내지 못하도록."""
    item, particle = _notice_missing_item_phrase(target_reviews, menu_names)
    return f"최근 {item}{particle} 빠진 상태로 배달된 일이 있었습니다."


def _replace_first_line(body: str, new_first: str) -> str:
    lines = [ln for ln in body.strip().splitlines() if ln.strip()]
    if not lines:
        return new_first
    return "\n".join([new_first] + lines[1:])


def _notice_fallback_text(target_reviews, menu_names, chosen_measures, start_label):
    """두 번 다시 써도 점검을 못 넘으면 쓰는 코드 템플릿 본문 (c6.reply._fallback_sentence 와 같은 방식).
    "주문하신" 처럼 손님 한 명을 가리키는 말은 notice_not_personal 에 걸리니 기본값으로 쓰지 않는다."""
    item, particle = _notice_missing_item_phrase(target_reviews, menu_names)
    if chosen_measures:
        measure_sentence = MEASURE_FALLBACK_SENTENCES.get(
            chosen_measures[0]["id"], chosen_measures[0]["text"],
        )
    else:
        measure_sentence = _NOTICE_FALLBACK_GENERIC_MEASURE
    measure_sentence = _drop_leading_time_phrase(measure_sentence)
    return NOTICE_FALLBACK_TMPL.format(
        item=item, particle=particle, start_label=start_label, measure_sentence=measure_sentence,
    )


def generate_prevention_notice(ctx, card, key, model="HCX-005", chosen_measures=None,
                                reply_texts=None, start_label="오늘부터"):
    store = ctx.store
    tone = ctx.tone
    menu_names = list(store.menu)
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
            "no_broken_ending": checks.no_broken_ending(text),
            "no_overpromise": not checks.has_overpromise(text),
            "no_claimed_action": not checks.has_claimed_action(text),
            "has_apology": checks.has_apology(body),
            "notice_has_start": checks.notice_has_start(body, start_label),
            "notice_not_personal": checks.notice_not_personal(text),
            "notice_formal": checks.notice_formal(body),
            "notice_vs_reply": checks.notice_vs_reply(text, reply_texts),
            "notice_no_complaint_word": checks.notice_no_complaint_word(text),
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

    resp = clova.call(key, system, messages, model=model, max_tokens=512, temperature=0.3)
    total_won += resp.get("won", 0)
    raw = resp.get("content", "")
    body = parsing.extract_body(raw)  # JSON이든 평문이든 본문을 절대 버리지 않는다
    body = _dedupe_start_label_line(body, start_label)

    text, check_results, failed = _check(body)

    while failed and body and rewrites < _MAX_REWRITES:
        hints = checks.fix_hints(failed, formal=True)
        # notice_formal 이 걸렸으면, 해요체로 끝난 줄을 그대로 보여 주고 고치게 한다
        if "notice_formal" in failed:
            bad_lines = checks.notice_informal_lines(body)
            if bad_lines:
                hints = hints + [
                    "해요체(-요)로 끝난 문장: " + " / ".join(bad_lines) + " → 합니다체로 고쳐 주세요.",
                ]
        retry_msg = [
            {"role": "user", "content": f"카드 이유: {card.reason_text}"},
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "수정 지시:\n" + "\n".join(f"- {h}" for h in hints)},
        ]
        resp2 = clova.call(key, system, retry_msg, model=model, max_tokens=512, temperature=0.3)
        total_won += resp2.get("won", 0)
        raw = resp2.get("content", "")
        body2 = parsing.extract_body(raw)
        rewrites += 1
        if body2:
            body = _dedupe_start_label_line(body2, start_label)
        text, check_results, failed = _check(body)

    # 딱딱한 표현이 남으면 본문에만 사전대로 단어를 바꾼다 (추가 호출 없음)
    if not check_results.get("no_stiff_words", True):
        body = checks.fix_stiff_words(body)
        text, check_results, failed = _check(body)

    # 조치 키워드가 본문에 이미 없을 때만 표준 문장을 마지막 줄(요청사항 안내) 바로 앞에 끼워 넣는다
    if chosen_measures and not checks.chosen_measure_included(body, chosen_measures):
        fallback = MEASURE_FALLBACK_SENTENCES.get(chosen_measures[0]["id"], chosen_measures[0]["text"])
        fallback = _drop_leading_time_phrase(fallback)
        body = _insert_measure_line(body, f"{start_label} {fallback}")
        text, check_results, failed = _check(body)

    # 그래도(총 1 + _MAX_REWRITES 번 시도) 점검을 못 넘으면 코드 템플릿으로 바꿔 넣고 통과 처리한다
    # (c6.reply 의 used_fallback 과 같은 방식). needs_input 에는 남기지 않는다 — 대체 문장은 늘
    # 점검을 통과하므로 사람이 볼 필요가 없다.
    used_fallback = bool(failed)
    if used_fallback:
        body = _notice_fallback_text(target_reviews, menu_names, chosen_measures, start_label)
        text, check_results, failed = _check(body)

    # 공지 첫 문장은 AI 가 아니라 늘 코드가 넣는다 — 빠진 품목을 빠뜨리거나 지어내지 못하도록
    body = _replace_first_line(body, _notice_first_sentence(target_reviews, menu_names))
    text, check_results, failed = _check(body)
    check_results["used_fallback"] = used_fallback

    elapsed_ms = round((time.perf_counter() - start) * 1000)

    draft = DraftOutput(
        draft_id=f"d_{uuid.uuid4().hex[:8]}",
        card_id=card.card_id,
        store_id=store.store_id,
        generator="prevention_notice",
        text=text,
        evidence_ids=evidence_ids,
        checks=check_results,
        failed_reasons=checks.fix_hints(failed, formal=True) if failed else [],
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
