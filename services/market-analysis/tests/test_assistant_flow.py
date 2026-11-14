"""Assistant API end to end with a synthetic catalogue and synthetic source rows.

B2~B4 results are produced by PR #12's own row interpreters from synthetic
rows, so fact cards are tested against the real result shapes. No .env, no
raw statistics, no model, no external Maps request.
"""
from contextlib import ExitStack
from datetime import date
import os
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

# Import the analysis modules before the catalogue module is replaced below.
import app.onboarding_changes  # noqa: F401
import app.onboarding_comparison  # noqa: F401
import app.onboarding_population  # noqa: F401
import app.onboarding_sales  # noqa: F401
import app.onboarding_stores  # noqa: F401
from app.assistant.answer_check import check_answer
from app.assistant.facts import cards_from_snapshot
from app.data_repository import DISTRIBUTION_FIELDS
from app.onboarding import OnboardingStore
from app.onboarding_population import analyze_population_row
from app.onboarding_sales import analyze_sales_row
from app.onboarding_stores import analyze_stores_row
from tests.test_onboarding import Clock, FakeMaps, intake_api
from tests.test_onboarding_analysis import FakeAnalysisCatalogue


def sales_row():
    row = {"THSMON_SELNG_AMT": 1000}
    for (_, field), value in zip(DISTRIBUTION_FIELDS["sales_weekday"], (100, 110, 120, 130, 140, 200, 200)):
        row[field] = value
    for (_, field), value in zip(DISTRIBUTION_FIELDS["sales_time"], (0, 100, 300, 200, 300, 100)):
        row[field] = value
    for (_, field), value in zip(DISTRIBUTION_FIELDS["sales_age"], (50, 200, 300, 200, 100, 50)):
        row[field] = value
    return row


def population_row():
    row = {"TOT_FLPOP_CO": 6000}
    for (_, field), value in zip(DISTRIBUTION_FIELDS["population_time"], (500, 1000, 1500, 1000, 1500, 500)):
        row[field] = value
    for field, value in zip(("AGRDE_10_FLPOP_CO", "AGRDE_20_FLPOP_CO", "AGRDE_30_FLPOP_CO", "AGRDE_40_FLPOP_CO",
                             "AGRDE_50_FLPOP_CO", "AGRDE_60_ABOVE_FLPOP_CO"), (500, 2000, 1500, 1000, 500, 500)):
        row[field] = value
    return row


STORES_ROW = {"SIMILR_INDUTY_STOR_CO": 20, "STOR_CO": 15, "FRC_STOR_CO": 5, "OPBIZ_STOR_CO": 2, "CLSBIZ_STOR_CO": 1}


def metric(key, label, unit, current, previous, left="current", right="previous"):
    delta = current - previous
    return {"key": key, "label": label, "unit": unit, left: {"value": current, "status": "available"},
            right: {"value": previous, "status": "available"}, "delta": delta,
            "percent": round(delta * 100 / previous, 2) if previous else None,
            "percent_status": "available", "status": "available", "warnings": []}


class Analyses:
    """Fake B2~B6 builders that count calls."""

    def __init__(self):
        self.calls = []
        self.sales_error = False

    def sales(self, selection, profile, **_):
        self.calls.append("sales")
        if self.sales_error:
            raise app.onboarding_sales.SalesDataError("synthetic failure")
        result = analyze_sales_row(sales_row(), selection, profile["industry"]["name"])
        return {**result, "data_version": "b2_synthetic", "source": {"title": "합성 추정매출", "url": "https://example.test/s"}}

    def stores(self, selection, profile, **_):
        self.calls.append("stores")
        return {**analyze_stores_row(STORES_ROW, selection, profile["industry"]["name"]), "data_version": "b3_synthetic"}

    def population(self, selection, profile, **_):
        self.calls.append("population")
        return {**analyze_population_row(population_row(), selection, profile["industry"]["name"]), "data_version": "b4_synthetic"}

    def changes(self, selection, profile, comparison):
        self.calls.append("changes_" + comparison)
        previous = "2025년 2분기" if comparison == "yoy" else "2026년 1분기"
        return {"status": "complete", "comparison": comparison,
                "previous_period": {"code": "x", "label": previous},
                "metrics": [metric("sales", "추정매출", "원", 1000, 800), metric("stores_total", "전체 점포", "개", 20, 18),
                            metric("floating_population", "지역 유동인구 원천 총지표", "명", 6000, 6000)],
                "warnings": ["변화율의 분모는 이전 기간 값입니다."], "summary": []}

    def comparison_options(self, selection, profile):
        self.calls.append("comparison_options")
        return {"status": "ready", "areas": [
            {"area_code": "3333333", "name": "합성 비교 상권", "district_code": "11440", "district_name": "마포구", "selectable": True},
            {"area_code": "4444444", "name": "막힌 상권", "district_code": "11440", "district_name": "마포구", "selectable": False}]}

    def comparison(self, selection, profile, area_code):
        self.calls.append("comparison")
        return {"status": "complete", "base_area": {"name": selection["area_name"]},
                "comparison_area": {"name": "합성 비교 상권"},
                "metrics": [metric("sales", "추정매출", "원", 1000, 1500, "base", "comparison")], "warnings": []}


