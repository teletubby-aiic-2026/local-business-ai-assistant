"""상권 분석 화면(#/market) 프록시 /api/market/* (5차 회의 11/18). 가짜 상권 서비스(httpx.MockTransport), 네트워크 없음.

지키는 것: Host 고정, 서랍과 따로인 세션 쿠키(경로 /api/market), 넘기는 쿼리만, 가게마다 기본 조건, 장애 때 503(500 없음)·status 200,
사람이 읽는 칸만 분기 코드를 '2026년 2분기'로.

실행 (services/web 에서):  env -u APP_MODE PYTHONPATH=../.. python -m pytest -q tests/test_market_proxy.py
"""
from __future__ import annotations

import json
import re
import secrets
import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from shared.storage import MemoryStore
from tests.test_web import FakeSource, settings
from web.assistant_proxy import STORE_DEFAULTS, AssistantProxy, MarketClient
from web.auth import AuthService
from web.care_proxy import CareProxy
from web.demo import Demo
from web.main import create_app
from web.market_proxy import MarketProxy, present
from web.marketing_proxy import MarketingProxy

COOKIE = "market_onboarding_session"


class FakeMarket:
    """상권 서비스의 /health·/api/onboarding/* 겉모습 (응답 모양은 실제 서비스에서 뽑은 것을 줄임)."""

    def __init__(self, mode="ok", data_ready=True):
        self.mode, self.data_ready = mode, data_ready
        self.requests: list[dict] = []
        self.sessions: dict[str, dict] = {}
        self.reply: dict[str, tuple[int, object]] = {}      # 경로 → (상태, 본문) 덮어쓰기

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        rec = {"method": request.method, "path": request.url.path, "params": dict(request.url.params),
               "host": request.headers.get("host"), "cookie": request.headers.get("cookie"), "json": body,
               "timeout": request.extensions.get("timeout")}
        self.requests.append(rec)
        if self.mode == "down":
            raise httpx.ConnectError("refused")
        if self.mode == "500":
            return httpx.Response(500, text="oops")
        if request.headers.get("host") != "127.0.0.1:8766":
            return httpx.Response(400, text="Invalid host header")
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"service": "seoul-market-analysis", "status": "ok"})
        match = re.search(rf"{COOKIE}=([A-Za-z0-9_-]{{43}})", request.headers.get("cookie", ""))
        token = match.group(1) if match else secrets.token_urlsafe(32)
        s = self.sessions.setdefault(token, {"revision": 0, "profile": None, "selection": None})
        headers = {"set-cookie": f"{COOKIE}={token}; HttpOnly; Path=/; SameSite=strict"}
        name = path.removeprefix("/api/onboarding/")
        if name in self.reply:
            status, data = self.reply[name]
            return httpx.Response(status, json=data, headers=headers)
        state = lambda: {"revision": s["revision"], "profile": s["profile"], "analysis_selection": s["selection"],
                         "conditions_confirmed": bool(s["selection"] and s["profile"])}
        if name == "data-status":
            return httpx.Response(200, json={"status": "ready" if self.data_ready else "data_required",
                                             "data_ready": self.data_ready, "latest_period": "20262" if self.data_ready else None,
                                             "message": "20262 까지 준비"}, headers=headers)
        if (request.method, name) == ("GET", "analysis-selection"):
            return httpx.Response(200, json=state(), headers=headers)
        if (request.method, name) == ("POST", "profile"):
            s["revision"] += 1
            s["selection"] = None
            s["profile"] = {"location": {**body["location"], "label": "역"}, "industry": {"code": body["industry_code"], "name": "업종"}}
            return httpx.Response(200, json=state(), headers=headers)
        if name == "analysis-options":
            codes = ["3110826", "3110836", "3120154"]
            return httpx.Response(200, json={"catalog_version": "c1", "candidates": [
                {"area_code": c, "name": f"상권 {c}", "relation": "inside", "available_periods": ["20261", "20262"]} for c in codes]},
                headers=headers)
        if (request.method, name) == ("POST", "analysis-selection"):
            s["revision"] += 1
            s["selection"] = {"area_code": body["area_code"], "area_name": f"상권 {body['area_code']}", "period": body["period"]}
            return httpx.Response(200, json=state(), headers=headers)
        if name == "sales":
            return httpx.Response(200, json={"status": "available", "selection": {"period": "20262"},
                                             "total": {"value": 20262, "value_text": "20262", "label": "20262 분기 추정매출"},
                                             "message": "20262 자료예요"}, headers=headers)
        return httpx.Response(200, json={"ok": True, "name": name}, headers=headers)


