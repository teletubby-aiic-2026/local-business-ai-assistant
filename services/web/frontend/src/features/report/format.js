// 종합 리포트의 글자·숫자 다듬기 (예전 app.js 1033~1042줄, rpClock, rpTick, rpTrend 의 계산, sourceLine)
import { praiseOf, shortBasis } from "../../lib/domain.js";

// 리뷰가 들어온 곳 (예전 SOURCE_KO)
export const SOURCE_KO = { sample: "합성 리뷰", paste: "붙여넣기", capture: "캡처", app: "가상 배달앱", memo: "매장 메모" };
export const RP_ISSUE_STATE = { recurred_after_reply: "답글 뒤 재발", no_recurrence: "답글 뒤 7일 재발 없음", replied_watching: "답글 달고 지켜보는 중", no_reply: "답글 없음" };

export const signed = (n) => (Number(n) > 0 ? `+${n}` : String(n ?? 0));
export const deltaTone = (n) => (Number(n) < 0 ? "neg" : Number(n) > 0 ? "pos" : "");
export const monthKo = (m) => { const [y, mo] = String(m || "").split("-"); return y && mo ? `${y}년 ${Number(mo)}월` : "이번 달"; };
export const shiftMonth = (m, d) => {
  const [y, mo] = m.split("-").map(Number);
  const t = new Date(Date.UTC(y, mo - 1 + d, 1));
  return `${t.getUTCFullYear()}-${String(t.getUTCMonth() + 1).padStart(2, "0")}`;
};
export const dateKo = (d) => { const m = String(d || "").match(/^\d{4}-(\d{2})-(\d{2})/); return m ? `${Number(m[1])}/${Number(m[2])}` : String(d || ""); };
export const clip = (t, n) => { const s = String(t || ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
export const peakText = (p) => (Array.isArray(p?.peak_hours) ? p.peak_hours : []).map((h) => String(h).replace("-", "~") + "시").join(", ");

// 남은 시간 글자: 1시간이 넘으면 'n시간 m분', 아니면 'm:ss'
export const rpClock = (sec) => {
  const s = Math.max(0, Math.round(sec)), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h}시간 ${m}분` : `${m}:${String(s % 60).padStart(2, "0")}`;
};

// 답글 기다리는 불만마다 시계 (서버와 브라우저 시계 차이는 remaining_seconds 로 맞춘다). 피크 중이면 멈춤
export function clocksOf(pending, peak, fetched) {
  return pending.map((p) => {
    const rem = Number(p.remaining_seconds), due = Date.parse(p.due_at);
    const skew = Number.isFinite(rem) && Number.isFinite(due) ? due - (fetched + rem * 1000) : 0;   // 서버 시계 - 브라우저 시계
    return { due: due - skew, rem, paused: p.paused === true || (peak && rem > 0) };
  });
}
// 시계 하나의 지금 글자와 모양 (예전 rpTick)
export function clockView(c, now) {
  if (!c) return { text: "", tone: "" };
  if (c.paused) return { text: `멈춤 · ${rpClock(c.rem)} 남음`, tone: "paused" };
  const left = Number.isFinite(c.due) ? (c.due - now) / 1000 : c.rem;
  return left >= 0 ? { text: `${rpClock(left)} 남음`, tone: left < 300 ? "soon" : "" } : { text: `기한 ${rpClock(-left)} 지남`, tone: "over" };
}

// 점수 추이 선 그래프의 좌표 (예전 rpTrend). 그림 폭 = 칸의 실제 폭 (좁은 화면에서 글자가 같이 줄어들지 않게), 인쇄 때는 종이 폭
export function trendGeometry(trend, width, height) {
  const pts = (Array.isArray(trend) ? trend : []).filter((t) => Number.isFinite(Number(t?.score)));
  if (!pts.length) return null;
  const W = Math.round(Math.min(860, Math.max(280, width || 600))), H = height || 170, L = 36, R = 16, T = 18, B = 26;
  const v = pts.map((t) => Number(t.score));
  const lo = Math.min(80, ...v), last = v.length - 1;
  const x = (i) => L + (W - L - R) * (pts.length === 1 ? 0.5 : i / last);
  const y = (s) => T + ((H - T - B) * (100 - s)) / Math.max(1, 100 - lo);
  const label = `날마다 응대 점수: ${dateKo(pts[0].date)} ${v[0]}점에서 ${dateKo(pts[last].date)} ${v[last]}점, 가장 낮은 날 ${Math.min(...v)}점`;
  return { pts, v, W, H, L, R, lo, last, x, y, label };
}

// 카드의 근거 한 줄 (예전 sourceLine)
export function sourceLine(p) {
  const ev = p.evidence || [];
  const reviews = ev.filter((e) => e.type === "review");
  const snaps = ev.filter((e) => e.type === "snapshot");
  const parts = [];
  if (reviews.length) parts.push(`리뷰 ${reviews.length}건 · 합성 데이터`);
  snaps.forEach((e) => parts.push(shortBasis(e.basis)));
  const praise = praiseOf({ ...p, evidence: ev });
  if (praise.shown.length) parts.push(`손님 칭찬 리뷰 ${praise.total}건 · 합성 데이터`);
  return parts.join(" · ");
}

// 인쇄 머리글의 한 줄 (예전 rpPrintPrep)
export function printMeta(now, { day, month, until }) {
  const two = (n) => String(n).padStart(2, "0");
  return [
    `출력한 날 ${now.getFullYear()}-${two(now.getMonth() + 1)}-${two(now.getDate())}`,
    day ? `오늘 요약 ${day}` : "",
    month ? `손님 칭찬 요약·월간 보고서 ${monthKo(month)}${until ? ` (${dateKo(until)}까지)` : ""}` : "",
    "응대 점수 최근 28일",
  ].filter(Boolean).join(" · ");
}
