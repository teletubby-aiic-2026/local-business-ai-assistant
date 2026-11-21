"""상권 비서 프록시 — 오른쪽 "AI에게 묻기" 서랍이 상권 서비스(ic26-market, 127.0.0.1:8766)와 대화하는 길.

브라우저는 이 서버(같은 출처)의 /api/assistant/* 만 부른다. 이 서버가 상권 서비스를 대신 불러 준다.

| 메서드 | 경로                            | 하는 일 |
|--------|---------------------------------|---------|
| GET    | /api/assistant/status           | 상권 비서를 쓸 수 있는지. 항상 200 (ready·off·down·disabled·no_data·error) |
| POST   | /api/assistant/setup            | 우리 가게(온기한식)의 분석 조건(장승배기역·한식음식점·최신 분기)을 자동으로 맞춘다. 항상 200.
|        |                                 | 이미 조건이 있으면 그대로 둔다. `?force=1` 이면 다른 곳을 보고 있어도 우리 가게 조건으로 되돌린다 |
| POST   | /api/assistant/messages         | 질문 1개 → 답, 근거 카드, 선택지 (상권 서비스의 같은 경로).
|        |                                 | 가게 자체를 묻는 질문(이름·업종·상권·메뉴, 리뷰·답글을 어디서 보는지)은 상권 서비스로 보내지 않고 여기서 답한다 |
| POST   | /api/assistant/actions          | 선택지 카드를 눌렀을 때 (같은 경로) |
| GET    | /api/assistant/conversation     | 이 세션의 대화와 분석 조건 (같은 경로) |
| DELETE | /api/assistant/conversation     | 대화 지우기 (같은 경로) |

상권 서비스의 답을 화면에 넘기기 전에 두 가지를 손본다 (보이는 글자만. 선택지 payload 처럼 상권 서비스로 되돌아가는 값은 그대로)
- 분기 코드(20262)가 글자에 그대로 들어 있으면 '2026년 2분기'로 바꾼다 (quarter_words).
- 분석 조건(conditions)에 `is_store_default` 를 더한다: 지금 조건이 우리 가게 기본 조건과 같은지 (서랍의 '우리 가게 조건으로' 버튼이 씀).

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

import copy
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

from shared import store_profiles
from shared.contracts import StoreProfile

from .sources import load_snapshots, to_store_profile

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
    # 직접 등록한 가게(11/20)는 주소로 등록할 수 있다. 예시 세 곳은 역(station) 그대로
    location_kind: str = "station"         # station | address
    road_address: str = ""                 # 주소로 등록한 가게의 도로명 주소 (상권 서비스 주소 검색에 다시 넣는다)
    latitude: float | None = None
    longitude: float | None = None


STORE_DEFAULTS: dict[str, SetupDefaults] = {
    "store_ongi": SetupDefaults(
        station_id="kric-e12f817979cd-S1107-0740",      # 장승배기역 (7호선)
        industry_code="CS100001",                       # 한식음식점
        area_code="3110826",                            # 장승배기역 4번 상권 (data/scenario/snapshot_2026Q2.json 의 상권)
        period="20262",                                 # 2026년 2분기
        business_status="operating",
        label="온기한식 · 장승배기역 · 한식음식점"),
}
# 5차 회의(11/18): 바삭치킨·몽글카페. 역·업종·상권 코드는 shared.store_profiles (상권 서비스 표에 있는 값, 시험이 확인)
for _sid in ("store_basak", "store_mongle"):
    _b = store_profiles.BUNDLES[_sid]
    STORE_DEFAULTS[_sid] = SetupDefaults(station_id=_b.station_id, industry_code=_b.industry_code, area_code=_b.area_code,
                                         period="20262", business_status="operating", label=_b.label)


# 사장님이 직접 등록한 가게 (6차 회의 11/20): 등록 때 받은 위치·업종·상권·분기가 기본 조건이다.
# 가게를 고치면 바로 따라가도록 저장 값(store_profiles.get, 5초 기억)에서 그때그때 만든다.
ADDRESS_MISS = "등록한 주소로 상권 위치를 찾지 못했어요. 질문이나 상권 분석 화면에서 위치를 직접 골라 주세요."


_SHORT_PLACE = re.compile(r"^(?:서울특별시|서울시|서울)\s+(\S+구\s+\S+(?:로|길)\S*\s+\d+(?:-\d+)?)(?:\s.*)?$")


def short_place(label: str) -> str:
    """'서울특별시 마포구 와우산로 94 학교법인홍익학원' → '마포구 와우산로 94'. 그 모양이 아니면 그대로."""
    text = re.sub(r"\s+", " ", label or "").strip()
    m = _SHORT_PLACE.match(text)
    return m.group(1) if m else text


def registered_defaults(store_id: str | None) -> SetupDefaults | None:
    """등록 가게의 기본 조건. 예시 가게·모르는 가게, 위치나 업종이 없어 맞출 수 없는 가게면 None."""
    if not store_profiles.is_registered_id(store_id):
        return None
    bundle = store_profiles.get(store_id)
    if bundle is None or not bundle.registered or not bundle.industry_code:
        return None
    loc = bundle.location or {}
    kind = "station" if loc.get("kind") == "station" else "address"
    road = (loc.get("road_address") or loc.get("label") or "").strip()
    if (kind == "station" and not bundle.station_id) or (kind == "address" and not road):
        return None
    label = bundle.label
    if kind == "address" and not bundle.station_name:
        # 서랍이 조건을 맞추는 동안 보이는 이름 (11/21): 주소 원문 "서울특별시 마포구 와우산로 94 학교법인홍익학원" 대신 "마포구 와우산로 94"
        label = f"{bundle.short_name} · {short_place(loc.get('label') or road) or bundle.area_name} · {bundle.business_type_name}"
    return SetupDefaults(station_id=bundle.station_id, industry_code=bundle.industry_code, area_code=bundle.area_code,
                         period=bundle.period, business_status=bundle.business_status, label=label,
                         location_kind=kind, road_address=road if kind == "address" else "",
                         latitude=loc.get("latitude"), longitude=loc.get("longitude"))


def store_defaults(store_id: str | None) -> SetupDefaults | None:
    """가게의 기본 분석 조건: 예시 세 곳은 STORE_DEFAULTS, 직접 등록한 가게는 등록한 값."""
    return STORE_DEFAULTS.get(store_id or "") or registered_defaults(store_id)


def _nospace(text: Any) -> str:
    return re.sub(r"\s+", "", text) if isinstance(text, str) else ""


def same_location(location: Any, wanted: SetupDefaults) -> bool:
    """상권 서비스에 저장된 위치가 우리 가게 위치와 같은지 (역 id, 또는 주소면 도로명 주소)."""
    if not isinstance(location, dict):
        return False
    if wanted.location_kind == "address":
        return location.get("kind") == "address" and _nospace(location.get("road_address")) == _nospace(wanted.road_address)
    return location.get("station_id") == wanted.station_id


def _meters(a_lat, a_lon, b_lat, b_lon) -> float:
    import math
    dy = (a_lat - b_lat) * 111_000.0
    dx = (a_lon - b_lon) * 111_000.0 * math.cos(math.radians((a_lat + b_lat) / 2))
    return math.hypot(dx, dy)


ADDRESS_NEAR_M = 150.0      # 도로명이 글자로 안 맞을 때 좌표로 같은 곳이라고 볼 거리


def pick_address(candidates: list[dict], wanted: SetupDefaults) -> dict | None:
    """주소 검색 후보 가운데 등록한 주소와 맞는 하나: 도로명 주소가 같은 것 → 좌표가 150m 안 → 후보가 하나뿐일 때. 아니면 None."""
    usable = [c for c in candidates if isinstance(c, dict) and c.get("id") and c.get("in_seoul") is not False]
    want = _nospace(wanted.road_address)
    same = [c for c in usable if want and want in (_nospace(c.get("road_address")), _nospace(c.get("label")))]
    if same:
        return same[0]
    if isinstance(wanted.latitude, (int, float)) and isinstance(wanted.longitude, (int, float)):
        near = sorted((_meters(wanted.latitude, wanted.longitude, c["latitude"], c["longitude"]), i, c)
                      for i, c in enumerate(usable)
                      if isinstance(c.get("latitude"), (int, float)) and isinstance(c.get("longitude"), (int, float)))
        if near and near[0][0] <= ADDRESS_NEAR_M:
            return near[0][2]
    return usable[0] if len(usable) == 1 else None


def location_body(call: Callable[..., Any], wanted: SetupDefaults) -> dict | None:
    """상권 서비스 프로필에 넣을 위치. 역은 그대로, 주소는 저장된 도로명 주소로 다시 검색해서 맞는 후보를 고른다
    (상권 서비스의 주소 후보 id 는 세션마다 다르다). 검색이 실패하거나 맞는 후보가 없으면 None."""
    if wanted.location_kind != "address":
        return {"kind": "station", "station_id": wanted.station_id}
    try:
        found = call("POST", "/api/onboarding/locations/search", {"query": wanted.road_address[:200]})
    except MarketError as exc:
        if exc.state == "down":
            raise
        log.info("등록 가게 주소 검색 실패 (%s)", exc.state)
        return None
    if not isinstance(found, dict) or not found.get("search_id"):
        return None
    chosen = pick_address(found.get("candidates") or [], wanted)
    if chosen is None:
        return None
    return {"kind": "address", "search_id": found["search_id"], "candidate_id": chosen["id"]}


# ── 분기 표기 ───────────────────────────────────────────────────────────
# 상권 서비스의 분기 코드는 '20262'(2026년 2분기)다. 조건에 분기 이름(period_label)이 빠지면 이 코드가 답 문장에 그대로 들어온다
# ("20262 자료로 볼게요"). 화면에 넘기기 전에 '2026년 2분기'로 바꾼다 (cards.quarter_words 의 '2026Q2' → '2026년 2분기'와 같은 모양).
# 금액·개수는 건드리지 않는다: 앞뒤에 숫자·영문·쉼표·점이 붙었거나(120262, 20,262, 20262.5) 바로 뒤에 단위가 오면(20262원) 그대로 둔다.
# 화면(frontend/src/features/assistant/chat.js 의 CHAT_QUARTER)도 같은 정규식을 쓴다. 시험이 두 곳의 정규식이 글자 그대로 같은지 확인한다.
QUARTER_CODE = re.compile(r"[0-9]{4}[1-4]")        # 칸 전체가 분기 코드일 때 (period_label 에 '20262' 가 온 경우)
QUARTER_IN_TEXT = re.compile(
    r"(^|[^0-9A-Za-z_,.\-])(20[0-9]{2})(?:Q([1-4])(?![0-9A-Za-z])|([1-4])(?![0-9A-Za-z_\-]|[,.][0-9]"
    r"|원|건|명|개|곳|호|번|위|배|회|세|살|대|가구|만|억|천|조|년|월|일|시|초|분(?!기)|평|점|%|퍼센트)(?: ?분기)?)")


def quarter_words(text: Any) -> Any:
    """문장 속 분기 코드(20262 · 2026Q2)를 '2026년 2분기'로. 글자가 아니면 그대로 돌려준다."""
    if not isinstance(text, str) or not text:
        return text
    return QUARTER_IN_TEXT.sub(lambda m: f"{m[1]}{m[2]}년 {m[3] or m[4]}분기", text)


def period_words(value: Any) -> Any:
    """분기 칸 하나(period_label): '20262' → '2026년 2분기'. 코드만 있는 칸이 아니면 문장으로 보고 quarter_words."""
    if isinstance(value, str) and QUARTER_CODE.fullmatch(value.strip()):
        code = value.strip()
        return f"{code[:4]}년 {code[4]}분기"
    return quarter_words(value)


def _reworded(item: Any, words: dict[str, Callable[[Any], Any]]) -> Any:
    """dict 의 정해 둔 칸만 바꾼 사본. 없는 칸은 만들지 않고, dict 가 아니면 그대로 돌려준다."""
    if not isinstance(item, dict):
        return item
    return {key: words[key](value) if key in words else value for key, value in item.items()}


def _each(change: Callable[[Any], Any]) -> Callable[[Any], Any]:
    return lambda items: [change(item) for item in items] if isinstance(items, list) else items


def _reply_words(reply: Any) -> Any:
    """답(reply)의 보이는 글자만. 선택지의 payload 는 상권 서비스로 되돌아가는 값이라 그대로 둔다."""
    return _reworded(reply, {"text": quarter_words, "notes": _each(quarter_words), "suggestions": _each(quarter_words),
                             "actions": _each(lambda action: _reworded(action, {"label": quarter_words}))})


def _card_words(card: Any) -> Any:
    """근거 카드의 보이는 글자만 (문장·주의 문장·값 이름·글자 값). 값의 code 와 출처는 그대로 둔다."""
    def value_words(value: Any) -> Any:
        label = value.get("label") if isinstance(value, dict) else None
        return _reworded(value, {"label": quarter_words, "value": period_words if label == "기간" else quarter_words})
    return _reworded(card, {"text": quarter_words, "warnings": _each(quarter_words), "values": _each(value_words)})


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


# ── 가게 기본 질문 (상권 서비스로 보내지 않고 여기서 답한다) ─────────────────────────────
# 서랍은 '동네 상권·업종 매출 상담'이지만 사장님은 "우리 가게 이름 뭐야?", "우리 가게 메뉴 뭐야?", "리뷰 답글은 어디서 봐?"도 묻는다.
# 상권 서비스는 이런 질문에 분석 조건 문장이나 엉뚱한 상권 숫자로 답한다. 그래서 가게 자체를 묻는 질문만 골라 가게 프로필로 답한다.
# 고르는 규칙은 보수적이다 (store_question). 상권 자료 단어가 하나라도 섞이면 상권 서비스로 보낸다.
REPLY_SCHEMA = "assistant-reply-v1"     # 상권 서비스 assistant/flow.py 의 SCHEMA (시험이 같은지 확인)
STORE_ANSWER = "store_profile"          # 여기서 답한 응답에만 붙는 answered_by 값
MAX_STORE_QUESTION = 40                 # 공백·기호를 뺀 글자 수. 이보다 긴 글은 단순한 가게 질문으로 보지 않는다
# 화면 메뉴 이름. frontend/src/components/Sidebar.jsx 의 메뉴 글자와 같아야 한다 (시험이 확인)
SCREENS = {"reviews": "리뷰 분석", "cards": "추천 카드", "drafts": "승인할 글", "done": "처리 완료", "marketing": "맞춤 마케팅",
           "report": "종합 리포트"}
MARKET_SCREEN = "상권 분석"          # 11/18 메뉴 (#/market). SCREENS 는 리뷰·마케팅 쪽 화면만 (가게 질문 시험이 그 목록을 고정)
BACK_TO_MARKET = ["우리 가게 상권 매출은 어때?", "주변에 같은 업종 점포는 몇 개야?"]     # 답 아래 '이어서 물어보기' (서랍 첫 추천 질문과 같은 문장)
STORE_NOTE = "가게 이름·업종·메뉴는 저장된 가게 프로필이에요. 상권 통계가 아니에요."
STORE_DOWN = "가게 정보를 지금 불러오지 못했어요. 잠시 뒤 다시 물어봐 주세요."
NOT_ON_SCREEN = "이 화면에는 그 정보가 없어요."
GUIDE_LINE = (f"참고: 리뷰는 화면 메뉴 '{SCREENS['reviews']}', 답글·안내문·홍보 글은 '{SCREENS['cards']}' → '{SCREENS['drafts']}', "
              f"맞춤 홍보 제안·광고비 점검은 '{SCREENS['marketing']}', 전체 요약은 '{SCREENS['report']}'에서 볼 수 있어요.")

# 하나라도 있으면 상권 질문 (가게 질문과 섞여 있어도 상권 서비스로 보낸다). 상권 서비스가 맡는 자료·의견·입지 비용 낱말
_MARKET_WORDS = ("상권", "매출", "장사", "벌이", "벌어", "벌었", "버는", "벌고", "수입", "유동", "인구", "점포", "경쟁", "개업", "폐업", "창업",
                 "평균", "비교", "순위", "주변", "근처", "동네", "다른가게", "분기", "주말", "평일", "요일", "점심", "저녁", "시간대",
                 "연령", "나이대", "추천", "팔리", "잘팔", "잘나가", "인기", "어때", "어떤가", "어떨까", "잘되", "잘돼", "안되", "안돼",
                 "될까", "좋", "괜찮", "나쁘", "나빠", "유리", "불리", "전망", "통계", "월세", "임대료", "권리금", "보증금")
# 가게 정보를 묻는 것이 아니라 일을 시키거나 조언을 구하는 말 → 여기서 답하지 않는다
_TASK_WORDS = ("써줘", "써주", "써줄", "써달", "만들어", "작성", "짜줘", "짜주", "바꿔", "바꾸", "바꿀", "수정", "고쳐", "고치", "추가",
               "삭제", "지워", "빼줘", "등록", "지어", "정해", "하면", "할까", "올릴", "올려", "내릴", "내려", "적정", "책정")
_WONDER = re.compile(r"(?<!니)까(요)?$")      # '뭐 넣을까?', '바꿀까요?'처럼 고민을 묻는 말끝 ('무엇입니까'는 그냥 질문)
_OURS = re.compile(r"(우리|저희|내|제|울)(가게|매장|식당|집|상호|메뉴)|^(가게|매장|식당|상호|메뉴)")     # '우리 가게…' 또는 '가게…'로 시작
# 가게 정보는 "그 낱말 + 바로 묻는 말"일 때만 고른다: '이름 뭐야', '이름이 뭐였지', '메뉴 좀 알려줘', 낱말로 끝나는 '우리 가게 메뉴'
_P = r"(이|가|은|는|을|를|도|의)?(좀)?"
_Q = r"(뭐|무엇|뭔|뭘|무슨|어떤|어디|어떻게|몇|얼마|알려|말해|보여|있|$)"
_NAME = re.compile(rf"(이름|상호|상호명|가게명|매장명){_P}{_Q}")
_INDUSTRY = re.compile(rf"업종{_P}{_Q}|(무슨|어떤)업종|(무슨|어떤|뭐하는)(가게|매장|식당|집)(이야|야|예요|에요|인지|이지|임|이냐|냐|$)")
_MENU = re.compile(rf"(메뉴|메뉴판|메뉴목록|메뉴종류){_P}{_Q}|(뭐|뭘|무엇을)(팔|파)")
_PRICE = re.compile(rf"(가격|가격표|값){_P}{_Q}|얼마(야|예요|에요|지|죠|니|임|인지|입니|인가|에팔|에파|씩|$)")
_AREA = re.compile(rf"(위치|주소){_P}{_Q}|어디(에)?(있|위치)|어디(야|예요|에요|지|죠|니|임|인지|쯤|$)")
_PROFILE = re.compile(rf"(정보|기본정보|프로필){_P}{_Q}|소개(해|좀|$)")
# 프로필에 없는 것. 지어내지 않고 '이 화면에는 그 정보가 없어요'라고 답한다
_NOT_KNOWN = re.compile(rf"(영업시간|운영시간|오픈시간|마감시간|휴무일|휴무|쉬는날|휴일|전화번호|연락처|사장님?(이름|성함)|대표자|대표자명"
                        rf"|사업자번호|사업자등록번호|직원수|직원|알바|좌석수|좌석|테이블수|테이블|주차장|주차|평수|면적|배달비|최소주문금액|최소주문"
                        rf"|원산지|칼로리|알레르기|와이파이|예약){_P}{_Q}|몇시|언제(열|닫|쉬|오픈|마감|문)")
# '상권'은 상권 낱말이지만 "우리 가게 어느 상권이야?", "우리 가게 상권이 뭐야?"는 가게가 속한 상권 이름을 묻는 것이다
_WHICH_AREA = re.compile(rf"(어느|무슨)상권|상권(이름|명)?{_P}(뭐|무엇|뭔|어디)(야|예요|에요|지|죠|니|임|인지|냐|였|더라|$)")
# 화면 위치를 묻는 질문: 화면에 있는 것(리뷰·답글·공지…) + 어디서 보는지
_SCREEN_WORDS = ("리뷰", "후기", "답글", "댓글", "공지", "안내문", "홍보", "쿠폰", "마케팅", "광고", "리포트", "보고서", "응대점수", "불만", "초안",
                 "승인", "추천카드", "처리완료")
_WHERE = re.compile(r"어디(에서|서|에|로)?(봐|보|볼|확인|찾|있|달|쓰|써|관리|승인|들어|눌|해|가면|가야)|어디로가|어디(야|예요|에요|지|죠|니|임|인지|더라)"
                    r"|어떻게(봐|보|볼|확인|찾|들어가)|(보|확인하|찾으|들어가)려면|(보|확인하)고싶|(볼|확인할|찾을)수있|보여(줘|줄|주)"
                    r"|(보는|확인하는|찾는)(곳|법|방법|데)|위치")
_NOT_WHERE = ("맛집", "써줘", "써주", "써줄", "써달", "만들어", "작성해", "짜줘", "짜주")      # 글을 써 달라는 말·다른 가게 찾기는 화면 위치 질문이 아니다
# 우리 가게의 메뉴별 매출: 리뷰 분석에도 상권 자료에도 없다. 상권 범위 낱말이 없을 때만 '없어요'라고 답한다
_MENU_SALES = re.compile(r"메뉴(별|마다|당)[가-힣]{0,6}(매출|판매|팔)|(매출|판매량)[가-힣]{0,4}메뉴(별|마다)|(많이|잘)(팔리|팔린|나가)[가-힣]{0,3}메뉴")
_SCOPE_WORDS = ("상권", "동네", "주변", "근처", "업종", "평균", "다른", "서울", "전체", "지역")


# 어순이 뒤바뀐 가게 질문 (11/20): "메뉴 우리 가게", "이름 가게"처럼 '우리 가게'가 뒤에 오면 앞으로 옮겨 한 번 더 본다
_OURS_LAST = re.compile(r"(우리|저희|내|제|울)(가게|매장|식당|집|상호)(은|는|이|가|의|요|야|예요|에요)?$")
_ATTR_SHOP = re.compile(r"(메뉴|메뉴판|이름|상호|상호명|업종|가격표|기본정보|프로필)(은|는|이|가|의)?(가게|매장|식당)(은|는|이|가|요|야|예요|에요)?")
# 메뉴 이름 없이 우리 가게 가격만 묻는 말 ("우리 가게 가격 알려줘", "가격 우리 가게") → 메뉴 가격표
_PLAIN_PRICE = re.compile(r"((우리|저희|내|제|울)?(가게|매장|식당|집)(의|은|는)?)?가격(표)?(이|가|은|는|좀)?(뭐|얼마|알려|보여|말해)?[가-힣]{0,3}")


def _squash(text: str) -> str:
    """공백·기호를 빼고 소문자로 (질문을 고를 때 쓰는 글자)."""
    return re.sub(r"[^0-9a-z가-힣]", "", (text or "").lower())


def _reordered(c: str) -> str | None:
    """'우리 가게'가 뒤에 온 글자를 '우리 가게…' 순서로 옮긴 것. 옮길 모양이 아니면 None.
      · '메뉴 우리 가게' → '우리가게메뉴' (소유격이 뒤에 옴)
      · '이름 가게'      → '우리가게이름' (속성 낱말 하나 + 가게. '우리이름가게'는 _OURS 를 지나지 못해 '우리'+가게+속성 순서로)"""
    m = _OURS_LAST.search(c)
    if m and m.start() > 0:
        return m.group(1) + m.group(2) + c[:m.start()]
    m = _ATTR_SHOP.fullmatch(c)
    if m:
        return "우리" + m.group(3) + m.group(1)
    return None


def store_question(text: str) -> str | None:
    """가게 자체를 묻는 질문이면 그 종류를, 아니면(상권 질문·모르는 말) None 을 돌려준다. None 이면 상권 서비스로 보낸다.

    종류: where(화면 위치) · name · industry · area · menu · price · profile(기본 정보) · unknown(프로필에 없는 것) · menu_sales(메뉴별 매출)
    순서
      ① 우리 가게 메뉴별 매출 (상권 범위 낱말이 없을 때만)
      ② 상권 낱말(_MARKET_WORDS)이 하나라도 있으면 상권 서비스. 하나뿐인 낱말이 '상권'이고 가게의 상권 이름을 묻는 모양일 때만 area
      ③ 화면 위치: 화면에 있는 것(리뷰·답글·공지…) + 어디서 보는지
      ④ 가게 정보: '우리 가게…'·'가게…'로 시작하고, 낱말 바로 뒤에 묻는 말이 올 때만. 일을 시키는 말(써줘·바꿔…)과 고민을 묻는 말(…할까?)은 뺀다
    ①~④에 걸리지 않으면 '우리 가게'가 뒤에 온 글자를 앞으로 옮겨(_reordered) 딱 한 번 더 본다 (11/20, "메뉴 우리 가게").
    옮긴 글자도 같은 규칙을 지나야 하므로 상권 낱말이 섞이면 그대로 상권 서비스다. 다시 옮기지는 않는다 (같은 글자가 되는 입력도 끝난다).
    공백·기호를 뺀 글자가 40자를 넘는 글은 여기서 답하지 않는다.
    """
    c = _squash(text)
    if not c or len(c) > MAX_STORE_QUESTION:
        return None
    found = _store_kind(c)
    if found is None:
        moved = _reordered(c)
        if moved is not None and moved != c:
            found = _store_kind(moved)
    return found


def _store_kind(c: str) -> str | None:
    """store_question 의 ①~④ (c 는 _squash 한 글자)."""
    def has(words: tuple[str, ...]) -> bool:
        return any(word in c for word in words)

    ours, task = bool(_OURS.search(c)), has(_TASK_WORDS) or bool(_WONDER.search(c))
    if ours and _MENU_SALES.search(c) and not has(_SCOPE_WORDS):
        return "menu_sales"
    market = [word for word in _MARKET_WORDS if word in c]
    if market:
        return "area" if market == ["상권"] and ours and not task and _WHICH_AREA.search(c) else None
    if has(_SCREEN_WORDS) and _WHERE.search(c) and not has(_NOT_WHERE):
        return "where"
    if not ours or task:
        return None
    for kind, pattern in (("unknown", _NOT_KNOWN), ("menu", _MENU), ("price", _PRICE), ("name", _NAME),
                          ("industry", _INDUSTRY), ("area", _AREA), ("profile", _PROFILE)):
        if pattern.search(c):
            return "price" if kind == "menu" and _PRICE.search(c) else kind
    return None


def _plain_price(text: str) -> bool:
    """메뉴 이름 없이 우리 가게 가격(표)만 묻는 말인지. 어순이 뒤바뀐 것('가격 우리 가게')도 옮겨서 본다."""
    c = _squash(text)
    moved = _reordered(c)
    return bool(_PLAIN_PRICE.fullmatch(c) or (moved is not None and _PLAIN_PRICE.fullmatch(moved)))


# ── 전 파트 질문 (5차 회의 11/18) ──────────────────────────────────────────────
# 상권 질문은 지금처럼 상권 서비스가 8분기 자료로 답한다. 입력·설정이 필요한 고객응대·마케팅·리포트 질문은 여기서
# 지금 가게의 현황 1~2줄과 그 기능 화면으로 바로 가는 버튼(payload.type "navigate")을 준다. 상권 서비스는 부르지 않는다.
# 버튼은 상권 서비스의 /actions 로 보내지 않고 화면(frontend/src/features/assistant/state.js)이 그 자리에서 이동한다.
DOMAIN_ANSWER = "web_domain"        # 여기서 답한 전 파트 응답의 answered_by
_STRONG_MARKET = ("상권", "유동", "인구", "점포", "경쟁", "개업", "폐업", "창업", "월세", "임대료", "권리금", "보증금", "통계",
                  "연령", "나이대", "배후", "집객", "직장인", "동네", "주변", "근처")
_REPORT_Q = ("리포트", "보고서", "응대점수", "성적", "pdf", "결산")
_MKT_NEW = ("인스타", "sns", "블로그", "플레이스", "배민공지", "신메뉴홍보", "손님늘", "단골늘")     # 11/20 더함 (PR #72)
_MKT_Q = ("쿠폰", "본전", "할인", "남은재료", "남는재료", "재고", "떨이", "광고비", "광고", "홍보", "가게이야기", "소개글", "스토리",
          "마케팅", "이벤트", "단골", "재주문", "사용률", "전단", "프로모션", *_MKT_NEW)
# 11/20 낱말과 함께 오면 상권 자료로 답할 질문 (11/21): "손님 늘리려면 점심이 나아 저녁이 나아?", "SNS 홍보하면 매출 늘까?",
# "인스타 하는 가게 매출 어때?" 는 마케팅 안내가 아니라 상권의 매출·시간대·요일을 묻는다. 11/20 전 낱말(쿠폰·홍보…)만 있는 질문은 그대로
_MKT_NEW_MARKET = ("매출", "점심", "저녁", "시간대", "요일", "주말", "평일")
_CARE_Q = ("리뷰", "후기", "불만", "답글", "댓글", "캡처", "캡쳐", "별점", "진상", "테러", "억울", "악플", "응대", "컴플레인", "클레임",
           "블랙컨슈머")
# 11/21: 리뷰라는 말 없이 손님 반응·주제를 묻는 말 ("손님들이 맛에 대해 뭐라고 해?", "알레르기 문의 있어?").
# 상권의 매출·시간대 낱말이 같이 오면 고르지 않는다 ("점심 손님들 많아?"는 상권 질문)
_CARE_MORE = ("평점", "칭찬", "문의", "알레르기", "손님반응", "손님들이", "뭐라고", "뭐래", "누락", "빠졌", "식었", "늦게왔", "눅눅",
              "불친절", "양이적")
# 리뷰 주제 낱말 (11/21): "이번주 맛은 어때?", "양 적다는 말 있어?" 처럼 '리뷰' 없이 음식·포장·배달을 묻는 말. '맛집'은 빼고
_CARE_TOPIC = re.compile(r"맛(?!집)|양이|양은|양적|포장(이|상태|불량)|식감|눅눅|위생|머리카락|이물질|친절|직원(이|태도|응대)|배달(이|시간)?(늦|느|오래)"
                         r"|평가|반응|후기|평이|뭐래")
_CARE_NOT = ("매출", "장사", "수입", "점포", "유동", "인구", "점심", "저녁", "시간대", "요일", "주말", "평일", "분기", "연령", "나이대")
# 오늘 추천 카드·할 일·초안을 묻는 말 (11/20). 단독 '추천'·'카드'는 상권 질문("메뉴 추천해줘")과 겹쳐 넣지 않는다
_CARDS_Q = ("추천카드", "오늘추천", "카드있", "오늘할일", "할일", "브리핑", "승인할글", "승인대기", "초안", "처리완료")
# 무엇을 물을지 모르는 말 ("우리 가게", "뭐 물어볼 수 있어?") → 상권 숫자를 꺼내지 않고 물을 수 있는 것을 알려 준다 (11/20)
_HELP_EXACT = re.compile(r"^((우리|저희|내|제|울)?(가게|매장|식당|집)|도와줘|도움말|뭐물어볼수있어|뭘물어볼수있어|무엇을물어볼수있어"
                         r"|뭐할수있어|무슨기능있어|어떤기능있어|기능알려줘)(요|야|예요|에요)?$")
# 고객응대 질문의 답 (리뷰 분석 서비스 /ask, 11/21). 답글·안내문을 '써 달라'는 말은 예전처럼 추천 카드로 안내한다
CARE_ANSWER = "review_insight"
NO_INQUIRY = ("통합 화면에는 아직 손님 문의 기능(문의 받기·문의 답하기)이 들어가 있지 않아요. 그래서 이 채팅에서도 손님 문의를 확인할 수 없어요.\n"
              "참고: 지금은 배달앱 리뷰만 볼 수 있어요. 리뷰에 남은 불만·답글은 물어보시면 바로 세어 드려요.")
_CARE_WRITE = re.compile(r"써줘|써주|써줄|써달|만들어|작성해|올리고싶")
_TO_CARDS = ("추천 카드에서 답글 만들기", "cards", None)
CARE_ACTIONS = {          # 질문 종류 → 이어서 할 일 버튼 (라벨, 화면, 탭)
    "complaints": [_TO_CARDS, ("불만 묶음 보기", "analysis", "issues")],
    "topic": [("불만 묶음 보기", "analysis", "issues"), _TO_CARDS],
    "time": [("불만 묶음 보기", "analysis", "issues"), _TO_CARDS],
    "trend": [("불만 묶음 보기", "analysis", "issues"), ("종합 리포트 보기", "report", None)],
    "unanswered": [_TO_CARDS, ("승인할 글 보기", "draft", None)],
    "howto": [_TO_CARDS],
    "score": [("종합 리포트 보기", "report", None), _TO_CARDS],
    "capture": [("리뷰 캡처·붙여넣기 열기", "analysis", "paste")],
    "inquiry": [("리뷰 분석 열기", "analysis", "summary")],
    "overview": [("리뷰 분석 열기", "analysis", "summary"), _TO_CARDS],
}
for _k in ("rating", "channel", "recent", "praise"):
    CARE_ACTIONS[_k] = [("리뷰 분석 열기", "analysis", "summary"), _TO_CARDS]
# 마케팅 질문의 답 (맞춤 마케팅 서비스 /ask, 11/21). 홍보 글을 '써 달라'는 말은 예전처럼 맞춤 마케팅 화면으로 안내한다
MKT_ANSWER = "marketing"
MKT_ACTIONS = {           # 질문 종류 → 이어서 할 일 버튼 (라벨, 화면, 탭: MKT_SUBS)
    "coupon_calc": [("맞춤 마케팅: 맞춤 홍보 제안", "marketing", "promo"), ("맞춤 마케팅: 쿠폰 결과 확인", "marketing", "repeat")],
    "coupon_result": [("맞춤 마케팅: 쿠폰 결과 확인", "marketing", "repeat")],
    "ads": [("맞춤 마케팅: 광고비 점검", "marketing", "ad")],
    "leftover": [("맞춤 마케팅: 남은 재료 팔기", "marketing", "leftover")],
    "notice_effect": [("맞춤 마케팅: 맞춤 홍보 제안", "marketing", "promo"), ("종합 리포트 보기", "report", None)],
    "activity": [("종합 리포트 보기", "report", None), ("맞춤 마케팅: 맞춤 홍보 제안", "marketing", "promo")],
    "overview": [("맞춤 마케팅: 맞춤 홍보 제안", "marketing", "promo"), ("종합 리포트 보기", "report", None)],
}
for _k in ("next", "ideas_new", "ideas_repeat", "ideas_value", "rainy", "menu_price"):
    MKT_ACTIONS[_k] = [("맞춤 마케팅: 맞춤 홍보 제안", "marketing", "promo"), ("맞춤 마케팅: 가게 이야기 글", "marketing", "story")]
HELP_TEXT = "어떤 것을 도와드릴까요? 상권 매출·점포 수, 우리 가게 메뉴·정보, 불만 리뷰 답글, 쿠폰·홍보 제안을 물어보실 수 있어요."
HELP_SUGGESTIONS = [BACK_TO_MARKET[0], "우리 가게 메뉴 뭐야?", "불만 리뷰 제일 많은 게 뭐야?"]     # 상권·가게·리뷰에서 하나씩
CARDS_SUGGESTIONS = ["불만 리뷰 제일 많은 게 뭐야?", "쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?", BACK_TO_MARKET[0]]
# 맞춤 마케팅 화면의 시작 모드 (frontend/src/features/marketing 의 MKT_SUB 와 같은 값, 시험이 확인)
MKT_SUBS = {"promo": "맞춤 홍보 제안", "leftover": "남은 재료 팔기", "ad": "광고비 점검", "story": "가게 이야기 글",
            "repeat": "쿠폰 결과 확인"}


def nav(label: str, route: str, sub: str | None = None) -> dict:
    payload = {"type": "navigate", "route": route}
    if sub:
        payload["sub"] = sub
    return {"label": label, "payload": payload}


def domain_question(text: str) -> str | None:
    """'help' · 'cards' · 'care' · 'marketing' · 'report' 또는 None(상권 서비스로).
    순서: ① 무엇을 물을지 모르는 말 그대로(_HELP_EXACT) → help ② 추천 카드·할 일·초안 낱말(_CARDS_Q)이 있고 상권 자료 낱말이 없으면 cards
    ③ 상권 자료 낱말(_STRONG_MARKET)이 있으면 상권 서비스 ④ 리포트 → 마케팅 → 고객응대 낱말.
    마케팅은 11/20 낱말(_MKT_NEW: 인스타·sns·손님늘 …)이 매출·점심·저녁·시간대·요일·주말·평일과 함께 오면 고르지 않는다 (11/21)."""
    c = _squash(text)
    if not c:
        return None
    if _HELP_EXACT.match(c):
        return "help"
    strong = any(w in c for w in _STRONG_MARKET)
    if any(w in c for w in _CARDS_Q) and not strong:
        return "cards"
    if strong:
        return None
    if any(w in c for w in _REPORT_Q):
        return "report"
    if any(w in c for w in _MKT_Q) and not (any(w in c for w in _MKT_NEW) and any(w in c for w in _MKT_NEW_MARKET)):
        return "marketing"
    if any(w in c for w in _CARE_Q):
        return "care"
    if (any(w in c for w in _CARE_MORE) or _CARE_TOPIC.search(c)) and not any(w in c for w in _CARE_NOT):
        return "care"
    return None


def marketing_sub(text: str) -> str:
    c = re.sub(r"[^0-9a-z가-힣]", "", (text or "").lower())
    for sub, words in (("leftover", ("남은재료", "남는재료", "재고", "떨이", "세트")), ("ad", ("광고비", "광고")),
                       ("story", ("가게이야기", "소개글", "스토리")), ("repeat", ("쿠폰결과", "사용률", "지난쿠폰"))):
        if any(w in c for w in words):
            return sub
    return "promo"


def _domain_reply(lines: list[str], kind: str, domain: str, actions: list[dict], suggestions: list[str]) -> dict:
    """상권 서비스 messages 와 같은 칸. conditions 는 싣지 않는다 (분석 조건을 바꾸지 않음)."""
    return {"schema_version": REPLY_SCHEMA,
            "reply": {"text": "\n".join(x for x in lines if x), "kind": kind, "cited": [], "actions": actions, "notes": [],
                      "suggestions": suggestions},
            "model_used": False, "cards": [], "topics": [],
            "classification": {"domain": domain, "turn_type": kind, "topics": [], "needs_user_choice": False,
                               "needs_model": False, "analyzer": "web_proxy"},
            "pending": None, "answered_by": DOMAIN_ANSWER}


def _ieyo(word: str) -> str:
    """'한식음식점' 뒤에는 '이에요', '카페' 뒤에는 '예요' (마지막 한글 글자의 받침으로 고른다)."""
    last = next((ch for ch in reversed(word) if "가" <= ch <= "힣"), None)
    return "예요" if last is not None and (ord(last) - 0xAC00) % 28 == 0 else "이에요"


def _store_reply(lines: list[str], kind: str, turn: str, *, notes: tuple[str, ...] = (), actions: list[dict] | None = None) -> dict:
    """상권 서비스가 messages 에 주는 것과 같은 칸 (assistant/flow.py 의 _finish. debug 는 원래 화면에 오지 않는다).
    conditions 는 싣지 않는다: 가게 질문은 분석 조건을 바꾸지 않으니 화면의 조건 줄이 그대로 남는다.
    actions: 화면 이동 버튼 (화면 위치 답만 싣는다. 가게 정보 답은 빈 목록)."""
    return {"schema_version": REPLY_SCHEMA,
            "reply": {"text": "\n".join(lines), "kind": kind, "cited": [], "actions": list(actions or []), "notes": list(notes),
                      "suggestions": list(BACK_TO_MARKET)},
            "model_used": False, "cards": [], "topics": [],
            "classification": {"domain": "store", "turn_type": turn, "topics": [], "needs_user_choice": False,
                               "needs_model": False, "analyzer": "web_proxy"},
            "pending": None, "answered_by": STORE_ANSWER}


def _where_answer(text: str) -> dict:
    c = re.sub(r"\s", "", text)
    drafts = (f"초안은 화면 메뉴 '{SCREENS['cards']}'에서 카드를 고르면 '{SCREENS['drafts']}'에 나와요. "
              f"승인한 글은 '{SCREENS['done']}'에 모여요.")
    # 첫 문장과 이동 버튼은 같은 분기에서 고른다 (문장이 말하는 화면과 버튼이 어긋나지 않게, 11/20)
    flow = [nav("추천 카드 보기", "cards"), nav("승인할 글 보기", "draft"), nav("처리 완료 보기", "done")]
    if "답글" in c or "댓글" in c:
        first, actions = "리뷰 답글 " + drafts, flow
    elif "공지" in c or "안내문" in c:
        first, actions = "포장·주문 안내문 " + drafts, flow
    elif "홍보" in c or "쿠폰" in c or "마케팅" in c or "광고" in c:
        # 맞춤 마케팅(설문으로 홍보 제안·쿠폰 손익·광고비 점검)이 먼저, 오늘 추천된 쿠폰 홍보글은 추천 카드에서
        first = (f"홍보·쿠폰·광고비는 화면 메뉴 '{SCREENS['marketing']}'에서 몇 가지 질문에 답하면 제안과 글을 만들어 드려요. "
                 f"오늘 추천된 쿠폰 홍보글은 '{SCREENS['cards']}'에서 카드를 고르면 '{SCREENS['drafts']}'에 나와요.")
        actions = [nav("맞춤 마케팅 열기", "marketing", "promo"), nav("추천 카드 보기", "cards")]
    elif "초안" in c or "승인" in c or "추천카드" in c or "처리완료" in c:
        first, actions = "글 " + drafts, flow
    elif "리포트" in c or "보고서" in c or "응대점수" in c:
        first = f"응대 점수와 월간 보고서는 화면 메뉴 '{SCREENS['report']}'에 있어요."
        actions = [nav("종합 리포트 열기", "report")]
    else:
        first = f"리뷰와 불만 묶음은 화면 메뉴 '{SCREENS['reviews']}'에서 볼 수 있어요."
        actions = [nav("리뷰 분석 열기", "analysis", "summary"), nav("추천 카드 보기", "cards")]
    return _store_reply([first,
                         f"- 리뷰·불만 묶음: '{SCREENS['reviews']}'",
                         f"- 답글·안내문·홍보 글 초안: '{SCREENS['cards']}' → '{SCREENS['drafts']}'",
                         f"- 맞춤 홍보 제안·광고비 점검·마케팅 보고서: '{SCREENS['marketing']}'",
                         f"- 승인한 글: '{SCREENS['done']}'",
                         f"- 응대 점수·월간 보고서: '{SCREENS['report']}'",
                         f"- 상권 매출·점포·유동인구 표와 차트: '{MARKET_SCREEN}'",
                         # 11/18부터 서랍이 리뷰·마케팅·리포트 질문에도 현황과 화면 이동 버튼으로 답한다 (예전 '리뷰는 여기서 답하지 않아요'는 맞지 않음)
                         "참고: 동네 상권·업종 매출 상담은 이 채팅에서 바로 답하고, 불만 리뷰·쿠폰·리포트를 물으면 지금 가게 현황과 그 화면으로 가는 버튼을 드려요."],
                        "store_guide", "where", actions=actions)


def store_answer(kind: str, text: str, store: StoreProfile | None) -> dict:
    """가게 질문의 답. 프로필에 있는 값만 쓴다 (없는 것은 '이 화면에는 그 정보가 없어요'). store 가 None 이면 프로필을 못 읽은 것."""
    if kind == "where":
        return _where_answer(text)
    if store is None:
        return _store_reply([STORE_DOWN, GUIDE_LINE], "store_unavailable", kind)
    menu = list(store.menu)
    prices = store.menu_prices or {}
    if kind == "price":
        # "우리 가게 김치찌개 얼마야?"처럼 메뉴 값을 물을 때만 가격표로 답한다. 메뉴가 아닌 것의 값은 프로필에 없다
        # 메뉴 이름 없이 가게 가격만 묻는 말("우리 가게 가격 알려줘", "가격 우리 가게")도 메뉴 가격표 (11/20)
        c = re.sub(r"\s", "", text)
        if not ("메뉴" in c or "가격표" in c or any(name.replace(" ", "") in c or name.split()[0] in c for name in menu)
                or _plain_price(text)):
            kind = "unknown"
    facts = {"name": f"- 이름: {store.name}", "industry": f"- 업종: {store.business_type_name}",
             "area": f"- 상권: {store.area_name}" if store.area_name else None,
             "menu": f"- 메뉴: {', '.join(menu)}" if menu else None}

    def rest(*skip: str) -> list[str]:
        return [line for key, line in facts.items() if key not in skip and line]

    def menu_lines(with_price: bool = True) -> list[str]:
        return [f"- {name} {prices[name]:,}원" if with_price and isinstance(prices.get(name), int) else f"- {name}" for name in menu]

    if kind == "name":
        lines = [f"우리 가게 이름은 '{store.name}'{_ieyo(store.name)}.", *rest("name")]
    elif kind == "industry":
        lines = [f"우리 가게 업종은 {store.business_type_name}{_ieyo(store.business_type_name)}.", *rest("industry")]
    elif kind == "area":
        where = f"우리 가게는 {store.area_name} 상권에 있어요." if store.area_name else "우리 가게 상권 정보는 이 화면에 없어요."
        lines = [("정확한 주소는 이 화면에 없어요. " if "주소" in text else "") + where, *rest("area")]
    elif kind in ("menu", "price", "menu_sales"):
        if not menu:
            lines = ["메뉴 정보는 이 화면에 없어요.", *rest("menu")]
        elif kind == "menu_sales":
            lines = ["이 화면에는 메뉴별 매출·판매량 정보가 없어요. 우리 가게 메뉴는 아래와 같아요.", *menu_lines(False),
                     "참고: 상권·업종 전체의 추정매출은 '우리 가게 상권 매출은 어때?'처럼 물어보면 알려 드려요."]
            return _store_reply(lines, "store_profile", kind, notes=(STORE_NOTE,))
        elif kind == "price" and not any(isinstance(prices.get(name), int) for name in menu):
            lines = ["메뉴 가격은 이 화면에 없어요. 우리 가게 메뉴는 아래와 같아요.", *menu_lines(False)]
        else:
            lines = [f"우리 가게 메뉴는 {len(menu)}가지예요.", *menu_lines()]
    elif kind == "unknown":
        lines = [f"{NOT_ON_SCREEN} 지금 아는 가게 정보는 아래와 같아요.", *rest()]
    else:      # profile
        lines = ["우리 가게 기본 정보예요.", *rest()]
    return _store_reply([*lines, GUIDE_LINE], "store_profile", kind, notes=(STORE_NOTE,))


# ── 프록시 ─────────────────────────────────────────────────────────────
class AssistantProxy:
    def __init__(self, client: MarketClient | None, *, store_id: str = "store_ongi", config_error: str | None = None):
        self.market = client                 # None 이면 이 서버에서 상권 비서를 끈 것
        self.config_error = config_error     # 주소 설정이 틀렸을 때의 안내 (off 가 아니라 error 로 보인다)
        self.store_id = store_id
        self.defaults = STORE_DEFAULTS.get(store_id)
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT)
        # setup 이 실제로 맞춘 우리 가게 조건 (상권 코드, 업종 코드, 분기). 정해 둔 분기·상권이 자료에 없어 다른 것으로 맞췄을 때도
        # '우리 가게 기본 조건'을 알아보려고 기억한다. 자료가 같으면 모든 방문자에게 같은 값이라 서버에 하나만 둔다
        self.home: tuple[str, str, str] | None = None
        self.read_store: Callable[[], StoreProfile] | None = None      # 가게 프로필을 읽는 함수 (attach_store 가 넣는다)
        self.demo = None                                               # 지금 가게의 Demo (전 파트 질문의 현황 1~2줄, attach_store)

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

    def for_store(self, store_id: str) -> "AssistantProxy":
        """다른 가게의 프록시 (얕은 사본: 같은 상권 서비스 연결·동시 요청 한도). 기본 조건과 가게 프로필만 그 가게 것."""
        view = copy.copy(self)
        view.store_id = store_id
        view.defaults = STORE_DEFAULTS.get(store_id)
        view.home = None
        view.read_store = None
        view.demo = None
        view.marketing = None
        return view

    @property
    def defaults(self) -> SetupDefaults | None:
        """우리 가게 기본 조건. 예시 세 곳은 정해 둔 값, 직접 등록한 가게(11/20)는 등록한 값(고치면 바로 따라감)."""
        fixed = self.__dict__.get("_defaults")
        if fixed is not None:
            return fixed
        return registered_defaults(self.__dict__.get("store_id"))

    @defaults.setter
    def defaults(self, value: SetupDefaults | None) -> None:
        self._defaults = value

    def attach_store(self, demo) -> None:
        """가게 기본 질문에 답할 때 가게 프로필을 읽을 곳을 붙인다 (create_app 이 부른다).
        Demo 가 ③ 생성에 쓰는 것과 같은 값이다: 리뷰 분석 서비스의 가게 정보 + 상권 지표 파일의 상권 이름.
        질문이 올 때마다 가게 정보만 새로 읽는다 (리뷰·분석은 읽지 않는다)."""
        def read() -> StoreProfile:
            snapshots = load_snapshots(demo.s.snapshot_path)
            return to_store_profile(demo.source.store(demo.s.store_id), snapshots[0].area_name if snapshots else None)
        self.read_store = read
        self.demo = demo

    def _store_profile(self) -> StoreProfile | None:
        """가게 프로필. 리뷰 분석 서비스가 꺼져 있거나 값이 이상하면 None (서랍에는 '불러오지 못했어요'로 답한다)."""
        if self.read_store is None:
            return None
        try:
            return self.read_store()
        except Exception as exc:
            log.warning("가게 프로필을 읽지 못함 (%s)", exc.__class__.__name__)
            return None

    # 화면에 넘기기 전에 ------------------------------------------------------
    def _is_home(self, conditions: dict) -> bool | None:
        """지금 조건이 우리 가게 기본 조건과 같은지 (상권·업종·분기 코드로 비교). 기본 조건이 없는 가게이거나 코드가 없으면 None(모름)."""
        key = tuple(conditions.get(name) for name in ("area_code", "industry_code", "period"))
        defaults = self.defaults
        if defaults is None or not all(isinstance(value, str) and value for value in key):
            return None
        wanted = (defaults.area_code, defaults.industry_code, defaults.period)
        return key == wanted or key == self.home

    def _conditions(self, conditions: Any) -> Any:
        """분석 조건: 분기 이름을 '2026년 2분기' 모양으로 맞추고(이름이 없으면 코드로 만든다) is_store_default 를 더한다."""
        if not isinstance(conditions, dict):
            return conditions
        out = dict(conditions)
        label = conditions.get("period_label") or conditions.get("period")
        if isinstance(label, str) and label:
            out["period_label"] = period_words(label)
        out["is_store_default"] = self._is_home(conditions)
        return out

    def _present(self, data: Any) -> Any:
        """상권 서비스 응답(답·대화·조건)의 보이는 글자를 손본 사본. 모르는 칸과 상권 서비스로 되돌아가는 값은 그대로 둔다."""
        return _reworded(data, {"reply": _reply_words, "cards": _each(_card_words), "conditions": self._conditions,
                                "turns": _each(self._present)})

    # 상태 ----------------------------------------------------------------
    def _unavailable(self) -> MarketError | None:
        if self.config_error:
            return MarketError("error", self.config_error)
        if self.market is None:
            return MarketError("off", MESSAGES["off"])
        return None

    def status(self) -> dict:
        defaults = self.defaults
        setup = {"label": defaults.label if defaults else None}
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

    def _setup_result(self, status: str, state: str, message: str | None, conditions: dict | None) -> dict:
        return {"status": status, "state": state, "message": message, "conditions": self._conditions(conditions)}

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
            location = location_body(call, wanted)
            if location is None:          # 주소로 등록한 가게인데 상권 서비스의 주소 검색이 맞는 후보를 못 줌 (11/20)
                return self._setup_result("unavailable", "error", ADDRESS_MISS, None), session["token"]
            state = call("POST", "/api/onboarding/profile", {
                "location": location, "industry_code": wanted.industry_code,
                "business_status": wanted.business_status, "expected_revision": state.get("revision")})
        elif not (same_location(profile["location"], wanted)
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
        self.home = (chosen["area_code"], wanted.industry_code, period)      # 방금 맞춘 것이 이 자료에서의 우리 가게 기본 조건
        return self._setup_result("ok", "ready", None, conditions()), session["token"]

    # 질문·선택지·대화 -----------------------------------------------------------
    def forward(self, method: str, path: str, token: str | None, body: dict | None = None) -> tuple[Any, str | None]:
        problem = self._unavailable()
        if problem is not None:
            raise problem
        up = self.market.request(method, path, token, body)
        return self._present(up.data), up.token or token

    def message(self, token: str | None, body: dict, visitor: str | None = None) -> tuple[Any, str | None]:
        """질문 1개. 가게 자체를 묻는 질문과 고객응대·마케팅·리포트 질문은 여기서 답하고(상권 서비스를 부르지 않는다),
        나머지(상권 질문)는 상권 서비스로 넘긴다. 상권 답에는 '상권 분석 표·차트 보기' 버튼을 붙인다."""
        text = body.get("text") or ""
        kind = store_question(text)
        if kind is not None:
            problem = self._unavailable()
            if problem is not None:
                raise problem
            return store_answer(kind, body["text"], None if kind == "where" else self._store_profile()), token
        domain = domain_question(text)
        if domain is not None:          # 상권 서비스가 꺼져 있어도 답한다 (가게의 리뷰·마케팅 현황은 이 서버가 안다)
            return self.domain_answer(domain, text, visitor), token
        problem = self._unavailable()
        if problem is not None:
            raise problem
        data, token_out = self.forward("POST", "/api/assistant/messages", token, body)
        reply = data.get("reply") if isinstance(data, dict) else None
        if isinstance(reply, dict) and reply.get("kind") in ("data_answer", "opinion", "summary") and isinstance(reply.get("actions"), list):
            reply["actions"] = [*reply["actions"], nav("상권 분석 표·차트 보기", "market")]
        return data, token_out

    # 전 파트 질문 ---------------------------------------------------------------
    def _briefing(self, visitor: str | None) -> dict | None:
        if self.demo is None:
            return None
        try:
            return self.demo.briefing(visitor)
        except Exception as exc:          # 리뷰 분석 서비스가 꺼져 있어도 버튼은 준다
            log.warning("서랍 현황: 브리핑을 읽지 못함 (%s)", exc.__class__.__name__)
            return None

    def _shop(self) -> str:
        defaults = self.defaults
        label = defaults.label if defaults else ""
        return label.split(" · ")[0] if label else "우리 가게"

    def domain_answer(self, domain: str, text: str, visitor: str | None = None) -> dict:
        shop = self._shop()
        if domain == "help":            # 아무것도 조회하지 않는다 (상권 숫자·리뷰 현황을 먼저 꺼내지 않음)
            return _domain_reply([HELP_TEXT], "help_guide", "general",
                                 [nav("추천 카드 보기", "cards"), nav("맞춤 마케팅 열기", "marketing", "promo"),
                                  nav("리뷰 분석 열기", "analysis", "summary"), nav("상권 분석 표·차트 보기", "market")],
                                 list(HELP_SUGGESTIONS))
        if domain == "cards":
            return _domain_reply(self._cards_status(visitor, shop), "cards_guide", "customer",
                                 [nav("추천 카드 보기", "cards"), nav("승인할 글 보기", "draft"),
                                  nav("맞춤 마케팅 열기", "marketing", "promo")],
                                 list(CARDS_SUGGESTIONS))
        c = re.sub(r"[^0-9a-z가-힣]", "", (text or "").lower())
        b = self._briefing(visitor)
        counts = (b or {}).get("counts") or {}
        top = next((g for g in (b or {}).get("groups", []) if g.get("issue_id") == (b or {}).get("top_issue_id")), None)
        if counts:
            status = f"{shop}: 리뷰 {counts.get('review_count', 0)}건 중 불만 {counts.get('complaint_count', 0)}건이에요."
            if top:
                band = f", {top['main_time_band']}에 몰렸어요" if top.get("main_time_band") else ""
                status += f" 가장 많은 불만은 '{top['topic_name']}' {top['review_count']}건{band}."
        else:
            status = f"{shop}의 리뷰 현황을 지금 불러오지 못했어요."
        if domain == "care" and "문의" in c:     # 손님 문의는 통합 화면에 없는 기능 (리뷰 분석 서비스를 부르지 않고 바로 알린다)
            return self._no_inquiry()
        if domain == "care" and not _CARE_WRITE.search(c):
            answered = self._care_ask(text, visitor)
            if answered is not None:
                return answered
        if domain == "care":
            if any(w in c for w in ("억울", "진상", "테러", "악플", "블랙컨슈머")):
                tip = ("가게 잘못이 아닌 별점에는 사과 없이 사실과 가게 원칙을 담담하게 쓰는 답글이 좋아요. "
                       "추천 카드에서 답글을 만들면 억울한 리뷰는 설명하는 답글로 나와요.")
            elif any(w in c for w in ("캡처", "캡쳐")):
                tip = "리뷰 분석의 '리뷰 붙여넣기' 탭에서 배달앱 리뷰 캡처를 올리면 글자와 별점을 읽어 와요. 저장하기 전에 한 번 확인해 주세요."
            else:
                tip = "추천 카드에서 답글과 포장·주문 안내문을 바로 만들고, 고쳐서 승인할 수 있어요."
            return _domain_reply([status, tip], "care_guide", "customer",
                                 [nav("추천 카드에서 답글·안내문 만들기", "cards"), nav("리뷰 캡처·붙여넣기 열기", "analysis", "paste"),
                                  nav("불만 묶음 보기", "analysis", "issues")],
                                 ["억울한 별점 답글은 어떻게 달아?", "불만 리뷰 제일 많은 게 뭐야?", *BACK_TO_MARKET[:1]])
        if domain == "marketing" and not _CARE_WRITE.search(c):
            answered = self._marketing_ask(text, visitor)
            if answered is not None:
                return answered
        if domain == "marketing":
            sub = marketing_sub(text)
            # 질문에 대한 안내가 먼저, 가게 현황은 그다음 (11/21: 남은 재료를 물었는데 칭찬 메뉴 문장이 먼저 나왔다)
            if any(w in c for w in ("본전", "할인", "쿠폰")) and sub in ("promo", "repeat"):
                lines = ["쿠폰 할인액·장수에 따른 본전 주문 수는 맞춤 마케팅이 메뉴 가격으로 계산해 드려요 (맞춤 홍보 제안의 재주문 쿠폰, "
                         "쿠폰 결과 확인)."]
            else:
                lines = [f"맞춤 마케팅의 '{MKT_SUBS[sub]}'에서 몇 가지 질문에 답하면 계산과 글을 만들어 드려요."]
            # 칭찬 메뉴·저녁 매출 문장과 '추천 카드 ⓑ' 버튼은 오늘 쿠폰 홍보 카드(ⓑ)가 있는 가게에서만. 그 문장은 카드 ⓑ 의 근거라
            # 쿠폰·홍보 질문에만 붙인다 (11/21: 카드가 없는 새 가게에도 버튼이 나왔고, 남은 재료 질문에도 칭찬 메뉴 문장이 붙었다)
            coupon = self._has_coupon_card(visitor)
            if coupon and sub in ("promo", "repeat"):
                status = self._marketing_status(visitor, shop)
                if status:
                    lines.append(status)
            approved = self._marketing_approved(visitor)
            if approved:
                lines.append(approved)
            actions = [nav(f"맞춤 마케팅: {MKT_SUBS[sub]}", "marketing", sub)]
            if sub != "promo":
                actions.append(nav("맞춤 마케팅: 맞춤 홍보 제안", "marketing", "promo"))
            if coupon:
                actions.append(nav("추천 카드 ⓑ 쿠폰 홍보글 보기", "cards"))
            return _domain_reply(lines, "marketing_guide", "marketing", actions,
                                 ["남은 재료 묶어서 팔고 싶어", "배달앱 광고비 괜찮은지 봐줘", "쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?"])
        tip = "종합 리포트에서 오늘 요약·응대 점수·손님 칭찬 요약·월간 보고서·상권·마케팅 요약을 한 번에 보고 PDF로 저장할 수 있어요."
        return _domain_reply([status, tip], "report_guide", "report", [nav("종합 리포트·PDF 저장 열기", "report")],
                             ["불만 리뷰 제일 많은 게 뭐야?", *BACK_TO_MARKET[:1]])

    def attach_marketing(self, marketing) -> None:
        """마케팅 질문을 물을 곳 (marketing_proxy.MarketingProxy, 그 가게 것). create_app·StoreHub 가 붙인다 (11/21)."""
        self.marketing = marketing

    def _marketing_ask(self, text: str, visitor: str | None) -> dict | None:
        """마케팅 질문을 맞춤 마케팅 서비스(POST /api/marketing-survey/ask)에 묻는다 (11/21). 고객응대(_care_ask)와 같은 모양.
        못 물으면 None (예전 안내로 답함)."""
        proxy = getattr(self, "marketing", None)
        ask = getattr(proxy, "ask", None)
        if ask is None:
            return None
        try:
            got = ask(visitor, text)
        except Exception as exc:              # 꺼져 있음·느림·예전 판(/ask 없음) → 예전 안내
            log.warning("서랍 마케팅 답: 맞춤 마케팅 서비스에 묻지 못함 (%s)", exc.__class__.__name__)
            return None
        return self._service_reply(got, "marketing_answer", "marketing", MKT_ACTIONS, MKT_ANSWER)

    def _service_reply(self, got, kind: str, domain: str, table: dict, answered_by: str) -> dict | None:
        """질문 답하기 서비스(리뷰 분석·맞춤 마케팅)의 답 → 서랍 답 모양(assistant-reply-v1). 모양이 틀리면 None."""
        if not isinstance(got, dict) or not isinstance(got.get("text"), str) or not got["text"].strip():
            return None
        cards = [c for c in got.get("cards") or [] if isinstance(c, dict) and isinstance(c.get("id"), str)]
        ids = {c["id"] for c in cards}
        intent = str(got.get("intent") or "overview")
        actions = [nav(label, route, sub) for label, route, sub in table.get(intent, table["overview"])]
        more = [q for q in got.get("suggestions") or [] if isinstance(q, str)][:2]
        hcx = got.get("method") == "hcx"
        return {"schema_version": REPLY_SCHEMA,
                "reply": {"text": got["text"].strip(), "kind": kind,
                          "cited": sorted(set(re.findall(r"\[(F\d+)\]", got["text"])) & ids),
                          "actions": actions, "notes": [n for n in got.get("notes") or [] if isinstance(n, str)],
                          "suggestions": [*more, BACK_TO_MARKET[0]]},
                "model_used": hcx, "cards": cards, "topics": [],
                "classification": {"domain": "customer" if domain == "care" else domain, "turn_type": intent, "topics": [],
                                   "needs_user_choice": False, "needs_model": hcx,
                                   "analyzer": f"{answered_by}+{got.get('classified_by') or 'rules'}"},
                "pending": None, "answered_by": answered_by}

    @staticmethod
    def _no_inquiry() -> dict:
        return _domain_reply([NO_INQUIRY], "care_no_inquiry", "customer",
                             [nav("리뷰 분석 열기", "analysis", "summary"), nav("불만 묶음 보기", "analysis", "issues")],
                             ["불만 리뷰 제일 많은 게 뭐야?", "답글 안 단 리뷰 몇 개야?", BACK_TO_MARKET[0]])

    def _care_ask(self, text: str, visitor: str | None) -> dict | None:
        """고객응대 질문을 리뷰 분석 서비스(POST /api/review-insight/ask)에 묻는다 (11/21). 상권 비서처럼 질문 종류마다 이 가게
        리뷰로 센 근거 카드(F1…)와 답을 받아 서랍 답 모양(assistant-reply-v1)으로 바꾼다. 못 물으면 None (예전 안내로 답함)."""
        ask = getattr(self.demo._src(visitor), "ask", None) if self.demo is not None else None
        if ask is None:
            return None
        try:
            got = ask(self.demo.s.store_id, text)
        except Exception as exc:              # 리뷰 분석 서비스가 꺼져 있거나 예전 버전(/ask 없음)이면 예전 안내
            log.warning("서랍 고객응대 답: 리뷰 분석 서비스에 묻지 못함 (%s)", exc.__class__.__name__)
            return None
        if isinstance(got, dict) and got.get("intent") == "inquiry":     # 통합 화면에는 손님 문의 기능이 아직 없다 (11/21)
            return self._no_inquiry()
        return self._service_reply(got, "care_answer", "care", CARE_ACTIONS, CARE_ANSWER)

    def _has_coupon_card(self, visitor: str | None) -> bool:
        """오늘 추천 카드에 쿠폰 홍보 카드(ⓑ, kind promo)가 있는지. 규칙만으로 계획한다(HCX 를 부르지 않음, _cards_status 와 같은 호출).
        읽지 못하면 False: 없는 카드로 가는 버튼을 주지 않는다."""
        if self.demo is None:
            return False
        try:
            from .cards import plan_cards
            st = self.demo._state(visitor)
            store, reviews = self.demo._contract_inputs(st)
            plans = plan_cards(st["insight"], st["snapshots"], self.demo.s.store_id, preferred_id=self.demo.s.card_b_snapshot_id,
                               threshold=self.demo.s.card_b_threshold, store=store, reviews=reviews)
        except Exception as exc:
            log.warning("서랍 현황: 추천 카드를 읽지 못함 (%s)", exc.__class__.__name__)
            return False
        return any(getattr(getattr(p, "card", None), "kind", None) == "promo" for p in plans)

    def _marketing_status(self, visitor: str | None, shop: str) -> str | None:
        """칭찬 인기 메뉴(shared.praise, 카드 ⓑ 와 같은 함수)와 상권 저녁 매출 지표 한 줄. 둘 다 못 읽으면 None."""
        if self.demo is None:
            return None
        parts = []
        try:
            from .cards import praised_coupon_menu
            st = self.demo._state(visitor)
            store, reviews = self.demo._contract_inputs(st)
            found = praised_coupon_menu(store, reviews)
            if found:
                parts.append(f"손님 칭찬 리뷰에 '{found['menu']}' 언급이 {found['count']}건 있어요.")
            from .cards import pick_card_b_snapshot, short_metric
            s = pick_card_b_snapshot(st["snapshots"])          # 카드 ⓑ 가 쓰는 지표와 같은 것
            if s is not None and s.value is not None:
                way = "줄었어요" if s.value < 0 else "늘었어요"
                # 지표 이름에 시간대·업종 범위가 들어 있다 (예: 저녁 시간대(17~24시) 추정매출(두 분기 공통 업종))
                parts.append(f"{short_metric(s.metric_name)}은 전년 같은 분기보다 {abs(s.value):.2f}% {way} ({s.area_name}).")
        except Exception as exc:
            log.warning("서랍 현황: 마케팅 현황을 읽지 못함 (%s)", exc.__class__.__name__)
        return " ".join(parts) or None

    def _marketing_approved(self, visitor: str | None) -> str | None:
        """맞춤 마케팅에서 승인한 글 건수 한 줄 (11/20). 없거나 못 읽으면 None.
        승인 목록(list_approvals)에는 card_id·kind 가 없어 draft_id 가 'mkt-' 로 시작하는 것으로 센다 (marketing_proxy.take_approvals,
        화면 state/boot.js 의 staffApprovals 와 같은 규칙). 가장 최근 글의 종류는 저장소의 details 에서 읽고, 못 읽으면 괄호를 뺀다."""
        if self.demo is None:
            return None
        try:
            rows = [r for r in self.demo.list_approvals(visitor)
                    if r.get("card_id") == "marketing" or str(r.get("draft_id") or "").startswith("mkt-")]
        except Exception as exc:
            log.warning("서랍 현황: 승인 기록을 읽지 못함 (%s)", exc.__class__.__name__)
            return None
        if not rows:
            return None
        kind = None
        try:
            from shared.storage import clean_visitor_id
            mine = {r["draft_id"] for r in rows}
            details = self.demo.storage.approvals.details(self.demo.s.store_id, clean_visitor_id(visitor))
            last = [d for d in details if d.get("draft_id") in mine and (d.get("card_id") == "marketing" or d["draft_id"].startswith("mkt-"))]
            if last and isinstance(last[-1].get("kind"), str) and last[-1]["kind"].strip():
                kind = last[-1]["kind"].strip()
        except Exception as exc:
            log.warning("서랍 현황: 승인한 글 종류를 읽지 못함 (%s)", exc.__class__.__name__)
        return f"맞춤 마케팅에서 승인한 글 {len(rows)}건" + (f"({kind})" if kind else "") + "이 있어요."

    def _cards_status(self, visitor: str | None, shop: str) -> list[str]:
        """오늘 추천 카드 개수·제목 (11/20). 규칙만으로 계획을 세운다(plan_cards 에 writer 를 주지 않음): live 에서도 HCX 를 부르지 않는다.
        만든 초안·승인 대기 수는 브라우저에만 있어 이 서버가 모른다 → 숫자를 지어내지 않고 화면으로 안내한다."""
        guide = f"추천 카드에서 카드를 고르면 글 초안이 '{SCREENS['drafts']}'에 나오고, 승인한 글은 '{SCREENS['done']}'에 모여요."
        if self.demo is None:
            return [f"{shop}의 오늘 추천 카드를 지금 불러오지 못했어요.", guide]
        try:
            from .cards import plan_cards
            st = self.demo._state(visitor)
            store, reviews = self.demo._contract_inputs(st)
            plans = plan_cards(st["insight"], st["snapshots"], self.demo.s.store_id, preferred_id=self.demo.s.card_b_snapshot_id,
                               threshold=self.demo.s.card_b_threshold, store=store, reviews=reviews)
        except Exception as exc:
            log.warning("서랍 현황: 추천 카드를 읽지 못함 (%s)", exc.__class__.__name__)
            return [f"{shop}의 오늘 추천 카드를 지금 불러오지 못했어요.", guide]
        if not plans:
            return [f"{shop}: 오늘은 추천 카드가 없어요. 리뷰 분석과 맞춤 마케팅에서 할 일을 찾아볼 수 있어요."]
        return [f"{shop}: 오늘 추천 카드는 {len(plans)}장이에요.", *[f"- {p.title}" for p in plans], guide]


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


def create_assistant_router(proxy: AssistantProxy, proxy_of: Callable[[Request], AssistantProxy] | None = None) -> APIRouter:
    """proxy_of(요청) 이 있으면 요청마다 그 가게의 프록시를 쓴다 (로그인한 사장님이 고른 가게, 5차 회의 11/18). 없으면 proxy 하나."""
    router = APIRouter(prefix="/api/assistant")
    pick = proxy_of or (lambda request: proxy)

    def guarded(request: Request, work: Callable[[AssistantProxy, str | None], tuple[Any, str | None]]) -> JSONResponse:
        """work(프록시, 세션 값) → (응답 본문, 새 세션 값). 상권 서비스 문제와 예상 못한 오류 모두 서랍용 오류 응답이 된다. 500 은 없다."""
        proxy = pick(request)
        token, secure = _token(request), _secure(request)
        if not proxy.slots.acquire(timeout=1.0):
            return _fail(MarketError("error", BUSY_MESSAGE), token, secure)
        try:
            data, token_out = work(proxy, token)
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
            return _ok(pick(request).status(), _token(request), _secure(request))
        except Exception as exc:     # status 는 어떤 경우에도 200
            log.exception("상권 비서 status 오류 (%s)", exc.__class__.__name__)
            return _ok({"state": "error", "message": MESSAGES["error"], "setup": {"label": None}}, None, False)

    @router.post("/setup")
    def setup(request: Request, force: bool = False):
        proxy = pick(request)
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
        visitor = getattr(request.state, "visitor_id", None)
        return guarded(request, lambda proxy, token: proxy.message(token, body.model_dump(exclude_none=True), visitor))

    @router.post("/actions")
    def actions(body: ActionIn, request: Request):
        return guarded(request, lambda proxy, token: proxy.forward("POST", "/api/assistant/actions", token,
                                                                   body.model_dump(exclude_none=True)))

    @router.get("/conversation")
    def conversation(request: Request):
        return guarded(request, lambda proxy, token: proxy.forward("GET", "/api/assistant/conversation", token))

    @router.delete("/conversation")
    def clear(request: Request):
        return guarded(request, lambda proxy, token: proxy.forward("DELETE", "/api/assistant/conversation", token))

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
