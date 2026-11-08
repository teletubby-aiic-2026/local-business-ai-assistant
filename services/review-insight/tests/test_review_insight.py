"""키 없이 도는 시험. CLOVA 응답은 가짜(httpx.MockTransport)로 만듭니다."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import classify, service
from app.classify import Classifier, validate
from app.cluster import build_insight
from app.models import Review
from app.topics import banned_in, evidence_ok, mask_pii


@pytest.fixture(autouse=True)
def tmp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(classify, "REPLAY_FILE", tmp_path / "replay.json")
    monkeypatch.setattr(classify, "RUNTIME_CACHE", tmp_path / "runtime.json")


def labels(store_id="store_ongi"):
    return service.labels(store_id)


# ── C2 합성 데이터 ──
@pytest.mark.parametrize("store_id,count", [("store_ongi", 40), ("store_basak", 30), ("store_mongle", 30)])
def test_synthetic_data_shape(store_id, count):
    rows = service.sample_reviews(store_id)
    assert len(rows) == count and len({r.review_id for r in rows}) == count
    assert set(labels(store_id)) == {r.review_id for r in rows}
    assert all(r.data_origin == "synthetic" and r.input_method == "sample" and r.store_id == store_id for r in rows)
    raw = json.loads((service.SYNTHETIC / store_id / "reviews.json").read_text(encoding="utf-8"))
    banned_fields = {"nickname", "author", "phone", "address", "customer_id"}
    assert not any(banned_fields & set(d) for d in raw)          # 개인정보 필드 없음
    assert not any(mask_pii(r.text)[1] for r in rows)
    from app.topics import TOPICS
    assert all(t["topic"] in TOPICS for l in labels(store_id).values() for t in l["expected_topics"])


def test_three_stores_and_ids_unique_across_stores():
    ids = service.store_ids()
    assert ids[0] == "store_ongi" and set(ids) == {"store_ongi", "store_basak", "store_mongle"}
    all_ids = [r.review_id for s in ids for r in service.sample_reviews(s)]
    assert len(all_ids) == len(set(all_ids)) == 100
    with pytest.raises(service.StoreNotFound):
        service.sample_reviews("store_nope")


# ── C3 규칙 검사 ──
def test_evidence_must_be_in_text():
    assert evidence_ok("배달이 너무 늦어요", "배달이 너무 늦어요. 예상 시간보다")
    assert evidence_ok("배달이  너무늦어요", "배달이 너무 늦어요")           # 띄어쓰기 차이는 봐줌
    assert not evidence_ok("배달 기사가 불친절", "배달이 너무 늦어요")
    assert not evidence_ok("늦", "배달이 너무 늦어요")                       # 너무 짧음


def test_validate_drops_bad_model_output():
    r = Review("rv_x", "s", "baemin", 1, "한 시간 기다렸는데 찌개가 다 식어서 왔어요", "2026-11-06T20:30:00+09:00")
    item = {"sentiment": "positive", "summary": "라이더 탓에 늦음", "topics": [
        {"topic": "delivery_time", "polarity": "negative", "evidence": "한 시간 기다렸는데"},
        {"topic": "temperature", "polarity": "negative", "evidence": "찌개가 다 식어서"},
        {"topic": "rider_attitude", "polarity": "negative", "evidence": "한 시간"},          # 사전에 없음
        {"topic": "taste", "polarity": "negative", "evidence": "맛이 없었어요"},             # 지어낸 근거
        {"topic": "packaging", "polarity": "bad", "evidence": "찌개가"}]}                    # 극성 오류
    c = validate(item, r, method="model", model="HCX-005")
    assert {(t.topic, t.polarity) for t in c.topics} == {("delivery_time", "negative"), ("temperature", "negative")}
    assert c.sentiment == "negative" and c.summary is None and len(c.warnings) == 5


def test_evidence_is_stored_exactly_as_in_review():
    """모델이 문장부호·띄어쓰기를 바꿔 낸 근거도, 리뷰 글에 적힌 그대로의 구절로 저장해야 묶음 검증을 통과함."""
    r = Review("rv_x", "s", "baemin", 1, "한 시간 기다렸는데 찌개가 다 식어서 왔어요", "2026-11-06T20:30:00+09:00")
    item = {"sentiment": "negative", "topics": [
        {"topic": "delivery_time", "polarity": "negative", "evidence": "“한 시간기다렸는데,”"},
        {"topic": "temperature", "polarity": "negative", "evidence": "찌개가 다 식어서 왔어요."}]}
    c = validate(item, r, method="model", model="HCX-005")
    assert [t.evidence for t in c.topics] == ["한 시간 기다렸는데", "찌개가 다 식어서 왔어요"]
    assert all(t.evidence in r.text for t in c.topics)


def test_validate_falls_back_to_rules_when_nothing_usable():
    r = Review("rv_x", "s", "baemin", 2, "포장이 허술해서 국물이 넘쳤어요", "2026-10-29T20:20:00+09:00")
    c = validate({"sentiment": "negative", "topics": [{"topic": "packaging", "polarity": "negative", "evidence": "용기가 깨짐"}]},
                 r, method="model", model="HCX-005")
    assert c.method == "rule_fallback" and "packaging" in c.negative_topics


def test_banned_and_pii():
    assert banned_in("배달 기사 탓입니다") and banned_in("010-1234-5678로 연락") and not banned_in("저녁 배달 지연")
    masked, changed = mask_pii("연락 주세요 010-1234-5678, a@b.com https://x.y")
    assert changed and "010" not in masked and "@" not in masked and "https" not in masked


# ── C3 반복 묶음 ──
def test_repeated_issues_from_synthetic_mock():
    ins = service.analyze(Classifier("mock"))
    by = {i.topic: i for i in ins.repeated_issues}
    assert set(by) == {"delivery_time", "temperature", "portion", "packaging"}     # 일부러 만든 반복 불만 4갈래
    assert by["delivery_time"].review_count == 6 and by["delivery_time"].main_time_band == "17~21시"
    assert by["temperature"].main_time_band == "17~21시" and by["packaging"].main_time_band == "17~21시"
    assert "missing_item" not in by                                                # 2건이라 반복 아님
    assert ins.review_count == 40 and ins.period_end == "2026-11-08"


def test_rule_classifier_matches_most_labels():
    """규칙 분류기는 대비책. 단서를 맞춘 온기한식에서는 거의 맞아야 함 (다른 가게 성능은 eval_classify로 봄)."""
    lab = labels()
    rows = service.sample_reviews()
    got = Classifier("mock").classify(rows)
    sent = sum(c.sentiment == lab[c.review_id]["expected_sentiment"] for c in got)
    assert sent >= 36


# ── live / replay (가짜 CLOVA) ──
def fake_clova(calls):
    def handler(req):
        body = json.loads(req.content)
        calls.append(body)
        assert req.headers["Authorization"] == "Bearer test-key"
        user = body["messages"][1]["content"]
        out = []
        for d in json.loads(user[user.index("\n[") + 1:]):
            out.append({"review_id": d["review_id"], "sentiment": "negative" if (d["rating"] or 3) <= 2 else "positive",
                        "topics": [{"topic": "taste", "polarity": "positive", "evidence": d["text"][:6]}], "summary": "요약"})
        return httpx.Response(200, json={"result": {"message": {"content": "```json\n" + json.dumps(out, ensure_ascii=False) + "\n```"}}})
    return httpx.MockTransport(handler)


def test_live_calls_in_batches_then_replay_reuses():
    calls = []
    rows = service.sample_reviews()
    live = Classifier("live", api_key="test-key", transport=fake_clova(calls))
    res = live.classify(rows)
    assert len(calls) == 7 and all(c.method == "model" for c in res)           # 40건 / 6건씩
    assert calls[0]["maxTokens"] >= 1024 and "[주제 사전]" in calls[0]["messages"][0]["content"]
    replay = Classifier("replay", api_key="")
    again = replay.classify(rows)
    assert all(c.method == "replay" for c in again)
    assert [t.evidence for t in again[0].topics] == [t.evidence for t in res[0].topics]


def test_parse_items_handles_messy_model_output():
    from app.classify import parse_items
    jsonl = '{"review_id": "a", "topics": []}\n{"review_id": "b", "topics": []}'
    two_arrays = '```json\n[{"review_id": "a"}]\n[{"review_id": "b"}]\n```'
    broken = '[{"review_id": "a", "summary": "ok"}, {"review_id": "b", "summary": "깨진 "따옴표" 요약"}, {"review_id": "c"}]'
    assert [x["review_id"] for x in parse_items(jsonl)] == ["a", "b"]
    assert [x["review_id"] for x in parse_items(two_arrays)] == ["a", "b"]
    assert [x["review_id"] for x in parse_items(broken)] == ["a", "c"]          # 깨진 b만 버림
    assert parse_items("죄송합니다") == []


def test_missing_reviews_are_asked_again_in_small_batches():
    """첫 답에서 빠진 리뷰는 작게 나눠 다시 물어서 모델 결과로 채움."""
    calls = []

    def handler(req):
        body = json.loads(req.content)
        user = body["messages"][1]["content"]
        rows = json.loads(user[user.index("\n[") + 1:])
        calls.append(len(rows))
        keep = rows if len(rows) <= 2 else rows[:2]          # 큰 묶음에서는 앞 2건만 답함
        out = [{"review_id": d["review_id"], "sentiment": "positive",
                "topics": [{"topic": "taste", "polarity": "positive", "evidence": d["text"][:6]}]} for d in keep]
        return httpx.Response(200, json={"result": {"message": {"content": json.dumps(out, ensure_ascii=False)}}})

    res = Classifier("live", api_key="k", transport=httpx.MockTransport(handler)).classify(service.sample_reviews()[:6])
    assert calls == [6, 2, 2] and all(c.method == "model" for c in res)


def test_live_failure_falls_back_to_rules():
    t = httpx.MockTransport(lambda req: httpx.Response(500, json={}))
    res = Classifier("live", api_key="k", transport=t).classify(service.sample_reviews()[:3])
    assert all(c.method == "rule_fallback" for c in res)


def test_live_requires_key():
    with pytest.raises(ValueError):
        Classifier("live", api_key="")


# ── S2 API ──
@pytest.fixture
def client(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_classifier", Classifier("mock"))
    return TestClient(main.app)


def test_paste_goes_to_chosen_store_only(client):
    r = client.post("/api/review-insight/reviews", json={"store_id": "store_basak", "text": "치킨무가 또 빠져 있었어요", "rating": 1})
    assert r.status_code == 201 and r.json()["review"]["review_id"].startswith("rv_basak_paste_")
    assert "iss_missing_item" in r.json()["joined_issues"]
    assert client.get("/api/review-insight/reviews?store_id=store_basak").json()["count"] == 31
    assert client.get("/api/review-insight/reviews?store_id=store_ongi").json()["count"] == 40
    bad = client.get("/api/review-insight/insight?store_id=store_nope")
    assert bad.status_code == 404 and bad.json()["error"]["code"] == "STORE_NOT_FOUND"
    assert len(client.get("/api/review-insight/stores").json()["stores"]) == 3


def test_paste_flow(client):
    r = client.post("/api/review-insight/reviews", json={"text": "저녁에 시켰는데 배달이 너무 늦어요 010-1111-2222", "rating": 1, "channel": "baemin"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["review"]["pii_masked"] and "010" not in d["review"]["text"] and d["review"]["input_method"] == "paste"
    assert "delivery_time" in d["classification"]["negative_topics"]
    assert "iss_delivery_time" in d["joined_issues"]
    by = {i["topic"]: i for i in d["repeated_issues"]}
    assert by["delivery_time"]["review_count"] == 7
    assert client.get("/api/review-insight/reviews").json()["count"] == 41
    assert client.delete("/api/review-insight/reviews/pasted").json() == {"deleted": 1}
    assert client.get("/api/review-insight/reviews").json()["count"] == 40


def test_paste_validation(client):
    for body in ({"text": ""}, {"text": "a" * 1001}, {"text": "좋아요", "rating": 9}, {"text": "좋아요", "channel": "kakao"}):
        r = client.post("/api/review-insight/reviews", json=body)
        assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.post("/api/review-insight/reviews", json={}).status_code == 400


def test_insight_endpoint_and_page(client):
    d = client.get("/api/review-insight/insight").json()
    assert d["repeated_issues"][0]["topic"] == "delivery_time" and d["data_origin"] == "synthetic"
    assert client.get("/").status_code == 200 and client.get("/health").json()["mode"] == "mock"
