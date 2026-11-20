"""MarketingPlan 의 전략을 C6 생성기로 넘겨 실제 글(초안)을 만든다. AI 호출은 c6 쪽에서만 한다.

- fix_first 중 H_REPEAT 에서 나온 것만 card_sample_a 로 prevention_notice 를 실제로 만든다. 늘
  M1(포장 마감 전 주문서 대조)을 chosen_measures 로 넘긴다 — 안 넘기면 "더 신경 쓰겠습니다"처럼
  조치 없는 문장도 chosen_measure_included 가 그냥 통과시킨다(NOTICE_CHOSEN_MEASURES 참고).
- H_LATE 의 공지는 아직 AI 생성기가 없어 LATE_NOTICE_TEMPLATE 코드 템플릿(합니다체 4문장:
  상황·사과·조치=피크 조리 예상 시간 늘림·요청)을 그대로 쓴다. H_STORE_ONLY 의 fix_first 는
  아직 사장님 확인/운영 조치가 먼저라 글을 만들지 않는다.
- 쿠폰 계열(leftover_deal/reorder_coupon/offpeak_coupon)은 card_sample_b 로 coupon_promo 를 만든다.
  설문이 정한 할인액(discount_won)·메뉴(menu)·시간대(timing)를 c6.promo.generate_coupon_promo 의
  coupon_discount·coupon_menu·time_window 인자로 그대로 넘긴다.
- review_promo 는 card_sample_b 로 c6.promo.generate_review_promo 를 만든다(쿠폰 줄 없음).
  배민 가게 소개 첫 줄(baemin_intro)은 글자 수로 자르지 않고, 40자 안에 들어오는 첫 문장만 쓰거나
  (안 들어오면) 고정 템플릿 한 줄로 바꾼다(_baemin_intro_line).
- 그 외(H_STORE_ONLY 의 fix_first)는 글을 만들지 않고, "사장님 할 일" 한 줄만 남긴다.

key 가 None 이면(CLOVA_API_KEY 없음) c6.registry.run_card 를 통해 저장본(c6/replay)을 재생한다
(review_promo 는 저장본이 없어 review_promo_fallback_text 코드 템플릿을 그대로 쓴다).

build_plan(ctx, strategy, answers, key, model, today=None) -> {title, total_minutes, steps, drafts,
coupon_card, measure}. marketing_survey.playbooks.build_playbook() 이 정한 할 일(steps)마다
run_step_generator() 로 글을 실제로 만들어 drafts 에 담는다(step_id -> 글).
"""

import re

from c6.measures import MEASURES
from c6.notice import generate_prevention_notice
from c6.output import DraftOutput
from c6.promo import generate_coupon_promo, generate_review_promo, review_promo_fallback_text
from c6.registry import run_card
from c6.reply import generate_reply_draft
from marketing_survey import adspend, ideas as _ideas, playbooks
from marketing_survey.coupon_calc import calc as _coupon_calc
from marketing_survey.decide import BUSY_TIMING

_COUPON_GENERATOR_TYPES = {"leftover_deal", "reorder_coupon", "offpeak_coupon"}
COUPON_DAYS = 14  # c6.promo.generate_coupon_promo 의 coupon_days 기본값과 같다(명시적으로 둠)

# H_REPEAT(포장 누락)의 공지는 늘 M1(포장 마감 전 주문서 대조)을 조치로 고른다 — chosen_measures 를
# 안 넘기면 c6.notice 가 "조치를 지어내지 말고 일반적 다짐만" 모드로 돌아서, "더 신경 쓰겠습니다"처럼
# 조치 없는 문장도 chosen_measure_included 를 그냥 통과한다(빈 chosen_measures는 True). 이 전략은
# 항상 주문서 대조가 조치이므로 명시적으로 넘긴다.
NOTICE_CHOSEN_MEASURES = [MEASURES[0]]

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
BAEMIN_INTRO_LIMIT = 40
_BAEMIN_INTRO_FALLBACK_TMPL = "{menu}, 정성껏 만들어 따뜻하게 보내드립니다."


# 카드가 없어 만들 수 없는 글의 안내 (사장님이 직접 등록한 가게, 11/20: 리뷰·상권 지표가 아직 없음). server.py 가 409 로 보여 준다
MISSING_CARD_MESSAGES = {
    "complaint": "이 가게는 아직 맞춤 마케팅에 반복 불만 자료가 없어 이 글을 만들 수 없어요. 리뷰 답글·배달앱 안내문은 추천 카드의 불만 카드에서 만들어 주세요.",
    "promo": "우리 가게 상권 지표가 아직 없어 쿠폰 홍보 글을 만들 수 없어요. 새 손님 홍보 글·남은 재료 팔기 같은 기능은 바로 쓸 수 있어요.",
}


