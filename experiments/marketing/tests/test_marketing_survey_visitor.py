"""맞춤 마케팅 서버를 통합 화면 뒤에 붙이며 고친 것 (11/16) — 가짜 응답, 네트워크 없음.

① 지어낸 재료 점검(no_invented_ingredient)이 메뉴 이름 '계란말이'의 '계란'을 지어낸 재료로 보던 오탐, 걸린 낱말을 적는 힌트
② review_promo 가 coupon_promo(PR #55)처럼 합니다체 힌트·코드 보정을 먼저 하고, HCX 호출 실패(예외·error)에도 죽지 않음
③ 방문자별 기록 파일(visitor_id), DELETE /records, /health, 모드(MARKETING_APP_MODE → APP_MODE → 키 유무)와
   mock 이면 키가 있어도 HCX 를 한 번도 부르지 않음

실행 (experiments/marketing 에서):
  python -m pytest -q -s tests/test_marketing_survey_visitor.py      또는      python -m tests.test_marketing_survey_visitor
기록은 시험마다 임시 폴더(MARKETING_RECORDS_DIR)에 쓴다. 리뷰·홍보글 문장은 이 시험을 위해 지어낸 합성 문장이다.
"""

import json
import os
import re
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from shared.sample_scenario import SAMPLE_CARDS, SAMPLE_REVIEWS, SAMPLE_SNAPSHOTS, SAMPLE_STORE, SAMPLE_TONE

from c6 import checks
from c6.contract import build_context
from c6.dummy import OWNER_REPLIES, POLICIES
from c6.output import CALL_FAILED_NOTE
from c6.promo import generate_coupon_promo, generate_review_promo, review_promo_fallback_text
from marketing_survey import records
from marketing_survey.server import app

CTX = build_context(store=SAMPLE_STORE, reviews=list(SAMPLE_REVIEWS), tone=SAMPLE_TONE, cards=list(SAMPLE_CARDS),
                    snapshots=list(SAMPLE_SNAPSHOTS), owner_replies=OWNER_REPLIES, policies=POLICIES)
PROMO_CARD = next(c for c in SAMPLE_CARDS if c.kind == "promo")
MENU = list(SAMPLE_STORE.menu)
STORE = SAMPLE_STORE.store_id
API = "/api/marketing-survey"

EGG = "계란말이"
EGG_GOOD = "오늘 저녁은 폭신한 계란말이로 든든하게 드셔 보세요. 정성껏 부쳐서 따뜻하게 보내드립니다. 편하게 주문해 주시기 바랍니다."
EGG_CHEESE = "오늘 저녁은 치즈를 듬뿍 올린 계란말이로 든든하게 드셔 보세요. 정성껏 부쳐서 따뜻하게 보내드립니다. 편하게 주문해 주시기 바랍니다."
FAIL = {"error": "TimeoutError: The read operation timed out"}
FAKE_KEY = "test-only-not-a-real-key-7f3a"     # 응답에 이 값이 나오면 안 된다
KEY_ENVS = ("CLOVA_API_KEY", "CLOVASTUDIO_API_KEY", "CLOVA_STUDIO_API_KEY", "APP_MODE", "MARKETING_APP_MODE")


def _env(**values):
    """키·모드 환경 변수를 모두 지운 뒤 values 만 넣는다 (기록 폴더는 시험마다 새 임시 폴더)."""
    env = {k: v for k, v in os.environ.items() if k not in KEY_ENVS}
    env[records.RECORDS_DIR_ENV] = tempfile.mkdtemp(prefix="mkt_visitor_")
    env.update(values)
    return patch.dict(os.environ, env, clear=True)


def _fake_call(answer):
    """HCX 가 늘 answer 를 준다고 치는 가짜 clova.call. (함수, 받은 메시지 목록)"""
    seen, lock = [], threading.Lock()

    def fake(key, system, messages, **_):
        with lock:
            seen.append(messages)
        return {"content": answer, "won": 0.01}
    return fake, seen


