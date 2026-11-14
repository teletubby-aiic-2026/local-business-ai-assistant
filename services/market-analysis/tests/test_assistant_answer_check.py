"""The sentence checker on its own: no model, no network, no chatbot flow.

These cases come from the chatbot's test files, so that the checker can be
tested without the rest of the assistant.
"""
import unittest

from app.assistant.answer_check import check_answer, comparison_problems, feedback, repair_citations, tier_problems

CARDS = [{"id": "F1", "topic": "conditions", "text": "분석 조건은 합성 상권, 커피-음료 업종, 2026년 2분기 자료입니다.",
          "values": [{"label": "상권", "value": "합성"}, {"label": "업종", "value": "커피-음료"},
                     {"label": "기간", "value": "2026년 2분기"}],
          "warnings": ["경계 경고"]},
         {"id": "F2", "topic": "sales_total", "text": "분기 추정매출은 1,000원입니다.",
          "values": [{"label": "분기 추정매출", "value": 1000, "unit": "원"}], "warnings": ["개별 가게 매출이 아닙니다."]}]

def _age_card(card_id, market, values):
    return {"id": card_id, "topic": "sales_age", "status": "available", "market": market,
            "text": f"{market} 상권의 연령별 매출입니다.",
            "values": [{"label": label, "value": value, "unit": "원", "market": market}
                       for label, value in zip(("10대", "20대", "30대", "40대"), values)]}

HAPJEONG = _age_card("F2", "합정역", (10, 300, 976, 200))

GANGNAM = _age_card("F3", "강남역", (20, 900, 800, 100))

TIME = {"id": "F4", "topic": "sales_time", "status": "available", "text": "시간대별 매출입니다.",
        "values": [{"label": label, "value": value, "unit": "원"} for label, value in
                   zip(("00~06시", "06~11시", "11~14시", "14~17시", "17~21시", "21~24시"),
                       (1, 2, 1854334193, 2443475828, 2127313686, 5))]}

PLACES = {"id": "F11", "topic": "comparison", "status": "available", "text": "비교입니다.", "values": [
    {"label": "추정매출", "value": 7286103096, "unit": "원", "role": "base", "market": "연남동(홍대)"},
    {"label": "추정매출", "value": 13638954166, "unit": "원", "role": "comparison", "market": "강남역"},
    {"label": "전체 점포", "value": 206, "unit": "개", "role": "base", "market": "연남동(홍대)"},
    {"label": "전체 점포", "value": 196, "unit": "개", "role": "comparison", "market": "강남역"}]}

def kinds(text, cards):
    return [problem["type"] for problem in comparison_problems(text, cards)]

GASAN = {"id": "F2", "topic": "sales_total", "status": "available", "market": "가산디지털단지", "text": "",
         "values": [{"label": "분기 추정매출", "value": 503058320534, "unit": "원", "market": "가산디지털단지"}]}

GANGNAM_ROUND3 = {"id": "F3", "topic": "sales_total", "status": "available", "market": "강남역", "text": "",
           "values": [{"label": "분기 추정매출", "value": 21093691228, "unit": "원", "market": "강남역"}]}

PEOPLE = {"id": "F4", "topic": "population", "status": "available", "market": "강남역", "text": "",
          "values": [{"label": "유동인구 원천 총지표", "value": 7433594, "unit": "명", "market": "강남역"}]}

OPINION = {"id": "F2", "topic": "opinion", "status": "available", "text": "",
           "values": [{"label": "점포 1곳당 유동인구", "value": 35911, "unit": "명", "market": "강남역", "derived": True},
                      {"label": "폐업 비율", "value": 1.93, "unit": "%", "market": "강남역", "derived": True}]}

def _time_card(card_id, market, status="available", dinner=900):
    values = [] if status != "available" else [
        {"label": "11~14시", "value": 500, "unit": "원", "market": market},
        {"label": "17~21시", "value": dinner, "unit": "원", "market": market}]
    text = "시간대별 매출입니다." if status == "available" else "시간대별 매출: 자료가 없습니다."
    return {"id": card_id, "topic": "sales_time", "status": status, "market": market, "text": f"{market} 상권의 {text}",
            "values": values, "warnings": []}