class _Env:
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"ASSISTANT_ENABLED": "1", "ASSISTANT_MORPH": "off"}, clear=True))
        self.store = OnboardingStore(":memory:", clock=Clock())
        self.stack.callback(self.store.close)
        self.maps = FakeMaps()
        self.stack.enter_context(patch.object(intake_api, "load_settings", return_value=None))
        self.stack.enter_context(patch.object(intake_api, "MapsClient", return_value=self.maps))
        self.catalogue = FakeAnalysisCatalogue()
        module = ModuleType("app.onboarding_analysis_catalog")
        module.get_analysis_options = self.catalogue.options
        module.validate_analysis_selection = self.catalogue.validate
        self.stack.enter_context(patch.dict(sys.modules, {module.__name__: module}))
        self.analyses = Analyses()
        for target, fake in (("app.onboarding_sales.build_sales_analysis", self.analyses.sales),
                             ("app.onboarding_stores.build_stores_analysis", self.analyses.stores),
                             ("app.onboarding_population.build_population_analysis", self.analyses.population),
                             ("app.onboarding_changes.build_changes_analysis", self.analyses.changes),
                             ("app.onboarding_comparison.get_comparison_options", self.analyses.comparison_options),
                             ("app.onboarding_comparison.build_comparison_analysis", self.analyses.comparison)):
            self.stack.enter_context(patch(target, fake))
        self.app = intake_api.create_app(onboarding_store=self.store)
        self.client = self.stack.enter_context(TestClient(self.app))
        self.counter = 0

    def tearDown(self):
        self.assertEqual(self.maps.calls, [])


