"""설문 맞춤 마케팅 — 규칙(decide)·설명(explain)·실행(execute) 전체 경로. AI 호출 없음(decide/explain)
이거나 --mock·저장본(execute)만 쓴다.

실행 방법
  python -m pytest tests/test_marketing_survey.py -q
  python -m tests.test_marketing_survey
"""

import unittest
from datetime import date
from types import SimpleNamespace

from c6.contract import build_context
from c6.dummy import OWNER_REPLIES, POLICIES
from marketing_survey import (
    adspend, coupon_calc, coupon_result, flow, ideas, leftover, notice_followup, playbooks, story,
)
from marketing_survey.decide import build_follow_up_strategy, decide
from marketing_survey.execute import build_plan, execute_strategy
from marketing_survey.explain import explain_strategy
from marketing_survey.models import SurveyAnswers
from marketing_survey.survey import answers_from_raw
from shared.contracts import ReviewRecord
from shared.sample_scenario import (
    SAMPLE_CARDS, SAMPLE_REVIEWS, SAMPLE_SNAPSHOTS, SAMPLE_STORE, SAMPLE_TONE,
)

DEFAULT_CTX = build_context(
    store=SAMPLE_STORE, reviews=list(SAMPLE_REVIEWS), tone=SAMPLE_TONE,
    cards=list(SAMPLE_CARDS), snapshots=list(SAMPLE_SNAPSHOTS),
    owner_replies=OWNER_REPLIES, policies=POLICIES,
)


def _late_delivery_ctx():
    """H_LATE 가 뜨도록 '늦은 배달' 리뷰 2건만 있는 가게 ctx(카드·지표는 비워서 다른 가설과 안 섞음)."""
    reviews = [
        ReviewRecord(
            review_id="rv_late_001", store_id=SAMPLE_STORE.store_id,
            text="배달이 너무 늦게 왔어요", created_at="2026-11-01T19:00:00+09:00",
            rating=2, sentiment="negative", negative_topics=["late_delivery"], topics=["late_delivery"],
        ),
        ReviewRecord(
            review_id="rv_late_002", store_id=SAMPLE_STORE.store_id,
            text="주문한 음식이 많이 늦었어요", created_at="2026-11-05T19:30:00+09:00",
            rating=2, sentiment="negative", negative_topics=["late_delivery"], topics=["late_delivery"],
        ),
    ]
    return build_context(
        store=SAMPLE_STORE, reviews=reviews, tone=SAMPLE_TONE, cards=[], snapshots=[],
        owner_replies=OWNER_REPLIES, policies=POLICIES,
    )


def _store_only_ctx():
    """H_STORE_ONLY 가 뜨도록(상권 지표 없음 + 반복 불만 카드 있음) ctx."""
    return build_context(
        store=SAMPLE_STORE, reviews=list(SAMPLE_REVIEWS), tone=SAMPLE_TONE,
        cards=list(SAMPLE_CARDS), snapshots=[],
        owner_replies=OWNER_REPLIES, policies=POLICIES,
    )


def _assert_budget_ok(case, answers, plan):
    case.assertLessEqual(plan.used_budget, plan.total_budget, plan.strategies)
    case.assertEqual(plan.used_budget, sum(s.budget_won for s in plan.strategies))
    for s in plan.strategies:
        if s.discount_won:
            price = DEFAULT_CTX.store.menu_prices.get(answers.discount_menu, 0)
            case.assertLessEqual(s.discount_won, answers.max_discount_won)
            case.assertLessEqual(s.discount_won, int(price * 0.3) + 1)  # 반올림 여유
        if s.count and s.discount_won:
            case.assertLessEqual(s.count * s.discount_won, plan.total_budget)


class TestDecideRules(unittest.TestCase):
    """우선순위(decide.py 맨 위 주석) 규칙별로 1개씩."""

    def test_h_late_confirmed_is_fix_first_no_coupon(self):
        ctx = _late_delivery_ctx()
        answers = SurveyAnswers(
            budget_won=100_000, goal="새 손님", discount_menu="제육볶음 정식", max_discount_won=5_000,
        )
        plan = decide(ctx, answers, confirms={"H_LATE": "예"})

        self.assertTrue(any(h.id == "H_LATE" for h in plan.hypotheses))
        self.assertEqual({s.type for s in plan.strategies}, {"fix_first"})
        self.assertEqual(plan.strategies[0].source_hypothesis, "H_LATE")
        self.assertEqual(plan.strategies[0].follow_up, "")
        self.assertEqual(plan.used_budget, 0)
        _assert_budget_ok(self, answers, plan)

    def test_h_repeat_confirmed_is_fix_first_with_follow_up(self):
        answers = SurveyAnswers(
            budget_won=100_000, goal="새 손님", discount_menu="제육볶음 정식", max_discount_won=5_000,
            discount_allowed=True,
        )
        plan = decide(DEFAULT_CTX, answers, confirms={"H_REPEAT": "예"})

        self.assertTrue(any(h.id == "H_REPEAT" for h in plan.hypotheses))
        strat = plan.strategies[0]
        self.assertEqual(strat.type, "fix_first")
        self.assertEqual(strat.source_hypothesis, "H_REPEAT")
        self.assertEqual(strat.follow_up, "reorder_coupon")
        self.assertEqual(plan.used_budget, 0)
        _assert_budget_ok(self, answers, plan)

    def test_h_repeat_without_budget_has_no_follow_up(self):
        answers = SurveyAnswers(budget_won=0, goal="새 손님")
        plan = decide(DEFAULT_CTX, answers, confirms={"H_REPEAT": "예"})

        self.assertEqual(plan.strategies[0].follow_up, "")

    def test_h_store_only_confirmed_is_fix_first_no_coupon(self):
        ctx = _store_only_ctx()
        answers = SurveyAnswers(
            budget_won=100_000, goal="새 손님", discount_menu="제육볶음 정식", max_discount_won=5_000,
        )
        plan = decide(ctx, answers, confirms={"H_STORE_ONLY": "예"})

        self.assertTrue(any(h.id == "H_STORE_ONLY" for h in plan.hypotheses))
        strat = plan.strategies[0]
        self.assertEqual(strat.type, "fix_first")
        self.assertEqual(strat.source_hypothesis, "H_STORE_ONLY")
        self.assertEqual(plan.used_budget, 0)
        _assert_budget_ok(self, answers, plan)

    def test_discount_not_allowed_is_review_promo(self):
        answers = SurveyAnswers(
            budget_won=100_000, goal="새 손님", discount_menu="제육볶음 정식", max_discount_won=5_000,
            discount_allowed=False,
        )
        plan = decide(DEFAULT_CTX, answers, confirms={})

        self.assertEqual({s.type for s in plan.strategies}, {"review_promo"})
        self.assertEqual(plan.used_budget, 0)
        _assert_budget_ok(self, answers, plan)

    def test_budget_zero_is_review_promo(self):
        answers = SurveyAnswers(budget_won=0, goal="새 손님")
        plan = decide(DEFAULT_CTX, answers, confirms={})

        self.assertEqual({s.type for s in plan.strategies}, {"review_promo"})
        _assert_budget_ok(self, answers, plan)

    def test_capacity_tight_goal_coupon_uses_offpeak_timing(self):
        answers = SurveyAnswers(
            budget_won=100_000, goal="새 손님", discount_menu="제육볶음 정식", max_discount_won=5_000,
            capacity="빠듯함",
        )
        plan = decide(DEFAULT_CTX, answers, confirms={})

        coupon = next(s for s in plan.strategies if s.type == "offpeak_coupon")
        self.assertIn("한가한", coupon.timing)
        _assert_budget_ok(self, answers, plan)

    def test_goal_based_coupon_types(self):
        for goal, expected_type in (
            ("남는 재료 처리", "leftover_deal"),
            ("재주문", "reorder_coupon"),
            ("새 손님", "offpeak_coupon"),
        ):
            answers = SurveyAnswers(
                budget_won=100_000, goal=goal, discount_menu="제육볶음 정식", max_discount_won=5_000,
            )
            plan = decide(DEFAULT_CTX, answers, confirms={})
            self.assertTrue(any(s.type == expected_type for s in plan.strategies), goal)
            _assert_budget_ok(self, answers, plan)

    def test_no_coupon_possible_falls_back_to_no_action(self):
        answers = SurveyAnswers(
            budget_won=100_000, goal="새 손님", discount_menu=None, max_discount_won=0,
        )
        plan = decide(DEFAULT_CTX, answers, confirms={})

        self.assertEqual({s.type for s in plan.strategies}, {"no_action"})
        self.assertTrue(plan.needs_input)


class TestAreaDropVsCapacity(unittest.TestCase):
    """H_AREA_DROP 은 쿠폰 시간대만 조정한다 — 수용력이 빠듯하면 그게 우선이고 note 에 이유가 남는다."""

    def test_area_drop_confirmed_prefers_declining_timing(self):
        answers = SurveyAnswers(
            budget_won=100_000, goal="새 손님", discount_menu="제육볶음 정식", max_discount_won=5_000,
            capacity="충분",
        )
        plan = decide(DEFAULT_CTX, answers, confirms={"H_AREA_DROP": "예"})

        coupon = next(s for s in plan.strategies if s.type == "offpeak_coupon")
        self.assertIn("하락", coupon.timing)
        self.assertIn("기준:", coupon.reason)  # basis_label 이 근거로 남는다
        self.assertEqual(coupon.note, "")

    def test_capacity_tight_wins_over_area_drop(self):
        answers = SurveyAnswers(
            budget_won=100_000, goal="새 손님", discount_menu="제육볶음 정식", max_discount_won=5_000,
            capacity="빠듯함",
        )
        plan = decide(DEFAULT_CTX, answers, confirms={"H_AREA_DROP": "예"})

        coupon = next(s for s in plan.strategies if s.type == "offpeak_coupon")
        self.assertIn("한가한", coupon.timing)
        self.assertIn("수용력", coupon.note)


