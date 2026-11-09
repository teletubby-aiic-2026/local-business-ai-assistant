"""③ 결과물 생성 (C6, PR #16) 연결.

- live: c6.registry.run_card 를 그대로 부른다. 키는 직접 넘긴다. (config.get_api_key()는 키가 없으면 input()으로
  묻기 때문에 서버 안에서 부르면 요청이 멈춘다. 그래서 쓰지 않는다.)
- 키가 없을 때(mock): 김수현의 발표용 저장본 c6/replay/c6_cache_best.json 을 우리 카드에 맞춰 보여 준다.
  저장본의 이유 문장은 쓰지 않는다(홍보 카드는 '-X%' 자리표시자). 글(drafts)만 쓰고 출처를 표시한다.
- 사다리(결정안 6절): ladder 1 = 답글만 실시간, ladder 2 = 답글 하나만 실시간. 나머지는 저장본.

C6 코드는 고치지 않는다. CardResult·DraftOutput 은 c6.output 을 그대로 쓴다(최소 변경, shared 이동은 보류).
"""
from __future__ import annotations

import copy
import json
import re
import sys
from dataclasses import replace
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


# ── live ─────────────────────────────────────────────────────────────
def _context(store: StoreProfile, reviews: list[ReviewRecord], card: RecommendationCard,
             snapshots: list[AnalysisSnapshot]):
    from c6.contract import build_context
    return build_context(store=store, reviews=reviews, cards=[card], snapshots=snapshots)


def run_live(card: RecommendationCard, *, store: StoreProfile, reviews: list[ReviewRecord],
             snapshots: list[AnalysisSnapshot], key: str, model: str, ladder: int,
             cached: dict | None) -> dict:
    """HCX-005 로 생성. ladder 가 1·2 이면 정해진 부분만 실시간이고 나머지는 cached(저장본)에서 가져온다."""
    if not key:
        raise GenerateError("HCX 키가 없어 실시간 생성을 할 수 없어요. APP_MODE=mock 또는 replay 로 실행하세요.")
    from c6.registry import run_card

    ctx = _context(store, reviews, card, snapshots)
    if ladder == 0 or card.kind != "complaint":
        if ladder != 0 and cached:   # 사다리에서 홍보글은 저장본
            return {**cached, "source": "replay", "source_note": f"사다리 {ladder}칸: 홍보글은 저장본"}
        result = run_card(ctx, card, key, model=model).to_dict()
        result["source"] = "live"
        result["needs_input"] = list(ctx.needs_input)
        return result

    from c6.reply import generate_reply_draft
    live_card = card if ladder == 1 else replace(card, review_ids=card.review_ids[:1])
    live = generate_reply_draft(ctx, live_card, key, model=model).to_dict()
    live_ids = {d["target_review_id"] for d in live["drafts"]}
    rest = [d for d in (cached or {}).get("drafts", []) if d.get("target_review_id") not in live_ids]
    result = {**live, "card_id": card.card_id, "kind": card.kind, "reason_text": card.reason_text,
              "drafts": live["drafts"] + rest, "source": "live+replay",
              "source_note": f"사다리 {ladder}칸: 답글 {len(live['drafts'])}개만 실시간, 나머지는 저장본",
              "needs_input": list(ctx.needs_input)}
    return result


def draft_texts(result: dict) -> list[str]:
    return [d["text"] for d in result.get("drafts", [])]


# 사장님이 하지 않은 조치를 이미 한 것처럼 말하거나, 정하지 않은 보상을 약속하는 문장 (C6 점검이 잡지 못한 것).
# 예: "공깃밥 추가로 보내드렸어요" (11/9 C6 저장본). 사과("불편을 드려")나 재발 방지 다짐("꼼꼼히 챙기겠습니다")은 잡지 않는다.
_DONE_ACTION = re.compile(r"(보내|챙겨|넣어|환불|적립|교환|발송|처리|추가|지급|쿠폰)[^.!?\n]{0,12}?드렸")
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
