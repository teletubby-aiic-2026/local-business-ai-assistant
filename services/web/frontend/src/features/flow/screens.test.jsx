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
    // 11/21 QA B-7: 어디로 가는지 버튼에 (Figma 06 B1)
    expect(screen.getByRole("button", { name: "무엇을 할까요? (추천 카드 보기)" }).disabled).toBe(false);
  });
  it("시작 버튼 옆 보조 문구 없이, 상권 칸 범위는 칩으로 (상권명 · 업종 · 시간대)", () => {
    setState({ briefing: { ...briefing, snapshots: [{ snapshot_id: "s1", value: -19.31, unit: "%", area_name: "장승배기역 4번",
      metric_name: "저녁 시간대(17~24시) 추정매출 전년 동기 대비 변화율 · 두 분기 공통 업종" }] } });
    const { container } = render(<Home />);
    expect(screen.queryByText(/추천 카드 2장/)).toBeNull();
    expect(container.querySelector(".flow-todo-foot").textContent).toBe("무엇을 할까요? (추천 카드 보기)");
    expect(screen.getByText("-19.31%")).toBeTruthy();
    expect([...container.querySelectorAll(".flow-scope-chip")].map((x) => x.textContent)).toEqual(["장승배기역 4번", "공통 업종", "17~24시"]);
    expect(screen.getByText("전년 같은 분기 대비")).toBeTruthy();
    // 서랍 숫자(한 업종 하루 전체)와 다르다는 설명은 마우스를 올리면 (칸 title)
    expect(container.querySelector(".tile.tint-sage").getAttribute("title")).toContain("하루 전체 매출이 아니에요");
  });
  it("처음 불러오기 실패", () => {
    setState({ cards: [], bootError: "요청 실패 (500)" });
    render(<Home />);
    expect(screen.getByText("불러오지 못했어요", { selector: "li" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "불러오지 못했어요" }).disabled).toBe(true);
  });
  it("브리핑을 못 받으면(등록 가게를 리뷰 분석이 아직 모를 때 등) 핵심 문제·기간 줄이 '정리하고 있어요'·'불러오는 중'으로 남지 않음", () => {
    setState({ cards: [], briefing: null, bootError: "리뷰 분석 서비스 오류 404" });
    const { container } = render(<Home />);
    expect(screen.getByText("리뷰를 불러오지 못했어요", { selector: "strong" })).toBeTruthy();
    expect(container.querySelector(".flow-eyebrow").textContent).toBe("밤 11시 브리핑");
  });
});

describe("추천 카드", () => {
  it("머리 설명 한 줄(Figma 06 B2), 근거 보기는 리뷰·지표 출처와 원본 링크만 (검사기 표현 없음), 시험용 수칙 고지는 한 줄", () => {
    setState({ cards: [{ ...cardA, reason_source: "HCX-005 (검사기 통과)", problems: [{ type: "too_long" }],
      evidence: [...cardA.evidence, { type: "snapshot", id: "s1", text: "저녁 매출 -19.31%", basis: "서울시 상권분석서비스 2026년 2분기 · https://golmok.seoul.go.kr/x" }] }] });
    const { container } = render(<Cards />);
    // 11/21 QA B-7: 제목 아래 설명은 그림대로 두되, 시험용 실행이라 'AI가 글을 써요'라고 하지 않는다
    expect(container.querySelector(".page-head .ph-sub").textContent).toBe("오늘 리뷰와 상권 자료로 고른 추천 1가지예요. 고르면 예시 글을 보여 드려요.");
    const more = container.querySelector(".flow-more");
    expect(more.textContent).not.toMatch(/검사기|이유 문장:|HCX/);
    expect(more.textContent).toContain("리뷰 r1: “밥이 빠졌어요”");
    expect(more.textContent).toContain("저녁 매출 -19.31% · 서울시 상권분석서비스 2026년 2분기");
    expect(more.textContent).toContain("카드 설명 글은 AI가 썼어요.");   // AI 생성 여부는 남긴다
    const link = more.querySelector("a");
    expect(link.textContent).toBe("원본");
    expect(link.getAttribute("href")).toBe("https://golmok.seoul.go.kr/x");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(container.querySelectorAll(".flow-measures p")).toHaveLength(1);
    expect(screen.getByText("시험용 실행이라 고른 수칙이 글에 반영되지 않아요.")).toBeTruthy();
  });
  it("고정 문장 카드는 AI 표시가 없다", () => {
    const { container } = render(<Cards />);
    expect(container.querySelector(".flow-more").textContent).not.toContain("AI가 썼어요");
  });
});

