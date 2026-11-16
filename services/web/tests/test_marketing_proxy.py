"""맞춤 마케팅 프록시(web/marketing_proxy.py)와 승인·'처음부터 다시' 연동 검증.
가짜 마케팅 서비스(httpx.MockTransport)를 쓰고 네트워크·HCX 는 부르지 않는다.

확인하는 것
  · 허용 목록: 화면이 쓰는 경로(메서드까지)만 넘기고 stores·records·자체 화면·모르는 경로는 404 (서비스에 보내지 않음)
  · store 는 우리 가게, visitor_id 는 방문자 쿠키로 고정 (브라우저가 보낸 값은 버림). 쿼리는 report 의 period 만
  · 기다리는 시간: 글을 만드는 plan·generate·idea-try 는 길게(45초, MARKETING_TIMEOUT_SEC), 나머지는 10초
  · 꺼짐 503·느림 504·연결 실패 503·서비스 4xx 는 그 상태와 한국어 문장·5xx 502. 어떤 경우에도 500 없음
  · off 면 서비스를 부르지 않음. health 는 늘 200
  · 승인 연동: 성공(2xx, edit_failed 없음)일 때만 이 서버의 승인 기록에 남고(card_id marketing, draft_id mkt-), approval 칸은
    서비스로 가지 않으며, 리뷰 분석 서비스의 '답글 달았음' 기록은 부르지 않음
  · 초기화 연동: DELETE /api/approvals 가 이 방문자의 마케팅 기록도 지움. 서비스가 꺼져 있어도 승인 기록은 지워짐 (marketing_cleared)
  · 다른 화면(/api/health·/api/cards·/)은 마케팅 서비스 장애와 상관없고, 느린 마케팅 호출이 다른 경로를 붙잡지 않음

실행 (services/web 에서): PYTHONPATH=<저장소 루트>:. python -m pytest -q tests/test_marketing_proxy.py
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

from shared.storage import MemoryStore
from shared.storage.memory import MemoryApprovals
from web import marketing_proxy as mp
from web.assistant_proxy import AssistantProxy
from web.care_proxy import CareProxy
from web.demo import Demo
from web.main import create_app
from web.marketing_proxy import MarketingProxy
from web.settings import Settings

from tests.test_care_proxy import FakeCare
from tests.test_web import FakeSource, settings

M = "/api/marketing-survey"
STATE = {"node": "start", "raw": {}, "confirms": {}, "mode": "survey"}


class FakeMarketing:
    """마케팅 서비스(marketing_survey.server)의 겉모습. 모양은 server.py 의 응답 그대로 (A 가 더하는 health·records 포함)."""

    def __init__(self, mode="ok", delay=0.0):
        self.mode, self.delay = mode, delay
        self.requests: list[dict] = []
        self.started = threading.Event()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        rec = {"method": request.method, "path": path, "params": dict(request.url.params),
               "timeout": request.extensions.get("timeout"), "json": None}
        if request.content:
            try:
                rec["json"] = json.loads(request.content)
            except ValueError:
                pass
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
        if mode == "html":
            return httpx.Response(200, text="<html>not json</html>", headers={"content-type": "text/html"})
        if mode == "nf" or mode == "old" and (path.endswith("/health") or path.endswith("/records")):
            return httpx.Response(404, json={"detail": "Not Found"})            # PR #56 그대로인 서비스 (health·records 없음)
        name = path[len(M) + 1:] if path.startswith(M + "/") else None
        body = rec["json"] or {}
        if (request.method, name) == ("GET", "health"):
            return httpx.Response(200, json={"status": "ok", "service": "marketing-survey", "mode": "mock", "mode_source": "MARKETING_APP_MODE",
                                             "key_present": True, "demo": True, "store_id": "store_ongi", "records_dir_writable": True,
                                             "notes": ["mock: 키가 있어도 HCX 를 부르지 않아요."]})
        if (request.method, name) == ("GET", "meta"):
            return httpx.Response(200, json={"store_name": "온기한식 (가상)", "store_id": "store_ongi", "stores": []})
        if (request.method, name) == ("POST", "step"):
            if mode == "400":
                return httpx.Response(400, json={"detail": "이 질문은 보기 중 하나(문자열)를 골라야 해요."})
            if mode == "422":
                return httpx.Response(422, json={"detail": [{"loc": ["body", "answer"], "msg": "bad", "type": "x"}]})
            return httpx.Response(200, json={"state": STATE, "bot_messages": ["무엇을 도와드릴까요?"],
                                             "options": [{"label": "맞춤 홍보 제안"}], "multi": False, "done": False})
        if (request.method, name) in {("POST", n) for n in ("result", "plan", "generate", "next-idea", "idea-try", "coupon-calc",
                                                            "notice-followup")}:
            return httpx.Response(200, json={"title": "재발 방지 공지", "demo": True, "session_id": "s_1", "path": name})
        if (request.method, name) == ("POST", "approve"):
            if any("010-" in t for t in (body.get("edited_texts") or {}).values()):
                return httpx.Response(200, json={"follow_up": False, "state": body.get("state"),
                                                 "edit_failed": {"notice": ["개인정보로 보일 수 있는 내용이 있어요"]}})
            return httpx.Response(200, json={"follow_up": False, "state": body.get("state")})
        if (request.method, name) == ("GET", "report"):
            if request.url.params.get("period") not in ("weekly", "monthly"):
                return httpx.Response(400, json={"detail": "period 는 weekly 또는 monthly 여야 해요."})
            return httpx.Response(200, json={"period": {"kind": request.url.params["period"]}, "demo": True})
        if (request.method, name) == ("DELETE", "records"):
            return httpx.Response(200, json={"deleted": True})
        return httpx.Response(404, json={"detail": "Not Found"})

    def calls(self, method=None, name=None):
        return [r for r in self.requests if (method is None or r["method"] == method) and (name is None or r["path"] == f"{M}/{name}")]


class SpyApprovals(MemoryApprovals):
    """승인 기록을 남길 때 받은 card_id·kind 를 같이 적어 둔다 (메모리 저장소는 두 칸을 목록에 싣지 않음)."""

    def __init__(self):
        super().__init__()
        self.saved: list[dict] = []

    def save(self, store_id, visitor_id, entry, *, card_id=None, kind=None):
        self.saved.append({"visitor_id": visitor_id, "draft_id": entry["draft_id"], "card_id": card_id, "kind": kind,
                           "text": entry["text"], "edited": entry["edited"]})
        super().save(store_id, visitor_id, entry, card_id=card_id, kind=kind)


def build(fake: FakeMarketing | None = None, *, marketing: MarketingProxy | None = None, care: CareProxy | None = None,
          timeout: float = mp.LONG_TIMEOUT):
    tmp = Path(tempfile.mkdtemp())
    fake = fake or FakeMarketing()
    proxy = marketing or MarketingProxy("http://marketing.internal:8030", timeout=timeout, transport=httpx.MockTransport(fake))
    storage = MemoryStore()
    storage.approvals = SpyApprovals()
    demo = Demo(settings(tmp), source=FakeSource(), storage=storage)
    app = create_app(demo, assistant=AssistantProxy(None), care=care or CareProxy(None), marketing=proxy)
    return TestClient(app), proxy, demo


def visitor(client: TestClient) -> str:
    client.get("/api/health")
    return client.cookies["visitor_id"]


def error_of(res) -> dict:
    return res.json()["error"]


class AllowList(unittest.TestCase):
    def setUp(self):
        self.fake = FakeMarketing()
        self.client, self.proxy, _ = build(self.fake)

    def test_the_routes_the_screen_uses_are_forwarded(self):
        c = self.client
        self.assertEqual(c.get(f"{M}/meta").json()["store_name"], "온기한식 (가상)")
        self.assertEqual(c.post(f"{M}/step", json={"state": None, "answer": None}).json()["bot_messages"], ["무엇을 도와드릴까요?"])
        for name in ("result", "plan", "generate", "next-idea", "idea-try", "coupon-calc", "notice-followup"):
            res = c.post(f"{M}/{name}", json={"state": STATE})
            self.assertEqual((res.status_code, res.json()["path"]), (200, name), name)
        self.assertEqual(c.post(f"{M}/approve", json={"state": STATE}).status_code, 200)
        self.assertEqual(c.get(f"{M}/report?period=weekly").json()["period"]["kind"], "weekly")
        names = [r["path"][len(M) + 1:] for r in self.fake.requests]
        self.assertEqual(names, ["meta", "step", "result", "plan", "generate", "next-idea", "idea-try", "coupon-calc",
                                 "notice-followup", "approve", "report"])
        self.assertEqual(self.fake.calls("POST", "step")[0]["json"], {"state": None, "answer": None})     # 본문은 그대로

    def test_everything_else_is_404_and_never_reaches_the_service(self):
        c = self.client
        refused = [("GET", f"{M}/stores"), ("DELETE", f"{M}/records"), ("GET", f"{M}/records"), ("GET", f"{M}/step"),
                   ("POST", f"{M}/meta"), ("PUT", f"{M}/approve"), ("POST", f"{M}/report"), ("GET", f"{M}/plan"),
                   ("POST", f"{M}/health"), ("GET", f"{M}/web/app.js"), ("GET", f"{M}/"), ("GET", f"{M}/step/"),
                   ("GET", f"{M}/unknown")]
        for method, path in refused:
            with self.subTest(method=method, path=path):
                res = c.request(method, path, json={} if method != "GET" else None)
                self.assertIn(res.status_code, (404, 405))
                if res.status_code == 404 and res.headers.get("content-type", "").startswith("application/json") and "error" in res.json():
                    self.assertEqual(error_of(res)["state"], "not_found")
        self.assertEqual(self.fake.requests, [])
        self.assertEqual(c.get("/web/app.js").status_code, 404)             # 김수현 님 자체 화면은 이 서버에 없다

    def test_store_and_visitor_are_fixed_by_the_server(self):
        me = visitor(self.client)
        self.client.post(f"{M}/step?store=store_basak&visitor_id=someone_else&debug=1", json={"state": None, "answer": None})
        self.client.get(f"{M}/report?period=monthly&store=store_mongle&visitor_id=x&extra=1")
        self.client.get(f"{M}/meta?store=store_basak")
        for rec in self.fake.requests:
            with self.subTest(path=rec["path"]):
                self.assertEqual(rec["params"]["store"], "store_ongi")
                self.assertEqual(rec["params"]["visitor_id"], me)
        self.assertEqual(self.fake.calls("GET", "report")[0]["params"], {"store": "store_ongi", "visitor_id": me, "period": "monthly"})
        self.assertEqual(self.fake.calls("POST", "step")[0]["params"], {"store": "store_ongi", "visitor_id": me})

    def test_each_visitor_cookie_gets_its_own_visitor_id(self):
        other = TestClient(self.client.app)
        a, b = visitor(self.client), visitor(other)
        self.assertNotEqual(a, b)
        self.client.get(f"{M}/meta")
        other.get(f"{M}/meta")
        self.assertEqual([r["params"]["visitor_id"] for r in self.fake.requests], [a, b])

    def test_a_bad_cookie_is_replaced_not_forwarded(self):
        fresh = TestClient(self.client.app, cookies={"visitor_id": "../../etc"})
        fresh.get(f"{M}/meta")
        sent = self.fake.requests[-1]["params"]["visitor_id"]
        self.assertNotEqual(sent, "../../etc")
        self.assertTrue(mp.VISITOR_ID.fullmatch(sent))

    def test_long_waits_only_for_the_paths_that_write(self):
        c = self.client
        c.get(f"{M}/meta")
        for name in ("step", "plan", "generate", "idea-try", "coupon-calc", "approve", "next-idea", "notice-followup"):
            c.post(f"{M}/{name}", json={"state": STATE})
        c.get(f"{M}/report?period=weekly")
        reads = {r["path"][len(M) + 1:]: r["timeout"]["read"] for r in self.fake.requests}
        for name in ("plan", "generate", "idea-try"):
            self.assertEqual(reads[name], 45.0, name)
        for name in ("meta", "step", "coupon-calc", "approve", "next-idea", "notice-followup", "report"):
            self.assertEqual(reads[name], 10.0, name)

    def test_long_wait_follows_the_setting(self):
        fake = FakeMarketing()
        proxy = MarketingProxy.from_settings(Settings(marketing_url="http://m.internal:8030", marketing_timeout=80.0))
        proxy.client._transport = httpx.MockTransport(fake)
        client, _, _ = build(fake, marketing=proxy)
        client.post(f"{M}/plan", json={"state": STATE})
        client.post(f"{M}/step", json={"state": STATE})
        self.assertEqual([r["timeout"]["read"] for r in fake.requests], [80.0, 10.0])


class NothingDiesWhenTheServiceIsUnwell(unittest.TestCase):
    def test_down_slow_and_off(self):
        cases = [("down", FakeMarketing("down"), None, 503), ("slow", FakeMarketing("timeout"), None, 504),
                 ("off", None, MarketingProxy(None), 503)]
        for state, fake, proxy, code in cases:
            with self.subTest(state=state):
                client, _, _ = build(fake, marketing=proxy)
                res = client.post(f"{M}/plan", json={"state": STATE})
                self.assertEqual((res.status_code, error_of(res)["state"]), (code, state))
                self.assertEqual(error_of(res)["message"], mp.MESSAGES[state])
                self.assertEqual(res.headers["cache-control"], "no-store")

    def test_off_never_calls_the_service(self):
        fake = FakeMarketing()
        proxy = MarketingProxy.from_settings(Settings(marketing_url="off"))
        self.assertIsNone(proxy.client)
        client, _, _ = build(fake, marketing=proxy)
        self.assertEqual(client.post(f"{M}/step", json={}).status_code, 503)
        self.assertEqual(client.get(f"{M}/health").json()["state"], "off")
        self.assertEqual(client.delete("/api/approvals").json(), {"deleted": 0, "marketing_cleared": None})
        self.assertEqual(fake.requests, [])

    def test_bad_address_setting_is_an_error_not_off(self):
        for raw in ("ftp://m.internal", "http://m.internal/api", "http://user:pw@m.internal", "localhost:8030"):
            with self.subTest(raw=raw):
                proxy = MarketingProxy.from_settings(Settings(marketing_url=raw))
                self.assertIsNone(proxy.client)
                client, _, _ = build(marketing=proxy)
                self.assertEqual(client.get(f"{M}/health").json()["state"], "error")
                res = client.get(f"{M}/meta")
                self.assertEqual((res.status_code, error_of(res)["state"]), (503, "error"))
                self.assertIn("MARKETING_SURVEY_URL", error_of(res)["message"])

    def test_no_500_from_upstream_errors_odd_replies_or_our_own_bugs(self):
        for mode, code in (("500", 502), ("html", 502), ("boom", 503)):
            with self.subTest(mode=mode):
                client, _, _ = build(FakeMarketing(mode))
                for method, path in (("POST", f"{M}/plan"), ("GET", f"{M}/meta"), ("POST", f"{M}/approve")):
                    res = client.request(method, path, json={"state": STATE} if method == "POST" else None)
                    self.assertEqual(res.status_code, code, (mode, path))
                    self.assertEqual(error_of(res)["state"], "error")
                    self.assertTrue(error_of(res)["message"])

    def test_service_4xx_keeps_its_status_and_becomes_the_screen_error_shape(self):
        client, _, _ = build(FakeMarketing("400"))
        res = client.post(f"{M}/step", json={"state": STATE, "answer": ["x"]})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json(), {"error": {"message": "이 질문은 보기 중 하나(문자열)를 골라야 해요.", "state": "invalid"}})
        client, _, _ = build(FakeMarketing("422"))
        res = client.post(f"{M}/step", json={"state": STATE})
        self.assertEqual((res.status_code, error_of(res)), (422, {"message": mp.MESSAGES["invalid"], "state": "invalid"}))
        client, _, _ = build(FakeMarketing())
        res = client.get(f"{M}/report?period=daily")
        self.assertEqual((res.status_code, error_of(res)["message"]), (400, "period 는 weekly 또는 monthly 여야 해요."))
        client, _, _ = build(FakeMarketing("nf"))
        res = client.get(f"{M}/meta")                                       # 경로가 없는 판(영어 'Not Found')은 정해 둔 한국어로
        self.assertEqual((res.status_code, error_of(res)), (404, {"message": mp.MISSING, "state": "not_found"}))

    def test_bodies_over_the_cap_are_413_and_bad_bodies_422(self):
        fake = FakeMarketing()
        client, _, _ = build(fake)
        big = client.post(f"{M}/plan", content=b'{"state": "' + b"x" * (mp.MAX_JSON + 10) + b'"}',
                          headers={"content-type": "application/json"})
        self.assertEqual((big.status_code, error_of(big)["state"]), (413, "too_big"))
        for content in (b"not json", b"[1, 2]"):
            res = client.post(f"{M}/step", content=content, headers={"content-type": "application/json"})
            self.assertEqual((res.status_code, error_of(res)["state"]), (422, "invalid"))
        self.assertEqual(fake.requests, [])

    def test_health_is_always_200(self):
        cases = [(FakeMarketing(), None, "ready"), (FakeMarketing("down"), None, "down"), (FakeMarketing("timeout"), None, "down"),
                 (FakeMarketing("500"), None, "error"), (FakeMarketing("html"), None, "error"),
                 (None, MarketingProxy(None), "off")]
        for fake, proxy, state in cases:
            with self.subTest(state=state, mode=getattr(fake, "mode", "off")):
                client, _, _ = build(fake, marketing=proxy)
                res = client.get(f"{M}/health")
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["state"], state)
                self.assertEqual(res.json()["service"], "marketing-survey")
        ready = build(FakeMarketing())[0].get(f"{M}/health").json()
        self.assertEqual((ready["mode"], ready["key_present"], ready["demo"]), ("mock", True, True))   # mock 이면 키가 있어도 데모
        self.assertEqual(ready["notes"], ["mock: 키가 있어도 HCX 를 부르지 않아요."])
        self.assertNotIn("records_dir_writable", ready)                     # 화면이 쓰지 않는 칸은 넘기지 않는다

    def test_health_on_a_service_without_the_health_path_falls_back_to_meta(self):
        fake = FakeMarketing("old")
        client, _, _ = build(fake)
        data = client.get(f"{M}/health").json()
        self.assertEqual((data["state"], data["mode"], data["key_present"]), ("ready", None, None))
        self.assertEqual([r["path"] for r in fake.requests], [f"{M}/health", f"{M}/meta"])

    def test_other_screens_do_not_feel_the_marketing_service(self):
        for fake in (FakeMarketing("down"), FakeMarketing("timeout"), FakeMarketing("boom"), FakeMarketing("500")):
            with self.subTest(mode=fake.mode):
                client, _, _ = build(fake)
                health = client.get("/api/health")
                self.assertEqual(health.status_code, 200)
                self.assertNotIn("마케팅", json.dumps(health.json(), ensure_ascii=False))   # 맨 위 막힘 띠에 섞이지 않는다
                self.assertNotIn("marketing", health.json())
                self.assertEqual(client.get("/api/cards").status_code, 200)
                self.assertEqual(client.get("/api/briefing").status_code, 200)
                self.assertEqual(client.get("/").status_code, 200)
                self.assertEqual(fake.requests, [])                          # 다른 화면은 마케팅 서비스를 부르지 않는다


class DoesNotBlockTheServer(unittest.TestCase):
    def test_a_slow_plan_does_not_hold_up_other_routes(self):
        fake = FakeMarketing(delay=1.5)
        client, _, _ = build(fake)
        done = {}
        with TestClient(client.app) as c:
            worker = threading.Thread(target=lambda: done.setdefault("r", c.post(f"{M}/plan", json={"state": STATE})))
            worker.start()
            self.assertTrue(fake.started.wait(5))
            t0 = time.perf_counter()
            health = c.get("/api/health")
            cards = c.get("/api/cards")
            waited = time.perf_counter() - t0
            worker.join(10)
        self.assertEqual((health.status_code, cards.status_code), (200, 200))
        self.assertLess(waited, 0.8, f"느린 마케팅 호출 동안 다른 경로가 {waited:.2f}초 기다림")
        self.assertEqual(done["r"].status_code, 200)


class ApprovalIsRecordedHere(unittest.TestCase):
    ITEM = {"draft_id": "r1-notice", "text": "포장할 때 주문서를 한 번 더 확인할게요.", "original": "포장할 때 주문서를 확인할게요.",
            "kind": "공지", "title": "재발 방지 공지"}

    def setUp(self):
        self.fake = FakeMarketing()
        self.care_fake = FakeCare()
        self.care = CareProxy("http://care.internal:8020", transport=httpx.MockTransport(self.care_fake))
        self.client, self.proxy, self.demo = build(self.fake, care=self.care)
        self.me = visitor(self.client)

    def approve(self, approval, edited=None):
        body = {"state": STATE, "draft_id": None, "session_id": "s_1", "edited_texts": edited or {}, "approval": approval}
        res = self.client.post(f"{M}/approve", json=body)
        self.care.flush()
        return res

    def test_a_successful_approval_lands_in_this_servers_records(self):
        res = self.approve(self.ITEM)
        self.assertEqual(res.status_code, 200, res.text)
        (row,) = res.json()["recorded"]
        self.assertEqual((row["draft_id"], row["kind"], row["edited"]), ("mkt-r1-notice", "공지", True))
        self.assertTrue(row["approved_at"])
        self.assertEqual(res.json()["follow_up"], False)                     # 서비스 응답은 그대로
        (saved,) = self.demo.storage.approvals.saved
        self.assertEqual(saved, {"visitor_id": self.me, "draft_id": "mkt-r1-notice", "card_id": "marketing", "kind": "공지",
                                 "text": self.ITEM["text"], "edited": True})
        items = self.client.get("/api/approvals").json()["items"]            # '처리 완료'의 '서버 처리 기록'
        self.assertEqual([i["draft_id"] for i in items], ["mkt-r1-notice"])

    def test_the_approval_field_never_reaches_the_service(self):
        self.approve([self.ITEM, {**self.ITEM, "draft_id": "r1-reply", "kind": "답글"}])
        sent = self.fake.calls("POST", "approve")[0]["json"]
        self.assertNotIn("approval", sent)
        self.assertEqual(sent, {"state": STATE, "draft_id": None, "session_id": "s_1", "edited_texts": {}})

    def test_a_list_is_recorded_item_by_item_and_odd_items_are_cleaned(self):
        res = self.approve([self.ITEM, {"text": "  "}, "글", {"draft_id": "../x", "text": "쿠폰 글", "kind": "reply_draft"},
                            {"draft_id": "mkt-already", "text": "홍보", "kind": "홍보 글"}])
        rows = res.json()["recorded"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["draft_id"], "mkt-r1-notice")
        self.assertTrue(rows[1]["draft_id"].startswith("mkt-") and "../" not in rows[1]["draft_id"])
        self.assertEqual(rows[1]["kind"], "마케팅 글")                       # 비서 화면의 초안 종류(reply_draft)는 받지 않는다
        self.assertEqual(rows[2]["draft_id"], "mkt-already")                  # 접두사를 두 번 붙이지 않는다
        self.assertEqual(len(self.approve([self.ITEM] * 15).json()["recorded"]), mp.MAX_APPROVALS)

    def test_a_marketing_reply_never_marks_a_review_as_replied(self):
        self.approve({**self.ITEM, "kind": "답글", "draft_id": "r1-reply"})
        self.approve({**self.ITEM, "kind": "reply_draft", "draft_id": "r1-reply2"})
        self.assertEqual(self.care_fake.requests, [])                        # 리뷰 분석 서비스의 '답글 달았음'을 부르지 않는다

    def test_edit_failed_is_not_recorded(self):
        res = self.approve(self.ITEM, edited={"notice": "연락은 010-1234-5678 로 주세요"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("edit_failed", res.json())
        self.assertNotIn("recorded", res.json())
        self.assertEqual(self.demo.storage.approvals.saved, [])

    def test_a_failed_approval_is_not_recorded(self):
        for mode in ("down", "timeout", "500", "html", "nf"):
            with self.subTest(mode=mode):
                self.fake.mode = mode
                res = self.approve(self.ITEM)
                self.assertGreaterEqual(res.status_code, 400)
                self.assertNotEqual(res.status_code, 500)
        self.assertEqual(self.demo.storage.approvals.saved, [])

    def test_without_an_approval_field_nothing_is_recorded(self):
        res = self.client.post(f"{M}/approve", json={"state": STATE, "edited_texts": {}})
        self.assertEqual(res.json()["recorded"], [])
        self.assertEqual(self.demo.storage.approvals.saved, [])

    def test_a_storage_failure_does_not_fail_the_approval(self):
        def broken(*a, **k):
            raise RuntimeError("저장소 고장")
        self.demo.approve = broken
        res = self.approve(self.ITEM)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["recorded"], [])
        self.assertEqual(res.json()["record_warning"], mp.RECORD_WARNING)


class RestartClearsMarketingRecords(unittest.TestCase):
    def test_restart_deletes_this_visitors_marketing_records(self):
        fake = FakeMarketing()
        client, _, _ = build(fake)
        me = visitor(client)
        client.post(f"{M}/approve", json={"state": STATE, "approval": ApprovalIsRecordedHere.ITEM})
        res = client.delete("/api/approvals")
        self.assertEqual(res.json(), {"deleted": 1, "marketing_cleared": True})
        (call,) = fake.calls("DELETE", "records")
        self.assertEqual(call["params"], {"store": "store_ongi", "visitor_id": me})
        self.assertLessEqual(call["timeout"]["read"], mp.CLEAR_TIMEOUT)
        self.assertEqual(client.get("/api/approvals").json(), {"items": []})

    def test_approvals_are_cleared_even_when_the_marketing_service_is_unwell(self):
        for mode, cleared in (("down", None), ("old", False), ("500", False), ("timeout", False), ("boom", False)):
            with self.subTest(mode=mode):
                fake = FakeMarketing()
                client, _, demo = build(fake)
                client.post(f"{M}/approve", json={"state": STATE, "approval": ApprovalIsRecordedHere.ITEM})
                fake.mode = mode
                res = client.delete("/api/approvals")
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json(), {"deleted": 1, "marketing_cleared": cleared})
                self.assertEqual(client.get("/api/approvals").json(), {"items": []})


if __name__ == "__main__":
    unittest.main()
