"""기본 구현: 서버 메모리. DB 설정이 없을 때 쓴다 (프로세스를 다시 켜면 사라진다).

PostgreSQL 구현(pg.py)과 이름·인자·돌려주는 모양이 같다. 승인 기록의 파일(approvals.jsonl) 덧붙이기는 지금처럼
services/web 의 Demo 가 한다 (경로가 웹 설정이라서).
"""
from __future__ import annotations

import threading
from datetime import date, datetime

from .times import now_kst, to_date, to_kst_iso


class MemoryApprovals:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str], list[dict]] = {}

    def save(self, store_id: str, visitor_id: str, entry: dict, *, card_id: str | None = None, kind: str | None = None) -> None:
        """같은 draft_id 는 마지막 것으로 바꾼다 (맨 뒤로 옮김). entry 는 복사하지 않고 그대로 쥔다."""
        with self._lock:
            rows = self._rows.setdefault((store_id, visitor_id), [])
            self._rows[(store_id, visitor_id)] = [r for r in rows if r["draft_id"] != entry["draft_id"]] + [entry]

    def list(self, store_id: str, visitor_id: str) -> list[dict]:
        with self._lock:
            return list(self._rows.get((store_id, visitor_id), []))

    def clear(self, store_id: str, visitor_id: str) -> int:
        """이 가게·이 방문자의 승인 기록을 모두 지우고 지운 건수를 돌려준다. 다른 방문자·다른 가게의 기록은 그대로다."""
        with self._lock:
            return len(self._rows.pop((store_id, visitor_id), []))


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


class MemoryStore:
    """승인 기록·카드 이유·보고서를 메모리에 둔다. (붙여넣은 리뷰와 분류 결과는 리뷰 분석 서비스가 자기 파일로 다룬다.)"""
    kind = "memory"

    def __init__(self) -> None:
        self.approvals = MemoryApprovals()
        self.card_reasons = MemoryCardReasons()
        self.reports = MemoryReports()

    def close(self) -> None:
        pass
