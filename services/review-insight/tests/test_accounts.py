"""가게 계정: 로그인하면 그 가게의 리뷰만 보인다. 새 계정의 가게는 합성 리뷰 없이 0건에서 시작한다.
시험용 비밀번호는 이 파일 안에서만 쓰는 값이다 (실제 계정 아님)."""
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


def web_app(service_client, token="", base="http://testserver", **kw):
    """비서 화면 서버를 흉내: 방문자 쿠키 → request.state.visitor_id, 그리고 프록시 두 개."""
    web = FastAPI()

    @web.middleware("http")
    async def visitor(request: Request, call_next):
        request.state.visitor_id = request.cookies.get("visitor_id") or "fresh-visitor"
        return await call_next(request)

    api, pages = care_proxy.create_care_routers(base_url=base, token=token, store_id="store_ongi", client=service_client, **kw)
    web.include_router(api)
    web.include_router(pages)
    return TestClient(web)


@pytest.fixture
def svc(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_classifier", Classifier("mock"))
    monkeypatch.setattr(main, "_reader", capture.CaptureReader("mock"))
    return TestClient(main.app)


from app import accounts  # noqa: E402

A = "/api/review-insight"
DEMO_PW, PW = "demo-pass-for-test", "owner-pass-1234"


@pytest.fixture(autouse=True)
def demo_password(monkeypatch):
    monkeypatch.setenv("DEMO_ACCOUNT_PASSWORD", DEMO_PW)
    monkeypatch.delenv("ACCOUNT_SIGNUP_CODE", raising=False)
    accounts._fails.clear()


def join(client, login_id="bunsik", name="우리분식", prefix=A + "/auth/accounts", **extra):
    return client.post(prefix, json={"login_id": login_id, "password": PW, "store_name": name} | extra)


# ── 서비스 (계정 확인·새 가게) ──
def test_demo_accounts_open_the_three_synthetic_stores(svc, monkeypatch):
    for login_id, store in (("ongi", "store_ongi"), ("basak", "store_basak"), ("mongle", "store_mongle")):
        got = svc.post(f"{A}/auth/login", json={"login_id": login_id, "password": DEMO_PW}).json()
        assert got["store_id"] == store and got["demo"] is True and got["store_name"]
    assert svc.post(f"{A}/auth/login", json={"login_id": "ongi", "password": "wrong-password"}).status_code == 401
    monkeypatch.setenv("DEMO_ACCOUNT_PASSWORD", "")            # 비밀번호를 안 정하면 시연용 계정은 닫힘 (빈 비밀번호로도 안 됨)
    assert svc.post(f"{A}/auth/login", json={"login_id": "ongi", "password": ""}).status_code == 401
    assert svc.post(f"{A}/auth/login", json={"login_id": "ongi", "password": DEMO_PW}).status_code == 401


def test_new_account_gets_an_empty_store_of_its_own(svc):
    made = join(svc, business_type_name="분식")
    assert made.status_code == 201 and made.json() == {"login_id": "bunsik", "store_id": "store_bunsik", "store_name": "우리분식", "demo": False}
    q = {"store_id": "store_bunsik"}
    assert svc.get(f"{A}/reviews", params=q).json() == {"items": [], "count": 0}        # 합성 리뷰가 없다
    insight = svc.get(f"{A}/insight", params=q).json()
    assert insight["review_count"] == 0 and insight["complaint_count"] == 0
    for path in ("/response", "/report/daily", "/report/monthly", "/profile", "/inbox", "/promises"):
        assert svc.get(A + path, params=q).status_code == 200, path
    assert svc.get(f"{A}/store", params=q).json()["data_origin"] == "synthetic"
    assert svc.post(f"{A}/auth/login", json={"login_id": "bunsik", "password": PW}).json()["store_id"] == "store_bunsik"
    assert svc.post(f"{A}/auth/login", json={"login_id": "BUNSIK", "password": PW}).status_code == 200      # 아이디는 대소문자 안 가림
    assert svc.post(f"{A}/auth/login", json={"login_id": "bunsik", "password": PW + "x"}).status_code == 401


def test_password_is_stored_only_as_a_hash(svc):
    join(svc)
    saved = (service.RUNTIME / "accounts.json").read_text(encoding="utf-8")
    assert PW not in saved and "salt" in saved and "hash" in saved
    assert PW not in (service.RUNTIME / "stores" / "store_bunsik" / "store.json").read_text(encoding="utf-8")


def test_signup_input_is_checked(svc, monkeypatch):
    for bad in ({"login_id": "ab"}, {"login_id": "Has Space"}, {"login_id": "../etc"}, {"login_id": "ongi"}, {"name": ""}, {"name": "가" * 41}):
        assert join(svc, **bad).status_code == 400, bad
    assert svc.post(f"{A}/auth/accounts", json={"login_id": "shortpw", "password": "1234567", "store_name": "가게"}).status_code == 400
    assert join(svc).status_code == 201 and join(svc).status_code == 400                # 같은 아이디 두 번
    assert sorted(service.made_store_ids()) == ["store_bunsik"]                          # 실패한 가입은 가게를 남기지 않음
    monkeypatch.setenv("ACCOUNT_SIGNUP_CODE", "team-code")
    assert join(svc, "gimbap").status_code == 403 and join(svc, "gimbap", signup_code="team-code").status_code == 201


def test_wrong_password_is_slowed_down(svc):
    join(svc)
    for _ in range(accounts.FAILS_ALLOWED):
        assert svc.post(f"{A}/auth/login", json={"login_id": "bunsik", "password": "wrong-password"}).status_code == 401
    assert svc.post(f"{A}/auth/login", json={"login_id": "bunsik", "password": PW}).status_code == 429       # 맞아도 잠시 막힘
    assert svc.post(f"{A}/auth/login", json={"login_id": "ongi", "password": DEMO_PW}).status_code == 200    # 다른 아이디는 됨


def test_store_id_cannot_point_outside_the_store_folders(svc):
    for bad in ("store_../x", "../store_ongi", "store_ONGI", "x"):
        assert svc.get(f"{A}/reviews", params={"store_id": bad}).status_code == 404
    assert "store_bunsik" not in str(svc.get(f"{A}/reviews", params={"store_id": "store_none"}).json())


# ── 화면 서버 프록시 (로그인 세션) ──
def login(web, login_id, password):
    return web.post("/api/care/auth/login", json={"login_id": login_id, "password": password})


def test_logged_in_owner_sees_only_their_store(svc):
    join(svc)
    ongi, bunsik = web_app(svc), web_app(svc)
    assert login(ongi, "ongi", DEMO_PW).json() == {"logged_in": True, "login_id": "ongi", "store_id": "store_ongi", "store_name": "온기한식 (가상)", "demo": True}
    assert login(bunsik, "bunsik", PW).json()["store_id"] == "store_bunsik"
    assert ongi.get("/api/care/reviews").json()["count"] == 40                # 시연용 계정: 합성 리뷰가 원래 있던 리뷰
    assert bunsik.get("/api/care/reviews").json()["count"] == 0               # 새 계정: 0건
    # 브라우저가 다른 가게를 골라 보내도 자기 가게로 덮어쓴다
    r = bunsik.post("/api/care/reviews?store_id=store_ongi", json={"text": "떡볶이가 너무 불었어요", "rating": 2, "store_id": "store_ongi"})
    assert r.status_code == 201 and r.json()["review"]["store_id"] == "store_bunsik"
    assert bunsik.get("/api/care/reviews", params={"store_id": "store_ongi"}).json()["count"] == 1
    assert ongi.get("/api/care/reviews").json()["count"] == 40
    assert bunsik.get("/api/care/profile").json()["store_id"] == "store_bunsik"
    assert bunsik.get("/api/care/status").json()["store_id"] == "store_bunsik"


def test_same_account_on_another_device_sees_the_same_reviews(svc):
    """로그인하면 시연자별(방문자) 구분이 없다: 같은 계정이면 어느 기기에서든 같은 리뷰·답글."""
    join(svc)
    laptop, phone = web_app(svc), web_app(svc)
    laptop.cookies.set("visitor_id", "visitor-laptop")
    phone.cookies.set("visitor_id", "visitor-phone")
    login(laptop, "bunsik", PW), login(phone, "bunsik", PW)
    rid = laptop.post("/api/care/reviews", json={"text": "순대가 식어서 왔어요", "rating": 2}).json()["review"]["review_id"]
    phone.post(f"/api/care/reviews/{rid}/status", json={"status": "replied", "reply_text": "죄송합니다. 따뜻하게 보내드릴게요."})
    row = laptop.get("/api/care/reviews").json()["items"][0]
    assert row["review_id"] == rid and row["reply"]["text"].startswith("죄송합니다")
    assert svc.get(f"{A}/reviews", params={"store_id": "store_bunsik", "visitor_id": "visitor-laptop", "source": "paste"}).json()["count"] == 0


def test_session_cookie_cannot_be_forged_and_expires(svc):
    join(svc)
    now = {"t": 1_000_000.0}
    web = web_app(svc, clock=lambda: now["t"], login_required=True)
    assert web.get("/api/care/reviews").status_code == 401 and web.get("/api/care/reviews").json()["error"]["state"] == "login_required"
    assert web.get("/api/care/auth/me").json() == {"logged_in": False, "login_required": True, "store_id": None}
    res = login(web, "bunsik", PW)
    cookie = res.cookies["care_session"]
    assert "httponly" in res.headers["set-cookie"].lower() and "samesite=lax" in res.headers["set-cookie"].lower()
    assert PW not in cookie and web.get("/api/care/auth/me").json()["store_id"] == "store_bunsik"
    payload, sig = cookie.split(".")
    import base64
    other = base64.urlsafe_b64encode(base64.urlsafe_b64decode(payload).replace(b"store_bunsik", b"store_ongi")).decode()
    for forged in (f"{other}.{sig}", f"{payload}.{'0' * 64}", payload, "x.y", ""):
        web.cookies.clear()
        web.cookies.set("care_session", forged)
        assert web.get("/api/care/reviews").status_code == 401, forged
    web.cookies.clear()
    web.cookies.set("care_session", cookie)
    assert web.get("/api/care/reviews").status_code == 200
    now["t"] += care_proxy.SESSION_SECONDS + 1
    assert web.get("/api/care/reviews").status_code == 401                    # 12시간 뒤 만료
    assert web_app(svc, session_secret="another-server-key", login_required=True).get(
        "/api/care/reviews", cookies={"care_session": cookie}).status_code == 401


def test_login_failures_logout_and_signup_through_proxy(svc):
    web = web_app(svc)
    bad = login(web, "ongi", "wrong-password")
    assert bad.status_code == 401 and bad.json()["error"]["state"] == "login_failed" and "set-cookie" not in bad.headers
    assert web.post("/api/care/auth/login", content=b"not json", headers={"content-type": "application/json"}).status_code == 422
    made = join(web, "gimbap", "김밥천국 아님", prefix="/api/care/auth/signup")
    assert made.status_code == 201 and made.json()["store_id"] == "store_gimbap"       # 가입하면 바로 로그인 상태
    assert web.get("/api/care/reviews").json()["count"] == 0
    assert web.post("/api/care/auth/logout").json() == {"logged_in": False}
    assert web.get("/api/care/auth/me").json()["logged_in"] is False
    assert web.get("/api/care/reviews").json()["count"] == 40                  # 로그인 안 하면 지금까지처럼 시연 가게 (기본 설정)


def test_without_login_demo_store_still_split_by_visitor(svc):
    web = web_app(svc)
    web.cookies.set("visitor_id", "visitor-a")
    web.post("/api/care/reviews", json={"text": "포장이 새서 국물이 흘렀어요", "rating": 2})
    assert svc.get(f"{A}/reviews", params={"visitor_id": "visitor-a", "source": "paste"}).json()["count"] == 1