describe("승인할 글", () => {
  it("진행은 맨 위 진행줄 한 곳, 아래는 '초안 목록' + 글마다 상태 배지", async () => {
    mockFetch((path, opt) => {
      if (path.includes("/approve")) { const b = JSON.parse(opt.body); return { edited: false, approved_at: "2026-11-19T21:00:05+09:00", text: b.text }; }
      return {};
    });
    setState({ results: { card_a: runA }, current: "card_a" });
    render(<Draft />);
    expect(screen.getAllByText(/^승인 \d+ \/ \d+$/)).toHaveLength(1);
    expect(screen.getByText("승인 0 / 2")).toBeTruthy();
    expect(screen.queryByText("남은 글")).toBeNull();
    expect(screen.queryByText(/승인 안 한 글/)).toBeNull();
    const rows = () => [...screen.getByRole("list", { name: "초안 목록" }).querySelectorAll("li")]
      .map((li) => [li.querySelector(".flow-list-name").textContent, [...li.querySelectorAll(".badge")].map((b) => b.textContent)]);
    // 11/21 QA B-6: 점검 통과도 칩으로, 답글은 원 리뷰 첫 줄을 이름 아래에 (공지는 대상 리뷰가 없어 줄 없음)
    expect(rows()).toEqual([["1. 포장·주문 안내문", ["승인 대기", "확인 필요"]], ["2. 답글", ["승인 대기", "점검 통과"]]]);
    expect([...document.querySelectorAll(".flow-list li")].map((li) => li.querySelector(".flow-list-target")?.textContent ?? null))
      .toEqual([null, "“밥이 빠졌어요”"]);
    // 시험용 저장 예시: 수칙 줄은 짧게, 출처 배지는 머리에 그대로
    expect(screen.getByText(/예시 글이라 반영되지 않아요/)).toBeTruthy();
    expect(screen.getByText("시험용 저장 예시 (실제 AI 결과 아님)")).toBeTruthy();
    // '다시 만들기'는 공통 Button 부품 (ref 로 포커스를 되돌림)
    expect(screen.getByRole("button", { name: "다시 만들기" }).className).toBe("btn text");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "승인" })); });
    expect(screen.getByText("승인 1 / 2")).toBeTruthy();
    expect(rows()[0]).toEqual(["1. 포장·주문 안내문", ["승인 완료"]]);
  });
  it("서버의 글 출처 설명은 접어 두고, 답글을 못 만든 붙여넣은 리뷰는 보인다", () => {
    setState({ results: { card_a: { ...runA, source_note: "김수현 저장본(c6_cache_best.json)", pasted_reply_skipped: [{ review_id: "rv_p1", reason: "같은 글의 저장 예시가 없음" }] } }, current: "card_a" });
    const { container } = render(<Draft />);
    expect(container.querySelector("details.flow-more summary").textContent).toBe("글 출처");
    expect(container.querySelector("details.flow-more").textContent).toContain("김수현 저장본");
    expect(screen.getByText("붙여넣은 불만 리뷰 1건은 답글을 만들지 않았어요 (같은 글의 저장 예시가 없음).")).toBeTruthy();
  });
  it("만든 글이 없으면 빈 안내와 버튼 하나", () => {
    render(<Draft />);
    expect(screen.getByText("아직 만든 글이 없어요.")).toBeTruthy();
    expect(screen.queryByText("추천 카드에서 카드를 하나 골라 주세요.")).toBeNull();
    expect(screen.getByRole("link", { name: "추천 카드 보기" }).getAttribute("href")).toBe("#/cards");
  });
});

