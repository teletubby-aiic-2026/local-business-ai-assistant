"""캡처 입력: 리뷰 화면 캡처 한 장 → HCX-005 가 보이는 그대로 옮겨 적은 리뷰 후보 목록.

흐름 (POST /api/review-insight/reviews/capture)
1. 이미지 검사: png·jpg·webp, CAPTURE_MAX_BYTES(기본 10MB) 이하. 형식은 파일 이름이 아니라 내용(Pillow)으로 확인
2. HCX-005 이미지 조건에 맞추기: 긴 변 2240px 이하, 가로세로 1:5~5:1. 세로로 아주 긴 캡처는 겹치게 잘라 최대 5조각
3. 조각마다 HCX-005 에 "보이는 그대로 옮겨 적기" (요약·수정·추측 금지, 닉네임·날짜·주문 정보·사장님 답글 제외)
4. JSON 배열만 받아 글·별점을 정리하고, 겹친 조각에서 두 번 나온 리뷰를 하나로
5. 분류는 하지 않는다. 사장님이 후보를 확인·수정한 뒤 기존 POST /reviews 로 저장할 때 분류된다

- 이미지는 메모리에서만 쓰고 디스크·로그에 남기지 않는다. 사용 기록에는 조각 수·후보 수·토큰·시간만 남긴다.
- dataUri 의 data 는 "data:image/jpeg;base64,<base64>" 앞머리가 있어야 한다 (앞머리 없으면 400 Invalid parameter, 11/15 실제 호출로 확인).
- 키는 분류와 같은 CLOVASTUDIO_API_KEY. APP_MODE=mock 이거나 키가 없으면 실제 호출 없이 예시 후보를 돌려준다(demo).
- 모델이 화면에 없는 글을 지어내거나 리뷰를 빠뜨릴 수 있고, 원문 글자가 따로 없어 코드로 대조할 수 없다.
  그래서 저장 전에 사장님 확인 단계를 반드시 거친다 (README '정직하게 밝힐 것').
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

log = logging.getLogger("review_insight.capture")

ROOT = Path(__file__).resolve().parents[2]
USAGE_LOG = ROOT / "logs" / "llm_usage.jsonl"        # 분류와 같은 파일, purpose 로 구분
ENDPOINT = "https://clovastudio.stream.ntruss.com/v3/chat-completions/{model}"
KST = timezone(timedelta(hours=9))

# MPO = 휴대폰 카메라·카카오톡이 저장하는 jpg (사진 여러 장이 든 JPEG). 확장자는 .jpg 이고 첫 장만 쓴다
FORMATS = {"PNG": "png", "JPEG": "jpg", "MPO": "jpg", "WEBP": "webp"}
LONG_SIDE = 2240           # HCX-005 이미지: 긴 변 이하
MAX_RATIO = 5.0            # 가로세로 1:5 ~ 5:1
PIECE_RATIO = 4.5          # 자를 때 조각 하나의 세로/가로 (5 보다 조금 작게)
OVERLAP = 0.12             # 조각끼리 겹치는 비율 (경계에 걸린 리뷰가 잘리지 않게)
MAX_PIECES = 5             # 요청당 이미지 최대 5장 규칙에 맞춤 (여기서는 조각마다 따로 부름)
MAX_TOKENS = 4096

PROMPT = """이 이미지는 배달앱이나 지도앱의 리뷰 화면 캡처다. 화면에 보이는 손님 리뷰를 보이는 그대로 옮겨 적어라.
규칙:
1. 글을 요약·수정·맞춤법 교정·추측하지 않는다. 오타와 이모티콘도 보이는 그대로 적는다.
2. 화면 위아래에서 잘려 끝까지 안 보이는 리뷰는 적지 않는다.
3. 닉네임, 날짜, 주문 메뉴 목록, 주문번호, 사장님 답글, 버튼·광고·메뉴 글자는 적지 않는다.
4. 별점은 리뷰마다 따로 센다. 색이 채워진 별(★)만 세고 빈 별(☆)은 세지 않는다. 숫자로 보이면 그 숫자. 1~5 정수, 확실하지 않으면 null.
5. 답은 JSON 배열 하나만 쓴다. 다른 글은 쓰지 않는다. 리뷰가 없으면 [].
형식: [{"text": "리뷰 글", "rating": 5}]"""

MENU_PROMPT = """이 이미지는 음식점 메뉴판 사진이나 캡처다. 보이는 메뉴 이름과 가격을 보이는 그대로 옮겨 적어라.
규칙:
1. 메뉴 이름을 고치거나 추측하지 않는다. 설명 글·광고 문구·가게 이름은 적지 않는다.
2. 가격은 숫자만 원 단위 정수로 (9,500원 → 9500). 안 보이면 null.
3. 크기별 가격이 따로 있으면 "메뉴 이름 (크기)"로 나눠 적는다.
4. 답은 JSON 배열 하나만 쓴다. 다른 글은 쓰지 않는다. 메뉴가 없으면 [].
형식: [{"name": "제육볶음 정식", "price": 9500}]"""

# APP_MODE=mock 이거나 키가 없을 때 돌려주는 예시 (실제 이미지 인식 결과가 아님 → demo: true)
DEMO_REVIEWS = [
    {"text": "제육볶음 양이 넉넉하고 맛있어요. 또 시킬게요!", "rating": 5},
    {"text": "공깃밥이 또 빠져 있었어요. 다음엔 꼭 챙겨 주세요", "rating": 2},
    {"text": "배달이 40분 넘게 늦어서 찌개가 식어서 왔어요", "rating": 2},
]


DEMO_MENU = [{"name": "제육볶음 정식", "price": 9500}, {"name": "된장찌개", "price": 8000}, {"name": "계란말이", "price": 6000}]


class CaptureError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False, details: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.retryable, self.details = status, code, message, retryable, details or {}


@dataclass
class CaptureResult:
    reviews: list[dict]                       # [{"text", "rating"}] 옮겨 적은 그대로 (가리기 전)
    pieces: int = 1
    demo: bool = False
    warnings: list[str] = field(default_factory=list)


def max_bytes() -> int:
    return int(os.environ.get("CAPTURE_MAX_BYTES", "") or 10 * 1024 * 1024)


# ── 1·2. 이미지 검사와 맞추기 ─────────────────────────────────────
def prepare(data: bytes) -> list[bytes]:
    """올린 이미지 → HCX-005 조건에 맞춘 JPEG 조각들. 조건에 안 맞으면 CaptureError(400)."""
    if not data:
        raise CaptureError(400, "VALIDATION_ERROR", "이미지가 비어 있습니다")
    if len(data) > max_bytes():
        raise CaptureError(400, "VALIDATION_ERROR", f"이미지는 {max_bytes() // (1024 * 1024)}MB 이하로 올려 주세요",
                           details={"max_bytes": max_bytes(), "bytes": len(data)})
    from PIL import Image, UnidentifiedImageError
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise CaptureError(400, "VALIDATION_ERROR", "png·jpg·webp 이미지만 올릴 수 있습니다") from None
    if fmt not in FORMATS:
        raise CaptureError(400, "VALIDATION_ERROR", f"png·jpg·webp 이미지만 올릴 수 있습니다 (이 파일은 {fmt or '알 수 없는'} 형식)",
                           details={"format": fmt})
    img = img.convert("RGB")
    w, h = img.size
    if w < 4 or h < 4:
        raise CaptureError(400, "VALIDATION_ERROR", "이미지가 너무 작습니다")
    if w / h > MAX_RATIO:
        raise CaptureError(400, "VALIDATION_ERROR", "가로로 너무 긴 이미지입니다. 리뷰 부분만 잘라서 올려 주세요")

    pieces = [img] if h / w <= MAX_RATIO else _split(img)
    if len(pieces) > MAX_PIECES:
        raise CaptureError(400, "CAPTURE_TOO_LONG", f"캡처가 너무 깁니다. {MAX_PIECES}장 이하로 나눠 올려 주세요",
                           details={"pieces_needed": len(pieces), "max_pieces": MAX_PIECES})
    out = []
    for p in pieces:
        if max(p.size) > LONG_SIDE:
            scale = LONG_SIDE / max(p.size)
            p = p.resize((max(4, round(p.width * scale)), max(4, round(p.height * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        p.save(buf, format="JPEG", quality=90)
        out.append(buf.getvalue())
    return out


def _split(img) -> list:
    """세로로 긴 캡처를 세로/가로 PIECE_RATIO 조각으로 겹치게 자른다."""
    w, h = img.size
    step_h = int(w * PIECE_RATIO)
    stride = max(1, int(step_h * (1 - OVERLAP)))
    tops = list(range(0, max(1, h - step_h) + 1, stride))
    if tops[-1] + step_h < h:
        tops.append(h - step_h)
    return [img.crop((0, t, w, min(h, t + step_h))) for t in tops]


# ── 3·4. 모델 호출과 답 정리 ──────────────────────────────────────
def parse_reviews(content: str) -> list[dict]:
    """모델 답에서 [{"text","rating"}] 를 건진다. ```json 감싸기·앞뒤 설명 글은 무시. 깨진 객체는 버린다."""
    text = re.sub(r"```(?:json)?", "", content or "")
    dec = json.JSONDecoder()
    found: list = []
    i = 0
    while i < len(text):
        if text[i] not in "[{":
            i += 1
            continue
        try:
            value, end = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            i += 1
            continue
        found.extend(value if isinstance(value, list) else [value])
        i = end
    out = []
    for item in found:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        body = " ".join(item["text"].split())
        if not body:
            continue
        rating = item.get("rating")
        if isinstance(rating, str) and rating.strip().isdigit():
            rating = int(rating.strip())
        if isinstance(rating, float) and rating.is_integer():
            rating = int(rating)
        if not (isinstance(rating, int) and not isinstance(rating, bool) and 1 <= rating <= 5):
            rating = None
        out.append({"text": body, "rating": rating})
    return out


