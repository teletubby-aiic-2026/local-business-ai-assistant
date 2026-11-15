"""카드 ⓑ(쿠폰 홍보)의 손님 칭찬 근거 [F3] (11/16). CLOVA·네트워크를 부르지 않는다 (리뷰 서비스·모델은 가짜).

지키는 것
- 가게·리뷰를 주지 않으면 카드는 예전 그대로다 (build_cards 서명도 그대로).
- 칭찬 리뷰에 쿠폰 메뉴 언급이 1건 이상이면 제목·이유·사실 카드(F3)·근거(evidence)·card.review_ids 에 붙는다.
- 사실대로: 혼자 가장 많이 언급된 메뉴일 때만 '가장 많이'라고 쓴다 (같은 수, 가격 없는 메뉴가 더 많은 경우는 쓰지 않는다).
- 고정 문장은 check_answer 와 reason_problems 를 통과한다. 이유 문장은 두 카드(F2·F3)를 모두 인용하고 숫자를 써야 하고,
  한 카드를 인용한 문장에 다른 카드의 표기(메뉴 이름, 상권·시간대)를 섞으면 안 된다.
- live: 모델에게는 상권 지표 카드(F2)만 주고, 칭찬 근거 한 줄(메뉴·건수)은 코드가 끼워 넣는다 (모델이 두 근거를 섞어 쓰지 못한다).
- 카드가 말한 메뉴 == 홍보글의 쿠폰 메뉴 (live 는 C6 가 같은 함수로 고르고, mock 은 저장 예시의 메뉴일 때만 칭찬 근거를 붙인다).
- 붙여넣은 칭찬 리뷰는 그 방문자의 카드에만 보인다.

실행 (services/web 에서): PYTHONPATH=<저장소 루트>:. python -m pytest -q tests/test_praise_card.py
리뷰 문장은 모두 이 시험을 위해 지어낸 합성 문장이다.
"""
from __future__ import annotations

import copy
import json
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from shared.answer_check import check_answer
from shared.contracts import AnalysisSnapshot, ReviewRecord, load_json
from web.cards import build_cards, plan_cards, reason_problems
from web.demo import Demo
from web.main import create_app
from web.sources import to_review_records, to_store_profile

from tests.test_web import FIX, HAS_C6, FakeSource, fixture, settings, snapshots

EVENING = FIX / "snapshot_pr17_evening.json"
OLD_TITLE = "관측 업종 합산 추정매출 (하루 전체 시간대) 하락 → 쿠폰 홍보"
EGG_GOOD = "오늘 저녁은 폭신한 계란말이로 든든하게 드셔 보세요. 정성껏 부쳐서 따뜻하게 보내드립니다. 편하게 주문해 주시기 바랍니다."


def insight():
    return fixture("insight_ongi.json")


def store():
    return to_store_profile(fixture("store_ongi.json"), "장승배기역 4번")


def reviews():
    """시험 고정 리뷰 40건 (칭찬 26건, 메뉴마다 칭찬 언급 1건씩)."""
    return to_review_records(fixture("reviews_ongi.json"), insight())


def rv(i, text, rating=5, sentiment="positive", negative=()):
    return ReviewRecord(review_id=f"rv_t_{i:03d}", store_id="store_ongi", text=text, created_at="2026-11-09T12:00:00+09:00",
                        rating=rating, sentiment=sentiment, topics=list(negative), negative_topics=list(negative))


def card_b(extra=(), snaps=None, shop=None, base=None):
    """가게·리뷰를 함께 준 카드 ⓑ."""
    listed = list(extra) + (reviews() if base is None else list(base))
    plans = plan_cards(insight(), snaps or snapshots(), "store_ongi", store=shop or store(), reviews=listed)
    return next(p for p in plans if p.card.kind == "promo")


def praise_of(plan_dict):
    return [e for e in plan_dict["evidence"] if e["type"] == "praise"]


