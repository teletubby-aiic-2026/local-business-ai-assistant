"""③ 결과물 생성 (C6, PR #16) 연결.

- live: c6.registry.run_card 를 그대로 부른다. 키는 직접 넘긴다. (config.get_api_key()는 키가 없으면 input()으로
  묻기 때문에 서버 안에서 부르면 요청이 멈춘다. 그래서 쓰지 않는다.)
- 키가 없을 때(mock): 시험용 실행. 김수현의 C6 저장 예시 c6/replay/c6_cache_best.json 을 우리 카드에 맞춰 보여 준다.
  저장 예시의 이유 문장은 쓰지 않는다(홍보 카드는 '-X%' 자리표시자). 글(drafts)만 쓰고 출처를 표시한다.
  실제 AI 결과가 아니다.

C6 코드는 고치지 않는다. CardResult·DraftOutput 은 c6.output 을 그대로 쓴다(최소 변경, shared 이동은 보류).
붙여넣은 불만 리뷰가 카드 ⓐ 묶음에 들지 않으면 그 답글도 함께 만든다 (pasted_reply_targets 이하, 11/14).
"""
from __future__ import annotations

import copy
import json
import random
import re
import sys
import time
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


SEED_STORE_ID = "store_ongi"     # 김수현 저장본(c6_cache_best.json)이 만들어진 가게. 다른 가게는 저장본 글이 맞지 않는다
MOCK_TEMPLATE_NOTE = "시험용 예시 글이에요 (이 가게는 저장된 AI 예시가 없어 코드 틀로 만든 글. 실제 AI 결과 아님)"


def _short(name: str) -> str:
    return (name or "").replace("(가상)", "").strip() or "저희 가게"


def _josa(word: str, pair: tuple[str, str]) -> str:
    """받침이 있으면 pair[0], 없으면 pair[1] ('을'/'를' 등). 한글이 아니면 pair[1]."""
    last = word[-1:] if word else ""
    if "가" <= last <= "힣":
        return pair[0] if (ord(last) - 0xAC00) % 28 else pair[1]
    return pair[1]


def mock_template(card: RecommendationCard, store: StoreProfile, reviews: list[ReviewRecord],
                  snapshots: list[AnalysisSnapshot], coupon_menu: str | None = None) -> dict:
    """mock: 저장본이 없는 가게(바삭치킨·몽글카페, 11/18)의 화면 확인용 글. 코드 틀이고 AI 가 쓴 글이 아니다.
    모든 글에 needs_input 으로 그렇게 적어 화면이 '확인 필요'로 보여 준다 (점검 통과로 보이지 않게)."""
    shop = _short(store.name)
    by_id = {r.review_id: r for r in reviews}
    drafts: list[dict] = []

    def draft(n: int, generator: str, text: str, target: str | None = None, evidence: list[str] | None = None) -> dict:
        return {"draft_id": f"d_mock_{card.card_id}_{n}", "card_id": card.card_id, "store_id": store.store_id,
                "generator": generator, "target_review_id": target, "text": text, "evidence_ids": list(evidence or []),
                "checks": {}, "failed_reasons": [], "rewrites": 0, "needs_input": [MOCK_TEMPLATE_NOTE], "status": "draft",
                "edited_text": None, "model": None, "elapsed_ms": 0, "data_origin": "synthetic", "stance": None,
                "stance_reasons": [], "style": None}

    if card.kind == "complaint":
        targets = [by_id[r] for r in card.review_ids if r in by_id]
        drafts.append(draft(0, "prevention_notice",
                            f"[안내] {shop} 주문·포장 안내\n{shop}{_josa(shop, ('을', '를'))} 찾아 주시는 분들께\n"
                            "최근 같은 불편을 말씀해 주신 리뷰가 이어졌습니다. 불편을 드려 죄송합니다.\n"
                            "오늘부터 포장을 마치기 전에 주문서와 한 번 더 대조하겠습니다.\n"
                            "요청하실 내용은 주문 요청사항에 적어 주시면 꼭 챙기겠습니다.",
                            evidence=[f"F_{r.review_id}" for r in targets]))
        for i, review in enumerate(targets, start=1):
            drafts.append(draft(i, "reply_draft",
                                f"안녕하세요 고객님, {shop}입니다. 말씀해 주신 불편을 드려 죄송해요. "
                                "남겨 주신 내용을 확인했고, 다음 주문부터 한 번 더 꼼꼼히 챙길게요.",
                                target=review.review_id, evidence=[f"F_{review.review_id}"]))
    else:
        menu = coupon_menu or (store.menu[0] if store.menu else "대표 메뉴")
        snap = snapshots[0] if snapshots else None
        line = (f"요즘 저녁 시간이 조금 한가해졌어요. 오늘 저녁 {menu} 주문에 쓰실 수 있는 쿠폰을 준비했어요."
                if snap is not None else f"오늘 {menu} 주문에 쓰실 수 있는 쿠폰을 준비했어요.")
        drafts.append(draft(0, "coupon_promo", f"{shop}에서 알려 드려요.\n{line}\n따뜻할 때 맛있게 드실 수 있게 준비할게요.",
                            evidence=[s.snapshot_id for s in snapshots]))
    return {"card_id": card.card_id, "kind": card.kind, "reason_text": card.reason_text, "basis_label": None,
            "drafts": drafts, "chosen_measures": [], "elapsed_ms": 0, "won": 0.0, "source": "seed",
            "source_note": "시험용 실행: 이 가게는 저장된 AI 예시가 없어 코드 틀 글을 보여 줘요 (실제 AI 결과 아님)"}


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


