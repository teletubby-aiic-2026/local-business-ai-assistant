// A4 새 가게 등록 (features/stores/StoreNew.jsx · storeApi.js): 업종 → 역 → 상권 후보 → 고르기 → 메뉴 → 저장 본문 → 가게 열기 → 메인 화면 홈,
// 주소 찾기(후보 고르기 · 후보 없음 · 서울 밖 · 조회 불가), 지도가 안 떠도 라디오로 고르기, 업종·위치를 바꾸면 후보 다시 받기,
// 고치기(채우기 · 바뀐 칸만 PATCH · 위치를 안 바꾸면 상권 서비스에 다시 묻지 않음), 오류 표시(store_limit 포함), 중복 누름, 취소.
// 메인 화면의 화면 8개와 서랍은 가짜로 바꿔 틀만 본다 (stages.test.jsx 와 같은 방식). 지도는 키가 없는 상태(지금은 지도를 볼 수 없어요)
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, act, waitFor } from "@testing-library/react";
import { resetStore, setState, getState } from "../../state/store.js";
import { resetNaverMapsForTest } from "../../components/NaverMap.jsx";
import { resetStoreApiForTest, areaRows, defaultArea, checkMenus, locationBody, errorField, foodIndustries, stationsOf, storePatch, latestIndustryPeriod } from "./storeApi.js";
import App from "../../App.jsx";

vi.mock("../flow/Home.jsx", async () => { const { PageHead } = await import("../../components/ui.jsx"); return { default: () => <PageHead title="홈 화면" /> }; });
vi.mock("../flow/Cards.jsx", () => ({ default: () => <p>추천 카드 화면</p> }));
vi.mock("../flow/Draft.jsx", () => ({ default: () => <p>승인할 글 화면</p> }));
vi.mock("../flow/Done.jsx", () => ({ default: () => <p>처리 완료 화면</p> }));
vi.mock("../analysis/Analysis.jsx", () => ({ default: () => <p>리뷰 분석 화면</p> }));
vi.mock("../marketing/Marketing.jsx", () => ({ default: () => <p>맞춤 마케팅 화면</p> }));
vi.mock("../report/Report.jsx", () => ({ default: () => <p>종합 리포트 화면</p> }));
vi.mock("../market/Market.jsx", () => ({ default: () => <p>상권 분석 화면</p> }));
vi.mock("../assistant/Drawer.jsx", () => ({ default: () => <aside id="assistant" className="drawer" hidden /> }));

const OPTIONS = {
  districts: [{ code: "11590", name: "동작구" }],
  industries: [{ code: "CS100001", name: "한식음식점" }, { code: "CS100010", name: "커피-음료" }],
  business_statuses: [{ code: "operating", label: "운영 중" }, { code: "planning", label: "창업 준비 중" }, { code: "exploring", label: "창업 검토 중" }],
  station_lines: [{ code: "line-7", name: "7호선" }, { code: "line-9", name: "9호선" }],
  stations: [
    { id: "kric-jsb", name: "장승배기역", lines: ["7호선"], district_name: "동작구", road_address: "서울특별시 동작구 상도로 지하188", latitude: 37.504845, longitude: 126.939025, selectable_line_codes: ["line-7"] },
    { id: "kric-sd", name: "상도역", lines: ["7호선"], district_name: "동작구", road_address: "서울특별시 동작구 상도로 지하272", latitude: 37.50275, longitude: 126.94796, selectable_line_codes: ["line-7"] },
    { id: "kric-nr", name: "노량진역", lines: ["서울 도시철도 9호선"], district_name: "동작구", road_address: "서울특별시 동작구 노량진로 지하151", latitude: 37.5133, longitude: 126.9411, selectable_line_codes: ["line-9"] },
  ],
};
const POLY = { type: "Polygon", coordinates: [[[126.93, 37.50], [126.94, 37.50], [126.94, 37.51], [126.93, 37.50]]] };
const per = (codes, industry = true) => codes.map((c) => ({ code: c, label: `${c.slice(0, 4)}년 ${c[4]}분기`, available: true, industry_data_available: industry }));
const cand = (code, name, extra = {}) => ({ area_code: code, name, type: "골목상권", relation: "nearby", distance_m: 140, district_name: "동작구", geometry: POLY,
  availability: { periods: per(["20261", "20262"]) }, selection_blocked_reason: null, ...extra });
const JSB = [
  cand("3120154", "장승배기역", { type: "발달상권", relation: "inside", distance_m: 0 }),
  cand("3110826", "장승배기역 4번", { availability: { periods: [{ code: "20262", label: "2026년 2분기", available: true, industry_data_available: false }, ...per(["20261"])] } }),
  cand("3110999", "이름이 다른 상권", { distance_m: 300, selection_blocked_reason: "경계와 상권 명칭의 연결 확인이 필요합니다." }),
  cand("3110998", "업종 자료 없는 상권", { distance_m: 420, availability: { periods: per(["20262"], false) } }),
];
const SD = [cand("3110836", "상도역 5번", { relation: "inside", distance_m: 0 }), cand("3110826", "장승배기역 4번", { distance_m: 500 })];
const NOTICE = "2023년 공개 경계이며 현재 분기 경계와의 동일성은 확인되지 않았습니다.";
const ADDR = [
  { id: "c1", label: "서울특별시 동작구 장승배기로 10", road_address: "서울특별시 동작구 장승배기로 10", jibun_address: "서울특별시 동작구 상도동 1", in_seoul: true, latitude: 37.505, longitude: 126.94 },
  { id: "c2", label: "서울특별시 동작구 장승배기로 100", road_address: "서울특별시 동작구 장승배기로 100", jibun_address: "서울특별시 동작구 노량진동 2", in_seoul: true, latitude: 37.507, longitude: 126.938 },
];
const NEW_ID = "store_abc123def456";
const ME0 = { authenticated: true, store_id: null, stores: [], demo_login: false,
  user: { user_id: "u1", login_id: "owner_test", display_name: "김시험", demo: false, created_at: "2026-11-20" } };