def build(fake: FakeMarket | None = None, *, market: MarketProxy | None = None):
    tmp = Path(tempfile.mkdtemp())
    fake = fake or FakeMarket()
    market = market or MarketProxy(MarketClient("http://market.test", "127.0.0.1:8766", read_timeout=5.0,
                                                transport=httpx.MockTransport(fake)))
    storage = MemoryStore()
    demo = Demo(settings(tmp), source=FakeSource(), storage=storage)
    app = create_app(demo, assistant=AssistantProxy(None), care=CareProxy(None), marketing=MarketingProxy(None),
                     auth=AuthService(storage), market=market)
    return TestClient(app), fake


class Status(unittest.TestCase):
    def test_ready_no_data_off_and_down_are_all_200(self):
        client, _ = build()
        data = client.get("/api/market/status").json()
        self.assertEqual((data["state"], data["store"]["store_id"]), ("ready", "store_ongi"))
        self.assertEqual(build(FakeMarket(data_ready=False))[0].get("/api/market/status").json()["state"], "no_data")
        off = build(market=MarketProxy(None))[0].get("/api/market/status")
        self.assertEqual((off.status_code, off.json()["state"]), (200, "off"))
        down = build(FakeMarket(mode="down"))[0].get("/api/market/status")
        self.assertEqual((down.status_code, down.json()["state"]), (200, "down"))


class Relay(unittest.TestCase):
    def setUp(self):
        self.client, self.fake = build()

    def test_host_query_allow_list_and_own_session_cookie(self):
        res = self.client.get("/api/market/sales?expected_revision=3&store_id=x&visitor_id=y&debug=1")
        self.assertEqual(res.status_code, 200, res.text)
        req = self.fake.requests[-1]
        self.assertEqual((req["host"], req["path"], req["params"]), ("127.0.0.1:8766", "/api/onboarding/sales", {"expected_revision": "3"}))
        cookie = next(h for h in res.headers.get_list("set-cookie") if h.startswith(COOKIE))
        self.assertIn("Path=/api/market", cookie)
        self.assertIn("httponly", cookie.lower())
        token = re.search(rf"{COOKIE}=([A-Za-z0-9_-]{{43}})", cookie).group(1)
        self.client.get("/api/market/stores")
        self.assertIn(token, self.fake.requests[-1]["cookie"])          # 같은 세션으로 이어 부름

    def test_only_reader_text_gets_quarter_words(self):
        data = self.client.get("/api/market/sales").json()
        self.assertEqual(data["message"], "2026년 2분기 자료예요")
        self.assertEqual(data["total"]["label"], "2026년 2분기 추정매출")       # '20262 분기' 는 '분기'까지 한 번에
        self.assertEqual((data["total"]["value"], data["total"]["value_text"]), (20262, "20262"))   # 숫자는 그대로
        self.assertEqual(data["selection"]["period"], "20262")
        self.assertEqual(data["selection"]["period_label"], "2026년 2분기")
        self.assertEqual(present({"value_text": "20262", "notes": ["20262 기준"]}), {"value_text": "20262", "notes": ["2026년 2분기 기준"]})

    def test_changes_and_comparison_pass_their_query(self):
        self.client.get("/api/market/changes?comparison=yoy&expected_revision=2&x=1")
        self.assertEqual(self.fake.requests[-1]["params"], {"comparison": "yoy", "expected_revision": "2"})
        self.client.get("/api/market/comparison?comparison_area_code=3110826")
        self.assertEqual(self.fake.requests[-1]["params"], {"comparison_area_code": "3110826"})

    def test_cultural_events_defaults_to_the_store_district(self):
        self.client.get("/api/market/cultural-events")
        self.assertEqual(self.fake.requests[-1]["params"], {"district": "동작구"})
        self.client.get("/api/market/cultural-events?district=관악구")
        self.assertEqual(self.fake.requests[-1]["params"], {"district": "관악구"})

    def test_data_sync_is_post_with_a_long_wait(self):
        self.assertEqual(self.client.get("/api/market/data-sync").status_code, 405)
        res = self.client.post("/api/market/data-sync", json={})
        self.assertEqual(res.status_code, 200, res.text)
        req = self.fake.requests[-1]
        self.assertEqual((req["method"], req["path"]), ("POST", "/api/onboarding/data-sync"))
        self.assertGreaterEqual(req["timeout"]["read"], 60)

    def test_unknown_paths_big_bodies_and_bad_json(self):
        self.assertEqual(self.client.get("/api/market/context").status_code, 404)
        self.assertEqual(self.client.post("/api/market/profile", content=b"x" * 5000,
                                          headers={"content-type": "application/json"}).status_code, 413)
        self.assertEqual(self.client.post("/api/market/profile", content=b"[1]",
                                          headers={"content-type": "application/json"}).status_code, 422)


