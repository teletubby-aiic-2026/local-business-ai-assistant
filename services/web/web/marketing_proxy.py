"""맞춤 마케팅 프록시 — 통합 화면의 '맞춤 마케팅'(#/marketing)이 마케팅 서비스(experiments/marketing 의 marketing_survey,
기본 127.0.0.1:8030)를 쓰는 길. 고객응대 프록시(care_proxy.py)·상권 비서 프록시(assistant_proxy.py)와 같은 규칙으로 만들었다.

브라우저는 이 서버(같은 출처)의 /api/marketing-survey/* 만 부른다. 경로 이름은 마케팅 서비스와 같고, 이 서버가 대신 부른다.

| 메서드 | 경로 (/api/marketing-survey/ 뒤) | 기다리는 시간 | 하는 일 |
|--------|----------------------------------|---------------|---------|
| GET    | health                           | 3초           | 쓸 수 있는지. 항상 200 (ready·off·down·error) + 서비스가 준 mode·key_present·demo·notes |
| GET    | meta                             | 10초          | 마케팅 서비스가 아는 우리 가게 이름 |
| POST   | step                             | 10초          | 질문 하나 진행 (선택지·입력칸·예시 문구) |
| POST   | result                           | 10초          | 결정 + 설명 3줄 (지금 화면은 쓰지 않음, 김수현 님 서버에 있어 열어 둠) |
| POST   | plan                             | 45초          | 결과 카드: 판단 근거·숫자·할 일·글. 글은 HCX 로 만든다 (키가 없으면 저장본) |
| POST   | generate                         | 45초          | '이 조건으로 쿠폰 글 만들기' (HCX) |
| POST   | next-idea                        | 10초          | 다른 아이디어 보기 |
| POST   | idea-try                         | 45초          | 질문이 필요한 아이디어 해 보기. 지금은 코드 틀 글이지만 아이디어 글 생성 자리라 길게 둔다 |
| POST   | coupon-calc                      | 10초          | 쿠폰 슬라이더 계산 (장수·최대 비용·본전 주문 수) |
| POST   | approve                          | 10초          | 승인. 성공하면 이 서버의 방문자 승인 기록에도 남긴다 (아래) |
| POST   | notice-followup                  | 10초          | 공지 2주 뒤 개선 소식 (코드 틀) |
| GET    | report?period=weekly|monthly      | 10초          | 마케팅 보고서 (기록이 없으면 데모 기록, demo: true) |

- 위 표 밖은 404 (서비스에 보내지 않음). 여러 가게 목록(stores)은 통합 화면이 가게 하나라 열지 않는다. 기록 지우기
  (DELETE records)는 화면이 직접 부르지 않고 이 서버의 DELETE /api/approvals('처음부터 다시')가 부른다 (clear_records).
  김수현 님 자체 화면(/, /web/*)도 열지 않는다 (통합 화면이 그 기능을 옮겨 왔다).
- 쿼리 store 는 늘 DEMO_STORE_ID, visitor_id 는 이 서버의 방문자 쿠키(request.state.visitor_id)로 **고정**한다.
  브라우저가 쿼리로 보낸 store·visitor_id 는 버린다. 그 밖의 쿼리는 report 의 period 만 넘긴다.
- 실패는 {"error": {"message": "한국어 안내", "state": "…"}} 이고 500 은 없다.
    꺼 둠(off)·연결 못 함(down)·몰림(busy) 503 · 너무 오래 걸림(slow) 504 · 서비스의 5xx·JSON 아님 502 (state error)
    서비스의 4xx 는 그 상태 코드 그대로, FastAPI 의 {"detail": "…"} 문장을 message 로 옮긴다 (한국어 문장이 아니면 정해 둔 안내).
    허용 목록 밖 404 (not_found) · 본문 64KB 초과 413 (too_big) · JSON 아님 422 (invalid) · 이 모듈의 버그 503 (error)
- 막히지 않게: 서비스 호출(동기 httpx)은 스레드에서 돈다. 동시에 기다리는 호출은 MAX_CONCURRENT 개까지.
  마케팅 서비스가 꺼져 있거나 느려도 비서 화면의 다른 API(/api/health 등)는 그대로다. /api/health 에 마케팅 상태를 섞지 않는다
  (섞으면 다른 화면 맨 위의 막힘 띠에 마케팅 꺼짐이 뜬다). 화면은 #/marketing 을 열 때 health 를 따로 부른다.

승인 연동 (POST approve)
- 화면은 마케팅 서비스가 받는 칸(state, session_id, edited_texts …)에 더해 "approval": {draft_id, text, original, kind, title}
  (또는 그 목록, 10개까지)를 실어 보낸다. 이 칸은 떼고 나머지만 서비스로 보낸다.
- 서비스가 2xx 이고 edit_failed 가 없을 때만 그 글마다 record(방문자, 글)를 부른다 (main.py 가 demo.approve 를 넘겨 줌).
  card_id 는 MARKETING_CARD_ID("marketing"), kind 는 정해 둔 한국어 글 종류, draft_id 는 "mkt-" 로 시작한다.
  그래서 '처리 완료'의 '서버 처리 기록'에 보이고, 리뷰 분석 서비스의 '답글 달았음' 기록(care.mark_replied_later)은 부르지 않는다.
- 응답은 서비스의 응답에 "recorded": [{draft_id, kind, approved_at, edited}] 를 더한 것. 기록하지 못하면 "record_warning".

설정 (settings.py)
  MARKETING_SURVEY_URL    마케팅 서비스 주소. 기본 http://127.0.0.1:8030. off 면 이 서버에서 맞춤 마케팅을 끈다
  MARKETING_TIMEOUT_SEC   글을 만드는 경로(plan·generate·idea-try)를 기다리는 최대 시간(초). 기본 45. 나머지는 10초
"""
from __future__ import annotations

