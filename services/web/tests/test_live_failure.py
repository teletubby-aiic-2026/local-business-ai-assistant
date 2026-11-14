"""실시간(live) 글 생성이 HCX 문제로 실패해도 서버가 500 을 내지 않는지 본다 — CLOVA·네트워크를 부르지 않는다.

실행 (services/web 에서): PYTHONPATH=<저장소 루트> python -m pytest -q tests/test_live_failure.py
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from web.demo import Demo
from web.generate import ensure_marketing_on_path
from web.main import create_app

from tests.test_web import HAS_C6, MARKETING, FakeSource, settings


@unittest.skipUnless(HAS_C6, "MARKETING_DIR(C6 저장본) 없음")
class LiveFailure(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        ensure_marketing_on_path(MARKETING)
        demo = Demo(settings(self.tmp, mode="live", clova_key="test-key"), source=FakeSource(),
                    reason_model=lambda system, user: "")
        self.client = TestClient(create_app(demo))
        cards = self.client.get("/api/cards").json()["cards"]
        self.complaint = next(c["card"]["card_id"] for c in cards if c["card"]["kind"] == "complaint")
        self.promo = next(c["card"]["card_id"] for c in cards if c["card"]["kind"] == "promo")

    def test_unexpected_error_becomes_a_screen_alert_not_a_500(self):
        with mock.patch("web.demo.run_live", side_effect=TimeoutError("The read operation timed out")):
            res = self.client.post(f"/api/cards/{self.complaint}/run")
        self.assertEqual(res.status_code, 502)
        message = res.json()["error"]["message"]
        self.assertIn("다시 눌러", message)
        self.assertNotIn("TimeoutError", message)         # 내부 오류 이름을 화면에 내지 않는다

    def test_hcx_down_for_every_call_still_returns_drafts_for_the_owner_to_fix(self):
        failing = {"error": "TimeoutError: The read operation timed out"}
        with mock.patch("clova.call", side_effect=lambda *a, **k: dict(failing)) as call:
            res = self.client.post(f"/api/cards/{self.complaint}/run")
        self.assertEqual(res.status_code, 200)
        made = res.json()
        self.assertEqual(made["source"], "live")
        self.assertTrue(made["drafts"])
        for d in made["drafts"]:
            self.assertTrue(d["needs_input"], d["generator"])        # 화면에 '확인 필요'
            self.assertIn("죄송", d["text"])                          # 기본 문장
            self.assertEqual(d["failed_reasons"], [])
        self.assertLessEqual(call.call_count, len(made["drafts"]) + 1)   # 다시 쓰기·재시도 폭주 없음

    def test_promo_with_hcx_down_keeps_the_coupon_line(self):
        with mock.patch("clova.call", side_effect=lambda *a, **k: {"error": "HTTP 503: down"}):
            res = self.client.post(f"/api/cards/{self.promo}/run")
        self.assertEqual(res.status_code, 200)
        draft = res.json()["drafts"][0]
        self.assertTrue(draft["needs_input"])
        self.assertIn("쿠폰", draft["text"])

    def test_a_healthy_run_is_unchanged(self):
        body = "주문하신 메뉴가 빠져서 정말 죄송해요. 앞으로 더 꼼꼼히 챙겨 볼게요. 소중한 리뷰 감사해요."
        with mock.patch("clova.call", side_effect=lambda *a, **k: {"content": body, "won": 0.01}):
            res = self.client.post(f"/api/cards/{self.complaint}/run")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["drafts"])


if __name__ == "__main__":
    unittest.main()
