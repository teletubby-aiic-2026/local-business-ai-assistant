// 맞춤 마케팅 전용 호출 (예전 app.js 의 mktApi·mktPost 를 그대로 옮김).
// 이 서버의 /api/marketing-survey/* 만 부르고 주소 뒤에 가게를 붙이지 않는다 (가게·방문자는 서버가 고정해 붙임).
// 공통 api()·맨 위 띠를 쓰지 않아서, 마케팅 서비스가 꺼져 있거나 느려도 안내는 이 화면 안에만 보인다.
// 로그인 표시 헤더(authHeaders)를 붙이고, 실패한 응답의 status·state 로 handleAuthError 를 불러 401·409·403 이면 단계를 바꾼다 (lib/api.js).
import { authHeaders, handleAuthError } from "../../lib/api.js";

const MKT_BASE = "/api/marketing-survey/";
const MKT_WAIT_MS = 15000;      // 질문·계산·보고서 (서버는 10초까지 기다림)
const MKT_LONG_MS = 60000;      // 글을 만드는 plan·generate·idea-try (서버는 45초까지, MARKETING_TIMEOUT_SEC)
const MKT_LONG = ["plan", "generate", "idea-try"];

// path 는 /api/marketing-survey/ 뒤 부분. 실패하면 message·state·status 를 담은 Error
export async function mktApi(path, options = {}) {
  const ctl = new AbortController();
  const name = String(path).split("?")[0];
  const timer = setTimeout(() => ctl.abort(), MKT_LONG.includes(name) ? MKT_LONG_MS : MKT_WAIT_MS);
  const fail = (message, st, status) => {
    const e = Object.assign(new Error(message), { state: st, status });
    handleAuthError(e);
    return e;
  };
  const headers = { Accept: "application/json", ...authHeaders() };
  if (typeof options.body === "string") headers["Content-Type"] = "application/json";
  try {
    const res = await fetch(MKT_BASE + path, { credentials: "same-origin", cache: "no-store", ...options, headers, signal: ctl.signal });
    const body = await res.json().catch(() => null);
    if (res.ok && body) return body;
    if (body?.error?.message) throw fail(body.error.message, body.error.state || "error", res.status);
    if (res.status === 404) throw fail("이 서버에는 아직 맞춤 마케팅이 연결되지 않았어요.", "off", 404);
    throw fail(res.ok ? "응답을 읽지 못했어요. 잠시 뒤 다시 해 주세요." : `맞춤 마케팅이 응답하지 않았어요 (${res.status}). 잠시 뒤 다시 해 주세요.`, "error", res.status);
  } catch (e) {
    if (e.name === "AbortError") throw fail("응답이 너무 늦어요. 잠시 뒤 다시 해 주세요.", "timeout", 0);
    if (e instanceof TypeError) throw fail("서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.", "down", 0);
    throw e;
  } finally { clearTimeout(timer); }
}

export const mktPost = (path, data) => mktApi(path, { method: "POST", body: JSON.stringify(data) });
