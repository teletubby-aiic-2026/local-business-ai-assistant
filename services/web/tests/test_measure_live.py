"""측정 스크립트(scripts/measure_live.py) 시험. 서버를 띄우지 않는다: mock 앱을 TestClient 로 직접 부른다.
HCX·네트워크 호출 없음. 실행 (services/web 에서):
  env -u APP_MODE PYTHONPATH="../.." python -m pytest -q tests/test_measure_live.py
C6 저장본(기본: 저장소의 experiments/marketing)이 없으면 그 저장본이 필요한 시험만 건너뛴다.
"""
from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from web.demo import Demo
from web.main import create_app
from web.settings import WEB_DIR

from .test_web import HAS_C6, FakeSource, settings

# scripts/ 는 패키지가 아니라 단독 실행 스크립트라서 경로로 불러온다
_spec = importlib.util.spec_from_file_location("measure_live", WEB_DIR / "scripts" / "measure_live.py")
ml = importlib.util.module_from_spec(_spec)
sys.modules["measure_live"] = ml
_spec.loader.exec_module(ml)

PASS, CHECK, FAIL = ml.PASS, ml.CHECK, ml.FAIL
APP_JS = WEB_DIR / "web" / "static" / "app.js"


def mock_client() -> TestClient:
    return TestClient(create_app(Demo(settings(Path(tempfile.mkdtemp())), source=FakeSource())))


class Recorder:
    """TestClient 를 감싸 보낸 요청을 적어 둔다."""

    def __init__(self, inner):
        self.inner, self.posts = inner, []

    def get(self, path, **kw):
        return self.inner.get(path, **kw)

    def post(self, path, **kw):
        self.posts.append((path, kw.get("json")))
        return self.inner.post(path, **kw)


class Flaky:
    """정해 둔 호출만 실패시킨다. plan: {(경로, 그 경로의 몇 번째 호출): "timeout" | "garbage" | "boom" | HTTP 상태 번호}."""

    def __init__(self, inner, plan):
        self.inner, self.plan, self.seen = inner, plan, {}

    def _go(self, call, path, kw):
        self.seen[path] = self.seen.get(path, 0) + 1
        action = self.plan.get((path, self.seen[path]))
        if action == "timeout":
            raise httpx.ReadTimeout("시험용 시간 초과")
        if action == "boom":
            raise RuntimeError("시험용 예외")
        if action == "garbage":
            return httpx.Response(200, content=b"<html>not json</html>")
        if isinstance(action, int):
            return httpx.Response(action, json={"error": {"message": "시험용 서버 오류"}})
        return call(path, **kw)

    def get(self, path, **kw):
        return self._go(self.inner.get, path, kw)

    def post(self, path, **kw):
        return self._go(self.inner.post, path, kw)


class AlwaysDown:
    def get(self, path, **kw):
        raise httpx.ConnectError("시험용: 서버 없음")

    post = get


def draft(**kw) -> dict:
    base = {"draft_id": "d_x", "generator": "reply_draft", "text": "본문", "failed_reasons": [], "needs_input": [],
            "c7_flags": [], "checks": {}}
    base.update(kw)
    return base


