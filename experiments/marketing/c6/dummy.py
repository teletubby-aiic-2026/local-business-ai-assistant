"""C6 더미 데이터 — 답글·재발 방지 공지·쿠폰 홍보글 생성 테스트용."""

DATA_ORIGIN = "synthetic"

STORE = {
    "name": "든든한끼",
    "category": "한식 덮밥",
    "location": "성수동",
    "delivery_ratio": 0.80,
    "menu": [
        {"name": "제육덮밥", "price": 9500},
        {"name": "치킨마요덮밥", "price": 9000},
        {"name": "계란국", "price": 2000},
        {"name": "콜라", "price": 2000},
    ],
}

REVIEWS = [
    {
        "review_id": "R01",
        "rating": 2,
        "text": "제육덮밥 맛은 괜찮은데 계란국이 안 왔어요. 포장 확인 좀 해 주세요.",
        "date": "2026-10-28",
        "topic": "포장 누락",
    },
    {
        "review_id": "R02",
        "rating": 3,
        "text": "콜라를 빼먹으셨네요. 덮밥은 맛있었는데 아쉬워요.",
        "date": "2026-10-30",
        "topic": "포장 누락",
    },
    {
        "review_id": "R03",
        "rating": 2,
        "text": "소스가 빠져 있어서 밋밋하게 먹었습니다. 맛 자체는 나쁘지 않은데 소스 없으면 좀…",
        "date": "2026-11-02",
        "topic": "포장 누락",
    },
    {
        "review_id": "R04",
        "rating": 1,
        "text": "배달이 50분이나 걸렸어요. 다 식어서 왔네요.",
        "date": "2026-11-03",
        "topic": "늦은 배달",
    },
    {
        "review_id": "R05",
        "rating": 5,
        "text": "제육덮밥 양도 많고 맛도 최고예요! 자주 시켜 먹을게요.",
        "date": "2026-11-04",
        "topic": "칭찬",
    },
    {
        "review_id": "R06",
        "rating": 5,
        "text": "치킨마요덮밥 진짜 맛있어요. 가성비 좋아서 단골 될 것 같아요.",
        "date": "2026-11-05",
        "topic": "칭찬",
    },
]

OWNER_REPLIES = [
    "안녕하세요 고객님 :) 맛있게 드셨다니 정말 감사해요. 다음에도 맛있게 준비할게요. 든든한끼 드림",
    "안녕하세요 고객님 :) 소중한 리뷰 감사합니다. 더 좋은 맛으로 보답할게요. 든든한끼 드림",
    "안녕하세요 고객님 :) 불편을 드려 죄송해요. 포장 과정을 다시 점검하겠습니다. 든든한끼 드림",
    "안녕하세요 고객님 :) 배달이 늦어 정말 죄송합니다. 배달 파트너사에 말씀 전달할게요. 든든한끼 드림",
]

POLICIES = [
    {"policy_id": "P1", "text": "누락 품목은 다음 주문 요청사항에 적어 주시면 챙겨 드리겠습니다."},
    {"policy_id": "P2", "text": "환불은 배달앱 고객센터를 통해 안내해 드리고 있습니다."},
    {"policy_id": "P3", "text": "리뷰 답글에 금전 보상(쿠폰·할인·무료 제공 등)을 약속하지 않습니다."},
]

CARDS = [
    {
        "card_id": "A",
        "type": "repeat_complaint",
        "topic": "포장 누락",
        "review_ids": ["R01", "R02", "R03"],
        "reason": "최근 불만 중 반복된 주제는 포장 누락 3건이에요",
    },
    {
        "card_id": "B",
        "type": "sales_drop",
        "metric": "저녁 추정매출 전년 동기 대비",
        "value": None,
        "quarter": "2026 2Q",
        "source": "서울시 상권분석서비스",
        "reason_template": "저녁 추정매출이 전년 동기 대비 {value} 줄었어요",
    },
]

# ── C1 계약에 있지만 팀 데이터(C2·C3)에 없는 것들의 더미 ────────────

DUMMY_TONE = {
    "tone_id": "tone_dummy",
    "store_id": "unknown",
    "style_description": "~해요체로 부드럽게. 사과는 짧고 구체적으로.",
    "example_sentences": [
        "불편하셨죠, 죄송해요.",
        "다음에는 꼭 챙길게요.",
        "소중한 말씀 감사해요.",
    ],
    "forbidden_phrases": ["배달 기사님 탓", "플랫폼 문제", "원래 그렇습니다"],
}

DUMMY_SNAPSHOTS = [
    {
        "snapshot_id": "snap_dummy_01",
        "area_name": "상권 미정",
        "metric_name": "저녁 시간대 추정매출 (전년 동기 대비 변화율)",
        "value": None,
        "unit": "%",
        "basis_quarter": "2026Q2",
        "is_estimate": True,
        "source": "서울시",
        "compared_with_quarter": "2025Q2",
        "note": "자리표시자: C4 상권 데이터 필요",
    },
]
