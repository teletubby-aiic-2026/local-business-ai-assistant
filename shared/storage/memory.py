"""기본 구현: 서버 메모리. DB 설정이 없을 때 쓴다 (프로세스를 다시 켜면 사라진다).

PostgreSQL 구현(pg.py)과 이름·인자·돌려주는 모양이 같다. 승인 기록의 파일(approvals.jsonl) 덧붙이기는 지금처럼
services/web 의 Demo 가 한다 (경로가 웹 설정이라서).
"""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, timezone

from .errors import DuplicateLogin
from .times import now_kst, to_date, to_kst_iso


STYLES = ("haeyo", "hamnida", "mixed")     # 답글 말투 (c6.output._VALID_STYLES 와 같음)
MAX_DRAFT_TEXT = 4000
MAX_CHECKS = 40


def clean_detail(detail: dict | None) -> dict:
    """승인 기록의 초안 정보(이슈 #51 ERD, 11/18)를 표에 넣을 모양으로. 모르는 값은 비움·{}·False.
    draft_text: AI 가 쓴 원문 / checks: 점검 이름 → 통과 여부 / used_fallback: 점검 2번 실패로 코드 템플릿을 썼는지 /
    style: 답글 말투 haeyo·hamnida·mixed (답글이 아니면 None)."""
    d = detail if isinstance(detail, dict) else {}
    text = d.get("draft_text")
    raw = d.get("checks") if isinstance(d.get("checks"), dict) else {}
    checks = {str(k)[:60]: v for k, v in list(raw.items())[:MAX_CHECKS] if isinstance(v, bool) and k != "used_fallback"}
    style = d.get("style") if d.get("style") in STYLES else None
    return {"draft_text": text[:MAX_DRAFT_TEXT] if isinstance(text, str) else None, "checks": checks,
            "used_fallback": d.get("used_fallback") is True, "style": style}


class MemoryApprovals:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str], list[dict]] = {}
        self._meta: dict[tuple[str, str, str], dict] = {}     # (가게, 방문자, 초안) → 카드·종류·초안 정보 (list() 응답에는 넣지 않음)

    def save(self, store_id: str, visitor_id: str, entry: dict, *, card_id: str | None = None, kind: str | None = None,
             detail: dict | None = None) -> None:
        """같은 draft_id 는 마지막 것으로 바꾼다 (맨 뒤로 옮김). entry 는 복사하지 않고 그대로 쥔다.
        card_id·kind·detail 은 PostgreSQL 과 같은 규칙으로 따로 쥔다 (모르면 앞서 저장한 값을 둠). list() 의 모양은 그대로다."""
        with self._lock:
            rows = self._rows.setdefault((store_id, visitor_id), [])
            self._rows[(store_id, visitor_id)] = [r for r in rows if r["draft_id"] != entry["draft_id"]] + [entry]
            key = (store_id, visitor_id, entry["draft_id"])
            old = self._meta.get(key) or {"card_id": None, "kind": None, **clean_detail(None)}
            meta = {"card_id": card_id or old["card_id"], "kind": kind or old["kind"]}
            if detail is None:
                meta.update({k: old[k] for k in ("draft_text", "checks", "used_fallback", "style")})
            else:
                new = clean_detail(detail)
                meta.update(new, draft_text=new["draft_text"] if new["draft_text"] is not None else old["draft_text"])
            self._meta[key] = meta

    def list(self, store_id: str, visitor_id: str) -> list[dict]:
        with self._lock:
            return list(self._rows.get((store_id, visitor_id), []))

    def details(self, store_id: str, visitor_id: str) -> list[dict]:
        """list() 에 카드·종류와 초안 정보를 더한 것 (PostgreSQL 의 details 와 같은 칸)."""
        with self._lock:
            return [{"draft_id": r["draft_id"], "status": r.get("status"), "edited": r.get("edited"), "text": r.get("text"),
                     "approved_at": r.get("approved_at"), "mode": r.get("mode"),
                     **self._meta.get((store_id, visitor_id, r["draft_id"]), {})}
                    for r in self._rows.get((store_id, visitor_id), [])]

    def clear(self, store_id: str, visitor_id: str) -> int:
        """이 가게·이 방문자의 승인 기록을 모두 지우고 지운 건수를 돌려준다. 다른 방문자·다른 가게의 기록은 그대로다."""
        with self._lock:
            for key in [k for k in self._meta if k[:2] == (store_id, visitor_id)]:
                del self._meta[key]
            return len(self._rows.pop((store_id, visitor_id), []))

    def delete(self, store_id: str, visitor_id: str, draft_ids) -> int:
        """이 가게·이 방문자의 승인 기록 가운데 draft_ids 의 것만 지우고 지운 건수를 돌려준다 (다시 만들어 바뀐 옛 글, 11/16).
        없는 id 는 세지 않는다. 다른 방문자·다른 가게·다른 글의 기록은 그대로다."""
        wanted = set(draft_ids or ())
        with self._lock:
            rows = self._rows.get((store_id, visitor_id))
            if not rows or not wanted:
                return 0
            kept = [r for r in rows if r["draft_id"] not in wanted]
            self._rows[(store_id, visitor_id)] = kept
            for draft_id in wanted:
                self._meta.pop((store_id, visitor_id, draft_id), None)
            return len(rows) - len(kept)


