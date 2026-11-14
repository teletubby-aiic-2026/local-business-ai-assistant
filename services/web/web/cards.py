"""② 추천 카드 2장 (C5 참조 구현).

C5 담당(김진수)의 구현이 오면 build_cards 만 바꿔 끼운다. 인터페이스는 메인 세션 프롬프트 4절 제안 그대로:

    build_cards(insight: dict, snapshots: list[AnalysisSnapshot], store_id: str) -> list[RecommendationCard]

규칙 (어떤 카드를 띄울지는 규칙이 정하고, 모델은 이유 문장만 쓴다)
- 카드 ⓐ complaint: insight["top_issue_id"] 가 가리키는 묶음 (가장 큰 반복 묶음 1개). 없으면 만들지 않는다.
- 카드 ⓑ promo: 지표를 **고정된 우선순위로 먼저 하나 고르고**, 그 값이 기준 이하(하락)일 때만 만든다.
  고른 지표가 하락이 아니면 다른 지표를 찾아 내려가지 않는다 (숫자를 먼저 정하고 데이터를 맞추지 않음).
  우선순위: CARD_B_SNAPSHOT_ID → snap_evening_sales_yoy(저녁 17~21시) → 단위 % 인 첫 '추정매출' 지표.
- 이유 문장: 사실 카드(F1·F2)를 근거로 쓰고 shared.answer_check 를 통과해야 쓴다. 화면에는 [F1] 표시를 지운다.
  mock 은 고정 문장, live 는 HCX-005 한 문장(1회 재시도) → 실패하면 고정 문장.
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
REASON_OK = "HCX-005 (검사기 통과)"   # 모델 문장이 규칙 검사를 통과했을 때의 reason_source


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
    rounds: int = 0                                       # live 에서 모델에게 이유를 쓰게 한 횟수 (재시도 라운드)
    measures: dict = field(default_factory=dict)          # 불만 카드: 재발 방지 조치 {options, default} (C6 목록)

    def to_dict(self) -> dict:
        return {
            "card": self.card.to_dict(), "title": self.title, "reason_source": self.reason_source,
            "checked_text": self.checked_text, "facts": self.facts, "evidence": self.evidence,
            "problems": self.problems, "measures": self.measures,
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
        "keep": [band] if band else [],   # 이유 문장이 그대로 써야 하는 표기 (C7 규칙, 검사기는 이 키를 보지 않음)
    }
    fixed = f"{name} 불만이 {count}건 반복됐어요 [F1]"
    if all_in_band:
        fixed = f"{name} 불만이 {count}건 반복됐고, 모두 {band}에 들어왔어요 [F1]"
    evidence = [{"type": "review", "id": e["review_id"], "text": e["quote"]} for e in group.get("evidence", [])]
    card = RecommendationCard(
        card_id=f"card_{_store_key(store_id)}_a", store_id=store_id, kind="complaint",
        reason_text=strip_citations(fixed), review_ids=list(group["review_ids"]),
    )
    # 강조점: 같은 불만이 다시 안 생기게 하는 공지가 먼저, 답글은 함께 나오는 것 (결정안 덧붙임 2, 11/10)
    return CardPlan(card=card, title=f"{name} {count}건 반복 → 재발 방지 공지 + 답글", facts=[fact],
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
        # 상권 이름과 시간대는 바꾸면 안 된다 (11/10 live 9차: "장승배기역 4번 출구 상권", 17~24시 누락)
        "keep": [f"{snap.area_name} 상권", *re.findall(r"\d{1,2}~\d{1,2}시", snap.metric_name)],
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


_LOOSE_CITE = re.compile(r"[\[［]\s*(F\d+)\s*[\]］]")


def normalize_citations(text: str) -> str:
    """'[ F1 ]'·'［F1］'처럼 괄호 안 띄어쓰기·전각 괄호만 '[F1]'로 맞춘다. 내용은 바꾸지 않는다 (검사기는 고치지 않음)."""
    return _LOOSE_CITE.sub(r"[\1]", text or "")


def _fact_value_words(facts: list[dict]) -> list[str]:
    """사실 카드 숫자가 문장에 들어갈 때의 모양: 3 → '3건', -19.31 → '19.31'."""
    words = []
    for fact in facts:
        for v in fact.get("values", []):
            value = v.get("value")
            if isinstance(value, (int, float)):
                number = f"{abs(value):g}" if float(value).is_integer() else f"{abs(value):.2f}"
                words.append(number + ("건" if v.get("unit") == "건" else ""))
    return words


_HOURS = re.compile(r"(\d{1,2})\s*시?\s*(?:부터|~|-|–|에서)\s*(\d{1,2})\s*시")


def _same_hours(text: str) -> str:
    """'17시부터 21시'·'17시~21시'·'17~21시'를 같은 표기('17~21시')로 맞춘다."""
    return _HOURS.sub(r"\1~\2시", text)


REASON_MAX_CHARS = 180
_PREDICTION = re.compile(r"수 있(?:어요|습니다|을 거)|예상|가능성|높아질|늘어날|개선될|회복될|이어질")


def reason_problems(text: str, facts: list[dict]) -> list[dict]:
    """모델 이유 문장 규칙 검사: 검사기 통과 + 인용 표시 + 사실 카드 숫자를 실제로 씀.

    숫자 검사를 더한 이유: 검사기는 '카드에 없는 숫자'를 막지만 숫자가 없는 일반론
    ("문제를 해결하면 만족도가 높아질 수 있어요")은 통과시킨다. 이유 문장은 근거 숫자를 말해야 한다.
    """
    if not text:
        return [{"type": "empty"}]
    problems = list(check_answer(text, facts)["problems"])
    if not _CITE.search(text):
        problems.append({"type": "no_citation"})
    words = _fact_value_words(facts)
    if words and not any(w in text for w in words):
        problems.append({"type": "no_fact_value", "detail": " 또는 ".join(words)})
    # 길이·예측 (11/10 live 8차: 문단 4개짜리 글, "브랜드 이미지를 개선할 수 있습니다"가 검사기를 통과함)
    plain = strip_citations(text)
    sentences = [s for s in re.split(r"(?<=[.!?。])\s+|\n+", plain) if s.strip()]
    if len(plain) > REASON_MAX_CHARS or len(sentences) > 3:
        problems.append({"type": "too_long", "detail": f"두 문장, {REASON_MAX_CHARS}자 안으로 써요"})
    if "\n\n" in plain.strip():
        problems.append({"type": "too_long", "detail": "한 문단으로 써요 (같은 말을 두 번 하지 않아요)"})
    flat = _same_hours(plain).replace(" ", "")
    missing = [k for f in facts for k in f.get("keep", []) if k and _same_hours(k).replace(" ", "") not in flat]
    if missing:
        problems.append({"type": "label_changed", "detail": "근거 카드 표기를 그대로 써요: " + ", ".join(f"'{k}'" for k in missing)})
    found = _PREDICTION.search(plain)
    if found:
        problems.append({"type": "prediction", "detail": f"앞날 예측('{found.group(0)}')은 빼요"})
    # 변화율(%)을 퍼센트포인트(%p)로 쓰면 뜻이 달라진다 (11/10 live 4차: "19.31%p 감소")
    units = {v.get("unit") for f in facts for v in f.get("values", [])}
    if "%" in units and re.search(r"\d\s*(%p|％p|퍼센트포인트|%포인트)", text):
        problems.append({"type": "unit_mismatch", "detail": "변화율은 %로 써요 (%p 아님)"})
    return problems


def model_reason_failed(plan: CardPlan) -> bool:
    """live 에서 모델 이유 문장이 검사에 걸리거나 호출이 실패해 고정 문장으로 돌아간 카드."""
    return plan.reason_source.startswith("HCX-005 ") and "→ 고정 문장" in plan.reason_source


def apply_writer(plan: CardPlan, writer: ReasonWriter) -> CardPlan:
    """모델 문장으로 바꿔 보고, 규칙 검사를 통과하지 못하면 고정 문장을 그대로 둔다 (재시도는 writer 안에서)."""
    plan.rounds += 1
    try:
        text = writer(plan.card.kind, plan.facts, plan.checked_text)
    except Exception as exc:  # 네트워크·키 문제: 데모가 멈추지 않게 고정 문장으로
        plan.reason_source = f"HCX-005 실패({exc.__class__.__name__}) → 고정 문장"
        return plan
    problems = reason_problems(text or "", plan.facts)
    if problems:
        plan.reason_source = "HCX-005 검사 불통과 → 고정 문장"
        plan.problems = problems
        return plan
    plan.checked_text = text
    plan.card.reason_text = strip_citations(text)
    plan.reason_source = REASON_OK
    plan.problems = []
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
            apply_writer(plan, writer)
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