# ── 카드 규칙 ───────────────────────────────────────────────────────
class OldCardStays(unittest.TestCase):
    def test_build_cards_signature_and_result_are_unchanged(self):
        """C5 인터페이스 build_cards(insight, snapshots, store_id) 는 그대로이고, 가게·리뷰 없이 만든 카드는 예전과 같다."""
        cards = build_cards(insight(), snapshots(), "store_ongi")
        self.assertEqual([c.kind for c in cards], ["complaint", "promo"])
        plan = plan_cards(insight(), snapshots(), "store_ongi")[1]
        self.assertEqual(plan.title, OLD_TITLE)
        self.assertEqual([f["id"] for f in plan.facts], ["F2"])
        self.assertEqual([e["type"] for e in plan.evidence], ["snapshot"])
        self.assertEqual((plan.card.review_ids, cards[1].review_ids), ([], []))
        self.assertEqual(plan.card.reason_text, "장승배기역 4번 상권의 관측 업종 합산 추정매출 (하루 전체 시간대): 2026년 2분기, "
                                                "전년 동기 대비 27.95% 감소\n손님을 다시 부르는 쿠폰 홍보를 제안해요.")

    def test_no_store_or_reviews_means_the_old_card(self):
        old = plan_cards(insight(), snapshots(), "store_ongi")[1].to_dict()
        for kw in ({"store": None, "reviews": None}, {"store": store(), "reviews": None}, {"store": None, "reviews": reviews()}):
            with self.subTest(given=sorted(k for k, v in kw.items() if v is not None)):
                self.assertEqual(plan_cards(insight(), snapshots(), "store_ongi", **kw)[1].to_dict(), old)

    def test_no_praise_for_any_menu_means_the_old_card(self):
        old = plan_cards(insight(), snapshots(), "store_ongi")[1].to_dict()
        complaints = [r for r in reviews() if r.sentiment != "positive"]
        for base in (complaints, [rv(1, "사장님이 친절하세요"), rv(2, "배달이 빨라요")], []):
            with self.subTest(n=len(base)):
                self.assertEqual(card_b(base=base).to_dict(), old)

    def test_complaint_card_is_the_same_with_or_without_reviews(self):
        old = plan_cards(insight(), snapshots(), "store_ongi")[0].to_dict()
        new = plan_cards(insight(), snapshots(), "store_ongi", store=store(), reviews=reviews())[0].to_dict()
        self.assertEqual(new, old)


class PraiseFact(unittest.TestCase):
    def test_same_count_is_not_called_the_most(self):
        """시험 고정 리뷰는 메뉴마다 칭찬 언급이 1건씩이다 → 메뉴판 순서로 제육볶음 정식, '가장 많이'라고 쓰지 않는다."""
        plan = card_b()
        self.assertEqual(plan.title, "관측 업종 합산 추정매출 (하루 전체 시간대) 하락 → '제육볶음 정식' 쿠폰 홍보")
        self.assertEqual(plan.card.reason_text.split("\n")[1:],
                         ["손님 칭찬 리뷰에 제육볶음 정식 언급이 1건 있어요", "손님을 다시 부르는 제육볶음 정식 쿠폰 홍보를 제안해요."])
        self.assertNotIn("가장", plan.checked_text)
        self.assertIn("27.95% 감소 [F2]", plan.checked_text)
        self.assertIn("언급이 1건 있어요 [F3]", plan.checked_text)
        f2, f3 = plan.facts
        self.assertEqual((f2["id"], f3["id"], f3["topic"], f3["status"]), ("F2", "F3", "review_praise", "available"))
        self.assertEqual(f3["values"], [{"label": "쿠폰 메뉴를 언급한 칭찬 리뷰", "value": 1, "unit": "건"},
                                        {"label": "쿠폰 메뉴", "value": "제육볶음 정식"}])
        self.assertEqual(f3["keep"], ["제육볶음 정식"])
        self.assertIn("가장", f3["avoid"])
        self.assertNotIn("가장", f3["text"])
        self.assertEqual(plan.evidence[0]["type"], "snapshot")                      # 상권 지표 근거는 그대로 맨 앞
        self.assertEqual(plan.evidence[1:], [{"type": "praise", "id": "rv_ongi_013", "text": "제육볶음이 불맛 나고 정말 맛있어요!",
                                              "menu": "제육볶음 정식", "rating": 5}])
        self.assertEqual(plan.card.review_ids, ["rv_ongi_013"])
        self.assertEqual(plan.card.snapshot_ids, ["snap_3110826_sales_all_day_observed_yoy_2026Q2"])

    def test_single_top_menu_is_called_the_most_with_its_count(self):
        plan = card_b([rv(1, "계란말이 또 시킬게요"), rv(2, "계란말이 아이가 잘 먹어요")])
        self.assertIn("'계란말이' 쿠폰 홍보", plan.title)
        self.assertIn("손님 칭찬 리뷰에서 계란말이 언급이 3건으로 가장 많아요 [F3]", plan.checked_text)
        self.assertTrue(plan.card.reason_text.endswith("손님을 다시 부르는 계란말이 쿠폰 홍보를 제안해요."))
        f3 = plan.facts[1]
        self.assertEqual(f3["text"], "손님 칭찬 리뷰에서 가장 많이 언급된 메뉴는 계란말이, 3건")
        self.assertNotIn("avoid", f3)
        self.assertEqual(plan.card.review_ids, ["rv_t_001", "rv_t_002", "rv_ongi_015"])
        self.assertEqual([e["id"] for e in plan.evidence if e["type"] == "praise"], ["rv_t_001", "rv_t_002", "rv_ongi_015"])

    def test_evidence_shows_three_reviews_but_counts_all(self):
        extra = [rv(i, f"계란말이 맛있어요 {i}번째") for i in range(1, 5)]
        plan = card_b(extra)
        self.assertIn("계란말이 언급이 5건으로 가장 많아요 [F3]", plan.checked_text)
        self.assertEqual(len(plan.card.review_ids), 5)
        self.assertEqual([e["id"] for e in plan.evidence if e["type"] == "praise"], ["rv_t_001", "rv_t_002", "rv_t_003"])

    def test_more_praised_menu_without_price_is_not_hidden_behind_most(self):
        """가격 없는 메뉴(계란말이)가 더 많이 칭찬받았으면, 쿠폰 메뉴(가격 있는 것 중 1등)를 '가장 많이'라고 하지 않는다."""
        shop = store()
        shop = replace(shop, menu_prices={m: p for m, p in shop.menu_prices.items() if m != "계란말이"})
        plan = card_b([rv(1, "계란말이 또 시킬게요"), rv(2, "계란말이 최고"), rv(3, "된장찌개 구수해요")], shop=shop)
        self.assertIn("'된장찌개' 쿠폰 홍보", plan.title)
        self.assertIn("손님 칭찬 리뷰에 된장찌개 언급이 2건 있어요 [F3]", plan.checked_text)
        self.assertNotIn("가장", plan.checked_text)
        self.assertIn("가장", plan.facts[1]["avoid"])

    def test_complaints_about_a_menu_are_not_praise(self):
        bad = [rv(i, "김치찌개가 너무 짜요", 1, "negative", ["taste"]) for i in range(1, 4)]
        plan = card_b(bad)
        self.assertIn("제육볶음 정식 언급이 1건 있어요", plan.checked_text)          # 김치찌개 칭찬 언급은 여전히 1건

    def test_long_pasted_review_is_cut_in_the_evidence(self):
        long_text = "계란말이 " + "정말 맛있어요 " * 100
        plan = card_b([rv(1, long_text), rv(2, "계란말이 또 시킬게요")])
        shown = next(e for e in plan.evidence if e["id"] == "rv_t_001")
        self.assertLessEqual(len(shown["text"]), 121)
        self.assertTrue(shown["text"].endswith("…"))

    def test_reviews_may_be_plain_dicts(self):
        from web.cards import praised_coupon_menu
        rows = [{"review_id": "rv_d_1", "text": "계란말이 폭신해요", "rating": 5, "sentiment": "positive"},
                {"review_id": "rv_d_2", "text": "계란말이 또 시켜요", "rating": 4, "sentiment": "positive"}]
        found = praised_coupon_menu(store(), rows)
        self.assertEqual((found["menu"], found["count"], found["alone"]), ("계란말이", 2, True))
        self.assertEqual([e["rating"] for e in found["evidence"]], [5, 4])
        self.assertIsNone(praised_coupon_menu(store(), []))
        self.assertIsNone(praised_coupon_menu(None, rows))


