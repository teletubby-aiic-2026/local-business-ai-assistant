"""답글 태도(c6.stance)와 '사과 없이 사실을 설명하는 답글'(c6.reply_explain) 검증 — AI 호출 없음 (가짜 응답).

실행 (experiments/marketing 에서):
  python -m pytest -q tests/test_c6_stance.py      또는      python -m tests.test_c6_stance
리뷰 문장은 모두 이 시험을 위해 지어낸 합성 문장이다 (데모 가게 온기한식 메뉴 기준).
"""

import unittest
from unittest.mock import patch

from shared.contracts import RecommendationCard, ReviewRecord
from shared.sample_scenario import SAMPLE_REVIEWS, SAMPLE_STORE, SAMPLE_TONE

from c6 import checks
from c6.contract import build_context
from c6.dummy import POLICIES
from c6.output import DraftOutput, _VALID_STANCES
from c6.reply import SYSTEM_TMPL, generate_reply_draft
from c6 import reply_explain as rx
from c6.stance import (APOLOGY, APOLOGY_CHECKS, CHECKS_BY_STANCE, EXPLAIN, EXPLAIN_CHECKS, EXPLAIN_NEEDS_INPUT,
                       FEE_PRINCIPLE, OPTIONAL_CHECKS, REQUESTS, STANCES, judge_review, judge_stance)

MENU = list(SAMPLE_STORE.menu)
PRICES = list(SAMPLE_STORE.menu_prices.values())

# 가게 과실이 아닌 '원칙 밖 요청 → 거절 → 낮은 별점' (합성)
UNFAIR = {
    "menu_change": "제육볶음 정식 고기를 불고기로 그냥 바꿔 달라고 했더니 안 된대요. 그것도 못 해 주나요? 별 하나 드립니다",
    "free_extra": "계란말이 서비스로 하나 달라고 했더니 안 된다고 하셨어요. 단골한테 너무하네요",
    "refund_after_eating": "다 먹고 나서 환불해 달라고 했더니 안 된다고 하네요. 별 하나 드립니다",
    "fee": "된장찌개를 순두부찌개로 그냥 바꿔 달라고 했는데 추가 요금을 내라고 하네요. 실망이에요",
    "customer_mistake": "제가 주문을 잘못 넣어서 된장찌개를 받았는데, 김치찌개로 다시 보내 달라니까 안 된대요",
    "outside_area_hours": "배달 가능 지역에서 조금 벗어났다고 주문을 안 받아 주시네요. 바로 옆인데 너무해요",
}

# 가게 과실일 수 있는 불만 — 무리한 말이 섞여 있어도 사과 답글이어야 한다 (잘못 판정하면 안 되는 쪽)
FAULT = {
    "누락+무리한 말": "계란말이가 빠져 있었어요. 이럴 거면 다음엔 공짜로 하나 더 주셔야죠. 바꿔 달라고 해도 안 된다더니 진짜 별로",
    "거절+불친절": "불고기 덮밥 밥을 반만 달라고 했더니 안 된다고 퉁명스럽게 말하셨어요",
    "거절+늦은 배달": "순두부찌개를 김치찌개로 바꿔 달라고 했는데 안 된대요. 게다가 1시간 넘게 걸려서 왔어요",
    "거절+식은 음식": "김치찌개가 다 식어서 다시 보내 달라고 했더니 안 된대요",
    "거절+잘못 온 메뉴": "주문한 거랑 다른 메뉴가 와서 바꿔 달라니까 안 된다네요",
    "거절+이물질": "서비스로 계란말이 달라고 한 건 안 된다더니 반찬에 머리카락까지 나왔어요",
    "요청사항 반영 안 됨": "요청사항에 계란말이 서비스로 부탁드린다고 썼는데 안 된다고 하시네요",
    "맛 불만+환불 거절": "다 먹고 나서 맛이 이상해서 환불해 달라고 했는데 안 된대요",
    "양 불만+거절": "양이 너무 적어서 더 달라고 했는데 추가 요금을 내라네요",
    "음식 별로+교체 거절": "음식이 별로라서 다른 메뉴로 바꿔 달라고 했는데 거절하셨어요",
}

