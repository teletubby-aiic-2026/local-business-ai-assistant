"""Regressions from the bounded cloud model comparison; all model replies are replayed.

No model, source API, credentials or database is used by these tests.
"""
from copy import deepcopy
import unittest
from unittest.mock import Mock

from app.assistant.answer_check import check_answer, comparison_problems, has_statistics, interpretation_line, statistics
from app.assistant.flow import AssistantService
from app.assistant.templates import model_body


TIME = {"id": "F4", "topic": "sales_time", "status": "available", "text": "시간대별 매출입니다.",
        "values": [{"label": "11~14시", "value": 4_972_053_609, "unit": "원", "share_percent": 36.45},
                   {"label": "17~21시", "value": 3_118_504_113, "unit": "원", "share_percent": 22.86},
                   {"label": "21~24시", "value": 678_696_036, "unit": "원"}], "warnings": []}
MONTHS = {"id": "F11", "topic": "area_profile", "status": "available", "text": "평균 영업 기간 자료입니다.",
          "values": [{"label": "운영 중 가게 평균 영업 기간", "value": 109, "unit": "개월"},
                     {"label": "서울 운영 중 가게 평균 영업 기간", "value": 118, "unit": "개월"},
                     {"label": "자료 기준분기", "value": "2026년 2분기", "unit": None}], "warnings": []}


def kinds(text, cards=None):
    return [problem["type"] for problem in comparison_problems(text, cards or [TIME])]


class LiveComparisonTests(unittest.TestCase):
    def test_month_durations_cannot_drop_remainder_by_converting_to_years(self):
        for shown in ("9년", "약 9년", "9년 5개월", "9년 1개월", "9.1년"):
            with self.subTest(shown=shown):
                result = check_answer(f"평균 영업 기간은 {shown}이에요. [F11]", [MONTHS])
                self.assertIn("duration_unit_changed", [p["type"] for p in result["problems"]])

    def test_calendar_year_and_exact_month_value_remain_valid(self):
        result = check_answer("2026년 2분기 평균 영업 기간은 109개월이에요. [F11]", [MONTHS])
        self.assertTrue(result["ok"], result)

    def test_year_conversion_is_also_rejected_in_interpretation(self):
        result = check_answer("해석: 대략 9년 정도 유지하는 가게들일 수 있어요.", [MONTHS])
        self.assertIn("duration_unit_changed", [p["type"] for p in result["problems"]])

    def test_live_reversed_comparison_is_rejected_after_model_body(self):
        raw = ("점심에 비해 저녁 매출이 높아요. [F4]\n"
               "점심(11~14시) 매출은 4,972,053,609원(36.45%)이고, "
               "저녁(17~21시) 매출은 3,118,504,113원(22.86%)이에요. [F4]")
        body = model_body(raw, [TIME], show_conditions=False)
        result = check_answer(body, [TIME])
        self.assertFalse(result["ok"])
        self.assertIn("wrong_comparison", [problem["type"] for problem in result["problems"]])
        service = AssistantService.__new__(AssistantService)
        service.writer = Mock(return_value=raw)
        result = service._write([TIME], {"text": "점심과 저녁 매출을 비교해줘"}, show_conditions=False)
        self.assertFalse(result["model_used"])
        self.assertEqual(service.writer.call_count, 2)

    def test_reference_markers_support_both_word_orders_and_both_directions(self):
        for marker in ("보다", "에 비해", "에 비해서", "에 비하면", "에 비하여", "과 비교하면", "과 비교해서", " 대비"):
            for text, expected in (
                (f"점심{marker} 저녁 매출이 높아요.", ["wrong_comparison"]),
                (f"저녁 매출은 점심{marker} 높아요.", ["wrong_comparison"]),
                (f"점심{marker} 저녁 매출이 낮아요.", []),
                (f"저녁 매출은 점심{marker} 낮아요.", []),
                (f"저녁{marker} 점심 매출이 높아요.", []),
                (f"점심 매출은 저녁{marker} 낮아요.", ["wrong_comparison"]),
            ):
                with self.subTest(text=text):
                    self.assertEqual(kinds(text), expected)

    def test_comparison_supports_numeric_time_and_day_aliases(self):
        self.assertEqual(kinds("오후 5시부터 9시와 비교하면 점심 매출이 낮아요."), ["wrong_comparison"])
        self.assertEqual(kinds("11~14시 대비 저녁 매출이 낮아요."), [])
        days = {"id": "F3", "topic": "sales_weekday", "values": [
            {"label": "월", "value": 200, "unit": "원"}, {"label": "토", "value": 100, "unit": "원"}]}
        self.assertEqual(kinds("월요일에 비해 토요일 매출이 높아요.", [days]), ["wrong_comparison"])
        self.assertEqual(kinds("토요일 매출은 월요일 대비 적어요.", [days]), [])

    def test_market_name_aliases_and_metric_gap_are_preserved(self):
        markets = {"id": "F5", "topic": "comparison", "values": [
            {"label": "추정매출", "market": "강남역", "value": 200, "unit": "원"},
            {"label": "추정매출", "market": "연남동(홍대)", "value": 100, "unit": "원"}]}
        self.assertEqual(kinds("홍대와 비교하면 강남 매출이 높아요.", [markets]), [])
        self.assertEqual(kinds("강남역의 매출에 비해 연남동 매출이 높아요.", [markets]), ["wrong_comparison"])
        self.assertEqual(kinds("홍대 매출은 강남역 대비 낮아요.", [markets]), [])

    def test_equal_values_do_not_support_greater_or_less_claims(self):
        card = deepcopy(TIME)
        card["values"][1]["value"] = card["values"][0]["value"]
        for word in ("높아요", "낮아요"):
            with self.subTest(word=word):
                self.assertEqual(kinds(f"점심에 비해 저녁 매출이 {word}.", [card]), ["wrong_comparison"])
        for word in ("높지 않아요", "낮지 않아요"):
            with self.subTest(word=word):
                self.assertEqual(kinds(f"점심에 비해 저녁 매출이 {word}.", [card]), [])

    def test_negated_comparisons_preserve_the_existing_abstention_rule(self):
        # The existing checker deliberately does not infer a numeric order from negation.
        for text in ("점심에 비해 저녁 매출이 높지 않아요.", "점심에 비해 저녁 매출이 낮지 않아요.",
                     "점심 매출은 저녁 대비 낮은 편은 아니에요.", "저녁 매출은 점심 대비 낮은 편은 아니에요."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), [])

    def test_an_unrelated_period_marker_does_not_hide_a_later_comparison(self):
        self.assertEqual(kinds("지난 분기 대비 매출을 보면 점심이 저녁보다 낮아요."), ["wrong_comparison"])
        self.assertEqual(kinds("점심에 비해 저녁은 낮고 저녁에 비해 밤 매출은 높아요."), ["wrong_comparison"])


