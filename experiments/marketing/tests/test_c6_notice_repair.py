"""재발 방지 공지 템플릿 쏠림 고침 (11/15) — 가짜 응답, 네트워크 없음.

11/15 실시간 HCX-005 8번 중 5번이 코드 템플릿이었다. 원인은
① has_apology 가 '죄송'만 보아 '사과드립니다'·'사과의 말씀'·'송구'가 걸림
② no_stiff_words 가 공지에 자연스러운 '여러분'·'과정에서'까지 걸고, 힌트가 어떤 말이 걸렸는지 안 알려 줌
③ 자동 치환이 '기재해 주시면' → '적어해 주시면'(깨진 어미)을 만들어 다시 걸림
고친 것: 사과 표현 넓히기, 공지 허용 말, 걸린 말·구절을 힌트에 적기, 합니다체 치환(formal), '기재' 꼴별 치환,
재시도 뒤 사과 빠짐·해요체 어미만 남으면 코드 보정(ai_part_repaired).

실행 (experiments/marketing 에서):
  python -m pytest -q tests/test_c6_notice_repair.py      또는      python -m tests.test_c6_notice_repair
리뷰·공지 문장은 모두 이 시험을 위해 지어낸 합성 문장이다 (데모 가게 온기한식).
"""

import unittest
from unittest.mock import patch

from shared.sample_scenario import SAMPLE_CARDS, SAMPLE_REVIEWS, SAMPLE_SNAPSHOTS, SAMPLE_STORE, SAMPLE_TONE

from c6 import checks
from c6.contract import build_context
from c6.dummy import OWNER_REPLIES, POLICIES
from c6.measures import MEASURES
from c6.notice import NOTICE_APOLOGY_LINE, _repair_notice_body, generate_prevention_notice

CTX = build_context(store=SAMPLE_STORE, reviews=list(SAMPLE_REVIEWS), tone=SAMPLE_TONE, cards=list(SAMPLE_CARDS),
                    snapshots=list(SAMPLE_SNAPSHOTS), owner_replies=OWNER_REPLIES, policies=POLICIES)
CARD = next(c for c in SAMPLE_CARDS if c.kind == "complaint")
TARGETS = [r for r in SAMPLE_REVIEWS if r.review_id in CARD.review_ids]

LINE1 = "최근 공깃밥, 수저, 계란말이가 빠진 상태로 배달된 일이 있었습니다."
LINE3 = "오늘부터 포장 마감 전에 주문서와 한 번 더 대조하겠습니다."
LINE4 = "이외에도 필요한 게 있으면 요청사항에 적어 주세요."


def run_notice(answer):
    """HCX 가 늘 같은 본문(answer)을 준다고 치고 공지를 만든다. (초안, 받은 메시지 목록)"""
    seen = []

    def fake(key, system, messages, **kw):
        seen.append(messages)
        return {"content": answer, "won": 0.01}

    with patch("clova.call", side_effect=fake):
        d = generate_prevention_notice(CTX, CARD, "k", chosen_measures=[MEASURES[0]]).drafts[0]
    return d, seen


def body_lines(d):
    """조립된 공지에서 코드가 붙인 제목·시작·마무리 줄을 뺀 본문 줄."""
    return d.text.splitlines()[2:-1]


class TestPoliteApologyCounts(unittest.TestCase):
    """① 정중한 사과 표현도 사과로 본다 (처음 두 문장 안에서)."""

    def test_polite_apologies(self):
        for second in ("불편을 드린 점 진심으로 사과드립니다.", "고객 여러분께 사과의 말씀 드립니다.", "깊이 사과를 드립니다.",
                       "너무나 송구스럽습니다.", "모두 저희의 불찰입니다.", "면목이 없습니다.", "불편을 드려 죄송합니다."):
            with self.subTest(second=second):
                self.assertTrue(checks.has_apology(f"{LINE1}\n{second}\n{LINE3}"))

    def test_not_apologies(self):
        for second in ("새로 나온 사과 주스도 많이 찾아 주세요.", "많이 실망하셨을 것 같아 안타깝습니다.", "앞으로 더 신경 쓰겠습니다."):
            with self.subTest(second=second):
                self.assertFalse(checks.has_apology(f"{LINE1}\n{second}"))

    def test_still_only_the_first_two_sentences(self):
        self.assertFalse(checks.has_apology(f"{LINE1}\n{LINE3}\n불편을 드린 점 사과드립니다."))

    def test_notice_with_sagwa_passes_first_time(self):
        d, seen = run_notice(f"{LINE1}\n불편을 드린 점 진심으로 사과드립니다.\n{LINE3}\n{LINE4}")
        self.assertEqual(len(seen), 1)
        self.assertEqual((d.rewrites, d.checks["used_fallback"], d.checks["ai_part_repaired"]), (0, False, False))
        self.assertIn("진심으로 사과드립니다.", d.text)


