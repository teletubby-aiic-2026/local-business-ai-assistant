"""종합 리포트의 주간·월간 보고서 — 열면 저장, 다시 열면 저장본 (6차 회의 11/20, Figma 06 'D1 종합 리포트').

| 메서드 | 경로                                     | 하는 일 |
|--------|------------------------------------------|---------|
| GET    | /api/reports/weekly?period=YYYY-MM-DD    | 주간 보고서 열기 (그 날이 든 월~일. 비우면 이번 주) |
| GET    | /api/reports/monthly?period=YYYY-MM      | 월간 보고서 열기 (비우면 이번 달) |
| POST   | /api/reports/weekly/regenerate?period=   | 주간 다시 만들기: 새로 계산해 저장본을 덮어씀 |
| POST   | /api/reports/monthly/regenerate?period=  | 월간 다시 만들기 |
| GET    | /api/reports/saved                       | 지금 가게의 저장된 보고서 목록 (기간이 늦은 것부터) |
| GET    | /api/reports/counts                      | 내 가게 전체의 저장된 주간·월간 보고서 수 (사장님 프로필 '보관한 보고서') |

저장 (로그인한 사장님만)
- 열기: 저장본이 있으면 저장본을 그대로 (만든 시각·낡았는지와 함께), 없으면 계산해서 저장하고 돌려준다.
- 저장 자리는 (지금 가게, 방문자 'u-<user_id>', 종류, 기간). 같은 가게라도 사장님마다 따로다 (붙여넣은 리뷰·답글 기록이 달라서).
  표는 db/schema.sql 의 reports, 저장소는 shared/storage 의 reports (save·get·list·count·delete).
- 게스트(로그인 안 함)는 지금처럼 계산만 하고 저장하지 않는다 (storage: "guest"). 저장소(DB)에 닿지 못하면 계산한 것을
  돌려주고 storage: "unavailable" (화면은 그대로 그린다).
- 일일은 저장하지 않는다 (홈·종합 리포트 위 요약 줄에서 /api/care/report/daily 로 그때그때).

계산 (모두 규칙, 모델 호출 없음)
- 보고서 본문(report): 리뷰 분석 서비스의 GET /report/weekly · GET /report/monthly?compare=true (care_proxy.fetch_json).
  가게는 지금 가게, 방문자는 이 요청의 방문자, now 는 이 서버의 시각으로 넘긴다 (기간 계산이 두 서버에서 같게).
- 승인한 글(approvals): 이 서버의 승인 기록(GET /api/approvals 와 같은 Demo.list_approvals) 가운데 승인 시각이 그 기간 안인 것.
  글 종류는 저장소의 details(card_id·kind)로 나눈다: 답글(reply_draft) · 안내문(prevention_notice·공지) · 홍보(맞춤 마케팅 글·쿠폰 홍보) · 그 밖.
- 마케팅 숫자(marketing): 승인한 홍보 글 수만 승인 기록으로 채운다. 쿠폰 사용률·광고 건당 비용·공지 전후 불만 재발은
  이 보고서가 읽는 자료에 없어서 null (화면은 '–'). 없는 숫자를 지어내지 않는다.

낡음 판정 (stale)
- 저장본을 만든 시각(report.until)이 기간 끝(끝날 23:59:59)보다 이르면 = 진행 중에 만든 저장본이면, 열 때 지금 값을 한 번 더 계산해
  견준다 (규칙 계산이라 빠름, 모델을 부르지 않음). 기간이 다 끝난 뒤에 만든 저장본은 다시 계산하지 않는다 (stale: null).
- 견주는 것: 리뷰 수(new_reviews = 지금 − 저장본), 응대 기록(점수·기한 넘김·묶음 답글 수), 그 기간 승인한 글 수,
  기간이 저장 뒤에 끝났는지(period_closed). 하나라도 다르면 stale.is_stale = true → 화면이 '다시 만들면 반영돼요'.
  지금 값을 계산하지 못하면 {"checked": false}.
- 알려진 빈틈: 기간이 끝난 뒤 만든 저장본은, 그 뒤에 붙여넣은 리뷰를 지우는(데모 다시 하기) 일이 있어도 낡았다고 하지 않는다.

응답 모양 (열기·다시 만들기)
  {kind, period: {key, start, end, label, range, in_progress}, nav: {prev, next},
   storage: "saved"|"guest"|"unavailable", saved: bool, created_at, made_now: bool, stale: null|{…},
   report: {리뷰 분석 서비스 응답}, approvals: {total, reply, notice, promo, other}, marketing: {…}}
실패는 {"error": {"message", "state"}} (고객응대 프록시와 같은 모양, 500 없음): 기간 형식·미래 기간 400 invalid,
리뷰 분석 서비스 문제는 care_proxy 의 state(off·down·slow·busy·error, 서비스가 준 400 은 그 문장).
"""
from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from shared.storage import clean_visitor_id, is_valid_visitor_id

