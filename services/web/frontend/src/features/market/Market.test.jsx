import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { resetStore, setState, getState } from "../../state/store.js";
import { resetMarketForTest, getMarket } from "./state.js";
import { resetNaverMapsForTest } from "../../components/NaverMap.jsx";
import Market, { mapSource } from "./Market.jsx";

const COND = { area_code: "A1", area_name: "상도역", industry_code: "I1", industry_name: "한식음식점", period: "20262", period_label: "2026년 2분기", revision: 3, home: true };
const RESP = {
  status: { state: "ready", data: { status: "ready", message: "서버에 2026년 1분기~2026년 2분기 상권 자료 2개 분기가 준비돼 있어요.", periods: ["20261", "20262"], verified_files: 837 },
    store: { name: "상도 국밥", station_name: "상도역", business_type_name: "한식" } },
  setup: { conditions: COND },
  "analysis-options": { candidates: [{ area_code: "A1", name: "상도역", district_code: "D1", available_periods: ["20261", "20262"] }] },
  options: { industries: [{ code: "I1", name: "한식음식점" }] },
  sales: { total: { value: 1200000000 }, distributions: { time: { label: "시간대", items: [{ label: "점심", share_percent: 60 }] } } },
  stores: { counts: { total: { label: "전체", value: 12, unit: "개" }, opened: { label: "개업", value: 1 }, closed: { label: "폐업", value: 2 } } },
  population: { total: { value: 5000 } },
  "area-context": { status: "not_collected" },
  changes: { previous_period: "20252", current_period: "20262", metrics: [{ key: "sales", label: "추정매출", unit: "원", percent: -2.5, previous: { value: 1 }, current: { value: 2 } }] },
  "comparison-options": { districts: [{ code: "D1", name: "동작구" }], areas: [{ area_code: "A2", name: "노량진", district_code: "D1" }] },
  comparison: { base_area: { name: "상도역" }, comparison_area: { name: "노량진" }, metrics: [{ key: "sales", label: "추정매출", unit: "원", percent: 10, base: { value: 100000000 }, comparison: { value: 110000000 } }] },
  "cultural-events": { district: "동작구", events: [{ title: "음악회", link: "javascript:x", category: "공연" }] },
};

let calls, scrolled;
beforeEach(() => {
  resetStore(); resetMarketForTest(); calls = [];
  // jsdom 에는 scrollIntoView 가 없다 (주변 상권을 누르면 비교 칸으로 내림, 11/22). 부른 요소와 인자를 남긴다
  Element.prototype.scrollIntoView = vi.fn(function scrollIntoView(opts) { scrolled.push({ id: this.id, opts }); });
  scrolled = [];
  delete window.matchMedia;
  global.fetch = vi.fn(async (url) => {
    const path = String(url).replace("/api/market/", "").split("?")[0];
    calls.push(String(url));
    return { ok: true, status: 200, json: async () => RESP[path] || {} };
  });
});
afterEach(() => { cleanup(); });

