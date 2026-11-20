"""불만 주제별 답글·안내문 (11/21 실시간 품질 확인 M1·M2) — 가짜 응답, 네트워크 없음.

가게가 예시 3곳 + 직접 등록한 가게로 늘면서, 포장 누락이 아닌 불만(눅눅한 치킨·긴 대기·새는 국물)에도 답글에
"포장 마감 전에 주문서와 대조해 빠지는 게 없도록"(조치 M1)·"요청사항에 적어 주시면"(P1)이 붙고, 기본 문장은
"주문하신 품목이 빠져 있었다니"였다. 이제 조치·요청사항·기본 문장을 리뷰의 불만 주제로 고른다.

실행 (experiments/marketing 에서): python -m pytest -q tests/test_c6_reply_topic.py
리뷰 글은 모두 이 시험을 위해 지어낸 합성 문장이다.
"""

import unittest
from unittest.mock import patch

from shared.contracts import RecommendationCard, ReviewRecord
from shared.sample_scenario import SAMPLE_REVIEWS, SAMPLE_STORE, SAMPLE_TONE

from c6 import checks
from c6.contract import build_context
from c6.dummy import OWNER_REPLIES, POLICIES
from c6.measures import (M1_SENTENCES, NEUTRAL_LINES, OTHER_FALLBACK, P1_SENTENCES, TOPIC_FALLBACK_FRAMES, TOPIC_PHRASES,
                         measures_for_topics)
from c6.notice import _notice_fallback_text, generate_prevention_notice
from c6.reply import _fallback_sentence, generate_reply_draft, reply_topic

M5 = {"id": "M5", "text": "배달 파트너사에 온도 유지 요청"}


def review(rid, text, neg=(), rating=2, topics=None):
    return ReviewRecord(review_id=rid, store_id=SAMPLE_STORE.store_id, text=text, created_at="2026-11-14T19:00:00+09:00",
                        rating=rating, input_method="paste", sentiment="negative" if neg else None,
                        topics=list(topics if topics is not None else neg), negative_topics=list(neg))


def run(reviews, answer, chosen=None):
    card = RecommendationCard(card_id="card_t", store_id=SAMPLE_STORE.store_id, kind="complaint", reason_text="시험",
                              review_ids=[r.review_id for r in reviews])
    ctx = build_context(store=SAMPLE_STORE, reviews=list(reviews), tone=SAMPLE_TONE, cards=[card], snapshots=[],
                        owner_replies=OWNER_REPLIES, policies=POLICIES)
    prompts = []

    def fake(key, system, messages, **kw):
        prompts.append(system)
        return {"content": answer(messages[0]["content"]) if callable(answer) else answer, "won": 0.0}

    with patch("clova.call", side_effect=fake):
        return generate_reply_draft(ctx, card, "k", chosen_measures=chosen).drafts, prompts


SOGGY = review("rv_t_soggy", "튀김옷이 눅눅해서 바삭한 맛이 없었어요", ["texture"])
WAIT = review("rv_t_wait", "주문이 밀려서 한참 기다렸어요", ["wait_time"])
SOUP = review("rv_t_soup", "떡볶이 국물이 포장 밖으로 다 새서 왔어요", ["packaging"])
COLD = review("rv_t_cold", "치킨이 다 식어서 왔어요", ["temperature"])


class TestTopic(unittest.TestCase):
    def test_reply_topic(self):
        self.assertEqual(reply_topic(SAMPLE_REVIEWS[0]), "missing_item")
        self.assertEqual(reply_topic(SOGGY), "texture")
        self.assertEqual(reply_topic(review("a", "국물이 새고 늦게 왔어요", ["delivery_time", "packaging"])), "packaging")
        self.assertEqual(reply_topic(review("b", "계란말이가 빠졌어요")), "missing_item")    # 분류 없음 + 빠짐 표현
        self.assertEqual(reply_topic(review("c", "별로였어요")), "other")                   # 분류 없음
        self.assertEqual(reply_topic(review("d", "맛있어요", [], 4, ["taste"])), "other")   # 불만 주제가 없음

    def test_measure_options_by_topic(self):
        self.assertEqual(measures_for_topics(["missing_item"]), ["M1", "M2", "M3", "M4"])
        self.assertEqual(measures_for_topics(["temperature"]), ["M5"])
        self.assertEqual(measures_for_topics(["texture"]), [])
        self.assertEqual(measures_for_topics(["wait_time"]), [])


