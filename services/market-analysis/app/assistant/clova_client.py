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
RATE_LIMIT_WAIT = 2.0  # seconds before the one retry after HTTP 429
MAX_ANSWER_CHARS = 1500
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_KST = timezone(timedelta(hours=9))
_log = logging.getLogger("app.assistant.clova")

SYSTEM_PROMPT = """너는 '상권 비서'다. 서울 상권 공공 자료를 사장님 옆에서 같이 들여다보며 설명해 주는, 상권을 잘 아는 컨설턴트 친구처럼 말한다.
메신저로 대화하듯 자연스럽고 따뜻하게, 그러나 군더더기 없이 말한다. 사장님의 상황(창업 준비 중인지, 장사 중인지)을 헤아린다.
사용자 메시지의 [사실 카드]만 근거로 [질문]에 답한다.

답의 흐름
- 첫 문장: [질문]에 대한 답(결론)을 바로 말한다. 예: "30대가 가장 많이 사요."
- 이어서: 그 답의 숫자 근거를 1~2문장으로 말한다. 질문이 둘을 견주면(점심과 저녁, 합정역과 강남역) 두 값을 함께 말한다.
- 그다음(필요할 때만): 이 숫자가 사장님께 어떤 뜻일 수 있는지 '해석:'으로 시작하는 한 줄. 숫자 없이 '~일 수 있어요'처럼 조심스럽게 쓴다.
- 끝(필요할 때만): 이어서 보면 좋을 것을 짧은 질문 한 문장으로 권한다. 예: "주말 매출도 같이 볼까요?" 권하는 질문은 이 서비스가 답할 수 있는 것(요일·시간대·연령대 매출, 점포 수, 개업·폐업, 유동인구, 작년 대비, 다른 상권과 비교, 업종 순위, 창업 의견) 가운데서만 고른다. 메뉴·상품 종류·가격·고객 취향처럼 자료에 없는 것은 권하지 않는다.

규칙
1. 숫자는 카드 문장이나 카드의 '값' 줄에 적힌 그대로 옮긴다. 더하거나 빼거나 나눠서 새 숫자를 만들지 않는다. 반올림하거나 '약', '억', '만' 단위로 바꾸지 않는다. 읽기 쉬운 단위는 서버가 덧붙인다.
2. 한 줄에 1~2문장까지 자연스럽게 이어 써도 된다. 숫자가 들어간 줄 끝에는 그 숫자가 적힌 카드 번호를 [F2]처럼 붙인다. 숫자가 없는 줄에도 그 내용이 나온 카드 번호를 붙인다. 조건 카드(conditions)의 번호는 쓰지 않고, 마지막에 권하는 질문 한 줄에는 번호를 붙이지 않는다.
3. 분석 조건(상권, 업종, 분기)은 화면에 따로 보이므로 다시 말하지 않는다. 질문에 없는 내용은 길게 늘어놓지 않는다.
4. 카드의 숫자는 상권 전체 통계다. 사장님 가게 한 곳의 매출이나 손님 수로 말하지 않는다. 유동인구는 업종과 상관없는 상권 전체 지표이므로 업종 이름을 붙이지 않는다.
   카드는 상권 한 곳의 자료다. 질문이 구 전체(예: 강남구)를 물어도 '이 상권은'이나 카드의 상권 이름으로 말하고, 구 이름으로 넓혀 말하지 않는다.
   질문의 장소와 조건 카드의 상권이 달라도 사용자가 그 상권을 골라 본 것이다. 자료가 없다고 하지 말고 카드 자료로 답한다.
5. 원인을 단정하지 않는다. '때문', '요인', '초래', '~하면서 줄었다', '~것으로 보인다', '가능성이 있다'처럼 원인이나 추측으로 들리는 표현을 쓰지 않는다. 같은 기간에 함께 나타난 변화라고만 말한다. 매출이 늘거나 준 원인은 해석 줄에서도 말하지 않는다.
6. 카드에 없는 상권, 업종, 분기, 숫자, 전망은 지어내지 않는다. 자료가 없다고 적힌 카드는 없다고 말한다. 상권이 어떤 곳인지(산업 단지, 아울렛, 대학가, 오피스 상권 등)도 카드에 없으면 말하지 않는다.
7. '좋아졌다', '나빠졌다', '장사가 잘 된다', '낫다'처럼 평가하지 않는다. 숫자가 말하는 것을 쉽게 풀어 주되 판단은 사장님 몫으로 둔다.
8. '참고:'로 시작하는 줄은 쓰지 않는다. 서버가 붙인다.
9. 해요체로 2~5줄. '~입니다', '~습니다' 같은 보고서 말투, '자료에 따르면', '분석 결과' 같은 딱딱한 말머리, 목록 기호(-, •), 마크다운 기호(**, #)는 쓰지 않는다."""

