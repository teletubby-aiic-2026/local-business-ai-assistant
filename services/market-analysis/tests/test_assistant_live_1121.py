"""서랍 상권 답의 숫자·비교 검사 (2026-11-21). 외부 호출 없음.

HCX-005 가 실시간 서버(이 PC, 새 가게 '동네맛김밥' 분식·홍대입구역(홍대)·2026년 2분기, 예시 가게 온기한식)에서 실제로 쓴
답을 그대로 옮겨 둔다. 숫자는 서울시 공공 자료의 상권·업종 분기 합계다(가게 한 곳의 매출이 아님).
- M4: 작년 대비 증가액 135,101,464원을 '13억 5천만 원 정도'로 읽음 (3번 중 3번, 모두 게시됨). 검사기가 '13억'을 작년 매출
  13억 2,065만과 1억 안에서 맞다고 보고, '5천만'의 '5'를 카드의 '개업 점포 5개 감소'로 보아 놓쳤다.
- M5: '주말 매출이 더 높아요' 뒤에 주말·평일 합계만 나란히 (주말 4.97억 < 평일 9.58억), '훨씬'(하루 평균 차이 +30%)
- 11: 기준 없는 평가('많은 편', '괜찮은 매출 규모', '경쟁해야 할 점포가 많다는 걸 의미해요'), 메뉴 권유, 같은 문장 두 번
- 10: '약 14억 5,575만 원'(내림) ↔ 화면 '14억 5,576만 원'(반올림)

실행 (services/market-analysis 에서):  python -m unittest tests.test_assistant_live_1121
"""
import unittest

from app.assistant.answer_check import check_answer, feedback
from app.assistant.facts import changes_card, size_order, weekday_aggregates
from app.assistant.intent import classify
from app.assistant.korean import amount_words, with_units

PERIOD = "20262"
NEW_DAYS = (176358295, 191940640, 176213243, 194352017, 219589406, 301930775, 195371691)   # 하루 평균은 주말이 큼(+30%)
YOY = {"status": "available", "previous_period": {"code": "20252", "label": "2025년 2분기"}, "metrics": [
    {"key": "sales", "label": "추정매출", "unit": "원", "status": "available", "current": {"value": 1455756067},
     "previous": {"value": 1320654603}, "delta": 135101464, "percent": 10.23},
    {"key": "stores_total", "label": "전체 점포", "unit": "개", "status": "available", "current": {"value": 47},
     "previous": {"value": 53}, "delta": -6, "percent": -11.32},
    {"key": "stores_opened", "label": "개업 점포", "unit": "개", "status": "available", "current": {"value": 1},
     "previous": {"value": 6}, "delta": -5, "percent": -83.33},
    {"key": "stores_closed", "label": "폐업 점포", "unit": "개", "status": "available", "current": {"value": 6},
     "previous": {"value": 1}, "delta": 5, "percent": 500.0}]}
CONDITIONS = {"id": "F1", "topic": "conditions", "status": "available",
              "text": "분석 조건은 홍대입구역(홍대) 상권, 분식전문점 업종, 2026년 2분기 자료입니다.",
              "values": [{"label": "상권", "value": "홍대입구역(홍대)"}, {"label": "업종", "value": "분식전문점"},
                         {"label": "기간", "value": "2026년 2분기"}]}


def _yoy_cards():
    card = changes_card(YOY, "yoy")
    card["id"] = "F10"
    total = {"id": "F2", "topic": "sales_total", "status": "available", "text": "분기 추정매출은 1,455,756,067원입니다.",
             "values": [{"label": "분기 추정매출", "value": 1455756067, "unit": "원"}]}
    return [CONDITIONS, total, card]


def _week_cards():
    days = [{"label": label, "value": value, "unit": "원"} for label, value in zip("월화수목금토일", NEW_DAYS)]
    extra, sentence = weekday_aggregates(days, PERIOD)
    return [CONDITIONS, {"id": "F3", "topic": "sales_weekday", "status": "available",
                         "text": "요일별 매출" + size_order(days) + sentence, "values": days + extra}]


def _types(text, cards):
    return [problem["type"] for problem in check_answer(text, cards)["problems"]]