class TestReplyByTopic(unittest.TestCase):
    GOOD = {"rv_t_soggy": "튀김옷이 눅눅해서 많이 아쉬우셨겠어요. 정말 죄송해요.",
            "rv_t_wait": "한참 기다리시게 해서 정말 죄송해요.",
            "rv_t_soup": "국물이 새서 받으셨다니 정말 죄송해요."}

    def answer(self, content):
        return next(v for k, v in self.GOOD.items() if k in content)

    def test_no_missing_item_measure_on_other_topics(self):
        drafts, prompts = run([SOGGY, WAIT, SOUP], self.answer)
        for d in drafts:
            with self.subTest(d.target_review_id):
                self.assertNotIn("주문서", d.text)
                self.assertNotIn("요청사항", d.text)
                self.assertNotIn("빠지", d.text)
                self.assertFalse(d.checks["used_fallback"])
                self.assertEqual(d.failed_reasons, [])
                self.assertEqual(d.evidence_ids, [f"F_{d.target_review_id}"])
                self.assertTrue(any(line in d.text for line in NEUTRAL_LINES["해요체"]))
        self.assertTrue(all("빠진 품목을 구체적으로" not in p for p in prompts))
        self.assertTrue(any("'식감' 불편" in p for p in prompts))

    def test_missing_item_reply_is_unchanged(self):
        drafts, _ = run([SAMPLE_REVIEWS[0]], "공깃밥이 빠져 있었다니 정말 죄송해요.")
        d = drafts[0]
        self.assertIn(M1_SENTENCES["해요체"][0], d.text)
        self.assertIn(P1_SENTENCES["해요체"][0], d.text)
        self.assertEqual(d.evidence_ids, [f"F_{SAMPLE_REVIEWS[0].review_id}", "M1", "P1"])

    def test_chosen_measure_that_fits_the_topic(self):
        drafts, _ = run([COLD], "치킨이 식어서 왔다니 정말 죄송해요.", chosen=[M5])
        d = drafts[0]
        self.assertIn("배달 파트너사에 음식 온도", d.text)
        self.assertEqual(d.evidence_ids, ["F_rv_t_cold", "M5"])
        self.assertEqual(d.failed_reasons, [])
        self.assertTrue(d.checks["chosen_measure_included"] and d.checks["no_invented_measure"])

    def test_chosen_measure_that_does_not_fit_is_not_added(self):
        drafts, _ = run([SOGGY], self.GOOD["rv_t_soggy"], chosen=[{"id": "M1", "text": "포장 마감 전 주문서 대조"}])
        self.assertNotIn("주문서", drafts[0].text)
        self.assertEqual(drafts[0].evidence_ids, ["F_rv_t_soggy"])

    def test_fallback_speaks_about_the_topic(self):
        drafts, _ = run([SOGGY, WAIT, SOUP], "앞으로 꼭 챙길게요.")   # 늘 약속만 → 기본 문장
        texts = {d.target_review_id: d.text for d in drafts}
        for d in drafts:
            self.assertTrue(d.checks["used_fallback"])
            self.assertNotIn("빠져", d.text)
            self.assertNotIn("주문하신 품목", d.text)
            self.assertEqual(d.failed_reasons, [])
        self.assertIn("식감", texts["rv_t_soggy"])
        self.assertIn("기다리셨다니", texts["rv_t_wait"])
        self.assertIn("포장이", texts["rv_t_soup"])

    def test_promise_from_the_ai_is_removed_not_kept(self):
        drafts, _ = run([SOGGY], "튀김옷이 눅눅했다니 정말 속상해요. 다음에는 꼭 바삭하게 드실 수 있도록 더 신경 쓸게요.")
        d = drafts[0]
        self.assertFalse(d.checks["used_fallback"])
        self.assertTrue(d.checks["ai_part_repaired"])
        self.assertNotIn("신경 쓸게요", d.text)
        self.assertIn("튀김옷이 눅눅했다니 정말 속상해요. 진심으로 죄송해요.", d.text)


