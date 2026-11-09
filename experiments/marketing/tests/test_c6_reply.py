"""C6 답글 생성 검증 — --mock: 가짜 CLOVA 응답, 기본: live."""

import json
import os
import sys
import unittest
from unittest.mock import patch

import config
from c6.dummy import STORE, REVIEWS, OWNER_REPLIES, POLICIES, CARDS
from c6.contract import to_ctx
from c6.measures import MEASURES
from c6.reply import generate_replies, _robust_parse, _normalize_replies

CTX = to_ctx({
    "store": STORE, "reviews": REVIEWS,
    "owner_replies": OWNER_REPLIES,
    "policies": POLICIES, "cards": CARDS,
})
CARD = CARDS[0]  # repeat_complaint, review_ids=["R01","R02","R03"]

# ── 가짜 CLOVA 응답 ────────────────────────────────────────────

GOOD_REPLY = (
    "안녕하세요 고객님 :) 제육덮밥과 함께 주문하신 계란국이 빠져서 정말 죄송합니다. "
    "앞으로 더 꼼꼼히 확인해서 이런 일이 없도록 하겠습니다. "
    "다음 주문 때 요청사항에 남겨 주시면 반드시 챙기겠습니다. "
    "소중한 의견 감사드려요. 든든한끼 드림"
)

BAD_PROMISE_REPLY = (
    "안녕하세요 고객님 :) 콜라가 빠져서 정말 죄송합니다. "
    "다음에 주문해 주시면 무료 증정해 드리겠습니다! "
    "소중한 리뷰 감사합니다. 든든한끼 드림"
)

NO_MISSING_REPLY = (
    "안녕하세요 고객님 :) 불편을 드려 정말 죄송합니다. "
    "앞으로 더 신경 써서 준비하겠습니다. "
    "소중한 리뷰 감사합니다. 든든한끼 드림"
)

FIXED_R02 = (
    "안녕하세요 고객님 :) 덮밥은 맛있게 드셨는데 콜라가 빠져 아쉬우셨겠어요, 죄송합니다. "
    "앞으로 더 꼼꼼히 살펴서 빠지는 일이 없도록 하겠습니다. "
    "다음 주문 시 요청사항에 말씀 남겨 주시면 꼭 챙길게요. 감사합니다! 든든한끼 드림"
)

FIXED_R03 = (
    "안녕하세요 고객님 :) 소스가 빠져서 밋밋하게 드셨다니 정말 죄송합니다. "
    "앞으로 누락 없이 잘 준비하겠습니다. "
    "혹시 다음 주문에서도 불편하시면 요청사항에 남겨 주세요. "
    "귀한 의견 고맙습니다. 든든한끼 드림"
)

MOCK_RESP_1 = {
    "content": json.dumps({"답글": [
        {"review_id": "R01", "text": GOOD_REPLY, "근거": ["F01", "P1"]},
        {"review_id": "R02", "text": BAD_PROMISE_REPLY, "근거": ["F02", "P3"]},
        {"review_id": "R03", "text": NO_MISSING_REPLY, "근거": ["F03", "P1"]},
    ]}, ensure_ascii=False),
    "won": 0.05, "tokens": 300, "seconds": 1.0,
}

MOCK_RESP_2 = {
    "content": json.dumps({"답글": [
        {"review_id": "R02", "text": FIXED_R02, "근거": ["F02", "P1"]},
        {"review_id": "R03", "text": FIXED_R03, "근거": ["F03", "P1"]},
    ]}, ensure_ascii=False),
    "won": 0.03, "tokens": 200, "seconds": 0.8,
}

_call_count = 0

def _mock_call(key, system, messages, model="HCX-005", **kw):
    global _call_count
    _call_count += 1
    if _call_count == 1:
        return MOCK_RESP_1
    return MOCK_RESP_2


