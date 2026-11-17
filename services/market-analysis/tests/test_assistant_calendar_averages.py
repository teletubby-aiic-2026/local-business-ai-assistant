"""Calendar-day regression cases for quarterly sales, without raw data or external calls."""
from copy import deepcopy
import unittest

from app.assistant.facts import sales_cards, weekday_aggregates
from app.assistant.overview import summed_cards
from app.assistant.templates import focus_line
from app.data_repository import DISTRIBUTION_FIELDS
from app.onboarding_sales import analyze_sales_row
from tests.test_assistant_allind import _AllSource


def _days(amounts=(1300, 1300, 1300, 1300, 1300, 2600, 2600)):
    return [{"label": label, "value": value, "unit": "원"}
            for label, value in zip("월화수목금토일", amounts)]


class CalendarAverageTests(unittest.TestCase):
    def test_quarter_calendar_counts_include_leap_day_and_year_end(self):
        # Independent calendar expectations: 2024 Q1 starts Monday and ends Sunday (13 full weeks).
        # 2023 Q1 is one day shorter; 2026 Q1 has 64 weekdays; 2025 Q4 spans 92 calendar days.
        for period, weekday_days, weekend_days, weekday_average, weekend_average in (
            ("20262", 65, 26, 100, 200),
            ("20241", 65, 26, 100, 200),
            ("20231", 65, 25, 100, 208),
            ("20261", 64, 26, 102, 200),
            ("20254", 66, 26, 98, 200),
        ):
            with self.subTest(period=period):
                extra, sentence = weekday_aggregates(_days(), period)
                by_label = {item["label"]: item for item in extra}
                self.assertEqual(by_label["평일 합계"]["value"], 6500)
                self.assertEqual(by_label["주말 합계"]["value"], 5200)
                for label, count, amount in (("평일 하루 평균", weekday_days, weekday_average),
                                             ("주말 하루 평균", weekend_days, weekend_average)):
                    self.assertEqual(by_label[label]["value"], amount)
                    self.assertEqual(by_label[label]["denominator_days"], count)
                    self.assertEqual(by_label[label]["average_basis"], "calendar_day")
                    self.assertEqual(by_label[label]["period"], period)
                self.assertIn("원 단위 반올림", sentence)
                self.assertIn("가게의 실제 영업일 평균은 아닙니다", sentence)

    def test_half_won_rounds_up_and_observed_zero_is_retained(self):
        extra, _ = weekday_aggregates(_days((0, 0, 0, 0, 0, 13, 0)), "20262")
        values = {item["label"]: item["value"] for item in extra}
        self.assertEqual(values["평일 하루 평균"], 0)
        self.assertEqual(values["주말 하루 평균"], 1)  # 13 / 26 = 0.5 won, half up.

    def test_unknown_or_invalid_period_keeps_totals_and_withholds_averages(self):
        for period in (None, "", "2026", "2026Q2", "20260", "20265", "00001", " 20262", 20262, True):
            with self.subTest(period=period):
                extra, sentence = weekday_aggregates(_days(), period)
                self.assertEqual({item["label"]: item["value"] for item in extra},
                                 {"평일 합계": 6500, "주말 합계": 5200})
                self.assertIn("하루 평균은 계산하지 않았습니다", sentence)
                card = {"id": "F2", "topic": "sales_weekday", "values": _days() + extra}
                focused = focus_line(card, "주말이랑 평일은?")
                self.assertIn("주말(토·일)은 합계 5,200원", focused)
                self.assertNotIn("하루 평균", focused)

    def test_incomplete_duplicate_negative_and_noninteger_days_are_not_aggregated(self):
        invalid = [_days()[:-1], _days() + [{"label": "월", "value": 1}],
                   _days((-1, 0, 0, 0, 0, 0, 0)), _days((True, 0, 0, 0, 0, 0, 0)),
                   _days((1.5, 0, 0, 0, 0, 0, 0)), _days((None, 0, 0, 0, 0, 0, 0))]
        for values in invalid:
            with self.subTest(values=values):
                self.assertEqual(weekday_aggregates(values, "20262"), ([], ""))

    def test_single_market_uses_real_b2_selection_period(self):
        selection = {"area_code": "1111111", "area_name": "합성 상권", "industry_code": "CS100010",
                     "period": "20261", "period_label": "2026년 1분기", "catalog_version": "test", "boundary": {}}
        row = {"THSMON_SELNG_AMT": 11700}
        row.update({field: item["value"] for (_, field), item in zip(DISTRIBUTION_FIELDS["sales_weekday"], _days())})
        result = analyze_sales_row(row, selection, "커피-음료")
        card = next(card for card in sales_cards(result) if card["topic"] == "sales_weekday")
        average = next(item for item in card["values"] if item["label"] == "평일 하루 평균")
        self.assertEqual((average["value"], average["denominator_days"], average["period"]), (102, 64, "20261"))
        self.assertTrue(any("달력일" in note and "실제 영업일" in note for note in card["warnings"]))
        missing = deepcopy(result)
        missing["selection"].pop("period")
        missing_card = next(card for card in sales_cards(missing) if card["topic"] == "sales_weekday")
        self.assertFalse(any("하루 평균" in item["label"] for item in missing_card["values"]))
        self.assertIn("평일 합계", {item["label"] for item in missing_card["values"]})

    def test_all_industry_and_seoul_sums_use_the_selected_quarter(self):
        for area in ({"area_code": "3000001", "area_name": "강남역"}, {}):
            with self.subTest(area=area):
                cards = summed_cards(_AllSource(), ["sales_weekday"], period="20261", **area)
                card = next(card for card in cards if card["topic"] == "sales_weekday")
                average = next(item for item in card["values"] if item["label"] == "평일 하루 평균")
                self.assertEqual((average["denominator_days"], average["period"]), (64, "20261"))
                self.assertIn("달력일 기준 하루 평균", card["speech"])
                self.assertIn("실제 영업일 평균은 아닙니다", card["speech"])


if __name__ == "__main__":
    unittest.main()
