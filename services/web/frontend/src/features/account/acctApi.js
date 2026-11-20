// 계정 화면(가게 선택·사장님 프로필)의 서버 부르기와 문장 (예전 app.js acctClearChat·acctPost·acctSummary·ACCT_ACTS).
// 가게 목록·요약·빼기·순서·이름·비밀번호는 공통 api() (로그인 표시 헤더와 401·409·403 단계 전환을 알아서 함)
import { api, authHeaders, handleAuthError } from "../../lib/api.js";

const enc = encodeURIComponent;
const json = (method, body) => ({ method, body: JSON.stringify(body) });

// GET /api/account/stores → {stores: [{store_id, name, business_type_name, area_name, station_name, sample, menu_count, last_opened}]}
export const listStores = () => api("/api/account/stores");
// 가게 카드의 숫자 줄: {state: ready|empty|unavailable, reviews, complaints, headline, tone: bad|good|muted}
export const storeSummary = (id) => api(`/api/account/stores/${enc(id)}/summary`);
// 내 가게에서 빼기 → {stores, store_id} (지금 보던 가게를 뺐으면 store_id 가 다른 가게 또는 null)
export const removeStore = (id) => api(`/api/account/stores/${enc(id)}`, { method: "DELETE" });
export const orderStores = (ids) => api("/api/account/stores/order", json("PUT", { store_ids: ids }));
export const saveProfile = (name) => api("/api/account/profile", json("PATCH", { display_name: name }));
export const changePassword = (current, next) => api("/api/account/password", json("POST", { current_password: current, new_password: next }));

// 가게 선택 순서: 마지막으로 본 가게를 맨 앞, 나머지는 서버 순서 그대로
export function pickOrder(stores) {
  const list = Array.isArray(stores) ? stores : [];
  return [...list.filter((s) => s.last_opened), ...list.filter((s) => !s.last_opened)];
}

const KEPT = ["가게 기본 리뷰와 상권 자료 같은 공용 자료", "계정과 로그인(아이디·비밀번호)"];
export const ACCT_ACTS = {
  store: {
    title: (n) => `${n} 기록을 지울까요?`,
    lead: (n) => `지금 보고 있는 ${n} 한 곳의 기록만 지워요. 다른 가게 기록은 그대로예요.`,
    gone: ["승인 기록(완료 목록)", "붙여넣은 리뷰와 그 분류·답글 상태", "저장된 주간·월간 보고서", "맞춤 마케팅 기록", "AI에게 묻기 대화"],
    kept: ["다른 가게의 기록", ...KEPT],
    go: "지우기", busy: "지우는 중…",
  },
  account: {
    title: () => "모든 가게 기록을 지울까요?",
    lead: (n, all) => `가진 가게 ${all}곳의 기록을 모두 지워요. 계정은 남아서 다시 로그인할 수 있어요.`,
    gone: ["모든 가게의 승인 기록(완료 목록)", "모든 가게의 붙여넣은 리뷰와 그 분류·답글 상태", "모든 가게의 저장된 주간·월간 보고서", "모든 가게의 맞춤 마케팅 기록", "AI에게 묻기 대화"],
    kept: KEPT,
    go: "모두 지우기", busy: "지우는 중…",
  },
  withdraw: {
    title: () => "회원 탈퇴할까요?",
    lead: (n, all, demo) => (demo
      ? "시연 계정과 그 기록을 지워요. 시연 계정으로 다시 시작하면 빈 기록부터예요."
      : `계정과 가진 가게 ${all}곳의 기록을 모두 지워요. 같은 아이디로 다시 로그인할 수 없어요.`),
    gone: ["모든 가게의 승인 기록(완료 목록)", "모든 가게의 붙여넣은 리뷰와 그 분류·답글 상태", "모든 가게의 저장된 주간·월간 보고서", "모든 가게의 맞춤 마케팅 기록", "AI에게 묻기 대화",
      "계정과 로그인(아이디·비밀번호)"],
    kept: ["가게 기본 리뷰와 상권 자료 같은 공용 자료"],
    go: "탈퇴하기", busy: "탈퇴하는 중…", irrev: "탈퇴하면 되돌릴 수 없어요.",
  },
};

export const isDemo = (me) => !!(me && me.user && me.user.demo);

// 지금 가게 이름 (없으면 '이 가게')
export function storeName(me) {
  const s = ((me && me.stores) || []).find((x) => x.store_id === (me && me.store_id));
  return (s && s.name) || "이 가게";
}

const MKT = { cleared: "지움", off: "꺼져 있어 지울 것 없음", failed: "못 지움" };
// 결과 한 줄: 가게별 지운 건수 (못 지운 칸은 '못 지움')
export function summary(r) {
  const n = (v, unit) => (v === null || v === undefined ? "못 지움" : `${v}${unit}`);
  return (Array.isArray(r && r.stores) ? r.stores : []).map((s) =>
    `${s.name || s.store_id}: 승인 기록 ${n(s.approvals, "건")} · 붙여넣은 리뷰 ${n(s.reviews, "건")} · 맞춤 마케팅 ${MKT[s.marketing] || "확인 못 함"}`).join(" / ");
}

// 상권 대화 지우기: 실패해도·꺼져 있어도 계속 (8초에서 끊음).
// 상권 대화 쿠키는 경로가 /api/assistant 라 auth 경로의 서버가 지우지 못해 화면이 먼저 부른다
export async function clearChat() {
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 8000);
  try { await fetch("/api/assistant/conversation", { method: "DELETE", credentials: "same-origin", cache: "no-store", headers: authHeaders(), signal: ctl.signal }); }
  catch { /* 상권 비서가 꺼져 있거나 늦으면 그냥 넘어간다 */ }
  finally { clearTimeout(timer); }
}

// /api/auth/reset · withdraw 호출. 실패하면 서버의 쉬운 문장(error.message)과 status·state 를 담은 Error.
// 401 login_needed 는 handleAuthError 가 '다시 로그인' 화면으로 바꾼다
const FAIL = {
  401: "로그인이 풀렸어요. 다시 로그인해 주세요.",
  404: "이 서버에는 아직 이 기능이 없어요.",
  422: "요청을 다시 확인해 주세요.",
  429: "너무 여러 번 시도했어요. 잠시 뒤 다시 해 주세요.",
};
export async function acctPost(path, body) {
  let res;
  try {
    res = await fetch(path, { method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json", ...authHeaders() }, body: JSON.stringify(body || {}) });
  } catch { throw Object.assign(new Error("서버에 연결하지 못했어요. 인터넷 연결을 확인하고 다시 눌러 주세요."), { status: 0, state: "down" }); }
  const data = await res.json().catch(() => null);
  if (res.ok && data) return data;
  const err = (data && data.error) || {};
  const msg = err.message || FAIL[res.status] || (res.ok ? "응답을 읽지 못했어요. 잠시 뒤 다시 확인해 주세요." : `요청이 실패했어요 (${res.status}). 잠시 뒤 다시 눌러 주세요.`);
  const e = Object.assign(new Error(msg), { status: res.status, state: err.state || "" });
  handleAuthError(e);
  throw e;
}