const meWith = (stores, storeId) => ({ ...ME0, stores, store_id: storeId });
const NEW_ROW = { store_id: NEW_ID, name: "우리분식", business_type_name: "한식음식점", area_name: "장승배기역 4번", station_name: "장승배기역", sample: false };
const SAVED = { ...NEW_ROW, store_id: "store_mine00000001", area_name: "장승배기역", menu_count: 2, last_opened: false,
  industry_code: "CS100001", business_status: "operating", channels: ["baemin"],
  location: { kind: "station", label: "장승배기역", road_address: "서울특별시 동작구 상도로 지하188", latitude: 37.504845, longitude: 126.939025,
    station_id: "kric-jsb", station_name: "장승배기역", district_name: "동작구" },
  area: { area_code: "3120154", name: "장승배기역", period: "20262" },
  menus: [{ name: "떡볶이", price: 4500 }, { name: "순대", price: 5000 }] };
const SAVED_ADDR = { ...SAVED, store_id: "store_mine00000002",
  location: { kind: "address", label: "서울특별시 동작구 장승배기로 10", road_address: "서울특별시 동작구 장승배기로 10", latitude: 37.505, longitude: 126.94,
    station_id: null, station_name: null, district_name: "동작구" } };

let calls, routes, market;
// "METHOD /path" 또는 "/path" → 값 | [상태, 값] | (body) => … (Promise 도 됨). 상권 서비스의 세션(revision·조건)은 market 에
function server(extra = {}) {
  calls = [];
  market = { rev: 0, prof: null, lastSearch: [], cands: (p) => (p.location.station_id === "kric-sd" ? SD : JSB) };
  const locOf = (l) => {
    if (l.kind === "station") {
      const s = OPTIONS.stations.find((x) => x.id === l.station_id);
      return { kind: "station", station_id: s.id, name: s.name, label: s.name, lines: s.lines, district_name: s.district_name, road_address: s.road_address, latitude: s.latitude, longitude: s.longitude };
    }
    const c = market.lastSearch.find((x) => x.id === l.candidate_id);
    return { kind: "address", label: c.label, road_address: c.road_address, jibun_address: c.jibun_address, latitude: c.latitude, longitude: c.longitude, district_code: "11590", district_name: "동작구" };
  };
  routes = {
    "/api/health": { mode: "mock" }, "/api/briefing": { store: { name: "우리분식" }, groups: [], counts: { review_count: 0 }, snapshots: [] },
    "/api/cards": { cards: [] }, "/api/insight": {}, "/api/approvals": { items: [] }, "/api/market/status": { state: "ready" },
    "/api/market/options": OPTIONS,
    "/api/market/map-config": { client_id: "", configured: false },
    "GET /api/market/profile": () => ({ revision: market.rev, profile: market.prof }),
    "POST /api/market/profile": (b) => {
      if (b.expected_revision !== market.rev) return [409, { error: { message: "다른 화면에서 정보가 변경됐습니다.", state: "conflict" } }];
      market.rev += 1;
      market.prof = { revision: market.rev, location: locOf(b.location), industry: { code: b.industry_code }, business_status: b.business_status };
      return { revision: market.rev, profile: market.prof, message: "기본 정보를 저장했습니다." };
    },
    "/api/market/analysis-options": () => ({ status: "ready", candidates: market.cands(market.prof), scope: { boundary_notice: NOTICE },
      message: "공개 상권 경계를 확인하고 분석할 상권을 선택해 주세요.", revision: market.rev, profile: market.prof }),
    "POST /api/market/locations/search": () => {
      market.lastSearch = ADDR;
      return { status: "choose_candidate", message: "주소 후보가 여러 곳입니다. 의도한 주소를 선택하거나 구·동을 더 알려 주세요.", search_id: "s-1", candidates: ADDR };
    },
    "POST /api/account/stores": (b) => [201, { store: { ...NEW_ROW, ...b, store_id: NEW_ID } }],
    "POST /api/auth/store": (b) => meWith([NEW_ROW], b.store_id),
    "/api/auth/me": meWith([SAVED], null),
    "/api/account/stores": { stores: [SAVED] },
    [`/api/account/stores/${SAVED.store_id}`]: { store: SAVED },
    [`PATCH /api/account/stores/${SAVED.store_id}`]: (b) => ({ store: { ...SAVED, ...b } }),
    [`/api/account/stores/${SAVED_ADDR.store_id}`]: { store: SAVED_ADDR },
    ...extra,
  };
  globalThis.fetch = vi.fn(async (path, opt = {}) => {
    const method = (opt.method || "GET").toUpperCase();
    const body = opt.body ? JSON.parse(opt.body) : undefined;
    calls.push({ path, method, body, headers: opt.headers || {} });
    const h = routes[`${method} ${path}`] ?? routes[path];
    const out = typeof h === "function" ? await h(body) : h;
    const [status, data] = Array.isArray(out) ? out : [200, out ?? {}];
    return { ok: status < 400, status, json: async () => data, headers: { get: () => "application/json" } };
  });
}
const paths = () => calls.map((c) => c.path);
const sent = (method, path) => calls.filter((c) => c.method === method && c.path === path);
const $ = (id) => document.getElementById(id);
const change = (el, value) => fireEvent.change(el, { target: { value } });
const h1 = () => document.querySelector("h1")?.textContent;
const MARKET_ASK = ["/api/market/profile", "/api/market/analysis-options"];

function show(mode = "signup", extra = {}) {
  setState({ stage: "store-new", storeNew: { mode, ...(extra.storeId ? { storeId: extra.storeId } : {}) }, storeNewFrom: extra.from || "pick", me: extra.me || ME0, health: { mode: "mock" } });
  return render(<App />);
}
async function ready() { await waitFor(() => expect($("sn-name")).toBeTruthy()); }
async function pickStation(line = "line-7", id = "kric-jsb") {
  fireEvent.click(screen.getByRole("radio", { name: "가까운 역으로" }));
  change($("sn-line"), line);
  change($("sn-station"), id);
}
const checked = () => [...document.querySelectorAll('input[name="area_code"]')].filter((x) => x.checked).map((x) => x.value);

