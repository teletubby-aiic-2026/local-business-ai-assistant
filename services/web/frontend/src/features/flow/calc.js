// 오늘 할 일 흐름(홈·추천 카드·승인할 글·처리 완료)의 순수 계산 (예전 app.js 1 오늘 ~ 4 완료). 화면을 만지지 않는다.
import { draftsOf, praiseOf, shortBasis } from "../../lib/domain.js";

export const RULES_TITLE = "오늘부터 실천할 주방 점검 수칙";
export const RERUN_LABEL = "카드 전체 다시 만들기";
export const RERUN_ARM_MS = 5000;
// 다시 만들 때 보내는 옛 글 id 는 서버(demo.REPLACES_MAX)와 같은 20개까지
export const REPLACES_MAX = 20;

// ── 홈 숫자 타일 (R1 통계 요약 카드): 리뷰 · 불만 · 반복 불만 ──
export function homeStats(b) {
  if (!b) return null;
  const c = b.counts || {};
  const days = Math.round((new Date(b.period?.end) - new Date(b.period?.start)) / 86400000) + 1;
  const repeated = (b.groups || []).filter((g) => g.is_repeated);
  return {
    reviews: c.review_count,
    reviewsSub: Number.isFinite(days) ? `${days}일 동안` : "",
    complaints: c.complaint_count,
    complaintsSub: c.review_count ? `리뷰의 ${Math.round((c.complaint_count / c.review_count) * 100)}%` : "",
    repeated: repeated.reduce((n, g) => n + g.review_count, 0),
    repeatedSub: repeated.map((g) => g.topic_name).join(", ") || "없음",
  };
}

// 홈 차트: 브리핑의 불만 리뷰(묶음 + 묶이지 않은 불만)만 센다. 리뷰 하나에 주제 하나 기준
export function complaintsOf(b) {
  const list = [];
  (b?.groups || []).forEach((g) => (g.reviews || []).forEach((r) => list.push({ topic: g.topic_name, at: r.created_at, top: g.issue_id === b.top_issue_id })));
  (b?.single_complaints || []).forEach((x) => list.push({ topic: (x.topic_names || [])[0], at: x.created_at, top: false }));
  return list;
}

// 주제별 불만: 상위 3개 + 그 밖. 핵심 문제 묶음의 주제는 hot (빨간 막대)
export function keywordRows(b) {
  const counts = new Map(), top = new Set();
  complaintsOf(b).forEach((r) => { if (!r.topic) return; counts.set(r.topic, (counts.get(r.topic) || 0) + 1); if (r.top) top.add(r.topic); });
  const sorted = [...counts].sort((x, y) => y[1] - x[1]);
  const head = sorted.slice(0, 3);
  const max = Math.max(1, ...head.map((r) => r[1]));   // 막대 길이는 상위 주제끼리만 비교 (그 밖 합계가 1등처럼 보이지 않게)
  return {
    rows: head.map(([topic, n]) => ({ topic, n, ratio: n / max, hot: top.has(topic) })),
    rest: sorted.slice(3).map(([topic, n]) => ({ topic, n })),
  };
}

// 불만 리뷰가 몰린 시간: 11~23시 막대. 핵심 문제 묶음의 몰린 시간대(예: 17~21시)는 hot, 같은 뜻을 글자(aria-label·note)로도 쓴다
export function hourChart(b) {
  const by = new Map();
  complaintsOf(b).forEach((r) => { const h = Number(String(r.at || "").slice(11, 13)); if (Number.isFinite(h) && String(r.at || "").length >= 13) by.set(h, (by.get(h) || 0) + 1); });
  const hours = [...by.keys()];
  const from = Math.min(11, ...hours), to = Math.max(23, ...hours);
  const top = (b?.groups || []).find((g) => g.issue_id === b.top_issue_id);
  const band = String(top?.main_time_band || "").match(/(\d+)\D+(\d+)/);
  const hot = (h) => !!band && h >= Number(band[1]) && h < Number(band[2]);
  const max = Math.max(1, ...by.values());
  const cols = [];
  for (let h = from; h <= to; h++) {
    const n = by.get(h) || 0;
    cols.push({ h, n, hot: hot(h), height: n ? Math.max(6, Math.round((n / max) * 100)) : 2 });
  }
  return {
    cols,
    label: "시간대별 불만 리뷰: " + ([...by].sort((x, y) => x[0] - y[0]).map(([h, n]) => `${h}시 ${n}건`).join(", ") || "없음"),
    note: band ? `빨간 막대 = ${top.topic_name}이 몰린 ${top.main_time_band}` : "시 단위",
  };
}

