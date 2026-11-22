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
    const { container } = render(<Analysis />);
    expect(screen.getByText("2026-10-12 ~ 2026-11-08 · 리뷰는 합성 데이터")).toBeTruthy();
    // 머리말 설명 없이 제목만 (합성 데이터 고지는 기간 줄 한 곳)
    expect(container.querySelector(".page-head .ph-sub")).toBeNull();
    expect(screen.getByText("리뷰 하나에 주제가 여럿이면 주제마다 1건씩 들어가요.")).toBeTruthy();
    expect(screen.getByText("불만이 많은 주제")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "불만 묶음" }));
    expect(getMod().tab).toBe("issues");
    expect(screen.getByText("포장 누락 3건")).toBeTruthy();
    expect(screen.getByText("묶이지 않은 불만 1건")).toBeTruthy();
    expect(screen.queryByText("어느 묶음에도 들지 않은 불만이에요.")).toBeNull();   // 제목을 되풀이하던 줄
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
      if (path === "/api/reviews") return json({ review: { review_id: "rv_p1", text: "식었어요", pii_masked: true }, classification: { sentiment: "negative", method: "rules", topics: [{ topic: "temperature", polarity: "negative" }] }, joined_issues: ["iss_missing_item"] }, 201);
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
    await waitFor(() => expect(screen.getByText("리뷰를 저장하고 분석 결과를 갱신했어요.")).toBeTruthy());
    expect(calls[0]).toEqual(["/api/reviews", "POST", JSON.stringify({ text: "식었어요", rating: 2 })]);
    expect(calls.map((c) => c[0])).toEqual(["/api/reviews", "/api/briefing", "/api/cards", "/api/insight", "/api/approvals"]);
    expect(getState().joined).toEqual(["iss_missing_item"]);
    expect(screen.getByText(/불만 묶음에 들어갔어요/).textContent).toContain("포장 누락");   // 들어간 묶음 이름
    // 분류 방식과 개인정보 가림은 배지로. 내부 id(rv_p1)·방식 이름(rules)·'검증:' 같은 내부 표현은 보이지 않음
    const meta = document.querySelector(".an-result-meta");
    expect([...meta.querySelectorAll(".badge")].map((b) => b.textContent)).toEqual(["규칙 분류 (AI 아님)", "개인정보 가림"]);
    expect(document.body.textContent).not.toContain("rv_p1");
    expect(document.body.textContent).not.toContain("분류 방식");
    expect(document.body.textContent).not.toContain("검증:");
    // 채널 고르기는 그대로 (안 고르면 본문에 넣지 않음)
    expect(screen.getByLabelText("채널").tagName).toBe("SELECT");
  });

  it("캡처: 후보를 읽고 고른 것만 source=capture 로 저장, 오류는 칸 안에만", async () => {
    const calls = [];
    let fail = true;
    vi.spyOn(globalThis, "fetch").mockImplementation((path, opt = {}) => {
      calls.push([path, opt.body]);
      if (path === "/api/care/reviews/capture") return fail ? json({ error: { message: "리뷰를 찾지 못했어요", state: "invalid" } }, 422)
        : json({ candidates: [{ text: "맛있어요", rating: 5, pii_masked: true }, { text: "같은 글", rating: 3, duplicate: true }], demo: true, warnings: ["예시"] });
      if (path === "/api/reviews") return json({ joined_issues: [] }, 201);
      if (path === "/api/cards") return json({ cards: [] });
      if (path === "/api/approvals") return json({ items: [] });
      return json(path === "/api/insight" ? insight : {});
    });
    const { container } = render(<Analysis />);
    fireEvent.click(screen.getByRole("tab", { name: "리뷰 넣기" }));
    // 올리기 전 설명은 한 줄
    expect(screen.getByText("AI가 배달앱 리뷰 캡처에서 글과 별점을 읽어 와요.")).toBeTruthy();
    expect(screen.queryByText(/바로 저장하지 않고/)).toBeNull();
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
    expect(screen.queryByText(/키가 없거나/)).toBeNull();
    // 확인 경고는 후보 목록 바로 위에 남는다 (상태 줄에는 같은 안내를 되풀이하지 않음)
    const warn = container.querySelector(".an-cap-star");
    const list = screen.getByRole("list", { name: "옮겨 적은 리뷰 후보" });
    expect(warn.textContent).toContain("저장하기 전에 별점과 글이 캡처와 같은지 확인해 주세요.");
    expect(warn.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(container.querySelector(".an-cap-status").textContent).toBe("후보 2건 · 예시 결과");
    expect(screen.getByText("개인정보 가림")).toBeTruthy();   // 후보 1의 개인정보 가림 배지
    expect(screen.getByText("1건 고름")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "선택한 리뷰 저장" })); });
    await waitFor(() => expect(screen.getByText("리뷰 1건을 저장하고 분석 결과를 갱신했어요.")).toBeTruthy());
    expect(calls.find((c) => c[0] === "/api/reviews")[1]).toBe(JSON.stringify({ text: "맛있어요", rating: 5, source: "capture" }));
    expect(screen.getByText("저장함")).toBeTruthy();
  });

  // Figma 06 C1·C2 배치 (11/20)
  it("리뷰 넣기: 붙여넣기 | 캡처로 넣기 두 칸, 분류 결과는 붙여넣기 칸 안 (분류 전에는 없음), 캡처는 점선 상자 안에서 파일 고르기", () => {
    const { container } = render(<Analysis />);
    fireEvent.click(screen.getByRole("tab", { name: "리뷰 넣기" }));
    const grid = container.querySelector(".an-paste-grid");
    expect([...grid.children].map((x) => x.querySelector("h2").textContent)).toEqual(["붙여넣기", "캡처로 넣기"]);
    expect(container.querySelector(".an-result")).toBeNull();
    expect(screen.queryByText("분류 결과")).toBeNull();
    // 개인정보 안내는 글 칸 설명으로 이어지고 (화면에는 버튼 아래 한 줄)
    expect(document.getElementById("paste-text").getAttribute("aria-describedby")).toBe("paste-pii");
    const drop = container.querySelector(".an-cap .an-cap-drop");
    expect(drop.textContent).toContain("AI가 배달앱 리뷰 캡처에서 글과 별점을 읽어 와요.");
    expect(drop.querySelector("button").textContent).toBe("파일 고르기");
    expect(screen.getByRole("button", { name: "캡처 읽기" }).closest(".an-cap-drop")).toBeNull();
    // 탭 줄과 요약 패널 이름
    fireEvent.click(screen.getByRole("tab", { name: "요약" }));
    expect(screen.getByRole("region", { name: "칭찬·불만 주제" })).toBeTruthy();
  });

  // 11/21 실사용 QA
  it("B-4·B-5 요약: 주제 칸은 리뷰 속 문장 기준이라고 밝히고(불만 리뷰 속 칭찬도 셈), 8개 뒤 주제는 '그 밖' 한 줄", () => {
    // 리뷰 4건 모두 부정인데 '맛은 괜찮았다' 문장이 있어 칭찬 주제 맛 1건 (QA 재현 모양) + 불만 주제 10개
    const neg = Object.fromEntries(["texture", "taste", "portion", "price", "delivery_time", "temperature", "packaging", "missing_item", "service", "hygiene"]
      .map((t, i) => [t, { negative: 10 - i, positive: t === "taste" ? 1 : 0 }]));
    setState({ insight: { ...insight, review_count: 4, complaint_count: 4, sentiment_counts: { negative: 4, positive: 0, neutral: 0 }, topic_counts: neg, groups: [] } });
    const { container } = render(<Analysis />);
    const panel = screen.getByRole("region", { name: "칭찬·불만 주제" });
    expect(panel.querySelector(".panel-head .sub").textContent).toBe("리뷰 속 문장 기준");
    const [negCol, posCol] = container.querySelectorAll(".an-topics");
    expect(posCol.querySelector(".an-topic-note").textContent).toBe("불만 리뷰 속 칭찬 문장도 셈");
    expect(posCol.textContent).toContain("맛");
    expect(negCol.querySelectorAll(".an-topic-list li")).toHaveLength(8);
    expect(negCol.querySelector(".an-topic-rest").textContent).toBe("그 밖 2개 주제: 응대 2 · 위생 1");
    expect(posCol.querySelector(".an-topic-rest")).toBeNull();
    // 타일 숫자는 그대로 (리뷰 단위 긍정 0), 반복 0건은 기준을 부제로
    expect(container.querySelector(".an-tiles").textContent).toContain("긍정 0");
    expect(container.querySelector(".an-tiles").textContent).toContain("같은 불만 3건부터");
  });

  it("B-3 붙여넣기 결과·불만 묶음 탭의 기준 문장이 같다", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((path) => {
      if (path === "/api/reviews") return json({ review: { review_id: "rv_p1", text: "식었어요" }, classification: { sentiment: "negative", topics: [{ topic: "temperature", polarity: "negative" }] }, joined_issues: [] }, 201);
      if (path === "/api/cards") return json({ cards: [] });
      if (path === "/api/approvals") return json({ items: [] });
      return json(path === "/api/insight" ? insight : {});
    });
    render(<Analysis />);
    fireEvent.click(screen.getByRole("tab", { name: "리뷰 넣기" }));
    fireEvent.change(screen.getByLabelText(/리뷰 글/), { target: { value: "식었어요" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "분류하기" })); });
    await waitFor(() => expect(screen.getByText(/아직 어느 묶음에도 들지 않았어요/)).toBeTruthy());
    const rule = "같은 불만이 2건 이상이면 묶음, 3건 이상이면 반복으로 봐요";
    expect(screen.getByText(/아직 어느 묶음에도 들지 않았어요/).textContent).toBe(`→ 아직 어느 묶음에도 들지 않았어요 (${rule}).`);
    fireEvent.click(screen.getByRole("tab", { name: "불만 묶음" }));
    expect(screen.getByText(`${rule}.`)).toBeTruthy();
  });

  // 11/22 실사용 QA D1·D2
  it("D1 불만 묶음 흐름: 칸마다 단위(건·개)와 무엇을 셌는지, 묶음 합계가 불만 리뷰 수와 다를 수 있다는 한 줄", () => {
    const g2 = { issue_id: "iss_temperature", topic_name: "음식 온도", review_count: 2, is_repeated: false, time_bands: {}, main_time_band: null,
      evidence: [{ review_id: "rv_1", quote: "식었어요" }, { review_id: "rv_2", quote: "미지근" }] };
    setState({ insight: { ...insight, groups: [...insight.groups, g2] } });
    const { container } = render(<Analysis />);
    fireEvent.click(screen.getByRole("tab", { name: "불만 묶음" }));
    const boxes = [...container.querySelectorAll(".an-funnel .an-fbox")].map((b) => [b.querySelector(".an-fn").textContent, b.querySelector(".small").textContent]);
    expect(boxes).toEqual([["40건", "리뷰"], ["12건", "불만 리뷰"], ["2개", "묶음 (반복 1개)"], ["1건", "묶이지 않은 불만"]]);
    expect(screen.getByText("리뷰 하나에 불만 주제가 둘 이상이면 묶음마다 들어가요. 그래서 묶음의 건수를 더하면 불만 리뷰 수보다 많을 수 있어요.")).toBeTruthy();
    expect(screen.getByText("같은 불만이 2건 이상이면 묶음, 3건 이상이면 반복으로 봐요.")).toBeTruthy();
  });

  it("D2 인용 옆에 내부 리뷰 id 대신 채널 · 날짜 (id 는 data-review-id 에만)", () => {
    setState({
      reviewsById: { rv_1: { review_id: "rv_1", channel: "배민", created_at: "2026-11-03T18:10:00+09:00" } },
      insight: { ...insight, single_complaints: [...insight.single_complaints,
        { review_id: "rv_a2cf0aaafdf9c_paste_002", topic_names: ["양"], quote: "양이 적어요", created_at: "2026-10-30T12:00:00+09:00", channel: "yogiyo" }] },
    });
    const { container } = render(<Analysis />);
    fireEvent.click(screen.getByRole("tab", { name: "불만 묶음" }));
    const text = container.textContent;
    expect(text).not.toContain("rv_1");
    expect(text).not.toContain("rv_8");
    expect(text).not.toContain("rv_a2cf0aaafdf9c_paste_002");
    const quote = container.querySelector('.an-group [data-review-id="rv_1"]');
    expect(quote.textContent).toBe("“안 들어 있었어요” 배민 · 11-03");
    // 스토어에 없는 묶이지 않은 불만: 그 칸의 채널·날짜, 아무 정보도 없으면 꼬리 없이
    expect(container.querySelector('[data-review-id="rv_a2cf0aaafdf9c_paste_002"]').textContent).toBe("양: “양이 적어요” 요기요 · 10-30");
    const bare = container.querySelector('[data-review-id="rv_8"]');
    expect(bare.textContent).toBe("위생: “머리카락”");
    expect(bare.querySelector(".an-qmeta")).toBeNull();
    expect(container.querySelector(".an-rid")).toBeNull();
  });

  it("D1 요약 탭 '반복 불만' 타일: 숫자는 묶음 건수 합 그대로, 부제에 묶음 수와 합계 기준", () => {
    const g = (id, name, ids) => ({ issue_id: id, topic_name: name, review_count: ids.length, is_repeated: true, review_ids: ids, time_bands: {}, evidence: [] });
    setState({ insight: { ...insight, complaint_count: 5, groups: [g("iss_a", "배달 시간", ["r1", "r2", "r3", "r4"]), g("iss_b", "음식 온도", ["r1", "r2", "r5"])] } });
    const { container } = render(<Analysis />);
    const tile = [...container.querySelectorAll(".an-tiles .tile")].find((t) => t.querySelector(".tile-label").textContent === "반복 불만");
    expect(tile.querySelector(".num").textContent).toBe("7건");
    expect(tile.querySelector(".tile-sub").textContent).toBe("묶음 2개 합계 · 겹친 리뷰 빼면 5건 · 배달 시간, 음식 온도");
  });

  it("리뷰 0건인 새 가게: 기간 대신 짧은 안내, 타일·주제·묶음이 깨지지 않는다", () => {
    setState({ me: null, insight: { period_start: null, period_end: null, review_count: 0, complaint_count: 0, sentiment_counts: {},
      topic_counts: {}, group_count: 0, single_complaint_count: 0, top_issue_id: null, groups: [], single_complaints: [], data_origin: null } });
    const { container } = render(<Analysis />);
    expect(container.querySelector(".an-period").textContent).toBe("아직 들어온 리뷰가 없어요.");
    expect(container.textContent).not.toMatch(/undefined|null|NaN|1일/);
    fireEvent.click(screen.getByRole("tab", { name: "불만 묶음" }));
    expect(screen.getByText("묶인 불만이 없어요.")).toBeTruthy();
  });
});
