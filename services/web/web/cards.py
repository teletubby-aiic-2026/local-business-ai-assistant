"""② 추천 카드 2장 (C5 참조 구현).

C5 담당(김진수)의 구현이 오면 build_cards 만 바꿔 끼운다. 인터페이스는 메인 세션 프롬프트 4절 제안 그대로:

    build_cards(insight: dict, snapshots: list[AnalysisSnapshot], store_id: str) -> list[RecommendationCard]

규칙 (어떤 카드를 띄울지는 규칙이 정하고, 모델은 이유 문장만 쓴다)
- 카드 ⓐ complaint: insight["top_issue_id"] 가 가리키는 묶음 (가장 큰 반복 묶음 1개). 없으면 만들지 않는다.
- 카드 ⓑ promo: 지표를 **고정된 우선순위로 먼저 하나 고르고**, 그 값이 기준 이하(하락)일 때만 만든다.
  고른 지표가 하락이 아니면 다른 지표를 찾아 내려가지 않는다 (숫자를 먼저 정하고 데이터를 맞추지 않음).
  우선순위: CARD_B_SNAPSHOT_ID → snap_evening_sales_yoy(저녁 17~21시) → 단위 % 인 첫 '추정매출' 지표.
- 이유 문장: 사실 카드(F1·F2)를 근거로 쓰고 shared.answer_check 를 통과해야 쓴다. 화면에는 [F1] 표시를 지운다.
  mock·replay 는 고정 문장, live 는 HCX-005 한 문장(1회 재시도) → 실패하면 고정 문장.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from shared.answer_check import check_answer
from shared.contracts import AnalysisSnapshot, RecommendationCard

EVENING_ID = "snap_evening_sales_yoy"
_CITE = re.compile(r"\s*\[F\d+\]")
_QUARTER = re.compile(r"^(\d{4})Q([1-4])$")

ReasonWriter = Callable[[str, list[dict], str], str]   # (카드 종류, 사실 카드, 고정 문장) -> 모델 문장(인용 포함)


@dataclass
class CardPlan:
    """카드 1장 + 화면에 필요한 근거 설명."""
    card: RecommendationCard
    title: str
    facts: list[dict]                  # 검사기에 넘긴 사실 카드
    checked_text: str                  # 검사기를 통과한 문장 ([F1] 포함)
    reason_source: str                 # "고정 문장" | "HCX-005" | "HCX-005 실패 → 고정 문장"
    evidence: list[dict] = field(default_factory=list)   # 화면 근거 칩
    problems: list[dict] = field(default_factory=list)   # 모델 문장이 걸린 이유 (있으면)

    def to_dict(self) -> dict:
        return {
            "card": self.card.to_dict(), "title": self.title, "reason_source": self.reason_source,
            "checked_text": self.checked_text, "facts": self.facts, "evidence": self.evidence,
            "problems": self.problems,
        }


def quarter_words(quarter: str) -> str:
    """'2026Q2' → '2026년 2분기' (검사기가 분기를 이 모양으로 읽는다)."""
    match = _QUARTER.match(quarter or "")
    return f"{match.group(1)}년 {match.group(2)}분기" if match else quarter


def strip_citations(text: str) -> str:
    return _CITE.sub("", text).strip()


def short_metric(name: str) -> str:
    """지표 이름에서 '전년 동기 대비 변화율'을 떼고, ' · ' 뒤의 범위 설명은 괄호로 붙인다.

    '저녁 시간대(17~24시) 추정매출 전년 동기 대비 변화율 · 두 분기 공통 업종'
      → '저녁 시간대(17~24시) 추정매출(두 분기 공통 업종)'
    """
    parts = [p.strip() for p in name.split(" · ")]
    main = re.sub(r"\s*\(?\s*전년 동기 대비 변화율\s*\)?", "", parts[0]).strip()
    rest = [re.sub(r"\s*전년 동기 대비 변화율\s*", "", p).strip() for p in parts[1:]]
    rest = [p for p in rest if p]
    return f"{main}({', '.join(rest)})" if rest else main


def pick_card_b_snapshot(snapshots: list[AnalysisSnapshot], preferred_id: str = "") -> AnalysisSnapshot | None:
    by_id = {s.snapshot_id: s for s in snapshots}
    for wanted in (preferred_id, EVENING_ID):
        if wanted and wanted in by_id:
            return by_id[wanted]
    for snap in snapshots:
        if snap.unit == "%" and "추정매출" in snap.metric_name:
            return snap
    return None


def _store_key(store_id: str) -> str:
    return store_id[len("store_"):] if store_id.startswith("store_") else store_id


# ── 카드 ⓐ ──────────────────────────────────────────────────────────
def _complaint_plan(insight: dict, store_id: str) -> CardPlan | None:
    top_id = insight.get("top_issue_id")
    group = next((g for g in insight.get("groups", []) if g["issue_id"] == top_id), None)
    if not group:
        return None
    name, count = group["topic_name"], group["review_count"]
    band = group.get("main_time_band")
    all_in_band = bool(band) and (group.get("time_bands") or {}).get(band) == count
    fact = {
        "id": "F1", "topic": "review_issue", "status": "available",
        "text": f"{name} 불만 리뷰 {count}건, 반복 묶음" + (f", 주로 {band}" if band else ""),
        "values": [{"label": f"{name} 불만 리뷰", "value": count, "unit": "건"}],
    }
    fixed = f"{name} 불만이 {count}건 반복됐어요 [F1]"
    if all_in_band:
        fixed = f"{name} 불만이 {count}건 반복됐고, 모두 {band}에 들어왔어요 [F1]"
    evidence = [{"type": "review", "id": e["review_id"], "text": e["quote"]} for e in group.get("evidence", [])]
    card = RecommendationCard(
        card_id=f"card_{_store_key(store_id)}_a", store_id=store_id, kind="complaint",
        reason_text=strip_citations(fixed), review_ids=list(group["review_ids"]),
    )
    return CardPlan(card=card, title=f"{name} {count}건 → 답글 + 재발 방지 공지", facts=[fact],
                    checked_text=fixed, reason_source="고정 문장", evidence=evidence)


# ── 카드 ⓑ ──────────────────────────────────────────────────────────
def _promo_plan(snapshots: list[AnalysisSnapshot], store_id: str, preferred_id: str, threshold: float) -> CardPlan | None:
    snap = pick_card_b_snapshot(snapshots, preferred_id)
    if snap is None or snap.value is None or snap.value > threshold:
        return None
    metric = short_metric(snap.metric_name)
    period = quarter_words(snap.basis_quarter)
    compared = quarter_words(snap.compared_with_quarter) if snap.compared_with_quarter else "전년 동기"
    shown = round(abs(float(snap.value)), 2)
    fact = {
        "id": "F2", "topic": "market_sales_change", "status": "available",
        "text": f"{snap.area_name} 상권, {period} {metric}, {compared} 대비. 출처 {snap.source}",
        "values": [{"label": f"{metric} 전년 동기 대비 변화율", "value": round(float(snap.value), 2), "unit": "%"}],
    }
    evening = snap.snapshot_id == EVENING_ID or "17~21" in snap.metric_name or "저녁" in snap.metric_name
    target = "저녁 손님을" if evening else "손님을"
    fixed = (f"{snap.area_name} 상권의 {metric}: {period}, 전년 동기 대비 {shown:.2f}% 감소 [F2]\n"
             f"{target} 다시 부르는 쿠폰 홍보를 제안해요.")
    card = RecommendationCard(
        card_id=f"card_{_store_key(store_id)}_b", store_id=store_id, kind="promo",
        reason_text=strip_citations(fixed), snapshot_ids=[snap.snapshot_id],
    )
    evidence = [{"type": "snapshot", "id": snap.snapshot_id, "text": f"{metric} {snap.value:+.2f}%",
                 "basis": snap.basis_label, "note": snap.note}]
    return CardPlan(card=card, title=f"{metric} 하락 → 쿠폰 홍보", facts=[fact], checked_text=fixed,
                    reason_source="고정 문장", evidence=evidence)


def _apply_writer(plan: CardPlan, writer: ReasonWriter) -> CardPlan:
    """모델 문장으로 바꿔 보고, 검사기를 통과하지 못하면 고정 문장을 그대로 둔다 (1회 재시도는 writer 안에서)."""
    try:
        text = writer(plan.card.kind, plan.facts, plan.checked_text)
    except Exception as exc:  # 네트워크·키 문제: 데모가 멈추지 않게 고정 문장으로
        plan.reason_source = f"HCX-005 실패({exc.__class__.__name__}) → 고정 문장"
        return plan
    result = check_answer(text or "", plan.facts)
    if not text or not result["ok"] or not _CITE.search(text):
        plan.reason_source = "HCX-005 검사 불통과 → 고정 문장"
        plan.problems = result["problems"] or [{"type": "no_citation"}]
        return plan
    plan.checked_text = text
    plan.card.reason_text = strip_citations(text)
    plan.reason_source = "HCX-005 (검사기 통과)"
    return plan


def plan_cards(insight: dict, snapshots: list[AnalysisSnapshot], store_id: str, *,
               preferred_id: str = "", threshold: float = -5.0,
               writer: ReasonWriter | None = None) -> list[CardPlan]:
    plans = [p for p in (_complaint_plan(insight, store_id),
                         _promo_plan(snapshots, store_id, preferred_id, threshold)) if p]
    for plan in plans:
        fixed = check_answer(plan.checked_text, plan.facts)
        if not fixed["ok"]:   # 고정 문장이 검사기에 걸리면 코드 버그다. 화면에 숨기지 않는다.
            plan.problems = fixed["problems"]
            plan.reason_source = "고정 문장 (검사기 경고)"
        elif writer is not None:
            _apply_writer(plan, writer)
    return plans


def build_cards(insight: dict, snapshots: list[AnalysisSnapshot], store_id: str) -> list[RecommendationCard]:
    """C5 인터페이스 (프롬프트 4절). 이유는 고정 문장."""
    return [p.card for p in plan_cards(insight, snapshots, store_id)]


def why_no_card_b(snapshots: list[AnalysisSnapshot], preferred_id: str, threshold: float) -> str | None:
    """카드 ⓑ 가 없을 때 화면에 보여 줄 이유."""
    snap = pick_card_b_snapshot(snapshots, preferred_id)
    if not snapshots:
        return "상권 지표 파일(C4)이 없어 카드 ⓑ 를 만들지 않았어요."
    if snap is None:
        return "추정매출 변화율 지표가 없어 카드 ⓑ 를 만들지 않았어요."
    if snap.value is None:
        return f"'{snap.metric_name}' 값이 '자료 없음'이라 카드 ⓑ 를 만들지 않았어요."
    if snap.value > threshold:
        return f"'{snap.metric_name}' 값({snap.value:+.2f}%)이 기준({threshold:+.0f}%)보다 높아 카드 ⓑ 를 만들지 않았어요."
    return None
