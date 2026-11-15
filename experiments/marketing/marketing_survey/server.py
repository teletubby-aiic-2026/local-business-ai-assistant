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

from c6.contract import build_context
from c6.dummy import OWNER_REPLIES, POLICIES
from common.korean import display_name
from marketing_survey import flow
from marketing_survey.decide import build_follow_up_strategy, decide
from marketing_survey.execute import COUPON_DAYS, build_plan, execute_strategy
from marketing_survey.explain import explain_strategy
from marketing_survey.survey import answers_from_raw
from shared.sample_scenario import (
    SAMPLE_CARDS, SAMPLE_REVIEWS, SAMPLE_SNAPSHOTS, SAMPLE_STORE, SAMPLE_TONE,
)

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
    node: str = "repeat_complaint"
    raw: dict = Field(default_factory=dict)
    confirms: dict = Field(default_factory=dict)
    mode: str = "survey"


class StepRequest(BaseModel):
    state: FlowState | None = None
    answer: str | list[str] | None = None


class StateOnlyRequest(BaseModel):
    state: FlowState


class ApproveRequest(BaseModel):
    state: FlowState
    draft_id: str | None = None


def _options_payload(node_id: str, state: FlowState) -> list[dict]:
    opts = flow.node_options(node_id, CTX, {"raw": state.raw, "confirms": state.confirms})
    if flow.NODES[node_id].get("multi"):
        return [{"label": o["label"], "value": o["value"]} for o in opts]
    return [{"label": o["label"]} for o in opts]


def _resolve_strategy_and_answers(state: FlowState):
    answers = answers_from_raw(state.raw)
    if state.mode == "follow_up":
        strategy, note = build_follow_up_strategy(CTX, answers)
        if strategy is None:
            raise HTTPException(400, note or "재주문 쿠폰을 만들 수 없어요.")
        return strategy, answers
    plan = decide(CTX, answers, confirms=state.confirms)
    return plan.strategies[0], answers


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

    if req.answer is None:
        node_id = state.node
    else:
        node = flow.NODES.get(state.node)
        if node is None:
            raise HTTPException(400, f"알 수 없는 노드: {state.node}")
        if node.get("multi"):
            if not isinstance(req.answer, list):
                raise HTTPException(400, "이 질문은 여러 개를 배열로 골라야 해요.")
            flow.apply_channels(scratch, req.answer)
            node_id = flow.DECISION
        else:
            if not isinstance(req.answer, str):
                raise HTTPException(400, "이 질문은 보기 중 하나(문자열)를 골라야 해요.")
            try:
                node_id = flow.advance(state.node, CTX, scratch, req.answer)
            except flow.FlowError as exc:
                raise HTTPException(400, str(exc)) from exc

    new_state = FlowState(node=node_id, raw=scratch["raw"], confirms=scratch["confirms"], mode=state.mode)

    if node_id == flow.DECISION:
        return {"state": new_state, "bot_messages": [], "options": [], "multi": False, "done": True}

    text = flow.node_text(node_id, CTX, scratch)
    return {
        "state": new_state,
        "bot_messages": [text],
        "options": _options_payload(node_id, new_state),
        "multi": bool(flow.NODES[node_id].get("multi")),
        "done": False,
    }


@app.post("/api/marketing-survey/result")
def result(req: StateOnlyRequest):
    """결정(decide 또는 follow_up) + explain 3줄 + 근거."""
    strategy = _resolve_strategy(req.state)
    return {"strategy": strategy.to_dict(), "explain": explain_strategy(strategy)}


@app.post("/api/marketing-survey/generate")
def generate(req: StateOnlyRequest):
    """execute 로 C6 글을 만든다. 키가 없으면 c6 저장본을 쓰고 demo:true 를 남긴다."""
    strategy = _resolve_strategy(req.state)
    key = os.environ.get("CLOVA_API_KEY")
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
    """실행 계획: {title, total_minutes, steps, drafts, coupon_card, measure}."""
    strategy, answers = _resolve_strategy_and_answers(req.state)
    key = os.environ.get("CLOVA_API_KEY")
    result = build_plan(CTX, strategy, answers, key)
    result["demo"] = key is None
    return result


@app.post("/api/marketing-survey/approve")
def approve(req: ApproveRequest):
    """승인 처리. H_REPEAT 의 fix_first 를 승인했을 때만 재주문 쿠폰 질문(예산부터)으로 이어진다."""
    state = req.state
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
