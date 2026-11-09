"""User export 2026-11-08 16:05: what the third round of fixes covers.

- A market opened by a button gave the model no question; it wrote a list with
  '(F2)' or no card numbers, and every line was dropped (empty answer twice).
- '5,030억', '743만' and a number cited with the other market's card were rejected.
- '하루 유동 인구 35,911명' named the per-store value as daily people.
- '서울전체에서 매출 높은 순위로 업종' listed the saved market's industries, and
  '아니아니 서울 전체에서' turned into an age overview.
Synthetic rows only: no raw statistics, no model, no Maps.
"""
from datetime import date
import unittest

from app.assistant import templates
from app.assistant.answer_check import check_answer, repair_citations
from app.assistant.facts import changes_card
from app.assistant.planner import to_classification
from app.assistant.ranking import rank_industries
from tests.test_assistant_flow import metric
from tests.test_assistant_ranking import COFFEE, FASTFOOD, KOREAN, FakeRankingSource, _RankingEnv

GASAN = {"id": "F2", "topic": "sales_total", "status": "available", "market": "가산디지털단지", "text": "",
         "values": [{"label": "분기 추정매출", "value": 503058320534, "unit": "원", "market": "가산디지털단지"}]}
GANGNAM = {"id": "F3", "topic": "sales_total", "status": "available", "market": "강남역", "text": "",
           "values": [{"label": "분기 추정매출", "value": 21093691228, "unit": "원", "market": "강남역"}]}
PEOPLE = {"id": "F4", "topic": "population", "status": "available", "market": "강남역", "text": "",
          "values": [{"label": "유동인구 원천 총지표", "value": 7433594, "unit": "명", "market": "강남역"}]}
OPINION = {"id": "F2", "topic": "opinion", "status": "available", "text": "",
           "values": [{"label": "점포 1곳당 유동인구", "value": 35911, "unit": "명", "market": "강남역", "derived": True},
                      {"label": "폐업 비율", "value": 1.93, "unit": "%", "market": "강남역", "derived": True}]}


class NumberTests(unittest.TestCase):
    def test_korean_unit_readings_of_card_numbers_are_checked(self):
        cards = [GASAN, GANGNAM, PEOPLE]
        self.assertTrue(check_answer("가산디지털단지 매출은 5,030억 5,832만 원이에요. [F2]", cards)["ok"])
        self.assertTrue(check_answer("강남역은 210억 원 정도예요. [F3]", cards)["ok"])
        self.assertTrue(check_answer("강남역 유동인구는 743만 명이에요. [F4]", cards)["ok"])
        wrong = check_answer("가산디지털단지 매출은 503억 원이에요. [F2]", cards)
        self.assertEqual([p["type"] for p in wrong["problems"]], ["number_not_on_card"])

    def test_a_number_cited_with_another_card_gets_its_own_card(self):
        cards = [GASAN, GANGNAM]
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

    def test_bare_card_numbers_are_citations(self):
        body = templates.model_body("분기 추정 매출액: 503,058,320,534원 F2", [GASAN], show_conditions=False)
        self.assertEqual(body, "분기 추정 매출액: 503,058,320,534원 [F2]")

    def test_the_year_on_year_card_reads_as_a_sentence(self):
        result = {"status": "complete", "previous_period": {"label": "2025년 2분기"},
                  "metrics": [metric("sales", "추정매출", "원", 1000, 800), metric("stores_total", "전체 점포", "개", 20, 18)],
                  "warnings": []}
        text = changes_card(result, "yoy")["text"]
        self.assertEqual(text, "작년 같은 분기(2025년 2분기)와 비교하면 매출은 200원 증가(+25.00%), "
                               "점포 수는 2개 증가(+11.11%)입니다.")


class SeoulIndustryTests(unittest.TestCase):
    def test_every_market_of_seoul_added_up_per_industry(self):
        result = rank_industries(FakeRankingSource(), None, limit=3)
        self.assertEqual(result["area_name"], "서울 전체")
        names = [(item["industry_code"], item["value"]) for item in result["items"]]
        # 커피-음료 9,000+8,000+7,000+6,000+5,000+1,000 (9999999 is not in the catalogue), 한식 12,000.
        self.assertEqual(names[0], (COFFEE, 36000))
        self.assertEqual(names[1], (KOREAN, 12000))
        self.assertIsNone(result["stores_collected"])

    def test_leaving_an_industry_out_still_means_every_other_one(self):
        rule = {"turn_type": "condition_change", "topics": [], "all_industries": False,
                "slots": {"locations": [], "industries": [{"text": "커피-음료", "candidates": [
                    {"code": COFFEE, "name": "커피-음료"}]}], "period": {"period_code": None}}}
        decided = to_classification("market_data", {"place": "가산디지털단지", "all_industries": True, "topics": []},
                                    rule=rule, question="가산디지털단지 커피-음료 말고 다른 상권분석도 해줘",
                                    use_morph=False, today=date(2026, 11, 8))
        self.assertTrue(decided["all_industries"])


class FlowTests(_RankingEnv, unittest.TestCase):
    def test_seoul_industries_and_the_short_correction(self):
        self.say("합정역 카페 매출 어때?")
        market = self.say("추천해줘")
        self.assertEqual(market["reply"]["kind"], "industry_rank", market["reply"]["text"])
        seoul = self.say("아니아니 서울 전체에서")
        self.assertEqual(seoul["reply"]["kind"], "industry_rank", seoul["reply"]["text"])
        self.assertTrue(seoul["reply"]["text"].startswith("서울 전체 상권의 업종들을"), seoul["reply"]["text"])
        self.assertIn("1위 커피-음료: 매출 36,000원", seoul["reply"]["text"])
        self.assertIn("서울 전체 상권에서 자료가 있는", seoul["reply"]["text"])
        self.assertEqual(seoul["reply"]["actions"], [], "Seoul is not a market to open")

    def test_the_next_questions_follow_the_list(self):
        self.say("합정역 카페 매출 어때?")
        listed = self.say("추천해줘")["reply"]
        self.assertEqual(listed["suggestions"], ["한식음식점 말고 다른 업종은?", "서울에서 한식음식점 매출 높은 곳은?"])
        self.assertNotIn(FASTFOOD, str(listed["suggestions"]))


class PlaceKindTests(unittest.TestCase):
    def test_what_kind_of_place_a_market_is_never_comes_from_the_model(self):
        line = "해석: 가산은 IT 위주의 산업 단지지만 소비는 패션 아울렛에서 일어날 수 있어요."
        details = [p.get("detail") for p in check_answer(line, [GASAN])["problems"]]
        self.assertIn("아울렛", details)
        self.assertIn("산업 단지", details)

    def test_the_ratio_sentence_takes_the_right_particle(self):
        from app.assistant.multi import ratio_card

        cards = [{"id": f"F{i}", "topic": "stores_count", "market": market, "status": "available", "text": "",
                  "values": [{"label": "전체 점포", "value": value, "unit": "개", "market": market}]}
                 for i, (market, value) in enumerate((("가산디지털단지", 956), ("강남역", 207)), start=2)]
        self.assertIn("가산디지털단지 점포 수는 강남역의 4.6배입니다.", ratio_card(cards, [{}, {}])["text"])
