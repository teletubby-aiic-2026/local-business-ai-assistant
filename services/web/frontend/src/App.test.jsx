// 화면 틀: 덮는 메뉴(761~1024px)의 포커스 가두기·Esc·돌려주기, 메뉴가 안 보일 때 상단 바의 승인 대기 수,
// 시험용 안내 띠 한 곳, 사장님 칸 문구. 화면 8개와 서랍은 가짜로 바꿔 틀만 본다 (화면 시험은 각 화면 폴더에).
// 11/20 단계 전환 뒤로 메인 화면(틀)은 로그인하고 가게에 들어간 app 단계에서만 그린다 (부팅·로그인 흐름 시험은 features/account/stages.test.jsx)
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import { resetStore, setState, getState } from "./state/store.js";
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

// 로그인하고 가게에 들어간 사장님 (시험용 값)
const ME = { authenticated: true, store_id: "store_ongi", demo_login: false,
  user: { user_id: "u-test", login_id: "owner_test", display_name: "김시험", demo: false, created_at: "2026-11-15" },
  stores: [{ store_id: "store_ongi", name: "온기한식", business_type_name: "한식음식점", area_name: "장승배기역 4번", station_name: "장승배기역", sample: true }] };

beforeEach(() => {
  resetStore();
  localStorage.clear();
  window.location.hash = "#/today";
  window.scrollTo = () => {};
  globalThis.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}), headers: { get: () => "application/json" } }));
  setState({ booted: true, stage: "app", me: ME, entered: "store_ongi" });
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

  // 11/20: 예전 시험은 메뉴 안 [로그인]이 로그인 창을 여는 것이었다. 로그인 창이 없어지고(로그인은 단계 화면) 메뉴 아래에는
  // '프로필'이 생겨서, 프로필로 가면 메뉴와 본문 inert 가 함께 사라지는지 + 창(dialog[open])이 떠 있으면 Tab 을 가로채지 않는지로 바꿈
  it("메뉴 안 '프로필'을 누르면 메뉴째 사라지고 프로필 단계로, 창이 떠 있으면 Tab 을 가로채지 않는다", () => {
    mockWidth("mid");
    render(<App />);
    fireEvent.click(document.getElementById("menu-toggle"));
    const extra = document.createElement("dialog");
    document.body.appendChild(extra);
    extra.setAttribute("open", "");
    const ev = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    document.body.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
    extra.remove();
    const side = document.getElementById("side-menu");
    const profile = [...side.querySelectorAll("button")].find((b) => b.textContent === "프로필");
    act(() => { fireEvent.click(profile); });
    expect(getState().stage).toBe("profile");
    expect(document.getElementById("side-menu")).toBeNull();
    expect(document.querySelector(".main")).toBeNull();
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

  // 11/20: 게스트로는 메인 화면에 들어오지 않으므로 '게스트 + [로그인]' 시험을 사장님 칸 시험으로 바꿈 (Figma 06 B1)
  it("사장님 칸: 메뉴 아래 첫 글자 · '{이름} 사장님' · '프로필 · 로그아웃', 상단 바 가게 칩(예시면 '(가상)')과 [바꾸기]·이름 버튼", () => {
    mockWidth("wide");
    render(<App />);
    expect(document.body.textContent).not.toMatch(/게스트|로그인하고 가게 고르기/);
    expect(document.getElementById("acct-login")).toBeNull();
    expect(document.querySelector(".side .account .face").textContent).toBe("김");
    expect(document.querySelector(".side .account b").textContent).toBe("김시험 사장님");
    expect([...document.querySelectorAll(".side .account button")].map((b) => b.textContent)).toEqual(["프로필", "로그아웃"]);
    expect(document.getElementById("store-name").textContent).toBe("온기한식 (가상)");
    expect(document.querySelector(".store-pick .sp-sub").textContent).toBe("한식음식점 · 장승배기역 4번 상권");
    expect(document.querySelector("#acct-store").tagName).toBe("BUTTON");
    expect(document.querySelector(".top select")).toBeNull();
    expect(document.getElementById("acct-user").textContent).toBe("김시험 사장님");
    expect(document.querySelector(".side .logo-slot")).toBeNull();
    expect(document.querySelector(".side .brand .logo svg")).toBeTruthy();
    act(() => { fireEvent.click(document.getElementById("acct-store")); });
    expect(getState().stage).toBe("pick");
  });
});