def _review_promo(fake, menu=EGG):
    with patch("clova.call", side_effect=fake):
        return generate_review_promo(CTX, PROMO_CARD, "k", menu=menu).drafts[0]


# ── ① 지어낸 재료 점검 ─────────────────────────────────────────────

class TestInventedIngredient(unittest.TestCase):
    def test_menu_name_ingredient_is_not_invented(self):
        """'계란말이' 홍보글의 '계란'은 메뉴 이름에 든 재료다 (메뉴 설명이 비어 있어도)."""
        self.assertTrue(checks.invented_ingredient(EGG_GOOD, {}))                     # 예전 방식: 오탐
        self.assertFalse(checks.invented_ingredient(EGG_GOOD, {}, (EGG,)))
        self.assertFalse(checks.invented_ingredient(EGG_GOOD, {}, EGG))                # 문자열 하나도 받는다
        self.assertEqual(checks.invented_ingredient_words(EGG_GOOD, {}, (EGG,), MENU), [])

    def test_really_invented_ingredient_is_still_caught(self):
        self.assertTrue(checks.invented_ingredient(EGG_CHEESE, {}, (EGG,), MENU))
        self.assertEqual(checks.invented_ingredient_words(EGG_CHEESE, {}, (EGG,), MENU), ["치즈"])

    def test_other_menu_name_does_not_hide_an_invented_topping(self):
        """메뉴판에 '계란말이'가 있다고 제육볶음 홍보글에 지어 넣은 '계란'이 통과하면 안 된다."""
        text = "계란을 올린 제육볶음 정식을 추천드립니다."
        self.assertEqual(checks.invented_ingredient_words(text, {}, ("제육볶음 정식",), MENU), ["계란"])

    def test_other_menu_mentioned_is_left_to_only_coupon_menu(self):
        """다른 메뉴 이름이 통째로 나오면 그건 only_coupon_menu 가 잡고, 지어낸 재료로 겹쳐 잡지 않는다."""
        text = "제육볶음 정식과 계란말이를 함께 추천드립니다."
        self.assertFalse(checks.invented_ingredient(text, {}, ("제육볶음 정식",), MENU))
        self.assertFalse(checks.only_coupon_menu_mentioned(text, MENU, "제육볶음 정식"))

    def test_unverified_claim_words(self):
        self.assertEqual(checks.unverified_claim_words("가장 인기 있는 1위 메뉴입니다."), ["가장 인기", "1위"])
        self.assertEqual(checks.unverified_claim_words(EGG_GOOD), [])
        self.assertTrue(checks.has_unverified_claim("많은 분들이 찾으십니다."))

    def test_detail_hints_name_the_words(self):
        text = "치즈를 올린 계란말이는 가장 인기 있는 메뉴입니다."
        hints = checks.promo_detail_hints(
            ["no_invented_ingredient", "no_unverified_claim"], text, menu_names=MENU, coupon_menu=EGG,
            review_texts=[], reviews=[], menu_descriptions={}, menu_label="대표 메뉴", coupon_line=False)
        joined = "\n".join(hints)
        self.assertIn("'치즈'", joined)
        self.assertNotIn("'계란'", joined)
        self.assertIn("'가장 인기'", joined)

    def test_formal_hints_have_no_haeyo_statements(self):
        """합니다체 글의 다시 쓰기 지시에는 '…붙여요.'·'…있어요.' 같은 해요체 설명문을 넣지 않는다 ('~해 주세요' 지시는 괜찮다)."""
        names = ["no_coupon_invented", "no_forbidden_phrase", "no_invented_ingredient", "no_unverified_claim",
                 "no_stiff_words", "promo_formal"]
        haeyo_statement = re.compile(r"(?<![세])요[.)!]*$")
        for hint in checks.fix_hints(names, formal=True):
            for sentence in re.split(r"(?<=[.!?])\s+", hint.strip()):
                with self.subTest(sentence=sentence):
                    self.assertIsNone(haeyo_statement.search(sentence))
                    self.assertNotIn("구어체", sentence)
        coupon_detail = checks.promo_detail_hints(["no_coupon_invented"], "1000원 할인!", menu_names=MENU,
                                                  coupon_menu=EGG, review_texts=[], reviews=[])
        self.assertTrue(coupon_detail and coupon_detail[0].endswith("붙입니다."))


