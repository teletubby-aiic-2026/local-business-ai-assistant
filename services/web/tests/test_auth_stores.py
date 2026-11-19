"""로그인과 사장님 가게 여러 개 (5차 회의 11/18). CLOVA·네트워크는 부르지 않는다.

- 로그인하지 않으면 예전과 똑같다 (가게 store_ongi, 쿠키 visitor_id).
- 로그인하면 방문자 id 가 'u-<user_id>', 가게는 세션이 고른 가게. 그 값이 Demo·고객응대·맞춤 마케팅에 똑같이 간다.
- 세션 쿠키 ic26_session: HttpOnly, SameSite=Lax, Secure 는 https 일 때만.

실행 (services/web 에서):  env -u APP_MODE PYTHONPATH=../.. python -m pytest -q tests/test_auth_stores.py
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from shared import store_profiles
from shared.storage import MemoryStore, is_valid_visitor_id
from tests.test_web import FakeSource, settings
from web import auth as auth_mod
from web.assistant_proxy import STORE_DEFAULTS, AssistantProxy
from web.auth import SESSION_COOKIE, AuthService, hash_password, verify_password, visitor_for
from web.care_proxy import CareProxy
from web.demo import Demo
from web.main import create_app
from web.marketing_proxy import MarketingProxy

REPO = Path(__file__).resolve().parents[3]
MARKET_APP = REPO / "services" / "market-analysis" / "app"


class RecordingSource(FakeSource):
    """가게 id 를 적어 두는 리뷰 분석 서비스 대신 (내용은 온기한식 시험 자료 그대로)."""

    def __init__(self):
        super().__init__()
        self.calls: list[tuple[str, str]] = []

    def store(self, store_id):
        self.calls.append(("store", store_id))
        if store_id in ("store_basak", "store_mongle"):     # 그 가게의 합성 store.json (리뷰 분석 서비스가 주는 것과 같음)
            return json.loads((REPO / "services" / "review-insight" / "data" / "synthetic" / store_id / "store.json")
                              .read_text(encoding="utf-8"))
        return super().store(store_id)

    def reviews(self, store_id):
        self.calls.append(("reviews", store_id)); return super().reviews(store_id)

    def insight(self, store_id):
        self.calls.append(("insight", store_id)); return super().insight(store_id)


class Recorder:
    """가짜 아래 서비스 (고객응대·맞춤 마케팅). 받은 쿼리·본문을 적고 200 을 준다."""

    def __init__(self, body: dict):
        self.body, self.requests = body, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        rec = {"path": request.url.path, "params": dict(request.url.params), "json": None}
        if request.content:
            try:
                rec["json"] = json.loads(request.content)
            except ValueError:
                pass
        self.requests.append(rec)
        return httpx.Response(200, json=self.body)


def build(*, demo_enabled=True, storage=None):
    tmp = Path(tempfile.mkdtemp())
    storage = storage or MemoryStore()
    source = RecordingSource()
    care_fake = Recorder({"items": []})
    mkt_fake = Recorder({"state": "ok", "service": "marketing-survey"})
    care = CareProxy("http://review.test", transport=httpx.MockTransport(care_fake))
    marketing = MarketingProxy("http://marketing.test", transport=httpx.MockTransport(mkt_fake))
    demo = Demo(settings(tmp), source=source, storage=storage)
    app = create_app(demo, assistant=AssistantProxy(None), care=care, marketing=marketing,
                     auth=AuthService(storage, demo_enabled=demo_enabled))
    return TestClient(app), demo, source, care_fake, mkt_fake


def signup(client, login="owner01", stores=("store_ongi", "store_basak"), **more):
    return client.post("/api/auth/signup", json={"login_id": login, "password": "pass-word-1", "display_name": "김사장",
                                                 "stores": list(stores), **more})


class Passwords(unittest.TestCase):
    def test_scrypt_hash_verifies_and_rejects(self):
        stored = hash_password("비밀번호123")
        self.assertTrue(stored.startswith("scrypt$16384$8$1$"))
        self.assertTrue(verify_password("비밀번호123", stored))
        self.assertFalse(verify_password("비밀번호124", stored))
        self.assertNotEqual(stored, hash_password("비밀번호123"))          # 소금이 매번 다름
        for bad in ("!", "", None, "scrypt$x", "md5$1$2$3$4$5", stored[:-3]):
            self.assertFalse(verify_password("비밀번호123", bad))

    def test_user_visitor_ids_fit_every_service_rule(self):
        for user_id in ("0123456789abcdef", "demo-0123456789ab"):
            v = visitor_for(user_id)
            self.assertTrue(v.startswith("u-") and "_" not in v and is_valid_visitor_id(v) and len(v) <= 64)
        with self.assertRaises(ValueError):
            visitor_for("x" * 70)


class GuestIsUnchanged(unittest.TestCase):
    def setUp(self):
        self.client, self.demo, self.source, self.care, self.mkt = build()

    def test_me_for_a_guest(self):
        data = self.client.get("/api/auth/me").json()
        self.assertEqual((data["authenticated"], data["user"], data["store_id"]), (False, None, "store_ongi"))
        self.assertEqual([s["store_id"] for s in data["stores"]], ["store_ongi"])
        self.assertTrue(data["demo_login"])

    def test_guest_requests_use_the_default_store_and_the_cookie_visitor(self):
        self.client.get("/api/briefing")
        visitor = self.client.cookies["visitor_id"]
        self.assertEqual({s for _, s in self.source.calls}, {"store_ongi"})
        self.client.get("/api/care/status")
        self.client.get("/api/care/report/daily")
        self.assertEqual(self.care.requests[-1]["params"]["store_id"], "store_ongi")
        self.assertEqual(self.care.requests[-1]["params"]["visitor_id"], visitor)
        self.assertNotIn(SESSION_COOKIE, self.client.cookies)

    def test_guest_cannot_switch_store(self):
        res = self.client.post("/api/auth/store", json={"store_id": "store_basak"})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me").json()["store_id"], "store_ongi")


class LoginFlow(unittest.TestCase):
    def setUp(self):
        self.client, self.demo, self.source, self.care, self.mkt = build()

    def test_signup_logs_in_with_a_safe_cookie(self):
        res = signup(self.client)
        self.assertEqual(res.status_code, 201, res.text)
        data = res.json()
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["user"]["display_name"], "김사장")
        self.assertEqual([s["store_id"] for s in data["stores"]], ["store_ongi", "store_basak"])
        cookie = next(h for h in res.headers.get_list("set-cookie") if h.startswith(SESSION_COOKIE + "="))
        low = cookie.lower()
        self.assertIn("httponly", low)
        self.assertIn("samesite=lax", low)
        self.assertNotIn("secure", low)                       # 지금 공개 주소는 http: Secure 면 로그인이 풀린다
        self.assertNotIn("password", json.dumps(data))
        self.assertTrue(self.client.get("/api/auth/me").json()["authenticated"])

    def test_cookie_is_secure_behind_https(self):
        res = self.client.post(
            "/api/auth/signup", headers={"x-forwarded-proto": "https"},
            json={"login_id": "owner02", "password": "pass-word-1", "display_name": "박사장"})
        cookie = next(h for h in res.headers.get_list("set-cookie") if h.startswith(SESSION_COOKIE + "="))
        self.assertIn("secure", cookie.lower())

    def test_login_logout_and_wrong_password(self):
        signup(self.client)
        self.client.post("/api/auth/logout")
        self.assertFalse(self.client.get("/api/auth/me").json()["authenticated"])
        bad = self.client.post("/api/auth/login", json={"login_id": "owner01", "password": "wrong-pass"})
        nobody = self.client.post("/api/auth/login", json={"login_id": "nobody", "password": "wrong-pass"})
        self.assertEqual((bad.status_code, nobody.status_code), (401, 401))
        self.assertEqual(bad.json()["error"]["message"], nobody.json()["error"]["message"])   # 아이디가 있는지 알려 주지 않음
        ok = self.client.post("/api/auth/login", json={"login_id": "OWNER01", "password": "pass-word-1"})
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()["user"]["login_id"], "owner01")

    def test_logout_clears_the_session_and_the_market_cookies(self):
        signup(self.client)
        res = self.client.post("/api/auth/logout")
        headers = " ".join(res.headers.get_list("set-cookie"))
        self.assertIn(f'{SESSION_COOKIE}=""', headers)
        for path in ("/api/assistant", "/api/market"):
            self.assertIn(f"Path={path}", headers)
        self.assertEqual(res.json()["store_id"], "store_ongi")

    def test_signup_validation_and_duplicates(self):
        self.assertEqual(signup(self.client).status_code, 201)
        self.assertEqual(signup(TestClient(self.client.app)).status_code, 409)       # 같은 아이디
        cases = [{"login_id": "ab"}, {"login_id": "한글아이디"}, {"password": "short"},
                 {"display_name": "x" * 25}, {"stores": ["store_unknown"]}, {"stores": []}]
        for case in cases:
            body = {"login_id": "owner99", "password": "pass-word-1", "display_name": "사장", "stores": ["store_ongi"], **case}
            res = TestClient(self.client.app).post("/api/auth/signup", json=body)
            self.assertEqual(res.status_code, 422, (case, res.text))

    def test_too_many_failures_are_blocked(self):
        signup(self.client)
        other = TestClient(self.client.app)
        codes = [other.post("/api/auth/login", json={"login_id": "owner01", "password": "nope-nope"}).status_code
                 for _ in range(auth_mod.FAIL_LIMIT + 1)]
        self.assertEqual(codes[:auth_mod.FAIL_LIMIT], [401] * auth_mod.FAIL_LIMIT)
        self.assertEqual(codes[-1], 429)
        # 맞는 비밀번호도 잠시 막힌다 (같은 아이디·같은 주소)
        self.assertEqual(other.post("/api/auth/login", json={"login_id": "owner01", "password": "pass-word-1"}).status_code, 429)

    def test_a_forged_or_expired_cookie_is_a_guest(self):
        self.client.cookies.set(SESSION_COOKIE, "x" * 43)
        self.assertFalse(self.client.get("/api/auth/me").json()["authenticated"])
        self.client.cookies.set(SESSION_COOKIE, "bad cookie;")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)


def _request(peer, forwarded=None, visitor="visitor-a"):
    """auth._client 에 넘길 요청 (바로 앞 주소·X-Forwarded-For·방문자 쿠키만)."""
    from starlette.requests import Request
    headers = [(b"x-forwarded-for", forwarded.encode("ascii"))] if forwarded is not None else []
    request = Request({"type": "http", "method": "POST", "path": "/api/auth/login", "headers": headers,
                       "client": (peer, 50000)})
    request.state.guest_visitor_id = visitor
    return request


class BehindProxies(unittest.TestCase):
    """실서버: 공개 ALB → Nginx → 내부 ALB → WAS. WAS 가 보는 주소는 늘 내부 ALB 의 사설 주소다 (11/19 보완)."""

    def setUp(self):
        self.client, *_ = build()

    def at(self, peer, forwarded=None):
        headers = {"X-Forwarded-For": forwarded} if forwarded else None
        return TestClient(self.client.app, client=(peer, 50000), headers=headers)

    def fail_until_blocked(self, client, login="stranger01"):
        codes = [client.post("/api/auth/login", json={"login_id": login, "password": "nope-nope"}).status_code
                 for _ in range(auth_mod.FAIL_LIMIT + 1)]
        self.assertEqual(codes, [401] * auth_mod.FAIL_LIMIT + [429])

    def test_rightmost_public_address_is_the_client(self):
        self.assertEqual(auth_mod._client(_request("10.0.1.9", "1.2.3.4, 203.0.113.9, 10.0.1.5")), "203.0.113.9")
        self.assertEqual(auth_mod._client(_request("127.0.0.1", "198.51.100.20")), "198.51.100.20")
        self.assertEqual(auth_mod._client(_request("::ffff:10.0.2.6", "198.51.100.20")), "198.51.100.20")
        self.assertEqual(auth_mod._client(_request("testclient", "198.51.100.20")), "198.51.100.20")

    def test_forwarded_header_from_a_public_peer_is_ignored(self):
        self.assertEqual(auth_mod._client(_request("198.51.100.7", "1.2.3.4")), "198.51.100.7")
        self.assertEqual(auth_mod._client(_request("198.51.100.7")), "198.51.100.7")

    def test_unknown_public_address_falls_back_to_the_visitor(self):
        self.assertEqual(auth_mod._client(_request("10.0.2.6")), "10.0.2.6:v:visitor-a")
        self.assertEqual(auth_mod._client(_request("10.0.2.6", "10.0.0.3, 192.168.1.4")), "10.0.2.6:v:visitor-a")
        # 주소가 아닌 값을 만나면 그 왼쪽(손님이 지어낼 수 있는 쪽)은 믿지 않는다
        self.assertEqual(auth_mod._client(_request("10.0.2.6", "1.2.3.4, nonsense, 10.0.1.5")), "10.0.2.6:v:visitor-a")
        self.assertEqual(auth_mod._client(_request("10.0.2.6", visitor="visitor-b")), "10.0.2.6:v:visitor-b")

    def test_one_visitor_failing_behind_a_private_proxy_does_not_lock_the_others(self):
        signup(TestClient(self.client.app), login="owner02")
        a, b = self.at("10.0.2.6"), self.at("10.0.2.6")
        a.get("/api/auth/me"), b.get("/api/auth/me")                       # 방문자 쿠키를 받아 둠
        self.assertNotEqual(a.cookies.get("visitor_id"), b.cookies.get("visitor_id"))
        self.fail_until_blocked(a)
        # A 는 다른 아이디로도 막힌다 (주소 키가 A 의 방문자와 묶였으므로)
        self.assertEqual(a.post("/api/auth/login", json={"login_id": "owner02", "password": "pass-word-1"}).status_code, 429)
        # 같은 사설 주소 뒤의 B 는 그대로 로그인된다
        res = b.post("/api/auth/login", json={"login_id": "owner02", "password": "pass-word-1"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["authenticated"])

    def test_forwarded_public_address_is_counted_per_person(self):
        signup(TestClient(self.client.app), login="owner03")
        a = self.at("10.0.2.6", "203.0.113.9, 10.0.1.5")
        self.fail_until_blocked(a)
        # 같은 공인 주소면 방문자 쿠키를 바꿔도 막힌다 (쿠키를 지워 피해 갈 수 없게)
        same_place = self.at("10.0.2.6", "203.0.113.9, 10.0.1.5")
        self.assertEqual(same_place.post("/api/auth/login", json={"login_id": "owner03", "password": "pass-word-1"}).status_code, 429)
        # 다른 공인 주소의 손님은 같은 내부 ALB 를 거쳐도 로그인된다
        other = self.at("10.0.2.6", "198.51.100.20, 10.0.1.5")
        self.assertEqual(other.post("/api/auth/login", json={"login_id": "owner03", "password": "pass-word-1"}).status_code, 200)

    def test_id_limit_still_holds_behind_a_proxy(self):
        signup(TestClient(self.client.app), login="owner04")
        self.fail_until_blocked(self.at("10.0.2.6"), login="owner04")
        # 다른 방문자라도 같은 아이디는 잠시 막힌다 (아이디마다 10분에 10번은 그대로)
        self.assertEqual(self.at("10.0.2.6").post("/api/auth/login", json={"login_id": "owner04", "password": "pass-word-1"}).status_code, 429)


class DemoPrefix(unittest.TestCase):
    """'demo-' 아이디는 시연 계정 몫 (11/19 보완)."""

    def setUp(self):
        self.client, self.demo, *_ = build()

    def test_signup_refuses_demo_prefix(self):
        for login in ("demo-abc", "DEMO-owner", "demo-0123456789ab"):
            res = signup(TestClient(self.client.app), login=login)
            self.assertEqual(res.status_code, 422, (login, res.text))
            self.assertIn("시연 계정", res.json()["error"]["message"])
        self.assertEqual(signup(TestClient(self.client.app), login="demoowner").status_code, 201)   # 'demo-' 만 막음

    def test_demo_login_is_a_clear_error_if_its_id_was_taken_before(self):
        import hashlib
        guest = TestClient(self.client.app)
        guest.get("/api/auth/me")
        visitor = guest.cookies.get("visitor_id")
        demo_id = auth_mod.DEMO_PREFIX + hashlib.sha256(f"ic26-demo:{visitor}".encode("utf-8")).hexdigest()[:12]
        # 예약 전에 누군가 그 아이디로 가입해 둔 경우 (저장소에 바로 넣음)
        self.demo.storage.users.create("someone0001", demo_id, hash_password("pass-word-1"), "먼저 가입", ["store_ongi"])
        res = guest.post("/api/auth/demo-login")
        self.assertEqual(res.status_code, 409, res.text)
        self.assertIn("시연 계정", res.json()["error"]["message"])
        self.assertFalse(guest.get("/api/auth/me").json()["authenticated"])


class StoresPerOwner(unittest.TestCase):
    def setUp(self):
        self.client, self.demo, self.source, self.care, self.mkt = build()

    def test_demo_login_has_three_stores_and_switches(self):
        data = self.client.post("/api/auth/demo-login").json()
        self.assertTrue(data["authenticated"] and data["user"]["demo"])
        self.assertEqual([s["store_id"] for s in data["stores"]], list(store_profiles.STORE_IDS))
        self.assertEqual([s["name"] for s in data["stores"]], ["온기한식", "바삭치킨", "몽글카페"])
        self.assertEqual(data["store_id"], "store_ongi")
        for sid in ("store_basak", "store_mongle", "store_ongi"):
            res = self.client.post("/api/auth/store", json={"store_id": sid})
            self.assertEqual((res.status_code, res.json()["store_id"]), (200, sid), res.text)
            self.assertEqual(self.client.get("/api/health").json()["store_id"], sid)

    def test_demo_login_is_per_browser(self):
        a, b = TestClient(self.client.app), TestClient(self.client.app)
        a.get("/api/health"); b.get("/api/health")
        ua = a.post("/api/auth/demo-login").json()["user"]["user_id"]
        ub = b.post("/api/auth/demo-login").json()["user"]["user_id"]
        self.assertNotEqual(ua, ub)
        self.assertEqual(a.post("/api/auth/demo-login").json()["user"]["user_id"], ua)   # 같은 브라우저는 같은 사장님

    def test_demo_login_can_be_turned_off(self):
        client = build(demo_enabled=False)[0]
        self.assertEqual(client.post("/api/auth/demo-login").status_code, 403)
        self.assertFalse(client.get("/api/auth/me").json()["demo_login"])

    def test_only_owned_stores_can_be_picked(self):
        signup(self.client, stores=("store_mongle",))
        self.assertEqual(self.client.get("/api/auth/me").json()["store_id"], "store_mongle")
        self.assertEqual(self.client.post("/api/auth/store", json={"store_id": "store_basak"}).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/store", json={"store_id": "store_unknown"}).status_code, 403)

    def test_every_downstream_gets_the_active_store_and_the_user_visitor(self):
        data = self.client.post("/api/auth/demo-login").json()
        user_visitor = "u-" + data["user"]["user_id"]
        self.client.post("/api/auth/store", json={"store_id": "store_basak"})
        self.source.calls.clear()
        self.client.get("/api/briefing")
        self.assertEqual({s for _, s in self.source.calls}, {"store_basak"})
        self.client.get("/api/care/report/daily?store_id=store_ongi&visitor_id=someone")
        self.assertEqual((self.care.requests[-1]["params"]["store_id"], self.care.requests[-1]["params"]["visitor_id"]),
                         ("store_basak", user_visitor))
        self.client.get("/api/marketing-survey/meta?store=store_ongi")
        self.assertEqual((self.mkt.requests[-1]["params"]["store"], self.mkt.requests[-1]["params"]["visitor_id"]),
                         ("store_basak", user_visitor))

    def test_approvals_are_separate_per_user_store_and_guest(self):
        guest = TestClient(self.client.app)
        guest.post("/api/drafts/d_g/approve", json={"text": "손님 글", "original": "손님 글"})
        self.client.post("/api/auth/demo-login")
        self.client.post("/api/drafts/d_o/approve", json={"text": "온기 글", "original": "온기 글"})
        self.client.post("/api/auth/store", json={"store_id": "store_basak"})
        self.client.post("/api/drafts/d_b/approve", json={"text": "바삭 글", "original": "바삭 글"})
        shown = lambda c: [i["draft_id"] for i in c.get("/api/approvals").json()["items"]]
        self.assertEqual(shown(self.client), ["d_b"])
        self.client.post("/api/auth/store", json={"store_id": "store_ongi"})
        self.assertEqual(shown(self.client), ["d_o"])
        self.assertEqual(shown(guest), ["d_g"])
        self.client.post("/api/auth/logout")
        self.assertNotIn("d_o", shown(self.client))          # 로그아웃하면 게스트 기록만

    def test_marketing_approvals_go_to_the_active_store(self):
        self.client.post("/api/auth/demo-login")
        self.client.post("/api/auth/store", json={"store_id": "store_mongle"})
        self.mkt.body = {"follow_up": False}
        self.client.post("/api/marketing-survey/approve", json={"state": {}, "approval": {
            "draft_id": "r1-notice", "text": "고친 글", "original": "처음 글", "kind": "공지"}})
        visitor = "u-" + self.client.get("/api/auth/me").json()["user"]["user_id"]
        self.assertEqual([r["draft_id"] for r in self.demo.storage.approvals.list("store_mongle", visitor)], ["mkt-r1-notice"])
        self.assertEqual(self.demo.storage.approvals.list("store_ongi", visitor), [])


class WithPostgres(unittest.TestCase):
    """같은 흐름을 PostgreSQL 로 (TEST_DB_HOST 가 있을 때만). 서버 두 대 = 같은 DB 에 붙은 앱 둘: 한 대에서 로그인하면 다른 대도 안다."""

    def setUp(self):
        from shared.storage.testing import open_test_db
        self.dbs = [open_test_db(app_name="ic26-test-auth-a"), open_test_db(app_name="ic26-test-auth-b")]
        if self.dbs[0] is None:
            self.skipTest("TEST_DB_HOST 없음 (PostgreSQL 시험은 건너뜀)")

    def tearDown(self):
        for db in self.dbs:
            if db is not None:
                db.close()

    def test_login_on_one_server_is_seen_by_the_other(self):
        a, b = build(storage=self.dbs[0])[0], build(storage=self.dbs[1])[0]
        login = "pg" + __import__("uuid").uuid4().hex[:10]
        res = a.post("/api/auth/signup", json={"login_id": login, "password": "pass-word-1", "display_name": "정사장",
                                               "stores": ["store_mongle", "store_ongi"]})
        self.assertEqual(res.status_code, 201, res.text)
        b.cookies.set(SESSION_COOKIE, a.cookies[SESSION_COOKIE])
        me = b.get("/api/auth/me").json()
        self.assertEqual((me["authenticated"], me["store_id"]), (True, "store_mongle"))
        self.assertEqual(b.post("/api/auth/store", json={"store_id": "store_ongi"}).status_code, 200)
        self.assertEqual(a.get("/api/auth/me").json()["store_id"], "store_ongi")      # 세션은 DB 에 있다
        b.post("/api/auth/logout")
        self.assertFalse(a.get("/api/auth/me").json()["authenticated"])                # 한 대에서 로그아웃하면 둘 다


class StoreProfiles(unittest.TestCase):
    def test_codes_exist_in_the_market_service_tables(self):
        industries = {r["code"]: r["name"] for r in json.loads((MARKET_APP / "onboarding_industries.json").read_text(encoding="utf-8"))["industries"]}
        stations = json.loads((MARKET_APP / "onboarding_stations.json").read_text(encoding="utf-8"))
        station_ids = {r["id"]: r["name"] for r in (stations["stations"] if isinstance(stations, dict) else stations)}
        for sid in store_profiles.STORE_IDS:
            b = store_profiles.BUNDLES[sid]
            self.assertEqual(industries.get(b.industry_code), b.business_type_name, sid)
            self.assertEqual(station_ids.get(b.station_id), b.station_name, sid)
            d = STORE_DEFAULTS[sid]
            self.assertEqual((d.station_id, d.industry_code, d.area_code, d.period),
                             (b.station_id, b.industry_code, b.area_code, "20262"))
        self.assertEqual(STORE_DEFAULTS["store_basak"].industry_code, "CS100007")    # 치킨전문점
        self.assertEqual(STORE_DEFAULTS["store_mongle"].industry_code, "CS100010")   # 커피-음료

    def test_new_store_snapshots_are_real_and_reproducible(self):
        import subprocess
        import sys
        done = subprocess.run([sys.executable, str(REPO / "scripts" / "reproduce_store_snapshots.py")],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        for sid in ("store_basak", "store_mongle"):
            snaps = store_profiles.load_snapshots(sid)
            self.assertEqual(len(snaps), 1)
            s = snaps[0]
            self.assertFalse(s.note.startswith("개발용 가짜 값"))
            self.assertIn("data.seoul.go.kr", s.source)
            self.assertEqual((s.unit, s.basis_quarter, s.compared_with_quarter), ("%", "2026Q2", "2025Q2"))
            self.assertIn(store_profiles.BUNDLES[sid].business_type_name, s.metric_name)
            self.assertLess(s.value, -5)        # 카드 ⓑ 기준(-5%)보다 내려가 카드가 뜬다

    def test_menu_prices_and_c6_extras(self):
        self.assertEqual(store_profiles.c6_extras("store_ongi"), {})          # 온기한식은 예전과 같은 C6 기본값
        extras = store_profiles.c6_extras("store_basak")
        self.assertEqual(extras["tone"].store_id, "store_basak")
        self.assertTrue(all("바삭치킨" in r for r in extras["owner_replies"]))
        store = store_profiles.store_profile("store_mongle")
        self.assertEqual(set(store.menu), set(store.menu_prices))


class MockWritingForOtherStores(unittest.TestCase):
    """mock: 저장본(온기한식)이 없는 가게는 코드 틀 글이고, '확인 필요'로 보이게 그렇다고 적는다."""

    def test_basak_mock_drafts_are_marked_as_templates(self):
        client, demo, source, *_ = build()
        client.post("/api/auth/demo-login")
        client.post("/api/auth/store", json={"store_id": "store_basak"})
        cards = client.get("/api/cards").json()["cards"]
        for card in cards:
            res = client.post(f"/api/cards/{card['card']['card_id']}/run", json={})
            self.assertEqual(res.status_code, 200, res.text)
            drafts = res.json()["drafts"]
            self.assertTrue(drafts)
            for d in drafts:
                self.assertTrue(d["needs_input"], d)
                self.assertIn("실제 AI 결과 아님", d["needs_input"][0])
                self.assertNotIn("온기한식", d["text"])


if __name__ == "__main__":
    unittest.main()