describe("처리 완료", () => {
  it("'고쳐서 승인' 칸은 비율, 만든 글 대비 진행은 목록 머리 한 곳, 지우는 버튼만 경고", async () => {
    mockFetch(() => ({ items: [] }));
    setState({ results: { card_a: runA }, approved: new Set(["d1", "d2"]), approvedLog: [
      { id: "d2", edited: true, kind: "prevention_notice", name: "포장·주문 안내문", card: "포장 누락을 막아요", at: "2026-11-19T21:00:05+09:00", text: "안내문 고침" },
      { id: "d1", edited: false, kind: "reply_draft", name: "답글", card: "포장 누락을 막아요", at: "2026-11-19T21:01:00+09:00", text: "답글 하나" },
    ] });
    await act(async () => { render(<Done />); });
    expect(screen.queryByText("사장님이 고친 글")).toBeNull();
    expect(screen.getByText("승인한 글 중 50%")).toBeTruthy();
    expect(screen.getByText("만든 글 2개 중 2개 승인")).toBeTruthy();
    expect(screen.queryByText(/승인한 글 2개 \/ 만든 글/)).toBeNull();
    expect(screen.getByText("게시는 복사해서 직접 올려요.")).toBeTruthy();
    expect(screen.queryByText(/‘홈으로’는/)).toBeNull();
    expect(screen.getByRole("button", { name: "처음부터 다시" }).getAttribute("aria-describedby")).toBe("flow-restart-note");
    expect(document.getElementById("flow-restart-note").textContent).toContain("되돌릴 수 없어요");
    expect(screen.getByText("예시 글이라 안내문에 반영되지 않았어요.")).toBeTruthy();
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
    expect(screen.getByText("한 번 더 누르면 승인했거나 고친 글 1개까지 모두 새 글로 바뀌어요.")).toBeTruthy();
    expect(calls).toHaveLength(1);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "승인" })); });
    // 11/22: 글 종류·카드는 늘 보낸다 (초안을 만든 WAS 와 승인을 받은 WAS 가 달라도 서버 기록에 종류가 남게). 리뷰 id 는 답글만
    expect(JSON.parse(calls[1].body)).toEqual({ text: "안내문 고침", original: "안내문", kind: "prevention_notice", card_id: "card_a" });
    // 다음 미승인 글(답글)로
    expect(screen.getByLabelText(/AI 답글 초안/).value).toBe("답글 하나");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "승인" })); });
    expect(JSON.parse(calls[2].body)).toEqual({ text: "답글 하나", original: "답글 하나", kind: "reply_draft", card_id: "card_a", review_id: "r1" });
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