class MissingCard(ValueError):
    """ctx 에 그 종류의 카드가 없음. message 는 사장님에게 보여 줄 문장."""

    def __init__(self, kind: str):
        super().__init__(f"이 가게엔 kind={kind} 카드가 없어요")
        self.kind = kind
        self.message = MISSING_CARD_MESSAGES.get(kind, "이 가게 자료가 아직 없어 이 글을 만들 수 없어요.")


def _card_by_kind(ctx, kind: str):
    """ctx.cards 에서 kind(complaint/promo)로 카드를 찾는다 — card_id 를 박지 않아 가게가
    바뀌어도(ctx.cards 가 바뀌어도) 그대로 쓸 수 있다. 없으면 MissingCard (ValueError)."""
    card = next((c for c in ctx.cards if c.kind == kind), None)
    if card is None:
        raise MissingCard(kind)
    return card


def _has_card(ctx, kind: str) -> bool:
    return any(c.kind == kind for c in ctx.cards)


def _baemin_intro_line(text: str, menu: str | None, limit: int = BAEMIN_INTRO_LIMIT) -> str:
    """배민 가게 소개 첫 줄 — 글자 수로 중간을 자르지 않는다. review_promo 글의 첫 문장이
    limit 자 안에 들어오면 그 문장 그대로 쓰고, 안 들어오면 고정 템플릿 한 줄로 바꾼다."""
    first = _SENT_SPLIT.split(text.strip())[0].strip() if text and text.strip() else ""
    if first and len(first) <= limit:
        return first
    return _BAEMIN_INTRO_FALLBACK_TMPL.format(menu=menu or "대표 메뉴")


LATE_NOTICE_TEMPLATE = (
    "최근 배달이 평소보다 늦어진다는 말씀을 주신 적이 있었습니다.\n"
    "불편을 드려 죄송합니다.\n"
    "오늘부터 피크 시간대 조리 예상 시간을 넉넉하게 늘려 안내하겠습니다.\n"
    "급하신 경우 주문 전에 미리 말씀해 주시면 감사하겠습니다."
)


def _run_notice(ctx, key, model):
    notice_card = _card_by_kind(ctx, "complaint")
    if key is None:
        # key 가 없으면 run_card 가 chosen_measures 를 쓰지 않고 저장본을 그대로 재생하지만,
        # 생성 경로(else)와 똑같이 M1을 넘겨 둔다 — 저장본이 chosen_measures 를 쓰게 바뀌어도
        # 조용히 달라지지 않도록.
        result = run_card(ctx, notice_card, None, chosen_measures=NOTICE_CHOSEN_MEASURES)
    else:
        result = generate_prevention_notice(
            ctx, notice_card, key, model=model, chosen_measures=NOTICE_CHOSEN_MEASURES,
        )
    draft = next((d for d in result.drafts if d.generator == "prevention_notice"), None)
    return result, draft


def _run_reply(ctx, key, model):
    notice_card = _card_by_kind(ctx, "complaint")
    if key is None:
        # reply_draft 는 chosen_measures 를 쓰지 않지만(c6.reply 참고), run_card 호출 모양은
        # _run_notice 와 똑같이 맞춰 둔다.
        result = run_card(ctx, notice_card, None, chosen_measures=NOTICE_CHOSEN_MEASURES)
    else:
        result = generate_reply_draft(ctx, notice_card, key, model=model)
    draft = next((d for d in result.drafts if d.generator == "reply_draft"), None)
    return result, draft


def _run_review_promo(ctx, strategy, key, model):
    if not _has_card(ctx, "promo"):
        # 상권 카드가 없는 가게(직접 등록한 가게, 11/20): 홍보 글은 가게 이름·메뉴만으로 쓰는 코드 템플릿으로 (키 유무와 상관없이)
        text = review_promo_fallback_text(ctx.store, strategy.menu or None)
        return None, DraftOutput(
            draft_id=f"d_demo_card_{ctx.store.store_id.removeprefix('store_')}_promo",
            card_id=f"card_{ctx.store.store_id.removeprefix('store_')}_promo",
            store_id=ctx.store.store_id, generator="review_promo", text=text, data_origin=ctx.store.data_origin)
    promo_card = _card_by_kind(ctx, "promo")
    if key is None:
        # review_promo 는 아직 저장본(c6/replay)이 없어, 다른 생성기처럼 run_card 재생 대신
        # AI 없이도 늘 점검을 통과하는 코드 템플릿(review_promo_fallback_text)을 그대로 쓴다.
        text = review_promo_fallback_text(ctx.store, strategy.menu or None)
        draft = DraftOutput(
            draft_id=f"d_demo_{promo_card.card_id}", card_id=promo_card.card_id,
            store_id=ctx.store.store_id, generator="review_promo", text=text,
            data_origin=ctx.store.data_origin,
        )
        return None, draft
    result = generate_review_promo(ctx, promo_card, key, model=model, menu=strategy.menu or None)
    draft = next((d for d in result.drafts if d.generator == "review_promo"), None)
    return result, draft