// ── 2 추천 카드 ──
// 카드마다 출처·시점 한 줄 (근거 종류: review 불만 리뷰 · snapshot 상권 지표 · praise 쿠폰 메뉴 칭찬 리뷰)
export function sourceLine(p) {
  const ev = p.evidence || [];
  const reviews = ev.filter((e) => e.type === "review");
  const parts = [];
  if (reviews.length) parts.push(`리뷰 ${reviews.length}건 · 합성 데이터`);
  ev.filter((e) => e.type === "snapshot").forEach((e) => parts.push(shortBasis(e.basis)));
  const praise = praiseOf(p);
  if (praise.shown.length) parts.push(`손님 칭찬 리뷰 ${praise.total}건 · 합성 데이터`);
  return parts.join(" · ");
}

// 카드 ⓐ 점검 수칙에서 지금 체크된 id (선택지 순서). 사장님이 바꾼 값(picks) → 이미 만든 카드는 그때 고른 수칙 → 카드 기본값
// (이미 만든 카드가 기본값으로 돌아가면 '카드 전체 다시 만들기'가 고른 수칙을 잃는다)
export function measureIds(p, results, picks = {}) {
  const opts = p?.measures?.options || [];
  const cid = p?.card?.card_id;
  const made = results?.[cid]?.chosen_measures;
  const on = picks[cid] ?? (made ? made.map((x) => x.id) : p?.measures?.default || []);
  return opts.map((o) => o.id).filter((id) => on.includes(id));
}

// 승인한 글부터 20개 (승인하지 않은 글은 서버에 지울 기록이 없다)
export const replacesOf = (ids, approved) => [...ids.filter((id) => approved.has(id)), ...ids.filter((id) => !approved.has(id))].slice(0, REPLACES_MAX);

// ── 3 승인할 글 ──
// 점검 실패 = 자동 점검에 걸림(failed_reasons) → 글을 고쳐야 함
// 확인 필요 = 빠진 정보(needs_input)·하지 않은 조치/정하지 않은 보상(c7_flags) → 사장님이 사실을 확인
export const failedOf = (d) => d.failed_reasons || [];
export const checksOf = (d) => [...(d.needs_input || []), ...(d.c7_flags || [])];
export const statusOf = (d, approved) => approved.has(d.draft_id) ? ["ok", "승인 완료"]
  : failedOf(d).length ? ["bad", "점검 실패"] : checksOf(d).length ? ["warn", "확인 필요"] : ["ok", "점검 통과"];

export const regenKey = (cardId, d) => [cardId, d.generator, d.target_review_id || ""].join("|");
export const sameSlot = (a, b) => a.generator === b.generator && (a.target_review_id || "") === (b.target_review_id || "");

// 편집 칸에 보이는 글 (고치는 중 → 고쳐서 승인한 글 → 원문)
export const textOf = (s, d) => s.pending[d.draft_id] ?? d.edited_text ?? d.text;
export const isEdited = (s, d) => s.pending[d.draft_id] != null && s.pending[d.draft_id] !== (d.edited_text ?? d.text);
// 승인했거나 고치는 중인 글 수 ('카드 전체 다시 만들기'를 한 번 더 눌러야 하는지)
export const touchedOf = (s, cardId) => draftsOf(s.results, cardId).filter((d) => s.approved.has(d.draft_id) || isEdited(s, d)).length;

export function findDraft(results, id) {
  for (const r of Object.values(results)) for (const d of r.drafts || []) if (d.draft_id === id) return d;
  return null;
}
export const cardOfDraft = (cards, results, id) => cards.find((p) => (results[p.card.card_id]?.drafts || []).some((d) => d.draft_id === id)) || null;

// 글 하나를 바꾼 results (새 객체)
export function mapDraft(results, id, fn) {
  const out = {};
  for (const [k, r] of Object.entries(results)) out[k] = (r.drafts || []).some((d) => d.draft_id === id) ? { ...r, drafts: r.drafts.map((d) => (d.draft_id === id ? fn(d) : d)) } : r;
  return out;
}

// 초안 화면에 보일 카드·글: 없거나 사라졌으면 첫 카드 / 첫 미승인 글
export function pickCurrent(s) {
  const made = s.cards.filter((p) => s.results[p.card.card_id]);
  const current = s.results[s.current] && made.some((p) => p.card.card_id === s.current) ? s.current : made[0]?.card.card_id ?? null;
  const drafts = current ? draftsOf(s.results, current) : [];
  const draftId = drafts.some((d) => d.draft_id === s.draftId) ? s.draftId
    : (drafts.find((d) => !s.approved.has(d.draft_id)) || drafts[0] || {}).draft_id ?? null;
  return { made, current, drafts, draftId };
}

// 별점 n (1~5) → ★★★☆☆
export const starText = (n) => (n >= 1 && n <= 5 ? "★".repeat(n) + "☆".repeat(5 - n) : "");
