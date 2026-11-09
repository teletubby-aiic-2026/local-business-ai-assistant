# C1 데이터 계약 기준 필드 매핑 (shared/contracts.py @ origin/feat/c1-data-contract)
#
# ┌─────────────────┬──────────────────────┬───────────────────────────────────────┐
# │ C1 dataclass    │ C6 ctx 키            │ 출처                                  │
# ├─────────────────┼──────────────────────┼───────────────────────────────────────┤
# │ StoreProfile    │ ctx["store"]         │ C2 store.json + dummy(menu_prices 등) │
# │ ReviewRecord    │ ctx["reviews"]       │ C2 reviews.json + C3 labels.json 병합 │
# │ ToneProfile     │ ctx["tone"]          │ dummy (팀 데이터에 없음)              │
# │ RecommendationCard │ ctx["cards"]      │ make_cards_from_c3(classified)        │
# │ AnalysisSnapshot│ ctx["snapshots"]     │ dummy (팀 데이터에 없음)              │
# │ (없음)          │ ctx["owner_replies"] │ dummy (팀 데이터에 없음)              │
# │ (없음)          │ ctx["policies"]      │ dummy (팀 데이터에 없음)              │
# └─────────────────┴──────────────────────┴───────────────────────────────────────┘
#
# C2↔C1 차이점:
#   - store: city·area_name·menu_prices 없음 → 기본값/더미
#   - reviews: C1 필드 그대로. 분류 결과는 별도 labels.json
# C3↔C1 차이점:
#   - labels.json: expected_sentiment → sentiment
#   - labels.json: expected_topics [{topic,polarity}] → topics [str] + negative_topics [str]
#   - urgency: C3에 없음 → None
"""형식 변환층: 팀 원천 데이터(C2·C3) → C1 계약 기준 C6 표준 dict."""

from __future__ import annotations

from typing import Any


def _merge_labels(reviews: list[dict], labels: list[dict]) -> list[dict]:
    """C3 labels.json 을 C2 reviews 에 병합해 C1 ReviewRecord 형식으로."""
    by_id = {lb["review_id"]: lb for lb in labels}
    merged = []
    for rv in reviews:
        rv = dict(rv)
        lb = by_id.get(rv["review_id"])
        if lb:
            rv["sentiment"] = lb.get("expected_sentiment")
            topics_raw = lb.get("expected_topics", [])
            rv["topics"] = [t["topic"] for t in topics_raw]
            rv["negative_topics"] = [
                t["topic"] for t in topics_raw if t.get("polarity") == "negative"
            ]
        else:
            rv.setdefault("sentiment", None)
            rv.setdefault("topics", [])
            rv.setdefault("negative_topics", [])
        rv.setdefault("urgency", None)
        merged.append(rv)
    return merged


def _map_store(raw_store: dict) -> dict:
    """C2 store.json → C1 StoreProfile 호환 dict."""
    store = dict(raw_store)
    store.setdefault("city", "서울")
    store.setdefault("area_name", None)
    store.setdefault("menu_prices", {})
    return store


def make_cards_from_c3(classified: list[dict], store_id: str) -> list[dict]:
    """C3 분류된 리뷰에서 반복 불만 카드를 만든다.

    규칙: negative_topics 중 같은 주제 2건 이상 → 가장 많은 주제 1개로 카드 ⓐ.
    카드 ⓑ(promo)는 상권 지표가 없으므로 더미 snapshot 근거로 채운다.
    """
    topic_reviews: dict[str, list[str]] = {}
    for rv in classified:
        for topic in rv.get("negative_topics", []):
            topic_reviews.setdefault(topic, []).append(rv["review_id"])

    cards: list[dict] = []

    repeated = {t: ids for t, ids in topic_reviews.items() if len(ids) >= 2}
    if repeated:
        top_topic = max(repeated, key=lambda t: len(repeated[t]))
        cards.append({
            "card_id": "card_a",
            "store_id": store_id,
            "kind": "complaint",
            "reason_text": (
                f"{top_topic} 관련 불만 리뷰가 {len(repeated[top_topic])}건 반복됐어요."
            ),
            "review_ids": repeated[top_topic],
            "snapshot_ids": [],
        })

    cards.append({
        "card_id": "card_b",
        "store_id": store_id,
        "kind": "promo",
        "reason_text": "저녁 시간대 추정매출 변화 데이터가 필요해요.",
        "review_ids": [],
        "snapshot_ids": ["snap_dummy_01"],
    })

    return cards


def to_ctx(raw: dict) -> dict:
    """팀 원천 데이터 → C6 표준 context dict.

    raw 키:
      - store: C2 store.json (dict)
      - reviews: C2 reviews.json (list[dict])
      - labels: C3 labels.json (list[dict])  — 선택
    나머지(tone, owner_replies, policies, snapshots)는 팀 데이터에 없으므로
    dummy 값으로 채우고 needs_input 에 기록한다.
    """
    from c6.dummy import OWNER_REPLIES, POLICIES, DUMMY_TONE, DUMMY_SNAPSHOTS

    needs_input: list[str] = []
    ctx: dict[str, Any] = {}

    if "store" in raw:
        ctx["store"] = _map_store(raw["store"])
    else:
        needs_input.append("store")

    if "reviews" in raw:
        labels = raw.get("labels", [])
        ctx["reviews"] = _merge_labels(raw["reviews"], labels)
    else:
        needs_input.append("reviews")

    if "cards" in raw:
        ctx["cards"] = raw["cards"]
    elif "reviews" in ctx:
        store_id = ctx.get("store", {}).get("store_id", "unknown")
        ctx["cards"] = make_cards_from_c3(ctx["reviews"], store_id)
    else:
        needs_input.append("cards")

    for key, dummy, label in [
        ("owner_replies", OWNER_REPLIES, "사장님 예전 답글"),
        ("policies", POLICIES, "가게 정책"),
        ("tone", DUMMY_TONE, "사장님 말투(ToneProfile)"),
        ("snapshots", DUMMY_SNAPSHOTS, "상권 지표(AnalysisSnapshot)"),
    ]:
        if key in raw:
            ctx[key] = raw[key]
        else:
            ctx[key] = dummy
            needs_input.append(f"팀 데이터에 없음: {label}")

    ctx["needs_input"] = needs_input
    return ctx
