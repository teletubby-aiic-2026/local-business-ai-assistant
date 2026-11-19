"""C7 한 화면 웹. 실행: services/web/run.sh (README 참고)

| 메서드 | 경로                          | 화면 단계 |
|--------|-------------------------------|-----------|
| GET    | /api/health                   | 맨 위 '동작/모의' 띠, 막힘 안내 |
| GET    | /api/briefing                 | ① 오늘의 브리핑 |
| GET    | /api/insight                  | 리뷰 분석 화면(요약·불만 묶음), 읽기 전용 |
| GET    | /api/cards                    | ② 추천 카드 2장 |
| POST   | /api/cards/{card_id}/run      | ③ 결과물 생성. 본문에 generator(+review_id)가 있으면 그 글 한 건만 다시 만듦 (초안 상자의 '다시 만들기'). replaces(옛 글 id)를 보내면 생성 뒤 그 승인 기록을 지움 |
| POST   | /api/drafts/{draft_id}/approve| ④ 승인 (수정 글 포함) |
| GET    | /api/approvals                | ④ 처리 완료 기록 |
| DELETE | /api/approvals                | ④ 이 방문자의 승인 기록 지우기 (완료 화면의 '처음부터 다시') |
| POST   | /api/reviews                  | S2 직접 붙여넣기 (#14 로 전달) |
| DELETE | /api/reviews/pasted           | 붙여넣은 리뷰 지우기 (데모 다시 하기) |
| *      | /api/assistant/*              | 서랍의 상권 채팅. 상권 서비스(ic26-market)를 대신 불러 줌 (assistant_proxy.py) |
| *      | /api/care/*                   | 캡처 입력·응대 점수·보고서. 리뷰 분석 서비스의 고객응대 API 를 대신 불러 줌 (care_proxy.py) |
| *      | /api/marketing-survey/*       | 맞춤 마케팅(#/marketing). 마케팅 서비스(김수현 님 설문형)를 대신 불러 줌 (marketing_proxy.py) |
| *      | /api/auth/*                   | 로그인·회원가입·로그아웃·가게 바꾸기·시연 로그인 (auth.py, 5차 회의 11/18), 계정 초기화 (11/19, account.py) |
| *      | /api/market/*                 | 상권 분석 화면(#/market). 상권 서비스의 분석·서울시 자료 확인·문화행사를 대신 불러 줌 (market_proxy.py) |

리뷰 답글을 승인하면(④) 리뷰 분석 서비스에 '답글 달았음'을 따로 기록한다 (care_proxy.mark_replied_later, 승인 응답은 기다리지 않음).
캡처 후보 저장은 붙여넣기와 같은 POST /api/reviews 에 source="capture" 를 붙여 보낸다.
맞춤 마케팅에서 글을 승인하면 이 서버의 승인 기록에도 남고(card_id "marketing"), '처음부터 다시'(DELETE /api/approvals)는
이 방문자의 마케팅 기록도 지운다 (응답의 marketing_cleared: true·false·null).

방문자 구분: 쿠키 `visitor_id`(없으면 서버가 새로 만들어 응답에 실음. HttpOnly, SameSite=Lax). 이 값으로 승인 기록과
붙여넣은 리뷰를 방문자별로 나눈다. 합성 리뷰와 카드 추천 이유 문장은 모두에게 같다. 화면(JS)은 쿠키를 다룰 필요가 없다.
로그인(쿠키 `ic26_session`)하면 방문자 id 는 'u-<user_id>', 가게는 세션의 고른 가게가 된다 (auth.py). 로그인하지 않으면
예전과 똑같이 기본 가게(DEMO_STORE_ID)와 쿠키 visitor_id 다. 가게마다의 Demo·프록시는 stores.StoreHub 가 고른다.
저장: 환경 변수 DB_HOST 가 있으면 PostgreSQL, 없으면 서버 메모리·파일 (shared/storage).
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from shared.storage import new_visitor_id, open_store, visitor_from_cookie

from .account import AccountData
from .assistant_proxy import AssistantProxy, create_assistant_router, validation_error_response
from .auth import SESSION_COOKIE, AuthService, create_auth_router
from .care_proxy import CareProxy, create_care_routers
from .demo import Demo, DemoError
from .market_proxy import MarketProxy, create_market_router
from .marketing_proxy import MARKETING_CARD_ID, MarketingProxy, create_marketing_router
from .settings import Settings
from .stores import StoreHub

# 화면: services/web/frontend(React 18 + Vite 5)의 빌드 결과. WEB_FRONTEND_DIST 로 다른 빌드 폴더를 줄 수 있다 (선택)
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
ASSET_PREFIXES = ("/assets/",)   # 빌드 파일 (index.html 이 부르는 /assets/index-<해시>.js·.css)
# 빌드가 없을 때 / 가 주는 안내 (서버 API 와 백엔드 시험은 빌드 없이도 돈다)
NO_BUILD_HTML = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>텔레토비 AI 비서</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto; padding: 0 1rem; line-height: 1.6">
<h1 style="font-size: 1.25rem">화면 빌드가 아직 없어요</h1>
<p><code>services/web/frontend</code> 에서 <code>npm ci &amp;&amp; npm run build</code> 를 실행한 뒤 새로고침해 주세요.
<code>services/web/run.sh</code> 로 띄우면 자동으로 빌드해요.</p>
</body></html>
"""
VISITOR_COOKIE = "visitor_id"
VISITOR_COOKIE_SECONDS = 60 * 60 * 24 * 30   # 30일
log = logging.getLogger("web.main")


