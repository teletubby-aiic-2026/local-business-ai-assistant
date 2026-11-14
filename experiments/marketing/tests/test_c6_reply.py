"""C6 답글·공지·홍보 생성 검증 — --mock: 가짜 CLOVA 응답으로 전체 경로 확인."""

import json
import os
import sys
import unittest
from unittest.mock import patch

import config
from shared.sample_scenario import (
    SAMPLE_CARDS, SAMPLE_REVIEWS, SAMPLE_SNAPSHOTS, SAMPLE_STORE, SAMPLE_TONE,
)
from c6.contract import build_context
from c6.measures import MEASURES
from c6.reply import generate_reply_draft, _robust_parse, _normalize_replies
from c6.notice import generate_prevention_notice
from c6.promo import generate_coupon_promo
from c6.registry import CARD_GENERATORS
from c6.output import DraftOutput, CardResult
from c6.dummy import OWNER_REPLIES, POLICIES

CTX = build_context(
    store=SAMPLE_STORE,
    reviews=list(SAMPLE_REVIEWS),
    tone=SAMPLE_TONE,
    cards=list(SAMPLE_CARDS),
    snapshots=list(SAMPLE_SNAPSHOTS),
    owner_replies=OWNER_REPLIES,
    policies=POLICIES,
)
COMPLAINT_CARD = next(c for c in SAMPLE_CARDS if c.kind == "complaint")
PROMO_CARD = next(c for c in SAMPLE_CARDS if c.kind == "promo")

# ── 가짜 CLOVA 응답 (store_ongi, rv_ongi_001~003) ─────────────

GOOD_REPLY_001 = (
    "안녕하세요 고객님 :) 주문하신 공깃밥이 빠져서 정말 죄송해요. "
    "이런 실수가 생기지 않도록 포장 과정을 꼼꼼히 살피겠습니다. "
    "다음에 주문하실 때 요청사항에 남겨 주시면 반드시 챙겨 드릴게요. "
    "소중한 말씀 감사드려요. 온기한식 드림"
)

BAD_PROMISE_REPLY_002 = (
    "안녕하세요 고객님 :) 수저랑 젓가락이 빠져서 식사하시기 불편하셨을 텐데 정말 죄송합니다. "
    "다음에 주문해 주시면 무료 증정해 드리겠습니다! "
    "소중한 리뷰 감사합니다. 온기한식 드림"
)

NO_MISSING_REPLY_003 = (
    "안녕하세요 고객님 :) 주문하신 계란말이가 빠져서 많이 실망하셨을 텐데 죄송합니다. "
    "앞으로 더 신경 써서 빠지는 품목이 없도록 준비하겠습니다. "
    "소중한 리뷰 남겨 주셔서 감사합니다. 온기한식 드림"
)

FIXED_002 = (
    "안녕하세요 고객님 :) 수저랑 젓가락이 빠져서 식사에 불편을 드렸죠, 죄송해요. "
    "앞으로 포장할 때 수저 세트를 빠뜨리지 않도록 더 신경 쓸게요. "
    "다음 주문 시 요청사항에 남겨 주시면 꼭 챙기겠습니다. "
    "소중한 리뷰 감사해요. 온기한식 드림"
)

FIXED_003 = (
    "안녕하세요 고객님 :) 함께 주문하신 계란말이가 누락돼서 정말 죄송합니다. "
    "이런 일이 다시 없도록 출발 전 품목을 꼼꼼히 대조하겠습니다. "
    "혹시 다음 주문에서도 불편하시면 요청사항에 남겨 주세요. "
    "귀한 의견 고맙습니다. 온기한식 드림"
)

MOCK_RESP_1 = {
    "content": json.dumps({"답글": [
        {"review_id": "rv_ongi_001", "text": GOOD_REPLY_001, "근거": ["F_rv_ongi_001", "P1"]},
        {"review_id": "rv_ongi_002", "text": BAD_PROMISE_REPLY_002, "근거": ["F_rv_ongi_002", "P3"]},
        {"review_id": "rv_ongi_003", "text": NO_MISSING_REPLY_003, "근거": ["F_rv_ongi_003", "P1"]},
    ]}, ensure_ascii=False),
    "won": 0.05, "tokens": 300, "seconds": 1.0,
}

