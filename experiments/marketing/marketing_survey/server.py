"""설문 맞춤 마케팅 — FastAPI 서버 (127.0.0.1:8030). 프레임워크 없는 web/ 정적 페이지를 돌려준다.

상태는 서버에 저장하지 않는다 — 클라이언트가 {node, raw, confirms, mode} 를 들고 다니며 매 요청마다
그대로 보낸다(세션/DB 없음). CLOVA_API_KEY 가 없으면 c6 저장본(c6/replay)으로 동작하고
/generate 응답에 demo:true 를 남긴다.

실행: python -m uvicorn marketing_survey.server:app --port 8030 --host 127.0.0.1
"""

import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from c6.checks import personal_info, promises_not_in_policy
from marketing_survey import (
    adspend, coupon_result, flow, ideas, leftover, notice_followup, playbooks, records, report, story, stores,
)
from marketing_survey.coupon_calc import calc as coupon_calc
from marketing_survey.decide import build_follow_up_strategy, decide
from marketing_survey.execute import COUPON_DAYS, _card_by_kind, _idea_entry, build_plan, execute_strategy
from marketing_survey.explain import explain_strategy
from marketing_survey.models import Strategy
from marketing_survey.survey import answers_from_raw

_SURVEY_MODES = ("survey", "follow_up")

WEB_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(title="설문 맞춤 마케팅")
if WEB_DIR.is_dir():
    app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")


class FlowState(BaseModel):
    node: str = flow.START
    raw: dict = Field(default_factory=dict)
    confirms: dict = Field(default_factory=dict)
    mode: str = "survey"


class StepRequest(BaseModel):
    state: FlowState | None = None
    answer: str | list[str] | None = None


class StateOnlyRequest(BaseModel):
    state: FlowState
    coupon_override: dict | None = None


class ApproveRequest(BaseModel):
    state: FlowState
    draft_id: str | None = None
    session_id: str | None = None  # /plan 이 돌려준 기록 id — 승인 기록의 parent_id 가 된다
    edited_texts: dict[str, str] = Field(default_factory=dict)


class NextIdeaRequest(BaseModel):
    state: FlowState
    current_index: int = 0


class IdeaTryRequest(BaseModel):
    state: FlowState
    idea_id: str
    index: int = 0
    answer: str | None = None


class CouponCalcRequest(BaseModel):
    budget_won: int
    discount_won: int
    price_won: int
    avg_order_won: int
    margin_pct: int


def _get_ctx(store: str):
    """?store=store_id 로 고른 가게의 Context. 데이터가 없는 가게면 404(화면에서는 고를 수 없다)."""
    ctx = stores.get_ctx(store)
    if ctx is None:
        raise HTTPException(404, f"'{store}'는 데모 데이터가 없는 가게예요.")
    return ctx


def _options_payload(node_id: str, state: FlowState, ctx) -> list[dict]:
    opts = flow.node_options(node_id, ctx, {"raw": state.raw, "confirms": state.confirms})
    if flow.NODES[node_id].get("multi"):
        return [{"label": o["label"], "value": o["value"]} for o in opts]
    return [{"label": o["label"]} for o in opts]


def _input_payload(node_id: str) -> dict | None:
    """free_input 노드면 {key, type} 를 돌려준다 — 클라이언트가 버튼 대신 입력칸을 보이게 한다."""
    return flow.NODES[node_id].get("free_input")


def _resolve_strategy_and_answers(state: FlowState, ctx):
    answers = answers_from_raw(state.raw)
    if state.mode == "follow_up":
        strategy, note = build_follow_up_strategy(ctx, answers)
        if strategy is None:
            raise HTTPException(400, note or "재주문 쿠폰을 만들 수 없어요.")
        return strategy, answers
    plan = decide(ctx, answers, confirms=state.confirms)
    return plan.strategies[0], answers


