// 오늘 할 일 진행(만든 글·승인 표시·고치는 중인 글)을 이 브라우저의 localStorage 에 보관하고 되살린다 (11/22 실사용 QA).
// 서버는 승인한 글만 저장하고 초안 본문은 두지 않아서(WAS 2대), 새로고침·다시 로그인한 뒤 이어서 하려면 화면이 들고 있어야 한다.
// - 키는 사장님·가게마다 `ic26.flow.v1:<user_id>:<store_id>` (다른 계정에는 보이지 않음). 로그아웃은 지우지 않는다
// - 쓰기는 store 의 flowKey 가 채워진 뒤에만 (boot.js refresh 가 되살리기를 시도한 뒤). storeChanged 가 비운 '빈 진행'으로
//   새 가게의 키를 지우지 않게 하려고
// - 되살리기는 v·카드(id·근거)·24시간 안을 모두 만족할 때만. 하나라도 어긋나면 키를 지운다
// localStorage 는 늘 try/catch 안에서 부른다 (못 쓰면 지금처럼 메모리만).
import { getState, subscribe } from "./store.js";
import { allDrafts } from "../lib/domain.js";

export const FLOW_PREFIX = "ic26.flow.v1:";
export const FLOW_VERSION = 1;
export const FLOW_TTL_MS = 24 * 60 * 60 * 1000;
export const FLOW_MAX_CHARS = 1500000;   // 이보다 크면 보관하지 않는다 (localStorage 한도가 5MB 안팎이라 다른 칸 몫을 남김)
const WRITE_MS = 200;                     // 글을 고치는 동안 글자마다 쓰지 않게 조금 모아서

// 카드의 id·근거가 같을 때만 같은 값 (카드가 바뀌면 만든 글을 버린다)
export const cardKey = (cards) => (cards || []).map((p) => p.card.card_id + p.card.review_ids + p.card.snapshot_ids).join();

// 사장님·가게의 키. 둘 중 하나라도 모르면 "" (보관하지 않음)
export function flowKeyOf(me) {
  const user = me?.user?.user_id, store = me?.store_id;
  return user && store ? `${FLOW_PREFIX}${user}:${store}` : "";
}

const isObj = (v) => !!v && typeof v === "object" && !Array.isArray(v);
const storage = () => { try { return window.localStorage; } catch { return null; } };

function removeKey(key) {
  try { storage()?.removeItem(key); } catch { /* 못 지워도 24시간 뒤에는 되살리지 않는다 */ }
}

// 보관할 모양. 진행이 모두 비었으면 null (키를 지움)
function pack(s) {
  const approved = [...s.approved];
  if (!Object.keys(s.results).length && !approved.length && !s.approvedLog.length && !Object.keys(s.pending).length) return null;
  return { v: FLOW_VERSION, at: new Date().toISOString(), cardKey: cardKey(s.cards), results: s.results, approved,
    approvedLog: s.approvedLog, pending: s.pending, current: s.current, draftId: s.draftId };
}

function write(key, s) {
  const data = pack(s);
  if (!data) { removeKey(key); return; }
  let text;
  try { text = JSON.stringify(data); } catch { return; }
  // 너무 크면 쓰지 않고, 앞서 쓴 옛 진행도 지운다 (옛 글을 되살리면 서버 기록과 어긋남)
  if (text.length > FLOW_MAX_CHARS) { removeKey(key); return; }
  try { storage()?.setItem(key, text); } catch { removeKey(key); }
}

// ── 쓰기: store 를 듣다가 진행 조각이 바뀌면 WRITE_MS 뒤에, 페이지를 떠날 때는 바로 ──
let queued = null;     // { key, s } 아직 쓰지 않은 마지막 상태
let timer = null;
let seen = null;       // { key, parts } 마지막으로 본 진행 조각 (같으면 쓰지 않음)
const partsOf = (s) => [s.results, s.approved, s.approvedLog, s.pending, s.current, s.draftId, s.cards];

export function flushFlowKeep() {
  clearTimeout(timer);
  timer = null;
  const q = queued;
  queued = null;
  if (q) write(q.key, q.s);
}