describe("상권 분석 화면", () => {
  it("처음 열면 상태 → 기본 조건 → 자료를 읽어 지표를 그린다", async () => {
    render(<Market />);
    await screen.findAllByText("12억 원");
    expect(screen.getAllByText("-2.50%").every((e) => e.className === "mk-neg")).toBe(true);
    expect(screen.getAllByText("12개").length).toBe(2);
    expect(screen.getByText(/상권 분석 비서 · 상도 국밥 · 상도역 · 한식/)).toBeTruthy();
    expect(screen.getByText("상도역 · 한식음식점 · 2026년 2분기 · 우리 가게 기준")).toBeTruthy();
    expect(calls.some((u) => u.includes("sales?expected_revision=3"))).toBe(true);
    expect(getState().staffMarket.state).toBe("ready");
    expect(screen.getByText("음악회").tagName).toBe("B");   // http(s) 아닌 링크는 열지 않음
  });

  it("머리 고지는 한 줄 (출처·추정치·우리 가게 매출 아님), 옆 칸 제목은 '서울시 자료 최신화'", async () => {
    render(<Market />);
    await screen.findAllByText("12억 원");
    const sub = document.querySelector(".page-head .ph-sub");
    // 11/20 Figma F1 문구로 바꿈 (출처·추정치·우리 가게 매출 아님은 그대로 한 줄)
    expect(sub.textContent).toBe("서울시 상권분석서비스 공식 자료로 우리 가게 주변 상권을 봐요. 상권·업종 전체의 추정치이고, 우리 가게 매출이 아니에요.");
    expect(screen.getAllByText(/우리 가게 (실제 )?매출이 아니에요/).length).toBe(1);
    expect(screen.getByRole("heading", { name: "서울시 자료 최신화" })).toBeTruthy();
    expect(screen.queryByText(/열린데이터광장/)).toBeNull();
    // 11/21: 볼 수 있는 분기 범위만 사장님 말로 (원본 파일 수·'서버에 준비'·'확인 기록 없음' 같은 안쪽 사정은 적지 않음)
    expect(screen.getByText("2026년 1분기~2026년 2분기 자료를 볼 수 있어요.")).toBeTruthy();
    expect(document.querySelector(".mk-seoul").textContent).not.toMatch(/원본 파일|837|확인 기록|서버에/);
    expect(screen.getByText("2026년 2분기 · 한식음식점")).toBeTruthy();   // 기준 분기·업종은 지표에 그대로
  });

  it("비교 탭을 열면 목록을 받고 비교한다, 화면을 다시 열어도 남는다", async () => {
    const { unmount } = render(<Market />);
    await screen.findAllByText("12억 원");
    fireEvent.click(screen.getByRole("tab", { name: "타 상권 1:1 비교" }));
    await screen.findByText("우리 가게 상권과 비교할 상권을 골라 주세요.");
    fireEvent.click(screen.getByRole("button", { name: "비교하기" }));
    await screen.findByText("1억 1,000만 원");
    expect(calls.some((u) => u.includes("comparison?comparison_area_code=A2&expected_revision=3"))).toBe(true);
    unmount();
    const n = calls.length;
    render(<Market />);
    expect(screen.getByText("1억 1,000만 원")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "타 상권 1:1 비교" }).getAttribute("aria-selected")).toBe("true");
    expect(calls.length).toBe(n);   // 다시 부르지 않음
  });

  it("비교 탭이 409를 받으면 서버의 조건 번호로 맞춰 한 번 다시 보낸다 (11/22 QA, WAS 두 대)", async () => {
    render(<Market />);
    await screen.findAllByText("12억 원");
    // 이제부터 서버 조건 번호는 4: 번호 3으로 온 비교 요청은 409, setup 은 번호 4를 준다
    const base = global.fetch;
    global.fetch = vi.fn(async (url, opts) => {
      const u = String(url), path = u.replace("/api/market/", "").split("?")[0];
      calls.push(u);
      if (path.startsWith("comparison") && u.includes("expected_revision=3")) {
        return { ok: false, status: 409, json: async () => ({ error: { message: "분석 조건이 변경됐습니다. 최신 조건을 불러온 뒤 다시 조회해 주세요." } }) };
      }
      if (path === "setup") return { ok: true, status: 200, json: async () => ({ conditions: { ...COND, revision: 4 } }) };
      return base(url, opts);
    });
    fireEvent.click(screen.getByRole("tab", { name: "타 상권 1:1 비교" }));
    await screen.findByText("우리 가게 상권과 비교할 상권을 골라 주세요.");
    expect(calls.some((u) => u.includes("comparison-options?expected_revision=4"))).toBe(true);
    expect(getMarket().cond.revision).toBe(4);
    fireEvent.click(screen.getByRole("button", { name: "비교하기" }));
    await screen.findByText("1억 1,000만 원");
    expect(calls.some((u) => u.includes("comparison?comparison_area_code=A2&expected_revision=4"))).toBe(true);
    expect(screen.queryByText(/분석 조건이 변경됐습니다/)).toBeNull();
  });

  it("비교 중 다른 화면에서 조건이 바뀌었으면(409 뒤 다른 상권) 화면을 새 조건으로 다시 그린다", async () => {
    render(<Market />);
    await screen.findAllByText("12억 원");
    fireEvent.click(screen.getByRole("tab", { name: "타 상권 1:1 비교" }));
    await screen.findByText("우리 가게 상권과 비교할 상권을 골라 주세요.");
    const base = global.fetch;
    global.fetch = vi.fn(async (url, opts) => {
      const u = String(url), path = u.replace("/api/market/", "").split("?")[0];
      calls.push(u);
      if (path === "comparison" && u.includes("expected_revision=3")) return { ok: false, status: 409, json: async () => ({ error: { message: "x" } }) };
      if (path === "setup") return { ok: true, status: 200, json: async () => ({ conditions: { ...COND, period: "20261", period_label: "2026년 1분기", revision: 5 } }) };
      return base(url, opts);
    });
    fireEvent.click(screen.getByRole("button", { name: "비교하기" }));
    await screen.findByText(/새 조건으로 다시 불러왔어요/);
    await waitFor(() => expect(getMarket().cond.revision).toBe(5));
    expect(calls.some((u) => u.includes("sales?expected_revision=5"))).toBe(true);
  });

  it("가게가 바뀌면(epoch) 처음부터, ready 가 아니면 안내와 잠긴 조건", async () => {
    render(<Market />);
    await screen.findAllByText("12억 원");
    cleanup();
    RESP.status = { state: "off", message: "상권 서비스가 꺼져 있어요." };
    act(() => setState({ epoch: getState().epoch + 1 }));
    render(<Market />);
    await screen.findByText("상권 서비스가 꺼져 있어요.");
    expect(getMarket().cond).toBeNull();
    expect(screen.getByRole("button", { name: "이 조건으로 보기" }).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "AI에게 묻기" }).disabled).toBe(false);
  });

  it("navTo 로 탭을 연다", async () => {
    setState({ nav: { name: "market", sub: "stores", seq: 1 } });
    render(<Market />);
    await waitFor(() => expect(screen.getByRole("tab", { name: "점포·개폐업" }).getAttribute("aria-selected")).toBe("true"));
    expect(document.activeElement.id).toBe("mk-tab-stores");
  });
});

