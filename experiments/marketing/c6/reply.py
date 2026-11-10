"""리뷰 답글 생성기 — 리뷰 1개당 LLM 1회 호출(ThreadPoolExecutor로 동시 실행) → 점검 → 다시 쓰기.

구조: 시작 인사 + [AI 공감·사과 1~2문장] + [코드 조치 문장(M1)] + [코드 요청사항 문장(P1)] + 마무리.
AI 는 리뷰에서 빠진 품목을 짚는 공감·사과만 쓴다 — 조치·요청사항·감사 인사는 전부 코드가 붙인다.
답글마다 말투 3종(haeyo/hamnida/mixed)을 카드 리뷰 순서대로 돌아가며 쓴다(c6.measures.REPLY_STYLES) —
haeyo 는 전부 해요체, hamnida 는 전부 합니다체, mixed 는 공감(AI)만 해요체이고 조치·요청사항은 합니다체다.
시작 인사·마무리·M1·P1 고정 문구는 모두 c6.measures 에 말투별로 정의돼 있고, c6.style.assemble 로 조립한다.
근거 ID(F_리뷰id·M1·P1)는 늘 고정으로 붙는다.
"""

import json
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import config
import clova
from c6 import checks
from c6 import parsing
from c6.measures import (
    MEASURES, REPLY_STYLES, REPLY_STYLE_REGISTER, REPLY_AI_REGISTER,
    REPLY_OPENING, REPLY_CLOSING, M1_SENTENCES, P1_SENTENCES, REPLY_FEWSHOT,
)
from c6.style import assemble
from c6.output import DraftOutput, CardResult
from common.korean import display_name

# --mock 으로 돌릴 때는 live 결과 파일(c6_reply_raw.txt)을 더럽히지 않도록 따로 쓴다
_RAW_LOG = config.RESULTS_DIR / ("c6_reply_raw_mock.txt" if "--mock" in sys.argv else "c6_reply_raw.txt")

_TASTE = re.compile(r"맛있|맛없|맛이|맛도|맛은|밋밋|짜|싱거|느끼|달|매워|매운|맵|쓴|텁텁")
_AMOUNT = re.compile(r"양이|양도|양은|많|적|푸짐|부족|넉넉|모자")

_LIST_KEY = re.compile(r"^(답글|replies|answers)$", re.I)
_ID_KEY = re.compile(r"^(review_id|리뷰ID|id)$", re.I)
_TEXT_KEY = re.compile(r"^(text|답글|reply)$", re.I)
_EVIDENCE_KEY = re.compile(r"^(근거|evidence|evidence_ids)$", re.I)

_RETRY_EXEMPT = ("length_ok", "uses_opening", "uses_closing")  # 참고만: 다시 쓰기 사유에서 제외

_raw_log_started = False
_raw_log_lock = threading.Lock()


def _log_raw(text, review_id):
    """실행마다 한 번만 새로 쓰고, 그 뒤 호출은 이어 붙인다. 호출 1번 = review_id 1개."""
    global _raw_log_started
    _RAW_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _raw_log_lock:
        mode = "w" if not _raw_log_started else "a"
        _raw_log_started = True
        with open(_RAW_LOG, mode, encoding="utf-8") as f:
            f.write(f"--- review_id: {review_id} ---\n{text}\n\n")


def _robust_parse(text):
    """JSON 파싱(배열·fenced code block 허용). c6.reply 밖에서도 쓰는 공용 파서라 남겨 둔다."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    cleaned = cleaned.strip()

    start = -1
    for i, ch in enumerate(cleaned):
        if ch in "{[":
            start = i
            break
    if start < 0:
        return None, "JSON 시작 문자 '{' 또는 '[' 없음"

    end = -1
    target = "}" if cleaned[start] == "{" else "]"
    for i in range(len(cleaned) - 1, start - 1, -1):
        if cleaned[i] == target:
            end = i
            break
    if end < 0:
        return None, f"JSON 닫는 '{target}' 없음"

    try:
        data = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as e:
        return None, f"json.loads 실패: {e}"

    return data, None


def _normalize_replies(data, fallback_ids):
    """예전 '답글' 배열 형식 파서. 더 쓰지는 않지만 공용 유틸로 남겨 둔다."""
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = None
        for k in data:
            if _LIST_KEY.match(k):
                items = data[k]
                break
        if items is None:
            return None, f"응답 JSON 파싱 실패: 키 '답글' 없음 (있는 키: {list(data.keys())})"
    else:
        return None, f"최상위 타입이 dict/list 아님: {type(data).__name__}"

    if not isinstance(items, list):
        return None, f"답글 목록이 list 아님: {type(items).__name__}"

    normalized = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        rid = None
        for k in item:
            if _ID_KEY.match(k):
                rid = item[k]
                break
        if rid is None and idx < len(fallback_ids):
            rid = fallback_ids[idx]

        text = ""
        for k in item:
            if _TEXT_KEY.match(k):
                text = item[k]
                break

        evidence = []
        for k in item:
            if _EVIDENCE_KEY.match(k):
                evidence = item[k] if isinstance(item[k], list) else []
                break

        normalized.append({"review_id": rid, "text": text, "근거": evidence})

    return normalized, None


SYSTEM_TMPL = """\
당신은 {store_name} 사장님입니다. 아래 리뷰에 대한 답글 중 "공감·사과 부분만" 작성하세요.
인사말·마무리 인사·개선 조치 약속·요청사항 안내·감사 인사는 쓰지 마세요. 전부 코드가 따로 붙입니다.
JSON이 아니라 문장 그대로 답해도 됩니다.

