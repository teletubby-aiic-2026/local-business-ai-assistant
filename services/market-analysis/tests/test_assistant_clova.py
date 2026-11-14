"""CLOVA Studio writer with a mock transport. No network, no real key, no model call."""
from datetime import date, datetime
import json
import logging
import os
import secrets
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.assistant import templates
from app.assistant.answer_check import check_answer
from app.assistant.clova_client import (ClovaWriter, ModelError, SYSTEM_PROMPT, build_request,
                                        writer_from_env)
from app.onboarding import OnboardingStore
from tests.test_assistant_flow import _Env
from tests.test_onboarding import intake_api

# Generated per run: no key-shaped value is ever committed, not even a fake one.
KEY = "nv-" + secrets.token_hex(16)
CARDS = [{"id": "F1", "topic": "conditions", "text": "분석 조건은 합성 상권, 커피-음료 업종, 2026년 2분기 자료입니다.",
          "values": [{"label": "상권", "value": "합성"}, {"label": "업종", "value": "커피-음료"},
                     {"label": "기간", "value": "2026년 2분기"}],
          "warnings": ["경계 경고"]},
         {"id": "F2", "topic": "sales_total", "text": "분기 추정매출은 1,000원입니다.",
          "values": [{"label": "분기 추정매출", "value": 1000, "unit": "원"}], "warnings": ["개별 가게 매출이 아닙니다."]}]
CLS = {"text": "합성 상권 카페 매출 어때?", "topics": ["sales_total"]}


def completion(content, *, code="20000", finish="stop", role="assistant"):
    return {"status": {"code": code, "message": "OK"},
            "result": {"message": {"role": role, "content": content}, "finishReason": finish,
                       "usage": {"promptTokens": 10, "completionTokens": 5, "totalTokens": 15}}}


class Recorder:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, httpx.Response):
            return item
        return httpx.Response(200, json=item)


def writer(recorder, **options):
    return ClovaWriter(KEY, transport=httpx.MockTransport(recorder), **options)


class SettingsTests(unittest.TestCase):
    def test_no_model_unless_app_mode_is_live(self):
        for mode in ("", "mock", " MOCK "):
            self.assertIsNone(writer_from_env({"APP_MODE": mode, "CLOVA_STUDIO_API_KEY": KEY}))
        self.assertIsNone(writer_from_env({"CLOVA_STUDIO_API_KEY": KEY}))

    def test_live_settings_are_validated_at_start_up(self):
        for env, message in (({"APP_MODE": "live"}, "CLOVA_STUDIO_API_KEY"),
                             ({"APP_MODE": "replay", "CLOVA_STUDIO_API_KEY": KEY}, "replay"),
                             ({"APP_MODE": "prod", "CLOVA_STUDIO_API_KEY": KEY}, "APP_MODE"),
                             ({"APP_MODE": "live", "CLOVA_STUDIO_API_KEY": KEY[:6] + " " + KEY[6:]}, "spaces"),
                             ({"APP_MODE": "live", "CLOVA_STUDIO_API_KEY": KEY, "CLOVA_MODEL_ANSWER": "../x"}, "CLOVA_MODEL_ANSWER"),
                             ({"APP_MODE": "live", "CLOVA_STUDIO_API_KEY": KEY, "ASSISTANT_MODEL_DAILY_LIMIT": "0"}, "LIMIT"),
                             ({"APP_MODE": "live", "CLOVA_STUDIO_API_KEY": KEY, "ASSISTANT_MODEL_DAILY_LIMIT": "x"}, "LIMIT")):
            with self.subTest(env=env), self.assertRaises(ValueError) as caught:
                writer_from_env(env)
            self.assertIn(message, str(caught.exception))
            self.assertNotIn(KEY, str(caught.exception))

    def test_live_writer_uses_defaults_and_hides_the_key(self):
        built = writer_from_env({"APP_MODE": "live", "CLOVA_STUDIO_API_KEY": "Bearer " + KEY})
        self.addCleanup(built.close)
        self.assertEqual((built.model, built.daily_limit), ("HCX-005", 100))
        self.assertNotIn(KEY, repr(built))
        custom = writer_from_env({"APP_MODE": "live", "CLOVA_STUDIO_API_KEY": KEY,
                                  "CLOVA_MODEL_ANSWER": "HCX-007", "ASSISTANT_MODEL_DAILY_LIMIT": "5"})
        self.addCleanup(custom.close)
        self.assertEqual((custom.model, custom.daily_limit), ("HCX-007", 5))


