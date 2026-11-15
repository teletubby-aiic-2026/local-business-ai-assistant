"""가게 레지스트리 — server 가 ?store=store_id 로 가게를 고를 때 쓴다.

실제 데이터(StoreProfile·리뷰·상권 지표·카드)가 갖춰진 가게만 "available=True" 다. 다른 팀
브랜치(scripts/pull_team_data.py 가 아는 store_basak·store_mongle)는 이 가게들의 id 는 알지만
아직 이 프로젝트가 쓸 수 있는 형태(shared.contracts.StoreProfile 등)의 데이터가 없어
available=False 로만 둔다 — 메뉴·가격을 지어내지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass

from c6.contract import C6Context, build_context
from c6.dummy import OWNER_REPLIES, POLICIES
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

_AVAILABLE: dict[str, StoreEntry] = {
    SAMPLE_STORE.store_id: StoreEntry(
        store_id=SAMPLE_STORE.store_id, name=SAMPLE_STORE.name, available=True, ctx=_ONGI_CTX,
    ),
}

# scripts/pull_team_data.py 가 아는 다른 팀 가게 id — 이름·메뉴·가격 데이터가 아직 여기 없다.
_KNOWN_NOT_AVAILABLE = ("store_basak", "store_mongle")
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
