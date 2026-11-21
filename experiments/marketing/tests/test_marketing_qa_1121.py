"""11/21 실사용 QA 맞춤 마케팅 고침 — AI 호출 없음 (mock·저장본·코드 템플릿, live 경로는 생성기를 가짜로 바꿔 넘기는 인자만 본다).

- M-A1: '어떤 불만인가요?' 보기가 그 가게 리뷰의 반복 불만이고, 고른 주제 = 안내문 주제 = 조치 주제인지 (온기한식·바삭치킨·몽글카페).
- M-A2: 안내문 승인 뒤 재주문 쿠폰(선택)을 '여기까지 할게요'·예산 0원·할인 아니요·메뉴 가격 없음으로 오류 없이 끝내는지.
- M-A4: '이번 주 할 일'에 2주 뒤 재측정이 없고 '측정' 줄에만 있는지.

실행 (experiments/marketing 에서): python -m pytest tests/test_marketing_qa_1121.py -q -s
"""

import dataclasses
import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from c6.contract import build_context
from c6.dummy import POLICIES
from c6.measures import MISSING_TOPIC, TOPIC_LABELS
from c6.notice import notice_topic
from c6.output import CardResult, DraftOutput
from marketing_survey import complaints, flow, playbooks, records, report, stores
from marketing_survey.decide import decide, follow_up_end_message
from marketing_survey.execute import LATE_NOTICE_TEMPLATE, NOTICE_CHOSEN_MEASURES, _run_notice, _run_reply, build_plan
from marketing_survey.survey import answers_from_raw
from shared.contracts import RecommendationCard, ReviewRecord, StoreProfile, ToneProfile

TODAY = date(2026, 11, 21)   # 토요일. +14일 = 12/5(토)
SAMPLE_STORES = ("store_ongi", "store_basak", "store_mongle")
EXPECTED_OPTIONS = {
    "store_ongi": ["포장 누락", "그 외"],
    "store_basak": ["식감", "포장 누락", "배달 지연", "그 외"],
    "store_mongle": ["매장 대기", "포장 상태", "맛", "그 외"],
}
TEST_STORE = StoreProfile(
    store_id="store_qa1121", name="시험가게 (가상)", business_type="korean", business_type_name="한식",
    channels=["baemin", "naver_place"], menu=["국밥", "수육"], menu_prices={"국밥": 9000, "수육": 18000},
)
TEST_TONE = ToneProfile(tone_id="tone_qa1121", store_id=TEST_STORE.store_id, style_description="친근한 해요체",
                        example_sentences=["맛있게 드세요!"])


def _ctx(reviews=(), cards=(), menu_prices=None):
    store = TEST_STORE if menu_prices is None else dataclasses.replace(TEST_STORE, menu_prices=menu_prices)
    return build_context(store=store, reviews=list(reviews), tone=TEST_TONE, cards=list(cards), snapshots=[],
                         owner_replies=[], policies=POLICIES)


def _review(n, text, topics):
    return ReviewRecord(review_id=f"rv_qa_{n:03d}", store_id=TEST_STORE.store_id, text=text,
                        created_at=f"2026-11-{10 + n:02d}T19:00:00+09:00", rating=2, sentiment="negative",
                        topics=list(topics), negative_topics=list(topics))


def _temperature_ctx():
    """'음식 온도' 불만이 반복된 가게 — 주제에 맞는 조치(M5 배달 파트너사 온도 유지 요청)가 있는 주제."""
    return _ctx([_review(1, "국밥이 다 식어서 왔어요", ["temperature"]),
                 _review(2, "수육이 차갑게 식어서 도착했어요", ["temperature"])])


def _options(ctx):
    return flow.node_options("complaint_type", ctx, {"raw": {}, "confirms": {}})


def _choose(ctx, label):
    """complaint_type 에서 label 을 고른 설문 상태(raw·confirms)."""
    state = {"raw": {}, "confirms": {}}
    assert flow.advance("complaint_type", ctx, state, label) == flow.DECISION
    return state


def _strategy(ctx, state):
    answers = answers_from_raw(state["raw"])
    return decide(ctx, answers, confirms=state["confirms"], complaint_topic=state["raw"].get("complaint_topic")).strategies[0], answers


def _target_reviews(ctx, card):
    by_id = {r.review_id: r for r in ctx.reviews}
    return [by_id[i] for i in card.review_ids if i in by_id]


