// 종합 리포트 (11/20 주간·월간 저장 구조):
// - 'AI 문장 아님' 고지는 머리 한 곳(인쇄는 머리글)에만, 출처 링크·우리 가게 매출 아님·응대 점수 변동 근거는 남는다 (예전 시험 그대로)
// - 탭(주간·월간)은 해시가 아니라 화면 안 상태, 기간 이동은 서버가 준 이전·다음 값으로 (다음이 미래면 잠김)
// - 저장 안내 띠: 방금 만들어 저장 · 저장본 · 낡음(새 리뷰 수) · 게스트
// - [다시 만들기]는 지금 탭·지금 기간을 POST …/regenerate, 저장된 보고서 [열기]는 그 종류·기간을 연다
// - 리뷰 0건: 숫자 0 과 '아직 리뷰가 없어요', 자료 없는 칸은 '–'
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { resetStore, setState } from "../../state/store.js";
import { resetReportForTest } from "./state.js";
import { RP_NOTE } from "./format.js";
import Report from "./Report.jsx";
import SavedReportCounts from "./SavedReportCounts.jsx";

const daily = {
  date: "2026-11-20", until: "2026-11-20T15:00:00+09:00", summary: "", review_count: 2, complaint_count: 1,
  replied_on_time: 1, replied_late: 0, score_start: 100, score_end: 100, score_change: 0, changes: [], todo: { text: "밀린 응대 없음" },
  by_source: { paste: 2 }, pending_count: 0, overdue_count: 0,
};
const score = {
  score: 95, reasons: [{ delta: -5, message: "기한을 넘긴 답글 1건" }], policy: { sla_minutes: 30, peak_hours: ["11-14", "17-21"] },
  pending: [], peak_now: true, untimed_unanswered: 2, overdue_count: 0,
};
const report = (over = {}) => ({
  review_count: 14, complaint_count: 4, complaint_rate: 29, score_start: 100, score_end: 91, score_change: -9, late_count: 1,
  until: "2026-11-16T23:59:59+09:00", score_trend: [{ date: "2026-11-10", score: 100 }, { date: "2026-11-16", score: 91 }], changes: [],
  previous: { review_count: 11, complaint_count: 4, complaint_rate: 33 },
  topics: [
    { topic: "missing_item", topic_name: "포장 누락", polarity: "negative", count: 2, previous: 1 },
    { topic: "taste", topic_name: "맛", polarity: "positive", count: 6, previous: 4 },
  ],
  repeated_issues: [{ issue_id: "iss_missing_item", topic_name: "포장 누락", review_count: 3, count_this_week: 2, count_this_month: 2, is_repeated: true,
    replied_count: 0, recurred_after_reply: 0, state: "no_reply", main_time_band: "17~21시" }],
  suggestions: [{ kind: "no_reply", title: "'포장 누락' 불만 3건에 아직 답글이 없어요", evidence: "이번 주 2건 · 전체 3건 · 17~21시에 많음",
    text: "답글로 조치를 알리고, 매장에서 확인해 보세요" }],
  praise: { high_rating_count: 8, positive_count: 9, top_topics: [], top_menus: [{ menu: "제육볶음 정식", count: 3 }], quote: null, review_count: 14, praise_count: 9 },
  ...over,
});
const weekView = (key, over = {}) => ({
  kind: "weekly",
  period: { key, start: key, end: key === "2026-11-16" ? "2026-11-22" : "2026-11-15", label: key === "2026-11-16" ? "11월 3주" : "11월 2주",
    range: key === "2026-11-16" ? "11/16 ~ 11/22" : "11/9 ~ 11/15", in_progress: key === "2026-11-16" },
  nav: key === "2026-11-16" ? { prev: "2026-11-09", next: null } : { prev: "2026-11-02", next: "2026-11-16" },
  storage: "saved", saved: true, created_at: "2026-11-17T09:00:00+09:00", made_now: false,
  stale: { checked: true, is_stale: true, new_reviews: 3, reviews_now: 17, responses_changed: false, approvals_changed: false, period_closed: false },
  report: report(), approvals: { total: 7, reply: 5, notice: 0, promo: 2, other: 0 },
  marketing: { promo_approved: 2, coupon_usage_rate: null, ad_cost_per_order: null, notice_recurrence: null },
  ...over,
});
const monthView = {
  ...weekView("2026-11"), kind: "monthly",
  period: { key: "2026-11", start: "2026-11-01", end: "2026-11-30", label: "2026년 11월", range: "11/1 ~ 11/30", in_progress: true },
  nav: { prev: "2026-10", next: null }, made_now: true, stale: null, created_at: "2026-11-20T15:00:00+09:00",
  report: report({ suggestions: [{ text: "'포장 누락' 불만 3건에 아직 답글이 없어요. 답글로 조치를 알리고, 매장에서 확인해 보세요" }] }),
};
const saved = { storage: "saved", items: [
  { kind: "weekly", key: "2026-11-16", label: "11월 3주", range: "11/16 ~ 11/22", start: "2026-11-16", end: "2026-11-22", created_at: "2026-11-17T09:00:00+09:00" },
  { kind: "weekly", key: "2026-11-09", label: "11월 2주", range: "11/9 ~ 11/15", start: "2026-11-09", end: "2026-11-15", created_at: "2026-11-16T10:00:00+09:00" },
  { kind: "monthly", key: "2026-10", label: "2026년 10월", range: "10/1 ~ 10/31", start: "2026-10-01", end: "2026-10-31", created_at: "2026-11-01T00:10:00+09:00" },
] };
const json = (body, status = 200) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body), headers: { get: () => "application/json" } });

