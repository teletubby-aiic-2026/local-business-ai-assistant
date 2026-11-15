"""리뷰 분석 API (C2 합성 리뷰 · C3 분류·묶음 · S2 직접 붙여넣기).

실행 (services/review-insight 에서): uvicorn app.main:app --port 8020
다른 화면(⑤ 한 화면)에서는 `router` 를 가져다 붙이면 됩니다:  app.include_router(router)
"""
from __future__ import annotations

import contextvars
import hmac
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.security import APIKeyHeader
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from app import accounts, report, service, storage  # noqa: E402  (.env 를 먼저 읽어야 함)
from app.classify import Classifier  # noqa: E402
from app.sources import capture  # noqa: E402

SPEC_VERSION = "0.1"   # docs/module-io-spec.md 의 공통 규칙(3·6·7·9절)을 따름. C3 내용은 결정안 v0.4
_token_header = APIKeyHeader(name="X-Access-Token", auto_error=False,
                             description="서버 .env 의 APP_ACCESS_TOKEN 값 (설정했을 때만 필요)")


class AccessDenied(Exception):
    pass


def check_token(token: str | None = Depends(_token_header)) -> None:
    """규격 9.1: 밖에 띄울 때 APP_ACCESS_TOKEN 을 정하면, 같은 값을 X-Access-Token 헤더로 보낸 요청만 받음.
    값을 정하지 않으면(로컬 개발) 검사하지 않음."""
    expected = os.getenv("APP_ACCESS_TOKEN", "").strip()
    if expected and not hmac.compare_digest((token or "").strip(), expected):
        raise AccessDenied()


router = APIRouter(prefix="/api/review-insight", tags=["review-insight"], dependencies=[Depends(check_token)])
_classifier: Classifier | None = None
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


def request_id() -> str:
    return _request_id.get() or f"req_{uuid.uuid4().hex[:6]}"


_reader: capture.CaptureReader | None = None


def reader() -> capture.CaptureReader:
    global _reader
    if _reader is None:
        _reader = capture.CaptureReader()
    return _reader


def classifier() -> Classifier:
    global _classifier
    if _classifier is None:
        _classifier = Classifier()
    return _classifier


def error(status: int, code: str, message: str, details: dict | None = None, retryable: bool = False):
    return JSONResponse(status_code=status, content={"error": {
        "code": code, "message": message, "retryable": retryable, "details": details or {},
        "request_id": request_id()}})


VISITOR_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"      # app/service.py 의 clean_visitor 와 같은 규칙 (파일 이름에 들어감)
VISITOR_DESC = ("방문자 id (선택). 영문·숫자·-·_ 1~64자. 주면 합성 리뷰에 이 방문자가 붙여넣은 리뷰만 더해 보여 주고, 분석하고, 지운다. "
                "안 주면 지금까지처럼 모두가 쓰는 공용 값")


class PasteIn(BaseModel):
    text: str = Field(..., description="리뷰 글 (1~1000자)")
    rating: Optional[int] = Field(None, description="별점 1~5, 모르면 비움")
    channel: Optional[str] = Field(None, description="baemin | coupangeats | yogiyo | naver_place, 모르면 비움")
    store_id: str = Field(service.DEFAULT_STORE, description="가게 ID")
    visitor_id: Optional[str] = Field(None, pattern=VISITOR_PATTERN, description=VISITOR_DESC)
    source: Optional[str] = Field(None, description="어디서 들어왔나: paste(기본) | capture(캡처 후보 확인) | app(가상 배달앱) | memo(매장 메모). "
                                                    "계약의 input_method 는 모두 paste 로 저장하고 이 값은 source 칸에 따로 둔다")
    menu: Optional[str] = Field(None, description="주문 메뉴 이름 (40자 이하, 가상 배달앱이 보냄). 리뷰 조회 응답의 menu 로 돌려줌")
    input_method: Optional[str] = Field(None, description="source 와 같은 뜻 (paste | capture | app | memo). 둘 다 주면 source 가 우선")


