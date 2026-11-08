"""리뷰 분석 API (C2 합성 리뷰 · C3 분류·묶음 · S2 직접 붙여넣기).

실행 (services/review-insight 에서): uvicorn app.main:app --port 8020
다른 화면(⑤ 한 화면)에서는 `router` 를 가져다 붙이면 됩니다:  app.include_router(router)
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from app import service  # noqa: E402  (.env 를 먼저 읽어야 함)
from app.classify import Classifier  # noqa: E402

router = APIRouter(prefix="/api/review-insight", tags=["review-insight"])
_classifier: Classifier | None = None


def classifier() -> Classifier:
    global _classifier
    if _classifier is None:
        _classifier = Classifier()
    return _classifier


def error(status: int, code: str, message: str, details: dict | None = None, retryable: bool = False):
    return JSONResponse(status_code=status, content={"error": {
        "code": code, "message": message, "retryable": retryable, "details": details or {},
        "request_id": f"req_{uuid.uuid4().hex[:6]}"}})


class PasteIn(BaseModel):
    text: str = Field(..., description="리뷰 글 (1~1000자)")
    rating: Optional[int] = Field(None, description="별점 1~5, 모르면 비움")
    channel: Optional[str] = Field(None, description="baemin | coupangeats | yogiyo | naver_place, 모르면 비움")
    store_id: str = Field(service.DEFAULT_STORE, description="가게 ID")


StoreQ = Query(service.DEFAULT_STORE, description="가게 ID (기본: 발표 시나리오 가게 store_ongi)")


@router.get("/stores")
def list_stores():
    return {"stores": service.stores(), "default": service.DEFAULT_STORE}


@router.get("/store")
def get_store(store_id: str = StoreQ):
    return service.store(store_id)


@router.get("/reviews")
def list_reviews(store_id: str = StoreQ):
    rows = service.all_reviews(store_id)
    return {"reviews": [r.to_dict() for r in sorted(rows, key=lambda r: r.created_at, reverse=True)], "count": len(rows)}


@router.get("/insight")
def get_insight(store_id: str = StoreQ):
    """C5 추천 카드·C6 생성이 쓰는 결과: 감정·주제 건수, 반복 불만 묶음, 리뷰별 분류."""
    return service.analyze(classifier(), store_id).to_dict()


@router.post("/reviews", status_code=201)
def paste_review(body: PasteIn):
    """S2 직접 붙여넣기 → 바로 분류 → 반복 묶음 다시 계산."""
    try:
        review = service.add_pasted(body.text, body.rating, body.channel, store_id=body.store_id)
    except ValueError as e:
        return error(400, "VALIDATION_ERROR", str(e))
    insight = service.analyze(classifier(), body.store_id)
    mine = next((c for c in insight.classifications if c.review_id == review.review_id), None)
    joined = [g.issue_id for g in insight.groups if review.review_id in g.review_ids]
    return {"review": review.to_dict(), "classification": mine.to_dict() if mine else None,
            "joined_issues": joined, "complaint_count": insight.complaint_count,
            "groups": [g.to_dict() for g in insight.groups],
            "repeated_issues": [i.to_dict() for i in insight.repeated_issues],
            "single_complaints": insight.single_complaints,
            "top_issue_id": insight.top_issue.issue_id if insight.top_issue else None}


@router.delete("/reviews/pasted")
def reset_pasted(store_id: str = StoreQ):
    """데모 다시 하기: 그 가게에 붙여넣은 리뷰를 모두 지움 (합성 리뷰는 그대로)."""
    return {"deleted": service.clear_pasted(store_id)}


app = FastAPI(title="리뷰 분석 (C2·C3·S2)")
app.include_router(router)


@app.exception_handler(service.StoreNotFound)
async def _no_store(_: Request, exc: service.StoreNotFound):
    return error(404, "STORE_NOT_FOUND", f"없는 가게입니다: {exc.args[0]}", {"stores": service.store_ids()})


@app.exception_handler(RequestValidationError)
async def _bad_request(_: Request, exc: RequestValidationError):
    fields = {".".join(str(p) for p in e["loc"][1:]): e["msg"] for e in exc.errors()}
    return error(400, "VALIDATION_ERROR", "입력 형식이 맞지 않습니다", {"fields": fields})


@app.get("/")
def page():
    return FileResponse(ROOT / "app" / "static" / "index.html")


@app.get("/health")
def health():
    return {"ok": True, "mode": classifier().mode}
