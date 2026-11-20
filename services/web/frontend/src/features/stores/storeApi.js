// 새 가게 등록 화면(A4)의 서버 부르기와 순수 계산 (11/20, 6차 회의 ③).
// - 계정의 가게(등록·읽기·고치기)는 공통 api(): 로그인 표시 헤더와 401·409·403 단계 전환을 알아서 한다 (docs/api/contract.md 1.16).
// - 상권 서비스(업종·호선·역 목록, 주소 찾기, 위치 알리기, 상권 후보)는 serviceApi(): 제한 시간이 있고 같은 헤더·단계 전환을 하며,
//   오류는 이 화면 안에만 보인다 (1.14). 주소 찾기 결과(search_id·후보 id)는 상권 서비스 세션(/api/market 쿠키)에 남는다.
import { api, serviceApi } from "../../lib/api.js";

const enc = encodeURIComponent;
const post = (body) => ({ method: "POST", body: JSON.stringify(body) });

export const NAME_MAX = 30;
export const MENU_MAX = 30;
export const PRICE_MAX = 1000000;
export const QUERY_MIN = 2;
export const QUERY_MAX = 200;

// 입점한 배달 채널 (서버에는 code 를 보낸다)
export const CHANNELS = [
  { code: "baemin", name: "배달의민족" },
  { code: "coupangeats", name: "쿠팡이츠" },
  { code: "yogiyo", name: "요기요" },
  { code: "ddangyo", name: "땡겨요" },
];

// ── 상권 서비스 ──────────────────────────────────────────────────────────
// 업종·운영 상태·호선·역 목록 (응답 약 240KB, 바뀌지 않는 공식 목록이라 한 번 받은 것을 둔다. 실패하면 다음에 다시 받음)
let optionsPromise = null;
export function marketOptions() {
  if (!optionsPromise) {
    optionsPromise = serviceApi("/api/market/options", {}, 20000).then(pickOptions);
    optionsPromise.catch(() => { optionsPromise = null; });
  }
  return optionsPromise;
}

const list = (v) => (Array.isArray(v) ? v : []);
function pickOptions(o) {
  return {
    industries: list(o && o.industries).filter((x) => x && x.code && x.name),
    statuses: list(o && o.business_statuses).filter((x) => x && x.code && x.label),
    lines: list(o && o.station_lines).filter((x) => x && x.code && x.name),
    stations: list(o && o.stations).filter((x) => x && x.id && x.name),
  };
}

// 주소 찾기 → {status, message, search_id, candidates[{id, label, road_address, jibun_address, in_seoul, latitude, longitude}]}
export const searchAddress = (query) => serviceApi("/api/market/locations/search", post({ query }), 20000);

// 위치·업종을 상권 서비스에 알리고(POST profile) 그 위치의 상권 후보를 받는다(GET analysis-options).
// - 상권 서비스는 같은 세션에 저장한 적이 있으면 expected_revision 이 지금 값과 같아야 받는다 (없이 보내면 409).
//   그래서 먼저 GET profile 로 revision 을 읽고, 그사이 바뀌어 409 가 오면 한 번만 다시 한다.
// - 세션의 조건은 하나라서 두 요청이 겹치면 후보가 섞인다. 차례대로 하나씩 하고, 차례가 왔을 때 이미 지난 요청(isCurrent false)은 건너뛴다.
let chain = Promise.resolve();
export function resolveAreas(req, isCurrent = () => true) {
  const run = chain.then(() => {
    if (!isCurrent()) throw Object.assign(new Error("지난 요청"), { stale: true });
    return resolveNow(req);
  });
  chain = run.catch(() => {});
  return run;
}

async function resolveNow({ location, industry_code, business_status }) {
  const send = async () => {
    const cur = await serviceApi("/api/market/profile", {}, 15000);
    const revision = Number.isInteger(cur && cur.revision) && cur.revision >= 0 ? cur.revision : 0;
    return serviceApi("/api/market/profile", post({ location, industry_code, business_status, expected_revision: revision }), 20000);
  };
  let saved;
  try { saved = await send(); }
  catch (e) { if (e.status !== 409) throw e; saved = await send(); }
  const opts = await serviceApi("/api/market/analysis-options", {}, 30000);
  const profile = (opts && opts.profile) || (saved && saved.profile) || {};
  return {
    location: profile.location || null,
    candidates: list(opts && opts.candidates),
    notice: (opts && opts.scope && opts.scope.boundary_notice) || "",
    message: (opts && opts.message) || "",
  };
}