# 요청이나 거절 표현이 없어 애매한 불만 — 사과 답글
AMBIGUOUS = {
    "거절 표현 없음": "제육볶음 정식 고기를 불고기로 바꿔 달라고 요청했어요",
    "요청 표현 없음": "주문했는데 안 된다고 하시네요. 별 하나요",
    "막연한 불만": "별로예요. 다시는 안 시켜요",
    "정당한 요청 거절(수저)": "젓가락 좀 넣어 달라고 했더니 안 된대요",
}


def _review(text, rid="rv_ongi_paste_001", topics=("service",)):
    return ReviewRecord(review_id=rid, store_id=SAMPLE_STORE.store_id, text=text, created_at="2026-11-14T19:00:00+09:00",
                        rating=1, input_method="paste", sentiment="negative", topics=list(topics),
                        negative_topics=list(topics))


def _assemble(ai_part, decision):
    return rx.assemble("안녕하세요 고객님 :)", rx.build_body(ai_part, decision), "온기한식 드림")


# ── 1. 태도 판정 ─────────────────────────────────────────────────────
class TestJudgeStance(unittest.TestCase):
    def test_unfair_requests_are_explain(self):
        expect = {"menu_change": "menu_change", "free_extra": "free_extra", "refund_after_eating": "refund_after_eating",
                  "fee": "menu_change", "customer_mistake": "customer_mistake",
                  "outside_area_hours": "outside_area_hours"}
        for name, text in UNFAIR.items():
            with self.subTest(name):
                d = judge_stance(text)
                self.assertEqual(d.stance, EXPLAIN, d.reasons)
                self.assertEqual(d.request, expect[name])
                self.assertTrue(d.principle)
                self.assertTrue(any(r.startswith("거절") for r in d.reasons))

    def test_fee_refusal_uses_fee_principle(self):
        self.assertEqual(judge_stance(UNFAIR["fee"]).principle, FEE_PRINCIPLE)
        self.assertEqual(judge_stance(UNFAIR["menu_change"]).principle, REQUESTS["menu_change"]["principle"])

    def test_store_fault_mixed_with_unreasonable_words_stays_apology(self):
        for name, text in FAULT.items():
            with self.subTest(name):
                d = judge_stance(text)
                self.assertEqual(d.stance, APOLOGY, d.reasons)
                self.assertTrue(any("가게 과실" in r for r in d.reasons), d.reasons)

    def test_ambiguous_stays_apology(self):
        for name, text in AMBIGUOUS.items():
            with self.subTest(name):
                self.assertEqual(judge_stance(text).stance, APOLOGY)

    def test_fault_topic_from_classifier_vetoes(self):
        """글에는 과실 표현이 없어도 리뷰 분류가 포장 누락·배달 시간 등을 붙였으면 사과 답글."""
        text = UNFAIR["menu_change"]
        self.assertEqual(judge_stance(text, negative_topics=["service"]).stance, EXPLAIN)
        for topic in ("missing_item", "delivery_time", "temperature", "hygiene", "packaging", "wait_time"):
            with self.subTest(topic):
                d = judge_stance(text, negative_topics=["service", topic])
                self.assertEqual(d.stance, APOLOGY)
                self.assertIn(f"리뷰 분류의 과실 주제 — {topic}", d.reasons)

    def test_free_word_is_not_salty_taste(self):
        """'공짜'의 '짜'를 맛(짜다)으로 보지 않는다."""
        self.assertEqual(judge_stance("계란말이 공짜로 달라고 했는데 안 된대요").stance, EXPLAIN)
        self.assertEqual(judge_stance("계란말이 공짜로 달라고 했는데 안 된대요. 찌개도 짜고요").stance, APOLOGY)

    def test_customer_mistake_needs_self_mistake_and_redo(self):
        self.assertEqual(judge_stance("김치찌개로 다시 보내 달라니까 안 된대요").stance, APOLOGY)   # 손님 실수라는 말 없음
        self.assertEqual(judge_stance(UNFAIR["customer_mistake"]).request, "customer_mistake")

    def test_empty_and_deterministic(self):
        self.assertEqual(judge_stance("").stance, APOLOGY)
        self.assertEqual(judge_stance(UNFAIR["free_extra"]), judge_stance(UNFAIR["free_extra"]))

    def test_demo_sample_reviews_stay_apology(self):
        """발표용 포장 누락 3건(rv_ongi_001~003)은 그대로 사과 답글."""
        for rv in SAMPLE_REVIEWS:
            self.assertEqual(judge_review(rv).stance, APOLOGY)

    def test_stance_values_match_draft_output(self):
        self.assertEqual(tuple(STANCES), _VALID_STANCES)
        self.assertEqual(set(CHECKS_BY_STANCE), set(STANCES))