def measure_catalog(topics: list[str] | None = None) -> list[dict]:
    """C6 조치 목록. topics(묶음 주제 id)를 주면 그 주제에 맞는 조치만 (c6.measures.TOPIC_MEASURES, 11/21):
    포장 누락은 M1~M4, 음식 온도는 M5, 맞는 조치가 없는 주제(식감·대기·포장 상태 등)는 빈 목록."""
    try:
        from c6.measures import MEASURES, measures_for_topics
    except Exception:
        return []
    if topics is None:
        return [dict(m) for m in MEASURES]
    wanted = set(measures_for_topics(topics))
    return [dict(m) for m in MEASURES if m["id"] in wanted]


def pick_measures(ids: list[str] | None) -> list[dict]:
    catalog = {m["id"]: m for m in measure_catalog()}
    unknown = [i for i in (ids or []) if i not in catalog]
    if unknown:
        raise GenerateError(f"모르는 주방 점검 수칙이에요: {', '.join(unknown)}")
    return [catalog[i] for i in (ids or [])]


# ── live ─────────────────────────────────────────────────────────────
def _context(store: StoreProfile, reviews: list[ReviewRecord], card: RecommendationCard,
             snapshots: list[AnalysisSnapshot]):
    from c6.contract import build_context
    from shared.store_profiles import c6_extras
    # 가게별 말투·예전 답글·정책 (11/18). 온기한식은 비어 있어 C6 기본값(지금까지와 같은 결과)
    return build_context(store=store, reviews=reviews, cards=[card], snapshots=snapshots, **c6_extras(store.store_id))


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


# ── 붙여넣은 불만 리뷰의 답글 (11/14) ─────────────────────────────────
# 카드 ⓐ 는 가장 큰 반복 묶음만 답글 대상으로 삼아서, 사장님이 붙여넣은 리뷰가 그 묶음에 들지 않으면(예: 무리한 요청을
# 거절해 남은 억울한 별점은 '응대'로 분류됨) 답글이 만들어지지 않았다. 카드 ⓐ 를 만들 때 이런 붙여넣은 불만 리뷰의
# 답글을 같이 만들어 drafts 뒤에 붙인다. 카드의 근거(review_ids)·공지 입력은 그대로다.
# 답글 태도(사과 / 사과 없이 사실 설명)는 C6(c6.stance)가 리뷰마다 정한다.
PASTED_EXAMPLES_RELATIVE = Path("c6") / "replay" / "pasted_reply_examples.json"
PASTED_REPLY_MAX = 3   # 한 번에 답글을 만드는 붙여넣은 리뷰 수 (최근 것부터)


def pasted_reply_targets(card: RecommendationCard, reviews: list[ReviewRecord],
                         limit: int = PASTED_REPLY_MAX) -> list[ReviewRecord]:
    """카드 근거에 없는 붙여넣은 불만 리뷰 (불만 분류이거나 별점 2점 이하). 순서는 받은 그대로(리뷰 목록은 최신순)."""
    found = []
    for r in reviews:
        if r.input_method != "paste" or r.review_id in card.review_ids:
            continue
        if r.sentiment in ("negative", "mixed") or r.negative_topics or (r.rating is not None and r.rating <= 2):
            found.append(r)
    return found[:limit]


def load_pasted_examples(marketing_dir: Path) -> list[dict]:
    """mock 용 저장 예시: 같은 글의 붙여넣은 리뷰에만 보여 주는 답글 (HCX-005 실시간 결과를 저장한 것). 없으면 빈 목록."""
    path = Path(marketing_dir) / PASTED_EXAMPLES_RELATIVE
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _same_text(a: str, b: str) -> bool:
    return " ".join((a or "").split()) == " ".join((b or "").split())