from .care_proxy import CareError

log = logging.getLogger("web.reports")

KST = timezone(timedelta(hours=9))
KINDS = ("weekly", "monthly")
REPORT_VERSION = "rules-1"          # reports.prompt_version: 문장 틀 판 (모델을 부르지 않음). 틀을 바꾸면 올린다
BUNDLE_VERSION = 1                  # reports.numbers 묶음 모양의 판. 다른 판의 저장본은 열 때 새로 만든다
LIST_LIMIT = 60
BACK_WEEKS, BACK_MONTHS = 52, 12    # '지난주'·'지난달' 이동은 1년 전까지 (예전 월간 달 이동과 같음)

REPLY_KINDS = {"reply_draft", "답글"}
NOTICE_KINDS = {"prevention_notice", "공지"}
PROMO_KINDS = {"coupon_promo", "홍보 글", "쿠폰 글", "가게 이야기 글", "남은 재료 글", "아이디어 글", "개선 소식", "기본 할 일 글",
               "마케팅 글"}
MARKETING_CARD = "marketing"        # marketing_proxy.MARKETING_CARD_ID 와 같은 값 (맞춤 마케팅 승인 기록의 card_id)


class ReportError(Exception):
    def __init__(self, state: str, message: str, http: int = 400):
        super().__init__(message)
        self.state, self.message, self.http = state, message, http


# ── 기간 ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Period:
    kind: str
    start: date
    end: date
    key: str            # 주간: 월요일 YYYY-MM-DD, 월간: YYYY-MM
    prev: str | None
    next: str | None
    in_progress: bool

    @property
    def label(self) -> str:
        """월간 '2026년 11월'. 주간 '11월 3주': 그 주의 목요일이 든 달의 몇째 주 (주의 나흘 이상이 든 달, ISO 8601 주와 같은 셈.
        달을 걸친 주가 두 달에 겹쳐 세이지 않는다). 화면은 날짜 범위(range)를 늘 같이 보여 준다."""
        if self.kind == "monthly":
            return f"{self.start.year}년 {self.start.month}월"
        thu = self.start + timedelta(days=3)
        return f"{thu.month}월 {(thu.day - 1) // 7 + 1}주"

    @property
    def range(self) -> str:
        return f"{self.start.month}/{self.start.day} ~ {self.end.month}/{self.end.day}"

    @property
    def closes_at(self) -> datetime:
        return datetime.combine(self.end, time(23, 59, 59), tzinfo=KST)

    def view(self) -> dict:
        return {"key": self.key, "start": self.start.isoformat(), "end": self.end.isoformat(), "label": self.label,
                "range": self.range, "in_progress": self.in_progress}


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def make_period(kind: str, value: str | None, today: date) -> Period:
    """기간 값 → Period. 주간은 아무 날짜나 받아 그 주(월~일)로, 월간은 YYYY-MM. 비우면 이번 주·이번 달. 오지 않은 기간은 400."""
    value = (value or "").strip()
    if kind == "weekly":
        try:
            day = date.fromisoformat(value) if value else today
        except ValueError:
            raise ReportError("invalid", "주간 기간은 YYYY-MM-DD 형식이어야 해요.") from None
        start = day - timedelta(days=day.weekday())
        end = start + timedelta(days=6)
        this = today - timedelta(days=today.weekday())
        prev = start - timedelta(days=7)
        nxt = start + timedelta(days=7)
        oldest = this - timedelta(weeks=BACK_WEEKS)
        key, prev_key, next_key = start.isoformat(), prev.isoformat() if prev >= oldest else None, nxt.isoformat() if nxt <= this else None
    elif kind == "monthly":
        try:
            y, m = (int(x) for x in value.split("-")) if value else (today.year, today.month)
            if not (1 <= m <= 12 and 1 <= y <= 9999) or (value and len(value.split("-")[1]) != 2):
                raise ValueError
            start = date(y, m, 1)
        except ValueError:
            raise ReportError("invalid", "월간 기간은 YYYY-MM 형식이어야 해요.") from None
        end = date(y, m, calendar.monthrange(y, m)[1])
        this = today.replace(day=1)
        prev = (start - timedelta(days=1)).replace(day=1)
        nxt = end + timedelta(days=1)
        back = this
        for _ in range(BACK_MONTHS):
            back = (back - timedelta(days=1)).replace(day=1)
        key, prev_key, next_key = _month_key(start), _month_key(prev) if prev >= back else None, _month_key(nxt) if nxt <= this else None
    else:
        raise ReportError("not_found", "없는 보고서 종류예요.", 404)
    if start > today:
        raise ReportError("invalid", "아직 오지 않은 기간이에요.")
    return Period(kind, start, end, key, prev_key, next_key, in_progress=end >= today)


