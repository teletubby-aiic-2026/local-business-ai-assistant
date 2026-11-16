// 텔레토비 AI 비서: 단계별 화면 (1 오늘 → 2 제안 → 3 초안 → 4 완료) + 리뷰 분석. 외부 라이브러리 없이 동작.
// 화면은 주소 해시로 바꾼다: #/today #/cards #/draft #/done #/analysis #/marketing #/report (재정비/05 UI 디자인 레퍼런스 15번, 박건영 결정 11/10)
// 화면마다 할 일은 하나. API: /api/health, briefing, insight, cards, cards/{id}/run, drafts/{id}/approve, approvals, reviews.
// 오른쪽 'AI에게 묻기' 서랍은 상권 채팅: /api/assistant/* (서랍 전용 drawerApi, 서랍을 처음 열 때부터).
// 리뷰 분석(#/analysis)은 따로 떠 있던 리뷰 분석 화면의 세 화면(요약·불만 묶음·붙여넣기)을 옮겨 왔다 (11/13 통합 1차).
// 붙여넣기 탭의 '캡처로 넣기'와 종합 리포트(#/report)는 고객응대 API(/api/care/*, careApi)를 쓴다 (11/15).
// 맞춤 마케팅(#/marketing)은 마케팅 서비스 프록시(/api/marketing-survey/*, 전용 mktApi)를 쓴다 (11/16).
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
// 종합 리포트(#/report)는 11/15 진짜 화면으로 채웠다 (index.html section data-view="report", 아래 '종합 리포트' 덩어리)
const LATER = [
  { route: "market", long: "", short: "상권", desc: "가게 주변 상권 지표를 볼 화면이에요. 지금은 홈의 '상권 저녁 매출' 칸, 종합 리포트의 상권 요약, 추천 카드 ⓑ의 근거에서 볼 수 있어요." },
];
const ROUTES = ["today", "cards", "draft", "done", "analysis", "marketing", "report", ...LATER.map((x) => x.route)];

