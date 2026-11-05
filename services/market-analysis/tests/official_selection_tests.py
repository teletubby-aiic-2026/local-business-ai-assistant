"""Saved selection round trip against prepared official data."""
import unittest
import sys
import importlib
from unittest.mock import patch
from tests.test_onboarding_analysis import OnboardingAnalysisTests

class OfficialSelectionTests(unittest.TestCase):
    setUp = OnboardingAnalysisTests.setUp
    tearDown = OnboardingAnalysisTests.tearDown
    profile_body = OnboardingAnalysisTests.profile_body
    save_profile = OnboardingAnalysisTests.save_profile
    state = OnboardingAnalysisTests.state
    options = OnboardingAnalysisTests.options
    selection_body = OnboardingAnalysisTests.selection_body
    save_selection = OnboardingAnalysisTests.save_selection
    selected = OnboardingAnalysisTests.selected

    def test_real_offline_catalogue_round_trip_uses_server_candidate_and_period(self):
        # One integration path uses the preserved official snapshot; the other
        # tests remain independent of that catalogue's own validation logic.
        with patch.dict(sys.modules):
            del sys.modules["app.onboarding_analysis_catalog"]
            importlib.import_module("app.onboarding_analysis_catalog")
            stations = self.client.get("/api/onboarding/options").json()["stations"]
            station = next(s for s in stations if s["name"] == "이태원역")
            profile = self.save_profile(self.profile_body(location={"kind": "station", "station_id": station["id"]}))
            options = self.options()
            candidate = next(c for c in options["candidates"] if c["available_periods"])
            body = {"area_code": candidate["area_code"], "period": candidate["available_periods"][0],
                    "expected_revision": profile["revision"], "expected_catalog_version": options["catalog_version"]}
            saved = self.save_selection(body)
            selection = saved["analysis_selection"]
            self.assertEqual(selection["area_code"], candidate["area_code"])
            self.assertEqual(selection["period"], body["period"])
            self.assertEqual(selection["catalog_version"], options["catalog_version"])
            self.assertEqual(selection["industry_code"], self.coffee)
            self.assertTrue(saved["conditions_confirmed"])
            self.assertFalse(saved["ready_for_analysis"])
            self.assertEqual(self.state()["analysis_selection"], selection)
