"""Network-free checks for the basic/Function Calling demonstration.

Synthetic completion responses exercise the protocol and local tool dispatcher.
They do not establish real API access or model response quality.
"""

from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import clova_function_calling_test as target
from clova_live_test import ApiError


FAKE_KEY = "test-only-not-a-real-api-key"
TOOL_CALL_ID = "call_test_store_001"
USAGE = {"prompt_tokens": 21, "completion_tokens": 13, "total_tokens": 34}


def store_tool_call(arguments=None, name="get_store_info"):
    if arguments is None:
        arguments = json.dumps({"store_name": "달빛카페"}, ensure_ascii=False)
    return {
        "id": TOOL_CALL_ID,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def completion(message, finish_reason="stop", usage=None):
    return {
        "id": "chatcmpl-offline-fixture",
        "object": "chat.completion",
        "created": 0,
        "model": "HCX-005",
        "choices": [{
            "index": 0,
            "message": deepcopy(message),
            "finish_reason": finish_reason,
        }],
        "usage": deepcopy(USAGE if usage is None else usage),
    }


def text_completion(text="달빛카페는 토요일에 휴무입니다.", finish_reason="stop"):
    return completion({"role": "assistant", "content": text}, finish_reason)


def tool_completion(tool_call=None):
    return completion(
        {"role": "assistant", "content": None,
         "tool_calls": [store_tool_call() if tool_call is None else tool_call]},
        "tool_calls",
    )


class RecordingTransport:
    """A finite response queue. Unexpected retries fail immediately."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, payload, api_key, request_id):
        self.requests.append({
            "payload": deepcopy(payload),
            "api_key": api_key,
            "request_id": request_id,
        })
        if not self.responses:
            raise AssertionError("Unexpected extra transport call or automatic retry")
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return deepcopy(result)


class OfflineOnlyTestCase(unittest.TestCase):
    def setUp(self):
        # Never read a developer's real API key or perform a real HTTP request.
        self.env_patch = patch.dict("os.environ", {}, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.http_patch = patch(
            "urllib.request.OpenerDirector.open",
            side_effect=AssertionError("Real network use is forbidden in these tests"),
        )
        self.http_patch.start()
        self.addCleanup(self.http_patch.stop)
        self.socket_patch = patch(
            "socket.create_connection",
            side_effect=AssertionError("Real network use is forbidden in these tests"),
        )
        self.socket_patch.start()
        self.addCleanup(self.socket_patch.stop)

    def live_client(self, responses):
        transport = RecordingTransport(responses)
        client = target.CompletionClient(
            mode="live", api_key=FAKE_KEY, transport=transport,
        )
        return client, transport


class ToolValidationTests(OfflineOnlyTestCase):
    def test_only_known_store_can_be_read_as_json_serializable_data(self):
        result = target.execute_tool(store_tool_call())
        self.assertIsInstance(result, dict)
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertIn("달빛카페", serialized)
        self.assertEqual(json.loads(serialized), result)

    def test_unknown_tool_is_rejected(self):
        with self.assertRaises(ApiError):
            target.execute_tool(store_tool_call(name="run_shell"))

    def test_arguments_must_be_exact_store_name_json_object(self):
        bad_arguments = [
            "not json",
            "{'store_name': '달빛카페'}",
            "null",
            "[]",
            '"달빛카페"',
            "{}",
            '{"store_name": "다른카페"}',
            '{"store_name": ""}',
            '{"store_name": 1}',
            '{"store_name": null}',
            '{"store_name": ["달빛카페"]}',
            '{"store_name": "달빛카페", "extra": true}',
            {"store_name": "달빛카페"},
            ["달빛카페"],
            1,
            False,
        ]
        for arguments in bad_arguments:
            with self.subTest(arguments=arguments):
                call = store_tool_call()
                call["function"]["arguments"] = arguments
                with self.assertRaises(ApiError):
                    target.execute_tool(call)

    def test_null_or_missing_arguments_are_rejected(self):
        for remove in (False, True):
            with self.subTest(missing=remove):
                call = store_tool_call()
                if remove:
                    del call["function"]["arguments"]
                else:
                    call["function"]["arguments"] = None
                with self.assertRaises(ApiError):
                    target.execute_tool(call)

    def test_malformed_tool_call_envelopes_are_rejected(self):
        bad_calls = [None, [], "get_store_info", {},
                     {"id": TOOL_CALL_ID, "type": "function", "function": []}]
        for field, value in (("id", ""), ("id", None), ("type", "shell")):
            call = store_tool_call()
            call[field] = value
            bad_calls.append(call)
        for field in ("id", "type", "function"):
            call = store_tool_call()
            del call[field]
            bad_calls.append(call)
        for call in bad_calls:
            with self.subTest(tool_call=call):
                with self.assertRaises(ApiError):
                    target.execute_tool(call)

    def test_code_like_arguments_are_not_evaluated(self):
        arguments = "__import__('os').system('DO_NOT_EXECUTE')"
        with patch("builtins.eval", side_effect=AssertionError("Tool input was evaluated")):
            with self.assertRaises(ApiError):
                target.execute_tool(store_tool_call(arguments=arguments))


class MockWorkflowTests(OfflineOnlyTestCase):
    def test_default_client_works_without_api_key_or_network(self):
        client = target.CompletionClient()
        result = target.run_basic(client)
        self.assertTrue(result["response_text"].strip())
        self.assertEqual(len(client.calls), 1)

    def test_mock_basic_and_function_flow_complete_with_three_calls(self):
        client = target.CompletionClient(mode="mock")
        basic = target.run_basic(client)
        function = target.run_function_calling(client)
        self.assertTrue(basic["response_text"].strip())
        self.assertTrue(function["response_text"].strip())
        self.assertEqual(len(function["tool_executions"]), 1)
        self.assertEqual(len(client.calls), 3)

    def test_mock_function_call_id_and_local_result_are_preserved(self):
        client = target.CompletionClient(mode="mock")
        result = target.run_function_calling(client)
        selection = client.calls[0]["response"]["choices"][0]["message"]["tool_calls"][0]
        follow_up = client.calls[1]["request"]["messages"]
        self.assertEqual(follow_up[-2]["tool_calls"], [selection])
        self.assertEqual(follow_up[-1]["role"], "tool")
        self.assertEqual(follow_up[-1]["tool_call_id"], selection["id"])
        self.assertEqual(json.loads(follow_up[-1]["content"]), result["tool_executions"][0]["result"])
        self.assertEqual(result["tool_selection"], "fixed_mock_model")

    def test_mock_does_not_report_real_token_usage_or_http_latency(self):
        client = target.CompletionClient(mode="mock")
        target.run_basic(client)
        target.run_function_calling(client)
        for call in client.calls:
            self.assertFalse(call["http_request_attempted"])
            self.assertIsNone(call["usage"])
            self.assertIsNone(call["elapsed_seconds"])
            self.assertGreaterEqual(call["mock_processing_seconds"], 0)
        self.assertIsNone(target.summarize_usage(client.calls))

    def test_basic_and_both_function_stages_use_required_token_limits(self):
        # Regression for API 40001: any request carrying tools needs >=1024,
        # including the final-answer request with tool_choice="none".
        client = target.CompletionClient(mode="mock")
        target.run_basic(client)
        target.run_function_calling(client)
        basic, selection, answer = [call["request"] for call in client.calls]

        self.assertEqual(basic["max_tokens"], 256)
        self.assertNotIn("tools", basic)
        for payload, expected_choice in ((selection, "auto"), (answer, "none")):
            with self.subTest(tool_choice=expected_choice):
                self.assertTrue(payload["tools"])
                self.assertEqual(payload["tool_choice"], expected_choice)
                self.assertEqual(payload["max_tokens"], 1024)
        for payload in (basic, selection, answer):
            self.assertNotIn("max_completion_tokens", payload)

    def test_mock_does_not_invoke_a_supplied_live_transport(self):
        def forbidden_transport(*args):
            raise AssertionError("Mock mode invoked the HTTP transport")

        client = target.CompletionClient(mode="mock", transport=forbidden_transport)
        target.run_basic(client)
        target.run_function_calling(client)


class FunctionCallingProtocolTests(OfflineOnlyTestCase):
    def test_tool_result_is_sent_back_with_matching_call_id(self):
        call = store_tool_call()
        final_text = "달빛카페는 토요일과 일요일에 휴무입니다."
        client, transport = self.live_client([
            (200, tool_completion(call)),
            (200, text_completion(final_text)),
        ])

        result = target.run_function_calling(client)

        self.assertEqual(result["response_text"], final_text)
        self.assertEqual(len(result["tool_executions"]), 1)
        self.assertEqual(len(transport.requests), 2)
        initial = transport.requests[0]["payload"]
        follow_up = transport.requests[1]["payload"]
        self.assertEqual(initial["messages"][-1]["role"], "user")
        definitions = initial["tools"]
        self.assertEqual(definitions[0]["type"], "function")
        self.assertEqual(definitions[0]["function"]["name"], "get_store_info")
        self.assertEqual(follow_up["messages"][:len(initial["messages"])], initial["messages"])
        assistant_message, tool_message = follow_up["messages"][-2:]
        self.assertEqual(assistant_message["role"], "assistant")
        self.assertEqual(assistant_message["tool_calls"], [call])
        self.assertEqual(tool_message["role"], "tool")
        self.assertEqual(tool_message["tool_call_id"], TOOL_CALL_ID)
        self.assertIsInstance(tool_message["content"], str)
        self.assertEqual(json.loads(tool_message["content"]), target.execute_tool(call))

    def test_final_answer_without_tool_selection_is_rejected(self):
        client, transport = self.live_client([(200, text_completion())])
        with self.assertRaises(ApiError):
            target.run_function_calling(client)
        self.assertEqual(len(transport.requests), 1)

    def test_unknown_selected_tool_stops_before_second_model_call(self):
        client, transport = self.live_client([
            (200, tool_completion(store_tool_call(name="run_shell"))),
        ])
        with self.assertRaises(ApiError):
            target.run_function_calling(client)
        self.assertEqual(len(transport.requests), 1)

    def test_malformed_arguments_stop_before_second_model_call(self):
        client, transport = self.live_client([
            (200, tool_completion(store_tool_call(arguments="{broken"))),
        ])
        with self.assertRaises(ApiError):
            target.run_function_calling(client)
        self.assertEqual(len(transport.requests), 1)

    def test_empty_final_answer_is_rejected(self):
        for answer in ("", " \n ", None):
            with self.subTest(answer=answer):
                client, transport = self.live_client([
                    (200, tool_completion()),
                    (200, text_completion(answer)),
                ])
                with self.assertRaises(ApiError):
                    target.run_function_calling(client)
                self.assertEqual(len(transport.requests), 2)

    def test_truncated_final_answer_is_rejected(self):
        client, transport = self.live_client([
            (200, tool_completion()),
            (200, text_completion("달빛카페는", finish_reason="length")),
        ])
        with self.assertRaises(ApiError):
            target.run_function_calling(client)
        self.assertEqual(len(transport.requests), 2)


class CompletionClientTests(OfflineOnlyTestCase):
    def test_endpoint_is_openai_compatible_route(self):
        self.assertEqual(
            target.ENDPOINT,
            "https://clovastudio.stream.ntruss.com/v1/openai/chat/completions",
        )

    def test_basic_rejects_empty_answers(self):
        for answer in ("", " \n ", None):
            with self.subTest(answer=answer):
                client, transport = self.live_client([(200, text_completion(answer))])
                with self.assertRaises(ApiError):
                    target.run_basic(client)
                self.assertEqual(len(transport.requests), 1)

    def test_basic_rejects_truncated_answer(self):
        client, transport = self.live_client([
            (200, text_completion("달빛카페는", finish_reason="length")),
        ])
        with self.assertRaises(ApiError):
            target.run_basic(client)
        self.assertEqual(len(transport.requests), 1)

    def test_calls_use_snake_case_and_record_usage_and_elapsed_time(self):
        client, transport = self.live_client([
            (200, text_completion()),
            (200, tool_completion()),
            (200, text_completion()),
        ])
        target.run_basic(client)
        target.run_function_calling(client)
        self.assertEqual(len(client.calls), 3)
        forbidden_keys = {
            "topP", "topK", "maxTokens", "repetitionPenalty",
            "stopSequences", "includeAiFilters", "toolChoice", "parallelToolCalls",
        }
        for request in transport.requests:
            payload = request["payload"]
            self.assertFalse(forbidden_keys.intersection(payload))
            self.assertIn("max_tokens", payload)
            self.assertIn("model", payload)
            self.assertEqual(request["api_key"], FAKE_KEY)
            self.assertTrue(request["request_id"])
            self.assertNotIn(FAKE_KEY, json.dumps(payload, ensure_ascii=False))
        ids = [request["request_id"] for request in transport.requests]
        self.assertEqual(len(set(ids)), 3)
        for call in client.calls:
            self.assertIsInstance(call["elapsed_seconds"], (int, float))
            self.assertGreaterEqual(call["elapsed_seconds"], 0)
            self.assertEqual(call["usage"], USAGE)

    def test_fourth_request_is_refused_before_transport(self):
        client, transport = self.live_client([(200, text_completion()) for _ in range(3)])
        for _ in range(3):
            target.run_basic(client)
        with self.assertRaises(ApiError):
            target.run_basic(client)
        self.assertEqual(len(transport.requests), 3)
        self.assertEqual(len(client.calls), 3)

    def test_http_failures_are_not_retried_and_consume_call_budget(self):
        responses = [(503, {"error": {"message": "synthetic unavailable"}}) for _ in range(3)]
        client, transport = self.live_client(responses)
        for expected_count in (1, 2, 3):
            with self.assertRaises(ApiError):
                target.run_basic(client)
            self.assertEqual(len(transport.requests), expected_count)
        with self.assertRaises(ApiError):
            target.run_basic(client)
        self.assertEqual(len(transport.requests), 3)
        self.assertEqual(len(client.calls), 3)

    def test_transport_error_is_not_retried(self):
        client, transport = self.live_client([ApiError("synthetic transport error")])
        with self.assertRaises(ApiError):
            target.run_basic(client)
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(len(client.calls), 1)

    def test_missing_token_usage_stays_unknown_in_live_results(self):
        response = text_completion()
        del response["usage"]
        client, transport = self.live_client([(200, response)])
        target.run_basic(client)
        self.assertEqual(len(transport.requests), 1)
        self.assertIsNone(client.calls[0]["usage"])
        self.assertIsNone(target.summarize_usage(client.calls))
        self.assertGreaterEqual(client.calls[0]["elapsed_seconds"], 0)

    def test_invalid_usage_is_not_invented_as_zero(self):
        for usage in (None, {}, {"prompt_tokens": 3},
                      {"prompt_tokens": 3, "completion_tokens": True, "total_tokens": 4},
                      {"prompt_tokens": -1, "completion_tokens": 2, "total_tokens": 1},
                      {"prompt_tokens": "3", "completion_tokens": 2, "total_tokens": 5}):
            with self.subTest(usage=usage):
                response = text_completion()
                response["usage"] = usage
                client, _ = self.live_client([(200, response)])
                target.run_basic(client)
                self.assertIsNone(client.calls[0]["usage"])
                self.assertIsNone(target.summarize_usage(client.calls))


class CommandLineTests(OfflineOnlyTestCase):
    def invoke_mock(self, extra_arguments):
        with TemporaryDirectory() as temporary:
            fake_script = str(Path(temporary) / "clova_function_calling_test.py")
            with patch.object(target, "__file__", fake_script), \
                    patch.object(sys, "argv", [fake_script, *extra_arguments]), \
                    patch.object(target, "load_api_key", side_effect=AssertionError("Mock must not load a key")), \
                    redirect_stdout(io.StringIO()):
                exit_code = target.main()
            output = Path(temporary) / "output" / "clova_openai_mock_latest.json"
            self.assertTrue(output.is_file())
            return exit_code, json.loads(output.read_text(encoding="utf-8"))

    def test_default_cli_is_mock_all_and_writes_explicit_mock_report(self):
        exit_code, report = self.invoke_mock([])
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["mode"], "mock")
        self.assertEqual(report["scenario"], "all")
        self.assertEqual(report["status"], "flow_completed")
        self.assertEqual(report["http_requests_attempted"], 0)
        self.assertEqual(report["automatic_retries"], 0)
        self.assertEqual(report["model_responses_simulated"], 3)
        self.assertIsNone(report["token_usage_total"])
        self.assertEqual(report["elapsed_time_scope"], "local_mock_only")
        self.assertEqual(set(report["scenarios"]), {"basic", "function_calling"})
        for call in report["calls"]:
            self.assertFalse(call["http_request_attempted"])
            self.assertIsNone(call["usage"])
            self.assertIsNone(call["elapsed_seconds"])

    def test_each_scenario_runs_only_its_requested_flow(self):
        for scenario, expected_calls, expected_results in (
                ("basic", 1, {"basic"}),
                ("function", 2, {"function_calling"}),
                ("all", 3, {"basic", "function_calling"})):
            with self.subTest(scenario=scenario):
                exit_code, report = self.invoke_mock(["--scenario", scenario])
                self.assertEqual(exit_code, 0)
                self.assertEqual(report["mode"], "mock")
                self.assertEqual(len(report["calls"]), expected_calls)
                self.assertEqual(set(report["scenarios"]), expected_results)
                self.assertEqual(report["http_requests_attempted"], 0)
                self.assertEqual(report["model_responses_simulated"], expected_calls)
                if scenario == "function":
                    self.assertEqual(
                        [call["stage"] for call in report["calls"]],
                        ["function_select", "function_answer"],
                    )
                    self.assertEqual(
                        [call["request"]["max_tokens"] for call in report["calls"]],
                        [1024, 1024],
                    )

    def test_explicit_live_without_key_stops_before_any_request(self):
        with patch.object(sys, "argv", ["clova_function_calling_test.py", "--live"]), \
                patch.object(target, "load_api_key", side_effect=ApiError("synthetic missing key")), \
                patch.object(target, "post_json", side_effect=AssertionError("Missing key must prevent HTTP")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(target.main(), 2)


if __name__ == "__main__":
    unittest.main()