def _parse(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=KST) if dt.tzinfo is None else dt


# ── 보고서 책 ────────────────────────────────────────────────────────────
class ReportBook:
    def __init__(self, hub, storage, clock: Callable[[], datetime] | None = None):
        self.hub = hub
        self.storage = storage
        self.clock = clock or (lambda: datetime.now(KST))

    def _now(self) -> datetime:
        return self.clock().astimezone(KST)

    # 계산 ------------------------------------------------------------------
    def build(self, store_id: str, visitor_id: str, period: Period, now: datetime) -> dict:
        """리뷰 분석 서비스의 보고서 + 승인한 글 수 → 저장할 묶음. 실패는 CareError."""
        params = {"now": now.isoformat(timespec="seconds")}
        if is_valid_visitor_id(visitor_id):
            params["visitor_id"] = visitor_id
        care = self.hub.care(store_id)
        if period.kind == "weekly":
            data = care.fetch_json("/report/weekly", {**params, "week": period.key})
        else:
            data = care.fetch_json("/report/monthly", {**params, "month": period.key, "compare": "true"})
        approvals = self.approvals(store_id, visitor_id, period)
        return {
            "version": BUNDLE_VERSION, "kind": period.kind, "period": {"key": period.key, "start": period.start.isoformat(),
                                                                       "end": period.end.isoformat()},
            "report": data, "approvals": approvals,
            "marketing": {"promo_approved": approvals["promo"], "coupon_usage_rate": None, "ad_cost_per_order": None,
                          "notice_recurrence": None},
        }

    def approvals(self, store_id: str, visitor_id: str, period: Period) -> dict:
        """그 기간에 승인한 글 수 (답글·안내문·홍보·그 밖). 승인 기록을 읽지 못하면 0 (Demo 가 로그를 남김)."""
        demo = self.hub.demo(store_id)
        rows = demo.list_approvals(visitor_id)
        try:
            details = {d.get("draft_id"): d for d in demo.storage.approvals.details(demo.s.store_id, clean_visitor_id(visitor_id))}
        except Exception as exc:          # 종류를 못 읽으면 글 id 로만 나눈다 (맞춤 마케팅 글은 mkt-)
            log.warning("보고서: 승인한 글 종류를 읽지 못함 (%s)", exc.__class__.__name__)
            details = {}
        out = {"total": 0, "reply": 0, "notice": 0, "promo": 0, "other": 0}
        for r in rows:
            at = _parse(r.get("approved_at"))
            if at is None or not (period.start <= at.astimezone(KST).date() <= period.end):
                continue
            d = details.get(r.get("draft_id")) or {}
            kind, card, draft = d.get("kind"), d.get("card_id"), str(r.get("draft_id") or "")
            bucket = ("reply" if kind in REPLY_KINDS else "notice" if kind in NOTICE_KINDS
                      else "promo" if kind in PROMO_KINDS or card == MARKETING_CARD or draft.startswith("mkt-") else "other")
            out[bucket] += 1
            out["total"] += 1
        return out

    # 낡음 -------------------------------------------------------------------
    def stale(self, bundle: dict, store_id: str, visitor_id: str, period: Period, now: datetime) -> dict | None:
        saved = bundle.get("report") or {}
        until = _parse(saved.get("until"))
        if until is not None and until >= period.closes_at:
            return None                    # 기간이 다 끝난 뒤에 만든 저장본
        try:
            fresh = self.build(store_id, visitor_id, period, now)
        except CareError as exc:
            log.warning("보고서: 낡았는지 확인하지 못함 (%s)", exc.state)
            return {"checked": False}
        now_r = fresh["report"]
        replied = lambda r: sum(int(i.get("replied_count") or 0) for i in r.get("repeated_issues") or [])
        new_reviews = int(now_r.get("review_count") or 0) - int(saved.get("review_count") or 0)
        responses = (now_r.get("score_end"), now_r.get("late_count"), replied(now_r)) != \
                    (saved.get("score_end"), saved.get("late_count"), replied(saved))
        approvals = fresh["approvals"] != bundle.get("approvals")
        closed = now > period.closes_at
        return {"checked": True, "is_stale": bool(new_reviews or responses or approvals or closed), "new_reviews": new_reviews,
                "reviews_now": int(now_r.get("review_count") or 0), "responses_changed": responses,
                "approvals_changed": approvals, "period_closed": closed}

    # 열기 · 다시 만들기 ------------------------------------------------------
    def open(self, *, store_id: str, visitor_id: str, member: bool, kind: str, value: str | None, remake: bool = False) -> dict:
        now = self._now()
        period = make_period(kind, value, now.date())
        storage = "saved" if member else "guest"
        if member and not remake:
            try:
                row = self.storage.reports.get(store_id, kind, period.start, period.end, visitor_id=visitor_id)
            except Exception as exc:
                log.warning("보고서 저장본을 읽지 못함 (%s)", exc.__class__.__name__)
                row, storage = None, "unavailable"
            bundle = (row or {}).get("numbers") or {}
            if row and bundle.get("version") == BUNDLE_VERSION and isinstance(bundle.get("report"), dict):
                return self._view(period, bundle, storage="saved", created_at=row["created_at"], made_now=False,
                                  stale=self.stale(bundle, store_id, visitor_id, period, now))
        try:
            bundle = self.build(store_id, visitor_id, period, now)
        except CareError as exc:
            raise ReportError(exc.state, exc.message, exc.http) from None
        created_at = now.isoformat(timespec="seconds")
        if storage == "saved":
            try:
                row = self.storage.reports.save(store_id, kind, period.start, period.end, numbers=bundle,
                                                body_text=self._body(bundle), evidence_ids=self._evidence(bundle),
                                                prompt_version=REPORT_VERSION, created_at=now, visitor_id=visitor_id)
                created_at = row["created_at"]
            except Exception as exc:
                log.warning("보고서를 저장하지 못함 (%s)", exc.__class__.__name__)
                storage = "unavailable"
        return self._view(period, bundle, storage=storage, created_at=created_at, made_now=True, stale=None)

    @staticmethod
    def _body(bundle: dict) -> str:
        """보고서 문장 (고칠 것·제안 틀 문장, 줄마다). 저장 표의 body_text 칸."""
        lines = []
        for s in (bundle.get("report") or {}).get("suggestions") or []:
            lines.append(" — ".join(x for x in (s.get("title"), s.get("evidence"), s.get("text")) if x))
        return "\n".join(lines)

    @staticmethod
    def _evidence(bundle: dict) -> list[str]:
        return [str(i["issue_id"]) for i in (bundle.get("report") or {}).get("repeated_issues") or [] if i.get("issue_id")]

    @staticmethod
    def _view(period: Period, bundle: dict, *, storage: str, created_at: str, made_now: bool, stale: dict | None) -> dict:
        return {"kind": period.kind, "period": period.view(), "nav": {"prev": period.prev, "next": period.next},
                "storage": storage, "saved": storage == "saved", "created_at": created_at, "made_now": made_now, "stale": stale,
                "report": bundle.get("report"), "approvals": bundle.get("approvals"), "marketing": bundle.get("marketing")}

    # 목록 · 수 ----------------------------------------------------------------
    def saved(self, *, store_id: str, visitor_id: str, member: bool) -> dict:
        if not member:
            return {"storage": "guest", "items": []}
        try:
            rows = self.storage.reports.list(store_id, limit=LIST_LIMIT, visitor_id=visitor_id)
        except Exception as exc:
            log.warning("저장된 보고서 목록을 읽지 못함 (%s)", exc.__class__.__name__)
            return {"storage": "unavailable", "items": []}
        items, seen = [], set()
        for r in rows:
            key = (r["period_kind"], r["period_start"])
            if key in seen or r["period_kind"] not in KINDS:
                continue
            seen.add(key)
            start, end = date.fromisoformat(r["period_start"]), date.fromisoformat(r["period_end"])
            p = Period(r["period_kind"], start, end, start.isoformat() if r["period_kind"] == "weekly" else _month_key(start),
                       None, None, False)
            items.append({"kind": p.kind, "key": p.key, "start": r["period_start"], "end": r["period_end"], "label": p.label,
                          "range": p.range, "created_at": r["created_at"]})
        return {"storage": "saved", "items": items}

    def counts(self, *, store_ids, visitor_id: str, member: bool) -> dict:
        if not member:
            return {"storage": "guest", "weekly": 0, "monthly": 0}
        try:
            found = self.storage.reports.count(list(store_ids), visitor_id)
        except Exception as exc:
            log.warning("저장된 보고서 수를 읽지 못함 (%s)", exc.__class__.__name__)
            return {"storage": "unavailable", "weekly": None, "monthly": None}
        return {"storage": "saved", "weekly": found.get("weekly", 0), "monthly": found.get("monthly", 0)}

    def erase(self, store_ids, visitor_id: str) -> int:
        """계정 초기화·탈퇴에서 부를 자리: 이 사장님의 저장된 보고서를 가게마다 지운다 (account.py 연결은 통합 때)."""
        if not (isinstance(visitor_id, str) and visitor_id.startswith("u-")):
            raise ValueError("로그인한 사장님의 방문자 id 만 지울 수 있어요")
        return sum(self.storage.reports.delete(s, visitor_id) for s in dict.fromkeys(store_ids))


