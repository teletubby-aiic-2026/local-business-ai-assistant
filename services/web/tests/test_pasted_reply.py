"""붙여넣은 불만 리뷰의 답글 (11/14) — 카드 ⓐ 묶음에 들지 않은 붙여넣은 리뷰(예: 무리한 요청을 거절해 남은 억울한 별점)도
카드 ⓐ 를 만들 때 답글이 같이 나오는지, 답글 태도(stance)가 응답에 실리는지 본다. CLOVA·네트워크를 부르지 않는다.

실행 (services/web 에서): PYTHONPATH=<저장소 루트> python -m pytest -q tests/test_pasted_reply.py
리뷰 문장은 모두 이 시험을 위해 지어낸 합성 문장이다.
"""
from __future__ import annotations

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from web.demo import Demo
from web.generate import PASTED_EXAMPLES_RELATIVE, ensure_marketing_on_path, pasted_reply_targets
from web.main import create_app
from web.settings import WEB_DIR

from tests.test_web import HAS_C6, MARKETING, FakeSource, settings

STATIC = WEB_DIR / "web" / "static"
EXAMPLES = MARKETING / PASTED_EXAMPLES_RELATIVE
UNFAIR = "제육볶음 정식 고기를 불고기로 그냥 바꿔 달라고 했더니 안 된대요. 그것도 못 해 주나요? 별 하나 드립니다"
OTHER_UNFAIR = "계란말이 서비스로 하나 달라고 했더니 안 된다고 하셨어요. 단골한테 너무하네요"


class PasteSource(FakeSource):
    """#14 처럼 붙여넣은 리뷰에 별점과 분류를 붙인다 (억울한 리뷰는 live 에서 '응대'로 분류돼 카드 ⓐ 묶음에 안 들어감)."""

    def paste(self, store_id, text, rating=None, channel=None):
        out = super().paste(store_id, text, rating, channel)
        self.pasted[-1]["rating"] = rating
        return out

    def insight(self, store_id):
        ins = copy.deepcopy(super().insight(store_id))
        for r in self.pasted:
            positive = (r.get("rating") or 0) >= 4
            ins["classifications"].append({
                "review_id": r["review_id"], "sentiment": "positive" if positive else "negative",
                "topics": [{"topic": "service", "polarity": "positive" if positive else "negative", "evidence": r["text"][:6]}],
                "negative_topics": [] if positive else ["service"], "method": "rule", "model": "kiwi", "warnings": []})
        return ins


