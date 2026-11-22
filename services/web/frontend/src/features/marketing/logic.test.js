import { describe, expect, it } from "vitest";
import { MKT_ADSPEND_RULE, MKT_MODES, MKT_PROFIT_TILE, MKT_REPORT_DESC, MKT_UNIT, askQuestionOf, badgeOf, calcRange, downKey, draftLabel, initialDrafts,
  progressLabel, reportView, tilesOf, verdictCountText, whyLinesOf, wonKo } from "./logic.js";

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
      .toEqual([["2개", "점검한 채널"], ["손해 0개 · 주의 1개", "채널 판정"], [wonKo(3000), "건당 남는 돈 (광고비 빼기 전)"]]);
    expect(tilesOf({ coupon_card: { discount_won: 2000, count: 30, breakeven_orders: 5 } }))
      .toEqual([[wonKo(2000), "할인액"], ["30장", "발급 수량"], ["5건", "본전 주문 수"]]);
  });
  it("광고비 판정 타일은 손해·주의를 나눠 세고, 둘 다 없으면 '모두 괜찮음' (11/22 QA: 흑자인 주의가 손해와 묶였다)", () => {
    expect(verdictCountText([{ verdict: "손해 광고" }, { verdict: "주의" }, { verdict: "주의" }, { verdict: "괜찮음" }])).toBe("손해 1개 · 주의 2개");
    expect(verdictCountText([{ verdict: "손해 광고" }])).toBe("손해 1개 · 주의 0개");
    expect(verdictCountText([{ verdict: "괜찮음" }, { verdict: "괜찮음" }])).toBe("모두 괜찮음");
    expect(verdictCountText([{ verdict: null }])).toBe("–");
    expect(verdictCountText([])).toBe("–");
    // 기준 문장은 서버 adspend.judge 와 같은 기준(이상 → 손해, 절반 이상 → 주의), '건당 남는 돈'은 광고비 빼기 전 값임을 밝힘
    expect(MKT_ADSPEND_RULE).toBe("주문 1건에 든 광고비가 남는 돈 이상이면 '손해 광고', 절반 이상이면 '주의'예요.");
    expect(MKT_PROFIT_TILE).toBe("건당 남는 돈 (광고비 빼기 전)");
  });
  it("남는 비율 '직접 입력' 칸(보기와 같은 키)은 단위가 %", () => {
    expect([MKT_UNIT.adspend_margin_pct, MKT_UNIT.coupon_margin_pct, MKT_UNIT.survey_margin_pct]).toEqual(["%", "%", "%"]);
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
  it("글 상자 순서는 할 일 → 기본 할 일, 데모면 '예시' 표시 (실제 AI 결과 아님은 카드 배지가 알림)", () => {
    const { drafts, order } = initialDrafts({ steps: [{ step_id: "notice", generator: "prevention_notice" }, { step_id: "x" }],
      drafts: { notice: "공지 글" }, basic_todos: [{ title: "a", draft: "기본 글" }] }, "survey", true);
    expect(order).toEqual(["notice", "basic_todo_0"]);
    expect(drafts.notice.kind).toBe("공지");
    expect(drafts.notice.label).toBe("공지 예시");
    expect(draftLabel("홍보 글", false)).toBe("홍보 글 초안");
    expect(draftLabel("아이디어 글", false, true)).toBe("아이디어 글 · 정해 둔 틀 (AI 아님)");
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
  it("시작 모드 설명은 받는 결과 중심으로 짧게, 질문 진행 표시는 '질문 n'", () => {
    expect(Object.keys(MKT_MODES)).toEqual(["맞춤 홍보 제안", "남은 재료 팔기", "광고비 점검", "가게 이야기 글", "쿠폰 결과 확인"]);
    for (const d of [...Object.values(MKT_MODES), MKT_REPORT_DESC]) {
      expect(d).not.toMatch(/여쭤|알려 드려요|드려요/);
      expect(d.length).toBeLessThanOrEqual(24);
    }
    expect(progressLabel(0)).toBe("");
    expect(progressLabel(3)).toBe("질문 3");
  });
});

describe("'AI에게 이어서 묻기' 질문", () => {
  it("광고비 표 → 쿠폰·할인 → 불만 먼저 고치기 → 그 밖 순서로 고른다", () => {
    expect(askQuestionOf({ data: { table: [], coupon_card: {} } })).toBe("주변에 같은 업종 점포는 몇 개야?");
    expect(askQuestionOf({ data: { coupon_card: { discount_won: 2000 } } })).toBe("점심과 저녁 중 매출은 어디가 커?");
    expect(askQuestionOf({ data: { usage_rate: null } })).toBe("점심과 저녁 중 매출은 어디가 커?");
    expect(askQuestionOf({ data: { usage_rate: 0.3, strategy_type: "fix_first" } })).toBe("점심과 저녁 중 매출은 어디가 커?");
    expect(askQuestionOf({ data: { strategy_type: "fix_first" } })).toBe("불만 리뷰 제일 많은 게 뭐야?");
    expect(askQuestionOf({ data: { title: "맞춤 홍보 제안" } })).toBe("우리 가게 상권 매출은 어때?");
    expect(askQuestionOf({})).toBe("우리 가게 상권 매출은 어때?");
  });
});
