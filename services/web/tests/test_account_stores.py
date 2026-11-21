"""계정 안의 가게 (6차 회의 11/20): 가게 0곳 가입, 가게 등록·고치기·빼기·순서, 이름·비밀번호 바꾸기, 로그인 상태 헤더.
CLOVA·네트워크는 부르지 않는다.

- 로그인했는데 가게가 0곳이면 me 는 authenticated true·store_id null·stores []. 가게가 있어야 하는 API 는 409 no_store.
- X-IC26-Signed-In: 1 이 있는데 세션이 없으면 /api/auth/* 를 뺀 /api/* 는 401 login_needed. 헤더가 없으면 예전처럼 게스트.
- 예시 가게 세 곳·게스트의 예전 동작은 그대로 (test_auth_stores.py·test_account_data.py 가 같이 지킨다).

실행 (services/web 에서):  env -u APP_MODE PYTHONPATH=../..:. python -m pytest -q tests/test_account_stores.py
"""
from __future__ import annotations

import copy
import re
import tempfile
import unittest
import uuid
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from shared import store_profiles
from shared.storage import MemoryStore
from tests.test_account_data import FakeReview, Recorder, market_cookies_expired
from tests.test_auth_stores import RecordingSource, build, signup
from tests.test_web import fixture, settings
from web.assistant_proxy import AssistantProxy
from web.auth import SESSION_COOKIE, AuthService
from web.care_proxy import CareProxy
from web.demo import Demo
from web.main import create_app
from web.marketing_proxy import MarketingProxy
from web.sources import ReviewSource, SourceError

SIGNED = {"X-IC26-Signed-In": "1"}
STORE_NEEDED = ("/api/briefing", "/api/cards", "/api/insight", "/api/approvals", "/api/care/status",
                "/api/marketing-survey/meta", "/api/assistant/status")


def new_store(**more) -> dict:
    body = {"name": "  우리분식  ", "industry_code": "CS100002", "business_type_name": "분식전문점",
            "business_status": "operating", "channels": ["배달의민족", "쿠팡이츠", "배달의민족"],
            "location": {"kind": "address", "label": "서울 동작구 상도로 1", "road_address": "서울 동작구 상도로 1",
                         "latitude": 37.5, "longitude": 126.9, "district_name": "동작구"},
            "area": {"area_code": "3110836", "name": "상도역 5번", "period": "20262"},
            "menus": [{"name": "떡볶이", "price": 5000}, {"name": "순대", "price": 4500}, {"name": "떡볶이", "price": 5500}]}
    body.update(more)
    return body


def empty_owner(client, login="owner01"):
    res = signup(client, login=login, stores=())
    assert res.status_code == 201, res.text
    return res


class StoreAwareSource(RecordingSource):
    """예시 가게만 아는 리뷰 분석 서비스 대신 (등록 가게는 실제 서비스처럼 404). insight 를 가게마다 바꿀 수 있다."""

    def __init__(self):
        super().__init__()
        self.insights: dict[str, dict] = {}
        self.down = False

    def _known(self, store_id):
        if self.down:
            raise SourceError("리뷰 분석 서비스에 연결하지 못했습니다: ConnectError")
        if store_id not in store_profiles.STORE_IDS:
            raise SourceError(f"리뷰 분석 서비스 오류 404: 없는 가게입니다: {store_id}")

    def store(self, store_id):
        self._known(store_id); return super().store(store_id)

    def reviews(self, store_id):
        self._known(store_id); return super().reviews(store_id)

    def insight(self, store_id):
        self._known(store_id)
        return self.insights.get(store_id) or super().insight(store_id)


def build_aware(storage=None):
    tmp = Path(tempfile.mkdtemp())
    storage = storage or MemoryStore()
    source = StoreAwareSource()
    care = CareProxy("http://review.test", transport=httpx.MockTransport(Recorder({"items": []})))
    marketing = MarketingProxy("http://marketing.test", transport=httpx.MockTransport(Recorder({"state": "ok"})))
    demo = Demo(settings(tmp), source=source, storage=storage)
    app = create_app(demo, assistant=AssistantProxy(None), care=care, marketing=marketing, auth=AuthService(storage))
    return TestClient(app), demo, source


