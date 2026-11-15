"""쿠폰 메뉴 고르기 (11/16) — 가짜 응답, 네트워크 없음.

전에는 홍보글의 쿠폰 메뉴가 늘 메뉴판 첫 메뉴(store.menu[0], 가격 있는 것)였다. 이제는 가격 있는 메뉴 가운데 손님 칭찬
리뷰에 가장 많이 언급된 메뉴를 고르고, 같은 수거나 언급이 없으면 메뉴판 순서를 따른다 (shared.praise.pick_praised_menu —
카드 ⓑ 의 근거 [F3] 도 같은 함수로 정한다).

실행 (experiments/marketing 에서):
  python -m pytest -q tests/test_c6_promo_menu.py      또는      python -m tests.test_c6_promo_menu
리뷰·홍보글 문장은 모두 이 시험을 위해 지어낸 합성 문장이다 (데모 가게 온기한식).
"""

import threading
import unittest
from dataclasses import replace
from unittest.mock import patch

from shared.contracts import ReviewRecord
from shared.sample_scenario import SAMPLE_CARDS, SAMPLE_REVIEWS, SAMPLE_SNAPSHOTS, SAMPLE_STORE, SAMPLE_TONE

from c6.contract import build_context
from c6.dummy import OWNER_REPLIES, POLICIES
from c6.promo import generate_coupon_promo

CARD = next(c for c in SAMPLE_CARDS if c.kind == "promo")
FIRST = next(m for m in SAMPLE_STORE.menu if m in SAMPLE_STORE.menu_prices)          # 제육볶음 정식 (메뉴판 첫 메뉴)

EGG_GOOD = "오늘 저녁은 폭신한 계란말이로 든든하게 드셔 보세요. 정성껏 부쳐서 따뜻하게 보내드립니다. 편하게 주문해 주시기 바랍니다."
PORK_GOOD = ("오늘 저녁은 매콤한 제육볶음 정식으로 든든하게 드셔 보세요. 양념이 잘 밴 고기를 밥과 함께 넉넉히 담아 "
             "보내드립니다. 편하게 주문해 주시기 바랍니다.")


def rv(i, text, rating=5, sentiment="positive", negative=()):
    return ReviewRecord(review_id=f"rv_t_{i:03d}", store_id=SAMPLE_STORE.store_id, text=text,
                        created_at="2026-11-01T12:00:00+09:00", rating=rating, sentiment=sentiment,
                        topics=list(negative), negative_topics=list(negative))


def run_promo(reviews, answer=EGG_GOOD, store=SAMPLE_STORE, **kw):
    """HCX 가 늘 같은 글(answer)을 준다고 치고 홍보글을 만든다. (초안, 받은 system 프롬프트 목록)"""
    ctx = build_context(store=store, reviews=list(reviews), tone=SAMPLE_TONE, cards=list(SAMPLE_CARDS),
                        snapshots=list(SAMPLE_SNAPSHOTS), owner_replies=OWNER_REPLIES, policies=POLICIES)
    seen, lock = [], threading.Lock()

    def fake(key, system, messages, **_):
        with lock:
            seen.append(system)
        return {"content": answer, "won": 0.01}

    with patch("clova.call", side_effect=fake):
        d = generate_coupon_promo(ctx, CARD, "k", **kw).drafts[0]
    return d, seen


def coupon_of(d):
    """코드가 붙인 쿠폰 줄과 근거에서 읽은 쿠폰 메뉴 (둘이 같아야 한다)."""
    from_evidence = [e[len("coupon:"):] for e in d.evidence_ids if e.startswith("coupon:")]
    line = d.text.split("\n🎟 ")[1]
    assert len(from_evidence) == 1 and line.startswith(from_evidence[0] + " 1,000원 할인 쿠폰"), (from_evidence, line)
    return from_evidence[0]


