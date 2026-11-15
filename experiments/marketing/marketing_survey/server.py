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
from c6.contract import build_context
from c6.dummy import OWNER_REPLIES, POLICIES
from common.korean import display_name
from marketing_survey import adspend, coupon_result, flow, ideas, leftover, notice_followup, playbooks, story
from marketing_survey.coupon_calc import calc as coupon_calc
from marketing_survey.decide import build_follow_up_strategy, decide
from marketing_survey.execute import COUPON_DAYS, NOTICE_CARD, _idea_entry, build_plan, execute_strategy
from marketing_survey.explain import explain_strategy
from marketing_survey.models import Strategy
from marketing_survey.survey import answers_from_raw
from shared.sample_scenario import (
    SAMPLE_CARDS, SAMPLE_REVIEWS, SAMPLE_SNAPSHOTS, SAMPLE_STORE, SAMPLE_TONE,
)

_SURVEY_MODES = ("survey", "follow_up")

WEB_DIR = Path(__file__).resolve().parent / "web"

CTX = build_context(
    store=SAMPLE_STORE, reviews=list(SAMPLE_REVIEWS), tone=SAMPLE_TONE,
    cards=list(SAMPLE_CARDS), snapshots=list(SAMPLE_SNAPSHOTS),
    owner_replies=OWNER_REPLIES, policies=POLICIES,
)
STORE_DISPLAY = display_name(SAMPLE_STORE.name)

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


def _options_payload(node_id: str, state: FlowState) -> list[dict]:
    opts = flow.node_options(node_id, CTX, {"raw": state.raw, "confirms": state.confirms})
    if flow.NODES[node_id].get("multi"):
        return [{"label": o["label"], "value": o["value"]} for o in opts]
    return [{"label": o["label"]} for o in opts]


def _input_payload(node_id: str) -> dict | None:
    """free_input 노드면 {key, type} 를 돌려준다 — 클라이언트가 버튼 대신 입력칸을 보이게 한다."""
    return flow.NODES[node_id].get("free_input")


def _resolve_strategy_and_answers(state: FlowState):
    answers = answers_from_raw(state.raw)
    if state.mode == "follow_up":
        strategy, note = build_follow_up_strategy(CTX, answers)
        if strategy is None:
            raise HTTPException(400, note or "재주문 쿠폰을 만들 수 없어요.")
        return strategy, answers
    plan = decide(CTX, answers, confirms=state.confirms)
    return plan.strategies[0], answers


def _check_edited_text(text: str) -> list[str]:
    """고친 글(edited_text) 점검 — 개인정보·정책에 없는 보상 약속만 다시 돈다(그 외 점검은 생성 때 이미 끝났음)."""
    reasons = []
    if personal_info(text):
        reasons.append("개인정보로 보일 수 있는 내용이 있어요")
    if promises_not_in_policy(text, POLICIES):
        reasons.append("가게 정책에 없는 보상 약속이 있어요")
    return reasons


def _resolve_strategy(state: FlowState):
    strategy, _ = _resolve_strategy_and_answers(state)
    return strategy


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/marketing-survey/meta")
def meta():
    return {"store_name": STORE_DISPLAY}


@app.post("/api/marketing-survey/step")
def step(req: StepRequest):
    """질문 1개 진행. answer 가 없으면(state 도 없으면 새 설문 시작) 지금 노드 질문만 돌려준다.

    answer 가 있으면 flow.advance() 로 "다음 노드"를 직접 계산해 state.node 에 그대로 넣는다 —
    예전 버전처럼 노드가 안 바뀐 채로 같은 질문이 다시 나오는 일이 없다(모든 진행은 여기 한 곳에서만
    일어나고, 다음 노드가 그래프에 없으면 조용히 멈추는 대신 바로 에러가 난다).
    """
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
                node_id = flow.advance(state.node, CTX, scratch, req.answer)
            except flow.FlowError as exc:
                raise HTTPException(400, str(exc)) from exc

    new_state = FlowState(node=node_id, raw=scratch["raw"], confirms=scratch["confirms"], mode=mode)

    if node_id == flow.DECISION:
        return {"state": new_state, "bot_messages": [], "options": [], "multi": False, "done": True}

    text = flow.node_text(node_id, CTX, scratch)
    return {
        "state": new_state,
        "bot_messages": [text],
        "options": _options_payload(node_id, new_state),
        "multi": bool(flow.NODES[node_id].get("multi")),
        "input": _input_payload(node_id),
        "example": flow.node_example(node_id),
        "done": False,
    }