class YearOverYearAmountTests(unittest.TestCase):
    def test_the_live_answers_are_rejected(self):
        cards = _yoy_cards()
        for text in ("작년 같은 분기와 비교해 13억 5천만 원 정도 매출이 올랐어요. [F10]",
                     "작년 같은 분기와 비교해 13억 5천만 원 정도 매출이 상승했고, 퍼센트로는 10.23% 오른 것으로 나타났어요. [F10]"):
            with self.subTest(text=text):
                self.assertIn("number_not_on_card", _types(text, cards))

    def test_thousands_and_hundreds_inside_korean_amounts(self):
        cards = _yoy_cards()
        for text in ("매출이 1억 3천만 원 정도 늘었어요. [F10]", "매출이 약 1억 3,510만 원 늘었어요. [F10]",
                     "매출이 135,101,464원 늘었어요. [F10]", "매출이 1억 3천 5백만 원 늘었어요. [F10]"):
            with self.subTest(text=text):
                self.assertEqual(_types(text, cards), [])
        self.assertIn("number_not_on_card", _types("매출이 1억 5천만 원 늘었어요. [F10]", cards))

    def test_an_increase_must_be_the_difference_not_a_level(self):
        cards = _yoy_cards()
        for text in ("매출이 13억 2,065만 원 늘었어요. [F10]", "작년보다 1,455,756,067원 증가했어요. [F10][F2]",
                     "증가액은 1,320,654,603원이에요. [F10]"):
            with self.subTest(text=text):
                self.assertIn("change_amount_not_delta", _types(text, cards))
        # The two levels told as levels are fine.
        fine = "작년 같은 분기 1,320,654,603원에서 이번 분기 1,455,756,067원으로 늘었어요. [F10]"
        self.assertEqual(_types(fine, cards), [])
        self.assertIn("'차이' 값", feedback(check_answer("매출이 13억 2,065만 원 늘었어요. [F10]", cards)["problems"], cards))

    def test_the_card_carries_the_reading_of_the_difference(self):
        text = changes_card(YOY, "yoy")["text"]
        self.assertIn("매출은 135,101,464원(약 1억 3,510만 원) 증가(+10.23%)", text)
        self.assertIn("점포 수는 6개 감소", text)                          # 개수에는 읽기를 붙이지 않는다
        self.assertEqual(with_units(text), text)                          # 서버가 같은 읽기를 두 번 붙이지 않는다


class WeekpartAnswerTests(unittest.TestCase):
    def test_a_comparison_with_the_totals_only_is_rejected(self):
        live = ("주말 매출이 더 높아요. [F3]\n"
                "주말은 합계 497,302,466원, 평일은 합계 958,453,601원이에요. [F3]")
        self.assertIn("weekpart_average_missing", _types(live, _week_cards()))

    def test_a_comparison_with_both_day_averages_passes(self):
        for text in ("주말 매출이 더 많아요. [F3]\n주말 하루 평균 매출이 19,127,018원이고, 평일은 14,745,440원이에요. [F3]",
                     "주말 매출이 더 많아요. [F3]\n주말(토·일) 매출 합계는 497,302,466원이고, 하루 평균으로는 19,127,018원이에요. "
                     "반면 평일은 하루 평균 14,745,440원이에요. [F3]"):
            with self.subTest(text=text):
                self.assertEqual(_types(text, _week_cards()), [])

    def test_much_is_kept_for_a_large_gap(self):
        text = "주말 매출이 평일보다 훨씬 높아요. [F3]\n주말 하루 평균 19,127,018원, 평일 하루 평균 14,745,440원이에요. [F3]"
        self.assertIn("weekpart_exaggerated", _types(text, _week_cards()))

    def test_a_total_named_as_a_day_average_is_rejected(self):
        self.assertIn("average_misnamed", _types("주말 하루 평균은 497,302,466원이에요. [F3]", _week_cards()))
        self.assertIn("total_misnamed", _types("평일 합계는 14,745,440원이에요. [F3]", _week_cards()))


