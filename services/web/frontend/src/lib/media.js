// 창 폭 구간 (docs/api/contract.md 2.9 와 같은 기준). CSS(layout.css)의 @media 와 숫자를 맞춘다
// narrow: 760px 이하 (가로 메뉴·아래 시트) · mid: 761~1024px (메뉴는 덮는 방식) · wide: 1025px 이상 (메뉴 고정)
// 폭이 소수(760.5px 같은 화면 배율)여서 두 구간 사이에 걸치면 CSS 처럼 넓은 화면 규칙(wide)을 따른다
import { useSyncExternalStore } from "react";

export const BAND_QUERIES = { narrow: "(max-width: 760px)", mid: "(min-width: 761px) and (max-width: 1024px)" };

const mq = (q) => (typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(q) : null);

export function bandNow() {
  if (mq(BAND_QUERIES.narrow)?.matches) return "narrow";
  if (mq(BAND_QUERIES.mid)?.matches) return "mid";
  return "wide";
}

function subscribe(cb) {
  const list = Object.values(BAND_QUERIES).map(mq).filter(Boolean);
  list.forEach((m) => (m.addEventListener ? m.addEventListener("change", cb) : m.addListener?.(cb)));
  window.addEventListener("resize", cb);   // matchMedia 의 change 를 못 받는 환경을 위해
  return () => {
    list.forEach((m) => (m.removeEventListener ? m.removeEventListener("change", cb) : m.removeListener?.(cb)));
    window.removeEventListener("resize", cb);
  };
}

// 지금 구간 이름. 구간이 바뀌면 다시 그린다
export function useBand() {
  return useSyncExternalStore(subscribe, bandNow, () => "wide");
}
