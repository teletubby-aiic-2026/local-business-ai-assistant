"""Run explicit offline suites; add --with-official for original-data checks.

The default suite uses synthetic inputs, temporary/in-memory SQLite, and checked-in
selection lists. It requires no API key, raw statistics, or source catalogue.
The optional suite requires prepared official raw sources and never fetches them.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE_TESTS = (
    'tests.test_onboarding', 'tests.test_intake_location',
    'tests.test_onboarding_analysis',
    'tests.test_onboarding_analysis_catalog.RawValidationTests',
    'tests.test_onboarding_sales', 'tests.test_onboarding_stores', 'tests.test_onboarding_area_context',
    'tests.test_onboarding_population', 'tests.test_onboarding_comparison',
    'tests.test_onboarding_changes', 'tests.test_prepare_data',
    'tests.test_source_runtime', 'tests.test_onboarding_data_sync',
)
OFFICIAL_TESTS = (
    'tests.official_selection_tests.OfficialSelectionTests',
    'tests.official_industry_tests.OfficialIndustryCatalogueTests',
    'tests.test_onboarding_analysis_catalog.AnalysisCatalogTests',
    'tests.test_onboarding_analysis_independent', 'tests.test_onboarding_analysis_journeys',
    'tests.test_onboarding_sales_independent', 'tests.test_onboarding_sales_journeys',
    'tests.test_onboarding_stores_independent', 'tests.test_onboarding_population_independent',
    'tests.test_onboarding_comparison_independent', 'tests.test_onboarding_changes_independent',
    'tests.test_onboarding_functions_journeys',
)


def check_suite_inputs(names, with_official):
    for name in names:
        module = '.'.join(name.split('.')[:2])
        path = ROOT / (module.replace('.', '/') + '.py')
        if not path.is_file():
            raise ValueError('Required test module is missing: ' + module)
    if with_official:
        raw = ROOT / 'data/raw/official'
        snapshot = ROOT / 'data/official/onboarding_analysis_catalog.json'
        if not snapshot.is_file() or not raw.is_dir():
            raise ValueError('Official suite requires prepared data. Run scripts.prepare_data --from-dir PATH or --collect first.')
        data = json.loads(snapshot.read_text(encoding='utf-8'))
        for entry in data['source']['files']:
            relative = Path(entry['path'])
            if relative.is_absolute() or '..' in relative.parts or not (ROOT / relative).is_file():
                raise ValueError('Official suite source is missing or invalid: ' + str(relative))
        if not (raw / 'OA-15560_seq5_boundaries.zip').is_file():
            raise ValueError('Official suite requires the reviewed boundary ZIP')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-official', action='store_true', help='Include independent original-data assertions; never download data')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args(argv)
    names = SOURCE_TESTS + (OFFICIAL_TESTS if args.with_official else ())
    try:
        check_suite_inputs(names, args.with_official)
    except (ValueError, KeyError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    from app.onboarding import OnboardingStore
    original_init = OnboardingStore.__init__
    stores = []

    def isolated_init(self, path=None, **kwargs):
        target = ':memory:' if path is None else path
        original_init(self, target, **kwargs)
        stores.append(str(target))

    with ExitStack() as stack:
        stack.enter_context(patch.object(OnboardingStore, '__init__', isolated_init))
        stack.enter_context(patch('socket.create_connection', side_effect=AssertionError('Network forbidden in offline verification')))
        stack.enter_context(patch('app.config.load_settings', side_effect=AssertionError('Credential loading forbidden in offline verification')))
        suite = unittest.defaultTestLoader.loadTestsFromNames(names)
        result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    print(json.dumps({'suite': 'source_and_official' if args.with_official else 'source_only',
                      'tests_run': result.testsRun, 'failures': len(result.failures),
                      'errors': len(result.errors), 'skipped': len(result.skipped),
                      'stores': len(stores), 'memory_stores': stores.count(':memory:'),
                      'official_tests_selected': args.with_official,
                      'network': 'blocked'}, ensure_ascii=False))
    return 0 if result.wasSuccessful() and result.testsRun > 0 and not result.skipped else 1


if __name__ == '__main__':
    raise SystemExit(main())