beforeEach(() => {
  resetStore();
  resetStoreApiForTest();
  resetNaverMapsForTest();
  sessionStorage.clear();
  window.location.hash = "#/report";
  window.scrollTo = () => {};
  server();
});
afterEach(() => cleanup());

describe("새 가게 등록: 역으로 고르는 흐름", () => {
  it("업종 → 역 → 상권 후보(기본은 위치가 들어 있는 상권) → 다른 상권 고르기 → 메뉴 → 저장 본문 → 가게 열기 → 메인 화면 홈", async () => {
    show("signup");
    await ready();
    expect(h1()).toBe("새 가게 등록");
    expect(document.activeElement).toBe(document.querySelector("h1"));
    expect(screen.getByText("가게 등록 2 / 3")).toBeTruthy();   // 가입 화면의 세 단계 가운데 둘째 (11/21)
    expect(screen.getByRole("button", { name: "가게 선택으로" })).toBeTruthy();
    expect(screen.getByText("등록하면 이렇게 시작해요")).toBeTruthy();
    expect(screen.getByText(/새 가게에는 아직 리뷰가 없어요\. 등록을 마치면 리뷰 넣기\(붙여넣기·캡처\)부터 안내하고, 상권 분석은 바로 볼 수 있어요\./)).toBeTruthy();
    // 업종 셀렉트는 상권 서비스의 업종 목록, 운영 상태는 기본 '운영 중'
    expect([...$("sn-industry").options].map((o) => o.textContent)).toEqual(["업종을 골라 주세요", "한식음식점", "커피-음료"]);
    expect($("sn-status").value).toBe("operating");
    expect([...$("sn-status").options].map((o) => o.textContent)).toEqual(["운영 중", "창업 준비 중", "창업 검토 중"]);

    change($("sn-name"), "  우리분식 ");
    change($("sn-industry"), "CS100001");
    fireEvent.click($("sn-ch-baemin"));
    fireEvent.click($("sn-ch-yogiyo"));
    await pickStation();
    // 호선을 고르면 그 호선의 역만 (9호선 역은 공식 이름이 달라도 코드로 고름)
    expect([...$("sn-station").options].map((o) => o.textContent)).toEqual(["역을 골라 주세요", "상도역 (동작구)", "장승배기역 (동작구)"]);
    await waitFor(() => expect($("sn-area-3120154")).toBeTruthy());
    // 상권 서비스: revision 을 읽고 → 위치·업종 알리기 → 상권 후보
    expect(sent("POST", "/api/market/profile")[0].body).toEqual({ location: { kind: "station", station_id: "kric-jsb" }, industry_code: "CS100001",
      business_status: "operating", expected_revision: 0 });
    expect(paths().indexOf("/api/market/analysis-options")).toBeGreaterThan(paths().lastIndexOf("/api/market/profile"));
    expect(sent("GET", "/api/market/analysis-options")[0].headers["X-IC26-Signed-In"]).toBe("1");
    expect(screen.getByText("장승배기역", { selector: ".sn-place b" })).toBeTruthy();   // 고른 위치
    // 라디오: 이름 + '종류 · 공식 상권 코드 · 위치 관계 · 최신 분기 자료 있음', 기본은 위치가 들어 있는 상권
    expect(checked()).toEqual(["3120154"]);
    expect($("sn-area-sub-3120154").textContent).toBe("발달상권 · 공식 상권 코드 3120154 · 가게 위치가 안에 있어요 · 2026년 2분기 자료 있음");
    expect($("sn-area-sub-3110826").textContent).toBe("골목상권 · 공식 상권 코드 3110826 · 140m 거리 · 2026년 1분기 자료 있음");
    // 고를 수 없는 상권: 이유를 보이고 잠금
    expect($("sn-area-3110999").disabled).toBe(true);
    expect($("sn-area-sub-3110999").textContent).toContain("경계와 상권 명칭의 연결 확인이 필요합니다.");
    expect($("sn-area-3110998").disabled).toBe(true);
    expect($("sn-area-sub-3110998").textContent).toContain("이 업종의 상권 자료가 없어 고를 수 없어요.");
    // 정직 고지 + 경계 안내
    expect(screen.getByText(/상권 자료는 우리 가게 매출이 아니라 상권·업종 전체의 추정치예요\./)).toBeTruthy();
    // 지도는 키가 없어 한 줄 안내만, 라디오로 그대로 고른다
    await waitFor(() => expect(screen.getByText("지금은 지도를 볼 수 없어요.")).toBeTruthy());
    fireEvent.click($("sn-area-3110826"));
    expect(checked()).toEqual(["3110826"]);

    // 메뉴: 빈 줄은 보내지 않고, 가격의 쉼표·'원'은 숫자로
    const names = document.querySelectorAll('input[name="menu_name"]');
    const prices = document.querySelectorAll('input[name="menu_price"]');
    expect(names).toHaveLength(3);
    expect(names[0].placeholder).toBe("예: 제육볶음 정식");
    change(names[0], "떡볶이"); change(prices[0], "4,500");
    change(names[2], "순대"); change(prices[2], "5000원");
    fireEvent.click(screen.getByRole("button", { name: "+ 메뉴 더하기" }));
    await waitFor(() => expect(document.querySelectorAll('input[name="menu_name"]')).toHaveLength(4));
    const last = document.querySelectorAll('input[name="menu_name"]')[3];
    await waitFor(() => expect(document.activeElement).toBe(last));
    change(last, "김밥"); change(document.querySelectorAll('input[name="menu_price"]')[3], "0");

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "가게 등록하고 시작" })); });
    await waitFor(() => expect(getState().stage).toBe("app"));
    expect(sent("POST", "/api/account/stores")).toHaveLength(1);
    expect(sent("POST", "/api/account/stores")[0].body).toEqual({
      name: "우리분식", industry_code: "CS100001", business_type_name: "한식음식점", business_status: "operating", channels: ["baemin", "yogiyo"],
      menus: [{ name: "떡볶이", price: 4500 }, { name: "순대", price: 5000 }, { name: "김밥", price: 0 }],
      location: { kind: "station", label: "장승배기역", road_address: "서울특별시 동작구 상도로 지하188", latitude: 37.504845, longitude: 126.939025,
        station_id: "kric-jsb", station_name: "장승배기역", district_name: "동작구" },
      area: { area_code: "3110826", name: "장승배기역 4번", period: "20261" },
    });
    expect(sent("POST", "/api/account/stores")[0].headers["X-IC26-Signed-In"]).toBe("1");
    // 가게 선택의 [이 가게 열기]와 같은 길: 지금 가게를 바꾸고 → 그 가게 자료 → 홈
    expect(sent("POST", "/api/auth/store")[0].body).toEqual({ store_id: NEW_ID });
    expect(sessionStorage.getItem("ic26.entered")).toBe(NEW_ID);
    expect(window.location.hash).toBe("#/today");
    await waitFor(() => expect(paths()).toContain("/api/briefing"));
    expect(h1()).toBe("홈 화면");
    // 상단 바 가게 칩은 신원의 가게 목록 값 (브리핑에 업종·상권이 없어도)
    expect($("store-name").textContent).toBe("우리분식");
    expect(document.querySelector(".store-pick .sp-sub").textContent).toBe("한식음식점 · 장승배기역 4번 상권");
  });

  it("업종을 고르기 전에 역을 고르면 상권 서비스를 부르지 않고 업종부터 안내, 업종을 고르면 그때 후보를 받는다", async () => {
    show("add");
    await ready();
    expect(screen.queryByText("가게 등록 2 / 3")).toBeNull();
    await pickStation();
    expect(screen.getByText("업종을 먼저 골라 주세요. 업종마다 상권 자료가 달라요.")).toBeTruthy();
    MARKET_ASK.forEach((p) => expect(paths()).not.toContain(p));
    change($("sn-industry"), "CS100001");
    await waitFor(() => expect(checked()).toEqual(["3120154"]));
  });

  it("업종·위치를 바꾸면 후보를 다시 받고, 예전 선택이 새 후보에 있으면 그대로 · 없으면 비운다", async () => {
    show("add");
    await ready();
    change($("sn-industry"), "CS100001");
    await pickStation();
    await waitFor(() => expect(checked()).toEqual(["3120154"]));
    fireEvent.click($("sn-area-3110826"));
    // 업종을 바꿈: 같은 위치로 다시 알리고(revision 1) 후보를 다시. 고른 상권이 새 후보에도 있으면 그대로
    change($("sn-industry"), "CS100010");
    await waitFor(() => expect(sent("POST", "/api/market/profile")).toHaveLength(2));
    expect(sent("POST", "/api/market/profile")[1].body).toMatchObject({ industry_code: "CS100010", expected_revision: 1, location: { kind: "station", station_id: "kric-jsb" } });
    await waitFor(() => expect(sent("GET", "/api/market/analysis-options")).toHaveLength(2));
    await waitFor(() => expect(checked()).toEqual(["3110826"]));
    // 위치를 바꿈: 상도역 후보에 예전 선택(장승배기역 4번)이 있지만 고를 수 없게 바꿔 두면 → 비우고 위치가 들어 있는 상권으로
    market.cands = (p) => (p.location.station_id === "kric-sd" ? [SD[0], { ...SD[1], selection_blocked_reason: "경계와 상권 명칭의 연결 확인이 필요합니다." }] : JSB);
    change($("sn-station"), "kric-sd");
    await waitFor(() => expect($("sn-area-3110836")).toBeTruthy());
    expect(checked()).toEqual(["3110836"]);
    // 위치가 들어 있는 상권도 고를 수 없으면 아무것도 고르지 않은 채로
    market.cands = () => [cand("3110700", "먼 상권", { distance_m: 800 })];
    change($("sn-station"), "kric-jsb");
    await waitFor(() => expect($("sn-area-3110700")).toBeTruthy());
    expect(checked()).toEqual([]);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "가게 등록하고 시작" })); });
    expect($("sn-err-area").textContent).toBe("상권을 하나 골라 주세요.");
  });

  it("상권 서비스가 다른 곳에서 바뀌어 409 면 revision 을 다시 읽어 한 번 더 보낸다", async () => {
    market.rev = 3;   // 이 브라우저의 상권 세션에 이미 다른 조건이 있음
    show("add");
    await ready();
    change($("sn-industry"), "CS100001");
    const post = routes["POST /api/market/profile"];
    let first = true;
    routes["POST /api/market/profile"] = (b) => { if (first) { first = false; market.rev += 1; } return post(b); };   // 그사이 다른 화면이 저장
    await pickStation();
    await waitFor(() => expect(checked()).toEqual(["3120154"]));
    expect(sent("POST", "/api/market/profile").map((c) => c.body.expected_revision)).toEqual([3, 4]);
    expect(sent("GET", "/api/market/profile")).toHaveLength(2);
  });

  it("상권 후보를 못 받으면 그 칸에 서버 문장과 [다시 시도]", async () => {
    server({ "/api/market/analysis-options": [503, { error: { message: "상권 분석에 문제가 생겼어요. 잠시 뒤 다시 시도해 주세요.", state: "error" } }] });
    show("add");
    await ready();
    change($("sn-industry"), "CS100001");
    await pickStation();
    await waitFor(() => expect(screen.getByText(/상권 후보를 불러오지 못했어요\. 상권 분석에 문제가 생겼어요/)).toBeTruthy());
    expect(getState().alert).toBe("");   // 맨 위 띠는 쓰지 않음
    routes["/api/market/analysis-options"] = () => ({ candidates: JSB, scope: {}, profile: market.prof });
    // (지도 칸의 [다시 시도]와 따로) 상권 칸의 [다시 시도]
    await act(async () => { fireEvent.click(document.querySelector(".sn-note.bad button")); });
    await waitFor(() => expect(checked()).toEqual(["3120154"]));
  });
});

