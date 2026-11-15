"""쿠폰 결과 확인 — 발급·사용 장수로 사용률을 계산한다. AI 호출 없음, 전부 코드.

usage_rate = 사용 장수 / 발급 장수. 30% 미만이면 "할인액 올리기 또는 시간대 바꾸기",
30% 이상이면 "같은 조건으로 한 번 더"를 할 일로 남긴다.
build_coupon_result_plan(raw, today=None) -> marketing_survey.execute.build_plan() 과 같은 모양.
"""
from __future__ import annotations

from datetime import date

from marketing_survey.playbooks import PlaybookStep, _date_label

USAGE_THRESHOLD = 0.3
TODO_LOW_USAGE = "할인액 올리기 또는 시간대 바꾸기"
TODO_HIGH_USAGE = "같은 조건으로 한 번 더"


def usage_rate(issued: int, used: int) -> float | None:
    """발급 장수가 0이면 계산할 수 없다(없는 값을 만들지 않고 None)."""
    if issued <= 0:
        return None
    return used / issued


def build_coupon_result_plan(raw: dict, today: date | None = None) -> dict:
    today = today or date.today()
    issued = int(raw.get("coupon_issued") or 0)
    used = int(raw.get("coupon_used") or 0)
    rate = usage_rate(issued, used)

    if rate is None:
        todo = "발급 장수를 입력해 주세요"
        tip = "발급 장수가 0이라 사용률을 계산할 수 없어요"
    elif rate < USAGE_THRESHOLD:
        todo = TODO_LOW_USAGE
        tip = f"사용률 {round(rate * 100)}% — 30% 미만이에요"
    else:
        todo = TODO_HIGH_USAGE
        tip = f"사용률 {round(rate * 100)}% — 30% 이상이에요"

    step = PlaybookStep("coupon_result_todo", _date_label(today, 0), todo, "-", 5, tip=tip, cost_krw=0)
    return {
        "title": "쿠폰 결과 확인",
        "total_minutes": step.minutes,
        "steps": [step.to_dict()],
        "drafts": {},
        "measure": "측정: 다음 쿠폰 사용률과 비교",
        "total_cost_krw": 0,
        "usage_rate": rate,
        "issued": issued,
        "used": used,
    }
