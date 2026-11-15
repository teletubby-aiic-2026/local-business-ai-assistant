"""방문자별로 나뉘는 붙여넣은 리뷰와, 저장 계층(파일 / PostgreSQL) 시험. CLOVA 는 가짜.

- 앞부분은 DB 없이 돈다 (파일 방식).
- 'pg' 가 붙은 시험은 환경 변수 TEST_DB_HOST 등(shared/storage/testing.py)이 있을 때만 돌고, 없으면 건너뜀.
  서버 2대 = 연결 풀 둘 (같은 DB 에 따로 붙은 Database 두 개).
"""
import json
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app import classify, service, storage
from app.classify import Classifier

OLD_SCREEN = "/api/review-insight"
VISITOR_A = "visitor-A_0123456789abcdef"
VISITOR_B = "visitor-B_0123456789abcdef"


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


def paste(client, text, visitor=None, store="store_ongi", rating=1):
    body = {"store_id": store, "text": text, "rating": rating}
    if visitor is not None:
        body["visitor_id"] = visitor
    return client.post(f"{OLD_SCREEN}/reviews", json=body)


def counts(client, visitor=None, store="store_ongi"):
    q = f"?store_id={store}" + (f"&visitor_id={visitor}" if visitor is not None else "")
    reviews = client.get(f"{OLD_SCREEN}/reviews{q}").json()
    insight = client.get(f"{OLD_SCREEN}/insight{q}").json()
    return reviews["count"], insight["review_count"], insight["complaint_count"]


# ── 파일 방식: 방문자 나누기 ─────────────────────────────────────────
def test_visitors_do_not_see_each_others_pasted_reviews(client):
    assert counts(client, VISITOR_A) == (40, 40, 12) and counts(client, VISITOR_B) == (40, 40, 12)
    assert paste(client, "치킨무가 또 빠져 있었어요", VISITOR_A).status_code == 201
    assert paste(client, "치킨무가 또 빠져 있었어요", VISITOR_A).status_code == 201
    assert counts(client, VISITOR_A)[0] == 42 and counts(client, VISITOR_A)[1] == 42     # 합성 40 + 내가 붙인 2
    assert counts(client, VISITOR_B) == (40, 40, 12)                                      # 다음 사람의 숫자는 그대로
    assert counts(client) == (40, 40, 12)                                                 # 방문자를 안 준 공용도 그대로
    texts_b = [r["text"] for r in client.get(f"{OLD_SCREEN}/reviews?visitor_id={VISITOR_B}").json()["items"]]
    assert "치킨무가 또 빠져 있었어요" not in texts_b


def test_each_visitor_clears_only_their_own_and_numbers_restart(client):
    first_a = paste(client, "A 의 첫 글", VISITOR_A).json()["review"]["review_id"]
    first_b = paste(client, "B 의 첫 글", VISITOR_B).json()["review"]["review_id"]
    assert first_a == first_b == "rv_ongi_paste_001"                                      # 번호는 방문자마다 1번부터 (겹쳐도 서로 안 보임)
    assert paste(client, "A 의 둘째", VISITOR_A).json()["review"]["review_id"] == "rv_ongi_paste_002"
    assert client.delete(f"{OLD_SCREEN}/reviews/pasted?visitor_id={VISITOR_A}").json() == {"deleted": 2}
    assert counts(client, VISITOR_A)[0] == 40 and counts(client, VISITOR_B)[0] == 41
    assert client.delete(f"{OLD_SCREEN}/reviews/pasted?visitor_id={VISITOR_A}").json() == {"deleted": 0}


def test_one_review_can_be_fetched_only_by_its_visitor(client):
    rid = paste(client, "비밀 리뷰", VISITOR_A).json()["review"]["review_id"]
    assert client.get(f"{OLD_SCREEN}/reviews/{rid}?visitor_id={VISITOR_A}").status_code == 200
    assert client.get(f"{OLD_SCREEN}/reviews/{rid}?visitor_id={VISITOR_B}").status_code == 404
    assert client.get(f"{OLD_SCREEN}/reviews/{rid}").status_code == 404


def test_without_visitor_id_it_is_the_old_shared_behavior_and_file(client, tmp_path):
    """visitor_id 를 안 주면 지금까지와 똑같이: 모두가 한 곳을 보고, 파일 이름도 그대로."""
    paste(client, "공용으로 붙인 글")
    assert counts(client)[0] == 41
    assert (tmp_path / "runtime" / "pasted_store_ongi.json").exists()
    assert not (tmp_path / "runtime" / "visitors").exists()
    assert counts(client, "common")[0] == 41                 # 'common' 을 직접 줘도 공용
    assert counts(client, VISITOR_A)[0] == 40
    assert client.delete(f"{OLD_SCREEN}/reviews/pasted").json() == {"deleted": 1}