# ── ② review_promo ─────────────────────────────────────────────────

class TestReviewPromo(unittest.TestCase):
    def test_egg_menu_passes_without_rewrite(self):
        fake, seen = _fake_call(EGG_GOOD)
        d = _review_promo(fake)
        self.assertEqual(len(seen), 2)                                   # 후보 2개만, 다시 쓰기 없음
        self.assertTrue(d.checks["no_invented_ingredient"])
        self.assertEqual((d.rewrites, d.checks["used_fallback"], d.checks["ai_part_repaired"]), (0, False, False))
        self.assertEqual(d.text, EGG_GOOD)

    def test_egg_template_passes_its_own_checks(self):
        """다시 쓰기를 다 써도 못 고치면 템플릿 — 템플릿의 '계란말이'도 점검을 통과해야 한다(예전엔 템플릿까지 걸렸다)."""
        fake, seen = _fake_call(EGG_CHEESE)
        d = _review_promo(fake)
        self.assertEqual(len(seen), 4)                                   # 후보 2 + 다시 쓰기 2
        self.assertTrue(d.checks["used_fallback"])
        self.assertEqual(d.text, review_promo_fallback_text(SAMPLE_STORE, EGG))
        self.assertEqual(d.failed_reasons, [])
        self.assertEqual(d.needs_input, [])

    def test_rewrite_uses_formal_hints_and_names_the_word(self):
        fake, seen = _fake_call(EGG_CHEESE)
        _review_promo(fake)
        retry = seen[2][-1]["content"]
        self.assertIn("'치즈'", retry)                                   # 실제로 걸린 낱말
        self.assertIn("합니다체", retry)
        self.assertNotIn("구어체", retry)
        self.assertEqual(seen[2][1]["content"], EGG_CHEESE)              # 손질한 글을 고치게 한다

    def test_code_fix_before_rewrite(self):
        """4번째 문장·딱딱한 말·해요체 어미는 다시 쓰기 전에 코드가 고친다 (추가 호출 없음, ai_part_repaired)."""
        answer = ("오늘 저녁은 폭신한 계란말이로 든든한 한 끼를 즐겨보세요. 정성껏 부쳐서 따뜻하게 보내드릴게요. "
                  "편하게 주문해 주시면 좋겠어요. 이번 기회를 놓치지 마세요!")
        fake, seen = _fake_call(answer)
        d = _review_promo(fake)
        self.assertEqual(len(seen), 2)
        self.assertEqual((d.checks["used_fallback"], d.checks["ai_part_repaired"]), (False, True))
        self.assertTrue(d.checks["promo_formal"])
        self.assertEqual(d.text, "오늘 저녁은 폭신한 계란말이로 든든한 한 끼를 드셔 보세요. 정성껏 부쳐서 따뜻하게 "
                                 "보내드리겠습니다. 편하게 주문해 주시면 좋겠습니다.")

    def test_template_passes_for_every_menu(self):
        """호출이 모두 실패하면 쓰는 템플릿이 메뉴마다 점검을 다 넘는다 (예전 템플릿은 '정성껏'을 되풀이해 늘 걸렸다)."""
        for menu in MENU + [None]:
            with self.subTest(menu=menu), patch("clova.call", side_effect=lambda *a, **k: dict(FAIL)):
                d = generate_review_promo(CTX, PROMO_CARD, "k", menu=menu).drafts[0]
                self.assertEqual(d.failed_reasons, [])
                self.assertEqual(d.needs_input, [CALL_FAILED_NOTE])

    def test_call_exception_does_not_crash(self):
        def boom(*a, **k):
            raise RuntimeError("연결이 끊겼어요")
        with patch("clova.call", side_effect=boom) as call:
            d = generate_review_promo(CTX, PROMO_CARD, "k", menu=EGG).drafts[0]
        self.assertEqual(call.call_count, 2)                             # 후보 2개만, 다시 쓰기 없음
        self.assertEqual(d.text, review_promo_fallback_text(SAMPLE_STORE, EGG))
        self.assertEqual(d.needs_input, [CALL_FAILED_NOTE])
        self.assertEqual(d.failed_reasons, [])
        self.assertFalse(d.checks["used_fallback"])

    def test_error_response_does_not_crash(self):
        with patch("clova.call", side_effect=lambda *a, **k: dict(FAIL)):
            d = generate_review_promo(CTX, PROMO_CARD, "k", menu=EGG).drafts[0]
        self.assertEqual(d.text, review_promo_fallback_text(SAMPLE_STORE, EGG))
        self.assertEqual(d.needs_input, [CALL_FAILED_NOTE])

    def test_one_failed_candidate_uses_the_other(self):
        lock, n = threading.Lock(), {"i": 0}

        def half(*a, **k):
            with lock:
                n["i"] += 1
                i = n["i"]
            if i == 1:
                raise RuntimeError("첫 후보만 실패")
            return {"content": EGG_GOOD}
        with patch("clova.call", side_effect=half):
            d = generate_review_promo(CTX, PROMO_CARD, "k", menu=EGG).drafts[0]
        self.assertEqual(d.text, EGG_GOOD)
        self.assertEqual(d.needs_input, [])

    def test_failed_rewrite_call_keeps_the_ai_text(self):
        def fake(key, system, messages, **_):
            if "수정 지시" in messages[-1]["content"]:
                raise RuntimeError("다시 쓰기만 실패")
            return {"content": EGG_CHEESE}
        with patch("clova.call", side_effect=fake):
            d = generate_review_promo(CTX, PROMO_CARD, "k", menu=EGG).drafts[0]
        self.assertEqual(d.text, EGG_CHEESE)
        self.assertFalse(d.checks["used_fallback"])
        self.assertTrue(d.failed_reasons)

    def test_coupon_promo_uses_the_other_candidate_too(self):
        lock, n = threading.Lock(), {"i": 0}

        def half(*a, **k):
            with lock:
                n["i"] += 1
                i = n["i"]
            return dict(FAIL) if i == 1 else {"content": EGG_GOOD}
        with patch("clova.call", side_effect=half):
            d = generate_coupon_promo(CTX, PROMO_CARD, "k", coupon_menu=EGG).drafts[0]
        self.assertTrue(d.text.startswith(EGG_GOOD))
        self.assertEqual(d.needs_input, [])
        self.assertFalse(d.checks["used_fallback"])


