// 종합 리포트의 글자·숫자 다듬기 (시계·점수 추이 계산, 근거 한 줄, 11/20 주간·월간 저장 보고서의 타일·안내 띠)

// 카드의 근거 한 줄은 추천 카드 화면과 같은 함수를 쓴다 (예전에는 여기에 같은 함수를 따로 두어 한쪽만 고치면 어긋났다, 11/21 QA)
export { sourceLine } from "../flow/calc.js";

// 주제별 흐름의 기준: 주제는 리뷰 속 문장 단위라 불만 리뷰 안의 칭찬도 칭찬 주제로 센다 ('손님 칭찬 요약'은 리뷰 단위, 11/21 QA)
export const TOPIC_BASIS = "리뷰 속 문장 기준";
export const PRAISE_TOPIC_NOTE = "불만 리뷰 속 칭찬 문장도 셈";

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
// 점수 변화 글자: 0이면 맨숫자 '0' 대신 '변화 없음' (11/22 QA R3: '98 → 98 0'을 읽지 못함)
export const NO_CHANGE = "변화 없음";
export const changeText = (n) => (n != null && Number(n) === 0 ? NO_CHANGE : signed(n));
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
  const scoreSub = Number.isFinite(Number(r.score_start)) ? `시작 ${r.score_start}점 · ${changeText(r.score_change ?? (r.score_end - r.score_start))}` : "";
  return [
    { id: "rp-t-reviews", label: "리뷰", value: `${n}건`, sub: reviewSub, tint: "green" },
    { id: "rp-t-rate", label: "불만 비율", value: rate, sub: prevRate, tint: "mint" },
    { id: "rp-t-score", label: "응대 점수", value: score, sub: scoreSub, tint: "lime", title: "응대 점수는 100점에서 시작해요" },
    { id: "rp-t-approved", label: "승인한 글", value: a ? `${a.total ?? 0}개` : NONE, sub: approvalLine(a), tint: "sage" },
  ];
}

// '고칠 것' 칸의 제목: 진행 중인 기간은 '이번 주에 고칠 것'·'이번 달에 고칠 것', 끝난 기간은 '이 주 기록에서 고칠 것'
export const fixTitle = (view) => { const w = PERIOD_WORDS[view?.kind] || PERIOD_WORDS.weekly; return isPast(view) ? w.fixPast : w.fix; };

// 리뷰가 0건인 기간인가 (보고서가 없으면 아님)
const noReviews = (view) => !!view?.report && !Number(view.report.review_count);

// '고칠 것' 목록 [{title, evidence, text}]. 서버 문장(리뷰 분석 서비스)은 '이번 주·이번 달' 기준이라
// - 리뷰가 0건인 기간: 빈 목록 (서버도 11/22부터 빈 목록. 그 전에 저장된 보고서에 든 기간 밖 반복 불만도 보이지 않게, QA R5)
// - 끝난 기간: '이번 주·이번 달'을 '이 주·이 달'로 바꿔 읽는다 (숫자·근거는 그대로)
export function fixItems(view) {
  const w = PERIOD_WORDS[view?.kind] || PERIOD_WORDS.weekly;
  const past = isPast(view);
  if (noReviews(view)) return [];
  const list = (Array.isArray(view?.report?.suggestions) ? view.report.suggestions : []).filter((x) => x && (x.title || x.text));
  const fix = (t) => (past && t ? String(t).replace(new RegExp(w.now, "g"), w.this) : t);
  return list.map((x) => ({ title: fix(x.title), evidence: fix(x.evidence), text: fix(x.text) }));
}

// '고칠 것'이 비었을 때 한 줄. 리뷰 0건이면 그래서 고르지 않았다고 (끝난 기간에는 '아직' 없이)
export function fixEmpty(view) {
  const w = PERIOD_WORDS[view?.kind] || PERIOD_WORDS.weekly;
  if (!noReviews(view)) return "제안이 없어요.";
  return isPast(view) ? `${w.this}에는 리뷰가 없어 고칠 것을 고르지 않았어요.` : `${w.now}에는 아직 리뷰가 없어 고칠 것을 고르지 않았어요.`;
}

// 인기 메뉴 칸 제목: 셋 다 찼을 때만 'TOP 3' (1~2개인데 'TOP 3'이면 빠진 것처럼 보였다, 11/22 QA R4). 인쇄용 A4(report.py menu_heading)와 같은 규칙
export const menuTitle = (menus) => ((Array.isArray(menus) ? menus.length : 0) >= 3 ? "인기 메뉴 TOP 3" : "인기 메뉴");

// 응대 점수가 왜 이 숫자인지: 크게 깎인 것부터 limit 줄은 바로 보이고 나머지는 접는다 {shown, rest} (11/22 QA R2: 98점의 까닭을 못 찾음)
export function scoreReasons(reasons, limit = 3) {
  const list = (Array.isArray(reasons) ? reasons : []).filter((x) => x && Number(x.delta));
  const sorted = list.map((x, i) => [x, i]).sort((a, b) => Number(a[0].delta) - Number(b[0].delta) || a[1] - b[1]).map(([x]) => x);
  return { shown: sorted.slice(0, limit), rest: sorted.slice(limit) };
}

