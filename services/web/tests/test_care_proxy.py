"""고객응대 프록시(web/care_proxy.py)와 답글 승인 기록, 캡처 후보 저장 길 검증.
가짜 리뷰 분석 서비스(httpx.MockTransport)를 쓰고 네트워크·HCX 는 부르지 않는다.

확인하는 것
  · 허용 목록: 캡처·상태 기록·응대 점수·보고서(일일·월간·인쇄)만 넘기고 가게 정보·문의·받은함·약속 장부·다국어 메뉴판 등은 404
  · store_id 는 우리 가게, visitor_id 는 방문자 쿠키로 덮어씀 (쿼리·JSON·캡처 업로드). 쿼리는 date·month·now 만
  · 손님용 /s/{가게}·/api/care/public/* 는 기본으로 없음. CARE_PUBLIC 일 때만, 손님 주소는 X-Real-IP 로
  · /api/care/status 는 늘 200. 서비스가 꺼짐·느림·꺼 둠·오류여도 비서 화면(/, health, briefing, cards)은 200, 500 은 없음
  · 본문 상한 413 (JSON 64KB, 업로드 12MB), 서비스 오류는 메시지 그대로 + state
  · 느린 서비스가 다른 경로를 붙잡지 않음 (이벤트 루프를 막지 않음)
  · 답글 승인 → 서비스에 replied 기록 (따로 보내고 승인 응답은 기다리지 않음, 실패해도 승인은 그대로)
  · 캡처 후보 저장은 POST /api/reviews 에 source=capture (붙여넣기와 같은 길)

실행 (services/web 에서): PYTHONPATH=<저장소 루트>:. python -m pytest -q tests/test_care_proxy.py
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from web import care_proxy as cp
from web.assistant_proxy import AssistantProxy
from web.care_proxy import CareProxy
from web.demo import Demo
from web.main import create_app
from web.settings import Settings
from web.sources import ReviewSource

from tests.test_web import FakeSource, settings

P = "/api/review-insight"
PRINT_HTML = "<!doctype html><html><head><title>보고서</title></head><body><h1>온기한식 · 11월 응대 보고서</h1></body></html>"
INQUIRY_HTML = '<!doctype html><html><head><meta name="care-api" content="/api/review-insight/public"></head><body>문의</body></html>'


class FakeCare:
    """리뷰 분석 서비스의 고객응대 API 겉모습 (모양은 services/review-insight/docs/handoff.md 2절 예시)."""

    def __init__(self, mode="ok", delay=0.0, token_required=False):
        self.mode, self.delay, self.token_required = mode, delay, token_required
        self.requests: list[dict] = []
        self.started = threading.Event()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        rec = {"method": request.method, "path": path, "params": dict(request.url.params), "headers": dict(request.headers),
               "content": request.content, "timeout": request.extensions.get("timeout")}
        try:
            rec["json"] = json.loads(request.content) if request.content and "json" in request.headers.get("content-type", "") else None
        except ValueError:
            rec["json"] = None
        self.requests.append(rec)
        self.started.set()
        if self.delay:
            time.sleep(self.delay)
        mode = self.mode
        if mode == "down":
            raise httpx.ConnectError("connection refused")
        if mode == "timeout":
            raise httpx.ReadTimeout("read timed out")
        if mode == "boom":
            raise RuntimeError("프록시 안의 예상 못한 오류")
        if mode == "500":
            return httpx.Response(500, text="Internal Server Error")
        if mode == "401":
            return httpx.Response(401, json={"error": {"code": "UNAUTHORIZED", "message": "접근 토큰이 없거나 틀렸습니다.", "retryable": False}})
        if mode == "html":
            return httpx.Response(200, text="<html>not json</html>", headers={"content-type": "text/html"})
        if path == "/api/health":
            return httpx.Response(200, json={"status": "ok", "mode": "mock", "token_required": self.token_required})
        if (request.method, path) == ("POST", P + "/reviews/capture"):
            if mode == "unreadable":
                return httpx.Response(422, json={"error": {"code": "CAPTURE_UNREADABLE", "message": "캡처에서 리뷰를 찾지 못했습니다. 리뷰가 잘 보이게 다시 올리거나, 붙여넣기를 써 주세요",
                                                           "retryable": False, "details": {}, "request_id": "req_1"}})
            if mode == "llm":
                return httpx.Response(502, json={"error": {"code": "LLM_TIMEOUT", "message": "캡처를 읽는 AI 호출에 실패했습니다. 잠시 뒤 다시 올리거나 붙여넣기를 써 주세요",
                                                           "retryable": True}})
            return httpx.Response(200, json={"candidates": [{"text": "공깃밥이 또 빠져 있었어요", "rating": 2, "pii_masked": False, "duplicate": False}],
                                             "count": 1, "demo": True, "pieces": 1, "warnings": ["예시 결과입니다"], "engine": "demo"})
        if request.method == "POST" and path.startswith(P + "/reviews/") and path.endswith("/status"):
            review_id = path.split("/")[-2]
            if review_id == "rv_missing":
                return httpx.Response(404, json={"error": {"code": "REVIEW_NOT_FOUND", "message": f"없는 리뷰입니다: {review_id}"}})
            return httpx.Response(200, json={"review": {"review_id": review_id, "status": "replied"}})
        if (request.method, path) == ("GET", P + "/response"):
            return httpx.Response(200, json={"store_id": "store_ongi", "score": 91, "reasons": [], "pending": [], "pending_count": 0,
                                             "overdue_count": 0, "untimed_unanswered": 12, "peak_now": False})
        if (request.method, path) == ("GET", P + "/report/daily"):
            return httpx.Response(200, json={"date": "2026-11-15", "summary": "11월 15일: 리뷰 0건", "review_count": 0})
        if (request.method, path) == ("GET", P + "/report/monthly"):
            return httpx.Response(200, json={"month": request.url.params.get("month") or "2026-11", "score_trend": [], "repeated_issues": []})
        if (request.method, path) == ("GET", P + "/report/monthly/print"):
            return httpx.Response(200, text=PRINT_HTML, headers={"content-type": "text/html; charset=utf-8", "cache-control": "no-store"})
        if path.startswith(P + "/public/"):
            return httpx.Response(201 if request.method == "POST" else 200, json={"ok": True})
        if path == "/s/store_ongi":
            return httpx.Response(200, text=INQUIRY_HTML, headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404, json={"detail": "Not Found"})

    def calls(self, path_prefix=P):
        return [r for r in self.requests if r["path"].startswith(path_prefix)]


def build(fake: FakeCare | None = None, *, public=False, token="", timeout=5.0, source=None, care: CareProxy | None = None):
    tmp = Path(tempfile.mkdtemp())
    fake = fake or FakeCare()
    proxy = care or CareProxy("http://care.internal:8020", token=token, public=public, timeout=timeout,
                              transport=httpx.MockTransport(fake))
    demo = Demo(settings(tmp), source=source or FakeSource())
    app = create_app(demo, assistant=AssistantProxy(None), care=proxy)
    return TestClient(app), proxy, demo


def visitor(client: TestClient) -> str:
    client.get("/api/health")
    return client.cookies["visitor_id"]


def png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"0" * 200


class AllowList(unittest.TestCase):
    def setUp(self):
        self.fake = FakeCare()
        self.client, self.proxy, _ = build(self.fake)

    def test_the_routes_this_screen_uses_are_forwarded(self):
        c = self.client
        self.assertEqual(c.get("/api/care/response").json()["score"], 91)
        self.assertEqual(c.get("/api/care/report/daily?date=2026-11-15").status_code, 200)
        self.assertEqual(c.get("/api/care/report/monthly?month=2026-10").json()["month"], "2026-10")
        self.assertEqual(c.post("/api/care/reviews/rv_ongi_001/status", json={"status": "replied", "reply_text": "감사합니다"}).status_code, 200)
        res = c.post("/api/care/reviews/capture", files={"file": ("cap.png", png(), "image/png")})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["demo"])
        paths = [r["path"] for r in self.fake.calls()]
        self.assertEqual(paths, [P + "/response", P + "/report/daily", P + "/report/monthly", P + "/reviews/rv_ongi_001/status",
                                 P + "/reviews/capture"])

    def test_everything_else_is_404_and_never_reaches_the_service(self):
        c = self.client
        refused = [("GET", "/api/care/profile"), ("PUT", "/api/care/profile"), ("DELETE", "/api/care/profile"),
                   ("POST", "/api/care/profile/notices"), ("DELETE", "/api/care/profile/notices/n_1"),
                   ("POST", "/api/care/profile/answers"), ("POST", "/api/care/profile/menu/capture"),
                   ("GET", "/api/care/inbox"), ("POST", "/api/care/inquiries/q_1/status"), ("POST", "/api/care/inquiries/q_1/draft"),
                   ("GET", "/api/care/promises"), ("GET", "/api/care/menu/foreign"), ("GET", "/api/care/menu/foreign/print"),
                   ("GET", "/api/care/reviews"), ("POST", "/api/care/reviews"), ("DELETE", "/api/care/reviews/pasted"),
                   ("GET", "/api/care/reviews/rv_ongi_001"), ("GET", "/api/care/insight"), ("GET", "/api/care/store"),
                   ("GET", "/api/care/reviews/capture"), ("POST", "/api/care/response"), ("DELETE", "/api/care/report/daily"),
                   ("GET", "/api/care/report/%2e%2e/profile"), ("GET", "/api/care/public/store_ongi/info"),
                   ("POST", "/api/care/public/store_ongi/inquiries"), ("GET", "/api/care/s/store_ongi")]
        for method, path in refused:
            with self.subTest(method=method, path=path):
                res = c.request(method, path, json={} if method in ("POST", "PUT") else None)
                self.assertEqual(res.status_code, 404, res.text)
                self.assertEqual(res.json()["error"]["state"], "not_found")
        self.assertEqual(self.fake.calls(), [])

    def test_customer_pages_are_not_mounted_by_default(self):
        self.assertEqual(self.client.get("/s/store_ongi").status_code, 404)
        self.assertEqual(self.fake.requests, [])
        self.assertFalse(any(getattr(r, "path", "") == "/s/{store_id}" for r in self.client.app.routes))

    def test_store_and_visitor_are_overwritten_and_only_known_query_keys_pass(self):
        me = visitor(self.client)
        self.client.get("/api/care/report/monthly?month=2026-10&store_id=store_basak&visitor_id=someone_else&foo=bar&now=2026-10-31T23:00:00%2B09:00")
        params = self.fake.calls()[-1]["params"]
        self.assertEqual(params, {"month": "2026-10", "now": "2026-10-31T23:00:00+09:00", "store_id": "store_ongi", "visitor_id": me})

    def test_json_body_store_and_visitor_are_overwritten(self):
        me = visitor(self.client)
        self.client.post("/api/care/reviews/rv_ongi_001/status",
                         json={"status": "replied", "reply_text": "감사합니다", "store_id": "store_basak", "visitor_id": "other"})
        sent = self.fake.calls()[-1]
        self.assertEqual(sent["json"], {"status": "replied", "reply_text": "감사합니다", "store_id": "store_ongi", "visitor_id": me})
        self.assertEqual(sent["params"], {"store_id": "store_ongi", "visitor_id": me})

    def test_capture_upload_is_passed_through_and_scoped_by_the_query(self):
        me = visitor(self.client)
        self.client.post("/api/care/reviews/capture", files={"file": ("cap.png", png(), "image/png")},
                         data={"store_id": "store_basak", "visitor_id": "other"})
        sent = self.fake.calls()[-1]
        self.assertTrue(sent["headers"]["content-type"].startswith("multipart/form-data; boundary="))
        self.assertIn(png(), sent["content"])                                  # 본문은 그대로
        self.assertEqual(sent["params"], {"store_id": "store_ongi", "visitor_id": me})   # 서비스는 쿼리 값을 폼보다 먼저 씀
        self.assertGreaterEqual(sent["timeout"]["read"], 5.0)                  # 캡처는 긴 제한 시간 (여기서는 build 의 5초)

    def test_token_is_added_by_the_server_and_never_taken_from_the_browser(self):
        self.client.get("/api/care/response", headers={"X-Access-Token": "browser-guess"})
        self.assertNotIn("x-access-token", self.fake.calls()[-1]["headers"])
        fake = FakeCare()
        client, _, _ = build(fake, token="team-token")
        client.get("/api/care/response", headers={"X-Access-Token": "browser-guess"})
        self.assertEqual(fake.calls()[-1]["headers"]["x-access-token"], "team-token")

    def test_print_page_is_html_with_a_strict_policy(self):
        res = self.client.get("/api/care/report/monthly/print?month=2026-11")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.headers["content-type"].startswith("text/html"))
        self.assertIn("11월 응대 보고서", res.text)
        self.assertIn("default-src 'none'", res.headers["content-security-policy"])
        self.assertEqual(res.headers["x-content-type-options"], "nosniff")
        self.assertEqual(self.fake.calls()[-1]["params"]["month"], "2026-11")


class CustomerPagesBehindTheFlag(unittest.TestCase):
    def setUp(self):
        self.fake = FakeCare()
        self.client, _, _ = build(self.fake, public=True, token="team-token")

    def test_public_api_is_forwarded_without_token_or_visitor(self):
        res = self.client.get("/api/care/public/store_ongi/info?store_id=x&visitor_id=y")
        self.assertEqual(res.status_code, 200, res.text)
        sent = self.fake.calls()[-1]
        self.assertEqual(sent["path"], P + "/public/store_ongi/info")
        self.assertNotIn("x-access-token", sent["headers"])
        self.assertEqual(sent["params"], {})

    def test_client_address_comes_from_x_real_ip_not_the_spoofable_forwarded_for(self):
        self.client.post("/api/care/public/store_ongi/inquiries", json={"text": "주차 되나요?"},
                         headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.9", "X-Real-IP": "203.0.113.7"})
        self.assertEqual(self.fake.calls()[-1]["headers"]["x-forwarded-for"], "203.0.113.7")
        self.client.post("/api/care/public/store_ongi/inquiries", json={"text": "주차 되나요?"},
                         headers={"X-Forwarded-For": "1.2.3.4"})
        self.assertEqual(self.fake.calls()[-1]["headers"]["x-forwarded-for"], "testclient")   # 접속한 쪽 주소

    def test_only_our_store_and_the_inquiry_page_is_rewritten(self):
        self.assertEqual(self.client.get("/api/care/public/store_basak/info").status_code, 404)
        self.assertEqual(self.client.get("/s/store_basak").status_code, 404)
        page = self.client.get("/s/store_ongi")
        self.assertEqual(page.status_code, 200)
        self.assertIn('content="/api/care/public"', page.text)
        self.assertNotIn("/api/review-insight", page.text)

    def test_settings_flag(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"CARE_PUBLIC": "1"}):
            self.assertTrue(Settings.from_env().care_public)
        with mock.patch.dict(os.environ, {"CARE_PUBLIC": ""}):
            self.assertFalse(Settings.from_env().care_public)


class NothingDiesWhenTheServiceIsUnwell(unittest.TestCase):
    def assert_rest_of_the_screen_is_fine(self, client):
        for path in ("/", "/api/health", "/api/briefing", "/api/cards"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 200)
        self.assertEqual(client.get("/api/care/status").status_code, 200)

    def test_down_slow_off_and_bad_settings(self):
        cases = [("down", FakeCare("down"), None), ("slow", FakeCare("timeout"), None),
                 ("off", None, CareProxy(None)),
                 ("error", None, CareProxy(None, config_error="리뷰 분석 서비스 주소 설정이 올바르지 않아요."))]
        for state, fake, care in cases:
            with self.subTest(state=state):
                client, _, _ = build(fake, care=care)
                for path in ("/api/care/response", "/api/care/report/daily", "/api/care/report/monthly"):
                    res = client.get(path)
                    self.assertEqual(res.status_code, 503, res.text)
                    self.assertEqual(res.json()["error"]["state"], state)
                    self.assertTrue(res.json()["error"]["message"])
                res = client.post("/api/care/reviews/capture", files={"file": ("cap.png", png(), "image/png")})
                self.assertEqual((res.status_code, res.json()["error"]["state"]), (503, state))
                self.assert_rest_of_the_screen_is_fine(client)

    def test_no_500_from_upstream_errors_odd_replies_or_our_own_bugs(self):
        for mode in ("500", "html", "boom", "401"):
            with self.subTest(mode=mode):
                client, _, _ = build(FakeCare(mode))
                res = client.get("/api/care/response")
                self.assertEqual(res.status_code, 503, res.text)
                self.assertEqual(res.json()["error"]["state"], "error")
                self.assert_rest_of_the_screen_is_fine(client)
        client, _, _ = build(FakeCare("401"))
        self.assertIn("REVIEW_INSIGHT_TOKEN", client.get("/api/care/response").json()["error"]["message"])

    def test_service_errors_keep_their_message_and_gain_a_state(self):
        client, _, _ = build(FakeCare("unreadable"))
        res = client.post("/api/care/reviews/capture", files={"file": ("cap.png", png(), "image/png")})
        self.assertEqual(res.status_code, 422)
        err = res.json()["error"]
        self.assertEqual((err["code"], err["state"]), ("CAPTURE_UNREADABLE", "invalid"))
        self.assertIn("붙여넣기를 써 주세요", err["message"])
        client, _, _ = build(FakeCare("llm"))
        res = client.post("/api/care/reviews/capture", files={"file": ("cap.png", png(), "image/png")})
        self.assertEqual((res.status_code, res.json()["error"]["state"]), (502, "upstream"))
        client, _, _ = build(FakeCare())
        res = client.post("/api/care/reviews/rv_missing/status", json={"status": "replied", "reply_text": "네"})
        self.assertEqual((res.status_code, res.json()["error"]["state"]), (404, "not_found"))

    def test_status_is_always_200(self):
        expected = {"ready": FakeCare(), "down": FakeCare("down"), "error": FakeCare("500")}
        for state, fake in expected.items():
            with self.subTest(state=state):
                client, _, _ = build(fake)
                res = client.get("/api/care/status")
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["state"], state)
        client, _, _ = build(care=CareProxy(None))
        self.assertEqual(client.get("/api/care/status").json()["state"], "off")
        client, _, _ = build(FakeCare(token_required=True))                     # 서비스는 토큰을 요구하는데 이 서버에 값이 없음
        self.assertEqual(client.get("/api/care/status").json()["state"], "error")
        ready = build(FakeCare())[0].get("/api/care/status").json()
        self.assertEqual((ready["mode"], ready["store_id"], ready["public"]), ("mock", "store_ongi", False))

    def test_bodies_over_the_cap_are_413_and_not_sent(self):
        fake = FakeCare()
        client, _, _ = build(fake)
        res = client.post("/api/care/reviews/rv_ongi_001/status", json={"status": "replied", "reply_text": "가" * (cp.MAX_JSON)})
        self.assertEqual((res.status_code, res.json()["error"]["state"]), (413, "too_big"))
        res = client.post("/api/care/reviews/capture", files={"file": ("big.png", b"0" * (cp.MAX_UPLOAD + 1), "image/png")})
        self.assertEqual((res.status_code, res.json()["error"]["state"]), (413, "too_big"))
        self.assertIn("10MB", res.json()["error"]["message"])
        self.assertEqual(fake.calls(), [])

    def test_bad_bodies_are_422(self):
        client, _, _ = build()
        res = client.post("/api/care/reviews/rv_ongi_001/status", content=b"not json", headers={"Content-Type": "application/json"})
        self.assertEqual((res.status_code, res.json()["error"]["state"]), (422, "invalid"))
        res = client.post("/api/care/reviews/capture", json={"file": "x"})          # 여러 부분 폼이 아님
        self.assertEqual((res.status_code, res.json()["error"]["state"]), (422, "invalid"))


class DoesNotBlockTheServer(unittest.TestCase):
    def test_a_slow_service_does_not_hold_up_other_routes(self):
        """예전 참고 구현은 async 경로 안에서 동기 httpx 를 불러, 서비스가 5초 걸리면 다른 경로도 4.5초 기다렸다 (리뷰어가 잼)."""
        fake = FakeCare(delay=1.5)
        client, _, _ = build(fake)
        done = {}
        with TestClient(client.app) as c:        # 이벤트 루프 하나를 같이 쓴다 (실제 서버와 같음)
            worker = threading.Thread(target=lambda: done.setdefault("r", c.post(
                "/api/care/reviews/capture", files={"file": ("cap.png", png(), "image/png")})))
            worker.start()
            self.assertTrue(fake.started.wait(5))
            t0 = time.perf_counter()
            health = c.get("/api/health")
            briefing = c.get("/api/briefing")
            waited = time.perf_counter() - t0
            worker.join(10)
        self.assertEqual((health.status_code, briefing.status_code), (200, 200))
        self.assertLess(waited, 0.8, f"느린 캡처 동안 다른 경로가 {waited:.2f}초 기다림")
        self.assertEqual(done["r"].status_code, 200)


class ApproveRecordsTheReply(unittest.TestCase):
    KEYS = {"draft_id", "status", "edited", "text", "approved_at", "mode"}

    def make(self, fake=None, **kw):
        self.fake = fake or FakeCare()
        self.client, self.proxy, self.demo = build(self.fake, **kw)
        self.demo._remember_drafts("card_ongi_a", {"drafts": [
            {"draft_id": "d_reply", "generator": "reply_draft", "target_review_id": "rv_ongi_001"},
            {"draft_id": "d_notice", "generator": "prevention_notice"}]})
        return self.client

    def approve(self, draft_id, text="불편을 드려 죄송합니다. 포장할 때 한 번 더 확인하겠습니다.", **more):
        res = self.client.post(f"/api/drafts/{draft_id}/approve", json={"text": text, "original": text, **more})
        self.proxy.flush()
        return res

    def status_calls(self):
        return [r for r in self.fake.calls() if r["path"].endswith("/status")]

    def test_reply_approval_is_recorded_as_replied(self):
        self.make(token="team-token")
        me = visitor(self.client)
        res = self.approve("d_reply")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(set(res.json()), self.KEYS)                     # 승인 응답 모양은 그대로
        (call,) = self.status_calls()
        self.assertEqual(call["path"], P + "/reviews/rv_ongi_001/status")
        self.assertEqual(call["json"], {"store_id": "store_ongi", "status": "replied", "visitor_id": me,
                                        "reply_text": "불편을 드려 죄송합니다. 포장할 때 한 번 더 확인하겠습니다.",
                                        "at": res.json()["approved_at"]})
        self.assertEqual(call["headers"]["x-access-token"], "team-token")
        self.assertLessEqual(call["timeout"]["read"], cp.REPLY_TIMEOUT)    # 짧게 기다림

    def test_other_drafts_are_not_recorded(self):
        self.make()
        self.assertEqual(self.approve("d_notice").status_code, 200)
        self.assertEqual(self.status_calls(), [])

    def test_a_draft_from_another_server_uses_the_screen_hint_only_for_replies(self):
        self.make()
        self.approve("d_elsewhere", kind="reply_draft", review_id="rv_ongi_paste_002")
        self.assertEqual([c["path"] for c in self.status_calls()], [P + "/reviews/rv_ongi_paste_002/status"])
        self.approve("d_elsewhere2", kind="coupon_promo", review_id="rv_ongi_003")
        self.approve("d_elsewhere3", review_id="rv_ongi_003")
        res = self.approve("d_elsewhere4", kind="reply_draft", review_id="../../profile")
        self.assertEqual(res.status_code, 200)                           # 이상한 값이어도 승인은 성공, 기록만 안 함
        self.assertEqual(len(self.status_calls()), 1)
        self.approve("d_reply", kind="coupon_promo", review_id="rv_ongi_009")   # 이 서버가 아는 초안이면 서버 기억이 먼저
        self.assertEqual(self.status_calls()[-1]["path"], P + "/reviews/rv_ongi_001/status")

    def test_approval_never_fails_when_the_service_is_down_off_or_broken(self):
        for fake, care in ((FakeCare("down"), None), (FakeCare("500"), None), (FakeCare("boom"), None), (None, CareProxy(None))):
            with self.subTest(mode=getattr(fake, "mode", "off")):
                self.make(fake, care=care)
                res = self.approve("d_reply")
                self.assertEqual(res.status_code, 200)
                self.assertEqual(set(res.json()), self.KEYS)
                self.assertEqual(res.json()["status"], "approved")

    def test_approval_does_not_wait_for_a_slow_service(self):
        self.make(FakeCare(delay=1.5))
        t0 = time.perf_counter()
        res = self.client.post("/api/drafts/d_reply/approve", json={"text": "감사합니다", "original": "감사합니다"})
        waited = time.perf_counter() - t0
        self.assertEqual(res.status_code, 200)
        self.assertLess(waited, 0.8, f"승인이 {waited:.2f}초 걸림")
        self.proxy.flush()
        self.assertEqual(len(self.status_calls()), 1)                     # 뒤에서 보내기는 했다


class CaptureCandidatesAreSavedLikePastedReviews(unittest.TestCase):
    def setUp(self):
        self.seen: list[dict] = []

        def handler(request: httpx.Request):
            body = json.loads(request.content) if request.content else None
            self.seen.append({"method": request.method, "path": request.url.path, "json": body})
            if (request.method, request.url.path) == ("POST", P + "/reviews"):
                review = {"review_id": "rv_ongi_paste_001", "text": body["text"], "rating": body.get("rating"), "input_method": "paste",
                          "source": body.get("source", "paste"), "pii_masked": False}
                return httpx.Response(201, json={"review": review, "classification": None, "joined_issues": []})
            return httpx.Response(404, json={"detail": "Not Found"})

        src = ReviewSource("http://review.internal", client=httpx.Client(base_url="http://review.internal",
                                                                         transport=httpx.MockTransport(handler)))
        self.client, _, _ = build(source=src, care=CareProxy(None))

    def test_source_capture_reaches_the_review_service_with_this_visitor(self):
        me = visitor(self.client)
        res = self.client.post("/api/reviews", json={"text": "공깃밥이 또 빠져 있었어요", "rating": 2, "source": "capture"})
        self.assertEqual(res.status_code, 201, res.text)
        sent = self.seen[-1]["json"]
        self.assertEqual(sent, {"store_id": "store_ongi", "text": "공깃밥이 또 빠져 있었어요", "visitor_id": me, "rating": 2, "source": "capture"})
        self.assertEqual(res.json()["review"]["input_method"], "paste")     # 계약 값은 그대로

    def test_plain_paste_is_unchanged(self):
        self.client.post("/api/reviews", json={"text": "맛있어요", "rating": 5})
        self.assertNotIn("source", self.seen[-1]["json"])
        self.client.post("/api/reviews", json={"text": "맛있어요", "source": "paste"})
        self.assertNotIn("source", self.seen[-1]["json"])

    def test_other_sources_are_refused(self):
        for source in ("app", "memo", "sample", ""):
            with self.subTest(source=source):
                self.assertEqual(self.client.post("/api/reviews", json={"text": "글", "source": source}).status_code, 422)


class SettingsAndAddress(unittest.TestCase):
    def test_from_env(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"CARE_URL": "off", "CARE_TIMEOUT_SEC": "90"}):
            s = Settings.from_env()
        self.assertEqual((s.care_url, s.care_timeout, s.care_public), ("off", 90.0, False))
        with mock.patch.dict(os.environ, {"CARE_TIMEOUT_SEC": "nope"}):
            self.assertEqual(Settings.from_env().care_timeout, 100.0)

    def test_from_settings(self):
        tmp = Path(tempfile.mkdtemp())
        self.assertIsNone(CareProxy.from_settings(settings(tmp, care_url="off")).client)
        same = CareProxy.from_settings(settings(tmp, review_url="http://127.0.0.1:8020"))
        self.assertEqual(str(same.client.base_url), "http://127.0.0.1:8020")
        bad = CareProxy.from_settings(settings(tmp, care_url="ftp://x/y"))
        self.assertIsNone(bad.client)
        self.assertEqual(bad.status()["state"], "error")
        own = CareProxy.from_settings(settings(tmp, care_url="http://10.0.0.5:8020/", care_timeout=60.0, care_public=True,
                                               review_token="t"))
        self.assertEqual((str(own.client.base_url), own.timeout, own.public, own.token), ("http://10.0.0.5:8020", 60.0, True, "t"))


if __name__ == "__main__":
    unittest.main()


class SavingAReviewWaitsForTheLiveClassifier(unittest.TestCase):
    """리뷰 저장은 리뷰 분석이 그 자리에서 HCX 로 분류해 10초를 넘을 수 있다 (11/15 실시간 23.8초 → 저장은 됐는데 화면은 503).
    저장 요청만 길게 기다리고, 다른 조회는 10초 그대로."""

    def setUp(self):
        self.seen = []

        def handler(request: httpx.Request):
            self.seen.append((request.method, request.url.path, request.extensions.get("timeout", {}).get("read")))
            if request.method == "POST":
                return httpx.Response(201, json={"review": {"review_id": "rv_ongi_paste_001"}, "classification": None})
            return httpx.Response(200, json={"items": [], "count": 0})

        self.client = httpx.Client(base_url="http://review.test", transport=httpx.MockTransport(handler), timeout=10.0)

    def test_paste_waits_longer_than_other_calls(self):
        src = ReviewSource("http://review.test", client=self.client, paste_timeout=45.0).for_visitor("v1")
        src.paste("store_ongi", "공깃밥이 빠졌어요", 2, source="capture")
        src.reviews("store_ongi")
        self.assertEqual([(m, t) for m, _, t in self.seen], [("POST", 45.0), ("GET", 10.0)])

    def test_setting_reaches_the_review_source(self):
        from unittest.mock import patch
        for raw, want in (("60", 60.0), ("", 45.0), ("abc", 45.0)):
            with self.subTest(raw=raw), patch.dict("os.environ", {"REVIEW_PASTE_TIMEOUT_SEC": raw}):
                self.assertEqual(Settings.from_env().review_paste_timeout, want)
