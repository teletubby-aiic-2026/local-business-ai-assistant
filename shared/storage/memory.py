"""기본 구현: 서버 메모리. DB 설정이 없을 때 쓴다 (프로세스를 다시 켜면 사라진다).

PostgreSQL 구현(pg.py)과 이름·인자·돌려주는 모양이 같다. 승인 기록의 파일(approvals.jsonl) 덧붙이기는 지금처럼
services/web 의 Demo 가 한다 (경로가 웹 설정이라서).
"""
from __future__ import annotations

import threading
from datetime import date, datetime

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


class MemoryStore:
    """승인 기록·카드 이유·보고서를 메모리에 둔다. (붙여넣은 리뷰와 분류 결과는 리뷰 분석 서비스가 자기 파일로 다룬다.)"""
    kind = "memory"

    def __init__(self) -> None:
        self.approvals = MemoryApprovals()
        self.card_reasons = MemoryCardReasons()
        self.reports = MemoryReports()

    def close(self) -> None:
        pass
