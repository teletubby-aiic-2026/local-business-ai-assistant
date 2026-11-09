"""User export 2026-11-08 17:28: opinions measured against Seoul, and Seoul-wide questions.

- '서울에 어느 상권에서 창업을 하는 게 좋다고 봐?' asked to compare two earlier markets.
- '서울 전체로 생각해줘' and '서울 전체 모든 상권들과 업종들로 비교해줘' became age statistics.
- '폐업률은 낮은 편', '많은 편', '중상위권' were said with nothing to compare with.
Synthetic markets and rows only: no raw statistics, no model, no Maps.
"""
from datetime import date
import unittest

from starlette.requests import Request

from app.assistant import opinion as opinions
from app.assistant import templates
from app.assistant.answer_check import check_answer, tier_problems
from app.assistant.intent import classify
from app.assistant.overview import seoul_cards
from app.assistant.planner import to_classification
from app.data_repository import DISTRIBUTION_FIELDS
from tests.test_assistant_ranking import COFFEE, KOREAN, FakeRankingSource, _RankingEnv

_CODES = ["1111111", *(f"70000{n:02d}" for n in range(1, 12))]


def _area(index: int, code: str) -> dict:
    return {"area_code": code, "name": "홍대입구역(홍대)" if index == 0 else f"시험상권{index}", "type": "골목상권",
            "district_code": "11440", "district_name": "마포구", "neighborhood_code": f"114406{index:02d}",
            "neighborhood_name": f"시험동{index}", "boundary_identity_status": "code_name_match"}


class _TableSource(FakeRankingSource):
    """Twelve markets: per-store sales rise with the index, so 시험상권11 stands best and 홍대입구역 last."""

    def periods(self):
        return ["20252", "20261", "20262"]

    def areas(self):
        return {code: _area(index, code) for index, code in enumerate(_CODES)}

    def sales(self, period):
        rows = {}
        for index, code in enumerate(_CODES):
            amount = (index + 1) * 10_000 * (1 if period == "20262" else 1)
            if period == "20252":
                amount = amount * 100 // (100 + index * 2)  # growth rises with the index, up to +22%
            rows[(code, COFFEE)] = {"THSMON_SELNG_AMT": amount, "SVC_INDUTY_CD_NM": "커피-음료"}
            rows[(code, KOREAN)] = {"THSMON_SELNG_AMT": 50_000, "SVC_INDUTY_CD_NM": "한식음식점"}
            for number, (_label, field) in enumerate(DISTRIBUTION_FIELDS["sales_age"]):
                rows[(code, COFFEE)][field] = 100 + number
        return rows, "b2_synthetic_table"

    def area_sales(self, period, area_code):
        rows, version = self.sales(period)
        return {industry: row for (area, industry), row in rows.items() if area == area_code}, version

    def store_table(self, period):
        return {code: {COFFEE: {"SIMILR_INDUTY_STOR_CO": 10, "FRC_STOR_CO": 2, "OPBIZ_STOR_CO": 1, "CLSBIZ_STOR_CO": 12 - index}}
                for index, code in enumerate(_CODES)}

    def population_table(self, period):
        return {code: (index + 1) * 1_000 for index, code in enumerate(_CODES)}


def _figure(source, code):
    table = {row["area_code"]: row for row in opinions.market_table(source, COFFEE, "20262")}
    return dict(table[code])


