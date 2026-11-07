"""Ranking answers, complaint/unknown replies and the B1~B6 page button.

Synthetic markets and sales rows only: no raw statistics, no model, no Maps.
"""
import os
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.assistant.answer_check import check_answer
from app.assistant.ranking import Exclusion, RankingRequest, rank_sales
from tests.test_assistant_flow import _Env, intake_api

COFFEE, FASTFOOD, KOREAN, WESTERN = "CS100010", "CS100006", "CS100001", "CS100004"


def _area(code, name, district_code, district_name, neighborhood_code, neighborhood_name, status="code_name_match"):
    return {"area_code": code, "name": name, "type": "골목상권", "district_code": district_code,
            "district_name": district_name, "neighborhood_code": neighborhood_code,
            "neighborhood_name": neighborhood_name, "boundary_identity_status": status}


class FakeRankingSource:
    """Six markets; '1111111' is also the fake catalogue's candidate, so its button can be opened."""

    def __init__(self):
        self.fail = False
        self.read = []
        self._areas = {area["area_code"]: area for area in (
            _area("3000001", "강남역", "11680", "강남구", "11680640", "역삼1동"),
            _area("3000002", "신논현역", "11680", "강남구", "11680510", "논현1동"),
            _area("1111111", "홍대입구역(홍대)", "11440", "마포구", "11440660", "서교동"),
            _area("3000004", "명동 관광특구", "11140", "중구", "11140550", "명동"),
            _area("3000005", "성수카페거리", "11200", "성동구", "11200690", "성수2가3동"),
            _area("3000006", "망원시장", "11440", "마포구", "11440690", "망원1동", status="name_mismatch"))}

    def periods(self):
        return ["20261", "20262"]

    def areas(self):
        return self._areas

    def sales(self, period):
        if self.fail:
            raise ValueError("synthetic source failure")
        self.read.append(period)
        values = {"3000001": 9000, "3000002": 8000, "1111111": 7000, "3000004": 6000, "3000005": 5000, "3000006": 1000}
        rows = {(code, COFFEE): {"THSMON_SELNG_AMT": value, "SVC_INDUTY_CD_NM": "커피-음료"} for code, value in values.items()}
        rows[("1111111", FASTFOOD)] = {"THSMON_SELNG_AMT": 500, "SVC_INDUTY_CD_NM": "패스트푸드점"}
        rows[("1111111", KOREAN)] = {"THSMON_SELNG_AMT": 12000, "SVC_INDUTY_CD_NM": "한식음식점"}
        rows[("1111111", WESTERN)] = {"THSMON_SELNG_AMT": 3000, "SVC_INDUTY_CD_NM": "양식음식점"}
        rows[("3000004", "CS100002")] = {"THSMON_SELNG_AMT": 4000, "SVC_INDUTY_CD_NM": "중식음식점"}
        rows[("9999999", COFFEE)] = {"THSMON_SELNG_AMT": 99999, "SVC_INDUTY_CD_NM": "커피-음료"}  # not in the catalogue
        rows[("3000004", FASTFOOD)] = {"THSMON_SELNG_AMT": "12.5", "SVC_INDUTY_CD_NM": "패스트푸드점"}  # not an integer
        return rows, "b2_synthetic_rank"

    def area_sales(self, period, area_code):
        rows, version = self.sales(period)
        return {industry: row for (area, industry), row in rows.items() if area == area_code}, version

    def area_stores(self, period, area_code):
        # 양식 has no store row, so its line shows sales only.
        return {KOREAN: 30, COFFEE: 25, FASTFOOD: 3} if area_code == "1111111" else {}


