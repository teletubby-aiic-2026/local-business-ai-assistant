"""AI planner: the model chooses one tool, code checks it against the dictionaries.

A fake client returns scripted tool calls, so no network and no model are used.
"""
from datetime import date
import json
import unittest

from app.assistant.answer_check import check_answer
from app.assistant.planner import Planner, build_context, parse_decision, safe_reply, to_classification
from app.assistant.intent import classify
from tests.test_assistant_flow import _Env
from tests.test_assistant_ranking import FakeRankingSource

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


class ToClassificationTests(unittest.TestCase):
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
        self.assertEqual(plan("market_data", {"topics": [], "unavailable": "회사·직장인 수"})["unavailable"], "회사·직장인 수")
        self.assertIsNone(plan("market_data", {"topics": [], "unavailable": "가" * 40})["unavailable"])

    def test_model_lines_that_only_repeat_the_missing_note_are_dropped(self):
        from app.assistant import templates

        cards = [{"id": "F1", "topic": "conditions", "text": "분석 조건은 합성 상권입니다.", "values": []},
                 {"id": "F6", "topic": "stores_count", "text": "전체 점포는 316개입니다.",
                  "values": [{"label": "전체 점포", "value": 316, "unit": "개"}]}]
        live = "죄송합니다. 프랜차이즈 브랜드 이름은 제공된 자료에 없습니다. [F6]"  # HCX-005, 2026-11-08
        self.assertEqual(templates.model_body(live, cards, show_conditions=False, drop_missing_notes=True), "")
        kept = templates.model_body(live + "\n전체 점포는 316개예요. [F6]", cards, show_conditions=False,
                                    drop_missing_notes=True)
        self.assertEqual(kept, "전체 점포는 316개예요. [F6]")
        self.assertIn("죄송", templates.model_body(live, cards, show_conditions=False))
        grouped = templates.model_body("점포는 316개예요. [F1,F6]", cards, show_conditions=False)
        self.assertEqual(grouped, "점포는 316개예요. [F1][F6]")
        guess = "목요일 매출이 커서 직장인이 많이 찾을 것으로 예상됩니다. [F6]"
        self.assertFalse(check_answer(guess, cards)["ok"])

    def test_interpretation_is_allowed_only_as_a_marked_line(self):
        from app.assistant import templates

        cards = [{"id": "F1", "topic": "conditions", "text": "분석 조건은 합성 상권입니다.", "values": []},
                 {"id": "F4", "topic": "sales_time", "text": "시간대별 매출에서 가장 높은 항목은 11~14시입니다.",
                  "values": [{"label": "11~14시", "value": 300, "unit": "원", "share_percent": 30.0}]}]
        # User decision 2026-11-08: the live sentence below may stay, marked as an interpretation.
        live = ("점심(11~14시) 매출이 300원(30.00%)으로 가장 커요. [F4]\n"
                "매출이 가장 많은 시간대는 점심시간이며, 이는 직장인들이 몰리는 시간임을 시사합니다. [F4]")
        body = templates.model_body(live, cards, show_conditions=False)
        self.assertTrue(body.splitlines()[1].startswith("해석: "), body)
        self.assertTrue(check_answer(body, cards)["ok"], check_answer(body, cards))
        for text in ("해석: 점심 매출이 300원이라 직장인이 많아요.", "해석: 유동인구가 줄어서 매출이 감소했을 수 있어요.",
                     "해석: 경기 때문일 수 있어요.", "직장인이 많이 찾을 것으로 예상됩니다. 점심은 300원이에요. [F4]"):
            self.assertFalse(check_answer(text, cards)["ok"], text)
        many = "\n".join(f"손님층이 {word}일 수 있음을 시사해요." for word in ("직장인", "학생", "관광객"))
        self.assertEqual(templates.model_body(many, cards, show_conditions=False).count("해석:"), 2)

    def test_market_choices_put_markets_with_data_first(self):
        from app.assistant.ranking import order_markets

        source = FakeRankingSource()
        areas = [source.areas()[code] for code in ("3000006", "1111111", "3000001")]
        areas.insert(1, {"area_code": "9999998", "name": "자료 없는 상권"})
        ordered = [area["area_code"] for area in order_markets(source, areas)]
        self.assertEqual(ordered, ["1111111", "3000001", "3000006"])

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