const state = {
  health: null, briefing: null, cards: [], results: {}, approved: new Set(), approvedLog: [],
  reviews: {}, pending: {},
  current: null,   // 초안 화면에 보이는 카드
  draftId: null,   // 초안 화면에 크게 보이는 글
  insight: null,   // 리뷰 분석 화면 (/api/insight)
  joined: [],      // 방금 붙여넣은 리뷰가 들어간 묶음 id (불만 묶음 탭에서 표시)
  booted: false, bootError: null,   // 처음 불러오기가 끝났는지·실패 문장 (종합 리포트의 상권·마케팅 요약이 씀)
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
  if (name === "report") loadReport(); else rpStop();
  if (name === "marketing") mktOpen();   // 맞춤 마케팅은 이 화면을 처음 열 때 시작한다 (첫 화면 로딩에 영향 없음)
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

// ── 왼쪽 메뉴 접기 (11/16) ─────────────────────────────────────────
// 상단 바의 #menu-toggle 로 왼쪽 메뉴를 접고 편다. 상태는 <html data-menu="open|closed"> 하나로만 알리고, 모양·배치는 style.css 가 정한다.
//   1025px 이상   펼친 채 시작. 접으면 본문이 넓어지고, 접었는지를 localStorage(ic26.menu)에 기억한다
//   761~1024px   늘 접힌 채 시작 (기억한 값과 상관없음). 펼치면 본문을 밀지 않고 위에 덮는다 → 바깥·Esc·메뉴 항목을 누르면 닫힘
//   760px 이하    메뉴가 상단 바 아래 가로줄이라 접지 않는다 (토글 버튼이 없음)
const MENU_KEY = "ic26.menu";
const menuMid = window.matchMedia("(min-width: 761px) and (max-width: 1024px)");
const menuPhone = window.matchMedia("(max-width: 760px)");
// 창 폭이 소수일 때(화면 배율) 구간 사이 1px 틈은 style.css 와 같이 넓은 화면으로 본다
const menuBandNow = () => (menuMid.matches ? "mid" : menuPhone.matches ? "phone" : "wide");
let menuBand = "";       // 지금 폭 구간. 구간이 바뀔 때만 그 구간의 처음 상태로 되돌린다
let menuPref = "open";   // localStorage 를 못 쓰는 환경(사생활 보호 모드 등)에서는 이 값으로만 기억한다 (새로고침하면 처음으로)
function menuRead() { try { return localStorage.getItem(MENU_KEY) || menuPref; } catch (e) { return menuPref; } }
function menuWrite(v) { menuPref = v; try { localStorage.setItem(MENU_KEY, v); } catch (e) { /* 저장하지 못해도 이번 화면에서는 그대로 동작 */ } }
const menuIsOpen = () => document.documentElement.dataset.menu !== "closed";
const menuOverlayOpen = () => menuBand === "mid" && menuIsOpen();   // 본문 위에 덮인 메뉴가 열려 있는지
function setMenu(open) {
  document.documentElement.dataset.menu = open ? "open" : "closed";
  const b = $("menu-toggle"), label = open ? "왼쪽 메뉴 접기" : "왼쪽 메뉴 펼치기";
  b.setAttribute("aria-expanded", String(open));
  b.setAttribute("aria-label", label);
  b.title = label;
  setTopH();   // 접으면 상단 바에 로고가 들어와 높이가 달라질 수 있다 (덮는 메뉴는 상단 바 바로 아래에서 시작)
}
function applyMenu() {
  menuBand = menuBandNow();
  setMenu(menuBand === "mid" ? false : menuBand === "wide" ? menuRead() !== "closed" : true);
}
function toggleMenu() {
  const open = !menuIsOpen();
  setMenu(open);
  if (menuBand !== "mid") { menuWrite(open ? "open" : "closed"); return; }
  // 덮는 메뉴: 기억하지 않는다. 열면 포커스를 메뉴(지금 화면의 항목)로, 닫으면 토글 버튼으로
  if (open) (document.querySelector('.side .menu a[aria-current="page"]') || document.querySelector(".side .menu a")).focus();
  else $("menu-toggle").focus();
}
// 덮는 메뉴 닫기. 포커스가 메뉴 안에 있었으면(또는 잃었으면) 토글 버튼으로 돌려준다. 이미 다른 곳으로 옮겨 갔으면 건드리지 않는다
function closeMenuOverlay() {
  const a = document.activeElement;
  const back = !a || a === document.body || !!a.closest(".side");
  setMenu(false);
  if (back) $("menu-toggle").focus();
}
// 메뉴가 접혀 있는 동안 토글 버튼 위에 보이는 승인 대기 수 (renderDash 가 #nav-draft-count 와 같이 맞춘다)
function syncMenuCount(n) {
  const c = $("menu-toggle-count");
  c.hidden = !n;
  c.innerHTML = n ? `<span aria-hidden="true">${esc(n)}</span><span class="sr">승인 대기 ${esc(n)}개</span>` : "";
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
// 근거 종류는 셋: review(불만 리뷰, 카드 ⓐ) · snapshot(상권 지표, 카드 ⓑ) · praise(쿠폰 메뉴를 칭찬한 리뷰, 카드 ⓑ).
function sourceLine(p) {
  const reviews = p.evidence.filter((e) => e.type === "review");
  const snaps = p.evidence.filter((e) => e.type === "snapshot");
  const parts = [];
  if (reviews.length) parts.push(`리뷰 ${reviews.length}건 · 합성 데이터`);
  snaps.forEach((e) => parts.push(shortBasis(e.basis)));
  if (praiseOf(p).shown.length) parts.push(`손님 칭찬 리뷰 ${praiseOf(p).total}건 · 합성 데이터`);
  return parts.join(" · ");
}
// 카드 ⓑ 의 칭찬 근거: 보여 줄 리뷰(최대 3건), 쿠폰 메뉴, 그 메뉴를 언급한 칭찬 리뷰 수 (card.review_ids 가 전부를 담는다)
function praiseOf(p) {
  const shown = p.evidence.filter((e) => e.type === "praise");
  return { shown, menu: shown.length ? shown[0].menu : "", total: Math.max(shown.length, (p.card.review_ids || []).length) };
}
// '근거 보기'의 칩 하나. 리뷰 글·id 는 사용자 입력일 수 있어 esc() 를 거친다. 지표(snapshot)만 기준·'원본' 링크가 붙는다
function evidenceChip(e) {
  const body = e.type === "review" ? `리뷰 ${esc(e.id)}: “${esc(e.text)}”`
    : e.type === "praise" ? `칭찬 리뷰 ${esc(e.id)}: “${esc(e.text)}”`
    : `${esc(e.text)} · ${esc(shortBasis(e.basis))}${sourceUrl(e.basis) ? ` · <a href="${esc(sourceUrl(e.basis))}" target="_blank" rel="noopener">원본</a>` : ""}`;
  return `<span title="${esc(e.note || "")}">${body}</span>`;
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
        <div class="ev">${p.evidence.map(evidenceChip).join("")}</div>
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
    const menu = praiseOf(mkt).menu;   // 손님 칭찬 리뷰에 나온 쿠폰 메뉴 (칭찬 근거가 없으면 빈 글자 → 예전 문구)
    items.push({ key: "promo", card: mkt, cid: mkt.card.card_id, gen: "coupon_promo", title: "쿠폰 홍보글", sub: `저녁 매출 ${$("stat-market").textContent} · ${menu ? `손님이 칭찬한 ${menu} 쿠폰으로 ` : ""}저녁 손님 다시 부르기`, agent: "마케팅 에이전트", st: status(mkt, of(mkt, "coupon_promo"), made) });
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
  syncMenuCount(waiting);   // 메뉴가 접혀 있을 때는 토글 버튼 위에
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

// 불만 카드: 오늘부터 가게에서 실천할 점검 수칙을 사장님이 고른다 (C6 조치 목록). 문서용 옵션이 아니라 현장에서 할 일로 보이게 쓴다.
// 고른 수칙만 재발 방지 공지에 들어가고, 고르지 않은 것은 글에 못 들어간다. (답글은 C6 가 늘 같은 조치 문장을 붙여서 '공지에 반영'이라고만 적는다)
const RULES_TITLE = "오늘부터 실천할 주방 점검 수칙";
function measureBox(p) {
  const m = p.measures || {};
  if (!(m.options || []).length) return "";
  const on = new Set(m.default || []);
  // 이미 만든 카드는 그때 고른 수칙을 체크해 둔다. 카드를 다시 그릴 때 기본값으로 돌아가면 '카드 전체 다시 만들기'가 고른 수칙을 잃는다
  const made = state.results[p.card.card_id]?.chosen_measures;
  const picked = made ? new Set(made.map((x) => x.id)) : on;
  // 시험용 실행(mock)은 저장 예시 글을 그대로 보여 주므로 '공지에 반영'이라고 말하지 않는다
  const mock = state.health?.mode === "mock";
  return `<fieldset class="measures"><legend class="small">${RULES_TITLE}${mock ? "" : " (공지에 반영)"}</legend>
    ${m.options.map((o) => `<label class="small"><input type="checkbox" data-measure="${esc(p.card.card_id)}" value="${esc(o.id)}"${picked.has(o.id) ? " checked" : ""}> ${esc(o.text)}</label>`).join("")}
    ${mock ? '<p class="small muted">시험용 실행에서는 저장 예시 글이 그대로 나와요. 고른 수칙은 화면에만 표시돼요.</p>' : ""}
  </fieldset>`;
}

// 카드를 고르면: 이미 만든 글이 있으면 그 글로, 없으면 만들고 초안으로
async function choose(cardId, button) {
  if (state.results[cardId]) { state.current = cardId; state.draftId = null; go("draft"); return; }
  await runCard(cardId, button);
}
// 다시 만들 때 보내는 옛 글 id (replaces, 11/16): 서버는 새 글을 만든 뒤에만 이 방문자의 승인 기록에서 그 글들을 지운다.
// 서버(demo.REPLACES_MAX)와 같은 20개까지, 승인한 글부터 보낸다 (승인하지 않은 글은 지울 기록이 없어 서버가 0 으로 센다)
const REPLACES_MAX = 20;
const replacesOf = (ids) => [...ids.filter((id) => state.approved.has(id)), ...ids.filter((id) => !state.approved.has(id))].slice(0, REPLACES_MAX);
async function runCard(cardId, button) {
  const old = button ? button.textContent : "";
  if (button) { button.disabled = true; button.textContent = "만드는 중…"; }
  try {
    const boxes = [...document.querySelectorAll(`[data-measure="${CSS.escape(cardId)}"]`)];
    const picked = boxes.length ? JSON.stringify({ measures: boxes.filter((b) => b.checked).map((b) => b.value) }) : undefined;
    // 카드 전체 다시 만들기면 지금 글 id 를 replaces 로 더한다. 처음 만들 때는 예전과 같은 본문 (scripts/measure_live.py 가 따라 함)
    const before = (state.results[cardId]?.drafts || []).map((d) => d.draft_id);
    const body = before.length ? JSON.stringify({ ...JSON.parse(picked || "{}"), replaces: replacesOf(before) }) : picked;
    const result = await api(`/api/cards/${encodeURIComponent(cardId)}/run`, { method: "POST", body });
    if (result.replace_warning) showAlert(result.replace_warning);   // 새 글은 받았지만 서버의 옛 승인 기록은 못 지움
    // 다시 만들면 그 카드의 예전 글 승인·고친 내용은 버린다 (완료 화면의 승인 목록에서도 뺀다)
    const gone = new Set((state.results[cardId]?.drafts || []).map((d) => d.draft_id));
    gone.forEach((id) => { dropBox(id); state.approved.delete(id); delete state.pending[id]; });
    state.approvedLog = state.approvedLog.filter((x) => !gone.has(x.id));
    draftNote = null;
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
  // 홍보글: 상권 근거 지표와, 쿠폰 메뉴를 칭찬한 손님 리뷰를 둘 다 보여 준다 (칭찬 근거가 없는 카드는 지표만)
  const snaps = p.evidence.filter((e) => e.type === "snapshot");
  const praise = praiseOf(p);
  const praised = praise.shown.map((e) => state.reviews[e.id] || { text: e.text, rating: e.rating });
  return (snaps.length ? `<div class="rv"><p class="rv-title">근거 지표</p>${snaps.map((e) => `<p class="rv-text">${esc(e.text)}</p><div class="rv-meta"><span>${esc(shortBasis(e.basis))}</span></div>`).join("")}</div>` : "")
    + (praised.length ? `<div class="rv"><p class="rv-title">손님 칭찬 리뷰 · ${esc(praise.menu)} 언급 ${praise.total}건${praise.total > praised.length ? ` 중 ${praised.length}건` : ""}</p><ul class="rv-list">${praised.map(reviewItem).join("")}</ul></div>` : "");
}

function saveEdits() {
  // 다시 그리기 전에, 아직 승인하지 않은 글에서 고친 내용을 보존한다
  document.querySelectorAll("textarea[data-text]").forEach((box) => (state.pending[box.dataset.text] = box.value));
}
// 새 글로 바꿔 버린 글의 편집 칸이 아직 화면에 있으면, 다음 saveEdits 가 그 내용을 새 글에 다시 담지 않게 뗀다 (mock 은 새 글 id 가 예전과 같다)
const dropBox = (id) => document.querySelectorAll(`textarea[data-text="${CSS.escape(id)}"]`).forEach((box) => box.removeAttribute("data-text"));

// ── 다시 만들기 두 가지 (11/16) ─────────────────────────────────────
// 초안 상자의 '다시 만들기'(data-regen = 글 id)는 지금 보는 글 한 건만 새로 만든다: 같은 API 에 generator(+review_id)를 보낸다.
//   그 글의 승인·고친 내용만 지우고, 다른 글의 승인·고친 내용은 그대로 둔다.
// 진행줄 옆 '카드 전체 다시 만들기'(data-rerun = 카드 id)는 그 카드의 글을 모두 새로 만든다 (runCard). 승인했거나 고치는 중인 글이
//   있으면 한 번 더 눌러야 실행한다 (대화상자 대신, 서랍의 '대화 지우기'와 같은 방식).
const RERUN_LABEL = "카드 전체 다시 만들기";
const RERUN_ARM_MS = 5000;
const rerunArm = { card: null, timer: null };   // 한 번 눌러 둔 카드 (RERUN_ARM_MS 안에 한 번 더 누르면 실행)
const regenBusy = new Set();                    // 지금 다시 만드는 중인 글. 화면을 다시 그려도 '만드는 중…'으로 남는다
let draftNote = null;                           // 초안 상자 아래 한 줄 안내 { id: 글 id, text }
const regenKey = (cardId, d) => [cardId, d.generator, d.target_review_id || ""].join("|");
const sameSlot = (a, b) => a.generator === b.generator && (a.target_review_id || "") === (b.target_review_id || "");
const isEdited = (d) => state.pending[d.draft_id] != null && state.pending[d.draft_id] !== (d.edited_text ?? d.text);
const touchedOf = (cardId) => draftsOf(cardId).filter((d) => state.approved.has(d.draft_id) || isEdited(d)).length;

async function regenDraft(id) {
  const cardId = state.current, r = state.results[cardId];
  const p = state.cards.find((x) => x.card.card_id === cardId);
  const d = (r?.drafts || []).find((x) => x.draft_id === id);
  if (!p || !d) return;
  const key = regenKey(cardId, d);
  if (regenBusy.has(key)) return;
  const body = { generator: d.generator };
  if (d.target_review_id) body.review_id = d.target_review_id;
  body.replaces = [d.draft_id];   // 바뀌는 옛 글: 서버가 새 글을 만든 뒤에만 그 승인 기록을 지운다 (못 만들면 그대로)
  // 불만 카드: 처음 만들 때 고른 수칙을 그대로 보낸다. 공지는 지금 화면의 묶음 답글도 보낸다 (공지가 답글과 너무 비슷한지 서버가 견줌)
  if (p.card.kind === "complaint") body.measures = (r.chosen_measures || []).map((m) => m.id);
  if (d.generator === "prevention_notice") {
    const pasted = new Set(r.pasted_reply_review_ids || []);
    body.reply_texts = r.drafts.filter((x) => x.generator === "reply_draft" && !pasted.has(x.target_review_id)).map((x) => x.text);
  }
  regenBusy.add(key); draftNote = null;
  renderDraft();
  try {
    const made = await api(`/api/cards/${encodeURIComponent(cardId)}/run`, { method: "POST", body: JSON.stringify(body) });
    const fresh = (made.drafts || [])[0];
    if (!fresh) throw new Error("새 글을 받지 못했어요. 다시 눌러 주세요.");
    if (made.replace_warning) showAlert(made.replace_warning);   // 새 글은 받았지만 서버의 옛 승인 기록은 못 지움
    const at = state.results[cardId] === r ? r.drafts.findIndex((x) => sameSlot(x, d)) : -1;
    if (at < 0) return;   // 기다리는 동안 카드 전체를 다시 만들었거나 카드가 바뀌었다: 늦게 온 이 글은 버린다
    const gone = r.drafts[at].draft_id;
    // 바꾼 글의 승인·고친 내용만 지운다. 다른 글의 것은 건드리지 않는다
    dropBox(gone); state.approved.delete(gone); delete state.pending[gone];
    state.approvedLog = state.approvedLog.filter((x) => x.id !== gone);
    r.drafts[at] = fresh;
    r.flagged_count = r.drafts.filter((x) => failedOf(x).length || checksOf(x).length).length;
    if (state.draftId === gone) state.draftId = fresh.draft_id;
    draftNote = { id: fresh.draft_id, text: (made.source === "seed" ? "이 글만 다시 불러왔어요. 시험용 실행이라 저장 예시 글 그대로예요." : "이 글만 새로 만들었어요.")
      + " 다른 글의 승인과 고친 내용은 그대로예요." };
  } catch (e) { showAlert(e.message); }
  finally {
    regenBusy.delete(key);
    renderDash();
    if (currentRoute() === "draft") {
      // 다시 그려도 고치던 글 칸의 포커스·커서 자리는 지킨다 (기다리는 동안 다른 글을 고치고 있을 수 있다)
      const box = document.activeElement?.matches?.("textarea[data-text]") ? document.activeElement : null;
      const keep = box && { id: box.dataset.text, start: box.selectionStart, end: box.selectionEnd, top: box.scrollTop };
      renderDraft();
      const again = keep && document.querySelector(`textarea[data-text="${CSS.escape(keep.id)}"]`);
      if (again) { again.focus({ preventScroll: true }); again.setSelectionRange(keep.start, keep.end); again.scrollTop = keep.top; }
      else if (document.activeElement === document.body) $("draft").querySelector("[data-regen]")?.focus({ preventScroll: true });   // 버튼이 다시 그려져 잃은 포커스
    }
  }
}

function rerunDisarm() { clearTimeout(rerunArm.timer); rerunArm.card = null; rerunArm.timer = null; }
// 버튼 글자와 안내 한 줄만 지금 상태에 맞춘다. 화면을 통째로 다시 그리지 않는다 (글을 고치는 중일 수 있어서)
function rerunPaint() {
  const button = $("draft").querySelector("[data-rerun]"), note = $("draft").querySelector("[data-rerun-note]");
  if (!button || !note) return;
  const armed = rerunArm.card === button.dataset.rerun;
  button.textContent = armed ? "한 번 더 눌러 실행" : RERUN_LABEL;
  note.textContent = armed ? `한 번 더 누르면 이 카드의 글을 모두 다시 만들어요. 승인했거나 고친 글 ${touchedOf(rerunArm.card)}개도 새 글로 바뀌어요.` : "";
}
async function rerunCard(cardId, button) {
  saveEdits();
  if (touchedOf(cardId) && rerunArm.card !== cardId) {
    rerunDisarm();
    rerunArm.card = cardId;
    rerunArm.timer = setTimeout(() => { rerunDisarm(); rerunPaint(); }, RERUN_ARM_MS);
    rerunPaint();
    return;
  }
  rerunDisarm(); rerunPaint();
  await runCard(cardId, button);
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
  const busy = !!d && regenBusy.has(regenKey(state.current, d));   // 이 글을 다시 만드는 중

  const name = GEN_NAMES[d?.generator] || d?.generator || "";
  el.innerHTML = `
    <div class="page-head">
      <p class="eyebrow">${agent ? `<span class="agent">${esc(agent)}</span>` : ""}<span class="badge">${esc(srcLabel)}</span></p>
      <h1 tabindex="-1">${esc(p.title)}</h1>
    </div>
    ${made.length > 1 ? `<div class="seg" role="group" aria-label="카드">${made.map((q) => `<button type="button" data-card="${esc(q.card.card_id)}"${q.card.card_id === state.current ? ' aria-current="true"' : ""}>${state.cards.indexOf(q) === 0 ? "ⓐ" : "ⓑ"} ${esc(KIND_NAMES[q.card.kind] || q.card.kind)}</button>`).join("")}</div>` : ""}
    ${r.source_note ? `<p class="small muted">${esc(r.source_note)}</p>` : ""}
    ${(r.chosen_measures || []).length ? `<p class="small">${RULES_TITLE}: ${r.chosen_measures.map((m) => esc(m.text)).join(", ")} <span class="muted">· ${r.source === "seed" ? "시험용 저장 예시 글은 고른 수칙과 상관없이 그대로예요" : "공지에 반영"}</span></p>` : ""}
    <div class="progress"><span>승인 ${done} / ${drafts.length}</span><span class="track" aria-hidden="true"><i style="width:${drafts.length ? Math.round((done / drafts.length) * 100) : 0}%"></i></span>
      <button type="button" class="ghost" data-rerun="${esc(state.current)}">${RERUN_LABEL}</button></div>
    <p class="small muted draft-note" role="status" data-rerun-note></p>
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
        <textarea id="text-${esc(d.draft_id)}" rows="7" data-text="${esc(d.draft_id)}"${busy ? " readonly" : ""}>${esc(state.pending[d.draft_id] ?? d.edited_text ?? d.text)}</textarea>
        ${failed.length ? `<ul class="issues bad">${failed.map((x) => `<li><b>점검 실패</b> ${esc(x)}</li>`).join("")}</ul>` : ""}
        ${checks.length ? `<ul class="issues">${checks.map((x) => `<li><b>확인 필요</b> ${esc(x)}</li>`).join("")}</ul>` : ""}
      </div>
      <div class="row">
        <button type="button" class="primary" data-approve="${esc(d.draft_id)}"${busy ? " disabled" : ""}>${approved ? "다시 승인" : "승인"}</button>
        <button type="button" data-copy="${esc(d.draft_id)}">복사</button>
        <button type="button" class="ghost" data-regen="${esc(d.draft_id)}"${busy ? " disabled" : ""}>${busy ? "만드는 중…" : "다시 만들기"}</button>
      </div>
      <p class="small muted draft-note" role="status">${busy ? "이 글만 다시 만들고 있어요. 다른 글의 승인과 고친 내용은 그대로예요." : draftNote?.id === d.draft_id ? esc(draftNote.text) : ""}</p>
      <p class="small muted model">${esc(d.model || "")}${d.elapsed_ms ? " · " + (d.elapsed_ms / 1000).toFixed(1) + "초" : ""}</p>
    </article>` : '<div class="panel"><p class="muted">이 카드에서 만든 글이 없어요.</p></div>'}`;

  el.querySelectorAll("[data-card]").forEach((b) => b.addEventListener("click", () => { saveEdits(); draftNote = null; state.current = b.dataset.card; state.draftId = null; renderDraft(); }));
  el.querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", () => { saveEdits(); draftNote = null; state.draftId = b.dataset.pick; renderDraft(); }));
  el.querySelectorAll("[data-approve]").forEach((b) => b.addEventListener("click", () => approve(b.dataset.approve)));
  el.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", () => copyDraft(b.dataset.copy, b)));
  el.querySelectorAll("[data-regen]").forEach((b) => b.addEventListener("click", () => regenDraft(b.dataset.regen)));
  el.querySelectorAll("[data-rerun]").forEach((b) => b.addEventListener("click", () => rerunCard(b.dataset.rerun, b)));
  rerunPaint();
}

function findDraft(id) {
  for (const r of Object.values(state.results)) for (const d of r.drafts || []) if (d.draft_id === id) return d;
  return null;
}

// 승인하면 이 카드의 다음 미승인 글로, 다 끝나면 완료 화면으로
async function approve(id) {
  const d = findDraft(id); const box = document.querySelector(`[data-text="${CSS.escape(id)}"]`);
  try {
    // 리뷰 답글이면 어느 리뷰의 답글인지도 보낸다: 서버가 리뷰 분석 서비스에 '답글 달았음'을 기록 (응대 점수·기한). 서버가 아는 초안이면 서버 값이 먼저
    const hint = d.target_review_id ? { kind: d.generator, review_id: d.target_review_id } : {};
    const entry = await api(`/api/drafts/${encodeURIComponent(id)}/approve`, { method: "POST", body: JSON.stringify({ text: box.value, original: d.text, ...hint }) });
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
  // 맞춤 마케팅에서 승인한 글(mkt)은 비서 화면이 만든 글이 아니므로 승인한 만큼 '만든 글'에도 더한다
  const total = Object.values(state.results).flatMap((r) => r.drafts || []).length + log.filter((a) => a.mkt).length;
  // 불만 카드를 만들 때 사장님이 고른 수칙 (서버 응답의 chosen_measures). 글 승인과 함께 오늘부터 현장에서 할 일로 다시 보여 준다
  const care = state.cards.find((p) => p.card.kind === "complaint");
  const made = care ? state.results[care.card.card_id] : null;
  const rules = made?.chosen_measures || [];
  const noticeDone = (made?.drafts || []).some((d) => d.generator === "prevention_notice" && state.approved.has(d.draft_id));
  const rulesNote = made?.source === "seed" ? "시험용 저장 예시 글은 고른 수칙과 상관없이 그대로예요."
    : noticeDone ? "승인한 재발 방지 공지에 넣어 만든 수칙이에요." : "재발 방지 공지에 넣어 만든 수칙이에요. 공지는 아직 승인 전이에요.";
  el.innerHTML = `
    <div class="page-head"><h1 tabindex="-1">처리 완료</h1>
      <p class="muted">승인한 글 ${log.length}개 / 만든 글 ${total}개 · 게시는 복사해서 직접 올려요</p></div>
    <div class="panel">
      <div class="progress"><span>승인 ${log.length} / ${total}</span><span class="track" aria-hidden="true"><i style="width:${total ? Math.round((log.length / total) * 100) : 0}%"></i></span></div>
      <ul class="plain log">${log.map((a) => `<li><span class="badge ok">승인 완료</span> ${esc(a.name)} <span class="small muted">· ${esc(a.card)} · ${esc(String(a.at).slice(11, 19))}${a.edited ? " · 사장님이 고침" : ""}</span></li>`).join("")}</ul>
    </div>
    ${rules.length ? `<div class="panel done-rules"><h2>${RULES_TITLE}</h2>
      <ul>${rules.map((m) => `<li>${esc(m.text)}</li>`).join("")}</ul>
      <p class="small muted">사장님이 카드에서 고른 수칙 ${rules.length}가지예요. ${rulesNote}</p></div>` : ""}
    <div class="row done-actions">
      <button type="button" class="primary big" data-home>홈으로</button>
      <button type="button" class="ghost" id="restart">처음부터 다시</button>
    </div>
    <p class="small muted done-hint">‘홈으로’는 만든 글과 승인 표시를 그대로 둬요. ‘처음부터 다시’는 만든 글과 승인 기록(맞춤 마케팅 포함)을 모두 지워요.</p>
    <details class="more"><summary class="small">서버 처리 기록</summary><ul id="approvals" class="plain small"></ul></details>`;
  el.querySelector("[data-home]").addEventListener("click", () => go("today"));
  $("restart").addEventListener("click", (e) => restart(e.currentTarget));
  loadApprovals().catch(() => {});
}

async function loadApprovals() {
  const data = await api("/api/approvals");
  const ul = $("approvals");
  // 맞춤 마케팅에서 승인한 글은 글 id 가 mkt- 로 시작한다 (marketing_proxy.py)
  if (ul) ul.innerHTML = data.items.map((a) => `<li>${esc(a.approved_at.slice(11, 19))} · ${String(a.draft_id).startsWith("mkt-") ? "맞춤 마케팅 · " : ""}${esc(a.draft_id)} 승인${a.edited ? " (사장님이 고침)" : ""}</li>`).join("") || "<li>기록 없음</li>";
}

// 처음부터 다시: 이 브라우저의 진행(만든 글·승인 표시·고친 내용)을 비우고, 서버에 남은 이 방문자의 승인 기록도 지운다 (DELETE /api/approvals).
// 서버는 이 방문자의 맞춤 마케팅 기록도 같이 지우고(marketing_cleared), 화면은 맞춤 마케팅의 대화·결과 카드·보고서도 처음으로 돌린다 (mktReset).
// 다시 카드 → 승인 → 완료로 왔을 때 예전 승인이 '서버 처리 기록'에 남아 있지 않게 한다. 서버가 못 지워도 화면은 비우고 알림 띠로 알린다.
// (진행을 그대로 두고 대시보드로 가는 것은 주 버튼 '홈으로')
async function restart(button) {
  if (button) { button.disabled = true; button.textContent = "지우는 중…"; }
  let failed = "", cleared = null;
  try { const r = await api("/api/approvals", { method: "DELETE" }); cleared = r.marketing_cleared ?? null; }
  catch (e) { failed = e.message; }
  rerunDisarm(); regenBusy.clear(); draftNote = null;
  state.results = {}; state.approved.clear(); state.approvedLog = []; state.pending = {};
  state.current = null; state.draftId = null;
  $("draft").replaceChildren();   // 숨은 초안 화면에 남은 편집 칸도 치운다 (다음에 그릴 때 saveEdits 가 예전 글을 다시 담지 않게)
  mktReset(failed ? null : cleared);   // 맞춤 마케팅 화면도 처음으로 (마케팅 기록을 못 지웠으면 그 화면 안에만 안내)
  renderCards({ cards: state.cards, no_card_b: $("no-card-b").textContent });
  go("today");
  if (failed) showAlert(`화면은 처음으로 돌렸지만 서버의 승인 기록은 지우지 못했어요. ${failed}`);
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

// ── 고객응대 호출: 캡처로 넣기 · 종합 리포트 (11/15) ─────────────────────
// 이 서버의 /api/care/*(리뷰 분석 서비스의 고객응대 API 를 서버가 대신 부름), 캡처 후보 저장용 /api/reviews, 승인 기록 /api/approvals 만 부른다.
// 호출은 careApi 로만 한다: 전역 api()·showAlert(#alert)를 쓰지 않아서 오류는 그 칸(캡처 칸, 리포트의 각 칸) 안에만 보이고 화면의 다른 곳은 그대로.
// 서버 글은 esc() 를 거쳐서만 넣는다.
const CARE_WAIT_MS = 20000;
const CAP_WAIT_MS = 110000;   // 캡처: 긴 캡처는 최대 5조각으로 나눠 조각마다 HCX 를 부른다 (보통 5~20초). 서버는 100초까지 기다림
const CAP_MAX_BYTES = 10 * 1024 * 1024;
const CAP_TYPES = ["image/png", "image/jpeg", "image/webp"];
const SOURCE_KO = { sample: "합성 리뷰", paste: "붙여넣기", capture: "캡처", app: "가상 배달앱", memo: "매장 메모" };

async function careApi(path, options = {}, waitMs = CARE_WAIT_MS) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), waitMs);
  const fail = (message, st, status) => Object.assign(new Error(message), { state: st, status });
  const headers = { Accept: "application/json" };
  if (typeof options.body === "string") headers["Content-Type"] = "application/json";   // FormData(캡처)는 브라우저가 경계값을 붙인다
  try {
    const res = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options, headers, signal: ctl.signal });
    const body = await res.json().catch(() => null);
    if (res.ok && body) return body;
    if (body?.error?.message) throw fail(body.error.message, body.error.state || "error", res.status);
    if (res.status === 413) throw fail("파일이 너무 커요. 10MB 이하 이미지를 올려 주세요.", "too_big", 413);   // Nginx 가 막으면 HTML 로 옴
    if (res.status === 422) throw fail("보내는 내용을 다시 확인해 주세요.", "invalid", 422);
    if (res.status === 404) throw fail("이 서버에는 아직 고객응대 기능이 연결되지 않았어요.", "off", 404);
    throw fail(res.ok ? "응답을 읽지 못했어요. 잠시 뒤 다시 해 주세요." : `고객응대 기능이 응답하지 않았어요 (${res.status}). 잠시 뒤 다시 해 주세요.`, "error", res.status);
  } catch (e) {
    if (e.name === "AbortError") throw fail("응답이 너무 늦어요. 잠시 뒤 다시 해 주세요.", "timeout", 0);
    if (e instanceof TypeError) throw fail("서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.", "down", 0);
    throw e;
  } finally { clearTimeout(timer); }
}

// ── 캡처로 넣기 (리뷰 붙여넣기 탭) ───────────────────────────────────
// 파일 고르기(또는 끌어 놓기) → POST /api/care/reviews/capture (저장하지 않고 후보만) → 후보마다 글 고치기·별점·개인정보 가림·이미 있는 리뷰 표시
// → '선택한 리뷰 저장'이 고른 후보를 한 건씩 POST /api/reviews {text, rating, source: "capture"} 로 저장 (붙여넣기와 같은 길) → 홈·카드·분석 다시 불러오기.
// demo(예시 결과)와 warnings 는 받은 그대로 꼭 보이고, 별점은 잘못 읽을 수 있다는 안내가 늘 붙는다 (실시간 시험에서 1~2점을 3점으로 읽은 적이 절반쯤).
const cap = { file: null, url: null, busy: false, tick: null };
const CAP_RATINGS = [["", "별점 모름"], ["5", "별점 5"], ["4", "별점 4"], ["3", "별점 3"], ["2", "별점 2"], ["1", "별점 1"]];
function capErr(msg) { $("cap-error").textContent = msg || ""; }
function capPick(file) {
  capErr("");
  if (!file) return;
  if (file.type && !CAP_TYPES.includes(file.type)) { capErr("png·jpg·webp 이미지만 올릴 수 있어요."); return; }
  if (file.size > CAP_MAX_BYTES) { capErr("이미지는 10MB 이하로 올려 주세요."); return; }
  cap.file = file;
  const size = file.size >= 1048576 ? `${(file.size / 1048576).toFixed(1)}MB` : `${Math.max(1, Math.round(file.size / 1024))}KB`;
  $("cap-file-name").textContent = `${file.name || "캡처"} · ${size}`;
  $("cap-send").disabled = cap.busy;
}
// 진행 표시 (#cap-status, role=status): 깜박이는 점 + 글 + 걸린 초 (초는 읽기 프로그램에 읽히지 않게)
function capBusy(on) {
  cap.busy = on;
  $("cap-send").disabled = on || !cap.file;
  $("cap-choose").disabled = on;
  $("cap-save").disabled = on || !capPicked().length;
  clearInterval(cap.tick);
  const el = $("cap-status");
  el.classList.toggle("busy", on);
  el.replaceChildren();
  if (!on) return;
  const msg = mk("span", "", "캡처를 읽고 있어요");
  const sec = mk("span", "cap-sec");
  sec.setAttribute("aria-hidden", "true");
  el.append(msg, sec);
  const t0 = Date.now();
  cap.tick = setInterval(() => {
    const s = Math.floor((Date.now() - t0) / 1000);
    sec.textContent = s >= 2 ? `${s}초` : "";
    if (s === 6) msg.textContent = "캡처를 읽고 있어요. 긴 캡처는 최대 5조각으로 나눠 읽어서 20초쯤 걸릴 수 있어요";
  }, 1000);
}
async function capRead() {
  if (!cap.file || cap.busy) return;
  capErr("");
  $("cap-save-msg").textContent = "";
  $("cap-result").hidden = true;          // 앞 캡처의 후보는 치운다 (새 캡처가 실패했을 때 옛 후보를 새 것으로 착각하지 않게)
  $("cap-list").replaceChildren();
  capBusy(true);
  const form = new FormData();
  form.append("file", cap.file, cap.file.name || "capture.png");
  try {
    const r = await careApi("/api/care/reviews/capture", { method: "POST", body: form }, CAP_WAIT_MS);
    capBusy(false);
    capRender(r);
  } catch (e) {
    capBusy(false);
    capErr(e.message);   // 400·413·422·502·503 모두 서버(리뷰 분석 서비스·프록시) 문장 그대로
  }
}
function capItem(c, i) {
  const n = i + 1;
  return `<li class="cap-item${c.duplicate ? " dup" : ""}">
    <div class="cap-item-head">
      <label class="cap-check"><input type="checkbox" data-cap-pick="${i}"${c.duplicate ? "" : " checked"}> 후보 ${n} 저장</label>
      ${c.pii_masked ? '<span class="badge" title="전화번호·이메일·링크를 [가림]으로 바꿨어요">개인정보 가림</span>' : ""}
      ${c.duplicate ? '<span class="badge warn" title="이미 저장된 리뷰와 글이 같아서 처음에는 고르지 않았어요">이미 있는 리뷰</span>' : ""}
      <span class="badge ok cap-saved" hidden>저장함</span>
    </div>
    <label class="sr" for="cap-text-${i}">후보 ${n} 리뷰 글</label>
    <textarea id="cap-text-${i}" data-cap-text="${i}" rows="3" maxlength="1000">${esc(c.text)}</textarea>
    <div class="cap-item-foot">
      <label class="small" for="cap-rate-${i}">별점</label>
      <select id="cap-rate-${i}" data-cap-rate="${i}">${CAP_RATINGS.map(([v, t]) => `<option value="${v}"${String(c.rating ?? "") === v ? " selected" : ""}>${t}</option>`).join("")}</select>
      <span class="small muted">AI가 읽은 별점: ${Number.isInteger(c.rating) ? `${esc(c.rating)}점` : "못 읽음"}</span>
    </div>
    <p class="cap-item-msg" data-cap-msg="${i}"></p>
  </li>`;
}
function capRender(r) {
  const list = (Array.isArray(r?.candidates) ? r.candidates : []).filter((c) => c && typeof c.text === "string")
    .map((c) => ({ text: c.text, rating: Number.isInteger(c.rating) && c.rating >= 1 && c.rating <= 5 ? c.rating : null,
      pii_masked: !!c.pii_masked, duplicate: !!c.duplicate }));
  const warns = (Array.isArray(r?.warnings) ? r.warnings : []).filter((w) => typeof w === "string" && w.trim());
  $("cap-result").hidden = false;
  $("cap-demo").hidden = r?.demo !== true;
  $("cap-warnings").innerHTML = warns.map((w) => `<li>${esc(w)}</li>`).join("");
  $("cap-warnings").hidden = !warns.length;
  if (cap.url) URL.revokeObjectURL(cap.url);
  cap.url = URL.createObjectURL(cap.file);
  $("cap-preview").src = cap.url;
  $("cap-list").innerHTML = list.map(capItem).join("") || '<li class="small muted">옮겨 적은 리뷰가 없어요. 다시 올리거나 붙여넣기를 써 주세요.</li>';
  capCount();
  const pieces = Number(r?.pieces) > 1 ? ` · ${Number(r.pieces)}조각으로 나눠 읽음` : "";
  $("cap-status").textContent = `후보 ${list.length}건${pieces} · ${r?.demo ? "예시 결과" : `읽은 모델 ${r?.engine || ""}`}. 글과 별점을 고치고, 저장할 리뷰를 골라 주세요.`;
}
const capPicked = () => [...document.querySelectorAll("#cap-list [data-cap-pick]")].filter((b) => b.checked && !b.disabled);
function capCount() {
  const n = capPicked().length;
  $("cap-picked").textContent = n ? `${n}건 고름` : "고른 리뷰 없음";
  $("cap-save").disabled = cap.busy || !n;
}
async function capSave() {
  const picks = capPicked();
  if (cap.busy) return;
  if (!picks.length) { $("cap-save-msg").textContent = "저장할 리뷰를 골라 주세요."; return; }
  cap.busy = true;
  ["cap-save", "cap-send", "cap-choose"].forEach((id) => ($(id).disabled = true));
  let ok = 0, bad = 0;
  const joined = new Set();
  for (const [k, box] of picks.entries()) {
    const li = box.closest(".cap-item");
    const text = li.querySelector("[data-cap-text]").value.trim();
    const rating = li.querySelector("[data-cap-rate]").value;
    const msg = li.querySelector("[data-cap-msg]");
    $("cap-save-msg").textContent = `저장하는 중… (${k + 1} / ${picks.length})`;
    if (!text) { msg.textContent = "글이 비어 있어 저장하지 않았어요."; bad++; continue; }
    try {
      const r = await careApi("/api/reviews", { method: "POST", body: JSON.stringify({ text, rating: rating ? Number(rating) : null, source: "capture" }) });
      (r.joined_issues || []).forEach((id) => joined.add(id));
      msg.textContent = "";
      li.classList.add("saved");
      li.querySelector(".cap-saved").hidden = false;
      box.checked = false; box.disabled = true;
      li.querySelectorAll("textarea, select").forEach((x) => (x.disabled = true));
      ok++;
    } catch (e) { msg.textContent = `저장하지 못했어요: ${e.message}`; bad++; }
  }
  const tail = bad ? ` ${bad}건은 저장하지 못했어요 (후보 아래 이유).` : "";
  if (ok) {
    state.joined = [...joined];
    $("cap-save-msg").textContent = `${ok}건 저장했어요. 홈 숫자와 추천 카드도 다시 불러와요…`;
    try {
      await refresh();   // 붙여넣기와 같이 홈 숫자 · 추천 카드 · 리뷰 분석(요약·묶음)을 모두 새로
      $("cap-save-msg").textContent = `${ok}건 저장했어요. 요약·불만 묶음·홈 숫자·추천 카드에 반영했어요.${tail}`;
    } catch (e) { $("cap-save-msg").textContent = `${ok}건 저장했어요. 다만 화면을 다시 불러오지 못했어요: ${e.message}${tail}`; }
  } else $("cap-save-msg").textContent = `저장하지 못했어요.${tail}`;
  cap.busy = false;
  $("cap-choose").disabled = false;
  $("cap-send").disabled = !cap.file;
  capCount();
}

// ── 종합 리포트 (#/report) ────────────────────────────────────────────
// 칸 여섯 개를 따로 그린다: 오늘 요약(/api/care/report/daily) · 응대 점수(/api/care/response) · 손님 칭찬 요약 · 월간 보고서(/api/care/report/monthly)
// · 상권 요약 · 마케팅 요약. 상권·마케팅은 처음 화면을 열 때 이미 받은 브리핑·추천 카드(state)와 /api/approvals 로만 만든다.
// 손님 칭찬 요약은 월간 보고서 응답의 praise 칸으로 그린다 (요청을 더하지 않음). '전체 리포트 PDF 저장'은 이 여섯 칸을 브라우저 인쇄로 내보낸다.
// 이 화면을 열어도 AI(HCX)를 새로 부르지 않는다 (/api/cards·/api/briefing·글 만들기·서랍을 부르지 않음). 한 칸이 실패해도 다른 칸은 그대로.
// 남은 시간: 서버의 due_at 으로 1초마다 센다 (서버와 브라우저 시계 차이는 응답의 remaining_seconds 로 맞춤). 피크 중이면 '멈춤'.
const rp = { month: null, maxMonth: null, loading: null, loadedAt: 0, clocks: [], peak: false, tick: null, poll: null,
  day: null, until: null, trend: null, mktBusy: 0 };   // day·until: 인쇄 머리글의 기간 · trend: 인쇄 폭으로 다시 그릴 점수 추이 · mktBusy: 마케팅 요약을 불러오는 중인 수
const RP_STATE = { daily: "rp-daily-state", score: "rp-score-state", praise: "rp-praise-state", month: "rp-month-state", market: "rp-market-state", mkt: "rp-mkt-state" };
const RP_ISSUE_STATE = { recurred_after_reply: "답글 뒤 재발", no_recurrence: "답글 뒤 7일 재발 없음", replied_watching: "답글 달고 지켜보는 중", no_reply: "답글 없음" };
const signed = (n) => (Number(n) > 0 ? `+${n}` : String(n ?? 0));
const rpDelta = (n) => `<span class="rp-delta ${Number(n) < 0 ? "neg" : Number(n) > 0 ? "pos" : ""}">${esc(signed(n))}</span>`;
const rpReasons = (list, empty) => `<ul class="plain rp-reasons">${(Array.isArray(list) ? list : []).map((x) => `<li>${rpDelta(x.delta)}<span>${esc(x.message)}</span></li>`).join("")
  || `<li class="small muted">${esc(empty)}</li>`}</ul>`;
const monthKo = (m) => { const [y, mo] = String(m || "").split("-"); return y && mo ? `${y}년 ${Number(mo)}월` : "이번 달"; };
const shiftMonth = (m, d) => { const [y, mo] = m.split("-").map(Number); const t = new Date(Date.UTC(y, mo - 1 + d, 1)); return `${t.getUTCFullYear()}-${String(t.getUTCMonth() + 1).padStart(2, "0")}`; };
const dateKo = (d) => { const m = String(d || "").match(/^\d{4}-(\d{2})-(\d{2})/); return m ? `${Number(m[1])}/${Number(m[2])}` : String(d || ""); };
const clip = (t, n) => { const s = String(t || ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
const peakText = (p) => (Array.isArray(p?.peak_hours) ? p.peak_hours : []).map((h) => String(h).replace("-", "~") + "시").join(", ");

function rpState(name, msg, bad = false) {
  const el = $(RP_STATE[name]);
  el.hidden = !msg;
  el.textContent = msg || "";
  el.classList.toggle("bad", bad);
}
function rpStop() { clearInterval(rp.tick); clearInterval(rp.poll); rp.tick = rp.poll = null; rpMark(); }
// 남은 시간 1초 시계 + 1분마다 점수 다시 부르기 (화면을 보고 있을 때만). restart 면 새로 맞춘다
function rpTimers(restart = false) {
  if (restart) rpStop();
  if (!rp.tick) rp.tick = setInterval(rpTick, 1000);
  if (!rp.poll) rp.poll = setInterval(() => { if (!document.hidden && currentRoute() === "report") rpScore(true); }, 60000);
}
// force: '다시 불러오기'. 처음 열 때 route() 가 두 번 불려도(시작 직후·브리핑을 받은 뒤) 고객응대 칸은 한 번만 부른다
function loadReport(force = false) {
  rpMark();
  rpMarket();
  rp.mktBusy += 1;
  rpMarketing().finally(() => { rp.mktBusy -= 1; });
  if (rp.loading) return rp.loading;
  if (!force && Date.now() - rp.loadedAt < 3000) { rpTimers(); return Promise.resolve(); }   // 방금 불렀으면 시계만 다시 돌린다
  rp.loading = Promise.all([rpDaily(), rpScore(), rpMonth(rp.month)]).finally(() => { rp.loading = null; rp.loadedAt = Date.now(); });
  return rp.loading;
}

async function rpDaily() {
  rpState("daily", "불러오는 중…");
  try {
    const d = await careApi("/api/care/report/daily");
    const src = Object.entries(d.by_source || {}).map(([k, n]) => `${SOURCE_KO[k] || k} ${n}`).join(" · ");
    rp.day = d.date || null;
    $("rp-daily-date").textContent = d.date ? `${d.date}${d.until ? ` · ${String(d.until).slice(11, 16)}까지` : ""}` : "";
    $("rp-daily").innerHTML = `
      <p class="rp-summary">${esc(d.summary)}</p>
      <dl class="rp-nums">
        <div><dt>리뷰</dt><dd>${esc(d.review_count ?? 0)}건</dd></div>
        <div><dt>불만</dt><dd>${esc(d.complaint_count ?? 0)}건</dd></div>
        <div><dt>기한 안 답글</dt><dd>${esc(d.replied_on_time ?? 0)}건</dd></div>
        <div><dt>늦은 답글</dt><dd>${esc(d.replied_late ?? 0)}건</dd></div>
      </dl>
      <p class="rp-line">응대 점수 <b>${esc(d.score_start)} → ${esc(d.score_end)}</b> ${rpDelta(d.score_change ?? (d.score_end - d.score_start))}</p>
      ${rpReasons(d.changes, "오늘은 점수가 바뀐 일이 없어요.")}
      <div class="rp-todo"><span class="rp-todo-label">내일 먼저 할 일</span><strong>${esc(d.todo?.text || "밀린 응대가 없어요")}</strong></div>
      <p class="small muted">${src ? `들어온 곳: ${esc(src)} · ` : ""}답글 기다림 ${esc(d.pending_count ?? 0)}건${d.overdue_count ? ` (기한 넘김 ${esc(d.overdue_count)}건)` : ""}</p>
      <p class="small muted">합성 리뷰는 지난 날짜(시나리오 기간)라서, 오늘 숫자에는 오늘 붙여넣기·캡처로 넣은 리뷰만 들어가요. 문장은 정해 둔 틀에 숫자만 넣었어요.</p>`;
    rpState("daily", "");
  } catch (e) { $("rp-daily").innerHTML = ""; $("rp-daily-date").textContent = ""; rpState("daily", e.message, true); }
}

const rpClock = (sec) => {
  const s = Math.max(0, Math.round(sec)), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h}시간 ${m}분` : `${m}:${String(s % 60).padStart(2, "0")}`;
};
function rpTick() {
  document.querySelectorAll("#rp-score [data-clock]").forEach((el) => {
    const c = rp.clocks[Number(el.dataset.clock)];
    if (!c) return;
    if (c.paused) { el.textContent = `멈춤 · ${rpClock(c.rem)} 남음`; el.className = "rp-clock paused"; return; }
    const left = Number.isFinite(c.due) ? (c.due - Date.now()) / 1000 : c.rem;
    el.textContent = left >= 0 ? `${rpClock(left)} 남음` : `기한 ${rpClock(-left)} 지남`;
    el.className = "rp-clock" + (left < 0 ? " over" : left < 300 ? " soon" : "");
  });
}
async function rpScore(quiet = false) {
  if (!quiet) rpState("score", "불러오는 중…");
  try {
    const r = await careApi("/api/care/response");
    const fetched = Date.now();
    const pending = Array.isArray(r.pending) ? r.pending : [];
    const peaks = peakText(r.policy);
    rp.peak = r.peak_now === true;
    rp.clocks = pending.map((p) => {
      const rem = Number(p.remaining_seconds), due = Date.parse(p.due_at);
      const skew = Number.isFinite(rem) && Number.isFinite(due) ? due - (fetched + rem * 1000) : 0;   // 서버 시계 - 브라우저 시계
      return { due: due - skew, rem, paused: p.paused === true || (rp.peak && rem > 0) };
    });
    $("rp-score").innerHTML = `
      <div class="rp-score-top">
        <p class="rp-big"><span class="rp-big-n">${esc(r.score)}</span><span class="rp-big-unit">/ 100점</span></p>
        ${rpReasons(r.reasons, "점수를 깎거나 올린 일이 없어요.")}
      </div>
      ${rp.peak ? `<p class="rp-peak">지금은 피크 시간이라 답글 기한이 멈춰 있어요${peaks ? ` (${esc(peaks)})` : ""}.</p>` : ""}
      <h3 class="rp-h3">답글을 기다리는 불만 ${esc(pending.length)}건${r.overdue_count ? ` · 기한 넘김 ${esc(r.overdue_count)}건` : ""}</h3>
      <ul class="plain rp-pending">${pending.map((p, i) => `
        <li class="rp-p${p.overdue ? " over" : ""}">
          <div class="rp-p-main"><p class="rp-p-text">“${esc(clip(p.text, 90))}”</p>
            <p class="small muted">${esc((p.topic_names || []).join("·") || "불만")} · ${esc(SOURCE_KO[p.source] || p.source || "")}${Number(p.penalty) < 0 ? ` · 감점 ${esc(p.penalty)}점` : ""}</p></div>
          <span class="rp-clock" data-clock="${i}"></span>
        </li>`).join("") || '<li class="small muted">지금 답글을 기다리는 불만이 없어요.</li>'}</ul>
      <p class="rp-untimed">지난 불만 <b>${esc(r.untimed_unanswered ?? 0)}건</b> <span class="small muted">· 기한 없이 답글을 안 단 지난(합성) 불만 리뷰</span></p>
      <p class="small muted">기한은 불만 리뷰를 받은 뒤 ${esc(r.policy?.sla_minutes ?? 30)}분${peaks ? `, 피크(${esc(peaks)}) 중에는 멈춤` : ""}. 답글을 승인하면 기록돼요. 점수 이유는 서버 문장 그대로예요.</p>`;
    rpState("score", "");
    rpTick();
    rpTimers(true);
  } catch (e) {
    if (quiet) return;     // 1분마다 다시 부르다 실패하면 보이던 값을 그대로 둔다
    $("rp-score").innerHTML = "";
    rp.clocks = [];
    rpState("score", e.message, true);
  }
}

// 날마다 점수 선 그래프 (외부 라이브러리 없이 SVG). 색은 CSS(.rp-line 등)가 정해 라이트·다크를 따른다
function rpTrend(trend, width, height) {
  const pts = (Array.isArray(trend) ? trend : []).filter((t) => Number.isFinite(Number(t?.score)));
  if (!pts.length) return '<p class="small muted">점수 기록이 없어요.</p>';
  // 그림 폭 = 칸의 실제 폭 (좁은 화면에서 글자가 같이 줄어들어 안 보이지 않게). 칸이 숨어 있으면 600. width 를 주면 그 폭 (인쇄할 때 종이 폭)
  // height 를 주면 그 높이 (인쇄: 두 쪽 안에 들게 낮춘다, RP_PRINT_H)
  const W = Math.round(Math.min(860, Math.max(280, width || $("rp-month").clientWidth || 600))), H = height || 170, L = 36, R = 16, T = 18, B = 26;
  const v = pts.map((t) => Number(t.score));
  const lo = Math.min(80, ...v), last = v.length - 1;
  const x = (i) => L + (W - L - R) * (pts.length === 1 ? 0.5 : i / last);
  const y = (s) => T + ((H - T - B) * (100 - s)) / Math.max(1, 100 - lo);
  const label = `날마다 응대 점수: ${dateKo(pts[0].date)} ${v[0]}점에서 ${dateKo(pts[last].date)} ${v[last]}점, 가장 낮은 날 ${Math.min(...v)}점`;
  return `<svg class="rp-trend" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">
    <line class="rp-gl" x1="${L}" x2="${W - R}" y1="${y(100)}" y2="${y(100)}"/>
    <line class="rp-gl" x1="${L}" x2="${W - R}" y1="${y(lo).toFixed(1)}" y2="${y(lo).toFixed(1)}"/>
    <text class="rp-ax" x="${L - 8}" y="${y(100) + 4}" text-anchor="end">100</text>
    <text class="rp-ax" x="${L - 8}" y="${(y(lo) + 4).toFixed(1)}" text-anchor="end">${esc(lo)}</text>
    <polyline class="rp-line" points="${pts.map((t, i) => `${x(i).toFixed(1)},${y(v[i]).toFixed(1)}`).join(" ")}"/>
    ${pts.map((t, i) => `<circle class="rp-pt" cx="${x(i).toFixed(1)}" cy="${y(v[i]).toFixed(1)}" r="${i === last ? 4.5 : 2.5}"/>`).join("")}
    <text class="rp-ax rp-now" x="${x(last).toFixed(1)}" y="${(y(v[last]) - 10).toFixed(1)}" text-anchor="${pts.length === 1 ? "middle" : "end"}">${esc(v[last])}점</text>
    <text class="rp-ax" x="${L}" y="${H - 6}">${esc(dateKo(pts[0].date))}</text>
    <text class="rp-ax" x="${W - R}" y="${H - 6}" text-anchor="end">${esc(dateKo(pts[last].date))}</text>
  </svg>`;
}
async function rpMonth(month) {
  rpState("month", "불러오는 중…");
  rpState("praise", "불러오는 중…");
  try {
    const m = await careApi("/api/care/report/monthly" + (month ? `?month=${encodeURIComponent(month)}` : ""));
    rp.month = m.month;
    rp.until = m.until || null;
    rp.trend = m.score_trend;
    rpPraise(m);
    if (!month || !rp.maxMonth) rp.maxMonth = rp.maxMonth && rp.maxMonth > m.month ? rp.maxMonth : m.month;   // 달 없이 부른 값 = 서버의 이번 달
    const issues = Array.isArray(m.repeated_issues) ? m.repeated_issues : [];
    $("rp-month").innerHTML = `
      <dl class="rp-nums">
        <div><dt>리뷰</dt><dd>${esc(m.review_count ?? 0)}건</dd></div>
        <div><dt>불만</dt><dd>${esc(m.complaint_count ?? 0)}건</dd></div>
        <div><dt>응대 점수</dt><dd>${esc(m.score_start)} → ${esc(m.score_end)} ${rpDelta(m.score_change)}</dd></div>
        <div><dt>기한 넘긴 답글</dt><dd>${esc(m.late_count ?? 0)}건</dd></div>
      </dl>
      <figure class="rp-chart">${rpTrend(m.score_trend)}<figcaption class="small muted">날마다 응대 점수 (그날 끝 기준${m.until ? ` · ${esc(String(m.until).slice(0, 10))}까지` : ""})</figcaption></figure>
      <h3 class="rp-h3">반복 불만과 재발 여부</h3>
      <div class="rp-table-wrap"><table class="rp-table">
        <thead><tr><th scope="col">불만</th><th scope="col" class="num">전체</th><th scope="col" class="num">이번 달</th><th scope="col" class="num">답글</th><th scope="col" class="num">답글 뒤 재발</th><th scope="col">상태</th><th scope="col">많은 시간대</th></tr></thead>
        <tbody>${issues.map((i) => `<tr><th scope="row">${esc(i.topic_name)}${i.is_repeated ? ' <span class="badge rep">반복</span>' : ""}</th>
          <td class="num">${esc(i.review_count)}</td><td class="num">${esc(i.count_this_month)}</td><td class="num">${esc(i.replied_count)}</td>
          <td class="num">${esc(i.recurred_after_reply)}</td><td>${esc(RP_ISSUE_STATE[i.state] || i.state)}</td><td>${esc(i.main_time_band || "–")}</td></tr>`).join("")
          || '<tr><td colspan="7" class="muted">이 달에 묶인 불만이 없어요.</td></tr>'}</tbody>
      </table></div>
      <h3 class="rp-h3">다음 달 개선 제안</h3>
      <ol class="rp-sugg">${(Array.isArray(m.suggestions) ? m.suggestions : []).map((s) => `<li>${esc(s.text)}</li>`).join("") || '<li class="muted">제안이 없어요.</li>'}</ol>
      ${(m.changes || []).length ? `<details class="more"><summary class="small">이 달에 점수가 바뀐 이유 ${esc(m.changes.length)}개</summary>${rpReasons(m.changes, "")}</details>` : ""}
      <p class="small muted">숫자는 코드가 계산하고, 제안은 정해 둔 틀에 숫자만 넣었어요 (AI 문장 아님). 원인을 단정하지 않으니 매장에서 확인해 주세요.</p>`;
    rpState("month", "");
  } catch (e) {
    if (month) rp.month = month;
    rp.until = rp.trend = null;
    $("rp-month").innerHTML = "";
    rpState("month", e.message, true);
    rpPraise(null, e.message);
  } finally {
    $("rp-month-label").textContent = monthKo(rp.month);
    $("rp-print").href = "/api/care/report/monthly/print" + (rp.month ? `?month=${encodeURIComponent(rp.month)}` : "");
    $("rp-month-prev").disabled = !rp.month || (rp.maxMonth && rp.month <= shiftMonth(rp.maxMonth, -11));   // 1년 전까지
    $("rp-month-next").disabled = !rp.month || !rp.maxMonth || rp.month >= rp.maxMonth;
  }
}
async function rpMoveMonth(step, button) {
  if (!rp.month) return;
  await rpMonth(shiftMonth(rp.month, step));
  if (button.disabled && document.activeElement === button) $(step < 0 ? "rp-month-next" : "rp-month-prev").focus();   // 끝에 닿아 막힌 버튼의 포커스를 옆으로
}
// 손님 칭찬 요약 (11/16): 월간 보고서 응답의 praise 칸으로만 그린다 (요청을 더하지 않음). 집계 기간 = 월간 보고서에서 고른 달.
// 숫자·주제·메뉴·대표 한 줄은 리뷰 분석 서비스가 코드로 센 값 그대로다 (모델 호출 없음). 대표 한 줄은 서비스가 개인정보를 가린 글만 보낸다.
function rpPraise(m, error) {
  const p = m?.praise;
  $("rp-praise-period").textContent = m ? `${monthKo(m.month)}${m.until ? ` · ${dateKo(m.until)}까지` : ""}` : "";
  if (!p) {
    $("rp-praise").innerHTML = "";
    rpState("praise", error || "이 서버의 리뷰 분석 서비스는 아직 손님 칭찬 요약을 보내지 않아요.", !!error);
    return;
  }
  const topics = Array.isArray(p.top_topics) ? p.top_topics : [], menus = Array.isArray(p.top_menus) ? p.top_menus : [];
  $("rp-praise").innerHTML = `
    <div class="rp-praise-body">
      <div>
        <dl class="rp-nums">
          <div><dt>별점 4~5점</dt><dd>${esc(p.high_rating_count ?? 0)}건</dd></div>
          <div><dt>긍정 리뷰</dt><dd>${esc(p.positive_count ?? 0)}건</dd></div>
        </dl>
        <h3 class="rp-h3">칭찬 주제 상위</h3>
        <ul class="plain rp-praise-topics">${topics.map((t) => `<li class="kw-chip pos">${esc(t.topic_name)} <b>${esc(t.count)}</b></li>`).join("")
          || '<li class="small muted">칭찬으로 분류된 주제가 아직 없어요.</li>'}</ul>
      </div>
      <div>
        <h3 class="rp-h3">인기 메뉴 TOP 3 <span class="small muted">· 칭찬 리뷰에 이름이 나온 수</span></h3>
        <ol class="plain rp-menus">${menus.map((x, i) => `<li><span class="rp-rank">${i + 1}</span><b>${esc(x.menu)}</b><span class="rp-menu-n">${esc(x.count)}건</span></li>`).join("")
          || '<li class="small muted">칭찬 리뷰에 나온 메뉴가 아직 없어요.</li>'}</ol>
        <h3 class="rp-h3">대표 칭찬 한 줄</h3>
        ${p.quote ? `<blockquote class="rp-quote"><p>“${esc(p.quote.text)}”</p><footer class="small muted">${p.quote.rating ? `별점 ${esc(p.quote.rating)}점 리뷰` : "별점 없는 리뷰"} · 개인정보를 가린 글</footer></blockquote>`
          : '<p class="small muted rp-quote-none">아직 칭찬 리뷰가 없어요.</p>'}
      </div>
    </div>
    <p class="small muted">이 달 리뷰 ${esc(p.review_count ?? 0)}건을 코드로 셌어요 (모델 호출 없음). 인기 메뉴와 대표 한 줄은 칭찬 리뷰 ${esc(p.praise_count ?? 0)}건에서 골랐어요.${
      p.praise_basis === "rating" ? " 긍정으로 분류된 리뷰가 없어서, 별점 4점 이상이고 불만이 없는 리뷰를 칭찬 리뷰로 봤어요." : ""}<span class="rp-screen"> 달은 월간 보고서에서 바꿔요.</span></p>`;
  rpState("praise", "");
}

// 상권 요약: 브리핑의 상권 지표 (홈 '상권 저녁 매출' 칸과 같은 자료). 서버를 다시 부르지 않는다
function rpMarket() {
  const b = state.briefing;
  if (!b) {
    $("rp-market").innerHTML = "";
    rpState("market", state.booted ? "브리핑을 불러오지 못해 상권 요약을 만들 수 없어요. 홈에서 다시 불러와 주세요." : "불러오는 중…", !!state.booted);
    return;
  }
  const snaps = (b.snapshots || []).filter((s) => s && typeof s.value === "number");
  $("rp-market").innerHTML = `
    <p class="rp-store">${esc([b.store?.name, b.store?.business_type_name, b.store?.area_name ? `${b.store.area_name} 상권` : ""].filter(Boolean).join(" · "))}</p>
    <ul class="plain rp-snaps">${snaps.map((s) => `
      <li><span class="rp-snap-v${s.value < 0 ? " neg" : ""}">${esc(`${s.value > 0 ? "+" : ""}${s.value.toFixed(2)}${s.unit || ""}`)}</span>
        <span class="rp-snap-t"><b>${esc(s.metric_name)}</b>
          <span class="small muted">${esc([s.area_name, s.compared_with_quarter ? "전년 같은 분기 대비" : "", shortBasis(s.basis_label)].filter(Boolean).join(" · "))}${sourceUrl(s.source) ? ` · <a href="${esc(sourceUrl(s.source))}" target="_blank" rel="noopener">원본</a>` : ""}</span>
          ${s.dev_fake ? '<span class="badge bad">개발용 가짜 값 · 발표에 쓰지 마세요</span>' : ""}</span></li>`).join("")
      || '<li class="small muted">상권 지표가 없어요.</li>'}</ul>
    <p class="small muted">상권 통계는 상권·업종 전체의 추정치예요. 우리 가게 매출이 아니에요.</p>
    <button type="button" class="ghost rp-ask" data-rp-ask>AI에게 묻기로 상권 더 보기</button>`;
  rpState("market", "");
}
// 마케팅 요약: 추천 카드 ⓑ(쿠폰 홍보)와 이 브라우저에서 만든 홍보글의 승인 상태, 서버 승인 기록 수 (/api/approvals 는 저장된 기록만 읽음)
// 맞춤 마케팅(#/marketing)은 링크와 이 브라우저에서 승인한 글 수(state.approvedLog)만 둔다. 마케팅 서비스는 부르지 않는다 (리포트를 열어도 AI 를 새로 부르지 않음)
async function rpMarketing() {
  if (!state.booted && !state.cards.length) { $("rp-mkt").innerHTML = ""; rpState("mkt", "불러오는 중…"); return; }
  const promo = state.cards.find((p) => p.card.kind === "promo");
  let html;
  if (promo) {
    const id = promo.card.card_id, made = !!state.results[id];
    const ds = draftsOf(id).filter((d) => d.generator === "coupon_promo");
    const ok = ds.filter((d) => state.approved.has(d.draft_id)).length;
    const st = !made ? ["", "홍보글을 아직 만들지 않았어요"] : ds.length && ok === ds.length ? ["ok", "홍보글 승인 완료"] : ["warn", `홍보글 승인 대기 ${ds.length - ok}개`];
    html = `<p class="rp-mkt-title"><b>${esc(promo.title)}</b></p>
      <p class="rp-mkt-reason">${esc(promo.card.reason_text)}</p>
      <p class="small muted">근거: ${esc(sourceLine(promo))}</p>
      <p class="rp-mkt-st"><span class="badge ${st[0]}">${esc(st[1])}</span><a class="small" href="#/cards">추천 카드에서 보기</a></p>`;
    rpState("mkt", "");
  } else if (state.cards.length || !state.bootError) {
    const why = $("no-card-b").textContent;
    html = `<p class="muted rp-mkt-none">오늘은 쿠폰 홍보 카드(ⓑ)가 없어요.${why ? ` ${esc(why)}` : ""}</p>`;
    rpState("mkt", "");
  } else {
    html = "";
    rpState("mkt", "추천 카드를 불러오지 못해 마케팅 요약을 만들 수 없어요. 홈에서 다시 불러와 주세요.", true);
  }
  const mktDone = state.approvedLog.filter((x) => x.mkt).length;
  // 링크 줄(rp-screen)은 인쇄에서 빠진다 (style.css '종합 리포트 인쇄'가 .rp-screen 을 숨김)
  $("rp-mkt").innerHTML = `${html}${mktDone ? `<p class="small rp-mkt-count">맞춤 마케팅에서 승인한 글 ${esc(mktDone)}건 (이 브라우저 기준)</p>` : ""}
    <p class="small rp-mkt-more rp-screen"><a href="#/marketing">맞춤 마케팅에서 자세히 보기</a></p>
    <p id="rp-approvals" class="small muted">승인 기록을 불러오는 중…</p>`;
  try {
    const a = await careApi("/api/approvals");
    const el = $("rp-approvals");
    if (el) el.textContent = `서버에 남은 승인 기록 ${(a.items || []).length}건 (답글·공지·홍보글·맞춤 마케팅 글 합계, 이 방문자 기준)`;
  } catch (e) { const el = $("rp-approvals"); if (el) el.textContent = `승인 기록을 불러오지 못했어요: ${e.message}`; }
}

// 전체 리포트 PDF 저장 (11/16): 브라우저 인쇄 창을 연다 (거기서 'PDF로 저장'). 서버에 새로 묻지 않고, 지금 그려진 여섯 칸이 그대로 나온다.
// 인쇄 모양은 style.css 의 '종합 리포트 인쇄' 덩어리가 정하고, 그 덩어리는 <html class="rp-view"> 일 때만(리포트 화면이 보일 때만) 먹는다.
const RP_PDF_WAIT_MS = 20000;   // 아직 불러오는 칸이 있으면 여기까지 기다렸다가 인쇄 창을 연다
const RP_PDF_HINT = "인쇄 창이 열리면 ‘PDF로 저장’을 골라 주세요.";
// 인쇄할 때 점수 추이 그래프를 그리는 폭·높이. 창이 좁아도(휴대전화) 종이에서는 같은 모양·같은 쪽 수로 나오게.
// 폭은 종이에서 그래프 칸의 폭(A4 − 좌우 여백 − 칸 안 여백 ≈ 675px)에 가까운 값 → 축 글자가 화면처럼 12px. 높이는 두 쪽 안에 들게 낮춤 (11/16)
const RP_PRINT_W = 680;
const RP_PRINT_H = 112;
// route() 가 화면을 바꿀 때마다 loadReport() 나 rpStop() 을 부르므로, 두 곳에서 부르면 표시가 늘 지금 화면과 맞는다
function rpMark() { document.documentElement.classList.toggle("rp-view", currentRoute() === "report"); }
const rpReady = () => state.booted && !rp.loading && !rp.mktBusy;
// 인쇄 직전: 머리글(가게 이름 · 출력한 날 · 기간)을 채우고 접힌 칸(details)을 펼친다. 인쇄가 끝나면 rpPrintDone 이 다시 접는다.
// 시험용 실행이면 화면 맨 위 띠의 안내(실제 AI 결과 아님)를 머리글에도 적는다 (인쇄에서는 그 띠가 빠지므로)
function rpTrendWidth(width) {   // 점수 추이 그래프를 그 폭으로 다시 그린다 (폭을 주면 인쇄 모양: 그 폭과 RP_PRINT_H. 안 주면 화면 폭·화면 높이)
  const svg = document.querySelector("#rp-month .rp-trend");
  if (svg && rp.trend) svg.outerHTML = rpTrend(rp.trend, width, width ? RP_PRINT_H : undefined);
}
function rpPrintPrep() {
  rpMark();
  rpTrendWidth(RP_PRINT_W);
  const now = new Date(), two = (n) => String(n).padStart(2, "0");
  $("rp-print-store").textContent = state.briefing?.store?.name || "";
  $("rp-print-meta").textContent = [
    `출력한 날 ${now.getFullYear()}-${two(now.getMonth() + 1)}-${two(now.getDate())}`,
    rp.day ? `오늘 요약 ${rp.day}` : "",
    rp.month ? `손님 칭찬 요약·월간 보고서 ${monthKo(rp.month)}${rp.until ? ` (${dateKo(rp.until)}까지)` : ""}` : "",
    "응대 점수 최근 28일",
  ].filter(Boolean).join(" · ");
  $("rp-print-note").textContent = state.health?.mode_notice || "";
  document.querySelectorAll('[data-view="report"] details:not([open])').forEach((d) => { d.open = true; d.dataset.rpOpened = "1"; });
}
function rpPrintDone() {
  document.querySelectorAll('[data-view="report"] details[data-rp-opened]').forEach((d) => { d.open = false; delete d.dataset.rpOpened; });
  rpTrendWidth();
}
async function rpPdf() {
  const button = $("rp-pdf"), msg = $("rp-pdf-msg");
  if (!rpReady()) {   // 아직 불러오는 칸이 있으면 끝날 때까지 기다린다 (그동안 버튼을 잠근다)
    button.disabled = true;
    msg.textContent = "리포트를 다 불러오면 인쇄 창을 열어요…";
    const until = Date.now() + RP_PDF_WAIT_MS;
    while (!rpReady() && Date.now() < until) await new Promise((done) => setTimeout(done, 150));
    button.disabled = false;
    msg.textContent = RP_PDF_HINT;
    if (currentRoute() !== "report") return;   // 기다리는 동안 다른 화면으로 갔으면 인쇄하지 않는다
  }
  rpPrintPrep();
  window.print();
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

// ── 맞춤 마케팅 (#/marketing, 11/16 통합) ──────────────────────────────
// 김수현 님 설문형 마케팅(PR #56, experiments/marketing/marketing_survey/web/app.js)의 기능을 이 화면 모양으로 다시 썼다:
// 시작 모드 다섯 개 → 단계별 질문(선택지·여러 개 고르기·숫자/글 입력) → 결과 카드(판단 근거·숫자·할 일·글·쿠폰 계산·광고비 막대·추천 아이디어)
// → 글 고치기·승인(고친 글 점검 실패 표시)·복사 → (공지면) 재주문 쿠폰 이어 묻기·2주 뒤 개선 소식, 그리고 '마케팅 보고서'(주간·월간) 탭.
// 호출은 전용 mktApi 로만 한다: 이 서버의 /api/marketing-survey/* 만 부르고 주소 뒤에 가게를 붙이지 않는다 (가게·방문자는 서버가 고정해 붙임).
// 전역 api()·showAlert(#alert)를 쓰지 않아서, 마케팅 서비스가 꺼져 있거나 느려도 안내는 이 화면 안(#mkt-state·#mkt-error·카드 안)에만 보인다.
// 설문 상태는 서버에 없고 화면이 들고 다닌다 (mkt.flow = {node, raw, confirms, mode}, 요청마다 그대로 보냄).
// 서버 글은 esc() 를 거쳐서만 innerHTML 에 넣는다. 키 없이 저장된 예시(demo: true)면 '시험용 저장 예시 (실제 AI 결과 아님)'를 꼭 보인다.
// 승인하면 서버가 이 방문자의 승인 기록에도 남기고(응답의 recorded), 화면은 '처리 완료' 목록(state.approvedLog)에 더한다.
const MKT_BASE = "/api/marketing-survey/";
const MKT_WAIT_MS = 15000;      // 질문·계산·보고서 (서버는 10초까지 기다림)
const MKT_LONG_MS = 60000;      // 글을 만드는 plan·generate·idea-try (서버는 45초까지, MARKETING_TIMEOUT_SEC)
const MKT_LONG = ["plan", "generate", "idea-try"];
const MKT_DEMO = "시험용 저장 예시 (실제 AI 결과 아님)";
// 시작 모드 다섯 개: 서버(flow.py START_MODES)가 주는 보기 글자 → 한 줄 설명. 보기 자체는 서버가 준 것만 그린다
const MKT_MODES = {
  "맞춤 홍보 제안": "반복 불만·목표·예산을 여쭤보고 홍보 방법과 글을 제안해요",
  "남은 재료 팔기": "오늘 남은 메뉴를 세트·할인·추천 글로 팔아요",
  "광고비 점검": "배달앱 광고비가 주문 한 건에서 남는 돈보다 큰지 계산해요",
  "가게 이야기 글": "사장님 답만으로 플레이스·인스타·배민 소개 글을 써요",
  "쿠폰 결과 확인": "지난 쿠폰의 사용률과 다음 쿠폰 조건을 알려 드려요",
};
// 숫자 입력칸의 단위 (서버 free_input.key → 화면 표시만)
const MKT_UNIT = { leftover_portions: "인분", _adspend_spend_entry: "원", _adspend_orders_entry: "건", adspend_avg_amount_won: "원",
  coupon_issued: "장", coupon_used: "장", coupon_discount_won: "원", coupon_avg_order_won: "원", survey_avg_order_won: "원" };
const MKT_VERDICT = { "손해 광고": ["bad", "손해 광고"], "주의": ["warn", "주의"], "괜찮음": ["ok", "괜찮음"] };
// 글 만드는 생성기 → 승인 기록에 남기는 글 종류 (서버 server.py 의 _GENERATOR_KINDS 와 같은 이름, marketing_proxy.KINDS 안에서만)
const MKT_KIND = { prevention_notice: "공지", late_notice_template: "공지", reply_draft: "답글", review_promo: "홍보 글", coupon_promo: "쿠폰 글" };
const MKT_MODE_KIND = { leftover: "남은 재료 글", story: "가게 이야기 글" };
const MKT_PERIOD = {
  weekly: { name: "주간", now: "이번 주", prev: "지난주", next: "다음 주" },
  monthly: { name: "월간", now: "이번 달", prev: "지난달", next: "다음 달" },
};
const MKT_TABS = ["chat", "report"];
const MKT_STATES = {
  off: "맞춤 마케팅을 쓸 수 없어요", down: "지금은 맞춤 마케팅에 연결할 수 없어요", error: "맞춤 마케팅을 불러오지 못했어요",
};
const mkt = {
  started: false, loading: false, ready: false, busy: false,
  health: null,       // GET health 응답 (state, mode, key_present, demo)
  flow: null,         // 설문 상태 {node, raw, confirms, mode}. 요청마다 그대로 보낸다
  prompt: null,       // 지금 답 고르기 칸의 보기·입력 ({opts, input})
  retry: null,        // '다시 시도'가 다시 부를 일
  gen: 0,             // '처음부터'·'처음부터 다시' 때 올린다 → 그 전에 보낸 요청의 늦은 답은 버린다
  cards: 0,           // 결과 카드 번호 (요소 id·승인 기록의 글 id 에 씀)
  demoSeen: false,    // 저장된 예시(demo: true) 결과를 한 번이라도 받았는지
  clearNote: "",      // '처음부터 다시' 때 마케팅 기록을 지우지 못했으면 그 안내
  tab: "chat", period: "weekly", reportGen: 0, tick: null,
};
const wonKo = (n) => `${Number(n || 0).toLocaleString("ko-KR")}원`;
const mktRound100 = (v) => Math.round(v / 100) * 100;
const mktKey = (k) => String(k).replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 40);

// 맞춤 마케팅 전용 호출 (api() 와 같은 모양): path 는 /api/marketing-survey/ 뒤 부분. 글을 만드는 경로는 60초, 그 밖은 15초에 끊는다.
// 실패하면 message·state 를 담은 Error (화면 맨 위 띠에는 아무것도 띄우지 않음)
async function mktApi(path, options = {}) {
  const ctl = new AbortController();
  const name = String(path).split("?")[0];
  const timer = setTimeout(() => ctl.abort(), MKT_LONG.includes(name) ? MKT_LONG_MS : MKT_WAIT_MS);
  const fail = (message, st, status) => Object.assign(new Error(message), { state: st, status });
  const headers = { Accept: "application/json" };
  if (typeof options.body === "string") headers["Content-Type"] = "application/json";
  try {
    const res = await fetch(MKT_BASE + path, { credentials: "same-origin", cache: "no-store", ...options, headers, signal: ctl.signal });
    const body = await res.json().catch(() => null);
    if (res.ok && body) return body;
    if (body?.error?.message) throw fail(body.error.message, body.error.state || "error", res.status);
    if (res.status === 404) throw fail("이 서버에는 아직 맞춤 마케팅이 연결되지 않았어요.", "off", 404);
    throw fail(res.ok ? "응답을 읽지 못했어요. 잠시 뒤 다시 해 주세요." : `맞춤 마케팅이 응답하지 않았어요 (${res.status}). 잠시 뒤 다시 해 주세요.`, "error", res.status);
  } catch (e) {
    if (e.name === "AbortError") throw fail("응답이 너무 늦어요. 잠시 뒤 다시 해 주세요.", "timeout", 0);
    if (e instanceof TypeError) throw fail("서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.", "down", 0);
    throw e;
  } finally { clearTimeout(timer); }
}
const mktPost = (path, data) => mktApi(path, { method: "POST", body: JSON.stringify(data) });

// ── 진행·오류·위쪽 안내 ──
// 진행 안내 (#mkt-status, role=status): 깜박이는 점 + 글 + 걸린 초 (초는 읽기 프로그램에 읽히지 않게)
function mktBusy(text, long = false) {
  const el = $("mkt-status");
  clearInterval(mkt.tick);
  mkt.busy = !!text;
  el.classList.toggle("busy", !!text);
  el.replaceChildren();
  if (!text) return;
  const msg = mk("span", "", text), sec = mk("span", "mkt-sec");
  sec.setAttribute("aria-hidden", "true");
  el.append(msg, sec);
  const t0 = Date.now();
  mkt.tick = setInterval(() => {
    const s = Math.floor((Date.now() - t0) / 1000);
    sec.textContent = s >= 2 ? `${s}초` : "";
    if (long && s === 6) msg.textContent = `${text}. AI가 글을 쓰면 30초 넘게 걸릴 수 있어요`;
  }, 1000);
}
// 오류 (#mkt-error, role=alert). retry 를 주면 답 고르기 칸에 '다시 시도'
function mktErr(message, retry) {
  $("mkt-error").textContent = message || "";
  mkt.retry = retry || null;
  if (retry) $("mkt-options").innerHTML = '<div class="row"><button type="button" class="primary" data-mkt-retry>다시 시도</button></div>';
}
// 화면 위 안내 (#mkt-notice): 키 없이 저장된 예시로 도는 중이면 꼭, '처음부터 다시' 때 기록을 못 지웠으면 그 안내도
function mktNotice() {
  const h = mkt.health || {};
  const demo = h.demo === true || h.mode === "mock" || h.key_present === false || mkt.demoSeen;   // mock 이면 키가 있어도 데모
  const lines = [demo ? "시험용 실행 · 맞춤 마케팅이 지금 HCX를 부르지 않아 글은 미리 저장한 예시·정해 둔 틀이에요 (실제 AI 결과 아님)" : "", mkt.clearNote].filter(Boolean);
  $("mkt-notice").hidden = !lines.length;
  $("mkt-notice").textContent = lines.join(" ");
}
// 마케팅 서비스를 쓸 수 없을 때: 탭·대화를 숨기고 상태 안내와 '다시 확인'만 (다른 화면은 그대로)
function mktDown(st, message) {
  const key = MKT_STATES[st] ? st : st === "timeout" ? "down" : "error";
  mkt.ready = false;
  $("mkt-state").dataset.state = key;
  $("mkt-state-title").textContent = MKT_STATES[key];
  $("mkt-state-msg").textContent = message || "잠시 뒤 다시 확인해 주세요.";
  mktPanels(false);
  mktBusy("");
  $("mkt-status").textContent = "";
}
function mktPanels(ready) {
  $("mkt-state").hidden = ready;
  document.querySelector(".mkt-tabs").hidden = !ready;
  $("mkt-chat").hidden = !ready || mkt.tab !== "chat";
  $("mkt-report-panel").hidden = !ready || mkt.tab !== "report";
}

// ── 대화 칸 ──
function mktAdd(html) { $("mkt-log").insertAdjacentHTML("beforeend", html); return $("mkt-log").lastElementChild; }
const mktBot = (text) => mktAdd(`<div class="mkt-msg bot"><p>${esc(text)}</p></div>`);
const mktUser = (text) => mktAdd(`<div class="mkt-msg user"><p class="mkt-bubble">${esc(text)}</p></div>`);
function mktReveal(el, block = "nearest") {
  if (el && el.isConnected) el.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block });
}

// 화면을 열 때 (route): 처음이면 시작, 보고서 탭이면 그 기간을 다시 부른다
function mktOpen() {
  mktNotice();
  if (!mkt.started) { mkt.started = true; mktStart(); return; }
  if (mkt.ready && mkt.tab === "report") mktReport(mkt.period);
}
// 시작 (처음 열 때, '다시 확인'): health → 가게 이름 → 첫 질문
async function mktStart() {
  if (mkt.loading) return;
  mkt.loading = true;
  const gen = ++mkt.gen, retry = $("mkt-retry");
  retry.disabled = true; retry.textContent = "확인하는 중…";
  mktErr("");
  mktBusy("맞춤 마케팅을 확인하고 있어요");
  try {
    const h = await mktApi("health");
    if (gen !== mkt.gen) return;
    mkt.health = h;
    mktNotice();
    if (h.state !== "ready") { mktDown(h.state, h.message); return; }
    mkt.ready = true;
    mktPanels(true);
    mktApi("meta").then((m) => { $("mkt-store").textContent = m?.store_name ? `${m.store_name} 기준` : ""; }).catch(() => {});
    await mktFirst(gen);
  } catch (e) { if (gen === mkt.gen) mktDown(e.state, e.message); }
  finally {
    mkt.loading = false;
    retry.disabled = false; retry.textContent = "다시 확인";
  }
}
// 첫 질문 (무엇을 도와드릴까요? + 시작 모드 다섯 개). '처음부터'도 여기로 (기록은 지우지 않음)
async function mktFirst(gen = ++mkt.gen, focus = false) {
  $("mkt-log").replaceChildren();
  $("mkt-options").replaceChildren();
  mkt.flow = null; mkt.prompt = null;
  mktErr("");
  mktBusy("첫 질문을 불러오고 있어요");
  try {
    const d = await mktPost("step", { state: null, answer: null });
    if (gen !== mkt.gen) return;
    mktBusy("");
    mkt.flow = d.state;
    (d.bot_messages || []).forEach(mktBot);
    mktAdd('<p class="mkt-sub">고친 만큼, 남는 만큼만 홍보해요</p>');
    mktPrompt(d, focus);
  } catch (e) {
    if (gen !== mkt.gen) return;
    mktBusy("");
    mktErr(e.message, () => mktFirst(undefined, true));
  }
}

// 답 고르기 칸: 시작 모드 카드 · 보기(하나) · 여러 개 고르기 + [다음] · 숫자/글 입력(예시 문구, 건너뛰기)
function mktPrompt(d, focus = true) {
  const box = $("mkt-options");
  const opts = Array.isArray(d.options) ? d.options : [];
  const start = mkt.flow?.node === "start";
  mkt.prompt = { opts, input: d.input || null };
  if (d.example) mktAdd(`<p class="mkt-example small muted">${esc(d.example)}</p>`);
  let html = "";
  if (start) {
    html = `<div class="mkt-modes">${opts.map((o, i) => `<button type="button" class="mkt-mode" data-mkt-opt="${i}"><b>${esc(o.label)}</b>${MKT_MODES[o.label] ? `<span class="small muted">${esc(MKT_MODES[o.label])}</span>` : ""}</button>`).join("")}
      <button type="button" class="mkt-mode mkt-mode-report" data-mkt-goto-report><b>마케팅 보고서</b><span class="small muted">이번 주·이번 달 마케팅 기록을 봐요</span></button></div>`;
  } else if (d.multi) {
    html = `<div class="mkt-chips" role="group" aria-label="여러 개 고르기">${opts.map((o, i) => `<button type="button" class="chip" aria-pressed="false" data-mkt-multi="${i}">${esc(o.label)}</button>`).join("")}</div>
      <div class="row mkt-multi-row"><button type="button" class="primary" data-mkt-next disabled>다음</button><span class="small muted">여러 개 고를 수 있어요</span></div>`;
  } else if (opts.length) {
    html = `<div class="mkt-chips">${opts.map((o, i) => `<button type="button" class="chip" data-mkt-opt="${i}">${esc(o.label)}</button>`).join("")}</div>`;
  }
  if (d.input) html += mktInputHtml(d.input, opts.length > 0);
  box.innerHTML = html;
  if (focus) box.querySelector("button:not([disabled]), input, textarea")?.focus({ preventScroll: true });
  mktReveal(box);
}
function mktInputHtml(spec, withOptions) {
  if (spec.type === "number") {
    const unit = MKT_UNIT[spec.key] || "";
    return `<div class="mkt-input" data-mkt-input="number"><label class="sr" for="mkt-num">숫자로 답하기</label>
        <input id="mkt-num" type="text" inputmode="numeric" autocomplete="off" placeholder="숫자로 답해 주세요">
        ${unit ? `<span class="mkt-unit">${esc(unit)}</span>` : ""}<button type="button" class="primary" data-mkt-send>보내기</button></div>
      ${spec.skip ? '<div class="row"><button type="button" class="chip" data-mkt-skip>건너뛰기</button></div>' : ""}
      <p class="mkt-input-err" data-mkt-input-err role="alert"></p>`;
  }
  if (spec.skip) {   // 가게 이야기처럼 길게 쓰는 답: 여러 줄 칸 + 글자 수 + [건너뛰기][보내기]
    return `<div class="mkt-free" data-mkt-input="free"><label class="sr" for="mkt-free">답 쓰기</label>
      <textarea id="mkt-free" rows="3" maxlength="500" placeholder="답을 입력해 주세요"></textarea>
      <div class="mkt-free-bar"><span class="small muted" data-mkt-count aria-hidden="true">0자</span>
        <span class="row"><button type="button" class="ghost" data-mkt-skip>건너뛰기</button><button type="button" class="primary" data-mkt-send>보내기</button></span></div></div>`;
  }
  return `<div class="mkt-input" data-mkt-input="text"><label class="sr" for="mkt-text">${withOptions ? "직접 입력" : "답 쓰기"}</label>
      <input id="mkt-text" type="text" maxlength="100" autocomplete="off" placeholder="${withOptions ? "또는 직접 입력해 주세요" : "답을 입력해 주세요"}">
      <button type="button" class="primary" data-mkt-send>보내기</button></div>
    <p class="mkt-input-err" data-mkt-input-err role="alert"></p>`;
}
// 입력칸의 [보내기] (Enter 도 같다. 한글 입력 중의 Enter 는 글자만 확정)
function mktSend() {
  const box = $("mkt-options"), kind = box.querySelector("[data-mkt-input]")?.dataset.mktInput;
  const err = box.querySelector("[data-mkt-input-err]");
  if (kind === "number") {
    const digits = $("mkt-num").value.replace(/[^0-9]/g, "");
    if (!digits) { err.textContent = "숫자를 입력해 주세요"; $("mkt-num").focus(); return; }
    mktAnswer(digits, `${Number(digits).toLocaleString("ko-KR")}${MKT_UNIT[mkt.prompt?.input?.key] || ""}`);
  } else if (kind === "free" || kind === "text") {
    const el = kind === "free" ? $("mkt-free") : $("mkt-text");
    const value = el.value.trim();
    if (!value) { if (err) err.textContent = "답을 입력해 주세요"; el.focus(); return; }
    mktAnswer(value, value);
  }
}
async function mktAnswer(answer, label) {
  if (mkt.busy) return;
  mktUser(label);
  await mktStep(answer);
}
// 질문 하나 진행 (POST step). 끝(done)이면 결과 카드
async function mktStep(answer, focus = true) {
  const gen = mkt.gen;
  mktErr("");
  $("mkt-options").replaceChildren();
  mkt.prompt = null;
  mktBusy("다음 질문을 준비하고 있어요");
  let d;
  try { d = await mktPost("step", { state: mkt.flow, answer }); }
  catch (e) {
    if (gen !== mkt.gen) return;
    mktBusy("");
    mktErr(e.message, () => mktStep(answer, focus));
    return;
  }
  if (gen !== mkt.gen) return;
  mktBusy("");
  mkt.flow = d.state;
  if (d.done) { await mktDecide(); return; }
  (d.bot_messages || []).forEach(mktBot);
  mktPrompt(d, focus);
}

// ── 결과 카드 ──
// plan(글 생성 포함)과, 맞춤 홍보 제안·재주문 쿠폰이면 result(결정 설명 3줄, 규칙 계산)를 같이 받는다
async function mktDecide(flow = mkt.flow, label = "결과를 정리하고 글을 만들고 있어요") {
  const gen = mkt.gen;
  mktErr("");
  if (flow === mkt.flow) $("mkt-options").replaceChildren();   // 다시 쓰기로 예전 카드를 다시 받을 때는 지금 질문을 지우지 않는다
  mktBusy(label, true);
  const survey = flow?.mode === "survey" || flow?.mode === "follow_up";
  let plan, why;
  try {
    [plan, why] = await Promise.all([mktPost("plan", { state: flow }), survey ? mktPost("result", { state: flow }).catch(() => null) : null]);
  } catch (e) {
    if (gen !== mkt.gen) return;
    mktBusy("");
    mktErr(e.message, () => mktDecide(flow, label));
    return;
  }
  if (gen !== mkt.gen) return;
  mktBusy("");
  return mktResult(plan, why, flow);
}
// 판정 배지: 서버가 준 판정(verdict·usage_rate·strategy_type)만 보고 가른다 (원본 badgeFor)
function mktBadge(d) {
  if (Array.isArray(d.table)) {
    const rank = { "괜찮음": 0, "주의": 1, "손해 광고": 2 };
    const judged = d.table.filter((r) => r.verdict);
    return judged.length ? MKT_VERDICT[judged.reduce((a, b) => (rank[b.verdict] > rank[a.verdict] ? b : a)).verdict] || null : null;
  }
  if (d.strategy_type === "fix_first") return ["bad", "먼저 고치기"];
  if (d.usage_rate !== undefined) {
    const r = d.usage_rate;
    return r == null ? ["bad", "점검 필요"] : r < 0.2 ? ["warn", "주의"] : r <= 0.5 ? ["ok", "같은 조건 유지"] : ["warn", "할인 큼"];
  }
  return ["", "정보"];
}
// 숫자 타일 [값, 이름] (원본 buildTiles)
function mktTiles(d) {
  if (Array.isArray(d.table)) {
    const flagged = d.table.filter((r) => r.verdict && r.verdict !== "괜찮음");
    return [[`${d.table.length}개`, "점검한 채널"], [`${flagged.length}개`, "주의·손해 채널"],
      ...(d.profit_per_order_won != null ? [[wonKo(d.profit_per_order_won), "건당 이익(추정)"]] : [])];
  }
  if (d.usage_rate !== undefined) {
    const t = [];
    if (d.usage_rate != null) t.push([`${Math.round(d.usage_rate * 100)}%`, "쿠폰 사용률"]);
    if (d.issued != null && d.used != null) t.push([`${d.issued}장 / ${d.used}장`, "발급 / 사용"]);
    if (d.total_discount_cost_won != null) t.push([wonKo(d.total_discount_cost_won), "총 할인 비용"]);
    if (d.breakeven_orders != null) t.push([`${d.breakeven_orders}건`, "본전 주문 수"]);
    return t;
  }
  if (d.coupon_card) {
    const c = d.coupon_card, t = [[wonKo(c.discount_won), "할인액"]];
    if (c.count) t.push([`${c.count}장`, "발급 수량"]);
    if (c.breakeven_orders != null) t.push([`${c.breakeven_orders}건`, "본전 주문 수"]);
    return t;
  }
  return [];
}
const mktTilesHtml = (tiles, attr = "") => `<dl class="mkt-tiles"${attr}>${tiles.map(([n, l], i) => `<div><dt>${esc(l)}</dt><dd data-mkt-tile="${i}">${esc(n)}</dd></div>`).join("")}</dl>`;
// 글 상자 하나: 바로 고칠 수 있는 글 칸 + 복사. 승인할 때 이 카드의 글을 모두 같이 보낸다 (card.drafts 에 등록)
function mktDraftHtml(card, key, text, kind, label) {
  const id = `mkt-text-${card.n}-${mktKey(key)}`;
  card.pending.push({ key, text: String(text ?? ""), kind });
  return `<div class="mkt-draft" data-mkt-draft="${esc(key)}">
    <div class="mkt-draft-head"><label for="${esc(id)}">${esc(label)}</label><span class="badge warn" data-mkt-edited hidden>고친 글</span></div>
    <textarea id="${esc(id)}" rows="4" data-mkt-text="${esc(key)}">${esc(text)}</textarea>
    <ul class="issues bad" data-mkt-fail hidden></ul>
    <div class="row"><button type="button" class="ghost" data-mkt-copy="${esc(key)}">복사</button></div>
  </div>`;
}
const mktDraftLabel = (kind, demo, fixed = false) => demo ? `${kind} · ${MKT_DEMO}` : fixed ? `${kind} · 정해 둔 틀 (AI 아님)` : `${kind} 초안`;
// 방금 그린 글 상자를 카드에 등록 (승인·고친 표시·점검 실패 표시가 이 등록을 본다)
function mktRegister(card, root = card.el) {
  card.pending.splice(0).forEach((p) => {
    const box = root.querySelector(`textarea[data-mkt-text="${CSS.escape(p.key)}"]`);
    if (box) card.drafts.set(p.key, { kind: p.kind, original: p.text, box });
  });
}

function mktResult(d, why, flow) {
  // run: 이 카드의 글 id 앞부분 (새로 고친 뒤에도 앞서 승인한 기록과 겹치지 않게 임의 값)
  const run = (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "") : Date.now().toString(36) + Math.random().toString(36).slice(2)).slice(0, 10);
  const card = { n: ++mkt.cards, run, flow, data: d, session: d.session_id || null, demo: d.demo === true, title: d.title || "결과",
    drafts: new Map(), pending: [], approved: false, busy: false, idea: null, ideaIndex: d.idea_index ?? 0, timer: null, seq: 0, gen: mkt.gen };
  if (card.demo) { mkt.demoSeen = true; mktNotice(); }
  const badge = mktBadge(d), tiles = mktTiles(d), steps = Array.isArray(d.steps) ? d.steps : [], drafts = d.drafts || {};
  const whyLines = (Array.isArray(why?.explain) && why.explain.length ? why.explain
    : d.summary ? [d.summary] : steps.length === 1 && steps[0].tip ? [steps[0].tip] : []).filter((t) => typeof t === "string" && t);
  const stepKind = (s) => MKT_KIND[s.generator] || MKT_MODE_KIND[flow?.mode] || "마케팅 글";
  const todoHead = steps.length ? `이번 주 할 일 ${steps.length}개 · 약 ${esc(d.total_minutes ?? 0)}분${d.total_cost_krw ? ` · 추정 비용 ${esc(wonKo(d.total_cost_krw))}` : ""}` : "";
  const html = `<article class="mkt-card" id="mkt-card-${card.n}" aria-labelledby="mkt-card-${card.n}-title">
    <div class="mkt-card-head"><h2 id="mkt-card-${card.n}-title" tabindex="-1">${esc(card.title)}</h2>
      ${badge ? `<span class="badge ${badge[0]}" data-mkt-badge>${esc(badge[1])}</span>` : ""}
      ${card.demo ? `<span class="badge">${esc(MKT_DEMO)}</span>` : ""}<span class="badge ok" data-mkt-approved hidden>승인함</span></div>
    ${tiles.length ? mktTilesHtml(tiles) : ""}
    ${whyLines.length ? `<div class="mkt-why"><p class="mkt-why-title">왜 이렇게 판단했나요</p><ul>${whyLines.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>
      <p class="small muted">사장님 답변과 가게 데이터 기준 · 정해 둔 규칙으로 고른 결과예요 (AI 판단 아님)</p></div>` : ""}
    ${d.over_budget ? '<p class="mkt-warn">예상 비용(추정) 합계가 설문에서 답한 예산을 넘어요.</p>' : ""}
    ${Array.isArray(d.table) && d.table.length ? mktAdspendHtml(d.table) : ""}
    ${steps.length ? `<p class="mkt-todo-head">${todoHead}</p><ol class="mkt-steps">${steps.map((s, i) => `<li class="mkt-step">
        <div class="mkt-step-top"><span class="mkt-step-n" aria-hidden="true">${i + 1}</span><b>${esc(s.what)}</b>
          <span class="mkt-step-meta">${esc(s.when || "")}${s.minutes ? ` · ${esc(s.minutes)}분` : ""}${s.cost_krw ? ` · ${esc(wonKo(s.cost_krw))}` : ""}</span></div>
        ${s.where && s.where !== "-" ? `<p class="small muted">${esc(s.where)}</p>` : ""}
        ${drafts[s.step_id] ? mktDraftHtml(card, s.step_id, drafts[s.step_id], stepKind(s), mktDraftLabel(stepKind(s), card.demo, s.generator === "late_notice_template")) : ""}
        ${s.tip ? `<p class="small mkt-tip">체크: ${esc(s.tip)}</p>` : ""}</li>`).join("")}</ol>` : ""}
    ${Array.isArray(d.todos) && d.todos.length ? `<p class="mkt-todo-head">할 일 ${d.todos.length}개</p>
      <ol class="mkt-steps">${d.todos.map((t, i) => `<li class="mkt-step"><div class="mkt-step-top"><span class="mkt-step-n" aria-hidden="true">${i + 1}</span><b>${esc(t)}</b></div></li>`).join("")}</ol>
      ${d.todo_note ? `<p class="small muted">${esc(d.todo_note)}</p>` : ""}` : ""}
    ${d.bundle ? `<p class="mkt-line">원래 합계 ${esc(wonKo(d.bundle.original_won))} → 세트 가격 <b>${esc(wonKo(d.bundle.bundle_won))}</b></p>` : ""}
    ${d.discount_tile ? `<p class="mkt-line">원래 가격 ${esc(wonKo(d.discount_tile.original_won))} → 할인 가격 <b>${esc(wonKo(d.discount_tile.sale_won))}</b></p>` : ""}
    ${Array.isArray(d.basic_todos) && d.basic_todos.length ? `<div class="mkt-box"><p class="mkt-box-title">기본 할 일</p>
      <ul class="mkt-list">${d.basic_todos.map((t) => `<li>${esc(t.title)}</li>`).join("")}</ul>
      ${d.basic_todos.map((t, i) => (t.draft ? mktDraftHtml(card, `basic_todo_${i}`, t.draft, "기본 할 일 글", mktDraftLabel("기본 할 일 글", card.demo)) : "")).join("")}</div>` : ""}
    ${d.idea ? '<div data-mkt-idea></div>' : ""}
    ${d.coupon_card ? mktCouponHtml(card, d.coupon_card) : ""}
    ${d.breakeven_orders != null && !d.coupon_card ? `<p class="mkt-line">본전이 되려면 ${esc(d.breakeven_orders)}건이 필요해요</p>` : ""}
    ${d.next_condition ? `<div class="mkt-box dashed"><p class="mkt-box-title">다음 쿠폰 조건</p>
      <p class="mkt-line">할인액 ${esc(wonKo(d.next_condition.discount_won))} · ${esc(d.next_condition.note || "")}</p>
      <div class="row"><button type="button" data-mkt-next-coupon>이 조건으로 쿠폰 글 만들기</button></div><div data-mkt-next-out></div></div>` : ""}
    ${d.measure ? `<p class="mkt-measure"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg><span>${esc(d.measure)}</span></p>` : ""}
    ${card.demo ? '<p class="mkt-demo">HCX를 부르지 않고 미리 저장한 예시·정해 둔 틀로 만든 글이에요. 실제 AI가 이 가게를 보고 쓴 글이 아니에요.</p>' : ""}
    <div class="row mkt-card-actions"><button type="button" class="primary" data-mkt-approve>승인</button>
      <button type="button" class="ghost" data-mkt-rewrite>다시 쓰기</button><a class="small" href="#/done" data-mkt-done hidden>처리 완료에서 보기</a></div>
    <p class="small mkt-card-msg" role="status" data-mkt-card-msg></p>
    <div data-mkt-follow></div>
  </article>`;
  card.el = mktAdd(html);
  mktRegister(card);
  if (d.idea) mktIdea(card, d.idea, card.ideaIndex);
  if (d.coupon_card?.calc_input) mktCalcBind(card, card.el.querySelector("[data-mkt-calc]"), d.coupon_card.calc_input);
  mktCardBind(card);
  mktReveal(card.el, "start");
  card.el.querySelector("h2").focus({ preventScroll: true });
  return card;
}
function mktCardMsg(card, text, bad = false) {
  const el = card.el.querySelector("[data-mkt-card-msg]");
  el.textContent = text || "";
  el.classList.toggle("bad", bad);
}
// 카드 안의 버튼·글 칸 (한 카드 안에서만 찾는다)
function mktCardBind(card) {
  const el = card.el;
  el.addEventListener("input", (e) => {
    const box = e.target.closest("textarea[data-mkt-text]");
    if (!box) return;
    const d = card.drafts.get(box.dataset.mktText);
    const wrap = box.closest(".mkt-draft");
    if (d && wrap) {
      wrap.querySelector("[data-mkt-edited]").hidden = box.value.trim() === d.original.trim();
      const fail = wrap.querySelector("[data-mkt-fail]");
      fail.hidden = true; fail.replaceChildren();
    }
  });
  el.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || b.disabled || !el.contains(b)) return;
    if (b.dataset.mktCopy != null) mktCopy(b, b.closest(".mkt-draft")?.querySelector("textarea"));
    else if (b.hasAttribute("data-mkt-approve")) mktApprove(card, b);
    else if (b.hasAttribute("data-mkt-rewrite")) mktRewrite(card, b);
    else if (b.hasAttribute("data-mkt-next-coupon")) mktNextCoupon(card, b);
    else if (b.hasAttribute("data-mkt-coupon-gen")) mktCouponGen(card, b);
    else if (b.hasAttribute("data-mkt-notice")) mktNoticeFollow(card, b);
  });
}
async function mktCopy(button, box) {
  if (!box) return;
  try { await navigator.clipboard.writeText(box.value); }
  catch { box.select(); document.execCommand("copy"); }
  button.textContent = "복사됨";
  setTimeout(() => { if (button.isConnected) button.textContent = "복사"; }, 1500);
}

