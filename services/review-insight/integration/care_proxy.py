"""고객응대 프록시 (참고 구현) — 비서 화면 서버(services/web)가 리뷰 분석·고객응대 서비스(127.0.0.1:8020)를 대신 불러 주는 길.

상권 비서 프록시(services/web/web/assistant_proxy.py, 브랜치 feat/assistant-proxy)와 같은 모양입니다.
이 파일은 리뷰 분석 모듈 담당이 만든 **참고 구현**이고, services/web 에 붙이는 일은 통합 담당이 정합니다 (docs/handoff.md 9절).
fastapi·httpx 만 쓰고 이 모듈의 app 패키지를 import 하지 않습니다 (두 서비스 모두 최상위 패키지가 app/ 이라 부딪힘).

브라우저는 비서 화면 서버(같은 출처)의 아래 경로만 부릅니다. 이 서버가 서비스의 /api/review-insight/... 로 넘깁니다.

| 화면 서버 경로 (브라우저가 부름)            | 서비스 경로                                   | 넘길 때 하는 일 |
|---------------------------------------------|-----------------------------------------------|-----------------|
| /api/care/status                            | /api/health                                   | 쓸 수 있는지 (ready·off·down). 항상 200 |
| /api/care/auth/login · signup · logout · me | /api/review-insight/auth/login · auth/accounts | 가게 계정 로그인. 맞으면 서명한 세션 쿠키(care_session)를 심음 (아래 '로그인') |
| /api/care/{사장님용 경로}                   | /api/review-insight/{같은 경로}               | X-Access-Token 붙임. 로그인했으면 store_id=그 계정의 가게, 방문자 없음(가게 공용). 안 했으면 store_id=DEMO_STORE_ID, visitor_id=방문자 쿠키 |
| /api/care/public/{가게}/...                 | /api/review-insight/public/{가게}/...         | 토큰·방문자 없음 (손님용, 가게 공용). 손님 주소는 X-Forwarded-For 로 넘김 (횟수 제한용) |
| /s/{가게}                                   | /s/{가게}                                     | 손님 문의 페이지. 페이지 안의 API 주소를 /api/care/public 으로 바꿔서 줌 |

사장님용 경로는 아래 ALLOWED 목록만 넘깁니다 (모르는 경로는 404). 실패는 {"error": {"message", "state"}} 로만 주고 500 을 내지 않습니다.

로그인 (가게 계정)
- 로그인하면 사장님용 요청의 가게는 **그 계정의 가게**로 정해지고, 방문자(visitor_id)는 붙이지 않습니다.
  같은 계정으로 들어온 사람은 어느 기기에서든 같은 리뷰·답글을 봅니다 (시연자별 구분 없음).
- 브라우저가 store_id·visitor_id 를 보내도 버립니다. 다른 가게를 고를 수 없습니다.
- 로그인하지 않으면 지금까지처럼 DEMO_STORE_ID 가게를 방문자 쿠키로 나눠 보여 줍니다.
  CARE_LOGIN_REQUIRED=1 이면 로그인하지 않은 사장님용 요청을 401 (state: login_required) 로 막습니다.
- 세션 쿠키: care_session = 내용.서명 (HMAC-SHA256). HttpOnly, SameSite=Lax, https 면 Secure, 12시간.
  서버에 세션을 저장하지 않으므로 WAS 가 여러 대여도 CARE_SESSION_SECRET(또는 REVIEW_INSIGHT_TOKEN)이 같으면 통합니다.
- 로그인 화면(아이디·비밀번호 입력 칸)은 통합 화면(services/web)의 몫입니다.

설정 (환경 변수, 화면 서버의 Settings 에 이미 있는 이름을 그대로 씀)
  REVIEW_INSIGHT_URL    서비스 주소. 기본 http://127.0.0.1:8020. off 면 끔
  REVIEW_INSIGHT_TOKEN  서비스의 APP_ACCESS_TOKEN 과 같은 값 (비우면 안 붙임)
  DEMO_STORE_ID         가게 하나 고정 (기본 store_ongi). 사장님용 요청의 store_id 는 늘 이 값
  CARE_SESSION_SECRET   세션 쿠키 서명 키. 비우면 REVIEW_INSIGHT_TOKEN 에서 만들고, 그것도 없으면 서버를 켤 때마다 새로 만듦 (재시작하면 로그아웃)
  CARE_LOGIN_REQUIRED   1 이면 로그인해야 사장님용 경로를 쓸 수 있음. 기본은 꺼짐 (로그인 없이 시연 가게)
  CARE_TIMEOUT_SEC      기다리는 최대 시간. 기본 40 (캡처는 조각마다 HCX 를 불러 오래 걸릴 수 있음)

붙이는 법 (services/web/web/main.py, 통합 담당):
    from web.care_proxy import create_care_routers         # 이 파일을 web/care_proxy.py 로 복사
    api, pages = create_care_routers(visitor_of=lambda request: request.state.visitor_id)
    app.include_router(api); app.include_router(pages)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Callable

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

SERVICE_PREFIX = "/api/review-insight"
PAGE_API = "/api/review-insight/public"         # 문의 페이지가 기본으로 부르는 주소 → /api/care/public 으로 바꿈
MAX_JSON = 64 * 1024
MAX_UPLOAD = 12 * 1024 * 1024                   # 서비스 캡처 상한 10MB + 여유 (Nginx client_max_body_size 도 12m 이상)

# 사장님용으로 넘기는 것: (메서드, 경로 정규식). 경로는 /api/care 뒤 부분
ALLOWED: list[tuple[str, re.Pattern]] = [(m, re.compile(p)) for m, p in [
    ("GET", r"/reviews"), ("POST", r"/reviews"), ("POST", r"/reviews/capture"), ("POST", r"/reviews/[A-Za-z0-9_-]+/status"),
    ("GET", r"/reviews/[A-Za-z0-9_-]+"),
    ("GET", r"/insight"), ("GET", r"/response"), ("GET", r"/report/daily"), ("GET", r"/report/monthly"), ("GET", r"/report/monthly/print"),
    ("GET", r"/profile"), ("PUT", r"/profile"), ("DELETE", r"/profile"),
    ("POST", r"/profile/notices"), ("DELETE", r"/profile/notices/[A-Za-z0-9_-]+"),
    ("POST", r"/profile/answers"), ("DELETE", r"/profile/answers/[A-Za-z0-9_-]+"), ("POST", r"/profile/menu/capture"),
    ("GET", r"/inbox"), ("POST", r"/inquiries/[A-Za-z0-9_-]+/status"), ("POST", r"/inquiries/[A-Za-z0-9_-]+/draft"),
    ("GET", r"/promises"), ("GET", r"/menu/foreign"), ("GET", r"/menu/foreign/print"),
]]
PUBLIC = [(m, re.compile(p)) for m, p in [
    ("GET", r"/public/[a-z0-9_]+/info"), ("POST", r"/public/[a-z0-9_]+/inquiries"),
    ("GET", r"/public/[a-z0-9_]+/inquiries/[A-Za-z0-9_-]+"),
]]
SESSION_COOKIE = "care_session"
SESSION_SECONDS = 12 * 3600
STORE_ID = re.compile(r"store_[a-z0-9_]{1,40}")
MULTIPART = {"/reviews/capture", "/profile/menu/capture"}

MESSAGES = {"off": "이 서버에서는 고객응대 기능을 켜 두지 않았어요.",
            "down": "리뷰 분석 서비스에 연결하지 못했어요. 잠시 뒤 다시 확인해 주세요.",
            "slow": "리뷰 분석 서비스가 답하는 데 너무 오래 걸렸어요. 잠시 뒤 다시 해 주세요.",
            "too_big": "보내는 내용이 너무 커요.", "not_found": "없는 주소예요.",
            "login_required": "로그인이 필요해요.", "login_failed": "아이디나 비밀번호가 맞지 않아요.",
            "invalid": "보낸 내용을 확인해 주세요."}


def _fail(state: str, http: int = 503, message: str | None = None) -> JSONResponse:
    return JSONResponse({"error": {"message": message or MESSAGES.get(state, "고객응대 기능에 문제가 생겼어요."), "state": state}},
                        status_code=http)


def _match(table, method: str, path: str) -> bool:
    return any(m == method and p.fullmatch(path) for m, p in table)


def create_care_routers(*, base_url: str | None = None, token: str | None = None, store_id: str | None = None,
                        timeout: float | None = None, client: httpx.Client | None = None,
                        visitor_of: Callable[[Request], str | None] | None = None,
                        session_secret: str | None = None, login_required: bool | None = None,
                        clock: Callable[[], float] = time.time) -> tuple[APIRouter, APIRouter]:
    env = os.environ.get
    base = (base_url if base_url is not None else env("REVIEW_INSIGHT_URL", "http://127.0.0.1:8020")).strip().rstrip("/")
    token = (token if token is not None else env("REVIEW_INSIGHT_TOKEN", "")).strip()
    store = (store_id or env("DEMO_STORE_ID", "store_ongi")).strip()
    wait = float(timeout if timeout is not None else (env("CARE_TIMEOUT_SEC", "") or 40))
    off = base.lower() == "off"
    http = client or (None if off else httpx.Client(base_url=base, timeout=wait))
    visitor_of = visitor_of or (lambda request: getattr(request.state, "visitor_id", None) or request.cookies.get("visitor_id"))
    configured = session_secret if session_secret is not None else env("CARE_SESSION_SECRET", "")
    secret = (configured or (f"care-session:{token}" if token else secrets.token_hex(32))).encode("utf-8")
    must_login = login_required if login_required is not None else env("CARE_LOGIN_REQUIRED", "").strip().lower() in ("1", "true", "yes")
    api = APIRouter(prefix="/api/care", tags=["customer-care-proxy"])

    # ── 로그인 세션 (서명한 쿠키. 서버에 저장하지 않음) ─────────────────────────────
    def _sign(payload: str) -> str:
        return hmac.new(secret, payload.encode("ascii"), hashlib.sha256).hexdigest()

    def _pack(account: dict) -> str:
        data = {"l": account["login_id"], "s": account["store_id"], "n": account.get("store_name"), "d": bool(account.get("demo")),
                "e": int(clock()) + SESSION_SECONDS}
        payload = base64.urlsafe_b64encode(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("ascii")
        return f"{payload}.{_sign(payload)}"

    def session_of(request: Request) -> dict | None:
        """맞는 세션이면 {"login_id","store_id","store_name","demo"}. 없거나 고쳐졌거나 지났으면 None."""
        raw = request.cookies.get(SESSION_COOKIE) or ""
        payload, _, sig = raw.partition(".")
        if not payload or not sig or not hmac.compare_digest(_sign(payload) if payload.isascii() else "", sig):
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get("e"), int) or data["e"] < clock():
            return None
        if not (isinstance(data.get("s"), str) and STORE_ID.fullmatch(data["s"]) and isinstance(data.get("l"), str)):
            return None
        return {"login_id": data["l"], "store_id": data["s"], "store_name": data.get("n"), "demo": bool(data.get("d"))}

    def _https(request: Request) -> bool:
        return request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip() == "https"

    async def _json_body(request: Request):
        body = await request.body()
        if len(body) > MAX_JSON:
            return None, _fail("too_big", 413)
        try:
            data = json.loads(body or b"null")
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return None, _fail("invalid", 422, "본문이 JSON 이 아니에요.")
        return data, None

    def _ask_service(request: Request, path: str, data: dict):
        """(계정 dict, None) 또는 (None, 실패 응답). 비밀번호는 서비스로 넘기기만 하고 남기지 않는다."""
        if off:
            return None, _fail("off")
        headers = {"X-Access-Token": token} if token else {}
        client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")
        if client_ip:
            headers["X-Forwarded-For"] = client_ip
        try:
            r = http.post(SERVICE_PREFIX + path, json=data, headers=headers, timeout=wait)
            got = r.json()
        except httpx.TimeoutException:
            return None, _fail("slow")
        except (httpx.HTTPError, ValueError):
            return None, _fail("down")
        if r.status_code >= 400 or not isinstance(got, dict):
            err = got.get("error", {}) if isinstance(got, dict) else {}
            state = {401: "login_failed", 429: "too_many_tries", 403: "signup_code", 400: "invalid"}.get(r.status_code, "failed")
            shown = str(err.get("message")) if r.status_code in (400, 401, 403, 429) and err.get("message") else None
            return None, _fail(state, r.status_code if r.status_code < 500 else 502, shown)
        if not (isinstance(got.get("store_id"), str) and STORE_ID.fullmatch(got["store_id"]) and isinstance(got.get("login_id"), str)):
            return None, _fail("failed", 502)
        return got, None

    def _logged_in(request: Request, account: dict, http_status: int = 200) -> JSONResponse:
        out = {k: account.get(k) for k in ("login_id", "store_id", "store_name", "demo")}
        response = JSONResponse({"logged_in": True, **out}, status_code=http_status)
        response.set_cookie(SESSION_COOKIE, _pack(account), max_age=SESSION_SECONDS, path="/", httponly=True, samesite="lax",
                            secure=_https(request))
        return response

    api.session_of = session_of          # 같은 서버의 다른 길(예: 확인용 화면)이 로그인 여부를 물을 때 씀

    @api.post("/auth/login")
    async def login(request: Request):
        data, failed = await _json_body(request)
        if failed:
            return failed
        account, failed = _ask_service(request, "/auth/login", {"login_id": data.get("login_id"), "password": data.get("password")})
        return failed or _logged_in(request, account)

    @api.post("/auth/signup")
    async def signup(request: Request):
        """새 계정 + 새 가게(리뷰 0건). 만들고 바로 로그인 상태가 된다."""
        data, failed = await _json_body(request)
        if failed:
            return failed
        wanted = {k: data.get(k) for k in ("login_id", "password", "store_name", "business_type_name", "signup_code")}
        account, failed = _ask_service(request, "/auth/accounts", wanted)
        return failed or _logged_in(request, account, 201)

    @api.post("/auth/logout")
    def logout():
        response = JSONResponse({"logged_in": False})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @api.get("/auth/me")
    def me(request: Request):
        account = session_of(request)
        if account is None:
            return {"logged_in": False, "login_required": must_login, "store_id": None if must_login else store}
        return {"logged_in": True, "login_required": must_login, **account}
    pages = APIRouter(tags=["customer-care-proxy"])

    def send(method: str, url: str, *, params=None, content=None, headers=None) -> Response:
        if off:
            return _fail("off")
        try:
            r = http.request(method, url, params=params, content=content, headers=headers or {}, timeout=wait)
        except httpx.TimeoutException:
            return _fail("slow")
        except httpx.HTTPError:
            return _fail("down")
        kept = {k: v for k, v in r.headers.items() if k.lower() in ("content-type", "x-request-id", "cache-control")}
        return Response(r.content, status_code=r.status_code, headers=kept)

    @api.get("/status")
    def status(request: Request):
        account = session_of(request)
        if off:
            return {"state": "off", "message": MESSAGES["off"]}
        try:
            h = http.get("/api/health", timeout=5).json()
        except (httpx.HTTPError, ValueError):
            return {"state": "down", "message": MESSAGES["down"]}
        return {"state": "ready", "message": None, "mode": h.get("mode"),
                "store_id": account["store_id"] if account else (None if must_login else store), "logged_in": account is not None}

    @api.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def forward(path: str, request: Request):
        path = "/" + path
        method = request.method
        public = path.startswith("/public/")
        if not (_match(PUBLIC, method, path) if public else _match(ALLOWED, method, path)):
            return _fail("not_found", 404)
        body = await request.body()
        multipart = path in MULTIPART
        if len(body) > (MAX_UPLOAD if multipart else MAX_JSON):
            return _fail("too_big", 413)
        headers = {"Content-Type": request.headers.get("content-type", "application/json")}
        client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")
        if client_ip:
            headers["X-Forwarded-For"] = client_ip
        params = dict(request.query_params)
        if not public:
            if token:
                headers["X-Access-Token"] = token
            account = session_of(request)
            if account is None and must_login:
                return _fail("login_required", 401)
            # 로그인했으면 그 계정의 가게, 방문자 없이(가게 공용). 안 했으면 시연 가게를 방문자 쿠키로 나눔
            store_now = account["store_id"] if account else store
            visitor = None if account else visitor_of(request)
            params["store_id"] = store_now
            params.pop("visitor_id", None)
            if visitor:
                params["visitor_id"] = visitor
            if method in ("POST", "PUT") and not multipart and body:
                try:
                    data = json.loads(body)
                except ValueError:
                    return _fail("invalid", 422, "본문이 JSON 이 아니에요.")
                if isinstance(data, dict):
                    data["store_id"] = store_now
                    data.pop("visitor_id", None)
                    if visitor:
                        data["visitor_id"] = visitor
                    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            # 여러 부분 폼(캡처 업로드)은 본문을 고치지 않고, 서비스가 쿼리의 store_id·visitor_id 를 우선해서 쓴다
        # 손님용(/public/*)은 방문자를 붙이지 않는다: 손님 문의·가게 정보는 가게 공용 (서비스가 visitor_id 를 쓰지 않음)
        return send(method, SERVICE_PREFIX + path, params=params, content=body or None, headers=headers)

    @pages.get("/s/{store_id}")
    def inquiry_page(store_id: str):
        r = send("GET", f"/s/{store_id}")
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("text/html"):
            return r
        html = r.body.decode("utf-8").replace(f'content="{PAGE_API}"', 'content="/api/care/public"', 1)
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    return api, pages
