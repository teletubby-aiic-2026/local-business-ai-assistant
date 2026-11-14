"""AI 응답에서 본문을 꺼낸다 — JSON이면 text류 키 값, 아니면 원문 그대로. 절대 버리지 않는다.

reply·notice·promo 공용. AI 가 JSON을 안 쓰고 문장 그대로 답해도(또는 "text" 가 아닌 다른 키를 써도)
본문을 잃지 않으려고, JSON 파싱이 안 되거나 쓸 만한 키가 없으면 원문(코드펜스만 벗김)을 그대로 돌려준다.
"""

import json
import re

_TEXT_KEY = re.compile(r"^(text|답글|reply|본문|공지)$", re.I)


def _strip_fence(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    return cleaned.strip()


def extract_body(raw: str) -> str:
    """JSON으로 파싱되고 text류 키가 있으면 그 값, 아니면 원문을 그대로 본문으로 쓴다."""
    cleaned = _strip_fence(raw or "")
    si = cleaned.find("{")
    ei = cleaned.rfind("}") + 1
    if si >= 0 and ei > si:
        try:
            data = json.loads(cleaned[si:ei])
        except (json.JSONDecodeError, ValueError):
            data = None
        if isinstance(data, dict):
            for k in data:
                if _TEXT_KEY.match(k) and isinstance(data[k], str) and data[k].strip():
                    return data[k].strip()
    return cleaned
