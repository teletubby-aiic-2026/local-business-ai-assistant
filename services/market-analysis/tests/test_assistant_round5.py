"""User request 2026-11-08: weights by industry, Seoul follow-ups, what a place is, rent and key money.

- '네 기준의 비중이 모두 같습니다': criteria are weighted by industry group and said out loud.
- '서울 전체 답 뒤에 "경쟁 가게는 몇 개야?"': a follow-up with no place stays on Seoul.
- '개나리아파트처럼 입지 특성을 알아야': workers, residents, facilities and a location type from code.
- '임대료와 권리금': no public figure per market, so the user says it and code does the arithmetic.
Synthetic markets and rows only: no raw statistics, no model, no Maps.
"""
import json
from pathlib import Path
import re
import tempfile
import unittest

import httpx

from app.assistant import context as location
from app.assistant import opinion as opinions
from app.assistant import site_costs
from app.assistant.answer_check import check_answer
from app.assistant.intent import classify
from scripts import collect_assistant_context as collector
from tests.test_assistant_ranking import COFFEE, _RankingEnv
from tests.test_assistant_round4 import _CODES, _TableSource

RETAIL, SERVICE = "CS300001", "CS200001"


class CostParsingTests(unittest.TestCase):
    def test_the_ways_people_say_an_amount(self):
        cases = {"월세 500만 원, 권리금 5천만 원이야": {"rent": 5_000_000, "key_money": 50_000_000},
                 "권리금이 1억 2천만원": {"key_money": 120_000_000},
                 "보증금 5천": {"deposit": 50_000_000},
                 "월세 300": {"rent": 3_000_000},
                 "월세 이백만원이고 권리금은 없어": {"rent": 2_000_000, "key_money": 0}}
        for text, expected in cases.items():
            self.assertEqual(site_costs.parse(text), expected, text)

    def test_a_question_about_rent_carries_no_figure(self):
        self.assertIsNone(site_costs.parse("임대료는 얼마야?"))
        self.assertTrue(site_costs.asks("임대료는 얼마야?"))
        self.assertIsNone(site_costs.parse("합정역 카페 매출 어때?"))

    def test_margin_or_cost_of_goods(self):
        self.assertEqual(site_costs.parse("월세 300만원 마진 25%")["margin"], 25)
        self.assertEqual(site_costs.parse("월세 300만원 원가율 70%")["margin"], 30)