class TestChannelFilter(unittest.TestCase):
    """설문 channels 로 안 쓰는 채널은 전략에서 빠진다."""

    def test_unused_channels_are_excluded(self):
        answers = SurveyAnswers(
            budget_won=100_000, goal="새 손님", discount_menu="제육볶음 정식", max_discount_won=5_000,
            channels=["naver_place"],
        )
        plan = decide(DEFAULT_CTX, answers, confirms={})

        coupon = next(s for s in plan.strategies if s.type == "offpeak_coupon")
        self.assertEqual(coupon.channels, ["naver_place"])
        self.assertNotIn("baemin", coupon.channels)

    def test_no_channels_chosen_keeps_all_store_channels(self):
        answers = SurveyAnswers(
            budget_won=100_000, goal="새 손님", discount_menu="제육볶음 정식", max_discount_won=5_000,
        )
        plan = decide(DEFAULT_CTX, answers, confirms={})

        coupon = next(s for s in plan.strategies if s.type == "offpeak_coupon")
        self.assertEqual(coupon.channels, list(SAMPLE_STORE.channels))


class TestExplain(unittest.TestCase):
    def test_explain_is_three_lines_with_metric_and_no_effect_numbers(self):
        answers = SurveyAnswers(
            budget_won=100_000, goal="재주문", discount_menu="제육볶음 정식", max_discount_won=5_000,
        )
        plan = decide(DEFAULT_CTX, answers, confirms={})
        lines = explain_strategy(plan.strategies[0])

        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("왜 이 방식:"))
        self.assertIn("추정", lines[1])
        self.assertEqual(lines[2], "측정 지표: 재주문 수")
        for line in lines:
            self.assertNotIn("매출 증가", line)
            self.assertNotIn("%p", line)

    def test_explain_shows_follow_up_as_fourth_line(self):
        answers = SurveyAnswers(budget_won=100_000, goal="새 손님", discount_allowed=True)
        plan = decide(DEFAULT_CTX, answers, confirms={"H_REPEAT": "예"})
        lines = explain_strategy(plan.strategies[0])

        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[3], "공지 먼저 → 승인 뒤 재주문 쿠폰")


class TestExecuteReplay(unittest.TestCase):
    """key=None(CLOVA_API_KEY 없음) -> 저장본(c6/replay) 재생만 쓴다. live 호출 없음."""

    def test_h_repeat_fix_first_generates_notice(self):
        answers = SurveyAnswers(budget_won=100_000, goal="새 손님", discount_allowed=True)
        plan = decide(DEFAULT_CTX, answers, confirms={"H_REPEAT": "예"})

        _, draft, todo = execute_strategy(DEFAULT_CTX, plan.strategies[0], None)
        self.assertIsNone(todo)
        self.assertIsNotNone(draft)
        self.assertEqual(draft.generator, "prevention_notice")

    def test_coupon_strategy_generates_coupon_promo(self):
        answers = SurveyAnswers(
            budget_won=100_000, goal="재주문", discount_menu="제육볶음 정식", max_discount_won=5_000,
        )
        plan = decide(DEFAULT_CTX, answers, confirms={})

        _, draft, todo = execute_strategy(DEFAULT_CTX, plan.strategies[0], None)
        self.assertIsNone(todo)
        self.assertIsNotNone(draft)
        self.assertEqual(draft.generator, "coupon_promo")

    def test_h_late_and_store_only_are_not_generated(self):
        late_ctx = _late_delivery_ctx()
        store_only_ctx = _store_only_ctx()
        cases = [
            (late_ctx, SurveyAnswers(budget_won=100_000, goal="새 손님"), {"H_LATE": "예"}),
            (store_only_ctx, SurveyAnswers(budget_won=100_000, goal="새 손님"), {"H_STORE_ONLY": "예"}),
        ]
        for ctx, answers, confirms in cases:
            plan = decide(ctx, answers, confirms=confirms)
            _, draft, todo = execute_strategy(ctx, plan.strategies[0], None)
            self.assertIsNone(draft, plan.strategies[0].type)
            self.assertIsNotNone(todo, plan.strategies[0].type)

    def test_notice_and_reply_replay_pass_m1_chosen_measure(self):
        """key=None 재생 경로도 key 있을 때와 같은 모양으로 run_card 에 M1 을 넘긴다
        (저장본이 나중에 chosen_measures 를 쓰게 바뀌어도 조용히 달라지지 않도록)."""
        from unittest.mock import patch

        from marketing_survey.execute import NOTICE_CHOSEN_MEASURES, _run_notice, _run_reply

        answers = SurveyAnswers(budget_won=100_000, goal="새 손님", discount_allowed=True)
        plan = decide(DEFAULT_CTX, answers, confirms={"H_REPEAT": "예"})

        with patch("marketing_survey.execute.run_card") as mock_run_card:
            mock_run_card.return_value.drafts = []
            _run_notice(DEFAULT_CTX, None, "HCX-005")
            _run_reply(DEFAULT_CTX, None, "HCX-005")

        self.assertEqual(mock_run_card.call_count, 2)
        for call in mock_run_card.call_args_list:
            self.assertEqual(call.kwargs.get("chosen_measures"), NOTICE_CHOSEN_MEASURES)

    def test_review_promo_generates_draft_without_coupon_words(self):
        answers = SurveyAnswers(budget_won=0, goal="새 손님")
        plan = decide(DEFAULT_CTX, answers, confirms={})

        _, draft, todo = execute_strategy(DEFAULT_CTX, plan.strategies[0], None)
        self.assertIsNone(todo)
        self.assertIsNotNone(draft)
        self.assertEqual(draft.generator, "review_promo")
        for word in ("할인", "쿠폰", "코드", "반값", "%"):
            self.assertNotIn(word, draft.text)


class TestPlaybooks(unittest.TestCase):
    """marketing_survey.playbooks — 결정별 할 일 목록(언제·무엇을·어디서·몇 분). AI 호출 없음."""

    _TODAY = date(2026, 11, 15)  # 일요일

    def test_h_repeat_steps_cover_notice_reply_memo_recheck(self):
        answers = SurveyAnswers(budget_won=100_000, goal="새 손님", discount_allowed=True, weekly_hours=5)
        plan = decide(DEFAULT_CTX, answers, confirms={"H_REPEAT": "예"})
        strategy = plan.strategies[0]

        pb = playbooks.build_playbook(DEFAULT_CTX, strategy, answers, today=self._TODAY)

        step_ids = [s["step_id"] for s in pb["steps"]]
        self.assertEqual(step_ids, ["notice", "reply", "pack_memo", "recheck"])
        self.assertEqual(pb["steps"][0]["when"], "오늘")
        self.assertEqual(pb["steps"][3]["when"], "11/29(일)")  # 오늘 + 14일
        self.assertIn("같은 불만 리뷰 수", pb["measure"])

    def test_h_late_steps_have_no_coupon(self):
        answers = SurveyAnswers(budget_won=100_000, goal="새 손님", weekly_hours=5)
        plan = decide(_late_delivery_ctx(), answers, confirms={"H_LATE": "예"})
        strategy = plan.strategies[0]

        pb = playbooks.build_playbook(_late_delivery_ctx(), strategy, answers, today=self._TODAY)

        self.assertEqual([s["step_id"] for s in pb["steps"]], ["notice", "peak_time", "recheck"])
        self.assertTrue(all(s["generator"] != "coupon_promo" for s in pb["steps"]))

    def test_review_promo_steps_have_naver_and_baemin_with_char_limit(self):
        answers = SurveyAnswers(budget_won=0, goal="새 손님")
        plan = decide(DEFAULT_CTX, answers, confirms={})
        strategy = plan.strategies[0]

        pb = playbooks.build_playbook(DEFAULT_CTX, strategy, answers, today=self._TODAY)

        step_by_id = {s["step_id"]: s for s in pb["steps"]}
        self.assertEqual(step_by_id["naver_notice"]["generator"], "review_promo")
        self.assertEqual(step_by_id["baemin_intro"]["max_chars"], 40)

    def test_coupon_steps_include_create_and_measure(self):
        answers = SurveyAnswers(
            budget_won=100_000, goal="재주문", discount_menu="제육볶음 정식", max_discount_won=5_000,
            weekly_hours=5,
        )
        plan = decide(DEFAULT_CTX, answers, confirms={})
        strategy = plan.strategies[0]

        pb = playbooks.build_playbook(DEFAULT_CTX, strategy, answers, today=self._TODAY)

        self.assertEqual(
            [s["step_id"] for s in pb["steps"]],
            ["coupon_values", "coupon_promo_post", "coupon_create", "measure"],
        )
        self.assertIn("쿠폰 사용 수", pb["measure"])

    def test_channel_filter_drops_steps_tied_to_unused_channel(self):
        answers = SurveyAnswers(budget_won=0, goal="새 손님", channels=["baemin"])
        plan = decide(DEFAULT_CTX, answers, confirms={})
        strategy = plan.strategies[0]

        pb = playbooks.build_playbook(DEFAULT_CTX, strategy, answers, today=self._TODAY)

        step_ids = [s["step_id"] for s in pb["steps"]]
        self.assertIn("baemin_intro", step_ids)
        self.assertNotIn("naver_notice", step_ids)  # naver_place 를 안 골라서 빠짐

    def test_weekly_hours_one_or_less_keeps_only_first_two_steps(self):
        answers = SurveyAnswers(budget_won=100_000, goal="새 손님", discount_allowed=True, weekly_hours=1)
        plan = decide(DEFAULT_CTX, answers, confirms={"H_REPEAT": "예"})
        strategy = plan.strategies[0]

        pb = playbooks.build_playbook(DEFAULT_CTX, strategy, answers, today=self._TODAY)

        self.assertEqual(len(pb["steps"]), 2)
        # 짧아져도 measure(언제 무엇을 비교)는 그대로 남아 있어야 한다
        self.assertIn("같은 불만 리뷰 수", pb["measure"])

    def test_weekly_hours_above_one_keeps_all_steps(self):
        answers = SurveyAnswers(budget_won=100_000, goal="새 손님", discount_allowed=True, weekly_hours=5)
        plan = decide(DEFAULT_CTX, answers, confirms={"H_REPEAT": "예"})
        strategy = plan.strategies[0]

        pb = playbooks.build_playbook(DEFAULT_CTX, strategy, answers, today=self._TODAY)

        self.assertEqual(len(pb["steps"]), 4)


