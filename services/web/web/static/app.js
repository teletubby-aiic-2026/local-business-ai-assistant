// 텔레토비 AI 비서: 단계별 화면 (1 오늘 → 2 제안 → 3 초안 → 4 완료) + 리뷰 분석. 외부 라이브러리 없이 동작.
// 화면은 주소 해시로 바꾼다: #/today #/cards #/draft #/done #/analysis (재정비/05 UI 디자인 레퍼런스 15번, 박건영 결정 11/10)
// 화면마다 할 일은 하나. API: /api/health, briefing, insight, cards, cards/{id}/run, drafts/{id}/approve, approvals, reviews.
// 오른쪽 'AI에게 묻기' 서랍은 상권 채팅: /api/assistant/* (서랍 전용 drawerApi, 서랍을 처음 열 때부터).
// 리뷰 분석(#/analysis)은 따로 떠 있던 리뷰 분석 화면의 세 화면(요약·불만 묶음·붙여넣기)을 옮겨 왔다 (11/13 통합 1차).
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const GEN_NAMES = { reply_draft: "답글", prevention_notice: "재발 방지 공지", coupon_promo: "쿠폰 홍보글" };
const KIND_NAMES = { complaint: "불만 대응", promo: "쿠폰 홍보" };
// AI 직원 3명: 오늘·분석 = 데이터 분석 비서, 카드 ⓐ·초안 = 고객 응대 비서, 카드 ⓑ = 마케팅 에이전트
const KIND_AGENT = { complaint: "고객 응대 비서", promo: "마케팅 에이전트" };
// 재발 방지 공지를 답글보다 먼저 (강조점: 다시 안 생기게 하는 조치가 먼저)
const GEN_ORDER = { prevention_notice: 0, coupon_promo: 1, reply_draft: 2 };
const byGen = (a, b) => (GEN_ORDER[a.generator] ?? 9) - (GEN_ORDER[b.generator] ?? 9);
const SOURCE_NAMES = { live: "실시간 HCX-005", seed: "시험용 저장 예시 (실제 AI 결과 아님)" };

// ── 준비 중 자리 (4차 회의에서 정한 뒤 채움) ──────────────────────────
// 메뉴 링크와 빈 화면을 둘 다 이 목록에서 만든다 (mountLater). 지우려면 여기서 빼면 끝.
// 채울 때는 index.html 에 진짜 화면(section data-view)을 만들고 여기서 빼서 ROUTES 에 이름을 넣는다. 모양은 style.css '준비 중 자리' 한 덩어리.
// long: 375px 메뉴에서 숨기는 앞부분 (다른 메뉴의 '추천 '·'처리 '와 같은 방식)
const LATER = [
  { route: "report", long: "종합 ", short: "리포트", desc: "여러 분석 결과를 한 장으로 모아 볼 화면이에요. 무엇을 담을지는 회의에서 정해요." },
  { route: "market", long: "", short: "상권", desc: "가게 주변 상권 지표를 볼 화면이에요. 지금은 홈의 '상권 저녁 매출' 칸과 추천 카드 ⓑ의 근거에서 볼 수 있어요." },
];
const ROUTES = ["today", "cards", "draft", "done", "analysis", ...LATER.map((x) => x.route)];

const state = {
  health: null, briefing: null, cards: [], results: {}, approved: new Set(), approvedLog: [],
  reviews: {}, pending: {},
  current: null,   // 초안 화면에 보이는 카드
  draftId: null,   // 초안 화면에 크게 보이는 글
  insight: null,   // 리뷰 분석 화면 (/api/insight)
  joined: [],      // 방금 붙여넣은 리뷰가 들어간 묶음 id (불만 묶음 탭에서 표시)
};
// 출처 문자열에서 URL 을 떼어 화면에는 이름만 (URL 은 링크로)
const sourceUrl = (s) => (String(s || "").match(/https?:\/\/\S+/) || [""])[0];
const shortBasis = (t) => String(t || "").replace(/\s·\s*https?:\/\/\S+/g, "");

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body?.error?.message || body?.detail?.[0]?.msg || `요청 실패 (${res.status})`);
  return body;
}

function showAlert(msg) { const el = $("alert"); el.hidden = !msg; el.textContent = msg || ""; }