import copy
import http.cookiejar
import json
import logging
import re
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from shared import store_header

log = logging.getLogger("web.marketing")

DEFAULT_URL = "http://127.0.0.1:8030"
SERVICE_PREFIX = "/api/marketing-survey"
MARKETING_CARD_ID = "marketing"                 # 승인 기록의 card_id (비서 화면의 카드 id 와 겹치지 않는 고정값)
MAX_JSON = 64 * 1024
MAX_CONCURRENT = 8
LONG_TIMEOUT = 45.0                             # 글을 만드는 경로 (MARKETING_TIMEOUT_SEC 로 바꿈)
SHORT_TIMEOUT = 10.0                            # 그 밖의 경로 (규칙·계산만)
HEALTH_TIMEOUT = 3.0
CLEAR_TIMEOUT = 3.0                             # '처음부터 다시'가 기록 지우기를 기다리는 최대 시간
MAX_APPROVALS = 10                              # 승인 한 번에 기록하는 글 수 상한
MAX_TEXT = 4000                                 # 기록하는 글 하나의 최대 글자 수

VISITOR_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")      # 마케팅 서비스(A)와 정한 visitor_id 규칙과 같다
DRAFT_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
# 승인 기록의 kind 로 받는 글 종류. 이 밖의 값은 '마케팅 글'로 남긴다 (reply_draft 같은 비서 화면 초안 종류가 섞이지 않게)
KINDS = ("공지", "답글", "홍보 글", "쿠폰 글", "가게 이야기 글", "남은 재료 글", "아이디어 글", "개선 소식", "기본 할 일 글", "마케팅 글")


@dataclass(frozen=True)
class Route:
    method: str
    long: bool = False          # 글을 만드는 경로 (기다리는 시간이 길다)


ROUTES: dict[str, Route] = {
    "meta": Route("GET"),
    "report": Route("GET"),
    "step": Route("POST"),
    "result": Route("POST"),
    "plan": Route("POST", long=True),
    "generate": Route("POST", long=True),
    "next-idea": Route("POST"),
    "idea-try": Route("POST", long=True),
    "coupon-calc": Route("POST"),
    "approve": Route("POST"),
    "notice-followup": Route("POST"),
    "ask": Route("POST", long=True),     # 마케팅 질문 답하기 (11/21). live 면 HCX-005 를 두 번 부를 수 있어 길게 기다린다
}
QUERY_KEYS = {"report": ("period",)}              # 브라우저 쿼리 중 넘기는 것 (store·visitor_id 는 서버가 붙임)