def test_visitor_files_stay_inside_the_runtime_folder(client, tmp_path):
    paste(client, "글", VISITOR_A)
    files = sorted(p.relative_to(tmp_path).as_posix() for p in (tmp_path / "runtime").rglob("*") if p.is_file())
    assert files == [f"runtime/visitors/{VISITOR_A}/pasted_store_ongi.json",
                     f"runtime/visitors/{VISITOR_A}/records_store_ongi.json"]      # 받은 시각·상태 기록 (app/records.py)


BAD_IDS = ["../x", "..", "a/b", "a\\b", "a.b", "a b", "x" * 65, "abc%0A", "%2e%2e%2f", "한글", "a;b", "~"]


@pytest.mark.parametrize("bad", BAD_IDS)
def test_bad_visitor_ids_are_rejected_everywhere_and_write_nothing(client, tmp_path, bad):
    q = f"visitor_id={bad}"
    for url in (f"{OLD_SCREEN}/reviews?{q}", f"{OLD_SCREEN}/insight?{q}", f"{OLD_SCREEN}/reviews/rv_x?{q}"):
        res = client.get(url)
        assert res.status_code == 400 and res.json()["error"]["code"] == "VALIDATION_ERROR", url
    assert client.delete(f"{OLD_SCREEN}/reviews/pasted?{q}").status_code == 400
    res = client.post(f"{OLD_SCREEN}/reviews", json={"text": "글", "visitor_id": bad})
    assert res.status_code == 400 and res.json()["error"]["code"] == "VALIDATION_ERROR"
    assert not (tmp_path / "runtime").exists()                                            # 아무것도 쓰지 않았다


def test_newline_after_a_valid_id_is_rejected_too(client):
    assert paste(client, "글", "abc\n").status_code == 400                               # `$` 로 검사하면 통과하는 값
    assert client.get(f"{OLD_SCREEN}/reviews", params={"visitor_id": "abc\n"}).status_code == 400
    with pytest.raises(ValueError):
        service.clean_visitor("abc\n")


def test_service_functions_also_reject_bad_ids_directly(tmp_path):
    for bad in ["../x", "a/b", "x" * 65, "\n"]:
        with pytest.raises(ValueError):
            service.pasted_reviews("store_ongi", bad)
        with pytest.raises(ValueError):
            service.add_pasted("글", store_id="store_ongi", visitor_id=bad)
        with pytest.raises(ValueError):
            service.clear_pasted("store_ongi", bad)
    assert service.clean_visitor(None) == service.clean_visitor("") == service.COMMON_VISITOR


def test_visitor_rule_is_the_same_as_the_shared_one():
    """app/service.py 의 사본과 shared/storage/visitor.py 가 같은 값에 같은 답을 낸다."""
    shared = storage._import_shared()
    from shared.storage import visitor as shared_visitor
    samples = ["a", "A-b_9", "x" * 64, "x" * 65, "../x", "a/b", "a.b", "abc\n", "한글", "", None, "common", "a b"] + BAD_IDS
    for value in samples:
        try:
            mine = service.clean_visitor(value)
        except ValueError:
            mine = ValueError
        try:
            theirs = shared_visitor.clean_visitor_id(value)
        except ValueError:
            theirs = ValueError
        assert mine == theirs, value
    assert shared.COMMON_VISITOR == service.COMMON_VISITOR


def test_unknown_store_still_404_with_visitor(client):
    bad = client.get(f"{OLD_SCREEN}/insight?store_id=store_nope&visitor_id={VISITOR_A}")
    assert bad.status_code == 404 and bad.json()["error"]["code"] == "STORE_NOT_FOUND"
    assert paste(client, "글", VISITOR_A, store="store_nope").status_code == 404


def test_synthetic_reviews_are_the_same_for_everyone(client):
    ids_a = [r["review_id"] for r in client.get(f"{OLD_SCREEN}/reviews?visitor_id={VISITOR_A}").json()["items"]]
    ids_b = [r["review_id"] for r in client.get(f"{OLD_SCREEN}/reviews?visitor_id={VISITOR_B}").json()["items"]]
    assert ids_a == ids_b and len(ids_a) == 40
    a = client.get(f"{OLD_SCREEN}/insight?visitor_id={VISITOR_A}").json()
    b = client.get(f"{OLD_SCREEN}/insight").json()
    assert (a["review_count"], a["complaint_count"], a["top_issue_id"]) == (b["review_count"], b["complaint_count"], b["top_issue_id"]) == (40, 12, b["top_issue_id"])


