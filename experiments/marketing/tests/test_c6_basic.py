"""C6 기본 검증 — 계약 dataclass 기준, AI 호출 없음."""

import unittest

from shared.sample_scenario import SAMPLE_STORE, SAMPLE_TONE
from c6.contract import build_context
from c6 import checks
from c6.style import owner_style
from c6.dummy import OWNER_REPLIES
from c6.output import DraftOutput, CardResult


class TestBuildContext(unittest.TestCase):
    def test_defaults_use_sample(self):
        ctx = build_context()
        self.assertEqual(ctx.store.store_id, "store_ongi")
        self.assertEqual(ctx.store.name, "온기한식 (가상)")
        self.assertEqual(len(ctx.reviews), 3)
        self.assertTrue(all("팀 데이터에 없음" in n for n in ctx.needs_input))

    def test_full_args_no_needs(self):
        ctx = build_context(
            store=SAMPLE_STORE,
            reviews=[],
            tone=SAMPLE_TONE,
            cards=[],
            snapshots=[],
            owner_replies=["테스트"],
            policies=[],
        )
        self.assertEqual(ctx.needs_input, [])


MENU_NAMES = list(SAMPLE_STORE.menu)
ALLOWED_PRICES = list(SAMPLE_STORE.menu_prices.values())

BAD = [
    "제육볶음 정식 10000원에 드시면 됩니다.",
    "다음에 쿠폰 드릴게요!",
    "삼겹살이랑 같이 드셔 보세요.",
    "김철수님 감사합니다!",
    "010-1234-5678로 연락 주세요.",
    "서울시 성동구 성수동 12길 34로 오세요.",
]

POLICIES = [
    {"policy_id": "P1", "text": "누락 품목은 다음 주문 요청사항에 적어 주시면 챙겨 드리겠습니다."},
    {"policy_id": "P3", "text": "리뷰 답글에 금전 보상(쿠폰·할인·무료 제공 등)을 약속하지 않습니다."},
]


class TestChecks(unittest.TestCase):
    def test_has_number_bad(self):
        self.assertTrue(checks.has_number_not_in(BAD[0], ALLOWED_PRICES))

    def test_has_number_good(self):
        self.assertFalse(checks.has_number_not_in("제육볶음 정식 9,500원이에요.", ALLOWED_PRICES))

    def test_promises_bad(self):
        self.assertTrue(checks.promises_not_in_policy(BAD[1], POLICIES))

    def test_promises_good(self):
        self.assertFalse(checks.promises_not_in_policy("감사합니다!", POLICIES))

    def test_unknown_menu_bad(self):
        self.assertTrue(checks.mentions_unknown_menu(BAD[2], MENU_NAMES))

    def test_unknown_menu_good(self):
        self.assertFalse(checks.mentions_unknown_menu("제육볶음 정식 감사합니다.", MENU_NAMES))

    def test_personal_info_name(self):
        self.assertTrue(checks.personal_info(BAD[3]))

    def test_personal_info_phone(self):
        self.assertTrue(checks.personal_info(BAD[4]))

    def test_personal_info_address(self):
        self.assertTrue(checks.personal_info(BAD[5]))

    def test_personal_info_good(self):
        self.assertFalse(checks.personal_info("고객님 감사합니다."))

    def test_forbidden_phrase_hit(self):
        self.assertTrue(checks.forbidden_phrase("배달 기사님 탓이에요", ["배달 기사님 탓", "플랫폼 문제"]))

    def test_forbidden_phrase_clean(self):
        self.assertFalse(checks.forbidden_phrase("죄송합니다", ["배달 기사님 탓", "플랫폼 문제"]))

    def test_forbidden_phrase_empty(self):
        self.assertFalse(checks.forbidden_phrase("아무 문장", []))

    def test_too_similar(self):
        self.assertTrue(checks.too_similar("감사합니다 맛있게 드세요", "감사합니다 맛있게 드세요!"))

    def test_not_similar(self):
        self.assertFalse(checks.too_similar("완전히 다른 문장입니다", "배달이 늦어 죄송합니다"))

    def test_length_ok(self):
        self.assertTrue(checks.length_ok("열 글자짜리 문장입니다", 5, 50))
        self.assertFalse(checks.length_ok("짧", 5, 50))

    def test_fix_hints(self):
        hints = checks.fix_hints(["no_bad_number", "no_personal_info"])
        self.assertEqual(len(hints), 2)
        self.assertIn("가격", hints[0])

    def test_fix_hints_forbidden(self):
        hints = checks.fix_hints(["no_forbidden_phrase"])
        self.assertIn("표현", hints[0])


class TestStyle(unittest.TestCase):
    def test_owner_style(self):
        style = owner_style(OWNER_REPLIES)
        self.assertIn("안녕하세요 고객님 :)", style["시작 인사"])
        self.assertIn("온기한식 드림", style["마무리"])
        self.assertIn(style["높임"], ("해요체", "합니다체"))
        self.assertFalse(style["이모지 사용"])
        self.assertIsInstance(style["평균 문장 길이"], float)

    def test_empty_replies(self):
        self.assertEqual(owner_style([]), {})


class TestOutput(unittest.TestCase):
    def test_draft_output_validation(self):
        with self.assertRaises(ValueError):
            DraftOutput(draft_id="d1", card_id="c1", store_id="s1",
                        generator="unknown", text="test")
        with self.assertRaises(ValueError):
            DraftOutput(draft_id="", card_id="c1", store_id="s1",
                        generator="reply_draft", text="test")

    def test_draft_output_roundtrip(self):
        d = DraftOutput(
            draft_id="d1", card_id="c1", store_id="s1",
            generator="reply_draft", text="test",
            target_review_id="rv_001",
        )
        d2 = DraftOutput.from_dict(d.to_dict())
        self.assertEqual(d.draft_id, d2.draft_id)
        self.assertEqual(d.generator, d2.generator)
        self.assertEqual(d.target_review_id, d2.target_review_id)

    def test_card_result_validation(self):
        with self.assertRaises(ValueError):
            CardResult(card_id="", kind="complaint", reason_text="이유")

    def test_card_result_roundtrip(self):
        draft = DraftOutput(
            draft_id="d1", card_id="c1", store_id="s1",
            generator="reply_draft", text="test",
        )
        cr = CardResult(
            card_id="c1", kind="complaint", reason_text="이유",
            basis_label="기준: 2026 2분기", drafts=[draft],
        )
        cr2 = CardResult.from_dict(cr.to_dict())
        self.assertEqual(cr2.card_id, "c1")
        self.assertEqual(len(cr2.drafts), 1)
        self.assertEqual(cr2.drafts[0].generator, "reply_draft")


if __name__ == "__main__":
    unittest.main()
