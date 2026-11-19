// 상권 분석 화면의 모듈 상태와 동작 (예전 app.js 의 mkv·marketApi·mkvStart·mkvLoad·mkvApply·mkvHome·mkvCompare·mkvSync·mkvEvents).
// - 이 서버의 /api/market/* 만 부른다. 공통 api()·맨 위 띠를 쓰지 않아 상권 서비스가 꺼져도 안내는 이 화면 안에만.
// - 분석 조건은 상권 서비스의 세션에 있고, 화면은 서버가 준 조건(conditions)을 그대로 보여 준다 (가게 기본 조건 여부도 서버가 판단: home).
// - 화면을 떠났다 와도 조건·받은 자료·탭·비교 결과가 남도록 화면 밖(이 모듈)에 둔다. 가게가 바뀌면(epoch) 처음으로 (예전 mkvReset).
import { useSyncExternalStore } from "react";
import { getState, setState as setApp } from "../../state/store.js";
import { condText, dataStatusText, syncText, withQuery } from "./format.js";

export const MKV_TABS = ["sales", "stores", "pop", "compare"];
const MKV_WAIT_MS = 30000;
export const CMP_HINT = "우리 가게 상권과 비교할 상권을 골라 주세요.";

async function marketApi(path, options = {}, ms = MKV_WAIT_MS) {
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), ms);
  try {
    const res = await fetch("/api/market/" + path, { headers: { "Content-Type": "application/json" }, signal: ctl.signal, ...options });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error((body && body.error && body.error.message) || `상권 분석 요청 실패 (${res.status})`);
      err.state = body && body.error && body.error.state; err.status = res.status;
      throw err;
    }
    return body;
  } catch (e) {
    if (e.name === "AbortError") { const err = new Error("상권 서비스가 답하는 데 너무 오래 걸렸어요. 잠시 뒤 다시 해 주세요."); err.state = "error"; throw err; }
    throw e;
  } finally { clearTimeout(timer); }
}

// 가게가 바뀌면 비우는 것. 탭·업종 목록·동기화 중 여부·처리한 nav 번호는 남긴다 (예전 mkvReset 이 건드리지 않던 것)
const blank = () => ({
  started: false, cond: null, condLine: "", options: null, data: {}, cmp: null, cmpLoading: -1, events: false,
  status: "", warn: false,           // 화면 위 안내 (예전 #mk-state)
  busy: true,                         // 조건 고르기·버튼 잠금 (예전 mkvBusy)
  storeLine: "",                      // 가게 이름 · 가까운 역 · 업종 (예전 #mk-store)
  dataLine: "자료 상태를 불러오는 중…", // 예전 #mk-data
  syncLine: "", syncWarn: false,      // 예전 #mk-sync-result
  eventsNote: "", eventsList: null, eventsMsg: "", eventsNotice: "",
  pick: { area: "", industry: "", period: "" },      // 고르는 중인 조건 (적용 전)
  cmpPick: { district: "", area: "" },
  cmpResult: { kind: "hint", text: CMP_HINT },         // hint·loading·error·table
  cmpRunning: false,
});

let m = { ...blank(), gen: 0, epoch: null, tab: "sales", industries: null, syncing: false, navSeq: 0 };
const listeners = new Set();
const set = (patch) => { m = { ...m, ...(typeof patch === "function" ? patch(m) : patch) }; listeners.forEach((l) => l()); };
const subscribe = (l) => { listeners.add(l); return () => listeners.delete(l); };
export const getMarket = () => m;
export const useMarket = () => useSyncExternalStore(subscribe, () => m);

// 이 응답을 아직 써도 되는가: 같은 요청 차례이고 가게가 그대로
const live = (gen) => gen === m.gen && m.epoch === getState().epoch;
const state = (msg, warn = false) => set({ status: msg || "", warn });

function resetIfStoreChanged() {
  const epoch = getState().epoch;
  if (m.epoch === epoch) return;
  set((s) => ({ ...blank(), gen: s.gen + 1, epoch }));
}

// 화면을 열 때마다 (예전 mkvOpen): 처음이면 시작, 문화행사는 못 받았으면 다시
export function marketOpen() {
  resetIfStoreChanged();
  if (!m.started) { set({ started: true }); start(); }
  if (!m.events) loadEvents();
}

