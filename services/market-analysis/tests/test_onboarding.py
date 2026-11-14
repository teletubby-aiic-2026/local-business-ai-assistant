"""Form onboarding through HTTP, isolated SQLite and synthetic Maps responses.

No .env file, production profile database, external map request or model call is
used. Coordinates below are fixture values, not verified real-world locations.
"""
from contextlib import ExitStack
from copy import deepcopy
from functools import lru_cache
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.onboarding import COOKIE_NAME, SEARCH_TTL, OnboardingStore
from app.naver_clients import NaverApiError


# intake_api creates its default application on import. Keep that construction
# in memory too, without replacing the class binding for later test modules.
_store_init = OnboardingStore.__init__


def _memory_default(self, path=None, **kwargs):
    _store_init(self, ":memory:" if path is None else path, **kwargs)


with patch.object(OnboardingStore, "__init__", _memory_default):
    intake_api = importlib.import_module("app.intake_api")


SEOUL_ADDRESS = "서울특별시 마포구 양화로 45"
OTHER_SEOUL_ADDRESS = "서울특별시 성동구 왕십리로 83"
BUSAN_ADDRESS = "부산광역시 해운대구 구남로 20"


@lru_cache(maxsize=1)
def raw_industry_evidence():
    """Independent code/name union from local sources, not the app builder."""
    raw_root = Path(__file__).resolve().parents[1] / "data" / "raw" / "official"
    result = {"catalogues": {}, "period_catalogues": {}, "stores_area_codes": set(),
              "stores_area_codes_by_period": {}, "stores_citywide_periods": set(), "conflicts": []}
    for dataset, pattern, service in (("sales", "sales_*_all_*.json", "VwsmTrdarSelngQq"),
                                      ("stores", "stores_*.json", "VwsmTrdarStorQq")):
        paths = sorted(raw_root.glob(pattern))
        if not paths:
            raise AssertionError("Missing independent " + dataset + " source files")
        catalogue, per_period = {}, {}
        for path in paths:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
            if document["service"] != service or document["payload"][service]["RESULT"]["CODE"] != "INFO-000":
                raise AssertionError("Invalid independent source envelope: " + path.name)
            period = document["query"]["period"]
            period_values = per_period.setdefault(period, {})
            if dataset == "stores" and document["query"]["area_code"] is None:
                result["stores_citywide_periods"].add(period)
            for row in document["payload"][service]["row"]:
                if dataset == "stores":
                    result["stores_area_codes"].add(row["TRDAR_CD"])
                    result["stores_area_codes_by_period"].setdefault(period, set()).add(row["TRDAR_CD"])
                code, name = row["SVC_INDUTY_CD"], row["SVC_INDUTY_CD_NM"]
                for table in (catalogue, period_values):
                    if code in table and table[code] != name:
                        result["conflicts"].append((dataset, period, code, table[code], name))
                    table[code] = name
        result["catalogues"][dataset] = catalogue
        result["period_catalogues"][dataset] = per_period
    return result


class Clock:
    def __init__(self):
        self.value = 1000000.0

    def __call__(self):
        return self.value