class TestTemplates(unittest.TestCase):
    """주제별 기본 문장·약속 없는 문장은 점검을 모두 넘는다."""

    def assert_ai_part_ok(self, text, register):
        style = "haeyo" if register == "해요체" else "hamnida"
        self.assertTrue(checks.has_apology_anywhere(text), text)
        self.assertTrue(checks.ai_part_only_empathy(text), text)
        self.assertTrue(checks.style_match(text, style), text)
        self.assertFalse(checks.has_stiff_words(text), text)
        self.assertTrue(checks.no_broken_ending(text), text)
        self.assertFalse(checks.has_claimed_action(text), text)

    def test_topic_fallbacks(self):
        for register in ("해요체", "합니다체"):
            for topic in [*TOPIC_PHRASES, "other"]:
                for idx in range(3):
                    text = _fallback_sentence(review("x", "글", [topic] if topic != "other" else []), [], register, idx, topic)
                    with self.subTest(register=register, topic=topic, idx=idx):
                        self.assert_ai_part_ok(text, register)
            self.assertEqual(len(TOPIC_FALLBACK_FRAMES[register]), 3)
            self.assertEqual(len(OTHER_FALLBACK[register]), 3)

    def test_rotating_variants_differ(self):
        texts = {_fallback_sentence(SOGGY, [], "해요체", i) for i in range(3)}
        self.assertEqual(len(texts), 3)

    def test_neutral_lines_make_no_promise_of_a_measure(self):
        for register, lines in NEUTRAL_LINES.items():
            for line in lines:
                with self.subTest(line=line):
                    self.assertFalse(checks.has_invented_measure(line, []))
                    self.assertFalse(checks.has_overpromise(line))
                    self.assertFalse(checks.has_claimed_action(line))


class TestChecks(unittest.TestCase):
    def test_promise_endings(self):
        for bad in ("더 신경 쓸게요.", "포장해서 보낼게요.", "다시 한번 확인해야겠네요.", "더욱 신경 쓰겠습니다.",
                    "주의하도록 하겠습니다."):
            self.assertFalse(checks.ai_part_only_empathy(bad), bad)
        for ok in ("정말 속상하시겠어요.", "많이 불편하셨겠습니다.", "아쉬우셨겠어요, 죄송해요.", "정말 죄송해요."):
            self.assertTrue(checks.ai_part_only_empathy(ok), ok)

    def test_ihae_is_not_a_broken_ending(self):
        self.assertTrue(checks.no_broken_ending("답답하셨을 마음 충분히 이해해요."))
        self.assertFalse(checks.no_broken_ending("적어해해 주세요"))

    def test_jyo_is_haeyo(self):
        self.assertTrue(checks.style_match("치킨 먹는 재미가 없죠. 정말 죄송해요.", "haeyo"))
        self.assertFalse(checks.style_match("치킨 먹는 재미가 없죠. 정말 죄송합니다.", "haeyo"))

    def test_common_formal_endings_to_haeyo(self):
        self.assertEqual(checks.to_haeyo_endings("실망감을 잘 알고 있습니다. 마음 충분히 이해합니다."),
                         "실망감을 잘 알고 있어요. 마음 충분히 이해해요.")
        self.assertEqual(checks.to_haeyo_endings("더 신경 쓰겠습니다."), "더 신경 쓰겠습니다.")   # 약속은 바꾸지 않는다

    def test_guessed_cause(self):
        self.assertTrue(checks.guessed_cause("배달 과정에서 시간이 지체되어 이런 문제가 발생한 것으로 보입니다."))
        self.assertTrue(checks.guessed_cause("주문이 몰렸기 때문에 늦었습니다."))
        self.assertFalse(checks.guessed_cause("최근 음료를 오래 기다리셨다는 말씀이 이어졌습니다."))


