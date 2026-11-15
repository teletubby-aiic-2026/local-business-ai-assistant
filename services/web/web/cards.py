"""② 추천 카드 2장 (C5 참조 구현).

C5 담당(김진수)의 구현이 오면 build_cards 만 바꿔 끼운다. 인터페이스는 메인 세션 프롬프트 4절 제안 그대로:

    build_cards(insight: dict, snapshots: list[AnalysisSnapshot], store_id: str) -> list[RecommendationCard]

규칙 (어떤 카드를 띄울지는 규칙이 정하고, 모델은 이유 문장만 쓴다)
- 카드 ⓐ complaint: insight["top_issue_id"] 가 가리키는 묶음 (가장 큰 반복 묶음 1개). 없으면 만들지 않는다.
- 카드 ⓑ promo: 지표를 **고정된 우선순위로 먼저 하나 고르고**, 그 값이 기준 이하(하락)일 때만 만든다.
  고른 지표가 하락이 아니면 다른 지표를 찾아 내려가지 않는다 (숫자를 먼저 정하고 데이터를 맞추지 않음).
  우선순위: CARD_B_SNAPSHOT_ID → snap_evening_sales_yoy(저녁 17~21시) → 단위 % 인 첫 '추정매출' 지표.
  가게·리뷰(store·reviews)를 함께 받으면 쿠폰 메뉴의 손님 칭찬 근거(F3)를 붙인다: 가격 있는 메뉴 가운데 칭찬 리뷰에 가장 많이
  언급된 메뉴와 건수. C6(c6/promo.py)가 쿠폰 메뉴를 고르는 것과 같은 함수(shared.praise.pick_praised_menu)를 쓴다.
- 이유 문장: 사실 카드(F1·F2·F3)를 근거로 쓰고 shared.answer_check 를 통과해야 쓴다. 화면에는 [F1] 표시를 지운다.
  mock 은 고정 문장, live 는 HCX-005 한 문장(1회 재시도) → 실패하면 고정 문장.
  칭찬 근거(F3)가 붙은 카드 ⓑ 는 live 에서 모델이 상권 지표 문장만 쓰고, 칭찬 근거 한 줄(메뉴·건수)은 코드가 끼워 넣는다 (apply_writer).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from shared.answer_check import check_answer
from shared.contracts import AnalysisSnapshot, RecommendationCard
from shared.praise import menu_mentions, pick_praised_menu, praise_reviews

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
    # 카드 ⓑ + 손님 칭찬 근거일 때만 채운다: 모델은 상권 지표(model_facts)만 보고 model_fixed 를 참고해 쓰고, 칭찬 근거 한 줄
    # (code_line)은 코드가 끼워 넣는다 (apply_writer). 비어 있으면 facts·checked_text 전체를 모델에게 준다.
    model_facts: list[dict] | None = None
    model_fixed: str = ""
    code_line: str = ""

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
PRAISE_EVIDENCE_MAX = 3      # 화면 근거로 보여 주는 칭찬 리뷰 수
PRAISE_TEXT_MAX = 120        # 근거 칩에 넣는 리뷰 글 길이 (붙여넣은 리뷰는 1000자까지 올 수 있다)
NOT_TOP_WORDS = ("가장", "제일", "최다", "1위")   # 언급 수가 같거나 더 많은 메뉴가 있을 때 이유 문장에 쓰면 안 되는 말


def praised_coupon_menu(store, reviews) -> dict | None:
    """쿠폰에 쓸 메뉴와 그 칭찬 근거. 가게·리뷰가 없거나 칭찬 리뷰에 그 메뉴 언급이 없으면 None (카드는 예전 그대로).

    C6(c6/promo.py)가 쿠폰 메뉴를 고르는 것과 같은 함수·같은 입력이어야 한다 → 카드가 말한 메뉴 == 홍보글의 쿠폰 메뉴.
    돌려주는 값: pick_praised_menu 의 값 + "alone"(메뉴판 전체에서 혼자 가장 많이 언급됨) + "evidence"(화면 근거, 최대 3건).
    리뷰는 ReviewRecord 든 dict 든 받는다 (shared.praise 와 같다).
    """
    if store is None or reviews is None:
        return None
    reviews = list(reviews)
    picked = pick_praised_menu(store.menu, reviews, priced=store.menu_prices)
    if not picked or picked["count"] < 1:
        return None
    # '가장 많이'는 메뉴판 전체에서 혼자 1등일 때만 쓴다. 가격 없는 메뉴가 더 많이 언급됐을 수도 있다 (그 메뉴는 쿠폰에 못 씀)
    counts = [row["count"] for row in menu_mentions(store.menu, praise_reviews(reviews))]
    alone = picked["count"] == max(counts) and counts.count(picked["count"]) == 1
    by_id = {_field(r, "review_id"): r for r in reviews}
    evidence = [{"type": "praise", "id": rid, "text": _clip(str(_field(by_id[rid], "text") or "")), "menu": picked["menu"],
                 "rating": _field(by_id[rid], "rating")} for rid in picked["review_ids"][:PRAISE_EVIDENCE_MAX]]
    return {**picked, "alone": alone, "evidence": evidence}


def _field(review, name: str):
    return review.get(name) if isinstance(review, dict) else getattr(review, name, None)


def _clip(text: str, limit: int = PRAISE_TEXT_MAX) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _praise_fact(praise: dict) -> tuple[dict, str]:
    """사실 카드 F3 와 고정 문장의 한 줄. 혼자 가장 많이 언급된 메뉴일 때만 '가장 많이'라고 쓴다 (같은 수면 사실과 다르다)."""
    menu, count = praise["menu"], praise["count"]
    if praise["alone"]:
        text = f"손님 칭찬 리뷰에서 가장 많이 언급된 메뉴는 {menu}, {count}건"
        line = f"손님 칭찬 리뷰에서 {menu} 언급이 {count}건으로 가장 많아요 [F3]"
    else:
        text = f"손님 칭찬 리뷰에 {menu} 언급 {count}건 (언급 수가 같거나 더 많은 다른 메뉴가 있음)"
        line = f"손님 칭찬 리뷰에 {menu} 언급이 {count}건 있어요 [F3]"
    fact = {
        "id": "F3", "topic": "review_praise", "status": "available", "text": text,
        # 메뉴 이름은 글자 값으로도 둔다: 이름에 숫자가 있어도('1인 정식') 검사기가 통계 숫자로 읽지 않는다
        "values": [{"label": "쿠폰 메뉴를 언급한 칭찬 리뷰", "value": count, "unit": "건"},
                   {"label": "쿠폰 메뉴", "value": menu}],
        "keep": [menu],   # 이유 문장에 메뉴 이름이 그대로 있어야 한다
    }
    if not praise["alone"]:
        fact["avoid"] = list(NOT_TOP_WORDS)   # reason_problems 가 이 말을 막는다
    return fact, line


def _promo_plan(snapshots: list[AnalysisSnapshot], store_id: str, preferred_id: str, threshold: float,
                store=None, reviews=None) -> CardPlan | None:
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
    market_line = f"{snap.area_name} 상권의 {metric}: {period}, 전년 동기 대비 {shown:.2f}% 감소 [F2]"
    fixed = f"{market_line}\n{target} 다시 부르는 쿠폰 홍보를 제안해요."
    evidence = [{"type": "snapshot", "id": snap.snapshot_id, "text": f"{metric} {snap.value:+.2f}%",
                 "basis": snap.basis_label, "note": snap.note}]
    card_id = f"card_{_store_key(store_id)}_b"
    # 손님 칭찬 근거(F3)가 있으면 상권 지표와 함께 쓴다: 제목·이유·근거에 쿠폰 메뉴와 칭찬 건수
    praise = praised_coupon_menu(store, reviews)
    if praise:
        praise_fact, praise_line = _praise_fact(praise)
        menu = praise["menu"]
        both = f"{market_line}\n{praise_line}\n{target} 다시 부르는 {menu} 쿠폰 홍보를 제안해요."
        # 메뉴 이름 때문에 고정 문장이 규칙에 걸리면(금지 표현이 든 이름, 너무 긴 이름) 칭찬 근거 없이 예전 카드로 둔다
        if not reason_problems(both, [fact, praise_fact]):
            card = RecommendationCard(
                card_id=card_id, store_id=store_id, kind="promo", reason_text=strip_citations(both),
                review_ids=list(praise["review_ids"]), snapshot_ids=[snap.snapshot_id],
            )
            return CardPlan(card=card, title=f"{metric} 하락 → '{menu}' 쿠폰 홍보", facts=[fact, praise_fact],
                            checked_text=both, reason_source="고정 문장", evidence=evidence + praise["evidence"],
                            model_facts=[fact], model_fixed=fixed, code_line=praise_line)
    card = RecommendationCard(
        card_id=card_id, store_id=store_id, kind="promo",
        reason_text=strip_citations(fixed), snapshot_ids=[snap.snapshot_id],
    )
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


_CITE_GROUP = re.compile(r"((?:\[F\d+\]\s*)+)")


def _cited_pieces(text: str):
    """(글 조각, 그 조각 바로 뒤에 붙은 카드 번호들). 검사기가 숫자를 카드와 맞춰 보는 단위와 같다 (한 줄 안에서 인용 표시 앞까지)."""
    for line in text.splitlines():
        parts = _CITE_GROUP.split(line)
        for index in range(0, len(parts), 2):
            yield parts[index], re.findall(r"F\d+", parts[index + 1]) if index + 1 < len(parts) else []


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
    for fact in facts:   # 근거 카드마다 그 카드의 숫자를 하나는 써야 한다 (카드가 한 장이면 예전과 같다)
        words = _fact_value_words([fact])
        if words and not any(w in text for w in words):
            problems.append({"type": "no_fact_value", "detail": " 또는 ".join(words)})
    if len(facts) > 1:   # 근거 카드가 여러 장이면(카드 ⓑ: 상권 지표 F2 + 손님 칭찬 F3) 빠진 카드 없이 모두 인용해야 한다
        cited = set(re.findall(r"\[(F\d+)\]", text))
        for fact in facts:
            if fact["id"] not in cited:
                problems.append({"type": "promised_card_left_out", "detail": fact["id"]})
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
    # 근거 카드가 쓰지 말라고 한 말 (칭찬 언급 수가 같은 메뉴가 있는데 '가장 많이'라고 하면 사실과 다르다)
    for word in dict.fromkeys(w for f in facts for w in f.get("avoid", []) if w and w in plain):
        problems.append({"type": "forbidden_phrase", "detail": word})
    # 근거 카드가 여러 장일 때: 한 카드를 인용한 문장에 다른 카드의 표기를 섞으면 뜻이 바뀐다. 숫자·인용이 맞아 검사기는 통과한다
    # (11/16 live: "17시부터 24시까지 제육볶음 정식 매출이 19.31% 감소했어요[F2]" — 상권 통계가 메뉴 매출이 됨,
    #  "17시부터 24시까지 제육볶음 정식 칭찬 리뷰가 1건[F3]" — 리뷰에 없는 시간대가 붙음)
    if len(facts) > 1:
        for piece, cited in _cited_pieces(text):
            flat_piece = _same_hours(piece).replace(" ", "")
            for fact in facts if cited else ():   # 인용이 없는 문장(할 일)은 메뉴·시간대를 함께 말해도 된다
                mixed = [k for k in fact.get("keep", []) if k and _same_hours(k).replace(" ", "") in flat_piece]
                if fact["id"] not in cited and mixed:
                    marks = "".join(f"[{c}]" for c in cited)
                    problems.append({"type": "label_changed", "detail": f"{marks} 문장에는 " + ", ".join(f"'{k}'" for k in mixed)
                                     + f"을(를) 넣지 않아요 ([{fact['id']}] 문장에만 써요)"})
    # 변화율(%)을 퍼센트포인트(%p)로 쓰면 뜻이 달라진다 (11/10 live 4차: "19.31%p 감소")
    units = {v.get("unit") for f in facts for v in f.get("values", [])}
    if "%" in units and re.search(r"\d\s*(%p|％p|퍼센트포인트|%포인트)", text):
        problems.append({"type": "unit_mismatch", "detail": "변화율은 %로 써요 (%p 아님)"})
    return problems


def model_reason_failed(plan: CardPlan) -> bool:
    """live 에서 모델 이유 문장이 검사에 걸리거나 호출이 실패해 고정 문장으로 돌아간 카드."""
    return plan.reason_source.startswith("HCX-005 ") and "→ 고정 문장" in plan.reason_source


_AFTER_CITE = re.compile(r"[ \t]*[.!?。]+")
_SENTENCE_END = re.compile(r"[.!?。]+(?=\s|$)|\n")


def insert_code_line(text: str, line: str, fact_id: str) -> str:
    """모델 문장에서 fact_id 를 인용한 문장 바로 뒤에 코드가 쓴 한 줄을 끼운다 (문장 가운데는 자르지 않는다).
    그 문장이 글의 끝이면 맨 뒤에 붙인다."""
    mark = f"[{fact_id}]"
    at = text.rfind(mark)
    cut = len(text)
    if at >= 0:
        end = at + len(mark)
        dot = _AFTER_CITE.match(text, end)
        if dot:                                                  # "…감소했어요[F2]. 저녁 손님을…"
            cut = dot.end()
        elif text[:at].rstrip().endswith((".", "!", "?", "。")) or text[end:].lstrip(" \t")[:1] in ("", "\n"):
            cut = end                                            # "…감소했어요. [F2] 저녁…" / 줄 끝의 인용
        else:                                                    # "…감소했으므로[F2], 쿠폰 홍보를…" → 그 문장이 끝난 뒤
            closed = _SENTENCE_END.search(text, end)
            cut = closed.end() if closed else len(text)
    head, rest = text[:cut].rstrip(), text[cut:].strip()
    return head + "\n" + line + ("\n" + rest if rest else "")


def apply_writer(plan: CardPlan, writer: ReasonWriter) -> CardPlan:
    """모델 문장으로 바꿔 보고, 규칙 검사를 통과하지 못하면 고정 문장을 그대로 둔다 (재시도는 writer 안에서).

    카드 ⓑ 에 손님 칭찬 근거가 있으면 모델에게는 상권 지표 카드만 주고(예전 홍보 카드와 같은 요청), 칭찬 근거 한 줄은 코드가
    끼워 넣는다. 두 근거를 함께 주면 모델이 섞어 쓴다 — 11/16 live: "17시부터 24시까지 제육볶음 정식 매출이 19.31%
    감소했어요[F2]"가 검사기를 통과했다 (상권 통계가 메뉴 매출이 됨). 메뉴·건수는 코드가 쓰면 틀릴 수 없다.
    """
    plan.rounds += 1
    facts = plan.model_facts if plan.model_facts is not None else plan.facts
    try:
        text = writer(plan.card.kind, facts, plan.model_fixed or plan.checked_text)
    except Exception as exc:  # 네트워크·키 문제: 데모가 멈추지 않게 고정 문장으로
        plan.reason_source = f"HCX-005 실패({exc.__class__.__name__}) → 고정 문장"
        return plan
    problems = reason_problems(text or "", facts)
    if not problems and plan.code_line:
        text = insert_code_line(text, plan.code_line, facts[-1]["id"])
        problems = reason_problems(text, plan.facts)   # 끼워 넣은 글 전체를 이 카드의 모든 근거로 다시 본다
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
               writer: ReasonWriter | None = None, store=None, reviews=None) -> list[CardPlan]:
    """store(StoreProfile)·reviews(ReviewRecord 목록): C6 에 넘기는 것과 같은 값을 주면 카드 ⓑ 에 손님 칭찬 근거(F3)를 붙인다.
    주지 않으면 예전과 같은 카드(F2 만)다."""
    plans = [p for p in (_complaint_plan(insight, store_id),
                         _promo_plan(snapshots, store_id, preferred_id, threshold, store, reviews)) if p]
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