# ── DB 오류는 503 (장애 전환 중) ─────────────────────────────────────
class _Down:
    """DB 에 닿지 못하는 저장소 (장애 전환 중)."""
    def __init__(self):
        err = storage._import_shared().StorageError

        def boom(*_a, **_k):
            raise err("DB 에 닿지 못했습니다 (PoolTimeout)")
        self.reviews = type("R", (), {"list": boom, "add": boom, "clear": boom})()
        self.labels = type("L", (), {"get_many": boom, "put_many": boom})()

    def close(self):
        pass


def test_db_down_answers_503_retryable_not_500(client):
    storage.use(_Down())
    for res in (client.get(f"{OLD_SCREEN}/reviews?visitor_id={VISITOR_A}"), client.get(f"{OLD_SCREEN}/insight"),
                paste(client, "글", VISITOR_A), client.delete(f"{OLD_SCREEN}/reviews/pasted")):
        assert res.status_code == 503, res.text
        error = res.json()["error"]
        assert error["code"] == "STORAGE_UNAVAILABLE" and error["retryable"] is True and error["request_id"].startswith("req_")
    assert client.get("/api/health").status_code == 200                                   # 상태 확인은 DB 와 상관없음
    assert client.get(f"{OLD_SCREEN}/stores").status_code == 200


def test_classification_cache_failure_does_not_fail_the_request(monkeypatch, tmp_path):
    """분류 결과 저장소가 안 되면 (live) 모델로 새로 분류해서 답한다. 저장은 못 해도 결과는 쓴다."""
    storage.use(_Down())
    calls = []
    clf = Classifier("live", api_key="k", transport=_fake_model(calls))
    review = service.sample_reviews("store_ongi")[0]
    review = review.__class__(**{**review.to_dict(), "input_method": "paste"})
    assert clf.classify([review])[0].method == "model" and calls == [1]


# ── DB 있는 시험: 서버 2대 ───────────────────────────────────────────
def _fake_model(calls):
    def handler(req):
        body = json.loads(req.content)
        user = body["messages"][-1]["content"]
        rows = json.loads(user[user.index("\n[\n") + 1:])
        calls.append(len(rows))
        out = [{"review_id": r["review_id"], "sentiment": "negative", "summary": "요약",
                "topics": [{"topic": "missing_item", "polarity": "negative", "evidence": r["text"][:6]}]} for r in rows]
        return httpx.Response(200, json={"result": {"message": {"content": json.dumps(out, ensure_ascii=False)}}})
    return httpx.MockTransport(handler)


@pytest.fixture
def two_servers():
    """같은 DB 에 따로 붙은 서버 두 대. use(db) 로 어느 서버가 요청을 받는지 바꾼다."""
    storage._import_shared()
    from shared.storage.testing import open_test_db
    first, second = open_test_db("ic26-review-1"), open_test_db("ic26-review-2")
    if first is None:
        pytest.skip("TEST_DB_HOST 없음 (PostgreSQL 시험은 건너뜀)")
    yield first, second
    first.close()
    second.close()


def _unique_visitor():
    return "v_" + uuid.uuid4().hex[:12]


def test_pg_paste_on_one_server_shows_on_the_other(client, two_servers):
    one, two = two_servers
    a, b = _unique_visitor(), _unique_visitor()
    storage.use(one)
    assert paste(client, "치킨무가 또 빠져 있었어요", a).status_code == 201
    storage.use(two)                                          # 다음 요청이 다른 서버로 감
    assert counts(client, a)[:2] == (41, 41)
    assert counts(client, b) == (40, 40, 12)                  # 다른 방문자는 못 봄
    assert paste(client, "수저가 빠져 있었어요", a).json()["review"]["review_id"] == "rv_ongi_paste_002"
    storage.use(one)
    assert counts(client, a)[0] == 42
    assert client.delete(f"{OLD_SCREEN}/reviews/pasted?visitor_id={a}").json() == {"deleted": 2}
    storage.use(two)
    assert counts(client, a)[0] == 40


def test_pg_same_response_shape_and_numbers_as_files(client, two_servers):
    """붙여넣기 응답의 모양과 숫자가 파일 방식과 같다 (화면은 어느 쪽인지 모른다)."""
    one, _ = two_servers
    body = {"store_id": "store_ongi", "text": "치킨무가 또 빠져 있었어요 010-1234-5678", "rating": 1, "channel": "baemin"}
    storage.use(None)
    from_files = client.post(f"{OLD_SCREEN}/reviews", json={**body, "visitor_id": _unique_visitor()}).json()
    storage.use(one)
    from_db = client.post(f"{OLD_SCREEN}/reviews", json={**body, "visitor_id": _unique_visitor()}).json()
    assert from_db == from_files
    assert from_db["review"]["text"].count("010") == 0 and from_db["review"]["pii_masked"] is True


