"""서랍의 고객응대 질문 → 리뷰 분석 서비스의 질문 답하기(POST /api/review-insight/ask, 11/21).

예전에는 리뷰 질문 8개가 글자까지 같은 안내 두 줄을 받았다. 이제 고객응대 질문은 리뷰 분석 서비스가 그 가게 리뷰로 센 근거 카드와 답을 주고,
이 서버는 그것을 서랍 답 모양(assistant-reply-v1)으로 바꾸고 질문 종류에 맞는 이동 버튼을 붙인다.
- 리뷰 분석 서비스가 꺼져 있거나 /ask 가 없는 예전 버전이면 예전 안내 그대로 (test_assistant_domains.py 가 그 경우를 본다)
- 답글·안내문을 '써 달라'는 말은 예전처럼 추천 카드 안내
- 리뷰라는 말 없이 손님 반응·주제를 묻는 말도 고객응대로 (예전에는 상권 서비스로 가서 엉뚱한 상권 숫자가 나옴)
실행 (services/web 에서):  env -u APP_MODE PYTHONPATH=../.. python -m pytest -q tests/test_assistant_care_ask.py
"""
from __future__ import annotations

import unittest

from tests.test_assistant_domains import ask, build, routes
from tests.test_auth_stores import RecordingSource
from web import assistant_proxy as ap
from web.assistant_proxy import domain_question
from web.sources import SourceError

CARDS = [{"id": "F1", "topic": "불만 순위", "status": "available", "text": "불만 리뷰 12건의 주제별 건수예요.",
          "values": [{"label": "포장 누락", "value": 3, "unit": "건", "share_percent": 25}], "warnings": [],
          "source_ref": {"source_title": "리뷰 분석 서비스", "data_version": "2026-10-13~2026-11-08"}},
         {"id": "F2", "topic": "시간대", "status": "available", "text": "'포장 누락' 불만 3건의 들어온 시간대예요.",
          "values": [{"label": "17~21시", "value": 3, "unit": "건"}], "warnings": [], "source_ref": {}}]


class AskingSource(RecordingSource):
    """/ask 가 있는 리뷰 분석 서비스 대신. 질문을 적어 두고, 질문마다 다른 답을 준다."""

    def __init__(self, fail: bool = False):
        super().__init__()
        self.asked: list[tuple[str, str, str | None]] = []
        self.fail = fail

    def ask(self, store_id, text, timeout=30.0):
        self.asked.append((store_id, text, getattr(self, "visitor_id", None)))
        if self.fail:
            raise SourceError("리뷰 분석 서비스에 연결하지 못했습니다: ConnectError")
        intent = "time" if "언제" in text else "rating" if "별점" in text else "complaints"
        return {"text": f"[{intent}] 가장 많은 불만은 '포장 누락'(3건)이에요 [F1]. 17~21시에 3건 몰렸어요 [F2].",
                "intent": intent, "topic": None, "channels": [], "cards": CARDS,
                "suggestions": ["그 불만 언제 많이 와?", "답글 안 단 리뷰 몇 개야?", "셋째 추천"], "method": "template",
                "demo": True, "checks": [], "notes": [], "base_day": "2026-11-08"}


def client_with(source):
    from tests import test_assistant_domains as dom
    original = dom.RecordingSource
    dom.RecordingSource = lambda: source            # build() 가 만드는 Demo 의 리뷰 분석 연결을 이것으로
    try:
        return build()
    finally:
        dom.RecordingSource = original


