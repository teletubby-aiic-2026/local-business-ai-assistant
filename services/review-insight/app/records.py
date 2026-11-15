"""리뷰마다 붙는 새 기록(어디서 들어왔나·실제로 받은 시각·상태·답글)의 읽기·쓰기를 한 곳에 모은 곳.

왜 리뷰와 따로 두나
- 리뷰 자체(글·별점·작성 시각)는 파일이나 DB(reviews 표)에 저장된다. DB 표의 칸은 shared/storage 가 정해서
  이 모듈이 칸을 늘릴 수 없다. 그래서 새 기록은 DB 모드여도 이 파일에 둔다.
- 나중에 DB 표(handoff.md 'DB 에 저장할 항목')가 생기면 이 파일의 load·update·clear 세 함수만 바꿔 끼운다.

모양 (data/runtime/records_<가게>.json, 방문자는 data/runtime/visitors/<방문자>/records_<가게>.json)
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


def load(store_id: str, visitor_id: str | None = None) -> dict[str, dict]:
    """review_id → 기록. 없으면 {}."""
    try:
        data = json.loads(_file(store_id, visitor_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data.get("reviews") or {}


def update(store_id: str, visitor_id: str | None, review_id: str, fields: dict, event: dict | None = None) -> dict:
    """한 리뷰의 기록에 fields 를 덮어쓰고, event 가 있으면 history 에 더한다. 바뀐 기록을 돌려준다."""
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
    with _lock:
        try:
            _file(store_id, visitor_id).unlink()
        except FileNotFoundError:
            pass
