"""사장님이 직접 등록한 가게로 메인 서비스가 도는지 (6차 회의 11/20). 실제 리뷰 분석·맞춤 마케팅 서비스 코드를 같은 프로세스에 띄워
비서 화면 서버와 잇는다 (HTTP 대신 TestClient 전송). 분류 모델·상권 서비스는 가짜, 네트워크 없음, HCX 안 부름.

- 등록 가게의 요청에만 X-IC26-Store-Profile 헤더가 실린다 (예시 세 곳·게스트는 예전 요청 그대로).
- 리뷰 0건: 홈·카드·분석은 빈 결과 + empty_reason / no_card_a / no_card_b (사장님 말). 붙여넣으면 분류·묶음·불만 카드·생성·승인.
- 고객응대(응대 점수·보고서)·맞춤 마케팅이 오류 없이 돈다. 계정 초기화·탈퇴가 등록 가게의 붙여넣은 리뷰·마케팅 기록을 지운다.
- 상권 setup: 역으로 등록한 가게는 역, 주소로 등록한 가게는 주소 검색 → 맞는 후보, 검색 실패는 200 + 'unavailable'.
- StoreHub 는 등록 가게를 상한까지만 들고 있다.

실행 (services/web 에서):  env -u APP_MODE -u DB_HOST PYTHONPATH=../..:. python -m pytest -q tests/test_registered_services.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from shared import store_header, store_profiles
from shared.storage import MemoryStore
from tests.test_account_stores import new_store
from tests.test_auth_stores import signup
from tests.test_market_proxy import FakeMarket
from tests.test_web import FakeSource, settings
from web.assistant_proxy import ADDRESS_MISS, AssistantProxy, MarketClient
from web.auth import AuthService
from web.care_proxy import CareProxy
from web.demo import Demo
from web.main import create_app
from web.market_proxy import MarketProxy
from web.marketing_proxy import MarketingProxy
from web.sources import ReviewSource
from web.stores import StoreHub

REPO = Path(__file__).resolve().parents[3]
for extra in (REPO / "services" / "review-insight", REPO / "experiments" / "marketing"):
    if str(extra) not in sys.path:
        sys.path.append(str(extra))           # 맨 뒤에: 이 서버의 web 패키지보다 앞서지 않게

from app import classify as review_classify  # noqa: E402  (services/review-insight 의 app)
from app import main as review_main  # noqa: E402
from app import registered as review_registered  # noqa: E402
from app import service as review_service  # noqa: E402
from app import storage as review_storage  # noqa: E402
from app.classify import Classifier  # noqa: E402
from marketing_survey import server as marketing_server  # noqa: E402
from marketing_survey import stores as marketing_stores  # noqa: E402

PASSWORD = "pass-word-1"


def _fake_model():
    """리뷰마다 '포장 누락' 불만 하나 (근거는 글 앞 4자)."""
    def handler(req):
        body = json.loads(req.content)
        user = body["messages"][-1]["content"]
        rows = json.loads(user[user.index("\n[\n") + 1:])
        out = [{"review_id": r["review_id"], "sentiment": "negative", "summary": "요약",
                "topics": [{"topic": "missing_item", "polarity": "negative", "evidence": r["text"][:4]}]} for r in rows]
        return httpx.Response(200, json={"result": {"message": {"content": json.dumps(out, ensure_ascii=False)}}})
    return httpx.MockTransport(handler)


class Tap(httpx.BaseTransport):
    """다른 전송을 그대로 부르면서 (서비스, 경로, 쿼리의 가게, 헤더의 가게 프로필)을 적는다."""

    def __init__(self, name: str, inner: httpx.BaseTransport, log: list):
        self.name, self.inner, self.log = name, inner, log

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        store = params.get("store_id") or params.get("store")
        if store is None and request.content and request.headers.get("content-type", "").startswith("application/json"):
            try:
                store = json.loads(request.content).get("store_id")
            except ValueError:
                pass
        self.log.append((self.name, request.url.path, store, request.headers.get(store_header.HEADER)))
        return self.inner.handle_request(request)


def services(log: list):
    """(ReviewSource, CareProxy, MarketingProxy) — 실제 서비스 앱에 붙인 것."""
    review_tc = TestClient(review_main.app, raise_server_exceptions=False)
    mkt_tc = TestClient(marketing_server.app, raise_server_exceptions=False)
    review_http = httpx.Client(base_url="http://review.test", transport=Tap("review", review_tc._transport, log))
    source = ReviewSource("http://review.test", client=review_http)
    care = CareProxy("http://review.test", transport=Tap("care", review_tc._transport, log))
    marketing = MarketingProxy("http://marketing.test", transport=Tap("marketing", mkt_tc._transport, log))
    return source, care, marketing


class ServiceSandbox(unittest.TestCase):
    """리뷰 분석·맞춤 마케팅 서비스의 저장 폴더를 임시 폴더로, 분류는 가짜 모델로."""

    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.patches = [
            mock.patch.object(review_service, "RUNTIME", tmp / "runtime"),
            mock.patch.object(review_classify, "REPLAY_FILE", tmp / "replay.json"),
            mock.patch.object(review_classify, "RUNTIME_CACHE", tmp / "runtime.json"),
            mock.patch.object(review_classify, "USAGE_LOG", tmp / "logs" / "usage.jsonl"),
            mock.patch.object(review_main, "_classifier", Classifier("live", api_key="k", transport=_fake_model(), hints=False)),
            mock.patch.dict(os.environ, {"MARKETING_RECORDS_DIR": str(tmp / "marketing"), "MARKETING_APP_MODE": "mock"}),
        ]
        for p in self.patches:
            p.start()
        review_storage.use(None)
        review_registered.registry().clear()
        marketing_stores._registered.clear()
        self.tmp = tmp

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        review_storage.reset()
        review_registered.registry().clear()
        marketing_stores._registered.clear()


class RegisteredStoreEndToEnd(ServiceSandbox):
    def setUp(self):
        super().setUp()
        self.log: list = []
        source, care, marketing = services(self.log)
        storage = MemoryStore()
        self.demo = Demo(settings(self.tmp), source=source, storage=storage)
        self.app = create_app(self.demo, assistant=AssistantProxy(None), care=care, marketing=marketing,
                              auth=AuthService(storage), market=MarketProxy(None))
        self.client = TestClient(self.app)
        res = signup(self.client, stores=())
        self.assertEqual(res.status_code, 201, res.text)
        created = self.client.post("/api/account/stores", json=new_store())
        self.assertEqual(created.status_code, 201, created.text)
        self.sid = created.json()["store"]["store_id"]
        self.assertEqual(self.client.post("/api/auth/store", json={"store_id": self.sid}).status_code, 200)
        self.visitor = self.client.get("/api/auth/me").json()["user"]["user_id"]

    def headers_for(self, store):
        return [h for _, _, s, h in self.log if s == store]

    def paste(self, text):
        res = self.client.post("/api/reviews", json={"text": text, "rating": 1, "channel": "baemin"})
        self.assertEqual(res.status_code, 201, res.text)
        return res.json()

    def test_zero_reviews_is_empty_everywhere_with_reasons(self):
        brief = self.client.get("/api/briefing")
        self.assertEqual(brief.status_code, 200, brief.text)
        b = brief.json()
        self.assertEqual((b["store"]["name"], b["store"]["area_name"], b["counts"]["review_count"], b["groups"]),
                         ("우리분식", "상도역 5번", 0, []))
        self.assertEqual(b["empty_reason"], Demo.EMPTY_REASON)
        cards = self.client.get("/api/cards").json()
        self.assertEqual(cards["cards"], [])
        self.assertEqual((cards["no_card_a"], cards["no_card_b"]), (Demo.EMPTY_REASON, Demo.NO_CARD_B_REGISTERED))
        ins = self.client.get("/api/insight").json()
        self.assertEqual((ins["review_count"], ins["complaint_count"], ins["top_issue_id"]), (0, 0, None))
        summary = self.client.get(f"/api/account/stores/{self.sid}/summary").json()
        self.assertEqual(summary["state"], "empty")
        # 등록 가게의 서비스 요청에는 모두 가게 프로필 헤더가 실렸다
        sent = self.headers_for(self.sid)
        self.assertTrue(sent and all(sent))
        self.assertEqual(store_header.decode(sent[0])["name"], "우리분식")

    def test_paste_analysis_card_generate_and_approve(self):
        for text in ("떡볶이 소스가 빠져 왔어요", "순대 소금이 빠져 있었어요", "어묵 국물이 빠졌네요"):
            self.paste(text)
        ins = self.client.get("/api/insight").json()
        self.assertEqual((ins["review_count"], ins["top_issue_id"]), (3, "iss_missing_item"))
        self.assertNotIn("empty_reason", ins)
        cards = self.client.get("/api/cards").json()
        complaint = next(c["card"] for c in cards["cards"] if c["card"]["kind"] == "complaint")
        self.assertNotIn("no_card_a", cards)
        self.assertEqual(cards["no_card_b"], Demo.NO_CARD_B_REGISTERED)
        run = self.client.post(f"/api/cards/{complaint['card_id']}/run", json={})
        self.assertEqual(run.status_code, 200, run.text)
        drafts = run.json()["drafts"]
        self.assertTrue(any("우리분식" in d["text"] for d in drafts))
        self.assertFalse(any("온기한식" in d["text"] for d in drafts))
        reply = next(d for d in drafts if d["generator"] == "reply_draft")
        ok = self.client.post(f"/api/drafts/{reply['draft_id']}/approve",
                              json={"text": reply["text"], "original": reply["text"], "card_id": complaint["card_id"],
                                    "kind": "reply_draft", "review_id": reply["target_review_id"]})
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(len(self.client.get("/api/approvals").json()["items"]), 1)
        # 고객응대: 응대 점수·보고서
        for path in ("/api/care/response", "/api/care/report/daily", "/api/care/report/monthly"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.get(f"/api/account/stores/{self.sid}/summary").json()["state"], "ready")

    def test_care_at_zero_reviews(self):
        for path in ("/api/care/status", "/api/care/response", "/api/care/report/daily", "/api/care/report/monthly"):
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, (path, res.text))

    def test_marketing_starts_with_the_registered_store(self):
        meta = self.client.get("/api/marketing-survey/meta")
        self.assertEqual(meta.status_code, 200, meta.text)
        self.assertEqual(meta.json()["store_name"], "우리분식")
        step = self.client.post("/api/marketing-survey/step", json={"state": None})
        self.assertEqual(step.status_code, 200, step.text)
        state = step.json()["state"]
        for answer in ("맞춤 홍보 제안", "예", "포장 누락"):
            state = self.client.post("/api/marketing-survey/step", json={"state": state, "answer": answer}).json()["state"]
        gen = self.client.post("/api/marketing-survey/generate", json={"state": state})
        self.assertEqual(gen.status_code, 409)
        self.assertIn("리뷰", gen.json()["error"]["message"])            # 화면이 보여 줄 안내 문장 (500 아님)
        plan = self.client.post("/api/marketing-survey/plan", json={"state": state})
        self.assertEqual(plan.status_code, 200, plan.text)
        self.assertTrue(plan.json()["unavailable_drafts"])
        self.assertEqual(self.client.get("/api/marketing-survey/health").json()["state"], "ready")

    def test_reset_and_withdraw_erase_registered_records(self):
        self.paste("떡볶이 소스가 빠져 왔어요")
        self.client.post("/api/marketing-survey/plan", json={"state": {"node": "DECISION", "mode": "leftover",
                                                                       "raw": {"leftover_item": "떡볶이", "leftover_portions": 3}}})
        reset = self.client.post("/api/auth/reset", json={"scope": "store"}).json()
        self.assertTrue(reset["complete"], reset)
        row = reset["stores"][0]
        self.assertEqual((row["store_id"], row["reviews"], row["marketing"]), (self.sid, 1, "cleared"))
        self.assertEqual(self.client.get("/api/insight").json()["review_count"], 0)
        self.paste("순대가 빠졌어요")
        gone = self.client.post("/api/auth/withdraw", json={"password": PASSWORD})
        self.assertEqual(gone.status_code, 200, gone.text)
        self.assertEqual(review_service.pasted_reviews(self.sid, f"u-{self.visitor}"), [])
        from marketing_survey import records as marketing_records
        self.assertFalse(marketing_records.records_path(self.sid, f"u-{self.visitor}").exists())

    def test_sample_stores_and_guests_send_no_profile_header(self):
        guest = TestClient(self.app)
        for path in ("/api/briefing", "/api/cards", "/api/insight", "/api/care/response", "/api/marketing-survey/meta"):
            self.assertEqual(guest.get(path).status_code, 200, path)
        sent = self.headers_for("store_ongi")
        self.assertTrue(sent)
        self.assertEqual(set(sent), {None})


class FakeMarketWithSearch(FakeMarket):
    """주소 검색(POST /api/onboarding/locations/search)과 서랍의 status·conversation 까지 흉내 낸다."""

    def __init__(self, candidates=None, search_status=200):
        super().__init__()
        self.candidates = candidates if candidates is not None else []
        self.search_status = search_status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/onboarding/locations/search":
            self.requests.append({"method": "POST", "path": request.url.path, "json": json.loads(request.content)})
            if self.search_status != 200:
                return httpx.Response(self.search_status, json={"detail": "주소 검색에는 도로명과 건물 번호를 입력해 주세요."})
            return httpx.Response(200, json={"status": "address_candidate", "search_id": "srch1" if self.candidates else None,
                                             "candidates": self.candidates})
        if request.url.path == "/api/assistant/status":
            return httpx.Response(200, json={"enabled": True, "model_connected": False})
        if request.url.path == "/api/assistant/conversation":
            res = super().__call__(httpx.Request("GET", "http://market.test/api/onboarding/analysis-selection",
                                                 headers=request.headers))
            st = res.json()
            sel, prof = st.get("analysis_selection") or {}, st.get("profile") or {}
            cond = {"area_code": sel.get("area_code"), "industry_code": (prof.get("industry") or {}).get("code"),
                    "period": sel.get("period")} if st.get("conditions_confirmed") else None
            return httpx.Response(200, json={"turns": [], "conditions": cond}, headers=res.headers)
        return super().__call__(request)


class RegisteredMarketSetup(unittest.TestCase):
    def build(self, fake, store_body):
        tmp = Path(tempfile.mkdtemp())
        storage = MemoryStore()
        client_of = lambda: MarketClient("http://market.test", "127.0.0.1:8766", read_timeout=5.0, transport=httpx.MockTransport(fake))
        demo = Demo(settings(tmp), source=FakeSource(), storage=storage)
        app = create_app(demo, assistant=AssistantProxy(client_of()), care=CareProxy(None), marketing=MarketingProxy(None),
                         auth=AuthService(storage), market=MarketProxy(client_of()))
        client = TestClient(app)
        signup(client, stores=())
        sid = client.post("/api/account/stores", json=store_body).json()["store"]["store_id"]
        client.post("/api/auth/store", json={"store_id": sid})
        return client, sid

    def posted_profiles(self, fake):
        return [r["json"] for r in fake.requests if r["method"] == "POST" and r["path"].endswith("/profile")]

    def test_station_store_uses_its_station_industry_area_and_period(self):
        fake = FakeMarketWithSearch()
        body = new_store(industry_code="CS100007", location={"kind": "station", "label": "상도역", "station_id": "kric-st-1",
                                                             "station_name": "상도역", "district_name": "동작구"},
                         area={"area_code": "3110836", "name": "상도역 5번", "period": "20261"})
        client, _ = self.build(fake, body)
        data = client.post("/api/market/setup").json()
        self.assertEqual(data["status"], "ok", data)
        self.assertEqual((data["conditions"]["area_code"], data["conditions"]["industry_code"], data["conditions"]["period"],
                          data["conditions"]["home"]), ("3110836", "CS100007", "20261", True))
        self.assertEqual(self.posted_profiles(fake)[0]["location"], {"kind": "station", "station_id": "kric-st-1"})
        status = client.get("/api/market/status").json()
        self.assertEqual((status["store"]["name"], status["store"]["location_label"], status["store"]["district_name"]),
                         ("우리분식", "상도역", "동작구"))
        # 서랍도 같은 가게 조건
        drawer = client.post("/api/assistant/setup?force=1").json()
        self.assertEqual(drawer["status"], "ok", drawer)
        self.assertTrue(drawer["conditions"]["is_store_default"])
        self.assertTrue(client.get("/api/assistant/status").json()["setup"]["label"].startswith("우리분식 · 상도역"))

    def test_address_store_searches_again_and_picks_the_matching_candidate(self):
        fake = FakeMarketWithSearch(candidates=[
            {"id": "c-other", "label": "서울특별시 동작구 상도로 100", "road_address": "서울특별시 동작구 상도로 100",
             "in_seoul": True, "latitude": 37.6, "longitude": 127.0},
            {"id": "c-mine", "label": "서울 동작구 상도로 1", "road_address": "서울 동작구 상도로 1", "in_seoul": True,
             "latitude": 37.5, "longitude": 126.9}])
        client, _ = self.build(fake, new_store())
        data = client.post("/api/market/setup").json()
        self.assertEqual(data["status"], "ok", data)
        search = next(r for r in fake.requests if r["path"] == "/api/onboarding/locations/search")
        self.assertEqual(search["json"], {"query": "서울 동작구 상도로 1"})
        self.assertEqual(self.posted_profiles(fake)[0]["location"], {"kind": "address", "search_id": "srch1", "candidate_id": "c-mine"})
        self.assertTrue(data["conditions"]["home"])

    def test_address_search_failure_is_200_unavailable_not_500(self):
        for fake in (FakeMarketWithSearch(candidates=[]), FakeMarketWithSearch(search_status=422),
                     FakeMarketWithSearch(candidates=[{"id": "a", "road_address": "서울 중구 세종대로 1", "in_seoul": True},
                                                      {"id": "b", "road_address": "서울 중구 세종대로 2", "in_seoul": True}])):
            client, _ = self.build(fake, new_store())
            res = client.post("/api/market/setup")
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual((res.json()["status"], res.json()["message"], res.json()["conditions"]), ("unavailable", ADDRESS_MISS, None))
            drawer = client.post("/api/assistant/setup").json()
            self.assertEqual((drawer["status"], drawer["message"]), ("unavailable", ADDRESS_MISS))
            self.assertEqual(self.posted_profiles(fake), [])

    def test_cultural_events_use_the_registered_district_or_seoul(self):
        fake = FakeMarketWithSearch()
        client, _ = self.build(fake, new_store(location={"kind": "address", "label": "서울 관악구 관악로 1",
                                                         "road_address": "서울특별시 관악구 관악로 1"}))
        client.get("/api/market/cultural-events")
        sent = [r for r in fake.requests if r["path"].endswith("/cultural-events")][-1]
        self.assertEqual(sent["params"], {"district": "관악구"})
        fake2 = FakeMarketWithSearch()
        client2, _ = self.build(fake2, new_store(location={"kind": "address", "label": "어딘가 1", "road_address": "어딘가 1"}))
        client2.get("/api/market/cultural-events")
        sent = [r for r in fake2.requests if r["path"].endswith("/cultural-events")][-1]
        self.assertEqual(sent["params"], {})                                       # 구를 모름 → 서울 전체


class HubLimit(unittest.TestCase):
    def tearDown(self):
        store_profiles.set_registered_lookup(None)

    def test_registered_demos_are_bounded_and_samples_stay(self):
        rows = {f"store_{i:012x}": {"store_id": f"store_{i:012x}", "name": f"가게{i}", "profile": {}} for i in range(5)}
        store_profiles.set_registered_lookup(rows.get)
        demo = Demo(settings(Path(tempfile.mkdtemp())), source=FakeSource(), storage=MemoryStore())
        hub = StoreHub(demo, AssistantProxy(None), CareProxy(None), MarketingProxy(None), registered_max=2)
        hub.demo("store_basak")
        for sid in rows:
            hub.demo(sid)
            hub.care(sid)
            hub.marketing(sid)
        self.assertEqual(hub.held(), 2)
        held = {d.s.store_id for d in hub.demos()}
        self.assertEqual(held, {"store_ongi", "store_basak", "store_000000000003", "store_000000000004"})
        again = hub.demo("store_000000000000")                 # 버린 가게를 다시 쓰면 새로 만든다
        self.assertEqual(again.s.store_id, "store_000000000000")
        self.assertEqual(hub.held(), 2)


if __name__ == "__main__":
    unittest.main()
