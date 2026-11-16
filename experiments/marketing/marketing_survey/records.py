"""기록 저장(DB 전 단계) — 설문 결과·승인·쿠폰 결과·광고비 점검을 가게마다 파일 한 개에 한 줄씩 덧붙인다.

파일: data/marketing/records_{store_id}.json  (줄 1개 = JSON 1개, .gitignore 대상)
칸 이름은 나중에 DB 로 옮길 때 표 이름과 같게 맞춘다.

  marketing_sessions : feature, goal, answers, decision, result, parent_id, created_at
  coupon_runs        : menu_name, discount_krw, issued, used, avg_order_krw, period_start, period_end, created_at
                       (+ margin_pct: 본전 주문 수 계산에 쓰는 남는 비율. 표에 칸이 생기면 같이 옮긴다)

각 줄에는 "table"(위 표 이름)과 "id"가 붙는다. 승인 줄의 parent_id 는 그 승인의 바탕이 된 설문 결과 줄의 id.
실제 기록이 없는 가게는 data/marketing/demo_records_{store_id}.json(합성 데모)을 읽는다 — load_for_report().
기록은 보조 기능이라 쓰기에 실패해도(디스크 등) 화면 흐름을 막지 않는다 — 호출하는 쪽에서 OSError 를 삼킨다.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config

KST = timezone(timedelta(hours=9))
SESSIONS = "marketing_sessions"
COUPON_RUNS = "coupon_runs"
RECORDS_DIR_ENV = "MARKETING_RECORDS_DIR"  # 테스트가 임시 폴더로 돌릴 때 쓴다

_STORE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def records_dir() -> Path:
    override = os.environ.get(RECORDS_DIR_ENV)
    return Path(override) if override else config.DATA_DIR / "marketing"


def _check_store_id(store_id: str) -> str:
    if not _STORE_ID_RE.match(store_id or ""):
        raise ValueError("가게 id 형식이 올바르지 않아요.")
    return store_id


def records_path(store_id: str) -> Path:
    return records_dir() / f"records_{_check_store_id(store_id)}.json"


def demo_path(store_id: str) -> Path:
    # 데모는 저장소에 들어 있는 파일이라 테스트용 records_dir 덮어쓰기와 상관없이 늘 같은 자리다.
    return config.DATA_DIR / "marketing" / f"demo_records_{_check_store_id(store_id)}.json"


def _now_iso(now: datetime | None) -> str:
    return (now or datetime.now(KST)).astimezone(KST).isoformat(timespec="seconds")


def _append(store_id: str, row: dict) -> dict:
    path = records_path(store_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def append_session(store_id: str, feature: str, *, goal: str | None = None, answers: dict | None = None,
                   decision: str | None = None, result: dict | None = None, parent_id: str | None = None,
                   now: datetime | None = None) -> dict:
    """marketing_sessions 한 줄. 돌려주는 row["id"] 를 승인 줄의 parent_id 로 쓴다."""
    return _append(store_id, {
        "table": SESSIONS, "id": uuid.uuid4().hex, "store_id": store_id,
        "feature": feature, "goal": goal, "answers": answers or {}, "decision": decision,
        "result": result or {}, "parent_id": parent_id, "created_at": _now_iso(now),
    })


def append_coupon_run(store_id: str, *, menu_name: str | None, discount_krw: int, issued: int, used: int,
                      avg_order_krw: int, margin_pct: int | None = None, period_start: str | None = None,
                      period_end: str | None = None, now: datetime | None = None) -> dict:
    """coupon_runs 한 줄. 기간을 모르면 period_* 는 None(보고서는 created_at 으로 센다)."""
    return _append(store_id, {
        "table": COUPON_RUNS, "id": uuid.uuid4().hex, "store_id": store_id,
        "menu_name": menu_name, "discount_krw": int(discount_krw), "issued": int(issued), "used": int(used),
        "avg_order_krw": int(avg_order_krw), "margin_pct": margin_pct,
        "period_start": period_start, "period_end": period_end, "created_at": _now_iso(now),
    })


def _read_lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue  # 깨진 줄은 건너뛴다(없는 값을 만들지 않는다)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def load(store_id: str) -> list[dict]:
    """실제 기록(없으면 빈 목록)."""
    return _read_lines(records_path(store_id))


def load_demo(store_id: str) -> list[dict]:
    path = demo_path(store_id)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    rows = data.get("records") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def load_for_report(store_id: str) -> tuple[list[dict], bool]:
    """(기록, 데모 여부). 실제 기록이 한 줄이라도 있으면 그것만 쓰고 데모는 쓰지 않는다."""
    real = load(store_id)
    if real:
        return real, False
    return load_demo(store_id), True
