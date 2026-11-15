"""가상 배달앱 주소 시험. 키·네트워크 없이 돕니다 (리뷰 분석 서비스는 가짜 응답)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shop_routes import NOTICE, POSTS_PER_MINUTE, create_shop_router  # noqa: E402

PROFILE = {
    "store_id": "store_ongi", "data_origin": "synthetic",
    "basic": {"hours": {"mon": "11:00-21:00", "sun": "휴무"}, "break_time": "15:00-17:00", "last_order": "20:30",
              "holidays": "매주 일요일", "address": "서울 동작구 (가상 주소)", "phone": None},
    "order": {"delivery_area": "장승배기역 반경 2km", "min_order": 12000, "takeout": True},
    "menu": [{"name": "제육볶음 정식", "price": 9500, "ingredients": ["돼지고기"], "spicy": 2, "allergens": ["돼지고기"], "recommended": True, "sold_out": False},
             {"name": "계란말이", "price": 6000, "ingredients": ["계란"], "spicy": 0, "allergens": ["계란"], "recommended": False, "sold_out": False}],
    "reply": {"tone": "polite", "sla_minutes": 30}, "answers": [{"q": "주차", "a": "2대"}],
    "today": {"date": "2026-11-16", "day": "월", "hours": "11:00-21:00", "sold_out": ["계란말이"]},
    "active_notices": [{"text": "오늘 재료 소진 시 일찍 닫아요"}],
}
SAMPLE = {"review_id": "rv_ongi_001", "text": "맛있어요", "rating": 5, "created_at": "2026-11-08T12:00:00+09:00", "input_method": "sample",
          "source": "sample", "received_at": None, "reply": None, "status": "new", "pii_masked": False, "store_id": "store_ongi"}


class FakeService:
    """리뷰 분석 서비스 흉내: 배달앱 리뷰는 가게 공용 칸에 쌓인다 (방문자 없이 부르면 공용 칸)."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.rows: list[dict] = []
        self.fail: str | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.fail == "down":
            raise httpx.ConnectError("refused")
        if self.fail == "slow":
            raise httpx.ReadTimeout("slow")
        path, q = request.url.path, dict(request.url.params)
        asked = q.get("store_id") or (json.loads(request.content).get("store_id") if request.method == "POST" else None)
        if asked == "store_none":
            return httpx.Response(404, json={"error": {"code": "STORE_NOT_FOUND", "message": "없는 가게입니다: store_none"}})
        if path == "/api/health":
            return httpx.Response(200, json={"status": "ok", "mode": "mock", "data_origin": "synthetic"})
        if path == "/api/review-insight/profile":
            return httpx.Response(200, json=PROFILE)
        if path == "/api/review-insight/public/store_ongi/info":
            return httpx.Response(200, json={"name": "온기한식 (가상)", "business_type_name": "한식음식점"})
        if path == "/api/review-insight/reviews" and request.method == "GET":
            rows = [SAMPLE] + self.rows
            return httpx.Response(200, json={"items": rows, "count": len(rows)})
        if path == "/api/review-insight/reviews" and request.method == "POST":
            body = json.loads(request.content)
            if body["text"] == "거절":
                return httpx.Response(400, json={"error": {"code": "VALIDATION_ERROR", "message": "리뷰 글을 확인해 주세요", "request_id": "r1"}})
            mine = self.rows
            row = {"review_id": f"rv_ongi_app_{len(mine) + 1:03d}", "text": body["text"], "rating": body["rating"], "input_method": "paste",
                   "source": body["source"], "menu": body.get("menu"), "created_at": "2026-11-08T23:00:00+09:00", "received_at": "2026-11-15T12:00:00+09:00",
                   "reply": None, "status": "analyzed", "store_id": body["store_id"]}
            mine.append(row)
            return httpx.Response(201, json={"review": row, "classification": {"sentiment": "negative"}, "groups": []})
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})


