"""Opinions, Seoul-wide sums and comparison checks (user test 2026-11-08).

The user showed that the assistant only listed statistics: it refused '두 지역 중
어디를 추천할 것 같아?', called 점심 stronger than 저녁 while the numbers said the
opposite, and described markets with words no card supports. Synthetic markets
and rows only: no raw statistics, no model, no Maps.
"""
from datetime import date
import unittest
from unittest.mock import patch

from starlette.requests import Request

from app.assistant import opinion as opinions
from app.assistant import templates
from app.assistant.answer_check import check_answer, comparison_problems
from app.assistant.overview import seoul_cards
from app.assistant.planner import to_classification
from app.data_repository import DISTRIBUTION_FIELDS
from tests.test_assistant_flow import metric
from tests.test_assistant_ranking import COFFEE, FakeRankingSource, _RankingEnv

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


class ComparisonCheckTests(unittest.TestCase):
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

    def test_lines_without_a_card_are_dropped(self):
        live = ("강남역 매출이 연남동보다 약 6,352,851,070원 많아요. [F11]\n"
                "연남동은 강남역에 비해 규모가 작은 편이지만 그만큼 볼거리가 많은 곳이죠.\n"
                "해석: " + "어느 상권이든 손님층에 맞춰 준비하면 좋을 수 있어요. " * 3)
        body = templates.model_body(live, [PLACES], show_conditions=False)
        self.assertEqual(body, "강남역 매출이 연남동보다 6,352,851,070원 많아요. [F11]")
        verdict = "저라면 강남역 쪽을 고르겠어요.\n강남역 매출이 13,638,954,166원으로 더 커요. [F11]"
        self.assertIn("저라면", templates.model_body(verdict, [PLACES], show_conditions=False, opinion=True))
        self.assertNotIn("저라면", templates.model_body(verdict, [PLACES], show_conditions=False))

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


def _two_markets():
    first = {"name": "가나역", "area_code": "1", "sales": 1000, "stores": 20, "opened": 2, "closed": 1,
             "population": 6000, "sales_last_year": 800}
    second = {"name": "다라동", "area_code": "2", "sales": 3000, "stores": 30, "opened": 1, "closed": 3,
              "population": 6000, "sales_last_year": 3000}
    return [opinions.derive(first), opinions.derive(second)]


class OpinionCardTests(unittest.TestCase):
    def test_criteria_are_computed_and_led(self):
        markets = _two_markets()
        self.assertEqual((markets[0]["per_store_sales"], markets[1]["per_store_sales"]), (50, 100))
        self.assertEqual((markets[0]["yoy"], markets[1]["yoy"]), (25.0, 0.0))
        self.assertEqual((markets[0]["per_store_people"], markets[1]["per_store_people"]), (300, 200))
        self.assertEqual((markets[0]["closure_rate"], markets[1]["closure_rate"]), (5.0, 10.0))
        leaders = {item["key"]: item["leader"] for item in opinions.leads(markets)}
        self.assertEqual(leaders, {"per_store_sales": "다라동", "yoy": "가나역", "per_store_people": "가나역",
                                   "closure_rate": "가나역"})
        card = {**opinions.opinion_card(markets, industry_name="한식음식점", period_label="2026년 2분기"), "id": "F2"}
        self.assertIn("4개 기준 가운데 가나역 3개, 다라동 1개에서 앞섭니다.", card["text"])
        lines = opinions.fixed_lines(markets, "F2")
        self.assertEqual(lines[0], "자료로만 보면 저는 가나역 쪽이 조금 더 나아 보여요. [F2]")
        self.assertIn("점포당 분기 추정매출은 가나역 50원, 다라동 100원으로 다라동이 앞서요. [F2]", lines)
        self.assertIn("점포 1곳당 유동인구는 가나역 300명, 다라동 200명으로 가나역이 앞서요. [F2]", lines)
        # The fixed opinion passes the same checks as a model's.
        self.assertTrue(check_answer("\n".join(lines), [card], opinion=True)["ok"],
                        check_answer("\n".join(lines), [card], opinion=True))

    def test_a_tie_and_one_market(self):
        first, second = _two_markets()
        second.update(per_store_sales=50, yoy=25.0, per_store_people=300, closure_rate=5.0)
        self.assertIn("엇갈려서", opinions.fixed_lines([first, second], "F2")[0])
        single = opinions.fixed_lines([{**first, "rank": 3, "ranked": 100}], "F2")
        self.assertEqual(single[0], "자료로만 보면 가나역 상권은 해볼 만한 쪽으로 보여요. [F2]")
        self.assertIn("작년 같은 분기 대비 매출 변화율은 +25.00%예요. [F2]", single)
        self.assertIn("서울 100곳 가운데 매출 3위(상위 3.00%, 상위권)예요. [F2]", single)
        card = {**opinions.opinion_card([{**first, "rank": 3, "ranked": 100}], industry_name="한식음식점",
                                        period_label="2026년 2분기"), "id": "F2"}
        self.assertIn("가나역은 서울 한식음식점 상권 100곳 가운데 매출 3위(상위 3.00%, 상위권)입니다(매출 총액 기준).", card["text"])
        result = check_answer("\n".join(single), [card], opinion=True)
        self.assertTrue(result["ok"], result)


