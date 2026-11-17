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
from .errors import StorageError
from .memory import check_period, clean_detail
from .times import to_date, to_datetime, to_kst_iso

log = logging.getLogger("shared.storage")
T = TypeVar("T")

TABLES = ("stores", "reviews", "review_labels", "approvals", "card_reasons", "reports")


class Database:
    """연결 풀 하나와 표별 저장소 (reviews, labels, approvals, card_reasons, reports)."""
    kind = "postgres"

    def __init__(self, config: DbConfig, *, app_name: str = ""):
        self.config = config
        self.app_name = app_name
        self._pool: ConnectionPool | None = None
        self._lock = threading.Lock()
        self._blocked_until = 0.0
        self.reviews = PgReviews(self)
        self.labels = PgLabels(self)
        self.approvals = PgApprovals(self)
        self.card_reasons = PgCardReasons(self)
        self.reports = PgReports(self)

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


# ── 승인 기록 ───────────────────────────────────────────────────────
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