// Figma 06 설계 기준 화면(B1~B4)에 맞춘 배치를 고정한다 (11/20). 글자보다 구역의 순서·자리를 본다
describe("기준 화면 배치 (Figma 06 B1~B4)", () => {
  const order = (a, b) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

  it("홈: 오늘 할 일(넓은 칸) 다음 담당 비서 현황, 비서마다 첫 글자 동그라미, 할 일 줄은 상자 + 오른쪽 버튼 모양, 묻기 줄", () => {
    const { container } = render(<Home />);
    const dash = container.querySelector(".flow-dash");
    expect([...dash.children].map((x) => x.querySelector("h2").textContent)).toEqual(["오늘 할 일", "담당 비서 현황"]);
    expect([...container.querySelectorAll(".flow-staff-av")].map((x) => x.textContent)).toEqual(["데", "고", "마", "상"]);
    const todo = container.querySelector(".flow-todo-item");
    expect(todo.lastElementChild.className).toBe("flow-todo-st");
    expect(todo.lastElementChild.textContent).toBe("만들기");
    // 오늘 할 일 · 비서 → 차트 두 칸(시간 · 주제) → 묻기 줄 순서
    const charts = container.querySelector(".flow-charts");
    expect(order(dash, charts)).toBe(true);
    expect([...charts.children].map((x) => x.querySelector("h2").textContent)).toEqual(["불만 리뷰가 몰린 시간", "주제별 불만"]);
    expect(screen.getByText("상위 1개")).toBeTruthy();
    const ask = screen.getByRole("button", { name: /AI에게 묻기 · 예\)/ });
    expect(order(charts, ask)).toBe(true);
    expect(ask.querySelector(".flow-ask-go").textContent).toBe("묻기");
    // 오늘의 핵심 문제는 이름표 + 굵은 한 줄
    expect(container.querySelector(".flow-hero .flow-hero-label").textContent).toBe("오늘의 핵심 문제");
  });

  it("홈: 리뷰 0건이면 빈 안내 아래 다음에 할 일 두 개 ([리뷰 넣기] → 리뷰 분석의 리뷰 넣기 탭, [상권 분석 보기])", () => {
    setState({ cards: [], briefing: { store: { name: "새 가게" }, period: { start: null, end: null },
      counts: { review_count: 0, complaint_count: 0 }, top_issue_id: null, groups: [], single_complaints: [], pasted: [], snapshots: [] } });
    const { container } = render(<Home />);
    const foot = container.querySelector(".flow-todo-foot");
    expect([...foot.querySelectorAll("button")].map((x) => x.textContent)).toEqual(["리뷰 넣기", "상권 분석 보기"]);
    expect(screen.queryByRole("button", { name: /무엇을 할까요/ })).toBeNull();
    expect(container.querySelector(".flow-staff-text").textContent).toBe("데이터 분석 비서아직 리뷰 없음");
    act(() => { fireEvent.click(screen.getByRole("button", { name: "리뷰 넣기" })); });
    expect(window.location.hash).toBe("#/analysis");
    expect(getState().nav).toMatchObject({ name: "analysis", sub: "paste" });
    act(() => { fireEvent.click(screen.getByRole("button", { name: "상권 분석 보기" })); });
    expect(window.location.hash).toBe("#/market");
  });

  it("홈: 리뷰가 있는 가게는 그대로 ('무엇을 할까요?' 하나, 다음 할 일 버튼 없음)", () => {
    const { container } = render(<Home />);
    expect([...container.querySelector(".flow-todo-foot").querySelectorAll("button")].map((x) => x.textContent)).toEqual(["무엇을 할까요? (추천 카드 보기)"]);
    expect(screen.queryByRole("button", { name: "리뷰 넣기" })).toBeNull();
    expect(screen.queryByRole("button", { name: "상권 분석 보기" })).toBeNull();
  });

  it("홈: 리뷰 0건인 새 가게도 깨지지 않고 짧은 빈 안내 (로그인 정보가 없어도)", () => {
    setState({ me: null, cards: [], briefing: { store: { name: "새 가게" }, period: { start: null, end: null },
      counts: { review_count: 0, complaint_count: 0 }, top_issue_id: null, groups: [], single_complaints: [], pasted: [], snapshots: [] } });
    const { container } = render(<Home />);
    expect(container.textContent).not.toMatch(/undefined|null|NaN/);
    expect(container.querySelector(".flow-eyebrow").textContent).toBe("밤 11시 브리핑");
    expect(screen.getByText("아직 들어온 리뷰가 없어요", { selector: "strong" })).toBeTruthy();
    expect(screen.queryByText("1일 동안")).toBeNull();
    expect(screen.getByText("리뷰가 들어오면 할 일을 골라 드려요.")).toBeTruthy();
    expect(container.querySelector(".flow-hours")).toBeNull();   // 빈 막대 대신 한 줄
    expect(screen.getAllByText("불만 리뷰가 없어요.")).toHaveLength(2);   // 시간 · 주제 두 칸
  });

  it("추천 카드: 카드를 위아래로 한 장씩, 만들기 버튼 옆 '근거 보기'가 근거를 펼친다", () => {
    const { container } = render(<Cards />);
    const grid = container.querySelector(".flow-card-grid");
    expect(grid.classList.contains("grid-2")).toBe(false);
    const foot = container.querySelector(".flow-card .flow-card-foot");
    expect([...foot.children].map((x) => x.textContent)).toEqual(["포장·주문 안내문·답글 만들기", "근거 보기 ▾"]);
    const toggle = screen.getByRole("button", { name: "근거 보기" });
    const ev = container.querySelector(".flow-more");
    expect(toggle.getAttribute("aria-controls")).toBe(ev.id);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(ev.hidden).toBe(true);
    expect(order(foot, ev)).toBe(true);   // 펼친 근거는 버튼 줄 아래
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(ev.hidden).toBe(false);
    // 점검 수칙은 회색 상자 안, 버튼 줄보다 위
    expect(order(container.querySelector(".flow-measures"), foot)).toBe(true);
  });

  it("추천 카드: 리뷰 0건인 새 가게는 짧은 빈 안내", () => {
    setState({ cards: [], briefing: { ...briefing, counts: { review_count: 0, complaint_count: 0 }, groups: [] } });
    render(<Cards />);
    expect(screen.getByText("리뷰가 들어오면 추천 카드를 골라 드려요.")).toBeTruthy();
  });

  it("승인할 글: 진행줄은 글자 + 지금 글 이름 (막대 없음), 리뷰마다 회색 상자, 점검 칩 줄은 글 칸과 버튼 사이", () => {
    const run = { ...runA, drafts: [runA.drafts[0], { ...runA.drafts[1], model: "HCX-005", elapsed_ms: 7400, checks: { used_fallback: true } }] };
    setState({ results: { card_a: run }, current: "card_a", draftId: "d2" });
    const { container } = render(<Draft />);
    const progress = container.querySelector(".flow-progress");
    expect(progress.querySelector(".flow-track")).toBeNull();
    expect(progress.querySelector(".flow-progress-text").textContent).toBe("승인 0 / 2 · 포장·주문 안내문");
    // 손님 리뷰: 근거 건수는 패널 오른쪽, 리뷰마다 상자
    const rv = screen.getByRole("region", { name: "손님 리뷰" });
    expect(rv.querySelector(".panel-head .sub").textContent).toBe("근거 리뷰 2건");
    expect(rv.querySelectorAll(".flow-rv-box")).toHaveLength(2);
    // 초안 상자: 글 칸 → 칩 줄 → 고칠 곳 → 버튼 줄
    const box = screen.getByLabelText(/AI 포장·주문 안내문 초안/);
    const chips = container.querySelector(".flow-checks");
    const issues = container.querySelector(".flow-issues");
    const approveBtn = screen.getByRole("button", { name: "승인" });
    expect(order(box, chips) && order(chips, issues) && order(issues, approveBtn)).toBe(true);
    expect([...chips.querySelectorAll(".badge")].map((b) => b.textContent)).toEqual(["확인 필요 1", "기본 문장으로 바꿈"]);
    // 기본 문장으로 바꾼 글: 이유 한 줄이 칩 아래에 있고, 모델 이름·걸린 시간은 보이지 않는다
    const draftBox = container.querySelector(".flow-draft-box");
    // 11/21: 기본 문장은 리뷰와 안 맞을 수 있어 확인·고침 안내를 덧붙임 (실시간 확인 M2)
    expect(draftBox.querySelector(".flow-fallback-note").textContent).toBe("AI 글이 점검을 넘지 못해 기본 문장으로 바꿨어요. 리뷰 내용과 맞는지 확인하고 고쳐서 승인해 주세요.");
    expect(draftBox.textContent).not.toContain("HCX-005");
    expect(draftBox.textContent).not.toContain("7.4초");
    expect(container.querySelector(".flow-draft-box .panel-head .badge")).toBeNull();   // 머리 오른쪽에는 배지 없음
  });

  it("처리 완료: 타일 → 승인한 글 → 점검 수칙 → 서버 처리 기록 → 버튼, 기록은 글 이름으로", async () => {
    mockFetch(() => ({ items: [
      { draft_id: "d2", edited: true, approved_at: "2026-11-19T21:00:05+09:00" },
      { draft_id: "mkt-x-promo", edited: false, approved_at: "2026-11-19T21:02:00+09:00" },
    ] }));
    setState({ results: { card_a: runA }, approved: new Set(["d2"]), approvedLog: [
      { id: "d2", edited: true, kind: "prevention_notice", name: "포장·주문 안내문", card: "포장 누락을 막아요", at: "2026-11-19T21:00:05+09:00", text: "안내문 고침" },
    ] });
    let container;
    await act(async () => { ({ container } = render(<Done />)); });
    const col = container.querySelector(".flow-done");
    const tiles = col.querySelector(".flow-done-tiles");
    const list = screen.getByRole("region", { name: "승인한 글" });
    const rules = screen.getByRole("region", { name: "오늘부터 실천할 주방 점검 수칙" });
    const server = col.querySelector("details.flow-server");
    const home = screen.getByRole("button", { name: "홈으로" });
    expect(order(tiles, list) && order(list, rules) && order(rules, server) && order(server, home)).toBe(true);
    // 11/21 QA B-1: 승인한 글 = 이 브라우저 목록 ∪ 서버 기록 (같은 글 d2 는 한 번만, 서버에만 있는 맞춤 마케팅 글도 들어감)
    expect(tiles.querySelector(".num").textContent).toBe("2개");
    // 승인한 글: 이름 · 시각 / 글 앞부분, 승인 완료 배지는 없음 (모두 승인한 글이라)
    const items = [...list.querySelectorAll(".flow-log-item")];
    expect(items.map((x) => x.querySelector(".strong").textContent)).toEqual(["포장·주문 안내문", "맞춤 마케팅 글"]);
    const item = items[0];
    expect(item.querySelector(".strong").textContent).toBe("포장·주문 안내문");
    expect(item.querySelector(".flow-log-excerpt").textContent).toBe("안내문 고침");
    expect(list.querySelector(".badge")).toBeNull();
    expect(server.querySelector("summary h2").textContent).toBe("서버 처리 기록");
    expect([...server.querySelectorAll("li")].map((x) => x.textContent)).toEqual([
      "11-19 21:00 승인 · 포장·주문 안내문 (고침)", "11-19 21:02 승인 · 맞춤 마케팅 글"]);
    expect(server.textContent).not.toContain("d2");   // 내부 글 id 는 보이지 않음
  });
});

