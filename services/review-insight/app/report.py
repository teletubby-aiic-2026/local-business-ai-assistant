"""일일 요약과 월간 보고서. 숫자는 모두 코드가 계산하고, 문장은 틀 문장에 숫자만 넣는다 (모델 호출 없음).

- 날짜는 한국 시간. 리뷰가 "그날 들어왔다"는 받은 시각(received_at) 기준이고,
  받은 시각이 없는 합성 샘플은 작성 시각(시나리오 날짜, 10/13~11/8) 기준이다.
- 틀 문장은 원인을 단정하지 않는다 ("~때문" 대신 "확인해 보세요"). 숫자는 바로 옆 칸의 값과 같다 (시험으로 확인).
"""
from __future__ import annotations

import calendar
import html
from collections import Counter
from datetime import date, datetime, timedelta

from app import response
from app.service import KST, Timeline

def _day_end(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=KST)


def _cut(d: date, now: datetime) -> datetime:
    """그날 끝 시각. 오늘이면 지금까지만 본다."""
    return min(_day_end(d), now)


def _in_day(t: datetime, d: date) -> bool:
    return t.astimezone(KST).date() == d


def parse_day(value: str | None, now: datetime) -> date:
    if not value:
        return now.astimezone(KST).date()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("date 는 YYYY-MM-DD 형식이어야 합니다") from None


def parse_month(value: str | None, now: datetime) -> tuple[int, int]:
    if not value:
        n = now.astimezone(KST)
        return n.year, n.month
    try:
        y, m = value.split("-")
        y, m = int(y), int(m)
        if not 1 <= m <= 12:
            raise ValueError
        return y, m
    except ValueError:
        raise ValueError("month 는 YYYY-MM 형식이어야 합니다") from None


def _replies_in(tl: Timeline, start: datetime, end: datetime) -> list[tuple[dict, datetime]]:
    out = []
    for row in tl.rows:
        times = [datetime.fromisoformat(h["at"]) for h in row["history"] if h.get("status") == "replied"]
        if times and start <= min(times) <= end:
            out.append((row, min(times)))
    return out


def _todo(state: dict, insight) -> dict:
    """내일 먼저 할 일 1개: 기한 넘긴 불만 → 반복 묶음 → 기한 없는 미답변 → 없음."""
    overdue = [x for x in state["pending"] if x["overdue"]]
    if overdue:
        x = overdue[0]
        return {"kind": "reply_overdue", "review_id": x["review_id"],
                "text": f"기한을 넘긴 '{'·'.join(x['topic_names'])}' 불만 리뷰에 답글 달기 (모두 {len(overdue)}건)"}
    if state["pending"]:
        x = state["pending"][0]
        return {"kind": "reply_pending", "review_id": x["review_id"],
                "text": f"답글을 기다리는 '{'·'.join(x['topic_names'])}' 불만 리뷰에 답글 달기 (모두 {len(state['pending'])}건)"}
    repeated = [g for g in (insight.groups if insight else []) if g.is_repeated]
    if repeated:
        g = repeated[0]
        return {"kind": "check_repeated", "issue_id": g.issue_id,
                "text": f"'{g.topic_name}' 불만이 {g.review_count}건 반복돼요. 매장에서 확인 절차를 점검해 보세요"}
    if state["untimed_unanswered"]:
        return {"kind": "reply_untimed", "text": f"답글을 안 단 지난 불만 리뷰 {state['untimed_unanswered']}건 정리하기"}
    return {"kind": "none", "text": "밀린 응대가 없어요"}


