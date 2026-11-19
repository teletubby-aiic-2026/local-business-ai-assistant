// 처음 불러오기와 다시 불러오기 (예전 app.js boot·refresh·storeChanged·acctLoad·staff*)
import { api, serviceApi } from "../lib/api.js";
import { healthProblems } from "../lib/domain.js";
import { getState, setState, setAlert } from "./store.js";

const cardKey = (cards) => cards.map((p) => p.card.card_id + p.card.review_ids + p.card.snapshot_ids).join();

// 오늘 할 일 진행을 비운다 (카드가 바뀌었거나 가게가 바뀜)
export const emptyFlow = () => ({ results: {}, approved: new Set(), approvedLog: [], pending: {}, current: null, draftId: null });

export async function acctLoad() {
  let me = null;
  try { me = await api("/api/auth/me"); } catch { me = null; }
  setState({ me });
  if (me && me.notice) setAlert(me.notice);
  return me;
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

// 서버에 남은 이 방문자(로그인하면 사장님)의 맞춤 마케팅 승인 수 (글 id 가 mkt- 로 시작)
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

export async function boot() {
  await acctLoad();
  staffMarket();
  try { await loadAll(); setState({ bootError: "" }); }
  catch (e) { setAlert(e.message); setState({ bootError: e.message, insightError: `리뷰 분석을 불러오지 못했어요: ${e.message}` }); }
  setState({ booted: true });
}

// 가게가 바뀌었다 (로그인·로그아웃·가게 고르기·기록 지우기·탈퇴): 그 가게의 진행을 비우고 모든 화면을 새 가게로.
// 각 화면(맞춤 마케팅·상권 분석·서랍·종합 리포트)은 epoch 가 바뀌면 자기 상태를 처음으로 되돌린다.
export async function storeChanged() {
  setState((s) => ({ ...emptyFlow(), cards: [], insight: null, joined: [], reviewsById: {}, mktServer: 0, alert: "", acctNotice: "", acctBusy: true, epoch: s.epoch + 1 }));
  try { await loadAll(); setState({ bootError: "" }); }
  catch (e) { setAlert(e.message); }
  staffMarket();
  setState({ acctBusy: false });
}
