"""B2 numerical semantics, preserved-source verification and HTTP boundaries."""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import onboarding_sales as sales
from app.data_repository import canonical_hash, SOURCE_URLS
from app.onboarding import COOKIE_NAME, ProfileInput
from tests import test_onboarding_analysis as setup_helpers


def selection():
    return {"area_code": "1111111", "area_name": "합성 상권 1111111", "industry_code": "CS100010",
        "period": "20262", "period_label": "2026년 2분기", "catalog_version": "synthetic-catalogue-v1",
        "boundary": {"publication_date": "2023-10-23", "compatibility": "unverified"}}


def row_fixture():
    row = {"STDR_YYQU_CD": "20262", "TRDAR_CD": "1111111", "TRDAR_CD_NM": "합성 상권 1111111",
           "SVC_INDUTY_CD": "CS100010", "SVC_INDUTY_CD_NM": "커피-음료", "THSMON_SELNG_AMT": 112}
    for kind, values in (("weekday", (10, 20, 20, 20, 10, 20, 12)),
                         ("time", (10, 20, 40, 20, 12, 10)), ("age", (0, 0, 30, 30, 0, 0))):
        for (_label, field), value in zip(sales._GROUPS[kind][1], values):
            row[field] = value
    return row


def analyze(row):
    return sales.analyze_sales_row(row, selection(), "커피-음료")


class SalesSemanticsTests(unittest.TestCase):
    def test_total_and_separate_distributions_use_explicit_denominators(self):
        result = analyze(row_fixture())
        self.assertEqual(result["total"]["value"], 112)
        self.assertEqual(result["total"]["value_text"], "112")
        self.assertEqual(result["distributions"]["weekday"]["denominator"]["value"], 112)
        age = result["distributions"]["age"]
        self.assertEqual(age["denominator"]["kind"], "age_classified_total")
        self.assertEqual(age["denominator"]["value"], 60)
        self.assertEqual(age["items"][2]["share_percent"], 50.0)
        self.assertEqual(age["classified_share_of_total_percent"], 53.57)
        self.assertEqual(age["total_difference"], -52)

    def test_all_highest_and_lowest_ties_are_returned(self):
        days = analyze(row_fixture())["distributions"]["weekday"]
        self.assertEqual(days["ranking"]["highest"], ["화", "수", "목", "토"])
        self.assertEqual(days["ranking"]["lowest"], ["월", "금"])
        self.assertEqual(days["ranking"]["highest_value"], 20)

    def test_zero_total_preserves_observed_zeros_but_has_no_ratios(self):
        row = row_fixture()
        for field in sales._FIELDS:
            row[field] = 0
        result = analyze(row)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["total"]["value"], 0)
        for kind, dist in result["distributions"].items():
            self.assertEqual(dist["status"], "complete")
            self.assertTrue(all(item["value"] == 0 and item["share_percent"] is None for item in dist["items"]))
            self.assertEqual(len(dist["ranking"]["highest"]), len(dist["items"]))
            self.assertEqual(len(dist["ranking"]["lowest"]), len(dist["items"]))

    def test_missing_row_is_empty_data_without_replacement(self):
        result = analyze(None)
        self.assertEqual(result["status"], "no_data")
        self.assertEqual(result["total"]["status"], "missing")
        self.assertIsNone(result["total"]["value"])
        self.assertEqual(result["summary"], [])
        for dist in result["distributions"].values():
            self.assertEqual(dist["status"], "no_data")
            self.assertEqual(dist["ranking"]["status"], "unavailable")
            self.assertTrue(all(item["value"] is None for item in dist["items"]))

    def test_partial_weekday_and_time_never_rank_or_compute_shares(self):
        for kind in ("weekday", "time"):
            with self.subTest(kind=kind):
                row = row_fixture()
                row.pop(sales._GROUPS[kind][1][0][1])
                dist = analyze(row)["distributions"][kind]
                self.assertEqual(dist["status"], "partial")
                self.assertEqual(dist["items"][0]["status"], "missing")
                self.assertIsNone(dist["items"][0]["value"])
                self.assertIsNone(dist["sum"])
                self.assertEqual(dist["ranking"]["highest"], [])
                self.assertTrue(all(item["share_percent"] is None for item in dist["items"]))

    def test_distribution_sum_mismatch_preserves_values_but_blocks_interpretation(self):
        for kind in ("weekday", "time"):
            with self.subTest(kind=kind):
                row = row_fixture()
                row[sales._GROUPS[kind][1][0][1]] += 1
                dist = analyze(row)["distributions"][kind]
                self.assertEqual(dist["status"], "inconsistent")
                self.assertEqual(dist["total_difference"], 1)
                self.assertEqual(dist["ranking"]["status"], "unavailable")
                self.assertTrue(all(item["share_percent"] is None for item in dist["items"]))

    def test_age_above_total_even_by_one_won_is_not_a_valid_distribution(self):
        row = row_fixture()
        row["AGRDE_30_SELNG_AMT"] = 83
        dist = analyze(row)["distributions"]["age"]
        self.assertEqual(dist["sum"], 113)
        self.assertEqual(dist["status"], "inconsistent")
        self.assertEqual(dist["ranking"]["status"], "unavailable")
        self.assertTrue(all(item["share_percent"] is None for item in dist["items"]))

    def test_tiny_age_coverage_is_not_described_as_all_sales(self):
        row = row_fixture()
        row["THSMON_SELNG_AMT"] = 1000000
        age = analyze(row)["distributions"]["age"]
        self.assertEqual(age["denominator"]["value"], 60)
        self.assertEqual(age["classified_share_of_total_percent"], 0.01)
        self.assertTrue(any("절반 미만" in warning for warning in age["warnings"]))
        self.assertTrue(any("전체 매출이 아닌" in warning for warning in age["warnings"]))

    def test_exact_integer_amount_above_javascript_safe_integer_is_preserved(self):
        value = 2 ** 53 + 1
        row = row_fixture()
        row["THSMON_SELNG_AMT"] = str(value)
        for _kind, (_label, fields) in sales._GROUPS.items():
            for index, (_name, field) in enumerate(fields):
                row[field] = str(value) if index == 0 else "0"
        result = analyze(row)
        self.assertEqual(result["total"]["value"], value)
        self.assertEqual(result["total"]["value_text"], str(value))
        self.assertEqual(result["distributions"]["weekday"]["items"][0]["share_percent"], 100.0)

    def test_invalid_amounts_are_not_silently_rounded_zeroed_or_missing(self):
        for value in (True, -1, "1.5", float("nan"), float("inf"), 1.5, "1e3",
                      Decimal("NaN"), Decimal("Infinity"), Decimal("-1"), Decimal("1.5")):
            with self.subTest(value=str(value)):
                row = row_fixture()
                row["THSMON_SELNG_AMT"] = value
                result = analyze(row)
                self.assertEqual(result["status"], "invalid")
                self.assertEqual(result["total"]["status"], "invalid")
                self.assertIsNone(result["total"]["value"])
                self.assertTrue(result["total"]["message"])
                self.assertEqual(result["summary"], [])

    def test_missing_total_is_normal_no_data_and_does_not_enable_rankings(self):
        row = row_fixture()
        row.pop("THSMON_SELNG_AMT")
        result = analyze(row)
        self.assertEqual(result["status"], "no_data")
        self.assertTrue(all(d["ranking"]["status"] == "unavailable" for d in result["distributions"].values()))

    def test_invalid_distribution_item_does_not_hide_valid_total(self):
        row = row_fixture()
        row["MON_SELNG_AMT"] = -5
        result = analyze(row)
        self.assertEqual(result["total"]["value"], 112)
        self.assertEqual(result["distributions"]["weekday"]["status"], "invalid")
        self.assertEqual(result["distributions"]["time"]["status"], "complete")
        self.assertEqual(result["distributions"]["weekday"]["ranking"]["status"], "unavailable")


class SalesProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="b2-synthetic-source-")
        self.addCleanup(self.directory.cleanup)
        self.raw_root = Path(self.directory.name)
        self.source = {"catalog_version": "synthetic-catalogue-v1", "files": []}
        self.patch = patch.object(sales, "get_analysis_catalog_source", side_effect=lambda: deepcopy(self.source))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.profile = {"industry": {"code": "CS100010", "name": "커피-음료"}}

    def page(self, rows, start=1, total=None):
        payload = {"VwsmTrdarSelngQq": {"RESULT": {"CODE": "INFO-000"}, "row": rows,
                                      "list_total_count": len(rows) if total is None else total}}
        doc = {"query": {"dataset": "sales", "period": "20262", "area_code": None, "start": start, "count": len(rows)},
            "payload": payload, "payload_sha256": canonical_hash(payload), "service": "VwsmTrdarSelngQq",
            "source_url": SOURCE_URLS["sales"], "sample_only": False}
        path = self.raw_root / f"sales_20262_all_{start}.json"
        data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        path.write_bytes(data)
        self.source["files"].append({"path": "data/raw/official/" + path.name, "dataset": "sales", "period": "20262",
            "file_sha256": sha256(data).hexdigest(), "payload_sha256": doc["payload_sha256"], "start": start, "row_count": len(rows)})
        return path

    def build(self):
        return sales.build_sales_analysis(selection(), self.profile, raw_root=self.raw_root)

    def test_verified_source_connects_evidence_and_repeated_read_is_identical(self):
        path = self.page([row_fixture()])
        first, second = self.build(), self.build()
        self.assertEqual(first, second)
        self.assertEqual(first["evidence"][0]["file_name"], path.name)
        self.assertEqual(first["evidence"][0]["file_sha256"], self.source["files"][0]["file_sha256"])
        self.assertEqual(first["total"]["value"], 112)
        self.assertTrue(first["data_version"].startswith("b2_"))

    def test_raw_change_after_warm_cache_is_detected(self):
        path = self.page([row_fixture()])
        self.build()
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(sales.SalesDataError):
            self.build()

    def test_missing_page_and_duplicate_rows_cannot_be_used(self):
        self.page([row_fixture()], start=2, total=2)
        with self.assertRaises(sales.SalesDataError):
            self.build()
        self.page([row_fixture()], start=1, total=2)
        with self.assertRaises(sales.SalesDataError):
            self.build()

    def test_payload_hash_mismatch_rejected_even_when_file_hash_is_updated(self):
        path = self.page([row_fixture()])
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["payload"]["VwsmTrdarSelngQq"]["row"][0]["THSMON_SELNG_AMT"] = 113
        data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        path.write_bytes(data)
        self.source["files"][0]["file_sha256"] = sha256(data).hexdigest()
        with self.assertRaises(sales.SalesDataError):
            self.build()

    def test_no_selected_observation_is_normal_empty_without_using_another_industry(self):
        row = row_fixture()
        row.update(SVC_INDUTY_CD="CS200041", SVC_INDUTY_CD_NM="사진관")
        self.page([row])
        result = self.build()
        self.assertEqual(result["status"], "no_data")
        self.assertEqual(result["selection"]["industry_code"], "CS100010")
        self.assertIsNone(result["total"]["value"])
        self.assertTrue(result["evidence"])
        self.assertEqual(result["coverage_status"], "collected")
        self.assertEqual(result["observation_status"], "no_observation")

    def test_uncollected_period_is_normal_missing_and_does_not_read_other_quarters(self):
        self.page([row_fixture()])
        selected = {**selection(), "period": "20261", "period_label": "2026년 1분기"}
        result = sales.build_sales_analysis(selected, self.profile, raw_root=self.raw_root)
        self.assertEqual(result["status"], "no_data")
        self.assertEqual(result["total"]["status"], "not_collected")
        self.assertIsNone(result["total"]["value"])
        self.assertEqual(result["coverage_status"], "not_collected")
        self.assertEqual(result["observation_status"], "not_collected")
        self.assertEqual(result["evidence"], [])
        self.assertIn("확보하지", result["total"]["message"])

    def test_catalogue_version_is_part_of_cache_identity_and_selection_contract(self):
        self.page([row_fixture()])
        first = self.build()
        self.source["catalog_version"] = "synthetic-catalogue-v2"
        with self.assertRaises(sales.SalesDataError):
            self.build()
        selected = {**selection(), "catalog_version": self.source["catalog_version"]}
        second = sales.build_sales_analysis(selected, self.profile, raw_root=self.raw_root)
        self.assertNotEqual(first["data_version"], second["data_version"])

    def test_json_decimal_tokens_are_checked_before_float_rounding_can_lose_digits(self):
        path = self.page([row_fixture()])
        original = path.read_text(encoding="utf-8")
        original_hash = self.source["files"][0]["payload_sha256"]
        for token, expected in (("9007199254740993.0", 9007199254740993), ("9007199254740990.5", None)):
            with self.subTest(token=token):
                text = original.replace('"THSMON_SELNG_AMT": 112', '"THSMON_SELNG_AMT": ' + token)
                payload_hash = canonical_hash(json.loads(text)["payload"])
                data = text.replace(original_hash, payload_hash).encode("utf-8")
                path.write_bytes(data)
                self.source["files"][0].update(file_sha256=sha256(data).hexdigest(), payload_sha256=payload_hash)
                total = self.build()["total"]
                self.assertEqual(total["value"], expected)
                self.assertEqual(total["status"], "available" if expected is not None else "invalid")
                if expected is not None:
                    self.assertEqual(total["value_text"], str(expected))

    def test_same_size_rewrite_with_same_mtime_is_read_again(self):
        # Linux can record two quick writes with the same mtime. A rewrite that
        # the catalogue records must be read again, not answered from the cache.
        path = self.page([row_fixture()])
        original, old_hash, first_mtime = path.read_text(encoding="utf-8"), self.source["files"][0]["payload_sha256"], path.stat().st_mtime_ns
        self.assertEqual(self.build()["total"]["value"], 112)
        text = original.replace('"THSMON_SELNG_AMT": 112', '"THSMON_SELNG_AMT": 211')
        payload_hash = canonical_hash(json.loads(text)["payload"])
        data = text.replace(old_hash, payload_hash).encode("utf-8")
        path.write_bytes(data)
        os.utime(path, ns=(path.stat().st_atime_ns, first_mtime))
        self.source["files"][0].update(file_sha256=sha256(data).hexdigest(), payload_sha256=payload_hash)
        self.assertEqual(self.build()["total"]["value"], 211)