class FixedSentence(unittest.TestCase):
    def test_fixed_sentences_pass_the_checker_and_the_reason_rules(self):
        cases = {
            "같은 수": card_b(),
            "혼자 1등": card_b([rv(1, "계란말이 또 시킬게요"), rv(2, "계란말이 최고예요")]),
            "저녁 지표 + 같은 수": card_b(snaps=load_json(AnalysisSnapshot, EVENING)),
            "저녁 지표 + 혼자 1등": card_b([rv(1, "불고기 덮밥 달달해요"), rv(2, "불고기 덮밥 또 시켜요")],
                                     snaps=load_json(AnalysisSnapshot, EVENING)),
        }
        for name, plan in cases.items():
            with self.subTest(name):
                self.assertEqual([f["id"] for f in plan.facts], ["F2", "F3"])
                self.assertEqual(plan.reason_source, "고정 문장", plan.problems)
                self.assertTrue(check_answer(plan.checked_text, plan.facts)["ok"])
                self.assertEqual(reason_problems(plan.checked_text, plan.facts), [])
                self.assertNotIn("[F", plan.card.reason_text)

    def test_evening_card_keeps_the_evening_wording(self):
        plan = card_b(snaps=load_json(AnalysisSnapshot, EVENING))
        self.assertEqual(plan.title, "저녁 시간대(17~24시) 추정매출(두 분기 공통 업종) 하락 → '제육볶음 정식' 쿠폰 홍보")
        self.assertEqual(plan.card.reason_text.split("\n")[2], "저녁 손님을 다시 부르는 제육볶음 정식 쿠폰 홍보를 제안해요.")

    def test_menu_name_with_a_number_is_not_read_as_a_statistic(self):
        shop = replace(store(), menu=["1인 정식", "된장찌개"], menu_prices={"1인 정식": 9000, "된장찌개": 8000})
        plan = card_b(base=[rv(1, "1인 정식 든든해요"), rv(2, "1인 정식 또 시켜요")], shop=shop)
        self.assertIn("'1인 정식' 쿠폰 홍보", plan.title)
        self.assertEqual(reason_problems(plan.checked_text, plan.facts), [])

    def test_menu_name_that_breaks_the_rules_falls_back_to_the_old_card(self):
        """메뉴 이름에 검사기가 막는 말('대박')이 있으면 칭찬 근거를 붙이지 않는다 (검사 규칙은 그대로 둔다)."""
        shop = replace(store(), menu=["대박 정식", "된장찌개"], menu_prices={"대박 정식": 9000, "된장찌개": 8000})
        plan = card_b(base=[rv(1, "대박 정식 든든해요")], shop=shop)
        self.assertEqual(plan.to_dict(), plan_cards(insight(), snapshots(), "store_ongi")[1].to_dict())