class PlannerFlowTests(_Env, unittest.TestCase):
    def service(self, *steps):
        from app.assistant.bridge import endpoint_table
        from app.assistant.flow import AssistantService
        from app.assistant.history import AssistantHistory
        from app.onboarding import create_onboarding_router

        self.fake = FakeClient(*steps)
        self.svc = AssistantService(self.store, AssistantHistory(self.store),
                                    endpoint_table(create_onboarding_router(self.store)), use_morph=False, today=TODAY,
                                    ranking_source=FakeRankingSource(), planner=Planner(self.fake, use_morph=False))
        self.owner, self.token = self.store.session(None)

    def say(self, text):
        from starlette.requests import Request

        from app.assistant.bridge import request_with_session

        scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}
        return self.svc.handle_message(self.owner, request_with_session(Request(scope), self.token), text, None)

    def test_the_model_reads_the_dialogue_and_code_executes(self):
        self.service(("rank_industries", {"place": "홍대"}), ("rank_industries", {"place": "홍대"}),
                     ("small_talk", {"reply": "서울 상권 자료를 알려드리는 상권 비서예요. 궁금한 동네를 말씀해 주세요."}))
        first = self.say("홍대에서 창업을 하고 싶은데 어떤로 창업하면 될까")
        self.assertEqual(first["reply"]["kind"], "industry_rank")
        self.assertEqual(first["classification"]["analyzer"], "clova-planner")
        again = self.say("추천해줘")
        self.assertEqual(again["reply"]["kind"], "industry_rank")
        context = self.fake.bodies[1]["messages"][-1]["content"]
        self.assertIn("사용자: 홍대에서 창업을 하고 싶은데 어떤로 창업하면 될까", context, "the model sees the dialogue")
        self.assertNotIn("tools", self.fake.bodies[1], "JSON decisions, not CLOVA function calling")
        talk = self.say("너 누구야")
        self.assertEqual((talk["reply"]["kind"], talk["model_used"]), ("smalltalk", True))

    def test_missing_data_is_said_first_and_unknown_industries_are_asked(self):
        self.service(("market_data", {"place": "합정역", "industry": "카페", "topics": ["sales_total"]}),
                     ("market_data", {"topics": ["stores_count"], "unavailable": "프랜차이즈 브랜드별 매출"}),
                     ("rank_areas", {"industry": "마라탕집"}), ("rank_areas", {"industry": "중식음식점"}),
                     ("rank_areas", {"industry": "카페"}))
        self.say("합정역 카페 매출 어때?")
        brand = self.say("프랜차이즈들 중에서 어느 프랜차이즈가 매출이 높아?")
        self.assertTrue(brand["reply"]["text"].startswith(
            "말씀하신 프랜차이즈 브랜드별 매출은 상권 공공 자료에 없어서 알려드릴 수 없어요."), brand["reply"]["text"])
        asked = self.say("서울에서 마라탕집 매출 높은 곳 어디야")
        self.assertEqual(asked["reply"]["kind"], "need_industry")
        self.assertIn("'마라탕집'", asked["reply"]["text"])
        ranked = self.say("중식음식점")
        self.assertEqual(ranked["reply"]["kind"], "ranking", "the industry answer continues the ranking question")
        gu = self.say("너가 카페 창업을 한다면 서울 무슨구에 할 것 같아?")
        self.assertIn("위 상권들이 속한 구는", gu["reply"]["text"])

    def test_failures_fall_back_to_the_rule_classifier(self):
        self.service(RuntimeError("quota"), ("delete_everything", {}),
                     ("small_talk", {"reply": "카페 매출은 1,000원이에요."}))
        self.assertEqual(self.say("ㅁㄴㅇㄹ")["reply"]["kind"], "unknown")
        self.assertEqual(self.say("안녕")["reply"]["kind"], "smalltalk")
        talk = self.say("안녕하세요")
        self.assertFalse(talk["model_used"], "a reply with statistics is replaced by the fixed text")
        self.assertNotIn("1,000원", talk["reply"]["text"])


if __name__ == "__main__":
    unittest.main()