@app.post("/api/marketing-survey/result")
def result(req: StateOnlyRequest):
    """결정(decide 또는 follow_up) + explain 3줄 + 근거. [맞춤 홍보 제안] 경로에서만 쓰인다."""
    if req.state.mode not in _SURVEY_MODES:
        raise HTTPException(400, "이 기능은 결과를 /plan 으로 바로 받아요.")
    strategy = _resolve_strategy(req.state)
    return {"strategy": strategy.to_dict(), "explain": explain_strategy(strategy)}


def _coupon_result_next_strategy(raw: dict) -> Strategy:
    """쿠폰 결과 확인의 "다음 쿠폰 조건" 카드 -> coupon_promo 로 넘길 임시 Strategy.
    할인액은 코드(coupon_result.next_coupon_condition)가 정한 값만 쓰고, 메뉴는 대표 메뉴를 쓴다."""
    out = coupon_result.build_coupon_result_plan(raw)
    condition = out.get("next_condition")
    if not condition:
        raise HTTPException(400, "사용률을 계산할 수 없어 다음 쿠폰 조건을 만들 수 없어요.")
    return Strategy(
        type="reorder_coupon", title="다음 쿠폰", reason="쿠폰 결과 기준",
        discount_won=condition["discount_won"], menu=playbooks.default_menu(CTX.store) or "",
    )


@app.post("/api/marketing-survey/generate")
def generate(req: StateOnlyRequest):
    """execute 로 C6 글을 만든다. 키가 없으면 c6 저장본을 쓰고 demo:true 를 남긴다."""
    key = os.environ.get("CLOVA_API_KEY")
    if req.state.mode == "coupon_result":
        strategy = _coupon_result_next_strategy(req.state.raw)
        _, draft, todo = execute_strategy(CTX, strategy, key)
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
    strategy, answers = _resolve_strategy_and_answers(req.state)
    if req.coupon_override and strategy.discount_won:
        price_won = CTX.store.menu_prices.get(strategy.menu, 0)
        figures = coupon_calc(
            int(req.coupon_override.get("budget_won") or 0),
            int(req.coupon_override.get("discount_won") or 0),
            price_won, answers.avg_order_won, answers.margin_pct,
        )
        strategy.discount_won = int(req.coupon_override.get("discount_won") or 0)
        strategy.count = figures["count"]
        strategy.budget_won = figures["max_cost_won"]
    _, draft, todo = execute_strategy(CTX, strategy, key)

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
def plan(req: StateOnlyRequest):
    """실행 계획: {title, total_minutes, steps, drafts, measure, ...}. mode 로 기능을 가른다."""
    state = req.state
    key = os.environ.get("CLOVA_API_KEY")

    if state.mode == "leftover":
        result = leftover.build_leftover_plan(CTX, state.raw, key)
    elif state.mode == "adspend":
        result = adspend.build_adspend_table(CTX, state.raw)
    elif state.mode == "story":
        result = story.build_story_plan(state.raw)
    elif state.mode == "coupon_result":
        result = coupon_result.build_coupon_result_plan(state.raw)
    else:
        strategy, answers = _resolve_strategy_and_answers(state)
        result = build_plan(CTX, strategy, answers, key)

    result["demo"] = key is None
    return result


