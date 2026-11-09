"""팀 공통 데이터 계약 (C1).

파트마다 입출력 형식이 달라 이어 붙일 수 없던 문제를, 앱 안의 dataclass 5개로 줄인 것입니다.
표준 라이브러리만 쓰므로 어느 파트에서든 import할 수 있습니다.

    from shared.contracts import (
        StoreProfile, AnalysisSnapshot, ReviewRecord, ToneProfile, RecommendationCard,
        CARD_GENERATORS,
    )

| 클래스               | 한 개가 뜻하는 것                    | ID 필드       | ID 접두사 |
|----------------------|--------------------------------------|---------------|-----------|
| StoreProfile         | 가게 1곳                             | store_id      | store_    |
| AnalysisSnapshot     | 상권 지표 1건 (JSON 파일은 이것의 목록) | snapshot_id   | snap_     |
| ReviewRecord         | 리뷰 1건 (+ 분류 결과)               | review_id     | rv_       |
| ToneProfile          | 사장님 말투 1벌                      | tone_id       | tone_     |
| RecommendationCard   | 추천 카드 1장                        | card_id       | card_     |

규칙
- 필드 이름과 정해진 값(열거값)은 소문자 snake_case입니다 (PR #7 규격의 규칙을 이어받음).
- ID는 접두사가 붙은 문자열입니다. 접두사는 약속일 뿐 코드가 강제하지는 않습니다.
- 값이 없을 때는 None입니다. "자료 없음"(None)과 "0"은 다릅니다.
- 시각은 ISO 8601 "문자열"입니다("2026-11-07T22:41:00+09:00"). 만들 때 항상 한국 시간(+09:00)으로 맞추므로
  문자열 정렬이 곧 시간순입니다. datetime이 필요하면 ReviewRecord.created_datetime을 쓰세요.
- 이 계약은 PR #14(C2·C3)의 실제 데이터(리뷰 100건·가게 3곳)가 그대로 읽히도록 그쪽 필드 이름과 값에 맞췄습니다.
- 잘못된 값은 만드는 순간 ValueError로 막습니다. 화면에 가기 전에 데이터 쪽에서 틀린 곳을 알 수 있게 하려는 것입니다.
- JSON 읽기/쓰기: record.to_dict() / Class.from_dict(dict), 또는 dump_json() / load_json().
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field, fields, MISSING
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, TypeVar

# ── 정해진 값 (열거값) ───────────────────────────────────────────────
CHANNELS = ("baemin", "coupangeats", "yogiyo", "naver_place")
SENTIMENTS = ("positive", "negative", "mixed", "neutral")
URGENCIES = ("low", "medium", "high")
CARD_KINDS = ("complaint", "promo")
INPUT_METHODS = ("sample", "paste")                                      # 합성 샘플 | 직접 붙여넣기(S2)
REVIEW_STATUSES = ("new", "analyzed", "drafted", "replied", "skipped")   # 규격 PR #7의 흐름
DATA_ORIGINS = ("synthetic", "real")                                      # 대회 동안은 항상 synthetic

Channel = Literal["baemin", "coupangeats", "yogiyo", "naver_place"]
Sentiment = Literal["positive", "negative", "mixed", "neutral"]
Urgency = Literal["low", "medium", "high"]
CardKind = Literal["complaint", "promo"]

# 화면에 보여 줄 한글 이름. 코드 값은 영문, 화면 표시는 이 표로.
# 리뷰 주제(topics)의 한글 이름은 주제 사전을 가진 C3(services/review-insight)가 정합니다.
LABELS_KO = {
    "baemin": "배민",
    "coupangeats": "쿠팡이츠",
    "yogiyo": "요기요",
    "naver_place": "네이버 플레이스",
    "positive": "긍정",
    "neutral": "중립",
    "mixed": "긍정·부정 섞임",
    "negative": "부정",
    "low": "낮음",
    "medium": "보통",
    "high": "높음",
    "complaint": "불만 대응",
    "promo": "쿠폰 홍보",
}

# ── 카드 종류 → 생성기 표 ────────────────────────────────────────────
# 어느 생성기를 부를지는 모델의 함수 호출이 아니라 이 표로 정합니다 (결정안 2절).
# 값은 함수가 아니라 "생성기 이름"입니다. 이 파일이 마케팅 코드를 import하지 않아도 되고,
# 실제 함수와 이름을 이어 주는 일은 C5(API 연결)가 합니다.
#   reply_draft       불만 리뷰마다 사장님 말투의 답글 초안 (C6: tone.py 확장)
#   prevention_notice 재발 방지 공지, 플레이스 소식 형식 (C6: notice.py 재사용)
#   coupon_promo      쿠폰 홍보글 1개 (C6: coupon.py·event_plan.py 재사용)
CARD_GENERATORS: dict[str, tuple[str, ...]] = {
    "complaint": ("reply_draft", "prevention_notice"),
    "promo": ("coupon_promo",),
}

KST = timezone(timedelta(hours=9))
_QUARTER = re.compile(r"^(\d{4})Q([1-4])$")
_SEOUL_PERIOD = re.compile(r"^(\d{4})([1-4])$")


# ── 분기 표기 ────────────────────────────────────────────────────────
def quarter_label(quarter: str) -> str:
    """'2026Q2' -> '2026 2분기' (화면 표시용)."""
    match = _QUARTER.match(quarter) if isinstance(quarter, str) else None
    if not match:
        raise ValueError(f"분기는 'YYYYQn' 형식이어야 합니다. 예: 2026Q2 (받은 값: {quarter!r})")
    return f"{match.group(1)} {match.group(2)}분기"


def quarter_from_seoul_period(period: str) -> str:
    """상권분석(PR #12)의 기간 형식 '20262' -> 이 계약의 '2026Q2'. C4 어댑터가 씁니다."""
    match = _SEOUL_PERIOD.match(period) if isinstance(period, str) else None
    if not match:
        raise ValueError(f"상권분석 기간은 'YYYYQ' 형식이어야 합니다. 예: 20262 (받은 값: {period!r})")
    return f"{match.group(1)}Q{match.group(2)}"


# ── 검사 도구 (안 쓰는 이름은 밑줄) ──────────────────────────────────
def _need_text(owner: str, name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{owner}.{name}은(는) 비어 있지 않은 문자열이어야 합니다 (받은 값: {value!r})")


def _need_choice(owner: str, name: str, value: Any, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ValueError(f"{owner}.{name}은(는) {list(allowed)} 중 하나여야 합니다 (받은 값: {value!r})")


def _need_text_list(owner: str, name: str, values: Any) -> list[str]:
    # 문자열 하나를 목록으로 착각해 글자 단위로 쪼개지는 실수를 막는다.
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{owner}.{name}은(는) 문자열 목록이어야 합니다 (받은 값: {values!r})")
    for item in values:
        _need_text(owner, f"{name}의 항목", item)
    return list(values)


def _need_quarter(owner: str, name: str, value: Any) -> None:
    if not isinstance(value, str) or not _QUARTER.match(value):
        raise ValueError(
            f"{owner}.{name}은(는) 'YYYYQn' 형식이어야 합니다. 예: 2026Q2 "
            f"(받은 값: {value!r}. 상권분석의 '20262' 형식이면 quarter_from_seoul_period()로 바꾸세요)"
        )


def _kst_iso(owner: str, name: str, value: Any) -> str:
    """ISO 8601 문자열(또는 datetime)을 '한국 시간, 초 단위' 문자열로 맞춘다.

    시간대가 없으면 한국 시간으로 본다. 모두 +09:00으로 맞춰 두면 문자열 정렬이 곧 시간순이다.
    """
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(
                f"{owner}.{name}은(는) ISO 8601 형식이어야 합니다. 예: 2026-11-07T22:41:00+09:00 (받은 값: {value!r})"
            ) from None
    if not isinstance(value, datetime):
        raise ValueError(f"{owner}.{name}은(는) ISO 8601 문자열이어야 합니다 (받은 값: {value!r})")
    if value.tzinfo is None:
        value = value.replace(tzinfo=KST)
    return value.astimezone(KST).isoformat(timespec="seconds")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


_R = TypeVar("_R", bound="_Record")


class _Record:
    """5개 클래스가 같이 쓰는 JSON 변환. 직접 만들어 쓰지 않습니다."""

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))  # type: ignore[call-overload]

    @classmethod
    def from_dict(cls: type[_R], data: dict[str, Any]) -> _R:
        if not isinstance(data, dict):
            raise ValueError(f"{cls.__name__}.from_dict는 dict를 받습니다 (받은 값: {type(data).__name__})")
        all_names = {f.name for f in fields(cls)}  # type: ignore[arg-type]
        required = {
            f.name for f in fields(cls)  # type: ignore[arg-type]
            if f.default is MISSING and f.default_factory is MISSING
        }
        unknown = sorted(set(data) - all_names)
        if unknown:
            raise ValueError(f"{cls.__name__}에 없는 필드입니다: {unknown}. 필드 이름 오타인지 확인하세요.")
        missing = sorted(required - set(data))
        if missing:
            raise ValueError(f"{cls.__name__}에 꼭 필요한 필드가 없습니다: {missing}")
        return cls(**data)


# ── 1. 가게 ──────────────────────────────────────────────────────────
@dataclass
class StoreProfile(_Record):
    """가게 1곳. 시나리오는 서울의 배달 위주 음식점입니다.

    앞의 7개 필드는 C2(PR #14)의 store.json 그대로입니다. 뒤의 3개는 C4·C6이 채우는 선택 필드입니다.
    """

    store_id: str                                   # 예: "store_ongi"
    name: str                                       # 화면에 나오는 이름. 예: "온기한식 (가상)"
    business_type: str                              # 업종 코드. 예: "korean", "chicken", "cafe"
    business_type_name: str                         # 업종 이름. 예: "한식음식점"
    channels: list[str] = field(default_factory=list)   # 입점한 채널. CHANNELS 중에서
    menu: list[str] = field(default_factory=list)       # 메뉴 이름
    data_origin: str = "synthetic"                  # DATA_ORIGINS 중 하나
    city: str = "서울"
    area_name: str | None = None                    # 속한 상권. C4가 11/9에 정하기 전에는 None
    menu_prices: dict[str, int] = field(default_factory=dict)    # C6 쿠폰용. {"제육볶음 정식": 9500} 단위 원

    def __post_init__(self) -> None:
        owner = "StoreProfile"
        for name in ("store_id", "name", "business_type", "business_type_name", "city"):
            _need_text(owner, name, getattr(self, name))
        _need_choice(owner, "data_origin", self.data_origin, DATA_ORIGINS)
        if self.area_name is not None:
            _need_text(owner, "area_name", self.area_name)
        self.channels = _need_text_list(owner, "channels", self.channels)
        for channel in self.channels:
            _need_choice(owner, "channels의 항목", channel, CHANNELS)
        self.menu = _need_text_list(owner, "menu", self.menu)
        if not isinstance(self.menu_prices, dict):
            raise ValueError(f"{owner}.menu_prices는 {{메뉴 이름: 가격(원)}} dict여야 합니다")
        for menu_name, price in self.menu_prices.items():
            _need_text(owner, "menu_prices의 메뉴 이름", menu_name)
            if self.menu and menu_name not in self.menu:
                raise ValueError(f"{owner}.menu_prices에 menu에 없는 메뉴가 있습니다: {menu_name!r}")
            if isinstance(price, bool) or not isinstance(price, int) or price < 0:
                raise ValueError(f"{owner}.menu_prices[{menu_name!r}]는 0 이상의 정수(원)여야 합니다 (받은 값: {price!r})")


# ── 2. 상권 지표 ─────────────────────────────────────────────────────
@dataclass
class AnalysisSnapshot(_Record):
    """상권 지표 1건. 예: '저녁 시간대 추정매출, 전년 동기 대비 변화율'.

    기준 분기·추정 여부·출처는 지표마다 반드시 있습니다. 화면의 한 줄
    "기준: 2026 2분기 · 추정 · 출처 서울시"가 basis_label 입니다.
    """

    snapshot_id: str                    # 예: "snap_001". 카드의 근거 ID(snapshot_ids)가 가리킴
    area_name: str                      # 상권 이름
    metric_name: str                    # 사람이 읽는 지표 이름. 예: "저녁 시간대 추정매출 (전년 동기 대비 변화율)"
    value: float | int | None           # None이면 "자료 없음". 0과 다릅니다
    unit: str                           # "%", "원", "개" ...
    basis_quarter: str                  # 필수. "2026Q2"
    is_estimate: bool                   # 필수. 추정치이면 True
    source: str                         # 필수. 예: "서울시"
    compared_with_quarter: str | None = None   # 변화율의 비교 기준 분기. 예: "2025Q2"
    note: str = ""                      # 사람이 읽는 메모 (자료 없음의 이유, 자리표시자 표시 등)

    def __post_init__(self) -> None:
        owner = "AnalysisSnapshot"
        for name in ("snapshot_id", "area_name", "metric_name", "unit", "source"):
            _need_text(owner, name, getattr(self, name))
        _need_quarter(owner, "basis_quarter", self.basis_quarter)
        if self.compared_with_quarter is not None:
            _need_quarter(owner, "compared_with_quarter", self.compared_with_quarter)
        if not isinstance(self.is_estimate, bool):
            raise ValueError(f"{owner}.is_estimate는 True/False여야 합니다 (받은 값: {self.is_estimate!r})")
        if self.value is not None:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)) or not math.isfinite(self.value):
                raise ValueError(
                    f"{owner}.value는 숫자 또는 None이어야 합니다 (받은 값: {self.value!r}). "
                    "자료가 없으면 NaN이 아니라 None을 쓰세요."
                )
        if not isinstance(self.note, str):
            raise ValueError(f"{owner}.note는 문자열이어야 합니다")

    @property
    def basis_label(self) -> str:
        """화면 표시용 한 줄. 예: '기준: 2026 2분기 · 추정 · 출처 서울시'."""
        parts = [f"기준: {quarter_label(self.basis_quarter)}"]
        if self.is_estimate:
            parts.append("추정")
        parts.append(f"출처 {self.source}")
        return " · ".join(parts)


