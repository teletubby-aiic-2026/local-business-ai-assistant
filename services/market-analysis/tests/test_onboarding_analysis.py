"""Analysis setup HTTP contracts with a synthetic catalogue and memory SQLite.

Catalogue geography/data correctness belongs to its independent source tests.
These tests exercise session state, honest readiness, validation and revision
boundaries without .env, model calls or external Maps requests.
"""
from contextlib import ExitStack
from copy import deepcopy
import importlib
import json
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.onboarding import COOKIE_NAME, SESSION_TTL, OnboardingStore
from tests.test_onboarding import Clock, FakeMaps, intake_api


class FakeAnalysisCatalogue:
    def __init__(self):
        self.version = "synthetic-catalogue-v1"
        self.calls = []
        self.no_data = set()
        self.population_only = set()
        self.blocked = False

    def options(self, location, industry_code):
        self.calls.append((deepcopy(location), industry_code))
        area_code = "2222222" if location["label"] == "연남동" else "1111111"
        no_data = industry_code in self.no_data or self.blocked
        population_only = industry_code in self.population_only
        periods = []
        for code in ("20262", "20261"):
            metrics = {key: {"status": "no_observation" if no_data or (population_only and specific) else "available",
                             "label": key, "industry_specific": specific}
                       for key, specific in (("sales", True), ("stores", True), ("floating_population", False))}
            if not no_data and not population_only:
                metrics["stores"]["zero_observation"] = True
            periods.append({"code": code, "label": code, "available": not no_data,
                "industry_data_available": not no_data and not population_only,
                "population_only": not no_data and population_only, "metrics": metrics})
        availability = {"periods": periods, "available_periods": [] if no_data else ["20262", "20261"]}
        candidate = {"area_code": area_code, "name": "합성 상권 " + area_code,
            "district_code": location["district_code"], "district_name": location["district_name"],
            "geometry": {"type": "Polygon", "coordinates": [[[126.9, 37.5], [126.91, 37.5],
                [126.91, 37.51], [126.9, 37.5]]]}, "relation": "nearby", "distance_m": 100.0,
            "available_periods": availability["available_periods"], "availability": availability}
        if self.blocked:
            candidate.update(boundary_identity_status="name_mismatch", selection_blocked_reason="합성 경계 불일치")
        return {"catalog_version": self.version, "status": "no_data" if no_data else "available",
            "message": "합성 시험 자료", "candidates": [candidate], "candidate_count": 1, "truncated": False,
            "scope": {"boundary_publication_date": "2023-10-23", "compatibility": "unverified"}}

    def validate(self, location, industry_code, area_code, period, expected_catalog_version=None):
        options = self.options(location, industry_code)
        if expected_catalog_version != self.version:
            raise ValueError("자료 버전이 변경됐습니다.")
        candidate = next((c for c in options["candidates"] if c["area_code"] == area_code), None)
        if candidate is None:
            raise ValueError("현재 위치의 후보가 아닙니다.")
        if period not in candidate["available_periods"]:
            raise ValueError("이 상권·업종·기간의 자료가 없습니다.")
        availability = next(p for p in candidate["availability"]["periods"] if p["code"] == period)
        return {"area_code": area_code, "area_name": candidate["name"], "period": period, "period_label": period,
            "industry_code": industry_code, "catalog_version": self.version, "availability": availability,
            "boundary": {"publication_date": "2023-10-23", "compatibility": "unverified",
                         "source_url": "https://example.test/synthetic-boundary"},
            "ready_for_analysis": False, "analysis_setup_complete": True, "analysis_stage": "configuration_only"}


class OnboardingAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.clock = Clock()
        self.store = OnboardingStore(":memory:", clock=self.clock)
        self.stack.callback(self.store.close)
        self.maps = FakeMaps()
        self.stack.enter_context(patch.object(intake_api, "load_settings", return_value=None))
        self.stack.enter_context(patch.object(intake_api, "MapsClient", return_value=self.maps))
        self.catalogue = FakeAnalysisCatalogue()
        module = ModuleType("app.onboarding_analysis_catalog")
        module.get_analysis_options = self.catalogue.options
        module.validate_analysis_selection = self.catalogue.validate
        self.stack.enter_context(patch.dict(sys.modules, {module.__name__: module}))
        self.app = intake_api.create_app(onboarding_store=self.store)
        self.client = self.stack.enter_context(TestClient(self.app))
        options = self.client.get("/api/onboarding/options").json()
        self.mapo = next(d["code"] for d in options["districts"] if d["name"] == "마포구")
        self.coffee = next(i["code"] for i in options["industries"] if i["name"] == "커피-음료")
        self.photography = next(i["code"] for i in options["industries"] if i["name"] == "사진관")

    def tearDown(self):
        self.assertEqual(self.maps.calls, [])

    def profile_body(self, *, text="합정동", industry_code=None, expected_revision=0, **updates):
        body = {"location": {"kind": "area", "text": text, "district_code": self.mapo},
            "industry_code": industry_code or self.coffee, "business_status": "operating",
            "expected_revision": expected_revision}
        body.update(updates)
        return body

    def save_profile(self, body=None, client=None):
        result = (client or self.client).post("/api/onboarding/profile", json=body or self.profile_body())
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def state(self, client=None):
        response = (client or self.client).get("/api/onboarding/analysis-selection")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return response.json()

    def options(self, client=None):
        result = (client or self.client).get("/api/onboarding/analysis-options")
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def selection_body(self, options=None, **updates):
        options = options or self.options()
        body = {"area_code": options["candidates"][0]["area_code"], "period": "20262",
            "expected_revision": options["revision"], "expected_catalog_version": options["catalog_version"]}
        body.update(updates)
        return body

    def save_selection(self, body=None, client=None):
        result = (client or self.client).post("/api/onboarding/analysis-selection", json=body or self.selection_body())
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def selected(self):
        self.save_profile()
        return self.save_selection()

    def test_analysis_setup_requires_a_saved_profile(self):
        state = self.state()
        self.assertEqual(state["revision"], 0)
        self.assertIsNone(state["profile"])
        self.assertIsNone(state["analysis_selection"])
        self.assertFalse(state["analysis_setup_complete"])
        self.assertEqual(self.client.get("/api/onboarding/analysis-options").status_code, 409)
        self.assertEqual(self.client.get("/api/onboarding/context").status_code, 409)
        response = self.client.post("/api/onboarding/analysis-selection", json={"area_code": "1111111", "period": "20262",
            "expected_revision": 0, "expected_catalog_version": self.catalogue.version})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.catalogue.calls, [])

    def test_options_use_saved_location_industry_and_do_not_auto_select(self):
        profile = self.save_profile()["profile"]
        result = self.options()
        self.assertEqual(result["profile"], profile)
        self.assertEqual(result["revision"], profile["revision"])
        self.assertEqual(result["catalog_version"], self.catalogue.version)
        self.assertTrue(result["candidates"][0]["geometry"])
        self.assertIsNone(result["analysis_selection"])
        self.assertFalse(result["conditions_confirmed"])
        self.assertFalse(result["ready_for_analysis"])
        self.assertEqual(self.catalogue.calls[-1], (profile["location"], profile["industry"]["code"]))

    def test_selection_restores_server_fields_and_context_without_claiming_execution_ready(self):
        saved = self.selected()
        selection = saved["analysis_selection"]
        self.assertEqual(saved["revision"], 2)
        self.assertEqual(saved["profile"]["revision"], 2)
        self.assertEqual(selection["area_code"], "1111111")
        self.assertEqual(selection["industry_code"], self.coffee)
        self.assertEqual(selection["boundary"]["compatibility"], "unverified")
        self.assertTrue(saved["analysis_setup_complete"])
        self.assertTrue(selection["conditions_confirmed"])
        self.assertFalse(selection["ready_for_analysis"])
        self.assertFalse(saved["profile"]["ready_for_analysis"])
        self.assertEqual(self.state()["analysis_selection"], selection)
        context = self.client.get("/api/onboarding/context").json()
        self.assertEqual(context["analysis_area"]["code"], "1111111")
        self.assertEqual(context["data_period"], "20262")
        self.assertEqual(context["catalog_version"], self.catalogue.version)
        self.assertEqual(context["availability"], selection["availability"])
        self.assertTrue(context["analysis_setup_complete"])
        self.assertFalse(context["ready_for_analysis"])

    def test_selection_fields_are_required_and_client_facts_cannot_be_injected(self):
        original = self.save_profile()["profile"]
        valid = self.selection_body()
        invalid = [{k: v for k, v in valid.items() if k != missing} for missing in valid]
        invalid += [{**valid, field: value} for field, value in (
            ("latitude", 37.5), ("longitude", 127.0), ("industry_code", self.photography),
            ("area_name", "임의 상권"), ("ready_for_analysis", True),
            ("availability", {"available": True}), ("expected_revision", True),
            ("area_code", "123"), ("period", "20265"), ("period", None), ("expected_revision", -1))]
        for body in invalid:
            with self.subTest(body=body):
                response = self.client.post("/api/onboarding/analysis-selection", json=body)
                self.assertEqual(response.status_code, 422, response.text)
        state = self.state()
        self.assertEqual(state["profile"], original)
        self.assertIsNone(state["analysis_selection"])

    def test_known_area_outside_saved_location_candidates_is_rejected(self):
        self.save_profile()
        response = self.client.post("/api/onboarding/analysis-selection", json=self.selection_body(area_code="2222222"))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIsNone(self.state()["analysis_selection"])

    def test_unavailable_period_is_not_replaced_with_latest(self):
        self.save_profile()
        response = self.client.post("/api/onboarding/analysis-selection", json=self.selection_body(period="20254"))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIsNone(self.state()["analysis_selection"])

    def test_no_data_industry_is_preserved_and_cannot_silently_become_coffee(self):
        self.catalogue.no_data.add(self.photography)
        profile = self.save_profile(self.profile_body(industry_code=self.photography))["profile"]
        options = self.options()
        self.assertEqual(options["status"], "no_data")
        self.assertEqual(options["candidates"][0]["available_periods"], [])
        response = self.client.post("/api/onboarding/analysis-selection", json=self.selection_body(options))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.state()["profile"], profile)
        self.assertTrue(all(industry == self.photography for _, industry in self.catalogue.calls))

    def test_population_only_can_confirm_conditions_but_industry_data_remains_absent(self):
        self.catalogue.population_only.add(self.photography)
        self.save_profile(self.profile_body(industry_code=self.photography))
        selected = self.save_selection()
        availability = selected["analysis_selection"]["availability"]
        self.assertTrue(availability["population_only"])
        self.assertFalse(availability["industry_data_available"])
        self.assertEqual(availability["metrics"]["sales"]["status"], "no_observation")
        self.assertEqual(availability["metrics"]["floating_population"]["status"], "available")
        self.assertTrue(selected["analysis_setup_complete"])
        self.assertFalse(selected["ready_for_analysis"])

    def test_observed_zero_is_available_instead_of_missing(self):
        selection = self.selected()["analysis_selection"]
        stores = selection["availability"]["metrics"]["stores"]
        self.assertEqual(stores["status"], "available")
        self.assertTrue(stores["zero_observation"])

    def test_stale_profile_revision_rejects_selection_without_overwrite(self):
        self.save_profile()
        old = self.selection_body()
        updated = self.save_profile(self.profile_body(location=None, business_status="planning", expected_revision=1))
        response = self.client.post("/api/onboarding/analysis-selection", json=old)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.state()["profile"], updated["profile"])
        self.assertIsNone(self.state()["analysis_selection"])

    def test_catalogue_version_change_requires_reloading_before_save(self):
        original = self.save_profile()["profile"]
        old = self.selection_body()
        self.catalogue.version = "synthetic-catalogue-v2"
        response = self.client.post("/api/onboarding/analysis-selection", json=old)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.state()["profile"], original)
        self.assertIsNone(self.state()["analysis_selection"])

    def test_existing_selection_becomes_stale_after_catalogue_change_without_implicit_resave(self):
        saved = self.selected()
        self.catalogue.version = "synthetic-catalogue-v2"
        state = self.state()
        self.assertEqual(state["revision"], saved["revision"])
        self.assertEqual(state["analysis_selection"]["status"], "stale")
        self.assertEqual(state["analysis_selection"]["area_code"], "1111111")
        self.assertFalse(state["conditions_confirmed"])
        self.assertFalse(state["analysis_setup_complete"])
        context = self.client.get("/api/onboarding/context").json()
        self.assertIsNone(context["analysis_area"])
        self.assertIsNone(context["data_period"])
        self.assertFalse(context["ready_for_analysis"])
        self.assertEqual(self.options()["catalog_version"], "synthetic-catalogue-v2")

    def test_status_only_change_preserves_selection_and_advances_shared_revision(self):
        selected = self.selected()
        updated = self.save_profile(self.profile_body(location=None, business_status="planning", expected_revision=2))
        self.assertEqual(updated["revision"], 3)
        self.assertEqual(updated["profile"]["revision"], 3)
        self.assertEqual(updated["analysis_selection"], selected["analysis_selection"])
        self.assertTrue(updated["conditions_confirmed"])

    def test_location_change_clears_selection_and_uses_new_candidates(self):
        self.selected()
        updated = self.save_profile(self.profile_body(text="연남동", expected_revision=2))
        self.assertIsNone(updated["analysis_selection"])
        self.assertFalse(updated["analysis_setup_complete"])
        self.assertEqual(self.options()["candidates"][0]["area_code"], "2222222")
        self.assertIsNone(self.client.get("/api/onboarding/context").json()["analysis_area"])

    def test_industry_change_clears_selection_even_if_some_data_exists(self):
        self.selected()
        updated = self.save_profile(self.profile_body(location=None, industry_code=self.photography, expected_revision=2))
        self.assertIsNone(updated["analysis_selection"])
        self.assertEqual(updated["profile"]["industry"]["code"], self.photography)
        self.assertFalse(updated["conditions_confirmed"])

    def test_resaving_identical_location_and_industry_keeps_selection(self):
        selected = self.selected()
        updated = self.save_profile(self.profile_body(expected_revision=2))
        self.assertEqual(updated["analysis_selection"], selected["analysis_selection"])
        self.assertTrue(updated["analysis_setup_complete"])

    def test_rejected_profile_edit_does_not_invalidate_selection(self):
        saved = self.selected()
        response = self.client.post("/api/onboarding/profile", json=self.profile_body(
            text="연남동", industry_code="INVALID", expected_revision=2))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.state()["analysis_selection"], saved["analysis_selection"])
        self.assertEqual(self.state()["profile"], saved["profile"])

    def test_sessions_cannot_replace_each_others_analysis_or_use_foreign_candidates(self):
        mine = self.selected()
        other = self.stack.enter_context(TestClient(self.app))
        their_profile = self.save_profile(self.profile_body(text="연남동"), client=other)
        wrong = self.selection_body(self.options(other), area_code=mine["analysis_selection"]["area_code"])
        rejected = other.post("/api/onboarding/analysis-selection", json=wrong)
        self.assertEqual(rejected.status_code, 422, rejected.text)
        theirs = self.save_selection(self.selection_body(self.options(other)), client=other)
        self.assertEqual(theirs["analysis_selection"]["area_code"], "2222222")
        self.assertEqual(self.state()["analysis_selection"], mine["analysis_selection"])
        self.assertEqual(self.state(other)["profile"]["location"], their_profile["profile"]["location"])

    def test_delete_selection_preserves_profile_and_revision_protects_old_requests(self):
        saved = self.selected()
        stale = self.client.delete("/api/onboarding/analysis-selection", params={"expected_revision": 1})
        self.assertEqual(stale.status_code, 409, stale.text)
        missing = self.client.delete("/api/onboarding/analysis-selection")
        self.assertEqual(missing.status_code, 422, missing.text)
        deleted = self.client.delete("/api/onboarding/analysis-selection", params={"expected_revision": 2})
        self.assertEqual(deleted.status_code, 200, deleted.text)
        state = deleted.json()
        self.assertEqual(state["revision"], 3)
        self.assertEqual(state["profile"]["location"], saved["profile"]["location"])
        self.assertIsNone(state["analysis_selection"])
        old = self.client.post("/api/onboarding/analysis-selection", json=self.selection_body(expected_revision=2))
        self.assertEqual(old.status_code, 409, old.text)
        self.assertEqual(self.save_selection()["revision"], 4)

    def test_profile_reset_also_removes_analysis_selection(self):
        self.selected()
        result = self.client.delete("/api/onboarding/profile", params={"expected_revision": 2})
        self.assertEqual(result.status_code, 200, result.text)
        state = self.state()
        self.assertEqual(state["revision"], 3)
        self.assertIsNone(state["profile"])
        self.assertIsNone(state["analysis_selection"])

    def test_same_cookie_restores_profile_and_selection_in_a_new_browser_client(self):
        saved = self.selected()
        restored = self.stack.enter_context(TestClient(self.app))
        restored.cookies.set(COOKIE_NAME, self.client.cookies.get(COOKIE_NAME))
        self.assertEqual(self.state(restored)["analysis_selection"], saved["analysis_selection"])
        self.assertEqual(self.state(restored)["profile"], saved["profile"])

    def test_expired_session_does_not_resurrect_its_analysis_selection(self):
        self.selected()
        self.clock.value += SESSION_TTL + 1
        state = self.state()
        self.assertEqual(state["revision"], 0)
        self.assertIsNone(state["profile"])
        self.assertIsNone(state["analysis_selection"])

    def test_same_revision_can_commit_only_one_selection(self):
        self.save_profile()
        request = self.selection_body()
        first = self.save_selection(request)
        response = self.client.post("/api/onboarding/analysis-selection", json={**request, "period": "20261"})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.state()["analysis_selection"], first["analysis_selection"])

    def test_boundary_identity_mismatch_cannot_be_saved_even_if_candidate_is_shown(self):
        self.catalogue.blocked = True
        self.save_profile()
        options = self.options()
        self.assertEqual(options["candidates"][0]["boundary_identity_status"], "name_mismatch")
        response = self.client.post("/api/onboarding/analysis-selection", json=self.selection_body(options))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIsNone(self.state()["analysis_selection"])

    def test_catalogue_failure_is_503_without_details_and_does_not_break_profile_or_context(self):
        self.selected()
        module = sys.modules["app.onboarding_analysis_catalog"]
        for failure in (OSError("C:/private/source-file.json"), ValueError("secret catalogue hash"), KeyError("internal-path")):
            with self.subTest(failure=type(failure).__name__):
                revision = self.state()["revision"]
                with patch.object(module, "get_analysis_options", side_effect=failure):
                    options = self.client.get("/api/onboarding/analysis-options")
                    self.assertEqual(options.status_code, 503, options.text)
                    response = self.client.post("/api/onboarding/analysis-selection", json={
                        "area_code": "1111111", "period": "20262", "expected_revision": revision,
                        "expected_catalog_version": self.catalogue.version})
                    self.assertEqual(response.status_code, 503, response.text)
                    for body in (options.text, response.text):
                        self.assertNotIn(str(failure), body)
                        self.assertNotIn("private", body)
                        self.assertNotIn("secret", body)
                    state = self.state()
                    self.assertEqual(state["analysis_selection"]["status"], "unavailable")
                    self.assertFalse(state["analysis_setup_complete"])
                    self.assertEqual(self.client.get("/api/onboarding/profile").status_code, 200)
                    context = self.client.get("/api/onboarding/context")
                    self.assertEqual(context.status_code, 200, context.text)
                    self.assertIsNone(context.json()["analysis_area"])
                    changed = self.save_profile(self.profile_body(location=None, business_status="planning",
                                                                  expected_revision=revision))
                    self.assertEqual(changed["analysis_selection"]["status"], "unavailable")
                    self.assertEqual(changed["revision"], revision + 1)

    def test_corrupt_or_incomplete_saved_selection_is_stale_without_losing_profile(self):
        saved = self.selected()
        bad = deepcopy(saved["analysis_selection"])
        bad.pop("area_code")
        for payload in (json.dumps(bad), "[]", "not json"):
            with self.subTest(payload=payload):
                with self.store.connection:
                    self.store.connection.execute("UPDATE onboarding_analysis_selections SET selection=?", (payload,))
                state = self.state()
                self.assertEqual(state["analysis_selection"]["status"], "stale")
                self.assertFalse(state["conditions_confirmed"])
                self.assertEqual(state["profile"], saved["profile"])
                self.assertEqual(self.client.get("/api/onboarding/profile").status_code, 200)
                context = self.client.get("/api/onboarding/context")
                self.assertEqual(context.status_code, 200, context.text)
                self.assertIsNone(context.json()["analysis_area"])
        self.assertTrue(self.save_selection()["conditions_confirmed"])



if __name__ == "__main__":
    unittest.main()
