"""Measure the question classifier on tests/assistant_intent_cases.json.

    python -m scripts.eval_intent              # rules only, and Kiwi if installed
    python -m scripts.eval_intent --failures   # also print every wrong field
    python -m scripts.eval_intent --json       # machine-readable summary
    python -m scripts.eval_intent --cases tests/assistant_intent_blind_cases.json

Reads only local files. No network, no model, nothing is written.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "assistant_intent_cases.json"
FIELDS = ("domain", "turn_type", "topics", "locations", "location_mentions", "industries", "period", "signals",
          "business_status", "needs_user_choice", "needs_model")


def actual_value(result: dict, field: str):
    from app.assistant.intent import industry_codes, location_labels

    if field == "locations":
        return location_labels(result)
    if field == "location_mentions":
        return [m["text"] for m in result["slots"]["locations"]]
    if field == "industries":
        return industry_codes(result)
    if field == "period":
        return result["slots"]["period"]
    if field == "business_status":
        return result["slots"]["business_status"]
    return result[field]


def matches(field: str, expected, actual) -> bool:
    if field == "location_mentions":
        from app.assistant.lexicon import compact

        return sorted(compact(item) for item in expected) == sorted(actual)
    if field in ("topics", "locations", "industries"):
        return sorted(expected) == sorted(actual)
    if field == "signals":
        return all(actual.get(key) == value for key, value in expected.items())
    return expected == actual


def evaluate(cases: dict, *, use_morph: bool) -> dict:
    from app.assistant.intent import classify

    today = date.fromisoformat(cases["today"])
    per_field = {field: [0, 0] for field in FIELDS}
    exact, failures, analyzer = 0, [], None
    for case in cases["cases"]:
        result = classify(case["text"], context=case.get("context"), today=today, use_morph=use_morph)
        analyzer = result["analyzer"]
        wrong = []
        for field, expected in case["expect"].items():
            actual = actual_value(result, field)
            per_field[field][1] += 1
            if matches(field, expected, actual):
                per_field[field][0] += 1
            else:
                wrong.append({"field": field, "expected": expected, "actual": actual})
        if not wrong:
            exact += 1
        else:
            failures.append({"id": case["id"], "text": case["text"], "wrong": wrong, "reasons": result["reasons"]})
    return {"analyzer": analyzer, "cases": len(cases["cases"]), "exact": exact,
            "per_field": {field: {"correct": c, "checked": n} for field, (c, n) in per_field.items() if n},
            "failures": failures}


def kiwi_available() -> bool:
    try:
        import kiwipiepy  # noqa: F401
    except ImportError:
        return False
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--failures", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--cases", type=Path, default=CASES, help="평가 사례 JSON (기본: tests/assistant_intent_cases.json)")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    runs = [evaluate(cases, use_morph=False)]
    if kiwi_available():
        runs.append(evaluate(cases, use_morph=True))
    if args.json:
        print(json.dumps(runs, ensure_ascii=False, indent=2))
        return 0
    header = f"{'항목':<18}" + "".join(f"{run['analyzer']:>14}" for run in runs)
    print(header)
    print(f"{'사례 전체 일치':<16}" + "".join(f"{run['exact']:>9}/{run['cases']:<4}" for run in runs))
    for field in FIELDS:
        cells = []
        for run in runs:
            stat = run["per_field"].get(field)
            cells.append(f"{stat['correct']:>9}/{stat['checked']:<4}" if stat else f"{'-':>14}")
        print(f"{field:<18}" + "".join(cells))
    if args.failures:
        for run in runs:
            print(f"\n[{run['analyzer']}] 틀린 사례 {len(run['failures'])}건")
            for failure in run["failures"]:
                print(f"- {failure['id']} {failure['text']}")
                for item in failure["wrong"]:
                    print(f"    {item['field']}: 정답 {item['expected']} / 결과 {item['actual']}")
                if failure["reasons"]:
                    print(f"    근거: {'; '.join(failure['reasons'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
