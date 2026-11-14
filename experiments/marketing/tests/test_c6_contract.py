"""C6 contract 검증 — shared.contracts 기준, AI 호출 없음."""

import unittest

from shared.contracts import (
    StoreProfile, ReviewRecord, ToneProfile, RecommendationCard, AnalysisSnapshot,
)
from shared.sample_scenario import (
    SAMPLE_STORE, SAMPLE_REVIEWS, SAMPLE_SNAPSHOTS, SAMPLE_TONE, SAMPLE_CARDS,
)
from c6.contract import C6Context, build_context


class TestBuildContextDefaults(unittest.TestCase):
    def test_defaults_populate_from_sample(self):
        ctx = build_context()
        self.assertIsInstance(ctx.store, StoreProfile)
        self.assertEqual(ctx.store.store_id, "store_ongi")
        self.assertEqual(len(ctx.reviews), 3)
        for rv in ctx.reviews:
            self.assertIsInstance(rv, ReviewRecord)
        self.assertIsInstance(ctx.tone, ToneProfile)
        self.assertEqual(ctx.tone.tone_id, "tone_ongi")
        for card in ctx.cards:
            self.assertIsInstance(card, RecommendationCard)
        for snap in ctx.snapshots:
            self.assertIsInstance(snap, AnalysisSnapshot)
        self.assertIsInstance(ctx.owner_replies, list)
        self.assertIsInstance(ctx.policies, list)
        self.assertTrue(all("팀 데이터에 없음" in n for n in ctx.needs_input))

    def test_custom_store_no_needs(self):
        ctx = build_context(
            store=SAMPLE_STORE,
            reviews=list(SAMPLE_REVIEWS),
            tone=SAMPLE_TONE,
            cards=list(SAMPLE_CARDS),
            snapshots=list(SAMPLE_SNAPSHOTS),
            owner_replies=["안녕하세요"],
            policies=[{"policy_id": "P1", "text": "정책"}],
        )
        self.assertEqual(ctx.needs_input, [])
        self.assertEqual(ctx.store.store_id, "store_ongi")
        self.assertEqual(len(ctx.reviews), 3)

    def test_partial_fills_rest_with_dummy(self):
        ctx = build_context(store=SAMPLE_STORE, reviews=list(SAMPLE_REVIEWS))
        self.assertNotIn("리뷰", " ".join(ctx.needs_input))
        self.assertIn("팀 데이터에 없음: 사장님 말투(ToneProfile)", ctx.needs_input)


class TestC6Context(unittest.TestCase):
    def test_slots(self):
        ctx = build_context()
        with self.assertRaises(AttributeError):
            ctx.nonexistent = "test"  # type: ignore[attr-defined]

    def test_dataclass_instances_used_directly(self):
        ctx = build_context()
        self.assertEqual(ctx.store.name, SAMPLE_STORE.name)
        self.assertEqual(ctx.reviews[0].review_id, SAMPLE_REVIEWS[0].review_id)
        self.assertEqual(ctx.tone.style_description, SAMPLE_TONE.style_description)
        self.assertEqual(ctx.cards[0].kind, "complaint")
        self.assertEqual(ctx.snapshots[0].snapshot_id, SAMPLE_SNAPSHOTS[0].snapshot_id)


class TestSampleDataIntegrity(unittest.TestCase):
    def test_review_ids_match_card(self):
        complaint_card = next(c for c in SAMPLE_CARDS if c.kind == "complaint")
        review_ids = {r.review_id for r in SAMPLE_REVIEWS}
        for rid in complaint_card.review_ids:
            self.assertIn(rid, review_ids)

    def test_snapshot_ids_match_promo_card(self):
        promo_card = next(c for c in SAMPLE_CARDS if c.kind == "promo")
        snapshot_ids = {s.snapshot_id for s in SAMPLE_SNAPSHOTS}
        for sid in promo_card.snapshot_ids:
            self.assertIn(sid, snapshot_ids)

    def test_tone_has_forbidden_phrases(self):
        self.assertTrue(len(SAMPLE_TONE.forbidden_phrases) > 0)

    def test_tone_has_style(self):
        self.assertTrue(len(SAMPLE_TONE.style_description) > 0)
        self.assertTrue(len(SAMPLE_TONE.example_sentences) > 0)


if __name__ == "__main__":
    unittest.main()
