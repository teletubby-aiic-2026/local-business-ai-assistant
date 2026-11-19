"""계정 초기화·탈퇴용 지우기 (11/19): DELETE /reviews/pasted?forget_labels=true. CLOVA 는 가짜.

- forget_labels=true 면 그 방문자·그 가게의 붙여넣은 리뷰·상태·답글 기록과 그 리뷰들의 분류 결과(공용 키)를 지운다.
- 그 가게의 합성 리뷰가 같이 쓰는 키는 남긴다. 다른 방문자·다른 가게의 리뷰와 기록은 그대로다.
- forget_labels 를 안 주면 예전과 똑같다 (응답 {"deleted": n}, 분류 결과는 남김).
- 'pg' 시험은 TEST_DB_HOST 가 있을 때만.
"""
import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app import classify, records, service, storage
from app.classify import Classifier

API = "/api/review-insight"


@pytest.fixture(autouse=True)
def tmp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(classify, "REPLAY_FILE", tmp_path / "replay.json")
    monkeypatch.setattr(classify, "RUNTIME_CACHE", tmp_path / "runtime.json")
    monkeypatch.setattr(classify, "USAGE_LOG", tmp_path / "logs" / "llm_usage.jsonl")


def _fake_model():
    def handler(req):
        body = json.loads(req.content)
        user = body["messages"][-1]["content"]
        rows = json.loads(user[user.index("\n[\n") + 1:])
        out = [{"review_id": r["review_id"], "sentiment": "negative", "summary": "요약",
                "topics": [{"topic": "missing_item", "polarity": "negative", "evidence": r["text"][:4]}]} for r in rows]
        return httpx.Response(200, json={"result": {"message": {"content": json.dumps(out, ensure_ascii=False)}}})
    return httpx.MockTransport(handler)


@pytest.fixture
def live(monkeypatch):
    from app import main
    clf = Classifier("live", api_key="k", transport=_fake_model(), hints=False)
    monkeypatch.setattr(main, "_classifier", clf)
    return TestClient(main.app), clf


def paste(client, text, visitor, store="store_ongi", rating=1, channel="baemin"):
    res = client.post(f"{API}/reviews", json={"store_id": store, "text": text, "rating": rating, "channel": channel,
                                              "visitor_id": visitor})
    assert res.status_code == 201, res.text
    return res.json()["review"]["review_id"]


def key_of(clf, text, rating=1, channel="baemin"):
    from app.models import Review
    r = Review(review_id="x", store_id="store_ongi", channel=channel, rating=rating, text=text,
               created_at="2026-11-01T23:00:00+09:00", input_method="paste", pii_masked=False, data_origin="synthetic")
    return classify.cache_key(r, clf.model, clf.hints)