class DurationStatisticsTests(unittest.TestCase):
    def test_month_duration_is_a_statistic_but_calendar_labels_are_not(self):
        text = "2026년 2분기의 평균 영업 기간은 109개월이에요. [F11]"
        self.assertEqual(statistics(text, [MONTHS]), ["109"])
        self.assertTrue(has_statistics(text, [MONTHS]))
        self.assertTrue(check_answer(text, [MONTHS])["ok"])

    def test_wrong_or_uncited_month_count_is_checked(self):
        for text, expected in (("평균 영업 기간은 999개월이에요. [F11]", "number_not_on_card"),
                               ("평균 영업 기간은 109개월이에요.", "uncited_number")):
            with self.subTest(text=text):
                self.assertIn(expected, [p["type"] for p in check_answer(text, [MONTHS])["problems"]])

    def test_month_count_cannot_hide_in_an_interpretation_line(self):
        line = "평균 영업 기간이 109개월인 것으로 보여요. [F11]"
        self.assertFalse(interpretation_line(line, [MONTHS]))
        self.assertIn("number_in_interpretation", [p["type"] for p in check_answer("해석: " + line, [MONTHS])["problems"]])

    def test_live_109_month_reply_is_not_rejected_as_numberless(self):
        raw = "운영 중인 가게들의 평균 영업 기간은 109개월이에요. [F11]"
        service = AssistantService.__new__(AssistantService)
        service.writer = Mock(return_value=raw)
        reply = service._write([MONTHS], {"text": "평균 영업 기간을 알려줘"}, show_conditions=False)
        self.assertTrue(reply["model_used"])
        self.assertEqual(service.writer.call_count, 1)


if __name__ == "__main__":
    unittest.main()