class Failures(unittest.TestCase):
    def test_upstream_input_errors_pass_and_outages_are_503_never_500(self):
        fake = FakeMarket()
        client, _ = build(fake)
        fake.reply["comparison"] = (422, {"detail": "비교할 상권을 골라 주세요"})
        res = client.get("/api/market/comparison?comparison_area_code=1234567")
        self.assertEqual((res.status_code, res.json()["error"]["message"]), (422, "비교할 상권을 골라 주세요"))
        fake.reply["sales"] = (409, {"detail": "분석 조건이 변경됐습니다."})
        self.assertEqual(client.get("/api/market/sales").status_code, 409)
        for mode in ("down", "500"):
            client2, _ = build(FakeMarket(mode=mode))
            res = client2.get("/api/market/sales")
            self.assertEqual(res.status_code, 503, mode)
            self.assertIn("state", res.json()["error"])
            self.assertEqual(client2.get("/api/health").status_code, 200)       # 다른 화면은 그대로
            self.assertEqual(client2.get("/api/briefing").status_code, 200)
        off = build(market=MarketProxy(None))[0].get("/api/market/sales")
        self.assertEqual((off.status_code, off.json()["error"]["state"]), (503, "off"))


# 주소 글의 건물 번호 '20241' 은 분기 코드처럼 보여서 present() 를 거치면 '2024년 1분기'가 된다 (그래서 지도·주소 경로는 그대로 넘긴다)
ADDRESS = "서울특별시 동작구 상도로 20241"
SEARCH_REPLY = {"status": "address_candidate", "message": f"{ADDRESS} 이 맞나요?", "search_id": "s1", "candidates": [
    {"id": "c1", "label": ADDRESS, "road_address": ADDRESS, "jibun_address": "서울특별시 동작구 상도동 20231",
     "latitude": 37.5045, "longitude": 126.9393, "in_seoul": True}]}


