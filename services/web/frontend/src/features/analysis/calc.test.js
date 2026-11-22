import { describe, expect, it } from "vitest";
import { bandRows, capCheck, capItems, capStatusLine, groupNote, pasteJoin, periodLine, quoteMeta, repeatedTile, restTopics, summaryTiles, topTopics } from "./calc.js";

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
    // 11/21 QA B-3: 반복 0건이면 '없음' 대신 기준 (2건 묶음이 있어도 반복은 3건부터)
    expect(summaryTiles({ ...d, groups: [] }).repeatedSub).toBe("같은 불만 3건부터");
    expect(summaryTiles({ ...d, groups: [d.groups[1]] })).toMatchObject({ repeated: 0, repeatedSub: "같은 불만 3건부터" });
  });
  it("리뷰 0건인 새 가게: 기간이 비어도 '1일'이 나오지 않는다", () => {
    const empty = { period_start: null, period_end: null, review_count: 0, complaint_count: 0, sentiment_counts: {}, topic_counts: {}, groups: [] };
    expect(summaryTiles(empty)).toEqual({ reviews: 0, reviewsSub: "긍정 0 · 중립 0", complaints: 0, complaintsSub: "", repeated: 0, repeatedSub: "같은 불만 3건부터" });
    expect(topTopics(empty, "negative")).toEqual([]);
    expect(restTopics(empty, "negative")).toEqual([]);
  });
  it("11/21 QA B-5: 8개를 넘는 주제는 '그 밖'으로 (말없이 빠지지 않게)", () => {
    const many = { topic_counts: Object.fromEntries(Array.from({ length: 10 }, (_, i) => [`t${i}`, { negative: 10 - i }])) };
    expect(topTopics(many, "negative")).toHaveLength(8);
    expect(restTopics(many, "negative")).toEqual([{ name: "t8", n: 2 }, { name: "t9", n: 1 }]);
    expect(restTopics(d, "negative")).toEqual([]);
  });
  it("주제는 많은 순, 모르는 id 는 그대로, 0건은 뺌, 막대는 칸 안 최댓값 대비", () => {
    expect(topTopics(d, "negative").map((t) => [t.name, t.n, t.ratio])).toEqual([["포장 누락", 3, 1], ["배달 시간", 2, 2 / 3], ["맛", 2, 2 / 3], ["odd", 1, 1 / 3]]);
    expect(topTopics(d, "positive").map((t) => t.name)).toEqual(["맛", "배달 시간"]);
    expect(topTopics(null, "positive")).toEqual([]);
  });
  it("기간 줄", () => expect(periodLine(d)).toBe("2026-10-12 ~ 2026-11-08 · 리뷰는 합성 데이터"));

  // 11/22 QA: 불만 리뷰 5건인데 '반복 불만 7건'이 리뷰 수로 읽힘 → 숫자는 그대로, 부제에 묶음 수와 합계 기준
  it("반복 불만 타일: 묶음 2개부터 '합계', 같은 리뷰가 두 묶음에 들면 겹친 리뷰를 뺀 수", () => {
    const g1 = { topic_name: "배달 시간", review_count: 4, is_repeated: true, review_ids: ["a", "b", "c", "d"] };
    const g2 = { topic_name: "음식 온도", review_count: 3, is_repeated: true, review_ids: ["a", "b", "e"] };
    const small = { topic_name: "맛", review_count: 2, is_repeated: false, review_ids: ["a", "f"] };
    expect(repeatedTile([g1, g2, small])).toEqual({ value: 7, sub: "묶음 2개 합계 · 겹친 리뷰 빼면 5건 · 배달 시간, 음식 온도" });
    expect(repeatedTile([g1, { ...g2, review_ids: ["e", "f", "g"] }])).toEqual({ value: 7, sub: "묶음 2개 합계 · 배달 시간, 음식 온도" });
    expect(repeatedTile([g1])).toEqual({ value: 4, sub: "묶음 1개 · 배달 시간" });
    expect(repeatedTile([small])).toEqual({ value: 0, sub: "같은 불만 3건부터" });
    expect(repeatedTile(undefined)).toEqual({ value: 0, sub: "같은 불만 3건부터" });
    // 홈 브리핑은 reviews[].review_id, id 를 다 모르면(근거만 일부) 겹침을 말하지 않는다
    const h1 = { topic_name: "배달 시간", review_count: 3, is_repeated: true, reviews: [{ review_id: "a" }, { review_id: "b" }, { review_id: "c" }] };
    const h2 = { topic_name: "음식 온도", review_count: 3, is_repeated: true, reviews: [{ review_id: "a" }, { review_id: "d" }, { review_id: "e" }] };
    expect(repeatedTile([h1, h2]).sub).toBe("묶음 2개 합계 · 겹친 리뷰 빼면 5건 · 배달 시간, 음식 온도");
    expect(repeatedTile([h1, { ...h2, reviews: undefined, evidence: [{ review_id: "a" }] }]).sub).toBe("묶음 2개 합계 · 배달 시간, 음식 온도");
  });
});

describe("불만 묶음", () => {
  const g = { time_bands: { "11~14시": 1, "17~21시": 4 }, main_time_band: "17~21시", previous_count: 0, recent_count: 4 };
  it("한 줄과 시간대 막대", () => {
    expect(groupNote(g)).toBe("주로 17~21시 · 앞 2주 0건 → 최근 2주 4건");
    expect(groupNote({})).toBe("여러 시간대");
    expect(bandRows(g)).toEqual([{ band: "11~14시", n: 1, pct: 25, hot: false }, { band: "17~21시", n: 4, pct: 100, hot: true }]);
  });
  // 11/22 QA: 인용 옆 내부 id(rv_…_paste_002) 대신 채널 · 날짜. 붙여넣은 리뷰는 넣은 날이라 '붙여넣음'
  it("인용 옆 한 조각: 채널 · 날짜", () => {
    const reviews = { r1: { channel: "배민", created_at: "2026-11-03T18:10:00+09:00" }, p1: { channel: null, created_at: "2026-11-22T00:05:00+09:00", input_method: "paste" },
      p2: { channel: "쿠팡이츠", created_at: "2026-11-22T00:06:00+09:00", input_method: "paste" }, x: { text: "글만" } };
    expect(quoteMeta("r1", reviews)).toBe("배민 · 11-03");
    expect(quoteMeta("p1", reviews)).toBe("붙여넣음");
    expect(quoteMeta("p2", reviews)).toBe("쿠팡이츠 · 붙여넣음");
    expect(quoteMeta("x", reviews)).toBe("");
    expect(quoteMeta("none", reviews)).toBe("");
    expect(quoteMeta("none", null)).toBe("");
    // 스토어에 없으면 그 칸의 값 (묶이지 않은 불만: 채널 코드 → 짧은 이름)
    expect(quoteMeta("s1", reviews, { channel: "baemin", created_at: "2026-10-30T12:00:00+09:00" })).toBe("배민 · 10-30");
    expect(quoteMeta("s2", reviews, { channel: "unknown", created_at: "엉뚱한 값" })).toBe("");
    expect(quoteMeta("r1", reviews, { channel: "yogiyo" })).toBe("배민 · 11-03");   // 스토어가 먼저
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
