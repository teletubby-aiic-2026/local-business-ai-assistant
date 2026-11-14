"""Several places in one question, units next to amounts, the development export and one rewrite.

User feedback 2026-11-08: '합정역과 강남역의 주 고객 연령대' asked to pick one place
and answered for it only; amounts were hard to read; the replies felt stiff;
and testing needed the conversation as a file instead of screenshots.
Synthetic markets and rows only: no raw statistics, no model, no Maps.
"""
from datetime import date
import os
import tempfile
import unittest
from unittest.mock import patch

from starlette.requests import Request

from app.assistant import templates
from app.assistant.answer_check import check_answer, comparison_problems, feedback
from app.assistant.korean import amount_words, with_units
from app.assistant.multi import lead_lines
from app.assistant.planner import to_classification
from tests.test_assistant_ranking import FakeRankingSource, _RankingEnv


class UnitTests(unittest.TestCase):
    def test_large_amounts_get_a_reading(self):
        self.assertEqual(amount_words(976474889, "원"), "약 9억 7,647만 원")
        self.assertEqual(amount_words(100000000, "원"), "1억 원")
        self.assertEqual(amount_words(5563124400780, "원"), "약 5조 5,631억 원")
        self.assertEqual(with_units("30대는 976,474,889원이에요. [F5]"), "30대는 976,474,889원(약 9억 7,647만 원)이에요. [F5]")
        self.assertEqual(with_units("유동인구는 7,433,594명이에요."), "유동인구는 7,433,594명(약 743만 명)이에요.")
        self.assertEqual(with_units("매출 12,000원, 195명"), "매출 12,000원, 195명", "small numbers stay as they are")
        self.assertEqual(with_units("30대(976,474,889원, 비중 37.22%)"), "30대(976,474,889원, 비중 37.22%)",
                         "no brackets inside brackets")


def _age_card(card_id, market, values):
    return {"id": card_id, "topic": "sales_age", "status": "available", "market": market,
            "text": f"{market} 상권의 연령별 매출입니다.",
            "values": [{"label": label, "value": value, "unit": "원", "market": market}
                       for label, value in zip(("10대", "20대", "30대", "40대"), values)]}


HAPJEONG = _age_card("F2", "합정역", (10, 300, 976, 200))
GANGNAM = _age_card("F3", "강남역", (20, 900, 800, 100))


class MultiCheckTests(unittest.TestCase):
    def test_each_market_is_checked_against_its_own_card(self):
        cards = [HAPJEONG, GANGNAM]
        self.assertEqual(comparison_problems("합정역은 30대가 가장 많아요. [F2]", cards), [])
        self.assertEqual([p["type"] for p in comparison_problems("강남역도 30대가 가장 많아요. [F3]", cards)],
                         ["wrong_superlative"])
        self.assertEqual(comparison_problems("30대 매출은 합정역이 강남역보다 많아요. [F2][F3]", cards), [])
        self.assertEqual([p["type"] for p in comparison_problems("20대 매출은 합정역이 강남역보다 많아요. [F2][F3]", cards)],
                         ["wrong_comparison"])
        self.assertEqual(comparison_problems("30대가 가장 많아요. [F2][F3]", cards), [], "which market is unclear")

    def test_the_fixed_answer_names_each_market_first(self):
        self.assertEqual(lead_lines([HAPJEONG, GANGNAM]), ["주 고객 연령대는 합정역 30대, 강남역 20대예요. [F2][F3]"])


class ModelBodyTests(unittest.TestCase):
    CARDS = [{"id": "F2", "topic": "sales_total", "status": "available", "text": "매출입니다.",
              "values": [{"label": "분기 추정매출", "value": 1000, "unit": "원"}]}]

    def test_a_closing_question_stays_last_and_other_uncited_lines_go(self):
        live = "매출은 1,000원이에요. [F2]\n주말 매출도 같이 볼까요?\n분위기가 좋은 곳이에요."
        self.assertEqual(templates.model_body(live, self.CARDS, show_conditions=False),
                         "매출은 1,000원이에요. [F2]\n주말 매출도 같이 볼까요?")

    def test_the_checker_findings_become_rewrite_instructions(self):
        problems = check_answer("매출은 2,000원이에요. [F2]", self.CARDS)["problems"]
        self.assertIn("'2,000'은 카드에 없는 숫자예요.", feedback(problems))


class PlannerPlacesTests(unittest.TestCase):
    def test_places_list_becomes_every_location(self):
        rule = {"turn_type": "unknown", "topics": [], "slots": {"locations": [], "industries": [],
                                                                "period": {"period_code": None}}}
        decided = to_classification("market_data", {"places": ["합정역", "강남역"], "topics": ["sales_age"]}, rule=rule,
                                    question="합정역과 강남역의 주 고객 연령대를 알려줘", use_morph=False,
                                    today=date(2026, 11, 8))
        self.assertEqual([m["text"] for m in decided["slots"]["locations"]], ["합정역", "강남역"])
        self.assertEqual(decided["topics"], ["sales_age"])


class _MultiSource(FakeRankingSource):
    """The fake catalogue's market 1111111 and 강남역 3000001 both have coffee sales."""


