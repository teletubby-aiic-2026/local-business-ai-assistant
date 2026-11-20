// 네이버 지도 부품 (11/20, 6차 회의 ⑥). 상권 분석 화면의 상권 경계 지도, 새 가게 등록의 위치 지도가 같이 쓴다.
// 원래 구현은 상권 서비스 화면 services/market-analysis/app/static/onboarding/onboarding.js 의
// loadMapSDK(SDK 불러오기) · candidatePolygons(GeoJSON 검사) · analysisBounds(범위) · renderAnalysisMap(다각형·마커).
//
// 쓰는 법:
//   <NaverMap className center={{lat, lng}} zoom marker={{lat, lng, title}}
//             areas={[{id, name, geometry, kind: "selected"|"nearby", disabled, note}]}
//             onAreaClick={(id) => …} fit="areas"|"marker" label listLabel list>{범례 등}</NaverMap>
// - SDK 는 처음 필요할 때 한 번만 불러온다 (모듈 수준 Promise, loadNaverMaps). 공개 ID 는 이 서버의 /api/market/map-config.
// - 지도가 안 뜨면(키 없음 · 인증 실패 · 시간 초과 · 연결 실패) 그 자리에 안내 한 줄과 [다시 시도]만. 화면의 나머지는 그대로 쓴다.
// - 다각형은 키보드로 고를 수 없으니 onAreaClick 이 있으면 지도 아래에 같은 선택을 하는 버튼 목록을 둔다 (list={false} 면 뺌).
// - 서버가 준 글(상권 이름 등)은 JSX 와 SDK 의 title 칸으로만 넣는다 (HTML 글자로 만들지 않음).
import { useEffect, useRef, useState } from "react";
import { authHeaders, handleAuthError } from "../lib/api.js";
import { Button } from "./ui.jsx";
import "./NaverMap.css";

export const MAP_SDK_URL = "https://oapi.map.naver.com/openapi/v3/maps.js";
export const MAP_TIMEOUT_MS = 15000;
const MAP_CONFIG = "/api/market/map-config";
const SEOUL = { lat: 37.5665, lng: 126.978 };      // 그릴 것이 없을 때의 가운데 (서울시청)
const FIT_PADDING = 40;
const FAIL_KINDS = ["no_key", "auth", "timeout", "error"];

// 지도가 안 뜰 때 한 줄 (사장님 말로. 키 이름·콘솔 설정 같은 내부 사정은 쓰지 않는다)
export const MAP_FAIL_TEXT = {
  no_key: "지금은 지도를 볼 수 없어요.",
  auth: "지도를 불러오지 못했어요.",
  timeout: "지도를 여는 데 시간이 너무 걸려요.",
  error: "지도를 불러오지 못했어요.",
};
const LIST_HINT = "아래 목록에서 상권을 고를 수 있어요.";

class MapLoadError extends Error {
  constructor(kind) { super(MAP_FAIL_TEXT[kind] || MAP_FAIL_TEXT.error); this.kind = kind; }
}

// ── SDK 불러오기 (모듈에 하나) ───────────────────────────────────────────
const fresh = () => ({ promise: null, script: null, authFailed: false, force: false, listeners: new Set() });
let sdk = fresh();

function authFailure() {
  sdk.authFailed = true;
  sdk.reject?.(new MapLoadError("auth"));
  sdk.listeners.forEach((l) => l());
}

async function startLoad() {
  window.navermap_authFailure = authFailure;       // 네이버 SDK 가 인증에 실패하면 부르는 이름 (스크립트를 읽은 뒤에도 올 수 있음)
  if (window.naver?.maps && !sdk.force && !sdk.authFailed) return window.naver.maps;
  let config = null;
  try {
    // 로그인 표시 헤더를 붙이고, 401 login_needed 등은 다른 호출처럼 단계를 바꾼다 (lib/api.js)
    const res = await fetch(MAP_CONFIG, { headers: { Accept: "application/json", ...authHeaders() } });
    config = await res.json().catch(() => null);
    if (!res.ok) { handleAuthError({ status: res.status, state: config && config.error && config.error.state }); config = null; }
  } catch { config = null; }
  if (!config) throw new MapLoadError("error");
  const id = typeof config.client_id === "string" ? config.client_id.trim() : "";
  if (config.configured !== true || !id) throw new MapLoadError("no_key");
  return new Promise((resolve, reject) => {
    let done = false;
    const finish = (err) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      sdk.reject = null;
      if (err) reject(err); else resolve(window.naver.maps);
    };
    const timer = setTimeout(() => finish(new MapLoadError("timeout")), MAP_TIMEOUT_MS);
    sdk.reject = finish;
    const script = document.createElement("script");
    script.async = true;
    script.src = `${MAP_SDK_URL}?ncpKeyId=${encodeURIComponent(id)}`;
    script.onload = () => finish(sdk.authFailed ? new MapLoadError("auth") : window.naver?.maps ? null : new MapLoadError("error"));
    script.onerror = () => finish(new MapLoadError("error"));
    sdk.script = script;
    sdk.force = false;
    document.head.append(script);
  });
}

