"""사과 없이 사실·원칙을 설명하는 답글 — 가게 과실이 아닌 낮은 별점 리뷰용 (c6.stance 의 EXPLAIN).

c6.reply._process_review 가 리뷰마다 c6.stance.judge_review 로 태도를 정하고, EXPLAIN 이면 여기로 넘긴다.
사과 답글(APOLOGY)의 프롬프트·점검은 c6.reply 에 그대로 있고 바뀌지 않았다.

구조: 시작 인사 + [AI 공감 1~2문장] + [코드 원칙 문장] + [코드 다짐·고마움 문장] + 마무리.
- AI 는 리뷰의 메뉴·요청을 짚어 '원하시던 대로 해 드리지 못해 아쉬우셨을' 마음만 쓴다.
- 가게 원칙 문장(c6.stance.REQUESTS 의 principle)과 다짐 문장(CLOSING_LINE)은 틀리면 안 되는 고정 문구라 코드가 붙인다.
  (HCX-005 에게 원칙 설명까지 맡기면 합니다체·'환불'·'정책상'·'주문 시 참고 부탁' 같은 말이 섞여 점검을 자주 못 넘었다, 11/14 live)
점검(EXPLAIN_CHECKS)은 조립한 글 전체로 보고, 유감 표현·메뉴 짚기·딱딱한 말은 AI 가 쓴 부분만 본다. 걸리면 고칠 점을 붙여
다시 쓰게 하고(최대 MAX_REWRITES 번), 그래도 걸리면 AI 부분을 코드 기본 문장(fallback_empathy)으로 바꾸고 needs_input 에 적는다.
가게가 실제로 그랬는지는 시스템이 알 수 없으므로, 답글에는 늘 사장님 확인 안내(needs_input)와 태도·판정 근거를 싣는다.
"""
from __future__ import annotations

import time
import uuid

import clova
from c6 import checks
from c6 import parsing
from c6.output import DraftOutput
from c6.stance import EXPLAIN, EXPLAIN_NEEDS_INPUT, StanceDecision
from c6.style import assemble

MAX_REWRITES = 2   # 점검에 걸리면 고칠 점을 붙여 다시 쓰게 하는 횟수 (처음 1번 + 최대 2번)
RETRY_WAIT_S = 1.5   # 호출이 오류를 돌려주면 이만큼 기다렸다가 한 번 더 부른다
_RETRY_EXEMPT = ("length_ok", "uses_opening", "uses_closing")   # c6.reply 와 같음: 참고만, 다시 쓰기 사유에서 제외
CLOSING_LINE = "앞으로도 메뉴판 안에서 늘 정성껏 준비할게요. 남겨 주신 말씀 고마워요."
DEFAULT_PRINCIPLE = "저희는 메뉴판에 있는 구성대로만 준비하고 있어요."
FALLBACK_NOTE = "AI가 쓴 첫 문장이 점검을 넘지 못해 기본 문장으로 넣었어요. 리뷰 내용에 맞게 다듬어 주세요."
CALL_FAILED_NOTE = "AI 호출이 실패해 첫 문장을 기본 문장으로 넣었어요. 리뷰 내용에 맞게 다듬어 주세요."
# AI 부분만 보는 점검 (코드가 붙이는 원칙·다짐 문장은 대상이 아니다): has_regret, request_mentioned, haeyo_only, no_stiff_words

SYSTEM_TMPL = """\
당신은 {store_name} 사장님입니다. 아래 리뷰에 다는 답글 중 "첫머리 공감 부분만" 쓰세요.
인사말, 가게 원칙 설명, 다짐, 감사 인사는 쓰지 마세요. 당신이 쓴 문장 뒤에 코드가 아래 문장을 그대로 붙입니다.
- {principle}
- {closing_line}

## 상황
이 리뷰는 가게 쪽 문제가 아니라, 가게가 정한 메뉴·원칙 밖의 요청({request_name})을 들어드리지 못해 남은 낮은 별점이에요.
그래서 사과하거나 잘못을 인정하지 않고, 손님이 아쉬우셨을 마음에만 정중하게 공감합니다. 다른 손님이 읽어도 차분해 보이게 씁니다.

## 사실 (코드가 리뷰에서 찾은 것)
- 요청: {request_name}
- 리뷰에 나온 메뉴: {items}

## 규칙
1. 사장님이 손님에게 직접 말하듯 해요체로만, 1~2문장, 전체 30~80자. 문장은 "~것 같아요", "~셨겠어요"처럼 '요'로 끝낼 것.
   "~습니다", "~니다"로 끝내지 말 것
2. 손님이 원하셨던 것을 주어로, 리뷰에 나온 메뉴 이름과 요청을 짚어 아쉬우셨을 마음에 공감할 것
   (예: "{example}")
3. 사과·잘못 인정 금지: "죄송", "사과", "잘못", "실수", "불편을 드려", "책임" 같은 말을 쓰지 말 것
4. 손님을 탓하거나 가르치거나 비꼬지 말 것: "~하셔야", "원래", "당연히", "무리한", "억지", "규정", "참고 부탁" 같은 말 금지
5. 요청을 들어드리겠다는 약속 금지. "환불"·"쿠폰"·"무료"·"공짜"·"서비스"·"보상"·"증정"·"할인" 같은 낱말은 아예 쓰지 말 것
6. "다음에는", "앞으로" 같은 다짐과 가게 원칙 설명은 쓰지 말 것 (위의 문장을 코드가 붙입니다)
7. 숫자, 고객 개인정보(이름·전화번호·주소)를 쓰지 말 것. 손님을 부를 때는 "고객님"만

## 출력
공감 문장만 답하세요(따옴표·설명 없이). {{"text": "..."}} 형식으로 답해도 됩니다.
"""