class FakeMaps:
    def __init__(self):
        self.calls = []
        self.error = None
        self.rows = {
            SEOUL_ADDRESS: [{"road_address": SEOUL_ADDRESS,
                "jibun_address": "서울특별시 마포구 합정동 1-1",
                "longitude": 126.91, "latitude": 37.55}],
            OTHER_SEOUL_ADDRESS: [{"road_address": OTHER_SEOUL_ADDRESS,
                "jibun_address": "서울특별시 성동구 성수동1가 1-1",
                "longitude": 127.04, "latitude": 37.54}],
            BUSAN_ADDRESS: [{"road_address": BUSAN_ADDRESS,
                "jibun_address": "부산광역시 해운대구 중동 1-1",
                "longitude": 129.16, "latitude": 35.16}],
        }
        self.rows["서울특별시 마포구 합정동"] = deepcopy(self.rows[SEOUL_ADDRESS])
        self.rows["서울 마포구 합정동"] = deepcopy(self.rows[SEOUL_ADDRESS])
        self.rows["서울특별시 성동구 성수동"] = deepcopy(self.rows[OTHER_SEOUL_ADDRESS])

    def geocode(self, query):
        self.calls.append(query)
        if self.error:
            raise self.error
        return deepcopy(self.rows.get(query, []))


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.clock = Clock()
        self.store = OnboardingStore(":memory:", clock=self.clock)
        # ExitStack closes TestClient lifespans before the database.
        self.stack.callback(self.store.close)
        self.maps = FakeMaps()
        self.stack.enter_context(patch.object(intake_api, "load_settings", return_value=None))
        self.stack.enter_context(patch.object(intake_api, "MapsClient", return_value=self.maps))
        self.app = intake_api.create_app(onboarding_store=self.store)
        self.client = self.stack.enter_context(TestClient(self.app))
        self.options = self.client.get("/api/onboarding/options").json()
        self.mapo = next(d["code"] for d in self.options["districts"] if d["name"] == "마포구")
        self.seongdong = next(d["code"] for d in self.options["districts"] if d["name"] == "성동구")
        self.coffee = next(i["code"] for i in self.options["industries"] if i["name"] == "커피-음료")
        self.other_industry = next(i["code"] for i in self.options["industries"] if i["code"] != self.coffee)
        self.hapjeong = next(s for s in self.options["stations"] if s["name"] == "합정역")
        self.seongsu = next(s for s in self.options["stations"] if s["name"] == "성수역")
        self.hapjeong_dong = next(n for n in self.options["neighborhoods"] if n["name"] == "합정동" and n["district_code"] == self.mapo)
        self.yeonnam_dong = next(n for n in self.options["neighborhoods"] if n["name"] == "연남동" and n["district_code"] == self.mapo)

    def area_body(self, **updates):
        result = {"location": {"kind": "area", "text": "합정동", "district_code": self.mapo},
                  "industry_code": self.coffee, "business_status": "operating", "expected_revision": 0}
        result.update(updates)
        return result

    def save(self, body=None, client=None):
        result = (client or self.client).post("/api/onboarding/profile", json=self.area_body() if body is None else body)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def search(self, query=SEOUL_ADDRESS, client=None):
        result = (client or self.client).post("/api/onboarding/locations/search", json={"query": query})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def address_body(self, search):
        return self.area_body(location={"kind": "address", "search_id": search["search_id"],
                                        "candidate_id": search["candidates"][0]["id"]})

    def area_preview(self, text="합정동", district_code=None, client=None):
        result = (client or self.client).post("/api/onboarding/locations/area-preview", json={
            "kind": "area", "text": text, "district_code": district_code or self.mapo})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def area_candidate_body(self, preview, text="합정동", district_code=None):
        return self.area_body(location={"kind": "area", "text": text, "district_code": district_code or self.mapo,
            "search_id": preview["search_id"], "candidate_id": preview["candidates"][0]["id"]})

    def selected_neighborhood_body(self, neighborhood=None, **updates):
        neighborhood = neighborhood or self.hapjeong_dong
        body = self.area_body(location={"kind": "area", "neighborhood_code": neighborhood["code"],
                                       "district_code": neighborhood["district_code"]})
        body.update(updates)
        return body

    def selected_neighborhood_preview(self, neighborhood=None):
        location = self.selected_neighborhood_body(neighborhood)["location"]
        result = self.client.post("/api/onboarding/locations/area-preview", json=location)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def with_reference(self, body, preview):
        result = deepcopy(body)
        result["location"].update(search_id=preview["search_id"], candidate_id=preview["candidates"][0]["id"])
        return result

    def current(self, client=None):
        result = (client or self.client).get("/api/onboarding/profile")
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def other_client(self):
        return self.stack.enter_context(TestClient(self.app))

    def test_options_offer_seoul_districts_industries_and_three_states(self):
        self.assertEqual(len(self.options["districts"]), 25)
        self.assertEqual(len({d["code"] for d in self.options["districts"]}), 25)
        self.assertEqual(len(self.options["industries"]), 100)
        self.assertEqual({s["code"] for s in self.options["business_statuses"]},
                         {"operating", "planning", "exploring"})
        self.assertFalse(self.options["catalog_source"]["analysis_availability_verified"])
        self.assertEqual(self.maps.calls, [])




    def test_well_formed_unlisted_industry_and_client_supplied_name_are_rejected(self):
        fake_code = "CS999999"
        self.assertNotIn(fake_code, {item["code"] for item in self.options["industries"]})
        body = self.area_body(industry_code=fake_code)
        self.assertEqual(self.client.post("/api/onboarding/profile", json=body).status_code, 422)
        body = self.area_body(industry_code="CS200041")
        body["industry_name"] = "카페"
        self.assertEqual(self.client.post("/api/onboarding/profile", json=body).status_code, 422)
        self.assertIsNone(self.current()["profile"])

    def test_map_config_contains_only_public_client_id_and_no_server_credentials(self):
        secrets = {"NAVER_MAPS_CLIENT_SECRET": "private-maps-secret-must-not-appear",
                   "CLOVA_STUDIO_API_KEY": "private-model-key-must-not-appear",
                   "SEOUL_OPENAPI_KEY": "private-source-key-must-not-appear"}
        with patch.dict(os.environ, {"NAVER_MAPS_CLIENT_ID": "  public-map-client-id  ", **secrets}, clear=True):
            result = self.client.get("/api/onboarding/map-config")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json(), {"client_id": "public-map-client-id", "configured": True})
        self.assertEqual(result.headers["cache-control"], "no-store")
        exposed = result.text + str(dict(result.headers))
        for name, value in secrets.items():
            self.assertNotIn(name, exposed)
            self.assertNotIn(value, exposed)
        self.assertEqual(self.maps.calls, [])

    def test_map_config_without_public_id_is_unconfigured_even_if_secret_exists(self):
        with patch.dict(os.environ, {"NAVER_MAPS_CLIENT_ID": "   ",
                                     "NAVER_MAPS_CLIENT_SECRET": "server-only-secret"}, clear=True):
            result = self.client.get("/api/onboarding/map-config")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json(), {"client_id": "", "configured": False})
        self.assertEqual(result.headers["cache-control"], "no-store")
        self.assertNotIn("server-only-secret", result.text + str(dict(result.headers)))
        self.assertEqual(self.maps.calls, [])

    def test_initial_profile_is_empty_revision_zero_and_cookie_is_private(self):
        result = self.client.get("/api/onboarding/profile")
        self.assertEqual(result.json(), {"revision": 0, "profile": None})
        self.assertEqual(result.headers["cache-control"], "no-store")
        cookie = result.headers["set-cookie"]
        self.assertIn(COOKIE_NAME + "=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)

    def test_area_save_is_user_declared_not_ready_and_get_matches(self):
        saved = self.save()
        profile = saved["profile"]
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(profile["location"]["label"], "합정동")
        self.assertEqual(profile["location"]["verification"], "user_declared")
        self.assertFalse(profile["location"]["analysis_area_confirmed"])
        self.assertFalse(profile["ready_for_analysis"])
        self.assertNotIn("longitude", profile["location"])
        self.assertNotIn("latitude", profile["location"])
        self.assertEqual(self.current()["profile"], profile)
        self.assertEqual(self.maps.calls, [])

    def test_neighborhood_options_are_427_administrative_dongs_in_25_districts(self):
        neighborhoods = self.options["neighborhoods"]
        self.assertEqual(len(neighborhoods), 427)
        self.assertEqual(len({n["code"] for n in neighborhoods}), 427)
        districts = {d["code"]: d["name"] for d in self.options["districts"]}
        self.assertEqual({n["district_code"] for n in neighborhoods}, set(districts))
        for item in neighborhoods:
            with self.subTest(code=item["code"]):
                self.assertRegex(item["code"], r"^[0-9]{8}$")
                self.assertTrue(item["code"].startswith(item["district_code"]))
                self.assertEqual(item["district_name"], districts[item["district_code"]])
                self.assertTrue(item["name"])
                self.assertNotIn("latitude", item)
                self.assertNotIn("longitude", item)
        source = self.options["neighborhood_source"]
        self.assertEqual(source["type"], "administrative_dong")
        self.assertEqual(source["base_ym"], "202608")
        self.assertEqual(source["neighborhood_count"], 427)
        self.assertEqual(source["district_count"], 25)
        self.assertFalse(source["coordinates_provided"])
        self.assertFalse(source["analysis_area_confirmed"])

    def test_selected_neighborhood_uses_server_name_and_does_not_claim_map_or_boundary(self):
        saved = self.save(self.selected_neighborhood_body())["profile"]
        location = saved["location"]
        self.assertEqual(location["label"], "합정동")
        self.assertEqual(location["neighborhood_code"], self.hapjeong_dong["code"])
        self.assertEqual(location["neighborhood_name"], self.hapjeong_dong["name"])
        self.assertEqual(location["neighborhood_type"], "administrative_dong")
        self.assertEqual(location["neighborhood_source_date"], "2026-08")
        self.assertEqual(location["verification"], "selected_neighborhood")
        self.assertEqual(location["district_code"], self.mapo)
        self.assertFalse(location["analysis_area_confirmed"])
        self.assertNotIn("reference_point", location)
        self.assertNotIn("latitude", location)
        self.assertNotIn("longitude", location)
        self.assertFalse(saved["ready_for_analysis"])
        self.assertEqual(self.current()["profile"], saved)
        self.assertEqual(self.maps.calls, [])

    def test_neighborhood_code_district_and_optional_name_must_agree(self):
        base = self.selected_neighborhood_body()["location"]
        invalid = [
            {**base, "neighborhood_code": "99999999", "text": "합정동"},
            {**base, "neighborhood_code": "123"},
            {**base, "district_code": self.seongdong},
            {**base, "text": "연남동"},
            {**base, "text": "서울 마포구 합정동"},
            {"kind": "area", "neighborhood_code": self.hapjeong_dong["code"]},
            {**base, "latitude": 37.5},
        ]
        for location in invalid:
            with self.subTest(location=location):
                result = self.client.post("/api/onboarding/profile", json=self.area_body(location=location))
                self.assertEqual(result.status_code, 422, result.text)
        self.assertIsNone(self.current()["profile"])
        saved = self.save(self.area_body(location={**base, "text": " 합정동 "}))["profile"]
        self.assertEqual(saved["location"]["label"], "합정동")

    def test_neighborhood_code_cannot_be_injected_into_station_or_address(self):
        address_location = self.address_body(self.search())["location"]
        for location in (address_location, {"kind": "station", "station_id": self.hapjeong["id"]}):
            with self.subTest(kind=location["kind"]):
                result = self.client.post("/api/onboarding/profile", json=self.area_body(
                    location={**location, "neighborhood_code": self.hapjeong_dong["code"]}))
                self.assertEqual(result.status_code, 422, result.text)
        self.assertIsNone(self.current()["profile"])

    def test_selected_neighborhood_reference_keeps_administrative_identity(self):
        preview = self.selected_neighborhood_preview()
        saved = self.save(self.with_reference(self.selected_neighborhood_body(), preview))["profile"]
        location = saved["location"]
        self.assertEqual(location["verification"], "geocoded_area_reference")
        self.assertEqual(location["neighborhood_code"], self.hapjeong_dong["code"])
        self.assertEqual(location["neighborhood_name"], "합정동")
        self.assertEqual(location["neighborhood_type"], "administrative_dong")
        self.assertEqual(location["reference_point"]["source"], "naver_geocoding")
        self.assertEqual(location["reference_point"]["longitude"], 126.91)
        self.assertFalse(location["analysis_area_confirmed"])
        self.assertFalse(saved["ready_for_analysis"])
        self.assertEqual(self.maps.calls, ["서울특별시 마포구 합정동"])

    def test_legacy_and_coded_neighborhood_references_cannot_cross_namespaces(self):
        legacy_preview = self.area_preview()
        coded_preview = self.selected_neighborhood_preview()
        bodies = [self.with_reference(self.selected_neighborhood_body(), legacy_preview),
                  self.area_candidate_body(coded_preview)]
        for body in bodies:
            result = self.client.post("/api/onboarding/profile", json=body)
            self.assertEqual(result.status_code, 422, result.text)
        self.assertIsNone(self.current()["profile"])

    def test_neighborhood_reference_cannot_follow_different_selection(self):
        preview = self.selected_neighborhood_preview()
        body = self.with_reference(self.selected_neighborhood_body(self.yeonnam_dong), preview)
        result = self.client.post("/api/onboarding/profile", json=body)
        self.assertEqual(result.status_code, 422, result.text)
        self.assertIsNone(self.current()["profile"])

    def test_neighborhood_can_be_saved_when_no_matching_map_reference_exists(self):
        self.maps.rows["서울특별시 마포구 합정동"] = []
        preview = self.selected_neighborhood_preview()
        self.assertEqual(preview["status"], "not_found")
        self.assertEqual(preview["candidates"], [])
        saved = self.save(self.selected_neighborhood_body())["profile"]
        self.assertEqual(saved["location"]["verification"], "selected_neighborhood")
        self.assertNotIn("reference_point", saved["location"])
        self.assertEqual(self.maps.calls, ["서울특별시 마포구 합정동"])

    def test_changing_selected_neighborhood_discards_old_map_reference(self):
        preview = self.selected_neighborhood_preview()
        first = self.save(self.with_reference(self.selected_neighborhood_body(), preview))["profile"]
        changed = self.save(self.selected_neighborhood_body(self.yeonnam_dong, expected_revision=first["revision"]))["profile"]
        self.assertEqual(changed["location"]["label"], "연남동")
        self.assertEqual(changed["location"]["neighborhood_code"], self.yeonnam_dong["code"])
        self.assertEqual(changed["location"]["verification"], "selected_neighborhood")
        self.assertNotIn("reference_point", changed["location"])
        self.assertNotIn("latitude", changed["location"])
        self.assertNotIn("longitude", changed["location"])

    def test_legacy_profile_restores_and_updates_until_neighborhood_explicitly_selected(self):
        old = self.save(self.area_candidate_body(self.area_preview()))["profile"]
        self.assertNotIn("neighborhood_code", old["location"])
        self.assertEqual(self.current()["profile"], old)
        changed = self.save({"location": None, "industry_code": self.other_industry,
            "business_status": "planning", "expected_revision": old["revision"]})["profile"]
        self.assertEqual(changed["location"], old["location"])
        selected = self.save(self.selected_neighborhood_body(expected_revision=changed["revision"]))["profile"]
        self.assertEqual(selected["location"]["verification"], "selected_neighborhood")
        self.assertEqual(selected["location"]["neighborhood_code"], self.hapjeong_dong["code"])
        self.assertNotIn("reference_point", selected["location"])

    def test_official_station_accepts_each_business_state_without_geocoding(self):
        revision = 0
        for state in ("operating", "planning", "exploring"):
            saved = self.save(self.area_body(location={"kind": "station", "station_id": self.hapjeong["id"]},
                business_status=state, expected_revision=revision))
            revision = saved["revision"]
            self.assertEqual(saved["profile"]["business_status"], state)
            location = saved["profile"]["location"]
            self.assertEqual(location["verification"], "verified_station")
            self.assertEqual(location["source"], "kric_station_catalog")
            self.assertEqual(location["label"], "합정역")
            self.assertFalse(location["analysis_area_confirmed"])
            for key in ("name", "lines", "district_code", "district_name", "road_address"):
                self.assertEqual(location[key], self.hapjeong[key])
            for key in ("longitude", "latitude"):
                if key in self.hapjeong:
                    self.assertEqual(location[key], self.hapjeong[key])
                else:
                    self.assertNotIn(key, location)
        self.assertEqual(self.maps.calls, [])

    def test_station_with_withheld_coordinates_saves_without_inventing_a_point(self):
        station = next(s for s in self.options["stations"] if s.get("longitude") is None or s.get("latitude") is None)
        saved = self.save(self.area_body(location={"kind": "station", "station_id": station["id"]}))["profile"]
        location = saved["location"]
        self.assertEqual(location["station_id"], station["id"])
        self.assertEqual(location["name"], station["name"])
        self.assertEqual(location["coordinate_status"], station["coordinate_status"])
        self.assertEqual(location["source"], "kric_station_catalog")
        self.assertEqual(location["verification"], "verified_station")
        self.assertIsNone(location.get("longitude"))
        self.assertIsNone(location.get("latitude"))
        self.assertFalse(location["analysis_area_confirmed"])
        self.assertFalse(saved["ready_for_analysis"])
        self.assertEqual(self.maps.calls, [])

    def test_station_choices_are_unique_and_seoul_only(self):
        stations = self.options["stations"]
        self.assertGreater(len(stations), 1)
        self.assertEqual(len(stations), len({station["id"] for station in stations}))
        districts = {district["code"]: district["name"] for district in self.options["districts"]}
        for station in stations:
            with self.subTest(station=station["id"]):
                # Official secondary names follow the main name in parentheses,
                # e.g. 강변역(동서울터미널); preserve them instead of rejecting them.
                self.assertTrue(station["name"].split("(", 1)[0].strip().endswith("역"))
                self.assertTrue(station["lines"])
                self.assertEqual(station["district_name"], districts[station["district_code"]])
                self.assertTrue(station["road_address"].startswith(("서울특별시 ", "서울시 ", "서울 ")))

    def test_station_line_options_cover_choices_without_rewriting_source_lines(self):
        from app.onboarding_stations import get_station

        lines = self.options["station_lines"]
        self.assertGreater(len(lines), 1)
        self.assertEqual(len(lines), len({line["code"] for line in lines}))
        line_codes = {line["code"] for line in lines}
        referenced = set()
        for line in lines:
            self.assertTrue(line["name"])
        for station in self.options["stations"]:
            with self.subTest(station=station["id"]):
                allowed = station["selectable_line_codes"]
                self.assertTrue(allowed)
                self.assertEqual(len(allowed), len(set(allowed)))
                self.assertLessEqual(set(allowed), line_codes)
                self.assertEqual(station["lines"], get_station(station["id"])["lines"])
                referenced.update(allowed)
        self.assertEqual(referenced, line_codes)
        line_two = next(line["code"] for line in lines if line["name"] == "2호선")
        self.assertEqual(self.seongsu["selectable_line_codes"], [line_two])
        source = self.options["station_line_source"]
        self.assertEqual(source["station_count"], len(self.options["stations"]))
        self.assertEqual(source["line_count"], len(lines))
        self.assertEqual(source["station_line_membership_count"],
                         sum(len(station["selectable_line_codes"]) for station in self.options["stations"]))
        self.assertTrue(source["preserves_source_station_ids"])
        self.assertFalse(source["adds_stations"])
        self.assertFalse(source["complete_current_route_coverage"])
        self.assertTrue(source["coverage_note"])
        self.assertTrue(source["ordering_note"])
        self.assertTrue(source["sources"])
        for evidence in source["sources"]:
            self.assertTrue(evidence["url"].startswith("https://"))
            self.assertTrue(evidence["title"])
            self.assertTrue(evidence["use"])

    def test_selected_station_line_saves_canonical_name_and_restores(self):
        code = self.seongsu["selectable_line_codes"][0]
        line = next(line for line in self.options["station_lines"] if line["code"] == code)
        saved = self.save(self.area_body(location={"kind": "station", "station_id": self.seongsu["id"],
                                                  "station_line_code": code}))["profile"]
        location = saved["location"]
        self.assertEqual(location["station_line_code"], line["code"])
        self.assertEqual(location["station_line_name"], line["name"])
        self.assertEqual(location["station_id"], self.seongsu["id"])
        for key in ("name", "lines", "district_code", "district_name", "road_address"):
            self.assertEqual(location[key], self.seongsu[key])
        self.assertEqual(location["verification"], "verified_station")
        self.assertFalse(location["analysis_area_confirmed"])
        self.assertEqual(self.current()["profile"], saved)
        context = self.client.get("/api/onboarding/context")
        self.assertEqual(context.status_code, 200, context.text)
        self.assertEqual(context.json()["location"], location)
        self.assertEqual(self.maps.calls, [])

    def test_display_lines_follow_service_identity_instead_of_raw_railway_name(self):
        from app.onboarding_stations import get_station

        # Independent reviewed identities from the official source evidence:
        # these 경원선 rows belong to different passenger-service selections.
        expected = {("I4102", code): ["line-gyeongui-jungang"]
                    for code in ("1003", "1008", "1009", "1010", "1011", "1012", "1013")}
        expected.update({("I4102", "1019"): ["line-1"],
                         ("I4108", "1019"): ["line-gyeongchun"],
                         ("I4108", "1201"): ["line-gyeongchun", "line-gyeongui-jungang"],
                         ("I4108", "1202"): ["line-gyeongchun", "line-gyeongui-jungang"]})
        observed = {}
        for station in self.options["stations"]:
            original = get_station(station["id"])
            identity = (original["source_line_code"], original["source_station_code"])
            if original["operator"] == "한국철도공사" and identity in expected:
                observed[identity] = sorted(station["selectable_line_codes"])
        self.assertEqual(observed, {identity: sorted(codes) for identity, codes in expected.items()})

    def test_same_named_station_cannot_borrow_the_other_source_identity_line(self):
        choices = [s for s in self.options["stations"] if s["name"] == "광운대역"]
        line_one = next(s for s in choices if s["selectable_line_codes"] == ["line-1"])
        gyeongchun = next(s for s in choices if s["selectable_line_codes"] == ["line-gyeongchun"])
        self.assertNotEqual(line_one["id"], gyeongchun["id"])
        invalid = self.client.post("/api/onboarding/profile", json=self.area_body(location={
            "kind": "station", "station_id": line_one["id"], "station_line_code": "line-gyeongchun"}))
        self.assertEqual(invalid.status_code, 422, invalid.text)
        self.assertIsNone(self.current()["profile"])
        saved = self.save(self.area_body(location={"kind": "station", "station_id": gyeongchun["id"],
                                                  "station_line_code": "line-gyeongchun"}))["profile"]
        self.assertEqual(saved["location"]["station_id"], gyeongchun["id"])
        self.assertEqual(saved["location"]["station_line_code"], "line-gyeongchun")

    def test_station_line_requires_a_known_matching_station(self):
        good = self.seongsu["selectable_line_codes"][0]
        wrong = next(line["code"] for line in self.options["station_lines"]
                     if line["code"] not in self.seongsu["selectable_line_codes"])
        base = {"kind": "station", "station_id": self.seongsu["id"]}
        invalid = [{**base, "station_line_code": wrong}, {**base, "station_line_code": "unknown-line"},
                   {**base, "station_line_code": ""}, {"kind": "station", "station_line_code": good},
                   {**base, "station_line_code": good, "station_line_name": "가짜 노선"}]
        for location in invalid:
            with self.subTest(location=location):
                result = self.client.post("/api/onboarding/profile", json=self.area_body(location=location))
                self.assertEqual(result.status_code, 422, result.text)
        self.assertIsNone(self.current()["profile"])
        self.assertEqual(self.maps.calls, [])

    def test_station_line_cannot_be_injected_into_address_or_neighborhood(self):
        code = self.seongsu["selectable_line_codes"][0]
        locations = [self.address_body(self.search())["location"], self.area_body()["location"],
                     self.selected_neighborhood_body()["location"]]
        for location in locations:
            with self.subTest(location=location):
                injected = {**location, "station_line_code": code}
                result = self.client.post("/api/onboarding/profile", json=self.area_body(location=injected))
                self.assertEqual(result.status_code, 422, result.text)
                if location["kind"] == "area":
                    preview = self.client.post("/api/onboarding/locations/area-preview", json=injected)
                    self.assertEqual(preview.status_code, 422, preview.text)
        self.assertIsNone(self.current()["profile"])

    def test_legacy_station_profile_restores_without_inventing_selected_line(self):
        saved = self.save(self.area_body(location={"kind": "station", "station_id": self.seongsu["id"]}))["profile"]
        self.assertNotIn("station_line_code", saved["location"])
        self.assertNotIn("station_line_name", saved["location"])
        self.assertEqual(self.current()["profile"], saved)
        changed = self.save(self.area_body(location=None, industry_code=self.other_industry,
            expected_revision=saved["revision"]))["profile"]
        self.assertEqual(changed["location"], saved["location"])
        self.assertEqual(self.maps.calls, [])

    def test_industry_only_edit_preserves_explicit_station_line(self):
        code = self.seongsu["selectable_line_codes"][0]
        saved = self.save(self.area_body(location={"kind": "station", "station_id": self.seongsu["id"],
                                                  "station_line_code": code}))["profile"]
        changed = self.save(self.area_body(location=None, industry_code=self.other_industry,
            business_status="planning", expected_revision=saved["revision"]))["profile"]
        self.assertEqual(changed["location"], saved["location"])
        self.assertEqual(self.current()["profile"]["location"]["station_line_code"], code)
        self.assertEqual(self.maps.calls, [])

    def test_replacing_station_does_not_keep_previous_selected_line(self):
        code = self.seongsu["selectable_line_codes"][0]
        saved = self.save(self.area_body(location={"kind": "station", "station_id": self.seongsu["id"],
                                                  "station_line_code": code}))["profile"]
        changed = self.save(self.area_body(location={"kind": "station", "station_id": self.hapjeong["id"]},
            expected_revision=saved["revision"]))["profile"]
        self.assertEqual(changed["location"]["station_id"], self.hapjeong["id"])
        self.assertNotIn("station_line_code", changed["location"])
        self.assertNotIn("station_line_name", changed["location"])

    def test_invalid_station_line_edit_does_not_replace_saved_profile(self):
        code = self.seongsu["selectable_line_codes"][0]
        saved = self.save(self.area_body(location={"kind": "station", "station_id": self.seongsu["id"],
                                                  "station_line_code": code}))["profile"]
        wrong = next(line["code"] for line in self.options["station_lines"]
                     if line["code"] not in self.seongsu["selectable_line_codes"])
        result = self.client.post("/api/onboarding/profile", json=self.area_body(
            location={"kind": "station", "station_id": self.seongsu["id"], "station_line_code": wrong},
            expected_revision=saved["revision"]))
        self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(self.current()["profile"], saved)

    def test_station_id_is_required_and_unknown_ids_are_rejected(self):
        locations = [
            {"kind": "station"},
            {"kind": "station", "station_id": "made-up-or-non-seoul-station"},
            {"kind": "station", "text": "합정역", "district_code": self.mapo},
            {"kind": "station", "station_id": ""},
        ]
        for location in locations:
            with self.subTest(location=location):
                result = self.client.post("/api/onboarding/profile", json=self.area_body(location=location))
                self.assertEqual(result.status_code, 422, result.text)
        self.assertIsNone(self.current()["profile"])
        self.assertEqual(self.maps.calls, [])

    def test_station_rejects_user_supplied_location_fields_even_with_valid_id(self):
        for field, value in (("text", "합정역"), ("district_code", self.mapo),
                             ("longitude", 127.0), ("latitude", 37.5),
                             ("search_id", "search"), ("candidate_id", "candidate")):
            with self.subTest(field=field):
                location = {"kind": "station", "station_id": self.hapjeong["id"], field: value}
                result = self.client.post("/api/onboarding/profile", json=self.area_body(location=location))
                self.assertEqual(result.status_code, 422, result.text)
        self.assertIsNone(self.current()["profile"])

    def test_required_fields_missing_are_rejected_without_profile(self):
        for missing in ("location", "industry_code", "business_status"):
            with self.subTest(missing=missing):
                body = self.area_body()
                body.pop(missing)
                result = self.client.post("/api/onboarding/profile", json=body)
                self.assertEqual(result.status_code, 422, result.text)
                self.assertIsNone(self.current()["profile"])

    def test_invalid_code_state_text_and_extra_client_coordinates_rejected(self):
        bodies = [
            self.area_body(industry_code="UNKNOWN"), self.area_body(business_status="unknown"),
            self.area_body(location={"kind": "area", "text": "   ", "district_code": self.mapo}),
            self.area_body(location={"kind": "area", "text": "합정동", "district_code": "99999"}),
            self.area_body(location={"kind": "station", "text": "합정동", "district_code": self.mapo}),
            self.area_body(location={"kind": "area", "text": "합정동\n", "district_code": self.mapo}),
            self.area_body(location={"kind": "area", "text": "합정동", "district_code": self.mapo, "longitude": 127.0}),
        ]
        for body in bodies:
            with self.subTest(body=body):
                result = self.client.post("/api/onboarding/profile", json=body)
                self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(self.current()["revision"], 0)

    def test_explicit_non_seoul_raw_location_rejected(self):
        for text in ("부산 해운대구", "경기도 수원시"):
            with self.subTest(text=text):
                result = self.client.post("/api/onboarding/profile", json=self.area_body(
                    location={"kind": "area", "text": text, "district_code": self.mapo}))
                self.assertEqual(result.status_code, 422, result.text)
        self.assertIsNone(self.current()["profile"])

    def test_raw_location_and_selected_district_cannot_conflict(self):
        result = self.client.post("/api/onboarding/profile", json=self.area_body(location={
            "kind": "area", "text": "서울 성동구 성수동", "district_code": self.mapo}))
        self.assertEqual(result.status_code, 422, result.text)
        self.assertIsNone(self.current()["profile"])
        saved = self.save(self.area_body(location={"kind": "area", "text": "서울 마포구 합정동",
            "district_code": self.mapo}))
        self.assertEqual(saved["profile"]["location"]["district_code"], self.mapo)

    def test_address_search_does_not_save_until_selected(self):
        search = self.search()
        self.assertEqual(search["status"], "address_candidate")
        self.assertIsInstance(search["message"], str)
        self.assertTrue(search["search_id"])
        self.assertTrue(search["candidates"][0]["in_seoul"])
        self.assertEqual(search["candidates"][0]["longitude"], 126.91)
        self.assertEqual(search["candidates"][0]["latitude"], 37.55)
        self.assertIsNone(self.current()["profile"])
        saved = self.save(self.address_body(search))["profile"]
        self.assertEqual(saved["location"]["verification"], "verified_address")
        self.assertEqual(saved["location"]["road_address"], SEOUL_ADDRESS)
        self.assertEqual(saved["location"]["longitude"], 126.91)
        self.assertEqual(saved["location"]["latitude"], 37.55)
        self.assertFalse(saved["location"]["analysis_area_confirmed"])
        self.assertFalse(saved["ready_for_analysis"])
        self.assertEqual(self.maps.calls, [SEOUL_ADDRESS])

    def test_underground_address_can_be_selected_without_accepting_ground_variant(self):
        query = "서울특별시 종로구 사직로 지하130"
        self.maps.rows[query] = [{"road_address": query, "jibun_address": "",
                                  "longitude": 126.973, "latitude": 37.576}]
        search = self.search(query)
        self.assertEqual(search["status"], "address_candidate")
        saved = self.save(self.address_body(search))["profile"]
        self.assertEqual(saved["location"]["road_address"], query)
        self.maps.rows[query][0]["road_address"] = "서울특별시 종로구 사직로 130"
        mismatch = self.search(query)
        self.assertEqual(mismatch["status"], "needs_precision")
        self.assertEqual(mismatch["candidates"], [])
        self.assertIsNone(mismatch["search_id"])
        self.assertEqual(self.current()["profile"], saved)

    def test_manual_address_and_candidate_payload_tampering_rejected(self):
        manual = self.area_body(location={"kind": "address", "text": SEOUL_ADDRESS})
        self.assertEqual(self.client.post("/api/onboarding/profile", json=manual).status_code, 422)
        search = self.search()
        body = self.address_body(search)
        body["location"]["text"] = OTHER_SEOUL_ADDRESS
        self.assertEqual(self.client.post("/api/onboarding/profile", json=body).status_code, 422)
        body = self.address_body(search)
        body["location"]["candidate_id"] = "made-up-candidate"
        self.assertEqual(self.client.post("/api/onboarding/profile", json=body).status_code, 422)
        for field in ("longitude", "latitude"):
            body = self.address_body(search)
            body["location"][field] = 0.0
            self.assertEqual(self.client.post("/api/onboarding/profile", json=body).status_code, 422)
        self.assertIsNone(self.current()["profile"])

    def test_editing_preview_coordinates_cannot_change_server_stored_candidate(self):
        search = self.search()
        search["candidates"][0]["longitude"] = 0.0
        search["candidates"][0]["latitude"] = 0.0
        saved = self.save(self.address_body(search))["profile"]["location"]
        self.assertEqual(saved["longitude"], 126.91)
        self.assertEqual(saved["latitude"], 37.55)
        self.assertEqual(saved["road_address"], SEOUL_ADDRESS)

    def test_area_preview_and_selected_reference_are_not_an_exact_store_or_market(self):
        preview = self.area_preview()
        self.assertTrue(preview["search_id"])
        self.assertTrue(preview["message"])
        self.assertEqual(len(preview["candidates"]), 1)
        candidate = preview["candidates"][0]
        self.assertEqual(candidate["longitude"], 126.91)
        self.assertEqual(candidate["latitude"], 37.55)
        self.assertTrue(candidate["in_seoul"])
        self.assertIsNone(self.current()["profile"])
        saved = self.save(self.area_candidate_body(preview))["profile"]
        location = saved["location"]
        self.assertEqual(location["kind"], "area")
        self.assertEqual(location["label"], "합정동")
        self.assertEqual(location["verification"], "geocoded_area_reference")
        self.assertEqual(location["reference_point"]["longitude"], 126.91)
        self.assertEqual(location["reference_point"]["latitude"], 37.55)
        self.assertEqual(location["reference_point"]["source"], "naver_geocoding")
        self.assertNotIn("longitude", location)
        self.assertNotIn("latitude", location)
        self.assertFalse(location["analysis_area_confirmed"])
        self.assertFalse(saved["ready_for_analysis"])
        self.assertEqual(self.maps.calls, ["서울특별시 마포구 합정동"])

    def test_area_preview_does_not_duplicate_existing_city_prefix(self):
        preview = self.area_preview("서울 마포구 합정동")
        self.assertTrue(preview["candidates"])
        self.assertEqual(len(self.maps.calls), 1)
        self.assertIn(self.maps.calls[0], {"서울 마포구 합정동", "서울특별시 마포구 합정동"})

    def test_area_preview_rejects_unrelated_district_outside_city_and_other_neighborhood(self):
        query = "서울특별시 마포구 합정동"
        unrelated = {"road_address": "서울특별시 마포구 서교로 30", "jibun_address": "서울특별시 마포구 서교동 1-1",
                     "longitude": 126.92, "latitude": 37.56}
        for rows in (self.maps.rows[OTHER_SEOUL_ADDRESS], self.maps.rows[BUSAN_ADDRESS], [unrelated]):
            with self.subTest(rows=rows):
                self.maps.rows[query] = deepcopy(rows)
                preview = self.area_preview()
                self.assertEqual(preview["candidates"], [])
                self.assertIsNone(preview["search_id"])
                self.assertTrue(preview["message"])
        self.assertIsNone(self.current()["profile"])

    def test_area_reference_candidate_is_owned_and_expires(self):
        preview = self.area_preview()
        body = self.area_candidate_body(preview)
        other = self.other_client()
        result = other.post("/api/onboarding/profile", json=body)
        self.assertEqual(result.status_code, 422, result.text)
        self.clock.value += SEARCH_TTL
        result = self.client.post("/api/onboarding/profile", json=body)
        self.assertEqual(result.status_code, 422, result.text)
        self.assertIsNone(self.current()["profile"])
        self.assertIsNone(self.current(other)["profile"])

    def test_address_and_area_candidates_cannot_be_saved_as_each_others_purpose(self):
        area = self.area_preview()
        address = self.search()
        result = self.client.post("/api/onboarding/profile", json=self.address_body(area))
        self.assertEqual(result.status_code, 422, result.text)
        result = self.client.post("/api/onboarding/profile", json=self.area_candidate_body(address))
        self.assertEqual(result.status_code, 422, result.text)
        self.assertIsNone(self.current()["profile"])

    def test_area_candidate_cannot_be_reused_after_text_or_district_changes(self):
        preview = self.area_preview()
        for text, district in (("서교동", self.mapo), ("합정동", self.seongdong)):
            with self.subTest(text=text, district=district):
                body = self.area_candidate_body(preview, text=text, district_code=district)
                result = self.client.post("/api/onboarding/profile", json=body)
                self.assertEqual(result.status_code, 422, result.text)
        self.assertIsNone(self.current()["profile"])

    def test_area_preview_invalid_inputs_do_not_call_maps(self):
        bodies = [
            {"kind": "area", "text": "합정동"},
            {"kind": "area", "text": "서울 성동구 성수동", "district_code": self.mapo},
            {"kind": "area", "text": "부산 해운대구", "district_code": self.mapo},
            {"kind": "area", "text": "합정동", "district_code": self.mapo, "longitude": 127.0},
            {"kind": "station", "station_id": self.hapjeong["id"]},
        ]
        for body in bodies:
            with self.subTest(body=body):
                result = self.client.post("/api/onboarding/locations/area-preview", json=body)
                self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(self.maps.calls, [])

    def test_area_preview_lookup_failure_is_explicit_and_does_not_create_search(self):
        self.maps.error = NaverApiError("synthetic area lookup failure")
        preview = self.area_preview()
        self.assertEqual(preview["status"], "lookup_unavailable")
        self.assertEqual(preview["candidates"], [])
        self.assertIsNone(preview["search_id"])
        self.assertTrue(preview["message"])
        self.assertIsNone(self.current()["profile"])

    def test_non_seoul_search_candidate_cannot_be_saved(self):
        search = self.search(BUSAN_ADDRESS)
        self.assertEqual(search["status"], "outside_seoul")
        self.assertFalse(search["candidates"][0]["in_seoul"])
        result = self.client.post("/api/onboarding/profile", json=self.address_body(search))
        self.assertEqual(result.status_code, 422, result.text)
        self.assertIsNone(self.current()["profile"])

    def test_candidate_from_different_search_cannot_be_combined(self):
        first = self.search()
        second = self.search(OTHER_SEOUL_ADDRESS)
        body = self.address_body(first)
        body["location"]["candidate_id"] = second["candidates"][0]["id"]
        self.assertEqual(self.client.post("/api/onboarding/profile", json=body).status_code, 422)
        self.assertIsNone(self.current()["profile"])

    def test_candidate_from_another_browser_session_rejected(self):
        search = self.search()
        other = self.other_client()
        result = other.post("/api/onboarding/profile", json=self.address_body(search))
        self.assertEqual(result.status_code, 422, result.text)
        self.assertIsNone(self.current(other)["profile"])
        self.save(self.address_body(search))

    def test_expired_candidate_rejected_at_expiry_boundary(self):
        search = self.search()
        self.clock.value += SEARCH_TTL
        result = self.client.post("/api/onboarding/profile", json=self.address_body(search))
        self.assertEqual(result.status_code, 422, result.text)
        self.assertIsNone(self.current()["profile"])

    def test_address_search_empty_mismatch_and_provider_failure_do_not_create_profile(self):
        self.assertEqual(self.search("서울특별시 마포구 양화로 999")["status"], "not_found")
        self.maps.rows["서울특별시 마포구 양화로 999"] = self.maps.rows[SEOUL_ADDRESS]
        mismatch = self.search("서울특별시 마포구 양화로 999")
        self.assertEqual(mismatch["status"], "needs_precision")
        self.assertIsNone(mismatch["search_id"])
        self.assertEqual(mismatch["candidates"], [])
        self.maps.error = NaverApiError("synthetic lookup unavailable")
        unavailable = self.search()
        self.assertEqual(unavailable["status"], "lookup_unavailable")
        self.assertIsNone(unavailable["search_id"])
        self.assertIsNone(self.current()["profile"])

    def test_search_query_validation_happens_before_maps(self):
        for query in ("", " ", "가", "서울\n양화로 45", "가" * 201):
            with self.subTest(query=query):
                result = self.client.post("/api/onboarding/locations/search", json={"query": query})
                self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(self.maps.calls, [])

    def test_nearby_address_expressions_are_not_accepted_as_exact_address(self):
        for qualifier in ("근처", "맞은편", "주변", "인근", "부근", "일대"):
            with self.subTest(qualifier=qualifier):
                result = self.client.post("/api/onboarding/locations/search", json={"query": SEOUL_ADDRESS + " " + qualifier})
                self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(self.maps.calls, [])
        self.assertIsNone(self.current()["profile"])

    def test_new_profile_can_omit_revision_but_updates_cannot(self):
        body = self.area_body()
        body.pop("expected_revision")
        self.save(body)
        result = self.client.post("/api/onboarding/profile", json=body)
        self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(self.current()["revision"], 1)

    def test_stale_revision_update_is_atomic(self):
        first = self.save()["profile"]
        result = self.client.post("/api/onboarding/profile", json=self.area_body(
            industry_code=self.other_industry, business_status="planning", expected_revision=0))
        self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(self.current()["profile"], first)

    def test_industry_status_only_edit_preserves_confirmed_location(self):
        first = self.save(self.address_body(self.search()))["profile"]
        saved = self.save({"industry_code": self.other_industry, "business_status": "planning",
                           "expected_revision": first["revision"]})["profile"]
        self.assertEqual(saved["revision"], 2)
        self.assertEqual(saved["industry"]["code"], self.other_industry)
        self.assertEqual(saved["business_status"], "planning")
        self.assertEqual(saved["location"], first["location"])
        self.assertFalse(saved["ready_for_analysis"])
        self.assertEqual(len(self.maps.calls), 1)

    def test_changing_address_to_raw_area_discards_old_coordinates(self):
        first = self.save(self.address_body(self.search()))["profile"]
        saved = self.save(self.area_body(location={"kind": "area", "text": "성수동", "district_code": self.seongdong},
            expected_revision=first["revision"]))["profile"]
        self.assertEqual(saved["location"]["label"], "성수동")
        self.assertEqual(saved["location"]["verification"], "user_declared")
        for old_field in ("longitude", "latitude", "road_address", "jibun_address"):
            self.assertNotIn(old_field, saved["location"])
        self.assertFalse(saved["location"]["analysis_area_confirmed"])

    def test_changing_address_to_station_uses_only_official_station_fields(self):
        first = self.save(self.address_body(self.search()))["profile"]
        updated = self.save(self.area_body(location={"kind": "station", "station_id": self.seongsu["id"]},
            expected_revision=first["revision"]))["profile"]
        location = updated["location"]
        self.assertEqual(location["station_id"], self.seongsu["id"])
        self.assertEqual(location["verification"], "verified_station")
        for key in ("name", "lines", "district_code", "district_name", "road_address"):
            self.assertEqual(location[key], self.seongsu[key])
        for key in ("longitude", "latitude"):
            if key in self.seongsu:
                self.assertEqual(location[key], self.seongsu[key])
            else:
                self.assertNotIn(key, location)
        self.assertNotIn("jibun_address", location)
        self.assertFalse(updated["ready_for_analysis"])
        self.assertEqual(self.maps.calls, [SEOUL_ADDRESS])

    def test_invalid_location_edit_leaves_existing_profile_untouched(self):
        first = self.save()["profile"]
        result = self.client.post("/api/onboarding/profile", json=self.area_body(
            location={"kind": "area", "text": "서울 성동구 성수동", "district_code": self.mapo}, expected_revision=1))
        self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(self.current()["profile"], first)

    def test_stale_delete_does_not_remove_saved_profile(self):
        first = self.save()["profile"]
        result = self.client.delete("/api/onboarding/profile?expected_revision=0")
        self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(self.current()["profile"], first)

    def test_reset_keeps_monotonic_revision_and_invalidates_searches(self):
        search = self.search()
        self.save(self.address_body(search))
        result = self.client.delete("/api/onboarding/profile?expected_revision=1")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json(), {"profile": None, "revision": 2})
        self.assertEqual(self.current(), {"profile": None, "revision": 2})
        self.assertEqual(self.client.post("/api/onboarding/profile", json=self.area_body()).status_code, 409)
        stale_search = self.address_body(search)
        stale_search["expected_revision"] = 2
        self.assertEqual(self.client.post("/api/onboarding/profile", json=stale_search).status_code, 422)
        self.assertEqual(self.save(self.area_body(expected_revision=2))["revision"], 3)

    def test_two_sessions_profiles_and_deletes_are_isolated(self):
        mine = self.save()["profile"]
        other = self.other_client()
        self.assertIsNone(self.current(other)["profile"])
        theirs = self.save(self.area_body(location={"kind": "area", "text": "성수동", "district_code": self.seongdong},
            industry_code=self.other_industry, business_status="planning"), client=other)["profile"]
        self.assertEqual(self.current()["profile"], mine)
        self.assertEqual(self.current(other)["profile"], theirs)
        self.client.delete("/api/onboarding/profile?expected_revision=1")
        self.assertEqual(self.current(other)["profile"], theirs)

    def test_context_requires_profile_and_reuses_only_saved_fields(self):
        self.assertEqual(self.client.get("/api/onboarding/context").status_code, 409)
        saved = self.save()["profile"]
        context = self.client.get("/api/onboarding/context")
        self.assertEqual(context.status_code, 200, context.text)
        data = context.json()
        self.assertEqual(data["profile_revision"], saved["revision"])
        self.assertEqual(data["location"], saved["location"])
        self.assertEqual(data["industry"], saved["industry"])
        self.assertEqual(data["business_status"], saved["business_status"])
        self.assertIsNone(data["analysis_area"])
        self.assertIsNone(data["data_period"])
        self.assertFalse(data["ready_for_analysis"])