CONDITIONS = {"id": "F1", "topic": "conditions", "status": "available", "text": "분석 조건입니다.", "warnings": [],
              "values": [{"label": "상권", "value": "노량진역·강남역", "unit": None}, {"label": "업종", "value": "수산물판매", "unit": None},
                         {"label": "기간", "value": "2026년 2분기", "unit": None}]}

HAS_DATA = _time_card("F2", "노량진역")

NO_DATA = _time_card("F3", "강남역", status="no_data")


class ClovaModelBodyTests(unittest.TestCase):
    def test_quarters_and_cause_words_must_match_the_cards(self):
        problems = check_answer("2025년 4분기 매출은 1,000원이에요. [F2]", CARDS)["problems"]
        self.assertEqual([p["type"] for p in problems], ["period_not_on_card"])
        self.assertFalse(check_answer("역 공사 때문에 매출이 1,000원이에요. [F2]", CARDS)["ok"])
        self.assertTrue(check_answer("2026년 2분기 매출은 1,000원이에요. [F2]", CARDS)["ok"])

    def test_guesses_and_verdicts_from_live_answers_are_rejected(self):
        # Sentences HCX-005 wrote on 2026-11-08 that passed the earlier checker.
        for sentence in ("유동인구도 줄어들면서 전체적으로 매출이 감소한 것으로 보입니다. [F2]",
                         "이러한 요인들이 복합적으로 작용하여 매출 감소를 초래했을 가능성이 있습니다.",
                         "폐업 점포도 줄어든 것으로 보아 전반적으로 좋아졌다고 할 수 있습니다. [F2]"):
            self.assertFalse(check_answer(sentence, CARDS)["ok"], sentence)


class FlowAnswerCheckTests(unittest.TestCase):
    CARDS = [{"id": "F1", "topic": "conditions", "values": [{"label": "기간", "value": "2026년 2분기"}]},
             {"id": "F2", "topic": "sales_total", "values": [{"label": "매출", "value": 1000, "unit": "원"},
                                                             {"label": "비중", "value": 12.5, "unit": "%"}]}]

    def test_numbers_must_be_on_the_cited_card(self):
        self.assertTrue(check_answer("2026년 2분기 매출은 1,000원이고 비중은 12.50%입니다. [F2]", self.CARDS)["ok"])
        problems = {p["type"] for p in check_answer("매출은 1,200원입니다. [F2]", self.CARDS)["problems"]}
        self.assertEqual(problems, {"number_not_on_card"})
        self.assertEqual(check_answer("매출은 1,000원입니다.", self.CARDS)["problems"][0]["type"], "uncited_number")
        self.assertEqual(check_answer("매출은 1,000원입니다. [F9]", self.CARDS)["problems"][0]["type"], "unknown_citation")
        self.assertFalse(check_answer("사장님 가게 매출은 확실히 오를 거예요.", self.CARDS)["ok"])

    def test_labels_and_warning_lines_are_not_statistics(self):
        text = "20대가 11~14시에 많아요. [F2]\n참고: 2023년 공개 경계이며 1,650개 상권 기준입니다."
        self.assertTrue(check_answer(text, self.CARDS)["ok"])


class MultiMultiCheckTests(unittest.TestCase):
    def test_each_market_is_checked_against_its_own_card(self):
        cards = [HAPJEONG, GANGNAM]
        self.assertEqual(comparison_problems("합정역은 30대가 가장 많아요. [F2]", cards), [])
        self.assertEqual([p["type"] for p in comparison_problems("강남역도 30대가 가장 많아요. [F3]", cards)],
                         ["wrong_superlative"])
        self.assertEqual(comparison_problems("30대 매출은 합정역이 강남역보다 많아요. [F2][F3]", cards), [])
        self.assertEqual([p["type"] for p in comparison_problems("20대 매출은 합정역이 강남역보다 많아요. [F2][F3]", cards)],
                         ["wrong_comparison"])
        self.assertEqual(comparison_problems("30대가 가장 많아요. [F2][F3]", cards), [], "which market is unclear")


class MultiModelBodyTests(unittest.TestCase):
    CARDS = [{"id": "F2", "topic": "sales_total", "status": "available", "text": "매출입니다.",
              "values": [{"label": "분기 추정매출", "value": 1000, "unit": "원"}]}]

    def test_the_checker_findings_become_rewrite_instructions(self):
        problems = check_answer("매출은 2,000원이에요. [F2]", self.CARDS)["problems"]
        self.assertIn("'2,000'은 카드에 없는 숫자예요.", feedback(problems))