describe("11/21 실시간 확인에서 고친 것", () => {
  const own = { authenticated: true, store_id: "u1", stores: [{ store_id: "u1", name: "동네맛김밥", sample: false, area_name: "홍대입구역(홍대)", business_type_name: "분식전문점" }] };
  it("홈: 직접 등록한 가게는 상권 지표가 없으면 '없음' 대신 '상권 분석에서 보기' → 상권 분석 (M3)", () => {
    setState({ me: own });
    const { container } = render(<Home />);
    const tile = container.querySelector(".tile.tint-sage");
    expect(tile.textContent).not.toMatch(/지표 없음|–/);
    expect(tile.querySelector(".tile-sub").textContent).toBe("홍대입구역(홍대) 상권");
    fireEvent.click(screen.getByRole("button", { name: "상권 분석에서 보기" }));
    expect(window.location.hash).toBe("#/market");
  });
  it("홈: 예시 가게는 그대로 (지표가 있으면 숫자, 없으면 '상권 지표 없음')", () => {
    setState({ me: { ...own, stores: [{ ...own.stores[0], sample: true }] } });
    const { container } = render(<Home />);
    expect(container.querySelector(".tile.tint-sage").textContent).toContain("상권 지표 없음");
    expect(screen.queryByRole("button", { name: "상권 분석에서 보기" })).toBeNull();
  });
  it("추천 카드: 쿠폰 홍보 카드(ⓑ)가 없으면 그 자리에 까닭과 맞춤 마케팅 버튼 (빈 화면이 아님, 12)", () => {
    setState({ noCardB: "우리 가게 상권 지표가 아직 없어 쿠폰 홍보 카드는 만들지 않았어요." });
    render(<Cards />);
    const panel = screen.getByRole("region", { name: "오늘은 쿠폰 홍보 카드가 없어요" });
    expect(panel.textContent).toContain("ⓑ 쿠폰 홍보");
    expect(screen.getAllByText(/상권 지표가 아직 없어/)).toHaveLength(1);   // 아래 작은 줄로 또 말하지 않음
    fireEvent.click(screen.getByRole("button", { name: "맞춤 마케팅에서 홍보 제안 받기" }));
    expect(window.location.hash).toBe("#/marketing");
    expect(getState().nav).toMatchObject({ name: "marketing", sub: "promo" });
  });
  it("추천 카드: ⓑ 카드가 있으면 빈 자리 칸이 없다", () => {
    setState({ cards: [cardA, { ...cardA, title: "쿠폰", card: { card_id: "card_b", kind: "promo", reason_text: "칭찬", review_ids: [] }, evidence: [], measures: null }] });
    render(<Cards />);
    expect(screen.queryByText("오늘은 쿠폰 홍보 카드가 없어요")).toBeNull();
  });
  it("승인할 글: 기본 문장으로 바꾼 글은 '점검 통과' 없이 '기본 문장으로 바꿈'(주의)과 확인 안내, 목록 배지도 '기본 문장' (M2)", () => {
    const run = { ...runA, drafts: [{ ...runA.drafts[0], checks: { used_fallback: true } }, runA.drafts[1]] };
    setState({ results: { card_a: run }, current: "card_a", draftId: "d1" });
    const { container } = render(<Draft />);
    const chips = [...container.querySelectorAll(".flow-checks .badge")];
    expect(chips.map((b) => b.textContent)).toEqual(["기본 문장으로 바꿈"]);
    expect(chips[0].className).toContain("warn");
    expect(container.querySelector(".flow-checks").textContent).not.toContain("점검 통과");
    expect(screen.getByLabelText(/AI 답글 초안/).labels[0].textContent).toBe("AI 답글 초안 (기본 문장으로 바꿈)");
    const row = [...container.querySelectorAll(".flow-list button")].find((b) => b.textContent.includes("답글"));
    expect([...row.querySelectorAll(".badge")].map((b) => b.textContent)).toEqual(["승인 대기", "기본 문장"]);
  });
  it("승인할 글: '다시 만들기'에 같은 기본 문장이 다시 오면 '새로 만들었어요' 대신 사실대로 (M2)", async () => {
    const fb = { ...runA.drafts[0], text: "주문하신 품목이 빠져 있었다니 정말 죄송해요.", checks: { used_fallback: true } };
    setState({ results: { card_a: { ...runA, source: "live", drafts: [fb, runA.drafts[1]] } }, current: "card_a", draftId: "d1" });
    mockFetch(() => ({ source: "live", drafts: [{ ...fb, draft_id: "d9" }] }));
    render(<Draft />);
    fireEvent.click(screen.getByRole("button", { name: "다시 만들기" }));
    expect(await screen.findByText("다시 만들었지만 같은 기본 문장이 나왔어요. 리뷰와 맞게 직접 고쳐서 승인해 주세요.")).toBeTruthy();
    expect(screen.queryByText(/이 글만 새로 만들었어요/)).toBeNull();
    expect(getState().draftId).toBe("d9");
  });
});

