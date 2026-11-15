"""결정(decide() 가 고른 전략 1개)을 "실행 계획"(할 일 목록)으로 바꾼다.

사실(언제·무엇을·어디서·몇 분)은 전부 여기 코드가 정한다 — 글(초안)만 나중에 C6(AI)이 쓴다.
AI 호출 없음, 표준 라이브러리만.

build_playbook(ctx, strategy, answers, today=None) -> dict
  {title, total_minutes, steps: [...], measure}
  steps[i] = {step_id, when, what, where, minutes, generator(없으면 None), tip, max_chars(없으면 None)}

필터
  - channels: 설문 channels 에 없는 채널에 묶인 할 일은 뺀다(step.channel 참고. None 이면 채널과
    무관해 안 걸린다).
  - weekly_hours: 설문 weekly_hours <= 1 이면, 필터를 통과한 할 일 중 앞에서 2개만 남긴다.
  - 둘 다 "measure"(언제 무엇을 비교할지)에는 영향을 주지 않는다 — 할 일 목록이 줄어도 나중에
    무엇을 비교해야 하는지는 그대로 알려 줘야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

_WEEKDAY_KO = ("월", "화", "수", "목", "금", "토", "일")
_SCREEN_NOTE = " (앱 화면은 바뀔 수 있어요)"

_CHANNEL_PATH = {
    "naver_place": "네이버 플레이스 앱 > 소식 등록",
    "baemin": "배민 사장님광장 > 가게 소개",
    "coupangeats": "쿠팡이츠 윙 > 공지·이벤트",
    "yogiyo": "요기요 사장님 사이트 > 공지",
}

_APP_TO_CHANNEL = {"배민": "baemin", "쿠팡이츠": "coupangeats", "요기요": "yogiyo", "네이버 플레이스": "naver_place"}

_COUPON_TYPES = ("leftover_deal", "reorder_coupon", "offpeak_coupon")


def _channel_where(channel: str) -> str:
    return _CHANNEL_PATH.get(channel, channel) + _SCREEN_NOTE


def _date_label(today: date, offset_days: int, hour: int | None = None) -> str:
    """오늘 기준 +offset_days 일을 사람이 읽는 라벨로. 0=오늘, 1=내일, 그 외엔 "11/18(수)"."""
    d = today + timedelta(days=offset_days)
    if offset_days <= 0:
        label = "오늘"
    elif offset_days == 1:
        label = "내일"
    else:
        label = f"{d.month}/{d.day}({_WEEKDAY_KO[d.weekday()]})"
    if hour is not None:
        label += f" {hour}시 전"
    return label


def _apps_label(answers) -> str:
    apps = [a for a in answers.apps if a in _APP_TO_CHANNEL]
    return "/".join(apps) if apps else "배달앱"


BASIC_TODOS_BY_GOAL = {
    "새 손님": ["새 손님에게 보이는 채널에 쿠폰 알림 글 올리기", "메뉴 사진 다시 찍어 올리기"],
    "재주문": ["포장 봉투에 재주문 쿠폰 카드 넣기", "다음 주문 요청사항 안내 문구 올리기"],
    "객단가": ["대표 메뉴 + 추가 메뉴 세트 문구 올리기", "최소 주문 금액 점검하기"],
    "남는 재료 처리": ["남은 재료 할인 글 올리기", "재고 다시 세기"],
}


def basic_todos_for_goal(goal: str) -> list[str]:
    """목표별 기본 할 일 2개(목표마다 서로 겹치지 않음) — "AI 추천 아이디어" 상자와 별도로 늘 보여 준다."""
    return list(BASIC_TODOS_BY_GOAL.get(goal, []))


def default_menu(store) -> str | None:
    """review_promo 가 쓸 대표 메뉴 — 가격 있는 메뉴 중 첫 번째, 없으면 메뉴 목록의 첫 번째.
    c6.promo.generate_review_promo 의 기본 메뉴 선택과 같은 규칙(menu 인자를 안 주면 똑같이 고른다)."""
    return next((m for m in store.menu if m in store.menu_prices), None) or (
        store.menu[0] if store.menu else None
    )


def match_menu(store, item: str | None) -> str | None:
    """자유 입력 텍스트(남은 재료 이름)를 가격 있는 메뉴 이름에 맞춘다. 못 찾으면 None."""
    prices = store.menu_prices
    if item in prices:
        return item
    return next((m for m in prices if item and item in m), None)


@dataclass
class PlaybookStep:
    step_id: str
    when: str
    what: str
    where: str
    minutes: int
    generator: str | None = None
    tip: str = ""
    channel: str | None = None     # channels 필터용. None 이면 채널과 무관해 필터에 안 걸림
    max_chars: int | None = None   # 생성 글자 수 제한(배민 가게 소개 첫 줄 등). 없으면 None
    cost_krw: int = 0              # 이 할 일의 추정 비용(원). 글 올리기 등 돈이 안 드는 일은 0

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id, "when": self.when, "what": self.what, "where": self.where,
            "minutes": self.minutes, "generator": self.generator, "tip": self.tip,
            "max_chars": self.max_chars, "cost_krw": self.cost_krw,
        }


def _fix_first_steps(today: date, strategy) -> list[PlaybookStep]:
    hyp = strategy.source_hypothesis
    if hyp == "H_REPEAT":
        return [
            PlaybookStep(
                "notice", _date_label(today, 0), "가게 공지 올리기", _channel_where("naver_place"), 5,
                generator="prevention_notice", tip="재발 방지 다짐이 들어갔는지 확인해요", channel="naver_place",
            ),
            PlaybookStep(
                "reply", _date_label(today, 0), "불만 리뷰 답글 달기",
                "리뷰가 들어온 채널(배민·쿠팡이츠·요기요 등) > 리뷰 답글" + _SCREEN_NOTE, 10,
                generator="reply_draft", tip="사과와 다음 조치가 들어갔는지 확인해요",
            ),
            PlaybookStep(
                "pack_memo", _date_label(today, 0), '포장대에 "주문서 대조" 메모 붙이기',
                "가게 포장대(아래 문구를 출력해서 붙여요)", 2,
                tip='"포장 전, 주문서와 음식을 한 번 더 맞춰보세요" 한 줄이면 충분해요',
            ),
            PlaybookStep(
                "recheck", _date_label(today, 14), "같은 불만 리뷰 수 다시 세기",
                "리뷰가 들어온 채널 전체", 5,
                tip="오늘 이전 14일과 비교해 줄었는지 확인해요",
            ),
        ]
    if hyp == "H_LATE":
        return [
            PlaybookStep(
                "notice", _date_label(today, 0), "배달 지연 안내 공지 올리기", _channel_where("naver_place"), 5,
                generator="late_notice_template",
                tip="피크 시간 조리 예상 시간을 늘린다는 조치가 들어갔는지 확인해요", channel="naver_place",
            ),
            PlaybookStep(
                "peak_time", _date_label(today, 0), "피크 시간 조리 예상 시간 늘리기",
                "쓰는 배달앱의 조리 예상 시간 설정" + _SCREEN_NOTE, 3,
                tip="실제 조리에 걸리는 시간보다 여유 있게 잡아요",
            ),
            PlaybookStep(
                "recheck", _date_label(today, 14), "지연 관련 리뷰 수 다시 세기",
                "리뷰가 들어온 채널 전체", 5,
                tip="오늘 이전 14일과 비교해 줄었는지 확인해요",
            ),
        ]
    # H_STORE_ONLY
    return [
        PlaybookStep(
            "checklist", _date_label(today, 0), "원인 점검 체크리스트 확인",
            "가게 안 + 배달앱 가게 페이지", 10,
            tip="가격 변동 / 영업시간 / 메뉴 사진 / 최근 별점 / 품절 표시, 5개를 하나씩 확인해요",
        ),
    ]


def _review_promo_steps(today: date, store) -> list[PlaybookStep]:
    menu = default_menu(store) or "대표 메뉴"
    when = f"{_date_label(today, 0)}, 피크 2시간 전"
    return [
        PlaybookStep(
            "naver_notice", when, "네이버 플레이스 소식 올리기", _channel_where("naver_place"), 5,
            generator="review_promo", tip="칭찬받은 점이 자연스럽게 들어갔는지 확인해요", channel="naver_place",
        ),
        PlaybookStep(
            "baemin_intro", when, "배민 가게 소개 첫 줄 바꾸기", _channel_where("baemin"), 3,
            generator="review_promo", tip="40자 안에 들어오는지 확인해요", channel="baemin", max_chars=40,
        ),
        PlaybookStep(
            "menu_photo", _date_label(today, 0), f"{menu} 사진 다시 찍기",
            "가게(휴대폰으로 찍어 각 배달앱에 등록)" + _SCREEN_NOTE, 10,
            tip="밝은 곳에서, 접시를 꽉 채워서 찍어요",
        ),
    ]


def _coupon_steps(today: date, answers, strategy) -> list[PlaybookStep]:
    apps_label = _apps_label(answers)
    return [
        PlaybookStep(
            "coupon_values", _date_label(today, 0), "쿠폰 값 정하기", "쿠폰 카드(메뉴·할인액·장수·기간·시간대) 참고", 3,
            tip="장수 = 예산 ÷ 할인액, 예산을 넘지 않는지 확인해요",
        ),
        PlaybookStep(
            "coupon_promo_post", _date_label(today, 0), "쿠폰 알림 글 올리기", _channel_where("naver_place"), 5,
            generator="coupon_promo", tip="쿠폰 조건(시간대·기간)이 글 끝에 붙어 있는지 확인해요", channel="naver_place",
        ),
        PlaybookStep(
            "coupon_create", _date_label(today, 0), "쿠폰 만들기",
            f"{apps_label} 사장님 사이트 > 쿠폰" + _SCREEN_NOTE, 10,
            tip="쿠폰 카드의 메뉴·할인액·기간과 똑같이 입력해요",
            cost_krw=strategy.budget_won,  # 추정 — 쿠폰 전체 예상 비용(장수 x 할인액)
        ),
        PlaybookStep(
            "measure", _date_label(today, 14), "쿠폰 사용 수 확인하기",
            f"{apps_label} 사장님 사이트 > 쿠폰 사용 내역", 5,
            tip="오늘부터 14일 동안 사용된 쿠폰 수를 세어요",
        ),
    ]


def _no_action_steps(today: date) -> list[PlaybookStep]:
    return [
        PlaybookStep(
            "wait", _date_label(today, 0), "지금은 유지", "-", 0,
            tip="조건에 맞는 뚜렷한 전략이 없어 당장은 할 일이 없어요",
        ),
    ]


def _steps_for_strategy(today: date, answers, ctx, strategy) -> list[PlaybookStep]:
    if strategy.type == "fix_first":
        return _fix_first_steps(today, strategy)
    if strategy.type == "review_promo":
        return _review_promo_steps(today, ctx.store)
    if strategy.type in _COUPON_TYPES:
        return _coupon_steps(today, answers, strategy)
    return _no_action_steps(today)


def _measure_for(today: date, strategy) -> str:
    """steps 가 채널·시간 필터로 줄어도 "언제 무엇을 비교"는 늘 알려 준다."""
    t, hyp = strategy.type, strategy.source_hypothesis
    if t == "fix_first" and hyp == "H_REPEAT":
        when, what = _date_label(today, 14), "같은 불만 리뷰 수"
    elif t == "fix_first" and hyp == "H_LATE":
        when, what = _date_label(today, 14), "지연 관련 리뷰 수"
    elif t == "fix_first":  # H_STORE_ONLY
        when, what = _date_label(today, 14), "리뷰·별점 변화"
    elif t in _COUPON_TYPES:
        when, what = _date_label(today, 14), "쿠폰 사용 수"
    elif t == "review_promo":
        when, what = _date_label(today, 14), "게시물 반응(조회·문의)"
    else:
        return "측정: 게시물 반응"
    return f"측정: {when}, {what} 비교"


def _active_channels(store, answers) -> list[str]:
    if answers.channels:
        return [c for c in store.channels if c in answers.channels]
    return list(store.channels)


def build_playbook(ctx, strategy, answers, today: date | None = None) -> dict:
    """전략 1개 -> {title, total_minutes, steps, measure}. drafts·coupon_card 는
    marketing_survey.execute 쪽이 각 step 의 generator 를 실행해 덧붙인다."""
    today = today or date.today()
    steps = _steps_for_strategy(today, answers, ctx, strategy)
    measure = _measure_for(today, strategy)

    active = _active_channels(ctx.store, answers)
    steps = [s for s in steps if s.channel is None or s.channel in active]

    if answers.weekly_hours <= 1:
        steps = steps[:2]

    total_cost_krw = sum(s.cost_krw for s in steps)
    return {
        "title": strategy.title,
        "total_minutes": sum(s.minutes for s in steps),
        "steps": [s.to_dict() for s in steps],
        "measure": measure,
        "total_cost_krw": total_cost_krw,
        "over_budget": bool(answers.budget_won) and total_cost_krw > answers.budget_won,
    }