class AssistantFlowTests(_Env, unittest.TestCase):
    def say(self, text, **extra):
        self.counter += 1
        response = self.client.post("/api/assistant/messages", json={"text": text, "client_message_id": f"m{self.counter}", **extra})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def pick(self, action):
        response = self.client.post("/api/assistant/actions", json=action["payload"])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def assert_checked(self, data):
        self.assertTrue(check_answer(data["reply"]["text"], data["cards"])["ok"],
                        check_answer(data["reply"]["text"], data["cards"]))

    def test_one_message_sets_conditions_and_answers_from_cards(self):
        data = self.say("합정역 카페 매출 어때?")
        self.assertEqual(data["reply"]["kind"], "data_answer")
        self.assertEqual([card["topic"] for card in data["cards"]], ["conditions", "sales_total"])
        self.assertIn("1,000원", data["reply"]["text"])
        self.assertIn("[F2]", data["reply"]["text"])
        self.assertEqual(data["conditions"]["industry_name"], "커피-음료")
        self.assertFalse(data["model_used"])
        self.assert_checked(data)
        # The B1 screen sees the same saved profile and selection.
        context = self.client.get("/api/onboarding/context").json()
        self.assertEqual(context["location"]["name"], "합정역")
        self.assertTrue(context["conditions_confirmed"])

    def test_missing_location_and_industry_are_asked_and_remembered(self):
        self.assertEqual(self.say("매출 어때?")["reply"]["kind"], "need_location")
        self.assertEqual(self.say("합정역")["reply"]["kind"], "need_industry")
        data = self.say("카페")
        self.assertEqual(data["reply"]["kind"], "data_answer")
        self.assertIn("sales_total", data["topics"])

    def test_ambiguous_place_is_offered_as_choices(self):
        data = self.say("망원동 카페 매출")
        self.assertEqual(data["reply"]["kind"], "choose_location")
        labels = [action["label"] for action in data["reply"]["actions"]]
        self.assertEqual(labels, ["망원1동", "망원2동"])
        chosen = self.pick(data["reply"]["actions"][1])
        self.assertEqual(chosen["reply"]["kind"], "data_answer")
        self.assertFalse(chosen["reply"]["text"].startswith("이번에는"), "the first condition is not a change")
        self.assertEqual(self.client.get("/api/onboarding/context").json()["location"]["neighborhood_name"], "망원2동")
        moved = self.pick(self.say("망원동으로 바꿔줘")["reply"]["actions"][0])
        # Said in context, not as a bare '조건을 바꿨어요' (user feedback 2026-11-08).
        self.assertTrue(moved["reply"]["text"].startswith("이번에는 합성 상권 1111111 상권의 커피-음료 업종을"))
        self.assertNotIn("조건을 바꿨어요", moved["reply"]["text"])
        self.assertEqual(self.client.get("/api/onboarding/context").json()["location"]["neighborhood_name"], "망원1동")

    def test_followup_uses_cached_snapshot(self):
        self.say("합정역 카페 매출 어때?")
        calls = len(self.analyses.calls)
        data = self.say("주말은?")
        self.assertEqual([card["topic"] for card in data["cards"]], ["conditions", "sales_weekday"])
        self.assertIn("토, 일", data["reply"]["text"])
        self.assertEqual(len(self.analyses.calls), calls, "same selection must not recompute")
        self.assert_checked(data)

    def test_changes_population_and_stores_cards(self):
        self.say("합정역 카페 매출 어때?")
        data = self.say("작년이랑 비교하면 손님은 줄었어?")
        topics = [card["topic"] for card in data["cards"]]
        self.assertIn("change_yoy", topics)
        self.assertIn("population", topics)
        self.assertIn("200원 증가(+25.00%)", data["reply"]["text"])
        self.assert_checked(data)
        stores = self.say("경쟁 가게는 몇 개야?")
        self.assertIn("전체 점포는 20개", stores["reply"]["text"])
        self.assertIn("프랜차이즈 비중 25.00%", stores["reply"]["text"])
        self.assert_checked(stores)

    def test_period_change_and_unavailable_period(self):
        self.say("합정역 카페 매출 어때?")
        changed = self.say("2026년 1분기로 보여줘")
        self.assertTrue(changed["reply"]["text"].startswith("이번에는 ") and "20261 자료로 볼게요" in changed["reply"]["text"])
        self.assertEqual(changed["conditions"]["period"], "20261")
        missing = self.say("2024년 1분기로 보여줘")
        self.assertEqual(missing["reply"]["kind"], "period_unavailable")
        self.assertEqual(self.client.get("/api/onboarding/context").json()["data_period"], "20261")

    def test_comparison_asks_for_a_market_then_adds_a_card(self):
        self.say("합정역 카페 매출 어때?")
        data = self.say("다른 상권이랑 비교해 줘")
        self.assertEqual(data["reply"]["kind"], "choose_comparison")
        self.assertEqual(len(data["reply"]["actions"]), 1, "unselectable markets are not offered")
        compared = self.pick(data["reply"]["actions"][0])
        self.assertIn("comparison", [card["topic"] for card in compared["cards"]])
        self.assertIn("합성 비교 상권 1,500원", compared["reply"]["text"])
        self.assert_checked(compared)

    def test_other_domains_and_smalltalk_do_not_touch_conditions(self):
        replies = {text: self.say(text)["reply"]["kind"] for text in
                   ("인스타 홍보글 써줘", "리뷰에 불만 글 달렸어 답글 써줘", "임대료는 얼마야?",
                    "우리 가게는 매출이 20% 줄었어요", "안녕하세요", "ㅁㄴㅇㄹ")}
        self.assertEqual(replies, {"인스타 홍보글 써줘": "handoff_marketing", "리뷰에 불만 글 달렸어 답글 써줘": "handoff_customer",
                                   "임대료는 얼마야?": "ask_site_costs", "우리 가게는 매출이 20% 줄었어요": "personal_metric",
                                   "안녕하세요": "smalltalk", "ㅁㄴㅇㄹ": "unknown"})
        self.assertIsNone(self.client.get("/api/onboarding/profile").json()["profile"])
        self.assertEqual(self.analyses.calls, [])

    def test_repeated_message_id_returns_the_same_reply_without_work(self):
        first = self.client.post("/api/assistant/messages", json={"text": "합정역 카페 매출", "client_message_id": "same"}).json()
        calls = len(self.analyses.calls)
        again = self.client.post("/api/assistant/messages", json={"text": "합정역 카페 매출", "client_message_id": "same"}).json()
        self.assertTrue(again["repeated"])
        self.assertEqual(again["reply"], first["reply"])
        self.assertEqual(len(self.analyses.calls), calls)

    def test_one_failing_analysis_is_reported_while_others_answer(self):
        self.analyses.sales_error = True
        data = self.say("합정역 카페 매출이랑 점포 수 알려줘")
        texts = {card["topic"]: card["text"] for card in data["cards"]}
        self.assertIn("불러오지 못했습니다", texts["sales_total"])
        self.assertIn("전체 점포는 20개", texts["stores_count"])

    def test_blocked_markets_are_not_auto_selected(self):
        self.catalogue.blocked = True
        data = self.say("합정역 카페 매출")
        self.assertEqual(data["reply"]["kind"], "data_unavailable")
        self.assertFalse(self.client.get("/api/onboarding/context").json()["conditions_confirmed"])

    def test_conversation_is_listed_and_can_be_cleared(self):
        self.say("합정역 카페 매출")
        listed = self.client.get("/api/assistant/conversation").json()
        self.assertEqual(len(listed["turns"]), 1)
        self.assertEqual(listed["conditions"]["industry_name"], "커피-음료")
        self.assertEqual(self.client.delete("/api/assistant/conversation").json()["removed_turns"], 1)
        self.assertEqual(self.client.get("/api/assistant/conversation").json()["turns"], [])

    def test_sessions_are_isolated(self):
        self.say("합정역 카페 매출")
        other = TestClient(self.app)
        self.assertEqual(other.get("/api/assistant/conversation").json()["turns"], [])
        self.assertIsNone(other.get("/api/onboarding/profile").json()["profile"])

    def test_input_validation(self):
        self.assertEqual(self.client.post("/api/assistant/messages", json={"text": "   "}).status_code, 422)
        self.assertEqual(self.client.post("/api/assistant/messages", json={"text": "a" * 1001}).status_code, 422)
        self.assertEqual(self.client.post("/api/assistant/actions", json={"type": "unknown"}).status_code, 422)
        self.assertEqual(self.client.post("/api/assistant/messages", json={"text": "hi", "user_id": "x"}).status_code, 422)


