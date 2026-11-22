// 오늘 할 일 진행 보관 (state/flowKeep.js, 11/22 실사용 QA): 쓰고 되살리기, 24시간·카드 바뀜, 되살리기 전 쓰기 금지,
// 지우는 때(한 가게 · 이 사장님 전부)와 지우지 않는 때(로그아웃·가게 바꾸기), 서버 목록에 없는 승인 풀기, 크기·localStorage 오류
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { resetStore, setState, getState } from "./store.js";
import { clearStoreData, emptyFlow } from "./boot.js";
import { signedOut } from "./account.js";
import {
  FLOW_MAX_CHARS, FLOW_TTL_MS, cardKey, flowKeyOf, flushFlowKeep, forgetFlow, forgetUserFlows, loadFlow, restoredFlow,
} from "./flowKeep.js";

const CARD_A = { title: "포장 누락을 막아요", card: { card_id: "card_a", kind: "complaint", review_ids: ["r1", "r2"], snapshot_ids: [] } };
const CARD_A2 = { ...CARD_A, card: { ...CARD_A.card, review_ids: ["r1", "r2", "r3"] } };   // 같은 카드 id, 근거가 바뀜
const RUN_A = { card_id: "card_a", source: "seed", _run: 1, drafts: [
  { draft_id: "d1", generator: "reply_draft", target_review_id: "r1", text: "답글 하나" },
  { draft_id: "d2", generator: "prevention_notice", target_review_id: null, text: "안내문" },
] };
const KEY = "ic26.flow.v1:u1:store_ongi";
const ME = { authenticated: true, store_id: "store_ongi", user: { user_id: "u1" }, stores: [] };
const saved = () => JSON.parse(localStorage.getItem(KEY));

// 이 가게에서 되살리기를 마친 상태 (refresh 가 하는 일: 카드와 flowKey 를 함께)
const arm = (key = KEY) => setState({ me: ME, cards: [CARD_A], flowKey: key });
// 만든 글 + 안내문 승인 + 답글 고치는 중
const work = () => setState({ results: { card_a: RUN_A }, approved: new Set(["d2"]), pending: { d1: "답글 고침" }, current: "card_a", draftId: "d1",
  approvedLog: [{ id: "d2", kind: "prevention_notice", name: "포장·주문 안내문", at: "2026-11-22T10:00:00+09:00", edited: false, text: "안내문" }] });

