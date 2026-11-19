"""고객응대 프록시 — 비서 화면이 리뷰 분석·고객응대 서비스(services/review-insight, 127.0.0.1:8020)의
캡처 입력·응대 점수·보고서를 쓰는 길. 상권 비서 프록시(assistant_proxy.py)와 같은 규칙으로 만들었다.

브라우저는 이 서버(같은 출처)의 /api/care/* 만 부른다. 이 서버가 서비스의 /api/review-insight/* 를 대신 부른다.

| 메서드 | 경로 (브라우저가 부름)            | 서비스 경로                                  | 하는 일 |
|--------|-----------------------------------|----------------------------------------------|---------|
| GET    | /api/care/status                  | /api/health                                  | 쓸 수 있는지 (ready·off·down·error). 항상 200 |
| POST   | /api/care/reviews/capture         | /api/review-insight/reviews/capture          | 리뷰 화면 캡처 1장 → 리뷰 후보 (저장하지 않음). multipart 그대로, 12MB 까지 |
| POST   | /api/care/reviews/{id}/status     | /api/review-insight/reviews/{id}/status      | 리뷰 상태·답글 기록 (JSON 64KB 까지) |
| GET    | /api/care/response                | /api/review-insight/response                 | 응대 점수·답글 기다리는 불만의 기한 |
| GET    | /api/care/report/daily            | /api/review-insight/report/daily             | 일일 요약 (?date=YYYY-MM-DD) |
| GET    | /api/care/report/monthly          | /api/review-insight/report/monthly           | 월간 보고서 (?month=YYYY-MM) |
| GET    | /api/care/report/monthly/print    | /api/review-insight/report/monthly/print     | 월간 보고서 인쇄용 A4 HTML |

- 캡처 후보의 **저장**은 여기로 하지 않는다. 붙여넣기와 같은 POST /api/reviews 에 "source": "capture" 를 붙여 보낸다
  (main.py → sources.py → 서비스 POST /reviews). 그래야 붙여넣은 리뷰와 똑같이 이 방문자의 분석·카드에 들어간다.
- 위 표 밖의 경로는 404 다. 특히 가게 정보(/profile*)는 가게 공용이라 아무 방문자나 고치거나 지울 수 있고(임시 공지를
  101개 넣으면 저장본이 깨지는 버그도 있음), 문의(/inquiries*)·받은함(/inbox)·약속 장부(/promises)·다국어 메뉴판(/menu/foreign*)은
  이 화면이 아직 쓰지 않는다. 리뷰 목록·insight·붙여넣기 지우기는 이 서버의 /api/insight·/api/reviews 가 이미 맡는다.
- 손님용 문의 페이지(/s/{가게})와 /api/care/public/* 는 CARE_PUBLIC=1 일 때만 연다 (기본 꺼짐). Nginx(ic26-proxy-all.conf)가 / 아래를
  모두 이 서버로 넘기므로, 붙이기만 해도 밖에 열린다. 보안 검토 전까지 닫아 둔다 (팀장 결정 11/15).
  켜면 손님 주소는 Nginx 가 넣는 X-Real-IP(없으면 접속한 쪽 주소)만 쓴다. 손님이 직접 넣을 수 있는 X-Forwarded-For 의 맨 앞 값은 믿지 않는다.

넘길 때 하는 일
- store_id 는 늘 DEMO_STORE_ID, visitor_id 는 이 서버의 방문자 쿠키(request.state.visitor_id)로 **덮어쓴다** (쿼리·JSON 본문 모두.
  캡처 업로드는 본문을 고치지 않고 쿼리에 싣는다: 서비스가 쿼리 값을 폼보다 먼저 씀). 브라우저가 다른 가게·방문자를 고를 수 없다.
- 쿼리는 date·month·now 만 넘긴다. X-Access-Token(REVIEW_INSIGHT_TOKEN)은 서버가 붙인다 (브라우저는 토큰을 모름).
- 실패는 {"error": {"message": "한국어 안내", "state": "…"}} 이고 500 은 없다. 서비스가 준 오류(400·404·422·502 등)는 본문을 그대로 두고
  state 만 더한다 (message 는 서비스 문장 그대로). 이 서버가 만드는 state: off·down·slow·busy·too_big·not_found·invalid·error.
- 막히지 않게: 서비스 호출(동기 httpx)은 스레드에서 돈다(run_in_threadpool). 캡처 하나가 20초 걸려도 다른 화면 요청은 기다리지 않는다.
  동시에 기다리는 호출은 MAX_CONCURRENT 개까지 (서버 스레드를 다 잡아먹지 않게).

답글 승인 기록 (main.py 의 승인 경로가 부름)
- 사장님이 리뷰 답글을 승인하면 서비스의 POST /reviews/{review_id}/status 에 {"status": "replied", "reply_text": 승인한 글, "at": 승인 시각}.
  이 기록이 없으면 응대 점수가 모든 불만을 기한 넘김으로 센다 (docs/handoff.md 4절 2번, 9절 4번).
- 승인 응답을 기다리게 하지 않는다: 따로 도는 스레드 2개에서 보내고, 2초 안에 답이 없으면 버린다. 실패는 로그만 남긴다 (답글 글은 남기지 않음).

설정 (settings.py)
  CARE_URL           서비스 주소. 비우면 REVIEW_INSIGHT_URL 과 같은 곳(기본 http://127.0.0.1:8020). off 면 이 서버에서 고객응대를 끈다
  CARE_TIMEOUT_SEC   캡처 하나를 기다리는 최대 시간(초). 기본 100 (Nginx·로드 밸런서 120초보다 짧게). 다른 경로는 15초
  CARE_PUBLIC        1 이면 손님용 문의 페이지와 /api/care/public/* 를 연다. 기본 꺼짐
  REVIEW_INSIGHT_TOKEN, DEMO_STORE_ID  이미 있는 값을 그대로 쓴다
"""
from __future__ import annotations

