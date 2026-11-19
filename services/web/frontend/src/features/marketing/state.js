// 맞춤 마케팅 화면의 모듈 상태와 동작 (예전 app.js 의 mkt 객체와 mktStart·mktFirst·mktStep·mktDecide·mktResult·카드 동작·mktReport·mktReset·mktJump).
// - 설문 상태는 서버에 없고 화면이 들고 다닌다 (flow = {node, raw, confirms, mode}, 요청마다 그대로 보냄).
// - 화면을 떠났다 와도 대화·결과 카드·보고서가 남도록 화면 밖(이 모듈)에 둔다.
// - 가게가 바뀌거나(epoch) 처리 완료의 '처음부터 다시'(mktResetSeq)면 처음으로 (예전 mktReset). 다음에 화면을 열 때 처음부터 시작한다.
// - 오류는 이 화면 안에만 (맨 위 띠를 쓰지 않음).
import { useSyncExternalStore } from "react";
import { getState, setState as setApp } from "../../state/store.js";
import { staffApprovals } from "../../state/boot.js";
import { currentRoute } from "../../lib/router.js";
import { mktApi, mktPost } from "./api.js";
import { MKT_STATES, MKT_SUB, MKT_UNIT, badgeOf, calcRange, downKey, draftLabel, initialDrafts, mktKey } from "./logic.js";

// 대화를 처음으로 되돌릴 때 비우는 것
const blankChat = () => ({ flow: null, prompt: null, log: [], cards: [], error: "", hasRetry: false, questions: 0 });
// '처음부터 다시'·가게 바뀜 때 비우는 것 (예전 mktReset). gen·reportGen·카드 번호·처리한 nav 번호는 이어 간다
const blank = () => ({
  ...blankChat(),
  started: false, loading: false, ready: false, checking: false,
  busy: false, status: null,     // 진행 안내 {text, long, t0} (예전 #mkt-status)
  health: null, storeName: "",   // GET health · meta 의 가게 이름
  down: null,                    // 쓸 수 없을 때 {key, title, message} (예전 #mkt-state)
  demoSeen: false,               // 저장된 예시(demo: true) 결과를 한 번이라도 받았는지
  clearNote: "",                 // '처음부터 다시' 때 마케팅 기록을 지우지 못했으면 그 안내
  tab: "chat", period: "weekly",
  report: { data: null, period: "weekly", msg: "", bad: false },
});

let m = { ...blank(), gen: 0, reportGen: 0, cardsN: 0, promptN: 0, navSeq: 0, epoch: null, resetSeq: null };
const listeners = new Set();
const set = (patch) => { m = { ...m, ...(typeof patch === "function" ? patch(m) : patch) }; listeners.forEach((l) => l()); };
const subscribe = (l) => { listeners.add(l); return () => listeners.delete(l); };
export const getMkt = () => m;
export const useMkt = (selector = (s) => s) => useSyncExternalStore(subscribe, () => selector(m));

let retryFn = null;                // '다시 시도'가 다시 부를 일 (예전 mkt.retry)
let want = null;                   // mktJump 가 기다리는 시작 모드
const timers = new Map();          // 카드 번호 → 슬라이더 묶음 타이머
const seqs = new Map();            // 카드 번호 → 슬라이더 계산 차례 (늦게 온 숫자는 버림)
const clearTimers = () => { timers.forEach((t) => clearTimeout(t)); timers.clear(); seqs.clear(); };

