"""B1 -> B2 real-catalogue HTTP journeys with independent raw expected totals."""
import importlib
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.onboarding import OnboardingStore
from app.onboarding_neighborhoods import get_neighborhoods
from app.onboarding_stations import get_stations
from app.onboarding_station_lines import get_station_line_codes
from tests.official_source_oracle import get_oracle

_original_init = OnboardingStore.__init__


def _memory_default(self, path=None, **kwargs):
    _original_init(self, ':memory:' if path is None else path, **kwargs)


with patch.object(OnboardingStore, '__init__', _memory_default):
    intake_api = importlib.import_module('app.intake_api')


class ActualSalesJourneys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.oracle = get_oracle()
        cls.expected = cls.oracle.rows['sales']

    def setUp(self):
        self.store = OnboardingStore(':memory:')
        self.client = TestClient(intake_api.create_app(self.store))

    def tearDown(self):
        self.client.close()
        self.store.close()

    def save_profile(self, location, industry):
        revision = self.client.get('/api/onboarding/profile').json()['revision']
        response = self.client.post('/api/onboarding/profile', json={
            'location': location, 'industry_code': industry,
            'business_status': 'planning', 'expected_revision': revision,
        })
        self.assertEqual(response.status_code, 200, response.text)
        options = self.client.get('/api/onboarding/analysis-options')
        self.assertEqual(options.status_code, 200, options.text)
        return options.json()

    def save_selection(self, options, candidate, period):
        revision = self.client.get('/api/onboarding/profile').json()['revision']
        response = self.client.post('/api/onboarding/analysis-selection', json={
            'area_code': candidate['area_code'], 'period': period,
            'expected_revision': revision,
            'expected_catalog_version': options['catalog_version'],
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def assert_report(self, saved):
        before = self.client.get('/api/onboarding/analysis-selection').json()
        response = self.client.get('/api/onboarding/sales', params={'expected_revision': saved['revision']})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        selected = saved['analysis_selection']
        for key in ('area_code', 'industry_code', 'period', 'catalog_version'):
            self.assertEqual(result['selection'][key], selected[key])
        key = selected['area_code'], selected['industry_code'], selected['period']
        row = self.expected.get(key)
        expected = int(row['THSMON_SELNG_AMT']) if row is not None else None
        self.assertEqual(result['total']['value'], expected)
        self.assertEqual(result['status'], 'no_data' if expected is None else 'available')
        if expected is not None:
            self.assertEqual(result['total']['value_text'], str(expected))
            self.assertEqual(result['total']['unit'], '원')
            self.assertTrue(result['evidence'])
        self.assertEqual(self.client.get('/api/onboarding/analysis-selection').json(), before)
        self.assertEqual(self.client.get('/api/onboarding/sales', params={
            'expected_revision': saved['revision'],
        }).json(), result)
        return result

    def test_six_neighborhood_industries_and_three_exact_quarters(self):
        cases = [('마포구', '연남동', 'CS100010'),
                 ('성동구', '성수1가1동', 'CS100001'),
                 ('중랑구', '신내1동', 'CS300002'),
                 ('강남구', '역삼1동', 'CS200007'),
                 ('용산구', '이태원1동', 'CS100004'),
                 ('종로구', '종로1.2.3.4가동', 'CS100005')]
        visited = set()
        for district, name, industry in cases:
            with self.subTest(district=district, neighborhood=name, industry=industry):
                neighborhood = next(n for n in get_neighborhoods()
                                    if n['district_name'] == district and n['name'] == name)
                options = self.save_profile({'kind': 'area', 'district_code': neighborhood['district_code'],
                                             'neighborhood_code': neighborhood['code']}, industry)
                # B1 can legitimately be saved using population alone. Keep
                # such real combinations in the journey and expect no_data.
                eligible = [c for c in options['candidates'] if
                            all(p in c['available_periods'] for p in ('20262', '20261', '20252'))]
                candidate = max(eligible, key=lambda c: sum(
                    (c['area_code'], industry, p) in self.expected for p in ('20262', '20261', '20252')))
                for period in ('20262', '20261', '20252'):
                    self.assert_report(self.save_selection(options, candidate, period))
                    visited.add((candidate['area_code'], industry, period))
        self.assertEqual(len(visited), 18)

    def test_station_selection_then_industry_change_removes_previous_sales(self):
        station = next(s for s in get_stations() if s['name'] == '강남역'
                       and 'line-2' in get_station_line_codes(s['id']))
        location = {'kind': 'station', 'station_id': station['id'], 'station_line_code': 'line-2'}
        options = self.save_profile(location, 'CS100010')
        candidate = next(c for c in options['candidates']
                         if (c['area_code'], 'CS100010', '20262') in self.expected
                         and '20262' in c['available_periods'])
        first = self.save_selection(options, candidate, '20262')
        self.assert_report(first)
        options = self.save_profile(location, 'CS200009')  # 동물병원: no retained sales rows.
        self.assertEqual(self.client.get('/api/onboarding/sales', params={
            'expected_revision': first['revision'],
        }).status_code, 409)
        self.assertEqual(self.client.get('/api/onboarding/sales').status_code, 409)
        candidate = next(c for c in options['candidates'] if '20262' in c['available_periods'])
        report = self.assert_report(self.save_selection(options, candidate, '20262'))
        self.assertEqual(report['status'], 'no_data')
        self.assertEqual(report['summary'], [])

    def test_same_shop_can_select_each_of_eight_consecutive_quarters(self):
        neighborhood = next(n for n in get_neighborhoods() if n['name'] == '연남동')
        options = self.save_profile({'kind': 'area', 'district_code': neighborhood['district_code'],
                                    'neighborhood_code': neighborhood['code']}, 'CS100010')
        periods = self.oracle.periods['sales']
        self.assertEqual(periods, ['20243', '20244', '20251', '20252', '20253', '20254', '20261', '20262'])
        candidate = next(c for c in options['candidates'] if c['area_code'] == '3110562')
        self.assertTrue(set(periods).issubset(candidate['available_periods']))
        for period in periods:
            with self.subTest(period=period):
                self.assert_report(self.save_selection(options, candidate, period))

    def test_new_session_cannot_read_another_users_saved_sales(self):
        neighborhood = next(n for n in get_neighborhoods() if n['name'] == '연남동')
        options = self.save_profile({'kind': 'area', 'district_code': neighborhood['district_code'],
                                     'neighborhood_code': neighborhood['code']}, 'CS100010')
        candidate = next(c for c in options['candidates'] if '20262' in c['available_periods'])
        saved = self.save_selection(options, candidate, '20262')
        self.assert_report(saved)
        stranger = TestClient(intake_api.create_app(self.store))
        try:
            self.assertEqual(stranger.get('/api/onboarding/sales').status_code, 409)
        finally:
            stranger.close()
        self.assert_report(saved)


if __name__ == '__main__':
    unittest.main()