# ── 2. 담백 대응 점검 (규칙마다 통과 예·실패 예) ─────────────────────────
class TestExplainCheckRules(unittest.TestCase):
    def test_no_compensation_offer(self):
        self.assertFalse(checks.offers_compensation("메뉴판에 있는 구성대로만 준비하고 있어요."))
        self.assertFalse(checks.offers_compensation("앞으로도 메뉴판 안에서 늘 정성껏 준비할게요."))
        for bad in ("다음 주문 때 계란말이 하나 더 챙겨 드릴게요.", "환불은 바로 해 드릴게요.", "다음엔 무료로 바꿔 드릴게요.",
                    "요청하신 대로 해 드릴게요.", "쿠폰을 보내 드릴게요."):
            with self.subTest(bad):
                self.assertTrue(checks.offers_compensation(bad))

    def test_no_fault_admission(self):
        self.assertFalse(checks.admits_fault("원하시던 대로 해 드리지 못해 아쉬우셨을 것 같아요."))
        for bad in ("불편을 드려 죄송해요.", "저희 잘못이에요.", "저희 실수로 그렇게 됐어요.", "사과드려요.", "모두 저희 책임이에요."):
            with self.subTest(bad):
                self.assertTrue(checks.admits_fault(bad))

    def test_no_customer_blame(self):
        self.assertFalse(checks.blames_customer("제육볶음 정식을 원하시던 대로 해 드리지 못해 아쉬우셨을 것 같아요."))
        for bad in ("무리한 요구는 들어드릴 수 없어요.", "주문 전에 메뉴판을 확인하셔야 해요.", "원래 그렇게는 안 돼요.",
                    "그런 건 당연히 안 되죠.", "그러시면 다른 가게를 이용해 주세요.", "규정 위반이라 안 돼요.", "주문 시 참고 부탁드려요.",
                    "별점 테러는 곤란해요 ㅋㅋ"):
            with self.subTest(bad):
                self.assertTrue(checks.blames_customer(bad))

    def test_has_regret(self):
        self.assertTrue(checks.has_regret("원하시던 대로 해 드리지 못해 아쉬우셨을 것 같아요."))
        self.assertTrue(checks.has_regret("기대에 못 미쳐 속상하셨을 것 같아요."))
        self.assertFalse(checks.has_regret("메뉴판에 있는 구성대로만 준비하고 있어요."))

    def test_explains_principle(self):
        self.assertTrue(checks.explains_principle("저희는 메뉴판에 있는 구성대로만 준비하고 있어요."))
        self.assertTrue(checks.explains_principle("드신 뒤의 요청은 배달앱 고객센터를 통해 안내해 드리고 있어요."))
        self.assertFalse(checks.explains_principle("아쉬우셨을 것 같아요. 다음에 또 찾아 주세요."))

    def test_request_mentioned(self):
        review = UNFAIR["menu_change"]
        self.assertTrue(checks.mentions_review_items("제육볶음 정식 고기를 바꿔 드리지 못해 아쉬우셨을 것 같아요.", review, MENU))
        self.assertTrue(checks.mentions_review_items("불고기로 바꾸고 싶으셨을 텐데 아쉬우셨을 것 같아요.", review, MENU))
        self.assertFalse(checks.mentions_review_items("원하시던 대로 해 드리지 못해 아쉬우셨을 것 같아요.", review, MENU))
        # 리뷰에 메뉴 이름이 없으면 따지지 않는다
        self.assertTrue(checks.mentions_review_items("아쉬우셨을 것 같아요.", UNFAIR["outside_area_hours"], MENU))

    def test_haeyo_only(self):
        self.assertTrue(checks.haeyo_only("제육볶음 정식을 바꿔 드리지 못해 아쉬우셨을 것 같아요."))
        self.assertTrue(checks.haeyo_only("속상하셨겠어요. 원하시던 대로 못 해 드렸어요!"))
        self.assertFalse(checks.haeyo_only("아쉬우셨을 것 같습니다."))
        self.assertFalse(checks.haeyo_only("아쉬우셨을 거예요. 양해 부탁드립니다."))
        self.assertFalse(checks.haeyo_only(""))

    def test_personal_info_length_and_tone_rules_are_the_existing_ones(self):
        d = judge_stance(UNFAIR["menu_change"])
        ai = "제육볶음 정식 고기를 불고기로 바꿔 드리지 못해 아쉬우셨을 것 같아요."
        good = _assemble(ai, d)
        bad = _assemble("김민수님, 010-1234-5678로 연락 주세요. 아쉬우셨을 것 같아요.", d)
        kw = dict(review_text=UNFAIR["menu_change"], menu_names=MENU, allowed_numbers=PRICES, policies=POLICIES,
                  forbidden_phrases=SAMPLE_TONE.forbidden_phrases, evidence=["F_x"], valid_ids={"F_x"})
        ok = rx.run_explain_checks(good, ai_part=ai, **kw)
        self.assertEqual([k for k, v in ok.items() if not v], [])
        ng = rx.run_explain_checks(bad, ai_part="김민수님, 010-1234-5678로 연락 주세요. 아쉬우셨을 것 같아요.", **kw)
        self.assertFalse(ng["no_personal_info"])
        self.assertFalse(ng["no_bad_number"])
        stiff = rx.run_explain_checks(good, ai_part="해당 요청을 들어드리지 못해 아쉬우셨을 것 같아요.", **kw)
        self.assertFalse(stiff["no_stiff_words"])

    def test_bad_promise_is_the_same_policy_check(self):
        """정책에 없는 보상 약속 점검(promises_not_in_policy)은 사과 답글과 같은 함수·정책으로 본다."""
        d = judge_stance(UNFAIR["free_extra"])
        text = _assemble("계란말이를 무료로 드리지 못해 아쉬우셨을 것 같아요.", d)
        res = rx.run_explain_checks(text, ai_part=text, review_text=UNFAIR["free_extra"], menu_names=MENU,
                                    allowed_numbers=PRICES, policies=POLICIES, forbidden_phrases=[],
                                    evidence=["F_x"], valid_ids={"F_x"})
        self.assertFalse(res["no_bad_promise"])
        self.assertEqual(res["no_bad_promise"], not checks.promises_not_in_policy(text, POLICIES))

    def test_has_apology_meaning_unchanged(self):
        """has_apology 는 여전히 '첫 문장에 죄송'만 본다 (공지 점검에 그대로 씀)."""
        self.assertTrue(checks.has_apology("불편하셨을 텐데 정말 죄송해요. 다음엔 챙길게요."))
        self.assertFalse(checks.has_apology("아쉬우셨을 것 같아요. 죄송해요."))

    def test_fallback_sentence_passes_every_explain_check(self):
        for name, text in UNFAIR.items():
            with self.subTest(name):
                d = judge_stance(text)
                ai = rx.fallback_empathy(text, MENU)
                full = _assemble(ai, d)
                res = rx.run_explain_checks(full, ai_part=ai, review_text=text, menu_names=MENU, allowed_numbers=PRICES,
                                            policies=POLICIES, forbidden_phrases=SAMPLE_TONE.forbidden_phrases,
                                            evidence=["F_x"], valid_ids={"F_x"})
                self.assertEqual([k for k, v in res.items() if not v], [], full)

    def test_clean_ai_part_drops_copied_code_lines(self):
        d = judge_stance(UNFAIR["outside_area_hours"])
        raw = f"- 아쉬우셨을 것 같아요.\n{d.principle} {rx.CLOSING_LINE} -"
        self.assertEqual(rx.clean_ai_part(raw, d), "아쉬우셨을 것 같아요.")


