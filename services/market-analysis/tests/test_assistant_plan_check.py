"""The planner and question analysis on their own: a fake client, no network, no chatbot flow.

These cases come from the chatbot's test files, so that this code can be tested
without the rest of the assistant.
"""
from datetime import date
import json
import unittest

from app.assistant.intent import classify
from app.assistant.planner import Planner, build_context, parse_decision, safe_reply, to_classification


TODAY = date(2026, 11, 8)


def rule(text):
    return classify(text, today=TODAY, use_morph=False)


def plan(name, args, text="질문"):
    return to_classification(name, args, rule=rule(text), question=text, use_morph=False, today=TODAY)


class FakeClient:
    """Answers each call with the next scripted (tool, arguments) or raises the scripted error."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.bodies = []

    def complete(self, body, *, purpose):
        self.bodies.append(body)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        name, args = step
        call = {"id": "call-1", "type": "function",
                "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
        return {"message": {"role": "assistant", "content": "", "toolCalls": [call]}, "finishReason": "tool_calls"}


class AllindClassifyTests(unittest.TestCase):
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


class MultiPlannerPlacesTests(unittest.TestCase):
    def test_places_list_becomes_every_location(self):
        rule = {"turn_type": "unknown", "topics": [], "slots": {"locations": [], "industries": [],
                                                                "period": {"period_code": None}}}
        decided = to_classification("market_data", {"places": ["합정역", "강남역"], "topics": ["sales_age"]}, rule=rule,
                                    question="합정역과 강남역의 주 고객 연령대를 알려줘", use_morph=False,
                                    today=date(2026, 11, 8))
        self.assertEqual([m["text"] for m in decided["slots"]["locations"]], ["합정역", "강남역"])
        self.assertEqual(decided["topics"], ["sales_age"])


class OpinionPlannerTests(unittest.TestCase):
    RULE = {"turn_type": "unknown", "topics": [], "slots": {"locations": [], "industries": [],
                                                           "period": {"period_code": None}}}

    def test_opinion_and_overview_decisions(self):
        decided = to_classification("opinion", {"places": ["연남동", "강남역"]}, rule=self.RULE,
                                    question="두 지역 중 어디가 나아?", use_morph=False, today=date(2026, 11, 8))
        self.assertEqual((decided["turn_type"], decided["topics"]), ("opinion", ["opinion"]))
        self.assertEqual([m["text"] for m in decided["slots"]["locations"]], ["연남동", "강남역"])
        overview = to_classification("seoul_overview", {}, rule=self.RULE, question="모든 곳을 통계적으로 말해줘",
                                     use_morph=False, today=date(2026, 11, 8))
        self.assertEqual((overview["turn_type"], overview["topics"]), ("seoul_overview", ["sales_age"]))
        # A place, or an answer to '어떤 업종을 볼까요?', is about one market even if the model says Seoul.
        named = {**self.RULE, "slots": {**self.RULE["slots"], "locations": [{"text": "연남동", "candidates": [
            {"kind": "neighborhood", "label": "연남동", "name": "연남동", "code": "11440710", "district_code": "11440"}]}]}}
        place = to_classification("seoul_overview", {}, rule=named, question="연남동", use_morph=False,
                                  today=date(2026, 11, 8))
        self.assertEqual(place["turn_type"], "data_question")
        answer = to_classification("seoul_overview", {"industry": "카페"}, rule=self.RULE, question="카페",
                                   use_morph=False, today=date(2026, 11, 8), setting_up=True)
        self.assertEqual(answer["turn_type"], "condition_change")
        compare = to_classification("market_data", {"compare_place": "강남역", "topics": []}, rule=self.RULE,
                                    question="강남역이랑 비교해줘", use_morph=False, today=date(2026, 11, 8))
        self.assertEqual(compare["topics"], ["comparison"], "a comparison alone gets no default topics")


class PlannerToClassificationTests(unittest.TestCase):
    def test_market_data_resolves_names_through_the_dictionaries(self):
        result = plan("market_data", {"place": "홍대", "industry": "카페", "topics": ["sales_time", "made_up"]})
        self.assertEqual((result["turn_type"], result["topics"]), ("data_question", ["sales_time"]))
        self.assertEqual([m["text"] for m in result["slots"]["locations"]], ["홍대"])
        self.assertEqual({c["code"] for m in result["slots"]["industries"] for c in m["candidates"]}, {"CS100010"})
        invented = plan("market_data", {"place": "가짜마을", "topics": ["sales_total"]})
        self.assertEqual(invented["slots"]["locations"], [], "a place outside the dictionary is dropped")
        moved = plan("market_data", {"place": "망원역", "topics": []})
        self.assertEqual(moved["turn_type"], "condition_change")
        vague = plan("market_data", {"topics": []})
        self.assertEqual((vague["turn_type"], vague["topics_defaulted"]), ("data_question", True))
        period = plan("market_data", {"period": "2025년 3분기", "topics": ["sales_total"]})
        self.assertEqual(period["slots"]["period"]["period_code"], "20253")
        compared = plan("market_data", {"place": "연남동", "compare_place": "망원역", "topics": ["sales_total"]})
        self.assertIn("comparison", compared["topics"])
        self.assertEqual(len(compared["slots"]["locations"]), 2)

    def test_odd_argument_shapes_never_break_a_turn(self):
        listed = plan("market_data", {"place": ["홍대", "합정역"], "topics": "sales_total", "period": 20253})
        self.assertEqual([m["text"] for m in listed["slots"]["locations"]], ["홍대", "합정역"])
        self.assertEqual(listed["topics"], ["sales_total"])
        for args in ({"place": {"name": "홍대"}}, {"topics": None, "count": "3"}, {"exclude_places": "강남"}):
            for name in ("market_data", "rank_areas", "rank_industries"):
                self.assertIsNotNone(plan(name, args), (name, args))
        planner = Planner(FakeClient(("market_data", {"compare_place": 7})), use_morph=False)
        self.assertIsNotNone(planner.plan("비교", rule=rule("비교"), conditions=None, recent=[], loaded=[], today=TODAY))

    def test_names_in_the_question_fill_what_the_model_left_out(self):
        both = plan("market_data", {"industry": "분식집", "topics": ["stores_count"]},
                    text="노원구 분식집이랑 치킨집 중에 어느 쪽이 더 많아")
        self.assertEqual(len({c["code"] for m in both["slots"]["industries"] for c in m["candidates"]}), 2)
        missing = plan("market_data", {"topics": ["sales_total"]}, text="망원역 빵집 매출")
        self.assertEqual([m["text"] for m in missing["slots"]["locations"]], ["망원역"])
        chosen = plan("market_data", {"industry": "치킨", "topics": []}, text="카페 말고 치킨으로 바꿔줘")
        self.assertEqual({c["name"] for m in chosen["slots"]["industries"] for c in m["candidates"]},
                         {c["name"] for m in rule("치킨")["slots"]["industries"] for c in m["candidates"]},
                         "the model's choice stays when the question's names are not a superset")

    def test_code_guards_what_the_model_got_wrong_in_live_tests(self):
        # HCX-005 chose rank_industries for this and excluded 분식, which the user never asked for.
        text = "망원동에서 분식집 하려는데 상권 어때?"
        about = plan("rank_industries", {"place": "망원동", "exclude_industries": ["분식집"]}, text=text)
        self.assertEqual((about["turn_type"], about["topics_defaulted"]), ("data_question", True))
        self.assertTrue(about["slots"]["industries"])
        listed = plan("rank_industries", {"place": "망원동", "exclude_industries": ["카페"]}, text="망원동에서 뭐 하면 좋아?")
        self.assertEqual(listed["slots"]["excluded_industries"], [], "no 말고 in the question, no exclusion")
        asked = plan("rank_industries", {"exclude_industries": ["카페"]}, text="카페 말고 다른 업종은?")
        self.assertEqual([m["text"] for m in asked["slots"]["excluded_industries"]], ["카페"])
        # The model left out '강남' in a live run; the '말고' the rules found in the question still applies.
        forgot = plan("rank_areas", {"industry": "카페"}, text="강남 말고 서울에서 카페 매출 높은 곳")
        self.assertEqual([m["text"] for m in forgot["slots"]["excluded_locations"]], ["강남"])
        forgot = plan("rank_industries", {}, text="카페 말고 다른 업종 추천해줘")
        self.assertEqual([m["text"] for m in forgot["slots"]["excluded_industries"]], ["카페"])

    def test_area_rankings_need_a_list_cue_and_counts_come_from_the_question(self):
        about = plan("rank_areas", {"within_place": "망원동", "industry": "분식집"}, text="망원동에서 분식집 하려는데 상권 어때?")
        self.assertEqual(about["turn_type"], "data_question")
        listed = plan("rank_areas", {"industry": "치킨"}, text="그럼 치킨은?")
        self.assertEqual(listed["turn_type"], "data_question", "no cue and no list before it")
        again = to_classification("rank_areas", {"industry": "치킨"}, rule=rule("그럼 치킨은?"), question="그럼 치킨은?",
                                  use_morph=False, today=TODAY, after_list=True)
        self.assertEqual(again["turn_type"], "ranking")
        self.assertEqual(plan("rank_areas", {"industry": "카페", "count": 1}, text="카페 매출 높은 곳")["slots"]["count"], None)
        self.assertEqual(plan("rank_industries", {"count": 1}, text="업종 네 개만 알려줘")["slots"]["count"], 4)

    def test_user_test_2026_11_08_sentences(self):
        # '중식점' was not in the dictionary and the saved 커피-음료 ranking was shown instead.
        chinese = plan("rank_areas", {"industry": "중식점"}, text="서울시에서 중식점 매출이 가장 높은 곳은 어디야?")
        self.assertEqual({c["code"] for m in chinese["slots"]["industries"] for c in m["candidates"]}, {"CS100002"})
        odd = plan("rank_areas", {"industry": "마라탕집"}, text="서울에서 마라탕집 매출 높은 곳 어디야")
        self.assertEqual((odd["slots"]["industries"], odd["unresolved_industry"]), ([], "마라탕집"))
        # '무슨 구' asks for a list, so the guard keeps the model's area ranking.
        gu = plan("rank_areas", {"industry": "커피"}, text="너가 커피 관련해서 창업을 한다면 서울 무슨구에 창업을 할것같아?")
        self.assertEqual(gu["turn_type"], "ranking")
        # Brand names are not in the data: the note is kept and must be short text without digits.
        brand = plan("market_data", {"topics": ["stores_count"], "unavailable": "프랜차이즈 브랜드별 매출"},
                     text="프랜차이즈들 중에서 어느 프랜차이즈가 매출이 높아?")
        self.assertEqual(brand["unavailable"], "프랜차이즈 브랜드별 매출")
        self.assertIsNone(plan("market_data", {"topics": [], "unavailable": "매출 1위 브랜드 3개"})["unavailable"])
        # Live run: '점심이랑 저녁 중에 언제 더 팔려?' came back with unavailable '점심, 저녁', which the data has.
        self.assertIsNone(plan("market_data", {"topics": ["sales_time"], "unavailable": "점심, 저녁"})["unavailable"])
        self.assertEqual(plan("market_data", {"topics": [], "unavailable": "브랜드별 매출"})["unavailable"], "브랜드별 매출")
        self.assertIsNone(plan("market_data", {"topics": [], "unavailable": "가" * 40})["unavailable"])

    def test_rankings_and_exclusions(self):
        areas = plan("rank_areas", {"industry": "카페", "exclude_places": ["강남"], "count": 9},
                     text="강남 말고 카페 매출 높은 곳 탑9")
        self.assertEqual((areas["turn_type"], areas["slots"]["count"]), ("ranking", 5))
        self.assertEqual([m["text"] for m in areas["slots"]["excluded_locations"]], ["강남"])
        industries = plan("rank_industries", {"place": "연남동", "exclude_industries": ["카페"]},
                          text="연남동에서 카페 말고 뭐가 좋아?")
        self.assertEqual(industries["turn_type"], "industry_rank")
        self.assertEqual([m["text"] for m in industries["slots"]["locations"]], ["연남동"])
        self.assertEqual([m["text"] for m in industries["slots"]["excluded_industries"]], ["카페"])

    def test_free_text_is_checked_and_unknown_tools_are_refused(self):
        self.assertEqual(plan("small_talk", {"reply": "반가워요! 궁금한 동네를 말씀해 주세요."})["ai_reply"],
                         "반가워요! 궁금한 동네를 말씀해 주세요.")
        self.assertIsNone(plan("small_talk", {"reply": "홍대 카페 매출은 1,000원이에요."})["ai_reply"])
        self.assertIsNone(safe_reply("요즘 장사가 잘 안되는 건 경기 때문이에요."))
        self.assertIsNone(safe_reply("가" * 300))
        self.assertEqual(plan("ask_user", {"reply": "어느 동네를 볼까요?"})["turn_type"], "clarify")
        self.assertEqual(plan("handoff", {"domain": "marketing"})["domain"], "marketing")
        self.assertIsNone(plan("handoff", {"domain": "finance"}))
        self.assertIsNone(plan("delete_everything", {}))
        self.assertIsNone(plan(None, {}))

    def test_json_decisions_are_parsed_and_anything_else_is_refused(self):
        def reply(content):
            return {"message": {"role": "assistant", "content": content}}

        self.assertEqual(parse_decision(reply('{"action": "rank_industries", "args": {"place": "연남동"}}')),
                         ("rank_industries", {"place": "연남동"}))
        self.assertEqual(parse_decision(reply('판단: {"action": "small_talk", "args": {"reply": "안녕하세요"}} 입니다'))[0],
                         "small_talk")
        for content in ("도구: rank_industries", '{"action": "drop_table"}', "{not json}", '["market_data"]', ""):
            self.assertIsNone(parse_decision(reply(content))[0], content)

    def test_context_carries_every_reference(self):
        text = build_context("추천해줘", rule=rule("추천해줘"), conditions=None,
                             recent=["사용자: 연남동에서 창업하고 싶어", "상권 비서: …"], loaded=["F2 (sales_total) 매출"],
                             use_morph=False)
        for part in ("[지금 조건]\n아직 정하지 않음", "사용자: 연남동에서 창업하고 싶어", "[불러 둔 자료]\nF2", "[형태소 분석]",
                     "[사전 후보]", "[규칙 분류기 추측]\nunknown", "[비슷한 예문]", '→ {"action": "rank_industries"',
                     "[질문]\n추천해줘"):
            self.assertIn(part, text)


class Round4WordingTests(unittest.TestCase):
    def test_rules_hear_an_open_opinion_and_a_seoul_comparison(self):
        self.assertEqual(classify("너가 생각했을때 서울에 어느 상권이 좋다고 봐?", use_morph=False)["turn_type"], "opinion")
        self.assertEqual(classify("서울 전체 모든 상권들과 업종들로 비교해줘", use_morph=False)["turn_type"], "seoul_overview")


class Round4NamedMarketTests(unittest.TestCase):
    def test_the_user_place_beats_a_place_the_model_swapped_in(self):
        rule = classify("강남 쪽 일식 어때 보여? 너라면 차릴 거야?", use_morph=False)
        decided = to_classification("opinion", {"places": ["홍대입구역"]}, rule=rule, question=rule["text"], use_morph=False,
                                    today=date(2026, 11, 8))
        self.assertEqual([m["text"] for m in decided["slots"]["locations"]], ["강남"])


class Round5CheckerTests(unittest.TestCase):
    def test_rule_classifier_knows_these_are_data_now(self):
        self.assertIn("area_profile", classify("합정역 직장인구 얼마나 돼?", use_morph=False)["topics"])
        self.assertIn("area_profile", classify("거기 근처에 회사 많아?", use_morph=False)["topics"])


class Round6OtherIndustriesTests(unittest.TestCase):
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


class Round6FlowTests(unittest.TestCase):
    def test_the_rules_hear_a_highest_zone_as_a_ranking(self):
        self.assertEqual(classify("서울시 안에서 상권들 중 제일 매출액이 높은 구역은 어디임?", use_morph=False,
                                  today=TODAY)["turn_type"], "ranking")


class PlannerFailureTests(unittest.TestCase):
    def test_a_failing_client_returns_none_so_the_rules_answer(self):
        class Broken:
            def complete(self, request, purpose):
                raise RuntimeError("no key")

        question = "합정역 카페 매출 어때?"
        planner = Planner(Broken(), use_morph=False)
        with self.assertLogs("app.assistant.planner", "WARNING"):
            planned = planner.plan(question, rule=classify(question, use_morph=False), conditions=None,
                                   recent=[], loaded=[])
        self.assertIsNone(planned)
        self.assertTrue(planner.last_failure.startswith("call:"))


if __name__ == "__main__":
    unittest.main()