def _check_edited_text(text: str, ctx) -> list[str]:
    """고친 글(edited_text) 점검 — 개인정보·정책에 없는 보상 약속만 다시 돈다(그 외 점검은 생성 때 이미 끝났음)."""
    reasons = []
    if personal_info(text):
        reasons.append("개인정보로 보일 수 있는 내용이 있어요")
    if promises_not_in_policy(text, ctx.policies):
        reasons.append("가게 정책에 없는 보상 약속이 있어요")
    return reasons


def _resolve_strategy(state: FlowState, ctx):
    strategy, _ = _resolve_strategy_and_answers(state, ctx)
    return strategy


# playbook 글 생성기 이름 -> 보고서에 세는 글 종류
_GENERATOR_KINDS = {
    "prevention_notice": "공지", "late_notice_template": "공지", "reply_draft": "답글",
    "review_promo": "홍보 글", "coupon_promo": "쿠폰 글",
}


def _record(write, *args, **kwargs) -> dict | None:
    """기록은 보조 기능 — 쓰기에 실패해도(디스크 등) 화면 흐름은 그대로 간다."""
    try:
        return write(*args, **kwargs)
    except (OSError, ValueError):
        return None


def _plan_kinds(steps: list[dict]) -> list[str]:
    kinds: list[str] = []
    for s in steps:
        kind = _GENERATOR_KINDS.get(s.get("generator") or "")
        if kind and kind not in kinds:
            kinds.append(kind)
    return kinds


def _record_plan(store: str, state: FlowState, result: dict, answers_goal: str | None) -> str | None:
    """/plan 결과 기록. 쿠폰 결과는 coupon_runs, 나머지는 marketing_sessions. 기록 id(없으면 None)."""
    if state.mode == "coupon_result":
        if result.get("issued"):
            row = _record(
                records.append_coupon_run, store, menu_name=None, discount_krw=result["discount_won"],
                issued=result["issued"], used=result["used"], avg_order_krw=result["avg_order_won"],
                margin_pct=result["margin_pct"],
            )
            return row["id"] if row else None
        return None
    if state.mode == "adspend":
        summary = {"table": [
            {k: r[k] for k in ("channel", "label", "spend_won", "orders", "cost_per_order_won",
                               "profit_per_order_won", "verdict")} for r in result["table"]
        ], "profit_per_order_won": result["profit_per_order_won"]}
        row = _record(records.append_session, store, "adspend", answers=state.raw, decision="checked", result=summary)
        return row["id"] if row else None
    row = _record(
        records.append_session, store, state.mode, goal=answers_goal, answers=state.raw, decision="proposed",
        result={"title": result.get("title"), "kinds": _plan_kinds(result.get("steps") or [])},
    )
    return row["id"] if row else None


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/marketing-survey/meta")
def meta(store: str = stores.DEFAULT_STORE_ID):
    ctx = _get_ctx(store)
    return {"store_name": ctx.store.name, "store_id": ctx.store.store_id, "stores": stores.list_stores()}


@app.get("/api/marketing-survey/stores")
def stores_endpoint():
    return {"stores": stores.list_stores()}


