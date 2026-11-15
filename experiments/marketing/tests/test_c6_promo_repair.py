"""홍보글 템플릿 쏠림 고침 (11/15) — 가짜 응답, 네트워크 없음.

11/15 실시간 HCX-005로 홍보글을 10번 만들어 보니 6번이 코드 템플릿이었다. HCX 가 준 글마다 걸린 점검을 보니
① no_unknown_menu 가 쿠폰 메뉴(제육볶음 정식)의 재료 '고기'를 다른 음식으로 봄 (가장 많음)
② 예시(PROMO_EXAMPLE)가 "손님들이 '양이 넉넉하다'고 해 주신"이라 따옴표 인용·'넉넉하다'를 그대로 따라 씀
③ 다시 쓰기 힌트가 합니다체 기준이 아니라 '편한 구어체로'라고 해서 해요체로 다시 씀(promo_formal)
④ '맛보시길 바랍니다'·'즐겨보세요'·'제공하고 있습니다'는 바꿀 말이 없어 다시 쓰기를 부름
⑤ 오탐: '성원'의 '원'(no_coupon_invented), '좋아해 주고'(no_broken_ending)
⑥ 4번째 문장은 어차피 잘라 내는데 자르기 전 글을 점검해 다시 쓰기를 부름

실행 (experiments/marketing 에서):
  python -m pytest -q tests/test_c6_promo_repair.py      또는      python -m tests.test_c6_promo_repair
홍보글 문장은 모두 이 시험을 위해 지어낸 합성 문장이다 (데모 가게 온기한식).
"""

import threading
import unittest
from unittest.mock import patch

from shared.sample_scenario import SAMPLE_CARDS, SAMPLE_REVIEWS, SAMPLE_SNAPSHOTS, SAMPLE_STORE, SAMPLE_TONE

from c6 import checks
from c6.contract import build_context
from c6.dummy import OWNER_REPLIES, POLICIES
from c6.promo import PROMO_EXAMPLE, generate_coupon_promo

CTX = build_context(store=SAMPLE_STORE, reviews=list(SAMPLE_REVIEWS), tone=SAMPLE_TONE, cards=list(SAMPLE_CARDS),
                    snapshots=list(SAMPLE_SNAPSHOTS), owner_replies=OWNER_REPLIES, policies=POLICIES)
CARD = next(c for c in SAMPLE_CARDS if c.kind == "promo")
MENU = list(SAMPLE_STORE.menu)
COUPON = next(m for m in MENU if m in SAMPLE_STORE.menu_prices)          # 제육볶음 정식
REVIEW_TEXTS = [r.text for r in SAMPLE_REVIEWS]

GOOD = ("오늘 저녁은 매콤한 제육볶음 정식으로 든든하게 드셔 보세요. 양념이 잘 밴 고기를 밥과 함께 넉넉히 담아 "
        "보내드립니다. 편하게 주문해 주시기 바랍니다.")


def run_promo(answer):
    """HCX 가 늘 같은 글(answer)을 준다고 치고 홍보글을 만든다. (초안, 받은 메시지 목록)"""
    seen, lock = [], threading.Lock()

    def fake(key, system, messages, **kw):
        with lock:
            seen.append(messages)
        return {"content": answer, "won": 0.01}

    with patch("clova.call", side_effect=fake):
        d = generate_coupon_promo(CTX, CARD, "k").drafts[0]
    return d, seen


def body(d):
    """쿠폰 줄(코드가 붙임)을 뺀 본문."""
    return d.text.split("\n🎟")[0]


def promo_failures(text):
    """홍보글 점검 중 예시·본문이 넘어야 할 것 (promo.py _run_promo_checks 와 같은 함수)."""
    allow = checks.menu_ingredient_words(COUPON)
    bad = {
        "quote": checks.quotes_customer_speech(text), "fewshot": checks.fewshot_copied(text, MENU, REVIEW_TEXTS),
        "unknown_menu": checks.mentions_unknown_menu(text, MENU, allow=allow), "stiff": checks.has_stiff_words(text),
        "exaggeration": checks.has_exaggeration(text), "coupon": checks.coupon_invented(text),
        "informal": not checks.promo_formal(text), "broken": not checks.no_broken_ending(text),
        "markdown": checks.has_markdown(text), "circumstance": checks.store_circumstance_leaked(text),
    }
    return [k for k, v in bad.items() if v]