STATES = ("ready", "off", "down", "error")
MESSAGES = {
    "off": "이 서버에서는 맞춤 마케팅을 켜 두지 않았어요.",
    "down": "맞춤 마케팅 서비스에 연결하지 못했어요. 잠시 뒤 다시 해 주세요.",
    "slow": "맞춤 마케팅 서비스가 답하는 데 너무 오래 걸렸어요. 잠시 뒤 다시 해 주세요.",
    "busy": "요청이 몰려 있어요. 잠시 뒤 다시 해 주세요.",
    "not_found": "없는 주소예요.",
    "invalid": "보내는 내용의 형식이 맞지 않아요.",
    "too_big": "보내는 내용이 너무 커요.",
    "error": "맞춤 마케팅 서비스에 문제가 생겼어요. 잠시 뒤 다시 해 주세요.",
}
MISSING = "이 서버의 맞춤 마케팅 서비스에는 아직 이 기능이 없어요."
RECORD_WARNING = "마케팅 승인은 끝났지만 '처리 완료' 기록에는 남기지 못했어요."
UPSTREAM_STATE = {400: "invalid", 404: "not_found", 405: "not_found", 409: "invalid", 413: "too_big", 422: "invalid", 429: "busy"}
HANGUL = re.compile(r"[가-힣]")


class MarketingError(Exception):
    """마케팅 서비스와의 문제. state 는 화면이 보여 줄 분류, http 는 이 서버가 돌려줄 상태 코드."""

    def __init__(self, state: str, message: str | None = None, http: int = 503):
        super().__init__(message or MESSAGES.get(state, MESSAGES["error"]))
        self.state, self.message, self.http = state, message or MESSAGES.get(state, MESSAGES["error"]), http


def fail(state: str, http: int = 503, message: str | None = None) -> JSONResponse:
    out = JSONResponse({"error": {"message": message or MESSAGES.get(state, MESSAGES["error"]), "state": state}}, status_code=http)
    out.headers["Cache-Control"] = "no-store"
    return out


def _ok(data: Any) -> JSONResponse:
    out = JSONResponse(data)
    out.headers["Cache-Control"] = "no-store"
    return out


def _detail(data: Any) -> str | None:
    """FastAPI 오류 본문의 detail 문장 (한국어 문장일 때만). 목록(입력 검사 오류)이나 영어 기본 문장('Not Found')은 None."""
    detail = data.get("detail") if isinstance(data, dict) else None
    if isinstance(detail, str) and detail.strip() and HANGUL.search(detail):
        return detail.strip()[:300]
    return None


