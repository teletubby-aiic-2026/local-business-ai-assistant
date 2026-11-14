"""C6→C7 생성 결과물 형식."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_VALID_GENERATORS = ("reply_draft", "prevention_notice", "coupon_promo")
_VALID_STATUSES = ("draft", "edited", "approved")
_VALID_STANCES = ("apology", "explain")   # c6.stance.STANCES 와 같아야 한다 (시험이 확인)


@dataclass
class DraftOutput:
    draft_id: str
    card_id: str
    store_id: str
    generator: str
    text: str
    target_review_id: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    failed_reasons: list[str] = field(default_factory=list)
    rewrites: int = 0
    needs_input: list[str] = field(default_factory=list)
    status: str = "draft"
    edited_text: str | None = None
    model: str | None = None
    elapsed_ms: int = 0
    data_origin: str = "synthetic"
    # 답글 태도 (reply_draft 전용, 그 외는 None): "apology" 사과 답글 | "explain" 사과 없이 사실·원칙을 설명 (c6.stance)
    stance: str | None = None
    stance_reasons: list[str] = field(default_factory=list)   # 태도를 그렇게 정한 근거 (사장님 확인용)

    def __post_init__(self) -> None:
        if not self.draft_id:
            raise ValueError("DraftOutput.draft_id는 비어 있을 수 없습니다")
        if not self.card_id:
            raise ValueError("DraftOutput.card_id는 비어 있을 수 없습니다")
        if not self.store_id:
            raise ValueError("DraftOutput.store_id는 비어 있을 수 없습니다")
        if self.generator not in _VALID_GENERATORS:
            raise ValueError(
                f"DraftOutput.generator는 {_VALID_GENERATORS} 중 하나여야 합니다"
                f" (받은 값: {self.generator!r})"
            )
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"DraftOutput.status는 {_VALID_STATUSES} 중 하나여야 합니다"
                f" (받은 값: {self.status!r})"
            )
        if self.stance is not None and self.stance not in _VALID_STANCES:
            raise ValueError(
                f"DraftOutput.stance는 {_VALID_STANCES} 중 하나거나 None이어야 합니다"
                f" (받은 값: {self.stance!r})"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "card_id": self.card_id,
            "store_id": self.store_id,
            "generator": self.generator,
            "target_review_id": self.target_review_id,
            "text": self.text,
            "evidence_ids": list(self.evidence_ids),
            "checks": dict(self.checks),
            "failed_reasons": list(self.failed_reasons),
            "rewrites": self.rewrites,
            "needs_input": list(self.needs_input),
            "status": self.status,
            "edited_text": self.edited_text,
            "model": self.model,
            "elapsed_ms": self.elapsed_ms,
            "data_origin": self.data_origin,
            "stance": self.stance,
            "stance_reasons": list(self.stance_reasons),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DraftOutput:
        if not isinstance(data, dict):
            raise ValueError(f"DraftOutput.from_dict는 dict를 받습니다 (받은 값: {type(data).__name__})")
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CardResult:
    card_id: str
    kind: str
    reason_text: str
    basis_label: str | None = None
    drafts: list[DraftOutput] = field(default_factory=list)
    chosen_measures: list[dict] = field(default_factory=list)
    elapsed_ms: int = 0
    won: float = 0.0

    def __post_init__(self) -> None:
        if not self.card_id:
            raise ValueError("CardResult.card_id는 비어 있을 수 없습니다")
        if not self.kind:
            raise ValueError("CardResult.kind는 비어 있을 수 없습니다")
        if not self.reason_text:
            raise ValueError("CardResult.reason_text는 비어 있을 수 없습니다")

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "kind": self.kind,
            "reason_text": self.reason_text,
            "basis_label": self.basis_label,
            "drafts": [d.to_dict() for d in self.drafts],
            "chosen_measures": list(self.chosen_measures),
            "elapsed_ms": self.elapsed_ms,
            "won": self.won,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CardResult:
        if not isinstance(data, dict):
            raise ValueError(f"CardResult.from_dict는 dict를 받습니다 (받은 값: {type(data).__name__})")
        d = dict(data)
        if "drafts" in d:
            d["drafts"] = [DraftOutput.from_dict(x) for x in d["drafts"]]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