MOCK_RESP_2 = {
    "content": json.dumps({"답글": [
        {"review_id": "rv_ongi_002", "text": FIXED_002, "근거": ["F_rv_ongi_002", "P1"]},
        {"review_id": "rv_ongi_003", "text": FIXED_003, "근거": ["F_rv_ongi_003", "P1"]},
    ]}, ensure_ascii=False),
    "won": 0.03, "tokens": 200, "seconds": 0.8,
}

_reply_call_count = 0


def _mock_reply_call(key, system, messages, model="HCX-005", **kw):
    global _reply_call_count
    _reply_call_count += 1
    if _reply_call_count == 1:
        return MOCK_RESP_1
    return MOCK_RESP_2


class TestReplyDraftMock(unittest.TestCase):
    def setUp(self):
        global _reply_call_count
        _reply_call_count = 0

    @patch("clova.call", side_effect=_mock_reply_call)
    def test_generate(self, mock_clova):
        result = generate_reply_draft(CTX, COMPLAINT_CARD, "fake-key", model="HCX-005")

        self.assertIsInstance(result, CardResult)
        self.assertEqual(result.card_id, COMPLAINT_CARD.card_id)
        self.assertEqual(result.kind, "complaint")
        self.assertEqual(len(result.drafts), 3)

        by_id = {d.target_review_id: d for d in result.drafts}

        d001 = by_id["rv_ongi_001"]
        self.assertIsInstance(d001, DraftOutput)
        self.assertEqual(d001.generator, "reply_draft")
        self.assertEqual(d001.store_id, "store_ongi")
        self.assertTrue(all(d001.checks.values()), f"001 checks failed: {d001.checks}")
        self.assertEqual(d001.rewrites, 0)

        d002 = by_id["rv_ongi_002"]
        self.assertNotIn("무료 증정", d002.text)
        self.assertGreaterEqual(d002.rewrites, 1)

        d003 = by_id["rv_ongi_003"]
        self.assertTrue("계란말이" in d003.text, "003 should mention 계란말이 after rewrite")


# ── 재발 방지 공지 mock ──────────────────────────────────────

NOTICE_MOCK = {
    "content": json.dumps({
        "text": "포장 누락으로 불편을 드려 죄송합니다. 앞으로 포장 전 주문서를 한 번 더 대조해서 빠지는 품목이 없도록 하겠습니다. 불편을 드린 점 다시 한번 사과드려요.",
        "evidence_ids": ["rv_ongi_001", "rv_ongi_002", "rv_ongi_003"],
    }, ensure_ascii=False),
    "won": 0.03, "tokens": 100, "seconds": 0.5,
}


class TestNotice(unittest.TestCase):
    @patch("clova.call", return_value=NOTICE_MOCK)
    def test_generate_notice(self, mock_clova):
        result = generate_prevention_notice(CTX, COMPLAINT_CARD, "fake-key")
        self.assertIsInstance(result, CardResult)
        self.assertEqual(len(result.drafts), 1)
        draft = result.drafts[0]
        self.assertEqual(draft.generator, "prevention_notice")
        self.assertTrue(len(draft.text) > 0)
        self.assertEqual(draft.store_id, "store_ongi")


# ── 쿠폰 홍보글 mock ────────────────────────────────────────

PROMO_MOCK = {
    "content": json.dumps({
        "text": "온기한식에서 제육볶음 정식을 특별한 가격에 만나보세요! 따뜻한 한 끼가 필요하신 분들께 추천드려요. 쿠폰 받고 맛있게 드세요.",
        "evidence_ids": ["snap_sample_01"],
    }, ensure_ascii=False),
    "won": 0.03, "tokens": 100, "seconds": 0.5,
}


