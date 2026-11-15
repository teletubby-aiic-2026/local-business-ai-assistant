"""고객응대 프록시 (참고 구현) — 비서 화면 서버(services/web)가 리뷰 분석·고객응대 서비스(127.0.0.1:8020)를 대신 불러 주는 길.

상권 비서 프록시(services/web/web/assistant_proxy.py, 브랜치 feat/assistant-proxy)와 같은 모양입니다.
이 파일은 리뷰 분석 모듈 담당이 만든 **참고 구현**이고, services/web 에 붙이는 일은 통합 담당이 정합니다 (docs/handoff.md 9절).
fastapi·httpx 만 쓰고 이 모듈의 app 패키지를 import 하지 않습니다 (두 서비스 모두 최상위 패키지가 app/ 이라 부딪힘).

브라우저는 비서 화면 서버(같은 출처)의 아래 경로만 부릅니다. 이 서버가 서비스의 /api/review-insight/... 로 넘깁니다.

| 화면 서버 경로 (브라우저가 부름)            | 서비스 경로                                   | 넘길 때 하는 일 |
|---------------------------------------------|-----------------------------------------------|-----------------|
| /api/care/status                            | /api/health                                   | 쓸 수 있는지 (ready·off·down). 항상 200 |
| /api/care/{사장님용 경로}                   | /api/review-insight/{같은 경로}               | X-Access-Token 붙임, store_id=DEMO_STORE_ID, visitor_id=방문자 쿠키 로 덮어씀 |
| /api/care/public/{가게}/...                 | /api/review-insight/public/{가게}/...         | 토큰·방문자 없음 (손님용, 가게 공용). 손님 주소는 X-Forwarded-For 로 넘김 (횟수 제한용) |
| /s/{가게}                                   | /s/{가게}                                     | 손님 문의 페이지. 페이지 안의 API 주소를 /api/care/public 으로 바꿔서 줌 |

사장님용 경로는 아래 ALLOWED 목록만 넘깁니다 (모르는 경로는 404). 실패는 {"error": {"message", "state"}} 로만 주고 500 을 내지 않습니다.

설정 (환경 변수, 화면 서버의 Settings 에 이미 있는 이름을 그대로 씀)
  REVIEW_INSIGHT_URL    서비스 주소. 기본 http://127.0.0.1:8020. off 면 끔
  REVIEW_INSIGHT_TOKEN  서비스의 APP_ACCESS_TOKEN 과 같은 값 (비우면 안 붙임)
  DEMO_STORE_ID         가게 하나 고정 (기본 store_ongi). 사장님용 요청의 store_id 는 늘 이 값
  CARE_TIMEOUT_SEC      기다리는 최대 시간. 기본 40 (캡처는 조각마다 HCX 를 불러 오래 걸릴 수 있음)

붙이는 법 (services/web/web/main.py, 통합 담당):
    from web.care_proxy import create_care_routers         # 이 파일을 web/care_proxy.py 로 복사
    api, pages = create_care_routers(visitor_of=lambda request: request.state.visitor_id)
    app.include_router(api); app.include_router(pages)
"""
from __future__ import annotations

import json
import os
import re
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
MULTIPART = {"/reviews/capture", "/profile/menu/capture"}

MESSAGES = {"off": "이 서버에서는 고객응대 기능을 켜 두지 않았어요.",
            "down": "리뷰 분석 서비스에 연결하지 못했어요. 잠시 뒤 다시 확인해 주세요.",
            "slow": "리뷰 분석 서비스가 답하는 데 너무 오래 걸렸어요. 잠시 뒤 다시 해 주세요.",
            "too_big": "보내는 내용이 너무 커요.", "not_found": "없는 주소예요."}


def _fail(state: str, http: int = 503, message: str | None = None) -> JSONResponse:
    return JSONResponse({"error": {"message": message or MESSAGES.get(state, "고객응대 기능에 문제가 생겼어요."), "state": state}},
                        status_code=http)


def _match(table, method: str, path: str) -> bool:
    return any(m == method and p.fullmatch(path) for m, p in table)


def create_care_routers(*, base_url: str | None = None, token: str | None = None, store_id: str | None = None,
                        timeout: float | None = None, client: httpx.Client | None = None,
                        visitor_of: Callable[[Request], str | None] | None = None) -> tuple[APIRouter, APIRouter]:
    env = os.environ.get
    base = (base_url if base_url is not None else env("REVIEW_INSIGHT_URL", "http://127.0.0.1:8020")).strip().rstrip("/")
    token = (token if token is not None else env("REVIEW_INSIGHT_TOKEN", "")).strip()
    store = (store_id or env("DEMO_STORE_ID", "store_ongi")).strip()
    wait = float(timeout if timeout is not None else (env("CARE_TIMEOUT_SEC", "") or 40))
    off = base.lower() == "off"
    http = client or (None if off else httpx.Client(base_url=base, timeout=wait))
    visitor_of = visitor_of or (lambda request: getattr(request.state, "visitor_id", None) or request.cookies.get("visitor_id"))
    api = APIRouter(prefix="/api/care", tags=["customer-care-proxy"])
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
    def status():
        if off:
            return {"state": "off", "message": MESSAGES["off"]}
        try:
            h = http.get("/api/health", timeout=5).json()
        except (httpx.HTTPError, ValueError):
            return {"state": "down", "message": MESSAGES["down"]}
        return {"state": "ready", "message": None, "mode": h.get("mode"), "store_id": store}

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
            visitor = visitor_of(request)
            params["store_id"] = store
            params.pop("visitor_id", None)
            if visitor:
                params["visitor_id"] = visitor
            if method in ("POST", "PUT") and not multipart and body:
                try:
                    data = json.loads(body)
                except ValueError:
                    return _fail("invalid", 422, "본문이 JSON 이 아니에요.")
                if isinstance(data, dict):
                    data["store_id"] = store
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
