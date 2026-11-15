"""챗봇형 설문 — 한 번에 한 질문, 답에 따라 다음 질문이 갈라진다. AI 호출 없음, 전부 데이터+규칙.

기존 marketing_survey.survey 의 SurveyAnswers 필드 이름과 marketing_survey.hypotheses 의 가설 id
(H_LATE/H_REPEAT/H_STORE_ONLY/H_AREA_DROP)를 그대로 쓴다 — 이 모듈은 "질문 순서"만 다루고,
답을 최종 결정으로 바꾸는 규칙은 여전히 marketing_survey.decide 에 있다.

노드 그래프 (NODES): 노드 1개 = {id, text(또는 동적이면 "dynamic" 태그), options[]}.
option 1개 = {label, set(라Raw 설문 답 dict 에 합칠 값), confirm(가설 확인 dict 에 합칠 값), next(다음 노드 id)}.
"DECISION" 은 끝(terminal) 표시 — 이 노드에 닿으면 흐름이 끝나고 decide() 를 부른다.

전체 흐름
  repeat_complaint(반복 불만?)
    예 -> complaint_type(불만 종류)
      포장 누락 -> H_REPEAT 확정 -> DECISION (예산 등은 안 물음 — decide() 가 쿠폰보다 공지 먼저)
      배달 지연 -> H_LATE 확정 -> DECISION
      그 외     -> H_STORE_ONLY 후보 확정 -> goal (상권 질문에서 취소될 수 있음)
    아니요/모름 -> goal
  goal(목표) -> area_question(상권 질문: snapshot 값·basis_label 을 문장에 넣음)
    예   -> H_AREA_DROP 확정, H_STORE_ONLY 취소 -> budget
    아니요 -> H_STORE_ONLY 아님(취소) -> budget
    모름  -> 보류(아무것도 확정 안 함) -> budget
  budget(예산) -> 0원이면 DECISION, 아니면 discount_allowed
  discount_allowed(할인 가능?) -> 아니요면 DECISION, 예면 menu
  menu(할인 메뉴, 가격 같이 표시) -> max_discount
  max_discount(최대 할인, 가격의 10/20/30%, 100원 단위) -> capacity
  capacity(주문 감당) -> channels
  channels(쓰는 채널, 여러 개 + [다음]) -> DECISION

follow_up(재주문 쿠폰 질문)은 FOLLOW_UP_START("budget")에서 같은 체인을 재사용한다 — goal 질문은
다시 묻지 않는다(build_follow_up_strategy 가 goal 과 상관없이 reorder_coupon 으로 만들기 때문).
"""

import re

from marketing_survey.hypotheses import _area_drop_snapshot

DECISION = "DECISION"
FOLLOW_UP_START = "budget"
START = "start"

# "start" 보기의 mode 값 -> server.py 가 FlowState.mode 로 그대로 쓴다(흐름 데이터와 분리해 둠).
START_MODES = {
    "맞춤 홍보 제안": "survey",
    "남은 재료 팔기": "leftover",
    "광고비 점검": "adspend",
    "가게 이야기 글": "story",
    "쿠폰 결과 확인": "coupon_result",
}

_MENU_AMOUNT_STEP = 100
_MENU_AMOUNT_PCTS = (10, 20, 30)

CHANNEL_LABELS = {
    "baemin": "배민", "coupangeats": "쿠팡이츠", "yogiyo": "요기요",
    "naver_place": "네이버 플레이스",
}


def _round_to_step(amount: float, step: int = _MENU_AMOUNT_STEP) -> int:
    return int(round(amount / step)) * step


