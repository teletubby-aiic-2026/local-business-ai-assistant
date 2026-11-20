// 단계 전환 (11/20, state/stage.js · state/boot.js · state/account.js · lib/api.js): 부팅 분기, 로그인 → 가게 선택 → 가게 열기 → 메인 화면,
// 새로고침 유지, 로그아웃, 회원가입 → 새 가게 등록, 401 login_needed → 다시 로그인(하던 화면으로), 409 no_store → 가게 선택, 403 → 권한 없음,
// 로그인 표시 헤더. 메인 화면의 화면 8개와 서랍은 가짜로 바꿔 틀만 본다 (App.test.jsx 와 같은 방식)
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, act, waitFor } from "@testing-library/react";
import { resetStore, setState, getState } from "../../state/store.js";
import { boot } from "../../state/boot.js";
import { api, authHeaders, authStageOf, handleAuthError } from "../../lib/api.js";
import App from "../../App.jsx";

vi.mock("../flow/Home.jsx", async () => { const { PageHead } = await import("../../components/ui.jsx"); return { default: () => <PageHead title="홈 화면" /> }; });
vi.mock("../flow/Cards.jsx", () => ({ default: () => <p>추천 카드 화면</p> }));
vi.mock("../flow/Draft.jsx", () => ({ default: () => <p>승인할 글 화면</p> }));
vi.mock("../flow/Done.jsx", () => ({ default: () => <p>처리 완료 화면</p> }));
vi.mock("../analysis/Analysis.jsx", () => ({ default: () => <p>리뷰 분석 화면</p> }));
vi.mock("../marketing/Marketing.jsx", () => ({ default: () => <p>맞춤 마케팅 화면</p> }));
vi.mock("../report/Report.jsx", () => ({ default: () => <p>종합 리포트 화면</p> }));
vi.mock("../market/Market.jsx", async () => { const { PageHead } = await import("../../components/ui.jsx"); return { default: () => <PageHead title="상권 분석 화면" /> }; });
vi.mock("../assistant/Drawer.jsx", () => ({ default: () => <aside id="assistant" className="drawer" hidden /> }));

// 시험용 값 (실제 계정 아님)
const TEST_ID = "owner_test";
const TEST_PW = "test-only-pw-1";
const HEALTH = { mode: "mock", mode_notice: "시험용 실행 · …", parts: { reviews: "합성 데이터" } };
const GUEST = { authenticated: false, user: null, store_id: null, stores: [], demo_login: true };
const STORE = (id, name, extra = {}) => ({ store_id: id, name, business_type_name: "한식음식점", area_name: "장승배기역 4번", station_name: "장승배기역", sample: true, ...extra });
const STORES = [STORE("store_ongi", "온기한식"), STORE("store_basak", "바삭치킨", { business_type_name: "치킨전문점", area_name: "상도역 5번" })];
const meOf = (storeId, userId = "u1") => ({ authenticated: true, store_id: storeId, demo_login: true, stores: STORES,
  user: { user_id: userId, login_id: TEST_ID, display_name: "김시험", demo: false, created_at: "2026-11-15" } });
const BRIEFING = { store: { name: "온기한식" }, groups: [], counts: {}, snapshots: [] };

let calls, routes;
// "METHOD /path" 또는 "/path" → 값 | [상태, 값] | (body) => …  (없으면 200 {})
function server(extra = {}) {
  calls = [];
  routes = { "/api/health": HEALTH, "/api/briefing": BRIEFING, "/api/cards": { cards: [] }, "/api/insight": {}, "/api/approvals": { items: [] },
    "/api/market/status": { state: "ready" }, "/api/account/stores": { stores: STORES.map((s, i) => ({ ...s, menu_count: 3, last_opened: i === 0 })) }, ...extra };
  globalThis.fetch = vi.fn(async (path, opt = {}) => {
    const method = (opt.method || "GET").toUpperCase();
    const body = opt.body ? JSON.parse(opt.body) : undefined;
    calls.push({ path, method, body, headers: opt.headers || {} });
    const h = routes[`${method} ${path}`] ?? routes[path];
    const out = typeof h === "function" ? h(body) : h;
    const [status, data] = Array.isArray(out) ? out : [200, out ?? {}];
    return { ok: status < 400, status, json: async () => data, headers: { get: () => "application/json" } };
  });
}
const paths = () => calls.map((c) => c.path);
const sent = (method, path) => calls.filter((c) => c.method === method && c.path === path);
const STORE_DATA = ["/api/briefing", "/api/cards", "/api/insight", "/api/approvals", "/api/market/status"];
const h1 = () => document.querySelector("h1")?.textContent;

async function start() {
  await act(async () => { await boot(); });
  return render(<App />);
}