class RequestTests(unittest.TestCase):
    def test_request_shape_follows_the_v3_api(self):
        recorder = Recorder(completion("분기 추정매출은 1,000원이에요. [F2]"))
        client = writer(recorder)
        self.addCleanup(client.close)
        self.assertEqual(client(CARDS, CLS), "분기 추정매출은 1,000원이에요. [F2]")
        request = recorder.requests[0]
        self.assertEqual(str(request.url), "https://clovastudio.stream.ntruss.com/v3/chat-completions/HCX-005")
        self.assertEqual(request.headers["authorization"], "Bearer " + KEY)
        self.assertEqual(len(request.headers["x-ncp-clovastudio-request-id"]), 36)
        body = json.loads(request.content)
        roles = [message["role"] for message in body["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])  # one system message per request
        self.assertEqual(body["messages"][0]["content"], SYSTEM_PROMPT)
        last = body["messages"][-1]["content"]
        self.assertIn("합성 상권 카페 매출 어때?", last)
        self.assertIn("F2 (sales_total) 분기 추정매출은 1,000원입니다.", last)
        self.assertNotIn("개별 가게 매출이 아닙니다.", last)  # warnings are added by the server, not the model
        self.assertEqual(body["maxTokens"], 600)
        self.assertNotIn(KEY, request.content.decode("utf-8"))

    def test_action_turn_without_text_still_gets_a_question(self):
        last = build_request(CARDS, {"topics": []})["messages"][-1]["content"]
        self.assertIn("[질문]\n이 상권 자료를 정리해 주세요.", last)

    def test_failures_raise_model_error_without_the_key(self):
        cases = {
            "http 401": httpx.Response(401, json={"status": {"code": "40100", "message": "Unauthorized"}}),
            "api code": completion("x", code="42901"),
            "cut off": completion("분기 추정매출은", finish="length"),
            "empty": completion("   "),
            "role": completion("x", role="user"),
            "not json": httpx.Response(200, content=b"<html>"),
            "too large": httpx.Response(200, content=b" " * (1024 * 1024 + 1)),
            "timeout": httpx.ConnectTimeout("slow"),
            "too long": completion("가" * 1501),
        }
        for name, response in cases.items():
            client = writer(Recorder(response))
            self.addCleanup(client.close)
            with self.subTest(name), self.assertLogs("app.assistant.clova", level="INFO") as logs, \
                    self.assertRaises(ModelError) as caught:
                logging.getLogger("app.assistant.clova").info("start")
                client(CARDS, CLS)
            self.assertNotIn(KEY, str(caught.exception))
            self.assertNotIn(KEY, "\n".join(logs.output))

    def test_daily_limit_stops_before_sending(self):
        days = iter([datetime(2026, 11, 7, 9), datetime(2026, 11, 7, 10), datetime(2026, 11, 7, 11),
                     datetime(2026, 11, 8, 9)])
        recorder = Recorder(completion("a"), completion("b"), completion("c"))
        client = writer(recorder, daily_limit=2, now=lambda: next(days))
        self.addCleanup(client.close)
        self.assertEqual([client(CARDS, CLS), client(CARDS, CLS)], ["a", "b"])
        with self.assertRaises(ModelError):
            client(CARDS, CLS)
        self.assertEqual(len(recorder.requests), 2)
        self.assertEqual(client(CARDS, CLS), "c")  # a new KST day


class ModelBodyTests(unittest.TestCase):
    def test_server_lines_are_removed_and_conditions_come_first(self):
        body = templates.model_body("**매출**은 1,000원이에요. [F2]\n참고: 매출은 9,999원입니다.\n참고 : 또 9,999원\n", CARDS)
        self.assertEqual(body, "합성 상권의 커피-음료 업종을 2026년 2분기 자료로 볼게요. [F1]\n매출은 1,000원이에요. [F2]")
        self.assertTrue(check_answer(body, CARDS)["ok"])
        self.assertEqual(templates.model_body("참고: 9,999원", CARDS), "")
        # Only the server's conditions sentence may cite the conditions card (live HCX-005 answer, 2026-11-08).
        self.assertEqual(templates.model_body("합성 상권 2026년 2분기 자료예요. [F1]", CARDS), "")
        claim = templates.model_body("주말이 평일보다 장사가 잘 돼요. [F1]\n매출은 1,000원이에요. [F2]", CARDS)
        self.assertEqual(claim, "합성 상권의 커피-음료 업종을 2026년 2분기 자료로 볼게요. [F1]\n매출은 1,000원이에요. [F2]")

    def test_quarters_and_cause_words_must_match_the_cards(self):
        problems = check_answer("2025년 4분기 매출은 1,000원이에요. [F2]", CARDS)["problems"]
        self.assertEqual([p["type"] for p in problems], ["period_not_on_card"])
        self.assertFalse(check_answer("역 공사 때문에 매출이 1,000원이에요. [F2]", CARDS)["ok"])
        self.assertTrue(check_answer("2026년 2분기 매출은 1,000원이에요. [F2]", CARDS)["ok"])

    def test_guesses_and_verdicts_from_live_answers_are_rejected(self):
        # Sentences HCX-005 wrote on 2026-11-08 that passed the earlier checker.
        for sentence in ("유동인구도 줄어들면서 전체적으로 매출이 감소한 것으로 보입니다. [F2]",
                         "이러한 요인들이 복합적으로 작용하여 매출 감소를 초래했을 가능성이 있습니다.",
                         "폐업 점포도 줄어든 것으로 보아 전반적으로 좋아졌다고 할 수 있습니다. [F2]"):
            self.assertFalse(check_answer(sentence, CARDS)["ok"], sentence)


class ClovaFlowTests(_Env, unittest.TestCase):
    """The writer inside one assistant turn, with PR #12 results from synthetic rows."""

    def turn(self, *answers):
        from starlette.requests import Request

        from app.assistant.bridge import endpoint_table, request_with_session
        from app.assistant.flow import AssistantService
        from app.assistant.history import AssistantHistory
        from app.onboarding import create_onboarding_router

        recorder = Recorder(*answers)
        client = writer(recorder)
        self.addCleanup(client.close)
        service = AssistantService(self.store, AssistantHistory(self.store),
                                   endpoint_table(create_onboarding_router(self.store)),
                                   writer=client, use_morph=False, today=date(2026, 11, 7))
        owner, token = self.store.session(None)
        scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}
        return service.handle_message(owner, request_with_session(Request(scope), token), "합정역 카페 매출", None), recorder

    def test_checked_model_text_is_published_with_server_warnings(self):
        data, recorder = self.turn(completion("합정역 카페 매출이 궁금하시군요.\n분기 추정매출은 1,000원이에요. [F2]\n참고: 지어낸 9,999원"))
        self.assertTrue(data["model_used"], data["reply"]["text"])
        text = data["reply"]["text"]
        self.assertTrue(text.startswith("합성 상권 1111111 상권의 커피-음료 업종을 "), text)  # the fake quarter label is 20262
        self.assertIn("분기 추정매출은 1,000원이에요. [F2]", text)
        self.assertNotIn("9,999", text)
        # Warnings and next questions are the server's own and travel beside the text, not inside it.
        self.assertNotIn("참고: ", text)
        self.assertTrue(data["reply"]["notes"])
        self.assertTrue(data["reply"]["suggestions"])
        self.assertIn("F2", data["reply"]["cited"])
        self.assertIn("합정역 카페 매출", json.loads(recorder.requests[0].content)["messages"][-1]["content"])

    def test_wrong_or_failed_model_answers_fall_back(self):
        for answer in (completion("분기 추정매출은 9,999원이에요. [F2]"), completion("2024년 1분기 매출은 1,000원이에요. [F2]"),
                       httpx.Response(500, json={"status": {"code": "50000"}}), completion("")):
            with self.subTest(answer=answer if isinstance(answer, dict) else answer.status_code):
                data, _ = self.turn(answer)
                self.assertFalse(data["model_used"])
                self.assertIn("1,000원", data["reply"]["text"])
                self.assertTrue(data["reply"]["text"].startswith("합성 상권 1111111 상권의"), data["reply"]["text"])


class RouterSettingTests(unittest.TestCase):
    def setUp(self):
        self.store = OnboardingStore(":memory:")
        self.addCleanup(self.store.close)

    def test_status_reports_the_connection_but_never_the_key(self):
        logger = logging.getLogger("app.assistant")
        before = (list(logger.handlers), logger.level, logger.propagate)

        def restore():
            logger.handlers[:] = before[0]
            logger.setLevel(before[1])  # setLevel also clears the logger's level cache
            logger.propagate = before[2]

        self.addCleanup(restore)
        with patch.dict(os.environ, {"ASSISTANT_ENABLED": "1", "APP_MODE": "live", "CLOVA_STUDIO_API_KEY": KEY}, clear=True):
            client = TestClient(intake_api.create_app(self.store))
            status = client.get("/api/assistant/status")
        self.assertEqual(status.json()["model_connected"], True)
        self.assertEqual(status.json()["planner_connected"], True)
        self.assertIn("rank_industries", status.json()["tools"])
        self.assertNotIn(KEY, status.text)
        # Usage lines reach the service log only through this handler.
        self.assertEqual((logger.level, len(logger.handlers)), (logging.INFO, 1))
        env = {"ASSISTANT_ENABLED": "1", "APP_MODE": "live", "CLOVA_STUDIO_API_KEY": KEY, "ASSISTANT_PLANNER": "off"}
        with patch.dict(os.environ, env, clear=True):
            status = TestClient(intake_api.create_app(self.store)).get("/api/assistant/status").json()
        self.assertEqual((status["model_connected"], status["planner_connected"], status["tools"]), (True, False, []))
        with patch.dict(os.environ, {**env, "ASSISTANT_PLANNER": "maybe"}, clear=True), self.assertRaises(ValueError):
            intake_api.create_app(self.store)

    def test_model_settings_do_not_touch_the_basic_app(self):
        with patch.dict(os.environ, {"APP_MODE": "live"}, clear=True):
            client = TestClient(intake_api.create_app(self.store))  # no key needed while the assistant is off
            self.assertEqual(client.get("/api/assistant/status").status_code, 404)
        with patch.dict(os.environ, {"ASSISTANT_ENABLED": "1", "APP_MODE": "live"}, clear=True), \
                self.assertRaises(ValueError):
            intake_api.create_app(self.store)


if __name__ == "__main__":
    unittest.main()
