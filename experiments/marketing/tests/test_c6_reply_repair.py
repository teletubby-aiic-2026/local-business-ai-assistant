"""답글 템플릿 쏠림 고침 (11/15) — 가짜 응답, 네트워크 없음.

PR #36(공감만 쓰기·말투 점검)과 PR #47(사과 포함 점검)을 합친 뒤, 실시간 HCX-005 답글 15건이 모두 코드 템플릿이었다.
원인은 사과↔말투 핑퐁: 사과를 넣으라는 힌트에 '죄송합니다'를 쓰면 해요체 점검이 걸리고, '~요'로 고치면 사과가 빠졌다.
① 다시 쓰기 힌트에 목표 말투와 사과 예시를 적는다  ② 남은 실패가 사과 어미·사과 빠짐뿐이면 코드가 그 부분만 고친다
③ 템플릿의 조사 오류('계란말이가 빠뜨리고')를 고친다.

실행 (experiments/marketing 에서):
  python -m pytest -q tests/test_c6_reply_repair.py      또는      python -m tests.test_c6_reply_repair
리뷰·답글 문장은 모두 이 시험을 위해 지어낸 합성 문장이다 (데모 가게 온기한식).
"""

import re
import unittest
from unittest.mock import patch

from shared.contracts import RecommendationCard
from shared.sample_scenario import SAMPLE_REVIEWS, SAMPLE_STORE, SAMPLE_TONE

from c6 import checks
from c6.contract import build_context
from c6.dummy import OWNER_REPLIES, POLICIES
from c6.measures import REPLY_FALLBACK_TMPL
from c6.reply import _repair_ai_part, generate_reply_draft
from c6.stance import OPTIONAL_CHECKS
from common.korean import josa


def one_review_ctx():
    review = SAMPLE_REVIEWS[0]    # 공깃밥이 빠졌다는 리뷰
    card = RecommendationCard(card_id="card_t", store_id=SAMPLE_STORE.store_id, kind="complaint", reason_text="시험",
                              review_ids=[review.review_id])
    ctx = build_context(store=SAMPLE_STORE, reviews=list(SAMPLE_REVIEWS), tone=SAMPLE_TONE, cards=[card], snapshots=[],
                        owner_replies=OWNER_REPLIES, policies=POLICIES)
    return ctx, card


def run_reply(answer, style):
    """HCX 가 늘 같은 글(answer)을 준다고 치고 답글 하나를 만든다. (초안, 받은 프롬프트 목록)"""
    ctx, card = one_review_ctx()
    prompts = []

    def fake(key, system, messages, **kw):
        prompts.append(messages[0]["content"])
        return {"content": answer, "won": 0.01}

    with patch("clova.call", side_effect=fake):
        return generate_reply_draft(ctx, card, "k", reply_style=style).drafts[0], prompts


class TestHintsNameTheRegister(unittest.TestCase):
    """① 힌트가 목표 말투와 사과 예시를 적는다."""

    def test_haeyo_hints_ask_for_jwesonghaeyo(self):
        style, apology = checks.fix_hints(["style_match", "apology_expressed"], register="해요체")
        for hint in (style, apology):
            self.assertIn("해요체", hint)
            self.assertIn("'정말 죄송해요'", hint)
            self.assertNotIn("예: '정말 죄송합니다'", hint)

    def test_hamnida_hints_ask_for_jwesonghamnida(self):
        style, apology = checks.fix_hints(["style_match", "apology_expressed"], register="합니다체")
        for hint in (style, apology):
            self.assertIn("합니다체", hint)
            self.assertIn("'정말 죄송합니다'", hint)

    def test_without_register_the_old_hints_stay(self):
        self.assertEqual(checks.fix_hints(["style_match"]),
                         ["말투를 섞지 말고 지정된 말투(해요체 또는 합니다체)로만 써 주세요."])
        self.assertIn("죄송하다는 사과", checks.fix_hints(["apology_expressed"])[0])

    def test_rewrite_prompt_carries_the_register_hint(self):
        _, prompts = run_reply("공깃밥 추가하셨는데 빠뜨려서 정말 죄송합니다.", "haeyo")
        self.assertEqual(len(prompts), 3)                     # 처음 1번 + 다시 쓰기 2번 (보정은 그 뒤에 한다)
        self.assertIn("'~요'로 끝내 주세요", prompts[1])
        self.assertIn("'정말 죄송해요'", prompts[1])


