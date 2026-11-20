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


DETAIL = {"draft_text": "AI 원문", "checks": {"no_bad_number": True, "no_bad_promise": False, "used_fallback": True},
          "used_fallback": True, "style": "haeyo"}


def test_approvals_store_draft_detail_without_changing_the_list_shape(backend):
    """이슈 #51 ERD (11/18): 승인 기록에 초안 정보 4칸(draft_text, checks, used_fallback, style). list() 응답 모양은 그대로."""
    sid, v = uid("store"), uid("v")
    backend.approvals.save(sid, v, entry("d1", text="고친 글", edited=True), card_id="card_a", kind="reply_draft", detail=DETAIL)
    backend.approvals.save(sid, v, entry("d2", at="2026-11-14T10:00:01+09:00"), kind="prevention_notice")   # 초안 정보를 모름
    assert set(backend.approvals.list(sid, v)[0]) == {"draft_id", "status", "edited", "text", "approved_at", "mode"}
    rows = {r["draft_id"]: r for r in backend.approvals.details(sid, v)}
    d1, d2 = rows["d1"], rows["d2"]
    assert (d1["card_id"], d1["kind"], d1["text"], d1["draft_text"]) == ("card_a", "reply_draft", "고친 글", "AI 원문")
    assert d1["checks"] == {"no_bad_number": True, "no_bad_promise": False}      # used_fallback 은 따로 칸
    assert d1["used_fallback"] is True and d1["style"] == "haeyo"
    assert (d2["draft_text"], d2["checks"], d2["used_fallback"], d2["style"]) == (None, {}, False, None)   # 모르면 빈 값


def test_approvals_detail_rules_on_reapprove_and_bad_values(backend):
    sid, v = uid("store"), uid("v")
    backend.approvals.save(sid, v, entry("d1"), detail=DETAIL)
    backend.approvals.save(sid, v, entry("d1", text="다시", at="2026-11-14T10:00:05+09:00"))            # 정보 없이 다시 승인 → 앞의 것을 둠
    d = backend.approvals.details(sid, v)[0]
    assert (d["text"], d["draft_text"], d["used_fallback"], d["style"]) == ("다시", "AI 원문", True, "haeyo")
    backend.approvals.save(sid, v, entry("d1"), detail={"draft_text": None, "checks": {"a": True}, "style": "반말"})
    d = backend.approvals.details(sid, v)[0]
    assert d["draft_text"] == "AI 원문"                                  # 원문을 모르면 앞의 원문을 둠
    assert (d["checks"], d["used_fallback"], d["style"]) == ({"a": True}, False, None)   # 모르는 말투는 비움
    backend.approvals.save(sid, v, entry("d2"), detail={"checks": {"x": "yes", "y": True}, "used_fallback": "true",
                                                      "draft_text": "가" * 5000})
    d2 = backend.approvals.details(sid, v)[1]
    assert d2["checks"] == {"y": True} and d2["used_fallback"] is False and len(d2["draft_text"]) == 4000


def test_approvals_clear_and_delete_also_drop_the_detail(backend):
    s1, a, b = uid("store"), uid("v"), uid("v")
    for d in ("d1", "d2", "d3"):
        backend.approvals.save(s1, a, entry(d), detail={**DETAIL, "draft_text": f"원문 {d}"})
    backend.approvals.save(s1, b, entry("d1"), detail=DETAIL)
    assert backend.approvals.delete(s1, a, ["d2"]) == 1
    assert [(r["draft_id"], r["draft_text"]) for r in backend.approvals.details(s1, a)] == [("d1", "원문 d1"), ("d3", "원문 d3")]
    backend.approvals.save(s1, a, entry("d2"))                           # 지운 뒤 다시 승인: 옛 초안 정보가 되살아나지 않음
    assert backend.approvals.details(s1, a)[-1]["draft_text"] is None
    assert backend.approvals.clear(s1, a) == 3 and backend.approvals.details(s1, a) == []
    backend.approvals.save(s1, a, entry("d1"))
    assert backend.approvals.details(s1, a)[0]["draft_text"] is None     # clear 뒤에도 되살아나지 않음
    assert backend.approvals.details(s1, b)[0]["draft_text"] == "AI 원문"   # 다른 방문자 것은 그대로


