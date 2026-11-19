// 화면 모양: 시스템 설정 따름(기본) · 밝게 · 어둡게. <html data-theme="light|dark"> 하나로만 알리고 색은 tokens.css 가 정한다.
// 고른 값은 localStorage 'ic26.theme' 에 기억한다. 주소 뒤 ?theme=light|dark 는 이번 화면에서만 그 모양으로 (예전 화면과 같은 규칙, 저장 안 함)
import { useSyncExternalStore } from "react";

export const THEMES = ["system", "light", "dark"];
export const THEME_LABELS = { system: "시스템 설정 따름", light: "밝게", dark: "어둡게" };
const KEY = "ic26.theme";

function fromQuery() {
  try { const q = new URLSearchParams(window.location.search).get("theme"); return q === "light" || q === "dark" ? q : null; } catch { return null; }
}
function saved() {
  try { const v = localStorage.getItem(KEY); return THEMES.includes(v) ? v : "system"; } catch { return "system"; }
}

let current = fromQuery() || saved();
const listeners = new Set();

export function applyTheme(choice = current) {
  const html = document.documentElement;
  if (choice === "light" || choice === "dark") html.dataset.theme = choice;
  else delete html.dataset.theme;
}

export function setTheme(choice) {
  if (!THEMES.includes(choice)) return;
  current = choice;
  try { if (choice === "system") localStorage.removeItem(KEY); else localStorage.setItem(KEY, choice); } catch { /* 저장 못 해도 이번 화면은 그대로 */ }
  applyTheme(choice);
  listeners.forEach((l) => l());
}

// 다음 값: 시스템 → 밝게 → 어둡게 → 시스템
export const nextTheme = (choice) => THEMES[(THEMES.indexOf(choice) + 1) % THEMES.length];

// 지금 실제로 보이는 모양 (시스템이면 운영체제 설정을 본다)
export function effectiveTheme(choice = current) {
  if (choice === "light" || choice === "dark") return choice;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function subscribe(l) {
  listeners.add(l);
  const mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  mq?.addEventListener?.("change", l);
  return () => { listeners.delete(l); mq?.removeEventListener?.("change", l); };
}

// {choice, effective}
export function useTheme() {
  const key = useSyncExternalStore(subscribe, () => `${current}|${effectiveTheme()}`);
  const [choice, effective] = key.split("|");
  return { choice, effective };
}
