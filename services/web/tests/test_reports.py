"""종합 리포트의 주간·월간 보고서 저장 (web/reports.py, 6차 회의 11/20). 가짜 리뷰 분석 서비스(httpx.MockTransport)를 쓰고
네트워크·HCX 는 부르지 않는다. 주간 집계 자체(경계·지난주 비교·0건)는 services/review-insight/tests/test_report_weekly.py 가 본다.

확인하는 것
  · 처음 열면 계산해서 저장, 다시 열면 저장본 (기간이 끝난 뒤 만든 저장본은 서비스를 다시 부르지 않음)
  · 다시 만들기는 새로 계산해 덮어씀 (목록에는 그 기간이 하나)
  · 계정이 다르면 따로 저장, 가게가 다르면 따로 목록, 수 세기는 내 가게 전체
  · 게스트는 계산만 하고 저장하지 않음 (목록·수는 비어 있음)
  · 진행 중에 만든 저장본은 열 때 지금 값과 견줘 낡았는지 알림 (새 리뷰 수·응대 기록·승인한 글·기간 끝남)
  · 기간 이동 값(이전·다음, 다음이 미래면 없음), 주 이름, 오지 않은 기간·틀린 형식은 400, 서비스 꺼짐은 503 (500 없음)
  · 승인한 글 수는 그 기간에 승인한 것만, 답글·안내문·홍보로 나눔. 마케팅 숫자 중 자료가 없는 칸은 null
  · 저장소(DB)에 닿지 못해도 계산한 보고서는 보여 줌 (storage: unavailable)

실행 (services/web 에서): PYTHONPATH=<저장소 루트>:. python -m pytest -q tests/test_reports.py
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from shared.storage import MemoryStore
from tests.test_web import FakeSource, settings
from web.assistant_proxy import AssistantProxy
from web.auth import AuthService
from web.care_proxy import CareProxy
from web.demo import Demo
from web.main import create_app
from web.marketing_proxy import MarketingProxy
from web.reports import BUNDLE_VERSION, REPORT_VERSION, make_period

KST = timezone(timedelta(hours=9))
P = "/api/review-insight"
NOW = datetime(2026, 11, 20, 15, 0, tzinfo=KST)          # 금요일. 이번 주 11/16~11/22, 이번 달 11월


class FakeService:
    """리뷰 분석 서비스의 /report/weekly·/report/monthly 겉모습. 숫자는 시험이 바꾼다."""

    def __init__(self):
        self.reviews, self.score, self.replied, self.mode = 3, 95, 0, "ok"
        self.requests: list[dict] = []

    def calls(self, kind: str | None = None) -> list[dict]:
        return [r for r in self.requests if r["path"].startswith(P + "/report") and (kind is None or r["path"].endswith(kind))]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.requests.append({"path": request.url.path, "params": params})
        if self.mode == "down":
            raise httpx.ConnectError("connection refused")
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok", "mode": "mock"})
        now = datetime.fromisoformat(params["now"])
        if request.url.path == P + "/report/weekly":
            monday = date.fromisoformat(params["week"])
            monday -= timedelta(days=monday.weekday())
            first, last = monday, monday + timedelta(days=6)
            head = {"week": monday.isoformat(), "week_start": first.isoformat(), "week_end": last.isoformat()}
        elif request.url.path == P + "/report/monthly":
            y, m = map(int, params["month"].split("-"))
            first = date(y, m, 1)
            last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
            head = {"month": params["month"]}
        else:
            return httpx.Response(404, json={"detail": "Not Found"})
        if datetime.combine(first, time(0), tzinfo=KST) > now:
            return httpx.Response(400, json={"error": {"code": "VALIDATION_ERROR", "message": "아직 오지 않은 주입니다"}})
        until = min(datetime.combine(last, time(23, 59, 59), tzinfo=KST), now)
        body = {"store_id": params["store_id"], **head, "until": until.isoformat(timespec="seconds"),
                "review_count": self.reviews, "complaint_count": 1, "complaint_rate": 33 if self.reviews else None,
                "score_start": 100, "score_end": self.score, "score_change": self.score - 100, "score_trend": [], "changes": [],
                "late_count": 0, "repeated_issues": [{"issue_id": "iss_missing_item", "topic_name": "포장 누락", "replied_count": self.replied}],
                "previous": {"review_count": 2, "complaint_count": 1, "complaint_rate": 50}, "topics": [],
                "suggestions": [{"kind": "no_reply", "title": "'포장 누락' 불만 3건에 아직 답글이 없어요", "evidence": "이번 주 1건 · 전체 3건",
                                 "text": "답글로 조치를 알리고, 매장에서 확인해 보세요"}],
                "summary_method": "template", "praise": None}
        return httpx.Response(200, json=body)


def build(storage=None):
    tmp = Path(tempfile.mkdtemp())
    storage = storage or MemoryStore()
    fake = FakeService()
    care = CareProxy("http://review.test", transport=httpx.MockTransport(fake))
    marketing = MarketingProxy("http://marketing.test", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    demo = Demo(settings(tmp), source=FakeSource(), storage=storage)
    app = create_app(demo, assistant=AssistantProxy(None), care=care, marketing=marketing, auth=AuthService(storage))
    app.state.reports.clock = lambda: NOW
    return app, fake, demo, storage


def login(app) -> tuple[TestClient, str]:
    """새 브라우저(TestClient) 하나로 시연 로그인 → (클라이언트, 방문자 id 'u-…')."""
    client = TestClient(app)
    res = client.post("/api/auth/demo-login")
    assert res.status_code == 200, res.text
    return client, "u-" + res.json()["user"]["user_id"]


class Periods(unittest.TestCase):
    def test_week_and_month_keys_labels_and_navigation(self):
        today = NOW.date()
        w = make_period("weekly", "2026-11-18", today)                  # 수요일 → 그 주 월요일
        self.assertEqual((w.key, w.start.isoformat(), w.end.isoformat()), ("2026-11-16", "2026-11-16", "2026-11-22"))
        self.assertEqual((w.label, w.range, w.in_progress), ("11월 3주", "11/16 ~ 11/22", True))
        self.assertEqual((w.prev, w.next), ("2026-11-09", None))       # 다음 주는 미래
        last = make_period("weekly", "2026-11-09", today)
        self.assertEqual((last.prev, last.next, last.in_progress), ("2026-11-02", "2026-11-16", False))
        # 달을 걸친 주는 목요일이 든 달: 10/26~11/1 은 10월 5주, 11/30~12/6 은 12월 1주
        self.assertEqual(make_period("weekly", "2026-10-26", today).label, "10월 5주")
        self.assertEqual(make_period("weekly", "2026-11-02", today).label, "11월 1주")
        self.assertEqual(make_period("weekly", None, date(2026, 12, 2)).label, "12월 1주")
        m = make_period("monthly", None, today)
        self.assertEqual((m.key, m.label, m.range, m.prev, m.next), ("2026-11", "2026년 11월", "11/1 ~ 11/30", "2026-10", None))
        jan = make_period("monthly", "2026-01", today)
        self.assertEqual((jan.prev, jan.next, jan.end.isoformat()), ("2025-12", "2026-02", "2026-01-31"))
        self.assertIsNone(make_period("monthly", "2025-11", today).prev)    # 1년 전까지
        self.assertIsNone(make_period("weekly", "2025-11-17", today).prev)

    def test_bad_and_future_periods_are_rejected(self):
        from web.reports import ReportError
        for kind, value in (("weekly", "2026-11-23"), ("monthly", "2026-12"), ("weekly", "11월"), ("monthly", "2026-13"),
                            ("monthly", "2026-11-01"), ("monthly", "2026-1")):
            with self.subTest(kind=kind, value=value), self.assertRaises(ReportError) as got:
                make_period(kind, value, NOW.date())
            self.assertEqual((got.exception.state, got.exception.http), ("invalid", 400))


class SaveAndReopen(unittest.TestCase):
    def setUp(self):
        self.app, self.fake, self.demo, self.storage = build()
        self.client, self.me = login(self.app)

    def test_first_open_saves_and_second_open_returns_the_saved_one(self):
        first = self.client.get("/api/reports/weekly", params={"period": "2026-11-09"})
        self.assertEqual(first.status_code, 200, first.text)
        a = first.json()
        self.assertEqual((a["storage"], a["saved"], a["made_now"], a["stale"]), ("saved", True, True, None))
        self.assertEqual(a["period"], {"key": "2026-11-09", "start": "2026-11-09", "end": "2026-11-15", "label": "11월 2주",
                                       "range": "11/9 ~ 11/15", "in_progress": False})
        self.assertEqual(a["nav"], {"prev": "2026-11-02", "next": "2026-11-16"})
        self.assertEqual(a["report"]["review_count"], 3)
        self.assertEqual(first.headers["cache-control"], "no-store")
        call = self.fake.calls("weekly")[-1]["params"]
        self.assertEqual((call["store_id"], call["visitor_id"], call["week"], call["now"]),
                         ("store_ongi", self.me, "2026-11-09", "2026-11-20T15:00:00+09:00"))
        row = self.storage.reports.get("store_ongi", "weekly", "2026-11-09", "2026-11-15", visitor_id=self.me)
        self.assertEqual((row["prompt_version"], row["numbers"]["version"], row["numbers"]["report"]["review_count"]),
                         (REPORT_VERSION, BUNDLE_VERSION, 3))
        self.assertIn("답글이 없어요", row["body_text"])
        self.assertEqual(row["evidence_ids"], ["iss_missing_item"])

        self.fake.reviews = 9                       # 서비스 값이 바뀌어도 저장본을 준다
        before = len(self.fake.calls())
        b = self.client.get("/api/reports/weekly", params={"period": "2026-11-12"}).json()     # 같은 주의 다른 날
        self.assertEqual((b["made_now"], b["report"]["review_count"], b["created_at"]), (False, 3, a["created_at"]))
        self.assertIsNone(b["stale"])               # 기간이 끝난 뒤 만든 저장본: 다시 계산하지 않음
        self.assertEqual(len(self.fake.calls()), before)

    def test_regenerate_overwrites_the_saved_report(self):
        a = self.client.get("/api/reports/monthly", params={"period": "2026-10"}).json()
        self.assertEqual(self.fake.calls("monthly")[-1]["params"]["compare"], "true")
        self.fake.reviews = 7
        self.app.state.reports.clock = lambda: NOW + timedelta(hours=2)
        r = self.client.post("/api/reports/monthly/regenerate", params={"period": "2026-10"})
        self.assertEqual(r.status_code, 200, r.text)
        b = r.json()
        self.assertEqual((b["made_now"], b["report"]["review_count"], b["saved"]), (True, 7, True))
        self.assertNotEqual(b["created_at"], a["created_at"])
        again = self.client.get("/api/reports/monthly", params={"period": "2026-10"}).json()
        self.assertEqual((again["made_now"], again["report"]["review_count"], again["created_at"]), (False, 7, b["created_at"]))
        items = self.client.get("/api/reports/saved").json()["items"]
        self.assertEqual([(i["kind"], i["key"]) for i in items], [("monthly", "2026-10")])

    def test_in_progress_report_tells_when_it_is_stale(self):
        a = self.client.get("/api/reports/weekly").json()            # 이번 주 (진행 중)
        self.assertEqual((a["period"]["key"], a["period"]["in_progress"], a["made_now"]), ("2026-11-16", True, True))
        b = self.client.get("/api/reports/weekly").json()
        self.assertEqual(b["stale"], {"checked": True, "is_stale": False, "new_reviews": 0, "reviews_now": 3,
                                      "responses_changed": False, "approvals_changed": False, "period_closed": False})
        self.fake.reviews = 6
        c = self.client.get("/api/reports/weekly").json()
        self.assertEqual((c["report"]["review_count"], c["stale"]["is_stale"], c["stale"]["new_reviews"]), (3, True, 3))
        self.fake.reviews, self.fake.replied = 3, 1                  # 리뷰 수는 같고 답글 기록만 바뀜
        d = self.client.get("/api/reports/weekly").json()["stale"]
        self.assertEqual((d["is_stale"], d["new_reviews"], d["responses_changed"]), (True, 0, True))
        self.fake.replied = 0
        self.storage.approvals.save("store_ongi", self.me, {"draft_id": "d_r1", "status": "approved", "edited": False, "text": "답글",
                                                             "approved_at": "2026-11-20T10:00:00+09:00", "mode": "mock"},
                                    kind="reply_draft")
        e = self.client.get("/api/reports/weekly").json()
        self.assertEqual((e["stale"]["approvals_changed"], e["approvals"]["total"]), (True, 0))   # 저장본의 숫자는 그대로
        # 기간이 끝난 뒤 열면: 끝나기 전에 만든 저장본이라 낡음
        self.storage.approvals.clear("store_ongi", self.me)
        self.app.state.reports.clock = lambda: datetime(2026, 11, 23, 9, tzinfo=KST)
        f = self.client.get("/api/reports/weekly", params={"period": "2026-11-16"}).json()
        self.assertEqual((f["made_now"], f["stale"]["period_closed"], f["stale"]["is_stale"]), (False, True, True))
        self.assertEqual(f["period"]["in_progress"], False)
        # 서비스가 꺼져 있어도 저장본은 보이고, 낡았는지는 확인하지 못했다고 한다
        self.fake.mode = "down"
        g = self.client.get("/api/reports/weekly", params={"period": "2026-11-16"})
        self.assertEqual(g.status_code, 200)
        self.assertEqual((g.json()["report"]["review_count"], g.json()["stale"]), (3, {"checked": False}))

    def test_accounts_and_stores_are_kept_apart_and_counted(self):
        other, you = login(self.app)
        self.assertNotEqual(you, self.me)
        self.client.get("/api/reports/weekly", params={"period": "2026-11-09"})
        self.fake.reviews = 5
        mine_for_you = other.get("/api/reports/weekly", params={"period": "2026-11-09"}).json()
        self.assertEqual((mine_for_you["made_now"], mine_for_you["report"]["review_count"]), (True, 5))
        self.assertEqual(self.fake.calls("weekly")[-1]["params"]["visitor_id"], you)
        self.assertEqual(self.client.get("/api/reports/weekly", params={"period": "2026-11-09"}).json()["report"]["review_count"], 3)
        other.post("/api/reports/weekly/regenerate", params={"period": "2026-11-09"})
        self.assertEqual(self.client.get("/api/reports/weekly", params={"period": "2026-11-09"}).json()["report"]["review_count"], 3)

        self.client.get("/api/reports/monthly", params={"period": "2026-10"})
        self.assertEqual(self.client.post("/api/auth/store", json={"store_id": "store_basak"}).status_code, 200)
        self.assertEqual(self.client.get("/api/reports/saved").json(), {"storage": "saved", "items": []})
        self.client.get("/api/reports/weekly", params={"period": "2026-11-02"})
        self.assertEqual(self.fake.calls("weekly")[-1]["params"]["store_id"], "store_basak")
        self.assertEqual(self.client.get("/api/reports/counts").json(), {"storage": "saved", "weekly": 2, "monthly": 1})
        self.assertEqual(other.get("/api/reports/counts").json(), {"storage": "saved", "weekly": 1, "monthly": 0})
        self.client.post("/api/auth/store", json={"store_id": "store_ongi"})
        items = self.client.get("/api/reports/saved").json()["items"]
        self.assertEqual([(i["kind"], i["key"], i["label"], i["range"]) for i in items],
                         [("weekly", "2026-11-09", "11월 2주", "11/9 ~ 11/15"), ("monthly", "2026-10", "2026년 10월", "10/1 ~ 10/31")])
        self.assertTrue(all(i["created_at"].endswith("+09:00") for i in items))
        # 계정 초기화 자리: 이 사장님 것만 지움
        self.assertEqual(self.app.state.reports.erase(["store_ongi", "store_basak"], self.me), 3)
        self.assertEqual(self.client.get("/api/reports/counts").json()["weekly"], 0)
        self.assertEqual(other.get("/api/reports/counts").json()["weekly"], 1)
        with self.assertRaises(ValueError):
            self.app.state.reports.erase(["store_ongi"], "common")

    def test_approved_posts_are_counted_by_period_and_kind(self):
        rows = [("d_reply1", "reply_draft", None, "2026-11-10T09:00:00+09:00"), ("d_reply2", "reply_draft", None, "2026-11-15T23:30:00+09:00"),
                ("d_notice", "prevention_notice", None, "2026-11-11T12:00:00+09:00"), ("mkt-abc", "쿠폰 글", "marketing", "2026-11-12T12:00:00+09:00"),
                ("d_promo", "coupon_promo", None, "2026-11-13T12:00:00+09:00"), ("d_old", "reply_draft", None, "2026-11-08T23:59:00+09:00"),
                ("d_next", "reply_draft", None, "2026-11-16T00:10:00+09:00")]
        for draft, kind, card, at in rows:
            self.storage.approvals.save("store_ongi", self.me, {"draft_id": draft, "status": "approved", "edited": False, "text": "글",
                                                                 "approved_at": at, "mode": "mock"}, kind=kind, card_id=card)
        r = self.client.get("/api/reports/weekly", params={"period": "2026-11-09"}).json()
        self.assertEqual(r["approvals"], {"total": 5, "reply": 2, "notice": 1, "promo": 2, "other": 0})
        self.assertEqual(r["marketing"], {"promo_approved": 2, "coupon_usage_rate": None, "ad_cost_per_order": None,
                                          "notice_recurrence": None})


class WithPostgres(unittest.TestCase):
    """같은 흐름을 PostgreSQL 저장소로 (TEST_DB_* 가 없으면 건너뜀)."""

    def setUp(self):
        from shared.storage.testing import open_test_db
        self.db = open_test_db()
        if self.db is None:
            self.skipTest("TEST_DB_HOST 없음 (PostgreSQL 시험은 건너뜀)")
        self.addCleanup(self.db.close)
        self.app, self.fake, self.demo, _ = build(storage=self.db)

    def test_open_save_reopen_regenerate_count_erase(self):
        client, me = login(self.app)
        other, you = login(self.app)
        a = client.get("/api/reports/weekly", params={"period": "2026-11-09"}).json()
        self.assertEqual((a["made_now"], a["saved"], a["created_at"]), (True, True, "2026-11-20T15:00:00+09:00"))
        other.get("/api/reports/weekly", params={"period": "2026-11-09"})
        self.fake.reviews = 8
        b = client.get("/api/reports/weekly", params={"period": "2026-11-09"}).json()
        self.assertEqual((b["made_now"], b["report"]["review_count"]), (False, 3))
        self.app.state.reports.clock = lambda: NOW + timedelta(minutes=5)
        c = client.post("/api/reports/weekly/regenerate", params={"period": "2026-11-09"}).json()
        self.assertEqual((c["report"]["review_count"], c["created_at"]), (8, "2026-11-20T15:05:00+09:00"))
        self.assertEqual(other.get("/api/reports/weekly", params={"period": "2026-11-09"}).json()["report"]["review_count"], 3)
        self.assertEqual(client.get("/api/reports/counts").json(), {"storage": "saved", "weekly": 1, "monthly": 0})
        self.assertEqual([i["key"] for i in client.get("/api/reports/saved").json()["items"]], ["2026-11-09"])
        self.assertEqual(self.app.state.reports.erase(["store_ongi", "store_basak", "store_mongle"], me), 1)
        self.assertEqual(client.get("/api/reports/counts").json()["weekly"], 0)
        self.assertEqual(other.get("/api/reports/counts").json()["weekly"], 1)
        self.app.state.reports.erase(["store_ongi"], you)

    def test_account_reset_and_withdraw_erase_saved_reports(self):
        """계정 초기화·탈퇴는 그 사장님이 저장한 보고서도 지운다 (다른 사장님 것은 그대로)."""
        client, me = login(self.app)
        other, you = login(self.app)
        client.get("/api/reports/weekly", params={"period": "2026-11-09"})
        client.get("/api/reports/monthly", params={"period": "2026-10"})
        other.get("/api/reports/weekly", params={"period": "2026-11-09"})
        self.assertEqual(client.get("/api/reports/counts").json()["weekly"], 1)
        res = client.post("/api/auth/reset", json={"scope": "store"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(client.get("/api/reports/counts").json(), {"storage": "saved", "weekly": 0, "monthly": 0})
        self.assertEqual(other.get("/api/reports/counts").json()["weekly"], 1)
        res = other.post("/api/auth/withdraw", json={})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.app.state.reports.storage.reports.list("store_ongi", visitor_id=you), [])


class Guests(unittest.TestCase):
    def test_a_guest_gets_a_computed_report_that_is_not_saved(self):
        app, fake, demo, storage = build()
        client = TestClient(app)
        a = client.get("/api/reports/weekly", params={"period": "2026-11-09"}).json()
        self.assertEqual((a["storage"], a["saved"], a["made_now"]), ("guest", False, True))
        visitor = client.cookies["visitor_id"]
        self.assertEqual(fake.calls("weekly")[-1]["params"]["visitor_id"], visitor)
        self.assertEqual(storage.reports.list("store_ongi", visitor_id=visitor), [])
        self.assertEqual(client.post("/api/reports/weekly/regenerate", params={"period": "2026-11-09"}).json()["saved"], False)
        self.assertEqual(storage.reports.list("store_ongi", visitor_id=visitor), [])
        client.get("/api/reports/weekly", params={"period": "2026-11-09"})
        self.assertEqual(len(fake.calls("weekly")), 3)             # 저장본이 없으니 열 때마다 계산
        self.assertEqual(client.get("/api/reports/saved").json(), {"storage": "guest", "items": []})
        self.assertEqual(client.get("/api/reports/counts").json(), {"storage": "guest", "weekly": 0, "monthly": 0})


class Failures(unittest.TestCase):
    def setUp(self):
        self.app, self.fake, self.demo, self.storage = build()
        self.client, self.me = login(self.app)

    def test_errors_have_the_care_shape_and_never_500(self):
        r = self.client.get("/api/reports/weekly", params={"period": "2026-11-30"})
        self.assertEqual((r.status_code, r.json()["error"]["state"]), (400, "invalid"))
        self.assertEqual(r.json()["error"]["message"], "아직 오지 않은 기간이에요.")
        self.assertEqual(self.client.get("/api/reports/monthly", params={"period": "11월"}).status_code, 400)
        self.assertEqual(self.client.get("/api/reports/daily").status_code, 422)      # 일일은 저장하지 않는다
        self.fake.mode = "down"
        d = self.client.get("/api/reports/weekly", params={"period": "2026-11-09"})
        self.assertEqual((d.status_code, d.json()["error"]["state"]), (503, "down"))
        self.assertEqual(self.storage.reports.list("store_ongi", visitor_id=self.me), [])

    def test_storage_outage_still_shows_the_computed_report(self):
        class Broken:
            def __getattr__(self, name):
                def fail(*a, **k):
                    raise RuntimeError("DB 에 닿지 못함")
                return fail
        self.app.state.reports.storage = type("S", (), {"reports": Broken()})()
        r = self.client.get("/api/reports/weekly", params={"period": "2026-11-09"}).json()
        self.assertEqual((r["storage"], r["saved"], r["report"]["review_count"]), ("unavailable", False, 3))
        self.assertEqual(self.client.get("/api/reports/saved").json(), {"storage": "unavailable", "items": []})
        self.assertEqual(self.client.get("/api/reports/counts").json(), {"storage": "unavailable", "weekly": None, "monthly": None})


if __name__ == "__main__":
    unittest.main()
