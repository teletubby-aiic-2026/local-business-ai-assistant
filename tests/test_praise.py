"""shared/praise.py: 칭찬 리뷰 고르기와 메뉴 언급 수 (쿠폰 메뉴·카드 ⓑ 근거·리포트 인기 메뉴가 함께 쓰는 기준)."""
from __future__ import annotations

import unittest

from shared.contracts import ReviewRecord
from shared.praise import menu_mentions, menu_variants, pick_praised_menu, praise_reviews, top_praised_menus

MENU = ["제육볶음 정식", "된장찌개", "김치찌개", "순두부찌개", "불고기 덮밥", "계란말이"]


def rv(i, text, rating=5, sentiment=None, negative_topics=()):
    return {"review_id": f"rv_{i:03d}", "text": text, "rating": rating, "sentiment": sentiment,
            "negative_topics": list(negative_topics)}


class PraiseReviewsTest(unittest.TestCase):
    def test_positive_sentiment_first(self):
        reviews = [rv(1, "맛있어요", 5, "positive"), rv(2, "보통", 5, "neutral"), rv(3, "별로", 1, "negative")]
        self.assertEqual([r["review_id"] for r in praise_reviews(reviews)], ["rv_001"])

    def test_fallback_is_high_rating_without_complaint(self):
        reviews = [rv(1, "맛있어요", 5), rv(2, "맛은 좋은데 식었어요", 4, None, ["temperature"]),
                   rv(3, "괜찮아요", 3), rv(4, "좋긴 한데 늦음", 5, "mixed"), rv(5, "별점 없음", None)]
        self.assertEqual([r["review_id"] for r in praise_reviews(reviews)], ["rv_001"])

    def test_accepts_review_records(self):
        record = ReviewRecord(review_id="rv_ongi_900", store_id="store_ongi", text="계란말이 최고", created_at="2026-11-01T12:00:00+09:00",
                              rating=5, sentiment="positive")
        self.assertEqual(praise_reviews([record]), [record])
        self.assertEqual(top_praised_menus(MENU, [record])[0]["menu"], "계란말이")


class MenuMentionsTest(unittest.TestCase):
    def test_variants_skip_generic_and_shared_words(self):
        variants = menu_variants(MENU)
        self.assertEqual(variants["제육볶음 정식"], ("제육볶음정식", "제육볶음"))
        self.assertEqual(variants["불고기 덮밥"], ("불고기덮밥", "불고기"))
        self.assertEqual(variants["된장찌개"], ("된장찌개",))
        # 두 메뉴가 같이 쓰는 낱말은 어느 메뉴인지 알 수 없어 뺀다
        self.assertEqual(menu_variants(["한우 불고기", "돼지 불고기"]), {"한우 불고기": ("한우불고기",), "돼지 불고기": ("돼지불고기",)})

    def test_counts_each_review_once_per_menu(self):
        reviews = [rv(1, "제육볶음 정식 맛있고 제육볶음 양도 많아요"), rv(2, "제육 볶음 정식 좋아요"), rv(3, "정식 맛있어요")]
        rows = {r["menu"]: r for r in menu_mentions(MENU, reviews)}
        self.assertEqual(rows["제육볶음 정식"]["count"], 2)   # 띄어 써도 세고, 한 리뷰는 한 번만
        self.assertEqual(rows["제육볶음 정식"]["review_ids"], ["rv_001", "rv_002"])
        self.assertEqual(sum(r["count"] for r in rows.values()), 2)   # '정식'만으로는 세지 않는다

    def test_top_praised_uses_only_praise_and_keeps_menu_order_on_ties(self):
        reviews = [rv(1, "계란말이 폭신해요", 5, "positive"), rv(2, "계란말이 또 시켜요", 5, "positive"),
                   rv(3, "된장찌개 구수해요", 4, "positive"), rv(4, "김치찌개 칼칼해요", 5, "positive"),
                   rv(5, "제육볶음 너무 짜요", 1, "negative")]
        top = top_praised_menus(MENU, reviews)
        self.assertEqual([(r["menu"], r["count"]) for r in top], [("계란말이", 2), ("된장찌개", 1), ("김치찌개", 1)])
        self.assertEqual(top_praised_menus(MENU, [rv(9, "친절해요", 5, "positive")]), [])


class PickPraisedMenuTest(unittest.TestCase):
    def test_most_praised_priced_menu(self):
        reviews = [rv(1, "계란말이 폭신해요", 5, "positive"), rv(2, "계란말이 또 시켜요", 5, "positive"),
                   rv(3, "제육볶음 맛있어요", 5, "positive")]
        picked = pick_praised_menu(MENU, reviews, priced=MENU)
        self.assertEqual((picked["menu"], picked["count"], picked["tied"], picked["praise_total"]), ("계란말이", 2, False, 3))
        # 가장 많이 칭찬받은 메뉴에 가격이 없으면 가격 있는 메뉴 중에서 고른다
        picked = pick_praised_menu(MENU, reviews, priced=["제육볶음 정식", "된장찌개"])
        self.assertEqual((picked["menu"], picked["count"]), ("제육볶음 정식", 1))

    def test_tie_and_no_mention_fall_back_to_menu_order(self):
        tie = [rv(1, "된장찌개 구수해요", 5, "positive"), rv(2, "제육볶음 맛있어요", 5, "positive")]
        picked = pick_praised_menu(MENU, tie, priced=MENU)
        self.assertEqual((picked["menu"], picked["count"], picked["tied"]), ("제육볶음 정식", 1, True))
        none = pick_praised_menu(MENU, [rv(1, "친절해요", 5, "positive")], priced=MENU)
        self.assertEqual((none["menu"], none["count"], none["tied"]), ("제육볶음 정식", 0, False))
        self.assertIsNone(pick_praised_menu(MENU, tie, priced=[]))


if __name__ == "__main__":
    unittest.main()