class ApproveIn(BaseModel):
    text: str | None = None          # 사장님이 고친 글 (안 고쳤으면 원문과 같음)
    original: str | None = None      # 생성된 원문
    card_id: str | None = Field(default=None, max_length=100)   # 선택: 어느 카드의 초안인지 (안 보내면 서버가 ③ 에서 기억한 값)
    kind: str | None = Field(default=None, max_length=40)       # 선택: 초안 종류 (reply_draft 등)
    # 선택: 답글이 가리키는 리뷰 id. 이 서버가 ③ 에서 기억한 값이 먼저이고, 다른 서버가 만든 초안일 때만 쓴다.
    # 형식이 틀려도 승인은 실패시키지 않고 무시한다 (그래서 여기서 검사하지 않음, demo.reply_target 이 검사)
    review_id: str | None = None


class RunIn(BaseModel):
    measures: list[str] | None = None   # 사장님이 고른 재발 방지 조치 id (C6 measures.MEASURES, 예: "M1"). 없으면 기본값
    # 개별 다시 만들기 (선택). generator 가 있으면 그 종류의 글 한 건만 다시 만들고, 없으면 예전 그대로 카드 전체를 만든다
    generator: str | None = Field(default=None, max_length=40)    # reply_draft | prevention_notice | coupon_promo
    review_id: str | None = Field(default=None, max_length=100)   # reply_draft 일 때 필수: 그 답글이 가리키는 리뷰
    # prevention_notice 일 때만 씀: 지금 화면의 묶음 답글들. 새 공지가 답글과 너무 비슷한지 견주는 데만 쓰고 모델에 넘기지 않는다
    reply_texts: list[str] | None = Field(default=None, max_length=20)
    # 선택 (11/16): 이 생성으로 바뀌는 옛 글 id (최대 20개). 생성이 성공한 뒤에만 이 방문자의 승인 기록에서 지운다.
    # 개수·모양은 demo 가 400 으로 막는다 (화면 알림 띠에 그대로 보이는 문장)
    replaces: list[str] | None = None


class PasteIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)   # 리뷰 분석 서버(review-insight MAX_TEXT)·입력칸(maxlength)과 같은 1000자
    rating: int | None = Field(default=None, ge=1, le=5)
    channel: str | None = None
    source: Literal["paste", "capture"] | None = None   # capture = 캡처 후보를 사장님이 확인·수정해 저장 (분석에는 붙여넣기와 똑같이 들어감)