let calls;
let routes;
function route(path, opts = {}) {
  calls.push({ path, method: opts.method || "GET" });
  for (const [test, body] of routes) if (test(path, opts)) return json(typeof body === "function" ? body(path, opts) : body);
  return json({});
}

beforeEach(() => {
  resetStore();
  resetReportForTest();
  calls = [];
  routes = [
    [(p) => p.startsWith("/api/care/report/daily"), daily],
    [(p) => p.startsWith("/api/care/response"), score],
    [(p, o) => p.startsWith("/api/reports/weekly/regenerate") && o.method === "POST",
      (p) => weekView(new URL(p, "http://x").searchParams.get("period"), { made_now: true, stale: null, created_at: "2026-11-20T15:30:00+09:00", report: report({ review_count: 17 }) })],
    [(p) => p.startsWith("/api/reports/weekly"), (p) => weekView(new URL(p, "http://x").searchParams.get("period") || "2026-11-16")],
    [(p) => p.startsWith("/api/reports/monthly"), monthView],
    [(p) => p === "/api/reports/saved", saved],
    [(p) => p === "/api/reports/counts", { storage: "saved", weekly: 4, monthly: 1 }],
    [(p) => p === "/api/approvals", { items: [] }],
  ];
  setState({
    booted: true,
    briefing: { store: { name: "온기한식", business_type_name: "한식음식점", area_name: "장승배기역 4번" }, snapshots: [{
      snapshot_id: "s1", value: -19.31, unit: "%", area_name: "장승배기역 4번", compared_with_quarter: true,
      metric_name: "저녁 시간대(17~24시) 추정매출 전년 동기 대비 변화율 · 두 분기 공통 업종",
      basis_label: "서울시 상권분석서비스 2026년 2분기", source: "서울 열린데이터광장 https://data.seoul.go.kr/x",
    }] },
  });
  vi.spyOn(globalThis, "fetch").mockImplementation(route);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const tiles = (c) => [...c.querySelectorAll("#rp-tiles .tile")].map((t) => t.textContent);

describe("종합 리포트", () => {
  it("AI 문장 아님 고지는 머리 한 곳(+인쇄 머리글), 근거·출처·우리 가게 매출 아님은 남김", async () => {
    const { container } = render(<Report />);
    await waitFor(() => expect(container.querySelector("#rp-tiles")).toBeTruthy());
    await waitFor(() => expect(container.querySelector("#rp-score")).toBeTruthy());

    expect(container.querySelector(".page-head .ph-sub").textContent).toBe(RP_NOTE);
    expect(container.querySelector("#rp-print-head").textContent).toContain(RP_NOTE);   // 인쇄에서는 머리가 빠지므로
    const screenText = [...container.querySelectorAll(".rp-sec, .rp-today, #rp-saved")].map((el) => el.textContent).join("\n");
    expect(screenText).not.toMatch(/AI 문장 아님|코드로 셌어요|코드가 계산|모델 호출 없음|서버 문장 그대로|정해 둔 틀에|AI가 써요/);

    // 응대 점수 변동 근거 · 기한 규칙(피크 시간은 한 곳)
    expect(screen.getByText("기한을 넘긴 답글 1건")).toBeTruthy();
    expect(screen.getByText("지금은 피크 시간이라 답글 기한이 멈춰 있어요.")).toBeTruthy();
    expect(screen.getByText("답글 기한은 불만 리뷰를 받은 뒤 30분이에요 (피크 11~14시, 17~21시에는 멈춤). 답글을 승인하면 기록돼요.")).toBeTruthy();
    // 고칠 것 바로 아래 한 줄
    expect(screen.getByText("원인을 단정하지 않은 제안이에요. 매장에서 확인해 주세요.")).toBeTruthy();
    // 상권: 서울시 출처·기준 분기 + 원본 링크 + 우리 가게 매출 아님 (한 번만)
    expect(container.querySelector("#rp-market").textContent).toContain("서울시 상권분석서비스 2026년 2분기");
    expect(container.querySelector("#rp-market a[href='https://data.seoul.go.kr/x']").textContent).toBe("원본");
    expect(screen.getAllByText(/우리 가게 매출 아님/)).toHaveLength(1);
    expect(screen.getByText(/'AI에게 묻기'는 업종 하나의 하루 전체로 답해서 숫자가 다를 수 있어요/)).toBeTruthy();
    // 마케팅 요약 칸은 목차 같은 부제 없이
    expect(container.querySelector("#rp-mkt-sec .panel-head .sub")).toBeNull();
    await waitFor(() => expect(screen.getByText("서버에 남은 승인 기록 0건 (맞춤 마케팅 포함 · 이 계정 기준)")).toBeTruthy());
  });

  it("그림의 차례: 머리 → 오늘·점수 줄 → 탭·기간 → 저장 띠 → 타일 → 고칠 것·주제 → 마케팅 숫자 → … → 저장된 보고서", async () => {
    const { container } = render(<Report />);
    await waitFor(() => expect(container.querySelector("#rp-tiles")).toBeTruthy());
    await waitFor(() => expect(container.querySelector("#rp-saved-list")).toBeTruthy());
    const order = ["header.page-head", "#rp-today", ".rp-bar", "#rp-saved", "#rp-tiles", "#rp-fix-sec", "#rp-topics-sec", "#rp-mn-sec",
      "#rp-praise-sec", "#rp-record-sec", "#rp-score-sec", "#rp-market-sec", "#rp-mkt-sec", "#rp-list-sec"].map((s) => container.querySelector(s));
    order.forEach((el, i) => expect(el, `차례 ${i}`).toBeTruthy());
    for (let i = 1; i < order.length; i += 1) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    expect([...container.querySelectorAll(".page-head .btn")].map((b) => b.textContent)).toEqual(["다시 만들기", "PDF 저장"]);
    // 타일 4개 (그림: 리뷰 14건 지난주보다 +3 · 불만 비율 29% 지난주 33% · 응대 점수 91점 · 승인한 글 7개 답글 5 · 홍보 2)
    expect(tiles(container)).toEqual(["리뷰14건지난주보다 +3", "불만 비율29%지난주 33%", "응대 점수91점시작 100점 · -9", "승인한 글7개답글 5 · 홍보 2"]);
    expect(container.querySelector("#rp-fix-title").textContent).toBe("이번 주에 고칠 것");
    expect(container.querySelector("#rp-fixes").textContent).toContain("근거: 이번 주 2건 · 전체 3건 · 17~21시에 많음");
    expect(container.querySelector("#rp-topics").textContent).toContain("포장 누락2건 · 지난주 1건");
    expect([...container.querySelectorAll("#rp-mn dd")].map((d) => d.textContent)).toEqual(["2개", "–", "–", "–"]);
    // 낡은 저장본 안내 (그림의 문장)
    expect(container.querySelector("#rp-saved").textContent)
      .toBe("11-17 09:00에 만들어 저장한 보고서예요. 그 뒤 새 리뷰 3건이 들어왔어요 → 다시 만들면 반영돼요.");
    expect(container.querySelector("#rp-period-label").textContent).toBe("11월 3주 (11/16 ~ 11/22)");
    // 오늘 요약·응대 점수 한 줄
    expect(container.querySelector("#rp-daily").textContent).toContain("리뷰 2건 · 불만 1건 · 기한 안 답글 1건 · 늦은 답글 0건");
    expect(container.querySelector("#rp-score-line").textContent).toContain("95");
  });

  it("탭은 화면 안 상태(해시 그대로), 기간 이동은 서버 값으로, 다음이 미래면 잠김", async () => {
    window.location.hash = "#/report";
    const { container } = render(<Report />);
    await waitFor(() => expect(container.querySelector("#rp-period-label").textContent).toBe("11월 3주 (11/16 ~ 11/22)"));
    expect(container.querySelector("#rp-next").disabled).toBe(true);
    expect(container.querySelector("#rp-prev").textContent).toContain("지난주");
    fireEvent.click(container.querySelector("#rp-prev"));
    await waitFor(() => expect(container.querySelector("#rp-period-label").textContent).toBe("11월 2주 (11/9 ~ 11/15)"));
    expect(calls.some((c) => c.path === "/api/reports/weekly?period=2026-11-09")).toBe(true);
    expect(container.querySelector("#rp-next").disabled).toBe(false);

    fireEvent.click(screen.getByRole("tab", { name: "월간" }));
    await waitFor(() => expect(container.querySelector("#rp-period-label").textContent).toBe("2026년 11월 (11/1 ~ 11/30)"));
    expect(window.location.hash).toBe("#/report");
    expect(screen.getByRole("tab", { name: "월간" }).getAttribute("aria-selected")).toBe("true");
    expect(container.querySelector("#rp-panel-weekly").hidden).toBe(true);
    expect(container.querySelector("#rp-fix-title").textContent).toBe("다음 달에 고칠 것");
    expect(container.querySelector("#rp-prev").textContent).toContain("지난달");
    expect(container.querySelector("#rp-print").getAttribute("href")).toBe("/api/care/report/monthly/print?month=2026-11");
    expect(container.querySelector("#rp-saved").textContent).toBe("11-20 15:00에 만들어 저장했어요. 이번 달은 아직 진행 중이라, 새 리뷰가 들어오면 다시 만들어 주세요.");
    // 주간으로 돌아오면 보던 기간 그대로
    fireEvent.click(screen.getByRole("tab", { name: "주간" }));
    expect(container.querySelector("#rp-period-label").textContent).toBe("11월 2주 (11/9 ~ 11/15)");
    expect(container.querySelector("#rp-print")).toBeNull();
  });

  it("[다시 만들기]는 지금 탭·기간을 새로 계산해 저장본을 바꾸고, 목록 [열기]는 그 보고서를 연다", async () => {
    const { container } = render(<Report />);
    await waitFor(() => expect(container.querySelector("#rp-saved-list")).toBeTruthy());
    fireEvent.click(container.querySelector("#rp-remake"));
    await waitFor(() => expect(container.querySelector("#rp-saved").textContent).toBe("11-20 15:30에 만들어 저장했어요. 이번 주는 아직 진행 중이라, 새 리뷰가 들어오면 다시 만들어 주세요."));
    expect(calls.some((c) => c.path === "/api/reports/weekly/regenerate?period=2026-11-16" && c.method === "POST")).toBe(true);
    expect(tiles(container)[0]).toBe("리뷰17건지난주보다 +6");

    const items = [...container.querySelectorAll("#rp-saved-list li")];
    expect(items.map((li) => li.textContent)).toEqual([
      "주간11월 3주 11/16 ~ 11/22만든 시각 11-17 09:00열기", "주간11월 2주 11/9 ~ 11/15만든 시각 11-16 10:00열기", "월간2026년 10월 10/1 ~ 10/31만든 시각 11-01 00:10열기"]);
    expect(items[0].getAttribute("aria-current")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "월간 2026년 10월 보고서 열기" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/reports/monthly?period=2026-10")).toBe(true));
    await waitFor(() => expect(screen.getByRole("tab", { name: "월간" }).getAttribute("aria-selected")).toBe("true"));
  });

  it("리뷰 0건: 숫자 0 과 '아직 리뷰가 없어요', 비율은 '–', 깨지지 않음", async () => {
    routes.unshift([(p) => p.startsWith("/api/reports/weekly"), weekView("2026-11-16", {
      made_now: true, stale: null, approvals: { total: 0, reply: 0, notice: 0, promo: 0, other: 0 },
      marketing: { promo_approved: 0, coupon_usage_rate: null, ad_cost_per_order: null, notice_recurrence: null },
      report: report({ review_count: 0, complaint_count: 0, complaint_rate: null, previous: { review_count: 0, complaint_count: 0, complaint_rate: null },
        topics: [], repeated_issues: [], praise: { high_rating_count: 0, positive_count: 0, top_topics: [], top_menus: [], quote: null, review_count: 0, praise_count: 0 },
        suggestions: [{ kind: "empty", title: "이번 주에 들어온 리뷰가 아직 없어요", evidence: "리뷰 0건", text: "리뷰가 들어오면 보고서를 다시 만들어 보세요" }] }),
    })]);
    const { container } = render(<Report />);
    await waitFor(() => expect(container.querySelector("#rp-tiles")).toBeTruthy());
    expect(tiles(container)).toEqual(["리뷰0건아직 리뷰가 없어요", "불만 비율–지난주 –", "응대 점수91점시작 100점 · -9", "승인한 글0개답글 0 · 홍보 0"]);
    expect(container.querySelector("#rp-topics").textContent).toBe("아직 리뷰가 없어요.");
    expect(container.querySelector("#rp-fixes").textContent).toContain("이번 주에 들어온 리뷰가 아직 없어요");
    expect(container.querySelector("#rp-praise").textContent).toContain("아직 칭찬 리뷰가 없어요.");
    expect(container.querySelector("#rp-record").textContent).toContain("이 기간에 묶인 불만이 없어요.");
  });

  it("게스트는 저장되지 않는다는 안내와 빈 목록", async () => {
    routes.unshift([(p) => p.startsWith("/api/reports/weekly"), weekView("2026-11-16", { storage: "guest", saved: false, made_now: true, stale: null })]);
    routes.unshift([(p) => p === "/api/reports/saved", { storage: "guest", items: [] }]);
    const { container } = render(<Report />);
    await waitFor(() => expect(container.querySelector("#rp-saved").textContent).toBe("로그인하면 만든 보고서가 이 계정에 저장돼요."));
    await waitFor(() => expect(container.querySelector("#rp-list-sec").textContent).toContain("로그인하면 만든 보고서가 여기에 쌓여요."));
  });

  it("보고서를 못 불러오면 그 자리에만 오류, 다른 칸은 그대로", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((path, opts) => (path.startsWith("/api/reports/weekly")
      ? json({ error: { message: "리뷰 분석 서비스에 연결하지 못했어요. 잠시 뒤 다시 확인해 주세요.", state: "down" } }, 503) : route(path, opts)));
    const { container } = render(<Report />);
    await waitFor(() => expect(container.querySelector("#rp-report-state").textContent).toBe("리뷰 분석 서비스에 연결하지 못했어요. 잠시 뒤 다시 확인해 주세요."));
    expect(container.querySelector("#rp-report-state").classList.contains("bad")).toBe(true);
    expect(container.querySelector("#rp-tiles")).toBeNull();
    await waitFor(() => expect(container.querySelector("#rp-score")).toBeTruthy());
  });
});

describe("프로필의 보관한 보고서 수", () => {
  it("주간 n개 · 월간 n개 타일, 게스트는 안내 한 줄", async () => {
    const { container, unmount } = render(<SavedReportCounts />);
    await waitFor(() => expect(container.querySelector("#saved-weekly")).toBeTruthy());
    expect(container.querySelector("#saved-weekly").textContent).toBe("주간4개");
    expect(container.querySelector("#saved-monthly").textContent).toBe("월간1개");
    expect(calls.map((c) => c.path)).toEqual(["/api/reports/counts"]);
    unmount();
    const guest = render(<SavedReportCounts counts={{ storage: "guest", weekly: 0, monthly: 0 }} />);
    expect(guest.container.textContent).toBe("로그인하면 주간·월간 보고서가 이 계정에 저장돼요.");
    expect(guest.container.querySelector(".tile")).toBeNull();
  });
});