def seed_pasted_replies(examples: list[dict], card: RecommendationCard,
                        targets: list[ReviewRecord]) -> tuple[list[dict], list[dict]]:
    """mock: 글이 똑같은 저장 예시가 있는 리뷰만 그 답글을 쓴다 (다른 리뷰에 다른 리뷰의 답글을 붙이지 않는다).
    돌려주는 값: (답글 목록, 못 만든 리뷰 [{review_id, reason}])."""
    drafts, skipped = [], []
    for review in targets:
        example = next((e for e in examples if _same_text(e.get("review_text", ""), review.text)), None)
        if example is None:
            skipped.append({"review_id": review.review_id, "reason": "같은 글의 저장 예시가 없음 (실시간 실행에서 만들어요)"})
            continue
        draft = copy.deepcopy(example["draft"])
        draft["draft_id"] = f"{draft['draft_id']}_{review.review_id.rsplit('_', 1)[-1]}"
        draft["card_id"] = card.card_id
        draft["target_review_id"] = review.review_id
        draft["evidence_ids"] = [f"F_{review.review_id}"] + [e for e in draft.get("evidence_ids", []) if not e.startswith("F_")]
        drafts.append(draft)
    return drafts, skipped


def run_live_pasted_replies(card: RecommendationCard, targets: list[ReviewRecord], *, store: StoreProfile,
                            reviews: list[ReviewRecord], snapshots: list[AnalysisSnapshot], key: str, model: str) -> dict:
    """live: 붙여넣은 리뷰마다 C6 답글을 만든다 (재발 방지 조치는 넣지 않음 — 카드 ⓐ 묶음의 조치라서)."""
    from c6.reply import generate_reply_draft

    sub = RecommendationCard(card_id=card.card_id, store_id=card.store_id, kind="complaint",
                             reason_text=card.reason_text, review_ids=[r.review_id for r in targets])
    ctx = _context(store, reviews, card, snapshots)
    return generate_reply_draft(ctx, sub, key, model=model, chosen_measures=None).to_dict()


def add_pasted_replies(result: dict, drafts: list[dict], skipped: list[dict], *, won: float = 0.0,
                       note: str | None = None) -> dict:
    """카드 결과 뒤에 붙여넣은 리뷰 답글을 붙이고, 어느 리뷰에 붙였는지·못 붙였는지를 새 칸에 적는다."""
    result["drafts"] = list(result.get("drafts", [])) + drafts
    result["pasted_reply_review_ids"] = [d["target_review_id"] for d in drafts]
    result["pasted_reply_skipped"] = skipped
    if won:
        result["won"] = round(float(result.get("won") or 0) + won, 4)
    parts = [p for p in (result.get("source_note"), note) if p]
    if skipped:
        parts.append(f"붙여넣은 불만 리뷰 {len(skipped)}건은 답글을 만들지 않았어요 ({skipped[0]['reason']})")
    if parts:
        result["source_note"] = " · ".join(parts)
    return result


# ── 개별 다시 만들기: 카드의 글 한 건만 (11/16) ─────────────────────────
# 초안 상자의 '다시 만들기'가 카드 전체를 다시 만들어 다른 글의 수정·승인까지 날리던 것을 고쳤다.
# 전체 실행(run_live → c6.registry.run_card, run_live_pasted_replies)이 그 글을 만들 때와 같은 입력으로 한 건만 부른다.
def pick_seed_draft(result: dict, generator: str, review_id: str | None) -> dict | None:
    """mock: 카드에 맞춘 저장 예시(adapt_seed 결과)에서 그 글 한 건을 고른다. 답글은 리뷰 id 까지 같아야 한다."""
    for draft in result.get("drafts", []):
        if draft.get("generator") == generator and (generator != "reply_draft" or draft.get("target_review_id") == review_id):
            return draft
    return None


def reply_order(card: RecommendationCard, reviews: list[ReviewRecord], review_id: str) -> tuple[ReviewRecord, int, bool] | None:
    """답글 한 건의 (리뷰, 전체 실행에서의 순서, 붙여넣은 리뷰인지). 카드 묶음 리뷰도 붙여넣은 답글 대상도 아니면 None.
    순서는 C6 가 답글마다 고정 문장(조치·요청사항)을 돌려 쓰는 기준이라, 전체 실행 때와 같아야 문장이 다른 답글과 겹치지 않는다."""
    by_id = {r.review_id: r for r in reviews}
    bundle = [by_id[rid] for rid in card.review_ids if rid in by_id]       # c6.reply.generate_reply_draft 가 도는 순서
    for targets, pasted in ((bundle, False), (pasted_reply_targets(card, reviews), True)):
        for index, review in enumerate(targets):
            if review.review_id == review_id:
                return review, index, pasted
    return None


