// 화면 전환: 주소 해시(#/today …). 예전 app.js 와 같은 주소를 그대로 쓴다 (docs/api/contract.md 2.5).
import { useSyncExternalStore } from "react";
import { getState, setState } from "../state/store.js";

export const ROUTES = ["today", "cards", "draft", "done", "analysis", "marketing", "report", "market"];

export function currentRoute() {
  const r = (window.location.hash.match(/^#\/(\w+)/) || [])[1];
  return ROUTES.includes(r) ? r : "today";
}

const listeners = new Set();
let tick = 0;   // 같은 화면으로 go() 해도 화면이 다시 그려지게 (예전 route() 다시 부르기)
function notify() { tick += 1; listeners.forEach((l) => l()); }
window.addEventListener("hashchange", notify);
function subscribe(l) { listeners.add(l); return () => listeners.delete(l); }
const snapshot = () => `${currentRoute()}#${tick}`;

// 지금 화면 이름. 같은 화면을 다시 열면 key 가 바뀐다 ({name, key})
export function useRoute() {
  const s = useSyncExternalStore(subscribe, snapshot);
  const [name, key] = s.split("#");
  return { name, key: Number(key) };
}

export function go(name) {
  if (currentRoute() === name) notify();
  else window.location.hash = "#/" + name;
}

// 서랍 버튼·AI 비서 칸에서 다른 화면의 탭·시작 모드까지 바로 (예전 navTo).
// sub: 리뷰 분석 탭(summary·issues·paste), 상권 분석 탭(sales·stores·pop·compare), 맞춤 마케팅 시작 모드(promo·leftover·ad·story·repeat)
// 각 화면은 store 의 nav 를 보고 자기 화면 요청이면 그 탭으로 간다 (nav.seq 가 바뀔 때마다 한 번).
export function navTo(name, sub) {
  if (!ROUTES.includes(name)) return;
  const prev = getState().nav;
  setState({ nav: { name, sub: sub || null, seq: (prev?.seq || 0) + 1 } });
  go(name);
}