@app.post("/api/marketing-survey/step")
def step(req: StepRequest, store: str = stores.DEFAULT_STORE_ID):
    """질문 1개 진행. answer 가 없으면(state 도 없으면 새 설문 시작) 지금 노드 질문만 돌려준다.

    answer 가 있으면 flow.advance() 로 "다음 노드"를 직접 계산해 state.node 에 그대로 넣는다 —
    예전 버전처럼 노드가 안 바뀐 채로 같은 질문이 다시 나오는 일이 없다(모든 진행은 여기 한 곳에서만
    일어나고, 다음 노드가 그래프에 없으면 조용히 멈추는 대신 바로 에러가 난다).
    """
    ctx = _get_ctx(store)
    state = req.state or FlowState()
    scratch = {"raw": dict(state.raw), "confirms": dict(state.confirms)}
    mode = state.mode

    if req.answer is None:
        node_id = state.node
    else:
        node = flow.NODES.get(state.node)
        if node is None:
            raise HTTPException(400, f"알 수 없는 노드: {state.node}")
        if node.get("multi"):
            if not isinstance(req.answer, list):
                raise HTTPException(400, "이 질문은 여러 개를 배열로 골라야 해요.")
            flow.apply_multi(scratch, state.node, req.answer)
            node_id = flow.multi_next_node(state.node, scratch["raw"])
        else:
            if not isinstance(req.answer, str):
                raise HTTPException(400, "이 질문은 보기 중 하나(문자열)를 골라야 해요.")
            if state.node == flow.START:
                mode = flow.START_MODES.get(req.answer, mode)
            try:
                node_id = flow.advance(state.node, ctx, scratch, req.answer)
            except flow.FlowError as exc:
                raise HTTPException(400, str(exc)) from exc

    new_state = FlowState(node=node_id, raw=scratch["raw"], confirms=scratch["confirms"], mode=mode)

    if node_id == flow.DECISION:
        return {"state": new_state, "bot_messages": [], "options": [], "multi": False, "done": True}

    text = flow.node_text(node_id, ctx, scratch)
    return {
        "state": new_state,
        "bot_messages": [text],
        "options": _options_payload(node_id, new_state, ctx),
        "multi": bool(flow.NODES[node_id].get("multi")),
        "input": _input_payload(node_id),
        "example": flow.node_example(node_id),
        "done": False,
    }


@app.post("/api/marketing-survey/result")
def result(req: StateOnlyRequest, store: str = stores.DEFAULT_STORE_ID):
    """결정(decide 또는 follow_up) + explain 3줄 + 근거. [맞춤 홍보 제안] 경로에서만 쓰인다."""
    ctx = _get_ctx(store)
    if req.state.mode not in _SURVEY_MODES:
        raise HTTPException(400, "이 기능은 결과를 /plan 으로 바로 받아요.")
    strategy = _resolve_strategy(req.state, ctx)
    return {"strategy": strategy.to_dict(), "explain": explain_strategy(strategy)}


def _coupon_result_next_strategy(raw: dict, ctx) -> Strategy:
    """쿠폰 결과 확인의 "다음 쿠폰 조건" 카드 -> coupon_promo 로 넘길 임시 Strategy.
    할인액은 코드(coupon_result.next_coupon_condition)가 정한 값만 쓰고, 메뉴는 대표 메뉴를 쓴다."""
    out = coupon_result.build_coupon_result_plan(raw)
    condition = out.get("next_condition")
    if not condition:
        raise HTTPException(400, "사용률을 계산할 수 없어 다음 쿠폰 조건을 만들 수 없어요.")
    return Strategy(
        type="reorder_coupon", title="다음 쿠폰", reason="쿠폰 결과 기준",
        discount_won=condition["discount_won"], menu=playbooks.default_menu(ctx.store) or "",
    )