class ModelSentence(unittest.TestCase):
    """live 이유 문장: 상권 지표(F2)와 손님 칭찬(F3)을 둘 다 인용하고 숫자를 써야 통과한다."""

    def setUp(self):
        self.tied = card_b(snaps=load_json(AnalysisSnapshot, EVENING)).facts
        self.alone = card_b([rv(1, "제육볶음 맛있어요"), rv(2, "제육볶음 정식 든든해요")], snaps=load_json(AnalysisSnapshot, EVENING)).facts
        self.market = ("장승배기역 4번 상권의 저녁 시간대(17~24시) 추정 매출은 2026년 2분기에 전년 동기 대비 19.31% 감소했어요[F2]. ")

    def types(self, text, facts):
        return [p["type"] for p in reason_problems(text, facts)]

    def test_good_sentence_passes(self):
        good = self.market + "손님 칭찬 리뷰에는 제육볶음 정식이 1건 언급됐어요[F3]. 저녁 손님을 다시 부르는 쿠폰 홍보를 제안해요."
        self.assertEqual(reason_problems(good, self.tied), [])

    def test_leaving_out_the_praise_card_is_rejected(self):
        only_market = self.market + "저녁 손님을 다시 부르는 제육볶음 정식 쿠폰 홍보를 제안해요."
        found = reason_problems(only_market, self.tied)
        self.assertIn({"type": "promised_card_left_out", "detail": "F3"}, found)
        self.assertIn({"type": "no_fact_value", "detail": "1건"}, found)
        no_number = self.market + "손님 칭찬 리뷰에 제육볶음 정식이 언급됐어요[F3]. 쿠폰 홍보를 제안해요."
        self.assertEqual(self.types(no_number, self.tied), ["no_fact_value"])

    def test_leaving_out_the_market_card_is_rejected(self):
        only_praise = "장승배기역 4번 상권 17~24시 손님 칭찬 리뷰에 제육볶음 정식이 1건 언급됐어요[F3]. 쿠폰 홍보를 제안해요."
        found = self.types(only_praise, self.tied)
        self.assertIn("promised_card_left_out", found)
        self.assertIn("no_fact_value", found)

    def test_menu_name_must_be_kept(self):
        other = self.market + "손님 칭찬 리뷰에는 제육이 1건 언급됐어요[F3]. 쿠폰 홍보를 제안해요."
        self.assertEqual(self.types(other, self.tied), ["label_changed"])

    def test_wrong_count_is_rejected_by_the_checker(self):
        wrong = self.market + "손님 칭찬 리뷰에는 제육볶음 정식이 5건 언급됐어요[F3]. 쿠폰 홍보를 제안해요."
        self.assertIn("number_not_on_card", self.types(wrong, self.tied))

    def test_most_is_allowed_only_for_a_single_top_menu(self):
        most = self.market + "손님 칭찬 리뷰에서 가장 많이 언급된 메뉴는 제육볶음 정식이고 {n}건이에요[F3]. 쿠폰 홍보를 제안해요."
        self.assertEqual(reason_problems(most.format(n=1), self.tied), [{"type": "forbidden_phrase", "detail": "가장"}])
        self.assertEqual(reason_problems(most.format(n=3), self.alone), [])

    def test_cards_must_not_be_mixed_in_one_sentence(self):
        """11/16 실시간에서 검사기를 통과한 문장들: 상권 통계가 메뉴 매출이 되고, 칭찬 리뷰에 없는 시간대가 붙었다."""
        menu_sales = ("장승배기역 4번 상권에서 17시부터 24시까지 제육볶음 정식 매출이 전년 동기 대비 19.31% 감소했어요[F2]. "
                      "손님 리뷰에도 제육볶음 정식 언급이 1건 있었어요[F3]. 쿠폰 홍보를 제안해요.")
        self.assertEqual(reason_problems(menu_sales, self.tied), [
            {"type": "label_changed", "detail": "[F2] 문장에는 '제육볶음 정식'을(를) 넣지 않아요 ([F3] 문장에만 써요)"}])
        timed_praise = (self.market + "장승배기역 4번 상권에서 17시부터 24시까지 제육볶음 정식 칭찬 리뷰가 1건 있어요[F3]. "
                        "쿠폰 홍보를 제안해요.")
        self.assertEqual(reason_problems(timed_praise, self.tied), [
            {"type": "label_changed", "detail": "[F3] 문장에는 '장승배기역 4번 상권', '17~24시'을(를) 넣지 않아요 ([F2] 문장에만 써요)"}])
        together = ("장승배기역 4번 상권의 17~24시 추정매출이 19.31% 감소했고 손님 칭찬 리뷰에 제육볶음 정식 언급이 1건 있어요[F2][F3]. "
                    "저녁 손님을 다시 부르는 제육볶음 정식 쿠폰 홍보를 제안해요.")
        self.assertEqual(reason_problems(together, self.tied), [])                  # 두 카드를 함께 인용한 문장, 인용 없는 '할 일' 문장은 된다

    def test_code_line_goes_right_after_the_cited_sentence(self):
        from web.cards import insert_code_line
        line = "손님 칭찬 리뷰에 제육볶음 정식 언급이 1건 있어요 [F3]"
        cases = {
            "감소했어요[F2]. 쿠폰 홍보를 제안해요.": f"감소했어요[F2].\n{line}\n쿠폰 홍보를 제안해요.",
            "감소했어요 [F2]\n쿠폰 홍보를 제안해요.": f"감소했어요 [F2]\n{line}\n쿠폰 홍보를 제안해요.",
            "감소했어요. [F2] 쿠폰 홍보를 제안해요.": f"감소했어요. [F2]\n{line}\n쿠폰 홍보를 제안해요.",
            "감소했으므로[F2], 쿠폰 홍보를 제안해요. 끝 문장.": f"감소했으므로[F2], 쿠폰 홍보를 제안해요.\n{line}\n끝 문장.",   # 문장 가운데는 자르지 않는다
            "감소했어요. 쿠폰 홍보를 제안해요[F2]": f"감소했어요. 쿠폰 홍보를 제안해요[F2]\n{line}",
            "감소했어요[F2]": f"감소했어요[F2]\n{line}",
        }
        for text, wanted in cases.items():
            with self.subTest(text):
                self.assertEqual(insert_code_line(text, line, "F2"), wanted)

    def test_one_fact_card_is_judged_as_before(self):
        """근거 카드가 한 장인 카드(불만 카드, 칭찬 근거 없는 홍보 카드)는 규칙이 예전과 같다."""
        facts_a = plan_cards(insight(), [], "store_ongi")[0].facts
        self.assertEqual(reason_problems("포장 누락 불만이 3건, 모두 17~21시에 들어왔어요 [F1]\n재발 방지 공지를 올려요.", facts_a), [])
        self.assertEqual(self.types("17~21시에 불만이 반복됐어요[F1].", facts_a), ["no_fact_value"])
        facts_b = plan_cards(insight(), load_json(AnalysisSnapshot, EVENING), "store_ongi")[1].facts
        self.assertEqual([f["id"] for f in facts_b], ["F2"])
        self.assertEqual(reason_problems(self.market + "저녁 손님을 다시 부르는 쿠폰 홍보를 제안해요.", facts_b), [])