# ── 3. 리뷰 ──────────────────────────────────────────────────────────
@dataclass
class ReviewRecord(_Record):
    """리뷰 1건과 그 분류 결과.

    앞의 11개 필드는 C2(PR #14)의 reviews.json 그대로입니다. 뒤의 4개(sentiment·topics·negative_topics·urgency)가
    분류(C3) 결과이고, 분류 전에는 None 또는 빈 목록입니다.
    """

    review_id: str                      # 예: "rv_ongi_001"
    store_id: str
    text: str                           # 리뷰 원문
    created_at: str                     # 작성 시각. ISO 8601 "문자열", 한국 시간으로 맞춰 저장됨
    channel: str | None = None          # CHANNELS 중 하나. 붙여넣기에서 모르면 None
    rating: int | None = None           # 별점 1~5. 없으면 None
    input_method: str = "sample"        # INPUT_METHODS 중 하나
    pii_masked: bool = False            # 개인정보를 가렸으면 True
    order_ref: str | None = None        # 주문 연결. 이번 데모에서는 항상 None
    status: str = "new"                 # REVIEW_STATUSES 중 하나
    data_origin: str = "synthetic"      # DATA_ORIGINS 중 하나. 화면의 "합성 데이터" 표시 근거
    sentiment: str | None = None        # 분류 결과: 감정. SENTIMENTS 중 하나
    topics: list[str] = field(default_factory=list)            # 분류 결과: 주제 사전의 주제 id 전체 (예: "missing_item")
    negative_topics: list[str] = field(default_factory=list)   # 그중 불만으로 잡힌 것 (topics의 부분집합)
    urgency: str | None = None          # 분류 결과: 긴급도. URGENCIES 중 하나. 아직 만드는 파트가 없음

    def __post_init__(self) -> None:
        owner = "ReviewRecord"
        for name in ("review_id", "store_id", "text"):
            _need_text(owner, name, getattr(self, name))
        self.created_at = _kst_iso(owner, "created_at", self.created_at)
        if self.channel is not None:
            _need_choice(owner, "channel", self.channel, CHANNELS)
        if self.rating is not None and (
            isinstance(self.rating, bool) or not isinstance(self.rating, int) or not 1 <= self.rating <= 5
        ):
            raise ValueError(f"{owner}.rating은 1~5 정수 또는 None이어야 합니다 (받은 값: {self.rating!r})")
        _need_choice(owner, "input_method", self.input_method, INPUT_METHODS)
        if not isinstance(self.pii_masked, bool):
            raise ValueError(f"{owner}.pii_masked는 True/False여야 합니다 (받은 값: {self.pii_masked!r})")
        if self.order_ref is not None:
            _need_text(owner, "order_ref", self.order_ref)
        _need_choice(owner, "status", self.status, REVIEW_STATUSES)
        _need_choice(owner, "data_origin", self.data_origin, DATA_ORIGINS)
        if self.sentiment is not None:
            _need_choice(owner, "sentiment", self.sentiment, SENTIMENTS)
        self.topics = _need_text_list(owner, "topics", self.topics)
        self.negative_topics = _need_text_list(owner, "negative_topics", self.negative_topics)
        outside = [t for t in self.negative_topics if t not in self.topics]
        if outside:
            raise ValueError(f"{owner}.negative_topics는 topics 안에 있어야 합니다 (topics에 없는 것: {outside})")
        if self.urgency is not None:
            _need_choice(owner, "urgency", self.urgency, URGENCIES)

    @property
    def created_datetime(self) -> datetime:
        """created_at을 datetime으로. 시간대는 한국 시간(+09:00)."""
        return datetime.fromisoformat(self.created_at)


