"""Full HTTP journeys against the real local B1 catalogue, isolated storage."""
import importlib
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.onboarding import COOKIE_NAME, OnboardingStore
from app.onboarding_neighborhoods import get_neighborhoods
from app.onboarding_stations import get_stations
from app.onboarding_station_lines import get_station_line_codes

original_init = OnboardingStore.__init__


def memory_default(self, path=None, **kwargs):
    original_init(self, ":memory:" if path is None else path, **kwargs)


with patch.object(OnboardingStore, "__init__", memory_default):
    intake_api = importlib.import_module("app.intake_api")


class ActualCatalogueJourneys(unittest.TestCase):
    def save_and_confirm(self, client, location, industry="CS100010"):
        before = client.get("/api/onboarding/profile").json()
        response = client.post("/api/onboarding/profile", json={
            "location": location, "industry_code": industry, "business_status": "planning",
            "expected_revision": before["revision"],
        })
        self.assertEqual(response.status_code, 200, response.text)
        options = client.get("/api/onboarding/analysis-options")
        self.assertEqual(options.status_code, 200, options.text)
        options = options.json()
        self.assertEqual(options["profile"]["industry"]["code"], industry)
        self.assertGreater(options["candidate_count"], 0)
        candidate = next(row for row in options["candidates"] if row["available_periods"])
        saved = client.post("/api/onboarding/analysis-selection", json={
            "area_code": candidate["area_code"], "period": candidate["available_periods"][0],
            "expected_revision": options["revision"], "expected_catalog_version": options["catalog_version"],
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        restored = client.get("/api/onboarding/analysis-selection").json()
        self.assertTrue(restored["conditions_confirmed"])
        self.assertEqual(restored["analysis_selection"]["area_code"], candidate["area_code"])
        context = client.get("/api/onboarding/context").json()
        self.assertEqual(context["analysis_area"]["code"], candidate["area_code"])
        self.assertFalse(context["ready_for_analysis"])
        return options, restored

    def test_eight_real_station_profiles_across_seoul(self):
        cases = [("강남역", "line-2"), ("홍대입구역", "line-2"), ("시청역", "line-1"),
                 ("성수역", "line-2"), ("이태원역", "line-6"), ("김포공항역", "line-9"),
                 ("도봉산역", "line-1"), ("잠실역(송파구청)", "line-2")]
        stations = get_stations()
        for name, line in cases:
            with self.subTest(station=name, line=line):
                station = next(s for s in stations if s["name"] == name and line in get_station_line_codes(s["id"]))
                store = OnboardingStore(":memory:")
                try:
                    client = TestClient(intake_api.create_app(store))
                    options, _ = self.save_and_confirm(client, {"kind": "station", "station_id": station["id"], "station_line_code": line})
                    for candidate in options["candidates"]:
                        self.assertLessEqual(candidate["distance_m"], 1000)
                        self.assertIn(candidate["relation"], ("inside", "boundary", "nearby"))
                finally:
                    store.close()

    def test_six_neighborhoods_without_geocoder_and_varied_industries(self):
        cases = [("마포구", "연남동", "CS100010"), ("성동구", "성수1가1동", "CS100001"),
                 ("중랑구", "신내1동", "CS300002"), ("강남구", "역삼1동", "CS200007"),
                 ("용산구", "이태원1동", "CS200006"), ("종로구", "종로1.2.3.4가동", "CS100005")]
        for district, name, industry in cases:
            with self.subTest(district=district, neighborhood=name, industry=industry):
                neighborhood = next(n for n in get_neighborhoods() if n["district_name"] == district and n["name"] == name)
                store = OnboardingStore(":memory:")
                try:
                    client = TestClient(intake_api.create_app(store))
                    options, _ = self.save_and_confirm(client, {"kind": "area", "district_code": neighborhood["district_code"], "neighborhood_code": neighborhood["code"]}, industry)
                    for candidate in options["candidates"]:
                        self.assertEqual(candidate["relation"], "neighborhood")
                        self.assertEqual(candidate["district_code"], neighborhood["district_code"])
                        self.assertEqual(candidate["neighborhood_code"], neighborhood["code"])
                finally:
                    store.close()

    def test_sqlite_reopen_and_new_session_isolation(self):
        station = next(s for s in get_stations() if s["name"] == "강남역" and "line-2" in get_station_line_codes(s["id"]))
        with tempfile.TemporaryDirectory(prefix="b1-isolated-sqlite-") as directory:
            path = Path(directory) / "test.sqlite3"
            store = OnboardingStore(path)
            client = TestClient(intake_api.create_app(store))
            _, saved = self.save_and_confirm(client, {"kind": "station", "station_id": station["id"], "station_line_code": "line-2"})
            cookie = client.cookies.get(COOKIE_NAME)
            store.close()
            reopened = OnboardingStore(path)
            try:
                app = intake_api.create_app(reopened)
                same_user = TestClient(app)
                same_user.cookies.set(COOKIE_NAME, cookie)
                restored = same_user.get("/api/onboarding/analysis-selection").json()
                self.assertTrue(restored["conditions_confirmed"])
                self.assertEqual(restored["analysis_selection"]["area_code"], saved["analysis_selection"]["area_code"])
                stranger = TestClient(app).get("/api/onboarding/analysis-selection").json()
                self.assertIsNone(stranger["profile"])
                self.assertIsNone(stranger["analysis_selection"])
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
