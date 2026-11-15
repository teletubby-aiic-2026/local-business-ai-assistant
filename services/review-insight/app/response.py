"""응대 기한과 리뷰 응대 점수. 규칙으로만 계산한다 (모델 호출 없음).

기한
- 새로 들어온 불만 리뷰(받은 시각 received_at 이 있는 것)마다 30분 (REVIEW_REPLY_SLA_MINUTES).
- 피크타임(기본 11~14시, 17~21시, REVIEW_PEAK_HOURS="11-14,17-21", 끄려면 "off")에는 타이머가 멈춘다.
  피크 중에 들어오면 피크가 끝난 때부터 30분이 시작되고, 세는 중에 피크가 시작되면 멈췄다가 이어서 센다.
- 합성 샘플 리뷰는 받은 시각이 없어(미리 만든 과거 리뷰) 기한을 걸지 않고 "기한 없는 미답변 n건"으로만 센다.
  반복 묶음 계산에는 들어간다.

점수 (100점에서 시작, 최근 28일, 0~100) — 사용자와 정한 수식 (2026-11-14). 숫자는 POLICY 에서 바꿀 수 있다.
| 일                                       | 점수                                   |
| 기한을 넘긴 미답변 불만                  | −6, 그 뒤 30분마다 −1 더 (리뷰당 최대 −10) |
| 기한을 넘긴 뒤 답글                      | 깎인 것의 절반 회복                    |
| 기한 안 답글                             | 0 (빨리 달기만 해서는 안 오르게)        |
| 답글을 단 주제에 같은 불만이 다시 들어옴 | 들어온 리뷰마다 −5                      |
| 반복 묶음(3건 이상)이 있음               | 묶음마다 −2                             |
| 답글 단 주제가 7일 동안 재발 없음        | 주제마다 +3 (100 넘지 않게)             |

이유 목록(reasons)은 항목마다 key 가 있어, 두 시각의 점수를 비교할 때 key 별로 차이를 내면 "왜 변했는지"가 된다 (일일 요약).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.topics import topic_name


@dataclass(frozen=True)
class Policy:
    sla_minutes: int = 30
    peaks: tuple[tuple[int, int], ...] = ((11, 14), (17, 21))
    window_days: int = 28
    late_base: int = 6           # 기한을 넘기면
    late_step_minutes: int = 30  # 그 뒤 이만큼마다
    late_step: int = 1           # 이만큼 더
    late_cap: int = 10           # 리뷰당 최대
    again: int = 5               # 답글 단 주제의 재발
    repeat_group: int = 2        # 반복 묶음마다
    fixed: int = 3               # 재발 없음 확인
    fixed_days: int = 7


def parse_peaks(text: str) -> tuple[tuple[int, int], ...]:
    """"11-14,17-21" → ((11,14),(17,21)). "off"·"none" → (). 잘못된 값은 ValueError."""
    text = (text or "").strip().lower()
    if text in ("off", "none", "0"):
        return ()
    out = []
    for part in text.split(","):
        a, sep, b = part.strip().partition("-")
        if not sep or not a.strip().isdigit() or not b.strip().isdigit():
            raise ValueError(f"REVIEW_PEAK_HOURS 형식이 잘못됐습니다: {part!r} (예: 11-14,17-21)")
        s, e = int(a), int(b)
        if not 0 <= s < e <= 24:
            raise ValueError(f"REVIEW_PEAK_HOURS 시간이 잘못됐습니다: {part!r}")
        out.append((s, e))
    return tuple(sorted(out))


def policy() -> Policy:
    env = os.environ
    kw: dict = {}
    if env.get("REVIEW_PEAK_HOURS", "").strip():
        kw["peaks"] = parse_peaks(env["REVIEW_PEAK_HOURS"])
    if env.get("REVIEW_REPLY_SLA_MINUTES", "").strip():
        kw["sla_minutes"] = max(1, int(env["REVIEW_REPLY_SLA_MINUTES"]))
    return Policy(**kw)


# ── 기한 ──────────────────────────────────────────────────────────
def _peak_windows(day: datetime, peaks) -> list[tuple[datetime, datetime]]:
    base = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return [(base + timedelta(hours=s), base + timedelta(hours=e)) for s, e in peaks]


def in_peak(t: datetime, peaks) -> bool:
    return any(s <= t < e for s, e in _peak_windows(t, peaks))


def due_at(arrival: datetime, p: Policy) -> datetime:
    """받은 시각부터 피크가 아닌 시간으로 sla_minutes 를 센 시각."""
    left = timedelta(minutes=p.sla_minutes)
    t = arrival
    for _ in range(1000):           # 하루에 피크가 몇 개든 몇 바퀴면 끝난다
        windows = _peak_windows(t, p.peaks) + _peak_windows(t + timedelta(days=1), p.peaks)
        current = next(((s, e) for s, e in windows if s <= t < e), None)
        if current:
            t = current[1]
            continue
        nxt = min((s for s, _ in windows if s > t), default=None)
        if nxt is None or t + left <= nxt:
            return t + left
        left -= nxt - t
        t = nxt
    return t + left


# ── 점수 ──────────────────────────────────────────────────────────
def _t(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _first(history: list[dict], statuses: tuple[str, ...], until: datetime) -> datetime | None:
    times = [_t(h["at"]) for h in history or [] if h.get("status") in statuses and _t(h["at"]) <= until]
    return min(times) if times else None


def _late_penalty(due: datetime, end: datetime, p: Policy) -> int:
    if end <= due:
        return 0
    steps = int((end - due).total_seconds() // (p.late_step_minutes * 60))
    return min(p.late_cap, p.late_base + steps * p.late_step)


def _short(text: str, n: int = 40) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


def evaluate(reviews: list[dict], negative: dict[str, list[str]], groups: list[dict], now: datetime,
             p: Policy | None = None) -> dict:
    """reviews: service.decorate 모양 (+ history). negative: review_id → 불만 주제. groups: 그 시각의 묶음 (to_dict 모양).
    now 시각까지 일어난 일만 본다 (그 뒤에 받은 리뷰·답글은 없는 것으로)."""
    p = p or policy()
    since = now - timedelta(days=p.window_days)
    reasons: list[dict] = []
    pending: list[dict] = []
    untimed = 0
    replied_topics: list[tuple[datetime, str, str]] = []      # (답글 시각, 주제, review_id)
    arrivals: list[tuple[datetime, str, list[str]]] = []      # 새로 들어온 불만 (받은 시각, id, 주제)

    for r in reviews:
        rid = r["review_id"]
        topics = negative.get(rid) or []
        arrival = _t(r.get("received_at"))
        if arrival is not None and arrival > now:
            continue
        history = r.get("history") or []
        replied = _first(history, ("replied",), now)
        closed = _first(history, ("replied", "skipped"), now)
        if replied is not None:
            for t in topics:
                replied_topics.append((replied, t, rid))
        if not topics:
            continue
        if arrival is None:                     # 합성 샘플(또는 받은 시각 없는 예전 리뷰): 기한 없음
            if closed is None:
                untimed += 1
            continue
        arrivals.append((arrival, rid, topics))
        due = due_at(arrival, p)
        end = closed or now
        penalty = _late_penalty(due, end, p)
        names = "·".join(topic_name(t) for t in topics)
        if penalty and due >= since:
            late_min = int((end - due).total_seconds() // 60)
            reasons.append({"key": f"late:{rid}", "kind": "late", "delta": -penalty, "at": due.isoformat(timespec="seconds"),
                            "review_id": rid, "message": f"'{names}' 불만 답글 기한을 {late_min}분 넘김"})
            if replied is not None:
                back = penalty // 2
                if back:
                    reasons.append({"key": f"recover:{rid}", "kind": "recover", "delta": back,
                                    "at": replied.isoformat(timespec="seconds"), "review_id": rid,
                                    "message": f"늦었지만 '{names}' 불만에 답글 → {back}점 회복"})
        if closed is None:
            remaining = int((due - now).total_seconds())
            pending.append({"review_id": rid, "text": _short(r["text"]), "topics": topics,
                            "topic_names": [topic_name(t) for t in topics], "source": r.get("source"),
                            "received_at": arrival.isoformat(timespec="seconds"), "due_at": due.isoformat(timespec="seconds"),
                            "remaining_seconds": remaining, "overdue": remaining < 0,
                            "paused": remaining > 0 and in_peak(now, p.peaks), "penalty": -penalty})

    # 답글 단 주제에 같은 불만이 다시 들어옴 (약속했는데 또)
    for arrival, rid, topics in arrivals:
        if arrival < since:
            continue
        hit = next(((t, src) for when, t, src in sorted(replied_topics) if t in topics and when < arrival and src != rid), None)
        if hit:
            reasons.append({"key": f"again:{rid}", "kind": "again", "delta": -p.again, "at": arrival.isoformat(timespec="seconds"),
                            "review_id": rid, "topic": hit[0],
                            "message": f"답글을 단 '{topic_name(hit[0])}' 불만이 다시 들어옴"})

    # 반복 묶음
    for g in groups:
        if g.get("is_repeated"):
            reasons.append({"key": f"repeat:{g['issue_id']}", "kind": "repeat", "delta": -p.repeat_group,
                            "at": g.get("last_at"), "issue_id": g["issue_id"],
                            "message": f"'{g['topic_name']}' 불만이 {g['review_count']}건 반복 중"})

    # 답글 단 주제가 7일 동안 재발 없음
    last_reply: dict[str, datetime] = {}
    for when, t, _ in replied_topics:
        last_reply[t] = max(when, last_reply.get(t, when))
    for t, when in sorted(last_reply.items()):
        until = when + timedelta(days=p.fixed_days)
        if until > now or until < since:
            continue
        if any(when < a <= until and t in topics for a, _, topics in arrivals):
            continue
        reasons.append({"key": f"fixed:{t}", "kind": "fixed", "delta": p.fixed, "at": until.isoformat(timespec="seconds"),
                        "topic": t, "message": f"'{topic_name(t)}' 답글 뒤 {p.fixed_days}일 동안 같은 불만 없음"})

    raw = 100 + sum(x["delta"] for x in reasons)
    reasons.sort(key=lambda x: x.get("at") or "", reverse=True)
    pending.sort(key=lambda x: x["due_at"])
    return {"score": max(0, min(100, raw)), "raw_score": raw, "reasons": reasons, "pending": pending,
            "pending_count": len(pending), "overdue_count": sum(x["overdue"] for x in pending),
            "untimed_unanswered": untimed, "now": now.isoformat(timespec="seconds"),
            "peak_now": in_peak(now, p.peaks),
            "policy": {"sla_minutes": p.sla_minutes, "peak_hours": [f"{s}-{e}" for s, e in p.peaks],
                       "window_days": p.window_days}}


def diff(before: dict, after: dict) -> list[dict]:
    """두 시각의 점수 이유를 key 별로 비교 → 그 사이에 점수를 바꾼 이유 (변한 만큼의 delta)."""
    old = {x["key"]: x for x in before["reasons"]}
    new = {x["key"]: x for x in after["reasons"]}
    out = []
    for key in list(new) + [k for k in old if k not in new]:
        d = new.get(key, {}).get("delta", 0) - old.get(key, {}).get("delta", 0)
        if d:
            base = new.get(key) or old[key]
            msg = base["message"] if key in new else base["message"] + " (해소)"
            out.append({**base, "delta": d, "message": msg})
    return out
