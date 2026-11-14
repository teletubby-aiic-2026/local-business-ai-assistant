"""User export 2026-11-08 21:09, replayed on the current code.

- '커피-음료 말고 다른 상권분석도 해줘' repeated coffee, and the model named 173 stores "'일반 음식점'".
- '강남역과 비교했을때 수익이 어느 곳이' compared with a market that had no figure, and profit is in no file.
- Questions asked one right after another met CLOVA's per-minute limit and fell back to fixed answers.
Synthetic markets and rows only: no raw statistics, no model, no Maps.
"""
from datetime import date
import secrets
import unittest
from unittest.mock import patch

import httpx

from app.assistant import multi
from app.assistant import templates
from app.assistant.answer_check import check_answer, comparison_problems
from app.assistant.clova_client import ClovaWriter, ModelError
from app.assistant.intent import classify
from app.assistant.planner import to_classification
from tests.test_assistant_clova import CARDS, CLS, Recorder, completion
from tests.test_assistant_ranking import _RankingEnv

KEY = "nv-" + secrets.token_hex(16)
TODAY = date(2026, 11, 8)
LIMITED = httpx.Response(429, json={"status": {"code": "42901", "message": "Too many requests"}})


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


class OtherIndustriesTests(unittest.TestCase):
    QUESTION = "가산디지털단지 커피-음료 말고 다른 상권분석도 해줘"

    def test_the_rules_hear_every_other_industry(self):
        self.assertTrue(classify(self.QUESTION, use_morph=False, today=TODAY)["all_industries"])
        self.assertFalse(classify("가산디지털단지 커피-음료 말고 한식 매출 알려줘", use_morph=False, today=TODAY)["all_industries"])
        self.assertFalse(classify("강남 말고 다른 상권 추천해줘", use_morph=False, today=TODAY)["all_industries"])

    def test_the_model_may_say_it_in_the_industry_field(self):
        rule = classify("강남역 어때?", use_morph=False, today=TODAY)
        decided = to_classification("market_data", {"place": "강남역", "industry": "모든 업종", "topics": []}, rule=rule,
                                    question="강남역 어때?", use_morph=False, today=TODAY, known="강남역 어때?")
        self.assertTrue(decided["all_industries"])
        self.assertEqual(decided["slots"]["industries"], [])

    def test_a_ranking_of_the_same_industry_is_not_what_was_asked(self):
        rule = classify(self.QUESTION, use_morph=False, today=TODAY)
        decided = to_classification("rank_areas", {"industry": "커피-음료", "exclude_places": ["가산디지털단지역"], "count": 5},
                                    rule=rule, question=self.QUESTION, use_morph=False, today=TODAY, known=self.QUESTION)
        self.assertEqual(decided["turn_type"], "condition_change")
        self.assertTrue(decided["all_industries"])
        self.assertEqual([m["text"] for m in decided["slots"]["locations"]], ["가산디지털단지"])
        self.assertEqual(decided["slots"]["industries"], [])

    def test_the_time_of_day_the_user_named_is_kept(self):
        question = "저녁을 기준으로 강남역과 비교했을때 매출이 어때?"
        rule = classify(question, use_morph=False, today=TODAY)
        self.assertIn("sales_time", rule["topics"])
        decided = to_classification("market_data", {"compare_place": "강남역", "topics": ["sales_total", "population"]}, rule=rule,
                                    question=question, use_morph=False, today=TODAY, known=question)
        self.assertIn("sales_time", decided["topics"])
        self.assertNotIn("sales_total", decided["topics"])

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


class NoCounterpartTests(unittest.TestCase):
    def test_a_comparison_needs_the_other_side(self):
        problems = comparison_problems("노량진역에서 저녁 매출이 훨씬 높아요. [F2]", [CONDITIONS, HAS_DATA, NO_DATA])
        self.assertEqual([p["type"] for p in problems], ["no_counterpart"])
        self.assertEqual(comparison_problems("노량진역은 저녁 매출이 900원이에요. [F2]", [CONDITIONS, HAS_DATA, NO_DATA]), [])

    def test_a_market_with_only_people_is_not_set_against_sales(self):
        people = {"id": "F4", "topic": "population", "status": "available", "market": "강남역", "text": "유동인구입니다.", "warnings": [],
                  "values": [{"label": "유동인구 원천 총지표", "value": 42, "unit": "명", "market": "강남역"}]}
        markets = [{"name": "노량진역"}, {"name": "강남역"}]
        cards = [CONDITIONS, HAS_DATA, NO_DATA, people]
        self.assertEqual(multi.without_data(cards, markets, ["sales_time", "population"]), ["강남역"])

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

    def test_which_markets_have_nothing(self):
        markets = [{"name": "노량진역"}, {"name": "강남역"}]
        self.assertEqual(multi.without_data([CONDITIONS, HAS_DATA, NO_DATA], markets, ["sales_time"]), ["강남역"])
        self.assertEqual(multi.without_data([CONDITIONS, NO_DATA], markets, ["sales_time"]), [])

    def test_the_fixed_answer_says_which_market_the_value_belongs_to(self):
        both = [CONDITIONS, HAS_DATA, _time_card("F3", "강남역", dinner=100)]
        text = templates.data_answer(both, {"text": "저녁 매출 비교"})["text"]
        self.assertIn("노량진역 상권에서 저녁(17~21시)은", text)
        self.assertIn("강남역 상권에서 저녁(17~21시)은", text)


