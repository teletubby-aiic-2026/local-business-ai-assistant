#!/usr/bin/env python3
"""사장님 비서 화면 서버(services/web)가 만든 글의 '점검 통과' 수를 세는 측정 스크립트.

떠 있는 서버에 HTTP 로만 말한다 (키·환경 변수·HCX 직접 호출 없음). 서버가 live 이면 이 숫자가 '기준선'이 되고,
다른 브랜치(생성기 개선 PR)를 넣은 서버에 같은 명령을 다시 돌려 앞뒤를 비교한다.

    python services/web/scripts/measure_live.py --base http://127.0.0.1:8540 --rounds 5 --label baseline --out baseline.json

하는 일
  1. GET /api/health            mode · parts · 리뷰 분석 서버 상태를 읽어 적는다. mode 가 live 가 아니면 크게 경고한다 (계속 진행).
  2. 라운드마다 GET /api/cards  걸린 시간을 잰다 (첫 화면이 느린 문제의 기준선).
  3. 라운드마다 카드 각각 POST /api/cards/{card_id}/run  걸린 시간을 재고, 초안의 종류·점검 상태·걸린 점검을 센다.
  4. 호출이 실패하면(HTTP 오류·시간 초과) 멈추지 않고 '호출 실패'로 세고 계속한다.
  5. 한국어 요약 표를 찍고, --out 이 있으면 같은 내용을 JSON 으로 저장한다. 초안 본문은 저장하지 않고 길이만 남긴다.

측정 로직(measure)은 httpx.Client 와 같은 인터페이스(.get / .post)만 받는다. 시험에서는 FastAPI TestClient 를 그대로 넘긴다.

화면(services/web/web/static/app.js)과 똑같이 하는 것
  - 점검 상태 3가지: app.js 의 statusOf(d) 규칙 (failedOf · checksOf 를 씀). draft_status() 에 그대로 옮겼다.
  - 요청 본문: app.js 의 runCard(cardId) 가 보내는 것. 재발 방지 조치 상자(measureBox)가 있는 카드는
    기본으로 체크된 조치만 {"measures": [...]} 로 보내고, 상자가 없는 카드(홍보)는 본문 없이 보낸다. card_run_body() 에 옮겼다.
  - 초안 종류 이름: app.js 의 GEN_NAMES (generator 필드). 홍보글만 화면에서는 '쿠폰 홍보글'이고 여기서는 '홍보글'로 쓴다.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

DEFAULT_BASE = "http://127.0.0.1:8540"
DEFAULT_ROUNDS = 5
DEFAULT_TIMEOUT = 120.0   # 호출 하나(카드 하나 만들기)에 허용하는 초
SCHEMA = 1

# ── 점검 상태: app.js 의 statusOf(d) ─────────────────────────────────
PASS, CHECK, FAIL = "점검 통과", "확인 필요", "점검 실패"
STATUSES = (PASS, CHECK, FAIL)

# app.js 의 GEN_NAMES (generator → 종류). 표에 나오는 순서이기도 하다.
GENERATOR_NAMES = {"reply_draft": "답글", "prevention_notice": "재발 방지 공지", "coupon_promo": "홍보글"}
CARD_KIND_NAMES = {"complaint": "불만 카드", "promo": "홍보 카드"}

# C6 가 '다시 쓰기 사유'에서 뺀 점검 (c6/reply.py _RETRY_EXEMPT, notice.py retry_exempt, promo.py retry_exempt).
# checks 에는 False 로 남아도 failed_reasons(= 화면의 '점검 실패')에는 들어가지 않는다.
RETRY_EXEMPT = frozenset({"length_ok", "uses_opening", "uses_closing"})
UNKNOWN_CHECK = "(점검 이름 없음)"   # failed_reasons 는 있는데 checks 에서 이름을 찾지 못한 경우


def _items(draft: dict, key: str) -> list:
    """app.js 의 `d.key || []`."""
    value = draft.get(key)
    return value if value else []


def draft_status(draft: dict) -> str:
    """app.js statusOf(d) 의 규칙 (승인 완료 분기는 이 스크립트가 승인하지 않으므로 없다).

        failedOf(d) = d.failed_reasons || []
        checksOf(d) = [...(d.needs_input || []), ...(d.c7_flags || [])]
        failedOf(d).length ? "점검 실패" : checksOf(d).length ? "확인 필요" : "점검 통과"
    """
    if len(_items(draft, "failed_reasons")):
        return FAIL
    if len(_items(draft, "needs_input")) + len(_items(draft, "c7_flags")):
        return CHECK
    return PASS


def draft_kind(draft: dict) -> str:
    gen = draft.get("generator")
    return GENERATOR_NAMES.get(gen, str(gen))


def failed_check_names(draft: dict) -> list[str]:
    """'점검 실패'를 만든 점검 이름 (draft.checks 에서 False 이고 다시 쓰기 사유였던 것, 예: has_apology)."""
    checks = draft.get("checks")
    names = [k for k, v in checks.items() if not v and k not in RETRY_EXEMPT] if isinstance(checks, dict) else []
    if not names and len(_items(draft, "failed_reasons")):
        return [UNKNOWN_CHECK]
    return names


def needs_check_names(draft: dict) -> list[str]:
    """'확인 필요'를 만든 사유 이름. needs_input 은 'needs_input/…', c7_flags 는 'c7_flags/…' 로 나눠 적는다.

    문구가 '이름: 설명' 모양이므로 ':' 앞만 쓴다 (c7_flags 의 설명에는 글 본문 조각이 들어 있어 저장하지 않는다).
    """
    names = []
    for source in ("needs_input", "c7_flags"):
        for text in _items(draft, source):
            names.append(f"{source}/{str(text).split(':', 1)[0].strip()}")
    return names


def describe_draft(draft: dict) -> dict:
    """저장용 한 줄. 본문(text)은 넣지 않고 길이만 남긴다."""
    return {
        "draft_id": draft.get("draft_id"), "generator": draft.get("generator"), "kind": draft_kind(draft),
        "target_review_id": draft.get("target_review_id"),
        "status": draft_status(draft),
        "failed_checks": failed_check_names(draft), "needs_checks": needs_check_names(draft),
        "failed_reason_count": len(_items(draft, "failed_reasons")),
        "needs_input_count": len(_items(draft, "needs_input")), "c7_flag_count": len(_items(draft, "c7_flags")),
        "text_len": len(draft.get("text") or ""), "rewrites": draft.get("rewrites"),
        "model": draft.get("model"), "server_elapsed_ms": draft.get("elapsed_ms"),
    }


# ── 요청: app.js 의 runCard ──────────────────────────────────────────
def card_run_body(plan: dict) -> dict | None:
    """화면이 카드 만들기에 보내는 본문. measureBox(p) 가 상자를 그리는 카드(measures.options 가 있음)는
    기본으로 체크된 조치(measures.default 에 든 것)만 보내고, 상자가 없는 카드는 본문이 없다."""
    measures = plan.get("measures") or {}
    options = measures.get("options") or []
    if not options:
        return None
    on = set(measures.get("default") or [])
    return {"measures": [o["id"] for o in options if o.get("id") in on]}


# ── 호출 하나 ────────────────────────────────────────────────────────
def _server_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:200]
        if body.get("detail"):
            return str(body["detail"])[:200]
    return ""


def timed_call(client: Any, method: str, path: str, *, timeout: float, json_body: dict | None = None) -> dict:
    """호출 하나. 실패해도 예외를 내지 않고 {"ok": False, "error": ...} 로 돌려준다. seconds 는 실패해도 잰다.

    시간 제한은 client 가 이미 갖고 있다 (main 이 httpx.Client(timeout=...) 로 건다. TestClient 는 호출마다 timeout 을 주면 경고를 낸다).
    여기 timeout 은 '시간 초과 (N초)' 문구에 적을 값이다."""
    start = time.perf_counter()
    error, data = None, None
    try:
        if method == "get":
            resp = client.get(path)
        else:
            resp = client.post(path, **({"json": json_body} if json_body is not None else {}))
        if resp.status_code >= 400:
            msg = _server_message(resp)
            error = f"HTTP {resp.status_code}" + (f": {msg}" if msg else "")
        else:
            try:
                data = resp.json()
            except ValueError:
                error = "응답이 JSON 이 아님"
    except httpx.TimeoutException:
        error = f"시간 초과 ({timeout:g}초)"
    except httpx.HTTPError as exc:
        error = f"연결 오류 ({exc.__class__.__name__})"
    except Exception as exc:  # 한 번의 이상한 응답이 측정 전체를 멈추지 않게
        error = f"예외 ({exc.__class__.__name__})"
    return {"ok": error is None, "seconds": round(time.perf_counter() - start, 3), "error": error, "data": data}


# ── 측정 ────────────────────────────────────────────────────────────
def read_health(client: Any, timeout: float) -> dict:
    call = timed_call(client, "get", "/api/health", timeout=timeout)
    if not call["ok"] or not isinstance(call["data"], dict):
        return {"ok": False, "error": call["error"] or "응답 모양이 다름", "mode": None}
    h = call["data"]
    review = h.get("review_service") or {}
    return {"ok": True, "error": None, "mode": h.get("mode"), "mode_label": h.get("mode_label"),
            "parts": h.get("parts"), "blocking": h.get("blocking") or [],
            "review_service": {"status": review.get("status"), "mode": review.get("mode"), "models": review.get("models")}}


def not_live_warning(health: dict) -> str | None:
    if health.get("mode") == "live":
        return None
    seen = f"서버 mode={health['mode']}" if health.get("mode") else f"서버 mode 를 읽지 못함 ({health.get('error')})"
    return (f"실시간이 아님: {seen}. 이 숫자는 실시간 HCX-005 결과가 아니니 기준선으로 쓰지 마세요 "
            "(mock 이면 저장된 예시이고 실제 AI 결과가 아님).")


def _card_summary(plan: dict) -> dict:
    card = plan.get("card") or {}
    return {"card_id": card.get("card_id"), "kind": card.get("kind"), "reason_source": plan.get("reason_source"),
            "problem_count": len(plan.get("problems") or [])}


def _run_summary(plan: dict, call: dict) -> dict:
    card = plan.get("card") or {}
    row = {"card_id": card.get("card_id"), "kind": card.get("kind"), "ok": call["ok"], "seconds": call["seconds"],
           "error": call["error"], "request_measures": (card_run_body(plan) or {}).get("measures")}
    data = call["data"] if call["ok"] else None
    if isinstance(data, dict) and isinstance(data.get("drafts"), list):
        row.update({
            "source": data.get("source"), "server_elapsed_ms": data.get("elapsed_ms"),
            "flagged_count": data.get("flagged_count"),
            "chosen_measures": [m.get("id") for m in data.get("chosen_measures") or []],
            "result_needs_input_count": len(data.get("needs_input") or []),
            "drafts": [describe_draft(d) for d in data["drafts"]]})
    elif call["ok"]:   # 200 인데 글 목록이 없음 → 호출 실패로 센다
        row.update({"ok": False, "error": "응답에 drafts 목록이 없음", "drafts": []})
    else:
        row["drafts"] = []
    return row


def measure(client: Any, *, rounds: int = DEFAULT_ROUNDS, label: str | None = None, base: str | None = None,
            timeout: float = DEFAULT_TIMEOUT, log: Callable[[str], None] | None = None) -> dict:
    """서버를 rounds 번 돌며 재고 세어 결과 dict 를 돌려준다.

    client: .get(path) / .post(path, json=) 를 가진 httpx.Client 또는 TestClient. 호출 하나의 시간 제한은 client 에 걸려 있어야 하고,
    timeout 인자는 그 값을 오류 문구와 저장 결과에 적기 위한 것이다 (main 은 둘을 같은 값으로 맞춘다).
    """
    say = log or (lambda _msg: None)
    started = datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")
    health = read_health(client, timeout)
    warning = not_live_warning(health)
    if warning:
        say("!" * 70 + "\n!! " + warning + "\n" + "!" * 70)
    say(f"서버 상태: mode={health.get('mode') or '?'} parts={health.get('parts') or '?'}")

    rounds_out: list[dict] = []
    known_cards: list[dict] = []   # 가장 최근에 받은 카드 목록 (이번 라운드 목록 호출이 실패했을 때 쓴다)
    for n in range(1, rounds + 1):
        listing = timed_call(client, "get", "/api/cards", timeout=timeout)
        plans = []
        if listing["ok"] and isinstance(listing["data"], dict) and isinstance(listing["data"].get("cards"), list):
            plans = listing["data"]["cards"]
            known_cards = plans
        elif listing["ok"]:
            listing.update({"ok": False, "error": "응답에 cards 목록이 없음"})
        cards_row = {"ok": listing["ok"], "seconds": listing["seconds"], "error": listing["error"],
                     "cards": [_card_summary(p) for p in plans],
                     "no_card_b": (listing["data"] or {}).get("no_card_b") if listing["ok"] else None}
        say(f"[라운드 {n}/{rounds}] /api/cards {listing['seconds']:.1f}초" + ("" if listing["ok"] else f" 실패: {listing['error']}"))
        runs, skipped = [], None
        todo = plans if listing["ok"] else known_cards
        if not todo:
            skipped = "서버가 카드를 0장 줘서 만들지 못함" if listing["ok"] else "카드 목록을 받지 못해 카드를 만들지 못함"
        for plan in todo:
            card_id = (plan.get("card") or {}).get("card_id")
            call = timed_call(client, "post", f"/api/cards/{card_id}/run", timeout=timeout, json_body=card_run_body(plan))
            row = _run_summary(plan, call)
            runs.append(row)
            say(f"[라운드 {n}/{rounds}] {card_id} {row['seconds']:.1f}초 "
                + (f"초안 {len(row['drafts'])}개 " + " ".join(f"{d['kind']}:{d['status']}" for d in row["drafts"])
                   if row["ok"] else f"실패: {row['error']}"))
        rounds_out.append({"round": n, "cards_call": cards_row, "runs": runs, "runs_skipped_reason": skipped})

    return {"schema": SCHEMA, "label": label, "base": base, "started_at": started, "rounds_requested": rounds,
            "timeout_s": timeout, "health": health, "not_live_warning": warning,
            "rounds": rounds_out, "summary": summarize_rounds(rounds_out)}


# ── 요약 ────────────────────────────────────────────────────────────
def _stats(values: list[float]) -> dict:
    values = [float(v) for v in values]
    if not values:
        return {"values": [], "median": None, "min": None, "max": None}
    return {"values": values, "median": round(statistics.median(values), 3), "min": min(values), "max": max(values)}


def summarize_rounds(rounds: list[dict]) -> dict:
    counts: dict[str, dict[str, int]] = {}
    failed_checks: dict[str, dict[str, int]] = {}
    needs_checks: dict[str, dict[str, int]] = {}
    failures: list[dict] = []
    cards_seconds: list[float] = []
    run_seconds: dict[str, list[float]] = {}
    sources: dict[str, int] = {}
    for rnd in rounds:
        cards_call = rnd["cards_call"]
        if cards_call["ok"]:
            cards_seconds.append(cards_call["seconds"])
        else:
            failures.append({"round": rnd["round"], "call": "GET /api/cards", "error": cards_call["error"]})
        if rnd.get("runs_skipped_reason"):
            failures.append({"round": rnd["round"], "call": "카드 실행 전체", "error": rnd["runs_skipped_reason"]})
        for run in rnd["runs"]:
            if not run["ok"]:
                failures.append({"round": rnd["round"], "call": f"POST /api/cards/{run['card_id']}/run", "error": run["error"]})
                continue
            run_seconds.setdefault(run.get("kind") or "?", []).append(run["seconds"])
            sources[str(run.get("source"))] = sources.get(str(run.get("source")), 0) + 1
            for d in run["drafts"]:
                kind = d["kind"]
                row = counts.setdefault(kind, {s: 0 for s in STATUSES})
                row[d["status"]] += 1
                for name in d["failed_checks"]:
                    failed_checks.setdefault(kind, {})[name] = failed_checks.get(kind, {}).get(name, 0) + 1
                for name in d["needs_checks"]:
                    needs_checks.setdefault(kind, {})[name] = needs_checks.get(kind, {}).get(name, 0) + 1
    order = [n for n in GENERATOR_NAMES.values() if n in counts] + [k for k in counts if k not in GENERATOR_NAMES.values()]
    counts = {k: {**counts[k], "합계": sum(counts[k].values())} for k in order}
    total = {s: sum(r[s] for r in counts.values()) for s in (*STATUSES, "합계")}
    return {"counts": counts, "total": total, "failed_checks": failed_checks, "needs_checks": needs_checks,
            "call_failures": failures, "result_sources": sources,
            "cards_seconds": _stats(cards_seconds),
            "run_seconds": {k: _stats(v) for k, v in run_seconds.items()}}


# ── 한국어 출력 ──────────────────────────────────────────────────────
def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text: Any, width: int, *, right: bool = False) -> str:
    text = str(text)
    gap = " " * max(0, width - _width(text))
    return gap + text if right else text + gap


def _secs(stats: dict) -> str:
    if not stats["values"]:
        return "-"
    return " ".join(f"{v:.1f}" for v in stats["values"]) + f"  중앙값 {stats['median']:.1f}"


def _check_line(by_kind: dict[str, dict[str, int]]) -> str:
    parts = [f"{kind} {name} {n}" for kind, names in by_kind.items() for name, n in names.items()]
    return " · ".join(parts) if parts else "없음"


def format_report(result: dict) -> str:
    s, h = result["summary"], result["health"]
    out: list[str] = []
    if result.get("not_live_warning"):
        bar = "!" * 70
        out += [bar, "!! " + result["not_live_warning"], bar]
    review = h.get("review_service") or {}
    out.append(f"측정 이름: {result.get('label') or '-'} | 서버: {result.get('base') or '-'} | 라운드 {result['rounds_requested']} | "
               f"시작 {result['started_at']}")
    out.append(f"서버 mode: {h.get('mode') or '?'}{' (' + h['mode_label'] + ')' if h.get('mode_label') else ''} | "
               f"리뷰 분석 서버: {review.get('status') or '?'}{' (' + str(review['mode']) + ')' if review.get('mode') else ''}")
    if h.get("parts"):
        out.append("부분별 동작: " + " / ".join(f"{k}={v}" for k, v in h["parts"].items()))
    if h.get("blocking"):
        out.append("서버가 알린 막힘: " + " ".join(h["blocking"]))
    if not h["ok"]:
        out.append(f"/api/health 호출 실패: {h['error']}")
    out.append("")

    rows = [(kind, c[PASS], c[CHECK], c[FAIL], c["합계"]) for kind, c in s["counts"].items()]
    t = s["total"]
    rows.append(("전체", t[PASS], t[CHECK], t[FAIL], t["합계"]))
    heads = ("종류", "통과", "확인 필요", "실패", "합계")
    widths = [max(_width(str(r[i])) for r in [heads, *rows]) for i in range(5)]
    out.append("  ".join(_pad(heads[i], widths[i], right=i > 0) for i in range(5)))
    for r in rows:
        out.append("  ".join(_pad(r[i], widths[i], right=i > 0) for i in range(5)))
    if not s["counts"]:
        out.append("(측정된 초안이 없어요)")
    out.append("")

    fails = s["call_failures"]
    out.append(f"호출 실패: {len(fails)}건" + ("" if not fails else " (측정에서 빠짐)"))
    out += [f"  라운드 {f['round']} · {f['call']} · {f['error']}" for f in fails]
    out.append("걸린 점검(실패): " + _check_line(s["failed_checks"]))
    out.append("걸린 점검(확인 필요): " + _check_line(s["needs_checks"]))
    cs = s["cards_seconds"]
    first = result["rounds"][0]["cards_call"] if result["rounds"] else None
    out.append("/api/cards 걸린 시간(초): " + _secs(cs)
               + (f"  (첫 호출 {first['seconds']:.1f})" if first and first["ok"] and len(cs["values"]) > 1 else ""))
    runs = [f"{CARD_KIND_NAMES.get(k, k)} 중앙값 {v['median']:.1f} ({' '.join(f'{x:.1f}' for x in v['values'])})"
            for k, v in s["run_seconds"].items()]
    out.append("카드 실행 걸린 시간(초): " + (", ".join(runs) if runs else "-"))
    out.append("결과 출처(서버 source): " + (", ".join(f"{k} {n}" for k, n in s["result_sources"].items()) or "-"))
    return "\n".join(out)


# ── 명령줄 ──────────────────────────────────────────────────────────
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="사장님 비서 화면 서버가 만든 글의 점검 통과 수를 센다 (서버에 HTTP 로만 말함, 키·환경 변수 안 씀).")
    p.add_argument("--base", default=DEFAULT_BASE, help=f"떠 있는 서버 주소 (기본 {DEFAULT_BASE})")
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS, help=f"반복 횟수 (기본 {DEFAULT_ROUNDS})")
    p.add_argument("--out", help="결과를 JSON 으로 저장할 경로 (초안 본문은 저장하지 않고 길이만)")
    p.add_argument("--label", help="결과에 적어 둘 꼬리표 (예: baseline, pr36)")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help=f"호출 하나의 시간 제한 초 (기본 {DEFAULT_TIMEOUT:g})")
    args = p.parse_args(argv)
    if args.rounds < 1:
        p.error("--rounds 는 1 이상이어야 해요")
    return args


def main(argv: list[str] | None = None, *, client: Any = None) -> int:
    """client 는 시험용 (TestClient). 없으면 --base 로 httpx.Client 를 만든다 (환경 변수의 프록시 설정은 읽지 않음)."""
    args = parse_args(argv)
    own = client is None
    if own:
        client = httpx.Client(base_url=args.base, timeout=args.timeout, trust_env=False)
    try:
        result = measure(client, rounds=args.rounds, label=args.label, base=args.base, timeout=args.timeout,
                         log=lambda msg: print(msg, file=sys.stderr, flush=True))
    finally:
        if own:
            client.close()
    print(format_report(result))
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n저장: {path}")
    return 0 if result["summary"]["total"]["합계"] else 1   # 센 초안이 하나도 없으면 1


if __name__ == "__main__":
    sys.exit(main())
