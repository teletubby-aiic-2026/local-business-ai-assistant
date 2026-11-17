"""Every industry of a market, weekday/weekend averages and rankings around a market.

User export 2026-11-08: '강남역 주말 모든 상권의 매출을 알려줘' answered for 커피-음료
only (the industry saved from '합정역 카페'), '그럼 평일은?' named Friday alone,
and '강남역 주변에 있는 다른 상권들 중에 가장 높은 상권은?' listed all of Seoul
with 강남역 itself in it. Synthetic markets and rows only: no raw statistics,
no model, no Maps.
"""
from datetime import date
import unittest
from unittest.mock import patch

from app.assistant.answer_check import check_answer
from app.assistant.facts import weekday_aggregates
from app.assistant.intent import classify
from app.assistant.overview import summed_cards
from app.assistant.planner import to_classification
from app.assistant.ranking import RankingRequest, rank_sales
from app.data_repository import DISTRIBUTION_FIELDS
from tests.test_assistant_ranking import COFFEE, KOREAN, FakeRankingSource, _RankingEnv

# 강남역 3000001 and 신논현역 3000002 are about 1km apart; 홍대입구역 1111111 is far away.
_COORDS = {"3000001": (37.4976, 127.0278), "3000002": (37.5045, 127.0250), "1111111": (37.5572, 126.9245),
           "3000004": (37.5636, 126.9850), "3000005": (37.5446, 127.0557), "3000006": (37.5556, 126.9015)}


class _AllSource(FakeRankingSource):
    """Coordinates for every market, and weekday amounts on every row; 강남역 also has a 한식 row."""

    def areas(self):
        return {code: {**area, "latitude": _COORDS[code][0], "longitude": _COORDS[code][1]}
                for code, area in super().areas().items()}

    def sales(self, period):
        rows, version = super().sales(period)
        rows = {key: dict(row) for key, row in rows.items()}
        rows[("3000001", KOREAN)] = {"THSMON_SELNG_AMT": 1000, "SVC_INDUTY_CD_NM": "한식음식점"}
        for key, row in rows.items():
            if type(row.get("THSMON_SELNG_AMT")) is not int:
                continue
            for number, (_label, field) in enumerate(DISTRIBUTION_FIELDS["sales_weekday"]):
                row[field] = 100 if number < 5 else 300  # 월~금 100 each, 토·일 300 each
        return rows, version


class UnitTests(unittest.TestCase):
    def test_weekday_and_weekend_totals_and_daily_averages(self):
        values = [{"label": day, "value": value, "unit": "원"} for day, value in zip("월화수목금토일", (100,) * 5 + (300, 300))]
        extra, sentence = weekday_aggregates(values, "20262")
        self.assertEqual({v["label"]: v["value"] for v in extra},
                         {"평일 합계": 500, "평일 하루 평균": 8, "주말 합계": 600, "주말 하루 평균": 23})
        self.assertIn("평일(월~금)은 합계 500원, 달력일 기준 하루 평균 8원이고, 주말(토·일)은 합계 600원, 달력일 기준 하루 평균 23원입니다", sentence)
        card = {"id": "F3", "topic": "sales_weekday", "status": "available", "text": "", "values": values + extra}
        self.assertTrue(check_answer("토요일이 가장 많이 팔려요. [F3]", [card])["ok"], "totals are never compared with one day")

    def test_one_market_every_industry_added_up(self):
        cards = summed_cards(_AllSource(), ["sales_total", "sales_weekday"], area_code="3000001", area_name="강남역")
        self.assertEqual([card["topic"] for card in cards], ["conditions", "sales_total", "sales_weekday"])
        self.assertIn("강남역 상권의 전체 업종(2개) 2026년 2분기 추정매출을 합치면 10,000원입니다.", cards[1]["text"])
        days = {v["label"]: v["value"] for v in cards[2]["values"]}
        self.assertEqual((days["토"], days["주말 하루 평균"], days["평일 하루 평균"]), (600, 46, 15))

    def test_rankings_of_every_industry_and_around_a_market(self):
        source = _AllSource()
        every = rank_sales(source, RankingRequest(industry_code=None))
        self.assertEqual(every["items"][0]["area_code"], "1111111", "12,000 + 7,000 + 3,000 + 500 for 홍대입구역")
        self.assertTrue(every["all_industries"])
        near = rank_sales(source, RankingRequest(industry_code=COFFEE, near={
            "lat": 37.4976, "lon": 127.0278, "km": 1.5, "exclude": "3000001", "label": "강남역"}))
        self.assertEqual([item["area_code"] for item in near["items"]], ["3000002"])
        self.assertEqual(near["scope_label"], "강남역 주변 1.5km")


class ClassifyTests(unittest.TestCase):
    def test_every_industry_and_near_are_heard(self):
        every = classify("강남역 주말 모든 상권의 매출을 알려줘", use_morph=False)
        self.assertTrue(every["all_industries"])
        near = classify("그럼 강남역 주변에 있는 다른 상권들 중에 가장 높은 상권은 어디야?", use_morph=False)
        self.assertEqual(near["turn_type"], "ranking")
        self.assertTrue(near["near"])
        self.assertFalse(classify("강남역 카페 주말 매출", use_morph=False)["all_industries"])

    def test_planner_flags_are_checked(self):
        rule = classify("그럼 강남역 주변에 있는 다른 상권들 중에 가장 높은 상권은 어디야?", use_morph=False)
        decided = to_classification("rank_areas", {"industry": "커피-음료", "compare_place": "강남역"}, rule=rule,
                                    question=rule["text"], use_morph=False, today=date(2026, 11, 8))
        self.assertTrue(decided["near"])
        self.assertEqual([m["text"] for m in decided["slots"]["locations"]], ["강남역"])
        every_rule = classify("강남역 주말 모든 상권의 매출을 알려줘", use_morph=False)
        every = to_classification("market_data", {"place": "강남역", "industry": "커피-음료", "topics": ["sales_weekday"]},
                                  rule=every_rule, question=every_rule["text"], use_morph=False, today=date(2026, 11, 8))
        self.assertTrue(every["all_industries"])
        self.assertEqual(every["slots"]["industries"], [], "the saved 커피-음료 does not stand in for every industry")


