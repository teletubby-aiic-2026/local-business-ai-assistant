"""Independent B1 source-to-result checks using retained official input rows.

Expected availability is derived here from the original response envelopes and
numeric fields, not the application's builder, cache or published ten-area demo.
No network, environment or user profile storage is used.
"""
from collections import defaultdict
from functools import lru_cache
import json
import math
from pathlib import Path
import unittest
from hashlib import sha256
from tempfile import TemporaryDirectory
from tests.official_source_oracle import get_oracle, AvailabilityValues, Oracle, source_url

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "official"


@lru_cache(maxsize=1)
def independent_sources():
    oracle = get_oracle()
    rows = AvailabilityValues(oracle)
    collected = defaultdict(set)
    areas = {}
    for path in RAW.glob("areas_none_all_*.json"):
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
        for row in doc["payload"]["TbgisTrdarRelm"]["row"]:
            areas[row["TRDAR_CD"]] = row
    for dataset, scope, period in oracle.collected:
        metric = "floating_population" if dataset == "population" else dataset
        collected[(metric, period)].add(scope)
    periods = sorted({period for values in oracle.periods.values() for period in values}, reverse=True)
    return areas, rows, collected, periods


class IndependentAvailabilityTests(unittest.TestCase):
    def test_all_observed_industry_pairs_and_unobserved_pairs_match_raw(self):
        from app.onboarding_analysis_catalog import get_area_availability
        areas, rows, scopes, periods = independent_sources()
        industries = json.loads((ROOT / "app/onboarding_industries.json").read_text(encoding="utf-8"))["industries"]
        pairs = {(key[2], key[3]) for key in rows if key[3] is not None}
        # Add a missing industry in every area, so successful-row checks cannot
        # conceal an implementation that treats missing combinations as zero.
        for area in areas:
            missing = next((item["code"] for item in industries if (area, item["code"]) not in pairs), None)
            if missing:
                pairs.add((area, missing))
        mismatched_boundary_names = {"3110024", "3110379"}
        checks = 0
        for area, industry in sorted(pairs):
            result = get_area_availability(area, industry)
            by_period = {entry["code"]: entry for entry in result["periods"]}
            self.assertEqual(set(by_period), set(periods), (area, industry))
            expected_periods = []
            for period in periods:
                found = []
                for metric in ("sales", "stores", "floating_population"):
                    key = (metric, period, area, None if metric == "floating_population" else industry)
                    scope = scopes[(metric, period)]
                    if area in mismatched_boundary_names:
                        expected = "unavailable"
                    elif None not in scope and area not in scope:
                        expected = "not_collected"
                    elif key not in rows:
                        expected = "no_observation"
                    else:
                        expected = "available" if rows[key] is not None else "unavailable"
                    actual = by_period[period]["metrics"][metric]
                    self.assertEqual(actual["status"], expected, (key, actual))
                    self.assertEqual(actual["industry_specific"], metric != "floating_population")
                    if expected == "available":
                        self.assertEqual(bool(actual.get("zero_observation")), rows[key] == 0, key)
                    found.append(expected == "available")
                    checks += 1
                self.assertEqual(by_period[period]["available"], any(found))
                if any(found):
                    expected_periods.append(period)
            self.assertEqual(result["available_periods"], expected_periods, (area, industry))
        print(f"Independent availability: {len(pairs)} area/industry pairs, {checks} metric-period checks")

    def test_full_geometry_catalogue_keeps_source_codes_and_seoul_bounds(self):
        from app.onboarding_analysis_catalog import get_analysis_areas
        areas, _, _, _ = independent_sources()
        result = get_analysis_areas()
        self.assertEqual(len(result), 1650)
        self.assertEqual({row["area_code"] for row in result}, set(areas))
        for row in result:
            self.assertEqual(row["name"], areas[row["area_code"]]["TRDAR_CD_NM"])
            geometry = row["geometry"]
            self.assertIn(geometry["type"], ("Polygon", "MultiPolygon"))
            polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
            for polygon in polygons:
                for ring in polygon:
                    self.assertGreaterEqual(len(ring), 4)
                    self.assertEqual(ring[0], ring[-1])
                    for lon, lat in ring:
                        self.assertTrue(126 < lon < 128 and 37 < lat < 38.5)