def _principle(decision: StanceDecision) -> str:
    return decision.principle or DEFAULT_PRINCIPLE


def fallback_empathy(review_text: str, menu_names: list[str]) -> str:
    """AI 공감 문장이 끝내 점검을 못 넘을 때 쓰는 기본 문장 (EXPLAIN_CHECKS 를 늘 통과하게 만든다).
    리뷰에 나온 메뉴 이름이 있으면 짚는다: '계란말이 요청을 원하시던 대로 해 드리지 못해 아쉬우셨을 것 같아요.'"""
    items = checks.review_menu_items(review_text, menu_names)
    what = f"{items[0]} 요청을 " if items else ""
    return f"{what}원하시던 대로 해 드리지 못해 아쉬우셨을 것 같아요."


def build_system(store_name: str, menu_names: list[str], decision: StanceDecision, review_text: str = "") -> str:
    items = checks.review_menu_items(review_text, menu_names)
    return SYSTEM_TMPL.format(
        store_name=store_name, request_name=decision.request_name or "메뉴·원칙 밖의 요청",
        principle=_principle(decision), closing_line=CLOSING_LINE,
        items=", ".join(items) if items else "없음",
        example=fallback_empathy(review_text, menu_names),
    )


def build_body(ai_part: str, decision: StanceDecision) -> str:
    """AI 공감 + 코드 원칙 문장 + 코드 다짐 문장."""
    return " ".join(p.strip() for p in (ai_part, _principle(decision), CLOSING_LINE) if p and p.strip())


def _norm(s: str) -> str:
    return "".join(ch for ch in s if ch.isalnum())


def clean_ai_part(ai_part: str, decision: StanceDecision) -> str:
    """AI 부분 정리 (뜻은 바꾸지 않음): 줄바꿈·앞뒤 '-' 같은 군더더기를 지우고, 코드가 붙일 원칙·다짐 문장을
    AI 가 그대로 따라 쓴 문장은 뺀다 (같은 문장이 두 번 나오지 않게)."""
    text = " ".join((ai_part or "").replace("\n", " ").split()).strip(" -·\"'“”")
    code = {_norm(s) for s in checks._SENT_SPLIT.split(f"{_principle(decision)} {CLOSING_LINE}") if s.strip()}
    kept = [s for s in checks._SENT_SPLIT.split(text) if s.strip() and _norm(s) not in code]
    return " ".join(kept).strip(" -")


def compute_evidence(text: str, review, policies: list[dict]) -> list[str]:
    """근거: 늘 F_리뷰id. 고객센터 안내가 들어가면 그 내용을 담은 정책 id(예: P2)도."""
    ev = [f"F_{review.review_id}"]
    if "고객센터" in text:
        ev += [p["policy_id"] for p in policies if "고객센터" in p.get("text", "")][:1]
    return ev


