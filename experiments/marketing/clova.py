"""CLOVA Studio 호출 공통 함수."""

import json
import re
import time
import urllib.error
import urllib.request
import uuid

import config

URL = "https://clovastudio.stream.ntruss.com/v3/chat-completions/{model}"


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
    req = urllib.request.Request(
        URL.format(model=model), data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {key}", "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid.uuid4()),
                 "Content-Type": "application/json"},
    )
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            data = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')}"}
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
