"""C6 기본 검증 — 더미 데이터 + 나쁜 예시 문장 6개, AI 호출 없음."""

import unittest

from c6.dummy import STORE, REVIEWS, OWNER_REPLIES, POLICIES, CARDS
from c6.contract import to_ctx
from c6 import checks
from c6.style import owner_style


class TestContract(unittest.TestCase):
    def test_to_ctx_full(self):
        raw = {
            "store": STORE,
            "reviews": REVIEWS,
            "owner_replies": OWNER_REPLIES,
            "policies": POLICIES,
            "cards": CARDS,
        }
        ctx = to_ctx(raw)
        non_dummy = [n for n in ctx["needs_input"] if "팀 데이터에 없음" not in n]
        self.assertEqual(non_dummy, [])
        self.assertEqual(ctx["store"]["name"], STORE["name"])

    def test_to_ctx_missing(self):
        ctx = to_ctx({"store": STORE})
        self.assertIn("reviews", ctx["needs_input"])


BAD = [
    "제육덮밥 10000원에 드시면 됩니다.",              # 메뉴에 없는 가격
    "다음에 쿠폰 드릴게요!",                          # 정책에 없는 보상 약속
    "삼겹살이랑 같이 드셔 보세요.",                    # 메뉴에 없는 음식
    "김철수님 감사합니다!",                            # 개인정보(이름)
    "010-1234-5678로 연락 주세요.",                    # 개인정보(전화번호)
    "서울시 성동구 성수동 12길 34로 오세요.",          # 개인정보(주소)
]

MENU_NAMES = [m["name"] for m in STORE["menu"]]
ALLOWED_PRICES = [m["price"] for m in STORE["menu"]]


class TestChecks(unittest.TestCase):
    def test_has_number_bad(self):
        self.assertTrue(checks.has_number_not_in(BAD[0], ALLOWED_PRICES))

    def test_has_number_good(self):
        self.assertFalse(checks.has_number_not_in("제육덮밥 9,500원이에요.", ALLOWED_PRICES))

    def test_promises_bad(self):
        self.assertTrue(checks.promises_not_in_policy(BAD[1], POLICIES))

    def test_promises_good(self):
        self.assertFalse(checks.promises_not_in_policy("감사합니다!", POLICIES))

    def test_unknown_menu_bad(self):
        self.assertTrue(checks.mentions_unknown_menu(BAD[2], MENU_NAMES))

    def test_unknown_menu_good(self):
        self.assertFalse(checks.mentions_unknown_menu("제육덮밥 감사합니다.", MENU_NAMES))

    def test_personal_info_name(self):
        self.assertTrue(checks.personal_info(BAD[3]))

    def test_personal_info_phone(self):
        self.assertTrue(checks.personal_info(BAD[4]))

    def test_personal_info_address(self):
        self.assertTrue(checks.personal_info(BAD[5]))

    def test_personal_info_good(self):
        self.assertFalse(checks.personal_info("고객님 감사합니다."))

    def test_too_similar(self):
        self.assertTrue(checks.too_similar("감사합니다 맛있게 드세요", "감사합니다 맛있게 드세요!"))

    def test_not_similar(self):
        self.assertFalse(checks.too_similar("완전히 다른 문장입니다", "배달이 늦어 죄송합니다"))

    def test_length_ok(self):
        self.assertTrue(checks.length_ok("열 글자짜리 문장입니다", 5, 50))
        self.assertFalse(checks.length_ok("짧", 5, 50))

    def test_fix_hints(self):
        hints = checks.fix_hints(["has_number_not_in", "personal_info"])
        self.assertEqual(len(hints), 2)
        self.assertIn("가격", hints[0])


class TestStyle(unittest.TestCase):
    def test_owner_style(self):
        style = owner_style(OWNER_REPLIES)
        self.assertIn("안녕하세요 고객님 :)", style["시작 인사"])
        self.assertIn("든든한끼 드림", style["마무리"])
        self.assertIn(style["높임"], ("해요체", "합니다체"))
        self.assertFalse(style["이모지 사용"])
        self.assertIsInstance(style["평균 문장 길이"], float)

    def test_empty_replies(self):
        self.assertEqual(owner_style([]), {})


if __name__ == "__main__":
    unittest.main()
