"""C3 반복 묶음: 같은 주제의 불만이 기간 안에 기준 건수 이상이면 '반복 불만'으로 묶습니다.

계산은 모두 코드가 합니다 (모델은 리뷰 한 건씩 주제만 고름).
시간대 구간은 서울시 상권 추정매출과 같은 6구간이라서, C5 카드가 '저녁(17~21시) 매출'과 바로 이어 볼 수 있습니다.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

import logging

from app.models import RepeatedIssue, Review, ReviewClassification, ReviewInsight
from app.topics import TOPICS, topic_name

log = logging.getLogger("review_insight.cluster")
TIME_BANDS = (("00~06시", 0, 6), ("06~11시", 6, 11), ("11~14시", 11, 14), ("14~17시", 14, 17), ("17~21시", 17, 21), ("21~24시", 21, 24))
MIN_COUNT = 3          # 이 건수 이상이면 반복
WINDOW_DAYS = 28       # 최근 4주
MAIN_BAND_SHARE = 0.6  # 한 시간대에 60% 이상 몰리면 '주로 이 시간대'


def time_band(iso: str) -> str:
    h = datetime.fromisoformat(iso).hour
    return next(name for name, a, b in TIME_BANDS if a <= h < b)


def build_insight(store_id: str, reviews: list[Review], classes: list[ReviewClassification], *,
                  end: datetime | None = None, window_days: int = WINDOW_DAYS, min_count: int = MIN_COUNT) -> ReviewInsight:
    by_id = {r.review_id: r for r in reviews}
    end = end or max(datetime.fromisoformat(r.created_at) for r in reviews)
    end_day = end.replace(hour=23, minute=59, second=59)
    start = (end_day - timedelta(days=window_days)).replace(hour=0, minute=0, second=0) + timedelta(days=1)
    mid = start + (end_day - start) / 2
    in_window = [c for c in classes if c.review_id in by_id and start <= datetime.fromisoformat(by_id[c.review_id].created_at) <= end_day]

    sentiment_counts = Counter(c.sentiment for c in in_window)
    topic_counts: dict[str, dict] = {}
    for c in in_window:
        for pol in ("positive", "negative"):
            for t in {h.topic for h in c.topics if h.polarity == pol}:
                topic_counts.setdefault(t, {"positive": 0, "negative": 0})[pol] += 1

    issues = []
    for topic in TOPICS:
        members = [c for c in in_window if topic in c.negative_topics]
        if len(members) < min_count:
            continue
        members.sort(key=lambda c: by_id[c.review_id].created_at)
        times = [datetime.fromisoformat(by_id[c.review_id].created_at) for c in members]
        bands = Counter(time_band(by_id[c.review_id].created_at) for c in members)
        band, n = bands.most_common(1)[0]
        issues.append(RepeatedIssue(
            issue_id=f"iss_{topic}", topic=topic, topic_name=topic_name(topic), review_count=len(members),
            review_ids=[c.review_id for c in members],
            evidence=[{"review_id": c.review_id, "quote": next(h.evidence for h in c.topics if h.topic == topic and h.polarity == "negative")} for c in members],
            time_bands={name: bands.get(name, 0) for name, _, _ in TIME_BANDS},
            main_time_band=band if n / len(members) >= MAIN_BAND_SHARE else None,
            channels=dict(Counter(by_id[c.review_id].channel or "unknown" for c in members)),
            recent_count=sum(t > mid for t in times), previous_count=sum(t <= mid for t in times),
            first_at=by_id[members[0].review_id].created_at, last_at=by_id[members[-1].review_id].created_at,
        ))
    issues.sort(key=lambda i: (-i.review_count, -i.recent_count, i.topic))
    issues = check_issues(issues, {c.review_id: c for c in classes}, by_id)
    return ReviewInsight(store_id=store_id, period_start=start.date().isoformat(), period_end=end_day.date().isoformat(),
                         review_count=len(in_window), sentiment_counts=dict(sentiment_counts), topic_counts=topic_counts,
                         repeated_issues=issues, classifications=in_window)


def check_issues(issues: list[RepeatedIssue], classes: dict, reviews: dict) -> list[RepeatedIssue]:
    """근거 ID 검증: 묶음의 리뷰 ID가 실제로 있고, 그 리뷰가 정말 그 주제의 불만이며, 근거 구절이 그 리뷰에 있어야 함.
    어긋난 리뷰는 묶음에서 빼고 기록만 남김 (화면 전체가 멈추지 않게). 빼고 나서 기준 미만이면 묶음을 버림."""
    kept = []
    for i in issues:
        good = []
        for e in i.evidence:
            rid = e["review_id"]
            ok = (rid in reviews and rid in classes and i.topic in classes[rid].negative_topics
                  and e["quote"] and e["quote"] in reviews[rid].text)
            if ok:
                good.append(e)
            else:
                log.warning("반복 묶음 %s: %s 근거가 맞지 않아 뺌", i.issue_id, rid)
        if len(good) != len(i.evidence):
            ids = {e["review_id"] for e in good}
            i.evidence = good
            i.review_ids = [r for r in i.review_ids if r in ids]
            i.review_count = len(i.review_ids)
        if i.review_count >= MIN_COUNT:
            kept.append(i)
    return kept
