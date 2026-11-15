"""① 가게 과실 답글의 사과 포함 점검(apology_expressed)  ② AI 호출이 끝내 실패했을 때의 마무리 — 가짜 응답, 네트워크 없음.

실행 (experiments/marketing 에서):
  python -m pytest -q tests/test_c6_apology_and_call_failure.py      또는      python -m tests.test_c6_apology_and_call_failure
리뷰·답글 문장은 모두 이 시험을 위해 지어낸 합성 문장이다 (데모 가게 온기한식).
"""

import unittest
from unittest.mock import patch

from shared.contracts import RecommendationCard, ReviewRecord
from shared.sample_scenario import SAMPLE_CARDS, SAMPLE_REVIEWS, SAMPLE_SNAPSHOTS, SAMPLE_STORE, SAMPLE_TONE

from c6 import checks
from c6.contract import build_context
from c6.dummy import OWNER_REPLIES, POLICIES
from c6.measures import MEASURES
from c6.notice import generate_prevention_notice
from c6.output import CALL_FAILED_NOTE, CALL_FAILED_NOTE_NO_TEXT
from c6.promo import generate_coupon_promo
from c6.reply import _missing_items, fallback_apology, generate_reply_draft
from c6.stance import APOLOGY, APOLOGY_CHECKS

FAIL = {"error": "TimeoutError: The read operation timed out"}
CTX = build_context(store=SAMPLE_STORE, reviews=list(SAMPLE_REVIEWS), tone=SAMPLE_TONE, cards=list(SAMPLE_CARDS),
                    snapshots=list(SAMPLE_SNAPSHOTS), owner_replies=OWNER_REPLIES, policies=POLICIES)
COMPLAINT = next(c for c in SAMPLE_CARDS if c.kind == "complaint")
PROMO = next(c for c in SAMPLE_CARDS if c.kind == "promo")
MENU = list(SAMPLE_STORE.menu)


def one_review_ctx():
    review = SAMPLE_REVIEWS[0]    # 공깃밥이 빠졌다는 리뷰
    card = RecommendationCard(card_id="card_t", store_id=SAMPLE_STORE.store_id, kind="complaint", reason_text="시험",
                              review_ids=[review.review_id])
    ctx = build_context(store=SAMPLE_STORE, reviews=list(SAMPLE_REVIEWS), tone=SAMPLE_TONE, cards=[card], snapshots=[],
                        owner_replies=OWNER_REPLIES, policies=POLICIES)
    return ctx, card, review


NO_APOLOGY = "주문하신 공깃밥이 빠진 건 저희가 확인해 볼게요. 소중한 리뷰 감사해요."
# PR #36 부터 AI 는 공감·사과 부분만 쓴다 (조치·요청사항·감사 인사는 코드가 붙임) → 다시 쓴 글도 그 모양
APOLOGY_ONLY = "공깃밥이 빠진 채로 가서 정말 죄송해요."
WITH_APOLOGY = "주문하신 공깃밥이 빠져서 정말 죄송해요. 앞으로 더 꼼꼼히 챙겨 볼게요. 소중한 리뷰 감사해요."


class TestApologyAnywhere(unittest.TestCase):
    def test_apology_words(self):
        for text in ("정말 죄송해요", "죄송합니다", "사과드립니다", "사과 말씀 드려요", "미안해요", "불찰이었어요", "송구합니다",
                     "불편을 드려 마음이 무거워요", "불편 드려서", "불편을 끼쳐 드렸어요", "불편하게 해 드렸네요", "첫 문장은 아니어도 끝에 죄송해요"):
            with self.subTest(text=text):
                self.assertTrue(checks.has_apology_anywhere(text))

    def test_not_apologies(self):
        for text in ("음식 바꾸는 건 원래 어렵지만 다시 한번 살펴볼게요", "많이 속상하셨겠어요", "아쉬우셨을 것 같아요",
                     "저희 실수예요", "확인해 볼게요", "", None):
            with self.subTest(text=text):
                self.assertFalse(checks.has_apology_anywhere(text))

    def test_has_apology_meaning_is_unchanged(self):
        """공지 점검 has_apology 는 앞부분만 본다 (PR #36 에서 '첫 문장' → '처음 두 문장'). 새 점검은 글 어디든 본다."""
        text = "주문 확인해 볼게요. 꼼꼼히 살펴볼게요. 정말 죄송해요."
        self.assertFalse(checks.has_apology(text))
        self.assertTrue(checks.has_apology_anywhere(text))

    def test_it_is_part_of_the_apology_check_set(self):
        self.assertIn("apology_expressed", APOLOGY_CHECKS)
        self.assertIn("죄송", checks.fix_hints(["apology_expressed"])[0])


