"""목표별 "AI 추천 아이디어" 데이터 — 제목·왜·할 일은 코드 고정 문구, 글도 고정 틀로 엮는다
(AI 호출 없음, 사장님이 답하지 않은 사실은 쓰지 않는다).

idea 1개 = {id, goals: [...], condition(ctx, answers)->bool, title, why, todos: [...], draft_kind}.
ideas_for(goal, ctx, answers) 는 그 목표에 맞고 condition 을 만족하는 아이디어를 "코드 순서대로"
돌려준다(무작위 아님) — idea_at() 이 index % len 으로 그 중 하나를 고른다([다른 아이디어 보기]용).
"""
from __future__ import annotations

from marketing_survey.playbooks import default_menu as _default_menu


def _always(ctx, answers) -> bool:
    return True


def _min_order_condition(ctx, answers) -> bool:
    menu = answers.discount_menu or _default_menu(ctx.store)
    price = ctx.store.menu_prices.get(menu, 0) if menu else 0
    return bool(price) and bool(answers.avg_order_won) and answers.avg_order_won < price * 1.5


IDEAS = [
    {
        "id": "upsell_pair", "goals": ["객단가"], "condition": _always,
        "title": "메뉴 묶어 팔기", "why": "객단가를 늘리려면 대표 메뉴에 한 가지를 더 얹는 게 가장 쉬워요",
        "todos": ["대표 메뉴 + 추가 메뉴 문구 올리기", "추가 금액 안내하기"], "draft_kind": "upsell_pair",
    },
    {
        "id": "min_order_check", "goals": ["객단가"], "condition": _min_order_condition,
        "title": "최소 주문 금액 점검", "why": "평균 주문 금액이 대표 메뉴 가격의 1.5배보다 낮아요",
        "todos": ["최소 주문 금액·2인 세트 점검"], "draft_kind": None,
    },
    {
        "id": "thank_note", "goals": ["재주문"], "condition": _always,
        "title": "포장 손글씨 메모", "why": "포장에 메모 한 줄이면 다음 주문으로 이어지기 쉬워요",
        "todos": ["메모 문구 3개 중 하나 골라 인쇄하기", "포장대에 붙이기"], "draft_kind": "thank_note",
    },
    {
        "id": "remember_request", "goals": ["재주문"], "condition": _always,
        "title": "요청사항 기억 안내", "why": "다음 주문 때 요청사항을 남기면 더 편하다고 안내해요",
        "todos": ["요청사항 안내 문구 올리기"], "draft_kind": "remember_request",
    },
    {
        "id": "story_link", "goals": ["새 손님"], "condition": _always,
        "title": "가게 이야기 글", "why": "새 손님은 가게를 모르니 이야기로 먼저 알려요",
        "todos": ["[가게 이야기 글 만들기]로 이동해 진행"], "draft_kind": "story_link",
    },
    {
        "id": "rainy_day", "goals": ["새 손님", "재주문", "객단가", "남는 재료 처리"], "condition": _always,
        "title": "비 오는 날 소식 미리 만들기",
        "why": "비 오는 날 바로 올릴 소식을 미리 준비해 둬요(날씨 데이터는 안 썼어요, 미리 써 두는 글이에요)",
        "todos": ["비 오는 날 올릴 소식 써 두기"], "draft_kind": "rainy_day",
    },
    {
        "id": "neighbor_cross", "goals": ["새 손님", "재주문", "객단가", "남는 재료 처리"], "condition": _always,
        "title": "이웃 가게와 전단 교환", "why": "근처 가게와 서로 전단을 나누면 비용 없이 손님을 넓힐 수 있어요",
        "todos": ["근처에 어떤 가게가 있는지 확인하기", "전단 교환 제안 메시지 보내기"], "draft_kind": "neighbor_cross",
    },
]


def ideas_for(goal: str, ctx, answers) -> list[dict]:
    """goal 에 맞고 condition 을 만족하는 아이디어들(코드에 적힌 순서 그대로)."""
    return [i for i in IDEAS if goal in i["goals"] and i.get("condition", _always)(ctx, answers)]


def idea_at(goal: str, ctx, answers, index: int) -> tuple[dict | None, int]:
    """목표에 맞는 아이디어 중 index 번째(순환). 하나도 없으면 (None, 0)."""
    candidates = ideas_for(goal, ctx, answers)
    if not candidates:
        return None, 0
    idx = index % len(candidates)
    return candidates[idx], idx


def render_idea_draft(idea: dict, ctx, answers) -> str | None:
    """idea 의 draft_kind 로 글 1개를 만든다(없으면 None). 전부 코드 틀만 쓴다."""
    kind = idea.get("draft_kind")
    store = ctx.store
    menu = answers.discount_menu or _default_menu(store)

    if kind == "upsell_pair":
        other = next((m for m in store.menu_prices if m != menu), None)
        if not other:
            return None
        add_price = store.menu_prices[other]
        return f"{menu or '대표 메뉴'} 주문하시면 {other} 추가 시 {add_price:,}원에 같이 담아 드려요."
    if kind == "thank_note":
        return "\n".join([
            "오늘도 맛있게 드세요, 감사합니다 :)",
            "정성껏 담았어요. 다음에 또 뵐게요!",
            "맛있게 드시고 좋은 하루 보내세요.",
        ])
    if kind == "remember_request":
        return "다음 주문 때 요청사항을 남겨 주시면 더 신경 써서 준비할게요."
    if kind == "rainy_day":
        return (
            "비 오는 날엔 따뜻한 한 끼 어떠세요? 포장 꼼꼼히 챙겨서 보내드릴게요. "
            "(날씨 데이터는 안 썼어요 — 미리 써 둔 글이에요)"
        )
    if kind == "neighbor_cross":
        return "안녕하세요, 근처에서 가게를 하고 있는데 서로 전단을 나눠 붙여볼까요?"
    return None