class _SeoulSource(FakeRankingSource):
    """Age and time amounts on every coffee row; one row lacks an age value and is left out whole."""

    def sales(self, period):
        rows, version = super().sales(period)
        rows = {key: dict(row) for key, row in rows.items()}
        for index, (key, row) in enumerate(sorted(rows.items())):
            if key[1] != COFFEE:
                continue
            for number, (_label, field) in enumerate(DISTRIBUTION_FIELDS["sales_age"]):
                row[field] = (number + 1) * 10
            for number, (_label, field) in enumerate(DISTRIBUTION_FIELDS["sales_time"]):
                row[field] = 100 if number == 4 else 10
        rows[("3000005", COFFEE)][DISTRIBUTION_FIELDS["sales_age"][0][1]] = None
        return rows, version


class SeoulOverviewTests(unittest.TestCase):
    def test_every_market_is_added_up(self):
        cards = seoul_cards(_SeoulSource(), ["sales_age"], industry_code=COFFEE, industry_name="커피-음료")
        self.assertEqual([card["id"] for card in cards], ["F1", "F2"])
        values = {value["label"]: value for value in cards[1]["values"]}
        # Five catalogued markets with every age value (3000005 lacks one, 9999999 is not in the catalogue).
        self.assertEqual(values["합친 상권 수"]["value"], 5)
        self.assertEqual(values["20대"]["value"], 100)
        self.assertEqual(values["60대 이상"]["share_percent"], 28.57)
        self.assertIn("가장 큰 항목은 60대 이상으로 300원(비중 28.57%)", cards[1]["text"])
        self.assertIn("사람 수가 아니라 매출액 기준", cards[1]["text"])
        self.assertTrue(check_answer("60대 이상이 300원으로 가장 커요. [F2]", cards)["ok"])
        self.assertEqual(seoul_cards(FakeRankingSource(), ["sales_age"]), [], "rows without age values add nothing")


class PlannerTests(unittest.TestCase):
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