class TestApologyInReply(unittest.TestCase):
    def test_reply_without_apology_is_rewritten_once(self):
        ctx, card, _ = one_review_ctx()
        prompts = []

        def fake(key, system, messages, **kw):
            prompts.append(messages[0]["content"])
            return {"content": APOLOGY_ONLY if "수정 지시" in messages[0]["content"] else NO_APOLOGY, "won": 0.01}

        with patch("clova.call", side_effect=fake):
            d = generate_reply_draft(ctx, card, "k").drafts[0]
        self.assertEqual(len(prompts), 2)
        self.assertIn("죄송하다는 사과", prompts[1])        # 고칠 점이 프롬프트에 실린다
        self.assertEqual(d.stance, APOLOGY)
        self.assertEqual(d.rewrites, 1)
        self.assertTrue(d.checks["apology_expressed"])
        self.assertEqual(d.failed_reasons, [])
        self.assertIn("죄송", d.text)

    def test_reply_that_stays_without_apology_still_ends_with_an_apology(self):
        """끝까지 사과 없는 AI 글은 내보내지 않는다. PR #36 부터는 다시 쓰기 2번 뒤 코드 템플릿(사과 포함)으로 바뀐다."""
        ctx, card, _ = one_review_ctx()
        with patch("clova.call", side_effect=lambda *a, **k: {"content": NO_APOLOGY}) as call:
            d = generate_reply_draft(ctx, card, "k").drafts[0]
        self.assertEqual(call.call_count, 3)                 # 처음 1번 + 다시 쓰기 2번
        self.assertTrue(d.checks["used_fallback"])
        self.assertTrue(d.checks["apology_expressed"])
        self.assertIn("죄송", d.text)
        self.assertNotIn("확인해 볼게요", d.text)             # 사과 없는 AI 글은 남지 않는다
        self.assertEqual(d.failed_reasons, [])

    def test_reply_with_apology_anywhere_passes(self):
        ctx, card, _ = one_review_ctx()
        late = "주문하신 공깃밥이 빠진 건 꼼꼼히 확인해 볼게요. 소중한 리뷰 감사해요. 불편을 드려 죄송해요."
        with patch("clova.call", side_effect=lambda *a, **k: {"content": late}) as call:
            d = generate_reply_draft(ctx, card, "k").drafts[0]
        self.assertEqual(call.call_count, 1)
        self.assertTrue(d.checks["apology_expressed"])
        self.assertEqual(d.failed_reasons, [])


