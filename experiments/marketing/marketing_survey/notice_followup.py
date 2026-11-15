"""개선 인증 소식(데모) — 공지 기준일(오늘) 앞뒤 14일 동안 "같은 불만" 리뷰 수를 코드가 센다.
AI 호출 없음, 전부 코드.

"같은 불만" = card.review_ids 로 뽑은 리뷰(c6.notice.generate_prevention_notice 의 target_reviews
와 같은 기준). created_at(ISO 8601)의 날짜만 보고 앞 14일/뒤 14일에 속하는지 가른다.

이후(after) < 이전(before) 이면 개선됐다고 보고 코드 템플릿 소식 글(숫자는 코드 값만, "리뷰 기준"
표시)을 만든다. 아니면 글을 만들지 않고 "아직 홍보하지 말고 원인 다시 보기"만 안내한다.
예측 문장은 쓰지 않는다 — "이전 N건 -> 이후 M건"처럼 이미 일어난 일만 말한다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

WINDOW_DAYS = 14

TODO_RECHECK_CAUSE = "아직 홍보하지 말고 원인 다시 보기"

_NOTICE_FOLLOWUP_TMPL = (
    "최근 {topic} 관련 불만이 줄었습니다.\n"
    "공지 전 {window}일 {before}건에서 공지 후 {window}일 {after}건으로 줄었습니다(리뷰 기준).\n"
    "앞으로도 지금의 조치를 계속하겠습니다."
)


def _review_date(review) -> date:
    return datetime.fromisoformat(review.created_at).date()


def _target_reviews(ctx, card) -> list:
    """card.review_ids 로 뽑은 리뷰만(c6.notice 가 쓰는 target_reviews 와 같은 기준)."""
    review_map = {r.review_id: r for r in ctx.reviews}
    return [review_map[rid] for rid in card.review_ids if rid in review_map]


def count_before_after(ctx, card, today: date | None = None) -> dict:
    """공지 기준일(today) 앞 14일[before_start, today) vs 뒤 14일[today, after_end] 리뷰 수."""
    today = today or date.today()
    reviews = _target_reviews(ctx, card)
    before_start = today - timedelta(days=WINDOW_DAYS)
    after_end = today + timedelta(days=WINDOW_DAYS)

    before = sum(1 for r in reviews if before_start <= _review_date(r) < today)
    after = sum(1 for r in reviews if today <= _review_date(r) < after_end)
    return {"before": before, "after": after, "today": today.isoformat(), "window_days": WINDOW_DAYS}


def build_notice_followup(ctx, card, topic: str = "포장 누락", today: date | None = None) -> dict:
    counts = count_before_after(ctx, card, today)
    before, after = counts["before"], counts["after"]
    improved = after < before

    text = None
    todo = None
    if improved:
        text = _NOTICE_FOLLOWUP_TMPL.format(topic=topic, window=WINDOW_DAYS, before=before, after=after)
    else:
        todo = TODO_RECHECK_CAUSE

    return {
        "before": before, "after": after, "window_days": WINDOW_DAYS,
        "basis": "리뷰 기준", "improved": improved, "text": text, "todo": todo,
    }