class MemoryCardReasons:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str, str], dict] = {}

    def get(self, store_id: str, card_id: str, evidence_key: str) -> dict | None:
        with self._lock:
            row = self._rows.get((store_id, card_id, evidence_key))
            return dict(row) if row else None

    def put(self, store_id: str, card_id: str, evidence_key: str, *, reason_text: str, source: str, model: str | None) -> None:
        with self._lock:
            self._rows[(store_id, card_id, evidence_key)] = {
                "reason_text": reason_text, "source": source, "model": model, "created_at": now_kst()}


class MemoryReports:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: list[dict] = []

    def save(self, store_id: str, period_kind: str, period_start: date | str, period_end: date | str, *, numbers: dict,
             body_text: str, evidence_ids: list[str], prompt_version: str, created_at: datetime | None = None) -> dict:
        check_period(period_kind, to_date(period_start), to_date(period_end))
        row = {"store_id": store_id, "period_kind": period_kind, "period_start": to_date(period_start).isoformat(),
               "period_end": to_date(period_end).isoformat(), "numbers": dict(numbers), "body_text": body_text,
               "evidence_ids": list(evidence_ids), "prompt_version": prompt_version,
               "created_at": to_kst_iso(created_at) if created_at else now_kst()}
        with self._lock:   # 같은 (가게, 종류, 기간, 프롬프트 버전)은 덮어쓴다
            same = lambda r: all(r[k] == row[k] for k in ("store_id", "period_kind", "period_start", "period_end", "prompt_version"))
            self._rows = [r for r in self._rows if not same(r)] + [row]
        return dict(row)

    def get(self, store_id: str, period_kind: str, period_start: date | str, period_end: date | str) -> dict | None:
        """그 기간 보고서 중 가장 늦게 만든 것."""
        start, end = to_date(period_start).isoformat(), to_date(period_end).isoformat()
        with self._lock:
            found = [r for r in self._rows if (r["store_id"], r["period_kind"], r["period_start"], r["period_end"]) ==
                     (store_id, period_kind, start, end)]
        # 같은 초 안에 만든 것끼리는 나중에 저장한 것이 이긴다 (DB 는 마이크로초까지 비교)
        return dict(max(enumerate(found), key=lambda t: (t[1]["created_at"], t[0]))[1]) if found else None

    def list(self, store_id: str, period_kind: str | None = None, limit: int = 20) -> list[dict]:
        """기간이 늦은 것부터, 같은 기간이면 늦게 만든 것부터."""
        with self._lock:
            rows = [r for r in self._rows if r["store_id"] == store_id and (period_kind is None or r["period_kind"] == period_kind)]
        order = sorted(enumerate(rows), key=lambda t: (t[1]["period_start"], t[1]["created_at"], t[0]), reverse=True)
        return [dict(r) for _, r in order[:limit]]


