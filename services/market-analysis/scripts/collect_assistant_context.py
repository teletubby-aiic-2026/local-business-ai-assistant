"""Collect the chat assistant's location context from the Seoul open-data service.

Usage: python -m scripts.collect_assistant_context [--period 20262]

Writes data/assistant_context/<dataset>_<quarter>.json (ignored by git). Only the
fields the assistant uses are kept. Three of the four services ignore the quarter
in the path and return every quarter (about 36 pages), so every page is read and
the newest quarter not later than the requested one is kept: it can be older than
the sales data, and the file name says which it is. A dataset whose rows do not
add up to the count the service reports is not written. The API key is read from
.env and is never printed: it is part of the request URL, so errors are reported
by type only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
import sys

import httpx

from app.assistant.context import CONTEXT_DIR, DATASETS, SCHEMA
from app.config import load_settings
from app.data_repository import atomic_json_write

BASE = "http://openapi.seoul.go.kr:8088"
PAGE = 1000
KST = timezone(timedelta(hours=9))


class CollectError(RuntimeError):
    """A page that could not be used. The message never contains the key."""


def _page(client: httpx.Client, key: str, service: str, period: str, start: int) -> tuple[list[dict], int]:
    try:
        response = client.get(f"{BASE}/{key}/json/{service}/{start}/{start + PAGE - 1}/{period}")
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise CollectError(f"{service} request failed: {type(error).__name__}") from None
    body = payload.get(service) if isinstance(payload, dict) else None
    if not isinstance(body, dict):
        code = ((payload or {}).get("RESULT") or {}).get("CODE") if isinstance(payload, dict) else None
        raise CollectError(f"{service} returned {code or 'no body'}")
    code = (body.get("RESULT") or {}).get("CODE")
    if code != "INFO-000" or not isinstance(body.get("row"), list):
        raise CollectError(f"{service} returned {code}")
    return body["row"], int(body["list_total_count"])


def collect(client: httpx.Client, key: str, service: str, fields: tuple, period: str) -> dict:
    quarters: dict[str, dict] = {}
    start, total, seen = 1, None, 0
    while total is None or start <= total:
        page, total = _page(client, key, service, period, start)
        if not page:
            raise CollectError(f"{service} returned an empty page")
        for row in page:
            quarter, area = str(row.get("STDR_YYQU_CD") or ""), str(row.get("TRDAR_CD") or "")
            if not quarter or not area:
                raise CollectError(f"{service} returned a row without its quarter or market")
            rows = quarters.setdefault(quarter, {})
            if area in rows:
                raise CollectError(f"{service} returned a market twice in one quarter")
            rows[area] = {field: row.get(field) for field in fields}
            seen += 1
        start += len(page)
    if seen != total:
        raise CollectError(f"{service} rows do not match its count")
    usable = [quarter for quarter in quarters if quarter <= period]
    if not usable:
        raise CollectError(f"{service} has no quarter up to {period}")
    newest = max(usable)
    return {"schema": SCHEMA, "service": service, "period": newest, "row_count": len(quarters[newest]),
            "fetched_at": datetime.now(KST).isoformat(timespec="seconds"), "rows": quarters[newest]}


def latest_period() -> str:
    from app.assistant.ranking import SeoulSalesSource

    return SeoulSalesSource().periods()[-1]


def main(argv=None, *, transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", help="기준 분기, 예: 20262 (생략하면 매출 자료의 최신 분기)")
    args = parser.parse_args(argv)
    load_settings()
    key = os.getenv("SEOUL_OPENAPI_KEY", "").strip()
    if not key:
        print("SEOUL_OPENAPI_KEY가 .env에 없습니다.", file=sys.stderr)
        return 2
    period = args.period or latest_period()
    failed = 0
    with httpx.Client(transport=transport, timeout=60.0) as client:
        for name, (service, fields) in DATASETS.items():
            try:
                document = collect(client, key, service, fields, period)
            except CollectError as error:
                print(f"{name}: 실패 ({error})", file=sys.stderr)
                failed += 1
                continue
            atomic_json_write(CONTEXT_DIR / f"{name}_{document['period']}.json", document)
            print(f"{name}: {document['row_count']}건 저장 ({document['period']})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
