// 처음 불러오기와 다시 불러오기 (예전 app.js boot·refresh·storeChanged·acctLoad·staff*).
// 11/20 단계 전환: 부팅은 /api/auth/me 로 단계(login · pick · app · error)를 정하고, 가게 자료(브리핑·카드·리뷰 분석·승인·상권 상태)는
// app 단계에 들어갈 때만 부른다. /api/health 는 모든 단계에서 부른다 (시험용 안내 띠가 로그인 화면에도 보여야 해서).
import { api, serviceApi } from "../lib/api.js";
import { healthProblems } from "../lib/domain.js";
import { getState, setState, setAlert } from "./store.js";
import { canResumeEntered, setStage, writeEntered } from "./stage.js";

const cardKey = (cards) => cards.map((p) => p.card.card_id + p.card.review_ids + p.card.snapshot_ids).join();

// 오늘 할 일 진행을 비운다 (카드가 바뀌었거나 가게가 바뀜)
export const emptyFlow = () => ({ results: {}, approved: new Set(), approvedLog: [], pending: {}, current: null, draftId: null });

// 지금 신원 다시 읽기. 실패하면 null (부르는 쪽이 판단)
export async function acctLoad() {
  let me = null;
  try { me = await api("/api/auth/me"); } catch { me = null; }
  if (me) setState({ me });
  return me;
}

// 서버 상태(시험용 실행 안내 띠 등). 실패해도 단계는 그대로 (띠만 못 띄움)
export async function loadHealth() {
  try { setState({ health: await api("/api/health") }); } catch { /* 가게 자료를 불러올 때 다시 부른다 */ }
}

// 리뷰 분석(요약·불만 묶음). 실패해도 홈·카드는 그대로 두고 분석 화면에만 알린다
export async function loadInsight() {
  try { setState({ insight: await api("/api/insight"), insightError: "" }); }
  catch (e) { setState({ insightError: `리뷰 분석을 불러오지 못했어요: ${e.message}` }); }
}

function reviewsOf(b) {
  const map = {};
  (b.groups || []).forEach((g) => (g.reviews || []).forEach((r) => (map[r.review_id] = r)));
  (b.pasted || []).forEach((r) => (map[r.review_id] = r));
  return map;
}

// 브리핑 → 카드 → 리뷰 분석. 카드의 id·근거가 바뀌면 만든 글·승인 표시·고친 내용을 버린다
export async function refresh() {
  const briefing = await api("/api/briefing");
  setState({ briefing, reviewsById: reviewsOf(briefing) });
  const data = await api("/api/cards");
  const before = cardKey(getState().cards), after = cardKey(data.cards || []);
  setState({ cards: data.cards || [], noCardB: data.no_card_b || "", ...(before && before !== after ? emptyFlow() : {}) });
  await loadInsight();
  staffApprovals();
}

// 서버에 남은 이 사장님의 맞춤 마케팅 승인 수 (글 id 가 mkt- 로 시작)
export async function staffApprovals() {
  try {
    const a = await api("/api/approvals");
    setState({ mktServer: (a.items || []).filter((x) => String(x.draft_id).startsWith("mkt-")).length });
  } catch { /* 못 읽어도 AI 비서 상태는 화면 기록으로 */ }
}

export async function staffMarket() {
  let m;
  try { m = await serviceApi("/api/market/status", {}, 8000); } catch (e) { m = { state: e.state || "down" }; }
  setState({ staffMarket: m });
}

async function loadAll() {
  const health = await api("/api/health");
  setState({ health });
  setAlert(healthProblems(health));
  await refresh();
}

// 부팅: 신원 → 단계. 신원을 못 받았거나(네트워크·5xx) 서버가 notice 를 주면 error([다시 시도]),
// 로그인 전이면 login, 로그인했으면 이 탭에서 들어갔던 가게가 그대로일 때 app(새로고침해도 보던 화면), 아니면 pick.
// toPick: X1 오류 카드의 [가게 선택으로]. 들어갔던 가게로 바로 가지 않고 가게 선택에서 멈춘다 (11/21 QA)
export async function boot({ toPick = false } = {}) {
  setState({ stage: "boot", stageError: "" });
  loadHealth();
  let me;
  try { me = await api("/api/auth/me"); }
  catch { setState({ me: null }); setStage("error", { stageError: "" }); return; }
  setState({ me });
  if (me.notice) { setStage("error", { stageError: me.notice }); return; }
  if (!me.authenticated) { setStage("login"); return; }
  if (!toPick && canResumeEntered(me)) { await enterApp(); return; }
  setStage("pick");
}

// 지금 가게(me.store_id)로 메인 화면에 들어가 그 가게의 자료를 처음부터 불러온다
export async function enterApp() {
  const id = (getState().me || {}).store_id || null;
  writeEntered(id);
  setStage("app", { entered: id, resume: null });
  await storeChanged();
}

// 가게 자료를 화면에서 비운다 (로그아웃·탈퇴: 다시 불러오지 않음). 각 화면은 epoch 가 바뀌면 자기 상태를 처음으로
export function clearStoreData() {
  setState((s) => ({ ...emptyFlow(), briefing: null, cards: [], noCardB: "", insight: null, insightError: "", joined: [], reviewsById: {},
    mktServer: 0, staffMarket: null, alert: "", booted: false, bootError: "", epoch: s.epoch + 1 }));
}

// 가게가 바뀌었다 (가게 열기·기록 지우기): 그 가게의 진행을 비우고 모든 화면을 새 가게로.
// 각 화면(맞춤 마케팅·상권 분석·서랍·종합 리포트)은 epoch 가 바뀌면 자기 상태를 처음으로 되돌린다.
// 401·409·403 으로 단계가 바뀌었으면(lib/api.js) 알림 띠를 띄우지 않는다
export async function storeChanged() {
  setState((s) => ({ ...emptyFlow(), briefing: null, cards: [], insight: null, joined: [], reviewsById: {}, mktServer: 0, alert: "", acctNotice: "",
    acctBusy: true, booted: false, bootError: "", epoch: s.epoch + 1 }));
  try { await loadAll(); setState({ bootError: "" }); }
  catch (e) {
    if (!e.authHandled) setAlert(e.message);
    setState({ bootError: e.message, insightError: `리뷰 분석을 불러오지 못했어요: ${e.message}` });
  }
  staffMarket();
  setState({ acctBusy: false, booted: true });
}