beforeEach(() => {
  resetStore();
  flushFlowKeep();
  localStorage.clear();
  window.scrollTo = () => {};
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe("키", () => {
  it("사장님 id 와 가게 id 로 만들고, 둘 중 하나라도 모르면 보관하지 않는다", () => {
    expect(flowKeyOf(ME)).toBe(KEY);
    expect(flowKeyOf({ ...ME, user: null })).toBe("");
    expect(flowKeyOf({ ...ME, store_id: null })).toBe("");
    expect(flowKeyOf(null)).toBe("");
    expect(flowKeyOf({ store_id: "store_ongi", user: { user_id: "demo-1a2b3c4d5e6f", demo: true } })).toBe("ic26.flow.v1:demo-1a2b3c4d5e6f:store_ongi");
  });
  it("카드 열쇠는 id·근거가 같을 때만 같다", () => {
    expect(cardKey([CARD_A])).toBe(cardKey([{ ...CARD_A, title: "다른 제목" }]));
    expect(cardKey([CARD_A])).not.toBe(cardKey([CARD_A2]));
    expect(cardKey([])).toBe("");
  });
});

describe("쓰기", () => {
  it("되살린 뒤 바뀐 진행을 200ms 모아서 쓰고, 되살린 것 자체는 다시 쓰지 않는다", () => {
    vi.useFakeTimers();
    arm();
    vi.advanceTimersByTime(1000);
    expect(localStorage.getItem(KEY)).toBeNull();          // 키만 채웠을 때는 쓰지 않음 (새로고침만으로 저장 시각이 늘지 않게)
    work();
    expect(localStorage.getItem(KEY)).toBeNull();
    vi.advanceTimersByTime(200);
    const s = saved();
    expect(s).toMatchObject({ v: 1, cardKey: cardKey([CARD_A]), approved: ["d2"], pending: { d1: "답글 고침" }, current: "card_a", draftId: "d1" });
    expect(s.results.card_a.drafts.map((d) => d.draft_id)).toEqual(["d1", "d2"]);
    expect(Number.isFinite(Date.parse(s.at))).toBe(true);
  });

  it("되살리기 전(flowKey 가 null)에는 쓰지도 지우지도 않는다: storeChanged 가 비운 진행으로 새 가게의 키를 지우지 않게", () => {
    localStorage.setItem(KEY, JSON.stringify({ v: 1, keep: "옛 진행" }));
    setState({ me: ME, cards: [CARD_A] });
    work();
    setState({ ...emptyFlow(), flowKey: null, epoch: 1 });
    flushFlowKeep();
    expect(saved()).toEqual({ v: 1, keep: "옛 진행" });
  });

  it("진행이 모두 비면 키를 지운다", () => {
    arm(); work(); flushFlowKeep();
    expect(saved()).not.toBeNull();
    setState(emptyFlow());
    flushFlowKeep();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("로그아웃(clearStoreData)은 지우지 않고, 그때까지 고친 것을 마저 쓴다", () => {
    vi.useFakeTimers();
    arm(); work();
    signedOut({ authenticated: false, user: null, store_id: null, stores: [] });   // 200ms 가 지나기 전에 로그아웃
    expect(getState().flowKey).toBeNull();
    expect(saved().pending).toEqual({ d1: "답글 고침" });
    vi.advanceTimersByTime(1000);
    expect(saved().approved).toEqual(["d2"]);
  });

  it("가게를 바꾸면 앞 가게 키에 마저 쓰고, 다른 가게의 키는 건드리지 않는다", () => {
    const other = "ic26.flow.v1:u1:store_basak";
    localStorage.setItem(other, JSON.stringify({ v: 1, keep: "바삭치킨 진행" }));
    arm(); work();
    clearStoreData();
    expect(saved().approved).toEqual(["d2"]);
    expect(JSON.parse(localStorage.getItem(other))).toEqual({ v: 1, keep: "바삭치킨 진행" });
  });

  it("너무 크면 쓰지 않고 앞서 쓴 옛 진행도 지운다", () => {
    arm(); work(); flushFlowKeep();
    expect(saved()).not.toBeNull();
    const big = "가".repeat(FLOW_MAX_CHARS + 10);
    setState({ results: { card_a: { ...RUN_A, drafts: [{ ...RUN_A.drafts[0], text: big }, RUN_A.drafts[1]] } } });
    flushFlowKeep();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("localStorage 가 막혀도 깨지지 않는다 (지금처럼 메모리만)", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("QuotaExceededError"); });
    arm(); work();
    expect(() => flushFlowKeep()).not.toThrow();
    expect(localStorage.getItem(KEY)).toBeNull();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("SecurityError"); });
    expect(loadFlow(KEY, [CARD_A])).toBeNull();
  });
});

describe("되살리기", () => {
  function write() { arm(); work(); flushFlowKeep(); resetStore(); }

  it("v·카드·24시간이 맞으면 되살리고 승인 표시는 Set 으로", () => {
    write();
    const s = loadFlow(KEY, [CARD_A]);
    const r = restoredFlow(s, null);
    expect(r.approved).toBeInstanceOf(Set);
    expect([...r.approved]).toEqual(["d2"]);
    expect(r.pending).toEqual({ d1: "답글 고침" });
    expect(r.approvedLog.map((a) => a.id)).toEqual(["d2"]);
    expect(r.results.card_a._run).toBe(1);
    expect([r.current, r.draftId]).toEqual(["card_a", "d1"]);
  });

  it("24시간이 지났으면 키를 지우고 되살리지 않는다", () => {
    write();
    expect(loadFlow(KEY, [CARD_A], Date.now() + FLOW_TTL_MS + 60000)).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("카드(id·근거)가 바뀌었으면 키를 지우고 되살리지 않는다", () => {
    write();
    expect(loadFlow(KEY, [CARD_A2])).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("판(v)이 다르거나 모양이 틀리면 지운다", () => {
    write();
    localStorage.setItem(KEY, JSON.stringify({ ...saved(), v: 2 }));
    expect(loadFlow(KEY, [CARD_A])).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
    localStorage.setItem(KEY, "{깨진 글");
    expect(loadFlow(KEY, [CARD_A])).toBeNull();
    expect(loadFlow("", [CARD_A])).toBeNull();
  });

  it("서버 승인 목록에 없는 승인 표시는 풀고, 목록을 못 읽었으면 보관한 그대로", () => {
    const s = { results: { card_a: RUN_A }, approved: ["d1", "d2"], pending: {}, current: "card_a", draftId: "d2",
      approvedLog: [{ id: "d1" }, { id: "d2" }, { id: "mkt-1", mkt: true }] };
    const off = restoredFlow(s, [{ draft_id: "d1", status: "approved" }, { draft_id: "mkt-1" }]);
    expect([...off.approved]).toEqual(["d1"]);
    expect(off.approvedLog.map((a) => a.id)).toEqual(["d1", "mkt-1"]);   // 맞춤 마케팅 승인은 results 에 없어도 서버에 있으면 남김
    const keep = restoredFlow(s, null);
    expect([...keep.approved]).toEqual(["d1", "d2"]);
    expect(keep.approvedLog).toHaveLength(3);
  });

  it("results 에 없는 글의 승인 표시·고치는 중인 글은 버린다", () => {
    const s = { results: { card_a: RUN_A }, approved: ["d2", "d_gone"], approvedLog: [], pending: { d1: "고침", d_gone: "옛 글", d2: 3 },
      current: "card_gone", draftId: "d_gone" };
    const r = restoredFlow(s, null);
    expect([...r.approved]).toEqual(["d2"]);
    expect(r.pending).toEqual({ d1: "고침" });
    expect([r.current, r.draftId]).toEqual([null, null]);
  });
});

describe("지우기", () => {
  it("forgetFlow: 그 가게의 키만, 아직 쓰지 않은 것도 버린다", () => {
    vi.useFakeTimers();
    localStorage.setItem("ic26.flow.v1:u1:store_basak", "{}");
    arm(); work();                         // 200ms 안: 아직 쓰지 않음
    forgetFlow(KEY);
    vi.advanceTimersByTime(1000);
    flushFlowKeep();
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(localStorage.getItem("ic26.flow.v1:u1:store_basak")).toBe("{}");
    expect(() => forgetFlow("")).not.toThrow();
  });

  it("forgetUserFlows: 이 사장님의 모든 가게 것만 (다른 사장님·다른 칸은 그대로)", () => {
    ["ic26.flow.v1:u1:store_ongi", "ic26.flow.v1:u1:store_basak", "ic26.flow.v1:u10:store_ongi", "ic26.flow.v1:u2:store_ongi", "ic26.theme"]
      .forEach((k) => localStorage.setItem(k, "{}"));
    forgetUserFlows("u1");
    const keys = Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i));
    expect(keys.sort()).toEqual(["ic26.flow.v1:u10:store_ongi", "ic26.flow.v1:u2:store_ongi", "ic26.theme"]);
    expect(() => forgetUserFlows("")).not.toThrow();
  });
});