def _same(a: str, b: str) -> bool:
    norm = lambda s: re.sub(r"[\s.,!?~…·]", "", s)
    return norm(a) == norm(b)


def merge(pieces: list[list[dict]]) -> list[dict]:
    """조각별 결과를 순서대로 합치되, 겹친 부분에서 두 번 나온 같은 글은 한 번만."""
    out: list[dict] = []
    for reviews in pieces:
        for r in reviews:
            same = next((x for x in out if _same(x["text"], r["text"])), None)
            if same is None:
                out.append(dict(r))
            elif same["rating"] is None and r["rating"] is not None:
                same["rating"] = r["rating"]
    return out


def parse_menu(content: str) -> list[dict]:
    """모델 답에서 [{"name","price"}] 를 건진다. 이름 없는 것은 버리고, 같은 이름은 한 번만."""
    text = re.sub(r"```(?:json)?", "", content or "")
    dec, found, i = json.JSONDecoder(), [], 0
    while i < len(text):
        if text[i] not in "[{":
            i += 1
            continue
        try:
            value, end = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            i += 1
            continue
        found.extend(value if isinstance(value, list) else [value])
        i = end
    out, seen = [], set()
    for item in found:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        name = " ".join(item["name"].split())[:40]
        price = item.get("price")
        if isinstance(price, str):
            digits = re.sub(r"[^0-9]", "", price)
            price = int(digits) if digits else None
        if isinstance(price, float) and price.is_integer():
            price = int(price)
        if not (isinstance(price, int) and not isinstance(price, bool) and 0 <= price <= 1_000_000):
            price = None
        if name and name not in seen:
            seen.add(name)
            out.append({"name": name, "price": price})
    return out