// 마케팅 숫자 칸 {cells, elsewhere}. 승인한 홍보 글은 늘 (승인 기록), 쿠폰 사용률·광고비·불만 재발은 값이 올 때만 칸을 그린다.
// 지금 서버는 그 셋을 늘 null 로 줘서(web/reports.py) '–' 세 칸이 '입력이 사라졌다'로 읽혔다 (11/22 QA R1) → elsewhere 면 맞춤 마케팅 보고서로 안내
export function marketingNumbers(view) {
  const m = view?.marketing || {};
  const pct = (v) => (v == null ? NONE : `${Math.round(Number(v) * 100)}%`);
  const won = (v) => (v == null ? NONE : `${Number(v).toLocaleString("ko-KR")}원`);
  const recur = (v) => (v && v.before != null && v.after != null ? `${v.before} → ${v.after}건` : NONE);
  const all = [
    { label: "승인한 홍보 글", value: m.promo_approved == null ? NONE : `${m.promo_approved}개` },
    { label: "쿠폰 사용률", value: pct(m.coupon_usage_rate), optional: true },
    { label: "광고 건당 비용", value: won(m.ad_cost_per_order), optional: true },
    { label: "불만 재발 (공지 전→후)", value: recur(m.notice_recurrence), optional: true },
  ];
  return {
    cells: all.filter((x) => !x.optional || x.value !== NONE).map(({ label, value }) => ({ label, value })),
    elsewhere: all.some((x) => x.optional && x.value === NONE),
  };
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

// '다시 만들기' 전후 보고서를 견준 값 {reviews, approvals} (같은 기간일 때만, 모르는 칸은 null). 서버 응답에 바뀐 내용이 없어 화면이 견준다 (11/21 QA)
export function remadeDiff(before, after) {
  if (!before || !after || before.kind !== after.kind || before.period?.key !== after.period?.key) return { reviews: null, approvals: null };
  const diff = (a, b) => (Number.isFinite(Number(a)) && Number.isFinite(Number(b)) && a != null && b != null ? Number(a) - Number(b) : null);
  return { reviews: diff(after.report?.review_count, before.report?.review_count), approvals: diff(after.approvals?.total, before.approvals?.total) };
}

// 다시 만든 뒤 덧붙이는 괄호 안 글: '새 리뷰 3건 · 승인 2건 반영' · '리뷰·승인 수는 그대로' · (견줄 수 없으면) ""
export function remadeText(d) {
  if (!d || (d.reviews == null && d.approvals == null)) return "";
  // 늘어난 것은 '… 반영', 줄어든 것(붙여넣은 리뷰 지우기·처음부터 다시)은 '… 빠짐'
  const added = [], removed = [];
  if (d.reviews > 0) added.push(`새 리뷰 ${d.reviews}건`);
  else if (d.reviews < 0) removed.push(`리뷰 ${-d.reviews}건 빠짐`);
  if (d.approvals > 0) added.push(`승인 ${d.approvals}건`);
  else if (d.approvals < 0) removed.push(`승인 ${-d.approvals}건 빠짐`);
  const parts = [added.length ? `${added.join(" · ")} 반영` : "", ...removed].filter(Boolean);
  return parts.length ? parts.join(" · ") : "리뷰·승인 수는 그대로";
}

// 저장 안내 띠: {tone, text}. tone: ok(저장함) · warn(낡음·저장 못 함) · ""(게스트·안내).
// remade: 방금 '다시 만들기'로 받은 보고서면 전후를 견준 값 (remadeDiff). 무엇이 바뀌었는지 한 마디 붙인다 (11/21 QA)
export function savedNote(view, remade = null) {
  if (!view) return { tone: "", text: "" };
  const w = PERIOD_WORDS[view.kind] || PERIOD_WORDS.weekly;
  const t = stamp(view.created_at);
  const changed = remade ? remadeText(remade) : "";
  if (view.storage === "guest") {
    return { tone: "", text: `${remade ? `다시 계산했어요${changed ? ` (${changed})` : ""}. ` : ""}로그인하면 만든 보고서가 이 계정에 저장돼요.` };
  }
  if (view.storage === "unavailable") return { tone: "warn", text: "지금은 보고서를 저장하지 못했어요. 보이는 숫자는 방금 계산한 값이에요." };
  if (view.made_now) {
    const head = remade ? `${t}에 다시 만들어 저장했어요${changed ? ` (${changed})` : ""}.` : `${t}에 만들어 저장했어요.`;
    return { tone: "ok", text: `${head}${view.period?.in_progress ? ` ${w.nowIs} 아직 진행 중이라, 새 리뷰가 들어오면 다시 만들어 주세요.` : ""}` };
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