class NoStoreOwner(unittest.TestCase):
    def setUp(self):
        self.client, self.demo, self.source, *_ = build()

    def test_signup_with_no_store_is_signed_in_without_a_store(self):
        data = empty_owner(self.client).json()
        self.assertEqual((data["authenticated"], data["store_id"], data["stores"]), (True, None, []))
        self.assertTrue(re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["user"]["created_at"]))
        me = self.client.get("/api/auth/me").json()
        self.assertEqual((me["authenticated"], me["store_id"], me["stores"]), (True, None, []))

    def test_store_data_apis_are_409_and_never_show_the_default_store(self):
        empty_owner(self.client)
        self.source.calls.clear()
        for path in STORE_NEEDED:
            for headers in ({}, SIGNED):
                res = self.client.get(path, headers=headers)
                self.assertEqual((res.status_code, res.json()["error"]["state"]), (409, "no_store"), path)
        res = self.client.post("/api/cards/card_a/run", json={})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(self.client.post("/api/reviews", json={"text": "맛있어요"}).status_code, 409)
        self.assertEqual(self.source.calls, [])                        # 온기한식 자료를 읽지도 않았다

    def test_store_free_apis_still_work(self):
        empty_owner(self.client)
        health = self.client.get("/api/health", headers=SIGNED)
        self.assertEqual((health.status_code, health.json()["store_id"]), (200, None))
        self.assertEqual(self.client.get("/api/account/stores").json(), {"stores": []})
        status = self.client.get("/api/market/status")
        self.assertEqual(status.status_code, 200)
        self.assertIsNone(status.json()["store"])                     # 기본 가게(온기한식) 이름을 보이지 않음
        self.assertEqual(self.client.post("/api/auth/reset", json={"scope": "store"}).status_code, 409)

    def test_login_without_a_store_and_session_only_cookie(self):
        empty_owner(self.client)
        self.client.post("/api/auth/logout")
        res = self.client.post("/api/auth/login", json={"login_id": "owner01", "password": "pass-word-1", "keep": False})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual((res.json()["authenticated"], res.json()["store_id"]), (True, None))
        cookie = next(h for h in res.headers.get_list("set-cookie") if h.startswith(SESSION_COOKIE + "="))
        self.assertNotIn("max-age", cookie.lower())
        self.assertNotIn("expires", cookie.lower())
        kept = self.client.post("/api/auth/login", json={"login_id": "owner01", "password": "pass-word-1"})
        cookie = next(h for h in kept.headers.get_list("set-cookie") if h.startswith(SESSION_COOKIE + "="))
        self.assertIn("max-age=604800", cookie.lower())                # 기본은 지금처럼 7일


class SignedInHeader(unittest.TestCase):
    def setUp(self):
        self.client, *_ = build()

    def test_header_without_a_session_is_401_but_auth_paths_are_open(self):
        for path in ("/api/briefing", "/api/health", "/api/account/stores", "/api/market/status"):
            res = self.client.get(path, headers=SIGNED)
            self.assertEqual((res.status_code, res.json()["error"]["state"]), (401, "login_needed"), path)
        me = self.client.get("/api/auth/me", headers=SIGNED)
        self.assertEqual((me.status_code, me.json()["authenticated"]), (200, False))

    def test_no_header_keeps_the_guest_behaviour(self):
        self.assertEqual(self.client.get("/api/briefing").status_code, 200)
        self.assertEqual(self.client.get("/api/health").json()["store_id"], "store_ongi")

    def test_expired_session_with_header_is_401(self):
        signup(self.client)
        self.assertEqual(self.client.get("/api/briefing", headers=SIGNED).status_code, 200)
        self.client.cookies.set(SESSION_COOKIE, "x" * 43)               # 끝난(없는) 세션
        res = self.client.get("/api/briefing", headers=SIGNED)
        self.assertEqual((res.status_code, res.json()["error"]["state"]), (401, "login_needed"))

    def test_account_needs_login(self):
        for method, path in (("GET", "/api/account/stores"), ("POST", "/api/account/stores"),
                             ("PUT", "/api/account/stores/order"), ("PATCH", "/api/account/profile"),
                             ("POST", "/api/account/password"), ("GET", "/api/account/stores/store_ongi/summary"),
                             ("DELETE", "/api/account/stores/store_ongi")):
            res = self.client.request(method, path, json={})
            self.assertEqual((res.status_code, res.json()["error"]["state"]), (401, "login_needed"), path)


