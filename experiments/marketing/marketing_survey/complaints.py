"""가게의 반복 불만 주제 — 맞춤 홍보 제안의 '어떤 불만인가요?' 보기, 안내문 주제, 안내문 조치를 같은 주제로 맞춘다 (11/21 QA).

11/21 실사용 QA: 보기가 '포장 누락 / 배달 지연 / 그 외'로 온기한식 기준 고정이라, 바삭치킨에서 '포장 누락'을 고르면 안내문은
그 가게 불만 카드(식감)로 쓰이고 조치는 주문서 대조로 고정돼 주제가 섞였다. 이제 보기는 그 가게 리뷰의 실제 반복 불만이고,
고른 주제의 리뷰 묶음으로 안내문·답글을 쓰고, 조치도 그 주제에 맞는 것(c6.measures.TOPIC_MEASURES)만 넣는다.

- 반복 = 같은 부정 주제(ReviewRecord.negative_topics)가 REPEAT_MIN 건 이상. hypotheses.H_REPEAT(카드 리뷰 2건 이상)와 같은 기준.
- 배달 시간(delivery_time) 불만은 예전 '배달 지연' 보기처럼 H_LATE(배달 지연 안내 공지)로 간다.
- 반복 불만이 없는 가게(직접 등록한 새 가게 등)는 예전 보기 그대로 묻고, 왜 기본 보기인지 질문 문장에 밝힌다.
AI 호출 없음, 표준 라이브러리 + c6 의 주제 표만.
"""
from __future__ import annotations

from dataclasses import dataclass

from c6.measures import MEASURES, MISSING_TOPIC, TOPIC_LABELS, TOPIC_MEASURES
from c6.notice import notice_topic
from shared.contracts import RecommendationCard

REPEAT_MIN = 2          # 같은 불만 2건 이상이면 반복 (hypotheses._repeat_complaint_card 와 같은 기준)
MAX_TOPICS = 3          # 보기 칩이 너무 길어지지 않게 많은 순서로 3개까지 (+ '그 외')
CARD_REVIEWS_MAX = 5    # 안내문·답글이 보는 리뷰 수 (shared.store_profiles.sample_cards 와 같은 상한)
LATE_TOPIC = "delivery_time"
# 보기 글자: 리뷰 분석 주제 이름(c6.measures.TOPIC_LABELS)을 쓰되, 배달 시간은 H_LATE 공지('배달 지연 안내 공지')와 같은 말로
_LABEL_OVERRIDE = {LATE_TOPIC: "배달 지연"}

# 반복 불만이 없는 가게의 예전 보기 (라벨은 예전 그대로 — 등록 가게 시험·화면이 이 글자로 고른다)
LEGACY_TOPICS = (("포장 누락", MISSING_TOPIC), ("배달 지연", LATE_TOPIC))

_MEASURE_BY_ID = {m["id"]: m for m in MEASURES}


@dataclass(frozen=True)
class ComplaintTopic:
    topic: str                      # 리뷰 분석 주제 id (예: texture)
    label: str                      # 보기 글자 (예: 식감)
    review_ids: tuple[str, ...]     # 이 주제 불만 리뷰 (가게 리뷰 순서)


def topic_label(topic: str | None) -> str:
    """보기·제목에 쓰는 주제 이름. 모르는 주제는 '그 밖의 불편'."""
    if not topic:
        return "그 밖의 불편"
    return _LABEL_OVERRIDE.get(topic) or TOPIC_LABELS.get(topic, "그 밖의 불편")


def _topic_reviews(ctx) -> dict[str, list[str]]:
    """부정 주제 id → 그 주제가 걸린 리뷰 id (가게 리뷰 순서, 한 리뷰는 주제마다 한 번)."""
    out: dict[str, list[str]] = {}
    for r in ctx.reviews:
        for t in dict.fromkeys(getattr(r, "negative_topics", None) or []):
            out.setdefault(t, []).append(r.review_id)
    return out


def base_card(ctx):
    """가게의 불만 카드(kind=complaint) 첫 장. 없으면 None."""
    return next((c for c in ctx.cards if c.kind == "complaint"), None)


