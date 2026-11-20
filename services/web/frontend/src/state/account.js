// 로그아웃·가게 바꾸기 (예전 app.js acctLogout·acctSwitch). 로그인·회원가입·내 계정 창은 features/account
import { api } from "../lib/api.js";
import { focusFirst } from "../lib/focus.js";
import { getState, setState, setAlert } from "./store.js";
import { storeChanged } from "./boot.js";

// 끝나면 상단 바의 [로그인](#acct-login)으로 포커스 (모든 화면을 다시 읽으며 화면 제목으로 갔던 포커스를 되돌림).
// 실패하면 로그인한 그대로이니 이름 버튼으로
export async function acctLogout() {
  if (getState().acctBusy) return;
  setState({ acctBusy: true });
  try {
    setState({ me: await api("/api/auth/logout", { method: "POST" }) });
    await storeChanged();
    focusFirst("acct-login", "acct-user");
  } catch (e) {
    setAlert(e.message);
    setState({ acctBusy: false });
    focusFirst("acct-user", "acct-login");
  }
}

// 가게를 바꾸면 모든 화면을 다시 읽는다. 끝나면 포커스를 가게 고르기 칸으로 돌려준다 (잠긴 사이 잃은 포커스)
export async function acctSwitch(storeId) {
  const { acctBusy, me } = getState();
  if (acctBusy || !me || storeId === me.store_id) return;
  setState({ acctBusy: true });
  try { setState({ me: await api("/api/auth/store", { method: "POST", body: JSON.stringify({ store_id: storeId }) }) }); await storeChanged(); }
  catch (e) { setAlert(e.message); setState({ acctBusy: false }); }
  focusFirst("acct-store", "acct-user", "acct-login");
}

// 로그인·회원가입·시연 계정 (창에서 부름). 성공하면 창을 닫고 모든 화면을 새 가게로. 실패하면 오류를 던진다 (창이 보여 줌)
export async function authDo(path, body) {
  const me = await api("/api/auth/" + path, { method: "POST", body: JSON.stringify(body || {}) });
  setState({ me, authOpen: false });
  await storeChanged();
  return me;
}

export const displayName = (me) => {
  const name = String(me?.user?.display_name || "");
  return name.endsWith("사장님") ? name : `${name} 사장님`;
};