class TestBuildPlan(unittest.TestCase):
    """marketing_survey.execute.build_plan — playbook 의 generator 를 실제로 돌려 drafts 를 채운다.
    key=None(저장본/코드 템플릿)만 쓴다 — live 호출 없음."""

    _TODAY = date(2026, 11, 15)

    def test_review_promo_plan_has_draft_for_naver_step_no_live_call(self):
        answers = SurveyAnswers(budget_won=0, goal="새 손님")
        plan = decide(DEFAULT_CTX, answers, confirms={})
        strategy = plan.strategies[0]

        out = build_plan(DEFAULT_CTX, strategy, answers, None, today=self._TODAY)

        self.assertEqual(out["title"], strategy.title)
        self.assertIn("naver_notice", out["drafts"])
        self.assertIsNone(out["coupon_card"])
        self.assertIn("측정:", out["measure"])

    def test_coupon_plan_has_coupon_card_and_draft_from_replay(self):
        answers = SurveyAnswers(
            budget_won=100_000, goal="재주문", discount_menu="제육볶음 정식", max_discount_won=5_000,
        )
        plan = decide(DEFAULT_CTX, answers, confirms={})
        strategy = plan.strategies[0]

        out = build_plan(DEFAULT_CTX, strategy, answers, None, today=self._TODAY)

        self.assertIsNotNone(out["coupon_card"])
        self.assertEqual(out["coupon_card"]["menu"], "제육볶음 정식")
        self.assertIn("coupon_promo_post", out["drafts"])
        # 8. 평균 주문 금액·남는 비율을 안 물었으면(기본 0) 건당 이익이 0 -> 본전 주문 수는 못 구함
        self.assertIsNone(out["coupon_card"]["breakeven_orders"])

    def test_coupon_plan_breakeven_orders_uses_avg_order_and_margin(self):
        """8. 본전 주문 수 = ceil(최대 할인 비용(=strategy.budget_won) ÷ 건당 이익)."""
        answers = SurveyAnswers(
            budget_won=100_000, goal="재주문", discount_menu="제육볶음 정식", max_discount_won=5_000,
            avg_order_won=15_000, margin_pct=30,
        )
        plan = decide(DEFAULT_CTX, answers, confirms={})
        strategy = plan.strategies[0]

        out = build_plan(DEFAULT_CTX, strategy, answers, None, today=self._TODAY)

        profit_per_order_won = adspend.profit_per_order(15_000, 30)
        expected = adspend.breakeven_orders(strategy.budget_won, profit_per_order_won)
        self.assertIsNotNone(expected)
        self.assertEqual(out["coupon_card"]["breakeven_orders"], expected)

    def test_h_repeat_plan_has_notice_and_reply_drafts_from_replay(self):
        answers = SurveyAnswers(budget_won=100_000, goal="새 손님", discount_allowed=True)
        plan = decide(DEFAULT_CTX, answers, confirms={"H_REPEAT": "예"})
        strategy = plan.strategies[0]

        out = build_plan(DEFAULT_CTX, strategy, answers, None, today=self._TODAY)

        self.assertIn("notice", out["drafts"])
        self.assertIn("reply", out["drafts"])

    def test_mocked_live_call_threads_discount_into_review_promo_text(self):
        from unittest.mock import patch

        answers = SurveyAnswers(budget_won=0, goal="새 손님")
        plan = decide(DEFAULT_CTX, answers, confirms={})
        strategy = plan.strategies[0]

        def _mock_call(key, system, messages, model="HCX-005", **kw):
            return {"content": "정성껏 준비한 메뉴를 소개합니다.", "won": 0.01, "tokens": 10, "seconds": 0.1}

        with patch("clova.call", side_effect=_mock_call):
            out = build_plan(DEFAULT_CTX, strategy, answers, "fake-key", today=self._TODAY)

        self.assertIn("naver_notice", out["drafts"])
        for word in ("할인", "쿠폰", "코드", "반값", "%"):
            self.assertNotIn(word, out["drafts"]["naver_notice"])

    def test_h_late_plan_uses_fixed_code_template_draft(self):
        from marketing_survey.execute import LATE_NOTICE_TEMPLATE

        ctx = _late_delivery_ctx()
        answers = SurveyAnswers(budget_won=100_000, goal="새 손님")
        plan = decide(ctx, answers, confirms={"H_LATE": "예"})
        strategy = plan.strategies[0]

        out = build_plan(ctx, strategy, answers, None, today=self._TODAY)

        self.assertEqual(out["drafts"]["notice"], LATE_NOTICE_TEMPLATE)
        self.assertEqual(len(LATE_NOTICE_TEMPLATE.splitlines()), 4)
        self.assertIn("피크", LATE_NOTICE_TEMPLATE)

    def test_h_repeat_notice_requires_m1_keywords_even_with_vague_ai_response(self):
        from unittest.mock import patch

        answers = SurveyAnswers(budget_won=100_000, goal="새 손님", discount_allowed=True)
        plan = decide(DEFAULT_CTX, answers, confirms={"H_REPEAT": "예"})
        strategy = plan.strategies[0]

        def _vague_call(key, system, messages, model="HCX-005", **kw):
            # 조치 없는 벙문("더 신경 쓰겠습니다") — M1 핵심어(주문서·대조/확인)가 전혀 없다
            return {
                "content": (
                    "최근 포장 품목이 빠진 일이 있었습니다.\n"
                    "불편을 드려 죄송합니다.\n"
                    "오늘부터 비슷한 일이 반복되지 않도록 더 신경 쓰겠습니다.\n"
                    "필요한 점이 있으면 요청사항에 적어 주시기 바랍니다."
                ),
                "won": 0.01, "tokens": 10, "seconds": 0.1,
            }

        with patch("clova.call", side_effect=_vague_call):
            out = build_plan(DEFAULT_CTX, strategy, answers, "fake-key", today=self._TODAY)

        self.assertIn("notice", out["drafts"])
        self.assertIn("주문서", out["drafts"]["notice"])

    def test_baemin_intro_uses_short_first_sentence_as_is(self):
        from unittest.mock import patch

        answers = SurveyAnswers(budget_won=0, goal="새 손님")
        plan = decide(DEFAULT_CTX, answers, confirms={})
        strategy = plan.strategies[0]

        def _short_first_sentence(key, system, messages, model="HCX-005", **kw):
            return {
                "content": "정성 가득 메뉴입니다. 오늘도 맛있게 준비했습니다.",
                "won": 0.01, "tokens": 10, "seconds": 0.1,
            }

        with patch("clova.call", side_effect=_short_first_sentence):
            out = build_plan(DEFAULT_CTX, strategy, answers, "fake-key", today=self._TODAY)

        self.assertEqual(out["drafts"]["baemin_intro"], "정성 가득 메뉴입니다.")

    def test_baemin_intro_falls_back_to_template_when_first_sentence_too_long(self):
        from unittest.mock import patch

        answers = SurveyAnswers(budget_won=0, goal="새 손님")
        plan = decide(DEFAULT_CTX, answers, confirms={})
        strategy = plan.strategies[0]

        def _long_first_sentence(key, system, messages, model="HCX-005", **kw):
            # 마침표 없이 40자를 넘는 한 문장 — 글자 수로 자르면 단어 중간이 잘린다
            return {
                "content": "오늘도 변함없이 정성스럽게 준비한 맛있는 메뉴를 손님들께 소개해 드립니다.",
                "won": 0.01, "tokens": 10, "seconds": 0.1,
            }

        with patch("clova.call", side_effect=_long_first_sentence):
            out = build_plan(DEFAULT_CTX, strategy, answers, "fake-key", today=self._TODAY)

        intro = out["drafts"]["baemin_intro"]
        self.assertNotIn("오늘도 변함없이", intro)
        self.assertTrue(intro.endswith("정성껏 만들어 따뜻하게 보내드립니다."), intro)


class TestDiscountThreadedToPromo(unittest.TestCase):
    """설문이 정한 할인액이 c6.promo.generate_coupon_promo 의 coupon_discount 인자로 그대로 넘어가는지
    (clova.call 을 --mock 식으로 흉내 내 live 호출 없이 확인)."""

    def test_discount_won_and_menu_are_passed_through(self):
        from unittest.mock import patch
        from marketing_survey.execute import PROMO_CARD

        answers = SurveyAnswers(
            budget_won=200_000, goal="재주문", discount_menu="된장찌개", max_discount_won=3_000,
        )
        plan = decide(DEFAULT_CTX, answers, confirms={})
        strat = plan.strategies[0]
        self.assertEqual(strat.menu, "된장찌개")
        expected_discount = min(3_000, int(8_000 * 0.3))
        self.assertEqual(strat.discount_won, expected_discount)

        def _mock_call(key, system, messages, model="HCX-005", **kw):
            return {"content": "된장찌개는 깊은 맛이 특징입니다.", "won": 0.01, "tokens": 10, "seconds": 0.1}

        with patch("clova.call", side_effect=_mock_call):
            _, draft, _ = execute_strategy(DEFAULT_CTX, strat, "fake-key")

        self.assertIn(f"{expected_discount:,}원", draft.text)
        self.assertIn("된장찌개", draft.text)
        self.assertEqual(PROMO_CARD.card_id, "card_sample_b")