def create_app(demo: Demo | None = None, assistant: AssistantProxy | None = None, care: CareProxy | None = None,
               marketing: MarketingProxy | None = None, auth: AuthService | None = None,
               market: MarketProxy | None = None) -> FastAPI:
    # 저장 위치는 여기서만 환경 변수로 정한다 (DB_HOST 가 있으면 PostgreSQL, 없으면 메모리·파일)
    demo = demo or Demo(Settings.from_env(), storage=open_store(app_name="ic26-web"))
    assistant = assistant or AssistantProxy.from_settings(demo.s)   # 시험에서는 가짜 상권 서비스를 넣은 것을 줄 수 있다
    assistant.attach_store(demo)                                    # 서랍의 가게 기본 질문(이름·메뉴)에 답할 때 가게 프로필을 읽을 곳
    care = care or CareProxy.from_settings(demo.s)                  # 고객응대 프록시 (시험에서는 가짜 리뷰 분석 서비스)
    marketing = marketing or MarketingProxy.from_settings(demo.s)   # 맞춤 마케팅 프록시 (시험에서는 가짜 마케팅 서비스)
    market = market or MarketProxy.from_settings(demo.s)            # 상권 분석 화면(#/market) 프록시 (시험에서는 가짜 상권 서비스)
    hub = StoreHub(demo, assistant, care, marketing)                # 가게마다의 Demo·프록시 (기본 가게는 위의 객체 그대로)
    auth = auth or AuthService.from_env(demo.storage, demo.s.store_id)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        getattr(demo.storage, "close", lambda: None)()      # 서버를 끌 때 DB 연결 풀을 닫는다 (메모리 저장소는 할 일 없음)
        assistant.close()
        care.close()
        marketing.close()
        market.close()

    app = FastAPI(title="텔레토비 AI 비서 — 한 화면", docs_url="/docs", redoc_url=None, lifespan=lifespan)
    app.state.demo = demo
    app.state.assistant = assistant
    app.state.care = care
    app.state.marketing = marketing
    app.state.hub = hub
    app.state.market = market
    app.state.auth = auth

    def sid(request: Request) -> str:
        return getattr(request.state, "store_id", None) or demo.s.store_id

    def store_demo(request: Request) -> Demo:
        return hub.demo(sid(request))

    @app.middleware("http")
    async def _visitor(request: Request, call_next):
        """방문자마다 임의의 id 를 쿠키로 준다. 쿠키가 없거나 형식이 틀리면 새로 만들어 이 요청에도 쓰고 응답에 싣는다.
        로그인 세션(ic26_session)이 살아 있으면 이 요청의 방문자 id 는 'u-<user_id>', 가게는 세션이 고른 가게다 (auth.py)."""
        found = visitor_from_cookie(request.cookies.get(VISITOR_COOKIE))
        guest = found or new_visitor_id()
        request.state.guest_visitor_id = guest
        if request.url.path.startswith(ASSET_PREFIXES):   # 화면 파일은 로그인 세션을 볼 필요가 없다
            who = auth.guest(guest)
        else:
            who = await run_in_threadpool(auth.resolve, request.cookies.get(SESSION_COOKIE), guest)
        request.state.who = who
        request.state.visitor_id = who.visitor_id
        request.state.store_id = who.store_id if hub.known(who.store_id) else demo.s.store_id
        response = await call_next(request)
        if found is None and not request.url.path.startswith(ASSET_PREFIXES):
            secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"
            response.set_cookie(VISITOR_COOKIE, guest, max_age=VISITOR_COOKIE_SECONDS, path="/",
                                httponly=True, samesite="lax", secure=secure)
        return response

    @app.exception_handler(DemoError)
    async def _demo_error(_: Request, exc: DemoError):
        return JSONResponse(status_code=exc.status, content={"error": {"message": str(exc)}})

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/assistant/"):     # 서랍이 읽는 오류 모양. 다른 경로의 422 는 예전 그대로
            return validation_error_response(exc)
        return await request_validation_exception_handler(request, exc)

    @app.get("/api/health")
    def health(request: Request):
        return store_demo(request).health()

    @app.get("/api/briefing")
    def briefing(request: Request):
        return store_demo(request).briefing(request.state.visitor_id)

    @app.get("/api/insight")
    def insight(request: Request):
        return store_demo(request).insight(request.state.visitor_id)

    @app.get("/api/cards")
    def cards(request: Request):
        return store_demo(request).cards(request.state.visitor_id)

    @app.post("/api/cards/{card_id}/run")
    def run(card_id: str, request: Request, body: RunIn | None = None):
        demo = store_demo(request)
        if body is not None and body.generator is not None:   # 개별 다시 만들기: 그 글 한 건만
            return demo.run(card_id, measures=body.measures, visitor=request.state.visitor_id, generator=body.generator,
                            review_id=body.review_id, reply_texts=body.reply_texts, replaces=body.replaces)
        return demo.run(card_id, measures=body.measures if body else None, visitor=request.state.visitor_id,
                        replaces=body.replaces if body else None)

    @app.post("/api/drafts/{draft_id}/approve")
    def approve(draft_id: str, body: ApproveIn, request: Request):
        demo, care = store_demo(request), hub.care(sid(request))
        entry = demo.approve(draft_id, body.text, body.original, visitor=request.state.visitor_id,
                             card_id=body.card_id, kind=body.kind)
        # 리뷰 답글이면 리뷰 분석 서비스에 '답글 달았음'을 기록 (응대 기한·점수가 이 기록으로 계산됨). 따로 보내고 기다리지 않는다
        try:
            target = demo.reply_target(draft_id, body.kind, body.review_id)
            if target and entry.get("text"):
                care.mark_replied_later(request.state.visitor_id, target, entry["text"], entry.get("approved_at"))
        except Exception as exc:     # 승인 자체는 끝났다. 기록을 못 보내도 승인을 실패시키지 않는다
            log.warning("답글 승인 기록을 보내지 못했어요 (%s)", exc.__class__.__name__)
        return entry

    @app.get("/api/approvals")
    def approvals(request: Request):
        return {"items": store_demo(request).list_approvals(request.state.visitor_id)}

    @app.delete("/api/approvals")
    def clear_approvals(request: Request):
        deleted = store_demo(request).clear_approvals(request.state.visitor_id)
        # 맞춤 마케팅의 이 방문자 기록도 지운다 (보고서가 데모 기록으로 돌아감). 마케팅 서비스가 꺼져 있어도 승인 기록 지우기는 성공:
        # true = 지움, false = 서비스가 받지 않음, null = 꺼 둠·연결 못 함
        return {"deleted": deleted, "marketing_cleared": hub.marketing(sid(request)).clear_records(request.state.visitor_id)}

    @app.post("/api/reviews", status_code=201)
    def paste(body: PasteIn, request: Request):
        return store_demo(request).paste(body.text, body.rating, body.channel, visitor=request.state.visitor_id,
                                         source=body.source or "paste")

    @app.delete("/api/reviews/pasted")
    def reset_pasted(request: Request):
        return store_demo(request).reset_pasted(request.state.visitor_id)

    app.state.account = AccountData(hub)              # 계정 초기화·탈퇴가 사장님 기록을 지우는 곳 (account.py, 11/19)
    app.include_router(create_auth_router(auth, who_of=lambda request: request.state.who, erase=app.state.account.clear))
    app.include_router(create_assistant_router(assistant, proxy_of=lambda request: hub.assistant(sid(request))))
    app.include_router(create_market_router(market, store_of=sid))

    def record_marketing(visitor: str | None, item: dict, store: str) -> dict:
        # 맞춤 마케팅에서 승인한 글을 이 방문자·이 가게의 승인 기록에 (리뷰 답글이 아니므로 '답글 달았음'은 부르지 않는다)
        return hub.demo(store).approve(item["draft_id"], item["text"], item["original"], visitor=visitor,
                                       card_id=MARKETING_CARD_ID, kind=item["kind"])

    app.include_router(create_marketing_router(marketing, proxy_of=lambda request: hub.marketing(sid(request)),
                                               record_store=record_marketing))
    # 손님용 문의 페이지는 CARE_PUBLIC=1 일 때만 들어 있다 (기본 가게 하나)
    for router in create_care_routers(care, proxy_of=lambda request: hub.care(sid(request))):
        app.include_router(router)

    # 화면 파일: / 는 빌드 폴더의 index.html, /assets/* 는 빌드 결과 (화면 주소는 #/today 처럼 # 뒤라 / 하나면 된다)
    dist = frontend_dist()
    index = dist / "index.html"
    if not index.is_file():
        log.warning("화면 빌드가 없습니다 (%s). services/web/frontend 에서 npm ci && npm run build 를 먼저 하세요 "
                    "(run.sh 는 자동으로 빌드합니다). 그 전까지 / 는 안내 글만 줍니다.", index)

    @app.get("/")
    def page():
        if index.is_file():   # 서버를 띄운 뒤 빌드해도 새로고침하면 보이게 요청마다 확인
            return FileResponse(index)
        return HTMLResponse(NO_BUILD_HTML)

    app.mount("/assets", BuildFiles(directory=dist / "assets", check_dir=False), name="assets")
    return app


class BuildFiles(StaticFiles):
    """빌드 파일. 빌드 폴더가 아직 없으면 500 대신 404 를 주고, 서버를 띄운 뒤 빌드해도 새로고침하면 보인다."""

    async def check_config(self) -> None:
        if self.directory is not None and not os.path.isdir(self.directory):
            raise HTTPException(status_code=404)
        await super().check_config()


def frontend_dist() -> Path:
    """화면 빌드 폴더. 기본은 services/web/frontend/dist, WEB_FRONTEND_DIST 를 주면 그 폴더 (index.html 은 없을 수도 있음)."""
    raw = os.environ.get("WEB_FRONTEND_DIST", "").strip()
    return Path(raw).expanduser().resolve() if raw else FRONTEND_DIST
# 실행: uvicorn web.main:create_app --factory  (import 할 때 앱을 만들지 않아 시험에서 가짜 데이터를 넣을 수 있음)
