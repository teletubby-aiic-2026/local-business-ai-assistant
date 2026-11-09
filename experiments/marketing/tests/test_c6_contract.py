"""C6 contract 매핑 검증 — 팀 데이터 샘플로, AI 호출 없음."""

import unittest

from c6.contract import to_ctx, _merge_labels, _map_store, make_cards_from_c3

# ── 팀 데이터 앞부분 샘플 (C2 store_basak 기준) ──────────────────────

SAMPLE_STORE = {
    "store_id": "store_basak",
    "name": "바삭치킨 (가상)",
    "business_type": "chicken",
    "business_type_name": "치킨전문점",
    "channels": ["baemin", "coupangeats", "yogiyo", "naver_place"],
    "menu": ["후라이드", "양념치킨", "반반", "순살 치킨", "치즈볼", "콜라"],
    "data_origin": "synthetic",
}

SAMPLE_REVIEWS = [
    {
        "review_id": "rv_basak_001",
        "store_id": "store_basak",
        "channel": "baemin",
        "rating": 1,
        "text": "양념 소스를 따로 요청했는데 안 왔어요",
        "created_at": "2026-10-14T22:15:00+09:00",
        "order_ref": None,
        "input_method": "sample",
        "pii_masked": False,
        "status": "new",
        "data_origin": "synthetic",
    },
    {
        "review_id": "rv_basak_002",
        "store_id": "store_basak",
        "channel": "coupangeats",
        "rating": 2,
        "text": "치킨무가 빠져 있었어요. 치킨에 무가 없으면 어떡해요",
        "created_at": "2026-10-20T21:40:00+09:00",
        "order_ref": None,
        "input_method": "sample",
        "pii_masked": False,
        "status": "new",
        "data_origin": "synthetic",
    },
    {
        "review_id": "rv_basak_003",
        "store_id": "store_basak",
        "channel": "yogiyo",
        "rating": 2,
        "text": "콜라 시켰는데 누락됐네요",
        "created_at": "2026-10-27T22:30:00+09:00",
        "order_ref": None,
        "input_method": "sample",
        "pii_masked": False,
        "status": "new",
        "data_origin": "synthetic",
    },
]

SAMPLE_LABELS = [
    {
        "review_id": "rv_basak_001",
        "expected_sentiment": "negative",
        "expected_topics": [{"topic": "missing_item", "polarity": "negative"}],
        "note": "소스 누락",
    },
    {
        "review_id": "rv_basak_002",
        "expected_sentiment": "negative",
        "expected_topics": [{"topic": "missing_item", "polarity": "negative"}],
        "note": "무 누락",
    },
    {
        "review_id": "rv_basak_003",
        "expected_sentiment": "negative",
        "expected_topics": [{"topic": "missing_item", "polarity": "negative"}],
        "note": "음료 누락",
    },
]


class TestMergeLabels(unittest.TestCase):
    def test_sentiment_mapped(self):
        merged = _merge_labels(SAMPLE_REVIEWS, SAMPLE_LABELS)
        self.assertEqual(merged[0]["sentiment"], "negative")

    def test_topics_flat_list(self):
        merged = _merge_labels(SAMPLE_REVIEWS, SAMPLE_LABELS)
        self.assertEqual(merged[1]["topics"], ["missing_item"])

    def test_negative_topics_extracted(self):
        merged = _merge_labels(SAMPLE_REVIEWS, SAMPLE_LABELS)
        self.assertEqual(merged[2]["negative_topics"], ["missing_item"])

    def test_urgency_none(self):
        merged = _merge_labels(SAMPLE_REVIEWS, SAMPLE_LABELS)
        for rv in merged:
            self.assertIsNone(rv["urgency"])

    def test_no_label_defaults(self):
        merged = _merge_labels(SAMPLE_REVIEWS, [])
        self.assertIsNone(merged[0]["sentiment"])
        self.assertEqual(merged[0]["topics"], [])
        self.assertEqual(merged[0]["negative_topics"], [])

    def test_mixed_polarity(self):
        labels = [{
            "review_id": "rv_basak_001",
            "expected_sentiment": "mixed",
            "expected_topics": [
                {"topic": "taste", "polarity": "positive"},
                {"topic": "wait_time", "polarity": "negative"},
            ],
        }]
        merged = _merge_labels(SAMPLE_REVIEWS[:1], labels)
        self.assertEqual(merged[0]["topics"], ["taste", "wait_time"])
        self.assertEqual(merged[0]["negative_topics"], ["wait_time"])