class TestExampleTeachesOnlyWhatPasses(unittest.TestCase):
    def test_promo_example_passes_every_promo_check(self):
        self.assertEqual(promo_failures(PROMO_EXAMPLE), [])
        self.assertNotIn("'", PROMO_EXAMPLE)
        self.assertNotIn("넉넉하다", PROMO_EXAMPLE)


class TestCustomerQuote(unittest.TestCase):
    def test_indirect_quotes_are_caught(self):
        for text in ("손님분들께서 혼밥하기도 좋고 음식 맛이 좋다고 말씀해주신 만큼 정성껏 준비했습니다.",
                     "제육볶음이 맛있다며 밥 한 공기 더 시키게 된다는 손님들을 위해 준비했습니다.",
                     "맛있다는 손님들이 많아 오늘도 준비했습니다.",
                     "많은 분들이 양이 많다고 극찬하신 메뉴입니다.",
                     "손님들이 '양이 넉넉하다'고 해 주셨습니다."):
            with self.subTest(text=text):
                self.assertTrue(checks.quotes_customer_speech(text))

    def test_own_words_are_not_quotes(self):
        for text in ("손님께 드리는 든든한 한 끼라고 생각합니다.", "많은 손님께서 인정해주신 만큼 자신 있는 맛입니다.",
                     "든든하다는 평을 받은 메뉴를 준비했습니다.", "손님들께서 항상 만족하시는 인기 메뉴입니다.", GOOD):
            with self.subTest(text=text):
                self.assertFalse(checks.quotes_customer_speech(text))


class TestFalsePositives(unittest.TestCase):
    def test_meat_is_an_ingredient_of_a_meat_menu(self):
        text = "매콤달콤한 양념과 고기의 조화가 일품인 제육볶음 정식입니다. 돼지고기를 듬뿍 넣었습니다."
        self.assertTrue(checks.mentions_unknown_menu(text, MENU))                               # 기본은 그대로
        self.assertFalse(checks.mentions_unknown_menu(text, MENU, allow=checks.menu_ingredient_words(COUPON)))
        self.assertEqual(checks.menu_ingredient_words("된장찌개"), ())
        self.assertTrue(checks.mentions_unknown_menu("고기와 치킨도 함께 보내드립니다.", MENU,
                                                     allow=checks.menu_ingredient_words(COUPON)))   # 치킨은 여전히 걸림
        self.assertEqual(checks.unknown_menu_words("고기와 치킨", MENU), ["고기", "치킨"])

    def test_won_only_as_money(self):
        for text in ("고객님들의 성원에 힘입어 준비했습니다.", "원하시는 만큼 담아 드립니다.", "원래 인기 메뉴입니다."):
            with self.subTest(text=text):
                self.assertFalse(checks.coupon_invented(text))
        for text in ("1,000원 내려 드립니다.", "천 원 더 저렴합니다.", "할인 쿠폰을 드립니다."):
            with self.subTest(text=text):
                self.assertTrue(checks.coupon_invented(text))

    def test_joahae_ju_is_correct_korean(self):
        self.assertTrue(checks.no_broken_ending("많은 분들이 좋아해 주고 계십니다."))
        self.assertTrue(checks.no_broken_ending("싫어해 주셔도 괜찮습니다."))
        self.assertFalse(checks.no_broken_ending("요청사항에 적어해주세요."))