# ── 3. 생성 흐름 (가짜 HCX) ─────────────────────────────────────────────
def _ctx(reviews):
    card = RecommendationCard(card_id="card_t", store_id=SAMPLE_STORE.store_id, kind="complaint", reason_text="시험",
                              review_ids=[r.review_id for r in reviews])
    return build_context(store=SAMPLE_STORE, reviews=reviews, tone=SAMPLE_TONE, cards=[card], snapshots=[]), card


class TestGenerateByStance(unittest.TestCase):
    def test_explain_review_gets_explain_draft(self):
        seen = []

        def fake(key, system, messages, **kw):
            seen.append(system)
            return {"content": "제육볶음 정식 고기를 불고기로 바꾸고 싶으셨을 텐데 그렇게 해 드리지 못해 아쉬우셨을 것 같아요.", "won": 0.01}

        ctx, card = _ctx([_review(UNFAIR["menu_change"])])
        with patch("clova.call", side_effect=fake):
            d = generate_reply_draft(ctx, card, "k", chosen_measures=[{"id": "M1", "text": "포장 마감 전 주문서 대조"}]).drafts[0]
        self.assertEqual(d.stance, EXPLAIN)
        self.assertEqual(set(d.checks) - set(OPTIONAL_CHECKS), set(EXPLAIN_CHECKS))
        self.assertEqual(d.failed_reasons, [])
        self.assertEqual(d.needs_input, [EXPLAIN_NEEDS_INPUT])
        self.assertIn("사과 없이", d.needs_input[0])
        self.assertTrue(d.stance_reasons)
        self.assertNotIn("죄송", d.text)
        self.assertIn(REQUESTS["menu_change"]["principle"], d.text)
        self.assertNotIn("주문서", d.text)            # 포장 누락용 재발 방지 조치(M1)를 끼워 넣지 않는다
        self.assertEqual(d.evidence_ids, ["F_rv_ongi_paste_001"])
        self.assertIn("사과·잘못 인정 금지", seen[0])   # 담백 대응 프롬프트로 불렀다
        self.assertEqual(d.to_dict()["stance"], EXPLAIN)
        self.assertEqual(d.to_dict()["stance_reasons"], d.stance_reasons)

    def test_explain_rewrites_then_passes(self):
        answers = iter(["불편을 드려 정말 죄송합니다.",
                        "제육볶음 정식을 원하시던 대로 해 드리지 못해 아쉬우셨을 것 같아요."])
        ctx, card = _ctx([_review(UNFAIR["menu_change"])])
        with patch("clova.call", side_effect=lambda *a, **k: {"content": next(answers)}) as call:
            d = generate_reply_draft(ctx, card, "k").drafts[0]
        self.assertEqual(call.call_count, 2)
        self.assertEqual(d.rewrites, 1)
        self.assertEqual(d.failed_reasons, [])
        retry_msg = call.call_args_list[1].args[2][-1]["content"]
        self.assertIn("수정 지시", retry_msg)
        self.assertIn("'죄송'", retry_msg)

    def test_explain_falls_back_and_tells_the_owner(self):
        ctx, card = _ctx([_review(UNFAIR["free_extra"])])
        with patch("clova.call", side_effect=lambda *a, **k: {"content": "규정상 안 됩니다. 죄송합니다."}) as call:
            d = generate_reply_draft(ctx, card, "k").drafts[0]
        self.assertEqual(call.call_count, 1 + rx.MAX_REWRITES)
        self.assertEqual(d.failed_reasons, [])
        self.assertIn(rx.FALLBACK_NOTE, d.needs_input)
        self.assertIn("계란말이 요청을 원하시던 대로 해 드리지 못해 아쉬우셨을 것 같아요.", d.text)

    def test_explain_call_failure_is_reported(self):
        ctx, card = _ctx([_review(UNFAIR["outside_area_hours"])])
        with patch("c6.reply_explain.RETRY_WAIT_S", 0), \
                patch("clova.call", side_effect=lambda *a, **k: {"error": "HTTP 429: 한도"}) as call:
            d = generate_reply_draft(ctx, card, "k").drafts[0]
        self.assertEqual(call.call_count, 2)   # 오류면 한 번만 다시 부른다
        self.assertIn(rx.CALL_FAILED_NOTE, d.needs_input)
        self.assertEqual(d.failed_reasons, [])

    def test_fault_review_keeps_the_original_apology_path(self):
        """가게 과실 리뷰는 원래 프롬프트(SYSTEM_TMPL)와 원래 점검 묶음 그대로."""
        seen = []

        def fake(key, system, messages, **kw):
            seen.append(system)
            return {"content": "주문하신 계란말이가 빠져서 정말 죄송해요. 다음 주문 때 요청사항에 남겨 주시면 꼭 챙길게요. 소중한 말씀 감사해요."}

        ctx, card = _ctx([_review(FAULT["누락+무리한 말"], topics=("missing_item",))])
        with patch("clova.call", side_effect=fake):
            d = generate_reply_draft(ctx, card, "k").drafts[0]
        self.assertEqual(d.stance, APOLOGY)
        self.assertEqual(set(d.checks) - set(OPTIONAL_CHECKS), set(APOLOGY_CHECKS))
        self.assertEqual(d.needs_input, [])
        self.assertIn("리뷰에서 빠진 품목을 구체적으로 짚어 사과", seen[0])
        self.assertIn(SYSTEM_TMPL.split("## 규칙")[1].split("## 사실")[0].strip()[:60], seen[0])   # 원래 규칙 그대로

    def test_mixed_card_gets_one_draft_per_stance(self):
        reviews = [SAMPLE_REVIEWS[0], _review(UNFAIR["free_extra"], rid="rv_ongi_paste_002")]

        def fake(key, system, messages, **kw):
            if "첫머리 공감 부분만" in system:
                return {"content": "계란말이를 더 받고 싶으셨을 텐데 그렇게 못 해 드려 아쉬우셨을 것 같아요."}
            return {"content": "주문하신 공깃밥이 빠져서 정말 죄송해요. 다음 주문 때 요청사항에 남겨 주시면 꼭 챙길게요. 소중한 말씀 감사해요."}

        ctx, card = _ctx(reviews)
        with patch("clova.call", side_effect=fake):
            drafts = generate_reply_draft(ctx, card, "k").drafts
        self.assertEqual([d.stance for d in drafts], [APOLOGY, EXPLAIN])


class TestDraftOutputStance(unittest.TestCase):
    def test_default_and_validation(self):
        base = dict(draft_id="d1", card_id="c1", store_id="s1", generator="reply_draft", text="t")
        self.assertIsNone(DraftOutput(**base).stance)
        self.assertEqual(DraftOutput(**base).to_dict()["stance_reasons"], [])
        self.assertEqual(DraftOutput.from_dict({**base, "stance": "explain"}).stance, "explain")
        with self.assertRaises(ValueError):
            DraftOutput(**base, stance="angry")


if __name__ == "__main__":
    unittest.main(verbosity=2)