# ── ③ 서버: 방문자·health·모드 ──────────────────────────────────────

def _walk(client, start, answers=(), visitor=None):
    """/step 을 처음부터 걸어 결정 직전 state 를 돌려준다. answers 가 모자라면 첫 보기를 고른다."""
    q = {"visitor_id": visitor} if visitor else {}
    d = client.post(f"{API}/step", params=q, json={"state": None, "answer": None}).json()
    todo = [start, *answers]
    for _ in range(20):
        ans = todo.pop(0) if todo else d["options"][0]["label"]
        d = client.post(f"{API}/step", params=q, json={"state": d["state"], "answer": ans})
        assert d.status_code == 200, d.text
        d = d.json()
        if d["done"]:
            return d["state"]
    raise AssertionError("결정에 닿지 못함")


COUPON_RESULT = ("쿠폰 결과 확인", "100", "10", "2000", "15000", "30%")
STORY = ("가게 이야기 글", "부모님 가게를 물려받아서", "제육볶음 정식", "매일 아침 장을 봐요", "", "")
LEFTOVER = ("남은 재료 팔기", EGG, "3", "다른 메뉴와 세트", "제육볶음 정식")


class TestVisitorRecords(unittest.TestCase):
    def setUp(self):
        self.env = _env()
        self.env.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.env.stop()

    def _coupon_result_plan(self, visitor=None):
        state = _walk(self.client, COUPON_RESULT[0], COUPON_RESULT[1:], visitor)
        q = {"visitor_id": visitor} if visitor else {}
        res = self.client.post(f"{API}/plan", params=q, json={"state": state})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_visitor_records_are_separate(self):
        self._coupon_result_plan("visitorA")
        self.assertTrue(records.records_path(STORE, "visitorA").is_file())
        self.assertFalse(records.records_path(STORE).exists())          # 가게 공용 파일은 그대로
        self.assertTrue(records.records_path(STORE, "visitorA").name.endswith(f"records_{STORE}_visitorA.json"))
        row = records.load(STORE, "visitorA")[0]
        self.assertEqual((row["table"], row["visitor_id"]), (records.COUPON_RUNS, "visitorA"))

        a = self.client.get(f"{API}/report", params={"visitor_id": "visitorA"}).json()
        b = self.client.get(f"{API}/report", params={"visitor_id": "visitorB"}).json()
        self.assertFalse(a["demo"])
        self.assertEqual(a["cost"]["coupon"]["issued"], 100)
        self.assertTrue(b["demo"])                                       # B 는 A 기록을 못 보고 데모
        self.assertFalse(records.records_path(STORE, "visitorB").exists())

    def test_no_visitor_uses_the_old_store_file(self):
        self._coupon_result_plan()
        self.assertTrue(records.records_path(STORE).is_file())
        self.assertEqual(records.records_path(STORE).name, f"records_{STORE}.json")
        self.assertFalse(self.client.get(f"{API}/report").json()["demo"])
        self.assertTrue(self.client.get(f"{API}/report", params={"visitor_id": "someone"}).json()["demo"])

    def test_approve_and_idea_go_to_the_visitor_file(self):
        state = _walk(self.client, "맞춤 홍보 제안", (), "visitorA")
        plan = self.client.post(f"{API}/plan", params={"visitor_id": "visitorA"}, json={"state": state}).json()
        res = self.client.post(f"{API}/approve", params={"visitor_id": "visitorA"},
                               json={"state": state, "session_id": plan["session_id"]})
        self.assertEqual(res.status_code, 200, res.text)
        rows = records.load(STORE, "visitorA")
        self.assertEqual([r["decision"] for r in rows], ["proposed", "approved"])
        self.assertEqual(rows[1]["parent_id"], rows[0]["id"])
        self.assertEqual(records.load(STORE), [])
        report = self.client.get(f"{API}/report", params={"visitor_id": "visitorA"}).json()
        self.assertFalse(report["demo"])
        self.assertTrue(report["activity"]["approved"])

    def test_bad_visitor_id_is_400_everywhere(self):
        bad = ["", "a b", "../x", "x" * 65, "한글", "a/b"]
        paths = [("get", f"{API}/report"), ("get", f"{API}/meta"), ("get", f"{API}/stores"), ("get", f"{API}/health"),
                 ("post", f"{API}/step"), ("delete", f"{API}/records")]
        for value in bad:
            for method, path in paths:
                with self.subTest(value=value, path=path):
                    kw = {"json": {"state": None, "answer": None}} if method == "post" else {}
                    res = getattr(self.client, method)(path, params={"visitor_id": value}, **kw)
                    self.assertEqual(res.status_code, 400, res.text)
                    self.assertIn("visitor_id", res.json()["detail"])
        ok = self.client.get(f"{API}/report", params={"visitor_id": "a" * 64})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.client.post(f"{API}/coupon-calc", params={"visitor_id": "a b"}, json={
            "budget_won": 1, "discount_won": 1, "price_won": 1, "avg_order_won": 1, "margin_pct": 1}).status_code, 400)

    def test_delete_removes_only_that_visitor(self):
        self._coupon_result_plan("visitorA")
        self._coupon_result_plan("visitorB")
        self._coupon_result_plan()
        res = self.client.delete(f"{API}/records", params={"visitor_id": "visitorA"})
        self.assertEqual((res.status_code, res.json()), (200, {"deleted": True}))
        self.assertFalse(records.records_path(STORE, "visitorA").exists())
        self.assertTrue(records.records_path(STORE, "visitorB").is_file())
        self.assertTrue(records.records_path(STORE).is_file())
        again = self.client.delete(f"{API}/records", params={"visitor_id": "visitorA"})
        self.assertEqual((again.status_code, again.json()), (200, {"deleted": False}))   # 없으면 false (오류 아님)
        self.assertTrue(self.client.get(f"{API}/report", params={"visitor_id": "visitorA"}).json()["demo"])

    def test_delete_without_visitor_is_400(self):
        self._coupon_result_plan()
        res = self.client.delete(f"{API}/records")
        self.assertEqual(res.status_code, 400)
        self.assertTrue(records.records_path(STORE).is_file())          # 가게 공용 파일은 지우지 않는다
        self.assertEqual(self.client.delete(f"{API}/records", params={"store": "store_basak", "visitor_id": "v1"})
                         .status_code, 404)

    def test_records_module_rejects_bad_visitor(self):
        with self.assertRaises(ValueError):
            records.records_path(STORE, "../evil")
        with self.assertRaises(ValueError):
            records.delete(STORE, None)