class MultiRoundTwoTests(unittest.TestCase):
    def test_the_subject_may_come_from_the_sentence_before(self):
        line = "두 상권 모두 20대 매출이 많아요. 다만, 합정역이 강남역보다 조금 더 높네요. [F2][F3]"
        self.assertEqual([p["type"] for p in comparison_problems(line, [HAPJEONG, GANGNAM])], ["wrong_comparison"])

    def test_the_rewrite_advice_names_the_card_that_holds_the_number(self):
        problems = check_answer("합정역 30대는 976원이에요. [F3]", [HAPJEONG, GANGNAM])["problems"]
        self.assertIn("'976'은 F2 카드의 숫자예요.", feedback(problems, [HAPJEONG, GANGNAM]))


class OpinionComparisonCheckTests(unittest.TestCase):
    def test_a_comparison_the_card_values_contradict_is_caught(self):
        cards = [TIME, PLACES]
        self.assertEqual(kinds("연남동에서는 점심이 저녁보다 잘 팔려요. [F4]", cards), ["wrong_comparison"])
        self.assertEqual(kinds("저녁보다 점심이 더 잘 팔려요. [F4]", cards), ["wrong_comparison"])
        self.assertEqual(kinds("저녁이 점심보다 잘 팔려요. [F4]", cards), [])
        self.assertEqual(kinds("저녁 매출이 점심보다 많지 않아요. [F4]", cards), [], "a negation is not judged")
        self.assertEqual(kinds("점심이 가장 많이 팔려요. [F4]", cards), ["wrong_superlative"])
        self.assertEqual(kinds("오후 2시부터 5시가 제일 잘 돼요. [F4]", cards), [], "오후 2시부터 5시 = 14~17시")
        self.assertEqual(kinds("연남동이 강남역보다 매출이 커요. [F11]", cards), ["wrong_comparison"])
        self.assertEqual(kinds("강남역이 연남동보다 매출이 많아요. [F11]", cards), [])
        self.assertEqual(kinds("연남동은 강남역보다 점포가 적어요. [F11]", cards), ["wrong_comparison"])
        self.assertEqual(kinds("점포는 홍대가 강남역 196개보다 많아요. [F11]", cards), [])
        self.assertEqual(kinds("작년보다 매출이 늘었어요.", cards), [], "작년 is no label on these cards")
        self.assertFalse(check_answer("연남동에서는 점심이 저녁보다 잘 팔려요. [F4]", cards)["ok"])

    def test_descriptions_no_card_supports_are_rejected(self):
        for text in ("연남동은 개성 있는 가게가 많아 매력적인 곳이에요. [F11]", "강남역은 성공할 거예요. [F11]"):
            self.assertFalse(check_answer(text, [PLACES])["ok"], text)
            self.assertFalse(check_answer(text, [PLACES], opinion=True)["ok"], text)

    def test_an_opinion_may_recommend_but_its_numbers_are_checked(self):
        line = "저라면 강남역을 추천해요. 매출이 13,638,954,166원으로 더 크기 때문이에요. [F11]"
        self.assertTrue(check_answer(line, [PLACES], opinion=True)["ok"], check_answer(line, [PLACES], opinion=True))
        self.assertFalse(check_answer(line, [PLACES])["ok"], "a data answer still may not recommend")
        wrong = "저라면 강남역을 추천해요. 매출이 13,000,000,000원으로 더 커요. [F11]"
        self.assertFalse(check_answer(wrong, [PLACES], opinion=True)["ok"])


class OpinionOneSidedComparisonTests(unittest.TestCase):
    def test_one_named_market_against_the_other(self):
        extra = [{"label": label, "value": value, "unit": "개", "role": role, "market": market}
                 for label, base, other in (("일반 점포", 181, 117), ("프랜차이즈 점포", 25, 79))
                 for role, market, value in (("base", "연남동(홍대)", base), ("comparison", "강남역", other))]
        cards = [{**PLACES, "values": PLACES["values"] + extra}]
        live = "강남역의 점포 수가 연남동보다 조금 적지만, 일반 점포는 오히려 연남동이 훨씬 적고, 프랜차이즈 점포는 강남역이 압도적으로 많아요. [F11]"
        self.assertEqual(kinds(live, cards), ["wrong_comparison"])
        self.assertEqual(kinds("일반 점포는 연남동이 더 많고, 프랜차이즈 점포는 강남역이 압도적으로 많아요. [F11]", cards), [])