// ── 화면 전환 ─────────────────────────────────────────────────────
function currentRoute() {
  const r = (location.hash.match(/^#\/(\w+)/) || [])[1];
  return ROUTES.includes(r) ? r : "today";
}
function route() {
  const name = currentRoute();
  if (name === "draft") renderDraft();
  if (name === "done") renderDone();
  if (name === "today") renderDash();
  document.querySelectorAll("[data-view]").forEach((v) => (v.hidden = v.dataset.view !== name));
  document.querySelectorAll(".menu a").forEach((a) => {
    if (a.dataset.route === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  window.scrollTo(0, 0);
  const h = document.querySelector(`[data-view="${name}"] h1`);
  if (h) h.focus({ preventScroll: true });
}
const go = (name) => { if (currentRoute() === name) route(); else location.hash = "#/" + name; };

// ── 테마 ─────────────────────────────────────────────────────────
// 운영체제 설정(라이트·다크)을 따른다. 주소 뒤 ?theme=light 를 붙이면 라이트로 고정한다.
function applyTheme() {
  if (new URLSearchParams(location.search).get("theme") === "light") document.documentElement.dataset.theme = "light";
  else delete document.documentElement.dataset.theme;
}

// ── 맨 위 띠·바닥 ─────────────────────────────────────────────────
function renderHealth(h) {
  // 시험용 실행(mock)일 때만 띄운다. live 에서는 보이지 않는다.
  $("mode-notice").hidden = !h.mode_notice;
  $("mode-notice").textContent = h.mode_notice || "";
  const p = h.parts || {};
  const items = [`리뷰: ${p.reviews || "합성 데이터"}`, p.briefing, `카드: ${p.cards}`, `글 생성: ${p.generate}`];
  $("honesty").innerHTML = items.filter(Boolean).map((t) => `<span>${esc(t)}</span>`).join("");
  const problems = [...(h.blocking || [])];
  if ((h.dev_fake_snapshots || []).length) problems.unshift(`개발용 가짜 지표가 화면에 있어요 (${h.dev_fake_snapshots.join(", ")}). 실제 값이 아니니 발표에 쓰지 마세요.`);
  if (h.review_service && h.review_service.status === "down") problems.push(`리뷰 분석 서비스(${h.review_service.url})가 꺼져 있어요.`);
  showAlert(problems.join(" "));
}

// ── 1 오늘 (브리핑) ──────────────────────────────────────────────────
function renderBriefing(b) {
  $("store-name").textContent = `${b.store.name || ""} · ${b.store.business_type_name || ""}${b.store.area_name ? " · " + b.store.area_name + " 상권" : ""}`;
  const c = b.counts;
  // 숫자 카드 줄 (R1 통계 요약 카드, 05 16번): 리뷰 · 불만 · 반복 불만
  const days = Math.round((new Date(b.period.end) - new Date(b.period.start)) / 86400000) + 1;
  const repeated = (b.groups || []).filter((g) => g.is_repeated);
  $("stat-reviews").textContent = c.review_count;
  $("stat-reviews-sub").textContent = Number.isFinite(days) ? `${days}일 동안` : "";
  $("stat-complaints").textContent = c.complaint_count;
  $("stat-complaints-sub").textContent = c.review_count ? `리뷰의 ${Math.round((c.complaint_count / c.review_count) * 100)}%` : "";
  $("stat-repeated").textContent = repeated.reduce((n, g) => n + g.review_count, 0);
  $("stat-repeated-sub").textContent = repeated.map((g) => g.topic_name).join(", ") || "없음";
  renderKeywords(b);
  renderHourChart(b);
  const snap = (b.snapshots || []).find((x) => x.value !== null && !x.dev_fake);
  $("stat-market").textContent = snap ? `${snap.value > 0 ? "+" : ""}${Number(snap.value).toFixed(2)}${snap.unit}` : "–";
  $("stat-market-sub").textContent = snap ? `${snap.area_name} · 전년 같은 분기 대비` : "상권 지표 없음";
  $("staff-data").textContent = `리뷰 ${c.review_count}건 정리 끝`;
  syncStaffStrip();
  // 오늘의 핵심 문제 (05 결정 1): 카드 ⓐ가 가리키는 묶음. 시간대는 불만이 몰린 구간(17~21시)만, 상권 지표의 17~24시와 섞지 않는다.
  const top = (b.groups || []).find((g) => g.issue_id === b.top_issue_id);
  $("hero-problem").textContent = top
    ? `${top.topic_name} ${top.review_count}건${top.is_repeated ? " 반복" : ""}${top.main_time_band ? ` · ${top.main_time_band}에 몰림` : ""}`
    : "오늘은 반복되는 불만이 없어요";
  $("today-source").textContent = `${b.period.start} ~ ${b.period.end} · 리뷰는 합성 데이터`;
  // 초안 화면의 '손님 리뷰' 칸이 쓰는 리뷰 원문 (리뷰 분석 화면의 묶음·근거는 /api/insight 에서 따로 그린다)
  state.reviews = {};
  b.groups.forEach((g) => g.reviews.forEach((r) => (state.reviews[r.review_id] = r)));
  b.pasted.forEach((r) => (state.reviews[r.review_id] = r));
}

// 홈 차트 (11/11 대시보드 시안 v2). 브리핑의 불만 리뷰(묶음 + 묶이지 않은 불만)만 센다. 리뷰 하나에 주제 하나 기준.
// 주제별 불만: 상위 3개 + 그 밖. 반복 묶음(핵심 문제) 주제는 빨간 막대. 칭찬 주제는 브리핑에 없어 그리지 않는다 (05 16번).
function complaintsOf(b) {
  const list = [];
  (b.groups || []).forEach((g) => g.reviews.forEach((r) => list.push({ topic: g.topic_name, at: r.created_at, top: g.issue_id === b.top_issue_id })));
  (b.single_complaints || []).forEach((x) => list.push({ topic: (x.topic_names || [])[0], at: x.created_at, top: false }));
  return list;
}
function renderKeywords(b) {
  const counts = new Map(), top = new Set();
  complaintsOf(b).forEach((r) => { if (!r.topic) return; counts.set(r.topic, (counts.get(r.topic) || 0) + 1); if (r.top) top.add(r.topic); });
  const sorted = [...counts].sort((x, y) => y[1] - x[1]);
  const rows = sorted.slice(0, 3);
  const rest = sorted.slice(3);
  const max = Math.max(1, ...rows.map((r) => r[1]));   // 막대 길이는 상위 주제끼리만 비교 (그 밖 합계가 1등처럼 보이지 않게)
  $("keywords").innerHTML = (rows.map(([t, n]) => `
    <div class="tb-row"><span class="tb-name">${esc(t)}</span>
      <span class="tb-track"><i class="${top.has(t) ? "hot" : ""}" style="width:${Math.round((n / max) * 100)}%"></i></span>
      <span class="tb-n">${esc(n)}건</span></div>`).join("")
    + (rest.length ? `<p class="tb-rest small muted">그 밖 ${rest.length}개 주제: ${rest.map(([t, n]) => `${esc(t)} ${esc(n)}`).join(" · ")}</p>` : ""))
    || '<p class="small muted">불만 리뷰가 없어요.</p>';
}
// 불만 리뷰가 몰린 시간: 11~23시 막대. 핵심 문제 묶음의 몰린 시간대(예: 17~21시)는 빨간 막대, 같은 뜻을 글자로도 쓴다.
function renderHourChart(b) {
  const by = new Map();
  complaintsOf(b).forEach((r) => { const h = Number(String(r.at || "").slice(11, 13)); if (Number.isFinite(h)) by.set(h, (by.get(h) || 0) + 1); });
  const hours = [...by.keys()];
  const from = Math.min(11, ...hours), to = Math.max(23, ...hours);
  const top = (b.groups || []).find((g) => g.issue_id === b.top_issue_id);
  const band = String(top?.main_time_band || "").match(/(\d+)\D+(\d+)/);
  const hot = (h) => band && h >= Number(band[1]) && h < Number(band[2]);
  const max = Math.max(1, ...by.values());
  const cols = [];
  for (let h = from; h <= to; h++) {
    const n = by.get(h) || 0;
    cols.push(`<div class="hc-col${hot(h) ? " hot" : ""}"><span class="hc-n">${n || ""}</span><i style="height:${n ? Math.max(6, Math.round((n / max) * 100)) : 2}%"></i><span class="hc-h">${h}</span></div>`);
  }
  $("hour-chart").innerHTML = cols.join("");
  $("hour-chart").setAttribute("aria-label", "시간대별 불만 리뷰: " + ([...by].sort((x, y) => x[0] - y[0]).map(([h, n]) => `${h}시 ${n}건`).join(", ") || "없음"));
  $("chart-note").textContent = band ? `빨간 막대 = ${top.topic_name}이 몰린 ${top.main_time_band}` : "시 단위";
}

// ── 2 제안 ───────────────────────────────────────────────────────
// 카드마다 출처·시점 한 줄은 늘 보이고(05 5절·7절), 근거 리뷰·이유 문장 출처는 '근거 보기'로 접는다.
function sourceLine(p) {
  const reviews = p.evidence.filter((e) => e.type === "review");
  const snaps = p.evidence.filter((e) => e.type !== "review");
  const parts = [];
  if (reviews.length) parts.push(`리뷰 ${reviews.length}건 · 합성 데이터`);
  snaps.forEach((e) => parts.push(shortBasis(e.basis)));
  return parts.join(" · ");
}
function renderCards(data) {
  state.cards = data.cards;
  $("cards").innerHTML = data.cards.map((p, i) => {
    const c = p.card;
    const made = !!state.results[c.card_id];
    const label = made ? "만든 글 보기" : c.kind === "complaint" ? "재발 방지 공지·답글 만들기" : "홍보글 만들기";
    return `<article class="card" id="card-${esc(c.card_id)}">
      <div class="kind">${i === 0 ? "ⓐ" : "ⓑ"} ${esc(KIND_NAMES[c.kind] || c.kind)}${KIND_AGENT[c.kind] ? ` <span class="agent">${esc(KIND_AGENT[c.kind])}</span>` : ""}</div>
      <h2>${esc(p.title)}</h2>
      <p class="reason">${esc(c.reason_text)}</p>
      <p class="small muted">근거: ${esc(sourceLine(p))}</p>
      ${measureBox(p)}
      <details class="more"><summary class="small">근거 보기</summary>
        <div class="ev">${p.evidence.map((e) => `<span title="${esc(e.note || "")}">${e.type === "review" ? "리뷰 " + esc(e.id) + ": “" + esc(e.text) + "”" : esc(e.text) + " · " + esc(shortBasis(e.basis))}${e.type !== "review" && sourceUrl(e.basis) ? ` · <a href="${esc(sourceUrl(e.basis))}" target="_blank" rel="noopener">원본</a>` : ""}</span>`).join("")}</div>
        <p class="small muted">이유 문장: ${esc(p.reason_source)}${(p.problems || []).length ? " · 검사기 지적 " + p.problems.length + "건" : ""}</p>
      </details>
      <button type="button" class="primary" data-run="${esc(c.card_id)}">${label}</button>
    </article>`;
  }).join("") || '<p class="muted">오늘은 추천할 카드가 없어요.</p>';
  $("no-card-b").textContent = data.no_card_b || "";
  document.querySelectorAll("#cards [data-run]").forEach((b) => b.addEventListener("click", () => choose(b.dataset.run, b)));
  renderDash();
}

// ── 홈 대시보드: 오늘 할 일 + 왼쪽 메뉴의 승인 대기 수·AI 직원 상태 (11/11 시안 v2) ─────────
// 할 일은 지금 카드에서 만든다: 카드 ⓐ(불만) → 재발 방지 공지, 답글 n개 / 카드 ⓑ(홍보) → 쿠폰 홍보글.
// 누르면 아직 안 만든 글은 만들고, 만든 글은 3 초안 화면에서 그 글을 연다.
const TODO_ICON = { done: "✓", wait: "", none: "" };
function todosOf() {
  const care = state.cards.find((p) => p.card.kind === "complaint");
  const mkt = state.cards.find((p) => p.card.kind === "promo");
  const items = [];
  const of = (p, gen) => draftsOf(p.card.card_id).filter((d) => d.generator === gen);
  const status = (p, ds, made) => !made ? ["none", "만들기"] : ds.length && ds.every((d) => state.approved.has(d.draft_id)) ? ["done", "완료"]
    : ["wait", `승인 ${ds.filter((d) => state.approved.has(d.draft_id)).length} / ${ds.length}`];
  if (care) {
    const made = !!state.results[care.card.card_id];
    const n = care.evidence.filter((e) => e.type === "review").length;
    items.push({ key: "notice", card: care, cid: care.card.card_id, gen: "prevention_notice", urgent: true, title: "재발 방지 공지 승인", sub: $("hero-problem").textContent, agent: "고객 응대 비서", st: status(care, of(care, "prevention_notice"), made) });
    items.push({ key: "reply", card: care, cid: care.card.card_id, gen: "reply_draft", title: `답글 ${made ? of(care, "reply_draft").length : n}개 승인`, sub: "같은 불만을 남긴 손님에게", agent: "고객 응대 비서", st: status(care, of(care, "reply_draft"), made) });
  }
  if (mkt) {
    const made = !!state.results[mkt.card.card_id];
    items.push({ key: "promo", card: mkt, cid: mkt.card.card_id, gen: "coupon_promo", title: "쿠폰 홍보글", sub: `저녁 매출 ${$("stat-market").textContent} · 저녁 손님 다시 부르기`, agent: "마케팅 에이전트", st: status(mkt, of(mkt, "coupon_promo"), made) });
  }
  return items;
}
function renderDash() {
  if (!state.cards.length) return;
  const items = todosOf();
  const left = items.filter((t) => t.st[0] !== "done").length;
  $("todo").innerHTML = items.map((t) => `
    <li><button type="button" class="todo-item ${t.urgent && t.st[0] !== "done" ? "urgent" : ""} ${t.st[0]}" data-todo="${esc(t.key)}">
      <span class="todo-check" aria-hidden="true">${TODO_ICON[t.st[0]]}</span>
      <span class="todo-text"><strong>${t.urgent && t.st[0] !== "done" ? '<span class="todo-urgent">급함</span>' : ""}${esc(t.title)}</strong><span class="small">${esc(t.sub)}</span><span class="small muted">${esc(t.agent)}</span></span>
      <span class="todo-st">${esc(t.st[1])}</span>
    </button></li>`).join("") || '<li class="small muted">오늘은 할 일이 없어요.</li>';
  $("todo-count").textContent = `${items.length - left} / ${items.length} 끝`;
  $("dash-title").textContent = left ? `사장님, 오늘 처리할 일 ${left}가지` : "사장님, 오늘 할 일을 모두 끝냈어요";
  document.querySelectorAll("[data-todo]").forEach((b) => b.addEventListener("click", () => runTodo(items.find((t) => t.key === b.dataset.todo), b)));
  // 왼쪽 메뉴: 승인 대기 수, AI 직원 상태 (점 색과 같은 뜻을 글자로)
  const all = Object.values(state.results).flatMap((r) => r.drafts || []);
  const waiting = all.filter((d) => !state.approved.has(d.draft_id)).length;
  $("nav-draft-count").hidden = !waiting;
  $("nav-draft-count").textContent = waiting;
  const staff = (prefix, list) => {
    const made = list.some((t) => t.st[0] !== "none");
    const done = list.length && list.every((t) => t.st[0] === "done");
    const wait = list.flatMap((t) => draftsOf(t.cid).filter((d) => d.generator === t.gen && !state.approved.has(d.draft_id))).length;
    $("dot-" + prefix).className = "dot " + (done ? "ok" : "warn");
    $("staff-" + prefix).textContent = !list.length ? "오늘 할 일 없음" : done ? "오늘 몫 끝" : made ? `승인 대기 ${wait}개` : "만들 차례";
  };
  staff("care", items.filter((t) => t.agent === "고객 응대 비서"));
  staff("mkt", items.filter((t) => t.agent === "마케팅 에이전트"));
  syncStaffStrip();
}
// 375px 홈의 직원 상태 줄: 왼쪽 메뉴 'AI 직원' 목록(#staff)을 그대로 옮겨 그린다 (내용은 한 곳에서만 정함)
function syncStaffStrip() {
  $("staff-strip").innerHTML = [...document.querySelectorAll("#staff li")].map((li) => {
    const dot = li.querySelector(".dot");
    return `<li><span class="${esc(dot ? dot.className : "dot")}" aria-hidden="true"></span><b>${esc(li.querySelector("b")?.textContent)}</b> <span class="muted">${esc(li.querySelector("b + span")?.textContent)}</span></li>`;
  }).join("");
}
async function runTodo(t, button) {
  if (!t) return;
  const id = t.cid;   // t.card는 카드 묶음({card, title, …})이라 id는 t.card.card.card_id
  if (!state.results[id]) {
    // runCard에 버튼을 넘기지 않는다: runCard는 버튼 글자를 통째로 바꿔 할 일 칸(체크·글·상태)이 깨진다
    if (button) { button.disabled = true; const st = button.querySelector(".todo-st"); if (st) st.textContent = "만드는 중…"; }
    await runCard(id);
    if (!state.results[id]) { renderDash(); return; }   // 실패하면 할 일 목록을 원래대로
  }
  const ds = draftsOf(id).filter((d) => d.generator === t.gen);
  state.current = id;
  state.draftId = (ds.find((d) => !state.approved.has(d.draft_id)) || ds[0] || {}).draft_id || null;
  if (currentRoute() === "draft") renderDraft(); else go("draft");
}

// 불만 카드: 공지에 넣을 재발 방지 조치를 사장님이 고른다 (C6 목록, 고르지 않은 조치는 글에 못 들어감)
function measureBox(p) {
  const m = p.measures || {};
  if (!(m.options || []).length) return "";
  const on = new Set(m.default || []);
  return `<fieldset class="measures"><legend class="small">공지에 넣을 재발 방지 조치</legend>
    ${m.options.map((o) => `<label class="small"><input type="checkbox" data-measure="${esc(p.card.card_id)}" value="${esc(o.id)}"${on.has(o.id) ? " checked" : ""}> ${esc(o.text)}</label>`).join("")}
  </fieldset>`;
}

// 카드를 고르면: 이미 만든 글이 있으면 그 글로, 없으면 만들고 초안으로
async function choose(cardId, button) {
  if (state.results[cardId]) { state.current = cardId; state.draftId = null; go("draft"); return; }
  await runCard(cardId, button);
}
async function runCard(cardId, button) {
  const old = button ? button.textContent : "";
  if (button) { button.disabled = true; button.textContent = "만드는 중…"; }
  try {
    const boxes = [...document.querySelectorAll(`[data-measure="${CSS.escape(cardId)}"]`)];
    const body = boxes.length ? JSON.stringify({ measures: boxes.filter((b) => b.checked).map((b) => b.value) }) : undefined;
    const result = await api(`/api/cards/${encodeURIComponent(cardId)}/run`, { method: "POST", body });
    // 다시 만들면 그 카드의 예전 글 승인·고친 내용은 버린다
    (state.results[cardId]?.drafts || []).forEach((d) => { state.approved.delete(d.draft_id); delete state.pending[d.draft_id]; });
    state.results[cardId] = result;
    state.current = cardId; state.draftId = null;
    renderCards({ cards: state.cards, no_card_b: $("no-card-b").textContent });
    go("draft");
  } catch (e) { showAlert(e.message); }
  finally { if (button && button.isConnected) { button.disabled = false; button.textContent = old; } }
}

// ── 3 초안 ───────────────────────────────────────────────────────
// 글 상태 (05 결정 4): 점검 실패와 확인 필요를 나눈다.
//  점검 실패 = C6 자동 점검에 걸림(failed_reasons) → 글을 고쳐야 함
//  확인 필요 = 빠진 정보(needs_input)·하지 않은 조치/정하지 않은 보상(c7_flags) → 사장님이 사실을 확인
const failedOf = (d) => d.failed_reasons || [];
const checksOf = (d) => [...(d.needs_input || []), ...(d.c7_flags || [])];
const statusOf = (d) => state.approved.has(d.draft_id) ? ["ok", "승인 완료"]
  : failedOf(d).length ? ["bad", "점검 실패"] : checksOf(d).length ? ["warn", "확인 필요"] : ["ok", "점검 통과"];
const draftsOf = (cardId) => [...((state.results[cardId] || {}).drafts || [])].sort(byGen);

// 초안 카드 윗부분 (R2): 이 글이 답하는 원 리뷰. 답글 = 그 리뷰 1건, 공지 = 카드 근거 리뷰, 홍보글 = 카드 근거 지표
const ICON_AI = '<svg class="ico" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2.5l2 5.5 5.5 2-5.5 2-2 5.5-2-5.5-5.5-2 5.5-2zM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9z"/></svg>';
const stars = (n) => (n >= 1 && n <= 5 ? `<span class="stars" role="img" aria-label="별점 ${n}점">${"★".repeat(n)}${"☆".repeat(5 - n)}</span>` : "");
function reviewItem(r) {
  const when = String(r.created_at || "").slice(5, 16).replace("T", " ");
  return `<li><div class="rv-meta">${stars(r.rating)}${r.channel ? `<span>${esc(r.channel)}</span>` : ""}${when ? `<span>${esc(when)}</span>` : ""}${r.input_method === "paste" ? "<span>붙여넣음</span>" : ""}</div>
    <p class="rv-text">${esc(r.text)}</p></li>`;
}
function sourceBlock(p, d) {
  const target = d.target_review_id ? state.reviews[d.target_review_id] : null;
  if (target) return `<div class="rv"><p class="rv-title">손님 리뷰</p><ul class="rv-list">${reviewItem(target)}</ul></div>`;
  const reviews = p.evidence.filter((e) => e.type === "review").map((e) => state.reviews[e.id] || { text: e.text });
  if (reviews.length) return `<div class="rv"><p class="rv-title">근거 리뷰 ${reviews.length}건</p><ul class="rv-list">${reviews.map(reviewItem).join("")}</ul></div>`;
  const snaps = p.evidence.filter((e) => e.type !== "review");
  if (snaps.length) return `<div class="rv"><p class="rv-title">근거 지표</p>${snaps.map((e) => `<p class="rv-text">${esc(e.text)}</p><div class="rv-meta"><span>${esc(shortBasis(e.basis))}</span></div>`).join("")}</div>`;
  return "";
}

function saveEdits() {
  // 다시 그리기 전에, 아직 승인하지 않은 글에서 고친 내용을 보존한다
  document.querySelectorAll("textarea[data-text]").forEach((box) => (state.pending[box.dataset.text] = box.value));
}

function renderDraft() {
  saveEdits();
  const el = $("draft");
  const made = state.cards.filter((p) => state.results[p.card.card_id]);
  if (!made.length) {
    el.innerHTML = `<div class="page-head"><h1 tabindex="-1">초안</h1></div>
      <div class="panel"><p class="muted" style="margin-top:0">아직 만든 글이 없어요. 제안에서 카드를 하나 골라 주세요.</p>
      <a class="button primary" href="#/cards">제안 보기</a></div>`;
    return;
  }
  if (!state.results[state.current]) state.current = made[0].card.card_id;
  const p = state.cards.find((x) => x.card.card_id === state.current);
  const r = state.results[state.current];
  const drafts = draftsOf(state.current);
  if (!drafts.some((d) => d.draft_id === state.draftId)) state.draftId = (drafts.find((d) => !state.approved.has(d.draft_id)) || drafts[0] || {}).draft_id;
  const d = drafts.find((x) => x.draft_id === state.draftId);
  const agent = KIND_AGENT[p.card.kind];
  const failed = d ? failedOf(d) : [], checks = d ? checksOf(d) : [];
  const done = drafts.filter((x) => state.approved.has(x.draft_id)).length;
  const approved = d && state.approved.has(d.draft_id);
  const [, statusText] = d ? statusOf(d) : [];
  const srcLabel = SOURCE_NAMES[r.source] || r.source || "";

  const name = GEN_NAMES[d?.generator] || d?.generator || "";
  el.innerHTML = `
    <div class="page-head">
      <p class="eyebrow">${agent ? `<span class="agent">${esc(agent)}</span>` : ""}<span class="badge">${esc(srcLabel)}</span></p>
      <h1 tabindex="-1">${esc(p.title)}</h1>
    </div>
    ${made.length > 1 ? `<div class="seg" role="group" aria-label="카드">${made.map((q) => `<button type="button" data-card="${esc(q.card.card_id)}"${q.card.card_id === state.current ? ' aria-current="true"' : ""}>${state.cards.indexOf(q) === 0 ? "ⓐ" : "ⓑ"} ${esc(KIND_NAMES[q.card.kind] || q.card.kind)}</button>`).join("")}</div>` : ""}
    ${r.source_note ? `<p class="small muted">${esc(r.source_note)}</p>` : ""}
    ${(r.chosen_measures || []).length ? `<p class="small">사장님이 고른 재발 방지 조치: ${r.chosen_measures.map((m) => esc(m.text)).join(", ")}</p>` : ""}
    <div class="progress"><span>승인 ${done} / ${drafts.length}</span><span class="track" aria-hidden="true"><i style="width:${drafts.length ? Math.round((done / drafts.length) * 100) : 0}%"></i></span></div>
    <ol class="draft-list" aria-label="글 ${drafts.length}개">${drafts.map((x, i) => {
      const [tone, text] = statusOf(x);
      return `<li><button type="button" data-pick="${esc(x.draft_id)}"${x.draft_id === state.draftId ? ' aria-current="true"' : ""}>${i + 1}. ${esc(GEN_NAMES[x.generator] || x.generator)} <span class="st ${tone}">${text}</span></button></li>`;
    }).join("")}</ol>
    ${d ? `<article class="draft ${approved ? "approved" : ""}" id="draft-${esc(d.draft_id)}">
      <div class="draft-head"><h2>${esc(name)}</h2>
        ${approved ? '<span class="badge ok">승인 완료</span>' : ""}
        ${failed.length ? `<span class="badge bad">점검 실패 ${failed.length}</span>` : ""}
        ${checks.length ? `<span class="badge warn">확인 필요 ${checks.length}</span>` : ""}
        ${failed.length || checks.length || approved ? "" : '<span class="badge ok">점검 통과</span>'}</div>
      ${sourceBlock(p, d)}
      <div class="reply">
        <label class="reply-label" for="text-${esc(d.draft_id)}">${ICON_AI}AI ${esc(name)} 초안<span class="sr"> (${esc(statusText)})</span></label>
        <textarea id="text-${esc(d.draft_id)}" rows="7" data-text="${esc(d.draft_id)}">${esc(state.pending[d.draft_id] ?? d.edited_text ?? d.text)}</textarea>
        ${failed.length ? `<ul class="issues bad">${failed.map((x) => `<li><b>점검 실패</b> ${esc(x)}</li>`).join("")}</ul>` : ""}
        ${checks.length ? `<ul class="issues">${checks.map((x) => `<li><b>확인 필요</b> ${esc(x)}</li>`).join("")}</ul>` : ""}
      </div>
      <div class="row">
        <button type="button" class="primary" data-approve="${esc(d.draft_id)}">${approved ? "다시 승인" : "승인"}</button>
        <button type="button" data-copy="${esc(d.draft_id)}">복사</button>
        <button type="button" class="ghost" data-rerun="${esc(state.current)}">다시 만들기</button>
      </div>
      <p class="small muted model">${esc(d.model || "")}${d.elapsed_ms ? " · " + (d.elapsed_ms / 1000).toFixed(1) + "초" : ""}</p>
    </article>` : '<div class="panel"><p class="muted">이 카드에서 만든 글이 없어요.</p></div>'}`;

  el.querySelectorAll("[data-card]").forEach((b) => b.addEventListener("click", () => { saveEdits(); state.current = b.dataset.card; state.draftId = null; renderDraft(); }));
  el.querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", () => { saveEdits(); state.draftId = b.dataset.pick; renderDraft(); }));
  el.querySelectorAll("[data-approve]").forEach((b) => b.addEventListener("click", () => approve(b.dataset.approve)));
  el.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", () => copyDraft(b.dataset.copy, b)));
  el.querySelectorAll("[data-rerun]").forEach((b) => b.addEventListener("click", () => runCard(b.dataset.rerun, b)));
}

function findDraft(id) {
  for (const r of Object.values(state.results)) for (const d of r.drafts || []) if (d.draft_id === id) return d;
  return null;
}

// 승인하면 이 카드의 다음 미승인 글로, 다 끝나면 완료 화면으로
async function approve(id) {
  const d = findDraft(id); const box = document.querySelector(`[data-text="${CSS.escape(id)}"]`);
  try {
    const entry = await api(`/api/drafts/${encodeURIComponent(id)}/approve`, { method: "POST", body: JSON.stringify({ text: box.value, original: d.text }) });
    d.edited_text = entry.edited ? box.value : null;
    delete state.pending[id];
    state.approved.add(id);
    renderDash();
    const card = state.cards.find((p) => (state.results[p.card.card_id]?.drafts || []).includes(d));
    state.approvedLog = state.approvedLog.filter((x) => x.id !== id);
    state.approvedLog.push({ id, at: entry.approved_at || new Date().toISOString(), edited: !!entry.edited,
      name: GEN_NAMES[d.generator] || d.generator, card: card ? card.title : "" });
    const next = draftsOf(state.current).find((x) => !state.approved.has(x.draft_id));
    if (next) { state.draftId = next.draft_id; renderDraft(); window.scrollTo(0, 0); }
    else go("done");
  } catch (e) { showAlert(e.message); }
}

async function copyDraft(id, button) {
  const box = document.querySelector(`[data-text="${CSS.escape(id)}"]`);
  try { await navigator.clipboard.writeText(box.value); button.textContent = "복사됨"; }
  catch { box.select(); document.execCommand("copy"); button.textContent = "복사됨"; }
  setTimeout(() => (button.textContent = "복사"), 1500);
}

// ── 4 완료 ───────────────────────────────────────────────────────
function renderDone() {
  const el = $("done");
  const log = state.approvedLog;
  if (!log.length) {
    el.innerHTML = `<div class="page-head"><h1 tabindex="-1">완료</h1></div>
      <div class="panel"><p class="muted" style="margin-top:0">아직 승인한 글이 없어요.</p>
      <a class="button primary" href="#/draft">초안으로</a></div>`;
    return;
  }
  const total = Object.values(state.results).flatMap((r) => r.drafts || []).length;
  el.innerHTML = `
    <div class="page-head"><h1 tabindex="-1">처리 완료</h1>
      <p class="muted">승인한 글 ${log.length}개 / 만든 글 ${total}개 · 게시는 복사해서 직접 올려요</p></div>
    <div class="panel">
      <div class="progress"><span>승인 ${log.length} / ${total}</span><span class="track" aria-hidden="true"><i style="width:${total ? Math.round((log.length / total) * 100) : 0}%"></i></span></div>
      <ul class="plain log">${log.map((a) => `<li><span class="badge ok">승인 완료</span> ${esc(a.name)} <span class="small muted">· ${esc(a.card)} · ${esc(String(a.at).slice(11, 19))}${a.edited ? " · 사장님이 고침" : ""}</span></li>`).join("")}</ul>
    </div>
    <button type="button" class="primary big" id="restart">처음으로</button>
    <details class="more"><summary class="small">서버 처리 기록</summary><ul id="approvals" class="plain small"></ul></details>`;
  $("restart").addEventListener("click", restart);
  loadApprovals().catch(() => {});
}

async function loadApprovals() {
  const data = await api("/api/approvals");
  const ul = $("approvals");
  if (ul) ul.innerHTML = data.items.map((a) => `<li>${esc(a.approved_at.slice(11, 19))} · ${esc(a.draft_id)} 승인${a.edited ? " (사장님이 고침)" : ""}</li>`).join("") || "<li>기록 없음</li>";
}

// 처음으로: 이 브라우저의 진행만 비운다 (서버 기록은 그대로)
function restart() {
  state.results = {}; state.approved.clear(); state.approvedLog = []; state.pending = {};
  state.current = null; state.draftId = null;
  renderCards({ cards: state.cards, no_card_b: $("no-card-b").textContent });
  go("today");
}

// ── 리뷰 분석: 요약 · 불만 묶음 · 리뷰 붙여넣기 (탭 3개) ─────────────────
// 예전에 따로 떠 있던 리뷰 분석 화면(services/review-insight 자체 페이지)의 내용을 이 화면 모양으로 옮겼다.
// 데이터: GET /api/insight (요약·불만 묶음), POST /api/reviews · DELETE /api/reviews/pasted (붙여넣기). 모두 이 서버를 거친다.
// 주제 id → 이름 (리뷰 분석 서비스의 주제 사전 app/topics.py 와 같은 이름. 모르는 id 는 그대로 보인다)
const TOPIC_NAMES = { texture: "식감", taste: "맛", portion: "양", price: "가격", delivery_time: "배달 시간", temperature: "음식 온도",
  packaging: "포장 상태", missing_item: "포장 누락", service: "응대", hygiene: "위생", menu: "메뉴 구성", atmosphere: "매장 환경", wait_time: "매장 대기" };
const SENTIMENT_NAMES = { positive: "긍정", negative: "부정", neutral: "중립", mixed: "긍정·부정 섞임" };
const topicName = (t) => TOPIC_NAMES[t] || t;
const PASTE_SAMPLES = [
  { text: "저녁 8시에 시켰는데 한 시간 넘게 걸렸고 국물도 다 식었어요", rating: 1 },
  { text: "맛은 정말 좋은데 포장이 허술해서 국물이 조금 샜어요", rating: 3 },
  { text: "점심에 먹었는데 반찬도 깔끔하고 사장님도 친절하세요!", rating: 5 },
  { text: "제육볶음 정식 고기를 불고기로 그냥 바꿔 달라고 했더니 안 된대요. 그것도 못 해 주나요? 별 하나 드립니다", rating: 1 },
];
const AN_TABS = ["summary", "issues", "paste"];

// 탭: 누르거나 ←/→/Home/End 로 옮긴다 (고른 탭만 Tab 키 순서에 들어감)
function showTab(name, focus = false) {
  AN_TABS.forEach((t) => {
    const tab = $("an-tab-" + t), on = t === name;
    tab.setAttribute("aria-selected", String(on));
    tab.tabIndex = on ? 0 : -1;
    $("an-" + t).hidden = !on;
    if (on && focus) tab.focus();
  });
}
function onTabKey(e) {
  const i = AN_TABS.indexOf(e.currentTarget.dataset.tab);
  const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: AN_TABS.length - 1 }[e.key];
  if (next === undefined) return;
  e.preventDefault();
  showTab(AN_TABS[(next + AN_TABS.length) % AN_TABS.length], true);
}

function anStatus(msg, bad = false) {
  const el = $("an-status");
  el.hidden = !msg;
  el.textContent = msg || "";
  el.classList.toggle("st", bad); el.classList.toggle("bad", bad);
}
async function loadInsight() {
  try {
    state.insight = await api("/api/insight");
    anStatus("");
    renderAnalysis(state.insight);
  } catch (e) { anStatus(`리뷰 분석을 불러오지 못했어요: ${e.message}`, true); }
}
function renderAnalysis(d) {
  $("an-period").textContent = `${d.period_start} ~ ${d.period_end}${d.data_origin === "synthetic" ? " · 리뷰는 합성 데이터" : ""}`;
  renderAnSummary(d);
  renderAnIssues(d);
}

// 요약: 리뷰 · 불만 · 반복 불만 + 칭찬·불만 키워드 (주제별 긍정·부정 수 topic_counts)
function renderAnSummary(d) {
  const days = Math.round((new Date(d.period_end) - new Date(d.period_start)) / 86400000) + 1;
  const s = d.sentiment_counts || {};
  const rep = (d.groups || []).filter((g) => g.is_repeated);
  $("an-reviews").textContent = d.review_count ?? "–";
  $("an-reviews-sub").textContent = `${Number.isFinite(days) ? days + "일 · " : ""}긍정 ${s.positive ?? 0} · 중립 ${s.neutral ?? 0}`;
  $("an-complaints").textContent = d.complaint_count ?? "–";
  $("an-complaints-sub").textContent = d.review_count ? `리뷰의 ${Math.round((d.complaint_count / d.review_count) * 100)}%` : "";
  $("an-repeated").textContent = rep.reduce((n, g) => n + g.review_count, 0);
  $("an-repeated-sub").textContent = rep.map((g) => g.topic_name).join(", ") || "없음";
  const top = (pol) => Object.entries(d.topic_counts || {}).map(([t, v]) => [topicName(t), (v || {})[pol] || 0])
    .filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const chips = (list, tone) => list.length
    ? list.map(([t, n]) => `<span class="kw-chip ${tone}">${esc(t)}<b>${esc(n)}</b></span>`).join("") : '<span class="small muted">없음</span>';
  $("an-kw").innerHTML = `<p class="kw-row"><span class="kw-title">칭찬 키워드</span>${chips(top("positive"), "pos")}</p>
    <p class="kw-row"><span class="kw-title">불만 키워드</span>${chips(top("negative"), "neg")}</p>`;
}

// 불만 묶음: 흐름 한 줄 → 묶음 카드(반복·몰린 시간대·시간대 분포·근거 인용과 리뷰 ID) → 묶이지 않은 불만
function renderAnIssues(d) {
  const groups = d.groups || [], singles = d.single_complaints || [];
  const joined = new Set(state.joined || []);
  $("an-funnel").innerHTML = `
    <div class="box"><div class="n">${esc(d.review_count)}</div><div class="small muted">리뷰</div></div><span class="arrow">→</span>
    <div class="box"><div class="n">${esc(d.complaint_count)}</div><div class="small muted">불만</div></div><span class="arrow">→</span>
    <div class="box"><div class="n">${esc(groups.length)}</div><div class="small muted">묶음 (반복 ${esc(groups.filter((g) => g.is_repeated).length)})</div></div>
    <span class="arrow">+</span>
    <div class="box"><div class="n">${esc(singles.length)}</div><div class="small muted">묶이지 않은 불만</div></div>`;
  $("an-groups").innerHTML = groups.map((g) => {
    const bands = Object.entries(g.time_bands || {});
    const max = Math.max(1, ...bands.map(([, n]) => n));
    const trend = Number.isFinite(g.previous_count) && Number.isFinite(g.recent_count) ? ` · 앞 2주 ${g.previous_count}건 → 최근 2주 ${g.recent_count}건` : "";
    return `<article class="group ${g.is_repeated ? "repeated" : ""} ${joined.has(g.issue_id) ? "new" : ""}">
      <div class="group-head"><h3>${esc(g.topic_name)} ${esc(g.review_count)}건</h3>
        ${g.is_repeated ? '<span class="badge rep">반복</span>' : ""}
        ${g.issue_id === d.top_issue_id ? '<span class="badge">추천 카드 ⓐ 근거</span>' : ""}
        ${joined.has(g.issue_id) ? '<span class="badge ok">방금 붙여넣은 리뷰가 들어감</span>' : ""}</div>
      <p class="small muted an-note">${g.main_time_band ? `주로 ${esc(g.main_time_band)}` : "여러 시간대"}${esc(trend)}</p>
      <div class="topic-bars an-bands" aria-label="시간대별 건수">${bands.map(([b, n]) => `
        <div class="tb-row"><span class="tb-name">${esc(b)}</span>
          <span class="tb-track" aria-hidden="true"><i class="${b === g.main_time_band ? "hot" : ""}" style="width:${Math.round((n / max) * 100)}%"></i></span>
          <span class="tb-n">${esc(n)}건</span></div>`).join("")}</div>
      <ul class="plain">${(g.evidence || []).slice(0, 3).map((e) => `<li class="quote">“${esc(e.quote)}” <span class="small muted">${esc(e.review_id)}</span></li>`).join("")}</ul>
    </article>`;
  }).join("") || '<div class="panel"><p class="muted" style="margin:0">묶인 불만이 없어요.</p></div>';
  $("an-singles-title").textContent = `묶이지 않은 불만 ${singles.length}건`;
  $("an-singles").innerHTML = singles.map((s) => `<li class="quote">${esc((s.topic_names || []).join("·"))}: “${esc(s.quote)}” <span class="small muted">${esc(s.review_id)}</span></li>`).join("")
    || '<li class="small muted">없어요.</li>';
}

// 리뷰 붙여넣기: 결과(감정·주제·들어간 묶음)를 보이고, 홈 숫자·추천 카드·요약·묶음을 모두 다시 불러온다 (refresh)
function renderPasteResult(r) {
  const c = r.classification || {};
  const topics = c.topics || [];
  const groups = r.groups || state.insight?.groups || [];
  const joined = (r.joined_issues || []).map((id) => groups.find((g) => g.issue_id === id)?.topic_name || id);
  const negative = topics.some((t) => t.polarity === "negative") || (c.negative_topics || []).length;
  $("paste-result").innerHTML = `<div class="panel">
    <div class="panel-head"><h2>분류 결과</h2><span class="small muted">${esc(r.review?.review_id || "")}${c.method ? ` · 분류 방식 ${esc(c.method)}` : ""}${r.review?.pii_masked ? " · 개인정보 가림" : ""}</span></div>
    <p class="rv-text">${esc(r.review?.text || "")}</p>
    <p class="small">감정 <b>${esc(SENTIMENT_NAMES[c.sentiment] || c.sentiment || "?")}</b></p>
    <div class="kw-row">${topics.length
      ? topics.map((t) => `<span class="kw-chip ${t.polarity === "negative" ? "neg" : "pos"}">${t.polarity === "negative" ? "불만" : "칭찬"} · ${esc(topicName(t.topic))}${t.evidence ? ` “${esc(t.evidence)}”` : ""}</span>`).join("")
      : '<span class="small muted">찾은 주제가 없어요.</span>'}</div>
    <p class="small an-joined">${joined.length
      ? `→ 불만 묶음에 들어갔어요: <b>${joined.map(esc).join(", ")}</b> <button type="button" class="ghost small" data-goto-tab="issues">불만 묶음 보기</button>`
      : negative ? "→ 아직 어느 묶음에도 들지 않았어요 (같은 불만이 2건 이상이면 묶여요)." : "→ 불만 주제가 없어 묶음에는 들지 않아요."}</p>
    ${(c.warnings || []).length ? `<ul class="issues">${c.warnings.map((w) => `<li>검증: ${esc(w)}</li>`).join("")}</ul>` : ""}
  </div>`;
}
async function paste() {
  const text = $("paste-text").value.trim();
  if (!text) { $("paste-msg").textContent = "리뷰 글을 넣어 주세요."; $("paste-text").focus(); return; }
  const rating = $("paste-rating").value ? Number($("paste-rating").value) : null;
  $("paste-send").disabled = true;
  $("paste-msg").textContent = "분류하는 중…";
  try {
    const r = await api("/api/reviews", { method: "POST", body: JSON.stringify({ text, rating }) });
    state.joined = r.joined_issues || [];
    renderPasteResult(r);
    $("paste-text").value = ""; $("paste-rating").value = "";
    $("paste-msg").textContent = "붙여 넣었어요. 홈 숫자와 추천 카드도 다시 불러와요…";
    await refresh();   // 홈 숫자 · 추천 카드 · 리뷰 분석(요약·묶음)을 모두 새로
    $("paste-msg").textContent = "붙여 넣었어요. 홈 숫자, 추천 카드, 요약, 불만 묶음에 반영했어요.";
  } catch (e) { $("paste-msg").textContent = e.message; }
  finally { $("paste-send").disabled = false; }
}
async function resetPaste() {
  $("paste-reset").disabled = true;
  try {
    const r = await api("/api/reviews/pasted", { method: "DELETE" });
    state.joined = [];
    $("paste-result").innerHTML = "";
    await refresh();
    $("paste-msg").textContent = `붙여넣은 리뷰${Number.isFinite(r.deleted) ? ` ${r.deleted}건` : ""}을 지웠어요. 홈 숫자와 추천 카드도 다시 불러왔어요.`;
  } catch (e) { $("paste-msg").textContent = e.message; }
  finally { $("paste-reset").disabled = false; }
}

// ── 준비 중 자리: LATER 목록으로 왼쪽 메뉴 링크와 빈 화면을 만든다 ─────────────
function mountLater() {
  const menu = document.querySelector(".side .menu");
  const main = document.querySelector(".shell > main");
  menu.insertAdjacentHTML("beforeend", '<p class="later-title" aria-hidden="true">준비 중</p>' + LATER.map((x) => `
    <a href="#/${esc(x.route)}" data-route="${esc(x.route)}" class="later"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="3 3" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/></svg><span>${x.long ? `<span class="long">${esc(x.long)}</span>` : ""}${esc(x.short)}</span><span class="badge later-badge">준비 중</span></a>`).join(""));
  main.insertAdjacentHTML("beforeend", LATER.map((x) => `
    <section class="view narrow" data-view="${esc(x.route)}" hidden>
      <div class="page-head"><p class="eyebrow"><span class="badge">준비 중</span></p><h1 tabindex="-1">${esc(x.long + x.short)}</h1></div>
      <div class="panel"><p style="margin-top:0"><strong>회의에서 정한 뒤 넣을 자리입니다.</strong></p><p class="small muted" style="margin-bottom:0">${esc(x.desc)}</p></div>
    </section>`).join(""));
}

// ── AI에게 묻기 서랍: 상권 채팅 (11/15) ──────────────────────────────
// 이 서버의 /api/assistant/* 만 부른다 (상권 서비스는 서버가 안에서 대신 부르는 프록시). 서랍을 처음 열 때 시작한다.
// 호출은 서랍 전용 drawerApi 로만 한다: 전역 api()·#alert 를 쓰지 않아서 오류는 서랍 안(#assistant-error·상태 안내)에만 보인다.
// 상권 숫자·문장은 서버가 준 그대로 textContent 로만 넣는다 (서버 글을 innerHTML 에 넣지 않음).
// 줄 종류·인용·주제 이름·값 모양은 상권 서비스 자체 채팅 화면(services/market-analysis/app/static/assistant/assistant.js)과 같다.
const CHAT_TOPICS = {
  conditions: "분석 조건", sales_total: "추정매출", sales_weekday: "요일별 매출", sales_time: "시간대별 매출",
  sales_age: "연령별 매출", stores_count: "점포 수", stores_open_close: "개업·폐업", population: "유동인구",
  change_qoq: "전분기 대비", change_yoy: "전년 동분기 대비", comparison: "상권 비교", ranking: "매출 상위 상권",
};
const CHAT_STATUS = {
  available: "", no_data: "자료 없음", not_collected: "미수집", invalid: "형식 확인 필요", error: "불러오기 실패",
  partial: "일부만 확인", missing: "자료 없음", no_observation: "관측 없음",
};
// 상태 안내 카드: [제목, 서버 문장(message)이 없을 때 쓰는 문장]. 제목은 서버 문장과 겹치지 않게 짧게
const CHAT_STATES = {
  off: ["상권 비서를 쓸 수 없어요", "이 서버에서는 상권 비서를 켜 두지 않았어요."],
  down: ["지금은 연결할 수 없어요", "상권 서비스에 연결하지 못했어요. 잠시 뒤 다시 확인해 주세요."],
  disabled: ["상권 챗봇이 쉬고 있어요", "상권 서비스는 켜져 있지만 상권 비서(챗봇)가 꺼져 있어요."],
  no_data: ["상권 자료를 준비하고 있어요", "공식 상권 자료가 아직 준비되지 않았어요. 자료가 들어오면 바로 쓸 수 있어요."],
  error: ["상권 비서를 불러오지 못했어요", "상권 비서에 문제가 생겼어요. 잠시 뒤 다시 시도해 주세요."],
};
// 처음 추천 질문 (11/15 실제 상권 서버로 확인한 4개. 다른 말투는 AI 계획기가 없는 기간을 지어내 '자료가 없어요'로 답하기도 함)
const CHAT_STARTERS = ["우리 가게 상권 매출은 어때?", "주말 매출은 어때?", "주변에 같은 업종 점포는 몇 개야?", "점심과 저녁 중 매출은 어디가 커?"];
const CHAT_WAIT_MS = 90000;   // 실제 AI 호출이라 60~90초 걸릴 수 있다. 넘으면 끊고 입력을 풀어 준다
const CHAT_SLOW = "답이 늦어지고 있어요. 잠시 뒤 다시 물어봐 주세요";
const chat = {
  started: false, loading: false, ready: false, busy: false,
  setupTried: false,          // 조건 자동 저장(setup)은 페이지마다 한 번만. '다시 확인'을 누르면 다시
  label: "",                  // 상태의 setup.label ("온기한식 · 장승배기역 · 한식음식점")
  latest: null,               // 마지막 답의 선택지 묶음 (이것만 누를 수 있음)
  chips: { list: [], starters: false },
  armed: null, tick: null,
};
const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
const chatUrl = (v) => { try { const u = new URL(String(v)); return u.protocol === "https:" || u.protocol === "http:" ? u.href : null; } catch { return null; } };
function chatValue(value, unit) {
  if (value === null || value === undefined) return "확인 불가";
  if (typeof value !== "number") return String(value);
  const text = Number.isInteger(value) && unit !== "%" ? value.toLocaleString("ko-KR")
    : value.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });   // 비율은 늘 소수 둘째 자리 (카드 문장과 같게)
  return unit ? text + unit : text;
}
const chatCondText = (c) => (c ? [c.area_name ? `${c.area_name} 상권` : null, c.industry_name, c.period_label].filter(Boolean).join(" · ") : "");
const chatId = () => "web-" + (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
const chatSuggest = (reply) => (Array.isArray(reply?.suggestions) ? reply.suggestions : []).filter((s) => typeof s === "string" && s.trim()).slice(0, 3);
const chatSameKey = (a, b) => JSON.stringify(a || {}, Object.keys(a || {}).sort()) === JSON.stringify(b || {}, Object.keys(b || {}).sort());

// 서랍 전용 호출: 같은 출처 쿠키·JSON, 90초가 넘으면 끊는다. 실패하면 message·state 를 담은 Error (화면 띠에는 아무것도 띄우지 않음)
async function drawerApi(path, options = {}, slow = "응답이 늦어지고 있어요. 잠시 뒤 다시 확인해 주세요.") {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), CHAT_WAIT_MS);
  const fail = (message, st) => Object.assign(new Error(message), { state: st });
  try {
    const res = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options, signal: ctl.signal,
      headers: { "Content-Type": "application/json", Accept: "application/json" } });
    const body = await res.json().catch(() => null);
    if (res.ok && body) return body;
    if (body?.error?.message) throw fail(body.error.message, body.error.state || "error");
    if (res.status === 404) throw fail("이 서버에는 아직 상권 비서가 연결되지 않았어요.", "off");
    if (res.status === 422) throw fail("질문을 다시 확인해 주세요. 1000자까지 쓸 수 있어요.", "invalid");
    throw fail(res.ok ? "응답을 읽지 못했어요. 잠시 뒤 다시 시도해 주세요." : `상권 비서가 응답하지 않았어요 (${res.status}). 잠시 뒤 다시 시도해 주세요.`, "error");
  } catch (e) {
    if (e.name === "AbortError") throw fail(slow, "timeout");
    if (e instanceof TypeError) throw fail("상권 비서에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.", "down");
    throw e;
  } finally { clearTimeout(timer); }
}

