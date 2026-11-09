// ①→④ 한 화면. 외부 라이브러리 없이 동작 (발표장 오프라인 대비).
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const GEN_NAMES = { reply_draft: "답글", prevention_notice: "재발 방지 공지", coupon_promo: "쿠폰 홍보글" };
const KIND_NAMES = { complaint: "불만 대응", promo: "쿠폰 홍보" };
// AI 직원 3명: ① 데이터 분석 비서, 카드 ⓐ·③ 고객 응대 비서, 카드 ⓑ 마케팅 에이전트
const KIND_AGENT = { complaint: "고객 응대 비서", promo: "마케팅 에이전트" };
// 재발 방지 공지를 답글보다 위에 (강조점: 다시 안 생기게 하는 조치가 먼저)
const GEN_ORDER = { prevention_notice: 0, coupon_promo: 1, reply_draft: 2 };
const byGen = (a, b) => (GEN_ORDER[a.generator] ?? 9) - (GEN_ORDER[b.generator] ?? 9);
const KPI_GEN = "prevention_notice";

const state = { health: null, briefing: null, cards: [], results: {}, approved: new Set(), startedAt: null, timer: null, reviews: {}, pending: {} };
// 출처 문자열에서 URL 을 떼어 화면에는 이름만 (URL 은 링크로)
const sourceName = (s) => String(s || "").split(/\s·\s(?=https?:)/)[0];
const sourceUrl = (s) => (String(s || "").match(/https?:\/\/\S+/) || [""])[0];
const shortBasis = (t) => String(t || "").replace(/\s·\s*https?:\/\/\S+/g, "");

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body?.error?.message || body?.detail?.[0]?.msg || `요청 실패 (${res.status})`);
  return body;
}

function showAlert(msg) { const el = $("alert"); el.hidden = !msg; el.textContent = msg || ""; }

// ── 맨 위 띠 ─────────────────────────────────────────────────────
function renderHealth(h) {
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
}

