// 맞춤 마케팅 화면이 가짜 서비스로 처음부터 승인까지 도는지 (health → meta → step → 시작 모드 → plan → 승인)
import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { getState } from "../../state/store.js";
import Marketing from "./Marketing.jsx";

const START = { state: { node: "start", raw: {}, confirms: {}, mode: null }, bot_messages: ["무엇을 도와드릴까요?"], done: false,
  options: [{ label: "맞춤 홍보 제안" }, { label: "광고비 점검" }], multi: false, input: null };
const PLAN = { title: "광고비 점검 결과", demo: true, session_id: "s1",
  table: [{ label: "배민", spend_won: 100000, orders: 20, cost_per_order_won: 5000, profit_per_order_won: 3000, verdict: "손해 광고" }],
  steps: [{ step_id: "promo", what: "홍보 글 올리기", generator: "review_promo" }], drafts: { promo: "처음 글" } };

function fakeFetch(calls) {
  return vi.fn(async (url, opts = {}) => {
    const path = String(url).replace("/api/marketing-survey/", "");
    const body = opts.body ? JSON.parse(opts.body) : null;
    calls.push({ path, body });
    let out;
    if (path === "health") out = { state: "ready", mode: "mock", demo: true };
    else if (path === "meta") out = { store_name: "온기한식" };
    else if (path === "step") out = body.answer == null ? START : { state: { node: "DECISION", raw: {}, confirms: {}, mode: "adspend" }, done: true };
    else if (path === "plan") out = PLAN;
    else if (path === "approve") out = { state: body.state, recorded: [{ draft_id: "mkt-x-promo", kind: "홍보 글", edited: true }] };
    else if (path.startsWith("report")) out = { period: { kind: "weekly" }, demo: true };
    else if (path === "/api/approvals") out = { items: [] };
    else out = {};
    return { ok: true, status: 200, json: async () => out, headers: { get: () => "application/json" } };
  });
}

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
    expect(screen.getAllByText(/시험용 저장 예시 \(실제 AI 결과 아님\)/).length).toBeGreaterThan(0);
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
});
