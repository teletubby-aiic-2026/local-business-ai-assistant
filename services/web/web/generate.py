"""③ 결과물 생성 (C6, PR #16) 연결.

- live: c6.registry.run_card 를 그대로 부른다. 키는 직접 넘긴다. (config.get_api_key()는 키가 없으면 input()으로
  묻기 때문에 서버 안에서 부르면 요청이 멈춘다. 그래서 쓰지 않는다.)
- 키가 없을 때(mock): 시험용 실행. 김수현의 C6 저장 예시 c6/replay/c6_cache_best.json 을 우리 카드에 맞춰 보여 준다.
  저장 예시의 이유 문장은 쓰지 않는다(홍보 카드는 '-X%' 자리표시자). 글(drafts)만 쓰고 출처를 표시한다.
  실제 AI 결과가 아니다.

C6 코드는 고치지 않는다. CardResult·DraftOutput 은 c6.output 을 그대로 쓴다(최소 변경, shared 이동은 보류).
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

from shared.contracts import AnalysisSnapshot, RecommendationCard, ReviewRecord, StoreProfile

SEED_RELATIVE = Path("c6") / "replay" / "c6_cache_best.json"


class GenerateError(RuntimeError):
    pass


def ensure_marketing_on_path(marketing_dir: Path) -> bool:
    """c6·clova·config 는 experiments/marketing 아래의 최상위 모듈이다. shared 를 먼저 import한 뒤에 경로를 더한다."""
    import shared.contracts  # noqa: F401  이 저장소의 shared 가 먼저 잡히게
    import shared.answer_check  # noqa: F401
    path = str(Path(marketing_dir).resolve())
    if not (Path(path) / "c6" / "registry.py").exists():
        return False
    if path not in sys.path:
        sys.path.append(path)
    return True


def c6_available(marketing_dir: Path) -> bool:
    if not ensure_marketing_on_path(marketing_dir):
        return False
    try:
        import c6.registry  # noqa: F401
    except Exception:
        return False
    return True


# ── 키 없을 때: 김수현 저장본 ───────────────────────────────────────
def load_seed(marketing_dir: Path) -> dict[str, dict]:
    """종류(complaint/promo) → CardResult dict."""
    path = Path(marketing_dir) / SEED_RELATIVE
    if not path.exists():
        return {}
    return {item["kind"]: item for item in json.loads(path.read_text(encoding="utf-8"))}


def adapt_seed(seed: dict, card: RecommendationCard) -> dict | None:
    """저장본 CardResult 를 우리 카드에 맞춘다. 글은 그대로, 카드 ID·이유·근거 ID만 바꾼다.

    불만 카드는 저장본이 우리 카드의 리뷰를 모두 다룰 때만 쓴다 (붙여넣기로 묶음이 바뀌면 저장본이 맞지 않음).
    """
    result = copy.deepcopy(seed)
    sample_ids = {d["target_review_id"] for d in result["drafts"] if d.get("target_review_id")}
    if card.kind == "complaint" and not set(card.review_ids) <= sample_ids:
        return None
    result["drafts"] = [d for d in result["drafts"]
                        if not d.get("target_review_id") or d["target_review_id"] in card.review_ids]
    old_card_id = result["card_id"]
    result["card_id"] = card.card_id
    result["reason_text"] = card.reason_text
    for draft in result["drafts"]:
        draft["card_id"] = card.card_id
        mapped = []
        for ev in draft.get("evidence_ids", []):
            if ev.startswith("snap_") and card.snapshot_ids:
                mapped.extend(x for x in card.snapshot_ids if x not in mapped)
            else:
                mapped.append(ev)
        draft["evidence_ids"] = mapped
    result["source"] = "seed"
    result["source_note"] = (f"김수현 저장본(c6_cache_best.json, 샘플 카드 {old_card_id}로 생성한 글). "
                             "이유 문장은 이 화면의 카드 문장으로 바꿈")
    return result


# ── 재발 방지 조치 (C6 measures.MEASURES) ───────────────────────────
# 사장님이 고른 조치만 공지·답글에 들어가고, 고르지 않은 조치를 지어내면 C6 점검이 잡는다.
# 기본 선택: 묶음 주제에 맞는 조치 하나 (사장님이 화면에서 바꿀 수 있음)
DEFAULT_MEASURES = {"iss_missing_item": ["M1"]}   # 포장 누락 → 포장 마감 전 주문서 대조


def measure_catalog() -> list[dict]:
    try:
        from c6.measures import MEASURES
    except Exception:
        return []
    return [dict(m) for m in MEASURES]


def pick_measures(ids: list[str] | None) -> list[dict]:
    catalog = {m["id"]: m for m in measure_catalog()}
    unknown = [i for i in (ids or []) if i not in catalog]
    if unknown:
        raise GenerateError(f"모르는 재발 방지 조치예요: {', '.join(unknown)}")
    return [catalog[i] for i in (ids or [])]


# ── live ─────────────────────────────────────────────────────────────
def _context(store: StoreProfile, reviews: list[ReviewRecord], card: RecommendationCard,
             snapshots: list[AnalysisSnapshot]):
    from c6.contract import build_context
    return build_context(store=store, reviews=reviews, cards=[card], snapshots=snapshots)


def run_live(card: RecommendationCard, *, store: StoreProfile, reviews: list[ReviewRecord],
             snapshots: list[AnalysisSnapshot], key: str, model: str,
             chosen_measures: list[dict] | None = None) -> dict:
    """HCX-005 로 생성. ③ 전부 실시간이고 파일에 저장하지 않는다."""
    if not key:
        raise GenerateError("HCX 키가 없어 실시간 생성을 할 수 없어요. APP_MODE=mock 으로 실행하세요.")
    from c6.registry import run_card

    ctx = _context(store, reviews, card, snapshots)
    result = run_card(ctx, card, key, model=model, chosen_measures=chosen_measures).to_dict()
    result["source"] = "live"
    result["needs_input"] = list(ctx.needs_input)
    return result


def draft_texts(result: dict) -> list[str]:
    return [d["text"] for d in result.get("drafts", [])]


# 사장님이 하지 않은 조치를 이미 한 것처럼 말하거나, 정하지 않은 보상을 약속하는 문장 (C6 점검이 잡지 못한 것).
# 예: "공깃밥 추가로 보내드렸어요" (11/9 C6 저장본). 사과("불편을 드려")나 재발 방지 다짐("꼼꼼히 챙기겠습니다")은 잡지 않는다.
# "보내드렸어야 했는데"(했어야 했다는 사과)는 조치가 아니므로 뺀다 (11/10 live 1차 답글)
_DONE_ACTION = re.compile(r"(보내|챙겨|넣어|환불|적립|교환|발송|처리|추가|지급|쿠폰)[^.!?\n]{0,12}?드렸(?!어야|더라면)")
_DONE_PROCESS = re.compile(r"(환불|적립|재발송|발송|교환|보상)[^.!?\n]{0,6}?(완료|했습니다|했어요|해 드렸)")
_PROMISE = re.compile(r"(서비스|쿠폰|환불|적립|보상|무료)[^.!?\n]{0,12}?(드릴게요|드리겠습니다|드릴 예정)")


def action_flags(text: str) -> list[str]:
    """하지 않은 조치·정하지 않은 보상 문장을 찾아 '확인 필요' 문구로 돌려준다."""
    flags = []
    checks = ((_DONE_ACTION, "이미 한 조치처럼 말함", "사장님이 실제로 했는지 확인"),
              (_DONE_PROCESS, "이미 처리한 것처럼 말함", "사장님이 실제로 했는지 확인"),
              (_PROMISE, "정하지 않은 보상 약속", "사장님이 정한 보상인지 확인"))
    for pattern, why, ask in checks:
        for match in pattern.finditer(text or ""):
            flags.append(f"{why}: '{match.group(0)}' ({ask})")
    return flags


def summarize(result: dict[str, Any]) -> dict[str, Any]:
    """화면에 바로 쓰기 좋은 모양: 글마다 C7 점검(하지 않은 조치)을 붙이고, 확인이 필요한 글 수를 센다."""
    drafts = []
    for d in result.get("drafts", []):
        d = {**d, "c7_flags": action_flags(d.get("text", ""))}
        drafts.append(d)
    flagged = [d for d in drafts if d.get("failed_reasons") or d.get("needs_input") or d["c7_flags"]]
    return {**result, "drafts": drafts, "flagged_count": len(flagged)}
