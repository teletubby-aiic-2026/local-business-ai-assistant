// 오늘 할 일 흐름(홈·추천 카드·승인할 글·처리 완료)의 순수 계산 (예전 app.js 1 오늘 ~ 4 완료). 화면을 만지지 않는다.
import { draftsOf, genName, praiseOf, shortBasis } from "../../lib/domain.js";
import { repeatedTile } from "../analysis/calc.js";

export const RULES_TITLE = "오늘부터 실천할 주방 점검 수칙";
export const RERUN_LABEL = "카드 전체 다시 만들기";
export const RERUN_ARM_MS = 5000;
// 다시 만들 때 보내는 옛 글 id 는 서버(demo.REPLACES_MAX)와 같은 20개까지
export const REPLACES_MAX = 20;

// ── 홈 숫자 타일 (R1 통계 요약 카드): 리뷰 · 불만 · 반복 불만 ──
export function homeStats(b) {
  if (!b) return null;
  const c = b.counts || {};
  // 리뷰가 0건인 새 가게는 기간이 비어 있다 (new Date(null) 끼리 빼면 0 → '1일'로 보이지 않게)
  const days = b.period?.start && b.period?.end ? Math.round((new Date(b.period.end) - new Date(b.period.start)) / 86400000) + 1 : NaN;
  // 반복 불만은 리뷰 분석 요약 탭과 같은 숫자·부제 (0건이면 기준 '같은 불만 3건부터', 11/21 QA · 묶음 수와 합계 기준, 11/22 QA)
  const rep = repeatedTile(b.groups);
  return {
    reviews: c.review_count,
    reviewsSub: Number.isFinite(days) ? `${days}일 동안` : "",
    complaints: c.complaint_count,
    complaintsSub: c.review_count ? `리뷰의 ${Math.round((c.complaint_count / c.review_count) * 100)}%` : "",
    repeated: rep.value,
    repeatedSub: rep.sub,
  };
}

// 홈 '상권 저녁 매출' 칸의 범위 칩: [상권명, 업종 범위, 시간대]. 지표 이름에서 읽는다 (lib/domain.js marketScope 와 같은 규칙).
// 칩으로 나눠 보여서 서랍의 답(한 업종 하루 전체)과 범위가 다르다는 것을 설명 문장 없이 드러낸다
export function scopeChips(snap) {
  if (!snap) return [];
  const name = String(snap.metric_name || "");
  const hours = (name.match(/([0-9]{1,2}~[0-9]{1,2}시)/) || [])[1] || "";
  const kind = name.includes(" · ") ? name.split(" · ").pop().replace(/^두 분기\s*/, "").trim() : "";
  return [snap.area_name, kind, hours].filter(Boolean);
}

// 홈 차트: 브리핑의 불만 리뷰(묶음 + 묶이지 않은 불만)만 센다. 리뷰 하나에 주제 하나 기준
export function complaintsOf(b) {
  const list = [];
  const pasted = new Set((b?.pasted || []).map((r) => r.review_id));   // 붙여넣기·캡처로 넣은 리뷰 (단건 불만에는 넣은 방법 칸이 없어 id 로 본다)
  (b?.groups || []).forEach((g) => (g.reviews || []).forEach((r) => list.push({ topic: g.topic_name, at: r.created_at, top: g.issue_id === b.top_issue_id, paste: r.input_method === "paste" || pasted.has(r.review_id) })));
  (b?.single_complaints || []).forEach((x) => list.push({ topic: (x.topic_names || [])[0], at: x.created_at, top: false, paste: x.input_method === "paste" || pasted.has(x.review_id) }));
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
  const all = complaintsOf(b);
  // 붙여넣기·캡처로 넣은 리뷰의 시각은 넣은 시각이지 손님이 주문한 시각이 아니라서 시간대 막대에 세지 않는다 (11/21 M6)
  all.forEach((r) => { if (r.paste) return; const h = Number(String(r.at || "").slice(11, 13)); if (Number.isFinite(h) && String(r.at || "").length >= 13) by.set(h, (by.get(h) || 0) + 1); });
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
  const timed = [...by.values()].reduce((n, x) => n + x, 0);
  // total·pasted: 막대가 비었을 때 '불만 없음'과 '시각을 모름'을 나눠 말하려고 (붙여넣은 불만만 있는 가게, 11/21 QA)
  const total = Math.max(all.length, Number(b?.counts?.complaint_count) || 0);
  const pasted = all.filter((r) => r.paste).length;
  return {
    cols, total, pasted, timed,
    label: "시간대별 불만 리뷰: " + ([...by].sort((x, y) => x[0] - y[0]).map(([h, n]) => `${h}시 ${n}건`).join(", ") || "없음"),
    note: band ? `빨간 막대 = ${top.topic_name}이 몰린 ${top.main_time_band}` : "시 단위",
  };
}