def runtime_keys() -> set:
    try:
        return set(json.loads(classify.RUNTIME_CACHE.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return set()


def test_files_forget_only_that_visitor_and_store_and_keep_shared_synthetic_keys(live):
    client, clf = live
    a, b = "u-aaaa0000aaaa0000", "u-bbbb0000bbbb0000"
    sample = service.sample_reviews("store_ongi")[0]               # 합성 리뷰와 글·별점·채널이 같은 붙여넣기
    mine = "A 만 쓴 글 " + uuid.uuid4().hex
    rid = paste(client, mine, a)
    paste(client, sample.text, a, rating=sample.rating, channel=sample.channel)
    paste(client, "바삭치킨에 A 가 쓴 글", a, store="store_basak")
    paste(client, "B 가 쓴 글", b)
    assert client.post(f"{API}/reviews/{rid}/status", json={"status": "replied", "reply_text": "죄송합니다",
                                                               "store_id": "store_ongi", "visitor_id": a}).status_code == 200
    assert records.load("store_ongi", a)[rid]["reply"]["text"] == "죄송합니다"
    before = runtime_keys()
    assert {key_of(clf, mine), key_of(clf, "B 가 쓴 글")} <= before

    res = client.delete(f"{API}/reviews/pasted?store_id=store_ongi&visitor_id={a}&forget_labels=true")
    assert res.status_code == 200 and res.json() == {"deleted": 2, "labels_deleted": 1}
    after = runtime_keys()
    assert key_of(clf, mine) not in after                                                   # A 의 글 키는 지움
    assert key_of(clf, sample.text, sample.rating, sample.channel) == key_of(clf, sample.text, sample.rating, sample.channel)
    assert key_of(clf, sample.text, sample.rating, sample.channel) in after                 # 합성 리뷰가 같이 쓰는 키는 남김
    assert key_of(clf, "B 가 쓴 글") in after and key_of(clf, "바삭치킨에 A 가 쓴 글") in after
    assert service.pasted_reviews("store_ongi", a) == [] and records.load("store_ongi", a) == {}
    assert not (service.RUNTIME / "visitors" / a / "pasted_store_ongi.json").exists()       # 빈 목록 파일을 남기지 않음
    assert len(service.pasted_reviews("store_ongi", b)) == 1 and len(service.pasted_reviews("store_basak", a)) == 1
    # 다시 불러도 안전 (0건)
    assert client.delete(f"{API}/reviews/pasted?store_id=store_ongi&visitor_id={a}&forget_labels=true").json() == \
        {"deleted": 0, "labels_deleted": 0}
    # 바삭치킨까지 지우면 방문자 폴더도 없어짐
    assert client.delete(f"{API}/reviews/pasted?store_id=store_basak&visitor_id={a}&forget_labels=true").json() == \
        {"deleted": 1, "labels_deleted": 1}
    assert not (service.RUNTIME / "visitors" / a).exists()


def test_without_the_flag_nothing_changes(live):
    client, clf = live
    a = "u-cccc0000cccc0000"
    paste(client, "그대로 남는 키", a)
    res = client.delete(f"{API}/reviews/pasted?store_id=store_ongi&visitor_id={a}")
    assert res.json() == {"deleted": 1}                                                      # 예전 응답 그대로
    assert key_of(clf, "그대로 남는 키") in runtime_keys()                                   # 분류 결과는 남김 ('데모 다시 하기')


def test_mock_mode_has_no_cache_and_still_answers(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_classifier", Classifier("mock"))
    client = TestClient(main.app)
    a = "u-dddd0000dddd0000"
    paste(client, "모의 모드 글", a)
    assert client.delete(f"{API}/reviews/pasted?visitor_id={a}&forget_labels=true").json() == {"deleted": 1, "labels_deleted": 0}


class _LabelsDown:
    """분류 결과 표만 닿지 않는 저장소. 리뷰는 지워지지 않아야 한다 (분류 결과를 먼저 지우므로)."""
    def __init__(self):
        err = storage._import_shared().StorageError
        self.cleared = []

        def boom(*_a, **_k):
            raise err("DB 에 닿지 못했습니다")
        rows = [{"review_id": "rv_ongi_paste_001", "store_id": "store_ongi", "channel": None, "rating": 1, "text": "글",
                 "created_at": "2026-11-01T23:00:00+09:00", "input_method": "paste", "pii_masked": False,
                 "data_origin": "synthetic"}]
        self.reviews = type("R", (), {"list": lambda *_a: rows, "clear": lambda _s, *a: self.cleared.append(a) or 1})()
        self.labels = type("L", (), {"get_many": boom, "put_many": boom, "delete_many": boom})()

    def close(self):
        pass


def test_label_store_down_is_503_and_reviews_stay(live):
    client, _ = live
    down = _LabelsDown()
    storage.use(down)
    res = client.delete(f"{API}/reviews/pasted?visitor_id=u-eeee0000eeee0000&forget_labels=true")
    assert res.status_code == 503 and res.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
    assert down.cleared == []


# ── PostgreSQL ─────────────────────────────────────────────────────
@pytest.fixture
def db():
    storage._import_shared()
    from shared.storage.testing import open_test_db
    found = open_test_db("ic26-review-erase")
    if found is None:
        pytest.skip("TEST_DB_HOST 없음 (PostgreSQL 시험은 건너뜀)")
    yield found
    found.close()


def test_pg_forget_removes_reviews_and_their_labels_only(live, db):
    client, clf = live
    storage.use(db)
    a, b = "u-" + uuid.uuid4().hex[:16], "u-" + uuid.uuid4().hex[:16]
    mine, theirs = "A 의 PG 글 " + uuid.uuid4().hex, "B 의 PG 글 " + uuid.uuid4().hex
    paste(client, mine, a)
    paste(client, theirs, b)
    paste(client, mine + " 몽글", a, store="store_mongle")
    k_mine, k_theirs, k_mongle = key_of(clf, mine), key_of(clf, theirs), key_of(clf, mine + " 몽글")
    assert set(db.labels.get_many([k_mine, k_theirs, k_mongle])) == {k_mine, k_theirs, k_mongle}
    res = client.delete(f"{API}/reviews/pasted?store_id=store_ongi&visitor_id={a}&forget_labels=true")
    assert res.json() == {"deleted": 1, "labels_deleted": 1}
    assert set(db.labels.get_many([k_mine, k_theirs, k_mongle])) == {k_theirs, k_mongle}
    assert db.reviews.list("store_ongi", a) == [] and len(db.reviews.list("store_ongi", b)) == 1
    assert len(db.reviews.list("store_mongle", a)) == 1
    client.delete(f"{API}/reviews/pasted?store_id=store_ongi&visitor_id={b}&forget_labels=true")
    client.delete(f"{API}/reviews/pasted?store_id=store_mongle&visitor_id={a}&forget_labels=true")
    assert db.labels.get_many([k_mine, k_theirs, k_mongle]) == {}
