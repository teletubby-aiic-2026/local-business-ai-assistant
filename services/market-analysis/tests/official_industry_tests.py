"""Official-source assertions; run only with verify_source --with-official."""
import unittest
from tests.test_onboarding import OnboardingTests, raw_industry_evidence

class OfficialIndustryCatalogueTests(unittest.TestCase):
    setUp = OnboardingTests.setUp
    area_body = OnboardingTests.area_body
    save = OnboardingTests.save
    current = OnboardingTests.current

    def test_industry_catalogue_matches_sales_and_store_original_code_names(self):
        raw = raw_industry_evidence()
        sales, stores = raw["catalogues"]["sales"], raw["catalogues"]["stores"]
        self.assertEqual(raw["conflicts"], [])
        self.assertEqual(len(sales), 62)
        self.assertEqual(len(stores), 100)
        self.assertEqual(len(set(stores) - set(sales)), 38)
        self.assertTrue(sales.items() <= stores.items())
        actual = {item["code"]: item["name"] for item in self.options["industries"]}
        self.assertEqual(actual, stores)
        self.assertEqual(len(actual), len(self.options["industries"]))
        for dataset, periods in raw["period_catalogues"].items():
            self.assertEqual(sorted(periods), self.options["catalog_source"]["dataset_periods"][dataset])
            for period, catalogue in periods.items():
                with self.subTest(dataset=dataset, period=period):
                    self.assertEqual(catalogue, raw["catalogues"][dataset])


    def test_catalogue_source_matches_actual_period_and_store_coverage_without_claiming_analysis(self):
        raw = raw_industry_evidence()
        source = self.options["catalog_source"]
        self.assertEqual(source["industry_count"], 100)
        self.assertEqual(source["dataset_industry_counts"], {"sales": 62, "stores": 100})
        self.assertEqual(source["stores_area_count"], len(raw["stores_area_codes"]))
        self.assertEqual(source["stores_area_codes"], sorted(raw["stores_area_codes"]))
        self.assertEqual(set(source["source_periods"]), set().union(*(set(periods) for periods in raw["period_catalogues"].values())))
        self.assertEqual(source["dataset_periods"], {kind: sorted(periods) for kind, periods in raw["period_catalogues"].items()})
        self.assertEqual(source["stores_area_counts_by_period"], {period: len(codes) for period, codes in raw["stores_area_codes_by_period"].items()})
        self.assertEqual(source["stores_citywide_periods"], sorted(raw["stores_citywide_periods"]))
        self.assertNotIn(None, source["stores_area_codes"])
        self.assertTrue(source["source_scope"]["sales"])
        self.assertTrue(source["source_scope"]["stores"])
        self.assertFalse(source["analysis_availability_verified"])


    def test_all_38_new_store_industries_save_and_restore_official_names(self):
        raw = raw_industry_evidence()["catalogues"]
        additions = {code: name for code, name in raw["stores"].items() if code not in raw["sales"]}
        self.assertEqual(len(additions), 38)
        self.assertEqual(additions["CS200041"], "사진관")
        revision = 0
        for code, name in sorted(additions.items()):
            with self.subTest(code=code, name=name):
                saved = self.save(self.area_body(industry_code=code, expected_revision=revision))
                revision = saved["revision"]
                restored = self.current()["profile"]
                self.assertEqual(restored["industry"], {"code": code, "name": name})
                self.assertEqual(restored["revision"], revision)
                self.assertEqual(restored["location"]["label"], "합정동")
                self.assertFalse(restored["ready_for_analysis"])
        self.assertEqual(self.maps.calls, [])