// ── 지도 (11/20, 6차 회의 ⑥) ─────────────────────────────────────────────
const sq = (lng, lat) => ({ type: "Polygon", coordinates: [[[lng, lat], [lng + 0.002, lat], [lng + 0.002, lat + 0.002], [lng, lat + 0.002], [lng, lat]]] });
const MAP_RESP = {
  ...RESP,
  status: { state: "ready", data: { message: "준비됨" }, store: { name: "상도 국밥", station_name: "상도역", business_type_name: "한식" } },
  "analysis-options": {
    scope: { boundary_publication_date: "2023-10-23", boundary_notice: "2023년 공개 경계" },
    candidates: [
      { area_code: "A1", name: "상도역", district_code: "D1", relation: "inside", distance_m: 0, available_periods: ["20261", "20262"], geometry: sq(126.947, 37.502) },
      { area_code: "A2", name: "노량진", district_code: "D2", relation: "nearby", distance_m: 420, available_periods: ["20262"], geometry: sq(126.942, 37.512) },
      { area_code: "A3", name: "장승배기", district_code: "D1", relation: "nearby", distance_m: 610, available_periods: ["20262"],
        selection_blocked_reason: "경계와 상권 명칭의 연결 확인이 필요합니다.", geometry: sq(126.939, 37.505) },
    ],
  },
  "analysis-selection": { revision: 3, profile: { industry: { code: "I1", name: "한식음식점" },
    location: { kind: "station", station_id: "S1", label: "상도역", latitude: 37.5028, longitude: 126.9479 } } },
  options: { industries: [{ code: "I1", name: "한식음식점" }, { code: "I2", name: "분식전문점" }] },
  "comparison-options": { districts: [{ code: "D1", name: "동작구" }, { code: "D2", name: "영등포구" }], areas: [
    { area_code: "A2", name: "노량진", district_code: "D2", selectable: true },
    { area_code: "A3", name: "장승배기", district_code: "D1", selectable: false, reason: "공개 경계와 상권 자료의 명칭이 달라 연결 확인이 필요합니다." },
  ] },
  "map-config": { client_id: "", configured: false },
};

function fakeNaver() {
  const made = { polygons: [], markers: [], listeners: [] };
  class LatLng { constructor(lat, lng) { this.lat = lat; this.lng = lng; } }
  const maps = {
    LatLng, LatLngBounds: class { constructor(sw, ne) { this.sw = sw; this.ne = ne; } }, Point: class {},
    Map: class { fitBounds() {} setCenter() {} setZoom() {} destroy() {} },
    Polygon: class { constructor(o) { this.opts = o; this.map = o.map; made.polygons.push(this); } setMap(m) { this.map = m; } setOptions() {} },
    Marker: class { constructor(o) { this.opts = o; made.markers.push(this); } setMap() {} },
    Event: { addListener: (target, name, fn) => { const h = { target, name, fn }; made.listeners.push(h); return h; }, removeListener: () => {} },
    Position: { TOP_RIGHT: 3 },
  };
  return { maps, made };
}