// 진행·안내 (#assistant-status, role=status). busy 이면 점이 깜박이고 걸린 초를 보인다 (초는 읽기 프로그램에 읽히지 않게).
// srOnly 는 화면에는 안 보이고 읽기 프로그램에만 알리는 안내
function chatStatus(text, busy = false, srOnly = false) {
  const el = $("assistant-status");
  clearInterval(chat.tick);
  el.classList.toggle("busy", !!text && busy);
  el.replaceChildren();
  if (!text) return;
  const msg = mk("span", srOnly ? "sr" : "", text);
  el.append(msg);
  if (!busy) return;
  const sec = mk("span", "drawer-sec");
  sec.setAttribute("aria-hidden", "true");
  el.append(sec);
  const t0 = Date.now();
  chat.tick = setInterval(() => {
    const s = Math.floor((Date.now() - t0) / 1000);
    sec.textContent = s >= 3 ? `${s}초` : "";
    if (s === 20) msg.textContent = `${text}. 길면 1분 넘게 걸려요`;
  }, 1000);
}
function chatError(message) { $("assistant-error").textContent = message || ""; }

// 입력칸·버튼을 지금 상태(준비·보내는 중)에 맞춘다
function chatInput() {
  const q = $("assistant-q"), off = !chat.ready || chat.busy;
  q.disabled = off;
  // 340px 서랍에서도 한 줄에 들어가게 짧게 (글 칸은 한 줄 높이에서 시작)
  q.placeholder = chat.busy ? "답을 기다리고 있어요…" : chat.ready ? "상권에 대해 물어보세요" : chat.loading ? "준비하고 있어요…" : "지금은 물어볼 수 없어요";
  $("assistant-send").disabled = off || !q.value.trim();
  $("assistant-clear").hidden = !chat.ready || !$("assistant-log").children.length;
  $("assistant-clear").disabled = chat.busy;
  $("assistant-home").disabled = off;
  $("assistant-chips").querySelectorAll("button").forEach((b) => (b.disabled = off));
  if (chat.latest) chat.latest.querySelectorAll("button").forEach((b) => (b.disabled = off));
  $("assistant-count").textContent = q.value.length >= 900 ? `${q.value.length} / 1000자` : "";
}
function chatBusy(on, text) {
  chat.busy = on;
  chatInput();
  chatStatus(on ? text : "", on);
}
function chatGrow() { const q = $("assistant-q"); q.style.height = "auto"; q.style.height = Math.min(q.scrollHeight, 140) + "px"; }
// 보낸 뒤 입력칸으로 포커스를 돌려준다. 다른 곳으로 옮겼거나 터치 화면(자판이 답을 가림)이면 그대로 둔다
function chatFocus(force = false) {
  const box = $("assistant"), a = document.activeElement;
  if (box.hidden || !chat.ready || (a && a !== document.body && !box.contains(a))) return;
  if (!force && matchMedia("(pointer: coarse)").matches) return;
  $("assistant-q").focus({ preventScroll: true });
}
// 대화 칸 안에서만 스크롤한다 (페이지는 움직이지 않음). where: start = 요소 맨 위로, near = 안 보일 때만, end = 맨 아래로
function chatReveal(el, where = "start") {
  const box = $("assistant-scroll");
  const smooth = matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  if (where === "end" || !el) { box.scrollTo({ top: box.scrollHeight, behavior: smooth }); return; }
  let y = 0;
  for (let n = el; n && n !== box; n = n.offsetParent) y += n.offsetTop;
  if (where === "near" && y >= box.scrollTop && y + el.offsetHeight <= box.scrollTop + box.clientHeight) return;
  box.scrollTo({ top: Math.max(0, y - 12), behavior: smooth });
}