class TestCallFailure(unittest.TestCase):
    """clova.call 이 재시도까지 하고도 {"error": ...} 를 돌려준 경우. 예외로 죽지 않고, 기본 문장 + '확인 필요'로 끝난다."""

    def test_reply_falls_back_to_a_code_written_apology(self):
        with patch("clova.call", side_effect=lambda *a, **k: dict(FAIL)) as call:
            drafts = generate_reply_draft(CTX, COMPLAINT, "k").drafts
        self.assertEqual(call.call_count, len(drafts))            # 리뷰마다 한 번씩만 부르고 다시 쓰기는 하지 않음
        self.assertEqual(len(drafts), 3)
        for d in drafts:
            self.assertEqual(d.needs_input, [CALL_FAILED_NOTE])
            self.assertEqual(d.failed_reasons, [])                 # 점검 실패가 아니라 '확인 필요'
            self.assertTrue(d.checks["apology_expressed"])
            self.assertTrue(d.checks["not_too_similar"])           # 기본 문장끼리 비슷해도 된다
            self.assertIn("죄송", d.text)
            self.assertTrue(d.text.startswith("안녕하세요") and d.text.endswith("드림"))

    def test_fallback_apology_names_the_missing_item(self):
        review = ReviewRecord(review_id="rv_t_001", store_id=SAMPLE_STORE.store_id, text="계란말이가 빠져 있었어요",
                              created_at="2026-11-14T19:00:00+09:00", rating=2, input_method="paste", sentiment="negative",
                              topics=["missing_item"], negative_topics=["missing_item"])
        self.assertEqual(_missing_items(review.text, MENU), ["계란말이"])
        text = fallback_apology(review, MENU)
        self.assertIn("계란말이", text)
        self.assertTrue(checks.has_apology_anywhere(text))

    def test_fallback_apology_without_a_known_item(self):
        review = ReviewRecord(review_id="rv_t_002", store_id=SAMPLE_STORE.store_id, text="배달이 너무 늦게 왔어요",
                              created_at="2026-11-14T19:00:00+09:00", rating=2, input_method="paste", sentiment="negative",
                              topics=["delivery_time"], negative_topics=["delivery_time"])
        self.assertEqual(_missing_items(review.text, MENU), [])   # 빠진 품목이 없는 리뷰
        text = fallback_apology(review, MENU)
        self.assertTrue(checks.has_apology_anywhere(text))
        self.assertNotIn("건으로", text)

    def test_failed_rewrite_call_keeps_the_ai_text(self):
        """첫 호출은 됐고 다시 쓰기 호출만 실패하면, AI 가 쓴 글을 그대로 두고 점검 실패로 보인다 (기본 문장으로 덮지 않음)."""
        ctx, card, _ = one_review_ctx()
        calls = []

        def fake(key, system, messages, **kw):
            calls.append(messages[0]["content"])
            return dict(FAIL) if "수정 지시" in messages[0]["content"] else {"content": NO_APOLOGY}

        with patch("clova.call", side_effect=fake):
            d = generate_reply_draft(ctx, card, "k").drafts[0]
        self.assertEqual(len(calls), 2)
        self.assertEqual(d.needs_input, [])
        self.assertIn("공깃밥이 빠진 건 저희가 확인해 볼게요", d.text)
        self.assertFalse(d.checks["apology_expressed"])
        self.assertTrue(d.failed_reasons)

    def test_notice_falls_back_with_a_first_sentence_apology(self):
        with patch("clova.call", side_effect=lambda *a, **k: dict(FAIL)) as call:
            d = generate_prevention_notice(CTX, COMPLAINT, "k", chosen_measures=[dict(MEASURES[0])]).drafts[0]
        self.assertEqual(call.call_count, 1)
        self.assertEqual(d.needs_input, [CALL_FAILED_NOTE])
        self.assertEqual(d.failed_reasons, [])
        self.assertTrue(d.checks["has_apology"])
        self.assertIn("죄송", d.text)

    def test_promo_keeps_the_coupon_line_and_asks_the_owner(self):
        with patch("clova.call", side_effect=lambda *a, **k: dict(FAIL)):
            d = generate_coupon_promo(CTX, PROMO, "k").drafts[0]
        self.assertIn(CALL_FAILED_NOTE_NO_TEXT, d.needs_input)
        self.assertTrue(d.text.startswith("🎟"))               # 코드가 만든 쿠폰 줄은 남는다

    def test_working_calls_do_not_get_the_note(self):
        ctx, card, _ = one_review_ctx()
        with patch("clova.call", side_effect=lambda *a, **k: {"content": WITH_APOLOGY}):
            d = generate_reply_draft(ctx, card, "k").drafts[0]
        self.assertEqual(d.needs_input, [])


if __name__ == "__main__":
    unittest.main()