// 가게가 바뀌었거나 '처음부터 다시'를 눌렀으면 처음으로 (예전 mktReset). 늦게 온 응답을 쓰기 전에도 부른다
export function sync() {
  const app = getState();
  if (m.epoch === null) { set({ epoch: app.epoch, resetSeq: app.mktResetSeq }); return; }
  if (m.epoch === app.epoch && m.resetSeq === app.mktResetSeq) return;
  // cleared = 서버의 marketing_cleared (false 면 기록을 못 지운 것 → 이 화면 안에만 안내). 가게가 바뀐 것이면 안내 없음
  const byReset = m.epoch === app.epoch && app.mktCleared === false;
  clearTimers();
  retryFn = null;
  set((s) => ({ ...blank(), gen: s.gen + 1, reportGen: s.reportGen + 1, epoch: app.epoch, resetSeq: app.mktResetSeq,
    clearNote: byReset ? "‘처음부터 다시’ 때 맞춤 마케팅 기록은 지우지 못했어요. 마케팅 보고서에 예전 기록이 남아 있을 수 있어요." : "" }));
}
// 이 응답을 버려야 하는가: '처음부터'·가게 바뀜으로 요청 차례가 바뀜
const stale = (gen) => { sync(); return gen !== m.gen; };
const bump = () => { set((s) => ({ gen: s.gen + 1 })); return m.gen; };

// ── 포커스·스크롤 (그린 뒤에) ──
const later = (fn) => setTimeout(fn, 0);
const reduced = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
export function reveal(el, block = "nearest") {
  if (el && el.isConnected) el.scrollIntoView({ behavior: reduced() ? "auto" : "smooth", block });
}
const firstControl = () => document.querySelector("#mkt-options button:not([disabled]), #mkt-options input, #mkt-options textarea");

// ── 진행·오류 ──
function busy(text, long = false) { set({ busy: !!text, status: text ? { text, long, t0: Date.now() } : null }); }
// 오류 (role=alert). retry 를 주면 답 고르기 칸에 '다시 시도'
function err(message, retry) { retryFn = retry || null; set({ error: message || "", hasRetry: !!retry }); }
export function retry() { const again = retryFn; err(""); if (again) again(); }

let logN = 0;
const entry = (kind, text) => ({ id: ++logN, kind, text });
const addLog = (...items) => set((s) => ({ log: [...s.log, ...items] }));
const bots = (d) => (d.bot_messages || []).map((t) => entry("bot", t));

// 마케팅 서비스를 쓸 수 없을 때: 탭·대화를 숨기고 상태 안내와 '다시 확인'만 (다른 화면은 그대로)
function down(st, message) {
  const key = downKey(st);
  set({ ready: false, down: { key, title: MKT_STATES[key], message: message || "잠시 뒤 다시 확인해 주세요." } });
  busy("");
}

// 화면을 열 때: 처음이면 시작, 보고서 탭이면 그 기간을 다시 부른다 (페이지를 열 때는 부르지 않음)
export function open() {
  sync();
  if (!m.started) { set({ started: true }); start(); return; }
  if (m.ready && m.tab === "report") loadReport(m.period);
}

// 시작 (처음 열 때, '다시 확인'): health → 가게 이름 → 첫 질문
export async function start() {
  if (m.loading) return;
  const gen = bump();
  set({ loading: true, checking: true });
  err("");
  busy("맞춤 마케팅을 확인하고 있어요");
  try {
    const h = await mktApi("health");
    if (stale(gen)) return;
    set({ health: h });
    if (h.state !== "ready") { down(h.state, h.message); return; }
    set({ ready: true, down: null });
    mktApi("meta").then((x) => { if (!stale(gen)) set({ storeName: x?.store_name || "" }); }).catch(() => {});
    await first(gen);
  } catch (e) { if (!stale(gen)) down(e.state, e.message); }
  finally { set({ loading: false, checking: false }); }
}
// '다시 확인': 다시 시작한 뒤 첫 보기(또는 탭)로, 아직 못 쓰면 그 버튼으로 포커스
export async function recheck() {
  await start();
  later(() => (m.ready ? firstControl() || document.getElementById("mkt-tab-chat") : document.getElementById("mkt-retry"))?.focus());
}

