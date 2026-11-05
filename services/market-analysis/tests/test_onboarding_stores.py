"""B3 counts, collection scope, provenance and read-only HTTP contracts."""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from app import onboarding_stores as stores
from app.data_repository import SOURCE_URLS, canonical_hash
from app.onboarding import COOKIE_NAME, ProfileInput
from tests import test_onboarding_analysis as setup_helpers


def selection():
    return {"area_code": "1111111", "area_name": "합성 상권 1111111", "industry_code": "CS100010",
        "period": "20262", "period_label": "2026년 2분기", "catalog_version": "synthetic-catalogue-v1",
        "boundary": {"publication_date": "2023-10-23", "compatibility": "unverified"}}


def row_fixture():
    return {"STDR_YYQU_CD": "20262", "TRDAR_CD": "1111111", "TRDAR_CD_NM": "합성 상권 1111111",
        "SVC_INDUTY_CD": "CS100010", "SVC_INDUTY_CD_NM": "커피-음료",
        "SIMILR_INDUTY_STOR_CO": 12, "STOR_CO": 9, "FRC_STOR_CO": 3, "OPBIZ_STOR_CO": 2, "CLSBIZ_STOR_CO": 4}


def analyze(row, **kwargs):
    return stores.analyze_stores_row(row, selection(), "커피-음료", **kwargs)


class StoresSemanticsTests(unittest.TestCase):
    def test_five_counts_are_distinct_and_franchise_share_has_total_denominator(self):
        result = analyze(row_fixture())
        self.assertEqual(result["status"], "available")
        self.assertEqual({key: item["value"] for key, item in result["counts"].items()},
                         {"total": 12, "general": 9, "franchise": 3, "opened": 2, "closed": 4})
        self.assertEqual(result["composition"]["sum"], 12)
        self.assertEqual(result["composition"]["difference"], 0)
        self.assertEqual(result["composition"]["franchise_share_percent"], 25.0)
        self.assertEqual(result["composition"]["denominator"]["value"], 12)
        self.assertNotIn("opening_rate", result)
        self.assertNotIn("net_change", result)

    def test_zero_inventory_and_closures_above_inventory_are_valid_observations(self):
        for total, closed in ((0, 2), (1, 2)):
            with self.subTest(total=total):
                row = row_fixture()
                row.update(SIMILR_INDUTY_STOR_CO=total, STOR_CO=total, FRC_STOR_CO=0, CLSBIZ_STOR_CO=closed)
                result = analyze(row)
                self.assertEqual(result["status"], "available")
                self.assertEqual(result["counts"]["closed"]["value"], closed)
                self.assertEqual(result["composition"]["status"], "consistent")
                self.assertEqual(result["composition"]["franchise_share_percent"], 0.0 if total else None)

    def test_sum_mismatch_keeps_raw_values_and_blocks_share(self):
        row = row_fixture()
        row["FRC_STOR_CO"] = 4
        result = analyze(row)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["counts"]["franchise"]["value"], 4)
        self.assertEqual(result["composition"]["status"], "inconsistent")
        self.assertEqual(result["composition"]["difference"], 1)
        self.assertIsNone(result["composition"]["franchise_share_percent"])

    def test_missing_composition_item_is_not_zero_and_cannot_support_share(self):
        row = row_fixture()
        row.pop("STOR_CO")
        result = analyze(row)
        self.assertEqual(result["counts"]["general"]["status"], "missing")
        self.assertIsNone(result["counts"]["general"]["value"])
        self.assertEqual(result["composition"]["status"], "incomplete")
        self.assertIsNone(result["composition"]["franchise_share_percent"])

    def test_missing_openings_does_not_remove_valid_inventory_composition(self):
        row = row_fixture()
        row.pop("OPBIZ_STOR_CO")
        result = analyze(row)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["counts"]["opened"]["status"], "missing")
        self.assertEqual(result["composition"]["franchise_share_percent"], 25.0)

    def test_uncollected_scope_and_absent_industry_row_are_distinct(self):
        for collected, expected in ((False, "not_collected"), (True, "no_observation")):
            with self.subTest(collected=collected):
                result = analyze(None, collected=collected)
                self.assertEqual(result["status"], expected)
                self.assertTrue(all(item["status"] == expected and item["value"] is None for item in result["counts"].values()))
                self.assertEqual(result["summary"], [])
                self.assertEqual(result["composition"]["status"], "no_data")

    def test_invalid_and_fractional_counts_are_not_silently_rounded(self):
        for value in (True, -1, "1.5", 1.5, float("inf"), Decimal("NaN"), Decimal("1.5"), Decimal("-1")):
            with self.subTest(value=str(value)):
                row = row_fixture()
                row["FRC_STOR_CO"] = value
                result = analyze(row)
                self.assertEqual(result["status"], "invalid")
                self.assertEqual(result["counts"]["franchise"]["status"], "invalid")
                self.assertIsNone(result["composition"]["franchise_share_percent"])

    def test_large_exact_counts_keep_integer_and_text(self):
        row = row_fixture()
        amount = 2 ** 53 + 1
        row.update(SIMILR_INDUTY_STOR_CO=Decimal(str(amount)), STOR_CO=str(amount - 1), FRC_STOR_CO=1)
        result = analyze(row)
        self.assertEqual(result["counts"]["total"]["value"], amount)
        self.assertEqual(result["counts"]["total"]["value_text"], str(amount))
        self.assertEqual(result["composition"]["difference"], 0)


class StoresProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="b3-synthetic-source-")
        self.addCleanup(self.directory.cleanup)
        self.raw = Path(self.directory.name)
        self.source = {"catalog_version": "synthetic-catalogue-v1", "files": []}
        self.patcher = patch.object(stores, "get_analysis_catalog_source", side_effect=lambda: deepcopy(self.source))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.profile = {"industry": {"code": "CS100010", "name": "커피-음료"}}

    def page(self, rows, start=1, total=None, area_code="1111111", period="20262"):
        payload = {"VwsmTrdarStorQq": {"RESULT": {"CODE": "INFO-000"}, "row": rows,
                                      "list_total_count": len(rows) if total is None else total}}
        doc = {"query": {"dataset": "stores", "period": period, "area_code": area_code, "start": start, "count": len(rows)},
            "payload": payload, "payload_sha256": canonical_hash(payload), "service": "VwsmTrdarStorQq",
            "source_url": SOURCE_URLS["stores"], "sample_only": False}
        path = self.raw / f"stores_{period}_{area_code or 'all'}_{start}.json"
        data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        path.write_bytes(data)
        self.source["files"].append({"path": "data/raw/official/" + path.name, "dataset": "stores", "period": period,
            "area_code": area_code, "file_sha256": sha256(data).hexdigest(), "payload_sha256": doc["payload_sha256"],
            "start": start, "row_count": len(rows)})
        return path

    def build(self, selected=None):
        return stores.build_stores_analysis(selected or selection(), self.profile, raw_root=self.raw)

    def test_source_proof_and_warm_cache_are_repeatable(self):
        path = self.page([row_fixture()])
        first = self.build()
        self.assertEqual(first, self.build())
        self.assertEqual(first["evidence"][0]["file_name"], path.name)
        self.assertEqual(first["counts"]["total"]["value"], 12)
        self.assertEqual(first["source"]["collected_area_count"], 1)

    def test_citywide_pages_cover_other_areas_and_preserve_legacy_without_double_counting(self):
        legacy = self.page([row_fixture()])
        other = {**row_fixture(), "TRDAR_CD": "2222222", "TRDAR_CD_NM": "다른 상권", "SIMILR_INDUTY_STOR_CO": 20, "STOR_CO": 17}
        first_page = self.page([row_fixture()], total=2, area_code=None)
        second_page = self.page([other], start=2, total=2, area_code=None)
        first = self.build()
        self.assertEqual(first["counts"]["total"]["value"], 12)
        self.assertEqual(first["source"]["collection_scope"], "citywide")
        self.assertEqual(first["source"]["collected_area_count"], 2)
        self.assertEqual([entry["file_name"] for entry in first["evidence"]], [first_page.name])
        self.assertTrue(legacy.exists())
        with patch.object(stores.json, "loads", side_effect=AssertionError("Citywide warm lookup reparsed source")):
            second = self.build({**selection(), "area_code": "2222222", "area_name": "다른 상권"})
        self.assertEqual(second["counts"]["total"]["value"], 20)
        self.assertEqual(second["evidence"][0]["file_name"], second_page.name)
        self.assertIn("서울 전체 조회", first["source"]["coverage_note"])
        self.assertNotIn("10개", first["source"]["coverage_note"])

    def test_citywide_absent_area_is_no_observation_and_exact_period_absence_is_not_collected(self):
        self.page([row_fixture()], area_code=None)
        missing_area = self.build({**selection(), "area_code": "2222222", "area_name": "다른 상권"})
        self.assertEqual(missing_area["status"], "no_observation")
        self.assertTrue(missing_area["evidence"])
        missing_period = self.build({**selection(), "period": "20261", "period_label": "2026년 1분기"})
        self.assertEqual(missing_period["status"], "not_collected")
        self.assertEqual(missing_period["evidence"], [])

    def test_citywide_incomplete_or_corrupt_source_never_uses_preserved_legacy(self):
        self.page([row_fixture()])
        path = self.page([row_fixture()], total=2, area_code=None)
        with self.assertRaisesRegex(stores.StoresDataError, "Incomplete"):
            self.build()
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(stores.StoresDataError, "hash"):
            self.build()

    def test_changed_citywide_page_invalidates_other_area_warm_lookup(self):
        first = self.page([row_fixture()], total=2, area_code=None)
        self.page([{**row_fixture(), "TRDAR_CD": "2222222"}], start=2, total=2, area_code=None)
        self.build()
        first.write_bytes(first.read_bytes() + b"\n")
        with self.assertRaises(stores.StoresDataError):
            self.build({**selection(), "area_code": "2222222"})

    def test_uncollected_area_does_not_borrow_another_areas_counts(self):
        self.page([row_fixture()])
        result = self.build({**selection(), "area_code": "2222222", "area_name": "다른 상권"})
        self.assertEqual(result["status"], "not_collected")
        self.assertEqual(result["evidence"], [])
        self.assertIsNone(result["counts"]["total"]["value"])

    def test_collected_area_with_no_industry_row_does_not_become_zero(self):
        row = row_fixture()
        row.update(SVC_INDUTY_CD="CS200041", SVC_INDUTY_CD_NM="사진관")
        self.page([row])
        result = self.build()
        self.assertEqual(result["status"], "no_observation")
        self.assertTrue(result["evidence"])
        self.assertIsNone(result["counts"]["total"]["value"])

    def test_changed_source_after_cache_is_rejected(self):
        path = self.page([row_fixture()])
        self.build()
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(stores.StoresDataError):
            self.build()

    def test_payload_hash_duplicate_rows_and_missing_pages_are_rejected(self):
        path = self.page([row_fixture()], start=2, total=2)
        with self.assertRaises(stores.StoresDataError):
            self.build()
        self.page([row_fixture()], start=1, total=2)
        with self.assertRaises(stores.StoresDataError):
            self.build()
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["payload"]["VwsmTrdarStorQq"]["row"][0]["STOR_CO"] = 100
        data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        path.write_bytes(data)
        self.source["files"][0]["file_sha256"] = sha256(data).hexdigest()
        with self.assertRaises(stores.StoresDataError):
            self.build()

    def test_decimal_source_token_is_preserved_and_fractional_token_rejected(self):
        path = self.page([row_fixture()])
        original = path.read_text(encoding="utf-8")
        old_hash = self.source["files"][0]["payload_sha256"]
        for token, expected in (("9007199254740993.0", 9007199254740993), ("9007199254740990.5", None)):
            text = original.replace('"SIMILR_INDUTY_STOR_CO": 12', '"SIMILR_INDUTY_STOR_CO": ' + token)
            payload_hash = canonical_hash(json.loads(text)["payload"])
            data = text.replace(old_hash, payload_hash).encode("utf-8")
            path.write_bytes(data)
            self.source["files"][0].update(file_sha256=sha256(data).hexdigest(), payload_sha256=payload_hash)
            count = self.build()["counts"]["total"]
            self.assertEqual(count["value"], expected)
            self.assertEqual(count["status"], "available" if expected is not None else "invalid")


