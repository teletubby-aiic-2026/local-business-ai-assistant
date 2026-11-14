"""B4 source totals/distributions, provenance and read-only HTTP boundaries."""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from app import onboarding_population as population
from app.data_repository import SOURCE_URLS, canonical_hash
from app.onboarding import COOKIE_NAME, ProfileInput
from tests import test_onboarding_analysis as setup_helpers


def selection():
    return {"area_code": "1111111", "area_name": "합성 상권 1111111", "industry_code": "CS100010",
        "period": "20262", "period_label": "2026년 2분기", "catalog_version": "synthetic-catalogue-v1",
        "boundary": {"publication_date": "2023-10-23", "compatibility": "unverified"}}


def row_fixture():
    row = {"STDR_YYQU_CD": "20262", "TRDAR_CD": "1111111", "TRDAR_CD_NM": "합성 상권 1111111", "TOT_FLPOP_CO": 120}
    for kind, values in (("time", (10, 20, 30, 30, 20, 10)), ("age", (0, 0, 60, 60, 0, 0))):
        for (_label, field), value in zip(population._GROUPS[kind][1], values):
            row[field] = value
    return row


def analyze(row, **kwargs):
    return population.analyze_population_row(row, selection(), "커피-음료", **kwargs)


class PopulationSemanticsTests(unittest.TestCase):
    def test_source_total_and_distribution_denominators_remain_area_wide(self):
        result = analyze(row_fixture())
        self.assertEqual(result["total"]["value"], 120)
        self.assertEqual(result["total"]["value_text"], "120")
        self.assertFalse(result["industry_applied"])
        self.assertEqual(result["population_scope"], "area_wide")
        for dist in result["distributions"].values():
            self.assertEqual(dist["denominator"]["kind"], "source_total")
            self.assertEqual(dist["denominator"]["value"], 120)
            self.assertEqual(dist["sum"], 120)
            self.assertEqual(dist["total_difference"], 0)
        self.assertEqual(result["distributions"]["age"]["items"][2]["share_percent"], 50.0)

    def test_all_ties_are_returned_without_combining_time_and_age(self):
        result = analyze(row_fixture())
        self.assertEqual(result["distributions"]["time"]["ranking"]["highest"], ["11~14시", "14~17시"])
        age = result["distributions"]["age"]
        self.assertEqual(age["ranking"]["highest"], ["연령대 30", "연령대 40"])
        self.assertEqual(len(age["ranking"]["lowest"]), 4)
        self.assertEqual(set(result["distributions"]), {"time", "age"})

    def test_even_one_unit_sum_difference_blocks_shares_and_rankings_but_not_total(self):
        for kind in ("time", "age"):
            for delta in (-1, 1):
                row = row_fixture()
                row[population._GROUPS[kind][1][2][1]] += delta
                result = analyze(row)
                dist = result["distributions"][kind]
                self.assertEqual(result["total"]["value"], 120)
                self.assertEqual(dist["status"], "inconsistent")
                self.assertEqual(dist["total_difference"], delta)
                self.assertEqual(dist["ranking"]["status"], "unavailable")
                self.assertTrue(all(item["share_percent"] is None for item in dist["items"]))

    def test_missing_item_does_not_become_zero_or_a_partial_ranking(self):
        row = row_fixture()
        row.pop("AGRDE_10_FLPOP_CO")
        dist = analyze(row)["distributions"]["age"]
        self.assertEqual(dist["status"], "partial")
        self.assertEqual(dist["items"][0]["status"], "missing")
        self.assertIsNone(dist["items"][0]["value"])
        self.assertIsNone(dist["sum"])
        self.assertEqual(dist["ranking"]["highest"], [])

    def test_observed_zero_remains_zero_with_undefined_shares_and_all_ties(self):
        row = row_fixture()
        for field in population._FIELDS:
            row[field] = 0
        result = analyze(row)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["total"]["value"], 0)
        for dist in result["distributions"].values():
            self.assertEqual(dist["status"], "complete")
            self.assertTrue(all(item["value"] == 0 and item["share_percent"] is None for item in dist["items"]))
            self.assertEqual(len(dist["ranking"]["highest"]), 6)

    def test_absent_row_missing_field_and_uncollected_period_are_distinct(self):
        missing_row = analyze(None)
        self.assertEqual(missing_row["observation_status"], "no_observation")
        self.assertEqual(missing_row["coverage_status"], "collected")
        row = row_fixture()
        row.pop("TOT_FLPOP_CO")
        self.assertEqual(analyze(row)["observation_status"], "missing")
        uncollected = analyze(None, collected=False)
        self.assertEqual(uncollected["coverage_status"], "not_collected")
        self.assertEqual(uncollected["observation_status"], "not_collected")
        for result in (missing_row, analyze(row), uncollected):
            self.assertEqual(result["status"], "no_data")
            self.assertIsNone(result["total"]["value"])
            self.assertEqual(result["summary"], [])

    def test_invalid_counts_are_not_rounded_or_converted_to_missing(self):
        for value in (True, -1, "1.5", 1.5, float("inf"), Decimal("NaN"), Decimal("1.5"), Decimal("-1")):
            row = row_fixture()
            row["TOT_FLPOP_CO"] = value
            result = analyze(row)
            self.assertEqual(result["status"], "invalid")
            self.assertEqual(result["total"]["status"], "invalid")
            self.assertTrue(result["total"]["message"])

    def test_large_integer_keeps_exact_value_and_text(self):
        row = row_fixture()
        amount = 2 ** 53 + 1
        row["TOT_FLPOP_CO"] = str(amount)
        result = analyze(row)
        self.assertEqual(result["total"]["value"], amount)
        self.assertEqual(result["total"]["value_text"], str(amount))

    def test_industry_context_never_filters_or_scales_population(self):
        first = analyze(row_fixture())
        second = population.analyze_population_row(row_fixture(), {**selection(), "industry_code": "CS200009"}, "동물병원")
        self.assertEqual(first["total"], second["total"])
        self.assertEqual(first["distributions"], second["distributions"])
        self.assertEqual(second["selection"]["industry_name"], "동물병원")
        self.assertFalse(second["industry_applied"])


class PopulationProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="b4-synthetic-source-")
        self.addCleanup(self.directory.cleanup)
        self.raw = Path(self.directory.name)
        self.source = {"catalog_version": "synthetic-catalogue-v1", "files": []}
        self.patcher = patch.object(population, "get_analysis_catalog_source", side_effect=lambda: deepcopy(self.source))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.profile = {"industry": {"code": "CS100010", "name": "커피-음료"}}

    def page(self, rows, start=1, total=None):
        payload = {"VwsmTrdarFlpopQq": {"RESULT": {"CODE": "INFO-000"}, "row": rows,
                                       "list_total_count": len(rows) if total is None else total}}
        doc = {"query": {"dataset": "population", "period": "20262", "area_code": None, "start": start, "count": len(rows)},
            "payload": payload, "payload_sha256": canonical_hash(payload), "service": "VwsmTrdarFlpopQq",
            "source_url": SOURCE_URLS["population"], "sample_only": False}
        path = self.raw / f"population_20262_all_{start}.json"
        data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        path.write_bytes(data)
        self.source["files"].append({"path": "data/raw/official/" + path.name, "dataset": "population", "period": "20262",
            "area_code": None, "file_sha256": sha256(data).hexdigest(), "payload_sha256": doc["payload_sha256"],
            "start": start, "row_count": len(rows)})
        return path

    def build(self, selected=None, profile=None):
        return population.build_population_analysis(selected or selection(), profile or self.profile, raw_root=self.raw)

    def test_loaded_source_and_data_version_are_independent_of_industry(self):
        path = self.page([row_fixture()])
        first = self.build()
        other = self.build({**selection(), "industry_code": "CS200009"}, {"industry": {"code": "CS200009", "name": "동물병원"}})
        self.assertEqual(first["total"], other["total"])
        self.assertEqual(first["distributions"], other["distributions"])
        self.assertEqual(first["data_version"], other["data_version"])
        self.assertEqual(first["evidence"][0]["file_name"], path.name)
        self.assertEqual(first, self.build())
        self.assertFalse(first["source"]["definition_verified"])

    def test_missing_area_row_and_uncollected_period_are_not_substituted(self):
        self.page([row_fixture()])
        absent = self.build({**selection(), "area_code": "2222222", "area_name": "다른 상권"})
        uncollected = self.build({**selection(), "period": "20261"})
        self.assertEqual(absent["observation_status"], "no_observation")
        self.assertEqual(uncollected["observation_status"], "not_collected")
        self.assertIsNone(absent["total"]["value"])
        self.assertIsNone(uncollected["total"]["value"])

    def test_changed_raw_after_cache_is_detected(self):
        path = self.page([row_fixture()])
        self.build()
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(population.PopulationDataError):
            self.build()

    def test_incomplete_pages_duplicates_and_payload_tampering_are_rejected(self):
        path = self.page([row_fixture()], start=2, total=2)
        with self.assertRaises(population.PopulationDataError):
            self.build()
        self.page([row_fixture()], start=1, total=2)
        with self.assertRaises(population.PopulationDataError):
            self.build()
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["payload"]["VwsmTrdarFlpopQq"]["row"][0]["TOT_FLPOP_CO"] = 121
        data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        path.write_bytes(data)
        self.source["files"][0]["file_sha256"] = sha256(data).hexdigest()
        with self.assertRaises(population.PopulationDataError):
            self.build()

    def test_decimal_tokens_are_validated_before_binary_float_rounding(self):
        path = self.page([row_fixture()])
        original = path.read_text(encoding="utf-8")
        old_hash = self.source["files"][0]["payload_sha256"]
        for token, expected in (("9007199254740993.0", 9007199254740993), ("9007199254740990.5", None)):
            text = original.replace('"TOT_FLPOP_CO": 120', '"TOT_FLPOP_CO": ' + token)
            payload_hash = canonical_hash(json.loads(text)["payload"])
            data = text.replace(old_hash, payload_hash).encode("utf-8")
            path.write_bytes(data)
            self.source["files"][0].update(file_sha256=sha256(data).hexdigest(), payload_sha256=payload_hash)
            total = self.build()["total"]
            self.assertEqual(total["value"], expected)
            self.assertEqual(total["status"], "available" if expected is not None else "invalid")


