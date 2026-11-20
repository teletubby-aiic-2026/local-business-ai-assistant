// 계정 화면 (11/20 단계 전환, Figma '06 설계 기준 화면' A1·A2·A3·A5).
// 예전 이 파일은 로그인 창(AuthDialog)·내 계정 창을 봤다. 창이 화면으로 바뀌어 같은 약속을 화면에서 다시 본다:
// 로그인 실패 때 비밀번호 유지 · 시연 버튼은 시험용 실행에서만 · 가게 카드 · 프로필의 이름 저장·가게 빼기·순서·기록 지우기·탈퇴 확인 문구
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, act, waitFor, within } from "@testing-library/react";
import { resetStore, setState, getState } from "../../state/store.js";
import Login from "./Login.jsx";
import Signup from "./Signup.jsx";
import PickStore from "./PickStore.jsx";
import Profile from "./Profile.jsx";

// 시험용 값 (실제 계정 아님)
const TEST_ID = "owner_test";
const TEST_PW = "test-only-pw-1";
const MOCK_HEALTH = { mode: "mock", mode_notice: "시험용 실행 · …", parts: { reviews: "합성 데이터" } };
const LIVE_HEALTH = { mode: "live", mode_notice: null, parts: { reviews: "합성 데이터" } };
const GUEST = { authenticated: false, user: null, store_id: null, stores: [], demo_login: true };
const STORES = [
  { store_id: "store_ongi", name: "온기한식", business_type_name: "한식음식점", area_name: "장승배기역 4번", station_name: "장승배기역", sample: true, menu_count: 9, last_opened: false },
  { store_id: "store_basak", name: "바삭치킨", business_type_name: "치킨전문점", area_name: "상도역 5번", station_name: "상도역", sample: true, menu_count: 7, last_opened: true },
  { store_id: "st_mine", name: "우리분식", business_type_name: "분식전문점", area_name: "노량진역", station_name: "노량진역", sample: false, menu_count: 4, last_opened: false },
];
const ME = { authenticated: true, store_id: "store_basak", demo_login: false,
  user: { user_id: "u1", login_id: TEST_ID, display_name: "김시험", demo: false, created_at: "2026-11-15" },
  stores: STORES.map(({ menu_count, last_opened, ...s }) => s) };

