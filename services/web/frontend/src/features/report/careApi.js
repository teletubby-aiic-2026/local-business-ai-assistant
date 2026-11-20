// 고객응대 호출 (예전 app.js careApi). 이 서버의 /api/care/*·/api/approvals 만 부른다.
// 공통 api()·맨 위 띠(setAlert)를 쓰지 않아서 오류는 그 칸 안에만 보이고 화면의 다른 곳은 그대로.
// 로그인한 사장님의 요청에는 로그인 표시 헤더를 붙이고, 세션 끝남(401)·가게 없음(409)·권한 없음(403)은 단계 전환으로 넘긴다 (lib/api.js, 11/20).
import { authHeaders, handleAuthError } from "../../lib/api.js";

export const CARE_WAIT_MS = 20000;

export async function careApi(path, options = {}, waitMs = CARE_WAIT_MS) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), waitMs);
  const fail = (message, st, status) => Object.assign(new Error(message), { state: st, status });
  const headers = { Accept: "application/json", ...authHeaders() };
  if (typeof options.body === "string") headers["Content-Type"] = "application/json";   // FormData(캡처)는 브라우저가 경계값을 붙인다
  try {
    const res = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options, headers, signal: ctl.signal });
    const body = await res.json().catch(() => null);
    if (res.ok && body) return body;
    if (body?.error?.message) {
      const err = fail(body.error.message, body.error.state || "error", res.status);
      handleAuthError(err);
      throw err;
    }
    if (res.status === 413) throw fail("파일이 너무 커요. 10MB 이하 이미지를 올려 주세요.", "too_big", 413);   // Nginx 가 막으면 HTML 로 옴
    if (res.status === 422) throw fail("보내는 내용을 다시 확인해 주세요.", "invalid", 422);
    if (res.status === 404) throw fail("이 서버에는 아직 고객응대 기능이 연결되지 않았어요.", "off", 404);
    throw fail(res.ok ? "응답을 읽지 못했어요. 잠시 뒤 다시 해 주세요." : `고객응대 기능이 응답하지 않았어요 (${res.status}). 잠시 뒤 다시 해 주세요.`, "error", res.status);
  } catch (e) {
    if (e.name === "AbortError") throw fail("응답이 너무 늦어요. 잠시 뒤 다시 해 주세요.", "timeout", 0);
    if (e instanceof TypeError) throw fail("서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.", "down", 0);
    throw e;
  } finally { clearTimeout(timer); }
}