@app.post("/api/marketing-survey/generate")
def generate(req: StateOnlyRequest, store: str = stores.DEFAULT_STORE_ID):
    """execute 로 C6 글을 만든다. 키가 없으면 c6 저장본을 쓰고 demo:true 를 남긴다."""
    ctx = _get_ctx(store)
    key = os.environ.get("CLOVA_API_KEY")
    if req.state.mode == "coupon_result":
        strategy = _coupon_result_next_strategy(req.state.raw, ctx)
        _, draft, todo = execute_strategy(ctx, strategy, key)
        coupon = {
            "menu": strategy.menu, "discount_won": strategy.discount_won,
            "timing": strategy.timing, "days": COUPON_DAYS,
        }
        return {
            "draft_id": uuid.uuid4().hex, "text": draft.text if draft else None,
            "todo": todo, "demo": key is None, "coupon": coupon,
        }
    if req.state.mode not in _SURVEY_MODES:
        raise HTTPException(400, "이 기능은 글을 /plan 으로 바로 받아요.")
    strategy, answers = _resolve_strategy_and_answers(req.state, ctx)
    if req.coupon_override and strategy.discount_won:
        price_won = ctx.store.menu_prices.get(strategy.menu, 0)
        figures = coupon_calc(
            int(req.coupon_override.get("budget_won") or 0),
            int(req.coupon_override.get("discount_won") or 0),
            price_won, answers.avg_order_won, answers.margin_pct,
        )
        strategy.discount_won = int(req.coupon_override.get("discount_won") or 0)
        strategy.count = figures["count"]
        strategy.budget_won = figures["max_cost_won"]
    _, draft, todo = execute_strategy(ctx, strategy, key)

    coupon = None
    if strategy.discount_won:
        coupon = {
            "menu": strategy.menu, "discount_won": strategy.discount_won,
            "timing": strategy.timing, "days": COUPON_DAYS,
        }

    return {
        "draft_id": uuid.uuid4().hex,
        "text": draft.text if draft else None,
        "todo": todo,
        "demo": key is None,
        "coupon": coupon,
    }


@app.post("/api/marketing-survey/plan")
def plan(req: StateOnlyRequest, store: str = stores.DEFAULT_STORE_ID):
    """실행 계획: {title, total_minutes, steps, drafts, measure, ...}. mode 로 기능을 가른다."""
    ctx = _get_ctx(store)
    state = req.state
    key = os.environ.get("CLOVA_API_KEY")
    goal = None

    if state.mode == "leftover":
        result = leftover.build_leftover_plan(ctx, state.raw, key)
    elif state.mode == "adspend":
        result = adspend.build_adspend_table(ctx, state.raw)
    elif state.mode == "story":
        result = story.build_story_plan(state.raw)
    elif state.mode == "coupon_result":
        result = coupon_result.build_coupon_result_plan(state.raw)
    else:
        strategy, answers = _resolve_strategy_and_answers(state, ctx)
        result = build_plan(ctx, strategy, answers, key)
        goal = answers.goal

    result["demo"] = key is None
    result["session_id"] = _record_plan(store, state, result, goal)
    return result


@app.post("/api/marketing-survey/next-idea")
def next_idea(req: NextIdeaRequest, store: str = stores.DEFAULT_STORE_ID):
    """[다른 아이디어 보기] — 같은 목표의 다음 아이디어로 순서대로 넘어간다(무작위 아님)."""
    ctx = _get_ctx(store)
    if req.state.mode not in _SURVEY_MODES:
        raise HTTPException(400, "이 기능은 설문 결과에서만 써요.")
    _, answers = _resolve_strategy_and_answers(req.state, ctx)
    idea, idx = ideas.idea_at(answers.goal, ctx, answers, req.current_index + 1)
    if idea is None:
        return {"idea": None, "idea_index": req.current_index}
    return {"idea": _idea_entry(idea, ctx, answers), "idea_index": idx}


@app.post("/api/marketing-survey/idea-try")
def idea_try(req: IdeaTryRequest, store: str = stores.DEFAULT_STORE_ID):
    """질문이 필요한 아이디어(custom_option·weekly_side·neighbor_cross) — [이 아이디어 해 보기]를
    누르면(answer 없이) 질문만 먼저 돌려주고, 답을 받으면 글을 만든다(불가능하면 skip=True)."""
    ctx = _get_ctx(store)
    if req.state.mode not in _SURVEY_MODES:
        raise HTTPException(400, "이 기능은 설문 결과에서만 써요.")
    _, answers = _resolve_strategy_and_answers(req.state, ctx)
    candidates = ideas.ideas_for(answers.goal, ctx, answers)
    idea = next((i for i in candidates if i["id"] == req.idea_id), None)
    if idea is None:
        raise HTTPException(400, "아이디어를 찾을 수 없어요.")

    if idea.get("needs_question") and req.answer is None:
        return {"need_answer": True, "question": idea.get("question"), "question_type": idea.get("question_type")}

    result = ideas.try_idea(idea, ctx, answers, req.answer)
    if not result["skip"]:
        _record(records.append_session, store, "idea", goal=answers.goal, decision="tried",
                result={"idea_id": idea["id"], "title": idea.get("title")})
    return {"need_answer": False, "draft": result["draft"], "skip": result["skip"]}