class TestReplyMock(unittest.TestCase):
    def setUp(self):
        global _call_count
        _call_count = 0

    @patch("clova.call", side_effect=_mock_call)
    def test_generate(self, mock_clova):
        result = generate_replies(CTX, CARD, "fake-key", model="HCX-005")

        self.assertIn("outputs", result)
        self.assertEqual(len(result["outputs"]), 3)
        self.assertGreaterEqual(result["calls"], 2)

        by_id = {o["target_id"]: o for o in result["outputs"]}

        r01 = by_id["R01"]
        self.assertEqual(r01["kind"], "reply")
        self.assertTrue(all(r01["checks"].values()), f"R01 checks failed: {r01['checks']}")
        self.assertEqual(r01["rewrites"], 0)
        self.assertEqual(r01["needs_input"], [])

        r02 = by_id["R02"]
        self.assertNotIn("무료 증정", r02["text"])
        self.assertGreaterEqual(r02["rewrites"], 1)

        r03 = by_id["R03"]
        self.assertTrue("소스" in r03["text"], "R03 should mention 소스 after rewrite")


# ── 조치 점검 mock 응답 ──────────────────────────────────────

INVENTED_REPLY_R01 = (
    "안녕하세요 고객님 :) 계란국이 빠져서 정말 죄송합니다. "
    "포장 체크리스트를 도입해서 누락이 없도록 개선하겠습니다. "
    "다음 주문 때 요청사항에 남겨 주시면 반드시 챙기겠습니다. "
    "소중한 의견 감사드려요. 든든한끼 드림"
)

GENERIC_REPLY_R01 = (
    "안녕하세요 고객님 :) 계란국이 빠져서 정말 죄송합니다. "
    "앞으로 더 꼼꼼히 확인해서 이런 일이 없도록 하겠습니다. "
    "다음 주문 때 요청사항에 남겨 주시면 반드시 챙기겠습니다. "
    "소중한 의견 감사드려요. 든든한끼 드림"
)

MEASURE_REPLY_R01 = (
    "안녕하세요 고객님 :) 계란국이 빠져서 정말 죄송합니다. "
    "포장 마감 전 주문서 대조를 통해 누락이 없도록 하겠습니다. "
    "다음 주문 때 요청사항에 남겨 주시면 반드시 챙기겠습니다. "
    "소중한 의견 감사드려요. 든든한끼 드림"
)

SIMPLE_R02 = (
    "안녕하세요 고객님 :) 콜라가 빠져서 정말 죄송합니다. "
    "앞으로 꼼꼼히 살펴서 빠지는 일이 없도록 할게요. "
    "다음 주문 시 요청사항에 남겨 주시면 꼭 챙기겠습니다. "
    "소중한 리뷰 감사합니다. 든든한끼 드림"
)

SIMPLE_R03 = (
    "안녕하세요 고객님 :) 소스가 빠져서 밋밋하게 드셨다니 죄송합니다. "
    "앞으로 누락 없도록 신경 쓰겠습니다. "
    "다음 주문 때 요청사항에 적어 주시면 챙겨 드릴게요. "
    "귀한 의견 감사합니다. 든든한끼 드림"
)


class TestInventedMeasure(unittest.TestCase):
    """조치 미선택 시 지어낸 조치 → 다시 쓰기 / 선택(M1) 시 통과."""

    def setUp(self):
        self._call_count = 0

    def _mock_invented(self, key, system, messages, model="HCX-005", **kw):
        self._call_count += 1
        if self._call_count == 1:
            return {"content": json.dumps({"답글": [
                {"review_id": "R01", "text": INVENTED_REPLY_R01, "근거": ["F01", "P1"]},
                {"review_id": "R02", "text": SIMPLE_R02, "근거": ["F02", "P1"]},
                {"review_id": "R03", "text": SIMPLE_R03, "근거": ["F03", "P1"]},
            ]}, ensure_ascii=False), "won": 0.05, "tokens": 300, "seconds": 1.0}
        return {"content": json.dumps({"답글": [
            {"review_id": "R01", "text": GENERIC_REPLY_R01, "근거": ["F01", "P1"]},
        ]}, ensure_ascii=False), "won": 0.03, "tokens": 100, "seconds": 0.5}

    @patch("clova.call")
    def test_no_measures_invented_triggers_rewrite(self, mock_clova):
        mock_clova.side_effect = self._mock_invented
        result = generate_replies(CTX, CARD, "fake-key", chosen_measures=None)
        by_id = {o["target_id"]: o for o in result["outputs"]}
        self.assertGreaterEqual(result["calls"], 2, "invented measure should trigger rewrite")
        self.assertNotIn("체크리스트", by_id["R01"]["text"])

    def _mock_with_measure(self, key, system, messages, model="HCX-005", **kw):
        self._call_count += 1
        return {"content": json.dumps({"답글": [
            {"review_id": "R01", "text": MEASURE_REPLY_R01, "근거": ["F01", "P1", "M1"]},
            {"review_id": "R02", "text": SIMPLE_R02, "근거": ["F02", "P1"]},
            {"review_id": "R03", "text": SIMPLE_R03, "근거": ["F03", "P1"]},
        ]}, ensure_ascii=False), "won": 0.05, "tokens": 300, "seconds": 1.0}

    @patch("clova.call")
    def test_chosen_measure_passes(self, mock_clova):
        mock_clova.side_effect = self._mock_with_measure
        m1 = MEASURES[0]  # M1: 포장 마감 전 주문서 대조
        result = generate_replies(CTX, CARD, "fake-key", chosen_measures=[m1])
        by_id = {o["target_id"]: o for o in result["outputs"]}
        r01 = by_id["R01"]
        self.assertTrue(r01["checks"].get("no_invented_measure", False),
                        f"M1 used but flagged: {r01['checks']}")
        self.assertEqual(result["calls"], 1)


