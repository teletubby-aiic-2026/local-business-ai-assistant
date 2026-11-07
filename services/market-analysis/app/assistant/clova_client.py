"""CLOVA Studio answer writer (Chat Completions v3, JSON response, no streaming).

Connected only when APP_MODE=live (team convention: mock | live | replay). With
APP_MODE empty or mock the assistant answers with the fixed-form templates and
never calls a model. The writer receives the fact cards chosen for this turn
and returns text; flow.py publishes that text only if answer_check passes, so a
failed or wrong model answer always falls back to the verified template.

The API key is read once from the environment, sent only in the Authorization
header and never logged, returned, or included in exception messages.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import os
import re
import sys
import threading
import time
import uuid

import httpx

ENDPOINT = "https://clovastudio.stream.ntruss.com/v3/chat-completions/{model}"
DEFAULT_MODEL = "HCX-005"
DEFAULT_DAILY_LIMIT = 100
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_ANSWER_CHARS = 1500
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_KST = timezone(timedelta(hours=9))
_log = logging.getLogger("app.assistant.clova")

SYSTEM_PROMPT = """너는 서울 상권 공공 자료를 소상공인 사장님께 설명하는 상담 도우미다.
동네 상권을 잘 아는 사람이 메신저로 이야기하듯 자연스럽게 말하고, 사장님의 상황(창업 준비 중인지, 장사 중인지)을 헤아려 말을 건넨다.
사용자 메시지의 [사실 카드]만 근거로 [질문]에 답한다.

규칙
1. 숫자는 카드 문장이나 카드의 '값' 줄에 적힌 그대로 옮긴다. 더하거나 빼거나 나눠서 새 숫자를 만들지 않는다. 반올림하거나 '약', '억', '만' 단위로 바꾸지 않는다.
2. 한 줄에 한 문장씩 쓴다. 숫자가 들어간 줄 끝에는 그 숫자가 적힌 카드 번호를 [F2]처럼 붙인다.
3. 첫 줄에서 [질문]에 바로 답한다. 분석 조건(상권, 업종, 분기)은 화면에 따로 보이므로 다시 말하지 않는다. 질문이 둘을 견주면(점심과 저녁, 주말과 평일) '값' 줄에서 두 값을 찾아 함께 말한다. 질문에 없는 내용은 길게 늘어놓지 않는다.
4. 카드의 숫자는 상권 전체 통계다. 사장님 가게 한 곳의 매출이나 손님 수로 말하지 않는다. 유동인구는 업종과 상관없는 상권 전체 지표이므로 업종 이름을 붙이지 않는다.
5. 원인을 말하지 않는다. '때문', '요인', '초래', '~하면서 줄었다', '~것으로 보인다', '가능성이 있다'처럼 원인이나 추측으로 들리는 표현을 쓰지 않는다. 같은 기간에 함께 나타난 변화라고만 말한다.
6. 카드에 없는 상권, 분기, 숫자, 전망은 지어내지 않는다. 자료가 없다고 적힌 카드는 없다고 말한다.
7. 카드에 없는 비교나 평가를 덧붙이지 않는다. '좋아졌다', '나빠졌다', '장사가 잘 된다', '주말이 평일보다 낫다'처럼 판단하지 말고 카드의 증감과 순위만 옮긴다.
   다만 질문에 도움이 되는 해석(예: 점심 매출이 커서 직장인 손님이 많을 수 있다)은 맨 끝에 '해석:'으로 시작하는 한 줄로만 쓴다. 해석 줄에는 숫자를 쓰지 않고 '~일 수 있어요', '~를 시사해요'처럼 조심스럽게 쓰며, 매출이 늘거나 준 원인은 해석 줄에서도 말하지 않는다.
