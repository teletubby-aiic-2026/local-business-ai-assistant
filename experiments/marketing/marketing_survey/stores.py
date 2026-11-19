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
from shared import store_profiles
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


def get_ctx(store_id: str) -> C6Context | None:
    """해당 가게의 Context. 데이터가 없는 가게면 None(서버가 에러로 바꾼다)."""
    entry = _AVAILABLE.get(store_id)
    return entry.ctx if entry else None