def test_pg_default_visitor_is_the_shared_one(client, two_servers):
    one, _ = two_servers
    storage.use(one)
    store = "store_mongle"
    client.delete(f"{OLD_SCREEN}/reviews/pasted?store_id={store}")                         # 시험 DB 의 공용 기록을 비우고 시작
    assert counts(client, store=store)[0] == 30
    paste(client, "공용 리뷰", store=store)
    assert counts(client, store=store)[0] == 31 and counts(client, "common", store=store)[0] == 31
    assert counts(client, _unique_visitor(), store=store)[0] == 30                          # 방문자를 준 쪽은 공용 기록을 안 봄
    assert client.delete(f"{OLD_SCREEN}/reviews/pasted?store_id={store}").json() == {"deleted": 1}
    assert counts(client, store=store)[0] == 30


def test_pg_classification_cache_is_shared_between_servers_and_visitors(two_servers):
    one, two = two_servers
    store = "store_ongi"
    sample = service.sample_reviews(store)
    text = "치킨무가 빠져 있었어요 " + uuid.uuid4().hex                 # 시험마다 다른 글
    a, b = _unique_visitor(), _unique_visitor()
    calls = []
    storage.use(one)
    service.add_pasted(text, 1, "baemin", store_id=store, visitor_id=a)
    live = Classifier("live", api_key="k", transport=_fake_model(calls))
    first = service.analyze(live, store, a)                             # 합성 40건(저장본 없음) + 붙여넣은 1건
    n_first = sum(calls)
    assert first.review_count == 41 and n_first == 41
    pasted_key = classify.cache_key(service.pasted_reviews(store, a)[0], live.model, live.hints)
    assert one.labels.get_many([pasted_key])[pasted_key]["topics"][0]["topic"] == "missing_item"

    storage.use(two)                                                    # 다른 서버, 다른 방문자, 같은 글
    service.add_pasted(text, 1, "baemin", store_id=store, visitor_id=b)
    again = Classifier("live", api_key="k", transport=_fake_model(calls))
    second = service.analyze(again, store, b)
    assert sum(calls) == n_first and second.review_count == 41           # 모델을 다시 부르지 않음 (합성은 파일 저장본, 붙여넣은 것은 DB)
    replay = Classifier("replay", api_key="")
    methods = {c.review_id: c.method for c in replay.classify(sample[:1] + service.pasted_reviews(store, b))}
    assert methods[service.pasted_reviews(store, b)[0].review_id] == "replay"


def test_pg_two_servers_numbers_do_not_collide(client, two_servers):
    one, two = two_servers
    v = _unique_visitor()
    ids = []
    for i in range(6):
        storage.use(one if i % 2 == 0 else two)
        ids.append(paste(client, f"글 {i}", v).json()["review"]["review_id"])
    assert ids == [f"rv_ongi_paste_{n:03d}" for n in range(1, 7)]
    storage.use(one)
    client.delete(f"{OLD_SCREEN}/reviews/pasted?visitor_id={v}")


def test_pg_recovers_after_the_database_goes_away_and_comes_back(client):
    """DB 가 잠시 사라졌다 돌아오면 다음 요청부터 된다. 사라진 동안은 500 이 아니라 503."""
    storage._import_shared()
    from shared.storage.testing import db_env, docker_ctl, open_test_db, wait_until_ready
    import os
    container = os.environ.get("TEST_DB_CONTAINER", "")
    if not (db_env() and container):
        pytest.skip("TEST_DB_CONTAINER 없음 (연결이 끊겼다 돌아오는 시험은 건너뜀)")
    db = open_test_db("ic26-review-restart", connect_timeout=2.0, retry_after=1.0)
    storage.use(db)
    v = _unique_visitor()
    try:
        assert paste(client, "멈추기 전 글", v).status_code == 201
        docker_ctl(container, "stop")
        try:
            started = time.monotonic()
            assert client.get(f"{OLD_SCREEN}/insight?visitor_id={v}").status_code == 503
            assert paste(client, "멈춰 있는 동안 글", v).status_code == 503
            assert time.monotonic() - started < 10
        finally:
            docker_ctl(container, "start")
        wait_until_ready()
        time.sleep(1.2)
        deadline = time.monotonic() + 20
        while True:
            res = client.get(f"{OLD_SCREEN}/reviews?visitor_id={v}")
            if res.status_code == 200:
                break
            assert time.monotonic() < deadline, res.text
            time.sleep(0.5)
        assert res.json()["count"] == 41
        assert paste(client, "돌아온 뒤 글", v).status_code == 201
        assert counts(client, v)[0] == 42
        client.delete(f"{OLD_SCREEN}/reviews/pasted?visitor_id={v}")
    finally:
        db.close()