class PopulationHttpTests(unittest.TestCase):
    profile_body = setup_helpers.OnboardingAnalysisTests.profile_body
    save_profile = setup_helpers.OnboardingAnalysisTests.save_profile
    state = setup_helpers.OnboardingAnalysisTests.state
    options = setup_helpers.OnboardingAnalysisTests.options
    selection_body = setup_helpers.OnboardingAnalysisTests.selection_body
    save_selection = setup_helpers.OnboardingAnalysisTests.save_selection
    selected = setup_helpers.OnboardingAnalysisTests.selected

    def setUp(self):
        setup_helpers.OnboardingAnalysisTests.setUp(self)
        self.row = row_fixture()
        self.build = self.stack.enter_context(patch.object(population, "build_population_analysis", side_effect=self.fake_build))

    def tearDown(self):
        setup_helpers.OnboardingAnalysisTests.tearDown(self)

    def fake_build(self, selected, profile):
        return {**population.analyze_population_row(self.row, selected, profile["industry"]["name"]),
                "data_version": "synthetic-population", "source": {"url": SOURCE_URLS["population"]}, "evidence": []}

    def test_read_uses_saved_conditions_and_leaves_state_unchanged(self):
        saved = self.selected()
        response = self.client.get("/api/onboarding/population", params={"expected_revision": saved["revision"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.json()["feature"], "population")
        self.assertEqual(response.json()["analysis_stage"], "population_result")
        self.assertFalse(response.json()["industry_applied"])
        self.assertEqual(response.json(), self.client.get("/api/onboarding/population").json())
        self.assertEqual(self.state()["profile"], saved["profile"])
        self.assertEqual(self.state()["analysis_selection"], saved["analysis_selection"])

    def test_missing_selection_stale_revision_and_query_injection_block_read(self):
        self.assertEqual(self.client.get("/api/onboarding/population").status_code, 409)
        saved = self.selected()
        self.assertEqual(self.client.get("/api/onboarding/population", params={"expected_revision": saved["revision"] - 1}).status_code, 409)
        for query in ({"area_code": "2222222"}, {"industry_code": self.photography}, {"period": "20261"}, {"latitude": 37.5}):
            response = self.client.get("/api/onboarding/population", params=query)
            self.assertEqual(response.status_code, 422, response.text)
        self.build.assert_not_called()

    def test_stale_or_unavailable_selection_does_not_call_population_loader(self):
        self.selected()
        self.catalogue.version = "changed-version"
        self.assertEqual(self.client.get("/api/onboarding/population").status_code, 409)
        self.catalogue.version = "synthetic-catalogue-v1"
        with patch.object(sys.modules["app.onboarding_analysis_catalog"], "get_analysis_options", side_effect=OSError("internal-path")):
            response = self.client.get("/api/onboarding/population")
            self.assertEqual(response.status_code, 503, response.text)
            self.assertNotIn("internal-path", response.text)
        self.build.assert_not_called()

    def test_condition_change_during_read_rejects_old_result(self):
        saved = self.selected()
        def changing(selected, profile):
            result = self.fake_build(selected, profile)
            owner, _ = self.store.session(self.client.cookies.get(COOKIE_NAME))
            self.store.save(owner, ProfileInput(location=None, industry_code=self.coffee, business_status="planning",
                expected_revision=saved["revision"]), lambda _owner, _location: None)
            return result
        self.build.side_effect = changing
        response = self.client.get("/api/onboarding/population", params={"expected_revision": saved["revision"]})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertNotIn("total", response.json())

    def test_source_error_is_generic_503_without_state_loss(self):
        saved = self.selected()
        self.build.side_effect = OSError("C:/private/.env")
        response = self.client.get("/api/onboarding/population")
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("private", response.text)
        self.assertNotIn(".env", response.text)
        self.assertEqual(self.state()["profile"], saved["profile"])

    def test_no_observation_is_normal_200_without_fake_zero(self):
        self.selected()
        self.row = None
        response = self.client.get("/api/onboarding/population")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "no_data")
        self.assertEqual(response.json()["observation_status"], "no_observation")
        self.assertIsNone(response.json()["total"]["value"])


if __name__ == "__main__":
    unittest.main()
