// 리뷰 분석 화면의 모듈 상태: 메뉴를 오가도 남아야 하는 것 (고른 탭, 붙여넣기 칸·결과, 캡처 진행).
// 화면은 메뉴로 들어올 때마다 새로 마운트되므로 여기에 두고, 가게가 바뀌면(epoch) 탭만 빼고 처음으로 되돌린다.
import { useSyncExternalStore } from "react";
import { AN_TABS } from "./calc.js";

const freshPaste = () => ({ text: "", rating: "", channel: "", msg: "", result: null, busy: false, resetBusy: false });
// file: 고른 파일, url: 미리보기 주소(읽은 캡처), reading: 캡처 읽는 중(진행 표시), busy: 읽기·저장 중(버튼 잠금)
// result: 읽은 결과 {demo, warnings} (없으면 후보 칸을 숨김), items: 후보 [{text, rating, ai, pii, dup, picked, saved, msg}]
const freshCap = () => ({ file: null, fileName: "고른 파일 없음", url: null, reading: false, busy: false, startedAt: 0,
  status: "", error: "", result: null, items: [], saveMsg: "" });

let mod = { tab: "summary", navSeq: 0, epoch: null, paste: freshPaste(), cap: freshCap() };
const listeners = new Set();
const emit = () => listeners.forEach((l) => l());

export const getMod = () => mod;
export function setMod(patch) { mod = { ...mod, ...patch }; emit(); }
export function setPaste(patch) { mod = { ...mod, paste: { ...mod.paste, ...patch } }; emit(); }
export function setCap(patch) { mod = { ...mod, cap: { ...mod.cap, ...(typeof patch === "function" ? patch(mod.cap) : patch) } }; emit(); }
export function setCapItem(i, patch) {
  setCap((c) => ({ items: c.items.map((x, k) => (k === i ? { ...x, ...patch } : x)) }));
}

// 가게가 바뀌었으면 처음으로 (예전 ...Reset). 화면을 그리기 전에 부른다: 알림 없이 바꿔서 그리는 중에 다른 화면을 흔들지 않음
export function syncEpoch(epoch) {
  if (mod.epoch === epoch) return;
  if (mod.epoch !== null) {
    if (mod.cap.url) URL.revokeObjectURL(mod.cap.url);
    mod = { ...mod, paste: freshPaste(), cap: freshCap() };
  }
  mod = { ...mod, epoch };
}

// 탭 고르기. focus 면 그 탭 버튼으로 포커스 (예전 showTab(name, true): 다른 화면의 바로가기·'불만 묶음 보기')
export function showTab(name, focus = false) {
  if (!AN_TABS.includes(name)) return;
  setMod({ tab: name });
  if (focus) setTimeout(() => document.getElementById(`an-tab-${name}`)?.focus(), 0);   // 화면을 열 때의 제목 포커스보다 뒤에
}

function subscribe(l) { listeners.add(l); return () => listeners.delete(l); }
export const useMod = (selector) => useSyncExternalStore(subscribe, () => selector(mod));

// 시험에서만
export function resetMod() { mod = { tab: "summary", navSeq: 0, epoch: null, paste: freshPaste(), cap: freshCap() }; emit(); }