let calls;
// routes: {"METHOD /path" 또는 "/path": 값 | [상태, 값] | (body) => …}
function server(routes = {}) {
  calls = [];
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
const sent = (method, path) => calls.filter((c) => c.method === method && c.path === path);

beforeEach(() => {
  resetStore();
  sessionStorage.clear();
  window.scrollTo = () => {};
  server();
});
afterEach(() => cleanup());

describe("A1 로그인", () => {
  function fill() {
    fireEvent.change(document.querySelector('#auth-login input[name="login_id"]'), { target: { value: TEST_ID } });
    fireEvent.change(document.querySelector('#auth-login input[name="password"]'), { target: { value: TEST_PW } });
  }
  const pwBox = () => document.querySelector('#auth-login input[name="password"]');

  it("열면 제목에 포커스, 실패하면 친 비밀번호를 그대로 두고 오류를 보인다", async () => {
    server({ "POST /api/auth/login": [401, { error: { message: "아이디 또는 비밀번호가 맞지 않아요.", state: "bad_login" } }] });
    setState({ stage: "login", me: GUEST, health: MOCK_HEALTH });
    render(<Login />);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1, name: "사장님 로그인" }));
    fill();
    fireEvent.submit(document.getElementById("auth-login"));
    expect(await screen.findByText("아이디 또는 비밀번호가 맞지 않아요.")).toBeTruthy();
    expect(pwBox().value).toBe(TEST_PW);
    expect(getState().stage).toBe("login");   // 401 bad_login 은 단계를 바꾸지 않음
    expect(sent("POST", "/api/auth/login")[0].body).toEqual({ login_id: TEST_ID, password: TEST_PW, keep: false });
  });

  it("'로그인 상태 유지'를 켜면 keep: true, 빈 칸이면 보내지 않음", async () => {
    server({ "POST /api/auth/login": ME });
    setState({ stage: "login", me: GUEST });
    render(<Login />);
    fireEvent.submit(document.getElementById("auth-login"));
    expect(screen.getByRole("alert").textContent).toBe("아이디와 비밀번호를 적어 주세요.");
    expect(sent("POST", "/api/auth/login")).toHaveLength(0);
    fill();
    fireEvent.click(screen.getByLabelText("로그인 상태 유지 (7일)"));
    fireEvent.submit(document.getElementById("auth-login"));
    await waitFor(() => expect(getState().stage).toBe("pick"));
    expect(sent("POST", "/api/auth/login")[0].body.keep).toBe(true);
  });

  it("'비밀번호를 잊었어요'는 그 자리에 한 줄만", () => {
    setState({ stage: "login", me: GUEST });
    render(<Login />);
    const line = "비밀번호 찾기는 아직 지원하지 않아요. 새 계정을 만들어 주세요.";
    expect(screen.getByText(line).hidden).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "비밀번호를 잊었어요" }));
    expect(screen.getByText(line).hidden).toBe(false);
  });

  it("시연 버튼은 시험용 실행이고 서버가 시연 계정을 켜 둔 때만 (실제 서버에서는 숨김)", async () => {
    const NAME = "시연 사장님으로 1초 시작 (가게 3곳)";
    setState({ stage: "login", me: GUEST, health: LIVE_HEALTH });
    const view = render(<Login />);
    expect(screen.queryByRole("button", { name: NAME })).toBeNull();
    act(() => setState({ me: { ...GUEST, demo_login: false }, health: MOCK_HEALTH }));
    expect(screen.queryByRole("button", { name: NAME })).toBeNull();
    act(() => setState({ me: GUEST, health: null }));          // 서버 상태를 못 받았으면 실제 서버로 봄
    expect(screen.queryByRole("button", { name: NAME })).toBeNull();
    act(() => setState({ health: MOCK_HEALTH }));
    const demo = screen.getByRole("button", { name: NAME });
    expect(demo.id).toBe("auth-demo");
    server({ "POST /api/auth/demo-login": { ...ME, user: { ...ME.user, demo: true } } });
    fireEvent.click(demo);
    await waitFor(() => expect(getState().stage).toBe("pick"));
    view.unmount();
  });
});

describe("A2 회원가입", () => {
  it("규칙에 맞지 않으면 보내지 않고 그 칸으로, 맞으면 가게 없이 가입", async () => {
    server({ "POST /api/auth/signup": [201, { ...ME, store_id: null, stores: [] }] });
    setState({ stage: "signup", me: GUEST });
    render(<Signup />);
    const set = (name, value) => fireEvent.change(document.querySelector(`#auth-signup input[name="${name}"]`), { target: { value } });
    set("login_id", "New_Owner"); set("password", TEST_PW); set("password_confirm", "different-pw"); set("display_name", "새사장");
    fireEvent.submit(document.getElementById("auth-signup"));
    expect(screen.getByRole("alert").textContent).toBe("비밀번호 확인이 맞지 않아요.");
    expect(document.activeElement.name).toBe("password_confirm");
    set("password_confirm", TEST_PW);
    fireEvent.submit(document.getElementById("auth-signup"));
    expect(screen.getByRole("alert").textContent).toBe("이용 약관과 개인정보 처리에 동의해 주세요.");
    expect(screen.getByText("아이디·이름·가게 정보를 저장해요. 탈퇴하면 계정과 기록을 지워요.")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("이용 약관과 개인정보 처리에 동의해요 (필수)"));
    expect(sent("POST", "/api/auth/signup")).toHaveLength(0);
    fireEvent.submit(document.getElementById("auth-signup"));
    await waitFor(() => expect(getState().stage).toBe("store-new"));
    expect(sent("POST", "/api/auth/signup")[0].body).toEqual({ login_id: "new_owner", password: TEST_PW, display_name: "새사장", stores: [] });
    expect(getState().storeNew).toEqual({ mode: "signup" });
  });
});