class TestPromo(unittest.TestCase):
    @patch("clova.call", return_value=PROMO_MOCK)
    def test_generate_promo(self, mock_clova):
        result = generate_coupon_promo(CTX, PROMO_CARD, "fake-key")
        self.assertIsInstance(result, CardResult)
        self.assertEqual(result.kind, "promo")
        self.assertIsNotNone(result.basis_label)
        self.assertIn("기준:", result.basis_label)
        self.assertIn("수치 확정 전", result.reason_text)
        self.assertEqual(len(result.drafts), 1)
        draft = result.drafts[0]
        self.assertEqual(draft.generator, "coupon_promo")
        self.assertTrue(len(draft.text) > 0)


# ── 레지스트리 ────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    def test_all_generators_registered(self):
        self.assertIn("reply_draft", CARD_GENERATORS)
        self.assertIn("prevention_notice", CARD_GENERATORS)
        self.assertIn("coupon_promo", CARD_GENERATORS)
        self.assertTrue(callable(CARD_GENERATORS["reply_draft"]))
        self.assertTrue(callable(CARD_GENERATORS["prevention_notice"]))
        self.assertTrue(callable(CARD_GENERATORS["coupon_promo"]))


# ── forbidden_phrase 점검 ─────────────────────────────────────

FORBIDDEN_REPLY = (
    "안녕하세요 고객님 :) 공깃밥이 빠져서 죄송합니다. "
    "배달 기사님 탓이 아니라 저희 포장 실수예요. "
    "다음엔 더 꼼꼼히 확인하겠습니다. "
    "소중한 의견 감사해요. 온기한식 드림"
)

CLEAN_REPLY = (
    "안녕하세요 고객님 :) 공깃밥이 빠져서 정말 죄송해요. "
    "앞으로 포장 전에 한 번 더 확인해서 이런 일이 없도록 하겠습니다. "
    "다음 주문 때 요청사항에 남겨 주시면 반드시 챙길게요. "
    "소중한 의견 감사해요. 온기한식 드림"
)

MOCK_FORBIDDEN_1 = {
    "content": json.dumps({"답글": [
        {"review_id": "rv_ongi_001", "text": FORBIDDEN_REPLY, "근거": ["F_rv_ongi_001", "P1"]},
        {"review_id": "rv_ongi_002", "text": FIXED_002, "근거": ["F_rv_ongi_002", "P1"]},
        {"review_id": "rv_ongi_003", "text": FIXED_003, "근거": ["F_rv_ongi_003", "P1"]},
    ]}, ensure_ascii=False),
    "won": 0.05, "tokens": 300, "seconds": 1.0,
}
MOCK_FORBIDDEN_2 = {
    "content": json.dumps({"답글": [
        {"review_id": "rv_ongi_001", "text": CLEAN_REPLY, "근거": ["F_rv_ongi_001", "P1"]},
    ]}, ensure_ascii=False),
    "won": 0.03, "tokens": 100, "seconds": 0.5,
}


class TestForbiddenPhrase(unittest.TestCase):
    def setUp(self):
        self._call_count = 0

    def _mock_forbidden(self, key, system, messages, model="HCX-005", **kw):
        self._call_count += 1
        if self._call_count == 1:
            return MOCK_FORBIDDEN_1
        return MOCK_FORBIDDEN_2

    @patch("clova.call")
    def test_forbidden_triggers_rewrite(self, mock_clova):
        mock_clova.side_effect = self._mock_forbidden
        result = generate_reply_draft(CTX, COMPLAINT_CARD, "fake-key")
        by_id = {d.target_review_id: d for d in result.drafts}
        d001 = by_id["rv_ongi_001"]
        self.assertNotIn("배달 기사님 탓", d001.text)


# ── 조치 점검 mock ────────────────────────────────────────────