class TestVirtualStoreScenarios(unittest.TestCase):
    """가상 매장 5개 시나리오의 기대 결정(decide 만, 실행은 안 함)."""

    def test_low_budget_new_customer(self):
        answers = SurveyAnswers(budget_won=0, goal="새 손님")
        plan = decide(DEFAULT_CTX, answers, confirms={})
        self.assertEqual({s.type for s in plan.strategies}, {"review_promo"})

    def test_reorder_goal(self):
        answers = SurveyAnswers(
            budget_won=100_000, goal="재주문", discount_menu="제육볶음 정식", max_discount_won=5_000,
        )
        plan = decide(DEFAULT_CTX, answers, confirms={})
        self.assertTrue(any(s.type == "reorder_coupon" for s in plan.strategies))

    def test_discount_not_allowed(self):
        answers = SurveyAnswers(
            budget_won=100_000, goal="객단가", discount_menu="제육볶음 정식", max_discount_won=5_000,
            discount_allowed=False,
        )
        plan = decide(DEFAULT_CTX, answers, confirms={})
        self.assertEqual({s.type for s in plan.strategies}, {"review_promo"})

    def test_solo_owner_short_on_time(self):
        answers = SurveyAnswers(
            budget_won=50_000, goal="객단가", discount_menu="계란말이", max_discount_won=2_000,
            capacity="빠듯함", weekly_hours=1,
        )
        plan = decide(DEFAULT_CTX, answers, confirms={})
        coupon = next(s for s in plan.strategies if s.type == "offpeak_coupon")
        self.assertIn("한가한", coupon.timing)

    def test_repeated_missing_item_complaints(self):
        answers = SurveyAnswers(budget_won=100_000, goal="새 손님", discount_allowed=True)
        plan = decide(DEFAULT_CTX, answers, confirms={"H_REPEAT": "예"})
        self.assertEqual({s.type for s in plan.strategies}, {"fix_first"})
        self.assertEqual(plan.strategies[0].follow_up, "reorder_coupon")


def _pick(options: list[dict], label: str) -> dict:
    return next(o for o in options if o["label"] == label)


def _walk(ctx, start_node: str, state: dict, choices: list, require_decision: bool = True) -> str:
    """start_node 에서 choices(라벨 순서대로, 멀티선택 노드는 라벨 리스트)를 고른다.
    state 를 그 자리에서 바꾸고, 멈춘 노드 id(완주했으면 DECISION)를 돌려준다."""
    node_id = start_node
    for label in choices:
        node = flow.NODES[node_id]
        if node.get("multi"):
            options = flow.node_options(node_id, ctx, state)
            values = [o["value"] for o in options if o["label"] in label]
            flow.apply_channels(state, values)
            node_id = flow.DECISION
            break
        options = flow.node_options(node_id, ctx, state)
        option = _pick(options, label)
        flow.apply_option(state, option)
        node_id = option["next"]
        if node_id == flow.DECISION:
            break
    if require_decision:
        assert node_id == flow.DECISION, f"DECISION 에 못 닿음 (멈춘 노드: {node_id})"
    return node_id


class TestChatFlowPaths(unittest.TestCase):
    """경로 4개가 기대한 결정에 도착하는지(흐름 데이터 + decide() 양쪽 다 거친다)."""

    def test_missing_item_then_notice_then_followup_coupon(self):
        state = {"raw": {}, "confirms": {}}
        _walk(DEFAULT_CTX, "repeat_complaint", state, ["예", "포장 누락"])
        answers = answers_from_raw(state["raw"])
        plan = decide(DEFAULT_CTX, answers, confirms=state["confirms"])

        self.assertEqual(plan.strategies[0].type, "fix_first")
        self.assertEqual(plan.strategies[0].source_hypothesis, "H_REPEAT")

        # 공지 승인 뒤 "재주문 쿠폰도 해 볼까요?" -> 예 -> 쿠폰 질문(예산부터) 이어짐
        menu_label = next(iter(DEFAULT_CTX.store.menu_prices))
        menu_options = flow.node_options("menu", DEFAULT_CTX, state)
        menu_choice_label = next(o["label"] for o in menu_options if menu_label in o["label"])
        follow_up_state = {"raw": {}, "confirms": {}}
        stopped_at = _walk(
            DEFAULT_CTX, flow.FOLLOW_UP_START, follow_up_state,
            ["100,000원", "예", menu_choice_label], require_decision=False,
        )
        self.assertEqual(stopped_at, "max_discount")
        max_discount_options = flow.node_options("max_discount", DEFAULT_CTX, follow_up_state)
        avg_amount_options = flow.node_options("coupon_avg_amount", DEFAULT_CTX, follow_up_state)
        _walk(
            DEFAULT_CTX, "max_discount", follow_up_state,
            [max_discount_options[0]["label"], avg_amount_options[0]["label"], "20%", "충분", ["네이버 플레이스"]],
        )
        follow_up_answers = answers_from_raw(follow_up_state["raw"])
        strategy, note = build_follow_up_strategy(DEFAULT_CTX, follow_up_answers)

        self.assertIsNotNone(strategy, note)
        self.assertEqual(strategy.type, "reorder_coupon")

    def test_late_delivery_path(self):
        state = {"raw": {}, "confirms": {}}
        _walk(DEFAULT_CTX, "repeat_complaint", state, ["예", "배달 지연"])
        answers = answers_from_raw(state["raw"])
        plan = decide(DEFAULT_CTX, answers, confirms=state["confirms"])

        self.assertEqual(plan.strategies[0].type, "fix_first")
        self.assertEqual(plan.strategies[0].source_hypothesis, "H_LATE")
        # 배달 지연 경로는 재주문 쿠폰으로 안 이어진다(포장 누락/H_REPEAT 만 이어짐)
        self.assertNotEqual(plan.strategies[0].source_hypothesis, "H_REPEAT")

    def test_budget_zero_path(self):
        state = {"raw": {}, "confirms": {}}
        _walk(DEFAULT_CTX, "repeat_complaint", state, ["아니요", "새 손님", "아니요", "0원(지금은 안 씀)"])
        answers = answers_from_raw(state["raw"])
        plan = decide(DEFAULT_CTX, answers, confirms=state["confirms"])

        self.assertEqual({s.type for s in plan.strategies}, {"review_promo"})

    def test_discount_not_allowed_path(self):
        state = {"raw": {}, "confirms": {}}
        _walk(
            DEFAULT_CTX, "repeat_complaint", state,
            ["아니요", "새 손님", "아니요", "100,000원", "아니요"],
        )
        answers = answers_from_raw(state["raw"])
        plan = decide(DEFAULT_CTX, answers, confirms=state["confirms"])

        self.assertEqual({s.type for s in plan.strategies}, {"review_promo"})


class TestChatFlowReachesEnd(unittest.TestCase):
    """모든 노드가 DECISION 에 닿는지(고아 노드·무한 루프 없음)."""

    def test_every_node_is_reachable_and_terminates(self):
        visited: set[str] = set()

        # adspend_apps 뒤는 고른 앱 수에 따라 adspend_spend_entry/orders_entry 를 오가는 동적
        # 루프라(흐름 데이터 자체가 사이클), 이 재귀 탐색으로는 못 따라간다 — 도달 가능한 노드로만
        # 바로 표시한다(실제 동작은 TestAdSpendFeature 의 서버 경로 테스트가 따로 확인한다).
        _ADSPEND_DYNAMIC_NODES = {
            "adspend_apps", "adspend_spend_entry", "adspend_orders_entry",
            "adspend_avg_amount", "adspend_avg_amount_custom", "adspend_margin",
        }

        def _explore(node_id: str, state: dict, depth: int = 0):
            self.assertLess(depth, 20, "사이클 의심(깊이 초과)")
            visited.add(node_id)
            node = flow.NODES[node_id]
            if node_id in _ADSPEND_DYNAMIC_NODES:
                visited.update(_ADSPEND_DYNAMIC_NODES)
                return
            if node.get("free_input"):
                nxt = node["next"]
                if nxt != flow.DECISION:
                    _explore(nxt, state, depth + 1)
                return
            if node_id == "channels":
                return  # 멀티선택 노드 — 다음은 항상 DECISION
            for option in flow.node_options(node_id, DEFAULT_CTX, state):
                branch = {"raw": dict(state["raw"]), "confirms": dict(state["confirms"])}
                flow.apply_option(branch, option)
                nxt = option["next"]
                if nxt != flow.DECISION:
                    _explore(nxt, branch, depth + 1)

        _explore(flow.START, {"raw": {}, "confirms": {}})

        self.assertEqual(visited, set(flow.all_node_ids()))