NODES = {
    "start": {
        "text": "무엇을 도와드릴까요?",
        "options": [
            {"label": label, "next": next_id}
            for label, next_id in (
                ("맞춤 홍보 제안", "repeat_complaint"),
                ("남은 재료 팔기", "leftover_ingredient"),
                ("광고비 점검", "adspend_baemin_spend"),
                ("가게 이야기 글", "story_reason"),
                ("쿠폰 결과 확인", "coupon_issued"),
            )
        ],
    },
    "leftover_ingredient": {
        "free_input": {"key": "leftover_item", "type": "text"},
        "suggest_menu": True,
        "text": "어떤 재료(메뉴)가 남았나요? 버튼을 고르거나 직접 입력해 주세요.",
        "next": "leftover_portions",
    },
    "leftover_portions": {
        "free_input": {"key": "leftover_portions", "type": "number"},
        "text": "몇 인분 남았나요? 숫자로 답해 주세요.",
        "next": "leftover_discount",
    },
    "leftover_discount": {
        "text": "할인 가능한가요?",
        "options": [
            {"label": "예", "set": {"leftover_discount_allowed": True}, "next": DECISION},
            {"label": "아니요", "set": {"leftover_discount_allowed": False}, "next": DECISION},
        ],
    },
    "adspend_baemin_spend": {
        "free_input": {"key": "adspend_baemin_spend", "type": "number"},
        "text": "배민 — 이번 달 광고비는 얼마였나요? (원)",
        "next": "adspend_baemin_orders",
    },
    "adspend_baemin_orders": {
        "free_input": {"key": "adspend_baemin_orders", "type": "number"},
        "text": "배민 — 그 광고로 온 주문 수는 몇 건인가요?",
        "next": "adspend_coupangeats_spend",
    },
    "adspend_coupangeats_spend": {
        "free_input": {"key": "adspend_coupangeats_spend", "type": "number"},
        "text": "쿠팡이츠 — 이번 달 광고비는 얼마였나요? (원)",
        "next": "adspend_coupangeats_orders",
    },
    "adspend_coupangeats_orders": {
        "free_input": {"key": "adspend_coupangeats_orders", "type": "number"},
        "text": "쿠팡이츠 — 그 광고로 온 주문 수는 몇 건인가요?",
        "next": "adspend_yogiyo_spend",
    },
    "adspend_yogiyo_spend": {
        "free_input": {"key": "adspend_yogiyo_spend", "type": "number"},
        "text": "요기요 — 이번 달 광고비는 얼마였나요? (원)",
        "next": "adspend_yogiyo_orders",
    },
    "adspend_yogiyo_orders": {
        "free_input": {"key": "adspend_yogiyo_orders", "type": "number"},
        "text": "요기요 — 그 광고로 온 주문 수는 몇 건인가요?",
        "next": DECISION,
    },
    "story_reason": {
        "free_input": {"key": "story_reason", "type": "text"},
        "text": "가게를 시작한 계기를 자유롭게 적어 주세요.",
        "next": "story_keep",
    },
    "story_keep": {
        "free_input": {"key": "story_keep", "type": "text"},
        "text": "음식에서 꼭 지키는 것은 무엇인가요?",
        "next": DECISION,
    },
    "coupon_issued": {
        "free_input": {"key": "coupon_issued", "type": "number"},
        "text": "쿠폰을 몇 장 발급했나요?",
        "next": "coupon_used",
    },
    "coupon_used": {
        "free_input": {"key": "coupon_used", "type": "number"},
        "text": "그 중 몇 장이 사용됐나요?",
        "next": DECISION,
    },
    "repeat_complaint": {
        "text": "최근 반복되는 불만이 있나요?",
        "options": [
            {"label": "예", "next": "complaint_type"},
            {"label": "아니요", "next": "goal"},
            {"label": "모름", "next": "goal"},
        ],
    },
    "complaint_type": {
        "text": "어떤 불만인가요?",
        "options": [
            {"label": "포장 누락", "confirm": {"H_REPEAT": "예"}, "next": DECISION},
            {"label": "배달 지연", "confirm": {"H_LATE": "예"}, "next": DECISION},
            {"label": "그 외", "confirm": {"H_STORE_ONLY": "예"}, "next": "goal"},
        ],
    },
    "goal": {
        "text": "지금 가장 원하시는 건 뭔가요?",
        "options": [
            {"label": g, "set": {"goal": g}, "next": "area_question"}
            for g in ("새 손님", "재주문", "객단가", "남는 재료 처리")
        ],
    },
    "area_question": {
        "dynamic_text": True,
        "options": [
            {"label": "예", "confirm": {"H_AREA_DROP": "예", "H_STORE_ONLY": "아니요"}, "next": "budget"},
            {"label": "아니요", "confirm": {"H_STORE_ONLY": "아니요"}, "next": "budget"},
            {"label": "모름", "next": "budget"},
        ],
    },
    "budget": {
        "text": "월 마케팅 예산은 얼마로 생각하시나요?",
        "options": [
            {
                "label": f"{won:,}원" if won else "0원(지금은 안 씀)",
                "set": {"budget_won": won},
                "next": DECISION if won == 0 else "discount_allowed",
            }
            for won in (0, 50_000, 100_000, 300_000)
        ],
    },
    "discount_allowed": {
        "text": "지금 할인(쿠폰)을 해도 괜찮으신가요?",
        "options": [
            {"label": "예", "set": {"discount_allowed": True}, "next": "menu"},
            {"label": "아니요", "set": {"discount_allowed": False}, "next": DECISION},
        ],
    },
    "menu": {
        "dynamic_options": True,
        "text": "할인해도 괜찮은 메뉴를 골라 주세요.",
    },
    "max_discount": {
        "dynamic_options": True,
        "text": "최대 할인 금액을 골라 주세요.",
    },
    "capacity": {
        "text": "지금보다 주문이 더 오면 감당되시나요?",
        "options": [
            {"label": "충분", "set": {"capacity": "충분"}, "next": "channels"},
            {"label": "빠듯함", "set": {"capacity": "빠듯함"}, "next": "channels"},
        ],
    },
    "channels": {
        "dynamic_options": True,
        "multi": True,
        "text": "손님에게 알릴 때 쓰는 채널을 모두 골라 주세요. 고르고 [다음]을 눌러 주세요.",
    },
}


