"""①→④ 를 잇는 한 곳. main.py(웹)와 시험이 이 클래스만 쓴다."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from shared.answer_check import check_answer, feedback
from shared.contracts import LABELS_KO, AnalysisSnapshot, StoreProfile, quarter_label

from .cards import (CardPlan, apply_writer, model_reason_failed, normalize_citations, plan_cards, reason_problems,
                    why_no_card_b)
from .generate import (DEFAULT_MEASURES, GenerateError, adapt_seed, c6_available, ensure_marketing_on_path, load_seed,
                       measure_catalog, pick_measures,
                       run_live, summarize)
from .settings import Settings
from .sources import ReviewSource, SourceError, is_dev_fake, load_snapshots, to_review_records, to_store_profile

MODE_LABELS = {"mock": "시험용 실행", "live": "실시간 HCX-005"}
# mock 일 때만 화면 맨 위에 띄운다. 저장된 예시가 실제 AI 결과처럼 보이면 안 된다.
MOCK_NOTICE = "시험용 실행 · 키 없이 저장된 예시 결과를 보여 줍니다 (실제 AI 결과 아님)"
KST = timezone(timedelta(hours=9))


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


class DemoError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Demo:
    def __init__(self, settings: Settings, source: ReviewSource | None = None, reason_model=None):
        self.s = settings
        self.source = source if source is not None else ReviewSource(settings.review_url, settings.review_token)
        self.c6 = c6_available(settings.marketing_dir)
        self.seed = load_seed(settings.marketing_dir)
        self._reason_model = reason_model          # 시험에서 가짜 모델을 넣는 자리
        self._reason_memo: dict[str, CardPlan] = {}
        self._lock = threading.Lock()
        self.approvals: list[dict] = []

    # ── 상태 ────────────────────────────────────────────────────────
    def _state(self) -> dict[str, Any]:
        try:
            store = self.source.store(self.s.store_id)
            reviews = self.source.reviews(self.s.store_id)
            insight = self.source.insight(self.s.store_id)
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

    def briefing(self) -> dict:
        st = self._state()
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

    def cards(self) -> dict:
        st = self._state()
        plans = self._plans(st)
        return {"cards": [p.to_dict() for p in plans],
                "no_card_b": why_no_card_b(st["snapshots"], self.s.card_b_snapshot_id, self.s.card_b_threshold)}

    def _plans(self, st: dict) -> list[CardPlan]:
        writer = self._reason_writer if self.s.mode == "live" else None
        key = json.dumps([st["insight"].get("top_issue_id"), [g["review_ids"] for g in st["insight"].get("groups", [])],
                          [s.to_dict() for s in st["snapshots"]], self.s.mode], ensure_ascii=False, sort_keys=True)
        with self._lock:
            if key not in self._reason_memo:   # live 에서 GET 마다 HCX 를 다시 부르지 않게
                self._reason_memo[key] = plan_cards(
                    st["insight"], st["snapshots"], self.s.store_id, preferred_id=self.s.card_b_snapshot_id,
                    threshold=self.s.card_b_threshold, writer=writer)
                if self.c6:   # 불만 카드에 재발 방지 조치 고르기 (C6 목록)
                    catalog = measure_catalog()
                    for plan in self._reason_memo[key]:
                        if plan.card.kind == "complaint" and catalog:
                            plan.measures = {"options": catalog,
                                             "default": DEFAULT_MEASURES.get(st["insight"].get("top_issue_id"), [])}
            elif writer is not None:
                # 검사에 걸려 고정 문장으로 돌아간 카드만 다음 요청 때 다시 쓰게 한다. 통과한 문장은 그대로 둔다.
                for plan in self._reason_memo[key]:
                    if model_reason_failed(plan) and plan.rounds < self.REASON_ROUNDS:
                        apply_writer(plan, writer)
            return self._reason_memo[key]

    REASON_ROUNDS = 3  # 카드 하나에 대해 이유 쓰기를 다시 시도하는 요청 수 (라운드마다 REASON_TRIES 번)
    REASON_TRIES = 5   # 사용자 지시(11/10): 확실한 결과가 나올 때까지 충분히 부른다
    # 할 일을 완성된 문장으로 준다 ("~하는 것"으로 주면 모델이 "~것을 추천해요"로 끝내서 검사기에 걸림, 11/10 live 6차)
    REASON_TODO = {"complaint": "같은 불만이 다시 안 생기게 재발 방지 공지를 올리고, 답글도 함께 달아요.",
                   "promo": "저녁 손님을 다시 부르는 쿠폰 홍보를 제안해요."}

    def _reason_writer(self, kind: str, facts: list[dict], fixed: str) -> str:
        """live: HCX-005 가 이유 문장을 쓴다. 규칙 검사(reason_problems)에 걸리면 고칠 점을 붙여 다시 쓴다 (최대 REASON_TRIES번)."""
        model = self._reason_model or self._clova_reason
        # '사실 카드'라고 부르면 모델이 문장을 "사실 …"로 시작해서 '근거 카드'라고 부른다 (11/10 live 2차)
        system = ("소상공인 사장님에게 오늘 이 카드를 먼저 처리하면 좋은 이유를 해요체 두 문장으로 써요.\n"
                  "첫 문장: 근거 카드의 숫자를 소수점까지 적힌 그대로(예: 3건, 19.31%) 쓰고, 시간대·분기도 그대로 쓰고, 그 문장 끝에 [F1]처럼 카드 번호를 붙여요.\n"
                  "둘째 문장: 아래 '할 일' 문장을 그대로 쓰거나 같은 뜻으로 짧게 써요. '추천'이라는 말은 쓰지 않아요.\n"
                  "근거 카드에 없는 숫자, 원인 단정('때문'), 보장, 앞날 예측('~할 수 있어요', '예상', '가능성', '높아질', '늘어날'), "
                  "좋아졌다/나빠졌다 같은 판단은 쓰지 않아요. 문장 앞에 '사실', '참고로' 같은 말을 붙이지 않아요.")
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
    def run(self, card_id: str, measures: list[str] | None = None) -> dict:
        """measures: 사장님이 고른 재발 방지 조치 id. None 이면 카드의 기본값 (불만 카드만 씀)."""
        st = self._state()
        plan = next((p for p in self._plans(st) if p.card.card_id == card_id), None)
        if plan is None:
            raise DemoError(f"카드 {card_id} 가 지금 화면의 카드가 아니에요. 새로 고침 하세요.", status=404)
        card = plan.card
        if self.s.mode == "mock":
            result = adapt_seed(self.seed[card.kind], card) if card.kind in self.seed else None
            if result is None:
                raise DemoError("이 카드에 맞는 저장본이 없어요 (붙여넣기로 묶음이 바뀌었을 수 있어요). "
                                "키가 있으면 APP_MODE=live 로 생성하세요.", status=404)
        else:
            store, reviews = self._contract_inputs(st)
            ids = plan.measures.get("default", []) if measures is None else measures
            try:
                chosen = pick_measures(ids) if card.kind == "complaint" else []
                result = run_live(card, store=store, reviews=reviews, snapshots=st["snapshots"], key=self.s.clova_key,
                                  model=self.s.model, chosen_measures=chosen)
            except GenerateError as exc:
                raise DemoError(str(exc)) from None
        return summarize(result)

    def _contract_inputs(self, st: dict) -> tuple[StoreProfile, list]:
        store = to_store_profile(st["store"], self._area_name(st["snapshots"]))
        return store, to_review_records(st["reviews"], st["insight"])

    # ── ④ ───────────────────────────────────────────────────────────
    def approve(self, draft_id: str, text: str | None, original: str | None) -> dict:
        edited = text is not None and original is not None and text.strip() != original.strip()
        entry = {"draft_id": draft_id, "status": "approved", "edited": edited,
                 "text": text if text is not None else original, "approved_at": now_kst(), "mode": self.s.mode}
        with self._lock:
            self.approvals = [a for a in self.approvals if a["draft_id"] != draft_id] + [entry]
        try:
            self.s.runtime_dir.mkdir(parents=True, exist_ok=True)
            with (self.s.runtime_dir / "approvals.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            entry["warning"] = "승인 기록 파일을 쓰지 못했어요 (화면 기록만 남음)"
        return entry

    # ── S2 붙여넣기 ─────────────────────────────────────────────────
    def paste(self, text: str, rating: int | None, channel: str | None) -> dict:
        try:
            return self.source.paste(self.s.store_id, text, rating, channel)
        except SourceError as exc:
            raise DemoError(str(exc), 503) from None

    def reset_pasted(self) -> dict:
        try:
            return self.source.reset_pasted(self.s.store_id)
        except SourceError as exc:
            raise DemoError(str(exc), 503) from None
