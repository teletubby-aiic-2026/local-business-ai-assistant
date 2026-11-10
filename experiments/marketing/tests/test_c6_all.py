"""C6 전체 카드 실행 — registry.run_card 로 store_ongi 의 카드를 전부 돌린다.

카드 1장 = CardResult 1개. complaint 카드는 reply_draft(답글 3개) + prevention_notice(공지 1개)를
한 번에 실행해 drafts 에 함께 담는다 (registry.run_card). promo 카드는 coupon_promo 하나.
complaint 카드는 조치 후보(MEASURES) 중 첫 번째를 chosen_measures 로 기본 선택한다.

실행 방법
  python -m tests.test_c6_all          (live 만. CLOVA_API_KEY 필요, 없으면 건너뜀)
  python -m tests.test_c6_all --mock   (mock 만. 가짜 CLOVA 응답으로 전체 경로 확인, API 호출 없음)
  두 모드는 같은 파일을 덮어쓰지 않는다.

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
from shared.sample_scenario import (
    SAMPLE_CARDS, SAMPLE_REVIEWS, SAMPLE_SNAPSHOTS, SAMPLE_STORE, SAMPLE_TONE,
)
from c6.contract import build_context
from c6.dummy import OWNER_REPLIES, POLICIES
from c6.measures import MEASURES, REPLY_STYLES, REPLY_STYLE_REGISTER, REPLY_OPENING, M1_SENTENCES, P1_SENTENCES
from c6.registry import run_card, REPLAY_PATH
from c6.output import CardResult
from common.korean import display_name


def _parse_cli_flags():
    """이 파일만 아는 --mock/--save-best/--cards 를 먼저 꺼낸다.
    unittest.main 은 이 플래그들을 모르니, 남은 인자(rest)만 넘겨야 한다
    (안 그러면 "unrecognized arguments" 로 죽는다)."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--save-best", action="store_true")
    parser.add_argument("--cards", default=None)
    args, rest = parser.parse_known_args(sys.argv[1:])
    return args.mock, args.save_best, args.cards, rest


MOCK, SAVE_BEST, CARDS_FILTER, _UNITTEST_ARGV = _parse_cli_flags()

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


def run_all_cards(key, model="HCX-005", kinds=None):
    """registry.run_card 로 store_ongi 의 카드를 실행 -> CardResult 목록 (카드 1장 = 1개).
    kinds 를 주면 그 종류(예: ["complaint"])만 실행한다. 없으면 전부."""
    results = []
    for card in CTX.cards:
        if kinds and card.kind not in kinds:
            continue
        chosen = [MEASURES[0]] if card.kind == "complaint" else None
        results.append(run_card(CTX, card, key, model=model, chosen_measures=chosen))
    return results


def _clean_run(results):
    """failed_reasons·needs_input 이 하나도 없으면 True."""
    for r in results:
        for d in r.drafts:
            if d.failed_reasons or d.needs_input:
                return False
    return True


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
            lines.append("- 실패 항목: " + ("; ".join(d.failed_reasons) if d.failed_reasons else "없음"))
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

        results = run_all_cards("fake-key")

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
            # 코드가 붙인 말투별 M1·P1 고정 문장이 들어 있음
            self.assertIn(M1_SENTENCES[register], d.text)
            self.assertIn(P1_SENTENCES[register], d.text)
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
                write_cache(results, REPLAY_PATH)
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
