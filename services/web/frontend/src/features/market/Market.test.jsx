import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { resetStore, setState, getState } from "../../state/store.js";
import { resetMarketForTest, getMarket } from "./state.js";
import Market from "./Market.jsx";

const COND = { area_code: "A1", area_name: "상도역", industry_code: "I1", industry_name: "한식음식점", period: "20262", period_label: "2026년 2분기", revision: 3, home: true };
const RESP = {
  status: { state: "ready", data: { message: "준비됨" }, store: { name: "상도 국밥", station_name: "상도역", business_type_name: "한식" } },
  setup: { conditions: COND },
  "analysis-options": { candidates: [{ area_code: "A1", name: "상도역", district_code: "D1", available_periods: ["20261", "20262"] }] },
  options: { industries: [{ code: "I1", name: "한식음식점" }] },
  sales: { total: { value: 1200000000 }, distributions: { time: { label: "시간대", items: [{ label: "점심", share_percent: 60 }] } } },
  stores: { counts: { total: { label: "전체", value: 12, unit: "개" }, opened: { label: "개업", value: 1 }, closed: { label: "폐업", value: 2 } } },
  population: { total: { value: 5000 } },
  "area-context": { status: "not_collected" },
  changes: { previous_period: "20252", current_period: "20262", metrics: [{ key: "sales", label: "추정매출", unit: "원", percent: -2.5, previous: { value: 1 }, current: { value: 2 } }] },
  "comparison-options": { districts: [{ code: "D1", name: "동작구" }], areas: [{ area_code: "A2", name: "노량진", district_code: "D1" }] },
  comparison: { base_area: { name: "상도역" }, comparison_area: { name: "노량진" }, metrics: [{ key: "sales", label: "추정매출", unit: "원", percent: 10, base: { value: 100000000 }, comparison: { value: 110000000 } }] },
  "cultural-events": { district: "동작구", events: [{ title: "음악회", link: "javascript:x", category: "공연" }] },
};

let calls;
beforeEach(() => {
  resetStore(); resetMarketForTest(); calls = [];
  global.fetch = vi.fn(async (url) => {
    const path = String(url).replace("/api/market/", "").split("?")[0];
    calls.push(String(url));
    return { ok: true, status: 200, json: async () => RESP[path] || {} };
  });
});
afterEach(() => { cleanup(); });

describe("상권 분석 화면", () => {
  it("처음 열면 상태 → 기본 조건 → 자료를 읽어 지표를 그린다", async () => {
    render(<Market />);
    await screen.findAllByText("12억 원");
    expect(screen.getAllByText("-2.50%").every((e) => e.className === "mk-neg")).toBe(true);
    expect(screen.getAllByText("12개").length).toBe(2);
    expect(screen.getByText(/상권 분석 비서 · 상도 국밥 · 상도역 · 한식/)).toBeTruthy();
    expect(screen.getByText("상도역 · 한식음식점 · 2026년 2분기 · 우리 가게 기준")).toBeTruthy();
    expect(calls.some((u) => u.includes("sales?expected_revision=3"))).toBe(true);
    expect(getState().staffMarket.state).toBe("ready");
    expect(screen.getByText("음악회").tagName).toBe("B");   // http(s) 아닌 링크는 열지 않음
  });

  it("머리 고지는 한 줄 (출처·추정치·우리 가게 매출 아님), 옆 칸 제목은 '서울시 자료 최신화'", async () => {
    render(<Market />);
    await screen.findAllByText("12억 원");
    const sub = document.querySelector(".page-head .ph-sub");
    expect(sub.textContent).toBe("서울시 상권분석서비스 추정치 기준 · 우리 가게 실제 매출이 아니에요");
    expect(screen.getAllByText(/우리 가게 (실제 )?매출이 아니에요/).length).toBe(1);
    expect(screen.getByRole("heading", { name: "서울시 자료 최신화" })).toBeTruthy();
    expect(screen.queryByText(/열린데이터광장/)).toBeNull();
    expect(screen.getByText("준비됨 · 서울시 확인 기록 없음")).toBeTruthy();
    expect(screen.getByText("2026년 2분기 · 한식음식점")).toBeTruthy();   // 기준 분기·업종은 지표에 그대로
  });

  it("비교 탭을 열면 목록을 받고 비교한다, 화면을 다시 열어도 남는다", async () => {
    const { unmount } = render(<Market />);
    await screen.findAllByText("12억 원");
    fireEvent.click(screen.getByRole("tab", { name: "타 상권 1:1 비교" }));
    await screen.findByText("우리 가게 상권과 비교할 상권을 골라 주세요.");
    fireEvent.click(screen.getByRole("button", { name: "비교하기" }));
    await screen.findByText("1억 1,000만 원");
    expect(calls.some((u) => u.includes("comparison?comparison_area_code=A2&expected_revision=3"))).toBe(true);
    unmount();
    const n = calls.length;
    render(<Market />);
    expect(screen.getByText("1억 1,000만 원")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "타 상권 1:1 비교" }).getAttribute("aria-selected")).toBe("true");
    expect(calls.length).toBe(n);   // 다시 부르지 않음
  });

  it("가게가 바뀌면(epoch) 처음부터, ready 가 아니면 안내와 잠긴 조건", async () => {
    render(<Market />);
    await screen.findAllByText("12억 원");
    cleanup();
    RESP.status = { state: "off", message: "상권 서비스가 꺼져 있어요." };
    act(() => setState({ epoch: getState().epoch + 1 }));
    render(<Market />);
    await screen.findByText("상권 서비스가 꺼져 있어요.");
    expect(getMarket().cond).toBeNull();
    expect(screen.getByRole("button", { name: "이 조건으로 보기" }).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "AI에게 묻기" }).disabled).toBe(false);
  });

  it("navTo 로 탭을 연다", async () => {
    setState({ nav: { name: "market", sub: "stores", seq: 1 } });
    render(<Market />);
    await waitFor(() => expect(screen.getByRole("tab", { name: "점포·개폐업" }).getAttribute("aria-selected")).toBe("true"));
    expect(document.activeElement.id).toBe("mk-tab-stores");
  });
});
