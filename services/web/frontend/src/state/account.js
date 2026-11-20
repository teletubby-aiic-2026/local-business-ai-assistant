// 서버를 부르는 단계 전환: 로그인·회원가입·시연 시작(authDo), 가게 열기(openStore), 로그아웃(acctLogout), 탈퇴 뒤(signedOut).
// 화면은 features/account (A1 로그인 · A2 회원가입 · A3 가게 선택 · A5 사장님 프로필 · X1·X2), 단계 규칙은 state/stage.js
import { api } from "../lib/api.js";
import { go } from "../lib/router.js";
import { getState, setState, setAlert } from "./store.js";
import { clearStoreData, enterApp, storeChanged } from "./boot.js";
import { setStage, writeEntered } from "./stage.js";

// 로그인이 끝났다 (로그아웃·탈퇴): 들어간 가게·서랍·가게 자료를 지우고 로그인 화면으로. me 는 서버가 준 게스트 신원
export function signedOut(me) {
  writeEntered(null);
  clearStoreData();
  setStage("login", { me: me && me.authenticated === false ? me : { authenticated: false, user: null, store_id: null, stores: [], demo_login: !!(me && me.demo_login) },
    entered: null, resume: null, acctBusy: false });
}

export async function acctLogout() {
  if (getState().acctBusy) return;
  setState({ acctBusy: true });
  let me = null;
  try { me = await api("/api/auth/logout", { method: "POST" }); }
  catch (e) {
    if (!e.authHandled && e.status !== 401) { setAlert(e.message); setState({ acctBusy: false }); return; }
    // 이미 로그인이 끝나 있었다 (401): 로그아웃한 것과 같다
  }
  signedOut(me);
}

// 로그인·회원가입·시연 시작 (A1·A2 가 부름). 실패하면 오류를 던진다 (화면이 보여 줌).
// - 회원가입 → 새 가게 등록 (가게 0곳)
// - 로그인·시연 → 가게 선택. 단 로그인이 끝나 다시 로그인한 것이고(expired) 같은 사장님·같은 가게면 하던 화면(app)으로 바로
export async function authDo(path, body) {
  const me = await api("/api/auth/" + path, { method: "POST", body: JSON.stringify(body || {}) });
  const { resume, entered } = getState();
  setState({ me, resume: null, alert: "" });
  if (path === "signup") { writeEntered(null); clearStoreData(); setStage("store-new", { entered: null, storeNew: { mode: "signup" } }); return me; }
  const sameUser = resume && resume.userId && me.user && resume.userId === me.user.user_id;
  if (sameUser && resume.storeId && resume.storeId === me.store_id && entered === resume.storeId
      && (me.stores || []).some((s) => s.store_id === resume.storeId)) {
    setStage("app");
    // 로그인이 끝나 자료를 다 못 받았으면 다시 불러온다 (진행은 그대로 두려면 받은 자료가 있을 때 건너뜀)
    const s = getState();
    if (!s.briefing || s.bootError) storeChanged();
    return me;
  }
  // 새 로그인은 가게 선택부터 (다른 사장님이면 이 탭의 진행도 비움)
  writeEntered(null);
  if (entered || !sameUser) clearStoreData();
  setStage("pick", { entered: null });
  return me;
}

// A3 '이 가게 열기': 서버의 지금 가게를 바꾸고(POST /api/auth/store) 그 가게의 홈으로.
// 이미 들어가 자료를 받아 둔 가게를 다시 열면 서버를 부르지 않고 홈으로만 (하던 진행·상권 대화를 그대로 둠).
// 실패하면 오류를 던진다 (403 not_your_store 는 lib/api.js 가 forbidden 으로)
export async function openStore(storeId) {
  const s = getState();
  if (s.acctBusy || !storeId) return;
  if (s.entered === storeId && s.me && s.me.store_id === storeId && s.briefing && !s.bootError) {
    go("today");
    setStage("app");
    return;
  }
  setState({ acctBusy: true });
  let me;
  try { me = await api("/api/auth/store", { method: "POST", body: JSON.stringify({ store_id: storeId }) }); }
  catch (e) { setState({ acctBusy: false }); throw e; }
  setState({ me, acctBusy: false });
  go("today");
  await enterApp();
}

export const displayName = (me) => {
  const name = String(me?.user?.display_name || "");
  return name.endsWith("사장님") ? name : `${name} 사장님`;
};

// 이름 첫 글자 (동그라미)
export const initialOf = (name) => String(name || "").trim().slice(0, 1) || "사";

// 상단 바·가게 카드의 가게 한 줄: 이름(예시 가게면 ' (가상)') · '업종 · 상권'
export function storeLabel(s) {
  if (!s) return { name: "", sub: "" };
  return {
    name: `${s.name || ""}${s.sample ? " (가상)" : ""}`,
    sub: [s.business_type_name, s.area_name ? `${s.area_name} 상권` : ""].filter(Boolean).join(" · "),
  };
}

// 신원의 지금 가게 (없으면 null)
export const currentStore = (me) => ((me && me.stores) || []).find((x) => x.store_id === (me && me.store_id)) || null;