class FlowTests(_RankingEnv, unittest.TestCase):
    def test_profit_is_said_to_be_missing_first(self):
        self.say("합정역 카페 매출 어때?")
        data = self.say("여기 수익은 얼마나 나?")
        self.assertTrue(data["reply"]["text"].startswith("말씀하신 수익(비용을 뺀 이익)은 상권 공공 자료에 없어서"),
                        data["reply"]["text"])

    def test_a_market_with_no_figure_is_named_and_not_compared(self):
        self.say("합정역 카페 매출 어때?")
        with patch("app.assistant.flow.multi.market_cards", return_value=[CONDITIONS, HAS_DATA, NO_DATA]), \
                patch("app.assistant.flow.multi.resolve",
                      return_value=([{"area_code": "1", "name": "노량진역"}, {"area_code": "2", "name": "강남역"}], [])):
            data = self.say("홍대입구역과 강남역의 저녁 시간대 매출 비교해줘")
        reply = data["reply"]
        self.assertEqual(reply["kind"], "multi_market", reply["text"])
        self.assertIn("강남역에는 커피-음료 매출 자료가 없어서 매출은 함께 견줄 수 없어요", reply["text"])
        self.assertFalse(data["model_used"])
        self.assertEqual([card["id"] for card in data["cards"]], ["F1", "F2"], "only the market with figures is cited")
        self.assertEqual(reply["suggestions"][0], "강남역에서는 어떤 업종 매출이 커?")

    def test_seoul_again_after_a_seoul_comparison_is_not_unknown(self):
        self.say("합정역 카페 매출 어때?")
        first = self.say("서울 전체 모든 상권들과 업종들로 비교해줘")
        self.assertEqual(first["reply"]["kind"], "seoul_compare", first["reply"]["text"])
        again = self.say("아니아니 서울 전체에서")
        self.assertEqual(again["reply"]["kind"], "seoul_compare", again["reply"]["text"])

    def test_the_rules_hear_a_highest_zone_as_a_ranking(self):
        self.assertEqual(classify("서울시 안에서 상권들 중 제일 매출액이 높은 구역은 어디임?", use_morph=False,
                                  today=TODAY)["turn_type"], "ranking")


class RateLimitTests(unittest.TestCase):
    def _writer(self, recorder):
        waits = []
        client = ClovaWriter(KEY, transport=httpx.MockTransport(recorder), sleep=waits.append)
        self.addCleanup(client.close)
        return client, waits

    def test_one_more_try_after_a_rate_limit(self):
        recorder = Recorder(LIMITED, completion("분기 추정매출은 1,000원이에요. [F2]"))
        client, waits = self._writer(recorder)
        self.assertEqual(client(CARDS, CLS), "분기 추정매출은 1,000원이에요. [F2]")
        self.assertEqual((len(recorder.requests), waits), (2, [2.0]))

    def test_a_second_rate_limit_is_a_model_error(self):
        recorder = Recorder(LIMITED, LIMITED)
        client, waits = self._writer(recorder)
        with self.assertRaises(ModelError) as caught:
            client(CARDS, CLS)
        self.assertIn("429", str(caught.exception))
        self.assertNotIn(KEY, str(caught.exception))
        self.assertEqual(len(recorder.requests), 2)

    def test_other_errors_are_not_tried_again(self):
        recorder = Recorder(httpx.Response(401, json={"status": {"code": "40100", "message": "Unauthorized"}}))
        client, waits = self._writer(recorder)
        with self.assertRaises(ModelError):
            client(CARDS, CLS)
        self.assertEqual((len(recorder.requests), waits), (1, []))