class RankingMissingDataTests(unittest.TestCase):
    def test_a_district_the_cards_never_name_is_rejected(self):
        cards = [{"id": "F1", "topic": "conditions", "text": "분석 조건은 신논현역 상권입니다.", "values": []},
                 {"id": "F2", "topic": "population", "text": "연령대별로는 20대가 가장 많습니다.", "values": []}]
        wide = check_answer("강남구 상권은 20대가 가장 많아요. [F2]", cards)
        self.assertIn({"type": "place_not_on_card", "detail": "강남구"}, wide["problems"])
        self.assertTrue(check_answer("이 상권은 20대가 가장 많아요. [F2]", cards)["ok"])
        self.assertTrue(check_answer("홍대입구역 출입구 근처예요. [F2]", cards)["ok"], "입구 is not a 구")

    def test_saying_no_data_about_a_card_that_has_data_is_rejected(self):
        ages = {"id": "F5", "topic": "sales_age", "status": "available", "text": "연령별 매출에서 가장 높은 항목은 50대입니다.",
                "values": []}
        empty = {"id": "F2", "topic": "sales_total", "status": "no_data", "text": "추정매출: 자료가 없습니다.", "values": []}
        denied = check_answer("죄송합니다. 해당 상권의 연령층 정보는 없어요. [F5]", [ages])
        self.assertIn("denies_available_card", [problem["type"] for problem in denied["problems"]])
        self.assertTrue(check_answer("추정 매출 자료는 없어요. [F2]", [empty])["ok"])
        self.assertTrue(check_answer("50대 매출이 가장 커요. [F5]", [ages])["ok"])


class Round3NumberTests(unittest.TestCase):
    def test_korean_unit_readings_of_card_numbers_are_checked(self):
        cards = [GASAN, GANGNAM_ROUND3, PEOPLE]
        self.assertTrue(check_answer("가산디지털단지 매출은 5,030억 5,832만 원이에요. [F2]", cards)["ok"])
        self.assertTrue(check_answer("강남역은 210억 원 정도예요. [F3]", cards)["ok"])
        self.assertTrue(check_answer("강남역 유동인구는 743만 명이에요. [F4]", cards)["ok"])
        wrong = check_answer("가산디지털단지 매출은 503억 원이에요. [F2]", cards)
        self.assertEqual([p["type"] for p in wrong["problems"]], ["number_not_on_card"])

    def test_a_number_cited_with_another_card_gets_its_own_card(self):
        cards = [GASAN, GANGNAM_ROUND3]
        fixed = repair_citations("강남역 매출은 21,093,691,228원이에요. [F2]", cards)
        self.assertEqual(fixed, "강남역 매출은 21,093,691,228원이에요. [F2][F3]")
        self.assertTrue(check_answer(fixed, cards)["ok"])
        moved = repair_citations("가산디지털단지 매출은 21,093,691,228원이에요. [F2]", cards)
        self.assertFalse(check_answer(moved, cards)["ok"], "another market's number is never moved to this one")

    def test_a_per_store_value_must_be_called_per_store(self):
        bad = check_answer("하루 유동 인구 또한 35,911명에 달해요. [F2]", [OPINION], opinion=True)
        self.assertIn("per_store_misnamed", [p["type"] for p in bad["problems"]])
        self.assertIn("forbidden_phrase", [p["type"] for p in bad["problems"]])
        good = check_answer("점포 1곳당 유동인구가 35,911명이에요. [F2]", [OPINION], opinion=True)
        self.assertTrue(good["ok"], good)


class Round3PlaceKindTests(unittest.TestCase):
    def test_what_kind_of_place_a_market_is_never_comes_from_the_model(self):
        line = "해석: 가산은 IT 위주의 산업 단지지만 소비는 패션 아울렛에서 일어날 수 있어요."
        details = [p.get("detail") for p in check_answer(line, [GASAN])["problems"]]
        self.assertIn("아울렛", details)
        self.assertIn("산업 단지", details)