class RankUnitTests(unittest.TestCase):
    def test_sorts_filters_and_skips_unusable_rows(self):
        source = FakeRankingSource()
        result = rank_sales(source, RankingRequest(industry_code=COFFEE))
        self.assertEqual([item["area_code"] for item in result["items"]], ["3000001", "3000002", "1111111", "3000004", "3000005"])
        self.assertEqual((result["period"], result["compared_count"], result["scope_label"]), ("20262", 6, "서울 전체"))
        fast = rank_sales(source, RankingRequest(industry_code=FASTFOOD))
        self.assertEqual([item["value"] for item in fast["items"]], [500], "a non-integer amount is not ranked")
        mapo = rank_sales(source, RankingRequest(industry_code=COFFEE, district_codes=frozenset({"11440"}),
                                                 district_labels=("마포구",)))
        self.assertEqual([item["name"] for item in mapo["items"]], ["홍대입구역(홍대)", "망원시장"])
        self.assertFalse(mapo["items"][1]["selectable"])
        self.assertEqual(rank_sales(source, RankingRequest(industry_code=COFFEE, period="20251"))["status"], "period_unavailable")

    def test_exclusion_from_mentions(self):
        gangnam = Exclusion.from_mentions([{"text": "강남", "candidates": [
            {"kind": "station", "name": "강남역", "label": "강남역", "code": None, "district_code": "11680"},
            {"kind": "district", "name": "강남구", "label": "강남구", "code": "11680", "district_code": "11680"}]}])
        self.assertEqual(gangnam.describe(), "강남구 전체와 이름에 '강남'이 들어간 상권은")
        self.assertTrue(gangnam.matches({"district_code": "11680", "name": "신논현역"}))
        self.assertTrue(gangnam.matches({"district_code": "11650", "name": "강남대로 상권"}))
        self.assertFalse(gangnam.matches({"district_code": "11440", "name": "홍대입구역"}))
        self.assertEqual(Exclusion.from_dict(gangnam.to_dict()), gangnam)