// ── ① 브리핑 ─────────────────────────────────────────────────────
function renderBriefing(b) {
  $("store-name").textContent = `${b.store.name || ""} · ${b.store.business_type_name || ""}${b.store.area_name ? " · " + b.store.area_name + " 상권" : ""}`;
  const c = b.counts;
  $("hero-title").textContent = `오늘까지 리뷰 ${c.review_count}건이 들어왔어요`;
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

// ── ② 카드 ───────────────────────────────────────────────────────
function renderCards(data) {
  state.cards = data.cards;
  $("cards").innerHTML = data.cards.map((p, i) => {
    const c = p.card;
    const label = c.kind === "complaint" ? "재발 방지 공지·답글 만들기" : "홍보글 만들기";
    return `<div class="card" id="card-${esc(c.card_id)}">
      <div class="kind">${i === 0 ? "ⓐ" : "ⓑ"} ${esc(KIND_NAMES[c.kind] || c.kind)}${KIND_AGENT[c.kind] ? ` <span class="agent">${esc(KIND_AGENT[c.kind])}</span>` : ""}</div>
      <strong>${esc(p.title)}</strong>
      <div class="reason">${esc(c.reason_text)}</div>
      <div class="ev">${p.evidence.map((e) => `<span title="${esc(e.note || "")}">${e.type === "review" ? "리뷰 " + esc(e.id) + ": “" + esc(e.text) + "”" : esc(e.text) + " · " + esc(shortBasis(e.basis))}</span>`).join("")}</div>
      <div class="small muted">이유 문장: ${esc(p.reason_source)}${(p.problems || []).length ? " · 검사기 지적 " + p.problems.length + "건" : ""}</div>
      <button type="button" class="primary" data-run="${esc(c.card_id)}">${label}</button>
    </div>`;
  }).join("") || '<p class="muted">오늘은 추천할 카드가 없어요.</p>';
  $("no-card-b").textContent = data.no_card_b || "";
  const used = new Set(data.cards.flatMap((p) => p.card.snapshot_ids || []));
  document.querySelectorAll("[data-snap]").forEach((el) => { el.querySelector("[data-used]").hidden = !used.has(el.dataset.snap); });
  document.querySelectorAll("[data-run]").forEach((b) => b.addEventListener("click", () => runCard(b.dataset.run, b)));
}

// ── ③④ 결과·승인 ─────────────────────────────────────────────────
async function runCard(cardId, button) {
  button.disabled = true; const old = button.textContent; button.textContent = "만드는 중…";
  try {
    const result = await api(`/api/cards/${encodeURIComponent(cardId)}/run`, { method: "POST" });
    state.results[cardId] = result;
    renderResults();
    $("step3").hidden = false; $("step3").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) { showAlert(e.message); }
  finally { button.disabled = false; button.textContent = old; }
}

function draftBlock(d) {
  const review = d.target_review_id ? state.reviews[d.target_review_id] : null;
  const issues = [...(d.failed_reasons || []), ...(d.needs_input || []), ...(d.c7_flags || [])];
  const approved = state.approved.has(d.draft_id);
  return `<div class="draft ${approved ? "approved" : ""}" id="draft-${esc(d.draft_id)}">
    <div class="draft-head"><strong>${esc(GEN_NAMES[d.generator] || d.generator)}</strong>
      ${review ? `<span class="small muted">→ “${esc(review.text)}”</span>` : ""}
      ${issues.length ? `<span class="badge warn">확인 필요 ${issues.length}</span>` : '<span class="badge ok">점검 통과</span>'}
      ${approved ? '<span class="badge ok">승인됨</span>' : ""}</div>
    <textarea rows="4" data-text="${esc(d.draft_id)}">${esc(state.pending[d.draft_id] ?? d.edited_text ?? d.text)}</textarea>
    ${issues.length ? `<ul class="issues">${issues.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    <div class="row">
      <button type="button" class="primary" data-approve="${esc(d.draft_id)}">${approved ? "다시 승인" : "승인"}</button>
      <button type="button" data-copy="${esc(d.draft_id)}">복사</button>
      <span class="small muted">${esc(d.model || "")}${d.elapsed_ms ? " · " + (d.elapsed_ms / 1000).toFixed(1) + "초" : ""}</span>
    </div></div>`;
}

function renderResults() {
  // 다시 그리기 전에, 아직 승인하지 않은 글에서 고친 내용을 보존한다
  document.querySelectorAll("textarea[data-text]").forEach((box) => (state.pending[box.dataset.text] = box.value));
  const blocks = state.cards.filter((p) => state.results[p.card.card_id]).map((p) => {
    const r = state.results[p.card.card_id];
    const src = { live: "실시간 HCX-005", seed: "저장본", replay: "발표 모드 저장본", "live+replay": "일부 실시간" }[r.source] || r.source || "";
    const agent = KIND_AGENT[p.card.kind];
    return `<div class="result"><div class="group-head">${agent ? `<span class="agent">${esc(agent)}</span>` : ""}<strong>${esc(p.title)}</strong><span class="badge">${esc(src)}</span>
      ${r.flagged_count ? `<span class="badge warn">확인 필요 글 ${r.flagged_count}개</span>` : ""}</div>
      ${r.source_note ? `<p class="small muted">${esc(r.source_note)}</p>` : ""}
      ${[...(r.drafts || [])].sort(byGen).map(draftBlock).join("")}</div>`;
  });
  $("results").innerHTML = blocks.join("");
  document.querySelectorAll("[data-approve]").forEach((b) => b.addEventListener("click", () => approve(b.dataset.approve)));
  document.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", () => copyDraft(b.dataset.copy, b)));
}

function findDraft(id) {
  for (const r of Object.values(state.results)) for (const d of r.drafts || []) if (d.draft_id === id) return d;
  return null;
}

async function approve(id) {
  const d = findDraft(id); const box = document.querySelector(`[data-text="${CSS.escape(id)}"]`);
  try {
    const entry = await api(`/api/drafts/${encodeURIComponent(id)}/approve`, { method: "POST", body: JSON.stringify({ text: box.value, original: d.text }) });
    d.edited_text = entry.edited ? box.value : null;
    state.approved.add(id);
    renderResults(); await loadApprovals(); checkDone();
  } catch (e) { showAlert(e.message); }
}

async function copyDraft(id, button) {
  const box = document.querySelector(`[data-text="${CSS.escape(id)}"]`);
  try { await navigator.clipboard.writeText(box.value); button.textContent = "복사됨"; }
  catch { box.select(); document.execCommand("copy"); button.textContent = "복사됨"; }
  setTimeout(() => (button.textContent = "복사"), 1500);
}

async function loadApprovals() {
  const data = await api("/api/approvals");
  $("log").hidden = !data.items.length;
  $("approvals").innerHTML = data.items.map((a) => `<li>${esc(a.approved_at.slice(11, 19))} · ${esc(a.draft_id)} 승인${a.edited ? " (사장님이 고침)" : ""}</li>`).join("");
}

// ── 타이머 (C8 KPI: 반복 원인을 알아채고 재발 방지 조치를 내놓기까지) ──
// 시작 버튼 → 재발 방지 공지 승인에서 멈춘다. 모든 글 승인까지 걸린 시간은 참고로 함께 적는다.
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
  const lines = [];
  if (state.kpiAt) lines.push(`반복 원인 확인부터 재발 방지 공지 승인까지 ${words(state.kpiAt - state.startedAt)}`);
  if (drafts.length && drafts.every((d) => state.approved.has(d.draft_id))) {
    state.allAt = state.allAt || Date.now();
    lines.push(`글 ${drafts.length}개 모두 승인까지 ${words(state.allAt - state.startedAt)}`);
  }
  if (lines.length) $("kpi").textContent = lines.join(" · ");
}

// ── S2 붙여넣기 ──────────────────────────────────────────────────
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
  if (before && before !== after) { state.results = {}; state.approved.clear(); state.pending = {}; $("results").innerHTML = ""; }
  renderCards(cards);
}

async function boot() {
  try {
    state.health = await api("/api/health"); renderHealth(state.health);
    await refresh();
    $("start").disabled = false;
    $("start").textContent = `밤 11시, 오늘 리뷰 ${state.briefing.counts.review_count}건 확인하기`;
  } catch (e) { showAlert(e.message); $("start").textContent = "불러오지 못했어요"; }
}

$("start").addEventListener("click", () => {
  startTimer();
  ["step1", "step2"].forEach((id) => ($(id).hidden = false));
  $("step1").scrollIntoView({ behavior: "smooth", block: "start" });
});
$("paste-send").addEventListener("click", paste);
$("paste-reset").addEventListener("click", resetPaste);
$("record").addEventListener("click", record);
boot();
