// AI에게 묻기 서랍의 모듈 상태와 동작 (예전 app.js 의 chat 객체와 chatSend·chatChoose·chatClear·chatHome·chatStart·chatReset).
// 서랍은 화면 밖에 늘 그려지므로 대화·조건·setup 시도 여부는 여기 둔다. 가게가 바뀌면(epoch) chatReset 으로 비운다.
// 호출은 drawerApi 로만 한다: 오류는 서랍 안(#assistant-error·상태 안내)에만 보이고 맨 위 띠는 쓰지 않는다.
import { useSyncExternalStore } from "react";
import { openDrawer } from "../../state/store.js";
import { navTo } from "../../lib/router.js";
import {
  CHAT_STARTERS, CHAT_STATES, CHAT_SLOW, chatQuarter, chatCondText, chatId, chatSuggest, chatSameKey, chatNavTarget, drawerApi,
} from "./chat.js";

const NO_CHIPS = { list: [], starters: false };
function init() {
  return {
    started: false, loading: false, ready: false, busy: false,
    setupTried: false,          // 조건 자동 저장(setup)은 한 번만. '다시 확인'을 누르면 다시
    label: "",                  // 상태의 setup.label ("온기한식 · 장승배기역 · 한식음식점")
    conditions: null,           // 조건 줄 (글자가 없으면 null → 숨김)
    atHome: false,              // 서버가 준 conditions.is_store_default 가 true 일 때만
    items: [],                  // 대화 줄 [{id, type: "user", text, failed} | {id, type: "bot", data, picked}]
    latest: null,               // 마지막 답의 id (이 답의 선택지만 누를 수 있음)
    chips: NO_CHIPS,
    welcome: false,
    stateCard: null,            // 쓸 수 없을 때의 안내 {key, title, msg}
    error: "",
    status: { text: "", busy: false, srOnly: false, seq: 0 },
    armed: false,               // 대화 지우기 확인 대기 (4초)
    homeFlash: false,           // '✓ 맞췄어요' 2초
    hl: null,                   // 강조한 근거 카드 "답id:F1"
    logLive: "polite",
    draft: "",                  // 입력칸 글
    epoch: null,
  };
}

let chat = init();
const listeners = new Set();
export const getChat = () => chat;
function set(patch) {
  const next = typeof patch === "function" ? patch(chat) : patch;
  if (!next) return;
  chat = { ...chat, ...next };
  listeners.forEach((l) => l());
}
const subscribe = (l) => { listeners.add(l); return () => listeners.delete(l); };
export const useChat = () => useSyncExternalStore(subscribe, () => chat);

let gen = 0;                    // chatReset 마다 1씩. 그 전에 시작한 호출의 결과는 버린다
let armedTimer = null, flashTimer = null, seq = 0, ids = 0;
const nextId = () => `m${++ids}`;
let skipFocus = false;          // 화면 이동 버튼으로 닫을 때는 포커스를 상단 버튼으로 돌려주지 않음 (새 화면 제목이 받음)
export const takeSkipFocus = () => { const v = skipFocus; skipFocus = false; return v; };

const $ = (id) => document.getElementById(id);
const afterPaint = (fn) => requestAnimationFrame(() => fn());
export const setDraft = (draft) => set({ draft });

// 진행·안내 (#assistant-status). busy 이면 점이 깜박이고 걸린 초를 보인다. srOnly 는 읽기 프로그램에만 알리는 안내
function chatStatus(text, busy = false, srOnly = false) { set({ status: { text: text || "", busy: !!text && busy, srOnly, seq: ++seq } }); }
function chatBusy(on, text) { set({ busy: on }); chatStatus(on ? text : "", on); }
function chatConditions(c) { set({ conditions: chatCondText(c) ? c : null, atHome: !!c && c.is_store_default === true }); }
const chatChips = (list, starters = false) => set({ chips: { list, starters } });

// 보낸 뒤 입력칸으로 포커스를 돌려준다. 다른 곳으로 옮겼거나 터치 화면(자판이 답을 가림)이면 그대로 둔다
export function chatFocus(force = false) {
  afterPaint(() => {
    const box = $("assistant"), a = document.activeElement;
    if (!box || box.hidden || !chat.ready || (a && a !== document.body && !box.contains(a))) return;
    if (!force && window.matchMedia("(pointer: coarse)").matches) return;
    $("assistant-q")?.focus({ preventScroll: true });
  });
}
// 대화 칸 안에서만 스크롤한다 (페이지는 움직이지 않음). where: start = 요소 맨 위로, near = 안 보일 때만, end = 맨 아래로
export function chatReveal(el, where = "start") {
  const box = $("assistant-scroll");
  if (!box) return;
  const smooth = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  if (where === "end" || !el) { box.scrollTo({ top: box.scrollHeight, behavior: smooth }); return; }
  let y = 0;
  for (let n = el; n && n !== box; n = n.offsetParent) y += n.offsetTop;
  if (where === "near" && y >= box.scrollTop && y + el.offsetHeight <= box.scrollTop + box.clientHeight) return;
  box.scrollTo({ top: Math.max(0, y - 12), behavior: smooth });
}
const msgEl = (id) => (id ? document.querySelector(`#assistant-log [data-msg="${id}"]`) : null);

