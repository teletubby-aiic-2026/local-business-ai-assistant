"""저장 계층 연결. DB 설정(환경 변수 DB_HOST)이 있을 때만 저장소 루트의 shared.storage 를 쓴다.

- DB_HOST 가 없으면 이 파일은 아무것도 가져오지 않고, 붙여넣은 리뷰와 분류 결과는 지금처럼 data/runtime 의 파일에 둔다.
  (Dockerfile 이미지에는 이 서비스 폴더만 들어가서 shared/ 가 없다. 그래도 파일 방식으로 돈다.)
- DB_HOST 가 있으면 shared.storage 가 필요하다. 서버에서는 저장소 루트를 PYTHONPATH 로 준다. 안 줘도
  저장소 안에서 실행하면(services/review-insight) 루트를 찾아 import 경로 맨 뒤에 붙인다.
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

_UNSET = object()
_db = _UNSET
_errors: tuple[type[BaseException], ...] = ()    # shared.storage 를 가져온 뒤에 StorageError 로 채워진다


class StorageUnavailable(RuntimeError):
    """DB 에 닿지 못했을 때 (장애 전환 중 등). API 는 503 으로 답한다."""


def _import_shared():
    try:
        import shared.storage as shared_storage
    except ImportError:
        root = str(Path(__file__).resolve().parents[3])
        if root not in sys.path:
            sys.path.append(root)         # 맨 뒤에 붙여서, 이 서비스의 app 패키지보다 앞서지 않게
        try:
            import shared.storage as shared_storage
        except ImportError:
            raise RuntimeError("DB_HOST 가 있는데 shared/storage 를 찾지 못했습니다. "
                               "PYTHONPATH 에 저장소 루트를 주세요") from None
    return shared_storage


def database():
    """Database 또는 None(파일). 처음 부를 때 환경 변수를 읽는다."""
    global _db, _errors
    if _db is _UNSET:
        if os.environ.get("DB_HOST", "").strip():
            shared_storage = _import_shared()
            _errors = (shared_storage.StorageError,)
            _db = shared_storage.open_database(app_name="ic26-review")
        else:
            _db = None
    return _db


def use(db) -> None:
    """시험·특수 실행용: 쓸 저장소를 직접 정한다 (None 이면 파일)."""
    global _db, _errors
    _db = db
    if db is not None:
        _errors = (_import_shared().StorageError,)


def reset() -> None:
    """다음에 database() 를 부를 때 환경 변수를 다시 읽는다."""
    global _db
    close()
    _db = _UNSET


def close() -> None:
    if _db is not _UNSET and _db is not None:
        _db.close()


@contextmanager
def guarded():
    """DB 오류를 StorageUnavailable 로 바꾼다 (파일 방식일 때는 아무 오류도 바꾸지 않는다)."""
    try:
        yield
    except _errors as exc:
        raise StorageUnavailable(str(exc)) from None