describe("상권 분석 화면의 지도", () => {
  let resp;
  beforeEach(() => {
    resetNaverMapsForTest();
    delete window.naver;
    resp = JSON.parse(JSON.stringify(MAP_RESP));
    global.fetch = vi.fn(async (url, opts = {}) => {
      const path = String(url).replace("/api/market/", "").split("?")[0];
      calls.push(`${opts.method || "GET"} ${String(url)}`);
      return { ok: true, status: 200, json: async () => resp[path] || {} };
    });
  });
  afterEach(() => { delete window.naver; });

  it("지도 구역: 제목·출처 한 줄·범례, 고른 상권 실선 + 주변 상권 점선, 가게 위치 마커", async () => {
    const { maps, made } = fakeNaver();
    window.naver = { maps };
    render(<Market />);
    await screen.findAllByText("12억 원");
    expect(screen.getByRole("heading", { name: "지도" })).toBeTruthy();
    expect(screen.getByText("네이버 지도 · 2023년 공개 상권 경계")).toBeTruthy();
    const legend = screen.getByRole("list", { name: "지도 범례" });
    expect(legend.textContent).toBe("가게 위치고른 상권주변 상권 (누르면 비교)");
    await waitFor(() => expect(made.polygons.length).toBe(3));
    expect(made.polygons.map((p) => p.opts.strokeStyle)).toEqual(["solid", "shortdash", "shortdot"]);   // A1 고른 · A2 주변 · A3 고를 수 없음
    expect(made.polygons[0].opts.paths[0][0]).toEqual(new maps.LatLng(37.502, 126.947));
    expect(made.markers.length).toBe(1);
    expect(made.markers[0].opts.title).toBe("가게 위치 · 상도역");
    expect(made.markers[0].opts.position).toEqual(new maps.LatLng(37.5028, 126.9479));
    // 지도 구역은 분석 조건과 지표 사이
    const order = [".mk-cond", ".mk-map", ".mk-tiles", ".mk-main"].map((q) => document.querySelector(q));
    order.slice(1).forEach((el, i) => expect(order[i].compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy());
    expect(screen.getAllByText(/우리 가게 (실제 )?매출이 아니에요/).length).toBe(1);   // 고지는 머리 한 곳
  });

  it("주변 상권 다각형을 누르면 비교 탭이 열리고 그 상권(다른 구)이 골라진다", async () => {
    const { maps, made } = fakeNaver();
    window.naver = { maps };
    render(<Market />);
    await screen.findAllByText("12억 원");
    await waitFor(() => expect(made.polygons.length).toBe(3));
    const clickOf = (poly) => made.listeners.find((h) => h.target === poly && h.name === "click").fn;
    act(() => clickOf(made.polygons[0])());                 // 고른 상권은 아무 일 없음
    expect(screen.getByRole("tab", { name: "타 상권 1:1 비교" }).getAttribute("aria-selected")).toBe("false");
    act(() => clickOf(made.polygons[1])());
    expect(screen.getByRole("tab", { name: "타 상권 1:1 비교" }).getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement.id).toBe("mk-tab-compare");
    await screen.findByText("노량진 상권을 비교 대상으로 골랐어요. '비교하기'를 누르면 두 상권을 나란히 봐요.");
    expect(document.getElementById("mk-cmp-district").value).toBe("D2");
    expect(document.getElementById("mk-cmp-area").value).toBe("A2");
    fireEvent.click(screen.getByRole("button", { name: "비교하기" }));
    await screen.findByText("1억 1,000만 원");
    expect(calls.some((u) => u.includes("comparison?comparison_area_code=A2&expected_revision=3"))).toBe(true);
  });

  it("지도가 안 떠도(키 없음) 안내 한 줄과 목록 버튼으로 같은 동작, 고를 수 없는 상권은 이유 한 줄", async () => {
    render(<Market />);
    await screen.findAllByText("12억 원");
    expect(await screen.findByText("지금은 지도를 볼 수 없어요. 아래 목록에서 상권을 고를 수 있어요.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "다시 시도" })).toBeTruthy();
    const list = screen.getByRole("list", { name: "주변 상권 (누르면 비교)" });
    expect(list.querySelector("[aria-current=true]").textContent).toBe("상도역 · 지금 보는 상권");
    fireEvent.click(screen.getByRole("button", { name: "장승배기 · 비교할 수 없음" }));
    await screen.findByText("장승배기 상권은 공개 경계와 상권 자료의 이름이 달라 지금은 비교할 수 없어요.");
    expect(document.getElementById("mk-cmp-area").value).not.toBe("A3");
    fireEvent.click(screen.getByRole("button", { name: "노량진 · 420m" }));
    await screen.findByText(/노량진 상권을 비교 대상으로 골랐어요/);
    expect(document.getElementById("mk-cmp-area").value).toBe("A2");
    expect(calls.filter((u) => u.includes("comparison-options")).length).toBe(1);   // 비교 목록은 한 번만
    // 조건·지표·탭은 그대로 쓸 수 있음
    expect(screen.getByRole("button", { name: "이 조건으로 보기" }).disabled).toBe(false);
  });

  it("비교 목록에 없는 상권이면 그 말 한 줄", async () => {
    resp["comparison-options"].areas = [];
    render(<Market />);
    await screen.findAllByText("12억 원");
    fireEvent.click(await screen.findByRole("button", { name: "노량진 · 420m" }));
    await screen.findByText("노량진 상권은 비교할 수 있는 상권 목록에 없어요.");
  });

  it("주소로 등록한 가게는 업종을 바꾸지 않고 안내 (역 위치를 지어 보내지 않음)", async () => {
    resp["analysis-selection"].profile.location = { kind: "address", label: "서울특별시 동작구 상도로 1", latitude: 37.5, longitude: 126.94 };
    render(<Market />);
    await screen.findAllByText("12억 원");
    fireEvent.change(document.getElementById("mk-industry"), { target: { value: "I2" } });
    fireEvent.click(screen.getByRole("button", { name: "이 조건으로 보기" }));
    await screen.findByText("주소로 등록한 가게는 아직 이 화면에서 업종을 바꿀 수 없어요. 상권과 분기는 바꿀 수 있어요.");
    expect(calls.some((u) => u.startsWith("POST") && u.includes("/profile"))).toBe(false);
    expect(document.getElementById("mk-industry").value).toBe("I1");
    expect(screen.getByRole("button", { name: "이 조건으로 보기" }).disabled).toBe(false);
  });

  it("주소로 등록한 가게: 머리줄에 'null' 대신 등록한 위치를 짧게, 업종 칸은 처음부터 잠기고 까닭 한 줄 (11/21 M7·7)", async () => {
    resp.status = { state: "ready", data: { status: "ready", periods: ["20262"] },
      store: { name: "동네맛김밥", station_name: null, location_label: "서울특별시 마포구 와우산로 94 학교법인홍익학원", business_type_name: "분식전문점", sample: false } };
    resp["analysis-selection"].profile.location = { kind: "address", label: "서울특별시 마포구 와우산로 94 학교법인홍익학원", latitude: 37.55, longitude: 126.92 };
    render(<Market />);
    await screen.findAllByText("12억 원");
    expect(document.querySelector(".owner-chip").textContent).toBe("상권 분석 비서 · 동네맛김밥 · 마포구 와우산로 94 · 분식전문점");
    expect(document.body.textContent).not.toMatch(/null|undefined/);
    const sel = document.getElementById("mk-industry");
    expect(sel.disabled).toBe(true);
    expect(sel.getAttribute("aria-describedby")).toBe("mk-industry-note");
    expect(document.getElementById("mk-industry-note").textContent).toBe("주소로 등록한 가게는 업종을 프로필의 '정보 고치기'에서 바꿔요.");
    // 상권·분기는 그대로 고를 수 있다
    expect(document.getElementById("mk-area").disabled).toBe(false);
    expect(screen.getByRole("button", { name: "이 조건으로 보기" }).disabled).toBe(false);
  });

  it("역으로 등록한 가게는 업종 칸이 열려 있고 까닭 줄이 없다", async () => {
    render(<Market />);
    await screen.findAllByText("12억 원");
    expect(document.getElementById("mk-industry").disabled).toBe(false);
    expect(document.getElementById("mk-industry-note")).toBeNull();
  });

  it("조건을 바꾸는 동안 보던 숫자는 흐리게, 지표 라벨·지금 조건 줄은 새 숫자와 함께 바뀐다 (11/21 8)", async () => {
    let release;
    const gate = new Promise((ok) => { release = ok; });
    const NEW = { ...COND, period: "20261", period_label: "2026년 1분기", home: false, revision: 4 };
    let applied = false;
    global.fetch = vi.fn(async (url, opts = {}) => {
      const path = String(url).replace("/api/market/", "").split("?")[0];
      calls.push(`${opts.method || "GET"} ${String(url)}`);
      if (opts.method === "POST" && path === "analysis-selection") applied = true;
      if (path === "setup" && applied) return { ok: true, status: 200, json: async () => ({ conditions: NEW }) };
      if (path === "sales" && String(url).includes("expected_revision=4")) {
        await gate;
        return { ok: true, status: 200, json: async () => ({ total: { value: 900000000 } }) };
      }
      return { ok: true, status: 200, json: async () => resp[path] || {} };
    });
    render(<Market />);
    await screen.findAllByText("12억 원");
    const tiles = document.querySelector(".mk-tiles");
    expect(tiles.className).not.toContain("mk-dim");
    fireEvent.change(document.getElementById("mk-period"), { target: { value: "20261" } });
    fireEvent.click(screen.getByRole("button", { name: "이 조건으로 보기" }));
    await waitFor(() => expect(document.querySelector(".mk-tiles").className).toContain("mk-dim"));
    expect(document.querySelector(".mk-tiles").getAttribute("aria-busy")).toBe("true");
    expect(document.querySelector(".mk-main").className).toContain("mk-dim");
    // 숫자가 오기 전: 라벨·지금 조건 줄은 아직 보던 숫자의 조건
    expect(screen.getByText("2026년 2분기 · 한식음식점")).toBeTruthy();
    expect(document.querySelector(".mk-cond-line").textContent).toContain("2026년 2분기");
    expect(document.querySelector(".mk-state").textContent).not.toBe("");
    await act(async () => { release(); });
    await screen.findAllByText("9억 원");
    expect(document.querySelector(".mk-tiles").className).not.toContain("mk-dim");
    expect(screen.getByText("2026년 1분기 · 한식음식점")).toBeTruthy();
    expect(document.querySelector(".mk-cond-line").textContent).toContain("2026년 1분기");
  });

  it("역으로 등록한 가게는 업종을 바꾸면 역 위치와 함께 profile 을 보낸다", async () => {
    render(<Market />);
    await screen.findAllByText("12억 원");
    fireEvent.change(document.getElementById("mk-industry"), { target: { value: "I2" } });
    fireEvent.click(screen.getByRole("button", { name: "이 조건으로 보기" }));
    await waitFor(() => expect(calls.some((u) => u === "POST /api/market/profile")).toBe(true));
  });

  it("출처 한 줄은 scope 의 공개일 연도로", () => {
    expect(mapSource({ boundary_publication_date: "2023-10-23" })).toBe("네이버 지도 · 2023년 공개 상권 경계");
    expect(mapSource(null)).toBe("네이버 지도 · 공개 상권 경계");
  });
});

// ── 11/22 실사용 QA: 상권 화면 작게 고칠 것 (B1~B5) ────────────────────────
// 서버 문장은 상권 서비스(onboarding_sales.py · onboarding_population.py)가 주는 그대로
const W_SALES_TIME = "시간대 구간의 길이가 서로 다릅니다. 구간별 분기 누적 금액이며 시간당 매출 순위가 아닙니다.";
const W_POP_TIME = "시간대 구간 길이가 다릅니다. 시간당 유동인구나 일평균으로 환산한 값이 아닙니다.";
const W_POP_AGE = "연령대 숫자는 원천 분류입니다. 연령대 10을 10대 이하 등 확인되지 않은 범위로 바꾸지 않았습니다.";
const W_POP_TOP = "상권 전체의 원천 지표이며 선택 업종의 고객 수나 개별 가게의 방문자 수가 아닙니다.";
const SCOPE_NOTE = "홈·종합 리포트의 상권 저녁 매출은 공통 업종·17~24시 기준이라 이 숫자와 다를 수 있어요.";
const FACILITY_NOTE = "상권 이름에 든 역·학교가 상권 경계 안에 있다는 뜻은 아니에요. 시설 수는 서울시 집객시설 자료 그대로예요.";
const RAW_AGE_NOTE = "'원천 분류'는 서울시 자료의 연령 구분 이름 그대로라는 뜻이에요. 매출 탭의 '10대'와 범위가 같은지는 확인되지 않았어요.";
const QA_RESP = {
  ...MAP_RESP,
  sales: { total: { value: 1200000000 }, warnings: ["상권·업종의 분기 추정매출이며 개별 가게의 실제 매출이나 특정 월 매출이 아닙니다."],
    distributions: {
      time: { label: "시간대별 매출", items: [{ label: "00~06시", share_percent: 25 }, { label: "06~11시", share_percent: 75 }], warnings: [W_SALES_TIME] },
      age: { label: "연령별 매출", items: [{ label: "10대", share_percent: 10 }, { label: "20대", share_percent: 90 }], warnings: [] },
    } },
  population: { total: { value: 5000 }, warnings: [W_POP_TOP, W_POP_TIME],   // 위 문장 하나가 분포 경고와 같아도 두 번 나오지 않아야 함
    distributions: {
      time: { label: "시간대별 유동인구 원천 지표", items: [{ label: "00~06시", value: 2500 }, { label: "06~11시", value: 2500 }], warnings: [W_POP_TIME] },
      age: { label: "연령별 유동인구 원천 지표", items: [{ label: "연령대 10 (원천 분류)", value: 1000 }, { label: "연령대 20", value: 4000 }], warnings: [W_POP_AGE] },
    } },
  "area-context": { status: "available", warnings: [], values: [
    { label: "직장인구", value: 1200, unit: "명" }, { label: "지하철역 수", value: 0, unit: "개" }, { label: "초중고 수", value: 0, unit: "개" },
  ] },
};

describe("11/22 QA: 상권 화면 작게 고칠 것", () => {
  let resp;
  beforeEach(() => {
    resetNaverMapsForTest();
    delete window.naver;
    resp = JSON.parse(JSON.stringify(QA_RESP));
    global.fetch = vi.fn(async (url, opts = {}) => {
      const path = String(url).replace("/api/market/", "").split("?")[0];
      calls.push(`${opts.method || "GET"} ${String(url)}`);
      return { ok: true, status: 200, json: async () => resp[path] || {} };
    });
  });
  const tab = (name) => fireEvent.click(screen.getByRole("tab", { name }));
  const count = (text) => screen.queryAllByText(text).length;

  it("B1: 분포의 경고(시간대 구간 길이가 다름)는 그 막대 바로 아래에, 탭 아래 경고와 겹치면 한 번만", async () => {
    render(<Market />);
    await screen.findAllByText("12억 원");
    // 매출 탭: 시간대 막대 바로 다음에 그 분포의 경고, 연령 막대 아래에는 없음
    const salesTime = screen.getByRole("list", { name: "시간대별 매출" });
    expect(salesTime.nextElementSibling.textContent).toBe(W_SALES_TIME);
    expect(salesTime.nextElementSibling.className).toBe("small muted");
    expect(screen.getByRole("list", { name: "연령별 매출" }).nextElementSibling).toBeNull();
    expect(count(W_SALES_TIME)).toBe(1);
    // 유동 탭: 시간대·연령 막대 아래 각각의 경고, 위 문장과 같은 경고는 막대 아래 한 번만, 다른 위 문장은 탭 아래 그대로
    tab("유동·배후인구·집객시설");
    const popTime = screen.getByRole("list", { name: "시간대별 유동인구 원천 지표" });
    expect(popTime.nextElementSibling.textContent).toBe(W_POP_TIME);
    expect(count(W_POP_TIME)).toBe(1);
    expect(screen.getByRole("list", { name: "연령별 유동인구 원천 지표" }).nextElementSibling.textContent).toBe(W_POP_AGE);
    expect(count(W_POP_TOP)).toBe(1);
    expect(screen.getByText(W_POP_TOP).closest(".mk-grid")).toBeNull();   // 위 문장은 막대 칸 밖(탭 아래)
  });

  it("B2: 유동 탭의 '연령대 10'은 서버 표기 그대로 두고 '원천 분류' 뜻을 한 줄로, 매출 탭은 '10대' 그대로", async () => {
    render(<Market />);
    await screen.findAllByText("12억 원");
    expect(screen.getByText("10대").closest("[role=tabpanel]").id).toBe("mk-panel-sales");
    expect(screen.getByText(RAW_AGE_NOTE).closest("[role=tabpanel]").id).toBe("mk-panel-pop");   // 덧말은 유동 탭에만 (매출 탭에는 없음)
    tab("유동·배후인구·집객시설");
    const age = screen.getByRole("list", { name: "연령별 유동인구 원천 지표" });
    expect(age.querySelector(".mk-bar-l").textContent).toBe("연령대 10");
    expect(age.textContent).not.toMatch(/10대/);   // 범위를 확인하지 못한 표기를 '10대'로 바꾸지 않음
    const note = screen.getByText(RAW_AGE_NOTE);
    expect(note.className).toBe("small muted");
    expect(note.closest("section")).toBe(age.closest("section"));
    // 원천 분류 표기가 아니면(서버가 이름을 바꾸면) 덧말도 없음
    cleanup(); resetMarketForTest();
    resp.population.distributions.age.items[0].label = "연령대 10";
    render(<Market />);
    await screen.findAllByText("12억 원");
    tab("유동·배후인구·집객시설");
    expect(count(RAW_AGE_NOTE)).toBe(0);
  });

  it("B3: 변화율 타일 sub 에 '선택 업종 · 분기 전체', 지표 바로 아래 홈 지표와 범위가 다르다는 한 줄", async () => {
    render(<Market />);
    await screen.findAllByText("12억 원");
    expect(screen.getByText("2025년 2분기 대비 · 선택 업종 · 분기 전체 추정매출").className).toBe("tile-sub");
    const note = screen.getByText(SCOPE_NOTE);
    expect(note.className).toBe("small muted mk-tiles-note");
    expect(document.querySelector(".mk-tiles").nextElementSibling).toBe(note);
    expect(count(SCOPE_NOTE)).toBe(1);
  });

  it("B3: 자료를 받기 전에는 범위 한 줄도 없다", async () => {
    resp.status = { state: "off", message: "상권 서비스가 꺼져 있어요." };
    render(<Market />);
    await screen.findByText("상권 서비스가 꺼져 있어요.");
    expect(count(SCOPE_NOTE)).toBe(0);
  });

  it("B4: 집객시설 목록 바로 아래 '이름에 든 역·학교 ≠ 경계 안' 한 줄, 자료가 없으면 없음", async () => {
    render(<Market />);
    await screen.findAllByText("12억 원");
    tab("유동·배후인구·집객시설");
    const facts = screen.getByText("지하철역 수").closest("ul");
    expect(facts.nextElementSibling.textContent).toBe(FACILITY_NOTE);
    expect(facts.nextElementSibling.className).toBe("small muted");
    cleanup(); resetMarketForTest();
    resp["area-context"] = { status: "not_collected", values: [], warnings: [] };
    render(<Market />);
    await screen.findAllByText("12억 원");
    tab("유동·배후인구·집객시설");
    expect(screen.getByText("이 상권의 직장인구·상주인구·집객시설 자료가 아직 없어요.")).toBeTruthy();
    expect(count(FACILITY_NOTE)).toBe(0);
  });

  it("B5: 주변 상권을 누르면 비교 탭이 열리고 비교 칸(#mk-cmp-form)까지 부드럽게 내린다, 포커스는 탭", async () => {
    render(<Market />);
    await screen.findAllByText("12억 원");
    fireEvent.click(await screen.findByRole("button", { name: "노량진 · 420m" }));
    expect(screen.getByRole("tab", { name: "타 상권 1:1 비교" }).getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement.id).toBe("mk-tab-compare");
    await waitFor(() => expect(scrolled).toEqual([{ id: "mk-cmp-form", opts: { behavior: "smooth", block: "center" } }]));
    const form = document.getElementById("mk-cmp-form");
    expect(form.contains(document.getElementById("mk-cmp-district"))).toBe(true);
    expect(form.contains(screen.getByRole("button", { name: "비교하기" }))).toBe(true);
    await screen.findByText(/노량진 상권을 비교 대상으로 골랐어요/);
    // 비교 탭이 이미 열려 있어도 다시 누르면 또 내린다 (탭이 보이는 상태에서 '그대로'로 보였던 경우)
    fireEvent.click(screen.getByRole("button", { name: "장승배기 · 비교할 수 없음" }));
    await waitFor(() => expect(scrolled.length).toBe(2));
    expect(scrolled[1].id).toBe("mk-cmp-form");
  });

  it("B5: 움직임 줄이기를 켰으면 부드러운 스크롤 없이 바로", async () => {
    window.matchMedia = (q) => ({ matches: q === "(prefers-reduced-motion: reduce)", media: q, addEventListener() {}, removeEventListener() {} });
    render(<Market />);
    await screen.findAllByText("12억 원");
    fireEvent.click(await screen.findByRole("button", { name: "노량진 · 420m" }));
    await waitFor(() => expect(scrolled).toEqual([{ id: "mk-cmp-form", opts: { behavior: "auto", block: "center" } }]));
  });
});
