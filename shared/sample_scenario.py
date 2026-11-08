"""시나리오 가게 1곳의 샘플 인스턴스 (합성 데이터).

다른 파트의 결과가 아직 없을 때 이것으로 먼저 개발합니다. 예: C7 화면, C6 생성기.
JSON 모양을 보려면 저장소 루트에서:

    python -m shared.sample_scenario

자리표시자 (C4 주현석 님이 11/9에 실제 값으로 정합니다)
- 상권 이름: PLACEHOLDER_AREA_NAME
- 저녁 추정매출 전년 동기 대비 변화율: value=None 이고 카드 문장에는 "-X%"로 적혀 있습니다.
  숫자를 먼저 정하고 데이터를 맞추지 않기 위해 가짜 숫자를 넣지 않았습니다.
실제 값이 정해지면 SAMPLE_SNAPSHOTS[0].value와 SAMPLE_STORE.area_name만 바꾸면 됩니다.

ID에 sample을 넣은 것(rv_sample_01 ...)은 C2가 만드는 실제 리뷰 40건(rv_0001 ...)과 섞이지 않게 하려는 것입니다.
리뷰 문장은 모두 지어낸 것이며 실제 손님 정보가 없습니다.
"""
from __future__ import annotations

import json

from shared.contracts import (
    AnalysisSnapshot, RecommendationCard, ReviewRecord, StoreProfile, ToneProfile,
)

PLACEHOLDER_AREA_NAME = "상권 미정 (C4가 11/9 확정)"

SAMPLE_STORE = StoreProfile(
    store_id="store_bora",
    store_name="보라 치킨",
    business_type="치킨",
    city="서울",
    area_name=PLACEHOLDER_AREA_NAME,
    delivery_channels=["baemin", "coupang_eats", "naver_place"],
    menu_prices={"후라이드 치킨": 19000, "양념 치킨": 20000, "치킨무 추가": 500},
)

SAMPLE_TONE = ToneProfile(
    tone_id="tone_bora",
    store_id=SAMPLE_STORE.store_id,
    style_description="~해요체로 부드럽게. 사과는 짧고 구체적으로 하고, 마지막에 다음에 어떻게 하겠다는 말을 붙인다.",
    example_sentences=[
        "주문 확인이 늦어서 불편하셨죠, 죄송해요.",
        "다음 주문부터는 포장 전에 한 번 더 확인할게요.",
        "소중한 말씀 감사해요, 또 찾아주세요.",
    ],
    forbidden_phrases=["배달 기사님 탓", "플랫폼 문제", "원래 그렇습니다", "100% 보상", "규정상"],
)

# 포장 누락 불만 3건: 결정안의 '유일한 반복 묶음'을 흉내 낸 것. 밤 11시 전후에 들어온 새 리뷰.
SAMPLE_REVIEWS = [
    ReviewRecord(
        review_id="rv_sample_01", store_id=SAMPLE_STORE.store_id, channel="baemin",
        written_at="2026-11-07T22:41:00+09:00", rating=2,
        text="치킨은 맛있었는데 치킨무가 빠져 있었어요. 기사님께 물어봐도 모른다고 하셔서 그냥 먹었네요.",
        topic="포장 누락", sentiment="negative", urgency="medium",
    ),
    ReviewRecord(
        review_id="rv_sample_02", store_id=SAMPLE_STORE.store_id, channel="coupang_eats",
        written_at="2026-11-07T22:58:00+09:00", rating=1,
        text="요청사항에 콜라 넣어달라고 썼는데 또 빠졌어요. 지난번엔 소스가 없었는데 이번엔 음료네요.",
        topic="포장 누락", sentiment="negative", urgency="high",
    ),
    ReviewRecord(
        review_id="rv_sample_03", store_id=SAMPLE_STORE.store_id, channel="naver_place",
        written_at="2026-11-07T23:05:00+09:00", rating=2,
        text="양념 소스를 따로 담아달라고 했는데 안 왔어요. 포장할 때 한 번만 확인해 주세요.",
        topic="포장 누락", sentiment="negative", urgency="medium",
    ),
]

SAMPLE_SNAPSHOTS = [
    AnalysisSnapshot(
        snapshot_id="snap_sample_01",
        area_name=PLACEHOLDER_AREA_NAME,
        metric_name="저녁 시간대 추정매출 (전년 동기 대비 변화율)",
        value=None,  # 자리표시자: -X%. C4가 11/9에 실제 값으로 정함
        unit="%",
        basis_quarter="2026Q2",
        is_estimate=True,
        source="서울시",
        compared_with_quarter="2025Q2",
        note="자리표시자: 변화율(-X%)은 C4가 11/9에 실제 데이터로 정합니다",
    ),
]

SAMPLE_CARDS = [
    # 카드 ⓐ: 가장 큰 반복 묶음 -> 답글 + 재발 방지 공지
    RecommendationCard(
        card_id="card_sample_a", store_id=SAMPLE_STORE.store_id, kind="complaint",
        reason_text="포장 누락을 말한 리뷰가 3건 반복됐고, 치킨무·음료·소스처럼 곁들임이 빠졌다는 내용입니다.",
        review_ids=[r.review_id for r in SAMPLE_REVIEWS],
    ),
    # 카드 ⓑ: 저녁 추정매출 하락 -> 쿠폰 홍보
    RecommendationCard(
        card_id="card_sample_b", store_id=SAMPLE_STORE.store_id, kind="promo",
        reason_text="이 상권의 저녁 시간대 추정매출이 전년 동기 대비 -X% 줄었습니다.",
        snapshot_ids=[s.snapshot_id for s in SAMPLE_SNAPSHOTS],
    ),
]


def sample_bundle() -> dict:
    """샘플 전체를 JSON으로 바꿀 수 있는 dict 하나로."""
    return {
        "store": SAMPLE_STORE.to_dict(),
        "tone": SAMPLE_TONE.to_dict(),
        "reviews": [r.to_dict() for r in SAMPLE_REVIEWS],
        "snapshots": [s.to_dict() for s in SAMPLE_SNAPSHOTS],
        "cards": [c.to_dict() for c in SAMPLE_CARDS],
    }


if __name__ == "__main__":
    print(json.dumps(sample_bundle(), ensure_ascii=False, indent=2))
