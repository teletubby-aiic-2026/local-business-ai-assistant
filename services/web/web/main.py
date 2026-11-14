"""C7 한 화면 웹. 실행: services/web/run.sh (README 참고)

| 메서드 | 경로                          | 화면 단계 |
|--------|-------------------------------|-----------|
| GET    | /api/health                   | 맨 위 '동작/모의' 띠, 막힘 안내 |
| GET    | /api/briefing                 | ① 오늘의 브리핑 |
| GET    | /api/insight                  | 리뷰 분석 화면(요약·불만 묶음), 읽기 전용 |
| GET    | /api/cards                    | ② 추천 카드 2장 |
| POST   | /api/cards/{card_id}/run      | ③ 결과물 생성 |
| POST   | /api/drafts/{draft_id}/approve| ④ 승인 (수정 글 포함) |
| GET    | /api/approvals                | ④ 처리 완료 기록 |
| POST   | /api/reviews                  | S2 직접 붙여넣기 (#14 로 전달) |
| DELETE | /api/reviews/pasted           | 붙여넣은 리뷰 지우기 (데모 다시 하기) |
| *      | /api/assistant/*              | 서랍의 상권 채팅. 상권 서비스(ic26-market)를 대신 불러 줌 (assistant_proxy.py) |

방문자 구분: 쿠키 `visitor_id`(없으면 서버가 새로 만들어 응답에 실음. HttpOnly, SameSite=Lax). 이 값으로 승인 기록과
붙여넣은 리뷰를 방문자별로 나눈다. 합성 리뷰와 카드 추천 이유 문장은 모두에게 같다. 화면(JS)은 쿠키를 다룰 필요가 없다.
저장: 환경 변수 DB_HOST 가 있으면 PostgreSQL, 없으면 서버 메모리·파일 (shared/storage).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from shared.storage import new_visitor_id, open_store, visitor_from_cookie

from .assistant_proxy import AssistantProxy, create_assistant_router, validation_error_response
from .demo import Demo, DemoError
from .settings import Settings

STATIC = Path(__file__).resolve().parent / "static"
VISITOR_COOKIE = "visitor_id"
VISITOR_COOKIE_SECONDS = 60 * 60 * 24 * 30   # 30일


class ApproveIn(BaseModel):
    text: str | None = None          # 사장님이 고친 글 (안 고쳤으면 원문과 같음)
    original: str | None = None      # 생성된 원문
    card_id: str | None = Field(default=None, max_length=100)   # 선택: 어느 카드의 초안인지 (안 보내면 서버가 ③ 에서 기억한 값)
    kind: str | None = Field(default=None, max_length=40)       # 선택: 초안 종류 (reply_draft 등)


class RunIn(BaseModel):
    measures: list[str] | None = None   # 사장님이 고른 재발 방지 조치 id (C6 measures.MEASURES, 예: "M1"). 없으면 기본값


class PasteIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)   # 리뷰 분석 서버(review-insight MAX_TEXT)·입력칸(maxlength)과 같은 1000자
    rating: int | None = Field(default=None, ge=1, le=5)
    channel: str | None = None


def create_app(demo: Demo | None = None, assistant: AssistantProxy | None = None) -> FastAPI:
    # 저장 위치는 여기서만 환경 변수로 정한다 (DB_HOST 가 있으면 PostgreSQL, 없으면 메모리·파일)
    demo = demo or Demo(Settings.from_env(), storage=open_store(app_name="ic26-web"))
    assistant = assistant or AssistantProxy.from_settings(demo.s)   # 시험에서는 가짜 상권 서비스를 넣은 것을 줄 수 있다

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        getattr(demo.storage, "close", lambda: None)()      # 서버를 끌 때 DB 연결 풀을 닫는다 (메모리 저장소는 할 일 없음)
        assistant.close()

    app = FastAPI(title="텔레토비 AI 비서 — 한 화면", docs_url="/docs", redoc_url=None, lifespan=lifespan)
    app.state.demo = demo
    app.state.assistant = assistant

    @app.middleware("http")
    async def _visitor(request: Request, call_next):
        """방문자마다 임의의 id 를 쿠키로 준다. 쿠키가 없거나 형식이 틀리면 새로 만들어 이 요청에도 쓰고 응답에 싣는다."""
        found = visitor_from_cookie(request.cookies.get(VISITOR_COOKIE))
        request.state.visitor_id = found or new_visitor_id()
        response = await call_next(request)
        if found is None and not request.url.path.startswith("/static/"):
            secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"
            response.set_cookie(VISITOR_COOKIE, request.state.visitor_id, max_age=VISITOR_COOKIE_SECONDS, path="/",
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
    def health():
        return demo.health()

    @app.get("/api/briefing")
    def briefing(request: Request):
        return demo.briefing(request.state.visitor_id)

    @app.get("/api/insight")
    def insight(request: Request):
        return demo.insight(request.state.visitor_id)

    @app.get("/api/cards")
    def cards(request: Request):
        return demo.cards(request.state.visitor_id)

    @app.post("/api/cards/{card_id}/run")
    def run(card_id: str, request: Request, body: RunIn | None = None):
        return demo.run(card_id, measures=body.measures if body else None, visitor=request.state.visitor_id)

    @app.post("/api/drafts/{draft_id}/approve")
    def approve(draft_id: str, body: ApproveIn, request: Request):
        return demo.approve(draft_id, body.text, body.original, visitor=request.state.visitor_id,
                            card_id=body.card_id, kind=body.kind)

    @app.get("/api/approvals")
    def approvals(request: Request):
        return {"items": demo.list_approvals(request.state.visitor_id)}

    @app.post("/api/reviews", status_code=201)
    def paste(body: PasteIn, request: Request):
        return demo.paste(body.text, body.rating, body.channel, visitor=request.state.visitor_id)

    @app.delete("/api/reviews/pasted")
    def reset_pasted(request: Request):
        return demo.reset_pasted(request.state.visitor_id)

    app.include_router(create_assistant_router(assistant))

    @app.get("/")
    def page():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
# 실행: uvicorn web.main:create_app --factory  (import 할 때 앱을 만들지 않아 시험에서 가짜 데이터를 넣을 수 있음)
