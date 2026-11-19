// 로그아웃·가게 바꾸기 (예전 app.js acctLogout·acctSwitch). 로그인·회원가입·내 계정 창은 features/account
import { api } from "../lib/api.js";
import { getState, setState, setAlert } from "./store.js";
import { storeChanged } from "./boot.js";

export async function acctLogout() {
  if (getState().acctBusy) return;
  setState({ acctBusy: true });
  try { setState({ me: await api("/api/auth/logout", { method: "POST" }) }); await storeChanged(); }
  catch (e) { setAlert(e.message); setState({ acctBusy: false }); }
}

export async function acctSwitch(storeId) {
  const { acctBusy, me } = getState();
  if (acctBusy || !me || storeId === me.store_id) return;
  setState({ acctBusy: true });
  try { setState({ me: await api("/api/auth/store", { method: "POST", body: JSON.stringify({ store_id: storeId }) }) }); await storeChanged(); }
  catch (e) { setAlert(e.message); setState({ acctBusy: false }); }
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
