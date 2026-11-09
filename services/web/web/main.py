"""C7 한 화면 웹. 실행: services/web/run.sh (README 참고)

| 메서드 | 경로                          | 화면 단계 |
|--------|-------------------------------|-----------|
| GET    | /api/health                   | 맨 위 '동작/모의' 띠, 막힘 안내 |
| GET    | /api/briefing                 | ① 오늘의 브리핑 |
| GET    | /api/cards                    | ② 추천 카드 2장 |
| POST   | /api/cards/{card_id}/run      | ③ 결과물 생성 |
| POST   | /api/drafts/{draft_id}/approve| ④ 승인 (수정 글 포함) |
| GET    | /api/approvals                | ④ 처리 완료 기록 |
| POST   | /api/reviews                  | S2 직접 붙여넣기 (#14 로 전달) |
| DELETE | /api/reviews/pasted           | 붙여넣은 리뷰 지우기 (데모 다시 하기) |
| POST   | /api/c9/record                | 지금 화면을 발표 모드 저장본으로 |
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .demo import Demo, DemoError
from .settings import Settings

STATIC = Path(__file__).resolve().parent / "static"


class ApproveIn(BaseModel):
    text: str | None = None          # 사장님이 고친 글 (안 고쳤으면 원문과 같음)
    original: str | None = None      # 생성된 원문


class PasteIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    rating: int | None = Field(default=None, ge=1, le=5)
    channel: str | None = None


def create_app(demo: Demo | None = None) -> FastAPI:
    demo = demo or Demo(Settings.from_env())
    app = FastAPI(title="텔레토비 AI 비서 — 한 화면", docs_url="/docs", redoc_url=None)
    app.state.demo = demo

    @app.exception_handler(DemoError)
    async def _demo_error(_: Request, exc: DemoError):
        return JSONResponse(status_code=exc.status, content={"error": {"message": str(exc)}})

    @app.get("/api/health")
    def health():
        return demo.health()

    @app.get("/api/briefing")
    def briefing():
        return demo.briefing()

    @app.get("/api/cards")
    def cards():
        return demo.cards()

    @app.post("/api/cards/{card_id}/run")
    def run(card_id: str):
        return demo.run(card_id)

    @app.post("/api/drafts/{draft_id}/approve")
    def approve(draft_id: str, body: ApproveIn):
        return demo.approve(draft_id, body.text, body.original)

    @app.get("/api/approvals")
    def approvals():
        return {"items": demo.approvals}

    @app.post("/api/reviews", status_code=201)
    def paste(body: PasteIn):
        return demo.paste(body.text, body.rating, body.channel)

    @app.delete("/api/reviews/pasted")
    def reset_pasted():
        return demo.reset_pasted()

    @app.post("/api/c9/record")
    def record():
        return demo.record()

    @app.get("/")
    def page():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
# 실행: uvicorn web.main:create_app --factory  (import 할 때 앱을 만들지 않아 시험에서 가짜 데이터를 넣을 수 있음)
