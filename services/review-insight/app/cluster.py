"""C3 묶음: 불만 리뷰를 주제별로 모으고, 2건 이상이면 묶음, 3건 이상이면 '반복'으로 표시합니다.

결정안 v0.4 와우: 리뷰 40건 → 불만 12건 → 3묶음(포장 누락 3 = 유일한 반복, 늦은 배달 2, 양·맛 2) + 단발 5건
- 묶음: 같은 주제의 불만이 2건 이상
- 반복: 그중 3건 이상 (카드 ⓐ는 가장 큰 반복 묶음 1개)
- 합치기: 서로 다른 주제인데 걸린 리뷰가 완전히 같으면 한 묶음 (예: 두 리뷰가 모두 양과 맛을 말함 → '양·맛')
- 단발: 어느 묶음에도 들지 않은 불만 리뷰

계산은 모두 코드가 합니다 (모델은 리뷰 한 건씩 주제만 고름). 같은 분류 결과면 묶음도 항상 같습니다.
시간대 구간은 서울시 상권 추정매출과 같은 6구간이라서, C5 카드가 '저녁(17~21시) 매출'과 바로 이어 볼 수 있습니다.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.models import IssueGroup, Review, ReviewClassification, ReviewInsight
from app.topics import TOPICS, topic_name

log = logging.getLogger("review_insight.cluster")
TIME_BANDS = (("00~06시", 0, 6), ("06~11시", 6, 11), ("11~14시", 11, 14), ("14~17시", 14, 17), ("17~21시", 17, 21), ("21~24시", 21, 24))
GROUP_MIN = 2          # 이 건수 이상이면 묶음
MIN_COUNT = 3          # 이 건수 이상이면 반복
WINDOW_DAYS = 28       # 최근 4주
MAIN_BAND_SHARE = 0.6  # 한 시간대에 60% 이상 몰리면 '주로 이 시간대'
_ORDER = {t: i for i, t in enumerate(TOPICS)}
KST = timezone(timedelta(hours=9))


def has_order_time(review: Review) -> bool:
    """작성 시각을 시간대 통계에 써도 되는 리뷰인가. 합성 샘플은 작성 시각이 있고, 붙여넣기·캡처·매장 메모로 받은 리뷰는
    받은 시각뿐이라 시간대를 모른다 (받은 날짜로 세는 응대 기한·최근 2주 건수는 그대로 created_at 을 쓴다)."""
    return getattr(review, "input_method", "sample") != "paste"


def time_band(iso: str) -> str:
    h = datetime.fromisoformat(iso).hour
    return next(name for name, a, b in TIME_BANDS if a <= h < b)


def _quote(c: ReviewClassification, topic: str) -> str:
    return next(h.evidence for h in c.topics if h.topic == topic and h.polarity == "negative")


def build_insight(store_id: str, reviews: list[Review], classes: list[ReviewClassification], *,
                  end: datetime | None = None, window_days: int = WINDOW_DAYS, min_count: int = MIN_COUNT,
                  group_min: int = GROUP_MIN) -> ReviewInsight:
    by_id = {r.review_id: r for r in reviews}
    if end is None:
        # 리뷰가 0건이면(직접 등록한 가게에 아직 리뷰를 안 넣음, 11/20) 오늘(한국 시간)까지 4주 → 빈 결과
        end = max(datetime.fromisoformat(r.created_at) for r in reviews) if reviews else datetime.now(KST)
    end_day = end.replace(hour=23, minute=59, second=59)
    start = (end_day - timedelta(days=window_days)).replace(hour=0, minute=0, second=0) + timedelta(days=1)
    mid = start + (end_day - start) / 2
    in_window = [c for c in classes if c.review_id in by_id and start <= datetime.fromisoformat(by_id[c.review_id].created_at) <= end_day]
    cls = {c.review_id: c for c in in_window}

    sentiment_counts = Counter(c.sentiment for c in in_window)
    topic_counts: dict[str, dict] = {}
    for c in in_window:
        for pol in ("positive", "negative"):
            for t in {h.topic for h in c.topics if h.polarity == pol}:
                topic_counts.setdefault(t, {"positive": 0, "negative": 0})[pol] += 1
    complaints = [c for c in in_window if c.negative_topics]

    # 주제별 불만 리뷰 → 걸린 리뷰가 완전히 같은 주제끼리 합침
    members: dict[str, frozenset] = {}
    for t in TOPICS:
        ids = frozenset(c.review_id for c in complaints if t in c.negative_topics)
        if len(ids) >= group_min:
            members[t] = ids
    merged: dict[frozenset, list[str]] = {}
    for t, ids in members.items():
        merged.setdefault(ids, []).append(t)

    groups = []
    for ids, topics in merged.items():
        topics = sorted(topics, key=_ORDER.get)
        rows = sorted((cls[i] for i in ids), key=lambda c: by_id[c.review_id].created_at)
        times = [datetime.fromisoformat(by_id[c.review_id].created_at) for c in rows]
        # 시간대는 손님이 리뷰를 쓴 시각을 아는 리뷰만 센다. 사장님이 붙여넣거나 캡처로 넣은 리뷰(input_method="paste")의
        # created_at 은 넣은 시각(또는 시나리오 시각)이라, 밤에 붙이면 늘 '00~06시에 몰림'이 됐다 (11/21 실시간 확인 M6).
        timed = [c for c in rows if has_order_time(by_id[c.review_id])]
        bands = Counter(time_band(by_id[c.review_id].created_at) for c in timed)
        band, n = bands.most_common(1)[0] if bands else (None, 0)
        groups.append(IssueGroup(
            issue_id="iss_" + "_".join(topics), topics=topics, topic=topics[0],
            topic_name="·".join(topic_name(t) for t in topics), review_count=len(rows),
            is_repeated=len(rows) >= min_count, review_ids=[c.review_id for c in rows],
            evidence=[{"review_id": c.review_id, "quote": " / ".join(dict.fromkeys(_quote(c, t) for t in topics))} for c in rows],
            time_bands={name: bands.get(name, 0) for name, _, _ in TIME_BANDS} if timed else {},
            main_time_band=band if len(timed) >= group_min and n / len(timed) >= MAIN_BAND_SHARE else None,
            channels=dict(Counter(by_id[c.review_id].channel or "unknown" for c in rows)),
            recent_count=sum(t > mid for t in times), previous_count=sum(t <= mid for t in times),
            first_at=by_id[rows[0].review_id].created_at, last_at=by_id[rows[-1].review_id].created_at,
        ))
    groups = check_groups(groups, cls, by_id, group_min=group_min, min_count=min_count)
    groups.sort(key=lambda g: (not g.is_repeated, -g.review_count, -g.recent_count, _ORDER[g.topic]))

    grouped = {rid for g in groups for rid in g.review_ids}
    singles = [{"review_id": c.review_id, "topics": c.negative_topics, "topic_names": [topic_name(t) for t in c.negative_topics],
                "quote": _quote(c, c.negative_topics[0]), "created_at": by_id[c.review_id].created_at,
                "channel": by_id[c.review_id].channel}
               for c in sorted(complaints, key=lambda c: by_id[c.review_id].created_at) if c.review_id not in grouped]

    return ReviewInsight(store_id=store_id, period_start=start.date().isoformat(), period_end=end_day.date().isoformat(),
                         review_count=len(in_window), complaint_count=len(complaints),
                         sentiment_counts=dict(sentiment_counts), topic_counts=topic_counts,
                         groups=groups, single_complaints=singles, classifications=in_window)


def check_groups(groups: list[IssueGroup], classes: dict, reviews: dict, *, group_min: int = GROUP_MIN,
                 min_count: int = MIN_COUNT) -> list[IssueGroup]:
    """근거 ID 검증: 묶음의 리뷰가 실제로 있고, 그 리뷰가 묶음의 모든 주제에 불만이며, 근거 구절이 원문에 있어야 함.
    어긋난 리뷰는 빼고 기록만 남김 (화면 전체가 멈추지 않게). 빼고 나서 묶음 기준 미만이면 버림."""
    kept = []
    for g in groups:
        good = []
        for e in g.evidence:
            rid = e["review_id"]
            ok = (rid in reviews and rid in classes and all(t in classes[rid].negative_topics for t in g.topics)
                  and e["quote"] and all(q in reviews[rid].text for q in e["quote"].split(" / ")))
            if ok:
                good.append(e)
            else:
                log.warning("묶음 %s: %s 근거가 맞지 않아 뺌", g.issue_id, rid)
        if len(good) != len(g.evidence):
            ids = {e["review_id"] for e in good}
            g.evidence = good
            g.review_ids = [r for r in g.review_ids if r in ids]
            g.review_count = len(g.review_ids)
            g.is_repeated = g.review_count >= min_count
        if g.review_count >= group_min:
            kept.append(g)
    return kept
