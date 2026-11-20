// 종합 리포트의 글자·숫자 다듬기 (시계·점수 추이 계산, 근거 한 줄, 11/20 주간·월간 저장 보고서의 타일·안내 띠)
import { praiseOf, shortBasis } from "../../lib/domain.js";

// 리뷰가 들어온 곳
export const SOURCE_KO = { sample: "합성 리뷰", paste: "붙여넣기", capture: "캡처", app: "가상 배달앱", memo: "매장 메모" };
export const RP_ISSUE_STATE = { recurred_after_reply: "답글 뒤 재발", no_recurrence: "답글 뒤 7일 재발 없음", replied_watching: "답글 달고 지켜보는 중", no_reply: "답글 없음" };

// 화면 머리(인쇄에서는 머리글)에 한 번만 두는 고지. 마케팅 요약의 카드 ⓑ 이유 문장은 AI 가 썼을 수 있어 범위를 응대 점수·보고서로 좁혀 말한다
export const RP_NOTE = "응대 점수와 보고서는 리뷰 기록으로 계산했어요 (AI 문장 아님).";

// 탭(주간·월간)마다 바뀌는 말. this·fixPast 는 이미 끝난 기간(period.in_progress === false)을 볼 때
export const KIND_KO = { weekly: "주간", monthly: "월간" };
export const PERIOD_WORDS = {
  weekly: { now: "이번 주", nowIs: "이번 주는", this: "이 주", prev: "지난주", same: "지난주와 같아요", next: "다음 주",
    fix: "이번 주에 고칠 것", fixPast: "이 주 기록에서 고칠 것", ended: "그 주가 끝나기 전에 만든 보고서예요", key: "count_this_week" },
  monthly: { now: "이번 달", nowIs: "이번 달은", this: "이 달", prev: "지난달", same: "지난달과 같아요", next: "다음 달",
    fix: "이번 달에 고칠 것", fixPast: "이 달 기록에서 고칠 것", ended: "그 달이 끝나기 전에 만든 보고서예요", key: "count_this_month" },
};
// 이미 끝난 기간의 보고서인가 (서버가 in_progress 를 주지 않으면 진행 중으로 본다)
export const isPast = (view) => view?.period?.in_progress === false;
export const NONE = "–";   // 자료가 없는 칸 (숫자를 지어내지 않음)

export const signed = (n) => (Number(n) > 0 ? `+${n}` : String(n ?? 0));
export const deltaTone = (n) => (Number(n) < 0 ? "neg" : Number(n) > 0 ? "pos" : "");
export const dateKo = (d) => { const m = String(d || "").match(/^\d{4}-(\d{2})-(\d{2})/); return m ? `${Number(m[1])}/${Number(m[2])}` : String(d || ""); };
export const clip = (t, n) => { const s = String(t || ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
export const peakText = (p) => (Array.isArray(p?.peak_hours) ? p.peak_hours : []).map((h) => String(h).replace("-", "~") + "시").join(", ");
// 서버 시각(한국 시간 ISO) → '11-17 09:00' (Figma D1 안내 띠·목록의 '만든 시각')
export const stamp = (iso) => { const m = String(iso || "").match(/^\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2})/); return m ? `${m[1]} ${m[2]}` : ""; };
// '11월 3주 (11/16 ~ 11/22)' · '2026년 11월 (11/1 ~ 11/30)'
export const periodText = (p) => (p?.label ? `${p.label}${p.range ? ` (${p.range})` : ""}` : "");

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
// 시계 하나의 지금 글자와 모양
export function clockView(c, now) {
  if (!c) return { text: "", tone: "" };
  if (c.paused) return { text: `멈춤 · ${rpClock(c.rem)} 남음`, tone: "paused" };
  const left = Number.isFinite(c.due) ? (c.due - now) / 1000 : c.rem;
  return left >= 0 ? { text: `${rpClock(left)} 남음`, tone: left < 300 ? "soon" : "" } : { text: `기한 ${rpClock(-left)} 지남`, tone: "over" };
}

// 점수 추이 선 그래프의 좌표. 그림 폭 = 칸의 실제 폭 (좁은 화면에서 글자가 같이 줄어들지 않게), 인쇄 때는 종이 폭
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

// 카드의 근거 한 줄
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