def paste_samples() -> list[dict]:
    """app.js 의 PASTE_SAMPLES 배열 (text·rating)."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    block = re.search(r"const PASTE_SAMPLES = \[(.*?)\];", js, re.S).group(1)
    return [{"text": t, "rating": int(r)} for t, r in re.findall(r'\{\s*text:\s*"([^"]+)",\s*rating:\s*(\d)\s*\}', block)]


@unittest.skipUnless(HAS_C6, "MARKETING_DIR(C6 저장본) 없음")
class MockPastedReply(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.source = PasteSource()
        self.client = TestClient(create_app(Demo(settings(self.tmp), source=self.source)))

    def _run_a(self):
        a = self.client.get("/api/cards").json()["cards"][0]["card"]
        return a, self.client.post(f"/api/cards/{a['card_id']}/run").json()

    def test_unfair_sample_gets_the_stored_explain_reply(self):
        _, before = self._run_a()
        rid = self.client.post("/api/reviews", json={"text": UNFAIR, "rating": 1}).json()["review"]["review_id"]
        card, r = self._run_a()
        self.assertNotIn(rid, card["review_ids"])                       # 카드 근거는 그대로 (포장 누락 3건)
        self.assertEqual([d["draft_id"] for d in r["drafts"][:4]], [d["draft_id"] for d in before["drafts"]])
        self.assertEqual(len(r["drafts"]), 5)
        mine = r["drafts"][4]
        self.assertEqual((mine["generator"], mine["target_review_id"], mine["card_id"]), ("reply_draft", rid, card["card_id"]))
        self.assertEqual(mine["stance"], "explain")
        self.assertTrue(mine["stance_reasons"])
        self.assertEqual(mine["evidence_ids"][0], f"F_{rid}")
        self.assertNotIn("죄송", mine["text"])
        self.assertEqual(mine["failed_reasons"], [])
        self.assertTrue(any("사과 없이" in n for n in mine["needs_input"]))   # 화면에서는 '확인 필요'로 보임
        self.assertEqual(r["pasted_reply_review_ids"], [rid])
        self.assertEqual(r["pasted_reply_skipped"], [])
        self.assertIn("저장 예시", r["source_note"])
        self.assertEqual(r["source"], "seed")                            # 실제 AI 결과 아님 표시는 그대로
        self.assertEqual(r["flagged_count"], before["flagged_count"] + 1)
        ok = self.client.post(f"/api/drafts/{mine['draft_id']}/approve", json={"text": mine["text"], "original": mine["text"]})
        self.assertEqual(ok.status_code, 200)

    def test_other_pasted_complaint_is_skipped_with_a_note(self):
        rid = self.client.post("/api/reviews", json={"text": OTHER_UNFAIR, "rating": 1}).json()["review"]["review_id"]
        _, r = self._run_a()
        self.assertEqual(len(r["drafts"]), 4)                            # 다른 리뷰의 저장 답글을 붙이지 않는다
        self.assertEqual([s["review_id"] for s in r["pasted_reply_skipped"]], [rid])
        self.assertIn("답글을 만들지 않았어요", r["source_note"])

    def test_praise_is_not_a_reply_target(self):
        self.client.post("/api/reviews", json={"text": "점심에 먹었는데 반찬도 깔끔하고 사장님도 친절하세요!", "rating": 5})
        _, r = self._run_a()
        self.assertEqual(len(r["drafts"]), 4)
        self.assertNotIn("pasted_reply_review_ids", r)

    def test_promo_card_is_unchanged(self):
        self.client.post("/api/reviews", json={"text": UNFAIR, "rating": 1})
        b = self.client.get("/api/cards").json()["cards"][1]["card"]
        r = self.client.post(f"/api/cards/{b['card_id']}/run").json()
        self.assertEqual([d["generator"] for d in r["drafts"]], ["coupon_promo"])


class LivePastedReply(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.source = PasteSource()
        demo = Demo(settings(self.tmp, mode="live", clova_key="test-key"), source=self.source,
                    reason_model=lambda system, user: "")
        self.client = TestClient(create_app(demo))
        self.made = {"kind": "complaint", "source": "live", "won": 1.0, "drafts": [
            {"draft_id": "d1", "generator": "reply_draft", "target_review_id": "rv_ongi_001", "text": "죄송해요."}]}

    def test_pasted_unfair_review_reply_is_made_with_the_card(self):
        rid = self.client.post("/api/reviews", json={"text": UNFAIR, "rating": 1}).json()["review"]["review_id"]
        extra = {"won": 0.5, "drafts": [{"draft_id": "d2", "generator": "reply_draft", "target_review_id": rid,
                                         "text": "아쉬우셨을 것 같아요.", "stance": "explain", "needs_input": ["사실 확인: …"]}]}
        card = self.client.get("/api/cards").json()["cards"][0]["card"]
        with mock.patch("web.demo.run_live", return_value=copy.deepcopy(self.made)) as live, \
                mock.patch("web.demo.run_live_pasted_replies", return_value=extra) as pasted:
            r = self.client.post(f"/api/cards/{card['card_id']}/run").json()
        self.assertEqual(live.call_count, 1)
        self.assertNotIn(rid, live.call_args.args[0].review_ids)          # 카드 ⓐ 생성 입력은 그대로
        self.assertEqual([t.review_id for t in pasted.call_args.args[1]], [rid])
        self.assertEqual([d["draft_id"] for d in r["drafts"]], ["d1", "d2"])
        self.assertEqual(r["pasted_reply_review_ids"], [rid])
        self.assertEqual(r["won"], 1.5)

    def test_no_pasted_review_means_no_extra_call(self):
        card = self.client.get("/api/cards").json()["cards"][0]["card"]
        with mock.patch("web.demo.run_live", return_value=copy.deepcopy(self.made)), \
                mock.patch("web.demo.run_live_pasted_replies") as pasted:
            r = self.client.post(f"/api/cards/{card['card_id']}/run").json()
        pasted.assert_not_called()
        self.assertNotIn("pasted_reply_review_ids", r)

    def test_pasted_reply_failure_keeps_the_card_drafts(self):
        rid = self.client.post("/api/reviews", json={"text": UNFAIR, "rating": 1}).json()["review"]["review_id"]
        card = self.client.get("/api/cards").json()["cards"][0]["card"]
        with mock.patch("web.demo.run_live", return_value=copy.deepcopy(self.made)), \
                mock.patch("web.demo.run_live_pasted_replies", side_effect=RuntimeError("boom")):
            res = self.client.post(f"/api/cards/{card['card_id']}/run")
        self.assertEqual(res.status_code, 200)
        r = res.json()
        self.assertEqual([d["draft_id"] for d in r["drafts"]], ["d1"])
        self.assertEqual([s["review_id"] for s in r["pasted_reply_skipped"]], [rid])


class Targets(unittest.TestCase):
    def test_only_pasted_complaints_outside_the_card(self):
        from shared.contracts import RecommendationCard, ReviewRecord

        def rv(i, method="paste", rating=1, sentiment="negative"):
            return ReviewRecord(review_id=f"rv_{i}", store_id="store_ongi", text="t", created_at="2026-11-14T10:00:00+09:00",
                                rating=rating, input_method=method, sentiment=sentiment)
        card = RecommendationCard(card_id="c", store_id="store_ongi", kind="complaint", reason_text="r", review_ids=["rv_1"])
        reviews = [rv(1), rv(2), rv(3, method="sample"), rv(4, rating=5, sentiment="positive"), rv(5, rating=None),
                   rv(6), rv(7), rv(8)]
        self.assertEqual([r.review_id for r in pasted_reply_targets(card, reviews)], ["rv_2", "rv_5", "rv_6"])   # 최대 3건


@unittest.skipUnless(HAS_C6, "MARKETING_DIR(C6 저장본) 없음")
class PasteSampleAndStoredExample(unittest.TestCase):
    def test_paste_samples_keep_the_old_three_and_add_the_unfair_one(self):
        samples = paste_samples()
        self.assertEqual(len(samples), 4)
        self.assertEqual(samples[:3], [
            {"text": "저녁 8시에 시켰는데 한 시간 넘게 걸렸고 국물도 다 식었어요", "rating": 1},
            {"text": "맛은 정말 좋은데 포장이 허술해서 국물이 조금 샜어요", "rating": 3},
            {"text": "점심에 먹었는데 반찬도 깔끔하고 사장님도 친절하세요!", "rating": 5}])
        self.assertEqual(samples[3], {"text": UNFAIR, "rating": 1})

    def test_unfair_sample_has_a_stored_example_that_still_passes(self):
        ensure_marketing_on_path(MARKETING)
        from c6 import reply_explain as rx
        from c6.dummy import POLICIES
        from c6.stance import EXPLAIN, judge_stance
        from shared.sample_scenario import SAMPLE_STORE, SAMPLE_TONE

        examples = json.loads(EXAMPLES.read_text(encoding="utf-8"))
        match = [e for e in examples if " ".join(e["review_text"].split()) == " ".join(UNFAIR.split())]
        self.assertEqual(len(match), 1)
        ex = match[0]
        self.assertEqual(judge_stance(UNFAIR).stance, EXPLAIN)            # 판정 규칙이 바뀌어도 저장 예시와 맞는지
        draft = ex["draft"]
        self.assertEqual(draft["stance"], EXPLAIN)
        self.assertEqual(draft["data_origin"], "synthetic")
        self.assertTrue(all(draft["checks"].values()), draft["checks"])
        # 지금 점검 규칙으로 다시 봐도 통과 (AI 부분 = 인사 뒤 첫 문장들, 코드 문장 앞까지)
        decision = judge_stance(UNFAIR)
        body = draft["text"].split(":)", 1)[1].rsplit(" 온기한식 드림", 1)[0]
        ai_part = body.split(decision.principle)[0].strip()
        res = rx.run_explain_checks(draft["text"], ai_part=ai_part, review_text=UNFAIR, menu_names=list(SAMPLE_STORE.menu),
                                    allowed_numbers=list(SAMPLE_STORE.menu_prices.values()), policies=POLICIES,
                                    forbidden_phrases=SAMPLE_TONE.forbidden_phrases, evidence=["F_x"], valid_ids={"F_x"})
        self.assertEqual([k for k, v in res.items() if not v], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
