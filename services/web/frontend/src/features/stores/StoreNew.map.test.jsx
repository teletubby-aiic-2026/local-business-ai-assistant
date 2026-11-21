// 새 가게 등록의 지도 연결 (지도 부품은 가짜): 목록은 화면의 라디오가 맡으므로 list={false}, 마커 = 가게 위치, 상권 = 후보(고른 것 selected · 나머지 nearby,
// 고를 수 없는 상권 disabled), 다각형을 누르면 그 상권을 고르고 고를 수 없는 상권이면 이유 한 줄. 지도 부품 자체는 components/NaverMap.test.jsx
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { resetStore, setState } from "../../state/store.js";
import { resetStoreApiForTest } from "./storeApi.js";
import StoreNew from "./StoreNew.jsx";

const seen = [];
vi.mock("../../components/NaverMap.jsx", async (orig) => ({
  ...(await orig()),
  default: (props) => {
    seen.push(props);
    return (
      <div data-testid="map">
        {props.areas.map((a) => <button key={a.id} type="button" data-area={a.id} onClick={() => props.onAreaClick(a.id)}>{`지도 ${a.name}`}</button>)}
      </div>
    );
  },
}));

const POLY = { type: "Polygon", coordinates: [[[126.93, 37.50], [126.94, 37.50], [126.94, 37.51], [126.93, 37.50]]] };
const per = [{ code: "20262", label: "2026년 2분기", available: true, industry_data_available: true }];
const CANDS = [
  { area_code: "3120154", name: "장승배기역", type: "발달상권", relation: "inside", distance_m: 0, geometry: POLY, availability: { periods: per } },
  { area_code: "3110826", name: "장승배기역 4번", type: "골목상권", relation: "nearby", distance_m: 140, geometry: POLY, availability: { periods: per } },
  { area_code: "3110999", name: "이름이 다른 상권", type: "골목상권", relation: "nearby", distance_m: 300, geometry: POLY, availability: { periods: per },
    selection_blocked_reason: "경계와 상권 명칭의 연결 확인이 필요합니다." },
];
const STATION = { id: "kric-jsb", name: "장승배기역", lines: ["7호선"], district_name: "동작구", road_address: "서울특별시 동작구 상도로 지하188",
  latitude: 37.504845, longitude: 126.939025, selectable_line_codes: ["line-7"] };
const OPTIONS = { industries: [{ code: "CS100001", name: "한식음식점" }], business_statuses: [{ code: "operating", label: "운영 중" }],
  station_lines: [{ code: "line-7", name: "7호선" }], stations: [STATION] };
const PROF = { location: { kind: "station", station_id: STATION.id, name: STATION.name, label: STATION.name, latitude: STATION.latitude, longitude: STATION.longitude, district_name: "동작구" } };

beforeEach(() => {
  resetStore();
  resetStoreApiForTest();
  seen.length = 0;
  window.scrollTo = () => {};
  setState({ stage: "store-new", storeNew: { mode: "add" }, me: { authenticated: true, user: { display_name: "김시험" }, stores: [] } });
  const routes = {
    "GET /api/market/options": OPTIONS, "GET /api/market/profile": { revision: 0, profile: null },
    "POST /api/market/profile": { revision: 1, profile: PROF }, "GET /api/market/analysis-options": { candidates: CANDS, scope: {}, profile: PROF },
  };
  globalThis.fetch = vi.fn(async (path, opt = {}) => {
    const out = routes[`${(opt.method || "GET").toUpperCase()} ${path}`] ?? {};
    return { ok: true, status: 200, json: async () => out, headers: { get: () => "application/json" } };
  });
});
afterEach(() => cleanup());

const $ = (id) => document.getElementById(id);
const last = () => seen[seen.length - 1];
const checked = () => [...document.querySelectorAll('input[name="area_code"]')].filter((x) => x.checked).map((x) => x.value);

describe("새 가게 등록의 지도", () => {
  it("위치를 고르기 전에는 지도가 없고, 고르면 가게 위치 마커 → 후보가 오면 상권 경계(고른 것 selected), 목록은 라디오가 맡음", async () => {
    render(<StoreNew mode="add" />);
    await waitFor(() => expect($("sn-industry")).toBeTruthy());
    expect(screen.queryByTestId("map")).toBeNull();
    expect(screen.getByText("주소를 찾거나 역을 고르면 그 위치의 상권이 보여요.")).toBeTruthy();
    fireEvent.change($("sn-industry"), { target: { value: "CS100001" } });
    fireEvent.click(screen.getByRole("radio", { name: "가까운 역으로" }));
    fireEvent.change($("sn-line"), { target: { value: "line-7" } });
    fireEvent.change($("sn-station"), { target: { value: STATION.id } });
    expect(screen.getByTestId("map")).toBeTruthy();
    expect(last().marker).toMatchObject({ lat: STATION.latitude, lng: STATION.longitude, title: "장승배기역" });
    await waitFor(() => expect(last().areas).toHaveLength(3));
    expect(last().list).toBe(false);
    expect(last().fit).toBe("areas");
    expect(last().areas.map((a) => [a.id, a.kind, a.disabled])).toEqual([["3120154", "selected", false], ["3110826", "nearby", false], ["3110999", "nearby", true]]);
    expect(last().areas[0].geometry).toEqual(POLY);
    // 다각형을 누르면 그 상권을 고름 (라디오와 같음)
    fireEvent.click(screen.getByRole("button", { name: "지도 장승배기역 4번" }));
    expect(checked()).toEqual(["3110826"]);
    expect(last().areas.map((a) => a.kind)).toEqual(["nearby", "selected", "nearby"]);
    // 고를 수 없는 상권을 누르면 선택은 그대로, 이유 한 줄 (상권 칸에 연결)
    fireEvent.click(screen.getByRole("button", { name: "지도 이름이 다른 상권" }));
    expect(checked()).toEqual(["3110826"]);
    expect($("sn-area-note").textContent).toBe("이름이 다른 상권: 경계와 상권 명칭의 연결 확인이 필요합니다.");
    expect($("sn-area-box").getAttribute("aria-describedby")).toContain("sn-area-note");
  });
});
