"""B6 exact quarter shifts, source availability and immutable HTTP reads."""
from contextlib import ExitStack
from copy import deepcopy
import sys
import unittest
from unittest.mock import patch

from app import onboarding_changes as changes
from app import onboarding_comparison as comparison_module
from app.onboarding import COOKIE_NAME, ProfileInput
from tests import test_onboarding_analysis as setup_helpers
from tests import test_onboarding_comparison as comparison_helpers


def selection():
    return comparison_helpers.selection()


class PeriodReaders:
    def __init__(self):
        self.inner = comparison_helpers.FakeReaders()
        self.values = {
            "20262": {"sales": 150, "stores": [20, 10, 10, 2, 0], "population": 100},
            "20261": {"sales": 100, "stores": [10, 8, 2, 0, 1], "population": 50},
            "20252": {"sales": 200, "stores": [25, 20, 5, 5, 3], "population": 80},
        }
        self.source = {"catalog_version": "synthetic-catalogue-v1", "files": [
            {"dataset": dataset, "period": period, "area_code": "1111111" if dataset == "stores" else None}
            for period in self.values for dataset in ("sales", "stores", "population")]}

    def attach(self, stack):
        stack.enter_context(patch.object(comparison_module, "get_analysis_catalog_source", side_effect=lambda: deepcopy(self.source)))
        stack.enter_context(patch.object(comparison_module, "get_analysis_area", side_effect=lambda code: deepcopy(
            next((area for area in self.inner.areas if area["area_code"] == code), None))))
        for dataset in ("sales", "stores", "population"):
            stack.enter_context(patch.object(changes, "build_" + dataset + "_analysis",
                side_effect=lambda selected, profile, kind=dataset: self.read(kind, selected, profile)))

    def read(self, dataset, selected, profile):
        self.inner.values["1111111"] = deepcopy(self.values[selected["period"]])
        result = self.inner.read(dataset, selected, profile)
        result["data_version"] = dataset + "-" + selected["period"]
        return result


class ChangesSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.readers = PeriodReaders()
        self.readers.attach(self.stack)
        self.profile = {"industry": {"code": "CS100010", "name": "커피-음료"}}

    def result(self, mode="qoq", selected=None):
        return changes.build_changes_analysis(selected or selection(), self.profile, mode)

    def test_qoq_and_yoy_use_exact_periods_current_minus_previous_and_previous_denominator(self):
        qoq = self.result()
        self.assertEqual(qoq["previous_period"]["code"], "20261")
        self.assertEqual(qoq["comparison_direction"], "current_minus_previous")
        metrics = {row["key"]: row for row in qoq["metrics"]}
        self.assertEqual(metrics["sales"]["delta"], 50)
        self.assertEqual(metrics["sales"]["percent"], 50.0)
        self.assertEqual(metrics["stores_closed"]["delta"], -1)
        self.assertEqual(metrics["stores_closed"]["percent"], -100.0)
        yoy = self.result("yoy")
        self.assertEqual(yoy["previous_period"]["code"], "20252")
        self.assertEqual(yoy["metrics"][0]["delta"], -50)
        self.assertEqual(yoy["metrics"][0]["percent"], -25.0)

    def test_first_quarter_uses_exact_missing_quarters_without_falling_back(self):
        current = {**selection(), "period": "20261", "period_label": "2026년 1분기"}
        for mode, previous in (("qoq", "20254"), ("yoy", "20251")):
            self.readers.inner.calls.clear()
            result = self.result(mode, current)
            self.assertEqual(result["previous_period"]["code"], previous)
            self.assertEqual(result["status"], "no_comparison")
            self.assertTrue(all(row["previous"]["status"] == "not_collected" for row in result["metrics"]))
            self.assertTrue(all(row["delta"] is None and row["percent"] is None for row in result["metrics"]))
            self.assertEqual(result["metrics"][0]["current"]["value"], 100)
            self.assertEqual(set(result["data_versions"]["previous"].values()), {None})
            self.assertEqual(set(result["period_collection"]["previous"].values()), {False})
            self.assertTrue(all(selected["period"] == "20261" for _dataset, selected, _profile in self.readers.inner.calls))

    def test_previous_zero_keeps_positive_and_zero_deltas_without_percent(self):
        self.readers.values["20261"] = {"sales": 0, "stores": [0, 0, 0, 0, 0], "population": 0}
        result = self.result()
        for row in result["metrics"]:
            self.assertEqual(row["percent_status"], "undefined_zero_previous")
            self.assertIsNone(row["percent"])
            self.assertEqual(row["delta"], row["current"]["value"])
        closed = next(row for row in result["metrics"] if row["key"] == "stores_closed")
        self.assertEqual(closed["delta"], 0)
        self.assertEqual(closed["delta_text"], "0")

    def test_missing_metric_does_not_block_other_changes(self):
        self.readers.values["20261"]["sales"] = None
        result = self.result()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["metrics"][0]["previous"]["status"], "missing")
        self.assertIsNone(result["metrics"][0]["delta"])
        self.assertEqual(sum(row["status"] == "available" for row in result["metrics"]), 6)

    def test_uncollected_store_scope_is_not_a_service_error_or_zero(self):
        self.readers.source["files"] = [entry for entry in self.readers.source["files"]
            if not (entry["dataset"] == "stores" and entry["period"] == "20261")]
        result = self.result()
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["period_collection"]["previous"]["stores"])
        self.assertIsNone(result["data_versions"]["previous"]["stores"])
        self.assertEqual(sum(row["status"] == "available" for row in result["metrics"]), 2)
        self.assertTrue(all(selected["period"] != "20261" or dataset != "stores"
                            for dataset, selected, _profile in self.readers.inner.calls))

    def test_citywide_store_manifest_is_collected_for_the_saved_area(self):
        for entry in self.readers.source["files"]:
            if entry["dataset"] == "stores":
                entry["area_code"] = None
        result = self.result()
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["period_collection"]["current"]["stores"])
        self.assertTrue(result["period_collection"]["previous"]["stores"])
        self.assertEqual(next(row for row in result["metrics"] if row["key"] == "stores_total")["delta"], 10)
        self.assertTrue(any("서울 전체 조회" in warning for warning in result["warnings"]))
        self.assertFalse(any("10개 상권" in warning for warning in result["warnings"]))

    def test_manifest_present_but_missing_file_is_not_reclassified_as_uncollected(self):
        with patch.object(changes, "build_sales_analysis", side_effect=FileNotFoundError("source file")):
            with self.assertRaises(FileNotFoundError):
                self.result()

    def test_different_period_data_versions_are_normal_and_conditions_stay_fixed(self):
        result = self.result()
        self.assertNotEqual(result["data_versions"]["current"]["sales"], result["data_versions"]["previous"]["sales"])
        self.assertEqual(result["status"], "complete")
        for _dataset, selected, _profile in self.readers.inner.calls:
            self.assertEqual(selected["area_code"], "1111111")
            self.assertEqual(selected["industry_code"], "CS100010")
            self.assertEqual(selected["catalog_version"], "synthetic-catalogue-v1")

    def test_definition_unit_and_catalogue_mismatches_are_rejected(self):
        def wrong_unit(dataset, selected, result):
            if dataset == "sales" and selected["period"] == "20261":
                result["source"]["unit"] = "달러"
            return result
        self.readers.inner.transform = wrong_unit
        with self.assertRaises(comparison_module.ComparisonDataError):
            self.result()
        self.readers.inner.transform = lambda _dataset, _selected, result: result
        self.readers.source["catalog_version"] = "changed"
        with self.assertRaises(comparison_module.ComparisonDataError):
            self.result()

    def test_large_exact_integer_delta_is_not_lost(self):
        previous = 2 ** 53 + 1
        self.readers.values["20261"]["sales"] = previous
        self.readers.values["20262"]["sales"] = previous + 1
        row = self.result()["metrics"][0]
        self.assertEqual(row["previous"]["value_text"], str(previous))
        self.assertEqual(row["current"]["value_text"], str(previous + 1))
        self.assertEqual(row["delta"], 1)
        self.assertEqual(row["delta_text"], "1")

    def test_unknown_comparison_mode_does_not_read_any_source(self):
        for mode in ("latest", "year", "", None):
            with self.assertRaises(changes.ChangesInputError):
                self.result(mode)
        self.assertEqual(self.readers.inner.calls, [])


