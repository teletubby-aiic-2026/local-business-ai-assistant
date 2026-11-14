"""CLOVA Studio 호출 공통 함수."""

import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid

import config

URL = "https://clovastudio.stream.ntruss.com/v3/chat-completions/{model}"

# 호출 1회의 제한 시간(초). 환경 변수 CLOVA_TIMEOUT_SEC 로 바꾼다. 평소 응답은 5~15초라 30초면 넉넉하다.
DEFAULT_TIMEOUT_SEC = 30.0
MAX_TIMEOUT_SEC = 300.0
# 실패하면 이만큼 쉬었다가 딱 한 번만 다시 부른다 (한도 초과·일시 오류·연결 끊김·제한 시간 초과).
RETRY_WAIT_SEC = 1.2
MAX_ATTEMPTS = 2
MAX_ERROR_CHARS = 500


def timeout_sec() -> float:
    """CLOVA_TIMEOUT_SEC (기본 30). 숫자가 아니거나 0 이하이면 기본값을 쓴다."""
    raw = (os.environ.get("CLOVA_TIMEOUT_SEC") or "").strip()
    try:
        value = float(raw) if raw else DEFAULT_TIMEOUT_SEC
    except ValueError:
        return DEFAULT_TIMEOUT_SEC
    return value if 0 < value <= MAX_TIMEOUT_SEC else DEFAULT_TIMEOUT_SEC


def _retryable_status(code: int) -> bool:
    return code == 429 or code >= 500


def call(key, system, messages, model=config.DEFAULT_MODEL, temperature=0.3, top_p=0.8,
         max_tokens=1024, thinking=None, tools=None, tool_choice=None):
    body = {
        "messages": [{"role": "system", "content": system}] + messages,
        "temperature": temperature,
        "topP": top_p,
    }
    if thinking:
        body["thinking"] = thinking
        body["maxCompletionTokens"] = max_tokens
    else:
        body["maxTokens"] = max_tokens
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["toolChoice"] = tool_choice
    payload = json.dumps(body).encode("utf-8")
    timeout = timeout_sec()
    start = time.time()
    data = None
    for attempt in range(MAX_ATTEMPTS):
        req = urllib.request.Request(      # 다시 부를 때는 요청 id 도 새로 만든다
            URL.format(model=model), data=payload, method="POST",
            headers={"Authorization": f"Bearer {key}", "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid.uuid4()),
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                data = json.loads(res.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "ignore")
            except Exception:
                detail = ""
            error, retry = f"HTTP {e.code}: {detail}", _retryable_status(e.code)
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:   # 제한 시간 초과, 연결 끊김 등
            error, retry = f"{e.__class__.__name__}: {e}", True
        except ValueError as e:      # 응답이 중간에 끊겨 JSON 을 읽지 못함
            error, retry = f"응답을 읽지 못했어요 ({e.__class__.__name__})", True
        if key:
            error = error.replace(key, "***")     # 오류 글에 키가 섞여 나가지 않게
        if not retry or attempt == MAX_ATTEMPTS - 1:
            return {"error": error[:MAX_ERROR_CHARS], "seconds": round(time.time() - start, 1)}
        time.sleep(RETRY_WAIT_SEC)
    result = data.get("result", {})
    usage = result.get("usage", {})
    tokens = usage.get("totalTokens", 0)
    price = config.PRICE_PER_1K.get(model, 7)
    cost_won = round(tokens / 1000 * price, 2)
    msg = result.get("message", {})
    out = {
        "content": msg.get("content", ""),
        "usage": usage,
        "tokens": tokens,
        "seconds": round(time.time() - start, 1),
        "cost_won": cost_won,
        "won": cost_won,
    }
    if msg.get("toolCalls"):
        out["toolCalls"] = msg["toolCalls"]
    return out


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