// 근거 카드 강조: 한 번에 하나만. 펼치는 것은 그 답(BotMsg)이 한다
export function chatHighlight(msgId, cardId, domId) {
  set({ hl: `${msgId}:${cardId}` });
  afterPaint(() => { const li = $(domId); if (!li) return; chatReveal(li, "near"); li.focus({ preventScroll: true }); });
}

function chatDisarm() { clearTimeout(armedTimer); armedTimer = null; if (chat.armed) set({ armed: false }); }

// 답을 받으면: 그 답을 붙이고, 선택지는 이 답 것만 누를 수 있게, 칩은 이 답의 suggestions, 조건은 응답에 있을 때만 바꾼다
function chatAnswer(r, mine) {
  const bot = { id: nextId(), type: "bot", data: r, picked: null };
  set((s) => ({ items: [...s.items, bot], latest: bot.id, chips: { list: chatSuggest(r?.reply), starters: false } }));
  if (r && "conditions" in r) chatConditions(r.conditions);
  afterPaint(() => chatReveal(msgEl(mine), "start"));
}
function chatFailed(mine, message, chips) {
  set((s) => ({ items: s.items.map((it) => (it.id === mine ? { ...it, failed: true } : it)), chips, error: message || "" }));
}

export async function chatSend(text) {
  const value = String(text ?? "").trim();
  if (!value || chat.busy || !chat.ready) return;
  const g = gen, chips = chat.chips, mine = nextId();
  chatDisarm();
  set((s) => ({
    error: "", welcome: false, items: [...s.items, { id: mine, type: "user", text: value, failed: false }], chips: NO_CHIPS,
    ...(s.draft.trim() === value ? { draft: "" } : {}),   // 칩으로 물었으면 쓰던 글은 그대로 둔다
  }));
  chatBusy(true, "자료를 확인하고 있어요");
  afterPaint(() => chatReveal(null, "end"));
  try {
    const r = await drawerApi("/api/assistant/messages", { method: "POST", body: JSON.stringify({ text: value, client_message_id: chatId() }) }, CHAT_SLOW);
    if (g === gen) chatAnswer(r, mine);
  } catch (e) {
    if (g !== gen) return;
    chatFailed(mine, e.message, chips);
    if (!chat.draft.trim()) set({ draft: value });   // 다시 보내기 쉽게 입력칸에 돌려놓는다
  } finally { if (g === gen) { chatBusy(false); chatFocus(); } }
}

// 서랍이 지금 본문(#main)을 덮고 있는가. 화면 폭 숫자 대신 실제 위치로 본다 (layout.css 의 밀기·덮기 기준이 바뀌어도 그대로 맞음).
// 위치를 잴 수 없으면(시험 환경 등) layout.css 와 같은 숫자로: 본문이 680px 넘게 남을 때만 밂 = 메뉴를 폈으면 1339px 이하, 접었으면 1079px 이하가 덮음
export function drawerCovers() {
  const d = $("assistant"), main = $("main");
  const a = d && !d.hidden ? d.getBoundingClientRect() : null;
  const b = main ? main.getBoundingClientRect() : null;
  if (!a || !b || !a.width || !b.width) {
    const q = document.querySelector(".app.menu-closed") ? "(max-width: 1079px)" : "(max-width: 1339px)";
    return !!window.matchMedia?.(q)?.matches;
  }
  return a.left < b.right - 1 && a.right > b.left + 1 && a.top < b.bottom - 1 && a.bottom > b.top + 1;
}
// 화면 이동으로 서랍을 닫은 뒤: 새 화면 제목(PageHead 의 h1)이 포커스를 받는다. PageHead 가 이미 옮겼거나
// 새 화면이 다른 곳(예: 맞춤 마케팅의 첫 보기)으로 옮겼으면 그대로 두고, 포커스가 닫힌 서랍·body 에 남았을 때만 제목으로 (화면이 늦게 그려질 수 있어 몇 번 본다)
function focusTitle(tries = 0) {
  setTimeout(() => {
    const a = document.activeElement;
    if (!a || a === document.body || a.closest?.("#assistant")) document.querySelector("#main h1")?.focus({ preventScroll: true });
    if (tries < 3) focusTitle(tries + 1);
  }, tries ? 60 : 0);
}