def run_explain_checks(text: str, *, ai_part: str, review_text: str, menu_names, allowed_numbers, policies,
                       forbidden_phrases, evidence, valid_ids) -> dict:
    """EXPLAIN_CHECKS (c6.stance) 를 계산한다. text = 조립한 글 전체, ai_part = AI 가 쓴 공감 부분.
    정책·숫자·개인정보·길이·장담·금지 표현은 사과 답글과 같은 점검이다."""
    result = {
        "evidence_valid": bool(evidence) and all(e in valid_ids for e in evidence),
        "no_bad_promise": not checks.promises_not_in_policy(text, policies),
        "no_compensation_offer": not checks.offers_compensation(text),
        "no_fault_admission": not checks.admits_fault(text),
        "no_customer_blame": not checks.blames_customer(text),
        "has_regret": checks.has_regret(ai_part),
        "explains_principle": checks.explains_principle(text),
        "request_mentioned": checks.mentions_review_items(ai_part, review_text, menu_names),
        "haeyo_only": checks.haeyo_only(ai_part),
        "no_invented_measure": not checks.has_invented_measure(text, None),
        "no_bad_number": not checks.has_number_not_in(text, allowed_numbers),
        "no_personal_info": not checks.personal_info(text),
        "length_ok": checks.length_ok(text, 120, 260),
        "no_stiff_words": not checks.has_stiff_words(ai_part),
        "no_overpromise": not checks.has_overpromise(text),
        "uses_opening": True,
        "uses_closing": True,
    }
    if forbidden_phrases:
        result["no_forbidden_phrase"] = not checks.forbidden_phrase(text, forbidden_phrases)
    return result


def process_explain_review(review, decision: StanceDecision, *, card_id, store, menu_names, allowed_numbers,
                           policies, forbidden_phrases, opening, closing, valid_ids, key, model, log_raw=None):
    """리뷰 1개 → DraftOutput 1개 (stance="explain"). c6.reply._process_review 와 같은 (draft, won) 을 돌려준다."""
    system = build_system(store.name, menu_names, decision, review.text)
    user_line = f"[{review.review_id}] ★{review.rating if review.rating is not None else '?'} {review.text}"
    won = 0.0
    call_errors = 0

    def _call(messages):
        nonlocal won, call_errors
        resp = clova.call(key, system, messages, model=model, max_tokens=200, temperature=0.3)
        if resp.get("error"):   # 잠깐의 호출 한도 초과 등: 한 번만 잠시 뒤 다시 부른다
            time.sleep(RETRY_WAIT_S)
            resp = clova.call(key, system, messages, model=model, max_tokens=200, temperature=0.3)
        won += resp.get("won", 0)
        call_errors += bool(resp.get("error"))
        raw = resp.get("content", "")
        if log_raw:
            log_raw(raw, review.review_id)
        return raw, clean_ai_part(parsing.extract_body(raw), decision)   # JSON이든 평문이든 본문을 버리지 않는다

    def _check(ai_part_):
        text_ = assemble(opening, build_body(ai_part_, decision), closing)
        evidence_ = compute_evidence(text_, review, policies)
        chk_ = run_explain_checks(text_, ai_part=ai_part_, review_text=review.text, menu_names=menu_names,
                                  allowed_numbers=allowed_numbers, policies=policies,
                                  forbidden_phrases=forbidden_phrases, evidence=evidence_, valid_ids=valid_ids)
        failed_ = [k for k, v in chk_.items() if not v and k not in _RETRY_EXEMPT]
        return text_, evidence_, chk_, failed_

    raw, ai_part = _call([{"role": "user", "content": user_line}])
    text, evidence, chk, failed = _check(ai_part)
    rewrites = 0
    while failed and ai_part and rewrites < MAX_REWRITES:
        hints = checks.fix_hints(failed)
        raw2, ai_part2 = _call([{"role": "user", "content": user_line}, {"role": "assistant", "content": raw},
                                {"role": "user", "content": "수정 지시:\n" + "\n".join(f"- {h}" for h in hints)}])
        rewrites += 1
        if ai_part2:
            raw, ai_part = raw2, ai_part2
        text, evidence, chk, failed = _check(ai_part)

    # 딱딱한 표현이 남으면 AI 부분에만 사전대로 단어를 바꾼다 (추가 호출 없음, c6.reply 와 같음)
    if failed and not chk.get("no_stiff_words", True):
        ai_part = checks.fix_stiff_words(ai_part)
        text, evidence, chk, failed = _check(ai_part)

    needs = [EXPLAIN_NEEDS_INPUT]
    if failed:   # 그래도 걸리면(또는 호출 실패로 글이 없으면) AI 부분을 기본 문장으로 바꾸고, 바꿨다는 것을 사장님께 알린다
        needs.append(CALL_FAILED_NOTE if call_errors and not ai_part else FALLBACK_NOTE)
        ai_part = fallback_empathy(review.text, menu_names)
        text, evidence, chk, failed = _check(ai_part)

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
        needs_input=needs,
        model=model,
        data_origin=store.data_origin,
        stance=EXPLAIN,
        stance_reasons=list(decision.reasons),
    )
    return draft, won
