// 화면 전체가 같이 보는 상태 하나 (외부 라이브러리 없이 useSyncExternalStore).
// - setState 는 얕게 합친다. Set·객체는 바꿀 때 새로 만들어 넣는다 (예: approved: new Set([...s.approved, id])).
// - useStore(selector) 의 selector 는 상태 안의 값을 그대로 돌려줘야 한다 (매번 새 객체를 만들면 끝없이 다시 그림).
import { useSyncExternalStore } from "react";

export function initialState() {
  return {
    // 서버에서 받은 것
    health: null,        // GET /api/health
    briefing: null,      // GET /api/briefing
    reviewsById: {},     // 브리핑의 리뷰 원문 (초안 화면의 '손님 리뷰' 칸)
    cards: [],           // GET /api/cards 의 cards
    noCardB: "",         // GET /api/cards 의 no_card_b
    insight: null,       // GET /api/insight
    insightError: "",
    me: null,            // GET /api/auth/me (null 이면 아직 모름. 로그인 전이면 authenticated: false)
    // 오늘 할 일 진행 (브라우저 메모리에만. 새로고침하면 사라짐, docs/api/contract.md 2.6)
    results: {},         // card_id → POST /api/cards/{id}/run 응답
    approved: new Set(), // 승인한 draft_id
    approvedLog: [],     // 처리 완료 화면의 승인 목록 [{id, kind, title, text, edited, at, mkt?}]
    pending: {},         // draft_id → 고치는 중인 글
    current: null,       // 초안 화면에 보이는 카드 id
    draftId: null,       // 초안 화면에 크게 보이는 글 id
    joined: [],          // 방금 붙여넣은 리뷰가 들어간 묶음 id
    // 단계 (state/stage.js, docs/api/contract.md 2.2). 해시 주소(#/today …)는 app 단계 안에서만 쓴다
    // boot · login · signup · pick(가게 선택) · store-new(새 가게 등록) · profile(사장님 프로필) · app(메인 화면) · error · expired · forbidden
    stage: "boot",
    stageError: "",      // error 단계에 보일 한 줄 (서버가 준 notice 등)
    storeNew: null,      // store-new 단계의 {mode: "signup"|"add"|"edit", storeId?}
    storeNewFrom: "pick", // store-new 의 [취소]가 돌아갈 단계 (pick · profile)
    entered: null,       // app 단계에서 자료를 불러온 가게 id (sessionStorage ic26.entered 와 같음)
    resume: null,        // 로그인이 끝나 expired 로 갈 때 {userId, storeId}: 같은 사장님·같은 가게로 다시 로그인하면 app 으로 바로
    // 화면 공통
    booted: false, bootError: "",   // booted: 들어간 가게의 자료를 한 번 다 불러옴 (실패 포함)
    alert: "",           // 맨 위 알림 띠
    acctBusy: false,     // 로그인·가게 열기 등 다시 읽는 중 (상단 바 계정 버튼 잠금)
    acctNotice: "",      // 기록 지우기·탈퇴 결과 띠 (모든 단계에서 오른쪽 아래)
    drawerOpen: false,   // AI에게 묻기 서랍
    staffMarket: null,   // GET /api/market/status (AI 비서 칸의 상권 분석 비서)
    mktServer: 0,        // 서버에 남은 맞춤 마케팅 승인 수
    nav: { name: null, sub: null, seq: 0 },   // navTo 요청 (router.js)
    mktResetSeq: 0,      // 처리 완료의 '처음부터 다시'가 1씩 올림 → 맞춤 마케팅 대화·카드·보고서를 처음으로 (예전 mktReset)
    mktCleared: null,    // 그때 서버의 marketing_cleared (true 지움 · false 서비스가 받지 않음 · null 꺼 둠·연결 못 함). false 면 맞춤 마케팅 화면 위에 안내
    reportsSeq: 0,       // 기록 지우기(POST /api/auth/reset)가 끝나면 1씩 → 프로필 '보관한 보고서' 수를 다시 부름 (11/21 QA)
    epoch: 0,            // 가게가 바뀔 때마다 1씩 (로그인·로그아웃·가게 바꾸기·기록 지우기). 각 화면은 이 값이 바뀌면 자기 상태를 처음으로
  };
}

let state = initialState();
const listeners = new Set();

export const getState = () => state;

export function setState(patch) {
  const next = typeof patch === "function" ? patch(state) : patch;
  if (!next) return;
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

function subscribe(l) { listeners.add(l); return () => listeners.delete(l); }

export function useStore(selector = (s) => s) {
  return useSyncExternalStore(subscribe, () => selector(state));
}

// 시험에서만 쓴다
export function resetStore() { state = initialState(); listeners.forEach((l) => l()); }

export const setAlert = (msg) => setState({ alert: msg || "" });
export const openDrawer = (open = true) => setState((s) => ({ drawerOpen: open === "toggle" ? !s.drawerOpen : !!open }));
// 'AI에게 묻기' 버튼: 닫혀 있으면 열고, 열려 있으면 닫지 않고 입력칸으로 (입력칸이 준비 전이면 닫기 버튼으로). 닫기는 서랍의 닫기·Esc 가 맡는다
export function focusOrOpenDrawer() {
  if (!state.drawerOpen) { openDrawer(true); return; }
  const q = document.getElementById("assistant-q");
  const target = q && !q.disabled ? q : document.getElementById("assistant-close");
  target?.focus({ preventScroll: true });
}