class TestHealthAndMode(unittest.TestCase):
    def _health(self, **env):
        with _env(**env):
            client = TestClient(app)
            a = client.get("/health")
            b = client.get(f"{API}/health")
        self.assertEqual(a.status_code, 200)
        self.assertEqual(a.json(), b.json())
        return a

    def test_health_has_no_key_value(self):
        res = self._health(CLOVA_API_KEY=FAKE_KEY, MARKETING_APP_MODE="mock")
        self.assertNotIn(FAKE_KEY, res.text)
        body = res.json()
        for k in ("status", "service", "mode", "mode_source", "key_present", "demo", "store_id", "records_dir_writable"):
            self.assertIn(k, body)
        self.assertEqual((body["status"], body["service"], body["store_id"]), ("ok", "marketing-survey", STORE))
        self.assertEqual((body["mode"], body["mode_source"], body["key_present"], body["demo"]),
                         ("mock", "MARKETING_APP_MODE", True, True))
        self.assertTrue(body["records_dir_writable"])

    def test_mode_order(self):
        cases = [
            (dict(MARKETING_APP_MODE="live", APP_MODE="mock", CLOVA_API_KEY=FAKE_KEY), ("live", "MARKETING_APP_MODE", False)),
            (dict(APP_MODE="mock", CLOVA_API_KEY=FAKE_KEY), ("mock", "APP_MODE", True)),
            (dict(APP_MODE="live", CLOVA_API_KEY=FAKE_KEY), ("live", "APP_MODE", False)),
            (dict(MARKETING_APP_MODE="replay", APP_MODE="live", CLOVA_API_KEY=FAKE_KEY), ("live", "APP_MODE", False)),
            (dict(CLOVA_API_KEY=FAKE_KEY), ("live", "key", False)),
            ({}, ("mock", "key", True)),
        ]
        for env, want in cases:
            with self.subTest(env={k: ("***" if "KEY" in k else v) for k, v in env.items()}):
                body = self._health(**env).json()
                self.assertEqual((body["mode"], body["mode_source"], body["demo"]), want)

    def test_live_without_key_is_demo_and_says_so(self):
        body = self._health(APP_MODE="live").json()
        self.assertEqual((body["mode"], body["key_present"], body["demo"]), ("live", False, True))
        self.assertTrue(any("CLOVA_API_KEY" in n for n in body["notes"]))

    def test_unwritable_records_dir(self):
        with _env(MARKETING_APP_MODE="mock") as _:
            os.environ[records.RECORDS_DIR_ENV] = "/proc/0/no-such-dir" if os.path.isdir("/proc") else "/dev/null/x"
            body = TestClient(app).get("/health").json()
        self.assertFalse(body["records_dir_writable"])


