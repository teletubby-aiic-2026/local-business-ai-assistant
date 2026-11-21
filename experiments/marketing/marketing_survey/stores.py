"""가게 레지스트리 — server 가 ?store=store_id 로 가게를 고를 때 쓴다.

실제 데이터(StoreProfile·리뷰·상권 지표·카드)가 갖춰진 가게만 "available=True" 다.
5차 회의(11/18) '사장님 한 명이 가게 여러 개' 결정으로 store_basak(바삭치킨)·store_mongle(몽글카페)도 쓸 수 있다:
가게·리뷰는 리뷰 분석 서비스의 합성 자료, 상권 지표는 서울시 공식 원본으로 만든 가게별 파일, 가격·말투·예전 답글은
shared.store_profiles 의 가정값이다 (온기한식의 가격과 같은 성격). 등록하지 않은 id 는 고를 수 없다(서버가 404).
"""
from __future__ import annotations

from dataclasses import dataclass

from c6.contract import C6Context, build_context
from c6.dummy import OWNER_REPLIES, POLICIES
from shared import store_header, store_profiles
from shared.contracts import CHANNELS, StoreProfile
from shared.sample_scenario import (
    SAMPLE_CARDS, SAMPLE_REVIEWS, SAMPLE_SNAPSHOTS, SAMPLE_STORE, SAMPLE_TONE,
)


@dataclass(frozen=True)
class StoreEntry:
    store_id: str
    name: str
    available: bool
    ctx: C6Context | None = None


_ONGI_CTX = build_context(
    store=SAMPLE_STORE, reviews=list(SAMPLE_REVIEWS), tone=SAMPLE_TONE,
    cards=list(SAMPLE_CARDS), snapshots=list(SAMPLE_SNAPSHOTS),
    owner_replies=OWNER_REPLIES, policies=POLICIES,
)

DEFAULT_STORE_ID = SAMPLE_STORE.store_id



def _shared_ctx(store_id: str) -> C6Context:
    """바삭치킨·몽글카페 (11/18). 공용 가게 정보(shared.store_profiles)로 만든 컨텍스트."""
    bundle = store_profiles.BUNDLES[store_id]
    return build_context(
        store=store_profiles.store_profile(store_id), reviews=store_profiles.review_records(store_id), tone=bundle.tone,
        cards=store_profiles.sample_cards(store_id), snapshots=store_profiles.load_snapshots(store_id),
        owner_replies=list(bundle.owner_replies), policies=[dict(p) for p in store_profiles.COMMON_POLICIES],
    )


_AVAILABLE: dict[str, StoreEntry] = {
    SAMPLE_STORE.store_id: StoreEntry(
        store_id=SAMPLE_STORE.store_id, name=SAMPLE_STORE.name, available=True, ctx=_ONGI_CTX,
    ),
}
for _sid in ("store_basak", "store_mongle"):
    _AVAILABLE[_sid] = StoreEntry(store_id=_sid, name=store_profiles.BUNDLES[_sid].name, available=True, ctx=_shared_ctx(_sid))

# 이름은 알지만 데이터가 아직 없는 가게 id. 11/18 부터 비어 있다 (바삭치킨·몽글카페가 쓸 수 있게 됨).
_KNOWN_NOT_AVAILABLE: tuple[str, ...] = ()
# 데이터 없는 가게의 화면 표시 이름(id 대신). 모르는 id 는 "다른 가게".
_NOT_AVAILABLE_LABELS = {"store_basak": "바삭", "store_mongle": "몽글"}
_NOT_AVAILABLE_FALLBACK = "다른 가게"
_NO_DATA_SUFFIX = " (데모 데이터 없음)"
_VIRTUAL_MARK = "(가상)"


def _display_name(name: str) -> str:
    """화면 표시용 이름. '(가상)' 표시만 떼고, 데이터(StoreProfile.name)는 그대로 둔다."""
    return name.replace(_VIRTUAL_MARK, "").strip()


def list_stores() -> list[dict]:
    """화면 가게 알약 목록. available=False 인 가게는 고를 수 없다(데모 데이터 없음)."""
    stores = [
        {"store_id": e.store_id, "name": _display_name(e.name), "available": True}
        for e in _AVAILABLE.values()
    ]
    stores += [
        {
            "store_id": store_id,
            "name": _NOT_AVAILABLE_LABELS.get(store_id, _NOT_AVAILABLE_FALLBACK) + _NO_DATA_SUFFIX,
            "available": False,
        }
        for store_id in _KNOWN_NOT_AVAILABLE
    ]
    return stores


# ── 사장님이 직접 등록한 가게 (6차 회의 11/20) ─────────────────────────
# 비서 화면 서버가 등록 가게의 요청마다 X-IC26-Store-Profile 헤더(shared/store_header.py)로 가게 프로필을 보낸다.
# server.py 의 미들웨어가 검사해서 여기 넣는다 (프로세스 메모리, 크기 상한 LRU). 서비스가 다시 켜져도 다음 요청의 헤더로 바로 안다.
# 컨텍스트: 등록한 이름·업종·메뉴·가격 + 기본 말투·공통 정책. 리뷰·카드·상권 지표·예전 답글은 없다 (빈 목록 — 샘플로 채우지 않음).
# 리뷰가 필요한 기능은 리뷰 0건일 때의 문구로, 상권 지표가 필요한 기능은 지표 없음 문구로 답한다.
_registered = store_header.Registry()


def register(profile: dict) -> None:
    """검사한 등록 가게 프로필 (store_header.decode 의 결과)을 목록에 넣는다."""
    _registered.put(profile)


def _registered_ctx(profile: dict) -> C6Context:
    bundle = store_profiles.registered_bundle({
        "store_id": profile["store_id"], "name": profile["name"], "business_type_name": profile["business_type_name"],
        "profile": {"industry_code": profile["industry_code"], "business_status": profile["business_status"],
                    "channels": profile["channels"], "location": profile["location"], "area": profile["area"],
                    "menus": profile["menus"]}})
    data = store_header.store_json(profile, CHANNELS)
    store = StoreProfile.from_dict({k: v for k, v in data.items() if k in StoreProfile.__dataclass_fields__}
                                   | {"area_name": bundle.area_name or None, "menu_prices": dict(bundle.menu_prices)})
    return build_context(store=store, reviews=[], tone=bundle.tone, cards=[], snapshots=[], owner_replies=[],
                         policies=[dict(p) for p in store_profiles.COMMON_POLICIES])


def is_registered(store_id: str) -> bool:
    return store_id not in _AVAILABLE and _registered.get(store_id) is not None


def get_ctx(store_id: str) -> C6Context | None:
    """해당 가게의 Context. 데이터가 없는 가게면 None(서버가 에러로 바꾼다). 등록 가게는 요청마다 새로 만든다 (값이 바뀔 수 있음)."""
    entry = _AVAILABLE.get(store_id)
    if entry:
        return entry.ctx
    profile = _registered.get(store_id)
    return _registered_ctx(profile) if profile is not None else None