// ── 주간·월간 저장 보고서 (11/20) ──
// 승인한 글 나눔 한 줄: '답글 5 · 홍보 2' (안내문·그 밖은 있을 때만)
export function approvalLine(a) {
  if (!a) return "";
  const parts = [`답글 ${a.reply ?? 0}`, `홍보 ${a.promo ?? 0}`];
  if (a.notice) parts.push(`안내문 ${a.notice}`);
  if (a.other) parts.push(`그 밖 ${a.other}`);
  return parts.join(" · ");
}

// 타일 4개: 리뷰 · 불만 비율 · 응대 점수 · 승인한 글. 자료가 없으면 '–'
export function tilesOf(view) {
  const w = PERIOD_WORDS[view?.kind] || PERIOD_WORDS.weekly;
  const r = view?.report || {}, prev = r.previous || null, a = view?.approvals || null;
  const n = Number(r.review_count) || 0;
  const diff = prev && Number.isFinite(Number(prev.review_count)) ? n - Number(prev.review_count) : null;
  const reviewSub = !n && !Number(prev?.review_count) ? (isPast(view) ? "들어온 리뷰가 없었어요" : "아직 리뷰가 없어요")
    : diff === null ? "" : diff === 0 ? w.same : `${w.prev}보다 ${signed(diff)}`;
  const rate = r.complaint_rate == null ? NONE : `${r.complaint_rate}%`;
  const prevRate = prev ? `${w.prev} ${prev.complaint_rate == null ? NONE : `${prev.complaint_rate}%`}` : "";
  const score = Number.isFinite(Number(r.score_end)) ? `${r.score_end}점` : NONE;
  const scoreSub = Number.isFinite(Number(r.score_start)) ? `시작 ${r.score_start}점 · ${signed(r.score_change ?? (r.score_end - r.score_start))}` : "";
  return [
    { id: "rp-t-reviews", label: "리뷰", value: `${n}건`, sub: reviewSub, tint: "green" },
    { id: "rp-t-rate", label: "불만 비율", value: rate, sub: prevRate, tint: "mint" },
    { id: "rp-t-score", label: "응대 점수", value: score, sub: scoreSub, tint: "lime", title: "응대 점수는 100점에서 시작해요" },
    { id: "rp-t-approved", label: "승인한 글", value: a ? `${a.total ?? 0}개` : NONE, sub: approvalLine(a), tint: "sage" },
  ];
}

// '고칠 것' 칸의 제목: 진행 중인 기간은 '이번 주에 고칠 것'·'이번 달에 고칠 것', 끝난 기간은 '이 주 기록에서 고칠 것'
export const fixTitle = (view) => { const w = PERIOD_WORDS[view?.kind] || PERIOD_WORDS.weekly; return isPast(view) ? w.fixPast : w.fix; };

// '고칠 것' 목록 [{title, evidence, text}]. 서버 문장(리뷰 분석 서비스)은 '이번 주·이번 달' 기준이라
// - 리뷰가 0건인 기간: 끝난 기간이면 '이 주에는 들어온 리뷰가 없었어요' (다시 만들어 보라는 말 없이), 진행 중이면 '아직 없어요' + 다시 만들기 안내
// - 끝난 기간: '이번 주·이번 달'을 '이 주·이 달'로 바꿔 읽는다 (숫자·근거는 그대로)
const NOTHING = /크게 고칠 응대가 보이지 않아요/;
export function fixItems(view) {
  const w = PERIOD_WORDS[view?.kind] || PERIOD_WORDS.weekly;
  const past = isPast(view);
  const list = (Array.isArray(view?.report?.suggestions) ? view.report.suggestions : []).filter((x) => x && (x.title || x.text));
  const zero = view?.report && !Number(view.report.review_count);
  if (zero && list.every((x) => x.kind === "empty" || x.kind === "none" || NOTHING.test(`${x.title || ""} ${x.text || ""}`))) {
    return [past ? { title: `${w.this}에는 들어온 리뷰가 없었어요`, evidence: "리뷰 0건", text: "" }
      : { title: `${w.now}에 들어온 리뷰가 아직 없어요`, evidence: "리뷰 0건", text: "리뷰가 들어오면 보고서를 다시 만들어 보세요" }];
  }
  const fix = (t) => (past && t ? String(t).replace(new RegExp(w.now, "g"), w.this) : t);
  return list.map((x) => ({ title: fix(x.title), evidence: fix(x.evidence), text: fix(x.text) }));
}

