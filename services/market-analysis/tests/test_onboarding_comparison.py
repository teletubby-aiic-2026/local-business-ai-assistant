"""B5 comparison arithmetic, reader compatibility and HTTP isolation."""
from copy import deepcopy
import sys
import unittest
from unittest.mock import patch

from app import onboarding_comparison as comparison
from app.data_repository import SOURCE_URLS
from app.onboarding import COOKIE_NAME, ProfileInput
from tests import test_onboarding_analysis as setup_helpers


def selection():
    return {"area_code": "1111111", "area_name": "합성 상권 1111111", "industry_code": "CS100010",
        "period": "20262", "period_label": "2026년 2분기", "catalog_version": "synthetic-catalogue-v1",
        "boundary": {"publication_date": "2023-10-23", "compatibility": "unverified"}}


class FakeReaders:
    def __init__(self):
        self.version = "synthetic-catalogue-v1"
        self.areas = [self.area("1111111", "11110", "종로구"), self.area("2222222", "11740", "강동구"),
                      self.area("3333333", "11110", "종로구", blocked=True)]
        self.values = {"1111111": {"sales": 100, "stores": [10, 8, 2, 0, 1], "population": 50},
                       "2222222": {"sales": 150, "stores": [20, 10, 10, 2, 0], "population": 100}}
        self.transform = lambda _dataset, _selection, result: result
        self.calls = []

    @staticmethod
    def area(code, district, district_name, blocked=False):
        return {"area_code": code, "name": "합성 상권 " + code, "district_code": district,
            "district_name": district_name, "type": "골목상권", "geometry": {"synthetic": True},
            "boundary_identity_status": "name_mismatch" if blocked else "code_name_match"}

    def attach(self, stack):
        stack.enter_context(patch.object(comparison, "get_analysis_catalog_source", side_effect=lambda: {"catalog_version": self.version}))
        stack.enter_context(patch.object(comparison, "get_analysis_areas", side_effect=lambda: deepcopy(self.areas)))
        stack.enter_context(patch.object(comparison, "get_analysis_area", side_effect=lambda code: deepcopy(next((a for a in self.areas if a["area_code"] == code), None))))
        for dataset in ("sales", "stores", "population"):
            stack.enter_context(patch.object(comparison, "build_" + dataset + "_analysis",
                side_effect=lambda selected, profile, kind=dataset: self.read(kind, selected, profile)))

    @staticmethod
    def observed(value, unit, missing="missing"):
        return {"status": "available" if value is not None else missing, "value": value,
                "value_text": str(value) if value is not None else None, "unit": unit}

    def read(self, dataset, selected, profile):
        self.calls.append((dataset, deepcopy(selected), deepcopy(profile)))
        values = self.values[selected["area_code"]][dataset]
        unit = {"sales": "원", "stores": "개", "population": "명"}[dataset]
        result = {"selection": deepcopy(selected), "data_version": dataset + "-" + selected["area_code"],
            "source": {"title": "합성 " + dataset, "url": SOURCE_URLS[dataset], "unit": unit, "period_basis": "quarter"},
            "evidence": [{"file_name": "synthetic-source", "source_url": SOURCE_URLS[dataset]}]}
        if dataset == "stores":
            result["counts"] = {key: self.observed(value, unit, "not_collected")
                for key, value in zip(("total", "general", "franchise", "opened", "closed"), values)}
            result["composition"] = {"status": "consistent"}
        else:
            result["total"] = self.observed(values, unit)
        if dataset == "population":
            result.update(industry_applied=False, population_scope="area_wide",
                          observation_status="available" if values is not None else "no_observation")
            result["source"]["aggregation_basis"] = "source_total"
        return self.transform(dataset, selected, result)