// 첫 질문 (무엇을 도와드릴까요? + 시작 모드 다섯 개). '처음부터'도 여기로 (승인 기록은 지우지 않음)
export async function first(gen, focus = false) {
  if (gen === undefined) gen = bump();
  clearTimers();
  set(blankChat());
  err("");
  busy("첫 질문을 불러오고 있어요");
  try {
    const d = await mktPost("step", { state: null, answer: null });
    if (stale(gen)) return;
    busy("");
    set({ flow: d.state, log: [...bots(d), entry("sub", "고친 만큼, 남는 만큼만 홍보해요")] });
    prompt(d, focus);
  } catch (e) {
    if (stale(gen)) return;
    busy("");
    err(e.message, () => first(undefined, true));
  }
}

// 답 고르기 칸: 시작 모드 카드 · 보기(하나) · 여러 개 고르기 + [다음] · 숫자/글 입력(예시 문구, 건너뛰기)
function prompt(d, focus = true) {
  const opts = Array.isArray(d.options) ? d.options : [];
  const atStart = m.flow?.node === "start";
  set((s) => ({
    prompt: { seq: s.promptN + 1, opts, input: d.input || null, multi: !!d.multi, start: atStart, picked: [] },
    promptN: s.promptN + 1,
    questions: atStart ? s.questions : s.questions + 1,
    log: d.example ? [...s.log, entry("example", d.example)] : s.log,
  }));
  later(() => {
    if (focus) firstControl()?.focus({ preventScroll: true });
    reveal(document.getElementById("mkt-options"));
  });
}
// 여러 개 고르기 칩을 누름 (고른 것은 화면을 떠났다 와도 남게 여기에)
export function togglePick(i) {
  if (!m.prompt) return;
  const picked = m.prompt.picked.includes(i) ? m.prompt.picked.filter((x) => x !== i) : [...m.prompt.picked, i];
  set({ prompt: { ...m.prompt, picked } });
}
export function pickOption(i) {
  if (m.busy) return;
  const o = m.prompt?.opts[i];
  if (o) answer(o.label, o.label);
}
export function sendPicked() {
  if (m.busy || !m.prompt) return;
  const picked = m.prompt.picked.slice().sort((a, b) => a - b).map((i) => m.prompt.opts[i]).filter(Boolean);
  if (picked.length) answer(picked.map((o) => o.value), picked.map((o) => o.label).join(", "));
}
export function skip() { if (!m.busy) answer("", "건너뛰기"); }
// 숫자 칸의 [보내기]: 숫자만 보내고 말풍선에는 단위를 붙여 보인다
export function sendNumber(digits) {
  if (m.busy) return;
  answer(digits, `${Number(digits).toLocaleString("ko-KR")}${MKT_UNIT[m.prompt?.input?.key] || ""}`);
}
export function sendText(value) { if (!m.busy) answer(value, value); }

export async function answer(value, label) {
  if (m.busy) return;
  addLog(entry("user", label));
  await step(value);
}
// 질문 하나 진행 (POST step). 끝(done)이면 결과 카드
async function step(value, focus = true) {
  const gen = m.gen;
  err("");
  set({ prompt: null });
  busy("다음 질문을 준비하고 있어요");
  let d;
  try { d = await mktPost("step", { state: m.flow, answer: value }); }
  catch (e) {
    if (stale(gen)) return;
    busy("");
    err(e.message, () => step(value, focus));
    return;
  }
  if (stale(gen)) return;
  busy("");
  set({ flow: d.state });
  if (d.done) { await decide(); return; }
  addLog(...bots(d));
  prompt(d, focus);
}

// ── 결과 카드 ──
// plan(글 생성 포함)과, 맞춤 홍보 제안·재주문 쿠폰이면 result(결정 설명 3줄, 규칙 계산)를 같이 받는다
async function decide(flow = m.flow, label = "결과를 정리하고 글을 만들고 있어요") {
  const gen = m.gen;
  err("");
  if (flow === m.flow) set({ prompt: null });   // 다시 쓰기로 예전 카드를 다시 받을 때는 지금 질문을 지우지 않는다
  busy(label, true);
  const survey = flow?.mode === "survey" || flow?.mode === "follow_up";
  let plan, why;
  try {
    [plan, why] = await Promise.all([mktPost("plan", { state: flow }), survey ? mktPost("result", { state: flow }).catch(() => null) : null]);
  } catch (e) {
    if (stale(gen)) return undefined;
    busy("");
    err(e.message, () => decide(flow, label));
    return undefined;
  }
  if (stale(gen)) return undefined;
  busy("");
  return addCard(plan, why, flow);
}

