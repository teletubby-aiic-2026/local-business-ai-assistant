"""①→④ 를 잇는 한 곳. main.py(웹)와 시험이 이 클래스만 쓴다."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

from shared import store_profiles
from shared.answer_check import check_answer, feedback
from shared.contracts import LABELS_KO, AnalysisSnapshot, StoreProfile, quarter_label
from shared.contracts import CARD_GENERATORS   # 카드 종류 → 그 카드가 만드는 글 종류 (개별 다시 만들기의 입력 검사)
from shared.storage import MemoryStore, StorageError, clean_visitor_id

from .cards import (REASON_OK, CardPlan, apply_writer, model_reason_failed, normalize_citations, plan_cards,
                    praised_coupon_menu, reason_problems, strip_citations, why_no_card_b)
from .generate import (DEFAULT_MEASURES, GenerateError, adapt_seed, add_pasted_replies, c6_available,
                       ensure_marketing_on_path, load_pasted_examples, load_seed, measure_catalog, pasted_reply_targets,
                       pick_measures, run_live, run_live_pasted_replies, seed_pasted_replies, summarize)
from .generate import pick_seed_draft, reply_order, run_live_one   # 개별 다시 만들기 (11/16)
from .generate import SEED_STORE_ID, mock_template   # 저장본이 없는 가게의 mock 글 (11/18)
from .settings import Settings
from .sources import ReviewSource, SourceError, is_dev_fake, load_snapshots, to_review_records, to_store_profile

MODE_LABELS = {"mock": "시험용 실행", "live": "실시간 HCX-005"}
# mock 일 때만 화면 맨 위에 띄운다. 저장된 예시가 실제 AI 결과처럼 보이면 안 된다.
MOCK_NOTICE = "시험용 실행 · 키 없이 저장된 예시 결과를 보여 줍니다 (실제 AI 결과 아님)"
KST = timezone(timedelta(hours=9))
log = logging.getLogger("web.demo")

REASON_VERSION = "reason-v3"   # 이유 문장 만드는 방식을 바꾸면 올린다 → 저장해 둔 이전 문장을 더 쓰지 않음 (프롬프트·모델·근거가 바뀌어도 열쇠가 달라진다)
#                                v3 (11/16): 카드 ⓑ 칭찬 근거 줄에 마침표, 말끝을 모델 문장(합니다체/해요체)에 맞춤
MEMO_MAX = 256                 # 카드 계획을 서버 메모리에 기억하는 최대 개수 (방문자가 많아져도 무한히 늘지 않게)
DRAFT_MAX = 2000               # 어느 카드의 초안인지 기억하는 최대 개수
PENDING_MAX = 2000             # DB 가 멈춘 동안 들고 있는 승인 기록의 최대 개수 (넘으면 오래된 것부터 버림)
REPLACES_MAX = 20              # 다시 만들기 한 번에 승인 기록을 지울 수 있는 옛 글 id 수 (replaces, 11/16)


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
        self.source = source if source is not None else ReviewSource(settings.review_url, settings.review_token,
                                                                            paste_timeout=settings.review_paste_timeout)
        self.c6 = c6_available(settings.marketing_dir)
        self.seed = load_seed(settings.marketing_dir)
        self.pasted_examples = load_pasted_examples(settings.marketing_dir)   # mock: 붙여넣은 리뷰 답글 저장 예시
        self._reason_model = reason_model          # 시험에서 가짜 모델을 넣는 자리
        self._reason_memo: OrderedDict[str, list[CardPlan]] = OrderedDict()
        self._lock = threading.Lock()
        self.storage = storage if storage is not None else MemoryStore()
        # DB 에 쓰지 못한 승인 기록 (방문자, 기록, 카드 id, 초안 종류, 초안 정보). 승인한 순서대로 들고 있다가 DB 가 돌아오면 쓴다 (DB 를 쓸 때만)
        self._pending: list[tuple[str, dict, str | None, str | None, dict | None]] = []
        self._flush_lock = threading.Lock()   # 밀린 승인 기록은 한 번에 한 요청만 쓴다 (순서가 섞이지 않게)
        # 초안 id → (카드 id, 초안 종류, 답글이 가리키는 리뷰 id). 승인 기록에 붙이고, 답글 승인을 리뷰 분석 서비스에 알릴 때 쓴다
        self._drafts: OrderedDict[str, tuple[str, str | None, str | None]] = OrderedDict()
        # 초안 id → 초안 정보 {draft_text, checks, used_fallback, style}. 승인 기록의 칸 4개(이슈 #51 ERD, 11/18)를 채운다.
        # ③ 을 이 서버가 만들었을 때만 안다 (서버가 2대이고 다른 서버가 만든 초안이면 화면이 보낸 원문만 남음)
        self._draft_info: OrderedDict[str, dict] = OrderedDict()

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
        out = {
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
        if self.registered and not out["store"]["area_name"]:      # 상권 지표 파일이 없는 등록 가게: 등록한 상권 이름
            bundle = store_profiles.get(self.s.store_id)
            out["store"]["area_name"] = (bundle.area_name or None) if bundle else None
        return self._with_empty(out, insight)

    # 리뷰 분석 화면(#/analysis)의 요약·불만 묶음용. #14 insight 를 읽어서 화면에 쓰는 칸만 그대로 넘긴다 (읽기 전용).
    # 리뷰별 분류(classifications)와 반복 묶음 사본(repeated_issues)은 화면에 안 써서 뺀다.
    INSIGHT_KEYS = ("period_start", "period_end", "review_count", "complaint_count", "sentiment_counts", "topic_counts",
                    "group_count", "single_complaint_count", "top_issue_id", "groups", "single_complaints", "data_origin")

    def insight(self, visitor: str | None = None) -> dict:
        try:
            found = self._src(visitor).insight(self.s.store_id)
        except SourceError as exc:
            raise DemoError(str(exc), status=503) from None
        return self._with_empty({k: found.get(k) for k in self.INSIGHT_KEYS}, found)

    # ── 직접 등록한 가게 (6차 회의 11/20) ─────────────────────────────
    # 리뷰가 0건이면 오류가 아니라 빈 결과다. 그때만 empty_reason(사장님 말 한 문장)을 더한다 (예시 세 곳은 리뷰가 있어 응답 그대로).
    EMPTY_REASON = "아직 리뷰가 없어요. 리뷰를 붙여넣거나 캡처로 넣으면 분석을 시작해요."
    NO_CARD_A = "같은 불만이 3건 이상 모이면 불만 카드를 만들어요. 아직 반복된 불만이 없어요."
    NO_CARD_B_REGISTERED = "우리 가게 상권 지표가 아직 없어 쿠폰 홍보 카드는 만들지 않았어요. 상권 분석 화면에서 상권 숫자는 볼 수 있어요."

    @property
    def registered(self) -> bool:
        return store_profiles.is_registered_id(self.s.store_id)

    def _with_empty(self, out: dict, insight: dict) -> dict:
        if self.registered and not insight.get("review_count"):
            out["empty_reason"] = self.EMPTY_REASON
        return out

    def cards(self, visitor: str | None = None) -> dict:
        st = self._state(visitor)
        plans = self._plans(st)
        out = {"cards": [p.to_dict() for p in plans],
               "no_card_b": why_no_card_b(st["snapshots"], self.s.card_b_snapshot_id, self.s.card_b_threshold)}
        if self.registered:
            # 등록 가게는 상권 지표 파일이 아직 없다: 개발용 문장(C4 파일) 대신 사장님 말로. 불만 카드가 없으면 그 이유도
            if out["no_card_b"] and not st["snapshots"]:
                out["no_card_b"] = self.NO_CARD_B_REGISTERED
            if not any(p.card.kind == "complaint" for p in plans):
                out["no_card_a"] = self.EMPTY_REASON if not st["insight"].get("review_count") else self.NO_CARD_A
        return self._with_empty(out, st["insight"])

    def _plans(self, st: dict) -> list[CardPlan]:
        writer = self._reason_writer if self.s.mode == "live" else None
        # 카드 ⓑ 의 손님 칭찬 근거: C6 에 넘기는 것과 같은 가게·리뷰(_contract_inputs)로 고른다 → 카드가 말한 메뉴 == 홍보글 쿠폰 메뉴.
        # 변환이 안 되는 리뷰가 있어도 카드는 뜨게 한다 (칭찬 근거 없이 예전 카드)
        try:
            store, reviews = self._contract_inputs(st)
            praise = praised_coupon_menu(store, reviews)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            log.warning("리뷰를 읽지 못해 카드 ⓑ 에 칭찬 근거를 붙이지 않아요 (%s)", exc.__class__.__name__)
            store = reviews = praise = None
        if praise and self.s.mode == "mock":
            # mock 의 홍보글은 저장 예시라 쿠폰 메뉴가 정해져 있다. 붙여넣은 칭찬 리뷰로 고른 메뉴가 그 메뉴와 달라지면
            # 카드가 다른 메뉴를 말하게 되므로 칭찬 근거를 붙이지 않는다 (live 는 고른 메뉴로 홍보글을 새로 쓴다)
            saved = {e for d in self.seed.get("promo", {}).get("drafts", []) for e in d.get("evidence_ids", [])
                     if e.startswith("coupon:")}
            if saved and f"coupon:{praise['menu']}" not in saved:
                store = reviews = praise = None
        # 묶음 전체(근거 문장 포함)를 열쇠에 넣는다. 방문자마다 붙여넣은 글이 다른데 리뷰 번호(…_paste_001)만 같으면
        # 한 방문자의 근거 문장이 다른 방문자에게 보일 수 있다. 내용이 같을 때만 같은 계획을 쓴다.
        # 칭찬 근거(고른 메뉴·건수·근거 리뷰 글)도 같은 이유로 넣는다: 붙여넣은 칭찬 리뷰가 카드 ⓑ 의 근거로 보인다.
        key = json.dumps([st["insight"].get("top_issue_id"), st["insight"].get("groups", []),
                          [s.to_dict() for s in st["snapshots"]], self.s.mode, praise], ensure_ascii=False, sort_keys=True)
        with self._lock:
            plans = self._reason_memo.get(key)
            if plans is None:   # live 에서 GET 마다 HCX 를 다시 부르지 않게
                plans = plan_cards(st["insight"], st["snapshots"], self.s.store_id, preferred_id=self.s.card_b_snapshot_id,
                                   threshold=self.s.card_b_threshold, store=store, reviews=reviews)
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
    REASON_TODO = {"complaint": "같은 불만이 다시 안 생기게 배달앱 포장·주문 안내문을 올리고, 답글도 함께 달아요.",
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
    def run(self, card_id: str, measures: list[str] | None = None, visitor: str | None = None,
            generator: str | None = None, review_id: str | None = None, reply_texts: list[str] | None = None,
            replaces: list[str] | None = None) -> dict:
        """measures: 사장님이 고른 재발 방지 조치 id. None 이면 카드의 기본값 (불만 카드만 씀).
        generator: 있으면 그 종류의 글 한 건만 다시 만든다 (개별 다시 만들기, _run_one). 없으면 예전 그대로 카드 전체.
        replaces: 이 생성으로 바뀌는 옛 글 id (화면이 다시 만들 때 보냄). 생성이 성공한 뒤에만 이 방문자의 승인 기록에서
        그 글들을 지우고 응답에 replaced_approvals(지운 수)를 싣는다. 생성이 실패하면(오류 응답) 아무것도 지우지 않는다."""
        old = self._check_replaces(replaces)   # 모양이 틀리면 글을 만들기 전에 400
        st = self._state(visitor)
        plan = next((p for p in self._plans(st) if p.card.card_id == card_id), None)
        if plan is None:
            raise DemoError(f"카드 {card_id} 가 지금 화면의 카드가 아니에요. 새로 고침 하세요.", status=404)
        if generator is not None:
            made = self._run_one(st, plan, generator, review_id, measures, reply_texts)
            self._remember_drafts(card_id, made)
            return self._replaced(made, visitor, old)
        card = plan.card
        if self.s.mode == "mock":
            result = self._mock_result(st, card)
            if result is None:
                raise DemoError("이 카드에 맞는 저장본이 없어요 (붙여넣기로 묶음이 바뀌었을 수 있어요). "
                                "키가 있으면 APP_MODE=live 로 생성하세요.", status=404)
            self._mock_measures(result, plan, measures)
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
            except DemoError:
                raise
            except Exception as exc:   # HCX 호출 쪽의 예상 못한 오류. 500 대신 화면 알림 띠로 보이게 한다
                log.exception("글 생성 중 예상 못한 오류 (%s)", exc.__class__.__name__)
                raise DemoError("글을 만들다가 문제가 생겼어요. 잠시 뒤 다시 눌러 주세요.", status=502) from None
        made = summarize(result)
        self._remember_drafts(card_id, made)
        return self._replaced(made, visitor, old)

    def _mock_result(self, st: dict, card) -> dict | None:
        """mock: 기본 가게(저장본을 만든 온기한식)는 저장본을 카드에 맞춰 쓰고, 다른 가게는 코드 틀 글 (11/18)."""
        if self.s.store_id == SEED_STORE_ID:
            return adapt_seed(self.seed[card.kind], card) if card.kind in self.seed else None
        store, reviews = self._contract_inputs(st)
        found = praised_coupon_menu(store, reviews) if card.kind == "promo" else None
        return mock_template(card, store, reviews, st["snapshots"], coupon_menu=(found or {}).get("menu"))

    def _mock_measures(self, result: dict, plan: CardPlan, measures: list[str] | None) -> None:
        """mock: 사장님이 고른 조치를 응답(chosen_measures)에 싣는다. 화면이 '오늘부터 실천할 수칙'으로 보여 준다 (초안·완료 화면).
        저장 예시 글은 고른 조치와 상관없이 그대로다. 그래서 화면은 mock 에서 '글에 반영'이라고 말하지 않는다 (frontend/src/features/flow 의 Draft·Done).
        조치 상자가 없는 카드는 건드리지 않는다 (저장 예시 값 그대로). 모르는 id 는 예전처럼 오류 없이 뺀다 (mock 은 measures 를 검사하지 않는다)."""
        options = {o["id"]: o for o in plan.measures.get("options") or []}
        if plan.card.kind != "complaint" or not options:
            return
        ids = plan.measures.get("default", []) if measures is None else measures
        result["chosen_measures"] = [dict(options[i]) for i in dict.fromkeys(ids) if i in options]

    # ── ③ 개별 다시 만들기 ───────────────────────────────────────────
    def _run_one(self, st: dict, plan: CardPlan, generator: str, review_id: str | None,
                 measures: list[str] | None, reply_texts: list[str] | None) -> dict:
        """카드의 글 한 건만 다시 만든다 (초안 상자의 '다시 만들기'). 다른 글은 만들지도 건드리지도 않는다.
        응답은 전체 실행과 같은 모양인데 drafts 에 그 한 건만 있고, partial=True 와 regenerated={generator, review_id, pasted} 가 붙는다.
        답글은 카드 묶음 리뷰의 것인지 붙여넣은 리뷰의 것인지 가려, 각각 전체 실행 때와 같은 조건으로 만든다."""
        card = plan.card
        if generator not in CARD_GENERATORS.get(card.kind, ()):
            raise DemoError(f"이 카드에서 만드는 글이 아니에요: {generator}", status=400)
        if generator != "reply_draft":
            review_id = None
        elif not review_id:
            raise DemoError("어느 리뷰의 답글을 다시 만들지(review_id) 알려 주세요.", status=400)
        not_target = "그 리뷰는 이 카드에서 답글을 만드는 리뷰가 아니에요. 새로 고침 하세요."
        pasted = False
        if self.s.mode == "mock":
            result = self._mock_result(st, card)
            if result is None:
                raise DemoError("이 카드에 맞는 저장본이 없어요 (붙여넣기로 묶음이 바뀌었을 수 있어요). "
                                "키가 있으면 APP_MODE=live 로 생성하세요.", status=404)
            self._mock_measures(result, plan, measures)
            draft = pick_seed_draft(result, generator, review_id)
            result["drafts"] = [draft] if draft else []
            if draft is None and generator != "reply_draft":
                raise DemoError("저장 예시에 이 글이 없어요. 키가 있으면 APP_MODE=live 로 생성하세요.", status=404)
            if draft is None:   # 묶음 리뷰의 답글이 아니면 붙여넣은 리뷰의 답글 (같은 글의 저장 예시가 있을 때만)
                target = [r for r in self._pasted_targets(st, card) if r.review_id == review_id]
                if not target:
                    raise DemoError(not_target, status=404)
                drafts, skipped = seed_pasted_replies(self.pasted_examples, card, target)
                if not drafts:
                    raise DemoError(f"이 리뷰의 답글은 지금 다시 만들 수 없어요 ({skipped[0]['reason']})", status=404)
                add_pasted_replies(result, drafts, [], note="붙여넣은 리뷰 답글은 같은 글로 미리 만든 저장 예시")
                pasted = True
        else:
            store, reviews = self._contract_inputs(st)
            review, index = None, 0
            if generator == "reply_draft":
                found = reply_order(card, reviews, review_id)
                if found is None:
                    raise DemoError(not_target, status=404)
                review, index, pasted = found
            ids = plan.measures.get("default", []) if measures is None else measures
            try:
                chosen = pick_measures(ids) if card.kind == "complaint" else []
                result = run_live_one(card, generator, store=store, reviews=reviews, snapshots=st["snapshots"],
                                      key=self.s.clova_key, model=self.s.model, chosen_measures=chosen, review=review,
                                      index=index, reply_texts=[t[:2000] for t in reply_texts or [] if isinstance(t, str)])
            except GenerateError as exc:
                raise DemoError(str(exc)) from None
            except Exception as exc:   # 전체 실행과 같다: 500 대신 화면 알림 띠로 보이게 한다
                log.exception("글 한 건을 다시 만들다가 예상 못한 오류 (%s)", exc.__class__.__name__)
                raise DemoError("글을 만들다가 문제가 생겼어요. 잠시 뒤 다시 눌러 주세요.", status=502) from None
            if pasted:
                result["pasted_reply_review_ids"], result["pasted_reply_skipped"] = [review_id], []
        made = summarize(result)
        made["partial"] = True
        made["regenerated"] = {"generator": generator, "review_id": review_id, "pasted": pasted}
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
                    self._drafts[draft["draft_id"]] = (card_id, draft.get("generator"), draft.get("target_review_id"))
                    checks = draft.get("checks") if isinstance(draft.get("checks"), dict) else {}
                    self._draft_info[draft["draft_id"]] = {
                        "draft_text": draft.get("text") if isinstance(draft.get("text"), str) else None,
                        "checks": checks, "used_fallback": checks.get("used_fallback") is True, "style": draft.get("style")}
            while len(self._drafts) > DRAFT_MAX:
                self._drafts.popitem(last=False)
            while len(self._draft_info) > DRAFT_MAX:
                self._draft_info.popitem(last=False)

    # 옛 글 id 모양 (replaces). 리뷰 id 와 같은 규칙: C6 의 'd_' + 16진수 8자리, 저장 예시 'd_ex_unfair01_001' 이 모두 들어간다.
    # 승인 API 는 어떤 문자열이든 받지만(1.6), 지우는 쪽은 모양을 본다 (이상한 값으로 DB 를 부르지 않게)
    DRAFT_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")

    @classmethod
    def _check_replaces(cls, replaces) -> list[str] | None:
        """replaces 검사. None 이면 None(지우지 않음, 응답에 replaced_approvals 도 없음). 틀리면 400 (글을 만들기 전에)."""
        if replaces is None:
            return None
        if not isinstance(replaces, (list, tuple)):
            raise DemoError("바꿀 옛 글 id(replaces)는 목록으로 보내 주세요.", status=400)
        if len(replaces) > REPLACES_MAX:
            raise DemoError(f"바꿀 옛 글 id(replaces)는 한 번에 {REPLACES_MAX}개까지예요.", status=400)
        if any(not isinstance(x, str) or not cls.DRAFT_ID.fullmatch(x) for x in replaces):
            raise DemoError("바꿀 옛 글 id(replaces)의 모양이 맞지 않아요. 새로 고침 하세요.", status=400)
        return list(dict.fromkeys(replaces))

    def _replaced(self, made: dict, visitor: str | None, old: list[str] | None) -> dict:
        """생성이 끝난 뒤: 바뀐 옛 글의 승인 기록을 지우고 지운 수를 싣는다. 지우지 못해도 새 글은 그대로 돌려준다
        (replaced_approvals: 0 과 replace_warning). 화면은 이미 옛 글을 버렸으니 생성까지 실패시키지 않는다."""
        if old is None:
            return made
        try:
            made["replaced_approvals"] = self.forget_approvals(visitor, old)
        except DemoError as exc:
            made["replaced_approvals"] = 0
            made["replace_warning"] = str(exc)
        return made

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
        known = self._drafts.get(draft_id, (None, None, None))
        with self._lock:
            info = self._draft_info.get(draft_id)
        # 초안 정보: 이 서버가 ③ 에서 기억한 것. 모르는 초안(다른 서버가 만든 것, 맞춤 마케팅 글)이면 화면이 보낸 원문만
        detail = dict(info) if info else {"draft_text": None}
        if detail.get("draft_text") is None:
            detail["draft_text"] = original
        warning = self._save_approval(clean_visitor_id(visitor), entry, card_id or known[0], kind or known[1], detail)
        if warning:
            entry["warning"] = warning
        return entry

    REVIEW_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")

    def reply_target(self, draft_id: str, kind: str | None = None, review_id: str | None = None) -> str | None:
        """승인한 글이 리뷰 답글이면 그 리뷰 id, 아니면 None. 이 서버가 ③ 에서 기억한 값이 먼저이고,
        모르는 초안(다른 서버가 만든 것)이면 화면이 보낸 종류·리뷰 id 를 쓴다. 형식이 틀린 값은 무시한다."""
        _, generator, target = self._drafts.get(draft_id, (None, None, None))
        if generator is None:
            generator, target = kind, review_id
        if generator != "reply_draft" or not isinstance(target, str) or not self.REVIEW_ID.fullmatch(target):
            return None
        return target

    def _save_approval(self, visitor_id: str, entry: dict, card_id: str | None, kind: str | None,
                       detail: dict | None = None) -> str | None:
        """승인 기록을 남긴다. 못 남기면 이유 문장을 돌려준다 (기록은 화면에만 남는다).
        detail(초안 정보)은 저장소에만 넘긴다. 응답(entry)과 approvals.jsonl 의 모양은 그대로다."""
        store_id = self.s.store_id
        if self.storage.kind == "memory":   # 기본: 서버 메모리 + 파일에 덧붙임
            self.storage.approvals.save(store_id, visitor_id, entry, card_id=card_id, kind=kind, detail=detail)
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
            self._pending.append((visitor_id, entry, card_id, kind, detail))
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
            for i, (visitor_id, entry, card_id, kind, detail) in enumerate(waiting):
                try:
                    self.storage.approvals.save(self.s.store_id, visitor_id, entry, card_id=card_id, kind=kind, detail=detail)
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

    def clear_approvals(self, visitor: str | None = None) -> int:
        """이 방문자의 승인 기록을 모두 지운다 (완료 화면의 '처음부터 다시'). 지운 건수를 돌려준다.
        다른 방문자의 기록은 건드리지 않는다. DB 에 아직 못 써서 이 서버가 들고 있던 것(_pending)도 같이 버린다.
        메모리 방식의 approvals.jsonl 은 덧붙이기만 하는 기록 파일이라 그대로 두고, 답글 승인 때 리뷰 분석 서비스에
        남긴 '답글 달았음' 기록도 여기서 지우지 않는다."""
        visitor_id = clean_visitor_id(visitor)
        if self._pending:
            self._flush_pending()   # 밀린 것이 DB 에 들어가 있어야 아래에서 같이 지워지고 건수도 맞는다
        with self._flush_lock:      # 지우는 사이에 다른 요청이 밀린 기록을 다시 써넣지 못하게 한다
            try:
                deleted = self.storage.approvals.clear(self.s.store_id, visitor_id)
            except Exception as exc:   # DB 에 닿지 못함 등. 지운 것이 없으니 들고 있던 것도 그대로 둔다
                log.warning("승인 기록을 지우지 못했어요 (%s)", exc.__class__.__name__)
                raise DemoError("승인 기록을 지우지 못했어요. 잠시 뒤 다시 눌러 주세요.", status=503) from None
            with self._lock:
                held = {p[1]["draft_id"] for p in self._pending if p[0] == visitor_id}
                self._pending = [p for p in self._pending if p[0] != visitor_id]
        return deleted + len(held)

    def forget_approvals(self, visitor: str | None, draft_ids) -> int:
        """다시 만들어 바뀐 옛 글(draft_ids)의 승인 기록만 지운다 (개별·카드 전체 다시 만들기, 11/16). 지운 건수를 돌려준다.
        이 방문자의 그 글들만 지운다 (다른 방문자·다른 글은 그대로). DB 에 아직 못 써서 이 서버가 들고 있던 것(_pending)에서도
        뺀다 — 두면 DB 가 돌아왔을 때 옛 글의 승인이 다시 써진다. clear_approvals 와 달리 DB 에 닿지 못해도 들고 있던 것은
        버린다 (화면은 이미 그 글을 버렸고 다시 누를 버튼이 없다). 그때는 DemoError(503)를 낸다.
        approvals.jsonl(메모리 방식의 덧붙이기 기록)과 리뷰 분석 서비스의 '답글 달았음' 기록은 clear_approvals 처럼 그대로 둔다."""
        wanted = set(draft_ids or ())
        if not wanted:
            return 0
        visitor_id = clean_visitor_id(visitor)
        if self._pending:
            self._flush_pending()   # 밀린 것이 DB 에 들어가 있어야 아래에서 같이 지워지고 건수도 맞는다
        with self._flush_lock:      # 지우는 사이에 다른 요청이 밀린 기록을 다시 써넣지 못하게 한다
            with self._lock:
                held = {p[1]["draft_id"] for p in self._pending if p[0] == visitor_id and p[1]["draft_id"] in wanted}
                self._pending = [p for p in self._pending if not (p[0] == visitor_id and p[1]["draft_id"] in wanted)]
            try:
                deleted = self.storage.approvals.delete(self.s.store_id, visitor_id, sorted(wanted))
            except Exception as exc:   # DB 에 닿지 못함 등
                log.warning("옛 글의 승인 기록을 지우지 못했어요 (%s)", exc.__class__.__name__)
                raise DemoError("옛 글의 승인 기록을 서버에서 지우지 못했어요. 새 글은 그대로 쓸 수 있어요.", status=503) from None
        return deleted + len(held)

    @property
    def approvals(self) -> list[dict]:
        """방문자를 가리지 않는 공용 승인 기록 (예전 이름)."""
        return self.list_approvals()

    # ── S2 붙여넣기 ─────────────────────────────────────────────────
    def paste(self, text: str, rating: int | None, channel: str | None, visitor: str | None = None,
              source: str = "paste") -> dict:
        """source: paste(붙여넣기) | capture(캡처 후보를 사장님이 확인해 저장). 리뷰 분석 서비스는 둘 다 계약대로 input_method="paste" 로
        저장하고 source 칸만 다르다. 붙여넣기는 예전과 똑같이 부른다 (source 를 보내지 않음)."""
        extra = {"source": source} if source != "paste" else {}
        try:
            return self._src(visitor).paste(self.s.store_id, text, rating, channel, **extra)
        except SourceError as exc:
            raise DemoError(str(exc), 503) from None

    def reset_pasted(self, visitor: str | None = None) -> dict:
        try:
            return self._src(visitor).reset_pasted(self.s.store_id)
        except SourceError as exc:
            raise DemoError(str(exc), 503) from None

    def erase_pasted(self, visitor: str) -> int:
        """계정 초기화·탈퇴용 (11/19): 이 방문자가 이 가게에 붙여넣은 리뷰·상태·답글 기록과 그 리뷰들의 분류 결과를 지운다.
        지운 리뷰 수. 리뷰 분석 서비스가 분류 결과를 지웠다고 답하지 않으면(옛 판 등) 다 지운 것으로 보지 않고 DemoError(503)."""
        if not visitor:
            raise DemoError("방문자 없이 기록을 지울 수 없어요", 400)      # 공용 기록을 지우지 않게
        try:
            data = self._src(visitor).reset_pasted(self.s.store_id, forget_labels=True)
        except SourceError as exc:
            raise DemoError(str(exc), 503) from None
        if not isinstance(data, dict) or not isinstance(data.get("deleted"), int) or not isinstance(data.get("labels_deleted"), int):
            raise DemoError("리뷰 분석 서비스가 분류 결과를 지웠다고 답하지 않았어요", 503)
        return data["deleted"]
