"""글만 주고받는 HCX-005 호출 (문의 답변 초안용). classify.py·capture.py 와 같은 방식: httpx, 시간 제한, 재시도 1번,
시험용 transport 주입, 사용 기록(글은 남기지 않음). APP_MODE=mock 이거나 키가 없으면 부르지 않는다 (available=False)."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime

import httpx

from app.sources import capture

log = logging.getLogger("review_insight.chat")


class ChatError(Exception):
    pass


class Chat:
    def __init__(self, mode: str | None = None, api_key: str | None = None, model: str | None = None,
                 transport: httpx.BaseTransport | None = None, timeout: float | None = None):
        env = os.environ
        self.mode = (mode if mode is not None else env.get("APP_MODE", "mock")).strip().lower() or "mock"
        if api_key is None:
            api_key = env.get("CLOVASTUDIO_API_KEY", "") or env.get("CLOVA_STUDIO_API_KEY", "")
        key = api_key.strip()
        self.api_key = key[7:].strip() if key.lower().startswith("bearer ") else key
        self.model = model or env.get("LLM_MODEL_CARE", "").strip() or "HCX-005"
        self.timeout = float(timeout if timeout is not None else (env.get("LLM_TIMEOUT_SECONDS", "") or 20))
        self.transport = transport

    @property
    def available(self) -> bool:
        return self.mode == "live" and bool(self.api_key)

    def ask(self, system: str, user: str, purpose: str, max_tokens: int = 600) -> str:
        if not self.available:
            raise ChatError("키가 없거나 APP_MODE=mock 입니다")
        body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "topP": 0.8, "topK": 0, "temperature": 0.3, "maxTokens": max_tokens, "repetitionPenalty": 1.1,
                "seed": 0, "includeAiFilters": True}
        resp, status, t0 = None, "ok", time.perf_counter()
        for attempt in range(2):
            try:
                with httpx.Client(timeout=self.timeout, transport=self.transport) as c:
                    resp = c.post(capture.ENDPOINT.format(model=self.model), json=body, headers={
                        "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                        "X-NCP-CLOVASTUDIO-REQUEST-ID": uuid.uuid4().hex})
            except httpx.TimeoutException:
                resp, status = None, "LLM_TIMEOUT"
                continue
            if (resp.status_code == 429 or resp.status_code >= 500) and attempt == 0:
                continue
            break
        latency = int((time.perf_counter() - t0) * 1000)
        result: dict = {}
        if resp is not None:
            status = "ok" if resp.status_code == 200 else ("LLM_RATE_LIMITED" if resp.status_code == 429 else "LLM_UPSTREAM_ERROR")
            if status == "ok":
                result = (resp.json() or {}).get("result") or {}
        usage = result.get("usage") or {}
        row = {"ts": datetime.now(capture.KST).isoformat(timespec="seconds"), "purpose": purpose, "model": self.model,
               "mode": self.mode, "http_status": resp.status_code if resp is not None else None, "status": status,
               "prompt_tokens": usage.get("promptTokens"), "completion_tokens": usage.get("completionTokens"),
               "total_tokens": usage.get("totalTokens"), "latency_ms": latency}
        try:
            capture.USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with capture.USAGE_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("사용량 기록 실패: %s", e)
        if status != "ok":
            raise ChatError(status)
        return ((result.get("message") or {}).get("content") or "").strip()