def _review_promo_text(ctx, menu, key, model):
    """review_promo 생성기를 메뉴 이름만으로 바로 돌린다(기본 할 일 — Strategy 객체가 없어도 된다)."""
    if key is None or not _has_card(ctx, "promo"):      # 상권 카드가 없는 가게도 코드 템플릿 (11/20)
        return review_promo_fallback_text(ctx.store, menu or None)
    promo_card = _card_by_kind(ctx, "promo")
    result = generate_review_promo(ctx, promo_card, key, model=model, menu=menu or None)
    draft = next((d for d in result.drafts if d.generator == "review_promo"), None)
    return draft.text if draft else None


_PACK_THANK_NOTE = "\n".join([
    "오늘도 맛있게 드세요, 감사합니다 :)",
    "정성껏 담았어요. 다음에 또 뵐게요!",
    "맛있게 드시고 좋은 하루 보내세요.",
])


def _basic_todo_drafts(ctx, answers, key, model):
    """목표별 기본 할 일 2개 + 글(가능하면). 할 일 제목은 playbooks(순수 데이터), 글은 여기서 생성기로 채운다."""
    titles = playbooks.basic_todos_for_goal(answers.goal)
    drafts: list[str | None] = [None] * len(titles)
    store = ctx.store
    menu = answers.discount_menu or playbooks.default_menu(store)

    if answers.goal == "새 손님":
        drafts[0] = _review_promo_text(ctx, menu, key, model)
    elif answers.goal == "재주문":
        try:
            _, reply_draft = _run_reply(ctx, key, model)
        except MissingCard:          # 반복 불만 카드가 없는 가게 (11/20): 답글 없이 요청사항 안내만
            reply_draft = None
        base = reply_draft.text if reply_draft else ""
        extra = "다음 주문 때도 같은 요청사항이 있으시면 요청사항에 적어 주세요."
        drafts[0] = f"{base}\n{extra}" if base else extra
        drafts[1] = _PACK_THANK_NOTE
    elif answers.goal == "객단가":
        other = next((m for m in store.menu_prices if m != menu), None)
        if menu and other:
            add_price = store.menu_prices[other]
            drafts[0] = f"{menu} 주문하시면 {other} 추가 시 {add_price:,}원에 같이 담아 드려요."

    return [{"title": t, "draft": d} for t, d in zip(titles, drafts)]


def run_step_generator(ctx, strategy, generator_name, key, model="HCX-005"):
    """playbooks.PlaybookStep.generator 이름 하나를 실제로 돌려 글 텍스트만 돌려준다."""
    if generator_name == "prevention_notice":
        _, draft = _run_notice(ctx, key, model)
        return draft.text if draft else None
    if generator_name == "reply_draft":
        _, draft = _run_reply(ctx, key, model)
        return draft.text if draft else None
    if generator_name == "coupon_promo":
        _, draft = _run_coupon(ctx, strategy, key, model)
        return draft.text if draft else None
    if generator_name == "review_promo":
        _, draft = _run_review_promo(ctx, strategy, key, model)
        return draft.text if draft else None
    if generator_name == "late_notice_template":
        # H_LATE 는 아직 AI 생성기가 없다 — 항상(키 유무와 상관없이) 코드 템플릿을 그대로 쓴다
        return LATE_NOTICE_TEMPLATE
    return None