class IndependentSourceIntegrityTests(unittest.TestCase):
    """Small synthetic envelopes keep collection failures testable after growth."""
    def row(self, industry="CS100001", count=0):
        return {"TRDAR_CD": "3110562", "TRDAR_CD_NM": "연트럴파크(연남동주민센터)", "STDR_YYQU_CD": "20262",
                "SVC_INDUTY_CD": industry, "SVC_INDUTY_CD_NM": industry,
                "SIMILR_INDUTY_STOR_CO": count, "STOR_CO": count, "FRC_STOR_CO": 0,
                "OPBIZ_STOR_CO": 0, "CLSBIZ_STOR_CO": 0, "OPBIZ_RT": 0, "CLSBIZ_RT": 0}

    def write_page(self, root, rows, *, scope=None, start=1, total=None, count=2):
        total = len(rows) if total is None else total
        payload = {"VwsmTrdarStorQq": {"RESULT": {"CODE": "INFO-000"}, "list_total_count": total, "row": rows}}
        doc = {"query": {"dataset": "stores", "period": "20262", "area_code": scope, "start": start, "count": count},
               "service": "VwsmTrdarStorQq", "sample_only": False, "source_url": source_url("stores"), "payload": payload,
               "payload_sha256": sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
        path = root / f"stores_20262_{scope or 'all'}_{start}_{start+count-1}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return path, doc

    def test_complete_citywide_overlap_is_counted_once_and_observed_zero_preserved(self):
        with TemporaryDirectory(prefix="onboarding-source-oracle-") as directory:
            root = Path(directory)
            rows = [self.row(), self.row("CS100002", 3)]
            self.write_page(root, rows, scope="3110562")
            self.write_page(root, rows)
            oracle = Oracle(root, None)
            self.assertEqual(len(oracle.rows["stores"]), 2)
            self.assertEqual(oracle.overlap, {"20262": 2})
            self.assertEqual(oracle.rows["stores"][("3110562", "CS100001", "20262")]["SIMILR_INDUTY_STOR_CO"], 0)
            self.assertTrue(oracle.is_collected("stores", "9999999", "20262"))

    def test_incomplete_citywide_never_falls_back_to_complete_legacy(self):
        with TemporaryDirectory(prefix="onboarding-source-oracle-") as directory:
            root = Path(directory)
            self.write_page(root, [self.row()], scope="3110562")
            self.write_page(root, [self.row(), self.row("CS100002")], total=3)
            with self.assertRaises(AssertionError):
                Oracle(root, None)

    def test_duplicate_identity_on_later_page_is_rejected(self):
        with TemporaryDirectory(prefix="onboarding-source-oracle-") as directory:
            root = Path(directory)
            self.write_page(root, [self.row(), self.row("CS100002")], total=3)
            self.write_page(root, [self.row()], start=3, total=3)
            with self.assertRaises(AssertionError):
                Oracle(root, None)

    def test_legacy_value_change_and_added_row_both_require_explicit_review(self):
        for changed_value in (True, False):
            with self.subTest(changed_value=changed_value), TemporaryDirectory(prefix="onboarding-source-oracle-") as directory:
                root = Path(directory)
                self.write_page(root, [self.row()], scope="3110562")
                rows = [self.row(count=1)] if changed_value else [self.row(), self.row("CS100002")]
                self.write_page(root, rows)
                with self.assertRaises(AssertionError):
                    Oracle(root, None)

    def test_missing_page_and_conflicting_total_are_rejected(self):
        for start, total in ((4, 4), (3, 4)):
            with self.subTest(start=start), TemporaryDirectory(prefix="onboarding-source-oracle-") as directory:
                root = Path(directory)
                self.write_page(root, [self.row(), self.row("CS100002")], total=3)
                rows = [self.row("CS100003")] if start == 4 else [self.row("CS100003"), self.row("CS100004")]
                self.write_page(root, rows, start=start, total=total)
                with self.assertRaises(AssertionError):
                    Oracle(root, None)

    def test_payload_and_manifest_file_hash_changes_are_rejected(self):
        with TemporaryDirectory(prefix="onboarding-source-oracle-") as directory:
            root = Path(directory)
            path, doc = self.write_page(root, [self.row()])
            doc["payload"]["VwsmTrdarStorQq"]["row"][0]["STOR_CO"] = 2
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(AssertionError):
                Oracle(root, None)
            path, doc = self.write_page(root, [self.row()])
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"catalog_version": "fixture", "areas": [], "source": {"files": [{
                "path": "data/raw/official/" + path.name, "dataset": "stores", "period": "20262", "area_code": None,
                "start": 1, "row_count": 1, "file_sha256": "0" * 64, "payload_sha256": doc["payload_sha256"]}]}}), encoding="utf-8")
            with self.assertRaises(AssertionError):
                Oracle(root, manifest)


if __name__ == "__main__":
    unittest.main()
