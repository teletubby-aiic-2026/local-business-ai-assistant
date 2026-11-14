"""Independent B4 source audit and exhaustive value/denominator comparison.

The expectation parser does not reuse application fields, math, or loaders.
HTTP uses a memory-only router, with credentials and live providers prohibited.
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
from tests.official_source_oracle import get_oracle, HISTORICAL_PERIODS, PopulationPairs
from app.onboarding_population import analyze_population_row, build_population_analysis


ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://data.seoul.go.kr/dataList/OA-15568/S/1/datasetView.do"
TOTAL = "TOT_FLPOP_CO"
GROUPS = {
    "time": [(label, "TMZON_" + value + "_FLPOP_CO") for label, value in zip(
        ("00~06시", "06~11시", "11~14시", "14~17시", "17~21시", "21~24시"),
        ("00_06", "06_11", "11_14", "14_17", "17_21", "21_24"))],
    "age": [(label, "AGRDE_" + value + "_FLPOP_CO") for label, value in zip(
        ("연령대 10 (원천 분류)", "연령대 20", "연령대 30", "연령대 40", "연령대 50", "연령대 60 이상"),
        ("10", "20", "30", "40", "50", "60_ABOVE"))],
}
AUDIT_GROUPS = {**{key: [field for _, field in fields] for key, fields in GROUPS.items()},
    "gender": ["ML_FLPOP_CO", "FML_FLPOP_CO"],
    "weekday": [day + "_FLPOP_CO" for day in ("MON", "TUES", "WED", "THUR", "FRI", "SAT", "SUN")]}
FIELDS = [TOTAL] + [field for fields in GROUPS.values() for _, field in fields]
PERIODS = ("20252", "20261", "20262")


def percent_oracle(value, denominator):
    if denominator == 0:
        return None
    quotient, remainder = divmod(value * 10000, denominator)
    return (quotient + (2 * remainder >= denominator)) / 100


class IndependentPopulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.oracle = get_oracle()
        cls.version = cls.oracle.version
        cls.rows = PopulationPairs(cls.oracle.rows["population"])
        cls.proof = PopulationPairs(cls.oracle.proof["population"])

    @classmethod
    def selection(cls, row, industry="CS100010"):
        period = row["STDR_YYQU_CD"]
        return {"area_code": row["TRDAR_CD"], "area_name": row["TRDAR_CD_NM"], "industry_code": industry,
                "period": period, "period_label": f"{period[:4]}년 {period[-1]}분기", "catalog_version": cls.version,
                "boundary": {"publication_date": "2023-10-23", "compatibility": "unverified"}}

    def assert_actual_row(self, row, result):
        total = int(row[TOTAL])
        self.assertEqual(result["status"], "available")
        self.assertIs(result["industry_applied"], False)
        self.assertEqual(result["population_scope"], "area_wide")
        self.assertEqual((result["total"]["value"], result["total"]["value_text"], result["total"]["unit"]), (total, str(total), "명"))
        for kind, fields in GROUPS.items():
            group = result["distributions"][kind]
            values = [int(row[field]) for _, field in fields]
            difference = sum(values) - total
            consistent = difference == 0
            self.assertEqual(group["status"], "complete" if consistent else "inconsistent")
            self.assertEqual(group["sum"], sum(values))
            self.assertEqual(group["total_difference"], difference)
            self.assertEqual(group["denominator"]["kind"], "source_total")
            self.assertEqual(group["denominator"]["value"], total)
            self.assertEqual(group["denominator"]["value_text"], str(total))
            self.assertEqual(len(group["items"]), 6)
            for item, (label, field), value in zip(group["items"], fields, values):
                self.assertEqual((item["label"], item["field"], item["status"], item["value"], item["value_text"]),
                                 (label, field, "available", value, str(value)))
                self.assertEqual(item["share_percent"], percent_oracle(value, total) if consistent else None)
            ranking = group["ranking"]
            self.assertEqual(ranking["status"], "available" if consistent else "unavailable")
            self.assertEqual(ranking["highest"], [label for (label, _), value in zip(fields, values) if value == max(values)] if consistent else [])
            self.assertEqual(ranking["lowest"], [label for (label, _), value in zip(fields, values) if value == min(values)] if consistent else [])
            self.assertEqual(ranking["highest_value"], max(values) if consistent else None)
            self.assertEqual(ranking["lowest_value"], min(values) if consistent else None)

    def test_independent_full_source_audit_all_four_marginals(self):
        historical = PopulationPairs(self.oracle.rows["population"].subset(periods=HISTORICAL_PERIODS))
        self.assertEqual(len(historical), 4946)
        self.assertEqual(Counter(key[1] for key in historical), {"20252": 1649, "20261": 1649, "20262": 1648})
        self.assertEqual(len({key[0] for key in historical}), 1649)
        self.assertEqual((min(row[TOTAL] for row in historical.values()), max(row[TOTAL] for row in historical.values())), (46, 8537311))
        expected = {
            "time": (1557, 1637, 1752, 14, 0, 5, -4, 4),
            "age": (1546, 1549, 1851, 21, 0, 9, -5, 4),
            "gender": (2479, 1187, 1280, 3, 0, 0, -3, 3),
            "weekday": (1411, 1645, 1890, 12, 13, 15, -4, 5),
        }
        for kind, fields in AUDIT_GROUPS.items():
            counts, differences = Counter(), []
            for row in historical.values():
                total = row[TOTAL]
                self.assertGreater(total, 0)
                values = [row[field] for field in fields]
                self.assertTrue(all(type(value) in (int, float) and value >= 0 and value % 1 == 0 for value in [total, *values]))
                difference = sum(values) - total
                differences.append(difference)
                counts["equal" if difference == 0 else "below" if difference < 0 else "above"] += 1
                counts["zero_items"] += values.count(0)
                counts["highest_tie"] += values.count(max(values)) > 1
                counts["lowest_tie"] += values.count(min(values)) > 1
            actual = tuple(counts[key] for key in ("equal", "below", "above", "zero_items", "highest_tie", "lowest_tie")) + (min(differences), max(differences))
            self.assertEqual(actual, expected[kind], kind)

    def test_all_active_actual_rows_keep_values_and_withhold_unverified_ratios(self):
        for key, row in self.rows.items():
            with self.subTest(key=key):
                self.assert_actual_row(row, analyze_population_row(row, self.selection(row), "커피-음료"))

    def test_loader_samples_cover_all_active_pages_and_periods(self):
        for area, _industry, period in self.oracle.loader_samples("population"):
            key = (area, period)
            row = self.rows[key]
            with self.subTest(key=key):
                result = build_population_analysis(self.selection(row), {"industry": {"code": "CS100010", "name": "커피-음료"}})
                self.assert_actual_row(row, result)
                evidence = {item["file_name"]: item for item in result["evidence"]}
                self.assertEqual(len(evidence), sum(entry["dataset"] == "population" and entry["period"] == key[1] for entry in self.oracle.files))
                file_name, file_hash, payload_hash = self.proof[key]
                self.assertEqual((evidence[file_name]["file_sha256"], evidence[file_name]["payload_sha256"]), (file_hash, payload_hash))
                self.assertEqual(set(evidence[file_name]["fields"]), set(FIELDS))
                self.assertEqual(result["source"]["url"], SOURCE_URL)
                self.assertEqual(result["source"]["aggregation_basis"], "source_total")
                self.assertIs(result["source"]["definition_verified"], False)

    def test_same_area_period_is_industry_independent_in_values_and_data_version(self):
        for period in PERIODS:
            row = self.rows[("3110562", period)]
            reports = [build_population_analysis(self.selection(row, code), {"industry": {"code": code, "name": name}})
                       for code, name in (("CS100010", "커피-음료"), ("CS100002", "중식음식점"), ("CS200009", "동물병원"))]
            for report in reports[1:]:
                for field in ("total", "distributions", "data_version", "source", "evidence", "summary", "warnings"):
                    self.assertEqual(report[field], reports[0][field])

    def test_actual_absent_rows_are_null_not_zero_or_other_period(self):
        for area, name, periods in (("3110946", "청계산원터골", PERIODS),
                                    ("3111002", "한국교통안전공단 강남자동차검사소", ("20262",))):
            for period in periods:
                self.assertNotIn((area, period), self.rows)
                row = {"TRDAR_CD": area, "TRDAR_CD_NM": name, "STDR_YYQU_CD": period}
                result = build_population_analysis(self.selection(row), {"industry": {"code": "CS100010", "name": "커피-음료"}})
                self.assertEqual(result["observation_status"], "no_observation")
                self.assertEqual(result["status"], "no_data")
                self.assertIsNone(result["total"]["value"])
                self.assertEqual(len(result["evidence"]), 2)
                for group in result["distributions"].values():
                    self.assertEqual(group["status"], "no_data")
                    self.assertTrue(all(item["value"] is None and item["share_percent"] is None for item in group["items"]))
        self.assertIn(("3111002", "20261"), self.rows)

    def test_actual_small_total_zero_components_and_unmatched_sum(self):
        row = self.rows[("3110948", "20252")]
        result = analyze_population_row(row, self.selection(row), "커피-음료")
        self.assert_actual_row(row, result)
        self.assertEqual(result["total"]["value"], 46)
        self.assertEqual([item["value"] for item in result["distributions"]["time"]["items"]], [0, 24, 12, 10, 0, 0])
        row = self.rows[("3110562", "20261")]
        result = analyze_population_row(row, self.selection(row), "커피-음료")
        self.assertEqual(result["total"]["value"], 1103359)
        self.assertEqual(result["distributions"]["time"]["status"], "complete")
        self.assertEqual(result["distributions"]["age"]["sum"], 1103355)
        self.assertEqual(result["distributions"]["age"]["total_difference"], -4)
        self.assertEqual(result["distributions"]["age"]["ranking"]["highest"], [])

    def test_synthetic_zero_ties_missing_invalid_and_not_collected(self):
        original = next(iter(self.rows.values()))
        selection = self.selection(original)
        zeros = {**original, **dict.fromkeys(FIELDS, 0)}
        result = analyze_population_row(zeros, selection, "커피-음료")
        self.assertEqual(result["status"], "available")
        for group in result["distributions"].values():
            self.assertEqual(group["status"], "complete")
            self.assertEqual(len(group["ranking"]["highest"]), 6)
            self.assertTrue(all(item["value"] == 0 and item["share_percent"] is None for item in group["items"]))
        for value, status in ((None, "partial"), (-1, "invalid"), (float("nan"), "invalid")):
            result = analyze_population_row({**original, "TMZON_00_06_FLPOP_CO": value}, selection, "커피-음료")
            self.assertEqual(result["distributions"]["time"]["status"], status)
            self.assertTrue(all(item["share_percent"] is None for item in result["distributions"]["time"]["items"]))
        result = analyze_population_row(None, selection, "커피-음료", collected=False)
        self.assertEqual(result["observation_status"], "not_collected")
        self.assertIsNone(result["total"]["value"])

    def test_memory_http_noncoffee_three_quarters_reads_source_without_mutation(self):
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
                    "industry_code": "CS100002", "business_status": "planning", "expected_revision": revision})
                self.assertEqual(response.status_code, 200, response.text)
                options = client.get("/api/onboarding/analysis-options").json()
                for period in PERIODS:
                    revision = client.get("/api/onboarding/profile").json()["revision"]
                    response = client.post("/api/onboarding/analysis-selection", json={"area_code": "3110562", "period": period,
                        "expected_revision": revision, "expected_catalog_version": options["catalog_version"]})
                    self.assertEqual(response.status_code, 200, response.text)
                    before = client.get("/api/onboarding/analysis-selection").json()
                    report = client.get("/api/onboarding/population", params={"expected_revision": before["revision"]})
                    self.assertEqual(report.status_code, 200, report.text)
                    self.assert_actual_row(self.rows[("3110562", period)], report.json())
                    self.assertEqual(client.get("/api/onboarding/analysis-selection").json(), before)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
