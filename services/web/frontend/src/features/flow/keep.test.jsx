// 새로고침·다시 로그인해도 오늘 할 일 진행이 남는지 (11/22 실사용 QA, state/flowKeep.js · state/boot.js refresh).
// 새로고침은 '페이지를 떠날 때 쓰기(pagehide) → store 를 처음으로 → 같은 사장님·가게로 다시 들어감(enterApp)'으로 흉내 낸다.
// 함께 보는 것: 승인 요청에 글 종류·카드, 처리 완료의 서버 글 이름, 진행이 없는 카드의 '오늘 승인한 글' 안내와 replaces
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, act, waitFor } from "@testing-library/react";
import { resetStore, setState, getState } from "../../state/store.js";
import { enterApp } from "../../state/boot.js";
import { signedOut } from "../../state/account.js";
import { cardKey, flushFlowKeep } from "../../state/flowKeep.js";
import { resetFlow } from "./state.js";
import { runCard, approve, restart } from "./actions.js";
import Home from "./Home.jsx";
import Cards from "./Cards.jsx";
import Draft from "./Draft.jsx";
import Done from "./Done.jsx";

const KEY = "ic26.flow.v1:u1:store_ongi";
const ME = (userId = "u1") => ({ authenticated: true, store_id: "store_ongi", demo_login: false,
  stores: [{ store_id: "store_ongi", name: "온기한식", sample: true }],
  user: { user_id: userId, login_id: "owner_test", display_name: "김시험", demo: false } });
const BRIEFING = { store: { name: "온기한식" }, period: { start: "2026-11-15", end: "2026-11-21" }, counts: { review_count: 20, complaint_count: 2 },
  top_issue_id: "i1", pasted: [], single_complaints: [], snapshots: [],
  groups: [{ issue_id: "i1", topic_name: "포장 누락", review_count: 2, is_repeated: false, main_time_band: "17~21시",
    reviews: [{ review_id: "r1", text: "밥이 빠졌어요", created_at: "2026-11-20T18:10:00+09:00" }, { review_id: "r2", text: "수저 없음", created_at: "2026-11-21T19:00:00+09:00" }] }] };
const CARD_A = { title: "포장 누락을 막아요", reason_source: "규칙", problems: [], reply_count: 1,
  card: { card_id: "card_a", kind: "complaint", reason_text: "포장 누락 2건", review_ids: ["r1", "r2"], snapshot_ids: [] },
  evidence: [{ type: "review", id: "r1", text: "밥이 빠졌어요" }, { type: "review", id: "r2", text: "수저 없음" }] };
const RUN_A = { card_id: "card_a", source: "seed", drafts: [
  { draft_id: "d1", generator: "reply_draft", target_review_id: "r1", text: "답글 하나" },
  { draft_id: "d2", generator: "prevention_notice", target_review_id: null, text: "안내문" },
] };

let calls, routes, approvals;
// 가짜 서버: 승인하면 서버 목록(approvals)에 글 종류·카드와 함께 남고, '처음부터 다시'는 목록을 비운다
function server(extra = {}) {
  calls = [];
  approvals = [];
  routes = { "/api/health": { mode: "mock" }, "/api/briefing": BRIEFING, "/api/cards": { cards: [CARD_A] }, "/api/insight": {},
    "/api/market/status": { state: "ready" }, "GET /api/approvals": () => ({ items: approvals }),
    "POST /api/cards/card_a/run": RUN_A,
    "DELETE /api/approvals": () => { const deleted = approvals.length; approvals = []; return { deleted, marketing_cleared: true }; },
    ...extra };
  globalThis.fetch = vi.fn(async (path, opt = {}) => {
    const method = (opt.method || "GET").toUpperCase();
    const body = opt.body ? JSON.parse(opt.body) : undefined;
    calls.push({ path, method, body });
    let h = routes[`${method} ${path}`] ?? routes[path];
    const m = path.match(/^\/api\/drafts\/([^/]+)\/approve$/);
    if (h === undefined && m) {
      h = (b) => {
        const entry = { draft_id: decodeURIComponent(m[1]), status: "approved", edited: b.text !== b.original, text: b.text,
          approved_at: "2026-11-22T10:00:00+09:00", mode: "mock" };
        approvals = [...approvals.filter((x) => x.draft_id !== entry.draft_id), { ...entry, kind: b.kind ?? null, card_id: b.card_id ?? null }];
        return entry;
      };
    }
    const out = typeof h === "function" ? h(body) : h;
    const [status, data] = Array.isArray(out) ? out : [200, out ?? {}];
    return { ok: status < 400, status, json: async () => data, headers: { get: () => "application/json" } };
  });
}
const since = (n) => calls.slice(n).map((c) => `${c.method} ${c.path}`);