class RegisterStores(unittest.TestCase):
    def setUp(self):
        self.client, self.demo, self.source, *_ = build()
        empty_owner(self.client)

    def register(self, client=None, **more):
        res = (client or self.client).post("/api/account/stores", json=new_store(**more))
        self.assertEqual(res.status_code, 201, res.text)
        return res.json()["store"]

    def test_register_list_me_and_switch(self):
        store = self.register()
        self.assertTrue(re.fullmatch(r"store_[0-9a-f]{12}", store["store_id"]))
        self.assertEqual(store["name"], "우리분식")                                   # 앞뒤 공백 정리
        self.assertEqual(store["channels"], ["배달의민족", "쿠팡이츠"])
        self.assertEqual(store["menus"], [{"name": "순대", "price": 4500}, {"name": "떡볶이", "price": 5500}])
        self.assertEqual((store["sample"], store["menu_count"], store["last_opened"]), (False, 2, False))
        self.assertEqual((store["area_name"], store["station_name"]), ("상도역 5번", None))
        # 가게 0곳이던 사장님: 세션에 고른 가게가 없으니 resolve 의 예전 규칙대로 목록의 첫 가게를 본다
        me = self.client.get("/api/auth/me").json()
        self.assertEqual(me["store_id"], store["store_id"])
        self.assertEqual([(s["store_id"], s["sample"]) for s in me["stores"]], [(store["store_id"], False)])
        # 이미 보던 가게가 있으면 등록해도 그대로다 (세션의 지금 가게는 바꾸지 않음)
        owner = TestClient(self.client.app)
        signup(owner, login="owner05", stores=("store_mongle",))
        made = owner.post("/api/account/stores", json=new_store()).json()["store"]
        me = owner.get("/api/auth/me").json()
        self.assertEqual((me["store_id"], [s["store_id"] for s in me["stores"]]), ("store_mongle", ["store_mongle", made["store_id"]]))
        res = self.client.post("/api/auth/store", json={"store_id": store["store_id"]})
        self.assertEqual((res.status_code, res.json()["store_id"]), (200, store["store_id"]), res.text)
        listed = self.client.get("/api/account/stores").json()["stores"]
        self.assertEqual(listed, [{"store_id": store["store_id"], "name": "우리분식", "business_type_name": "분식전문점",
                                   "area_name": "상도역 5번", "station_name": None, "sample": False, "menu_count": 2,
                                   "last_opened": True}])
        self.assertEqual(self.client.get("/api/health").json()["store_id"], store["store_id"])
        self.assertEqual(self.client.get("/api/health").json()["blocking"], [])

    def test_registered_store_data_apis_answer_without_500(self):
        client, demo, source = build_aware()
        empty_owner(client)
        sid = self.register(client)["store_id"]
        client.post("/api/auth/store", json={"store_id": sid})
        for path in ("/api/briefing", "/api/cards", "/api/insight"):
            res = client.get(path)
            self.assertEqual(res.status_code, 503, (path, res.text))      # 리뷰 분석 서비스가 아직 모르는 가게
            self.assertNotIn("온기한식", res.text)
        self.assertEqual(client.get("/api/approvals").json(), {"items": []})
        self.assertEqual(client.get("/api/market/status").json()["store"]["store_id"], sid)

    def test_validation(self):
        bad = [{"name": ""}, {"name": "x" * 31}, {"name": "가\x07게"}, {"industry_code": "CS 1"},
               {"business_status": "open"}, {"channels": ["a"] * 7}, {"channels": "배민"},
               {"location": {"kind": "gps", "label": "x"}}, {"location": {"kind": "address", "label": ""}},
               {"location": {"kind": "station", "label": "역", "latitude": 99}},
               {"area": {"area_code": "311083", "name": "상권"}}, {"area": {"area_code": "3110836", "name": "상권", "period": "2026Q2"}},
               {"menus": [{"name": "a", "price": -1}]}, {"menus": [{"name": "a", "price": 1_000_001}]},
               {"menus": [{"name": "a", "price": True}]}, {"menus": [{"name": f"m{i}", "price": 1} for i in range(31)]}]
        for case in bad:
            res = self.client.post("/api/account/stores", json=new_store(**case))
            self.assertEqual((res.status_code, res.json()["error"]["state"]), (422, "invalid"), (case, res.text))
        missing = new_store()
        del missing["area"]
        self.assertEqual(self.client.post("/api/account/stores", json=missing).status_code, 422)
        self.assertEqual(self.client.post("/api/account/stores", content=b"not json").status_code, 422)
        minimal = {k: v for k, v in new_store().items() if k not in ("channels", "menus")}
        made = self.client.post("/api/account/stores", json=minimal)
        self.assertEqual((made.status_code, made.json()["store"]["menus"], made.json()["store"]["channels"]), (201, [], []))

    def test_ten_stores_at_most(self):
        for i in range(10):
            self.register(name=f"가게{i}")
        res = self.client.post("/api/account/stores", json=new_store(name="열한번째"))
        self.assertEqual((res.status_code, res.json()["error"]["state"]), (422, "store_limit"))
        self.assertEqual(len(self.client.get("/api/account/stores").json()["stores"]), 10)

    def test_detail_and_patch_only_my_registered_store(self):
        mine = self.register()["store_id"]
        res = self.client.patch(f"/api/account/stores/{mine}",
                                json={"name": "우리분식 본점", "menus": [{"name": "김밥", "price": 3000}]})
        self.assertEqual(res.status_code, 200, res.text)
        store = res.json()["store"]
        self.assertEqual((store["name"], store["menus"], store["channels"]), ("우리분식 본점", [{"name": "김밥", "price": 3000}],
                                                                             ["배달의민족", "쿠팡이츠"]))
        self.assertEqual(self.client.get(f"/api/account/stores/{mine}").json()["store"]["name"], "우리분식 본점")
        self.assertEqual(self.client.get("/api/auth/me").json()["stores"][0]["name"], "우리분식 본점")
        self.assertEqual(self.client.patch(f"/api/account/stores/{mine}", json={"name": ""}).status_code, 422)
        # 예시 가게는 고칠 수 없다
        for method in ("GET", "PATCH"):
            res = self.client.request(method, "/api/account/stores/store_ongi", json={"name": "바꿈"})
            self.assertEqual((res.status_code, res.json()["error"]["state"]), (403, "sample_store"))
        # 남의 가게·없는 가게
        other = TestClient(self.client.app)
        empty_owner(other, login="owner02")
        theirs = self.register(other, name="옆집")["store_id"]
        for sid in (theirs, "store_000000000000", "store_nothing"):
            for method in ("GET", "PATCH", "DELETE"):
                res = self.client.request(method, f"/api/account/stores/{sid}", json={"name": "뺏기"})
                self.assertEqual((res.status_code, res.json()["error"]["state"]), (403, "not_your_store"), (sid, method))
            self.assertEqual(self.client.post("/api/auth/store", json={"store_id": sid}).status_code, 403)
            self.assertEqual(self.client.get(f"/api/account/stores/{sid}/summary").status_code, 403)
        self.assertEqual(other.get(f"/api/account/stores/{theirs}").json()["store"]["name"], "옆집")

    def test_remove_and_reorder(self):
        a = self.register(name="가")["store_id"]
        b = self.register(name="나")["store_id"]
        c = self.register(name="다")["store_id"]
        res = self.client.put("/api/account/stores/order", json={"store_ids": [c, a, b]})
        self.assertEqual([s["store_id"] for s in res.json()["stores"]], [c, a, b])
        self.assertEqual([s["store_id"] for s in self.client.get("/api/auth/me").json()["stores"]], [c, a, b])
        for wrong in ([c, a], [c, a, b, b], [c, a, "store_ongi"], "x"):
            res = self.client.put("/api/account/stores/order", json={"store_ids": wrong})
            self.assertEqual((res.status_code, res.json()["error"]["state"]), (422, "invalid"), wrong)
        self.client.post("/api/auth/store", json={"store_id": a})
        res = self.client.delete(f"/api/account/stores/{a}")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(([s["store_id"] for s in res.json()["stores"]], res.json()["store_id"]), ([c, b], c))
        self.assertEqual(self.client.get("/api/auth/me").json()["store_id"], c)
        self.assertEqual(self.client.delete(f"/api/account/stores/{a}").status_code, 403)       # 이미 뺌
        self.assertIsNotNone(self.demo.storage.registered_stores.get(a))                        # 가게 줄은 남는다
        self.client.delete(f"/api/account/stores/{b}")
        res = self.client.delete(f"/api/account/stores/{c}")
        self.assertEqual(res.json(), {"stores": [], "store_id": None})
        self.assertEqual(self.client.get("/api/briefing").status_code, 409)

    def test_sample_store_can_be_removed_from_my_list(self):
        signup(TestClient(self.client.app), login="owner03", stores=("store_ongi",))
        client = TestClient(self.client.app)
        client.post("/api/auth/login", json={"login_id": "owner03", "password": "pass-word-1"})
        sid = self.register(client)["store_id"]
        res = client.delete("/api/account/stores/store_ongi")
        self.assertEqual((res.json()["store_id"], [s["store_id"] for s in res.json()["stores"]]), (sid, [sid]))


