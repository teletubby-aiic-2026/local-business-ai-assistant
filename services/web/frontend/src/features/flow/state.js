// 흐름 화면이 떠났다 와도 남아야 하는 작은 상태 (store.js 와 같은 방식).
// 진행 결과(results·approved·pending …)는 store.js 에 있고, 여기는 화면 동작에만 쓰는 것:
//   busy   card_id → 만들고 있는 곳("card" | "todo:<key>" | "rerun"). 같은 카드의 버튼을 잠그고 그 버튼만 '만드는 중…'
//   regen  다시 만드는 중인 글 (regenKey). 화면을 다시 그려도 '만드는 중…'으로 남는다
//   note   초안 상자 아래 한 줄 안내 { id: 글 id, text }
//   armed  '카드 전체 다시 만들기'를 한 번 눌러 둔 카드 (5초 안에 한 번 더 누르면 실행)
//   picks  card_id → 사장님이 바꾼 점검 수칙 체크 (만들기 전에 홈 할 일에서 만들어도 같은 체크를 보낸다)
// 가게가 바뀌면(epoch) 처음으로 되돌린다.
import { useSyncExternalStore } from "react";
import { getState } from "../../state/store.js";

const init = () => ({ busy: {}, regen: new Set(), note: null, armed: null, timer: null, picks: {}, epoch: getState().epoch });
let flow = init();
const listeners = new Set();

export const getFlow = () => flow;

export function setFlow(patch) {
  const next = typeof patch === "function" ? patch(flow) : patch;
  if (!next) return;
  flow = { ...flow, ...next };
  listeners.forEach((l) => l());
}

export function resetFlow() {
  clearTimeout(flow.timer);
  flow = init();
  listeners.forEach((l) => l());
}

// 화면을 그리기 전에 부른다. 가게가 바뀌었으면 조용히 처음으로 (화면은 epoch 가 바뀌면 새로 마운트되므로 알릴 곳이 없다)
function syncEpoch() {
  if (flow.epoch !== getState().epoch) { clearTimeout(flow.timer); flow = init(); }
}

function subscribe(l) { listeners.add(l); return () => listeners.delete(l); }

export function useFlow(selector = (f) => f) {
  syncEpoch();
  return useSyncExternalStore(subscribe, () => selector(flow));
}