function onStore() {
  const s = getState();
  if (!s.flowKey) { flushFlowKeep(); seen = null; return; }   // 가게가 바뀜·로그아웃: 앞 가게 몫만 마저 쓰고 멈춘다
  const parts = partsOf(s);
  // 키가 막 채워졌다(되살린 직후): 되살린 것을 다시 쓰지 않는다 (새로고침만으로 저장 시각이 늘어나 24시간이 끝없이 밀리지 않게)
  if (!seen || seen.key !== s.flowKey) { flushFlowKeep(); seen = { key: s.flowKey, parts }; return; }
  if (parts.every((p, i) => p === seen.parts[i])) return;
  seen = { key: s.flowKey, parts };
  queued = { key: s.flowKey, s };
  clearTimeout(timer);
  timer = setTimeout(flushFlowKeep, WRITE_MS);
}

if (typeof window !== "undefined") {
  subscribe(onStore);
  window.addEventListener("pagehide", flushFlowKeep);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") flushFlowKeep(); });
}

// ── 지우기 ──
function dropQueued(match) {
  if (queued && match(queued.key)) { clearTimeout(timer); timer = null; queued = null; }
}

// 한 가게의 진행 ('처음부터 다시', 그 가게 기록 지우기, 카드가 바뀜)
export function forgetFlow(key) {
  if (!key) return;
  dropQueued((k) => k === key);
  removeKey(key);
}

// 이 사장님의 모든 가게 진행 (모든 가게 기록 지우기, 회원 탈퇴)
export function forgetUserFlows(userId) {
  if (!userId) return;
  const prefix = `${FLOW_PREFIX}${userId}:`;
  dropQueued((k) => k.startsWith(prefix));
  const ls = storage();
  if (!ls) return;
  try {
    const keys = [];
    for (let i = 0; i < ls.length; i++) { const k = ls.key(i); if (k && k.startsWith(prefix)) keys.push(k); }
    keys.forEach(removeKey);
  } catch { /* 못 지워도 24시간 뒤에는 되살리지 않는다 */ }
}

// ── 되살리기 ──
// 보관한 진행을 읽는다. v·카드·24시간 중 하나라도 어긋나거나 모양이 틀리면 키를 지우고 null
export function loadFlow(key, cards, now = Date.now()) {
  if (!key) return null;
  let saved = null;
  try { const text = storage()?.getItem(key); saved = text ? JSON.parse(text) : null; } catch { saved = null; }
  if (saved === null) return null;
  const at = Date.parse(saved?.at);
  const ok = isObj(saved) && saved.v === FLOW_VERSION && saved.cardKey === cardKey(cards)
    && Number.isFinite(at) && Math.abs(now - at) <= FLOW_TTL_MS
    && isObj(saved.results) && Array.isArray(saved.approved) && Array.isArray(saved.approvedLog) && isObj(saved.pending);
  if (!ok) { removeKey(key); return null; }
  return saved;
}

// 승인 기록으로 셀 서버 항목 (status 가 없으면 승인으로 본다, calc.js mergeApprovals 와 같은 규칙)
const approvedIds = (items) => new Set(items.filter((x) => x && x.draft_id && (!x.status || x.status === "approved")).map((x) => x.draft_id));

// 되살릴 store 조각. results 에 없는 글의 승인·고치는 중인 글은 버리고, 서버 승인 목록(items)을 읽었으면 거기 없는 승인 표시는 푼다
// (다른 곳에서 기록을 지웠을 수 있음). items 가 배열이 아니면(못 읽음) 보관한 그대로
export function restoredFlow(saved, items) {
  const ids = new Set(allDrafts(saved.results).map((d) => d.draft_id));
  const server = Array.isArray(items) ? approvedIds(items) : null;
  const kept = (id) => !server || server.has(id);
  const pending = {};
  Object.entries(saved.pending).forEach(([id, text]) => { if (ids.has(id) && typeof text === "string") pending[id] = text; });
  return {
    results: saved.results,
    approved: new Set(saved.approved.filter((id) => ids.has(id) && kept(id))),
    approvedLog: saved.approvedLog.filter((a) => isObj(a) && a.id && kept(a.id)),
    pending,
    current: typeof saved.current === "string" && saved.results[saved.current] ? saved.current : null,
    draftId: typeof saved.draftId === "string" && ids.has(saved.draftId) ? saved.draftId : null,
  };
}
