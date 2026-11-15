"""고객응대 API: 가게 정보 · 받은함 · 문의 · 답변 초안 · 약속 장부, 그리고 손님용 공개 API.

main.py 가 make_routers(...) 로 붙인다.
- 사장님용(토큰 검사): /api/review-insight/profile·inbox·inquiries·promises
- 손님용(토큰 없음):   /api/review-insight/public/{가게}/... — 문의 페이지(/s/{가게})가 부른다. 글자 수·횟수 제한
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app import care, foreign_menu, inquiry, profile as prof, service
from app.sources import capture

VISITOR_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
# 손님용 공개 API 횟수 제한: 손님(접속 주소) 1명당 1분에 10건, 가게 1곳에 1분 60건 (메모리, 서버마다 따로)
LIMITER = inquiry.RateLimit()


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_id: str = service.DEFAULT_STORE
    visitor_id: Optional[str] = Field(None, pattern=VISITOR_PATTERN)
    changes: dict[str, Any] = Field(..., description="고칠 묶음만: basic·order·menu·policy·reply·foreign (묶음 통째로 바뀜)")


class NoticeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_id: str = service.DEFAULT_STORE
    visitor_id: Optional[str] = Field(None, pattern=VISITOR_PATTERN)
    kind: Literal["closed", "sold_out", "hours", "other"] = "other"
    text: str = Field(..., min_length=1, max_length=200)
    start: str = Field(..., description="YYYY-MM-DD")
    end: str = Field(..., description="YYYY-MM-DD (이날까지 보이고, 지나면 저절로 빠짐)")
    menu: Optional[str] = None
    hours: Optional[str] = None


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_id: str = service.DEFAULT_STORE
    visitor_id: Optional[str] = Field(None, pattern=VISITOR_PATTERN)
    question: str = Field(..., min_length=2, max_length=300)
    answer: str = Field(..., min_length=1, max_length=500)


class InquiryStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_id: str = service.DEFAULT_STORE
    visitor_id: Optional[str] = Field(None, pattern=VISITOR_PATTERN)
    status: Literal["replied", "skipped", "new"] = "replied"
    reply_text: Optional[str] = Field(None, min_length=1, max_length=1000)
    learn: bool = Field(False, description="true 면 이 답을 가게 정보의 '배운 답'으로 저장 → 다음 비슷한 문의에 자동으로 씀")
    at: Optional[str] = None


class PublicInquiryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(..., min_length=2, max_length=500)


def make_routers(classifier: Callable, error: Callable, check_token) -> tuple[APIRouter, APIRouter]:
    owner = APIRouter(prefix="/api/review-insight", tags=["customer-care"], dependencies=[Depends(check_token)])
    public = APIRouter(prefix="/api/review-insight/public", tags=["customer-care-public"])
    limiter = LIMITER

    def now_of(value: str | None) -> datetime:
        return service.parse_time(value, "now") or datetime.now(service.KST)

    # ── 가게 정보 ──
    @owner.get("/profile")
    def get_profile(store_id: str = Query(service.DEFAULT_STORE), visitor_id: Optional[str] = Query(None, pattern=VISITOR_PATTERN),
                    now: Optional[str] = Query(None)):
        """응대용 가게 정보 + 오늘 영업시간·품절·유효한 공지 + 처음 설정 상태(setup.done, missing)."""
        try:
            return prof.view(prof.load(store_id, visitor_id), now_of(now))
        except ValueError as e:
            return error(400, "VALIDATION_ERROR", str(e))

    @owner.put("/profile")
    def put_profile(body: ProfileIn):
        """처음 설정과 이후 변경. 바꿀 묶음만 보내면 그 묶음만 바뀜 (예: {"changes": {"basic": {...}}})."""
        try:
            p = prof.update(body.store_id, body.visitor_id, body.changes)
        except ValidationError as e:
            return error(400, "VALIDATION_ERROR", "가게 정보 형식이 맞지 않습니다",
                         {"fields": {".".join(str(x) for x in err["loc"]): err["msg"] for err in e.errors()}})
        except ValueError as e:
            return error(400, "VALIDATION_ERROR", str(e))
        return prof.view(p, now_of(None))

    @owner.delete("/profile")
    def reset_profile(store_id: str = Query(service.DEFAULT_STORE), visitor_id: Optional[str] = Query(None, pattern=VISITOR_PATTERN)):
        """고친 가게 정보를 지우고 처음 값(합성 예시)으로 되돌림."""
        prof.reset(store_id, visitor_id)
        return prof.view(prof.load(store_id, visitor_id), now_of(None))

    @owner.post("/profile/notices", status_code=201)
    def add_notice(body: NoticeIn):
        """임시 공지 (임시휴무 closed · 품절 sold_out · 시간 변경 hours · 기타 other). end 가 지나면 저절로 빠짐."""
        try:
            n = prof.add_notice(body.store_id, body.visitor_id, body.model_dump(exclude={"store_id", "visitor_id"}))
        except ValidationError as e:
            return error(400, "VALIDATION_ERROR", "공지 형식이 맞지 않습니다",
                         {"fields": {".".join(str(x) for x in err["loc"]): err["msg"] for err in e.errors()}})
        except ValueError as e:
            return error(400, "VALIDATION_ERROR", str(e))
        return {"notice": n.model_dump(mode="json")}

    @owner.delete("/profile/notices/{notice_id}")
    def delete_notice(notice_id: str, store_id: str = Query(service.DEFAULT_STORE),
                      visitor_id: Optional[str] = Query(None, pattern=VISITOR_PATTERN)):
        if not prof.remove(store_id, visitor_id, "notices", notice_id):
            return error(404, "NOT_FOUND", f"없는 공지입니다: {notice_id}")
        return {"deleted": notice_id}

    @owner.post("/profile/answers", status_code=201)
    def add_answer(body: AnswerIn):
        """배운 답 직접 추가 (보통은 문의에 답할 때 learn=true 로 저장)."""
        return {"answer": prof.add_answer(body.store_id, body.visitor_id, body.question, body.answer).model_dump(mode="json")}

    @owner.delete("/profile/answers/{answer_id}")
    def delete_answer(answer_id: str, store_id: str = Query(service.DEFAULT_STORE),
                      visitor_id: Optional[str] = Query(None, pattern=VISITOR_PATTERN)):
        if not prof.remove(store_id, visitor_id, "answers", answer_id):
            return error(404, "NOT_FOUND", f"없는 답입니다: {answer_id}")
        return {"deleted": answer_id}

    @owner.post("/profile/menu/capture")
    async def menu_capture(file: UploadFile = File(..., description="메뉴판 사진·캡처 1장 (png·jpg·webp)"),
                           store_id: str = Form(service.DEFAULT_STORE),
                           visitor_id: Optional[str] = Form(None, pattern=VISITOR_PATTERN),
                           q_store: Optional[str] = Query(None, alias="store_id"),
                           q_visitor: Optional[str] = Query(None, alias="visitor_id", pattern=VISITOR_PATTERN)):
        """메뉴판 사진 → HCX-005 가 옮겨 적은 메뉴·가격 후보. 저장하지 않음: 확인 뒤 PUT /profile 의 menu 로 저장."""
        store_id, visitor_id = q_store or store_id, q_visitor or visitor_id
        from app import main
        data = await file.read(capture.max_bytes() + 1)
        await file.close()
        try:
            result = await run_in_threadpool(main.reader().read, data, kind="menu")     # 막히는 읽기는 스레드에서 (리뷰 캡처와 같은 이유)
        except capture.CaptureError as e:
            return error(e.status, e.code, e.message, e.details, e.retryable)
        finally:
            del data
        known = {m.name for m in prof.load(store_id, visitor_id).menu}
        cands = [r | {"exists": r["name"] in known} for r in result.reviews]
        return {"candidates": cands, "count": len(cands), "demo": result.demo, "pieces": result.pieces,
                "warnings": result.warnings, "engine": "demo" if result.demo else main.reader().model}

    # ── 다국어 메뉴판 ──
    @owner.get("/menu/foreign")
    def get_foreign_menu(lang: str = Query("en", description="en | ja | zh-CN"), store_id: str = Query(service.DEFAULT_STORE),
                         visitor_id: Optional[str] = Query(None, pattern=VISITOR_PATTERN)):
        """외국인 손님용 메뉴판 초안 (가게 정보 메뉴 → 로마자·번역 이름·재료·맵기·알레르기·가격) + 확인할 것(checks).
        사장님이 번역을 고치려면 PUT /profile 의 foreign.overrides."""
        try:
            return foreign_menu.build(service.store(store_id), prof.load(store_id, visitor_id), lang)
        except ValueError as e:
            return error(400, "VALIDATION_ERROR", str(e))

    @owner.get("/menu/foreign/print", response_class=HTMLResponse)
    def print_foreign_menu(lang: str = Query("en"), store_id: str = Query(service.DEFAULT_STORE),
                           visitor_id: Optional[str] = Query(None, pattern=VISITOR_PATTERN)):
        """인쇄용 A4 페이지 (HTML). 브라우저의 인쇄 → 'PDF로 저장'으로 PDF 를 만든다."""
        try:
            menu = foreign_menu.build(service.store(store_id), prof.load(store_id, visitor_id), lang)
        except ValueError as e:
            return error(400, "VALIDATION_ERROR", str(e))
        return HTMLResponse(foreign_menu.render(menu, datetime.now(service.KST)), headers={"Cache-Control": "no-store"})

    # ── 받은함 ──
    @owner.get("/inbox")
    def get_inbox(store_id: str = Query(service.DEFAULT_STORE), visitor_id: Optional[str] = Query(None, pattern=VISITOR_PATTERN),
                  kind: Optional[str] = Query(None, description="review | inquiry"),
                  intent: Optional[str] = Query(None, description="complaint | reservation | question | praise | other"),
                  needs_owner: Optional[bool] = Query(None, description="true 면 사장님 확인 필수만"),
                  open: bool = Query(False, description="true 면 아직 처리 안 한 것만"),
                  since: Optional[str] = Query(None, description="이 시각 뒤에 받은 것만 (새 항목 알림용)"),
                  limit: int = Query(50, ge=1, le=200), now: Optional[str] = Query(None)):
        """리뷰와 문의를 한 목록으로. 열린 '사장님 확인 필수' → 기한 가까운 순 → 나머지 최신순."""
        try:
            return care.inbox(classifier(), store_id, visitor_id, now_of(now), kind=kind, intent=intent,
                              needs_owner=needs_owner, open_only=open, since=since, limit=limit)
        except ValueError as e:
            return error(400, "VALIDATION_ERROR", str(e))

    # ── 문의 ──
    @owner.post("/inquiries/{item_id}/status")
    def inquiry_status(item_id: str, body: InquiryStatusIn):
        """문의에 답장(replied)·건너뜀(skipped). learn=true 면 가게 정보의 '배운 답'에 저장. 손님 페이지에 답이 보임."""
        if body.status == "replied" and not body.reply_text:
            return error(400, "VALIDATION_ERROR", "답장(replied)에는 reply_text 가 필요합니다")
        try:
            at = now_of(body.at)
            item = inquiry.set_status(body.store_id, body.visitor_id, item_id, body.status, body.reply_text, at)
        except LookupError:
            return error(404, "NOT_FOUND", f"없는 문의입니다: {item_id}")
        except ValueError as e:
            return error(400, "VALIDATION_ERROR", str(e))
        learned = None
        if body.learn and body.reply_text:
            learned = prof.add_answer(body.store_id, body.visitor_id, item["text"], body.reply_text, from_item=item_id).model_dump(mode="json")
        return {"item": item, "learned": learned}

    @owner.post("/inquiries/{item_id}/draft")
    def inquiry_draft(item_id: str, store_id: str = Query(service.DEFAULT_STORE),
                      visitor_id: Optional[str] = Query(None, pattern=VISITOR_PATTERN)):
        """문의 답 초안. 가게 정보에 있는 사실만 (live 는 HCX-005 + 코드 검사, 아니면 틀 문장)."""
        try:
            return care.draft(store_id, visitor_id, item_id, now_of(None))
        except LookupError:
            return error(404, "NOT_FOUND", f"없는 문의입니다: {item_id}")

    @owner.get("/promises")
    def get_promises(store_id: str = Query(service.DEFAULT_STORE), visitor_id: Optional[str] = Query(None, pattern=VISITOR_PATTERN),
                     now: Optional[str] = Query(None)):
        """약속 장부: 답글에 한 약속과 그 뒤 같은 불만이 다시 왔는지 (broken·watching·kept, 문의 약속은 check)."""
        try:
            return care.promises(classifier(), store_id, visitor_id, now_of(now))
        except ValueError as e:
            return error(400, "VALIDATION_ERROR", str(e))

    # ── 손님용 (토큰 없음) ──
    @public.get("/{store_id}/info")
    def public_info(store_id: str, now: Optional[str] = Query(None)):
        """문의 페이지 머리: 가게 이름·오늘 영업시간·공지·자주 묻는 질문. 내부 정책·배운 답의 출처 등은 내보내지 않음."""
        store = service.store(store_id)
        at = now_of(now)
        p = prof.load(store_id)
        hours, notices = prof.hours_on(p, at.date())
        faq = []
        for q in ("영업시간이 어떻게 되나요?", "쉬는 날이 언제예요?", "주차 되나요?", "배달 되나요?", "최소 주문 금액이 얼마예요?", "메뉴 뭐 있어요?"):
            d = inquiry.decide(p, q, at)
            if d["auto_answer"]:
                faq.append({"q": q, "a": d["auto_answer"]})
        for a in p.answers[-5:]:
            faq.append({"q": a.question, "a": a.answer})
        return {"store_id": store_id, "name": store["name"], "business_type_name": store.get("business_type_name"),
                "today": {"date": at.date().isoformat(), "hours": hours}, "notices": [n.text for n in notices],
                "faq": faq, "data_origin": "synthetic",
                "notice": "시연용 가상 가게입니다. 연락처·주문번호는 적지 마세요 (적으면 가립니다)."}

    @public.post("/{store_id}/inquiries", status_code=201)
    def public_ask(store_id: str, body: PublicInquiryIn, request: Request):
        """손님 문의 1건. 가게 정보로 답할 수 있으면 바로 답, 아니면 사장님 받은함으로. 확인 번호(code)로 나중에 답 확인."""
        service.store(store_id)                         # 없는 가게면 404
        client = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")
        if not limiter.allow(client, store_id):
            return error(429, "RATE_LIMITED", "문의가 너무 많아요. 1분 뒤 다시 남겨 주세요", retryable=True)
        text, masked = service.mask_pii(" ".join(body.text.split()))
        at = datetime.now(service.KST)
        p = prof.load(store_id)
        from app.models import Review
        probe = Review("probe", store_id, None, None, text, at.isoformat(timespec="seconds"), "paste")
        from app.classify import Classifier
        negative = Classifier("mock").classify([probe])[0].negative_topics      # 규칙 분류만 (모델 호출 없음)
        decision = inquiry.decide(p, text, at, negative)
        item = inquiry.add(store_id, None, text, at, decision, masked)       # 가게 공용 받은함
        return inquiry.public_view(item) | {"forwarded": item["reply"] is None,
                                            "message": "사장님께 전달했어요. 이 번호로 답을 확인할 수 있어요" if item["reply"] is None
                                            else "가게 정보로 바로 답했어요"}

    @public.get("/{store_id}/inquiries/{code}")
    def public_check(store_id: str, code: str):
        """확인 번호로 내 문의의 답 보기."""
        item = next((x for x in inquiry.load(store_id) if x["code"] == code), None)
        if item is None:
            return error(404, "NOT_FOUND", "없는 확인 번호입니다")
        return inquiry.public_view(item)

    return owner, public