class OpinionFlowTests(_RankingEnv, unittest.TestCase):
    def setUp(self):
        super().setUp()
        areas = [{"area_code": "3000001", "name": "강남역", "district_code": "11680", "district_name": "강남구",
                  "selectable": True}]

        def comparison(selection, profile, area_code):
            return {"status": "complete", "base_area": {"name": selection["area_name"]},
                    "comparison_area": {"name": "강남역"},
                    "metrics": [metric("sales", "추정매출", "원", 1000, 3000, "base", "comparison"),
                                metric("stores_total", "전체 점포", "개", 20, 30, "base", "comparison"),
                                metric("stores_closed", "폐업 점포", "개", 1, 3, "base", "comparison"),
                                metric("floating_population", "지역 유동인구 원천 총지표", "명", 6000, 6000,
                                       "base", "comparison")], "warnings": []}

        self.stack.enter_context(patch("app.onboarding_comparison.get_comparison_options",
                                       lambda selection, profile: {"status": "ready", "areas": areas}))
        self.stack.enter_context(patch("app.onboarding_comparison.build_comparison_analysis", comparison))

    def test_two_places_just_compared_get_an_opinion(self):
        self.say("합정역 카페 매출 어때?")
        self.say("강남역이랑 비교하면 어때?")
        data = self.say("두 지역 중 창업한다면 어디를 추천할 것 같아?")
        reply = data["reply"]
        self.assertEqual(reply["kind"], "opinion", reply["text"])
        self.assertEqual([card["topic"] for card in data["cards"]], ["conditions", "opinion"])
        lines = reply["text"].splitlines()
        self.assertEqual(lines[0], "자료로만 보면 저는 합성 상권 1111111 쪽이 조금 더 나아 보여요. [F2]")
        self.assertIn("점포당 분기 추정매출은 합성 상권 1111111 50원, 강남역 100원으로 강남역이 앞서요. [F2]", lines)
        self.assertEqual(lines[-1], opinions.CAVEAT)
        body = "\n".join(line for line in lines if "기준 비중은" not in line)  # the weights are the server's own line
        self.assertTrue(check_answer(body, data["cards"], opinion=True)["ok"])
        # '너의 생각이 궁금해' afterwards is the same kind of question.
        self.assertEqual(self.say("너의 생각이 궁금해서 그런 거야")["reply"]["kind"], "opinion")

    def test_one_market_gets_an_opinion_too(self):
        self.say("합정역 카페 매출 어때?")
        data = self.say("너라면 여기서 카페 차릴 거야?")
        self.assertEqual(data["reply"]["kind"], "opinion", data["reply"]["text"])
        self.assertIn("합성 상권 1111111 상권은", data["reply"]["text"].splitlines()[0])

    def test_a_model_opinion_that_contradicts_the_card_is_not_used(self):
        from app.assistant.bridge import endpoint_table, request_with_session
        from app.assistant.flow import AssistantService
        from app.assistant.history import AssistantHistory
        from app.onboarding import create_onboarding_router

        said = {"text": ""}
        service = AssistantService(self.store, AssistantHistory(self.store), endpoint_table(create_onboarding_router(self.store)),
                                   writer=lambda cards, cls: said["text"], use_morph=False, today=date(2026, 11, 8),
                                   ranking_source=self.source)
        owner, token = self.store.session(None)
        scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}

        def ask(text):
            return service.handle_message(owner, request_with_session(Request(scope), token), text, None)

        said["text"] = "합성 상권 1111111 매출은 1,000원이에요. [F2]"
        ask("합정역 카페 매출 어때?")
        ask("강남역이랑 비교하면 어때?")
        said["text"] = ("저라면 합성 상권 1111111 쪽을 고르겠어요.\n"
                        "점포당 분기 추정매출이 합성 상권 1111111이 강남역보다 높아요. [F2]")
        wrong = ask("두 곳 중 어디가 나아?")
        self.assertFalse(wrong["model_used"], wrong["reply"]["text"])
        said["text"] = ("저라면 합성 상권 1111111 쪽을 고르겠어요.\n"
                        "점포 1곳당 유동인구가 합성 상권 1111111 300명으로 강남역 200명보다 많아요. [F2]")
        right = ask("두 곳 중 어디가 나아?")
        self.assertTrue(right["model_used"], right["reply"]["text"])
        self.assertTrue(right["reply"]["text"].endswith(opinions.CAVEAT))

    def test_seoul_wide_question_keeps_the_saved_conditions(self):
        self.source.__class__ = _SeoulSource
        data = self.say("서울시의 모든 상권을 이용하는 연령층을 알려줘")
        self.assertEqual(data["reply"]["kind"], "seoul_overview", data["reply"]["text"])
        self.assertEqual([card["topic"] for card in data["cards"]], ["conditions", "sales_age"])
        self.assertNotIn("conditions", data, "the bar above the chat is not touched")

    def test_the_industry_is_asked_again_with_buttons(self):
        self.say("연남동")
        again = self.say("프랜차이즈")
        self.assertEqual(again["reply"]["kind"], "need_industry")
        self.assertIn("프랜차이즈 수는 업종마다", again["reply"]["text"])
        self.assertIn("카페", [action["label"] for action in again["reply"]["actions"]])