def prompt_part(system, head):
    """system 프롬프트의 한 칸 ('## 쿠폰 메뉴' 또는 '## 손님 반응')."""
    start = system.index(head)
    return system[start:system.index("\n## ", start + 1)]


class TestPickedMenu(unittest.TestCase):
    def test_most_praised_menu_is_the_coupon_menu(self):
        reviews = [rv(1, "계란말이가 폭신하고 맛있어요"), rv(2, "계란말이 또 시킬게요"), rv(3, "제육볶음이 불맛 나요")]
        d, seen = run_promo(reviews)
        self.assertEqual(coupon_of(d), "계란말이")                                # 전에는 늘 메뉴판 첫 메뉴(제육볶음 정식)
        self.assertIn("- 계란말이", prompt_part(seen[0], "## 쿠폰 메뉴"))
        self.assertEqual((d.rewrites, d.checks["used_fallback"]), (0, False))      # 고른 메뉴 기준으로 점검이 돈다

    def test_checks_follow_the_picked_menu(self):
        """고른 메뉴가 계란말이면 제육볶음 정식을 소개한 글은 '쿠폰 메뉴만 소개' 점검에 걸리고, 템플릿도 계란말이로 쓴다."""
        reviews = [rv(1, "계란말이가 폭신하고 맛있어요"), rv(2, "계란말이 또 시킬게요"), rv(3, "제육볶음이 불맛 나요")]
        d, _ = run_promo(reviews, answer=PORK_GOOD)
        self.assertTrue(d.checks["used_fallback"])
        self.assertIn("계란말이를 추천드립니다", d.text)
        self.assertNotIn("제육볶음", d.text)
        self.assertEqual(d.failed_reasons, [])
        self.assertEqual(coupon_of(d), "계란말이")

    def test_same_count_keeps_menu_order(self):
        reviews = [rv(1, "계란말이가 폭신해요"), rv(2, "된장찌개가 구수해요"), rv(3, "제육볶음이 불맛 나요")]
        d, _ = run_promo(reviews, answer=PORK_GOOD)
        self.assertEqual(coupon_of(d), FIRST)

    def test_no_mention_keeps_the_first_priced_menu(self):
        for reviews in (list(SAMPLE_REVIEWS), [rv(1, "사장님이 친절하세요"), rv(2, "배달이 빨라요")], []):
            with self.subTest(n=len(reviews)):
                d, _ = run_promo(reviews, answer=PORK_GOOD)
                self.assertEqual(coupon_of(d), FIRST)

    def test_menu_without_price_is_never_the_coupon_menu(self):
        prices = {m: p for m, p in SAMPLE_STORE.menu_prices.items() if m != "계란말이"}
        store = replace(SAMPLE_STORE, menu_prices=prices)
        reviews = [rv(1, "계란말이가 폭신해요"), rv(2, "계란말이 또 시킬게요"), rv(3, "계란말이 맛있어요"), rv(4, "된장찌개가 구수해요")]
        answer = "오늘 저녁은 구수한 된장찌개로 든든하게 드셔 보세요. 정성껏 끓여서 따뜻하게 보내드립니다. 편하게 주문해 주시기 바랍니다."
        d, _ = run_promo(reviews, answer=answer, store=store)
        self.assertEqual(coupon_of(d), "된장찌개")                                # 가격 있는 메뉴 중 가장 많이 칭찬받은 것
        d, _ = run_promo(reviews[:3], answer=PORK_GOOD, store=store)               # 가격 있는 메뉴는 언급이 없다 → 메뉴판 순서
        self.assertEqual(coupon_of(d), FIRST)

    def test_only_praise_counts(self):
        """불만 리뷰가 많이 말한 메뉴를 쿠폰 메뉴로 고르지 않는다."""
        reviews = [rv(1, "김치찌개가 너무 짜요", 1, "negative", ["taste"]), rv(2, "김치찌개 식어서 왔어요", 2, "negative", ["temperature"]),
                   rv(3, "김치찌개 양이 적어요", 2, "mixed", ["portion"]), rv(4, "계란말이가 폭신해요")]
        d, _ = run_promo(reviews)
        self.assertEqual(coupon_of(d), "계란말이")

    def test_before_classification_high_rating_without_complaint_counts(self):
        """감정 분류가 없으면: 별점 4점 이상이면서 불만 주제가 없는 리뷰만 칭찬으로 센다."""
        reviews = [rv(1, "된장찌개 맛은 좋은데 식었어요", 4, None, ["temperature"]), rv(2, "된장찌개 좋은데 늦게 왔어요", 5, None, ["delivery_time"]),
                   rv(3, "계란말이가 폭신해요", 5, None), rv(4, "김치찌개 그냥 그래요", 3, None)]
        d, _ = run_promo(reviews)
        self.assertEqual(coupon_of(d), "계란말이")

    def test_menu_given_by_the_caller_is_kept(self):
        reviews = [rv(1, "계란말이가 폭신해요"), rv(2, "계란말이 또 시킬게요")]
        d, _ = run_promo(reviews, answer=PORK_GOOD, coupon_menu=FIRST)
        self.assertEqual(coupon_of(d), FIRST)

    def test_no_priced_menu_still_asks_the_owner(self):
        d, _ = run_promo([rv(1, "계란말이가 폭신해요")], store=replace(SAMPLE_STORE, menu_prices={}))
        self.assertTrue(any("menu_prices 없음" in n for n in d.needs_input))
        self.assertNotIn("🎟", d.text)


