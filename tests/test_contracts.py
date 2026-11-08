"""shared.contracts 검증. 저장소 루트에서: python -m unittest tests.test_contracts -v"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shared.contracts import (
    CARD_GENERATORS, CARD_KINDS, LABELS_KO, AnalysisSnapshot, RecommendationCard, ReviewRecord,
    StoreProfile, ToneProfile, dump_json, load_json, quarter_from_seoul_period, quarter_label,
)
from shared.sample_scenario import (
    SAMPLE_CARDS, SAMPLE_REVIEWS, SAMPLE_SNAPSHOTS, SAMPLE_STORE, SAMPLE_TONE, sample_bundle,
)


def snapshot(**overrides) -> AnalysisSnapshot:
    base = dict(
        snapshot_id="snap_t1", area_name="테스트 상권", metric_name="저녁 추정매출 변화율", value=-12.5,
        unit="%", basis_quarter="2026Q2", is_estimate=True, source="서울시",
    )
    base.update(overrides)
    return AnalysisSnapshot(**base)


class JsonRoundTrip(unittest.TestCase):
    def test_every_sample_survives_json(self):
        everything = [SAMPLE_STORE, SAMPLE_TONE, *SAMPLE_REVIEWS, *SAMPLE_SNAPSHOTS, *SAMPLE_CARDS]
        for record in everything:
            with self.subTest(record=type(record).__name__):
                text = json.dumps(record.to_dict(), ensure_ascii=False)
                self.assertEqual(type(record).from_dict(json.loads(text)), record)

    def test_sample_bundle_is_pure_json(self):
        json.dumps(sample_bundle(), ensure_ascii=False)  # datetime 등이 남아 있으면 여기서 실패

    def test_dump_and_load_file_keep_korean_and_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            one, many = Path(tmp) / "one.json", Path(tmp) / "many.json"
            dump_json(SAMPLE_STORE, one)
            dump_json(SAMPLE_REVIEWS, many)
            self.assertIn("보라 치킨", one.read_text(encoding="utf-8"))  # \uXXXX로 깨지지 않음
            self.assertEqual(load_json(StoreProfile, one), SAMPLE_STORE)
            self.assertEqual(load_json(ReviewRecord, many), SAMPLE_REVIEWS)

    def test_unknown_and_missing_fields_are_named(self):
        data = SAMPLE_STORE.to_dict()
        with self.assertRaisesRegex(ValueError, "store_nmae"):
            StoreProfile.from_dict({**data, "store_nmae": "오타"})
        del data["area_name"]
        with self.assertRaisesRegex(ValueError, "area_name"):
            StoreProfile.from_dict(data)


class AnalysisSnapshotRules(unittest.TestCase):
    def test_basis_label_matches_the_screen_text(self):
        self.assertEqual(snapshot().basis_label, "기준: 2026 2분기 · 추정 · 출처 서울시")
        self.assertEqual(snapshot(is_estimate=False).basis_label, "기준: 2026 2분기 · 출처 서울시")

    def test_basis_quarter_estimate_and_source_are_required(self):
        for missing in ("basis_quarter", "is_estimate", "source"):
            with self.subTest(missing=missing):
                data = snapshot().to_dict()
                del data[missing]
                with self.assertRaisesRegex(ValueError, missing):
                    AnalysisSnapshot.from_dict(data)

    def test_bad_basis_quarter_is_rejected(self):
        for bad in ("20262", "2026-2Q", "2026Q5", "2026", "", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                snapshot(basis_quarter=bad)

    def test_empty_source_and_non_bool_estimate_are_rejected(self):
        with self.assertRaises(ValueError):
            snapshot(source="  ")
        with self.assertRaises(ValueError):
            snapshot(is_estimate="true")

    def test_none_is_no_data_and_zero_is_a_value(self):
        self.assertIsNone(snapshot(value=None).value)
        self.assertEqual(snapshot(value=0).value, 0)

    def test_nan_is_rejected_so_that_no_data_stays_none(self):
        with self.assertRaisesRegex(ValueError, "None"):
            snapshot(value=float("nan"))

    def test_seoul_period_converts_to_quarter(self):
        self.assertEqual(quarter_from_seoul_period("20262"), "2026Q2")
        self.assertEqual(quarter_label("2026Q2"), "2026 2분기")
        with self.assertRaises(ValueError):
            quarter_from_seoul_period("2026Q2")


class ReviewRecordRules(unittest.TestCase):
    base = dict(review_id="rv_t1", store_id="store_t", channel="baemin", text="맛있어요")

    def test_iso_string_is_parsed_and_naive_time_is_treated_as_kst(self):
        aware = ReviewRecord(**self.base, written_at="2026-11-07T22:41:00+09:00")
        naive = ReviewRecord(**self.base, written_at="2026-11-07T22:41:00")
        self.assertEqual(aware.written_at, naive.written_at)
        self.assertEqual(naive.written_at.utcoffset(), timedelta(hours=9))

    def test_naive_and_aware_reviews_can_be_sorted_together(self):
        a = ReviewRecord(**self.base, written_at=datetime(2026, 11, 7, 23, 0))
        b = ReviewRecord(**self.base, written_at=datetime(2026, 11, 7, 22, 0, tzinfo=timezone.utc))
        sorted([a, b], key=lambda r: r.written_at)  # TypeError가 나지 않아야 함

    def test_classification_is_optional_but_checked_when_given(self):
        unclassified = ReviewRecord(**self.base, written_at="2026-11-07T22:41:00+09:00")
        self.assertEqual((unclassified.topic, unclassified.sentiment, unclassified.urgency), (None, None, None))
        for field_name, bad in (("sentiment", "angry"), ("urgency", "urgent"), ("channel", "kakao"), ("rating", 6)):
            with self.subTest(field=field_name), self.assertRaises(ValueError):
                ReviewRecord(**{**self.base, field_name: bad}, written_at="2026-11-07T22:41:00+09:00")

    def test_bad_time_text_is_explained(self):
        with self.assertRaisesRegex(ValueError, "ISO 8601"):
            ReviewRecord(**self.base, written_at="어제 밤 11시")


class RecommendationCardRules(unittest.TestCase):
    def test_a_card_without_evidence_cannot_exist(self):
        with self.assertRaisesRegex(ValueError, "근거"):
            RecommendationCard(card_id="card_t", store_id="store_t", kind="complaint", reason_text="이유")

    def test_kind_must_be_a_known_kind(self):
        with self.assertRaises(ValueError):
            RecommendationCard(card_id="c", store_id="s", kind="event", reason_text="이유", review_ids=["rv_1"])

    def test_a_single_string_is_not_accepted_as_an_id_list(self):
        with self.assertRaises(ValueError):
            RecommendationCard(card_id="c", store_id="s", kind="complaint", reason_text="이유", review_ids="rv_1")

    def test_evidence_ids_joins_both_lists(self):
        card = RecommendationCard(
            card_id="c", store_id="s", kind="complaint", reason_text="이유", review_ids=["rv_1"], snapshot_ids=["snap_1"]
        )
        self.assertEqual(card.evidence_ids, ["rv_1", "snap_1"])

    def test_generator_table_covers_exactly_the_card_kinds(self):
        self.assertEqual(set(CARD_GENERATORS), set(CARD_KINDS))
        self.assertEqual(CARD_GENERATORS["complaint"], ("reply_draft", "prevention_notice"))
        self.assertEqual(CARD_GENERATORS["promo"], ("coupon_promo",))
        for generators in CARD_GENERATORS.values():
            self.assertTrue(all(isinstance(name, str) for name in generators))  # 함수가 아니라 이름

    def test_every_code_value_has_a_korean_label(self):
        for kind in CARD_KINDS:
            self.assertIn(kind, LABELS_KO)


class SampleScenario(unittest.TestCase):
    def test_card_evidence_ids_exist_in_the_sample_data(self):
        """C5가 쓸 '근거 ID가 실제로 존재하는가' 검사의 모양."""
        review_ids = {r.review_id for r in SAMPLE_REVIEWS}
        snapshot_ids = {s.snapshot_id for s in SAMPLE_SNAPSHOTS}
        for card in SAMPLE_CARDS:
            self.assertLessEqual(set(card.review_ids), review_ids)
            self.assertLessEqual(set(card.snapshot_ids), snapshot_ids)

    def test_sample_ids_do_not_collide_across_records(self):
        ids = [SAMPLE_STORE.store_id, SAMPLE_TONE.tone_id]
        ids += [r.review_id for r in SAMPLE_REVIEWS] + [s.snapshot_id for s in SAMPLE_SNAPSHOTS]
        ids += [c.card_id for c in SAMPLE_CARDS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_sample_records_belong_to_the_sample_store(self):
        for record in [SAMPLE_TONE, *SAMPLE_REVIEWS, *SAMPLE_CARDS]:
            self.assertEqual(record.store_id, SAMPLE_STORE.store_id)

    def test_sample_covers_both_card_kinds_with_the_wow_shape(self):
        self.assertEqual({c.kind for c in SAMPLE_CARDS}, set(CARD_KINDS))
        complaint = next(c for c in SAMPLE_CARDS if c.kind == "complaint")
        self.assertEqual(len(complaint.review_ids), 3)  # 포장 누락 3건


if __name__ == "__main__":
    unittest.main()