beforeEach(() => {
  resetStore();
  sessionStorage.clear();
  localStorage.clear();
  window.location.hash = "#/today";
  window.scrollTo = () => {};
  server();
});
afterEach(() => cleanup());

describe("부팅 분기", () => {
  it("로그인 전 → A1 로그인. 가게 자료는 부르지 않고, 시험용 안내 띠는 이 화면에도 한 곳", async () => {
    server({ "/api/auth/me": GUEST });
    await start();
    expect(getState().stage).toBe("login");
    expect(h1()).toBe("사장님 로그인");
    expect(document.activeElement.tagName).toBe("H1");
    expect(screen.getAllByRole("note")).toHaveLength(1);
    expect(screen.getByRole("note").textContent).toBe("시험용 예시 화면 · 실제 AI 생성 결과가 아니에요");
    expect(paths()).toContain("/api/health");
    STORE_DATA.forEach((p) => expect(paths()).not.toContain(p));
    expect(document.querySelector(".app")).toBeNull();   // 게스트로는 메인 화면에 들어가지 않음
    expect(sent("GET", "/api/auth/me")[0].headers["X-IC26-Signed-In"]).toBeUndefined();
  });

  it("로그인 + 이 탭에서 들어갔던 가게가 그대로 → 메인 화면 (새로고침해도 보던 화면)", async () => {
    sessionStorage.setItem("ic26.entered", "store_basak");
    window.location.hash = "#/market";
    server({ "/api/auth/me": meOf("store_basak") });
    await start();
    expect(getState().stage).toBe("app");
    expect(getState().entered).toBe("store_basak");
    expect(document.querySelector(".app")).toBeTruthy();
    expect(h1()).toBe("상권 분석 화면");
    await waitFor(() => STORE_DATA.forEach((p) => expect(paths()).toContain(p)));
    // 로그인한 동안은 모든 요청에 로그인 표시
    expect(sent("GET", "/api/briefing")[0].headers["X-IC26-Signed-In"]).toBe("1");
    expect(sent("GET", "/api/market/status")[0].headers["X-IC26-Signed-In"]).toBe("1");
    expect(getState().booted).toBe(true);
  });

  it("로그인만 (들어간 가게가 없거나 서버의 지금 가게와 다름) → A3 가게 선택", async () => {
    sessionStorage.setItem("ic26.entered", "store_ongi");
    server({ "/api/auth/me": meOf("store_basak") });
    await start();
    expect(getState().stage).toBe("pick");
    expect(h1()).toBe("어느 가게를 볼까요?");
    STORE_DATA.forEach((p) => expect(paths()).not.toContain(p));
  });

  it("신원을 못 받거나(5xx) 서버가 notice 를 주면 X1 오류, [다시 시도]로 다시 부팅", async () => {
    server({ "/api/auth/me": [503, { error: { message: "잠시 뒤 다시", state: "down" } }] });
    await start();
    expect(getState().stage).toBe("error");
    expect(h1()).toBe("잠시 문제가 생겼어요");
    routes["/api/auth/me"] = { ...GUEST, notice: "로그인 정보를 확인하지 못했어요. 잠시 뒤 다시 해 주세요." };
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "다시 시도" })); });
    await waitFor(() => expect(screen.getByText("로그인 정보를 확인하지 못했어요. 잠시 뒤 다시 해 주세요.")).toBeTruthy());
    expect(getState().stage).toBe("error");
    routes["/api/auth/me"] = GUEST;
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "다시 시도" })); });
    await waitFor(() => expect(getState().stage).toBe("login"));
  });
});