def test_users_create_login_and_stores(backend):
    """로그인 (5차 회의 11/18): 계정·가진 가게·로그인 아이디 중복. 두 구현이 같은 모양으로 돌려준다."""
    from shared.storage.errors import DuplicateLogin
    uid_ = uuid.uuid4().hex[:16]
    login = "owner" + uid_[:8]
    made = backend.users.create(uid_, login.upper(), "scrypt$x", "김사장", ["store_basak", "store_ongi"])
    assert set(made) == {"user_id", "login_id", "display_name", "created_at"} and made["login_id"] == login
    assert backend.users.get(uid_)["display_name"] == "김사장"
    found = backend.users.by_login(login.upper())
    assert found["user_id"] == uid_ and found["password_hash"] == "scrypt$x"
    assert "password_hash" not in backend.users.get(uid_)
    assert backend.users.stores(uid_) == ["store_basak", "store_ongi"]          # 고른 순서 그대로
    with pytest.raises(DuplicateLogin):
        backend.users.create(uuid.uuid4().hex[:16], login, "scrypt$y", "다른 사람", ["store_ongi"])
    assert backend.users.by_login("nobody-" + uid_) is None and backend.users.get("nobody") is None


def test_users_ensure_is_idempotent(backend):
    uid_ = "demo-" + uuid.uuid4().hex[:12]
    first = backend.users.ensure(uid_, uid_, "!", "시연 사장님", ["store_ongi", "store_basak", "store_mongle"])
    again = backend.users.ensure(uid_, uid_, "!", "시연 사장님", ["store_ongi", "store_basak", "store_mongle"])
    assert first["user_id"] == again["user_id"] == uid_
    assert backend.users.stores(uid_) == ["store_ongi", "store_basak", "store_mongle"]


def test_users_ensure_refuses_a_login_taken_by_another_user(backend):
    """다른 계정이 그 로그인 아이디를 이미 쓰면 DuplicateLogin (PG 의 UniqueViolation 이 500 으로 새지 않게, 11/19)."""
    from shared.storage.errors import DuplicateLogin
    demo_id = "demo-" + uuid.uuid4().hex[:12]
    other = uuid.uuid4().hex[:16]
    backend.users.create(other, demo_id, "scrypt$x", "먼저 가입", ["store_ongi"])
    with pytest.raises(DuplicateLogin):
        backend.users.ensure(demo_id, demo_id, "!", "시연 사장님", ["store_ongi", "store_basak", "store_mongle"])
    assert backend.users.get(demo_id) is None and backend.users.stores(demo_id) == []   # 아무것도 남지 않음
    assert backend.users.by_login(demo_id)["user_id"] == other
    assert backend.users.stores(other) == ["store_ongi"]


def test_pg_labels_delete_many_removes_only_those_keys(db):
    """계정 초기화·탈퇴가 지우는 리뷰들의 분류 결과만 지운다 (11/19). 없는 키·빈 입력은 0."""
    keep, gone1, gone2 = (uid("k") for _ in range(3))
    result = {"sentiment": "negative", "topics": [], "summary": "요약"}
    db.labels.put_many({keep: result, gone1: result, gone2: result}, prompt_version="c3-v7", model="HCX-005")
    assert db.labels.delete_many([]) == 0
    assert db.labels.delete_many({gone1, gone2, uid("none")}) == 2
    assert db.labels.get_many([keep, gone1, gone2]) == {keep: result}
    assert db.labels.delete_many([gone1]) == 0                                       # 여러 번 불러도 안전


def test_users_delete_and_auth_sessions_delete_user(backend):
    """회원 탈퇴 (11/19): 세션을 사장님 단위로 지우고 계정을 지운다. 같은 아이디로 다시 가입할 수 있다. 다른 사장님은 그대로."""
    from datetime import datetime, timedelta, timezone
    soon = datetime.now(timezone.utc) + timedelta(days=7)
    me, them = uuid.uuid4().hex[:16], uuid.uuid4().hex[:16]
    login = "w" + me[:10]
    backend.users.create(me, login, "scrypt$x", "사장", ["store_ongi", "store_basak"])
    backend.users.create(them, "w" + them[:10], "scrypt$x", "옆집", ["store_ongi"])
    mine, theirs = ["h" + uuid.uuid4().hex for _ in range(2)], "h" + uuid.uuid4().hex
    for h in mine:
        backend.auth_sessions.create(h, me, "store_ongi", soon)
    backend.auth_sessions.create(theirs, them, "store_ongi", soon)
    assert backend.auth_sessions.delete_user(me) == 2
    assert [backend.auth_sessions.get(h) for h in mine] == [None, None]
    assert backend.auth_sessions.get(theirs)["user_id"] == them
    assert backend.users.delete(me) is True
    assert backend.users.get(me) is None and backend.users.by_login(login) is None and backend.users.stores(me) == []
    assert backend.users.delete(me) is False and backend.auth_sessions.delete_user(me) == 0     # 여러 번 불러도 안전
    assert backend.users.get(them) is not None and backend.users.stores(them) == ["store_ongi"]
    again = uuid.uuid4().hex[:16]
    assert backend.users.create(again, login, "scrypt$y", "새 사장", ["store_mongle"])["login_id"] == login
    assert backend.users.by_login(login)["user_id"] == again