class TestNoticeByTopic(unittest.TestCase):
    def test_general_fallback_has_no_missing_item_words(self):
        for rv in (SOGGY, WAIT, SOUP):
            text = _notice_fallback_text([rv, rv], [], [], "오늘부터")
            with self.subTest(text=text):
                self.assertNotIn("빠진", text)
                self.assertNotIn("요청사항", text)
                self.assertIn(TOPIC_PHRASES[rv.negative_topics[0]]["notice"], text)

    def test_missing_fallback_unchanged(self):
        text = _notice_fallback_text([SAMPLE_REVIEWS[0]], list(SAMPLE_STORE.menu), [{"id": "M1", "text": "x"}], "오늘부터")
        self.assertIn("빠진 상태로 배달된 일이 있었습니다", text)
        self.assertIn("요청사항에 적어 주세요", text)

    def test_general_notice_prompt_and_fallback_pass_checks(self):
        card = RecommendationCard(card_id="card_t", store_id=SAMPLE_STORE.store_id, kind="complaint", reason_text="시험",
                                  review_ids=[SOGGY.review_id, WAIT.review_id])
        ctx = build_context(store=SAMPLE_STORE, reviews=[SOGGY, WAIT], tone=SAMPLE_TONE, cards=[card], snapshots=[],
                            owner_replies=OWNER_REPLIES, policies=POLICIES)
        seen = []
        bad = "배달 과정에서 시간이 지체되어 식감이 떨어진 것으로 보입니다.\n불편을 드려 죄송합니다.\n오늘부터 더 신경 쓰겠습니다.\n다른 불편한 점이 있으면 리뷰로 알려 주세요."

        def fake(key, system, messages, **kw):
            seen.append(system)
            return {"content": bad, "won": 0.0}

        with patch("clova.call", side_effect=fake):
            d = generate_prevention_notice(ctx, card, "k").drafts[0]
        self.assertNotIn("빠졌던 품목", seen[0])
        self.assertNotIn("요청사항에 적어 주시면", seen[0])
        self.assertTrue(d.checks["used_fallback"])        # 원인을 짐작한 글은 다시 써도 그대로라 템플릿으로
        self.assertEqual(d.failed_reasons, [])
        self.assertNotIn("것으로 보입니다", d.text)
        self.assertTrue(d.text.startswith("[안내] 식감 관련") or d.text.startswith("[안내] 매장 대기 관련"), d.text)

    def test_general_notice_measure_line_is_written_by_code(self):
        """고른 조치가 없는 포장 누락 밖 공지: AI 가 지어낸 '오늘부터' 조치 줄을 코드 문장으로 바꾼다."""
        from c6.notice import GENERAL_NOTICE_MEASURE
        card = RecommendationCard(card_id="card_t", store_id=SAMPLE_STORE.store_id, kind="complaint", reason_text="시험",
                                  review_ids=[WAIT.review_id])
        ctx = build_context(store=SAMPLE_STORE, reviews=[WAIT], tone=SAMPLE_TONE, cards=[card], snapshots=[],
                            owner_replies=OWNER_REPLIES, policies=POLICIES)
        ai = ("최근 음료를 오래 기다리셨다는 말씀이 이어졌습니다.\n불편을 드려 죄송합니다.\n"
              "오늘부터 대기 예상 시간을 미리 안내하고 주문을 유도하겠습니다.\n다른 불편한 점이 있으면 리뷰로 알려 주세요.")
        with patch("clova.call", side_effect=lambda *a, **k: {"content": ai, "won": 0.0}):
            d = generate_prevention_notice(ctx, card, "k").drafts[0]
        self.assertIn(f"오늘부터 {GENERAL_NOTICE_MEASURE}", d.text)
        self.assertNotIn("유도", d.text)
        later = ai.replace("오늘부터 대기 예상", "앞으로 대기 예상")      # '앞으로'로 시작한 조치 줄도 바꾼다
        with patch("clova.call", side_effect=lambda *a, **k: {"content": later, "won": 0.0}):
            d2 = generate_prevention_notice(ctx, card, "k").drafts[0]
        self.assertIn(f"오늘부터 {GENERAL_NOTICE_MEASURE}", d2.text)
        self.assertNotIn("유도", d2.text)
        self.assertEqual(d2.failed_reasons, [])
        self.assertFalse(d.checks["used_fallback"])
        self.assertTrue(d.checks["ai_part_repaired"])
        self.assertEqual(d.failed_reasons, [])


if __name__ == "__main__":
    unittest.main()
