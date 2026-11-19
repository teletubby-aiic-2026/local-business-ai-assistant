// 네 화면이 그려지고 주요 동작(만들기·고치기·승인·처음부터 다시)이 원본 순서대로 API 를 부르는지
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import { resetStore, setState, getState } from "../../state/store.js";
import { resetFlow } from "./state.js";
import Home from "./Home.jsx";
import Cards from "./Cards.jsx";
import Draft from "./Draft.jsx";
import Done from "./Done.jsx";

const briefing = {
  store: { name: "온기한식" }, period: { start: "2026-11-12", end: "2026-11-18" },
  counts: { review_count: 20, complaint_count: 3 }, top_issue_id: "i1", pasted: [], single_complaints: [],
  groups: [{ issue_id: "i1", topic_name: "포장 누락", review_count: 2, is_repeated: true, main_time_band: "17~21시",
    reviews: [{ review_id: "r1", text: "밥이 빠졌어요", rating: 2, created_at: "2026-11-12T18:10:00+09:00" }, { review_id: "r2", text: "수저 없음", created_at: "2026-11-13T19:00:00+09:00" }] }],
  snapshots: [],
};
const cardA = {
  title: "포장 누락을 막아요", reason_source: "규칙", problems: [],
  card: { card_id: "card_a", kind: "complaint", reason_text: "포장 누락 2건", review_ids: ["r1", "r2"] },
  evidence: [{ type: "review", id: "r1", text: "밥이 빠졌어요" }, { type: "review", id: "r2", text: "수저 없음" }],
  measures: { options: [{ id: "M1", text: "주문서 대조" }, { id: "M2", text: "수저 확인" }], default: ["M1"] },
};
const runA = {
  card_id: "card_a", source: "seed", chosen_measures: [{ id: "M1", text: "주문서 대조" }],
  drafts: [
    { draft_id: "d1", generator: "reply_draft", target_review_id: "r1", text: "답글 하나" },
    { draft_id: "d2", generator: "prevention_notice", target_review_id: null, text: "안내문", c7_flags: ["확인할 것"] },
  ],
};

let calls;
function mockFetch(handler) {
  calls = [];
  globalThis.fetch = vi.fn(async (path, opt = {}) => {
    calls.push({ path, method: opt.method || "GET", body: opt.body });
    const body = handler(path, opt);
    return { ok: true, status: 200, json: async () => body, headers: { get: () => "application/json" } };
  });
}

beforeEach(() => {
  resetStore(); resetFlow();
  window.location.hash = "#/today";
  window.scrollTo = () => {};
  setState({ booted: true, briefing, reviewsById: { r1: briefing.groups[0].reviews[0], r2: briefing.groups[0].reviews[1] }, cards: [cardA], health: { mode: "mock" } });
});
afterEach(() => cleanup());

describe("홈", () => {
  it("제목·핵심 문제·할 일", () => {
    render(<Home />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("사장님, 오늘 처리할 일 2가지");
    expect(screen.getByText("포장 누락 2건 반복 · 17~21시에 몰림", { selector: "strong" })).toBeTruthy();
    expect(screen.getByText("포장·주문 안내문 승인")).toBeTruthy();
    expect(screen.getByRole("img", { name: /18시 1건/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "무엇을 할까요?" }).disabled).toBe(false);
  });
  it("처음 불러오기 실패", () => {
    setState({ cards: [], bootError: "요청 실패 (500)" });
    render(<Home />);
    expect(screen.getByText("불러오지 못했어요", { selector: "li" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "불러오지 못했어요" }).disabled).toBe(true);
  });
});

describe("카드 → 초안 → 승인 → 완료 → 처음부터 다시", () => {
  it("원본 순서대로 부른다", async () => {
    mockFetch((path, opt) => {
      if (path.includes("/run")) return runA;
      if (path.includes("/approve")) { const b = JSON.parse(opt.body); return { edited: b.text !== b.original, approved_at: "2026-11-19T21:00:05+09:00", text: b.text }; }
      if (path === "/api/approvals" && opt.method === "DELETE") return { deleted: 2, marketing_cleared: false };
      if (path === "/api/approvals") return { items: [] };
      return {};
    });
    render(<Cards />);
    fireEvent.click(screen.getByLabelText(/수저 확인/));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "포장·주문 안내문·답글 만들기" })); });
    expect(calls[0]).toMatchObject({ path: "/api/cards/card_a/run", method: "POST", body: JSON.stringify({ measures: ["M1", "M2"] }) });
    expect(window.location.hash).toBe("#/draft");
    cleanup();

    render(<Draft />);
    // 안내문이 먼저, 확인 필요
    const box = screen.getByLabelText(/AI 포장·주문 안내문 초안/);
    expect(box.value).toBe("안내문");
    expect(screen.getByText("확인 필요 1")).toBeTruthy();
    fireEvent.change(box, { target: { value: "안내문 고침" } });
    expect(getState().pending.d2).toBe("안내문 고침");
    // 고친 글이 있으면 카드 전체 다시 만들기는 한 번 더 눌러야
    fireEvent.click(screen.getByRole("button", { name: "카드 전체 다시 만들기" }));
    expect(screen.getByRole("button", { name: "한 번 더 눌러 실행" })).toBeTruthy();
    expect(calls).toHaveLength(1);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "승인" })); });
    expect(JSON.parse(calls[1].body)).toEqual({ text: "안내문 고침", original: "안내문" });
    // 다음 미승인 글(답글)로
    expect(screen.getByLabelText(/AI 답글 초안/).value).toBe("답글 하나");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "승인" })); });
    expect(JSON.parse(calls[2].body)).toEqual({ text: "답글 하나", original: "답글 하나", kind: "reply_draft", review_id: "r1" });
    expect(window.location.hash).toBe("#/done");
    expect(getState().approvedLog.map((x) => [x.id, x.edited])).toEqual([["d2", true], ["d1", false]]);
    cleanup();

    await act(async () => { render(<Done />); });
    expect(screen.getByText("고쳐서 승인")).toBeTruthy();
    expect(screen.getByText("주문서 대조")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "처음부터 다시" })); });
    expect(calls.some((c) => c.path === "/api/approvals" && c.method === "DELETE")).toBe(true);
    expect(getState().results).toEqual({});
    expect(getState().mktResetSeq).toBe(1);
    expect(getState().mktCleared).toBe(false);
    expect(window.location.hash).toBe("#/today");
  });
});