def check_period(period_kind: str, start: date, end: date) -> None:
    """DB 의 CHECK 와 같은 검사. 두 구현이 같은 입력을 같게 거절한다."""
    if period_kind not in ("weekly", "monthly"):
        raise ValueError("period_kind 는 weekly 또는 monthly 여야 합니다")
    if end < start:
        raise ValueError("끝일이 시작일보다 빠릅니다")


class MemoryUsers:
    """사장님 계정과 가진 가게 (로그인, 5차 회의 11/18). PostgreSQL 의 users·user_stores 와 같은 동작."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._users: dict[str, dict] = {}        # user_id → {user_id, login_id, password_hash, display_name, created_at}
        self._stores: dict[str, list[str]] = {}

    @staticmethod
    def _public(row: dict) -> dict:
        return {k: row[k] for k in ("user_id", "login_id", "display_name", "created_at")}

    def create(self, user_id: str, login_id: str, password_hash: str, display_name: str, store_ids: list[str]) -> dict:
        login = login_id.lower()
        with self._lock:
            if user_id in self._users or any(u["login_id"] == login for u in self._users.values()):
                raise DuplicateLogin("이미 있는 아이디예요")
            row = {"user_id": user_id, "login_id": login, "password_hash": password_hash, "display_name": display_name,
                   "created_at": now_kst()}
            self._users[user_id] = row
            self._stores[user_id] = list(dict.fromkeys(store_ids))
            return self._public(row)

    def ensure(self, user_id: str, login_id: str, password_hash: str, display_name: str, store_ids: list[str]) -> dict:
        with self._lock:
            row = self._users.get(user_id)
            if row is None:
                if any(u["login_id"] == login_id.lower() for u in self._users.values()):
                    raise DuplicateLogin("이미 있는 아이디예요")      # 다른 계정이 이 아이디를 씀 (PgUsers 와 같게)
                row = {"user_id": user_id, "login_id": login_id.lower(), "password_hash": password_hash,
                       "display_name": display_name, "created_at": now_kst()}
                self._users[user_id] = row
            have = self._stores.setdefault(user_id, [])
            self._stores[user_id] = list(dict.fromkeys(list(store_ids) + [s for s in have if s not in store_ids]))
            return self._public(row)

    def by_login(self, login_id: str) -> dict | None:
        login = login_id.lower()
        with self._lock:
            row = next((u for u in self._users.values() if u["login_id"] == login), None)
            return {**self._public(row), "password_hash": row["password_hash"]} if row else None

    def get(self, user_id: str) -> dict | None:
        with self._lock:
            row = self._users.get(user_id)
            return self._public(row) if row else None

    def stores(self, user_id: str) -> list[str]:
        with self._lock:
            return list(self._stores.get(user_id, []))

    def delete(self, user_id: str) -> bool:
        """계정과 가진 가게 목록을 지운다 (회원 탈퇴, 11/19). 있었으면 True. 그 뒤 같은 아이디로 새로 가입할 수 있다.
        PostgreSQL 은 세션(auth_sessions)도 CASCADE 로 같이 지워지지만, 메모리는 세션이 따로라 auth_sessions.delete_user 를 같이 부른다."""
        with self._lock:
            self._stores.pop(user_id, None)
            return self._users.pop(user_id, None) is not None


class MemoryAuthSessions:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, dict] = {}

    def create(self, token_hash: str, user_id: str, active_store_id: str, expires_at: datetime) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._rows = {k: v for k, v in self._rows.items() if v["_expires"] > now}
            self._rows[token_hash] = {"token_hash": token_hash, "user_id": user_id, "active_store_id": active_store_id,
                                      "created_at": now_kst(), "expires_at": to_kst_iso(expires_at),
                                      "_expires": expires_at.astimezone(timezone.utc)}

    def get(self, token_hash: str) -> dict | None:
        with self._lock:
            row = self._rows.get(token_hash)
            if row is None:
                return None
            if row["_expires"] <= datetime.now(timezone.utc):
                del self._rows[token_hash]
                return None
            return {k: v for k, v in row.items() if not k.startswith("_")}

    def delete_user(self, user_id: str) -> int:
        """그 사장님의 세션을 모두 지운다 (회원 탈퇴: 다른 기기의 로그인도 끊김, 11/19). 지운 개수 (지난 세션 포함)."""
        with self._lock:
            gone = [k for k, v in self._rows.items() if v["user_id"] == user_id]
            for k in gone:
                del self._rows[k]
            return len(gone)

    def set_store(self, token_hash: str, store_id: str) -> bool:
        with self._lock:
            row = self._rows.get(token_hash)
            if row is None or row["_expires"] <= datetime.now(timezone.utc):
                return False
            row["active_store_id"] = store_id
            return True

    def delete(self, token_hash: str) -> bool:
        with self._lock:
            return self._rows.pop(token_hash, None) is not None


# ── 맞춤 마케팅 기록 (11/19, 이슈 #51 ERD §3.13) ───────────────────────
# experiments/marketing/marketing_survey/records.py 가 DB 설정이 있을 때 쓴다. 줄(row) 모양은 그 파일의 파일 방식과 같다.
MARKETING_SESSIONS = "marketing_sessions"
COUPON_RUNS = "coupon_runs"
MARKETING_TABLES = (MARKETING_SESSIONS, COUPON_RUNS)
_INT_MIN, _INT_MAX = -2**31, 2**31 - 1        # 표의 INTEGER 칸 범위. 두 구현이 같은 값을 같게 거절한다
_ID_MAX = 64


def _text(value, name: str, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value):
        raise ValueError(f"{name} 는 글자여야 합니다")
    return value


def _int(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not _INT_MIN <= value <= _INT_MAX:
        raise ValueError(f"{name} 는 INTEGER 범위의 정수여야 합니다")
    return value


def _json(value, name: str) -> dict:
    """JSONB 칸. 표에 넣었다 꺼낸 것과 같은 값(복사본)을 돌려준다. JSON 이 아닌 값은 ValueError."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{name} 는 JSON 객체여야 합니다")
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError):
        raise ValueError(f"{name} 를 JSON 으로 바꾸지 못했습니다") from None


