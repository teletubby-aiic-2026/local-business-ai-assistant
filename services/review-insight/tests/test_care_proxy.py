"""통합 키트 시험: integration/care_proxy.py 를 '비서 화면 서버 흉내' 앱에 붙이고, 이 서비스(app.main)를 뒤에 둔 채 끝까지 부른다.
실제 services/web 은 건드리지 않는다. 네트워크 없이 돈다 (서비스는 TestClient 로 같은 프로세스에서)."""
import importlib.util
import io
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from PIL import Image

from app import classify, service
from app.classify import Classifier
from app.sources import capture

spec = importlib.util.spec_from_file_location("care_proxy", Path(__file__).resolve().parents[1] / "integration" / "care_proxy.py")
care_proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(care_proxy)


@pytest.fixture(autouse=True)
def tmp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(classify, "RUNTIME_CACHE", tmp_path / "runtime.json")
    monkeypatch.setattr(classify, "USAGE_LOG", tmp_path / "logs" / "llm_usage.jsonl")
    monkeypatch.setattr(capture, "USAGE_LOG", tmp_path / "logs" / "llm_usage.jsonl")
    from app import care_api
    care_api.LIMITER._hits.clear()


def web_app(service_client, token="", base="http://testserver"):
    """비서 화면 서버를 흉내: 방문자 쿠키 → request.state.visitor_id, 그리고 프록시 두 개."""
    web = FastAPI()

    @web.middleware("http")
    async def visitor(request: Request, call_next):
        request.state.visitor_id = request.cookies.get("visitor_id") or "fresh-visitor"
        return await call_next(request)

    api, pages = care_proxy.create_care_routers(base_url=base, token=token, store_id="store_ongi", client=service_client)
    web.include_router(api)
    web.include_router(pages)
    return TestClient(web)