// 마케팅 숫자 4칸. 승인한 홍보 글만 승인 기록으로 채우고, 나머지는 자료가 오면 그 값 (지금은 null → '–')
export function marketingNumbers(view) {
  const m = view?.marketing || {};
  const pct = (v) => (v == null ? NONE : `${Math.round(Number(v) * 100)}%`);
  const won = (v) => (v == null ? NONE : `${Number(v).toLocaleString("ko-KR")}원`);
  const recur = (v) => (v && v.before != null && v.after != null ? `${v.before} → ${v.after}건` : NONE);
  return [
    { label: "승인한 홍보 글", value: m.promo_approved == null ? NONE : `${m.promo_approved}개` },
    { label: "쿠폰 사용률", value: pct(m.coupon_usage_rate) },
    { label: "광고 건당 비용", value: won(m.ad_cost_per_order) },
    { label: "불만 재발 (공지 전→후)", value: recur(m.notice_recurrence) },
  ];
}

// 주제별 흐름: 불만·칭찬 각각 이번 기간 건수 많은 순 상위 limit 개 (이번 기간 0건인 주제는 뺌)
export function topicRows(topics, limit = 4) {
  const list = Array.isArray(topics) ? topics : [];
  const pick = (pol) => list.filter((t) => t.polarity === pol && Number(t.count) > 0)
    .sort((a, b) => Number(b.count) - Number(a.count)).slice(0, limit);
  const complaints = pick("negative"), praises = pick("positive");
  const most = Math.max(1, ...[...complaints, ...praises].map((t) => Number(t.count) || 0));
  return { complaints, praises, most };
}

// 저장 안내 띠: {tone, text}. tone: ok(저장함) · warn(낡음·저장 못 함) · ""(게스트·안내)
export function savedNote(view) {
  if (!view) return { tone: "", text: "" };
  const w = PERIOD_WORDS[view.kind] || PERIOD_WORDS.weekly;
  const t = stamp(view.created_at);
  if (view.storage === "guest") return { tone: "", text: "로그인하면 만든 보고서가 이 계정에 저장돼요." };
  if (view.storage === "unavailable") return { tone: "warn", text: "지금은 보고서를 저장하지 못했어요. 보이는 숫자는 방금 계산한 값이에요." };
  if (view.made_now) {
    return { tone: "ok", text: `${t}에 만들어 저장했어요.${view.period?.in_progress ? ` ${w.nowIs} 아직 진행 중이라, 새 리뷰가 들어오면 다시 만들어 주세요.` : ""}` };
  }
  const head = `${t}에 만들어 저장한 보고서예요.`;
  const s = view.stale;
  if (!s) return { tone: "ok", text: head };
  if (s.checked === false) return { tone: "", text: `${head} 지금 기록과 견주지 못했어요.` };
  if (!s.is_stale) return { tone: "ok", text: head };
  const parts = [];
  if (s.new_reviews > 0) parts.push(`그 뒤 새 리뷰 ${s.new_reviews}건이 들어왔어요`);
  else if (s.new_reviews < 0) parts.push(`그 뒤 리뷰가 ${-s.new_reviews}건 줄었어요`);
  if (s.responses_changed || s.approvals_changed) parts.push(parts.length ? "답글·승인 기록도 바뀌었어요" : "그 뒤 답글·승인 기록이 바뀌었어요");
  if (s.period_closed) parts.push(w.ended);
  return { tone: "warn", text: `${head} ${parts.join(". ")} → 다시 만들면 반영돼요.` };
}

// 인쇄 머리글의 한 줄
export function printMeta(now, { day, kind, period, created }) {
  const two = (n) => String(n).padStart(2, "0");
  return [
    `출력한 날 ${now.getFullYear()}-${two(now.getMonth() + 1)}-${two(now.getDate())}`,
    day ? `오늘 요약 ${day}` : "",
    period ? `${KIND_KO[kind] || ""} 보고서 ${periodText(period)}`.trim() : "",
    created ? `${stamp(created)}에 만든 보고서` : "",
    "응대 점수 최근 28일",
  ].filter(Boolean).join(" · ");
}