class StatusIn(BaseModel):
    status: str = Field(..., description="new | analyzed | drafted | replied | skipped (계약의 REVIEW_STATUSES)")
    reply_text: Optional[str] = Field(None, description="답글 글 (status=replied 일 때, 1~1000자). 리뷰 조회 응답의 reply 로 돌려줌")
    at: Optional[str] = Field(None, description="상태가 바뀐 시각 ISO 8601. 비우면 지금 (승인 시각을 따로 가진 화면 서버가 넘길 때)")
    store_id: str = Field(service.DEFAULT_STORE, description="가게 ID")
    visitor_id: Optional[str] = Field(None, pattern=VISITOR_PATTERN, description=VISITOR_DESC)


NowQ = Query(None, description="계산 기준 시각 ISO 8601 (시연·시험용). 비우면 지금")


def _now(value: str | None):
    return service.parse_time(value, "now") or service.datetime.now(service.KST)


StoreQ = Query(service.DEFAULT_STORE, description="가게 ID (기본: 발표 시나리오 가게 store_ongi)")
VisitorQ = Query(None, pattern=VISITOR_PATTERN, description=VISITOR_DESC)


class LoginIn(BaseModel):
    login_id: str = Field(..., max_length=64, description="가게 계정 아이디 (시연용: ongi · basak · mongle)")
    password: str = Field(..., max_length=200, description="비밀번호. 저장·로그하지 않음")


class SignupIn(LoginIn):
    store_name: str = Field(..., description="가게 이름 (1~40자)")
    business_type_name: Optional[str] = Field(None, description="업종 (선택, 20자 이하. 예: 분식)")
    signup_code: Optional[str] = Field(None, max_length=200, description="서버에 ACCOUNT_SIGNUP_CODE 를 정했을 때 필요한 가입 코드")


@router.post("/auth/login")
def login(body: LoginIn):
    """아이디·비밀번호 확인 → 그 계정의 가게. 화면 서버가 부르고, 받은 store_id 로 이후 요청의 가게를 정한다."""
    try:
        return accounts.login(body.login_id, body.password)
    except accounts.TooManyTries:
        return error(429, "TOO_MANY_TRIES", "로그인을 여러 번 틀렸습니다. 5분 뒤에 다시 해 주세요.", retryable=True)
    except accounts.LoginFailed:
        return error(401, "LOGIN_FAILED", "아이디나 비밀번호가 맞지 않습니다.")


@router.post("/auth/accounts", status_code=201)
def signup(body: SignupIn):
    """새 계정 + 새 가게 (합성 리뷰 없이 0건에서 시작)."""
    try:
        return accounts.signup(body.login_id, body.password, body.store_name, body.business_type_name, signup_code=body.signup_code)
    except PermissionError as e:
        return error(403, "SIGNUP_CODE_REQUIRED", str(e))
    except ValueError as e:
        return error(400, "VALIDATION_ERROR", str(e))


@router.get("/stores")
def list_stores():
    items = service.stores()
    return {"items": items, "count": len(items), "default": service.DEFAULT_STORE}


@router.get("/store")
def get_store(store_id: str = StoreQ):
    return service.store(store_id)


@router.get("/reviews")
def list_reviews(store_id: str = StoreQ, visitor_id: Optional[str] = VisitorQ,
                 since: Optional[str] = Query(None, description="이 시각(ISO 8601) 뒤에 실제로 받은 리뷰만, 받은 순서로. 응답의 server_time 을 다음 since 로 쓰면 됨"),
                 source: Optional[str] = Query(None, description="sample | paste | capture | app | memo 중 하나만")):
    """리뷰 목록. 항목마다 source(어디서), received_at(실제로 받은 시각, 합성 샘플은 null), reply(사장님 답글)가 붙는다."""
    server_time = service.datetime.now(service.KST).isoformat(timespec="seconds")
    try:
        rows = service.list_reviews(store_id, visitor_id, since=since, source=source)
    except ValueError as e:
        return error(400, "VALIDATION_ERROR", str(e))
    out = {"items": rows, "count": len(rows)}
    return out | {"server_time": server_time} if since is not None else out      # 규격의 목록 모양 {items,count} 은 그대로