describe("주소로 찾기", () => {
  it("후보가 여럿이면 서버 문장과 함께 고르게 하고, 고른 주소로 상권 후보 → 저장 본문의 위치는 주소", async () => {
    show("add");
    await ready();
    expect(screen.getByRole("radio", { name: "주소로 찾기" }).checked).toBe(true);
    change($("sn-name"), "우리분식");
    change($("sn-industry"), "CS100001");
    change($("sn-addr"), "장승배기로 10");
    // 한 칸짜리 폼이라 Enter 는 저장이 아니라 찾기
    await act(async () => { fireEvent.keyDown($("sn-addr"), { key: "Enter" }); });
    await waitFor(() => expect(screen.getByText("주소 후보가 여러 곳입니다. 의도한 주소를 선택하거나 구·동을 더 알려 주세요.")).toBeTruthy());
    expect(sent("POST", "/api/market/locations/search")[0].body).toEqual({ query: "장승배기로 10" });
    expect(sent("POST", "/api/account/stores")).toHaveLength(0);
    MARKET_ASK.forEach((p) => expect(paths()).not.toContain(p));   // 고르기 전에는 묻지 않음
    fireEvent.click(screen.getByRole("radio", { name: /장승배기로 100/ }));
    await waitFor(() => expect(checked()).toEqual(["3120154"]));
    expect(sent("POST", "/api/market/profile")[0].body.location).toEqual({ kind: "address", search_id: "s-1", candidate_id: "c2" });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "가게 등록하고 시작" })); });
    await waitFor(() => expect(sent("POST", "/api/account/stores")).toHaveLength(1));
    expect(sent("POST", "/api/account/stores")[0].body.location).toEqual({ kind: "address", label: "서울특별시 동작구 장승배기로 100",
      road_address: "서울특별시 동작구 장승배기로 100", latitude: 37.507, longitude: 126.938, station_id: null, station_name: null, district_name: "동작구" });
    expect(sent("POST", "/api/account/stores")[0].body.area).toEqual({ area_code: "3120154", name: "장승배기역", period: "20262" });
  });

  it("서울 주소 하나로 확정되면 바로 고른다", async () => {
    server({ "POST /api/market/locations/search": () => { market.lastSearch = [ADDR[0]]; return { status: "address_candidate", message: "조회된 서울 주소가 의도한 위치인지 확인해 주세요.", search_id: "s-2", candidates: [ADDR[0]] }; } });
    show("add");
    await ready();
    change($("sn-industry"), "CS100001");
    change($("sn-addr"), "장승배기로 10");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "찾기" })); });
    await waitFor(() => expect(checked()).toEqual(["3120154"]));
    expect(screen.getByRole("radio", { name: /장승배기로 10/ }).checked).toBe(true);
    expect(sent("POST", "/api/market/profile")[0].body.location).toEqual({ kind: "address", search_id: "s-2", candidate_id: "c1" });
  });

  it("후보가 없거나 서울 밖이면 서버 문장 그대로, 조회가 안 되면 역으로 이어 준다, 2자 미만은 보내지 않음", async () => {
    let answer = { status: "not_found", message: "일치하는 주소를 찾지 못했습니다. 도로명·건물번호 또는 지번을 다시 확인해 주세요.", search_id: null, candidates: [] };
    server({ "POST /api/market/locations/search": () => answer });
    show("add");
    await ready();
    change($("sn-addr"), "가");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "찾기" })); });
    expect($("sn-err-location").textContent).toBe("주소를 2자 이상 적어 주세요.");
    expect($("sn-addr").getAttribute("aria-describedby")).toBe("sn-err-location");
    expect(sent("POST", "/api/market/locations/search")).toHaveLength(0);

    change($("sn-addr"), "없는로 99");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "찾기" })); });
    await waitFor(() => expect(screen.getByText(answer.message)).toBeTruthy());

    answer = { status: "outside_seoul", message: "조회된 주소는 서울 밖입니다. 분석할 서울 지역의 주소를 알려 주세요.", search_id: "s-3",
      candidates: [{ ...ADDR[0], id: "o1", label: "경기도 성남시 분당구 정자로 1", in_seoul: false }] };
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "찾기" })); });
    await waitFor(() => expect(screen.getByText(answer.message)).toBeTruthy());
    expect(document.querySelector('input[name="address_candidate"]')).toBeNull();   // 서울 밖 주소는 고를 수 없음

    answer = { status: "lookup_unavailable", message: "주소 조회를 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.", search_id: null, candidates: [] };
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "찾기" })); });
    await waitFor(() => expect(screen.getByText("주소를 찾지 못했어요. 가까운 역으로 골라 주세요.")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "가까운 역으로" }));
    expect(screen.getByRole("radio", { name: "가까운 역으로" }).checked).toBe(true);
    await waitFor(() => expect(document.activeElement).toBe($("sn-line")));
    MARKET_ASK.forEach((p) => expect(paths()).not.toContain(p));
  });

  it("주소 칸 검사 오류(422)는 검사기 머리말 없이 그 문장 그대로", async () => {
    server({ "POST /api/market/locations/search": [422, { error: { message: "Value error, 주소 검색에는 도로명과 건물 번호를 입력해 주세요.", state: "invalid" } }] });
    show("add");
    await ready();
    change($("sn-addr"), "장승배기역 근처");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "찾기" })); });
    await waitFor(() => expect(screen.getByText("주소 검색에는 도로명과 건물 번호를 입력해 주세요.")).toBeTruthy());
  });
});