function chatConditions(c) {
  const text = chatCondText(c);
  $("assistant-cond").hidden = !text;
  $("assistant-cond-text").textContent = text;
}
// 추천 질문 칩: 대화가 비었으면 고정 질문, 그 뒤에는 마지막 답의 suggestions
function chatChips(list, starters = false) {
  const box = $("assistant-chips");
  chat.chips = { list, starters };
  box.replaceChildren();
  box.hidden = !list.length;
  if (!list.length) return;
  const title = starters ? "이렇게 물어보세요" : "이어서 물어보기";
  box.setAttribute("aria-label", title);
  const head = mk("p", "drawer-chips-title", title);
  head.setAttribute("aria-hidden", "true");
  box.append(head, ...list.map((q) => {
    const b = mk("button", "chip", q);
    b.type = "button";
    b.disabled = !chat.ready || chat.busy;
    b.addEventListener("click", () => chatSend(q));
    return b;
  }));
}

// 근거 카드: 답 아래 접힌 '근거 n개'. 인용 [F1]을 누르면 펼치고 그 카드를 강조한다
function chatEvidence(cards) {
  const box = mk("details", "msg-fold msg-ev");
  box.append(mk("summary", "", `근거 ${cards.length}개`));
  const list = mk("ol", "ev-list");
  const byId = new Map();
  cards.forEach((c) => {
    const li = mk("li", "ev-card");
    li.tabIndex = -1;
    const head = mk("div", "ev-head");
    head.append(mk("span", "ev-id", c.id), mk("span", "ev-topic", CHAT_TOPICS[c.topic] || c.topic || ""));
    if (CHAT_STATUS[c.status]) head.append(mk("span", "ev-st", CHAT_STATUS[c.status]));
    li.append(head);
    if (c.text) li.append(mk("p", "ev-text", c.text));
    const nums = (Array.isArray(c.values) ? c.values : []).filter((v) => v && typeof v.value === "number");
    if (nums.length) {
      const table = mk("table", "ev-table");
      const thead = mk("thead", "sr"), tr0 = mk("tr");
      ["항목", "값", "비중"].forEach((t) => { const th = mk("th", "", t); th.scope = "col"; tr0.append(th); });
      thead.append(tr0);
      const tbody = mk("tbody");
      nums.slice(0, 12).forEach((v) => {
        const tr = mk("tr"), th = mk("th", "", v.group ? `${v.group} ${v.label}` : v.label);
        th.scope = "row";
        tr.append(th, mk("td", "", chatValue(v.value, v.unit)), mk("td", "share", typeof v.share_percent === "number" ? chatValue(v.share_percent, "%") : ""));
        tbody.append(tr);
      });
      table.append(thead, tbody);
      li.append(table);
      if (nums.length > 12) li.append(mk("p", "ev-more", `숫자 ${nums.length}개 중 12개만 보여요.`));
    }
    const warnings = (Array.isArray(c.warnings) ? c.warnings : []).filter((w) => typeof w === "string" && w);
    if (warnings.length) { const ul = mk("ul", "ev-warn"); warnings.forEach((w) => ul.append(mk("li", "", w))); li.append(ul); }
    const src = c.source_ref || {};
    if (src.source_title || src.data_version) {
      const p = mk("p", "ev-src");
      const href = chatUrl(src.source_url);
      if (src.source_title) {
        p.append("출처: ");
        if (href) { const a = mk("a", "", src.source_title); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; p.append(a); }
        else p.append(src.source_title);
      }
      if (src.data_version) p.append(`${src.source_title ? " · " : ""}자료 버전 ${src.data_version}`);
      li.append(p);
    }
    list.append(li);
    byId.set(String(c.id), li);
  });
  box.append(list, mk("p", "ev-note", "상권 통계는 상권·업종 전체의 추정치예요. 우리 가게 매출이 아니에요."));
  const show = (id) => {
    const li = byId.get(id);
    if (!li) return;
    box.open = true;
    $("assistant-log").querySelectorAll(".ev-card.hl").forEach((x) => x.classList.remove("hl"));
    li.classList.add("hl");
    chatReveal(li, "near");
    li.focus({ preventScroll: true });
  };
  return { box, has: (id) => byId.has(id), show };
}