@app.post("/api/marketing-survey/coupon-calc")
def coupon_calc_endpoint(req: CouponCalcRequest):
    """쿠폰 슬라이더(예산·할인액) 가 움직일 때마다 부른다 — 계산은 전부 coupon_calc.calc()(가게 무관)."""
    return coupon_calc(
        req.budget_won, req.discount_won, req.price_won, req.avg_order_won, req.margin_pct,
    )


@app.post("/api/marketing-survey/approve")
def approve(req: ApproveRequest, store: str = stores.DEFAULT_STORE_ID):
    """승인 처리. H_REPEAT 의 fix_first 를 승인했을 때만 재주문 쿠폰 질문(예산부터)으로 이어진다."""
    ctx = _get_ctx(store)
    state = req.state
    edit_failed = {
        key: reasons
        for key, text in req.edited_texts.items()
        if (reasons := _check_edited_text(text, ctx))
    }
    if edit_failed:
        return {"follow_up": False, "state": state, "edit_failed": edit_failed}

    if state.mode not in _SURVEY_MODES:
        return {"follow_up": False, "state": state}
    strategy, answers = _resolve_strategy_and_answers(state, ctx)
    steps = playbooks.build_playbook(ctx, strategy, answers)["steps"]
    _record(records.append_session, store, state.mode, goal=answers.goal, answers=state.raw,
            decision="approved", result={"kinds": _plan_kinds(steps)}, parent_id=req.session_id)

    if state.mode == "survey" and strategy.source_hypothesis == "H_REPEAT":
        next_state = FlowState(
            node=flow.FOLLOW_UP_START, raw=dict(state.raw), confirms=dict(state.confirms), mode="follow_up",
        )
        scratch = {"raw": next_state.raw, "confirms": next_state.confirms}
        text = flow.node_text(flow.FOLLOW_UP_START, ctx, scratch)
        return {
            "follow_up": True,
            "state": next_state,
            "bot_messages": ["공지 뒤에 재주문 쿠폰도 해 볼까요? 이어서 몇 가지만 더 여쭤볼게요.", text],
            "options": _options_payload(flow.FOLLOW_UP_START, next_state, ctx),
            "multi": False,
        }

    return {"follow_up": False, "state": state}


@app.post("/api/marketing-survey/notice-followup")
def notice_followup_endpoint(req: StateOnlyRequest, store: str = stores.DEFAULT_STORE_ID):
    """개선 인증 소식(데모) — H_REPEAT 공지(불만 카드) 기준일 앞뒤 14일의 같은 불만 리뷰 수를
    코드로 센다. 줄었으면 코드 템플릿 소식 글을, 아니면 '원인 다시 보기' 안내만 돌려준다."""
    ctx = _get_ctx(store)
    notice_card = _card_by_kind(ctx, "complaint")
    return notice_followup.build_notice_followup(ctx, notice_card)


@app.get("/api/marketing-survey/report")
def report_endpoint(period: str = "monthly", store: str = stores.DEFAULT_STORE_ID):
    """마케팅 보고서 — 기록에서 이번 주/이번 달을 센다(기록이 없으면 데모 기록, demo:true)."""
    _get_ctx(store)
    if period not in report.PERIOD_KINDS:
        raise HTTPException(400, "period 는 weekly 또는 monthly 여야 해요.")
    return report.marketing_section(store, period)
