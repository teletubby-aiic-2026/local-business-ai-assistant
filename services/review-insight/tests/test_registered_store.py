"""사장님이 직접 등록한 가게 (6차 회의 11/20): X-IC26-Store-Profile 헤더로 받은 가게. CLOVA 는 가짜, 네트워크 없음.

- 헤더가 오면 그 가게를 알고, 합성 폴더가 없어도 리뷰 0건의 빈 결과를 준다 (500 아님). 헤더 없이 온 모르는 가게는 예전처럼 404.
- 붙여넣으면 예시 가게와 같은 경로로 분류·묶음·반복 불만이 나오고, 상태·답글 기록과 지우기(forget_labels)도 된다.
- 헤더 값이 틀리면(모양·크기·예시 가게 id) 400 이고 요청을 처리하지 않는다.
- 서비스가 다시 켜져 목록이 비어도 다음 요청의 헤더로 바로 안다.
"""
import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import classify, registered, service
from app.classify import Classifier
from shared import store_header

API = "/api/review-insight"
SID = "store_00aa11bb22cc"
VISITOR = "u-0000aaaa1111bbbb"
PROFILE = {"v": 1, "store_id": SID, "name": "우리분식", "business_type_name": "분식전문점", "industry_code": "CS100002",
           "business_status": "operating", "channels": ["배달의민족", "쿠팡이츠", "땡겨요"],
           "menus": [{"name": "떡볶이", "price": 5000}, {"name": "순대", "price": 4500}],
           "location": {"kind": "address", "label": "서울 동작구 상도로 1", "road_address": "서울특별시 동작구 상도로 1",
                        "latitude": 37.5, "longitude": 126.9, "district_name": "동작구"},
           "area": {"area_code": "3110836", "name": "상도역 5번", "period": "20262"}}
HEADER = {store_header.HEADER: store_header.encode(PROFILE)}


@pytest.fixture(autouse=True)
def tmp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(classify, "REPLAY_FILE", tmp_path / "replay.json")
    monkeypatch.setattr(classify, "RUNTIME_CACHE", tmp_path / "runtime.json")
    monkeypatch.setattr(classify, "USAGE_LOG", tmp_path / "logs" / "llm_usage.jsonl")
    reg = registered.registry()
    reg.clear()
    yield
    reg.clear()


def _fake_model():
    """리뷰마다 '포장 누락' 불만 하나 (근거는 글 앞 4자)."""
    def handler(req):
        body = json.loads(req.content)
        user = body["messages"][-1]["content"]
        rows = json.loads(user[user.index("\n[\n") + 1:])
        out = [{"review_id": r["review_id"], "sentiment": "negative", "summary": "요약",
                "topics": [{"topic": "missing_item", "polarity": "negative", "evidence": r["text"][:4]}]} for r in rows]
        return httpx.Response(200, json={"result": {"message": {"content": json.dumps(out, ensure_ascii=False)}}})
    return httpx.MockTransport(handler)


