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
from app.models import ReviewClassification, TopicHit  # noqa: E402



def label_classes(rows, labels):
    """정답 라벨을 분류 결과 모양으로 바꿈 → 정답 기준 반복 묶음을 계산하는 데 씀."""
    out = []
    for r in rows:
        lab = labels[r.review_id]
        hits = [TopicHit(t["topic"], t["polarity"], r.text) for t in lab["expected_topics"]]
        out.append(ReviewClassification(r.review_id, lab["expected_sentiment"], hits))
    return out


def evaluate(clf, store_id):
    rows = service.sample_reviews(store_id)
    labels = service.labels(store_id)
    res = clf.classify(rows)
    sent_ok = tp = fp = fn = 0
    wrong, methods = [], {}
    for c in res:
        methods[c.method] = methods.get(c.method, 0) + 1
        lab = labels[c.review_id]
        got = {(t.topic, t.polarity) for t in c.topics}
        exp = {(t["topic"], t["polarity"]) for t in lab["expected_topics"]}
        sent_ok += c.sentiment == lab["expected_sentiment"]
        tp, fp, fn = tp + len(got & exp), fp + len(got - exp), fn + len(exp - got)
        if got != exp or c.sentiment != lab["expected_sentiment"]:
            text = next(r.text for r in rows if r.review_id == c.review_id)
            wrong.append(f"  {c.review_id} {text}\n     결과 {sorted(got)} {c.sentiment} ({c.method})\n     정답 {sorted(exp)} {lab['expected_sentiment']}")
    mine, truth = build_insight(store_id, rows, res), build_insight(store_id, rows, label_classes(rows, labels))
    found = {(g.issue_id, g.review_count, g.is_repeated) for g in mine.groups}
    expected = {(g.issue_id, g.review_count, g.is_repeated) for g in truth.groups}
    brief = f"불만 {mine.complaint_count}(정답 {truth.complaint_count}) · 단발 {len(mine.single_complaints)}(정답 {len(truth.single_complaints)})"
    return {"n": len(res), "sent_ok": sent_ok, "tp": tp, "fp": fp, "fn": fn, "found": found, "expected": expected,
            "wrong": wrong, "methods": methods, "brief": brief}


def main():
    clf = Classifier()
    print(f"APP_MODE={clf.mode} 모델={clf.model}\n")
    total = {"n": 0, "sent_ok": 0, "tp": 0, "fp": 0, "fn": 0}
    all_wrong = []
    for sid in service.store_ids():
        r = evaluate(clf, sid)
        for k in total:
            total[k] += r[k]
        p, rc = r["tp"] / max(r["tp"] + r["fp"], 1), r["tp"] / max(r["tp"] + r["fn"], 1)
        fmt = lambda gs: ", ".join(f"{i.removeprefix('iss_')} {n}{'(반복)' if rep else ''}" for i, n, rep in sorted(gs))
        ok = "일치" if r["found"] == r["expected"] else f"불일치 → 찾음 [{fmt(r['found'])}]"
        print(f"[{service.store(sid)['name']}] {r['n']}건 · 감정 {r['sent_ok']}/{r['n']} · 주제 정밀도 {p:.0%} 재현율 {rc:.0%} · 방식 {r['methods']}\n"
              f"    {r['brief']} · 묶음 정답 [{fmt(r['expected'])}] → {ok}")
        all_wrong += r["wrong"]
    p = total["tp"] / max(total["tp"] + total["fp"], 1)
    rc = total["tp"] / max(total["tp"] + total["fn"], 1)
    print(f"\n[전체] {total['n']}건 · 감정 정확도 {total['sent_ok'] / total['n']:.0%} · 주제 정밀도 {p:.0%} · 재현율 {rc:.0%}")
    if all_wrong:
        print(f"\n틀린 리뷰 {len(all_wrong)}건")
        print("\n".join(all_wrong))


if __name__ == "__main__":
    main()