// 한 줄을 글과 인용 버튼으로. 이 답에 없는 근거 번호는 글자 그대로 둔다
function chatLine(into, line, cite) {
  let last = 0;
  for (const m of line.matchAll(/\[(F\d+)\]/g)) {
    if (m.index > last) into.append(line.slice(last, m.index));
    into.append(cite(m[1]) || m[0]);
    last = m.index + m[0].length;
  }
  if (last < line.length) into.append(line.slice(last));
}
// 비서 답 하나: 글(목록·참고·해석·다음으로) → 선택지 → 근거 n개 → 자료 기준 안내. live = 마지막 답 (선택지를 누를 수 있음)
function chatBot(data, live) {
  const reply = data?.reply || {};
  const cards = (Array.isArray(data?.cards) ? data.cards : []).filter((c) => c && c.id);
  const msg = mk("div", "msg bot");
  const ev = cards.length ? chatEvidence(cards) : null;
  const cite = (id) => {
    if (!ev || !ev.has(id)) return null;
    const b = mk("button", "cite", id);
    b.type = "button";
    b.setAttribute("aria-label", `근거 ${id} 보기`);
    b.addEventListener("click", () => ev.show(id));
    return b;
  };
  const body = mk("div", "msg-text");
  let list = null;
  for (const line of String(reply.text || "").split("\n")) {
    if (!line.trim()) { list = null; continue; }
    if (line.startsWith("- ")) {
      if (!list) body.append((list = mk("ul")));
      const li = mk("li");
      chatLine(li, line.slice(2), cite);
      list.append(li);
      continue;
    }
    list = null;
    const kind = line.startsWith("참고:") ? "note" : line.startsWith("해석:") ? "insight" : line.startsWith("다음으로 ") ? "next" : "";
    const p = mk("p", kind ? "ln-" + kind : "");
    if (kind === "note" || kind === "insight") { p.append(mk("b", "", line.slice(0, 3))); chatLine(p, line.slice(3), cite); }
    else chatLine(p, line, cite);
    body.append(p);
  }
  msg.append(body);
  const actions = (Array.isArray(reply.actions) ? reply.actions : []).filter((a) => a && a.label);
  if (actions.length) {
    const group = mk("div", "msg-actions");
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", "선택지");
    actions.forEach((a) => {
      const b = mk("button", "pick", a.label);
      b.type = "button";
      b.disabled = !live || !chat.ready || chat.busy;
      b.addEventListener("click", () => chatChoose(group, b, a));
      group.append(b);
    });
    msg.append(group);
  }
  if (ev) msg.append(ev.box);
  const notes = (Array.isArray(reply.notes) ? reply.notes : []).filter((n) => typeof n === "string" && n);
  if (notes.length) {
    const d = mk("details", "msg-fold msg-notes");
    const ul = mk("ul");
    notes.forEach((n) => ul.append(mk("li", "", n)));
    d.append(mk("summary", "", "자료 기준 안내"), ul);
    msg.append(d);
  }
  return msg;
}
function chatUser(text) {
  const m = mk("div", "msg user");
  m.append(mk("p", "bubble", text));
  $("assistant-log").append(m);
  return m;
}
// 이전 대화: 선택지를 고른 턴은 앞 답의 선택지에서 이름을 찾아 '선택: 이름'으로 보이고 그 버튼을 고른 표시로
function chatHistory(turns) {
  const log = $("assistant-log");
  log.setAttribute("aria-live", "off");   // 처음 그릴 때 지난 대화를 통째로 읽지 않게
  log.replaceChildren();
  chat.latest = null;
  let prev = null, prevMsg = null;
  turns.forEach((t, i) => {
    if (t.user_text) chatUser(t.user_text);
    else if (t.action) {
      const picked = (prev?.reply?.actions || []).find((a) => chatSameKey(a.payload, t.action));
      chatUser(picked ? `선택: ${picked.label}` : "선택했어요");
      const b = picked && prevMsg && [...prevMsg.querySelectorAll(".pick")].find((x) => x.textContent === picked.label);
      if (b) b.setAttribute("aria-current", "true");
    }
    const m = chatBot(t, i === turns.length - 1);
    log.append(m);
    prev = t; prevMsg = m;
  });
  if (prevMsg) chat.latest = prevMsg.querySelector(".msg-actions");
  const last = turns[turns.length - 1];
  chatChips(last ? chatSuggest(last.reply) : CHAT_STARTERS, !last);
  requestAnimationFrame(() => log.setAttribute("aria-live", "polite"));
}
// 답을 받으면: 그 답을 붙이고, 선택지는 이 답 것만 누를 수 있게, 칩은 이 답의 suggestions, 조건은 응답에 있을 때만 바꾼다
function chatAnswer(r, mine) {
  const m = chatBot(r, true);
  $("assistant-log").append(m);
  chat.latest = m.querySelector(".msg-actions");
  chatChips(chatSuggest(r?.reply));
  if (r && "conditions" in r) chatConditions(r.conditions);
  requestAnimationFrame(() => chatReveal(mine, "start"));
}
function chatFailed(mine, message, chips) {
  mine.append(mk("p", "msg-fail", "보내지 못했어요"));
  chatChips(chips.list, chips.starters);
  chatError(message);
}