describe("로그인 → 가게 선택 → 가게 열기", () => {
  it("로그인하면 A3, [이 가게 열기]는 POST /api/auth/store 뒤 그 가게의 홈. 새로고침해도 그대로", async () => {
    window.location.hash = "#/report";
    server({ "/api/auth/me": GUEST, "POST /api/auth/login": meOf("store_ongi"), "POST /api/auth/store": (b) => meOf(b.store_id) });
    const view = await start();
    fireEvent.change(document.querySelector('#auth-login input[name="login_id"]'), { target: { value: TEST_ID } });
    fireEvent.change(document.querySelector('#auth-login input[name="password"]'), { target: { value: TEST_PW } });
    await act(async () => { fireEvent.submit(document.getElementById("auth-login")); });
    await waitFor(() => expect(getState().stage).toBe("pick"));
    expect(sessionStorage.getItem("ic26.entered")).toBeNull();   // 새 로그인은 가게 선택부터
    const cards = await screen.findAllByRole("button", { name: "이 가게 열기" });
    STORE_DATA.forEach((p) => expect(paths()).not.toContain(p));
    await act(async () => { fireEvent.click(cards[1]); });       // 바삭치킨
    await waitFor(() => expect(getState().stage).toBe("app"));
    expect(sent("POST", "/api/auth/store")[0].body).toEqual({ store_id: "store_basak" });
    expect(sent("POST", "/api/auth/store")[0].headers["X-IC26-Signed-In"]).toBe("1");
    expect(window.location.hash).toBe("#/today");
    expect(sessionStorage.getItem("ic26.entered")).toBe("store_basak");
    await waitFor(() => expect(paths()).toContain("/api/briefing"));
    expect(document.getElementById("store-name").textContent).toBe("바삭치킨 (가상)");

    // 새로고침: 같은 탭의 sessionStorage 는 남고 서버의 지금 가게도 그대로
    view.unmount();
    resetStore();
    server({ "/api/auth/me": meOf("store_basak") });
    await start();
    expect(getState().stage).toBe("app");
    expect(h1()).toBe("홈 화면");
  });

  it("상단 바 [바꾸기]로 A3, 들어가 있던 가게를 다시 열면 서버를 부르지 않고 홈으로", async () => {
    sessionStorage.setItem("ic26.entered", "store_ongi");
    server({ "/api/auth/me": meOf("store_ongi") });
    await start();
    await waitFor(() => expect(getState().booted).toBe(true));
    act(() => { fireEvent.click(document.getElementById("acct-store")); });
    expect(getState().stage).toBe("pick");
    const before = calls.length;
    const cards = await screen.findAllByRole("button", { name: "이 가게 열기" });
    await act(async () => { fireEvent.click(cards[0]); });       // 온기한식 (last_opened, 맨 앞)
    expect(getState().stage).toBe("app");
    expect(calls.slice(before).some((c) => c.path === "/api/auth/store" || c.path === "/api/briefing")).toBe(false);
  });
});

describe("로그아웃 · 회원가입", () => {
  it("로그아웃하면 A1, 들어간 가게와 가게 자료를 지움", async () => {
    sessionStorage.setItem("ic26.entered", "store_ongi");
    server({ "/api/auth/me": meOf("store_ongi"), "POST /api/auth/logout": GUEST });
    await start();
    await waitFor(() => expect(getState().booted).toBe(true));
    act(() => setState({ drawerOpen: true }));
    const out = [...document.querySelectorAll(".side .account button")].find((b) => b.textContent === "로그아웃");
    await act(async () => { fireEvent.click(out); });
    await waitFor(() => expect(getState().stage).toBe("login"));
    expect(sessionStorage.getItem("ic26.entered")).toBeNull();
    expect(getState().drawerOpen).toBe(false);
    expect(getState().briefing).toBeNull();
    expect(getState().me.authenticated).toBe(false);
    expect(h1()).toBe("사장님 로그인");
  });

  it("A1 → 회원가입 → 가입하면 새 가게 등록(자리), [가게 선택으로]", async () => {
    server({ "/api/auth/me": GUEST, "POST /api/auth/signup": [201, { ...meOf(null), stores: [] }], "/api/account/stores": { stores: [] } });
    await start();
    act(() => { fireEvent.click(screen.getByRole("button", { name: "회원가입" })); });
    expect(h1()).toBe("계정 만들기");
    const set = (name, value) => fireEvent.change(document.querySelector(`#auth-signup input[name="${name}"]`), { target: { value } });
    set("login_id", "newowner"); set("password", TEST_PW); set("password_confirm", TEST_PW); set("display_name", "새사장");
    fireEvent.click(screen.getByLabelText("이용 약관과 개인정보 처리에 동의해요 (필수)"));
    await act(async () => { fireEvent.submit(document.getElementById("auth-signup")); });
    await waitFor(() => expect(getState().stage).toBe("store-new"));
    expect(sent("POST", "/api/auth/signup")[0].body.stores).toEqual([]);
    expect(h1()).toBe("새 가게 등록");
    act(() => { fireEvent.click(screen.getByRole("button", { name: "가게 선택으로" })); });
    expect(getState().stage).toBe("pick");
    expect(await screen.findByText("아직 등록한 가게가 없어요")).toBeTruthy();
  });
});

