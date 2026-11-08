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
    monkeypatch.setattr(classify, "USAGE_LOG", tmp_path / "logs" / "llm_usage.jsonl")


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
def label_classes(store_id):
    from app.models import ReviewClassification, TopicHit
    L = labels(store_id)
    return [ReviewClassification(r.review_id, L[r.review_id]["expected_sentiment"],
                                 [TopicHit(t["topic"], t["polarity"], r.text) for t in L[r.review_id]["expected_topics"]])
            for r in service.sample_reviews(store_id)]


def assert_wow(ins):
    """결정안 v0.4 와우: 40건 → 불만 12 → 3묶음(포장 누락 3 = 유일한 반복, 늦은 배달 2, 양·맛 2) + 단발 5"""
    assert ins.review_count == 40 and ins.complaint_count == 12
    got = sorted((g.topics, g.review_count, g.is_repeated) for g in ins.groups)
    assert got == sorted([(["missing_item"], 3, True), (["delivery_time"], 2, False), (["taste", "portion"], 2, False)]) \
        or got == sorted([(["missing_item"], 3, True), (["delivery_time"], 2, False), (["portion", "taste"], 2, False)])
    assert len(ins.single_complaints) == 5
    assert ins.top_issue.topic == "missing_item" and ins.top_issue.topic_name == "포장 누락"
    assert [g.is_repeated for g in ins.groups] == [True, False, False]                # 반복 묶음이 맨 앞


def test_wow_scene_from_labels():
    """정답 라벨 그대로면 와우 숫자가 정확히 나와야 함 (묶음 계산 자체의 시험)."""
    ins = build_insight("store_ongi", service.sample_reviews("store_ongi"), label_classes("store_ongi"))
    assert_wow(ins)
    yangmat = next(g for g in ins.groups if len(g.topics) == 2)
    assert set(yangmat.topics) == {"portion", "taste"} and "·" in yangmat.topic_name   # 같은 리뷰 2건 → 한 묶음으로 합침


@pytest.mark.parametrize("kiwi_on", [True, False])
def test_wow_scene_with_rule_classifier(monkeypatch, kiwi_on):
    """모델 없이(mock) kiwi 규칙이면 와우 숫자가 그대로 나와야 함.
    kiwi도 없으면(글자 규칙) '공깃밥이 안 들어 있었어요'를 못 읽어 포장 누락이 2건이 되고, 카드 ⓐ(반복 묶음)가 사라짐.
    → kiwi를 requirements에 넣은 이유. 발표는 HCX-005 결과를 캐시(C9)로 고정해 씀."""
    from app import morph
    if kiwi_on and not morph.available():
        pytest.skip("kiwipiepy 미설치")
    monkeypatch.setattr(morph, "available", lambda: kiwi_on)
    ins = service.analyze(Classifier("mock"))
    if kiwi_on:
        assert_wow(ins)
    else:
        miss = next(g for g in ins.groups if g.topic == "missing_item")
        assert miss.review_count == 2 and ins.top_issue is None and ins.complaint_count < 12


def test_kiwi_reads_endings_and_negation():
    from app import morph
    from app.topics import rule_classify
    if not morph.available():
        pytest.skip("kiwipiepy 미설치")
    def got(text, rating=3, channel="baemin"):
        return {(t.topic, t.polarity) for t in rule_classify("x", text, rating, channel).topics}
    assert ("texture", "negative") in got("하나도 안 바삭해요")                      # 부정
    assert ("packaging", "positive") in got("국물 하나 안 샜어요")                    # 부정 + 불만어 = 칭찬
    assert ("missing_item", "negative") in got("소스를 요청했는데 안 왔어요", 1)
    assert ("wait_time", "negative") in got("음료 받기까지 너무 오래 걸려요", 2, "naver_place")   # 방문 리뷰
    assert ("delivery_time", "negative") in got("음료 받기까지 너무 오래 걸려요", 2, "baemin")
    assert not {t for t, _ in got("다음엔 포장해야겠네요")} & {"packaging"}           # 포장 주문 ≠ 포장 상태


def test_groups_merge_only_identical_review_sets():
    from app.models import ReviewClassification, TopicHit
    rows = [Review(f"r{i}", "s", "baemin", 2, "양도 적고 맛도 없어요", f"2026-11-0{i}T19:00:00+09:00") for i in range(1, 4)]
    cls = [ReviewClassification("r1", "negative", [TopicHit("portion", "negative", "양도 적고"), TopicHit("taste", "negative", "맛도 없어요")]),
           ReviewClassification("r2", "negative", [TopicHit("portion", "negative", "양도 적고"), TopicHit("taste", "negative", "맛도 없어요")]),
           ReviewClassification("r3", "negative", [TopicHit("portion", "negative", "양도 적고")])]
    ins = build_insight("s", rows, cls)
    assert [(g.topics, g.review_count, g.is_repeated) for g in ins.groups] == [(["portion"], 3, True), (["taste"], 2, False)]
    assert ins.single_complaints == []


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
        user = body["messages"][-1]["content"]
        out = []
        for d in json.loads(user[user.index("\n[\n") + 1:]):
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
        user = body["messages"][-1]["content"]
        rows = json.loads(user[user.index("\n[\n") + 1:])
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
    assert client.get("/api/review-insight/stores").json()["count"] == 3