describe("오류 표시", () => {
  it("빈 폼: 칸마다 옆에 오류(aria-describedby), 첫 칸으로 포커스, 서버는 부르지 않음", async () => {
    show("add");
    await ready();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "가게 등록하고 시작" })); });
    expect($("sn-err-name").textContent).toBe("가게 이름을 적어 주세요.");
    expect($("sn-name").getAttribute("aria-describedby")).toBe("sn-err-name");
    expect($("sn-name").getAttribute("aria-invalid")).toBe("true");
    expect($("sn-err-industry").textContent).toBe("업종을 골라 주세요.");
    expect($("sn-industry").getAttribute("aria-describedby")).toBe("sn-err-industry");
    expect($("sn-err-location").textContent).toBe("주소를 찾거나 가까운 역을 골라 주세요.");
    await waitFor(() => expect(document.activeElement).toBe($("sn-name")));
    expect(sent("POST", "/api/account/stores")).toHaveLength(0);
    // 고치면 그 칸의 오류만 사라짐
    change($("sn-name"), "우리분식");
    expect($("sn-err-name").hidden).toBe(true);
    expect($("sn-err-industry").hidden).toBe(false);
  });

  it("메뉴 줄: 이름만·가격만 있거나 가격이 숫자가 아니면 그 줄 아래 오류, 그 칸으로 포커스", async () => {
    show("add");
    await ready();
    change($("sn-name"), "우리분식");
    change($("sn-industry"), "CS100001");
    await pickStation();
    await waitFor(() => expect(checked()).toEqual(["3120154"]));
    const names = document.querySelectorAll('input[name="menu_name"]');
    const prices = document.querySelectorAll('input[name="menu_price"]');
    change(names[0], "떡볶이");
    change(prices[1], "4500");
    change(names[2], "순대"); change(prices[2], "1,000,001");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "가게 등록하고 시작" })); });
    const errs = [...document.querySelectorAll(".sn-menu-err")].map((p) => (p.hidden ? "" : p.textContent));
    expect(errs).toEqual(["가격을 적어 주세요.", "메뉴 이름을 적어 주세요.", "가격은 0~1,000,000원 사이의 숫자로 적어 주세요."]);
    expect(prices[0].getAttribute("aria-describedby")).toBe(document.querySelectorAll(".sn-menu-err")[0].id);
    await waitFor(() => expect(document.activeElement).toBe(prices[0]));
    expect(sent("POST", "/api/account/stores")).toHaveLength(0);
    // 줄 지우기: 지운 자리의 다음 줄 이름 칸으로 포커스
    fireEvent.click(screen.getByRole("button", { name: "2번째 메뉴 지우기" }));
    await waitFor(() => expect(document.querySelectorAll('input[name="menu_name"]')).toHaveLength(2));
    await waitFor(() => expect(document.activeElement).toBe(document.querySelectorAll('input[name="menu_name"]')[1]));
  });

  it("가게 10곳(422 store_limit)은 폼 아래에 서버 문장 + 할 수 있는 일, 칸 이름이 든 서버 오류는 그 칸 옆에", async () => {
    let answer = [422, { error: { message: "가게는 한 계정에 10곳까지 등록할 수 있어요.", state: "store_limit" } }];
    server({ "POST /api/account/stores": () => answer });
    show("add");
    await ready();
    change($("sn-name"), "우리분식");
    change($("sn-industry"), "CS100001");
    await pickStation();
    await waitFor(() => expect(checked()).toEqual(["3120154"]));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "가게 등록하고 시작" })); });
    await waitFor(() => expect($("sn-form-err").hidden).toBe(false));
    expect($("sn-form-err").textContent).toBe("가게는 한 계정에 10곳까지 등록할 수 있어요. 프로필에서 쓰지 않는 가게를 빼면 새로 등록할 수 있어요.");
    expect($("sn-form-err").getAttribute("role")).toBe("alert");
    expect(getState().stage).toBe("store-new");
    expect(sent("POST", "/api/auth/store")).toHaveLength(0);

    answer = [422, { error: { message: "가게 이름에 쓸 수 없는 글자가 있어요.", state: "invalid" } }];
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "가게 등록하고 시작" })); });
    await waitFor(() => expect($("sn-err-name").textContent).toBe("가게 이름에 쓸 수 없는 글자가 있어요."));
    expect($("sn-form-err").hidden).toBe(true);
    await waitFor(() => expect(document.activeElement).toBe($("sn-name")));
  });

  it("저장 중에는 버튼을 잠가 한 번만 보내고, 등록 뒤 가게 열기가 실패하면 다시 눌러도 새로 등록하지 않고 열기만", async () => {
    let release;
    const hold = new Promise((r) => { release = r; });
    let openFails = true;
    server({
      "POST /api/account/stores": async (b) => { await hold; return [201, { store: { ...NEW_ROW, ...b } }]; },
      "POST /api/auth/store": (b) => (openFails ? [503, { error: { message: "잠시 뒤 다시 해 주세요.", state: "down" } }] : meWith([NEW_ROW], b.store_id)),
    });
    show("add");
    await ready();
    change($("sn-name"), "우리분식");
    change($("sn-industry"), "CS100001");
    await pickStation();
    await waitFor(() => expect(checked()).toEqual(["3120154"]));
    const btn = screen.getByRole("button", { name: "가게 등록하고 시작" });
    await act(async () => { fireEvent.click(btn); });
    expect(screen.getByRole("button", { name: "등록하는 중…" }).disabled).toBe(true);
    await act(async () => { fireEvent.submit(document.querySelector(".sn-form")); });
    await act(async () => { release(); });
    await waitFor(() => expect($("sn-form-err").hidden).toBe(false));
    expect(sent("POST", "/api/account/stores")).toHaveLength(1);
    expect($("sn-form-err").textContent).toBe("가게는 등록했어요. 가게를 열지 못했어요: 잠시 뒤 다시 해 주세요.");
    openFails = false;
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "가게 열기" })); });
    await waitFor(() => expect(getState().stage).toBe("app"));
    expect(sent("POST", "/api/account/stores")).toHaveLength(1);
    expect(sent("POST", "/api/auth/store")).toHaveLength(2);
  });

  it("[취소]는 온 곳으로: 가게 선택에서 왔으면 가게 선택, 프로필에서 왔으면 프로필", async () => {
    show("add", { from: "profile" });
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    expect(getState().stage).toBe("profile");
    cleanup();
    show("signup");
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    expect(getState().stage).toBe("pick");
  });
});