// 네이버 지도 SDK 를 한 번만 불러온다. 성공하면 naver.maps, 실패하면 kind(no_key·auth·timeout·error)가 있는 Error
export function loadNaverMaps() {
  if (!sdk.promise) {
    sdk.promise = startLoad();
    sdk.promise.catch(() => {});   // 받는 쪽이 없어도 '처리 안 된 거부'가 되지 않게
  }
  return sdk.promise;
}

// [다시 시도]: 받은 결과를 버리고 다음 loadNaverMaps 가 스크립트부터 다시 붙이게
export function retryNaverMaps() {
  const listeners = sdk.listeners;
  sdk.script?.remove();
  sdk = { ...fresh(), listeners, force: true };
}

// 인증 실패를 듣는다 (지도를 그린 뒤에 오기도 함). 돌려준 함수로 그만 듣기
export function onNaverAuthFailure(listener) {
  sdk.listeners.add(listener);
  return () => sdk.listeners.delete(listener);
}

// 시험에서만 쓴다
export function resetNaverMapsForTest() {
  sdk.script?.remove();
  sdk = fresh();
  delete window.navermap_authFailure;
}

// ── 좌표 도우미 (SDK 없이 돈다) ──────────────────────────────────────────
const okPos = (p) => Array.isArray(p) && p.length >= 2 && typeof p[0] === "number" && typeof p[1] === "number"
  && Number.isFinite(p[0]) && Number.isFinite(p[1]) && Math.abs(p[0]) <= 180 && Math.abs(p[1]) <= 90;
const okRing = (r) => Array.isArray(r) && r.length >= 4 && r.every(okPos);

// GeoJSON Polygon·MultiPolygon([경도, 위도]) → 다각형마다 고리마다 [{lat, lng}] (순서를 위도·경도로 뒤집음).
// 좌표가 하나라도 틀린 다각형은 뺀다 (onboarding.js candidatePolygons 와 같은 규칙)
export function geometryPaths(geometry) {
  const polys = geometry?.type === "Polygon" ? [geometry.coordinates] : geometry?.type === "MultiPolygon" ? geometry.coordinates : [];
  if (!Array.isArray(polys)) return [];
  return polys.filter((poly) => Array.isArray(poly) && poly.length && poly.every(okRing))
    .map((poly) => poly.map((ring) => ring.map(([lng, lat]) => ({ lat, lng }))));
}

// 위치 칸(프로필의 location) → {lat, lng} 또는 null. 동네면 reference_point (onboarding.js mapPoint 와 같은 규칙)
export function locationPoint(location) {
  if (!location || typeof location !== "object") return null;
  const ref = location.reference_point || location;
  const raw = [ref.latitude, ref.longitude];
  if (raw.some((v) => v == null || typeof v === "boolean" || (typeof v === "string" && !v.trim()))) return null;
  const [lat, lng] = raw.map(Number);
  if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) return null;
  return { lat, lng };
}

const okPoint = (p) => !!p && Number.isFinite(p.lat) && Number.isFinite(p.lng) && Math.abs(p.lat) <= 90 && Math.abs(p.lng) <= 180;

// 상권들(+ 점)의 화면 범위 {south, west, north, east}. 그릴 것이 없으면 null
export function areasBounds(areas, point) {
  let south = 90, west = 180, north = -90, east = -180, any = false;
  const add = ({ lat, lng }) => {
    any = true;
    south = Math.min(south, lat); north = Math.max(north, lat);
    west = Math.min(west, lng); east = Math.max(east, lng);
  };
  for (const a of areas || []) for (const poly of geometryPaths(a && a.geometry)) for (const ring of poly) ring.forEach(add);
  if (okPoint(point)) add(point);
  return any ? { south, west, north, east } : null;
}