# ── 라우터 ──────────────────────────────────────────────────────────────
def _fail(exc: ReportError) -> JSONResponse:
    out = JSONResponse({"error": {"message": exc.message, "state": exc.state}}, status_code=exc.http)
    out.headers["Cache-Control"] = "no-store"
    return out


def _ok(data: dict) -> JSONResponse:
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


def _who(request: Request) -> tuple[str, str, bool, tuple]:
    who = getattr(request.state, "who", None)
    member = bool(who is not None and who.authenticated)
    stores = tuple(who.stores) if who is not None else ()
    return request.state.store_id, request.state.visitor_id, member, stores


PeriodQ = Query(None, max_length=10, description="주간: YYYY-MM-DD (그 날이 든 월~일), 월간: YYYY-MM. 비우면 이번 주·이번 달")


def create_reports_router(book: ReportBook) -> APIRouter:
    api = APIRouter(prefix="/api/reports", tags=["reports"])

    def guarded(work):
        try:
            return _ok(work())
        except ReportError as exc:
            return _fail(exc)
        except Exception as exc:          # 우리 쪽 버그. 화면 전체가 죽지 않게 이 칸에만 알린다
            log.exception("보고서 예상 못한 오류 (%s)", exc.__class__.__name__)
            return _fail(ReportError("error", "보고서를 만들지 못했어요. 잠시 뒤 다시 해 주세요.", 503))

    @api.get("/saved")
    def saved(request: Request):
        store_id, visitor_id, member, _ = _who(request)
        return guarded(lambda: book.saved(store_id=store_id, visitor_id=visitor_id, member=member))

    @api.get("/counts")
    def counts(request: Request):
        _, visitor_id, member, stores = _who(request)
        return guarded(lambda: book.counts(store_ids=stores, visitor_id=visitor_id, member=member))

    @api.get("/{kind}")
    def open_report(kind: Literal["weekly", "monthly"], request: Request, period: str | None = PeriodQ):
        store_id, visitor_id, member, _ = _who(request)
        return guarded(lambda: book.open(store_id=store_id, visitor_id=visitor_id, member=member, kind=kind, value=period))

    @api.post("/{kind}/regenerate")
    def regenerate(kind: Literal["weekly", "monthly"], request: Request, period: str | None = PeriodQ):
        store_id, visitor_id, member, _ = _who(request)
        return guarded(lambda: book.open(store_id=store_id, visitor_id=visitor_id, member=member, kind=kind, value=period,
                                         remake=True))

    return api
