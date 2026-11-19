"""'AI에게 묻기' 서랍을 전 파트로 (5차 회의 11/18). 가짜 상권 서비스·가짜 리뷰 분석, 네트워크·HCX 없음.

- 상권 질문은 예전처럼 상권 서비스로 가고, 답에 '상권 분석 표·차트 보기'(navigate market) 버튼이 붙는다.
- 고객응대·마케팅·리포트 질문은 이 서버가 지금 가게의 현황 1~2줄과 그 화면으로 가는 버튼(payload.type navigate)으로 답한다.
  상권 서비스는 부르지 않는다. 상권 서비스가 꺼져 있어도 답한다.
- 가게 기본 질문(이름·메뉴·화면 위치)은 예전 그대로.

실행 (services/web 에서):  env -u APP_MODE PYTHONPATH=../.. python -m pytest -q tests/test_assistant_domains.py
"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from shared.storage import MemoryStore
from tests.test_assistant_proxy import FakeMarket
from tests.test_auth_stores import REPO, RecordingSource
from tests.test_web import settings
from web import assistant_proxy as ap
from web.assistant_proxy import AssistantProxy, MarketClient, domain_question, marketing_sub
from web.auth import AuthService
from web.demo import Demo
from web.main import create_app

CARE = ["불만 리뷰 제일 많은 게 뭐야?", "진상 별점 테러 답글 어떻게 달아?", "캡처 사진 올리고 싶어", "억울한 리뷰 답글 써줘"]
MARKETING = ["쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?", "남은 재료 묶어서 팔고 싶어", "배달앱 광고비 괜찮은지 봐줘",
             "가게 이야기 소개글 써줘", "지난 쿠폰 사용률 어때?", "칭찬 리뷰로 홍보글 쓰고 싶어"]
REPORT = ["이번 달 응대 점수 알려줘", "월간 보고서 PDF로 받고 싶어", "리포트 보여줘"]
MARKET = ["우리 상권 매출 어때?", "주변에 같은 업종 점포는 몇 개야?", "유동인구 많은 시간대는?", "요즘 장사 어때?",
          "저녁 매출 전년보다 어때?", "근처 상권 광고 많이 해?"]


def build(market: FakeMarket | None = None, *, proxy: AssistantProxy | None = None):
    tmp = Path(tempfile.mkdtemp())
    market = market or FakeMarket()
    proxy = proxy or AssistantProxy(MarketClient("http://market.test", ap.DEFAULT_HOST, read_timeout=5.0,
                                                 transport=httpx.MockTransport(market)))
    storage = MemoryStore()
    # 실제 상권 지표 파일 (온기한식 저녁 17~24시 공통 업종 -19.31%). 시험용 옛 지표(하루 전체)는 쓰지 않는다
    demo = Demo(settings(tmp, snapshot_path=REPO / "data" / "scenario" / "snapshot_2026Q2.json"), source=RecordingSource(), storage=storage)
    return TestClient(create_app(demo, assistant=proxy, auth=AuthService(storage))), market


def ask(client, text):
    res = client.post("/api/assistant/messages", json={"text": text})
    assert res.status_code == 200, res.text
    return res.json()


def routes(data):
    return [(a["payload"]["route"], a["payload"].get("sub")) for a in data["reply"]["actions"] if a["payload"].get("type") == "navigate"]


class Classify(unittest.TestCase):
    def test_table(self):
        for q in CARE:
            self.assertEqual(domain_question(q), "care", q)
        for q in MARKETING:
            self.assertEqual(domain_question(q), "marketing", q)
        for q in REPORT:
            self.assertEqual(domain_question(q), "report", q)
        for q in MARKET:
            self.assertIsNone(domain_question(q), q)        # 상권 자료 낱말이 있으면 상권 서비스

    def test_marketing_modes(self):
        self.assertEqual([marketing_sub(q) for q in MARKETING], ["promo", "leftover", "ad", "story", "repeat", "promo"])
        self.assertEqual(set(ap.MKT_SUBS), {"promo", "leftover", "ad", "story", "repeat"})


class Answers(unittest.TestCase):
    def setUp(self):
        self.client, self.market = build()

    def market_calls(self):
        return [r for r in self.market.requests if r["path"] == "/api/assistant/messages"]

    def test_care_question_gets_store_status_and_deep_links_without_the_market_service(self):
        data = ask(self.client, "불만 리뷰 제일 많은 게 뭐야?")
        reply = data["reply"]
        self.assertEqual((reply["kind"], data["answered_by"], data["classification"]["domain"]), ("care_guide", "web_domain", "customer"))
        self.assertIn("온기한식: 리뷰 40건 중 불만 12건", reply["text"])
        self.assertIn("포장 누락", reply["text"])
        self.assertEqual(routes(data), [("cards", None), ("analysis", "paste"), ("analysis", "issues")])
        self.assertEqual(self.market_calls(), [])

    def test_unfair_and_capture_tips(self):
        self.assertIn("사과 없이", ask(self.client, "진상 별점 테러 답글 어떻게 달아?")["reply"]["text"])
        self.assertIn("캡처", ask(self.client, "캡처 사진 올리고 싶어")["reply"]["text"])

    def test_marketing_question_names_the_praised_menu_and_the_evening_figure(self):
        data = ask(self.client, "쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?")
        text = data["reply"]["text"]
        self.assertEqual(data["reply"]["kind"], "marketing_guide")
        self.assertIn("저녁 시간대(17~24시) 추정매출(두 분기 공통 업종)은 전년 같은 분기보다 19.31% 줄었어요", text)
        self.assertIn("본전", text)
        self.assertEqual(routes(data), [("marketing", "promo"), ("cards", None)])
        leftover = ask(self.client, "남은 재료 묶어서 팔고 싶어")
        self.assertEqual(routes(leftover)[0], ("marketing", "leftover"))
        self.assertIn(("marketing", "promo"), routes(leftover))
        self.assertEqual(routes(ask(self.client, "배달앱 광고비 괜찮은지 봐줘"))[0], ("marketing", "ad"))
        self.assertEqual(self.market_calls(), [])

    def test_report_question(self):
        data = ask(self.client, "이번 달 응대 점수 알려줘")
        self.assertEqual((data["reply"]["kind"], routes(data)), ("report_guide", [("report", None)]))
        self.assertIn("PDF", data["reply"]["text"])

    def test_market_question_still_goes_to_the_market_service_and_gets_a_chart_button(self):
        data = ask(self.client, "우리 상권 매출 어때?")
        self.assertEqual(len(self.market_calls()), 1)
        self.assertEqual(data["reply"]["kind"], "data_answer")
        self.assertEqual(routes(data), [("market", None)])

    def test_store_questions_are_unchanged(self):
        self.assertEqual(ask(self.client, "우리 가게 메뉴 뭐야?")["reply"]["kind"], "store_profile")
        where = ask(self.client, "리뷰 어디서 봐?")["reply"]
        self.assertEqual((where["kind"], where["actions"]), ("store_guide", []))
        # 화면 위치 안내에 새 메뉴가 있고, 예전 '리뷰 내용은 여기서 답하지 않아요'는 없다 (서랍이 이제 리뷰 질문에도 답함)
        self.assertIn(f"'{ap.MARKET_SCREEN}'", where["text"])
        self.assertNotIn("답하지 않아요", where["text"])
        html = (Path(ap.__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
        link = re.search(r'<a href="#/market" data-route="market">([\s\S]*?)</a>', html).group(1)
        self.assertEqual(re.sub(r"\s+", " ", re.sub(r"<svg[\s\S]*?</svg>|<[^>]+>", "", link)).strip(), ap.MARKET_SCREEN)   # 메뉴 글자와 같다
        self.assertEqual(self.market_calls(), [])

    def test_domain_answers_work_while_the_market_service_is_off(self):
        client, _ = build(proxy=AssistantProxy(None))
        self.assertEqual(ask(client, "불만 리뷰 제일 많은 게 뭐야?")["reply"]["kind"], "care_guide")
        res = client.post("/api/assistant/messages", json={"text": "우리 상권 매출 어때?"})
        self.assertEqual(res.json()["error"]["state"], "off")        # 상권 질문은 예전처럼 꺼짐 안내

    def test_answers_follow_the_active_store(self):
        self.client.post("/api/auth/demo-login")
        self.client.post("/api/auth/store", json={"store_id": "store_basak"})
        self.assertTrue(ask(self.client, "불만 리뷰 제일 많은 게 뭐야?")["reply"]["text"].startswith("바삭치킨:"))
        text = ask(self.client, "쿠폰 홍보하고 싶어")["reply"]["text"]
        self.assertIn("16.58%", text)
        self.assertIn("상도역 5번", text)


if __name__ == "__main__":
    unittest.main()
