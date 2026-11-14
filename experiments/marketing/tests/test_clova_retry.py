"""HCX 호출(clova.call)의 제한 시간·재시도·오류 반환 검증 — 네트워크를 부르지 않는다 (urlopen 을 가짜로 바꿈).

실행 (experiments/marketing 에서):
  python -m pytest -q tests/test_clova_retry.py      또는      python -m tests.test_clova_retry
"""

import io
import json
import os
import unittest
import urllib.error
from http.client import RemoteDisconnected
from unittest.mock import patch

import clova

KEY = "nv-test-secret-key-0123456789"
OK = {"result": {"message": {"content": "안녕하세요"}, "usage": {"totalTokens": 100}}}


class FakeResponse:
    def __init__(self, payload):
        self._raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, body="한도 초과"):
    return urllib.error.HTTPError("https://example.invalid", code, "msg", {}, io.BytesIO(body.encode("utf-8")))


def run(outcomes, env=None):
    """urlopen 이 차례로 돌려줄 응답·예외 목록으로 call 을 한 번 부른다. (결과, urlopen mock, sleep mock)"""
    with patch.dict(os.environ):
        os.environ.pop("CLOVA_TIMEOUT_SEC", None)
        os.environ.update(env or {})
        with patch("urllib.request.urlopen", side_effect=outcomes) as opened, patch("clova.time.sleep") as sleep:
            result = clova.call(KEY, "system", [{"role": "user", "content": "안녕"}])
    return result, opened, sleep


class TestTimeout(unittest.TestCase):
    def test_default_is_30_seconds(self):
        _, opened, _ = run([FakeResponse(OK)])
        self.assertEqual(opened.call_args.kwargs["timeout"], 30.0)

    def test_env_changes_it(self):
        _, opened, _ = run([FakeResponse(OK)], env={"CLOVA_TIMEOUT_SEC": "12.5"})
        self.assertEqual(opened.call_args.kwargs["timeout"], 12.5)

    def test_bad_values_fall_back_to_default(self):
        for bad in ("abc", "0", "-5", "", "nan", "99999"):
            with self.subTest(bad=bad):
                self.assertEqual(run([FakeResponse(OK)], env={"CLOVA_TIMEOUT_SEC": bad})[1].call_args.kwargs["timeout"], 30.0)


class TestRetry(unittest.TestCase):
    def test_success_first_try_does_not_wait(self):
        res, opened, sleep = run([FakeResponse(OK)])
        self.assertEqual(res["content"], "안녕하세요")
        self.assertEqual(opened.call_count, 1)
        sleep.assert_not_called()

    def test_timeout_then_success(self):
        res, opened, sleep = run([TimeoutError("The read operation timed out"), FakeResponse(OK)])
        self.assertEqual(res["content"], "안녕하세요")
        self.assertEqual(opened.call_count, 2)
        sleep.assert_called_once()
        self.assertTrue(1.0 <= sleep.call_args.args[0] <= 1.5, sleep.call_args)

    def test_retryable_failures_are_retried_exactly_once(self):
        cases = {
            "제한 시간 초과": TimeoutError("The read operation timed out"),
            "연결 못 함": urllib.error.URLError("connection refused"),
            "연결 끊김": ConnectionResetError("Connection reset by peer"),
            "응답 없이 끊김": RemoteDisconnected("Remote end closed connection"),
            "한도 초과 429": http_error(429),
            "서버 오류 500": http_error(500),
            "서버 오류 503": http_error(503),
            "응답이 중간에 끊김": FakeResponse(b'{"result": {"message": '),
        }
        for name, first in cases.items():
            with self.subTest(name):
                res, opened, sleep = run([first, FakeResponse(OK)])
                self.assertEqual(res.get("content"), "안녕하세요", res)
                self.assertEqual(opened.call_count, 2)
                self.assertEqual(sleep.call_count, 1)

    def test_still_failing_returns_error_dict_and_never_raises(self):
        for name, exc in {"시간 초과": TimeoutError("timed out"), "연결": urllib.error.URLError("down"),
                          "429": http_error(429), "502": http_error(502, "bad gateway")}.items():
            with self.subTest(name):
                res, opened, sleep = run([exc, exc])
                self.assertIn("error", res)
                self.assertNotIn("content", res)
                self.assertEqual(opened.call_count, 2)      # 처음 1번 + 다시 1번, 그 이상 부르지 않음
                self.assertEqual(sleep.call_count, 1)

    def test_client_errors_are_not_retried(self):
        for code in (400, 401, 403, 404):
            with self.subTest(code=code):
                res, opened, sleep = run([http_error(code, "잘못된 요청")])
                self.assertTrue(res["error"].startswith(f"HTTP {code}"))
                self.assertEqual(opened.call_count, 1)
                sleep.assert_not_called()

    def test_each_attempt_gets_a_new_request_id(self):
        _, opened, _ = run([TimeoutError("timed out"), FakeResponse(OK)])
        ids = [c.args[0].get_header("X-ncp-clovastudio-request-id") for c in opened.call_args_list]
        self.assertEqual(len(set(ids)), 2)

    def test_key_never_appears_in_the_error(self):
        res, _, _ = run([http_error(500, f"echo {KEY}"), http_error(500, f"echo {KEY}")])
        self.assertNotIn(KEY, res["error"])
        self.assertIn("***", res["error"])
        res, _, _ = run([http_error(400, f"echo {KEY}")])
        self.assertNotIn(KEY, res["error"])

    def test_error_text_is_capped(self):
        res, _, _ = run([http_error(400, "가" * 5000)])
        self.assertLessEqual(len(res["error"]), 500)


if __name__ == "__main__":
    unittest.main()
