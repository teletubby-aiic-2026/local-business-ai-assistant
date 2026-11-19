import { describe, expect, it } from "vitest";
import { badgeOf, calcRange, downKey, initialDrafts, reportView, tilesOf, whyLinesOf, wonKo } from "./logic.js";

describe("맞춤 마케팅 계산", () => {
  it("광고비 표는 가장 나쁜 판정을 배지로", () => {
    expect(badgeOf({ table: [{ verdict: "괜찮음" }, { verdict: "손해 광고" }, { verdict: "주의" }] })).toEqual(["bad", "손해 광고"]);
    expect(badgeOf({ table: [{ verdict: null }] })).toBe(null);
  });
  it("쿠폰 사용률로 배지를 가른다", () => {
    expect(badgeOf({ usage_rate: null })).toEqual(["bad", "점검 필요"]);
    expect(badgeOf({ usage_rate: 0.1 })).toEqual(["warn", "주의"]);
    expect(badgeOf({ usage_rate: 0.5 })).toEqual(["ok", "같은 조건 유지"]);
    expect(badgeOf({ usage_rate: 0.6 })).toEqual(["warn", "할인 큼"]);
    expect(badgeOf({ strategy_type: "fix_first" })).toEqual(["bad", "먼저 고치기"]);
    expect(badgeOf({})).toEqual(["", "정보"]);
  });
  it("숫자 타일", () => {
    expect(tilesOf({ table: [{ verdict: "주의" }, { verdict: "괜찮음" }], profit_per_order_won: 3000 }))
      .toEqual([["2개", "점검한 채널"], ["1개", "주의·손해 채널"], [wonKo(3000), "건당 이익(추정)"]]);
    expect(tilesOf({ coupon_card: { discount_won: 2000, count: 30, breakeven_orders: 5 } }))
      .toEqual([[wonKo(2000), "할인액"], ["30장", "발급 수량"], ["5건", "본전 주문 수"]]);
  });
  it("판단 근거는 result 설명 → summary → 할 일 하나의 tip", () => {
    expect(whyLinesOf({ summary: "s" }, { explain: ["a", "b"] })).toEqual(["a", "b"]);
    expect(whyLinesOf({ summary: "s" }, null)).toEqual(["s"]);
    expect(whyLinesOf({ steps: [{ tip: "t" }] }, null)).toEqual(["t"]);
  });
  it("슬라이더 범위는 가격의 5~30%, 예산은 30만 원까지", () => {
    expect(calcRange({ price_won: 20000, discount_won: 500, budget_won: 500000 })).toEqual({ minD: 1000, maxD: 6000, startD: 1000, budget: 300000 });
    expect(calcRange({ price_won: 0 })).toEqual({ minD: 100, maxD: 100, startD: 100, budget: 0 });
  });
  it("글 상자 순서는 할 일 → 기본 할 일, 데모면 시험용 표시", () => {
    const { drafts, order } = initialDrafts({ steps: [{ step_id: "notice", generator: "prevention_notice" }, { step_id: "x" }],
      drafts: { notice: "공지 글" }, basic_todos: [{ title: "a", draft: "기본 글" }] }, "survey", true);
    expect(order).toEqual(["notice", "basic_todo_0"]);
    expect(drafts.notice.kind).toBe("공지");
    expect(drafts.notice.label).toBe("공지 · 시험용 저장 예시 (실제 AI 결과 아님)");
  });
  it("서비스 상태 열쇠", () => {
    expect(downKey("off")).toBe("off");
    expect(downKey("timeout")).toBe("down");
    expect(downKey("slow")).toBe("error");
  });
  it("보고서 숫자", () => {
    const v = reportView({ period: { kind: "monthly", start: "2026-11-01", until: "2026-11-30T23:59" }, activity: { approved: { 공지: 2, 답글: 1 } },
      cost: { coupon: { usage_rate: 0.25, issued: 40, used: 10, discount_spent: 20000 } } }, "weekly");
    expect(v.L.now).toBe("이번 달");
    expect(v.until).toBe("2026-11-30");
    expect(v.tiles[0]).toEqual(["3건", "승인한 글 (공지 2 · 답글 1)"]);
    expect(v.tiles[1]).toEqual(["25%", "쿠폰 사용률 (40장 중 10장)"]);
    expect(v.empty).toBe(false);
  });
});
