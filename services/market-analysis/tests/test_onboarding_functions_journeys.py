"""Real saved-profile HTTP journeys, expected counts read from original files."""
import unittest

from app.onboarding_analysis_catalog import get_analysis_area
from tests import test_onboarding_sales_journeys as helpers
from tests.official_source_oracle import get_oracle, PopulationPairs


class RealFunctionJourneys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.oracle = get_oracle()
        cls.stores_raw = cls.oracle.rows['stores']
        cls.population_raw = PopulationPairs(cls.oracle.rows['population'])

    def setUp(self):
        self.helper = helpers.ActualSalesJourneys()
        self.helper.setUp()
        self.client = self.helper.client

    def tearDown(self):
        self.helper.tearDown()

    def select(self, code, industry, period):
        area = get_analysis_area(code)
        options = self.helper.save_profile({'kind': 'area', 'district_code': area['district_code'],
                                            'neighborhood_code': area['neighborhood_code']}, industry)
        candidate = next(c for c in options['candidates'] if c['area_code'] == code)
        return self.helper.save_selection(options, candidate, period)

    def report(self, feature, saved, **params):
        before = self.client.get('/api/onboarding/analysis-selection').json()
        response = self.client.get('/api/onboarding/' + feature,
                                   params={'expected_revision': saved['revision'], **params})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['revision'], saved['revision'])
        for key in ('area_code', 'industry_code', 'period', 'catalog_version'):
            self.assertEqual(result['selection'][key], saved['analysis_selection'][key])
        self.assertEqual(before, self.client.get('/api/onboarding/analysis-selection').json())
        return result

    def test_stores_ten_areas_three_quarters_match_original(self):
        fields = {'total': 'SIMILR_INDUTY_STOR_CO', 'general': 'STOR_CO', 'franchise': 'FRC_STOR_CO',
                  'opened': 'OPBIZ_STOR_CO', 'closed': 'CLSBIZ_STOR_CO'}
        areas = self.oracle.legacy_areas
        self.assertEqual(len(areas), 10)
        checked = 0
        for area in areas:
            for period in ('20252', '20261', '20262'):
                with self.subTest(area=area, period=period):
                    expected = self.stores_raw[area, 'CS100010', period]
                    result = self.report('stores', self.select(area, 'CS100010', period))
                    for name, field in fields.items():
                        self.assertEqual(result['counts'][name]['value'], int(expected[field]))
                        self.assertEqual(result['counts'][name]['value_text'], str(int(expected[field])))
                    self.assertEqual(result['composition']['status'], 'consistent')
                    checked += 1
        self.assertEqual(checked, 30)

    def test_stores_real_zero_and_closures_exceeding_current_total(self):
        zero_key = next(key for key, row in self.oracle.legacy_stores.items() if row['SIMILR_INDUTY_STOR_CO'] == 0)
        zero = self.report('stores', self.select(*zero_key))
        self.assertEqual(zero['counts']['total']['value'], 0)
        self.assertEqual(zero['counts']['total']['status'], 'available')
        self.assertIsNone(zero['composition']['franchise_share_percent'])
        key = ('3110562', 'CS100002', '20261')
        result = self.report('stores', self.select(*key))
        self.assertEqual(result['counts']['total']['value'], 1)
        self.assertEqual(result['counts']['closed']['value'], 2)
        self.assertNotIn('closure_rate', result)

    def test_stores_newly_collected_area_matches_source_and_sales_still_available(self):
        from app.onboarding_analysis_catalog import get_analysis_areas
        area = next(a for a in get_analysis_areas() if a['name'] == '압구정로데오역(압구정로데오)')
        saved = self.select(area['area_code'], 'CS100010', '20262')
        result = self.report('stores', saved)
        expected = self.stores_raw[area['area_code'], 'CS100010', '20262']
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['counts']['total']['value'], int(expected['SIMILR_INDUTY_STOR_CO']))
        self.assertEqual(result['source']['collection_scope'], 'citywide')
        sales = self.report('sales', saved)
        self.assertEqual(sales['status'], 'available')

    def test_population_six_areas_three_quarters_match_original(self):
        from app.onboarding_analysis_catalog import get_analysis_areas
        names = ('연트럴파크(연남동주민센터)', '압구정로데오역(압구정로데오)',
                 '강남 마이스 관광특구')
        areas = [a for a in get_analysis_areas() if a['name'] in names]
        districts = {a['district_code'] for a in areas}
        for area in get_analysis_areas():
            if len(areas) == 6:
                break
            if (area['district_code'] not in districts
                    and area.get('boundary_identity_status') != 'mismatch'
                    and all((area['area_code'], p) in self.population_raw
                            for p in ('20252', '20261', '20262'))):
                areas.append(area)
                districts.add(area['district_code'])
        self.assertEqual(len(areas), 6)
        for area in areas:
            for period in ('20252', '20261', '20262'):
                with self.subTest(area=area['name'], period=period):
                    saved = self.select(area['area_code'], 'CS100010', period)
                    result = self.report('population', saved)
                    expected = int(self.population_raw[area['area_code'], period]['TOT_FLPOP_CO'])
                    self.assertEqual(result['total']['value'], expected)
                    self.assertEqual(result['total']['value_text'], str(expected))
                    self.assertTrue(result['evidence'])

    def test_population_unchanged_across_industries_with_sales_gaps(self):
        area = '3110562'
        reports = []
        for industry in ('CS100010', 'CS100002', 'CS200009'):
            with self.subTest(industry=industry):
                saved = self.select(area, industry, '20261')
                result = self.report('population', saved)
                self.assertEqual(result['population_scope'], 'area_wide')
                self.assertIs(result['industry_applied'], False)
                reports.append(result)
                self.report('sales', saved)
                self.report('stores', saved)
        for report in reports[1:]:
            self.assertEqual(reports[0]['total'], report['total'])
            self.assertEqual(reports[0]['distributions'], report['distributions'])

    def test_population_missing_in_exact_period_does_not_reuse_previous_row(self):
        previous = self.report('population', self.select('3111002', 'CS100001', '20261'))
        self.assertIsNotNone(previous['total']['value'])
        saved = self.select('3111002', 'CS100001', '20262')
        current = self.report('population', saved)
        self.assertEqual(current['observation_status'], 'no_observation')
        self.assertIsNone(current['total']['value'])
        self.assertEqual(self.report('sales', saved)['total']['value'], 39561610)

    def test_comparison_values_equal_individual_feature_results_and_do_not_change_base(self):
        first, other = '3110562', '3001496'
        for period in ('20252', '20261', '20262'):
            with self.subTest(period=period):
                expected = {}
                for side, code in (('base', first), ('comparison', other)):
                    saved = self.select(code, 'CS100010', period)
                    sales = self.report('sales', saved)
                    stores = self.report('stores', saved)
                    population = self.report('population', saved)
                    expected[side] = {'sales': sales['total']['value'],
                                      'floating_population': population['total']['value'],
                                      **{'stores_' + key: item['value']
                                         for key, item in stores['counts'].items()}}
                saved = self.select(first, 'CS100010', period)
                result = self.report('comparison', saved, comparison_area_code=other)
                self.assertEqual(result['comparison_direction'], 'comparison_minus_base')
                self.assertEqual(len(result['metrics']), 7)
                for metric in result['metrics']:
                    key = metric['key']
                    for side in ('base', 'comparison'):
                        self.assertEqual(metric[side]['value'], expected[side][key])
                    left, right = expected['base'][key], expected['comparison'][key]
                    if left is not None and right is not None:
                        self.assertEqual(metric['delta'], right - left)
                        self.assertEqual(metric['delta_text'], str(right - left))
                    else:
                        self.assertIsNone(metric['delta'])

    def test_comparison_outside_nearby_candidates_keeps_available_metrics(self):
        saved = self.select('3110562', 'CS100010', '20262')
        options = self.client.get('/api/onboarding/analysis-options').json()
        self.assertNotIn('3110545', [a['area_code'] for a in options['candidates']])
        result = self.report('comparison', saved, comparison_area_code='3110545')
        metrics = {row['key']: row for row in result['metrics']}
        self.assertEqual(metrics['floating_population']['comparison']['value'], 460847)
        self.assertIsNotNone(metrics['sales']['delta'])
        self.assertIsNotNone(metrics['floating_population']['delta'])
        expected = int(self.stores_raw['3110545', 'CS100010', '20262']['SIMILR_INDUTY_STOR_CO'])
        self.assertEqual(metrics['stores_total']['comparison']['value'], expected)
        self.assertEqual(metrics['stores_total']['delta'], expected - metrics['stores_total']['base']['value'])
        self.assertEqual(result['status'], 'complete')

    def values_for(self, saved):
        return {'sales': self.report('sales', saved)['total']['value'],
                'floating_population': self.report('population', saved)['total']['value'],
                **{'stores_' + key: value['value']
                   for key, value in self.report('stores', saved)['counts'].items()}}

    def test_changes_both_modes_match_each_feature_at_exact_periods(self):
        # Tourist district, alley area and an area added by citywide collection.
        for area in ('3001496', '3110562', '3110545'):
            for mode, previous_period in (('qoq', '20261'), ('yoy', '20252')):
                with self.subTest(area=area, mode=mode):
                    previous = self.values_for(self.select(area, 'CS100010', previous_period))
                    saved = self.select(area, 'CS100010', '20262')
                    current = self.values_for(saved)
                    result = self.report('changes', saved, comparison=mode)
                    self.assertEqual(result['current_period']['code'], '20262')
                    self.assertEqual(result['previous_period']['code'], previous_period)
                    self.assertEqual(result['comparison_direction'], 'current_minus_previous')
                    self.assertEqual(len(result['metrics']), 7)
                    for metric in result['metrics']:
                        key = metric['key']
                        self.assertEqual(metric['current']['value'], current[key])
                        self.assertEqual(metric['previous']['value'], previous[key])
                        if current[key] is None or previous[key] is None:
                            self.assertIsNone(metric['delta'])
                        else:
                            self.assertEqual(metric['delta'], current[key] - previous[key])
                            self.assertEqual(metric['delta_text'], str(current[key] - previous[key]))

    def test_changes_newly_collected_quarters_are_used_at_exact_baselines(self):
        for mode, period in (('qoq', '20254'), ('yoy', '20251')):
            with self.subTest(mode=mode):
                previous = self.values_for(self.select('3001496', 'CS100010', period))
                saved = self.select('3001496', 'CS100010', '20261')
                current = self.values_for(saved)
                result = self.report('changes', saved, comparison=mode)
                self.assertEqual(result['status'], 'complete')
                self.assertEqual(result['previous_period']['code'], period)
                for metric in result['metrics']:
                    self.assertEqual(metric['current']['value'], current[metric['key']])
                    self.assertEqual(metric['previous']['value'], previous[metric['key']])
                    self.assertEqual(metric['delta'], current[metric['key']] - previous[metric['key']])

    def test_changes_earliest_quarter_missing_baselines_never_substitute_collected_period(self):
        self.assertEqual(self.oracle.periods['stores'][0], '20243')
        saved = self.select('3001496', 'CS100010', '20243')
        current = self.values_for(saved)
        for mode, period in (('qoq', '20242'), ('yoy', '20233')):
            with self.subTest(mode=mode):
                result = self.report('changes', saved, comparison=mode)
                self.assertEqual(result['status'], 'no_comparison')
                self.assertEqual(result['previous_period']['code'], period)
                for metric in result['metrics']:
                    self.assertEqual(metric['current']['value'], current[metric['key']])
                    self.assertEqual(metric['previous']['status'], 'not_collected')
                    self.assertIsNone(metric['previous']['value'])
                    self.assertIsNone(metric['delta'])
                    self.assertIsNone(metric['percent'])

    def test_profile_change_invalidates_all_reports_until_new_conditions_are_saved(self):
        saved = self.select('3110562', 'CS100010', '20262')
        self.report('comparison', saved, comparison_area_code='3001496')
        self.report('changes', saved, comparison='qoq')
        area = get_analysis_area('3110562')
        options = self.helper.save_profile({'kind': 'area', 'district_code': area['district_code'],
            'neighborhood_code': area['neighborhood_code']}, 'CS200009')
        endpoints = [('sales', {}), ('stores', {}), ('population', {}), ('comparison-options', {}),
                     ('comparison', {'comparison_area_code': '3001496'}), ('changes', {'comparison': 'qoq'})]
        for feature, params in endpoints:
            response = self.client.get('/api/onboarding/' + feature,
                                       params={'expected_revision': saved['revision'], **params})
            self.assertEqual(response.status_code, 409, (feature, response.text))
        candidate = next(c for c in options['candidates'] if c['area_code'] == '3110562')
        saved = self.helper.save_selection(options, candidate, '20262')
        for feature, params in endpoints:
            if feature == 'comparison-options':
                continue
            result = self.report(feature, saved, **params)
            self.assertEqual(result['selection']['industry_code'], 'CS200009')


if __name__ == '__main__':
    unittest.main()