describe("A3 가게 선택", () => {
  const SUMS = {
    store_ongi: { state: "ready", reviews: 40, complaints: 12, headline: "포장 누락 3건 반복", tone: "bad" },
    store_basak: { state: "ready", reviews: 30, complaints: 5, headline: "오늘 할 일 끝", tone: "good" },
    st_mine: { state: "unavailable", reviews: null, complaints: null, headline: "기록을 불러오지 못했어요", tone: "muted" },
  };
  function pickServer(stores = STORES) {
    const routes = { "/api/account/stores": { stores } };
    stores.forEach((s) => { routes[`/api/account/stores/${s.store_id}/summary`] = SUMS[s.store_id]; });
    server(routes);
  }

  it("마지막으로 본 가게가 맨 앞 + 초록 주 버튼 + 칩, 예시 가게는 '(가상)', 요약 줄은 tone 색, unavailable 은 숫자 줄 없음", async () => {
    pickServer();
    setState({ stage: "pick", me: ME });
    render(<PickStore />);
    expect(document.activeElement.textContent).toBe("어느 가게를 볼까요?");
    await screen.findByText("포장 누락 3건 반복");
    const cards = [...document.querySelectorAll(".pick-card")];
    expect(cards.map((c) => c.querySelector(".pick-name").textContent)).toEqual(["바삭치킨 (가상)", "온기한식 (가상)", "우리분식"]);
    expect(within(cards[0]).getByText("마지막으로 본 가게")).toBeTruthy();
    expect(cards[0].querySelector(".pick-open").classList.contains("primary")).toBe(true);
    expect(cards[1].querySelector(".pick-open").classList.contains("primary")).toBe(false);
    expect(cards[1].querySelector(".pick-face").textContent).toBe("온");
    expect(within(cards[1]).getByText("한식음식점 · 장승배기역 4번 상권")).toBeTruthy();
    expect(within(cards[1]).getByText("리뷰 40 · 불만 12")).toBeTruthy();
    expect(within(cards[1]).getByText("포장 누락 3건 반복").classList.contains("tone-bad")).toBe(true);
    expect(within(cards[0]).getByText("오늘 할 일 끝").classList.contains("tone-good")).toBe(true);
    expect(cards[2].textContent).not.toMatch(/리뷰 \d|불만 \d/);
    expect(within(cards[2]).getByText("기록을 불러오지 못했어요").classList.contains("tone-muted")).toBe(true);
    // 카드마다 요약을 따로 부름 · 서버가 모르는 숫자는 없음
    expect(calls.filter((c) => /\/summary$/.test(c.path))).toHaveLength(3);
    expect(document.body.textContent).not.toMatch(/승인 대기|보고서/);
    // 왼쪽 사장님 칸
    const owner = document.querySelector(".pick-owner");
    expect(owner.textContent).toContain("김시험 사장님");
    expect(owner.textContent).toContain("가진 가게3곳");
    expect(within(owner).getByText("가게를 고르면 그 가게의 홈으로 갑니다. 상단 바에서 언제든 바꿀 수 있어요.")).toBeTruthy();
    // 마지막 칸 '+ 새 가게 등록'
    fireEvent.click(screen.getByRole("button", { name: /새 가게 등록/ }));
    expect(getState().stage).toBe("store-new");
    expect(getState().storeNew).toEqual({ mode: "add" });
  });

  it("불러오는 동안 숫자 자리만 잡는다", async () => {
    let release;
    const routes = { "/api/account/stores": { stores: [STORES[0]] } };
    server(routes);
    const pending = new Promise((r) => { release = r; });
    const base = globalThis.fetch;
    globalThis.fetch = vi.fn(async (path, opt) => { if (path.endsWith("/summary")) { await pending; } return base(path, opt); });
    setState({ stage: "pick", me: ME });
    render(<PickStore />);
    await waitFor(() => expect(document.querySelector(".pick-sum.loading")).toBeTruthy());
    release();
    await waitFor(() => expect(document.querySelector(".pick-sum.loading")).toBeNull());
  });

  it("가게가 0곳이면 '+ 새 가게 등록' 칸과 안내만", async () => {
    pickServer([]);
    setState({ stage: "pick", me: { ...ME, store_id: null, stores: [] } });
    render(<PickStore />);
    expect(await screen.findByText("아직 등록한 가게가 없어요")).toBeTruthy();
    expect(document.querySelectorAll(".pick-card")).toHaveLength(0);
    expect(screen.getByRole("button", { name: /새 가게 등록/ })).toBeTruthy();
  });
});

