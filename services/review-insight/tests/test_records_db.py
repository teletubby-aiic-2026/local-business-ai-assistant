"""리뷰의 상태·답글 기록을 DB 로 (11/19): DB_HOST 가 있으면 review_records·review_status_events 표, 없으면 예전 파일. CLOVA 는 가짜.

- 같은 순서로 기록하면 파일 방식과 DB 방식이 돌려주는 기록(dict)이 같다.
- 서버 2대(연결 풀 둘)가 같은 기록을 본다 — 파일 방식에서는 서버마다 따로였다 (handoff.md 8절의 위험).
- '붙여넣은 리뷰 지우기'·계정 초기화가 그 방문자의 기록만 DB 에서 지운다 (합성 리뷰에 붙인 '답글 달았음' 포함).
- DB 에 닿지 못하면 503 (조용히 '기록 없음'으로 보이지 않게).
- 'pg' 시험은 TEST_DB_HOST 가 있을 때만 돈다.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import classify, records, service, storage
from app.classify import Classifier

API = "/api/review-insight"
KST = timezone(timedelta(hours=9))
SAMPLE = "rv_ongi_001"                 # 합성(기본) 리뷰: reviews 표에 줄이 없어도 기록은 붙는다


@pytest.fixture(autouse=True)
def tmp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(classify, "REPLAY_FILE", tmp_path / "replay.json")
    monkeypatch.setattr(classify, "RUNTIME_CACHE", tmp_path / "runtime.json")
    monkeypatch.setattr(classify, "USAGE_LOG", tmp_path / "logs" / "llm_usage.jsonl")


@pytest.fixture
def client(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_classifier", Classifier("mock"))
    return TestClient(main.app)


@pytest.fixture
def db():
    storage._import_shared()
    from shared.storage.testing import open_test_db
    found = open_test_db("ic26-review-records")
    if found is None:
        pytest.skip("TEST_DB_HOST 없음 (PostgreSQL 시험은 건너뜀)")
    yield found
    found.close()


def visitor() -> str:
    return "u-" + uuid.uuid4().hex[:16]


def story(v: str) -> dict:
    """붙여넣기(캡처) 1건 → 그 리뷰에 답글 → 합성 리뷰는 건너뜀 → 다시 답글. 시각을 정해 줘서 두 방식의 결과를 그대로 견준다."""
    t0 = datetime(2026, 11, 14, 19, 0, 0, tzinfo=KST)
    r = service.add_review("포장이 새서 국물이 다 흘렀어요", 2, "baemin", t0, "store_ongi", v, source="capture",
                           received_at=t0 + timedelta(minutes=2))
    service.set_status("store_ongi", v, r.review_id, "drafted", at="2026-11-14T19:05:00+09:00")
    service.set_status("store_ongi", v, r.review_id, "replied", reply_text="  죄송합니다. 포장을 다시 확인하겠습니다.  ",
                       at="2026-11-14T10:10:00+00:00")                       # 다른 시간대로 줘도 한국 시간으로 남는다
    service.set_status("store_ongi", v, SAMPLE, "skipped", at="2026-11-14T19:20:00+09:00")
    service.set_status("store_ongi", v, SAMPLE, "replied", reply_text="다음엔 꼭 챙기겠습니다.", at="2026-11-14T19:30:00+09:00")
    return records.load("store_ongi", v)


def test_file_mode_is_unchanged_and_has_the_documented_shape():
    v = visitor()
    got = story(v)
    assert got["rv_ongi_paste_001"] == {
        "source": "capture", "received_at": "2026-11-14T19:02:00+09:00", "status": "replied", "status_at": "2026-11-14T19:10:00+09:00",
        "reply": {"text": "죄송합니다. 포장을 다시 확인하겠습니다.", "replied_at": "2026-11-14T19:10:00+09:00"},
        "history": [{"status": "drafted", "at": "2026-11-14T19:05:00+09:00"}, {"status": "replied", "at": "2026-11-14T19:10:00+09:00"}]}
    assert [e["status"] for e in got[SAMPLE]["history"]] == ["skipped", "replied"]
    assert (service.RUNTIME / "visitors" / v / "records_store_ongi.json").is_file()      # DB 가 없으면 예전처럼 파일


def test_pg_records_have_the_same_shape_as_the_file_mode(db, tmp_path):
    in_files = story(visitor())
    storage.use(db)
    v = visitor()
    in_db = story(v)
    assert in_db == in_files                                                             # 값·칸이 같다 (방문자만 다름)
    assert not (service.RUNTIME / "visitors" / v).exists()                               # DB 방식은 기록 파일을 만들지 않는다
    timeline = service.Timeline(Classifier("mock"), "store_ongi", v)
    row = next(r for r in timeline.rows if r["review_id"] == SAMPLE)
    assert row["status"] == "replied" and [e["status"] for e in row["history"]] == ["skipped", "replied"]


def test_pg_two_servers_see_the_same_status_and_reply(client, db):
    """서버 A 에서 답글을 승인하면 서버 B 의 리뷰 조회에 그 상태와 답글이 보인다."""
    storage._import_shared()
    from shared.storage.testing import open_test_db
    other = open_test_db("ic26-review-records-2")
    v = visitor()
    try:
        storage.use(db)                                                                  # 서버 A
        res = client.post(f"{API}/reviews/{SAMPLE}/status", json={"status": "replied", "reply_text": "죄송합니다.", "visitor_id": v})
        assert res.status_code == 200, res.text
        storage.use(other)                                                               # 서버 B
        seen = client.get(f"{API}/reviews/{SAMPLE}?visitor_id={v}").json()["review"]
        assert seen["status"] == "replied" and seen["reply"]["text"] == "죄송합니다."
        listed = next(r for r in client.get(f"{API}/reviews?visitor_id={v}").json()["items"] if r["review_id"] == SAMPLE)
        assert listed["reply"]["text"] == "죄송합니다."
        fresh = client.get(f"{API}/reviews/{SAMPLE}?visitor_id={visitor()}").json()["review"]
        assert fresh["reply"] is None                                                    # 다른 방문자에게는 안 보인다
    finally:
        storage.use(db)
        other.close()


def test_pg_clearing_pasted_reviews_removes_only_that_visitors_records(client, db):
    storage.use(db)
    a, b = visitor(), visitor()
    for v in (a, b):
        rid = client.post(f"{API}/reviews", json={"store_id": "store_ongi", "text": "국물이 샜어요 " + v, "rating": 1,
                                                  "visitor_id": v}).json()["review"]["review_id"]
        client.post(f"{API}/reviews/{rid}/status", json={"status": "replied", "reply_text": "죄송합니다.", "visitor_id": v})
        client.post(f"{API}/reviews/{SAMPLE}/status", json={"status": "replied", "reply_text": "확인하겠습니다.", "visitor_id": v})
    assert set(db.review_records.load("store_ongi", a)) == {"rv_ongi_paste_001", SAMPLE}
    assert client.delete(f"{API}/reviews/pasted?store_id=store_ongi&visitor_id={a}").json() == {"deleted": 1}
    assert db.review_records.load("store_ongi", a) == {}                                 # 합성 리뷰에 붙인 기록도 같이
    assert set(db.review_records.load("store_ongi", b)) == {"rv_ongi_paste_001", SAMPLE}  # 다른 방문자는 그대로
    # 계정 초기화·탈퇴가 쓰는 경로(forget_labels=true)도 같다
    assert client.delete(f"{API}/reviews/pasted?store_id=store_ongi&visitor_id={b}&forget_labels=true").json()["deleted"] == 1
    assert db.review_records.load("store_ongi", b) == {}


def test_pg_unreachable_records_answer_503_not_empty(client, db, monkeypatch):
    storage.use(db)
    from shared.storage import StorageError
    v = visitor()

    def down(*_a, **_k):
        raise StorageError("DB 에 닿지 못했습니다 (시험)")

    monkeypatch.setattr(db.review_records, "load", down)
    res = client.get(f"{API}/reviews?visitor_id={v}")
    assert res.status_code == 503 and res.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
    monkeypatch.setattr(db.review_records, "update", down)
    res = client.post(f"{API}/reviews/{SAMPLE}/status", json={"status": "skipped", "visitor_id": v})
    assert res.status_code == 503, res.text
    monkeypatch.setattr(db.review_records, "clear", down)
    with pytest.raises(storage.StorageUnavailable):
        records.clear("store_ongi", v)