def margin_value(value) -> int | float | None:
    """margin_pct (DOUBLE PRECISION). 정수 값은 int 로 돌려준다 (파일 방식에서 int 로 쓰던 값이 30.0 으로 바뀌지 않게)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("margin_pct 는 숫자여야 합니다")
    out = float(value)
    if out != out or out in (float("inf"), float("-inf")):
        raise ValueError("margin_pct 는 유한한 숫자여야 합니다")
    return int(out) if out.is_integer() else out


def clean_marketing_row(row: dict) -> dict:
    """records.py 가 만든 줄을 표에 넣을 모양으로 검사·정리한다 (모양이 틀리면 ValueError — 기록은 건너뛰고 화면은 그대로).
    돌려주는 dict 의 칸 순서는 파일 방식의 줄과 같다 ("visitor_id" 는 빼고. 방문자는 따로 받는다)."""
    if not isinstance(row, dict) or row.get("table") not in MARKETING_TABLES:
        raise ValueError("table 은 marketing_sessions 또는 coupon_runs 여야 합니다")
    rid, store = _text(row.get("id"), "id", required=True), _text(row.get("store_id"), "store_id", required=True)
    if len(rid) > _ID_MAX:
        raise ValueError("id 가 너무 깁니다")
    created = to_kst_iso(row["created_at"]) if row.get("created_at") else now_kst()
    if row["table"] == MARKETING_SESSIONS:
        return {"table": MARKETING_SESSIONS, "id": rid, "store_id": store,
                "feature": _text(row.get("feature"), "feature", required=True), "goal": _text(row.get("goal"), "goal"),
                "answers": _json(row.get("answers"), "answers"), "decision": _text(row.get("decision"), "decision"),
                "result": _json(row.get("result"), "result"), "parent_id": _text(row.get("parent_id"), "parent_id"),
                "created_at": created}
    period = {k: to_date(row[k]).isoformat() if row.get(k) is not None else None for k in ("period_start", "period_end")}
    if period["period_start"] and period["period_end"] and period["period_end"] < period["period_start"]:
        raise ValueError("끝일이 시작일보다 빠릅니다")
    return {"table": COUPON_RUNS, "id": rid, "store_id": store, "menu_name": _text(row.get("menu_name"), "menu_name"),
            **{k: _int(row.get(k), k) for k in ("discount_krw", "issued", "used", "avg_order_krw")},
            "margin_pct": margin_value(row.get("margin_pct")), **period, "created_at": created}


def with_visitor(row: dict, visitor_id: str) -> dict:
    """꺼낼 때: 방문자를 가린 기록이면 파일 방식처럼 "visitor_id" 칸을 붙인다 (공용 'common' 이면 붙이지 않음)."""
    from .visitor import COMMON_VISITOR
    return row if visitor_id == COMMON_VISITOR else {**row, "visitor_id": visitor_id}


class MemoryMarketingRecords:
    """맞춤 마케팅 기록 (marketing_sessions + coupon_runs). PgMarketingRecords 와 같은 이름·인자·돌려주는 모양.
    visitor_id 는 늘 값이 있다 (방문자를 안 가린 호출은 부르는 쪽이 'common' 으로 바꿔서 준다)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str], list[dict]] = {}
        self._ids: set[tuple[str, str]] = set()     # (표, id). PostgreSQL 처럼 표마다 id 가 유일하다

    def add(self, store_id: str, visitor_id: str, row: dict) -> dict:
        """한 줄 넣고 표에 들어간 모양(꺼낼 때와 같은 모양)을 돌려준다. 같은 표에 같은 id 가 이미 있으면 ValueError."""
        clean = clean_marketing_row({**row, "store_id": store_id})
        with self._lock:
            if (clean["table"], clean["id"]) in self._ids:
                raise ValueError("같은 id 의 기록이 이미 있습니다")
            self._ids.add((clean["table"], clean["id"]))
            self._rows.setdefault((store_id, visitor_id), []).append(clean)
        return with_visitor(dict(clean), visitor_id)

    def list(self, store_id: str, visitor_id: str) -> list[dict]:
        """넣은 순서대로 (두 표가 섞여서). 이 가게·이 방문자의 것만."""
        with self._lock:
            rows = list(self._rows.get((store_id, visitor_id), []))
        return [with_visitor(json.loads(json.dumps(r, ensure_ascii=False)), visitor_id) for r in rows]

    def delete(self, store_id: str, visitor_id: str) -> int:
        """이 가게·이 방문자의 기록을 두 표에서 모두 지우고 지운 줄 수를 돌려준다."""
        with self._lock:
            rows = self._rows.pop((store_id, visitor_id), [])
            self._ids.difference_update((r["table"], r["id"]) for r in rows)
            return len(rows)


class MemoryStore:
    """승인 기록·카드 이유·보고서·맞춤 마케팅 기록을 메모리에 둔다. (붙여넣은 리뷰와 분류 결과는 리뷰 분석 서비스가 자기 파일로 다룬다.)"""
    kind = "memory"

    def __init__(self) -> None:
        self.approvals = MemoryApprovals()
        self.card_reasons = MemoryCardReasons()
        self.reports = MemoryReports()
        self.users = MemoryUsers()
        self.auth_sessions = MemoryAuthSessions()
        self.marketing = MemoryMarketingRecords()

    def close(self) -> None:
        pass