def make(*, token="tok", **kw):
    service = FakeService()
    http = httpx.Client(transport=httpx.MockTransport(service), base_url="http://service")
    ticks = {"now": 0.0}
    app = FastAPI()

    app.include_router(create_shop_router(client=http, token=token, clock=lambda: ticks["now"], **kw))
    return TestClient(app), service, ticks


def post(client, text="공깃밥이 빠졌어요", rating=2, menu=None, **kw):
    return client.post("/api/shop/reviews", json={"text": text, "rating": rating} | ({} if menu is None else {"menu": menu}), **kw)


def test_pages_and_only_listed_files():
    client, _, _ = make()
    page = client.get("/shop/")
    assert page.status_code == 200 and NOTICE in page.text
    assert client.get("/shop/app.js").status_code == 200 and client.get("/shop/style.css").status_code == 200
    assert client.get("/shop/..%2Fshop_routes.py").status_code == 404
    assert client.get("/shop/run_local.py").status_code == 404
    assert client.get("/shop", follow_redirects=False).headers["location"] == "/shop/"


def test_store_shows_only_customer_fields():
    client, service, _ = make()
    data = client.get("/api/shop/store").json()
    assert data["name"] == "온기한식 (가상)" and data["min_order"] == 12000 and data["notice"] == NOTICE
    assert [m["name"] for m in data["menu"]] == ["제육볶음 정식", "계란말이"]
    assert data["menu"][1]["sold_out"] is True                      # 오늘 품절 목록 반영
    assert data["notices"] == ["오늘 재료 소진 시 일찍 닫아요"]
    assert "reply" not in data and "answers" not in data            # 사장님 설정은 손님에게 안 나감
    assert all(c.headers.get("x-access-token") == "tok" for c in service.calls)


def test_review_is_sent_as_shared_app_review_with_menu():
    client, service, _ = make()
    r = post(client, menu=" 제육볶음 정식 ")
    assert r.status_code == 201
    sent = json.loads(service.calls[-1].content)
    assert sent == {"store_id": "store_ongi", "text": "공깃밥이 빠졌어요", "rating": 2, "source": "app", "menu": "제육볶음 정식"}   # 방문자 없음
    assert set(r.json()["review"]) == {"id", "text", "rating", "at", "from_app", "menu", "reply"}      # 분류 결과는 손님에게 안 나감
    assert r.json()["review"]["at"] == "2026-11-15T12:00:00+09:00"                              # 발표 장면 시각이 아니라 받은 시각
    assert r.json()["review"]["menu"] == "제육볶음 정식"


def test_menu_is_optional_and_checked():
    client, service, _ = make()
    assert post(client).status_code == 201 and "menu" not in json.loads(service.calls[-1].content)
    n = len(service.calls)
    assert post(client, menu="가" * 41).status_code == 400 and post(client, menu=3).status_code == 400
    assert len(service.calls) == n


def test_browser_cannot_choose_store_or_visitor():
    client, service, _ = make()
    client.post("/api/shop/reviews?visitor_id=v_other&store_id=store_x", json={"text": "맛있어요", "rating": 5, "visitor_id": "v_other", "store_id": "store_x", "source": "paste"})
    sent = json.loads(service.calls[-1].content)
    assert "visitor_id" not in sent and sent["store_id"] == "store_ongi" and sent["source"] == "app"
    client.get("/api/shop/reviews?visitor_id=v_other&store_id=store_x")
    assert dict(service.calls[-1].url.params) == {"store_id": "store_ongi"}


def test_reviews_list_app_first_with_reply_and_average():
    client, service, _ = make()
    post(client, "맛있어요!", 4, menu="계란말이")
    service.rows[0]["reply"] = {"text": "감사합니다", "replied_at": "2026-11-15T12:10:00+09:00"}
    service.rows.append({"review_id": "rv_ongi_paste_002", "text": "사장님이 붙여넣은 리뷰", "rating": 1, "source": "paste",
                         "created_at": "2026-11-08T23:01:00+09:00", "received_at": "2026-11-15T12:01:00+09:00", "reply": None})
    data = client.get("/api/shop/reviews").json()
    assert data["count"] == 2 and data["items"][0]["from_app"] is True          # 합성 + 배달앱 리뷰만 (붙여넣은 리뷰는 안 보임)
    assert data["items"][0]["menu"] == "계란말이" and data["items"][1]["menu"] is None
    assert data["items"][0]["reply"] == {"text": "감사합니다", "at": "2026-11-15T12:10:00+09:00"}
    assert data["average"] == 4.5 and data["by_rating"]["5"] == 1 and data["by_rating"]["4"] == 1
    assert "status" not in data["items"][0] and "input_method" not in data["items"][0]