# ── 점검 상태 3가지: app.js statusOf 와 같은 규칙 ─────────────────────
class StatusRule(unittest.TestCase):
    def test_three_statuses_from_hand_made_drafts(self):
        self.assertEqual(ml.draft_status(draft()), PASS)
        # length_ok 가 False 여도 failed_reasons 에 없으면 화면은 '점검 통과'다 (C6 가 다시 쓰기 사유에서 뺌)
        self.assertEqual(ml.draft_status(draft(checks={"length_ok": False, "no_bad_number": True})), PASS)
        self.assertEqual(ml.draft_status(draft(needs_input=["menu_prices 없음: 쿠폰 메뉴·금액을 정할 수 없어요"])), CHECK)
        self.assertEqual(ml.draft_status(draft(c7_flags=["이미 한 조치처럼 말함: '추가로 보내드렸' (확인)"])), CHECK)
        self.assertEqual(ml.draft_status(draft(needs_input=["a"], c7_flags=["b"])), CHECK)
        self.assertEqual(ml.draft_status(draft(failed_reasons=["첫 문장에 불편을 드려 죄송하다는 사과를 넣어 주세요."])), FAIL)
        # 실패가 확인 필요보다 먼저 (statusOf 는 failedOf 를 먼저 본다)
        self.assertEqual(ml.draft_status(draft(failed_reasons=["x"], needs_input=["a"], c7_flags=["b"])), FAIL)

    def test_missing_or_null_fields_are_a_pass(self):
        self.assertEqual(ml.draft_status({}), PASS)
        self.assertEqual(ml.draft_status({"failed_reasons": None, "needs_input": None, "c7_flags": None}), PASS)
        self.assertEqual(ml.draft_status({"needs_input": None, "c7_flags": ["b"]}), CHECK)

    def test_kind_comes_from_generator(self):
        self.assertEqual([ml.draft_kind(draft(generator=g)) for g in ("reply_draft", "prevention_notice", "coupon_promo")],
                         ["답글", "재발 방지 공지", "홍보글"])
        self.assertEqual(ml.draft_kind(draft(generator="new_thing")), "new_thing")   # 모르는 종류도 센다

    def test_failed_check_names(self):
        d = draft(checks={"length_ok": False, "has_apology": False, "no_bad_promise": True},
                  failed_reasons=["첫 문장에 불편을 드려 죄송하다는 사과를 넣어 주세요."])
        self.assertEqual(ml.failed_check_names(d), ["has_apology"])      # length_ok 는 점검 실패가 아님
        self.assertEqual(ml.failed_check_names(draft(checks={"length_ok": False})), [])
        self.assertEqual(ml.failed_check_names(draft(failed_reasons=["x"], checks={"length_ok": False})), [ml.UNKNOWN_CHECK])
        self.assertEqual(ml.failed_check_names(draft(failed_reasons=["x"])), [ml.UNKNOWN_CHECK])

    def test_needs_check_names_drop_the_quoted_body(self):
        d = draft(needs_input=["menu_prices 없음: 쿠폰 메뉴·금액을 정할 수 없어요", "사장님 확인 필요"],
                  c7_flags=["이미 한 조치처럼 말함: '추가로 보내드렸' (사장님이 실제로 했는지 확인)"])
        names = ml.needs_check_names(d)
        self.assertEqual(names, ["needs_input/menu_prices 없음", "needs_input/사장님 확인 필요", "c7_flags/이미 한 조치처럼 말함"])
        self.assertNotIn("보내드렸", " ".join(names))

    def test_saved_row_has_length_but_not_the_body(self):
        row = ml.describe_draft(draft(text="사장님만 아는 본문 글", failed_reasons=["x"], checks={"no_bad_number": False}))
        self.assertEqual(row["text_len"], len("사장님만 아는 본문 글"))
        self.assertEqual((row["status"], row["failed_checks"]), (FAIL, ["no_bad_number"]))
        self.assertNotIn("본문 글", json.dumps(row, ensure_ascii=False))
        self.assertNotIn("text", row)

    def test_rules_are_still_the_ones_in_app_js(self):
        """app.js 규칙이 바뀌면 여기서 걸린다 → scripts/measure_live.py 의 draft_status·card_run_body 를 같이 고칠 것."""
        js = re.sub(r"\s+", " ", APP_JS.read_text(encoding="utf-8"))
        for rule in ('const failedOf = (d) => d.failed_reasons || [];',
                     'const checksOf = (d) => [...(d.needs_input || []), ...(d.c7_flags || [])];',
                     '? ["bad", "점검 실패"] : checksOf(d).length ? ["warn", "확인 필요"] : ["ok", "점검 통과"]',
                     'failedOf(d).length ?',
                     'reply_draft: "답글", prevention_notice: "재발 방지 공지"',
                     'JSON.stringify({ measures: boxes.filter((b) => b.checked).map((b) => b.value) })',
                     'const on = new Set(m.default || []);'):
            self.assertIn(rule, js)


