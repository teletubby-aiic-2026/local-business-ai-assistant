"""
S3 이번 주 추천 카드 (AI 호출 없음)

목적: 마케팅 첫 화면에 "이번 주에 이걸 해 보세요" 카드를 최대 3개 보여 준다.
카드를 누르면 해당 기능(가게 정보·행사 추천·고객 응대)으로 이어진다.

재료
- 가게 정보 빈칸: features/store_profile.py 의 check_store_profile (우선순위 '높음' 빈칸이 있을 때만 카드)
- 행사 추천: features/event_plan.py 의 match, period
  - 참여형: 행사 시작일이 아니라 원래 문의일(시작일 - 21일)까지 14일 안일 때만
    (원래 문의일이 이미 지났으면 "모집이 끝났을 수 있어요" 문구로 바로 문의하도록 안내)
  - 주변형: 행사 시작일이 14일 안일 때만
- 불만 리뷰: complaints (고객 응대 파트가 넘겨줄 목록. 이번 주(7일 이내) 건만 센다)

급한 정도 (카드 종류가 달라 기준이 다르다. 높을수록 급함)
- 가게 정보 빈칸: 고정값 50
- 행사: 100 - D-day (참여형은 문의 마감일, 주변형은 시작일 기준. 가까울수록 큼, 최대 100)
- 불만 리뷰: 60 + 건수 × 10 (1건이어도 빈칸 50보다 급함)
"""

from datetime import timedelta

from common import korean as K
from features.event_plan import match, period
from features.store_profile import check_store_profile

MAX_CARDS = 3
EVENT_WINDOW_DAYS = 14
COMPLAINT_WINDOW_DAYS = 7
BLANK_URGENCY = 50
COMPLAINT_URGENCY_BASE = 60
COMPLAINT_URGENCY_PER_ITEM = 10
INQUIRY_LEAD_DAYS = 21  # event_plan.timeline 참여형 첫 할 일(셀러 문의)과 동일


def _blank_card(store):
    result = check_store_profile(store)
    high = [b for b in result["빈칸"] if b["우선순위"] == "높음"]
    if not high:
        return None
    top = high[0]
    return {
        "종류": "가게 정보",
        "제목": f"{top['이름']}{K.josa(top['이름'], '이', '가')} 비어 있어요. {top['안내']}",
        "근거": f"가게 정보 채움 비율 {result['채움_비율']:.0%} (빈칸 {len(result['빈칸'])}개)",
        "버튼": "store_profile",
        "급한 정도": BLANK_URGENCY,
    }


def _event_card(store, events, today):
    join, near = match(store, events, today)
    candidates = []
    for e in join:
        start = e["시작"]
        original_inquiry = start - timedelta(days=INQUIRY_LEAD_DAYS)
        if original_inquiry < today:
            d = 0
            event_d = (start - today).days
            title = f"{e['이름']} 셀러 모집이 끝났을 수 있어요. 오늘 바로 문의해 보세요 (행사까지 D-{event_d})"
        else:
            d = (original_inquiry - today).days
            title = f"{e['이름']} 셀러 문의는 {original_inquiry.month}월 {original_inquiry.day}일까지 해 보세요 (D-{d})"
        if 0 <= d <= EVENT_WINDOW_DAYS:
            candidates.append((d, {
                "종류": "행사",
                "제목": title,
                "근거": f"참여형 · {e['유형']} · {period(e)} · {e['출처']}",
                "버튼": "event_plan",
                "급한 정도": 100 - d,
            }))
    for e in near:
        d = (e["시작"] - today).days
        if 0 <= d <= EVENT_WINDOW_DAYS:
            candidates.append((d, {
                "종류": "행사",
                "제목": f"근처에서 {e['이름']}가 열려요. 홍보글 준비할까요? (D-{d})",
                "근거": f"주변형 · {e['유형']} · 도보 약 {e['도보']}분 · {period(e)}",
                "버튼": "event_plan",
                "급한 정도": 100 - d,
            }))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def _complaint_card(store, complaints, today):
    items = [c for c in (complaints or [])
             if c.get("가게") == store.get("이름") and 0 <= (today - c["날짜"]).days <= COMPLAINT_WINDOW_DAYS]
    if not items:
        return None
    n = len(items)
    return {
        "종류": "불만 리뷰",
        "제목": f"불만 리뷰 {n}건이 있어요",
        "근거": f"이번 주 접수된 불만 리뷰 {n}건",
        "버튼": "customer_reply",
        "급한 정도": COMPLAINT_URGENCY_BASE + n * COMPLAINT_URGENCY_PER_ITEM,
    }


def get_weekly_suggestions(store, events, today, complaints=None):
    """가게 1곳의 이번 주 추천 카드. 최대 3개, 같은 종류는 1개만, 급한 정도 높은 순.

    반환: [{"종류", "제목", "근거", "버튼", "급한 정도"}, ...] (카드 0개면 "이번 주는 할 일이 없어요" 카드 1개)
    """
    cards = [c for c in (
        _blank_card(store),
        _event_card(store, events, today),
        _complaint_card(store, complaints, today),
    ) if c is not None]
    cards.sort(key=lambda c: -c["급한 정도"])
    cards = cards[:MAX_CARDS]
    if not cards:
        return [{"종류": "없음", "제목": "이번 주는 할 일이 없어요", "근거": "", "버튼": "", "급한 정도": 0}]
    return cards
