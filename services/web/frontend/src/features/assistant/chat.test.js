import { describe, it, expect } from "vitest";
import {
  CHAT_SCOPE_DAY, chatQuarter, chatPeriod, chatCondText, chatNavTarget, chatBlocks, chatPieces, chatScopeNote, chatSuggest, chatSameKey, chatValue,
} from "./chat.js";

describe("분기 표기", () => {
  it("문장 속 분기 코드만 바꾸고 금액·개수는 그대로", () => {
    expect(chatQuarter("20262 자료로 볼게요")).toBe("2026년 2분기 자료로 볼게요");
    expect(chatQuarter("2026Q2 기준")).toBe("2026년 2분기 기준");
    expect(chatQuarter("20262원, 20,262, 120262")).toBe("20262원, 20,262, 120262");
    expect(chatQuarter("20262분기")).toBe("2026년 2분기");
  });
  it("조건 줄의 분기", () => {
    expect(chatPeriod({ period: "20262" })).toBe("2026년 2분기");
    expect(chatPeriod({ period_label: "2026년 2분기" })).toBe("2026년 2분기");
    expect(chatCondText({ area_name: "장승배기역 4번", industry_name: "한식음식점", period: "20262" })).toBe("장승배기역 4번 상권 · 한식음식점 · 2026년 2분기");
    expect(chatCondText(null)).toBe("");
  });
});

describe("답의 기준 범위", () => {
  it("칩은 '하루 전체', 안내 한 줄은 추정치·우리 가게 매출 아님·홈 타일 범위", () => {
    expect(CHAT_SCOPE_DAY).toBe("하루 전체");
    expect(chatScopeNote("공통 업종 17~24시")).toBe("상권·업종 전체 추정치예요 (우리 가게 매출 아님 · 홈 타일은 공통 업종 17~24시 기준)");
    expect(chatScopeNote("")).toBe("상권·업종 전체 추정치예요 (우리 가게 매출 아님)");
  });
});

describe("화면 이동 버튼", () => {
  it("navigate·handoff 만 화면으로", () => {
    expect(chatNavTarget({ payload: { type: "navigate", route: "analysis", sub: "paste" } })).toEqual({ route: "analysis", sub: "paste" });
    expect(chatNavTarget({ payload: { type: "navigate", route: "market" } })).toEqual({ route: "market", sub: null });
    expect(chatNavTarget({ payload: { type: "handoff", domain: "marketing" } })).toEqual({ route: "marketing", sub: null });
    expect(chatNavTarget({ payload: { type: "handoff", domain: "customer" } })).toEqual({ route: "cards", sub: null });
    expect(chatNavTarget({ payload: { type: "choose_location", code: "1" } })).toBeNull();
  });
});

describe("답 글 나누기", () => {
  it("목록·특별 줄·빈 줄", () => {
    const b = chatBlocks("첫 줄 [F1]\n- 하나\n- 둘\n\n- 셋\n참고: 메모\n해석: 풀이\n다음으로 이것");
    expect(b.map((x) => x.type + (x.kind || ""))).toEqual(["p", "ul", "ul", "pnote", "pinsight", "pnext"]);
    expect(b[1].items).toEqual(["하나", "둘"]);
    expect(b[3]).toMatchObject({ lead: "참고:", line: " 메모" });
  });
  it("인용 조각", () => {
    expect(chatPieces("매출 [F2] 이에요 [F9]")).toEqual([{ text: "매출 " }, { cite: "F2", raw: "[F2]" }, { text: " 이에요 " }, { cite: "F9", raw: "[F9]" }]);
  });
  it("suggestions 는 글자만 3개까지", () => {
    expect(chatSuggest({ suggestions: ["a", " ", 3, "b", "c", "d"] })).toEqual(["a", "b", "c"]);
  });
  it("payload 비교는 키 순서와 무관", () => {
    expect(chatSameKey({ a: 1, b: 2 }, { b: 2, a: 1 })).toBe(true);
    expect(chatSameKey({ a: 1 }, { a: 2 })).toBe(false);
  });
  it("값 모양", () => {
    expect(chatValue(null)).toBe("확인 불가");
    expect(chatValue(1000, "원")).toBe("1,000원");
    expect(chatValue(12.5, "%")).toBe("12.50%");
  });
});