# ── 4. 말투 ──────────────────────────────────────────────────────────
@dataclass
class ToneProfile(_Record):
    """사장님 말투 1벌과 쓰면 안 되는 표현."""

    tone_id: str                        # 예: "tone_bora"
    store_id: str
    style_description: str              # 말투를 한두 문장으로. 모델에게 주는 설명이기도 함
    example_sentences: list[str] = field(default_factory=list)   # 사장님이 실제로 쓰는 문장 예시
    forbidden_phrases: list[str] = field(default_factory=list)   # 글에 들어가면 안 되는 표현

    def __post_init__(self) -> None:
        owner = "ToneProfile"
        for name in ("tone_id", "store_id", "style_description"):
            _need_text(owner, name, getattr(self, name))
        self.example_sentences = _need_text_list(owner, "example_sentences", self.example_sentences)
        self.forbidden_phrases = _need_text_list(owner, "forbidden_phrases", self.forbidden_phrases)


# ── 5. 추천 카드 ─────────────────────────────────────────────────────
@dataclass
class RecommendationCard(_Record):
    """추천 카드 1장. 어떤 카드를 띄울지는 서버 규칙(C5)이, reason_text는 모델이 씁니다.

    근거 ID는 서버가 넣고 모델은 바꾸지 않습니다. 근거가 하나도 없는 카드는 만들 수 없습니다.
    """

    card_id: str                        # 예: "card_001"
    store_id: str
    kind: str                           # CARD_KINDS 중 하나. CARD_GENERATORS의 키
    reason_text: str                    # 이 카드를 띄운 이유 한 문장
    review_ids: list[str] = field(default_factory=list)     # 근거 리뷰 (ReviewRecord.review_id)
    snapshot_ids: list[str] = field(default_factory=list)   # 근거 지표 (AnalysisSnapshot.snapshot_id)

    def __post_init__(self) -> None:
        owner = "RecommendationCard"
        for name in ("card_id", "store_id", "reason_text"):
            _need_text(owner, name, getattr(self, name))
        _need_choice(owner, "kind", self.kind, CARD_KINDS)
        self.review_ids = _need_text_list(owner, "review_ids", self.review_ids)
        self.snapshot_ids = _need_text_list(owner, "snapshot_ids", self.snapshot_ids)
        if not self.review_ids and not self.snapshot_ids:
            raise ValueError(f"{owner}은(는) 근거(review_ids 또는 snapshot_ids)가 하나 이상 있어야 합니다")

    @property
    def evidence_ids(self) -> list[str]:
        """근거 ID 전체 (리뷰 ID + 지표 ID)."""
        return self.review_ids + self.snapshot_ids


# ── JSON 파일 읽기/쓰기 ──────────────────────────────────────────────
def dump_json(records: _Record | list[_Record], path: str | Path) -> None:
    """record 하나 또는 목록을 한글이 깨지지 않게 JSON 파일로 씁니다."""
    payload = [r.to_dict() for r in records] if isinstance(records, list) else records.to_dict()
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(cls: type[_R], path: str | Path) -> _R | list[_R]:
    """dump_json의 반대. 파일이 목록이면 목록을, 객체 하나면 record 하나를 돌려줍니다."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [cls.from_dict(item) for item in data]
    return cls.from_dict(data)


__all__ = [
    "StoreProfile", "AnalysisSnapshot", "ReviewRecord", "ToneProfile", "RecommendationCard",
    "CARD_GENERATORS", "CARD_KINDS", "CHANNELS", "SENTIMENTS", "URGENCIES", "INPUT_METHODS", "REVIEW_STATUSES",
    "DATA_ORIGINS", "LABELS_KO",
    "quarter_label", "quarter_from_seoul_period", "dump_json", "load_json",
]
