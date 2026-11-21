// AI에게 묻기 서랍: 선택지 위치(답 글 바로 아래, 근거·안내보다 위) · 기준 범위 칩과 안내 한 줄 · 화면 이동 뒤 포커스
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { getState, openDrawer, resetStore, setState } from "../../state/store.js";
import Drawer from "./Drawer.jsx";
import Topbar from "../../components/Topbar.jsx";
import { chatReset, drawerCovers } from "./state.js";

const COND = { area_name: "장승배기역 4번", industry_name: "한식음식점", period: "20262", is_store_default: true };
const NAV = { label: "상권 분석 표·차트 보기", payload: { type: "navigate", route: "market" } };
const TURN = {
  user_text: "우리 가게 상권 매출은 어때?",
  reply: { text: "추정매출은 12억 원이에요 [F1]", actions: [NAV], notes: ["2026년 2분기 기준이에요"], suggestions: ["주말 매출은?"] },
  cards: [{ id: "F1", topic: "sales_total", text: "분기 추정매출", values: [] }],
};
const SNAP = { value: -19.31, unit: "%", area_name: "장승배기역 4번",
  metric_name: "저녁 시간대(17~24시) 추정매출 전년 동기 대비 변화율 · 두 분기 공통 업종" };

let cover = false;   // 서랍이 본문을 덮는 폭인가 (jsdom 은 위치를 잴 수 없어 예전 기준 matchMedia 로 판단)
const fakeFetch = (turns) => vi.fn(async (url) => {
  const path = String(url);
  const out = path.endsWith("/status") ? { state: "ready", setup: { label: "온기한식" } }
    : path.endsWith("/conversation") ? { turns, conditions: COND } : {};
  return { ok: true, status: 200, json: async () => out };
});

// 상단 'AI에게 묻기' 버튼 + 본문 제목(PageHead 의 h1 자리) + 서랍
function Shell() {
  return (
    <>
      <button type="button" id="opener" aria-controls="assistant">AI에게 묻기</button>
      <main id="main"><h1 id="screen-title" tabIndex={-1}>지금 화면</h1></main>
      <Drawer />
    </>
  );
}

async function openWith(turns) {
  globalThis.fetch = fakeFetch(turns);
  render(<Shell />);
  document.getElementById("opener").focus();
  act(() => openDrawer(true));
  await waitFor(() => expect(document.getElementById("assistant-q").disabled).toBe(false));
}

beforeEach(() => {
  resetStore();
  chatReset(getState().epoch, false);
  cover = false;
  window.matchMedia = (q) => ({ matches: cover && q.includes("1339"), media: q, addEventListener() {}, removeEventListener() {} });
  Element.prototype.scrollTo = () => {};
  globalThis.requestAnimationFrame = globalThis.requestAnimationFrame || ((cb) => setTimeout(cb, 0));
  window.location.hash = "";
});
afterEach(() => { cleanup(); });

