"""남은 재료 팔기 — "오늘만 세트"(할인 가능) 또는 "오늘의 추천"(할인 불가) 글 1개를 만든다.

재료별 구성품 데이터가 없어(StoreProfile 에는 menu_prices 만 있음), "재료"는 가게 메뉴 이름을
그대로 쓴다(메뉴 구성품 버튼 = 메뉴 목록, 직접 입력도 가능). 세트 가격은 짝지은 두 메뉴 가격의
합계를 코드로 계산한다 — 사장님이 입력한 값(메뉴 가격) 만 쓰고 새 숫자를 지어내지 않는다.

build_leftover_plan(ctx, raw, key, model, today=None) -> marketing_survey.execute.build_plan() 과
같은 모양({title, total_minutes, steps, drafts, measure, total_cost_krw}).
"""
from __future__ import annotations

from datetime import date

from c6.promo import generate_review_promo, review_promo_fallback_text
from marketing_survey.execute import PROMO_CARD
from marketing_survey.flow import _round_to_step
from marketing_survey.playbooks import PlaybookStep, _channel_where, _date_label

SET_DISCOUNT_RATE = 0.9


def pick_pair_menus(store, item: str | None) -> tuple[str, str] | None:
    """item 과 짝지을 메뉴 2개(가격 있는 메뉴 중) 를 고른다. 가격 있는 메뉴가 2개 미만이면 None."""
    prices = store.menu_prices
    if len(prices) < 2:
        return None
    chosen = item if item in prices else next((m for m in prices if item and item in m), None)
    if chosen is None:
        chosen = next(iter(prices))
    others = [m for m in prices if m != chosen]
    return chosen, others[0]


def set_bundle_price(store, item: str | None) -> dict | None:
    """세트 가격 = 두 메뉴 가격 합계의 90%, 100원 단위 반올림. 짝지을 메뉴가 없으면 None."""
    pair = pick_pair_menus(store, item)
    if pair is None:
        return None
    a, b = pair
    original = store.menu_prices[a] + store.menu_prices[b]
    bundle = _round_to_step(original * SET_DISCOUNT_RATE)
    return {"menus": [a, b], "original_won": original, "bundle_won": bundle}


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
    discount_allowed = bool(raw.get("leftover_discount_allowed"))

    when = f"{_date_label(today, 0)}, 마감 2시간 전"
    base_text = _base_text(ctx, item, key, model)
    bundle = set_bundle_price(store, item) if discount_allowed else None

    if discount_allowed and bundle is not None:
        title = "오늘만 세트"
        set_line = f"🍱 {bundle['menus'][0]} + {bundle['menus'][1]} 오늘만 세트 {bundle['bundle_won']:,}원"
        draft_text = f"{base_text}\n{set_line}" if base_text else set_line
        tip = f"{portions}인분 남았다고 하셨어요 — 세트가 소진되면 바로 글을 내려 주세요"
        measure = "측정: 오늘 중, 세트 메뉴 주문 수"
    else:
        title = "오늘의 추천"
        rec_line = f"✨ 오늘의 추천: {item or '대표 메뉴'}"
        draft_text = f"{base_text}\n{rec_line}" if base_text else rec_line
        tip = f"{portions}인분 남았다고 하셨어요 — 할인 없이 추천만 해요"
        measure = "측정: 오늘 중, 추천 메뉴 주문 수"
        bundle = None

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