## 좋은 예시 (이런 느낌으로)
- {fewshot}

## 규칙
1. 사장님이 손님에게 직접 말하듯, {register}로만(다른 말투와 섞지 말 것), 1~2문장, 전체 40~70자
2. 이 리뷰에서 빠진 품목을 구체적으로 짚어 공감·사과만 할 것
3. 메뉴판에 없는 가격·숫자를 넣지 말 것
4. 금전 보상(쿠폰·할인·무료 제공·증정 등)을 약속하지 말 것
5. 고객 개인정보(이름·전화번호·주소)를 쓰지 말 것
6. "챙기"·"확인"·"대조"·"요청"·"다음에"·"다음부터"·"앞으로"·"감사" 같은 말은 절대 쓰지 말 것 —
   개선 조치·요청사항 안내·감사 인사는 이어서 코드가 붙입니다.
7. "없을 거예요"·"절대"·"완벽" 같은 장담이나 "도입했으니"처럼 이미 끝난 일처럼 말하지 말 것
8. "보내드렸어요"·"챙겨 드렸"·"환불해 드렸"·"다시 보내"·"재발송"처럼 아직 하지 않은 일을 이미 처리한 것처럼 말하지 말 것

## 사실
{fact_line}

## 출력
공감·사과 문장만 답하세요(따옴표·설명 없이). {{"text": "..."}} 형식으로 답해도 됩니다.
"""


def _missing_items(review_text, menu_names):
    found = []
    for m in menu_names:
        if re.search(rf"{re.escape(m)}.{{0,8}}(안 왔|빠져|빠졌|누락|없|안 들어)", review_text):
            found.append(m)
    return found


def _fact_line(review, menu_names):
    missing = _missing_items(review.text, menu_names)
    parts = [f"F_{review.review_id}.missing={','.join(missing) if missing else '없음'}"]
    parts.append(f"taste={'Y' if _TASTE.search(review.text) else 'N'}")
    parts.append(f"amount={'Y' if _AMOUNT.search(review.text) else 'N'}")
    return " / ".join(parts)


# 답글은 늘 M1 조치 문장 + P1 요청사항 문장을 코드가 붙이므로, 점검도 이 기준으로 본다.
_EFFECTIVE_MEASURES = [MEASURES[0]]


def _compute_evidence(review):
    """코드가 항상 M1 조치·P1 요청사항 문장을 붙이므로 근거도 늘 F_리뷰id·M1·P1."""
    return [f"F_{review.review_id}", "M1", "P1"]


def _run_checks(text, review, menu_names, allowed_numbers, policies,
                 forbidden_phrases, evidence, valid_ids):
    missing = _missing_items(review.text, menu_names)
    result = {
        "evidence_valid": bool(evidence) and all(e in valid_ids for e in evidence),
        "no_invented_measure": not checks.has_invented_measure(text, _EFFECTIVE_MEASURES),
        "chosen_measure_included": checks.chosen_measure_included(text, _EFFECTIVE_MEASURES),
        "missing_mentioned": any(m in text for m in missing) if missing else True,
        "no_bad_promise": not checks.promises_not_in_policy(text, policies),
        "no_bad_number": not checks.has_number_not_in(text, allowed_numbers),
        "no_personal_info": not checks.personal_info(text),
        "length_ok": checks.length_ok(text, 120, 260),
        "no_stiff_words": not checks.has_stiff_words(text),
        "no_overpromise": not checks.has_overpromise(text),
        "no_claimed_action": not checks.has_claimed_action(text),
        "uses_opening": True,
        "uses_closing": True,
    }
    if forbidden_phrases:
        result["no_forbidden_phrase"] = not checks.forbidden_phrase(text, forbidden_phrases)
    return result


def _process_review(review, *, idx, card_id, store, store_display, menu_names, allowed_numbers,
                     policies, forbidden_phrases, valid_ids, key, model):
    style = REPLY_STYLES[idx % len(REPLY_STYLES)]
    ai_register = REPLY_AI_REGISTER[style]
    measure_register = REPLY_STYLE_REGISTER[style]
    opening = REPLY_OPENING[style].format(store=store_display)
    closing = REPLY_CLOSING.format(store=store_display)
    measure_line = M1_SENTENCES[measure_register]
    request_line = P1_SENTENCES[measure_register]

    system = SYSTEM_TMPL.format(
        store_name=store_display, register=ai_register, fewshot=REPLY_FEWSHOT[ai_register],
        fact_line=_fact_line(review, menu_names),
    )
    user_line = f"[{review.review_id}] ★{review.rating if review.rating is not None else '?'} {review.text}"

    won = 0.0
    rewrites = 0

    def _call(content):
        nonlocal won
        resp = clova.call(key, system, [{"role": "user", "content": content}],
                           model=model, max_tokens=200, temperature=0.5)
        won += resp.get("won", 0)
        raw = resp.get("content", "")
        _log_raw(raw, review.review_id)
        return parsing.extract_body(raw)  # JSON이든 평문이든 본문을 절대 버리지 않는다

    def _build_body(ai_part):
        parts = [p.strip() for p in (ai_part, measure_line, request_line) if p and p.strip()]
        return " ".join(parts)

    def _check(ai_part):
        body_ = _build_body(ai_part)
        text_ = assemble(opening, body_, closing)
        evidence_ = _compute_evidence(review)
        chk_ = _run_checks(text_, review, menu_names, allowed_numbers, policies,
                            forbidden_phrases, evidence_, valid_ids)
        chk_["ai_part_only_empathy"] = checks.ai_part_only_empathy(ai_part)
        chk_["style_match"] = checks.style_match(ai_part, body_, style)
        failed_ = [k for k, v in chk_.items() if not v and k not in _RETRY_EXEMPT]
        return text_, evidence_, chk_, failed_

    ai_body = _call(user_line)
    text, evidence, chk, failed = _check(ai_body)

    if failed and ai_body:
        hints = checks.fix_hints(failed)
        ai_body2 = _call(user_line + "\n\n수정 지시:\n" + "\n".join(f"- {h}" for h in hints))
        if ai_body2:
            ai_body = ai_body2
            rewrites = 1
        text, evidence, chk, failed = _check(ai_body)

    # 딱딱한 표현이 남으면 AI 가 쓴 공감·사과 부분에만 사전대로 단어를 바꾼다 (추가 호출 없음)
    if not chk.get("no_stiff_words", True):
        ai_body = checks.fix_stiff_words(ai_body)
        text, evidence, chk, failed = _check(ai_body)

    draft = DraftOutput(
        draft_id=f"d_{uuid.uuid4().hex[:8]}",
        card_id=card_id,
        store_id=store.store_id,
        generator="reply_draft",
        target_review_id=review.review_id,
        text=text,
        evidence_ids=evidence,
        checks=chk,
        failed_reasons=checks.fix_hints(failed) if failed else [],
        rewrites=rewrites,
        model=model,
        data_origin=store.data_origin,
        style=style,
    )
    return draft, won


def generate_reply_draft(ctx, card, key, model="HCX-005", chosen_measures=None):
    # chosen_measures 는 registry 호출 시그니처 호환용으로 받지만 쓰지 않는다 — 답글은
    # 늘 M1 조치 문장 + P1 요청사항 문장을 코드가 고정으로 붙인다(구조 설명은 모듈 docstring 참고).
    store = ctx.store
    store_display = display_name(store.name)
    menu_names = list(store.menu)
    allowed_numbers = list(store.menu_prices.values())
    policies = ctx.policies
    review_map = {r.review_id: r for r in ctx.reviews}
    target_reviews = [review_map[rid] for rid in card.review_ids if rid in review_map]
    forbidden_phrases = list(ctx.tone.forbidden_phrases) if ctx.tone.forbidden_phrases else []

    valid_ids = {f"F_{r}" for r in review_map} | {p["policy_id"] for p in policies} | {"M1"}

    start = time.perf_counter()
    drafts = [None] * len(target_reviews)
    total_won = 0.0

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(
                _process_review, rv, idx=i, card_id=card.card_id,
                store=store, store_display=store_display, menu_names=menu_names,
                allowed_numbers=allowed_numbers, policies=policies,
                forbidden_phrases=forbidden_phrases,
                valid_ids=valid_ids, key=key, model=model,
            ): i
            for i, rv in enumerate(target_reviews)
        }
        for fut in futures:
            i = futures[fut]
            draft, won = fut.result()
            drafts[i] = draft
            total_won += won

    # 같은 리뷰 묶음이니 서로 너무 비슷하지 않은지는 전부 끝난 뒤에 본다 (추가 호출 없음)
    texts = [d.text for d in drafts]
    for i, d in enumerate(drafts):
        others = [t for j, t in enumerate(texts) if j != i]
        similar = any(checks.too_similar(d.text, o) for o in others)
        d.checks["not_too_similar"] = not similar
        if similar:
            d.failed_reasons = list(d.failed_reasons) + checks.fix_hints(["not_too_similar"])

    elapsed_ms = round((time.perf_counter() - start) * 1000)
    for d in drafts:
        d.elapsed_ms = elapsed_ms

    return CardResult(
        card_id=card.card_id, kind=card.kind, reason_text=card.reason_text,
        drafts=drafts, chosen_measures=chosen_measures or [],
        elapsed_ms=elapsed_ms, won=round(total_won, 4),
    )
