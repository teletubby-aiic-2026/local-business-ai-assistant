"""상권 비서 프록시(web/assistant_proxy.py) 검증 — 가짜 상권 서비스(httpx.MockTransport)를 쓰고 네트워크·CLOVA 는 부르지 않는다.

확인하는 것
  · 상권 서비스가 요구하는 세트: 세션 쿠키 전달과 새 쿠키 심기, Host: 127.0.0.1:8766, Origin 은 넘기지 않음, 본문 검사
  · messages · actions · conversation(조회·지우기) · status · setup 모두 프록시
  · 상권 서비스가 꺼짐·챗봇 꺼짐·공식 자료 없음·제한 시간 초과·이상한 응답·우리 쪽 버그여도 500 이 없고, 서랍용 오류만 나옴.
    비서 화면의 다른 API 는 영향이 없음
  · 우리 가게 분석 조건 자동 맞추기(setup)

실행 (services/web 에서): PYTHONPATH=<저장소 루트> python -m pytest -q tests/test_assistant_proxy.py
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

from web import assistant_proxy as ap
from web.assistant_proxy import AssistantProxy, MarketClient
from web.demo import Demo
from web.main import create_app
from web.settings import REPO_ROOT, Settings

from tests.test_web import FakeSource, settings

NO_DATA = "상권 자료를 불러오지 못했습니다. 잠시 후 다시 확인해 주세요."
WANTED = ap.STORE_DEFAULTS["store_ongi"]


class FakeMarket:
    """상권 서비스(services/market-analysis)의 겉모습만 흉내 낸다. 모양은 실제 응답(공식 자료 없는 앱, 합성 자료 앱)을 따라 했다."""

    def __init__(self, *, enabled=True, data=True, candidates=None, periods=("20262", "20261"), mode="ok"):
        self.enabled, self.data, self.mode, self.periods = enabled, data, mode, list(periods)
        self.candidates = candidates if candidates is not None else [self.candidate(WANTED.area_code, "장승배기역 4번", "inside")]
        self.sessions: dict[str, dict] = {}
        self.requests: list[dict] = []

    @staticmethod
    def candidate(code, name, relation="inside", periods=("20262", "20261")):
        return {"area_code": code, "name": name, "relation": relation, "available_periods": list(periods)}

    # 응답 도우미
    def _session(self, request):
        match = re.search(r"market_onboarding_session=([A-Za-z0-9_-]{43})", request.headers.get("cookie", ""))
        token = match.group(1) if match else secrets.token_urlsafe(32)
        self.sessions.setdefault(token, {"revision": 0, "profile": None, "selection": None, "turns": []})
        return token, self.sessions[token]

    @staticmethod
    def _json(data, status=200, token=None):
        headers = {"set-cookie": f"market_onboarding_session={token}; HttpOnly; Max-Age=2592000; Path=/; SameSite=strict"} if token else {}
        return httpx.Response(status, json=data, headers=headers)

    def _state(self, session):
        sel = session["selection"]
        return {"revision": session["revision"], "profile": session["profile"], "analysis_selection": sel,
                "analysis_setup_complete": bool(sel), "conditions_confirmed": bool(sel and session["profile"]),
                "ready_for_analysis": False}

    def _conditions(self, session):
        sel, profile = session["selection"], session["profile"]
        if not (sel and profile):
            return None
        return {"area_code": sel["area_code"], "area_name": sel["area_name"], "industry_code": profile["industry"]["code"],
                "industry_name": profile["industry"]["name"], "period": sel["period"], "period_label": sel["period_label"],
                "location_label": profile["location"]["label"]}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.requests.append({"method": request.method, "path": path, "host": request.headers.get("host"),
                              "cookie": request.headers.get("cookie"), "origin": request.headers.get("origin"), "json": body})
        if self.mode == "down":
            raise httpx.ConnectError("connection refused")
        if self.mode == "timeout":
            raise httpx.ReadTimeout("read timed out")
        if self.mode == "boom":
            raise RuntimeError("프록시 안의 예상 못한 오류")
        if self.mode == "500":
            return httpx.Response(500, text="Internal Server Error")
        if self.mode == "html":
            return httpx.Response(200, text="<html>not json</html>")
        if request.headers.get("host") != "127.0.0.1:8766":      # TrustedHostMiddleware
            return httpx.Response(400, text="Invalid host header")
        if request.headers.get("origin"):                          # allowed_origin_only
            return httpx.Response(403, json={"detail": "허용되지 않은 요청 출처입니다."})
        method = request.method
        if path.startswith("/api/assistant") and not self.enabled:
            return httpx.Response(404, json={"detail": "Not Found"})
        if (method, path) == ("GET", "/api/assistant/status"):      # 실제 status 는 세션을 건드리지 않는다
            return self._json({"enabled": True, "model_connected": False, "planner_connected": False, "tools": []})
        token, session = self._session(request)
        if (method, path) == ("GET", "/api/onboarding/analysis-selection"):
            return self._json(self._state(session), token=token)
        if (method, path) == ("POST", "/api/onboarding/profile"):
            if body["expected_revision"] != session["revision"]:
                return self._json({"detail": "다른 화면에서 조건이 바뀌었습니다."}, 409, token)
            loc = body["location"]
            session["revision"] += 1
            session["selection"] = None
            session["profile"] = {"location": {**loc, "name": "장승배기역", "label": "장승배기역"},
                                  "industry": {"code": body["industry_code"], "name": "한식음식점"},
                                  "business_status": body["business_status"]}
            return self._json(self._state(session), token=token)
        if (method, path) == ("GET", "/api/onboarding/analysis-options"):
            if not self.data:
                return self._json({"detail": NO_DATA}, 503, token)
            return self._json({"catalog_version": "v-test", "status": "available", "candidates": self.candidates}, token=token)
        if (method, path) == ("POST", "/api/onboarding/analysis-selection"):
            if body["expected_revision"] != session["revision"] or body["expected_catalog_version"] != "v-test":
                return self._json({"detail": "다른 화면에서 조건이 바뀌었습니다."}, 409, token)
            area = next(c for c in self.candidates if c["area_code"] == body["area_code"])
            session["selection"] = {"area_code": area["area_code"], "area_name": area["name"], "period": body["period"],
                                    "period_label": f"{body['period'][:4]}년 {body['period'][4]}분기", "catalog_version": "v-test"}
            return self._json(self._state(session), token=token)
        if (method, path) == ("GET", "/api/assistant/conversation"):
            return self._json({"turns": session["turns"], "conditions": self._conditions(session)}, token=token)
        if (method, path) == ("DELETE", "/api/assistant/conversation"):
            removed = len(session["turns"])
            session["turns"] = []
            return self._json({"removed_turns": removed}, token=token)
        if (method, path) == ("POST", "/api/assistant/messages"):
            reply = {"kind": "data_answer", "text": f"답: {body['text']} [F1]", "actions": [], "notes": [], "suggestions": ["다음 질문"]}
            session["turns"].append({"seq": len(session["turns"]) + 1, "user_text": body["text"], "reply": reply, "cards": [], "action": None})
            return self._json({"reply": reply, "cards": [{"id": "F1", "topic": "sales_total", "status": "available", "text": "카드"}],
                               "conditions": self._conditions(session)}, token=token)
        if (method, path) == ("POST", "/api/assistant/actions"):
            return self._json({"reply": {"kind": "data_answer", "text": "선택 반영", "actions": [], "notes": [], "suggestions": []},
                               "cards": [], "echo": body}, token=token)
        return httpx.Response(404, json={"detail": "Not Found"})


def build(market: FakeMarket, store_id="store_ongi", *, base="http://ic26-market.internal:8766", timeout=5.0):
    tmp = Path(tempfile.mkdtemp())
    client = MarketClient(base, ap.DEFAULT_HOST, read_timeout=timeout, transport=httpx.MockTransport(market))
    proxy = AssistantProxy(client, store_id=store_id)
    demo = Demo(settings(tmp, store_id=store_id), source=FakeSource())
    app = create_app(demo, assistant=proxy)
    return TestClient(app), proxy


def error_of(response):
    return response.json()["error"]


class Base(unittest.TestCase):
    def make(self, **kw):
        self.market = FakeMarket(**kw)
        self.client, self.proxy = build(self.market)
        return self.client


class TestWhatTheMarketServiceRequires(Base):
    def test_host_is_pinned_and_origin_is_never_forwarded(self):
        self.make()
        res = self.client.post("/api/assistant/messages", json={"text": "매출 어때?"},
                               headers={"Origin": "https://ic26.example", "Host": "ic26.example"})
        self.assertEqual(res.status_code, 200, res.text)
        sent = self.market.requests[-1]
        self.assertEqual(sent["host"], "127.0.0.1:8766")
        self.assertIsNone(sent["origin"])

    def test_session_cookie_round_trip(self):
        self.make()
        first = self.client.post("/api/assistant/messages", json={"text": "첫 질문"})
        self.assertIsNone(self.market.requests[-1]["cookie"])         # 처음에는 쿠키가 없다
        set_cookie = first.headers["set-cookie"]
        self.assertIn("market_onboarding_session=", set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("Path=/api/assistant", set_cookie)
        token = re.search(r"market_onboarding_session=([^;]+)", set_cookie).group(1)
        self.assertRegex(token, r"^[A-Za-z0-9_-]{43}$")
        self.client.post("/api/assistant/messages", json={"text": "둘째 질문"})
        self.assertEqual(self.market.requests[-1]["cookie"], f"market_onboarding_session={token}")
        history = self.client.get("/api/assistant/conversation").json()
        self.assertEqual([t["user_text"] for t in history["turns"]], ["첫 질문", "둘째 질문"])   # 같은 세션이라 대화가 이어짐

    def test_only_the_market_cookie_is_forwarded(self):
        self.make()
        self.client.get("/api/briefing")                                  # 이 서버가 visitor_id 쿠키를 준다
        self.assertIn("visitor_id", self.client.cookies.keys())
        self.client.post("/api/assistant/messages", json={"text": "질문"})
        self.client.post("/api/assistant/messages", json={"text": "또 질문"})
        cookie = self.market.requests[-1]["cookie"]
        self.assertNotIn("visitor_id", cookie)
        self.assertEqual(cookie.count("="), 1)

    def test_visitors_never_share_a_market_session(self):
        """상권 서비스가 준 쿠키를 프록시 안에 쌓아 두면 다음 방문자가 앞사람의 대화와 조건을 물려받는다 (실제 서버로 확인하다 찾은 버그)."""
        self.make()
        a, b = self.client, TestClient(self.client.app)
        a.post("/api/assistant/setup")
        a.post("/api/assistant/messages", json={"text": "A 의 질문"})
        for visitor in (b, TestClient(self.client.app)):
            self.assertEqual(visitor.get("/api/assistant/conversation").json()["turns"], [])
            self.assertIsNone(visitor.get("/api/assistant/conversation").json()["conditions"])
            self.assertEqual(visitor.post("/api/assistant/setup").json()["status"], "ok")     # 새 세션이라 조건을 처음부터 맞춘다
        self.assertEqual(len(self.market.sessions), 3)
        self.assertEqual([t["user_text"] for t in a.get("/api/assistant/conversation").json()["turns"]], ["A 의 질문"])
        cookieless = [r for r in self.market.requests if r["cookie"] is None]
        self.assertGreaterEqual(len(cookieless), 3)       # 쿠키가 없는 방문자의 요청에는 상권 세션이 실리지 않았다

    def test_the_http_client_keeps_no_cookies(self):
        self.make()
        self.client.post("/api/assistant/messages", json={"text": "질문"})
        self.assertEqual(len(self.proxy.market.client.cookies.jar), 0)

    def test_a_malformed_session_value_is_not_forwarded(self):
        self.make()
        self.client.cookies.set("market_onboarding_session", "x; Path=/; evil=1", path="/api/assistant")
        self.client.post("/api/assistant/messages", json={"text": "질문"})
        self.assertIsNone(self.market.requests[-1]["cookie"])

    def test_cookie_is_secure_behind_https(self):
        self.make()
        res = self.client.post("/api/assistant/messages", json={"text": "질문"}, headers={"X-Forwarded-Proto": "https"})
        self.assertIn("Secure", res.headers["set-cookie"])

    def test_cookie_name_matches_the_market_service(self):
        text = (REPO_ROOT / "services" / "market-analysis" / "app" / "onboarding.py").read_text(encoding="utf-8")
        self.assertEqual(re.search(r'^COOKIE_NAME = "([^"]+)"', text, re.M).group(1), ap.COOKIE_NAME)
        self.assertEqual(int(eval(re.search(r"^SESSION_TTL = (.+)$", text, re.M).group(1))), ap.SESSION_SECONDS)

    def test_market_host_pin_default_matches_the_documented_one(self):
        self.assertEqual(ap.DEFAULT_HOST, "127.0.0.1:8766")


class TestEveryEndpointIsProxied(Base):
    def test_messages_returns_the_market_answer_untouched(self):
        self.make()
        res = self.client.post("/api/assistant/messages", json={"text": "  매출 어때?  ", "client_message_id": "web-1"})
        data = res.json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(data["reply"]["text"], "답: 매출 어때? [F1]")      # 앞뒤 공백은 상권 서비스와 같게 다듬음
        self.assertEqual(data["cards"][0]["id"], "F1")
        self.assertEqual(self.market.requests[-1]["json"], {"text": "매출 어때?", "client_message_id": "web-1"})
        self.assertEqual(res.headers["cache-control"], "no-store")

    def test_actions_forward_the_payload(self):
        self.make()
        payload = {"type": "location", "kind": "station", "station_id": "kric-e12f817979cd-S1107-0740",
                   "industry_code": "CS100001", "area_code": "3110826", "period": "20262"}
        res = self.client.post("/api/assistant/actions", json=payload)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["echo"], payload)

    def test_conversation_read_and_clear(self):
        self.make()
        self.client.post("/api/assistant/messages", json={"text": "질문"})
        self.assertEqual(len(self.client.get("/api/assistant/conversation").json()["turns"]), 1)
        self.assertEqual(self.client.delete("/api/assistant/conversation").json(), {"removed_turns": 1})
        self.assertEqual(self.client.get("/api/assistant/conversation").json()["turns"], [])

    def test_status_ready(self):
        self.make()
        data = self.client.get("/api/assistant/status").json()
        self.assertEqual(data["state"], "ready")
        self.assertIsNone(data["message"])
        self.assertEqual(data["setup"]["label"], "온기한식 · 장승배기역 · 한식음식점")

    def test_development_export_is_not_exposed(self):
        self.make()
        self.assertEqual(self.client.get("/api/assistant/conversation.md").status_code, 404)

    def test_the_old_standalone_paths_are_not_exposed(self):
        self.make()
        for path in ("/api/onboarding/analysis-selection", "/api/onboarding/profile"):
            self.assertEqual(self.client.get(path).status_code, 404)      # 브라우저가 상권 온보딩 API 를 직접 부를 길은 없다


class TestInputChecks(Base):
    def test_bad_messages_are_422_in_the_drawer_shape(self):
        self.make()
        for body in ({"text": ""}, {"text": "   "}, {"text": "가" * 1001}, {}, {"text": "질문", "extra": 1}, {"text": 5},
                     {"text": "질문", "client_message_id": "공백 있음"}):
            with self.subTest(body=str(body)[:30]):
                res = self.client.post("/api/assistant/messages", json=body)
                self.assertEqual(res.status_code, 422)
                self.assertEqual(error_of(res)["state"], "invalid")
                self.assertTrue(error_of(res)["message"])
        self.assertEqual(self.market.requests, [])      # 상권 서비스까지 가지 않는다
        self.assertIn("1000자", error_of(self.client.post("/api/assistant/messages", json={"text": "가" * 1001}))["message"])

    def test_bad_actions_are_422(self):
        self.make()
        for body in ({"type": "delete_everything"}, {}, {"type": "area", "area_code": "12"}, {"type": "area", "evil": "x"},
                     {"type": "industry", "industry_code": "DROP TABLE"}):
            with self.subTest(body=str(body)[:40]):
                res = self.client.post("/api/assistant/actions", json=body)
                self.assertEqual(res.status_code, 422)
                self.assertEqual(error_of(res)["state"], "invalid")
        self.assertEqual(self.market.requests, [])

    def test_other_routes_keep_the_default_422_shape(self):
        self.make()
        res = self.client.post("/api/reviews", json={"text": ""})
        self.assertEqual(res.status_code, 422)
        self.assertIn("detail", res.json())


class TestNothingDiesWhenTheMarketServiceIsUnwell(Base):
    def assert_drawer_only(self, state, *, status=503):
        for method, path, body in (("post", "/api/assistant/messages", {"text": "질문"}),
                                   ("post", "/api/assistant/actions", {"type": "area", "area_code": "3110826"}),
                                   ("get", "/api/assistant/conversation", None), ("delete", "/api/assistant/conversation", None)):
            with self.subTest(path=path, method=method):
                res = getattr(self.client, method)(path, json=body) if body is not None else getattr(self.client, method)(path)
                self.assertEqual(res.status_code, status, res.text)
                self.assertEqual(error_of(res)["state"], state)
                self.assertTrue(error_of(res)["message"])
        self.assertEqual(self.client.get("/api/assistant/status").status_code, 200)
        self.assertEqual(self.client.post("/api/assistant/setup").status_code, 200)
        # 비서 화면의 나머지는 아무 일 없다
        for path in ("/api/health", "/api/briefing", "/api/cards", "/api/insight", "/api/approvals", "/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_market_service_down(self):
        self.make(mode="down")
        self.assert_drawer_only("down")
        self.assertEqual(self.client.get("/api/assistant/status").json()["state"], "down")

    def test_chatbot_switched_off(self):
        self.make(enabled=False)
        self.assert_drawer_only("disabled")
        data = self.client.get("/api/assistant/status").json()
        self.assertEqual((data["state"], bool(data["message"])), ("disabled", True))

    def test_slow_answer(self):
        self.make(mode="timeout")
        self.assert_drawer_only("error")
        self.assertIn("오래", error_of(self.client.post("/api/assistant/messages", json={"text": "질문"}))["message"])

    def test_server_error_and_non_json_reply(self):
        for mode in ("500", "html"):
            with self.subTest(mode=mode):
                self.make(mode=mode)
                self.assert_drawer_only("error")

    def test_a_bug_on_our_side_is_not_a_500(self):
        self.make(mode="boom")
        self.assert_drawer_only("error")

    def test_host_or_origin_refusal_is_reported_as_a_config_problem(self):
        self.market = FakeMarket()
        client = MarketClient("http://ic26-market.internal:8766", "ic26.example", transport=httpx.MockTransport(self.market))
        tmp = Path(tempfile.mkdtemp())
        self.client = TestClient(create_app(Demo(settings(tmp), source=FakeSource()), assistant=AssistantProxy(client)))
        res = self.client.post("/api/assistant/messages", json={"text": "질문"})
        self.assertEqual((res.status_code, error_of(res)["state"]), (503, "error"))
        self.assertIn("접속 주소", error_of(res)["message"])

    def test_no_data_yet(self):
        self.make(data=False)
        data = self.client.post("/api/assistant/setup").json()
        self.assertEqual((data["status"], data["state"]), ("unavailable", "no_data"))
        self.assertIn("공식 상권 자료", data["message"])
        # 챗봇에 직접 물어도 상권 서비스의 안내(200)가 그대로 간다. 여기서 죽지 않는다
        self.assertEqual(self.client.post("/api/assistant/messages", json={"text": "매출 어때?"}).status_code, 200)

    def test_assistant_switched_off_on_this_server(self):
        client = TestClient(create_app(Demo(settings(Path(tempfile.mkdtemp())), source=FakeSource()),
                                       assistant=AssistantProxy.from_settings(Settings(market_url="off"))))
        status = client.get("/api/assistant/status").json()
        self.assertEqual(status["state"], "off")
        self.assertEqual(client.post("/api/assistant/messages", json={"text": "질문"}).status_code, 503)
        self.assertEqual(error_of(client.post("/api/assistant/messages", json={"text": "질문"}))["state"], "off")
        self.assertEqual(client.get("/api/health").status_code, 200)

    def test_bad_address_setting_is_an_error_not_a_crash(self):
        for url in ("ftp://x", "not a url", "http://user:pw@host", "http://host/path?x=1"):
            with self.subTest(url=url):
                proxy = AssistantProxy.from_settings(Settings(market_url=url))
                client = TestClient(create_app(Demo(settings(Path(tempfile.mkdtemp())), source=FakeSource()), assistant=proxy))
                self.assertEqual(client.get("/api/assistant/status").json()["state"], "error")
                self.assertEqual(client.get("/api/health").status_code, 200)

    def test_too_many_waiting_questions_get_a_polite_refusal(self):
        self.make()
        held = [self.proxy.slots.acquire() for _ in range(ap.MAX_CONCURRENT)]
        self.assertTrue(all(held))
        try:
            res = self.client.post("/api/assistant/messages", json={"text": "질문"})
            self.assertEqual((res.status_code, error_of(res)["state"]), (503, "error"))
            self.assertEqual(self.market.requests, [])
        finally:
            for _ in held:
                self.proxy.slots.release()
        self.assertEqual(self.client.post("/api/assistant/messages", json={"text": "질문"}).status_code, 200)

    def test_a_status_probe_never_creates_a_session(self):
        self.make()
        self.client.get("/api/assistant/status")
        self.assertEqual(self.market.sessions, {})


class TestSetup(Base):
    def conditions(self):
        return self.client.get("/api/assistant/conversation").json()["conditions"]

    def test_first_open_sets_our_stores_conditions(self):
        self.make()
        data = self.client.post("/api/assistant/setup").json()
        self.assertEqual((data["status"], data["state"]), ("ok", "ready"))
        self.assertEqual(data["conditions"]["area_name"], "장승배기역 4번")
        self.assertEqual(data["conditions"]["industry_name"], "한식음식점")
        self.assertEqual(data["conditions"]["period"], "20262")
        profile_call = next(r for r in self.market.requests if r["path"] == "/api/onboarding/profile")
        self.assertEqual(profile_call["json"], {"location": {"kind": "station", "station_id": WANTED.station_id},
                                                "industry_code": "CS100001", "business_status": "operating", "expected_revision": 0})
        self.assertEqual(self.conditions()["area_code"], WANTED.area_code)      # 이어지는 요청은 같은 세션이라 조건이 남아 있다

    def test_second_call_changes_nothing(self):
        self.make()
        self.client.post("/api/assistant/setup")
        calls = len(self.market.requests)
        data = self.client.post("/api/assistant/setup").json()
        self.assertEqual(data["status"], "already")
        self.assertEqual(data["conditions"]["area_name"], "장승배기역 4번")
        writes = [r for r in self.market.requests[calls:] if r["method"] == "POST"]
        self.assertEqual(writes, [])

    def test_the_users_own_conditions_are_not_overwritten(self):
        self.make()
        self.client.post("/api/assistant/setup")
        token = list(self.market.sessions)[0]
        session = self.market.sessions[token]
        session["profile"]["location"]["station_id"] = "another-station"
        session["selection"] = None
        data = self.client.post("/api/assistant/setup").json()
        self.assertEqual((data["status"], data["conditions"]), ("already", None))
        self.assertEqual(session["profile"]["location"]["station_id"], "another-station")

    def test_force_brings_back_our_conditions_after_the_user_looked_elsewhere(self):
        self.make()
        self.client.post("/api/assistant/setup")
        session = next(iter(self.market.sessions.values()))
        session["profile"]["location"]["station_id"] = "another-station"            # 사용자가 다른 곳을 보고 있다
        session["profile"]["industry"] = {"code": "CS100010", "name": "카페"}
        session["selection"] = {"area_code": "1111111", "area_name": "다른 상권", "period": "20261", "period_label": "2026년 1분기"}
        plain = self.client.post("/api/assistant/setup").json()
        self.assertEqual(plain["status"], "already")                                  # force 없이는 건드리지 않는다
        self.assertEqual(session["selection"]["area_code"], "1111111")
        forced = self.client.post("/api/assistant/setup?force=1").json()
        self.assertEqual((forced["status"], forced["state"]), ("ok", "ready"))
        self.assertEqual((forced["conditions"]["area_name"], forced["conditions"]["industry_name"]), ("장승배기역 4번", "한식음식점"))
        self.assertEqual(session["profile"]["location"]["station_id"], WANTED.station_id)
        self.assertEqual(session["profile"]["industry"]["code"], WANTED.industry_code)

    def test_force_on_a_store_without_defaults_changes_nothing(self):
        market = FakeMarket()
        client, _ = build(market, store_id="store_unknown")
        data = client.post("/api/assistant/setup?force=1").json()
        self.assertEqual((data["status"], data["conditions"]), ("already", None))
        self.assertFalse([r for r in market.requests if r["method"] == "POST"])

    def test_falls_back_to_the_latest_quarter(self):
        self.make(periods=("20261",), candidates=[FakeMarket.candidate(WANTED.area_code, "장승배기역 4번", periods=("20261", "20253"))])
        data = self.client.post("/api/assistant/setup").json()
        self.assertEqual(data["conditions"]["period"], "20261")

    def test_a_single_unnamed_candidate_is_used_but_a_crowd_is_not(self):
        self.make(candidates=[FakeMarket.candidate("1234567", "다른 이름 상권", "nearby")])
        self.assertEqual(self.client.post("/api/assistant/setup").json()["conditions"]["area_code"], "1234567")
        self.make(candidates=[FakeMarket.candidate("1234567", "가 상권", "nearby"), FakeMarket.candidate("7654321", "나 상권", "nearby")])
        data = self.client.post("/api/assistant/setup").json()
        self.assertEqual((data["status"], data["state"]), ("unavailable", "error"))
        self.assertIn("상권을 하나로 정하지 못했어요", data["message"])

    def test_no_candidates_means_no_data(self):
        self.make(candidates=[])
        self.assertEqual(self.client.post("/api/assistant/setup").json()["state"], "no_data")

    def test_a_store_without_defaults_is_left_alone(self):
        # 11/18 부터 store_basak·store_mongle 은 기본 조건이 있다 (아래 시험). 기본 조건이 없는 가게는 등록하지 않은 id 로 본다
        market = FakeMarket()
        client, _ = build(market, store_id="store_unknown")
        self.assertIsNone(client.get("/api/assistant/status").json()["setup"]["label"])
        data = client.post("/api/assistant/setup").json()
        self.assertEqual((data["status"], data["state"], data["conditions"]), ("already", "ready", None))
        self.assertFalse([r for r in market.requests if r["method"] == "POST"])

    def test_setup_recovers_after_the_data_arrives(self):
        self.make(data=False)
        self.assertEqual(self.client.post("/api/assistant/setup").json()["state"], "no_data")
        self.market.data = True
        data = self.client.post("/api/assistant/setup").json()
        self.assertEqual((data["status"], data["conditions"]["area_name"]), ("ok", "장승배기역 4번"))
        self.assertEqual(len([r for r in self.market.requests if r["path"] == "/api/onboarding/profile"]), 1)   # 프로필은 다시 쓰지 않음

    def test_setup_does_not_touch_anything_when_the_chatbot_is_off_or_the_service_is_down(self):
        for kwargs, state in (({"enabled": False}, "disabled"), ({"mode": "down"}, "down")):
            with self.subTest(state=state):
                self.make(**kwargs)
                data = self.client.post("/api/assistant/setup").json()
                self.assertEqual((data["status"], data["state"]), ("unavailable", state))
                self.assertFalse([r for r in self.market.requests if r["path"].startswith("/api/onboarding")])
                self.assertFalse([r for r in self.market.requests if r["method"] == "POST"])

    def test_a_new_session_issued_midway_is_kept(self):
        self.make()
        res = self.client.post("/api/assistant/setup")
        self.assertIn("market_onboarding_session=", res.headers["set-cookie"])


class TestDefaults(unittest.TestCase):
    def test_default_codes_match_the_market_data(self):
        app = REPO_ROOT / "services/market-analysis/app"
        stations = json.loads((app / "onboarding_stations.json").read_text(encoding="utf-8"))["stations"]
        station = next(s for s in stations if s["id"] == WANTED.station_id)
        self.assertEqual(station["name"], "장승배기역")
        industries = json.loads((app / "onboarding_industries.json").read_text(encoding="utf-8"))["industries"]
        self.assertEqual(next(i["name"] for i in industries if i["code"] == WANTED.industry_code), "한식음식점")
        snapshot = (REPO_ROOT / "data/scenario/snapshot_2026Q2.json").read_text(encoding="utf-8")
        self.assertIn(WANTED.area_code, snapshot)

    def test_settings_from_env(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"MARKET_URL": "http://10.0.0.5:8766/", "MARKET_TIMEOUT_SEC": "abc"}, clear=False):
            s = Settings.from_env()
        self.assertEqual((s.market_url, s.market_timeout, s.market_host), ("http://10.0.0.5:8766/", 75.0, "127.0.0.1:8766"))


if __name__ == "__main__":
    unittest.main()