def daily(tl: Timeline, day: date, now: datetime) -> dict:
    start = datetime(day.year, day.month, day.day, tzinfo=KST)
    end = _cut(day, now)
    if end < start:
        raise ValueError("아직 오지 않은 날짜입니다")
    rows = [r for r in tl.rows if _in_day(tl.arrival(r), day) and tl.arrival(r) <= end]
    complaints = [r for r in rows if tl.negative.get(r["review_id"])]
    before, after = tl.at(start - timedelta(seconds=1)), tl.at(end)
    changes = response.diff(before, after)

    timed = [r for r in complaints if r["received_at"]]
    on_time = late = 0
    for r in timed:
        due = response.due_at(datetime.fromisoformat(r["received_at"]), tl.policy)
        first = next((datetime.fromisoformat(h["at"]) for h in r["history"] if h.get("status") == "replied"), None)
        if first is not None and first <= end:
            on_time += first <= due
            late += first > due
    replies = _replies_in(tl, start, end)
    change = after["score"] - before["score"]
    todo = _todo(after, tl.insight_at(end))
    sign = f"+{change}" if change > 0 else str(change)
    summary = (f"{day.month}월 {day.day}일: 리뷰 {len(rows)}건, 불만 {len(complaints)}건. "
               f"기한 안 답글 {on_time}건, 늦은 답글 {late}건. 점수 {before['score']} → {after['score']} ({sign}).")
    return {
        "store_id": tl.store_id, "date": day.isoformat(), "until": end.isoformat(timespec="seconds"),
        "review_count": len(rows), "complaint_count": len(complaints),
        "by_source": dict(Counter(r["source"] for r in rows)),
        "timed_complaint_count": len(timed), "replied_count": len(replies),
        "replied_on_time": on_time, "replied_late": late,
        "pending_count": after["pending_count"], "overdue_count": after["overdue_count"],
        "untimed_unanswered": after["untimed_unanswered"],
        "score_start": before["score"], "score_end": after["score"], "score_change": change,
        "changes": changes, "todo": todo, "summary": summary, "summary_method": "template",
    }


def monthly(tl: Timeline, year: int, month: int, now: datetime) -> dict:
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    start = datetime(year, month, 1, tzinfo=KST)
    if start > now:
        raise ValueError("아직 오지 않은 달입니다")
    days = [first + timedelta(days=i) for i in range((min(last, now.astimezone(KST).date()) - first).days + 1)]
    trend = []
    for d in days:
        s = tl.at(_cut(d, now))
        trend.append({"date": d.isoformat(), "score": s["score"]})
    end = _cut(days[-1], now)
    before, after = tl.at(start - timedelta(seconds=1)), tl.at(end)
    rows = [r for r in tl.rows if start <= tl.arrival(r) <= end]
    insight = tl.insight_at(end)

    # 반복 불만별: 이번 달 건수, 답글 여부, 답글 뒤 재발
    again = [x for x in after["reasons"] if x["kind"] == "again" and start.isoformat() <= x["at"] <= end.isoformat()]
    fixed = {x["topic"] for x in after["reasons"] if x["kind"] == "fixed"}
    month_ids = {r["review_id"] for r in rows}
    replied_ids = {r["review_id"] for r in tl.rows if any(h.get("status") == "replied" for h in r["history"])}
    issues = []
    for g in (insight.groups if insight else []):
        in_month = [i for i in g.review_ids if i in month_ids]
        if not in_month and not g.is_repeated:
            continue
        recurred = [x for x in again if x.get("topic") in g.topics]
        replied = [i for i in g.review_ids if i in replied_ids]
        state = ("recurred_after_reply" if recurred else "no_recurrence" if any(t in fixed for t in g.topics)
                 else "replied_watching" if replied else "no_reply")
        issues.append({"issue_id": g.issue_id, "topic_name": g.topic_name, "review_count": g.review_count,
                       "count_this_month": len(in_month), "is_repeated": g.is_repeated, "replied_count": len(replied),
                       "recurred_after_reply": len(recurred), "state": state, "main_time_band": g.main_time_band})

    late = sum(1 for x in after["reasons"] if x["kind"] == "late" and start.isoformat() <= x["at"] <= end.isoformat())
    suggestions = _suggestions(issues, late)
    return {
        "store_id": tl.store_id, "month": f"{year:04d}-{month:02d}", "until": end.isoformat(timespec="seconds"),
        "review_count": len(rows), "complaint_count": sum(1 for r in rows if tl.negative.get(r["review_id"])),
        "by_source": dict(Counter(r["source"] for r in rows)),
        "score_start": before["score"], "score_end": after["score"], "score_change": after["score"] - before["score"],
        "score_trend": trend, "changes": response.diff(before, after), "late_count": late,
        "repeated_issues": issues, "suggestions": suggestions, "summary_method": "template",
    }