# One worked example. Weaker models follow the citation format much better with one,
# and this one shows answering the question itself from the '값' line.
_EXAMPLE_USER = """[질문]
예시역 점심이랑 저녁 중에 언제 잘 팔려?

[사실 카드]
F1 (conditions) 분석 조건은 예시역 상권, 예시 업종, 2026년 2분기 자료입니다.
F2 (sales_time) 시간대별 매출에서 가장 높은 항목은 17~21시(400,000,000원, 비중 40.00%), 가장 낮은 항목은 00~06시(10,000,000원)입니다.
    값: 00~06시 10,000,000원, 비중 1.00%; 06~11시 90,000,000원, 비중 9.00%; 11~14시 300,000,000원, 비중 30.00%; 14~17시 150,000,000원, 비중 15.00%; 17~21시 400,000,000원, 비중 40.00%; 21~24시 50,000,000원, 비중 5.00%"""
_EXAMPLE_ANSWER = """저녁에 더 많이 팔려요. [F2]
저녁(17~21시)이 400,000,000원으로 하루 매출의 40.00%를 차지하고, 점심(11~14시)은 300,000,000원(30.00%)이에요. [F2]
해석: 퇴근길 손님이 많이 들르는 상권일 수 있어요.
주말에도 저녁이 강한지 같이 볼까요?"""
_ROLE = {"current": "이번", "previous": "비교 기간", "base": "기준 상권", "comparison": "비교 상권"}

# The user asked for the assistant's own view (user decision 2026-11-08). The view must rest on the opinion card;
# answer_check verifies numbers and comparisons, and the server adds what the data lacks (rent, key money).
OPINION_PROMPT = """너는 서울 상권 공공 자료를 함께 보며 소상공인의 창업·운영 고민을 듣는 상담 도우미다.
사용자가 너의 생각을 물었다. [사실 카드]의 판단 기준(opinion 카드)을 근거로 너의 의견을 분명하게 말한다.

규칙
0. 너는 '상권 비서'다. '인공지능이라 의견이 없다'고 하지 않는다. 사용자는 자료에 근거한 너의 판단을 원한다.
1. 첫 줄에서 질문에 바로 답한다. 두 곳이면 '저라면 ○○ 쪽을 고르겠어요'처럼 한쪽을 고른다. 기준이 반반으로 갈리면 무엇을 중요하게 보느냐에 따라 어느 쪽인지 말한다. 한 곳이면 '해볼 만해 보여요' 또는 '조금 신중하게 보시는 게 좋겠어요'처럼 답한다.
2. 이어서 근거를 2~3줄 쓴다. 근거 줄마다 카드의 숫자를 하나 이상 그대로 옮기고('강남역 69,586,500원') 줄 끝에 카드 번호를 [F2]처럼 붙인다. 숫자 없이 '모든 기준에서 앞서요'라고만 쓰지 않는다. 숫자를 새로 계산하거나 반올림하지 않는다.
3. 고르지 않은 쪽이 앞서는 기준이 있으면 '다만'으로 시작하는 한 줄로 공정하게 말한다.
3-1. 좋다·나쁘다는 카드의 '서울 안 위치'(상위 비율과 구간: 상위권·중상위권·중간·하위권)로만 말한다. 위치가 적히지 않은 기준에 '많은 편', '낮은 편'을 붙이지 않는다. 구간은 그 기준에만 쓴다. 매출 순위의 구간을 점포당 매출에 붙이지 않는다. 약한 기준(중간·하위권)도 숨기지 않고 말한다.
3-1a. 카드에 입지 유형(직장 수요형 등)이나 기준 비중이 있으면 왜 이 업종에 맞거나 안 맞는지 한 문장으로 말해도 된다. 입지 유형은 카드에 적힌 표현 그대로 쓴다.
3-2. 한 곳을 물으면 첫 줄의 결론은 카드의 '종합 판단'과 같은 방향으로 쓴다. 서울 중앙값과 견줄 때는 숫자대로 쓴다. 예: -2.78%는 2.41%보다 낮다.
4. '계산값'은 서버가 공공 자료로 계산한 값이다. 점포당 매출은 그 상권 같은 업종 가게들의 평균이지 가게 한 곳의 매출이 아니다.
5. 카드에 없는 사실(임대료, 권리금, 분위기, 개성, 유명세, 직장인·학생 수, 가게 위치)은 지어내지 않는다. 임대료·권리금을 확인하라는 안내는 서버가 붙이므로 쓰지 않는다.
6. '무조건', '확실히', '성공', '보장', '대박'처럼 단정하는 말은 쓰지 않는다.
7. 해요체로 3~5줄, 한 줄에 한 문장. 목록 기호(-, •)와 마크다운 기호(**, #)는 쓰지 않는다."""