class MultiFlowTests(_RankingEnv, unittest.TestCase):
    def test_two_places_are_answered_side_by_side_without_changing_the_conditions(self):
        base = self.say("합정역 카페 매출 어때?")["conditions"]
        # 홍대입구역 is the saved synthetic market 1111111 in the fake source.
        data = self.say("홍대입구역과 강남역의 주 고객 연령대를 알려줘")
        reply = data["reply"]
        self.assertEqual(reply["kind"], "multi_market", reply["text"])
        ages = [card for card in data["cards"] if card["topic"] == "sales_age"]
        self.assertEqual([card.get("market") for card in ages], [base["area_name"], "강남역"])
        self.assertIn("주 고객 연령대는", reply["text"])
        self.assertEqual(data["conditions"]["area_code"], base["area_code"], "the saved market stays")
        # A follow-up without a place keeps both markets.
        again = self.say("매출은?")
        self.assertEqual(again["reply"]["kind"], "multi_market", again["reply"]["text"])
        self.assertEqual(len([card for card in again["cards"] if card["topic"] == "sales_total"]), 2)

    def test_one_other_place_compared_on_ages_reads_both(self):
        self.say("합정역 카페 매출 어때?")
        data = self.say("강남역이랑 연령대 비교해줘")
        self.assertEqual(data["reply"]["kind"], "multi_market", data["reply"]["text"])
        self.assertEqual([card.get("market") for card in data["cards"][1:] if card["topic"] == "sales_age"],
                         ["합성 상권 1111111", "강남역"])

    def test_a_rejected_model_text_is_rewritten_once(self):
        from app.assistant.bridge import endpoint_table, request_with_session
        from app.assistant.flow import AssistantService
        from app.assistant.history import AssistantHistory
        from app.onboarding import create_onboarding_router

        calls = []

        def writer(cards, cls):
            calls.append(cls.get("retry"))
            return ("매출은 9,999원이에요. [F2]" if len(calls) == 1
                    else "매출은 1,000원이에요. [F2]")

        service = AssistantService(self.store, AssistantHistory(self.store), endpoint_table(create_onboarding_router(self.store)),
                                   writer=writer, use_morph=False, today=date(2026, 11, 8), ranking_source=self.source)
        owner, token = self.store.session(None)
        scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}
        data = service.handle_message(owner, request_with_session(Request(scope), token), "합정역 카페 매출 어때?", None)
        self.assertTrue(data["model_used"], data["reply"]["text"])
        self.assertIsNone(calls[0])
        self.assertIn("9,999", calls[1]["previous"])
        self.assertIn("카드에 없는 숫자", calls[1]["feedback"])
        self.assertEqual(len(calls), 2)

    def test_the_conversation_exports_as_markdown_in_development_only(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"ASSISTANT_EXPORT_DIR": folder}):
            self.say("합정역 카페 매출 어때?")
            self.say("홍대입구역과 강남역의 주 고객 연령대를 알려줘")
            status = self.client.get("/api/assistant/status").json()
            self.assertTrue(status["export"])
            response = self.client.get("/api/assistant/conversation.md")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.headers["content-type"].startswith("text/markdown"))
            text = response.text
            self.assertIn("# 상권 비서 대화 기록", text)
            self.assertIn("## 2. 사용자: 홍대입구역과 강남역의 주 고객 연령대를 알려줘", text)
            self.assertIn("답 종류 multi_market", text)
            self.assertIn("근거 카드:", text)
            saved = response.headers.get("x-export-saved")
            self.assertTrue(saved and os.path.exists(os.path.join(folder, saved)))
            self.assertNotIn("debug", self.say("매출은?"), "the page never receives the decision details")
        with patch.dict(os.environ, {"ASSISTANT_EXPORT": "off"}):
            from app.assistant import export

            self.assertFalse(export.enabled(public_mode=False))
        self.assertFalse(export.enabled(public_mode=True))


class RoundTwoTests(unittest.TestCase):
    """Server export 2026-11-08: the subject in the sentence before, model-made ratios, wrong card numbers."""

    def test_the_subject_may_come_from_the_sentence_before(self):
        line = "두 상권 모두 20대 매출이 많아요. 다만, 합정역이 강남역보다 조금 더 높네요. [F2][F3]"
        self.assertEqual([p["type"] for p in comparison_problems(line, [HAPJEONG, GANGNAM])], ["wrong_comparison"])

    def test_the_rewrite_advice_names_the_card_that_holds_the_number(self):
        problems = check_answer("합정역 30대는 976원이에요. [F3]", [HAPJEONG, GANGNAM])["problems"]
        self.assertIn("'976'은 F2 카드의 숫자예요.", feedback(problems, [HAPJEONG, GANGNAM]))

    def test_bracketed_card_numbers_are_citations(self):
        body = templates.model_body("합정역 30대는 976원(F2)이에요.", [HAPJEONG, GANGNAM], show_conditions=False)
        self.assertEqual(body, "합정역 30대는 976원[F2]이에요.")

    def test_two_markets_get_their_ratios_from_code(self):
        from app.assistant.multi import ratio_card

        cards = [{"id": f"F{i}", "topic": "sales_total", "market": market, "status": "available", "text": "",
                  "values": [{"label": "분기 추정매출", "value": value, "unit": "원", "market": market}]}
                 for i, (market, value) in enumerate((("합정역", 2796964885), ("강남역", 13638954166)), start=2)]
        card = {**ratio_card(cards, [{"name": "합정역"}, {"name": "강남역"}]), "id": "F4"}
        self.assertIn("강남역 분기 추정매출은 합정역의 4.9배입니다.", card["text"])
        self.assertTrue(check_answer("강남역 매출이 합정역의 4.9배예요. [F4]", [card])["ok"])
        self.assertFalse(check_answer("강남역 매출이 합정역의 5배예요. [F4]", [card])["ok"])

    def test_endings_before_a_card_number_become_conversational(self):
        from app.assistant.korean import soften

        self.assertEqual(soften("합정역 상권에는 78개가 있습니다 [F5]"), "합정역 상권에는 78개가 있어요 [F5]")
        self.assertEqual(soften("비중 12.14%입니다 [F6]"), "비중 12.14%예요 [F6]")