def _suggestions(issues: list[dict], late: int) -> list[dict]:
    """다음 달 개선 제안 (최대 3개). 원인은 단정하지 않고 확인할 일로 쓴다."""
    out = []
    for i in issues:
        if i["state"] == "recurred_after_reply":
            out.append({"issue_id": i["issue_id"], "text": f"'{i['topic_name']}': 답글을 단 뒤에도 {i['recurred_after_reply']}건 다시 들어왔어요. "
                                                         "답글의 약속이 매장 절차로 이어졌는지 확인해 보세요"})
    for i in issues:
        if i["is_repeated"] and i["state"] == "no_reply":
            band = f" {i['main_time_band']}에 많이 몰려 있어요." if i["main_time_band"] else ""
            out.append({"issue_id": i["issue_id"], "text": f"'{i['topic_name']}' 불만 {i['review_count']}건에 아직 답글이 없어요.{band} "
                                                         "답글로 조치를 알리고, 매장에서 확인해 보세요"})
    if late:
        out.append({"text": f"기한을 넘긴 답글이 {late}건 있었어요. 피크가 끝난 뒤 30분 안에 리뷰를 확인하는 시간을 정해 보세요"})
    if not out:
        out.append({"text": "이번 달은 크게 고칠 응대가 보이지 않아요. 지금 방식을 이어 가세요"})
    return out[:3]



_STATE = {"recurred_after_reply": "답글 뒤 재발", "no_recurrence": "답글 뒤 7일 재발 없음",
          "replied_watching": "답글 달고 지켜보는 중", "no_reply": "답글 없음"}
_SOURCE = {"sample": "합성 리뷰", "paste": "붙여넣기", "capture": "캡처", "app": "가상 배달앱", "memo": "매장 메모"}