INVENTED_REPLY = (
    "안녕하세요 고객님 :) 공깃밥이 빠져서 정말 죄송합니다. "
    "포장 체크리스트를 도입해서 누락이 없도록 개선하겠습니다. "
    "다음 주문 때 요청사항에 남겨 주시면 반드시 챙기겠습니다. "
    "소중한 의견 감사해요. 온기한식 드림"
)

GENERIC_REPLY = (
    "안녕하세요 고객님 :) 공깃밥이 빠져서 정말 죄송합니다. "
    "앞으로 더 꼼꼼히 확인해서 이런 일이 없도록 하겠습니다. "
    "다음 주문 때 요청사항에 남겨 주시면 반드시 챙기겠습니다. "
    "소중한 의견 감사해요. 온기한식 드림"
)

MEASURE_REPLY = (
    "안녕하세요 고객님 :) 공깃밥이 빠져서 정말 죄송합니다. "
    "포장 마감 전 주문서 대조를 통해 누락이 없도록 하겠습니다. "
    "다음 주문 때 요청사항에 남겨 주시면 반드시 챙기겠습니다. "
    "소중한 의견 감사해요. 온기한식 드림"
)

SIMPLE_002 = (
    "안녕하세요 고객님 :) 수저가 빠져서 정말 죄송합니다. "
    "앞으로 꼼꼼히 살펴서 빠지는 일이 없도록 할게요. "
    "다음 주문 시 요청사항에 남겨 주시면 꼭 챙기겠습니다. "
    "소중한 리뷰 감사해요. 온기한식 드림"
)

SIMPLE_003 = (
    "안녕하세요 고객님 :) 계란말이가 누락돼서 죄송합니다. "
    "앞으로 누락 없도록 신경 쓰겠습니다. "
    "다음 주문 때 요청사항에 적어 주시면 챙겨 드릴게요. "
    "귀한 의견 감사해요. 온기한식 드림"
)


class TestInventedMeasure(unittest.TestCase):
    def setUp(self):
        self._call_count = 0

    def _mock_invented(self, key, system, messages, model="HCX-005", **kw):
        self._call_count += 1
        if self._call_count == 1:
            return {"content": json.dumps({"답글": [
                {"review_id": "rv_ongi_001", "text": INVENTED_REPLY, "근거": ["F_rv_ongi_001", "P1"]},
                {"review_id": "rv_ongi_002", "text": SIMPLE_002, "근거": ["F_rv_ongi_002", "P1"]},
                {"review_id": "rv_ongi_003", "text": SIMPLE_003, "근거": ["F_rv_ongi_003", "P1"]},
            ]}, ensure_ascii=False), "won": 0.05, "tokens": 300, "seconds": 1.0}
        return {"content": json.dumps({"답글": [
            {"review_id": "rv_ongi_001", "text": GENERIC_REPLY, "근거": ["F_rv_ongi_001", "P1"]},
        ]}, ensure_ascii=False), "won": 0.03, "tokens": 100, "seconds": 0.5}

    @patch("clova.call")
    def test_no_measures_invented_triggers_rewrite(self, mock_clova):
        mock_clova.side_effect = self._mock_invented
        result = generate_reply_draft(CTX, COMPLAINT_CARD, "fake-key", chosen_measures=None)
        by_id = {d.target_review_id: d for d in result.drafts}
        self.assertNotIn("체크리스트", by_id["rv_ongi_001"].text)

    def _mock_with_measure(self, key, system, messages, model="HCX-005", **kw):
        self._call_count += 1
        return {"content": json.dumps({"답글": [
            {"review_id": "rv_ongi_001", "text": MEASURE_REPLY, "근거": ["F_rv_ongi_001", "P1", "M1"]},
            {"review_id": "rv_ongi_002", "text": SIMPLE_002, "근거": ["F_rv_ongi_002", "P1"]},
            {"review_id": "rv_ongi_003", "text": SIMPLE_003, "근거": ["F_rv_ongi_003", "P1"]},
        ]}, ensure_ascii=False), "won": 0.05, "tokens": 300, "seconds": 1.0}

    @patch("clova.call")
    def test_chosen_measure_passes(self, mock_clova):
        mock_clova.side_effect = self._mock_with_measure
        m1 = MEASURES[0]
        result = generate_reply_draft(CTX, COMPLAINT_CARD, "fake-key", chosen_measures=[m1])
        by_id = {d.target_review_id: d for d in result.drafts}
        d001 = by_id["rv_ongi_001"]
        self.assertTrue(d001.checks.get("no_invented_measure", False),
                        f"M1 used but flagged: {d001.checks}")