class BenchmarkTests(unittest.TestCase):
    def test_a_market_is_placed_among_seoul(self):
        source = _TableSource()
        best, worst = _figure(source, "7000011"), _figure(source, "1111111")
        opinions.add_benchmarks(source, [best, worst], COFFEE, "20262")
        self.assertEqual(best["position"]["per_store_sales"]["share"], 8.33)
        self.assertEqual(best["position"]["per_store_sales"]["tier"], "상위권")
        self.assertEqual(worst["position"]["per_store_sales"]["tier"], "하위권")
        self.assertEqual(best["position"]["closure_rate"]["tier"], "상위권", "a low closure rate stands high")
        self.assertEqual(worst["position"]["per_store_sales"]["count"], 12)

    def test_the_card_and_the_fixed_opinion_say_where_it_stands(self):
        source = _TableSource()
        worst = _figure(source, "1111111")
        opinions.add_benchmarks(source, [worst], COFFEE, "20262")
        card = {**opinions.opinion_card([worst], industry_name="커피-음료", period_label="2026년 2분기"), "id": "F2"}
        self.assertIn("폐업 비율(계산값)은 120.00%입니다. 서울 커피-음료 상권 12곳 가운데 서울 낮은 쪽으로 상위 100.00%, 하위권이고", card["text"])
        lines = opinions.fixed_lines([worst], "F2")
        self.assertEqual(lines[0], "자료로만 보면 홍대입구역(홍대) 상권은 조금 신중하게 보시는 게 좋겠어요. [F2]")
        result = check_answer("\n".join(lines), [card], opinion=True)
        self.assertTrue(result["ok"], result)

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

    def test_seoul_candidates_stand_best_on_the_four_criteria_together(self):
        source = _TableSource()
        top, compared = opinions.best_markets(opinions.market_table(source, COFFEE, "20262"))
        self.assertEqual(compared, 6, "only markets at or above the median of sales")
        self.assertEqual(top[0]["name"], "시험상권11")
        card = {**opinions.seoul_card(top, industry_name="커피-음료", period_label="2026년 2분기", compared=compared), "id": "F2"}
        result = check_answer("\n".join(opinions.seoul_fixed_lines(top, "F2")), [card], opinion=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(opinions.best_markets([]), ([], 0), "no candidates rather than a guess")


class WordingTests(unittest.TestCase):
    def test_the_fixed_seoul_answer_is_short(self):
        cards = seoul_cards(_TableSource(), ["sales_age"], industry_code=COFFEE, industry_name="커피-음료")
        speech = templates.data_answer(cards, {"text": "서울 연령대"})["text"].splitlines()[1]
        self.assertTrue(speech.startswith("연령별 매출은 60대 이상이"), speech)
        self.assertNotIn("매출이 큰 순서는", speech)
        self.assertIn("매출이 큰 순서는", cards[1]["text"], "the model still sees the whole card")

    def test_prompt_examples_name_no_real_industry(self):
        from app.assistant.clova_client import _EXAMPLE_USER, _OPINION_USER

        for example in (_EXAMPLE_USER, _OPINION_USER):
            self.assertNotIn("한식", example, "HCX-005 copied it into an answer about 일반의류")

    def test_rules_hear_an_open_opinion_and_a_seoul_comparison(self):
        self.assertEqual(classify("너가 생각했을때 서울에 어느 상권이 좋다고 봐?", use_morph=False)["turn_type"], "opinion")
        self.assertEqual(classify("서울 전체 모든 상권들과 업종들로 비교해줘", use_morph=False)["turn_type"], "seoul_overview")


class _Copying:
    """A planner that answers with a fixed decision and whatever else the live model copied."""

    def __init__(self, name, args):
        self.name, self.args = name, args

    def plan(self, question, *, rule, **_):
        if "합정역" in question:  # setting up the saved market goes by the rules
            return None
        return to_classification(self.name, self.args, rule=rule, question=question, use_morph=False, today=date(2026, 11, 8))


class FlowTests(_RankingEnv, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.source.__class__ = _TableSource

    def _ask(self, planner=None):
        from app.assistant.bridge import endpoint_table, request_with_session
        from app.assistant.flow import AssistantService
        from app.assistant.history import AssistantHistory
        from app.onboarding import create_onboarding_router

        service = AssistantService(self.store, AssistantHistory(self.store), endpoint_table(create_onboarding_router(self.store)),
                                   planner=planner, use_morph=False, today=date(2026, 11, 8), ranking_source=self.source)
        owner, token = self.store.session(None)
        scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}
        return lambda text: service.handle_message(owner, request_with_session(Request(scope), token), text, None)

    def test_an_open_opinion_looks_over_seoul_whatever_the_model_copied(self):
        ask = self._ask(_Copying("opinion", {"places": ["가산디지털단지", "강남역"]}))
        ask("합정역 카페 매출 어때?")
        data = ask("너가 생각했을때 창업을 한다면 서울에 어느 상권에서 하는 게 좋다고 봐?")
        reply = data["reply"]
        self.assertEqual(reply["kind"], "opinion", reply["text"])
        self.assertIn("서울에서 시험상권11 상권부터", reply["text"])
        self.assertEqual(reply["actions"][0]["label"], "시험상권11 자세히")
        self.assertEqual(reply["suggestions"], ["한식으로 보면?", "치킨으로 보면?", "안정적인 곳 위주로 보면?"])

    def test_one_market_opinion_says_where_it_stands(self):
        self.say("합정역 카페 매출 어때?")
        data = self.say("너라면 여기서 카페 차릴 거야?")
        self.assertEqual(data["reply"]["kind"], "opinion", data["reply"]["text"])
        self.assertIn("서울 중앙값", data["cards"][1]["text"])

    def test_seoul_after_an_opinion_and_a_comparison_of_everything(self):
        self.say("합정역 카페 매출 어때?")
        self.say("너라면 여기서 카페 차릴 거야?")
        again = self.say("서울 전체로 생각해줘")
        self.assertIn("상권부터", again["reply"]["text"], again["reply"]["text"])
        ask = self._ask(_Copying("seoul_overview", {"topics": ["sales_age", "sales_time", "sales_weekday"]}))
        wide = ask("서울 전체 모든 상권들과 업종들로 비교해줘")
        self.assertEqual(wide["reply"]["kind"], "seoul_compare", wide["reply"]["text"])
        self.assertIn("업종별로는", wide["reply"]["text"])

    def test_ages_are_not_chosen_when_nobody_asked(self):
        self.say("합정역 카페 매출 어때?")
        ask = self._ask(_Copying("seoul_overview", {"topics": ["sales_age"]}))
        self.assertEqual(ask("서울은 전반적으로 어때?")["reply"]["kind"], "seoul_compare")
        asked = self._ask(_Copying("seoul_overview", {"topics": ["sales_age"]}))("서울 전체 연령대별 매출 알려줘")
        self.assertEqual(asked["reply"]["kind"], "seoul_overview")
        self.assertEqual(asked["reply"]["suggestions"][-1], "서울 전체 점포 수는?")


class SubstantialMarketTests(unittest.TestCase):
    def test_tiny_or_jumping_markets_are_not_candidates(self):
        def row(code, sales, stores, change):
            figure = {"area_code": code, "name": code, "sales": sales, "stores": stores, "population": 100_000, "closed": 0,
                      "sales_last_year": sales * 100 // (100 + change), "selectable": True}
            return opinions.derive(figure)

        table = [row(f"S{n}", 1_000_000 + n, 20, 5) for n in range(8)] + [row("TINY", 9_000_000, 2, 5), row("JUMP", 9_000_000, 30, 1200)]
        top, compared = opinions.best_markets(table)
        self.assertEqual(compared, 8, "too few at the strict bar, so the relaxed bar; the two outliers stay out")
        self.assertNotIn("TINY", [market["name"] for market in top])
        self.assertNotIn("JUMP", [market["name"] for market in top])

    def test_one_shop_per_store_label_is_not_a_number(self):
        card = {"id": "F2", "topic": "opinion", "status": "available", "text": "", "values": [
            {"label": "점포 1곳당 유동인구", "value": 63328, "unit": "명", "market": "시험", "derived": True}]}
        result = check_answer("점포 1곳당 유동인구가 63,328명이에요. [F2]", [card], opinion=True)
        self.assertTrue(result["ok"], result)


class NamedMarketTests(unittest.TestCase):
    """'강남을지병원' was read as 강남 (강남역·강남구), and the model swapped in the saved 강남역."""

    @staticmethod
    def _service():
        from app.assistant.flow import AssistantService

        class Source(FakeRankingSource):
            def areas(self):
                return {"7000001": {**_area(1, "7000001"), "name": "강남을지병원"}}

        return AssistantService(None, None, {}, ranking_source=Source())

    @staticmethod
    def _cls(text, places):
        return {"text": text, "domain": "market_analysis", "turn_type": "opinion", "topics": ["opinion"],
                "slots": {"locations": [{"text": place, "candidates": []} for place in places], "industries": []}}

    def test_the_market_named_outright_replaces_its_piece_and_a_copied_place(self):
        result = self._service()._with_named_market(self._cls("강남을지병원쪽에서 일식 어때 보여?", ["강남", "강남역"]))
        self.assertEqual(result["named_market"]["area_code"], "7000001")
        self.assertEqual(result["slots"]["locations"], [])

    def test_other_questions_are_left_alone(self):
        cls = self._cls("강남역 카페 어때?", ["강남역"])
        self.assertIs(self._service()._with_named_market(cls), cls)

    def test_the_user_place_beats_a_place_the_model_swapped_in(self):
        rule = classify("강남 쪽 일식 어때 보여? 너라면 차릴 거야?", use_morph=False)
        decided = to_classification("opinion", {"places": ["홍대입구역"]}, rule=rule, question=rule["text"], use_morph=False,
                                    today=date(2026, 11, 8))
        self.assertEqual([m["text"] for m in decided["slots"]["locations"]], ["강남"])


class ConclusionTests(unittest.TestCase):
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

    def test_standing(self):
        strong, weak = {"tier": "상위권"}, {"tier": "하위권"}
        middling = {"tier": "중간"}
        self.assertEqual(opinions.standing({"a": strong, "b": strong, "c": middling}), ("positive", 2, 0))
        self.assertEqual(opinions.standing({"a": weak, "b": weak, "c": strong}), ("cautious", 1, 2))
        self.assertEqual(opinions.standing({"a": strong, "b": weak, "c": middling}), ("mixed", 1, 1))
        self.assertEqual(opinions.standing({"a": middling, "b": middling}), ("cautious", 0, 0))


class AfterSeoulOpinionTests(_RankingEnv, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.source.__class__ = _TableSource

    def test_a_market_named_after_a_seoul_opinion_is_about_that_market(self):
        from unittest.mock import patch as mock_patch

        from app.assistant.flow import AssistantService

        self.say("합정역 카페 매출 어때?")
        first = self.say("너라면 서울 어디에 카페 차릴 거야?")
        self.assertIn("상권부터", first["reply"]["text"], first["reply"]["text"])
        with mock_patch.object(AssistantService, "_with_named_market",
                               lambda service, cls: {**cls, "named_market": {
                                   "area_code": "1111111", "name": "합성 상권 1111111", "district_code": "11440",
                                   "neighborhood_code": "11440660"}}):
            again = self.say("을지병원쪽에서 카페 차리는 거 너라면 어때 보여?")
        self.assertEqual(again["reply"]["kind"], "opinion", again["reply"]["text"])
        self.assertEqual(len(again["cards"]), 2)
        self.assertNotIn("서울 전체", again["cards"][0]["text"])

    def test_irregular_ending(self):
        from app.assistant.korean import soften

        self.assertEqual(soften("강남역이 조금 더 낫아요."), "강남역이 조금 더 나아요.")
