"""Offline provenance, geography and missing/zero regression checks for B1."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import onboarding_analysis_catalog as catalog


class AnalysisCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.areas = catalog.get_analysis_areas()

    def test_full_geography_and_checked_source_scope(self):
        source = catalog.get_analysis_catalog_source()
        self.assertEqual(len(self.areas), 1650)
        self.assertEqual(len({area["area_code"] for area in self.areas}), 1650)
        raw = catalog._ROOT / "data/raw/official"
        self.assertEqual(source["file_count"], sum(len(list(raw.glob(pattern))) for pattern, _service in catalog._SOURCES.values()))
        self.assertEqual(source["file_count"], len(source["files"]))
        self.assertEqual(source["boundary_publication_date"], "2023-10-23")
        self.assertEqual(source["boundary_current_compatibility"], "unverified")
        self.assertEqual(source["observed_scope"]["sales"]["20262"]["industries"], 62)
        observed_store_areas = source["observed_scope"]["stores"]["20262"]["areas"]
        self.assertGreater(observed_store_areas, 0)
        self.assertLessEqual(observed_store_areas, len(self.areas))
        if any(entry["dataset"] == "stores" and entry["period"] == "20262" and entry["area_code"] is None for entry in source["files"]):
            self.assertGreater(observed_store_areas, 10)
            self.assertIn("20262", source["dataset_periods"]["stores"])
        self.assertEqual(source["neighborhood_join"]["matched_area_count"], 1636)
        metrics = catalog.get_area_availability("3110127", "CS100010")["periods"][0]["metrics"]
        for metric, dataset, field, url_id in (("sales", "sales", "THSMON_SELNG_AMT", "OA-15572"),
                                              ("stores", "stores", "SIMILR_INDUTY_STOR_CO", "OA-15577"),
                                              ("floating_population", "population", "TOT_FLPOP_CO", "OA-15568")):
            self.assertEqual(metrics[metric]["source_field"], field)
            self.assertEqual(metrics[metric]["source_url"], f"https://data.seoul.go.kr/dataList/{url_id}/S/1/datasetView.do")
            self.assertTrue(all(file["source_url"] == metrics[metric]["source_url"] for file in source["files"] if file["dataset"] == dataset))

    def test_observed_zero_is_available(self):
        zero = next(key for key, value in catalog._catalog()["observations"]["stores"].items() if value == 2)
        area, industry, period = zero.split("|")
        availability = catalog.get_area_availability(area, industry)
        entry = next(item for item in availability["periods"] if item["code"] == period)
        self.assertEqual(entry["metrics"]["stores"]["status"], "available")
        self.assertTrue(entry["metrics"]["stores"]["zero_observation"])
        self.assertIn(period, availability["available_periods"])

    def test_absent_observation_differs_from_uncollected_and_population(self):
        original = catalog._catalog()
        data = {**original, "coverage_index": dict(original["coverage_index"])}
        area = next(item for item in self.areas if item["boundary_identity_status"] == "code_name_match"
                    and f"{item['area_code']}|*|20262" in data["observations"]["floating_population"])
        # Exercise uncollected coverage independently of how many live snapshot
        # areas have since been collected; a missing scope must not borrow rows.
        data["coverage_index"].pop(("stores", "20262", None), None)
        data["coverage_index"].pop(("stores", "20262", area["area_code"]), None)
        with patch.object(catalog, "_catalog", return_value=data):
            entry = next(item for item in catalog.get_area_availability(area["area_code"], "CS200041")["periods"] if item["code"] == "20262")
        self.assertEqual(entry["metrics"]["sales"]["status"], "no_observation")
        self.assertEqual(entry["metrics"]["stores"]["status"], "not_collected")
        self.assertEqual(entry["metrics"]["floating_population"]["status"], "available")
        self.assertFalse(entry["metrics"]["floating_population"]["industry_specific"])
        self.assertTrue(entry["population_only"])
        self.assertFalse(entry["industry_data_available"])

    def test_boundary_name_mismatches_cannot_select_data(self):
        for code in ("3110024", "3110379"):
            with self.subTest(area=code):
                area = catalog.get_analysis_area(code)
                self.assertEqual(area["boundary_identity_status"], "name_mismatch")
                self.assertNotEqual(area["name"], area["boundary_name"])
                availability = catalog.get_area_availability(code, "CS100010")
                self.assertEqual(availability["available_periods"], [])
                self.assertTrue(all(metric["status"] == "unavailable" for period in availability["periods"]
                                    for metric in period["metrics"].values()))


    def test_far_point_does_not_fall_back_to_distant_markets(self):
        options = catalog.get_analysis_options({"kind": "address", "longitude": 126.1, "latitude": 37.1}, "CS100010")
        self.assertEqual(options["status"], "no_candidates")
        self.assertEqual(options["candidates"], [])

    def test_neighborhood_requires_code_district_and_matching_name(self):
        location = {"kind": "area", "district_code": "11260", "neighborhood_code": "11260680"}
        options = catalog.get_analysis_options(location, "CS100010")
        self.assertEqual(options["status"], "ready")
        self.assertIsNone(options["scope"]["search_radius_m"])
        self.assertEqual(options["scope"]["candidate_basis"], "administrative_dong")
        self.assertIn("행정동으로 등록된 상권", options["scope"]["search_radius_notice"])
        self.assertTrue(all(row["relation"] == "neighborhood" and row["neighborhood_code"] == "11260680"
                            and row["district_code"] == "11260" for row in options["candidates"]))
        wrong_district = catalog.get_analysis_options({**location, "district_code": "11440"}, "CS100010")
        self.assertEqual(wrong_district["status"], "needs_location_refinement")
        self.assertIsNone(wrong_district["scope"]["search_radius_m"])
        self.assertEqual(wrong_district["scope"]["candidate_basis"], "unresolved")
        known = {"code": "11110615", "name": "종로1.2.3.4가동", "district_code": "11110"}
        area = {"neighborhood_code": "11110615", "neighborhood_name": "종로1·2·3·4가동", "district_code": "11110"}
        self.assertTrue(catalog._neighborhood_matches(area, known))
        self.assertFalse(catalog._neighborhood_matches({**area, "neighborhood_name": "다른동"}, known))

    def test_holes_edges_and_multipolygons(self):
        outer = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]
        hole = [[1, 1], [1, 3], [3, 3], [3, 1], [1, 1]]
        geometry = {"type": "Polygon", "coordinates": [outer, hole]}
        self.assertEqual(catalog.geometry_membership((.5, .5), geometry), "inside")
        self.assertEqual(catalog.geometry_membership((2, 2), geometry), "outside")
        self.assertEqual(catalog.geometry_membership((1, 2), geometry), "boundary")
        self.assertEqual(catalog.geometry_membership((0, 2), geometry), "boundary")
        multi = {"type": "MultiPolygon", "coordinates": [[outer, hole], [[[5, 5], [6, 5], [6, 6], [5, 6], [5, 5]]]]}
        self.assertEqual(catalog.geometry_membership((5.5, 5.5), multi), "inside")

    def test_selection_checks_catalog_candidate_period_and_remains_b1(self):
        location = {"kind": "address", "longitude": 127.0276, "latitude": 37.4979}
        options = catalog.get_analysis_options(location, "CS100010")
        area = next(row for row in options["candidates"] if row["available_periods"])
        selected = catalog.validate_analysis_selection(location, "CS100010", area["area_code"], area["available_periods"][0], options["catalog_version"])
        self.assertTrue(selected["analysis_setup_complete"])
        self.assertFalse(selected["ready_for_analysis"])
        self.assertEqual(selected["boundary"]["compatibility"], "unverified")
        for code, period, version in [(area["area_code"], "20263", options["catalog_version"]),
                                      (area["area_code"], area["available_periods"][0], "old"),
                                      ("invalid", area["available_periods"][0], options["catalog_version"])]:
            with self.subTest(code=code, period=period, version=version), self.assertRaises(ValueError):
                catalog.validate_analysis_selection(location, "CS100010", code, period, version)


class RawValidationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.area = {"TRDAR_CD": "3110008", "TRDAR_CD_NM": "배화여자대학교(박노수미술관)", "TRDAR_SE_CD_NM": "골목상권",
                     "SIGNGU_CD": "11110", "SIGNGU_CD_NM": "종로구", "ADSTRD_CD": "11110515", "ADSTRD_CD_NM": "청운효자동"}
        self.docs = {}
        for kind, (_pattern, service) in catalog._SOURCES.items():
            record = deepcopy(self.area)
            if kind != "areas":
                record.update(STDR_YYQU_CD="20262")
            if kind in ("sales", "stores"):
                record.update(SVC_INDUTY_CD="CS100010", SVC_INDUTY_CD_NM="커피-음료")
            record.update(THSMON_SELNG_AMT=100, SIMILR_INDUTY_STOR_CO=2, TOT_FLPOP_CO=50)
            payload = {service: {"RESULT": {"CODE": "INFO-000"}, "list_total_count": 1, "row": [record]}}
            self.docs[kind] = {"service": service, "query": {"dataset": kind, "period": None if kind == "areas" else "20262",
                                                          "area_code": "3110008" if kind == "stores" else None, "start": 1, "count": 1000},
                               "payload": payload, "sample_only": False, "source_url": catalog.SOURCE_URLS[kind],
                               "fetched_at": "2026-11-02T00:00:00+00:00"}
        self.geometry = {"area_code": "3110008", "name": self.area["TRDAR_CD_NM"], "district_code": "11110",
                         "neighborhood_code": "11110515", "neighborhood_name": "청운효자동", "boundary_identity_status": "code_name_match"}

    def write(self):
        for kind, doc in self.docs.items():
            doc["payload_sha256"] = catalog.canonical_hash(doc["payload"])
            query = doc["query"]
            filename = f"{kind}_{query['period'] or 'none'}_{query['area_code'] or 'all'}_1_1000.json"
            (self.root / filename).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def build(self):
        self.write()
        with patch.object(catalog, "_load_geometries", return_value=([self.geometry], [])):
            return catalog.build_catalog(self.root)

    def row(self, kind):
        return self.docs[kind]["payload"][self.docs[kind]["service"]]["row"][0]

    def extra_page(self, doc):
        doc = deepcopy(doc)
        doc["payload_sha256"] = catalog.canonical_hash(doc["payload"])
        query = doc["query"]
        name = f"{query['dataset']}_{query['period']}_{query['area_code'] or 'all'}_{query['start']}_1000.json"
        (self.root / name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def test_citywide_store_source_reconciles_legacy_rows_without_double_counting(self):
        doc = deepcopy(self.docs["stores"])
        doc["query"]["area_code"] = None
        self.extra_page(doc)
        result = self.build()
        self.assertEqual(result["source"]["observed_scope"]["stores"]["20262"]["rows"], 1)
        self.assertEqual(len(result["observations"]["stores"]), 1)
        self.assertEqual(result["source"]["stores_overlap_validation"]["periods"],
                         [{"period": "20262", "matched_rows": 1, "legacy_area_count": 1}])
        self.assertEqual(len([entry for entry in result["source"]["files"] if entry["dataset"] == "stores"]), 2)

    def test_citywide_overlap_compares_non_displayed_fields_too(self):
        self.row("stores")["OPBIZ_RT"] = 0.0
        doc = deepcopy(self.docs["stores"])
        doc["query"]["area_code"] = None
        doc["payload"][doc["service"]]["row"][0]["OPBIZ_RT"] = 1.0
        self.extra_page(doc)
        with self.assertRaisesRegex(ValueError, "preserved area"):
            self.build()

    def test_complete_legacy_area_row_set_must_also_match_citywide(self):
        doc = deepcopy(self.docs["stores"])
        doc["query"]["area_code"] = None
        response = doc["payload"][doc["service"]]
        response["row"].append({**deepcopy(response["row"][0]), "SVC_INDUTY_CD": "CS200041", "SVC_INDUTY_CD_NM": "사진관"})
        response["list_total_count"] = 2
        self.extra_page(doc)
        with self.assertRaisesRegex(ValueError, "row sets"):
            self.build()

    def test_incomplete_citywide_pages_do_not_fall_back_to_complete_legacy(self):
        doc = deepcopy(self.docs["stores"])
        doc["query"].update(area_code=None, count=1)
        doc["payload"][doc["service"]]["list_total_count"] = 2
        self.extra_page(doc)
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            self.build()

    def test_dataset_periods_can_differ_and_uncollected_metrics_remain_distinct(self):
        doc = deepcopy(self.docs["sales"])
        doc["query"]["period"] = "20261"
        doc["payload"][doc["service"]]["row"][0]["STDR_YYQU_CD"] = "20261"
        self.extra_page(doc)
        result = self.build()
        self.assertEqual(result["periods"], ["20262", "20261"])
        self.assertEqual(result["source"]["dataset_periods"],
                         {"sales": ["20262", "20261"], "stores": ["20262"], "population": ["20262"]})
        result["area_index"] = {self.geometry["area_code"]: self.geometry}
        result["coverage_index"] = {(row["dataset"], row["period"], row["area_code"]): row for row in result["coverage"]}
        with patch.object(catalog, "_catalog", return_value=result):
            periods = catalog.get_area_availability("3110008", "CS100010")["periods"]
        self.assertEqual(periods[1]["metrics"]["sales"]["status"], "available")
        self.assertEqual(periods[1]["metrics"]["stores"]["status"], "not_collected")
        self.assertEqual(periods[1]["metrics"]["floating_population"]["status"], "not_collected")

    def test_citywide_coverage_without_industry_row_is_no_observation(self):
        doc = deepcopy(self.docs["stores"])
        doc["query"]["area_code"] = None
        self.extra_page(doc)
        result = self.build()
        result["area_index"] = {self.geometry["area_code"]: self.geometry}
        result["coverage_index"] = {(row["dataset"], row["period"], row["area_code"]): row for row in result["coverage"]
                                    if row["area_code"] is None}
        with patch.object(catalog, "_catalog", return_value=result):
            metric = catalog.get_area_availability("3110008", "CS200041")["periods"][0]["metrics"]["stores"]
        self.assertEqual(metric["status"], "no_observation")

    def test_reviewed_historical_name_is_preserved_but_area_remains_blocked(self):
        for doc in self.docs.values():
            for row in doc["payload"][doc["service"]]["row"]:
                row.update(TRDAR_CD="3110024", TRDAR_CD_NM="혜화동주민센터")
            if doc["query"]["dataset"] == "stores":
                doc["query"]["area_code"] = "3110024"
        self.row("stores")["TRDAR_CD_NM"] = "혜회동주민센터"
        self.geometry.update(area_code="3110024", name="혜화동주민센터", boundary_name="혜회동주민센터", boundary_identity_status="name_mismatch")
        result = self.build()
        self.assertEqual(result["source"]["observation_name_mismatches"], [{"dataset": "stores", "period": "20262",
            "area_code": "3110024", "source_name": "혜회동주민센터", "official_area_name": "혜화동주민센터",
            "row_count": 1, "selection_blocked": True}])
        result["area_index"] = {"3110024": self.geometry}
        result["coverage_index"] = {(r["dataset"], r["period"], r["area_code"]): r for r in result["coverage"]}
        with patch.object(catalog, "_catalog", return_value=result):
            availability = catalog.get_area_availability("3110024", "CS100010")
        self.assertEqual(availability["available_periods"], [])
        self.assertTrue(all(m["status"] == "unavailable" for m in availability["periods"][0]["metrics"].values()))
        self.row("stores")["TRDAR_CD_NM"] = "검증되지 않은 다른 명칭"
        with self.assertRaisesRegex(ValueError, "code/name"):
            self.build()

    def test_other_name_mismatch_is_not_accepted_as_a_historical_exception(self):
        self.geometry.update(boundary_name="이전 이름", boundary_identity_status="name_mismatch")
        self.row("stores")["TRDAR_CD_NM"] = "이전 이름"
        with self.assertRaisesRegex(ValueError, "code/name"):
            self.build()

    def test_missing_value_is_not_zero(self):
        self.row("sales")["THSMON_SELNG_AMT"] = None
        self.row("stores")["SIMILR_INDUTY_STOR_CO"] = 0
        data = self.build()
        data["area_index"] = {self.geometry["area_code"]: self.geometry}
        data["coverage_index"] = {(row["dataset"], row["period"], row["area_code"]): row for row in data["coverage"]}
        with patch.object(catalog, "_catalog", return_value=data):
            metrics = catalog.get_area_availability("3110008", "CS100010")["periods"][0]["metrics"]
        self.assertEqual(metrics["sales"]["status"], "unavailable")
        self.assertEqual(metrics["stores"]["status"], "available")
        self.assertTrue(metrics["stores"]["zero_observation"])

    def test_invalid_numeric_and_identity_rejected(self):
        for value in (True, -1, "NaN", "1,000", "unknown"):
            with self.subTest(value=value):
                self.row("sales")["THSMON_SELNG_AMT"] = value
                with self.assertRaises(ValueError):
                    self.build()
        self.row("sales")["THSMON_SELNG_AMT"] = 100
        self.row("sales")["TRDAR_CD_NM"] = "다른상권"
        with self.assertRaises(ValueError):
            self.build()

    def test_payload_tampering_and_query_period_mismatch_rejected(self):
        self.write()
        path = self.root / "sales_20262_all_1_1000.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["payload"][doc["service"]]["row"][0]["THSMON_SELNG_AMT"] = 999
        path.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaises(ValueError):
            catalog._read_sources(self.root)
        self.row("sales")["STDR_YYQU_CD"] = "20261"
        with self.assertRaises(ValueError):
            self.build()

    def test_incomplete_pages_and_duplicate_observations_rejected(self):
        response = self.docs["sales"]["payload"][self.docs["sales"]["service"]]
        response["list_total_count"] = 2
        self.docs["sales"]["query"]["count"] = 1
        with self.assertRaises(ValueError):
            self.build()
        self.docs["sales"]["query"]["count"] = 1000
        response["row"].append(deepcopy(response["row"][0]))
        with self.assertRaises(ValueError):
            self.build()


if __name__ == "__main__":
    unittest.main()