def _fake_result(card, generator):
    draft = DraftOutput(draft_id="d_fake", card_id=card.card_id, store_id=card.store_id, generator=generator, text="가짜 글")
    return CardResult(card_id=card.card_id, kind=card.kind, reason_text=card.reason_text, drafts=[draft])


class TestComplaintOptions(unittest.TestCase):
    """M-A1: 보기 = 그 가게 리뷰의 반복 불만 주제 (많은 순, 최대 3개) + '그 외'."""

    def test_sample_stores_offer_their_own_repeated_complaints(self):
        for sid in SAMPLE_STORES:
            ctx = stores.get_ctx(sid)
            self.assertEqual([o["label"] for o in _options(ctx)], EXPECTED_OPTIONS[sid], sid)
            text = flow.node_text("complaint_type", ctx, {"raw": {}, "confirms": {}})
            self.assertIn("리뷰에서 반복된 불만", text, sid)

    def test_basak_counts_are_in_the_question(self):
        text = flow.node_text("complaint_type", stores.get_ctx("store_basak"), {"raw": {}, "confirms": {}})
        self.assertIn("식감 4건 · 포장 누락 4건 · 배달 지연 3건", text)

    def test_delivery_goes_to_late_notice_and_other_topics_to_repeat_notice(self):
        for label, hyp, topic in (("배달 지연", "H_LATE", "delivery_time"), ("식감", "H_REPEAT", "texture"),
                                  ("포장 누락", "H_REPEAT", MISSING_TOPIC)):
            state = _choose(stores.get_ctx("store_basak"), label)
            self.assertEqual(state["confirms"], {hyp: "예"}, label)
            self.assertEqual(state["raw"]["complaint_topic"], topic, label)
        other = next(o for o in _options(stores.get_ctx("store_basak")) if o["label"] == "그 외")
        self.assertEqual((other["confirm"], other["next"]), ({"H_STORE_ONLY": "예"}, "goal"))

    def test_store_without_repeated_complaints_keeps_legacy_options_and_says_why(self):
        """직접 등록한 새 가게처럼 리뷰가 없으면 예전 보기 그대로 + 이유 한 줄 (등록 가게 시험이 '포장 누락'으로 고른다)."""
        ctx = _ctx()
        self.assertEqual([o["label"] for o in _options(ctx)], ["포장 누락", "배달 지연", "그 외"])
        self.assertIn("기본 보기", flow.node_text("complaint_type", ctx, {"raw": {}, "confirms": {}}))
        # 한 건뿐인 불만은 반복이 아니다
        one = _ctx([_review(1, "국밥이 짰어요", ["taste"])])
        self.assertEqual([o["label"] for o in _options(one)], ["포장 누락", "배달 지연", "그 외"])