class TestStiffWordsInNotices(unittest.TestCase):
    """② 공지에 자연스러운 말은 허용, 걸린 말은 힌트에 적기, 합니다체 치환과 '기재' 꼴별 치환."""

    def test_notice_allowed_words(self):
        body = f"최근 배달 과정에서 품목이 빠지는 일이 있었습니다.\n고객 여러분께 불편을 드려 죄송합니다.\n{LINE3}"
        self.assertTrue(checks.has_stiff_words(body))                                         # 홍보글·답글 기준으로는 걸림
        self.assertFalse(checks.has_stiff_words(body, allow=checks.NOTICE_ALLOWED_STIFF))     # 공지는 허용
        d, seen = run_notice(f"{body}\n{LINE4}")
        self.assertEqual(len(seen), 1)
        self.assertFalse(d.checks["used_fallback"])

    def test_formal_replacements_keep_hamnida(self):
        self.assertEqual(checks.fix_stiff_words("불편을 드려 진심으로 사과드리며 더 살피겠습니다.", formal=True),
                         "불편을 드려 진심으로 죄송하며 더 살피겠습니다.")
        self.assertEqual(checks.fix_stiff_words("앞으로 최선을 다할 예정입니다.", formal=True), "앞으로 더 신경 쓰겠습니다.")
        self.assertEqual(checks.fix_stiff_words("최선을 다할 예정이니 지켜봐 주세요.", formal=True),
                         "더 신경 쓸 예정이니 지켜봐 주세요.")
        # 답글(해요체)은 예전 사전 그대로
        self.assertEqual(checks.fix_stiff_words("진심으로 사과드리며"), "정말 죄송해요")
        for text in ("진심으로 사과드리며 살피겠습니다.", "최선을 다할 예정입니다."):
            self.assertNotIn("요", checks.fix_stiff_words(text, formal=True))

    def test_gijae_forms_do_not_break_endings(self):
        cases = {
            "요청사항에 기재해 주시면 챙기겠습니다.": "요청사항에 적어 주시면 챙기겠습니다.",
            "요청사항에 기재해주세요.": "요청사항에 적어 주세요.",
            "요청사항에 기재 부탁드립니다.": "요청사항에 적어 주시기 바랍니다.",
            "요청사항에 기재하여 주시기 바랍니다.": "요청사항에 적어 주시기 바랍니다.",
            "요청사항에 기재하시면 챙기겠습니다.": "요청사항에 적으시면 챙기겠습니다.",
        }
        for before, after in cases.items():
            with self.subTest(before=before):
                fixed = checks.fix_stiff_words(before, formal=True)
                self.assertEqual(fixed, after)
                self.assertTrue(checks.no_broken_ending(fixed))
                self.assertFalse(checks.has_stiff_words(fixed))
        # 표에 없는 꼴은 바꾸지 않는다 (틀린 문장을 만들지 않고 점검이 계속 걸리게)
        self.assertEqual(checks.fix_stiff_words("기재란을 확인합니다."), "기재란을 확인합니다.")

    def test_hint_names_the_words(self):
        body = f"{LINE1}\n이러한 일로 불편을 드려 죄송합니다.\n{LINE3}\n필요한 것은 요청사항에 기재해 주시면 챙기겠습니다."
        hint = checks.stiff_words_hint(body, allow=checks.NOTICE_ALLOWED_STIFF, formal=True)
        self.assertIn("'이러한' → 이런", hint)
        self.assertIn("'기재' → 적어 주세요", hint)
        self.assertEqual(checks.stiff_words_hint(LINE1), "")

    def test_fixable_stiff_words_are_replaced_without_a_rewrite(self):
        """사전으로 고칠 수 있는 말만 걸렸으면 다시 쓰기를 부르지 않고 바로 바꾼다 (다시 쓰면 '오늘부터' 줄을 잃곤 했다).
        코드가 바꾼 글이라 'AI 글 + 코드 보정'으로 표시한다."""
        body = f"{LINE1}\n이러한 일로 불편을 드려 죄송합니다.\n{LINE3}\n필요한 것은 요청사항에 기재해 주시면 챙기겠습니다."
        d, seen = run_notice(body)
        self.assertEqual(len(seen), 1)
        self.assertEqual((d.rewrites, d.checks["used_fallback"], d.checks["ai_part_repaired"]), (0, False, True))
        self.assertEqual(body_lines(d), [LINE1, "이런 일로 불편을 드려 죄송합니다.", LINE3,
                                         "필요한 것은 요청사항에 적어 주시면 챙기겠습니다."])
        self.assertEqual(d.failed_reasons, [])

    def test_unfixable_stiff_word_is_rewritten_with_the_words_named(self):
        body = (f"{LINE1}\n이러한 일로 불편을 드려 죄송합니다.\n{LINE3}\n"
                "만족을 최우선으로 여기며 요청사항에 기재해 주시면 챙기겠습니다.")
        d, seen = run_notice(body)
        self.assertEqual(len(seen), 3)                                    # '만족을 최우선으로'는 사전에 바꿀 말이 없어 다시 쓰기
        retry = seen[1][-1]["content"]
        for word in ("'이러한'", "'기재'", "'만족을 최우선으로'"):
            self.assertIn(word, retry)
        self.assertIn("'오늘부터'로 시작하는 조치 문장", retry)             # 지적한 곳만 고치고 나머지는 두라고 함
        self.assertTrue(d.checks["used_fallback"])                        # 끝까지 못 고치면 예전처럼 템플릿
        self.assertEqual(d.failed_reasons, [])


