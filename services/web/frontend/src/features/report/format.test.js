import { describe, expect, it } from "vitest";
import { clockView, clocksOf, dateKo, monthKo, peakText, printMeta, rpClock, shiftMonth, signed, trendGeometry } from "./format.js";

describe("종합 리포트 글자", () => {
  it("달 이름과 달 옮기기 (해를 넘김)", () => {
    expect(monthKo("2026-11")).toBe("2026년 11월");
    expect(monthKo(null)).toBe("이번 달");
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-11", -11)).toBe("2025-12");
  });
  it("날짜·부호·피크", () => {
    expect(dateKo("2026-11-05T23:59:00+09:00")).toBe("11/5");
    expect(signed(3)).toBe("+3");
    expect(signed(-2)).toBe("-2");
    expect(signed(undefined)).toBe("0");
    expect(peakText({ peak_hours: ["11-14", "17-21"] })).toBe("11~14시, 17~21시");
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
  it("인쇄 머리글 한 줄", () => {
    const now = new Date(2026, 10, 19);
    expect(printMeta(now, { day: "2026-11-19", month: "2026-11", until: "2026-11-19" }))
      .toBe("출력한 날 2026-11-19 · 오늘 요약 2026-11-19 · 손님 칭찬 요약·월간 보고서 2026년 11월 (11/19까지) · 응대 점수 최근 28일");
  });
});