// ── 계정의 가게 ──────────────────────────────────────────────────────────
export const createStore = (body) => api("/api/account/stores", post(body));
export const getStore = (id) => api(`/api/account/stores/${enc(id)}`);
export const patchStore = (id, body) => api(`/api/account/stores/${enc(id)}`, { method: "PATCH", body: JSON.stringify(body) });

// ── 순수 계산 ───────────────────────────────────────────────────────────
const PERIOD = /^[0-9]{4}[1-4]$/;
export const periodLabel = (code) => (PERIOD.test(String(code || "")) ? `${String(code).slice(0, 4)}년 ${String(code)[4]}분기` : "");

// 상권 후보에서 업종 자료가 있는 가장 최근 분기 {code, label} (없으면 null)
export function latestIndustryPeriod(c) {
  const ps = list(c && c.availability && c.availability.periods)
    .filter((p) => p && p.available && p.industry_data_available && PERIOD.test(String(p.code)));
  ps.sort((a, b) => String(b.code).localeCompare(String(a.code)));
  return ps[0] ? { code: String(ps[0].code), label: ps[0].label || periodLabel(ps[0].code) } : null;
}

export const NO_INDUSTRY_DATA = "이 업종의 상권 자료가 없어 고를 수 없어요.";

// 상권 후보 → 라디오 한 줄 {code, name, type, relation, distance, period, blocked, geometry}. blocked 가 있으면 고를 수 없음 (그 이유)
export function areaRows(candidates) {
  return list(candidates).filter((c) => c && /^[0-9]{7}$/.test(String(c.area_code))).map((c) => {
    const period = latestIndustryPeriod(c);
    const blocked = c.selection_blocked_reason ? String(c.selection_blocked_reason) : !period ? NO_INDUSTRY_DATA : "";
    return { code: String(c.area_code), name: c.name || String(c.area_code), type: c.type || "", relation: c.relation || "",
      distance: Number.isFinite(c.distance_m) ? c.distance_m : null, period, blocked, geometry: c.geometry || null };
  });
}

// 라디오 아래 줄: '종류 · 공식 상권 코드 · 위치 관계 · 최신 분기 자료 있음'
export function relationText(r) {
  if (r.relation === "inside") return "가게 위치가 안에 있어요";
  if (r.relation === "boundary") return "가게 위치가 경계에 있어요";
  if (r.relation === "neighborhood") return "같은 동네";
  return Number.isFinite(r.distance) ? `${r.distance.toLocaleString("ko-KR")}m 거리` : "";
}
export function areaSub(r) {
  return [r.type, `공식 상권 코드 ${r.code}`, relationText(r), r.blocked ? "" : r.period ? `${r.period.label} 자료 있음` : ""].filter(Boolean).join(" · ");
}

// 기본 선택: 예전 선택을 새 후보에서도 고를 수 있으면 그대로, 아니면 위치가 들어 있는 상권(inside 먼저, 다음 boundary) 중 고를 수 있는 첫 번째.
// 그런 상권이 없으면 비운다 (사장님이 고름)
export function defaultArea(rows, prev) {
  const ok = list(rows).filter((r) => !r.blocked);
  if (prev && ok.some((r) => r.code === prev)) return prev;
  const pick = ok.find((r) => r.relation === "inside") || ok.find((r) => r.relation === "boundary");
  return pick ? pick.code : "";
}

// 호선 코드 → 그 호선의 역 (이름 순). 역의 lines 는 호선 '이름'이고 공식 이름이 달라('서울 도시철도 9호선') 코드(selectable_line_codes)로 고른다
export function stationsOf(stations, lineCode, lines) {
  if (!lineCode) return [];
  const lineName = (list(lines).find((l) => l.code === lineCode) || {}).name;
  return list(stations)
    .filter((s) => (Array.isArray(s.selectable_line_codes) ? s.selectable_line_codes.includes(lineCode) : list(s.lines).includes(lineName)))
    .sort((a, b) => String(a.name).localeCompare(String(b.name), "ko"));
}

// 역의 첫 호선 코드 (고치기 화면에서 저장한 역을 셀렉트에 다시 채울 때)
export function lineOf(station, lines) {
  if (!station) return "";
  const codes = list(station.selectable_line_codes);
  if (codes.length) return codes[0];
  const hit = list(lines).find((l) => list(station.lines).includes(l.name));
  return hit ? hit.code : "";
}