class TestChosenTopicMatchesNoticeAndMeasure(unittest.TestCase):
    """M-A1: 고른 주제 = 안내문 주제(카드 리뷰의 주제·제목) = 조치 주제. 가게 세 곳의 H_REPEAT 보기 전부."""

    def _repeat_labels(self, sid):
        return [lab for lab in EXPECTED_OPTIONS[sid] if lab not in ("그 외", "배달 지연")]

    def test_live_path_passes_the_chosen_topic_card_and_its_measures(self):
        """키가 있을 때(실제 HCX 경로) 생성기에 넘기는 카드·조치가 고른 주제의 것인지 — 생성기는 가짜로 바꿔 부르지 않는다."""
        for sid in SAMPLE_STORES:
            ctx = stores.get_ctx(sid)
            for label in self._repeat_labels(sid):
                state = _choose(ctx, label)
                strategy, _ = _strategy(ctx, state)
                topic = state["raw"]["complaint_topic"]
                self.assertEqual(strategy.topic, topic, (sid, label))
                with patch("marketing_survey.execute.generate_prevention_notice",
                           side_effect=lambda c, card, *a, **k: _fake_result(card, "prevention_notice")) as gen, \
                     patch("marketing_survey.execute.generate_reply_draft",
                           side_effect=lambda c, card, *a, **k: _fake_result(card, "reply_draft")) as rep:
                    _run_notice(ctx, "fake-key", "HCX-005", strategy.topic)
                    _run_reply(ctx, "fake-key", "HCX-005", strategy.topic)
                for mock in (gen, rep):
                    card = mock.call_args.args[1]
                    reviews = _target_reviews(ctx, card)
                    self.assertTrue(reviews and all(topic in r.negative_topics for r in reviews), (sid, label, card))
                    self.assertEqual(notice_topic(reviews), topic, (sid, label))           # 안내문 제목이 이 주제로
                    self.assertEqual(mock.call_args.kwargs["chosen_measures"], complaints.notice_measures(topic), (sid, label))
                measures = gen.call_args.kwargs["chosen_measures"]
                if topic == MISSING_TOPIC:
                    self.assertEqual(measures, NOTICE_CHOSEN_MEASURES)    # 포장 누락 = 주문서 대조 (예전 그대로)
                else:
                    self.assertEqual(measures, [], (sid, label))            # 식감·대기 등에 주문서 대조를 넣지 않는다

    def test_mock_plan_notice_title_reply_and_steps_follow_the_chosen_topic(self):
        """키 없이(mock) 결과 카드 전체: 제목·안내문 '[안내] … 관련'·답글·할 일이 고른 주제와 같은지."""
        for sid in SAMPLE_STORES:
            ctx = stores.get_ctx(sid)
            for label in self._repeat_labels(sid):
                state = _choose(ctx, label)
                strategy, answers = _strategy(ctx, state)
                topic = state["raw"]["complaint_topic"]
                plan = build_plan(ctx, strategy, answers, None, today=TODAY)
                notice, reply = plan["drafts"]["notice"], plan["drafts"]["reply"]
                self.assertTrue(notice.startswith(f"[안내] {TOPIC_LABELS[topic]} 관련"), (sid, label, notice[:40]))
                step_ids = [s["step_id"] for s in plan["steps"]]
                if topic == MISSING_TOPIC:
                    self.assertEqual(plan["title"], "배달앱 포장·주문 안내문")
                    self.assertIn("주문서", notice)
                    self.assertIn("pack_memo", step_ids)
                else:
                    self.assertEqual(plan["title"], f"{label} 불만 안내문", sid)
                    for text in (notice, reply):
                        self.assertNotIn("주문서", text, (sid, label))
                        self.assertNotIn("빠진", text, (sid, label))
                    self.assertNotIn("pack_memo", step_ids, (sid, label))
                    self.assertNotIn("포장·주문", plan["steps"][0]["tip"], (sid, label))

    def test_ongi_missing_item_is_unchanged(self):
        """온기한식 포장 누락은 예전과 같은 카드(card_sample_a)·저장본 글·조치(M1)."""
        ctx = stores.get_ctx("store_ongi")
        state = _choose(ctx, "포장 누락")
        strategy, answers = _strategy(ctx, state)
        self.assertEqual(complaints.topic_card(ctx, strategy.topic).card_id, "card_sample_a")
        self.assertEqual(complaints.notice_measures(strategy.topic), NOTICE_CHOSEN_MEASURES)
        _, draft = _run_notice(ctx, None, "HCX-005", strategy.topic)
        _, old = _run_notice(ctx, None, "HCX-005")                 # 주제 없이(예전 상태) 부른 것과 같은 글
        self.assertEqual(draft.text, old.text)
        self.assertIn("포장 마감 전에 주문서", draft.text)
        plan = build_plan(ctx, strategy, answers, None, today=TODAY)
        self.assertEqual([s["step_id"] for s in plan["steps"]], ["notice", "reply", "pack_memo"])

    def test_old_state_without_topic_uses_the_store_card_topic(self):
        """예전 화면이 보낸 상태(complaint_topic 없음)는 가게 불만 카드의 주제로 — 바삭치킨이면 식감, 조치 없음."""
        ctx = stores.get_ctx("store_basak")
        strategy = decide(ctx, answers_from_raw({}), confirms={"H_REPEAT": "예"}).strategies[0]
        self.assertEqual((strategy.topic, strategy.title), ("texture", "식감 불만 안내문"))

    def test_basak_late_option_makes_the_late_notice(self):
        ctx = stores.get_ctx("store_basak")
        strategy, answers = _strategy(ctx, _choose(ctx, "배달 지연"))
        self.assertEqual((strategy.source_hypothesis, strategy.topic), ("H_LATE", "delivery_time"))
        plan = build_plan(ctx, strategy, answers, None, today=TODAY)
        self.assertEqual(plan["drafts"]["notice"], LATE_NOTICE_TEMPLATE)

    def test_topic_with_its_own_measure_puts_that_measure_in_notice_reply_and_todo(self):
        """음식 온도: 조치 = M5(배달 파트너사 온도 유지 요청). 안내문·답글·할 일이 같은 조치, 주문서 대조는 없음."""
        ctx = _temperature_ctx()
        self.assertEqual([o["label"] for o in _options(ctx)], ["음식 온도", "그 외"])
        strategy, answers = _strategy(ctx, _choose(ctx, "음식 온도"))
        self.assertEqual([m["id"] for m in complaints.notice_measures(strategy.topic)], ["M5"])
        plan = build_plan(ctx, strategy, answers, None, today=TODAY)   # 저장본 없는 카드 → 코드 템플릿 글
        notice, reply = plan["drafts"]["notice"], plan["drafts"]["reply"]
        self.assertTrue(notice.startswith("[안내] 음식 온도 관련"))
        self.assertIn("오늘부터 배달 파트너사에 온도 유지를 요청하겠습니다.", notice)
        self.assertIn("배달 파트너사", reply)
        for text in (notice, reply):
            self.assertNotIn("주문서", text)
        steps = {s["step_id"]: s for s in plan["steps"]}
        self.assertEqual(steps["measure_do"]["what"], "배달 파트너사에 온도 유지 요청하기")
        self.assertIn("배달 파트너사에 온도 유지 요청", steps["notice"]["tip"])

    def test_topic_without_reviews_is_a_missing_card_not_a_mixed_notice(self):
        """새 가게가 예전 보기 '포장 누락'을 골랐는데 그 리뷰가 없으면: 다른 주제 카드로 쓰지 않고 '자료가 없어요' 안내."""
        ctx = _ctx(cards=[RecommendationCard(card_id="card_qa_a", store_id=TEST_STORE.store_id, kind="complaint",
                                             reason_text="맛 불만", review_ids=["rv_qa_001"])],
                   reviews=[_review(1, "국밥이 짰어요", ["taste"])])
        strategy, answers = _strategy(ctx, _choose(ctx, "포장 누락"))
        plan = build_plan(ctx, strategy, answers, None, today=TODAY)
        self.assertNotIn("notice", plan["drafts"])
        self.assertEqual({u["step_id"] for u in plan["unavailable_drafts"]}, {"notice", "reply"})