// 선택지: 화면 이동 버튼은 서버로 보내지 않고 navTo 로 바로 간다. 서랍이 본문을 덮고 있으면 서랍을 닫고(11/18)
// 포커스는 'AI에게 묻기' 버튼으로 돌려주지 않고 이동한 화면 제목으로 보낸다
export async function chatChoose(botId, index, action) {
  const target = chatNavTarget(action);
  if (target) {
    const cover = drawerCovers();
    navTo(target.route, target.sub);
    if (cover) { skipFocus = true; openDrawer(false); focusTitle(); }
    return;
  }
  if (chat.busy || !chat.ready || botId !== chat.latest) return;
  const g = gen, chips = chat.chips, mine = nextId();
  chatDisarm();
  const mark = (picked) => (it) => (it.id === botId ? { ...it, picked } : it);
  set((s) => ({ error: "", items: [...s.items.map(mark(index)), { id: mine, type: "user", text: `선택: ${chatQuarter(action.label)}`, failed: false }], chips: NO_CHIPS }));
  chatBusy(true, "자료를 확인하고 있어요");
  afterPaint(() => chatReveal(null, "end"));
  try {
    const r = await drawerApi("/api/assistant/actions", { method: "POST", body: JSON.stringify(action.payload ?? {}) }, CHAT_SLOW);
    if (g === gen) chatAnswer(r, mine);
  } catch (e) {
    if (g !== gen) return;
    set((s) => ({ items: s.items.map(mark(null)) }));
    chatFailed(mine, e.message, chips);
  } finally { if (g === gen) { chatBusy(false); chatFocus(); } }
}

// 대화 지우기: 두 번 눌러 확인 (4초 안에). 분석 조건은 서버에 남으니 setup 은 다시 부르지 않고 표시만 서버 값으로 다시 맞춘다
export async function chatClear() {
  if (chat.busy || !chat.ready) return;
  if (!chat.armed) {
    set({ armed: true });
    chatStatus("한 번 더 누르면 대화를 지워요", false, true);
    armedTimer = setTimeout(() => { chatDisarm(); chatStatus(""); }, 4000);
    return;
  }
  const g = gen;
  chatDisarm(); set({ error: "" });
  let done = false;
  chatBusy(true, "대화를 지우고 있어요");
  try {
    await drawerApi("/api/assistant/conversation", { method: "DELETE" });
    if (g !== gen) return;
    set({ items: [], latest: null, welcome: true, hl: null });
    chatConditions(null);
    chatChips(CHAT_STARTERS, true);
    done = true;
    drawerApi("/api/assistant/conversation").then((c) => { if (g === gen) chatConditions(c.conditions); }).catch(() => {});
  } catch (e) { if (g === gen) set({ error: e.message }); }
  finally {
    if (g === gen) {
      chatBusy(false);
      if (done) { chatStatus("대화를 지웠어요", false, true); afterPaint(() => { const b = $("assistant-scroll"); if (b) b.scrollTop = 0; }); chatFocus(true); }
    }
  }
}

// '우리 가게 조건으로': 채팅에서 다른 상권·업종을 보고 있어도 우리 가게 조건으로 되돌린다 (setup?force=1). 대화 기록은 그대로
export async function chatHome() {
  if (chat.busy || !chat.ready) return;
  const g = gen;
  set({ error: "" }); chatDisarm();
  chatBusy(true, "우리 가게 조건으로 맞추고 있어요");
  let done = false;
  try {
    const s = await drawerApi("/api/assistant/setup?force=1", { method: "POST" });
    if (g !== gen) return;
    if (s?.status === "unavailable") set({ error: s.message || (CHAT_STATES[s.state] || CHAT_STATES.error)[1] });
    else { if (s && "conditions" in s) chatConditions(s.conditions); done = true; }
  } catch (e) { if (g === gen) set({ error: e.message }); }
  finally {
    if (g === gen) {
      chatBusy(false);
      // 누르는 동안 막혀서 잃은 포커스. 맞춘 뒤 버튼이 '적용 중'으로 막히면 입력칸으로 보낸다
      afterPaint(() => {
        const box = $("assistant"), b = $("assistant-home");
        if (document.activeElement !== document.body || !box || box.hidden || !chat.conditions || !b) return;
        if (b.disabled) $("assistant-q")?.focus({ preventScroll: true }); else b.focus();
      });
      if (done) {
        chatStatus("우리 가게 조건으로 맞췄어요", false, true);
        // 서버가 같은지 알려 주지 않는 가게에서는 버튼 글자가 그대로라, 눌렀다는 것을 잠깐 알린다 ('적용 중'으로 바뀌면 그 글자가 알림)
        if (!chat.atHome) { clearTimeout(flashTimer); set({ homeFlash: true }); flashTimer = setTimeout(() => set({ homeFlash: false }), 2000); }
      }
    }
  }
}

