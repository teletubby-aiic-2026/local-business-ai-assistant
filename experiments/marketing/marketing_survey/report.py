"""마케팅 보고서 — 기록(records)에서 이번 주/이번 달 활동·쿠폰·광고비·불만 재발을 코드로 센다.
AI 호출 없음, 기대 효과·예측 없음, 기록에 없는 숫자는 만들지 않는다(없으면 그 덩어리를 비운다).

기간(services/review-insight/app/report.py 의 monthly 와 같은 경계, 한국 시간):
  monthly  그 달 1일 00:00 ~ min(그 달 마지막 날 23:59:59, 지금). 이전 기간 = 바로 앞 달 전체.
  weekly   그 주 월요일 00:00 ~ min(일요일 23:59:59, 지금). 이전 기간 = 바로 앞 주 전체.
  기록은 created_at 의 날짜가 기간 안(양 끝 포함)이면 센다.

marketing_section(store_id, period_kind, today=None, visitor_id=None) -> {
  period, demo,
  activity: {approved: {글 종류: 건수}, ideas_tried: [아이디어 이름]},
  cost: {coupon: {...} | None, ads: [{app, label, cost_per_order, profit_per_order, verdict, prev_verdict}]},
  fixed: [{complaint, before_14d, after_14d, after_complete}],
  next: [{title, why}] (0~3개)
}
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from marketing_survey import adspend, complaints, coupon_result, notice_followup, records, stores
from marketing_survey.execute import _card_by_kind

KST = records.KST
PERIOD_KINDS = ("weekly", "monthly")
KIND_NOTICE = "공지"
COMPLAINT_TOPIC = "포장 누락"  # notice_followup.build_notice_followup 의 기본 불만 이름과 같다
MAX_NEXT = 3

TITLE_COUPON_UP = coupon_result.TODO_LOW_USAGE
TITLE_IMPROVE_NEWS = "개선 소식 올리기"
TITLE_CAUSE_RECHECK = "원인 다시 보기"


def _md(iso: str) -> str:
    """'2026-11-21' -> '11/21' (화면·제안 문장용)."""
    d = date.fromisoformat(iso)
    return f"{d.month}/{d.day}"
TITLE_COUPON_INPUT = "쿠폰 결과 입력하기"
WHY_COUPON_INPUT = "쿠폰 결과를 입력하면 다음 보고서에 들어가요"


# ---------- 기간 ----------

def _day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=KST)


def _day_end(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=KST)


def period_bounds(period_kind: str, today: date) -> tuple[date, date, date, date]:
    """(시작일, 끝일, 이전 시작일, 이전 끝일). 끝일은 기간의 마지막 날(오늘이 아직 안 지났어도 그 날)."""
    if period_kind == "monthly":
        start = today.replace(day=1)
        end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
        prev_end = start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
    elif period_kind == "weekly":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        prev_start, prev_end = start - timedelta(days=7), start - timedelta(days=1)
    else:
        raise ValueError("period 는 weekly 또는 monthly 여야 해요")
    return start, end, prev_start, prev_end


def _row_date(row: dict) -> date | None:
    try:
        return datetime.fromisoformat(row["created_at"]).astimezone(KST).date()
    except (KeyError, TypeError, ValueError):
        return None


def _in(row: dict, start: date, end: date) -> bool:
    d = _row_date(row)
    return d is not None and start <= d <= end


# ---------- 덩어리 ----------

def _activity(sessions: list[dict], start: date, end: date) -> dict:
    approved: dict[str, int] = {}
    for r in sessions:
        if r.get("decision") == "approved" and _in(r, start, end):
            for kind in (r.get("result") or {}).get("kinds") or []:
                approved[kind] = approved.get(kind, 0) + 1
    ideas, seen = [], set()
    for r in sessions:
        if r.get("feature") == "idea" and _in(r, start, end):
            title = (r.get("result") or {}).get("title")
            if title and title not in seen:
                seen.add(title)
                ideas.append(title)
    return {"approved": approved, "ideas_tried": ideas}


def _coupon(runs: list[dict], start: date, end: date) -> dict | None:
    """기간 안에 입력한 쿠폰 결과를 합친다. 계산식은 coupon_result·adspend 와 같다."""
    mine = [r for r in runs if _in(r, start, end)]
    if not mine:
        return None
    issued = sum(int(r.get("issued") or 0) for r in mine)
    used = sum(int(r.get("used") or 0) for r in mine)
    spent = sum(coupon_result.total_discount_cost(int(r.get("used") or 0), int(r.get("discount_krw") or 0))
                for r in mine)
    breakeven = None
    margins_known = all(r.get("margin_pct") is not None for r in mine)
    if margins_known and used > 0:
        profit_sum = sum(int(r["used"]) * adspend.profit_per_order(int(r["avg_order_krw"]), int(r["margin_pct"]))
                         for r in mine)
        breakeven = adspend.breakeven_orders(spent, round(profit_sum / used))
    return {"issued": issued, "used": used, "usage_rate": coupon_result.usage_rate(issued, used),
            "discount_spent": spent, "breakeven_orders": breakeven, "coupon_orders": used}


def _latest_adspend(sessions: list[dict], start: date, end: date) -> dict | None:
    rows = [r for r in sessions if r.get("feature") == "adspend" and _in(r, start, end)]
    return max(rows, key=lambda r: r["created_at"], default=None)


def _ads(sessions: list[dict], start: date, end: date, prev_start: date, prev_end: date) -> list[dict]:
    now_row = _latest_adspend(sessions, start, end)
    if now_row is None:
        return []
    prev_row = _latest_adspend(sessions, prev_start, prev_end)
    prev = {t.get("channel"): t.get("verdict") for t in ((prev_row or {}).get("result") or {}).get("table") or []}
    out = []
    for t in (now_row.get("result") or {}).get("table") or []:
        if t.get("cost_per_order_won") is None:
            continue
        out.append({
            "app": t["channel"], "label": t.get("label") or adspend.AD_APP_LABELS.get(t["channel"], t["channel"]),
            "cost_per_order": t["cost_per_order_won"], "profit_per_order": t.get("profit_per_order_won"),
            "verdict": t.get("verdict"), "prev_verdict": prev.get(t["channel"]),
        })
    return out


def _fixed(sessions: list[dict], ctx, start: date, end: date, today: date) -> list[dict]:
    """공지 승인일 앞·뒤 14일 같은 불만 리뷰 수(notice_followup 과 같은 기준, 리뷰 created_at 의 날짜).
    승인일이 기간 안이거나, 승인 뒤 14일이 이 기간에 걸치면(승인일 ≥ 시작 − 14일) 센다."""
    if ctx is None:
        return []
    try:
        card = _card_by_kind(ctx, "complaint")
    except Exception:
        return []
    if card is None or not any(r.review_id in set(card.review_ids) for r in ctx.reviews):
        return []  # 리뷰가 없으면 이 칸을 숨긴다
    window = timedelta(days=notice_followup.WINDOW_DAYS)
    out = []
    for r in sessions:
        if r.get("decision") != "approved" or KIND_NOTICE not in ((r.get("result") or {}).get("kinds") or []):
            continue
        d = _row_date(r)
        if d is None or not (start - window <= d <= end) or d > today:
            continue
        # 그 안내문이 다룬 불만 주제(승인 기록의 answers.complaint_topic)로 센다. 없으면(예전 기록) 불만 카드 그대로 (11/21 QA)
        chosen = (r.get("answers") or {}).get("complaint_topic")
        topic_card = complaints.topic_card(ctx, chosen) if chosen else None
        name = complaints.topic_label(chosen) if topic_card is not None else COMPLAINT_TOPIC
        counts = notice_followup.count_before_after(ctx, topic_card or card, d)
        ends = d + window  # 뒤 14일 확인이 끝나는 날(이 날까지 포함해 본다)
        complete = ends <= today
        tile = (f"{name} 불만 재발 (공지 전·후 14일)" if complete
                else f"{name} 불만 재발 (진행 중, {_md(ends.isoformat())} 확정)")
        out.append({
            "complaint": name, "approved_on": d.isoformat(),
            "before_14d": counts["before"], "after_14d": counts["after"],
            "after_complete": complete, "window_ends": ends.isoformat(), "tile_label": tile,
        })
    return out


def _next(coupon: dict | None, ads: list[dict], fixed: list[dict]) -> list[dict]:
    """코드 규칙으로만 제안한다(기대 효과 숫자 없음). 위에서부터 채우고 3개에서 멈춘다."""
    out: list[dict] = []
    if coupon is not None and coupon["usage_rate"] is not None and coupon["usage_rate"] < coupon_result.LOW_USAGE_THRESHOLD:
        out.append({"title": TITLE_COUPON_UP,
                    "why": f"쿠폰 사용률이 {round(coupon['usage_rate'] * 100)}%예요(20% 미만)"})
    for a in ads:
        if a["verdict"] == adspend.VERDICT_LOSS:
            out.append({"title": f"{a['label']} 광고 조건 다시 보기",
                        "why": f"주문 1건에 광고비 {a['cost_per_order']:,}원, 1건에 남는 돈은 약 {a['profit_per_order']:,}원이에요"})
    for f in fixed:
        if f["before_14d"] <= 0:
            continue  # 공지 전에 불만이 없었으면 비교할 게 없다
        if f["after_14d"] == 0 and not f["after_complete"]:
            ends = _md(f["window_ends"])
            out.append({"title": f"{ends}에 다시 확인하고, 그때도 0건이면 개선 소식 올리기",
                        "why": f"공지 후 14일이 아직 안 끝났어요. 지금까지 '{f['complaint']}' 재발 0건이에요(리뷰 기준)"})
            break
        if f["after_14d"] == 0 and f["after_complete"]:
            out.append({"title": TITLE_IMPROVE_NEWS,
                        "why": f"'{f['complaint']}' 불만이 공지 전 14일 {f['before_14d']}건에서 공지 후 14일 0건이에요(리뷰 기준)"})
            break
        if f["after_14d"] > 0 and f["after_complete"]:
            out.append({"title": TITLE_CAUSE_RECHECK,
                        "why": f"공지 후 14일에도 '{f['complaint']}' 불만이 {f['after_14d']}건 있었어요(리뷰 기준)"})
            break
    if coupon is None:
        out.append({"title": TITLE_COUPON_INPUT, "why": WHY_COUPON_INPUT})
    return out[:MAX_NEXT]


# ---------- 진입점 ----------

def marketing_section(store_id: str, period_kind: str = "monthly", today: date | None = None,
                      visitor_id: str | None = None) -> dict:
    """visitor_id 가 있으면 그 방문자의 기록만 센다 (없으면 데모 기록, demo: true). records.load_for_report 참고."""
    today = today or datetime.now(KST).date()
    start, end, prev_start, prev_end = period_bounds(period_kind, today)
    rows, demo = records.load_for_report(store_id, visitor_id)
    sessions = [r for r in rows if r.get("table") == records.SESSIONS]
    runs = [r for r in rows if r.get("table") == records.COUPON_RUNS]
    ctx = stores.get_ctx(store_id)

    coupon = _coupon(runs, start, end)
    ads = _ads(sessions, start, end, prev_start, prev_end)
    fixed = _fixed(sessions, ctx, start, end, today)
    until = _day_end(min(end, today))  # 아직 안 온 날은 세지 않는다
    return {
        "store_id": store_id,
        "period": {
            "kind": period_kind, "start": start.isoformat(), "end": end.isoformat(),
            "until": until.isoformat(timespec="seconds"),
            "prev_start": prev_start.isoformat(), "prev_end": prev_end.isoformat(),
            **({"month": f"{start.year:04d}-{start.month:02d}"} if period_kind == "monthly" else {}),
        },
        "demo": demo,
        "activity": _activity(sessions, start, end),
        "cost": {"coupon": coupon, "ads": ads},
        "fixed": fixed,
        "next": _next(coupon, ads, fixed),
    }