def build_plan(ctx, strategy, answers, key, model="HCX-005", today=None):
    """playbooks.build_playbook() 의 할 일마다 generator 를 실행해 글(drafts)과 쿠폰 카드를 채운다.

    출력 형식: {title, total_minutes, steps, drafts: {step_id: 글}, coupon_card, measure, strategy_type}.
    """
    plan = playbooks.build_playbook(ctx, strategy, answers, today=today)

    drafts: dict[str, str] = {}
    for step in plan["steps"]:
        generator_name = step.get("generator")
        if not generator_name:
            continue
        try:
            text = run_step_generator(ctx, strategy, generator_name, key, model=model)
        except MissingCard as exc:
            # 카드가 없어 이 글만 못 만듦 (직접 등록한 가게, 11/20). 할 일·쿠폰 계산은 그대로 보여 주고 이유를 싣는다
            plan.setdefault("unavailable_drafts", []).append({"step_id": step["step_id"], "message": exc.message})
            continue
        if text and step["step_id"] == "baemin_intro":
            menu = strategy.menu or playbooks.default_menu(ctx.store)
            text = _baemin_intro_line(text, menu, step.get("max_chars") or BAEMIN_INTRO_LIMIT)
        if text:
            drafts[step["step_id"]] = text

    coupon_card = None
    if strategy.discount_won:
        price_won = ctx.store.menu_prices.get(strategy.menu, 0)
        figures = _coupon_calc(
            answers.budget_won, strategy.discount_won, price_won, answers.avg_order_won, answers.margin_pct,
        )
        coupon_card = {
            "menu": strategy.menu, "discount_won": strategy.discount_won, "count": strategy.count,
            "timing": strategy.timing, "days": COUPON_DAYS,
            "breakeven_orders": figures["breakeven_orders"],
            "calc_input": {
                "budget_won": answers.budget_won, "discount_won": strategy.discount_won,
                "price_won": price_won, "avg_order_won": answers.avg_order_won,
                "margin_pct": answers.margin_pct,
            },
        }

    plan["drafts"] = drafts
    plan["coupon_card"] = coupon_card
    plan["strategy_type"] = strategy.type  # 화면이 카드 아이콘을 고르는 용도(사실 자체는 그대로 strategy 가 정함)
    plan["basic_todos"] = _basic_todo_drafts(ctx, answers, key, model)
    plan["idea"] = None
    plan["idea_index"] = 0
    idea, idx = _ideas.idea_at(answers.goal, ctx, answers, 0)
    if idea is not None:
        plan["idea_index"] = idx
        plan["idea"] = _idea_entry(idea, ctx, answers)
    return plan


def _idea_entry(idea, ctx, answers):
    """plan["idea"] 1개 모양 — needs_question 이면 글은 비워 두고(질문에 답한 뒤에만 만든다),
    아니면 바로 try_idea() 로 채운다."""
    entry = {
        "id": idea["id"], "title": idea["title"], "why": idea["why"], "todos": list(idea["todos"]),
        "needs_question": bool(idea.get("needs_question")),
        "question": idea.get("question"), "question_type": idea.get("question_type"),
        "draft": None,
    }
    if not entry["needs_question"]:
        entry["draft"] = _ideas.try_idea(idea, ctx, answers)["draft"]
    return entry


def _run_coupon(ctx, strategy, key, model):
    promo_card = _card_by_kind(ctx, "promo")
    if key is None:
        result = run_card(ctx, promo_card, None)
    else:
        # "상권 하락 시간대 우선"은 구체적인 시간대가 아니라, c6 쪽이 상권 지표(snapshot)에서
        # 정확한 시간대("저녁 5~9시 주문 시" 등)를 자동으로 뽑으라는 뜻이라 None(자동)으로 둔다.
        # "한가한 시간대"만 명시적으로 덮어쓴다 — 수용력이 빠듯할 때 상권 신호보다 우선하기 위해서다.
        time_window = BUSY_TIMING if strategy.timing == BUSY_TIMING else None
        result = generate_coupon_promo(
            ctx, promo_card, key, model=model,
            coupon_menu=strategy.menu or None,
            coupon_discount=strategy.discount_won or 1000,
            coupon_days=COUPON_DAYS,
            time_window=time_window,
        )
    draft = next((d for d in result.drafts if d.generator == "coupon_promo"), None)
    return result, draft


def execute_strategy(ctx, strategy, key, model="HCX-005"):
    """전략 1개 실행. (CardResult|None, DraftOutput|None, 사장님 할 일 문구|None) 를 돌려준다."""
    if strategy.type == "fix_first" and strategy.source_hypothesis == "H_REPEAT":
        result, draft = _run_notice(ctx, key, model)
        return result, draft, None
    if strategy.type in _COUPON_GENERATOR_TYPES:
        result, draft = _run_coupon(ctx, strategy, key, model)
        return result, draft, None
    if strategy.type == "review_promo":
        result, draft = _run_review_promo(ctx, strategy, key, model)
        return result, draft, None
    # 사유(strategy.reason)는 explain_strategy() 의 "왜" 줄에 이미 나오므로 여기서는 반복하지 않는다
    return None, None, f"사장님 확인 필요 — {strategy.title}"


def execute_plan(ctx, plan, key, model="HCX-005"):
    """plan.strategies 를 순서대로 실행. [(strategy, CardResult|None, DraftOutput|None, 할 일|None), ...]."""
    out = []
    for strategy in plan.strategies:
        result, draft, todo = execute_strategy(ctx, strategy, key, model=model)
        out.append((strategy, result, draft, todo))
    return out
