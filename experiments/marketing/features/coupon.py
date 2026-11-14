"""
네이버 플레이스 쿠폰 만들기 (AI 호출 없음)

※ 보류: 2025-11-03 네이버 플레이스 쿠폰 화면에 실제로 보이는 입력 항목에 맞춰
  구조만 먼저 만들어 둔 기능입니다. 쿠폰 발급이 사장님에게 비용이 드는지
  아직 확인 전이라, 기능 정의서에는 '보류'로 올려 둡니다.

화면에 보이는 입력 항목 6가지를 그대로 담아 쿠폰 입력값을 만들고,
흔히 하는 실수(가게에 없는 메뉴, 메뉴 가격보다 큰 할인, 과도한 비율, 이상한
수량·기간)를 점검하며, 자주 빠뜨리는 사용 조건을 추천한다.
"""

import datetime

STANDARD_CONDITIONS = ["중복 사용 불가", "1인(또는 테이블당) 1회", "다른 메뉴와 함께 주문 시"]

USAGE_TEXT = {"매장": "매장 사용", "예약": "예약 시 사용"}

MAX_PERIOD_DAYS = 90
MAX_PERCENT = 50


def _menu_price(store, menu_name):
    """store["메뉴"]에서 menu_name의 가격(원, 정수)을 찾는다. 없으면 None.

    store["메뉴"]는 [(이름, 가격), ...] 형태를 받는다. 가격은 정수(원) 또는
    "4,500원" 같은 문자열 모두 허용한다.
    """
    for name, price in store.get("메뉴", []):
        if name == menu_name:
            if isinstance(price, str):
                digits = "".join(c for c in price if c.isdigit())
                return int(digits) if digits else None
            return price
    return None


def _coupon_name(choice):
    혜택, 메뉴, 값 = choice["혜택"], choice["메뉴"], choice.get("값")
    if 혜택 == "증정":
        return f"{메뉴} 1개 증정"
    if 혜택 == "금액 할인":
        return f"{메뉴} {값:,}원 할인"
    if 혜택 == "비율 할인":
        return f"{메뉴} {값}% 할인"
    return f"{메뉴} {혜택}"


def _valid_until_text(today, period_days):
    if period_days > 0:
        end = today + datetime.timedelta(days=period_days - 1)
        date_str = f"{end.year}. {end.month}. {end.day}."
    else:
        date_str = "-"
    return f"오늘 받으면 {date_str} · 발급일 포함 {period_days}일"


def build_coupon(choice, store, today):
    """화면에 보이는 쿠폰 입력값을 만들고 점검한다.

    반환: {"입력값": {쿠폰 이름, 혜택, 총 발급 횟수, 사용 방법, 유효기간, 사용 조건},
           "확인 필요": [문제 설명, ...], "추천 조건": [선택 안 한 표준 조건, ...]}
    """
    혜택 = choice["혜택"]
    메뉴 = choice["메뉴"]
    값 = choice.get("값")
    수량 = choice.get("수량", 0)
    기간_일 = choice.get("기간_일", 0)
    사용_방법 = choice.get("사용 방법", "매장")
    조건 = choice.get("조건", [])

    issues = []

    menu_price = _menu_price(store, 메뉴)
    if 메뉴 != "전 메뉴" and menu_price is None:
        issues.append(f"메뉴 '{메뉴}'가 가게 메뉴에 없어요")

    if 혜택 == "금액 할인" and menu_price is not None and 값 is not None and 값 >= menu_price:
        issues.append(f"할인 금액({값:,}원)이 메뉴 가격({menu_price:,}원) 이상이에요")

    if 혜택 == "비율 할인" and 값 is not None and 값 > MAX_PERCENT:
        issues.append(f"할인 비율이 {MAX_PERCENT}%를 초과해요 (현재 {값}%)")

    if 수량 <= 0:
        issues.append("총 발급 횟수는 1 이상이어야 해요")

    if 기간_일 <= 0:
        issues.append("유효기간은 1일 이상이어야 해요")
    elif 기간_일 > MAX_PERIOD_DAYS:
        issues.append(f"유효기간은 {MAX_PERIOD_DAYS}일 이하여야 해요 (현재 {기간_일}일)")

    추천_조건 = [c for c in STANDARD_CONDITIONS if c not in 조건]

    입력값 = {
        "쿠폰 이름": _coupon_name(choice),
        "혜택": 혜택,
        "총 발급 횟수": 수량,
        "사용 방법": USAGE_TEXT.get(사용_방법, 사용_방법),
        "유효기간": _valid_until_text(today, 기간_일),
        "사용 조건": list(조건),
    }

    return {"입력값": 입력값, "확인 필요": issues, "추천 조건": 추천_조건}