class Round4BenchmarkTests(unittest.TestCase):
    def test_a_judgment_must_match_that_criterion(self):
        card = {"id": "F2", "topic": "opinion", "status": "available", "text": "", "values": [
            {"label": "폐업 비율 서울 상위 비율", "value": 80.0, "unit": "%", "tier": "하위권", "criterion": "폐업 비율"},
            {"label": "점포당 분기 추정매출 서울 상위 비율", "value": 45.0, "unit": "%", "tier": "중간", "criterion": "점포당 분기 추정매출"},
            {"label": "폐업 비율", "value": 4.35, "unit": "%"}, {"label": "점포당 분기 추정매출", "value": 37053885, "unit": "원"}]}
        kinds = lambda text: [p["type"] for p in tier_problems(text, [card])]
        self.assertEqual(kinds("폐업률은 4.35%로 낮은 편이에요."), ["tier_mismatch"])
        self.assertEqual(kinds("점포 1곳당 분기 추정 매출이 37,053,885원으로, 서울 상권 중에서 중상위권에 속해요."), ["tier_mismatch"])
        self.assertEqual(kinds("점포당 분기 추정매출은 서울에서 중간이에요."), [])
        self.assertEqual(kinds("폐업 비율은 높은 편이에요."), [])


class Round4SubstantialMarketTests(unittest.TestCase):
    def test_one_shop_per_store_label_is_not_a_number(self):
        card = {"id": "F2", "topic": "opinion", "status": "available", "text": "", "values": [
            {"label": "점포 1곳당 유동인구", "value": 63328, "unit": "명", "market": "시험", "derived": True}]}
        result = check_answer("점포 1곳당 유동인구가 63,328명이에요. [F2]", [card], opinion=True)
        self.assertTrue(result["ok"], result)


class Round4ConclusionTests(unittest.TestCase):
    CARD = {"id": "F2", "topic": "opinion", "status": "available", "text": "", "values": [
        {"label": "작년 같은 분기 대비 매출 변화율", "market": "시험", "value": -2.78, "unit": "%", "derived": True},
        {"label": "작년 같은 분기 대비 매출 변화율 서울 중앙값", "value": 2.41, "unit": "%", "derived": True},
        {"label": "폐업 비율", "market": "시험", "value": 0.0, "unit": "%", "derived": True},
        {"label": "종합 판단", "market": "시험", "value": "신중하게 볼 쪽", "unit": None, "verdict": "cautious"}]}

    def kinds(self, text):
        return [p["type"] for p in check_answer(text, [self.CARD], opinion=True)["problems"]]

    def test_a_comparison_with_the_median_is_checked(self):
        self.assertIn("wrong_comparison", self.kinds("작년 같은 분기 대비 매출 변화율은 -2.78%로 서울 중앙값 2.41%보다 높아요. [F2]"))
        self.assertEqual(self.kinds("작년 같은 분기 대비 매출 변화율은 -2.78%로 서울 중앙값 2.41%보다 낮아요. [F2]"), [])

    def test_the_conclusion_goes_the_way_of_the_criteria(self):
        self.assertIn("verdict_mismatch", self.kinds("저는 해볼 만하다고 봐요. 변화율은 -2.78%예요. [F2]"))
        self.assertEqual(self.kinds("조금 신중하게 보시는 게 좋겠어요. 변화율은 -2.78%예요. [F2]"), [])

    def test_no_closures_is_a_fact_not_a_denial(self):
        self.assertEqual(self.kinds("폐업은 없어요. 폐업 비율이 0.00%예요. [F2]"), [])


class Round5YearlyClosureTests(unittest.TestCase):
    def test_the_checker_reads_the_yearly_rate(self):
        card = {"id": "F2", "topic": "opinion", "status": "available", "text": "", "values": [
            {"label": "최근 1년 폐업 비율", "value": 90.0, "unit": "%", "derived": True},
            {"label": "최근 1년 폐업 비율 서울 상위 비율", "value": 95.0, "unit": "%", "tier": "하위권",
             "criterion": "최근 1년 폐업 비율", "derived": True},
            {"label": "최근 1년 폐업 점포", "value": 9, "unit": "개"}]}
        wrong = check_answer("최근 1년 폐업 비율은 90.00%로 낮은 편이에요. [F2]", [card], opinion=True)
        self.assertIn("tier_mismatch", [problem["type"] for problem in wrong["problems"]])
        right = check_answer("최근 1년 폐업 비율은 90.00%로 높은 편이에요. 최근 1년 폐업 점포는 9개예요. [F2]", [card], opinion=True)
        self.assertTrue(right["ok"], right)