def card_topic(ctx, card) -> str | None:
    """카드 리뷰로 쓰는 안내문의 주제 id — c6.notice 가 제목('[안내] … 관련')을 고르는 기준과 같다."""
    if card is None:
        return None
    review_map = {r.review_id: r for r in ctx.reviews}
    return notice_topic([review_map[rid] for rid in card.review_ids if rid in review_map])


def repeated_topics(ctx) -> list[ComplaintTopic]:
    """그 가게의 반복 불만 주제 (많은 순, 같으면 불만 카드의 주제 먼저 → 이름 순). 최대 MAX_TOPICS 개."""
    first = card_topic(ctx, base_card(ctx))
    rows = [(t, ids) for t, ids in _topic_reviews(ctx).items() if len(ids) >= REPEAT_MIN]
    rows.sort(key=lambda kv: (-len(kv[1]), kv[0] != first, kv[0]))
    return [ComplaintTopic(t, topic_label(t), tuple(ids)) for t, ids in rows[:MAX_TOPICS]]


def notice_measures(topic: str | None) -> list[dict]:
    """안내문 '오늘부터' 줄에 넣을 조치 — 그 주제에 맞는 조치(c6.measures.TOPIC_MEASURES)의 첫째 하나.
    포장 누락은 예전처럼 M1(포장 마감 전 주문서 대조). 맞는 조치가 없는 주제(식감·맛·대기 등)는 빈 목록이라
    c6.notice 가 무엇을 바꾸겠다는 약속 없이 '말씀해 주신 점을 매장에서 더 꼼꼼히 살피겠습니다'만 쓴다 (지어낸 조치·보상 없음)."""
    ids = TOPIC_MEASURES.get(topic or "", [])
    return [dict(_MEASURE_BY_ID[ids[0]])] if ids and ids[0] in _MEASURE_BY_ID else []


def topic_card(ctx, topic: str | None):
    """고른 주제의 불만 리뷰 묶음 카드. 안내문·답글 생성기(c6)는 카드 리뷰로 주제를 정하므로, 이 카드를 넘기면
    안내문 주제가 고른 주제와 같아진다.
    - topic 이 없거나(예전 상태) 불만 카드의 주제와 같으면 그 카드를 그대로 쓴다 (온기한식 포장 누락은 예전과 같은 카드·저장본).
    - 다른 주제면 그 주제 리뷰로 카드를 새로 만든다 (그 주제만 걸린 리뷰 먼저, 최대 CARD_REVIEWS_MAX 건).
    - 그 주제 리뷰도 불만 카드도 없으면 None (부르는 쪽이 '자료가 없어 만들 수 없어요'로 바꾼다)."""
    base = base_card(ctx)
    if not topic or (base is not None and card_topic(ctx, base) == topic):
        return base
    by_id = {r.review_id: r for r in ctx.reviews}
    all_ids = _topic_reviews(ctx).get(topic, [])
    if not all_ids:
        return None
    ids = sorted(all_ids, key=lambda rid: len(by_id[rid].negative_topics or []) > 1)[:CARD_REVIEWS_MAX]
    key = ctx.store.store_id.removeprefix("store_")
    card_id = f"{base.card_id}_{topic}" if base is not None else f"card_{key}_{topic}"
    return RecommendationCard(card_id=card_id, store_id=ctx.store.store_id, kind="complaint",
                              reason_text=f"{topic_label(topic)} 불만이 {len(all_ids)}건 반복됐어요.", review_ids=ids)


def resolve_topic(ctx, chosen: str | None) -> str | None:
    """안내문 주제 id: 사장님이 고른 주제, 없으면(예전 상태) 불만 카드의 주제."""
    return chosen or card_topic(ctx, base_card(ctx))


def topic_count(ctx, topic: str | None) -> int:
    """그 주제 불만 리뷰 수 (왜 이렇게 판단했나요 줄에 씀). 모르면 0."""
    return len(_topic_reviews(ctx).get(topic or "", []))