describe("A5 사장님 프로필", () => {
  function profileServer(extra = {}) {
    server({ "/api/account/stores": { stores: STORES }, "/api/auth/me": ME, ...extra });
    setState({ stage: "profile", me: ME, entered: "store_basak" });
    return render(<Profile />);
  }

  it("머리: 이름·아이디·가입일, 아이디는 읽기 전용, 이름 저장은 PATCH 로", async () => {
    profileServer({ "PATCH /api/account/profile": (b) => ({ ...ME, user: { ...ME.user, display_name: b.display_name } }) });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("김시험 사장님");
    expect(screen.getByText("아이디 owner_test · 2026-11-15 가입")).toBeTruthy();
    expect(document.querySelector('input[name="login_id"]').readOnly).toBe(true);
    const save = screen.getByRole("button", { name: "이름 저장" });
    expect(save.disabled).toBe(true);                        // 바꾼 것이 없으면 잠김
    fireEvent.change(document.querySelector('input[name="display_name"]'), { target: { value: "김새이름" } });
    fireEvent.click(save);
    expect(await screen.findByText("이름을 저장했어요.")).toBeTruthy();
    expect(sent("PATCH", "/api/account/profile")[0].body).toEqual({ display_name: "김새이름" });
    expect(getState().me.user.display_name).toBe("김새이름");
  });

  it("비밀번호 바꾸기: 틀리면(401 bad_password) 다시 로그인으로 가지 않고 그 자리에, 보낸 뒤 칸은 비움", async () => {
    profileServer({ "POST /api/account/password": [401, { error: { message: "지금 비밀번호가 맞지 않아요.", state: "bad_password" } }] });
    fireEvent.click(screen.getByRole("button", { name: "비밀번호 바꾸기" }));
    const box = (n) => document.querySelector(`#prof-pw input[name="${n}"]`);
    fireEvent.change(box("current_password"), { target: { value: "wrong-pw-1" } });
    fireEvent.change(box("new_password"), { target: { value: "new-test-pw-1" } });
    fireEvent.change(box("new_password_confirm"), { target: { value: "new-test-pw-1" } });
    fireEvent.submit(document.getElementById("prof-pw"));
    expect(await screen.findByText("지금 비밀번호가 맞지 않아요.")).toBeTruthy();
    expect(getState().stage).toBe("profile");
    expect(box("current_password").value).toBe("");
    expect(sent("POST", "/api/account/password")[0].body).toEqual({ current_password: "wrong-pw-1", new_password: "new-test-pw-1" });
  });

  it("내 가게: 예시 가게는 '예시 가게' 표시, 직접 등록한 가게만 [정보 고치기], 빼기는 확인 뒤 DELETE", async () => {
    profileServer({ "DELETE /api/account/stores/store_basak": { stores: [STORES[0], STORES[2]], store_id: "store_ongi" } });
    await screen.findByText("우리분식");
    expect(screen.getByRole("heading", { level: 2, name: "내 가게 (3곳)" })).toBeTruthy();
    const rows = [...document.querySelectorAll(".prof-store")];
    expect(within(rows[0]).getByText("예시 가게")).toBeTruthy();
    expect(within(rows[0]).queryByRole("button", { name: /정보 고치기/ })).toBeNull();
    expect(within(rows[0]).getByText("한식음식점 · 장승배기역 4번 · 메뉴 9개")).toBeTruthy();
    fireEvent.click(within(rows[2]).getByRole("button", { name: "우리분식 정보 고치기" }));
    expect(getState().stage).toBe("store-new");
    expect(getState().storeNew).toEqual({ mode: "edit", storeId: "st_mine" });
    act(() => setState({ stage: "profile" }));

    fireEvent.click(within(rows[1]).getByRole("button", { name: "바삭치킨 빼기" }));
    expect(within(rows[1]).getByText(/가게를 빼도 그 가게의 기록은 지워지지 않아요\./)).toBeTruthy();
    expect(sent("DELETE", "/api/account/stores/store_basak")).toHaveLength(0);   // 확인 전에는 보내지 않음
    fireEvent.click(within(rows[1]).getAllByRole("button", { name: "빼기" }).pop());
    await waitFor(() => expect(sent("DELETE", "/api/account/stores/store_basak")).toHaveLength(1));
    await waitFor(() => expect(document.querySelectorAll(".prof-store")).toHaveLength(2));
    // 들어가 있던 가게를 뺐으니 '가게로 돌아가기'는 가게 선택으로
    expect(getState().entered).toBeNull();
  });

  it("순서 바꾸기: [아래로] → PUT 순서", async () => {
    profileServer({ "PUT /api/account/stores/order": (b) => ({ stores: b.store_ids.map((id) => STORES.find((s) => s.store_id === id)) }) });
    await screen.findByText("우리분식");
    expect(screen.getByRole("button", { name: "온기한식 위로" }).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "온기한식 아래로" }));
    await waitFor(() => expect(sent("PUT", "/api/account/stores/order")).toHaveLength(1));
    expect(sent("PUT", "/api/account/stores/order")[0].body).toEqual({ store_ids: ["store_basak", "store_ongi", "st_mine"] });
    await waitFor(() => expect([...document.querySelectorAll(".prof-store b")].map((b) => b.textContent))
      .toEqual(["바삭치킨 (가상)", "온기한식 (가상)", "우리분식"]));
  });

  it("기록과 탈퇴: 확인 창에 '되돌릴 수 없어요'가 남고, 탈퇴는 비밀번호를 한 번 더, Esc 는 취소", async () => {
    profileServer();
    expect(screen.queryByText(/보관한 보고서/)).toBeNull();   // 서버에 보고서 저장 기능이 없어 만들지 않음
    const dlg = document.getElementById("acct-dialog");
    expect(dlg.hasAttribute("open")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "회원 탈퇴" }));
    expect(dlg.hasAttribute("open")).toBe(true);
    expect(within(dlg).getByText("회원 탈퇴할까요?")).toBeTruthy();
    expect(within(dlg).getByText("탈퇴하면 되돌릴 수 없어요.")).toBeTruthy();
    expect(within(dlg).getByLabelText("비밀번호 확인")).toBeTruthy();
    fireEvent.keyDown(dlg, { key: "Escape" });
    expect(dlg.hasAttribute("open")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "바삭치킨 기록 지우기" }));
    expect(within(dlg).getByText("지우면 되돌릴 수 없어요.")).toBeTruthy();
    fireEvent.click(within(dlg).getByRole("button", { name: "취소" }));
    expect(dlg.hasAttribute("open")).toBe(false);
    expect(calls.some((c) => c.path === "/api/auth/reset" || c.path === "/api/auth/withdraw")).toBe(false);
  });

  it("탈퇴하면 로그인 화면으로, 들어간 가게를 지우고 결과 띠", async () => {
    sessionStorage.setItem("ic26.entered", "store_basak");
    profileServer({ "POST /api/auth/withdraw": { ...GUEST, withdrawn: true } });
    fireEvent.click(screen.getByRole("button", { name: "회원 탈퇴" }));
    const dlg = document.getElementById("acct-dialog");
    fireEvent.change(within(dlg).getByLabelText("비밀번호 확인"), { target: { value: TEST_PW } });
    fireEvent.click(within(dlg).getByRole("button", { name: "탈퇴하기" }));
    await waitFor(() => expect(getState().stage).toBe("login"));
    expect(sent("POST", "/api/auth/withdraw")[0].body).toEqual({ password: TEST_PW });
    expect(sent("DELETE", "/api/assistant/conversation")).toHaveLength(1);
    expect(sessionStorage.getItem("ic26.entered")).toBeNull();
    expect(getState().me.authenticated).toBe(false);
    expect(getState().acctNotice).toBe("회원 탈퇴를 마쳤어요. 계정과 기록을 모두 지웠어요.");
  });
});
