// 종합 리포트의 모듈 상태와 불러오기 (예전 app.js 의 rp·loadReport·rpDaily·rpScore·rpMonth·rpMarketing 의 승인 기록·rpReady).
// - 칸마다 따로 부른다: 오늘 요약(/api/care/report/daily) · 응대 점수(/api/care/response) · 월간 보고서(/api/care/report/monthly).
//   손님 칭찬 요약은 월간 응답의 praise 칸으로 그린다 (요청을 더하지 않음). 한 칸이 실패해도 다른 칸은 그대로.
// - 이 화면을 열어도 AI(HCX)를 새로 부르지 않는다 (/api/cards·/api/briefing·글 만들기·서랍을 부르지 않음).
// - 화면을 떠났다 와도 고른 달·받은 값이 남도록 화면 밖(이 모듈)에 둔다. 가게가 바뀌면(epoch) 처음으로 (예전 rp.loadedAt = 0; rp.month = null).
import { useSyncExternalStore } from "react";
import { getState } from "../../state/store.js";
import { careApi } from "./careApi.js";
import { clocksOf } from "./format.js";

const LOADING = "불러오는 중…";
export const NO_PRAISE = "이 서버의 리뷰 분석 서비스는 아직 손님 칭찬 요약을 보내지 않아요.";

// msg: 칸 위 상태 글 (비면 숨김), bad: 오류 모양
const blank = () => ({
  month: null, maxMonth: null,   // 보고 있는 달 · 서버의 이번 달 (달 없이 부른 값)
  loadedAt: 0, loading: null,    // 세 응대 칸을 마지막으로 다 읽은 시각 · 읽는 중인 약속
  monthSeq: 0,                   // 달을 빨리 여러 번 옮겨도 마지막 요청만 쓴다
  daily: { data: null, msg: LOADING, bad: false },
  score: { data: null, pending: [], clocks: [], peak: false, fetchedAt: 0, msg: LOADING, bad: false },
  monthly: { data: null, msg: LOADING, bad: false },
  praise: { msg: LOADING, bad: false },
  appr: { text: "승인 기록을 불러오는 중…", busy: 0 },   // 마케팅 요약의 서버 승인 기록 · 불러오는 중인 수 (예전 mktBusy)
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

// force: '다시 불러오기'. 화면을 연 지 3초 안에 다시 열면(시험용 이중 마운트 포함) 고객응대 칸은 한 번만 부른다
export function loadReport(force = false) {
  if (r.loading) return r.loading;
  if (!force && Date.now() - r.loadedAt < 3000) return Promise.resolve();
  const ep = r.epoch;
  const p = Promise.all([loadDaily(), loadScore(), loadMonth(r.month)])
    .finally(() => { if (ep === r.epoch) set({ loading: null, loadedAt: Date.now() }); });
  set({ loading: p });
  return p;
}

async function loadDaily() {
  const ep = r.epoch;
  set((s) => ({ daily: { ...s.daily, msg: LOADING, bad: false } }));
  try {
    const d = await careApi("/api/care/report/daily");
    if (ep === r.epoch) set({ daily: { data: d, msg: "", bad: false } });
  } catch (e) { if (ep === r.epoch) set({ daily: { data: null, msg: e.message, bad: true } }); }
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

export async function loadMonth(month) {
  const seq = r.monthSeq + 1, ep = r.epoch;
  const live = () => seq === r.monthSeq && ep === r.epoch;
  set((s) => ({ monthSeq: seq, monthly: { ...s.monthly, msg: LOADING, bad: false }, praise: { msg: LOADING, bad: false } }));
  try {
    const m = await careApi("/api/care/report/monthly" + (month ? `?month=${encodeURIComponent(month)}` : ""));
    if (!live()) return;
    // 달 없이 부른 값 = 서버의 이번 달 (다음 달 버튼의 끝)
    const maxMonth = !month || !r.maxMonth ? (r.maxMonth && r.maxMonth > m.month ? r.maxMonth : m.month) : r.maxMonth;
    set({ month: m.month, maxMonth, monthly: { data: m, msg: "", bad: false }, praise: m.praise ? { msg: "", bad: false } : { msg: NO_PRAISE, bad: false } });
  } catch (e) {
    if (!live()) return;
    set((s) => ({ month: month || s.month, monthly: { data: null, msg: e.message, bad: true }, praise: { msg: e.message, bad: true } }));
  }
}

// 마케팅 요약의 서버 승인 기록 수 (/api/approvals 는 저장된 기록만 읽음)
export async function loadApprovals() {
  const ep = r.epoch;
  set((s) => ({ appr: { text: "승인 기록을 불러오는 중…", busy: s.appr.busy + 1 } }));
  let text;
  try {
    const a = await careApi("/api/approvals");
    text = `서버에 남은 승인 기록 ${(a.items || []).length}건 (맞춤 마케팅 포함 · 이 방문자 기준)`;
  } catch (e) { text = `승인 기록을 불러오지 못했어요: ${e.message}`; }
  if (ep === r.epoch) set((s) => ({ appr: { text, busy: Math.max(0, s.appr.busy - 1) } }));
}

// PDF 저장 전에: 처음 불러오기가 끝났고 읽는 중인 칸이 없다
export const reportReady = () => getState().booted && !r.loading && !r.appr.busy;

// 시험에서만 쓴다
export function resetReportForTest() { r = { ...blank(), epoch: null }; }