def test_pg_users_delete_cascades_to_stores_and_sessions(db):
    from datetime import datetime, timedelta, timezone
    me = uuid.uuid4().hex[:16]
    db.users.create(me, "c" + me[:10], "scrypt$x", "사장", ["store_ongi", "store_basak"])
    h = "h" + uuid.uuid4().hex
    db.auth_sessions.create(h, me, "store_ongi", datetime.now(timezone.utc) + timedelta(days=7))
    assert db.users.delete(me) is True
    assert db.auth_sessions.get(h) is None and db.users.stores(me) == []


def test_auth_sessions_create_get_switch_delete_and_expire(backend):
    from datetime import datetime, timedelta, timezone
    uid_ = uuid.uuid4().hex[:16]
    backend.users.create(uid_, "s" + uid_[:10], "scrypt$x", "사장", ["store_ongi", "store_basak"])
    live, old = "h" + uuid.uuid4().hex, "h" + uuid.uuid4().hex
    backend.auth_sessions.create(live, uid_, "store_ongi", datetime.now(timezone.utc) + timedelta(days=7))
    backend.auth_sessions.create(old, uid_, "store_ongi", datetime.now(timezone.utc) - timedelta(seconds=1))
    got = backend.auth_sessions.get(live)
    assert (got["user_id"], got["active_store_id"]) == (uid_, "store_ongi")
    assert backend.auth_sessions.get(old) is None                                   # 지난 세션은 없는 것
    assert backend.auth_sessions.set_store(live, "store_basak") is True
    assert backend.auth_sessions.get(live)["active_store_id"] == "store_basak"
    assert backend.auth_sessions.set_store(old, "store_basak") is False
    assert backend.auth_sessions.delete(live) is True and backend.auth_sessions.get(live) is None
    assert backend.auth_sessions.delete(live) is False


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


def test_reports_are_kept_per_visitor(backend):
    """같은 가게·같은 기간이어도 방문자(사장님)마다 따로 저장된다 (11/20). 방문자를 안 주면 공용 자리."""
    sid = uid("store")
    a, b = "u-" + uid("a"), "u-" + uid("b")
    backend.reports.save(sid, "weekly", "2026-11-09", "2026-11-15", numbers={"n": 1}, body_text="a", evidence_ids=[],
                         prompt_version="p1", visitor_id=a)
    backend.reports.save(sid, "weekly", "2026-11-09", "2026-11-15", numbers={"n": 2}, body_text="b", evidence_ids=[],
                         prompt_version="p1", visitor_id=b)
    got_a = backend.reports.get(sid, "weekly", "2026-11-09", "2026-11-15", visitor_id=a)
    assert got_a["numbers"] == {"n": 1} and got_a["visitor_id"] == a
    assert backend.reports.get(sid, "weekly", "2026-11-09", "2026-11-15", visitor_id=b)["numbers"] == {"n": 2}
    assert backend.reports.get(sid, "weekly", "2026-11-09", "2026-11-15") is None            # 공용 자리에는 없음
    assert [r["body_text"] for r in backend.reports.list(sid, visitor_id=a)] == ["a"]
    assert backend.reports.list(sid) == []
    # 다시 만들기 = 같은 방문자·같은 기간 덮어쓰기 (다른 방문자는 그대로)
    backend.reports.save(sid, "weekly", "2026-11-09", "2026-11-15", numbers={"n": 3}, body_text="a2", evidence_ids=[],
                         prompt_version="p1", visitor_id=a)
    assert [r["numbers"] for r in backend.reports.list(sid, visitor_id=a)] == [{"n": 3}]
    assert backend.reports.get(sid, "weekly", "2026-11-09", "2026-11-15", visitor_id=b)["numbers"] == {"n": 2}