def _one_reply(ctx, card: RecommendationCard, review: ReviewRecord, index: int, key: str, model: str,
               chosen_measures: list[dict] | None = None) -> tuple[dict, float]:
    """리뷰 한 건의 답글. c6.reply.generate_reply_draft(reply_style="auto") 가 리뷰마다 하는 일을 그대로 한다.

    generate_reply_draft 는 카드의 답글을 모두 다시 만들고 리뷰 순서(idx)를 밖에서 정할 수 없어서, 그 안에서 리뷰 한 건을
    처리하는 _process_review 를 같은 인자로 직접 부른다 (C6 코드는 고치지 않음). C6 가 이 함수의 인자를 바꾸면 여기도 같이
    고쳐야 한다 — tests/test_regen_one.py 가 진짜 C6 코드를 가짜 HCX 응답으로 돌려서 어긋나면 바로 잡는다.
    전체 실행과 다른 점 하나: 다른 답글과 표현이 겹치는지(checks.not_too_similar)는 보지 않는다. 그 비교는 답글들의 AI 가 쓴
    부분끼리 하는데 여기서는 한 건만 만들기 때문이다. 그래서 이 칸은 넣지 않는다 (참고용 점검이라 글 상태는 같다).
    """
    from c6 import reply as c6_reply

    store, policies = ctx.store, ctx.policies
    start = time.perf_counter()
    draft, won, *_ = c6_reply._process_review(
        review, idx=index, card_id=card.card_id, store=store, store_display=c6_reply.display_name(store.name),
        menu_names=list(store.menu), allowed_numbers=list(store.menu_prices.values()), policies=policies,
        forbidden_phrases=list(ctx.tone.forbidden_phrases) if ctx.tone.forbidden_phrases else [],
        valid_ids={f"F_{r.review_id}" for r in ctx.reviews} | {p["policy_id"] for p in policies} | {"M1"},
        key=key, model=model, fixed_style=c6_reply.detect_register(ctx.tone), chosen_measures=chosen_measures,
        # 다시 만들기도 점검을 못 넘으면 기본 문장인데, 늘 같은 문장이면 바뀐 게 없어 보인다 → 틀을 돌려 쓴다 (11/21)
        fallback_offset=random.randrange(1, 3))
    draft.elapsed_ms = round((time.perf_counter() - start) * 1000)
    return draft.to_dict(), float(won or 0)


def run_live_one(card: RecommendationCard, generator: str, *, store: StoreProfile, reviews: list[ReviewRecord],
                 snapshots: list[AnalysisSnapshot], key: str, model: str, chosen_measures: list[dict] | None = None,
                 review: ReviewRecord | None = None, index: int = 0, reply_texts: list[str] | None = None) -> dict:
    """HCX-005 로 글 한 건만 다시 만든다. 돌려주는 모양은 run_live 와 같고 drafts 에 그 한 건만 있다.

    - coupon_promo: 카드 ⓑ 는 글이 하나라 카드 전체 실행과 같다.
    - prevention_notice: 고른 조치와, 지금 화면에 있는 묶음 답글들(reply_texts: 공지가 답글과 너무 비슷한지 견줄 때만 씀).
    - reply_draft: review 한 건 (index 는 reply_order 가 준 순서). 붙여넣은 리뷰도 같은 방식 (조치는 원래 답글에 넣지 않는다).
    """
    if generator == "coupon_promo":
        return run_live(card, store=store, reviews=reviews, snapshots=snapshots, key=key, model=model,
                        chosen_measures=chosen_measures)
    if not key:
        raise GenerateError("HCX 키가 없어 실시간 생성을 할 수 없어요. APP_MODE=mock 으로 실행하세요.")
    ctx = _context(store, reviews, card, snapshots)
    if generator == "prevention_notice":
        from c6.notice import generate_prevention_notice
        result = generate_prevention_notice(ctx, card, key, model=model, chosen_measures=chosen_measures,
                                            reply_texts=list(reply_texts or [])).to_dict()
    elif generator == "reply_draft" and review is not None:
        # 붙여넣은 리뷰의 답글은 카드 묶음의 조치를 쓰지 않는다 (run_live_pasted_replies 와 같다)
        pasted = review.review_id not in card.review_ids
        draft, won = _one_reply(ctx, card, review, index, key, model, None if pasted else chosen_measures)
        result = {"card_id": card.card_id, "kind": card.kind, "reason_text": card.reason_text, "basis_label": None,
                  "drafts": [draft], "chosen_measures": list(chosen_measures or []), "elapsed_ms": draft["elapsed_ms"],
                  "won": round(won, 4)}
    else:
        raise GenerateError(f"한 건만 다시 만들 수 없는 글이에요: {generator}")
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
