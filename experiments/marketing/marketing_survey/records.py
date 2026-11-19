"""기록 저장 — 설문 결과·승인·쿠폰 결과·광고비 점검을 한 줄씩 남긴다. DB 설정이 있으면 PostgreSQL, 없으면 파일.

저장 위치 (11/19):
  DB_HOST 가 있으면  PostgreSQL 의 marketing_sessions·coupon_runs 표 (shared.storage, 표 정의는 db/schema.sql).
                     WAS 가 두 대여도 같은 기록을 본다. 표는 코드를 올리기 전에 python -m shared.storage.init_db 로 만든다.
  DB_HOST 가 없으면  예전 그대로 파일 data/marketing/records_{store_id}.json  (줄 1개 = JSON 1개, .gitignore 대상)
  어느 쪽이든 공개 함수(append_session·append_coupon_run·load·delete·load_for_report)가 돌려주는 dict 모양은 같다.
  DB 를 쓸 때만 저장소 루트의 shared/ 를 가져온다 (마케팅 시험처럼 shared 를 못 찾는 환경에서도 파일 방식은 그대로 돈다).
  예전 파일 기록을 DB 로 옮기는 일은 하지 않는다.
칸 이름은 DB 표 이름과 같다 (이슈 #51 ERD §3.13).

  marketing_sessions : feature, goal, answers, decision, result, parent_id, created_at
  coupon_runs        : menu_name, discount_krw, issued, used, avg_order_krw, margin_pct, period_start, period_end, created_at
                       (margin_pct: 본전 주문 수 계산에 쓰는 남는 비율)

각 줄에는 "table"(위 표 이름)과 "id"가 붙는다. 승인 줄의 parent_id 는 그 승인의 바탕이 된 설문 결과 줄의 id.
실제 기록이 없는 가게는 data/marketing/demo_records_{store_id}.json(합성 데모)을 읽는다 — load_for_report().
기록은 보조 기능이라 쓰기에 실패해도(디스크·DB) 화면 흐름을 막지 않는다 — 호출하는 쪽에서 OSError 를 삼킨다.
  DB 에 닿지 못하면 RecordsUnavailable(OSError 의 한 갈래)을 낸다. 그래서 파일 오류와 같은 자리에서 같은 방식으로 다뤄진다.
  읽기에서 DB 에 닿지 못했을 때는 데모 기록으로 바꾸지 않고 RecordsUnavailable 을 그대로 올린다
  (기록이 있는 사장님에게 '기록 없음 → 데모' 화면이 조용히 나가지 않게. 서버의 /report 가 503 으로 답한다).

방문자 격리 (11/16, 통합 화면 뒤에 붙이면서): 함수마다 visitor_id 를 받는다(쿠키에서 온 방문자 id, ^[A-Za-z0-9_-]{1,64}$).
  visitor_id 가 있으면  records_{store_id}_{visitor_id}.json  (그 방문자 것만 쓰고 읽고 지운다. 줄에도 "visitor_id" 칸)
  visitor_id 가 없으면  records_{store_id}.json              (예전과 같음 — 단독 화면(marketing_survey/web)·시험용)
  보고서는 그 방문자의 실제 기록이 없으면 데모(demo_records_{store_id}.json)를 쓴다. 가게 공용 파일을 섞어 읽지 않는다.
  주의: 가게 id 가 '다른 가게 id + _ + 방문자 id' 꼴이면 파일 이름이 겹친다. 지금 가게 목록(store_ongi 하나)에서는 없다.
  DB 에서는 visitor_id 칸에 둔다. 방문자가 없는 호출은 shared.storage 의 공용 값 'common' 으로 둔다 (approvals 와 같은 관례).
    visitor_id='common' 을 직접 주면 방문자 없는 호출과 같은 곳을 본다 (비서 화면 서버는 이 값을 쿠키로 받지 않아 보내지 않는다).
    delete() 는 'common' 기록을 지우지 않는다 (가게 공용 기록은 이 함수로 지우지 않는다는 약속 그대로).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config

KST = timezone(timedelta(hours=9))
SESSIONS = "marketing_sessions"
COUPON_RUNS = "coupon_runs"
RECORDS_DIR_ENV = "MARKETING_RECORDS_DIR"  # 테스트가 임시 폴더로 돌릴 때 쓴다

COMMON_VISITOR = "common"   # shared/storage/visitor.py 의 COMMON_VISITOR 와 같은 값 (DB 에서 방문자 없는 호출을 두는 곳)
log = logging.getLogger("marketing_survey.records")

_STORE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
VISITOR_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def records_dir() -> Path:
    override = os.environ.get(RECORDS_DIR_ENV)
    return Path(override) if override else config.DATA_DIR / "marketing"


def _check_store_id(store_id: str) -> str:
    if not _STORE_ID_RE.match(store_id or ""):
        raise ValueError("가게 id 형식이 올바르지 않아요.")
    return store_id


def check_visitor_id(visitor_id: str | None) -> str | None:
    """None 이면 None(방문자 없음 — 가게 공용 파일). 형식이 틀리면 ValueError."""
    if visitor_id is None:
        return None
    if not isinstance(visitor_id, str) or not VISITOR_ID_RE.match(visitor_id):
        raise ValueError("방문자 id 형식이 올바르지 않아요.")
    return visitor_id


def records_path(store_id: str, visitor_id: str | None = None) -> Path:
    store_id = _check_store_id(store_id)
    visitor_id = check_visitor_id(visitor_id)
    if visitor_id:
        return records_dir() / f"records_{store_id}_{visitor_id}.json"
    return records_dir() / f"records_{store_id}.json"


def demo_path(store_id: str) -> Path:
    # 데모는 저장소에 들어 있는 파일이라 테스트용 records_dir 덮어쓰기와 상관없이 늘 같은 자리다.
    return config.DATA_DIR / "marketing" / f"demo_records_{_check_store_id(store_id)}.json"


class RecordsUnavailable(OSError):
    """DB 에 닿지 못했다 (장애 전환 중, 표가 아직 없음 등). OSError 라서 파일을 못 쓸 때와 같은 자리에서 잡힌다."""


_UNSET = object()
_store = _UNSET                                   # None 이면 파일, 아니면 .marketing 을 가진 저장소 (shared.storage)
_storage_errors: tuple[type[BaseException], ...] = ()


def _import_shared():
    """저장소 루트의 shared.storage. PYTHONPATH 에 루트가 없으면 이 파일 기준으로 루트를 찾아 import 경로 맨 뒤에 붙인다."""
    try:
        import shared.storage as shared_storage
    except ImportError:
        root = str(Path(__file__).resolve().parents[3])
        if root not in sys.path:
            sys.path.append(root)                 # 맨 뒤: 마케팅 폴더의 config·tests 보다 앞서지 않게
        try:
            import shared.storage as shared_storage
        except ImportError:
            raise RuntimeError("DB_HOST 가 있는데 shared/storage 를 찾지 못했습니다. PYTHONPATH 에 저장소 루트를 주세요") from None
    return shared_storage


def backend():
    """DB 저장소 또는 None(파일). 처음 부를 때 DB_HOST 를 본다.
    DB_HOST 가 있는데 설정이 틀렸거나 psycopg·shared 가 없으면 여기서 오류 (서버는 켜질 때 불러서 바로 멈춘다).
    DB 가 꺼져 있는 것은 괜찮다 (연결은 쓸 때 맺는다)."""
    global _store, _storage_errors
    if _store is _UNSET:
        if (os.environ.get("DB_HOST") or "").strip():
            shared_storage = _import_shared()
            _storage_errors = (shared_storage.StorageError,)
            _store = shared_storage.open_database(app_name="ic26-marketing")
        else:
            _store = None
    return _store


def use(store) -> None:
    """시험·특수 실행용: 쓸 저장소를 직접 정한다 (None 이면 파일). store 는 .marketing 을 가진 것 (MemoryStore·Database)."""
    global _store, _storage_errors
    _store = store
    if store is not None:
        _storage_errors = (_import_shared().StorageError,)


def close() -> None:
    if _store is not _UNSET and _store is not None:
        _store.close()


def reset() -> None:
    """연 저장소를 닫고, 다음에 backend() 를 부를 때 환경 변수를 다시 읽는다."""
    global _store
    close()
    _store = _UNSET


def storage_kind() -> str:
    """기록을 두는 곳: "db" | "file"."""
    return "file" if backend() is None else "db"


@contextmanager
def _guarded():
    try:
        yield
    except _storage_errors as exc:
        log.warning("맞춤 마케팅 기록: DB 에 닿지 못했어요 (%s)", exc)
        raise RecordsUnavailable(f"기록 DB 에 닿지 못했어요 ({exc})") from None


def _db_visitor(visitor_id: str | None) -> str:
    visitor_id = check_visitor_id(visitor_id)
    return visitor_id or COMMON_VISITOR


def _now_iso(now: datetime | None) -> str:
    return (now or datetime.now(KST)).astimezone(KST).isoformat(timespec="seconds")


def _append(store_id: str, row: dict, visitor_id: str | None = None) -> dict:
    db = backend()
    if db is not None:
        _check_store_id(store_id)
        with _guarded():
            return db.marketing.add(store_id, _db_visitor(visitor_id), row)
    path = records_path(store_id, visitor_id)
    if visitor_id:
        row["visitor_id"] = visitor_id
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def append_session(store_id: str, feature: str, *, goal: str | None = None, answers: dict | None = None,
                   decision: str | None = None, result: dict | None = None, parent_id: str | None = None,
                   now: datetime | None = None, visitor_id: str | None = None) -> dict:
    """marketing_sessions 한 줄. 돌려주는 row["id"] 를 승인 줄의 parent_id 로 쓴다."""
    return _append(store_id, {
        "table": SESSIONS, "id": uuid.uuid4().hex, "store_id": store_id,
        "feature": feature, "goal": goal, "answers": answers or {}, "decision": decision,
        "result": result or {}, "parent_id": parent_id, "created_at": _now_iso(now),
    }, visitor_id)


def append_coupon_run(store_id: str, *, menu_name: str | None, discount_krw: int, issued: int, used: int,
                      avg_order_krw: int, margin_pct: int | None = None, period_start: str | None = None,
                      period_end: str | None = None, now: datetime | None = None,
                      visitor_id: str | None = None) -> dict:
    """coupon_runs 한 줄. 기간을 모르면 period_* 는 None(보고서는 created_at 으로 센다)."""
    return _append(store_id, {
        "table": COUPON_RUNS, "id": uuid.uuid4().hex, "store_id": store_id,
        "menu_name": menu_name, "discount_krw": int(discount_krw), "issued": int(issued), "used": int(used),
        "avg_order_krw": int(avg_order_krw), "margin_pct": margin_pct,
        "period_start": period_start, "period_end": period_end, "created_at": _now_iso(now),
    }, visitor_id)


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


def load(store_id: str, visitor_id: str | None = None) -> list[dict]:
    """실제 기록(없으면 빈 목록). visitor_id 가 있으면 그 방문자 것만. DB 에 닿지 못하면 RecordsUnavailable."""
    db = backend()
    if db is not None:
        _check_store_id(store_id)
        with _guarded():
            return db.marketing.list(store_id, _db_visitor(visitor_id))
    return _read_lines(records_path(store_id, visitor_id))


def delete(store_id: str, visitor_id: str) -> bool:
    """그 방문자의 기록만 지운다(파일이면 그 파일, DB 면 두 표의 그 방문자 줄). 지웠으면 True, 없었으면 False.
    visitor_id 가 없으면 ValueError — 가게 공용 파일(records_{store_id}.json)은 이 함수로 지우지 않는다."""
    if not visitor_id:
        raise ValueError("방문자 id 가 없으면 기록을 지우지 않아요.")
    db = backend()
    if db is not None:
        _check_store_id(store_id)
        if _db_visitor(visitor_id) == COMMON_VISITOR:
            return False                          # DB 에서 'common' 은 가게 공용 기록 자리라 지우지 않는다
        with _guarded():
            return db.marketing.delete(store_id, visitor_id) > 0
    path = records_path(store_id, visitor_id)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


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


def load_for_report(store_id: str, visitor_id: str | None = None) -> tuple[list[dict], bool]:
    """(기록, 데모 여부). 실제 기록이 한 줄이라도 있으면 그것만 쓰고 데모는 쓰지 않는다.
    visitor_id 가 있으면 그 방문자의 기록만 본다 (없으면 데모 — 가게 공용·다른 방문자 기록은 섞지 않는다).
    DB 에 닿지 못하면 데모로 바꾸지 않고 RecordsUnavailable 을 올린다 (기록이 없는 것과 읽지 못한 것을 섞지 않게)."""
    real = load(store_id, visitor_id)
    if real:
        return real, False
    return load_demo(store_id), True
