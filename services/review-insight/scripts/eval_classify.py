"""분류 결과를 정답 라벨과 비교해 맞힌 비율을 봅니다 (발표·멘토링용 숫자).

services/review-insight 에서:
  python -m scripts.eval_classify            # .env 의 APP_MODE 로 (mock 이면 규칙 분류기 평가)
  APP_MODE=live python -m scripts.eval_classify   # HCX-005 평가 + data/replay/classify.json 저장 (발표 재생용)
"""
from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from app import service  # noqa: E402
from app.classify import Classifier  # noqa: E402
from app.cluster import build_insight  # noqa: E402

EXPECTED_ISSUES = {"delivery_time", "temperature", "portion", "packaging"}


def main():
    clf = Classifier()
    rows = service.sample_reviews()
    labels = {l["review_id"]: l for l in json.loads((service.SYNTHETIC / "labels.json").read_text(encoding="utf-8"))}
    res = clf.classify(rows)
    sent_ok = tp = fp = fn = 0
    wrong = []
    for c in res:
        lab = labels[c.review_id]
        got = {(t.topic, t.polarity) for t in c.topics}
        exp = {(t["topic"], t["polarity"]) for t in lab["expected_topics"]}
        sent_ok += c.sentiment == lab["expected_sentiment"]
        tp, fp, fn = tp + len(got & exp), fp + len(got - exp), fn + len(exp - got)
        if got != exp or c.sentiment != lab["expected_sentiment"]:
            text = next(r.text for r in rows if r.review_id == c.review_id)
            wrong.append(f"  {c.review_id} {text}\n     모델 {sorted(got)} {c.sentiment} ({c.method})\n     정답 {sorted(exp)} {lab['expected_sentiment']}")
    methods = {}
    for c in res:
        methods[c.method] = methods.get(c.method, 0) + 1
    precision, recall = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    issues = {i.topic for i in build_insight("eval", rows, res).repeated_issues}

    print(f"APP_MODE={clf.mode} 모델={clf.model} 방식별 건수={methods}")
    print(f"감정 정확도   {sent_ok}/{len(res)} = {sent_ok / len(res):.0%}")
    print(f"주제 정밀도   {precision:.0%} (찾은 것 중 맞은 비율)")
    print(f"주제 재현율   {recall:.0%} (정답 중 찾은 비율)")
    print(f"반복 묶음     찾음 {sorted(issues)} / 정답 {sorted(EXPECTED_ISSUES)} → {'일치' if issues == EXPECTED_ISSUES else '불일치'}")
    if wrong:
        print("\n틀린 리뷰")
        print("\n".join(wrong))


if __name__ == "__main__":
    main()