def test_reports_count_across_stores_and_delete_one_store(backend):
    s1, s2, other = uid("store"), uid("store"), uid("store")
    me, you = "u-" + uid("me"), "u-" + uid("you")
    for sid, kind, start, end in [(s1, "weekly", "2026-11-02", "2026-11-08"), (s1, "weekly", "2026-11-09", "2026-11-15"),
                                  (s2, "weekly", "2026-11-09", "2026-11-15"), (s2, "monthly", "2026-10-01", "2026-10-31"),
                                  (other, "monthly", "2026-11-01", "2026-11-30")]:
        backend.reports.save(sid, kind, start, end, numbers={}, body_text="", evidence_ids=[], prompt_version="p1", visitor_id=me)
    backend.reports.save(s1, "weekly", "2026-11-02", "2026-11-08", numbers={}, body_text="", evidence_ids=[], prompt_version="p2",
                         visitor_id=me)                                  # 같은 기간의 다른 판은 하나로 센다
    backend.reports.save(s1, "monthly", "2026-11-01", "2026-11-30", numbers={}, body_text="", evidence_ids=[], prompt_version="p1",
                         visitor_id=you)
    assert backend.reports.count([s1, s2], me) == {"weekly": 3, "monthly": 1}
    assert backend.reports.count([s1, s2], you) == {"weekly": 0, "monthly": 1}
    assert backend.reports.count([], me) == {"weekly": 0, "monthly": 0}
    assert backend.reports.delete(s1, me) == 3
    assert backend.reports.count([s1, s2], me) == {"weekly": 1, "monthly": 1}
    assert backend.reports.list(s1, visitor_id=you) and backend.reports.delete(s1, me) == 0


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


def test_pg_approval_detail_columns_have_erd_types(db):
    """이슈 #51 합의: draft_text TEXT, checks JSONB NOT NULL DEFAULT '{}', used_fallback BOOLEAN NOT NULL DEFAULT FALSE, style TEXT."""
    cols = db.run(lambda c: c.execute(
        "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'approvals' "
        "AND column_name IN ('draft_text', 'checks', 'used_fallback', 'style')").fetchall())
    got = {r["column_name"]: (r["data_type"], r["is_nullable"], (r["column_default"] or "").lower()) for r in cols}
    assert got["draft_text"][:2] == ("text", "YES") and got["style"][:2] == ("text", "YES")
    assert got["checks"][:2] == ("jsonb", "NO") and got["checks"][2].startswith("'{}'::jsonb")
    assert got["used_fallback"][:2] == ("boolean", "NO") and got["used_fallback"][2] == "false"
    sid, v = uid("store"), uid("v")
    db.approvals.save(sid, v, entry("d1"), detail=DETAIL)
    row = db.run(lambda c: c.execute("SELECT draft_text, checks, used_fallback, style FROM approvals WHERE store_id=%s", (sid,)).fetchone())
    assert row == {"draft_text": "AI 원문", "checks": {"no_bad_number": True, "no_bad_promise": False}, "used_fallback": True, "style": "haeyo"}


def test_pg_old_approvals_table_gets_the_new_columns_and_keeps_rows(db):
    """11/18 전에 만든 DB: 칸 4개가 없는 approvals 표에 init_db 를 다시 돌리면 칸이 더해지고 기록은 남는다.
    init_db 전에는 칸 없이 옛 방식으로 저장된다 (승인이 빠지지 않음). 시험용 스키마 하나를 따로 만들어 본다."""
    from psycopg import sql
    from shared.storage.init_db import create_tables
    schema = uid("old").replace("-", "_").lower()
    db.run(lambda c: c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))))
    scoped = _scoped_db(schema)
    try:
        def make_old(c):
            c.execute("CREATE TABLE approvals (id BIGSERIAL PRIMARY KEY, store_id TEXT NOT NULL, visitor_id TEXT NOT NULL, "
                      "draft_id TEXT NOT NULL, card_id TEXT, kind TEXT, status TEXT NOT NULL DEFAULT 'approved', "
                      "approved_text TEXT NOT NULL, edited BOOLEAN NOT NULL DEFAULT FALSE, approved_at TIMESTAMPTZ NOT NULL, "
                      "mode TEXT NOT NULL, saved_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (store_id, visitor_id, draft_id))")
            c.execute("INSERT INTO approvals (store_id, visitor_id, draft_id, approved_text, approved_at, mode) "
                      "VALUES ('s', 'v', 'd_old', '옛 글', now(), 'live')")
        scoped.run(make_old)
        # 칸이 없을 때 저장 → 옛 방식으로 들어감 (승인이 빠지지 않음)
        scoped.approvals.save("s", "v", entry("d_new"), detail=DETAIL)
        names = scoped.run(lambda c: [r["draft_id"] for r in c.execute("SELECT draft_id FROM approvals ORDER BY id").fetchall()])
        assert names == ["d_old", "d_new"]
        create_tables(scoped)                       # init_db 다시 → ALTER ADD COLUMN IF NOT EXISTS
        create_tables(scoped)                       # 두 번째도 안전
        scoped.approvals._legacy_until = 0.0
        scoped.approvals.save("s", "v", entry("d_after"), detail=DETAIL)
        rows = {r["draft_id"]: r for r in scoped.approvals.details("s", "v")}
        assert rows["d_old"]["text"] == "옛 글" and rows["d_old"]["checks"] == {} and rows["d_old"]["used_fallback"] is False
        assert rows["d_after"]["draft_text"] == "AI 원문" and rows["d_after"]["style"] == "haeyo"
    finally:
        scoped.close()
        db.run(lambda c: c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))))