import copy
import http.cookiejar
import json
import logging
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response

log = logging.getLogger("web.care")

DEFAULT_URL = "http://127.0.0.1:8020"
SERVICE_PREFIX = "/api/review-insight"
PAGE_API = "/api/review-insight/public"        # 손님 문의 페이지가 기본으로 부르는 주소 → /api/care/public 으로 바꿔서 준다
MAX_JSON = 64 * 1024
MAX_UPLOAD = 12 * 1024 * 1024                  # 서비스 캡처 상한 10MB + 여러 부분 폼 여유. Nginx 의 캡처 경로도 12m
MAX_CONCURRENT = 8
DEFAULT_TIMEOUT = 100.0
READ_TIMEOUT = 15.0                            # 캡처가 아닌 경로 (점수·보고서는 규칙 계산이라 빠르다)
REPLY_TIMEOUT = 2.0                            # 승인 기록 한 번에 기다리는 최대 시간

REVIEW_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")
VISITOR_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")      # 서비스의 VISITOR_PATTERN 과 같은 규칙
QUERY_KEYS = ("date", "month", "now")

# 사장님용으로 넘기는 것: (메서드, 경로). 경로는 /api/care 뒤 부분이고 fullmatch 로만 본다
ALLOWED: list[tuple[str, re.Pattern]] = [(m, re.compile(p)) for m, p in [
    ("POST", r"/reviews/capture"),
    ("POST", r"/reviews/[A-Za-z0-9_-]{1,100}/status"),
    ("GET", r"/response"),
    ("GET", r"/report/daily"),
    ("GET", r"/report/monthly"),
    ("GET", r"/report/monthly/print"),
]]
MULTIPART = frozenset({"/reviews/capture"})
HTML_PATHS = frozenset({"/report/monthly/print"})