// ── 색 (styles/tokens.css 의 값을 그때그때 읽는다. 지도 타일은 밝은 색 그대로) ──────
function tokens() {
  const cs = getComputedStyle(document.documentElement);
  const v = (name) => cs.getPropertyValue(name).trim() || undefined;
  return { line: v("--accent"), fill: v("--brand"), near: v("--muted") };
}

function polygonStyle(area, c, hover = false) {
  if (area.kind === "selected") {
    return { strokeColor: c.line, strokeOpacity: 1, strokeWeight: hover ? 4 : 3, strokeStyle: "solid",
      fillColor: c.fill, fillOpacity: hover ? 0.26 : 0.18, zIndex: 3 };
  }
  return { strokeColor: c.near, strokeOpacity: area.disabled ? 0.45 : 0.9, strokeWeight: hover ? 3 : 2,
    strokeStyle: area.disabled ? "shortdot" : "shortdash", fillColor: c.near, fillOpacity: hover ? 0.12 : 0.05, zIndex: hover ? 2 : 1 };
}

// 다시 그릴지 가르는 글자 (부르는 쪽이 매번 새 배열을 넘겨도 내용이 같으면 그대로 둔다 → 사장님이 옮긴 지도를 되돌리지 않음)
function drawKey(areas, marker, center, zoom, fit) {
  const geo = (g) => {
    const first = geometryPaths(g)[0];
    return first ? `${geometryPaths(g).length}:${first[0].length}:${first[0][0].lat},${first[0][0].lng}` : "";
  };
  return JSON.stringify([(areas || []).map((a) => [a.id, a.kind, !!a.disabled, a.name, geo(a.geometry)]),
    okPoint(marker) ? [marker.lat, marker.lng, marker.title || ""] : null, okPoint(center) ? [center.lat, center.lng] : null, zoom, fit]);
}