class RequestBody(unittest.TestCase):
    def test_body_is_what_the_screen_sends(self):
        card = {"measures": {"options": [{"id": "M1"}, {"id": "M2"}, {"id": "M3"}], "default": ["M2", "M9"]}}
        self.assertEqual(ml.card_run_body(card), {"measures": ["M2"]})                # 상자에 없는 id 는 못 보냄
        self.assertEqual(ml.card_run_body({"measures": {"options": [{"id": "M1"}], "default": []}}), {"measures": []})
        self.assertIsNone(ml.card_run_body({"measures": {}}))                          # 홍보 카드: 상자가 없어 본문 없음
        self.assertIsNone(ml.card_run_body({}))


# ── mock 앱을 2라운드 ───────────────────────────────────────────────
@unittest.skipUnless(HAS_C6, "C6 저장본 없음")
class MockTwoRounds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = mock_client()
        cls.rec = Recorder(cls.client)
        cls.result = ml.measure(cls.rec, rounds=2, label="mock-test", base="http://testserver")
        cls.summary = cls.result["summary"]

    def test_health_is_recorded_and_mock_is_warned(self):
        h = self.result["health"]
        self.assertEqual((h["ok"], h["mode"]), (True, "mock"))
        self.assertEqual(h["parts"]["reviews"], "합성 데이터")
        self.assertEqual(h["review_service"]["status"], "ok")
        self.assertTrue(self.result["not_live_warning"].startswith("실시간이 아님"))
        self.assertEqual((self.result["label"], self.result["rounds_requested"]), ("mock-test", 2))

    def test_each_round_runs_both_cards_with_the_screens_body(self):
        for rnd in self.result["rounds"]:
            self.assertTrue(rnd["cards_call"]["ok"])
            self.assertEqual([c["kind"] for c in rnd["cards_call"]["cards"]], ["complaint", "promo"])
            complaint, promo = rnd["runs"]
            # mock: 불만 카드는 답글 3 + 공지 1, 홍보 카드는 홍보글 1
            self.assertEqual(sorted(d["kind"] for d in complaint["drafts"]), ["답글"] * 3 + ["재발 방지 공지"])
            self.assertEqual([d["kind"] for d in promo["drafts"]], ["홍보글"])
            self.assertEqual((complaint["source"], promo["source"]), ("seed", "seed"))
        self.assertEqual(self.rec.posts, [("/api/cards/card_ongi_a/run", {"measures": ["M1"]}),
                                          ("/api/cards/card_ongi_b/run", None)] * 2)

    def test_totals_by_kind_and_status(self):
        # mock 저장본(c6/replay/c6_cache_best.json)은 PR #36 에서 새로 만든 것 — 10개 모두 점검 통과.
        # 실패·확인 필요를 세는 규칙은 위 단위 시험(failed_check_names·needs_check_names·status_of)이 본다.
        self.assertEqual(self.summary["counts"], {
            "답글": {PASS: 6, CHECK: 0, FAIL: 0, "합계": 6},
            "재발 방지 공지": {PASS: 2, CHECK: 0, FAIL: 0, "합계": 2},
            "홍보글": {PASS: 2, CHECK: 0, FAIL: 0, "합계": 2}})
        self.assertEqual(self.summary["total"], {PASS: 10, CHECK: 0, FAIL: 0, "합계": 10})
        self.assertEqual(list(self.summary["counts"]), ["답글", "재발 방지 공지", "홍보글"])
        self.assertEqual(self.summary["call_failures"], [])

    def test_totals_agree_with_the_servers_own_flag_count(self):
        """서버의 flagged_count(실패·확인 필요가 있는 글 수)와 우리가 센 확인 필요 + 실패가 같다."""
        flagged = sum(run["flagged_count"] for rnd in self.result["rounds"] for run in rnd["runs"])
        self.assertEqual(flagged, self.summary["total"][CHECK] + self.summary["total"][FAIL])

    def test_which_checks_caught_them(self):
        self.assertEqual(self.summary["failed_checks"], {})     # PR #36 저장본은 모두 통과
        self.assertEqual(self.summary["needs_checks"], {})

    def test_timings_are_recorded_per_call(self):
        self.assertEqual(len(self.summary["cards_seconds"]["values"]), 2)
        self.assertEqual(set(self.summary["run_seconds"]), {"complaint", "promo"})
        self.assertEqual([len(v["values"]) for v in self.summary["run_seconds"].values()], [2, 2])
        for rnd in self.result["rounds"]:
            self.assertGreaterEqual(rnd["cards_call"]["seconds"], 0)

    def test_saved_result_has_lengths_but_no_draft_text(self):
        dumped = json.dumps(self.result, ensure_ascii=False)
        cards = self.client.get("/api/cards").json()["cards"]
        made = [self.client.post(f"/api/cards/{p['card']['card_id']}/run").json() for p in cards]
        rows = {d["draft_id"]: d for rnd in self.result["rounds"] for run in rnd["runs"] for d in run["drafts"]}
        texts = [d for r in made for d in r["drafts"]]
        self.assertEqual(len(texts), 5)
        for d in texts:
            self.assertNotIn(d["text"], dumped)
            self.assertNotIn(d["text"][:20], dumped)
            self.assertEqual(rows[d["draft_id"]]["text_len"], len(d["text"]))

    def test_korean_report(self):
        text = ml.format_report(self.result)
        for part in ("실시간이 아님", "종류", "통과", "확인 필요", "실패", "합계", "답글", "재발 방지 공지", "홍보글", "전체",
                     "호출 실패: 0건", "걸린 점검(실패): 없음", "걸린 점검(확인 필요): 없음",
                     "/api/cards 걸린 시간(초): ", "중앙값", "카드 실행 걸린 시간(초): 불만 카드 중앙값", "홍보 카드 중앙값"):
            self.assertIn(part, text)
        row = next(line for line in text.splitlines() if line.startswith("답글"))
        self.assertEqual(row.split()[-4:], ["6", "0", "0", "6"])


