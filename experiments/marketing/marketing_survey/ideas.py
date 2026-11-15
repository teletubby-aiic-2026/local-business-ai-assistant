"""목표별 "AI 추천 아이디어" 데이터 — 제목·왜·할 일은 코드 고정 문구, 글도 고정 틀로 엮는다
(AI 호출 없음, 사장님이 답하지 않은 사실은 쓰지 않는다).

아이디어는 목표 하나에만 배정된다("공통" 없음) — IDEAS_BY_GOAL[goal] 의 순서가 그대로
[다른 아이디어 보기] 순환 순서다(무작위 아님, 다른 목표로는 안 넘어간다).

idea 1개 = {id, title, why, todos: [...], draft_kind,
            needs_question, question(있으면), question_type("bool"|"text", 있으면)}.
needs_question 이 True 인 아이디어(custom_option·weekly_side·neighbor_cross)는 질문에 답해야
글이 만들어진다 — [이 아이디어 해 보기]를 눌렀을 때만 그 질문을 잇는다(목록을 그냥 훑어볼 때는
묻지 않는다). try_idea() 가 답(answer)을 받아 글을 만들거나, 조건이 안 맞으면 skip=True 를 돌려준다
(custom_option 에서 "아니요"면 이 아이디어는 통째로 건너뛴다).
"""
from __future__ import annotations

from marketing_survey.playbooks import default_menu as _default_menu


def _always(ctx, answers) -> bool:
    return True


IDEAS_BY_GOAL: dict[str, list[dict]] = {
    "새 손님": [
        {
            "id": "story_link", "title": "가게 이야기 글",
            "why": "새 손님은 가게를 모르니 이야기로 먼저 알려요",
            "todos": ["[가게 이야기 글 만들기]로 이동해 진행"],
            "draft_kind": "story_link", "needs_question": False,
        },
        {
            "id": "first_order_combo", "title": "첫 주문 추천 조합",
            "why": "무엇을 고를지 못 정한 새 손님에겐 조합을 먼저 보여주는 게 효과적이에요",
            "todos": ["대표 메뉴 + 메뉴 1개 조합 글 올리기"],
            "draft_kind": "first_order_combo", "needs_question": False,
        },
        {
            "id": "rainy_day", "title": "비 오는 날 소식 미리 만들기",
            "why": "비 오는 날 바로 올릴 소식을 미리 준비해 둬요(날씨 데이터는 안 썼어요, 미리 써 두는 글이에요)",
            "todos": ["비 오는 날 올릴 소식 써 두기"],
            "draft_kind": "rainy_day", "needs_question": False,
        },
        {
            "id": "neighbor_cross", "title": "이웃 가게와 전단 교환",
            "why": "근처 가게와 서로 전단을 나누면 비용 없이 손님을 넓힐 수 있어요",
            "todos": ["근처에 어떤 가게가 있는지 확인하기", "전단 교환 제안 메시지 보내기"],
            "draft_kind": "neighbor_cross", "needs_question": True,
            "question": "근처에 어떤 가게가 있나요?", "question_type": "text",
        },
    ],
    "재주문": [
        {
            "id": "remember_taste", "title": "지난번 요청 기억 안내",
            "why": "지난번과 같은 맛을 원하면 요청사항에 적어 달라고 안내해요",
            "todos": ["안내 문구 올리기"],
            "draft_kind": "remember_taste", "needs_question": False,
        },
        {
            "id": "custom_option", "title": "맵기·양 조절 안내",
            "why": "조절이 가능하면 재주문으로 이어지기 쉬워요",
            "todos": ["조절 가능 여부 확인하기", "가능하면 안내 글 올리기"],
            "draft_kind": "custom_option", "needs_question": True,
            "question": "맵기·밥 양 조절이 가능하신가요?", "question_type": "bool",
        },
        {
            "id": "weekly_side", "title": "이번 주 바뀐 반찬 소식",
            "why": "이번 주만의 변화가 있으면 재주문 이유가 돼요",
            "todos": ["이번 주 바뀐 반찬 확인하기", "소식 글 올리기"],
            "draft_kind": "weekly_side", "needs_question": True,
            "question": "이번 주 바뀐 반찬이 있다면 적어 주세요.", "question_type": "text",
        },
    ],
    "객단가": [
        {
            "id": "two_person_set", "title": "2인 구성 추천",
            "why": "둘이 시킬 때 뭘 더할지 보여주면 객단가가 올라가요",
            "todos": ["2인 구성 글 올리기"],
            "draft_kind": "two_person_set", "needs_question": False,
        },
        {
            "id": "pair_line", "title": "같이 추천 한 줄",
            "why": "배민 메뉴 설명에 짧게 추천을 더하면 객단가가 올라가요",
            "todos": ["배민 메뉴 설명에 한 줄 추가하기"],
            "draft_kind": "pair_line", "needs_question": False,
        },
        {
            "id": "side_photo", "title": "사이드 메뉴 사진 추가",
            "why": "사이드 메뉴가 보이면 같이 담는 손님이 늘어요",
            "todos": ["사이드 메뉴 사진 찍어 추가하기"],
            "draft_kind": None, "needs_question": False,
        },
    ],
}