class CareAsk(unittest.TestCase):
    def setUp(self):
        self.source = AskingSource()
        self.client, self.market = client_with(self.source)

    def test_care_question_is_answered_with_cards_from_the_review_service(self):
        data = ask(self.client, "불만 리뷰 제일 많은 게 뭐야?")
        reply = data["reply"]
        self.assertEqual((reply["kind"], data["answered_by"], data["classification"]["domain"]),
                         ("care_answer", ap.CARE_ANSWER, "customer"))
        self.assertTrue(reply["text"].startswith("[complaints]"))
        self.assertEqual([c["id"] for c in data["cards"]], ["F1", "F2"])
        self.assertEqual(reply["cited"], ["F1", "F2"])
        self.assertEqual(reply["notes"], [])                     # 답 아래 안내 줄 없음 (11/21)
        self.assertEqual(reply["suggestions"], ["그 불만 언제 많이 와?", "답글 안 단 리뷰 몇 개야?", ap.BACK_TO_MARKET[0]])
        self.assertEqual(routes(data), [("cards", None), ("analysis", "issues")])
        self.assertEqual(self.source.asked[-1][:2], ("store_ongi", "불만 리뷰 제일 많은 게 뭐야?"))
        self.assertEqual([r for r in self.market.requests if r["path"] == "/api/assistant/messages"], [])   # 상권 서비스는 안 부름

    def test_each_question_gets_its_own_answer_and_buttons(self):
        a = ask(self.client, "포장 누락 불만 언제 많이 와?")
        b = ask(self.client, "별점 평균 몇 점이야?")
        self.assertNotEqual(a["reply"]["text"], b["reply"]["text"])
        self.assertEqual(routes(a), [("analysis", "issues"), ("cards", None)])
        self.assertEqual(routes(b), [("analysis", "summary"), ("cards", None)])

    def test_write_requests_keep_the_card_guide(self):
        data = ask(self.client, "억울한 리뷰 답글 써줘")
        self.assertEqual(data["reply"]["kind"], "care_guide")
        self.assertEqual(self.source.asked, [])

    def test_review_service_down_falls_back_to_the_guide(self):
        client, _ = client_with(AskingSource(fail=True))
        self.assertEqual(ask(client, "불만 리뷰 제일 많은 게 뭐야?")["reply"]["kind"], "care_guide")

    def test_inquiry_questions_say_the_feature_is_not_in_the_screen(self):
        """통합 화면에는 손님 문의 기능이 없다 (11/21). 문의를 물으면 그렇다고 알리고, 리뷰 분석 서비스는 부르지 않는다."""
        for q in ("문의가 들어온 게 없을까?", "알레르기 문의 들어온 거 있어?", "손님 문의 몇 개야?"):
            data = ask(self.client, q)
            self.assertEqual(data["reply"]["kind"], "care_no_inquiry", q)
            self.assertIn("손님 문의 기능", data["reply"]["text"])
            self.assertEqual(data["cards"], [])
        self.assertEqual(self.source.asked, [])

    def test_inquiry_notice_even_when_the_review_service_is_down(self):
        client, _ = client_with(AskingSource(fail=True))
        self.assertEqual(ask(client, "문의 들어온 거 있어?")["reply"]["kind"], "care_no_inquiry")

    def test_every_intent_has_buttons(self):
        for intent in ("complaints", "topic", "time", "trend", "unanswered", "howto", "score", "capture", "inquiry",
                       "rating", "channel", "recent", "praise", "overview"):
            self.assertTrue(ap.CARE_ACTIONS[intent], intent)


class Routing(unittest.TestCase):
    def test_customer_reaction_questions_go_to_care(self):
        for q in ("손님들이 맛에 대해 뭐라고 해?", "알레르기 문의 들어온 거 있어?", "평점 몇이야?", "칭찬 많이 받은 거 뭐야?",
                  "음식 식었다는 말 많아?"):
            self.assertEqual(domain_question(q), "care", q)

    def test_topic_questions_without_the_word_review_go_to_care(self):
        """11/21: '이번주 맛은 어때?'처럼 '리뷰'·'불만' 없이 음식·배달을 묻는 말이 상권 서비스로 갔다."""
        for q in ("이번주 맛에 대한 불만 리뷰는 몇 건이냐?", "이번주 맛은 어때?", "요즘 맛 평가 어때?", "양 적다는 말 있어?",
                  "배달 늦다는 말 많아?", "손님 반응 어때?", "직원 태도 얘기 있어?"):
            self.assertEqual(domain_question(q), "care", q)
        for q in ("맛집 상권 어디야?", "저녁 시간대 반응 어때?", "점심 매출 어때?", "직원 몇 명 뽑아야 해?"):
            self.assertNotEqual(domain_question(q), "care", q)

    def test_routing_fixes_from_live_check(self):
        """11/22 PR #75 live 확인: 상권 질문인데 고객응대로 가던 말 / 아직 상권으로 가던 손님 반응 말."""
        for q in ("20대 반응 어때?", "맛있는 메뉴 추천해줘", "다른 가게들 반응은?"):
            self.assertNotEqual(domain_question(q), "care", q)
        for q in ("우리 가게 평판 어때?", "손님들 만족해?", "손님들 뭐가 제일 불편했대?"):
            self.assertEqual(domain_question(q), "care", q)

    def test_market_time_and_sales_words_still_go_to_the_market_service(self):
        for q in ("점심 손님들이 많이 와?", "주말 문의 매출 어때?", "저녁 시간대 손님들이 뭐라고 해?"):
            self.assertIsNone(domain_question(q), q)


if __name__ == "__main__":
    unittest.main()
