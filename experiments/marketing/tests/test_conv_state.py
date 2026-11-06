"""
대화 상태 처리 함수(값 정리·pending·이어지는 말) 검증 — AI 호출 없음.

실행: python -m tests.test_conv_state
"""

import io
import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from features import assistant as A

TODAY = date(2026, 11, 6)

FAIL = []


def check(name, got, expected):
    ok = got == expected
    status = "✅" if ok else "❌"
    print(f"{status} {name}: {got!r}" + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAIL.append(name)


def case1_영업시간():
    store = {"영업시간": None, "휴무일": ["월"], "전화번호": "02-1234-5678",
              "메뉴": [("아메리카노", "4,500원")], "주소": "서울", "가게 소개": "카페",
              "대표 사진": ["p.jpg"], "포장": "가능", "배달": "불가", "주차": "없음",
              "예약 가능": "가능", "편의시설": ["Wi-Fi"]}
    update = A.apply_store_update(store, "영업시간", "11시부터 20시까지")
    check("영업시간 반영", store["영업시간"], "11:00 ~ 20:00")
    check("영업시간 표시값", update["표시값"], "11:00 ~ 20:00")


def case2_휴무일():
    store = {"영업시간": "11:00 ~ 20:00", "휴무일": None, "전화번호": "02-1234-5678",
              "메뉴": [("아메리카노", "4,500원"), ("라떼", "5,000원"), ("휘낭시에", "4,000원")],
              "주소": "서울", "가게 소개": "카페", "대표 사진": ["p.jpg"], "포장": "가능",
              "배달": "불가", "주차": "없음", "예약 가능": "가능", "편의시설": ["Wi-Fi"]}
    update = A.apply_store_update(store, "휴무일", "매주 화요일에 쉬어요")
    check("휴무일 반영", store["휴무일"], ["화"])
    check("휴무일 다 채움(화요일 반영 후)", update["다 채움"], True)


def case3_주차_가능():
    store = {"영업시간": "11:00 ~ 20:00", "휴무일": ["화"], "전화번호": "02-1234-5678",
              "메뉴": [("아메리카노", "4,500원")], "주소": "서울", "가게 소개": "카페",
              "대표 사진": ["p.jpg"], "포장": "가능", "배달": "불가", "주차": None,
              "예약 가능": "가능", "편의시설": ["Wi-Fi"]}
    update = A.apply_store_update(store, "주차", "주차 가능해요")
    check("주차 반영", store["주차"], "가능")
    check("주차 표시값", update["표시값"], "주차 가능")


def case4_pending_합치기():
    cards = [{"종류": "되묻기", "제목": "쿠폰을 만들려면 몇 가지 더 알려 주세요",
              "내용": "- 혜택 종류 (금액 할인 / 비율 할인 / 1+1 / 서비스 증정)\n- 적용 메뉴"}]
    pending = A.extract_pending("make_coupon", cards, "단골 쿠폰 만들고 싶은데")
    check("pending 필요한 항목 2개", len(pending["필요한_항목"]), 2)
    merged = A.resolve_pending_message(pending, "아메리카노 10% 할인")
    check("pending 합친 메시지", merged, "단골 쿠폰 만들고 싶은데 아메리카노 10% 할인")


def case5_followup_채널():
    f = A.detect_followup("인스타로 다시 써줘")
    check("채널 followup", f, {"종류": "채널", "채널": "인스타그램"})


def case6_followup_수정():
    f = A.detect_followup("아니 수요일로")
    check("수정 followup 종류", f["종류"], "수정")
    f2 = A.detect_followup("근처에 행사 있어?")
    check("일반 질문은 followup 아님", f2, None)


def case7_공지_날짜있으면_확인():
    info = {"종류": "임시휴무", "시작": date(2026, 11, 10), "종료": date(2026, 11, 10), "확인필요": []}
    step = A.decide_notice_step(info, {"임시 휴무일": []}, TODAY)
    check("날짜 있으면 확인 단계", step["단계"], "확인")


def case8_공지_기록0개_질문():
    info = {"종류": "임시휴무", "시작": None}
    step = A.decide_notice_step(info, {"임시 휴무일": []}, TODAY)
    check("기록 0개면 질문 단계", step["단계"], "질문")


def case9_공지_기록1개_선택():
    store = {"임시 휴무일": [{"날짜": "2026-11-10", "사유": "개인 사정", "공지 여부": False}]}
    info = {"종류": "임시휴무", "시작": None}
    step = A.decide_notice_step(info, store, TODAY)
    check("기록 1개면 선택 단계", step["단계"], "선택")
    check("기록 1개 개수", len(step["기록"]), 1)


def case10_공지_기록2개이상_선택():
    store = {"임시 휴무일": [
        {"날짜": "2026-11-07", "사유": "", "공지 여부": False},
        {"날짜": "2026-11-10", "사유": "개인 사정", "공지 여부": False},
        {"날짜": "2026-10-01", "사유": "지난 휴무", "공지 여부": True},  # 지난 날짜는 빠져야 함
    ]}
    info = {"종류": "임시휴무", "시작": None}
    step = A.decide_notice_step(info, store, TODAY)
    check("기록 2개 이상이면 선택 단계", step["단계"], "선택")
    check("지난 날짜는 빼고 2개만", len(step["기록"]), 2)


def case11_날짜_중복_추가_없음():
    store = {"임시 휴무일": []}
    A.add_temp_closure(store, "2026-11-10", "개인 사정")
    A.add_temp_closure(store, "2026-11-10", "다른 사유")
    check("같은 날짜 재요청해도 1개만 기록", len(store["임시 휴무일"]), 1)
    check("기존 사유가 비어 있지 않으면 안 바뀜", store["임시 휴무일"][0]["사유"], "개인 사정")


def main():
    case1_영업시간()
    case2_휴무일()
    case3_주차_가능()
    case4_pending_합치기()
    case5_followup_채널()
    case6_followup_수정()
    case7_공지_날짜있으면_확인()
    case8_공지_기록0개_질문()
    case9_공지_기록1개_선택()
    case10_공지_기록2개이상_선택()
    case11_날짜_중복_추가_없음()

    print()
    if FAIL:
        print(f"❌ {len(FAIL)}건 실패: {FAIL}")
        return False
    print("✅ 모두 통과")
    return True


if __name__ == "__main__":
    ok = main()
    if not ok:
        sys.exit(1)
