"""Bounded Seoul OpenAPI collection. Raw responses are not analysis releases.

This module validates the response envelope only. It does not normalize domain
values, infer a latest quarter, or approve the data for analysis.
"""

import json
import os
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


BASE_URL = "http://openapi.seoul.go.kr:8088"
TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
SERVICES = MappingProxyType({
    "sales": "VwsmTrdarSelngQq",
    "stores": "VwsmTrdarStorQq",
    "population": "VwsmTrdarFlpopQq",
    "areas": "TbgisTrdarRelm",
})


class SeoulApiError(RuntimeError):
    """Safe diagnostic: never contains a request URL or upstream message."""


@dataclass(frozen=True)
class ParsedResponse:
    rows: list[dict[str, Any]] = field(repr=False)
    total_count: int
    result_code: str


@dataclass(frozen=True)
class SeoulPage:
    dataset: str
    service: str
    period: str | None
    start_index: int
    end_index: int
    source_url: str
    sample_only: bool
    parsed: ParsedResponse
    payload: dict[str, Any] = field(repr=False)


def validate_query(dataset: str, period: str | None, start: int, count: int) -> None:
    if dataset not in SERVICES:
        raise ValueError("Dataset must be sales, stores, population, or areas.")
    if period is not None and (
        not isinstance(period, str) or re.fullmatch(r"20\d{2}[1-4]", period) is None
    ):
        raise ValueError("Period must be YYYYQ, with a quarter from 1 to 4.")
    if dataset == "areas" and period is not None:
        raise ValueError("The areas API does not accept a period parameter.")
    if type(start) is not int or start < 1:
        raise ValueError("Start index must be a positive integer.")
    if type(count) is not int or not 1 <= count <= 1000:
        raise ValueError("Page size must be an integer from 1 to 1000.")


def _result_code(result: Any) -> str:
    if not isinstance(result, dict):
        raise SeoulApiError("Invalid API response: missing RESULT object.")
    code = result.get("CODE")
    if not isinstance(code, str) or re.fullmatch(r"[A-Z]+-\d{3}", code) is None:
        raise SeoulApiError("Invalid API response: invalid result code.")
    return code


def parse_seoul_response(payload: Any, service: str) -> ParsedResponse:
    """Validate an API envelope without changing the original payload."""
    if service not in SERVICES.values():
        raise ValueError("Unsupported Seoul API service.")
    if not isinstance(payload, dict):
        raise SeoulApiError("Invalid API response: expected a JSON object.")
    # Seoul returns errors and no-data results outside the service envelope.
    if "RESULT" in payload:
        code = _result_code(payload["RESULT"])
        if service in payload:
            raise SeoulApiError("Invalid API response: conflicting result envelopes.")
        if code == "INFO-200":
            return ParsedResponse([], 0, code)
        if code != "INFO-000":
            raise SeoulApiError(f"Seoul API rejected the request ({code}).")
        raise SeoulApiError("Invalid API response: missing service envelope.")

    body = payload.get(service)
    if not isinstance(body, dict):
        raise SeoulApiError("Invalid API response: missing service envelope.")
    code = _result_code(body.get("RESULT"))
    if code == "INFO-200":
        if body.get("row", []) != [] or body.get("list_total_count", 0) != 0:
            raise SeoulApiError("Invalid API response: inconsistent no-data result.")
        return ParsedResponse([], 0, code)
    if code != "INFO-000":
        raise SeoulApiError(f"Seoul API rejected the request ({code}).")

    total = body.get("list_total_count")
    rows = body.get("row")
    if type(total) is not int or total < 0:
        raise SeoulApiError("Invalid API response: invalid total count.")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise SeoulApiError("Invalid API response: row must be a list of objects.")
    if len(rows) > total:
        raise SeoulApiError("Invalid API response: row count exceeds total count.")
    return ParsedResponse(rows, total, code)


def _reject_nonfinite(_: str) -> None:
    raise ValueError("Non-finite JSON number.")


class SeoulClient:
    """Read-only client. Empty credentials select the public five-row sample."""

    def __init__(self, api_key: str | None = None) -> None:
        value = os.getenv("SEOUL_OPENAPI_KEY", "") if api_key is None else api_key
        if not isinstance(value, str):
            raise ValueError("API key must be a string.")
        value = value.strip()
        self.sample_only = not value or value == "sample"
        self._api_key = "sample" if self.sample_only else value

    def __repr__(self) -> str:
        return f"SeoulClient(sample_only={self.sample_only})"

    def fetch_page(
        self, dataset: str, period: str | None = None, start: int = 1, count: int = 5,
        *, area_code: str | None = None,
    ) -> SeoulPage:
        validate_query(dataset, period, start, count)
        if area_code is not None and (
            dataset != "stores" or period is None or not isinstance(area_code, str)
            or re.fullmatch(r"[0-9]{7}", area_code) is None
        ):
            raise ValueError("Area filtering requires the stores API, a period, and a 7-digit area code.")
        end = start + count - 1
        if self.sample_only and end > 5:
            raise ValueError("Sample-only mode permits indices 1 through 5 only.")
        service = SERVICES[dataset]
        suffix = f"/json/{service}/{start}/{end}/"
        if period is not None:
            suffix += f"{period}/"
        if area_code is not None:
            suffix += f"{area_code}/"
        request_url = f"{BASE_URL}/{quote(self._api_key, safe='')}{suffix}"
        # Never derive user-visible diagnostics from the credential-bearing URL.
        source_url = f"{BASE_URL}/REDACTED{suffix}"
        safe_error = None
        raw = b""
        try:
            request = Request(request_url, headers={"Accept": "application/json"})
            with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            status = exc.code if type(exc.code) is int else "unknown"
            safe_error = f"Seoul API HTTP request failed (status {status})."
            # An unclosed HTTPError can later emit a ResourceWarning containing
            # its original message, even after our safe exception is handled.
            try:
                exc.close()
            except (OSError, ValueError):
                pass
        except (URLError, OSError, ValueError):
            safe_error = "Seoul API request failed or timed out."
        # Raise outside the except block: no credential-bearing exception context.
        if safe_error is not None:
            raise SeoulApiError(safe_error)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise SeoulApiError("Seoul API response exceeded the collection size limit.")

        payload = None
        invalid_json = False
        try:
            payload = json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_nonfinite)
        except (UnicodeError, ValueError, RecursionError):
            invalid_json = True
        if invalid_json:
            raise SeoulApiError("Seoul API returned invalid JSON.")
        parsed = parse_seoul_response(payload, service)
        if len(parsed.rows) > count:
            raise SeoulApiError("Invalid API response: returned more rows than requested.")
        return SeoulPage(
            dataset, service, period, start, end, source_url,
            self.sample_only, parsed, payload,
        )
