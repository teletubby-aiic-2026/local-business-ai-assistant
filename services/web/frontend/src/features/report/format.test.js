import { describe, expect, it } from "vitest";
import {
  approvalLine, clockView, clocksOf, dateKo, marketingNumbers, peakText, periodText, printMeta, rpClock, savedNote, signed, stamp, tilesOf, topicRows,
  trendGeometry,
} from "./format.js";

const view = (over = {}) => ({
  kind: "weekly", storage: "saved", created_at: "2026-11-17T09:00:00+09:00", made_now: false, stale: null,
  period: { key: "2026-11-09", label: "11월 2주", range: "11/9 ~ 11/15", in_progress: false },
  report: { review_count: 14, complaint_rate: 29, score_start: 100, score_end: 91, score_change: -9, previous: { review_count: 11, complaint_rate: 33 } },
  approvals: { total: 7, reply: 5, notice: 0, promo: 2, other: 0 },
  marketing: { promo_approved: 2, coupon_usage_rate: null, ad_cost_per_order: null, notice_recurrence: null },
  ...over,
});

describe("종합 리포트 글자", () => {
  it("날짜·부호·피크·만든 시각·기간 이름", () => {
    expect(dateKo("2026-11-05T23:59:00+09:00")).toBe("11/5");
    expect(signed(3)).toBe("+3");
    expect(signed(-2)).toBe("-2");
    expect(signed(undefined)).toBe("0");
    expect(peakText({ peak_hours: ["11-14", "17-21"] })).toBe("11~14시, 17~21시");
    expect(stamp("2026-11-17T09:00:00+09:00")).toBe("11-17 09:00");
    expect(stamp(null)).toBe("");
    expect(periodText({ label: "11월 3주", range: "11/16 ~ 11/22" })).toBe("11월 3주 (11/16 ~ 11/22)");
    expect(periodText(null)).toBe("");
  });
  it("남은 시간 글자", () => {
    expect(rpClock(65)).toBe("1:05");
    expect(rpClock(3725)).toBe("1시간 2분");
    expect(rpClock(-5)).toBe("0:00");
  });
  it("시계: 서버 시계 차이를 맞추고, 피크면 멈춤, 지나면 '지남'", () => {
    const fetched = Date.parse("2026-11-19T12:00:00Z");
    // 서버는 10분 남았다고 했는데 due_at 은 브라우저 기준 15분 뒤 → 서버 시계가 5분 빠름. 남은 시간은 10분으로 센다
    const [c] = clocksOf([{ remaining_seconds: 600, due_at: "2026-11-19T12:15:00Z" }], false, fetched);
    expect(clockView(c, fetched)).toEqual({ text: "10:00 남음", tone: "" });
    expect(clockView(c, fetched + 9 * 60000).tone).toBe("soon");
    expect(clockView(c, fetched + 11 * 60000)).toEqual({ text: "기한 1:00 지남", tone: "over" });
    const [p] = clocksOf([{ remaining_seconds: 600, due_at: "2026-11-19T12:10:00Z" }], true, fetched);
    expect(clockView(p, fetched + 60000)).toEqual({ text: "멈춤 · 10:00 남음", tone: "paused" });
  });
  it("점수 추이: 점이 없으면 null, 폭은 280~860", () => {
    expect(trendGeometry([], 500)).toBeNull();
    const g = trendGeometry([{ date: "2026-11-01", score: 100 }, { date: "2026-11-02", score: 90 }], 2000);
    expect(g.W).toBe(860);
    expect(g.lo).toBe(80);
    expect(g.label).toBe("날마다 응대 점수: 11/1 100점에서 11/2 90점, 가장 낮은 날 90점");
  });
  it("인쇄 머리글 한 줄 (탭의 기간과 만든 시각)", () => {
    const now = new Date(2026, 10, 20);
    expect(printMeta(now, { day: "2026-11-20", kind: "weekly", period: { label: "11월 3주", range: "11/16 ~ 11/22" }, created: "2026-11-20T15:00:00+09:00" }))
      .toBe("출력한 날 2026-11-20 · 오늘 요약 2026-11-20 · 주간 보고서 11월 3주 (11/16 ~ 11/22) · 11-20 15:00에 만든 보고서 · 응대 점수 최근 28일");
    expect(printMeta(now, { kind: "monthly" })).toBe("출력한 날 2026-11-20 · 응대 점수 최근 28일");
  });
});

