"""상권 비서 프록시 — 오른쪽 "AI에게 묻기" 서랍이 상권 서비스(ic26-market, 127.0.0.1:8766)와 대화하는 길.

브라우저는 이 서버(같은 출처)의 /api/assistant/* 만 부른다. 이 서버가 상권 서비스를 대신 불러 준다.

| 메서드 | 경로                            | 하는 일 |
|--------|---------------------------------|---------|
| GET    | /api/assistant/status           | 상권 비서를 쓸 수 있는지. 항상 200 (ready·off·down·disabled·no_data·error) |
| POST   | /api/assistant/setup            | 우리 가게(온기한식)의 분석 조건(장승배기역·한식음식점·최신 분기)을 자동으로 맞춘다. 항상 200.
|        |                                 | 이미 조건이 있으면 그대로 둔다. `?force=1` 이면 다른 곳을 보고 있어도 우리 가게 조건으로 되돌린다 |
| POST   | /api/assistant/messages         | 질문 1개 → 답, 근거 카드, 선택지 (상권 서비스의 같은 경로) |
| POST   | /api/assistant/actions          | 선택지 카드를 눌렀을 때 (같은 경로) |
| GET    | /api/assistant/conversation     | 이 세션의 대화와 분석 조건 (같은 경로) |
| DELETE | /api/assistant/conversation     | 대화 지우기 (같은 경로) |

상권 서비스가 요구하는 것 (services/market-analysis/app/intake_api.py, assistant/router.py, onboarding.py)
- 세션 쿠키 `market_onboarding_session` (43자). 대화와 분석 조건이 이 세션에 붙는다. 브라우저의 쿠키를 그대로 넘기고, 상권 서비스가
  새로 준 값은 브라우저에 다시 심는다 (이 서버 주소에서만, 경로는 /api/assistant). 이 서버의 방문자 쿠키(visitor_id)는 넘기지 않는다.
- `Host: 127.0.0.1:8766`. 상권 서비스는 바깥 주소 이름(로드 밸런서 도메인 등)의 Host 와 Origin 을 막는다 (Host 가 127.0.0.1·localhost 가 아니면 400,
  Origin 은 127.0.0.1:8766 만 허용). 그래서 Host 를 늘 이 값으로 고정하고 Origin 은 아예 넘기지 않는다.
- 본문 형식은 상권 서비스가 엄격하게 검사한다 (모르는 칸이 있으면 422). 여기서도 같은 규칙으로 먼저 검사한다.

상권 서비스가 꺼져 있거나 공식 자료가 아직 없거나 챗봇이 꺼져 있어도 이 서버의 다른 화면은 아무 영향이 없다. 모든 실패는
  {"error": {"message": "한국어 안내", "state": "down|error|disabled|no_data|invalid"}} 로 서랍에만 전해진다 (HTTP 503, 입력 문제는 422).
이 모듈은 어떤 경우에도 500 을 내지 않는다.

설정 (환경 변수)
  MARKET_URL          상권 서비스 주소. 기본 http://127.0.0.1:8766. off 로 쓰면 이 서버에서는 상권 비서를 끈다
  MARKET_HOST         상권 서비스에 보낼 Host 값. 기본 127.0.0.1:8766 (바꿀 일이 거의 없음)
  MARKET_TIMEOUT_SEC  질문 1개를 기다리는 최대 시간(초). 기본 75 (실제 AI 호출이 들어 있음. 로드 밸런서 제한 120초보다 짧게)
"""
from __future__ import annotations

import http.cookiejar
import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

log = logging.getLogger("web.assistant")

COOKIE_NAME = "market_onboarding_session"      # services/market-analysis/app/onboarding.py 의 COOKIE_NAME (시험이 같은지 확인)
SESSION_SECONDS = 30 * 86400                   # 상권 서비스의 SESSION_TTL 과 같은 30일
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")       # 상권 서비스가 만드는 세션 값의 모양. 다른 모양은 넘기지 않는다
SET_COOKIE = re.compile(rf"(?:^|[,;\s]){COOKIE_NAME}=([A-Za-z0-9_-]{{43}})")

