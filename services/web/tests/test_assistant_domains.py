"""'AI에게 묻기' 서랍을 전 파트로 (5차 회의 11/18). 가짜 상권 서비스·가짜 리뷰 분석, 네트워크·HCX 없음.

- 상권 질문은 예전처럼 상권 서비스로 가고, 답에 '상권 분석 표·차트 보기'(navigate market) 버튼이 붙는다.
- 고객응대·마케팅·리포트 질문은 이 서버가 지금 가게의 현황 1~2줄과 그 화면으로 가는 버튼(payload.type navigate)으로 답한다.
  상권 서비스는 부르지 않는다. 상권 서비스가 꺼져 있어도 답한다.
- 가게 기본 질문(이름·메뉴·화면 위치)은 예전 그대로.
- 화면(React, services/web/frontend/src)과 맞물리는 이름: #/market 메뉴 글자(Sidebar.jsx)·맞춤 마케팅 시작 모드(marketing/logic.js MKT_SUB).

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
from tests import frontend_src as fs
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

    def test_marketing_modes_match_the_screen(self):
        """서랍 버튼의 sub(promo …)로 맞춤 마케팅 화면이 고르는 시작 모드 글자가 서버 MKT_SUBS 와 같다 (11/20 React 전환 때
        test_post_m5_ui_static.py 에서 옮김). 글자는 마케팅 서비스(flow.py START_MODES)가 주는 보기 이름이라 화면 문구와 따로 바꿀 수 없다."""
        logic = fs.read("features/marketing/logic.js")
        where = "frontend/src/features/marketing/logic.js"
        self.assertEqual(fs.object_pairs(fs.const_value(logic, "MKT_SUB", where)), ap.MKT_SUBS,
                         "화면 MKT_SUB 와 assistant_proxy.MKT_SUBS 가 달라요 (서랍의 '맞춤 마케팅: …' 버튼이 다른 모드를 열게 됨)")
        modes = fs.object_keys(fs.const_value(logic, "MKT_MODES", where))   # 시작 모드 카드 (보기 글자 → 설명)
        for label in ap.MKT_SUBS.values():
            self.assertIn(label, modes, f"화면 MKT_MODES 에 시작 모드 '{label}' 가 없어요")


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

    def test_marketing_answer_leads_with_the_question_and_keeps_the_praise_line_for_coupon_questions(self):
        """11/21: 남은 재료를 물으면 칭찬 메뉴 문장 없이 그 기능 안내가 먼저. 쿠폰을 물으면 안내 다음에 카드 ⓑ 근거."""
        leftover = ask(self.client, "남은 재료 묶어서 팔고 싶어")["reply"]["text"]
        self.assertTrue(leftover.startswith("맞춤 마케팅의 '남은 재료 팔기'"), leftover)
        self.assertNotIn("칭찬 리뷰", leftover)
        coupon = ask(self.client, "쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?")["reply"]["text"].split("\n")
        self.assertTrue(coupon[0].startswith("쿠폰 할인액"), coupon)
        self.assertIn("19.31%", coupon[1])

    def test_store_without_a_coupon_card_gets_no_card_button_and_no_card_sentence(self):
        """11/21: 쿠폰 홍보 카드(ⓑ)가 없는 가게(새로 등록한 가게)에 '추천 카드 ⓑ' 버튼과 '불러오지 못했어요'·칭찬 문장이 나왔다."""
        from unittest import mock
        with mock.patch.object(AssistantProxy, "_has_coupon_card", return_value=False):
            for q in ("쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?", "남은 재료 묶어서 팔고 싶어", "쿠폰 홍보하고 싶어"):
                with self.subTest(q=q):
                    data = ask(self.client, q)
                    self.assertNotIn(("cards", None), routes(data))
                    self.assertNotIn("칭찬 리뷰", data["reply"]["text"])
                    self.assertNotIn("불러오지 못했어요", data["reply"]["text"])
                    self.assertEqual(routes(data)[0][0], "marketing")

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
        where = ask(self.client, "리뷰 어디서 봐?")
        self.assertEqual(routes(where), [("analysis", "summary"), ("cards", None)])     # 화면 위치 답에는 그 화면으로 가는 버튼 (11/20)
        where = where["reply"]
        self.assertEqual(where["kind"], "store_guide")
        # 화면 위치 안내에 새 메뉴가 있고, 예전 '리뷰 내용은 여기서 답하지 않아요'는 없다 (서랍이 이제 리뷰 질문에도 답함)
        self.assertIn(f"'{ap.MARKET_SCREEN}'", where["text"])
        self.assertNotIn("답하지 않아요", where["text"])
        menu = fs.sidebar_menu()                                     # frontend/src/components/Sidebar.jsx 왼쪽 메뉴 {주소: 글자}
        self.assertEqual(menu.get("market"), ap.MARKET_SCREEN,       # #/market 메뉴 글자와 같다
                         f"Sidebar.jsx 의 #/market 메뉴 글자({menu.get('market')!r})가 assistant_proxy.MARKET_SCREEN 과 달라요 (같이 고칠 것)")
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

    def test_where_buttons_follow_the_first_sentence(self):
        """화면 위치 답의 버튼은 첫 문장과 같은 분기에서 고른다 (11/20)."""
        flow = [("cards", None), ("draft", None), ("done", None)]
        for text, first, wanted in (
                ("리뷰 답글은 어디서 봐?", "리뷰 답글 초안은", flow), ("공지 어디서 써?", "포장·주문 안내문 초안은", flow),
                ("승인한 글 어디서 확인해?", "글 초안은", flow),
                ("홍보글 어디서 확인해?", "홍보·쿠폰·광고비는", [("marketing", "promo"), ("cards", None)]),
                ("종합 리포트 어디 있어?", "응대 점수와 월간 보고서는", [("report", None)]),
                ("리뷰 보여줘", "리뷰와 불만 묶음은", [("analysis", "summary"), ("cards", None)])):
            with self.subTest(text=text):
                data = ask(self.client, text)
                self.assertTrue(data["reply"]["text"].startswith(first), data["reply"]["text"])
                self.assertEqual(routes(data), wanted)
        self.assertEqual(self.market_calls(), [])


# ── 11/20 서랍 의도 라우팅 (어순·추천 카드·되묻기·마케팅 승인) ──────────────────────────
CARDS_ASK = ["오늘 추천 카드 있어?", "오늘 할 일 뭐야?", "승인 대기 글 있어?", "오늘 브리핑 해줘"]
HELP_ASK = ["우리 가게", "뭐 물어볼 수 있어?", "도와줘", "저희 매장요", "도움말"]


class NewRouting(unittest.TestCase):
    def test_cards_and_help_questions(self):
        for q in CARDS_ASK:
            self.assertEqual((ap.store_question(q), domain_question(q)), (None, "cards"), q)
        for q in HELP_ASK:
            self.assertEqual((ap.store_question(q), domain_question(q)), (None, "help"), q)
        # '추천'·'카드' 하나만으로는 cards 가 아니다. 상권 자료 낱말이 섞이면 상권 서비스
        for q in ("메뉴 추천해줘", "카드 결제 많아?", "주변 가게 오늘 할 일", "근처 상권 추천 카드 있어?", "우리 가게 이름 뭐야?"):
            self.assertNotIn(domain_question(q), ("cards", "help"), q)

    def test_what_first_questions_go_to_cards(self):
        """11/22 QA: '오늘 뭐부터 할까요?'가 상권 서비스로 가서 매출 순위로 답했다. 무엇부터 할지 묻는 말은 오늘 할 일(cards)."""
        for q in ("오늘 뭐부터 할까요?", "뭘 먼저 해야 돼?", "먼저 뭐 하면 돼?", "지금 뭐 해야 해?", "오늘 할 거 있어?",
                  "무엇부터 처리할까요"):
            self.assertEqual((ap.store_question(q), domain_question(q)), (None, "cards"), q)
        # 상권 자료를 묻는 말은 그대로 상권 서비스
        for q in ("점심이랑 저녁 중 뭐부터 공략해야 해?", "주변 상권에서 뭐부터 봐야 해?", "매출 높은 시간대부터 뭐 해야 돼?"):
            self.assertIsNone(domain_question(q), q)

    def test_new_marketing_words(self):
        for q in ("인스타 올리고 싶어", "SNS 글 써줘", "블로그에 올릴 글", "네이버 플레이스 소개", "배민 공지 바꾸고 싶어",
                  "신메뉴 홍보하고 싶어", "손님 늘리고 싶어", "단골 늘리는 법"):
            self.assertEqual(domain_question(q), "marketing", q)
        self.assertIsNone(domain_question("근처 상권 광고 많이 해?"))           # 상권 자료 낱말이 먼저

    def test_old_tables_keep_their_classification(self):
        """11/20 새 낱말(cards·help·마케팅)이 예전 표의 분류를 바꾸지 않는다. 상권 질문은 여전히 상권 서비스로 간다."""
        from tests.test_assistant_ux import MARKET_QUESTIONS, STORE_QUESTIONS
        known = {"답글 써줘": "care", "홍보 글 써줘": "marketing", "우리 가게 리뷰 어때?": "care"}      # 11/20 전에도 그랬음
        for q in MARKET_QUESTIONS:
            self.assertEqual(domain_question(q), known.get(q), q)
        for q, kind in STORE_QUESTIONS:
            self.assertEqual(ap.store_question(q), kind, q)               # 가게 질문은 domain_question 보다 먼저 고른다
        starters = fs.strings(fs.const_value(fs.read("features/assistant/chat.js"), "CHAT_STARTERS", "chat.js"))
        self.assertEqual(sorted(str(domain_question(q)) for q in starters), ["None", "None", "None", "care", "marketing", "marketing"])

    def test_new_marketing_words_with_market_words_go_to_the_market_service(self):
        """11/21: 11/20 낱말(인스타·SNS·손님 늘…)에 매출·점심·저녁·시간대·요일·주말·평일이 같이 오면 상권 자료로 답한다.
        11/20 전 낱말만 있는 질문(쿠폰·홍보 …)과 매출 낱말이 없는 질문은 그대로 마케팅."""
        for q in ("손님 늘리려면 점심이 나아 저녁이 나아?", "SNS 홍보하면 매출 늘까?", "인스타 하는 가게 매출 어때?",
                  "블로그 하면 주말 손님 많아?"):
            self.assertIsNone(domain_question(q), q)
            self.assertIsNone(ap.store_question(q), q)
        for q in ("손님 늘리고 싶어", "인스타 올리고 싶어", "쿠폰 하면 매출 늘까?", "저녁 쿠폰 홍보하고 싶어", "홍보 글 써줘"):
            self.assertEqual(domain_question(q), "marketing", q)

    def test_short_place_for_the_setup_label(self):
        """11/21: 서랍이 조건을 맞추는 동안 보이는 이름에 주소 원문 대신 구·도로명·번지만."""
        self.assertEqual(ap.short_place("서울특별시 마포구 와우산로 94 학교법인홍익학원"), "마포구 와우산로 94")
        self.assertEqual(ap.short_place("서울 동작구 장승배기로 161"), "동작구 장승배기로 161")
        self.assertEqual(ap.short_place("서울특별시 강남구 테헤란로8길 12-3 (역삼동)"), "강남구 테헤란로8길 12-3")
        self.assertEqual(ap.short_place("장승배기역"), "장승배기역")

    def test_reordering_runs_once(self):
        """옮긴 글자가 원래 글자와 같아도(우리가게 우리가게) 한 번만 보고 끝난다 (재귀 없음)."""
        for q in ("우리가게 우리가게", "우리 가게 우리 가게 우리 가게", "저희 매장 우리 가게", "가게 가게", "이름 가게 우리 가게"):
            with self.subTest(q=q):
                self.assertIn(ap.store_question(q), (None, "name"))
        self.assertIsNone(ap.store_question("합정역 가게 이름 알려줘"))
        self.assertIsNone(ap.store_question("메뉴 추천해줘 우리 가게"))
        self.assertIsNone(ap.store_question("메뉴 " + "가" * 40 + " 우리 가게"))      # 40자 제한은 그대로


def build_live(model):
    """live 모드 Demo (이유 문장 모델은 가짜). 서랍이 모델을 부르는지 센다."""
    tmp = Path(tempfile.mkdtemp())
    market = FakeMarket()
    proxy = AssistantProxy(MarketClient("http://market.test", ap.DEFAULT_HOST, read_timeout=5.0, transport=httpx.MockTransport(market)))
    demo = Demo(settings(tmp, mode="live", snapshot_path=REPO / "data" / "scenario" / "snapshot_2026Q2.json"),
                source=RecordingSource(), storage=MemoryStore(), reason_model=model)
    return TestClient(create_app(demo, assistant=proxy, auth=AuthService(demo.storage))), market, demo


class CardsAndHelpAnswers(unittest.TestCase):
    def setUp(self):
        self.client, self.market = build()
        self.source = self.client.app.state.demo.source

    def market_calls(self):
        return [r for r in self.market.requests if r["path"] == "/api/assistant/messages"]

    def test_cards_question_lists_todays_cards(self):
        for q in ("오늘 추천 카드 있어?", "오늘 할 일 뭐야?"):
            with self.subTest(q=q):
                data = ask(self.client, q)
                reply = data["reply"]
                self.assertEqual((reply["kind"], data["answered_by"], data["classification"]["domain"]),
                                 ("cards_guide", "web_domain", "customer"))
                lines = reply["text"].split("\n")
                self.assertEqual(lines[0], "온기한식: 오늘 추천 카드는 2장이에요.")
                self.assertTrue(lines[1].startswith("- 포장 누락") and "안내문" in lines[1], lines[1])
                self.assertIn("쿠폰 홍보", lines[2])
                self.assertIsNone(re.search(r"승인 대기 \d|초안 \d+개", reply["text"]))   # 브라우저에만 있는 수는 지어내지 않는다
                self.assertEqual(routes(data), [("cards", None), ("draft", None), ("marketing", "promo")])
                self.assertEqual(reply["suggestions"], ["불만 리뷰 제일 많은 게 뭐야?", "쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?",
                                                        "우리 가게 상권 매출은 어때?"])
        self.assertEqual(self.market.requests, [])

    def test_cards_question_does_not_call_the_model_in_live_mode(self):
        calls = []

        def model(system, user):
            calls.append(user)
            return "포장 누락 불만이 3건, 모두 17~21시에 들어왔어요 [F1]"
        client, market, demo = build_live(model)
        for q in ("오늘 추천 카드 있어?", "오늘 할 일 뭐야?"):
            data = ask(client, q)
            self.assertEqual(data["reply"]["kind"], "cards_guide")
            self.assertIn("오늘 추천 카드는", data["reply"]["text"])
            self.assertEqual(len(routes(data)), 3)
        self.assertEqual(calls, [])                                       # live 에서도 이유 문장 모델을 부르지 않는다
        self.assertEqual(market.requests, [])
        demo.cards()                                                      # 대조: 추천 카드 화면(GET /api/cards)은 이 가짜 모델을 부른다
        self.assertGreater(len(calls), 0)

    def test_cards_answer_when_the_review_service_is_down(self):
        self.client.app.state.demo.source.down = True
        data = ask(self.client, "오늘 할 일 뭐야?")
        self.assertEqual(data["reply"]["kind"], "cards_guide")
        self.assertTrue(data["reply"]["text"].startswith("온기한식의 오늘 추천 카드를 지금 불러오지 못했어요."))
        self.assertEqual(len(routes(data)), 3)
        proxy = AssistantProxy(None)                                      # 가게(Demo)가 붙지 않은 프록시
        self.assertTrue(proxy.domain_answer("cards", "오늘 할 일")["reply"]["text"].startswith("온기한식의 오늘 추천 카드를"))

    def test_help_question_offers_what_can_be_asked_without_looking_anything_up(self):
        for q in ("우리 가게", "뭐 물어볼 수 있어?"):
            with self.subTest(q=q):
                self.source.calls.clear()
                data = ask(self.client, q)
                reply = data["reply"]
                self.assertEqual((reply["kind"], data["classification"]["domain"]), ("help_guide", "general"))
                self.assertEqual(reply["text"], ap.HELP_TEXT)
                self.assertEqual(routes(data), [("cards", None), ("marketing", "promo"), ("analysis", "summary"), ("market", None)])
                self.assertEqual(len(reply["suggestions"]), 3)
                self.assertEqual(self.source.calls, [])                  # 리뷰 분석도 읽지 않는다
        self.assertEqual(self.market.requests, [])
        client, _ = build(proxy=AssistantProxy(None))                     # 상권 서비스가 꺼져 있어도 답한다
        self.assertEqual(ask(client, "우리 가게")["reply"]["kind"], "help_guide")

    def test_reordered_store_questions_are_answered_here(self):
        for q, first in (("메뉴 우리 가게", "우리 가게 메뉴는 6가지예요."), ("이름 우리 가게", "우리 가게 이름은 '온기한식 (가상)'이에요."),
                         ("업종 우리 가게", "우리 가게 업종은 한식음식점이에요."), ("위치 우리 가게", "우리 가게는 장승배기역 4번 상권에 있어요."),
                         ("가격 우리 가게", "우리 가게 메뉴는 6가지예요."), ("우리 가게 가격 알려줘", "우리 가게 메뉴는 6가지예요."),
                         ("김치찌개 얼마야 우리 가게", "우리 가게 메뉴는 6가지예요.")):
            with self.subTest(q=q):
                data = ask(self.client, q)
                self.assertEqual((data["answered_by"], data["reply"]["kind"]), ("store_profile", "store_profile"))
                self.assertEqual(data["reply"]["text"].split("\n")[0], first)
                self.assertEqual(data["reply"]["actions"], [])
        self.assertIn("- 김치찌개 8,000원", ask(self.client, "가격 우리 가게")["reply"]["text"])
        self.assertTrue(ask(self.client, "우리 가게 화장지 값 얼마야?")["reply"]["text"].startswith("이 화면에는 그 정보가 없어요."))
        self.assertEqual(self.market.requests, [])


class MarketingApprovalsInTheDrawer(unittest.TestCase):
    ITEM = {"draft_id": "r1-coupon", "text": "재주문 쿠폰 2천원 드려요.", "original": "재주문 쿠폰 드려요.", "kind": "쿠폰 글",
            "title": "쿠폰 홍보글"}

    def setUp(self):
        from tests.test_marketing_proxy import STATE, FakeMarketing
        from web.marketing_proxy import MarketingProxy
        tmp = Path(tempfile.mkdtemp())
        self.state = STATE
        self.market = FakeMarket()
        proxy = AssistantProxy(MarketClient("http://market.test", ap.DEFAULT_HOST, read_timeout=5.0,
                                            transport=httpx.MockTransport(self.market)))
        marketing = MarketingProxy("http://marketing.internal:8030", transport=httpx.MockTransport(FakeMarketing()))
        storage = MemoryStore()
        demo = Demo(settings(tmp, snapshot_path=REPO / "data" / "scenario" / "snapshot_2026Q2.json"), source=RecordingSource(), storage=storage)
        self.client = TestClient(create_app(demo, assistant=proxy, auth=AuthService(storage), marketing=marketing))

    def approve(self, item):
        res = self.client.post("/api/marketing-survey/approve",
                               json={"state": self.state, "draft_id": None, "session_id": "s_1", "edited_texts": {}, "approval": item})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(len(res.json()["recorded"]), 1)

    def test_no_sentence_before_any_approval(self):
        text = ask(self.client, "쿠폰 홍보하고 싶어")["reply"]["text"]
        self.assertNotIn("맞춤 마케팅에서 승인한 글", text)
        self.assertIn("19.31%", text)                                     # 예전 현황 문장은 그대로

    def test_marketing_answer_counts_approved_marketing_posts(self):
        self.approve(self.ITEM)
        data = ask(self.client, "쿠폰 홍보하고 싶어")
        self.assertEqual(data["reply"]["kind"], "marketing_guide")
        self.assertIn("맞춤 마케팅에서 승인한 글 1건(쿠폰 글)이 있어요.", data["reply"]["text"])
        self.assertIn("19.31%", data["reply"]["text"])
        self.approve({**self.ITEM, "draft_id": "r1-notice", "kind": "공지"})
        self.assertIn("맞춤 마케팅에서 승인한 글 2건(공지)이 있어요.", ask(self.client, "인스타 홍보 하고 싶어")["reply"]["text"])
        other = TestClient(self.client.app)                               # 다른 방문자에게는 보이지 않는다
        self.assertNotIn("승인한 글", ask(other, "쿠폰 홍보하고 싶어")["reply"]["text"])
        self.assertEqual([r for r in self.market.requests if r["path"] == "/api/assistant/messages"], [])

    def test_kind_is_left_out_when_details_cannot_be_read(self):
        self.approve(self.ITEM)
        demo = self.client.app.state.demo

        def broken(*args, **kwargs):
            raise RuntimeError("details 없음")
        demo.storage.approvals.details = broken
        text = ask(self.client, "쿠폰 홍보하고 싶어")["reply"]["text"]
        self.assertIn("맞춤 마케팅에서 승인한 글 1건이 있어요.", text)

        def broken_list(*args, **kwargs):
            raise RuntimeError("목록 없음")
        demo.list_approvals = broken_list
        text = ask(self.client, "쿠폰 홍보하고 싶어")["reply"]["text"]
        self.assertNotIn("승인한 글", text)
        self.assertIn("19.31%", text)


if __name__ == "__main__":
    unittest.main()
