"""상권 서랍 다듬기(11/16) 검증 — 프록시(web/assistant_proxy.py) 쪽. 가짜 상권 서비스를 쓰고 네트워크·CLOVA 는 부르지 않는다.

확인하는 것
  · 분기 표기: 분기 코드(20262 · 2026Q2)가 화면에 가는 글자에서 '2026년 2분기'로 바뀌고, 금액·개수·코드는 그대로다.
    상권 서비스로 되돌아가는 값(선택지 payload, 조건의 코드, 대화의 action, 사용자가 쓴 글)은 바뀌지 않는다
  · 기본 조건 표시: conditions.is_store_default (지금 조건이 우리 가게 기본 조건과 같은지)
  · 가게 기본 질문: 고르는 규칙(가게 질문·상권 질문 표), 답의 내용과 모양, 상권 서비스를 부르지 않음, 프로필을 못 읽을 때
  · 화면(React, services/web/frontend/src)과 맞물리는 것: 분기 정규식(chat.js CHAT_QUARTER·chatQuarter·chatPeriod)이 서버와 같고,
    서랍 첫 추천 질문(chat.js CHAT_STARTERS → state.js)이 상권·전 파트 질문이며, 답에 적는 메뉴 이름이 Sidebar.jsx 메뉴 글자와 같다.
    node 가 있으면 chat.js 를 실제로 불러 서버 함수와 결과를 견준다 (없으면 그 한 건만 건너뜀)

실행 (services/web 에서): PYTHONPATH=<저장소 루트> python -m pytest -q tests/test_assistant_ux.py
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from web import assistant_proxy as ap
from web.assistant_proxy import AssistantProxy, MarketClient
from web.demo import Demo
from web.main import create_app
from web.settings import REPO_ROOT, Settings

from tests import frontend_src as fs
from tests.test_assistant_proxy import WANTED, FakeMarket, build, error_of
from tests.test_web import FakeSource, fixture, settings

MARKET_FLOW = (REPO_ROOT / "services" / "market-analysis" / "app" / "assistant" / "flow.py").read_text(encoding="utf-8")
CHAT_JS = "features/assistant/chat.js"          # 서랍의 순수 계산 (CHAT_QUARTER · chatQuarter · chatPeriod · CHAT_STARTERS)
CHAT_STATE = "features/assistant/state.js"      # 서랍 상태 (첫 추천 질문 칩을 CHAT_STARTERS 로 채움)
STORE = fixture("store_ongi.json")
AN_TABS = fs.strings(fs.const_value(fs.read("features/analysis/calc.js"), "AN_TABS", "frontend/src/features/analysis/calc.js"))

# 가게 자체를 묻는 질문 → 프록시가 답한다 (질문, 종류)
STORE_QUESTIONS = [
    ("우리 가게 이름 뭐야?", "name"), ("가게 이름 알려줘", "name"), ("우리 가게 이름이 뭐였지?", "name"), ("상호가 뭐야?", "name"),
    ("우리 가게 이름", "name"), ("우리 가게 이름이 무엇입니까?", "name"),
    ("우리 가게 메뉴 뭐야?", "menu"), ("메뉴 알려줘", "menu"), ("저희 매장 메뉴 뭐뭐 있어요?", "menu"), ("우리 가게 메뉴 좀 알려줘", "menu"),
    ("메뉴판 보여줘", "menu"), ("우리 가게 뭐 팔아?", "menu"), ("우리 가게 메뉴 몇 개야?", "menu"),
    ("우리 가게 메뉴 가격 알려줘", "price"), ("우리 가게 김치찌개 얼마야?", "price"),
    ("우리 가게 업종 뭐야?", "industry"), ("우리 가게 무슨 업종이야?", "industry"), ("우리 가게 무슨 가게야?", "industry"),
    ("우리 가게 어느 상권이야?", "area"), ("우리 가게 상권이 뭐야?", "area"), ("우리 가게 상권 이름 뭐야?", "area"),
    ("우리 가게 어디에 있어?", "area"), ("우리 가게 위치 알려줘", "area"), ("우리 가게 주소 뭐야?", "area"), ("우리 가게 어디야?", "area"),
    ("우리 가게 정보 알려줘", "profile"), ("우리 가게 소개해줘", "profile"),
    ("우리 가게 영업시간 알려줘", "unknown"), ("우리 가게 전화번호 뭐야?", "unknown"), ("우리 가게 몇 시에 열어?", "unknown"),
    ("우리 가게 사장님 이름 뭐야?", "unknown"),
    ("우리 가게 메뉴별 매출 알려줘", "menu_sales"), ("우리 가게에서 제일 잘 팔리는 메뉴 뭐야?", "menu_sales"),
    ("비 오는 날엔 우리 가게에서 뭐가 잘 팔릴까요?", "menu_sales"), ("우리 가게에서 뭐가 제일 잘 팔려?", "menu_sales"),
    ("리뷰 답글은 어디서 봐?", "where"), ("리뷰 분석은 어디서 봐?", "where"), ("우리 가게 리뷰 어디서 봐?", "where"),
    ("공지 어디서 써?", "where"), ("홍보글 어디서 확인해?", "where"), ("종합 리포트 어디 있어?", "where"),
    ("승인한 글 어디서 확인해?", "where"), ("리뷰 보여줘", "where"),
    # 어순이 뒤바뀐 가게 질문 (11/20): '우리 가게'가 뒤에 오거나 속성 낱말 하나 + 가게
    ("메뉴 우리 가게", "menu"), ("이름 우리 가게", "name"), ("업종 우리 가게", "industry"), ("위치 우리 가게", "area"),
    ("김치찌개 얼마야 우리 가게", "price"), ("가격 우리 가게", "price"), ("우리 가게 가격 알려줘", "price"), ("이름 가게", "name"),
    ("메뉴 뭐야 저희 매장은", "menu"),
]

# 상권 질문·그 밖의 말 → 반드시 상권 서비스로 간다
MARKET_QUESTIONS = [
    # 서랍의 첫 추천 질문 중 상권 질문 (frontend/src/features/assistant/chat.js CHAT_STARTERS)
    "우리 가게 상권 매출은 어때?", "주말 매출은 어때?", "주변에 같은 업종 점포는 몇 개야?", "점심과 저녁 중 매출은 어디가 커?",
    # 우리 가게·동네를 말하지만 상권 자료를 묻는 질문
    "우리 가게 주변 상권 매출 어때?", "우리 동네 한식 매출", "우리 가게 업종 평균 매출", "우리 가게 업종 점포 수 알려줘",
    "우리 가게 상권 어때?", "우리 가게 상권 정보 알려줘", "우리 가게 업종은 요즘 어때?", "우리 가게 업종 요즘 잘 돼?",
    "우리 가게 위치 좋아?", "우리 가게 얼마나 벌어?", "우리 가게 매출 20% 떨어졌어", "우리 가게 월세 얼마야?",
    "우리 가게 상권 뭐가 유명해?", "우리 가게 손님은 주로 몇 살이야?", "우리 가게 주말에 영업해?",
    # 가게 질문과 상권 질문이 섞임 → 상권 서비스
    "우리 가게 이름이랑 상권 매출 같이 알려줘", "우리 가게 메뉴가 이 동네에서 통할까?", "우리 가게 업종에서 잘 나가는 메뉴 뭐야?",
    "이 동네에서 잘 팔리는 메뉴 뭐야?", "합정역 카페 메뉴 뭐가 인기야?", "리뷰 많은 상권 어디야?",
    # 다른 곳·다른 업종
    "합정역 카페 매출 어때?", "합정역 가게 이름 알려줘", "이 상권 이름이 뭐야?", "장승배기역 상권 어디가 제일 붐벼?",
    "서울에서 카페 매출 높은 곳은?", "연남동에서 뭐 하면 잘 될까?", "한식음식점 매출 순위 알려줘", "상도역으로 바꿔줘", "카페로 보면?",
    # 상권 서비스가 '이어서 물어보기'로 주는 문장 (assistant/templates.py)
    "주말 매출은?", "점심·저녁 중 언제 잘 팔려?", "어느 연령대가 많이 사?", "경쟁 가게는 몇 개야?", "요즘 개업·폐업은?", "유동인구는?",
    "작년이랑 비교하면?", "지난 분기보다 어때?", "매출은 얼마야?", "전체 업종으로 보면?", "서울 전체 점포 수는?",
    # 일을 시키거나 조언을 구하는 말, 인사
    "메뉴 추천해줘", "답글 써줘", "홍보 글 써줘", "휴무 공지 써줘", "우리 가게 이름 지어줘", "메뉴 가격 얼마로 하면 좋을까?",
    "우리 가게 어디로 옮길까?", "우리 가게 메뉴 중에 뭐가 제일 남아?", "월세 300만 원, 권리금 5천만 원이야", "우리 가게 리뷰 어때?",
    "메뉴 뭐 넣을까?", "우리 가게 메뉴 뭘 뺄까요?", "우리 가게 이름 뭐로 지을까?",
    "안녕", "고마워",
    # 어순을 옮겨도 상권 낱말이 섞이면 상권 서비스 (11/20)
    "메뉴 추천해줘 우리 가게", "매출 어때 우리 가게", "이름 합정역 가게",
]


# 분기 표기 표 (아래 QuarterOnScreen 도 같은 표로 화면 함수 chat.js chatQuarter 를 돌려 본다): (상권 서비스가 준 글자, 화면에 보일 글자)
QUARTER_CHANGED = [
    ("20262", "2026년 2분기"),
    ("장승배기역 4번 상권의 한식음식점 업종을 20262 자료로 볼게요. [F1]", "장승배기역 4번 상권의 한식음식점 업종을 2026년 2분기 자료로 볼게요. [F1]"),
    ("분석 조건은 장승배기역 4번 상권, 한식음식점 업종, 20262 자료입니다.", "분석 조건은 장승배기역 4번 상권, 한식음식점 업종, 2026년 2분기 자료입니다."),
    ("기간: 20261", "기간: 2026년 1분기"), ("(20254)", "(2025년 4분기)"), ("20262에는 올랐어요", "2026년 2분기에는 올랐어요"),
    ("20253~20262 자료", "2025년 3분기~2026년 2분기 자료"), ("20262, 20261 자료", "2026년 2분기, 2026년 1분기 자료"),
    ("기간은 20262.", "기간은 2026년 2분기."), ("첫 줄\n20262 자료", "첫 줄\n2026년 2분기 자료"),
    ("20262분기", "2026년 2분기"), ("20262 분기 자료", "2026년 2분기 자료"),
    ("2026Q2 기준", "2026년 2분기 기준"), ("2025Q4와 2026Q1", "2025년 4분기와 2026년 1분기"),
]
# 금액·개수·코드·이미 바른 표기: 한 글자도 바뀌지 않는다
QUARTER_UNCHANGED = [
    "20262원", "매출은 20262원이에요", "20,262", "매출 20,262원", "120262", "202620", "20262.5", "20262,000원", "1,20262",
    "20262건", "20262명", "20262개", "20262곳", "20262%", "20262만 원", "20262억", "20262가구", "20262년", "20262점",
    "2026년", "2026년 2분기", "2026년 2분기 자료로 볼게요", "20265", "20260", "19994 자료", "30262 자료",
    "3110826", "CS100001", "2026-10-02", "02-2026-2123", "A20262", "F20262", "v-20262", "20262-1", "20262a",
    "snap_3110826_sales_2026Q2", "2026Q5", "X2026Q2", "2026Q2a", "", "분기 추정매출은 1,000원이에요.",
]


class RawMarket(FakeMarket):
    """분기 이름 없이 코드만 주는 상권 서비스. 실제 서비스도 조건에 period_label 이 빠지면 답 문장에 '20262' 가 그대로 들어간다
    (assistant/facts.py conditions_card: period_label 이 없으면 period 를 씀)."""
    TEXT = ("장승배기역 4번 상권의 한식음식점 업종을 20262 자료로 볼게요. [F1]\n"
            "분기 추정매출은 20262원이에요. 결제는 20,262건, 점포는 120262개예요. [F2]\n"
            "- 2026Q2 기준이고 20261 자료와 비교했어요.")
    ACTION = {"type": "area", "area_code": "3110826", "period": "20261"}

    def _conditions(self, session):
        found = super()._conditions(session)
        return {**found, "period_label": session.get("label", found["period"])} if found else None

    def __call__(self, request):
        path, method = request.url.path, request.method
        if (method, path) not in (("POST", "/api/assistant/messages"), ("GET", "/api/assistant/conversation")):
            return super().__call__(request)
        self.requests.append({"method": method, "path": path, "host": request.headers.get("host"), "json": None,
                              "cookie": request.headers.get("cookie"), "origin": request.headers.get("origin")})
        token, session = self._session(request)
        reply = {"kind": "data_answer", "text": self.TEXT, "cited": ["F1", "F2"],
                 "actions": [{"label": "20261 자료로 보기", "payload": dict(self.ACTION)}],
                 "notes": ["20262 자료는 추정값이에요.", "카드 결제 20262건 기준이에요."], "suggestions": ["20261 자료로 보면?"]}
        cards = [{"id": "F1", "topic": "conditions", "status": "available", "text": "분석 조건은 장승배기역 4번 상권, 한식음식점 업종, 20262 자료입니다.",
                  "values": [{"label": "상권", "value": "장승배기역 4번", "unit": None, "code": "3110826"},
                             {"label": "기간", "value": "20262", "unit": None, "code": "20262"}],
                  "warnings": ["상권 지도는 2023-10-23 공개 경계입니다. 20262 경계와 같은지는 확인되지 않았습니다."],
                  "source_ref": {"analysis": "selection", "catalog_version": "v-20262"}},
                 {"id": "F2", "topic": "sales_total", "status": "available", "text": "분기 추정매출은 20262원입니다.",
                  "values": [{"label": "분기 추정매출", "value": 20262, "unit": "원"}], "warnings": []}]
        if method == "GET":
            turns = [{"seq": 1, "user_text": "20262 매출 알려줘", "reply": reply, "cards": cards, "action": None},
                     {"seq": 2, "user_text": None, "reply": {**reply, "actions": []}, "cards": [], "action": dict(self.ACTION)}]
            return self._json({"turns": turns, "conditions": self._conditions(session)}, token=token)
        return self._json({"schema_version": "assistant-reply-v1", "reply": reply, "model_used": False, "cards": cards,
                           "topics": ["sales_total"], "pending": None, "conditions": self._conditions(session)}, token=token)


class Base(unittest.TestCase):
    market_class = FakeMarket

    def make(self, source=None, **kw):
        self.market = self.market_class(**kw)
        tmp = Path(tempfile.mkdtemp())
        client = MarketClient("http://ic26-market.internal:8766", ap.DEFAULT_HOST, read_timeout=5.0,
                              transport=httpx.MockTransport(self.market))
        self.proxy = AssistantProxy(client)
        self.client = TestClient(create_app(Demo(settings(tmp), source=source or FakeSource()), assistant=self.proxy))
        return self.client

    def ask(self, text):
        return self.client.post("/api/assistant/messages", json={"text": text})

    def sent(self, path="/api/assistant/messages"):
        return [r for r in self.market.requests if r["path"] == path]


# ── 분기 표기 ───────────────────────────────────────────────────────────
class TestQuarterWords(unittest.TestCase):
    def test_raw_quarter_codes_become_words(self):
        for raw, shown in QUARTER_CHANGED:
            with self.subTest(raw=raw):
                self.assertEqual(ap.quarter_words(raw), shown)

    def test_money_counts_and_codes_are_left_alone(self):
        for text in QUARTER_UNCHANGED:
            with self.subTest(text=text):
                self.assertEqual(ap.quarter_words(text), text)

    def test_the_quarter_field(self):
        self.assertEqual(ap.period_words("20262"), "2026년 2분기")
        self.assertEqual(ap.period_words(" 20261 "), "2026년 1분기")
        self.assertEqual(ap.period_words("19994"), "1999년 4분기")          # 칸 전체가 코드이면 연도를 가리지 않는다
        self.assertEqual(ap.period_words("2026년 2분기"), "2026년 2분기")
        self.assertEqual(ap.period_words("20262 기준"), "2026년 2분기 기준")
        self.assertEqual(ap.period_words("20265"), "20265")                 # 5분기는 없다

    def test_things_that_are_not_text_pass_through(self):
        for value in (None, 20262, 20262.0, ["20262"], {"period": "20262"}, True):
            with self.subTest(value=value):
                self.assertEqual(ap.quarter_words(value), value)
                self.assertEqual(ap.period_words(value), value)

    def test_same_words_as_the_card_helper(self):
        from web.cards import quarter_words as card_words          # 추천 카드가 쓰는 '2026Q2' → '2026년 2분기'
        self.assertEqual(ap.quarter_words("2026Q2"), card_words("2026Q2"))
        self.assertEqual(ap.period_words("20262"), card_words("2026Q2"))


class TestQuarterWordsOnTheWire(Base):
    market_class = RawMarket

    def answer(self):
        self.make()
        self.client.post("/api/assistant/setup")
        res = self.ask("매출은 얼마야?")
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_answer_text_shows_words_and_keeps_numbers(self):
        reply = self.answer()["reply"]
        lines = reply["text"].split("\n")
        self.assertEqual(lines[0], "장승배기역 4번 상권의 한식음식점 업종을 2026년 2분기 자료로 볼게요. [F1]")
        self.assertEqual(lines[1], "분기 추정매출은 20262원이에요. 결제는 20,262건, 점포는 120262개예요. [F2]")     # 숫자는 그대로
        self.assertEqual(lines[2], "- 2026년 2분기 기준이고 2026년 1분기 자료와 비교했어요.")
        self.assertEqual(reply["notes"], ["2026년 2분기 자료는 추정값이에요.", "카드 결제 20262건 기준이에요."])
        self.assertEqual(reply["suggestions"], ["2026년 1분기 자료로 보면?"])
        self.assertEqual(reply["cited"], ["F1", "F2"])

    def test_choice_labels_change_but_payloads_do_not(self):
        data = self.answer()
        action = data["reply"]["actions"][0]
        self.assertEqual(action["label"], "2026년 1분기 자료로 보기")
        self.assertEqual(action["payload"], RawMarket.ACTION)                    # 누르면 이 값이 그대로 상권 서비스로 간다
        res = self.client.post("/api/assistant/actions", json=action["payload"])
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.sent("/api/assistant/actions")[-1]["json"], RawMarket.ACTION)

    def test_cards_show_words_but_keep_codes_and_numbers(self):
        cards = self.answer()["cards"]
        self.assertEqual(cards[0]["text"], "분석 조건은 장승배기역 4번 상권, 한식음식점 업종, 2026년 2분기 자료입니다.")
        period = cards[0]["values"][1]
        self.assertEqual((period["value"], period["code"]), ("2026년 2분기", "20262"))
        self.assertEqual(cards[0]["values"][0], {"label": "상권", "value": "장승배기역 4번", "unit": None, "code": "3110826"})
        self.assertIn("2023-10-23 공개 경계입니다. 2026년 2분기 경계와", cards[0]["warnings"][0])
        self.assertEqual(cards[0]["source_ref"], {"analysis": "selection", "catalog_version": "v-20262"})
        self.assertEqual(cards[1]["text"], "분기 추정매출은 20262원입니다.")
        self.assertEqual(cards[1]["values"], [{"label": "분기 추정매출", "value": 20262, "unit": "원"}])

    def test_conditions_get_a_quarter_name_and_keep_the_code(self):
        self.make()
        setup = self.client.post("/api/assistant/setup").json()["conditions"]
        self.assertEqual((setup["period"], setup["period_label"]), ("20262", "2026년 2분기"))
        for found in (self.ask("매출은?").json()["conditions"], self.client.get("/api/assistant/conversation").json()["conditions"]):
            self.assertEqual((found["period"], found["period_label"]), ("20262", "2026년 2분기"))
            self.assertEqual((found["area_code"], found["industry_code"]), ("3110826", "CS100001"))

    def test_a_missing_quarter_name_is_made_from_the_code(self):
        self.make()
        self.client.post("/api/assistant/setup")
        next(iter(self.market.sessions.values()))["label"] = None
        self.assertEqual(self.client.get("/api/assistant/conversation").json()["conditions"]["period_label"], "2026년 2분기")

    def test_history_shows_words_but_keeps_what_the_user_typed_and_picked(self):
        self.make()
        turns = self.client.get("/api/assistant/conversation").json()["turns"]
        self.assertEqual(turns[0]["user_text"], "20262 매출 알려줘")                  # 사용자가 쓴 글은 고치지 않는다
        self.assertIn("2026년 2분기 자료로 볼게요", turns[0]["reply"]["text"])
        self.assertEqual(turns[0]["reply"]["actions"][0]["label"], "2026년 1분기 자료로 보기")
        self.assertEqual(turns[0]["reply"]["actions"][0]["payload"], RawMarket.ACTION)
        self.assertEqual(turns[0]["cards"][0]["values"][1]["value"], "2026년 2분기")
        self.assertEqual(turns[1]["action"], RawMarket.ACTION)                        # 화면이 고른 선택지를 이 값으로 찾는다

    def test_no_raw_code_is_left_in_what_the_drawer_shows(self):
        data = self.answer()
        shown = [data["reply"]["text"], *data["reply"]["notes"], *data["reply"]["suggestions"],
                 *[a["label"] for a in data["reply"]["actions"]], data["conditions"]["period_label"],
                 *[c["text"] for c in data["cards"]], *[w for c in data["cards"] for w in c["warnings"]]]
        for text in shown:
            with self.subTest(text=text[:30]):
                self.assertIsNone(re.search(r"(?<![0-9,])2026[1-4](?![0-9원건개,])", text))
                self.assertNotIn("2026Q", text)

    def test_other_replies_pass_through_unchanged(self):
        self.make()
        self.client.post("/api/assistant/messages", json={"text": "질문"})
        self.assertEqual(self.client.delete("/api/assistant/conversation").json(), {"removed_turns": 0})
        echo = {"type": "location", "kind": "station", "station_id": WANTED.station_id, "period": "20262"}
        self.assertEqual(self.client.post("/api/assistant/actions", json=echo).json()["echo"], echo)   # 모르는 칸은 건드리지 않는다


class QuarterOnScreen(unittest.TestCase):
    """화면(frontend/src/features/assistant/chat.js)도 서버가 놓친 분기 코드를 같은 규칙으로 바꾼다.
    정규식 글자가 서버(QUARTER_IN_TEXT)와 같고, node 가 있으면 화면 함수를 실제로 돌려 서버 함수와 결과가 같은지 본다.
    (11/20 React 전환 때 test_assistant_ux_static.py 에서 옮김)"""

    def source(self) -> tuple[str, str]:
        return fs.regex_const(fs.read(CHAT_JS), "CHAT_QUARTER", f"frontend/src/{CHAT_JS}")

    def test_same_pattern_as_the_server(self):
        pattern, flags = self.source()
        self.assertEqual(pattern, ap.QUARTER_IN_TEXT.pattern,
                         "화면 chat.js 의 CHAT_QUARTER 와 서버 assistant_proxy.QUARTER_IN_TEXT 정규식이 달라요 (둘을 같이 고칠 것)")
        self.assertEqual(flags, "g")                                             # 문장 속 모든 분기 코드를 바꾼다

    def test_pattern_runs_on_older_browsers(self):
        pattern, _ = self.source()
        self.assertNotIn("(?<", pattern)     # 뒤돌아보기(lookbehind)는 예전 Safari 에서 파일 전체가 안 읽힌다. 앞 글자를 묶음으로 잡는다
        self.assertNotIn("/", pattern)

    def test_replacement_matches_the_server(self):
        js = fs.read(CHAT_JS)
        quarter = fs.squash(fs.function_text(js, "chatQuarter", f"frontend/src/{CHAT_JS}"))
        self.assertIn(fs.squash("t.replace(CHAT_QUARTER, (_, pre, y, q, n) => `${pre}${y}년 ${q || n}분기`)"), quarter)
        self.assertIn(fs.squash('typeof t === "string"'), quarter)               # 글자가 아니면 그대로 (서버 quarter_words 와 같음)
        period = fs.squash(fs.function_text(js, "chatPeriod", f"frontend/src/{CHAT_JS}"))
        self.assertIn(fs.squash("/^[0-9]{4}[1-4]$/.test(p)"), period)           # 조건 줄: 칸 전체가 코드일 때 (서버 QUARTER_CODE)
        self.assertEqual(ap.QUARTER_CODE.pattern, "[0-9]{4}[1-4]")

    @unittest.skipUnless(fs.NODE, "node 가 없어 화면 함수를 실제로 돌려 보지 못함")
    def test_runs_like_the_server_function(self):
        texts = [raw for raw, _ in QUARTER_CHANGED] + QUARTER_UNCHANGED
        fields = ["20262", "19994", "2026년 2분기", "20262 기준", "20265"]
        out = fs.node_eval({CHAT_JS: ["chatQuarter", "chatPeriod"]}, f"""{{
            texts: {json.dumps(texts, ensure_ascii=False)}.map(chatQuarter),
            twice: {json.dumps(texts, ensure_ascii=False)}.map(chatQuarter).map(chatQuarter),
            fields: {json.dumps(fields, ensure_ascii=False)}.map((p) => chatPeriod({{ period_label: p }})),
            fromCode: chatPeriod({{ period_label: null, period: "20261" }}),
            other: [chatQuarter(null), chatQuarter(20262)] }}""")
        self.assertEqual(out["texts"], [ap.quarter_words(t) for t in texts])
        self.assertEqual(out["twice"], out["texts"])                             # 서버가 이미 바꾼 글자를 또 바꾸지 않는다
        self.assertEqual(out["fields"], [ap.period_words(p) for p in fields])
        self.assertEqual(out["fromCode"], "2026년 1분기")
        self.assertEqual(out["other"], [None, 20262])


# ── 기본 조건 표시 ───────────────────────────────────────────────────────
class TestStoreDefaultFlag(Base):
    def conditions(self):
        return self.client.get("/api/assistant/conversation").json()["conditions"]

    def session(self):
        return next(iter(self.market.sessions.values()))

    def test_true_right_after_setup_on_every_reply_that_carries_conditions(self):
        self.make()
        setup = self.client.post("/api/assistant/setup").json()
        self.assertEqual(setup["status"], "ok")
        self.assertIs(setup["conditions"]["is_store_default"], True)
        self.assertIs(self.conditions()["is_store_default"], True)
        self.assertIs(self.ask("매출 어때?").json()["conditions"]["is_store_default"], True)
        self.assertIs(self.client.post("/api/assistant/setup").json()["conditions"]["is_store_default"], True)     # already

    def test_false_when_the_chat_moved_to_another_area_industry_or_quarter(self):
        for name, change in (
                ("area", lambda s: s["selection"].update(area_code="1111111", area_name="합정역")),
                ("industry", lambda s: s["profile"].update(industry={"code": "CS100010", "name": "커피-음료"})),
                ("quarter", lambda s: s["selection"].update(period="20261", period_label="2026년 1분기"))):
            with self.subTest(changed=name):
                self.make()
                self.client.post("/api/assistant/setup")
                change(self.session())
                self.assertIs(self.conditions()["is_store_default"], False)
                self.assertIs(self.ask("매출 어때?").json()["conditions"]["is_store_default"], False)
                self.assertIs(self.client.post("/api/assistant/setup").json()["conditions"]["is_store_default"], False)   # force 없이는 그대로

    def test_force_brings_it_back_to_true(self):
        self.make()
        self.client.post("/api/assistant/setup")
        self.session()["profile"]["location"]["station_id"] = "another-station"
        self.session()["profile"]["industry"] = {"code": "CS100010", "name": "커피-음료"}
        self.session()["selection"].update(area_code="1111111", area_name="합정역")
        self.assertIs(self.conditions()["is_store_default"], False)
        forced = self.client.post("/api/assistant/setup?force=1").json()
        self.assertEqual((forced["status"], forced["conditions"]["is_store_default"]), ("ok", True))
        self.assertIs(self.conditions()["is_store_default"], True)

    def test_the_latest_quarter_fallback_counts_as_our_default(self):
        """정해 둔 분기(20262)가 자료에 없어 가장 최근 분기로 맞췄으면, 그 조건이 이 자료에서의 우리 가게 기본 조건이다."""
        self.make(candidates=[FakeMarket.candidate(WANTED.area_code, "장승배기역 4번", periods=("20261", "20253"))])
        setup = self.client.post("/api/assistant/setup").json()["conditions"]
        self.assertEqual((setup["period"], setup["is_store_default"]), ("20261", True))
        self.assertIs(self.conditions()["is_store_default"], True)
        self.session()["selection"].update(period="20253", period_label="2025년 3분기")
        self.assertIs(self.conditions()["is_store_default"], False)

    def test_a_fallback_area_counts_too(self):
        self.make(candidates=[FakeMarket.candidate("1234567", "다른 이름 상권", "nearby")])
        self.assertIs(self.client.post("/api/assistant/setup").json()["conditions"]["is_store_default"], True)

    def test_before_any_setup_only_the_exact_default_counts(self):
        """서버를 다시 켠 직후(맞춘 기억이 없음)에는 정해 둔 값과 똑같을 때만 true. 한 번 맞추고 나면 그 값을 기억한다."""
        self.make(candidates=[FakeMarket.candidate(WANTED.area_code, "장승배기역 4번", periods=("20261",))])
        self.client.post("/api/assistant/setup")
        self.proxy.home = None                                   # 서버 재시작과 같은 상태
        self.assertIs(self.conditions()["is_store_default"], False)
        self.assertIs(self.client.post("/api/assistant/setup?force=1").json()["conditions"]["is_store_default"], True)
        self.assertIs(self.conditions()["is_store_default"], True)

    def test_unknown_for_a_store_without_defaults_and_for_conditions_without_codes(self):
        market = FakeMarket()
        client, proxy = build(market, store_id="store_unknown")
        self.assertIsNone(proxy._conditions({"area_code": "3110826", "industry_code": "CS100001", "period": "20262"})["is_store_default"])
        self.assertIsNone(client.post("/api/assistant/setup").json()["conditions"])
        self.make()
        self.assertIsNone(self.proxy._conditions({"area_name": "장승배기역 4번", "period_label": "2026년 2분기"})["is_store_default"])

    def test_no_conditions_stay_none_and_status_is_unchanged(self):
        self.make()
        self.assertIsNone(self.conditions())
        self.assertNotIn("is_store_default", self.client.get("/api/assistant/status").json())
        self.make(data=False)
        self.assertIsNone(self.client.post("/api/assistant/setup").json()["conditions"])


# ── 가게 기본 질문 ───────────────────────────────────────────────────────
class TestStoreQuestionRules(unittest.TestCase):
    def test_store_questions(self):
        self.assertGreaterEqual(len(STORE_QUESTIONS), 10)
        for text, kind in STORE_QUESTIONS:
            with self.subTest(text=text):
                self.assertEqual(ap.store_question(text), kind)

    def test_market_questions_always_go_to_the_market_service(self):
        self.assertGreaterEqual(len(MARKET_QUESTIONS), 10)
        for text in MARKET_QUESTIONS:
            with self.subTest(text=text):
                self.assertIsNone(ap.store_question(text))

    def test_the_drawer_starters_are_market_questions(self):
        # 5차 회의(11/18): 첫 추천 질문은 상권 질문과 전 파트 질문(고객응대·마케팅)이 섞인다. 가게 기본 질문은 없다
        starters = fs.strings(fs.const_value(fs.read(CHAT_JS), "CHAT_STARTERS", f"frontend/src/{CHAT_JS}"))
        # 서랍 상태(state.js)가 이 상수로 첫 칩을 채운다 (가져오기 한 번 + 쓰는 곳)
        state = fs.read(CHAT_STATE)
        self.assertRegex(state, r'import\s*\{[^}]*\bCHAT_STARTERS\b[^}]*\}\s*from\s*["\']\./chat\.js["\']',
                         f"frontend/src/{CHAT_STATE} 가 chat.js 의 CHAT_STARTERS 를 가져오지 않아요")
        self.assertGreaterEqual(len(re.findall(r"\bCHAT_STARTERS\b", state)), 2, f"frontend/src/{CHAT_STATE} 가 CHAT_STARTERS 를 쓰지 않아요")
        self.assertEqual(len(starters), 6)
        for text in starters:
            self.assertIsNone(ap.store_question(text), text)
        domains = [ap.domain_question(text) for text in starters]
        self.assertEqual(domains.count(None), 3)                      # 상권 서비스로 가는 질문 셋
        self.assertEqual(sorted(d for d in domains if d), ["care", "marketing", "marketing"])
        for text in ap.BACK_TO_MARKET:                 # 가게 답 아래 '이어서 물어보기'는 첫 추천 질문과 같은 문장이고 상권으로 간다
            self.assertIn(text, starters)

    def test_spacing_punctuation_and_length(self):
        self.assertEqual(ap.store_question("  우리가게이름뭐야??  "), "name")
        self.assertEqual(ap.store_question("우리 가게 메뉴, 뭐야!"), "menu")
        self.assertIsNone(ap.store_question(""))
        self.assertIsNone(ap.store_question("?!"))
        long = "우리 가게 이름 뭐야? " + "그리고 요즘 손님들이 어떤 걸 찾는지도 같이 궁금해서 물어보는 건데 " * 2
        self.assertIsNone(ap.store_question(long))      # 긴 글은 단순한 가게 질문으로 보지 않는다

    def test_every_market_word_alone_blocks_a_store_answer(self):
        for word in ap._MARKET_WORDS:
            if word == "상권":
                continue                                 # '상권'만 있을 때는 가게의 상권 이름을 묻는 모양만 따로 본다
            with self.subTest(word=word):
                self.assertIsNone(ap.store_question(f"우리 가게 이름 뭐야 {word}"))
                self.assertIsNone(ap.store_question(f"{word} 리뷰 어디서 봐?"))

    def test_polite_endings(self):
        self.assertEqual((ap._ieyo("한식음식점"), ap._ieyo("카페"), ap._ieyo("온기한식 (가상)"), ap._ieyo("ABC")),
                         ("이에요", "예요", "이에요", "이에요"))


class TestStoreAnswers(Base):
    def test_the_name_question_is_answered_from_the_profile_without_the_market_service(self):
        self.make()
        res = self.ask("우리 가게 이름 뭐야?")
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        lines = data["reply"]["text"].split("\n")
        self.assertEqual(lines[0], "우리 가게 이름은 '온기한식 (가상)'이에요.")
        self.assertIn("- 업종: 한식음식점", lines)
        self.assertIn("- 상권: 장승배기역 4번", lines)
        self.assertIn("- 메뉴: " + ", ".join(STORE["menu"]), lines)
        self.assertEqual(lines[-1], ap.GUIDE_LINE)
        self.assertEqual(data["answered_by"], "store_profile")
        self.assertEqual(self.market.requests, [])                    # 상권 서비스는 한 번도 부르지 않았다
        self.assertEqual(res.headers["cache-control"], "no-store")

    def test_the_answer_has_the_same_fields_as_a_market_answer(self):
        """상권 서비스 flow.py 의 _finish 가 만드는 칸과 같아야 화면이 같은 코드로 그린다 (debug 는 라우터가 빼고 보낸다)."""
        finish = MARKET_FLOW[MARKET_FLOW.index("def _finish("):]
        top = ["schema_version", "reply", "model_used", "cards", "topics", "classification", "pending"]
        for key in top:
            self.assertIn(f'"{key}":', finish)
        reply_keys = re.search(r'for key in \(("text", "kind", "cited", "actions")\)', finish)
        self.assertIsNotNone(reply_keys)
        class_keys = re.findall(r'"(\w+)"', re.search(r'"classification": \{key: cls\.get\(key\) for key in\s*\(([^)]*)\)', finish).group(1))
        self.assertEqual(re.search(r'^SCHEMA = "([^"]+)"', MARKET_FLOW, re.M).group(1), ap.REPLY_SCHEMA)
        self.make()
        for text, _ in STORE_QUESTIONS:
            with self.subTest(text=text):
                data = self.ask(text).json()
                self.assertEqual(sorted(data), sorted([*top, "answered_by"]))            # conditions 는 싣지 않는다 (조건 줄이 그대로)
                self.assertEqual(sorted(data["reply"]), sorted(["text", "kind", "cited", "actions", "notes", "suggestions"]))
                self.assertEqual(sorted(data["classification"]), sorted(class_keys))
                self.assertEqual(data["schema_version"], ap.REPLY_SCHEMA)
                self.assertEqual((data["cards"], data["topics"], data["pending"], data["model_used"]), ([], [], None, False))
                self.assertEqual(data["reply"]["cited"], [])
                self.assertTrue(data["reply"]["text"].strip())
                self.assertIn(data["reply"]["kind"], ("store_profile", "store_guide"))
                actions = data["reply"]["actions"]
                if data["reply"]["kind"] == "store_profile":
                    self.assertEqual(actions, [])                                         # 가게 정보 답에는 버튼이 없다
                else:                                                                     # 화면 위치 답: 그 화면으로 가는 버튼 1~3개 (11/20)
                    self.assertTrue(1 <= len(actions) <= 3, actions)
                    for action in actions:
                        payload = action["payload"]
                        self.assertTrue(action["label"].strip())
                        self.assertEqual(payload["type"], "navigate")
                        self.assertIn(payload["route"], fs.ROUTES)
                        if payload["route"] == "analysis":
                            self.assertIn(payload.get("sub"), AN_TABS)
                self.assertEqual(data["reply"]["suggestions"], ap.BACK_TO_MARKET)
                self.assertTrue(all(isinstance(n, str) for n in data["reply"]["notes"]))
                self.assertEqual(data["classification"]["domain"], "store")
        self.assertEqual(self.market.requests, [])

    def test_a_market_answer_has_no_field_the_store_answer_lacks(self):
        self.make()
        market, store = self.ask("매출 어때?").json(), self.ask("우리 가게 이름 뭐야?").json()
        self.assertNotIn("answered_by", market)
        self.assertEqual(set(market["reply"]) - set(store["reply"]), set())
        self.assertEqual(set(market) - set(store) - {"conditions"}, set())

    def test_menu_and_prices(self):
        self.make()
        lines = self.ask("우리 가게 메뉴 뭐야?").json()["reply"]["text"].split("\n")
        self.assertEqual(lines[0], "우리 가게 메뉴는 6가지예요.")
        self.assertEqual(lines[1:7], ["- 제육볶음 정식 9,500원", "- 된장찌개 8,000원", "- 김치찌개 8,000원", "- 순두부찌개 8,500원",
                                      "- 불고기 덮밥 9,000원", "- 계란말이 6,000원"])
        priced = self.ask("우리 가게 김치찌개 얼마야?").json()["reply"]["text"]
        self.assertIn("- 김치찌개 8,000원", priced)

    def test_prices_are_shown_only_when_the_profile_has_them(self):
        self.make()
        profile = ap.to_store_profile({**STORE, "store_id": "store_other", "menu": ["아메리카노", "라떼"]}, None)
        self.proxy.read_store = lambda: profile
        lines = self.ask("우리 가게 메뉴 가격 알려줘").json()["reply"]["text"].split("\n")
        self.assertEqual(lines[:3], ["메뉴 가격은 이 화면에 없어요. 우리 가게 메뉴는 아래와 같아요.", "- 아메리카노", "- 라떼"])
        self.assertNotIn("원", "".join(lines[:3]))
        area = self.ask("우리 가게 어디에 있어?").json()["reply"]["text"]
        self.assertIn("우리 가게 상권 정보는 이 화면에 없어요.", area)               # 상권을 모르면 지어내지 않는다
        self.assertNotIn("- 상권:", self.ask("우리 가게 이름 뭐야?").json()["reply"]["text"])

    def test_industry_and_area(self):
        self.make()
        self.assertEqual(self.ask("우리 가게 업종 뭐야?").json()["reply"]["text"].split("\n")[0], "우리 가게 업종은 한식음식점이에요.")
        self.assertEqual(self.ask("우리 가게 어느 상권이야?").json()["reply"]["text"].split("\n")[0], "우리 가게는 장승배기역 4번 상권에 있어요.")
        self.assertTrue(self.ask("우리 가게 주소 뭐야?").json()["reply"]["text"].startswith("정확한 주소는 이 화면에 없어요. 우리 가게는 장승배기역 4번"))

    def test_what_the_profile_does_not_have_is_not_made_up(self):
        self.make()
        for text in ("우리 가게 영업시간 알려줘", "우리 가게 전화번호 뭐야?", "우리 가게 몇 시에 열어?", "우리 가게 사장님 이름 뭐야?"):
            with self.subTest(text=text):
                reply = self.ask(text).json()["reply"]["text"]
                self.assertTrue(reply.startswith("이 화면에는 그 정보가 없어요."))
                self.assertIsNone(re.search(r"\d{1,2}시|\d{2,4}-\d{3,4}", reply))        # 시각·전화번호를 지어내지 않는다
                self.assertIn("- 이름: 온기한식 (가상)", reply)
        sales = self.ask("우리 가게 메뉴별 매출 알려줘").json()["reply"]["text"]
        self.assertTrue(sales.startswith("이 화면에는 메뉴별 매출·판매량 정보가 없어요."))
        self.assertNotIn("원\n", sales)                                                # 가격도 매출처럼 보일 수 있어 뺀다
        rent = self.ask("우리 가게 화장지 값 얼마야?").json()["reply"]["text"]           # 값은 값인데 메뉴가 아니다
        self.assertTrue(rent.startswith("이 화면에는 그 정보가 없어요."))

    def test_where_to_see_reviews_and_replies(self):
        self.make()
        reply = self.ask("리뷰 답글은 어디서 봐?").json()["reply"]
        lines = reply["text"].split("\n")
        self.assertEqual(lines[0], "리뷰 답글 초안은 화면 메뉴 '추천 카드'에서 카드를 고르면 '승인할 글'에 나와요. 승인한 글은 '처리 완료'에 모여요.")
        for name in ("리뷰 분석", "추천 카드", "승인할 글", "처리 완료", "맞춤 마케팅", "종합 리포트"):
            self.assertIn(f"'{name}'", reply["text"])
        self.assertEqual(reply["kind"], "store_guide")
        self.assertTrue(self.ask("리뷰 분석은 어디서 봐?").json()["reply"]["text"].startswith("리뷰와 불만 묶음은 화면 메뉴 '리뷰 분석'"))
        self.assertTrue(self.ask("종합 리포트 어디 있어?").json()["reply"]["text"].startswith("응대 점수와 월간 보고서는 화면 메뉴 '종합 리포트'"))
        self.assertTrue(self.ask("공지 어디서 써?").json()["reply"]["text"].startswith("포장·주문 안내문 초안은 화면 메뉴 '추천 카드'"))
        self.assertTrue(self.ask("안내문 어디서 봐?").json()["reply"]["text"].startswith("포장·주문 안내문 초안은 화면 메뉴 '추천 카드'"))   # 11/18 새 이름
        for text in ("홍보는 어디서 해?", "광고비 점검 어디서 해?", "마케팅 보고서 어디서 봐?"):     # 맞춤 마케팅 (11/16)
            with self.subTest(text=text):
                self.assertTrue(self.ask(text).json()["reply"]["text"].startswith("홍보·쿠폰·광고비는 화면 메뉴 '맞춤 마케팅'"))
        self.assertEqual(self.market.requests, [])

    def test_screen_names_match_the_menu_on_the_page(self):
        labels = list(fs.sidebar_menu().values())             # frontend/src/components/Sidebar.jsx 왼쪽 메뉴 글자
        self.assertEqual(sorted(ap.SCREENS.values()), sorted(["리뷰 분석", "추천 카드", "승인할 글", "처리 완료", "맞춤 마케팅", "종합 리포트"]))
        for name in ap.SCREENS.values():                      # 답에 적는 메뉴 이름이 화면 메뉴 글자와 같다
            self.assertIn(name, labels, f"서랍 답(assistant_proxy.SCREENS)의 메뉴 이름 '{name}' 이 Sidebar.jsx 메뉴 {labels} 에 없어요 "
                                        "(메뉴 글자를 바꿨다면 assistant_proxy.SCREENS 도 같이 고칠 것)")
        self.assertIn("동네 상권·업종 매출 상담", ap._where_answer("리뷰 어디서 봐?")["reply"]["text"])

    def test_when_the_profile_cannot_be_read(self):
        self.make(source=FakeSource(down=True))
        res = self.ask("우리 가게 이름 뭐야?")
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(data["reply"]["text"].startswith("가게 정보를 지금 불러오지 못했어요."))
        self.assertEqual((data["reply"]["kind"], data["answered_by"]), ("store_unavailable", "store_profile"))
        self.assertNotIn("온기한식", data["reply"]["text"])
        self.assertEqual(self.market.requests, [])                       # 그래도 상권 서비스로 넘기지 않는다
        guide = self.ask("리뷰 답글은 어디서 봐?").json()                  # 화면 위치는 프로필이 없어도 답한다
        self.assertEqual(guide["reply"]["kind"], "store_guide")

    def test_a_broken_profile_or_no_profile_source_is_not_a_crash(self):
        self.make()
        for reader in (None, lambda: (_ for _ in ()).throw(ValueError("이상한 값")), lambda: ap.StoreProfile.from_dict({"store_id": "x"})):
            with self.subTest(reader=reader):
                self.proxy.read_store = reader
                res = self.ask("우리 가게 메뉴 뭐야?")
                self.assertEqual((res.status_code, res.json()["reply"]["kind"]), (200, "store_unavailable"))

    def test_market_questions_are_still_forwarded(self):
        self.make()
        for text in ("우리 가게 상권 매출은 어때?", "우리 가게 이름이랑 상권 매출 같이 알려줘", "우리 가게 업종 평균 매출"):
            with self.subTest(text=text):
                data = self.ask(text).json()
                self.assertEqual(data["reply"]["text"], f"답: {text} [F1]")
                self.assertNotIn("answered_by", data)
                self.assertEqual(self.sent()[-1]["json"], {"text": text})
        self.assertEqual(len(self.sent()), 3)

    def test_a_store_question_between_market_questions_keeps_the_session(self):
        self.make()
        self.client.post("/api/assistant/setup")
        self.ask("매출 어때?")
        before = len(self.market.requests)
        store = self.ask("우리 가게 메뉴 뭐야?")
        self.assertEqual(len(self.market.requests), before)
        self.assertNotIn("conditions", store.json())
        self.ask("주말 매출은?")
        history = self.client.get("/api/assistant/conversation").json()
        # 알려진 한계: 프록시가 답한 문답은 상권 서비스의 대화 기록에 없다 (새로 고치면 그 문답은 보이지 않는다)
        self.assertEqual([t["user_text"] for t in history["turns"]], ["매출 어때?", "주말 매출은?"])
        self.assertIs(history["conditions"]["is_store_default"], True)

    def test_store_questions_are_answered_even_when_the_market_service_is_unwell(self):
        for kwargs in ({"mode": "down"}, {"mode": "timeout"}, {"enabled": False}, {"data": False}):
            with self.subTest(market=kwargs):
                self.make(**kwargs)
                res = self.ask("우리 가게 이름 뭐야?")
                self.assertEqual(res.status_code, 200, res.text)
                self.assertIn("온기한식 (가상)", res.json()["reply"]["text"])
        self.make(mode="down")
        self.assertEqual((self.ask("매출 어때?").status_code, error_of(self.ask("매출 어때?"))["state"]), (503, "down"))

    def test_not_answered_when_the_assistant_is_switched_off_on_this_server(self):
        client = TestClient(create_app(Demo(settings(Path(tempfile.mkdtemp())), source=FakeSource()),
                                       assistant=AssistantProxy.from_settings(Settings(market_url="off"))))
        res = client.post("/api/assistant/messages", json={"text": "우리 가게 이름 뭐야?"})
        self.assertEqual((res.status_code, error_of(res)["state"]), (503, "off"))

    def test_input_checks_come_first(self):
        self.make()
        for body in ({"text": "우리 가게 이름 뭐야?", "extra": 1}, {"text": "우리 가게 이름 뭐야? " + "가" * 1000}):
            self.assertEqual(self.client.post("/api/assistant/messages", json=body).status_code, 422)

    def test_the_real_review_service_profile_reads_the_same(self):
        """리뷰 분석 서비스의 실제 가게 파일과 시험 자료가 같은 값인지 (이름·업종·메뉴가 답에 그대로 나온다)."""
        import json
        real = json.loads((REPO_ROOT / "services/review-insight/data/synthetic/store_ongi/store.json").read_text(encoding="utf-8"))
        self.assertEqual({k: real[k] for k in ("name", "business_type_name", "menu")},
                         {k: STORE[k] for k in ("name", "business_type_name", "menu")})


if __name__ == "__main__":
    unittest.main()
