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


# ── 분기 표기 ───────────────────────────────────────────────────────────
# 상권 서비스의 분기 코드는 '20262'(2026년 2분기)다. 조건에 분기 이름(period_label)이 빠지면 이 코드가 답 문장에 그대로 들어온다
# ("20262 자료로 볼게요"). 화면에 넘기기 전에 '2026년 2분기'로 바꾼다 (cards.quarter_words 의 '2026Q2' → '2026년 2분기'와 같은 모양).
# 금액·개수는 건드리지 않는다: 앞뒤에 숫자·영문·쉼표·점이 붙었거나(120262, 20,262, 20262.5) 바로 뒤에 단위가 오면(20262원) 그대로 둔다.
# 화면(app.js 의 CHAT_QUARTER)도 같은 정규식을 쓴다. 시험이 두 곳의 정규식이 글자 그대로 같은지 확인한다.
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
# 화면 메뉴 이름. static/index.html 의 메뉴 글자와 같아야 한다 (시험이 확인)
SCREENS = {"reviews": "리뷰 분석", "cards": "추천 카드", "drafts": "승인할 글", "done": "처리 완료", "marketing": "맞춤 마케팅",
           "report": "종합 리포트"}
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


def store_question(text: str) -> str | None:
    """가게 자체를 묻는 질문이면 그 종류를, 아니면(상권 질문·모르는 말) None 을 돌려준다. None 이면 상권 서비스로 보낸다.

    종류: where(화면 위치) · name · industry · area · menu · price · profile(기본 정보) · unknown(프로필에 없는 것) · menu_sales(메뉴별 매출)
    순서
      ① 우리 가게 메뉴별 매출 (상권 범위 낱말이 없을 때만)
      ② 상권 낱말(_MARKET_WORDS)이 하나라도 있으면 상권 서비스. 하나뿐인 낱말이 '상권'이고 가게의 상권 이름을 묻는 모양일 때만 area
      ③ 화면 위치: 화면에 있는 것(리뷰·답글·공지…) + 어디서 보는지
      ④ 가게 정보: '우리 가게…'·'가게…'로 시작하고, 낱말 바로 뒤에 묻는 말이 올 때만. 일을 시키는 말(써줘·바꿔…)과 고민을 묻는 말(…할까?)은 뺀다
    공백·기호를 뺀 글자가 40자를 넘는 글은 여기서 답하지 않는다.
    """
    c = re.sub(r"[^0-9a-z가-힣]", "", (text or "").lower())
    if not c or len(c) > MAX_STORE_QUESTION:
        return None

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


def _ieyo(word: str) -> str:
    """'한식음식점' 뒤에는 '이에요', '카페' 뒤에는 '예요' (마지막 한글 글자의 받침으로 고른다)."""
    last = next((ch for ch in reversed(word) if "가" <= ch <= "힣"), None)
    return "예요" if last is not None and (ord(last) - 0xAC00) % 28 == 0 else "이에요"


def _store_reply(lines: list[str], kind: str, turn: str, *, notes: tuple[str, ...] = ()) -> dict:
    """상권 서비스가 messages 에 주는 것과 같은 칸 (assistant/flow.py 의 _finish. debug 는 원래 화면에 오지 않는다).
    conditions 는 싣지 않는다: 가게 질문은 분석 조건을 바꾸지 않으니 화면의 조건 줄이 그대로 남는다."""
    return {"schema_version": REPLY_SCHEMA,
            "reply": {"text": "\n".join(lines), "kind": kind, "cited": [], "actions": [], "notes": list(notes),
                      "suggestions": list(BACK_TO_MARKET)},
            "model_used": False, "cards": [], "topics": [],
            "classification": {"domain": "store", "turn_type": turn, "topics": [], "needs_user_choice": False,
                               "needs_model": False, "analyzer": "web_proxy"},
            "pending": None, "answered_by": STORE_ANSWER}