// 광고비 점검: 표 + 앱마다 막대 두 개(건당 광고비 · 건당 이익, 같은 눈금). 값은 서버가 계산한 그대로
function mktAdspendHtml(rows) {
  const judged = rows.filter((r) => r.cost_per_order_won != null);
  const scale = Math.max(1, ...judged.flatMap((r) => [Number(r.cost_per_order_won) || 0, Number(r.profit_per_order_won) || 0]));
  const pct = (v) => Math.max(0, Math.min(100, Math.round(((Number(v) || 0) / scale) * 100)));
  return `<div class="mkt-table-wrap"><table class="mkt-table"><caption class="sr">배달앱별 광고비 손익</caption>
      <thead><tr><th scope="col">앱</th><th scope="col" class="num">광고비</th><th scope="col" class="num">주문</th><th scope="col" class="num">건당 광고비</th><th scope="col" class="num">건당 이익</th><th scope="col">판정</th></tr></thead>
      <tbody>${rows.map((r) => { const v = MKT_VERDICT[r.verdict]; return `<tr><th scope="row">${esc(r.label)}</th><td class="num">${esc(wonKo(r.spend_won))}</td>
        <td class="num">${esc(Number(r.orders || 0).toLocaleString("ko-KR"))}건</td><td class="num">${r.cost_per_order_won == null ? "–" : esc(wonKo(r.cost_per_order_won))}</td>
        <td class="num">${esc(wonKo(r.profit_per_order_won))}</td><td>${v ? `<span class="badge ${v[0]}">${esc(v[1])}</span>` : "–"}</td></tr>`; }).join("")}</tbody></table></div>
    ${judged.length ? `<div class="mkt-bars">${judged.map((r) => `<div class="mkt-bar-row" role="img" aria-label="${esc(`${r.label}: 건당 광고비 ${wonKo(r.cost_per_order_won)}, 건당 이익 ${wonKo(r.profit_per_order_won)}`)}">
        <p class="mkt-bar-name" aria-hidden="true">${esc(r.label)}</p>
        <div class="mkt-bar" aria-hidden="true"><span class="mkt-bar-track"><i class="${esc((MKT_VERDICT[r.verdict] || ["ok"])[0])}" style="width:${pct(r.cost_per_order_won)}%"></i></span><span class="small">건당 광고비 ${esc(wonKo(r.cost_per_order_won))}</span></div>
        <div class="mkt-bar" aria-hidden="true"><span class="mkt-bar-track"><i class="profit" style="width:${pct(r.profit_per_order_won)}%"></i></span><span class="small">건당 이익 ${esc(wonKo(r.profit_per_order_won))}</span></div></div>`).join("")}</div>` : ""}`;
}

