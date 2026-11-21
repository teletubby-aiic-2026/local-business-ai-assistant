// 맞춤 마케팅 화면이 가짜 서비스로 처음부터 승인까지 도는지 (health → meta → step → 시작 모드 → plan → 승인)
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { getState, setState } from "../../state/store.js";
import Marketing from "./Marketing.jsx";
import { MKT_DEMO_NOTICE, noticeLines } from "./state.js";
import { getChat } from "../assistant/state.js";

const START = { state: { node: "start", raw: {}, confirms: {}, mode: null }, bot_messages: ["무엇을 도와드릴까요?"], done: false,
  options: [{ label: "맞춤 홍보 제안" }, { label: "광고비 점검" }], multi: false, input: null };
const PLAN = { title: "광고비 점검 결과", demo: true, session_id: "s1",
  table: [{ label: "배민", spend_won: 100000, orders: 20, cost_per_order_won: 5000, profit_per_order_won: 3000, verdict: "손해 광고" }],
  steps: [{ step_id: "promo", what: "홍보 글 올리기", generator: "review_promo" }], drafts: { promo: "처음 글" } };

// hold: 시작 모드를 고른 뒤의 step 응답을 붙잡아 둘 약속 (응답 전 화면을 보려고)
function fakeFetch(calls, hold = null, plan = PLAN) {
  return vi.fn(async (url, opts = {}) => {
    const path = String(url).replace("/api/marketing-survey/", "");
    const body = opts.body ? JSON.parse(opts.body) : null;
    calls.push({ path, body });
    let out;
    if (path === "health") out = { state: "ready", mode: "mock", demo: true };
    else if (path === "meta") out = { store_name: "온기한식" };
    else if (path === "step" && body.answer != null && hold) out = await hold;
    else if (path === "step") out = body.answer == null ? START : { state: { node: "DECISION", raw: {}, confirms: {}, mode: "adspend" }, done: true };
    else if (path === "plan") out = plan;
    else if (path === "approve") out = { state: body.state, recorded: [{ draft_id: "mkt-x-promo", kind: "홍보 글", edited: true }] };
    else if (path.startsWith("report")) out = { period: { kind: "weekly" }, demo: true };
    else if (path === "/api/approvals") out = { items: [] };
    else out = {};
    return { ok: true, status: 200, json: async () => out, headers: { get: () => "application/json" } };
  });
}

afterEach(() => { cleanup(); });
const prep = () => {
  Element.prototype.scrollIntoView = () => {};
  window.matchMedia = window.matchMedia || (() => ({ matches: false }));
};