class TestServerAPI(unittest.TestCase):
    """FastAPI 서버 — 상태는 클라이언트가 들고 다닌다(서버 저장 없음). live 호출 없음(키 없으면 저장본)."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from marketing_survey.server import app

        cls.client = TestClient(app)

    def _step(self, state, answer):
        res = self.client.post("/api/marketing-survey/step", json={"state": state, "answer": answer})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_missing_item_path_reaches_result_and_approve_leads_to_coupon_question(self):
        data = self._step(None, None)
        self.assertEqual(data["state"]["node"], "start")
        data = self._step(data["state"], "맞춤 홍보 제안")
        self.assertEqual(data["state"]["node"], "repeat_complaint")
        self.assertEqual(data["state"]["mode"], "survey")
        self.assertFalse(data["done"])

        data = self._step(data["state"], "예")
        self.assertEqual(data["state"]["node"], "complaint_type")

        data = self._step(data["state"], "포장 누락")
        self.assertTrue(data["done"])
        self.assertEqual(data["state"]["node"], "DECISION")
        self.assertEqual(data["state"]["confirms"].get("H_REPEAT"), "예")
        state = data["state"]

        res = self.client.post("/api/marketing-survey/result", json={"state": state})
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["strategy"]["type"], "fix_first")
        self.assertEqual(body["strategy"]["source_hypothesis"], "H_REPEAT")
        self.assertEqual(len(body["explain"]), 3)

        res = self.client.post("/api/marketing-survey/generate", json={"state": state})
        self.assertEqual(res.status_code, 200, res.text)
        gen = res.json()
        self.assertTrue(gen["demo"])  # CLOVA_API_KEY 없음 -> 저장본
        self.assertIsNotNone(gen["text"])
        self.assertIn("포장", gen["text"])

        res = self.client.post("/api/marketing-survey/approve", json={"state": state, "draft_id": gen["draft_id"]})
        self.assertEqual(res.status_code, 200, res.text)
        approved = res.json()
        self.assertTrue(approved["follow_up"])
        self.assertEqual(approved["state"]["node"], "budget")
        self.assertEqual(approved["state"]["mode"], "follow_up")
        self.assertTrue(any("재주문" in m for m in approved["bot_messages"]))
        self.assertTrue(any(o["label"] == "100,000원" for o in approved["options"]))

    def test_discount_not_allowed_path(self):
        data = self._step(None, None)
        data = self._step(data["state"], "맞춤 홍보 제안")
        data = self._step(data["state"], "아니요")  # repeat_complaint -> goal
        self.assertEqual(data["state"]["node"], "goal")
        data = self._step(data["state"], "새 손님")
        self.assertEqual(data["state"]["node"], "area_question")
        data = self._step(data["state"], "아니요")
        self.assertEqual(data["state"]["node"], "budget")
        data = self._step(data["state"], "100,000원")
        self.assertEqual(data["state"]["node"], "discount_allowed")
        data = self._step(data["state"], "아니요")
        self.assertTrue(data["done"])

        res = self.client.post("/api/marketing-survey/result", json={"state": data["state"]})
        body = res.json()
        self.assertEqual(body["strategy"]["type"], "review_promo")

    def test_same_answer_does_not_repeat_the_same_question(self):
        """'포장 누락'을 누르면 같은 질문(complaint_type)이 반복되지 않고 노드가 반드시 바뀐다."""
        data = self._step(None, None)
        data = self._step(data["state"], "맞춤 홍보 제안")
        data = self._step(data["state"], "예")
        before_node = data["state"]["node"]
        self.assertEqual(before_node, "complaint_type")

        data = self._step(data["state"], "포장 누락")
        after_node = data["state"]["node"]

        self.assertNotEqual(after_node, before_node)
        self.assertEqual(after_node, "DECISION")
        self.assertTrue(data["done"])
        self.assertEqual(data["bot_messages"], [])
        self.assertEqual(data["options"], [])

        # 이미 DECISION 에 닿은(그래프에 없는) 노드로 다시 답을 보내면 조용히 반복하는 대신 에러가 난다
        res = self.client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "포장 누락"},
        )
        self.assertEqual(res.status_code, 400)


class TestStartScreen(unittest.TestCase):
    """0. 첫 화면 — 5개 보기 중 하나를 고르면 그 기능의 첫 질문으로 간다."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from marketing_survey.server import app

        cls.client = TestClient(app)

    def test_start_has_five_options_and_each_leads_somewhere(self):
        res = self.client.post("/api/marketing-survey/step", json={"state": None, "answer": None})
        data = res.json()
        self.assertEqual(data["state"]["node"], "start")
        labels = [o["label"] for o in data["options"]]
        self.assertEqual(
            labels, ["맞춤 홍보 제안", "남은 재료 팔기", "광고비 점검", "가게 이야기 글", "쿠폰 결과 확인"],
        )

    def test_leftover_option_sets_leftover_mode(self):
        res = self.client.post("/api/marketing-survey/step", json={"state": None, "answer": None})
        state = res.json()["state"]
        res = self.client.post(
            "/api/marketing-survey/step", json={"state": state, "answer": "남은 재료 팔기"},
        )
        data = res.json()
        self.assertEqual(data["state"]["mode"], "leftover")
        self.assertEqual(data["state"]["node"], "leftover_ingredient")
        self.assertIsNotNone(data["input"])


class TestBudgetAllocation(unittest.TestCase):
    """1. 모든 실행 계획 step 에 cost_krw 가 있고, 합계가 예산을 넘지 않는다."""

    _TODAY = date(2026, 11, 15)

    def test_all_steps_have_cost_krw_and_posting_steps_are_zero(self):
        answers = SurveyAnswers(budget_won=0, goal="새 손님")
        plan = decide(DEFAULT_CTX, answers, confirms={})
        pb = playbooks.build_playbook(DEFAULT_CTX, plan.strategies[0], answers, today=self._TODAY)

        for step in pb["steps"]:
            self.assertIn("cost_krw", step)
        self.assertEqual(pb["total_cost_krw"], 0)  # review_promo — 글 올리기만, 전부 0원

    def test_coupon_plan_total_cost_matches_budget_used_and_not_over_budget(self):
        answers = SurveyAnswers(
            budget_won=100_000, goal="재주문", discount_menu="제육볶음 정식", max_discount_won=5_000,
            weekly_hours=5,
        )
        plan = decide(DEFAULT_CTX, answers, confirms={})
        strategy = plan.strategies[0]
        pb = playbooks.build_playbook(DEFAULT_CTX, strategy, answers, today=self._TODAY)

        self.assertEqual(pb["total_cost_krw"], strategy.budget_won)
        self.assertLessEqual(pb["total_cost_krw"], answers.budget_won)
        self.assertFalse(pb["over_budget"])


class TestLeftoverFeature(unittest.TestCase):
    """2. 남은 재료 팔기 — "어떻게 팔까요?" 3갈래(세트/이 메뉴만 할인/추천) + 세트는 사장님이
    고른 메뉴만 들어가는지(묻지 않은 메뉴가 자동으로 세트에 들어가던 버그 재발 방지)."""

    def test_bundle_price_is_90_percent_rounded_to_100_and_uses_chosen_pair_only(self):
        store = DEFAULT_CTX.store
        menu_items = list(store.menu_prices.items())
        item, partner = menu_items[0][0], menu_items[1][0]
        bundle = leftover.bundle_price(store, item, partner)

        self.assertEqual(bundle["menus"], [item, partner])
        total = store.menu_prices[item] + store.menu_prices[partner]
        self.assertEqual(bundle["original_won"], total)
        expected = int(round(total * 0.9 / 100)) * 100
        self.assertEqual(bundle["bundle_won"], expected)
        self.assertEqual(bundle["bundle_won"] % 100, 0)

    def test_bundle_mode_without_chosen_partner_falls_back_to_no_bundle(self):
        """leftover_bundle_menu 를 안 골랐으면(파트너 없음) 세트를 지어내지 않는다."""
        menu = next(iter(DEFAULT_CTX.store.menu_prices))
        raw = {"leftover_item": menu, "leftover_portions": 3, "leftover_mode": "bundle"}
        out = leftover.build_leftover_plan(DEFAULT_CTX, raw, None)

        self.assertIsNone(out["bundle"])
        self.assertEqual(out["title"], "오늘의 추천")

    def test_bundle_mode_only_includes_the_chosen_partner_menu(self):
        """세트면 사장님이 고른 메뉴(leftover_bundle_menu) 만 들어가야 한다 — 다른 메뉴가
        자동으로 들어가면 안 된다."""
        menu_items = list(DEFAULT_CTX.store.menu_prices.items())
        item, partner = menu_items[0][0], menu_items[1][0]
        other_menus = [m for m, _ in menu_items if m not in (item, partner)]
        raw = {
            "leftover_item": item, "leftover_portions": 3,
            "leftover_mode": "bundle", "leftover_bundle_menu": partner,
        }
        out = leftover.build_leftover_plan(DEFAULT_CTX, raw, None)

        self.assertEqual(out["title"], "오늘만 세트")
        self.assertEqual(set(out["bundle"]["menus"]), {item, partner})
        for other in other_menus:
            self.assertNotIn(other, out["bundle"]["menus"])
            self.assertNotIn(other, out["drafts"]["leftover_post"])

    def test_discount_only_mode_has_no_bundle(self):
        menu = next(iter(DEFAULT_CTX.store.menu_prices))
        raw = {"leftover_item": menu, "leftover_portions": 3, "leftover_mode": "discount_only"}
        out = leftover.build_leftover_plan(DEFAULT_CTX, raw, None)

        self.assertEqual(out["title"], "이 메뉴만 할인")
        self.assertIsNone(out["bundle"])
        self.assertNotIn("세트", out["drafts"]["leftover_post"])

    def test_no_discount_mode_produces_today_recommendation(self):
        menu = next(iter(DEFAULT_CTX.store.menu_prices))
        raw = {"leftover_item": menu, "leftover_portions": 3, "leftover_mode": "no_discount"}
        out = leftover.build_leftover_plan(DEFAULT_CTX, raw, None)

        self.assertEqual(out["title"], "오늘의 추천")
        self.assertIn("오늘의 추천", out["drafts"]["leftover_post"])
        self.assertNotIn("세트", out["drafts"]["leftover_post"])

    def test_leftover_bundle_menu_options_exclude_the_chosen_item(self):
        """'어떤 메뉴와 묶을까요?' 보기에는 이미 고른 남은 재료(메뉴) 가 없어야 한다."""
        menu = next(iter(DEFAULT_CTX.store.menu_prices))
        state = {"raw": {"leftover_item": menu}, "confirms": {}}
        options = flow.node_options("leftover_bundle_menu", DEFAULT_CTX, state)
        labels = [o["label"] for o in options]
        self.assertNotIn(menu, labels)
        self.assertTrue(labels)

    def test_leftover_chat_path_bundle_reaches_decision(self):
        from fastapi.testclient import TestClient
        from marketing_survey.server import app

        client = TestClient(app)
        data = client.post("/api/marketing-survey/step", json={"state": None, "answer": None}).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "남은 재료 팔기"},
        ).json()
        menu_items = list(DEFAULT_CTX.store.menu_prices.items())
        item, partner = menu_items[0][0], menu_items[1][0]
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": item},
        ).json()
        self.assertEqual(data["state"]["node"], "leftover_portions")
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "3"},
        ).json()
        self.assertEqual(data["state"]["node"], "leftover_sell_mode")
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "다른 메뉴와 세트"},
        ).json()
        self.assertEqual(data["state"]["node"], "leftover_bundle_menu")
        self.assertNotIn(item, [o["label"] for o in data["options"]])
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": partner},
        ).json()
        self.assertTrue(data["done"])

        res = client.post("/api/marketing-survey/plan", json={"state": data["state"]})
        body = res.json()
        self.assertEqual(body["title"], "오늘만 세트")
        self.assertEqual(set(body["bundle"]["menus"]), {item, partner})

    def test_leftover_chat_path_discount_only_reaches_decision(self):
        from fastapi.testclient import TestClient
        from marketing_survey.server import app

        client = TestClient(app)
        data = client.post("/api/marketing-survey/step", json={"state": None, "answer": None}).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "남은 재료 팔기"},
        ).json()
        menu = next(iter(DEFAULT_CTX.store.menu_prices))
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": menu},
        ).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "3"},
        ).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "이 메뉴만 할인"},
        ).json()
        self.assertEqual(data["state"]["node"], "leftover_discount_pct")
        discount_label = data["options"][0]["label"]
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": discount_label},
        ).json()
        self.assertTrue(data["done"])

        res = client.post("/api/marketing-survey/plan", json={"state": data["state"]})
        body = res.json()
        self.assertEqual(body["title"], "이 메뉴만 할인")
        self.assertIsNone(body["bundle"])
        self.assertIsNotNone(body["discount_tile"])
        self.assertLess(body["discount_tile"]["sale_won"], body["discount_tile"]["original_won"])