class StoresHttpTests(unittest.TestCase):
    profile_body = setup_helpers.OnboardingAnalysisTests.profile_body
    save_profile = setup_helpers.OnboardingAnalysisTests.save_profile
    state = setup_helpers.OnboardingAnalysisTests.state
    options = setup_helpers.OnboardingAnalysisTests.options
    selection_body = setup_helpers.OnboardingAnalysisTests.selection_body
    save_selection = setup_helpers.OnboardingAnalysisTests.save_selection
    selected = setup_helpers.OnboardingAnalysisTests.selected

    def setUp(self):
        setup_helpers.OnboardingAnalysisTests.setUp(self)
        self.build = self.stack.enter_context(patch.object(stores, "build_stores_analysis", side_effect=self.fake_build))

    def tearDown(self):
        setup_helpers.OnboardingAnalysisTests.tearDown(self)

    def fake_build(self, selected, profile):
        return {**stores.analyze_stores_row(row_fixture(), selected, profile["industry"]["name"]),
                "data_version": "synthetic-stores", "source": {"url": SOURCE_URLS["stores"]}, "evidence": []}

    def test_get_uses_saved_conditions_and_does_not_change_selection_or_revision(self):
        saved = self.selected()
        first = self.client.get("/api/onboarding/stores", params={"expected_revision": saved["revision"]})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.headers["cache-control"], "no-store")
        self.assertEqual(first.json()["feature"], "stores")
        self.assertEqual(first.json()["analysis_stage"], "stores_result")
        self.assertEqual(first.json(), self.client.get("/api/onboarding/stores").json())
        self.assertEqual(self.state()["profile"], saved["profile"])
        self.assertEqual(self.state()["analysis_selection"], saved["analysis_selection"])

    def test_missing_selection_and_stale_revision_are_409(self):
        self.assertEqual(self.client.get("/api/onboarding/stores").status_code, 409)
        self.save_profile()
        self.assertEqual(self.client.get("/api/onboarding/stores").status_code, 409)
        saved = self.save_selection()
        self.assertEqual(self.client.get("/api/onboarding/stores", params={"expected_revision": saved["revision"] - 1}).status_code, 409)
        self.build.assert_not_called()

    def test_client_cannot_inject_area_industry_period_or_coordinates(self):
        self.selected()
        for query in ({"area_code": "2222222"}, {"industry_code": self.photography}, {"period": "20261"}, {"longitude": 127.0}):
            response = self.client.get("/api/onboarding/stores", params=query)
            self.assertEqual(response.status_code, 422, response.text)
        self.build.assert_not_called()

    def test_stale_and_unavailable_selection_block_read(self):
        self.selected()
        self.catalogue.version = "changed-version"
        self.assertEqual(self.client.get("/api/onboarding/stores").status_code, 409)
        self.catalogue.version = "synthetic-catalogue-v1"
        with patch.object(sys.modules["app.onboarding_analysis_catalog"], "get_analysis_options", side_effect=OSError("internal-file")):
            response = self.client.get("/api/onboarding/stores")
            self.assertEqual(response.status_code, 503, response.text)
            self.assertNotIn("internal-file", response.text)
        self.build.assert_not_called()

    def test_profile_change_during_read_rejects_old_result(self):
        saved = self.selected()
        def changing_build(selected, profile):
            result = self.fake_build(selected, profile)
            owner, _ = self.store.session(self.client.cookies.get(COOKIE_NAME))
            body = ProfileInput(location=None, industry_code=self.coffee, business_status="planning", expected_revision=saved["revision"])
            self.store.save(owner, body, lambda _owner, _location: None)
            return result
        self.build.side_effect = changing_build
        response = self.client.get("/api/onboarding/stores", params={"expected_revision": saved["revision"]})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertNotIn("counts", response.json())

    def test_source_failure_is_generic_503_and_preserves_profile(self):
        saved = self.selected()
        self.build.side_effect = OSError("C:/private/.env")
        response = self.client.get("/api/onboarding/stores")
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("private", response.text)
        self.assertNotIn(".env", response.text)
        self.assertEqual(self.state()["profile"], saved["profile"])

    def test_uncollected_and_no_observation_are_honest_200_results_not_service_errors(self):
        saved = self.selected()
        for collected, expected in ((False, "not_collected"), (True, "no_observation")):
            self.build.side_effect = lambda selected, profile: stores.analyze_stores_row(
                None, selected, profile["industry"]["name"], collected=collected)
            response = self.client.get("/api/onboarding/stores")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], expected)
            self.assertIsNone(response.json()["counts"]["total"]["value"])
            self.assertEqual(self.state()["analysis_selection"], saved["analysis_selection"])


if __name__ == "__main__":
    unittest.main()