describe("휴대폰 (760px 이하): 아래 탭 + 묶음 하위 탭 + 한 줄 상단 바", () => {
  it("왼쪽 메뉴 대신 아래 탭 5칸, 현재 탭 표시, '오늘 처리'에 승인 대기 수", () => {
    mockWidth("narrow");
    setState({ results: waitingResults });
    render(<App />);
    expect(document.getElementById("side-menu")).toBeNull();
    const bar = document.querySelector(".tabbar");
    expect(bar.getAttribute("aria-label")).toBe("메뉴");
    expect([...bar.querySelectorAll(".tab-label")].map((x) => x.textContent)).toEqual(["홈", "오늘 처리", "AI에게 묻기", "살펴보기", "마케팅"]);
    expect(bar.querySelector('[aria-current="page"] .tab-label').textContent).toBe("홈");
    const flow = [...bar.querySelectorAll("a.tab")].find((a) => a.textContent.includes("오늘 처리"));
    expect(flow.getAttribute("href")).toBe("#/draft");               // 승인 대기가 있으면 승인할 글로
    expect(flow.querySelector(".count").getAttribute("aria-label")).toBe("승인 대기 2개");
    expect(document.getElementById("top-waiting")).toBeNull();       // 상단 바 칩은 넓은 화면에서만
  });

  it("가운데 'AI에게 묻기'가 서랍을 열고, 상단 바에는 같은 이름 버튼이 하나만", () => {
    mockWidth("narrow");
    render(<App />);
    const asks = screen.getAllByRole("button", { name: "AI에게 묻기" });
    expect(asks).toHaveLength(1);
    expect(asks[0].closest(".tabbar")).toBeTruthy();
    fireEvent.click(asks[0]);
    expect(asks[0].getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(asks[0]);   // 한 번 더 눌러도 닫히지 않는다 (닫기는 서랍의 닫기·Esc)
    expect(asks[0].getAttribute("aria-expanded")).toBe("true");
  });

  it("살펴보기 화면에서는 하위 탭(리뷰 분석·상권 분석·종합 리포트)과 현재 화면 표시, 홈에는 하위 탭 없음", async () => {
    mockWidth("narrow");
    await new Promise((r) => setTimeout(r, 0));   // 앞 시험의 링크 누르기가 남긴 늦은 주소 이동(#/cards)을 먼저 흘려보낸다
    window.location.hash = "#/market";
    render(<App />);
    const nav = document.querySelector(".group-nav");
    expect(nav.getAttribute("aria-label")).toBe("살펴보기");
    expect([...nav.querySelectorAll("a")].map((a) => a.textContent)).toEqual(["리뷰 분석", "상권 분석", "종합 리포트"]);
    expect(nav.querySelector('[aria-current="page"]').textContent).toBe("상권 분석");
    expect(document.querySelector('.tabbar [aria-current="page"] .tab-label').textContent).toBe("살펴보기");
    await act(async () => { window.location.hash = "#/today"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });   // jsdom 의 늦은 hashchange 까지 지나가게
    expect(document.querySelector(".group-nav")).toBeNull();
  });

  // 11/20: 계정 단추가 [로그인](#acct-login)에서 이름 버튼(#acct-user → 사장님 프로필) 하나로 바뀌어 그 단추를 봄
  it("상단 바 계정 단추는 그림 단추지만 이름(읽기 프로그램)과 id 는 그대로, 누르면 사장님 프로필", () => {
    mockWidth("narrow");
    render(<App />);
    const user = document.getElementById("acct-user");
    expect(user.classList.contains("icon-btn")).toBe(true);
    expect(user.querySelector(".sr").textContent).toBe("김시험 사장님");
    expect(user.querySelector("svg")).toBeTruthy();
    expect(document.querySelector(".top .top-logo")).toBeTruthy();
    expect(document.getElementById("acct-store")).toBeTruthy();
    act(() => { fireEvent.click(user); });
    expect(getState().stage).toBe("profile");
  });

  it("넓은 화면에서는 아래 탭·하위 탭을 그리지 않는다", () => {
    mockWidth("wide");
    window.location.hash = "#/market";
    render(<App />);
    expect(document.querySelector(".tabbar")).toBeNull();
    expect(document.querySelector(".group-nav")).toBeNull();
    expect(document.getElementById("side-menu")).toBeTruthy();
  });
});