const runId = () => (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "") : Date.now().toString(36) + Math.random().toString(36).slice(2)).slice(0, 10);

function addCard(d, why, flow) {
  const n = m.cardsN + 1;
  const demo = d.demo === true;
  const { drafts, order } = initialDrafts(d, flow?.mode, demo);
  const input = d.coupon_card?.calc_input || null;
  const range = input ? calcRange(input) : null;
  // run: 이 카드의 글 id 앞부분 (새로 고친 뒤에도 앞서 승인한 기록과 겹치지 않게 임의 값)
  let card = {
    n, run: runId(), flow, data: d, why, session: d.session_id || null, demo, title: d.title || "결과", gen: m.gen,
    drafts, order, badge: badgeOf(d),
    approved: false, approving: false, replaced: false, rewriting: false, busy: false, work: null, msg: "", msgBad: false, done: false,
    idea: null,
    calc: range ? { budget_won: range.budget, discount_won: range.startD } : null, range, figs: null,
    nextCoupon: null,                                  // '다음 쿠폰 조건'으로 만든 쿠폰 {coupon}
    noticeOffer: false, notice: { busy: false, result: null, error: "", text: "" },
  };
  if (d.idea) card = { ...card, ...ideaPatch(card, d.idea, d.idea_index ?? 0) };
  set((s) => ({ cards: [...s.cards, card], cardsN: n, demoSeen: s.demoSeen || demo }));
  if (input) recalc(n);
  later(() => {
    reveal(document.getElementById(`mkt-card-${n}`), "start");
    document.getElementById(`mkt-card-${n}-title`)?.focus({ preventScroll: true });
  });
  return n;
}
const cardOf = (n) => m.cards.find((c) => c.n === n);
function updCard(n, patch) {
  set((s) => ({ cards: s.cards.map((c) => (c.n === n ? { ...c, ...(typeof patch === "function" ? patch(c) : patch) } : c)) }));
}
const cardMsg = (n, text, bad = false) => updCard(n, { msg: text || "", msgBad: bad });
// 글 상자를 카드에 넣는다 (같은 열쇠는 지우고 맨 뒤에: 승인할 때 이 순서로 보냄)
function withDraft(c, key, text, kind, label) {
  const order = [...c.order.filter((k) => k !== key), key];
  return { drafts: { ...c.drafts, [key]: { kind, label, original: String(text ?? ""), text: String(text ?? ""), failed: null } }, order };
}
function withoutDrafts(c, test) {
  const order = c.order.filter((k) => !test(k)), drafts = {};
  order.forEach((k) => { drafts[k] = c.drafts[k]; });
  return { drafts, order };
}
// 글 칸을 고침: '고친 글' 표시는 그리면서 원래 글과 비교, 점검 실패 안내는 지움
export function editDraft(n, key, text) {
  updCard(n, (c) => (c.drafts[key] ? { drafts: { ...c.drafts, [key]: { ...c.drafts[key], text, failed: null } } } : {}));
}
export function editFollow(n, text) { updCard(n, (c) => ({ notice: { ...c.notice, text } })); }

