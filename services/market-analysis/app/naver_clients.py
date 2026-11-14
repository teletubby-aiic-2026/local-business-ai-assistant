"""Server-side NAVER Maps client with a fixed destination and safe diagnostics.

The application calls config.load_settings() before constructing these clients.
Credentials are never returned, logged, placed in URLs, or stored in cache keys.
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import json
import math
import os
import re
from threading import Lock
from typing import Any

import httpx



MAPS_URL = "https://maps.apigw.ntruss.com/map-geocode/v2/geocode"
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_ERROR_RESPONSE_BYTES = 16 * 1024
_ERROR_READ_CHUNK_BYTES = 1024
MAX_CACHE_ENTRIES = 128
MAX_RATE_LIMIT_VALUE = 1_000_000_000
MAX_RATE_LIMIT_WAIT_SECONDS = 86400
_RATE_COUNT_KEYS = frozenset({'limit_requests', 'limit_tokens', 'remaining_requests', 'remaining_tokens'})
_RATE_WAIT_KEYS = frozenset({'reset_requests_seconds', 'reset_tokens_seconds', 'retry_after_seconds'})


def _safe_rate_limit_metadata(values: dict | None) -> dict[str, int | float]:
    """Only bounded numeric diagnostic fields may cross the client boundary."""
    if not isinstance(values, dict):
        return {}
    safe = {}
    for key, value in values.items():
        if key in _RATE_COUNT_KEYS and type(value) is int and 0 <= value <= MAX_RATE_LIMIT_VALUE:
            safe[key] = value
        elif (key in _RATE_WAIT_KEYS and type(value) in (int, float)
              and 0 <= value <= MAX_RATE_LIMIT_WAIT_SECONDS and math.isfinite(value)
              and (key != 'retry_after_seconds' or type(value) is int)):
            safe[key] = value
    return safe


def _rate_limit_headers(headers: httpx.Headers) -> dict[str, int | float]:
    """Parse a fixed header allowlist without retaining any upstream text."""
    values = {}
    for key in _RATE_COUNT_KEYS:
        raw = headers.get('x-ratelimit-' + key.replace('_', '-'), '').strip()
        if re.fullmatch(r'[0-9]{1,10}', raw):
            values[key] = int(raw)
    for kind in ('requests', 'tokens'):
        raw = headers.get('x-ratelimit-reset-' + kind, '').strip()
        match = re.fullmatch(r'([0-9]{1,9}(?:\.[0-9]{1,3})?)(ms|s)', raw)
        if match:
            value = float(match[1]) / (1000 if match[2] == 'ms' else 1)
            values['reset_' + kind + '_seconds'] = value
    raw = headers.get('retry-after', '').strip()
    if re.fullmatch(r'[0-9]{1,10}', raw):
        values['retry_after_seconds'] = int(raw)
    return _safe_rate_limit_metadata(values)


def _safe_provider_code(value: Any) -> str | None:
    """Provider diagnostics contain only an exact five-digit ASCII code."""
    if type(value) is int and 10000 <= value <= 99999:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"[0-9]{5}", value):
        return value
    return None


class NaverApiError(RuntimeError):
    """Contains only our own diagnostic text, never an upstream body or URL."""

    def __init__(self, message: str, http_status: int | None = None,
                 *, rate_limit: dict | None = None, code: str | None = None,
                 provider_code: str | int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.rate_limit = _safe_rate_limit_metadata(rate_limit)
        self.code = code if code in {'rate_limited', 'timeout'} else ('rate_limited' if http_status == 429 else None)
        self.provider_code = _safe_provider_code(provider_code)


def _credential(name: str, explicit: str | None) -> str:
    value = os.getenv(name, "") if explicit is None else explicit
    if not isinstance(value, str):
        raise ValueError("인증정보는 문자열이어야 합니다.")
    return value.strip()


def _reject_constant(_: str) -> None:
    raise ValueError("Invalid JSON number.")


def _unique_error_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate error field")
        result[key] = value
    return result


def _error_provider_code(response: httpx.Response) -> str | None:
    """Best-effort bounded diagnostics; never retain upstream prose.

    Accept at most 16 KiB of decoded JSON, with one bounded lookahead chunk to
    detect overflow. Only three fixed code paths are considered. Truncation,
    ambiguity and any read/parse failure leave the original HTTP error intact.
    """
    raw = bytearray()
    try:
        chunks = response.iter_bytes(chunk_size=_ERROR_READ_CHUNK_BYTES)
        while True:
            try:
                chunk = next(chunks)
            except StopIteration:
                break
            if len(raw) + len(chunk) > MAX_ERROR_RESPONSE_BYTES:
                return None
            raw.extend(chunk)
        body = json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant,
                          object_pairs_hook=_unique_error_object)
        if not isinstance(body, dict):
            return None
        values = [body["code"]] if "code" in body else []
        for key in ("status", "error"):
            container = body.get(key)
            if isinstance(container, dict) and "code" in container:
                values.append(container["code"])
        codes = [_safe_provider_code(value) for value in values]
        return codes[0] if codes and None not in codes and len(set(codes)) == 1 else None
    except Exception:
        # This optional diagnostic must not replace the existing HTTP failure,
        # attach a secret-bearing exception or trigger another provider call.
        return None


def _request_json(
    method: str, url: str, headers: dict, *, timeout: int,
    params: dict | None = None, payload: dict | None = None,
    transport: httpx.BaseTransport | None = None,
    rate_limit: dict | None = None,
) -> dict:
    safe_error = None
    status = None
    raw = bytearray()
    safe_limits = {}
    error_code = None
    provider_code = None
    # No redirects, environment proxy configuration, or automatic retries.
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False,
                          transport=transport) as client:
            with client.stream(method, url, headers=headers, params=params, json=payload) as response:
                status = response.status_code
                safe_limits = _rate_limit_headers(response.headers)
                if rate_limit is not None:
                    rate_limit.update(safe_limits)
                if not 200 <= status < 300:
                    safe_error = "NAVER API 요청이 거절되었습니다. 인증정보·권한·이용 한도를 확인하세요."
                    provider_code = _error_provider_code(response)
                else:
                    for chunk in response.iter_bytes():
                        if len(raw) + len(chunk) > MAX_RESPONSE_BYTES:
                            safe_error = "NAVER API 응답이 허용 크기를 초과했습니다."
                            break
                        raw.extend(chunk)
    except httpx.TimeoutException:
        safe_error = "NAVER API 응답 대기 시간이 초과되었습니다."
        error_code = "timeout"
    except (httpx.HTTPError, OSError, ValueError):
        safe_error = "NAVER API 연결에 실패했거나 응답 시간이 초과되었습니다."
    # Raise outside except: even exception context cannot retain a secret-bearing error.
    if safe_error:
        raise NaverApiError(safe_error, status,
                           rate_limit=safe_limits,code=error_code,provider_code=provider_code)
    result = None
    invalid = False
    try:
        result = json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError):
        invalid = True
    if invalid or not isinstance(result, dict):
        raise NaverApiError("NAVER API 응답 형식을 확인할 수 없습니다.", status, rate_limit=safe_limits)
    if "error" in result:
        raise NaverApiError("NAVER API가 오류를 반환했습니다. 인증정보·권한·이용 한도를 확인하세요.", status, rate_limit=safe_limits)
    return result


class MapsClient:
    """Geocoding with a process-local, bounded LRU cache per client instance."""

    def __init__(self, client_id: str | None = None, client_secret: str | None = None,
                 *, transport: httpx.BaseTransport | None = None) -> None:
        self._client_id = _credential("NAVER_MAPS_CLIENT_ID", client_id)
        self._client_secret = _credential("NAVER_MAPS_CLIENT_SECRET", client_secret)
        self._transport = transport
        self._cache: OrderedDict[str, list[dict]] = OrderedDict()
        self._lock = Lock()

    def __repr__(self) -> str:
        return "MapsClient(credentials=redacted)"

    def geocode(self, address: str) -> list[dict]:
        if not isinstance(address, str) or not 1 <= len(address.strip()) <= 200:
            raise ValueError("주소는 1~200자로 입력하세요.")
        address = address.strip()
        if any(ord(char) < 32 for char in address):
            raise ValueError("주소에는 제어 문자를 사용할 수 없습니다.")
        if not self._client_id or not self._client_secret:
            raise NaverApiError("NAVER Maps 인증정보가 설정되지 않았습니다.")
        with self._lock:
            if address in self._cache:
                self._cache.move_to_end(address)
                return deepcopy(self._cache[address])
        body = _request_json(
            "GET", MAPS_URL,
            {"x-ncp-apigw-api-key-id": self._client_id,
             "x-ncp-apigw-api-key": self._client_secret, "Accept": "application/json"},
            params={"query": address, "count": 10}, timeout=10, transport=self._transport,
        )
        rows = body.get("addresses")
        if body.get("status") != "OK" or not isinstance(rows, list) or len(rows) > 10:
            raise NaverApiError("NAVER Maps 주소 응답을 확인할 수 없습니다.")
        results = []
        invalid = False
        for row in rows:
            try:
                if not isinstance(row, dict) or isinstance(row.get("x"), bool) or isinstance(row.get("y"), bool):
                    invalid = True
                    break
                longitude, latitude = float(row["x"]), float(row["y"])
                road, jibun = row.get("roadAddress", ""), row.get("jibunAddress", "")
                if not (math.isfinite(longitude) and -180 <= longitude <= 180
                        and math.isfinite(latitude) and -90 <= latitude <= 90
                        and isinstance(road, str) and isinstance(jibun, str)
                        and len(road) <= 500 and len(jibun) <= 500):
                    invalid = True
                    break
                results.append({"road_address": road, "jibun_address": jibun,
                                "longitude": longitude, "latitude": latitude})
            except (KeyError, TypeError, ValueError, OverflowError):
                invalid = True
                break
        if invalid:
            raise NaverApiError("NAVER Maps 좌표 응답을 확인할 수 없습니다.")
        with self._lock:
            self._cache[address] = deepcopy(results)
            self._cache.move_to_end(address)
            while len(self._cache) > MAX_CACHE_ENTRIES:
                self._cache.popitem(last=False)
        return results