// 서버 오류 문장 끝의 'Value error, ' 같은 검사기 머리말을 뗀다 (주소 칸 검사 오류가 그대로 넘어옴)
export const plainMessage = (m) => String(m || "").replace(/^Value error,\s*/i, "");

// 가격 글자 → 정수 (쉼표·띄어쓰기·'원'은 무시). 비었으면 null, 숫자가 아니면 NaN
export function parsePrice(text) {
  const t = String(text ?? "").replace(/[,\s원]/g, "");
  if (!t) return null;
  return /^[0-9]+$/.test(t) ? Number(t) : NaN;
}

// 메뉴 줄 검사: 빈 줄은 빼고 {menus: [{name, price}], errors: {줄 key: {name?, price?}}}
export function checkMenus(rows) {
  const menus = [], errors = {};
  for (const row of list(rows)) {
    const name = String(row.name || "").trim();
    const price = parsePrice(row.price);
    if (!name && price === null) continue;
    const e = {};
    if (!name) e.name = "메뉴 이름을 적어 주세요.";
    else if (name.length > NAME_MAX) e.name = `메뉴 이름은 ${NAME_MAX}자까지 적을 수 있어요.`;
    if (price === null) e.price = "가격을 적어 주세요.";
    else if (!Number.isInteger(price) || price > PRICE_MAX) e.price = `가격은 0~${PRICE_MAX.toLocaleString("ko-KR")}원 사이의 숫자로 적어 주세요.`;
    if (e.name || e.price) errors[row.key] = e;
    else menus.push({ name, price });
  }
  return { menus, errors };
}

const cut = (v, n) => {
  const s = typeof v === "string" ? v.trim() : "";
  return s ? s.slice(0, n) : null;
};
const coord = (v, lim) => (typeof v === "number" && Number.isFinite(v) && Math.abs(v) <= lim ? v : null);

// 상권 서비스가 돌려준 위치(profile.location) → 등록 본문의 location (1.16 '가게 칸'). fallback: 고른 후보·역에서 아는 값
export function locationBody(loc, fallback = {}) {
  const l = loc && typeof loc === "object" ? loc : {};
  const kind = l.kind === "station" || l.kind === "address" ? l.kind : fallback.kind;
  const station = kind === "station";
  return {
    kind,
    label: cut(l.label || l.name || fallback.label, 120) || "",
    road_address: cut(l.road_address || fallback.road_address, 200),
    latitude: coord(l.latitude ?? fallback.latitude, 90),
    longitude: coord(l.longitude ?? fallback.longitude, 180),
    station_id: station ? cut(l.station_id || fallback.station_id, 80) : null,
    station_name: station ? cut(l.name || l.label || fallback.label, 40) : null,
    district_name: cut(l.district_name || fallback.district_name, 20),
  };
}

// 서버 오류 문장 → 그 문장을 보일 칸 (account_api.py 의 문장에 칸 이름이 들어 있음). 모르면 폼 아래
export function errorField(message) {
  const m = String(message || "");
  if (/가게 이름/.test(m)) return "name";
  if (/업종/.test(m)) return "industry";
  if (/영업 상태|운영 상태/.test(m)) return "status";
  if (/배달 채널/.test(m)) return "channels";
  if (/메뉴/.test(m)) return "menus";
  if (/상권|분기/.test(m)) return "area";
  if (/위치|역 id|역 이름|도로명|위도|경도|자치구/.test(m)) return "location";
  return "form";
}

const sameList = (a, b) => JSON.stringify(list(a)) === JSON.stringify(list(b));
// 고치기: 바뀐 칸만 (location·area 는 위치를 다시 고른 때만 → 상권 서비스에 다시 묻지 않은 저장은 그대로 둔다)
export function storePatch(saved, next) {
  const out = {};
  if (next.name !== saved.name) out.name = next.name;
  if (next.industry_code !== saved.industry_code) { out.industry_code = next.industry_code; out.business_type_name = next.business_type_name; }
  if (next.business_status !== saved.business_status) out.business_status = next.business_status;
  if (!sameList([...next.channels].sort(), [...list(saved.channels)].sort())) out.channels = next.channels;
  if (!sameList(next.menus, list(saved.menus).map((m) => ({ name: m.name, price: m.price })))) out.menus = next.menus;
  if (next.location) out.location = next.location;
  if (next.area) out.area = next.area;
  return out;
}

// 시험에서만 쓴다
export function resetStoreApiForTest() { optionsPromise = null; chain = Promise.resolve(); }