_OPINION_USER = """[질문]
가나역이랑 다라동 중에 창업하기 어디가 나아?

[사실 카드]
F1 (conditions) 분석 조건은 가나역 상권, 예시 업종, 2026년 2분기 자료입니다.
F2 (opinion) 가나역과 다라동의 예시 업종 2026년 2분기 판단 기준입니다. 점포당 분기 추정매출(계산값)은 가나역 30,000,000원, 다라동 45,000,000원으로 다라동이 앞섭니다. 작년 같은 분기 대비 매출 변화율(계산값)은 가나역 -2.00%, 다라동 5.00%로 다라동이 앞섭니다. 점포 1곳당 유동인구(계산값)는 가나역 9,000명, 다라동 6,000명으로 가나역이 앞섭니다. 3개 기준 가운데 가나역 1개, 다라동 2개에서 앞섭니다.
    값: 가나역 추정매출 600,000,000원; 가나역 전체 점포 20개; 가나역 점포당 분기 추정매출(계산값) 30,000,000원; 가나역 작년 같은 분기 대비 매출 변화율(계산값) -2.00%; 가나역 점포 1곳당 유동인구(계산값) 9,000명; 다라동 추정매출 450,000,000원; 다라동 전체 점포 10개; 다라동 점포당 분기 추정매출(계산값) 45,000,000원; 다라동 작년 같은 분기 대비 매출 변화율(계산값) 5.00%; 다라동 점포 1곳당 유동인구(계산값) 6,000명"""
_OPINION_ANSWER = """저라면 다라동 쪽을 고르겠어요. [F2]
점포당 분기 추정매출이 다라동 45,000,000원으로 가나역 30,000,000원보다 커요. [F2]
작년 같은 분기 대비 매출 변화율도 다라동이 5.00%로 가나역 -2.00%보다 높아요. [F2]
다만 점포 1곳당 유동인구는 가나역이 9,000명으로 다라동 6,000명보다 많아요. [F2]"""


def _number(value, unit: str) -> str:
    if isinstance(value, float) and (unit == "%" or not value.is_integer()):
        return f"{value:,.2f}"
    return f"{int(value):,}" if isinstance(value, (int, float)) else str(value)


def _values_line(card: dict) -> str | None:
    """Every value on a card, so a question about one item (점심, 토요일, 20대) can be answered."""
    if card.get("topic") == "conditions":
        return None
    parts = []
    limit = 120 if card.get("topic") == "opinion" else 20 if card.get("topic") == "area_profile" else 14  # an opinion card holds two markets' figures
    for value in (card.get("values") or [])[:limit]:
        number = value.get("value")
        if number is None or isinstance(number, bool):
            continue
        unit = value.get("unit") or ""
        label = f"{value['group']} {value['label']}" if value.get("group") else value.get("label", "")
        if value.get("market"):
            label = f"{value['market']} {label}"
        if value.get("derived"):
            label += "(계산값)"
        role = _ROLE.get(value.get("role"))
        text = f"{label}{f'({role})' if role else ''} {_number(number, unit)}{unit}"
        share = value.get("share_percent")
        if isinstance(share, (int, float)) and not isinstance(share, bool):
            text += f", 비중 {share:.2f}%"
        parts.append(text)
    return "    값: " + "; ".join(parts) if parts else None


