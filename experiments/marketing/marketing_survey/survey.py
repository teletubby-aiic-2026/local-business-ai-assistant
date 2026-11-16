"""기본 설문 5문항 — 문구·선택지는 코드 고정(AI 가 바꾸지 않는다). AI 호출 없음."""

from marketing_survey.models import SurveyAnswers

DEFAULT_CHANNELS = ["naver_place"]
DEFAULT_WEEKLY_HOURS = 2


def build_survey_questions(store) -> list[dict]:
    """8문항. 3번(할인 메뉴)·7번(채널)만 가게 데이터(메뉴·채널)에 따라 선택지가 달라진다."""
    return [
        {
            "id": "budget_won", "text": "월 마케팅 예산은 얼마로 생각하시나요?",
            "type": "single", "choices": [0, 50000, 100000, 300000],
        },
        {
            "id": "goal", "text": "지금 가장 원하시는 건 뭔가요?",
            "type": "single", "choices": ["새 손님", "재주문", "객단가", "남는 재료 처리"],
        },
        {
            "id": "discount", "text": "할인해도 괜찮은 메뉴와 최대 할인 금액을 알려 주세요.",
            "type": "menu_and_amount", "choices": list(store.menu),
        },
        {
            "id": "discount_allowed", "text": "지금 할인(쿠폰)을 해도 괜찮으신가요?",
            "type": "bool", "choices": [True, False], "default": True,
        },
        {
            "id": "capacity", "text": "지금보다 주문이 더 오면 감당되시나요?",
            "type": "single", "choices": ["충분", "빠듯함"],
        },
        {
            "id": "weekly_hours", "text": "마케팅에 쓸 수 있는 시간은 주당 몇 시간 정도인가요?",
            "type": "number", "choices": [0, 1, 2, 5, 10], "default": DEFAULT_WEEKLY_HOURS,
        },
        {
            "id": "apps", "text": "쓰고 있는 배달앱을 모두 골라 주세요.",
            "type": "multi", "choices": ["배민", "쿠팡이츠", "땡겨요", "네이버 플레이스"],
        },
        {
            "id": "channels", "text": "손님에게 알릴 때 쓰는 채널을 모두 골라 주세요(비우면 가게 채널 전부 씀).",
            "type": "multi", "choices": list(store.channels), "default": list(DEFAULT_CHANNELS),
        },
    ]


def answers_from_raw(raw: dict) -> SurveyAnswers:
    """build_survey_questions() 응답(문항 id -> 값)을 SurveyAnswers 로 바꾼다."""
    return SurveyAnswers(
        budget_won=int(raw.get("budget_won", 0) or 0),
        goal=raw.get("goal", "") or "",
        discount_menu=raw.get("discount_menu") or None,
        max_discount_won=int(raw.get("max_discount_won", 0) or 0),
        capacity=raw.get("capacity", "충분") or "충분",
        apps=list(raw.get("apps", []) or []),
        channels=list(raw.get("channels", []) or []),
        discount_allowed=bool(raw.get("discount_allowed", True)),
        weekly_hours=int(raw.get("weekly_hours", DEFAULT_WEEKLY_HOURS) or 0),
        avg_order_won=int(raw.get("survey_avg_order_won", 0) or 0),
        margin_pct=int(raw.get("survey_margin_pct", 0) or 0),
    )
