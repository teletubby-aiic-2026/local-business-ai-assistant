"""Call the existing /api/onboarding endpoint functions from the assistant.

The assistant must not duplicate PR #12's location validation, revision checks
or data availability rules. Those live inside ``create_onboarding_router`` as
endpoint functions, so the bridge looks them up on that router and calls them
with the caller's own request (same session cookie). Results come back as the
JSON the browser would have received; HTTP errors stay HTTPException.
"""
from __future__ import annotations

import json

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute

from app.onboarding import COOKIE_NAME, AnalysisSelectionInput, ProfileInput, ProfileLocation

PREFIX = "/api/onboarding"


def endpoint_table(router) -> dict[tuple[str, str], object]:
    table = {}
    for route in router.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                table[(method, route.path)] = route.endpoint
    return table


def request_with_session(request: Request, token: str) -> Request:
    """Return a request whose cookie is this session's token.

    A first visit has no cookie yet; without this every bridged call would
    create a different anonymous session. The query string is always removed
    because the analysis endpoints refuse any parameter they did not expect.
    """
    scope = dict(request.scope)
    headers = [(key, value) for key, value in scope.get("headers", []) if key.lower() != b"cookie"]
    headers.append((b"cookie", f"{COOKIE_NAME}={token}".encode("latin-1")))
    scope["headers"] = headers
    scope["query_string"] = b""
    return Request(scope, request.receive)


def _json(response):
    return json.loads(response.body)


class OnboardingBridge:
    def __init__(self, table: dict, request: Request):
        self._table = table
        self._request = request

    def _call(self, method, path, *args, **kwargs):
        endpoint = self._table.get((method, PREFIX + path))
        if endpoint is None:
            raise RuntimeError(f"onboarding endpoint {method} {path} is not mounted")
        return _json(endpoint(*args, request=self._request, **kwargs))

    # Conditions ------------------------------------------------------------
    def state(self) -> dict:
        return self._call("GET", "/analysis-selection")

    def save_profile(self, location: dict | None, industry_code: str, business_status: str,
                     expected_revision: int | None) -> dict:
        body = ProfileInput(location=ProfileLocation(**location) if location is not None else None,
                            industry_code=industry_code, business_status=business_status,
                            expected_revision=expected_revision)
        return self._call("POST", "/profile", body)

    def analysis_options(self) -> dict:
        return self._call("GET", "/analysis-options")

    def save_selection(self, area_code: str, period: str, expected_revision: int, catalog_version: str) -> dict:
        body = AnalysisSelectionInput(area_code=area_code, period=period, expected_revision=expected_revision,
                                      expected_catalog_version=catalog_version)
        return self._call("POST", "/analysis-selection", body)

    # Analyses (B2~B6) --------------------------------------------------------
    def sales(self, revision: int) -> dict:
        return self._call("GET", "/sales", expected_revision=revision)

    def stores(self, revision: int) -> dict:
        return self._call("GET", "/stores", expected_revision=revision)

    def population(self, revision: int) -> dict:
        return self._call("GET", "/population", expected_revision=revision)

    def changes(self, comparison: str, revision: int) -> dict:
        return self._call("GET", "/changes", comparison=comparison, expected_revision=revision)

    def comparison_options(self, revision: int) -> dict:
        return self._call("GET", "/comparison-options", expected_revision=revision)

    def comparison(self, area_code: str, revision: int) -> dict:
        return self._call("GET", "/comparison", comparison_area_code=area_code, expected_revision=revision)


def error_message(error: Exception) -> str:
    if isinstance(error, HTTPException):
        return str(error.detail)
    return "자료를 불러오지 못했습니다."
