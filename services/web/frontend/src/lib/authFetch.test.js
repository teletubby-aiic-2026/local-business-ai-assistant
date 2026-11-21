// 공통 api() 없이 따로 fetch 하는 곳도 같은 로그인 규칙 (11/20 통합 뒤 정리, docs/api/contract.md 2.2 (6)):
// 로그인한 동안 X-IC26-Signed-In: 1 을 붙이고, 401 login_needed → 다시 로그인 · 409 no_store → 가게 선택 · 403 not_your_store → 권한 없음.
// 대상: 맞춤 마케팅(mktApi) · 리뷰 분석 캡처(careApi) · 상권 분석(market/state.js) · AI에게 묻기 서랍(assistant/state.js 의 call) · 지도 설정(NaverMap)
import { describe, it, expect, beforeEach, vi } from "vitest";
import { waitFor } from "@testing-library/react";
import { resetStore, setState, getState } from "../state/store.js";
import { mktApi } from "../features/marketing/api.js";
import { careApi } from "../features/analysis/careApi.js";
import { marketOpen, resetMarketForTest } from "../features/market/state.js";
import { chatStart } from "../features/assistant/state.js";
import { loadNaverMaps, resetNaverMapsForTest } from "../components/NaverMap.jsx";

const ME = { authenticated: true, store_id: "store_ongi", stores: [{ store_id: "store_ongi", name: "온기한식" }], user: { user_id: "u1", display_name: "김시험" } };
const FAIL = {
  expired: [401, { error: { message: "로그인이 끝났어요. 다시 로그인해 주세요.", state: "login_needed" } }],
  pick: [409, { error: { message: "먼저 가게를 등록하거나 골라 주세요.", state: "no_store" } }],
  forbidden: [403, { error: { message: "가지고 계신 가게만 볼 수 있어요.", state: "not_your_store" } }],
};
let calls;
function answer(status, body) {
  calls = [];
  globalThis.fetch = vi.fn(async (path, opt = {}) => {
    calls.push({ path, headers: opt.headers || {} });
    return { ok: status < 400, status, json: async () => body, headers: { get: () => "application/json" } };
  });
}

beforeEach(() => {
  resetStore();
  resetMarketForTest();
  resetNaverMapsForTest();
  window.scrollTo = () => {};
  setState({ stage: "app", me: ME, entered: "store_ongi", epoch: 1 });
});

describe("따로 fetch 하는 곳의 로그인 표시와 단계 전환", () => {
  it("맞춤 마케팅: 헤더를 붙이고 401 login_needed 면 다시 로그인 단계로 (오류는 그대로 던짐)", async () => {
    answer(...FAIL.expired);
    await expect(mktApi("health")).rejects.toMatchObject({ status: 401, state: "login_needed", authHandled: true });
    expect(calls[0].headers["X-IC26-Signed-In"]).toBe("1");
    expect(getState().stage).toBe("expired");
  });

  it("리뷰 분석 캡처(careApi): 헤더를 붙이고 403 not_your_store 면 권한 없음", async () => {
    answer(...FAIL.forbidden);
    await expect(careApi("/api/care/response")).rejects.toMatchObject({ status: 403, authHandled: true });
    expect(calls[0].headers["X-IC26-Signed-In"]).toBe("1");
    expect(getState().stage).toBe("forbidden");
  });

  it("상권 분석: 헤더를 붙이고 409 no_store 면 가게 선택", async () => {
    answer(...FAIL.pick);
    marketOpen();
    await waitFor(() => expect(getState().stage).toBe("pick"));
    expect(calls.find((c) => c.path === "/api/market/status").headers["X-IC26-Signed-In"]).toBe("1");
  });

  it("AI에게 묻기 서랍: 헤더를 붙이고 401 login_needed 면 다시 로그인", async () => {
    answer(...FAIL.expired);
    await chatStart();
    expect(calls[0].path).toBe("/api/assistant/status");
    expect(calls[0].headers["X-IC26-Signed-In"]).toBe("1");
    expect(calls[0].headers["Content-Type"]).toBe("application/json");
    expect(getState().stage).toBe("expired");
  });

  it("지도 설정(map-config): 헤더를 붙이고 401 login_needed 면 다시 로그인 (지도는 못 띄움)", async () => {
    answer(...FAIL.expired);
    await expect(loadNaverMaps()).rejects.toMatchObject({ kind: "error" });
    expect(calls[0].headers["X-IC26-Signed-In"]).toBe("1");
    expect(getState().stage).toBe("expired");
  });

  it("로그인 전(게스트)에는 헤더를 붙이지 않는다", async () => {
    setState({ stage: "login", me: { authenticated: false, user: null, stores: [] } });
    answer(200, { ok: true });
    await mktApi("health");
    await careApi("/api/care/response");
    expect(calls.map((c) => c.headers["X-IC26-Signed-In"])).toEqual([undefined, undefined]);
  });
});
