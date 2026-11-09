"""리뷰 답글 생성 — 사실 추출 → LLM 1회 호출 → 점검 → 다시 쓰기."""

import json
import re
import time

import config
import clova
from c6 import checks
from c6.measures import MEASURES, INVENTED_KW
from c6.style import owner_style

_RAW_LOG = config.RESULTS_DIR / "c6_reply_raw.txt"

_TASTE = re.compile(r"맛있|맛없|맛이|맛도|맛은|밋밋|짜|싱거|느끼|달|매워|매운|맵|쓴|텁텁")
_AMOUNT = re.compile(r"양이|양도|양은|많|적|푸짐|부족|넉넉|모자")

_LIST_KEY = re.compile(r"^(답글|replies|answers)$", re.I)
_ID_KEY = re.compile(r"^(review_id|리뷰ID|id)$", re.I)
_TEXT_KEY = re.compile(r"^(text|답글|reply)$", re.I)
_EVIDENCE_KEY = re.compile(r"^(근거|evidence|evidence_ids)$", re.I)


def _log_raw(text, call_idx):
    _RAW_LOG.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if call_idx == 1 else "a"
    with open(_RAW_LOG, mode, encoding="utf-8") as f:
        f.write(f"--- call {call_idx} ---\n{text}\n\n")


def _robust_parse(text):
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


_ALL_MEASURE_TEXTS = [m["text"] for m in MEASURES]


def _has_invented_measure(text, chosen_measures):
    if chosen_measures:
        chosen_texts = {m["text"] for m in chosen_measures}
        for kw in INVENTED_KW:
            if kw in text:
                if not any(ct for ct in chosen_texts if kw in ct):
                    return True
        for mt in _ALL_MEASURE_TEXTS:
            if mt in text and mt not in chosen_texts:
                return True
        return False
    for kw in INVENTED_KW:
        if kw in text:
            return True
    for mt in _ALL_MEASURE_TEXTS:
        if mt in text:
            return True
    return False


SYSTEM_TMPL = """\
당신은 {store_name} 사장님입니다. 아래 사실·정책을 바탕으로 리뷰 답글을 JSON으로 작성하세요.

## 말투
- 시작 인사: {opening}
- 마무리: {closing}
- 높임: {honorific}

## 규칙
1. 답글 순서: 사과 → 빠진 품목을 구체적으로 언급 → 확인·개선 약속(정책 범위 안에서만) → 감사
2. 120~220자
3. 리뷰마다 내용에 맞게 서로 다르게 쓸 것
4. 근거 ID는 아래 제공된 것만 사용
5. 메뉴판에 없는 가격·숫자를 넣지 말 것
6. 금전 보상(쿠폰·할인·무료 제공·증정 등)을 약속하지 말 것
7. 고객 개인정보(이름·전화번호·주소)를 쓰지 말 것
{measure_rule}

## 사실
{facts}

## 정책
{policies}
{measures_section}

## 출력 형식 (JSON만, 다른 텍스트 없이)
{{"답글":[{{"review_id":"R01","text":"답글 본문","근거":["F1","P1"]}}]}}
"""


def _extract_facts(reviews, menu_names):
    facts = []
    for rv in reviews:
        rid = rv["review_id"]
        txt = rv["text"]
        ordered = {m for m in menu_names if m in txt}
        missing = []
        for m in menu_names:
            if m not in txt and any(m != o and o in txt for o in ordered):
                pass
            neg = re.search(rf"{re.escape(m)}.{{0,8}}(안 왔|빠져|빠졌|누락|없|안 들어)", txt)
            if neg:
                missing.append(m)
        if not missing:
            for token in ("빠져", "빠졌", "안 왔", "누락", "없으면", "안 들어"):
                if token in txt:
                    missing_candidates = [m for m in menu_names if m not in txt]
                    if len(ordered) > 0 and missing_candidates:
                        pass
                    break
        fid = f"F{rid.replace('R', '', 1)}"
        parts = [f"{fid}.missing={','.join(missing) if missing else '없음'}"]
        parts.append(f"taste={'Y' if _TASTE.search(txt) else 'N'}")
        parts.append(f"amount={'Y' if _AMOUNT.search(txt) else 'N'}")
        facts.append(" / ".join(parts))
    return facts


