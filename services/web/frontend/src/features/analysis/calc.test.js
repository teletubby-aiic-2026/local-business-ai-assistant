import { describe, expect, it } from "vitest";
import { bandRows, capCheck, capItems, capStatusLine, groupNote, pasteJoin, periodLine, summaryTiles, topTopics } from "./calc.js";

const d = {
  period_start: "2026-10-12", period_end: "2026-11-08", review_count: 40, complaint_count: 12,
  sentiment_counts: { negative: 12, positive: 26, neutral: 2 },
  topic_counts: { missing_item: { positive: 0, negative: 3 }, delivery_time: { positive: 2, negative: 2 }, taste: { positive: 13, negative: 2 }, odd: { negative: 1 } },
  groups: [{ issue_id: "iss_missing_item", topic_name: "포장 누락", review_count: 3, is_repeated: true },
    { issue_id: "iss_x", topic_name: "맛", review_count: 2, is_repeated: false }],
  data_origin: "synthetic",
};

describe("요약", () => {
  it("타일 세 개를 예전 문장으로", () => {
    expect(summaryTiles(d)).toEqual({ reviews: 40, reviewsSub: "28일 · 긍정 26 · 중립 2", complaints: 12, complaintsSub: "리뷰의 30%",
      repeated: 3, repeatedSub: "묶음 1개 · 포장 누락" });
    expect(summaryTiles(null).reviews).toBe("–");
    expect(summaryTiles({ ...d, groups: [] }).repeatedSub).toBe("없음");
  });
  it("주제는 많은 순, 모르는 id 는 그대로, 0건은 뺌, 막대는 칸 안 최댓값 대비", () => {
    expect(topTopics(d, "negative").map((t) => [t.name, t.n, t.ratio])).toEqual([["포장 누락", 3, 1], ["배달 시간", 2, 2 / 3], ["맛", 2, 2 / 3], ["odd", 1, 1 / 3]]);
    expect(topTopics(d, "positive").map((t) => t.name)).toEqual(["맛", "배달 시간"]);
    expect(topTopics(null, "positive")).toEqual([]);
  });
  it("기간 줄", () => expect(periodLine(d)).toBe("2026-10-12 ~ 2026-11-08 · 리뷰는 합성 데이터"));
});

describe("불만 묶음", () => {
  const g = { time_bands: { "11~14시": 1, "17~21시": 4 }, main_time_band: "17~21시", previous_count: 0, recent_count: 4 };
  it("한 줄과 시간대 막대", () => {
    expect(groupNote(g)).toBe("주로 17~21시 · 앞 2주 0건 → 최근 2주 4건");
    expect(groupNote({})).toBe("여러 시간대");
    expect(bandRows(g)).toEqual([{ band: "11~14시", n: 1, pct: 25, hot: false }, { band: "17~21시", n: 4, pct: 100, hot: true }]);
  });
  it("붙여넣기 결과의 들어간 묶음", () => {
    const r = { classification: { topics: [{ topic: "packaging", polarity: "negative" }] }, joined_issues: ["iss_missing_item", "iss_?"] };
    expect(pasteJoin(r, d.groups)).toEqual({ joined: ["포장 누락", "iss_?"], negative: true });
    expect(pasteJoin({ classification: { topics: [] } }, []).negative).toBe(false);
  });
});

describe("캡처", () => {
  it("파일 확인", () => {
    expect(capCheck({ type: "image/gif", size: 1 })).toMatch("png·jpg·webp");
    expect(capCheck({ type: "image/png", size: 11 * 1024 * 1024 })).toMatch("10MB");
    expect(capCheck({ type: "", size: 10 })).toBe("");
  });
  it("후보: 이상한 별점은 모름, 이미 있는 리뷰는 처음에 안 고름", () => {
    const items = capItems({ candidates: [{ text: "a", rating: 5 }, { text: "b", rating: 7, duplicate: true, pii_masked: true }, { rating: 3 }, null] });
    expect(items).toEqual([
      { text: "a", rating: "5", ai: 5, pii: false, dup: false, picked: true, saved: false, msg: "" },
      { text: "b", rating: "", ai: null, pii: true, dup: true, picked: false, saved: false, msg: "" },
    ]);
    // 고치고 고르라는 안내는 후보 목록 위 확인 경고 한 곳에만 (상태 줄에서는 뺌)
    expect(capStatusLine({ demo: true, pieces: 3 }, 2)).toBe("후보 2건 · 3조각으로 나눠 읽음 · 예시 결과");
    expect(capStatusLine({ engine: "HCX-005" }, 1)).toBe("후보 1건 · 읽은 모델 HCX-005");
  });
});

describe("분류 방식 배지", () => {
  it("model·rule 은 사람이 읽는 이름으로, 그 밖 값은 저장된 AI 분류, 빈 값은 숨김", async () => {
    const { methodName } = await import("./calc.js");
    expect(methodName("model")).toBe("AI 분류");
    expect(methodName("saved")).toBe("저장된 AI 분류");
    expect(methodName("rules")).toBe("규칙 분류 (AI 아님)");
    expect(methodName("rule")).toBe("규칙 분류 (AI 아님)");
    expect(methodName("")).toBe("");
    expect(methodName(undefined)).toBe("");
  });
});
