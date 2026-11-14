"""C6 mentions_unknown_menu 점검 — 메뉴에 있는 음식을 '없는 음식'으로 잘못 잡지 않는지. AI 호출 없음.

메뉴 이름을 글에서 먼저 지우고(긴 것부터, 띄어쓰기 조각 2글자 이상 포함), 남은 글에서만 일반 음식 낱말을 찾는다.
"""

import unittest

from c6 import checks
from shared.sample_scenario import SAMPLE_STORE

MENU = ["제육볶음 정식", "된장찌개", "김치찌개", "순두부찌개", "불고기 덮밥", "계란말이"]


class TestUnknownMenu(unittest.TestCase):
    def test_sample_menu_is_the_one_these_cases_assume(self):
        self.assertEqual(list(SAMPLE_STORE.menu), MENU)

    def test_menu_items_are_not_flagged(self):
        for text in ("된장찌개를 소개합니다", "김치찌개 한 그릇", "순두부찌개",
                     "불고기 덮밥 어떠세요", "불고기가 인기예요", "제육볶음 정식 1,000원 할인"):
            with self.subTest(text=text):
                self.assertFalse(checks.mentions_unknown_menu(text, MENU))

    def test_food_not_on_the_menu_is_still_flagged(self):
        for text in ("부대찌개도 있어요", "삼겹살 구워 드려요", "돼지고기 듬뿍",
                     "치킨 한 마리", "커피 한 잔", "된장찌개와 삼겹살"):
            with self.subTest(text=text):
                self.assertTrue(checks.mentions_unknown_menu(text, MENU))

    def test_empty_menu_flags_any_generic_food_word_as_before(self):
        self.assertTrue(checks.mentions_unknown_menu("된장찌개를 소개합니다", []))
        self.assertTrue(checks.mentions_unknown_menu("불고기가 인기예요", []))
        self.assertTrue(checks.mentions_unknown_menu("치킨 한 마리", []))
        self.assertFalse(checks.mentions_unknown_menu("오늘도 감사합니다", []))

    def test_menu_name_piece_without_space_is_kept(self):
        # '불고기 덮밥'을 붙여 써도 조각('불고기', '덮밥')으로 지워진다
        self.assertFalse(checks.mentions_unknown_menu("불고기덮밥 어떠세요", MENU))

    def test_unknown_food_stuck_to_a_menu_piece_is_still_flagged(self):
        # '덮밥'을 지우고 나면 '치킨'이 남는다
        self.assertTrue(checks.mentions_unknown_menu("치킨덮밥 어떠세요", MENU))

    def test_menu_name_equal_to_a_food_word_is_still_allowed(self):
        self.assertFalse(checks.mentions_unknown_menu("치킨 한 마리", ["치킨", "피자"]))
        self.assertTrue(checks.mentions_unknown_menu("커피 한 잔", ["치킨", "피자"]))

    def test_longer_menu_name_is_removed_before_its_part(self):
        # '김치'를 먼저 지우면 '찌개'가 남아 걸린다. 긴 '김치찌개'부터 지워야 한다
        self.assertFalse(checks.mentions_unknown_menu("김치찌개 한 그릇", ["김치", "김치찌개"]))

    def test_menu_names_with_odd_spacing_do_not_break_it(self):
        self.assertFalse(checks.mentions_unknown_menu("불고기 덮밥", ["  불고기   덮밥 ", ""]))
        self.assertTrue(checks.mentions_unknown_menu("삼겹살", ["  불고기   덮밥 ", ""]))


if __name__ == "__main__":
    unittest.main()
