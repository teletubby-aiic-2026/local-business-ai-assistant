"""C6 전체 카드 실행 — registry.run_card 로 store_ongi 의 카드를 전부 돌린다.

카드 1장 = CardResult 1개. complaint 카드는 reply_draft(답글 3개) + prevention_notice(공지 1개)를
한 번에 실행해 drafts 에 함께 담는다 (registry.run_card). promo 카드는 coupon_promo 하나.
complaint 카드는 조치 후보(MEASURES) 중 첫 번째를 chosen_measures 로 기본 선택한다.

실행 방법
  python -m tests.test_c6_all          (live 만. CLOVA_API_KEY 필요, 없으면 건너뜀)
  python -m tests.test_c6_all --mock   (mock 만. 가짜 CLOVA 응답으로 전체 경로 확인, API 호출 없음)
  두 모드는 같은 파일을 덮어쓰지 않는다.

  --reply-style auto|rotate|haeyo|hamnida|mixed  (기본 auto. live 실행에 쓰임. 자세한 뜻은
                                                   c6.reply.generate_reply_draft 참고)

  python -m tests.test_c6_all --save-best                 (live 결과가 전부 깨끗하면 저장본 덮어씀)
  python -m tests.test_c6_all --save-best --cards complaint  (홍보 카드는 빼고 complaint 만 실행·저장)

결과 (live)
  results/c6_results.md   발표 모드용 보고서 — 맨 위에 "모드: live", 카드별 걸린 시간(초)·요금,
                           이유·근거 표시·선택된 조치, 초안마다 글·근거 ID(내용 포함)·
                           실패 항목(사람 말로)·다시 쓴 횟수
  results/c6_cache.json   CardResult 전체 (발표 모드 캐시는 이 live 결과만 쓴다)

결과 (--mock)
  results/c6_results_mock.md, results/c6_cache_mock.json   위와 같은 내용, mock 전용 파일
"""

import argparse
import json
import os
import sys
import threading
import unittest
from unittest.mock import patch

import config
from shared.contracts import ToneProfile
from shared.sample_scenario import (
    SAMPLE_CARDS, SAMPLE_REVIEWS, SAMPLE_SNAPSHOTS, SAMPLE_STORE, SAMPLE_TONE,
)
from c6 import checks
from c6.contract import build_context
from c6.dummy import OWNER_REPLIES, POLICIES
from c6.measures import MEASURES, REPLY_STYLES, REPLY_STYLE_REGISTER, REPLY_OPENING, M1_SENTENCES, P1_SENTENCES
from c6.registry import run_card, REPLAY_PATH
from c6.output import CardResult
from c6.style import detect_register
from common.korean import display_name


