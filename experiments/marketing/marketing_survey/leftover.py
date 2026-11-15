"""남은 재료 팔기 — 사장님이 고른 "어떻게 팔까요?" 에 따라 "오늘만 세트"(다른 메뉴와 세트),
"이 메뉴만 할인", "오늘의 추천"(할인 없음) 중 글 1개를 만든다.

재료별 구성품 데이터가 없어(StoreProfile 에는 menu_prices 만 있음), "재료"는 가게 메뉴 이름을
그대로 쓴다(메뉴 구성품 버튼 = 메뉴 목록, 직접 입력도 가능). 세트 메뉴는 사장님이 직접 고른
메뉴(leftover_bundle_menu) 만 쓴다 — 묻지 않은 메뉴를 자동으로 끼워 넣지 않는다. 세트 가격은
짝지은 두 메뉴 가격의 합계를 코드로 계산한다 — 사장님이 입력한 값(메뉴 가격) 만 쓰고 새 숫자를
지어내지 않는다.

build_leftover_plan(ctx, raw, key, model, today=None) -> marketing_survey.execute.build_plan() 과
같은 모양({title, total_minutes, steps, drafts, measure, total_cost_krw}).
"""
from __future__ import annotations

from datetime import date

from c6.promo import generate_review_promo, review_promo_fallback_text
from marketing_survey.execute import PROMO_CARD
from marketing_survey.flow import _round_to_step
from marketing_survey.playbooks import PlaybookStep, _channel_where, _date_label, match_menu

SET_DISCOUNT_RATE = 0.9

MODE_BUNDLE = "bundle"
MODE_DISCOUNT_ONLY = "discount_only"
MODE_NO_DISCOUNT = "no_discount"


def bundle_price(store, item: str, partner: str) -> dict:
    """세트 가격 = item·partner 가격 합계의 90%, 100원 단위 반올림(둘 다 사장님이 고른 메뉴)."""
    original = store.menu_prices[item] + store.menu_prices[partner]
    bundle_won = _round_to_step(original * SET_DISCOUNT_RATE)
    return {"menus": [item, partner], "original_won": original, "bundle_won": bundle_won}


def _base_text(ctx, item: str | None, key, model) -> str:
    if key is None:
        return review_promo_fallback_text(ctx.store, item)
    result = generate_review_promo(ctx, PROMO_CARD, key, model=model, menu=item)
    draft = next((d for d in result.drafts if d.generator == "review_promo"), None)
    return draft.text if draft else ""


def build_leftover_plan(ctx, raw: dict, key, model: str = "HCX-005", today: date | None = None) -> dict:
    today = today or date.today()
    store = ctx.store
    item = (raw.get("leftover_item") or "").strip() or None
    portions = int(raw.get("leftover_portions") or 0)
    mode = raw.get("leftover_mode") or MODE_NO_DISCOUNT

    when = f"{_date_label(today, 0)}, 마감 2시간 전"
    base_text = _base_text(ctx, item, key, model)
    bundle = None

    if mode == MODE_BUNDLE:
        chosen = match_menu(store, item)
        partner = raw.get("leftover_bundle_menu")
        if chosen and partner and partner in store.menu_prices and partner != chosen:
            bundle = bundle_price(store, chosen, partner)

    if bundle is not None:
        title = "오늘만 세트"
        set_line = f"🍱 {bundle['menus'][0]} + {bundle['menus'][1]} 오늘만 세트 {bundle['bundle_won']:,}원"
        draft_text = f"{base_text}\n{set_line}" if base_text else set_line
        tip = f"{portions}인분 남았다고 하셨어요 — 세트가 소진되면 바로 글을 내려 주세요"
        measure = "측정: 오늘 중, 세트 메뉴 주문 수"
    elif mode == MODE_DISCOUNT_ONLY:
        title = "이 메뉴만 할인"
        discount_line = f"🔥 오늘만, {item or '대표 메뉴'} 할인 판매해요"
        draft_text = f"{base_text}\n{discount_line}" if base_text else discount_line
        tip = f"{portions}인분 남았다고 하셨어요 — 이 메뉴만 할인해요"
        measure = "측정: 오늘 중, 할인 메뉴 주문 수"
    else:
        title = "오늘의 추천"
        rec_line = f"✨ 오늘의 추천: {item or '대표 메뉴'}"
        draft_text = f"{base_text}\n{rec_line}" if base_text else rec_line
        tip = f"{portions}인분 남았다고 하셨어요 — 할인 없이 추천만 해요"
        measure = "측정: 오늘 중, 추천 메뉴 주문 수"

    step = PlaybookStep(
        "leftover_post", when, f"{title} 글 올리기", _channel_where("naver_place"), 5,
        tip=tip, channel="naver_place", cost_krw=0,
    )
    return {
        "title": title,
        "total_minutes": step.minutes,
        "steps": [step.to_dict()],
        "drafts": {"leftover_post": draft_text},
        "measure": measure,
        "total_cost_krw": step.cost_krw,
        "bundle": bundle,
    }