class WriterTests(_Env, unittest.TestCase):
    """A model writer is only trusted when its text passes answer_check."""

    def run_with(self, writer, text="합정역 카페 매출"):
        from starlette.requests import Request

        from app.assistant.bridge import endpoint_table, request_with_session
        from app.assistant.flow import AssistantService
        from app.assistant.history import AssistantHistory
        from app.onboarding import create_onboarding_router

        table = endpoint_table(create_onboarding_router(self.store))
        service = AssistantService(self.store, AssistantHistory(self.store), table,
                                   writer=writer, use_morph=False, today=date(2026, 11, 7))
        owner, token = self.store.session(None)
        scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}
        return service.handle_message(owner, request_with_session(Request(scope), token), text, None)

    def test_valid_model_text_is_published(self):
        good = self.run_with(lambda cards, cls: f"{cards[1]['text']} [{cards[1]['id']}]")
        self.assertTrue(good["model_used"])

    def test_wrong_number_or_failure_falls_back_to_the_fixed_answer(self):
        wrong = self.run_with(lambda cards, cls: "매출은 9,999원입니다. [F2]")
        self.assertFalse(wrong["model_used"])
        self.assertIn("1,000원", wrong["reply"]["text"])

        def broken(cards, cls):
            raise RuntimeError("model down")

        failed = self.run_with(broken)
        self.assertFalse(failed["model_used"])
        self.assertIn("1,000원", failed["reply"]["text"])


class AnswerCheckTests(unittest.TestCase):
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


class FactCardTests(unittest.TestCase):
    def test_cards_are_numbered_in_topic_order_and_keep_warnings(self):
        selection = {"area_code": "1111111", "area_name": "합성 상권", "industry_code": "CS100010", "period": "20262",
                     "period_label": "2026년 2분기", "catalog_version": "v", "boundary": {"publication_date": "2023-10-23"}}
        profile = {"industry": {"code": "CS100010", "name": "커피-음료"}, "location": {}}
        snapshot = {"selection": selection, "profile": profile, "results": {
            "sales": analyze_sales_row(sales_row(), selection, "커피-음료"),
            "stores": analyze_stores_row(STORES_ROW, selection, "커피-음료"),
            "population": analyze_population_row(population_row(), selection, "커피-음료")}}
        cards = cards_from_snapshot(snapshot)
        self.assertEqual([c["id"] for c in cards], [f"F{i}" for i in range(1, len(cards) + 1)])
        self.assertEqual(cards[0]["topic"], "conditions")
        by_topic = {c["topic"]: c for c in cards}
        self.assertIn("개별 가게", " ".join(by_topic["sales_total"]["warnings"]))
        self.assertIn("30대", by_topic["sales_age"]["text"])  # 300 of the age-classified 900
        self.assertIn("90.00%", by_topic["sales_age"]["text"])  # 900 of 1,000 is age-classified
        empty = cards_from_snapshot({**snapshot, "results": {"sales": analyze_sales_row(None, selection, "커피-음료")}})
        self.assertEqual({c["topic"]: c["status"] for c in empty}["sales_total"], "no_data")


if __name__ == "__main__":
    unittest.main()