describe("서랍 답의 선택지", () => {
  it("선택지는 답 글 바로 아래, '근거 n개'·'자료 기준 안내'보다 먼저 나온다", async () => {
    await openWith([TURN]);
    await screen.findByText(/추정매출은 12억 원이에요/);
    const text = document.querySelector(".chat-msg.bot .chat-text");
    const actions = document.querySelector(".chat-msg.bot .chat-actions");
    const ev = document.querySelector(".chat-msg.bot details.chat-ev");
    const notes = document.querySelector(".chat-msg.bot details.chat-notes");
    expect(text.nextElementSibling).toBe(actions);
    expect(actions.compareDocumentPosition(ev) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(actions.compareDocumentPosition(notes) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("근거 1개")).toBeTruthy();
    expect(screen.getByText("자료 기준 안내")).toBeTruthy();
  });

  it("화면 이동 선택지로 서랍이 닫히면 포커스는 'AI에게 묻기'가 아니라 이동한 화면 제목으로", async () => {
    cover = true;
    await openWith([TURN]);
    const pick = await screen.findByRole("button", { name: NAV.label });
    act(() => { fireEvent.click(pick); });
    expect(getState().drawerOpen).toBe(false);
    expect(getState().nav).toMatchObject({ name: "market", sub: null });
    expect(window.location.hash).toBe("#/market");
    await waitFor(() => expect(document.activeElement.id).toBe("screen-title"));
    await new Promise((r) => setTimeout(r, 250));   // 몇 번 다시 봐도 'AI에게 묻기'로 돌아가지 않는다
    expect(document.activeElement.id).toBe("screen-title");
  });

  it("서랍이 본문을 밀어 둔 넓은 화면이면 화면만 옮기고 서랍은 그대로", async () => {
    await openWith([TURN]);
    act(() => { fireEvent.click(screen.getByRole("button", { name: NAV.label })); });
    expect(getState().drawerOpen).toBe(true);
    expect(window.location.hash).toBe("#/market");
  });

  it("그냥 닫으면 연 버튼으로 포커스를 돌려준다", async () => {
    await openWith([TURN]);
    fireEvent.click(screen.getByRole("button", { name: "AI에게 묻기 닫기" }));
    expect(getState().drawerOpen).toBe(false);
    expect(document.activeElement.id).toBe("opener");
  });
});

describe("상단 'AI에게 묻기' 버튼 (실제 상단 바)", () => {
  const ask = () => screen.getByRole("button", { name: "AI에게 묻기" });

  it("두 번 눌러도 서랍은 닫히지 않고 입력칸으로 간다", async () => {
    globalThis.fetch = fakeFetch([]);
    render(<><Topbar /><Drawer /></>);
    ask().focus();
    act(() => { fireEvent.click(ask()); });
    expect(getState().drawerOpen).toBe(true);
    await waitFor(() => expect(document.getElementById("assistant-q").disabled).toBe(false));
    ask().focus();   // 실제로 누르면 버튼이 포커스를 가져간다
    act(() => { fireEvent.click(ask()); });
    expect(getState().drawerOpen).toBe(true);
    expect(ask().getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement.id).toBe("assistant-q");
  });

  it("처음 열면 준비되는 동안 닫기 버튼에 있다가, 준비가 끝나면 입력칸으로 간다", async () => {
    globalThis.fetch = fakeFetch([]);
    render(<><Topbar /><Drawer /></>);
    ask().focus();
    act(() => { fireEvent.click(ask()); });
    expect(document.activeElement.id).toBe("assistant-close");   // 입력칸이 아직 막혀 있음
    await waitFor(() => expect(document.getElementById("assistant-q").disabled).toBe(false));
    await waitFor(() => expect(document.activeElement.id).toBe("assistant-q"));
  });

  it("입력칸이 아직 막혀 있으면(준비 전) 다시 눌렀을 때 닫기 버튼으로 간다", async () => {
    globalThis.fetch = vi.fn(() => new Promise(() => {}));   // 상태 확인이 끝나지 않음
    render(<><Topbar /><Drawer /></>);
    ask().focus();
    act(() => { fireEvent.click(ask()); });
    expect(document.getElementById("assistant-q").disabled).toBe(true);
    ask().focus();
    act(() => { fireEvent.click(ask()); });
    expect(getState().drawerOpen).toBe(true);
    expect(ask().getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement.id).toBe("assistant-close");
  });
});

describe("서랍의 기준 범위", () => {
  it("칩은 상권 · 업종 · 분기 · 하루 전체, '우리 가게 매출 아님'은 위 안내 한 줄에만", async () => {
    await openWith([TURN]);
    await screen.findByText(/추정매출은 12억 원이에요/);
    const chips = [...document.querySelectorAll("#assistant-cond-text .chat-cond-chip")].map((e) => e.textContent);
    expect(chips).toEqual(["장승배기역 4번 상권", "한식음식점", "2026년 2분기", "하루 전체"]);
    expect(document.getElementById("assistant-cond-note").textContent).toBe("상권·업종 전체 추정치예요 (우리 가게 매출 아님)");
    expect(screen.getAllByText(/우리 가게 매출/).length).toBe(1);
    expect(screen.queryByText(/우리 가게 매출이 아니에요/)).toBeNull();
    // 홈 '상권 저녁 매출' 지표가 있으면 그 범위(공통 업종 17~24시)를 같은 줄에
    act(() => setState({ briefing: { snapshots: [SNAP] } }));
    expect(document.getElementById("assistant-cond-note").textContent)
      .toBe("상권·업종 전체 추정치예요 (우리 가게 매출 아님 · 홈 타일은 공통 업종 17~24시 기준)");
  });

  it("첫 안내에도 같은 고지를 또 쓰지 않는다", async () => {
    await openWith([]);
    expect(await screen.findByText("우리 가게 상권, 편하게 물어보세요")).toBeTruthy();
    expect(screen.getAllByText(/우리 가게 매출/).length).toBe(1);
    expect(screen.getByText("우리 가게 상권 매출은 어때?")).toBeTruthy();   // 첫 추천 질문은 그대로
  });
});

describe("서랍이 본문을 덮는가", () => {
  it("위치로 판단: 본문 오른쪽이 서랍 왼쪽을 넘으면 덮음", () => {
    const d = document.createElement("aside"), m = document.createElement("main");
    d.id = "assistant"; m.id = "main";
    document.body.append(d, m);
    d.getBoundingClientRect = () => ({ left: 880, right: 1280, top: 0, bottom: 800, width: 400, height: 800 });
    m.getBoundingClientRect = () => ({ left: 260, right: 1280, top: 64, bottom: 2000, width: 1020, height: 1936 });   // 1280px: 덮음
    expect(drawerCovers()).toBe(true);
    d.getBoundingClientRect = () => ({ left: 1040, right: 1440, top: 0, bottom: 900, width: 400, height: 900 });
    m.getBoundingClientRect = () => ({ left: 260, right: 1040, top: 64, bottom: 2000, width: 780, height: 1936 });    // 넓은 화면: 밀림
    expect(drawerCovers()).toBe(false);
    d.getBoundingClientRect = () => ({ left: 0, right: 375, top: 120, bottom: 812, width: 375, height: 692 });
    m.getBoundingClientRect = () => ({ left: 0, right: 375, top: 110, bottom: 1600, width: 375, height: 1490 });      // 휴대전화 시트: 덮음
    expect(drawerCovers()).toBe(true);
    d.remove(); m.remove();
  });
});

describe("휴대폰 시트의 뒤 막과 스크롤 잠금 (11/21 QA)", () => {
  // 760px 이하로 보이게 (lib/media.js 의 narrow 질의만 맞음)
  const phone = () => { window.matchMedia = (q) => ({ matches: q === "(max-width: 760px)", media: q, addEventListener() {}, removeEventListener() {} }); };
  const scrim = () => document.querySelector(".drawer-scrim");
  const locked = () => document.documentElement.classList.contains("drawer-lock");

  it("열면 뒤에 막(읽기 프로그램에는 숨김)과 스크롤 잠금, 막을 누르면 닫히고 잠금이 풀리며 연 버튼으로 포커스", async () => {
    phone();
    await openWith([]);
    expect(scrim()).toBeTruthy();
    expect(scrim().getAttribute("aria-hidden")).toBe("true");
    expect(locked()).toBe(true);
    expect(document.activeElement.id).toBe("assistant-q");   // 여는 포커스는 그대로
    act(() => { fireEvent.click(scrim()); });
    expect(getState().drawerOpen).toBe(false);
    expect(scrim()).toBeNull();
    expect(locked()).toBe(false);
    expect(document.activeElement.id).toBe("opener");
  });

  it("[닫기]·Esc 로 닫아도 잠금이 풀린다", async () => {
    phone();
    await openWith([]);
    fireEvent.click(screen.getByRole("button", { name: "AI에게 묻기 닫기" }));
    expect(locked()).toBe(false);
    act(() => openDrawer(true));
    expect(locked()).toBe(true);
    act(() => { fireEvent.keyDown(document, { key: "Escape" }); });
    expect(getState().drawerOpen).toBe(false);
    expect(locked()).toBe(false);
    expect(scrim()).toBeNull();
  });

  it("넓은 화면은 막도 잠금도 없이 지금 배치 그대로", async () => {
    await openWith([]);
    expect(getState().drawerOpen).toBe(true);
    expect(scrim()).toBeNull();
    expect(locked()).toBe(false);
  });
});

describe("서랍 첫 안내 (11/21 실시간 확인 M7·9)", () => {
  it("조건을 맞추는 동안의 안내에 주소 원문 대신 짧은 위치 (빈 조각·'null'은 빼고)", async () => {
    let release;
    const gate = new Promise((ok) => { release = ok; });
    const reply = (out) => ({ ok: true, status: 200, json: async () => out });
    globalThis.fetch = vi.fn(async (url) => {
      const path = String(url);
      if (path.endsWith("/status")) return reply({ state: "ready", setup: { label: "동네맛김밥 · 서울특별시 마포구 와우산로 94 학교법인홍익학원 · 분식전문점" } });
      if (path.endsWith("/conversation")) return reply({ turns: [], conditions: null });
      if (path.endsWith("/setup")) { await gate; return reply({ status: "ok", conditions: COND }); }
      return reply({});
    });
    render(<Shell />);
    act(() => openDrawer(true));
    await waitFor(() => expect(document.getElementById("assistant-status").textContent).toContain("분석 조건을 맞추고 있어요"));
    const t = document.getElementById("assistant-status").textContent;
    expect(t).toContain("(동네맛김밥 · 마포구 와우산로 94 · 분식전문점)");
    expect(t).not.toMatch(/학교법인|서울특별시|null/);
    await act(async () => { release(); });
    await waitFor(() => expect(document.getElementById("assistant-q").disabled).toBe(false));
    expect(document.getElementById("assistant-cond-text").textContent).not.toMatch(/null|undefined/);
  });
});
