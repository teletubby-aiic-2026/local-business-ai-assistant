// 텔레토비 AI 비서: 단계별 화면 (1 오늘 → 2 제안 → 3 초안 → 4 완료) + 분석. 외부 라이브러리 없이 동작 (발표장 오프라인 대비).
// 화면은 주소 해시로 바꾼다: #/today #/cards #/draft #/done #/analysis (재정비/05 UI 디자인 레퍼런스 15번, 박건영 결정 11/10)
// 화면마다 할 일은 하나. API·저장본은 그대로 쓴다 (/api/health, briefing, cards, cards/{id}/run, drafts/{id}/approve, approvals, reviews, c9/record).
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
const KPI_GEN = "prevention_notice";
const SOURCE_NAMES = { live: "실시간 HCX-005", seed: "저장본", replay: "발표 모드 저장본", "live+replay": "일부 실시간" };
const ROUTES = ["today", "cards", "draft", "done", "analysis"];

const state = {
  health: null, briefing: null, cards: [], results: {}, approved: new Set(), approvedLog: [],
  startedAt: null, timer: null, kpiAt: null, allAt: null, reviews: {}, pending: {},
  current: null,   // 초안 화면에 보이는 카드
  draftId: null,   // 초안 화면에 크게 보이는 글
};
// 출처 문자열에서 URL 을 떼어 화면에는 이름만 (URL 은 링크로)
const sourceUrl = (s) => (String(s || "").match(/https?:\/\/\S+/) || [""])[0];
const shortBasis = (t) => String(t || "").replace(/\s·\s*https?:\/\/\S+/g, "");
const isReplay = () => state.health && state.health.mode === "replay";

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
  document.querySelectorAll("[data-view]").forEach((v) => (v.hidden = v.dataset.view !== name));
  document.querySelectorAll(".menu a").forEach((a) => {
    if (a.dataset.route === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  window.scrollTo(0, 0);
  const h = document.querySelector(`[data-view="${name}"] h1`);
  if (h) h.focus({ preventScroll: true });
}
const go = (name) => { if (currentRoute() === name) route(); else location.hash = "#/" + name; };

// ── 테마 (재정비/05 검토 9번 결정 5: 발표 때는 라이트로 고정) ──────────────
// 발표 모드(replay)와 사다리(발표용 live 일부 실시간)는 운영체제가 다크여도 라이트로 보인다.
// 그 밖(mock·live)은 운영체제 설정을 따른다. 주소 뒤 ?theme=light 는 언제나 라이트, ?theme=auto 는 언제나 운영체제 설정.
function applyTheme(h) {
  const want = new URLSearchParams(location.search).get("theme");
  const presenting = h.mode === "replay" || Number(h.ladder) > 0;
  const light = want === "light" || (want !== "auto" && presenting);
  if (light) document.documentElement.dataset.theme = "light";
  else delete document.documentElement.dataset.theme;
}

// ── 맨 위 띠·바닥 ─────────────────────────────────────────────────
function renderHealth(h) {
  applyTheme(h);
  const chip = $("mode-chip");
  chip.textContent = h.mode_label + (h.ladder ? ` · 사다리 ${h.ladder}칸` : "");
  chip.className = "chip " + h.mode;
  const p = h.parts || {};
  const items = [`리뷰: ${p.reviews || "합성 데이터"}`, p.briefing, `카드: ${p.cards}`, `글 생성: ${p.generate}`];
  $("honesty").innerHTML = items.filter(Boolean).map((t) => `<span>${esc(t)}</span>`).join("");
  const problems = [...(h.blocking || [])];
  if ((h.dev_fake_snapshots || []).length) problems.unshift(`개발용 가짜 지표가 화면에 있어요 (${h.dev_fake_snapshots.join(", ")}). 실제 값이 아니니 발표에 쓰지 마세요.`);
  if (h.review_service && h.review_service.status === "down") problems.push(`리뷰 분석 서비스(${h.review_service.url})가 꺼져 있어요.`);
  showAlert(problems.join(" "));
  $("record").hidden = h.mode === "replay";
  const c = h.cache || {};
  $("foot-msg").textContent = c.exists ? `발표 모드 저장본: ${c.recorded_at} (${c.recorded_mode})` : "발표 모드 저장본 없음";
  // 분석 탭 → 리뷰 분석 화면(A)은 그 서비스가 떠 있을 때만 (발표 모드·라이브데모 링크에는 A가 없음)
  const rs = h.review_service || {};
  $("analysis-link").innerHTML = rs.status === "ok" && rs.url
    ? `<a href="${esc(rs.url)}/" target="_blank" rel="noopener">리뷰 분석 화면에서 리뷰 하나씩 보기 ↗</a>`
    : `<span class="muted">${h.mode === "replay" ? "발표 모드에서는 리뷰 분석 화면을 따로 띄우지 않아요. 아래가 저장된 같은 결과예요." : "리뷰 분석 화면에 연결할 수 없어요."}</span>`;
}

// ── 1 오늘 + 분석 (브리핑) ───────────────────────────────────────────
function renderBriefing(b) {
  $("store-name").textContent = `${b.store.name || ""} · ${b.store.business_type_name || ""}${b.store.area_name ? " · " + b.store.area_name + " 상권" : ""}`;
  const c = b.counts;
  // 숫자 하나: 리뷰 N건 중 불만 M건 (대본 0~5초)
  $("today-num").textContent = `${c.complaint_count}건`;
  $("today-num-label").textContent = `리뷰 ${c.review_count}건 중 불만`;
  // 오늘의 핵심 문제 (05 결정 1): 카드 ⓐ가 가리키는 묶음. 시간대는 불만이 몰린 구간(17~21시)만, 상권 지표의 17~24시와 섞지 않는다.
  const top = (b.groups || []).find((g) => g.issue_id === b.top_issue_id);
  $("hero-problem").textContent = top
    ? `${top.topic_name} ${top.review_count}건${top.is_repeated ? " 반복" : ""}${top.main_time_band ? ` · ${top.main_time_band}에 몰림` : ""}`
    : "오늘은 반복되는 불만이 없어요";
  $("today-source").textContent = `${b.period.start} ~ ${b.period.end} · 리뷰는 합성 데이터`;

  $("funnel").innerHTML = `
    <div class="box"><div class="n">${esc(c.review_count)}</div><div class="small muted">리뷰</div></div><span class="arrow">→</span>
    <div class="box"><div class="n">${esc(c.complaint_count)}</div><div class="small muted">불만</div></div><span class="arrow">→</span>
    <div class="box"><div class="n">${esc(c.group_count)}</div><div class="small muted">묶음 (반복 ${esc(b.repeated_count)})</div></div>
    <span class="arrow">+</span>
    <div class="box"><div class="n">${esc(c.single_complaint_count)}</div><div class="small muted">묶이지 않은 불만</div></div>
    <span class="small muted">${esc(b.period.start)} ~ ${esc(b.period.end)} · 리뷰는 합성 데이터</span>`;
  state.reviews = {};
  b.groups.forEach((g) => g.reviews.forEach((r) => (state.reviews[r.review_id] = r)));
  b.pasted.forEach((r) => (state.reviews[r.review_id] = r));
  $("groups").innerHTML = b.groups.map((g) => `
    <div class="group ${g.is_repeated ? "repeated" : ""}">
      <div class="group-head"><strong>${esc(g.topic_name)} ${esc(g.review_count)}건</strong>
        ${g.is_repeated ? '<span class="badge rep">반복</span>' : ""}
        ${g.main_time_band ? `<span class="badge">${esc(g.main_time_band)}에 몰림</span>` : ""}</div>
      ${g.reviews.map((r) => `<p class="quote">“${esc(r.text)}” <span class="small muted">${esc(r.channel || "")} · ${esc((r.created_at || "").slice(5, 16).replace("T", " "))}${r.input_method === "paste" ? " · 붙여넣음" : ""}</span></p>`).join("")}
    </div>`).join("") || '<p class="muted">묶음이 없어요.</p>';
  $("singles-title").textContent = `묶이지 않은 불만 ${b.single_complaints.length}건`;
  $("singles").innerHTML = b.single_complaints.map((s) => `<li class="quote">${esc((s.topic_names || []).join("·"))}: “${esc(s.quote)}”</li>`).join("");
  $("market").innerHTML = b.snapshots.map((s) => `
    <div class="metric ${s.dev_fake ? "fake" : ""}" data-snap="${esc(s.snapshot_id)}">
      <div class="small muted">${esc(s.area_name)} · ${esc(s.metric_name)} <span class="badge rep" data-used hidden>카드 ⓑ 근거</span></div>
      <div class="v">${s.value === null ? "자료 없음" : esc((s.value > 0 ? "+" : "") + Number(s.value).toFixed(2) + s.unit)}</div>
      <div class="small">${esc(shortBasis(s.basis_label))}${s.compared_with_quarter ? ` · 비교: ${esc(s.compared_with_quarter)}` : ""}
        ${sourceUrl(s.source) ? ` · <a href="${esc(sourceUrl(s.source))}" target="_blank" rel="noopener">원본</a>` : ""}</div>
      ${s.dev_fake ? '<div class="badge bad">개발용 가짜 값</div>' : ""}
    </div>`).join("") || '<p class="muted">상권 지표 파일이 아직 없어요 (C4).</p>';
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
  const used = new Set(data.cards.flatMap((p) => p.card.snapshot_ids || []));
  document.querySelectorAll("[data-snap]").forEach((el) => { el.querySelector("[data-used]").hidden = !used.has(el.dataset.snap); });
  document.querySelectorAll("[data-run]").forEach((b) => b.addEventListener("click", () => choose(b.dataset.run, b)));
}

// 불만 카드: 공지에 넣을 재발 방지 조치를 사장님이 고른다 (C6 목록, 고르지 않은 조치는 글에 못 들어감)
function measureBox(p) {
  const m = p.measures || {};
  if (!(m.options || []).length) return "";
  const on = new Set(m.default || []);
  return `<fieldset class="measures"${isReplay() ? " disabled" : ""}><legend class="small">공지에 넣을 재발 방지 조치${isReplay() ? " (발표 모드: 저장된 선택)" : ""}</legend>
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
const statusOf = (d) => state.approved.has(d.draft_id) ? ["ok", "승인됨"]
  : failedOf(d).length ? ["bad", "점검 실패"] : checksOf(d).length ? ["warn", "확인 필요"] : ["ok", "점검 통과"];
const draftsOf = (cardId) => [...((state.results[cardId] || {}).drafts || [])].sort(byGen);

function saveEdits() {
  // 다시 그리기 전에, 아직 승인하지 않은 글에서 고친 내용을 보존한다
  document.querySelectorAll("textarea[data-text]").forEach((box) => (state.pending[box.dataset.text] = box.value));
}

function renderDraft() {
  saveEdits();
  const el = $("draft");
  const made = state.cards.filter((p) => state.results[p.card.card_id]);
  if (!made.length) {
    el.innerHTML = `<h1 tabindex="-1">초안</h1><p class="muted">아직 만든 글이 없어요. 제안에서 카드를 하나 골라 주세요.</p>
      <a class="button primary" href="#/cards">제안 보기</a>`;
    return;
  }
  if (!state.results[state.current]) state.current = made[0].card.card_id;
  const p = state.cards.find((x) => x.card.card_id === state.current);
  const r = state.results[state.current];
  const drafts = draftsOf(state.current);
  if (!drafts.some((d) => d.draft_id === state.draftId)) state.draftId = (drafts.find((d) => !state.approved.has(d.draft_id)) || drafts[0] || {}).draft_id;
  const d = drafts.find((x) => x.draft_id === state.draftId);
  const agent = KIND_AGENT[p.card.kind];
  const review = d && d.target_review_id ? state.reviews[d.target_review_id] : null;
  const failed = d ? failedOf(d) : [], checks = d ? checksOf(d) : [];
  const approved = d && state.approved.has(d.draft_id);
  const [, statusText] = d ? statusOf(d) : [];
  // 발표 모드는 저장본을 그대로 돌려주므로 r.source 가 기록 당시 값(live)이다 → '발표 모드 저장본 · 기록 당시 …'로 밝힌다
  const srcName = SOURCE_NAMES[r.source] || r.source || "";
  const srcLabel = isReplay() ? `발표 모드 저장본 · 기록 당시 ${srcName}` : srcName;

  el.innerHTML = `
    <p class="eyebrow">${agent ? `<span class="agent">${esc(agent)}</span>` : ""}<span class="badge">${esc(srcLabel)}</span></p>
    <h1 tabindex="-1">${esc(p.title)}</h1>
    ${made.length > 1 ? `<div class="seg" role="group" aria-label="카드">${made.map((q, i) => `<button type="button" data-card="${esc(q.card.card_id)}"${q.card.card_id === state.current ? ' aria-current="true"' : ""}>${state.cards.indexOf(q) === 0 ? "ⓐ" : "ⓑ"} ${esc(KIND_NAMES[q.card.kind] || q.card.kind)}</button>`).join("")}</div>` : ""}
    ${r.source_note ? `<p class="small muted">${esc(r.source_note)}</p>` : ""}
    ${(r.chosen_measures || []).length ? `<p class="small">사장님이 고른 재발 방지 조치: ${r.chosen_measures.map((m) => esc(m.text)).join(", ")}</p>` : ""}
    <ol class="draft-list" aria-label="글 ${drafts.length}개">${drafts.map((x, i) => {
      const [tone, text] = statusOf(x);
      return `<li><button type="button" data-pick="${esc(x.draft_id)}"${x.draft_id === state.draftId ? ' aria-current="true"' : ""}>${i + 1}. ${esc(GEN_NAMES[x.generator] || x.generator)} <span class="st ${tone}">${text}</span></button></li>`;
    }).join("")}</ol>
    ${d ? `<article class="draft ${approved ? "approved" : ""}" id="draft-${esc(d.draft_id)}">
      <div class="draft-head"><h2>${esc(GEN_NAMES[d.generator] || d.generator)}</h2>
        ${failed.length ? `<span class="badge bad">점검 실패 ${failed.length}</span>` : ""}
        ${checks.length ? `<span class="badge warn">확인 필요 ${checks.length}</span>` : ""}
        ${failed.length || checks.length ? "" : '<span class="badge ok">점검 통과</span>'}
        ${approved ? '<span class="badge ok">승인됨</span>' : ""}</div>
      ${review ? `<p class="target small">손님 리뷰: “${esc(review.text)}”</p>` : ""}
      <label class="sr" for="text-${esc(d.draft_id)}">${esc(GEN_NAMES[d.generator] || d.generator)} 내용 (${esc(statusText)})</label>
      <textarea id="text-${esc(d.draft_id)}" rows="7" data-text="${esc(d.draft_id)}">${esc(state.pending[d.draft_id] ?? d.edited_text ?? d.text)}</textarea>
      ${failed.length ? `<ul class="issues bad">${failed.map((x) => `<li><b>점검 실패</b> ${esc(x)}</li>`).join("")}</ul>` : ""}
      ${checks.length ? `<ul class="issues">${checks.map((x) => `<li><b>확인 필요</b> ${esc(x)}</li>`).join("")}</ul>` : ""}
      <div class="row">
        <button type="button" class="primary" data-approve="${esc(d.draft_id)}">${approved ? "다시 승인" : "승인"}</button>
        <button type="button" data-copy="${esc(d.draft_id)}">복사</button>
        ${isReplay() ? "" : `<button type="button" class="ghost" data-rerun="${esc(state.current)}">다시 만들기</button>`}
      </div>
      <p class="small muted">${esc(d.model || "")}${d.elapsed_ms ? " · " + (d.elapsed_ms / 1000).toFixed(1) + "초" : ""}</p>
    </article>` : '<p class="muted">이 카드에서 만든 글이 없어요.</p>'}`;

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
    const card = state.cards.find((p) => (state.results[p.card.card_id]?.drafts || []).includes(d));
    state.approvedLog = state.approvedLog.filter((x) => x.id !== id);
    state.approvedLog.push({ id, at: entry.approved_at || new Date().toISOString(), edited: !!entry.edited,
      name: GEN_NAMES[d.generator] || d.generator, card: card ? card.title : "" });
    checkDone();
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
function kpiLines() {
  const lines = [];
  if (state.kpiAt) lines.push(`반복 원인 확인부터 재발 방지 공지 승인까지 ${words(state.kpiAt - state.startedAt)}`);
  if (state.allAt) lines.push(`글 ${Object.values(state.results).flatMap((r) => r.drafts || []).length}개 모두 승인까지 ${words(state.allAt - state.startedAt)}`);
  return lines;
}
function renderDone() {
  const el = $("done");
  const log = state.approvedLog;
  if (!log.length) {
    el.innerHTML = `<h1 tabindex="-1">완료</h1><p class="muted">아직 승인한 글이 없어요.</p>
      <a class="button primary" href="#/draft">초안으로</a>`;
    return;
  }
  const lines = kpiLines();
  const total = Object.values(state.results).flatMap((r) => r.drafts || []).length;
  el.innerHTML = `
    <h1 tabindex="-1">처리 완료</h1>
    ${lines.length ? `<p class="kpi">${lines.map(esc).join("<br>")}</p>` : `<p class="small muted">타이머는 1 오늘의 '무엇을 할까요?'부터 잽니다.</p>`}
    <p class="muted">승인한 글 ${log.length}개 / 만든 글 ${total}개 · 게시는 복사해서 직접 올려요</p>
    <ul class="plain log">${log.map((a) => `<li><span class="badge ok">승인됨</span> ${esc(a.name)} <span class="small muted">· ${esc(a.card)} · ${esc(String(a.at).slice(11, 19))}${a.edited ? " · 사장님이 고침" : ""}</span></li>`).join("")}</ul>
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

// 처음으로: 이 브라우저의 진행만 비운다 (서버 기록·저장본은 그대로)
function restart() {
  state.results = {}; state.approved.clear(); state.approvedLog = []; state.pending = {};
  state.current = null; state.draftId = null;
  clearInterval(state.timer); state.startedAt = null; state.kpiAt = null; state.allAt = null;
  $("timer").textContent = "00:00";
  renderCards({ cards: state.cards, no_card_b: $("no-card-b").textContent });
  go("today");
}

// ── 타이머 (C8 KPI: 반복 원인을 알아채고 재발 방지 조치를 내놓기까지) ──
// '무엇을 할까요?' → 재발 방지 공지 승인에서 멈춘다. 모든 글 승인까지 걸린 시간은 참고로 함께 적는다.
function fmt(ms) { const s = Math.floor(ms / 1000); return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; }
const words = (ms) => `${Math.floor(ms / 60000)}분 ${Math.floor((ms % 60000) / 1000)}초`;
function startTimer() {
  state.startedAt = Date.now(); state.kpiAt = null; state.allAt = null;
  clearInterval(state.timer);
  state.timer = setInterval(() => ($("timer").textContent = fmt(Date.now() - state.startedAt)), 500);
}
function checkDone() {
  if (!state.startedAt) return;
  const drafts = Object.values(state.results).flatMap((r) => r.drafts || []);
  const notice = drafts.find((d) => d.generator === KPI_GEN && state.approved.has(d.draft_id));
  if (notice && !state.kpiAt) {
    state.kpiAt = Date.now();
    clearInterval(state.timer);
    $("timer").textContent = fmt(state.kpiAt - state.startedAt);
  }
  if (drafts.length && drafts.every((d) => state.approved.has(d.draft_id))) state.allAt = state.allAt || Date.now();
}

// ── 분석: S2 붙여넣기 ─────────────────────────────────────────────
async function paste() {
  const text = $("paste-text").value.trim();
  if (!text) return;
  try {
    const r = await api("/api/reviews", { method: "POST", body: JSON.stringify({ text }) });
    const topics = (r.classification?.negative_topics || []).join(", ");
    $("paste-msg").textContent = `붙여 넣었어요. 분류: ${r.classification?.sentiment || "?"}${topics ? " · 불만 주제 " + topics : ""}`;
    $("paste-text").value = "";
    await refresh();
  } catch (e) { $("paste-msg").textContent = e.message; }
}
async function resetPaste() {
  try { await api("/api/reviews/pasted", { method: "DELETE" }); $("paste-msg").textContent = "붙여넣은 리뷰를 지웠어요."; await refresh(); }
  catch (e) { $("paste-msg").textContent = e.message; }
}

async function record() {
  try { const r = await api("/api/c9/record", { method: "POST" }); $("foot-msg").textContent = `발표 모드로 저장했어요: ${r.recorded_at} · 카드 ${r.cards}장 · 결과 ${r.results.length}개`; }
  catch (e) { showAlert(e.message); }
}

// ── 시작 ─────────────────────────────────────────────────────────
async function refresh() {
  state.briefing = await api("/api/briefing"); renderBriefing(state.briefing);
  const cards = await api("/api/cards");
  const before = state.cards.map((p) => p.card.card_id + p.card.review_ids + p.card.snapshot_ids).join();
  const after = cards.cards.map((p) => p.card.card_id + p.card.review_ids + p.card.snapshot_ids).join();
  if (before && before !== after) { state.results = {}; state.approved.clear(); state.approvedLog = []; state.pending = {}; state.current = null; state.draftId = null; }
  renderCards(cards);
}

async function boot() {
  try {
    state.health = await api("/api/health"); renderHealth(state.health);
    await refresh();
    $("start").disabled = false;
    $("start").textContent = "무엇을 할까요?";
  } catch (e) { showAlert(e.message); $("start").textContent = "불러오지 못했어요"; }
  route();
}

applyTheme({}); // ?theme=light 는 서버 응답을 기다리지 않고 바로 (발표 모드 판정은 /api/health 뒤)

$("start").addEventListener("click", () => { startTimer(); go("cards"); });
$("paste-send").addEventListener("click", paste);
$("paste-reset").addEventListener("click", resetPaste);
$("record").addEventListener("click", record);
window.addEventListener("hashchange", route);
route();
boot();
