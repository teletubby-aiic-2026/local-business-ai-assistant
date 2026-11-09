"""Assistant HTTP API. Mounted only when ASSISTANT_ENABLED is set.

POST /api/assistant/messages      one user message -> reply, fact cards, choices
POST /api/assistant/actions       the user picked a choice card
GET  /api/assistant/conversation  this session's turns and current conditions
GET  /api/assistant/conversation.md  the same as a Markdown file (development only, export.py)
DELETE /api/assistant/conversation
GET  /api/assistant/status

The session is the same cookie as /api/onboarding, so conditions chosen in the
chat and on the B1~B6 screens are one state.
"""
from __future__ import annotations

import os
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.assistant import export
from app.assistant.bridge import OnboardingBridge, endpoint_table, request_with_session
from app.assistant.flow import AssistantService, _conditions
from app.assistant.history import AssistantHistory
from app.onboarding import COOKIE_NAME, SESSION_TTL, OnboardingStore


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MessageInput(_Input):
    text: str = Field(min_length=1, max_length=1000)
    client_message_id: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")

    @field_validator("text")
    @classmethod
    def clean(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("메시지를 입력해 주세요.")
        return value


class ActionInput(_Input):
    type: Literal["location", "industry", "area", "comparison_area", "handoff"]
    kind: str | None = Field(default=None, max_length=20)
    station_id: str | None = Field(default=None, max_length=160)
    district_code: str | None = Field(default=None, pattern=r"^\d{5}$")
    neighborhood_code: str | None = Field(default=None, pattern=r"^\d{8}$")
    industry_code: str | None = Field(default=None, pattern=r"^CS\d{6}$")
    area_code: str | None = Field(default=None, pattern=r"^\d{7}$")
    period: str | None = Field(default=None, pattern=r"^\d{4}[1-4]$")
    domain: Literal["marketing", "customer"] | None = None


_FROM_ENV = object()


def planner_actions() -> list[str]:
    from app.assistant.planner import ACTIONS

    return list(ACTIONS)


def _planner_from_env(writer, use_morph: bool):
    """The AI planner rides on the CLOVA writer (same key and daily quota). ASSISTANT_PLANNER=off disables it."""
    value = os.environ.get("ASSISTANT_PLANNER", "").strip().lower()
    if value in ("off", "0", "false"):
        return None
    if value not in ("", "on", "1", "true"):
        raise ValueError("ASSISTANT_PLANNER must be empty, on or off")
    from app.assistant.planner import Planner

    return Planner(writer, use_morph=use_morph)


def create_assistant_router(store: OnboardingStore, onboarding_router=None, *, cookie_secure: bool = False,
                            writer=_FROM_ENV, use_morph: bool = True) -> APIRouter:
    planner = None
    if writer is _FROM_ENV:
        # APP_MODE=live connects CLOVA; empty or mock keeps fixed-form answers. Bad settings stop start-up.
        from app.assistant.clova_client import attach_usage_log, writer_from_env

        writer = writer_from_env()
        if writer is not None:
            attach_usage_log()
            planner = _planner_from_env(writer, use_morph)
    router = APIRouter(prefix="/api/assistant")
    history = AssistantHistory(store)
    table = endpoint_table(onboarding_router) if onboarding_router is not None else {}
    service = AssistantService(store, history, table, writer=writer, use_morph=use_morph, planner=planner)

    def session(request: Request):
        owner, token = store.session(request.cookies.get(COOKIE_NAME))
        return owner, token, request_with_session(request, token)

    can_export = export.enabled(cookie_secure)

    def respond(data, token):
        # The decision details stay in the stored turn for the development export; the page does not need them.
        result = JSONResponse({key: value for key, value in data.items() if key != "debug"})
        result.set_cookie(COOKIE_NAME, token, max_age=SESSION_TTL, httponly=True, samesite="strict",
                          secure=cookie_secure, path="/")
        result.headers["Cache-Control"] = "no-store"
        return result

    def require_table():
        if not table:
            raise HTTPException(503, "상권 분석 기능이 연결되지 않았습니다.")

    @router.get("/status")
    def status():
        # Report only what is actually wired. Never include credentials or configuration values.
        tools = planner_actions() if planner is not None else []
        return {"enabled": True, "model_connected": writer is not None, "planner_connected": planner is not None,
                "tools": tools, "export": can_export,
                "pipeline": ["classify", "conditions", "snapshot", "fact_cards", "answer_check"]}

    @router.post("/messages")
    def messages(body: MessageInput, request: Request):
        require_table()
        owner, token, scoped = session(request)
        return respond(service.handle_message(owner, scoped, body.text, body.client_message_id), token)

    @router.post("/actions")
    def actions(body: ActionInput, request: Request):
        require_table()
        owner, token, scoped = session(request)
        payload = body.model_dump(exclude_none=True)
        return respond(service.handle_action(owner, scoped, payload), token)

    @router.get("/conversation")
    def conversation(request: Request):
        owner, token, scoped = session(request)
        state = None
        if table:
            try:
                state = OnboardingBridge(table, scoped).state()
            except HTTPException:
                state = None
        turns = [{"seq": t["seq"], "user_text": t["user_text"], "reply": t["response"].get("reply"),
                  "cards": t["response"].get("cards", []), "action": t["response"].get("action")}
                 for t in history.recent(owner)]
        return respond({"turns": turns, "conditions": _conditions(state)}, token)

    @router.get("/conversation.md")
    def conversation_markdown(request: Request):
        if not can_export:
            raise HTTPException(404, "대화 내보내기는 개발 환경에서만 쓸 수 있습니다.")
        owner, token, scoped = session(request)
        state = None
        if table:
            try:
                state = OnboardingBridge(table, scoped).state()
            except HTTPException:
                state = None
        text = export.conversation_markdown(history.recent(owner, 50), _conditions(state),
                                            model=getattr(writer, "model", None))
        saved = export.save_copy(text, owner)
        stamp = export.datetime.now(export.KST).strftime("%Y%m%d-%H%M")
        result = Response(text, media_type="text/markdown; charset=utf-8")
        result.headers["Content-Disposition"] = f'attachment; filename="assistant-chat-{stamp}.md"'
        result.headers["Cache-Control"] = "no-store"
        if saved:
            result.headers["X-Export-Saved"] = saved
        result.set_cookie(COOKIE_NAME, token, max_age=SESSION_TTL, httponly=True, samesite="strict",
                          secure=cookie_secure, path="/")
        return result

    @router.delete("/conversation")
    def clear(request: Request):
        owner, token, _scoped = session(request)
        removed = history.clear(owner)
        service.snapshots.drop_owner(owner)
        return respond({"removed_turns": removed}, token)

    return router
