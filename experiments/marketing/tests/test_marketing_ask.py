"""마케팅 질문 답하기 (POST /api/marketing-survey/ask, marketing_survey/ask.py, 11/21).

통합 서랍의 마케팅 질문은 늘 "맞춤 마케팅의 'OO'에서…" 안내 한 줄이었다. 여기서는
- 질문 종류마다 이 서비스의 보고서·쿠폰 계산·광고 판정으로 만든 근거 카드와 서로 다른 답이 나오는지
- 숫자가 이 서비스 계산(coupon_calc.calc, report.marketing_section)과 같은지
- live 에서 HCX-005 플래너·답 쓰기가 쓰이고, 틀린 플래너 답·근거에 없는 숫자는 규칙·틀 답으로 바뀌는지
를 본다. CLOVA 는 부르지 않는다 (가짜 call).
실행 (experiments/marketing 에서): python -m tests.test_marketing_ask
"""
import os
import re
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from marketing_survey import ask, coupon_calc, records, report, stores
from marketing_survey.server import app

KEY_ENVS = ("CLOVA_API_KEY", "CLOVASTUDIO_API_KEY", "CLOVA_STUDIO_API_KEY", "APP_MODE", "MARKETING_APP_MODE")
STORE = stores.DEFAULT_STORE_ID


def _env(**values):
    env = {k: v for k, v in os.environ.items() if k not in KEY_ENVS}
    env[records.RECORDS_DIR_ENV] = tempfile.mkdtemp(prefix="mkt_ask_")
    env.update(values)
    return patch.dict(os.environ, env, clear=True)


def _fake(plan_reply, write_reply=""):
    """플래너(시스템 글에 '분류기')와 답 쓰기를 나눠 답하는 가짜 clova.call. 부른 순서를 calls 에 적는다."""
    calls = []

    def call(key, system, messages, **kw):
        kind = "plan" if "분류기" in system else "write"
        calls.append((kind, kw.get("model")))
        return {"content": plan_reply if kind == "plan" else write_reply}
    return call, calls


QUESTIONS = ["쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?", "지난번 쿠폰 효과 있었어?", "광고비 월 30만원 괜찮아?",
             "공지 올린 거 효과 있었어?", "단골 늘리려면 뭐 해야 돼?", "새 손님 늘리고 싶어", "객단가 올리는 법",
             "비 오는 날 홍보 뭐 할까?", "남은 재료 어떻게 팔아?", "다음엔 뭐 하면 좋아?", "이번 달 마케팅 정리해줘",
             "제육볶음 정식 가격 얼마야?"]


_REAL_SECTION = report.marketing_section


def _with_records(store_id, period="monthly", today=None, visitor_id=None):
    """기록이 있는 사장님처럼: 보고서의 예시 기록을 실제 기록(demo=False)인 것처럼 돌려준다."""
    return {**_REAL_SECTION(store_id, period, today=today, visitor_id=visitor_id), "demo": False}


def recorded():
    return patch.object(ask.report, "marketing_section", side_effect=_with_records)