describe("가게 정보 고치기", () => {
  it("저장한 값으로 채우고, 위치·상권을 안 바꾸면 상권 서비스에 묻지 않고 바뀐 칸만 PATCH → 프로필", async () => {
    show("edit", { storeId: SAVED.store_id, from: "profile", me: meWith([SAVED], null) });
    await ready();
    expect(h1()).toBe("가게 정보 고치기");
    expect(screen.queryByText("등록하면 이렇게 시작해요")).toBeNull();
    expect(sent("GET", `/api/account/stores/${SAVED.store_id}`)).toHaveLength(1);
    expect($("sn-name").value).toBe("우리분식");
    expect($("sn-industry").value).toBe("CS100001");
    expect($("sn-ch-baemin").checked).toBe(true);
    expect($("sn-ch-yogiyo").checked).toBe(false);
    expect([...document.querySelectorAll('input[name="menu_name"]')].map((x) => x.value)).toEqual(["떡볶이", "순대"]);
    expect([...document.querySelectorAll('input[name="menu_price"]')].map((x) => x.value)).toEqual(["4500", "5000"]);
    // 저장한 위치 한 줄 + [위치 바꾸기], 저장한 상권 하나가 골라져 있음
    expect(document.querySelector(".sn-saved b").textContent).toBe("장승배기역");
    expect(checked()).toEqual(["3120154"]);
    expect($("sn-area-sub-3120154").textContent).toBe("공식 상권 코드 3120154 · 2026년 2분기 자료");
    change($("sn-name"), "우리분식 본점");
    change(document.querySelectorAll('input[name="menu_price"]')[1], "5500");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "저장" })); });
    await waitFor(() => expect(getState().stage).toBe("profile"));
    expect(sent("PATCH", `/api/account/stores/${SAVED.store_id}`)[0].body).toEqual({ name: "우리분식 본점", menus: [{ name: "떡볶이", price: 4500 }, { name: "순대", price: 5500 }] });
    expect(paths()).toContain("/api/auth/me");   // 상단 바·가게 선택의 이름이 서버와 같게
    MARKET_ASK.forEach((p) => expect(paths()).not.toContain(p));
    // 11/21: 저장했다는 한 줄 (오른쪽 아래 결과 띠, 실시간 확인 18)
    expect(getState().acctNotice).toBe("우리분식 본점 정보를 저장했어요.");
    await waitFor(() => expect(screen.getByText("우리분식 본점 정보를 저장했어요.")).toBeTruthy());
  });

  it("고친 것 없이 [저장]하면 PATCH 없이 '바뀐 내용이 없어 그대로 두었어요' (11/21)", async () => {
    show("edit", { storeId: SAVED.store_id, from: "profile", me: meWith([SAVED], null) });
    await ready();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "저장" })); });
    await waitFor(() => expect(getState().stage).toBe("profile"));
    expect(sent("PATCH", `/api/account/stores/${SAVED.store_id}`)).toHaveLength(0);
    expect(getState().acctNotice).toBe("바뀐 내용이 없어 그대로 두었어요.");
  });

  it("업종 칸은 음식 업종(코드 CS1…)만, 고치기에서 저장한 업종이 그 밖이면 그 하나는 남긴다 (11/21)", async () => {
    const ALL = [...OPTIONS.industries, { code: "CS200001", name: "일반교습학원" }, { code: "CS300001", name: "슈퍼마켓" }];
    server({ "/api/market/options": { ...OPTIONS, industries: ALL },
      [`/api/account/stores/${SAVED.store_id}`]: { store: { ...SAVED, industry_code: "CS300001", business_type_name: "슈퍼마켓" } } });
    const opts = () => [...$("sn-industry").options].map((o) => o.value);
    const first = show("add");
    await ready();
    expect(opts()).toEqual(["", "CS100001", "CS100010"]);
    first.unmount();
    show("edit", { storeId: SAVED.store_id, from: "profile", me: meWith([SAVED], null) });
    await ready();
    expect(opts()).toEqual(["", "CS100001", "CS100010", "CS300001"]);
    expect($("sn-industry").value).toBe("CS300001");
  });

  it("[위치 바꾸기]로 새 역을 고르면 상권 서비스에 묻고, PATCH 에 위치·상권이 들어간다 ([위치 바꾸지 않기]로 되돌리기)", async () => {
    show("edit", { storeId: SAVED.store_id, from: "profile", me: meWith([SAVED], null) });
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "위치 바꾸기" }));
    expect(screen.getByRole("radio", { name: "가까운 역으로" }).checked).toBe(true);
    expect($("sn-line").value).toBe("line-7");   // 저장한 역의 호선
    change($("sn-station"), "kric-sd");
    await waitFor(() => expect(checked()).toEqual(["3110836"]));
    // 되돌리기 → 저장한 위치·상권, 상권 서비스는 더 부르지 않음
    fireEvent.click(screen.getByRole("button", { name: "위치 바꾸지 않기" }));
    expect(checked()).toEqual(["3120154"]);
    await waitFor(() => expect(document.activeElement).toBe($("sn-loc-change")));
    fireEvent.click(screen.getByRole("button", { name: "위치 바꾸기" }));
    change($("sn-station"), "kric-sd");
    await waitFor(() => expect(checked()).toEqual(["3110836"]));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "저장" })); });
    await waitFor(() => expect(getState().stage).toBe("profile"));
    const body = sent("PATCH", `/api/account/stores/${SAVED.store_id}`)[0].body;
    expect(Object.keys(body).sort()).toEqual(["area", "location"]);
    expect(body.location).toMatchObject({ kind: "station", station_id: "kric-sd", label: "상도역", station_name: "상도역" });
    expect(body.area).toEqual({ area_code: "3110836", name: "상도역 5번", period: "20262" });
  });

  it("역으로 등록한 가게의 업종만 바꾸면 저장한 역으로 상권 후보를 다시 받고, 고른 상권이 있으면 그대로", async () => {
    show("edit", { storeId: SAVED.store_id, from: "profile", me: meWith([SAVED], null) });
    await ready();
    change($("sn-industry"), "CS100010");
    await waitFor(() => expect(sent("POST", "/api/market/profile")).toHaveLength(1));
    expect(sent("POST", "/api/market/profile")[0].body).toMatchObject({ location: { kind: "station", station_id: "kric-jsb" }, industry_code: "CS100010" });
    await waitFor(() => expect($("sn-area-3110826")).toBeTruthy());
    expect(checked()).toEqual(["3120154"]);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "저장" })); });
    await waitFor(() => expect(getState().stage).toBe("profile"));
    const body = sent("PATCH", `/api/account/stores/${SAVED.store_id}`)[0].body;
    expect(body).toMatchObject({ industry_code: "CS100010", business_type_name: "커피-음료", area: { area_code: "3120154", period: "20262" } });
  });

  it("주소로 등록한 가게의 업종을 바꾸면 주소를 다시 찾게 하고(저장한 주소를 채워 둠), 찾기 전에는 저장하지 않는다", async () => {
    show("edit", { storeId: SAVED_ADDR.store_id, from: "profile", me: meWith([SAVED_ADDR], null) });
    await ready();
    expect(document.querySelector(".sn-saved b").textContent).toBe("서울특별시 동작구 장승배기로 10");
    change($("sn-industry"), "CS100010");
    expect($("sn-addr").value).toBe("서울특별시 동작구 장승배기로 10");
    expect(screen.getByText("업종을 바꾸면 상권 자료가 달라져요. 주소를 다시 찾아 상권을 골라 주세요.")).toBeTruthy();
    MARKET_ASK.forEach((p) => expect(paths()).not.toContain(p));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "저장" })); });
    expect($("sn-err-location").textContent).toBe("업종을 바꿨으니 주소를 다시 찾아 상권을 골라 주세요.");
    expect(sent("PATCH", `/api/account/stores/${SAVED_ADDR.store_id}`)).toHaveLength(0);
    // 업종을 되돌리면 저장한 위치·상권 그대로
    change($("sn-industry"), "CS100001");
    expect(checked()).toEqual(["3120154"]);
  });

  it("예시 가게처럼 고칠 수 없는 가게면 서버 문장과 [돌아가기]", async () => {
    server({ "/api/account/stores/store_ongi": [403, { error: { message: "예시 가게는 고칠 수 없어요.", state: "sample_store" } }] });
    show("edit", { storeId: "store_ongi", from: "profile" });
    await waitFor(() => expect(screen.getByText(/가게 정보를 불러오지 못했어요\. 예시 가게는 고칠 수 없어요\./)).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "돌아가기" }));
    expect(getState().stage).toBe("profile");
  });
});

