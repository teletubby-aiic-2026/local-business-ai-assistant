"""실행 중에 생기는 데이터(승인 기록, 붙여넣은 리뷰와 분류 결과, 카드 추천 이유, 주간·월간 보고서)의 저장 계층.

구현이 두 가지다. 쓰는 쪽은 어느 쪽인지 몰라도 된다.
- 기본 (memory.py): 서버 메모리. 붙여넣은 리뷰와 분류 결과는 리뷰 분석 서비스가 지금처럼 자기 파일에 둔다.
- PostgreSQL (pg.py): 환경 변수 DB_HOST 가 있을 때. 서버를 여러 대 띄워도 같은 내용을 본다.

    from shared.storage import open_store
    store = open_store(app_name="ic26-web")     # DB 설정이 없으면 MemoryStore
    store.approvals.save(store_id, visitor_id, entry)

DB 설정이 없고 psycopg 도 없는 환경에서도 이 패키지는 import 된다 (psycopg 는 DB 를 켤 때 처음 가져온다).
표 정의는 db/schema.sql, 표 만들기는 `python -m shared.storage.init_db`. 환경 변수는 config.py.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Mapping

from .config import DbConfig
from .errors import StorageConfigError, StorageError
from .memory import MemoryStore
from .visitor import (COMMON_VISITOR, clean_visitor_id, is_valid_visitor_id, new_visitor_id, visitor_from_cookie)

__all__ = ["COMMON_VISITOR", "DbConfig", "MemoryStore", "StorageConfigError", "StorageError", "clean_visitor_id",
           "is_valid_visitor_id", "new_visitor_id", "open_database", "open_store", "visitor_from_cookie"]

if TYPE_CHECKING:
    from .pg import Database

log = logging.getLogger("shared.storage")


def open_database(env: Mapping[str, str] | None = None, *, app_name: str = "") -> "Database | None":
    """DB_HOST 가 있으면 연결 풀을 열어 Database 를, 없으면 None 을 돌려준다.

    DB 가 안 떠 있어도 여기서 기다리거나 실패하지 않는다. 설정이 틀렸거나 psycopg 가 없을 때만 StorageConfigError.
    """
    config = DbConfig.from_env(env)
    if config is None:
        return None
    try:
        from .pg import Database
    except ImportError:
        raise StorageConfigError("DB_HOST 가 있는데 psycopg 를 가져오지 못했습니다. "
                                 "pip install 'psycopg[binary,pool]' (requirements.txt 에 있음)") from None
    db = Database(config, app_name=app_name).open()
    log.info("저장소: PostgreSQL %s:%s/%s", config.host, config.port, config.dbname)
    return db


def open_store(env: Mapping[str, str] | None = None, *, app_name: str = "") -> "Database | MemoryStore":
    """Database 또는 MemoryStore. 둘 다 approvals, card_reasons, reports 를 가진다 (kind 는 'postgres' | 'memory')."""
    return open_database(env, app_name=app_name) or MemoryStore()
