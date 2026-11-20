"""평일·주말 비교와 '순' 나열 검사 (2026-11-19). 외부 호출 없음.

HCX-005 가 실제로 쓴 답(로컬 live, 가게 3곳 × 질문 2개, 모델 답 29개 중 14개가 틀림)을 그대로 옮겨 둔다.
숫자는 서울시 공공 자료의 상권·업종 분기 합계다(가게 한 곳의 매출이 아님).
- 평일 65일 합계와 주말 26일 합계를 그대로 견준 답, 한 문장 안에서 숫자와 결론이 반대인 답
- '토, 다음으로 금, 일 순' 처럼 값의 크기와 다른 나열

실행 (services/market-analysis 에서):  python -m unittest tests.test_assistant_weekpart_order
"""
import unittest

from app.assistant.answer_check import check_answer, feedback, order_problems, weekpart_problems
from app.assistant.clova_client import SYSTEM_PROMPT
from app.assistant.facts import size_order, weekday_aggregates, weekpart_verdict

PERIOD = "20262"  # 평일 65일, 주말 26일
ONGI = (185970717, 247969404, 243401279, 223289295, 298218280, 340322049, 301258663)   # 하루 평균은 주말이 큼
BASAK = (3934908, 11159362, 14322343, 15536901, 23451136, 21618775, 14937697)          # 하루 평균은 주말이 큼
MONGLE = (30065497, 36576309, 34450545, 37035864, 39260460, 37745599, 28245661)        # 하루 평균도 평일이 큼


def _cards(amounts, period=PERIOD):
    days = [{"label": label, "value": value, "unit": "원"} for label, value in zip("월화수목금토일", amounts)]
    extra, sentence = weekday_aggregates(days, period)
    return [{"id": "F1", "topic": "conditions", "status": "available", "text": "분석 조건", "values": []},
            {"id": "F3", "topic": "sales_weekday", "status": "available",
             "text": "요일별 매출" + size_order(days) + sentence, "values": days + extra}]


def _types(problems):
    return [problem["type"] for problem in problems]


class WeekpartComparisonTests(unittest.TestCase):
    def test_live_answers_that_compared_totals_are_rejected(self):
        cards = _cards(BASAK)
        for text in (
            "평일에 더 잘 팔려요. [F3]",
            "평일 손님이 조금 더 많은 상권일 수 있어요.",
            "주말보다 평일에 손님이 많다는 뜻일 수 있어요.",
            "평일과 주말을 나누어 보아도, 주말보다 평일이 전반적으로 매출이 좋아요. [F3]",
            "평일의 유동 인구가 더 많은 상권일 가능성이 있어요.",
        ):
            with self.subTest(text=text):
                self.assertEqual(_types(weekpart_problems(text, cards)), ["wrong_weekpart_comparison"])

    def test_a_sentence_whose_figures_contradict_its_own_conclusion_is_rejected(self):
        cards = _cards(BASAK)
        for text in (
            "전체적으로 봤을 때는 평일 매출(합계 68,404,650원)보다 주말(36,556,472원)에 더 많은 편이에요. [F3]",
            "전체적으로 봤을 때는 평일 매출(합계 68,404,650원)보다는 주말 매출(36,556,472원)이 높아요. [F3]",
        ):
            with self.subTest(text=text):
                self.assertEqual(_types(weekpart_problems(text, cards)), ["wrong_weekpart_comparison"])

    def test_answers_that_follow_the_daily_average_pass(self):
        for amounts, text in (
            (BASAK, "평일보다 주말에 매출이 조금 더 많아요. [F3]"),
            (BASAK, "평일은 하루 평균 1,052,379원, 주말은 1,406,018원으로 주말이 조금 더 많네요. [F3]"),
            (ONGI, "주말에 더 많이 팔려요. [F3]"),
            (MONGLE, "평일에 더 잘 팔려요. [F3]"),
            (MONGLE, "평일 고객 수요가 조금 더 높다고 할 수 있어요. [F3]"),
            (MONGLE, "평일에 손님이 조금 더 많지만, 주말에도 꽤 많은 손님을 모을 수 있어요."),
        ):
            with self.subTest(text=text):
                self.assertEqual(weekpart_problems(text, _cards(amounts)), [])

    def test_a_true_statement_about_totals_passes_and_a_false_one_does_not(self):
        cards = _cards(BASAK)
        self.assertEqual(weekpart_problems("합계로는 평일이 주말보다 커요. [F3]", cards), [])
        self.assertEqual(_types(weekpart_problems("합계로는 주말이 평일보다 커요. [F3]", cards)),
                         ["wrong_weekpart_comparison"])

    def test_statements_without_a_claim_are_left_alone(self):
        cards = _cards(BASAK)
        for text in (
            "평일은 총 68,404,650원, 주말은 36,556,472원이에요. [F3]",
            "평일에는 금요일에, 주말에는 토요일 매출이 제일 높아요. [F3]",
            "평일과 주말 매출도 비교해 볼까요?",
            "주말에도 저녁이 더 강한지 같이 볼까요?",
            "주말에 손님을 더 많이 받을 수 있도록 준비를 조금 더 해두시면 좋겠어요.",
            "주말보다 금요일이 더 높아요. [F3]",
        ):
            with self.subTest(text=text):
                self.assertEqual(weekpart_problems(text, cards), [])

    def test_without_calendar_averages_or_with_equal_ones_nothing_is_judged(self):
        self.assertEqual(weekpart_problems("평일에 더 잘 팔려요. [F3]", _cards(BASAK, period=None)), [])
        even = (26, 26, 26, 26, 26, 26, 26)  # 130 / 65 = 52 / 26
        self.assertEqual(weekpart_problems("평일에 더 잘 팔려요. [F3]", _cards(even)), [])

    def test_two_markets_in_one_answer_are_not_judged(self):
        cards = _cards(BASAK)
        other = _cards(MONGLE)[1]
        for card, market in ((cards[1], "상도역"), (other, "장승배기역")):
            for value in card["values"]:
                value["market"] = market
        other["id"] = "F4"
        self.assertEqual(weekpart_problems("평일에 더 잘 팔려요. [F3]", cards + [other]), [])


