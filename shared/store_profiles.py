"""가게 세 곳(온기한식·바삭치킨·몽글카페)의 공용 정보 — 5차 회의(11/18) '사장님 한 명이 가게 여러 개' 결정.

비서 화면(services/web)과 맞춤 마케팅(experiments/marketing)이 같이 읽는다. 가게마다 다른 것만 모았다.

- 가게 기본 정보(이름·업종·메뉴)는 리뷰 분석 서비스의 합성 자료(services/review-insight/data/synthetic/<가게>/store.json)가 원본이다.
- 상권 지표: 온기한식은 data/scenario/snapshot_2026Q2.json(공통 업종 합계), 다른 두 가게는 data/scenario/<가게>/snapshot_2026Q2.json
  (한 업종, scripts/reproduce_store_snapshots.py 가 서울시 공식 원본으로 만듦).
- 상권 분석 기본 조건(역·업종·상권·분기 코드)은 상권 서비스의 표(onboarding_stations.json·onboarding_industries.json)에 있는 값이다.
- 메뉴 가격·사장님 말투·예전 답글은 이 프로젝트가 정한 가정값(합성)이다. 온기한식은 shared.sample_scenario 의 것을 그대로 쓴다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from shared.contracts import AnalysisSnapshot, RecommendationCard, ReviewRecord, StoreProfile, ToneProfile
from shared.sample_scenario import SAMPLE_STORE, SAMPLE_TONE

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIO = REPO_ROOT / "data" / "scenario"
SYNTHETIC = REPO_ROOT / "services" / "review-insight" / "data" / "synthetic"

DEFAULT_STORE_ID = "store_ongi"
STORE_IDS = ("store_ongi", "store_basak", "store_mongle")

# 답글 정책은 가게와 상관없는 문장이다 (c6.dummy.POLICIES 와 같은 뜻). 금전 보상 약속 금지는 모든 가게에 같다.
COMMON_POLICIES = [
    {"policy_id": "P1", "text": "누락 품목은 다음 주문 요청사항에 적어 주시면 챙겨 드리겠습니다."},
    {"policy_id": "P2", "text": "환불은 배달앱 고객센터를 통해 안내해 드리고 있습니다."},
    {"policy_id": "P3", "text": "리뷰 답글에 금전 보상(쿠폰·할인·무료 제공 등)을 약속하지 않습니다."},
]


@dataclass(frozen=True)
class StoreBundle:
    store_id: str
    name: str                     # 합성 자료의 이름 그대로 ("바삭치킨 (가상)")
    short_name: str               # 화면·답글 서명용 ("바삭치킨")
    business_type: str
    business_type_name: str       # 업종 이름 (상권 서비스의 업종 이름과 같게)
    industry_code: str            # 상권 서비스 업종 코드 (onboarding_industries.json)
    station_id: str               # 상권 서비스 역 id (onboarding_stations.json)
    station_name: str
    area_code: str                # 상권 코드 (서울시 상권분석서비스)
    area_name: str
    snapshot_path: Path
    menu_prices: dict[str, int]
    tone: ToneProfile
    owner_replies: tuple[str, ...] = ()
    signature: str = ""
    extras: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        """서랍·상권 화면의 기본 조건 이름 ("바삭치킨 · 상도역 · 치킨전문점")."""
        return f"{self.short_name} · {self.station_name} · {self.business_type_name}"

    def public(self) -> dict:
        """화면에 보내도 되는 칸 (가게 고르기 목록)."""
        return {"store_id": self.store_id, "name": self.short_name, "business_type_name": self.business_type_name,
                "area_name": self.area_name, "station_name": self.station_name}


_BASAK_TONE = ToneProfile(
    tone_id="tone_basak", store_id="store_basak",
    style_description="~해요체로 밝고 짧게. 사과는 한 문장으로 분명히 하고, 다음 주문에 무엇을 확인하겠다고 말한다.",
    example_sentences=[
        "소스가 빠져서 많이 아쉬우셨죠, 정말 죄송해요.",
        "다음 주문부터는 포장 마감 전에 소스·무 개수를 한 번 더 셀게요.",
        "바삭하게 드셨다니 저희도 힘이 나요, 또 찾아 주세요.",
    ],
    forbidden_phrases=["배달 기사님 탓", "플랫폼 문제", "원래 그렇습니다", "100% 보상", "규정상"],
)
_MONGLE_TONE = ToneProfile(
    tone_id="tone_mongle", store_id="store_mongle",
    style_description="~해요체로 다정하게. 기다리게 한 일은 먼저 사과하고, 매장에서 바꾸는 점을 구체적으로 한 가지 말한다.",
    example_sentences=[
        "음료를 오래 기다리게 해 드려 죄송해요.",
        "점심시간에는 주문 순서표를 한 번 더 확인하며 만들게요.",
        "소금빵을 맛있게 드셨다니 기뻐요, 또 들러 주세요.",
    ],
    forbidden_phrases=["손님이 많아서 어쩔 수 없", "원래 그렇습니다", "100% 보상", "규정상"],
)

BUNDLES: dict[str, StoreBundle] = {
    "store_ongi": StoreBundle(
        store_id="store_ongi", name=SAMPLE_STORE.name, short_name="온기한식", business_type="korean",
        business_type_name="한식음식점", industry_code="CS100001",
        station_id="kric-e12f817979cd-S1107-0740", station_name="장승배기역",
        area_code="3110826", area_name="장승배기역 4번",
        snapshot_path=SCENARIO / "snapshot_2026Q2.json",
        menu_prices=dict(SAMPLE_STORE.menu_prices), tone=SAMPLE_TONE, signature="온기한식 드림"),
    "store_basak": StoreBundle(
        store_id="store_basak", name="바삭치킨 (가상)", short_name="바삭치킨", business_type="chicken",
        business_type_name="치킨전문점", industry_code="CS100007",
        station_id="kric-e12f817979cd-S1107-0739", station_name="상도역",
        area_code="3110836", area_name="상도역 5번",
        snapshot_path=SCENARIO / "store_basak" / "snapshot_2026Q2.json",
        # 가정값: 쿠폰 손익 계산용. 합성 자료에는 가격이 없다
        menu_prices={"후라이드": 19000, "양념치킨": 20000, "반반": 20000, "순살 치킨": 21000, "치즈볼": 5000, "콜라": 2500},
        tone=_BASAK_TONE, signature="바삭치킨 드림",
        owner_replies=(
            "안녕하세요 고객님 :) 바삭하게 맛있게 드셨다니 정말 기뻐요. 다음에도 갓 튀긴 치킨으로 기다릴게요. 바삭치킨 드림",
            "안녕하세요 고객님 :) 소스가 빠져서 아쉬우셨죠, 정말 죄송해요. 포장 마감 전에 소스 개수를 한 번 더 확인할게요. 바삭치킨 드림",
            "안녕하세요 고객님 :) 배달이 늦어 많이 기다리셨죠, 죄송해요. 주문이 몰리는 시간에는 조리 순서를 더 꼼꼼히 챙길게요. 바삭치킨 드림",
        )),
    "store_mongle": StoreBundle(
        store_id="store_mongle", name="몽글카페 (가상)", short_name="몽글카페", business_type="cafe",
        business_type_name="커피-음료", industry_code="CS100010",
        station_id="kric-e12f817979cd-S1107-0740", station_name="장승배기역",
        area_code="3120154", area_name="장승배기역",
        snapshot_path=SCENARIO / "store_mongle" / "snapshot_2026Q2.json",
        menu_prices={"아메리카노": 4000, "바닐라라떼": 5000, "딸기 케이크": 6500, "소금빵": 3500, "크로플": 5500},
        tone=_MONGLE_TONE, signature="몽글카페 드림",
        owner_replies=(
            "안녕하세요 :) 소금빵을 맛있게 드셨다니 저희도 기분이 좋아요. 다음에도 따뜻하게 구워 둘게요. 몽글카페 드림",
            "안녕하세요 :) 음료를 오래 기다리게 해 드려 죄송해요. 점심시간에는 주문 순서를 한 번 더 확인하며 만들게요. 몽글카페 드림",
            "안녕하세요 :) 케이크 모양이 흐트러져 속상하셨죠, 죄송해요. 포장할 때 고정 받침을 꼭 넣을게요. 몽글카페 드림",
        )),
}


def get(store_id: str | None) -> StoreBundle | None:
    return BUNDLES.get(store_id or "")


def known(store_id: str | None) -> bool:
    return (store_id or "") in BUNDLES


def menu_prices(store_id: str | None) -> dict[str, int]:
    bundle = get(store_id)
    return dict(bundle.menu_prices) if bundle else {}


def c6_extras(store_id: str | None) -> dict:
    """C6 build_context 에 더 넘길 가게별 말투·예전 답글·정책. 온기한식은 비워 둔다 (C6 기본값 = 지금까지와 같은 결과)."""
    bundle = get(store_id)
    if bundle is None or store_id == DEFAULT_STORE_ID:
        return {}
    return {"tone": bundle.tone, "owner_replies": list(bundle.owner_replies), "policies": [dict(p) for p in COMMON_POLICIES]}


def load_snapshots(store_id: str) -> list[AnalysisSnapshot]:
    bundle = get(store_id)
    if bundle is None or not bundle.snapshot_path.exists():
        return []
    data = json.loads(bundle.snapshot_path.read_text(encoding="utf-8"))
    return [AnalysisSnapshot.from_dict(d) for d in (data if isinstance(data, list) else [data])]


@lru_cache(maxsize=8)
def _synthetic(store_id: str) -> tuple[dict, list[dict], dict]:
    folder = SYNTHETIC / store_id
    store = json.loads((folder / "store.json").read_text(encoding="utf-8"))
    reviews = json.loads((folder / "reviews.json").read_text(encoding="utf-8"))
    labels = {x["review_id"]: x for x in json.loads((folder / "labels.json").read_text(encoding="utf-8"))}
    return store, reviews, labels


def store_profile(store_id: str) -> StoreProfile:
    """합성 store.json + 가정 가격 + 상권 이름 → StoreProfile. 온기한식은 shared.sample_scenario 의 SAMPLE_STORE 와 같은 값."""
    bundle = BUNDLES[store_id]
    store, _, _ = _synthetic(store_id)
    names = StoreProfile.__dataclass_fields__
    data = {k: v for k, v in store.items() if k in names}
    data.update(menu_prices=dict(bundle.menu_prices), area_name=bundle.area_name)
    return StoreProfile.from_dict(data)


def review_records(store_id: str) -> list[ReviewRecord]:
    """합성 리뷰 + 정답표(labels.json) → ReviewRecord (맞춤 마케팅의 C6 컨텍스트용. 비서 화면은 리뷰 분석 서비스의 실시간 분류를 쓴다)."""
    _, reviews, labels = _synthetic(store_id)
    names = ReviewRecord.__dataclass_fields__
    out = []
    for review in reviews:
        data = {k: v for k, v in review.items() if k in names}
        label = labels.get(review["review_id"]) or {}
        topics = []
        for hit in label.get("expected_topics", []):
            topic = hit.get("topic") if isinstance(hit, dict) else hit
            if topic and topic not in topics:
                topics.append(topic)
        negative = [h["topic"] for h in label.get("expected_topics", [])
                    if isinstance(h, dict) and h.get("polarity") == "negative" and h.get("topic") in topics]
        data.update(sentiment=label.get("expected_sentiment"), topics=topics, negative_topics=negative)
        if label:
            data["status"] = "analyzed"
        out.append(ReviewRecord.from_dict(data))
    return out


def sample_cards(store_id: str) -> list[RecommendationCard]:
    """C6 컨텍스트용 카드 두 장: 가장 많은 부정 주제 묶음(답글·안내문)과 상권 저녁 매출(쿠폰 홍보)."""
    reviews = review_records(store_id)
    counts: dict[str, list[str]] = {}
    for r in reviews:
        for topic in r.negative_topics:
            counts.setdefault(topic, []).append(r.review_id)
    top = max(counts.items(), key=lambda kv: (len(kv[1]), kv[0]))[1] if counts else []
    key = store_id.removeprefix("store_")
    cards = [RecommendationCard(card_id=f"card_{key}_a", store_id=store_id, kind="complaint",
                                reason_text=f"같은 불만이 {len(top)}건 반복됐어요.", review_ids=top[:5])]
    snaps = load_snapshots(store_id)
    if snaps:
        cards.append(RecommendationCard(card_id=f"card_{key}_b", store_id=store_id, kind="promo",
                                        reason_text=f"이 상권의 저녁 시간대 추정매출이 전년 동기 대비 {abs(snaps[0].value):.2f}% 줄었습니다.",
                                        snapshot_ids=[s.snapshot_id for s in snaps]))
    return cards


def public_list(store_ids: list[str] | tuple[str, ...] = STORE_IDS) -> list[dict]:
    return [BUNDLES[s].public() for s in store_ids if s in BUNDLES]
