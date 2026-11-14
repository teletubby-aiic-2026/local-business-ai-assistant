"""B6 exact-period original-file oracle, including absent-period and zero cases."""
from collections import defaultdict
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.onboarding import OnboardingStore, create_onboarding_router
from tests.official_source_oracle import get_oracle, HISTORICAL_PERIODS
from app.onboarding_changes import build_changes_analysis
import app.onboarding_changes as changes_module
from app.onboarding_comparison import ComparisonDataError
import app.onboarding_population as population_module


ROOT = Path(__file__).resolve().parents[1]
PERIODS = {"qoq": "20261", "yoy": "20252"}
METRICS = {
    "sales": ("sales", "THSMON_SELNG_AMT", "원"),
    "stores_total": ("stores", "SIMILR_INDUTY_STOR_CO", "개"),
    "stores_general": ("stores", "STOR_CO", "개"),
    "stores_franchise": ("stores", "FRC_STOR_CO", "개"),
    "stores_opened": ("stores", "OPBIZ_STOR_CO", "개"),
    "stores_closed": ("stores", "CLSBIZ_STOR_CO", "개"),
    "floating_population": ("population", "TOT_FLPOP_CO", "명"),
}
SOURCES = {"sales": "OA-15572", "stores": "OA-15577", "population": "OA-15568"}
SERVICES = {"sales": "VwsmTrdarSelngQq", "stores": "VwsmTrdarStorQq", "population": "VwsmTrdarFlpopQq"}


def signed_percent_oracle(delta, denominator):
    if denominator == 0:
        return None
    quotient, remainder = divmod(abs(delta) * 10000, denominator)
    value = (quotient + (2 * remainder >= denominator)) / 100
    return -value if delta < 0 else value


class IndependentChangesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.oracle = get_oracle()
        cls.version = cls.oracle.version
        cls.areas = cls.oracle.areas
        cls.rows, cls.proof = cls.oracle.rows, cls.oracle.proof
        cls.names, cls.collected = cls.oracle.industry_names, cls.oracle.collected
        cls.store_areas = cls.oracle.legacy_areas

    @classmethod
    def selection(cls, area, industry, period):
        return {"area_code": area, "area_name": cls.areas[area]["name"], "industry_code": industry,
                "period": period, "period_label": f"{period[:4]}년 {period[-1]}분기", "catalog_version": cls.version,
                "boundary": {"publication_date": "2023-10-23", "compatibility": "unverified"}}

    @classmethod
    def profile(cls, industry):
        return {"industry": {"code": industry, "name": cls.names[industry]}}

    def assert_report(self, area, industry, current, previous, mode, result):
        self.assertEqual(result["comparison"], mode)
        self.assertEqual(result["comparison_direction"], "current_minus_previous")
        self.assertEqual(result["current_period"]["code"], current)
        self.assertEqual(result["previous_period"]["code"], previous)
        self.assertEqual(result["selection"]["area_code"], area)
        self.assertEqual(result["selection"]["industry_code"], industry)
        self.assertEqual(result["selection"]["period"], current)
        metrics = {item["key"]: item for item in result["metrics"]}
        self.assertEqual(set(metrics), set(METRICS))
        for key, (dataset, field, unit) in METRICS.items():
            metric = metrics[key]
            identities = [(area, None if dataset == "population" else industry, period) for period in (current, previous)]
            rows = [self.rows[dataset].get(identity) for identity in identities]
            values = [int(row[field]) if row is not None else None for row in rows]
            self.assertEqual(metric["unit"], unit)
            self.assertEqual(metric["source"]["field"], field)
            self.assertEqual(metric["source"]["url"], f"https://data.seoul.go.kr/dataList/{SOURCES[dataset]}/S/1/datasetView.do")
            for side, value, identity in zip(("current", "previous"), values, identities):
                self.assertEqual(metric[side]["value"], value)
                self.assertEqual(metric[side]["value_text"], str(value) if value is not None else None)
                collected = self.oracle.is_collected(dataset, area, identity[2])
                self.assertEqual(result["period_collection"][side][dataset], collected)
                if value is not None:
                    self.assertEqual(metric[side]["status"], "available")
                    self.assertIn(self.proof[dataset][identity], [(entry["file_name"], entry["file_sha256"], entry["payload_sha256"]) for entry in metric["evidence"][side]])
                elif not collected:
                    self.assertEqual(metric[side]["status"], "not_collected")
                    self.assertIsNone(result["data_versions"][side][dataset])
            if None in values:
                self.assertEqual(metric["status"], "unavailable")
                self.assertIsNone(metric["delta"])
                self.assertIsNone(metric["delta_text"])
                self.assertIsNone(metric["percent"])
                self.assertEqual(metric["percent_status"], "unavailable")
            else:
                difference = values[0] - values[1]
                self.assertEqual(metric["status"], "available")
                self.assertEqual(metric["delta"], difference)
                self.assertEqual(metric["delta_text"], str(difference))
                self.assertEqual(metric["percent"], signed_percent_oracle(difference, values[1]))
                self.assertEqual(metric["percent_status"], "available" if values[1] else "undefined_zero_previous")

    def test_ten_areas_three_industries_exact_qoq_yoy_match_seven_original_metrics(self):
        self.assertEqual(len(self.store_areas), 10)
        count = 0
        for area in self.store_areas:
            for industry in ("CS100010", "CS100001", "CS200041"):
                for mode, previous in PERIODS.items():
                    with self.subTest(area=area, industry=industry, mode=mode):
                        result = build_changes_analysis(self.selection(area, industry, "20262"), self.profile(industry), mode)
                        self.assert_report(area, industry, "20262", previous, mode, result)
                        count += 1
        self.assertEqual(count, 60)

    def test_missing_exact_previous_period_is_not_replaced_with_available_quarter(self):
        area, industry = "3110562", "CS100010"
        for current, mode, previous in (("20261", "qoq", "20254"), ("20261", "yoy", "20251"),
                                        ("20252", "qoq", "20251"), ("20252", "yoy", "20242")):
            result = build_changes_analysis(self.selection(area, industry, current), self.profile(industry), mode)
            self.assert_report(area, industry, current, previous, mode, result)
            if all(not self.oracle.is_collected(dataset, area, previous) for dataset in SERVICES):
                self.assertEqual(result["status"], "no_comparison")
                self.assertTrue(all(metric["previous"]["status"] == "not_collected" for metric in result["metrics"]))
            self.assertTrue(all(metric["current"]["value"] is not None for metric in result["metrics"]))

    def test_uncollected_exact_period_fixture_never_falls_back_after_expansion(self):
        selection, profile = self.selection("3110562", "CS100010", "20262"), self.profile("CS100010")
        original_source, area = changes_module._base_context(selection, profile)
        for mode, previous in PERIODS.items():
            source = deepcopy(original_source)
            source["files"] = [entry for entry in source["files"] if entry["period"] != previous]
            with patch.object(changes_module, "_base_context", return_value=(source, area)):
                result = build_changes_analysis(selection, profile, mode)
            self.assertEqual(result["previous_period"]["code"], previous)
            self.assertEqual(result["status"], "no_comparison")
            for metric in result["metrics"]:
                self.assertEqual(metric["previous"]["status"], "not_collected")
                self.assertIsNone(metric["previous"]["value"])
                self.assertIsNone(metric["delta"])
                self.assertIsNone(metric["percent"])
                self.assertIsNotNone(metric["current"]["value"])

    def test_dataset_period_scope_fixture_keeps_other_metrics_available(self):
        selection, profile = self.selection("3110562", "CS100010", "20262"), self.profile("CS100010")
        source, area = changes_module._base_context(selection, profile)
        source = deepcopy(source)
        source["files"] = [entry for entry in source["files"] if not (entry["dataset"] == "stores" and entry["period"] == "20261")]
        with patch.object(changes_module, "_base_context", return_value=(source, area)):
            result = build_changes_analysis(selection, profile, "qoq")
        metrics = {metric["key"]: metric for metric in result["metrics"]}
        self.assertEqual(metrics["sales"]["status"], "available")
        self.assertEqual(metrics["floating_population"]["status"], "available")
        self.assertEqual(metrics["stores_total"]["previous"]["status"], "not_collected")
        self.assertIsNone(metrics["stores_total"]["delta"])

    def test_diverse_real_positive_negative_unchanged_and_previous_zero_cases(self):
        cases, represented = set(), set()
        for mode, previous in PERIODS.items():
            for key, (dataset, field, _unit) in METRICS.items():
                found = set()
                for area, industry, period in self.rows[dataset]:
                    if period != "20262" or area in ("3110024", "3110379") or (dataset == "stores" and area not in self.store_areas):
                        continue
                    row = self.rows[dataset][(area, industry, period)]
                    older = self.rows[dataset].get((area, industry, previous))
                    if older is None:
                        continue
                    delta = int(row[field]) - int(older[field])
                    categories = {"positive" if delta > 0 else "negative" if delta < 0 else "unchanged"}
                    if older[field] == 0:
                        categories.add("previous_zero")
                    if older[field] == row[field] == 0:
                        categories.add("both_zero")
                    if categories - found:
                        cases.add((area, industry or "CS100010", mode))
                        represented.update((mode, key, category) for category in categories)
                        found.update(categories)
                    if len(found) == 5:
                        break
        for area, industry, mode in sorted(cases):
            result = build_changes_analysis(self.selection(area, industry, "20262"), self.profile(industry), mode)
            self.assert_report(area, industry, "20262", PERIODS[mode], mode, result)
        for mode in PERIODS:
            for key in METRICS:
                self.assertIn((mode, key, "positive"), represented)
                self.assertIn((mode, key, "negative"), represented)
            for key in ("stores_general", "stores_franchise", "stores_opened", "stores_closed"):
                self.assertIn((mode, key, "both_zero"), represented)
            self.assertNotIn((mode, "stores_total", "previous_zero"), represented)

    def test_expanded_stores_follow_actual_scope_with_sales_and_population_changes(self):
        area = next(code for code, row in self.areas.items() if row["name"] == "압구정로데오역(압구정로데오)")
        industry = "CS100010"
        for mode, previous in PERIODS.items():
            result = build_changes_analysis(self.selection(area, industry, "20262"), self.profile(industry), mode)
            self.assert_report(area, industry, "20262", previous, mode, result)
            metrics = {item["key"]: item for item in result["metrics"]}
            self.assertEqual(metrics["sales"]["status"], "available")
            self.assertEqual(metrics["floating_population"]["status"], "available")
            for side, period in (("current", "20262"), ("previous", previous)):
                if not self.oracle.is_collected("stores", area, period):
                    self.assertEqual(metrics["stores_total"][side]["status"], "not_collected")
                elif (area, industry, period) in self.rows["stores"]:
                    self.assertEqual(metrics["stores_total"][side]["status"], "available")

    def test_prior_zero_total_row_with_current_row_absent_does_not_invent_growth(self):
        for area, industry, previous, mode in (("3110520", "CS200024", "20261", "qoq"),
                                                ("3001496", "CS300037", "20252", "yoy")):
            self.assertEqual(self.rows["stores"][(area, industry, previous)]["SIMILR_INDUTY_STOR_CO"], 0)
            self.assertNotIn((area, industry, "20262"), self.rows["stores"])
            result = build_changes_analysis(self.selection(area, industry, "20262"), self.profile(industry), mode)
            self.assert_report(area, industry, "20262", previous, mode, result)
            metric = next(item for item in result["metrics"] if item["key"] == "stores_total")
            self.assertIsNone(metric["current"]["value"])
            self.assertEqual(metric["previous"]["value"], 0)
            self.assertIsNone(metric["delta"])
            self.assertEqual(metric["percent_status"], "unavailable")

    def test_synthetic_zero_previous_for_all_metrics_and_different_source_versions(self):
        area, industry = "3110562", "CS100010"
        selection, profile = self.selection(area, industry, "20262"), self.profile(industry)
        fixtures = {}
        for dataset in SERVICES:
            reader = getattr(changes_module, "build_" + dataset + "_analysis")
            fixtures[dataset] = {period: reader(self.selection(area, industry, period), profile) for period in ("20262", "20261")}
            self.assertNotEqual(fixtures[dataset]["20262"]["data_version"], fixtures[dataset]["20261"]["data_version"])

        def controlled_reader(dataset, current_value):
            def read(conditions, _profile):
                result = deepcopy(fixtures[dataset][conditions["period"]])
                value = current_value if conditions["period"] == "20262" else 0
                observations = result["counts"].values() if dataset == "stores" else [result["total"]]
                for observed in observations:
                    observed.update(status="available", value=value, value_text=str(value))
                return result
            return read

        for current_value in (0, 5):
            with patch.object(changes_module, "build_sales_analysis", controlled_reader("sales", current_value)), \
                    patch.object(changes_module, "build_stores_analysis", controlled_reader("stores", current_value)), \
                    patch.object(changes_module, "build_population_analysis", controlled_reader("population", current_value)):
                result = build_changes_analysis(selection, profile, "qoq")
            self.assertEqual(result["status"], "complete")
            for metric in result["metrics"]:
                self.assertEqual(metric["delta"], current_value)
                self.assertEqual(metric["delta_text"], str(current_value))
                self.assertIsNone(metric["percent"])
                self.assertEqual(metric["percent_status"], "undefined_zero_previous")

    def test_incompatible_units_sources_and_population_definition_are_rejected(self):
        area, industry = "3110562", "CS100010"
        cases = (("sales", "source", "unit", "천원"), ("sales", "source", "url", "https://example.invalid/unverified"),
                 ("stores", "source", "period_basis", "month"), ("population", "source", "aggregation_basis", "daily_average"),
                 ("population", None, "industry_applied", True))
        for dataset, group, field, value in cases:
            original_reader = getattr(changes_module, "build_" + dataset + "_analysis")
            def changed_reader(conditions, original_profile, reader=original_reader, group=group, field=field, value=value):
                result = deepcopy(reader(conditions, original_profile))
                (result[group] if group else result)[field] = value
                return result
            with self.subTest(dataset=dataset, field=field), \
                    patch.object(changes_module, "build_" + dataset + "_analysis", changed_reader), \
                    self.assertRaises(ComparisonDataError):
                build_changes_analysis(self.selection(area, industry, "20262"), self.profile(industry), "qoq")

    def saved_http(self):
        store = OnboardingStore(":memory:")
        app = FastAPI()
        app.include_router(create_onboarding_router(store))
        client = TestClient(app)
        revision = client.get("/api/onboarding/profile").json()["revision"]
        response = client.post("/api/onboarding/profile", json={"location": {"kind": "area", "district_code": "11440", "neighborhood_code": "11440710"},
            "industry_code": "CS100010", "business_status": "planning", "expected_revision": revision})
        self.assertEqual(response.status_code, 200, response.text)
        options = client.get("/api/onboarding/analysis-options").json()
        revision = client.get("/api/onboarding/profile").json()["revision"]
        response = client.post("/api/onboarding/analysis-selection", json={"area_code": "3110562", "period": "20262",
            "expected_revision": revision, "expected_catalog_version": options["catalog_version"]})
        self.assertEqual(response.status_code, 200, response.text)
        return store, client, response.json()

    def test_memory_http_modes_match_originals_without_changing_saved_selection(self):
        with patch("socket.create_connection", side_effect=AssertionError("No live network")), \
                patch("app.naver_clients.MapsClient.geocode", side_effect=AssertionError("No live map")), \
                patch("app.config.load_settings", side_effect=AssertionError("No credentials")):
            store, client, saved = self.saved_http()
            try:
                before = client.get("/api/onboarding/analysis-selection").json()
                profile_before = client.get("/api/onboarding/profile").json()
                for mode, previous in PERIODS.items():
                    response = client.get("/api/onboarding/changes", params={"comparison": mode, "expected_revision": saved["revision"]})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assert_report("3110562", "CS100010", "20262", previous, mode, response.json())
                    self.assertEqual(client.get("/api/onboarding/analysis-selection").json(), before)
                    self.assertEqual(client.get("/api/onboarding/profile").json(), profile_before)
                self.assertEqual(client.get("/api/onboarding/changes", params={"comparison": "qoq", "expected_revision": saved["revision"] - 1}).status_code, 409)
                self.assertEqual(client.get("/api/onboarding/changes", params={"comparison": "monthly"}).status_code, 422)
                self.assertEqual(client.get("/api/onboarding/changes", params={"comparison": "yoy", "period": "20261"}).status_code, 422)
            finally:
                client.close()
                store.close()

    def test_copied_tampered_source_is_503_not_an_uncollected_period(self):
        with patch("socket.create_connection", side_effect=AssertionError("No live network")), \
                patch("app.naver_clients.MapsClient.geocode", side_effect=AssertionError("No live map")), \
                patch("app.config.load_settings", side_effect=AssertionError("No credentials")):
            store, client, saved = self.saved_http()
            try:
                with TemporaryDirectory(prefix="onboarding-b6-source-") as directory:
                    copied = Path(directory)
                    for path in (ROOT / "data/raw/official").glob("population_*_all_*.json"):
                        shutil.copyfile(path, copied / path.name)
                    target = copied / "population_20262_all_1_1000.json"
                    target.write_bytes(target.read_bytes() + b" ")
                    with patch.object(population_module, "_RAW", copied):
                        response = client.get("/api/onboarding/changes", params={"comparison": "qoq", "expected_revision": saved["revision"]})
                    self.assertEqual(response.status_code, 503, response.text)
                response = client.get("/api/onboarding/changes", params={"comparison": "qoq", "expected_revision": saved["revision"]})
                self.assertEqual(response.status_code, 200, response.text)
                self.assert_report("3110562", "CS100010", "20262", "20261", "qoq", response.json())
            finally:
                client.close()
                store.close()


if __name__ == "__main__":
    unittest.main()
