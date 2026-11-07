"""Compare the AI planner with the rule classifier on an intent case file.

    python -m scripts.eval_planner --cases tests/assistant_intent_blind2_cases.json
    python -m scripts.eval_planner --cases <file> --limit 10 --failures

Calls CLOVA once per case (APP_MODE=live and CLOVA_STUDIO_API_KEY from .env;
the key is never printed). Each case is scored on what the planner decides:
the action (market data / area ranking / industry ranking / small talk / out
of scope / handoff / ask back) and, when the case names them, the places and
industries. Writes nothing.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]

_ACTION = {"data_question": "market_data", "condition_change": "market_data", "followup": "market_data",
           "ranking": "rank_areas", "industry_rank": "rank_industries", "smalltalk": "small_talk",
           "out_of_scope": "out_of_scope", "unknown": "ask_user", "clarify": "ask_user"}


def expected_action(expect: dict) -> str | None:
    if expect.get("domain") in ("marketing", "customer"):
        return "handoff"
    return _ACTION.get(expect.get("turn_type"))


def action_of(result: dict) -> str | None:
    if result.get("domain") in ("marketing", "customer"):
        return "handoff"
    return _ACTION.get(result.get("turn_type"))


def names(result: dict, kind: str) -> list[str]:
    from app.assistant.intent import industry_codes

    if kind == "industries":
        return industry_codes(result)
    return sorted(m["text"] for m in result["slots"]["locations"])


def score(case: dict, result: dict | None) -> dict:
    expect = case["expect"]
    marks = {}
    wanted = expected_action(expect)
    if wanted:
        marks["action"] = result is not None and action_of(result) == wanted
    if "location_mentions" in expect and wanted in ("market_data", "rank_areas", "rank_industries"):
        marks["places"] = result is not None and names(result, "places") == sorted(expect["location_mentions"])
    if "industries" in expect and wanted in ("market_data", "rank_areas"):
        marks["industries"] = result is not None and names(result, "industries") == sorted(expect["industries"])
    return marks


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--failures", action="store_true")
    parser.add_argument("--pause", type=float, default=1.5, help="seconds between calls (rate limit)")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    from app.config import load_settings

    load_settings()
    from app.assistant.clova_client import writer_from_env
    from app.assistant.intent import classify
    from app.assistant.planner import Planner

    client = writer_from_env()
    if client is None:
        print("APP_MODE=live and CLOVA_STUDIO_API_KEY are needed", file=sys.stderr)
        return 2
    client.daily_limit = 10_000  # this script's own process; the service keeps its own counter
    planner = Planner(client)
    data = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    today = date.fromisoformat(data.get("today", "2026-11-07"))
    cases = data["cases"][:args.limit] if args.limit else data["cases"]
    labels = ("rules", "planner", "service")  # service = planner, or the rules when the planner gives nothing
    totals = {label: {} for label in labels}
    failures, no_decision, reasons = [], 0, {}
    for case in cases:
        context = case.get("context") or {}
        rule = classify(case["text"], context=context, today=today)
        recent, conditions = [], None
        if context.get("previous_topics"):
            # A follow-up only makes sense after an answer, so there are saved conditions.
            recent = [f"(앞 대화에서 다룬 주제: {', '.join(context['previous_topics'])})"]
            conditions = {"area_name": "합성 상권", "industry_name": "커피-음료", "period_label": "2026년 2분기"}
        planned = planner.plan(case["text"], rule=rule, conditions=conditions, recent=recent, loaded=[], today=today)
        if planned is None:
            no_decision += 1
            reasons[planner.last_failure] = reasons.get(planner.last_failure, 0) + 1
        time.sleep(args.pause)  # back-to-back calls hit the API rate limit
        for label, result in (("rules", rule), ("planner", planned), ("service", planned or rule)):
            for field, ok in score(case, result).items():
                hit, total = totals[label].get(field, (0, 0))
                totals[label][field] = (hit + int(ok), total + 1)
        marks = score(case, planned)
        if not all(marks.values()):
            failures.append((case["id"], case["text"], action_of(planned) if planned else None,
                             expected_action(case["expect"]), marks))
    print(f"cases {len(cases)}  ({args.cases})  planner gave no usable decision: {no_decision} {reasons or ''}")
    print(f"{'field':12}" + "".join(f"{label:>12}" for label in labels))
    for field in ("action", "places", "industries"):
        cells = []
        for label in labels:
            hit, total = totals[label].get(field, (0, 0))
            cells.append(f"{hit}/{total}" if total else "-")
        print(f"{field:12}" + "".join(f"{cell:>12}" for cell in cells))
    if args.failures:
        for case_id, text, got, wanted, marks in failures:
            print(f"- {case_id} {text}\n    planner={got} expected={wanted} {marks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
