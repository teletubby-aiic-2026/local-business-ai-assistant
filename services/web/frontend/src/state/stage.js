// 단계 전환 (6차 회의 11/20, Figma '06 설계 기준 화면'의 여정 F). 새 해시 주소 없이 상태의 stage 로 화면을 고른다 (App.jsx).
// 이 파일은 서버를 부르지 않는다 (lib/api.js 가 상태 코드를 보고 authFail 을 부르므로, 여기서 api 를 import 하면 서로 물림).
// 서버를 부르는 전환(로그인·가게 열기·로그아웃)은 state/account.js, 처음 불러오기는 state/boot.js.
import { getState, setState } from "./store.js";

export const STAGES = ["boot", "login", "signup", "pick", "store-new", "profile", "app", "error", "expired", "forbidden"];
// 로그인한 사장님만 있는 단계. 이 단계에서 받은 401 login_needed·409 no_store·403 not_your_store 만 화면을 바꾼다
const SIGNED_IN = new Set(["pick", "store-new", "profile", "app", "expired", "forbidden"]);

// 마지막으로 들어간 가게 (탭마다, 새로고침해도 남음). 새 로그인은 가게 선택부터라 로그인할 때 지운다
export const ENTERED_KEY = "ic26.entered";
export function readEntered() { try { return sessionStorage.getItem(ENTERED_KEY) || null; } catch { return null; } }
export function writeEntered(id) {
  try { if (id) sessionStorage.setItem(ENTERED_KEY, id); else sessionStorage.removeItem(ENTERED_KEY); } catch { /* 못 써도 이번 화면은 그대로 */ }
}

const hasStore = (me, id) => !!id && ((me && me.stores) || []).some((s) => s.store_id === id);

// 새로고침 뒤 바로 메인 화면으로 갈지: 이 탭에서 들어갔던 가게가 서버의 지금 가게이고 내 가게 목록에 있을 때
export function canResumeEntered(me) {
  const id = readEntered();
  return !!(me && me.authenticated && id && id === me.store_id && hasStore(me, id));
}

// 단계 바꾸기. 메인 화면을 떠나면 서랍을 닫는다 (서랍은 app 단계에만 있음)
export function setStage(stage, extra = {}) {
  if (!STAGES.includes(stage)) return;
  setState({ stage, ...(stage === "app" ? {} : { drawerOpen: false }), ...extra });
  try { window.scrollTo(0, 0); } catch { /* 시험 환경 */ }
}

export const goPick = () => setStage("pick");
export const goProfile = () => setStage("profile");
// 새 가게 등록 (mode: signup 회원가입 직후 · add 가게 더하기 · edit 정보 고치기).
// storeNewFrom: [취소]로 돌아갈 단계 (프로필에서 왔으면 profile, 그 밖은 가게 선택)
export const goStoreNew = (mode = "add", storeId) => setStage("store-new", {
  storeNew: { mode, ...(storeId ? { storeId } : {}) }, storeNewFrom: getState().stage === "profile" ? "profile" : "pick",
});

// 들어가 있던 가게로 (프로필 '가게로 돌아가기'). 그 가게가 아직 내 가게이고 지금 가게면 메인 화면, 아니면 가게 선택
export function backToStore() {
  const { me, entered } = getState();
  if (entered && entered === (me && me.store_id) && hasStore(me, entered)) setStage("app");
  else setStage("pick");
}

// lib/api.js 가 부른다. kind: expired(401 login_needed) · pick(409 no_store) · forbidden(403 not_your_store)
export function authFail(kind) {
  const s = getState();
  if (!SIGNED_IN.has(s.stage)) return false;   // 로그인 전 단계(부팅·로그인·가입·오류)에 늦게 온 응답은 무시
  if (kind === "expired") {
    if (s.stage === "expired") return true;
    const me = s.me || {};
    // 다시 로그인했을 때 같은 사장님·같은 가게면 하던 화면으로. 로그인 표시(헤더)는 끈다
    const resume = s.resume || { userId: (me.user && me.user.user_id) || null, storeId: s.entered || null,
      loginId: (me.user && !me.user.demo && me.user.login_id) || "" };
    setStage("expired", { resume, me: { authenticated: false, user: null, store_id: null, stores: [], demo_login: !!me.demo_login } });
    return true;
  }
  if (kind === "pick") {
    writeEntered(null);
    setStage("pick", { entered: null });
    return true;
  }
  if (kind === "forbidden") {   // 들어가 있던 가게가 더는 내 가게가 아니다: 새로고침해도 그 가게로 가지 않게
    writeEntered(null);
    setStage("forbidden", { entered: null });
    return true;
  }
  return false;
}
