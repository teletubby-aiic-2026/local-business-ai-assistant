import { describe, it, expect } from "vitest";
import { homeStats, keywordRows, hourChart, scopeChips, sourceLine, reasonByAI, measureIds, replacesOf, statusOf, listBadges, touchedOf, mapDraft, pickCurrent, starText } from "./calc.js";

const briefing = {
  period: { start: "2026-11-12", end: "2026-11-18" },
  counts: { review_count: 20, complaint_count: 5 },
  top_issue_id: "i1",
  groups: [
    { issue_id: "i1", topic_name: "포장 누락", review_count: 3, is_repeated: true, main_time_band: "17~21시",
      reviews: [{ review_id: "r1", created_at: "2026-11-12T18:10:00+09:00" }, { review_id: "r2", created_at: "2026-11-13T19:00:00+09:00" }, { review_id: "r3", created_at: "2026-11-14T12:30:00+09:00" }] },
  ],
  single_complaints: [
    { review_id: "r4", topic_names: ["맛"], created_at: "2026-11-15T13:00:00+09:00" },
    { review_id: "r5", topic_names: ["배달"], created_at: "2026-11-15T13:20:00+09:00" },
    { review_id: "r6", topic_names: ["가격"], created_at: "2026-11-16T20:00:00+09:00" },
  ],
};

describe("홈", () => {
  it("숫자 타일", () => {
    const s = homeStats(briefing);
    expect(s.reviewsSub).toBe("7일 동안");
    expect(s.complaintsSub).toBe("리뷰의 25%");
    expect(s.repeated).toBe(3);
    expect(s.repeatedSub).toBe("포장 누락");
  });
  it("상권 칸 범위 칩: 상권명 · 업종 · 시간대 (지표 이름에서)", () => {
    const snap = { area_name: "장승배기역 4번", metric_name: "저녁 시간대(17~24시) 추정매출 전년 동기 대비 변화율 · 두 분기 공통 업종" };
    expect(scopeChips(snap)).toEqual(["장승배기역 4번", "공통 업종", "17~24시"]);
    expect(scopeChips({ area_name: "노량진", metric_name: "추정매출 변화율" })).toEqual(["노량진"]);
    expect(scopeChips(null)).toEqual([]);
  });
  it("주제별 불만은 상위 3개 + 그 밖, 핵심 문제 주제는 hot", () => {
    const k = keywordRows(briefing);
    expect(k.rows.map((r) => r.topic)).toEqual(["포장 누락", "맛", "배달"]);
    expect(k.rows[0]).toMatchObject({ n: 3, ratio: 1, hot: true });
    expect(k.rows[1].hot).toBe(false);
    expect(k.rest).toEqual([{ topic: "가격", n: 1 }]);
  });
  it("시간 차트는 11~23시, 몰린 시간대 hot, 같은 뜻을 글자로", () => {
    const h = hourChart(briefing);
    expect(h.cols[0].h).toBe(11);
    expect(h.cols.at(-1).h).toBe(23);
    expect(h.cols.find((c) => c.h === 18)).toMatchObject({ n: 1, hot: true });
    expect(h.cols.find((c) => c.h === 21).hot).toBe(false);
    expect(h.cols.find((c) => c.h === 13)).toMatchObject({ n: 2, height: 100 });
    expect(h.cols.find((c) => c.h === 14).height).toBe(2);
    expect(h.label).toBe("시간대별 불만 리뷰: 12시 1건, 13시 2건, 18시 1건, 19시 1건, 20시 1건");
    expect(h.note).toBe("빨간 막대 = 포장 누락이 몰린 17~21시");
  });
});