// 쿠폰 슬라이더: 예산·할인액을 움직이면 150ms 뒤 coupon-calc 로 장수·최대 비용·본전 주문 수를 다시 계산 (원본처럼 묶어서 보냄)
export function slide(n, name, value) {
  updCard(n, (c) => ({ calc: { ...c.calc, [name]: Number(value) } }));
  clearTimeout(timers.get(n));
  timers.set(n, setTimeout(() => recalc(n), 150));
}
async function recalc(n) {
  const c = cardOf(n);
  if (!c || !c.calc || c.gen !== m.gen) return;
  const input = c.data.coupon_card.calc_input;
  const seq = (seqs.get(n) || 0) + 1;
  seqs.set(n, seq);
  let fig;
  try {
    fig = await mktPost("coupon-calc", { budget_won: c.calc.budget_won, discount_won: c.calc.discount_won, price_won: Number(input.price_won) || 0,
      avg_order_won: input.avg_order_won, margin_pct: input.margin_pct });
  } catch (e) { if (seq === seqs.get(n) && cardOf(n)) cardMsg(n, `계산하지 못했어요: ${e.message}`, true); return; }
  if (seq !== seqs.get(n) || !cardOf(n)) return;   // 그 사이 슬라이더를 또 움직였다: 늦게 온 숫자는 버린다
  updCard(n, (x) => {
    const patch = { msg: "", msgBad: false, figs: { ...fig, budgetAt: x.calc.budget_won } };
    // 판정 배지가 '정보'인 카드는 할인이 크면 '할인 큼'으로 (원본과 같음)
    if (x.badge && (x.badge[1] === "정보" || x.badge[1] === "할인 큼")) patch.badge = fig.discount_pct > 20 ? ["warn", "할인 큼"] : ["", "정보"];
    return patch;
  });
}

// 카드 안 버튼 하나의 일: 버튼을 잠그고 진행 글을 보이고, 실패하면 카드 안에 안내 (화면의 다른 곳은 그대로)
async function cardWork(n, name, text, work) {
  const c = cardOf(n);
  if (!c || c.busy) return;
  updCard(n, { busy: true, work: name, msg: text, msgBad: false });
  try { await work(); }
  catch (e) { if (cardOf(n)) cardMsg(n, e.message, true); }
  finally { if (cardOf(n)) updCard(n, { busy: false, work: null }); }
}
// '이 조건으로 쿠폰 글 만들기' (슬라이더 값으로 generate). 새 글은 그 아래, 이 카드를 승인할 때 같이 승인된다
export function couponGen(n) {
  const c = cardOf(n);
  if (!c || c.approved) return;
  cardWork(n, "coupon-gen", "쿠폰 글을 만들고 있어요…", async () => {
    const g = await mktPost("generate", { state: c.flow, coupon_override: { ...cardOf(n).calc } });
    if (!cardOf(n)) return;
    if (!g.text) { cardMsg(n, "이 조건으로는 쿠폰 글을 만들지 못했어요.", true); return; }
    if (g.demo) set({ demoSeen: true });
    updCard(n, (x) => ({ ...withDraft(x, "coupon_regen", g.text, "쿠폰 글", draftLabel("쿠폰 글", g.demo === true)), msg: "이 조건으로 쿠폰 글을 만들었어요. 승인하면 같이 승인돼요.", msgBad: false }));
  });
}
// 쿠폰 결과 확인의 '다음 쿠폰 조건' → generate (할인액은 서버 코드가 정한 값)
export function nextCoupon(n) {
  const c = cardOf(n);
  if (!c || c.approved) return;
  cardWork(n, "next-coupon", "쿠폰 글을 만들고 있어요…", async () => {
    const g = await mktPost("generate", { state: c.flow });
    if (!cardOf(n)) return;
    if (g.demo) set({ demoSeen: true });
    updCard(n, (x) => {
      const base = withoutDrafts(x, (k) => k === "next_coupon");
      const withText = g.text ? withDraft({ ...x, ...base }, "next_coupon", g.text, "쿠폰 글", draftLabel("쿠폰 글", g.demo === true)) : base;
      return { ...withText, nextCoupon: { coupon: g.coupon || null }, msg: g.text ? "다음 쿠폰 글을 만들었어요. 승인하면 같이 승인돼요." : "쿠폰 글을 만들지 못했어요.", msgBad: !g.text };
    });
  });
}

