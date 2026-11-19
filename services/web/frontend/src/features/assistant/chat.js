// AI에게 묻기 서랍: 순수 계산과 서랍 전용 호출 (예전 app.js 2272~2348줄)
// 줄 종류·인용·주제 이름·값 모양은 상권 서비스 자체 채팅 화면(services/market-analysis/app/static/assistant/assistant.js)과 같다.
// 서버 글은 JSX 글자로만 넣는다 (innerHTML 금지).

export const CHAT_TOPICS = {
  conditions: "분석 조건", sales_total: "추정매출", sales_weekday: "요일별 매출", sales_time: "시간대별 매출",
  sales_age: "연령별 매출", stores_count: "점포 수", stores_open_close: "개업·폐업", population: "유동인구",
  change_qoq: "전분기 대비", change_yoy: "전년 동분기 대비", comparison: "상권 비교", ranking: "매출 상위 상권",
};
export const CHAT_STATUS = {
  available: "", no_data: "자료 없음", not_collected: "미수집", invalid: "형식 확인 필요", error: "불러오기 실패",
  partial: "일부만 확인", missing: "자료 없음", no_observation: "관측 없음",
};
// 상태 안내: [제목, 서버 문장(message)이 없을 때 쓰는 문장]. 제목은 서버 문장과 겹치지 않게 짧게
export const CHAT_STATES = {
  off: ["상권 비서를 쓸 수 없어요", "이 서버에서는 상권 비서를 켜 두지 않았어요."],
  down: ["지금은 연결할 수 없어요", "상권 서비스에 연결하지 못했어요. 잠시 뒤 다시 확인해 주세요."],
  disabled: ["상권 챗봇이 쉬고 있어요", "상권 서비스는 켜져 있지만 상권 비서(챗봇)가 꺼져 있어요."],
  no_data: ["상권 자료를 준비하고 있어요", "공식 상권 자료가 아직 준비되지 않았어요. 자료가 들어오면 바로 쓸 수 있어요."],
  error: ["상권 비서를 불러오지 못했어요", "상권 비서에 문제가 생겼어요. 잠시 뒤 다시 시도해 주세요."],
};
// 처음 추천 질문: 상권 질문(11/15 실제 상권 서버로 확인한 말투) + 전 파트 질문(5차 회의 11/18: 불만 리뷰·쿠폰 손익·남은 재료).
// 상권 질문은 다른 말투면 AI 계획기가 없는 기간을 지어내 '자료가 없어요'로 답하기도 해서 확인한 문장만 쓴다
export const CHAT_STARTERS = ["우리 가게 상권 매출은 어때?", "주변에 같은 업종 점포는 몇 개야?", "불만 리뷰 제일 많은 게 뭐야?",
  "쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?", "남은 재료 묶어서 팔고 싶어", "점심과 저녁 중 매출은 어디가 커?"];
export const CHAT_WAIT_MS = 90000;   // 실제 AI 호출이라 60~90초 걸릴 수 있다. 넘으면 끊고 입력을 풀어 준다
export const CHAT_SLOW = "답이 늦어지고 있어요. 잠시 뒤 다시 물어봐 주세요";