// 쿠폰 카드 (+ calc_input 이 있으면 슬라이더): 예산·할인액을 움직이면 150ms 뒤 coupon-calc 로 장수·최대 비용·본전 주문 수를 다시 계산 (원본처럼 묶어서 보냄)
function mktCouponHtml(card, c) {
  const rows = [["혜택", `${wonKo(c.discount_won)} 할인`], ["발급 수량", c.count ? `${c.count}장` : null], ["시간대", c.timing || null],
    ["유효기간", c.days ? `발급일 포함 ${c.days}일` : null]].filter(([, v]) => v != null && v !== "-");
  let calc = "";
  const input = c.calc_input;
  if (input) {
    const price = Number(input.price_won) || 0;
    const minD = Math.max(100, mktRound100(price * 0.05)), maxD = Math.max(minD, mktRound100(price * 0.3));
    const startD = Math.min(Math.max(Number(input.discount_won) || 0, minD), maxD), maxB = 300000;
    card.calc = { budget_won: Math.min(Number(input.budget_won) || 0, maxB), discount_won: startD };
    const n = card.n;
    calc = `<div class="mkt-calc" data-mkt-calc>
      <div class="mkt-slider"><label for="mkt-budget-${n}">월 예산 <output data-mkt-out="budget_won">${esc(wonKo(card.calc.budget_won))}</output></label>
        <input type="range" id="mkt-budget-${n}" min="0" max="${maxB}" step="10000" value="${esc(card.calc.budget_won)}" data-mkt-range="budget_won" aria-valuetext="${esc(wonKo(card.calc.budget_won))}">
        <p class="mkt-minmax small muted" aria-hidden="true"><span>0원</span><span>${esc(wonKo(maxB))}</span></p></div>
      <div class="mkt-slider"><label for="mkt-discount-${n}">할인액 <output data-mkt-out="discount_won">${esc(wonKo(startD))}</output></label>
        <input type="range" id="mkt-discount-${n}" min="${minD}" max="${maxD}" step="100" value="${startD}" data-mkt-range="discount_won" aria-valuetext="${esc(wonKo(startD))}">
        <p class="mkt-minmax small muted" aria-hidden="true"><span>${esc(wonKo(minD))}</span><span>${esc(wonKo(maxD))}</span></p></div>
      <div class="mkt-budget"><span class="mkt-bar-track" aria-hidden="true"><i class="ok" data-mkt-fill style="width:0%"></i></span><p class="small" data-mkt-budget-label></p></div>
      ${mktTilesHtml([["–", "쿠폰 장수"], ["–", "최대 비용"], ["–", "본전 주문 수"]], ' data-mkt-figs aria-live="polite"')}
      <p class="mkt-warn" data-mkt-calc-warn hidden>할인이 클수록 본전까지 더 많은 주문이 필요해요</p>
      <p class="small muted">계산은 서버 코드가 해요 (AI 아님). 슬라이더를 움직이면 잠깐 뒤 숫자가 바뀌어요.</p>
      <div class="row"><button type="button" data-mkt-coupon-gen>이 조건으로 쿠폰 글 만들기</button></div><div data-mkt-coupon-out></div>
    </div>`;
  }
  return `<div class="mkt-coupon"><p class="small muted mkt-coupon-cap">쿠폰 이름</p>
    <p class="mkt-coupon-title">${esc(c.menu || "대표 메뉴")} ${esc(wonKo(c.discount_won))} 할인</p>
    <dl class="mkt-kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
    ${c.breakeven_orders != null ? `<p class="mkt-line">본전이 되려면 ${esc(c.breakeven_orders)}건이 필요해요</p>` : ""}${calc}</div>`;
}
function mktCalcBind(card, panel, input) {
  if (!panel) return;
  const price = Number(input.price_won) || 0;
  const recalc = async () => {
    if (!panel.isConnected || card.gen !== mkt.gen) return;
    const seq = ++card.seq;
    let fig;
    try {
      fig = await mktPost("coupon-calc", { budget_won: card.calc.budget_won, discount_won: card.calc.discount_won, price_won: price,
        avg_order_won: input.avg_order_won, margin_pct: input.margin_pct });
    } catch (e) { if (seq === card.seq) mktCardMsg(card, `계산하지 못했어요: ${e.message}`, true); return; }
    if (seq !== card.seq) return;   // 그 사이 슬라이더를 또 움직였다: 늦게 온 숫자는 버린다
    mktCardMsg(card, "");
    const budget = card.calc.budget_won;
    panel.querySelector("[data-mkt-fill]").style.width = `${budget > 0 ? Math.min(100, (fig.max_cost_won / budget) * 100) : 0}%`;
    panel.querySelector("[data-mkt-budget-label]").textContent = `쿠폰 비용 ${wonKo(fig.max_cost_won)} · 남는 예산 ${wonKo(fig.remaining_won)}`;
    const cells = panel.querySelectorAll("[data-mkt-figs] dd");
    cells[0].textContent = `${fig.count}장`;
    cells[1].textContent = wonKo(fig.max_cost_won);
    cells[2].textContent = fig.breakeven_orders != null ? `${fig.breakeven_orders}건` : "–";
    panel.querySelector("[data-mkt-calc-warn]").hidden = !(fig.discount_pct > 20);
    // 판정 배지가 '정보'인 카드는 할인이 크면 '할인 큼'으로 (원본과 같음)
    const badge = card.el.querySelector("[data-mkt-badge]");
    if (badge && (badge.textContent === "정보" || badge.textContent === "할인 큼")) {
      badge.className = `badge ${fig.discount_pct > 20 ? "warn" : ""}`;
      badge.textContent = fig.discount_pct > 20 ? "할인 큼" : "정보";
    }
  };
  panel.addEventListener("input", (e) => {
    const r = e.target.closest("[data-mkt-range]");
    if (!r) return;
    card.calc[r.dataset.mktRange] = Number(r.value);
    const text = wonKo(r.value);
    panel.querySelector(`[data-mkt-out="${r.dataset.mktRange}"]`).textContent = text;
    r.setAttribute("aria-valuetext", text);
    clearTimeout(card.timer);
    card.timer = setTimeout(recalc, 150);
  });
  recalc();
}
// '이 조건으로 쿠폰 글 만들기' (슬라이더 값으로 generate). 새 글은 그 아래, 이 카드를 승인할 때 같이 승인된다
async function mktCouponGen(card, button) {
  if (card.approved) return;
  const out = card.el.querySelector("[data-mkt-coupon-out]");
  await mktCardWork(card, button, "쿠폰 글을 만들고 있어요…", async () => {
    const g = await mktPost("generate", { state: card.flow, coupon_override: { ...card.calc } });
    if (!g.text) { mktCardMsg(card, "이 조건으로는 쿠폰 글을 만들지 못했어요.", true); return; }
    if (g.demo) { mkt.demoSeen = true; mktNotice(); }
    card.drafts.delete("coupon_regen");
    out.innerHTML = mktDraftHtml(card, "coupon_regen", g.text, "쿠폰 글", mktDraftLabel("쿠폰 글", g.demo === true));
    mktRegister(card, out);
    mktCardMsg(card, "이 조건으로 쿠폰 글을 만들었어요. 승인하면 같이 승인돼요.");
  });
}
// 쿠폰 결과 확인의 '다음 쿠폰 조건' → generate (할인액은 서버 코드가 정한 값)
async function mktNextCoupon(card, button) {
  if (card.approved) return;
  const out = card.el.querySelector("[data-mkt-next-out]");
  await mktCardWork(card, button, "쿠폰 글을 만들고 있어요…", async () => {
    const g = await mktPost("generate", { state: card.flow });
    if (g.demo) { mkt.demoSeen = true; mktNotice(); }
    card.drafts.delete("next_coupon");
    out.innerHTML = (g.text ? mktDraftHtml(card, "next_coupon", g.text, "쿠폰 글", mktDraftLabel("쿠폰 글", g.demo === true)) : "")
      + (g.coupon ? mktCouponHtml(card, { ...g.coupon, calc_input: null }) : "");
    mktRegister(card, out);
    mktCardMsg(card, g.text ? "다음 쿠폰 글을 만들었어요. 승인하면 같이 승인돼요." : "쿠폰 글을 만들지 못했어요.", !g.text);
  });
}
// 카드 안 버튼 하나의 일: 버튼을 잠그고 진행 글을 보이고, 실패하면 카드 안에 안내 (화면의 다른 곳은 그대로)
async function mktCardWork(card, button, text, work) {
  if (card.busy) return;
  card.busy = true;
  const old = button.textContent;
  button.disabled = true; button.textContent = "만드는 중…";
  mktCardMsg(card, text);
  try { await work(); }
  catch (e) { if (card.el.isConnected) mktCardMsg(card, e.message, true); }
  finally {
    card.busy = false;
    if (button.isConnected) { button.disabled = card.approved; button.textContent = old; }
  }
}