class TestCustomerReactionPart(unittest.TestCase):
    """프롬프트의 '손님 반응' 칸: 쿠폰 메뉴를 칭찬한 리뷰가 먼저, 다른 메뉴만 말한 칭찬 리뷰는 넣지 않는다."""

    def test_reviews_about_the_coupon_menu_come_first(self):
        reviews = [rv(1, "혼밥하기 편하고 음식도 맛있어요"), rv(2, "순두부찌개 얼큰하고 맛있어요"), rv(3, "계란말이가 폭신해요"),
                   rv(4, "계란말이 또 시킬게요"), rv(5, "계란말이 아이가 잘 먹어요")]
        _, seen = run_promo(reviews)
        part = prompt_part(seen[0], "## 손님 반응")
        self.assertEqual(part.count("\n- "), 2)
        self.assertIn("계란말이가 폭신해요", part)
        self.assertIn("계란말이 또 시킬게요", part)
        self.assertNotIn("순두부찌개", part)

    def test_other_menu_praise_is_left_out_when_filling(self):
        reviews = [rv(1, "순두부찌개 얼큰하고 맛있어요"), rv(2, "혼밥하기 편하고 음식도 맛있어요"), rv(3, "제육볶음이 불맛 나요")]
        d, seen = run_promo(reviews, answer=PORK_GOOD)
        self.assertEqual(coupon_of(d), FIRST)                                     # 모두 1건 → 메뉴판 순서
        lines = [line for line in prompt_part(seen[0], "## 손님 반응").splitlines() if line.startswith("- ")]
        self.assertEqual(lines, ['- "제육볶음이 불맛 나요" (★5)', '- "혼밥하기 편하고 음식도 맛있어요" (★5)'])

    def test_without_praise_for_the_menu_the_old_order_is_kept(self):
        reviews = [rv(1, "사장님이 친절하세요"), rv(2, "배달이 빨라요"), rv(3, "포장이 꼼꼼해요")]
        _, seen = run_promo(reviews, answer=PORK_GOOD)
        lines = [line for line in prompt_part(seen[0], "## 손님 반응").splitlines() if line.startswith("- ")]
        self.assertEqual(lines, ['- "사장님이 친절하세요" (★5)', '- "배달이 빨라요" (★5)'])


if __name__ == "__main__":
    unittest.main()