# ── 서버 (Demo) ─────────────────────────────────────────────────────
class PraiseSource(FakeSource):
    """리뷰 분석 서버 대신. 방문자마다 붙여넣은 리뷰를 따로 두고, 붙여넣은 리뷰를 분류해 준다 (별점 4점 이상이면 긍정)."""

    def __init__(self):
        super().__init__()
        self.books: dict = {}
        self.pasted = self.books.setdefault(None, [])

    def for_visitor(self, visitor):
        view = copy.copy(self)
        view.pasted = self.books.setdefault(visitor, [])
        return view

    def paste(self, store_id, text, rating=None, channel=None):
        out = super().paste(store_id, text, rating, channel)
        self.pasted[-1]["rating"] = rating
        return out

    def insight(self, store_id):
        found = copy.deepcopy(super().insight(store_id))
        for r in self.pasted:
            positive = (r.get("rating") or 0) >= 4
            found["classifications"].append({
                "review_id": r["review_id"], "sentiment": "positive" if positive else "negative",
                "topics": [{"topic": "taste", "polarity": "positive" if positive else "negative", "evidence": r["text"][:6]}],
                "negative_topics": [] if positive else ["taste"], "method": "rule", "model": "kiwi", "warnings": []})
        return found


def echo_model(system, user):
    """가짜 모델: 참고 문장(고정 문장)을 그대로 돌려준다. 고정 문장은 규칙을 통과하므로 모델 문장으로 쓰인다."""
    return user.split("참고 문장(이 정도 길이, 근거 카드에 있는 사실만): ", 1)[1]