@router.get("/reviews/{review_id}")
def get_review(review_id: str, store_id: str = StoreQ, visitor_id: Optional[str] = VisitorQ):
    """리뷰 한 건과 그 분류 결과 (규격 6절 #5와 같은 모양, 분석 = 주제 분류)."""
    review = next((r for r in service.all_reviews(store_id, visitor_id) if r.review_id == review_id), None)
    if review is None:
        return error(404, "REVIEW_NOT_FOUND", f"없는 리뷰입니다: {review_id}")
    c = classifier().classify([review])[0]
    meta = service.meta_for(store_id, visitor_id).get(review_id)
    d = service.decorate(review, meta)
    if not (meta or {}).get("status"):
        d["status"] = "analyzed"
    return {"review": d, "classification": c.to_dict()}


@router.post("/reviews/{review_id}/status")
def set_review_status(review_id: str, body: StatusIn):
    """답글 승인(replied)·건너뜀(skipped) 등 상태와 시각, 답글 글을 기록. 응대 기한·점수가 이 기록으로 계산된다."""
    try:
        review = service.set_status(body.store_id, body.visitor_id, review_id, body.status, reply_text=body.reply_text, at=body.at)
    except LookupError:
        return error(404, "REVIEW_NOT_FOUND", f"없는 리뷰입니다: {review_id}")
    except ValueError as e:
        return error(400, "VALIDATION_ERROR", str(e))
    return {"review": review}


@router.get("/response")
def get_response(store_id: str = StoreQ, visitor_id: Optional[str] = VisitorQ, now: Optional[str] = NowQ):
    """응대 기한과 점수 (규칙으로만 계산). 답글 대기 불만별 due_at·남은 시간, 점수(0~100)와 이유 목록."""
    try:
        at = _now(now)
    except ValueError as e:
        return error(400, "VALIDATION_ERROR", str(e))
    return {"store_id": store_id} | service.Timeline(classifier(), store_id, visitor_id).at(at)


@router.get("/report/daily")
def get_daily(store_id: str = StoreQ, visitor_id: Optional[str] = VisitorQ,
              date: Optional[str] = Query(None, description="YYYY-MM-DD (한국 날짜). 비우면 오늘"), now: Optional[str] = NowQ):
    """일일 요약: 그날 리뷰·불만 수, 기한 안 답글 수, 점수 변동과 이유, 내일 먼저 할 일 1개. 숫자·문장 모두 코드(틀 문장)."""
    try:
        at = _now(now)
        return report.daily(service.Timeline(classifier(), store_id, visitor_id), report.parse_day(date, at), at)
    except ValueError as e:
        return error(400, "VALIDATION_ERROR", str(e))


@router.get("/report/monthly/print", response_class=HTMLResponse)
def print_monthly(store_id: str = StoreQ, visitor_id: Optional[str] = VisitorQ,
                  month: Optional[str] = Query(None, description="YYYY-MM. 비우면 이번 달"), now: Optional[str] = NowQ):
    """월간 보고서 인쇄용 A4 (HTML). 브라우저 인쇄 → 'PDF로 저장'. 개선 제안은 체크 칸 할 일 목록."""
    try:
        at = _now(now)
        y, m = report.parse_month(month, at)
        data = report.monthly(service.Timeline(classifier(), store_id, visitor_id), y, m, at)
    except ValueError as e:
        return error(400, "VALIDATION_ERROR", str(e))
    name = service.store(store_id).get("name", store_id)
    return HTMLResponse(report.render_monthly(data, name, service.datetime.now(service.KST)), headers={"Cache-Control": "no-store"})


@router.get("/report/monthly")
def get_monthly(store_id: str = StoreQ, visitor_id: Optional[str] = VisitorQ,
                month: Optional[str] = Query(None, description="YYYY-MM. 비우면 이번 달"), now: Optional[str] = NowQ):
    """월간 보고서: 날마다 점수 추이, 반복 불만별 건수와 답글 뒤 재발 여부, 다음 달 개선 제안 (최대 3개)."""
    try:
        at = _now(now)
        y, m = report.parse_month(month, at)
        return report.monthly(service.Timeline(classifier(), store_id, visitor_id), y, m, at)
    except ValueError as e:
        return error(400, "VALIDATION_ERROR", str(e))


