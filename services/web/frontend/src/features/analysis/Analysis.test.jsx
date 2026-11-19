import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { resetStore, setState, getState } from "../../state/store.js";
import { resetMod, getMod } from "./state.js";
import Analysis from "./Analysis.jsx";

const insight = {
  period_start: "2026-10-12", period_end: "2026-11-08", review_count: 40, complaint_count: 12,
  sentiment_counts: { positive: 26, neutral: 2 }, topic_counts: { taste: { positive: 13, negative: 2 }, missing_item: { negative: 3 } },
  top_issue_id: "iss_missing_item",
  groups: [{ issue_id: "iss_missing_item", topic_name: "포장 누락", review_count: 3, is_repeated: true, time_bands: { "17~21시": 3 }, main_time_band: "17~21시",
    evidence: [{ review_id: "rv_1", quote: "안 들어 있었어요" }] }],
  single_complaints: [{ review_id: "rv_8", topic_names: ["위생"], quote: "머리카락" }], data_origin: "synthetic",
};
const json = (body, status = 200) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body), headers: { get: () => "application/json" } });

beforeEach(() => { resetStore(); resetMod(); setState({ insight }); globalThis.URL.createObjectURL = () => "blob:x"; globalThis.URL.revokeObjectURL = () => {}; });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("리뷰 분석 화면", () => {
  it("요약·묶음을 그리고 탭을 바꾼다", () => {
    render(<Analysis />);
    expect(screen.getByText("2026-10-12 ~ 2026-11-08 · 리뷰는 합성 데이터")).toBeTruthy();
    expect(screen.getByText("불만이 많은 주제")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "불만 묶음" }));
    expect(getMod().tab).toBe("issues");
    expect(screen.getByText("포장 누락 3건")).toBeTruthy();
    expect(screen.getByText("묶이지 않은 불만 1건")).toBeTruthy();
  });

  it("navTo 로 탭을 연다", () => {
    setState({ nav: { name: "analysis", sub: "paste", seq: 5 } });
    render(<Analysis />);
    expect(getMod().tab).toBe("paste");
  });

  it("빈 글은 보내지 않고, 붙여넣기 뒤 다시 읽는다", async () => {
    const calls = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((path, opt = {}) => {
      calls.push([path, opt.method || "GET", opt.body]);
      if (path === "/api/reviews") return json({ review: { review_id: "rv_p1", text: "식었어요" }, classification: { sentiment: "negative", topics: [{ topic: "temperature", polarity: "negative" }] }, joined_issues: ["iss_missing_item"] }, 201);
      if (path === "/api/cards") return json({ cards: [] });
      if (path === "/api/approvals") return json({ items: [] });
      return json(path === "/api/insight" ? insight : {});
    });
    render(<Analysis />);
    fireEvent.click(screen.getByRole("tab", { name: "리뷰 넣기" }));
    fireEvent.click(screen.getByRole("button", { name: "분류하기" }));
    expect(screen.getByText("리뷰 글을 넣어 주세요.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/리뷰 글/), { target: { value: " 식었어요 " } });
    fireEvent.change(screen.getByLabelText("별점"), { target: { value: "2" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "분류하기" })); });
    await waitFor(() => expect(screen.getByText("붙여 넣었어요. 홈 숫자, 추천 카드, 요약, 불만 묶음에 반영했어요.")).toBeTruthy());
    expect(calls[0]).toEqual(["/api/reviews", "POST", JSON.stringify({ text: "식었어요", rating: 2 })]);
    expect(calls.map((c) => c[0])).toEqual(["/api/reviews", "/api/briefing", "/api/cards", "/api/insight", "/api/approvals"]);
    expect(getState().joined).toEqual(["iss_missing_item"]);
    expect(screen.getByText(/불만 묶음에 들어갔어요/).textContent).toContain("포장 누락");   // 들어간 묶음 이름
  });

  it("캡처: 후보를 읽고 고른 것만 source=capture 로 저장, 오류는 칸 안에만", async () => {
    const calls = [];
    let fail = true;
    vi.spyOn(globalThis, "fetch").mockImplementation((path, opt = {}) => {
      calls.push([path, opt.body]);
      if (path === "/api/care/reviews/capture") return fail ? json({ error: { message: "리뷰를 찾지 못했어요", state: "invalid" } }, 422)
        : json({ candidates: [{ text: "맛있어요", rating: 5 }, { text: "같은 글", rating: 3, duplicate: true }], demo: true, warnings: ["예시"] });
      if (path === "/api/reviews") return json({ joined_issues: [] }, 201);
      if (path === "/api/cards") return json({ cards: [] });
      if (path === "/api/approvals") return json({ items: [] });
      return json(path === "/api/insight" ? insight : {});
    });
    const { container } = render(<Analysis />);
    fireEvent.click(screen.getByRole("tab", { name: "리뷰 넣기" }));
    const input = container.querySelector("#cap-file");
    fireEvent.change(input, { target: { files: [new File(["x"], "a.gif", { type: "image/gif" })] } });
    expect(screen.getByRole("alert").textContent).toBe("png·jpg·webp 이미지만 올릴 수 있어요.");
    fireEvent.change(input, { target: { files: [new File(["x"], "a.png", { type: "image/png" })] } });
    expect(screen.getByText("a.png · 1KB")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "캡처 읽기" })); });
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("리뷰를 찾지 못했어요"));
    expect(getState().alert).toBe("");
    fail = false;
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "캡처 읽기" })); });
    await waitFor(() => expect(screen.getByText("예시 결과 — 이미지를 실제로 읽지 않았어요")).toBeTruthy());
    expect(screen.getByText("1건 고름")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "선택한 리뷰 저장" })); });
    await waitFor(() => expect(screen.getByText("1건 저장했어요. 요약·불만 묶음·홈 숫자·추천 카드에 반영했어요.")).toBeTruthy());
    expect(calls.find((c) => c[0] === "/api/reviews")[1]).toBe(JSON.stringify({ text: "맛있어요", rating: 5, source: "capture" }));
    expect(screen.getByText("저장함")).toBeTruthy();
  });
});