8. 숫자가 없는 줄에도 그 내용이 나온 카드 번호를 붙인다. 조건 카드(conditions)의 번호는 쓰지 않는다.
9. '참고:'로 시작하는 줄과 다음 질문 안내는 쓰지 않는다. 서버가 붙인다.
10. 해요체로 2~5줄 안에 짧게 답한다. 보고서처럼 '~입니다', '~습니다'로 끝내지 말고 대화하듯 쓴다. 목록 기호(-, •)와 마크다운 기호(**, #)는 쓰지 않는다."""

# One worked example. Weaker models follow the citation format much better with one,
# and this one shows answering the question itself from the '값' line.
_EXAMPLE_USER = """[질문]
예시역 한식 점심이랑 저녁 중에 언제 잘 팔려?

[사실 카드]
F1 (conditions) 분석 조건은 예시역 상권, 한식음식점 업종, 2026년 2분기 자료입니다.
F2 (sales_time) 시간대별 매출에서 가장 높은 항목은 17~21시(400,000,000원, 비중 40.00%), 가장 낮은 항목은 00~06시(10,000,000원)입니다.
    값: 00~06시 10,000,000원, 비중 1.00%; 06~11시 90,000,000원, 비중 9.00%; 11~14시 300,000,000원, 비중 30.00%; 14~17시 150,000,000원, 비중 15.00%; 17~21시 400,000,000원, 비중 40.00%; 21~24시 50,000,000원, 비중 5.00%"""
_EXAMPLE_ANSWER = """저녁(17~21시) 매출이 점심(11~14시)보다 커요. [F2]
저녁은 400,000,000원(40.00%), 점심은 300,000,000원(30.00%)이에요. [F2]
하루 시간대 가운데 가장 큰 구간도 저녁(17~21시)이에요. [F2]"""
_ROLE = {"current": "이번", "previous": "비교 기간", "base": "기준 상권", "comparison": "비교 상권"}


def _number(value, unit: str) -> str:
    if isinstance(value, float) and (unit == "%" or not value.is_integer()):
        return f"{value:,.2f}"
    return f"{int(value):,}" if isinstance(value, (int, float)) else str(value)


def _values_line(card: dict) -> str | None:
    """Every value on a card, so a question about one item (점심, 토요일, 20대) can be answered."""
    if card.get("topic") == "conditions":
        return None
    parts = []
    for value in (card.get("values") or [])[:14]:
        number = value.get("value")
        if number is None or isinstance(number, bool):
            continue
        unit = value.get("unit") or ""
        label = f"{value['group']} {value['label']}" if value.get("group") else value.get("label", "")
        role = _ROLE.get(value.get("role"))
        text = f"{label}{f'({role})' if role else ''} {_number(number, unit)}{unit}"
        share = value.get("share_percent")
        if isinstance(share, (int, float)) and not isinstance(share, bool):
            text += f", 비중 {share:.2f}%"
        parts.append(text)
    return "    값: " + "; ".join(parts) if parts else None


class ModelError(RuntimeError):
    """A model call that produced no usable text. The message never contains the key."""


def build_messages(cards: list[dict], classification: dict) -> list[dict]:
    question = (classification.get("text") or "").strip() or "이 상권 자료를 정리해 주세요."
    lines = []
    for card in cards:
        lines.append(f"{card['id']} ({card['topic']}) {card['text']}")
        values = _values_line(card)
        if values:
            lines.append(values)
    user = "[질문]\n" + question[:500] + "\n\n[사실 카드]\n" + "\n".join(lines)
    missing = classification.get("unavailable")
    if missing:
        # The server already tells the user this part is not in the data; the model must not answer it.
        user += (f"\n\n[자료에 없는 부분]\n{missing}: 서버가 '자료에 없다'고 이미 말했다. 이 부분은 다시 언급하거나 "
                 "사과하지 말고, 카드의 숫자를 이 부분의 답처럼 쓰지 않는다. 대신 카드에 있는 내용을 정리한다.")
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _EXAMPLE_USER},
            {"role": "assistant", "content": _EXAMPLE_ANSWER},
            {"role": "user", "content": user}]


def build_request(cards: list[dict], classification: dict) -> dict:
    return {"messages": build_messages(cards, classification), "topP": 0.8, "topK": 0, "maxTokens": 600,
            "temperature": 0.3, "repetitionPenalty": 1.1, "seed": 0, "includeAiFilters": True}


def _api_status(payload) -> str:
    status = payload.get("status") if isinstance(payload, dict) else None
    return str(status.get("code", "unknown")) if isinstance(status, dict) else "unknown"


