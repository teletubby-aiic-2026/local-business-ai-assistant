"""DB 접속 설정. 환경 변수에서만 읽습니다 (서버에서는 /etc/ic26/env).

    DB_HOST        있으면 PostgreSQL 을 쓴다. 없으면 DB 를 쓰지 않는다 (메모리·파일, 지금까지와 같음)
    DB_PORT        기본 5432
    DB_NAME, DB_USER, DB_PASSWORD
    DB_SSLMODE          (선택) require 등. 비우면 드라이버 기본값
    DB_CONNECT_TIMEOUT  (선택) 접속 제한 초. 기본 3 (libpq 는 최소 2초)
    DB_QUERY_TIMEOUT    (선택) 질의 제한 초. 기본 5
    DB_POOL_MAX         (선택) 연결 풀 크기. 기본 5 (서버 2대 × 서비스 2개 × 5 = 최대 20개 연결)

DB_HOST 만 있고 DB_NAME 이나 DB_USER 가 없으면 오류로 멈춥니다. 오타 때문에 조용히 메모리로 도는 것을 막으려는 것입니다
(서버가 2대면 서로 다른 내용을 보게 됩니다). 비밀번호는 repr 와 오류 메시지에 나오지 않습니다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

from .errors import StorageConfigError


def _number(env: Mapping[str, str], key: str, default: float, minimum: float, cast=float):
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise StorageConfigError(f"{key} 는 숫자여야 합니다") from None
    if value < minimum:
        raise StorageConfigError(f"{key} 는 {minimum:g} 이상이어야 합니다")
    return value


@dataclass(frozen=True)
class DbConfig:
    host: str
    dbname: str
    user: str
    password: str = field(default="", repr=False)
    port: int = 5432
    sslmode: str = ""
    connect_timeout: float = 3.0      # 초. 접속과 연결 풀에서 연결을 받는 일에 모두 쓴다
    query_timeout: float = 5.0        # 초. 질의 하나가 이보다 길면 DB 가 끊는다 (statement_timeout)
    pool_max: int = 5
    retry_after: float = 2.0          # 초. 실패한 뒤 이 시간 동안은 DB 를 다시 부르지 않고 바로 오류 (장애 중 요청이 줄줄이 기다리지 않게)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "DbConfig | None":
        env = os.environ if env is None else env
        host = (env.get("DB_HOST") or "").strip()
        if not host:
            return None
        dbname, user = (env.get("DB_NAME") or "").strip(), (env.get("DB_USER") or "").strip()
        missing = [k for k, v in (("DB_NAME", dbname), ("DB_USER", user)) if not v]
        if missing:
            raise StorageConfigError(f"DB_HOST 가 있으면 {', '.join(missing)} 도 필요합니다")
        return cls(host=host, dbname=dbname, user=user, password=env.get("DB_PASSWORD") or "",
                   port=int(_number(env, "DB_PORT", 5432, 1, int)), sslmode=(env.get("DB_SSLMODE") or "").strip(),
                   connect_timeout=_number(env, "DB_CONNECT_TIMEOUT", 3.0, 1.0),
                   query_timeout=_number(env, "DB_QUERY_TIMEOUT", 5.0, 0.5),
                   pool_max=int(_number(env, "DB_POOL_MAX", 5, 1, int)))

    def connect_kwargs(self, app_name: str = "") -> dict:
        """psycopg.connect 에 그대로 넘기는 값. 비밀번호를 접속 문자열에 합치지 않고 따로 넘긴다."""
        kwargs: dict = {
            "host": self.host, "port": self.port, "dbname": self.dbname, "user": self.user,
            "connect_timeout": max(2, round(self.connect_timeout)),
            # 질의 제한과, 장애 전환으로 조용히 끊긴 연결을 빨리 알아차리는 TCP 확인
            "options": f"-c statement_timeout={int(self.query_timeout * 1000)}",
            "keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3,
        }
        if self.password:
            kwargs["password"] = self.password
        if self.sslmode:
            kwargs["sslmode"] = self.sslmode
        if app_name:
            kwargs["application_name"] = app_name
        return kwargs

    def scrub(self, text: object) -> str:
        """오류 글에 비밀번호가 섞여 있으면 가린다."""
        out = str(text)
        return out.replace(self.password, "***") if self.password else out
