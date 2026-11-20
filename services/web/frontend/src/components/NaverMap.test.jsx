// 네이버 지도 부품: 가짜 window.naver.maps 로 SDK 불러오기 한 번 · 다각형 수와 좌표 순서 · 누르기 · 실패 안내와 다시 시도 · 정리
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import NaverMap, {
  MAP_TIMEOUT_MS, areasBounds, geometryPaths, loadNaverMaps, locationPoint, resetNaverMapsForTest,
} from "./NaverMap.jsx";

// 가짜 SDK: 만든 지도·다각형·마커·리스너를 모아 둔다
function fakeSdk() {
  const made = { maps: [], polygons: [], markers: [], listeners: [] };
  class LatLng { constructor(lat, lng) { this.lat = lat; this.lng = lng; } }
  class LatLngBounds { constructor(sw, ne) { this.sw = sw; this.ne = ne; } }
  class Point { constructor(x, y) { this.x = x; this.y = y; } }
  class Map {
    constructor(el, opts) { this.el = el; this.opts = opts; this.destroyed = false; made.maps.push(this); }
    fitBounds(b, pad) { this.fitted = b; this.pad = pad; }
    setCenter(c) { this.center = c; }
    setZoom(z) { this.zoom = z; }
    destroy() { this.destroyed = true; }
  }
  class Polygon {
    constructor(opts) { this.opts = { ...opts }; this.map = opts.map; made.polygons.push(this); }
    setMap(m) { this.map = m; }
    setOptions(o) { Object.assign(this.opts, o); }
  }
  class Marker {
    constructor(opts) { this.opts = opts; this.map = opts.map; made.markers.push(this); }
    setMap(m) { this.map = m; }
  }
  const Event = {
    addListener(target, name, fn) { const h = { target, name, fn }; made.listeners.push(h); return h; },
    removeListener(hs) { for (const h of [].concat(hs)) { const i = made.listeners.indexOf(h); if (i >= 0) made.listeners.splice(i, 1); } },
  };
  const fire = (target, name) => act(() => { made.listeners.filter((h) => h.target === target && h.name === name).forEach((h) => h.fn()); });
  return { maps: { LatLng, LatLngBounds, Point, Map, Polygon, Marker, Event, Position: { TOP_RIGHT: 3 } }, made, fire };
}

// 사각형 고리 하나 ([경도, 위도], 닫힘)
const ring = (lng, lat, d = 0.002) => [[lng, lat], [lng + d, lat], [lng + d, lat + d], [lng, lat + d], [lng, lat]];
const AREAS = [
  { id: "A1", name: "장승배기역 4번", kind: "selected", geometry: { type: "Polygon", coordinates: [ring(126.939, 37.504)] } },
  { id: "A2", name: "노량진역", kind: "nearby", geometry: { type: "MultiPolygon", coordinates: [[ring(126.942, 37.513)], [ring(126.95, 37.51, 0.001)]] } },
  { id: "A3", name: "깨진 경계", kind: "nearby", disabled: true, geometry: { type: "Polygon", coordinates: [[[126.9, 37.5], [200, 37.5]]] } },
];
const MARKER = { lat: 37.5049, lng: 126.9398, title: "가게 위치" };

let config, sdk;
const scriptEl = () => document.querySelector('script[src^="https://oapi.map.naver.com/openapi/v3/maps.js"]');
// 스크립트를 다 읽은 것처럼: window.naver 를 채우고 onload
async function loadScript() {
  await waitFor(() => expect(scriptEl()).toBeTruthy());
  window.naver = { maps: sdk.maps };
  await act(async () => { scriptEl().onload(); });
}