class GuardTests(unittest.TestCase):
    """Server test 2026-11-08: the planner set 카페 for '연남동' on its own and echoed '연남동(홍대)' back."""

    RULE = PlannerTests.RULE

    def test_an_industry_nobody_said_is_not_used(self):
        from app.assistant.planner import known_text

        recent = ["사용자: 프랜차이즈는 어때", "상권 비서: 어떤 업종을 볼까요? 예: 카페, 한식, 미용실, 편의점"]
        known = known_text("연남동", recent, None)
        invented = to_classification("market_data", {"place": "연남동", "industry": "카페", "topics": []}, rule=self.RULE,
                                     question="연남동", use_morph=False, today=date(2026, 11, 8), known=known)
        self.assertEqual(invented["slots"]["industries"], [])
        self.assertIsNone(invented["unresolved_industry"])
        said = known_text("연남동", ["사용자: 카페 차리려고요", "상권 비서: 어느 곳의 상권을 볼까요?"], None)
        kept = to_classification("market_data", {"place": "연남동", "industry": "커피숍", "topics": []}, rule=self.RULE,
                                 question="연남동", use_morph=False, today=date(2026, 11, 8), known=said)
        self.assertEqual([c["code"] for m in kept["slots"]["industries"] for c in m["candidates"]], [COFFEE],
                         "커피숍 and 카페 are the same official industry")

    def test_the_saved_market_echoed_back_is_not_a_new_place(self):
        from app.assistant.flow import AssistantService

        last = {"conditions": {"area_name": "연남동(홍대)"}}
        pieces = [{"text": "연남동", "candidates": [{}]}, {"text": "홍대", "candidates": [{}, {}]}]
        self.assertTrue(AssistantService._echoes_saved_market(pieces, last, None))
        self.assertFalse(AssistantService._echoes_saved_market(pieces[1:], last, None), "'홍대' alone may be 홍대입구역")
        self.assertFalse(AssistantService._echoes_saved_market([{"text": "강남역", "candidates": [{}]}], last, None))

    def test_a_verdict_in_a_data_answer_is_dropped_and_an_opinion_needs_numbers(self):
        live = "연남동(홍대)보다 강남역이 나아요. [F11]\n강남역 매출은 13,638,954,166원이에요. [F11]"
        self.assertEqual(templates.model_body(live, [PLACES], show_conditions=False),
                         "강남역 매출은 13,638,954,166원이에요. [F11]")
        bare = "강남역을 더 추천해요. [F11]\n강남역이 모든 기준에서 앞서요. [F11]"
        self.assertIn({"type": "opinion_without_numbers"}, check_answer(bare, [PLACES], opinion=True)["problems"])

    def test_the_area_question_is_not_repeated_word_for_word(self):
        options = {"candidates": [{"area_code": "1", "name": "연남동(홍대)", "relation": "neighborhood"}]}
        self.assertNotEqual(templates.choose_area(options, None)["text"],
                            templates.choose_area(options, None, repeated=True)["text"])


class WriterQuestionTests(unittest.TestCase):
    def test_the_model_is_asked_what_to_judge(self):
        markets = _two_markets()
        asked = opinions.writer_question(markets, "커피-음료", "너의 생각이 궁금해서 그런 거야")
        self.assertTrue(asked.startswith("가나역과 다라동 가운데 커피-음료 창업에 어디가 더 나을지"), asked)
        self.assertIn("(사용자가 한 말: 너의 생각이 궁금해서 그런 거야)", asked)
        self.assertTrue(opinions.writer_question(markets[:1], "커피-음료", "").startswith("가나역에서 커피-음료 창업을"))

    def test_the_fixed_answer_says_which_time_is_larger_first(self):
        line = templates.focus_line(TIME, "점심·저녁 중 언제 잘 팔려?")
        self.assertTrue(line.startswith("저녁(17~21시)이 점심(11~14시)보다 매출이 커요. [F4]\n"), line)
        self.assertEqual(comparison_problems(line, [TIME]), [])


class OneSidedComparisonTests(unittest.TestCase):
    def test_one_named_market_against_the_other(self):
        extra = [{"label": label, "value": value, "unit": "개", "role": role, "market": market}
                 for label, base, other in (("일반 점포", 181, 117), ("프랜차이즈 점포", 25, 79))
                 for role, market, value in (("base", "연남동(홍대)", base), ("comparison", "강남역", other))]
        cards = [{**PLACES, "values": PLACES["values"] + extra}]
        live = "강남역의 점포 수가 연남동보다 조금 적지만, 일반 점포는 오히려 연남동이 훨씬 적고, 프랜차이즈 점포는 강남역이 압도적으로 많아요. [F11]"
        self.assertEqual(kinds(live, cards), ["wrong_comparison"])
        self.assertEqual(kinds("일반 점포는 연남동이 더 많고, 프랜차이즈 점포는 강남역이 압도적으로 많아요. [F11]", cards), [])

    def test_vowel_stem_endings_become_conversational(self):
        from app.assistant.korean import soften

        self.assertEqual(soften("강남역 매출이 큽니다. 더 나아 보입니다."), "강남역 매출이 커요. 더 나아 보여요.")


class IndustryWordTests(unittest.TestCase):
    def test_an_industry_the_cards_are_not_about_is_rejected(self):
        cafe = [{**PLACES, "text": "연남동(홍대)과 강남역의 커피-음료 비교입니다."}]
        live = "강남역 매출이 13,638,954,166원으로 커요. [F11]\n강남역에서 한식을 파는 게 좋아 보여요. [F11]"
        self.assertIn({"type": "industry_not_on_card", "detail": "한식"}, check_answer(live, cafe)["problems"])
        self.assertTrue(check_answer("강남역 카페 매출이 13,638,954,166원으로 커요. [F11]", cafe)["ok"])
        dropped = templates.model_body("연남동보다 강남역이 더 장사가 잘 돼요. [F11]\n강남역 매출은 13,638,954,166원이에요. [F11]",
                                       cafe, show_conditions=False)
        self.assertEqual(dropped, "강남역 매출은 13,638,954,166원이에요. [F11]")
