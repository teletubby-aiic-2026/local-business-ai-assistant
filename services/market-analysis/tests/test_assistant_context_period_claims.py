"""Source-quarter claims need checking even when a sentence repeats no figure."""
import unittest
from unittest.mock import Mock

from app.assistant import context
from app.assistant.answer_check import check_answer
from app.assistant.flow import AssistantService


def card(name="시험상권", workers="20261", residents="20262", card_id="F1"):
    figure = {"name": name, "workers": 5000, "residents": 900,
              "context_requested_period": "20262", "context_sources": {
                  dataset: {"dataset": dataset, "period": period, "requested_period": "20262"}
                  for dataset, period in (("workers", workers), ("residents", residents))}}
    return {**context.profile_card(figure), "id": card_id}


class ContextPeriodClaimTests(unittest.TestCase):
    def assert_valid(self, text, cards=None):
        result = check_answer(text, cards or [card()])
        self.assertTrue(result["ok"], result["problems"])

    def assert_mismatch(self, text, cards=None):
        result = check_answer(text, cards or [card()])
        self.assertIn("context_period_mismatch", {problem["type"] for problem in result["problems"]}, result)

    def test_named_metric_period_requires_no_statistic(self):
        for text in ("직장인구는 2026년 2분기 기준입니다. [F1]",
                     "2026년 2분기 기준 직장 인구 자료입니다. [F1]",
                     "직장인구 자료 기준분기는 2026년 2분기입니다. [F1]"):
            with self.subTest(text=text):
                self.assert_mismatch(text)

    def test_named_metric_correct_period_without_statistic(self):
        for text in ("직장인구는 2026년 1분기 기준입니다. [F1]",
                     "상주인구는 2026년 2분기 기준입니다. [F1]",
                     "직장 인구 자료 기준분기는 2026년 1분기입니다. [F1]"):
            with self.subTest(text=text):
                self.assert_valid(text)

    def test_omitting_a_citation_cannot_bypass_an_explicit_period_claim(self):
        self.assert_mismatch("직장인구는 2026년 2분기 기준입니다.")
        self.assert_valid("직장인구는 2026년 1분기 기준입니다.")
        self.assert_mismatch("직장인구는 5,000명이고 상주인구는 900명입니다. [F1]\n"
                             "두 자료 모두 2026년 2분기 기준입니다.")

    def test_uncited_collective_keeps_the_preceding_cited_card_scope(self):
        cards = [card(), card("다른상권", workers="20262", card_id="F2")]
        self.assert_valid("직장인구는 5,000명이고 상주인구는 900명입니다. [F2]\n"
                          "두 자료 모두 2026년 2분기 기준입니다.", cards)
        self.assert_valid("다른상권 직장인구는 2026년 2분기 기준입니다.", cards)
        self.assert_mismatch("시험상권 직장인구는 2026년 2분기 기준입니다.", cards)

    def test_collective_date_after_figures_is_checked(self):
        prefix = "직장인구는 5,000명이고 상주인구는 900명입니다. [F1]\n"
        for subject in ("두 자료 모두", "모든 자료는", "둘 다", "모두", "전부"):
            with self.subTest(subject=subject):
                self.assert_mismatch(prefix + subject + " 2026년 2분기 기준이에요. [F1]")

    def test_collective_date_in_same_citation_segment_is_checked(self):
        self.assert_mismatch("직장인구는 5,000명이고 상주인구는 900명입니다. 두 자료 모두 2026년 2분기 기준이에요. [F1]")
        self.assert_mismatch("직장인구와 상주인구는 모두 2026년 2분기 기준입니다. [F1]")

    def test_collective_date_is_valid_when_both_sources_match(self):
        self.assert_valid("직장인구는 5,000명이고 상주인구는 900명입니다. [F1]\n"
                          "두 자료 모두 2026년 2분기 기준이에요. [F1]", [card(workers="20262")])

    def test_all_sources_claim_does_not_inherit_only_the_last_metric(self):
        self.assert_mismatch("상주인구는 900명입니다. [F1]\n모든 자료는 2026년 2분기 기준입니다. [F1]")

    def test_separate_correct_dates_and_explicit_two_quarter_contrast(self):
        for text in ("직장인구는 2026년 1분기, 상주인구는 2026년 2분기 기준입니다. [F1]",
                     "직장인구는 2026년 1분기 자료이며 상주인구는 2026년 2분기 자료입니다. [F1]",
                     "직장인구는 2026년 2분기가 아닌 2026년 1분기 자료입니다. [F1]",
                     "직장인구 자료는 선택한 2026년 2분기보다 이전인 2026년 1분기 기준입니다. [F1]"):
            with self.subTest(text=text):
                self.assert_valid(text)

    def test_explicit_current_data_unavailability_is_not_a_date_claim(self):
        for text in ("2026년 2분기 직장인구 자료는 없고, 이전 분기 값은 5,000명입니다. [F1]",
                     "2026년 2분기 직장인구 자료는 없어서 이전 값 5,000명을 사용합니다. [F1]",
                     "2026년 2분기 직장인구 자료를 확인할 수 없어 이전 값 5,000명을 사용합니다. [F1]"):
            with self.subTest(text=text):
                self.assert_valid(text)

    def test_missing_data_explanation_does_not_hide_another_wrong_claim(self):
        self.assert_mismatch("2026년 2분기 직장인구 자료는 없고, 상주인구는 2026년 1분기 기준입니다. [F1]")

    def test_one_card_multiple_markets_preserves_explicit_scope(self):
        first, second = card("강남역"), card("합정역", workers="20262", residents="20262")
        merged = {**first, "values": first["values"] + second["values"], "text": first["text"] + second["text"]}
        for text in ("강남역 직장인구는 2026년 1분기 기준입니다. [F1]",
                     "합정역 직장인구는 2026년 2분기 기준입니다. [F1]",
                     "강남 직장인구는 2026년 1분기, 합정 직장인구는 2026년 2분기 기준입니다. [F1]",
                     "합정역 직장인구는 5,000명이고 상주인구는 900명입니다. [F1]\n"
                     "합정역의 두 자료 모두 2026년 2분기 기준입니다. [F1]"):
            with self.subTest(text=text):
                self.assert_valid(text, [merged])
        self.assert_mismatch("강남역 직장인구는 2026년 2분기 기준입니다. [F1]", [merged])
        self.assert_mismatch("강남역과 합정역 직장인구는 모두 2026년 2분기 기준입니다. [F1]", [merged])

    def test_collective_citation_scope_does_not_include_another_card(self):
        self.assert_valid("직장인구는 5,000명이고 상주인구는 900명입니다. [F2]\n"
                          "두 자료 모두 2026년 2분기 기준입니다. [F2]",
                          [card(), card("다른상권", workers="20262", card_id="F2")])

    def test_collective_subjects_keep_the_market_named_before_the_figures(self):
        first, second = card("강남역", residents="20261"), card("합정역", workers="20262")
        merged = {**first, "values": first["values"] + second["values"], "text": first["text"] + second["text"]}
        self.assert_valid("합정역 직장인구는 5,000명이고 상주인구는 900명입니다. [F1]\n"
                          "두 자료 모두 2026년 2분기 기준입니다. [F1]", [merged])
        self.assert_mismatch("강남역 직장인구는 5,000명이고 상주인구는 900명입니다. [F1]\n"
                             "두 자료 모두 2026년 2분기 기준입니다. [F1]", [merged])

    def test_wrong_collective_date_retries_and_falls_back(self):
        evidence = card()
        service = AssistantService.__new__(AssistantService)
        service.writer = Mock(return_value="직장인구는 5,000명이고 상주인구는 900명입니다. [F1]\n"
                                          "두 자료 모두 2026년 2분기 기준이에요. [F1]")
        reply = service._write([evidence], {"text": "직장인구와 상주인구 기준분기를 알려줘"})
        self.assertFalse(reply["model_used"])
        self.assertEqual(service.writer.call_count, 2)
        self.assertIn("context_period_mismatch", {problem["type"] for problem in reply["model_rejected"]})


if __name__ == "__main__":
    unittest.main()