def test_pg_old_reports_table_gets_visitor_column_and_per_visitor_key(db):
    """11/20 전에 만든 reports 표 (방문자 칸 없음, 유일 조건이 (가게, 종류, 기간, 판)): init_db 를 다시 돌리면 visitor_id 칸이 생기고,
    옛 유일 조건이 빠져 같은 기간을 사장님마다 따로 저장할 수 있다. 있던 행은 공용('common') 자리로 남는다. 두 번째도 안전."""
    from psycopg import sql
    from shared.storage.init_db import create_tables
    schema = uid("oldrep").replace("-", "_").lower()
    db.run(lambda c: c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))))
    scoped = _scoped_db(schema)
    try:
        def make_old(c):
            c.execute("CREATE TABLE reports (id BIGSERIAL PRIMARY KEY, store_id TEXT NOT NULL, "
                      "period_kind TEXT NOT NULL CHECK (period_kind IN ('weekly', 'monthly')), period_start DATE NOT NULL, "
                      "period_end DATE NOT NULL, numbers JSONB NOT NULL DEFAULT '{}'::jsonb, body_text TEXT NOT NULL DEFAULT '', "
                      "evidence_ids TEXT[] NOT NULL DEFAULT '{}', prompt_version TEXT NOT NULL, "
                      "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), CHECK (period_end >= period_start), "
                      "UNIQUE (store_id, period_kind, period_start, period_end, prompt_version))")
            c.execute("CREATE INDEX reports_by_period ON reports (store_id, period_kind, period_start DESC)")
            c.execute("INSERT INTO reports (store_id, period_kind, period_start, period_end, prompt_version) "
                      "VALUES ('s', 'weekly', '2026-11-02', '2026-11-08', 'p1')")
        scoped.run(make_old)
        create_tables(scoped)
        create_tables(scoped)                       # 두 번째도 안전 (DO 블록은 지울 것이 없음)
        uniques = scoped.run(lambda c: [r["n"] for r in c.execute(
            "SELECT pg_get_constraintdef(oid) AS n FROM pg_constraint WHERE conrelid = 'reports'::regclass AND contype = 'u'").fetchall()])
        assert uniques == []                        # 옛 유일 조건은 빠지고, 유일 색인 reports_one_per_period 가 대신한다
        assert scoped.reports.get("s", "weekly", "2026-11-02", "2026-11-08")["visitor_id"] == "common"   # 있던 행
        for v, n in (("u-a", 1), ("u-b", 2), ("u-a", 3)):
            scoped.reports.save("s", "weekly", "2026-11-02", "2026-11-08", numbers={"n": n}, body_text="", evidence_ids=[],
                                prompt_version="p1", visitor_id=v)
        assert scoped.reports.get("s", "weekly", "2026-11-02", "2026-11-08", visitor_id="u-a")["numbers"] == {"n": 3}
        assert scoped.reports.get("s", "weekly", "2026-11-02", "2026-11-08", visitor_id="u-b")["numbers"] == {"n": 2}
        assert scoped.run(lambda c: c.execute("SELECT count(*) AS n FROM reports").fetchone()["n"]) == 3
    finally:
        scoped.close()
        db.run(lambda c: c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))))