def _where_answer(text: str) -> dict:
    c = re.sub(r"\s", "", text)
    drafts = (f"초안은 화면 메뉴 '{SCREENS['cards']}'에서 카드를 고르면 '{SCREENS['drafts']}'에 나와요. "
              f"승인한 글은 '{SCREENS['done']}'에 모여요.")
    if "답글" in c or "댓글" in c:
        first = "리뷰 답글 " + drafts
    elif "공지" in c or "안내문" in c:
        first = "포장·주문 안내문 " + drafts
    elif "홍보" in c or "쿠폰" in c or "마케팅" in c or "광고" in c:
        # 맞춤 마케팅(설문으로 홍보 제안·쿠폰 손익·광고비 점검)이 먼저, 오늘 추천된 쿠폰 홍보글은 추천 카드에서
        first = (f"홍보·쿠폰·광고비는 화면 메뉴 '{SCREENS['marketing']}'에서 몇 가지 질문에 답하면 제안과 글을 만들어 드려요. "
                 f"오늘 추천된 쿠폰 홍보글은 '{SCREENS['cards']}'에서 카드를 고르면 '{SCREENS['drafts']}'에 나와요.")
    elif "초안" in c or "승인" in c or "추천카드" in c or "처리완료" in c:
        first = "글 " + drafts
    elif "리포트" in c or "보고서" in c or "응대점수" in c:
        first = f"응대 점수와 월간 보고서는 화면 메뉴 '{SCREENS['report']}'에 있어요."
    else:
        first = f"리뷰와 불만 묶음은 화면 메뉴 '{SCREENS['reviews']}'에서 볼 수 있어요."
    return _store_reply([first,
                         f"- 리뷰·불만 묶음: '{SCREENS['reviews']}'",
                         f"- 답글·안내문·홍보 글 초안: '{SCREENS['cards']}' → '{SCREENS['drafts']}'",
                         f"- 맞춤 홍보 제안·광고비 점검·마케팅 보고서: '{SCREENS['marketing']}'",
                         f"- 승인한 글: '{SCREENS['done']}'",
                         f"- 응대 점수·월간 보고서: '{SCREENS['report']}'",
                         "참고: 이 채팅은 동네 상권·업종 매출 상담이라 리뷰 내용은 여기서 답하지 않아요."], "store_guide", "where")


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
        c = re.sub(r"\s", "", text)
        if not ("메뉴" in c or "가격표" in c or any(name.replace(" ", "") in c or name.split()[0] in c for name in menu)):
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
        self.defaults = STORE_DEFAULTS.get(store_id)
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT)
        # setup 이 실제로 맞춘 우리 가게 조건 (상권 코드, 업종 코드, 분기). 정해 둔 분기·상권이 자료에 없어 다른 것으로 맞췄을 때도
        # '우리 가게 기본 조건'을 알아보려고 기억한다. 자료가 같으면 모든 방문자에게 같은 값이라 서버에 하나만 둔다
        self.home: tuple[str, str, str] | None = None
        self.read_store: Callable[[], StoreProfile] | None = None      # 가게 프로필을 읽는 함수 (attach_store 가 넣는다)

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
        view.defaults = STORE_DEFAULTS.get(store_id)
        view.home = None
        view.read_store = None
        return view

    def attach_store(self, demo) -> None:
        """가게 기본 질문에 답할 때 가게 프로필을 읽을 곳을 붙인다 (create_app 이 부른다).
        Demo 가 ③ 생성에 쓰는 것과 같은 값이다: 리뷰 분석 서비스의 가게 정보 + 상권 지표 파일의 상권 이름.
        질문이 올 때마다 가게 정보만 새로 읽는다 (리뷰·분석은 읽지 않는다)."""
        def read() -> StoreProfile:
            snapshots = load_snapshots(demo.s.snapshot_path)
            return to_store_profile(demo.source.store(demo.s.store_id), snapshots[0].area_name if snapshots else None)
        self.read_store = read

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
        if self.defaults is None or not all(isinstance(value, str) and value for value in key):
            return None
        wanted = (self.defaults.area_code, self.defaults.industry_code, self.defaults.period)
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
        self.home = (chosen["area_code"], wanted.industry_code, period)      # 방금 맞춘 것이 이 자료에서의 우리 가게 기본 조건
        return self._setup_result("ok", "ready", None, conditions()), session["token"]

    # 질문·선택지·대화 -----------------------------------------------------------
    def forward(self, method: str, path: str, token: str | None, body: dict | None = None) -> tuple[Any, str | None]:
        problem = self._unavailable()
        if problem is not None:
            raise problem
        up = self.market.request(method, path, token, body)
        return self._present(up.data), up.token or token

    def message(self, token: str | None, body: dict) -> tuple[Any, str | None]:
        """질문 1개. 가게 자체를 묻는 질문은 여기서 답하고(상권 서비스를 부르지 않는다) 나머지는 상권 서비스로 넘긴다."""
        problem = self._unavailable()
        if problem is not None:
            raise problem
        kind = store_question(body.get("text") or "")
        if kind is None:
            return self.forward("POST", "/api/assistant/messages", token, body)
        return store_answer(kind, body["text"], None if kind == "where" else self._store_profile()), token


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
        return guarded(request, lambda proxy, token: proxy.message(token, body.model_dump(exclude_none=True)))

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
