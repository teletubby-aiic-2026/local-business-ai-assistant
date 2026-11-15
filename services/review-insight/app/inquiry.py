"""손님 문의: 가게 정보로 바로 답할 것과 사장님에게 넘길 것을 나눈다. 규칙으로만 (모델 호출 없음).

흐름 (POST /api/review-insight/public/{가게}/inquiries — 손님용 문의 페이지가 부름)
1. 개인정보 가림 (리뷰와 같은 mask_pii)
2. 무엇을 묻나(types): 영업시간·휴무·브레이크·주차·위치·배달 지역·최소 주문·포장·단체·메뉴·가격·맵기·재료·반려동물·예약
3. 사장님이 꼭 봐야 하나(needs_owner): 알레르기 · 위생(이물질·배탈) · 환불·보상 · 직원 지목.
   이런 문의는 가게 정보에 답이 있어도 **자동으로 답하지 않고** 사장님에게 넘긴다 (AI 가 "괜찮아요"라고 하면 안 되는 것)
4. 의도(intent): complaint(불만) · reservation(예약 요청) · question(질문) · praise(칭찬) · other
5. 모든 질문에 가게 정보로 답할 수 있으면 → 바로 답 (status=replied, reply.by=auto). 하나라도 모르면 → 사장님 받은함 (status=new, 30분 기한)
   - 배운 답(가게 정보 answers)과 비슷한 질문이면 그 답을 쓴다

손님에게는 확인 번호(code)를 준다. 연락처를 받지 않는다 (개인정보를 모으지 않음). 손님은 같은 페이지에서 번호로 답을 확인한다.
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from app import profile as prof
from app.profile import CLOSED, DAY_NAMES, DAYS, Profile

_lock = threading.RLock()
INTENTS = ("complaint", "reservation", "question", "praise", "other")
OWNER_FLAGS = {"allergy": "알레르기", "hygiene": "위생", "refund": "환불·보상", "staff": "직원 응대"}

# ── 사장님이 꼭 봐야 하는 것 ──
_ALLERGY = re.compile(r"알레르기|알러지|아토피|못\s*먹|먹으면\s*안|글루텐|땅콩|견과|갑각류|새우|게살|조개|우유|유제품|달걀|계란.*빼|비건|채식|할랄|돼지고기.*(안|못|빼)")
_HYGIENE = re.compile(r"머리카락|벌레|이물질|비닐|플라스틱|철수세미|식중독|배탈|설사|토했|상한|쉰\s*냄새|곰팡")
_REFUND = re.compile(r"환불|보상|돈\s*돌려|취소해|결제\s*취소|배상|고소|신고")
_STAFF = re.compile(r"(직원|알바|사장|배달원|기사).{0,12}(불친절|반말|무시|태도|욕|화를|짜증|퉁명|소리)|(불친절|반말|태도).{0,6}(직원|알바|사장)")

# ── 무엇을 묻나 ──
_TYPES = [
    ("reservation", re.compile(r"예약|자리\s*맡|몇\s*명.*(가능|돼|되)|\d+\s*명")),
    ("group", re.compile(r"단체|\d+\s*인분|대량")),
    ("break", re.compile(r"브레이크|쉬는\s*시간")),
    ("last_order", re.compile(r"라스트\s*오더|주문\s*마감|마지막\s*주문")),
    ("holiday", re.compile(r"휴무|쉬는\s*날|쉬어요|쉬나요|정기\s*휴일|[월화수목금토일]요일.{0,6}(열|영업|하나|해요|해\?)")),
    ("hours", re.compile(r"영업\s*시간|몇\s*시|언제\s*(열|까지|문)|문\s*(열|닫)|오픈|마감|영업\s*(해|하|중)|열려\s*있|지금\s*(열|가면|영업)")),
    ("parking", re.compile(r"주차")),
    ("address", re.compile(r"주소|위치|어디(에|예요|인가|있)|찾아가|오시는\s*길")),
    ("delivery_area", re.compile(r"배달.{0,6}(돼|되|가능|지역|와요|오나)|배달\s*범위")),
    ("min_order", re.compile(r"최소\s*주문|최소\s*금액")),
    ("takeout", re.compile(r"포장.{0,4}(돼|되|가능|해\s*가)|테이크\s*아웃")),
    ("pets", re.compile(r"반려|강아지|애견|고양이|펫")),
    ("spicy", re.compile(r"맵|매워|매운|맵기|순한")),
    ("ingredients", re.compile(r"재료|뭐가\s*들어|들어가(나|요|는)|원산지")),
    ("price", re.compile(r"얼마|가격|몇\s*원")),
    ("menu", re.compile(r"메뉴|뭐\s*(팔|있)|추천")),
    ("remake", re.compile(r"다시\s*만들|재조리|바꿔\s*주")),
]
_PRAISE = re.compile(r"맛있|최고|감사|잘\s*먹었|또\s*올|또\s*시킬|친절|좋았|짱")


def flags(text: str) -> list[str]:
    out = []
    for name, pat in (("allergy", _ALLERGY), ("hygiene", _HYGIENE), ("refund", _REFUND), ("staff", _STAFF)):
        if pat.search(text):
            out.append(name)
    return out


def question_types(text: str) -> list[str]:
    found = [name for name, pat in _TYPES if pat.search(text)]
    if "holiday" in found and any(f"{d}요일" in text for d in DAY_NAMES.values()):
        found = [t for t in found if t != "hours"]          # "일요일에 영업하나요?" 는 그 요일만 답한다
    return found


def intent_of(text: str, types: list[str], owner: list[str], negative_topics: list[str]) -> str:
    if negative_topics or {"hygiene", "refund", "staff"} & set(owner):
        return "complaint"
    if "reservation" in types or "group" in types:
        return "reservation"
    if types or "?" in text or re.search(r"(나요|가요|까요|되나|돼요\?|있어요\?)\s*$", text.strip()):
        return "question"
    if _PRAISE.search(text):
        return "praise"
    return "other"


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"[^0-9A-Za-z가-힣]", "", text)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def learned(p: Profile, text: str, threshold: float = 0.5):
    """배운 답 중 가장 비슷한 질문. 두 글자 묶음이 2개 이상 겹치고, 짧은 쪽 기준 겹침 비율이 threshold 이상일 때만."""
    q = _bigrams(text)
    best, score = None, 0.0
    for a in p.answers:
        b = _bigrams(a.question)
        common = q & b
        if len(common) < 2:
            continue
        s = len(common) / min(len(q), len(b))
        if s > score:
            best, score = a, s
    return best if score >= threshold else None


def _won(n: int) -> str:
    return f"{n:,}원"


def _menu_hits(p: Profile, text: str):
    """문의에 나온 메뉴. 메뉴 이름의 낱말(2자 이상)이 있거나, 4자 이상 낱말의 앞 2자(제육볶음 → 제육)가 있으면."""
    t = text.replace(" ", "")
    hits = []
    for m in p.menu:
        words = [w for w in m.name.split() if len(w) >= 2]
        if m.name.replace(" ", "") in t or any(w in t for w in words) or any(len(w) >= 4 and w[:2] in t for w in words):
            hits.append(m)
    return hits


def answer(p: Profile, text: str, now: datetime) -> dict:
    """가게 정보로 답할 수 있는 줄만 만든다. 답할 수 없는 질문 유형은 unknown 에 넣는다."""
    types = question_types(text)
    lines: list[str] = []
    unknown: list[str] = []
    facts: list[str] = []
    today = now.date()
    hours_today, notices = prof.hours_on(p, today)
    for n in notices:
        facts.append(f"공지: {n.text} ({n.start}~{n.end})")
    sold = {n.menu for n in notices if n.kind == "sold_out"} | {m.name for m in p.menu if m.sold_out}
    hits = _menu_hits(p, text)
    if not hits and len(types) > 1:      # "최소 주문 얼마예요?" 의 '얼마'처럼 메뉴 없이 붙은 가격·맵기 말은 무시
        types = [t for t in types if t not in ("price", "spicy", "ingredients")] or types
    b, o, pol = p.basic, p.order, p.policy

    def say(line: str | None, kind: str):
        if line:
            lines.append(line)
            facts.append(line)
        else:
            unknown.append(kind)

    for kind in types:
        if kind == "hours":
            if hours_today == CLOSED:
                say(f"오늘({DAY_NAMES[DAYS[today.weekday()]]})은 쉬는 날이에요." + (f" {notices[0].text}" if notices else ""), kind)
            else:
                say(f"오늘 영업시간은 {hours_today}예요." if hours_today else None, kind)
                if hours_today and b.last_order:
                    lines.append(f"마지막 주문은 {b.last_order}까지예요.")
        elif kind == "holiday":
            day = next((d for d, name in DAY_NAMES.items() if f"{name}요일" in text), None)
            if day:
                h = p.basic.hours.get(day)
                say(None if h is None else (f"{DAY_NAMES[day]}요일은 쉬어요." if h == CLOSED else f"{DAY_NAMES[day]}요일은 {h}에 영업해요."), kind)
            else:
                say(f"쉬는 날은 {b.holidays}이에요." if b.holidays else None, kind)
        elif kind == "break":
            say(f"브레이크타임은 {b.break_time}이에요." if b.break_time else ("브레이크타임 없이 영업해요." if b.hours else None), kind)
        elif kind == "last_order":
            say(f"마지막 주문은 {b.last_order}까지예요." if b.last_order else None, kind)
        elif kind == "parking":
            say(f"주차: {b.parking}" if b.parking else None, kind)
        elif kind == "address":
            say(f"위치: {b.address}" if b.address else None, kind)
        elif kind == "delivery_area":
            say(f"배달 지역은 {o.delivery_area}예요." if o.delivery_area else None, kind)
        elif kind == "min_order":
            say(f"최소 주문 금액은 {_won(o.min_order)}이에요." if o.min_order is not None else None, kind)
        elif kind == "takeout":
            say(None if o.takeout is None else ("포장 주문 가능해요." if o.takeout else "포장은 하지 않아요."), kind)
        elif kind == "group":
            say(o.group_order, kind)
        elif kind == "pets":
            say(pol.pets, kind)
        elif kind == "remake":
            say(pol.remake, kind)
        elif kind == "reservation":
            unknown.append(kind)          # 예약은 날짜·인원을 사장님이 확인해야 함 → 늘 넘긴다
            if pol.reservation:
                lines.append(pol.reservation)
                facts.append(pol.reservation)
        elif kind in ("price", "spicy", "ingredients"):
            if not hits:
                unknown.append(kind)
                continue
            for m in hits:
                if kind == "price":
                    say(f"{m.name}은 {_won(m.price)}이에요." if m.price is not None else None, kind)
                elif kind == "spicy":
                    level = ("안 매워요", "조금 매워요", "보통 매워요", "많이 매워요")[m.spicy]
                    say(f"{m.name}은 {level}.", kind)
                else:
                    say(f"{m.name}에는 {', '.join(m.ingredients)}이(가) 들어가요." if m.ingredients else None, kind)
        elif kind == "menu":
            if p.menu:
                rec = [m.name for m in p.menu if m.recommended]
                names = ", ".join(f"{m.name}({_won(m.price)})" if m.price is not None else m.name for m in p.menu[:8])
                say(f"메뉴: {names}." + (f" 추천은 {', '.join(rec)}예요." if rec else ""), kind)
            else:
                unknown.append(kind)
    for m in hits:
        if m.name in sold:
            lines.append(f"{m.name}은 오늘 품절이에요.")
            facts.append(f"{m.name} 오늘 품절")
    if hits:
        for m in hits:
            facts.append(f"메뉴 {m.name}: 가격 {_won(m.price) if m.price is not None else '모름'}, 맵기 {m.spicy}/3, "
                         f"재료 {', '.join(m.ingredients) or '모름'}, 등록된 알레르기 재료 {', '.join(m.allergens) or '없음(미등록일 수 있음)'}")
    if pol.refund:
        facts.append(f"환불 기준: {pol.refund}")
    if pol.remake and "remake" not in types:
        facts.append(f"다시 만들어 주는 기준: {pol.remake}")
    return {"types": types, "lines": list(dict.fromkeys(lines)), "unknown": unknown, "facts": list(dict.fromkeys(facts))}


def decide(p: Profile, text: str, now: datetime, negative_topics: list[str] | None = None) -> dict:
    """문의 한 건을 나눈다. auto_answer 가 있으면 바로 답, 없으면 사장님에게."""
    owner = flags(text)
    if negative_topics and "hygiene" in negative_topics and "hygiene" not in owner:
        owner.append("hygiene")
    got = answer(p, text, now)
    intent = intent_of(text, got["types"], owner, negative_topics or [])
    learned_hit = None if owner else learned(p, text)
    auto = None
    if not owner and intent in ("question",):
        if got["types"] and not got["unknown"]:
            auto = " ".join(got["lines"])
        elif learned_hit is not None and (not got["types"] or got["unknown"]):
            auto = learned_hit.answer
    reason = ("사장님이 직접 확인해야 하는 문의예요: " + ", ".join(OWNER_FLAGS[f] for f in owner)) if owner else \
             ("예약은 날짜·인원을 사장님이 확인해요" if intent == "reservation" else
              ("불만은 사장님이 직접 답해요" if intent == "complaint" else
               (None if auto else "가게 정보에 없는 질문이라 사장님에게 전달했어요")))
    return {"intent": intent, "needs_owner": owner, "types": got["types"], "unknown": got["unknown"],
            "lines": got["lines"], "facts": got["facts"], "auto_answer": auto,
            "learned_id": learned_hit.id if (auto and learned_hit is not None and auto == learned_hit.answer) else None,
            "forward_reason": reason}


# ── 저장 (records.py 와 같은 방식, DB 로 바꿀 때는 load·_save 만) ──
def _file(store_id: str, visitor_id: str | None = None) -> Path:
    """손님 문의는 **가게 공용** 받은함 하나다 (visitor_id 는 받지만 쓰지 않음).
    손님은 사장님 화면의 방문자 쿠키가 없으므로, 방문자별로 나누면 사장님 받은함에 보이지 않는다 (11/15 통합 시뮬레이션에서 확인)."""
    from app import service
    service._dir(store_id)
    return service.RUNTIME / f"inquiries_{store_id}.json"


def load(store_id: str, visitor_id: str | None = None) -> list[dict]:
    try:
        return json.loads(_file(store_id, visitor_id).read_text(encoding="utf-8")).get("items") or []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(store_id: str, visitor_id: str | None, items: list[dict]) -> None:
    path = _file(store_id, visitor_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def clear(store_id: str, visitor_id: str | None = None) -> int:
    with _lock:
        n = len(load(store_id, visitor_id))
        try:
            _file(store_id, visitor_id).unlink()
        except FileNotFoundError:
            pass
    return n


def add(store_id: str, visitor_id: str | None, text: str, now: datetime, decision: dict, masked: bool) -> dict:
    from app import service
    short = store_id.removeprefix("store_")
    stamp = now.isoformat(timespec="seconds")
    with _lock:
        items = load(store_id, visitor_id)
        n = max([int(x["item_id"].rsplit("_", 1)[-1]) for x in items] or [0]) + 1
        item = {"item_id": f"iq_{short}_{n:03d}", "kind": "inquiry", "store_id": store_id, "source": "page",
                "text": text, "pii_masked": masked, "received_at": stamp, "data_origin": "synthetic",
                "intent": decision["intent"], "needs_owner": decision["needs_owner"], "types": decision["types"],
                "unknown": decision["unknown"], "facts": decision["facts"], "forward_reason": decision["forward_reason"],
                "code": secrets.token_urlsafe(6)[:8], "status": "new", "reply": None, "history": []}
        if decision["auto_answer"]:
            item["status"] = "replied"
            item["reply"] = {"text": decision["auto_answer"], "replied_at": stamp, "by": "auto",
                             "learned_id": decision.get("learned_id")}
            item["history"].append({"status": "replied", "at": stamp, "by": "auto"})
        items.append(item)
        _save(store_id, visitor_id, items)
    _ = service
    return item


def set_status(store_id: str, visitor_id: str | None, item_id: str, status: str, reply_text: str | None,
               at: datetime) -> dict:
    stamp = at.isoformat(timespec="seconds")
    with _lock:
        items = load(store_id, visitor_id)
        item = next((x for x in items if x["item_id"] == item_id), None)
        if item is None:
            raise LookupError(item_id)
        item["status"] = status
        item["status_at"] = stamp
        if reply_text is not None:
            item["reply"] = {"text": reply_text, "replied_at": stamp, "by": "owner"}
        item["history"] = list(item.get("history") or []) + [{"status": status, "at": stamp, "by": "owner"}]
        _save(store_id, visitor_id, items)
    return item


def public_view(item: dict) -> dict:
    """손님에게 보여 주는 모양: 글·상태·답만 (내부 판단·근거는 빼고)."""
    reply = item.get("reply")
    return {"code": item["code"], "text": item["text"], "received_at": item["received_at"],
            "status": "answered" if reply else ("closed" if item["status"] == "skipped" else "waiting"),
            "answer": reply["text"] if reply else None, "answered_at": reply["replied_at"] if reply else None,
            "answered_by": ("가게 안내" if reply["by"] == "auto" else "사장님") if reply else None}


# ── 공개 API 횟수 제한 (메모리, 서버 1대 기준) ──
class RateLimit:
    def __init__(self, per_client: int = 10, per_store: int = 60, window: float = 60.0):
        self.per_client, self.per_store, self.window = per_client, per_store, window
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, client: str, store_id: str) -> bool:
        now = time.monotonic()
        with self._lock:
            for key, limit in ((f"c:{client}", self.per_client), (f"s:{store_id}", self.per_store)):
                q = self._hits.setdefault(key, deque())
                while q and now - q[0] > self.window:
                    q.popleft()
                if len(q) >= limit:
                    return False
            for key in (f"c:{client}", f"s:{store_id}"):
                self._hits[key].append(now)
        return True