class IndustryCatalogueBuilderTests(unittest.TestCase):
    def setUp(self):
        from app import onboarding_catalog
        self.catalogue = onboarding_catalog
        self.directory = tempfile.TemporaryDirectory(prefix="industry-catalogue-fixture-")
        self.addCleanup(self.directory.cleanup)
        self.raw = Path(self.directory.name)
        self.write("areas", None, None, [{"SIGNGU_CD": f"11{number:03}", "SIGNGU_CD_NM": f"합성자치구{number}"} for number in range(25)])
        self.write("sales", "20262", None, [self.row("1111111", "20262", "CS100010", "커피-음료")])
        self.write("stores", "20261", None, [self.row("1111111", "20261", "CS200041", "사진관"),
                                             self.row("2222222", "20261", "CS200041", "사진관")])

    @staticmethod
    def row(area, period, code, name):
        return {"TRDAR_CD": area, "STDR_YYQU_CD": period, "SVC_INDUTY_CD": code, "SVC_INDUTY_CD_NM": name,
                "SIMILR_INDUTY_STOR_CO": 1, "THSMON_SELNG_AMT": 100}

    def write(self, kind, period, scope, rows, total=None):
        service = {"areas": "TbgisTrdarRelm", "sales": "VwsmTrdarSelngQq", "stores": "VwsmTrdarStorQq"}[kind]
        payload = {service: {"RESULT": {"CODE": "INFO-000"}, "row": rows, "list_total_count": len(rows) if total is None else total}}
        document = {"service": service, "payload": payload, "payload_sha256": self.catalogue._canonical_hash(payload),
                    "query": {"dataset": kind, "period": period, "area_code": scope, "start": 1, "count": len(rows)},
                    "sample_only": False, "fetched_at": "2026-11-04T00:00:00Z", "source_url": "https://example.invalid/synthetic"}
        path = self.raw / f"{kind}_{period or 'none'}_{scope or 'all'}_1_1000.json"
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    def test_citywide_actual_area_codes_and_asymmetric_dataset_periods(self):
        result = self.catalogue.build_catalog(self.raw)
        source = result["catalog_source"]
        self.assertEqual(source["dataset_periods"], {"sales": ["20262"], "stores": ["20261"]})
        self.assertEqual(source["source_periods"], ["20261", "20262"])
        self.assertEqual(source["stores_area_codes"], ["1111111", "2222222"])
        self.assertEqual(source["stores_area_count"], 2)
        self.assertEqual(source["stores_citywide_periods"], ["20261"])
        self.assertEqual(len(result["industries"]), 2)
        self.assertEqual(len(result["districts"]), 25)

    def test_mixed_quarter_area_and_category_coverage_preserves_union(self):
        self.write("stores", "20262", "3333333", [self.row("3333333", "20262", "CS100010", "커피-음료")])
        self.write("stores", "20261", "1111111", [self.row("1111111", "20261", "CS200041", "사진관")])
        source = self.catalogue.build_catalog(self.raw)["catalog_source"]
        self.assertEqual(source["stores_area_codes"], ["1111111", "2222222", "3333333"])
        self.assertEqual(source["stores_area_counts_by_period"], {"20261": 2, "20262": 1})
        self.assertFalse(source["same_industries_across_quarters"])
        self.assertEqual(source["dataset_industry_counts"], {"sales": 1, "stores": 2})

    def test_code_name_conflicts_across_quarters_are_rejected(self):
        self.write("stores", "20262", None, [self.row("3333333", "20262", "CS200041", "다른 업종명")])
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.catalogue.build_catalog(self.raw)

    def test_incomplete_citywide_source_is_rejected_despite_complete_legacy_scope(self):
        rows = [self.row("1111111", "20261", "CS200041", "사진관")]
        self.write("stores", "20261", None, rows, total=2)
        self.write("stores", "20261", "1111111", rows)
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            self.catalogue.build_catalog(self.raw)


if __name__ == "__main__":
    unittest.main()
