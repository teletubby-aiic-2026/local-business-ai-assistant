"""B3 expectations read independently from the preserved official store pages.

Full raw-row coverage, integer-only ratio oracle, and a memory-only HTTP journey.
No intake_api import, credentials, persistent database, or provider calls.
"""
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.onboarding import OnboardingStore, create_onboarding_router
from tests.official_source_oracle import get_oracle, HISTORICAL_PERIODS
from app.onboarding_stores import analyze_stores_row, build_stores_analysis


ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://data.seoul.go.kr/dataList/OA-15577/S/1/datasetView.do"
FIELDS = {"total": "SIMILR_INDUTY_STOR_CO", "general": "STOR_CO", "franchise": "FRC_STOR_CO",
          "opened": "OPBIZ_STOR_CO", "closed": "CLSBIZ_STOR_CO"}
PERIODS = ("20252", "20261", "20262")


def percent_oracle(numerator, denominator):
    if denominator == 0:
        return None
    quotient, remainder = divmod(numerator * 10000, denominator)
    return (quotient + (2 * remainder >= denominator)) / 100


class IndependentStoresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.oracle = get_oracle()
        cls.version = cls.oracle.version
        cls.areas = cls.oracle.areas
        cls.rows = cls.oracle.rows["stores"]
        cls.proof = cls.oracle.proof["stores"]
        cls.names = cls.oracle.industry_names
        cls.legacy = cls.oracle.legacy_stores
        cls.buckets = defaultdict(list)
        for key in cls.rows:
            cls.buckets[(key[0], key[2])].append(key)
        cls.area_counts = Counter(period for _area, period in cls.buckets)

    @classmethod
    def selection(cls, row):
        period = row["STDR_YYQU_CD"]
        return {"area_code": row["TRDAR_CD"], "area_name": row["TRDAR_CD_NM"],
                "industry_code": row["SVC_INDUTY_CD"], "period": period,
                "period_label": f"{period[:4]}년 {period[-1]}분기", "catalog_version": cls.version,
                "boundary": {"publication_date": "2023-10-23", "compatibility": "unverified"}}

    def assert_actual_row(self, row, result):
        self.assertEqual(result["status"], "available")
        for key, field in FIELDS.items():
            observed = result["counts"][key]
            expected = int(row[field])
            self.assertEqual((observed["field"], observed["status"], observed["value"], observed["value_text"], observed["unit"]),
                             (field, "available", expected, str(expected), "개"))
        total = int(row[FIELDS["total"]])
        composition = result["composition"]
        self.assertEqual(composition["status"], "consistent")
        self.assertEqual(composition["sum"], int(row[FIELDS["general"]]) + int(row[FIELDS["franchise"]]))
        self.assertEqual(composition["difference"], 0)
        self.assertEqual(composition["denominator"]["value"], total)
        self.assertEqual(composition["denominator"]["value_text"], str(total))
        self.assertEqual(composition["franchise_share_percent"], percent_oracle(int(row[FIELDS["franchise"]]), total))

    def test_independent_full_source_audit_counts_zeros_and_composition(self):
        self.assertEqual(len(self.legacy), 1941)
        self.assertEqual(Counter(key[2] for key in self.legacy), {"20252": 649, "20261": 646, "20262": 646})
        self.assertEqual(len({key[0] for key in self.legacy}), 10)
        for period in PERIODS:
            self.assertEqual(len({key[1] for key in self.legacy if key[2] == period}), 100)
        zeros, ties = Counter(), Counter()
        for row in self.legacy.values():
            for key, field in FIELDS.items():
                value = row[field]
                self.assertTrue(type(value) in (int, float) and value >= 0 and value % 1 == 0)
                zeros[key] += value == 0
            self.assertEqual(row[FIELDS["total"]], row[FIELDS["general"]] + row[FIELDS["franchise"]])
            ties["composition"] += row[FIELDS["general"]] == row[FIELDS["franchise"]]
            ties["composition_positive"] += row[FIELDS["general"]] == row[FIELDS["franchise"]] > 0
            ties["opened_closed"] += row[FIELDS["opened"]] == row[FIELDS["closed"]]
            ties["opened_closed_positive"] += row[FIELDS["opened"]] == row[FIELDS["closed"]] > 0
        self.assertEqual(dict(zeros), {"total": 7, "general": 49, "franchise": 1437, "opened": 1609, "closed": 1574})
        self.assertEqual(dict(ties), {"composition": 22, "composition_positive": 15, "opened_closed": 1469, "opened_closed_positive": 55})

    def test_all_active_actual_rows_match_independent_counts_and_denominator(self):
        for key, row in self.rows.items():
            with self.subTest(key=key):
                self.assert_actual_row(row, analyze_stores_row(row, self.selection(row), row["SVC_INDUTY_CD_NM"]))

    def test_file_loader_samples_cover_all_active_pages_and_industries(self):
        for key in self.oracle.loader_samples("stores"):
            row = self.rows[key]
            with self.subTest(key=key):
                result = build_stores_analysis(self.selection(row), {"industry": {"code": key[1], "name": row["SVC_INDUTY_CD_NM"]}})
                self.assert_actual_row(row, result)
                self.assertIn(self.proof[key], [(entry["file_name"], entry["file_sha256"], entry["payload_sha256"]) for entry in result["evidence"]])
                evidence = next(entry for entry in result["evidence"] if entry["file_name"] == self.proof[key][0])
                self.assertEqual(set(evidence["fields"]), set(FIELDS.values()))
                self.assertEqual((result["source"]["url"], result["source"]["period_basis"], result["source"]["collected_area_count"]), (SOURCE_URL, "quarter", self.area_counts[key[2]]))

    def test_actual_zero_and_closures_above_current_stock_remain_observations(self):
        rows = [row for row in self.legacy.values() if row[FIELDS["total"]] == 0 or row[FIELDS["closed"]] > row[FIELDS["total"]]]
        self.assertEqual(sum(row[FIELDS["closed"]] > row[FIELDS["total"]] for row in self.legacy.values()), 8)
        for row in rows:
            self.assert_actual_row(row, analyze_stores_row(row, self.selection(row), row["SVC_INDUTY_CD_NM"]))
        row = self.rows[("3110562", "CS100002", "20261")]
        self.assertEqual([row[field] for field in FIELDS.values()], [1, 1, 0, 1, 2])
        self.assertEqual(row["CLSBIZ_RT"], 200)
        result = analyze_stores_row(row, self.selection(row), row["SVC_INDUTY_CD_NM"])
        self.assertNotIn("closure_rate", result)
        self.assertTrue(any("임의 계산" in warning for warning in result["warnings"]))

    def test_actual_no_observation_and_uncollected_period_are_distinct_from_zero(self):
        # Fixed historical areas bound the HTTP-reader workload. Expected row
        # absence is derived from the active all-or-area source, not assumed.
        for area in self.oracle.legacy_areas:
            for period in self.oracle.periods["stores"]:
                keys = self.buckets.get((area, period), [])
                if not keys:
                    continue
                code = next((code for code in self.names if (area, code, period) not in self.rows), None)
                if code is None:
                    continue
                original = self.rows[keys[0]]
                row = {**original, "SVC_INDUTY_CD": code, "SVC_INDUTY_CD_NM": self.names[code]}
                result = build_stores_analysis(self.selection(row), {"industry": {"code": code, "name": self.names[code]}})
                self.assertEqual(result["status"], "no_observation")
                self.assertTrue(result["evidence"])
                self.assertTrue(all(item["status"] == "no_observation" and item["value"] is None for item in result["counts"].values()))
        period = "20001"
        self.assertNotIn(period, self.oracle.periods["stores"])
        original = next(iter(self.rows.values()))
        row = {**original, "STDR_YYQU_CD": period}
        result = build_stores_analysis(self.selection(row), {"industry": {"code": row["SVC_INDUTY_CD"], "name": row["SVC_INDUTY_CD_NM"]}})
        self.assertEqual(result["status"], "not_collected")
        self.assertEqual(result["evidence"], [])
        self.assertTrue(all(item["status"] == "not_collected" and item["value"] is None for item in result["counts"].values()))

    def test_opening_minus_closure_is_not_equivalent_to_actual_stock_change(self):
        outcomes = Counter()
        for (area, industry, period), row in self.legacy.items():
            if period != "20262":
                continue
            previous = self.legacy.get((area, industry, "20261"))
            if previous is None:
                outcomes["previous_absent"] += 1
                continue
            stock_change = row[FIELDS["total"]] - previous[FIELDS["total"]]
            events = row[FIELDS["opened"]] - row[FIELDS["closed"]]
            outcomes["equal" if stock_change == events else "different"] += 1
        self.assertEqual(dict(outcomes), {"equal": 620, "different": 25, "previous_absent": 1})

    def test_missing_invalid_and_inconsistent_composition_do_not_invent_a_share(self):
        original = next(iter(self.rows.values()))
        selection = self.selection(original)
        for changes, expected in (({"STOR_CO": None}, "incomplete"), ({"FRC_STOR_CO": -1}, "incomplete"),
                                  ({"SIMILR_INDUTY_STOR_CO": 7, "STOR_CO": 2, "FRC_STOR_CO": 3}, "inconsistent")):
            result = analyze_stores_row({**original, **changes}, selection, original["SVC_INDUTY_CD_NM"])
            self.assertEqual(result["composition"]["status"], expected)
            self.assertIsNone(result["composition"]["franchise_share_percent"])

    def test_noncoffee_http_three_quarters_matches_original_and_does_not_save(self):
        store = OnboardingStore(":memory:")
        app = FastAPI()
        app.include_router(create_onboarding_router(store))
        try:
            with TestClient(app) as client, \
                    patch("socket.create_connection", side_effect=AssertionError("No live network")), \
                    patch("app.naver_clients.MapsClient.geocode", side_effect=AssertionError("No live map")), \
                    patch("app.config.load_settings", side_effect=AssertionError("No credentials")):
                initial = client.get("/api/onboarding/profile").json()
                saved = client.post("/api/onboarding/profile", json={"location": {"kind": "area", "district_code": "11440", "neighborhood_code": "11440710"},
                    "industry_code": "CS100002", "business_status": "planning", "expected_revision": initial["revision"]})
                self.assertEqual(saved.status_code, 200, saved.text)
                options = client.get("/api/onboarding/analysis-options").json()
                self.assertIn("3110562", {candidate["area_code"] for candidate in options["candidates"]})
                for period in PERIODS:
                    revision = client.get("/api/onboarding/profile").json()["revision"]
                    response = client.post("/api/onboarding/analysis-selection", json={"area_code": "3110562", "period": period,
                        "expected_revision": revision, "expected_catalog_version": options["catalog_version"]})
                    self.assertEqual(response.status_code, 200, response.text)
                    before = client.get("/api/onboarding/analysis-selection").json()
                    report = client.get("/api/onboarding/stores", params={"expected_revision": before["revision"]})
                    self.assertEqual(report.status_code, 200, report.text)
                    self.assert_actual_row(self.rows[("3110562", "CS100002", period)], report.json())
                    self.assertEqual(report.json()["feature"], "stores")
                    self.assertEqual(client.get("/api/onboarding/analysis-selection").json(), before)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
