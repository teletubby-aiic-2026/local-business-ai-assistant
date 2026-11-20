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
  it("시작 버튼 옆 보조 문구 없이, 상권 칸 범위는 칩으로 (상권명 · 업종 · 시간대)", () => {
    setState({ briefing: { ...briefing, snapshots: [{ snapshot_id: "s1", value: -19.31, unit: "%", area_name: "장승배기역 4번",
      metric_name: "저녁 시간대(17~24시) 추정매출 전년 동기 대비 변화율 · 두 분기 공통 업종" }] } });
    const { container } = render(<Home />);
    expect(screen.queryByText(/추천 카드 2장/)).toBeNull();
    expect(container.querySelector(".flow-todo-foot").textContent).toBe("무엇을 할까요?");
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
});

describe("추천 카드", () => {
  it("머리말 설명 없이, 근거 보기는 리뷰·지표 출처와 원본 링크만 (검사기 표현 없음), 시험용 수칙 고지는 한 줄", () => {
    setState({ cards: [{ ...cardA, reason_source: "HCX-005 (검사기 통과)", problems: [{ type: "too_long" }],
      evidence: [...cardA.evidence, { type: "snapshot", id: "s1", text: "저녁 매출 -19.31%", basis: "서울시 상권분석서비스 2026년 2분기 · https://golmok.seoul.go.kr/x" }] }] });
    const { container } = render(<Cards />);
    expect(container.querySelector(".page-head .ph-sub")).toBeNull();
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
    expect(rows()).toEqual([["1. 포장·주문 안내문", ["승인 대기", "확인 필요"]], ["2. 답글", ["승인 대기"]]]);
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
    const run = { ...runA, drafts: [runA.drafts[0], { ...runA.drafts[1], checks: { used_fallback: true } }] };
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
    expect([...chips.querySelectorAll(".badge")].map((b) => b.textContent)).toEqual(["확인 필요 1", "기본 문장 (AI 글 아님)"]);
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
    expect(tiles.querySelector(".num").textContent).toBe("1개");
    // 승인한 글: 이름 · 시각 / 글 앞부분, 승인 완료 배지는 없음 (모두 승인한 글이라)
    const item = list.querySelector(".flow-log-item");
    expect(item.querySelector(".strong").textContent).toBe("포장·주문 안내문");
    expect(item.querySelector(".flow-log-excerpt").textContent).toBe("안내문 고침");
    expect(list.querySelector(".badge")).toBeNull();
    expect(server.querySelector("summary h2").textContent).toBe("서버 처리 기록");
    expect([...server.querySelectorAll("li")].map((x) => x.textContent)).toEqual([
      "11-19 21:00 승인 · 포장·주문 안내문 (고침)", "11-19 21:02 승인 · 맞춤 마케팅 글"]);
    expect(server.textContent).not.toContain("d2");   // 내부 글 id 는 보이지 않음
  });
});
