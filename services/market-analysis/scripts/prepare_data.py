"""Check data readiness; explicitly import or collect official source data.

No argument loads credentials or performs network requests. --from-dir validates
an existing official raw-source directory. --collect fetches the selected periods
using SEOUL_OPENAPI_KEY. Both explicit actions validate before publication.
Original source files are immutable; conflicting bytes require a separate data
directory and review. Stop the application while preparing a new snapshot.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import zipfile
import io

from app.data_repository import SOURCE_URLS, atomic_json_write, canonical_hash
from app.seoul_client import SeoulApiError, SeoulClient, SERVICES, parse_seoul_response, validate_query

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PERIODS = ('20243', '20244', '20251', '20252', '20253', '20254', '20261', '20262')
BOUNDARY_NAME = 'OA-15560_seq5_boundaries.zip'
BOUNDARY_SHA256 = '38bb8fab4e45a1171af4989cd7fa1275f68e5d644aa770f5431ce7ccc38384dd'
BOUNDARY_URL = 'https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false'
SOURCE_NAME = re.compile(r'(?:areas_none_all|(?:sales|population)_[0-9]{5}_all|stores_[0-9]{5}_(?:all|[0-9]{7}))_[0-9]+_[0-9]+\.json')


class PreparationError(ValueError):
    pass


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def immutable_copy(source, destination):
    """Copy complete bytes exclusively; never overwrite an existing source."""
    source, destination = Path(source), Path(destination)
    expected = digest(source)
    if destination.exists():
        if not destination.is_file() or destination.is_symlink() or digest(destination) != expected:
            raise PreparationError('Existing official source differs; use a separate data directory')
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.source-', delete=False) as output:
            temporary = Path(output.name)
            with source.open('rb') as stream:
                shutil.copyfileobj(stream, output)
            output.flush()
            os.fsync(output.fileno())
        if digest(temporary) != expected:
            raise PreparationError('Source changed while copying')
        if os.name == 'nt':
            temporary.rename(destination)
            temporary = None
        else:
            os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def source_files(raw):
    raw = Path(raw)
    if not raw.is_dir() or raw.is_symlink():
        raise PreparationError('An official raw-source directory is required')
    files = []
    for path in sorted(raw.iterdir()):
        if not (SOURCE_NAME.fullmatch(path.name) or path.name == BOUNDARY_NAME):
            continue
        if not path.is_file() or path.is_symlink():
            raise PreparationError('Official sources must be regular files')
        files.append(path)
    if not files or not (raw / BOUNDARY_NAME).is_file():
        raise PreparationError('Official API pages and the reviewed boundary ZIP are required')
    if digest(raw / BOUNDARY_NAME) != BOUNDARY_SHA256:
        raise PreparationError('Boundary version differs from the reviewed 2023 publication')
    return files


class Collector:
    """Bounded, source-preserving collection based on the existing collector."""
    def __init__(self, client, raw, max_requests=1000):
        if type(max_requests) is not int or not 1 <= max_requests <= 2000:
            raise PreparationError('Request limit must be between 1 and 2000')
        self.client, self.raw = client, Path(raw)
        self.max_requests, self.requests = max_requests, 0

    def page(self, dataset, period, start):
        validate_query(dataset, period, start, 1000)
        name = f'{dataset}_{period or "none"}_all_{start}_{start + 999}.json'
        path = self.raw / name
        query = {'dataset': dataset, 'period': period, 'start': start, 'count': 1000, 'area_code': None}
        if path.exists():
            doc = json.loads(path.read_text(encoding='utf-8-sig'))
        else:
            if self.client.sample_only or self.requests >= self.max_requests:
                raise PreparationError('A configured Seoul API key and remaining request budget are required')
            self.requests += 1
            page = self.client.fetch_page(dataset, period, start, 1000)
            doc = {'validation_status': 'RAW / NOT AN ANALYSIS RELEASE', 'query': query,
                   'fetched_at': datetime.now(timezone.utc).isoformat(), 'service': page.service,
                   'sample_only': page.sample_only, 'source_url': SOURCE_URLS[dataset],
                   'request_url_redacted': page.source_url, 'payload_sha256': canonical_hash(page.payload),
                   'payload': page.payload}
        if (doc.get('query') != query or doc.get('service') != SERVICES[dataset]
                or doc.get('sample_only') is not False or doc.get('source_url') != SOURCE_URLS[dataset]
                or doc.get('payload_sha256') != canonical_hash(doc.get('payload'))):
            raise PreparationError('Source identity or payload hash mismatch')
        parsed = parse_seoul_response(doc['payload'], SERVICES[dataset])
        if (parsed.result_code != 'INFO-000' or parsed.total_count <= 0
                or len(parsed.rows) != min(1000, parsed.total_count - start + 1) or not parsed.rows
                or (period is not None and any(row.get('STDR_YYQU_CD') != period for row in parsed.rows))):
            raise PreparationError('Empty, incomplete or wrong-period source page')
        if not path.exists():
            atomic_json_write(path, doc)
        return parsed

    def table(self, dataset, period=None):
        first = self.page(dataset, period, 1)
        total, observed = first.total_count, len(first.rows)
        for start in range(1001, total + 1, 1000):
            page = self.page(dataset, period, start)
            if page.total_count != total:
                raise PreparationError('Provider total changed during collection')
            observed += len(page.rows)
        if observed != total:
            raise PreparationError('Collected row count differs from source total')
        return {'dataset': dataset, 'period': period, 'rows': observed}


def download_boundary(destination):
    request = Request(BOUNDARY_URL, data=urlencode({'infId': 'OA-15560', 'seqNo': '', 'seq': '5', 'infSeq': '3'}).encode(),
                      headers={'Referer': SOURCE_URLS['areas']}, method='POST')
    with urlopen(request, timeout=30) as response:
        content = response.read(10 * 1024 * 1024 + 1)
    if (len(content) > 10 * 1024 * 1024 or not zipfile.is_zipfile(io.BytesIO(content))
            or sha256(content).hexdigest() != BOUNDARY_SHA256):
        raise PreparationError('Downloaded boundary is not the reviewed publication')
    Path(destination).write_bytes(content)


def validate_and_publish(raw, *, root=ROOT):
    from app.onboarding_analysis_catalog import build_catalog
    from app.onboarding_catalog import build_catalog as build_industries

    raw, root = Path(raw), Path(root)
    inputs = source_files(raw)
    before = {path.name: digest(path) for path in inputs}
    catalog = build_catalog(raw)
    industries = build_industries(raw)
    checked_choices = json.loads((root / 'app/onboarding_industries.json').read_text(encoding='utf-8'))
    for field in ('districts', 'industries'):
        if industries[field] != checked_choices[field]:
            raise PreparationError('Official form choices changed; review the source package first')
    if {path.name: digest(path) for path in source_files(raw)} != before:
        raise PreparationError('Source files changed during validation')
    target = root / 'data/raw/official'
    target.mkdir(parents=True, exist_ok=True)
    # Preflight every collision before publishing any file.
    for path in inputs:
        destination = target / path.name
        if destination.exists() and (not destination.is_file() or destination.is_symlink() or digest(destination) != before[path.name]):
            raise PreparationError('Published source differs; preserve it and review the new snapshot separately')
    for path in inputs:
        immutable_copy(path, target / path.name)
    for path in inputs:
        if digest(target / path.name) != before[path.name]:
            raise PreparationError('Published source hash mismatch')
    # Rewrite only generated catalogues; never create or modify a user database.
    for item in industries['catalog_source']['files']:
        item['path'] = 'data/raw/official/' + Path(item['path']).name
    atomic_json_write(root / 'app/onboarding_industries.json', industries)
    atomic_json_write(root / 'data/official/onboarding_analysis_catalog.json', catalog)
    return {'status': 'ready', 'catalog_version': catalog['catalog_version'],
            'periods': catalog['periods'], 'source_files': len(inputs)}


def readiness(root=ROOT):
    root = Path(root)
    snapshot = root / 'data/official/onboarding_analysis_catalog.json'
    if not snapshot.is_file():
        return {'status': 'data_required', 'next': 'Use --from-dir OFFICIAL_RAW_DIRECTORY or --collect explicitly'}
    catalog = json.loads(snapshot.read_text(encoding='utf-8'))
    missing = [entry['path'] for entry in catalog['source']['files'] if not (root / entry['path']).is_file()]
    return {'status': 'source_files_missing' if missing else 'prepared_not_revalidated',
            'catalog_version': catalog['catalog_version'], 'periods': catalog['periods'], 'missing_files': len(missing),
            'next': 'python -m scripts.verify_source --with-official'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--collect', action='store_true', help='Fetch official data with a Seoul API key, validate, and publish')
    action.add_argument('--from-dir', type=Path, help='Validate and import an existing official raw-source directory without network')
    parser.add_argument('--periods', nargs='+', default=list(DEFAULT_PERIODS))
    parser.add_argument('--max-requests', type=int, default=1000)
    args = parser.parse_args(argv)
    if not args.collect and args.from_dir is None:
        print(json.dumps(readiness(), ensure_ascii=False))
        return 0
    try:
        if args.from_dir is not None:
            result = validate_and_publish(args.from_dir)
        else:
            if not 1 <= len(args.periods) <= 12 or len(args.periods) != len(set(args.periods)):
                raise PreparationError('Choose 1 to 12 distinct quarters')
            for period in args.periods:
                validate_query('sales', period, 1, 1000)
            from app.config import load_settings
            load_settings()
            stage_root = ROOT / 'data/staging'
            stage_root.mkdir(parents=True, exist_ok=True)
            raw = Path(tempfile.mkdtemp(prefix='official-collection-', dir=stage_root))
            collector = Collector(SeoulClient(), raw, args.max_requests)
            collector.table('areas')
            download_boundary(raw / BOUNDARY_NAME)
            for period in args.periods:
                for dataset in ('stores', 'sales', 'population'):
                    print(json.dumps(collector.table(dataset, period), ensure_ascii=False), flush=True)
            result = validate_and_publish(raw)
            result['api_requests'] = collector.requests
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (PreparationError, SeoulApiError, OSError, ValueError, KeyError, HTTPError, URLError) as error:
        # Never print provider URLs, API keys, or arbitrary exception messages.
        print(json.dumps({'status': 'not_published_or_incomplete', 'error_type': type(error).__name__,
                          'message': 'Data preparation failed; existing source files were not overwritten.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