// ── 추천 아이디어 ──
// 목표 하나 안에서 순서대로 돈다(next-idea, 무작위 아님). 질문이 필요한 아이디어는 [해 볼게요]를 누른 뒤에만 묻고(idea-try),
// 조건이 안 맞으면(skip) 다음 아이디어로 넘어간다. 아이디어 글은 서버의 정해 둔 틀이다 (AI 아님)
function ideaPatch(c, idea, index) {
  const base = withoutDrafts(c, (k) => k.startsWith("idea_"));   // 지난 아이디어 글은 승인 대상에서 뺀다
  const story = idea.id === "story_link";
  const next = idea.draft && !idea.needs_question && !story
    ? withDraft({ ...c, ...base }, `idea_${idea.id}`, idea.draft, "아이디어 글", draftLabel("아이디어 글", false, true)) : base;
  return { ...next, idea: { item: idea, index, asking: false, qBusy: false, tried: false, nextBusy: false, storyBusy: false, msg: "" } };
}
const updIdea = (n, patch) => updCard(n, (c) => (c.idea ? { idea: { ...c.idea, ...patch } } : {}));
export async function ideaNext(n) {
  const c = cardOf(n);
  if (!c?.idea) return;
  updIdea(n, { nextBusy: true });
  try {
    const r = await mktPost("next-idea", { state: c.flow, current_index: c.idea.index });
    if (!cardOf(n)) return;
    if (r.idea) {
      updCard(n, (x) => ideaPatch(x, r.idea, r.idea_index ?? x.idea.index));
      later(() => document.getElementById(`mkt-idea-${n}-title`)?.focus());
    } else updIdea(n, { msg: "다른 아이디어가 없어요." });
  } catch (e) { updIdea(n, { msg: e.message }); }
  finally { updIdea(n, { nextBusy: false }); }
}
export function ideaAsk(n) {
  updIdea(n, { asking: true });
  later(() => document.querySelector(`#mkt-idea-${n}-q button, #mkt-idea-${n}-q input`)?.focus());
}
export async function ideaTry(n, value) {
  const c = cardOf(n);
  if (!c?.idea) return;
  const idea = c.idea.item;
  updIdea(n, { qBusy: true, msg: "아이디어를 글로 만들고 있어요…" });
  try {
    const r = await mktPost("idea-try", { state: c.flow, idea_id: idea.id, index: c.idea.index, answer: value });
    if (!cardOf(n)) return;
    if (r.skip) {
      updIdea(n, { msg: "이 아이디어는 지금은 건너뛸게요." });
      await ideaNext(n);
      return;
    }
    updCard(n, (x) => ({
      ...(r.draft ? withDraft(x, `idea_${idea.id}`, r.draft, "아이디어 글", draftLabel("아이디어 글", false, true)) : {}),
      idea: { ...x.idea, tried: true, qBusy: false, msg: r.draft ? "아이디어 글을 만들었어요. 카드를 승인하면 같이 승인돼요." : "" },
    }));
  } catch (e) {
    updIdea(n, { qBusy: false, msg: e.message });
  }
}
// '가게 이야기 글 만들기' 아이디어: 새 설문(가게 이야기 글)으로 이어서 묻는다
export async function storyLink(n) {
  if (m.busy) return;
  updIdea(n, { storyBusy: true });
  const gen = m.gen;
  addLog(entry("user", "가게 이야기 글 만들기"));
  busy("가게 이야기 질문을 준비하고 있어요");
  try {
    const base = await mktPost("step", { state: null, answer: null });
    const r = await mktPost("step", { state: base.state, answer: "가게 이야기 글" });
    if (stale(gen)) return;
    busy("");
    set({ flow: r.state });
    addLog(...bots(r));
    prompt(r);
  } catch (e) {
    if (stale(gen)) return;
    busy("");
    updIdea(n, { storyBusy: false });
    err(e.message);
  }
}