class TestCouponCalc(unittest.TestCase):
    """3. 쿠폰 계산 — calc() 경계값. 예측(주문 수·매출 증가) 없이 지금 조건 숫자만 계산한다."""

    def test_zero_budget_gives_zero_count_and_zero_cost(self):
        out = coupon_calc.calc(0, 1_000, 10_000, 15_000, 30)
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["max_cost_won"], 0)
        self.assertEqual(out["remaining_won"], 0)
        self.assertEqual(out["breakeven_orders"], 0)

    def test_zero_discount_does_not_divide_by_zero(self):
        out = coupon_calc.calc(100_000, 0, 10_000, 15_000, 30)
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["max_cost_won"], 0)
        self.assertEqual(out["discount_pct"], 0)

    def test_budget_not_evenly_divisible_leaves_remainder_in_remaining(self):
        out = coupon_calc.calc(10_500, 2_000, 10_000, 15_000, 30)
        self.assertEqual(out["count"], 5)
        self.assertEqual(out["max_cost_won"], 10_000)
        self.assertEqual(out["remaining_won"], 500)

    def test_breakeven_orders_uses_profit_per_order_and_ceils(self):
        out = coupon_calc.calc(100_000, 2_000, 10_000, 15_000, 30)
        profit_per_order_won = adspend.profit_per_order(15_000, 30)
        expected = adspend.breakeven_orders(out["max_cost_won"], profit_per_order_won)
        self.assertEqual(out["breakeven_orders"], expected)

    def test_discount_pct_rounds_from_price(self):
        out = coupon_calc.calc(100_000, 2_000, 10_000, 15_000, 30)
        self.assertEqual(out["discount_pct"], 20)


class TestCouponCalcAPI(unittest.TestCase):
    """3. POST /api/marketing-survey/coupon-calc — 슬라이더가 호출하는 바로 그 계산."""

    def test_coupon_calc_endpoint_matches_calc_function(self):
        from fastapi.testclient import TestClient
        from marketing_survey.server import app

        client = TestClient(app)
        body = {
            "budget_won": 100_000, "discount_won": 2_000, "price_won": 10_000,
            "avg_order_won": 15_000, "margin_pct": 30,
        }
        res = client.post("/api/marketing-survey/coupon-calc", json=body)
        self.assertEqual(res.status_code, 200)
        expected = coupon_calc.calc(**body)
        self.assertEqual(res.json(), expected)


class TestAdSpendFeature(unittest.TestCase):
    """3. 광고비 점검 — 고른 앱만 묻고, 건당 광고비 vs 건당 이익으로 손해/주의/괜찮음을 가른다. AI 없음."""

    def test_cost_per_order_basic(self):
        self.assertEqual(adspend.cost_per_order(150_000, 30), 5_000)
        self.assertIsNone(adspend.cost_per_order(150_000, 0))

    def test_profit_per_order_uses_avg_amount_and_margin(self):
        self.assertEqual(adspend.profit_per_order(15_000, 30), 4_500)

    def test_judge_loss_caution_ok_thresholds(self):
        profit = 2_000
        self.assertEqual(adspend.judge(2_000, profit), adspend.VERDICT_LOSS)   # 건당 광고비 >= 이익
        self.assertEqual(adspend.judge(1_200, profit), adspend.VERDICT_CAUTION)  # 이익의 50~100%
        self.assertEqual(adspend.judge(500, profit), adspend.VERDICT_OK)
        self.assertIsNone(adspend.judge(None, profit))  # 주문 수 0 등 계산 불가

    def test_breakeven_orders_ceils_and_handles_zero_profit(self):
        """8. 본전 주문 수 = ceil(비용 ÷ 건당 이익). 예측 문장이 아니라 "본전이 되려면 N건"에만 쓴다."""
        self.assertEqual(adspend.breakeven_orders(20_000, 4_500), 5)  # ceil(4.44) = 5
        self.assertEqual(adspend.breakeven_orders(0, 4_500), 0)
        self.assertIsNone(adspend.breakeven_orders(20_000, 0))

    def test_only_chosen_apps_appear_in_table(self):
        raw = {
            "adspend_apps": ["baemin", "yogiyo"],
            "adspend_baemin_spend": 150_000, "adspend_baemin_orders": 20,
            "adspend_yogiyo_spend": 10_000, "adspend_yogiyo_orders": 50,
            "adspend_coupangeats_spend": 999_999, "adspend_coupangeats_orders": 1,  # 안 고름 -> 무시돼야 함
            "adspend_avg_amount_won": 15_000, "adspend_margin_pct": 30,
        }
        out = adspend.build_adspend_table(DEFAULT_CTX, raw)
        channels = {r["channel"] for r in out["table"]}
        self.assertEqual(channels, {"baemin", "yogiyo"})

    def test_high_cost_channel_is_flagged_and_low_cost_is_not(self):
        raw = {
            "adspend_apps": ["baemin", "yogiyo"],
            "adspend_baemin_spend": 100_000, "adspend_baemin_orders": 10,  # 건당 10,000원 (손해)
            "adspend_yogiyo_spend": 1_000, "adspend_yogiyo_orders": 1_000,  # 건당 1원 (괜찮음)
            "adspend_avg_amount_won": 15_000, "adspend_margin_pct": 30,  # 건당 이익 4,500원
        }
        out = adspend.build_adspend_table(DEFAULT_CTX, raw)
        by_channel = {r["channel"]: r for r in out["table"]}

        self.assertEqual(by_channel["baemin"]["verdict"], adspend.VERDICT_LOSS)
        self.assertEqual(by_channel["yogiyo"]["verdict"], adspend.VERDICT_OK)
        self.assertIn(adspend.TODO_LOWER_BID, out["todos"])
        self.assertIn("배민", out["summary"])

    def test_no_flag_when_all_channels_within_threshold(self):
        raw = {
            "adspend_apps": ["baemin"],
            "adspend_baemin_spend": 1_000, "adspend_baemin_orders": 1_000,
            "adspend_avg_amount_won": 15_000, "adspend_margin_pct": 30,
        }
        out = adspend.build_adspend_table(DEFAULT_CTX, raw)
        self.assertEqual(out["todos"], [])

    def test_adspend_chat_path_validates_min_spend_and_orders(self):
        from fastapi.testclient import TestClient
        from marketing_survey.server import app

        client = TestClient(app)
        data = client.post("/api/marketing-survey/step", json={"state": None, "answer": None}).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "광고비 점검"},
        ).json()
        self.assertEqual(data["state"]["node"], "adspend_apps")

        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": ["baemin"]},
        ).json()
        self.assertEqual(data["state"]["node"], "adspend_spend_entry")

        # 1,000원 미만 -> 같은 질문을 다시 받는다
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "500"},
        ).json()
        self.assertEqual(data["state"]["node"], "adspend_spend_entry")
        self.assertIn("1,000원 이상", data["bot_messages"][0])

        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "150000"},
        ).json()
        self.assertEqual(data["state"]["node"], "adspend_orders_entry")

        # 주문 수 0 -> 같은 질문을 다시 받는다
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "0"},
        ).json()
        self.assertEqual(data["state"]["node"], "adspend_orders_entry")

        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "20"},
        ).json()
        self.assertEqual(data["state"]["node"], "adspend_avg_amount")

        avg_options = [o["label"] for o in data["options"]]
        self.assertIn("직접 입력", avg_options)
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": avg_options[0]},
        ).json()
        self.assertEqual(data["state"]["node"], "adspend_margin")

        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "30%"},
        ).json()
        self.assertTrue(data["done"])

        res = client.post("/api/marketing-survey/plan", json={"state": data["state"]})
        body = res.json()
        self.assertEqual(body["table"][0]["channel"], "baemin")
        self.assertEqual(body["table"][0]["spend_won"], 150_000)
        self.assertEqual(body["table"][0]["orders"], 20)