async function chatSend(text) {
  const value = String(text ?? "").trim();
  if (!value || chat.busy || !chat.ready) return;
  const q = $("assistant-q"), chips = chat.chips;
  chatError(""); chatDisarm();
  $("assistant-welcome").hidden = true;
  const mine = chatUser(value);
  if (q.value.trim() === value) { q.value = ""; chatGrow(); }   // 칩으로 물었으면 쓰던 글은 그대로 둔다
  chatChips([]);
  chatBusy(true, "자료를 확인하고 있어요");
  chatReveal(null, "end");
  try {
    chatAnswer(await drawerApi("/api/assistant/messages", { method: "POST", body: JSON.stringify({ text: value, client_message_id: chatId() }) }, CHAT_SLOW), mine);
  } catch (e) {
    chatFailed(mine, e.message, chips);
    if (!q.value.trim()) { q.value = value; chatGrow(); }   // 다시 보내기 쉽게 입력칸에 돌려놓는다
  } finally { chatBusy(false); chatFocus(); }
}
async function chatChoose(group, button, action) {
  if (chat.busy || !chat.ready || group !== chat.latest) return;
  const chips = chat.chips;
  chatError(""); chatDisarm();
  button.setAttribute("aria-current", "true");
  const mine = chatUser(`선택: ${action.label}`);
  chatChips([]);
  chatBusy(true, "자료를 확인하고 있어요");
  chatReveal(null, "end");
  try {
    chatAnswer(await drawerApi("/api/assistant/actions", { method: "POST", body: JSON.stringify(action.payload ?? {}) }, CHAT_SLOW), mine);
  } catch (e) {
    button.removeAttribute("aria-current");
    chatFailed(mine, e.message, chips);
  } finally { chatBusy(false); chatFocus(); }
}