class TestMockNeverCallsHcx(unittest.TestCase):
    """MARKETING_APP_MODE=mock(또는 APP_MODE=mock)이면 환경에 키가 있어도 clova.call 이 한 번도 불리지 않는다."""

    STORY_JSON = json.dumps({"naver_place": "부모님 가게를 물려받아서 시작했습니다. 매일 아침 장을 봅니다.",
                             "instagram": "부모님 가게를 물려받아서 시작했습니다.\n#동네맛집 #오늘의한끼 #단골환영",
                             "baemin_intro": "부모님 가게를 물려받아서"}, ensure_ascii=False)

    def _run_everything(self, **env):
        """기능 다섯 가지의 plan·generate·approve·idea-try·notice-followup·report 를 모두 부르고 clova.call 횟수를 센다."""
        def fake(key, system, messages, **_):
            return {"content": self.STORY_JSON if "가게 이름:" in messages[0]["content"] else EGG_GOOD, "won": 0.0}
        out = {}
        with _env(**env), patch("clova.call", side_effect=fake) as call:
            client = TestClient(app)
            q = {"visitor_id": "mockcheck"}
            for name, path in (("survey", ("맞춤 홍보 제안",)), ("leftover", LEFTOVER), ("story", STORY),
                               ("coupon_result", COUPON_RESULT)):
                state = _walk(client, path[0], path[1:], "mockcheck")
                plan = client.post(f"{API}/plan", params=q, json={"state": state})
                self.assertEqual(plan.status_code, 200, plan.text)
                out[name] = plan.json()
                if name in ("survey", "coupon_result"):
                    gen = client.post(f"{API}/generate", params=q, json={"state": state})
                    self.assertEqual(gen.status_code, 200, gen.text)
                    out[name + "_generate"] = gen.json()
                if name == "survey":
                    self.assertEqual(client.post(f"{API}/approve", params=q, json={"state": state}).status_code, 200)
                    idea = (plan.json().get("idea") or {}).get("id")
                    if idea:
                        self.assertEqual(client.post(f"{API}/idea-try", params=q,
                                                     json={"state": state, "idea_id": idea, "answer": "예"}).status_code, 200)
                    self.assertEqual(client.post(f"{API}/notice-followup", params=q, json={"state": state}).status_code, 200)
            self.assertEqual(client.get(f"{API}/report", params=q).status_code, 200)
            out["calls"] = call.call_count
        return out

    def test_marketing_mock_with_key_calls_nothing(self):
        out = self._run_everything(MARKETING_APP_MODE="mock", APP_MODE="live", CLOVA_API_KEY=FAKE_KEY)
        self.assertEqual(out["calls"], 0)
        for name in ("survey", "leftover", "story", "coupon_result"):
            self.assertTrue(out[name]["demo"], name)
        self.assertTrue(out["survey_generate"]["demo"])

    def test_app_mode_mock_with_key_calls_nothing(self):
        self.assertEqual(self._run_everything(APP_MODE="mock", CLOVA_API_KEY=FAKE_KEY)["calls"], 0)

    def test_live_with_key_does_call(self):
        """대조군: 같은 경로를 live 로 부르면 가짜 clova.call 이 불린다 (세는 방법이 맞는지 확인)."""
        out = self._run_everything(MARKETING_APP_MODE="live", APP_MODE="mock", CLOVA_API_KEY=FAKE_KEY)
        self.assertGreater(out["calls"], 0)
        self.assertFalse(out["story"]["demo"])
        self.assertIn("부모님 가게를 물려받아서", out["story"]["drafts"]["naver_place_intro"])
        self.assertFalse(out["leftover"]["demo"])

    def test_story_alone_in_mock_calls_nothing(self):
        with _env(MARKETING_APP_MODE="mock", CLOVA_API_KEY=FAKE_KEY), patch("clova.call") as call:
            client = TestClient(app)
            state = _walk(client, STORY[0], STORY[1:])
            body = client.post(f"{API}/plan", json={"state": state}).json()
        self.assertEqual(call.call_count, 0)
        self.assertTrue(body["demo"])
        self.assertIn("부모님 가게를 물려받아서", body["drafts"]["naver_place_intro"])


if __name__ == "__main__":
    unittest.main()