class TestServerTopicFlow(unittest.TestCase):
    """서버 경로 (mock): 바삭치킨·몽글카페도 안내문 결과가 500 없이 나오고, 2주 뒤 개선 소식도 같은 주제로 센다."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from marketing_survey.server import app

        # mock + 이 클래스만의 기록 폴더 (다른 시험 파일의 보고서 시험이 이 승인 기록을 세지 않게)
        cls.env = patch.dict(os.environ, {"MARKETING_APP_MODE": "mock",
                                          records.RECORDS_DIR_ENV: tempfile.mkdtemp(prefix="marketing_records_qa1121_")})
        cls.env.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()

    def _walk(self, sid, answers):
        data = self.client.post("/api/marketing-survey/step", json={"state": None, "answer": None}, params={"store": sid}).json()
        for a in answers:
            res = self.client.post("/api/marketing-survey/step", json={"state": data["state"], "answer": a}, params={"store": sid})
            self.assertEqual(res.status_code, 200, res.text)
            data = res.json()
        return data

    def test_each_store_each_topic_plan_is_200_with_matching_notice(self):
        for sid in SAMPLE_STORES:
            for label in EXPECTED_OPTIONS[sid]:
                if label in ("그 외", "배달 지연"):
                    continue
                data = self._walk(sid, ["맞춤 홍보 제안", "예", label])
                self.assertTrue(data["done"])
                plan = self.client.post("/api/marketing-survey/plan", json={"state": data["state"]}, params={"store": sid})
                self.assertEqual(plan.status_code, 200, (sid, label, plan.text[:200]))
                topic = data["state"]["raw"]["complaint_topic"]
                self.assertTrue(plan.json()["drafts"]["notice"].startswith(f"[안내] {TOPIC_LABELS[topic]} 관련"), (sid, label))
                why = self.client.post("/api/marketing-survey/result", json={"state": data["state"]}, params={"store": sid}).json()
                self.assertIn(f"{label} 불만이 리뷰에서", why["explain"][0])
                gen = self.client.post("/api/marketing-survey/generate", json={"state": data["state"]}, params={"store": sid})
                self.assertEqual(gen.status_code, 200, gen.text)
                self.assertTrue(gen.json()["text"].startswith(f"[안내] {TOPIC_LABELS[topic]} 관련"))

    def test_notice_followup_counts_and_names_the_chosen_topic(self):
        class _Day(date):          # 개선 소식은 '오늘' 앞뒤 14일을 센다 — 날짜를 고정해 늘 같은 결과로
            @classmethod
            def today(cls):
                return TODAY

        data = self._walk("store_mongle", ["맞춤 홍보 제안", "예", "매장 대기"])
        with patch("marketing_survey.notice_followup.date", _Day):
            res = self.client.post("/api/marketing-survey/notice-followup", json={"state": data["state"]},
                                   params={"store": "store_mongle"})
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertTrue(body["improved"], body)
        self.assertIn("최근 매장 대기 관련 불만이 줄었습니다", body["text"])
        self.assertNotIn("포장 누락", body["text"])


class TestFollowUpCanEnd(unittest.TestCase):
    """M-A2: 안내문 승인 뒤 재주문 쿠폰은 선택 — 끝낼 보기가 있고, 만들지 않으면 오류가 아니라 보통 끝(end)."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from marketing_survey.server import app

        # mock + 이 클래스만의 기록 폴더 (다른 시험 파일의 보고서 시험이 이 승인 기록을 세지 않게)
        cls.env = patch.dict(os.environ, {"MARKETING_APP_MODE": "mock",
                                          records.RECORDS_DIR_ENV: tempfile.mkdtemp(prefix="marketing_records_qa1121_")})
        cls.env.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()

    def _approved(self, sid="store_ongi", label="포장 누락"):
        data = self.client.post("/api/marketing-survey/step", json={"state": None, "answer": None}, params={"store": sid}).json()
        for a in ("맞춤 홍보 제안", "예", label):
            data = self.client.post("/api/marketing-survey/step", json={"state": data["state"], "answer": a}, params={"store": sid}).json()
        res = self.client.post("/api/marketing-survey/approve", json={"state": data["state"]}, params={"store": sid})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def _step(self, state, answer, sid="store_ongi"):
        res = self.client.post("/api/marketing-survey/step", json={"state": state, "answer": answer}, params={"store": sid})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_first_follow_up_message_says_approval_is_done_and_offers_stop(self):
        a = self._approved()
        self.assertTrue(a["follow_up"])
        self.assertIn("승인은 끝났어요", a["bot_messages"][0])
        self.assertIn("선택", a["bot_messages"][0])
        labels = [o["label"] for o in a["options"]]
        self.assertEqual(labels, ["0원(지금은 안 씀)", "50,000원", "100,000원", "300,000원", "여기까지 할게요"])

    def test_stop_zero_budget_and_no_discount_end_normally(self):
        for sid, label in (("store_ongi", "포장 누락"), ("store_basak", "식감"), ("store_mongle", "매장 대기")):
            a = self._approved(sid, label)
            cases = (
                (["여기까지 할게요"], "재주문 쿠폰은 만들지 않을게요"),
                (["0원(지금은 안 씀)"], "쿠폰은 지금 만들지 않을게요"),
                (["50,000원", "아니요"], "할인이 어렵다고"),
            )
            for answers, words in cases:
                d = {"state": a["state"]}
                for ans in answers:
                    d = self._step(d["state"], ans, sid)
                self.assertTrue(d["done"] and d["end"], (sid, answers))
                self.assertIn(words, d["bot_messages"][0])
                self.assertIn("처리 완료", d["bot_messages"][0])
                self.assertEqual(d["options"], [])
                # 화면은 end 면 plan 을 부르지 않는다. 직접 불러도 500·'메뉴 가격' 오류가 아니라 같은 끝 안내 (409)
                plan = self.client.post("/api/marketing-survey/plan", json={"state": d["state"]}, params={"store": sid})
                self.assertEqual(plan.status_code, 409, plan.text)
                self.assertIn("처리 완료", plan.json()["detail"])

    def test_coupon_path_still_reaches_a_decision(self):
        a = self._approved()
        d = self._step(a["state"], "100,000원")
        self.assertEqual(d["state"]["node"], "discount_allowed")
        d = self._step(d["state"], "예")
        self.assertEqual(d["state"]["node"], "menu")
        self.assertTrue(d["options"])

    def test_store_without_menu_prices_skips_the_empty_menu_question_and_says_why(self):
        """메뉴 가격이 없는 가게: '할인 메뉴'에 고를 보기가 없어 질문이 멈추던 것 → 끝으로 가고 이유를 말한다."""
        ctx = _ctx(menu_prices={})
        state = {"raw": {"budget_won": 50_000}, "confirms": {}}
        self.assertEqual(flow.advance("discount_allowed", ctx, state, "예"), flow.DECISION)
        message = follow_up_end_message(ctx, answers_from_raw(state["raw"]))
        self.assertIn("메뉴 가격", message)
        self.assertIn("처리 완료", message)
        # 맞춤 홍보 제안(설문)에서도 같은 경우 '지금은 유지'에 이유가 보인다
        plan = decide(ctx, answers_from_raw({**state["raw"], "goal": "새 손님"}), confirms={})
        self.assertEqual(plan.strategies[0].type, "no_action")
        self.assertIn("메뉴 가격", plan.strategies[0].reason)

    def test_store_without_a_notice_does_not_continue_with_after_notice_questions(self):
        """반복 불만 자료가 없어 안내문을 못 만든 새 가게는 '안내문 승인 뒤' 질문으로 잇지 않는다 (승인한 안내문이 없으므로)."""
        original = stores.get_ctx
        with patch("marketing_survey.stores.get_ctx", side_effect=lambda sid: _ctx() if sid == TEST_STORE.store_id else original(sid)):
            sid = TEST_STORE.store_id
            data = self.client.post("/api/marketing-survey/step", json={"state": None, "answer": None}, params={"store": sid}).json()
            for a in ("맞춤 홍보 제안", "예", "포장 누락"):
                data = self._step(data["state"], a, sid)
            plan = self.client.post("/api/marketing-survey/plan", json={"state": data["state"]}, params={"store": sid}).json()
            self.assertEqual({u["step_id"] for u in plan["unavailable_drafts"]}, {"notice", "reply"})
            approved = self.client.post("/api/marketing-survey/approve", json={"state": data["state"]}, params={"store": sid}).json()
        self.assertFalse(approved["follow_up"])

    def test_follow_up_with_coupon_answers_is_not_an_end(self):
        ctx = stores.get_ctx("store_ongi")
        raw = {"budget_won": 100_000, "discount_allowed": True, "discount_menu": "제육볶음 정식", "max_discount_won": 1900}
        self.assertIsNone(follow_up_end_message(ctx, answers_from_raw(raw)))


