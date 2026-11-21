"""서랍의 마케팅 질문 → 맞춤 마케팅 서비스의 질문 답하기(POST /api/marketing-survey/ask, 11/21).

예전에는 마케팅 질문 9개 중 5개가 같은 안내 한 줄을 받았다. 이제 마케팅 서비스가 보고서·쿠폰 계산·광고 판정으로 만든 근거 카드와
답을 주고, 이 서버는 고객응대와 같은 모양(assistant-reply-v1)으로 바꾸고 질문 종류에 맞는 맞춤 마케팅 버튼을 붙인다.
- 그 가게 마케팅 프록시로 묻고, 쿼리 store·visitor_id 는 이 서버가 붙인다 (본문은 질문만)
- 마케팅 서비스가 꺼져 있거나 /ask 가 없는 예전 판이면 예전 안내 그대로
- 홍보 글을 '써 달라'는 말은 예전처럼 맞춤 마케팅 화면 안내
실행 (services/web 에서):  env -u APP_MODE PYTHONPATH=../.. python -m pytest -q tests/test_assistant_marketing_ask.py
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from shared.storage import MemoryStore
from tests.test_assistant_domains import ask, routes
from tests.test_assistant_proxy import FakeMarket
from tests.test_auth_stores import REPO, RecordingSource
from tests.test_web import settings
from web import assistant_proxy as ap
from web.assistant_proxy import AssistantProxy, MarketClient
from web.auth import AuthService
from web.demo import Demo
from web.main import create_app
from web.marketing_proxy import MarketingProxy

CARDS = [{"id": "F1", "topic": "쿠폰 계산", "status": "available", "text": "할인 2,000원 쿠폰을 예산 100,000원으로 낼 때예요.",
          "values": [{"label": "본전 주문 수", "value": 23, "unit": "건"}], "warnings": ["예산은 가정한 값이에요."], "source_ref": {}}]


class FakeMarketing:
    def __init__(self, down: bool = False, missing: bool = False):
        self.requests: list[dict] = []
        self.down, self.missing = down, missing

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("down", request=request)
        body = json.loads(request.content) if request.content else None
        self.requests.append({"path": request.url.path, "params": dict(request.url.params), "body": body})
        if request.url.path != "/api/marketing-survey/ask" or self.missing:
            return httpx.Response(404, json={"detail": "Not Found"})
        intent = "ads" if "광고" in body["text"] else "coupon_calc"
        return httpx.Response(200, json={
            "text": f"[{intent}] 쿠폰 주문이 23건 넘으면 본전이에요 [F1].", "intent": intent, "cards": CARDS,
            "suggestions": ["지난번 쿠폰 효과 있었어?", "배달앱 광고비 괜찮아?", "셋째"], "method": "template", "model": None,
            "demo": True, "checks": [], "classified_by": "rules", "rule_intent": intent, "plan_note": None, "notes": []})


def build(marketing: FakeMarketing):
    tmp = Path(tempfile.mkdtemp())
    market = FakeMarket()
    proxy = AssistantProxy(MarketClient("http://market.test", ap.DEFAULT_HOST, read_timeout=5.0, transport=httpx.MockTransport(market)))
    storage = MemoryStore()
    demo = Demo(settings(tmp, snapshot_path=REPO / "data" / "scenario" / "snapshot_2026Q2.json"), source=RecordingSource(), storage=storage)
    mkt = MarketingProxy("http://marketing.test", transport=httpx.MockTransport(marketing))
    return TestClient(create_app(demo, assistant=proxy, auth=AuthService(storage), marketing=mkt)), market


class MarketingAsk(unittest.TestCase):
    def setUp(self):
        self.mkt = FakeMarketing()
        self.client, self.market = build(self.mkt)

    def test_marketing_question_is_answered_with_cards(self):
        data = ask(self.client, "쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?")
        reply = data["reply"]
        self.assertEqual((reply["kind"], data["answered_by"], data["classification"]["domain"]),
                         ("marketing_answer", ap.MKT_ANSWER, "marketing"))
        self.assertTrue(reply["text"].startswith("[coupon_calc]"))
        self.assertEqual(([c["id"] for c in data["cards"]], reply["cited"]), (["F1"], ["F1"]))
        self.assertEqual(reply["suggestions"], ["지난번 쿠폰 효과 있었어?", "배달앱 광고비 괜찮아?", ap.BACK_TO_MARKET[0]])
        self.assertEqual(routes(data), [("marketing", "promo"), ("marketing", "repeat")])
        sent = self.mkt.requests[-1]
        self.assertEqual(sent["body"], {"text": "쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?"})
        self.assertEqual(sent["params"]["store"], "store_ongi")
        self.assertRegex(sent["params"].get("visitor_id", ""), r"^[A-Za-z0-9_-]{1,64}$")
        self.assertEqual([r for r in self.market.requests if r["path"] == "/api/assistant/messages"], [])

    def test_buttons_follow_the_question_type(self):
        self.assertEqual(routes(ask(self.client, "배달앱 광고비 괜찮아?")), [("marketing", "ad")])

    def test_write_requests_keep_the_guide(self):
        data = ask(self.client, "신메뉴 홍보 문구 써줘")
        self.assertEqual(data["reply"]["kind"], "marketing_guide")
        self.assertFalse(any(r["path"].endswith("/ask") for r in self.mkt.requests))

    def test_service_down_or_old_falls_back_to_the_guide(self):
        for fake in (FakeMarketing(down=True), FakeMarketing(missing=True)):
            client, _ = build(fake)
            self.assertEqual(ask(client, "쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?")["reply"]["kind"], "marketing_guide")

    def test_every_intent_has_buttons(self):
        for intent in ("coupon_calc", "coupon_result", "ads", "notice_effect", "activity", "next", "ideas_new", "ideas_repeat",
                       "ideas_value", "rainy", "leftover", "menu_price", "overview"):
            self.assertTrue(ap.MKT_ACTIONS[intent], intent)


if __name__ == "__main__":
    unittest.main()