@pytest.fixture
def client(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_classifier", Classifier("live", api_key="k", transport=_fake_model(), hints=False))
    return TestClient(main.app)


def paste(client, text, headers=HEADER):
    return client.post(f"{API}/reviews", json={"store_id": SID, "text": text, "rating": 1, "channel": "baemin",
                                               "visitor_id": VISITOR}, headers=headers)


def test_unknown_store_without_header_is_404_as_before(client):
    res = client.get(f"{API}/insight", params={"store_id": SID})
    assert res.status_code == 404 and res.json()["error"]["code"] == "STORE_NOT_FOUND"
    assert res.json()["error"]["details"]["stores"] == service.store_ids()          # 예시 가게 목록 그대로


def test_zero_reviews_is_an_empty_result_not_an_error(client):
    store = client.get(f"{API}/store", params={"store_id": SID}, headers=HEADER).json()
    assert store == {"store_id": SID, "name": "우리분식", "business_type": "CS100002", "business_type_name": "분식전문점",
                     "channels": ["baemin", "coupangeats"], "menu": ["떡볶이", "순대"], "data_origin": "real",
                     "registered": True}
    ins = client.get(f"{API}/insight", params={"store_id": SID, "visitor_id": VISITOR}, headers=HEADER)
    assert ins.status_code == 200, ins.text
    d = ins.json()
    assert (d["review_count"], d["complaint_count"], d["groups"], d["top_issue_id"], d["single_complaints"]) == (0, 0, [], None, [])
    assert client.get(f"{API}/reviews", params={"store_id": SID}, headers=HEADER).json() == {"items": [], "count": 0}
    # 이후 요청은 헤더 없이도 이 프로세스가 기억한다 (화면 서버는 늘 헤더를 싣는다)
    assert client.get(f"{API}/insight", params={"store_id": SID}).status_code == 200


def test_care_endpoints_work_at_zero_reviews(client):
    params = {"store_id": SID, "visitor_id": VISITOR, "now": "2026-11-20T12:00:00+09:00"}
    res = client.get(f"{API}/response", params=params, headers=HEADER)
    assert res.status_code == 200, res.text
    assert res.json()["store_id"] == SID
    for path in ("inbox", "promises"):
        assert client.get(f"{API}/{path}", params=params, headers=HEADER).status_code == 200, path
    prof = client.get(f"{API}/profile", params={"store_id": SID}, headers=HEADER).json()
    assert [(m["name"], m["price"]) for m in prof["menu"]] == [("떡볶이", 5000), ("순대", 4500)]
    assert prof["basic"]["address"] == "서울특별시 동작구 상도로 1"
    assert prof["reply"]["sign_off"] == "우리분식 드림"


def test_paste_classifies_groups_and_records_like_sample_stores(client):
    first = paste(client, "떡볶이 소스가 빠져 왔어요")
    assert first.status_code == 201, first.text
    body = first.json()
    rid = body["review"]["review_id"]
    assert rid == "rv_00aa11bb22cc_paste_001" and body["review"]["store_id"] == SID
    assert body["classification"]["negative_topics"] == ["missing_item"] and body["groups"] == []
    paste(client, "순대 소금이 빠져 있었어요")
    third = paste(client, "어묵 국물이 빠졌네요").json()
    assert third["review_count"] == 3 and third["complaint_count"] == 3
    assert third["top_issue_id"] == "iss_missing_item" and third["groups"][0]["is_repeated"] is True
    ins = client.get(f"{API}/insight", params={"store_id": SID, "visitor_id": VISITOR}, headers=HEADER).json()
    assert ins["top_issue_id"] == "iss_missing_item" and ins["groups"][0]["review_count"] == 3
    # 다른 방문자에게는 보이지 않는다
    other = client.get(f"{API}/insight", params={"store_id": SID, "visitor_id": "u-other"}, headers=HEADER).json()
    assert other["review_count"] == 0
    # 답글 승인 기록 → 응대 점수에 반영
    res = client.post(f"{API}/reviews/{rid}/status", json={"status": "replied", "reply_text": "죄송합니다", "store_id": SID,
                                                          "visitor_id": VISITOR}, headers=HEADER)
    assert res.status_code == 200 and res.json()["review"]["reply"]["text"] == "죄송합니다"
    # 계정 초기화·탈퇴: 붙여넣은 리뷰·기록·분류 결과를 지운다
    erased = client.delete(f"{API}/reviews/pasted", params={"store_id": SID, "visitor_id": VISITOR, "forget_labels": "true"},
                           headers=HEADER).json()
    assert erased == {"deleted": 3, "labels_deleted": 3}
    after = client.get(f"{API}/insight", params={"store_id": SID, "visitor_id": VISITOR}, headers=HEADER).json()
    assert after["review_count"] == 0


def test_restart_first_request_with_header_just_works(client):
    assert paste(client, "떡볶이 소스가 빠져 왔어요").status_code == 201
    registered.registry().clear()                      # 서비스가 다시 켜진 것과 같음 (붙여넣은 리뷰 파일은 그대로)
    assert client.get(f"{API}/insight", params={"store_id": SID, "visitor_id": VISITOR}).status_code == 404
    res = client.get(f"{API}/insight", params={"store_id": SID, "visitor_id": VISITOR}, headers=HEADER)
    assert res.status_code == 200 and res.json()["review_count"] == 1


def _raw(data) -> str:
    return base64.urlsafe_b64encode(json.dumps(data, ensure_ascii=False).encode()).decode().rstrip("=")


@pytest.mark.parametrize("value", [
    "not base64 !!",
    _raw(["list"]),
    _raw({**PROFILE, "store_id": "store_ongi"}),                     # 예시 가게를 덮어쓰려는 값
    _raw({**PROFILE, "store_id": "store_00AA11BB22CC"}),
    _raw({**PROFILE, "v": 2}),
    _raw({**PROFILE, "name": ""}),
    _raw({**PROFILE, "menus": [{"name": "떡볶이", "price": -1}]}),
    _raw({**PROFILE, "menus": [{"name": f"메뉴{i}", "price": 1} for i in range(31)]}),
    _raw({**PROFILE, "area": {"area_code": "12", "name": "x"}}),
    "A" * (store_header.MAX_HEADER + 1),                            # 너무 큼
])
def test_bad_header_is_400_and_registers_nothing(client, value):
    res = client.get(f"{API}/store", params={"store_id": "store_ongi"}, headers={store_header.HEADER: value})
    assert res.status_code == 400 and res.json()["error"]["code"] == "VALIDATION_ERROR"
    assert registered.get("store_ongi") is None and registered.get(SID) is None


def test_sample_store_answers_are_unchanged_by_the_registry(client):
    before = client.get(f"{API}/store", params={"store_id": "store_basak"}).json()
    client.get(f"{API}/insight", params={"store_id": SID}, headers=HEADER)
    assert client.get(f"{API}/store", params={"store_id": "store_basak"}).json() == before
    assert client.get(f"{API}/stores").json()["count"] == 3