def client_for(tmp, source=None, **kw):
    demo = Demo(settings(Path(tmp), **kw), source=source or PraiseSource())
    return TestClient(create_app(demo)), demo


def promo(client):
    return next(c for c in client.get("/api/cards").json()["cards"] if c["card"]["kind"] == "promo")


class MockServer(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_card_b_carries_the_praise_evidence(self):
        client, _ = client_for(self.tmp)
        b = promo(client)
        self.assertTrue(b["title"].endswith("하락 → '제육볶음 정식' 쿠폰 홍보"))
        self.assertEqual([e["type"] for e in b["evidence"]], ["snapshot", "praise"])
        self.assertEqual([f["id"] for f in b["facts"]], ["F2", "F3"])
        self.assertEqual(b["card"]["review_ids"], ["rv_ongi_013"])
        self.assertEqual((b["reason_source"], b["problems"]), ("고정 문장", []))
        a = client.get("/api/cards").json()["cards"][0]
        self.assertEqual([e["type"] for e in a["evidence"]], ["review"] * 3)         # 불만 카드는 그대로

    def test_pasted_praise_shows_only_on_that_visitors_card(self):
        """두 방문자가 각자 한 건씩 붙여넣으면 리뷰 번호(…_paste_001)가 같다. 근거 리뷰 글이 서로 섞이면 안 된다."""
        a_client, _ = client_for(self.tmp)
        b_client, c_client = TestClient(a_client.app), TestClient(a_client.app)
        a_client.post("/api/reviews", json={"text": "제육볶음 정식 A 가 쓴 칭찬", "rating": 5})
        b_client.post("/api/reviews", json={"text": "제육볶음 정식 B 가 쓴 칭찬", "rating": 5})
        texts = lambda client: [e["text"] for e in praise_of(promo(client))]       # noqa: E731
        for _ in range(2):                                                          # 두 번째는 기억해 둔 계획에서 온다
            self.assertIn("제육볶음 정식 A 가 쓴 칭찬", texts(a_client))
            self.assertNotIn("제육볶음 정식 B 가 쓴 칭찬", texts(a_client))
            self.assertIn("제육볶음 정식 B 가 쓴 칭찬", texts(b_client))
            self.assertNotIn("제육볶음 정식 A 가 쓴 칭찬", texts(b_client))
            self.assertEqual(texts(c_client), ["제육볶음이 불맛 나고 정말 맛있어요!"])    # 아무것도 안 붙인 방문자
        self.assertIn("제육볶음 정식 언급이 2건으로 가장 많아요", promo(a_client)["card"]["reason_text"])
        self.assertIn("제육볶음 정식 언급이 1건 있어요", promo(c_client)["card"]["reason_text"])

    def test_pasted_complaint_does_not_become_praise(self):
        client, _ = client_for(self.tmp)
        client.post("/api/reviews", json={"text": "계란말이가 다 식어서 왔어요", "rating": 1})
        client.post("/api/reviews", json={"text": "계란말이 너무 짜요", "rating": 2})
        self.assertEqual([e["id"] for e in praise_of(promo(client))], ["rv_ongi_013"])

    @unittest.skipUnless(HAS_C6, "C6 저장본 없음")
    def test_card_menu_is_the_saved_promo_menu(self):
        client, _ = client_for(self.tmp)
        b = promo(client)
        r = client.post(f"/api/cards/{b['card']['card_id']}/run").json()
        self.assertIn(f"coupon:{praise_of(b)[0]['menu']}", r["drafts"][0]["evidence_ids"])

    @unittest.skipUnless(HAS_C6, "C6 저장본 없음")
    def test_mock_card_does_not_name_a_menu_the_saved_promo_is_not_about(self):
        """mock 의 홍보글은 저장 예시(제육볶음 정식)다. 붙여넣은 칭찬으로 고른 메뉴가 달라지면 카드는 메뉴를 말하지 않는다."""
        client, _ = client_for(self.tmp)
        client.post("/api/reviews", json={"text": "계란말이 또 시킬게요", "rating": 5})
        client.post("/api/reviews", json={"text": "계란말이 아이가 잘 먹어요", "rating": 5})
        b = promo(client)
        self.assertEqual(b["title"], OLD_TITLE)
        self.assertEqual(([e["type"] for e in b["evidence"]], b["card"]["review_ids"]), (["snapshot"], []))
        self.assertNotIn("계란말이", json.dumps(b, ensure_ascii=False))
        r = client.post(f"/api/cards/{b['card']['card_id']}/run").json()
        self.assertIn("coupon:제육볶음 정식", r["drafts"][0]["evidence_ids"])

    def test_unreadable_review_still_shows_the_cards(self):
        """계약 형식으로 못 바꾸는 리뷰가 있어도 카드 화면은 뜬다 (칭찬 근거 없이 예전 카드)."""
        class BrokenSource(PraiseSource):
            def reviews(self, store_id):
                return super().reviews(store_id) + [{"review_id": "rv_bad", "store_id": store_id, "text": "제육볶음 맛있어요",
                                                     "created_at": "2026-11-09T23:00:00+09:00", "rating": 9}]
        client, _ = client_for(self.tmp, source=BrokenSource())
        with self.assertLogs("web.demo", level="WARNING") as logs:
            res = client.get("/api/cards")
        self.assertEqual(res.status_code, 200, res.text)
        b = next(c for c in res.json()["cards"] if c["card"]["kind"] == "promo")
        self.assertEqual((b["title"], [e["type"] for e in b["evidence"]]), (OLD_TITLE, ["snapshot"]))
        self.assertIn("칭찬 근거", logs.output[0])
        self.assertNotIn("제육볶음 맛있어요", logs.output[0])                         # 리뷰 글은 로그에 남기지 않는다


class LiveServer(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_reason_version_was_raised(self):
        from web.demo import REASON_VERSION
        self.assertNotEqual(REASON_VERSION, "reason-v1")                            # 예전 방식으로 저장해 둔 이유 문장을 다시 쓰지 않는다

    def test_model_gets_only_the_market_card_and_code_adds_the_praise_line(self):
        """모델에게는 상권 지표 카드만 간다 (메뉴·칭찬 건수를 모른다). 칭찬 근거 줄은 코드가 [F2] 문장 바로 뒤에 끼운다."""
        asked = []

        def model(system, user):
            asked.append(user)
            if '"F1"' in user:
                return echo_model(system, user)
            return ("장승배기역 4번 상권의 관측 업종 합산 추정매출은 2026년 2분기에 전년 동기 대비 27.95% 감소했어요[F2]. "
                    "손님을 다시 부르는 쿠폰 홍보를 제안해요.")
        demo = Demo(settings(self.tmp, mode="live"), source=PraiseSource(), reason_model=model)
        b = next(c for c in demo.cards()["cards"] if c["card"]["kind"] == "promo")
        self.assertEqual((b["reason_source"], b["problems"]), ("HCX-005 (검사기 통과)", []))
        self.assertEqual(b["card"]["reason_text"].split("\n"), [
            "장승배기역 4번 상권의 관측 업종 합산 추정매출은 2026년 2분기에 전년 동기 대비 27.95% 감소했어요.",
            "손님 칭찬 리뷰에 제육볶음 정식 언급이 1건 있어요",
            "손님을 다시 부르는 쿠폰 홍보를 제안해요."])
        self.assertIn("27.95% 감소했어요[F2].\n손님 칭찬 리뷰에 제육볶음 정식 언급이 1건 있어요 [F3]\n", b["checked_text"])
        self.assertEqual([f["id"] for f in b["facts"]], ["F2", "F3"])                 # 카드의 근거는 둘 다
        promo_ask = next(u for u in asked if '"F2"' in u)
        for hidden in ('"F3"', "제육볶음", "칭찬"):
            self.assertNotIn(hidden, promo_ask)
        self.assertIn("참고 문장(이 정도 길이, 근거 카드에 있는 사실만): 장승배기역 4번 상권의", promo_ask)

    def test_bad_market_sentence_falls_back_to_the_fixed_sentence_with_both(self):
        def model(system, user):
            return echo_model(system, user) if '"F1"' in user else "매출이 늘어날 것으로 예상돼요[F2]."
        demo = Demo(settings(self.tmp, mode="live"), source=PraiseSource(), reason_model=model)
        b = next(c for c in demo.cards()["cards"] if c["card"]["kind"] == "promo")
        self.assertIn("검사 불통과", b["reason_source"])
        self.assertIn("27.95% 감소 [F2]\n손님 칭찬 리뷰에 제육볶음 정식 언급이 1건 있어요 [F3]\n", b["checked_text"])

    def test_too_many_model_sentences_do_not_fit_with_the_praise_line(self):
        """모델이 세 문장을 쓰면 칭찬 줄까지 네 문장이 된다 → 규칙(세 문장)에 걸려 고정 문장으로."""
        def model(system, user):
            if '"F1"' in user:
                return echo_model(system, user)
            return ("장승배기역 4번 상권의 관측 업종 합산 추정매출은 2026년 2분기에 전년 동기 대비 27.95% 감소했어요[F2]. "
                    "손님을 다시 부르는 쿠폰 홍보를 제안해요. 쿠폰은 홍보글과 함께 올려요.")
        demo = Demo(settings(self.tmp, mode="live"), source=PraiseSource(), reason_model=model)
        b = next(c for c in demo.cards()["cards"] if c["card"]["kind"] == "promo")
        self.assertIn("검사 불통과", b["reason_source"])
        self.assertEqual([p["type"] for p in b["problems"]], ["too_long"])

    def test_praise_is_part_of_the_saved_reason_key(self):
        """칭찬 근거가 달라지면(1건 → 2건) 저장해 둔 이유 문장을 다시 쓰지 않고 모델에게 새로 묻는다."""
        calls = []

        def model(system, user):
            calls.append(user)
            return echo_model(system, user)
        demo = Demo(settings(self.tmp, mode="live"), source=PraiseSource(), reason_model=model)
        demo.cards(visitor="visitor_one_1234")
        first = len(calls)
        demo.cards(visitor="visitor_two_1234")                                      # 근거가 같은 다른 방문자: 다시 묻지 않는다
        self.assertEqual(len(calls), first)
        demo.paste("제육볶음 정식 든든해요", 5, None, visitor="visitor_two_1234")
        text = next(c for c in demo.cards(visitor="visitor_two_1234")["cards"] if c["card"]["kind"] == "promo")["card"]["reason_text"]
        self.assertEqual(len(calls), first + 1)                                     # 카드 ⓑ 만 새로 (카드 ⓐ 근거는 그대로)
        self.assertIn("제육볶음 정식 언급이 2건으로 가장 많아요", text)

    @unittest.skipUnless(HAS_C6, "C6 코드 없음")
    def test_card_menu_is_the_coupon_menu_c6_writes_about(self):
        """live: 붙여넣은 칭찬으로 계란말이가 가장 많이 언급되면 카드도, C6 가 쓴 홍보글의 쿠폰도 계란말이다."""
        demo = Demo(settings(self.tmp, mode="live", clova_key="test-key"), source=PraiseSource(), reason_model=echo_model)
        client = TestClient(create_app(demo))
        for text in ("계란말이 또 시킬게요", "계란말이 아이가 잘 먹어요"):
            self.assertEqual(client.post("/api/reviews", json={"text": text, "rating": 5}).status_code, 201)
        b = promo(client)
        self.assertEqual({e["menu"] for e in praise_of(b)}, {"계란말이"})
        self.assertIn("계란말이 언급이 3건으로 가장 많아요", b["card"]["reason_text"])
        self.assertIn("'계란말이' 쿠폰 홍보", b["title"])
        with mock.patch("clova.call", side_effect=lambda key, system, messages, **kw: {"content": EGG_GOOD, "won": 0.01}):
            res = client.post(f"/api/cards/{b['card']['card_id']}/run")
        self.assertEqual(res.status_code, 200, res.text)
        draft = res.json()["drafts"][0]
        self.assertIn("coupon:계란말이", draft["evidence_ids"])
        self.assertIn("🎟 계란말이 1,000원 할인 쿠폰", draft["text"])
        self.assertFalse(draft["checks"]["used_fallback"])

    @unittest.skipUnless(HAS_C6, "C6 코드 없음")
    def test_card_and_coupon_menu_agree_for_the_fixture_reviews(self):
        """시험 고정 리뷰(메뉴마다 1건, 같은 수): 카드와 쿠폰 모두 메뉴판 순서의 제육볶음 정식."""
        demo = Demo(settings(self.tmp, mode="live", clova_key="test-key"), source=PraiseSource(), reason_model=echo_model)
        client = TestClient(create_app(demo))
        b = promo(client)
        answer = "오늘 저녁은 매콤한 제육볶음 정식으로 든든하게 드셔 보세요. 정성껏 볶아서 따뜻하게 보내드립니다. 편하게 주문해 주시기 바랍니다."
        seen = []

        def fake(key, system, messages, **kw):
            seen.append(system)
            return {"content": answer, "won": 0.01}
        with mock.patch("clova.call", side_effect=fake):
            draft = client.post(f"/api/cards/{b['card']['card_id']}/run").json()["drafts"][0]
        self.assertEqual(praise_of(b)[0]["menu"], "제육볶음 정식")
        self.assertIn("coupon:제육볶음 정식", draft["evidence_ids"])
        reaction = seen[0][seen[0].index("## 손님 반응"):seen[0].index("## 규칙")]
        self.assertIn(praise_of(b)[0]["text"], reaction)                             # 카드 근거로 보여 준 칭찬 리뷰가 홍보글 프롬프트에도 들어간다
        self.assertEqual(re.findall(r"된장찌개|김치찌개|순두부찌개|불고기|계란말이", reaction), [])


if __name__ == "__main__":
    unittest.main()
