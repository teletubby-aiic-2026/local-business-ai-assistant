// 화면 틀: 덮는 메뉴(761~1024px)의 포커스 가두기·Esc·돌려주기, 메뉴가 안 보일 때 상단 바의 승인 대기 수,
// 시험용 안내 띠 한 곳, 계정 줄 문구. 화면 8개와 서랍은 가짜로 바꿔 틀만 본다 (화면 시험은 각 화면 폴더에)
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import { resetStore, setState } from "./state/store.js";
import App from "./App.jsx";

vi.mock("./features/flow/Home.jsx", async () => { const { PageHead } = await import("./components/ui.jsx"); return { default: () => <PageHead title="홈 화면" /> }; });
vi.mock("./features/flow/Cards.jsx", async () => { const { PageHead } = await import("./components/ui.jsx"); return { default: () => <PageHead title="추천 카드 화면" /> }; });
vi.mock("./features/flow/Draft.jsx", async () => { const { PageHead } = await import("./components/ui.jsx"); return { default: () => <PageHead title="승인할 글 화면" /> }; });
vi.mock("./features/flow/Done.jsx", () => ({ default: () => <p>처리 완료 화면</p> }));
vi.mock("./features/analysis/Analysis.jsx", () => ({ default: () => <p>리뷰 분석 화면</p> }));
vi.mock("./features/marketing/Marketing.jsx", () => ({ default: () => <p>맞춤 마케팅 화면</p> }));
vi.mock("./features/report/Report.jsx", () => ({ default: () => <p>종합 리포트 화면</p> }));
vi.mock("./features/market/Market.jsx", () => ({ default: () => <p>상권 분석 화면</p> }));
vi.mock("./features/assistant/Drawer.jsx", () => ({ default: () => <aside id="assistant" className="drawer" hidden /> }));

// 창 폭 흉내: band 는 "wide" | "mid" | "narrow"
function mockWidth(band) {
  const matches = (q) => (band === "narrow" ? q.includes("max-width: 760px") && !q.includes("min-width")
    : band === "mid" ? q.includes("min-width: 761px") : false);
  window.matchMedia = vi.fn((q) => ({ matches: matches(q), media: q, addEventListener() {}, removeEventListener() {} }));
}

const waitingResults = { card_a: { drafts: [{ draft_id: "d1", generator: "reply_draft" }, { draft_id: "d2", generator: "prevention_notice" }] } };

beforeEach(() => {
  resetStore();
  localStorage.clear();
  window.location.hash = "#/today";
  window.scrollTo = () => {};
  globalThis.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}), headers: { get: () => "application/json" } }));
  setState({ booted: true });
});
afterEach(() => { cleanup(); delete window.matchMedia; });