def _area_question_text(ctx) -> str:
    snap = _area_drop_snapshot(list(ctx.snapshots))
    if snap is None:
        return "이 상권 저녁 시간대 매출 자료가 아직 없어요. 가게 저녁 주문은 줄었다고 느끼시나요?"
    if snap.value is None:
        return (
            "이 상권 저녁 시간대 매출 변화율은 아직 수치가 확정되지 않았어요"
            f"(추정, {snap.basis_label}). 가게 저녁 주문도 줄었나요?"
        )
    return (
        f"이 상권 저녁 시간대 매출이 {snap.value:g}% 줄었어요(추정, {snap.basis_label}). "
        "가게 저녁 주문도 줄었나요?"
    )


def _menu_options(ctx) -> list[dict]:
    store = ctx.store
    options = []
    for menu, price in store.menu_prices.items():
        options.append({"label": f"{menu} ({price:,}원)", "set": {"discount_menu": menu}, "next": "max_discount"})
    return options


def _max_discount_options(ctx, raw: dict) -> list[dict]:
    store = ctx.store
    menu = raw.get("discount_menu")
    price = store.menu_prices.get(menu, 0) if menu else 0
    options = []
    for pct in _MENU_AMOUNT_PCTS:
        amount = _round_to_step(price * pct / 100)
        options.append({
            "label": f"{amount:,}원 (가격의 {pct}%)",
            "set": {"max_discount_won": amount},
            "next": "capacity",
        })
    return options


def _channel_options(ctx) -> list[dict]:
    return [
        {"label": CHANNEL_LABELS.get(c, c), "value": c}
        for c in ctx.store.channels
    ]


def node_text(node_id: str, ctx, state: dict) -> str:
    """노드의 봇 문장. area_question 처럼 동적인 노드는 ctx(snapshot) 를 넣어 만든다."""
    node = NODES[node_id]
    if node.get("dynamic_text"):
        return _area_question_text(ctx)
    return node["text"]


