"""시나리오 가게 1곳의 샘플 인스턴스 (합성 데이터).

발표용 가게는 C2(PR #14)가 만든 "온기한식 (가상)"(store_ongi)입니다. 이 샘플은 그 가게의 모양을 보여 주고,
다른 파트의 결과가 아직 없을 때 먼저 개발하는 용도입니다. 예: C7 화면, C6 생성기.
JSON 모양을 보려면 저장소 루트에서:

    python -m shared.sample_scenario

C2 데이터와의 관계
- SAMPLE_STORE와 SAMPLE_REVIEWS(rv_ongi_001~003)는 PR #14의 services/review-insight/data/synthetic/store_ongi/
  내용과 같습니다 (포장 누락 3건 = 결정안의 유일한 반복 묶음). 원본은 C2 데이터이고 여기는 복사본입니다.
- 분류 결과(sentiment·topics)는 같은 폴더 labels.json의 정답표를 옮긴 것입니다.
- 가격(menu_prices)은 쿠폰 홍보글 개발용으로 이 샘플에서 정한 가정값입니다. 이건영 님 데이터에는 없습니다.

자리표시자 (C4 주현석 님이 11/9에 실제 값으로 정합니다)
- 상권: SAMPLE_STORE.area_name은 None, 지표의 area_name은 PLACEHOLDER_AREA_NAME (아직 미정)
- 저녁 추정매출 전년 동기 대비 변화율: 팀 결정 v0.4로 value=-19.31 확정. 카드 문장의 "-X%"는
  c6.promo가 이 값으로 채워 넣는다(값이 채워지면 "수치 확정 전" 문구는 붙지 않는다).
남은 자리표시자(area_name)가 정해지면 SAMPLE_SNAPSHOTS[0].area_name만 바꾸면 됩니다.
"""
from __future__ import annotations

import json

from shared.contracts import (
    AnalysisSnapshot, RecommendationCard, ReviewRecord, StoreProfile, ToneProfile,
)

PLACEHOLDER_AREA_NAME = "상권 미정 (C4가 11/9 확정)"

SAMPLE_STORE = StoreProfile(
    store_id="store_ongi",
    name="온기한식 (가상)",
    business_type="korean",
    business_type_name="한식음식점",
    channels=["baemin", "coupangeats", "yogiyo", "naver_place"],
    menu=["제육볶음 정식", "된장찌개", "김치찌개", "순두부찌개", "불고기 덮밥", "계란말이"],
    area_name=None,  # 자리표시자: C4가 11/9에 정함
    menu_prices={"제육볶음 정식": 9500, "된장찌개": 8000, "김치찌개": 8000,
                 "순두부찌개": 8500, "불고기 덮밥": 9000, "계란말이": 6000},
)

SAMPLE_TONE = ToneProfile(
    tone_id="tone_ongi",
    store_id=SAMPLE_STORE.store_id,
    style_description="~해요체로 부드럽게. 사과는 짧고 구체적으로 하고, 마지막에 다음에 어떻게 하겠다는 말을 붙인다.",
    example_sentences=[
        "주문 확인이 늦어서 불편하셨죠, 죄송해요.",
        "다음 주문부터는 포장 전에 한 번 더 확인할게요.",
        "소중한 말씀 감사해요, 또 찾아주세요.",
    ],
    forbidden_phrases=["배달 기사님 탓", "플랫폼 문제", "원래 그렇습니다", "100% 보상", "규정상"],
)


def _missing_item_review(number: int, channel: str, rating: int, text: str, created_at: str) -> ReviewRecord:
    return ReviewRecord(
        review_id=f"rv_ongi_{number:03d}", store_id=SAMPLE_STORE.store_id, text=text, created_at=created_at,
        channel=channel, rating=rating,
        sentiment="negative", topics=["missing_item"], negative_topics=["missing_item"],
    )


# 포장 누락 불만 3건: 결정안의 '유일한 반복 묶음'이자 카드 ⓐ의 근거. urgency는 C3가 아직 내지 않아 비워 둠.
SAMPLE_REVIEWS = [
    _missing_item_review(1, "baemin", 2, "공깃밥 추가했는데 안 들어 있었어요", "2026-10-27T19:30:00+09:00"),
    _missing_item_review(2, "coupangeats", 2, "수저랑 젓가락이 빠져 있었어요", "2026-11-03T20:10:00+09:00"),
    _missing_item_review(3, "yogiyo", 1, "계란말이를 같이 시켰는데 누락됐어요", "2026-11-06T19:50:00+09:00"),
]

SAMPLE_SNAPSHOTS = [
    AnalysisSnapshot(
        snapshot_id="snap_sample_01",
        area_name=PLACEHOLDER_AREA_NAME,
        metric_name="저녁 시간대 추정매출 (전년 동기 대비 변화율)",
        value=-19.31,  # 팀 결정 v0.4 값 (C4 확정)
        unit="%",
        basis_quarter="2026Q2",
        is_estimate=True,
        source="서울시",
        compared_with_quarter="2025Q2",
        note="팀 결정 v0.4: 저녁 시간대 추정매출 변화율 -19.31%",
    ),
]

SAMPLE_CARDS = [
    # 카드 ⓐ: 가장 큰 반복 묶음 -> 답글 + 재발 방지 공지
    RecommendationCard(
        card_id="card_sample_a", store_id=SAMPLE_STORE.store_id, kind="complaint",
        reason_text="포장 누락을 말한 리뷰가 3건 반복됐고, 공깃밥·수저·계란말이처럼 주문한 품목이나 구성품이 빠졌다는 내용입니다.",
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
