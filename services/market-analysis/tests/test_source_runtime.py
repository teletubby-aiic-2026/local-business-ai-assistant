"""Source-package smoke tests without official raw data, secrets or live APIs."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app import intake_api
from app.naver_clients import MAPS_URL, MapsClient, NaverApiError
from app.onboarding import OnboardingStore


PROFILE = {
    "location": {"kind": "area", "district_code": "11110", "neighborhood_code": "11110515"},
    "industry_code": "CS100010",
    "business_status": "operating",
    "expected_revision": 0,
}


class BasicRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.store = OnboardingStore(":memory:")
        self.addCleanup(self.store.close)

    def test_local_and_public_apps_only_expose_basic_analysis(self):
        expected = {"/api/onboarding/analysis-selection", "/api/onboarding/sales",
                    "/api/onboarding/stores", "/api/onboarding/population",
                    "/api/onboarding/comparison", "/api/onboarding/changes"}
        excluded = ("/api/intake", "/api/ask", "/conversation-preview", "/request-preview",
                    "/conversation-assets/index.html", "/request-preview-assets/index.html")
        for origin, base in (("", "http://testserver"), ("https://market.example", "https://market.example")):
            with self.subTest(origin=origin), patch.dict(os.environ, {"APP_PUBLIC_ORIGIN": origin}):
                app = intake_api.create_app(self.store)
                client = TestClient(app, base_url=base)
                paths = client.get("/openapi.json").json()["paths"]
                self.assertTrue(expected.issubset(paths))
                self.assertTrue(all(path in {"/", "/health"} or path.startswith("/api/onboarding/") for path in paths))
                for path in excluded:
                    self.assertEqual(client.get(path).status_code, 404, path)
                    self.assertEqual(client.post(path, json={}).status_code, 404, path)
                self.assertEqual(client.get("/health").json()["features"], ["B1", "B2", "B3", "B4", "B5", "B6"])

    def test_profile_round_trip_session_isolation_and_stale_revision(self):
        app = intake_api.create_app(self.store)
        first, second = TestClient(app), TestClient(app)
        saved = first.post("/api/onboarding/profile", json=PROFILE)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["profile"]["industry"]["code"], "CS100010")
        self.assertEqual(first.get("/api/onboarding/profile").json()["profile"]["location"]["neighborhood_code"], "11110515")
        self.assertIsNone(second.get("/api/onboarding/profile").json()["profile"])
        self.assertEqual(first.post("/api/onboarding/profile", json=PROFILE).status_code, 409)
        self.assertIsNone(second.get("/api/onboarding/profile").json()["profile"])

    def test_missing_analysis_data_preserves_profile_and_returns_unavailable(self):
        client = TestClient(intake_api.create_app(self.store))
        self.assertEqual(client.post("/api/onboarding/profile", json=PROFILE).status_code, 200)
        before = client.get("/api/onboarding/profile").json()
        with patch("app.onboarding_analysis_catalog.get_analysis_options", side_effect=FileNotFoundError("synthetic missing data")):
            response = client.get("/api/onboarding/analysis-options")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("synthetic", response.text)
        self.assertEqual(client.get("/api/onboarding/profile").json(), before)

    def test_public_origin_and_cookie_guards(self):
        with patch.dict(os.environ, {"APP_PUBLIC_ORIGIN": "https://market.example"}):
            client = TestClient(intake_api.create_app(self.store), base_url="https://market.example")
        response = client.get("/api/onboarding/profile")
        cookie = response.headers["set-cookie"].lower()
        for attribute in ("secure", "httponly", "samesite=strict"):
            self.assertIn(attribute, cookie)
        self.assertEqual(client.get("/health", headers={"Origin": "https://outside.example"}).status_code, 403)
        self.assertEqual(client.get("/health", headers={"Host": "outside.example"}).status_code, 400)

    def test_configured_factory_loads_origin_before_constructing_app(self):
        def settings():
            os.environ["APP_PUBLIC_ORIGIN"] = "https://market.example"

        factory = intake_api.create_app
        with patch.object(intake_api, "load_settings", side_effect=settings) as load, \
                patch.object(intake_api, "create_app", side_effect=lambda: factory(self.store)):
            app = intake_api.configured_app()
        load.assert_called_once_with()
        self.assertTrue(app.state.public_mode)
        self.assertEqual(TestClient(app, base_url="https://market.example").get("/health").status_code, 200)

    def test_factory_and_lifespan_do_not_implicitly_read_settings(self):
        with patch.object(intake_api, "load_settings", side_effect=AssertionError("No real settings")) as load, \
                patch.object(intake_api, "MapsClient") as maps:
            with TestClient(intake_api.create_app(self.store)) as client:
                self.assertEqual(client.get("/health").status_code, 200)
            load.assert_not_called()
            maps.assert_called_once_with()

    def test_profile_survives_an_independent_store_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "isolated.sqlite3"
            first_store = OnboardingStore(database)
            try:
                first = TestClient(intake_api.create_app(first_store))
                self.assertEqual(first.post("/api/onboarding/profile", json=PROFILE).status_code, 200)
                cookies = dict(first.cookies)
            finally:
                first_store.close()
            second_store = OnboardingStore(database)
            try:
                second = TestClient(intake_api.create_app(second_store), cookies=cookies)
                profile = second.get("/api/onboarding/profile").json()["profile"]
                self.assertEqual(profile["industry"]["code"], "CS100010")
                self.assertEqual(profile["location"]["neighborhood_code"], "11110515")
            finally:
                second_store.close()


class MapsClientTests(unittest.TestCase):
    def test_geocoding_uses_fixed_endpoint_and_returns_independent_cached_values(self):
        seen = []

        def respond(request):
            seen.append(request)
            self.assertEqual(str(request.url).split("?")[0], MAPS_URL)
            self.assertEqual(request.headers["x-ncp-apigw-api-key-id"], "test-client")
            self.assertEqual(request.headers["x-ncp-apigw-api-key"], "test-secret")
            return httpx.Response(200, json={"status": "OK", "addresses": [
                {"roadAddress": "서울특별시 종로구 세종대로 1", "jibunAddress": "", "x": "126.98", "y": "37.57"}]})

        client = MapsClient("test-client", "test-secret", transport=httpx.MockTransport(respond))
        first = client.geocode("서울특별시 종로구 세종대로 1")
        first[0]["latitude"] = 0
        self.assertEqual(client.geocode("서울특별시 종로구 세종대로 1")[0]["latitude"], 37.57)
        self.assertEqual(len(seen), 1)
        self.assertNotIn("test-secret", repr(client))

    def test_missing_credentials_and_invalid_coordinates_are_not_results(self):
        def prohibited(request):
            self.fail("Missing credentials must not send a request")

        with self.assertRaises(NaverApiError):
            MapsClient("", "", transport=httpx.MockTransport(prohibited)).geocode("서울시청")
        bad = httpx.MockTransport(lambda request: httpx.Response(200, json={"status": "OK", "addresses": [
            {"roadAddress": "synthetic", "jibunAddress": "", "x": True, "y": "37.57"}]}))
        with self.assertRaises(NaverApiError):
            MapsClient("test-client", "test-secret", transport=bad).geocode("서울시청")

    def test_provider_errors_do_not_expose_credentials_or_response_text(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(401, json={
            "error": {"code": "21001", "message": "test-secret must never escape"}}))
        with self.assertRaises(NaverApiError) as caught:
            MapsClient("test-client", "test-secret", transport=transport).geocode("서울시청")
        self.assertEqual(caught.exception.http_status, 401)
        self.assertEqual(caught.exception.provider_code, "21001")
        self.assertNotIn("test-secret", str(caught.exception))
        self.assertNotIn("must never escape", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