class UnsupportedWordingTests(unittest.TestCase):
    def test_live_lines_without_a_yardstick(self):
        cards = _yoy_cards()
        for line in ("해석: 주변에 경쟁해야 할 점포들이 꽤 많다는 걸 의미해요.",
                     "해석: 한식 음식점을 내기에 괜찮은 매출 규모예요.",
                     "해석: 젊은 층에게 인기 있는 아이템을 추가하면 도움이 될 거예요.",
                     "분식 전문점을 찾는 사람이 많은 편이에요. [F2]",
                     "해석: 작년에 비해 장사가 나아진 것으로 보여요.",
                     "해석: 이는 긍정적인 신호일 수 있어요.", "해석: 안정적인 매출 규모를 보이는 것으로 보여요.",
                     "해석: 매출 규모로 보아 꽤 큰 상권임을 알 수 있어요.",
                     "해석: 젊은 층이 주로 찾는 품목 위주로 구성하면 어떨까 싶네요!",
                     "해석: 인스타그램 마케팅이 효과가 있었는지 알 수는 없지만, 매출 자체는 나쁘지 않아 보여요.",
                     "해석: 저녁에 사람이 몰리는 상권이라 저녁 영업을 강화하면 도움이 될 거예요.",
                     "해석: 주변에 경쟁 업체가 꽤 많다는 걸 의미해요.", "홍대입구역 근처 분식집 매출은 좋아요. [F2]",
                     "해석: 인스타그램 마케팅이 효과를 냈다고 볼 수도 있겠어요.",
                     "해석: 이는 고객들이 올해 우리 가게 음식을 더 찾았다는 의미일 수 있어요.",
                     "해석: 퇴근 후 식사를 잡으면 더 많은 손님을 끌어들일 가능성이 높아요.",
                     "해석: 주말은 외출하는 사람이 많아 상대적으로 매출이 높아지는 것으로 보여요."):
            with self.subTest(line=line):
                self.assertIn("forbidden_phrase", _types("매출은 1,455,756,067원이에요. [F2]\n" + line, cards))

    def test_the_same_sentence_twice(self):
        line = "주말 하루 평균 매출이 19,127,018원이고, 평일은 14,745,440원이에요. [F3]"
        text = "주말 매출이 더 많아요. [F3]\n" + line + "\n" + line
        self.assertIn("repeated_line", _types(text, _week_cards()))


class ReadingTests(unittest.TestCase):
    def test_rounded_half_up_like_the_market_screen(self):
        self.assertEqual(amount_words(1455756067, "원"), "약 14억 5,576만 원")
        self.assertEqual(amount_words(1840429687, "원"), "약 18억 4,043만 원")
        self.assertEqual(amount_words(104961122, "원"), "약 1억 496만 원")
        self.assertEqual(amount_words(199995000, "원"), "약 2억 원")          # 9,999.5만 → 2억 (자리 올림)
        self.assertEqual(amount_words(100000000, "원"), "1억 원")
        self.assertEqual(amount_words(34876902, "원"), "약 3,488만 원")
        self.assertEqual(with_units("1,455,756,067원"), "1,455,756,067원(약 14억 5,576만 원)")


class IntentTests(unittest.TestCase):
    def test_what_to_eat_is_not_a_sales_question(self):
        for text in ("오늘 점심 뭐 먹지?", "저녁 뭐 먹을까", "점심 메뉴 뭐 먹을까?"):
            with self.subTest(text=text):
                result = classify(text)
                self.assertEqual((result["domain"], result["turn_type"]), ("general", "out_of_scope"))
        self.assertEqual(classify("점심 매출 어때?")["turn_type"], "data_question")

    def test_marketing_words_with_a_sales_question_are_answered_with_market_data(self):
        for text in ("손님 늘리려면 점심이 나아 저녁이 나아?", "SNS 홍보하면 매출 늘까?", "인스타 하는 가게 매출 어때?"):
            with self.subTest(text=text):
                result = classify(text)
                self.assertEqual((result["domain"], result["turn_type"]), ("market_analysis", "data_question"))
        for text in ("홍보 글 써줘", "쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?",
                     "을지로에서 호프 하는데 손님 대부분이 30대 직장인이에요. 퇴근길에 한잔하러 오게 만들 이벤트 뭐 없을까요?"):
            with self.subTest(text=text):
                self.assertEqual(classify(text)["domain"], "marketing")


if __name__ == "__main__":
    unittest.main()