class ClovaWriter:
    """Callable writer: ``writer(cards, classification) -> text``."""

    def __init__(self, api_key: str, *, model: str = DEFAULT_MODEL, daily_limit: int = DEFAULT_DAILY_LIMIT,
                 transport: httpx.BaseTransport | None = None, timeout: float = 30.0, now=None):
        self._key = api_key
        self.model = model
        self.daily_limit = daily_limit
        self._now = now or (lambda: datetime.now(_KST))
        self._used: dict = {}
        self._lock = threading.Lock()
        self._client = httpx.Client(transport=transport, timeout=httpx.Timeout(timeout, connect=5.0),
                                    follow_redirects=False)

    def __repr__(self) -> str:
        return f"ClovaWriter(model={self.model!r}, daily_limit={self.daily_limit})"

    def close(self) -> None:
        self._client.close()

    def _take_quota(self) -> None:
        # Counted per process and per KST day; failed attempts count too.
        today = self._now().date()
        with self._lock:
            used = self._used.get(today, 0)
            if used >= self.daily_limit:
                raise ModelError("daily model call limit reached")
            self._used = {today: used + 1}

    def __call__(self, cards: list[dict], classification: dict) -> str:
        result = self.complete(build_request(cards, classification), purpose="answer")
        message = result["message"]
        text = message.get("content")
        if message.get("role") != "assistant" or not isinstance(text, str) or not text.strip():
            raise ModelError("empty answer")
        if result.get("finishReason") == "length":
            raise ModelError("answer cut off at maxTokens")
        if len(text) > MAX_ANSWER_CHARS:
            raise ModelError("answer too long")
        return text

    def complete(self, body: dict, *, purpose: str) -> dict:
        """One Chat Completions call with the shared daily quota. Returns ``result`` with a dict ``message``.

        The planner (tool calls) and the answer writer use the same client, so
        the daily limit counts every model call of the assistant.
        """
        self._take_quota()
        request_id = str(uuid.uuid4())
        started = time.monotonic()
        try:
            response = self._client.post(
                ENDPOINT.format(model=self.model), json=body,
                headers={"Authorization": f"Bearer {self._key}", "X-NCP-CLOVASTUDIO-REQUEST-ID": request_id,
                         "Content-Type": "application/json; charset=utf-8", "Accept": "application/json"})
        except httpx.HTTPError as error:
            _log.warning("clova request failed: %s request_id=%s", type(error).__name__, request_id)
            raise ModelError(f"request failed: {type(error).__name__}") from None
        seconds = time.monotonic() - started
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise ModelError("response too large")
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code != 200 or not isinstance(payload, dict):
            code = _api_status(payload)
            _log.warning("clova http %s api %s request_id=%s", response.status_code, code, request_id)
            raise ModelError(f"HTTP {response.status_code}, API code {code}")
        code = _api_status(payload)
        if code != "20000":
            _log.warning("clova api %s request_id=%s", code, request_id)
            raise ModelError(f"API code {code}")
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        message = result.get("message") if isinstance(result.get("message"), dict) else {}
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        _log.info("clova %s model=%s tokens=%s seconds=%.1f finish=%s request_id=%s", purpose, self.model,
                  usage.get("totalTokens"), seconds, result.get("finishReason"), request_id)
        return {**result, "message": message}


def attach_usage_log() -> None:
    """Send assistant INFO logs (tokens, seconds per call) to stderr.

    uvicorn configures only its own loggers, so without this the per-call usage
    lines are dropped and only warnings reach the service log. Only the
    assistant logger is touched; other libraries keep their defaults.
    """
    logger = logging.getLogger("app.assistant")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def writer_from_env(environ=None, *, transport: httpx.BaseTransport | None = None) -> ClovaWriter | None:
    """The configured writer, or None when no model should be called.

    Raises ValueError for settings that would otherwise fail silently later,
    so a misconfigured server stops at start-up instead of answering wrongly.
    """
    env = os.environ if environ is None else environ
    mode = env.get("APP_MODE", "").strip().lower()
    if mode in ("", "mock"):
        return None
    if mode == "replay":
        raise ValueError("APP_MODE=replay is not supported by the assistant yet; use mock or live")
    if mode != "live":
        raise ValueError("APP_MODE must be empty, mock or live")
    key = env.get("CLOVA_STUDIO_API_KEY", "").strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    if not key:
        raise ValueError("APP_MODE=live needs CLOVA_STUDIO_API_KEY in .env")
    if not key.isascii() or any(character.isspace() for character in key):
        raise ValueError("CLOVA_STUDIO_API_KEY contains spaces or non-ASCII characters")
    model = env.get("CLOVA_MODEL_ANSWER", "").strip() or DEFAULT_MODEL
    if not _MODEL_NAME.fullmatch(model):
        raise ValueError("CLOVA_MODEL_ANSWER must be a model name such as HCX-005")
    raw_limit = env.get("ASSISTANT_MODEL_DAILY_LIMIT", "").strip()
    try:
        limit = int(raw_limit) if raw_limit else DEFAULT_DAILY_LIMIT
    except ValueError:
        raise ValueError("ASSISTANT_MODEL_DAILY_LIMIT must be a positive integer") from None
    if limit < 1:
        raise ValueError("ASSISTANT_MODEL_DAILY_LIMIT must be a positive integer")
    return ClovaWriter(key, model=model, daily_limit=limit, transport=transport)