DEFAULT_URL = "http://127.0.0.1:8766"
DEFAULT_HOST = "127.0.0.1:8766"
DEFAULT_TIMEOUT = 75.0
MAX_BODY = 4096                                # 선택지 본문은 작다. 이보다 크면 상권 서비스에 보내지 않는다
MAX_CONCURRENT = 8                             # 상권 서비스를 동시에 기다리는 요청 수 (서버 스레드를 다 잡아먹지 않게)

STATES = ("ready", "off", "down", "disabled", "no_data", "error")
MESSAGES = {
    "off": "이 서버에서는 상권 비서를 켜 두지 않았어요.",
    "down": "상권 서비스에 연결하지 못했어요. 잠시 뒤 다시 확인해 주세요.",
    "disabled": "상권 서비스는 켜져 있지만 상권 비서(챗봇)가 꺼져 있어요.",
    "no_data": "공식 상권 자료가 아직 준비되지 않았어요. 자료가 들어오면 바로 쓸 수 있어요.",
    "error": "상권 비서에 문제가 생겼어요. 잠시 뒤 다시 시도해 주세요.",
}
SLOW_MESSAGE = "상권 비서가 답하는 데 너무 오래 걸렸어요. 잠시 뒤 다시 물어봐 주세요."
BUSY_MESSAGE = "질문이 몰려 있어요. 잠시 뒤 다시 물어봐 주세요."
HOST_MESSAGE = "상권 서비스가 이 서버의 요청을 받아들이지 않았어요. 접속 주소 설정을 확인해 주세요."
NO_DATA_DETAIL = "상권 자료를 불러오지 못했습니다"    # 공식 자료가 없을 때 상권 서비스가 주는 문장의 앞부분


class MarketError(Exception):
    """상권 서비스와의 문제. state 는 서랍이 그대로 보여 주는 분류, http 는 이 서버가 돌려줄 상태 코드."""

    def __init__(self, state: str, message: str, http: int = 503):
        super().__init__(message)
        self.state, self.message, self.http = state, message, http


@dataclass(frozen=True)
class SetupDefaults:
    """우리 가게의 분석 조건. 상권 서비스의 위치·업종·상권·분기 코드와 같다 (onboarding_stations.json, 업종 표, 상권 지표)."""
    station_id: str
    industry_code: str
    area_code: str
    period: str
    business_status: str
    label: str


STORE_DEFAULTS: dict[str, SetupDefaults] = {
    "store_ongi": SetupDefaults(
        station_id="kric-e12f817979cd-S1107-0740",      # 장승배기역 (7호선)
        industry_code="CS100001",                       # 한식음식점
        area_code="3110826",                            # 장승배기역 4번 상권 (data/scenario/snapshot_2026Q2.json 의 상권)
        period="20262",                                 # 2026년 2분기
        business_status="operating",
        label="온기한식 · 장승배기역 · 한식음식점"),
}