class Summary(unittest.TestCase):
    def setUp(self):
        self.client, self.demo, self.source = build_aware()
        signup(self.client, stores=("store_ongi", "store_basak"))

    def test_ready_bad_good_empty_and_unavailable(self):
        res = self.client.get("/api/account/stores/store_ongi/summary")
        self.assertEqual(res.json(), {"state": "ready", "reviews": 40, "complaints": 12,
                                      "headline": "포장 누락 3건 반복", "tone": "bad"})
        calm = copy.deepcopy(fixture("insight_ongi.json"))
        for g in calm["groups"]:
            g["is_repeated"] = False
        self.source.insights["store_basak"] = calm
        self.assertEqual(self.client.get("/api/account/stores/store_basak/summary").json(),
                         {"state": "ready", "reviews": 40, "complaints": 12, "headline": "반복된 불만이 없어요", "tone": "good"})
        self.source.insights["store_basak"] = {**calm, "review_count": 0, "complaint_count": 0, "groups": []}
        self.assertEqual(self.client.get("/api/account/stores/store_basak/summary").json(),
                         {"state": "empty", "reviews": 0, "complaints": 0, "headline": "리뷰를 넣으면 분석을 시작해요",
                          "tone": "muted"})
        self.source.down = True
        res = self.client.get("/api/account/stores/store_ongi/summary")
        self.assertEqual(res.status_code, 200)
        self.assertEqual((res.json()["state"], res.json()["reviews"], res.json()["complaints"]), ("unavailable", None, None))
        self.assertEqual(self.client.get("/api/account/stores/store_mongle/summary").status_code, 403)   # 가지지 않은 가게

    def test_registered_store_without_reviews_is_empty(self):
        sid = self.client.post("/api/account/stores", json=new_store()).json()["store"]["store_id"]
        self.assertEqual(self.client.get(f"/api/account/stores/{sid}/summary").json()["state"], "empty")