# ── 호출 실패는 세고 계속한다 ─────────────────────────────────────────
@unittest.skipUnless(HAS_C6, "C6 저장본 없음")
class CallFailures(unittest.TestCase):
    def test_failures_are_counted_and_the_run_goes_on(self):
        plan = {("/api/cards", 1): 500,                      # 1라운드: 카드 목록 실패, 알던 카드도 없음 → 카드 실행도 못 함
                ("/api/cards/card_ongi_b/run", 1): "timeout",  # 2라운드: 홍보 카드가 시간 초과 (카드 목록은 성공)
                ("/api/cards", 3): "timeout",                # 3라운드: 목록 시간 초과 → 2라운드에서 받은 카드로 계속
                ("/api/cards/card_ongi_a/run", 2): 500}      # 3라운드: 불만 카드 서버 오류
        client = Flaky(mock_client(), plan)
        result = ml.measure(client, rounds=3)
        s = result["summary"]
        self.assertEqual([(f["round"], f["call"]) for f in s["call_failures"]], [
            (1, "GET /api/cards"), (1, "카드 실행 전체"), (2, "POST /api/cards/card_ongi_b/run"),
            (3, "GET /api/cards"), (3, "POST /api/cards/card_ongi_a/run")])
        errors = [f["error"] for f in s["call_failures"]]
        self.assertEqual(errors[0], "HTTP 500: 시험용 서버 오류")
        self.assertEqual(errors[2], "시간 초과 (120초)")
        self.assertEqual(errors[3], "시간 초과 (120초)")
        # 성공한 호출만 센다: 2라운드 불만 카드(답글 3 + 공지 1) + 3라운드 홍보 카드(홍보글 1)
        self.assertEqual(s["counts"], {"답글": {PASS: 3, CHECK: 0, FAIL: 0, "합계": 3},
                                       "재발 방지 공지": {PASS: 1, CHECK: 0, FAIL: 0, "합계": 1},
                                       "홍보글": {PASS: 1, CHECK: 0, FAIL: 0, "합계": 1}})
        self.assertEqual(len(s["cards_seconds"]["values"]), 1)       # 성공한 목록 호출은 2라운드 하나
        self.assertEqual(len(result["rounds"]), 3)
        self.assertIn("호출 실패: 5건", ml.format_report(result))

    def test_bad_bodies_and_exceptions_are_failures_too(self):
        plan = {("/api/cards/card_ongi_a/run", 1): "garbage", ("/api/cards/card_ongi_b/run", 1): "boom"}
        result = ml.measure(Flaky(mock_client(), plan), rounds=1)
        self.assertEqual([f["error"] for f in result["summary"]["call_failures"]], ["응답이 JSON 이 아님", "예외 (RuntimeError)"])
        self.assertEqual(result["summary"]["total"]["합계"], 0)

    def test_health_failure_is_reported_and_measuring_continues(self):
        result = ml.measure(Flaky(mock_client(), {("/api/health", 1): 500}), rounds=1)
        self.assertFalse(result["health"]["ok"])
        self.assertIsNone(result["health"]["mode"])
        self.assertIn("읽지 못함", result["not_live_warning"])
        self.assertEqual(result["summary"]["total"]["합계"], 5)
        self.assertIn("/api/health 호출 실패", ml.format_report(result))

    def test_unreachable_server_finishes_with_every_call_failed(self):
        result = ml.measure(AlwaysDown(), rounds=2)
        self.assertEqual(result["summary"]["total"]["합계"], 0)
        self.assertEqual([f["call"] for f in result["summary"]["call_failures"]],
                         ["GET /api/cards", "카드 실행 전체"] * 2)
        self.assertIn("연결 오류 (ConnectError)", ml.format_report(result))


