"""마케팅 가설 — ctx(리뷰·카드·상권 지표)와 설문 답변에서 코드가 뽑는다. AI 호출 없음.

build_hypotheses(ctx, answers) -> 최대 3개, 아래 순서가 우선순위다.
  H_LATE       불만 중 '늦은 배달' 표현이 2건 이상
  H_AREA_DROP  상권 지표(시간대별 매출)가 하락(또는 수치 확정 전)
  H_STORE_ONLY 상권은 하락이 아니면서 반복 불만 카드가 있음(가게만의 문제 의심)
  H_REPEAT     반복 불만 묶음(카드, review_ids 2건 이상)이 있음
  H_LEFTOVER   설문 목표가 '남는 재료 처리'
"""

import re

from marketing_survey.models import Hypothesis

_LATE = re.compile(r"늦게|늦었|배달.{0,4}늦|오래\s*걸")


def _late_delivery_reviews(reviews):
    return [r for r in reviews if _LATE.search(r.text)]


def _area_drop_snapshot(snapshots):
    """값이 음수거나(하락) 아직 확정 전(None)인 상권 지표 — 특정 시간대 낱말(예: '저녁')에
    의존하지 않는다(가게가 바뀌면 metric_name 도 바뀔 수 있어서)."""
    for s in snapshots:
        if s.value is None or (isinstance(s.value, (int, float)) and s.value < 0):
            return s
    return None


def window_label(metric_name: str | None) -> str:
    """snapshot.metric_name 에서 시간대 낱말만 뽑는다(예: '저녁 시간대 추정매출...' -> '저녁').
    시간대 낱말이 없거나 지표가 없으면 '전체'."""
    if metric_name:
        match = re.match(r"^(\S+)\s*시간대", metric_name)
        if match:
            return match.group(1)
    return "전체"


def _repeat_complaint_card(cards):
    for c in cards:
        if c.kind == "complaint" and len(c.review_ids) >= 2:
            return c
    return None


def build_hypotheses(ctx, answers) -> list[Hypothesis]:
    candidates: list[Hypothesis] = []

    late_reviews = _late_delivery_reviews(ctx.reviews)
    if len(late_reviews) >= 2:
        candidates.append(Hypothesis(
            id="H_LATE", title="배달 지연 의심",
            evidence_ids=[r.review_id for r in late_reviews],
            question="요즘 저녁에 배달 대행이 잘 안 잡히나요?",
            choices=["예", "아니요"],
        ))

    area_snap = _area_drop_snapshot(ctx.snapshots)
    repeat_card = _repeat_complaint_card(ctx.cards)

    if area_snap is not None:
        window = window_label(area_snap.metric_name)
        note = "" if area_snap.value is not None else " (수치 확정 전)"
        candidates.append(Hypothesis(
            id="H_AREA_DROP", title=f"상권 {window} 매출 하락{note}",
            evidence_ids=[area_snap.snapshot_id],
            question=f"최근 {window} 주문이 줄었다고 느끼시나요?",
            choices=["예", "아니요"],
        ))
    elif repeat_card is not None:
        candidates.append(Hypothesis(
            id="H_STORE_ONLY", title="가게만의 문제 의심",
            evidence_ids=[repeat_card.card_id],
            question="최근 메뉴·가격·포장을 바꾼 적 있나요?",
            choices=["예", "아니요"],
        ))

    if repeat_card is not None:
        candidates.append(Hypothesis(
            id="H_REPEAT", title="반복 불만",
            evidence_ids=list(repeat_card.review_ids),
            question="이 문제를 먼저 해결하고 싶으신가요?",
            choices=["예", "아니요"],
        ))

    if answers.goal == "남는 재료 처리":
        candidates.append(Hypothesis(
            id="H_LEFTOVER", title="남는 재료 처리",
            evidence_ids=[f"survey:goal={answers.goal}"],
            question="주로 남는 메뉴는?",
            choices=list(ctx.store.menu),
        ))

    return candidates[:3]