@router.get("/insight")
def get_insight(store_id: str = StoreQ, visitor_id: Optional[str] = VisitorQ):
    """C5 추천 카드·C6 생성이 쓰는 결과: 감정·주제 건수, 반복 불만 묶음, 리뷰별 분류."""
    return service.analyze(classifier(), store_id, visitor_id).to_dict()


@router.post("/reviews", status_code=201)
def paste_review(body: PasteIn):
    """S2 직접 붙여넣기 → 바로 분류 → 반복 묶음 다시 계산."""
    source = body.source or body.input_method or "paste"
    try:
        review = service.add_review(body.text, body.rating, body.channel, store_id=body.store_id,
                                    visitor_id=body.visitor_id, source=source, menu=body.menu)
    except ValueError as e:
        return error(400, "VALIDATION_ERROR", str(e))
    insight = service.analyze(classifier(), body.store_id, body.visitor_id)
    mine = next((c for c in insight.classifications if c.review_id == review.review_id), None)
    joined = [g.issue_id for g in insight.groups if review.review_id in g.review_ids]
    shown = service.decorate(review, service.meta_for(body.store_id, body.visitor_id).get(review.review_id))
    return {"review": shown | ({"status": "analyzed"} if mine else {}), "classification": mine.to_dict() if mine else None,
            "joined_issues": joined, "review_count": insight.review_count, "complaint_count": insight.complaint_count,
            "groups": [g.to_dict() for g in insight.groups],
            "repeated_issues": [i.to_dict() for i in insight.repeated_issues],
            "single_complaints": insight.single_complaints,
            "top_issue_id": insight.top_issue.issue_id if insight.top_issue else None}


@router.post("/reviews/capture")
async def capture_reviews(file: UploadFile = File(..., description="리뷰 화면 캡처 1장 (png·jpg·webp)"),
                          store_id: str = Form(service.DEFAULT_STORE),
                          visitor_id: Optional[str] = Form(None, pattern=VISITOR_PATTERN),
                          q_store: Optional[str] = Query(None, alias="store_id", description="쿼리로 주면 폼보다 우선 (화면 서버 프록시용)"),
                          q_visitor: Optional[str] = Query(None, alias="visitor_id", pattern=VISITOR_PATTERN)):
    """캡처 → HCX-005 가 옮겨 적은 리뷰 후보. 저장하지 않음: 사장님이 확인·수정한 뒤 POST /reviews 로 저장."""
    store_id, visitor_id = q_store or store_id, q_visitor or visitor_id
    limit = capture.max_bytes()
    data = await file.read(limit + 1)          # 메모리에서만 씀. 디스크·로그에 남기지 않음
    await file.close()
    try:
        # 읽기(Pillow·HCX 호출·재시도 대기)는 막히는 코드라 스레드에서 돌린다. 여기서 바로 부르면 캡처 하나가 끝날 때까지(5~20초)
        # 이 서비스의 다른 요청(/api/health 포함)이 모두 멈춘다 (11/15 통합 점검에서 4.8~18.1초 멈춤을 잼)
        result = await run_in_threadpool(reader().read, data)
    except capture.CaptureError as e:
        return error(e.status, e.code, e.message, e.details, e.retryable)
    finally:
        del data
    reviews = await run_in_threadpool(service.all_reviews, store_id, visitor_id)
    saved = {" ".join(r.text.split()) for r in reviews}
    candidates = []
    for r in result.reviews:
        text, masked = service.mask_pii(r["text"][:1000])
        candidates.append({"text": text, "rating": r["rating"], "pii_masked": masked,
                           "duplicate": " ".join(text.split()) in saved or " ".join(r["text"].split()) in saved})
    return {"candidates": candidates, "count": len(candidates), "demo": result.demo, "pieces": result.pieces,
            "warnings": result.warnings, "engine": "demo" if result.demo else reader().model,
            "next": "후보를 확인·수정한 뒤 POST /api/review-insight/reviews 로 한 건씩 저장하세요"}