// 대화 지우기: 두 번 눌러 확인 (4초 안에). 분석 조건은 서버에 남으니 setup 은 다시 부르지 않고 표시만 서버 값으로 다시 맞춘다
function chatDisarm() {
  clearTimeout(chat.armed);
  chat.armed = null;
  $("assistant-clear").textContent = "대화 지우기";
  $("assistant-clear").classList.remove("armed");
}
async function chatClear() {
  if (chat.busy || !chat.ready) return;
  if (!chat.armed) {
    $("assistant-clear").textContent = "한 번 더 누르면 지워요";
    $("assistant-clear").classList.add("armed");
    chatStatus("한 번 더 누르면 대화를 지워요", false, true);
    chat.armed = setTimeout(() => { chatDisarm(); chatStatus(""); }, 4000);
    return;
  }
  chatDisarm(); chatError("");
  let done = false;
  chatBusy(true, "대화를 지우고 있어요");
  try {
    await drawerApi("/api/assistant/conversation", { method: "DELETE" });
    $("assistant-log").replaceChildren();
    chat.latest = null;
    chatConditions(null);
    $("assistant-welcome").hidden = false;
    chatChips(CHAT_STARTERS, true);
    done = true;
    drawerApi("/api/assistant/conversation").then((c) => chatConditions(c.conditions)).catch(() => {});
  } catch (e) { chatError(e.message); }
  finally {
    chatBusy(false);
    if (done) { chatStatus("대화를 지웠어요", false, true); $("assistant-scroll").scrollTop = 0; chatFocus(true); }
  }
}