class TestParsing(unittest.TestCase):
    """펜스·list 최상위·다른 키 이름 응답 파싱."""

    IDS = ["R01", "R02", "R03"]

    def test_fenced_json(self):
        raw = '```json\n{"답글":[{"review_id":"R01","text":"감사합니다","근거":["F01"]}]}\n```'
        data, err = _robust_parse(raw)
        self.assertIsNone(err, err)
        replies, err = _normalize_replies(data, self.IDS)
        self.assertIsNone(err, err)
        self.assertEqual(replies[0]["review_id"], "R01")

    def test_list_toplevel(self):
        raw = json.dumps([
            {"review_id": "R01", "text": "첫 번째", "근거": ["F01"]},
            {"review_id": "R02", "text": "두 번째", "근거": ["F02"]},
        ], ensure_ascii=False)
        data, err = _robust_parse(raw)
        self.assertIsNone(err, err)
        replies, err = _normalize_replies(data, self.IDS)
        self.assertIsNone(err, err)
        self.assertEqual(len(replies), 2)
        self.assertEqual(replies[1]["text"], "두 번째")

    def test_alt_keys_no_id(self):
        raw = json.dumps({"replies": [
            {"reply": "답글A", "evidence": ["F01"]},
            {"reply": "답글B", "evidence": ["F02"]},
            {"reply": "답글C", "evidence": ["F03"]},
        ]}, ensure_ascii=False)
        data, err = _robust_parse(raw)
        self.assertIsNone(err, err)
        replies, err = _normalize_replies(data, self.IDS)
        self.assertIsNone(err, err)
        self.assertEqual(len(replies), 3)
        self.assertEqual(replies[0]["review_id"], "R01")
        self.assertEqual(replies[2]["text"], "답글C")
        self.assertEqual(replies[1]["근거"], ["F02"])


class TestReplyLive(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("CLOVA_API_KEY") and "--mock" not in sys.argv,
        "live test: CLOVA_API_KEY 필요, --mock 시 건너뜀",
    )
    def test_live(self):
        key = os.environ["CLOVA_API_KEY"]
        result = generate_replies(CTX, CARD, key, model="HCX-005")

        self.assertEqual(len(result["outputs"]), 3)
        for o in result["outputs"]:
            self.assertEqual(o["kind"], "reply")
            self.assertIn("checks", o)

        md_lines = ["# C6 답글 생성 결과\n"]
        for o in result["outputs"]:
            md_lines.append(f"## {o['target_id']}")
            md_lines.append(f"- 답글: {o['text']}")
            md_lines.append(f"- 근거: {o['evidence_ids']}")
            md_lines.append(f"- 점검: {o['checks']}")
            md_lines.append(f"- 다시 쓴 횟수: {o['rewrites']}")
            if o["needs_input"]:
                md_lines.append(f"- ⚠ needs_input: {o['needs_input']}")
            md_lines.append("")
        md_lines.append(f"- 걸린 시간: {result['elapsed_s']}초")
        md_lines.append(f"- 호출 횟수: {result['calls']}")
        md_lines.append(f"- 예상 요금: {result['won']}원")

        out = config.RESULTS_DIR / "c6_reply.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(md_lines), encoding="utf-8")
        print(f"\n결과 저장: {out}")


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--mock"]
    unittest.main(argv=argv, verbosity=2)