def ideas_for(goal: str, ctx, answers) -> list[dict]:
    """그 목표에만 배정된 아이디어들(코드에 적힌 순서 그대로, 다른 목표 아이디어는 안 섞인다)."""
    return [i for i in IDEAS_BY_GOAL.get(goal, []) if i.get("condition", _always)(ctx, answers)]


def idea_at(goal: str, ctx, answers, index: int) -> tuple[dict | None, int]:
    """목표에 맞는 아이디어 중 index 번째(그 목표 안에서만 순환). 하나도 없으면 (None, 0)."""
    candidates = ideas_for(goal, ctx, answers)
    if not candidates:
        return None, 0
    idx = index % len(candidates)
    return candidates[idx], idx


def try_idea(idea: dict, ctx, answers, answer: str | None = None) -> dict:
    """idea 를 글로 만든다 — {"draft": str|None, "skip": bool}.
    skip=True 면 이 아이디어는(조건이 안 맞아) 쓸 수 없다는 뜻 — 호출한 쪽이 다음 아이디어로 넘어간다."""
    kind = idea.get("draft_kind")
    store = ctx.store
    menu = answers.discount_menu or _default_menu(store)

    if kind == "story_link":
        return {"draft": None, "skip": False}

    if kind == "first_order_combo":
        other = next((m for m in store.menu_prices if m != menu), None)
        if not menu or not other:
            return {"draft": None, "skip": True}
        total = store.menu_prices[menu] + store.menu_prices[other]
        return {"draft": f"첫 주문이시면 {menu} + {other} 조합 어때요? 둘이 합쳐 {total:,}원이에요.", "skip": False}

    if kind == "rainy_day":
        return {
            "draft": (
                "비 오는 날엔 따뜻한 한 끼 어떠세요? 포장 꼼꼼히 챙겨서 보내드릴게요. "
                "(날씨 데이터는 안 썼어요 — 미리 써 둔 글이에요)"
            ),
            "skip": False,
        }

    if kind == "neighbor_cross":
        place = (answer or "").strip()
        if place:
            return {"draft": f"안녕하세요, {place} 근처에서 가게를 하고 있어요. 전단 교환 어떨까요?", "skip": False}
        return {"draft": "안녕하세요, 근처에서 가게를 하고 있는데 서로 전단을 나눠 붙여볼까요?", "skip": False}

    if kind == "remember_taste":
        return {"draft": "지난번 맵기·요청 그대로 원하시면 요청사항에 적어 주세요.", "skip": False}

    if kind == "custom_option":
        if answer != "예":
            return {"draft": None, "skip": True}
        return {"draft": "맵기·밥 양을 조절해 드릴 수 있어요. 요청사항에 적어 주세요.", "skip": False}

    if kind == "weekly_side":
        side = (answer or "").strip()
        if not side:
            return {"draft": None, "skip": True}
        return {"draft": f"이번 주는 {side}를 곁들여 드려요!", "skip": False}

    if kind == "two_person_set":
        other = next((m for m in store.menu_prices if m != menu), None)
        if not menu or not other:
            return {"draft": None, "skip": True}
        total = store.menu_prices[menu] + store.menu_prices[other]
        return {"draft": f"{menu} + {other} 2인 구성 {total:,}원(할인 없음)", "skip": False}

    if kind == "pair_line":
        other = next((m for m in store.menu_prices if m != menu), None)
        if not other:
            return {"draft": None, "skip": True}
        line = f"{other}랑 같이 추천해요"
        if len(line) > 40:
            line = "같이 추천해요"
        return {"draft": line, "skip": False}

    return {"draft": None, "skip": False}