class LiveIsNotWarned(unittest.TestCase):
    def test_live_mode_has_no_warning(self):
        self.assertIsNone(ml.not_live_warning({"mode": "live"}))
        self.assertIn("mode=mock", ml.not_live_warning({"mode": "mock"}))


# ── 명령줄 ──────────────────────────────────────────────────────────
@unittest.skipUnless(HAS_C6, "C6 저장본 없음")
class Cli(unittest.TestCase):
    def run_main(self, argv, client):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ml.main(argv, client=client)
        return code, out.getvalue(), err.getvalue()

    def test_writes_json_and_prints_table(self):
        path = Path(tempfile.mkdtemp()) / "nested" / "out.json"
        code, out, err = self.run_main(["--rounds", "1", "--label", "baseline", "--out", str(path)], mock_client())
        self.assertEqual(code, 0)
        self.assertIn("측정 이름: baseline", out)
        self.assertIn("종류", out)
        self.assertIn("실시간이 아님", err)                    # 시작할 때 진행 로그(stderr)에도 큰 경고
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((saved["label"], saved["rounds_requested"], saved["health"]["mode"]), ("baseline", 1, "mock"))
        self.assertEqual(saved["summary"]["total"]["합계"], 5)
        self.assertEqual(len(saved["rounds"]), 1)

    def test_exit_code_is_1_when_nothing_was_measured(self):
        code, out, _ = self.run_main(["--rounds", "1"], AlwaysDown())
        self.assertEqual(code, 1)
        self.assertIn("호출 실패: 2건", out)

    def test_options_and_defaults(self):
        args = ml.parse_args([])
        self.assertEqual((args.base, args.rounds, args.out, args.label, args.timeout),
                         ("http://127.0.0.1:8540", 5, None, None, 120.0))
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            ml.parse_args(["--rounds", "0"])
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit) as ctx:
            ml.parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        for opt in ("--base", "--rounds", "--out", "--label"):
            self.assertIn(opt, buf.getvalue())


if __name__ == "__main__":
    unittest.main()
