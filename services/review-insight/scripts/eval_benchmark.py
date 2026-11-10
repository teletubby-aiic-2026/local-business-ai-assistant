"""리뷰 분류 벤치마크 채점 (data/benchmark/v1, 정답 기준은 GUIDE.md).

services/review-insight 에서:
  python -m scripts.eval_benchmark --split dev                    # APP_MODE(.env, 기본 mock) = kiwi 규칙 분류
  APP_MODE=live python -m scripts.eval_benchmark --split test     # HCX-005 + kiwi 참고 자료
  APP_MODE=live REVIEW_KIWI_HINTS=off python -m scripts.eval_benchmark --split test   # 참고 자료 없이 (비교)

- 시험용(test)은 점수를 낼 때만 씁니다. 틀린 리뷰를 보고 프롬프트·규칙을 고치는 건 연습용(dev)으로만 합니다.
- live 결과는 data/benchmark/v1/runs/replay_*.json 에 저장해 다시 채점할 때 모델을 또 부르지 않습니다
  (발표용 data/replay/classify.json 과 섞이지 않게 따로 둠).
- 점수표는 runs/score_<split>_<방식>.json, 틀린 리뷰는 runs/wrong_<split>_<방식>.txt 에 남깁니다.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from app import classify  # noqa: E402
from app.models import Review  # noqa: E402
from app.topics import mask_pii, topic_name  # noqa: E402

BENCH = ROOT / "data" / "benchmark" / "v1"
RUNS = BENCH / "runs"


def load(split: str):
    reviews = [Review.from_dict(d) for d in json.loads((BENCH / f"reviews_{split}.json").read_text(encoding="utf-8"))]
    labels = {d["review_id"]: d for d in json.loads((BENCH / f"labels_{split}.json").read_text(encoding="utf-8"))}
    return reviews, labels


def pr(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else 0.0 if (p is not None and r is not None) else None
    return {"precision": p, "recall": r, "f1": f, "tp": tp, "fp": fp, "fn": fn}


def score(reviews, labels, results) -> tuple[dict, list[str]]:
    by_id = {r.review_id: r for r in reviews}
    sent_ok = exact = 0
    tp = fp = fn = 0
    per_topic: dict[str, Counter] = defaultdict(Counter)
    per_tag: dict[str, Counter] = defaultdict(Counter)
    confusion: Counter = Counter()
    methods: Counter = Counter()
    wrong = []
    for c in results:
        lab = labels[c.review_id]
        got = {(t.topic, t.polarity) for t in c.topics}
        exp = {(t["topic"], t["polarity"]) for t in lab["expected_topics"]}
        s_ok = c.sentiment == lab["expected_sentiment"]
        sent_ok += s_ok
        exact += s_ok and got == exp
        a, b, d = len(got & exp), len(got - exp), len(exp - got)
        tp, fp, fn = tp + a, fp + b, fn + d
        confusion[(lab["expected_sentiment"], c.sentiment)] += 1
        methods[c.method] += 1
        for key in got | exp:
            name = f"{key[0]}{'+' if key[1] == 'positive' else '-'}"
            per_topic[name]["tp" if key in got and key in exp else "fp" if key in got else "fn"] += 1
        for tag in lab["tags"]:
            per_tag[tag].update({"n": 1, "sent_ok": int(s_ok), "tp": a, "fp": b, "fn": d})
        if not s_ok or got != exp:
            fmt = lambda s: " ".join(sorted(f"{topic_name(t)}{'+' if p == 'positive' else '-'}" for t, p in s)) or "없음"
            wrong.append(f"{c.review_id} [{','.join(lab['tags'])}] ★{by_id[c.review_id].rating or '-'} {by_id[c.review_id].text}\n"
                         f"   결과 {c.sentiment:<8} {fmt(got)}  ({c.method})\n   정답 {lab['expected_sentiment']:<8} {fmt(exp)}")
    n = len(results)
    pii = [r for r in reviews if "pii" in labels[r.review_id]["tags"]]
    pii_ok = sum(1 for r in pii if mask_pii(r.text)[1])
    out = {
        "n": n, "sentiment_accuracy": sent_ok / n, "exact_match": exact / n, "topics": pr(tp, fp, fn),
        "per_topic": {k: pr(v["tp"], v["fp"], v["fn"]) for k, v in sorted(per_topic.items())},
        "per_tag": {k: {"n": v["n"], "sentiment_accuracy": v["sent_ok"] / v["n"], **pr(v["tp"], v["fp"], v["fn"])}
                    for k, v in sorted(per_tag.items())},
        "sentiment_confusion": {f"{e}->{g}": k for (e, g), k in sorted(confusion.items()) if e != g},
        "methods": dict(methods), "pii_masked": f"{pii_ok}/{len(pii)}",
    }
    return out, wrong


def pct(x) -> str:
    return "  -  " if x is None else f"{x * 100:5.1f}%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--show-wrong", type=int, default=15, help="틀린 리뷰를 몇 개까지 화면에 보일지 (test 는 기본 0)")
    args = ap.parse_args()

    RUNS.mkdir(parents=True, exist_ok=True)
    clf = classify.Classifier()
    how = "rule" if clf.mode == "mock" else f"{clf.model}{'+kiwi' if clf.hints else ''}"
    if clf.mode != "mock":
        classify.REPLAY_FILE = RUNS / f"replay_{clf.model}_{'hints' if clf.hints else 'nohints'}_{classify.PROMPT_VERSION}.json"
    reviews, labels = load(args.split)
    if clf.mode != "mock":
        print(f"HCX 에 {len(reviews)}건을 나눠 보내는 중… (처음이면 5~15분, 저장된 결과는 다시 부르지 않음)", flush=True)
    started = datetime.now()
    results = clf.classify(reviews)
    if clf.mode != "mock":
        print(f"분류 끝: {(datetime.now() - started).seconds}초", flush=True)
    out, wrong = score(reviews, labels, results)
    out.update({"split": args.split, "how": how, "prompt_version": classify.PROMPT_VERSION,
                "benchmark": "v1", "at": datetime.now().isoformat(timespec="seconds")})
    (RUNS / f"score_{args.split}_{how}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (RUNS / f"wrong_{args.split}_{how}.txt").write_text("\n".join(wrong) + "\n", encoding="utf-8")

    t = out["topics"]
    print(f"벤치마크 v1 · {args.split} {out['n']}건 · {how} (프롬프트 {classify.PROMPT_VERSION}) · 분류 방식 {out['methods']}")
    print(f"  감정 정확도 {pct(out['sentiment_accuracy'])} · 완전 일치 {pct(out['exact_match'])} · "
          f"주제 정밀도 {pct(t['precision'])} 재현율 {pct(t['recall'])} F1 {pct(t['f1'])} · 개인정보 가림 {out['pii_masked']}")
    print("  주제별 (정밀도 / 재현율 / 정답 수)")
    for k, v in out["per_topic"].items():
        print(f"    {topic_name(k[:-1])}{k[-1]:<2} {pct(v['precision'])} / {pct(v['recall'])} / {v['tp'] + v['fn']}")
    print("  유형별 (감정 정확도 / 주제 F1 / 건수)")
    for k, v in out["per_tag"].items():
        print(f"    {k:<16} {pct(v['sentiment_accuracy'])} / {pct(v['f1'])} / {v['n']}")
    if out["sentiment_confusion"]:
        print("  감정 헷갈림 (정답->결과: 건수)", out["sentiment_confusion"])
    show = args.show_wrong if args.split == "dev" else 0
    if wrong and show:
        print(f"  틀린 리뷰 {len(wrong)}건 중 {min(show, len(wrong))}건 (전체는 runs/wrong_{args.split}_{how}.txt)")
        for w in wrong[:show]:
            print("  " + w.replace("\n", "\n  "))
    elif wrong:
        print(f"  틀린 리뷰 {len(wrong)}건은 runs/wrong_{args.split}_{how}.txt (시험용은 보면서 고치지 않기)")


if __name__ == "__main__":
    main()