def merge_menu(pieces: list[list[dict]]) -> list[dict]:
    out: dict[str, dict] = {}
    for rows in pieces:
        for r in rows:
            if r["name"] not in out or out[r["name"]]["price"] is None:
                out[r["name"]] = dict(r)
    return list(out.values())


class CaptureReader:
    def __init__(self, mode: str | None = None, api_key: str | None = None, model: str | None = None,
                 transport: httpx.BaseTransport | None = None, timeout: float | None = None):
        env = os.environ
        self.mode = (mode if mode is not None else env.get("APP_MODE", "mock")).strip().lower() or "mock"
        if api_key is None:
            api_key = env.get("CLOVASTUDIO_API_KEY", "") or env.get("CLOVA_STUDIO_API_KEY", "")
        key = api_key.strip()
        self.api_key = key[7:].strip() if key.lower().startswith("bearer ") else key
        # 이미지 입력은 HCX-005 만 됨 (HCX-007·DASH 는 글만). 분류 모델을 바꿔도 캡처는 HCX-005
        self.model = model or env.get("LLM_MODEL_CAPTURE", "").strip() or "HCX-005"
        self.timeout = float(timeout if timeout is not None else (env.get("CAPTURE_TIMEOUT_SECONDS", "") or 40))
        self.transport = transport

    @property
    def demo(self) -> bool:
        return self.mode == "mock" or not self.api_key

    def read(self, data: bytes, kind: str = "reviews") -> CaptureResult:
        """kind: reviews(리뷰 화면 캡처) | menu(메뉴판 사진). menu 이면 reviews 칸에 [{"name","price"}] 가 들어간다."""
        menu = kind == "menu"
        pieces = prepare(data)                  # 검사는 demo 여도 똑같이 한다
        if self.demo:
            return CaptureResult(reviews=[dict(r) for r in (DEMO_MENU if menu else DEMO_REVIEWS)], pieces=len(pieces), demo=True,
                                 warnings=["예시 결과입니다. 키가 없거나 APP_MODE=mock 이라 이미지를 실제로 읽지 않았습니다"])
        what = "메뉴" if menu else "리뷰"
        results, warnings = [], []
        for n, piece in enumerate(pieces, 1):
            rows, truncated = self._ask(piece, n, len(pieces), MENU_PROMPT if menu else PROMPT,
                                        parse_menu if menu else parse_reviews, "menu_capture" if menu else "review_capture")
            if truncated:
                warnings.append(f"{n}번째 조각의 답이 길이 제한으로 잘렸을 수 있습니다. {what}가 빠졌는지 확인해 주세요")
            results.append(rows)
        merged = merge_menu(results) if menu else merge(results)
        if len(pieces) > 1:
            warnings.append(f"긴 캡처를 {len(pieces)}조각으로 나눠 읽었습니다. 경계에 걸린 {what}가 빠지거나 겹쳤는지 확인해 주세요")
        if not merged:
            raise CaptureError(422, "CAPTURE_UNREADABLE",
                               f"캡처에서 {what}를 찾지 못했습니다. 글자가 잘 보이게 다시 올리거나, 직접 입력해 주세요"
                               if menu else "캡처에서 리뷰를 찾지 못했습니다. 리뷰가 잘 보이게 다시 올리거나, 붙여넣기를 써 주세요",
                               details={"pieces": len(pieces)})
        return CaptureResult(reviews=merged, pieces=len(pieces), warnings=warnings)

    def _ask(self, piece: bytes, n: int, total: int, prompt: str = PROMPT, parser=parse_reviews,
             purpose: str = "review_capture") -> tuple[list[dict], bool]:
        body = {"messages": [{"role": "user", "content": [
                    {"type": "image_url", "dataUri": {"data": "data:image/jpeg;base64," + base64.b64encode(piece).decode("ascii")}},
                    {"type": "text", "text": prompt}]}],
                "topP": 0.8, "topK": 0, "temperature": 0.0, "maxTokens": MAX_TOKENS,
                "repetitionPenalty": 1.0, "seed": 0, "includeAiFilters": True}
        resp, status = None, "ok"
        t0 = time.perf_counter()
        for attempt in range(2):     # 분류와 같은 재시도 규칙: 429·5xx·시간 초과만 1번 더
            try:
                with httpx.Client(timeout=self.timeout, transport=self.transport) as c:
                    resp = c.post(ENDPOINT.format(model=self.model), json=body, headers={
                        "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                        "X-NCP-CLOVASTUDIO-REQUEST-ID": uuid.uuid4().hex})
            except httpx.TimeoutException:
                resp, status = None, "LLM_TIMEOUT"
                continue
            if resp.status_code == 429 and attempt == 0:
                time.sleep(min(float(resp.headers.get("retry-after", "2") or 2), 5))
                continue
            if resp.status_code >= 500 and attempt == 0:
                continue
            break
        latency = int((time.perf_counter() - t0) * 1000)
        result: dict = {}
        if resp is not None:
            if resp.status_code == 200:
                status = "ok"
                result = (resp.json() or {}).get("result") or {}
            else:
                status = "LLM_RATE_LIMITED" if resp.status_code == 429 else "LLM_UPSTREAM_ERROR"
        content = ((result.get("message") or {}).get("content") or "") if status == "ok" else ""
        reviews = parser(content) if status == "ok" else []
        truncated = result.get("finishReason") == "length"
        self._log(status, resp.status_code if resp is not None else None, result.get("usage") or {}, latency,
                  n, total, len(reviews), truncated, purpose)
        if status != "ok":
            retry = status in ("LLM_TIMEOUT", "LLM_RATE_LIMITED", "LLM_UPSTREAM_ERROR")
            raise CaptureError(502, status, "캡처를 읽는 AI 호출에 실패했습니다. 잠시 뒤 다시 올리거나 붙여넣기를 써 주세요",
                               retryable=retry, details={"http_status": resp.status_code if resp is not None else None})
        return reviews, truncated

    def _log(self, status, http_status, usage, latency_ms, piece, pieces, found, truncated, purpose="review_capture") -> None:
        """사용량 기록. 이미지·옮겨 적은 글은 남기지 않는다."""
        row = {"ts": datetime.now(KST).isoformat(timespec="seconds"), "purpose": purpose, "model": self.model,
               "mode": self.mode, "http_status": http_status, "status": status,
               "prompt_tokens": usage.get("promptTokens"), "completion_tokens": usage.get("completionTokens"),
               "total_tokens": usage.get("totalTokens"), "latency_ms": latency_ms,
               "piece": piece, "pieces": pieces, "reviews_found": found, "truncated": truncated}
        try:
            USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with USAGE_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("사용량 기록 실패: %s", e)