// ── 부품 ───────────────────────────────────────────────────────────────
export default function NaverMap({
  className = "", center, zoom = 16, marker, areas = [], onAreaClick, fit = "areas",
  label = "지도", listLabel = "지도의 상권 목록", list, children,
}) {
  const box = useRef(null);
  const mapRef = useRef(null);
  const mapsRef = useRef(null);
  const clickRef = useRef(onAreaClick);
  clickRef.current = onAreaClick;
  const [status, setStatus] = useState("loading");     // loading · ready · no_key · auth · timeout · error
  const [attempt, setAttempt] = useState(0);
  const [hover, setHover] = useState("");
  const showList = (list ?? !!onAreaClick) && areas.length > 0;
  const key = drawKey(areas, marker, center, zoom, fit);
  const drawn = useRef({ areas, marker, center, zoom, fit });
  drawn.current = { areas, marker, center, zoom, fit };

  // ① SDK 를 불러 지도를 만든다 (다시 시도할 때마다 새로)
  useEffect(() => {
    let alive = true;
    const el = box.current;
    setStatus("loading");
    const off = onNaverAuthFailure(() => { if (alive) setStatus("auth"); });
    loadNaverMaps().then((maps) => {
      if (!alive) return;
      if (sdk.authFailed) { setStatus("auth"); return; }
      try {
        const { marker: mk, center: ct, zoom: zm } = drawn.current;
        const start = okPoint(mk) ? mk : okPoint(ct) ? ct : SEOUL;
        const opts = { center: new maps.LatLng(start.lat, start.lng), zoom: zm, zoomControl: true, mapTypeControl: false, scaleControl: true };
        if (maps.Position && maps.Position.TOP_RIGHT != null) opts.zoomControlOptions = { position: maps.Position.TOP_RIGHT };
        mapRef.current = new maps.Map(el, opts);
        mapsRef.current = maps;
        setStatus("ready");
      } catch { setStatus("error"); }
    }, (e) => { if (alive) setStatus(FAIL_KINDS.includes(e && e.kind) ? e.kind : "error"); });
    return () => {
      alive = false;
      off();
      const map = mapRef.current;
      mapRef.current = null;
      try { map?.destroy?.(); } catch { /* 반쯤 만든 지도는 정리 중에도 오류를 낼 수 있다 */ }
      try { el?.replaceChildren(); } catch { /* 위와 같음 */ }
    };
  }, [attempt]);

  // ② 다각형·마커를 그리고 범위를 맞춘다. 바뀌거나 언마운트되면 지운다
  useEffect(() => {
    const maps = mapsRef.current, map = mapRef.current;
    if (status !== "ready" || !maps || !map) return undefined;
    const { areas: list2, marker: mk, center: ct, zoom: zm, fit: how } = drawn.current;
    const made = [], heard = [];
    const c = tokens();
    try {
      for (const area of list2) {
        for (const poly of geometryPaths(area.geometry)) {
          const polygon = new maps.Polygon({ map, clickable: true, paths: poly.map((ring) => ring.map((p) => new maps.LatLng(p.lat, p.lng))),
            ...polygonStyle(area, c) });
          made.push(polygon);
          heard.push(maps.Event.addListener(polygon, "click", () => clickRef.current?.(area.id)));
          heard.push(maps.Event.addListener(polygon, "mouseover", () => {
            setHover(area.name || "");
            try { polygon.setOptions(polygonStyle(area, c, true)); } catch { /* 모양만 */ }
          }));
          heard.push(maps.Event.addListener(polygon, "mouseout", () => {
            setHover("");
            try { polygon.setOptions(polygonStyle(area, c)); } catch { /* 모양만 */ }
          }));
        }
      }
      if (okPoint(mk)) {
        const opts = { map, position: new maps.LatLng(mk.lat, mk.lng), title: mk.title || "", zIndex: 10,
          icon: { content: '<span class="nmap-pin"></span>' } };
        if (maps.Point) opts.icon.anchor = new maps.Point(9, 9);
        made.push(new maps.Marker(opts));
      }
      const b = how === "areas" ? areasBounds(list2, mk) : null;
      if (b && (b.north > b.south || b.east > b.west)) {
        map.fitBounds(new maps.LatLngBounds(new maps.LatLng(b.south, b.west), new maps.LatLng(b.north, b.east)), FIT_PADDING);
      } else {
        const p = okPoint(mk) ? mk : b ? { lat: b.south, lng: b.west } : okPoint(ct) ? ct : null;
        if (p) { map.setCenter(new maps.LatLng(p.lat, p.lng)); map.setZoom(zm); }
      }
    } catch {
      setStatus("error");
    }
    return () => {
      try { if (heard.length) maps.Event.removeListener(heard); } catch { /* 정리 실패가 화면을 막지 않게 */ }
      for (const o of made) { try { o.setMap(null); } catch { /* 위와 같음 */ } }
      setHover("");
    };
  }, [status, key]);

  const failed = FAIL_KINDS.includes(status);
  const retry = () => { retryNaverMaps(); setAttempt((n) => n + 1); };
  return (
    <div className={["nmap", className].filter(Boolean).join(" ")}>
      <div className="nmap-box" role="region" aria-label={label} hidden={failed} aria-busy={status === "loading" || undefined}>
        <div ref={box} className="nmap-canvas" />
        {status === "loading" && <p className="nmap-wait small">지도를 불러오는 중…</p>}
        {hover && <p className="nmap-hover" aria-hidden="true">{hover}</p>}
      </div>
      {failed && (
        <div className="nmap-fail" role="status">
          <span>{MAP_FAIL_TEXT[status]}{showList ? ` ${LIST_HINT}` : ""}</span>
          <Button size="small" onClick={retry}>다시 시도</Button>
        </div>
      )}
      {children}
      {showList && (
        <ul className="plain nmap-list" aria-label={listLabel}>
          {areas.map((a) => (
            <li key={a.id}>
              {a.kind === "selected"
                ? <span className="nmap-area selected" aria-current="true">{a.name}{a.note && <span className="nmap-note"> · {a.note}</span>}</span>
                : (
                  <button type="button" className={["nmap-area", "nearby", a.disabled && "off"].filter(Boolean).join(" ")}
                    aria-disabled={a.disabled || undefined} onClick={() => clickRef.current?.(a.id)}>
                    {a.name}{a.note && <span className="nmap-note"> · {a.note}</span>}
                  </button>
                )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