@router.delete("/reviews/pasted")
def reset_pasted(store_id: str = StoreQ, visitor_id: Optional[str] = VisitorQ):
    """데모 다시 하기: 그 가게에 (그 방문자가) 붙여넣은 리뷰를 모두 지움 (합성 리뷰는 그대로)."""
    from app import inquiry
    if service.clean_visitor(visitor_id) == service.COMMON_VISITOR:
        inquiry.clear(store_id)              # 공용으로 부를 때만 손님 문의도 지움 (시연자 한 명의 '다시 하기'는 가게 공용 문의를 건드리지 않음)
    return {"deleted": service.clear_pasted(store_id, visitor_id)}


@asynccontextmanager
async def _lifespan(_: FastAPI):
    storage.database()      # DB_HOST 가 있는데 설정이 틀렸으면 켜질 때 멈춘다. DB 가 꺼져 있는 것은 괜찮다 (연결은 나중에 맺음)
    yield
    storage.close()


app = FastAPI(title="리뷰 분석 · 고객응대 (C2·C3·S2)", lifespan=_lifespan)
app.include_router(router)
from app.care_api import make_routers  # noqa: E402
_care, _public = make_routers(classifier, error, check_token)
app.include_router(_care)
app.include_router(_public)


@app.middleware("http")
async def _with_request_id(request: Request, call_next):
    """규격 6절: 모든 응답에 X-Request-Id, 오류 본문의 request_id 와 같은 값."""
    rid = f"req_{uuid.uuid4().hex[:6]}"
    token = _request_id.set(rid)
    try:
        response = await call_next(request)
    finally:
        _request_id.reset(token)
    response.headers["X-Request-Id"] = rid
    return response


@app.exception_handler(AccessDenied)
async def _denied(_: Request, exc: AccessDenied):
    return error(401, "UNAUTHORIZED", "접근 토큰이 없거나 틀렸습니다. X-Access-Token 헤더에 팀에서 정한 값을 넣어 주세요.")


@app.exception_handler(storage.StorageUnavailable)
async def _storage_down(_: Request, exc: storage.StorageUnavailable):
    """DB 에 닿지 못함 (장애 전환 중 등). 잠시 뒤 다시 하면 된다."""
    return error(503, "STORAGE_UNAVAILABLE", "저장소(DB)에 닿지 못했습니다. 잠시 뒤 다시 시도해 주세요.", retryable=True)


@app.exception_handler(service.StoreNotFound)
async def _no_store(_: Request, exc: service.StoreNotFound):
    return error(404, "STORE_NOT_FOUND", f"없는 가게입니다: {exc.args[0]}", {"stores": service.synthetic_store_ids()})


@app.exception_handler(RequestValidationError)
async def _bad_request(_: Request, exc: RequestValidationError):
    fields = {".".join(str(p) for p in e["loc"][1:]): e["msg"] for e in exc.errors()}
    return error(400, "VALIDATION_ERROR", "입력 형식이 맞지 않습니다", {"fields": fields})


@app.get("/")
def page():
    return FileResponse(ROOT / "app" / "static" / "index.html")


@app.get("/s/{store_id}")
def inquiry_page(store_id: str):
    """손님용 문의 페이지 (시연용). 통합 화면에서는 Nginx·화면 서버가 이 페이지와 /api/review-insight/public/* 만 밖에 연다."""
    service._dir(store_id)
    return FileResponse(ROOT / "app" / "static" / "inquiry.html")


@app.get("/health")
@app.get("/api/health")
def health():
    """규격 6절 #1"""
    c = classifier()
    return {"status": "ok", "mode": c.mode, "spec_version": SPEC_VERSION, "token_required": bool(os.getenv("APP_ACCESS_TOKEN", "").strip()),
            "models": {"review_classify": c.model if c.mode != "mock" else "rule"}, "data_origin": "synthetic"}
