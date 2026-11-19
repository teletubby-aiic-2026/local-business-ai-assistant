// 종합 리포트: 'AI 문장 아님' 고지는 머리 한 곳(인쇄는 머리글)에만, 칸마다 되풀이하던 내부 사정 문장은 없고
// 출처 링크·우리 가게 매출 아님·응대 점수 변동 근거는 남는지
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { resetStore, setState } from "../../state/store.js";
import { resetReportForTest } from "./state.js";
import { RP_NOTE } from "./format.js";
import Report from "./Report.jsx";

const daily = {
  date: "2026-11-19", until: "2026-11-19T21:00:00+09:00", summary: "오늘 불만 1건에 답글을 달았어요.", review_count: 2, complaint_count: 1,
  replied_on_time: 1, replied_late: 0, score_start: 100, score_end: 100, score_change: 0, changes: [], todo: { text: "밀린 응대 없음" },
  by_source: { paste: 2 }, pending_count: 0, overdue_count: 0,
};
const score = {
  score: 95, reasons: [{ delta: -5, message: "기한을 넘긴 답글 1건" }], policy: { sla_minutes: 30, peak_hours: ["11-14", "17-21"] },
  pending: [], peak_now: true, untimed_unanswered: 2, overdue_count: 0,
};
const monthly = {
  month: "2026-11", until: "2026-11-19", review_count: 40, complaint_count: 12, score_start: 100, score_end: 95, score_change: -5, late_count: 1,
  score_trend: [{ date: "2026-11-01", score: 100 }, { date: "2026-11-19", score: 95 }], repeated_issues: [], suggestions: [{ text: "포장 마감 전에 주문서를 대조해요." }],
  changes: [], praise: { high_rating_count: 20, positive_count: 22, top_topics: [], top_menus: [], quote: null, review_count: 40, praise_count: 22 },
};
const json = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body), headers: { get: () => "application/json" } });

beforeEach(() => {
  resetStore();
  resetReportForTest();
  setState({
    booted: true,
    briefing: { store: { name: "온기한식", business_type_name: "한식음식점", area_name: "장승배기역 4번" }, snapshots: [{
      snapshot_id: "s1", value: -19.31, unit: "%", area_name: "장승배기역 4번", compared_with_quarter: true,
      metric_name: "저녁 시간대(17~24시) 추정매출 전년 동기 대비 변화율 · 두 분기 공통 업종",
      basis_label: "서울시 상권분석서비스 2026년 2분기", source: "서울 열린데이터광장 https://data.seoul.go.kr/x",
    }] },
  });
  vi.spyOn(globalThis, "fetch").mockImplementation((path) => json(
    path.startsWith("/api/care/report/daily") ? daily : path.startsWith("/api/care/response") ? score
      : path.startsWith("/api/care/report/monthly") ? monthly : path === "/api/approvals" ? { items: [] } : {},
  ));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("종합 리포트", () => {
  it("AI 문장 아님 고지는 머리 한 곳(+인쇄 머리글), 근거·출처·우리 가게 매출 아님은 남김", async () => {
    const { container } = render(<Report />);
    await waitFor(() => expect(container.querySelector("#rp-month")).toBeTruthy());
    await waitFor(() => expect(container.querySelector("#rp-score")).toBeTruthy());

    expect(container.querySelector(".page-head .ph-sub").textContent).toBe(RP_NOTE);
    expect(container.querySelector("#rp-print-head").textContent).toContain(RP_NOTE);   // 인쇄에서는 머리가 빠지므로
    const screenText = [...container.querySelectorAll(".rp-sec")].map((el) => el.textContent).join("\n");
    expect(screenText).not.toMatch(/AI 문장 아님|코드로 셌어요|모델 호출 없음|서버 문장 그대로|정해 둔 틀에/);

    // 응대 점수 변동 근거 · 기한 규칙(피크 시간은 한 곳)
    expect(screen.getByText("기한을 넘긴 답글 1건")).toBeTruthy();
    expect(screen.getByText("지금은 피크 시간이라 답글 기한이 멈춰 있어요.")).toBeTruthy();
    expect(screen.getByText("답글 기한은 불만 리뷰를 받은 뒤 30분이에요 (피크 11~14시, 17~21시에는 멈춤). 답글을 승인하면 기록돼요.")).toBeTruthy();
    // 개선 제안 바로 아래 한 줄
    expect(screen.getByText("원인을 단정하지 않은 제안이에요. 매장에서 확인해 주세요.")).toBeTruthy();
    // 상권: 서울시 출처·기준 분기 + 원본 링크 + 우리 가게 매출 아님 (한 번만)
    expect(container.querySelector("#rp-market").textContent).toContain("서울시 상권분석서비스 2026년 2분기");
    expect(container.querySelector("#rp-market a[href='https://data.seoul.go.kr/x']").textContent).toBe("원본");
    expect(screen.getAllByText(/우리 가게 매출 아님/)).toHaveLength(1);
    expect(screen.getByText(/'AI에게 묻기'는 업종 하나의 하루 전체로 답해서 숫자가 다를 수 있어요/)).toBeTruthy();
    // 마케팅 요약 칸은 목차 같은 부제 없이
    expect(container.querySelector("#rp-mkt-sec .panel-head .sub")).toBeNull();
    await waitFor(() => expect(screen.getByText("서버에 남은 승인 기록 0건 (맞춤 마케팅 포함 · 이 방문자 기준)")).toBeTruthy());
  });
});