class TestThisWeekTodosHaveNoLaterRecheck(unittest.TestCase):
    """M-A4: '이번 주 할 일'(steps)에 14일 뒤 재측정이 없고, 언제 무엇을 비교할지는 '측정' 줄에 그대로."""

    def test_no_step_is_dated_two_weeks_later(self):
        later = TODAY + timedelta(days=14)
        later_label = f"{later.month}/{later.day}"
        cases = [
            (stores.get_ctx("store_ongi"), {"H_REPEAT": "예"}, {}),
            (stores.get_ctx("store_basak"), {"H_LATE": "예"}, {}),
            (stores.get_ctx("store_ongi"), {}, {"budget_won": 100_000, "goal": "재주문", "discount_menu": "제육볶음 정식",
                                                "max_discount_won": 1900, "weekly_hours": 5}),
        ]
        for ctx, confirms, raw in cases:
            answers = answers_from_raw({"weekly_hours": 5, **raw})
            strategy = decide(ctx, answers, confirms=confirms).strategies[0]
            pb = playbooks.build_playbook(ctx, strategy, answers, today=TODAY)
            self.assertTrue(pb["steps"], strategy.type)
            for s in pb["steps"]:
                self.assertNotIn(later_label, s["when"], (strategy.type, s))
                self.assertNotIn("다시 세기", s["what"])
            self.assertIn(f"측정: {later_label}", pb["measure"], strategy.type)


class TestReportUsesNoticeTopic(unittest.TestCase):
    """보고서의 '불만 재발' 칸도 승인한 안내문의 주제로 센다 (예전엔 늘 '포장 누락'·불만 카드)."""

    def test_fixed_row_names_the_approved_topic(self):
        ctx = stores.get_ctx("store_basak")
        start, end = date(2026, 11, 1), date(2026, 11, 30)
        rows = []
        for topic in (MISSING_TOPIC, "texture", None):
            rows.append({"decision": "approved", "result": {"kinds": ["공지"]}, "created_at": "2026-11-10T10:00:00+09:00",
                         "answers": {"complaint_topic": topic} if topic else {}})
        fixed = report._fixed(rows, ctx, start, end, TODAY)
        self.assertEqual([f["complaint"] for f in fixed], ["포장 누락", "식감", "포장 누락"])


if __name__ == "__main__":
    unittest.main()