@app.post("/api/marketing-survey/next-idea")
def next_idea(req: NextIdeaRequest):
    """[다른 아이디어 보기] — 같은 목표의 다음 아이디어로 순서대로 넘어간다(무작위 아님)."""
    if req.state.mode not in _SURVEY_MODES:
        raise HTTPException(400, "이 기능은 설문 결과에서만 써요.")
    _, answers = _resolve_strategy_and_answers(req.state)
    idea, idx = ideas.idea_at(answers.goal, CTX, answers, req.current_index + 1)
    if idea is None:
        return {"idea": None, "idea_index": req.current_index}
    return {"idea": _idea_entry(idea, CTX, answers), "idea_index": idx}


@app.post("/api/marketing-survey/idea-try")
def idea_try(req: IdeaTryRequest):
    """질문이 필요한 아이디어(custom_option·weekly_side·neighbor_cross) — [이 아이디어 해 보기]를
    누르면(answer 없이) 질문만 먼저 돌려주고, 답을 받으면 글을 만든다(불가능하면 skip=True)."""
    if req.state.mode not in _SURVEY_MODES:
        raise HTTPException(400, "이 기능은 설문 결과에서만 써요.")
    _, answers = _resolve_strategy_and_answers(req.state)
    candidates = ideas.ideas_for(answers.goal, CTX, answers)
    idea = next((i for i in candidates if i["id"] == req.idea_id), None)
    if idea is None:
        raise HTTPException(400, "아이디어를 찾을 수 없어요.")

    if idea.get("needs_question") and req.answer is None:
        return {"need_answer": True, "question": idea.get("question"), "question_type": idea.get("question_type")}

    result = ideas.try_idea(idea, CTX, answers, req.answer)
    return {"need_answer": False, "draft": result["draft"], "skip": result["skip"]}


@app.post("/api/marketing-survey/coupon-calc")
def coupon_calc_endpoint(req: CouponCalcRequest):
    """쿠폰 슬라이더(예산·할인액) 가 움직일 때마다 부른다 — 계산은 전부 coupon_calc.calc()."""
    return coupon_calc(
        req.budget_won, req.discount_won, req.price_won, req.avg_order_won, req.margin_pct,
    )


@app.post("/api/marketing-survey/approve")
def approve(req: ApproveRequest):
    """승인 처리. H_REPEAT 의 fix_first 를 승인했을 때만 재주문 쿠폰 질문(예산부터)으로 이어진다."""
    state = req.state
    edit_failed = {
        key: reasons
        for key, text in req.edited_texts.items()
        if (reasons := _check_edited_text(text))
    }
    if edit_failed:
        return {"follow_up": False, "state": state, "edit_failed": edit_failed}

    if state.mode not in _SURVEY_MODES:
        return {"follow_up": False, "state": state}
    strategy = _resolve_strategy(state)

    if state.mode == "survey" and strategy.source_hypothesis == "H_REPEAT":
        next_state = FlowState(
            node=flow.FOLLOW_UP_START, raw=dict(state.raw), confirms=dict(state.confirms), mode="follow_up",
        )
        scratch = {"raw": next_state.raw, "confirms": next_state.confirms}
        text = flow.node_text(flow.FOLLOW_UP_START, CTX, scratch)
        return {
            "follow_up": True,
            "state": next_state,
            "bot_messages": ["공지 뒤에 재주문 쿠폰도 해 볼까요? 이어서 몇 가지만 더 여쭤볼게요.", text],
            "options": _options_payload(flow.FOLLOW_UP_START, next_state),
            "multi": False,
        }

    return {"follow_up": False, "state": state}


@app.post("/api/marketing-survey/notice-followup")
def notice_followup_endpoint(req: StateOnlyRequest):
    """개선 인증 소식(데모) — H_REPEAT 공지(card_sample_a) 기준일 앞뒤 14일의 같은 불만 리뷰 수를
    코드로 센다. 줄었으면 코드 템플릿 소식 글을, 아니면 '원인 다시 보기' 안내만 돌려준다."""
    return notice_followup.build_notice_followup(CTX, NOTICE_CARD)