class Profile(unittest.TestCase):
    def setUp(self):
        self.client, self.demo, *_ = build()
        signup(self.client)

    def test_rename(self):
        res = self.client.patch("/api/account/profile", json={"display_name": "  이  사장 "})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["user"]["display_name"], "이 사장")
        self.assertEqual(set(res.json()), set(self.client.get("/api/auth/me").json()))       # me 와 같은 모양
        for bad in ("", "x" * 21, None, 3):
            res = self.client.patch("/api/account/profile", json={"display_name": bad})
            self.assertEqual((res.status_code, res.json()["error"]["state"]), (422, "invalid"), bad)

    def test_change_password(self):
        wrong = self.client.post("/api/account/password", json={"current_password": "nope-nope", "new_password": "new-pass-1"})
        self.assertEqual((wrong.status_code, wrong.json()["error"]["state"]), (401, "bad_password"))
        short = self.client.post("/api/account/password", json={"current_password": "pass-word-1", "new_password": "short"})
        self.assertEqual(short.status_code, 422)
        ok = self.client.post("/api/account/password", json={"current_password": "pass-word-1", "new_password": "new-pass-1"})
        self.assertEqual((ok.status_code, ok.json()), (200, {"ok": True}))
        other = TestClient(self.client.app)
        self.assertEqual(other.post("/api/auth/login", json={"login_id": "owner01", "password": "pass-word-1"}).status_code, 401)
        self.assertEqual(other.post("/api/auth/login", json={"login_id": "owner01", "password": "new-pass-1"}).status_code, 200)

    def test_wrong_current_password_counts_like_login_failures(self):
        from web import auth as auth_mod
        codes = [self.client.post("/api/account/password", json={"current_password": "nope-nope", "new_password": "new-pass-1"})
                 .status_code for _ in range(auth_mod.FAIL_LIMIT + 1)]
        self.assertEqual(codes, [401] * auth_mod.FAIL_LIMIT + [429])

    def test_demo_account_cannot_change_password(self):
        demo = TestClient(self.client.app)
        demo.post("/api/auth/demo-login")
        res = demo.post("/api/account/password", json={"current_password": "", "new_password": "new-pass-1"})
        self.assertEqual((res.status_code, res.json()["error"]["state"]), (403, "demo_account"))