def _scoped_db(schema: str):
    """search_path 를 schema 로 둔 연결 풀 (시험용 따로 만든 스키마 안의 표만 봄)."""
    from shared.storage.pg import Database
    db = Database(db_config(), app_name="ic26-test-scoped")
    original = db.run

    def run(work):
        def scoped(conn):
            conn.execute(f'SET LOCAL search_path TO "{schema}"')
            return work(conn)
        return original(scoped)
    db.run = run
    return db.open()


def test_init_db_twice_is_safe_and_creates_every_table(db):
    from shared.storage.init_db import create_tables
    from shared.storage.pg import TABLES
    assert create_tables(db) == sorted(TABLES) and create_tables(db) == sorted(TABLES)


def test_init_db_command_runs_twice_and_without_db_host(db):
    env = {**os.environ, **db_env(), "PYTHONPATH": str(REPO)}
    for _ in range(2):
        done = subprocess.run([sys.executable, "-m", "shared.storage.init_db"], cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr
        assert "표 13개 확인" in done.stdout and env["DB_PASSWORD"] not in done.stdout + done.stderr
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


# ── 맞춤 마케팅 기록 (11/19, marketing_sessions·coupon_runs) — 두 구현이 같은 약속 ─────────
def mk_session(rid=None, **kw):
    return {"table": "marketing_sessions", "id": rid or uuid.uuid4().hex, "feature": "survey", "goal": None, "answers": {},
            "decision": "proposed", "result": {}, "parent_id": None, "created_at": "2026-11-19T10:00:00+09:00", **kw}


def mk_coupon(rid=None, **kw):
    return {"table": "coupon_runs", "id": rid or uuid.uuid4().hex, "menu_name": None, "discount_krw": 2000, "issued": 100,
            "used": 10, "avg_order_krw": 15000, "margin_pct": 30, "period_start": None, "period_end": None,
            "created_at": "2026-11-19T10:00:00+09:00", **kw}


def test_marketing_add_list_keeps_order_shape_and_types(backend):
    sid, v = uid("store"), uid("v")
    s1 = backend.marketing.add(sid, v, mk_session(answers={"goal": "재방문", "n": [1, 2]}, result={"title": "제목"}))
    c1 = backend.marketing.add(sid, v, mk_coupon(margin_pct=12.5, period_start="2026-11-01", period_end="2026-11-14",
                                                 created_at="2026-11-19T01:02:03+00:00"))
    s2 = backend.marketing.add(sid, v, mk_session(decision="approved", parent_id=s1["id"]))
    rows = backend.marketing.list(sid, v)
    assert rows == [s1, c1, s2]                                        # 넣은 순서, 돌려준 모양 그대로
    assert list(rows[0]) == ["table", "id", "store_id", "feature", "goal", "answers", "decision", "result", "parent_id",
                             "created_at", "visitor_id"]
    assert list(rows[1]) == ["table", "id", "store_id", "menu_name", "discount_krw", "issued", "used", "avg_order_krw",
                             "margin_pct", "period_start", "period_end", "created_at", "visitor_id"]
    assert rows[0]["answers"] == {"goal": "재방문", "n": [1, 2]} and rows[0]["store_id"] == sid and rows[0]["visitor_id"] == v
    assert rows[1]["created_at"] == "2026-11-19T10:02:03+09:00"         # 한국 시간 ISO
    assert (rows[1]["margin_pct"], rows[1]["period_start"], rows[1]["period_end"]) == (12.5, "2026-11-01", "2026-11-14")
    whole = backend.marketing.add(sid, v, mk_coupon(margin_pct=30))
    assert backend.marketing.list(sid, v)[-1]["margin_pct"] == 30 and type(whole["margin_pct"]) is int   # 30.0 이 아니라 30


def test_marketing_is_separate_per_visitor_and_store_and_common_has_no_visitor_key(backend):
    sid, other, v, w = uid("store"), uid("store"), uid("v"), uid("w")
    backend.marketing.add(sid, v, mk_session())
    backend.marketing.add(sid, w, mk_coupon())
    backend.marketing.add(other, v, mk_session())
    common = backend.marketing.add(sid, COMMON_VISITOR, mk_session())
    assert "visitor_id" not in common and backend.marketing.list(sid, COMMON_VISITOR) == [common]
    assert [r["table"] for r in backend.marketing.list(sid, v)] == ["marketing_sessions"]
    assert [r["table"] for r in backend.marketing.list(sid, w)] == ["coupon_runs"]
    assert backend.marketing.list(uid("store"), v) == []


def test_marketing_delete_removes_only_that_visitor_in_that_store_from_both_tables(backend):
    sid, other, v, w = uid("store"), uid("store"), uid("v"), uid("w")
    for row in (mk_session(), mk_coupon(), mk_session()):
        backend.marketing.add(sid, v, row)
    backend.marketing.add(sid, w, mk_coupon())
    backend.marketing.add(other, v, mk_session())
    assert backend.marketing.delete(sid, v) == 3
    assert backend.marketing.list(sid, v) == [] and backend.marketing.delete(sid, v) == 0
    assert len(backend.marketing.list(sid, w)) == 1 and len(backend.marketing.list(other, v)) == 1


@pytest.mark.parametrize("bad", [
    mk_coupon(discount_krw=2**31), mk_coupon(issued=-2**31 - 1), mk_coupon(used="10"), mk_coupon(issued=True),
    mk_coupon(margin_pct=float("nan")), mk_coupon(margin_pct="30"), mk_coupon(period_start="어제"),
    mk_coupon(period_start="2026-11-14", period_end="2026-11-01"), mk_session(feature=None), mk_session(answers=[1]),
    mk_session(result={"x": object()}), mk_session(table="approvals"), mk_session(rid="x" * 65)])
def test_marketing_rejects_bad_rows_the_same_way(backend, bad):
    sid, v = uid("store"), uid("v")
    with pytest.raises(ValueError):
        backend.marketing.add(sid, v, bad)
    assert backend.marketing.list(sid, v) == []


def test_marketing_same_id_twice_is_a_value_error(backend):
    sid, v, rid = uid("store"), uid("v"), uuid.uuid4().hex
    backend.marketing.add(sid, v, mk_session(rid))
    with pytest.raises(ValueError):
        backend.marketing.add(sid, uid("v"), mk_session(rid))          # 같은 표에 같은 id (다른 방문자여도)
    assert len(backend.marketing.list(sid, v)) == 1


def test_pg_marketing_two_servers_see_the_same_records(db):
    other = open_test_db("ic26-test-second-server")
    try:
        sid, v = uid("store"), uid("v")
        row = db.marketing.add(sid, v, mk_coupon())
        assert other.marketing.list(sid, v) == [row]
        assert other.marketing.delete(sid, v) == 1 and db.marketing.list(sid, v) == []
    finally:
        other.close()


def test_pg_marketing_columns_have_erd_types(db):
    rows = db.run(lambda c: c.execute(
        "SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name IN ('marketing_sessions', 'coupon_runs')").fetchall())
    cols = {(r["table_name"], r["column_name"]): (r["data_type"], r["is_nullable"]) for r in rows}
    assert cols[("marketing_sessions", "answers")] == ("jsonb", "NO")
    assert cols[("marketing_sessions", "created_at")] == ("timestamp with time zone", "NO")
    assert cols[("marketing_sessions", "visitor_id")] == ("text", "NO")
    assert cols[("coupon_runs", "discount_krw")] == ("integer", "NO")
    assert cols[("coupon_runs", "margin_pct")] == ("double precision", "YES")
    assert cols[("coupon_runs", "period_start")] == ("date", "YES")


# ── 리뷰의 상태·답글 기록 (11/19, PostgreSQL 만 — DB 가 없으면 리뷰 분석 서비스가 파일을 쓴다) ──────────────
def test_pg_review_records_merge_fields_and_keep_history_in_order(db):
    sid, v = uid("store"), uid("visitor")
    assert db.review_records.load(sid, v) == {}
    first = db.review_records.update(sid, v, "rv_x_paste_001", {"source": "capture", "received_at": "2026-11-14T19:02:11+09:00"})
    assert first == {"source": "capture", "received_at": "2026-11-14T19:02:11+09:00"}        # 쓴 칸만, 한국 시간 그대로
    second = db.review_records.update(sid, v, "rv_x_paste_001", {"status": "drafted", "status_at": "2026-11-14T19:05:00+09:00"},
                                      {"status": "drafted", "at": "2026-11-14T19:05:00+09:00"})
    assert second == {"source": "capture", "received_at": "2026-11-14T19:02:11+09:00", "status": "drafted",
                      "status_at": "2026-11-14T19:05:00+09:00",
                      "history": [{"status": "drafted", "at": "2026-11-14T19:05:00+09:00"}]}
    third = db.review_records.update(
        sid, v, "rv_x_paste_001",
        {"status": "replied", "status_at": "2026-11-14T10:10:00+00:00", "reply": {"text": "죄송합니다", "replied_at": "2026-11-14T10:10:00+00:00"}},
        {"status": "replied", "at": "2026-11-14T10:10:00+00:00"})
    assert third["reply"] == {"text": "죄송합니다", "replied_at": "2026-11-14T19:10:00+09:00"}   # 다른 시간대로 줘도 한국 시간으로
    assert [e["status"] for e in third["history"]] == ["drafted", "replied"] and third["source"] == "capture"
    # 답글 없이 상태만 바꾸면 예전 답글은 그대로 (파일 방식의 row.update 와 같다)
    fourth = db.review_records.update(sid, v, "rv_x_paste_001", {"status": "skipped", "status_at": "2026-11-14T19:20:00+09:00"},
                                      {"status": "skipped", "at": "2026-11-14T19:20:00+09:00"})
    assert fourth["reply"]["text"] == "죄송합니다" and fourth["status"] == "skipped" and len(fourth["history"]) == 3
    assert db.review_records.load(sid, v) == {"rv_x_paste_001": fourth}


def test_pg_review_records_are_separate_per_store_visitor_and_review(db):
    s1, s2, a, b = uid("store"), uid("store"), uid("visitor"), uid("visitor")
    event = {"status": "replied", "at": "2026-11-14T19:10:00+09:00"}
    for store, visitor, rid in ((s1, a, "rv_1"), (s1, a, "rv_2"), (s1, b, "rv_1"), (s2, a, "rv_1"), (s1, COMMON_VISITOR, "rv_1")):
        db.review_records.update(store, visitor, rid, {"status": "replied", "status_at": event["at"]}, event)
    assert set(db.review_records.load(s1, a)) == {"rv_1", "rv_2"}
    assert db.review_records.clear(s1, a) == 2 and db.review_records.clear(s1, a) == 0
    assert db.review_records.load(s1, a) == {}
    for store, visitor in ((s1, b), (s2, a), (s1, COMMON_VISITOR)):                       # 다른 방문자·가게·공용은 그대로
        assert db.review_records.load(store, visitor)["rv_1"]["history"] == [event]
    left = db.run(lambda conn: conn.execute("SELECT count(*) AS n FROM review_status_events WHERE store_id = %s AND visitor_id = %s",
                                            (s1, a)).fetchone()["n"])
    assert left == 0                                                                      # 상태 기록도 같이 지워짐 (CASCADE)


def test_pg_review_records_keep_unknown_fields_and_ignore_history_in_fields(db):
    sid, v = uid("store"), uid("visitor")
    row = db.review_records.update(sid, v, "rv_1", {"source": "memo", "order_ref": "A-12", "history": [{"status": "x", "at": "y"}]})
    assert row == {"source": "memo", "order_ref": "A-12"}                                  # 모르는 칸은 extra 에, history 는 event 로만
    row = db.review_records.update(sid, v, "rv_1", {"reply": None, "order_ref": "A-13"})
    assert row == {"source": "memo", "order_ref": "A-13"}


def test_pg_review_records_two_servers_do_not_lose_each_others_updates(db):
    """서버 2대(연결 풀 둘)가 같은 리뷰의 상태를 같이 바꿔도 기록이 하나도 빠지지 않는다 (파일 방식은 서버마다 따로였다)."""
    other = open_test_db("ic26-test-second")
    sid, v, n = uid("store"), uid("visitor"), 12
    errors: list[BaseException] = []

    def work(handle, start):
        try:
            for i in range(start, start + n):
                stamp = f"2026-11-14T19:{i:02d}:00+09:00"
                handle.review_records.update(sid, v, "rv_1", {"status": "drafted", "status_at": stamp}, {"status": "drafted", "at": stamp})
        except BaseException as exc:       # noqa: BLE001 — 시험이 실패 이유를 보이게
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(db, 0)), threading.Thread(target=work, args=(other, n))]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        assert not errors, errors
        seen = other.review_records.load(sid, v)["rv_1"]
        assert len(seen["history"]) == 2 * n and seen == db.review_records.load(sid, v)["rv_1"]
        assert {e["at"] for e in seen["history"]} == {f"2026-11-14T19:{i:02d}:00+09:00" for i in range(2 * n)}
    finally:
        other.close()