describe("맞춤 마케팅 화면", () => {
  it("시작 모드를 고르면 결과 카드가 나오고, 고친 글을 승인하면 처리 완료에 남는다", async () => {
    const calls = [];
    globalThis.fetch = fakeFetch(calls);
    Element.prototype.scrollIntoView = () => {};
    window.matchMedia = window.matchMedia || (() => ({ matches: false }));
    render(<Marketing />);
    expect(await screen.findByText("무엇을 도와드릴까요?")).toBeTruthy();
    expect(screen.getByText("마케팅 비서 · 온기한식 기준")).toBeTruthy();
    expect(screen.getByText(/시험용 실행/)).toBeTruthy();
    expect(calls.map((c) => c.path).slice(0, 3)).toEqual(["health", "meta", "step"]);

    await act(async () => { fireEvent.click(screen.getByText("광고비 점검")); });
    expect(await screen.findByText("광고비 점검 결과")).toBeTruthy();
    // 예시 고지: 화면 위 띠 한 곳 + 결과 카드 배지 한 곳 ('실제 AI 결과 아님'이 세 번 넘게 나오지 않음)
    expect(screen.getAllByText(/시험용 저장 예시 \(실제 AI 결과 아님\)/).map((e) => e.className)).toEqual(["badge warn"]);
    expect(screen.getAllByText(/실제 AI 결과 아님/).length).toBe(2);
    expect(screen.queryByText(/코드가 계산하고/)).toBeNull();
    expect(screen.getAllByText("손해 광고").length).toBeGreaterThan(0);

    const box = screen.getByLabelText(/홍보 글/);
    fireEvent.change(box, { target: { value: "고친 글" } });
    expect(screen.getByText("고친 글", { selector: ".badge" })).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "승인" })); });
    const sent = calls.find((c) => c.path === "approve").body;
    expect(sent.edited_texts).toEqual({ promo: "고친 글" });
    expect(sent.approval[0].kind).toBe("홍보 글");
    expect(await screen.findByText(/'처리 완료'에 글 1건을 기록했어요/)).toBeTruthy();
    expect(getState().approvedLog.some((x) => x.id === "mkt-x-promo" && x.mkt)).toBe(true);
  });

  it("결과 칸은 새 카드를 읽어 주는 라이브 영역이다 (질문 대화 기록과 따로)", async () => {
    globalThis.fetch = fakeFetch([]);
    prep();
    act(() => setState({ epoch: getState().epoch + 1 }));   // 앞 시험의 대화를 비우고 처음부터
    render(<Marketing />);
    const mode = await screen.findByText("광고비 점검");
    await act(async () => { fireEvent.click(mode); });
    await screen.findByText("광고비 점검 결과");
    const region = document.getElementById("mkt-cards");
    expect(region.getAttribute("aria-live")).toBe("polite");
    expect(region.getAttribute("role")).toBe("log");
    expect(region.getAttribute("aria-relevant")).toBe("additions");
    expect(within(region).getByText("광고비 점검 결과")).toBeTruthy();
    // 질문 대화 기록(role=log)과 겹치지 않는다: 결과 카드는 대화 기록 안에 없고, 대화 기록은 결과 칸 안에 없다
    const log = document.getElementById("mkt-log");
    expect(log.contains(region) || region.contains(log)).toBe(false);
    expect(within(log).queryByText("광고비 점검 결과")).toBeNull();
  });

  it("결과 카드의 '측정' 줄 시계 아이콘은 16px 로 크기가 정해져 있다 (11/21 실사용 QA: 크기 없이 410px 로 커지던 것)", async () => {
    globalThis.fetch = fakeFetch([], null, { ...PLAN, measure: "12/5(토), 같은 불만 리뷰 수 비교" });
    prep();
    act(() => setState({ epoch: getState().epoch + 1 }));
    render(<Marketing />);
    const mode = await screen.findByText("광고비 점검");
    await act(async () => { fireEvent.click(mode); });
    const line = (await screen.findByText("12/5(토), 같은 불만 리뷰 수 비교")).closest(".mkt-measure");
    const icon = line.querySelector("svg");
    expect([icon.getAttribute("width"), icon.getAttribute("height")]).toEqual(["16", "16"]);
  });

  it("결과 카드의 'AI에게 이어서 묻기'는 서랍을 열고 카드에 맞는 질문을 입력칸에 채우기만 한다 (보내지 않음)", async () => {
    const calls = [];
    globalThis.fetch = fakeFetch(calls);
    prep();
    act(() => setState({ epoch: getState().epoch + 1, drawerOpen: false }));   // 앞 시험의 대화를 비우고 처음부터
    render(<Marketing />);
    const mode = await screen.findByText("광고비 점검");
    await act(async () => { fireEvent.click(mode); });
    await screen.findByText("광고비 점검 결과");
    const ask = screen.getByRole("button", { name: "AI에게 이어서 묻기" });
    expect(ask.closest(".mkt-card-actions")).toBeTruthy();
    await act(async () => { fireEvent.click(ask); });
    expect(getState().drawerOpen).toBe(true);
    expect(getChat().draft).toBe("주변에 같은 업종 점포는 몇 개야?");   // 광고비 표 카드
    expect(calls.some((c) => c.path.includes("/api/assistant/messages"))).toBe(false);
  });

  it("시작 모드를 고르면 첫 응답 전에도 고른 모드와 '처음부터'가 바로 보인다", async () => {
    let release;
    const hold = new Promise((r) => { release = r; });
    globalThis.fetch = fakeFetch([], hold);
    prep();
    act(() => setState({ epoch: getState().epoch + 1 }));
    render(<Marketing />);
    expect(await screen.findByText("무엇을 도와드릴까요?")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "처음부터" })).toBeNull();   // 첫 화면(기능 카드)에는 없음
    // 첫 화면의 기능 카드는 흰 패널로 감싸지 않고 바탕 위에 바로 (Figma 06 M1)
    const start = document.querySelector(".mkt-start");
    expect(start.classList.contains("panel")).toBe(false);
    expect(start.querySelector(".feature-grid")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByText("광고비 점검")); });
    // 아직 step 응답 전: 질문 칸 제목이 고른 모드, 내 답 말풍선, '처음부터' 버튼
    const title = document.getElementById("mkt-ask-title");
    expect(title.textContent).toBe("광고비 점검");
    expect(document.querySelector("#mkt-log .mkt-bubble").textContent).toBe("광고비 점검");
    expect(screen.getByRole("button", { name: "처음부터" })).toBeTruthy();
    expect(screen.getByText("승인한 기록은 그대로 남아요")).toBeTruthy();
    expect(screen.queryByText("질문")).toBeNull();   // '질문' 제목 + '질문 n' 배지가 따로 있지 않음
    // 비서 질문은 '마케팅 비서' 이름표가 붙은 상자, 사장님 답은 말풍선 (Figma 06 M1)
    expect([...document.querySelectorAll("#mkt-log .mkt-msg.bot")].map((x) => x.querySelector(".mkt-who").textContent)).toEqual(["마케팅 비서"]);
    await act(async () => { release({ state: { node: "DECISION", raw: {}, confirms: {}, mode: "adspend" }, done: true }); });
    expect(await screen.findByText("광고비 점검 결과")).toBeTruthy();
  });
});

describe("맞춤 마케팅 위 안내 띠", () => {
  it("예시면 한 줄, 화면 맨 위 시험용 띠가 있으면 겹쳐 띄우지 않는다", () => {
    expect(noticeLines({ health: { mode: "mock" }, clearNote: "" })).toEqual([MKT_DEMO_NOTICE]);
    expect(noticeLines({ health: { mode: "mock" }, clearNote: "" }, true)).toEqual([]);
    expect(noticeLines({ health: { mode: "live", demo: false }, demoSeen: false, clearNote: "기록 안내" }, true)).toEqual(["기록 안내"]);
    expect(MKT_DEMO_NOTICE).toMatch(/실제 AI 결과 아님/);
    expect(MKT_DEMO_NOTICE).not.toMatch(/HCX/);
  });
});