describe("카드", () => {
  const p = {
    card: { card_id: "a", kind: "complaint", review_ids: ["r1", "r2"] },
    evidence: [{ type: "review", id: "r1" }, { type: "review", id: "r2" }, { type: "snapshot", basis: "서울 상권 · https://x.test/a" }],
    measures: { options: [{ id: "M1" }, { id: "M2" }, { id: "M3" }], default: ["M1"] },
  };
  it("근거 한 줄", () => expect(sourceLine(p)).toBe("리뷰 2건 · 합성 데이터 · 서울 상권"));
  it("이유 문장을 AI 가 썼는지 (검사기 통과한 모델 문장만)", () => {
    expect(reasonByAI({ reason_source: "HCX-005 (검사기 통과)" })).toBe(true);
    expect(reasonByAI({ reason_source: "고정 문장" })).toBe(false);
    expect(reasonByAI({ reason_source: "HCX-005 실패 → 고정 문장" })).toBe(false);
    expect(reasonByAI({})).toBe(false);
  });
  it("점검 수칙: 바꾼 값 → 고른 값 → 기본값, 선택지 순서", () => {
    expect(measureIds(p, {}, {})).toEqual(["M1"]);
    expect(measureIds(p, { a: { chosen_measures: [{ id: "M3" }, { id: "M2" }] } }, {})).toEqual(["M2", "M3"]);
    expect(measureIds(p, { a: { chosen_measures: [{ id: "M3" }] } }, { a: ["M3", "M1"] })).toEqual(["M1", "M3"]);
    expect(measureIds(p, {}, { a: ["M9"] })).toEqual([]);
  });
  it("replaces 는 승인한 글부터 20개", () => {
    const ids = Array.from({ length: 25 }, (_, i) => `d${i}`);
    const out = replacesOf(ids, new Set(["d24"]));
    expect(out).toHaveLength(20);
    expect(out[0]).toBe("d24");
  });
});

describe("초안", () => {
  const d1 = { draft_id: "d1", generator: "reply_draft", text: "가" };
  const d2 = { draft_id: "d2", generator: "prevention_notice", text: "나", failed_reasons: ["x"] };
  const d3 = { draft_id: "d3", generator: "reply_draft", text: "다", c7_flags: ["y"] };
  const s = { cards: [{ card: { card_id: "a" } }, { card: { card_id: "b" } }], results: { a: { drafts: [d1, d2, d3] } }, approved: new Set(["d1"]), pending: { d3: "다다" }, current: null, draftId: null };
  it("글 상태", () => {
    expect(statusOf(d1, s.approved)).toEqual(["ok", "승인 완료"]);
    expect(statusOf(d2, s.approved)).toEqual(["bad", "점검 실패"]);
    expect(statusOf(d3, s.approved)).toEqual(["warn", "확인 필요"]);
  });
  it("초안 목록 배지: 승인 상태 먼저, 승인 전이면 점검 결과를 덧붙임", () => {
    expect(listBadges(d1, s.approved)).toEqual([["ok", "승인 완료"]]);
    expect(listBadges(d2, s.approved)).toEqual([["", "승인 대기"], ["bad", "점검 실패"]]);
    expect(listBadges(d3, s.approved)).toEqual([["", "승인 대기"], ["warn", "확인 필요"]]);
    expect(listBadges({ draft_id: "d4" }, s.approved)).toEqual([["", "승인 대기"]]);   // 점검 통과는 '승인 대기'만
  });
  it("승인했거나 고친 글 수", () => expect(touchedOf(s, "a")).toBe(2));
  it("보일 카드·글: 안내문이 먼저, 첫 미승인 글", () => {
    const c = pickCurrent(s);
    expect(c.current).toBe("a");
    expect(c.drafts.map((d) => d.draft_id)).toEqual(["d2", "d1", "d3"]);
    expect(c.draftId).toBe("d2");
    expect(pickCurrent({ ...s, draftId: "d3" }).draftId).toBe("d3");
  });
  it("mapDraft 는 새 객체를 만든다", () => {
    const out = mapDraft(s.results, "d2", (x) => ({ ...x, edited_text: "z" }));
    expect(out.a).not.toBe(s.results.a);
    expect(out.a.drafts[1].edited_text).toBe("z");
    expect(s.results.a.drafts[1].edited_text).toBeUndefined();
  });
  it("별점", () => { expect(starText(4)).toBe("★★★★☆"); expect(starText(0)).toBe(""); });
});
