"""①→④ 를 잇는 한 곳. main.py(웹)와 시험이 이 클래스만 쓴다."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

from shared.answer_check import check_answer, feedback
from shared.contracts import LABELS_KO, AnalysisSnapshot, StoreProfile, quarter_label
from shared.storage import MemoryStore, StorageError, clean_visitor_id

from .cards import (REASON_OK, CardPlan, apply_writer, model_reason_failed, normalize_citations, plan_cards,
                    reason_problems, strip_citations, why_no_card_b)
from .generate import (DEFAULT_MEASURES, GenerateError, adapt_seed, add_pasted_replies, c6_available,
                       ensure_marketing_on_path, load_pasted_examples, load_seed, measure_catalog, pasted_reply_targets,
                       pick_measures, run_live, run_live_pasted_replies, seed_pasted_replies, summarize)
from .settings import Settings
from .sources import ReviewSource, SourceError, is_dev_fake, load_snapshots, to_review_records, to_store_profile

MODE_LABELS = {"mock": "시험용 실행", "live": "실시간 HCX-005"}
# mock 일 때만 화면 맨 위에 띄운다. 저장된 예시가 실제 AI 결과처럼 보이면 안 된다.
MOCK_NOTICE = "시험용 실행 · 키 없이 저장된 예시 결과를 보여 줍니다 (실제 AI 결과 아님)"
KST = timezone(timedelta(hours=9))
log = logging.getLogger("web.demo")

REASON_VERSION = "reason-v1"   # 이유 문장 만드는 방식을 바꾸면 올린다 → 저장해 둔 이전 문장을 더 쓰지 않음 (프롬프트·모델·근거가 바뀌어도 열쇠가 달라진다)
MEMO_MAX = 256                 # 카드 계획을 서버 메모리에 기억하는 최대 개수 (방문자가 많아져도 무한히 늘지 않게)
DRAFT_MAX = 2000               # 어느 카드의 초안인지 기억하는 최대 개수
PENDING_MAX = 2000             # DB 가 멈춘 동안 들고 있는 승인 기록의 최대 개수 (넘으면 오래된 것부터 버림)


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


class DemoError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Demo:
    def __init__(self, settings: Settings, source: ReviewSource | None = None, reason_model=None, storage=None):
        """storage: 승인 기록·카드 이유·보고서를 둘 곳 (shared.storage). 안 주면 서버 메모리.
        서버는 create_app 이 환경 변수(DB_HOST)를 보고 정해서 넘긴다. 직접 만든 Demo 가 환경 변수에 끌려가 DB 에 붙지 않게 여기서는 읽지 않는다."""
        self.s = settings
        self.source = source if source is not None else ReviewSource(settings.review_url, settings.review_token)
        self.c6 = c6_available(settings.marketing_dir)
        self.seed = load_seed(settings.marketing_dir)
        self.pasted_examples = load_pasted_examples(settings.marketing_dir)   # mock: 붙여넣은 리뷰 답글 저장 예시
        self._reason_model = reason_model          # 시험에서 가짜 모델을 넣는 자리
        self._reason_memo: OrderedDict[str, list[CardPlan]] = OrderedDict()
        self._lock = threading.Lock()
        self.storage = storage if storage is not None else MemoryStore()
        # DB 에 쓰지 못한 승인 기록 (방문자, 기록, 카드 id, 초안 종류). 승인한 순서대로 들고 있다가 DB 가 돌아오면 쓴다 (DB 를 쓸 때만)
        self._pending: list[tuple[str, dict, str | None, str | None]] = []
        self._flush_lock = threading.Lock()   # 밀린 승인 기록은 한 번에 한 요청만 쓴다 (순서가 섞이지 않게)
        self._drafts: OrderedDict[str, tuple[str, str | None]] = OrderedDict()   # 초안 id → (카드 id, 초안 종류). 승인 기록에 붙임

    # ── 방문자 ──────────────────────────────────────────────────────
    def _src(self, visitor: str | None):
        """방문자가 붙여넣은 리뷰를 따로 보는 리뷰 분석 연결. 방문자별 구분을 모르는 연결이면 그대로 쓴다."""
        scoped = getattr(self.source, "for_visitor", None)
        return scoped(visitor) if (scoped is not None and visitor) else self.source

    # ── 상태 ────────────────────────────────────────────────────────
    def _state(self, visitor: str | None = None) -> dict[str, Any]:
        try:
            src = self._src(visitor)
            store = src.store(self.s.store_id)
            reviews = src.reviews(self.s.store_id)
            insight = src.insight(self.s.store_id)
        except SourceError as exc:
            raise DemoError(str(exc), status=503) from None
        return {"store": store, "reviews": reviews, "insight": insight,
                "snapshots": load_snapshots(self.s.snapshot_path)}

    def _area_name(self, snapshots: list[AnalysisSnapshot]) -> str | None:
        return snapshots[0].area_name if snapshots else None

    # ── 화면용 ──────────────────────────────────────────────────────
    def health(self) -> dict:
        snaps: list[AnalysisSnapshot] = []
        snap_error = None
        try:
            snaps = load_snapshots(self.s.snapshot_path)
        except ValueError as exc:
            snap_error = str(exc)
        fakes = [s.snapshot_id for s in snaps if is_dev_fake(s)]
        blocking: list[str] = []
        if self.s.mode == "live" and not self.s.key_present:
            blocking.append("APP_MODE=live 인데 HCX 키가 없어요. 키 파일(~/.config/teletubby-aiic/env)을 확인하세요.")
        if self.s.mode == "live" and not self.c6:
            blocking.append(f"C6 코드(c6/registry.py)를 찾지 못했어요: {self.s.marketing_dir}")
        if self.s.mode == "mock" and not self.seed:
            blocking.append(f"C6 저장본(c6/replay/c6_cache_best.json)을 찾지 못해 ③ 생성이 막혀요: {self.s.marketing_dir}")
        if not snaps and not snap_error:
            blocking.append(f"상권 지표 파일을 찾지 못해 카드 ⓑ 가 뜨지 않아요: {self.s.snapshot_path}")
        review = {"url": self.s.review_url, **self.source.health()}
        return {
            "mode": self.s.mode, "mode_label": MODE_LABELS[self.s.mode],
            "mode_notice": MOCK_NOTICE if self.s.mode == "mock" else None,
            "store_id": self.s.store_id, "key_present": self.s.key_present, "c6_available": self.c6,
            "seed_available": bool(self.seed), "review_service": review,
            "snapshot": {"file": self.s.snapshot_path.name, "count": len(snaps), "error": snap_error},
            "dev_fake_snapshots": fakes, "blocking": blocking,
            "parts": self._parts(),
        }

    def _parts(self) -> dict[str, str]:
        """화면 맨 위 '동작 / 모의' 띠 (결정안 4절)."""
        review_mode = (self.source.health().get("models") or {}).get("review_classify", "?")
        gen = {"mock": "저장본(김수현 C6 결과)", "live": "실시간 HCX-005"}[self.s.mode]
        return {"briefing": f"리뷰 분류: {review_mode}", "cards": "규칙 + " + ("HCX-005 이유 문장" if self.s.mode == "live" else "고정 문장"),
                "generate": gen, "reviews": "합성 데이터"}

    def briefing(self, visitor: str | None = None) -> dict:
        st = self._state(visitor)
        insight, snaps = st["insight"], st["snapshots"]
        by_id = {r["review_id"]: r for r in st["reviews"]}

        def review_view(rid: str) -> dict:
            r = by_id.get(rid, {})
            return {"review_id": rid, "text": r.get("text"), "rating": r.get("rating"),
                    "channel": LABELS_KO.get(r.get("channel") or "", r.get("channel")),
                    "created_at": r.get("created_at"), "input_method": r.get("input_method")}

        groups = [{**{k: g[k] for k in ("issue_id", "topic_name", "review_count", "is_repeated",
                                        "main_time_band", "time_bands", "evidence")},
                   "reviews": [review_view(rid) for rid in g["review_ids"]]} for g in insight.get("groups", [])]
        return {
            "store": {"name": st["store"].get("name"), "business_type_name": st["store"].get("business_type_name"),
                      "data_origin": st["store"].get("data_origin"), "area_name": self._area_name(snaps)},
            "period": {"start": insight.get("period_start"), "end": insight.get("period_end")},
            "counts": {k: insight.get(k) for k in ("review_count", "complaint_count", "group_count",
                                                   "single_complaint_count")},
            "repeated_count": sum(1 for g in insight.get("groups", []) if g.get("is_repeated")),
            "top_issue_id": insight.get("top_issue_id"),
            "groups": groups,
            "single_complaints": insight.get("single_complaints", []),
            "pasted": [review_view(r["review_id"]) for r in st["reviews"] if r.get("input_method") == "paste"],
            "snapshots": [{**s.to_dict(), "basis_label": s.basis_label, "quarter_label": quarter_label(s.basis_quarter),
                           "dev_fake": is_dev_fake(s)} for s in snaps],
            "data_origin": insight.get("data_origin"),
        }

    # 리뷰 분석 화면(#/analysis)의 요약·불만 묶음용. #14 insight 를 읽어서 화면에 쓰는 칸만 그대로 넘긴다 (읽기 전용).
    # 리뷰별 분류(classifications)와 반복 묶음 사본(repeated_issues)은 화면에 안 써서 뺀다.
    INSIGHT_KEYS = ("period_start", "period_end", "review_count", "complaint_count", "sentiment_counts", "topic_counts",
                    "group_count", "single_complaint_count", "top_issue_id", "groups", "single_complaints", "data_origin")

    def insight(self, visitor: str | None = None) -> dict:
        try:
            found = self._src(visitor).insight(self.s.store_id)
        except SourceError as exc:
            raise DemoError(str(exc), status=503) from None
        return {k: found.get(k) for k in self.INSIGHT_KEYS}

    def cards(self, visitor: str | None = None) -> dict:
        st = self._state(visitor)
        plans = self._plans(st)
        return {"cards": [p.to_dict() for p in plans],
                "no_card_b": why_no_card_b(st["snapshots"], self.s.card_b_snapshot_id, self.s.card_b_threshold)}

    def _plans(self, st: dict) -> list[CardPlan]:
        writer = self._reason_writer if self.s.mode == "live" else None
        # 묶음 전체(근거 문장 포함)를 열쇠에 넣는다. 방문자마다 붙여넣은 글이 다른데 리뷰 번호(…_paste_001)만 같으면
        # 한 방문자의 근거 문장이 다른 방문자에게 보일 수 있다. 내용이 같을 때만 같은 계획을 쓴다.
        key = json.dumps([st["insight"].get("top_issue_id"), st["insight"].get("groups", []),
                          [s.to_dict() for s in st["snapshots"]], self.s.mode], ensure_ascii=False, sort_keys=True)
        with self._lock:
            plans = self._reason_memo.get(key)
            if plans is None:   # live 에서 GET 마다 HCX 를 다시 부르지 않게
                plans = plan_cards(st["insight"], st["snapshots"], self.s.store_id, preferred_id=self.s.card_b_snapshot_id,
                                   threshold=self.s.card_b_threshold)
                if writer is not None:
                    for plan in plans:
                        if not plan.problems:   # 고정 문장이 검사기에 걸린 카드는 모델을 부르지 않는다 (plan_cards 와 같은 규칙)
                            self._write_reason(plan, writer)
                if self.c6:   # 불만 카드에 재발 방지 조치 고르기 (C6 목록)
                    catalog = measure_catalog()
                    for plan in plans:
                        if plan.card.kind == "complaint" and catalog:
                            plan.measures = {"options": catalog,
                                             "default": DEFAULT_MEASURES.get(st["insight"].get("top_issue_id"), [])}
                self._reason_memo[key] = plans
                while len(self._reason_memo) > MEMO_MAX:
                    self._reason_memo.popitem(last=False)
            else:
                self._reason_memo.move_to_end(key)
                if writer is not None:
                    # 검사에 걸려 고정 문장으로 돌아간 카드만 다음 요청 때 다시 쓰게 한다. 통과한 문장은 그대로 둔다.
                    for plan in plans:
                        if model_reason_failed(plan) and plan.rounds < self.REASON_ROUNDS:
                            self._write_reason(plan, writer)
            return plans

    # ── 카드 이유 저장 ──────────────────────────────────────────────
    def _reason_key(self, plan: CardPlan) -> str:
        """이 이유 문장을 다시 써도 되는 조건. 근거 카드(숫자)·참조 문장·근거 id·프롬프트·모델·버전 중 하나라도 바뀌면 달라진다."""
        card = plan.card
        material = {"version": REASON_VERSION, "model": self.s.model, "kind": card.kind, "system": self.REASON_SYSTEM,
                    "todo": self.REASON_TODO.get(card.kind, ""), "facts": plan.facts, "fixed": plan.checked_text,
                    "review_ids": card.review_ids, "snapshot_ids": card.snapshot_ids}
        return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:32]

    def _write_reason(self, plan: CardPlan, writer) -> None:
        """저장된 이유 문장이 있으면 모델을 부르지 않고 그대로 쓴다. 없으면 쓰게 하고, 검사를 통과했으면 저장한다.
        저장소가 실패해도 화면은 뜬다 (저장된 것이 없는 셈 치고 모델이 쓴다)."""
        key = self._reason_key(plan)
        try:
            saved = self.storage.card_reasons.get(self.s.store_id, plan.card.card_id, key)
        except Exception as exc:
            log.warning("카드 이유 저장소를 읽지 못했어요 (%s)", exc.__class__.__name__)
            saved = None
        # 저장 뒤에 검사 규칙이 바뀌었을 수 있으니 지금 규칙으로 한 번 더 본다
        if saved and not reason_problems(saved["reason_text"], plan.facts):
            plan.checked_text = saved["reason_text"]
            plan.card.reason_text = strip_citations(saved["reason_text"])
            plan.reason_source = REASON_OK
            plan.problems = []
            return
        apply_writer(plan, writer)
        if plan.reason_source == REASON_OK:
            try:
                self.storage.card_reasons.put(self.s.store_id, plan.card.card_id, key, reason_text=plan.checked_text,
                                              source=plan.reason_source, model=self.s.model)
            except Exception as exc:
                log.warning("카드 이유를 저장하지 못했어요 (%s)", exc.__class__.__name__)

    REASON_ROUNDS = 3  # 카드 하나에 대해 이유 쓰기를 다시 시도하는 요청 수 (라운드마다 REASON_TRIES 번)
    REASON_TRIES = 5   # 사용자 지시(11/10): 확실한 결과가 나올 때까지 충분히 부른다
    # 할 일을 완성된 문장으로 준다 ("~하는 것"으로 주면 모델이 "~것을 추천해요"로 끝내서 검사기에 걸림, 11/10 live 6차)
    REASON_TODO = {"complaint": "같은 불만이 다시 안 생기게 재발 방지 공지를 올리고, 답글도 함께 달아요.",
                   "promo": "저녁 손님을 다시 부르는 쿠폰 홍보를 제안해요."}

    # '사실 카드'라고 부르면 모델이 문장을 "사실 …"로 시작해서 '근거 카드'라고 부른다 (11/10 live 2차)
    REASON_SYSTEM = ("소상공인 사장님에게 오늘 이 카드를 먼저 처리하면 좋은 이유를 해요체 두 문장으로 써요.\n"
                     "첫 문장: 근거 카드의 숫자를 소수점까지 적힌 그대로(예: 3건, 19.31%) 쓰고, 시간대·분기도 그대로 쓰고, 그 문장 끝에 [F1]처럼 카드 번호를 붙여요.\n"
                     "둘째 문장: 아래 '할 일' 문장을 그대로 쓰거나 같은 뜻으로 짧게 써요. '추천'이라는 말은 쓰지 않아요.\n"
                     "근거 카드에 없는 숫자, 원인 단정('때문'), 보장, 앞날 예측('~할 수 있어요', '예상', '가능성', '높아질', '늘어날'), "
                     "좋아졌다/나빠졌다 같은 판단은 쓰지 않아요. 문장 앞에 '사실', '참고로' 같은 말을 붙이지 않아요.")

    def _reason_writer(self, kind: str, facts: list[dict], fixed: str) -> str:
        """live: HCX-005 가 이유 문장을 쓴다. 규칙 검사(reason_problems)에 걸리면 고칠 점을 붙여 다시 쓴다 (최대 REASON_TRIES번)."""
        model = self._reason_model or self._clova_reason
        system = self.REASON_SYSTEM
        keep = [k for f in facts for k in f.get("keep", []) if k]
        user = (f"근거 카드: {json.dumps(facts, ensure_ascii=False)}\n할 일: {self.REASON_TODO.get(kind, '')}\n"
                + (f"글자 그대로 쓸 표기: {', '.join(repr(k) for k in keep)}\n" if keep else "")
                + f"참고 문장(이 정도 길이, 근거 카드에 있는 사실만): {fixed}")
        text, ask = "", user
        for _ in range(self.REASON_TRIES):
            text = normalize_citations(model(system, ask))
            problems = reason_problems(text, facts)
            if not problems:
                return text
            mine = ("no_citation", "no_fact_value", "empty", "unit_mismatch", "too_long", "prediction", "label_changed")
            hints = [p for p in problems if p["type"] not in mine]
            extra = [p["detail"] for p in problems if p["type"] in ("unit_mismatch", "too_long", "prediction", "label_changed")]
            if any(p["type"] == "no_fact_value" for p in problems):
                extra.append("근거 카드의 숫자(" + next(p["detail"] for p in problems if p["type"] == "no_fact_value") + ")를 그대로 넣어요")
            if any(p["type"] == "no_citation" for p in problems):
                extra.append("숫자를 쓴 문장 끝에 [F1]처럼 카드 번호를 붙여요")
            ask = user + "\n고칠 점: " + " / ".join(([feedback(hints, facts)] if hints else []) + extra)
        return text

    def _clova_reason(self, system: str, user: str) -> str:
        if not self.s.key_present:
            raise GenerateError("HCX 키 없음")
        ensure_marketing_on_path(self.s.marketing_dir)
        import clova  # experiments/marketing/clova.py (PR #16)
        resp = clova.call(self.s.clova_key, system, [{"role": "user", "content": user}],
                          model=self.s.model, max_tokens=200, temperature=0.3)
        if resp.get("error"):
            raise GenerateError(resp["error"][:200])
        return (resp.get("content") or "").strip()

    # ── ③ ───────────────────────────────────────────────────────────
    def run(self, card_id: str, measures: list[str] | None = None, visitor: str | None = None) -> dict:
        """measures: 사장님이 고른 재발 방지 조치 id. None 이면 카드의 기본값 (불만 카드만 씀)."""
        st = self._state(visitor)
        plan = next((p for p in self._plans(st) if p.card.card_id == card_id), None)
        if plan is None:
            raise DemoError(f"카드 {card_id} 가 지금 화면의 카드가 아니에요. 새로 고침 하세요.", status=404)
        card = plan.card
        if self.s.mode == "mock":
            result = adapt_seed(self.seed[card.kind], card) if card.kind in self.seed else None
            if result is None:
                raise DemoError("이 카드에 맞는 저장본이 없어요 (붙여넣기로 묶음이 바뀌었을 수 있어요). "
                                "키가 있으면 APP_MODE=live 로 생성하세요.", status=404)
            pasted = self._pasted_targets(st, card)
            if pasted:
                drafts, skipped = seed_pasted_replies(self.pasted_examples, card, pasted)
                add_pasted_replies(result, drafts, skipped,
                                   note="붙여넣은 리뷰 답글은 같은 글로 미리 만든 저장 예시" if drafts else None)
        else:
            store, reviews = self._contract_inputs(st)
            # 카드 ⓐ 묶음에 들지 않은 붙여넣은 불만 리뷰 (예: 무리한 요청을 거절해 남은 억울한 별점). 그 답글도 함께 만든다
            pasted = pasted_reply_targets(card, reviews) if card.kind == "complaint" and self.s.clova_key else []
            ids = plan.measures.get("default", []) if measures is None else measures
            try:
                chosen = pick_measures(ids) if card.kind == "complaint" else []
                with ThreadPoolExecutor(max_workers=2) as pool:   # 붙여넣은 리뷰 답글은 카드 생성과 동시에 만든다
                    extra = pool.submit(run_live_pasted_replies, card, pasted, store=store, reviews=reviews,
                                        snapshots=st["snapshots"], key=self.s.clova_key, model=self.s.model) if pasted else None
                    result = run_live(card, store=store, reviews=reviews, snapshots=st["snapshots"], key=self.s.clova_key,
                                      model=self.s.model, chosen_measures=chosen)
                    if extra is not None:
                        self._add_live_pasted(result, extra, pasted)
            except GenerateError as exc:
                raise DemoError(str(exc)) from None
        made = summarize(result)
        self._remember_drafts(card_id, made)
        return made

    def _pasted_targets(self, st: dict, card) -> list:
        """mock: 카드 ⓐ 묶음 밖의 붙여넣은 불만 리뷰. 변환이 안 되는 리뷰가 있어도 mock 화면은 예전처럼 뜨게 한다."""
        if card.kind != "complaint" or not any(r.get("input_method") == "paste" for r in st["reviews"]):
            return []
        try:
            return pasted_reply_targets(card, self._contract_inputs(st)[1])
        except ValueError as exc:
            log.warning("붙여넣은 리뷰를 읽지 못해 답글을 만들지 않아요 (%s)", exc)
            return []

    @staticmethod
    def _add_live_pasted(result: dict, extra, pasted: list) -> None:
        """붙여넣은 리뷰 답글이 실패해도 카드 ⓐ 의 글은 그대로 보여 준다 (못 만든 리뷰는 pasted_reply_skipped 에 적음)."""
        try:
            sub = extra.result()
        except Exception as exc:   # 네트워크·키 문제 등
            log.warning("붙여넣은 리뷰 답글을 만들지 못했어요 (%s)", exc.__class__.__name__)
            add_pasted_replies(result, [], [{"review_id": r.review_id, "reason": f"만들지 못함 ({exc.__class__.__name__})"}
                                            for r in pasted])
            return
        add_pasted_replies(result, sub.get("drafts", []), [], won=float(sub.get("won") or 0))

    def _remember_drafts(self, card_id: str, made: dict) -> None:
        """어느 카드의 어떤 초안인지 기억해 둔다. 승인 요청에는 초안 id 만 오기 때문 (승인 기록의 카드·종류 칸을 채움)."""
        with self._lock:
            for draft in made.get("drafts", []):
                if draft.get("draft_id"):
                    self._drafts[draft["draft_id"]] = (card_id, draft.get("generator"))
            while len(self._drafts) > DRAFT_MAX:
                self._drafts.popitem(last=False)

    def _contract_inputs(self, st: dict) -> tuple[StoreProfile, list]:
        store = to_store_profile(st["store"], self._area_name(st["snapshots"]))
        return store, to_review_records(st["reviews"], st["insight"])

    # ── ④ ───────────────────────────────────────────────────────────
    def approve(self, draft_id: str, text: str | None, original: str | None, visitor: str | None = None,
                card_id: str | None = None, kind: str | None = None) -> dict:
        """card_id·kind(초안 종류)는 화면이 보내면 그 값, 아니면 이 서버가 ③ 에서 기억해 둔 값 (다른 서버가 만든 초안이면 비어 있음)."""
        edited = text is not None and original is not None and text.strip() != original.strip()
        entry = {"draft_id": draft_id, "status": "approved", "edited": edited,
                 "text": text if text is not None else original, "approved_at": now_kst(), "mode": self.s.mode}
        known = self._drafts.get(draft_id, (None, None))
        warning = self._save_approval(clean_visitor_id(visitor), entry, card_id or known[0], kind or known[1])
        if warning:
            entry["warning"] = warning
        return entry

    def _save_approval(self, visitor_id: str, entry: dict, card_id: str | None, kind: str | None) -> str | None:
        """승인 기록을 남긴다. 못 남기면 이유 문장을 돌려준다 (기록은 화면에만 남는다)."""
        store_id = self.s.store_id
        if self.storage.kind == "memory":   # 기본: 서버 메모리 + 파일에 덧붙임
            self.storage.approvals.save(store_id, visitor_id, entry, card_id=card_id, kind=kind)
            try:
                self.s.runtime_dir.mkdir(parents=True, exist_ok=True)
                with (self.s.runtime_dir / "approvals.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError:
                return "승인 기록 파일을 쓰지 못했어요 (화면 기록만 남음)"
            return None
        # DB: 먼저 줄 맨 뒤에 세우고, 밀린 것부터 순서대로 쓴다 (멈춘 동안 승인한 것이 DB 가 돌아온 뒤에도 남게)
        with self._lock:
            self._pending = [p for p in self._pending if (p[0], p[1]["draft_id"]) != (visitor_id, entry["draft_id"])]
            self._pending.append((visitor_id, entry, card_id, kind))
            del self._pending[:-PENDING_MAX]
        refused = self._flush_pending()
        if any(e is entry for e in refused):
            return "승인 기록을 DB 에 저장하지 못했어요"
        with self._lock:
            waiting = any(p[1] is entry for p in self._pending)
        # 요청은 성공시킨다. 이 서버가 꺼지거나, 이 방문자의 요청이 다른 서버로만 가면 저장이 늦어지거나 빠질 수 있다
        return "승인 기록을 DB 에 쓰지 못했어요 (이 서버가 들고 있다가 DB 가 돌아오면 저장해요)" if waiting else None

    def _flush_pending(self) -> list[dict]:
        """DB 에 못 쓴 승인 기록을 승인한 순서대로 쓴다. DB 에 닿지 못하면 남은 것을 그대로 들고 있다가 다음에 다시 한다.
        돌려주는 값: DB 가 받아 주지 않아 버린 기록 (연결 문제가 아닌 오류. 다시 해도 같으니 줄을 막지 않게 뺀다)."""
        refused: list[dict] = []
        with self._flush_lock:
            with self._lock:
                waiting, self._pending = self._pending, []
            for i, (visitor_id, entry, card_id, kind) in enumerate(waiting):
                try:
                    self.storage.approvals.save(self.s.store_id, visitor_id, entry, card_id=card_id, kind=kind)
                except StorageError as exc:   # DB 장애 전환 중 등
                    log.warning("승인 기록을 DB 에 쓰지 못했어요 (%s). %d건을 들고 있어요", exc.__class__.__name__, len(waiting) - i)
                    with self._lock:
                        self._pending = waiting[i:] + self._pending
                    break
                except Exception as exc:
                    log.warning("DB 가 승인 기록을 받지 않았어요 (%s)", exc.__class__.__name__)
                    refused.append(entry)
        return refused

    def list_approvals(self, visitor: str | None = None) -> list[dict]:
        visitor_id = clean_visitor_id(visitor)
        if self._pending:
            self._flush_pending()   # DB 가 돌아왔으면 멈춘 동안의 승인을 이제 쓴다
        try:
            rows = self.storage.approvals.list(self.s.store_id, visitor_id)
        except Exception as exc:   # DB 에 닿지 못하면 이 서버가 들고 있는 것만 보여 준다
            log.warning("승인 기록을 DB 에서 읽지 못했어요 (%s)", exc.__class__.__name__)
            rows = []
        with self._lock:
            waiting = [p[1] for p in self._pending if p[0] == visitor_id]
        held = {e["draft_id"] for e in waiting}
        return [r for r in rows if r["draft_id"] not in held] + waiting

    @property
    def approvals(self) -> list[dict]:
        """방문자를 가리지 않는 공용 승인 기록 (예전 이름)."""
        return self.list_approvals()

    # ── S2 붙여넣기 ─────────────────────────────────────────────────
    def paste(self, text: str, rating: int | None, channel: str | None, visitor: str | None = None) -> dict:
        try:
            return self._src(visitor).paste(self.s.store_id, text, rating, channel)
        except SourceError as exc:
            raise DemoError(str(exc), 503) from None

    def reset_pasted(self, visitor: str | None = None) -> dict:
        try:
            return self._src(visitor).reset_pasted(self.s.store_id)
        except SourceError as exc:
            raise DemoError(str(exc), 503) from None