class _RankingEnv(_Env):
    """The synthetic source in place of SeoulSalesSource, plus chat helpers."""

    def setUp(self):
        super().setUp()
        self.source = FakeRankingSource()
        self.stack.enter_context(patch("app.assistant.flow.SeoulSalesSource", return_value=self.source))

    def say(self, text):
        self.counter += 1
        response = self.client.post("/api/assistant/messages", json={"text": text, "client_message_id": f"r{self.counter}"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def pick(self, action):
        response = self.client.post("/api/assistant/actions", json=action["payload"])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


class RankingFlowTests(_RankingEnv, unittest.TestCase):
    def test_screenshot_question_ranks_without_the_excluded_place(self):
        data = self.say("강남 말고는 서울에 카페 매출액 높은 곳 추천해줘")
        self.assertEqual(data["reply"]["kind"], "ranking")
        text = data["reply"]["text"]
        self.assertIn("- 1위 홍대입구역(홍대) (마포구): 7,000원 [F1]", text)
        self.assertNotIn("9,000원", text)
        self.assertNotIn("8,000원", text)
        self.assertIn("말씀하신 대로 강남구 전체와 이름에 '강남'이 들어간 상권은 뺐어요.", text)
        self.assertIn("자료가 있는 4곳을 비교했어요. [F1]", text)
        self.assertIn("매출만으로 정할 수는 없지만", text)
        self.assertEqual([card["topic"] for card in data["cards"]], ["ranking"])
        self.assertTrue(check_answer(text, data["cards"])["ok"], check_answer(text, data["cards"]))
        # Markets whose boundary does not match cannot be opened, so they get no button.
        self.assertEqual([a["label"] for a in data["reply"]["actions"]],
                         ["1위 홍대입구역(홍대) 자세히", "2위 명동 관광특구 자세히", "3위 성수카페거리 자세히"])
        self.assertIsNone(self.client.get("/api/onboarding/profile").json()["profile"], "a ranking saves no condition")

    def test_ranking_button_opens_that_market_with_the_ranked_industry(self):
        data = self.say("서울에서 카페 매출 제일 높은 상권 어디야?")
        opened = self.pick(data["reply"]["actions"][2])  # 3위 홍대입구역(홍대) = fake candidate 1111111
        self.assertEqual(opened["reply"]["kind"], "data_answer")
        self.assertEqual((opened["conditions"]["area_code"], opened["conditions"]["industry_name"]), ("1111111", "커피-음료"))
        self.assertEqual(opened["conditions"]["period"], "20262")
        self.assertEqual(self.client.get("/api/onboarding/context").json()["location"]["neighborhood_name"], "서교동")

    def test_saved_industry_followups_and_scope(self):
        self.say("합정역 카페 매출 어때?")
        data = self.say("서울에서 매출 높은 곳 추천해줘")
        self.assertEqual(data["reply"]["kind"], "ranking")
        self.assertIn("커피-음료 업종", data["reply"]["text"])
        self.assertEqual(data["conditions"]["area_code"], "1111111", "the saved conditions stay as they were")
        fast = self.say("그럼 패스트푸드는?")
        self.assertEqual(fast["reply"]["kind"], "ranking")
        self.assertIn("- 1위 홍대입구역(홍대) (마포구): 500원 [F1]", fast["reply"]["text"])
        mapo = self.say("마포구에서 카페 어디가 제일 괜찮을까요")
        self.assertIn("마포구 상권 가운데", mapo["reply"]["text"])
        self.assertNotIn("명동", mapo["reply"]["text"])
        detail = self.say("그럼 홍대는?")
        self.assertNotEqual(detail["reply"]["kind"], "ranking", "a named place after a ranking opens that place")

    def test_missing_industry_is_asked_then_ranked(self):
        self.assertEqual(self.say("매출 높은 곳 알려줘")["reply"]["kind"], "need_industry")
        data = self.say("카페")
        self.assertEqual(data["reply"]["kind"], "ranking")
        self.assertIn("1위 강남역 (강남구): 9,000원", data["reply"]["text"])

    def test_source_failure_is_reported_not_guessed(self):
        self.source.fail = True
        data = self.say("서울에서 카페 매출 높은 곳")
        self.assertEqual(data["reply"]["kind"], "data_unavailable")
        self.assertEqual(data["cards"], [])

    def test_replies_that_do_not_read_the_state_leave_the_conditions_bar_alone(self):
        self.assertIn("conditions", self.say("합정역 카페 매출 어때?"))
        for text in ("ㅁㄴㅇㄹ", "바보", "오늘 날씨 어때?"):
            self.assertNotIn("conditions", self.say(text), text)
        self.assertEqual(self.client.get("/api/assistant/conversation").json()["conditions"]["industry_name"], "커피-음료")

    def test_complaints_and_repeated_unknown_messages(self):
        sorry = self.say("바보")
        self.assertEqual(sorry["reply"]["kind"], "smalltalk")
        self.assertIn("죄송해요", sorry["reply"]["text"])
        self.assertTrue(sorry["reply"]["suggestions"], "example questions come as buttons")
        first = self.say("ㅁㄴㅇㄹ")["reply"]
        second = self.say("ㅋㅋㅋ ㄹㅇ")["reply"]
        self.assertTrue(first["text"].startswith("음, 어떤 걸 원하시는지"), first["text"])
        self.assertNotIn("답하기 어려워요", first["text"])
        self.assertTrue(second["text"].startswith("아직 제가 잘 못 알아들었어요."))
        self.assertTrue(first["suggestions"])
        self.assertEqual(self.say("오늘 날씨 어때?")["reply"]["kind"], "out_of_scope")

    def test_changing_only_the_industry_keeps_the_chosen_market(self):
        module = sys.modules["app.onboarding_analysis_catalog"]
        base_options, base_validate = module.get_analysis_options, module.validate_analysis_selection

        def options(location, industry_code):
            result = base_options(location, industry_code)
            first = {**result["candidates"][0], "relation": "neighborhood"}
            second = {**first, "area_code": "5555555", "name": "합성 상권 5555555"}
            return {**result, "candidates": [second, first], "candidate_count": 2}

        def validate(location, industry_code, area_code, period, expected_catalog_version=None):
            chosen = base_validate(location, industry_code, "1111111", period, expected_catalog_version)
            return {**chosen, "area_code": area_code, "area_name": "합성 상권 " + area_code}

        self.stack.enter_context(patch.object(module, "get_analysis_options", options))
        self.stack.enter_context(patch.object(module, "validate_analysis_selection", validate))
        first = self.say("합정역 카페 매출 어때?")
        self.assertEqual(first["reply"]["kind"], "choose_area")
        opened = self.pick(first["reply"]["actions"][1])
        self.assertEqual(opened["conditions"]["area_code"], "1111111")
        switched = self.say("그럼 패스트푸드는?")
        self.assertEqual(switched["reply"]["kind"], "data_answer", switched["reply"]["text"])
        self.assertEqual((switched["conditions"]["area_code"], switched["conditions"]["industry_code"]), ("1111111", FASTFOOD))

    def test_one_place_choice_is_asked_as_a_yes_question(self):
        data = self.say("강남 카페 매출")
        self.assertEqual(data["reply"]["kind"], "choose_location")
        self.assertEqual(len(data["reply"]["actions"]), 1)
        self.assertTrue(data["reply"]["text"].startswith("'강남'은 강남역 (강남구)로 볼까요?"), data["reply"]["text"])


class IndustryRankTests(_RankingEnv, unittest.TestCase):
    """'추천해줄만한 업종 3가지' inside one market."""

    def test_screenshot_question_lists_industries_of_the_saved_market(self):
        self.say("합정역 카페 매출 어때?")
        data = self.say("추천해줄만한 업종 3가지 말해줘")
        self.assertEqual(data["reply"]["kind"], "industry_rank")
        text = data["reply"]["text"]
        self.assertIn("- 1위 한식음식점: 매출 12,000원, 점포 30개 [F2]", text)
        self.assertIn("- 2위 커피-음료: 매출 7,000원, 점포 25개 [F2]", text)
        self.assertIn("- 3위 양식음식점: 매출 3,000원 [F2]", text, "no store row: sales only")
        self.assertNotIn("패스트푸드", text)
        self.assertIn("매출만으로 정할 수는 없지만", text)
        self.assertTrue(check_answer(text, data["cards"])["ok"], check_answer(text, data["cards"]))
        self.assertEqual([a["payload"] for a in data["reply"]["actions"]][0], {"type": "industry", "industry_code": KOREAN})
        detail = self.pick(data["reply"]["actions"][0])
        self.assertEqual(detail["reply"]["kind"], "data_answer")
        self.assertEqual((detail["conditions"]["area_code"], detail["conditions"]["industry_code"]), ("1111111", KOREAN))

    def test_without_conditions_the_market_is_asked_then_listed(self):
        self.assertEqual(self.say("여기서 뭐 하면 장사 잘 될까?")["reply"]["kind"], "need_location")
        data = self.say("홍대")
        self.assertEqual(data["reply"]["kind"], "industry_rank", data["reply"]["text"])
        self.assertIn("홍대입구역(홍대) 상권", data["reply"]["text"])
        payload = data["reply"]["actions"][1]["payload"]
        self.assertEqual((payload["type"], payload["area_code"], payload["industry_code"]), ("location", "1111111", COFFEE))
        opened = self.pick(data["reply"]["actions"][1])
        self.assertEqual((opened["conditions"]["area_code"], opened["conditions"]["industry_code"]), ("1111111", COFFEE))

    def test_excluded_industry_and_count(self):
        self.say("합정역 카페 매출 어때?")
        data = self.say("카페 말고 다른 업종 두 가지만 추천해줘")
        text = data["reply"]["text"]
        self.assertIn("말씀하신 대로 커피-음료는 뺐어요.", text)
        self.assertEqual(text.count("위 "), 2)
        self.assertEqual(self.client.get("/api/onboarding/context").json()["industry"]["name"], "커피-음료",
                         "an excluded industry does not change the saved condition")

    def test_new_question_drops_old_exclusions_and_followups_with_a_topic_leave_the_list(self):
        self.say("합정역 카페 매출 어때?")
        self.say("카페 말고 다른 업종 추천해줘")
        fresh = self.say("여기서 뭐 하면 장사 잘 될까?")
        self.assertNotIn("뺐어요", fresh["reply"]["text"])
        self.assertIn("2위 커피-음료", fresh["reply"]["text"])
        compared = self.say("작년이랑 비교하면?")
        self.assertEqual(compared["reply"]["kind"], "data_answer")
        self.assertIn("change_yoy", [card["topic"] for card in compared["cards"]])

    def test_fixed_answer_names_the_values_the_question_asked_about(self):
        self.say("합정역 카페 매출 어때?")
        times = self.say("점심과 저녁 중 언제 잘 팔려?")["reply"]["text"]
        self.assertTrue(times.startswith("점심(11~14시)은 300원(30.00%)이고, 저녁(17~21시)은 300원(30.00%)이에요. [F"), times)
        days = self.say("주말이랑 평일 중 언제 더 팔려?")["reply"]["text"]
        self.assertIn("주말은 토 200원(20.00%), 일 200원(20.00%)이고, 평일은 월 100원(10.00%)", days)

    def test_short_requests_follow_the_conversation_without_the_ai(self):
        # User feedback 2026-11-08: '추천해줘' after a 창업 question answered 'I cannot answer that'.
        self.say("합정역 카페 매출 어때?")
        follow = self.say("추천해줘")
        self.assertEqual(follow["reply"]["kind"], "industry_rank", follow["reply"]["text"])
        self.say("서울에서 카페 매출 높은 곳 알려줘")
        again = self.say("추천해줘")
        self.assertEqual(again["reply"]["kind"], "ranking")

    def test_warnings_and_next_questions_travel_beside_the_message(self):
        data = self.say("합정역 카페 매출 어때?")
        text = data["reply"]["text"]
        for removed in ("참고:", "다음으로", "\n- ", "입니다."):
            self.assertNotIn(removed, text)
        self.assertTrue(data["reply"]["notes"])
        self.assertIn("주말 매출은?", data["reply"]["suggestions"])
        ranked = self.say("서울에서 카페 매출 높은 곳 알려줘")["reply"]
        self.assertNotIn("참고:", ranked["text"])
        self.assertTrue(any("큰 상권일수록" in note for note in ranked["notes"]))

    def test_model_report_endings_are_softened(self):
        from app.assistant import templates

        cards = [{"id": "F2", "topic": "sales_total", "text": "분기 추정매출은 1,000원입니다.",
                  "values": [{"label": "분기 추정매출", "value": 1000, "unit": "원"}]}]
        body = templates.model_body("합정역 카페의 추정 매출은 1,000원입니다. [F2]\n점포 변화는 없었습니다. [F2]", cards)
        self.assertEqual(body, "합정역 카페의 추정 매출은 1,000원이에요. [F2]\n점포 변화는 없었어요. [F2]")

    def test_conditions_sentence_is_not_repeated_for_the_same_market(self):
        first = self.say("합정역 카페 매출 어때?")
        self.assertTrue(first["reply"]["text"].startswith("합성 상권 1111111 상권의 커피-음료 업종을"))
        again = self.say("주말은?")
        self.assertNotIn("상권의 커피-음료 업종을", again["reply"]["text"])
        self.assertEqual(again["cards"][0]["topic"], "conditions", "the card itself is still shown")


class PromptValuesTests(unittest.TestCase):
    def test_model_sees_every_value_to_answer_the_question_itself(self):
        from app.assistant import templates
        from app.assistant.clova_client import build_messages

        conditions = {"id": "F1", "topic": "conditions", "text": "분석 조건은 합성 상권입니다.", "values": [{"label": "상권", "value": "합성"}]}
        times = {"id": "F2", "topic": "sales_time", "text": "시간대별 매출에서 가장 높은 항목은 17~21시입니다.",
                 "values": [{"label": "11~14시", "value": 300, "unit": "원", "share_percent": 30.0},
                            {"label": "17~21시", "value": 400, "unit": "원", "share_percent": 40.0}]}
        user = build_messages([conditions, times], {"text": "점심과 저녁 중 언제 잘 팔려?"})[-1]["content"]
        self.assertIn("    값: 11~14시 300원, 비중 30.00%; 17~21시 400원, 비중 40.00%", user)
        self.assertNotIn("값: 상권", user)
        body = templates.model_body("저녁(17~21시)이 점심(11~14시)보다 커요. 400원이에요. [F2]", [conditions, times],
                                    show_conditions=False)
        self.assertFalse(body.startswith("분석 조건"))
        self.assertTrue(check_answer(body, [conditions, times])["ok"], check_answer(body, [conditions, times]))


class EntryButtonTests(_Env, unittest.TestCase):
    def test_onboarding_page_links_to_the_chat_only_when_enabled(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn('href="/assistant"', page.text)
        self.assertIn("/assistant-assets/entry.css", page.text)
        self.assertEqual(page.text.count("assistant-entry\""), 1)
        self.assertEqual(self.client.get("/assistant-assets/entry.css").status_code, 200)
        with patch.dict(os.environ, {"ASSISTANT_ENABLED": ""}):
            plain = TestClient(intake_api.create_app(onboarding_store=self.store))
            self.assertNotIn("/assistant", plain.get("/").text)


if __name__ == "__main__":
    unittest.main()
