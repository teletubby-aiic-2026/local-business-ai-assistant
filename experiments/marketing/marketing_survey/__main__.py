"""설문 맞춤 마케팅 — 가상 매장(온기한식) 설문 3개를 실제 CLOVA 호출로 돌려 결과를 저장한다.

실행 방법
  python -m marketing_survey --live   (CLOVA_API_KEY 필요. 없으면 실행하지 않고 안내만 출력)

결과: results/marketing_survey_results.md
  설문 3개 = 포장 누락 반복(H_REPEAT 확인) / 저녁 매출 하락·할인 가능(H_AREA_DROP 확인) / 할인 불가
  각각 결정 카드(explain 3줄) + 실제 생성 글(또는 사장님 할 일)을 적는다.
"""

import argparse
import os
import sys

import config
from c6.contract import build_context
from c6.dummy import OWNER_REPLIES, POLICIES
from marketing_survey.decide import decide
from marketing_survey.execute import execute_strategy
from marketing_survey.explain import explain_strategy
from marketing_survey.models import SurveyAnswers
from shared.sample_scenario import (
    SAMPLE_CARDS, SAMPLE_REVIEWS, SAMPLE_SNAPSHOTS, SAMPLE_STORE, SAMPLE_TONE,
)

CTX = build_context(
    store=SAMPLE_STORE, reviews=list(SAMPLE_REVIEWS), tone=SAMPLE_TONE,
    cards=list(SAMPLE_CARDS), snapshots=list(SAMPLE_SNAPSHOTS),
    owner_replies=OWNER_REPLIES, policies=POLICIES,
)

SCENARIOS = [
    (
        "포장 누락 반복",
        SurveyAnswers(
            budget_won=100_000, goal="재주문", discount_menu="제육볶음 정식", max_discount_won=5_000,
            capacity="충분", discount_allowed=True,
        ),
        {"H_REPEAT": "예"},
    ),
    (
        "저녁 매출 하락 · 할인 가능",
        SurveyAnswers(
            budget_won=100_000, goal="새 손님", discount_menu="제육볶음 정식", max_discount_won=5_000,
            capacity="충분", discount_allowed=True,
        ),
        {"H_REPEAT": "아니요", "H_AREA_DROP": "예"},
    ),
    (
        "할인 불가",
        SurveyAnswers(
            budget_won=100_000, goal="객단가", discount_menu="제육볶음 정식", max_discount_won=5_000,
            capacity="충분", discount_allowed=False,
        ),
        {"H_REPEAT": "아니요"},
    ),
]


def run_live(key: str) -> str:
    lines = ["# 설문 맞춤 마케팅 — 가상 매장 3개 (live)", ""]
    for name, answers, confirms in SCENARIOS:
        plan = decide(CTX, answers, confirms=confirms)
        lines.append(f"## {name}")
        for strat in plan.strategies:
            lines.append(f"### {strat.title} ({strat.type})")
            for line in explain_strategy(strat):
                lines.append(f"- {line}")
            _, draft, todo = execute_strategy(CTX, strat, key)
            if draft is not None:
                lines.append(f"- 글: {draft.text}")
            elif todo:
                lines.append(f"- ⚠ {todo}")
            lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    if not args.live:
        print("사용법: python -m marketing_survey --live")
        return

    key = os.environ.get("CLOVA_API_KEY")
    if not key:
        print("CLOVA_API_KEY 가 없어 실행하지 않습니다.")
        return

    report = run_live(key)
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.RESULTS_DIR / "marketing_survey_results.md"
    path.write_text(report, encoding="utf-8")
    print(f"결과 저장: {path}")


if __name__ == "__main__":
    sys.exit(main())