class ListedOrderTests(unittest.TestCase):
    def test_live_answers_with_friday_before_sunday_are_rejected(self):
        cards = _cards(ONGI)
        for text in (
            "요일별로 살펴보면, 토 매출이 제일 높고, 다음으로 금, 일 순이에요. [F3]",
            "요일별로 살펴보면, 토 매출이 가장 많고, 다음으로 금, 일 순으로 많아요. [F3]",
            "요일별로 살펴보면, 토요일 매출이 제일 높고, 다음으로 금요일, 일요일 순이에요. [F3]",
            "토요일 매출이 340,322,049원으로 가장 많고, 그다음으로 금요일(298,218,280원), "
            "일요일(301,258,663원) 순으로 높아요. [F3]",
        ):
            with self.subTest(text=text):
                problems = order_problems(text, cards)
                self.assertEqual(_types(problems), ["wrong_order"])
                self.assertIn("일 301,258,663 > 금 298,218,280", problems[0]["detail"])

    def test_orders_that_follow_the_values_pass(self):
        for amounts, text in (
            (ONGI, "요일별로는 토 매출이 제일 높고, 다음으로 일, 금 순이에요. [F3]"),
            (ONGI, "토요일, 일요일, 금요일 순으로 매출이 높아요. [F3]"),
            (BASAK, "금요일 매출이 23,451,136원으로 가장 높고, 다음으로는 목요일(15,536,901원)과 "
                    "수요일(14,322,343원) 순이에요. [F3]"),
            (ONGI, "월, 목, 수 순으로 매출이 낮아요. [F3]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(order_problems(text, _cards(amounts)), [])

    def test_an_ascending_list_is_checked_the_other_way(self):
        self.assertEqual(_types(order_problems("월, 수, 목 순으로 매출이 낮아요. [F3]", _cards(ONGI))), ["wrong_order"])

    def test_an_order_of_telling_is_not_an_order_of_size(self):
        cards = _cards(ONGI)
        for text in ("월, 화, 수 순으로 볼게요. [F3]", "요일별로 금, 토, 일 순서로 살펴볼까요?",
                     "평일과 주말 순으로 정리했어요."):
            with self.subTest(text=text):
                self.assertEqual(order_problems(text, cards), [])

    def test_day_letters_inside_other_words_are_not_days(self):
        # '요일별'·'평일'·'매일' 의 '일', '금액' 의 '금' 은 요일이 아니다.
        cards = _cards(ONGI)
        self.assertEqual(order_problems("요일별 금액은 토, 일 순으로 높아요. [F3]", cards), [])
        self.assertEqual(order_problems("매일 팔리는 금액으로는 평일보다 토, 일 순으로 높아요. [F3]", cards), [])

    def test_time_slots_and_ages_are_checked_too(self):
        times = [{"label": label, "value": value, "unit": "원"} for label, value in
                 (("11~14시", 300), ("14~17시", 150), ("17~21시", 400), ("21~24시", 50))]
        ages = [{"label": f"{n}대", "value": value, "unit": "원"} for n, value in ((20, 100), (30, 300), (40, 200))]
        cards = [{"id": "F2", "topic": "sales_time", "status": "available", "text": "", "values": times},
                 {"id": "F4", "topic": "sales_age", "status": "available", "text": "", "values": ages}]
        self.assertEqual(_types(order_problems("점심, 저녁, 오후 순으로 매출이 높아요. [F2]", cards)), ["wrong_order"])
        self.assertEqual(order_problems("저녁, 점심, 오후 순으로 매출이 높아요. [F2]", cards), [])
        self.assertEqual(_types(order_problems("20대, 30대, 40대 순으로 매출이 많아요. [F4]", cards)), ["wrong_order"])
        self.assertEqual(order_problems("30대, 40대, 20대 순으로 매출이 많아요. [F4]", cards), [])


class WiringTests(unittest.TestCase):
    def test_check_answer_rejects_both_and_tells_the_writer_how_to_fix_them(self):
        cards = _cards(ONGI)
        result = check_answer("토 매출이 제일 높고, 다음으로 금, 일 순이에요. [F3]\n평일에 더 잘 팔려요. [F3]", cards)
        self.assertFalse(result["ok"])
        self.assertEqual(set(_types(result["problems"])), {"wrong_order", "wrong_weekpart_comparison"})
        advice = feedback(result["problems"], cards)
        self.assertIn("큰 순서", advice)
        self.assertIn("하루 평균", advice)

    def test_a_correct_answer_still_passes_the_whole_check(self):
        text = ("주말에 더 많이 팔려요. [F3]\n"
                "주말은 하루 평균 24,676,181원이고 평일은 18,443,830원이에요. [F3]\n"
                "토 매출이 제일 높고, 다음으로 일, 금 순이에요. [F3]")
        self.assertEqual(check_answer(text, _cards(ONGI)), {"ok": True, "problems": []})


class CardSentenceTests(unittest.TestCase):
    def test_the_card_states_which_part_is_larger_per_day(self):
        _extra, sentence = weekday_aggregates(_cards(BASAK)[1]["values"][:7], PERIOD)
        self.assertIn("하루 평균으로 견주면 주말이 평일보다 많습니다.", sentence)
        self.assertIn("합계는 평일 65일치와 주말 26일치를 더한 값이라 합계끼리는 견주지 않습니다.", sentence)
        self.assertTrue(sentence.endswith("가게의 실제 영업일 평균은 아닙니다."))

    def test_no_day_count_caveat_when_totals_and_averages_agree(self):
        _extra, sentence = weekday_aggregates(_cards(MONGLE)[1]["values"][:7], PERIOD)
        self.assertIn("하루 평균으로 견주면 평일이 주말보다 많습니다.", sentence)
        self.assertNotIn("합계끼리는", sentence)

    def test_no_verdict_for_equal_averages_or_an_unknown_period(self):
        self.assertEqual(weekpart_verdict(130, 52, [2, 2], (65, 26)), "")
        _extra, sentence = weekday_aggregates(_cards(BASAK)[1]["values"][:7], None)
        self.assertNotIn("견주면", sentence)

    def test_size_order_is_written_out_only_when_it_is_certain(self):
        days = _cards(ONGI)[1]["values"][:7]
        self.assertEqual(size_order(days), " 큰 순서는 토, 일, 금, 화, 수, 목, 월입니다.")
        tied = [dict(day) for day in days]
        tied[0]["value"] = tied[1]["value"]
        self.assertEqual(size_order(tied), "")
        self.assertEqual(size_order(days[:2]), "")
        self.assertEqual(size_order(days[:6] + [{"label": "일", "value": None}]), "")

    def test_the_new_card_sentences_do_not_trip_the_number_check(self):
        cards = _cards(BASAK)
        text = "하루 평균으로 견주면 주말이 평일보다 많아요. 합계는 평일 65일치와 주말 26일치를 더한 값이에요. [F3]"
        self.assertEqual(check_answer(text, cards), {"ok": True, "problems": []})

    def test_the_writer_is_told_the_rule(self):
        self.assertIn("'하루 평균'으로만 견준다", SYSTEM_PROMPT)
        self.assertIn("'큰 순서'를 그대로 따른다", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