# ── 입력 검사 (상권 서비스 assistant/router.py 의 MessageInput·ActionInput 과 같은 규칙) ─────────
class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MessageIn(_In):
    text: str = Field(min_length=1, max_length=1000)
    client_message_id: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")

    @field_validator("text")
    @classmethod
    def clean(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("메시지를 입력해 주세요.")
        return value


class ActionIn(_In):
    type: Literal["location", "industry", "area", "comparison_area", "handoff"]
    kind: str | None = Field(default=None, max_length=20)
    station_id: str | None = Field(default=None, max_length=160)
    district_code: str | None = Field(default=None, pattern=r"^\d{5}$")
    neighborhood_code: str | None = Field(default=None, pattern=r"^\d{8}$")
    industry_code: str | None = Field(default=None, pattern=r"^CS\d{6}$")
    area_code: str | None = Field(default=None, pattern=r"^\d{7}$")
    period: str | None = Field(default=None, pattern=r"^\d{4}[1-4]$")
    domain: Literal["marketing", "customer"] | None = None


# ── 상권 서비스 호출 ─────────────────────────────────────────────────
@dataclass
class Upstream:
    status: int
    data: Any
    token: str | None      # 상권 서비스가 응답에 새로 실어 준 세션 값 (없으면 None)


class MarketClient:
    def __init__(self, base_url: str, host_header: str = DEFAULT_HOST, *, read_timeout: float = DEFAULT_TIMEOUT,
                 transport: httpx.BaseTransport | None = None):
        self.read_timeout = read_timeout
        self.client = httpx.Client(
            base_url=base_url, transport=transport, follow_redirects=False,
            headers={"Host": host_header, "Accept": "application/json"},
            timeout=httpx.Timeout(connect=2.0, read=read_timeout, write=5.0, pool=2.0))
        # httpx 는 받은 Set-Cookie 를 클라이언트 안에 쌓아 두었다가 다음 요청에 자동으로 실어 보낸다. 이 클라이언트는 모든 방문자가
        # 같이 쓰므로, 그대로 두면 쿠키가 없는 방문자가 앞사람의 상권 세션(대화·조건)을 물려받는다. 쿠키 보관을 아예 막고
        # 세션 값은 요청마다 우리가 직접 실어 보낸다.
        self.client.cookies.jar.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    def close(self) -> None:
        self.client.close()

    def request(self, method: str, path: str, token: str | None = None, body: dict | None = None, *,
                read_timeout: float | None = None) -> Upstream:
        """한 번 부른다. 성공(2xx)이면 Upstream, 아니면 MarketError. 어떤 오류도 그대로 새어 나가지 않는다."""
        headers = {"Cookie": f"{COOKIE_NAME}={token}"} if token and TOKEN.fullmatch(token) else {}
        timeout = httpx.Timeout(connect=2.0, read=read_timeout or self.read_timeout, write=5.0, pool=2.0)
        try:
            response = self.client.request(method, path, json=body, headers=headers, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            log.warning("상권 서비스에 연결하지 못함 (%s %s: %s)", method, path, exc.__class__.__name__)
            raise MarketError("down", MESSAGES["down"]) from None
        except httpx.ReadTimeout:
            log.warning("상권 서비스가 제한 시간 안에 답하지 않음 (%s %s)", method, path)
            raise MarketError("error", SLOW_MESSAGE) from None
        except httpx.HTTPError as exc:
            log.warning("상권 서비스 호출 오류 (%s %s: %s)", method, path, exc.__class__.__name__)
            raise MarketError("error", MESSAGES["error"]) from None
        token_out = None
        for value in response.headers.get_list("set-cookie"):
            found = SET_COOKIE.search(value)
            if found:
                token_out = found.group(1)
        try:
            data = response.json()
        except ValueError:
            data = None
        if 200 <= response.status_code < 300:
            if data is None:
                log.warning("상권 서비스가 JSON 이 아닌 응답을 줌 (%s %s)", method, path)
                raise MarketError("error", MESSAGES["error"])
            return Upstream(response.status_code, data, token_out)
        raise _upstream_error(response.status_code, data, path)


def _detail(data: Any) -> str | None:
    detail = data.get("detail") if isinstance(data, dict) else None
    return detail if isinstance(detail, str) and detail.strip() else None


def _upstream_error(status: int, data: Any, path: str) -> MarketError:
    """상권 서비스의 실패 응답을 서랍이 보여 줄 분류로 바꾼다."""
    detail = _detail(data)
    log.warning("상권 서비스 오류 응답 %s (%s)", status, path)
    if status == 404 and path.startswith("/api/assistant"):
        return MarketError("disabled", MESSAGES["disabled"])           # ASSISTANT_ENABLED 가 꺼져 있어 경로가 없다
    if status in (400, 403):
        return MarketError("error", HOST_MESSAGE)                      # Host·Origin 검사에 걸림
    if status == 422:
        return MarketError("invalid", detail or "입력 내용을 확인해 주세요.", 422)
    if status == 503 and detail and detail.startswith(NO_DATA_DETAIL):
        return MarketError("no_data", MESSAGES["no_data"])
    if status in (502, 504):
        return MarketError("down", MESSAGES["down"])
    return MarketError("error", detail if status == 503 and detail else MESSAGES["error"])


# ── 프록시 ─────────────────────────────────────────────────────────────
class AssistantProxy:
    def __init__(self, client: MarketClient | None, *, store_id: str = "store_ongi", config_error: str | None = None):
        self.market = client                 # None 이면 이 서버에서 상권 비서를 끈 것
        self.config_error = config_error     # 주소 설정이 틀렸을 때의 안내 (off 가 아니라 error 로 보인다)
        self.defaults = STORE_DEFAULTS.get(store_id)
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT)

    @classmethod
    def from_settings(cls, settings) -> "AssistantProxy":
        raw = (getattr(settings, "market_url", DEFAULT_URL) or "").strip().rstrip("/")
        store_id = getattr(settings, "store_id", "store_ongi")
        if raw.lower() in ("", "off", "none", "0", "false"):
            return cls(None, store_id=store_id)
        parts = urlsplit(raw)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.path not in ("", "/") or parts.query \
                or parts.username or parts.password:
            return cls(None, store_id=store_id, config_error="상권 서비스 주소(MARKET_URL) 설정이 올바르지 않아요.")
        client = MarketClient(raw, getattr(settings, "market_host", DEFAULT_HOST) or DEFAULT_HOST,
                              read_timeout=float(getattr(settings, "market_timeout", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT))
        return cls(client, store_id=store_id)

    def close(self) -> None:
        if self.market is not None:
            self.market.close()

    # 상태 ----------------------------------------------------------------
    def _unavailable(self) -> MarketError | None:
        if self.config_error:
            return MarketError("error", self.config_error)
        if self.market is None:
            return MarketError("off", MESSAGES["off"])
        return None

    def status(self) -> dict:
        setup = {"label": self.defaults.label if self.defaults else None}
        problem = self._unavailable()
        extra: dict = {}
        if problem is None:
            try:
                data = self.market.request("GET", "/api/assistant/status", read_timeout=3.0).data
                if not (isinstance(data, dict) and data.get("enabled") is True):
                    raise MarketError("disabled", MESSAGES["disabled"])
                extra = {"model_connected": bool(data.get("model_connected")), "planner_connected": bool(data.get("planner_connected"))}
            except MarketError as exc:
                problem = exc
        if problem is not None:
            return {"state": problem.state if problem.state in STATES else "error", "message": problem.message, "setup": setup}
        return {"state": "ready", "message": None, **extra, "setup": setup}

    # 분석 조건 자동 맞추기 ----------------------------------------------------
    def setup(self, token: str | None, force: bool = False) -> tuple[dict, str | None]:
        """조건이 비어 있으면 우리 가게 조건으로 채운다. force 이면 이미 있는 조건도 우리 가게 조건으로 되돌린다.
        (응답 본문, 브라우저에 심을 세션 값)"""
        problem = self._unavailable()
        if problem is not None:
            return self._setup_result("unavailable", problem.state, problem.message, None), token
        current = self.status()      # 상권 서비스가 꺼져 있거나 챗봇이 꺼져 있으면 조건을 맞추려 들지 않는다 (온보딩 길은 챗봇과 상관없이 열려 있다)
        if current["state"] != "ready":
            return self._setup_result("unavailable", current["state"], current["message"], None), token
        session = {"token": token}
        try:
            return self._setup(session, force)
        except MarketError as exc:
            if exc.state == "invalid":      # 우리가 보낸 조건을 상권 서비스가 거절 → 설정 문제이지 사용자 입력 문제가 아니다
                exc = MarketError("error", MESSAGES["error"])
            return self._setup_result("unavailable", exc.state, exc.message, None), session["token"]

    @staticmethod
    def _setup_result(status: str, state: str, message: str | None, conditions: dict | None) -> dict:
        return {"status": status, "state": state, "message": message, "conditions": conditions}

    def _setup(self, session: dict, force: bool = False) -> tuple[dict, str | None]:
        market, wanted = self.market, self.defaults

        def call(method, path, body=None, *, timeout=20.0):
            up = market.request(method, path, session["token"], body, read_timeout=timeout)
            session["token"] = up.token or session["token"]      # 상권 서비스가 새 세션을 열어 줬으면 이어서 그 값을 쓴다
            return up.data

        def conditions() -> dict | None:
            data = call("GET", "/api/assistant/conversation")
            return data.get("conditions") if isinstance(data, dict) else None

        state = call("GET", "/api/onboarding/analysis-selection")
        if wanted is None:
            # 기본 조건을 정해 두지 않은 가게: 질문할 때 위치·업종을 묻는다
            return self._setup_result("already", "ready", None, conditions() if state.get("conditions_confirmed") else None), session["token"]
        if state.get("conditions_confirmed") and not force:
            return self._setup_result("already", "ready", None, conditions()), session["token"]
        profile = state.get("profile")
        if profile is None or force:
            state = call("POST", "/api/onboarding/profile", {
                "location": {"kind": "station", "station_id": wanted.station_id}, "industry_code": wanted.industry_code,
                "business_status": wanted.business_status, "expected_revision": state.get("revision")})
        elif not (profile["location"].get("station_id") == wanted.station_id
                  and profile["industry"].get("code") == wanted.industry_code):
            # 사용자가 이미 다른 위치·업종을 고르는 중이다. 덮어쓰지 않는다
            return self._setup_result("already", "ready", None, None), session["token"]
        try:
            options = call("GET", "/api/onboarding/analysis-options")
        except MarketError as exc:
            if exc.state == "no_data":
                return self._setup_result("unavailable", "no_data", exc.message, None), session["token"]
            raise
        candidates = [c for c in options.get("candidates", []) if not c.get("selection_blocked_reason")]
        chosen = _pick_area(candidates, wanted)
        if chosen is None:
            if not candidates:
                return self._setup_result("unavailable", "no_data", MESSAGES["no_data"], None), session["token"]
            return self._setup_result("unavailable", "error",
                                      "우리 가게 상권을 하나로 정하지 못했어요. 질문에서 상권을 골라 주세요.", None), session["token"]
        periods = chosen.get("available_periods") or []
        if not periods:
            return self._setup_result("unavailable", "no_data", MESSAGES["no_data"], None), session["token"]
        period = wanted.period if wanted.period in periods else max(periods)
        fresh = call("GET", "/api/onboarding/analysis-selection")
        call("POST", "/api/onboarding/analysis-selection", {
            "area_code": chosen["area_code"], "period": period, "expected_revision": fresh.get("revision"),
            "expected_catalog_version": options["catalog_version"]})
        return self._setup_result("ok", "ready", None, conditions()), session["token"]

    # 질문·선택지·대화 -----------------------------------------------------------
    def forward(self, method: str, path: str, token: str | None, body: dict | None = None) -> tuple[Any, str | None]:
        problem = self._unavailable()
        if problem is not None:
            raise problem
        up = self.market.request(method, path, token, body)
        return up.data, up.token or token


def _pick_area(candidates: list[dict], wanted: SetupDefaults) -> dict | None:
    """정해 둔 상권 코드 → 이름에 '장승배기역'이 든 상권 하나 → 안쪽 상권이 하나뿐일 때. 그래도 못 정하면 None."""
    by_code = next((c for c in candidates if c.get("area_code") == wanted.area_code), None)
    if by_code is not None:
        return by_code
    inside = [c for c in candidates if c.get("relation") in ("inside", "boundary")]
    if len(inside) == 1:
        return inside[0]
    return candidates[0] if len(candidates) == 1 else None


# ── 라우터 ─────────────────────────────────────────────────────────────────
def _fail(exc: MarketError, token: str | None = None, secure: bool = False) -> JSONResponse:
    result = JSONResponse(status_code=exc.http, content={"error": {"message": exc.message, "state": exc.state}})
    result.headers["Cache-Control"] = "no-store"
    return _with_cookie(result, token, secure)


def _with_cookie(result: JSONResponse, token: str | None, secure: bool) -> JSONResponse:
    if token and TOKEN.fullmatch(token):
        result.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True, samesite="lax", secure=secure,
                          path="/api/assistant")
    return result


def _ok(data: Any, token: str | None, secure: bool) -> JSONResponse:
    result = JSONResponse(data)
    result.headers["Cache-Control"] = "no-store"
    return _with_cookie(result, token, secure)


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"


def _token(request: Request) -> str | None:
    value = request.cookies.get(COOKIE_NAME)
    return value if value and TOKEN.fullmatch(value) else None


def create_assistant_router(proxy: AssistantProxy) -> APIRouter:
    router = APIRouter(prefix="/api/assistant")

    def guarded(request: Request, work: Callable[[str | None], tuple[Any, str | None]]) -> JSONResponse:
        """work(세션 값) → (응답 본문, 새 세션 값). 상권 서비스 문제와 예상 못한 오류 모두 서랍용 오류 응답이 된다. 500 은 없다."""
        token, secure = _token(request), _secure(request)
        if not proxy.slots.acquire(timeout=1.0):
            return _fail(MarketError("error", BUSY_MESSAGE), token, secure)
        try:
            data, token_out = work(token)
            return _ok(data, token_out, secure)
        except MarketError as exc:
            return _fail(exc, token, secure)
        except Exception as exc:     # 여기까지 오면 우리 쪽 버그다. 화면 전체가 죽지 않게 서랍에만 알린다
            log.exception("상권 비서 프록시 예상 못한 오류 (%s)", exc.__class__.__name__)
            return _fail(MarketError("error", MESSAGES["error"]), token, secure)
        finally:
            proxy.slots.release()

    @router.get("/status")
    def status(request: Request):
        try:
            return _ok(proxy.status(), _token(request), _secure(request))
        except Exception as exc:     # status 는 어떤 경우에도 200
            log.exception("상권 비서 status 오류 (%s)", exc.__class__.__name__)
            return _ok({"state": "error", "message": MESSAGES["error"], "setup": {"label": None}}, None, False)

    @router.post("/setup")
    def setup(request: Request, force: bool = False):
        token, secure = _token(request), _secure(request)
        if not proxy.slots.acquire(timeout=1.0):
            return _ok({"status": "unavailable", "state": "error", "message": BUSY_MESSAGE, "conditions": None}, token, secure)
        try:
            data, token_out = proxy.setup(token, force)
            return _ok(data, token_out, secure)
        except Exception as exc:     # setup 도 항상 200
            log.exception("상권 비서 setup 오류 (%s)", exc.__class__.__name__)
            return _ok({"status": "unavailable", "state": "error", "message": MESSAGES["error"], "conditions": None}, token, secure)
        finally:
            proxy.slots.release()

    @router.post("/messages")
    def messages(body: MessageIn, request: Request):
        return guarded(request, lambda token: proxy.forward("POST", "/api/assistant/messages", token,
                                                            body.model_dump(exclude_none=True)))

    @router.post("/actions")
    def actions(body: ActionIn, request: Request):
        return guarded(request, lambda token: proxy.forward("POST", "/api/assistant/actions", token,
                                                            body.model_dump(exclude_none=True)))

    @router.get("/conversation")
    def conversation(request: Request):
        return guarded(request, lambda token: proxy.forward("GET", "/api/assistant/conversation", token))

    @router.delete("/conversation")
    def clear(request: Request):
        return guarded(request, lambda token: proxy.forward("DELETE", "/api/assistant/conversation", token))

    return router


def validation_error_response(exc) -> JSONResponse:
    """/api/assistant/* 의 입력 오류를 서랍이 읽는 모양으로. (다른 경로의 422 는 건드리지 않는다)"""
    first = (exc.errors() or [{}])[0]
    message = "입력 내용을 확인해 주세요."
    if first.get("type") == "string_too_long":
        message = "질문은 1000자까지 쓸 수 있어요."
    elif first.get("type") in ("string_too_short", "missing"):
        message = "질문을 입력해 주세요."
    return JSONResponse(status_code=422, content={"error": {"message": message, "state": "invalid"}})