class ComparisonSemanticsTests(unittest.TestCase):
    def setUp(self):
        from contextlib import ExitStack
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.readers = FakeReaders()
        self.readers.attach(self.stack)
        self.profile = {"industry": {"code": "CS100010", "name": "커피-음료"}}

    def result(self, code="2222222"):
        return comparison.build_comparison_analysis(selection(), self.profile, code)

    def test_seven_metrics_use_comparison_minus_base_and_base_denominator(self):
        result = self.result()
        rows = {row["key"]: row for row in result["metrics"]}
        self.assertEqual(len(rows), 7)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["comparison_direction"], "comparison_minus_base")
        self.assertEqual(rows["sales"]["delta"], 50)
        self.assertEqual(rows["sales"]["percent"], 50.0)
        self.assertEqual(rows["stores_closed"]["delta"], -1)
        self.assertEqual(rows["stores_closed"]["percent"], -100.0)
        self.assertEqual(rows["stores_franchise"]["delta"], 8)
        self.assertEqual(rows["stores_franchise"]["percent"], 400.0)
        self.assertFalse(rows["floating_population"]["industry_applied"])
        self.assertEqual(rows["sales"]["source"]["field"], "THSMON_SELNG_AMT")

    def test_zero_base_preserves_delta_but_never_defines_percent(self):
        rows = {row["key"]: row for row in self.result()["metrics"]}
        self.assertEqual(rows["stores_opened"]["base"]["value"], 0)
        self.assertEqual(rows["stores_opened"]["delta"], 2)
        self.assertIsNone(rows["stores_opened"]["percent"])
        self.assertEqual(rows["stores_opened"]["percent_status"], "undefined_zero_base")
        self.readers.values["2222222"]["stores"][3] = 0
        row = next(r for r in self.result()["metrics"] if r["key"] == "stores_opened")
        self.assertEqual(row["delta"], 0)
        self.assertEqual(row["delta_text"], "0")
        self.assertIsNone(row["percent"])

    def test_missing_stores_block_only_five_store_comparisons(self):
        self.readers.values["2222222"]["stores"] = [None] * 5
        result = self.result()
        self.assertEqual(result["status"], "partial")
        for row in result["metrics"]:
            if row["key"].startswith("stores_"):
                self.assertEqual(row["comparison"]["status"], "not_collected")
                self.assertEqual(row["status"], "unavailable")
                self.assertIsNone(row["delta"])
                self.assertIsNone(row["percent"])
            else:
                self.assertEqual(row["status"], "available")

    def test_no_comparable_observations_do_not_become_zero(self):
        self.readers.values["2222222"] = {"sales": None, "stores": [None] * 5, "population": None}
        result = self.result()
        self.assertEqual(result["status"], "no_data")
        self.assertTrue(all(row["delta"] is None and row["percent"] is None for row in result["metrics"]))
        self.assertEqual(result["metrics"][-1]["comparison"]["status"], "no_observation")

    def test_different_area_data_versions_are_preserved_and_valid(self):
        result = self.result()
        self.assertNotEqual(result["data_versions"]["base"]["stores"], result["data_versions"]["comparison"]["stores"])
        self.assertEqual(result["status"], "complete")
        for _dataset, selected, profile in self.readers.calls:
            self.assertEqual(selected["period"], "20262")
            self.assertEqual(selected["industry_code"], "CS100010")
            self.assertEqual(profile["industry"]["code"], "CS100010")

    def test_reader_unit_source_scope_and_conditions_must_be_compatible(self):
        mutations = [
            lambda r: r["source"].update(unit="달러"),
            lambda r: r["source"].update(url="https://example.test/wrong"),
            lambda r: r["source"].update(period_basis="month"),
            lambda r: r["selection"].update(period="20261"),
            lambda r: r["selection"].update(industry_code="CS200009"),
            lambda r: r["selection"].update(catalog_version="other"),
            lambda r: r["total"].update(value=1.5, value_text="1.5"),
        ]
        for mutate in mutations:
            def transform(dataset, selected, result):
                if dataset == "sales" and selected["area_code"] == "2222222":
                    mutate(result)
                return result
            self.readers.transform = transform
            with self.assertRaises(comparison.ComparisonDataError):
                self.result()
        def wrong_population(dataset, _selected, result):
            if dataset == "population":
                result["industry_applied"] = True
            return result
        self.readers.transform = wrong_population
        with self.assertRaises(comparison.ComparisonDataError):
            self.result()

    def test_same_unknown_and_boundary_mismatch_areas_are_rejected(self):
        for code in ("1111111", "9999999", "3333333"):
            with self.assertRaises(comparison.ComparisonInputError):
                self.result(code)
        self.assertEqual(self.readers.calls, [])

    def test_options_use_all_official_areas_without_geometries_or_base(self):
        result = comparison.get_comparison_options(selection(), self.profile)
        self.assertEqual(result["scope"]["official_area_count"], 3)
        self.assertEqual(result["scope"]["blocked_area_count"], 1)
        self.assertEqual({area["area_code"] for area in result["areas"]}, {"2222222", "3333333"})
        for area in result["areas"]:
            self.assertNotIn("geometry", area)
            self.assertNotIn("latitude", area)
            self.assertIn("type", area)
        blocked = next(a for a in result["areas"] if a["area_code"] == "3333333")
        self.assertFalse(blocked["selectable"])
        self.assertTrue(blocked["reason"])
        self.assertEqual(self.result()["comparison_area"]["district_name"], "강동구")

    def test_large_integer_difference_remains_exact(self):
        value = 2 ** 53 + 1
        self.readers.values["1111111"]["sales"] = value
        self.readers.values["2222222"]["sales"] = value + 1
        row = self.result()["metrics"][0]
        self.assertEqual(row["base"]["value_text"], str(value))
        self.assertEqual(row["comparison"]["value_text"], str(value + 1))
        self.assertEqual(row["delta"], 1)
        self.assertEqual(row["delta_text"], "1")