class TestMapStore(unittest.TestCase):
    def test_defaults_added(self):
        mapped = _map_store(SAMPLE_STORE)
        self.assertEqual(mapped["city"], "서울")
        self.assertIsNone(mapped["area_name"])
        self.assertEqual(mapped["menu_prices"], {})

    def test_original_preserved(self):
        mapped = _map_store(SAMPLE_STORE)
        self.assertEqual(mapped["store_id"], "store_basak")
        self.assertEqual(mapped["name"], "바삭치킨 (가상)")


class TestMakeCards(unittest.TestCase):
    def test_repeated_complaint_card(self):
        classified = _merge_labels(SAMPLE_REVIEWS, SAMPLE_LABELS)
        cards = make_cards_from_c3(classified, "store_basak")
        complaint = [c for c in cards if c["kind"] == "complaint"]
        self.assertEqual(len(complaint), 1)
        self.assertIn("missing_item", complaint[0]["reason_text"])
        self.assertEqual(len(complaint[0]["review_ids"]), 3)

    def test_promo_card_always_present(self):
        classified = _merge_labels(SAMPLE_REVIEWS, SAMPLE_LABELS)
        cards = make_cards_from_c3(classified, "store_basak")
        promo = [c for c in cards if c["kind"] == "promo"]
        self.assertEqual(len(promo), 1)
        self.assertEqual(promo[0]["snapshot_ids"], ["snap_dummy_01"])

    def test_no_repeated_no_complaint_card(self):
        one_review = _merge_labels(SAMPLE_REVIEWS[:1], SAMPLE_LABELS[:1])
        cards = make_cards_from_c3(one_review, "store_basak")
        complaint = [c for c in cards if c["kind"] == "complaint"]
        self.assertEqual(len(complaint), 0)


class TestToCtx(unittest.TestCase):
    def test_full_team_data(self):
        raw = {
            "store": SAMPLE_STORE,
            "reviews": SAMPLE_REVIEWS,
            "labels": SAMPLE_LABELS,
        }
        ctx = to_ctx(raw)
        self.assertEqual(ctx["store"]["city"], "서울")
        self.assertEqual(len(ctx["reviews"]), 3)
        self.assertEqual(ctx["reviews"][0]["sentiment"], "negative")
        self.assertTrue(len(ctx["cards"]) >= 1)
        self.assertIn("tone", ctx)
        self.assertIn("owner_replies", ctx)
        self.assertIn("policies", ctx)
        self.assertIn("snapshots", ctx)
        for item in ctx["needs_input"]:
            self.assertIn("팀 데이터에 없음", item)

    def test_empty_raw(self):
        ctx = to_ctx({})
        self.assertIn("store", ctx["needs_input"])
        self.assertIn("reviews", ctx["needs_input"])

    def test_cards_auto_generated(self):
        raw = {
            "store": SAMPLE_STORE,
            "reviews": SAMPLE_REVIEWS,
            "labels": SAMPLE_LABELS,
        }
        ctx = to_ctx(raw)
        self.assertNotIn("cards", ctx["needs_input"])
        complaint = [c for c in ctx["cards"] if c["kind"] == "complaint"]
        self.assertEqual(len(complaint), 1)


if __name__ == "__main__":
    unittest.main()
