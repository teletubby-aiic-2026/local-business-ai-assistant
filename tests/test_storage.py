"""저장 계층 시험 (shared/storage).

- DB 없이 도는 부분: 방문자 id 형식, 설정 읽기, 메모리 구현, 두 구현이 같아야 하는 약속(계약)의 메모리 쪽.
- PostgreSQL 이 필요한 부분: 환경 변수 TEST_DB_HOST 등이 없으면 건너뜀 (shared/storage/testing.py 에 설명).

DB 있는 시험 예 (임시 컨테이너):
    docker run -d --name ic26-storage-test -e POSTGRES_PASSWORD=<임의 값> -e POSTGRES_USER=ic26test -e POSTGRES_DB=ic26test \
        -p 127.0.0.1:55432:5432 postgres:16
    TEST_DB_HOST=127.0.0.1 TEST_DB_PORT=55432 TEST_DB_NAME=ic26test TEST_DB_USER=ic26test TEST_DB_PASSWORD=<같은 값> \
        TEST_DB_CONTAINER=ic26-storage-test python -m pytest -q tests/test_storage.py
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

from shared.storage import (COMMON_VISITOR, DbConfig, MemoryStore, StorageConfigError, StorageError, clean_visitor_id,
                            is_valid_visitor_id, new_visitor_id, open_database, open_store, visitor_from_cookie)
from shared.storage.testing import docker_ctl, open_test_db, db_config, db_env, wait_until_ready

REPO = Path(__file__).resolve().parents[1]
HAS_DB = db_env() is not None
needs_db = pytest.mark.skipif(not HAS_DB, reason="TEST_DB_HOST 없음 (PostgreSQL 시험은 건너뜀)")
CONTAINER = os.environ.get("TEST_DB_CONTAINER", "")


def uid(prefix: str = "t") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ── 방문자 id ───────────────────────────────────────────────────────
@pytest.mark.parametrize("value", ["a", "A-b_9", "x" * 64, "0123456789abcdef", "-", "_"])
def test_visitor_id_accepts_letters_digits_dash_underscore(value):
    assert is_valid_visitor_id(value) and clean_visitor_id(value) == value


@pytest.mark.parametrize("value", ["../x", "..", "a/b", "a\\b", "a.b", "a b", "x" * 65, "abc\n", "\nabc", "한글", "a\x00b",
                                   "%2e%2e", "a;b", "a,b", "~", "a:b"])
def test_visitor_id_rejects_path_and_odd_characters(value):
    assert not is_valid_visitor_id(value)
    with pytest.raises(ValueError):
        clean_visitor_id(value)


def test_visitor_id_defaults_and_non_strings():
    assert clean_visitor_id(None) == COMMON_VISITOR and clean_visitor_id("") == COMMON_VISITOR
    assert not is_valid_visitor_id(None) and not is_valid_visitor_id(123) and not is_valid_visitor_id(b"abc")


def test_new_visitor_ids_are_valid_and_different():
    ids = {new_visitor_id() for _ in range(200)}
    assert len(ids) == 200 and all(is_valid_visitor_id(i) and i != COMMON_VISITOR for i in ids)


def test_cookie_value_must_be_a_real_visitor_id():
    assert visitor_from_cookie("abc_DEF-123") == "abc_DEF-123"
    assert visitor_from_cookie(None) is None and visitor_from_cookie("") is None
    assert visitor_from_cookie("../etc") is None and visitor_from_cookie("x" * 65) is None
    assert visitor_from_cookie(COMMON_VISITOR) is None     # 공용 값을 쿠키로 만들어 공용 기록을 보지 못하게


# ── 설정 ────────────────────────────────────────────────────────────
def test_no_db_host_means_no_database():
    assert DbConfig.from_env({}) is None and DbConfig.from_env({"DB_HOST": "  "}) is None
    assert open_database({}) is None
    assert isinstance(open_store({}), MemoryStore) and open_store({}).kind == "memory"


def test_db_config_reads_env_with_defaults_and_hides_password():
    cfg = DbConfig.from_env({"DB_HOST": "db.internal", "DB_NAME": "ic26app", "DB_USER": "app", "DB_PASSWORD": "S3cret-pw!"})
    assert (cfg.host, cfg.port, cfg.dbname, cfg.user) == ("db.internal", 5432, "ic26app", "app")
    assert "S3cret-pw!" not in repr(cfg) and "S3cret-pw!" not in str(cfg)
    kwargs = cfg.connect_kwargs("ic26-web")
    assert kwargs["password"] == "S3cret-pw!" and kwargs["application_name"] == "ic26-web"
    assert kwargs["connect_timeout"] >= 2 and "statement_timeout=5000" in kwargs["options"]
    assert cfg.scrub("auth failed for password S3cret-pw!") == "auth failed for password ***"
    assert DbConfig.from_env({"DB_HOST": "h", "DB_NAME": "n", "DB_USER": "u", "DB_PORT": "6543"}).port == 6543


@pytest.mark.parametrize("env,word", [
    ({"DB_HOST": "h", "DB_USER": "u"}, "DB_NAME"),
    ({"DB_HOST": "h", "DB_NAME": "n"}, "DB_USER"),
    ({"DB_HOST": "h", "DB_NAME": "n", "DB_USER": "u", "DB_PORT": "abc"}, "DB_PORT"),
    ({"DB_HOST": "h", "DB_NAME": "n", "DB_USER": "u", "DB_QUERY_TIMEOUT": "0"}, "DB_QUERY_TIMEOUT"),
])
def test_half_configured_db_stops_loudly_instead_of_silently_using_memory(env, word):
    """DB_HOST 만 있고 나머지가 빠지면 조용히 메모리로 돌지 않는다 (서버가 2대면 서로 다른 내용을 보게 되므로)."""
    with pytest.raises(StorageConfigError) as err:
        DbConfig.from_env(env)
    assert word in str(err.value)


def test_db_host_without_psycopg_is_a_clear_startup_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "shared.storage.pg", None)      # psycopg 가 안 깔린 환경을 흉내: pg 를 가져오지 못함
    with pytest.raises(StorageConfigError) as err:
        open_database({"DB_HOST": "h", "DB_NAME": "n", "DB_USER": "u", "DB_PASSWORD": "pw-should-not-show"})
    assert "psycopg" in str(err.value) and "pw-should-not-show" not in str(err.value)


# ── 두 구현이 같아야 하는 약속 (메모리 + PostgreSQL) ───────────────────
@pytest.fixture(params=["memory", "postgres"])
def backend(request):
    if request.param == "memory":
        yield MemoryStore()
        return
    db = open_test_db()
    if db is None:
        pytest.skip("TEST_DB_HOST 없음 (PostgreSQL 시험은 건너뜀)")
    yield db
    db.close()


def entry(draft_id, text="글", at="2026-11-14T10:00:00+09:00", edited=False, mode="mock"):
    return {"draft_id": draft_id, "status": "approved", "edited": edited, "text": text, "approved_at": at, "mode": mode}


def test_approvals_replace_same_draft_and_keep_the_shape(backend):
    sid, v = uid("store"), uid("v")
    backend.approvals.save(sid, v, entry("d1", at="2026-11-14T10:00:00+09:00"), card_id="card_a", kind="reply_draft")
    backend.approvals.save(sid, v, entry("d2", at="2026-11-14T10:00:01+09:00"))
    backend.approvals.save(sid, v, entry("d1", text="고친 글", edited=True, at="2026-11-14T10:00:02+09:00"))
    items = backend.approvals.list(sid, v)
    assert [i["draft_id"] for i in items] == ["d2", "d1"]             # 다시 승인한 것은 맨 뒤로
    assert items[1]["text"] == "고친 글" and items[1]["edited"] is True and items[0]["edited"] is False
    assert set(items[0]) == {"draft_id", "status", "edited", "text", "approved_at", "mode"}   # 지금 화면이 받는 칸 그대로
    assert items[0]["approved_at"] == "2026-11-14T10:00:01+09:00" and items[0]["status"] == "approved"


def test_approvals_are_separate_per_visitor_and_store(backend):
    s1, s2, a, b = uid("store"), uid("store"), uid("v"), uid("v")
    backend.approvals.save(s1, a, entry("d1"))
    assert [i["draft_id"] for i in backend.approvals.list(s1, a)] == ["d1"]
    assert backend.approvals.list(s1, b) == [] and backend.approvals.list(s2, a) == []
    backend.approvals.save(s1, b, entry("d1", text="B 의 글"))       # 같은 초안 id 라도 방문자마다 따로
    assert backend.approvals.list(s1, a)[0]["text"] == "글" and backend.approvals.list(s1, b)[0]["text"] == "B 의 글"


def test_approvals_clear_removes_only_that_visitor_in_that_store(backend):
    """승인 기록 지우기('처음부터 다시'): 이 가게·이 방문자의 것만 지우고 지운 건수를 돌려준다."""
    s1, s2, a, b = uid("store"), uid("store"), uid("v"), uid("v")
    backend.approvals.save(s1, a, entry("d1"), card_id="card_a", kind="reply_draft")
    backend.approvals.save(s1, a, entry("d2", at="2026-11-14T10:00:01+09:00"))
    backend.approvals.save(s1, b, entry("d1", text="B 의 글"))
    backend.approvals.save(s2, a, entry("d1", text="다른 가게의 글"))
    assert backend.approvals.clear(s1, a) == 2
    assert backend.approvals.list(s1, a) == []
    assert [i["text"] for i in backend.approvals.list(s1, b)] == ["B 의 글"]            # 다른 방문자 것은 그대로
    assert [i["text"] for i in backend.approvals.list(s2, a)] == ["다른 가게의 글"]       # 다른 가게 것도 그대로
    assert backend.approvals.clear(s1, a) == 0                                        # 지울 것이 없으면 0
    backend.approvals.save(s1, a, entry("d3"))                                        # 지운 뒤에도 다시 쌓인다
    assert [i["draft_id"] for i in backend.approvals.list(s1, a)] == ["d3"]


def test_approvals_delete_removes_only_those_drafts_of_that_visitor_in_that_store(backend):
    """다시 만들어 바뀐 옛 글의 승인 기록만 지우기 (11/16): 이 가게·이 방문자의 그 글들만 지우고 지운 건수를 돌려준다."""
    s1, s2, a, b = uid("store"), uid("store"), uid("v"), uid("v")
    backend.approvals.save(s1, a, entry("d1"), card_id="card_a", kind="reply_draft")
    backend.approvals.save(s1, a, entry("d2", at="2026-11-14T10:00:01+09:00"))
    backend.approvals.save(s1, a, entry("d3", at="2026-11-14T10:00:02+09:00"))
    backend.approvals.save(s1, b, entry("d1", text="B 의 글"))
    backend.approvals.save(s2, a, entry("d1", text="다른 가게의 글"))
    assert backend.approvals.delete(s1, a, ["d1", "d3", "d_none"]) == 2                 # 없는 id 는 세지 않는다
    assert [i["draft_id"] for i in backend.approvals.list(s1, a)] == ["d2"]            # 다른 글은 그대로 (순서도)
    assert [i["text"] for i in backend.approvals.list(s1, b)] == ["B 의 글"]           # 다른 방문자 것은 그대로
    assert [i["text"] for i in backend.approvals.list(s2, a)] == ["다른 가게의 글"]      # 다른 가게 것도 그대로
    assert backend.approvals.delete(s1, a, ["d1"]) == 0 and backend.approvals.delete(s1, a, []) == 0
    assert backend.approvals.delete(s1, uid("v"), ["d2"]) == 0                          # 기록이 없는 방문자
    backend.approvals.save(s1, a, entry("d1", text="새 글", at="2026-11-14T10:00:03+09:00"))   # 같은 id 로 다시 승인하면 다시 쌓인다
    assert [i["draft_id"] for i in backend.approvals.list(s1, a)] == ["d2", "d1"]


def test_card_reasons_put_get_overwrite(backend):
    sid = uid("store")
    assert backend.card_reasons.get(sid, "card_a", "k1") is None
    backend.card_reasons.put(sid, "card_a", "k1", reason_text="포장 누락 3건 [F1]", source="HCX-005 (검사기 통과)", model="HCX-005")
    got = backend.card_reasons.get(sid, "card_a", "k1")
    assert (got["reason_text"], got["source"], got["model"]) == ("포장 누락 3건 [F1]", "HCX-005 (검사기 통과)", "HCX-005")
    assert got["created_at"][-6:] == "+09:00"
    assert backend.card_reasons.get(sid, "card_a", "k2") is None and backend.card_reasons.get(sid, "card_b", "k1") is None
    assert backend.card_reasons.get(uid("store"), "card_a", "k1") is None
    backend.card_reasons.put(sid, "card_a", "k1", reason_text="새 문장 [F1]", source="s", model=None)
    assert backend.card_reasons.get(sid, "card_a", "k1")["reason_text"] == "새 문장 [F1]"


def test_reports_save_get_list(backend):
    sid = uid("store")
    first = backend.reports.save(sid, "weekly", "2026-11-02", "2026-11-08", numbers={"review_count": 40, "복합": {"불만": [1, 2]}},
                                 body_text="이번 주 리뷰 40건", evidence_ids=["rv_1", "snap_2"], prompt_version="p1")
    assert first["period_start"] == "2026-11-02" and first["period_end"] == "2026-11-08"
    assert first["numbers"] == {"review_count": 40, "복합": {"불만": [1, 2]}} and first["evidence_ids"] == ["rv_1", "snap_2"]
    got = backend.reports.get(sid, "weekly", "2026-11-02", "2026-11-08")
    assert got["body_text"] == "이번 주 리뷰 40건" and got["prompt_version"] == "p1" and got["created_at"].endswith("+09:00")
    assert backend.reports.get(sid, "monthly", "2026-11-02", "2026-11-08") is None
    assert backend.reports.get(uid("store"), "weekly", "2026-11-02", "2026-11-08") is None


def test_reports_same_period_and_prompt_overwrite_other_prompt_kept(backend):
    sid = uid("store")
    backend.reports.save(sid, "weekly", "2026-11-02", "2026-11-08", numbers={"n": 1}, body_text="옛", evidence_ids=[], prompt_version="p1")
    backend.reports.save(sid, "weekly", "2026-11-02", "2026-11-08", numbers={"n": 2}, body_text="새", evidence_ids=[], prompt_version="p1")
    assert len(backend.reports.list(sid)) == 1 and backend.reports.get(sid, "weekly", "2026-11-02", "2026-11-08")["numbers"] == {"n": 2}
    time.sleep(0.01)
    backend.reports.save(sid, "weekly", "2026-11-02", "2026-11-08", numbers={"n": 3}, body_text="v2", evidence_ids=[], prompt_version="p2")
    assert len(backend.reports.list(sid)) == 2
    assert backend.reports.get(sid, "weekly", "2026-11-02", "2026-11-08")["prompt_version"] == "p2"     # 가장 늦게 만든 것


def test_reports_list_is_newest_period_first_and_can_filter(backend):
    sid = uid("store")
    for start, end, kind in [("2026-10-26", "2026-11-01", "weekly"), ("2026-11-02", "2026-11-08", "weekly"),
                             ("2026-10-01", "2026-10-31", "monthly")]:
        backend.reports.save(sid, kind, start, end, numbers={}, body_text=kind, evidence_ids=[], prompt_version="p1")
    assert [r["period_start"] for r in backend.reports.list(sid)] == ["2026-11-02", "2026-10-26", "2026-10-01"]
    assert [r["period_kind"] for r in backend.reports.list(sid, "monthly")] == ["monthly"]
    assert len(backend.reports.list(sid, limit=2)) == 2


def test_reports_reject_bad_period_the_same_way(backend):
    sid = uid("store")
    with pytest.raises(ValueError):
        backend.reports.save(sid, "daily", "2026-11-02", "2026-11-08", numbers={}, body_text="", evidence_ids=[], prompt_version="p1")
    with pytest.raises(ValueError):
        backend.reports.save(sid, "weekly", "2026-11-08", "2026-11-02", numbers={}, body_text="", evidence_ids=[], prompt_version="p1")
    assert backend.reports.list(sid) == []


# ── PostgreSQL 만 ───────────────────────────────────────────────────
@pytest.fixture
def db():
    handle = open_test_db()
    if handle is None:
        pytest.skip("TEST_DB_HOST 없음 (PostgreSQL 시험은 건너뜀)")
    yield handle
    handle.close()


def review(n, text="치킨무가 빠졌어요"):
    return {"review_id": f"rv_x_paste_{n:03d}", "channel": "baemin", "rating": 2, "text": text,
            "created_at": f"2026-11-09T23:{n:02d}:00+09:00", "input_method": "paste", "pii_masked": False, "data_origin": "synthetic"}


def test_pg_reviews_numbered_per_store_and_visitor_and_isolated(db):
    sid, a, b = uid("store"), uid("v"), uid("v")
    first = db.reviews.add(sid, a, lambda n: review(n, "A 의 글"))
    db.reviews.add(sid, a, lambda n: review(n, "A 의 둘째"))
    other = db.reviews.add(sid, b, lambda n: review(n, "B 의 글"))
    assert first["review_id"] == "rv_x_paste_001" and other["review_id"] == "rv_x_paste_001"   # 번호는 방문자마다 1부터
    mine = db.reviews.list(sid, a)
    assert [r["text"] for r in mine] == ["A 의 글", "A 의 둘째"] and [r["review_id"] for r in mine][-1] == "rv_x_paste_002"
    assert [r["text"] for r in db.reviews.list(sid, b)] == ["B 의 글"] and db.reviews.list(sid, uid("v")) == []
    assert db.reviews.list(uid("store"), a) == []
    assert mine[0]["created_at"] == "2026-11-09T23:01:00+09:00" and mine[0]["rating"] == 2 and mine[0]["channel"] == "baemin"
    assert db.reviews.clear(sid, a) == 2 and db.reviews.list(sid, a) == [] and len(db.reviews.list(sid, b)) == 1
    assert db.reviews.add(sid, a, lambda n: review(n))["review_id"] == "rv_x_paste_001"      # 지운 뒤에는 다시 1번부터 (파일 방식과 같음)


def test_pg_reviews_numbers_never_collide_across_two_servers(db):
    """서버 2대(연결 풀 둘)가 같은 방문자 리뷰를 동시에 붙여넣어도 번호가 겹치지 않는다."""
    sid, v = uid("store"), uid("v")
    other = open_test_db("ic26-test-2")
    errors, made = [], []

    def worker(handle):
        try:
            for _ in range(5):
                made.append(handle.reviews.add(sid, v, lambda n: review(n))["review_id"])
        except Exception as exc:     # pragma: no cover
            errors.append(exc)
    threads = [threading.Thread(target=worker, args=(h,)) for h in (db, other, db, other)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    other.close()
    assert not errors
    rows = db.run(lambda c: c.execute("SELECT seq FROM reviews WHERE store_id=%s AND visitor_id=%s ORDER BY seq", (sid, v)).fetchall())
    assert [r["seq"] for r in rows] == list(range(1, 21)) and len(made) == 20


def test_pg_labels_roundtrip(db):
    key1, key2 = uid("k"), uid("k")
    result = {"sentiment": "negative", "topics": [{"topic": "missing_item", "polarity": "negative", "evidence": "빠졌어요"}], "summary": "누락"}
    assert db.labels.get_many([]) == {} and db.labels.get_many([key1]) == {}
    db.labels.put_many({key1: result}, prompt_version="c3-v7", model="HCX-005")
    assert db.labels.get_many([key1, key2, key1]) == {key1: result}
    db.labels.put_many({key1: {**result, "summary": "새"}, key2: result}, prompt_version="c3-v8", model="HCX-005")
    got = db.labels.get_many({key1, key2})
    assert got[key1]["summary"] == "새" and got[key2] == result
    stored = db.run(lambda c: c.execute("SELECT prompt_version, model FROM review_labels WHERE label_key=%s", (key1,)).fetchone())
    assert stored == {"prompt_version": "c3-v8", "model": "HCX-005"}
    db.labels.put_many({}, prompt_version="x", model=None)          # 빈 입력은 아무 일도 하지 않음


def test_pg_approval_keeps_card_and_kind_columns(db):
    sid, v = uid("store"), uid("v")
    db.approvals.save(sid, v, entry("d1"), card_id="card_ongi_a", kind="reply_draft")
    db.approvals.save(sid, v, entry("d1", text="고침", edited=True, at="2026-11-14T10:05:00+09:00"))     # 다시 승인(카드·종류를 안 줘도 유지)
    row = db.run(lambda c: c.execute("SELECT card_id, kind, status, approved_text, edited, mode FROM approvals WHERE store_id=%s", (sid,)).fetchone())
    assert row == {"card_id": "card_ongi_a", "kind": "reply_draft", "status": "approved", "approved_text": "고침", "edited": True, "mode": "mock"}


def test_init_db_twice_is_safe_and_creates_every_table(db):
    from shared.storage.init_db import create_tables
    from shared.storage.pg import TABLES
    assert create_tables(db) == sorted(TABLES) and create_tables(db) == sorted(TABLES)


def test_init_db_command_runs_twice_and_without_db_host(db):
    env = {**os.environ, **db_env(), "PYTHONPATH": str(REPO)}
    for _ in range(2):
        done = subprocess.run([sys.executable, "-m", "shared.storage.init_db"], cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr
        assert "표 6개 확인" in done.stdout and env["DB_PASSWORD"] not in done.stdout + done.stderr
    bare = {k: v for k, v in env.items() if k != "DB_HOST"}
    done = subprocess.run([sys.executable, "-m", "shared.storage.init_db"], cwd=REPO, env=bare, capture_output=True, text=True, timeout=60)
    assert done.returncode == 2 and "DB_HOST" in done.stderr


def test_missing_tables_say_how_to_create_them(db):
    with pytest.raises(StorageError) as err:
        db.run(lambda c: c.execute("SELECT 1 FROM no_such_table_ic26").fetchall())
    assert "init_db" in str(err.value)
    db.ping()      # 표가 없다는 오류가 DB 를 '꺼진 것'으로 취급하지는 않는다


def _unused_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_unreachable_db_fails_fast_cleanly_and_never_prints_the_password(caplog):
    """접속할 수 없을 때: 짧은 시간 안에 StorageError. 비밀번호는 오류 글과 로그 어디에도 나오지 않는다. 바로 이어진 요청은 기다리지 않는다."""
    pytest.importorskip("psycopg_pool")          # 드라이버가 없는 환경에서는 건너뜀 (접속할 DB 는 필요 없음)
    from shared.storage.pg import Database
    password = "S3cret-pw!-unit-test"
    cfg = DbConfig(host="127.0.0.1", port=_unused_port(), dbname="x", user="u", password=password,
                   connect_timeout=2.0, retry_after=5.0)
    db = Database(cfg, app_name="ic26-test-down").open()
    try:
        with caplog.at_level(logging.DEBUG):
            started = time.monotonic()
            with pytest.raises(StorageError) as first:
                db.reviews.list("s", "v")
            waited = time.monotonic() - started
            assert waited < 6, waited
            started = time.monotonic()
            with pytest.raises(StorageError) as second:
                db.card_reasons.get("s", "c", "k")
            assert time.monotonic() - started < 0.5         # 실패 직후에는 DB 를 부르지 않고 바로 오류
        for text in (str(first.value), str(second.value), caplog.text, repr(db)):
            assert password not in text
    finally:
        db.close()


@pytest.mark.skipif(not (HAS_DB and CONTAINER), reason="TEST_DB_CONTAINER 없음 (연결이 끊겼다 돌아오는 시험은 건너뜀)")
def test_pg_recovers_after_the_database_goes_away_and_comes_back():
    """DB 가 잠시 사라졌다(컨테이너 멈춤) 돌아오면, 서비스를 다시 켜지 않아도 다음 요청부터 된다 (장애 전환 흉내)."""
    db = open_test_db("ic26-test-restart", connect_timeout=2.0, retry_after=1.0)
    sid, v = uid("store"), uid("v")
    try:
        db.approvals.save(sid, v, entry("d1"))
        assert len(db.approvals.list(sid, v)) == 1
        docker_ctl(CONTAINER, "stop")
        try:
            with pytest.raises(StorageError):
                db.approvals.list(sid, v)                       # 끊긴 연결은 StorageError 로 알려 줌 (500 이 아님)
            with pytest.raises(StorageError):
                db.approvals.save(sid, v, entry("d2"))
        finally:
            docker_ctl(CONTAINER, "start")
        wait_until_ready()
        time.sleep(1.2)                                           # retry_after
        deadline, items = time.monotonic() + 20, None
        while items is None:
            try:
                items = db.approvals.list(sid, v)
            except StorageError:
                assert time.monotonic() < deadline, "DB 가 돌아왔는데도 요청이 계속 실패함"
                time.sleep(0.5)
        assert [i["draft_id"] for i in items] == ["d1"]          # 멈추기 전에 쓴 것이 그대로 있음
        db.approvals.save(sid, v, entry("d3"))                    # 쓰기도 됨
        assert [i["draft_id"] for i in db.approvals.list(sid, v)] == ["d1", "d3"]
    finally:
        db.close()


def test_wrong_password_is_reported_without_leaking_it(caplog):
    cfg = db_config(password="wrong-pw-Zq91", connect_timeout=2.0) if HAS_DB else None
    if cfg is None:
        pytest.skip("TEST_DB_HOST 없음 (PostgreSQL 시험은 건너뜀)")
    from shared.storage.pg import Database
    db = Database(cfg, app_name="ic26-test-badpw").open()
    try:
        with caplog.at_level(logging.DEBUG), pytest.raises(StorageError) as err:
            db.approvals.list("s", "v")
        assert "wrong-pw-Zq91" not in str(err.value) + caplog.text + repr(db)
    finally:
        db.close()
