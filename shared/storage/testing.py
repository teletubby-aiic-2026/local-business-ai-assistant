"""DB 가 있는 시험의 도우미 (시험에서만 쓴다).

환경 변수 TEST_DB_HOST, TEST_DB_PORT, TEST_DB_NAME, TEST_DB_USER, TEST_DB_PASSWORD 가 있을 때만 PostgreSQL 시험을 돌리고,
없으면 시험이 건너뛴다 (평소 시험은 DB 없이 돈다). 앱이 읽는 DB_* 환경 변수와 이름이 달라서, 개발자 컴퓨터에 DB_HOST 가
있어도 시험이 그 DB 에 붙지 않는다.

    TEST_DB_CONTAINER (선택): 이 이름의 Docker 컨테이너를 멈췄다 켜서 '연결이 끊겼다 돌아오는' 시험을 돌린다. 없으면 그 시험만 건너뛴다.
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Mapping

from .config import DbConfig


def db_env(env: Mapping[str, str] | None = None) -> dict[str, str] | None:
    """TEST_DB_* 를 앱이 읽는 DB_* 모양으로 바꾼 것. TEST_DB_HOST 가 없으면 None."""
    env = os.environ if env is None else env
    if not (env.get("TEST_DB_HOST") or "").strip():
        return None
    return {k: env.get(f"TEST_{k}", "") for k in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")}


def db_config(**changes) -> DbConfig | None:
    import dataclasses
    mapping = db_env()
    config = DbConfig.from_env(mapping) if mapping else None
    return dataclasses.replace(config, **changes) if config and changes else config


def open_test_db(app_name: str = "ic26-test", **changes):
    """표가 만들어진 Database. TEST_DB_* 가 없으면 None. 열 때마다 새 연결 풀이다 (서버 한 대)."""
    config = db_config(**changes)
    if config is None:
        return None
    from .init_db import create_tables
    from .pg import Database
    db = Database(config, app_name=app_name).open()
    create_tables(db)
    return db


def docker_ctl(name: str, action: str) -> None:
    """Docker 컨테이너를 멈추거나(stop) 켜거나(start) 재시작(restart)한다. 장애 전환 때 DB 가 잠시 사라지는 것을 흉내낸다."""
    subprocess.run(["docker", action, name], check=True, capture_output=True, timeout=120)


def wait_until_ready(timeout: float = 40.0) -> None:
    """DB 가 다시 접속을 받을 때까지 기다린다 (시험용 따로 연 연결로 확인한다)."""
    from .pg import Database
    probe = Database(db_config(connect_timeout=2.0, retry_after=0.0), app_name="ic26-test-wait").open()
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                probe.ping()
                return
            except Exception:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
    finally:
        probe.close()