class TestStoryFeature(unittest.TestCase):
    """4. 가게 이야기 글 — 답에 없는 사실(연도·수상 등)이 들어가면 실패로 본다. AI 호출 없음."""

    def test_check_no_invented_facts_passes_for_text_within_source(self):
        source = "부모님 식당을 물려받아서 2015년에 다시 열었습니다 좋은 재료만 씁니다"
        text = "2015년에 다시 열었습니다. 좋은 재료만 씁니다."
        self.assertTrue(story.check_no_invented_facts(text, source))

    def test_check_no_invented_facts_fails_on_invented_year(self):
        source = "부모님 식당을 물려받아서 다시 열었습니다"
        text = "1998년부터 이어온 전통 있는 맛집입니다."
        self.assertFalse(story.check_no_invented_facts(text, source))

    def test_check_no_invented_facts_fails_on_invented_award_word(self):
        source = "맛있게 만들고 싶어서 시작했습니다"
        text = "대회에서 수상한 경력이 있습니다."
        self.assertFalse(story.check_no_invented_facts(text, source))

    def test_build_story_plan_uses_only_owner_answers(self):
        raw = {"story_reason": "부모님 식당을 물려받은 것", "story_keep": "국산 재료만 쓰는 것"}
        out = story.build_story_plan(raw, today=date(2026, 11, 15))

        self.assertIn("naver_place_intro", out["drafts"])
        self.assertIn("instagram_intro", out["drafts"])
        self.assertIn("baemin_intro", out["drafts"])
        self.assertIn("부모님 식당을 물려받은 것", out["drafts"]["naver_place_intro"])
        self.assertIn("국산 재료만 쓰는 것", out["drafts"]["naver_place_intro"])
        self.assertIn("#", out["drafts"]["instagram_intro"])  # 해시태그 포함

        # 결과 카드의 글 상자는 step_id -> drafts[step_id] 로 이어 붙는다 — step_id 가 drafts 키와
        # 어긋나면(예전 버그: step_id="story_post", drafts 키="naver_place_intro") 글 상자가 비어 보인다.
        step_ids = {s["step_id"] for s in out["steps"]}
        self.assertEqual(step_ids, set(out["drafts"].keys()))

    def test_build_story_plan_skipped_questions_leave_no_trace(self):
        """6. 건너뛴 질문(빈 문자열)의 내용은 어떤 글에도 안 들어간다."""
        raw = {
            "story_reason": "부모님 식당을 물려받은 것", "story_signature": "",
            "story_keep": "", "story_prep": "", "story_message": "",
        }
        out = story.build_story_plan(raw, today=date(2026, 11, 15))

        for text in out["drafts"].values():
            self.assertNotIn("story_signature", text)  # 안 쓴 답의 자리표시조차 안 남는다

    def test_story_chat_path_through_server_reaches_decision(self):
        from fastapi.testclient import TestClient
        from marketing_survey.server import app

        client = TestClient(app)
        data = client.post("/api/marketing-survey/step", json={"state": None, "answer": None}).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "가게 이야기 글"},
        ).json()
        data = client.post(
            "/api/marketing-survey/step",
            json={"state": data["state"], "answer": "부모님 가게를 물려받아서"},
        ).json()
        self.assertEqual(data["state"]["node"], "story_signature")
        self.assertIsNotNone(data["example"])  # 회색 예시 한 줄

        for answer in ("", "정성껏 만드는 것", "", ""):  # 대표 메뉴·준비·손님께 할 말은 건너뛰기
            data = client.post(
                "/api/marketing-survey/step", json={"state": data["state"], "answer": answer},
            ).json()
        self.assertTrue(data["done"])

        res = client.post("/api/marketing-survey/plan", json={"state": data["state"]})
        body = res.json()
        self.assertIn("부모님 가게를 물려받아서", body["drafts"]["naver_place_intro"])
        self.assertIn("정성껏 만드는 것", body["drafts"]["naver_place_intro"])


class TestCouponResultFeature(unittest.TestCase):
    """5. 쿠폰 결과 확인 — 발급·사용·할인액·평균 금액으로 사용률·효율을 계산하고, 사용률로
    다음 쿠폰 조건(할인액 조정)을 코드가 정한다. AI 없음."""

    def test_usage_rate_basic(self):
        self.assertAlmostEqual(coupon_result.usage_rate(100, 25), 0.25)
        self.assertIsNone(coupon_result.usage_rate(0, 0))

    def test_cost_and_revenue_and_ratio(self):
        self.assertEqual(coupon_result.total_discount_cost(20, 2_000), 40_000)
        self.assertEqual(coupon_result.coupon_order_revenue(20, 15_000), 300_000)
        self.assertAlmostEqual(coupon_result.revenue_per_discount_won(300_000, 40_000), 7.5)
        self.assertIsNone(coupon_result.revenue_per_discount_won(300_000, 0))

    def test_low_usage_suggests_raising_discount_or_timing(self):
        out = coupon_result.build_coupon_result_plan({
            "coupon_issued": 100, "coupon_used": 10, "coupon_discount_won": 2_000,
            "coupon_avg_order_won": 15_000,
        })
        self.assertEqual(out["steps"][0]["what"], coupon_result.TODO_LOW_USAGE)
        self.assertEqual(out["next_condition"]["discount_won"], 2_500)
        self.assertEqual(out["next_condition"]["delta_won"], 500)

    def test_mid_usage_keeps_same_condition(self):
        out = coupon_result.build_coupon_result_plan({
            "coupon_issued": 100, "coupon_used": 30, "coupon_discount_won": 2_000,
            "coupon_avg_order_won": 15_000,
        })
        self.assertEqual(out["steps"][0]["what"], coupon_result.TODO_MID_USAGE)
        self.assertEqual(out["next_condition"]["discount_won"], 2_000)
        self.assertEqual(out["next_condition"]["delta_won"], 0)

    def test_high_usage_suggests_lowering_discount(self):
        out = coupon_result.build_coupon_result_plan({
            "coupon_issued": 100, "coupon_used": 60, "coupon_discount_won": 2_000,
            "coupon_avg_order_won": 15_000,
        })
        self.assertEqual(out["steps"][0]["what"], coupon_result.TODO_HIGH_USAGE)
        self.assertEqual(out["next_condition"]["discount_won"], 1_500)
        self.assertEqual(out["next_condition"]["delta_won"], -500)

    def test_next_discount_never_goes_negative(self):
        out = coupon_result.build_coupon_result_plan({
            "coupon_issued": 100, "coupon_used": 60, "coupon_discount_won": 200,
            "coupon_avg_order_won": 15_000,
        })
        self.assertEqual(out["next_condition"]["discount_won"], 0)

    def test_coupon_result_chat_path_through_server_reaches_decision(self):
        from fastapi.testclient import TestClient
        from marketing_survey.server import app

        client = TestClient(app)
        data = client.post("/api/marketing-survey/step", json={"state": None, "answer": None}).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "쿠폰 결과 확인"},
        ).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "100"},
        ).json()
        self.assertEqual(data["state"]["node"], "coupon_used")
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "10"},
        ).json()
        self.assertEqual(data["state"]["node"], "coupon_discount_won")
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "2000"},
        ).json()
        self.assertEqual(data["state"]["node"], "coupon_avg_order_won")
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "15000"},
        ).json()
        self.assertEqual(data["state"]["node"], "coupon_result_margin")
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "30%"},
        ).json()
        self.assertTrue(data["done"])

        res = client.post("/api/marketing-survey/plan", json={"state": data["state"]})
        body = res.json()
        self.assertEqual(body["usage_rate"], 0.1)
        self.assertEqual(body["steps"][0]["what"], coupon_result.TODO_LOW_USAGE)
        self.assertEqual(body["next_condition"]["discount_won"], 2_500)
        # 본전 주문 수 = ceil(20,000 ÷ 4,500) = 5 (비용=10x2,000, 건당이익=15,000x30%)
        self.assertEqual(body["breakeven_orders"], 5)

        res = client.post("/api/marketing-survey/generate", json={"state": data["state"]})
        self.assertEqual(res.status_code, 200, res.text)
        gen = res.json()
        self.assertTrue(gen["demo"])
        self.assertIsNotNone(gen["text"])
        self.assertEqual(gen["coupon"]["discount_won"], 2_500)


