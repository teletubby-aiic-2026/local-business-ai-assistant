"""설문 맞춤 마케팅 데이터 모델 — dataclass. AI 호출 없음, 표준 라이브러리만."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any


def _filtered(cls, data: dict[str, Any]):
    """data 에 모델에 없는 키가 섞여 있어도 무시하고 받는다(c6.output.DraftOutput.from_dict 과 같은 방식)."""
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class SurveyAnswers:
    """marketing_survey.survey 의 설문 문항에 대한 사장님 응답."""

    budget_won: int = 0                         # 월 마케팅 예산(원)
    goal: str = ""                              # 새 손님 / 재주문 / 객단가 / 남는 재료 처리
    discount_menu: str | None = None            # 할인해도 되는 메뉴
    max_discount_won: int = 0                   # 그 메뉴의 최대 할인(원)
    capacity: str = "충분"                       # 충분 / 빠듯함
    apps: list[str] = field(default_factory=list)   # 쓰는 배달앱(복수)
    channels: list[str] = field(default_factory=list)   # 손님에게 알리는 채널(복수, 비우면 가게 채널 전부)
    discount_allowed: bool = True               # 할인 가능 여부(False면 쿠폰 대신 review_promo)
    weekly_hours: int = 0                       # 사장님이 마케팅에 쓸 수 있는 주당 시간(참고용)

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_won": self.budget_won, "goal": self.goal,
            "discount_menu": self.discount_menu, "max_discount_won": self.max_discount_won,
            "capacity": self.capacity, "apps": list(self.apps),
            "channels": list(self.channels), "discount_allowed": self.discount_allowed,
            "weekly_hours": self.weekly_hours,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SurveyAnswers:
        return _filtered(cls, data)


@dataclass
class Hypothesis:
    """근거 데이터에서 코드가 뽑은 가설 1개 + 사장님에게 확인할 질문."""

    id: str
    title: str
    evidence_ids: list[str] = field(default_factory=list)
    question: str = ""
    choices: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "evidence_ids": list(self.evidence_ids),
            "question": self.question, "choices": list(self.choices),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Hypothesis:
        return _filtered(cls, data)


@dataclass
class Strategy:
    """최종 전략 1개. generator 는 나중에 c6 쪽 생성기 이름(coupon_promo·prevention_notice 등).

    source_hypothesis: fix_first 가 어느 가설 확인에서 나왔는지(H_LATE/H_REPEAT/H_STORE_ONLY).
      execute.py 가 "H_REPEAT 의 fix_first 만 공지를 실제로 만든다"를 구분하는 데 쓴다.
    follow_up: fix_first 승인 뒤 이어서 제안할 전략 타입(예: "reorder_coupon"). 없으면 "".
    note: 수용력·상권 시간대처럼 서로 다른 신호가 충돌했을 때, 어느 쪽을 우선했는지 사람이 읽는 메모.
    channels: 이 전략을 알릴 채널(설문 channels 로 가게 채널을 거른 결과). 비우면 제한 없음.
    menu: 쿠폰형 전략이 쓰는 할인 메뉴 이름(coupon_promo 의 coupon_menu 로 그대로 넘어간다).
    """

    type: str
    title: str
    reason: str
    budget_won: int = 0
    count: int = 0
    discount_won: int = 0
    timing: str = ""
    generator: str = ""
    assumptions: list[str] = field(default_factory=list)
    source_hypothesis: str = ""
    follow_up: str = ""
    note: str = ""
    channels: list[str] = field(default_factory=list)
    menu: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type, "title": self.title, "reason": self.reason,
            "budget_won": self.budget_won, "count": self.count, "discount_won": self.discount_won,
            "timing": self.timing, "generator": self.generator, "assumptions": list(self.assumptions),
            "source_hypothesis": self.source_hypothesis, "follow_up": self.follow_up,
            "note": self.note, "channels": list(self.channels), "menu": self.menu,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Strategy:
        return _filtered(cls, data)


@dataclass
class MarketingPlan:
    """marketing_survey.decide.decide() 의 최종 결과물."""

    store_id: str
    answers: SurveyAnswers
    hypotheses: list[Hypothesis] = field(default_factory=list)
    confirms: dict[str, str] = field(default_factory=dict)      # hypothesis.id -> 사장님 확인 답변
    strategies: list[Strategy] = field(default_factory=list)
    total_budget: int = 0
    used_budget: int = 0
    needs_input: list[str] = field(default_factory=list)
    data_origin: str = "synthetic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "answers": self.answers.to_dict(),
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "confirms": dict(self.confirms),
            "strategies": [s.to_dict() for s in self.strategies],
            "total_budget": self.total_budget,
            "used_budget": self.used_budget,
            "needs_input": list(self.needs_input),
            "data_origin": self.data_origin,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MarketingPlan:
        d = dict(data)
        if isinstance(d.get("answers"), dict):
            d["answers"] = SurveyAnswers.from_dict(d["answers"])
        if "hypotheses" in d:
            d["hypotheses"] = [Hypothesis.from_dict(h) for h in d["hypotheses"]]
        if "strategies" in d:
            d["strategies"] = [Strategy.from_dict(s) for s in d["strategies"]]
        return _filtered(cls, d)