def _build_messages(reviews):
    lines = []
    for rv in reviews:
        lines.append(f"[{rv['review_id']}] ★{rv['rating']} {rv['text']}")
    return [{"role": "user", "content": "\n".join(lines)}]


def _run_checks(reply, review_map, menu_names, policies, allowed_numbers,
                style_info, other_texts, chosen_measures=None):
    result = {}
    rid = reply.get("review_id", "")
    text = reply.get("text", "")
    evidence = reply.get("근거", [])

    result["review_id_match"] = rid in review_map
    valid_ids = set()
    for r in review_map:
        num = r.replace("R", "", 1)
        valid_ids.add(f"F{num}")
    valid_ids |= {p["policy_id"] for p in policies}
    if chosen_measures:
        valid_ids |= {m["id"] for m in chosen_measures}
    result["evidence_valid"] = all(e in valid_ids for e in evidence)
    result["no_invented_measure"] = not _has_invented_measure(text, chosen_measures)

    rv = review_map.get(rid, {})
    rv_text = rv.get("text", "")
    missing_items = []
    for m in menu_names:
        neg = re.search(rf"{re.escape(m)}.{{0,8}}(안 왔|빠져|빠졌|누락|없|안 들어)", rv_text)
        if neg:
            missing_items.append(m)
    if missing_items:
        result["missing_mentioned"] = any(m in text for m in missing_items)
    else:
        result["missing_mentioned"] = True

    result["no_bad_promise"] = not checks.promises_not_in_policy(text, policies)
    result["no_bad_number"] = not checks.has_number_not_in(text, allowed_numbers)
    result["no_personal_info"] = not checks.personal_info(text)
    result["length_ok"] = checks.length_ok(text, 120, 220)
    result["not_too_similar"] = all(not checks.too_similar(text, o) for o in other_texts)
    opening = style_info.get("시작 인사", "")
    if opening:
        tokens = opening.split()
        prefix = " ".join(tokens[:3]) if len(tokens) >= 3 else opening
        result["uses_opening"] = prefix != "" and prefix in text
    else:
        result["uses_opening"] = True
    result["uses_closing"] = style_info.get("마무리", "") in text if style_info.get("마무리") else True

    return result