class ChangesHttpTests(unittest.TestCase):
    profile_body = setup_helpers.OnboardingAnalysisTests.profile_body
    save_profile = setup_helpers.OnboardingAnalysisTests.save_profile
    state = setup_helpers.OnboardingAnalysisTests.state
    options = setup_helpers.OnboardingAnalysisTests.options
    selection_body = setup_helpers.OnboardingAnalysisTests.selection_body
    save_selection = setup_helpers.OnboardingAnalysisTests.save_selection
    selected = setup_helpers.OnboardingAnalysisTests.selected

    def setUp(self):
        setup_helpers.OnboardingAnalysisTests.setUp(self)
        self.readers = PeriodReaders()
        self.readers.attach(self.stack)

    def tearDown(self):
        setup_helpers.OnboardingAnalysisTests.tearDown(self)

    def test_changes_read_is_immutable_and_current_conditions_are_used(self):
        saved = self.selected()
        response = self.client.get("/api/onboarding/changes", params={"comparison": "qoq", "expected_revision": saved["revision"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.json()["feature"], "changes")
        self.assertEqual(response.json()["analysis_stage"], "changes_result")
        self.assertEqual(response.json()["current_period"]["code"], saved["analysis_selection"]["period"])
        self.assertEqual(response.json(), self.client.get("/api/onboarding/changes", params={"comparison": "qoq"}).json())
        self.assertEqual(self.state()["profile"], saved["profile"])
        self.assertEqual(self.state()["analysis_selection"], saved["analysis_selection"])

    def test_missing_selection_and_stale_revision_are_409(self):
        self.assertEqual(self.client.get("/api/onboarding/changes", params={"comparison": "qoq"}).status_code, 409)
        saved = self.selected()
        response = self.client.get("/api/onboarding/changes", params={"comparison": "qoq", "expected_revision": saved["revision"] - 1})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.readers.inner.calls, [])

    def test_mode_required_and_query_injection_duplicates_or_custom_period_are_422(self):
        self.selected()
        for params in ({}, {"comparison": "latest"}, {"comparison": "qoq", "previous_period": "20252"},
                       {"comparison": "qoq", "period": "20261"}, {"comparison": "qoq", "industry_code": self.photography},
                       {"comparison": "yoy", "area_code": "2222222"}, {"comparison": "qoq", "expected_revision": -1}):
            response = self.client.get("/api/onboarding/changes", params=params)
            self.assertEqual(response.status_code, 422, response.text)
        response = self.client.get("/api/onboarding/changes", params=[("comparison", "qoq"), ("comparison", "yoy")])
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.readers.inner.calls, [])

    def test_missing_previous_period_is_normal_200_with_current_values(self):
        self.save_profile()
        self.save_selection(self.selection_body(period="20261"))
        for mode, expected in (("qoq", "20254"), ("yoy", "20251")):
            response = self.client.get("/api/onboarding/changes", params={"comparison": mode})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["previous_period"]["code"], expected)
            self.assertEqual(response.json()["status"], "no_comparison")
            self.assertEqual(response.json()["metrics"][0]["current"]["value"], 100)
            self.assertEqual(response.json()["metrics"][0]["previous"]["status"], "not_collected")

    def test_stale_or_unavailable_selection_blocks_load(self):
        self.selected()
        self.catalogue.version = "changed-version"
        self.assertEqual(self.client.get("/api/onboarding/changes", params={"comparison": "qoq"}).status_code, 409)
        self.catalogue.version = "synthetic-catalogue-v1"
        with patch.object(sys.modules["app.onboarding_analysis_catalog"], "get_analysis_options", side_effect=OSError("internal-source")):
            response = self.client.get("/api/onboarding/changes", params={"comparison": "qoq"})
            self.assertEqual(response.status_code, 503, response.text)
            self.assertNotIn("internal-source", response.text)
        self.assertEqual(self.readers.inner.calls, [])

    def test_condition_change_during_read_returns_409(self):
        saved = self.selected()
        original = changes.build_changes_analysis
        def changing(*args):
            result = original(*args)
            owner, _ = self.store.session(self.client.cookies.get(COOKIE_NAME))
            self.store.save(owner, ProfileInput(location=None, industry_code=self.coffee, business_status="planning",
                expected_revision=saved["revision"]), lambda _owner, _location: None)
            return result
        with patch.object(changes, "build_changes_analysis", side_effect=changing):
            response = self.client.get("/api/onboarding/changes", params={"comparison": "qoq", "expected_revision": saved["revision"]})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertNotIn("metrics", response.json())

    def test_declared_source_failure_is_503_not_uncollected_and_keeps_state(self):
        saved = self.selected()
        with patch.object(changes, "build_sales_analysis", side_effect=FileNotFoundError("C:/private/.env")):
            response = self.client.get("/api/onboarding/changes", params={"comparison": "qoq"})
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("private", response.text)
        self.assertNotIn(".env", response.text)
        self.assertEqual(self.state()["profile"], saved["profile"])


if __name__ == "__main__":
    unittest.main()