describe("순수 계산 (storeApi.js)", () => {
  it("상권 줄: 업종 자료가 있는 최신 분기, 고를 수 없는 이유, 기본 선택", () => {
    const rows = areaRows(JSB);
    expect(rows.map((r) => [r.code, r.period && r.period.code, r.blocked])).toEqual([
      ["3120154", "20262", ""], ["3110826", "20261", ""], ["3110999", "20262", "경계와 상권 명칭의 연결 확인이 필요합니다."],
      ["3110998", null, "이 업종의 상권 자료가 없어 고를 수 없어요."]]);
    expect(latestIndustryPeriod({})).toBeNull();
    expect(defaultArea(rows, "")).toBe("3120154");
    expect(defaultArea(rows, "3110826")).toBe("3110826");
    expect(defaultArea(rows, "3110999")).toBe("3120154");     // 고를 수 없는 예전 선택은 버림
    expect(defaultArea(areaRows([cand("1234567", "경계", { relation: "boundary" })]), "")).toBe("1234567");
    expect(defaultArea(areaRows([cand("1234567", "먼 곳")]), "")).toBe("");
  });
  it("음식 업종만 (코드 CS1…), 남길 업종 하나", () => {
    const list = [{ code: "CS100001", name: "한식음식점" }, { code: "CS200001", name: "일반교습학원" }, { code: "CS100010", name: "커피-음료" }];
    expect(foodIndustries(list).map((x) => x.code)).toEqual(["CS100001", "CS100010"]);
    expect(foodIndustries(list, "CS200001").map((x) => x.code)).toEqual(["CS100001", "CS200001", "CS100010"]);
    expect(foodIndustries(null)).toEqual([]);
  });
  it("메뉴 검사·위치 본문·오류 칸·역 고르기·고치기 본문", () => {
    expect(checkMenus([{ key: "a", name: " 떡볶이 ", price: "4,500원" }, { key: "b", name: "", price: "" }, { key: "c", name: "가".repeat(31), price: "1" }]))
      .toEqual({ menus: [{ name: "떡볶이", price: 4500 }], errors: { c: { name: "메뉴 이름은 30자까지 적을 수 있어요." } } });
    expect(locationBody({ kind: "station", name: "장승배기역", label: "장승배기역", station_id: "kric-jsb", latitude: 37.5, longitude: 126.9, district_name: "동작구" }))
      .toEqual({ kind: "station", label: "장승배기역", road_address: null, latitude: 37.5, longitude: 126.9, station_id: "kric-jsb", station_name: "장승배기역", district_name: "동작구" });
    expect(errorField("메뉴 가격은 0~1,000,000원 사이의 정수예요.")).toBe("menus");
    expect(errorField("상권 코드(area_code)는 숫자 7자리예요.")).toBe("area");
    expect(errorField("가게는 한 계정에 10곳까지 등록할 수 있어요.")).toBe("form");
    expect(stationsOf(OPTIONS.stations, "line-9", OPTIONS.station_lines).map((s) => s.name)).toEqual(["노량진역"]);
    expect(storePatch(SAVED, { name: SAVED.name, industry_code: "CS100001", business_type_name: "한식음식점", business_status: "operating",
      channels: ["baemin"], menus: SAVED.menus, location: null, area: null })).toEqual({});
  });
});