class TestApologyEnding(unittest.TestCase):
    """② (a) 끝 사과 어미만 말투에 맞춘다."""

    def test_to_haeyo(self):
        cases = {
            "공깃밥 추가하셨는데 빠뜨려서 정말 죄송합니다.": "공깃밥 추가하셨는데 빠뜨려서 정말 죄송해요.",
            "계란말이가 빠졌다니 정말 속상하시겠어요. 죄송합니다.": "계란말이가 빠졌다니 정말 속상하시겠어요. 죄송해요.",
            "불편을 드려 진심으로 사과드립니다!": "불편을 드려 진심으로 사과드려요!",
            "수저가 빠져 정말 죄송한 마음입니다.": "수저가 빠져 정말 죄송한 마음이에요.",
        }
        for before, after in cases.items():
            with self.subTest(before=before):
                self.assertEqual(checks.fix_apology_ending(before, "haeyo"), after)
                self.assertTrue(checks.style_match(after, "haeyo"))
                self.assertEqual(checks.fix_apology_ending(before, "mixed"), after)   # mixed 도 AI 부분은 해요체

    def test_to_hamnida(self):
        self.assertEqual(checks.fix_apology_ending("공깃밥이 빠져 불편하셨겠어요, 정말 죄송해요.", "hamnida"),
                         "공깃밥이 빠져 불편하셨겠어요, 정말 죄송합니다.")

    def test_only_apology_endings_change(self):
        for text in ("속상하셨을 것 같습니다. 죄송합니다.", "죄송합니다, 다음엔 잘하겠습니다.", "많이 불편하셨겠습니다."):
            with self.subTest(text=text):
                self.assertFalse(checks.style_match(checks.fix_apology_ending(text, "haeyo"), "haeyo"))

    def test_repair_only_for_style_and_apology(self):
        text = "공깃밥이 빠졌다니 속상하셨겠어요."
        self.assertEqual(_repair_ai_part(text, ["ai_part_only_empathy", "apology_expressed"], "haeyo", "해요체"), text)
        self.assertEqual(_repair_ai_part(text, [], "haeyo", "해요체"), text)
        self.assertEqual(_repair_ai_part("속상하셨을 것 같습니다.", ["style_match"], "haeyo", "해요체"),
                         "속상하셨을 것 같습니다.")      # 사과 아닌 문장의 말투는 고치지 않는다 → 템플릿으로 간다


