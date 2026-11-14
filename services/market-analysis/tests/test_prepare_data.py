"""Offline checks of explicit collection, immutable sources, and publication."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.data_repository import SOURCE_URLS, canonical_hash
from app.seoul_client import SERVICES
from scripts import prepare_data as preparation


class FakeClient:
    sample_only = False

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [{'TRDAR_CD': '3110008', 'STDR_YYQU_CD': '20262'}]
        self.calls = []

    def fetch_page(self, dataset, period, start, count):
        self.calls.append((dataset, period, start, count))
        service = SERVICES[dataset]
        payload = {service: {'RESULT': {'CODE': 'INFO-000', 'MESSAGE': 'ok'},
                            'list_total_count': len(self.rows), 'row': deepcopy(self.rows)}}
        return SimpleNamespace(service=service, payload=payload, sample_only=False,
                               source_url='https://example.test/redacted')


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_default_command_is_read_only_and_does_not_load_settings(self):
        with patch.object(preparation, 'readiness', return_value={'status': 'data_required'}) as status, \
                patch.object(preparation, 'SeoulClient', side_effect=AssertionError('must not construct a client')), \
                patch.object(preparation, 'validate_and_publish', side_effect=AssertionError('must not publish')):
            self.assertEqual(preparation.main([]), 0)
            status.assert_called_once_with()

    def test_missing_snapshot_reports_data_requirement(self):
        self.assertEqual(preparation.readiness(self.root)['status'], 'data_required')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_exclusive_source_copy_is_idempotent_and_rejects_conflict(self):
        source, target = self.root / 'source', self.root / 'target'
        source.write_bytes(b'first')
        preparation.immutable_copy(source, target)
        preparation.immutable_copy(source, target)
        source.write_bytes(b'changed')
        with self.assertRaises(preparation.PreparationError):
            preparation.immutable_copy(source, target)
        self.assertEqual(target.read_bytes(), b'first')

    def test_collector_preserves_source_envelope_and_reuses_checked_cache(self):
        client = FakeClient()
        collector = preparation.Collector(client, self.root, max_requests=1)
        self.assertEqual(collector.table('stores', '20262')['rows'], 1)
        self.assertEqual(collector.table('stores', '20262')['rows'], 1)
        self.assertEqual(len(client.calls), 1)
        doc = json.loads(next(self.root.glob('stores_*.json')).read_text(encoding='utf-8'))
        self.assertEqual(doc['source_url'], SOURCE_URLS['stores'])
        self.assertEqual(doc['payload_sha256'], canonical_hash(doc['payload']))
        self.assertEqual(doc['query']['area_code'], None)

    def test_wrong_period_or_incomplete_source_is_not_written(self):
        collector = preparation.Collector(FakeClient([{'STDR_YYQU_CD': '20261'}]), self.root)
        with self.assertRaises(preparation.PreparationError):
            collector.table('stores', '20262')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_area_collection_does_not_require_a_quarter(self):
        collector = preparation.Collector(FakeClient([{'TRDAR_CD': '3110008'}]), self.root)
        self.assertEqual(collector.table('areas')['rows'], 1)
        self.assertTrue((self.root / 'areas_none_all_1_1000.json').is_file())

    def test_cached_payload_tampering_and_exhausted_budget_are_rejected(self):
        client = FakeClient()
        collector = preparation.Collector(client, self.root, max_requests=1)
        collector.table('stores', '20262')
        with self.assertRaises(preparation.PreparationError):
            collector.table('sales', '20262')
        path = next(self.root.glob('stores_*.json'))
        doc = json.loads(path.read_text(encoding='utf-8'))
        doc['payload_sha256'] = '0' * 64
        path.write_text(json.dumps(doc), encoding='utf-8')
        with self.assertRaises(preparation.PreparationError):
            collector.table('stores', '20262')
        self.assertEqual(len(client.calls), 1)

    def test_missing_boundary_and_changed_reviewed_boundary_are_rejected(self):
        with self.assertRaises(preparation.PreparationError):
            preparation.source_files(self.root)
        (self.root / preparation.BOUNDARY_NAME).write_bytes(b'not-reviewed')
        with self.assertRaises(preparation.PreparationError):
            preparation.source_files(self.root)

    def test_initial_publication_requires_no_legacy_release_and_preserves_user_db(self):
        raw = self.root / 'input'
        raw.mkdir()
        boundary = raw / preparation.BOUNDARY_NAME
        boundary.write_bytes(b'synthetic-reviewed-boundary')
        source = raw / 'areas_none_all_1_1000.json'
        source.write_text('{}', encoding='utf-8')
        package = self.root / 'package'
        (package / 'app').mkdir(parents=True)
        choices = {'districts': [{'code': '11110', 'name': '종로구'}],
                   'industries': [{'code': 'CS100010', 'name': '커피-음료'}]}
        (package / 'app/onboarding_industries.json').write_text(json.dumps(choices), encoding='utf-8')
        (package / 'data').mkdir()
        database = package / 'data/onboarding.sqlite3'
        database.write_bytes(b'private-user-db')
        industry = {**choices, 'catalog_source': {'files': [{'path': 'development/data/raw/official/' + source.name}]}}
        catalog = {'catalog_version': 'synthetic-version', 'periods': ['20262']}
        with patch.object(preparation, 'BOUNDARY_SHA256', sha256(boundary.read_bytes()).hexdigest()), \
                patch('app.onboarding_analysis_catalog.build_catalog', return_value=catalog), \
                patch('app.onboarding_catalog.build_catalog', return_value=industry):
            result = preparation.validate_and_publish(raw, root=package)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(json.loads((package / 'data/official/onboarding_analysis_catalog.json').read_text()), catalog)
        self.assertEqual(database.read_bytes(), b'private-user-db')
        self.assertFalse((package / 'data/official/current.json').exists())

    def test_failed_validation_does_not_publish(self):
        raw = self.root / 'input'
        raw.mkdir()
        boundary = raw / preparation.BOUNDARY_NAME
        boundary.write_bytes(b'synthetic-reviewed-boundary')
        package = self.root / 'package'
        with patch.object(preparation, 'BOUNDARY_SHA256', sha256(boundary.read_bytes()).hexdigest()), \
                patch('app.onboarding_analysis_catalog.build_catalog', side_effect=ValueError('invalid data')):
            with self.assertRaises(ValueError):
                preparation.validate_and_publish(raw, root=package)
        self.assertFalse(package.exists())


if __name__ == '__main__':
    unittest.main()