async function open(me = ME()) {
  setState({ me });
  await act(async () => { await enterApp(); });
}
// 새로고침: 떠날 때 쓰고(pagehide) → 화면 상태를 처음으로 → 같은 사장님·가게로 다시 들어감
async function reload(me = ME()) {
  window.dispatchEvent(new Event("pagehide"));
  resetStore(); resetFlow();
  await open(me);
}

beforeEach(() => {
  resetStore(); resetFlow();
  flushFlowKeep();
  localStorage.clear();
  sessionStorage.clear();
  window.location.hash = "#/today";
  window.scrollTo = () => {};
  server();
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("새로고침해도 오늘 할 일 진행이 남는다", () => {
  it("만든 글 · 승인 표시 · 고치던 글이 그대로이고, 다시 만들지 않는다 (서버 목록을 기다려 맞춘 뒤 카드와 한 번에)", async () => {
    await open();
    expect(getState().flowKey).toBe(KEY);
    await act(async () => { await runCard("card_a"); });
    await act(async () => { await approve("d2"); });                 // 안내문 승인
    act(() => setState((s) => ({ pending: { ...s.pending, d1: "답글 고침" } })));   // 답글은 고치는 중
    expect(localStorage.getItem(KEY)).toBeNull();                     // 아직 200ms 안
    const n = calls.length;
    await reload();
    const s = getState();
    expect(Object.keys(s.results)).toEqual(["card_a"]);
    expect([...s.approved]).toEqual(["d2"]);
    expect(s.pending).toEqual({ d1: "답글 고침" });
    expect(s.approvedLog.map((a) => [a.id, a.name])).toEqual([["d2", "포장·주문 안내문"]]);
    // 카드를 받은 뒤 승인 목록을 기다려 받고 나서 리뷰 분석으로. 승인 목록은 한 번만, 글은 다시 만들지 않음 (HCX 재호출 없음)
    const after = since(n);
    expect(after.filter((x) => x === "GET /api/approvals")).toHaveLength(1);
    expect(after.indexOf("GET /api/cards")).toBeLessThan(after.indexOf("GET /api/approvals"));
    expect(after.indexOf("GET /api/approvals")).toBeLessThan(after.indexOf("GET /api/insight"));
    expect(after.some((x) => x.endsWith("/run"))).toBe(false);

    render(<Draft />);
    expect(screen.getByText("승인 1 / 2")).toBeTruthy();
    expect(screen.getByLabelText(/AI 답글 초안/).value).toBe("답글 고침");
    cleanup();
    const { container } = render(<Home />);
    // 안내문 할 일은 끝, 답글은 승인 대기 (만들기 전으로 돌아가지 않음)
    expect([...container.querySelectorAll(".flow-todo-st")].map((x) => x.textContent)).toEqual(["완료", "승인 0 / 1"]);
    expect(screen.queryByText(/오늘 승인한 글/)).toBeNull();          // 되살렸으면 안내 없음
  });

  it("로그아웃했다 같은 사장님으로 다시 로그인하면 이어서, 다른 사장님에게는 보이지 않는다", async () => {
    await open();
    await act(async () => { await runCard("card_a"); });
    await act(async () => { await approve("d1"); });
    act(() => signedOut({ authenticated: false, user: null, store_id: null, stores: [] }));
    expect(localStorage.getItem(KEY)).not.toBeNull();                 // 로그아웃은 지우지 않음
    expect(getState().results).toEqual({});
    await open(ME("u2"));                                             // 다른 사장님
    expect(getState().results).toEqual({});
    act(() => signedOut({ authenticated: false, user: null, store_id: null, stores: [] }));
    await open();                                                     // 같은 사장님 다시
    expect([...getState().approved]).toEqual(["d1"]);
    // 고객 응대 비서 줄도 승인한 답글을 센다 (불만 r1·r2 중 r1 답글 승인 → 1건, '2건'으로 돌아가지 않음)
    render(<Home />);
    expect(screen.getByText(/답글 안 단 불만 1건/)).toBeTruthy();
  });

  it("같은 가게를 다시 불러와도(storeChanged: 가게 정보 고치기 등) 비운 진행으로 키를 지우지 않고 이어서 한다", async () => {
    await open();
    await act(async () => { await runCard("card_a"); });
    await act(async () => { await approve("d1"); });
    await act(async () => { await enterApp(); });                     // 페이지는 그대로, 가게 자료만 다시
    expect([...getState().approved]).toEqual(["d1"]);
    expect(Object.keys(getState().results)).toEqual(["card_a"]);
  });

  it("다른 곳에서 서버 승인 기록을 지웠으면 그 승인 표시는 풀린다 (되살릴 때 한 번 맞춤)", async () => {
    await open();
    await act(async () => { await runCard("card_a"); });
    await act(async () => { await approve("d1"); });
    await act(async () => { await approve("d2"); });
    approvals = approvals.filter((x) => x.draft_id !== "d1");       // 다른 기기에서 지움
    await reload();
    expect([...getState().approved]).toEqual(["d2"]);
    expect(getState().approvedLog.map((a) => a.id)).toEqual(["d2"]);
    expect(Object.keys(getState().results)).toEqual(["card_a"]);     // 만든 글은 그대로
  });

  it("서버 목록을 못 읽으면 보관한 그대로 되살린다", async () => {
    await open();
    await act(async () => { await runCard("card_a"); });
    await act(async () => { await approve("d1"); });
    routes["GET /api/approvals"] = [503, { error: { message: "DB 꺼짐" } }];
    await reload();
    expect([...getState().approved]).toEqual(["d1"]);
  });

  it("되살린 글을 카드 전체로 다시 만들면 새 번호(_run)가 되살린 번호보다 크다 (새로고침하면 번호를 0부터 다시 세므로)", async () => {
    localStorage.setItem(KEY, JSON.stringify({ v: 1, at: new Date().toISOString(), cardKey: cardKey([CARD_A]),
      results: { card_a: { ...RUN_A, _run: 999 } }, approved: [], approvedLog: [], pending: {}, current: "card_a", draftId: null }));
    await open();
    expect(getState().results.card_a._run).toBe(999);
    await act(async () => { await runCard("card_a", "rerun"); });
    expect(getState().results.card_a._run).toBe(1000);
  });

  it("카드(근거)가 바뀌었으면 되살리지 않고 키도 지운다", async () => {
    await open();
    await act(async () => { await runCard("card_a"); });
    window.dispatchEvent(new Event("pagehide"));
    routes["/api/cards"] = { cards: [{ ...CARD_A, card: { ...CARD_A.card, review_ids: ["r1", "r2", "r3"] } }] };
    await reload();
    expect(getState().results).toEqual({});
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("'처음부터 다시'는 보관한 진행도 지운다", async () => {
    await open();
    await act(async () => { await runCard("card_a"); });
    await act(async () => { await approve("d1"); });
    window.dispatchEvent(new Event("pagehide"));
    expect(localStorage.getItem(KEY)).not.toBeNull();
    await act(async () => { await restart(); });
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(getState().serverApprovals).toEqual([]);
    await reload();
    expect(getState().results).toEqual({});
  });
});

describe("처리 완료: 서버에만 있는 글의 이름 (글 종류·카드)", () => {
  it("서버가 준 kind·card_id 로 '답글'·'포장·주문 안내문'·맞춤 마케팅 글 종류, 모르면 '글'", async () => {
    server({ "GET /api/approvals": { items: [
      { draft_id: "d_a", status: "approved", edited: false, text: "답글 글", approved_at: "2026-11-22T09:00:00+09:00", mode: "live", kind: "reply_draft", card_id: "card_a" },
      { draft_id: "d_b", status: "approved", edited: true, text: "안내문 글", approved_at: "2026-11-22T09:01:00+09:00", mode: "live", kind: "prevention_notice", card_id: "card_a" },
      { draft_id: "mkt-1", status: "approved", edited: false, text: "쿠폰", approved_at: "2026-11-22T09:02:00+09:00", mode: "live", kind: "쿠폰 글", card_id: "marketing" },
      { draft_id: "d_old", status: "approved", edited: false, text: "옛 글", approved_at: "2026-11-22T09:03:00+09:00", mode: "live", kind: null, card_id: null },
    ] } });
    setState({ cards: [CARD_A] });
    let container;
    await act(async () => { ({ container } = render(<Done />)); });
    const names = [...container.querySelectorAll(".flow-log-item .strong")].map((x) => x.textContent);
    expect(names).toEqual(["답글", "포장·주문 안내문", "쿠폰 글", "글"]);
    expect(container.querySelector(".flow-done-tiles .tile-sub").textContent).toBe("답글 1 · 포장·주문 안내문 1 · 쿠폰 글 1 · 글 1");
    expect([...container.querySelectorAll(".flow-server-log li")].map((x) => x.textContent)).toEqual([
      "11-22 09:00 승인 · 답글", "11-22 09:01 승인 · 포장·주문 안내문 (고침)", "11-22 09:02 승인 · 쿠폰 글", "11-22 09:03 승인 · 글"]);
    expect(screen.getByRole("button", { name: "포장·주문 안내문 복사" })).toBeTruthy();
  });
});

describe("진행이 없는데 서버에 그 카드의 승인 기록이 있으면 (다른 기기·24시간 뒤)", () => {
  // 안내·replaces 는 오늘 승인한 글만 대상이라 시험하는 날의 날짜로 만든다 (지난날 승인은 이력으로 남김)
  const pad = (n) => String(n).padStart(2, "0"), now = new Date();
  const TODAY = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const other = [
    { draft_id: "dx1", status: "approved", edited: false, text: "답글", approved_at: `${TODAY}T09:00:00+09:00`, mode: "mock", kind: "reply_draft", card_id: "card_a" },
    { draft_id: "dx2", status: "approved", edited: false, text: "안내문", approved_at: `${TODAY}T09:01:00+09:00`, mode: "mock", kind: "prevention_notice", card_id: "card_a" },
    { draft_id: "mkt-9", status: "approved", edited: false, text: "쿠폰", approved_at: `${TODAY}T09:02:00+09:00`, mode: "mock", kind: "쿠폰 글", card_id: "marketing" },
    { draft_id: "d_old", status: "approved", edited: false, text: "지난 답글", approved_at: "2026-01-05T09:00:00+09:00", mode: "mock", kind: "reply_draft", card_id: "card_a" },
  ];

  it("추천 카드·홈 할 일에 한 줄로 알리고, 만들면 그 승인 글을 replaces 로 보낸다 (처리 완료에 같은 글이 두 번 쌓이지 않게)", async () => {
    await open();
    approvals = other;
    await act(async () => { await enterApp(); });                     // 다른 기기에서 연 것처럼 (보관한 진행 없음)
    await waitFor(() => expect(getState().serverApprovals).toHaveLength(4));
    const note = "오늘 승인한 글 2개가 있어요. 새로 만들면 그 승인 기록은 새 글로 바뀌어요.";
    render(<Home />);
    const homeNote = screen.getByText(note, { exact: false });
    expect(homeNote.getAttribute("role")).toBe("status");
    expect(homeNote.querySelector("a").getAttribute("href")).toBe("#/done");
    cleanup();
    render(<Cards />);
    const cardNote = screen.getByText(note, { exact: false });
    expect(cardNote.closest("article").id).toBe("card-card_a");
    expect(screen.getByRole("link", { name: "처리 완료에서 보기" }).getAttribute("href")).toBe("#/done");
    const n = calls.length;
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "포장·주문 안내문·답글 만들기" })); });
    const run = calls.slice(n).find((c) => c.path === "/api/cards/card_a/run");
    expect(run.body).toEqual({ replaces: ["dx1", "dx2"] });
    expect(getState().serverApprovals.map((x) => x.draft_id)).toEqual(["mkt-9", "d_old"]);   // 바꾼 기록은 안내 목록에서도 뺌 (지난날 승인은 그대로)
    cleanup();
    render(<Cards />);
    expect(screen.queryByText(/오늘 승인한 글/)).toBeNull();          // 이제 이 브라우저에 진행이 있다
  });

  it("서버에 그 카드의 기록이 없으면 안내도 replaces 도 없다 (처음 만들 때 예전과 같은 본문)", async () => {
    await open();
    approvals = [other[2]];                                           // 맞춤 마케팅 승인만
    await act(async () => { await enterApp(); });
    await waitFor(() => expect(getState().serverApprovals).toHaveLength(1));
    render(<Cards />);
    expect(screen.queryByText(/오늘 승인한 글/)).toBeNull();
    const n = calls.length;
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "포장·주문 안내문·답글 만들기" })); });
    expect(calls.slice(n).find((c) => c.path === "/api/cards/card_a/run").body).toBeUndefined();
  });
});