class MapAndLocations(unittest.TestCase):
    """지도·위치 경로 3개 (11/20, 6차 회의 ⑥): map-config(GET) · locations/search(POST) · locations/area-preview(POST)."""

    def test_present_would_change_the_address_so_these_paths_skip_it(self):
        self.assertEqual(present({"label": ADDRESS})["label"], "서울특별시 동작구 상도로 2024년 1분기")

    def test_map_config_passes_only_the_public_id_and_configured(self):
        client, fake = build()
        fake.reply["map-config"] = (200, {"client_id": " abc_DEF-123 ", "configured": True, "client_secret": "s3cret",
                                          "env": {"NAVER_MAPS_CLIENT_SECRET": "x"}, "message": "20262"})
        res = client.get("/api/market/map-config")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {"client_id": "abc_DEF-123", "configured": True})
        self.assertNotIn("s3cret", res.text)
        req = fake.requests[-1]
        self.assertEqual((req["method"], req["path"], req["host"]), ("GET", "/api/onboarding/map-config", "127.0.0.1:8766"))
        self.assertEqual(res.headers["cache-control"], "no-store")
        for upstream in ({"client_id": "", "configured": False}, {"client_id": "abc", "configured": False},
                         {"client_id": "a b<script>", "configured": True}, {"configured": True}, ["abc"]):
            fake.reply["map-config"] = (200, upstream)
            self.assertEqual(client.get("/api/market/map-config").json(), {"client_id": "", "configured": False}, upstream)
        self.assertEqual(client.post("/api/market/map-config", json={}).status_code, 405)

    def test_location_search_forwards_the_body_and_keeps_the_address_text(self):
        client, fake = build()
        fake.reply["locations/search"] = (200, SEARCH_REPLY)
        res = client.post("/api/market/locations/search", json={"query": "상도로 20241 장승배기역 근처 가게 주소 길게"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), SEARCH_REPLY)                                      # 주소 글·좌표 그대로
        req = fake.requests[-1]
        self.assertEqual((req["method"], req["path"], req["params"]), ("POST", "/api/onboarding/locations/search", {}))
        self.assertEqual(req["json"], {"query": "상도로 20241 장승배기역 근처 가게 주소 길게"})   # 20자를 넘어도 본문은 그대로
        self.assertIn(COOKIE, " ".join(res.headers.get_list("set-cookie")))              # 상권 세션을 이어 받음 (검색 결과는 그 세션에 남음)
        self.assertEqual(client.get("/api/market/locations/search?query=x").status_code, 405)
        fake.reply["locations/search"] = (429, {"detail": "주소 조회 중입니다. 잠시 후 다시 시도해 주세요."})
        busy = client.post("/api/market/locations/search", json={"query": "상도로"})
        self.assertEqual((busy.status_code, busy.json()["error"]["message"]), (422, "주소 조회 중입니다. 잠시 후 다시 시도해 주세요."))

    def test_area_preview_forwards_the_body_and_keeps_the_address_text(self):
        client, fake = build()
        reply = {**SEARCH_REPLY, "status": "area_candidate"}
        fake.reply["locations/area-preview"] = (200, reply)
        body = {"kind": "area", "text": "상도동", "district_code": "11590", "neighborhood_code": "1159051000"}
        res = client.post("/api/market/locations/area-preview", json=body)
        self.assertEqual((res.status_code, res.json()), (200, reply))
        req = fake.requests[-1]
        self.assertEqual((req["method"], req["path"], req["json"]), ("POST", "/api/onboarding/locations/area-preview", body))
        fake.reply["locations/area-preview"] = (422, {"detail": "동네 이름을 입력해 주세요. 예: 연남동."})
        bad = client.post("/api/market/locations/area-preview", json={"kind": "area", "text": "동"})
        self.assertEqual((bad.status_code, bad.json()["error"]["message"]), (422, "동네 이름을 입력해 주세요. 예: 연남동."))

    def test_outage_is_503_never_500_and_off_is_503(self):
        calls = (("get", "/api/market/map-config", None), ("post", "/api/market/locations/search", {"query": "상도로"}),
                 ("post", "/api/market/locations/area-preview", {"kind": "area", "text": "상도동"}))
        for mode in ("down", "500"):
            client, _ = build(FakeMarket(mode=mode))
            for method, path, body in calls:
                res = getattr(client, method)(path, **({"json": body} if body is not None else {}))
                self.assertEqual(res.status_code, 503, (mode, path))
                self.assertIn(res.json()["error"]["state"], ("down", "error"), (mode, path))
            self.assertEqual(client.get("/api/health").status_code, 200)
        off, _ = build(market=MarketProxy(None))
        for method, path, body in calls:
            res = getattr(off, method)(path, **({"json": body} if body is not None else {}))
            self.assertEqual((res.status_code, res.json()["error"]["state"]), (503, "off"), path)


class SetupPerStore(unittest.TestCase):
    def test_guest_gets_the_default_store_conditions(self):
        client, fake = build()
        data = client.post("/api/market/setup").json()
        self.assertEqual((data["status"], data["conditions"]["area_code"], data["conditions"]["home"]),
                         ("ok", "3110826", True))
        profile = next(r for r in fake.requests if r["method"] == "POST" and r["path"].endswith("/profile"))
        self.assertEqual((profile["json"]["industry_code"], profile["json"]["location"]["station_id"]),
                         (STORE_DEFAULTS["store_ongi"].industry_code, STORE_DEFAULTS["store_ongi"].station_id))
        again = client.post("/api/market/setup").json()
        self.assertEqual(again["status"], "already")                          # 이미 맞춘 조건은 덮지 않음

    def test_switching_store_sets_up_that_store(self):
        client, fake = build()
        client.post("/api/auth/demo-login")
        client.post("/api/auth/store", json={"store_id": "store_basak"})
        data = client.post("/api/market/setup?force=1").json()
        self.assertEqual((data["conditions"]["area_code"], data["conditions"]["industry_code"], data["conditions"]["period"]),
                         ("3110836", "CS100007", "20262"))
        self.assertTrue(data["conditions"]["home"])
        client.post("/api/auth/store", json={"store_id": "store_mongle"})
        data = client.post("/api/market/setup?force=1").json()
        self.assertEqual((data["conditions"]["area_code"], data["conditions"]["industry_code"]), ("3120154", "CS100010"))


if __name__ == "__main__":
    unittest.main()
