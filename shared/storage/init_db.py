"""DB 표 만들기. 저장소 루트에서:

    python -m shared.storage.init_db

DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD 환경 변수로 접속해 db/schema.sql 을 실행한다.
여러 번 돌려도 안전하다 (CREATE ... IF NOT EXISTS). 이미 있는 표의 칸을 고치지는 않는다.
앱이 켜질 때 자동으로 부르지 않는다. 비밀번호는 출력하지 않는다.
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

from .config import DbConfig
from .errors import StorageConfigError, StorageError

DEFAULT_SCHEMA = Path(__file__).resolve().parents[2] / "db" / "schema.sql"


def create_tables(db, schema: Path = DEFAULT_SCHEMA) -> list[str]:
    """schema 를 한 트랜잭션으로 실행하고, 지금 있는 표 이름을 돌려준다."""
    from .pg import TABLES
    sql = Path(schema).read_text(encoding="utf-8")

    def work(conn):
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('ic26-init-db'))")   # 두 곳에서 동시에 돌려도 부딪히지 않게
        conn.execute(sql)
        rows = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() "
                            "AND table_name = ANY(%s)", (list(TABLES),)).fetchall()
        return sorted(r["table_name"] for r in rows)
    return db.run(work)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DB 표를 만든다 (db/schema.sql). 여러 번 돌려도 안전하다.")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA, help="표 정의 파일 (기본: db/schema.sql)")
    args = parser.parse_args(argv)
    try:
        config = DbConfig.from_env()
    except StorageConfigError as exc:
        print(f"DB 설정이 틀렸습니다: {exc}", file=sys.stderr)
        return 2
    if config is None:
        print("DB_HOST 환경 변수가 없습니다. DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD 를 정하고 다시 실행하세요.", file=sys.stderr)
        return 2
    try:
        from .pg import TABLES, Database
        db = Database(dataclasses.replace(config, query_timeout=60.0, retry_after=0.0), app_name="ic26-init-db").open()
        try:
            found = create_tables(db, args.schema)
        finally:
            db.close()
    except (StorageError, ImportError) as exc:
        print(f"표를 만들지 못했습니다: {config.scrub(exc)}", file=sys.stderr)
        return 1
    print(f"{config.host}:{config.port}/{config.dbname} 표 {len(found)}개 확인: {', '.join(found)}")
    missing = [t for t in TABLES if t not in found]
    if missing:
        print(f"없는 표: {', '.join(missing)} (db/schema.sql 에 없음)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
