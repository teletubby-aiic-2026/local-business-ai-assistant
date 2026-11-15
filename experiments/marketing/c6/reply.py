"""리뷰 답글 생성기 — 리뷰 1개당 LLM 1회 호출(ThreadPoolExecutor로 동시 실행) → 점검 → 다시 쓰기.

구조: 시작 인사 + [AI 공감·사과 1~2문장] + [코드 조치 문장(M1)] + [코드 요청사항 문장(P1)] + 마무리.
AI 는 리뷰에서 빠진 품목을 짚는 공감·사과만 쓴다 — 조치·요청사항·감사 인사는 전부 코드가 붙인다.
답글 말투는 reply_style 인자로 정한다(기본 "auto"):
- "auto": ToneProfile(c6.style.detect_register)로 사장님 말투가 해요체/합니다체인지 봐서 haeyo 또는 hamnida
  하나로 전부 통일한다(판단 불가하면 haeyo).
- "rotate": 카드 리뷰 순서대로 haeyo/hamnida/mixed 를 돌아가며 쓴다(c6.measures.REPLY_STYLES) — 데모·테스트용.
- "haeyo"/"hamnida"/"mixed": 그 말투로 전부.
haeyo 는 전부 해요체, hamnida 는 전부 합니다체, mixed 는 공감(AI)만 해요체이고 조치·요청사항은 합니다체다.
시작 인사·마무리 고정 문구는 c6.measures 에 말투별로 정의돼 있고, c6.style.assemble 로 조립한다.
M1·P1 고정 문구는 말투별로 3개씩 있어(c6.measures.M1_SENTENCES/P1_SENTENCES) 리뷰 순서(idx)로
돌려 쓴다 — reply_style="auto" 처럼 답글 3개의 말투가 전부 같아도 문장이 겹치지 않게 하기 위해서다.
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
    REPLY_OPENING, REPLY_CLOSING, M1_SENTENCES, P1_SENTENCES, REPLY_FEWSHOT, REPLY_FALLBACK_TMPL,
    COMPONENT_ITEMS,
)
from c6.style import assemble, detect_register
from c6.output import CALL_FAILED_NOTE, DraftOutput, CardResult
from c6.reply_explain import process_explain_review
from c6.stance import APOLOGY, EXPLAIN, judge_review
from common.korean import display_name, josa, join_item_groups

_MAX_REWRITES = 2  # 공감 부분을 이만큼 다시 써도 점검을 못 넘으면 코드 템플릿으로 바꿔 넣는다

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


_MISSING_KW = r"(?:안\s*왔|빠져|빠졌|누락|없|안\s*들어)"
# 메뉴·구성품 사전으로 못 찾을 때 쓰는 최후 수단: "OO이/가/을/를 ... 빠졌/누락/없음" 꼴에서 OO 을 꺼낸다.
_ITEM_FALLBACK_RE = re.compile(rf"(\S+?)(?:이|가|을|를)\s*\S*\s*{_MISSING_KW}")


def _missing_items(review_text, menu_names):
    """리뷰에서 빠졌다고 한 품목을 찾는다. 1순위: 메뉴판 이름 + 포장 구성품 사전(c6.measures.COMPONENT_ITEMS)
    중 빠짐 표현(_MISSING_KW)과 가까이(20자 안) 나오는 것 전부. 못 찾으면 2순위: 조사(이/가/을/를) +
    빠짐 표현으로 느슨하게 추출한 단어 1개. 둘 다 없으면 빈 리스트(호출부가 '주문하신 품목'으로 대신한다)."""
    found = []
    for item in list(menu_names) + COMPONENT_ITEMS:
        if item in found:
            continue
        if re.search(rf"{re.escape(item)}.{{0,20}}{_MISSING_KW}", review_text):
            found.append(item)
    if found:
        return found
    m = _ITEM_FALLBACK_RE.search(review_text)
    return [m.group(1)] if m else []


def fallback_apology(review, menu_names, register="해요체"):
    """AI 호출이 끝내 실패했을 때 쓰는 기본 사과 문장 (코드가 쓴다. 빠진 메뉴가 있으면 이름을 넣는다).
    AI 가 쓰는 공감·사과 자리에 들어가고, 조치(M1)·요청사항(P1)·인사·끝인사는 코드가 그대로 붙인다.
    register: 해요체 | 합니다체 (c6.measures.REPLY_AI_REGISTER)."""
    items = _missing_items(review.text, menu_names)
    sorry = "죄송합니다." if register == "합니다체" else "죄송해요."
    return f"{join_item_groups([items])} 건으로 불편을 드려 정말 {sorry}" if items else f"불편을 드려 정말 {sorry}"


def _fact_line(review, menu_names):
    missing = _missing_items(review.text, menu_names)
    parts = [f"F_{review.review_id}.missing={join_item_groups([missing]) if missing else '없음'}"]
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
    """전체 조립 글 기준 점검. no_stiff_words·style_match·ai_part_only_empathy·not_too_similar 는
    코드가 붙이는 M1·P1·인사·마무리를 건드리지 않도록 AI 가 쓴 부분만 따로 본다(_check 참고)."""
    missing = _missing_items(review.text, menu_names)
    result = {
        "evidence_valid": bool(evidence) and all(e in valid_ids for e in evidence),
        "no_invented_measure": not checks.has_invented_measure(text, _EFFECTIVE_MEASURES),
        "chosen_measure_included": checks.chosen_measure_included(text, _EFFECTIVE_MEASURES),
        "missing_mentioned": any(m in text for m in missing) if missing else True,
        "apology_expressed": checks.has_apology_anywhere(text),
        "no_bad_promise": not checks.promises_not_in_policy(text, policies),
        "no_bad_number": not checks.has_number_not_in(text, allowed_numbers),
        "no_personal_info": not checks.personal_info(text),
        "no_broken_ending": checks.no_broken_ending(text),
        "length_ok": checks.length_ok(text, 120, 260),
        "no_overpromise": not checks.has_overpromise(text),
        "no_claimed_action": not checks.has_claimed_action(text),
        "uses_opening": True,
        "uses_closing": True,
    }
    if forbidden_phrases:
        result["no_forbidden_phrase"] = not checks.forbidden_phrase(text, forbidden_phrases)
    return result


def _fallback_sentence(review, menu_names, register, idx):
    """공감 부분을 2번 다시 써도 점검을 못 넘으면 쓰는 코드 템플릿. 품목은 리뷰에서 빠진 품목
    전부를 common.korean.join_item_groups 로 연결(예: "수저와 젓가락"), 없으면 '주문하신 품목'.
    조사(이/가)는 common.korean.josa 로 고른다. 말투별 템플릿이 3개씩 있어 리뷰 순서(idx)로
    돌려 써서, 답글 여러 개가 한꺼번에 대체 문장을 써도 서로 겹치지 않게 한다."""
    missing = _missing_items(review.text, menu_names)
    item = join_item_groups([missing]) if missing else "주문하신 품목"
    particle = josa(item, "이", "가")
    variants = REPLY_FALLBACK_TMPL[register]
    return variants[idx % len(variants)].format(item=item, particle=particle)


# 다시 쓰기를 다 써도 남은 실패가 이것뿐이면 템플릿으로 통째 덮지 않고 코드가 AI 글의 그 부분만 고친다 (_repair_ai_part).
_REPAIRABLE = frozenset({"style_match", "apology_expressed"})


def _apology_addon(ai_part, register):
    """사과만 빠진 AI 글 끝에 붙이는 짧은 사과 한 문장 (말투별). AI 글에 이미 '정말'이 있으면 겹치지 않게 '진심으로'."""
    word = "진심으로" if "정말" in (ai_part or "") else "정말"
    return f"{word} 죄송합니다." if register == "합니다체" else f"{word} 죄송해요."


def _repair_ai_part(ai_part, failed, style, register):
    """다시 쓰기 뒤에도 남은 실패가 사과 말투·사과 빠짐뿐일 때, AI 가 쓴 공감 문장을 살리고 그 부분만 고친 글을 돌려준다.
    (a) style_match: 끝 사과 어미만 말투가 다르면 어미만 바꾼다('죄송합니다' → '죄송해요', 합니다체는 반대).
        사과가 아닌 문장의 말투가 다르면 고치지 않는다(원래 글을 그대로 돌려줘 템플릿으로 간다).
    (b) apology_expressed: 사과만 빠졌으면 말투에 맞는 짧은 사과 한 문장을 덧붙인다(_apology_addon).
    고칠 수 없으면 ai_part 를 그대로 돌려준다. 고친 글을 쓸지는 호출부가 점검을 다시 돌려 정한다."""
    if not ai_part or not failed or not set(failed) <= _REPAIRABLE:
        return ai_part
    fixed = ai_part
    if "style_match" in failed:
        fixed = checks.fix_apology_ending(fixed, style)
        if not checks.style_match(fixed, style):
            return ai_part
    if "apology_expressed" in failed:
        fixed = f"{fixed.rstrip()} {_apology_addon(fixed, register)}"
    return fixed


def _process_review(review, *, idx, card_id, store, store_display, menu_names, allowed_numbers,
                     policies, forbidden_phrases, valid_ids, key, model, fixed_style):
    style = fixed_style if fixed_style else REPLY_STYLES[idx % len(REPLY_STYLES)]
    ai_register = REPLY_AI_REGISTER[style]
    measure_register = REPLY_STYLE_REGISTER[style]
    opening = REPLY_OPENING[style].format(store=store_display)
    closing = REPLY_CLOSING.format(store=store_display)
    # 말투(해요체/합니다체)별로 3개씩 있는 M1·P1 고정 문장 중 리뷰 순서(idx)로 하나를 고른다 —
    # reply_style="auto" 처럼 답글 3개의 말투가 전부 같아도 문장이 겹치지 않게 하기 위해서다.
    measure_variants = M1_SENTENCES[measure_register]
    request_variants = P1_SENTENCES[measure_register]
    measure_line = measure_variants[idx % len(measure_variants)]
    request_line = request_variants[idx % len(request_variants)]

    # 답글 태도 (c6.stance): 가게 과실이 아닌 '요청 거절' 리뷰로 확실할 때만 사과 없이 설명하는 답글(reply_explain)로 간다.
    # 그 밖에는 아래의 사과 답글 그대로. 설명 답글의 AI 부분·원칙 문장은 늘 해요체라, 합니다체 인사와 만나면 '섞어서'가 된다.
    decision = judge_review(review)
    if decision.stance == EXPLAIN:
        draft, won = process_explain_review(
            review, decision, card_id=card_id, store=store, menu_names=menu_names, allowed_numbers=allowed_numbers,
            policies=policies, forbidden_phrases=forbidden_phrases, opening=opening, closing=closing,
            valid_ids=valid_ids, key=key, model=model, log_raw=_log_raw)
        draft.style = "haeyo" if style in ("haeyo", "mixed") else "mixed"
        # AI 부분(None)을 돌려주지 않아 답글끼리 비슷함 비교·다시 쓰기에서 빠진다 (사과 답글 프롬프트로 다시 쓰면 안 됨)
        return draft, won, None, None, None, None

    system = SYSTEM_TMPL.format(
        store_name=store_display, register=ai_register, fewshot=REPLY_FEWSHOT[ai_register],
        fact_line=_fact_line(review, menu_names),
    )
    user_line = f"[{review.review_id}] ★{review.rating if review.rating is not None else '?'} {review.text}"

    won = 0.0
    rewrites = 0
    call_errors = 0

    def _call(content):
        nonlocal won, call_errors
        resp = clova.call(key, system, [{"role": "user", "content": content}],
                           model=model, max_tokens=200, temperature=0.5)
        won += resp.get("won", 0)
        call_errors += bool(resp.get("error"))
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
        # AI 가 쓴 공감·사과 부분만 본다 — 코드가 붙이는 M1·P1·인사·마무리는 대상이 아니다
        chk_["no_stiff_words"] = not checks.has_stiff_words(ai_part)
        chk_["ai_part_only_empathy"] = checks.ai_part_only_empathy(ai_part)
        chk_["style_match"] = checks.style_match(ai_part, style)
        failed_ = [k for k, v in chk_.items() if not v and k not in _RETRY_EXEMPT]
        return text_, evidence_, chk_, failed_

    ai_body = _call(user_line)
    needs = []
    if call_errors and not ai_body:   # 호출이 끝내 실패해 AI 본문이 없다 → 코드가 쓴 기본 사과 문장으로 채우고 사장님께 알린다
        ai_body = fallback_apology(review, menu_names, ai_register)
        needs.append(CALL_FAILED_NOTE)
    text, evidence, chk, failed = _check(ai_body)

    rewrite_call_failed = False
    while failed and ai_body and not needs and rewrites < _MAX_REWRITES:   # 호출 실패로 채운 글은 다시 쓰지 않는다
        hints = checks.fix_hints(failed, register=ai_register)   # 목표 말투와 사과 예시를 같이 적는다 (사과↔말투 핑퐁 방지)
        errors_before = call_errors
        ai_body2 = _call(user_line + "\n\n수정 지시:\n" + "\n".join(f"- {h}" for h in hints))
        if call_errors > errors_before:   # 다시 쓰기 호출이 끝내 실패 → 더 부르지 않고 AI 글을 그대로 둔다 (점검 실패로 보임)
            rewrite_call_failed = True
            break
        rewrites += 1
        if ai_body2:
            ai_body = ai_body2
        text, evidence, chk, failed = _check(ai_body)

    # 딱딱한 표현이 남으면 AI 가 쓴 공감·사과 부분에만 사전대로 단어를 바꾼다 (추가 호출 없음)
    if failed and not chk.get("no_stiff_words", True):
        ai_body = checks.fix_stiff_words(ai_body)
        text, evidence, chk, failed = _check(ai_body)

    # 남은 실패가 사과 말투·사과 빠짐뿐이면 코드가 그 부분만 고친다 (추가 호출 없음, _repair_ai_part).
    # 고친 글이 점검을 전부 넘을 때만 쓰고, 아니면 아래 템플릿으로 간다. 고쳤는지는 checks.ai_part_repaired 로 남긴다.
    ai_part_repaired = False
    if failed and not needs and not rewrite_call_failed:
        repaired = _repair_ai_part(ai_body, failed, style, ai_register)
        if repaired != ai_body:
            r_text, r_evidence, r_chk, r_failed = _check(repaired)
            if not r_failed:
                ai_body, text, evidence, chk, failed = repaired, r_text, r_evidence, r_chk, r_failed
                ai_part_repaired = True

    # 그래도(총 1 + _MAX_REWRITES 번 시도) 점검을 못 넘으면 코드 템플릿으로 바꿔 넣고 통과 처리한다.
    # needs_input 에는 남기지 않는다 — 대체 문장은 늘 점검을 통과하므로 사람이 볼 필요가 없다.
    # 다시 쓰기 호출이 실패한 경우는 템플릿으로 덮지 않는다 — 사장님이 점검 실패를 보고 직접 고치게 한다
    used_fallback = bool(failed) and not rewrite_call_failed
    if used_fallback:
        ai_body = _fallback_sentence(review, menu_names, ai_register, idx)
        text, evidence, chk, failed = _check(ai_body)
    chk["used_fallback"] = used_fallback
    chk["ai_part_repaired"] = ai_part_repaired

    draft = DraftOutput(
        draft_id=f"d_{uuid.uuid4().hex[:8]}",
        card_id=card_id,
        store_id=store.store_id,
        generator="reply_draft",
        target_review_id=review.review_id,
        text=text,
        evidence_ids=evidence,
        checks=chk,
        failed_reasons=checks.fix_hints(failed, register=ai_register) if failed else [],
        rewrites=rewrites,
        needs_input=needs,
        model=model,
        data_origin=store.data_origin,
        stance=APOLOGY,
        stance_reasons=list(decision.reasons),
        style=style,
    )
    # not_too_similar(답글끼리 너무 겹치는지)는 다른 답글들이 다 끝나야 알 수 있어 여기선 못 본다.
    # generate_reply_draft 가 전부 끝난 뒤 한 번 더 써 볼 수 있도록 system·user_line·_check 를 같이 돌려준다.
    return draft, won, ai_body, system, user_line, _check


def generate_reply_draft(ctx, card, key, model="HCX-005", chosen_measures=None, reply_style="auto"):
    # chosen_measures 는 registry 호출 시그니처 호환용으로 받지만 쓰지 않는다 — 답글은
    # 늘 M1 조치 문장 + P1 요청사항 문장을 코드가 고정으로 붙인다(구조 설명은 모듈 docstring 참고).
    if reply_style == "auto":
        fixed_style = detect_register(ctx.tone)
    elif reply_style == "rotate":
        fixed_style = None
    elif reply_style in REPLY_STYLES:
        fixed_style = reply_style
    else:
        raise ValueError(
            f"reply_style은 'auto'/'rotate'/{REPLY_STYLES} 중 하나여야 합니다 (받은 값: {reply_style!r})"
        )

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
                valid_ids=valid_ids, key=key, model=model, fixed_style=fixed_style,
            ): i
            for i, rv in enumerate(target_reviews)
        }
        ai_parts = [None] * len(target_reviews)
        systems = [None] * len(target_reviews)
        user_lines = [None] * len(target_reviews)
        check_fns = [None] * len(target_reviews)
        for fut in futures:
            i = futures[fut]
            draft, won, ai_part, system, user_line, check_fn = fut.result()
            drafts[i] = draft
            ai_parts[i] = ai_part
            systems[i] = system
            user_lines[i] = user_line
            check_fns[i] = check_fn
            total_won += won

    # 같은 리뷰 묶음이니 서로 너무 비슷하지 않은지는 전부 끝난 뒤에 본다.
    # 코드가 붙이는 M1·P1·인사·마무리는 다 같이 겹치므로, AI 가 쓴 공감·사과 부분만 비교한다.
    # used_fallback=True 인 답글(코드 템플릿)은 비교에서 뺀다 — AI 가 쓴 게 아니라서 서로 비슷해도
    # 문제가 아니고, 템플릿도 말투별 3개를 돌려 쓰므로 실제로 겹칠 일이 드물다.
    # 비교 전에 리뷰 사실(F)에서 뽑은 품목 이름을 지운다 — "공깃밥이 빠져서 죄송해요"처럼 품목만
    # 다르고 틀이 같은 두 문장이 글자 수 차이만으로 서로 달라 보여 점검을 통과하는 걸 막기 위해서다.
    item_sets = [_missing_items(rv.text, menu_names) for rv in target_reviews]

    def _strip_items(text, items):
        for it in items:
            text = text.replace(it, "")
        return text

    def _similar_to_others(i, text):
        if not text:
            return False
        stripped_i = _strip_items(text, item_sets[i])
        for j, other in enumerate(ai_parts):
            if j == i or not other or drafts[j].checks.get("used_fallback") or CALL_FAILED_NOTE in drafts[j].needs_input:
                continue
            if checks.too_similar(stripped_i, _strip_items(other, item_sets[j])):
                return True
        return False

    for i, d in enumerate(drafts):
        # 템플릿(used_fallback)과 호출 실패로 채운 기본 문장은 비슷해도 된다 (사장님이 어차피 고친다)
        if d.checks.get("used_fallback") or CALL_FAILED_NOTE in d.needs_input:
            d.checks["not_too_similar"] = True
            continue
        similar = _similar_to_others(i, ai_parts[i])
        if similar:
            # 걸리면 1번만 다르게 다시 써 본다 (다른 답글과 겹친다고 알려 준다)
            retry_content = (
                user_lines[i] + "\n\n수정 지시:\n- 다른 답글과 표현이 겹쳐요. "
                "같은 뜻이라도 다른 표현으로 다시 써 주세요."
            )
            resp = clova.call(key, systems[i], [{"role": "user", "content": retry_content}],
                               model=model, max_tokens=200, temperature=0.5)
            total_won += resp.get("won", 0)
            raw = resp.get("content", "")
            _log_raw(raw, target_reviews[i].review_id)
            new_body = parsing.extract_body(raw)
            if new_body:
                new_text, new_evidence, new_chk, new_failed = check_fns[i](new_body)
                # 다른 점검까지 다 통과해야 바꿔 넣는다 (안 그러면 글이 더 나빠질 수 있다)
                if not new_failed:
                    ai_parts[i] = new_body
                    new_chk["used_fallback"] = False
                    new_chk["ai_part_repaired"] = False   # 새로 쓴 AI 글이 그대로 점검을 넘었다
                    d.text, d.evidence_ids, d.checks = new_text, new_evidence, new_chk
                    d.rewrites += 1
                    similar = _similar_to_others(i, ai_parts[i])
        # 그래도 비슷하면 실패가 아니라 참고로만 남긴다 — length_ok 처럼 failed_reasons·needs_input 에
        # 넣지 않는다(measure_live.py 의 RETRY_EXEMPT 도 같이 뺐다).
        d.checks["not_too_similar"] = not similar

    elapsed_ms = round((time.perf_counter() - start) * 1000)
    for d in drafts:
        d.elapsed_ms = elapsed_ms

    return CardResult(
        card_id=card.card_id, kind=card.kind, reason_text=card.reason_text,
        drafts=drafts, chosen_measures=chosen_measures or [],
        elapsed_ms=elapsed_ms, won=round(total_won, 4),
    )
