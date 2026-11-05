"""B5 original-file oracle for directions, denominator, gaps, and isolation."""
from collections import defaultdict
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.onboarding import OnboardingStore, create_onboarding_router
from tests.official_source_oracle import get_oracle, HISTORICAL_PERIODS
from app.onboarding_comparison import build_comparison_analysis, get_comparison_options
from app.onboarding_comparison import ComparisonDataError, ComparisonInputError
import app.onboarding_comparison as comparison_module


ROOT = Path(__file__).resolve().parents[1]
PERIODS = ("20252", "20261", "20262")
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


class IndependentComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.oracle = get_oracle()
        cls.version = cls.oracle.version
        cls.areas = cls.oracle.areas
        cls.rows, cls.proof = cls.oracle.rows, cls.oracle.proof
        cls.industry_names = cls.oracle.industry_names
        cls.store_areas = cls.oracle.legacy_areas

    @classmethod
    def selection(cls, area, industry, period):
        return {"area_code": area, "area_name": cls.areas[area]["name"], "industry_code": industry,
                "period": period, "period_label": f"{period[:4]}년 {period[-1]}분기", "catalog_version": cls.version,
                "boundary": {"publication_date": "2023-10-23", "compatibility": "unverified"}}

    @classmethod
    def profile(cls, industry):
        return {"industry": {"code": industry, "name": cls.industry_names[industry]}}

    def assert_report(self, base, target, industry, period, result):
        self.assertEqual(result["comparison_direction"], "comparison_minus_base")
        self.assertEqual(result["selection"]["area_code"], base)
        self.assertEqual(result["selection"]["industry_code"], industry)
        self.assertEqual(result["selection"]["period"], period)
        metrics = {metric["key"]: metric for metric in result["metrics"]}
        self.assertEqual(set(metrics), set(METRICS))
        for key, (dataset, field, unit) in METRICS.items():
            actual = metrics[key]
            identities = [(area, None if dataset == "population" else industry, period) for area in (base, target)]
            rows = [self.rows[dataset].get(identity) for identity in identities]
            values = [int(row[field]) if row is not None else None for row in rows]
            self.assertEqual(actual["unit"], unit)
            self.assertEqual(actual["industry_applied"], dataset != "population")
            self.assertEqual(actual["source"]["field"], field)
            self.assertEqual(actual["source"]["url"], f"https://data.seoul.go.kr/dataList/{SOURCES[dataset]}/S/1/datasetView.do")
            for side, value, identity in zip(("base", "comparison"), values, identities):
                self.assertEqual(actual[side]["value"], value, (key, side))
                self.assertEqual(actual[side]["value_text"], str(value) if value is not None else None)
                if value is not None:
                    self.assertEqual(actual[side]["status"], "available")
                    proof = self.proof[dataset][identity]
                    self.assertIn(proof, [(entry["file_name"], entry["file_sha256"], entry["payload_sha256"]) for entry in actual["evidence"][side]])
            if None in values:
                self.assertEqual(actual["status"], "unavailable")
                self.assertIsNone(actual["delta"])
                self.assertIsNone(actual["delta_text"])
                self.assertIsNone(actual["percent"])
                self.assertEqual(actual["percent_status"], "unavailable")
            else:
                difference = values[1] - values[0]
                self.assertEqual(actual["status"], "available")
                self.assertEqual(actual["delta"], difference)
                self.assertEqual(actual["delta_text"], str(difference))
                self.assertEqual(actual["percent"], signed_percent_oracle(difference, values[0]))
                self.assertEqual(actual["percent_status"], "available" if values[0] else "undefined_zero_base")

    def test_all_ten_store_areas_three_quarters_three_industries_match_originals(self):
        self.assertEqual(len(self.store_areas), 10)
        self.assertEqual([len(self.rows["sales"].subset(periods=HISTORICAL_PERIODS)), len(self.oracle.legacy_stores), len(self.rows["population"].subset(periods=HISTORICAL_PERIODS))], [63773, 1941, 4946])
        count = 0
        for index, base in enumerate(self.store_areas):
            target = self.store_areas[(index + 1) % len(self.store_areas)]
            for period in PERIODS:
                for industry in ("CS100010", "CS100001", "CS200041"):
                    with self.subTest(base=base, target=target, period=period, industry=industry):
                        result = build_comparison_analysis(self.selection(base, industry, period), self.profile(industry), target)
                        self.assert_report(base, target, industry, period, result)
                        count += 1
        self.assertEqual(count, 90)

    def test_seven_actual_zero_total_bases_have_defined_difference_but_no_percentage(self):
        count = 0
        for (base, industry, period), row in self.oracle.legacy_stores.items():
            if row["SIMILR_INDUTY_STOR_CO"] != 0:
                continue
            target = next(area for area in self.store_areas if area != base
                          and (area, industry, period) in self.rows["stores"]
                          and self.rows["stores"][(area, industry, period)]["SIMILR_INDUTY_STOR_CO"] > 0)
            result = build_comparison_analysis(self.selection(base, industry, period), self.profile(industry), target)
            self.assert_report(base, target, industry, period, result)
            metric = next(item for item in result["metrics"] if item["key"] == "stores_total")
            self.assertEqual(metric["base"]["value"], 0)
            self.assertGreater(metric["delta"], 0)
            self.assertIsNone(metric["percent"])
            count += 1
        self.assertEqual(count, 7)

    def test_expanded_area_keeps_source_store_status_and_available_sales_population(self):
        outside = next(code for code, area in self.areas.items() if area["name"] == "압구정로데오역(압구정로데오)")
        base, industry = "3110562", "CS100010"
        for period in PERIODS:
            result = build_comparison_analysis(self.selection(base, industry, period), self.profile(industry), outside)
            self.assert_report(base, outside, industry, period, result)
            metrics = {item["key"]: item for item in result["metrics"]}
            self.assertEqual(metrics["sales"]["status"], "available")
            self.assertEqual(metrics["floating_population"]["status"], "available")
            if not self.oracle.is_collected("stores", outside, period):
                self.assertEqual(metrics["stores_total"]["comparison"]["status"], "not_collected")
                self.assertIsNone(metrics["stores_total"]["delta"])
            elif (outside, industry, period) in self.rows["stores"]:
                self.assertEqual(metrics["stores_total"]["status"], "available")

    def test_reversing_areas_reverses_difference_and_changes_percentage_denominator(self):
        base, target, industry, period = "3110562", "3001491", "CS100010", "20262"
        forward = build_comparison_analysis(self.selection(base, industry, period), self.profile(industry), target)
        reverse = build_comparison_analysis(self.selection(target, industry, period), self.profile(industry), base)
        self.assert_report(base, target, industry, period, forward)
        self.assert_report(target, base, industry, period, reverse)
        for a, b in zip(forward["metrics"], reverse["metrics"]):
            if a["delta"] is not None:
                self.assertEqual(a["delta"], -b["delta"])
        a = next(item for item in forward["metrics"] if item["key"] == "sales")
        b = next(item for item in reverse["metrics"] if item["key"] == "sales")
        self.assertNotEqual(abs(a["percent"]), abs(b["percent"]))

    def test_options_are_official_distinct_and_block_known_identity_conflicts(self):
        base, industry, period = "3110562", "CS100010", "20262"
        selection = self.selection(base, industry, period)
        options = get_comparison_options(selection, self.profile(industry))
        areas = {area["area_code"]: area for area in options["areas"]}
        self.assertEqual(set(areas), set(self.areas) - {base})
        self.assertEqual(len(options["districts"]), 25)
        self.assertEqual({code for code, area in areas.items() if not area["selectable"]}, {"3110024", "3110379"})
        self.assertTrue(all("geometry" not in area for area in areas.values()))
        for invalid in (base, "9999999", "3110024", "3110379"):
            with self.assertRaises(ComparisonInputError):
                build_comparison_analysis(selection, self.profile(industry), invalid)

    def test_synthetic_zero_denominator_for_each_of_the_seven_metrics(self):
        base, target, industry, period = "3110562", "3001491", "CS100010", "20262"
        selection, profile = self.selection(base, industry, period), self.profile(industry)
        fixtures = {}
        for dataset in SERVICES:
            reader = getattr(comparison_module, "build_" + dataset + "_analysis")
            fixtures[dataset] = {area: reader(self.selection(area, industry, period), profile) for area in (base, target)}

        def controlled_reader(dataset, target_value):
            def read(conditions, _profile):
                result = deepcopy(fixtures[dataset][conditions["area_code"]])
                value = 0 if conditions["area_code"] == base else target_value
                observations = result["counts"].values() if dataset == "stores" else [result["total"]]
                for observed in observations:
                    observed.update(status="available", value=value, value_text=str(value))
                return result
            return read

        for target_value in (0, 5):
            with patch.object(comparison_module, "build_sales_analysis", controlled_reader("sales", target_value)), \
                    patch.object(comparison_module, "build_stores_analysis", controlled_reader("stores", target_value)), \
                    patch.object(comparison_module, "build_population_analysis", controlled_reader("population", target_value)):
                result = build_comparison_analysis(selection, profile, target)
            for metric in result["metrics"]:
                self.assertEqual(metric["status"], "available")
                self.assertEqual(metric["delta"], target_value)
                self.assertEqual(metric["delta_text"], str(target_value))
                self.assertIsNone(metric["percent"])
                self.assertEqual(metric["percent_status"], "undefined_zero_base")

    def test_incompatible_units_period_definitions_and_population_scope_fail_closed(self):
        base, target, industry, period = "3110562", "3001491", "CS100010", "20262"
        selection, profile = self.selection(base, industry, period), self.profile(industry)
        cases = (("sales", "source", "unit", "천원"), ("sales", "selection", "period", "20261"),
                 ("stores", "source", "period_basis", "month"), ("population", "source", "aggregation_basis", "daily_average"),
                 ("population", None, "industry_applied", True))
        for dataset, group, field, value in cases:
            original_reader = getattr(comparison_module, "build_" + dataset + "_analysis")
            def changed_reader(conditions, original_profile, reader=original_reader, group=group, field=field, value=value):
                result = deepcopy(reader(conditions, original_profile))
                (result[group] if group else result)[field] = value
                return result
            with self.subTest(dataset=dataset, field=field), \
                    patch.object(comparison_module, "build_" + dataset + "_analysis", changed_reader), \
                    self.assertRaises(ComparisonDataError):
                build_comparison_analysis(selection, profile, target)

    def test_memory_http_comparison_does_not_replace_saved_base_and_requires_current_revision(self):
        store = OnboardingStore(":memory:")
        app = FastAPI()
        app.include_router(create_onboarding_router(store))
        try:
            with TestClient(app) as client, \
                    patch("socket.create_connection", side_effect=AssertionError("No live network")), \
                    patch("app.naver_clients.MapsClient.geocode", side_effect=AssertionError("No live map")), \
                    patch("app.config.load_settings", side_effect=AssertionError("No credentials")):
                revision = client.get("/api/onboarding/profile").json()["revision"]
                response = client.post("/api/onboarding/profile", json={"location": {"kind": "area", "district_code": "11440", "neighborhood_code": "11440710"},
                    "industry_code": "CS100001", "business_status": "planning", "expected_revision": revision})
                self.assertEqual(response.status_code, 200, response.text)
                options = client.get("/api/onboarding/analysis-options").json()
                revision = client.get("/api/onboarding/profile").json()["revision"]
                response = client.post("/api/onboarding/analysis-selection", json={"area_code": "3110562", "period": "20262",
                    "expected_revision": revision, "expected_catalog_version": options["catalog_version"]})
                self.assertEqual(response.status_code, 200, response.text)
                before = client.get("/api/onboarding/analysis-selection").json()
                profile_before = client.get("/api/onboarding/profile").json()
                comparison_options = client.get("/api/onboarding/comparison-options", params={"expected_revision": before["revision"]})
                self.assertEqual(comparison_options.status_code, 200, comparison_options.text)
                for target in ("3001491", "3110127"):
                    report = client.get("/api/onboarding/comparison", params={"comparison_area_code": target, "expected_revision": before["revision"]})
                    self.assertEqual(report.status_code, 200, report.text)
                    self.assert_report("3110562", target, "CS100001", "20262", report.json())
                    self.assertEqual(client.get("/api/onboarding/analysis-selection").json(), before)
                    self.assertEqual(client.get("/api/onboarding/profile").json(), profile_before)
                self.assertEqual(client.get("/api/onboarding/comparison", params={"comparison_area_code": "3001491", "expected_revision": before["revision"] - 1}).status_code, 409)
                self.assertEqual(client.get("/api/onboarding/comparison", params={"comparison_area_code": "3001491", "period": "20261"}).status_code, 422)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
