"""설문 맞춤 마케팅 — 규칙(decide)·설명(explain)·실행(execute) 전체 경로. AI 호출 없음(decide/explain)
이거나 --mock·저장본(execute)만 쓴다.

실행 방법
  python -m pytest tests/test_marketing_survey.py -q
  python -m tests.test_marketing_survey
"""

import unittest
from datetime import date

from c6.contract import build_context
from c6.dummy import OWNER_REPLIES, POLICIES
from marketing_survey import adspend, coupon_result, flow, leftover, playbooks, story
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
        _walk(
            DEFAULT_CTX, "max_discount", follow_up_state,
            [max_discount_options[0]["label"], "충분", ["네이버 플레이스"]],
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

        def _explore(node_id: str, state: dict, depth: int = 0):
            self.assertLess(depth, 20, "사이클 의심(깊이 초과)")
            visited.add(node_id)
            node = flow.NODES[node_id]
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
    """2. 남은 재료 팔기 — 세트 가격 계산 + 할인 불가일 때 "오늘의 추천"으로 바뀌는지."""

    def test_set_bundle_price_is_90_percent_rounded_to_100(self):
        store = DEFAULT_CTX.store
        menu_items = list(store.menu_prices.items())
        first_menu = menu_items[0][0]
        bundle = leftover.set_bundle_price(store, first_menu)

        self.assertIsNotNone(bundle)
        total = sum(store.menu_prices[m] for m in bundle["menus"])
        self.assertEqual(bundle["original_won"], total)
        expected = int(round(total * 0.9 / 100)) * 100
        self.assertEqual(bundle["bundle_won"], expected)
        self.assertEqual(bundle["bundle_won"] % 100, 0)

    def test_discount_allowed_produces_today_only_set(self):
        menu = next(iter(DEFAULT_CTX.store.menu_prices))
        raw = {"leftover_item": menu, "leftover_portions": 3, "leftover_discount_allowed": True}
        out = leftover.build_leftover_plan(DEFAULT_CTX, raw, None)

        self.assertEqual(out["title"], "오늘만 세트")
        self.assertIn("leftover_post", out["drafts"])
        self.assertIn("세트", out["drafts"]["leftover_post"])
        self.assertEqual(out["total_cost_krw"], 0)

    def test_discount_not_allowed_produces_today_recommendation(self):
        menu = next(iter(DEFAULT_CTX.store.menu_prices))
        raw = {"leftover_item": menu, "leftover_portions": 3, "leftover_discount_allowed": False}
        out = leftover.build_leftover_plan(DEFAULT_CTX, raw, None)

        self.assertEqual(out["title"], "오늘의 추천")
        self.assertIn("오늘의 추천", out["drafts"]["leftover_post"])
        self.assertNotIn("세트", out["drafts"]["leftover_post"])

    def test_leftover_chat_path_through_server_reaches_decision(self):
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
        self.assertEqual(data["state"]["node"], "leftover_portions")
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "3"},
        ).json()
        self.assertEqual(data["state"]["node"], "leftover_discount")
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "예"},
        ).json()
        self.assertTrue(data["done"])

        res = client.post("/api/marketing-survey/plan", json={"state": data["state"]})
        body = res.json()
        self.assertEqual(body["title"], "오늘만 세트")


class TestAdSpendFeature(unittest.TestCase):
    """3. 광고비 점검 — 건당 광고비 계산, 15% 초과면 점검 필요. AI 없음."""

    def test_cost_per_order_basic(self):
        self.assertEqual(adspend.cost_per_order(150_000, 30), 5_000)
        self.assertIsNone(adspend.cost_per_order(150_000, 0))

    def test_high_cost_channel_is_flagged_and_low_cost_is_not(self):
        store = DEFAULT_CTX.store
        menu = playbooks.default_menu(store)
        price = store.menu_prices[menu]

        raw = {
            "adspend_baemin_spend": price * 1000, "adspend_baemin_orders": 1,  # 건당 광고비 = 메뉴값*1000 (매우 높음)
            "adspend_coupangeats_spend": 0, "adspend_coupangeats_orders": 0,
            "adspend_yogiyo_spend": 100, "adspend_yogiyo_orders": 1000,  # 건당 0.1원 (매우 낮음)
        }
        out = adspend.build_adspend_table(DEFAULT_CTX, raw)
        by_channel = {r["channel"]: r for r in out["table"]}

        self.assertTrue(by_channel["baemin"]["needs_check"])
        self.assertFalse(by_channel["yogiyo"]["needs_check"])
        self.assertIn("높은 채널 광고 조건 다시 보기", out["todos"])
        self.assertIn("예산을 낮은 채널로 옮기기(추정)", out["todos"])

    def test_no_flag_when_all_channels_within_threshold(self):
        raw = {f"adspend_{c}_spend": 0 for c in adspend.AD_CHANNELS}
        raw.update({f"adspend_{c}_orders": 0 for c in adspend.AD_CHANNELS})
        out = adspend.build_adspend_table(DEFAULT_CTX, raw)
        self.assertEqual(out["todos"], [])


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
        self.assertIn("부모님 식당을 물려받은 것", out["drafts"]["naver_place_intro"])
        self.assertIn("국산 재료만 쓰는 것", out["drafts"]["naver_place_intro"])

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
        self.assertEqual(data["state"]["node"], "story_keep")
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "정성껏 만드는 것"},
        ).json()
        self.assertTrue(data["done"])

        res = client.post("/api/marketing-survey/plan", json={"state": data["state"]})
        body = res.json()
        self.assertIn("부모님 가게를 물려받아서", body["drafts"]["naver_place_intro"])


class TestCouponResultFeature(unittest.TestCase):
    """5. 쿠폰 결과 확인 — 사용률 계산, 30% 기준으로 할 일이 바뀐다. AI 없음."""

    def test_usage_rate_basic(self):
        self.assertAlmostEqual(coupon_result.usage_rate(100, 25), 0.25)
        self.assertIsNone(coupon_result.usage_rate(0, 0))

    def test_low_usage_suggests_raising_discount_or_timing(self):
        out = coupon_result.build_coupon_result_plan({"coupon_issued": 100, "coupon_used": 20})
        self.assertEqual(out["steps"][0]["what"], coupon_result.TODO_LOW_USAGE)

    def test_high_usage_suggests_repeat(self):
        out = coupon_result.build_coupon_result_plan({"coupon_issued": 100, "coupon_used": 40})
        self.assertEqual(out["steps"][0]["what"], coupon_result.TODO_HIGH_USAGE)

    def test_coupon_result_chat_path_through_server_reaches_decision(self):
        from fastapi.testclient import TestClient
        from marketing_survey.server import app

        client = TestClient(app)
        data = client.post("/api/marketing-survey/step", json={"state": None, "answer": None}).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "쿠폰 결과 확인"},
        ).json()
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "50"},
        ).json()
        self.assertEqual(data["state"]["node"], "coupon_used")
        data = client.post(
            "/api/marketing-survey/step", json={"state": data["state"], "answer": "10"},
        ).json()
        self.assertTrue(data["done"])

        res = client.post("/api/marketing-survey/plan", json={"state": data["state"]})
        body = res.json()
        self.assertEqual(body["usage_rate"], 0.2)
        self.assertEqual(body["steps"][0]["what"], coupon_result.TODO_LOW_USAGE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