beforeEach(() => {
  resetNaverMapsForTest();
  delete window.naver;
  document.head.querySelectorAll("script").forEach((s) => s.remove());
  sdk = fakeSdk();
  config = { client_id: "abc_123", configured: true };
  global.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => config }));
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("SDK 불러오기", () => {
  it("여러 지도가 떠도 map-config 와 스크립트는 한 번만, 공개 ID 는 주소에 그대로", async () => {
    render(<><NaverMap marker={MARKER} /><NaverMap marker={MARKER} /></>);
    await loadScript();
    await waitFor(() => expect(sdk.made.maps.length).toBe(2));
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch.mock.calls[0][0]).toBe("/api/market/map-config");
    expect(document.querySelectorAll('script[src*="oapi.map.naver.com"]').length).toBe(1);
    expect(scriptEl().src).toBe("https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId=abc_123");
    expect(await loadNaverMaps()).toBe(sdk.maps);
    cleanup();
    render(<NaverMap marker={MARKER} />);   // 다시 열어도 부르지 않음
    await waitFor(() => expect(sdk.made.maps.length).toBe(3));
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it("키가 없으면(configured:false) 안내 한 줄과 다시 시도, 스크립트는 붙이지 않음", async () => {
    config = { client_id: "", configured: false };
    render(<NaverMap areas={AREAS} onAreaClick={() => {}} />);
    const line = await screen.findByText("지금은 지도를 볼 수 없어요. 아래 목록에서 상권을 고를 수 있어요.");
    expect(line.closest("[role=status]")).toBeTruthy();
    expect(scriptEl()).toBeNull();
    expect(document.querySelector(".nmap-box").hidden).toBe(true);
    expect(document.body.textContent).not.toMatch(/ncpKeyId|client_id|NAVER|키|콘솔/);   // 내부 사정은 화면에 없음
    config = { client_id: "abc_123", configured: true };
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    await loadScript();
    await waitFor(() => expect(sdk.made.maps.length).toBe(1));
    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("button", { name: "다시 시도" })).toBeNull();
    expect(document.querySelector(".nmap-box").hidden).toBe(false);
  });

  it("목록이 없으면 안내에 '아래 목록' 말이 없다", async () => {
    config = { configured: false };
    render(<NaverMap marker={MARKER} />);
    expect(await screen.findByText("지금은 지도를 볼 수 없어요.")).toBeTruthy();
  });

  it("인증 실패(navermap_authFailure)면 안내, 다시 시도하면 스크립트부터 새로", async () => {
    render(<NaverMap areas={AREAS} onAreaClick={() => {}} />);
    await waitFor(() => expect(scriptEl()).toBeTruthy());
    const first = scriptEl();
    act(() => { window.navermap_authFailure(); });
    expect(await screen.findByText("지도를 불러오지 못했어요. 아래 목록에서 상권을 고를 수 있어요.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    await waitFor(() => expect(scriptEl()).not.toBe(first));
    expect(first.isConnected).toBe(false);
    await loadScript();
    await waitFor(() => expect(sdk.made.polygons.length).toBe(3));
  });

  it("지도를 그린 뒤에 인증 실패가 와도 안내로 바꾸고 다각형을 지운다", async () => {
    render(<NaverMap areas={AREAS} marker={MARKER} onAreaClick={() => {}} />);
    await loadScript();
    await waitFor(() => expect(sdk.made.polygons.length).toBe(3));
    act(() => { window.navermap_authFailure(); });
    expect(await screen.findByText(/지도를 불러오지 못했어요/)).toBeTruthy();
    expect(sdk.made.polygons.every((p) => p.map === null)).toBe(true);
    expect(sdk.made.markers.every((p) => p.map === null)).toBe(true);
  });

  it("15초 안에 스크립트가 안 오면 시간 초과 안내", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    render(<NaverMap areas={AREAS} onAreaClick={() => {}} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(scriptEl()).toBeTruthy();
    expect(screen.getByText("지도를 불러오는 중…")).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(MAP_TIMEOUT_MS); });
    expect(screen.getByText("지도를 여는 데 시간이 너무 걸려요. 아래 목록에서 상권을 고를 수 있어요.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "다시 시도" })).toBeTruthy();
  });

  it("map-config 를 못 받으면(상권 서비스 꺼짐) 연결 실패 안내", async () => {
    global.fetch = vi.fn(async () => ({ ok: false, status: 503, json: async () => ({ error: { message: "x" } }) }));
    render(<NaverMap marker={MARKER} />);
    expect(await screen.findByText("지도를 불러오지 못했어요.")).toBeTruthy();
  });
});

describe("다각형·마커", () => {
  it("다각형 수와 좌표 순서(위도, 경도), 모양, 마커, 범위 맞추기", async () => {
    document.documentElement.style.setProperty("--accent", "#00843d");
    document.documentElement.style.setProperty("--muted", "#5a5e66");
    render(<NaverMap areas={AREAS} marker={MARKER} onAreaClick={() => {}} />);
    await loadScript();
    await waitFor(() => expect(sdk.made.polygons.length).toBe(3));   // A1 하나 + A2 둘, 깨진 A3 은 뺌
    const [a1, a2a] = sdk.made.polygons;
    expect(a1.opts.paths[0][0]).toEqual(new sdk.maps.LatLng(37.504, 126.939));
    expect(a1.opts.paths[0].length).toBe(5);
    expect(a1.opts.strokeStyle).toBe("solid");
    expect(a2a.opts.strokeStyle).toBe("shortdash");
    expect(a1.opts.zIndex).toBeGreaterThan(a2a.opts.zIndex);
    const style = getComputedStyle(document.documentElement);
    if (style.getPropertyValue("--accent").trim()) {   // jsdom 이 사용자 속성을 읽어 줄 때만
      expect(a1.opts.strokeColor).toBe("#00843d");
      expect(a2a.opts.strokeColor).toBe("#5a5e66");
    }
    expect(sdk.made.markers.length).toBe(1);
    expect(sdk.made.markers[0].opts.title).toBe("가게 위치");
    expect(sdk.made.markers[0].opts.position).toEqual(new sdk.maps.LatLng(37.5049, 126.9398));
    const map = sdk.made.maps[0];
    expect(map.el.className).toBe("nmap-canvas");
    const near = (got, lat, lng) => { expect(got.lat).toBeCloseTo(lat, 9); expect(got.lng).toBeCloseTo(lng, 9); };
    // 고른 상권(A1)이 있으면 그 상권과 가게 위치에 맞춘다 (후보 전체가 아님: 원래 화면과 같은 규칙)
    near(map.fitted.sw, 37.504, 126.939);
    near(map.fitted.ne, 37.506, 126.941);
    expect(map.pad).toBe(40);
    document.documentElement.style.removeProperty("--accent");
    document.documentElement.style.removeProperty("--muted");
  });

  it("고른 상권이 없으면 후보 전체에 맞춘다", async () => {
    render(<NaverMap areas={AREAS.map((a) => ({ ...a, kind: "nearby" }))} marker={MARKER} onAreaClick={() => {}} />);
    await loadScript();
    await waitFor(() => expect(sdk.made.maps.length).toBe(1));
    const map = sdk.made.maps[0];
    expect(map.fitted.sw.lat).toBeCloseTo(37.504, 9);
    expect(map.fitted.sw.lng).toBeCloseTo(126.939, 9);
    expect(map.fitted.ne.lat).toBeCloseTo(37.515, 9);
    expect(map.fitted.ne.lng).toBeCloseTo(126.951, 9);
  });

  it("다각형을 누르면 onAreaClick(id), 올리면 상권 이름", async () => {
    const onAreaClick = vi.fn();
    render(<NaverMap areas={AREAS} onAreaClick={onAreaClick} />);
    await loadScript();
    await waitFor(() => expect(sdk.made.polygons.length).toBe(3));
    sdk.fire(sdk.made.polygons[2], "click");
    expect(onAreaClick).toHaveBeenCalledWith("A2");
    sdk.fire(sdk.made.polygons[1], "mouseover");
    expect(document.querySelector(".nmap-hover").textContent).toBe("노량진역");
    expect(sdk.made.polygons[1].opts.strokeWeight).toBe(3);
    sdk.fire(sdk.made.polygons[1], "mouseout");
    expect(document.querySelector(".nmap-hover")).toBeNull();
  });

  it("지도 아래 목록: 주변 상권은 버튼(같은 onAreaClick), 고른 상권은 표시만", async () => {
    const onAreaClick = vi.fn();
    config = { configured: false };
    render(<NaverMap areas={AREAS} onAreaClick={onAreaClick} listLabel="주변 상권" />);
    const list = screen.getByRole("list", { name: "주변 상권" });
    expect(list.querySelector("[aria-current=true]").textContent).toBe("장승배기역 4번");
    fireEvent.click(screen.getByRole("button", { name: "노량진역" }));
    expect(onAreaClick).toHaveBeenCalledWith("A2");
    const off = screen.getByRole("button", { name: "깨진 경계" });
    expect(off.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(off);
    expect(onAreaClick).toHaveBeenCalledWith("A3");   // 고를 수 없는 이유는 부르는 화면이 알림
    expect(screen.queryByRole("button", { name: "장승배기역 4번" })).toBeNull();
  });

  it("list={false} 면 목록을 그리지 않는다", () => {
    render(<NaverMap areas={AREAS} onAreaClick={() => {}} list={false} />);
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("props 가 바뀌면 지우고 다시, 내용이 같은 새 배열이면 그대로, 언마운트하면 모두 정리", async () => {
    const { rerender, unmount } = render(<NaverMap areas={AREAS} marker={MARKER} onAreaClick={() => {}} />);
    await loadScript();
    await waitFor(() => expect(sdk.made.polygons.length).toBe(3));
    rerender(<NaverMap areas={AREAS.map((a) => ({ ...a }))} marker={{ ...MARKER }} onAreaClick={() => {}} />);
    expect(sdk.made.polygons.length).toBe(3);
    rerender(<NaverMap areas={[{ ...AREAS[1], kind: "selected" }]} marker={MARKER} onAreaClick={() => {}} />);
    await waitFor(() => expect(sdk.made.polygons.length).toBe(5));
    expect(sdk.made.polygons.slice(0, 3).every((p) => p.map === null)).toBe(true);
    expect(sdk.made.polygons.slice(3).every((p) => p.map === sdk.made.maps[0])).toBe(true);
    expect(sdk.made.polygons[3].opts.strokeStyle).toBe("solid");
    unmount();
    expect(sdk.made.polygons.every((p) => p.map === null)).toBe(true);
    expect(sdk.made.markers.every((p) => p.map === null)).toBe(true);
    expect(sdk.made.listeners.length).toBe(0);
    expect(sdk.made.maps[0].destroyed).toBe(true);
  });

  it("fit='marker' 면 범위를 맞추지 않고 마커로 가운데·확대", async () => {
    render(<NaverMap areas={AREAS} marker={MARKER} fit="marker" zoom={17} />);
    await loadScript();
    await waitFor(() => expect(sdk.made.maps[0] && sdk.made.maps[0].zoom).toBe(17));
    expect(sdk.made.maps[0].fitted).toBeUndefined();
    expect(sdk.made.maps[0].center).toEqual(new sdk.maps.LatLng(37.5049, 126.9398));
  });
});

describe("좌표 도우미", () => {
  it("geometryPaths: [경도, 위도] → {lat, lng}, 틀린 다각형은 뺌", () => {
    expect(geometryPaths(AREAS[0].geometry)[0][0][0]).toEqual({ lat: 37.504, lng: 126.939 });
    expect(geometryPaths(AREAS[1].geometry).length).toBe(2);
    expect(geometryPaths(AREAS[2].geometry)).toEqual([]);
    expect(geometryPaths(null)).toEqual([]);
    expect(geometryPaths({ type: "Point", coordinates: [126.9, 37.5] })).toEqual([]);
  });

  it("areasBounds: 상권들과 점을 모두 담는 범위, 그릴 것이 없으면 null", () => {
    const b = areasBounds(AREAS.slice(0, 1), { lat: 37.5, lng: 126.93 });
    [["south", 37.5], ["west", 126.93], ["north", 37.506], ["east", 126.941]].forEach(([k, v]) => expect(b[k]).toBeCloseTo(v, 9));
    expect(areasBounds([], null)).toBeNull();
    expect(areasBounds([AREAS[2]], { lat: NaN, lng: 1 })).toBeNull();
  });

  it("locationPoint: 동네는 reference_point, 글자 좌표도 읽고 빈 값·범위 밖은 null", () => {
    expect(locationPoint({ kind: "station", latitude: 37.5, longitude: 126.9 })).toEqual({ lat: 37.5, lng: 126.9 });
    expect(locationPoint({ kind: "area", reference_point: { latitude: "37.51", longitude: "126.95" } })).toEqual({ lat: 37.51, lng: 126.95 });
    expect(locationPoint({ kind: "station", latitude: null, longitude: 126.9 })).toBeNull();
    expect(locationPoint({ latitude: "", longitude: 126.9 })).toBeNull();
    expect(locationPoint({ latitude: 99, longitude: 126.9 })).toBeNull();
    expect(locationPoint(null)).toBeNull();
  });
});
