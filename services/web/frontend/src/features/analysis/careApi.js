// 고객응대 호출 (예전 app.js careApi 그대로). 캡처 읽기와 캡처 후보 저장(/api/reviews)이 쓴다.
// 공통 api()·setAlert 를 쓰지 않아서 오류는 캡처 칸 안에만 보이고 화면의 다른 곳은 그대로 (docs/api/contract.md 1.11).
export const CARE_WAIT_MS = 20000;
export const CAP_WAIT_MS = 110000;   // 캡처: 긴 캡처는 최대 5조각으로 나눠 조각마다 HCX 를 부른다 (보통 5~20초). 서버는 100초까지 기다림

export async function careApi(path, options = {}, waitMs = CARE_WAIT_MS) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), waitMs);
  const fail = (message, st, status) => Object.assign(new Error(message), { state: st, status });
  const headers = { Accept: "application/json" };
  if (typeof options.body === "string") headers["Content-Type"] = "application/json";   // FormData(캡처)는 브라우저가 경계값을 붙인다
  try {
    const res = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options, headers, signal: ctl.signal });
    const body = await res.json().catch(() => null);
    if (res.ok && body) return body;
    if (body?.error?.message) throw fail(body.error.message, body.error.state || "error", res.status);
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
