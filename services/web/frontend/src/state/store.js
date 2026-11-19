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
    me: null,            // GET /api/auth/me (null 이면 게스트로 봄)
    // 오늘 할 일 진행 (브라우저 메모리에만. 새로고침하면 사라짐, docs/api/contract.md 2.6)
    results: {},         // card_id → POST /api/cards/{id}/run 응답
    approved: new Set(), // 승인한 draft_id
    approvedLog: [],     // 처리 완료 화면의 승인 목록 [{id, kind, title, text, edited, at, mkt?}]
    pending: {},         // draft_id → 고치는 중인 글
    current: null,       // 초안 화면에 보이는 카드 id
    draftId: null,       // 초안 화면에 크게 보이는 글 id
    joined: [],          // 방금 붙여넣은 리뷰가 들어간 묶음 id
    // 화면 공통
    booted: false, bootError: "",
    alert: "",           // 맨 위 알림 띠
    acctBusy: false,     // 로그인·가게 바꾸기 등 다시 읽는 중 (상단 바 계정 버튼 잠금)
    acctNotice: "",      // 내 계정에서 지운 결과 띠
    authOpen: false,     // 로그인 창
    acctOpen: false,     // 내 계정 창
    drawerOpen: false,   // AI에게 묻기 서랍
    staffMarket: null,   // GET /api/market/status (AI 비서 칸의 상권 분석 비서)
    mktServer: 0,        // 서버에 남은 맞춤 마케팅 승인 수
    nav: { name: null, sub: null, seq: 0 },   // navTo 요청 (router.js)
    mktResetSeq: 0,      // 처리 완료의 '처음부터 다시'가 1씩 올림 → 맞춤 마케팅 대화·카드·보고서를 처음으로 (예전 mktReset)
    mktCleared: null,    // 그때 서버의 marketing_cleared (true 지움 · false 서비스가 받지 않음 · null 꺼 둠·연결 못 함). false 면 맞춤 마케팅 화면 위에 안내
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