STATES = ("ready", "off", "down", "error")
MESSAGES = {
    "off": "이 서버에서는 고객응대 기능(캡처·응대 점수·보고서)을 켜 두지 않았어요.",
    "down": "리뷰 분석 서비스에 연결하지 못했어요. 잠시 뒤 다시 확인해 주세요.",
    "slow": "리뷰 분석 서비스가 답하는 데 너무 오래 걸렸어요. 잠시 뒤 다시 해 주세요.",
    "busy": "요청이 몰려 있어요. 잠시 뒤 다시 해 주세요.",
    "not_found": "없는 주소예요.",
    "invalid": "보내는 내용의 형식이 맞지 않아요.",
    "error": "고객응대 기능에 문제가 생겼어요. 잠시 뒤 다시 해 주세요.",
}
TOO_BIG = {"upload": "캡처 파일이 너무 커요. 10MB 이하 이미지를 올려 주세요.", "json": "보내는 내용이 너무 커요."}
TOKEN_MESSAGE = "리뷰 분석 서비스가 이 서버의 요청을 받지 않았어요. 접근 토큰(REVIEW_INSIGHT_TOKEN) 설정을 확인해 주세요."
# 서비스가 준 오류에 붙이는 state (본문의 message 는 서비스 문장 그대로)
UPSTREAM_STATE = {400: "invalid", 404: "not_found", 413: "too_big", 422: "invalid", 429: "busy", 502: "upstream", 503: "unavailable"}
# 인쇄용 페이지는 이 서버 주소에서 열리므로, 스크립트·외부 주소를 막는다 (서비스가 글자를 html.escape 하지만 한 겹 더)
PRINT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"


def fail(state: str, http: int = 503, message: str | None = None) -> JSONResponse:
    out = JSONResponse({"error": {"message": message or MESSAGES.get(state, MESSAGES["error"]), "state": state}}, status_code=http)
    out.headers["Cache-Control"] = "no-store"
    return out


def _match(table, method: str, path: str) -> bool:
    return any(m == method and p.fullmatch(path) for m, p in table)


def _error_body(response: httpx.Response) -> dict | None:
    """서비스의 오류 본문 {"error": {"message", …}} 이면 그 dict, 아니면 None."""
    try:
        data = response.json()
    except ValueError:
        return None
    err = data.get("error") if isinstance(data, dict) else None
    return data if isinstance(err, dict) and isinstance(err.get("message"), str) and err["message"].strip() else None