// 11/21 실사용 QA 에서 나온 결함 (B-1 ~ B-9, B-8 은 팀 규칙에 따라 되돌림)
describe("11/21 실사용 QA", () => {
  // 사장님이 붙여넣은 불만 리뷰만 있는 새 가게 (리뷰 4건 모두 불만, 2건 묶음 하나는 반복 아님)
  const pastedOnly = {
    store: { name: "동네맛김밥", data_origin: "registered" }, period: { start: "2026-11-21", end: "2026-11-21" },
    counts: { review_count: 4, complaint_count: 4 }, top_issue_id: "g1",
    pasted: ["p1", "p2", "p3", "p4"].map((id) => ({ review_id: id, text: `불만 ${id}`, created_at: "2026-11-21T00:05:00+09:00", input_method: "paste" })),
    groups: [{ issue_id: "g1", topic_name: "식감", review_count: 2, is_repeated: false, main_time_band: null,
      reviews: [{ review_id: "p1", created_at: "2026-11-21T00:05:00+09:00", input_method: "paste" }, { review_id: "p2", created_at: "2026-11-21T00:06:00+09:00", input_method: "paste" }] }],
    single_complaints: [{ review_id: "p3", topic_names: ["양"], created_at: "2026-11-21T00:07:00+09:00" }, { review_id: "p4", topic_names: ["맛"], created_at: "2026-11-21T00:08:00+09:00" }],
    snapshots: [],
  };

  it("B-2·B-3 홈: 붙여넣은 불만만 있으면 '불만 리뷰가 없어요' 대신 시각이 없어 그리지 않는다고, 반복 0건은 기준", () => {
    setState({ cards: [], briefing: pastedOnly });
    const { container } = render(<Home />);
    const hour = screen.getByRole("region", { name: "불만 리뷰가 몰린 시간" });
    expect(hour.textContent).toContain("붙여넣은 리뷰에는 주문 시각이 없어 시간대를 그리지 않아요.");
    expect(hour.textContent).not.toContain("불만 리뷰가 없어요");
    expect(container.querySelector(".flow-hours")).toBeNull();
    // 같은 화면의 주제 칸은 불만을 그대로 보인다 (모순 없음)
    expect(screen.getByRole("region", { name: "주제별 불만" }).textContent).toContain("식감");
    // 반복 불만 0건 타일은 기준을 부제로
    const rep = container.querySelector(".tile.tint-lime");
    expect(rep.querySelector(".num").textContent).toBe("0건");
    expect(rep.querySelector(".tile-sub").textContent).toBe("같은 불만 3건부터");
  });

  it("B-2 홈: 합성 리뷰와 붙여넣은 불만이 섞이면 막대는 그리고 뺀 건수를 한 줄로", () => {
    setState({ briefing: { ...briefing, counts: { review_count: 21, complaint_count: 4 }, pasted: [{ review_id: "p1" }],
      single_complaints: [{ review_id: "p1", topic_names: ["맛"], created_at: "2026-11-21T00:05:00+09:00" }] } });
    const { container } = render(<Home />);
    expect(container.querySelector(".flow-hours")).toBeTruthy();
    expect(container.querySelector(".flow-hours-note").textContent).toBe("붙여넣은 불만 1건은 주문 시각이 없어 시간대에서 뺐어요.");
  });

  it("B-9 추천 카드: 점검 수칙은 라벨 한 줄 전체가 체크 자리 (글자를 눌러도 체크)", () => {
    render(<Cards />);
    const box = screen.getByRole("checkbox", { name: /수저 확인/ });
    expect(box.closest("label").textContent).toContain("수저 확인");
    fireEvent.click(box.closest("label"));
    expect(box.checked).toBe(true);
  });

  it("B-1 처리 완료: 새로 고침 뒤(브라우저 승인 목록이 빔)에도 서버 승인 기록을 '승인한 글'로 보인다", async () => {
    mockFetch(() => ({ items: [
      { draft_id: "d_1a2b3c4d", status: "approved", edited: true, text: "고객님 죄송합니다. 다음부터 꼭 챙길게요.", approved_at: "2026-11-21T20:00:00+09:00", mode: "live" },
      { draft_id: "mkt-77", status: "approved", edited: false, text: "제육볶음 쿠폰 드려요", approved_at: "2026-11-21T20:05:00+09:00", mode: "live" },
    ] }));
    let container;
    await act(async () => { ({ container } = render(<Done />)); });
    expect(screen.queryByText("아직 승인한 글이 없어요.")).toBeNull();
    const list = screen.getByRole("region", { name: "승인한 글" });
    const items = [...list.querySelectorAll(".flow-log-item")];
    expect(items.map((x) => x.querySelector(".strong").textContent)).toEqual(["글", "맞춤 마케팅 글"]);
    expect(items[0].querySelector(".flow-log-excerpt").textContent).toBe("고객님 죄송합니다. 다음부터 꼭 챙길게요.");
    expect(items[0].textContent).toContain("사장님이 고침");
    expect(screen.getByRole("button", { name: "글 복사" })).toBeTruthy();
    // 이 브라우저가 만든 글을 모르면 '만든 글 n개 중'을 지어내지 않는다
    expect(list.querySelector(".panel-head .sub").textContent).toBe("서버에 남은 승인 기록");
    const tiles = container.querySelectorAll(".flow-done-tiles .tile");
    expect(tiles[0].querySelector(".num").textContent).toBe("2개");
    expect(tiles[1].querySelector(".num").textContent).toBe("1개");
    // '처음부터 다시'는 그대로 있다
    expect(screen.getByRole("button", { name: "처음부터 다시" })).toBeTruthy();
  });

  it("B-1 처리 완료: 둘 다 비었을 때만 빈 화면, 서버 기록을 읽는 동안은 '없어요'라고 하지 않음", async () => {
    let finish;
    globalThis.fetch = vi.fn(() => new Promise((ok) => { finish = () => ok({ ok: true, status: 200, json: async () => ({ items: [] }), headers: { get: () => "application/json" } }); }));
    render(<Done />);
    expect(screen.getByText("승인 기록을 불러오는 중…")).toBeTruthy();
    expect(screen.queryByText("아직 승인한 글이 없어요.")).toBeNull();
    await act(async () => { finish(); });
    expect(screen.getByText("아직 승인한 글이 없어요.")).toBeTruthy();
  });

  it("B-1 처리 완료: 서버를 못 읽어도 이 브라우저의 승인 목록은 그대로", async () => {
    globalThis.fetch = vi.fn(async () => ({ ok: false, status: 503, json: async () => ({ error: { message: "DB 꺼짐" } }), headers: { get: () => "application/json" } }));
    setState({ results: { card_a: runA }, approved: new Set(["d1"]), approvedLog: [
      { id: "d1", edited: false, kind: "reply_draft", name: "답글", card: "포장 누락을 막아요", at: "2026-11-21T21:01:00+09:00", text: "답글 하나" }] });
    await act(async () => { render(<Done />); });
    const list = screen.getByRole("region", { name: "승인한 글" });
    expect([...list.querySelectorAll(".flow-log-item .strong")].map((x) => x.textContent)).toEqual(["답글"]);
    expect(list.querySelector(".panel-head .sub").textContent).toBe("만든 글 2개 중 1개 승인");
  });
});