def test_input_checked_before_calling_service():
    client, service, _ = make()
    before = len(service.calls)
    assert post(client, "", 3).status_code == 400
    assert post(client, "가" * 1001, 3).status_code == 400
    assert post(client, "맛있어요", 0).status_code == 400
    assert post(client, "맛있어요", True).status_code == 400
    assert client.post("/api/shop/reviews", content=b"x", headers={"content-type": "application/json"}).status_code == 422
    assert client.post("/api/shop/reviews", content=b"{" + b" " * 20000 + b"}", headers={"content-type": "application/json"}).status_code == 413
    assert len(service.calls) == before
    r = post(client, "거절", 3)                                                       # 서비스의 입력 오류 글은 그대로 전함
    assert r.status_code == 400 and r.json()["error"]["message"] == "리뷰 글을 확인해 주세요"
    assert "request_id" not in json.dumps(r.json())


def test_rate_limit_per_address():
    client, _, ticks = make()
    for _ in range(POSTS_PER_MINUTE):
        assert post(client).status_code == 201
    assert post(client).status_code == 429
    assert post(client, headers={"x-forwarded-for": "203.0.113.9"}).status_code == 201   # 다른 손님은 됨
    ticks["now"] = 61
    assert post(client).status_code == 201


def test_service_trouble_never_500():
    client, service, _ = make()
    service.fail = "down"
    assert client.get("/api/shop/status").json()["state"] == "down"
    for r in (client.get("/api/shop/store"), client.get("/api/shop/reviews"), post(client)):
        assert r.status_code == 503 and r.json()["error"]["state"] == "down"
    service.fail = "slow"
    assert post(client, headers={"x-forwarded-for": "203.0.113.7"}).json()["error"]["state"] == "slow"
    off, _, _ = make(base_url="off")
    assert off.get("/api/shop/status").json()["state"] == "off" and off.get("/api/shop/reviews").status_code == 503
    assert off.get("/shop/").status_code == 200                                      # 화면은 열림


def test_no_token_header_when_token_empty():
    client, service, _ = make(token="")
    assert post(client).status_code == 201
    assert "x-access-token" not in service.calls[-1].headers


def test_store_can_be_chosen_by_address_but_only_valid_ids():
    client, service, _ = make()
    client.get("/api/shop/reviews?store=store_bunsik")
    assert dict(service.calls[-1].url.params) == {"store_id": "store_bunsik"}
    assert post_to(client, "store_bunsik").status_code == 201 and json.loads(service.calls[-1].content)["store_id"] == "store_bunsik"
    assert client.get("/api/shop/status?store=store_bunsik").json()["store_id"] == "store_bunsik"
    n = len(service.calls)
    for bad in ("store_../x", "STORE_X", "ongi", "store_" + "a" * 41):
        r = client.get("/api/shop/reviews", params={"store": bad})
        assert r.status_code == 404 and r.json()["error"]["state"] == "no_store", bad
        assert post_to(client, bad).status_code == 404
    assert len(service.calls) == n                                   # 형식이 틀리면 서비스를 부르지 않음
    r = client.get("/api/shop/store?store=store_none")               # 형식은 맞지만 없는 가게
    assert r.status_code == 404 and r.json()["error"]["state"] == "no_store"


def post_to(client, store):
    return client.post("/api/shop/reviews", params={"store": store}, json={"text": "떡볶이가 불었어요", "rating": 2})