@pytest.fixture
def svc(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_classifier", Classifier("mock"))
    monkeypatch.setattr(main, "_reader", capture.CaptureReader("mock"))
    return TestClient(main.app)


def test_status_ready_and_down(svc):
    assert web_app(svc).get("/api/care/status").json()["state"] == "ready"

    def dead(request):
        raise httpx.ConnectError("refused")
    down = web_app(httpx.Client(base_url="http://x", transport=httpx.MockTransport(dead)))
    assert down.get("/api/care/status").json()["state"] == "down"
    r = down.get("/api/care/inbox")
    assert r.status_code == 503 and r.json()["error"]["state"] == "down"           # 500 이 아님
    assert web_app(None, base="off").get("/api/care/profile").json()["error"]["state"] == "off"


def test_owner_calls_get_store_and_visitor_from_server_not_browser(svc):
    web = web_app(svc)
    web.cookies.set("visitor_id", "visitor-a")
    # 브라우저가 다른 가게·방문자를 보내도 화면 서버 값으로 덮어씀
    r = web.put("/api/care/profile", json={"store_id": "store_basak", "visitor_id": "someone-else",
                                           "changes": {"reply": {"tone": "friendly"}}})
    assert r.status_code == 200 and r.json()["store_id"] == "store_ongi"
    assert web.get("/api/care/profile", params={"store_id": "store_basak"}).json()["reply"]["tone"] == "friendly"
    assert svc.get("/api/review-insight/profile").json()["reply"]["tone"] == "friendly"         # 가게 정보는 가게 공용
    # 방문자는 서버 값으로 덮어씀: 브라우저가 보낸 someone-else 가 아니라 visitor-a 의 붙여넣기 칸에 저장
    web.post("/api/care/reviews", json={"text": "포장이 새서 국물이 흘렀어요", "rating": 2, "visitor_id": "someone-else"})
    assert svc.get("/api/review-insight/reviews", params={"visitor_id": "visitor-a", "source": "paste"}).json()["count"] == 1
    assert svc.get("/api/review-insight/reviews", params={"visitor_id": "someone-else", "source": "paste"}).json()["count"] == 0


def test_token_is_added_by_server(svc, monkeypatch):
    monkeypatch.setenv("APP_ACCESS_TOKEN", "team-secret")
    assert web_app(svc).get("/api/care/inbox").status_code == 401
    assert web_app(svc, token="team-secret").get("/api/care/inbox").status_code == 200


def test_unknown_paths_are_not_forwarded(svc):
    web = web_app(svc)
    for method, path in (("GET", "/api/care/stores"), ("DELETE", "/api/care/reviews/pasted"), ("GET", "/api/care/../health"),
                         ("POST", "/api/care/public/store_ongi/info")):
        assert web.request(method, path).status_code == 404


def test_public_inquiry_through_proxy_reaches_owner_inbox(svc):
    web = web_app(svc)
    web.cookies.set("visitor_id", "visitor-a")              # 시연: 같은 브라우저 → 그 방문자 받은함
    page = web.get("/s/store_ongi").text
    assert 'content="/api/care/public"' in page and "/api/review-insight/public" not in page
    asked = web.post("/api/care/public/store_ongi/inquiries", json={"text": "토요일 저녁 6시 15명 예약 되나요?"}).json()
    assert asked["forwarded"]
    inbox = web.get("/api/care/inbox", params={"kind": "inquiry"}).json()
    assert inbox["items"][0]["intent"] == "reservation"
    item = inbox["items"][0]["item_id"]
    draft = web.post(f"/api/care/inquiries/{item}/draft").json()
    assert draft["method"] == "template" and draft["draft"]
    web.post(f"/api/care/inquiries/{item}/status", json={"reply_text": "가능해요. 단체석 확인하고 다시 연락드릴게요."})
    assert web.get(f"/api/care/public/store_ongi/inquiries/{asked['code']}").json()["status"] == "answered"
    assert web.get("/api/care/promises").json()["counts"]["check"] == 1


def test_customer_on_another_phone_reaches_owner_inbox(svc):
    """11/15 시뮬레이션에서 0건이던 경우: 손님은 다른 휴대폰(사장님 쿠키 없음)."""
    owner = web_app(svc)
    owner.cookies.set("visitor_id", "visitor-a")
    phone = web_app(svc)                                     # 쿠키 없는 손님
    phone.get("/s/store_ongi")
    asked = phone.post("/api/care/public/store_ongi/inquiries", json={"text": "토요일 6시 10명 예약 되나요?"}).json()
    items = owner.get("/api/care/inbox", params={"kind": "inquiry"}).json()["items"]
    assert len(items) == 1 and items[0]["intent"] == "reservation"
    owner.post(f"/api/care/inquiries/{items[0]['item_id']}/status", json={"reply_text": "가능해요. 단체석 준비할게요."})
    assert phone.get(f"/api/care/public/store_ongi/inquiries/{asked['code']}").json()["status"] == "answered"


def test_capture_upload_through_proxy(svc):
    web = web_app(svc)
    web.cookies.set("visitor_id", "visitor-a")
    buf = io.BytesIO(); Image.new("RGB", (600, 900), "white").save(buf, format="PNG")
    r = web.post("/api/care/reviews/capture", files={"file": ("c.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200 and r.json()["demo"]
    m = web.post("/api/care/profile/menu/capture", files={"file": ("m.png", buf.getvalue(), "image/png")})
    assert m.status_code == 200 and m.json()["candidates"]


def test_reports_and_response_through_proxy(svc):
    web = web_app(svc)
    assert web.get("/api/care/response").json()["store_id"] == "store_ongi"
    assert "summary" in web.get("/api/care/report/daily", params={"date": "2026-11-08"}).json()


def test_foreign_menu_print_through_proxy(svc):
    web = web_app(svc)
    r = web.get("/api/care/menu/foreign/print", params={"lang": "en"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and "size: A4" in r.text
    assert web.get("/api/care/menu/foreign", params={"lang": "zh-CN"}).json()["lang"] == "zh-CN"