def generate_replies(ctx, card, key, model="HCX-005", chosen_measures=None):
    store = ctx["store"]
    menu_names = [m["name"] for m in store["menu"]]
    allowed_numbers = [m["price"] for m in store["menu"]]
    policies = ctx["policies"]
    review_map = {r["review_id"]: r for r in ctx["reviews"]}
    target_reviews = [review_map[rid] for rid in card["review_ids"] if rid in review_map]
    style_info = owner_style(ctx.get("owner_replies", []))

    facts_lines = _extract_facts(target_reviews, menu_names)
    policy_lines = [f"{p['policy_id']}: {p['text']}" for p in policies]

    if chosen_measures:
        measure_rule = (
            "\n8. 개선 조치는 아래 '선택된 조치' 문장만 그대로 쓸 것. "
            "체크리스트·절차·도입·별도 용기 등 구체적 조치를 지어내지 말 것"
        )
        m_lines = [f"{m['id']}: {m['text']}" for m in chosen_measures]
        measures_section = "\n\n## 선택된 조치\n" + "\n".join(m_lines)
    else:
        measure_rule = (
            "\n8. 구체적 개선 조치(체크리스트·절차·도입·별도 용기 등)를 지어내지 말 것. "
            "\"더 꼼꼼히 확인하겠습니다\" 같은 일반적인 다짐만 쓸 것"
        )
        measures_section = ""

    system = SYSTEM_TMPL.format(
        store_name=store["name"],
        opening=style_info.get("시작 인사", "안녕하세요 고객님"),
        closing=style_info.get("마무리", "감사합니다"),
        honorific=style_info.get("높임", "해요체"),
        facts="\n".join(facts_lines),
        policies="\n".join(policy_lines),
        measure_rule=measure_rule,
        measures_section=measures_section,
    )

    target_ids = [rv["review_id"] for rv in target_reviews]
    start = time.time()
    total_won = 0.0
    total_calls = 0
    outputs = []
    parse_error = None

    def _call_and_parse(sys_prompt, msgs):
        nonlocal total_calls, total_won
        resp = clova.call(key, sys_prompt, msgs, model=model, max_tokens=1024)
        total_calls += 1
        total_won += resp.get("won", 0)
        raw = resp.get("content", "")
        _log_raw(raw, total_calls)
        return raw

    raw = _call_and_parse(system, _build_messages(target_reviews))
    data, err = _robust_parse(raw)
    if err:
        parse_error = err
    else:
        replies, err = _normalize_replies(data, target_ids)
        if err:
            parse_error = err

    if parse_error:
        retry_msg = _build_messages(target_reviews)
        retry_msg[0]["content"] += "\n\nJSON 형식으로만 답해 주세요. 설명 텍스트 없이 JSON만 출력하세요."
        raw = _call_and_parse(system, retry_msg)
        data, err = _robust_parse(raw)
        if err:
            parse_error = err
        else:
            replies, err = _normalize_replies(data, target_ids)
            if err:
                parse_error = err
            else:
                parse_error = None

    if parse_error:
        for rid in target_ids:
            outputs.append({
                "kind": "reply", "target_id": rid, "text": "",
                "evidence_ids": [], "checks": {},
                "rewrites": 0, "needs_input": [f"응답 JSON 파싱 실패: {parse_error}"],
            })
        elapsed = round(time.time() - start, 1)
        return {"outputs": outputs, "elapsed_s": elapsed, "won": total_won, "calls": total_calls}

    reply_by_id = {r.get("review_id"): r for r in replies}

    for _retry in range(2):
        all_texts = [r.get("text", "") for r in reply_by_id.values()]
        failed_ids = []
        for rid, rp in reply_by_id.items():
            others = [t for t in all_texts if t != rp.get("text", "")]
            chk = _run_checks(rp, review_map, menu_names, policies,
                              allowed_numbers, style_info, others, chosen_measures)
            rp["checks"] = chk
            rp["_pass"] = all(chk.values())
            if not rp["_pass"]:
                failed_names = [k for k, v in chk.items() if not v]
                rp["_failed"] = failed_names
                failed_ids.append(rid)

        if not failed_ids:
            break

        retry_reviews = [review_map[rid] for rid in failed_ids if rid in review_map]
        hints_parts = []
        for rid in failed_ids:
            rp = reply_by_id[rid]
            hints = checks.fix_hints(rp.get("_failed", []))
            hints_parts.append(f"[{rid}] " + " / ".join(hints))
        retry_msg = _build_messages(retry_reviews)
        retry_msg[0]["content"] += "\n\n수정 지시:\n" + "\n".join(hints_parts)

        raw2 = _call_and_parse(system, retry_msg)
        data2, _ = _robust_parse(raw2)
        if data2:
            reparsed, _ = _normalize_replies(data2, failed_ids)
            if reparsed:
                for rp2 in reparsed:
                    r2id = rp2.get("review_id")
                    if r2id in failed_ids:
                        prev_rewrites = reply_by_id.get(r2id, {}).get("rewrites", 0)
                        reply_by_id[r2id] = rp2
                        reply_by_id[r2id]["rewrites"] = prev_rewrites + 1

    for rid in target_ids:
        rp = reply_by_id.get(rid)
        if not rp:
            outputs.append({
                "kind": "reply", "target_id": rid, "text": "",
                "evidence_ids": [], "checks": {},
                "rewrites": 0, "needs_input": ["답글 생성 실패"],
            })
            continue
        all_texts = [r.get("text", "") for r in reply_by_id.values()]
        others = [t for t in all_texts if t != rp.get("text", "")]
        final_chk = _run_checks(rp, review_map, menu_names, policies,
                                allowed_numbers, style_info, others, chosen_measures)
        passed = all(final_chk.values())
        needs = []
        if not passed:
            needs = [k for k, v in final_chk.items() if not v]
        outputs.append({
            "kind": "reply",
            "target_id": rid,
            "text": rp.get("text", ""),
            "evidence_ids": rp.get("근거", []),
            "checks": final_chk,
            "rewrites": rp.get("rewrites", 0),
            "needs_input": needs,
        })

    elapsed = round(time.time() - start, 1)
    return {"outputs": outputs, "elapsed_s": elapsed, "won": total_won, "calls": total_calls}