describe("로그인·가게 상태 오류 (lib/api.js)", () => {
  it("상태 코드 → 단계: 401 login_needed · 409 no_store · 403 not_your_store 만", () => {
    expect(authStageOf(401, "login_needed")).toBe("expired");
    expect(authStageOf(409, "no_store")).toBe("pick");
    expect(authStageOf(403, "not_your_store")).toBe("forbidden");
    expect(authStageOf(401, "bad_login")).toBeNull();
    expect(authStageOf(401, "bad_password")).toBeNull();
    expect(authStageOf(403, "demo_account")).toBeNull();
    expect(authStageOf(409, "conflict")).toBeNull();
    setState({ me: GUEST });
    expect(authHeaders()).toEqual({});
    setState({ me: meOf("store_ongi") });
    expect(authHeaders()).toEqual({ "X-IC26-Signed-In": "1" });
  });

  it("401 login_needed → '다시 로그인해 주세요', 같은 사장님·같은 가게로 다시 로그인하면 하던 화면 그대로", async () => {
    sessionStorage.setItem("ic26.entered", "store_ongi");
    window.location.hash = "#/market";
    server({ "/api/auth/me": meOf("store_ongi") });
    await start();
    await waitFor(() => expect(getState().booted).toBe(true));
    act(() => setState({ approved: new Set(["d1"]) }));          // 하던 진행
    routes["/api/cards"] = [401, { error: { message: "다시 로그인해 주세요.", state: "login_needed" } }];
    await act(async () => { await api("/api/cards").catch(() => {}); });
    expect(getState().stage).toBe("expired");
    expect(h1()).toBe("다시 로그인해 주세요");
    expect(authHeaders()).toEqual({});                            // 끝난 로그인은 표시하지 않음
    act(() => { fireEvent.click(screen.getByRole("button", { name: "로그인" })); });
    expect(getState().stage).toBe("login");
    expect(document.querySelector('#auth-login input[name="login_id"]').value).toBe(TEST_ID);
    routes["POST /api/auth/login"] = meOf("store_ongi");
    fireEvent.change(document.querySelector('#auth-login input[name="password"]'), { target: { value: TEST_PW } });
    await act(async () => { fireEvent.submit(document.getElementById("auth-login")); });
    await waitFor(() => expect(getState().stage).toBe("app"));
    expect(window.location.hash).toBe("#/market");
    expect(h1()).toBe("상권 분석 화면");
    expect(getState().approved.has("d1")).toBe(true);
    expect(sent("POST", "/api/auth/store")).toHaveLength(0);
  });

  it("다른 사장님으로 다시 로그인하면 가게 선택부터 (진행은 비움)", async () => {
    sessionStorage.setItem("ic26.entered", "store_ongi");
    server({ "/api/auth/me": meOf("store_ongi") });
    await start();
    await waitFor(() => expect(getState().booted).toBe(true));
    act(() => setState({ approved: new Set(["d1"]) }));
    await act(async () => { handleAuthError({ status: 401, state: "login_needed" }); });
    act(() => { fireEvent.click(screen.getByRole("button", { name: "로그인" })); });
    routes["POST /api/auth/login"] = meOf("store_ongi", "u2");
    fireEvent.change(document.querySelector('#auth-login input[name="login_id"]'), { target: { value: "other_owner" } });
    fireEvent.change(document.querySelector('#auth-login input[name="password"]'), { target: { value: TEST_PW } });
    await act(async () => { fireEvent.submit(document.getElementById("auth-login")); });
    await waitFor(() => expect(getState().stage).toBe("pick"));
    expect(getState().approved.size).toBe(0);
  });

  it("409 no_store → 가게 선택, 403 not_your_store → 권한 없음 카드([가게 선택으로]·[로그아웃])", async () => {
    sessionStorage.setItem("ic26.entered", "store_ongi");
    server({ "/api/auth/me": meOf("store_ongi") });
    await start();
    await waitFor(() => expect(getState().booted).toBe(true));
    routes["/api/briefing"] = [409, { error: { message: "가게를 먼저 골라 주세요.", state: "no_store" } }];
    await act(async () => { await api("/api/briefing").catch(() => {}); });
    expect(getState().stage).toBe("pick");
    expect(sessionStorage.getItem("ic26.entered")).toBeNull();

    routes["POST /api/auth/store"] = [403, { error: { message: "내 가게가 아니에요.", state: "not_your_store" } }];
    const cards = await screen.findAllByRole("button", { name: "이 가게 열기" });
    await act(async () => { fireEvent.click(cards[1]); });
    expect(getState().stage).toBe("forbidden");
    expect(h1()).toBe("이 가게를 볼 권한이 없어요");
    expect(screen.getByRole("button", { name: "로그아웃" })).toBeTruthy();
    act(() => { fireEvent.click(screen.getByRole("button", { name: "가게 선택으로" })); });
    expect(getState().stage).toBe("pick");
  });

  it("로그인 전 단계에 늦게 온 401·409 는 무시", async () => {
    server({ "/api/auth/me": GUEST });
    await start();
    expect(handleAuthError({ status: 401, state: "login_needed" })).toBe(false);
    expect(handleAuthError({ status: 409, state: "no_store" })).toBe(false);
    expect(getState().stage).toBe("login");
  });
});
