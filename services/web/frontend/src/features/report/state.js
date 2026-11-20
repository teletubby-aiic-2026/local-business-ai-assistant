// 종합 리포트의 모듈 상태와 불러오기 (6차 회의 11/20: 주간·월간 탭, 계정별 저장).
// - 위 요약 줄은 그때그때: 오늘 요약(/api/care/report/daily) · 응대 점수(/api/care/response). 저장하지 않는다.
// - 탭(주간·월간)의 보고서는 /api/reports/{weekly|monthly}?period= — 서버가 저장본이 있으면 저장본을, 없으면 만들어 저장해 준다
//   (로그인한 사장님만 저장. 게스트는 계산만). '다시 만들기'는 POST /api/reports/{종류}/regenerate. 목록은 /api/reports/saved.
// - 마케팅 요약 칸의 서버 승인 기록 수는 /api/approvals.
// - 이 화면을 열어도 AI(HCX)를 새로 부르지 않는다 (/api/cards·/api/briefing·글 만들기·서랍을 부르지 않음). 보고서 숫자는 규칙 계산.
// - 화면을 떠났다 와도 고른 탭·기간·받은 값이 남도록 화면 밖(이 모듈)에 둔다. 가게가 바뀌면(epoch) 처음으로.
// - 탭은 주소(해시)가 아니라 이 모듈의 상태다 (화면 주소는 8개 고정).
import { useSyncExternalStore } from "react";
import { getState } from "../../state/store.js";
import { careApi } from "./careApi.js";
import { clocksOf } from "./format.js";

const LOADING = "불러오는 중…";
export const KINDS = ["weekly", "monthly"];

const sheet = () => ({ data: null, msg: LOADING, bad: false, seq: 0 });
// msg: 칸 위 상태 글 (비면 숨김), bad: 오류 모양
const blank = () => ({
  tab: "weekly",                 // 보고 있는 탭
  loadedAt: 0, loading: null,    // 위 요약 줄을 마지막으로 다 읽은 시각 · 읽는 중인 약속
  busy: null,                    // 보고서를 여는 중(open) · 다시 만드는 중(remake)
  daily: { data: null, msg: LOADING, bad: false },
  score: { data: null, pending: [], clocks: [], peak: false, fetchedAt: 0, msg: LOADING, bad: false },
  weekly: sheet(), monthly: sheet(),                    // 탭마다 연 보고서 (/api/reports/* 응답)
  saved: { items: [], storage: null, msg: LOADING, bad: false },   // 저장된 보고서 목록
  appr: { text: "승인 기록을 불러오는 중…", busy: 0 },   // 마케팅 요약의 서버 승인 기록 · 불러오는 중인 수
});

let r = { ...blank(), epoch: null };
const listeners = new Set();
const set = (patch) => { r = { ...r, ...(typeof patch === "function" ? patch(r) : patch) }; listeners.forEach((l) => l()); };
const subscribe = (l) => { listeners.add(l); return () => listeners.delete(l); };
export const getReport = () => r;
export const useReport = () => useSyncExternalStore(subscribe, () => r);

// 화면을 그리기 전에 부른다. 가게가 바뀌었으면 알리지 않고 처음으로 (그리는 중이라 구독자에게 알리지 않음)
export function resetIfStoreChanged() {
  const epoch = getState().epoch;
  if (r.epoch !== epoch) r = { ...blank(), epoch };
}

const reportPath = (kind, key, remake) =>
  "/api/reports/" + kind + (remake ? "/regenerate" : "") + (key ? `?period=${encodeURIComponent(key)}` : "");

// 화면을 열 때: 위 요약 줄 + 지금 탭의 보고서 + 저장 목록. force: '다시 만들기'가 같이 부름.
// 화면을 연 지 3초 안에 다시 열면(시험용 이중 마운트 포함) 한 번만
export function loadReport(force = false) {
  if (r.loading) return r.loading;
  if (!force && Date.now() - r.loadedAt < 3000) return Promise.resolve();
  const ep = r.epoch;
  const tab = r[r.tab];
  const p = Promise.all([loadDaily(), loadScore(), tab.data && !force ? null : openReport(r.tab, tab.data?.period?.key), loadSaved()])
    .finally(() => { if (ep === r.epoch) set({ loading: null, loadedAt: Date.now() }); });
  set({ loading: p });
  return p;
}

// quiet: '다시 만들기'가 같이 부를 때. 보이던 값을 두고 조용히 바꾼다 (실패하면 그대로)
async function loadDaily(quiet = false) {
  const ep = r.epoch;
  if (!quiet) set((s) => ({ daily: { ...s.daily, msg: LOADING, bad: false } }));
  try {
    const d = await careApi("/api/care/report/daily");
    if (ep === r.epoch) set({ daily: { data: d, msg: "", bad: false } });
  } catch (e) { if (!quiet && ep === r.epoch) set({ daily: { data: null, msg: e.message, bad: true } }); }
}