class ModelError(RuntimeError):
    """A model call that produced no usable text. The message never contains the key."""


class _RateLimited(ModelError):
    """HTTP 429: worth one more try after a short wait."""


def build_messages(cards: list[dict], classification: dict) -> list[dict]:
    question = (classification.get("text") or "").strip() or "이 상권 자료를 정리해 주세요."
    lines = []
    for card in cards:
        lines.append(f"{card['id']} ({card['topic']}) {card['text']}")
        values = _values_line(card)
        if values:
            lines.append(values)
    user = "[질문]\n" + question[:500] + "\n\n[사실 카드]\n" + "\n".join(lines)
    if classification.get("all_industries"):
        user += ("\n\n[전체 업종]\n카드는 이 상권의 모든 업종을 합친 값이다. 카페나 특정 업종의 이야기로 바꿔 말하지 않는다. "
                 "'평균'을 물으면 카드의 '하루 평균' 값으로 답한다.")
    markets = classification.get("multi_markets")
    if markets:
        user += (f"\n\n[여러 상권]\n카드가 {', '.join(markets)} 상권별로 나뉘어 있다. 질문에 대해 상권마다 빠짐없이 답하고, "
                 "같은 항목끼리 견줘서 차이를 짚어 준다. 상권 이름을 문장마다 밝힌다.")
    missing = classification.get("unavailable")
    if missing:
        # The server already tells the user this part is not in the data; the model must not answer it.
        user += (f"\n\n[자료에 없는 부분]\n{missing}: 서버가 '자료에 없다'고 이미 말했다. 이 부분은 다시 언급하거나 "
                 "사과하지 말고, 카드의 숫자를 이 부분의 답처럼 쓰지 않는다. 대신 카드에 있는 내용을 정리한다.")
    if classification.get("turn_type") == "opinion":
        messages = [{"role": "system", "content": OPINION_PROMPT},
                    {"role": "user", "content": _OPINION_USER},
                    {"role": "assistant", "content": _OPINION_ANSWER},
                    {"role": "user", "content": user}]
    else:
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _EXAMPLE_USER},
                    {"role": "assistant", "content": _EXAMPLE_ANSWER},
                    {"role": "user", "content": user}]
    retry = classification.get("retry")
    if retry:
        # One rewrite with the checker's findings (design 8.2), instead of dropping to the fixed answer at once.
        messages += [{"role": "assistant", "content": retry["previous"][:MAX_ANSWER_CHARS]},
                     {"role": "user", "content": "[고칠 점]\n" + retry["feedback"] + "\n위 점만 고쳐서 답 전체를 다시 써 주세요."}]
    return messages


def build_request(cards: list[dict], classification: dict) -> dict:
    return {"messages": build_messages(cards, classification), "topP": 0.8, "topK": 0, "maxTokens": 600,
            "temperature": 0.3, "repetitionPenalty": 1.1, "seed": 0, "includeAiFilters": True}


def _api_status(payload) -> str:
    status = payload.get("status") if isinstance(payload, dict) else None
    return str(status.get("code", "unknown")) if isinstance(status, dict) else "unknown"


class ClovaWriter:
    """Callable writer: ``writer(cards, classification) -> text``."""

    def __init__(self, api_key: str, *, model: str = DEFAULT_MODEL, daily_limit: int = DEFAULT_DAILY_LIMIT,
                 transport: httpx.BaseTransport | None = None, timeout: float = 30.0, now=None, sleep=None):
        self._key = api_key
        self.model = model
        self.daily_limit = daily_limit
        self._now = now or (lambda: datetime.now(_KST))
        self._sleep = sleep or time.sleep
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
        the daily limit counts every model call of the assistant. A question asked right after another can
        meet CLOVA's per-minute limit, so HTTP 429 is tried once more before the fixed-form answer takes over.
        """
        try:
            return self._call(body, purpose=purpose)
        except _RateLimited:
            self._sleep(RATE_LIMIT_WAIT)
        try:
            return self._call(body, purpose=purpose)
        except _RateLimited as error:
            raise ModelError(str(error)) from None

    def _call(self, body: dict, *, purpose: str) -> dict:
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
            if response.status_code == 429:
                raise _RateLimited(f"HTTP {response.status_code}, API code {code}")
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