class Round5CheckerTests(unittest.TestCase):
    def test_a_per_store_value_is_named_in_its_own_clause(self):
        card = {"id": "F2", "topic": "opinion", "status": "available", "text": "", "values": [
            {"label": "점포 1곳당 유동인구", "value": 70118, "unit": "명", "derived": True},
            {"label": "점포 1곳당 직장인구", "value": 41, "unit": "명", "derived": True}]}
        wrong = check_answer("점포 1곳당 유동인구가 70,118명으로 많지만 직장 인구는 41명이에요. [F2]", [card], opinion=True)
        self.assertIn("per_store_misnamed", [problem["type"] for problem in wrong["problems"]])
        right = check_answer("점포 1곳당 유동인구가 70,118명이지만 점포 1곳당 직장인구는 41명이에요. [F2]", [card], opinion=True)
        self.assertTrue(right["ok"], right)


class Round6OtherIndustriesTests(unittest.TestCase):
    def test_a_figure_under_a_name_of_the_models_own_is_refused(self):
        cards = [{"id": "F6", "topic": "stores_count", "status": "available", "text": "전체 점포입니다.", "warnings": [],
                  "values": [{"label": "일반 점포", "value": 173, "unit": "개"}]}]
        result = check_answer("가장 많은 업종은 '일반 음식점'(173곳)이에요. [F6]", cards)
        self.assertIn("term_not_on_card", [p["type"] for p in result["problems"]])
        self.assertTrue(check_answer("'일반 점포'는 173개예요. [F6]", cards)["ok"])

    def test_other_industries_need_a_list_on_the_cards(self):
        cards = [{"id": "F2", "topic": "sales_total", "status": "available", "text": "매출입니다.", "warnings": [],
                  "values": [{"label": "분기 추정매출", "value": 1000, "unit": "원"}]}]
        self.assertIn("industry_list_not_on_card",
                      [p["type"] for p in check_answer("다른 업종 중에서는 매출이 1,000원이에요. [F2]", cards)["problems"]])


class Round6NoCounterpartTests(unittest.TestCase):
    def test_a_comparison_needs_the_other_side(self):
        problems = comparison_problems("노량진역에서 저녁 매출이 훨씬 높아요. [F2]", [CONDITIONS, HAS_DATA, NO_DATA])
        self.assertEqual([p["type"] for p in problems], ["no_counterpart"])
        self.assertEqual(comparison_problems("노량진역은 저녁 매출이 900원이에요. [F2]", [CONDITIONS, HAS_DATA, NO_DATA]), [])

    def test_a_sales_comparison_with_no_other_figure_is_refused(self):
        sales = {"id": "F2", "topic": "sales_total", "status": "available", "market": "노량진역", "text": "매출입니다.", "warnings": [],
                 "values": [{"label": "분기 추정매출", "value": 900, "unit": "원", "market": "노량진역"}]}
        empty = {"id": "F3", "topic": "sales_total", "status": "no_data", "market": "강남역", "text": "자료가 없습니다.", "warnings": [],
                 "values": []}
        problems = comparison_problems("강남역보다 노량진역의 매출이 더 높아요. [F2]", [CONDITIONS, sales, empty])
        self.assertEqual([p["type"] for p in problems], ["no_counterpart"])

    def test_profit_is_not_said_even_as_an_interpretation(self):
        result = check_answer("해석: 노량진역에서 얻는 수입이 더 클 수 있어요.", [CONDITIONS, HAS_DATA, NO_DATA])
        self.assertIn("수입이", [p.get("detail") for p in result["problems"]])

    def test_the_other_market_with_figures_still_compares(self):
        both = [CONDITIONS, HAS_DATA, _time_card("F3", "강남역", dinner=100)]
        self.assertEqual(comparison_problems("노량진역에서 저녁 매출이 훨씬 높아요. [F2][F3]", both), [])


if __name__ == "__main__":
    unittest.main()
