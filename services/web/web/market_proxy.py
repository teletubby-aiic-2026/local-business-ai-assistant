"""상권 분석 화면(#/market)의 프록시 — 비서 화면 서버가 상권 서비스(ic26-market, 127.0.0.1:8766)를 대신 부른다 (5차 회의 11/18).

브라우저는 이 서버의 /api/market/* 만 부른다. 상권 서비스는 서버 안쪽에만 열려 있고, 바깥 주소 이름(Host)으로 오는 요청을 거절하므로
assistant_proxy.py 처럼 Host: 127.0.0.1:8766 을 고정해서 부른다.

| 메서드   | 이 서버                          | 상권 서비스                                   |
|----------|----------------------------------|-----------------------------------------------|
| GET      | /api/market/status               | /health + /api/onboarding/data-status         |
| POST     | /api/market/setup[?force=1]      | 지금 가게의 기본 상권·업종·분기로 맞춤 (profile → analysis-options → analysis-selection) |
| GET·POST | /api/market/profile              | /api/onboarding/profile (업종·위치 바꾸기)    |
| GET      | /api/market/options              | /api/onboarding/options                       |
| GET      | /api/market/analysis-options     | /api/onboarding/analysis-options              |
| GET·POST | /api/market/analysis-selection   | /api/onboarding/analysis-selection            |
| GET      | /api/market/{sales,stores,population,area-context} | /api/onboarding/… (expected_revision) |
| GET      | /api/market/changes?comparison=qoq·yoy | /api/onboarding/changes                |
| GET      | /api/market/comparison-options   | /api/onboarding/comparison-options            |
| GET      | /api/market/comparison?comparison_area_code=… | /api/onboarding/comparison       |
| GET      | /api/market/data-status          | /api/onboarding/data-status                   |
| POST     | /api/market/data-sync            | /api/onboarding/data-sync (서울 열린데이터광장 실시간 확인) |
| GET      | /api/market/cultural-events[?district=] | /api/onboarding/cultural-events (구를 안 주면 가게의 구) |
| GET      | /api/market/map-config           | /api/onboarding/map-config (네이버 지도 브라우저용 공개 ID. client_id·configured 두 칸만 넘김, 11/20) |
| POST     | /api/market/locations/search     | /api/onboarding/locations/search (주소 검색. 검색어는 본문으로, 11/20) |
| POST     | /api/market/locations/area-preview | /api/onboarding/locations/area-preview (동네 참고 위치, 11/20) |

지키는 것
- 세션: 상권 서비스의 세션 값(market_onboarding_session)을 이 서버의 쿠키로 들고 다닌다. 경로는 /api/market 이라 서랍(/api/assistant)과
  따로다 (화면에서 조건을 바꿔도 서랍 대화가 흔들리지 않게). 로그인·로그아웃·가게 바꾸기 때 auth.py 가 이 쿠키를 지운다.
- 장애 격리: 상권 서비스가 꺼지거나 느리거나 이상하면 이 경로들만 503(또는 422·409 같은 그 서비스의 입력 오류)을 준다. 500 은 없다.
  status 는 늘 200.
- 바꾸는 글자: 사람이 읽는 칸(message·label·note·warnings 등)의 분기 코드 '20262' → '2026년 2분기' (assistant_proxy.quarter_words).
  숫자 칸(value·value_text·period 코드)은 그대로 둔다. period 만 있고 period_label 이 없는 곳에는 period_label 을 붙인다.
  지도·주소 경로(RAW_ROUTES)는 바꾸지 않는다: 주소 글('상도로 20241')의 건물 번호가 분기 코드처럼 보여 '2024년 1분기'로 바뀌기 때문.
- 넘기는 쿼리는 경로마다 정한 것만 (나머지는 버림). 본문은 4KB 까지.
- map-config 는 상권 서비스가 무엇을 더 실어 보내도 client_id(모양을 확인한 공개 ID)·configured 두 칸만 화면에 준다.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from shared import store_profiles

import httpx

from .assistant_proxy import (COOKIE_NAME, DEFAULT_HOST, DEFAULT_TIMEOUT, SESSION_SECONDS, SET_COOKIE, STORE_DEFAULTS, TOKEN,
                              MarketClient, MarketError, SetupDefaults, Upstream, _detail, _pick_area, period_words,
                              quarter_words)

log = logging.getLogger("web.market_proxy")

PREFIX = "/api/market"
MAX_BODY = 4096
MAX_CONCURRENT = 6
MESSAGES = {
    "off": "이 서버에서는 상권 분석을 켜 두지 않았어요.",
    "down": "상권 서비스에 연결하지 못했어요. 잠시 뒤 다시 확인해 주세요.",
    "no_data": "공식 상권 자료가 아직 준비되지 않았어요.",
    "error": "상권 분석에 문제가 생겼어요. 잠시 뒤 다시 시도해 주세요.",
    "busy": "요청이 몰려 있어요. 잠시 뒤 다시 해 주세요.",
}
# 경로 → (허용 메서드, 상권 서비스 경로, 넘기는 쿼리 이름, 기다리는 시간(초))
ROUTES: dict[str, tuple[tuple[str, ...], str, tuple[str, ...], float]] = {
    "profile": (("GET", "POST"), "/api/onboarding/profile", (), 20.0),
    "options": (("GET",), "/api/onboarding/options", (), 20.0),
    "analysis-options": (("GET",), "/api/onboarding/analysis-options", (), 30.0),
    "analysis-selection": (("GET", "POST"), "/api/onboarding/analysis-selection", (), 20.0),
    "sales": (("GET",), "/api/onboarding/sales", ("expected_revision",), 30.0),
    "stores": (("GET",), "/api/onboarding/stores", ("expected_revision",), 30.0),
    "population": (("GET",), "/api/onboarding/population", ("expected_revision",), 30.0),
    "area-context": (("GET",), "/api/onboarding/area-context", ("expected_revision",), 20.0),
    "changes": (("GET",), "/api/onboarding/changes", ("comparison", "expected_revision"), 30.0),
    "comparison-options": (("GET",), "/api/onboarding/comparison-options", ("expected_revision",), 30.0),
    "comparison": (("GET",), "/api/onboarding/comparison", ("comparison_area_code", "expected_revision"), 30.0),
    "data-status": (("GET",), "/api/onboarding/data-status", (), 15.0),
    "data-sync": (("POST",), "/api/onboarding/data-sync", (), 60.0),
    "cultural-events": (("GET",), "/api/onboarding/cultural-events", ("district",), 20.0),
    # 지도·위치 (11/20, 6차 회의 ⑥ 상권 분석 지도 · 새 가게 등록). 주소 검색어는 쿼리(20자에서 잘림)가 아니라 본문으로
    "map-config": (("GET",), "/api/onboarding/map-config", (), 10.0),
    "locations/search": (("POST",), "/api/onboarding/locations/search", (), 20.0),
    "locations/area-preview": (("POST",), "/api/onboarding/locations/area-preview", (), 20.0),
}
# 응답을 present() 로 고치지 않는 경로 (주소 글을 그대로)
RAW_ROUTES = frozenset({"map-config", "locations/search", "locations/area-preview"})
MAP_CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
TEXT_KEYS = frozenset({"message", "detail", "label", "note", "notes", "warning", "warnings", "title", "reason", "description",
                       "summary", "text", "hint", "apply_hint", "notice", "sentence", "period_note"})


def present(value: Any, key: str = "") -> Any:
    """사람이 읽는 칸의 분기 코드만 '2026년 2분기'로. 숫자 칸은 그대로. period 만 있으면 period_label 을 붙인다."""
    if isinstance(value, dict):
        out = {k: present(v, k) for k, v in value.items()}
        if isinstance(out.get("period"), str) and "period_label" not in out:
            out["period_label"] = period_words(out["period"])
        return out
    if isinstance(value, list):
        return [present(v, key) for v in value]
    if isinstance(value, str) and key in TEXT_KEYS:
        return quarter_words(value)
    return value


def map_config(data: Any) -> dict:
    """map-config 응답에서 두 칸만: 모양이 맞는 공개 ID 가 있을 때만 configured=True (그 밖의 칸은 버림)."""
    data = data if isinstance(data, dict) else {}
    raw = data.get("client_id")
    client_id = raw.strip() if isinstance(raw, str) else ""
    ok = data.get("configured") is True and bool(MAP_CLIENT_ID.fullmatch(client_id))
    return {"client_id": client_id if ok else "", "configured": ok}


class MarketProxy:
    def __init__(self, client: MarketClient | None, *, config_error: str | None = None):
        self.market = client
        self.config_error = config_error
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT)

    @classmethod
    def from_settings(cls, settings) -> "MarketProxy":
        from urllib.parse import urlsplit
        raw = (getattr(settings, "market_url", "") or "").strip().rstrip("/")
        if raw.lower() in ("", "off", "none", "0", "false"):
            return cls(None)
        parts = urlsplit(raw)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.path not in ("", "/") or parts.query \
                or parts.username or parts.password:
            return cls(None, config_error="상권 서비스 주소(MARKET_URL) 설정이 올바르지 않아요.")
        return cls(MarketClient(raw, getattr(settings, "market_host", DEFAULT_HOST) or DEFAULT_HOST,
                                read_timeout=float(getattr(settings, "market_timeout", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT)))

    def close(self) -> None:
        if self.market is not None:
            self.market.close()

    def _ready(self) -> MarketClient:
        if self.config_error:
            raise MarketError("error", self.config_error)
        if self.market is None:
            raise MarketError("off", MESSAGES["off"])
        return self.market

    def _request(self, method: str, path: str, token: str | None = None, body: dict | None = None, *,
                 read_timeout: float = 20.0) -> Upstream:
        """상권 서비스를 한 번 부른다. 서랍용 MarketClient.request 와 같되, 입력 오류(409·422)는 그 상태 코드로 화면에 넘긴다
        (화면이 '조건이 바뀌었어요 → 다시 불러오기'를 할 수 있게). 연결·시간 초과·5xx·이상한 응답은 503 분류."""
        market = self._ready()
        headers = {"Cookie": f"{COOKIE_NAME}={token}"} if token and TOKEN.fullmatch(token) else {}
        timeout = httpx.Timeout(connect=2.0, read=read_timeout, write=5.0, pool=2.0)
        try:
            res = market.client.request(method, path, json=body, headers=headers, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise MarketError("down", MESSAGES["down"]) from None
        except httpx.ReadTimeout:
            raise MarketError("error", "상권 서비스가 답하는 데 너무 오래 걸렸어요. 잠시 뒤 다시 해 주세요.") from None
        except httpx.HTTPError:
            raise MarketError("error", MESSAGES["error"]) from None
        token_out = None
        for value in res.headers.get_list("set-cookie"):
            found = SET_COOKIE.search(value)
            if found:
                token_out = found.group(1)
        try:
            data = res.json()
        except ValueError:
            data = None
        if 200 <= res.status_code < 300 and data is not None:
            return Upstream(res.status_code, data, token_out)
        detail = _detail(data)
        if res.status_code in (409, 422, 429):
            first = data.get("detail")[0].get("msg") if isinstance(data, dict) and isinstance(data.get("detail"), list) \
                and data["detail"] and isinstance(data["detail"][0], dict) else None
            raise MarketError("conflict" if res.status_code == 409 else "invalid",
                              detail or first or "입력 내용을 확인해 주세요.", 422 if res.status_code == 429 else res.status_code)
        if res.status_code in (400, 403):
            raise MarketError("error", "상권 서비스가 이 서버의 요청을 받아들이지 않았어요. 접속 주소 설정을 확인해 주세요.")
        if res.status_code == 503 and detail and "자료" in detail:
            raise MarketError("no_data", detail)
        raise MarketError("down" if res.status_code in (502, 504) else "error", MESSAGES["error"])

    # 상태 ----------------------------------------------------------------
    def status(self) -> dict:
        try:
            self._request("GET", "/health", read_timeout=3.0)
        except MarketError as exc:
            return {"state": exc.state if exc.state in ("off", "down", "error") else "error", "message": exc.message}
        out: dict[str, Any] = {"state": "ready", "message": None}
        try:
            data = self._request("GET", "/api/onboarding/data-status", read_timeout=5.0).data
            out["data"] = present(data)
            # 상권 서비스 data-status: data_ready(bool)·latest_period·status("ready"|"data_required"|"source_files_missing")
            if isinstance(data, dict) and (data.get("data_ready") is False or data.get("status") == "data_required"):
                out.update(state="no_data", message=MESSAGES["no_data"])
        except MarketError as exc:          # 자료 상태를 못 읽어도 분석은 될 수 있다 (예전 상권 서비스)
            out["data"] = None
            if exc.state == "no_data":
                out.update(state="no_data", message=MESSAGES["no_data"])
        return out

    # 우리 가게 조건으로 ------------------------------------------------------------
    def setup(self, token: str | None, store_id: str, force: bool = False) -> tuple[dict, str | None]:
        wanted: SetupDefaults | None = STORE_DEFAULTS.get(store_id)
        session = {"token": token}

        def call(method, path, body=None, timeout=20.0):
            up = self._request(method, path, session["token"], body, read_timeout=timeout)
            session["token"] = up.token or session["token"]
            return up.data

        state = call("GET", "/api/onboarding/analysis-selection")
        if wanted is None:
            return {"status": "already", "state": "ready", "conditions": self._conditions(state, store_id)}, session["token"]
        if state.get("conditions_confirmed") and not force:
            return {"status": "already", "state": "ready", "conditions": self._conditions(state, store_id)}, session["token"]
        profile = state.get("profile")
        if profile is None or force or not (profile.get("location", {}).get("station_id") == wanted.station_id
                                           and profile.get("industry", {}).get("code") == wanted.industry_code):
            state = call("POST", "/api/onboarding/profile", {
                "location": {"kind": "station", "station_id": wanted.station_id}, "industry_code": wanted.industry_code,
                "business_status": wanted.business_status, "expected_revision": state.get("revision")})
        options = call("GET", "/api/onboarding/analysis-options", timeout=30.0)
        candidates = [c for c in options.get("candidates", []) if not c.get("selection_blocked_reason")]
        chosen = _pick_area(candidates, wanted)
        if chosen is None or not chosen.get("available_periods"):
            return {"status": "unavailable", "state": "no_data", "message": MESSAGES["no_data"], "conditions": None}, session["token"]
        periods = chosen["available_periods"]
        period = wanted.period if wanted.period in periods else max(periods)
        fresh = call("GET", "/api/onboarding/analysis-selection")
        state = call("POST", "/api/onboarding/analysis-selection", {
            "area_code": chosen["area_code"], "period": period, "expected_revision": fresh.get("revision"),
            "expected_catalog_version": options["catalog_version"]})
        return {"status": "ok", "state": "ready", "conditions": self._conditions(state, store_id)}, session["token"]

    @staticmethod
    def _conditions(state: dict, store_id: str) -> dict | None:
        """지금 분석 조건 (화면 조건 바). 조건이 정해지지 않았으면 None."""
        if not isinstance(state, dict) or not state.get("conditions_confirmed"):
            return None
        sel = state.get("analysis_selection") or {}
        profile = state.get("profile") or {}
        industry = profile.get("industry") or {}
        location = profile.get("location") or {}
        wanted = STORE_DEFAULTS.get(store_id)
        out = {"area_code": sel.get("area_code"), "area_name": sel.get("area_name") or sel.get("name"),
               "industry_code": industry.get("code"), "industry_name": industry.get("name"),
               "period": sel.get("period"), "period_label": period_words(sel.get("period_label") or sel.get("period")),
               "location_label": location.get("label") or location.get("name"), "revision": state.get("revision")}
        # 우리 가게 기본 조건인지 (서버가 판단. 화면의 서랍 플래그 이름과 겹치지 않게 home)
        out["home"] = bool(wanted) and (out["area_code"], out["industry_code"], out["period"]) == (
            wanted.area_code, wanted.industry_code, wanted.period)
        return out

    # 그대로 넘기기 ------------------------------------------------------------
    def forward(self, name: str, method: str, token: str | None, params: dict, body: dict | None) -> tuple[Any, str | None]:
        _, path, _, timeout = ROUTES[name]
        if params:
            from urllib.parse import urlencode
            path = f"{path}?{urlencode(params)}"
        up = self._request(method, path, token, body, read_timeout=timeout)
        if name == "map-config":
            return map_config(up.data), up.token or token
        return (up.data if name in RAW_ROUTES else present(up.data)), up.token or token


# ── 라우터 ─────────────────────────────────────────────────────────────
def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"


def _token(request: Request) -> str | None:
    value = request.cookies.get(COOKIE_NAME)
    return value if value and TOKEN.fullmatch(value) else None


def _respond(data: Any, status: int, token: str | None, secure: bool) -> JSONResponse:
    out = JSONResponse(data, status_code=status)
    out.headers["Cache-Control"] = "no-store"
    if token and TOKEN.fullmatch(token):
        out.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True, samesite="lax", secure=secure, path=PREFIX)
    return out


def _fail(exc: MarketError, token: str | None, secure: bool) -> JSONResponse:
    status = exc.http if exc.http in (409, 422) else 503      # 입력 오류만 그대로, 나머지는 모두 503 (500 없음)
    return _respond({"error": {"message": exc.message, "state": exc.state}}, status, token, secure)


def create_market_router(proxy: MarketProxy, store_of: Callable[[Request], str] | None = None) -> APIRouter:
    """store_of(요청) 은 그 요청의 가게 (로그인한 사장님이 고른 가게, 없으면 기본 가게)."""
    store_of = store_of or (lambda request: getattr(request.state, "store_id", None) or store_profiles.DEFAULT_STORE_ID)
    router = APIRouter(prefix=PREFIX, tags=["market-proxy"])

    def guarded(request: Request, work: Callable[[str | None], tuple[Any, str | None]]) -> JSONResponse:
        token, secure = _token(request), _secure(request)
        if not proxy.slots.acquire(timeout=1.0):
            return _respond({"error": {"message": MESSAGES["busy"], "state": "error"}}, 503, token, secure)
        try:
            data, token_out = work(token)
            return _respond(data, 200, token_out, secure)
        except MarketError as exc:
            return _fail(exc, token, secure)
        except Exception as exc:            # 우리 쪽 버그. 다른 화면은 그대로 두고 이 경로에만 알린다
            log.exception("상권 분석 프록시 예상 못한 오류 (%s)", exc.__class__.__name__)
            return _fail(MarketError("error", MESSAGES["error"]), token, secure)
        finally:
            proxy.slots.release()

    @router.get("/status")
    def status(request: Request):
        try:
            data = proxy.status()
        except Exception as exc:            # status 는 어떤 경우에도 200
            log.exception("상권 분석 status 오류 (%s)", exc.__class__.__name__)
            data = {"state": "error", "message": MESSAGES["error"]}
        bundle = store_profiles.get(store_of(request))
        data["store"] = bundle.public() if bundle else None
        return _respond(data, 200, None, False)

    @router.post("/setup")
    def setup(request: Request, force: bool = False):
        return guarded(request, lambda token: proxy.setup(token, store_of(request), force))

    async def relay(name: str, request: Request) -> JSONResponse:
        methods, _, keys, _ = ROUTES[name]
        if request.method not in methods:
            return _respond({"error": {"message": "지원하지 않는 요청이에요.", "state": "invalid"}}, 405, None, False)
        params = {k: request.query_params[k][:20] for k in keys if k in request.query_params}
        if name == "cultural-events" and not params.get("district"):
            bundle = store_profiles.get(store_of(request))
            params["district"] = bundle.district_name if bundle else "동작구"
        body = None
        if request.method == "POST":
            raw = await request.body()
            if len(raw) > MAX_BODY:
                return _respond({"error": {"message": "요청 내용이 너무 커요.", "state": "invalid"}}, 413, None, False)
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                return _respond({"error": {"message": "본문이 JSON 이 아니에요.", "state": "invalid"}}, 422, None, False)
            if not isinstance(body, dict):
                return _respond({"error": {"message": "입력 내용을 확인해 주세요.", "state": "invalid"}}, 422, None, False)
        return await run_in_threadpool(guarded, request, lambda token: proxy.forward(name, request.method, token, params, body))

    def make(name: str):
        # 경로마다의 엔드포인트. 이름을 기본 인자로 넘기면 FastAPI 가 쿼리 칸으로 읽어서, 닫힌 함수로 만든다
        async def endpoint(request: Request) -> JSONResponse:
            return await relay(name, request)
        return endpoint

    for name in ROUTES:
        # 허용하지 않는 메서드도 relay 가 405 를 주게 GET·POST 모두 받는다
        router.add_api_route(f"/{name}", make(name), methods=["GET", "POST"], name=f"market_{name}")
    return router