describe("11/22 실사용 QA", () => {
  const NOTE = "점검 결과는 고치기 전 글 기준이에요.";
  const order = (a, b) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

  it("D3 승인할 글: 고치면 칩 바로 아래 '고치기 전 글 기준' 한 줄, 칩과 확인 필요 설명은 그대로, 원문으로 되돌리면 사라짐", () => {
    setState({ results: { card_a: runA }, current: "card_a", draftId: "d2" });
    const { container } = render(<Draft />);
    const box = screen.getByLabelText(/AI 포장·주문 안내문 초안/);
    expect(screen.queryByText(NOTE)).toBeNull();                       // 고치기 전에는 없음
    fireEvent.change(box, { target: { value: "제가 통째로 다시 쓴 안내문" } });
    const note = screen.getByText(NOTE);
    expect(note.className).toContain("small muted");
    const chips = container.querySelector(".flow-checks");
    expect(order(chips, note) && order(note, container.querySelector(".flow-issues"))).toBe(true);
    expect([...chips.querySelectorAll(".badge")].map((b) => b.textContent)).toEqual(["확인 필요 1"]);
    expect(container.querySelector(".flow-issues").textContent).toBe("확인 필요 · 확인할 것");
    fireEvent.change(box, { target: { value: "안내문" } });           // 원문으로 되돌림
    expect(screen.queryByText(NOTE)).toBeNull();
  });

  it("D3 승인할 글: 고쳐서 승인한 글은 승인 완료 칩 옆에도 한 줄, 고치지 않고 승인한 글은 없음", () => {
    const run = { ...runA, drafts: [{ ...runA.drafts[0], edited_text: "고쳐서 승인한 답글" }, runA.drafts[1]] };
    setState({ results: { card_a: run }, current: "card_a", draftId: "d1", approved: new Set(["d1", "d2"]) });
    const view = render(<Draft />);
    expect(screen.getByLabelText(/AI 답글 초안/).value).toBe("고쳐서 승인한 답글");
    expect(screen.getByText(NOTE)).toBeTruthy();
    view.unmount();
    setState({ draftId: "d2" });
    render(<Draft />);
    expect(screen.queryByText(NOTE)).toBeNull();
  });

  it("D1 홈 '반복 불만' 타일: 숫자는 그대로, 부제는 리뷰 분석 요약 탭과 같은 '묶음 n개 · 주제'", () => {
    setState({ cards: [] });
    const { container } = render(<Home />);
    const rep = container.querySelector(".tile.tint-lime");
    expect(rep.querySelector(".num").textContent).toBe("2건");
    expect(rep.querySelector(".tile-sub").textContent).toBe("묶음 1개 · 포장 누락");
  });
});