class FlowTests(_RankingEnv, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.source.__class__ = _AllSource

    def test_every_industry_of_a_market_and_its_daily_averages(self):
        base = self.say("합정역 카페 매출 어때?")["conditions"]
        data = self.say("강남역 주말 모든 상권의 매출을 알려줘")
        reply = data["reply"]
        self.assertEqual(reply["kind"], "all_industries", reply["text"])
        self.assertTrue(reply["text"].startswith("강남역 상권의 전체 업종을 2026년 2분기 자료로 볼게요."), reply["text"])
        self.assertNotIn("커피", reply["text"])
        self.assertIn("주말(토·일)은 합계 1,200원, 달력일 기준 하루 평균 46원", reply["text"])
        self.assertEqual(data["conditions"], base, "the saved conditions stay")
        again = self.say("그럼 평일은?")
        self.assertEqual(again["reply"]["kind"], "all_industries", again["reply"]["text"])
        self.assertIn("평일(월~금)은 합계 1,000원, 달력일 기준 하루 평균 15원", again["reply"]["text"])

    def test_around_a_market_without_the_market_itself(self):
        self.say("합정역 카페 매출 어때?")
        data = self.say("그럼 강남역 주변에 있는 다른 상권들 중에 가장 높은 상권은 어디야?")
        reply = data["reply"]
        self.assertEqual(reply["kind"], "ranking", reply["text"])
        self.assertIn("강남역 주변 1.5km 상권 가운데", reply["text"])
        self.assertIn("1위 신논현역", reply["text"])
        self.assertNotIn("위 강남역", reply["text"])
        self.assertEqual(reply["suggestions"], ["전체 업종으로 보면?"], "커피-음료 came from earlier, so offer every industry")
        every = self.say("전체 업종으로 보면?")
        self.assertIn("전체 업종을 합친", every["reply"]["text"])
        self.assertIn("강남역 주변 1.5km", every["reply"]["text"], "the same ranking, every industry")

    def _service(self, writer=None, planner=None):
        from app.assistant.bridge import endpoint_table, request_with_session
        from app.assistant.flow import AssistantService
        from app.assistant.history import AssistantHistory
        from app.onboarding import create_onboarding_router
        from starlette.requests import Request

        service = AssistantService(self.store, AssistantHistory(self.store), endpoint_table(create_onboarding_router(self.store)),
                                   writer=writer, planner=planner, use_morph=False, today=date(2026, 11, 8),
                                   ranking_source=self.source)
        owner, token = self.store.session(None)
        scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}
        return lambda text: service.handle_message(owner, request_with_session(Request(scope), token), text, None)

    def test_a_follow_up_stays_on_every_industry_even_if_the_model_copies_the_saved_conditions(self):
        class CopyingPlanner:
            """Live HCX-005 answered '그럼 평일은?' with the saved 합정역·커피-음료 (2026-11-08 server test)."""

            def plan(self, question, *, rule, **_):
                if question != "그럼 평일은?":
                    return None
                return to_classification("market_data", {"places": ["홍대입구역"], "industry": "커피-음료",
                                                         "topics": ["sales_weekday"]},
                                         rule=rule, question=question, use_morph=False, today=date(2026, 11, 8))

        ask = self._service(planner=CopyingPlanner())
        ask("합정역 카페 매출 어때?")
        ask("강남역 주말 모든 상권의 매출을 알려줘")
        again = ask("그럼 평일은?")
        self.assertEqual(again["reply"]["kind"], "all_industries", again["reply"]["text"])
        self.assertEqual(again["cards"][0]["text"], "분석 조건은 강남역 상권, 전체 업종, 2026년 2분기 자료입니다.")

    def test_a_data_answer_without_a_number_is_written_again(self):
        calls = []

        def writer(cards, cls):
            calls.append(cls.get("retry"))
            return "주말 매출이 평일보다 적지만 많은 분들이 찾아요. [F2]"

        ask = self._service(writer=writer)
        ask("합정역 카페 매출 어때?")
        data = ask("강남역 주말 모든 상권의 매출을 알려줘")
        self.assertFalse(data["model_used"], data["reply"]["text"])
        self.assertIn("숫자를 카드에서", (calls[-1] or {}).get("feedback", ""))
        self.assertIn("주말(토·일)은 합계 1,200원", data["reply"]["text"], "the fixed answer with its numbers")

    def test_a_ranking_right_after_every_industry_keeps_every_industry(self):
        self.say("합정역 카페 매출 어때?")
        self.say("강남역 주말 모든 상권의 매출을 알려줘")
        data = self.say("그럼 강남역 주변에 있는 다른 상권들 중에 가장 높은 상권은 어디야?")
        self.assertIn("전체 업종을 합친", data["reply"]["text"])
        self.assertEqual(data["reply"]["suggestions"], [])
