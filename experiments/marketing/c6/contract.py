"""C6 컨텍스트 — shared.contracts 기준.

ctx 는 계약 dataclass 인스턴스를 그대로 담는다.
계약에 없는 것(예전 답글·정책)만 c6.dummy 에서 채우고 needs_input 에 기록한다.
기본 실행 가게는 store_ongi (발표용), 카드는 shared.sample_scenario 의 것을 쓴다.
"""
from __future__ import annotations

from shared.contracts import (
    AnalysisSnapshot,
    RecommendationCard,
    ReviewRecord,
    StoreProfile,
    ToneProfile,
)
from shared.sample_scenario import (
    SAMPLE_CARDS,
    SAMPLE_REVIEWS,
    SAMPLE_SNAPSHOTS,
    SAMPLE_STORE,
    SAMPLE_TONE,
)


class C6Context:
    """C6 생성기가 쓰는 컨텍스트."""

    __slots__ = (
        "store", "reviews", "tone", "cards", "snapshots",
        "owner_replies", "policies", "needs_input",
    )

    def __init__(
        self, *,
        store: StoreProfile,
        reviews: list[ReviewRecord],
        tone: ToneProfile,
        cards: list[RecommendationCard],
        snapshots: list[AnalysisSnapshot],
        owner_replies: list[str],
        policies: list[dict],
        needs_input: list[str],
    ) -> None:
        self.store = store
        self.reviews = reviews
        self.tone = tone
        self.cards = cards
        self.snapshots = snapshots
        self.owner_replies = owner_replies
        self.policies = policies
        self.needs_input = list(needs_input)


def build_context(
    *,
    store: StoreProfile | None = None,
    reviews: list[ReviewRecord] | None = None,
    tone: ToneProfile | None = None,
    cards: list[RecommendationCard] | None = None,
    snapshots: list[AnalysisSnapshot] | None = None,
    owner_replies: list[str] | None = None,
    policies: list[dict] | None = None,
) -> C6Context:
    """계약 dataclass 인스턴스로 C6Context 를 만든다. 없는 것은 더미/샘플로 채운다."""
    from c6.dummy import OWNER_REPLIES, POLICIES

    needs: list[str] = []

    if store is None:
        store = SAMPLE_STORE
    if reviews is None:
        reviews = list(SAMPLE_REVIEWS)
        needs.append("팀 데이터에 없음: 리뷰(ReviewRecord)")
    if tone is None:
        tone = SAMPLE_TONE
        needs.append("팀 데이터에 없음: 사장님 말투(ToneProfile)")
    if cards is None:
        cards = list(SAMPLE_CARDS)
        needs.append("팀 데이터에 없음: 추천 카드(RecommendationCard)")
    if snapshots is None:
        snapshots = list(SAMPLE_SNAPSHOTS)
        needs.append("팀 데이터에 없음: 상권 지표(AnalysisSnapshot)")
    if owner_replies is None:
        owner_replies = list(OWNER_REPLIES)
        needs.append("팀 데이터에 없음: 사장님 예전 답글")
    if policies is None:
        policies = list(POLICIES)
        needs.append("팀 데이터에 없음: 가게 정책")

    return C6Context(
        store=store, reviews=reviews, tone=tone,
        cards=cards, snapshots=snapshots,
        owner_replies=owner_replies, policies=policies,
        needs_input=needs,
    )
