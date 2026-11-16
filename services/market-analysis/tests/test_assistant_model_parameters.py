"""Model-specific API parameters at the wire boundary; no external API calls."""
from copy import deepcopy
import json
import unittest

import httpx

from app.assistant.clova_client import ClovaWriter, build_request, writer_from_env
from app.assistant.planner import build_request as planner_request
from tests.test_assistant_clova import CARDS, CLS, KEY, Recorder, completion


class ModelParameterTests(unittest.TestCase):
    def send(self, model, body, *, purpose="answer"):
        recorder = Recorder(completion("검증된 답변입니다."))
        client = ClovaWriter(KEY, model=model, transport=httpx.MockTransport(recorder))
        self.addCleanup(client.close)
        result = client.complete(body, purpose=purpose)
        return result, json.loads(recorder.requests[0].content), str(recorder.requests[0].url)

    def test_005_preserves_the_existing_request_exactly(self):
        body = build_request(CARDS, CLS)
        original = deepcopy(body)
        _result, sent, url = self.send("HCX-005", body)
        self.assertEqual(sent, original)
        self.assertEqual(body, original)
        self.assertTrue(url.endswith("/HCX-005"))

    def test_007_answer_uses_supported_parameters_without_mutating_shared_input(self):
        body = build_request(CARDS, CLS)
        original = deepcopy(body)
        _result, sent, url = self.send("HCX-007", body)
        self.assertTrue(url.endswith("/HCX-007"))
        self.assertNotIn("maxTokens", sent)
        self.assertEqual(sent["maxCompletionTokens"], 600)
        self.assertEqual(sent["thinking"], {"effort": "none"})
        self.assertEqual(sent["messages"], original["messages"])
        self.assertEqual(body, original)
        _result, legacy, _url = self.send("HCX-005", body)
        self.assertEqual(legacy, original)

    def test_007_planner_keeps_its_own_budget_and_messages(self):
        body = planner_request("합정역 카페 매출")
        original = deepcopy(body)
        _result, sent, _url = self.send("HCX-007", body, purpose="plan")
        self.assertEqual(sent["maxCompletionTokens"], 300)
        self.assertEqual(sent["thinking"], {"effort": "none"})
        self.assertNotIn("maxTokens", sent)
        self.assertEqual(sent["messages"], original["messages"])
        self.assertEqual(body, original)

    def test_explicit_007_budget_and_reasoning_settings_are_preserved(self):
        body = {"messages": [{"role": "user", "content": "시험"}],
                "maxCompletionTokens": 5120, "thinking": {"effort": "low"}, "seed": 123}
        original = deepcopy(body)
        _result, sent, _url = self.send("HCX-007", body)
        self.assertEqual(sent, original)
        self.assertEqual(body, original)

    def test_environment_selection_applies_007_parameters_to_the_writer(self):
        recorder = Recorder(completion("분기 추정매출은 1,000원입니다. [F2]"))
        client = writer_from_env({"APP_MODE": "live", "CLOVA_STUDIO_API_KEY": KEY,
                                  "CLOVA_MODEL_ANSWER": "HCX-007"},
                                 transport=httpx.MockTransport(recorder))
        self.addCleanup(client.close)
        self.assertEqual(client(CARDS, CLS), "분기 추정매출은 1,000원입니다. [F2]")
        sent = json.loads(recorder.requests[0].content)
        self.assertEqual(sent["maxCompletionTokens"], 600)
        self.assertNotIn("maxTokens", sent)


if __name__ == "__main__":
    unittest.main()