class TestCodeFixes(unittest.TestCase):
    def test_formal_promo_phrases(self):
        cases = {"이번 기회에 꼭 한번 맛보시길 바랍니다!": "이번 기회에 꼭 한번 드셔 보시기 바랍니다!",
                 "든든한 한 끼를 즐겨보세요!": "든든한 한 끼를 드셔 보세요!",
                 "다양한 반찬을 함께 제공하고 있습니다.": "다양한 반찬을 함께 준비하고 있습니다.",
                 "언제든 방문을 기다리겠습니다.": "언제든 주문을 기다리겠습니다."}
        for before, after in cases.items():
            with self.subTest(before=before):
                fixed = checks.fix_stiff_words(before, formal=True)
                self.assertEqual(fixed, after)
                self.assertFalse(checks.has_stiff_words(fixed))

    def test_sentence_endings(self):
        self.assertEqual(checks.to_formal_sentence_endings("밥이랑 먹으면 꿀맛이에요. 오늘 저녁은 이걸로 해결할게요!"),
                         "밥이랑 먹으면 꿀맛입니다. 오늘 저녁은 이걸로 해결하겠습니다!")

    def test_detail_hints_name_the_words(self):
        text = "손님들께서 '양도 많고 맛있다'고 해주신 제육볶음 정식에 된장찌개도 곁들여 즐겨보세요. 최고의 맛입니다."
        failed = ["no_customer_quote", "only_coupon_menu", "no_stiff_words", "no_exaggeration"]
        hints = "\n".join(checks.promo_detail_hints(failed, text, menu_names=MENU, coupon_menu=COUPON,
                                                    review_texts=REVIEW_TEXTS, reviews=SAMPLE_REVIEWS))
        for word in ("'양도 많고 맛있다'", "'된장찌개'", "'즐겨보세요' → 드셔 보세요", "'최고'"):
            self.assertIn(word, hints)


class TestPromoFlow(unittest.TestCase):
    def test_meat_promo_passes_without_rewrite(self):
        d, seen = run_promo(GOOD)
        self.assertEqual(len(seen), 2)                                          # 후보 2개만, 다시 쓰기 없음
        self.assertEqual((d.rewrites, d.checks["used_fallback"], d.checks["ai_part_repaired"]), (0, False, False))
        self.assertEqual(body(d), GOOD)

    def test_fourth_sentence_is_cut_before_checking(self):
        long_ = GOOD + " 이번 기회를 놓치지 마시고 최고의 맛을 즐겨보세요!"            # 4번째 문장에 과장·딱딱한 말
        d, seen = run_promo(long_)
        self.assertEqual(len(seen), 2)
        self.assertEqual((d.checks["used_fallback"], d.checks["ai_part_repaired"]), (False, True))   # 코드가 잘랐다
        self.assertEqual(body(d), GOOD)

    def test_stiff_phrase_is_replaced_without_rewrite(self):
        d, seen = run_promo("오늘 저녁은 매콤한 제육볶음 정식으로 든든한 한 끼를 즐겨보세요. 양념이 잘 밴 고기를 밥과 함께 담아 보내드립니다.")
        self.assertEqual(len(seen), 2)
        self.assertEqual((d.checks["used_fallback"], d.checks["ai_part_repaired"]), (False, True))
        self.assertIn("든든한 한 끼를 드셔 보세요.", body(d))

    def test_quote_is_rewritten_with_formal_and_named_hints(self):
        quote = "손님들께서 '양도 많고 맛있다'고 해주신 제육볶음 정식을 여러분께 추천합니다. 지금 바로 주문해 보세요."
        d, seen = run_promo(quote)
        self.assertEqual(len(seen), 4)                                          # 후보 2 + 다시 쓰기 2
        retry = seen[2][-1]["content"]
        self.assertIn("'양도 많고 맛있다'", retry)
        self.assertIn("'여러분'", retry)
        self.assertNotIn("구어체", retry)                                       # 합니다체 기준 힌트 (formal=True)
        self.assertEqual(seen[2][1]["content"], quote)                          # 손질한 글을 고치게 한다
        self.assertTrue(d.checks["used_fallback"])                              # 끝까지 못 고치면 예전처럼 템플릿
        self.assertFalse(d.checks["ai_part_repaired"])
        self.assertEqual(d.failed_reasons, [])


if __name__ == "__main__":
    unittest.main()