class CareProxy:
    def __init__(self, base_url: str | None, *, token: str = "", store_id: str = "store_ongi", timeout: float = DEFAULT_TIMEOUT,
                 public: bool = False, transport: httpx.BaseTransport | None = None, config_error: str | None = None,
                 reply_timeout: float = REPLY_TIMEOUT):
        self.store = store_id
        self.token = (token or "").strip()
        self.timeout = float(timeout)
        self.reply_timeout = float(reply_timeout)
        self.public = bool(public)
        self.config_error = config_error           # 주소 설정이 틀렸을 때의 안내 (off 가 아니라 error 로 보인다)
        self.client: httpx.Client | None = None    # None 이면 이 서버에서 고객응대를 끈 것
        if base_url and not config_error:
            self.client = httpx.Client(base_url=base_url, transport=transport, follow_redirects=False,
                                       timeout=httpx.Timeout(connect=2.0, read=READ_TIMEOUT, write=10.0, pool=2.0))
            # 모든 방문자가 같은 클라이언트를 쓰므로 서비스가 준 쿠키를 쌓아 두지 않는다 (assistant_proxy.py 와 같은 이유)
            self.client.cookies.jar.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT)
        self._replies = ThreadPoolExecutor(max_workers=2, thread_name_prefix="care-reply")
        self._pending: set[Future] = set()
        self._pending_lock = threading.Lock()
        public_paths = [r"/public/{s}/info", r"/public/{s}/inquiries", r"/public/{s}/inquiries/[A-Za-z0-9_-]{{1,40}}"]
        s = re.escape(store_id)
        # 손님용은 우리 가게 하나만 (가게 고르기 없음)
        self.public_routes = [(m, re.compile(p.format(s=s))) for m, p in zip(("GET", "POST", "GET"), public_paths)]

    def for_store(self, store_id: str) -> "CareProxy":
        """다른 가게의 프록시 (얕은 사본: 같은 연결·동시 요청 한도·답글 기록 일꾼). 가게 id 와 손님용 경로만 그 가게 것 (11/18)."""
        if store_id == self.store:
            return self
        view = copy.copy(self)
        view.store = store_id
        public_paths = [r"/public/{s}/info", r"/public/{s}/inquiries", r"/public/{s}/inquiries/[A-Za-z0-9_-]{{1,40}}"]
        view.public_routes = [(m, re.compile(p.format(s=re.escape(store_id)))) for m, p in zip(("GET", "POST", "GET"), public_paths)]
        return view

    @classmethod
    def from_settings(cls, settings) -> "CareProxy":
        store_id = getattr(settings, "store_id", "store_ongi")
        common = dict(token=getattr(settings, "review_token", ""), store_id=store_id,
                      timeout=float(getattr(settings, "care_timeout", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT),
                      public=bool(getattr(settings, "care_public", False)))
        raw = (getattr(settings, "care_url", "") or "").strip().rstrip("/")
        if raw.lower() in ("off", "none", "0", "false"):
            return cls(None, **common)
        raw = raw or (getattr(settings, "review_url", "") or DEFAULT_URL).strip().rstrip("/")
        parts = urlsplit(raw)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.path not in ("", "/") or parts.query \
                or parts.username or parts.password:
            return cls(None, config_error="리뷰 분석 서비스 주소(CARE_URL·REVIEW_INSIGHT_URL) 설정이 올바르지 않아요.", **common)
        return cls(raw, **common)

    def close(self) -> None:
        self._replies.shutdown(wait=False, cancel_futures=True)
        if self.client is not None:
            self.client.close()

    # ── 상태 ──────────────────────────────────────────────────────────
    def _unavailable(self) -> JSONResponse | None:
        if self.config_error:
            return fail("error", 503, self.config_error)
        if self.client is None:
            return fail("off")
        return None

    def status(self) -> dict:
        if self.config_error:
            return {"state": "error", "message": self.config_error}
        if self.client is None:
            return {"state": "off", "message": MESSAGES["off"]}
        try:
            r = self.client.get("/api/health", timeout=httpx.Timeout(3.0))
            data = r.json() if r.status_code == 200 else None
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return {"state": "down", "message": MESSAGES["down"]}
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("리뷰 분석 서비스 상태 확인 실패 (%s)", exc.__class__.__name__)
            return {"state": "error", "message": MESSAGES["error"]}
        if not isinstance(data, dict):
            return {"state": "error", "message": MESSAGES["error"]}
        if data.get("token_required") and not self.token:
            return {"state": "error", "message": TOKEN_MESSAGE}
        return {"state": "ready", "message": None, "mode": data.get("mode"), "store_id": self.store, "public": self.public}

    # ── 넘기기 (스레드에서 돈다) ──────────────────────────────────────────
    def forward(self, method: str, path: str, *, params: dict, content: bytes | None, content_type: str | None,
                public: bool = False, client_ip: str | None = None, service_path: str | None = None) -> Response:
        problem = self._unavailable()
        if problem is not None:
            return problem
        if not self.slots.acquire(timeout=1.0):
            return fail("busy")
        multipart = path in MULTIPART
        headers = {"Accept": "text/html" if path in HTML_PATHS or service_path else "application/json"}
        if content is not None and content_type:
            headers["Content-Type"] = content_type
        if public:
            if client_ip:
                headers["X-Forwarded-For"] = client_ip      # 서비스의 손님 횟수 제한이 이 값의 맨 앞을 쓴다 (값 하나만 보냄)
        elif self.token:
            headers["X-Access-Token"] = self.token
        timeout = httpx.Timeout(connect=2.0, read=self.timeout if multipart else min(READ_TIMEOUT, self.timeout),
                                write=30.0 if multipart else 10.0, pool=2.0)
        try:
            r = self.client.request(method, service_path or SERVICE_PREFIX + path, params=params, content=content,
                                    headers=headers, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            log.warning("리뷰 분석 서비스에 연결하지 못함 (%s %s: %s)", method, path, exc.__class__.__name__)
            return fail("down")
        except httpx.TimeoutException:
            log.warning("리뷰 분석 서비스가 제한 시간 안에 답하지 않음 (%s %s)", method, path)
            return fail("slow")
        except httpx.HTTPError as exc:
            log.warning("리뷰 분석 서비스 호출 오류 (%s %s: %s)", method, path, exc.__class__.__name__)
            return fail("error")
        finally:
            self.slots.release()
        return self._relay(r, path, html=path in HTML_PATHS or bool(service_path))

    def _relay(self, r: httpx.Response, path: str, html: bool) -> Response:
        ctype = r.headers.get("content-type", "")
        if r.status_code in (401, 403):
            log.warning("리뷰 분석 서비스가 토큰을 받지 않음 (%s, %s)", r.status_code, path)
            return fail("error", 503, TOKEN_MESSAGE)
        if r.status_code >= 400:
            body = _error_body(r)
            if body is None or r.status_code >= 500 and r.status_code not in (502, 503):
                log.warning("리뷰 분석 서비스 오류 응답 %s (%s)", r.status_code, path)
                return fail("not_found", 404, "이 서버의 리뷰 분석 서비스에는 아직 이 기능이 없어요.") if r.status_code == 404 \
                    else fail("error")
            body["error"].setdefault("state", UPSTREAM_STATE.get(r.status_code, "error"))
            out = JSONResponse(body, status_code=r.status_code)
            out.headers["Cache-Control"] = "no-store"
            return out
        if html != ctype.startswith("text/html") or (not html and "json" not in ctype):
            log.warning("리뷰 분석 서비스가 뜻밖의 형식으로 답함 (%s, %s)", ctype or "-", path)
            return fail("error")
        headers = {"Cache-Control": r.headers.get("cache-control") or "no-store"}
        if r.headers.get("x-request-id"):
            headers["X-Request-Id"] = r.headers["x-request-id"]
        if html:
            headers.update({"Content-Security-Policy": PRINT_CSP, "X-Content-Type-Options": "nosniff"})
        return Response(r.content, status_code=r.status_code, media_type=ctype, headers=headers)

    # ── 답글 승인 기록 ────────────────────────────────────────────────────
    def mark_replied(self, visitor_id: str | None, review_id: str, text: str, at: str | None = None) -> bool:
        """서비스에 '답글 달았음'을 기록. 실패해도 예외를 내지 않고 False (로그만)."""
        reply = (text or "").strip()[:1000]
        if self.client is None or self.config_error or not REVIEW_ID.fullmatch(review_id or "") or not reply:
            return False
        body = {"store_id": self.store, "status": "replied", "reply_text": reply}
        if at:
            body["at"] = at
        if visitor_id and VISITOR_ID.fullmatch(visitor_id):
            body["visitor_id"] = visitor_id
        headers = {"X-Access-Token": self.token} if self.token else {}
        try:
            r = self.client.post(f"{SERVICE_PREFIX}/reviews/{review_id}/status", json=body, headers=headers,
                                 timeout=httpx.Timeout(self.reply_timeout))
        except Exception as exc:          # 연결 실패·시간 초과 등. 승인은 이미 끝났으니 기록만 못 한 것
            log.warning("답글 승인 기록을 리뷰 분석 서비스에 보내지 못함 (%s, %s)", review_id, exc.__class__.__name__)
            return False
        if r.status_code != 200:
            log.warning("리뷰 분석 서비스가 답글 승인 기록을 받지 않음 (%s, %s)", review_id, r.status_code)
            return False
        return True

    def mark_replied_later(self, visitor_id: str | None, review_id: str, text: str, at: str | None = None) -> Future | None:
        """승인 응답을 기다리게 하지 않고 따로 보낸다. 고객응대를 꺼 두었으면 아무것도 하지 않는다."""
        if self.client is None or self.config_error:
            return None
        try:
            future = self._replies.submit(self.mark_replied, visitor_id, review_id, text, at)
        except RuntimeError:              # 서버를 끄는 중
            return None
        with self._pending_lock:
            self._pending.add(future)
        future.add_done_callback(self._forget)
        return future

    def _forget(self, future: Future) -> None:
        with self._pending_lock:
            self._pending.discard(future)

    def flush(self, timeout: float = 5.0) -> None:
        """보내는 중인 승인 기록이 끝날 때까지 (시험용)."""
        with self._pending_lock:
            waiting = list(self._pending)
        for f in waiting:
            try:
                f.result(timeout=timeout)
            except Exception:
                pass


async def _read_capped(request: Request, limit: int) -> bytes | None:
    """본문을 limit 바이트까지만 읽는다. 넘으면 None (그 자리에서 멈춰 큰 파일을 끝까지 받지 않음)."""
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


def _client_ip(request: Request) -> str:
    """손님 주소: Nginx 가 덮어써 넣는 X-Real-IP, 없으면 접속한 쪽. 손님이 보낸 X-Forwarded-For 는 쓰지 않는다."""
    real = request.headers.get("x-real-ip", "").strip()
    if real and re.fullmatch(r"[0-9A-Fa-f:.]{2,45}", real):
        return real
    return request.client.host if request.client else ""


def create_care_routers(proxy: CareProxy, visitor_of: Callable[[Request], str | None] | None = None,
                        proxy_of: Callable[[Request], CareProxy] | None = None) -> list[APIRouter]:
    """main.py 가 붙인다. 손님용 페이지 라우터는 CARE_PUBLIC=1 일 때만 목록에 들어간다.
    proxy_of(요청) 이 있으면 요청마다 그 가게의 프록시를 쓴다 (5차 회의 11/18). 손님용 페이지는 기본 가게 하나만."""
    visitor_of = visitor_of or (lambda request: getattr(request.state, "visitor_id", None))
    pick = proxy_of or (lambda request: proxy)
    base = proxy
    api = APIRouter(prefix="/api/care", tags=["customer-care-proxy"])

    @api.get("/status")
    def status(request: Request):
        try:
            data = pick(request).status()
        except Exception as exc:          # status 는 어떤 경우에도 200
            log.exception("고객응대 status 오류 (%s)", exc.__class__.__name__)
            data = {"state": "error", "message": MESSAGES["error"]}
        return JSONResponse(data, headers={"Cache-Control": "no-store"})

    async def _forward(path: str, request: Request) -> Response:
        proxy = pick(request)
        path = "/" + path
        method = request.method
        public = proxy.public and path.startswith("/public/")
        if not _match(proxy.public_routes if public else ALLOWED, method, path):
            return fail("not_found", 404)
        multipart = path in MULTIPART
        body = await _read_capped(request, MAX_UPLOAD if multipart else MAX_JSON)
        if body is None:
            return fail("too_big", 413, TOO_BIG["upload" if multipart else "json"])
        content_type = request.headers.get("content-type", "")
        params = {k: request.query_params[k] for k in QUERY_KEYS if k in request.query_params}
        if method == "GET":
            body = b""
        if multipart and not content_type.lower().startswith("multipart/form-data"):
            return fail("invalid", 422, "이미지 파일을 골라서 올려 주세요.")
        if method == "POST" and not multipart:
            try:
                data = json.loads(body or b"{}")
            except ValueError:
                return fail("invalid", 422, "본문이 JSON 이 아니에요.")
            if not isinstance(data, dict):
                return fail("invalid", 422)
            if not public:
                data.pop("visitor_id", None)
                data["store_id"] = proxy.store
            body, content_type = json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json"
        client_ip = None
        if public:
            client_ip = _client_ip(request)      # 손님용은 방문자·토큰 없이 (가게 공용)
        else:
            visitor = visitor_of(request)
            params["store_id"] = proxy.store
            if visitor and VISITOR_ID.fullmatch(visitor):
                params["visitor_id"] = visitor
                if method == "POST" and not multipart:
                    data["visitor_id"] = visitor
                    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        return await run_in_threadpool(proxy.forward, method, path, params=params, content=body or None,
                                       content_type=content_type or None, public=public, client_ip=client_ip)

    @api.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def forward(path: str, request: Request):
        try:
            return await _forward(path, request)
        except Exception as exc:          # 우리 쪽 버그. 화면 전체가 죽지 않게 이 칸에만 알린다
            log.exception("고객응대 프록시 예상 못한 오류 (%s)", exc.__class__.__name__)
            return fail("error")

    routers = [api]
    if base.public:
        pages = APIRouter(tags=["customer-care-proxy"])

        @pages.get("/s/{store_id}")
        async def inquiry_page(store_id: str):
            if store_id != base.store:
                return fail("not_found", 404)
            try:
                r = await run_in_threadpool(base.forward, "GET", f"/s/{store_id}", params={}, content=None, content_type=None,
                                            public=True, service_path=f"/s/{store_id}")
                if r.status_code != 200 or not (r.media_type or "").startswith("text/html"):
                    return r
                page = r.body.decode("utf-8").replace(f'content="{PAGE_API}"', 'content="/api/care/public"', 1)
            except Exception as exc:
                log.exception("손님 문의 페이지 오류 (%s)", exc.__class__.__name__)
                return fail("error")
            # 손님 페이지는 자기 스크립트를 쓰므로 인쇄용 CSP 는 붙이지 않는다
            return HTMLResponse(page, headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})

        routers.append(pages)
    return routers
