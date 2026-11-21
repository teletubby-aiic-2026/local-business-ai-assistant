"""계정 초기화(POST /api/auth/reset)와 회원 탈퇴(POST /api/auth/withdraw) (11/19). CLOVA·네트워크는 부르지 않는다.

- 초기화: 로그인한 사장님만. scope=store 는 지금 가게 하나, account 는 가진 가게 모두. 그 사장님(u-<user_id>)의 기록만 지운다
  (다른 가게·다른 사장님·게스트의 기록은 그대로). 못 지운 것이 있으면 200 + complete=false + message. 500 은 없다.
- 리뷰 분석 서비스에는 forget_labels=true 를 붙여 분류 결과까지 지우게 한다. 게스트의 '데모 다시 하기'는 예전처럼 붙이지 않는다.
- 맞춤 마케팅은 cleared | off | failed 로 나눈다 (예전 '처음부터 다시'의 marketing_cleared true·false·null 은 그대로).

실행 (services/web 에서):  env -u APP_MODE PYTHONPATH=../.. python -m pytest -q tests/test_account_data.py
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from shared.storage import MemoryStore, StorageError
from tests.test_auth_stores import Recorder, signup
from tests.test_web import settings
from web.assistant_proxy import AssistantProxy
from web.auth import SESSION_COOKIE, AuthService
from web.care_proxy import CareProxy
from web.demo import Demo
from web.main import create_app
from web.marketing_proxy import MarketingProxy
from web.sources import ReviewSource

STORES = ("store_ongi", "store_basak", "store_mongle")


class FakeReview:
    """리뷰 분석 서비스 대신. (가게, 방문자)마다 붙여넣은 리뷰 수를 들고 DELETE /reviews/pasted 를 받는다."""

    def __init__(self):
        self.pasted: dict[tuple[str, str], int] = {}
        self.requests: list[dict] = []
        self.fail_stores: set[str] = set()
        self.old = False                      # True 면 forget_labels 를 모르는 옛 판 (labels_deleted 를 안 줌)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.requests.append({"method": request.method, "path": request.url.path, "params": params})
        if request.method == "DELETE" and request.url.path == "/api/review-insight/reviews/pasted":
            store, visitor = params["store_id"], params.get("visitor_id", "common")
            if store in self.fail_stores:
                return httpx.Response(503, json={"error": {"message": "DB 에 닿지 못했습니다"}})
            n = self.pasted.pop((store, visitor), 0)
            body = {"deleted": n}
            if params.get("forget_labels") == "true" and not self.old:
                body["labels_deleted"] = n
            return httpx.Response(200, json=body)
        return httpx.Response(404, json={"error": {"message": "없음"}})

    def deletes(self) -> list[dict]:
        return [r["params"] for r in self.requests if r["method"] == "DELETE"]


def _down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("연결 안 됨", request=request)


def entry(draft_id: str) -> dict:
    return {"draft_id": draft_id, "status": "approved", "edited": False, "text": "글",
            "approved_at": "2026-11-19T10:00:00+09:00", "mode": "mock"}


def build(*, storage=None, marketing: str = "ok"):
    tmp = Path(tempfile.mkdtemp())
    storage = storage or MemoryStore()
    review = FakeReview()
    source = ReviewSource("http://review.test", client=httpx.Client(base_url="http://review.test",
                                                                    transport=httpx.MockTransport(review)))
    mkt = Recorder({"deleted": 0})
    if marketing == "ok":
        proxy = MarketingProxy("http://marketing.test", transport=httpx.MockTransport(mkt))
    elif marketing == "down":
        proxy = MarketingProxy("http://marketing.test", transport=httpx.MockTransport(_down))
    else:
        proxy = MarketingProxy(None)
    demo = Demo(settings(tmp), source=source, storage=storage)
    app = create_app(demo, assistant=AssistantProxy(None), care=CareProxy(None), marketing=proxy,
                     auth=AuthService(storage))
    return app, demo, review, mkt


def visitor_of(client) -> str:
    return "u-" + client.get("/api/auth/me").json()["user"]["user_id"]


def seed(storage, review: FakeReview, visitor: str, stores=STORES, n: int = 2) -> None:
    """가게마다 승인 n 건·붙여넣은 리뷰 n 건."""
    for store in stores:
        for i in range(n):
            storage.approvals.save(store, visitor, entry(f"{store}-{visitor}-{i}"))
        review.pasted[(store, visitor)] = n


def market_cookies_expired(res) -> set[str]:
    paths = set()
    for value in res.headers.get_list("set-cookie"):
        if value.startswith("market_onboarding_session=") and ("Max-Age=0" in value or "expires=Thu, 01 Jan 1970" in value):
            paths.add(value.split("Path=")[1].split(";")[0])
    return paths


class ResetGuards(unittest.TestCase):
    def setUp(self):
        self.app, self.demo, self.review, self.mkt = build()
        self.client = TestClient(self.app)

    def test_guest_gets_401_and_nothing_is_touched(self):
        self.client.get("/api/auth/me")
        guest = self.client.cookies["visitor_id"]
        seed(self.demo.storage, self.review, guest, stores=("store_ongi",))
        for body in ({"scope": "store"}, {"scope": "account"}, {"scope": "bad"}):
            res = self.client.post("/api/auth/reset", json=body)
            self.assertEqual(res.status_code, 401)
            self.assertEqual(res.json()["error"]["state"], "login_needed")
            self.assertEqual(res.headers["cache-control"], "no-store")
        self.assertEqual(self.review.deletes(), [])
        self.assertEqual(self.mkt.requests, [])
        self.assertEqual(len(self.demo.storage.approvals.list("store_ongi", guest)), 2)

    def test_bad_scope_is_422_in_the_auth_error_shape(self):
        signup(self.client)
        for kwargs in ({"json": {"scope": "all"}}, {"json": {}}, {"json": ["store"]}, {"content": b"not json"},
                       {"content": b""}, {"json": {"scope": None}}):
            res = self.client.post("/api/auth/reset", **kwargs)
            self.assertEqual(res.status_code, 422, kwargs)
            self.assertEqual(res.json()["error"]["state"], "invalid")
            self.assertIn("scope", res.json()["error"]["message"])
            self.assertEqual(res.headers["cache-control"], "no-store")
        self.assertEqual(self.review.deletes(), [])


class ResetScopes(unittest.TestCase):
    def setUp(self):
        self.app, self.demo, self.review, self.mkt = build()
        self.client = TestClient(self.app)
        signup(self.client, stores=("store_ongi", "store_basak"))
        self.me = visitor_of(self.client)
        other = TestClient(self.app)
        signup(other, login="owner02", stores=STORES)
        self.other = visitor_of(other)
        guest = TestClient(self.app)
        guest.get("/api/auth/me")
        self.guest = guest.cookies["visitor_id"]
        for v in (self.me, self.other, self.guest):
            seed(self.demo.storage, self.review, v)

    def left(self, visitor, store):
        return len(self.demo.storage.approvals.list(store, visitor)), self.review.pasted.get((store, visitor), 0)

    def test_store_scope_clears_only_the_current_store_of_this_owner(self):
        res = self.client.post("/api/auth/reset", json={"scope": "store"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.headers["cache-control"], "no-store")
        self.assertEqual(res.json(), {"scope": "store", "complete": True, "message": None, "reports": 0,
                                      "stores": [{"store_id": "store_ongi", "name": "온기한식", "approvals": 2, "reviews": 2,
                                                  "marketing": "cleared"}]})
        self.assertEqual(self.left(self.me, "store_ongi"), (0, 0))
        self.assertEqual(self.left(self.me, "store_basak"), (2, 2))                  # 다른 가게는 그대로
        for v in (self.other, self.guest):                                           # 다른 사장님·게스트는 그대로
            for s in STORES:
                self.assertEqual(self.left(v, s), (2, 2))
        # 아래 서비스에 넘어간 가게·방문자
        self.assertEqual(self.review.deletes(), [{"store_id": "store_ongi", "visitor_id": self.me, "forget_labels": "true"}])
        self.assertEqual([r["params"] for r in self.mkt.requests], [{"store": "store_ongi", "visitor_id": self.me}])
        self.assertEqual(self.mkt.requests[0]["path"], "/api/marketing-survey/records")
        self.assertEqual(market_cookies_expired(res), {"/api/assistant", "/api/market"})
        # 계정·가게 목록·세션은 남는다
        me = self.client.get("/api/auth/me").json()
        self.assertTrue(me["authenticated"])
        self.assertEqual([s["store_id"] for s in me["stores"]], ["store_ongi", "store_basak"])

    def test_store_scope_follows_the_store_being_viewed(self):
        self.client.post("/api/auth/store", json={"store_id": "store_basak"})
        data = self.client.post("/api/auth/reset", json={"scope": "store"}).json()
        self.assertEqual([s["store_id"] for s in data["stores"]], ["store_basak"])
        self.assertEqual(self.left(self.me, "store_basak"), (0, 0))
        self.assertEqual(self.left(self.me, "store_ongi"), (2, 2))

    def test_account_scope_clears_every_owned_store_and_nothing_else(self):
        res = self.client.post("/api/auth/reset", json={"scope": "account"})
        data = res.json()
        self.assertEqual((res.status_code, data["scope"], data["complete"], data["message"]), (200, "account", True, None))
        self.assertEqual([(s["store_id"], s["name"], s["approvals"], s["reviews"], s["marketing"]) for s in data["stores"]],
                         [("store_ongi", "온기한식", 2, 2, "cleared"), ("store_basak", "바삭치킨", 2, 2, "cleared")])
        self.assertEqual(self.left(self.me, "store_ongi"), (0, 0))
        self.assertEqual(self.left(self.me, "store_basak"), (0, 0))
        self.assertEqual(self.left(self.me, "store_mongle"), (2, 2))                 # 가지지 않은 가게는 건드리지 않음
        for v in (self.other, self.guest):
            for s in STORES:
                self.assertEqual(self.left(v, s), (2, 2))
        self.assertEqual({(p["store_id"], p["visitor_id"]) for p in self.review.deletes()},
                         {("store_ongi", self.me), ("store_basak", self.me)})
        self.assertEqual({(r["params"]["store"], r["params"]["visitor_id"]) for r in self.mkt.requests},
                         {("store_ongi", self.me), ("store_basak", self.me)})
        self.assertTrue(self.client.get("/api/auth/me").json()["authenticated"])

    def test_reset_twice_is_safe(self):
        self.client.post("/api/auth/reset", json={"scope": "account"})
        data = self.client.post("/api/auth/reset", json={"scope": "account"}).json()
        self.assertTrue(data["complete"])
        self.assertEqual([(s["approvals"], s["reviews"]) for s in data["stores"]], [(0, 0), (0, 0)])

    def test_pending_approvals_are_dropped_too(self):
        held = entry("held-1")
        with self.demo._lock:
            self.demo._pending.append((self.me, held, None, None, None))
        data = self.client.post("/api/auth/reset", json={"scope": "store"}).json()
        self.assertEqual(data["stores"][0]["approvals"], 3)
        self.assertEqual([p for p in self.demo._pending if p[0] == self.me], [])


def save_report(storage, store: str, visitor: str, kind: str = "weekly", version: str = "r1") -> None:
    """저장된 보고서 한 줄 (주간 11/9~11/15 · 월간 10월). version 이 다르면 같은 기간에 줄이 하나 더 생긴다."""
    start, end = ("2026-11-09", "2026-11-15") if kind == "weekly" else ("2026-10-01", "2026-10-31")
    storage.reports.save(store, kind, start, end, numbers={"version": 1}, body_text="", evidence_ids=[],
                         prompt_version=version, visitor_id=visitor)


class ResetReports(unittest.TestCase):
    """초기화 응답의 reports = 지운 저장 보고서 수 (화면 결과 띠에 '보관한 보고서 n개', 11/21 QA)."""

    def setUp(self):
        self.app, self.demo, self.review, _ = build()
        self.client = TestClient(self.app)
        signup(self.client, stores=("store_ongi", "store_basak"))
        self.me = visitor_of(self.client)
        other = TestClient(self.app)
        signup(other, login="owner02", stores=STORES)
        self.other = visitor_of(other)
        st = self.demo.storage
        save_report(st, "store_ongi", self.me, "weekly")
        save_report(st, "store_ongi", self.me, "weekly", version="r2")    # 같은 기간 다른 판: 프로필처럼 하나로 셈
        save_report(st, "store_ongi", self.me, "monthly")
        save_report(st, "store_basak", self.me, "weekly")
        save_report(st, "store_ongi", self.other, "weekly")

    def test_store_then_account_report_the_number_of_saved_reports_erased(self):
        self.assertEqual(self.demo.storage.reports.count(["store_ongi", "store_basak"], self.me), {"weekly": 2, "monthly": 1})
        data = self.client.post("/api/auth/reset", json={"scope": "store"}).json()
        self.assertEqual((data["complete"], data["reports"]), (True, 2))
        self.assertEqual(self.demo.storage.reports.count(["store_ongi"], self.me), {"weekly": 0, "monthly": 0})
        data = self.client.post("/api/auth/reset", json={"scope": "account"}).json()
        self.assertEqual((data["complete"], data["reports"]), (True, 1))
        self.assertEqual(self.client.post("/api/auth/reset", json={"scope": "account"}).json()["reports"], 0)
        # 다른 사장님 것은 그대로
        self.assertEqual(self.demo.storage.reports.count(["store_ongi"], self.other), {"weekly": 1, "monthly": 0})

    def test_reports_that_could_not_be_erased_are_null_and_incomplete(self):
        with mock.patch.object(self.app.state.reports.storage.reports, "delete", side_effect=StorageError("DB 에 닿지 못함")):
            res = self.client.post("/api/auth/reset", json={"scope": "account"})
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual((data["complete"], data["reports"]), (False, None))
        self.assertIn("저장된 보고서", data["message"])
        self.assertEqual([s["approvals"] for s in data["stores"]], [0, 0])               # 나머지는 지움

    def test_counting_failure_falls_back_to_rows_erased(self):
        with mock.patch.object(self.app.state.reports.storage.reports, "count", side_effect=StorageError("DB 에 닿지 못함")):
            data = self.client.post("/api/auth/reset", json={"scope": "store"}).json()
        self.assertEqual((data["complete"], data["reports"]), (True, 3))                  # 센 수 대신 지운 줄 수

    def test_withdraw_still_answers_with_the_guest_identity(self):
        res = self.client.post("/api/auth/withdraw", json={"password": "pass-word-1"})   # signup() 의 시험용 비밀번호
        self.assertEqual(res.status_code, 200, res.text)
        self.assertNotIn("reports", res.json())
        self.assertTrue(res.json()["withdrawn"])
        self.assertEqual(self.demo.storage.reports.count(["store_ongi", "store_basak"], self.me), {"weekly": 0, "monthly": 0})


class ResetPartialFailure(unittest.TestCase):
    def test_what_could_not_be_cleared_is_reported_without_a_500(self):
        app, demo, review, _ = build(marketing="down")
        client = TestClient(app)
        signup(client, stores=("store_ongi", "store_basak"))
        me = visitor_of(client)
        seed(demo.storage, review, me, stores=("store_ongi", "store_basak"))
        review.fail_stores = {"store_basak"}
        res = client.post("/api/auth/reset", json={"scope": "account"})
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertFalse(data["complete"])
        self.assertEqual([(s["approvals"], s["reviews"], s["marketing"]) for s in data["stores"]],
                         [(2, 2, "failed"), (2, None, "failed")])
        self.assertIn("바삭치킨의 붙여넣은 리뷰·맞춤 마케팅 기록", data["message"])
        self.assertIn("온기한식의 맞춤 마케팅 기록", data["message"])
        self.assertEqual(len(demo.storage.approvals.list("store_basak", me)), 0)     # 지울 수 있는 것은 지움
        self.assertEqual(review.pasted[("store_basak", me)], 2)
        self.assertEqual(market_cookies_expired(res), {"/api/assistant", "/api/market"})

    def test_approval_store_down_is_null_and_incomplete(self):
        app, demo, review, _ = build()
        client = TestClient(app)
        signup(client, stores=("store_ongi",))
        with mock.patch.object(demo.storage.approvals, "clear", side_effect=StorageError("DB 에 닿지 못함")):
            data = client.post("/api/auth/reset", json={"scope": "store"}).json()
        self.assertEqual((data["complete"], data["stores"][0]["approvals"], data["stores"][0]["reviews"]), (False, None, 0))
        self.assertIn("온기한식의 승인 기록", data["message"])

    def test_review_service_that_cannot_forget_labels_counts_as_not_cleared(self):
        app, demo, review, _ = build()
        review.old = True
        client = TestClient(app)
        signup(client, stores=("store_ongi",))
        data = client.post("/api/auth/reset", json={"scope": "store"}).json()
        self.assertEqual((data["complete"], data["stores"][0]["reviews"]), (False, None))

    def test_marketing_off_is_not_a_failure(self):
        app, demo, review, _ = build(marketing="off")
        client = TestClient(app)
        signup(client, stores=("store_ongi",))
        data = client.post("/api/auth/reset", json={"scope": "account"}).json()
        self.assertEqual((data["complete"], data["message"], data["stores"][0]["marketing"]), (True, None, "off"))


class ResetDemoAccounts(unittest.TestCase):
    def test_each_browser_clears_only_its_own_demo_owner(self):
        app, demo, review, _ = build()
        a, b = TestClient(app), TestClient(app)
        for c in (a, b):
            c.get("/api/auth/me")
            self.assertEqual(c.post("/api/auth/demo-login").status_code, 200)
        va, vb = visitor_of(a), visitor_of(b)
        self.assertNotEqual(va, vb)
        self.assertTrue(va.startswith("u-demo-"))
        seed(demo.storage, review, va)
        seed(demo.storage, review, vb)
        data = a.post("/api/auth/reset", json={"scope": "account"}).json()
        self.assertTrue(data["complete"])
        self.assertEqual([s["store_id"] for s in data["stores"]], list(STORES))
        for s in STORES:
            self.assertEqual(demo.storage.approvals.list(s, va), [])
            self.assertEqual(len(demo.storage.approvals.list(s, vb)), 2)
            self.assertEqual(review.pasted.get((s, vb)), 2)


class GuestPathsUnchanged(unittest.TestCase):
    def test_delete_approvals_and_pasted_keep_their_old_shape(self):
        app, demo, review, mkt = build()
        client = TestClient(app)
        client.get("/api/auth/me")
        guest = client.cookies["visitor_id"]
        seed(demo.storage, review, guest, stores=("store_ongi",))
        self.assertEqual(client.delete("/api/approvals").json(), {"deleted": 2, "marketing_cleared": True})
        self.assertEqual(client.delete("/api/reviews/pasted").json(), {"deleted": 2})
        self.assertEqual(review.deletes(), [{"store_id": "store_ongi", "visitor_id": guest}])   # forget_labels 없음
        self.assertNotIn(SESSION_COOKIE, client.cookies)

    def test_marketing_clear_records_keeps_true_false_null(self):
        ok = MarketingProxy("http://m.test", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
        refused = MarketingProxy("http://m.test", transport=httpx.MockTransport(lambda r: httpx.Response(404, json={})))
        down = MarketingProxy("http://m.test", transport=httpx.MockTransport(_down))
        off = MarketingProxy(None)
        bad = MarketingProxy(None, config_error="주소가 틀림")
        self.assertEqual([p.clear_records("u-abc") for p in (ok, refused, down, off, bad)], [True, False, None, None, None])
        self.assertIs(ok.clear_records("../x"), False)
        self.assertEqual([p.clear_state("u-abc") for p in (ok, refused, down, off, bad)],
                         ["cleared", "failed", "failed", "off", "failed"])


class WithPostgres(unittest.TestCase):
    """PostgreSQL 실DB 에서 승인 기록이 실제로 사라지는지 (TEST_DB_HOST 가 있을 때만)."""

    def setUp(self):
        from shared.storage.testing import open_test_db
        self.db = open_test_db(app_name="ic26-test-account")
        if self.db is None:
            self.skipTest("TEST_DB_HOST 없음 (PostgreSQL 시험은 건너뜀)")

    def tearDown(self):
        if getattr(self, "db", None) is not None:
            self.db.close()

    def test_reset_removes_rows_of_this_owner_only(self):
        app, demo, review, _ = build(storage=self.db)
        client, other = TestClient(app), TestClient(app)
        signup(client, login="pg" + __import__("uuid").uuid4().hex[:10], stores=("store_ongi", "store_basak"))
        signup(other, login="pg" + __import__("uuid").uuid4().hex[:10], stores=("store_ongi",))
        me, them = visitor_of(client), visitor_of(other)
        seed(self.db, review, me, stores=("store_ongi", "store_basak"))
        seed(self.db, review, them, stores=("store_ongi",))
        data = client.post("/api/auth/reset", json={"scope": "account"}).json()
        self.assertTrue(data["complete"], data)
        self.assertEqual([s["approvals"] for s in data["stores"]], [2, 2])
        self.assertEqual(self.db.approvals.list("store_ongi", me), [])
        self.assertEqual(self.db.approvals.list("store_basak", me), [])
        self.assertEqual(len(self.db.approvals.list("store_ongi", them)), 2)


# ── 회원 탈퇴 ───────────────────────────────────────────────────────
class Withdraw(unittest.TestCase):
    def setUp(self):
        self.app, self.demo, self.review, self.mkt = build()
        self.client = TestClient(self.app)
        self.assertEqual(signup(self.client, stores=("store_ongi", "store_basak")).status_code, 201)
        self.me = visitor_of(self.client)
        other = TestClient(self.app)
        signup(other, login="owner02", stores=STORES)
        self.other = visitor_of(other)
        guest = TestClient(self.app)
        guest.get("/api/auth/me")
        self.guest = guest.cookies["visitor_id"]
        for v in (self.me, self.other, self.guest):
            seed(self.demo.storage, self.review, v)          # 가지지 않은 몽글카페에도 내 기록이 있다고 둠 (모두 지워야 함)

    def test_guest_gets_401(self):
        guest = TestClient(self.app)
        res = guest.post("/api/auth/withdraw", json={"password": "pass-word-1"})
        self.assertEqual((res.status_code, res.json()["error"]["state"]), (401, "login_needed"))
        self.assertEqual(res.headers["cache-control"], "no-store")
        self.assertEqual(self.review.deletes(), [])

    def test_wrong_password_keeps_everything_and_counts_as_a_login_failure(self):
        for body in ({"password": "wrong-pass"}, {}, None):
            res = self.client.post("/api/auth/withdraw", json=body)
            self.assertEqual((res.status_code, res.json()["error"]["state"]), (401, "bad_password"))
            self.assertNotIn("pass-word-1", res.text)
        self.assertEqual(self.review.deletes(), [])
        self.assertEqual(len(self.demo.storage.approvals.list("store_ongi", self.me)), 2)
        self.assertTrue(self.client.get("/api/auth/me").json()["authenticated"])
        bad = self.client.post("/api/auth/withdraw", json={"password": 123})
        self.assertEqual((bad.status_code, bad.json()["error"]["state"]), (422, "invalid"))

    def test_too_many_wrong_passwords_is_429_and_also_blocks_login(self):
        for _ in range(10):
            self.assertEqual(self.client.post("/api/auth/withdraw", json={"password": "wrong-pass"}).status_code, 401)
        res = self.client.post("/api/auth/withdraw", json={"password": "pass-word-1"})
        self.assertEqual((res.status_code, res.json()["error"]["state"]), (429, "too_many"))
        login = TestClient(self.app).post("/api/auth/login", json={"login_id": "owner01", "password": "pass-word-1"})
        self.assertEqual(login.status_code, 429)                                      # 같은 아이디 키
        self.assertTrue(self.client.get("/api/auth/me").json()["authenticated"])

    def test_records_left_keeps_the_account_and_a_retry_finishes(self):
        self.review.fail_stores = {"store_mongle"}
        res = self.client.post("/api/auth/withdraw", json={"password": "pass-word-1"})
        self.assertEqual((res.status_code, res.json()["error"]["state"]), (503, "records_left"))
        self.assertTrue(self.client.get("/api/auth/me").json()["authenticated"])          # 계정·세션 그대로
        self.assertIsNotNone(self.demo.storage.users.by_login("owner01"))
        self.assertEqual(self.review.pasted[("store_mongle", self.me)], 2)
        self.assertEqual(self.review.pasted.get(("store_ongi", self.me)), None)            # 지울 수 있던 것은 지워짐
        self.review.fail_stores = set()
        res = self.client.post("/api/auth/withdraw", json={"password": "pass-word-1"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertNotIn(("store_mongle", self.me), self.review.pasted)

    def test_success_erases_every_store_deletes_the_account_and_ends_other_sessions(self):
        laptop = TestClient(self.app)
        self.assertEqual(laptop.post("/api/auth/login", json={"login_id": "owner01", "password": "pass-word-1"}).status_code, 200)
        self.assertTrue(laptop.get("/api/auth/me").json()["authenticated"])
        res = self.client.post("/api/auth/withdraw", json={"password": "pass-word-1"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.headers["cache-control"], "no-store")
        data = res.json()
        self.assertTrue(data.pop("withdrawn"))
        self.assertEqual(data, self.client.get("/api/auth/me").json())                   # 게스트 신원 모양 그대로
        self.assertFalse(data["authenticated"])
        self.assertTrue(any(v.startswith(f"{SESSION_COOKIE}=") and "Path=/" in v and
                            ("Max-Age=0" in v or "1970" in v) for v in res.headers.get_list("set-cookie")))
        self.assertEqual(market_cookies_expired(res), {"/api/assistant", "/api/market"})
        self.assertFalse(laptop.get("/api/auth/me").json()["authenticated"])            # 다른 기기의 세션도 끊김
        # 가게 세 곳 모두 (가지지 않은 몽글카페 포함) 내 기록만 지워짐
        for s in STORES:
            self.assertEqual(self.demo.storage.approvals.list(s, self.me), [])
            self.assertNotIn((s, self.me), self.review.pasted)
            for v in (self.other, self.guest):
                self.assertEqual(len(self.demo.storage.approvals.list(s, v)), 2)
                self.assertEqual(self.review.pasted[(s, v)], 2)
        self.assertEqual({(p["store_id"], p["visitor_id"], p["forget_labels"]) for p in self.review.deletes()},
                         {(s, self.me, "true") for s in STORES})
        self.assertEqual({(r["params"]["store"], r["params"]["visitor_id"]) for r in self.mkt.requests},
                         {(s, self.me) for s in STORES})
        # 탈퇴한 아이디로는 로그인 안 됨, 같은 아이디로 새로 가입은 됨 (빈 계정)
        again = TestClient(self.app)
        login = again.post("/api/auth/login", json={"login_id": "owner01", "password": "pass-word-1"})
        self.assertEqual((login.status_code, login.json()["error"]["state"]), (401, "bad_login"))
        self.assertEqual(signup(again, stores=("store_mongle",)).status_code, 201)
        self.assertNotEqual(visitor_of(again), self.me)
        self.assertEqual(again.get("/api/approvals").json()["items"], [])

    def test_account_delete_failure_is_503_down_not_500(self):
        with mock.patch.object(self.demo.storage.users, "delete", side_effect=StorageError("DB 에 닿지 못함")):
            res = self.client.post("/api/auth/withdraw", json={"password": "pass-word-1"})
        self.assertEqual((res.status_code, res.json()["error"]["state"]), (503, "down"))
        self.assertTrue(self.client.get("/api/auth/me").json()["authenticated"])


class WithdrawDemo(unittest.TestCase):
    def test_demo_owner_withdraws_without_a_password_and_comes_back_empty(self):
        app, demo, review, _ = build()
        a, b = TestClient(app), TestClient(app)
        for c in (a, b):
            c.get("/api/auth/me")
            c.post("/api/auth/demo-login")
        va, vb = visitor_of(a), visitor_of(b)
        seed(demo.storage, review, va)
        seed(demo.storage, review, vb)
        res = a.post("/api/auth/withdraw")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["withdrawn"])
        self.assertIsNone(demo.storage.users.get(va[2:]))
        for s in STORES:
            self.assertEqual(demo.storage.approvals.list(s, va), [])
            self.assertEqual(len(demo.storage.approvals.list(s, vb)), 2)                 # 다른 브라우저의 시연 사장님은 그대로
        self.assertEqual(a.post("/api/auth/demo-login").status_code, 200)                  # 다시 누르면 빈 계정으로 새로
        self.assertEqual(visitor_of(a), va)
        self.assertEqual(a.get("/api/approvals").json()["items"], [])
        self.assertTrue(b.get("/api/auth/me").json()["authenticated"])


class WithdrawWithPostgres(unittest.TestCase):
    """PostgreSQL 실DB 에서 계정·가진 가게·세션·승인 기록이 실제로 사라지는지 (TEST_DB_HOST 가 있을 때만)."""

    def setUp(self):
        from shared.storage.testing import open_test_db
        self.db = open_test_db(app_name="ic26-test-withdraw")
        if self.db is None:
            self.skipTest("TEST_DB_HOST 없음 (PostgreSQL 시험은 건너뜀)")

    def tearDown(self):
        if getattr(self, "db", None) is not None:
            self.db.close()

    def test_rows_are_gone_and_the_login_can_be_reused(self):
        from web.auth import token_hash
        app, demo, review, _ = build(storage=self.db)
        login = "pg" + __import__("uuid").uuid4().hex[:10]
        phone, laptop, other = TestClient(app), TestClient(app), TestClient(app)
        signup(phone, login=login, stores=("store_ongi", "store_basak"))
        laptop.post("/api/auth/login", json={"login_id": login, "password": "pass-word-1"})
        signup(other, login="pg" + __import__("uuid").uuid4().hex[:10], stores=("store_ongi",))
        me, them = visitor_of(phone), visitor_of(other)
        user_id = me[2:]
        hashes = [token_hash(c.cookies[SESSION_COOKIE]) for c in (phone, laptop)]
        seed(self.db, review, me)
        seed(self.db, review, them, stores=("store_ongi",))
        res = phone.post("/api/auth/withdraw", json={"password": "pass-word-1"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIsNone(self.db.users.get(user_id))
        self.assertIsNone(self.db.users.by_login(login))
        self.assertEqual(self.db.users.stores(user_id), [])
        self.assertEqual([self.db.auth_sessions.get(h) for h in hashes], [None, None])
        for s in STORES:
            self.assertEqual(self.db.approvals.list(s, me), [])
        self.assertEqual(len(self.db.approvals.list("store_ongi", them)), 2)
        self.assertFalse(laptop.get("/api/auth/me").json()["authenticated"])
        self.assertEqual(signup(TestClient(app), login=login).status_code, 201)
