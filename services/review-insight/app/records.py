"""리뷰마다 붙는 새 기록(어디서 들어왔나·실제로 받은 시각·상태·답글)의 읽기·쓰기를 한 곳에 모은 곳.

왜 리뷰와 따로 두나
- 리뷰 자체(글·별점·작성 시각)는 파일이나 DB(reviews 표)에 저장된다. 합성(기본) 리뷰는 git 파일이라 reviews 표에 줄이 없는데,
  그 리뷰에도 방문자마다 '답글 달았음' 같은 기록이 붙는다. 그래서 기록은 (가게, 방문자, 리뷰 id) 로 따로 둔다.

저장 위치 (11/19)
- DB_HOST 가 있으면 PostgreSQL 의 review_records·review_status_events 표 (shared.storage 의 PgReviewRecords, 표 정의는 db/schema.sql,
  칸은 handoff.md 'DB 에 저장할 항목'). WAS 가 두 대여도 같은 기록을 본다. DB 에 닿지 못하면 StorageUnavailable (API 는 503).
- DB_HOST 가 없으면 예전 그대로 아래 파일. 예전 파일 기록을 DB 로 옮기는 일은 하지 않는다.
- 어느 쪽이든 load·update 가 돌려주는 dict 모양은 같다 (시험이 견준다). 이 세 함수 밖에서는 어디에 두는지 몰라도 된다.

모양 (파일: data/runtime/records_<가게>.json, 방문자는 data/runtime/visitors/<방문자>/records_<가게>.json)
{"reviews": {"rv_ongi_paste_001": {
    "source": "app",                         # paste | capture | app | memo (계약의 input_method 는 모두 "paste")
    "received_at": "2026-11-14T19:02:11+09:00",   # 실제로 받은 시각 (기한·새 리뷰 조회용). 작성 시각(created_at)과 다름
    "status": "replied", "status_at": "...",
    "reply": {"text": "...", "replied_at": "..."} | null,
    "history": [{"status": "replied", "at": "..."}]}}}
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from app import storage

_lock = threading.RLock()


def _file(store_id: str, visitor_id: str | None) -> Path:
    from app import service              # service 가 이 모듈을 쓰므로 여기서 늦게 가져온다 (시험이 RUNTIME 을 바꿈)
    service._dir(store_id)
    visitor = service.clean_visitor(visitor_id)
    if visitor == service.COMMON_VISITOR:
        return service.RUNTIME / f"records_{store_id}.json"
    path = service.RUNTIME / "visitors" / visitor / f"records_{store_id}.json"
    if not path.resolve().is_relative_to(service.RUNTIME.resolve()):
        raise ValueError("방문자 id 가 저장 폴더 밖을 가리킵니다")
    return path


def _db(store_id: str, visitor_id: str | None):
    """(DB 의 기록 저장소, 방문자 id) 또는 (None, None)=파일 방식. 방문자가 없으면 공용('common') 자리 (파일의 records_<가게>.json 과 같은 뜻)."""
    from app import service              # 늦게 가져온다 (_file 과 같은 까닭)
    db = storage.database()
    if db is None:
        return None, None
    service._dir(store_id)               # 모르는 가게면 여기서 오류 (파일 방식과 같은 자리)
    return db.review_records, service.clean_visitor(visitor_id)


def load(store_id: str, visitor_id: str | None = None) -> dict[str, dict]:
    """review_id → 기록. 없으면 {}."""
    table, visitor = _db(store_id, visitor_id)
    if table is not None:
        with storage.guarded():
            return table.load(store_id, visitor)
    try:
        data = json.loads(_file(store_id, visitor_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data.get("reviews") or {}


def update(store_id: str, visitor_id: str | None, review_id: str, fields: dict, event: dict | None = None) -> dict:
    """한 리뷰의 기록에 fields 를 덮어쓰고, event 가 있으면 history 에 더한다. 바뀐 기록을 돌려준다."""
    table, visitor = _db(store_id, visitor_id)
    if table is not None:
        with storage.guarded():
            return table.update(store_id, visitor, review_id, fields, event)
    with _lock:
        rows = load(store_id, visitor_id)
        row = dict(rows.get(review_id) or {})
        row.update(fields)
        if event:
            row["history"] = list(row.get("history") or []) + [event]
        rows[review_id] = row
        path = _file(store_id, visitor_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"reviews": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)
        return row


def clear(store_id: str, visitor_id: str | None = None) -> None:
    table, visitor = _db(store_id, visitor_id)
    if table is not None:
        with storage.guarded():
            table.clear(store_id, visitor)
        return
    with _lock:
        try:
            _file(store_id, visitor_id).unlink()
        except FileNotFoundError:
            pass