// 상태 안내: 상권 비서를 쓸 수 없을 때 이것만 보이고 입력칸은 막힌다
function chatState(st, message) {
  const key = CHAT_STATES[st] ? st : "error";
  const [title, fallback] = CHAT_STATES[key];
  set({ ready: false, latest: null, items: [], welcome: false, chips: NO_CHIPS, hl: null, stateCard: { key, title, msg: message || fallback } });
  chatConditions(null);
  chatStatus(`${title}. ${message || fallback}`, false, true);
}

// 이전 대화: 선택지를 고른 턴은 앞 답의 선택지에서 이름을 찾아 '선택: 이름'으로 보이고 그 버튼을 고른 표시로
function chatHistory(turns) {
  const items = [];
  let prev = null, prevBot = null;
  turns.forEach((t) => {
    if (t.user_text) items.push({ id: nextId(), type: "user", text: t.user_text, failed: false });
    else if (t.action) {
      const picked = (prev?.reply?.actions || []).find((a) => chatSameKey(a.payload, t.action));
      items.push({ id: nextId(), type: "user", text: picked ? `선택: ${chatQuarter(picked.label)}` : "선택했어요", failed: false });
      if (picked && prevBot) {
        const shown = (Array.isArray(prev.reply.actions) ? prev.reply.actions : []).filter((a) => a && a.label);
        const i = shown.findIndex((a) => chatQuarter(a.label) === chatQuarter(picked.label));
        if (i >= 0) prevBot.picked = i;
      }
    }
    prevBot = { id: nextId(), type: "bot", data: t, picked: null };
    items.push(prevBot);
    prev = t;
  });
  const last = turns[turns.length - 1];
  // 처음 그릴 때 지난 대화를 통째로 읽지 않게 잠깐 aria-live 를 끈다
  set({ items, latest: prevBot ? prevBot.id : null, hl: null, logLive: "off", chips: { list: last ? chatSuggest(last.reply) : CHAT_STARTERS, starters: !last } });
  afterPaint(() => set({ logLive: "polite" }));
}

// 시작 (서랍을 처음 열 때, 또는 '다시 확인'): 상태 → (ready 이면) 이전 대화·조건 → 조건이 없으면 setup 한 번
export async function chatStart() {
  if (chat.loading) return;
  const g = gen;
  set({ loading: true, ready: false, started: true, error: "" }); chatDisarm();
  chatStatus("상권 비서를 확인하고 있어요", true);
  try {
    const st = await drawerApi("/api/assistant/status");
    if (g !== gen) return;
    set({ label: st?.setup?.label || "" });
    if (st?.state !== "ready") { chatState(st?.state, st?.message); return; }
    const conv = await drawerApi("/api/assistant/conversation");
    if (g !== gen) return;
    const turns = Array.isArray(conv.turns) ? conv.turns : [];
    let cond = conv.conditions || null;
    if (!cond && !chat.setupTried) {
      set({ setupTried: true });
      chatStatus(`분석 조건을 맞추고 있어요${chat.label ? ` (${chat.label})` : ""}`, true);
      const s = await drawerApi("/api/assistant/setup", { method: "POST" });
      if (g !== gen) return;
      if (s?.status === "unavailable") { chatState(s.state, s.message); return; }
      cond = s?.conditions || null;
    }
    set({ stateCard: null, ready: true });
    chatHistory(turns);
    chatConditions(cond);
    set({ welcome: turns.length === 0 });
    chatStatus("");
    afterPaint(() => { const users = document.querySelectorAll("#assistant-log .chat-msg.user"); chatReveal(users[users.length - 1] || null, "start"); });
  } catch (e) { if (g === gen) chatState(e.state, e.message); }
  finally { if (g === gen) set({ loading: false }); }
}
// '다시 확인': 이때만 setup 을 다시 부를 수 있다
export async function chatRetry() {
  set({ setupTried: false });
  await chatStart();
  afterPaint(() => (chat.ready ? $("assistant-q") : $("assistant-retry"))?.focus());
}

// 가게를 바꾸거나 로그인·로그아웃하면 (11/18): 서버가 상권 세션을 지웠으니 대화·조건을 비우고, 서랍이 열려 있으면 새 가게로 다시 시작
export function chatReset(epoch, open) {
  gen += 1;
  clearTimeout(armedTimer); clearTimeout(flashTimer); armedTimer = flashTimer = null;
  set((s) => ({ ...init(), draft: s.draft, epoch, status: { text: "", busy: false, srOnly: false, seq: ++seq } }));
  if (open) chatStart();
}
export const chatSeenEpoch = (epoch) => set({ epoch });
export { chatDisarm };