async function start() {
  const gen = m.gen + 1;
  set({ gen, busy: true });
  state("상권 자료를 확인하고 있어요");
  try {
    const st = await marketApi("status", {}, 10000);
    if (!live(gen)) return;
    setApp({ staffMarket: st });   // AI 비서 칸의 상권 분석 비서
    set({ dataLine: dataStatusText(st.data), storeLine: st.store ? `${st.store.name} · ${st.store.station_name} · ${st.store.business_type_name}` : "" });
    if (st.state !== "ready") { state(st.message || "상권 서비스에 연결하지 못했어요. 잠시 뒤 다시 확인해 주세요.", true); return; }
    const s = await marketApi("setup", { method: "POST" });
    if (!live(gen)) return;
    if (!s.conditions) { state(s.message || "우리 가게 상권을 정하지 못했어요.", true); return; }
    await load(s.conditions, gen);
  } catch (e) { if (live(gen)) state(e.message, true); }
}

// 조건 하나로 화면 전체를 그린다 (보기 목록 · 핵심 지표 · 지금 탭)
async function load(cond, gen) {
  set({ cond, condLine: condText(cond) });
  state("");
  const [opts, all] = await Promise.all([marketApi("analysis-options"), m.industries ? Promise.resolve(null) : marketApi("options")]);
  if (!live(gen)) return;
  set({ options: opts, ...(all ? { industries: all.industries || [] } : {}), pick: { area: cond.area_code, industry: cond.industry_code, period: cond.period } });
  const rev = cond.revision != null ? `expected_revision=${encodeURIComponent(cond.revision)}` : "";
  const q = (path, extra = "") => marketApi(withQuery(path, extra, rev));
  const names = ["sales", "stores", "pop", "ctx", "yoy"];
  const got = await Promise.allSettled([q("sales"), q("stores"), q("population"), q("area-context"), q("changes", "comparison=yoy")]);
  if (!live(gen)) return;
  if (got.some((r) => r.status === "rejected" && r.reason && r.reason.status === 409)) {   // 다른 화면에서 조건이 바뀜 → 서버의 지금 조건으로 한 번 더
    const s = await marketApi("setup", { method: "POST" });
    if (!live(gen)) return;
    if (s.conditions && s.conditions.revision !== cond.revision) return load(s.conditions, gen);
  }
  const data = {};
  got.forEach((r, i) => { data[names[i]] = r.status === "fulfilled" ? r.value : { error: r.reason ? r.reason.message : "불러오지 못했어요" }; });
  set({ data, busy: false });
  if (m.tab === "compare" && !m.cmp) loadCompareOptions();
}

// 고를 수 있는 분기 (최신 먼저)
export const periodsOf = (s, area) => {
  const cand = ((s.options && s.options.candidates) || []).find((a) => a.area_code === area);
  return ((cand && cand.available_periods) || []).slice().sort().reverse();
};

export function pickArea(area) {   // 예전 mkvPeriods: 상권을 바꾸면 분기 목록을 다시 (보던 분기가 없으면 최신)
  const periods = periodsOf(m, area);
  set({ pick: { ...m.pick, area, period: (m.cond && m.cond.period) || periods[0] || "" } });
}
export const pickIndustry = (industry) => set({ pick: { ...m.pick, industry } });
export const pickPeriod = (period) => set({ pick: { ...m.pick, period } });

export async function apply({ area, period, industry }) {
  const gen = m.gen + 1;
  set({ gen, busy: true });
  state("조건을 바꾸고 있어요");
  try {
    let sel = await marketApi("analysis-selection");
    const profile = sel.profile || {};
    if (industry && profile.industry && industry !== profile.industry.code) {
      sel = await marketApi("profile", { method: "POST", body: JSON.stringify({
        location: { kind: "station", station_id: profile.location && profile.location.station_id }, industry_code: industry,
        business_status: profile.business_status || "operating", expected_revision: sel.revision }) });
    }
    const opts = await marketApi("analysis-options");
    const cands = (opts.candidates || []).filter((a) => !a.selection_blocked_reason);
    const pick = cands.find((a) => a.area_code === area) || cands[0];
    if (!pick) { if (live(gen)) { state("이 업종은 고를 수 있는 상권이 없어요.", true); set({ busy: false }); } return; }
    const periods = (pick.available_periods || []).slice().sort();
    const per = periods.includes(period) ? period : periods[periods.length - 1];
    const fresh = await marketApi("analysis-selection");
    await marketApi("analysis-selection", { method: "POST", body: JSON.stringify({ area_code: pick.area_code, period: per,
      expected_revision: fresh.revision, expected_catalog_version: opts.catalog_version }) });
    const s = await marketApi("setup", { method: "POST" });
    if (!live(gen)) return;
    set({ cmp: null });
    await load(s.conditions, gen);
  } catch (e) { if (live(gen)) { state(e.message, true); set({ busy: false }); } }
}