// 추천 아이디어: 목표 하나 안에서 순서대로 돈다(next-idea, 무작위 아님). 질문이 필요한 아이디어는 [해 볼게요]를 누른 뒤에만 묻고(idea-try),
// 조건이 안 맞으면(skip) 다음 아이디어로 넘어간다. 아이디어 글은 서버의 정해 둔 틀이다 (AI 아님)
function mktIdea(card, idea, index) {
  const box = card.el.querySelector("[data-mkt-idea]");
  if (!box) return;
  card.idea = idea; card.ideaIndex = index;
  [...card.drafts.keys()].filter((k) => k.startsWith("idea_")).forEach((k) => card.drafts.delete(k));   // 지난 아이디어 글은 승인 대상에서 뺀다
  const story = idea.id === "story_link";
  box.innerHTML = `<div class="mkt-idea"><p class="mkt-idea-tag">추천 아이디어</p>
    <h3>${esc(idea.title)}</h3>${idea.why ? `<p class="mkt-idea-why">${esc(idea.why)}</p>` : ""}
    ${(idea.todos || []).length ? `<ul class="mkt-list">${idea.todos.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
    ${idea.draft && !idea.needs_question && !story ? mktDraftHtml(card, `idea_${idea.id}`, idea.draft, "아이디어 글", mktDraftLabel("아이디어 글", false, true)) : ""}
    <div class="mkt-q" data-mkt-idea-q></div>
    <div class="row">${story ? '<button type="button" data-mkt-idea-story>가게 이야기 글 만들기</button>'
      : idea.needs_question ? '<button type="button" data-mkt-idea-try>해 볼게요</button>' : ""}
      <button type="button" class="ghost" data-mkt-idea-next>다음 아이디어</button></div>
    <p class="small muted" data-mkt-idea-msg role="status"></p></div>`;
  mktRegister(card, box);
  box.onclick = (e) => {
    const b = e.target.closest("button");
    if (!b || b.disabled) return;
    if (b.hasAttribute("data-mkt-idea-next")) mktIdeaNext(card, b);
    else if (b.hasAttribute("data-mkt-idea-try")) mktIdeaAsk(card, b);
    else if (b.dataset.mktIdeaAnswer != null) mktIdeaTry(card, b.dataset.mktIdeaAnswer);
    else if (b.hasAttribute("data-mkt-idea-send")) mktIdeaTry(card, box.querySelector("[data-mkt-idea-input]")?.value.trim() || "");
    else if (b.hasAttribute("data-mkt-idea-story")) mktStoryLink(b);
  };
  box.onkeydown = (e) => {
    if (e.key === "Enter" && !e.isComposing && e.keyCode !== 229 && e.target.matches("[data-mkt-idea-input]")) { e.preventDefault(); mktIdeaTry(card, e.target.value.trim()); }
  };
}
const mktIdeaMsg = (card, text) => { const el = card.el.querySelector("[data-mkt-idea-msg]"); if (el) el.textContent = text || ""; };
async function mktIdeaNext(card, button) {
  button.disabled = true;
  try {
    const r = await mktPost("next-idea", { state: card.flow, current_index: card.ideaIndex });
    if (r.idea) { mktIdea(card, r.idea, r.idea_index ?? card.ideaIndex); card.el.querySelector("[data-mkt-idea] h3")?.setAttribute("tabindex", "-1"); card.el.querySelector("[data-mkt-idea] h3")?.focus(); }
    else mktIdeaMsg(card, "다른 아이디어가 없어요.");
  } catch (e) { mktIdeaMsg(card, e.message); }
  finally { if (button.isConnected) button.disabled = false; }
}
function mktIdeaAsk(card, button) {
  const q = card.el.querySelector("[data-mkt-idea-q]"), idea = card.idea, n = card.n;
  button.remove();
  q.innerHTML = `<p class="mkt-idea-why">${esc(idea.question || "")}</p>${idea.question_type === "bool"
    ? '<div class="row"><button type="button" class="chip" data-mkt-idea-answer="예">예</button><button type="button" class="chip" data-mkt-idea-answer="아니요">아니요</button></div>'
    : `<div class="mkt-input"><label class="sr" for="mkt-idea-${n}">아이디어 질문에 답하기</label><input id="mkt-idea-${n}" type="text" maxlength="60" autocomplete="off" data-mkt-idea-input placeholder="답을 입력해 주세요"><button type="button" class="primary" data-mkt-idea-send>보내기</button></div>`}`;
  q.querySelector("button, input")?.focus();
}
async function mktIdeaTry(card, answer) {
  const q = card.el.querySelector("[data-mkt-idea-q]"), idea = card.idea;
  q.querySelectorAll("button, input").forEach((x) => (x.disabled = true));
  mktIdeaMsg(card, "아이디어를 글로 만들고 있어요…");
  try {
    const r = await mktPost("idea-try", { state: card.flow, idea_id: idea.id, index: card.ideaIndex, answer });
    if (r.skip) {
      mktIdeaMsg(card, "이 아이디어는 지금은 건너뛸게요.");
      const next = card.el.querySelector("[data-mkt-idea-next]");
      if (next) await mktIdeaNext(card, next);
      return;
    }
    q.innerHTML = r.draft ? mktDraftHtml(card, `idea_${idea.id}`, r.draft, "아이디어 글", mktDraftLabel("아이디어 글", false, true)) : "";
    mktRegister(card, q);
    mktIdeaMsg(card, r.draft ? "아이디어 글을 만들었어요. 카드를 승인하면 같이 승인돼요." : "");
  } catch (e) {
    q.querySelectorAll("button, input").forEach((x) => (x.disabled = false));
    mktIdeaMsg(card, e.message);
  }
}
// '가게 이야기 글 만들기' 아이디어: 새 설문(가게 이야기 글)으로 이어서 묻는다
async function mktStoryLink(button) {
  if (mkt.busy) return;
  button.disabled = true;
  const gen = mkt.gen;
  mktUser("가게 이야기 글 만들기");
  mktBusy("가게 이야기 질문을 준비하고 있어요");
  try {
    const base = await mktPost("step", { state: null, answer: null });
    const r = await mktPost("step", { state: base.state, answer: "가게 이야기 글" });
    if (gen !== mkt.gen) return;
    mktBusy("");
    mkt.flow = r.state;
    (r.bot_messages || []).forEach(mktBot);
    mktPrompt(r);
  } catch (e) {
    if (gen !== mkt.gen) return;
    mktBusy("");
    button.disabled = false;
    mktErr(e.message);
  }
}

// 승인: 이 카드의 글(고친 글 포함)을 모두 보낸다. 마케팅 서비스가 고친 글을 다시 점검해 걸리면(edit_failed) 그 글 아래에 빨간 안내.
// 성공하면 서버가 이 방문자의 승인 기록에도 남기고(recorded) '처리 완료'에 보인다. 공지 카드면 '2주 뒤 확인해 보기'를 카드 안에 둔다
async function mktApprove(card, button) {
  if (card.approved || card.replaced || card.busy || mkt.busy) return;
  const gen = mkt.gen, edited = {}, approval = [];
  card.drafts.forEach((d, key) => {
    const text = d.box.value;
    if (text.trim() !== d.original.trim()) edited[key] = text;
    approval.push({ draft_id: `${card.run}-${mktKey(key)}`, text, original: d.original, kind: d.kind, title: card.title });
  });
  card.busy = true;
  button.disabled = true;
  card.el.querySelectorAll(".mkt-draft [data-mkt-fail]").forEach((f) => { f.hidden = true; f.replaceChildren(); });
  mktCardMsg(card, "승인하고 있어요…");
  mktBusy("승인하고 있어요");
  let a;
  try {
    a = await mktPost("approve", { state: card.flow, draft_id: null, session_id: card.session, edited_texts: edited, approval });
  } catch (e) {
    card.busy = false;
    if (gen !== mkt.gen) return;
    mktBusy("");
    button.disabled = false;
    mktCardMsg(card, `승인하지 못했어요: ${e.message}`, true);
    return;
  }
  card.busy = false;
  if (gen !== mkt.gen) return;
  mktBusy("");
  if (a.edit_failed) {
    let first = null;
    Object.entries(a.edit_failed).forEach(([key, reasons]) => {
      const wrap = card.el.querySelector(`.mkt-draft[data-mkt-draft="${CSS.escape(key)}"]`);
      if (!wrap) return;
      const ul = wrap.querySelector("[data-mkt-fail]");
      ul.innerHTML = (Array.isArray(reasons) ? reasons : [reasons]).map((r) => `<li><b>점검 실패</b> ${esc(r)}</li>`).join("");
      ul.hidden = false;
      first = first || wrap.querySelector("textarea");
    });
    button.disabled = false;
    mktCardMsg(card, "고친 글이 점검에 걸렸어요. 빨간 안내를 보고 글을 고친 뒤 다시 승인해 주세요.", true);
    first?.focus();
    return;
  }
  card.approved = true;
  card.el.classList.add("approved");
  card.el.querySelector("[data-mkt-approved]").hidden = false;
  button.textContent = "승인함";
  card.el.querySelectorAll("[data-mkt-rewrite], [data-mkt-coupon-gen], [data-mkt-next-coupon], [data-mkt-idea-try], [data-mkt-idea-next]").forEach((x) => (x.disabled = true));
  card.el.querySelectorAll("textarea[data-mkt-text]").forEach((x) => (x.readOnly = true));
  const recorded = Array.isArray(a.recorded) ? a.recorded : [];
  recorded.forEach((r) => {
    state.approvedLog = state.approvedLog.filter((x) => x.id !== r.draft_id);
    state.approvedLog.push({ id: r.draft_id, at: r.approved_at || new Date().toISOString(), edited: !!r.edited, name: r.kind, card: "맞춤 마케팅", mkt: true });
  });
  card.el.querySelector("[data-mkt-done]").hidden = !recorded.length;
  mktCardMsg(card, `승인했어요.${recorded.length ? ` '처리 완료'에 글 ${recorded.length}건을 기록했어요.` : ""}${a.record_warning ? ` ${a.record_warning}` : ""} 게시는 복사해서 직접 올려요.`);
  if ((card.data.steps || []).some((s) => s.generator === "prevention_notice")) mktNoticeOffer(card);
  mkt.flow = a.state || mkt.flow;
  if (a.follow_up) {
    (a.bot_messages || []).forEach(mktBot);
    mktPrompt(a);
  } else {
    mktBot("여기까지 도와드릴게요. 감사합니다! 다른 것도 해 보려면 아래 ‘처음부터’를 눌러 주세요.");
    $("mkt-options").replaceChildren();
  }
}
// 같은 답으로 결과를 다시 받는다 (글을 새로 씀). 새 카드는 아래에, 예전 카드는 그대로 남는다
async function mktRewrite(card, button) {
  if (mkt.busy || card.approved || card.busy) return;
  button.disabled = true;
  mktUser("다시 쓰기");
  const fresh = await mktDecide(card.flow, "같은 답으로 글을 다시 쓰고 있어요");
  if (!fresh) { if (button.isConnected) button.disabled = false; return; }
  // 새로 쓴 카드가 생기면 예전 카드는 승인하지 못하게 (같은 답의 글이 두 번 승인되지 않게)
  card.el.querySelectorAll("[data-mkt-approve], [data-mkt-coupon-gen], [data-mkt-next-coupon]").forEach((x) => (x.disabled = true));
  card.replaced = true;
  mktCardMsg(card, "새로 쓴 결과가 아래에 있어요. 이 카드는 승인할 수 없어요.");
}
// 공지(재발 방지 공지)를 승인한 카드: 2주 뒤 같은 불만이 줄었는지 (데모: 저장된 리뷰 날짜로 서버 코드가 셈). 줄었으면 개선 소식 글
// (원본은 재주문 쿠폰 질문이 이어지면 이 버튼이 나오지 않아 닿을 길이 없었다. 그래서 공지 카드 안에 둔다)
function mktNoticeOffer(card) {
  const box = card.el.querySelector("[data-mkt-follow]");
  box.innerHTML = `<div class="mkt-follow"><p class="mkt-box-title">2주 뒤 개선 소식</p>
    <p class="small muted">공지를 올리고 2주 뒤에 같은 불만 리뷰가 줄었는지 세어 봐요. 지금은 데모라 저장된 리뷰 날짜로 셈해요.</p>
    <div class="row"><button type="button" data-mkt-notice>2주 뒤 확인해 보기</button></div><div data-mkt-notice-out></div></div>`;
}
async function mktNoticeFollow(card, button) {
  const out = card.el.querySelector("[data-mkt-notice-out]");
  button.disabled = true;
  try {
    const f = await mktPost("notice-followup", { state: card.flow });
    const pend = card.pending.length;
    out.innerHTML = `<p class="mkt-line">공지 전후 불만 리뷰 수: 이전 ${esc(f.window_days)}일 ${esc(f.before)}건 → 이후 ${esc(f.window_days)}일 <b>${esc(f.after)}건</b> (${esc(f.basis || "리뷰 기준")})</p>
      ${f.improved && f.text ? mktDraftHtml(card, "notice_followup", f.text, "개선 소식", mktDraftLabel("개선 소식", false, true)) : f.todo ? `<p class="mkt-line">${esc(f.todo)}</p>` : ""}`;
    card.pending.splice(pend);   // 승인이 끝난 카드라 이 글은 승인 대상이 아니다 (복사해서 씀)
    button.remove();
  } catch (e) {
    button.disabled = false;
    out.innerHTML = `<p class="small mkt-card-msg bad">${esc(e.message)}</p>`;
  }
}

// ── 마케팅 보고서 탭 (주간·월간) ──
function mktTab(name, focus = false) {
  mkt.tab = name;
  MKT_TABS.forEach((t) => {
    const tab = $("mkt-tab-" + t), on = t === name;
    tab.setAttribute("aria-selected", String(on));
    tab.tabIndex = on ? 0 : -1;
    if (on && focus) tab.focus();
  });
  $("mkt-chat").hidden = name !== "chat";
  $("mkt-report-panel").hidden = name !== "report";
  if (name === "report") mktReport(mkt.period);
}
function mktTabKey(e) {
  const i = MKT_TABS.indexOf(e.currentTarget.dataset.mktTab);
  const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: MKT_TABS.length - 1 }[e.key];
  if (next === undefined) return;
  e.preventDefault();
  mktTab(MKT_TABS[(next + MKT_TABS.length) % MKT_TABS.length], true);
}
function mktReportState(msg, bad = false) {
  const el = $("mkt-report-state");
  el.hidden = !msg;
  el.textContent = msg || "";
  el.classList.toggle("bad", bad);
}
// 보고서는 기록을 코드로 센 것이다 (AI 호출 없음). 열 때마다 새로 부른다 (방금 승인한 것도 세게)
async function mktReport(period) {
  mkt.period = period;
  document.querySelectorAll("[data-mkt-period]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mktPeriod === period)));
  const gen = ++mkt.reportGen;
  mktReportState("불러오는 중…");
  try {
    const d = await mktApi(`report?period=${encodeURIComponent(period)}`);
    if (gen !== mkt.reportGen) return;
    mktReportState("");
    mktReportDraw(d, period);
  } catch (e) {
    if (gen !== mkt.reportGen) return;
    $("mkt-report").innerHTML = "";
    mktReportState(e.message, true);
  }
}
function mktReportDraw(d, period) {
  const L = MKT_PERIOD[d.period?.kind] || MKT_PERIOD[period];
  const tiles = [];
  const approved = Object.entries(d.activity?.approved || {});
  if (approved.length) tiles.push([`${approved.reduce((n, [, v]) => n + Number(v || 0), 0)}건`, `승인한 글 (${approved.map(([k, v]) => `${k} ${v}`).join(" · ")})`]);
  const c = d.cost?.coupon;
  if (c) {
    if (c.usage_rate != null) tiles.push([`${Math.round(c.usage_rate * 100)}%`, `쿠폰 사용률 (${c.issued}장 중 ${c.used}장)`]);
    tiles.push([wonKo(c.discount_spent), "할인에 쓴 돈"]);
  }
  (d.fixed || []).forEach((f) => tiles.push([`${f.before_14d}건 → ${f.after_14d}건`, f.tile_label || `${f.complaint} 불만 재발`]));
  const tried = d.activity?.ideas_tried || [], ads = d.cost?.ads || [], next = d.next || [];
  const scale = Math.max(1, ...ads.flatMap((a) => [Number(a.cost_per_order) || 0, Number(a.profit_per_order) || 0]));
  const pct = (v) => Math.max(0, Math.min(100, Math.round(((Number(v) || 0) / scale) * 100)));
  const until = String(d.period?.until || "").slice(0, 10);
  $("mkt-report").innerHTML = `<article class="mkt-card mkt-report-card" aria-labelledby="mkt-report-title">
    <div class="mkt-card-head"><h2 id="mkt-report-title">${esc(L.now)} 마케팅 보고서</h2>${d.demo ? '<span class="badge warn">데모 기록</span>' : ""}</div>
    <p class="small muted">${esc(d.period?.start || "")} ~ ${esc(until)} · 기록을 코드로 셌어요 (AI 호출 없음)</p>
    ${d.demo ? '<p class="mkt-demo">아직 이 가게에 쌓인 마케팅 기록이 없어 예시로 넣어 둔 데모 기록을 보여 줘요. 실제 우리 가게 기록이 아니에요.</p>' : ""}
    ${tiles.length ? mktTilesHtml(tiles) : ""}
    ${tried.length ? `<div class="mkt-box"><p class="mkt-box-title">해 본 아이디어</p><ul class="mkt-list">${tried.map((t) => `<li>${esc(t)}</li>`).join("")}</ul></div>` : ""}
    ${ads.length ? `<div class="mkt-box"><p class="mkt-box-title">광고 앱별 판정 (${esc(L.prev)} → ${esc(L.now)})</p><div class="mkt-bars">${ads.map((a) => {
      const v = MKT_VERDICT[a.verdict] || ["ok"];
      return `<div class="mkt-bar-row"><p class="mkt-bar-name">${esc(a.label)} <span class="small muted">${esc(L.prev)} ${esc(a.prev_verdict || "기록 없음")} → ${esc(L.now)} ${esc(a.verdict || "–")}</span></p>
        <div class="mkt-bar"><span class="mkt-bar-track" aria-hidden="true"><i class="${esc(v[0])}" style="width:${pct(a.cost_per_order)}%"></i></span><span class="small">건당 광고비 ${esc(wonKo(a.cost_per_order))}</span></div>
        ${a.profit_per_order != null ? `<div class="mkt-bar"><span class="mkt-bar-track" aria-hidden="true"><i class="profit" style="width:${pct(a.profit_per_order)}%"></i></span><span class="small">건당 이익 ${esc(wonKo(a.profit_per_order))}</span></div>` : ""}</div>`;
    }).join("")}</div></div>` : ""}
    ${next.length ? `<div class="mkt-box dashed"><p class="mkt-box-title">${esc(L.next)} 할 것</p><ul class="mkt-list">${next.map((n) => `<li><b>${esc(n.title)}</b> — ${esc(n.why)}</li>`).join("")}</ul></div>` : ""}
    ${!tiles.length && !tried.length && !ads.length && !next.length ? '<p class="muted">이 기간에 쌓인 기록이 아직 없어요.</p>' : ""}
  </article>`;
}

// '처음부터' (이 화면): 대화만 처음으로. 승인 기록·보고서 기록은 그대로
function mktRestartChat() {
  mktTab("chat");
  mktFirst(++mkt.gen, true);
}
// '처음부터 다시' (처리 완료 화면, restart): 대화·결과 카드·보고서를 비우고, 다음에 열 때 처음부터 시작한다.
// cleared = 서버의 marketing_cleared (false 면 기록을 못 지운 것 → 이 화면 안에만 안내)
function mktReset(cleared) {
  mkt.gen++;
  mkt.reportGen++;
  mkt.flow = null; mkt.prompt = null; mkt.started = false; mkt.ready = false; mkt.demoSeen = false;
  mktBusy("");
  $("mkt-log").replaceChildren();
  $("mkt-options").replaceChildren();
  $("mkt-report").replaceChildren();
  mktReportState("");
  mktErr("");
  mkt.clearNote = cleared === false ? "‘처음부터 다시’ 때 맞춤 마케팅 기록은 지우지 못했어요. 마케팅 보고서에 예전 기록이 남아 있을 수 있어요." : "";
  mkt.tab = "chat";
  mktTab("chat");
  mktNotice();
  if (currentRoute() === "marketing") mktOpen();
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
  atHome: false,              // 지금 분석 조건이 우리 가게 기본 조건과 같은지 (서버가 준 conditions.is_store_default 가 true 일 때만)
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
// 분기 코드(20262 · 2026Q2)를 '2026년 2분기'로. 서버(assistant_proxy.py 의 QUARTER_IN_TEXT)와 같은 정규식이다 (시험이 글자 그대로 같은지 확인).
// 서버가 먼저 바꿔 주지만, 서버가 놓친 글자도 날것으로 보이지 않게 화면에서 한 번 더 본다. 금액·개수(20262원, 20,262, 120262)는 그대로 둔다
const CHAT_QUARTER = /(^|[^0-9A-Za-z_,.\-])(20[0-9]{2})(?:Q([1-4])(?![0-9A-Za-z])|([1-4])(?![0-9A-Za-z_\-]|[,.][0-9]|원|건|명|개|곳|호|번|위|배|회|세|살|대|가구|만|억|천|조|년|월|일|시|초|분(?!기)|평|점|%|퍼센트)(?: ?분기)?)/g;
const chatQuarter = (t) => (typeof t === "string" ? t.replace(CHAT_QUARTER, (_, pre, y, q, n) => `${pre}${y}년 ${q || n}분기`) : t);
// 조건 줄의 분기: 이름이 코드 그대로(20262)이면 바꾸고, 이름이 없으면 코드(period)로 만든다
const chatPeriod = (c) => { const p = String(c.period_label || c.period || ""); return /^[0-9]{4}[1-4]$/.test(p) ? `${p.slice(0, 4)}년 ${p[4]}분기` : chatQuarter(p); };
const chatCondText = (c) => (c ? [c.area_name ? `${c.area_name} 상권` : null, c.industry_name, chatPeriod(c)].filter(Boolean).join(" · ") : "");
const chatId = () => "web-" + (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
const chatSuggest = (reply) => (Array.isArray(reply?.suggestions) ? reply.suggestions : []).filter((s) => typeof s === "string" && s.trim()).map(chatQuarter).slice(0, 3);
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
  $("assistant-home").disabled = off || chat.atHome;   // 이미 우리 가게 기본 조건이면 누를 것이 없다
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

// '우리 가게 조건으로' 버튼: 지금 조건이 우리 가게 기본 조건이면 누를 수 없는 '우리 가게 기준 적용 중', 다른 상권·업종·분기를 보고 있으면 되돌리기 버튼
function chatHomeButton() {
  const b = $("assistant-home");
  b.textContent = chat.atHome ? "우리 가게 기준 적용 중" : "우리 가게 조건으로";
  b.classList.toggle("on", chat.atHome);
  b.disabled = chat.atHome || !chat.ready || chat.busy;
}
// 같은지는 서버(프록시)만 판단한다. 값이 없으면(기본 조건이 없는 가게 등) 버튼은 누를 수 있는 채로 둔다
function chatConditions(c) {
  const text = chatCondText(c);
  $("assistant-cond").hidden = !text;
  $("assistant-cond-text").textContent = text;
  chat.atHome = !!c && c.is_store_default === true;
  chatHomeButton();
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
    if (c.text) li.append(mk("p", "ev-text", chatQuarter(c.text)));
    const nums = (Array.isArray(c.values) ? c.values : []).filter((v) => v && typeof v.value === "number");
    if (nums.length) {
      const table = mk("table", "ev-table");
      const thead = mk("thead", "sr"), tr0 = mk("tr");
      ["항목", "값", "비중"].forEach((t) => { const th = mk("th", "", t); th.scope = "col"; tr0.append(th); });
      thead.append(tr0);
      const tbody = mk("tbody");
      nums.slice(0, 12).forEach((v) => {
        const tr = mk("tr"), th = mk("th", "", chatQuarter(v.group ? `${v.group} ${v.label}` : v.label));
        th.scope = "row";
        tr.append(th, mk("td", "", chatValue(v.value, v.unit)), mk("td", "share", typeof v.share_percent === "number" ? chatValue(v.share_percent, "%") : ""));
        tbody.append(tr);
      });
      table.append(thead, tbody);
      li.append(table);
      if (nums.length > 12) li.append(mk("p", "ev-more", `숫자 ${nums.length}개 중 12개만 보여요.`));
    }
    const warnings = (Array.isArray(c.warnings) ? c.warnings : []).filter((w) => typeof w === "string" && w);
    if (warnings.length) { const ul = mk("ul", "ev-warn"); warnings.forEach((w) => ul.append(mk("li", "", chatQuarter(w)))); li.append(ul); }
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
    if (m.index > last) into.append(chatQuarter(line.slice(last, m.index)));
    into.append(cite(m[1]) || m[0]);
    last = m.index + m[0].length;
  }
  if (last < line.length) into.append(chatQuarter(line.slice(last)));
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
      const b = mk("button", "pick", chatQuarter(a.label));
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
    notes.forEach((n) => ul.append(mk("li", "", chatQuarter(n))));
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
      chatUser(picked ? `선택: ${chatQuarter(picked.label)}` : "선택했어요");
      const b = picked && prevMsg && [...prevMsg.querySelectorAll(".pick")].find((x) => x.textContent === chatQuarter(picked.label));
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
  const mine = chatUser(`선택: ${chatQuarter(action.label)}`);
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
    // 누르는 동안 막혀서 잃은 포커스. 맞춘 뒤 버튼이 '적용 중'으로 막히면 입력칸으로 보낸다
    if (document.activeElement === document.body && !$("assistant").hidden && !$("assistant-cond").hidden) { if (b.disabled) chatFocus(); else b.focus(); }
    if (done) {
      chatStatus("우리 가게 조건으로 맞췄어요", false, true);
      // 서버가 같은지 알려 주지 않는 가게에서는 버튼 글자가 그대로라, 눌렀다는 것을 잠깐 알린다 ('적용 중'으로 바뀌면 그 글자가 알림)
      if (!chat.atHome) { b.textContent = "✓ 맞췄어요"; setTimeout(chatHomeButton, 2000); }
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
  } catch (e) { showAlert(e.message); $("start").textContent = "불러오지 못했어요"; anStatus(`리뷰 분석을 불러오지 못했어요: ${e.message}`, true); state.bootError = e.message; }
  state.booted = true;   // 종합 리포트의 상권·마케팅 요약이 '불러오는 중'과 '못 불러옴'을 가린다
  setTopH();
  route();
}

applyTheme(); // ?theme=light 는 서버 응답을 기다리지 않고 바로
mountLater(); // 준비 중 메뉴·화면을 첫 route() 전에
applyMenu();  // 왼쪽 메뉴: 넓은 폭은 기억한 상태로, 761~1024px 은 접힌 채로 (첫 화면 전에)

// 왼쪽 메뉴 접기
$("menu-toggle").addEventListener("click", toggleMenu);
// 창 폭이 구간(760px 이하 · 761~1024px · 1025px 이상)을 넘으면 그 구간의 처음 상태로
window.addEventListener("resize", () => { if (menuBandNow() !== menuBand) applyMenu(); });
if (window.ResizeObserver) new ResizeObserver(setTopH).observe(document.querySelector(".top"));   // 상단 바가 두 줄이 되면 덮는 메뉴도 그 아래로
// 덮는 메뉴(761~1024px)가 열려 있는 동안: 바깥(어두운 배경)이나 메뉴 항목을 누르면 닫는다
document.addEventListener("click", (e) => {
  if (!menuOverlayOpen() || e.target.closest("#menu-toggle")) return;
  if (e.target.closest(".side") && !e.target.closest(".side a[href]")) return;   // 메뉴 안의 빈 곳
  closeMenuOverlay();
});
// Esc 로 닫고(캡처 단계에서 받아 서랍의 Esc 처리보다 먼저, 서랍은 그대로 둔다), Tab 은 토글 버튼과 메뉴 항목 안에서만 돈다
document.addEventListener("keydown", (e) => {
  if (!menuOverlayOpen() || e.isComposing) return;
  if (e.key === "Escape") { e.stopPropagation(); closeMenuOverlay(); return; }
  if (e.key !== "Tab") return;
  const stops = [$("menu-toggle"), ...document.querySelectorAll(".side a[href]")].filter((x) => x.getClientRects().length);
  const i = stops.indexOf(document.activeElement);
  e.preventDefault();
  stops[e.shiftKey ? (i <= 0 ? stops.length - 1 : i - 1) : (i + 1) % stops.length].focus();
}, true);

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
// 캡처로 넣기: 버튼으로 파일 고르기, 또는 칸에 끌어 놓기
$("cap-choose").addEventListener("click", () => $("cap-file").click());
$("cap-file").addEventListener("change", (e) => { capPick(e.target.files[0]); e.target.value = ""; });
$("cap-send").addEventListener("click", capRead);
$("cap-save").addEventListener("click", capSave);
$("cap-list").addEventListener("change", (e) => { if (e.target.matches("[data-cap-pick]")) capCount(); });
$("cap").addEventListener("dragover", (e) => { e.preventDefault(); $("cap").classList.add("drop"); });
$("cap").addEventListener("dragleave", () => $("cap").classList.remove("drop"));
$("cap").addEventListener("drop", (e) => { e.preventDefault(); $("cap").classList.remove("drop"); if (!cap.busy) capPick(e.dataTransfer?.files?.[0]); });
// 종합 리포트
$("rp-reload").addEventListener("click", () => loadReport(true));
$("rp-month-prev").addEventListener("click", (e) => rpMoveMonth(-1, e.currentTarget));
$("rp-month-next").addEventListener("click", (e) => rpMoveMonth(1, e.currentTarget));
$("rp-pdf").addEventListener("click", rpPdf);
// 브라우저 메뉴(Ctrl+P)로 인쇄해도 같은 머리글·펼친 칸으로 나오게
window.addEventListener("beforeprint", () => { if (currentRoute() === "report") rpPrintPrep(); else rpMark(); });
window.addEventListener("afterprint", rpPrintDone);
document.querySelector('[data-view="report"]').addEventListener("click", (e) => {
  const b = e.target.closest("[data-rp-ask]");
  if (b) toggleAssistant(true, b);
});
// 맞춤 마케팅: 답 고르기 칸(보기·여러 개 고르기·입력·다시 시도), 탭(←/→/Home/End), 보고서 기간, 처음부터, 다시 확인
$("mkt-options").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b || b.disabled) return;
  if (b.hasAttribute("data-mkt-retry")) { const again = mkt.retry; mktErr(""); if (again) again(); return; }
  if (b.hasAttribute("data-mkt-goto-report")) { mktTab("report", true); return; }
  if (mkt.busy) return;
  const p = mkt.prompt || { opts: [] }, box = $("mkt-options");
  if (b.dataset.mktOpt != null) { const o = p.opts[Number(b.dataset.mktOpt)]; if (o) mktAnswer(o.label, o.label); }
  else if (b.dataset.mktMulti != null) {
    b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true"));
    box.querySelector("[data-mkt-next]").disabled = !box.querySelector('[data-mkt-multi][aria-pressed="true"]');
  } else if (b.hasAttribute("data-mkt-next")) {
    const picked = [...box.querySelectorAll('[data-mkt-multi][aria-pressed="true"]')].map((x) => p.opts[Number(x.dataset.mktMulti)]).filter(Boolean);
    if (picked.length) mktAnswer(picked.map((o) => o.value), picked.map((o) => o.label).join(", "));
  } else if (b.hasAttribute("data-mkt-skip")) mktAnswer("", "건너뛰기");
  else if (b.hasAttribute("data-mkt-send")) mktSend();
});
$("mkt-options").addEventListener("input", (e) => {
  if (e.target.id === "mkt-num") { const digits = e.target.value.replace(/[^0-9]/g, "").slice(0, 12); e.target.value = digits ? Number(digits).toLocaleString("ko-KR") : ""; }
  if (e.target.id === "mkt-free") $("mkt-options").querySelector("[data-mkt-count]").textContent = `${e.target.value.length}자`;
  const err = $("mkt-options").querySelector("[data-mkt-input-err]");
  if (err) err.textContent = "";
});
// 한 줄 입력칸의 Enter = 보내기 (한글 입력 중의 Enter 는 글자만 확정. 여러 줄 칸은 줄바꿈)
$("mkt-options").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.isComposing && e.keyCode !== 229 && e.target.matches("#mkt-num, #mkt-text")) { e.preventDefault(); mktSend(); }
});
document.querySelectorAll("[data-mkt-tab]").forEach((t) => {
  t.addEventListener("click", () => mktTab(t.dataset.mktTab));
  t.addEventListener("keydown", mktTabKey);
});
document.querySelectorAll("[data-mkt-period]").forEach((b) => b.addEventListener("click", () => mktReport(b.dataset.mktPeriod)));
$("mkt-restart").addEventListener("click", mktRestartChat);
$("mkt-retry").addEventListener("click", async () => {
  await mktStart();
  (mkt.ready ? $("mkt-options").querySelector("button") || $("mkt-tab-chat") : $("mkt-retry")).focus();
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