// ── 승인 ──
// 이 카드의 글(고친 글 포함)을 모두 보낸다. 마케팅 서비스가 고친 글을 다시 점검해 걸리면(edit_failed) 그 글 아래에 빨간 안내.
// 성공하면 서버가 이 방문자의 승인 기록에도 남기고(recorded) '처리 완료'에 보인다. 공지 카드면 '2주 뒤 확인해 보기'를 카드 안에 둔다
export async function approve(n) {
  const c = cardOf(n);
  if (!c || c.approved || c.replaced || c.busy || m.busy) return;
  const gen = m.gen, edited = {}, approval = [];
  c.order.forEach((key) => {
    const d = c.drafts[key];
    if (d.text.trim() !== d.original.trim()) edited[key] = d.text;
    approval.push({ draft_id: `${c.run}-${mktKey(key)}`, text: d.text, original: d.original, kind: d.kind, title: c.title });
  });
  const cleared = {};
  c.order.forEach((k) => { cleared[k] = { ...c.drafts[k], failed: null }; });
  updCard(n, { busy: true, approving: true, drafts: cleared, msg: "승인하고 있어요…", msgBad: false });
  busy("승인하고 있어요");
  let a;
  try {
    a = await mktPost("approve", { state: c.flow, draft_id: null, session_id: c.session, edited_texts: edited, approval });
  } catch (e) {
    if (stale(gen)) return;
    busy("");
    updCard(n, { busy: false, approving: false, msg: `승인하지 못했어요: ${e.message}`, msgBad: true });
    return;
  }
  if (stale(gen)) return;
  busy("");
  if (a.edit_failed) {
    let first = null;
    updCard(n, (x) => {
      const drafts = { ...x.drafts };
      Object.entries(a.edit_failed).forEach(([key, reasons]) => {
        if (!drafts[key]) return;
        drafts[key] = { ...drafts[key], failed: Array.isArray(reasons) ? reasons : [reasons] };
        first = first || key;
      });
      return { drafts, busy: false, approving: false, msg: "고친 글이 점검에 걸렸어요. 빨간 안내를 보고 글을 고친 뒤 다시 승인해 주세요.", msgBad: true };
    });
    if (first) later(() => document.getElementById(`mkt-text-${n}-${mktKey(first)}`)?.focus());
    return;
  }
  const recorded = Array.isArray(a.recorded) ? a.recorded : [];
  const ids = new Set(recorded.map((r) => r.draft_id));
  setApp((s) => ({ approvedLog: [...s.approvedLog.filter((x) => !ids.has(x.id)),
    ...recorded.map((r) => ({ id: r.draft_id, at: r.approved_at || new Date().toISOString(), edited: !!r.edited, name: r.kind, card: "맞춤 마케팅", mkt: true }))] }));
  staffApprovals();
  const notice = (c.data.steps || []).some((s) => s.generator === "prevention_notice");
  updCard(n, { approved: true, busy: false, approving: false, done: recorded.length > 0, noticeOffer: notice,
    msg: `승인했어요.${recorded.length ? ` '처리 완료'에 글 ${recorded.length}건을 기록했어요.` : ""}${a.record_warning ? ` ${a.record_warning}` : ""} 게시는 복사해서 직접 올려요.`, msgBad: false });
  set({ flow: a.state || m.flow });
  if (a.follow_up) {
    addLog(...bots(a));
    prompt(a);
  } else {
    addLog(entry("bot", "여기까지 도와드릴게요. 감사합니다! 다른 것도 해 보려면 아래 ‘처음부터’를 눌러 주세요."));
    set({ prompt: null });
  }
}
// 같은 답으로 결과를 다시 받는다 (글을 새로 씀). 새 카드는 아래에, 예전 카드는 그대로 남는다
export async function rewrite(n) {
  const c = cardOf(n);
  if (!c || m.busy || c.approved || c.busy) return;
  updCard(n, { rewriting: true });
  addLog(entry("user", "다시 쓰기"));
  const fresh = await decide(c.flow, "같은 답으로 글을 다시 쓰고 있어요");
  if (!cardOf(n)) return;
  if (!fresh) { updCard(n, { rewriting: false }); return; }
  // 새로 쓴 카드가 생기면 예전 카드는 승인하지 못하게 (같은 답의 글이 두 번 승인되지 않게)
  updCard(n, { replaced: true, msg: "새로 쓴 결과가 아래에 있어요. 이 카드는 승인할 수 없어요.", msgBad: false });
}
// 공지를 승인한 카드: 2주 뒤 같은 불만이 줄었는지 (데모: 저장된 리뷰 날짜로 서버 코드가 셈). 줄었으면 개선 소식 글.
// 승인이 끝난 카드라 이 글은 승인 대상이 아니다 (복사해서 씀)
export async function noticeFollow(n) {
  const c = cardOf(n);
  if (!c) return;
  updCard(n, (x) => ({ notice: { ...x.notice, busy: true, error: "" } }));
  try {
    const f = await mktPost("notice-followup", { state: c.flow });
    if (!cardOf(n)) return;
    updCard(n, (x) => ({ notice: { ...x.notice, busy: false, result: f, text: f.improved && f.text ? String(f.text) : "" } }));
  } catch (e) {
    if (cardOf(n)) updCard(n, (x) => ({ notice: { ...x.notice, busy: false, error: e.message } }));
  }
}