def test_paste_flow(client):
    r = client.post("/api/review-insight/reviews", json={"text": "저녁에 시켰는데 배달이 너무 늦어요 010-1111-2222", "rating": 1, "channel": "baemin"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["review"]["pii_masked"] and "010" not in d["review"]["text"] and d["review"]["input_method"] == "paste"
    assert "delivery_time" in d["classification"]["negative_topics"]
    assert "iss_delivery_time" in d["joined_issues"]
    by = {g["issue_id"]: g for g in d["groups"]}
    assert by["iss_delivery_time"]["review_count"] == 3 and by["iss_delivery_time"]["is_repeated"]   # 2건 → 3건이 되어 반복으로
    assert d["complaint_count"] == 13
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
    assert d["top_issue_id"] == "iss_missing_item" and d["complaint_count"] == 12 and d["group_count"] == 3
    assert d["single_complaint_count"] == 5 and d["data_origin"] == "synthetic"
    assert client.get("/").status_code == 200 and client.get("/health").json()["mode"] == "mock"


def test_spec_common_rules(client):
    """docs/module-io-spec.md 공통 규칙: health, 목록 {items,count}, X-Request-Id, 오류 형식, 리뷰 필드"""
    h = client.get("/api/health")
    assert h.json()["status"] == "ok" and h.json()["spec_version"] == "0.1" and h.headers["X-Request-Id"].startswith("req_")
    lst = client.get("/api/review-insight/reviews").json()
    assert set(lst) == {"items", "count"} and lst["count"] == 40
    r = lst["items"][0]
    assert r["order_ref"] is None and r["status"] == "new" and r["data_origin"] == "synthetic"
    one = client.get("/api/review-insight/reviews/rv_ongi_001")
    assert one.status_code == 200 and one.json()["review"]["status"] == "analyzed"
    miss = client.get("/api/review-insight/reviews/rv_nope")
    err = miss.json()["error"]
    assert miss.status_code == 404 and err["code"] == "REVIEW_NOT_FOUND" and err["request_id"] == miss.headers["X-Request-Id"]
    bad = client.post("/api/review-insight/reviews", json={"text": ""})
    assert bad.json()["error"]["request_id"] == bad.headers["X-Request-Id"]


def test_retry_rules_and_usage_log(tmp_path):
    """규격 5.6: 429·5xx는 1번 재시도, 401은 재시도 안 함. 호출마다 사용량 한 줄 (글은 남기지 않음)."""
    rows = service.sample_reviews()[:2]
    for codes, expected_calls in (([500, 200], 2), ([401], 1), ([429, 429], 2)):
        seq = iter(codes)
        calls = []
        def handler(req, seq=seq, calls=calls):
            calls.append(1)
            code = next(seq)
            if code != 200:
                return httpx.Response(code, json={}, headers={"retry-after": "0"})
            out = [{"review_id": r.review_id, "sentiment": "negative", "topics": [], "summary": None} for r in rows]
            return httpx.Response(200, json={"result": {"message": {"content": json.dumps(out)}, "usage": {"promptTokens": 10, "completionTokens": 5, "totalTokens": 15}}})
        Classifier("live", api_key="k", transport=httpx.MockTransport(handler))._ask(rows)
        assert len(calls) == expected_calls, codes
    lines = [json.loads(l) for l in classify.USAGE_LOG.read_text(encoding="utf-8").splitlines()]
    assert [l["status"] for l in lines] == ["ok", "LLM_UPSTREAM_ERROR", "LLM_RATE_LIMITED"]
    assert lines[0]["total_tokens"] == 15 and lines[0]["review_ids"] == [r.review_id for r in rows]
    assert not any("text" in l or "content" in l for l in lines)


def test_key_env_names(monkeypatch):
    monkeypatch.delenv("CLOVA_STUDIO_API_KEY", raising=False)
    monkeypatch.setenv("CLOVASTUDIO_API_KEY", "spec-key")
    assert Classifier("live").api_key == "spec-key"
    monkeypatch.delenv("CLOVASTUDIO_API_KEY")
    monkeypatch.setenv("CLOVA_STUDIO_API_KEY", "Bearer pr13-key")
    assert Classifier("live").api_key == "pr13-key"


def test_kiwi_hints_go_into_live_request_and_disagreements_are_flagged():
    """kiwi 결합(상권 비서 방식): 힌트를 켜면 모델 요청에 형태소·규칙 추측·비슷한 예문이 들어가고, 모델이 놓친 불만은 경고로 남음."""
    from app import morph
    if not morph.available():
        pytest.skip("kiwipiepy 미설치")
    rows = [r for r in service.sample_reviews() if r.review_id in ("rv_ongi_001", "rv_ongi_006")]
    seen = {}

    def handler(req):
        body = json.loads(req.content)
        seen["system"], seen["user"] = body["messages"][0]["content"], body["messages"][-1]["content"]
        out = [{"review_id": "rv_ongi_001", "sentiment": "negative",
                "topics": [{"topic": "missing_item", "polarity": "negative", "evidence": "안 들어 있었어요"}]},
               {"review_id": "rv_ongi_006", "sentiment": "negative",       # 맛 불만을 일부러 빠뜨림
                "topics": [{"topic": "portion", "polarity": "negative", "evidence": "양도 적고"}]}]
        return httpx.Response(200, json={"result": {"message": {"content": json.dumps(out, ensure_ascii=False)}}})

    res = Classifier("live", api_key="k", transport=httpx.MockTransport(handler), hints=True).classify(rows)
    sent = json.loads(seen["user"][seen["user"].index("\n[\n") + 1:])
    assert "missing_item:-" in sent[0]["rule_guess"] and "/NNG" in sent[0]["morphemes"]
    assert "공깃밥/NNG" in sent[0]["morphemes"]                                 # 사용자 사전: 메뉴 이름이 한 낱말
    assert "[비슷한 예문]" in seen["user"] and "rule_guess" in seen["system"]
    assert not any(t in seen["user"] for t in ("공깃밥 추가했는데 안 들어 있었어요\" (",))  # 평가 리뷰는 예문으로 안 나옴
    assert any("규칙만 찾은 불만 taste" in w for w in res[1].warnings)            # 모델이 놓친 맛 불만을 표시
    assert not any(w.startswith("규칙 비교") for w in res[0].warnings)          # 둘이 같으면 경고 없음

    res_off = Classifier("live", api_key="k", transport=httpx.MockTransport(handler), hints=False).classify(rows)
    assert "rule_guess" not in seen["user"] and "rule_guess" not in seen["system"] and "[비슷한 예문]" not in seen["user"]
    assert not any(w.startswith("규칙 비교") for c in res_off for w in c.warnings)


def test_example_bank_does_not_leak_eval_reviews_and_finds_similar():
    from app import examples
    bank = {e["text"] for e in json.loads(examples.BANK.read_text(encoding="utf-8"))["examples"]}
    evals = {r.text for s in service.store_ids() for r in service.sample_reviews(s)}
    assert not bank & evals                                                   # 평가 세트와 겹치지 않음
    top = examples.similar("치킨무가 안 왔어요", limit=1)[0]
    assert "missing_item:-" in top["topics"]


def test_lexicon_is_a_json_file_teammates_can_edit():
    from app import morph
    lx = morph.lexicon()
    assert "missing_item" in lx["topics"] and "식다" in lx["negative"] and "공깃밥" in morph.user_words()


def test_morph_switch_off_falls_back_to_text_rules(monkeypatch):
    from app import morph
    monkeypatch.setenv("REVIEW_MORPH", "off")
    assert morph.get_analyzer() is None and morph.content_morphemes("식었어요") == []
    assert Classifier("live", api_key="k").hints is False


def test_kiwi_features_typos_clauses_lemma_and_pii():
    """kiwipiepy 0.24 기능을 직접 씀: 오타 교정, token.lemma, 토큰 위치로 구절 나누기, W_ 태그 개인정보."""
    from app import morph
    from app.topics import rule_classify
    if not morph.available():
        pytest.skip("kiwipiepy 미설치")
    got = {(h.topic, h.polarity) for h in rule_classify("x", "맛잇긴한데 양이 저거요", 3, "baemin").topics}
    assert got == {("taste", "positive"), ("portion", "negative")}                  # 오타 교정: 맛잇→맛있다, 저거요→적다
    assert morph.clauses("맛은 있는데 겉이 좀 눅눅했어요") == ["맛은 있는데", "겉이 좀 눅눅했어요"]
    assert morph.clauses("커피는 맛있는데 점심엔 대기가 너무 길어요")[0] == "커피는 맛있는데"   # ETM+데 경계
    assert all(c in "저녁 7시에 시켰는데 1시간 넘게 걸려서 왔어요. 배고파서 혼났네요." for c in morph.clauses("저녁 7시에 시켰는데 1시간 넘게 걸려서 왔어요. 배고파서 혼났네요."))
    assert "퍽퍽하다/VA" in morph.content_morphemes("퍽퍽했어요")                      # token.lemma
    masked, changed = mask_pii("문의 010 1234 5678 / me.owner@shop.kr 2-3인분 12,000원")
    assert changed and "5678" not in masked and "@" not in masked                      # 띄어 쓴 전화번호·이메일 가림
    assert "2-3인분" in masked and "12,000원" in masked                                # 짧은 숫자열·가격은 그대로
    assert morph.pii_spans("연락 a@b.com")                                              # kiwi W_EMAIL