class SalesHttpTests(unittest.TestCase):
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
        self.build = self.stack.enter_context(patch.object(sales, "build_sales_analysis", side_effect=self.fake_build))

    def tearDown(self):
        setup_helpers.OnboardingAnalysisTests.tearDown(self)

    def fake_build(self, selected, profile):
        result = sales.analyze_sales_row(self.row, selected, profile["industry"]["name"])
        return {**result, "data_version": "synthetic-sales-version", "source": {"url": SOURCE_URLS["sales"]}, "evidence": []}

    def test_missing_selection_is_409_and_does_not_load_sales(self):
        self.assertEqual(self.client.get("/api/onboarding/sales").status_code, 409)
        self.save_profile()
        self.assertEqual(self.client.get("/api/onboarding/sales").status_code, 409)
        self.build.assert_not_called()

    def test_saved_conditions_are_used_and_read_does_not_mutate_revision_or_selection(self):
        state = self.selected()
        first = self.client.get("/api/onboarding/sales", params={"expected_revision": state["revision"]})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.headers["cache-control"], "no-store")
        body = first.json()
        self.assertEqual(body["feature"], "sales")
        self.assertEqual(body["analysis_stage"], "sales_result")
        self.assertEqual(body["revision"], state["revision"])
        self.assertEqual(body["selection"]["area_code"], state["analysis_selection"]["area_code"])
        self.assertEqual(body, self.client.get("/api/onboarding/sales").json())
        self.assertEqual(self.state()["analysis_selection"], state["analysis_selection"])
        self.assertEqual(self.state()["profile"], state["profile"])

    def test_client_cannot_inject_analysis_conditions_or_old_revision(self):
        state = self.selected()
        for query in ({"area_code": "2222222"}, {"industry_code": self.photography}, {"period": "20261"},
                      {"latitude": 37.5}, {"expected_revision": -1}):
            with self.subTest(query=query):
                response = self.client.get("/api/onboarding/sales", params=query)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get("/api/onboarding/sales", params={"expected_revision": state["revision"] - 1}).status_code, 409)
        self.build.assert_not_called()

    def test_stale_and_unavailable_b1_selection_do_not_run_sales(self):
        self.selected()
        self.catalogue.version = "new-version"
        self.assertEqual(self.client.get("/api/onboarding/sales").status_code, 409)
        self.catalogue.version = "synthetic-catalogue-v1"
        import sys
        with patch.object(sys.modules["app.onboarding_analysis_catalog"], "get_analysis_options", side_effect=OSError("private-source-path")):
            result = self.client.get("/api/onboarding/sales")
            self.assertEqual(result.status_code, 503, result.text)
            self.assertNotIn("private-source-path", result.text)
        self.build.assert_not_called()

    def test_population_only_selection_returns_no_sales_without_industry_fallback(self):
        self.catalogue.population_only.add(self.photography)
        self.save_profile(self.profile_body(industry_code=self.photography))
        self.save_selection()
        self.row = None
        response = self.client.get("/api/onboarding/sales")
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["status"], "no_data")
        self.assertEqual(result["selection"]["industry_code"], self.photography)
        self.assertIsNone(result["total"]["value"])
        self.assertEqual(result["summary"], [])

    def test_change_during_computation_rejects_old_result_after_initial_revision_passes(self):
        saved = self.selected()
        def change_during_read(selected, profile):
            result = self.fake_build(selected, profile)
            owner, _token = self.store.session(self.client.cookies.get(COOKIE_NAME))
            body = ProfileInput(location=None, industry_code=self.coffee, business_status="planning",
                                expected_revision=saved["revision"])
            self.store.save(owner, body, lambda _owner, _location: None)
            return result
        self.build.side_effect = change_during_read
        response = self.client.get("/api/onboarding/sales", params={"expected_revision": saved["revision"]})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertNotIn("total", response.json())
        self.assertEqual(self.state()["profile"]["business_status"], "planning")

    def test_sales_failure_has_no_internal_details_and_preserves_saved_conditions(self):
        saved = self.selected()
        self.build.side_effect = OSError("C:/private/.env")
        response = self.client.get("/api/onboarding/sales")
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("private", response.text)
        self.assertNotIn(".env", response.text)
        self.assertEqual(self.state()["analysis_selection"], saved["analysis_selection"])
        self.assertEqual(self.state()["revision"], saved["revision"])


if __name__ == "__main__":
    unittest.main()