// 시간 차트 칸의 빈 안내 · 덧붙이는 한 줄: {empty, extra}. 불만이 정말 0건일 때만 '불만 리뷰가 없어요' (11/21 QA)
export function hourNotes(hc) {
  if (!hc) return { empty: "", extra: "" };
  if (!hc.total) return { empty: "불만 리뷰가 없어요.", extra: "" };
  if (!hc.timed) {
    return { empty: hc.pasted ? "붙여넣은 리뷰에는 주문 시각이 없어 시간대를 그리지 않아요." : "주문 시각을 아는 불만 리뷰가 없어 시간대를 그리지 않아요.", extra: "" };
  }
  return { empty: "", extra: hc.pasted ? `붙여넣은 불만 ${hc.pasted}건은 주문 시각이 없어 시간대에서 뺐어요.` : "" };
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

// 추천 카드 머리 설명 (Figma 06 B2). 상권 지표를 쓴 카드가 있을 때만 '상권 자료'를 말하고, 시험용 실행은 AI 가 쓰지 않으므로 그렇게 (11/21 QA)
export function cardsIntro(cards, mock) {
  if (!cards?.length) return "";
  const market = cards.some((p) => (p.evidence || []).some((e) => e.type === "snapshot"));
  return `오늘 리뷰${market ? "와 상권 자료" : ""}로 고른 추천 ${cards.length}가지예요. ${mock ? "고르면 예시 글을 보여 드려요." : "고르면 AI가 글을 써요."}`;
}

// 카드 이유 문장을 AI 가 썼는지 (reason_source: "고정 문장" | "HCX-005 (검사기 통과)" | "HCX-005 실패 → 고정 문장").
// 화면에는 검사기 이야기 없이 'AI가 쓴 문장'인지만 보인다
export const reasonByAI = (p) => { const s = String(p?.reason_source || ""); return /HCX/.test(s) && !s.includes("고정 문장"); };

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

// 오늘 날짜 'YYYY-MM-DD' (이 브라우저의 시각. 서버 승인 시각의 앞 10글자와 견준다)
const ymdOf = (d) => { const pad = (n) => String(n).padStart(2, "0"); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };

// 서버 승인 목록(GET /api/approvals 의 items, card_id 포함)에서 이 카드의 **오늘** 승인한 글 id (같은 글은 한 번).
// 지난날의 승인은 이력이라 세지 않는다: 새로 만들 때 replaces 로 지우면 주간·월간 보고서의 승인 수가 줄어든다
export const priorApprovals = (items, cardId, today = new Date()) => [...new Set((Array.isArray(items) ? items : [])
  .filter((x) => x && x.draft_id && x.card_id === cardId && (!x.status || x.status === "approved")
    && String(x.approved_at || "").slice(0, 10) === ymdOf(today)).map((x) => x.draft_id))];

// 이 브라우저에 진행이 없는 카드마다 서버에 남은 오늘 승인 글 수 (다른 기기에서 했거나 보관한 진행을 되살리지 못함). card_id → 수 (0 은 뺌)
export function priorByCard(cards, results, items, today = new Date()) {
  const out = {};
  (cards || []).forEach((p) => {
    const id = p.card.card_id;
    const n = results?.[id] ? 0 : priorApprovals(items, id, today).length;
    if (n) out[id] = n;
  });
  return out;
}
// 그 카드에 붙이는 한 줄 (뒤에 '처리 완료에서 보기' 링크)
export const priorNote = (n) => `오늘 승인한 글 ${n}개가 있어요. 새로 만들면 그 승인 기록은 새 글로 바뀌어요.`;

// ── 3 승인할 글 ──
// 점검 실패 = 자동 점검에 걸림(failed_reasons) → 글을 고쳐야 함
// 확인 필요 = 빠진 정보(needs_input)·하지 않은 조치/정하지 않은 보상(c7_flags) → 사장님이 사실을 확인
export const failedOf = (d) => d.failed_reasons || [];
export const checksOf = (d) => [...(d.needs_input || []), ...(d.c7_flags || [])];
export const statusOf = (d, approved) => approved.has(d.draft_id) ? ["ok", "승인 완료"]
  : failedOf(d).length ? ["bad", "점검 실패"] : checksOf(d).length ? ["warn", "확인 필요"] : ["ok", "점검 통과"];

// 점검을 못 넘어 정해 둔 기본 문장으로 바꾼 글 (checks.used_fallback). 점검 상태 규칙(statusOf)으로는 '점검 통과'지만
// 화면은 이 글에 '점검 통과'를 붙이지 않고 '기본 문장'으로 밝힌다 (리뷰와 맞는지 사장님이 확인해야 하는 글)
export const isFallback = (d) => d?.checks?.used_fallback === true;
// 초안 상자의 점검 상태 한 줄 (읽기 프로그램용 이름표에도 씀): 기본 문장으로 바꾼 글은 '점검 통과' 대신 '기본 문장으로 바꿈'
export const draftStateText = (d, approved) => {
  const [tone, text] = statusOf(d, approved);
  return tone === "ok" && !approved.has(d.draft_id) && isFallback(d) ? FALLBACK_CHIP : text;
};
export const FALLBACK_CHIP = "기본 문장으로 바꿈";

// 초안 목록의 배지: 승인 상태(승인 완료 · 승인 대기)를 먼저, 승인 전이면 점검 결과(점검 통과 · 점검 실패 · 확인 필요 · 기본 문장)를 덧붙인다.
// 진행 숫자는 위 진행줄 하나에만 두고, 목록은 글마다 상태만 보인다. 점검 통과도 칩으로 (Figma 06 B3, 11/21 QA). 기본 문장으로 바꾼 글은 '점검 통과'를 붙이지 않음
export function listBadges(d, approved) {
  if (approved.has(d.draft_id)) return [["ok", "승인 완료"]];
  const [tone, text] = statusOf(d, approved);
  const out = tone === "ok" ? (isFallback(d) ? [["", "승인 대기"]] : [["", "승인 대기"], ["ok", "점검 통과"]]) : [["", "승인 대기"], [tone, text]];
  if (isFallback(d)) out.push(["warn", "기본 문장"]);
  return out;
}

// 초안 목록에서 답글이 어느 리뷰의 답글인지: 원 리뷰 첫 줄 앞부분 (리뷰를 모르면 "")
export function targetLine(d, reviews, max = 24) {
  const r = d?.target_review_id ? reviews?.[d.target_review_id] : null;
  const first = String(r?.text || "").split("\n")[0].trim();
  return first.length > max ? `${first.slice(0, max - 1)}…` : first;
}

// ── 4 처리 완료 ──
// 서버 승인 기록(GET /api/approvals 항목 또는 글 id)의 글 이름. 서버가 준 글 종류(kind)와 카드(card_id → 카드 제목)로 genName.
// 종류를 모르면(옛 기록) 맞춤 마케팅 글(mkt-)만 알아보고 나머지는 '글'. 맞춤 마케팅의 kind 는 '쿠폰 글' 같은 이름 그대로다
export const MARKETING_CARD = "marketing";   // 맞춤 마케팅에서 승인한 글의 card_id (서버 marketing_proxy.MARKETING_CARD_ID)
export function serverName(item, cards = []) {
  const x = typeof item === "string" ? { draft_id: item } : item || {};
  const kind = typeof x.kind === "string" ? x.kind.trim() : "";
  if (!kind) return String(x.draft_id || "").startsWith("mkt-") ? "맞춤 마케팅 글" : "글";
  const card = (cards || []).find((p) => p.card.card_id === x.card_id);
  return genName(kind, card ? card.title : "");
}
const isMktItem = (x) => String(x.draft_id).startsWith("mkt-") || x.card_id === MARKETING_CARD;

// 처리 완료의 '승인한 글' = 이 브라우저의 승인 목록 ∪ 서버 승인 기록. 새로 고침하면 브라우저 목록이 비므로 서버 기록으로 채운다 (11/21 QA B-1).
// 같은 글은 한 번만 (브라우저 쪽이 글 이름을 알아 그쪽을 쓴다), 차례는 서버가 저장한 차례, 서버에 없는 브라우저 글은 뒤에.
// cards: 서버에만 있는 글의 카드 제목을 찾을 곳 (안내문 이름·마우스를 올리면 보이는 카드 제목)
export function mergeApprovals(log, items, cards = []) {
  const local = new Map((log || []).map((a) => [a.id, a]));
  const seen = new Set();
  const out = [];
  (items || []).filter((x) => x && x.draft_id && (!x.status || x.status === "approved")).forEach((x) => {
    if (seen.has(x.draft_id)) return;
    seen.add(x.draft_id);
    const mkt = isMktItem(x);
    const card = (cards || []).find((p) => p.card.card_id === x.card_id);
    out.push(local.get(x.draft_id) || { id: x.draft_id, at: x.approved_at || "", edited: !!x.edited, text: x.text || "",
      name: serverName(x, cards), kind: x.kind || undefined, card: mkt ? "맞춤 마케팅" : card ? card.title : "", mkt, server: true });
  });
  (log || []).forEach((a) => { if (!seen.has(a.id)) { seen.add(a.id); out.push(a); } });
  return out;
}

// 승인 시각: 오늘이면 '21:00', 다른 날이면 '11-19 21:00' (서버 기록에는 지난날 승인도 있어서)
export function whenText(at, today = new Date()) {
  const s = String(at || "");
  if (s.length < 16) return "";
  return s.slice(0, 10) === ymdOf(today) ? s.slice(11, 16) : `${s.slice(5, 10)} ${s.slice(11, 16)}`;
}

// 글 한 건 '다시 만들기' 뒤 안내 한 줄: 새 글이 예전 글과 같거나 또 기본 문장이면 사실대로 알린다
export function regenNote(before, fresh, source) {
  if (source === "seed") return "시험용 실행이라 같은 예시 글을 다시 불러왔어요. 다른 글은 그대로예요.";
  const same = String(fresh?.text ?? "").trim() === String(before?.text ?? "").trim();
  if (isFallback(fresh)) {
    return same ? "다시 만들었지만 같은 기본 문장이 나왔어요. 리뷰와 맞게 직접 고쳐서 승인해 주세요."
      : "다시 만들었지만 이번에도 기본 문장으로 바뀌었어요. 리뷰와 맞는지 확인하고 고쳐서 승인해 주세요.";
  }
  if (same) return "다시 만들었지만 같은 글이 나왔어요. 필요하면 직접 고쳐서 승인해 주세요.";
  return "이 글만 새로 만들었어요. 다른 글은 그대로예요.";
}

export const regenKey = (cardId, d) => [cardId, d.generator, d.target_review_id || ""].join("|");
export const sameSlot = (a, b) => a.generator === b.generator && (a.target_review_id || "") === (b.target_review_id || "");

// 편집 칸에 보이는 글 (고치는 중 → 고쳐서 승인한 글 → 원문)
export const textOf = (s, d) => s.pending[d.draft_id] ?? d.edited_text ?? d.text;
export const isEdited = (s, d) => s.pending[d.draft_id] != null && s.pending[d.draft_id] !== (d.edited_text ?? d.text);
// 지금 보이는 글이 AI 초안 원문과 다른지 (고치는 중이거나 고쳐서 승인). 점검 칩은 원문 기준이라 그때 한 줄을 붙인다.
// 앞뒤 공백만 다르면 같은 글로, 고쳤다가 원문으로 되돌리면 다시 같은 글로 본다 (11/22 QA: 고친 글이 점검을 통과한 것처럼 읽혔음)
export const changedFromDraft = (s, d) => String(textOf(s, d) ?? "").trim() !== String(d.text ?? "").trim();
export const EDITED_CHECK_NOTE = "점검 결과는 고치기 전 글 기준이에요.";
// 승인했거나 고치는 중인 글 수 ('카드 전체 다시 만들기'를 한 번 더 눌러야 하는지)
export const touchedOf = (s, cardId) => draftsOf(s.results, cardId).filter((d) => s.approved.has(d.draft_id) || isEdited(s, d)).length;

export function findDraft(results, id) {
  for (const r of Object.values(results)) for (const d of r.drafts || []) if (d.draft_id === id) return d;
  return null;
}
export const cardOfDraft = (cards, results, id) => cards.find((p) => (results[p.card.card_id]?.drafts || []).some((d) => d.draft_id === id)) || null;
// 그 글을 만든 카드 id (results 의 열쇠). 모르면 null
export const cardIdOfDraft = (results, id) => Object.keys(results).find((k) => (results[k]?.drafts || []).some((d) => d.draft_id === id)) || null;

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