describe("덮는 메뉴 (761~1024px)", () => {
  it("열면 첫 메뉴 항목으로, Tab 은 메뉴 안에서만 돌고, Esc 로 닫으면 토글 버튼으로", () => {
    mockWidth("mid");
    render(<App />);
    const toggle = document.getElementById("menu-toggle");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(document.querySelector(".app").classList.contains("menu-over")).toBe(true);
    const side = document.getElementById("side-menu");
    expect(document.activeElement).toBe(side.querySelector(".menu-item"));
    expect(document.activeElement.textContent).toContain("홈");
    // 본문은 그동안 inert
    expect(document.querySelector(".main").hasAttribute("inert")).toBe(true);

    const all = [...side.querySelectorAll("a[href], button:not([disabled])")];
    const first = all[0], last = all[all.length - 1];
    last.focus();
    fireEvent.keyDown(document.activeElement, { key: "Tab" });
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(document.activeElement, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);

    fireEvent.keyDown(document.activeElement, { key: "Escape" });
    expect(document.querySelector(".app").classList.contains("menu-over")).toBe(false);
    expect(document.activeElement).toBe(toggle);
    expect(document.querySelector(".main").hasAttribute("inert")).toBe(false);
  });

  it("바깥을 누르거나 [메뉴 닫기]로 닫아도 토글 버튼으로 돌아온다", () => {
    mockWidth("mid");
    render(<App />);
    const toggle = document.getElementById("menu-toggle");
    fireEvent.click(toggle);
    fireEvent.click(document.getElementById("main"));
    expect(document.querySelector(".app").classList.contains("menu-over")).toBe(false);
    expect(document.activeElement).toBe(toggle);

    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("button", { name: "메뉴 닫기" }));
    expect(document.querySelector(".app").classList.contains("menu-over")).toBe(false);
    expect(document.activeElement).toBe(toggle);
  });

  it("메뉴 항목으로 다른 화면에 가면 그 화면 제목이 포커스를 가진다", async () => {
    mockWidth("mid");
    render(<App />);
    fireEvent.click(document.getElementById("menu-toggle"));
    const link = document.querySelector('#side-menu a[data-route="cards"]');
    link.focus();
    fireEvent.click(link);
    await act(async () => { window.location.hash = "#/cards"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(document.querySelector(".app").classList.contains("menu-over")).toBe(false);
    expect(document.activeElement.tagName).toBe("H1");
    expect(document.activeElement.textContent).toBe("추천 카드 화면");
  });

  it("넓은 화면에서는 덮지 않고 접기만 한다", () => {
    mockWidth("wide");
    render(<App />);
    fireEvent.click(document.getElementById("menu-toggle"));
    expect(document.querySelector(".app").classList.contains("menu-closed")).toBe(true);
    expect(document.querySelector(".app").classList.contains("menu-over")).toBe(false);
    expect(localStorage.getItem("ic26.menu")).toBe("closed");
  });
});

describe("승인 대기 수 (메뉴가 안 보일 때 상단 바)", () => {
  it("넓은 화면에서 메뉴를 접으면 상단 바에 승인 대기 칩", () => {
    mockWidth("wide");
    setState({ results: waitingResults });
    render(<App />);
    expect(document.getElementById("top-waiting")).toBeNull();   // 메뉴가 보이면 메뉴 옆 숫자만
    expect(screen.getByLabelText("승인 대기 2개", { selector: ".side .count" })).toBeTruthy();
    fireEvent.click(document.getElementById("menu-toggle"));
    const chip = screen.getByRole("link", { name: "승인 대기 2개" });
    expect(chip.getAttribute("href")).toBe("#/draft");
    expect(chip.closest(".top")).toBeTruthy();
  });

  it("761~1024px 에서는 메뉴가 접혀 있으니 칩이 처음부터 보인다", () => {
    mockWidth("mid");
    setState({ results: waitingResults, approved: new Set(["d1"]) });
    render(<App />);
    expect(screen.getByRole("link", { name: "승인 대기 1개" })).toBeTruthy();
  });

  it("다 승인했으면 칩이 없다", () => {
    mockWidth("mid");
    setState({ results: waitingResults, approved: new Set(["d1", "d2"]) });
    render(<App />);
    expect(document.getElementById("top-waiting")).toBeNull();
  });
});

describe("안내 문구", () => {
  it("시험용 실행이면 상단 띠 한 곳에만 짧게 알리고, 바닥 줄은 자료 출처만", () => {
    mockWidth("wide");
    setState({ health: { mode: "mock", mode_notice: "시험용 실행 · 키 없이 저장된 예시 결과를 보여 줍니다 (실제 AI 결과 아님)",
      parts: { reviews: "합성 데이터", briefing: "리뷰 분류: rule", cards: "규칙 + 고정 문장", generate: "저장본(김수현 C6 결과)" } } });
    render(<App />);
    expect(screen.getByRole("note").textContent).toBe("시험용 예시 화면 · 실제 AI 생성 결과가 아니에요");
    expect(document.body.textContent.match(/실제 AI/g)).toHaveLength(1);
    const foot = document.querySelector("footer.honesty");
    expect(foot.textContent).toBe("리뷰: 합성 데이터");
    expect(document.body.textContent).not.toMatch(/규칙 \+|리뷰 분류|김수현|C6|키 없이/);
  });

  it("실시간이면 띠가 없고 바닥 줄에 AI 생성 표시", () => {
    mockWidth("wide");
    setState({ health: { mode: "live", mode_notice: null, parts: { reviews: "합성 데이터", generate: "실시간 HCX-005" } } });
    render(<App />);
    expect(screen.queryByRole("note")).toBeNull();
    expect(document.querySelector("footer.honesty").textContent).toBe("리뷰: 합성 데이터글 생성: 실시간 HCX-005");
  });

  it("게스트 안내는 한 번: 메뉴 아래 '게스트' + [로그인], 상단 바 [로그인] (배지·긴 안내 없음)", () => {
    mockWidth("wide");
    render(<App />);
    expect(document.body.textContent).not.toMatch(/게스트 체험|로그인하고 가게 고르기/);
    expect(document.querySelector(".side .account b").textContent).toBe("게스트");
    expect(document.getElementById("acct-login").textContent).toBe("로그인");
    expect(document.querySelector(".side .logo-slot")).toBeNull();
    expect(document.querySelector(".side .brand .logo svg")).toBeTruthy();
  });
});
