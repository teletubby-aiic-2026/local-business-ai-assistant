"""응대 받은함 · 문의 답변 초안(사실 확인) · 약속 장부.

받은함 (GET /inbox): 리뷰(합성·붙여넣기·캡처·가상 배달앱·매장 메모)와 손님 문의를 한 목록으로.
  항목마다 kind(review|inquiry) · intent(complaint·reservation·question·praise·other) · needs_owner(알레르기·위생·환불·직원)
  · 기한(due_at, 남은 시간). 응대 점수(/response)는 정해 둔 수식대로 **불만 리뷰만** 센다. 문의는 기한만 보여 주고 점수에 넣지 않는다.

답변 초안 (POST /inquiries/{id}/draft): 문의에 대한 사장님 답 초안.
  - 근거(facts)는 가게 정보에서 코드가 뽑는다. live 면 HCX-005 가 근거만으로 쓰고, 코드가 검사한다:
    ① 숫자(가격·시간·금액)는 근거에 있는 것만 ② 환불·보상·무료·할인은 정책에 있을 때만
    ③ 알레르기 문의에 "괜찮다·안 들어간다"고 단정하지 않고 "확인" 문장이 있어야 함 ④ 500자 이하
  - 검사를 못 넘거나 mock·키 없음이면 틀 문장 (method=template). 리뷰 답글은 비서 화면의 글 만들기(C6)가 맡아 여기서 만들지 않는다.

약속 장부 (GET /promises): 사장님 답글·답에 들어 있는 약속("포장할 때 한 번 더 확인하겠습니다")을 규칙으로 뽑아,
  리뷰 약속은 응대 점수의 재발(again)·재발 없음(fixed) 기록으로 상태를 정한다.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from app import inquiry, profile as prof, response, service
from app.inquiry import OWNER_FLAGS
from app.sources.chat import Chat, ChatError
from app.topics import topic_name

# ── 받은함 ────────────────────────────────────────────────────────
def _review_intent(c) -> str:
    if c is None:
        return "other"
    if c.negative_topics:
        return "complaint"
    return "praise" if c.sentiment == "positive" else "other"


def inbox(classifier, store_id: str, visitor_id: str | None, now: datetime, *, kind: str | None = None,
          intent: str | None = None, needs_owner: bool | None = None, open_only: bool = False,
          since: str | None = None, limit: int = 50) -> dict:
    if kind not in (None, "review", "inquiry"):
        raise ValueError("kind 는 review 또는 inquiry 입니다")
    if intent is not None and intent not in inquiry.INTENTS:
        raise ValueError(f"intent 는 {', '.join(inquiry.INTENTS)} 중 하나입니다")
    after = service.parse_time(since, "since") if since else None
    tl = service.Timeline(classifier, store_id, visitor_id)
    state = tl.at(now)
    pending = {p["review_id"]: p for p in state["pending"]}
    by_id = {c.review_id: c for c in tl.classes}
    p = prof.load(store_id, visitor_id)
    sla = p.reply.sla_minutes
    pol = response.Policy(sla_minutes=sla, peaks=tl.policy.peaks)
    items: list[dict] = []
    for row in tl.rows:
        c = by_id.get(row["review_id"])
        flags = inquiry.flags(row["text"])
        if c is not None and "hygiene" in c.negative_topics and "hygiene" not in flags:
            flags.append("hygiene")
        pend = pending.get(row["review_id"])
        closed = row["status"] in ("replied", "skipped")
        items.append({"item_id": row["review_id"], "kind": "review", "source": row["source"], "text": row["text"],
                      "rating": row["rating"], "channel": row.get("channel"), "intent": _review_intent(c),
                      "topics": (c.negative_topics if c else []), "topic_names": [topic_name(t) for t in (c.negative_topics if c else [])],
                      "needs_owner": flags, "received_at": row["received_at"], "created_at": row["created_at"],
                      "status": row["status"], "open": not closed and (c is not None and bool(c.negative_topics)),
                      "reply": row["reply"], "due_at": pend["due_at"] if pend else None,
                      "remaining_seconds": pend["remaining_seconds"] if pend else None,
                      "overdue": pend["overdue"] if pend else False, "data_origin": row.get("data_origin", "synthetic")})
    for q in inquiry.load(store_id, visitor_id):
        arrival = service.parse_time(q["received_at"])
        if arrival > now:
            continue
        open_ = q["status"] not in ("replied", "skipped")
        due = response.due_at(arrival, pol) if open_ else None
        remaining = int((due - now).total_seconds()) if due else None
        items.append({"item_id": q["item_id"], "kind": "inquiry", "source": q["source"], "text": q["text"], "rating": None,
                      "channel": None, "intent": q["intent"], "topics": [], "topic_names": [], "needs_owner": q["needs_owner"],
                      "received_at": q["received_at"], "created_at": q["received_at"], "status": q["status"], "open": open_,
                      "reply": q["reply"], "due_at": due.isoformat(timespec="seconds") if due else None,
                      "remaining_seconds": remaining, "overdue": bool(remaining is not None and remaining < 0),
                      "forward_reason": q.get("forward_reason"), "data_origin": q.get("data_origin", "synthetic")})
    all_items = items
    if kind:
        items = [x for x in items if x["kind"] == kind]
    if intent:
        items = [x for x in items if x["intent"] == intent]
    if needs_owner is not None:
        items = [x for x in items if bool(x["needs_owner"]) == needs_owner]
    if open_only:
        items = [x for x in items if x["open"]]
    if after is not None:
        items = [x for x in items if x["received_at"] and service.parse_time(x["received_at"]) > after]
    # 사장님 확인 필수(열림) → 기한 가까운 열린 것 → 나머지 최신순
    opens = sorted((x for x in items if x["open"]), key=lambda x: (0 if x["needs_owner"] else 1, x["due_at"] or "9999"))
    rest = sorted((x for x in items if not x["open"]), key=lambda x: x["received_at"] or x["created_at"], reverse=True)
    items = opens + rest
    opened = [x for x in all_items if x["open"]]
    summary = {"total": len(all_items), "open": len(opened),
               "needs_owner_open": sum(1 for x in opened if x["needs_owner"]),
               "overdue": sum(1 for x in opened if x["overdue"]),
               "by_kind": {k: sum(1 for x in all_items if x["kind"] == k) for k in ("review", "inquiry")},
               "open_by_intent": {i: sum(1 for x in opened if x["intent"] == i) for i in inquiry.INTENTS if any(x["intent"] == i for x in opened)},
               "auto_answered": sum(1 for x in all_items if x["kind"] == "inquiry" and (x["reply"] or {}).get("by") == "auto")}
    return {"items": items[:limit], "count": len(items), "summary": summary, "now": now.isoformat(timespec="seconds"),
            "server_time": datetime.now(service.KST).isoformat(timespec="seconds")}


# ── 답변 초안 ─────────────────────────────────────────────────────
_NUM = re.compile(r"\d[\d,]*(?::\d{2})?")
_PROMISE_WORDS = re.compile(r"환불|보상|무료|공짜|서비스로|할인|쿠폰|적립|배상")
_ALLERGY_SAFE = re.compile(r"괜찮|문제\s*없|안\s*들어|들어가지\s*않|없어요|없습니다|드셔도")


def _norm(text: str) -> str:
    return re.sub(r"[,\s]", "", text)


def check(draft: str, facts: list[str], needs_owner: list[str], sign_off: str | None) -> list[str]:
    """초안이 지켜야 할 것. 어긴 이유 목록 (빈 목록이면 통과)."""
    problems = []
    basis = _norm(" ".join(facts) + " " + (sign_off or ""))
    for n in _NUM.findall(draft):
        if _norm(n) not in basis:
            problems.append(f"근거에 없는 숫자: {n}")
    for w in set(_PROMISE_WORDS.findall(draft)):
        if w not in basis:
            problems.append(f"정책에 없는 약속: {w}")
    if "allergy" in needs_owner:
        if _ALLERGY_SAFE.search(draft):
            problems.append("알레르기를 단정함")
        if "확인" not in draft:
            problems.append("알레르기 문의에 확인 안내가 없음")
    if len(draft) > 500:
        problems.append("500자 초과")
    if not draft.strip():
        problems.append("빈 답")
    return problems


def template(item: dict, decision: dict, p: prof.Profile) -> str:
    polite = p.reply.tone == "polite"
    hello = "안녕하세요, 문의 주셔서 감사합니다." if polite else "안녕하세요! 문의 고마워요."
    later = "확인하고 다시 안내드릴게요." if polite else "확인하고 바로 알려 드릴게요."
    parts = [hello]
    owner = item.get("needs_owner") or []
    if "hygiene" in owner:
        parts.append("불편을 드려 정말 죄송합니다. 어떤 일이 있었는지 바로 확인하겠습니다.")
    if "staff" in owner:
        parts.append("응대로 불쾌하셨다니 죄송합니다. 어떤 상황이었는지 확인하겠습니다.")
    if "allergy" in owner:
        parts.append("알레르기는 들어가는 재료를 다시 확인하고 정확하게 안내드릴게요.")
    if "refund" in owner:
        parts.append("환불·보상 관련 내용은 확인한 뒤 안내드릴게요.")
    if not owner and decision["lines"]:
        parts.extend(decision["lines"])
    if decision["unknown"] or (not owner and not decision["lines"]):
        parts.append(later)
    if p.reply.sign_off:
        parts.append(p.reply.sign_off)
    return " ".join(dict.fromkeys(parts))


SYSTEM = """너는 동네 음식점 사장님을 대신해 손님 문의 답변 초안을 쓴다. 사장님이 읽고 고친 뒤 보낸다.
규칙:
1. [가게 정보]에 있는 사실만 쓴다. 없는 가격·시간·메뉴·재료를 지어내지 않는다. 모르는 것은 "확인하고 다시 안내드릴게요"라고 쓴다.
2. 환불·보상·무료·할인·쿠폰은 [가게 정보]에 그 정책이 있을 때만 말한다.
3. 알레르기 문의에는 "괜찮다", "안 들어간다"고 단정하지 않는다. 재료를 다시 확인해 안내하겠다고 쓴다.
4. 3~5문장, 500자 이하. 답변 글만 쓴다. 따옴표나 설명을 붙이지 않는다."""


def draft(store_id: str, visitor_id: str | None, item_id: str, now: datetime, chat: Chat | None = None) -> dict:
    items = inquiry.load(store_id, visitor_id)
    item = next((x for x in items if x["item_id"] == item_id), None)
    if item is None:
        raise LookupError(item_id)
    p = prof.load(store_id, visitor_id)
    decision = inquiry.decide(p, item["text"], now)
    facts = decision["facts"] + ([f"끝인사: {p.reply.sign_off}"] if p.reply.sign_off else [])
    fallback = template(item, decision, p)
    chat = chat or Chat()
    method, problems, text = "template", [], fallback
    if chat.available:
        tone = "존댓말, 정중하게" if p.reply.tone == "polite" else "존댓말, 친근하게"
        owner = ", ".join(OWNER_FLAGS[f] for f in item["needs_owner"]) or "없음"
        user = (f"[가게 정보]\n" + "\n".join(f"- {f}" for f in facts or ["(관련 정보 없음)"]) +
                f"\n\n[말투] {tone}\n[사장님 확인 필요] {owner}\n\n[손님 문의]\n{item['text']}")
        try:
            got = chat.ask(SYSTEM, user, "inquiry_draft").strip().strip('"')
            problems = check(got, facts, item["needs_owner"], p.reply.sign_off)
            if not problems:
                method, text = "hcx", got
        except ChatError as e:
            problems = [f"모델 호출 실패: {e}"]
    return {"item_id": item_id, "draft": text, "method": method, "demo": not chat.available,
            "facts": facts, "checks": problems, "needs_owner": item["needs_owner"],
            "note": "가게 정보에 있는 사실만 썼어요. 보내기 전에 읽고 고쳐 주세요"}


# ── 약속 장부 ─────────────────────────────────────────────────────
_SENT = re.compile(r"[^.!?\n]+[.!?]?")
_PROMISE = re.compile(r"(겠습니다|겠어요|할게요|드릴게요|볼게요|둘게요|하도록\s*하|챙길게요|바꿀게요)")
_ACTION = re.compile(r"확인|챙기|챙길|바꾸|바꿀|개선|신경|조심|넣어|다시|점검|교육|살피|꼼꼼|주의")


def promises_in(text: str) -> list[str]:
    out = []
    for s in _SENT.findall(text or ""):
        s = s.strip()
        if s and _PROMISE.search(s) and _ACTION.search(s) and not re.search(r"감사|죄송|드림$", s[-4:]):
            out.append(s)
    return out


def promises(classifier, store_id: str, visitor_id: str | None, now: datetime) -> dict:
    tl = service.Timeline(classifier, store_id, visitor_id)
    state = tl.at(now)
    again = [x for x in state["reasons"] if x["kind"] == "again"]
    fixed = {x["topic"]: x for x in state["reasons"] if x["kind"] == "fixed"}
    rows = []
    for row in tl.rows:
        reply = row.get("reply")
        if not reply:
            continue
        found = promises_in(reply["text"])
        if not found:
            continue
        topics = tl.negative.get(row["review_id"]) or []
        when = service.parse_time(reply["replied_at"])
        broke = [x for x in again if x.get("topic") in topics and service.parse_time(x["at"]) > when]
        kept = [fixed[t] for t in topics if t in fixed]
        if broke:
            st, msg = "broken", f"약속한 뒤 같은 불만이 {len(broke)}건 다시 들어왔어요"
        elif kept:
            st, msg = "kept", f"{tl.policy.fixed_days}일 동안 같은 불만이 없어요"
        else:
            left = (when + timedelta(days=tl.policy.fixed_days) - now).days
            st, msg = "watching", f"지켜보는 중 ({max(0, left)}일 남음)"
        rows.append({"item_id": row["review_id"], "kind": "review", "promises": found, "topics": topics,
                     "topic_names": [topic_name(t) for t in topics], "made_at": reply["replied_at"],
                     "state": st, "message": msg, "recurred": [x["review_id"] for x in broke]})
    for q in inquiry.load(store_id, visitor_id):
        reply = q.get("reply")
        if not reply or reply.get("by") != "owner":
            continue
        found = promises_in(reply["text"])
        if found:
            rows.append({"item_id": q["item_id"], "kind": "inquiry", "promises": found, "topics": [], "topic_names": [],
                         "made_at": reply["replied_at"], "state": "check", "message": "약속을 지켰는지 사장님이 확인해 주세요",
                         "recurred": []})
    rows.sort(key=lambda r: ({"broken": 0, "check": 1, "watching": 2, "kept": 3}[r["state"]], r["made_at"]))
    counts = {s: sum(1 for r in rows if r["state"] == s) for s in ("broken", "check", "watching", "kept")}
    return {"items": rows, "count": len(rows), "counts": counts, "now": now.isoformat(timespec="seconds")}
