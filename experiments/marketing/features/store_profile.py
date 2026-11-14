"""
가게 정보 빈칸 찾기 (AI 호출 없음)

목적: 사장님 가게 정보에서 빠진 항목을 찾아, 왜 필요한지와 함께 알려 준다 (이번 주 추천 카드의 재료).

팀 공통 가게 정보 형식이 정해지면 FIELDS 표만 고치면 된다.
"""

# ── 가게 정보 항목 표 (이 표만 고치면 됨) ───────────────────────
FIELDS = [
    {"키": "영업시간", "이름": "영업시간", "우선순위": "높음",
     "안내": "영업시간이 없으면 손님이 헛걸음할 수 있어요"},
    {"키": "휴무일", "이름": "휴무일", "우선순위": "높음",
     "안내": "휴무일이 없으면 쉬는 날 찾아온 손님이 헛걸음할 수 있어요"},
    {"키": "전화번호", "이름": "전화번호", "우선순위": "높음",
     "안내": "전화번호가 없으면 손님이 문의할 방법이 없어요"},
    {"키": "메뉴 가격", "이름": "메뉴 가격", "우선순위": "높음",
     "안내": "가격이 없으면 손님이 가격을 몰라 망설일 수 있어요"},
    {"키": "주소", "이름": "주소", "우선순위": "보통",
     "안내": "주소가 없으면 손님이 가게를 찾기 어려워요"},
    {"키": "가게 소개", "이름": "가게 소개", "우선순위": "보통",
     "안내": "소개가 없으면 어떤 가게인지 알기 어려워요"},
    {"키": "대표 사진", "이름": "대표 사진", "우선순위": "보통",
     "안내": "사진이 없으면 손님이 가게를 지나칠 수 있어요"},
    {"키": "포장·배달 여부", "이름": "포장·배달 여부", "우선순위": "보통",
     "안내": "포장·배달 여부가 없으면 이용 방법을 몰라 놓치는 손님이 있을 수 있어요"},
    {"키": "메뉴 3개 이상", "이름": "메뉴 3개 이상", "우선순위": "보통",
     "안내": "메뉴가 적으면 손님이 고를 게 없다고 느낄 수 있어요"},
    {"키": "주차", "이름": "주차", "우선순위": "낮음",
     "안내": "주차 정보가 없으면 차로 오는 손님이 불편할 수 있어요"},
    {"키": "예약 가능 여부", "이름": "예약 가능 여부", "우선순위": "낮음",
     "안내": "예약 가능 여부가 없으면 단체 손님을 놓칠 수 있어요"},
    {"키": "편의시설", "이름": "편의시설", "우선순위": "낮음",
     "안내": "편의시설 정보가 없으면 필요한 손님이 다른 곳을 찾을 수 있어요"},
]

PRIORITY_ORDER = {"높음": 0, "보통": 1, "낮음": 2}


def is_empty(v):
    """키 없음, None, 빈 문자열, 빈 목록, '-' 를 빈칸으로 본다."""
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() in ("", "-")
    if isinstance(v, (list, tuple, dict)):
        return len(v) == 0
    return False


def _generic(raw_key):
    return lambda store: is_empty(store.get(raw_key))


def _menu_price_empty(store):
    menu = store.get("메뉴") or []
    if not menu:
        return True
    return any(is_empty(price) for _, price in menu)


def _menu_count_empty(store):
    menu = store.get("메뉴") or []
    return len(menu) < 3


def _packaging_delivery_empty(store):
    return is_empty(store.get("포장")) and is_empty(store.get("배달"))


CHECKERS = {
    "영업시간": _generic("영업시간"),
    "휴무일": _generic("휴무일"),
    "전화번호": _generic("전화번호"),
    "메뉴 가격": _menu_price_empty,
    "주소": _generic("주소"),
    "가게 소개": _generic("가게 소개"),
    "대표 사진": _generic("대표 사진"),
    "포장·배달 여부": _packaging_delivery_empty,
    "메뉴 3개 이상": _menu_count_empty,
    "주차": _generic("주차"),
    "예약 가능 여부": _generic("예약 가능"),
    "편의시설": _generic("편의시설"),
}


def check_store_profile(store):
    """가게 정보에서 빈칸을 찾는다.

    반환: {"채움_비율": 0~1, "빈칸": [{항목, 이름, 우선순위, 안내}, ...] (높음→보통→낮음 순), "다 채움": bool}
    """
    blanks = []
    for f in FIELDS:
        if CHECKERS[f["키"]](store):
            blanks.append({"항목": f["키"], "이름": f["이름"], "우선순위": f["우선순위"], "안내": f["안내"]})
    blanks.sort(key=lambda b: PRIORITY_ORDER[b["우선순위"]])
    filled = len(FIELDS) - len(blanks)
    return {
        "채움_비율": round(filled / len(FIELDS), 2),
        "빈칸": blanks,
        "다 채움": len(blanks) == 0,
    }