def render_monthly(m: dict, store_name: str, printed_at: datetime) -> str:
    """월간 보고서 인쇄용 A4 한 장. 숫자는 m 그대로(코드 계산), 문장은 틀 문장. 개선 제안은 체크 칸이 있는 할 일 목록."""
    e = html.escape
    y, mo = m["month"].split("-")
    trend = m["score_trend"]
    svg = ""
    if trend:
        W, H, P = 640, 150, 28
        lo = min(min(t["score"] for t in trend), 80)
        x = lambda i: P + (W - 2 * P) * (0.5 if len(trend) == 1 else i / (len(trend) - 1))
        yv = lambda v: H - P - (H - 2 * P) * (v - lo) / max(1, 100 - lo)
        pts = " ".join(f"{x(i):.1f},{yv(t['score']):.1f}" for i, t in enumerate(trend))
        last = trend[-1]
        svg = (f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="날마다 점수">'
               f'<line x1="{P}" x2="{W - P}" y1="{yv(100):.1f}" y2="{yv(100):.1f}" stroke="#ccc"/>'
               f'<text x="{P}" y="{yv(100) - 4:.1f}" font-size="11" fill="#777">100</text>'
               f'<polyline points="{pts}" fill="none" stroke="#0a6b43" stroke-width="2.5"/>'
               f'<circle cx="{x(len(trend) - 1):.1f}" cy="{yv(last["score"]):.1f}" r="4" fill="#0a6b43"/>'
               f'<text x="{x(len(trend) - 1) - 6:.1f}" y="{yv(last["score"]) - 8:.1f}" font-size="12" font-weight="700" text-anchor="end">{last["score"]}점</text>'
               f'<text x="{P}" y="{H - 6}" font-size="11" fill="#777">{e(trend[0]["date"][5:])}</text>'
               f'<text x="{W - P}" y="{H - 6}" font-size="11" fill="#777" text-anchor="end">{e(last["date"][5:])}</text></svg>')
    sign = f"+{m['score_change']}" if m["score_change"] > 0 else str(m["score_change"])
    src = " · ".join(f"{_SOURCE.get(k, k)} {v}" for k, v in m["by_source"].items()) or "없음"
    changes = "".join(f'<tr><td class="num {"neg" if c["delta"] < 0 else "pos"}">{"+" if c["delta"] > 0 else ""}{c["delta"]}</td><td>{e(c["message"])}</td></tr>'
                      for c in m["changes"]) or '<tr><td colspan="2" class="muted">이번 달 점수가 바뀐 일이 없어요</td></tr>'
    rows_html = []
    for i in m["repeated_issues"]:
        state = _STATE.get(i["state"], i["state"]) + (f" ({i['recurred_after_reply']}건)" if i["recurred_after_reply"] else "")
        rows_html.append(f'<tr><td>{e(i["topic_name"])}{" <b>반복</b>" if i["is_repeated"] else ""}</td>'
                         f'<td class="num">{i["review_count"]}</td><td class="num">{i["count_this_month"]}</td>'
                         f'<td class="num">{i["replied_count"]}</td><td>{e(state)}</td><td>{e(i["main_time_band"] or "-")}</td></tr>')
    issues = "".join(rows_html) or '<tr><td colspan="6" class="muted">묶음이 없어요</td></tr>'
    todos = "".join(f'<li><span class="box"></span><div>{e(t["text"])}<div class="memo">메모 / 한 날짜: ______________________</div></div></li>'
                    for t in m["suggestions"])
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(store_name)} {int(mo)}월 응대 보고서</title>
<style>
  @page {{ size: A4; margin: 12mm; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:#fff; color:#111; font:13.5px/1.5 "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif; }}
  .page {{ max-width:186mm; margin:0 auto; padding:8px; }}
  header {{ display:flex; justify-content:space-between; align-items:flex-end; border-bottom:3px solid #111; padding-bottom:6px; }}
  h1 {{ font-size:22px; margin:0; }} h2 {{ font-size:15px; margin:14px 0 6px; }} .muted {{ color:#777; }}
  .kpi {{ display:grid; grid-template-columns:repeat(4, 1fr); gap:8px; margin-top:10px; }}
  .kpi div {{ border:1px solid #ddd; border-radius:8px; padding:8px 10px; }} .kpi b {{ display:block; font-size:22px; }} .kpi span {{ font-size:12px; color:#555; }}
  table {{ width:100%; border-collapse:collapse; }} td, th {{ border-bottom:1px solid #e5e5e5; padding:5px 6px; text-align:left; vertical-align:top; }}
  th {{ font-size:12px; color:#555; font-weight:600; }} .num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .neg {{ color:#b42318; font-weight:700; }} .pos {{ color:#0a6b43; font-weight:700; }}
  ol.todo {{ list-style:none; padding:0; margin:0; }} ol.todo li {{ display:flex; gap:10px; border:1.5px solid #111; border-radius:8px; padding:10px; margin-bottom:8px; break-inside:avoid; }}
  .box {{ flex:none; width:18px; height:18px; border:2px solid #111; border-radius:3px; margin-top:2px; }}
  .memo {{ margin-top:6px; font-size:12px; color:#666; }}
  footer {{ margin-top:12px; font-size:11px; color:#666; border-top:1px solid #ddd; padding-top:6px; }}
  section {{ break-inside:avoid; }}
</style></head><body><div class="page">
<header><div><h1>{e(store_name)} · {y}년 {int(mo)}월 응대 보고서</h1>
<div class="muted">{e(m["month"])}-01 ~ {e(m["until"][:10])} 기준</div></div><div class="muted">뽑은 날 {e(printed_at.strftime("%Y-%m-%d"))}</div></header>
<div class="kpi"><div><span>리뷰</span><b>{m["review_count"]}건</b><span>{e(src)}</span></div>
<div><span>불만</span><b>{m["complaint_count"]}건</b><span>불만 주제가 있는 리뷰</span></div>
<div><span>응대 점수</span><b>{m["score_end"]}점</b><span>{m["score_start"]} → {m["score_end"]} ({sign})</span></div>
<div><span>기한 넘긴 답글</span><b>{m["late_count"]}건</b><span>30분 기한 (피크 멈춤)</span></div></div>
<section><h2>날마다 응대 점수</h2>{svg}</section>
<section><h2>점수가 바뀐 이유</h2><table><tbody>{changes}</tbody></table></section>
<section><h2>반복 불만과 재발 여부</h2><table><thead><tr><th>불만</th><th class="num">전체</th><th class="num">이번 달</th><th class="num">답글</th><th>상태</th><th>많은 시간대</th></tr></thead><tbody>{issues}</tbody></table></section>
<section><h2>다음 달 개선 할 일 <span class="muted" style="font-weight:400">— 한 것은 체크해 주세요</span></h2><ol class="todo">{todos}</ol></section>
<footer>숫자는 리뷰 기록으로 코드가 계산했고, 문장은 정해 둔 틀에 숫자만 넣었어요 (AI 문장 아님). 원인을 단정하지 않으니 매장에서 확인해 주세요. 시연용 합성 데이터(가상 가게)입니다.</footer>
</div></body></html>"""
