// 서버 부르기. 화면과 API 는 같은 주소(origin)에서 받는 것이 전제다 (CORS 없음, 쿠키는 브라우저가 알아서 보냄).

// 비서 화면 서버의 /api/* (예전 app.js 의 api()와 같은 규칙).
// 오류 문장은 error.message → detail[0].msg → '요청 실패 (코드)' 순서로 고른다 (docs/api/contract.md 0.5).
export async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(body?.error?.message || body?.detail?.[0]?.msg || `요청 실패 (${res.status})`);
    err.status = res.status;
    err.state = body?.error?.state;
    err.body = body;
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
  const headers = options.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  try {
    const res = await fetch(path, { headers, signal: ctl.signal, ...options });
    const type = res.headers.get("content-type") || "";
    const body = type.includes("json") ? await res.json().catch(() => ({})) : {};
    if (!res.ok) {
      const err = new Error(body?.error?.message || (typeof body?.detail === "string" ? body.detail : "") || `요청 실패 (${res.status})`);
      err.status = res.status;
      err.state = body?.error?.state || (res.status === 504 ? "slow" : res.status >= 500 ? "down" : "invalid");
      err.body = body;
      throw err;
    }
    return body;
  } catch (e) {
    if (e.name === "AbortError") { const err = new Error("응답이 너무 오래 걸려요. 잠시 뒤 다시 해 주세요."); err.state = "slow"; throw err; }
    if (e instanceof TypeError) { const err = new Error("서버에 연결하지 못했어요. 잠시 뒤 다시 해 주세요."); err.state = "down"; throw err; }
    throw e;
  } finally { clearTimeout(timer); }
}