class Ask(unittest.TestCase):
    def setUp(self):
        self.env = _env()
        self.env.start()
        self.ctx = stores.get_ctx(STORE)

    def tearDown(self):
        self.env.stop()

    def answer(self, text, key=None, call=None):
        return ask.answer(self.ctx, STORE, None, text, key, **({"call": call} if call else {}))

    def test_parse(self):
        cases = {
            "쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?": ("coupon_calc", 2000, None),
            "예산 20만원으로 3천원 쿠폰 내면? 마진 35%": ("coupon_calc", 3000, 200_000),
            "지난번 쿠폰 효과 있었어?": ("coupon_result", None, None),
            "광고비 월 30만원 괜찮아?": ("ads", None, None),
            "인스타에 뭐 올리면 좋아?": ("ideas_new", None, None),
            "단골 늘리려면 뭐 해야 돼?": ("ideas_repeat", None, None),
            "비 오는 날 홍보 뭐 할까?": ("rainy", None, None),
            "이번 주 마케팅 정리해줘": ("activity", None, None),
        }
        for text, (intent, discount, budget) in cases.items():
            q = ask.parse(text, list(self.ctx.store.menu_prices))
            self.assertEqual((q.intent, q.discount_won, q.budget_won), (intent, discount, budget), text)
        self.assertEqual(ask.parse("예산 20만원으로 3천원 쿠폰 내면? 마진 35%").margin_pct, 35)
        self.assertEqual(ask.parse("광고비 월 30만원 괜찮아?").amount_won, 300_000)
        self.assertEqual(ask.parse("이번 주 마케팅 정리해줘").period, "weekly")

    def test_different_questions_get_different_answers_with_cards(self):
        got = [self.answer(q) for q in QUESTIONS]
        self.assertEqual(len({g["text"] for g in got}), len(QUESTIONS))
        for q, g in zip(QUESTIONS, got):
            cited = set(re.findall(r"\[(F\d+)\]", g["text"]))
            self.assertTrue(g["cards"] and cited and cited <= {c["id"] for c in g["cards"]}, q)
            self.assertEqual((g["method"], g["classified_by"], g["notes"]), ("template", "rules", []), q)

    def test_coupon_numbers_come_from_the_coupon_calculator(self):
        g = self.answer("예산 20만원으로 3천원 쿠폰 내면? 마진 35%")
        r = coupon_calc.calc(200_000, 3000, ask.ASSUME["avg_order_won"], ask.ASSUME["avg_order_won"], 35)
        self.assertIn(f"{r['count']}장", g["text"])
        self.assertIn(f"{r['breakeven_orders']}건 넘으면 본전", g["text"])
        self.assertIn("평균 주문 금액은 가정한 값", g["text"])           # 말하지 않은 값은 가정이라고 말한다
        self.assertTrue(g["cards"][0]["warnings"])

    def test_coupon_without_amount_asks_for_it(self):
        g = self.answer("쿠폰 하면 본전 몇 개야?")
        self.assertIn("할인 금액을 알려 주시면", g["text"])

    def test_report_numbers_match_the_report(self):
        sec = _with_records(STORE)
        cp = sec["cost"]["coupon"]
        with recorded():
            g = self.answer("지난번 쿠폰 효과 있었어?")
            self.assertIn(f"{cp['issued']}장 중 {cp['used']}장", g["text"])
            loss = [a for a in sec["cost"]["ads"] if a["verdict"] == "손해 광고"]
            g = self.answer("배달앱 광고 괜찮아?")
        self.assertTrue(all(a["label"] in g["text"] for a in sec["cost"]["ads"]))
        if loss:
            self.assertTrue(g["text"].startswith(loss[0]["label"]))

    def test_example_records_are_not_read_as_real(self):
        """기록이 없으면 보고서는 예시 기록(demo)을 준다. 종합 리포트가 '–'로 보이듯 서랍도 그 숫자를 말하지 않는다 (11/21)."""
        cp = report.marketing_section(STORE, "monthly")["cost"]["coupon"]
        g = self.answer("지난번 쿠폰 효과 있었어?")
        self.assertIn("기록이 없어요", g["text"])
        self.assertNotIn(f"{cp['issued']}장", g["text"])
        g = self.answer("광고비 월 30만원 괜찮아?")
        self.assertIn("광고 기록이 없어요", g["text"])
        self.assertIn("67건 넘어야 본전", g["text"])            # 말한 금액은 가정한 값으로 계산
        self.assertIn("가정한 값", g["text"])
        g = self.answer("다음엔 뭐 하면 좋아?")
        self.assertIn("아직 마케팅 기록이 없어요", g["text"])

    # live: HCX-005 플래너 · 답 쓰기 ─────────────────────────────
    def test_planner_and_writer_are_hcx_005(self):
        fixed = self.answer("요즘 장사 좀 띄우고 싶은데")
        self.assertEqual(fixed["intent"], "overview")
        call, calls = _fake('{"intent": "ideas_new"}', "")
        g = self.answer("요즘 장사 좀 띄우고 싶은데", key="k", call=call)
        self.assertEqual((g["intent"], g["classified_by"], g["rule_intent"]), ("ideas_new", "hcx", "overview"))
        self.assertEqual(calls, [("plan", "HCX-005"), ("write", "HCX-005")])
        self.assertEqual(g["method"], "template")                  # 빈 답은 점검에서 걸려 틀 답

    def test_model_answer_used_when_it_passes(self):
        with recorded():
            fixed = self.answer("지난번 쿠폰 효과 있었어?")
            m = re.search(r"(\d+)장 중 (\d+)장이 쓰였어요 \(사용률 (\d+)%\)", fixed["text"])
            good = (f"쿠폰을 {m.group(1)}장 냈고 그중 {m.group(2)}장을 손님이 썼어요 (사용률 {m.group(3)}%) [F1]. "
                    "쿠폰 주문으로 본전을 넘겼어요 [F1]. 다음엔 조건을 조금 바꿔 보세요.")
            call, _ = _fake('{"intent": "coupon_result"}', good)
            g = self.answer("지난번 쿠폰 효과 있었어?", key="k", call=call)
        self.assertEqual((g["method"], g["model"], g["text"]), ("hcx", "HCX-005", good))

    def test_bad_model_answers_fall_back(self):
        fixed = self.answer("지난번 쿠폰 효과 있었어?")
        for bad, why in (("쿠폰 99장이 쓰였어요 [F1].", "근거에 없는 숫자 99"), ("무조건 효과 있어요 [F1].", "쓰면 안 되는 말"),
                         ("효과가 있었어요 [F7].", "없는 근거 F7")):
            call, _ = _fake('{"intent": "coupon_result"}', bad)
            g = self.answer("지난번 쿠폰 효과 있었어?", key="k", call=call)
            self.assertEqual((g["method"], g["text"]), ("template", fixed["text"]), bad)
            self.assertTrue(any(why in p for p in g["checks"]), g["checks"])

    def test_bad_planner_keeps_the_rules(self):
        for bad in ('{"intent": "weather"}', "쿠폰 결과예요"):
            call, _ = _fake(bad, "")
            g = self.answer("요즘 장사 좀 띄우고 싶은데", key="k", call=call)   # 규칙이 못 고른 질문만 플래너에 묻는다
            self.assertEqual((g["intent"], g["classified_by"]), ("overview", "rules"))
            self.assertTrue(g["plan_note"])

    def test_model_error_falls_back(self):
        def call(key, system, messages, **kw):
            return {"error": "HTTP 500"}
        g = self.answer("지난번 쿠폰 효과 있었어?", key="k", call=call)
        self.assertEqual((g["method"], g["classified_by"]), ("template", "rules"))

    # 11/22 PR #75 live 확인 반영 ──────────────────────────────────
    def test_flipped_meaning_is_blocked(self):
        """손해 광고를 '해 보세요'라고 권한 답 (숫자는 맞음) → 틀 답의 '손해·다시 보기'가 답에 없어 막힌다."""
        with recorded():
            fixed = self.answer("배달앱 광고 괜찮아?")
            if "다시 보" not in fixed["text"]:
                self.skipTest("이 가게 예시 기록에는 손해 광고가 없음")
            nums = re.findall(r"\d[\d,]*원", fixed["text"])[:2]
            bad = f"쿠팡이츠 광고는 주문 1건 광고비가 {nums[0]}, 남는 돈이 {nums[1]}예요 [F1]. 효과가 있어 보여 시도해 보세요."
            call, _ = _fake('{"intent": "ads"}', bad)
            g = self.answer("배달앱 광고 괜찮아?", key="k", call=call)
        self.assertEqual(g["method"], "template")
        self.assertTrue(any("다른 뜻" in p or "빠짐" in p for p in g["checks"]), g["checks"])

    def test_small_numbers_are_checked_too(self):
        """예전엔 1·2·3 은 늘 통과했다."""
        with recorded():
            fixed = self.answer("지난번 쿠폰 효과 있었어?")
            bad = fixed["text"].replace("[F1].", "[F1]. 3번 더 해 보세요.", 1)
            probs = ask.check_answer(bad, self.answer("지난번 쿠폰 효과 있었어?")["cards"], fixed["text"])
        self.assertTrue(any("근거에 없는 숫자 3" in p for p in probs), probs)

    def test_formal_style_and_bold_marks(self):
        with recorded():
            fixed = self.answer("지난번 쿠폰 효과 있었어?")
            first = re.split(r"(?<=[.!?])\s+", fixed["text"])[0]
            call, _ = _fake('{}', "**" + first.replace("쓰였어요", "사용되었습니다") + " 본전을 넘겼습니다. 감사합니다.")
            g = self.answer("지난번 쿠폰 효과 있었어?", key="k", call=call)
            self.assertIn("해요체가 아님", g["checks"])
            call, _ = _fake('{}', "**" + fixed["text"] + "**")
            g = self.answer("지난번 쿠폰 효과 있었어?", key="k", call=call)
        self.assertEqual(g["method"], "hcx")
        self.assertNotIn("**", g["text"])

    def test_planner_only_when_rules_found_nothing(self):
        call, calls = _fake('{"intent": "leftover"}', "")
        g = self.answer("지난번 쿠폰 효과 있었어?", key="k", call=call)
        self.assertEqual((g["intent"], g["classified_by"]), ("coupon_result", "rules"))
        self.assertEqual([k for k, _ in calls], ["write"])

    def test_leftover_example_is_not_a_drink(self):
        g = self.answer("남은 재료 어떻게 팔아?")
        self.assertNotRegex(g["text"], r"콜라|사이다|음료")


class Endpoint(unittest.TestCase):
    def setUp(self):
        self.env = _env(MARKETING_APP_MODE="mock", CLOVA_API_KEY="test-only-not-a-real-key")
        self.env.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.env.stop()

    def test_ask(self):
        res = self.client.post("/api/marketing-survey/ask", json={"text": "쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?"},
                               params={"visitor_id": "u-mktask01"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual((body["intent"], body["method"], body["demo"]), ("coupon_calc", "template", True))   # mock: 키가 있어도 안 부름
        self.assertNotIn("test-only-not-a-real-key", res.text)
        self.assertEqual(self.client.post("/api/marketing-survey/ask", json={"text": ""}).status_code, 422)
        self.assertEqual(self.client.post("/api/marketing-survey/ask", json={"text": "x"},
                                          params={"visitor_id": "bad id!"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