class TestParsing(unittest.TestCase):
    IDS = ["rv_ongi_001", "rv_ongi_002", "rv_ongi_003"]

    def test_fenced_json(self):
        raw = '```json\n{"답글":[{"review_id":"rv_ongi_001","text":"감사합니다","근거":["F_rv_ongi_001"]}]}\n```'
        data, err = _robust_parse(raw)
        self.assertIsNone(err, err)
        replies, err = _normalize_replies(data, self.IDS)
        self.assertIsNone(err, err)
        self.assertEqual(replies[0]["review_id"], "rv_ongi_001")

    def test_list_toplevel(self):
        raw = json.dumps([
            {"review_id": "rv_ongi_001", "text": "첫 번째", "근거": ["F_rv_ongi_001"]},
            {"review_id": "rv_ongi_002", "text": "두 번째", "근거": ["F_rv_ongi_002"]},
        ], ensure_ascii=False)
        data, err = _robust_parse(raw)
        self.assertIsNone(err, err)
        replies, err = _normalize_replies(data, self.IDS)
        self.assertIsNone(err, err)
        self.assertEqual(len(replies), 2)
        self.assertEqual(replies[1]["text"], "두 번째")

    def test_alt_keys_no_id(self):
        raw = json.dumps({"replies": [
            {"reply": "답글A", "evidence": ["F_rv_ongi_001"]},
            {"reply": "답글B", "evidence": ["F_rv_ongi_002"]},
            {"reply": "답글C", "evidence": ["F_rv_ongi_003"]},
        ]}, ensure_ascii=False)
        data, err = _robust_parse(raw)
        self.assertIsNone(err, err)
        replies, err = _normalize_replies(data, self.IDS)
        self.assertIsNone(err, err)
        self.assertEqual(len(replies), 3)
        self.assertEqual(replies[0]["review_id"], "rv_ongi_001")
        self.assertEqual(replies[2]["text"], "답글C")
        self.assertEqual(replies[1]["근거"], ["F_rv_ongi_002"])


class TestReplyLive(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("CLOVA_API_KEY") and "--mock" not in sys.argv,
        "live test: CLOVA_API_KEY 필요, --mock 시 건너뜀",
    )
    def test_live(self):
        key = os.environ["CLOVA_API_KEY"]
        result = generate_reply_draft(CTX, COMPLAINT_CARD, key, model="HCX-005")

        self.assertIsInstance(result, CardResult)
        self.assertEqual(len(result.drafts), 3)
        for d in result.drafts:
            self.assertIsInstance(d, DraftOutput)
            self.assertEqual(d.generator, "reply_draft")

        md_lines = ["# C6 답글 생성 결과\n"]
        for d in result.drafts:
            md_lines.append(f"## {d.target_review_id}")
            md_lines.append(f"- 답글: {d.text}")
            md_lines.append(f"- 근거: {d.evidence_ids}")
            md_lines.append(f"- 점검: {d.checks}")
            md_lines.append(f"- 다시 쓴 횟수: {d.rewrites}")
            if d.needs_input:
                md_lines.append(f"- ⚠ needs_input: {d.needs_input}")
            md_lines.append("")
        md_lines.append(f"- 걸린 시간: {result.elapsed_ms}ms")
        md_lines.append(f"- 예상 요금: {result.won}원")

        out = config.RESULTS_DIR / "c6_reply.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(md_lines), encoding="utf-8")
        print(f"\n결과 저장: {out}")


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--mock"]
    unittest.main(argv=argv, verbosity=2)
