"""리뷰 답글 생성기 — 리뷰 1개당 LLM 1회 호출(ThreadPoolExecutor로 동시 실행) → 점검 → 다시 쓰기.

AI 는 본문만 쓴다(인사·마무리 금지). 시작 인사 + 본문 + 마무리는 코드가 조립하고(c6.style.assemble),
근거 ID(F_리뷰id·P1·M id)도 본문 내용을 보고 코드가 붙인다. 틀리면 안 되는 고정 문구·ID는 코드가,
AI는 가운데 본문만 책임진다.
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
from c6.measures import MEASURE_FALLBACK_SENTENCES
from c6.style import assemble, few_shot_examples, insert_before_last_sentence, owner_style
from c6.output import DraftOutput, CardResult

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
당신은 {store_name} 사장님입니다. 아래 리뷰에 대한 답글의 "본문만" 작성하세요.
인사말이나 마무리 인사는 쓰지 마세요. 코드가 따로 붙입니다. JSON이 아니라 문장 그대로 답해도 됩니다.

## 좋은 예시 (이런 느낌으로)
{examples_section}

## 규칙
1. 사장님이 손님에게 직접 말하듯 짧은 구어체 해요체로, 3~4문장, 한 문장은 40자 안팎
2. 순서: 리뷰에서 빠진 품목을 구체적으로 짚어 사과 → 확인·개선 약속(정책 범위 안에서만) → 감사
3. 이 리뷰 내용 한 가지를 구체적으로 짚을 것
4. 메뉴판에 없는 가격·숫자를 넣지 말 것
5. 금전 보상(쿠폰·할인·무료 제공·증정 등)을 약속하지 말 것
6. 고객 개인정보(이름·전화번호·주소)를 쓰지 말 것
7. {measure_rule}
8. "없을 거예요"·"절대"·"완벽" 같은 장담이나 "도입했으니"처럼 이미 끝난 일처럼 말하지 말고, "~할게요"처럼 앞으로 할 일로만 쓸 것

## 사실
{fact_line}

## 정책
{policies}
{measures_section}

## 출력
본문 문장만 답하세요(따옴표·설명 없이). {{"text": "..."}} 형식으로 답해도 됩니다.
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


def _measure_prompt_bits(chosen_measures):
    if chosen_measures:
        measure_rule = (
            "선택된 조치를 답글에 자연스럽게 한 번 포함할 것(그대로 쓰거나 자연스럽게 녹여서). "
            "체크리스트·절차·도입·별도 용기 등 다른 구체적 조치를 지어내지 말 것"
        )
        m_lines = [f"{m['id']}: {m['text']}" for m in chosen_measures]
        measures_section = "\n\n## 선택된 조치\n" + "\n".join(m_lines)
    else:
        measure_rule = (
            "구체적 개선 조치(체크리스트·절차·도입·별도 용기 등)를 지어내지 말 것. "
            "\"더 꼼꼼히 확인하겠습니다\" 같은 일반적인 다짐만 쓸 것"
        )
        measures_section = ""
    return measure_rule, measures_section


def _compute_evidence(text, review, menu_names, chosen_measures):
    """빠진 품목 언급 -> F_리뷰id, 요청사항·다음 주문 언급 -> P1, 조치 언급 -> M id. 절대 비우지 않는다."""
    ev = []
    missing = _missing_items(review.text, menu_names)
    if (missing and any(m in text for m in missing)) or not missing:
        ev.append(f"F_{review.review_id}")
    if "요청사항" in text or "다음 주문" in text:
        ev.append("P1")
    for m in (chosen_measures or []):
        if checks.measure_keywords_included(text, m["id"]) and m["id"] not in ev:
            ev.append(m["id"])
    if not ev:
        ev.append(f"F_{review.review_id}")
    return ev


def _run_checks(text, review, menu_names, allowed_numbers, policies,
                 chosen_measures, forbidden_phrases, evidence, valid_ids):
    missing = _missing_items(review.text, menu_names)
    result = {
        "evidence_valid": bool(evidence) and all(e in valid_ids for e in evidence),
        "no_invented_measure": not checks.has_invented_measure(text, chosen_measures),
        "chosen_measure_included": checks.chosen_measure_included(text, chosen_measures),
        "missing_mentioned": any(m in text for m in missing) if missing else True,
        "no_bad_promise": not checks.promises_not_in_policy(text, policies),
        "no_bad_number": not checks.has_number_not_in(text, allowed_numbers),
        "no_personal_info": not checks.personal_info(text),
        "length_ok": checks.length_ok(text, 120, 260),
        "no_stiff_words": not checks.has_stiff_words(text),
        "no_overpromise": not checks.has_overpromise(text),
        "uses_opening": True,
        "uses_closing": True,
    }
    if forbidden_phrases:
        result["no_forbidden_phrase"] = not checks.forbidden_phrase(text, forbidden_phrases)
    return result


def _process_review(review, *, card_id, store, menu_names, allowed_numbers, policies,
                     chosen_measures, forbidden_phrases, examples_section,
                     opening, closing, valid_ids, key, model):
    measure_rule, measures_section = _measure_prompt_bits(chosen_measures)
    system = SYSTEM_TMPL.format(
        store_name=store.name,
        examples_section="\n".join(f"- {s}" for s in examples_section),
        fact_line=_fact_line(review, menu_names),
        policies="\n".join(f"{p['policy_id']}: {p['text']}" for p in policies),
        measure_rule=measure_rule,
        measures_section=measures_section,
    )
    user_line = f"[{review.review_id}] ★{review.rating if review.rating is not None else '?'} {review.text}"

    won = 0.0
    rewrites = 0

    def _call(content):
        nonlocal won
        resp = clova.call(key, system, [{"role": "user", "content": content}],
                           model=model, max_tokens=400, temperature=0.5)
        won += resp.get("won", 0)
        raw = resp.get("content", "")
        _log_raw(raw, review.review_id)
        return parsing.extract_body(raw)  # JSON이든 평문이든 본문을 절대 버리지 않는다

    def _check(body_):
        text_ = assemble(opening, body_, closing)
        evidence_ = _compute_evidence(text_, review, menu_names, chosen_measures)
        chk_ = _run_checks(text_, review, menu_names, allowed_numbers, policies,
                            chosen_measures, forbidden_phrases, evidence_, valid_ids)
        failed_ = [k for k, v in chk_.items() if not v and k not in _RETRY_EXEMPT]
        return text_, evidence_, chk_, failed_

    body = _call(user_line)
    text, evidence, chk, failed = _check(body)

    if failed and body:
        hints = checks.fix_hints(failed)
        body2 = _call(user_line + "\n\n수정 지시:\n" + "\n".join(f"- {h}" for h in hints))
        if body2:
            body = body2
            rewrites = 1
        text, evidence, chk, failed = _check(body)

    # 딱딱한 표현이 남으면 본문에만 사전대로 단어를 바꾼다 (추가 호출 없음)
    if not chk.get("no_stiff_words", True):
        body = checks.fix_stiff_words(body)

    # 조치 키워드가 본문에 이미 없을 때만 표준 문장을 마지막 문장(감사·사과) 바로 앞에 끼워 넣는다
    if chosen_measures and not checks.chosen_measure_included(body, chosen_measures):
        fallback = MEASURE_FALLBACK_SENTENCES.get(chosen_measures[0]["id"], chosen_measures[0]["text"])
        body = insert_before_last_sentence(body, fallback)

    # 최종 조립 = 시작 인사 + AI 본문(그대로) + (필요하면 끼워 넣은 표준 문장) + 마무리
    text, evidence, chk, failed = _check(body)

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
    )
    return draft, won


def generate_reply_draft(ctx, card, key, model="HCX-005", chosen_measures=None):
    store = ctx.store
    menu_names = list(store.menu)
    allowed_numbers = list(store.menu_prices.values())
    policies = ctx.policies
    review_map = {r.review_id: r for r in ctx.reviews}
    target_reviews = [review_map[rid] for rid in card.review_ids if rid in review_map]
    forbidden_phrases = list(ctx.tone.forbidden_phrases) if ctx.tone.forbidden_phrases else []

    style_info = owner_style(ctx.owner_replies)
    opening = style_info.get("시작 인사") or "안녕하세요 고객님"
    closing = style_info.get("마무리") or f"{store.name} 드림"
    examples_section = few_shot_examples(ctx)

    valid_ids = {f"F_{r}" for r in review_map} | {p["policy_id"] for p in policies}
    if chosen_measures:
        valid_ids |= {m["id"] for m in chosen_measures}

    start = time.perf_counter()
    drafts = [None] * len(target_reviews)
    total_won = 0.0

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(
                _process_review, rv, card_id=card.card_id,
                store=store, menu_names=menu_names, allowed_numbers=allowed_numbers,
                policies=policies, chosen_measures=chosen_measures,
                forbidden_phrases=forbidden_phrases, examples_section=examples_section,
                opening=opening, closing=closing, valid_ids=valid_ids, key=key, model=model,
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