class MarketingProxy:
    def __init__(self, base_url: str | None, *, store_id: str = "store_ongi", timeout: float = LONG_TIMEOUT,
                 transport: httpx.BaseTransport | None = None, config_error: str | None = None):
        self.store = store_id
        self.long_timeout = float(timeout)
        self.config_error = config_error           # 주소 설정이 틀렸을 때의 안내 (off 가 아니라 error 로 보인다)
        self.client: httpx.Client | None = None    # None 이면 이 서버에서 맞춤 마케팅을 끈 것
        if base_url and not config_error:
            self.client = httpx.Client(base_url=base_url, transport=transport, follow_redirects=False,
                                       headers={"Accept": "application/json"},
                                       timeout=httpx.Timeout(connect=2.0, read=SHORT_TIMEOUT, write=10.0, pool=2.0))
            # 모든 방문자가 같은 클라이언트를 쓰므로 서비스가 준 쿠키를 쌓아 두지 않는다 (assistant_proxy.py 와 같은 이유)
            self.client.cookies.jar.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT)

    @classmethod
    def from_settings(cls, settings) -> "MarketingProxy":
        store_id = getattr(settings, "store_id", "store_ongi")
        timeout = float(getattr(settings, "marketing_timeout", LONG_TIMEOUT) or LONG_TIMEOUT)
        raw = (getattr(settings, "marketing_url", DEFAULT_URL) or "").strip().rstrip("/")
        if raw.lower() in ("", "off", "none", "0", "false"):
            return cls(None, store_id=store_id, timeout=timeout)
        parts = urlsplit(raw)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.path not in ("", "/") or parts.query \
                or parts.username or parts.password:
            return cls(None, store_id=store_id, timeout=timeout,
                       config_error="맞춤 마케팅 서비스 주소(MARKETING_SURVEY_URL) 설정이 올바르지 않아요.")
        return cls(raw, store_id=store_id, timeout=timeout)

    def for_store(self, store_id: str) -> "MarketingProxy":
        """다른 가게의 프록시 (얕은 사본: 같은 연결·동시 요청 한도). 쿼리 store 만 그 가게 (5차 회의 11/18)."""
        if store_id == self.store:
            return self
        view = copy.copy(self)
        view.store = store_id
        return view

    def close(self) -> None:
        if self.client is not None:
            self.client.close()

    def read_timeout(self, path: str) -> float:
        route = ROUTES.get(path)
        return self.long_timeout if route is not None and route.long else min(SHORT_TIMEOUT, self.long_timeout)

    def _unavailable(self) -> MarketingError | None:
        if self.config_error:
            return MarketingError("error", self.config_error, 503)
        if self.client is None:
            return MarketingError("off", http=503)
        return None

    # ── 상태 (항상 200) ───────────────────────────────────────────────
    def status(self) -> dict:
        problem = self._unavailable()
        if problem is not None:
            return {"state": problem.state, "message": problem.message, "service": "marketing-survey", "store_id": self.store}
        timeout = httpx.Timeout(HEALTH_TIMEOUT)
        try:
            r = self.client.get(SERVICE_PREFIX + "/health", params={"store": self.store}, timeout=timeout,
                                headers=store_header.headers_for(self.store) or None)
            data = r.json() if r.status_code == 200 else None
            if r.status_code == 404:
                # 마케팅 서비스가 /health 를 아직 모르는 판(PR #56 그대로)이면 가게 이름(meta)이 오는지로 쓸 수 있는지만 본다
                m = self.client.get(SERVICE_PREFIX + "/meta", params={"store": self.store}, timeout=timeout,
                                    headers=store_header.headers_for(self.store) or None)
                meta = m.json() if m.status_code == 200 else None
                if isinstance(meta, dict) and meta.get("store_name"):
                    return {"state": "ready", "message": None, "service": "marketing-survey", "mode": None,
                            "key_present": None, "demo": None, "notes": [], "store_id": self.store}
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return {"state": "down", "message": MESSAGES["down"], "service": "marketing-survey", "store_id": self.store}
        except httpx.TimeoutException:
            return {"state": "down", "message": MESSAGES["slow"], "service": "marketing-survey", "store_id": self.store}
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("맞춤 마케팅 서비스 상태 확인 실패 (%s)", exc.__class__.__name__)
            return {"state": "error", "message": MESSAGES["error"], "service": "marketing-survey", "store_id": self.store}
        if not isinstance(data, dict):
            log.warning("맞춤 마케팅 서비스 상태 응답이 이상함 (%s)", r.status_code)
            return {"state": "error", "message": MESSAGES["error"], "service": "marketing-survey", "store_id": self.store}
        # 서비스의 health (4부 4.6): mode·key_present·demo(HCX 를 부르지 않는 상태)·notes. 키 값·폴더 경로는 원래 싣지 않는다
        mode = data.get("mode") if data.get("mode") in ("live", "mock") else None
        flag = lambda name: data.get(name) if isinstance(data.get(name), bool) else None
        notes = [n[:200] for n in data.get("notes") or [] if isinstance(n, str)][:5] if isinstance(data.get("notes"), list) else []
        return {"state": "ready", "message": None, "service": "marketing-survey", "mode": mode, "key_present": flag("key_present"),
                "demo": flag("demo"), "notes": notes, "store_id": self.store}

    # ── 넘기기 (스레드에서 돈다) ──────────────────────────────────────────
    def call(self, method: str, path: str, params: dict, body: dict | None = None) -> Any:
        """한 번 부른다. 성공(2xx, JSON)이면 그 값, 아니면 MarketingError. 어떤 오류도 그대로 새어 나가지 않는다."""
        problem = self._unavailable()
        if problem is not None:
            raise problem
        if not self.slots.acquire(timeout=1.0):
            raise MarketingError("busy", http=503)
        timeout = httpx.Timeout(connect=2.0, read=self.read_timeout(path), write=10.0, pool=2.0)
        try:
            r = self.client.request(method, f"{SERVICE_PREFIX}/{path}", params=params,
                                    json=body if method != "GET" else None, timeout=timeout,
                                    headers=store_header.headers_for(self.store) or None)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            log.warning("맞춤 마케팅 서비스에 연결하지 못함 (%s %s: %s)", method, path, exc.__class__.__name__)
            raise MarketingError("down", http=503) from None
        except httpx.TimeoutException:
            log.warning("맞춤 마케팅 서비스가 제한 시간 안에 답하지 않음 (%s %s)", method, path)
            raise MarketingError("slow", http=504) from None
        except httpx.HTTPError as exc:
            log.warning("맞춤 마케팅 서비스 호출 오류 (%s %s: %s)", method, path, exc.__class__.__name__)
            raise MarketingError("error", http=502) from None
        finally:
            self.slots.release()
        return self._result(r, path)

    @staticmethod
    def _result(r: httpx.Response, path: str) -> Any:
        try:
            data = r.json()
        except ValueError:
            data = None
        if 200 <= r.status_code < 300:
            if not isinstance(data, (dict, list)):
                log.warning("맞춤 마케팅 서비스가 JSON 이 아닌 응답을 줌 (%s)", path)
                raise MarketingError("error", http=502)
            return data
        if r.status_code >= 500 or r.status_code < 400:
            log.warning("맞춤 마케팅 서비스 오류 응답 %s (%s)", r.status_code, path)
            raise MarketingError("error", http=502)
        state = UPSTREAM_STATE.get(r.status_code, "invalid")
        detail = _detail(data)
        log.info("맞춤 마케팅 서비스가 요청을 받지 않음 %s (%s)", r.status_code, path)
        if detail is None and r.status_code in (404, 405):
            detail = MISSING                     # FastAPI 기본 404·405: 이 서비스 판에는 그 경로가 없다
        raise MarketingError(state, detail, r.status_code)

    def ask(self, visitor_id: str | None, text: str) -> dict:
        """서랍의 마케팅 질문 1개 → 답·근거 카드 (마케팅 서비스 POST ask, 11/21). 실패는 MarketingError."""
        params = {"store": self.store}
        if visitor_id and VISITOR_ID.fullmatch(visitor_id):
            params["visitor_id"] = visitor_id
        data = self.call("POST", "ask", params, {"text": text})
        if not isinstance(data, dict):
            raise MarketingError("error", http=502)
        return data

    # ── '처음부터 다시' (main.py 의 DELETE /api/approvals 가 부름)·계정 초기화·탈퇴 (auth.py) ──────────────
    def _clear(self, visitor_id: str | None) -> str:
        """이 방문자의 마케팅 기록을 지운다. 'cleared'(지울 것이 없어도) | 'off'(꺼 둠) | 'config'(주소 설정이 틀림)
        | 'down'(연결 못 함) | 'refused'(받지 않음·너무 오래 걸림·방문자 id 가 틀림). 예외를 내지 않는다."""
        if self.config_error:
            return "config"
        if self.client is None:
            return "off"
        if not (visitor_id and VISITOR_ID.fullmatch(visitor_id)):
            return "refused"
        try:
            r = self.client.delete(SERVICE_PREFIX + "/records", params={"store": self.store, "visitor_id": visitor_id},
                                   headers=store_header.headers_for(self.store) or None,
                                   timeout=httpx.Timeout(connect=1.0, read=CLEAR_TIMEOUT, write=CLEAR_TIMEOUT, pool=1.0))
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            log.warning("맞춤 마케팅 기록을 지우지 못함: 서비스에 연결하지 못함")
            return "down"
        except Exception as exc:
            log.warning("맞춤 마케팅 기록을 지우지 못함 (%s)", exc.__class__.__name__)
            return "refused"
        if not 200 <= r.status_code < 300:
            log.warning("맞춤 마케팅 서비스가 기록 지우기를 받지 않음 (%s)", r.status_code)
            return "refused"
        return "cleared"

    def clear_records(self, visitor_id: str | None) -> bool | None:
        """이 방문자의 마케팅 기록을 지운다. True = 지움(지울 것이 없어도), False = 서비스가 받지 않음·너무 오래 걸림,
        None = 꺼 둠(off)·연결 못 함. 어떤 경우에도 예외를 내지 않는다 (승인 기록 지우기를 실패시키지 않게)."""
        return {"cleared": True, "refused": False}.get(self._clear(visitor_id))

    def clear_state(self, visitor_id: str | None) -> str:
        """계정 초기화·탈퇴용 (11/19). clear_records 와 같지만 꺼 둠과 실패를 나눈다:
        'cleared'(지웠거나 지울 것이 없음) | 'off'(이 서버에서 맞춤 마케팅을 꺼 둠 = 기록이 없음) | 'failed'(연결 못 함·거절·주소 설정이 틀림)."""
        state = self._clear(visitor_id)
        return state if state in ("cleared", "off") else "failed"