class CostArithmeticTests(unittest.TestCase):
    def test_three_assumed_margins_when_none_was_said(self):
        numbers = site_costs.calculate({"rent": 5_000_000, "key_money": 50_000_000}, 111_200_000)
        self.assertEqual(numbers["monthly_sales"], 37_066_666)
        self.assertEqual(numbers["rent_share"], 13.49)
        self.assertEqual([row["margin"] for row in numbers["rows"]], [20, 30, 40])
        self.assertEqual(numbers["rows"][0]["left"], 37_066_666 * 20 // 100 - 5_000_000)
        self.assertEqual(numbers["rows"][0]["break_even"], 25_000_000)

    def test_a_loss_is_said_and_no_payback_is_promised(self):
        costs = {"rent": 9_000_000, "key_money": 50_000_000}
        numbers = site_costs.calculate(costs, 30_000_000)
        self.assertIsNone(numbers["rows"][0]["months"])
        text = "\n".join(site_costs.lines(costs, numbers, area_name="시험", industry_name="커피-음료", card_id="F2"))
        self.assertIn("적자", text)
        self.assertIn("이 자리의 예상 매출은 아니에요", text)

    def test_the_card_holds_every_figure_the_lines_say(self):
        costs = {"rent": 5_000_000, "key_money": 50_000_000, "deposit": 30_000_000}
        numbers = site_costs.calculate(costs, 111_200_000)
        card = site_costs.card(costs, numbers, area_name="시험상권")
        held = {f"{value['value']:,}" for value in card["values"]}
        text = "\n".join(site_costs.lines(costs, numbers, area_name="시험상권", industry_name="커피-음료", card_id="F2"))
        for said in re.findall(r"\d[\d,]{3,}(?=원)", text):
            self.assertIn(said, held)


class WeightTests(unittest.TestCase):
    ROW = {"per_store_sales": 1, "trend": 1, "per_store_people": 1, "per_store_workers": 1, "per_store_residents": 1,
           "per_store_households": 1, "closure_rate": 1}

    def test_each_group_has_its_own_criteria_and_they_sum_to_100(self):
        plans = {code: opinions.weights_for(code, "", [self.ROW]) for code in (COFFEE, RETAIL, SERVICE)}
        for plan in plans.values():
            self.assertEqual(round(sum(plan["weights"].values())), 100, plan)
        self.assertEqual(plans[COFFEE]["weights"]["per_store_sales"], 35)
        self.assertEqual(plans[RETAIL]["weights"]["per_store_sales"], 40)
        self.assertEqual(plans[SERVICE]["weights"]["closure_rate"], 30)
        self.assertIn("per_store_workers", plans[COFFEE]["weights"])
        self.assertIn("per_store_residents", plans[SERVICE]["weights"])

    def test_what_the_user_cares_about_moves_the_weight(self):
        plain = opinions.weights_for(COFFEE, "", [self.ROW])
        steady = opinions.weights_for(COFFEE, "안정적인 곳 위주로 봐줘", [self.ROW])
        self.assertGreater(steady["weights"]["closure_rate"], plain["weights"]["closure_rate"])
        self.assertEqual(round(sum(steady["weights"].values())), 100)
        self.assertIn("안정 우선", opinions.weight_sentence(steady))

    def test_missing_data_hands_its_weight_on(self):
        row = {key: value for key, value in self.ROW.items() if key not in ("per_store_workers", "per_store_residents",
                                                                            "per_store_households")}
        plan = opinions.weights_for(COFFEE, "", [row])
        self.assertNotIn("per_store_workers", plan["weights"])
        self.assertEqual(round(plan["weights"]["per_store_people"]), 25)

    def test_an_unknown_group_keeps_equal_weights(self):
        self.assertIsNone(opinions.weights_for("XX900001", "", [self.ROW]))


class _Quarters(_TableSource):
    """Eight quarters: 7000011 jumped in the last one only, 7000010 grew steadily."""

    def periods(self):
        return ["20243", "20244", "20251", "20252", "20253", "20254", "20261", "20262"]

    def sales_amounts(self, period):
        order = self.periods().index(period)
        rows = {}
        for index, code in enumerate(_CODES):
            rows[(code, COFFEE)] = 10_000 + index * 100
        rows[("7000011", COFFEE)] = 90_000 if period == "20262" else 10_000
        rows[("7000010", COFFEE)] = 10_000 + order * 2_000
        return rows


class TrendTests(unittest.TestCase):
    def test_a_year_is_compared_with_the_year_before(self):
        table = {row["area_code"]: row for row in opinions.market_table(_Quarters(), COFFEE, "20262")}
        one_jump, steady = table["7000011"], table["7000010"]
        self.assertEqual(one_jump["trend"], 200.0, "(3 x 10,000 + 90,000) / 40,000 - 1")
        self.assertGreater(steady["trend"], 0)

    def test_a_source_with_too_few_quarters_has_no_trend(self):
        table = opinions.market_table(_TableSource(), COFFEE, "20262")
        self.assertTrue(all(row.get("trend") is None for row in table))


class _Closures(_Quarters):
    """7000011 closed nothing in the latest quarter but three shops in each of the three before."""

    def store_table(self, period):
        tables = {code: {COFFEE: {"SIMILR_INDUTY_STOR_CO": 10, "FRC_STOR_CO": 2, "OPBIZ_STOR_CO": 1, "CLSBIZ_STOR_CO": 1}}
                  for code in _CODES}
        tables["7000011"][COFFEE]["CLSBIZ_STOR_CO"] = 0 if period == "20262" else 3
        return tables


class YearlyClosureTests(unittest.TestCase):
    def test_a_quiet_quarter_does_not_read_as_no_closures(self):
        table = {row["area_code"]: row for row in opinions.market_table(_Closures(), COFFEE, "20262")}
        self.assertEqual(table["7000011"]["closure_rate"], 0.0)
        self.assertEqual(table["7000011"]["closed_year"], 9)
        self.assertEqual(table["7000011"]["closure_year"], 90.0, "9 closures against an average of 10 shops")
        self.assertEqual(table["7000001"]["closure_year"], 40.0)

    def test_a_market_missing_a_quarter_has_no_yearly_rate(self):
        class Gap(_Closures):
            def store_table(self, period):
                tables = super().store_table(period)
                if period == "20254":
                    tables.pop("7000005")
                return tables

        table = {row["area_code"]: row for row in opinions.market_table(Gap(), COFFEE, "20262")}
        self.assertIsNone(table["7000005"].get("closure_year"))
        self.assertIsNotNone(table["7000005"].get("closure_rate"), "the quarter's rate stays for one-market answers")

    def test_too_few_quarters_keep_the_quarter_rate(self):
        table = opinions.market_table(_TableSource(), COFFEE, "20262")
        self.assertTrue(all(row.get("closure_year") is None for row in table))
        plan = opinions.weights_for(COFFEE, "", table)
        self.assertIn("closure_rate", plan["weights"])

    def test_the_weight_and_the_preference_move_to_the_yearly_rate(self):
        row = {**WeightTests.ROW, "closure_year": 1}
        plan = opinions.weights_for(COFFEE, "안정적인 곳 위주로", [row])
        self.assertNotIn("closure_rate", plan["weights"])
        self.assertEqual(plan["preference"], "안정 우선")
        self.assertGreater(plan["weights"]["closure_year"], opinions.weights_for(COFFEE, "", [row])["weights"]["closure_year"])

    def test_candidates_are_ranked_and_said_on_the_yearly_rate(self):
        source = _Closures()
        table = opinions.market_table(source, COFFEE, "20262")
        plan = opinions.weights_for(COFFEE, "", table)
        top, _compared = opinions.best_markets(table, plan=plan)
        self.assertNotIn("7000011", [market["area_code"] for market in top], "90% a year is not a stable market")
        self.assertIn("최근 1년 폐업 비율 40.00%", opinions.seoul_fixed_lines(top, "F2", plan)[1])

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


def _rows(service, fields):
    return [{"STDR_YYQU_CD": "20262", "TRDAR_CD": code, **fields(index)} for index, code in enumerate(_CODES)]


def _context_files(folder: Path):
    numbers = {"workers": lambda n: {"TOT_WRC_POPLTN_CO": 5_000 if n == 11 else 100 + n},
               "residents": lambda n: {"TOT_REPOP_CO": 5_000 if n == 0 else 100 + n, "TOT_HSHLD_CO": 40 + n},
               "facilities": lambda n: {"VIATR_FCLTY_CO": 7, "SUBWAY_STATN_CO": 1, "ELESCH_CO": 1, "MSKUL_CO": 1, "HGSCHL_CO": None},
               "change": lambda n: {"TRDAR_CHNGE_IX_NM": "상권확장", "OPR_SALE_MT_AVRG": 100 + n, "SU_OPR_SALE_MT_AVRG": 106}}
    for name, fields in numbers.items():
        rows = {code: fields(index) for index, code in enumerate(_CODES)}
        (folder / f"{name}_20261.json").write_text(json.dumps({"schema": location.SCHEMA, "rows": rows}), encoding="utf-8")


class ContextTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def test_location_type_comes_from_the_figures(self):
        _context_files(self.folder)
        table = location.area_table("20262", {}, folder=self.folder)
        self.assertEqual(table["7000011"]["kind"], "직장 수요형")
        self.assertEqual(table["1111111"]["kind"], "주거 수요형")
        self.assertIsNone(table["1111111"]["schools"], "a missing high-school count leaves the combined count unknown")

    def test_nothing_collected_means_nothing_said(self):
        self.assertEqual(location.area_table("20262", {}, folder=self.folder), {})
        self.assertIsNone(location.profile_card({"name": "시험"}))

    def test_a_card_never_invents_a_figure(self):
        card = location.profile_card({"name": "시험", "workers": 100, "kind": "복합 수요형"})
        self.assertEqual([value["label"] for value in card["values"]], ["직장인구", "입지 유형"])
        self.assertIn("입지 유형은 복합 수요형", card["text"])


class CollectorTests(unittest.TestCase):
    @staticmethod
    def _client(pages):
        def respond(request):
            return httpx.Response(200, json=pages(request))

        return httpx.Client(transport=httpx.MockTransport(respond))

    @staticmethod
    def _body(service, rows, total):
        return {service: {"list_total_count": total, "RESULT": {"CODE": "INFO-000"}, "row": rows}}

    def test_keeps_only_the_fields_in_use(self):
        rows = [{"STDR_YYQU_CD": "20262", "TRDAR_CD": "1", "TOT_WRC_POPLTN_CO": 9, "OTHER": "x"}]
        with self._client(lambda _request: self._body("S", rows, 1)) as client:
            document = collector.collect(client, "k", "S", ("TOT_WRC_POPLTN_CO",), "20262")
        self.assertEqual(document["rows"], {"1": {"TOT_WRC_POPLTN_CO": 9}})

    def test_rows_that_do_not_add_up_are_refused(self):
        rows = [{"STDR_YYQU_CD": "20262", "TRDAR_CD": "1"}, {"STDR_YYQU_CD": "20262", "TRDAR_CD": "1"}]
        with self._client(lambda _request: self._body("S", rows, 2)) as client, self.assertRaises(collector.CollectError):
            collector.collect(client, "k", "S", (), "20262")

    def test_the_newest_quarter_up_to_the_request_is_kept(self):
        rows = [{"STDR_YYQU_CD": quarter, "TRDAR_CD": "1"} for quarter in ("20254", "20261", "20263")]
        with self._client(lambda _request: self._body("S", rows, 3)) as client:
            document = collector.collect(client, "k", "S", (), "20262")
        self.assertEqual(document["period"], "20261", "a service that ignores the quarter in the path")
        self.assertEqual(document["row_count"], 1)

    def test_only_later_quarters_are_refused(self):
        rows = [{"STDR_YYQU_CD": "20263", "TRDAR_CD": "1"}]
        with self._client(lambda _request: self._body("S", rows, 1)) as client, self.assertRaises(collector.CollectError):
            collector.collect(client, "k", "S", (), "20262")

    def test_an_error_never_carries_the_key(self):
        def fail(_request):
            raise httpx.ConnectError("http://openapi.seoul.go.kr:8088/SECRETVALUE/json/S/1/1000/20262")

        with httpx.Client(transport=httpx.MockTransport(fail)) as client:
            with self.assertRaises(collector.CollectError) as caught:
                collector.collect(client, "SECRETVALUE", "S", (), "20262")
        self.assertNotIn("SECRETVALUE", str(caught.exception))


class CheckerTests(unittest.TestCase):
    def test_workers_are_allowed_once_a_card_has_them(self):
        card = location.profile_card({"name": "시험", "workers": 5000, "residents": 100, "kind": "직장 수요형"})
        card = {**card, "id": "F2"}
        self.assertTrue(check_answer("시험 상권의 직장인구는 5,000명이에요. [F2]", [card])["ok"])
        other = {"id": "F2", "topic": "stores_count", "status": "available", "text": "전체 점포 3개", "values": [
            {"label": "전체 점포", "value": 3, "unit": "개"}]}
        self.assertFalse(check_answer("점포는 3개인데 직장인구가 많아요. [F2]", [other])["ok"])

    def test_a_per_store_value_is_named_in_its_own_clause(self):
        card = {"id": "F2", "topic": "opinion", "status": "available", "text": "", "values": [
            {"label": "점포 1곳당 유동인구", "value": 70118, "unit": "명", "derived": True},
            {"label": "점포 1곳당 직장인구", "value": 41, "unit": "명", "derived": True}]}
        wrong = check_answer("점포 1곳당 유동인구가 70,118명으로 많지만 직장 인구는 41명이에요. [F2]", [card], opinion=True)
        self.assertIn("per_store_misnamed", [problem["type"] for problem in wrong["problems"]])
        right = check_answer("점포 1곳당 유동인구가 70,118명이지만 점포 1곳당 직장인구는 41명이에요. [F2]", [card], opinion=True)
        self.assertTrue(right["ok"], right)

    def test_rule_classifier_knows_these_are_data_now(self):
        self.assertIn("area_profile", classify("합정역 직장인구 얼마나 돼?", use_morph=False)["topics"])
        self.assertIn("area_profile", classify("거기 근처에 회사 많아?", use_morph=False)["topics"])


class _WithContext(_TableSource):
    def context_table(self, period):
        class Anywhere(dict):
            def get(self, _code, default=None):
                return {"workers": 5_000, "residents": 900, "households": 400, "subway": 1, "kind": "직장 수요형"}

        return Anywhere()

    def sales_amounts(self, period):
        return {key: row["THSMON_SELNG_AMT"] for key, row in self.sales(period)[0].items()}


class FlowTests(_RankingEnv, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.source.__class__ = _WithContext

    def test_a_question_with_no_place_stays_on_seoul(self):
        self.say("합정역 카페 매출 어때?")
        self.assertEqual(self.say("서울 전체 연령대별 매출 알려줘")["reply"]["kind"], "seoul_overview")
        data = self.say("경쟁 가게는 몇 개야?")
        self.assertEqual(data["reply"]["kind"], "seoul_overview", data["reply"]["text"])
        self.assertIn("전체 점포", json.dumps(data["cards"], ensure_ascii=False))

    def test_naming_a_place_leaves_seoul(self):
        self.say("합정역 카페 매출 어때?")
        self.say("서울 전체 연령대별 매출 알려줘")
        data = self.say("합정역 점포 수는?")
        self.assertNotEqual(data["reply"]["kind"], "seoul_overview", data["reply"]["text"])

    def test_what_cannot_be_added_up_is_said(self):
        self.say("합정역 카페 매출 어때?")
        self.say("서울 전체 연령대별 매출 알려줘")
        data = self.say("유동인구는?")
        self.assertEqual(data["reply"]["kind"], "seoul_not_summed", data["reply"]["text"])
        self.assertIn("합치지 않아요", data["reply"]["text"])

    def test_rent_is_asked_for_then_computed(self):
        self.say("합정역 카페 매출 어때?")
        self.assertEqual(self.say("임대료는 얼마야?")["reply"]["kind"], "ask_site_costs")
        data = self.say("월세 5만 원, 권리금 100만 원이야")
        self.assertEqual(data["reply"]["kind"], "site_costs", data["reply"]["text"])
        self.assertIn("마진 20%일 때", data["reply"]["text"])
        self.assertFalse(data["reply"].get("model_used"))

    def test_the_opinion_uses_the_rent_that_was_said(self):
        self.say("합정역 카페 매출 어때?")
        self.say("월세 5만 원이야")
        data = self.say("너라면 여기서 카페 차릴 거야?")
        self.assertEqual(data["reply"]["kind"], "opinion", data["reply"]["text"])
        self.assertIn("말씀하신 월세", data["reply"]["text"])
        self.assertNotIn("임대료·권리금은 이 자료에 없어요", data["reply"]["text"])

    def test_an_opinion_says_its_weights_once(self):
        self.say("합정역 카페 매출 어때?")
        data = self.say("너라면 여기서 카페 차릴 거야?")
        self.assertIn("음식·카페 업종이라 기준 비중을", json.dumps(data["cards"], ensure_ascii=False))
        self.assertIn("음식·카페 업종이라 기준 비중은", data["reply"]["text"])
        again = self.say("너라면 여기서 카페 차릴 거야?")
        self.assertNotIn("기준 비중은", again["reply"]["text"], "the same weights are not said twice in a row")
        self.assertIn("말씀하신 대로 안정 우선으로", opinions.tail(
            opinions.weights_for(COFFEE, "안정적인 곳 위주로", [WeightTests.ROW]), shown_before=False))

    def test_other_weights_are_said_even_right_after_an_opinion(self):
        self.say("합정역 카페 매출 어때?")
        self.say("너가 생각했을때 서울에 어느 상권이 좋다고 봐?")
        steady = self.say("안정적인 곳 위주로 보면?")
        self.assertIn("말씀하신 대로 안정 우선으로", steady["reply"]["text"])

    def test_the_location_question_is_answered_from_the_card(self):
        self.say("합정역 카페 매출 어때?")
        data = self.say("여기 직장인구 얼마나 돼?")
        self.assertIn("area_profile", [card["topic"] for card in data["cards"]], data["reply"]["text"])
        self.assertIn("5,000", data["reply"]["text"])

    def test_where_to_open_is_a_view_not_a_list(self):
        self.say("합정역 카페 매출 어때?")
        data = self.say("서울에서 카페 창업하려면 어느 상권이 좋을까?")
        self.assertEqual(data["reply"]["kind"], "opinion", data["reply"]["text"])
        listed = self.say("서울에서 카페 매출 높은 곳 알려줘")
        self.assertEqual(listed["reply"]["kind"], "ranking", listed["reply"]["text"])

    def test_after_a_seoul_ranking_what_adds_up_stays_on_seoul(self):
        self.say("합정역 카페 매출 어때?")
        self.say("서울에서 카페 매출 높은 곳 알려줘")
        data = self.say("경쟁 가게는 몇 개야?")
        self.assertEqual(data["reply"]["kind"], "seoul_overview", data["reply"]["text"])
        self.say("서울에서 카페 매출 높은 곳 알려줘")
        saved = self.say("작년이랑 비교하면?")
        self.assertNotIn(saved["reply"]["kind"], ("seoul_overview", "seoul_not_summed"), saved["reply"]["text"])

    def test_a_preference_after_a_seoul_ranking_gives_candidates(self):
        self.say("합정역 카페 매출 어때?")
        self.say("서울에서 카페 매출 높은 곳 알려줘")
        data = self.say("안정적인 곳 위주로 보면?")
        self.assertEqual(data["reply"]["kind"], "opinion", data["reply"]["text"])
        self.assertIn("안정 우선", json.dumps(data["cards"], ensure_ascii=False))

    def test_a_preference_redoes_the_seoul_candidates(self):
        self.say("합정역 카페 매출 어때?")
        first = self.say("너가 생각했을때 서울에 어느 상권이 좋다고 봐?")
        self.assertEqual(first["reply"]["kind"], "opinion", first["reply"]["text"])
        again = self.say("안정적인 곳 위주로 보면?")
        self.assertEqual(again["reply"]["kind"], "opinion", again["reply"]["text"])
        self.assertIn("안정 우선", json.dumps(again["cards"], ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
