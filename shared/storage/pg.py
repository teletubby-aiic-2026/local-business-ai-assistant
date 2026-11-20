"""PostgreSQL 구현. psycopg(3판)와 연결 풀(psycopg_pool).

이 파일은 psycopg 를 맨 위에서 가져온다. DB 설정이 없을 때는 이 파일을 아예 가져오지 않는다 (shared.storage.open_database).

연결이 끊겼을 때 (DB 장애 전환 등)
- 풀이 연결을 내줄 때마다 살아 있는지 확인하고, 죽은 연결은 버리고 새로 맺는다 (check_connection).
- 연결·풀 대기·질의에는 짧은 시간 제한이 있다 (DbConfig). 넘으면 StorageError 로 바뀌어 올라간다.
- 한 번 실패하면 retry_after 초 동안은 DB 를 부르지 않고 바로 StorageError 를 낸다. 장애 중에 요청마다 제한 시간을 기다리지 않게.
- 그 뒤 첫 요청이 새 연결을 맺는다. 서비스를 다시 켤 필요가 없다.

표 이름과 칸 이름이 SQL 로 나오는 곳은 이 파일과 db/schema.sql 뿐이다.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime
from typing import Callable, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .config import DbConfig
from .errors import DuplicateLogin, DuplicateStore, StorageError, StoreLimit
from .memory import (COUPON_RUNS, MARKETING_SESSIONS, REGISTERED, check_period, clean_detail, clean_marketing_row,
                     clean_store_profile, margin_value, with_visitor)
from .times import to_date, to_datetime, to_kst_iso

log = logging.getLogger("shared.storage")
T = TypeVar("T")

TABLES = ("stores", "reviews", "review_labels", "approvals", "card_reasons", "reports", "users", "user_stores", "auth_sessions",
          "marketing_sessions", "coupon_runs", "review_records", "review_status_events")


class Database:
    """연결 풀 하나와 표별 저장소 (reviews, labels, review_records, approvals, card_reasons, reports, users, auth_sessions, marketing)."""
    kind = "postgres"

    def __init__(self, config: DbConfig, *, app_name: str = ""):
        self.config = config
        self.app_name = app_name
        self._pool: ConnectionPool | None = None
        self._lock = threading.Lock()
        self._blocked_until = 0.0
        self.reviews = PgReviews(self)
        self.labels = PgLabels(self)
        self.review_records = PgReviewRecords(self)
        self.approvals = PgApprovals(self)
        self.card_reasons = PgCardReasons(self)
        self.reports = PgReports(self)
        self.users = PgUsers(self)
        self.auth_sessions = PgAuthSessions(self)
        self.registered_stores = PgRegisteredStores(self)
        self.marketing = PgMarketingRecords(self)

    def __repr__(self) -> str:   # 비밀번호는 넣지 않는다
        return f"Database({self.config.host}:{self.config.port}/{self.config.dbname})"

    # ── 연결 풀 ──
    def open(self) -> "Database":
        """풀을 만든다. DB 가 안 떠 있어도 기다리지 않는다 (백그라운드에서 계속 접속을 시도함)."""
        with self._lock:
            if self._pool is None:
                cfg = self.config
                pool = ConnectionPool(
                    conninfo="", kwargs={**cfg.connect_kwargs(self.app_name), "row_factory": dict_row},
                    min_size=1, max_size=cfg.pool_max, timeout=cfg.connect_timeout,
                    max_lifetime=1800, max_idle=300,
                    check=ConnectionPool.check_connection,        # 내줄 때 죽은 연결을 걸러 낸다
                    name=f"ic26-{self.app_name or 'db'}", open=False)
                pool.open(wait=False)
                self._pool = pool
        return self

    def close(self) -> None:
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.close()

    def run(self, work: Callable[[psycopg.Connection], T]) -> T:
        """연결 하나를 받아 work(conn) 을 한 트랜잭션으로 돌린다. 끝나면 커밋, 오류면 되돌린다."""
        if time.monotonic() < self._blocked_until:
            raise StorageError("DB 에 닿지 못한 직후라 잠시 건너뜁니다")
        pool = self._pool or self.open()._pool
        try:
            with pool.connection() as conn:
                result = work(conn)
        except psycopg.errors.UndefinedTable:
            raise StorageError("DB 에 표가 없습니다. python -m shared.storage.init_db 를 먼저 실행하세요") from None
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:   # 접속 실패, 풀 대기·질의 시간 초과, 끊김
            self._blocked_until = time.monotonic() + self.config.retry_after
            log.warning("DB 사용 실패 (%s): %s", exc.__class__.__name__, self.config.scrub(exc).strip()[:200])
            raise StorageError(f"DB 에 닿지 못했습니다 ({exc.__class__.__name__})") from None
        self._blocked_until = 0.0
        return result

    def ping(self) -> None:
        self.run(lambda conn: conn.execute("SELECT 1").fetchone())


def _kst(row: dict, *keys: str) -> dict:
    return {**row, **{k: to_kst_iso(row[k]) for k in keys if row.get(k) is not None}}


# ── 붙여넣은 리뷰 ───────────────────────────────────────────────────
class PgReviews:
    def __init__(self, db: Database):
        self._db = db

    def list(self, store_id: str, visitor_id: str) -> list[dict]:
        """붙여넣은 순서대로 Review 모양의 dict."""
        def work(conn):
            rows = conn.execute(
                "SELECT review_id, store_id, channel, rating, text, created_at, input_method, pii_masked, data_origin "
                "FROM reviews WHERE store_id = %s AND visitor_id = %s ORDER BY seq", (store_id, visitor_id)).fetchall()
            return [_kst(r, "created_at") for r in rows]
        return self._db.run(work)

    def add(self, store_id: str, visitor_id: str, build: Callable[[int], dict]) -> dict:
        """다음 번호 n 을 받아 build(n) 이 만든 리뷰 dict 를 넣는다. 서버가 여러 대여도 번호가 겹치지 않는다."""
        def work(conn):
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"reviews/{store_id}/{visitor_id}",))
            n = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM reviews WHERE store_id = %s AND visitor_id = %s",
                             (store_id, visitor_id)).fetchone()["n"]
            r = build(n)
            conn.execute(
                "INSERT INTO reviews (store_id, visitor_id, seq, review_id, channel, rating, text, created_at, input_method, "
                "pii_masked, data_origin) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (store_id, visitor_id, n, r["review_id"], r.get("channel"), r.get("rating"), r["text"],
                 to_datetime(r["created_at"]), r.get("input_method") or "paste", bool(r.get("pii_masked")),
                 r.get("data_origin") or "synthetic"))
            return r
        return self._db.run(work)

    def clear(self, store_id: str, visitor_id: str) -> int:
        def work(conn):
            return conn.execute("DELETE FROM reviews WHERE store_id = %s AND visitor_id = %s", (store_id, visitor_id)).rowcount
        return self._db.run(work)


# ── 붙여넣은 리뷰의 분류 결과 ────────────────────────────────────────
class PgLabels:
    def __init__(self, db: Database):
        self._db = db

    def get_many(self, keys: "list[str] | set[str]") -> dict[str, dict]:
        keys = sorted(set(keys))
        if not keys:
            return {}

        def work(conn):
            rows = conn.execute("SELECT label_key, result FROM review_labels WHERE label_key = ANY(%s)", (keys,)).fetchall()
            return {r["label_key"]: r["result"] for r in rows}
        return self._db.run(work)

    def put_many(self, items: dict[str, dict], *, prompt_version: str, model: str | None) -> None:
        if not items:
            return

        def work(conn):
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO review_labels (label_key, result, prompt_version, model) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (label_key) DO UPDATE SET result = EXCLUDED.result, prompt_version = EXCLUDED.prompt_version, "
                    "model = EXCLUDED.model, created_at = now()",
                    [(k, Jsonb(v), prompt_version, model) for k, v in items.items()])
        self._db.run(work)

    def delete_many(self, keys: "list[str] | set[str]") -> int:
        """그 키들의 분류 결과를 지운다 (계정 초기화·탈퇴, 11/19). 지운 개수. 없는 키는 건너뛴다."""
        keys = sorted(set(keys))
        if not keys:
            return 0

        def work(conn):
            return conn.execute("DELETE FROM review_labels WHERE label_key = ANY(%s)", (keys,)).rowcount
        return self._db.run(work)


# ── 승인 기록 ───────────────────────────────────────────────────────
# ── 리뷰의 상태·답글 기록 (11/19) ────────────────────────────────────────
class PgReviewRecords:
    """리뷰마다 붙는 기록 (리뷰 분석 서비스의 app/records.py 가 씀). 파일 방식(records_<가게>.json)과 같은 모양으로 읽고 쓴다:
    {"source", "received_at", "status", "status_at", "reply": {"text", "replied_at"}, "history": [{"status", "at"}]}
    값이 없는 칸은 dict 에 넣지 않는다 (파일에도 쓴 칸만 있다). 시각은 한국 시간 ISO 글자.
    메모리 구현은 없다: DB 가 없으면 리뷰 분석 서비스가 파일을 쓴다 (reviews·labels 와 같다)."""
    _COLUMNS = {"source": "source", "received_at": "received_at", "status": "status", "status_at": "status_at"}
    _TIMES = ("received_at", "status_at")

    def __init__(self, db: Database):
        self._db = db

    @staticmethod
    def _shape(row: dict, events: list[dict]) -> dict:
        out: dict = {}
        for key in ("source", "received_at", "status", "status_at"):
            if row.get(key) is not None:
                out[key] = to_kst_iso(row[key]) if key in PgReviewRecords._TIMES else row[key]
        if row.get("reply_text") is not None:
            out["reply"] = {"text": row["reply_text"],
                            "replied_at": to_kst_iso(row["replied_at"]) if row.get("replied_at") is not None else None}
        out.update(row.get("extra") or {})
        if events:
            out["history"] = [{"status": e["status"], "at": to_kst_iso(e["at"])} for e in events]
        return out

    def load(self, store_id: str, visitor_id: str) -> dict[str, dict]:
        """review_id → 기록. 없으면 {}."""
        def work(conn):
            rows = conn.execute(
                "SELECT review_id, source, received_at, status, status_at, reply_text, replied_at, extra FROM review_records "
                "WHERE store_id = %s AND visitor_id = %s ORDER BY review_id", (store_id, visitor_id)).fetchall()
            events: dict[str, list[dict]] = {}
            for e in conn.execute("SELECT review_id, status, at FROM review_status_events "
                                  "WHERE store_id = %s AND visitor_id = %s ORDER BY id", (store_id, visitor_id)).fetchall():
                events.setdefault(e["review_id"], []).append(e)
            return {r["review_id"]: self._shape(r, events.get(r["review_id"], [])) for r in rows}
        return self._db.run(work)

    def update(self, store_id: str, visitor_id: str, review_id: str, fields: dict, event: dict | None = None) -> dict:
        """한 리뷰의 기록에 fields 를 덮어쓰고(준 칸만), event 가 있으면 상태 기록에 더한다. 바뀐 기록을 돌려준다.
        한 트랜잭션이고 그 줄을 잠그므로, 서버 두 대가 같은 리뷰를 같이 고쳐도 서로의 값을 지우지 않는다."""
        sets, values, extra = [], [], {}
        for key, value in (fields or {}).items():
            if key in self._COLUMNS:
                sets.append(f"{self._COLUMNS[key]} = %s")
                values.append(to_datetime(value) if key in self._TIMES and value is not None else value)
            elif key == "reply":
                reply = value or {}
                sets += ["reply_text = %s", "replied_at = %s"]
                values += [reply.get("text"), to_datetime(reply["replied_at"]) if reply.get("replied_at") else None]
            elif key != "history":                     # history 는 event 로만 쌓는다
                extra[key] = value
        if extra:
            sets.append("extra = extra || %s")
            values.append(Jsonb(extra))

        def work(conn):
            key = (store_id, visitor_id, review_id)
            conn.execute("INSERT INTO review_records (store_id, visitor_id, review_id) VALUES (%s, %s, %s) "
                         "ON CONFLICT (store_id, visitor_id, review_id) DO NOTHING", key)
            conn.execute("SELECT 1 FROM review_records WHERE store_id = %s AND visitor_id = %s AND review_id = %s FOR UPDATE", key)
            if sets:
                conn.execute(f"UPDATE review_records SET {', '.join(sets)}, updated_at = now() "
                             "WHERE store_id = %s AND visitor_id = %s AND review_id = %s", (*values, *key))
            if event:
                conn.execute("INSERT INTO review_status_events (store_id, visitor_id, review_id, status, at) VALUES (%s, %s, %s, %s, %s)",
                             (*key, event["status"], to_datetime(event["at"])))
            row = conn.execute(
                "SELECT review_id, source, received_at, status, status_at, reply_text, replied_at, extra FROM review_records "
                "WHERE store_id = %s AND visitor_id = %s AND review_id = %s", key).fetchone()
            events = conn.execute("SELECT status, at FROM review_status_events "
                                  "WHERE store_id = %s AND visitor_id = %s AND review_id = %s ORDER BY id", key).fetchall()
            return self._shape(row, events)
        return self._db.run(work)

    def clear(self, store_id: str, visitor_id: str) -> int:
        """그 가게·그 방문자의 기록을 모두 지운다 (상태 기록은 CASCADE). 지운 리뷰 기록 수."""
        def work(conn):
            return conn.execute("DELETE FROM review_records WHERE store_id = %s AND visitor_id = %s", (store_id, visitor_id)).rowcount
        return self._db.run(work)


class PgApprovals:
    # 칸 4개(draft_text, checks, used_fallback, style)가 없는 옛 표(11/18 전에 만든 DB)에서 잠시 옛 방식으로 쓰는 시간(초)
    LEGACY_RETRY_SEC = 60.0

    def __init__(self, db: Database):
        self._db = db
        self._legacy_until = 0.0

    def save(self, store_id: str, visitor_id: str, entry: dict, *, card_id: str | None = None, kind: str | None = None,
             detail: dict | None = None) -> None:
        """detail: 초안 정보 {draft_text, checks, used_fallback, style} (이슈 #51 ERD, 11/18). 서버가 모르면 None.
        같은 초안을 다시 승인할 때 detail 이 None 이면 앞서 저장한 초안 정보를 그대로 둔다.
        표에 그 칸이 아직 없으면(init_db 를 다시 돌리기 전) 칸 없이 옛 방식으로 저장하고 경고를 남긴다."""
        base = (store_id, visitor_id, entry["draft_id"], card_id, kind, entry.get("status") or "approved",
                entry.get("text") or "", bool(entry.get("edited")), to_datetime(entry["approved_at"]), entry.get("mode") or "")
        known = detail is not None
        d = clean_detail(detail)

        def work(conn):
            conn.execute(
                "INSERT INTO approvals (store_id, visitor_id, draft_id, card_id, kind, status, approved_text, edited, approved_at, mode, "
                "draft_text, checks, used_fallback, style) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (store_id, visitor_id, draft_id) DO UPDATE SET "
                "card_id = COALESCE(EXCLUDED.card_id, approvals.card_id), kind = COALESCE(EXCLUDED.kind, approvals.kind), "
                "status = EXCLUDED.status, approved_text = EXCLUDED.approved_text, edited = EXCLUDED.edited, "
                "approved_at = EXCLUDED.approved_at, mode = EXCLUDED.mode, saved_at = now(), "
                "draft_text = COALESCE(EXCLUDED.draft_text, approvals.draft_text), "
                "checks = CASE WHEN %s THEN EXCLUDED.checks ELSE approvals.checks END, "
                "used_fallback = CASE WHEN %s THEN EXCLUDED.used_fallback ELSE approvals.used_fallback END, "
                "style = CASE WHEN %s THEN EXCLUDED.style ELSE approvals.style END",
                base + (d["draft_text"], Jsonb(d["checks"]), d["used_fallback"], d["style"], known, known, known))

        def legacy(conn):
            conn.execute(
                "INSERT INTO approvals (store_id, visitor_id, draft_id, card_id, kind, status, approved_text, edited, approved_at, mode) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (store_id, visitor_id, draft_id) DO UPDATE SET "
                "card_id = COALESCE(EXCLUDED.card_id, approvals.card_id), kind = COALESCE(EXCLUDED.kind, approvals.kind), "
                "status = EXCLUDED.status, approved_text = EXCLUDED.approved_text, edited = EXCLUDED.edited, "
                "approved_at = EXCLUDED.approved_at, mode = EXCLUDED.mode, saved_at = now()", base)

        if time.monotonic() < self._legacy_until:
            self._db.run(legacy)
            return
        try:
            self._db.run(work)
        except psycopg.errors.UndefinedColumn:
            log.warning("approvals 표에 초안 정보 칸이 없어 칸 없이 저장했어요. python -m shared.storage.init_db 를 다시 돌리세요")
            self._legacy_until = time.monotonic() + self.LEGACY_RETRY_SEC
            self._db.run(legacy)

    def details(self, store_id: str, visitor_id: str) -> list[dict]:
        """list() 에 카드·종류와 초안 정보(draft_text, checks, used_fallback, style)를 더한 것 (보고서·점검용, 화면 응답에는 쓰지 않음)."""
        def work(conn):
            rows = conn.execute(
                "SELECT draft_id, card_id, kind, status, edited, approved_text AS text, approved_at, mode, "
                "draft_text, checks, used_fallback, style FROM approvals "
                "WHERE store_id = %s AND visitor_id = %s ORDER BY saved_at, id", (store_id, visitor_id)).fetchall()
            return [_kst(r, "approved_at") for r in rows]
        return self._db.run(work)

    def list(self, store_id: str, visitor_id: str) -> list[dict]:
        """메모리 구현과 같은 모양 (draft_id, status, edited, text, approved_at, mode). 다시 승인한 것은 맨 뒤 (저장한 순서)."""
        def work(conn):
            rows = conn.execute(
                "SELECT draft_id, status, edited, approved_text AS text, approved_at, mode FROM approvals "
                "WHERE store_id = %s AND visitor_id = %s ORDER BY saved_at, id", (store_id, visitor_id)).fetchall()
            return [_kst(r, "approved_at") for r in rows]
        return self._db.run(work)

    def clear(self, store_id: str, visitor_id: str) -> int:
        """메모리 구현과 같다: 이 가게·이 방문자의 승인 기록만 지우고 지운 건수를 돌려준다."""
        def work(conn):
            return conn.execute("DELETE FROM approvals WHERE store_id = %s AND visitor_id = %s", (store_id, visitor_id)).rowcount
        return self._db.run(work)

    def delete(self, store_id: str, visitor_id: str, draft_ids) -> int:
        """메모리 구현과 같다: 이 가게·이 방문자의 승인 기록 가운데 draft_ids 의 것만 지우고 지운 건수를 돌려준다 (11/16)."""
        ids = sorted(set(draft_ids or ()))
        if not ids:
            return 0

        def work(conn):
            return conn.execute("DELETE FROM approvals WHERE store_id = %s AND visitor_id = %s AND draft_id = ANY(%s)",
                                (store_id, visitor_id, ids)).rowcount
        return self._db.run(work)


# ── 카드 추천 이유 ──────────────────────────────────────────────────
class PgCardReasons:
    def __init__(self, db: Database):
        self._db = db

    def get(self, store_id: str, card_id: str, evidence_key: str) -> dict | None:
        def work(conn):
            row = conn.execute(
                "SELECT reason_text, source, model, created_at FROM card_reasons "
                "WHERE store_id = %s AND card_id = %s AND evidence_key = %s", (store_id, card_id, evidence_key)).fetchone()
            return _kst(row, "created_at") if row else None
        return self._db.run(work)

    def put(self, store_id: str, card_id: str, evidence_key: str, *, reason_text: str, source: str, model: str | None) -> None:
        def work(conn):
            conn.execute(
                "INSERT INTO card_reasons (store_id, card_id, evidence_key, reason_text, source, model) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (store_id, card_id, evidence_key) DO UPDATE SET "
                "reason_text = EXCLUDED.reason_text, source = EXCLUDED.source, model = EXCLUDED.model, created_at = now()",
                (store_id, card_id, evidence_key, reason_text, source, model))
        self._db.run(work)


# ── 주간·월간 보고서 ────────────────────────────────────────────────
_REPORT_COLUMNS = "store_id, period_kind, period_start, period_end, numbers, body_text, evidence_ids, prompt_version, created_at"


def _report(row: dict) -> dict:
    out = _kst(row, "created_at")
    out["period_start"], out["period_end"] = row["period_start"].isoformat(), row["period_end"].isoformat()
    return out


class PgReports:
    def __init__(self, db: Database):
        self._db = db

    def save(self, store_id: str, period_kind: str, period_start: date | str, period_end: date | str, *, numbers: dict,
             body_text: str, evidence_ids: list[str], prompt_version: str, created_at: datetime | None = None) -> dict:
        start, end = to_date(period_start), to_date(period_end)
        check_period(period_kind, start, end)

        def work(conn):
            row = conn.execute(
                "INSERT INTO reports (store_id, period_kind, period_start, period_end, numbers, body_text, evidence_ids, "
                "prompt_version, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now())) "
                "ON CONFLICT (store_id, period_kind, period_start, period_end, prompt_version) DO UPDATE SET "
                "numbers = EXCLUDED.numbers, body_text = EXCLUDED.body_text, evidence_ids = EXCLUDED.evidence_ids, "
                "created_at = EXCLUDED.created_at "
                f"RETURNING {_REPORT_COLUMNS}",
                (store_id, period_kind, start, end, Jsonb(numbers), body_text, list(evidence_ids), prompt_version,
                 to_datetime(created_at) if created_at else None)).fetchone()
            return _report(row)
        return self._db.run(work)

    def get(self, store_id: str, period_kind: str, period_start: date | str, period_end: date | str) -> dict | None:
        """그 기간 보고서 중 가장 늦게 만든 것."""
        def work(conn):
            row = conn.execute(
                f"SELECT {_REPORT_COLUMNS} FROM reports WHERE store_id = %s AND period_kind = %s AND period_start = %s "
                "AND period_end = %s ORDER BY created_at DESC LIMIT 1",
                (store_id, period_kind, to_date(period_start), to_date(period_end))).fetchone()
            return _report(row) if row else None
        return self._db.run(work)

    def list(self, store_id: str, period_kind: str | None = None, limit: int = 20) -> list[dict]:
        """기간이 늦은 것부터, 같은 기간이면 늦게 만든 것부터."""
        def work(conn):
            rows = conn.execute(
                f"SELECT {_REPORT_COLUMNS} FROM reports WHERE store_id = %s AND (%s::text IS NULL OR period_kind = %s) "
                "ORDER BY period_start DESC, created_at DESC LIMIT %s", (store_id, period_kind, period_kind, limit)).fetchall()
            return [_report(r) for r in rows]
        return self._db.run(work)


# ── 로그인 (5차 회의 11/18) ──────────────────────────────────────────
_USER_COLUMNS = "user_id, login_id, display_name, created_at"


class PgUsers:
    """사장님 계정과 가진 가게. MemoryUsers 와 같은 이름·인자·돌려주는 모양."""

    def __init__(self, db: Database):
        self._db = db

    def create(self, user_id: str, login_id: str, password_hash: str, display_name: str, store_ids: list[str]) -> dict:
        def work(conn):
            try:
                row = conn.execute(
                    f"INSERT INTO users (user_id, login_id, password_hash, display_name) VALUES (%s, %s, %s, %s) "
                    f"RETURNING {_USER_COLUMNS}", (user_id, login_id.lower(), password_hash, display_name)).fetchone()
            except psycopg.errors.UniqueViolation:
                raise DuplicateLogin("이미 있는 아이디예요") from None
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO user_stores (user_id, store_id, position) VALUES (%s, %s, %s)",
                                [(user_id, s, i) for i, s in enumerate(store_ids)])
            return _kst(row, "created_at")
        return self._db.run(work)

    def ensure(self, user_id: str, login_id: str, password_hash: str, display_name: str, store_ids: list[str]) -> dict:
        """없으면 만들고 있으면 그대로 (가진 가게는 store_ids 로 맞춤). 시연 계정처럼 여러 서버가 동시에 불러도 안전하다.
        다른 계정이 이 로그인 아이디를 이미 쓰면 DuplicateLogin (처리 안 된 UniqueViolation 이 500 으로 새지 않게)."""
        def work(conn):
            # 대상 없는 ON CONFLICT: user_id 든 login_id 든 겹치면 넣지 않는다. 넣었는지는 아래 SELECT 로 본다
            conn.execute("INSERT INTO users (user_id, login_id, password_hash, display_name) VALUES (%s, %s, %s, %s) "
                         "ON CONFLICT DO NOTHING", (user_id, login_id.lower(), password_hash, display_name))
            row = conn.execute(f"SELECT {_USER_COLUMNS} FROM users WHERE user_id = %s", (user_id,)).fetchone()
            if row is None:
                raise DuplicateLogin("이미 있는 아이디예요")            # 트랜잭션은 되돌려진다
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO user_stores (user_id, store_id, position) VALUES (%s, %s, %s) "
                                "ON CONFLICT (user_id, store_id) DO UPDATE SET position = EXCLUDED.position",
                                [(user_id, s, i) for i, s in enumerate(store_ids)])
            return _kst(row, "created_at")
        return self._db.run(work)

    def by_login(self, login_id: str) -> dict | None:
        """비밀번호 해시까지 (로그인 확인용)."""
        def work(conn):
            row = conn.execute(f"SELECT {_USER_COLUMNS}, password_hash FROM users WHERE login_id = %s",
                               (login_id.lower(),)).fetchone()
            return _kst(row, "created_at") if row else None
        return self._db.run(work)

    def get(self, user_id: str) -> dict | None:
        def work(conn):
            row = conn.execute(f"SELECT {_USER_COLUMNS} FROM users WHERE user_id = %s", (user_id,)).fetchone()
            return _kst(row, "created_at") if row else None
        return self._db.run(work)

    def stores(self, user_id: str) -> list[str]:
        def work(conn):
            rows = conn.execute("SELECT store_id FROM user_stores WHERE user_id = %s ORDER BY position, store_id",
                                (user_id,)).fetchall()
            return [r["store_id"] for r in rows]
        return self._db.run(work)

    def delete(self, user_id: str) -> bool:
        """계정을 지운다 (회원 탈퇴, 11/19). user_stores·auth_sessions 는 CASCADE 로 같이 지워진다. 있었으면 True."""
        def work(conn):
            return conn.execute("DELETE FROM users WHERE user_id = %s", (user_id,)).rowcount > 0
        return self._db.run(work)

    # ── 사장님 프로필과 가게 목록 고치기 (6차 회의 11/20). MemoryUsers 와 같은 동작 ──
    def rename(self, user_id: str, display_name: str) -> dict | None:
        def work(conn):
            row = conn.execute(f"UPDATE users SET display_name = %s WHERE user_id = %s RETURNING {_USER_COLUMNS}",
                               (display_name, user_id)).fetchone()
            return _kst(row, "created_at") if row else None
        return self._db.run(work)

    def set_password(self, user_id: str, password_hash: str) -> bool:
        def work(conn):
            return conn.execute("UPDATE users SET password_hash = %s WHERE user_id = %s",
                                (password_hash, user_id)).rowcount > 0
        return self._db.run(work)

    def add_store(self, user_id: str, store_id: str) -> list[str]:
        """목록 맨 뒤에 붙인다 (이미 있으면 그대로). 바뀐 목록."""
        def work(conn):
            conn.execute("SELECT 1 FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
            conn.execute("INSERT INTO user_stores (user_id, store_id, position) "
                         "SELECT %s, %s, COALESCE(MAX(position), -1) + 1 FROM user_stores WHERE user_id = %s "
                         "ON CONFLICT (user_id, store_id) DO NOTHING", (user_id, store_id, user_id))
        self._db.run(work)
        return self.stores(user_id)

    def remove_store(self, user_id: str, store_id: str) -> bool:
        def work(conn):
            return conn.execute("DELETE FROM user_stores WHERE user_id = %s AND store_id = %s",
                                (user_id, store_id)).rowcount > 0
        return self._db.run(work)

    def reorder(self, user_id: str, store_ids: list[str]) -> bool:
        """가진 가게 전부를 새 순서로. 겹치는 id 가 있거나 가진 가게 집합과 다르면 바꾸지 않고 False."""
        ids = list(store_ids)

        def work(conn):
            conn.execute("SELECT 1 FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
            have = [r["store_id"] for r in conn.execute("SELECT store_id FROM user_stores WHERE user_id = %s",
                                                        (user_id,)).fetchall()]
            if len(set(ids)) != len(ids) or set(ids) != set(have):
                return False
            with conn.cursor() as cur:
                cur.executemany("UPDATE user_stores SET position = %s WHERE user_id = %s AND store_id = %s",
                                [(i, user_id, s) for i, s in enumerate(ids)])
            return True
        return self._db.run(work)


# ── 사장님이 직접 등록한 가게 (6차 회의 11/20) ──────────────────────────
_STORE_COLUMNS = "store_id, owner_user_id, name, business_type_name, profile, created_at, updated_at"


class PgRegisteredStores:
    """stores 표의 직접 등록한 가게 (data_origin 'registered'). MemoryRegisteredStores 와 같은 이름·인자·돌려주는 모양."""

    def __init__(self, db: Database):
        self._db = db

    def _run(self, work):
        """stores 표에 11/20 칸(owner_user_id·profile·updated_at)이 아직 없으면(init_db 를 다시 돌리기 전) 500 대신 StorageError."""
        try:
            return self._db.run(work)
        except psycopg.errors.UndefinedColumn:
            log.warning("stores 표에 등록 가게 칸이 없어요. python -m shared.storage.init_db 를 다시 돌리세요")
            raise StorageError("stores 표에 등록 가게 칸이 없습니다. python -m shared.storage.init_db 를 다시 실행하세요") from None

    def create(self, store_id: str, owner_user_id: str, name: str, business_type_name: str, profile: dict, *,
               limit: int) -> dict:
        """가게 행과 가게 목록(맨 뒤)을 한 트랜잭션으로. 사장님 줄을 잠가 두 서버가 동시에 등록해도 한도를 넘지 않는다."""
        clean = clean_store_profile(profile)

        def work(conn):
            if conn.execute("SELECT 1 FROM users WHERE user_id = %s FOR UPDATE", (owner_user_id,)).fetchone() is None:
                raise KeyError("없는 사장님이에요")
            have = conn.execute("SELECT COUNT(*) AS n, COALESCE(MAX(position), -1) AS last FROM user_stores WHERE user_id = %s",
                                (owner_user_id,)).fetchone()
            if have["n"] >= limit:
                raise StoreLimit("가게 목록이 가득 찼어요")
            try:
                row = conn.execute(
                    "INSERT INTO stores (store_id, owner_user_id, name, business_type_name, profile, data_origin) "
                    f"VALUES (%s, %s, %s, %s, %s, '{REGISTERED}') RETURNING {_STORE_COLUMNS}",
                    (store_id, owner_user_id, name, business_type_name, Jsonb(clean))).fetchone()
            except psycopg.errors.UniqueViolation:
                raise DuplicateStore("이미 있는 가게 id 예요") from None
            conn.execute("INSERT INTO user_stores (user_id, store_id, position) VALUES (%s, %s, %s)",
                         (owner_user_id, store_id, have["last"] + 1))
            return _kst(row, "created_at", "updated_at")
        return self._run(work)

    def get(self, store_id: str) -> dict | None:
        def work(conn):
            row = conn.execute(f"SELECT {_STORE_COLUMNS} FROM stores WHERE store_id = %s AND data_origin = '{REGISTERED}'",
                               (store_id,)).fetchone()
            return _kst(row, "created_at", "updated_at") if row else None
        return self._run(work)

    def get_many(self, store_ids) -> dict[str, dict]:
        ids = list(dict.fromkeys(store_ids))
        if not ids:
            return {}

        def work(conn):
            rows = conn.execute(f"SELECT {_STORE_COLUMNS} FROM stores WHERE store_id = ANY(%s) AND data_origin = '{REGISTERED}'",
                                (ids,)).fetchall()
            return {r["store_id"]: _kst(r, "created_at", "updated_at") for r in rows}
        return self._run(work)

    def update(self, store_id: str, *, name: str | None = None, business_type_name: str | None = None,
               profile: dict | None = None) -> dict | None:
        clean = Jsonb(clean_store_profile(profile)) if profile is not None else None

        def work(conn):
            row = conn.execute(
                "UPDATE stores SET name = COALESCE(%s, name), business_type_name = COALESCE(%s, business_type_name), "
                "profile = COALESCE(%s, profile), updated_at = now() "
                f"WHERE store_id = %s AND data_origin = '{REGISTERED}' RETURNING {_STORE_COLUMNS}",
                (name, business_type_name, clean, store_id)).fetchone()
            return _kst(row, "created_at", "updated_at") if row else None
        return self._run(work)

    def list_by_owner(self, owner_user_id: str) -> list[dict]:
        def work(conn):
            rows = conn.execute(f"SELECT {_STORE_COLUMNS} FROM stores WHERE owner_user_id = %s AND data_origin = '{REGISTERED}' "
                                "ORDER BY created_at, store_id", (owner_user_id,)).fetchall()
            return [_kst(r, "created_at", "updated_at") for r in rows]
        return self._run(work)

    def delete(self, store_id: str) -> bool:
        def work(conn):
            conn.execute("DELETE FROM user_stores WHERE store_id = %s", (store_id,))
            return conn.execute(f"DELETE FROM stores WHERE store_id = %s AND data_origin = '{REGISTERED}'",
                                (store_id,)).rowcount > 0
        return self._run(work)

    def delete_by_owner(self, owner_user_id: str) -> int:
        def work(conn):
            gone = [r["store_id"] for r in conn.execute(
                f"DELETE FROM stores WHERE owner_user_id = %s AND data_origin = '{REGISTERED}' RETURNING store_id",
                (owner_user_id,)).fetchall()]
            if gone:
                conn.execute("DELETE FROM user_stores WHERE store_id = ANY(%s)", (gone,))
            return len(gone)
        return self._run(work)


class PgAuthSessions:
    def __init__(self, db: Database):
        self._db = db

    def create(self, token_hash: str, user_id: str, active_store_id: str, expires_at: datetime) -> None:
        def work(conn):
            conn.execute("INSERT INTO auth_sessions (token_hash, user_id, active_store_id, expires_at) VALUES (%s, %s, %s, %s)",
                         (token_hash, user_id, active_store_id, to_datetime(expires_at)))
            # 오래된 세션을 가끔 치운다 (만들 때마다 지난 것만)
            conn.execute("DELETE FROM auth_sessions WHERE expires_at < now()")
        self._db.run(work)

    def get(self, token_hash: str) -> dict | None:
        """살아 있는 세션 {token_hash, user_id, active_store_id, created_at, expires_at}. 지났거나 없으면 None."""
        def work(conn):
            row = conn.execute("SELECT token_hash, user_id, active_store_id, created_at, expires_at FROM auth_sessions "
                               "WHERE token_hash = %s AND expires_at > now()", (token_hash,)).fetchone()
            return _kst(row, "created_at", "expires_at") if row else None
        return self._db.run(work)

    def delete_user(self, user_id: str) -> int:
        """그 사장님의 세션을 모두 지운다 (회원 탈퇴: 다른 기기의 로그인도 끊김, 11/19). 지운 개수 (지난 세션 포함)."""
        def work(conn):
            return conn.execute("DELETE FROM auth_sessions WHERE user_id = %s", (user_id,)).rowcount
        return self._db.run(work)

    def set_store(self, token_hash: str, store_id: str) -> bool:
        def work(conn):
            return conn.execute("UPDATE auth_sessions SET active_store_id = %s WHERE token_hash = %s AND expires_at > now()",
                                (store_id, token_hash)).rowcount > 0
        return self._db.run(work)

    def delete(self, token_hash: str) -> bool:
        def work(conn):
            return conn.execute("DELETE FROM auth_sessions WHERE token_hash = %s", (token_hash,)).rowcount > 0
        return self._db.run(work)


# ── 맞춤 마케팅 기록 (11/19, 이슈 #51 ERD §3.13) ───────────────────────
_SESSION_COLUMNS = "id, store_id, feature, goal, answers, decision, result, parent_id, created_at"
_COUPON_COLUMNS = ("id, store_id, menu_name, discount_krw, issued, used, avg_order_krw, margin_pct, period_start, period_end, "
                   "created_at")


def _marketing_row(table: str, row: dict) -> dict:
    """표의 한 행 → 파일 방식과 같은 모양의 dict (칸 순서도 같게)."""
    out = {"table": table, **{k: v for k, v in row.items() if k != "seq"}}
    out["created_at"] = to_kst_iso(row["created_at"])
    if table == COUPON_RUNS:
        out["margin_pct"] = margin_value(row["margin_pct"])
        for k in ("period_start", "period_end"):
            out[k] = row[k].isoformat() if row[k] is not None else None
    return out


class PgMarketingRecords:
    """MemoryMarketingRecords 와 같은 이름·인자·돌려주는 모양. 두 표가 같은 번호표(marketing_records_seq)를 써서
    두 표를 섞어 읽어도 넣은 순서 그대로다 (파일에 한 줄씩 덧붙이던 순서와 같음)."""

    def __init__(self, db: Database):
        self._db = db

    def _run(self, work):
        """표에 맞지 않는 값(범위 밖 숫자, NUL 글자, 같은 id)은 ValueError 로 바꾼다. 연결 문제는 run() 이 StorageError 로 바꾼다."""
        try:
            return self._db.run(work)
        except (psycopg.DataError, psycopg.IntegrityError) as exc:
            raise ValueError(f"마케팅 기록을 표에 넣지 못했습니다 ({exc.__class__.__name__})") from None

    def add(self, store_id: str, visitor_id: str, row: dict) -> dict:
        r = clean_marketing_row({**row, "store_id": store_id})

        def work(conn):
            if r["table"] == MARKETING_SESSIONS:
                conn.execute(
                    "INSERT INTO marketing_sessions (id, store_id, visitor_id, feature, goal, answers, decision, result, parent_id, "
                    "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (r["id"], store_id, visitor_id, r["feature"], r["goal"], Jsonb(r["answers"]), r["decision"],
                     Jsonb(r["result"]), r["parent_id"], to_datetime(r["created_at"])))
            else:
                conn.execute(
                    "INSERT INTO coupon_runs (id, store_id, visitor_id, menu_name, discount_krw, issued, used, avg_order_krw, "
                    "margin_pct, period_start, period_end, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (r["id"], store_id, visitor_id, r["menu_name"], r["discount_krw"], r["issued"], r["used"], r["avg_order_krw"],
                     r["margin_pct"], to_date(r["period_start"]) if r["period_start"] else None,
                     to_date(r["period_end"]) if r["period_end"] else None, to_datetime(r["created_at"])))
        self._run(work)
        return with_visitor(r, visitor_id)

    def list(self, store_id: str, visitor_id: str) -> list[dict]:
        """넣은 순서대로 (두 표가 섞여서). 이 가게·이 방문자의 것만."""
        def work(conn):
            where = "WHERE store_id = %s AND visitor_id = %s"
            s = conn.execute(f"SELECT seq, {_SESSION_COLUMNS} FROM marketing_sessions {where}", (store_id, visitor_id)).fetchall()
            c = conn.execute(f"SELECT seq, {_COUPON_COLUMNS} FROM coupon_runs {where}", (store_id, visitor_id)).fetchall()
            return sorted([(x["seq"], MARKETING_SESSIONS, x) for x in s] + [(x["seq"], COUPON_RUNS, x) for x in c],
                          key=lambda t: t[0])
        return [with_visitor(_marketing_row(table, row), visitor_id) for _, table, row in self._run(work)]

    def delete(self, store_id: str, visitor_id: str) -> int:
        """이 가게·이 방문자의 기록을 두 표에서 모두 지우고 지운 줄 수를 돌려준다."""
        def work(conn):
            args = (store_id, visitor_id)
            return (conn.execute("DELETE FROM marketing_sessions WHERE store_id = %s AND visitor_id = %s", args).rowcount
                    + conn.execute("DELETE FROM coupon_runs WHERE store_id = %s AND visitor_id = %s", args).rowcount)
        return self._run(work)