def take_approvals(data: dict) -> list[dict]:
    """approve 본문에서 "approval" 칸(글 하나 또는 목록)을 떼어 기록할 글 목록으로. 글이 빈 것·모양이 틀린 것은 건너뛴다."""
    raw = data.pop("approval", None)
    items = raw if isinstance(raw, list) else [raw] if raw is not None else []
    out: list[dict] = []
    for item in items[:MAX_APPROVALS]:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        original = item.get("original") if isinstance(item.get("original"), str) else None
        draft = item.get("draft_id") if isinstance(item.get("draft_id"), str) and DRAFT_ID.fullmatch(item["draft_id"]) else uuid.uuid4().hex[:16]
        kind = item.get("kind") if item.get("kind") in KINDS else "마케팅 글"
        out.append({"draft_id": draft if draft.startswith("mkt-") else "mkt-" + draft, "text": text[:MAX_TEXT],
                    "original": original[:MAX_TEXT] if original is not None else None, "kind": kind})
    return out


async def _read_capped(request: Request, limit: int) -> bytes | None:
    """본문을 limit 바이트까지만 읽는다. 넘으면 None."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        return None
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def create_marketing_router(proxy: MarketingProxy, record: Callable[[str | None, dict], dict] | None = None,
                            visitor_of: Callable[[Request], str | None] | None = None,
                            proxy_of: Callable[[Request], MarketingProxy] | None = None,
                            record_store: Callable[[str | None, dict, str], dict] | None = None) -> APIRouter:
    """main.py 가 붙인다. record(방문자, 글) 은 승인한 마케팅 글을 이 서버의 승인 기록에 남기는 함수 (demo.approve).
    가게가 여럿일 때(5차 회의 11/18): proxy_of(요청) 이 그 요청의 가게 프록시를, record_store(방문자, 글, 가게) 가 그 가게의
    승인 기록에 남긴다. 둘 다 없으면 예전처럼 proxy 하나·record."""
    visitor_of = visitor_of or (lambda request: getattr(request.state, "visitor_id", None))
    pick = proxy_of or (lambda request: proxy)
    api = APIRouter(prefix=SERVICE_PREFIX, tags=["marketing-survey-proxy"])

    @api.get("/health")
    def health(request: Request):
        try:
            data = pick(request).status()
        except Exception as exc:          # health 는 어떤 경우에도 200
            log.exception("맞춤 마케팅 health 오류 (%s)", exc.__class__.__name__)
            data = {"state": "error", "message": MESSAGES["error"], "service": "marketing-survey"}
        return _ok(data)

    def save(visitor: str | None, items: list[dict], store: str) -> tuple[list[dict], str | None]:
        if (record is None and record_store is None) or not items:
            return [], None
        done: list[dict] = []
        for item in items:
            try:
                entry = record_store(visitor, item, store) if record_store is not None else record(visitor, item)
            except Exception as exc:      # 마케팅 승인은 이미 끝났다. 기록을 못 남겨도 승인을 실패시키지 않는다
                log.warning("마케팅 승인 기록을 남기지 못함 (%s)", exc.__class__.__name__)
                return done, RECORD_WARNING
            row = {"draft_id": entry.get("draft_id"), "kind": item["kind"], "approved_at": entry.get("approved_at"),
                   "edited": bool(entry.get("edited"))}
            if entry.get("warning"):
                row["warning"] = entry["warning"]
            done.append(row)
        return done, None

    async def _forward(path: str, request: Request) -> JSONResponse:
        proxy = pick(request)
        route = ROUTES.get(path)
        if route is None or route.method != request.method:
            return fail("not_found", 404)
        body = await _read_capped(request, MAX_JSON)
        if body is None:
            return fail("too_big", 413)
        data = None
        if route.method == "POST":
            try:
                data = json.loads(body or b"{}")
            except ValueError:
                return fail("invalid", 422, "본문이 JSON 이 아니에요.")
            if not isinstance(data, dict):
                return fail("invalid", 422)
        approvals = take_approvals(data) if path == "approve" else []
        visitor = visitor_of(request)
        params = {"store": proxy.store}
        if visitor and VISITOR_ID.fullmatch(visitor):
            params["visitor_id"] = visitor
        for key in QUERY_KEYS.get(path, ()):
            value = request.query_params.get(key)
            if value is not None:
                params[key] = value[:20]
        try:
            out = await run_in_threadpool(proxy.call, route.method, path, params, data)
        except MarketingError as exc:
            return fail(exc.state, exc.http, exc.message)
        if path == "approve" and isinstance(out, dict) and not out.get("edit_failed"):
            recorded, warning = await run_in_threadpool(save, visitor, approvals, proxy.store)
            out["recorded"] = recorded
            if warning:
                out["record_warning"] = warning
        return _ok(out)

    @api.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def forward(path: str, request: Request):
        try:
            return await _forward(path, request)
        except Exception as exc:          # 우리 쪽 버그. 화면 전체가 죽지 않게 맞춤 마케팅 칸에만 알린다
            log.exception("맞춤 마케팅 프록시 예상 못한 오류 (%s)", exc.__class__.__name__)
            return fail("error")

    return api
