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
            self.assertIn("온기한식", one.read_text(encoding="utf-8"))  # \uXXXX로 깨지지 않음
            self.assertEqual(load_json(StoreProfile, one), SAMPLE_STORE)
            self.assertEqual(load_json(ReviewRecord, many), SAMPLE_REVIEWS)

    def test_unknown_and_missing_fields_are_named(self):
        data = SAMPLE_STORE.to_dict()
        with self.assertRaisesRegex(ValueError, "store_nmae"):
            StoreProfile.from_dict({**data, "store_nmae": "오타"})
        del data["name"]
        with self.assertRaisesRegex(ValueError, r"\['name'\]"):
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
    base = dict(review_id="rv_t1", store_id="store_t", text="맛있어요", created_at="2026-11-07T22:41:00+09:00")

    def test_created_at_stays_a_string_so_that_pr14_code_keeps_working(self):
        """PR #14의 cluster.py는 datetime.fromisoformat(r.created_at)처럼 문자열을 받아 쓴다."""
        record = ReviewRecord(**self.base)
        self.assertIsInstance(record.created_at, str)
        self.assertEqual(datetime.fromisoformat(record.created_at), record.created_datetime)

    def test_every_time_is_stored_as_kst_so_string_order_is_time_order(self):
        base = {k: v for k, v in self.base.items() if k != "created_at"}
        naive = ReviewRecord(**base, created_at="2026-11-07T22:41:00")
        utc = ReviewRecord(**base, created_at=datetime(2026, 11, 7, 13, 41, tzinfo=timezone.utc))
        self.assertEqual(naive.created_at, "2026-11-07T22:41:00+09:00")
        self.assertEqual(utc.created_at, "2026-11-07T22:41:00+09:00")
        early = ReviewRecord(**base, created_at="2026-11-07T09:05:00+09:00")
        late = ReviewRecord(**base, created_at="2026-11-07T10:00:00+09:00")
        self.assertEqual(sorted([late, early], key=lambda r: r.created_at), [early, late])
        self.assertEqual(naive.created_datetime.utcoffset(), timedelta(hours=9))

    def test_classification_is_empty_before_c3_and_values_are_checked_after(self):
        unclassified = ReviewRecord(**self.base)
        self.assertEqual((unclassified.sentiment, unclassified.topics, unclassified.urgency), (None, [], None))
        self.assertEqual(ReviewRecord(**self.base, sentiment="mixed").sentiment, "mixed")  # C3가 쓰는 값
        for field_name, bad in (("sentiment", "angry"), ("urgency", "urgent"), ("channel", "kakao"), ("rating", 6),
                                ("input_method", "typed"), ("status", "done"), ("pii_masked", "no")):
            with self.subTest(field=field_name), self.assertRaises(ValueError):
                ReviewRecord(**{**self.base, field_name: bad})

    def test_channel_and_rating_may_be_missing_for_pasted_reviews(self):
        pasted = ReviewRecord(**self.base, input_method="paste")
        self.assertEqual((pasted.channel, pasted.rating), (None, None))

    def test_all_four_delivery_channels_of_pr14_are_accepted(self):
        for channel in ("baemin", "coupangeats", "yogiyo", "naver_place"):
            ReviewRecord(**self.base, channel=channel)

    def test_negative_topics_must_be_part_of_topics(self):
        ReviewRecord(**self.base, topics=["taste", "portion"], negative_topics=["portion"])
        with self.assertRaisesRegex(ValueError, "negative_topics"):
            ReviewRecord(**self.base, topics=["taste"], negative_topics=["portion"])

    def test_bad_time_text_is_explained(self):
        with self.assertRaisesRegex(ValueError, "ISO 8601"):
            ReviewRecord(**{**self.base, "created_at": "어제 밤 11시"})


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


ROOT = Path(__file__).resolve().parents[1]
C2_DATA = ROOT / "services" / "review-insight" / "data" / "synthetic"   # PR #14가 병합되면 생김
C4_SNAPSHOT = ROOT / "data" / "scenario" / "snapshot_2026Q2.json"        # C4 고정 파일 대안(또는 어댑터 출력)


class RealScenarioData(unittest.TestCase):
    """다른 파트가 실제로 만든 데이터가 이 계약으로 읽히는가. 파일이 아직 없으면 건너뜁니다."""

    @unittest.skipUnless(C2_DATA.is_dir(), "C2 합성 데이터(PR #14)가 아직 없음")
    def test_c2_stores_and_reviews_load(self):
        stores = sorted(C2_DATA.glob("*/store.json"))
        self.assertTrue(stores, "store.json이 하나도 없습니다")
        for store_file in stores:
            with self.subTest(store=store_file.parent.name):
                store = load_json(StoreProfile, store_file)
                reviews = load_json(ReviewRecord, store_file.parent / "reviews.json")
                self.assertTrue(reviews)
                self.assertEqual({r.store_id for r in reviews}, {store.store_id})
                self.assertEqual(len({r.review_id for r in reviews}), len(reviews), "리뷰 ID가 겹칩니다")

    @unittest.skipUnless(C4_SNAPSHOT.is_file(), "C4 상권 지표 JSON이 아직 없음")
    def test_c4_snapshot_file_loads_and_each_metric_has_its_basis(self):
        snapshots = load_json(AnalysisSnapshot, C4_SNAPSHOT)
        self.assertIsInstance(snapshots, list, "스냅샷 JSON은 AnalysisSnapshot의 목록이어야 합니다")
        self.assertEqual(len({s.snapshot_id for s in snapshots}), len(snapshots))
        for s in snapshots:
            self.assertTrue(s.basis_label.startswith("기준: "))


if __name__ == "__main__":
    unittest.main()