class TestQuoteHint(unittest.TestCase):
    def test_quoted_phrase_is_named(self):
        review = TARGETS[0].text
        body = f"최근 '{review[:12]}' 같은 일이 있었습니다.\n불편을 드려 죄송합니다.\n{LINE3}\n{LINE4}"
        self.assertTrue(checks.quotes_review(body, TARGETS))
        self.assertEqual(checks.quoted_chunks(body, TARGETS), [review[:12]])   # 겹치는 8자 구절을 이어 붙여 하나로
        hint = checks.quote_hint(body, TARGETS)
        self.assertIn(f"'{review[:12]}'", hint)
        d, seen = run_notice(body)
        self.assertIn(f"'{review[:12]}'", seen[1][-1]["content"])
        self.assertEqual(checks.quote_hint(LINE1, TARGETS), "")


class TestNoticeRepair(unittest.TestCase):
    """③ 재시도 뒤 사과 빠짐·해요체 어미만 남으면 템플릿 대신 AI 본문을 살린다."""

    def test_missing_apology_gets_the_apology_line(self):
        d, seen = run_notice(f"{LINE1}\n{LINE3}\n{LINE4}")
        self.assertEqual(len(seen), 3)
        self.assertEqual((d.checks["used_fallback"], d.checks["ai_part_repaired"]), (False, True))
        self.assertEqual(body_lines(d), [LINE1, NOTICE_APOLOGY_LINE, LINE3, LINE4])
        self.assertEqual(d.failed_reasons, [])

    def test_later_apology_moves_up_instead_of_doubling(self):
        later = "다시 한번 불편을 드린 점 사과드립니다."
        fixed = _repair_notice_body(f"{LINE1}\n{LINE3}\n{later}\n{LINE4}", ["has_apology"])
        self.assertEqual(fixed.splitlines(), [LINE1, later, LINE3, LINE4])

    def test_haeyo_endings_become_hamnida(self):
        haeyo = ("최근 공깃밥, 수저, 계란말이가 빠진 상태로 배달된 일이 있었어요.\n불편을 드려 죄송해요.\n"
                 "오늘부터 포장 마감 전에 주문서와 한 번 더 대조할게요.\n" + LINE4)
        d, seen = run_notice(haeyo)
        self.assertEqual(len(seen), 3)
        self.assertEqual((d.checks["used_fallback"], d.checks["ai_part_repaired"]), (False, True))
        self.assertEqual(body_lines(d), [LINE1, "불편을 드려 죄송합니다.", LINE3, LINE4])
        self.assertTrue(d.checks["notice_formal"])

    def test_to_formal_endings_table(self):
        self.assertEqual(checks.to_formal_endings("꼭 챙길게요.\n더 신경 쓸게요!\n문제예요\n바로 드려요."),
                         "꼭 챙기겠습니다.\n더 신경 쓰겠습니다!\n문제입니다\n바로 드립니다.")
        self.assertEqual(checks.to_formal_endings("새로 만들게요."), "새로 만들게요.")    # 표에 없는 꼴은 그대로
        self.assertEqual(checks.to_formal_endings(LINE4), LINE4)                        # '-세요'는 공지에서도 씀

    def test_missing_start_label_is_restored(self):
        """다시 쓴 글이 '오늘부터' 대신 '앞으로는'으로 조치 줄을 쓰면 그 말만 '오늘부터'로 바꾼다."""
        later = "앞으로는 포장 마감 전에 주문서와 한 번 더 대조하겠습니다."
        d, seen = run_notice(f"{LINE1}\n불편을 드려 죄송합니다.\n{later}\n{LINE4}")
        self.assertEqual(len(seen), 3)
        self.assertEqual((d.checks["used_fallback"], d.checks["ai_part_repaired"]), (False, True))
        self.assertEqual(body_lines(d), [LINE1, "불편을 드려 죄송합니다.", LINE3, LINE4])

    def test_start_label_is_not_glued_to_apeurodo(self):
        body = f"{LINE1}\n불편을 드려 죄송합니다.\n앞으로도 많은 관심 부탁드립니다.\n포장 마감 전에 주문서와 한 번 더 대조하겠습니다."
        fixed = _repair_notice_body(body, ["notice_has_start"], "오늘부터", [MEASURES[0]])
        self.assertIn("앞으로도 많은 관심 부탁드립니다.", fixed)                  # '앞으로도'는 시점 말이 아님
        self.assertIn("오늘부터 포장 마감 전에 주문서와 한 번 더 대조하겠습니다.", fixed)   # 조치 줄 앞에 붙임

    def test_other_faults_still_go_to_template(self):
        d, _ = run_notice(f"{LINE1}\n고객님께서 주문하신 음식이 늦어 실망하셨을 것 같습니다.\n{LINE3}\n{LINE4}")
        self.assertTrue(d.checks["used_fallback"])
        self.assertFalse(d.checks["ai_part_repaired"])
        self.assertNotIn("고객님", d.text)
        self.assertEqual(d.failed_reasons, [])

    def test_slang_line_is_never_kept_by_a_repair(self):
        """PR #54 회귀 (11/15 --mock 시험에서 발견): 반말·장난 한 줄짜리 AI 글에 코드가 사과 줄·조치 줄을 더하면
        notice_formal(다수결)을 넘어 그 줄이 그대로 나갔다. 코드 보정한 공지는 모든 줄이 공지 말투여야 쓴다 → 템플릿."""
        d, _ = run_notice("야 다들 들어봐 공깃밥 빠진 거 완전 웃기지 않냐 ㅋㅋ")
        self.assertTrue(d.checks["used_fallback"], d.text)
        self.assertFalse(d.checks["ai_part_repaired"])
        self.assertNotIn("ㅋㅋ", d.text)
        self.assertEqual(d.failed_reasons, [])
        self.assertTrue(checks.notice_lines_all_formal(f"{LINE1}\n{LINE3}\n{LINE4}"))
        self.assertFalse(checks.notice_lines_all_formal(f"{LINE1}\n공깃밥 빠진 거 웃기지 않냐 ㅋㅋ\n{LINE3}"))

    def test_clean_notice_is_not_marked(self):
        d, seen = run_notice(f"{LINE1}\n불편을 드려 죄송합니다.\n{LINE3}\n{LINE4}")
        self.assertEqual(len(seen), 1)
        self.assertEqual((d.checks["used_fallback"], d.checks["ai_part_repaired"]), (False, False))


if __name__ == "__main__":
    unittest.main()
