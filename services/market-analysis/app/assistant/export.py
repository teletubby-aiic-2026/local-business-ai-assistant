"""The conversation as a Markdown file, for testing in development (user request 2026-11-08).

The user tests the chat and sends the conversation back instead of
screenshots. Besides what was said, each reply lists what the server decided
(the planner's action, the turn type and topics), whether the model's text
was used and, if not, why answer_check rejected it. These come from the
stored turns only; nothing is recomputed and no key or setting is included.

Enabled only outside public mode (the SSH tunnel and local runs);
ASSISTANT_EXPORT=off turns it off there too. With ASSISTANT_EXPORT_DIR set,
each export is also written to that directory on the server.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re

KST = timezone(timedelta(hours=9))
_CITE = re.compile(r"\s*\[F\d+\]")


def enabled(public_mode: bool) -> bool:
    value = os.environ.get("ASSISTANT_EXPORT", "").strip().lower()
    if value in ("off", "0", "false"):
        return False
    return not public_mode


def _quote(text: str) -> list[str]:
    return [f"> {line}" if line.strip() else ">" for line in (text or "").splitlines()] or ["> (빈 답)"]


def _action_label(turn: dict, previous: dict | None) -> str:
    payload = turn["response"].get("action") or {}
    for action in ((previous or {}).get("reply") or {}).get("actions") or []:
        if action.get("payload") == payload:
            return action.get("label") or "선택"
    return " ".join(f"{key}={value}" for key, value in payload.items()) or "선택"


def _problems(debug: dict) -> str:
    rejected = debug.get("model_rejected") or []
    parts = []
    for problem in rejected[:6]:
        detail = problem.get("detail")
        if isinstance(detail, list):
            detail = ",".join(map(str, detail))
        parts.append(problem["type"] + (f"({detail})" if detail else ""))
    return ", ".join(parts)


def conversation_markdown(turns: list[dict], conditions: dict | None, *, model: str | None, now=None) -> str:
    now = now or datetime.now(KST)
    lines = ["# 상권 비서 대화 기록", "",
             f"- 내보낸 시각: {now.strftime('%Y-%m-%d %H:%M')} (KST)",
             f"- 지금 조건: " + (f"{conditions.get('area_name') or '상권 미정'} · {conditions.get('industry_name') or '업종 미정'}"
                              f" · {conditions.get('period_label') or '기간 미정'}" if conditions else "정하지 않음"),
             f"- 답변 모델: {model or '연결 안 됨(정형 답변만)'}",
             f"- 대화 수: {len(turns)}", ""]
    previous = None
    for number, turn in enumerate(turns, start=1):
        response = turn["response"]
        reply = response.get("reply") or {}
        said = turn["user_text"] if turn.get("user_text") else f"(버튼) {_action_label(turn, previous)}"
        lines += [f"## {number}. 사용자: {said}", ""]
        classification = response.get("classification") or {}
        debug = response.get("debug") or {}
        meta = [f"답 종류 {reply.get('kind')}",
                "AI 문장 사용" if response.get("model_used") else "정형 답변"]
        if classification.get("turn_type"):
            meta.append(f"분류 {classification.get('turn_type')} {classification.get('topics') or []}")
        planner = debug.get("planner") or {}
        if planner.get("action"):
            meta.append("AI 판단 " + planner["action"] + " " + json.dumps(planner.get("args") or {}, ensure_ascii=False))
        lines += ["**상권 비서** · " + " · ".join(meta), ""]
        lines += _quote(_CITE.sub("", reply.get("text") or ""))
        lines.append("")
        extras = []
        if reply.get("actions"):
            extras.append("- 버튼: " + " / ".join(action.get("label", "") for action in reply["actions"]))
        if reply.get("suggestions"):
            extras.append("- 다음 질문 버튼: " + " / ".join(reply["suggestions"]))
        cards = response.get("cards") or []
        if cards:
            extras.append("- 근거 카드: " + ", ".join(f"{card.get('id')} {card.get('topic')}" for card in cards))
        problems = _problems(debug)
        if problems:
            extras.append("- AI 문장을 쓰지 않은 이유: " + problems)
        if debug.get("model_error"):
            extras.append("- 모델 호출 실패: 정형 답변으로 대신함")
        if debug.get("reasons"):
            extras.append("- 판단 근거: " + "; ".join(map(str, debug["reasons"][:4])))
        if extras:
            lines += [*extras, ""]
        previous = response
    return "\n".join(lines).rstrip() + "\n"


def save_copy(text: str, owner: str, now=None) -> str | None:
    """Write the export to ASSISTANT_EXPORT_DIR on the server, if set. Returns the file name."""
    folder = os.environ.get("ASSISTANT_EXPORT_DIR", "").strip()
    if not folder:
        return None
    now = now or datetime.now(KST)
    path = Path(folder)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = f"assistant-{now.strftime('%Y%m%d-%H%M%S')}-{sha256(owner.encode()).hexdigest()[:8]}.md"
    (path / name).write_text(text, encoding="utf-8")
    return name