// '우리 가게 조건으로': 채팅에서 다른 상권·업종을 보고 있어도 우리 가게 조건으로 되돌린다 (setup?force=1). 대화 기록은 그대로
async function chatHome() {
  if (chat.busy || !chat.ready) return;
  const b = $("assistant-home");
  chatError(""); chatDisarm();
  chatBusy(true, "우리 가게 조건으로 맞추고 있어요");
  let done = false;
  try {
    const s = await drawerApi("/api/assistant/setup?force=1", { method: "POST" });
    if (s?.status === "unavailable") chatError(s.message || (CHAT_STATES[s.state] || CHAT_STATES.error)[1]);
    else { if (s && "conditions" in s) chatConditions(s.conditions); done = true; }
  } catch (e) { chatError(e.message); }
  finally {
    chatBusy(false);
    if (document.activeElement === document.body && !$("assistant").hidden && !$("assistant-cond").hidden) b.focus();   // 누르는 동안 막혀서 잃은 포커스
    if (done) {
      chatStatus("우리 가게 조건으로 맞췄어요", false, true);
      b.textContent = "✓ 맞췄어요";   // 조건이 이미 같으면 표시줄이 그대로라, 눌렀다는 것을 버튼 글자로 잠깐 알린다
      setTimeout(() => (b.textContent = "우리 가게 조건으로"), 2000);
    }
  }
}

// 상태 안내 카드: 상권 비서를 쓸 수 없을 때 이것만 보이고 입력칸은 막힌다
function chatState(st, message) {
  const key = CHAT_STATES[st] ? st : "error";
  const [title, fallback] = CHAT_STATES[key];
  chat.ready = false; chat.latest = null;
  $("assistant-log").replaceChildren();
  $("assistant-welcome").hidden = true;
  chatChips([]);
  chatConditions(null);
  $("assistant-state").dataset.state = key;
  $("assistant-state-title").textContent = title;
  $("assistant-state-msg").textContent = message || fallback;
  $("assistant-state").hidden = false;
  chatStatus(`${title}. ${message || fallback}`, false, true);
}
// 시작 (서랍을 처음 열 때, 또는 '다시 확인'): 상태 → (ready 이면) 이전 대화·조건 → 조건이 없으면 setup 한 번
async function chatStart() {
  if (chat.loading) return;
  chat.loading = true; chat.ready = false;
  chatError(""); chatDisarm(); chatInput();
  const retry = $("assistant-retry");
  retry.disabled = true; retry.textContent = "확인하는 중…";
  chatStatus("상권 비서를 확인하고 있어요", true);
  try {
    const st = await drawerApi("/api/assistant/status");
    chat.label = st?.setup?.label || "";
    if (st?.state !== "ready") { chatState(st?.state, st?.message); return; }
    const conv = await drawerApi("/api/assistant/conversation");
    const turns = Array.isArray(conv.turns) ? conv.turns : [];
    let cond = conv.conditions || null;
    if (!cond && !chat.setupTried) {
      chat.setupTried = true;
      chatStatus(`분석 조건을 맞추고 있어요${chat.label ? ` (${chat.label})` : ""}`, true);
      const s = await drawerApi("/api/assistant/setup", { method: "POST" });
      if (s?.status === "unavailable") { chatState(s.state, s.message); return; }
      cond = s?.conditions || null;
    }
    $("assistant-state").hidden = true;
    chat.ready = true;
    chatHistory(turns);
    chatConditions(cond);
    $("assistant-welcome").hidden = turns.length > 0;
    chatStatus("");
    const users = $("assistant-log").querySelectorAll(".msg.user");
    requestAnimationFrame(() => chatReveal(users[users.length - 1] || null, "start"));
  } catch (e) { chatState(e.state, e.message); }
  finally {
    chat.loading = false;
    retry.disabled = false; retry.textContent = "다시 확인";
    chatInput();
  }
}

// 상단 바 높이: 왼쪽 메뉴·서랍이 상단 바 아래에 붙게
function setTopH() { document.documentElement.style.setProperty("--top-h", document.querySelector(".top").offsetHeight + "px"); }
// 닫으면 서랍을 연 그 버튼(상단 'AI에게 묻기' 또는 홈 입력줄)으로 포커스를 돌려준다. 그 버튼이 화면에 없으면 상단 버튼으로.
// 처음 열 때만 상권 채팅을 시작한다 (열기 전에는 아무 호출도 하지 않아 첫 화면 로딩에 영향이 없음)
function toggleAssistant(open, opener) {
  const box = $("assistant");
  const on = open ?? box.hidden;
  document.documentElement.style.setProperty("--top-h", document.querySelector(".top").offsetHeight + "px"); // 서랍이 상단 바 아래에 붙게
  if (on && opener) state.askFrom = opener;
  box.hidden = !on;
  ["ask-ai", "ask-open"].forEach((id) => $(id).setAttribute("aria-expanded", String(on)));
  if (on) {
    $("assistant-close").focus();
    if (!chat.started) { chat.started = true; chatStart(); }
    return;
  }
  chatDisarm();
  const back = state.askFrom && state.askFrom.offsetParent !== null ? state.askFrom : $("ask-ai");
  if (!back.hidden) back.focus();
}

// ── 시작 ─────────────────────────────────────────────────────────
async function refresh() {
  state.briefing = await api("/api/briefing"); renderBriefing(state.briefing);
  const cards = await api("/api/cards");
  const before = state.cards.map((p) => p.card.card_id + p.card.review_ids + p.card.snapshot_ids).join();
  const after = cards.cards.map((p) => p.card.card_id + p.card.review_ids + p.card.snapshot_ids).join();
  if (before && before !== after) { state.results = {}; state.approved.clear(); state.approvedLog = []; state.pending = {}; state.current = null; state.draftId = null; }
  renderCards(cards);
  await loadInsight();   // 리뷰 분석(요약·불만 묶음). 실패해도 홈·카드는 그대로 두고 분석 화면에만 알린다
}

async function boot() {
  try {
    state.health = await api("/api/health"); renderHealth(state.health);
    await refresh();
    $("start").disabled = false;
    $("start").textContent = "무엇을 할까요?";
  } catch (e) { showAlert(e.message); $("start").textContent = "불러오지 못했어요"; anStatus(`리뷰 분석을 불러오지 못했어요: ${e.message}`, true); }
  setTopH();
  route();
}

applyTheme(); // ?theme=light 는 서버 응답을 기다리지 않고 바로
mountLater(); // 준비 중 메뉴·화면을 첫 route() 전에

$("start").addEventListener("click", () => go("cards"));
$("paste-send").addEventListener("click", paste);
$("paste-reset").addEventListener("click", resetPaste);
$("paste-samples").innerHTML = '<span class="small muted">예시:</span>' + PASTE_SAMPLES.map((s, i) =>
  `<button type="button" class="ghost" data-sample="${i}" title="${esc(s.text)}">${esc(s.text.slice(0, 16))}…</button>`).join("");
$("paste-samples").addEventListener("click", (e) => {
  const s = PASTE_SAMPLES[e.target.closest("[data-sample]")?.dataset.sample];
  if (s) { $("paste-text").value = s.text; $("paste-rating").value = String(s.rating); $("paste-text").focus(); }
});
document.querySelectorAll('[role="tab"][data-tab]').forEach((t) => {
  t.addEventListener("click", () => showTab(t.dataset.tab));
  t.addEventListener("keydown", onTabKey);
});
document.querySelector('[data-view="analysis"]').addEventListener("click", (e) => {
  const b = e.target.closest("[data-goto-tab]");
  if (b) showTab(b.dataset.gotoTab, true);
});
$("ask-ai").addEventListener("click", (e) => toggleAssistant(undefined, e.currentTarget));
$("ask-open").addEventListener("click", (e) => toggleAssistant(true, e.currentTarget));
window.addEventListener("resize", setTopH);
$("assistant-close").addEventListener("click", () => toggleAssistant(false));
$("assistant-clear").addEventListener("click", chatClear);
$("assistant-home").addEventListener("click", chatHome);
// 대화를 내리면 머리와 대화 칸 사이에 가는 선 (맨 위에서는 선 없이)
$("assistant-scroll").addEventListener("scroll", (e) => $("assistant").classList.toggle("scrolled", e.currentTarget.scrollTop > 0), { passive: true });
$("assistant-retry").addEventListener("click", async () => {
  chat.setupTried = false;   // '다시 확인'을 누를 때만 setup 을 다시 부를 수 있다
  await chatStart();
  (chat.ready ? $("assistant-q") : $("assistant-retry")).focus();
});
$("assistant-form").addEventListener("submit", (e) => { e.preventDefault(); chatSend($("assistant-q").value); });
$("assistant-q").addEventListener("keydown", (e) => {
  // 한글 입력 중의 Enter 는 글자를 확정할 뿐 보내지 않는다 (isComposing, Safari 는 keyCode 229). Shift+Enter 는 줄바꿈
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); chatSend(e.currentTarget.value); }
});
$("assistant-q").addEventListener("input", () => { chatGrow(); chatInput(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !e.isComposing && !$("assistant").hidden) toggleAssistant(false); });
window.addEventListener("hashchange", route);
route();
boot();
