import { describe, expect, it } from "vitest";
import { initialState } from "./store.js";
import { staffOf, todosOf, waitingCount } from "./staff.js";
import { heroProblem, homeSnap, marketScope, snapValue } from "../lib/domain.js";

const briefing = {
  counts: { review_count: 20, complaint_count: 5 },
  top_issue_id: "iss_missing_item",
  groups: [{ issue_id: "iss_missing_item", topic_name: "포장 누락", review_count: 3, is_repeated: true, main_time_band: "17~21시",
    reviews: [{ review_id: "r1" }, { review_id: "r2" }, { review_id: "r3" }] }],
  single_complaints: [{ review_id: "r4" }],
  pasted: [],
  snapshots: [{ value: null }, { value: -19.31, unit: "%", area_name: "장승배기역 4번", metric_name: "저녁 시간대(17~24시) 추정매출 · 두 분기 공통 업종" }],
};
const cards = [
  { card: { card_id: "card_ongi_a", kind: "complaint", review_ids: ["r1"] }, evidence: [{ type: "review" }, { type: "review" }] },
  { card: { card_id: "card_ongi_b", kind: "promo", review_ids: ["p1", "p2"] }, evidence: [{ type: "praise", menu: "제육볶음" }] },
];
const base = (extra = {}) => ({ ...initialState(), briefing, cards, booted: true, ...extra });

describe("오늘 할 일", () => {
  it("만들기 전에는 카드 ⓐ 두 줄과 카드 ⓑ 한 줄", () => {
    const t = todosOf(base());
    expect(t.map((x) => x.key)).toEqual(["notice", "reply", "promo"]);
    expect(t[1].title).toBe("답글 2개 승인");
    expect(t.every((x) => x.st[0] === "none")).toBe(true);
    expect(t[2].sub).toContain("손님이 칭찬한 제육볶음 쿠폰으로");
    expect(t[2].agent).toBe("마케팅 비서");
  });

  it("만든 글의 승인 수를 센다", () => {
    const results = { card_ongi_a: { drafts: [
      { draft_id: "d1", generator: "reply_draft", target_review_id: "r1" },
      { draft_id: "d2", generator: "reply_draft", target_review_id: "r2" },
      { draft_id: "d3", generator: "prevention_notice" },
    ] } };
    const s = base({ results, approved: new Set(["d3", "d1"]) });
    const t = todosOf(s);
    expect(t[0].st).toEqual(["done", "완료"]);
    expect(t[1].st).toEqual(["wait", "승인 1 / 2"]);
    expect(waitingCount(s)).toBe(1);
    const care = staffOf(s).find((x) => x.key === "care");
    expect(care.text).toBe("승인 대기 1개 · 답글 안 단 불만 3건");
  });
});

describe("AI 비서", () => {
  it("네 명의 이름과 상권 상태", () => {
    const st = staffOf(base({ staffMarket: { state: "ready", data: { latest_period_label: "2026년 2분기" } } }));
    expect(st.map((x) => x.name)).toEqual(["데이터 분석 비서", "고객 응대 비서", "마케팅 비서", "상권 분석 비서"]);
    expect(st[0].text).toBe("리뷰 20건 정리 끝");
    expect(st[3]).toMatchObject({ ok: true, text: "상권 자료 준비 · 2026년 2분기까지" });
  });

  it("상권 서비스를 아직 모르면 확인 중", () => {
    expect(staffOf(base()).find((x) => x.key === "market").text).toBe("확인 중");
  });
});

describe("홈 지표 도우미", () => {
  it("값이 있는 첫 지표와 범위", () => {
    const s = homeSnap(briefing);
    expect(snapValue(s)).toBe("-19.31%");
    expect(marketScope(s)).toBe("공통 업종 17~24시");
    expect(heroProblem(briefing)).toBe("포장 누락 3건 반복 · 17~21시에 몰림");
  });
});