class ComparisonHttpTests(unittest.TestCase):
    profile_body = setup_helpers.OnboardingAnalysisTests.profile_body
    save_profile = setup_helpers.OnboardingAnalysisTests.save_profile
    state = setup_helpers.OnboardingAnalysisTests.state
    options = setup_helpers.OnboardingAnalysisTests.options
    selection_body = setup_helpers.OnboardingAnalysisTests.selection_body
    save_selection = setup_helpers.OnboardingAnalysisTests.save_selection
    selected = setup_helpers.OnboardingAnalysisTests.selected

    def setUp(self):
        setup_helpers.OnboardingAnalysisTests.setUp(self)
        self.readers = FakeReaders()
        self.readers.attach(self.stack)

    def tearDown(self):
        setup_helpers.OnboardingAnalysisTests.tearDown(self)

    def query(self, **updates):
        return {"comparison_area_code": "2222222", **updates}

    def test_options_and_comparison_are_read_only_and_use_saved_conditions(self):
        saved = self.selected()
        options = self.client.get("/api/onboarding/comparison-options", params={"expected_revision": saved["revision"]})
        self.assertEqual(options.status_code, 200, options.text)
        self.assertEqual(options.headers["cache-control"], "no-store")
        result = self.client.get("/api/onboarding/comparison", params=self.query(expected_revision=saved["revision"]))
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["feature"], "comparison")
        self.assertEqual(result.json()["analysis_stage"], "comparison_result")
        self.assertEqual(result.json()["revision"], saved["revision"])
        self.assertEqual(result.json(), self.client.get("/api/onboarding/comparison", params=self.query()).json())
        self.assertEqual(self.state()["profile"], saved["profile"])
        self.assertEqual(self.state()["analysis_selection"], saved["analysis_selection"])

    def test_missing_selection_and_old_revision_are_409(self):
        for endpoint, params in (("comparison-options", {}), ("comparison", self.query())):
            self.assertEqual(self.client.get("/api/onboarding/" + endpoint, params=params).status_code, 409)
        saved = self.selected()
        for endpoint, params in (("comparison-options", {}), ("comparison", self.query())):
            response = self.client.get("/api/onboarding/" + endpoint, params={**params, "expected_revision": saved["revision"] - 1})
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.readers.calls, [])

    def test_input_injection_duplicates_and_invalid_comparison_area_are_422(self):
        self.selected()
        for params in (self.query(industry_code=self.photography), self.query(period="20261"), self.query(area_code="2222222"),
                       self.query(latitude=37.5), self.query(comparison_area_code="12"), {},
                       self.query(comparison_area_code="1111111"), self.query(comparison_area_code="3333333"),
                       self.query(comparison_area_code="9999999")):
            response = self.client.get("/api/onboarding/comparison", params=params)
            self.assertEqual(response.status_code, 422, response.text)
        response = self.client.get("/api/onboarding/comparison", params=[("comparison_area_code", "2222222"), ("comparison_area_code", "1111111")])
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get("/api/onboarding/comparison-options", params={"period": "20261"}).status_code, 422)

    def test_stale_or_unavailable_selection_blocks_both_endpoints(self):
        self.selected()
        self.catalogue.version = "changed-version"
        for endpoint, params in (("comparison-options", {}), ("comparison", self.query())):
            self.assertEqual(self.client.get("/api/onboarding/" + endpoint, params=params).status_code, 409)
        self.catalogue.version = "synthetic-catalogue-v1"
        with patch.object(sys.modules["app.onboarding_analysis_catalog"], "get_analysis_options", side_effect=OSError("private-file")):
            for endpoint, params in (("comparison-options", {}), ("comparison", self.query())):
                response = self.client.get("/api/onboarding/" + endpoint, params=params)
                self.assertEqual(response.status_code, 503, response.text)
                self.assertNotIn("private-file", response.text)

    def test_revision_change_during_options_or_comparison_returns_409(self):
        self.selected()
        for endpoint, function, params in (("comparison-options", "get_comparison_options", {}),
                                           ("comparison", "build_comparison_analysis", self.query())):
            original = getattr(comparison, function)
            def changing(*args):
                result = original(*args)
                owner, _ = self.store.session(self.client.cookies.get(COOKIE_NAME))
                revision = self.store.profile(owner)["revision"]
                self.store.save(owner, ProfileInput(location=None, industry_code=self.coffee, business_status="planning",
                    expected_revision=revision), lambda _owner, _location: None)
                return result
            with patch.object(comparison, function, side_effect=changing):
                response = self.client.get("/api/onboarding/" + endpoint, params=params)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertNotIn("metrics", response.json())

    def test_source_failure_hides_internal_details_and_preserves_base(self):
        saved = self.selected()
        with patch.object(comparison, "build_sales_analysis", side_effect=OSError("C:/private/.env")):
            response = self.client.get("/api/onboarding/comparison", params=self.query())
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("private", response.text)
        self.assertNotIn(".env", response.text)
        self.assertEqual(self.state()["analysis_selection"], saved["analysis_selection"])

    def test_partial_data_is_a_normal_200_with_other_metrics_kept(self):
        self.selected()
        self.readers.values["2222222"]["stores"] = [None] * 5
        response = self.client.get("/api/onboarding/comparison", params=self.query())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "partial")
        self.assertEqual(sum(row["status"] == "available" for row in response.json()["metrics"]), 2)


if __name__ == "__main__":
    unittest.main()