// quiet: 1분마다 다시 부르기. 실패하면 보이던 값을 그대로 둔다
export async function loadScore(quiet = false) {
  const ep = r.epoch;
  if (!quiet) set((s) => ({ score: { ...s.score, msg: LOADING, bad: false } }));
  try {
    const res = await careApi("/api/care/response");
    if (ep !== r.epoch) return;
    const fetched = Date.now();
    const pending = Array.isArray(res.pending) ? res.pending : [];
    const peak = res.peak_now === true;
    set({ score: { data: res, pending, peak, clocks: clocksOf(pending, peak, fetched), fetchedAt: fetched, msg: "", bad: false } });
  } catch (e) {
    if (quiet || ep !== r.epoch) return;
    set({ score: { data: null, pending: [], clocks: [], peak: false, fetchedAt: 0, msg: e.message, bad: true } });
  }
}

// 보고서 열기 (key 가 없으면 이번 주·이번 달). remake: 새로 계산해 저장본을 덮어씀.
// 기간을 빨리 여러 번 옮겨도 마지막 요청만 쓴다 (탭마다 seq). 실패하면 보이던 보고서는 두고 오류 글만
export async function openReport(kind, key, remake = false) {
  if (!KINDS.includes(kind)) return;
  const seq = r[kind].seq + 1, ep = r.epoch;
  const live = () => seq === r[kind].seq && ep === r.epoch;
  set((s) => ({ busy: remake ? "remake" : "open", [kind]: { ...s[kind], seq, msg: remake ? "다시 만드는 중…" : LOADING, bad: false } }));
  try {
    const data = await careApi(reportPath(kind, key, remake), remake ? { method: "POST" } : {});
    if (!live()) return;
    set((s) => ({ busy: null, [kind]: { ...s[kind], data, msg: "", bad: false } }));
    if (data.made_now && data.saved) loadSaved();      // 새로 저장했으면 목록도 새로
  } catch (e) {
    if (!live()) return;
    set((s) => ({ busy: null, [kind]: { ...s[kind], msg: e.message, bad: true } }));
  }
}

// 탭 바꾸기: 그 탭을 처음 열면 이번 기간을 부른다 (탭마다 보던 기간은 남음)
export function setTab(kind) {
  if (!KINDS.includes(kind) || r.tab === kind) return;
  set({ tab: kind });
  if (!r[kind].data && !r[kind].bad) openReport(kind, null);
}

// '다시 만들기': 지금 탭·지금 기간을 새로 계산해 저장하고, 위 요약 줄·목록·승인 기록도 새로
export function remakeReport() {
  const kind = r.tab, key = r[kind].data?.period?.key;
  loadDaily(!!r.daily.data);
  loadScore(true);
  loadApprovals();
  return openReport(kind, key, true);
}

// 저장된 보고서 목록의 [열기]
export function openSaved(item) {
  if (!item || !KINDS.includes(item.kind)) return Promise.resolve();
  set({ tab: item.kind });
  return openReport(item.kind, item.key);
}

export async function loadSaved() {
  const ep = r.epoch;
  try {
    const s = await careApi("/api/reports/saved");
    if (ep === r.epoch) set({ saved: { items: Array.isArray(s.items) ? s.items : [], storage: s.storage || null, msg: "", bad: false } });
  } catch (e) { if (ep === r.epoch) set((s) => ({ saved: { ...s.saved, msg: e.message, bad: true } })); }
}

// 마케팅 요약의 서버 승인 기록 수 (/api/approvals 는 저장된 기록만 읽음)
export async function loadApprovals() {
  const ep = r.epoch;
  set((s) => ({ appr: { text: "승인 기록을 불러오는 중…", busy: s.appr.busy + 1 } }));
  let text;
  try {
    const a = await careApi("/api/approvals");
    text = `서버에 남은 승인 기록 ${(a.items || []).length}건 (맞춤 마케팅 포함 · 이 계정 기준)`;
  } catch (e) { text = `승인 기록을 불러오지 못했어요: ${e.message}`; }
  if (ep === r.epoch) set((s) => ({ appr: { text, busy: Math.max(0, s.appr.busy - 1) } }));
}

// PDF 저장 전에: 처음 불러오기가 끝났고 읽는 중인 칸이 없다
export const reportReady = () => getState().booted && !r.loading && !r.busy && !r.appr.busy;

// 시험에서만 쓴다
export function resetReportForTest() { r = { ...blank(), epoch: null }; }