class TestNoticeFollowup(unittest.TestCase):
    """10. 개선 인증 소식(데모) — 공지 기준일 앞뒤 14일의 같은 불만 리뷰 수를 코드가 센다.
    줄었으면 코드 템플릿 소식 글(숫자는 코드 값만, '리뷰 기준'), 아니면 원인 재점검 안내만."""

    def test_sample_card_counts_before_after_with_explicit_today(self):
        # SAMPLE_REVIEWS(rv_ongi_001~003)는 2026-10-27~11-06 사이 — 2026-11-10 기준으로 전부 "이전".
        card = next(c for c in SAMPLE_CARDS if c.card_id == "card_sample_a")
        out = notice_followup.build_notice_followup(DEFAULT_CTX, card, today=date(2026, 11, 10))

        self.assertEqual(out["before"], 3)
        self.assertEqual(out["after"], 0)
        self.assertTrue(out["improved"])
        self.assertIsNotNone(out["text"])
        self.assertIn("리뷰 기준", out["text"])
        self.assertIn("3건", out["text"])
        self.assertIn("0건", out["text"])
        self.assertIsNone(out["todo"])

    def test_not_improved_skips_text_and_asks_to_recheck_cause(self):
        reviews = [
            ReviewRecord(review_id="rv_a", store_id="s", text="늦음1", created_at="2026-11-05T19:00:00+09:00"),
            ReviewRecord(review_id="rv_b", store_id="s", text="늦음2", created_at="2026-11-12T19:00:00+09:00"),
            ReviewRecord(review_id="rv_c", store_id="s", text="늦음3", created_at="2026-11-13T19:00:00+09:00"),
        ]
        ctx = build_context(
            store=SAMPLE_STORE, reviews=reviews, tone=SAMPLE_TONE, cards=[], snapshots=[],
            owner_replies=OWNER_REPLIES, policies=POLICIES,
        )
        card = SimpleNamespace(review_ids=["rv_a", "rv_b", "rv_c"])
        out = notice_followup.build_notice_followup(ctx, card, today=date(2026, 11, 11))

        self.assertEqual(out["before"], 1)  # rv_a만 이전 14일
        self.assertEqual(out["after"], 2)   # rv_b·rv_c는 이후 14일 -> 줄지 않음
        self.assertFalse(out["improved"])
        self.assertIsNone(out["text"])
        self.assertEqual(out["todo"], notice_followup.TODO_RECHECK_CAUSE)

    def test_server_endpoint_returns_followup_shape(self):
        from fastapi.testclient import TestClient
        from marketing_survey.server import app

        client = TestClient(app)
        res = client.post(
            "/api/marketing-survey/notice-followup",
            json={"state": {"node": "DECISION", "raw": {}, "confirms": {}, "mode": "survey"}},
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        for key in ("before", "after", "window_days", "basis", "improved", "text", "todo"):
            self.assertIn(key, body)


class TestEditDraftApprove(unittest.TestCase):
    """11. 고친 글 승인 — [고치기]로 바꾼 글(edited_text)도 개인정보·보상 약속만 다시 점검한다."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from marketing_survey.server import app

        cls.client = TestClient(app)

    def _survey_decision_state(self):
        data = self.client.post("/api/marketing-survey/step", json={"state": None, "answer": None}).json()
        data = self.client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "맞춤 홍보 제안"},
        ).json()
        data = self.client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "아니요"},
        ).json()
        data = self.client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "새 손님"},
        ).json()
        data = self.client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "아니요"},
        ).json()
        data = self.client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "0원(지금은 안 씀)"},
        ).json()
        self.assertTrue(data["done"])
        return data["state"]

    def test_clean_edited_text_passes_approve(self):
        state = self._survey_decision_state()
        res = self.client.post(
            "/api/marketing-survey/approve",
            json={"state": state, "edited_texts": {"naver_notice": "오늘도 맛있게 준비했어요."}},
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertNotIn("edit_failed", res.json())

    def test_personal_info_in_edited_text_fails_approve(self):
        state = self._survey_decision_state()
        res = self.client.post(
            "/api/marketing-survey/approve",
            json={"state": state, "edited_texts": {"naver_notice": "문의는 010-1234-5678 로 주세요."}},
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertIn("edit_failed", body)
        self.assertIn("naver_notice", body["edit_failed"])
        self.assertFalse(body["follow_up"])

    def test_promise_not_in_policy_in_edited_text_fails_approve(self):
        state = self._survey_decision_state()
        res = self.client.post(
            "/api/marketing-survey/approve",
            json={"state": state, "edited_texts": {"naver_notice": "불편을 드려 10000원을 환불해 드릴게요."}},
        )
        body = res.json()
        self.assertIn("edit_failed", body)


class TestIdeasPerGoal(unittest.TestCase):
    """12. 목표별 결과가 서로 다르다 — 기본 할 일 2개와 아이디어 목록이 목표마다 겹치지 않고
    (아이디어는 "공통" 없이 목표 하나에만 배정), [다른 아이디어 보기]는 그 목표 안에서만 순환한다."""

    _GOALS = ("새 손님", "재주문", "객단가")

    def test_basic_todos_do_not_overlap_across_goals(self):
        titles_by_goal = {g: set(playbooks.basic_todos_for_goal(g)) for g in self._GOALS}
        for a in self._GOALS:
            for b in self._GOALS:
                if a == b:
                    continue
                self.assertEqual(titles_by_goal[a] & titles_by_goal[b], set(), (a, b))

    def test_idea_ids_do_not_overlap_across_goals_and_have_no_common_bucket(self):
        answers = SurveyAnswers(budget_won=0, goal="")
        ids_by_goal = {g: {i["id"] for i in ideas.ideas_for(g, DEFAULT_CTX, answers)} for g in self._GOALS}

        for a in self._GOALS:
            for b in self._GOALS:
                if a == b:
                    continue
                self.assertEqual(ids_by_goal[a] & ids_by_goal[b], set(), (a, b))
        self.assertIn("story_link", ids_by_goal["새 손님"])
        self.assertIn("remember_taste", ids_by_goal["재주문"])
        self.assertIn("two_person_set", ids_by_goal["객단가"])

    def test_basic_todos_and_ideas_do_not_reuse_the_same_concept_per_goal(self):
        """기본 할 일에 쓴 것과 같은 아이디어는 그 목표에서 다시 나오지 않는다(upsell_pair·
        min_order_check·thank_note·remember_request 는 더 이상 아이디어 목록에 없다)."""
        answers = SurveyAnswers(budget_won=0, goal="")
        all_idea_ids = {i["id"] for g in self._GOALS for i in ideas.ideas_for(g, DEFAULT_CTX, answers)}
        for retired in ("upsell_pair", "min_order_check", "thank_note", "remember_request"):
            self.assertNotIn(retired, all_idea_ids)

    def test_idea_at_cycles_within_goal_only_in_fixed_code_order(self):
        answers = SurveyAnswers(budget_won=0, goal="재주문")
        candidates = ideas.ideas_for("재주문", DEFAULT_CTX, answers)
        n = len(candidates)
        self.assertGreater(n, 1)

        picked = [ideas.idea_at("재주문", DEFAULT_CTX, answers, i)[0]["id"] for i in range(n + 1)]
        self.assertEqual(picked[:n], [c["id"] for c in candidates])  # 코드에 적힌 순서 그대로
        self.assertEqual(picked[n], picked[0])  # n바퀴 돌면 처음으로 되돌아온다(무작위 아님)
        # 그 목표 아이디어 밖으로는 절대 넘어가지 않는다
        other_goal_ids = {i["id"] for i in ideas.ideas_for("객단가", DEFAULT_CTX, answers)}
        self.assertEqual(set(picked) & other_goal_ids, set())

    def test_custom_option_skips_when_adjustment_not_possible(self):
        """재주문의 custom_option — 맵기·밥 양 조절이 "아니요"면 이 아이디어는 건너뛴다."""
        answers = SurveyAnswers(budget_won=0, goal="재주문")
        idea = next(i for i in ideas.IDEAS_BY_GOAL["재주문"] if i["id"] == "custom_option")

        no_result = ideas.try_idea(idea, DEFAULT_CTX, answers, answer="아니요")
        self.assertTrue(no_result["skip"])
        self.assertIsNone(no_result["draft"])

        yes_result = ideas.try_idea(idea, DEFAULT_CTX, answers, answer="예")
        self.assertFalse(yes_result["skip"])
        self.assertIsNotNone(yes_result["draft"])

    def test_weekly_side_skips_when_answer_is_empty(self):
        answers = SurveyAnswers(budget_won=0, goal="재주문")
        idea = next(i for i in ideas.IDEAS_BY_GOAL["재주문"] if i["id"] == "weekly_side")

        empty = ideas.try_idea(idea, DEFAULT_CTX, answers, answer="")
        self.assertTrue(empty["skip"])

        filled = ideas.try_idea(idea, DEFAULT_CTX, answers, answer="계란찜")
        self.assertFalse(filled["skip"])
        self.assertIn("계란찜", filled["draft"])

    def test_first_order_combo_computes_sum_price_from_store_data(self):
        """새 손님의 first_order_combo — 조합 합계 가격은 코드가 메뉴 가격을 더해서 만든다."""
        store = DEFAULT_CTX.store
        menu = next(iter(store.menu_prices))
        answers = SurveyAnswers(budget_won=0, goal="새 손님", discount_menu=menu)
        idea = next(i for i in ideas.IDEAS_BY_GOAL["새 손님"] if i["id"] == "first_order_combo")

        result = ideas.try_idea(idea, DEFAULT_CTX, answers)

        other = next(m for m in store.menu_prices if m != menu)
        expected_total = store.menu_prices[menu] + store.menu_prices[other]
        self.assertFalse(result["skip"])
        self.assertIn(f"{expected_total:,}원", result["draft"])

    def test_two_person_set_computes_sum_price_with_no_discount(self):
        store = DEFAULT_CTX.store
        menu = next(iter(store.menu_prices))
        answers = SurveyAnswers(budget_won=0, goal="객단가", discount_menu=menu)
        idea = next(i for i in ideas.IDEAS_BY_GOAL["객단가"] if i["id"] == "two_person_set")

        result = ideas.try_idea(idea, DEFAULT_CTX, answers)

        other = next(m for m in store.menu_prices if m != menu)
        expected_total = store.menu_prices[menu] + store.menu_prices[other]
        self.assertIn(f"{expected_total:,}원", result["draft"])
        self.assertIn("할인 없음", result["draft"])

    def test_build_plan_attaches_goal_specific_idea_and_basic_todos(self):
        answers = SurveyAnswers(
            budget_won=100_000, goal="재주문", discount_menu="제육볶음 정식", max_discount_won=5_000,
        )
        plan = decide(DEFAULT_CTX, answers, confirms={})
        out = build_plan(DEFAULT_CTX, plan.strategies[0], answers, None, today=date(2026, 11, 15))

        titles = [t["title"] for t in out["basic_todos"]]
        self.assertEqual(titles, playbooks.basic_todos_for_goal("재주문"))
        self.assertNotEqual(titles, playbooks.basic_todos_for_goal("새 손님"))
        self.assertIsNotNone(out["idea"])
        self.assertIn(out["idea"]["id"], {i["id"] for i in ideas.ideas_for("재주문", DEFAULT_CTX, answers)})
        # 재주문의 첫 아이디어(remember_taste)는 질문이 필요 없어 바로 글이 채워진다
        self.assertFalse(out["idea"]["needs_question"])
        self.assertIsNotNone(out["idea"]["draft"])

    def test_next_idea_endpoint_cycles_through_server(self):
        from fastapi.testclient import TestClient
        from marketing_survey.server import app

        client = TestClient(app)
        data = client.post("/api/marketing-survey/step", json={"state": None, "answer": None}).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "맞춤 홍보 제안"},
        ).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "아니요"},
        ).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "재주문"},
        ).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "아니요"},
        ).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "0원(지금은 안 씀)"},
        ).json()
        self.assertTrue(data["done"])
        state = data["state"]

        plan_res = client.post("/api/marketing-survey/plan", json={"state": state}).json()
        first_id = plan_res["idea"]["id"]

        res = client.post(
            "/api/marketing-survey/next-idea", json={"state": state, "current_index": plan_res["idea_index"]},
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertIsNotNone(body["idea"])
        self.assertNotEqual(body["idea"]["id"], first_id)
        reorder_ids = {i["id"] for i in ideas.IDEAS_BY_GOAL["재주문"]}
        self.assertIn(body["idea"]["id"], reorder_ids)

    def test_idea_try_endpoint_asks_question_then_honors_skip(self):
        """custom_option — 먼저 answer 없이 부르면 질문만 오고, "아니요"로 답하면 skip=True."""
        from fastapi.testclient import TestClient
        from marketing_survey.server import app

        client = TestClient(app)
        data = client.post("/api/marketing-survey/step", json={"state": None, "answer": None}).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "맞춤 홍보 제안"},
        ).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "아니요"},
        ).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "재주문"},
        ).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "아니요"},
        ).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "0원(지금은 안 씀)"},
        ).json()
        state = data["state"]

        ask = client.post(
            "/api/marketing-survey/idea-try",
            json={"state": state, "idea_id": "custom_option", "index": 1},
        ).json()
        self.assertTrue(ask["need_answer"])
        self.assertIsNotNone(ask["question"])

        answered = client.post(
            "/api/marketing-survey/idea-try",
            json={"state": state, "idea_id": "custom_option", "index": 1, "answer": "아니요"},
        ).json()
        self.assertFalse(answered["need_answer"])
        self.assertTrue(answered["skip"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
