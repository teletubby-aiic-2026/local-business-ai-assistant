// 계정 창: 로그인 실패 때 비밀번호를 지우지 않음 · 성공·닫기 때만 비움 · 로그아웃 뒤 상단 바 [로그인]으로 포커스 ·
// 내 계정 창(공통 Dialog)의 [로그아웃]·확인 단계 경고·Esc
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, act, waitFor } from "@testing-library/react";
import { resetStore, setState, getState } from "../../state/store.js";
import { acctLogout } from "../../state/account.js";
import Topbar from "../../components/Topbar.jsx";
import AuthDialog from "./AuthDialog.jsx";
import AccountDialog from "./AccountDialog.jsx";

// 시험용 값 (실제 계정 아님)
const TEST_ID = "owner_test";
const TEST_PW = "test-only-pw-1";

const ME = { authenticated: true, store_id: "store_ongi", user: { display_name: "김시험", login_id: TEST_ID },
  stores: [{ store_id: "store_ongi", name: "온기한식" }, { store_id: "store_basak", name: "바삭치킨" }] };
const GUEST = { authenticated: false, demo_login: false };

let calls;
// handler(path, opt) → [status, body] (없으면 200 {})
function mockFetch(handler = () => null) {
  calls = [];
  globalThis.fetch = vi.fn(async (path, opt = {}) => {
    calls.push({ path, method: opt.method || "GET" });
    const [status, body] = handler(path, opt) || [200, {}];
    return { ok: status < 400, status, json: async () => body, headers: { get: () => "application/json" } };
  });
}

beforeEach(() => {
  resetStore();
  window.scrollTo = () => {};
  mockFetch();
});
afterEach(() => cleanup());

function openLogin() {
  setState({ me: GUEST, booted: true });
  const view = render(<><Topbar /><AuthDialog /></>);
  act(() => setState({ authOpen: true }));
  fireEvent.change(document.querySelector('#auth-panel-login input[name="login_id"]'), { target: { value: TEST_ID } });
  fireEvent.change(document.querySelector('#auth-panel-login input[name="password"]'), { target: { value: TEST_PW } });
  return view;
}
const pwBox = () => document.querySelector('#auth-panel-login input[name="password"]');

describe("로그인 창", () => {
  it("로그인에 실패하면 친 비밀번호를 그대로 두고 오류를 보인다", async () => {
    mockFetch((path) => (path === "/api/auth/login" ? [401, { error: { message: "아이디 또는 비밀번호가 맞지 않아요." } }] : null));
    openLogin();
    fireEvent.submit(document.getElementById("auth-panel-login"));
    expect(await screen.findByText("아이디 또는 비밀번호가 맞지 않아요.")).toBeTruthy();
    expect(pwBox().value).toBe(TEST_PW);
    expect(getState().authOpen).toBe(true);
  });

  it("성공하면 창을 닫고 비밀번호를 비운다", async () => {
    mockFetch((path) => (path === "/api/auth/login" ? [200, ME] : null));
    openLogin();
    fireEvent.submit(document.getElementById("auth-panel-login"));
    await waitFor(() => expect(getState().authOpen).toBe(false));
    await waitFor(() => expect(pwBox().value).toBe(""));
    expect(calls.map((c) => c.path)).toContain("/api/auth/login");
  });

  it("[닫기]로 닫아도 비밀번호를 비운다", () => {
    openLogin();
    fireEvent.click(screen.getAllByRole("button", { name: "닫기" })[0]);
    expect(getState().authOpen).toBe(false);
    expect(pwBox().value).toBe("");
  });

  it("문구: 시연 버튼은 짧게, '1초'·'다점포' 같은 군말 없이", () => {
    setState({ me: { authenticated: false }, authOpen: true });
    render(<AuthDialog />);
    expect(screen.getByRole("button", { name: "시연 계정으로 시작" })).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/1초|다점포|체험할 수 있어요/);
  });
});

describe("로그아웃", () => {
  it("끝나면 상단 바의 [로그인]으로 포커스", async () => {
    mockFetch((path) => (path === "/api/auth/logout" ? [200, { authenticated: false }] : null));
    setState({ me: ME, booted: true });
    render(<Topbar />);
    document.getElementById("acct-user").focus();
    await act(async () => { await acctLogout(); });
    await waitFor(() => expect(document.activeElement?.id).toBe("acct-login"));
    expect(getState().acctBusy).toBe(false);
  });

  it("내 계정 창의 [로그아웃]: 창을 닫고 로그아웃한 뒤 [로그인]으로", async () => {
    mockFetch((path) => (path === "/api/auth/logout" ? [200, { authenticated: false }] : null));
    setState({ me: ME, booted: true });
    render(<><Topbar /><AccountDialog /></>);
    act(() => setState({ acctOpen: true }));
    const dlg = document.getElementById("acct-dialog");
    expect(dlg.hasAttribute("open")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "로그아웃" }));
    expect(dlg.hasAttribute("open")).toBe(false);
    await waitFor(() => expect(document.activeElement?.id).toBe("acct-login"));
    expect(calls.some((c) => c.path === "/api/auth/logout" && c.method === "POST")).toBe(true);
  });
});

describe("내 계정 창", () => {
  it("공통 Dialog: 회원 탈퇴 확인 단계에 '되돌릴 수 없어요'가 남고, Esc 는 확인 단계만 취소", () => {
    setState({ me: ME, booted: true });
    render(<><Topbar /><AccountDialog /></>);
    act(() => setState({ acctOpen: true }));
    const dlg = document.getElementById("acct-dialog");
    expect(dlg.classList.contains("dialog")).toBe(true);
    expect(dlg.getAttribute("aria-labelledby")).toBe("acct-title");
    fireEvent.click(screen.getByRole("button", { name: "회원 탈퇴" }));
    expect(dlg.getAttribute("aria-labelledby")).toBe("acct-confirm-title");
    expect(screen.getByText("탈퇴하면 되돌릴 수 없어요.")).toBeTruthy();
    fireEvent.keyDown(dlg, { key: "Escape" });
    expect(dlg.getAttribute("aria-labelledby")).toBe("acct-title");
    expect(dlg.hasAttribute("open")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: `온기한식 기록 지우기` }));
    expect(screen.getByText("지우면 되돌릴 수 없어요.")).toBeTruthy();
  });

  it("상단 바 이름 버튼은 내 계정 창을 가리킨다 (aria-controls 가 실제 id)", () => {
    setState({ me: ME, booted: true });
    render(<><Topbar /><AccountDialog /></>);
    expect(document.getElementById(document.getElementById("acct-user").getAttribute("aria-controls"))).toBeTruthy();
  });
});
