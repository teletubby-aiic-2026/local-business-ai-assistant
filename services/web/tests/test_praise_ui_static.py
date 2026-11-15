"""카드 ⓑ 의 손님 칭찬 근거(evidence type "praise")를 화면이 어떻게 그리는지, app.js 를 글자로 읽어 확인하는 정적 시험.
서버·브라우저를 띄우지 않는다.

지키는 것
- 근거 종류를 이름으로 가린다 (review · snapshot · praise). '리뷰가 아니면 모두 지표'로 다루면 새 종류가 지표 자리에 잘못 나온다.
- 카드의 '근거:' 한 줄(sourceLine)에 칭찬 리뷰 건수, '근거 보기' 칩(evidenceChip)에 "칭찬 리뷰 rv_…: “…”".
- 홍보글 초안의 근거(sourceBlock)는 '근거 지표'와 '손님 칭찬 리뷰' 두 덩어리를 모두 보여 준다.
- 리뷰 글·리뷰 id·메뉴 이름은 esc() 를 거친다 (붙여넣은 리뷰는 사용자 입력).

실행 (services/web 에서): PYTHONPATH=<저장소 루트>:. python -m pytest -q tests/test_praise_ui_static.py
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "web" / "static"
JS = (STATIC / "app.js").read_text(encoding="utf-8")


def function(name: str) -> str:
    """app.js 의 최상위 함수 하나 (다음 최상위 선언 앞까지)."""
    m = re.search(rf"^function {name}\(.*?(?=^(?:async function|function|const|let|//) )", JS, re.S | re.M)
    assert m, name
    return m.group(0)


def code(js: str) -> str:
    return re.sub(r"//[^\n]*", "", js)       # 주석 속 설명 글자는 빼고 본다


class EvidenceKinds(unittest.TestCase):
    def test_kinds_are_told_apart_by_name(self):
        self.assertNotIn('e.type !== "review"', JS)                 # 새 종류가 지표 자리에 끼지 않게
        for name in ("sourceLine", "sourceBlock"):
            with self.subTest(name):
                self.assertIn('e.type === "snapshot"', function(name))
        self.assertIn('e.type === "praise"', function("praiseOf"))

    def test_source_line_adds_the_praise_count(self):
        js = code(function("sourceLine"))
        self.assertIn("리뷰 ${reviews.length}건 · 합성 데이터", js)   # 불만 카드의 줄은 그대로
        self.assertIn("snaps.forEach((e) => parts.push(shortBasis(e.basis)))", js)
        self.assertRegex(js, r"손님 칭찬 리뷰 \$\{praiseOf\(p\)\.total\}건")

    def test_praise_count_is_every_review_that_mentions_the_menu(self):
        """근거로 보여 주는 리뷰는 3건까지지만, 건수는 그 메뉴를 언급한 칭찬 리뷰 전부(card.review_ids)로 센다."""
        js = code(function("praiseOf"))
        self.assertIn("p.card.review_ids", js)
        self.assertIn("shown[0].menu", js)

    def test_chip_shows_praise_like_a_review(self):
        js = code(function("evidenceChip"))
        self.assertIn("칭찬 리뷰 ${esc(e.id)}: “${esc(e.text)}”", js)
        self.assertIn("리뷰 ${esc(e.id)}: “${esc(e.text)}”", js)      # 불만 리뷰 칩은 그대로
        self.assertIn("p.evidence.map(evidenceChip)", function("renderCards"))

    def test_only_the_snapshot_chip_has_the_basis_and_source_link(self):
        js = code(function("evidenceChip"))
        last = js[js.rindex(": `"):]                                 # 세 갈래 중 마지막(지표)
        self.assertIn("shortBasis(e.basis)", last)
        self.assertIn('target="_blank" rel="noopener"', last)
        self.assertEqual(js.count("shortBasis(e.basis)"), 1)
        self.assertEqual(js.count("원본"), 1)


class DraftSource(unittest.TestCase):
    def test_promo_draft_shows_both_the_metric_and_the_praise_reviews(self):
        js = code(function("sourceBlock"))
        self.assertIn("근거 지표", js)
        self.assertIn("손님 칭찬 리뷰", js)
        self.assertNotIn("if (snaps.length) return", js)             # 지표만 보여 주고 끝내지 않는다
        tail = js[js.index("const snaps"):]
        self.assertRegex(tail, r"return \(snaps\.length \?[\s\S]+\+ \(praised\.length \?")
        self.assertIn("praised.map(reviewItem)", tail)

    def test_complaint_draft_source_is_unchanged(self):
        js = code(function("sourceBlock"))
        self.assertIn('if (target) return `<div class="rv"><p class="rv-title">손님 리뷰</p><ul class="rv-list">${reviewItem(target)}</ul></div>`;', js)
        self.assertIn('if (reviews.length) return `<div class="rv"><p class="rv-title">근거 리뷰 ${reviews.length}건</p>', js)
        self.assertLess(js.index("if (reviews.length) return"), js.index("const snaps"))

    def test_user_text_goes_through_esc(self):
        block = code(function("sourceBlock"))
        self.assertIn("${esc(praise.menu)}", block)
        self.assertNotRegex(block, r"\$\{(?:e\.text|e\.id|e\.menu|praise\.menu)\}")
        chip = code(function("evidenceChip"))
        self.assertNotRegex(chip, r"\$\{(?:e\.text|e\.id|e\.menu|e\.note|e\.basis)\}")
        self.assertIn("${esc(r.text)}", function("reviewItem"))      # 칭찬 리뷰도 이 함수로 그린다


class TodoLine(unittest.TestCase):
    def test_promo_todo_names_the_praised_menu(self):
        js = code(function("todosOf"))
        self.assertIn("praiseOf(mkt).menu", js)
        self.assertIn("손님이 칭찬한 ${menu} 쿠폰으로", js)
        self.assertIn("저녁 손님 다시 부르기", js)                     # 칭찬 근거가 없으면 예전 문구
        self.assertIn("${esc(t.sub)}", function("renderDash"))      # 메뉴 이름이 든 부제도 esc() 를 거친다


if __name__ == "__main__":
    unittest.main()