def _parse_cli_flags():
    """이 파일만 아는 --mock/--save-best/--cards 를 먼저 꺼낸다.
    unittest.main 은 이 플래그들을 모르니, 남은 인자(rest)만 넘겨야 한다
    (안 그러면 "unrecognized arguments" 로 죽는다)."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--save-best", action="store_true")
    parser.add_argument("--cards", default=None)
    parser.add_argument("--reply-style", default="auto")
    args, rest = parser.parse_known_args(sys.argv[1:])
    return args.mock, args.save_best, args.cards, args.reply_style, rest


MOCK, SAVE_BEST, CARDS_FILTER, REPLY_STYLE, _UNITTEST_ARGV = _parse_cli_flags()

CTX = build_context(
    store=SAMPLE_STORE,
    reviews=list(SAMPLE_REVIEWS),
    tone=SAMPLE_TONE,
    cards=list(SAMPLE_CARDS),
    snapshots=list(SAMPLE_SNAPSHOTS),
    owner_replies=OWNER_REPLIES,
    policies=POLICIES,
)

REVIEW_MAP = {r.review_id: r for r in CTX.reviews}
POLICY_MAP = {p["policy_id"]: p["text"] for p in CTX.policies}
MEASURE_MAP = {m["id"]: m["text"] for m in MEASURES}
SNAPSHOT_MAP = {s.snapshot_id: s for s in CTX.snapshots}


def _evidence_content(eid):
    """근거 ID -> 사람이 읽는 내용 한 줄."""
    if eid.startswith("F_"):
        rv = REVIEW_MAP.get(eid[2:])
        return rv.text if rv else "(리뷰를 찾을 수 없음)"
    if eid.startswith("coupon:"):
        return f"쿠폰 적용 메뉴: {eid.split(':', 1)[1]}"
    if eid in POLICY_MAP:
        return POLICY_MAP[eid]
    if eid in MEASURE_MAP:
        return MEASURE_MAP[eid]
    if eid in SNAPSHOT_MAP:
        return SNAPSHOT_MAP[eid].metric_name
    return "(내용 확인 불가)"


def run_all_cards(key, model="HCX-005", kinds=None, reply_style=None):
    """registry.run_card 로 store_ongi 의 카드를 실행 -> CardResult 목록 (카드 1장 = 1개).
    kinds 를 주면 그 종류(예: ["complaint"])만 실행한다. 없으면 전부.
    reply_style 을 안 주면 CLI --reply-style 값(기본 auto)을 쓴다."""
    results = []
    for card in CTX.cards:
        if kinds and card.kind not in kinds:
            continue
        chosen = [MEASURES[0]] if card.kind == "complaint" else None
        results.append(run_card(
            CTX, card, key, model=model, chosen_measures=chosen,
            reply_style=reply_style if reply_style is not None else REPLY_STYLE,
        ))
    return results


def _clean_run(results):
    """failed_reasons·needs_input 이 하나도 없으면 True."""
    for r in results:
        for d in r.drafts:
            if d.failed_reasons or d.needs_input:
                return False
    return True


# 다시 쓰기 사유(실패)로 치지 않는 참고용 점검 — False 라도 d.failed_reasons 에는 안 들어간다
# (c6/reply.py _RETRY_EXEMPT, notice.py retry_exempt, services/web/scripts/measure_live.py
# RETRY_EXEMPT 와 같은 목록). used_fallback 은 반대로 True 일 때가 알릴 일이라 따로 표시한다.
_REFERENCE_ONLY_CHECKS = ("length_ok", "uses_opening", "uses_closing", "not_too_similar")
_REFERENCE_LABELS = {"length_ok": "길이", "uses_opening": "시작 인사", "uses_closing": "마무리 인사",
                     "not_too_similar": "비슷함"}


def write_report(results, path, mode):
    lines = ["# C6 전체 카드 실행 결과", "", f"모드: {mode}", "",
             "## 카드별 걸린 시간 · 요금", "",
             "| 카드 | 종류 | 걸린 시간(초) | 요금(원) |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.card_id} | {r.kind} | {r.elapsed_ms / 1000:.1f} | {round(r.won, 2)} |")
    lines.append("")

    for r in results:
        lines.append(f"## {r.card_id} · {r.kind}")
        lines.append(f"- 이유: {r.reason_text}")
        if r.basis_label:
            lines.append(f"- 근거 표시: {r.basis_label}")
        if r.chosen_measures:
            lines.append("- 선택된 조치: " + ", ".join(f"{m['id']}: {m['text']}" for m in r.chosen_measures))
        lines.append(f"- 걸린 시간: {r.elapsed_ms / 1000:.1f}초 · 요금: {round(r.won, 2)}원")
        lines.append("")
        for d in r.drafts:
            title = f"{d.target_review_id} ({d.generator})" if d.target_review_id else d.generator
            lines.append(f"### {title}")
            if d.style:
                lines.append(f"- 말투: {d.style}")
            lines.append(f"- 글: {d.text or '(생성 실패)'}")
            if d.evidence_ids:
                ev = "; ".join(f"{eid} ({_evidence_content(eid)})" for eid in d.evidence_ids)
            else:
                ev = "없음"
            lines.append(f"- 근거: {ev}")
            # 실패 항목은 d.failed_reasons 만 쓴다(= 다시 쓰기 사유였던 것). checks 에서 False 를
            # 직접 긁으면 length_ok·not_too_similar 처럼 참고용인데 "실패"로 잘못 보일 수 있다.
            if d.failed_reasons:
                detail = "; ".join(f"[{title}] {h}" for h in d.failed_reasons)
                lines.append(f"- 실패 항목: {detail}")
            else:
                lines.append("- 실패 항목: 없음")
            ref_keys = [k for k in _REFERENCE_ONLY_CHECKS if d.checks.get(k) is False]
            if ref_keys:
                labels = ", ".join(_REFERENCE_LABELS[k] for k in ref_keys)
                lines.append(f"- 참고: {labels}")
            if d.checks.get("used_fallback"):
                lines.append("- 대체 문장 사용: 예 (공감 부분을 코드 템플릿으로 교체)")
            lines.append(f"- 다시 쓴 횟수: {d.rewrites}")
            if d.needs_input:
                lines.append(f"- ⚠ needs_input: {d.needs_input}")
            lines.append("- 자연스러움: __/5")
            lines.append("")

    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_cache(results, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2), encoding="utf-8",
    )


def save_best(results, path):
    """저장본에 이번에 실행한 카드 종류만 교체하고, 실행하지 않은 다른 카드 종류는 그대로 둔다.

    --cards complaint 처럼 일부 카드만 돌렸을 때(예: promo)가 저장본에서 통째로 사라지는 걸 막는다.
    같은 card_id 는 이번 결과로 덮어쓰고, 저장본에만 있던 card_id 는 그대로 남긴다.
    """
    existing = []
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))

    new_ids = {r.card_id for r in results}
    kept = [d for d in existing if d.get("card_id") not in new_ids]
    merged = kept + [r.to_dict() for r in results]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")


class TestSaveBestMerge(unittest.TestCase):
    """save_best: --cards 로 일부 카드 종류만 돌려도, 저장본에만 있던 다른 카드 종류는 지워지지 않아야 한다."""

    def test_saving_complaint_only_keeps_existing_promo(self):
        import tempfile
        from pathlib import Path

        existing = [
            {"card_id": "card_sample_a", "kind": "complaint", "reason_text": "옛 이유", "drafts": []},
            {"card_id": "card_sample_b", "kind": "promo", "reason_text": "홍보 이유", "drafts": []},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")

            new_complaint = CardResult(
                card_id="card_sample_a", kind="complaint", reason_text="새 이유",
                drafts=[], elapsed_ms=0, won=0.0,
            )
            save_best([new_complaint], path)

            saved = json.loads(path.read_text(encoding="utf-8"))
            kinds = {d["card_id"]: d["kind"] for d in saved}
            # promo(card_sample_b)는 이번에 안 돌렸어도 저장본에 그대로 남아야 한다
            self.assertEqual(kinds, {"card_sample_a": "complaint", "card_sample_b": "promo"})
            updated = next(d for d in saved if d["card_id"] == "card_sample_a")
            self.assertEqual(updated["reason_text"], "새 이유")


class TestNoticeChecksConsistency(unittest.TestCase):
    """공지 점검끼리 서로 반대 요구를 하지 않는지: 합니다체 정상 공지 예시 1개가 모든 점검을 통과해야 한다."""

    def test_well_formed_hamnida_notice_passes_all_checks(self):
        body = (
            "최근 몇몇 주문에서 포장할 때 품목이 하나씩 빠지는 일이 있었습니다.\n"
            "불편을 드려 죄송합니다.\n"
            "오늘부터 포장 마감 전에 주문서와 한 번 더 대조하겠습니다.\n"
            "필요한 점이 있으면 요청사항에 적어 주시기 바랍니다."
        )
        chosen_measures = [MEASURES[0]]  # M1: 포장 마감 전 주문서 대조

        self.assertTrue(checks.has_apology(body), body)
        self.assertTrue(checks.notice_has_start(body, "오늘부터"), body)
        self.assertTrue(checks.notice_not_personal(body), body)
        self.assertTrue(checks.notice_formal(body), body)
        self.assertFalse(checks.has_stiff_words(body), body)
        self.assertFalse(checks.has_overpromise(body), body)
        self.assertFalse(checks.has_claimed_action(body), body)
        self.assertTrue(checks.chosen_measure_included(body, chosen_measures), body)
        self.assertFalse(checks.has_invented_measure(body, chosen_measures), body)
        self.assertTrue(checks.notice_vs_reply(body, None), body)


class TestNoticeFormalFixHintsMock(unittest.TestCase):
    """공지는 합니다체가 기본이라, no_stiff_words 힌트에 '구어체'로 바꾸라는 말이 나오면 안 된다."""

    def test_formal_hint_never_says_colloquial(self):
        hints = checks.fix_hints(["no_stiff_words"], formal=True)
        self.assertTrue(hints)
        for h in hints:
            self.assertNotIn("구어체", h, h)

    def test_non_formal_hint_still_mentions_colloquial(self):
        # 답글(reply)은 formal=False(기본값)로 부르니, 기존 문구가 그대로 남아야 한다
        hints = checks.fix_hints(["no_stiff_words"])
        self.assertIn("구어체", hints[0])


class TestNoticeFallbackTemplateMock(unittest.TestCase):
    """공지도 답글의 used_fallback 과 같은 방식: 두 번 다시 써도 점검을 못 넘으면 코드 템플릿으로
    바꿔 넣고 통과 처리한다."""

    @unittest.skipUnless(MOCK, "--mock 일 때만 실행")
    def test_always_bad_notice_response_falls_back_and_still_passes(self):
        card = next(c for c in CTX.cards if c.kind == "complaint")

        def _always_bad(key, system, messages, model="HCX-005", **kw):
            # 반말·개인정보 섞인, 절대 점검을 못 넘는 공지 본문
            return _ok("야 다들 들어봐 공깃밥 빠진 거 완전 웃기지 않냐 ㅋㅋ")

        with patch("clova.call", side_effect=_always_bad):
            result = run_card(CTX, card, "fake-key", chosen_measures=[MEASURES[0]])

        notice_draft = next(d for d in result.drafts if d.generator == "prevention_notice")
        self.assertTrue(notice_draft.checks["used_fallback"], notice_draft.checks)
        self.assertEqual(notice_draft.rewrites, 2)
        self.assertFalse(notice_draft.failed_reasons, notice_draft.failed_reasons)
        self.assertTrue(notice_draft.checks["notice_formal"], notice_draft.checks)
        self.assertTrue(notice_draft.checks["has_apology"], notice_draft.checks)
        self.assertTrue(notice_draft.checks["notice_has_start"], notice_draft.checks)
        self.assertTrue(notice_draft.checks["chosen_measure_included"], notice_draft.checks)
        # 템플릿은 "주문하신"처럼 손님 한 명을 가리키는 말을 쓰지 않는다
        self.assertNotIn("주문하신", notice_draft.text)
        # "오늘부터" 뒤에 "앞으로"/"다음부터"/"이제부터" 같은 시점 표현이 겹치지 않는다
        for dup in ("오늘부터 앞으로", "오늘부터 다음부터", "오늘부터 이제부터"):
            self.assertNotIn(dup, notice_draft.text, notice_draft.text)
        # 리뷰 3개(공깃밥 / 수저·젓가락 / 계란말이)가 리뷰별 묶음으로, 묶음 안은 '와/과', 묶음끼리는
        # 쉼표로 이어진다 — 하나로 뭉쳐 중복 제거한 평평한 목록이 아니다.
        self.assertIn("공깃밥, 수저와 젓가락, 계란말이", notice_draft.text)


class TestNoticeAiOverlapMock(unittest.TestCase):
    """fallback 템플릿뿐 아니라, AI 가 직접 쓴 공지 본문도 "오늘부터" 뒤에 "앞으로"/"다음부터"/
    "이제부터"가 겹치면 코드가 지운다(c6.notice._dedupe_start_label_line)."""

    @unittest.skipUnless(MOCK, "--mock 일 때만 실행")
    def test_ai_body_with_overlapping_time_phrase_is_deduped(self):
        card = next(c for c in CTX.cards if c.kind == "complaint")
        overlapping_body = (
            "최근 공깃밥, 수저와 젓가락, 계란말이가 빠진 상태로 배달된 일이 있었습니다.\n"
            "불편을 드려 죄송합니다.\n"
            "오늘부터 앞으로 포장 마감 전에 주문서와 한 번 더 대조하겠습니다.\n"
            "이외에도 필요한 게 있으면 요청사항에 적어 주세요."
        )

        def _overlap(key, system, messages, model="HCX-005", **kw):
            return _ok(overlapping_body)

        with patch("clova.call", side_effect=_overlap):
            result = run_card(CTX, card, "fake-key", chosen_measures=[MEASURES[0]])

        notice_draft = next(d for d in result.drafts if d.generator == "prevention_notice")
        # AI 가 쓴 문장을 그대로 살려 썼다(코드 템플릿으로 바뀌지 않았다)
        self.assertFalse(notice_draft.checks["used_fallback"], notice_draft.checks)
        for dup in ("오늘부터 앞으로", "오늘부터 다음부터", "오늘부터 이제부터"):
            self.assertNotIn(dup, notice_draft.text, notice_draft.text)
        self.assertIn("오늘부터 포장 마감 전에", notice_draft.text)


class TestBrokenEndingMock(unittest.TestCase):
    """checks.no_broken_ending: '적어해주세요'처럼 동사 뒤에 '해'가 잘못 붙은 깨진 어미를 잡는다."""

    def test_broken_ending_detected(self):
        self.assertFalse(checks.no_broken_ending("요청사항에 적어해주세요."))
        for bad in ("어해주", "아해주", "해해", "주세주세요"):
            self.assertFalse(checks.no_broken_ending(bad), bad)

    def test_normal_ending_passes(self):
        self.assertTrue(checks.no_broken_ending("요청사항에 적어 주세요."))
        self.assertTrue(checks.no_broken_ending(""))

    def test_fix_hints_suggests_spaced_form(self):
        hints = checks.fix_hints(["no_broken_ending"])
        self.assertIn("적어 주세요", hints[0])


class TestJoinItemGroupsMock(unittest.TestCase):
    """common.korean.join_item_groups: 묶음 안은 와/과, 묶음끼리는 쉼표. 답글·공지 템플릿·
    AI 프롬프트에 넘기는 품목 문자열이 모두 이 함수 하나로 만들어진다."""

    def test_single_group_matches_and_join(self):
        from common.korean import and_join, join_item_groups

        self.assertEqual(join_item_groups([["수저", "젓가락"]]), and_join(["수저", "젓가락"]))
        self.assertEqual(join_item_groups([["공깃밥"]]), "공깃밥")

    def test_multiple_groups_are_joined_by_review_with_commas(self):
        from common.korean import join_item_groups

        self.assertEqual(
            join_item_groups([["공깃밥"], ["수저", "젓가락"], ["계란말이"]]),
            "공깃밥, 수저와 젓가락, 계란말이",
        )
        # 빈 묶음은 건너뛴다
        self.assertEqual(join_item_groups([["공깃밥"], [], ["계란말이"]]), "공깃밥, 계란말이")

    @unittest.skipUnless(MOCK, "--mock 일 때만 실행")
    def test_reply_fact_line_uses_join_item_groups(self):
        from c6.reply import _fact_line
        from common.korean import join_item_groups

        rv = REVIEW_MAP["rv_ongi_002"]  # "수저랑 젓가락이 빠져 있었어요"
        line = _fact_line(rv, list(SAMPLE_STORE.menu))
        self.assertIn(f"missing={join_item_groups([['수저', '젓가락']])}", line)
        self.assertNotIn("missing=수저,젓가락", line)  # 예전 쉼표-only 형식이 아님


# rv_ongi_001·rv_ongi_003 은 품목(공깃밥/계란말이)만 다르고 틀이 같은 공감 문장 — 품목 이름을 지우면
# 글자 그대로 똑같다("이 빠져서 정말 죄송해요."). 재시도해도 모의 응답이 똑같아 그대로 비슷하게 남는다.
_SIMILAR_BODIES = {
    "rv_ongi_001": "공깃밥이 빠져서 정말 죄송해요.",
    "rv_ongi_002": "수저랑 젓가락이 빠져 있었다니 속상하셨겠어요.",
    "rv_ongi_003": "계란말이가 빠져서 정말 죄송해요.",
}


def _mock_clova_similar(key, system, messages, model="HCX-005", **kw):
    content = messages[0]["content"] if messages else ""
    if "## 사실" in system:
        for rid, body in _SIMILAR_BODIES.items():
            if rid in content:
                return _ok(body)
    return {"content": "{}", "won": 0.0, "tokens": 0, "seconds": 0}


class TestNotTooSimilarItemOnlyMock(unittest.TestCase):
    """품목 이름만 다르고 틀이 같은 두 공감 문장은(지우고 비교해도 비슷함) 실패로 세지 않는다."""

    @unittest.skipUnless(MOCK, "--mock 일 때만 실행")
    def test_item_only_difference_is_not_counted_as_failure(self):
        from c6.reply import generate_reply_draft

        card = next(c for c in CTX.cards if c.kind == "complaint")
        with patch("clova.call", side_effect=_mock_clova_similar):
            result = generate_reply_draft(CTX, card, "fake-key", reply_style="haeyo")

        by_review = {d.target_review_id: d for d in result.drafts}
        rv1, rv3 = by_review["rv_ongi_001"], by_review["rv_ongi_003"]

        # 품목을 지우면 틀이 똑같으니 not_too_similar 는 False(비슷함)로 남지만,
        self.assertFalse(rv1.checks["not_too_similar"], rv1.checks)
        self.assertFalse(rv3.checks["not_too_similar"], rv3.checks)
        # 실패·확인 필요로는 치지 않는다
        for d in (rv1, rv3):
            self.assertFalse(d.failed_reasons, d.failed_reasons)
            self.assertFalse(d.needs_input, d.needs_input)
        # 한 번 다시 써 보려고 시도는 한다 (모의 응답은 똑같아서 그대로 비슷하게 남음)
        self.assertGreaterEqual(rv1.rewrites + rv3.rewrites, 1)

        # 결과 md 에는 "실패 항목: 없음"과 "참고: 비슷함"으로 나와야 한다(실패로 보이면 안 된다)
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            write_report([result], path, mode="mock")
            text = path.read_text(encoding="utf-8")
        for rid in ("rv_ongi_001", "rv_ongi_003"):
            start = text.index(f"### {rid} (reply_draft)")
            end = text.find("\n\n", start)
            section = text[start:] if end < 0 else text[start:end]
            self.assertIn("- 실패 항목: 없음", section, section)
            ref_line = next(ln for ln in section.splitlines() if ln.startswith("- 참고:"))
            self.assertIn("비슷함", ref_line, section)


# ── --mock: 가짜 CLOVA 응답. reply.py 는 이제 AI 가 공감·사과만 주고, 조치(M1)·요청사항(P1)·
# 인사·마무리는 코드가 붙인다. reply 는 리뷰 1개당 1콜이라 review_id 로 구분해 서로 다른 본문을 돌려준다.

# 리뷰 순서대로 haeyo(해요체)/hamnida(합니다체)/mixed(공감 해요체) 말투라, 본문도 그 말투에 맞춘다.
REPLY_BODIES = {
    "rv_ongi_001": "주문하신 공깃밥이 빠져서 정말 죄송해요.",  # haeyo
    "rv_ongi_002": "수저랑 젓가락이 빠져서 불편하셨을 텐데 죄송합니다.",  # hamnida
    "rv_ongi_003": "계란말이가 빠져서 아쉬우셨겠어요, 정말 죄송해요.",  # mixed(AI 는 해요체)
}

# notice.py: 본문 4문장, 줄마다 문장(합니다체, 특정 손님 가리키는 말 없음)
NOTICE_BODY = (
    "최근 몇몇 주문에서 포장할 때 공깃밥·수저·계란말이 같은 품목이 하나씩 빠지는 일이 있었습니다.\n"
    "불편을 드려 죄송합니다.\n"
    "오늘부터 포장 마감 전에 주문서와 대조해서 빠지는 품목이 없도록 하겠습니다.\n"
    "이외에도 필요한 게 있으면 요청사항에 적어 주시기 바랍니다."
)

# 처음 2번(동시 생성되는 후보 2개)은 '반값·코드'가 섞인 본문(coupon_invented 로 둘 다 걸려야 함)
# -> 다시 쓰기 1회 -> 3번째 호출은 정상
PROMO_BAD_BODY = "온기한식 제육볶음 정식을 반값 코드로 만나보세요! 알싸한 양념이 매력적인 메뉴예요."
PROMO_GOOD_BODY = (
    "온기한식 제육볶음 정식은 매콤달콤한 양념과 두툼한 건더기가 매력이에요. "
    "뚝배기째 든든하게 즐기실 수 있는 한 상이니 편하게 들러 맛보세요."
)

_reply_calls_seen = []  # 어떤 review_id 로 몇 번 호출됐는지 (스레드 안전하게 lock 으로 보호)
_promo_call_count = {"n": 0}
_mock_lock = threading.Lock()


def _ok(body, won=0.02):
    # 평문 그대로 돌려준다 (JSON 이 아니어도 본문을 버리지 않는지 같이 확인한다)
    return {"content": body, "won": won, "tokens": 100, "seconds": 0.3}


def _mock_clova(key, system, messages, model="HCX-005", **kw):
    content = messages[0]["content"] if messages else ""

    if "## 사실" in system:            # reply.py: 리뷰 1개당 1콜
        for rid, body in REPLY_BODIES.items():
            if rid in content:
                with _mock_lock:
                    _reply_calls_seen.append(rid)
                return _ok(body)
        return {"content": "{}", "won": 0.0, "tokens": 0, "seconds": 0}

    if "공지" in system:                # notice.py
        return _ok(NOTICE_BODY, won=0.03)

    if "쿠폰 홍보글" in system:          # promo.py: 동시에 생성되는 후보 2개는 일부러 틀리게, 다시 쓰기 때 정상
        with _mock_lock:
            _promo_call_count["n"] += 1
            n = _promo_call_count["n"]
        return _ok(PROMO_BAD_BODY if n <= 2 else PROMO_GOOD_BODY, won=0.02)

    return {"content": "{}", "won": 0.0, "tokens": 0, "seconds": 0}


class TestAllCardsMock(unittest.TestCase):
    """--mock 일 때만 실행: 가짜 응답으로 registry 전체 경로를 확인한다."""

    @unittest.skipUnless(MOCK, "--mock 일 때만 실행")
    @patch("clova.call", side_effect=_mock_clova)
    def test_run_all(self, mock_clova):
        _reply_calls_seen.clear()
        _promo_call_count["n"] = 0

        # 이 테스트는 haeyo/hamnida/mixed 3종 회전(rotate)을 보여주는 데모·테스트용이라
        # CLI --reply-style(기본 auto)과 상관없이 rotate 로 고정해 돌린다.
        results = run_all_cards("fake-key", reply_style="rotate")

        # 카드 2장: complaint(card_sample_a, drafts=답글3+공지1) + promo(card_sample_b, drafts=1)
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertIsInstance(r, CardResult)
            self.assertTrue(r.drafts, f"{r.card_id} 초안이 없어요")
            for d in r.drafts:
                self.assertTrue(d.evidence_ids, f"{d.generator}·{d.target_review_id} 근거가 비어 있어요")

        # 리뷰 3개가 3번의 '개별' 호출로 처리됐는지 (배치 1콜이 아니라)
        self.assertEqual(sorted(_reply_calls_seen), ["rv_ongi_001", "rv_ongi_002", "rv_ongi_003"])

        complaint = next(r for r in results if r.kind == "complaint")
        self.assertEqual(complaint.chosen_measures, [MEASURES[0]])
        self.assertEqual(len(complaint.drafts), 4)
        generators = {d.generator for d in complaint.drafts}
        self.assertEqual(generators, {"reply_draft", "prevention_notice"})

        store_display = display_name(SAMPLE_STORE.name)
        reply_drafts = [d for d in complaint.drafts if d.generator == "reply_draft"]

        # 리뷰 순서대로 haeyo/hamnida/mixed 말투가 지정됨
        self.assertEqual(
            {d.target_review_id: d.style for d in reply_drafts},
            {"rv_ongi_001": "haeyo", "rv_ongi_002": "hamnida", "rv_ongi_003": "mixed"},
        )

        review_order = ["rv_ongi_001", "rv_ongi_002", "rv_ongi_003"]
        for d in reply_drafts:
            register = REPLY_STYLE_REGISTER[d.style]
            opening = REPLY_OPENING[d.style].format(store=store_display)
            # 말투별 고정 인사·마무리로 조립 후 통과
            self.assertTrue(d.text.startswith(opening), d.text)
            self.assertTrue(d.text.endswith(f"{store_display} 드림"), d.text)
            self.assertTrue(d.checks["uses_opening"] and d.checks["uses_closing"])
            # 코드가 붙인 M1 조치 문장이 들어 있으니 조치 포함으로 통과
            self.assertTrue(d.checks["chosen_measure_included"], d.checks)
            self.assertTrue(d.checks["ai_part_only_empathy"], d.checks)
            self.assertTrue(d.checks["style_match"], d.checks)
            self.assertIn("M1", d.evidence_ids)
            self.assertIn("P1", d.evidence_ids)
            # 최종 글에 AI 본문(공감·사과)이 그대로 포함됨 (조립에서 버려지지 않음)
            self.assertIn(REPLY_BODIES[d.target_review_id], d.text)
            # 코드가 붙인 말투별 M1·P1 고정 문장(리뷰 순서로 고른 변형)이 들어 있음
            idx = review_order.index(d.target_review_id)
            self.assertIn(M1_SENTENCES[register][idx % len(M1_SENTENCES[register])], d.text)
            self.assertIn(P1_SENTENCES[register][idx % len(P1_SENTENCES[register])], d.text)
            self.assertEqual(d.rewrites, 0)

        # 리뷰 3개의 최종 글이 서로 다름 (복붙이 아니라 리뷰마다 다른 답글)
        self.assertEqual(len({d.text for d in reply_drafts}), 3)

        notice_draft = next(d for d in complaint.drafts if d.generator == "prevention_notice")
        self.assertTrue(notice_draft.checks["chosen_measure_included"])
        self.assertTrue(all(eid != "snap_sample_01" for eid in notice_draft.evidence_ids))
        # 공지는 모두에게 알리는 글 — 제목·시작·마무리는 코드가 조립, 줄바꿈 포함
        # 글에 쓰는 가게 이름은 "(가상)" 괄호 표기를 지운 이름을 쓴다
        self.assertNotIn("(가상)", notice_draft.text)
        self.assertTrue(notice_draft.text.startswith("[안내] 포장 누락 관련\n"), notice_draft.text)
        self.assertIn(f"{store_display}을 찾아 주시는 분들께", notice_draft.text)
        self.assertTrue(notice_draft.text.endswith(f"{store_display} 드림"), notice_draft.text)
        self.assertIn("\n", notice_draft.text)
        self.assertTrue(notice_draft.checks["notice_has_start"], notice_draft.checks)
        self.assertTrue(notice_draft.checks["notice_not_personal"], notice_draft.checks)
        self.assertTrue(notice_draft.checks["notice_formal"], notice_draft.checks)
        self.assertTrue(notice_draft.checks["notice_vs_reply"], notice_draft.checks)
        self.assertEqual(notice_draft.rewrites, 0)

        promo = next(r for r in results if r.kind == "promo")
        self.assertIsNotNone(promo.basis_label)
        self.assertEqual(len(promo.drafts), 1)
        promo_draft = promo.drafts[0]
        self.assertIn("🎟", promo_draft.text)  # 코드가 붙인 쿠폰 값 한 줄
        self.assertEqual(promo_draft.rewrites, 1)  # '반값·코드' -> 다시 쓰기 1회
        self.assertTrue(promo_draft.checks["no_coupon_invented"])
        self.assertTrue(any(eid.startswith("coupon:") for eid in promo_draft.evidence_ids))

        write_report(results, config.RESULTS_DIR / "c6_results_mock.md", mode="mock")
        write_cache(results, config.RESULTS_DIR / "c6_cache_mock.json")
        print(f"\n결과 저장: {config.RESULTS_DIR / 'c6_results_mock.md'}, "
              f"{config.RESULTS_DIR / 'c6_cache_mock.json'}")


class TestMissingItemExtractionMock(unittest.TestCase):
    """_missing_items: 메뉴판 + 구성품 사전(c6.measures.COMPONENT_ITEMS)으로 rv_ongi_001~003
    원문에서 빠진 품목을 뽑는다. 못 찾으면 조사(이/가/을/를) + 빠짐 표현으로 느슨하게 꺼낸다."""

    @unittest.skipUnless(MOCK, "--mock 일 때만 실행")
    def test_extracts_items_from_sample_reviews(self):
        from c6.reply import _missing_items
        from common.korean import and_join

        menu_names = list(SAMPLE_STORE.menu)
        cases = {
            "rv_ongi_001": ["공깃밥"],              # "공깃밥 추가했는데 안 들어 있었어요"
            "rv_ongi_002": ["수저", "젓가락"],        # "수저랑 젓가락이 빠져 있었어요"
            "rv_ongi_003": ["계란말이"],             # "계란말이를 같이 시켰는데 누락됐어요" (메뉴 이름)
        }
        for rid, expected in cases.items():
            text = REVIEW_MAP[rid].text
            self.assertEqual(_missing_items(text, menu_names), expected, text)

        self.assertEqual(and_join(["수저", "젓가락"]), "수저와 젓가락")


class TestAutoReplyStyleMock(unittest.TestCase):
    """reply_style="auto" 판단: ToneProfile 예문의 문장 끝(요/니다) 비율로 haeyo/hamnida 를 고른다."""

    @unittest.skipUnless(MOCK, "--mock 일 때만 실행")
    def test_haeyo_examples_pick_haeyo(self):
        tone = ToneProfile(
            tone_id="tone_test_haeyo", store_id=SAMPLE_STORE.store_id,
            style_description="손님에게 부드럽게 해요체로 말해요.",
            example_sentences=[
                "주문 확인이 늦어서 불편하셨죠, 죄송해요.",
                "다음 주문부터는 포장 전에 한 번 더 확인할게요.",
            ],
        )
        self.assertEqual(detect_register(tone), "haeyo")

    @unittest.skipUnless(MOCK, "--mock 일 때만 실행")
    def test_hamnida_examples_pick_hamnida(self):
        tone = ToneProfile(
            tone_id="tone_test_hamnida", store_id=SAMPLE_STORE.store_id,
            style_description="손님에게 정중하게 합니다체로 안내합니다.",
            example_sentences=[
                "주문 확인이 늦어 불편을 드려 죄송합니다.",
                "다음 주문부터는 포장 전에 한 번 더 확인하겠습니다.",
            ],
        )
        self.assertEqual(detect_register(tone), "hamnida")


# AI 는 이제 공감·사과만 쓰므로, 두 본문 모두 조치·요청사항 표현은 없어야 한다(안 그러면
# reply_ai_body_clean 에 걸려 claimed_action 과 상관없는 이유로 재작성된다).
CLAIMED_ACTION_BODY = "주문하신 공깃밥이 빠져서 정말 죄송해요. 깜빡하고 빠뜨린 공깃밥은 추가로 보내드렸어요."
CLAIMED_ACTION_FIXED_BODY = "주문하신 공깃밥이 빠져서 정말 죄송해요. 깜빡하고 빠뜨려서 많이 속상하셨겠어요."

_claimed_action_calls = {"n": 0}


def _mock_clova_claimed_action(key, system, messages, model="HCX-005", **kw):
    content = messages[0]["content"] if messages else ""
    if "rv_ongi_001" in content:
        with _mock_lock:
            _claimed_action_calls["n"] += 1
            n = _claimed_action_calls["n"]
        return _ok(CLAIMED_ACTION_BODY if n == 1 else CLAIMED_ACTION_FIXED_BODY)
    for rid, body in REPLY_BODIES.items():
        if rid in content:
            return _ok(body)
    return {"content": "{}", "won": 0.0, "tokens": 0, "seconds": 0}


class TestClaimedActionMock(unittest.TestCase):
    """"보내드렸어요"처럼 하지 않은 조치를 한 것처럼 말하면 걸러지고 다시 써야 한다."""

    @unittest.skipUnless(MOCK, "--mock 일 때만 실행")
    def test_claimed_action_rejected_and_rewritten(self):
        from c6 import checks

        # 점검 함수 자체: 과거형("보내드렸어요")은 걸리고, 정책 P1 의 미래형("챙겨 드릴게요")은 통과한다
        self.assertTrue(checks.has_claimed_action(CLAIMED_ACTION_BODY))
        self.assertFalse(checks.has_claimed_action(CLAIMED_ACTION_FIXED_BODY))

        _claimed_action_calls["n"] = 0
        card = next(c for c in CTX.cards if c.kind == "complaint")
        with patch("clova.call", side_effect=_mock_clova_claimed_action):
            result = run_card(CTX, card, "fake-key", chosen_measures=[MEASURES[0]])

        draft = next(d for d in result.drafts
                     if d.generator == "reply_draft" and d.target_review_id == "rv_ongi_001")
        self.assertEqual(draft.rewrites, 1)
        self.assertTrue(draft.checks["no_claimed_action"], draft.checks)
        self.assertNotIn("보내드렸어요", draft.text)
        self.assertFalse(draft.failed_reasons, draft.failed_reasons)


PROMISE_BODY = "계란말이가 빠졌다니 속상하시겠어요. 다음에는 꼭 챙겨드릴게요."
PROMISE_FIXED_BODY = "계란말이가 빠져서 아쉬우셨겠어요, 정말 죄송해요."

_promise_calls = {"n": 0}


def _mock_clova_promise(key, system, messages, model="HCX-005", **kw):
    content = messages[0]["content"] if messages else ""
    if "rv_ongi_003" in content:
        with _mock_lock:
            _promise_calls["n"] += 1
            n = _promise_calls["n"]
        return _ok(PROMISE_BODY if n == 1 else PROMISE_FIXED_BODY)
    for rid, body in REPLY_BODIES.items():
        if rid in content:
            return _ok(body)
    return {"content": "{}", "won": 0.0, "tokens": 0, "seconds": 0}


class TestPromiseEmpathyMock(unittest.TestCase):
    """AI 부분에 '챙겨드릴게요'처럼 약속형 문장이 들어가면 걸러지고 다시 써야 한다."""

    @unittest.skipUnless(MOCK, "--mock 일 때만 실행")
    def test_promise_rejected_and_rewritten(self):
        self.assertFalse(checks.ai_part_only_empathy(PROMISE_BODY))
        self.assertTrue(checks.ai_part_only_empathy(PROMISE_FIXED_BODY))
        for bad in ("챙길게요.", "다음에는 잘 드릴게요.", "꼭 드리겠습니다."):
            self.assertFalse(checks.ai_part_only_empathy(bad), bad)

        _promise_calls["n"] = 0
        card = next(c for c in CTX.cards if c.kind == "complaint")
        with patch("clova.call", side_effect=_mock_clova_promise):
            result = run_card(CTX, card, "fake-key", chosen_measures=[MEASURES[0]], reply_style="auto")

        draft = next(d for d in result.drafts
                     if d.generator == "reply_draft" and d.target_review_id == "rv_ongi_003")
        self.assertEqual(draft.rewrites, 1)
        self.assertTrue(draft.checks["ai_part_only_empathy"], draft.checks)
        self.assertNotIn("챙겨드릴게요", draft.text)
        self.assertFalse(draft.failed_reasons, draft.failed_reasons)


class TestAllCardsLive(unittest.TestCase):
    """기본(인자 없음)일 때만 실행: 실제 CLOVA 호출로 store_ongi 의 카드를 전부 돌린다."""

    @unittest.skipUnless(
        os.environ.get("CLOVA_API_KEY") and not MOCK,
        "live test: CLOVA_API_KEY 필요, --mock 시 건너뜀",
    )
    def test_run_all_live(self):
        key = os.environ["CLOVA_API_KEY"]
        kinds = [CARDS_FILTER] if CARDS_FILTER else None
        results = run_all_cards(key, kinds=kinds)

        if kinds is None:
            self.assertEqual(len(results), 2)
        for r in results:
            self.assertIsInstance(r, CardResult)

        write_report(results, config.RESULTS_DIR / "c6_results.md", mode="live")
        write_cache(results, config.RESULTS_DIR / "c6_cache.json")
        print(f"\n결과 저장: {config.RESULTS_DIR / 'c6_results.md'}, "
              f"{config.RESULTS_DIR / 'c6_cache.json'}")

        if SAVE_BEST:
            if _clean_run(results):
                save_best(results, REPLAY_PATH)
                print(f"저장본 갱신: {REPLAY_PATH}")
            else:
                reasons = sorted({
                    reason
                    for r in results for d in r.drafts
                    for reason in (d.failed_reasons or (["needs_input"] if d.needs_input else []))
                })
                print(f"저장 안 함: failed_reasons/needs_input 있음 ({', '.join(reasons) or '있음'})")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + _UNITTEST_ARGV, verbosity=2)