class RegisteredReview(FakeReview):
    """리뷰 분석 서비스 대신: 등록 가게는 실제 서비스처럼 '없는 가게' 404."""

    def __call__(self, request):
        if store_profiles.is_registered_id(request.url.params.get("store_id")):
            self.requests.append({"method": request.method, "path": request.url.path, "params": dict(request.url.params)})
            return httpx.Response(404, json={"error": {"code": "STORE_NOT_FOUND", "message": "없는 가게입니다"}})
        return super().__call__(request)


def build_review(storage=None):
    tmp = Path(tempfile.mkdtemp())
    storage = storage or MemoryStore()
    review = RegisteredReview()
    source = ReviewSource("http://review.test", client=httpx.Client(base_url="http://review.test",
                                                                    transport=httpx.MockTransport(review)))
    mkt = Recorder({"deleted": 0})
    demo = Demo(settings(tmp), source=source, storage=storage)
    app = create_app(demo, assistant=AssistantProxy(None), care=CareProxy(None),
                     marketing=MarketingProxy("http://marketing.test", transport=httpx.MockTransport(mkt)),
                     auth=AuthService(storage))
    return app, demo, review, mkt


class ResetAndWithdrawRegistered(unittest.TestCase):
    def setUp(self):
        self.app, self.demo, self.review, self.mkt = build_review()
        self.client = TestClient(self.app)
        signup(self.client, stores=("store_ongi",))
        self.me = "u-" + self.client.get("/api/auth/me").json()["user"]["user_id"]
        self.kept = self.client.post("/api/account/stores", json=new_store(name="남긴 가게")).json()["store"]["store_id"]
        self.gone = self.client.post("/api/account/stores", json=new_store(name="뺀 가게")).json()["store"]["store_id"]
        self.client.delete(f"/api/account/stores/{self.gone}")
        for s in ("store_ongi", self.kept, self.gone):
            self.demo.storage.approvals.save(s, self.me, {"draft_id": f"d-{s}", "status": "approved", "edited": False,
                                                          "text": "글", "approved_at": "2026-11-20T10:00:00+09:00", "mode": "mock"})

    def test_reset_account_covers_registered_stores(self):
        res = self.client.post("/api/auth/reset", json={"scope": "account"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["complete"], res.json())
        self.assertEqual({r["store_id"] for r in res.json()["stores"]}, {"store_ongi", self.kept})
        self.assertEqual(self.demo.storage.approvals.list(self.kept, self.me), [])
        self.assertEqual(len(self.demo.storage.approvals.list(self.gone, self.me)), 1)   # 목록에서 뺀 가게는 초기화 대상 아님
        self.client.post("/api/auth/store", json={"store_id": self.kept})
        res = self.client.post("/api/auth/reset", json={"scope": "store"})
        self.assertEqual(([r["store_id"] for r in res.json()["stores"]], res.json()["complete"]), ([self.kept], True))

    def test_withdraw_erases_records_and_registered_rows(self):
        res = self.client.post("/api/auth/withdraw", json={"password": "pass-word-1"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(market_cookies_expired(res), {"/api/assistant", "/api/market"})
        for s in ("store_ongi", "store_basak", "store_mongle", self.kept, self.gone):
            self.assertEqual(self.demo.storage.approvals.list(s, self.me), [], s)
        self.assertEqual({(r["params"]["store"]) for r in self.mkt.requests},
                         {"store_ongi", "store_basak", "store_mongle", self.kept, self.gone})
        for s in (self.kept, self.gone):
            self.assertIsNone(self.demo.storage.registered_stores.get(s))
            self.assertFalse(store_profiles.known(s))
        self.assertFalse(self.client.get("/api/auth/me").json()["authenticated"])


class GuestAndSamplesUnchanged(unittest.TestCase):
    def test_sample_public_rows_only_gain_the_sample_flag(self):
        rows = store_profiles.public_list()
        self.assertEqual([r["sample"] for r in rows], [True, True, True])
        self.assertEqual([{k: v for k, v in r.items() if k != "sample"} for r in rows],
                         [{"store_id": b.store_id, "name": b.short_name, "business_type_name": b.business_type_name,
                           "area_name": b.area_name, "station_name": b.station_name} for b in store_profiles.BUNDLES.values()])
        self.assertEqual(store_profiles.BUNDLES["store_basak"].label, "바삭치킨 · 상도역 · 치킨전문점")

    def test_guest_me_and_demo_login(self):
        client, *_ = build()
        me = client.get("/api/auth/me").json()
        self.assertEqual((me["authenticated"], me["store_id"], me["stores"][0]["sample"]), (False, "store_ongi", True))
        data = client.post("/api/auth/demo-login").json()
        self.assertEqual([s["sample"] for s in data["stores"]], [True, True, True])
        self.assertEqual(client.get("/api/account/stores").json()["stores"][0]["last_opened"], True)


class WithPostgres(unittest.TestCase):
    """같은 흐름을 PostgreSQL 로 (TEST_DB_HOST 가 있을 때만). 서버 두 대 = 같은 DB 에 붙은 앱 둘."""

    def setUp(self):
        from shared.storage.testing import open_test_db
        self.dbs = [open_test_db(app_name="ic26-test-acct-a"), open_test_db(app_name="ic26-test-acct-b")]
        if self.dbs[0] is None:
            self.skipTest("TEST_DB_HOST 없음 (PostgreSQL 시험은 건너뜀)")

    def tearDown(self):
        for db in self.dbs:
            if db is not None:
                db.close()

    def test_store_made_on_one_server_is_seen_by_the_other(self):
        a = build(storage=self.dbs[0])[0]
        b = build(storage=self.dbs[1])[0]
        login = "pg" + uuid.uuid4().hex[:10]
        res = a.post("/api/auth/signup", json={"login_id": login, "password": "pass-word-1", "display_name": "정사장",
                                               "stores": []})
        self.assertEqual(res.status_code, 201, res.text)
        b.cookies.set(SESSION_COOKIE, a.cookies[SESSION_COOKIE])
        self.assertEqual(b.get("/api/auth/me").json()["stores"], [])
        sid = a.post("/api/account/stores", json=new_store()).json()["store"]["store_id"]
        store_profiles.forget(sid)                            # b 는 다른 서버: 기억해 둔 것 없이 DB 에서 찾는다
        self.assertEqual(b.post("/api/auth/store", json={"store_id": sid}).status_code, 200)
        self.assertEqual(a.get("/api/auth/me").json()["store_id"], sid)
        self.assertEqual(b.patch(f"/api/account/stores/{sid}", json={"name": "새 이름"}).json()["store"]["name"], "새 이름")
        store_profiles.forget(sid)
        self.assertEqual(a.get("/api/account/stores").json()["stores"][0]["name"], "새 이름")
        self.assertEqual(b.delete(f"/api/account/stores/{sid}").json(), {"stores": [], "store_id": None})
        self.assertEqual(a.get("/api/briefing").status_code, 409)
        self.assertEqual(a.post("/api/account/password", json={"current_password": "pass-word-1",
                                                               "new_password": "new-pass-1"}).json(), {"ok": True})
        self.assertEqual(TestClient(a.app).post("/api/auth/login", json={"login_id": login, "password": "new-pass-1"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