class TestRepairInReply(unittest.TestCase):
    """② 다시 쓰기 2번 뒤에도 사과 어미·사과 빠짐만 남으면 템플릿 대신 AI 글을 살린다."""

    def assert_kept_ai_text(self, d, ai_text_part):
        self.assertFalse(d.checks["used_fallback"])
        self.assertTrue(d.checks["ai_part_repaired"])
        self.assertEqual(d.failed_reasons, [])
        self.assertEqual(d.rewrites, 2)
        self.assertIn(ai_text_part, d.text)
        self.assertTrue(d.checks["apology_expressed"] and d.checks["style_match"])

    def test_haeyo_reply_ending_in_jwesonghamnida(self):
        d, _ = run_reply("공깃밥 추가하셨는데 빠뜨려서 정말 죄송합니다.", "haeyo")
        self.assert_kept_ai_text(d, "공깃밥 추가하셨는데 빠뜨려서 정말 죄송해요.")
        self.assertNotIn("죄송합니다", d.text)

    def test_hamnida_reply_ending_in_jwesonghaeyo(self):
        d, _ = run_reply("공깃밥이 빠져 많이 불편하셨을 텐데 죄송해요.", "hamnida")
        self.assert_kept_ai_text(d, "공깃밥이 빠져 많이 불편하셨을 텐데 죄송합니다.")

    def test_empathy_without_apology_gets_one_short_apology(self):
        d, _ = run_reply("공깃밥이 빠졌다니 정말 속상하시겠어요.", "haeyo")
        self.assert_kept_ai_text(d, "공깃밥이 빠졌다니 정말 속상하시겠어요. 진심으로 죄송해요.")   # '정말'이 있어 '진심으로'
        d, _ = run_reply("공깃밥이 빠졌다니 많이 속상하시겠어요.", "haeyo")
        self.assert_kept_ai_text(d, "공깃밥이 빠졌다니 많이 속상하시겠어요. 정말 죄송해요.")
        d, _ = run_reply("공깃밥이 빠져 많이 불편하셨을 것 같습니다.", "hamnida")
        self.assert_kept_ai_text(d, "공깃밥이 빠져 많이 불편하셨을 것 같습니다. 정말 죄송합니다.")

    def test_promise_in_ai_part_is_dropped(self):
        """11/21: AI 가 덧붙인 약속 문장은 빼고 공감 문장 + 짧은 사과로 살린다 (예전에는 템플릿으로 갔다)."""
        d, _ = run_reply("공깃밥이 빠졌다니 정말 속상하시겠어요. 다음에는 꼭 챙길게요.", "haeyo")
        self.assertFalse(d.checks["used_fallback"])
        self.assertTrue(d.checks["ai_part_repaired"])
        self.assertIn("공깃밥이 빠졌다니 정말 속상하시겠어요. 진심으로 죄송해요.", d.text)
        self.assertNotIn("챙길게요", d.text.split("앞으로")[0])

    def test_promise_only_still_goes_to_template(self):
        d, _ = run_reply("다음에는 꼭 챙길게요.", "haeyo")
        self.assertTrue(d.checks["used_fallback"])
        self.assertFalse(d.checks["ai_part_repaired"])
        self.assertNotIn("챙길게요", d.text.split("앞으로")[0])

    def test_word_replacement_is_marked_as_repaired(self):
        """사전 치환('이러한' → '이런')도 코드가 AI 글을 바꾼 것이라 ai_part_repaired 로 센다 (공지와 같은 기준)."""
        d, _ = run_reply("이러한 일로 공깃밥이 빠져 있었다니 정말 죄송해요.", "haeyo")
        self.assertFalse(d.checks["used_fallback"])
        self.assertTrue(d.checks["ai_part_repaired"])
        self.assertIn("이런 일로 공깃밥이 빠져 있었다니 정말 죄송해요.", d.text)

    def test_clean_ai_text_is_not_marked(self):
        d, prompts = run_reply("공깃밥이 빠져 있었다니 정말 죄송해요.", "haeyo")
        self.assertEqual(len(prompts), 1)
        self.assertFalse(d.checks["used_fallback"])
        self.assertFalse(d.checks["ai_part_repaired"])
        self.assertIn("ai_part_repaired", OPTIONAL_CHECKS)


class TestFallbackTemplates(unittest.TestCase):
    """③ 코드 템플릿은 조사가 맞고 모든 점검을 넘는다."""

    def test_no_subject_particle_with_transitive_verb(self):
        for register, variants in REPLY_FALLBACK_TMPL.items():
            for tmpl in variants:
                for item in ("계란말이", "공깃밥", "수저와 젓가락"):
                    text = tmpl.format(item=item, particle=josa(item, "이", "가"))
                    with self.subTest(text=text):
                        self.assertIsNone(re.search(r"[이가]\s빠뜨리", text))
                        self.assertTrue(checks.has_apology_anywhere(text))
                        self.assertTrue(checks.ai_part_only_empathy(text))
                        self.assertFalse(checks.has_claimed_action(text))
                        self.assertTrue(checks.style_match(text, "haeyo" if register == "해요체" else "hamnida"))


if __name__ == "__main__":
    unittest.main()