describe("주간·월간 저장 보고서", () => {
  it("타일 4개: 지난 기간 비교, 자료가 없으면 '–'", () => {
    expect(tilesOf(view()).map((t) => [t.label, t.value, t.sub])).toEqual([
      ["리뷰", "14건", "지난주보다 +3"], ["불만 비율", "29%", "지난주 33%"], ["응대 점수", "91점", "시작 100점 · -9"], ["승인한 글", "7개", "답글 5 · 홍보 2"]]);
    const month = tilesOf(view({ kind: "monthly", report: { review_count: 5, complaint_rate: null, previous: { review_count: 5, complaint_rate: null } }, approvals: null }));
    expect(month.map((t) => [t.value, t.sub])).toEqual([["5건", "지난달과 같아요"], ["–", "지난달 –"], ["–", ""], ["–", ""]]);
    expect(tilesOf(view({ report: { review_count: 0, previous: { review_count: 0 } } }))[0].sub).toBe("아직 리뷰가 없어요");
    expect(tilesOf(view({ report: { review_count: 0, previous: { review_count: 4 } } }))[0].sub).toBe("지난주보다 -4");
  });
  it("승인한 글 나눔: 안내문·그 밖은 있을 때만", () => {
    expect(approvalLine({ reply: 5, promo: 2, notice: 0, other: 0 })).toBe("답글 5 · 홍보 2");
    expect(approvalLine({ reply: 1, promo: 0, notice: 2, other: 1 })).toBe("답글 1 · 홍보 0 · 안내문 2 · 그 밖 1");
    expect(approvalLine(null)).toBe("");
  });
  it("마케팅 숫자: 없는 숫자를 지어내지 않음", () => {
    expect(marketingNumbers(view()).map((x) => x.value)).toEqual(["2개", "–", "–", "–"]);
    expect(marketingNumbers(view({ marketing: { promo_approved: 1, coupon_usage_rate: 0.18, ad_cost_per_order: 1200, notice_recurrence: { before: 3, after: 1 } } }))
      .map((x) => x.value)).toEqual(["1개", "18%", "1,200원", "3 → 1건"]);
    expect(marketingNumbers({}).map((x) => x.value)).toEqual(["–", "–", "–", "–"]);
  });
  it("주제별 흐름: 불만·칭찬 각각 많은 순, 0건은 뺌", () => {
    const rows = topicRows([
      { topic: "a", polarity: "negative", count: 1 }, { topic: "b", polarity: "negative", count: 3 }, { topic: "c", polarity: "negative", count: 0, previous: 2 },
      { topic: "d", polarity: "positive", count: 6 },
    ], 4);
    expect(rows.complaints.map((t) => t.topic)).toEqual(["b", "a"]);
    expect(rows.praises.map((t) => t.topic)).toEqual(["d"]);
    expect(rows.most).toBe(6);
    expect(topicRows(undefined)).toEqual({ complaints: [], praises: [], most: 1 });
  });
  it("저장 안내 띠: 방금 저장 · 저장본 · 낡음 · 확인 못 함 · 게스트 · 저장 못 함", () => {
    expect(savedNote(view({ made_now: true }))).toEqual({ tone: "ok", text: "11-17 09:00에 만들어 저장했어요." });
    expect(savedNote(view({ made_now: true, period: { in_progress: true } })).text)
      .toBe("11-17 09:00에 만들어 저장했어요. 이번 주는 아직 진행 중이라, 새 리뷰가 들어오면 다시 만들어 주세요.");
    expect(savedNote(view())).toEqual({ tone: "ok", text: "11-17 09:00에 만들어 저장한 보고서예요." });
    const stale = (s) => savedNote(view({ stale: { checked: true, is_stale: true, new_reviews: 0, responses_changed: false, approvals_changed: false, period_closed: false, ...s } }));
    expect(stale({ new_reviews: 3 })).toEqual({ tone: "warn", text: "11-17 09:00에 만들어 저장한 보고서예요. 그 뒤 새 리뷰 3건이 들어왔어요 → 다시 만들면 반영돼요." });
    expect(stale({ responses_changed: true }).text).toBe("11-17 09:00에 만들어 저장한 보고서예요. 그 뒤 답글·승인 기록이 바뀌었어요 → 다시 만들면 반영돼요.");
    expect(stale({ new_reviews: 2, approvals_changed: true, period_closed: true }).text)
      .toBe("11-17 09:00에 만들어 저장한 보고서예요. 그 뒤 새 리뷰 2건이 들어왔어요. 답글·승인 기록도 바뀌었어요. 그 주가 끝나기 전에 만든 보고서예요 → 다시 만들면 반영돼요.");
    expect(savedNote(view({ kind: "monthly", stale: { checked: true, is_stale: true, new_reviews: -1, period_closed: true } })).text)
      .toBe("11-17 09:00에 만들어 저장한 보고서예요. 그 뒤 리뷰가 1건 줄었어요. 그 달이 끝나기 전에 만든 보고서예요 → 다시 만들면 반영돼요.");
    expect(savedNote(view({ stale: { checked: true, is_stale: false } })).tone).toBe("ok");
    expect(savedNote(view({ stale: { checked: false } }))).toEqual({ tone: "", text: "11-17 09:00에 만들어 저장한 보고서예요. 지금 기록과 견주지 못했어요." });
    expect(savedNote(view({ storage: "guest" }))).toEqual({ tone: "", text: "로그인하면 만든 보고서가 이 계정에 저장돼요." });
    expect(savedNote(view({ storage: "unavailable" })).tone).toBe("warn");
    expect(savedNote(null)).toEqual({ tone: "", text: "" });
  });
});
