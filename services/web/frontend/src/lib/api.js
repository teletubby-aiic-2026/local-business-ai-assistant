// 서버 부르기. 화면과 API 는 같은 주소(origin)에서 받는 것이 전제다 (CORS 없음, 쿠키는 브라우저가 알아서 보냄).
//
// 로그인 표시와 로그인·가게 상태 오류 (11/20 단계 전환, docs/api/contract.md 2.2):
// - 로그인한 동안(me.authenticated)은 모든 요청에 X-IC26-Signed-In: 1 을 붙인다 (authHeaders). 서버는 이 표시가 있는데
//   세션이 끝났으면 게스트로 답하지 않고 401 login_needed 를 준다.
// - 응답이 401 login_needed → expired(다시 로그인), 409 no_store → pick(가게 선택), 403 not_your_store → forbidden 으로 화면을 바꾼다
//   (handleAuthError). 로그인 실패(401 bad_login)·비밀번호 틀림(401 bad_password) 같은 것은 부른 화면이 그대로 보여 준다.
// - 공통 api()·serviceApi() 는 이 둘을 알아서 한다. 따로 fetch 하는 곳은 authHeaders() 를 헤더에 펼쳐 넣고,
//   실패한 응답의 status·error.state 로 handleAuthError({status, state}) 를 부르면 된다.
import { getState } from "../state/store.js";
import { authFail } from "../state/stage.js";

export const SIGNED_IN_HEADER = "X-IC26-Signed-In";

export function authHeaders() {
  const me = getState().me;
  return me && me.authenticated ? { [SIGNED_IN_HEADER]: "1" } : {};
}

// 상태 코드 + error.state → 바꿀 단계 (없으면 null)
export function authStageOf(status, state) {
  if (status === 401 && state === "login_needed") return "expired";
  if (status === 409 && state === "no_store") return "pick";
  if (status === 403 && state === "not_your_store") return "forbidden";
  return null;
}

// 오류(또는 {status, state})를 보고 단계를 바꿨으면 true. 오류 객체에는 authHandled 를 단다 (부른 쪽이 알림 띠를 또 띄우지 않게)
export function handleAuthError(err) {
  const to = authStageOf(err && err.status, err && err.state);
  if (!to) return false;
  const done = authFail(to);
  if (done && err && typeof err === "object") err.authHandled = true;
  return done;
}

// 비서 화면 서버의 /api/* (예전 app.js 의 api()와 같은 규칙).
// 오류 문장은 error.message → detail[0].msg → '요청 실패 (코드)' 순서로 고른다 (docs/api/contract.md 0.5).
export async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...authHeaders(), ...(options.headers || {}) };
  const res = await fetch(path, { ...options, headers });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(body?.error?.message || body?.detail?.[0]?.msg || `요청 실패 (${res.status})`);
    err.status = res.status;
    err.state = body?.error?.state;
    err.body = body;
    handleAuthError(err);
    throw err;
  }
  return body;
}

// 다른 서비스를 대신 불러 주는 프록시(/api/care·/api/marketing-survey·/api/market·/api/assistant)용.
// 제한 시간이 있고, 실패하면 Error 에 status·state(서버가 준 error.state, 시간 초과는 'slow', 연결 실패는 'down')·body 를 붙인다.
// 이 오류는 그 화면 안에만 보여 준다 (맨 위 알림 띠를 쓰지 않음).
export async function serviceApi(path, options = {}, ms = 30000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  const headers = { ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...authHeaders(), ...(options.headers || {}) };
  try {
    const res = await fetch(path, { signal: ctl.signal, ...options, headers });
    const type = res.headers.get("content-type") || "";
    const body = type.includes("json") ? await res.json().catch(() => ({})) : {};
    if (!res.ok) {
      const err = new Error(body?.error?.message || (typeof body?.detail === "string" ? body.detail : "") || `요청 실패 (${res.status})`);
      err.status = res.status;
      err.state = body?.error?.state || (res.status === 504 ? "slow" : res.status >= 500 ? "down" : "invalid");
      err.body = body;
      handleAuthError(err);
      throw err;
    }
    return body;
  } catch (e) {
    if (e.name === "AbortError") { const err = new Error("응답이 너무 오래 걸려요. 잠시 뒤 다시 해 주세요."); err.state = "slow"; throw err; }
    if (e instanceof TypeError) { const err = new Error("서버에 연결하지 못했어요. 잠시 뒤 다시 해 주세요."); err.state = "down"; throw err; }
    throw e;
  } finally { clearTimeout(timer); }
}