// ── 마케팅 보고서 탭 (주간·월간) ──
export function setTab(name) {
  set({ tab: name });
  if (name === "report") loadReport(m.period);
}
// 보고서는 기록을 코드로 센 것이다 (AI 호출 없음). 열 때마다 새로 부른다 (방금 승인한 것도 세게)
export async function loadReport(period) {
  const gen = m.reportGen + 1;
  set((s) => ({ period, reportGen: gen, report: { ...s.report, msg: "불러오는 중…", bad: false } }));
  try {
    const d = await mktApi(`report?period=${encodeURIComponent(period)}`);
    sync();
    if (gen !== m.reportGen) return;
    set({ report: { data: d, period, msg: "", bad: false } });
  } catch (e) {
    sync();
    if (gen !== m.reportGen) return;
    set({ report: { data: null, period, msg: e.message, bad: true } });
  }
}

// '처음부터' (이 화면): 대화만 처음으로. 승인 기록·보고서 기록은 그대로
export function restartChat() {
  set({ tab: "chat" });
  first(bump(), true);
}

// 다른 화면의 navTo("marketing", sub): 그 시작 모드로 바로. nav.seq 가 바뀔 때마다 한 번
export function handleNav() {
  const nav = getState().nav;
  if (!nav || nav.seq === m.navSeq) return;
  set({ navSeq: nav.seq });
  if (nav.name === "marketing" && MKT_SUB[nav.sub]) jump(MKT_SUB[nav.sub]);
}
// 첫 질문(시작 모드 다섯 개)이 나오면 그 보기를 고른다. 다른 대화 중이면 처음부터 (예전 mktJump)
async function jump(label) {
  want = label;
  setTab("chat");
  for (let i = 0; i < 120 && want === label; i += 1) {
    sync();
    if (m.ready && !m.busy && !m.loading) {
      const atStart = m.flow && m.flow.node === "start" && m.prompt && (m.prompt.opts || []).some((o) => o.label === label);
      if (atStart) { want = null; answer(label, label); return; }
      if (m.flow && m.flow.node !== "start") { await first(bump()); continue; }
    }
    if (!m.started && currentRoute() === "marketing") open();
    await new Promise((r) => setTimeout(r, 150));
  }
}

// 위쪽 안내: 키 없이 저장된 예시로 도는 중이면 꼭, '처음부터 다시' 때 기록을 못 지웠으면 그 안내도 (예전 mktNotice)
export function noticeLines(s) {
  const h = s.health || {};
  const demo = h.demo === true || h.mode === "mock" || h.key_present === false || s.demoSeen;   // mock 이면 키가 있어도 데모
  return [demo ? "시험용 실행 · 맞춤 마케팅이 지금 HCX를 부르지 않아 글은 미리 저장한 예시·정해 둔 틀이에요 (실제 AI 결과 아님)" : "", s.clearNote].filter(Boolean);
}