def node_options(node_id: str, ctx, state: dict) -> list[dict]:
    """노드의 보기 버튼 목록. menu/max_discount/channels 는 가게 데이터·이전 답으로 계산한다.
    free_input 노드는 보기가 없고(버튼 없이 자유 입력), suggest_menu 면 메뉴 이름을 "제안 버튼"으로
    보여 준다 — 눌러도 그 라벨이 그대로 자유 입력 값처럼 쓰인다(연결(next) 없이 apply_free_input 이 처리)."""
    node = NODES[node_id]
    if node.get("free_input"):
        if node.get("suggest_menu"):
            return [{"label": m} for m in ctx.store.menu]
        return []
    if not node.get("dynamic_options"):
        return node["options"]
    if node_id == "menu":
        return _menu_options(ctx)
    if node_id == "max_discount":
        return _max_discount_options(ctx, state.get("raw", {}))
    if node_id == "channels":
        return _channel_options(ctx)
    raise ValueError(f"알 수 없는 동적 노드: {node_id}")


def apply_option(state: dict, option: dict) -> dict:
    """option 을 state(raw·confirms)에 합친다. state 는 그대로 바꿔서 돌려준다."""
    state.setdefault("raw", {})
    state.setdefault("confirms", {})
    state["raw"].update(option.get("set", {}))
    state["confirms"].update(option.get("confirm", {}))
    return state


def apply_channels(state: dict, selected: list[str]) -> dict:
    """channels(복수 선택 + [다음]) 전용 — 고른 채널 slug 목록을 raw["channels"]에 넣는다."""
    state.setdefault("raw", {})
    state["raw"]["channels"] = list(selected)
    return state


_NUMBER_RE = re.compile(r"-?\d+")


def apply_free_input(state: dict, node_id: str, value: str) -> dict:
    """free_input 노드 전용 — 버튼 보기 없이 받은 텍스트/숫자를 그대로(또는 숫자만 뽑아) raw 에 넣는다."""
    node = NODES[node_id]
    spec = node["free_input"]
    key, kind = spec["key"], spec["type"]
    if kind == "number":
        m = _NUMBER_RE.search(str(value))
        value = int(m.group()) if m else 0
    else:
        value = str(value).strip()
    state.setdefault("raw", {})
    state["raw"][key] = value
    return state


class FlowError(ValueError):
    """잘못된 노드·보기로 흐름을 진행하려 할 때(클라이언트 state 가 서버 그래프와 어긋남)."""


def resolve_option(node_id: str, ctx, state: dict, label: str) -> dict:
    """node_id 의 보기 중 label 과 같은 것 1개. 없으면 FlowError."""
    for option in node_options(node_id, ctx, state):
        if option["label"] == label:
            return option
    raise FlowError(f"'{node_id}' 노드에 '{label}' 보기가 없어요.")


def advance(node_id: str, ctx, state: dict, label: str) -> str:
    """label 로 고른 보기를 state 에 적용하고 다음 노드 id(또는 DECISION)를 돌려준다.

    예전 Streamlit 버전의 버그: 화면이 들고 있던 "현재 노드"를 DECISION으로 갈 때 갱신하지 않고
    다음 질문 텍스트만 다시 그려서, 같은 노드의 보기를 다시 눌러도 겉보기엔 "그대로"인 것처럼
    보였다(실제로는 매번 다른 state 가 쌓이고 있었다). 여기서는 advance() 가 "다음 노드"를 직접
    계산해 돌려주고, 호출한 쪽(server.py)이 그 값을 곧장 state.node 에 저장하도록 강제해
    같은 노드로 되돌아가거나 멈춰 있을 수 없게 한다. next 가 그래프에 없는 값이면 바로 에러를
    내서(조용히 같은 질문을 반복하는 대신) 원인을 바로 드러낸다.
    """
    node = NODES[node_id]
    if node.get("free_input"):
        apply_free_input(state, node_id, label)
        next_id = node["next"]
    else:
        option = resolve_option(node_id, ctx, state, label)
        apply_option(state, option)
        next_id = option["next"]
    if next_id != DECISION and next_id not in NODES:
        raise FlowError(f"'{node_id}' 의 다음 노드 '{next_id}' 가 그래프에 없어요.")
    return next_id


def all_node_ids() -> list[str]:
    return list(NODES.keys())