export async function home() {
  const gen = m.gen + 1;
  set({ gen, busy: true });
  state("우리 가게 기준으로 되돌리고 있어요");
  try {
    const s = await marketApi("setup?force=1", { method: "POST" });
    if (!live(gen)) return;
    set({ cmp: null });
    if (s.conditions) await load(s.conditions, gen); else state(s.message || "우리 가게 상권을 정하지 못했어요.", true);
  } catch (e) { if (live(gen)) { state(e.message, true); set({ busy: false }); } }
}

// 탭 고르기 (예전 mkvTab). 비교 탭을 처음 열면 비교할 상권 목록을 받는다
export function setTab(name) {
  set({ tab: MKV_TABS.includes(name) ? name : "sales" });
  if (m.tab === "compare" && m.cond && !m.cmp) loadCompareOptions();
}
export const markNav = (seq) => { m.navSeq = seq; };   // 다시 그리지 않아도 되는 기록

async function loadCompareOptions() {
  if (m.cmpLoading === m.gen) return;   // 탭을 여러 번 눌러도 한 번만 (조건이 바뀌어 차례가 넘어가면 새로)
  const gen = m.gen, cond = m.cond;
  set({ cmpLoading: gen, cmpResult: { kind: "loading", text: "비교할 상권 목록을 불러오는 중…" } });
  try {
    const o = await marketApi(withQuery("comparison-options", cond.revision != null ? `expected_revision=${encodeURIComponent(cond.revision)}` : ""));
    if (!live(gen)) return;
    const here = ((m.options && m.options.candidates) || []).find((a) => a.area_code === cond.area_code);
    const district = (here && here.district_code) || ((o.districts || [])[0] || {}).code || "";
    set({ cmp: o, cmpPick: { district, area: "" }, cmpResult: { kind: "hint", text: CMP_HINT } });
  } catch (e) { if (live(gen)) set({ cmpResult: { kind: "error", text: e.message } }); }
  finally { if (m.cmpLoading === gen) set({ cmpLoading: -1 }); }
}

// 고른 구의 비교할 상권 (우리 상권 빼고)
export const compareAreasOf = (s) => ((s.cmp && s.cmp.areas) || [])
  .filter((a) => a.district_code === s.cmpPick.district && a.area_code !== (s.cond && s.cond.area_code));
export const pickCompareDistrict = (district) => set({ cmpPick: { district, area: "" } });
export const pickCompareArea = (area) => set({ cmpPick: { ...m.cmpPick, area } });

export async function compare(code) {
  if (!code) return;
  const gen = m.gen, cond = m.cond;
  set({ cmpRunning: true, cmpResult: { kind: "loading", text: "비교하는 중…" } });
  try {
    const r = await marketApi(`comparison?comparison_area_code=${encodeURIComponent(code)}${cond.revision != null ? `&expected_revision=${encodeURIComponent(cond.revision)}` : ""}`);
    if (!live(gen)) return;
    set({ cmpResult: { kind: "table", r, cond } });
  } catch (e) { if (live(gen)) set({ cmpResult: { kind: "error", text: e.message } }); }
  finally { set({ cmpRunning: false }); }
}

// 서울 열린데이터광장 실시간 확인 (60초까지 기다리는 서버라 70초)
export async function sync() {
  if (m.syncing) return;
  set({ syncing: true, syncLine: "", syncWarn: false });
  const epoch = m.epoch;
  try {
    const r = await marketApi("data-sync", { method: "POST", body: "{}" }, 70000);
    set({ syncLine: syncText(r), syncWarn: r.status !== "up_to_date" });
    try {
      const st = await marketApi("status", {}, 8000);
      setApp({ staffMarket: st });
      if (epoch === m.epoch) set({ dataLine: dataStatusText(st.data) });
    } catch { /* 자료 상태는 다음에 */ }
  } catch (e) { set({ syncLine: e.message, syncWarn: true }); }
  finally { set({ syncing: false }); }
}

async function loadEvents() {
  set({ events: true });
  const epoch = m.epoch;
  try {
    const r = await marketApi("cultural-events", {}, 20000);
    if (epoch !== m.epoch) return;
    set({
      eventsNote: r.demo ? "(예시 · 실제 행사 아님)" : `(${r.district || "서울"}${r.fallback ? " 행사가 없어 서울 전체" : ""} · 서울시 문화행사 정보)`,
      eventsList: (r.events || []).slice(0, 8), eventsMsg: "", eventsNotice: r.notice || "",
    });
  } catch (e) { if (epoch === m.epoch) set({ eventsList: null, eventsMsg: e.message, events: false }); }
}

// 시험에서만 쓴다
export function resetMarketForTest() { m = { ...blank(), gen: 0, epoch: null, tab: "sales", industries: null, syncing: false, navSeq: 0 }; }