export const chatUrl = (v) => { try { const u = new URL(String(v)); return u.protocol === "https:" || u.protocol === "http:" ? u.href : null; } catch { return null; } };
export function chatValue(value, unit) {
  if (value === null || value === undefined) return "확인 불가";
  if (typeof value !== "number") return String(value);
  const text = Number.isInteger(value) && unit !== "%" ? value.toLocaleString("ko-KR")
    : value.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });   // 비율은 늘 소수 둘째 자리 (카드 문장과 같게)
  return unit ? text + unit : text;
}
// 분기 코드(20262 · 2026Q2)를 '2026년 2분기'로. 서버(assistant_proxy.py 의 QUARTER_IN_TEXT)와 같은 정규식이다.
// 서버가 먼저 바꿔 주지만, 서버가 놓친 글자도 날것으로 보이지 않게 화면에서 한 번 더 본다. 금액·개수(20262원, 20,262, 120262)는 그대로 둔다
export const CHAT_QUARTER = /(^|[^0-9A-Za-z_,.\-])(20[0-9]{2})(?:Q([1-4])(?![0-9A-Za-z])|([1-4])(?![0-9A-Za-z_\-]|[,.][0-9]|원|건|명|개|곳|호|번|위|배|회|세|살|대|가구|만|억|천|조|년|월|일|시|초|분(?!기)|평|점|%|퍼센트)(?: ?분기)?)/g;
export const chatQuarter = (t) => (typeof t === "string" ? t.replace(CHAT_QUARTER, (_, pre, y, q, n) => `${pre}${y}년 ${q || n}분기`) : t);
// 조건 줄의 분기: 이름이 코드 그대로(20262)이면 바꾸고, 이름이 없으면 코드(period)로 만든다
export const chatPeriod = (c) => { const p = String(c.period_label || c.period || ""); return /^[0-9]{4}[1-4]$/.test(p) ? `${p.slice(0, 4)}년 ${p[4]}분기` : chatQuarter(p); };
// 조건 칩: 상권 · 업종 · 분기 (비어 있는 것은 뺌)
export const chatCondParts = (c) => (c ? [c.area_name ? `${c.area_name} 상권` : null, c.industry_name, chatPeriod(c)].filter(Boolean) : []);
export const chatCondText = (c) => chatCondParts(c).join(" · ");
export const chatId = () => "web-" + (globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
export const chatSuggest = (reply) => (Array.isArray(reply?.suggestions) ? reply.suggestions : []).filter((s) => typeof s === "string" && s.trim()).map(chatQuarter).slice(0, 3);
export const chatSameKey = (a, b) => JSON.stringify(a || {}, Object.keys(a || {}).sort()) === JSON.stringify(b || {}, Object.keys(b || {}).sort());

// 답의 버튼 중 화면으로 가는 것(payload.type "navigate", 또는 고객응대·마케팅으로 넘기는 handoff)은 서버로 보내지 않고
// 그 화면으로 바로 간다 (docs/api/contract.md 1.15)
export function chatNavTarget(action) {
  const p = action && action.payload;
  if (!p || typeof p !== "object") return null;
  if (p.type === "navigate" && typeof p.route === "string") return { route: p.route, sub: typeof p.sub === "string" ? p.sub : null };
  if (p.type === "handoff") return p.domain === "marketing" ? { route: "marketing", sub: null } : p.domain === "customer" ? { route: "cards", sub: null } : null;
  return null;
}

// 답 글을 덩어리로: 빈 줄은 목록을 끊고, '- ' 줄은 목록, '참고:'·'해석:'·'다음으로 ' 줄은 특별 줄
export function chatBlocks(text) {
  const out = [];
  let list = null;
  for (const line of String(text || "").split("\n")) {
    if (!line.trim()) { list = null; continue; }
    if (line.startsWith("- ")) {
      if (!list) out.push((list = { type: "ul", items: [] }));
      list.items.push(line.slice(2));
      continue;
    }
    list = null;
    const kind = line.startsWith("참고:") ? "note" : line.startsWith("해석:") ? "insight" : line.startsWith("다음으로 ") ? "next" : "";
    if (kind === "note" || kind === "insight") out.push({ type: "p", kind, lead: line.slice(0, 3), line: line.slice(3) });
    else out.push({ type: "p", kind, lead: "", line });
  }
  return out;
}
// 한 줄을 글과 인용 [F1] 조각으로. 인용이 이 답에 없으면 화면이 글자 그대로(raw) 둔다
export function chatPieces(line) {
  const out = [];
  let last = 0;
  for (const m of String(line).matchAll(/\[(F\d+)\]/g)) {
    if (m.index > last) out.push({ text: chatQuarter(line.slice(last, m.index)) });
    out.push({ cite: m[1], raw: m[0] });
    last = m.index + m[0].length;
  }
  if (last < line.length) out.push({ text: chatQuarter(line.slice(last)) });
  return out;
}

// 서랍 전용 호출: 같은 출처 쿠키·JSON, 90초가 넘으면 끊는다. 실패하면 message·state 를 담은 Error (맨 위 띠에는 아무것도 띄우지 않음)
export async function drawerApi(path, options = {}, slow = "응답이 늦어지고 있어요. 잠시 뒤 다시 확인해 주세요.") {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), CHAT_WAIT_MS);
  const fail = (message, st) => Object.assign(new Error(message), { state: st });
  try {
    const res = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options, signal: ctl.signal,
      headers: { "Content-Type": "application/json", Accept: "application/json" } });
    const body = await res.json().catch(() => null);
    if (res.ok && body) return body;
    if (body?.error?.message) throw fail(body.error.message, body.error.state || "error");
    if (res.status === 404) throw fail("이 서버에는 아직 상권 비서가 연결되지 않았어요.", "off");
    if (res.status === 422) throw fail("질문을 다시 확인해 주세요. 1000자까지 쓸 수 있어요.", "invalid");
    throw fail(res.ok ? "응답을 읽지 못했어요. 잠시 뒤 다시 시도해 주세요." : `상권 비서가 응답하지 않았어요 (${res.status}). 잠시 뒤 다시 시도해 주세요.`, "error");
  } catch (e) {
    if (e.name === "AbortError") throw fail(slow, "timeout");
    if (e instanceof TypeError) throw fail("상권 비서에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.", "down");
    throw e;
  } finally { clearTimeout(timer); }
}
