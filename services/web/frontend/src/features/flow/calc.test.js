import { describe, it, expect } from "vitest";
import { homeStats, keywordRows, hourChart, scopeChips, sourceLine, reasonByAI, measureIds, replacesOf, statusOf, listBadges, touchedOf, mapDraft, pickCurrent, starText,
  changedFromDraft, EDITED_CHECK_NOTE,
  draftStateText, isFallback, regenNote, hourNotes, cardsIntro, targetLine, mergeApprovals, serverName, whenText, priorApprovals, priorByCard, priorNote } from "./calc.js";

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
    // 11/22 QA: 리뷰 분석 요약 탭과 같은 부제 (묶음 수 · 주제). 2개부터는 '합계', 겹친 리뷰가 있으면 뺀 수도
    expect(s.repeatedSub).toBe("묶음 1개 · 포장 누락");
    const g2 = { issue_id: "i2", topic_name: "음식 온도", review_count: 3, is_repeated: true, reviews: [{ review_id: "r1" }, { review_id: "r2" }, { review_id: "r9" }] };
    expect(homeStats({ ...briefing, groups: [...briefing.groups, g2] })).toMatchObject({ repeated: 6, repeatedSub: "묶음 2개 합계 · 겹친 리뷰 빼면 4건 · 포장 누락, 음식 온도" });
  });
  it("리뷰 0건인 새 가게: 기간이 비어도 '1일 동안'이 나오지 않는다", () => {
    const s = homeStats({ period: { start: null, end: null }, counts: { review_count: 0, complaint_count: 0 }, groups: [] });
    // 11/21 QA: 0건이면 '없음' 대신 반복 기준 (불만 묶음 탭과 같은 정의)
    expect(s).toMatchObject({ reviews: 0, reviewsSub: "", complaints: 0, complaintsSub: "", repeated: 0, repeatedSub: "같은 불만 3건부터" });
    expect(homeStats({ counts: {} }).reviewsSub).toBe("");
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
    // 11/21 QA: 점검 통과도 칩으로 (Figma 06 B3)
    expect(listBadges({ draft_id: "d4" }, s.approved)).toEqual([["", "승인 대기"], ["ok", "점검 통과"]]);
  });
  it("초안 목록의 대상 리뷰: 답글이면 원 리뷰 첫 줄 앞부분, 리뷰를 모르면 빈 글", () => {
    const reviews = { r1: { text: "공깃밥 추가했는데 안 들어 있었어요\n둘째 줄" }, r2: { text: "가".repeat(40) } };
    expect(targetLine({ target_review_id: "r1" }, reviews)).toBe("공깃밥 추가했는데 안 들어 있었어요");
    expect(targetLine({ target_review_id: "r2" }, reviews)).toBe(`${"가".repeat(23)}…`);
    expect(targetLine({ target_review_id: "r9" }, reviews)).toBe("");
    expect(targetLine({ target_review_id: null }, reviews)).toBe("");
  });
  it("승인했거나 고친 글 수", () => expect(touchedOf(s, "a")).toBe(2));
  // 11/22 QA: 고친 글에는 '점검 결과는 고치기 전 글 기준' 한 줄 (점검 칩은 원문 기준)
  it("원문과 다른 글인지: 고치는 중 · 고쳐서 승인 · 되돌림 · 앞뒤 공백만 다름", () => {
    expect(changedFromDraft(s, d3)).toBe(true);                                             // 고치는 중 ('다' → '다다')
    expect(changedFromDraft(s, d1)).toBe(false);                                            // 고치지 않고 승인
    expect(changedFromDraft(s, { ...d1, edited_text: "가가" })).toBe(true);                  // 고쳐서 승인
    expect(changedFromDraft({ pending: { d1: "가" } }, { ...d1, edited_text: "가가" })).toBe(false);   // 고쳐서 승인한 뒤 원문으로 되돌리는 중
    expect(changedFromDraft({ pending: { d3: " 다 \n" } }, d3)).toBe(false);                 // 앞뒤 공백만
    expect(EDITED_CHECK_NOTE).toBe("점검 결과는 고치기 전 글 기준이에요.");
  });
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

describe("기본 문장으로 바꾼 글 (11/21 실시간 확인 M2)", () => {
  const fb = { draft_id: "f1", text: "주문하신 품목이 빠져 있었다니 정말 죄송해요.", checks: { used_fallback: true } };
  it("점검 상태 규칙(statusOf)은 그대로 '점검 통과'지만, 화면 이름은 '기본 문장으로 바꿈'이고 목록 배지는 '기본 문장'", () => {
    expect(isFallback(fb)).toBe(true);
    expect(isFallback({ checks: { used_fallback: false } })).toBe(false);
    expect(isFallback({})).toBe(false);
    expect(statusOf(fb, new Set())).toEqual(["ok", "점검 통과"]);          // 측정 스크립트와 같은 규칙은 바꾸지 않음
    expect(draftStateText(fb, new Set())).toBe("기본 문장으로 바꿈");
    expect(draftStateText(fb, new Set(["f1"]))).toBe("승인 완료");
    expect(draftStateText({ draft_id: "x" }, new Set())).toBe("점검 통과");
    expect(listBadges(fb, new Set())).toEqual([["", "승인 대기"], ["warn", "기본 문장"]]);
    expect(listBadges({ ...fb, c7_flags: ["확인"] }, new Set())).toEqual([["", "승인 대기"], ["warn", "확인 필요"], ["warn", "기본 문장"]]);
    expect(listBadges(fb, new Set(["f1"]))).toEqual([["ok", "승인 완료"]]);
  });
  it("다시 만들기 뒤 안내: 같은 글·또 기본 문장이면 사실대로", () => {
    expect(regenNote(fb, { ...fb, draft_id: "f2" }, "live")).toBe("다시 만들었지만 같은 기본 문장이 나왔어요. 리뷰와 맞게 직접 고쳐서 승인해 주세요.");
    expect(regenNote(fb, { ...fb, text: "다른 기본 문장" }, "live")).toBe("다시 만들었지만 이번에도 기본 문장으로 바뀌었어요. 리뷰와 맞는지 확인하고 고쳐서 승인해 주세요.");
    expect(regenNote({ text: "A" }, { text: "A" }, "live")).toBe("다시 만들었지만 같은 글이 나왔어요. 필요하면 직접 고쳐서 승인해 주세요.");
    expect(regenNote({ text: "A" }, { text: "B" }, "live")).toBe("이 글만 새로 만들었어요. 다른 글은 그대로예요.");
    expect(regenNote({ text: "A" }, { text: "A" }, "seed")).toBe("시험용 실행이라 같은 예시 글을 다시 불러왔어요. 다른 글은 그대로예요.");
  });
});

describe("hourChart: 붙여넣은 리뷰는 시간대 막대에 세지 않는다 (11/21)", () => {
  it("넣은 시각(00시)이 아니라, 작성 시각을 아는 리뷰만 센다", () => {
    const b = {
      top_issue_id: "iss_a", pasted: [{ review_id: "rv_p1" }, { review_id: "rv_p2" }],
      groups: [{ issue_id: "iss_a", topic_name: "포장 누락", main_time_band: "17~21시",
        reviews: [{ review_id: "rv_1", created_at: "2026-11-01T18:10:00+09:00", input_method: "sample" },
                  { review_id: "rv_p1", created_at: "2026-11-21T00:03:00+09:00", input_method: "paste" }] }],
      single_complaints: [{ review_id: "rv_p2", topic_names: ["맛"], created_at: "2026-11-21T00:05:00+09:00" }],
    };
    const chart = hourChart(b);
    expect(chart.cols.find((c) => c.h === 18).n).toBe(1);
    expect(chart.cols.some((c) => c.h === 0)).toBe(false);
    expect(chart.label).toBe("시간대별 불만 리뷰: 18시 1건");
    // 11/21 QA B-2: 일부만 빠졌으면 뺀 건수를 한 줄로
    expect(chart).toMatchObject({ total: 3, pasted: 2, timed: 1 });
    expect(hourNotes(chart)).toEqual({ empty: "", extra: "붙여넣은 불만 2건은 주문 시각이 없어 시간대에서 뺐어요." });
  });
});

describe("11/21 QA: 시간 차트 빈 안내 (B-2)", () => {
  it("불만이 정말 0건일 때만 '불만 리뷰가 없어요', 붙여넣은 불만만 있으면 시각이 없어 그리지 않는다고", () => {
    const none = hourChart({ counts: { complaint_count: 0 }, groups: [], single_complaints: [], pasted: [] });
    expect(hourNotes(none)).toEqual({ empty: "불만 리뷰가 없어요.", extra: "" });
    const onlyPasted = hourChart({ counts: { review_count: 4, complaint_count: 4 }, pasted: [{ review_id: "p1" }, { review_id: "p2" }],
      groups: [{ issue_id: "g", topic_name: "맛", reviews: [{ review_id: "p1", created_at: "2026-11-21T00:03:00+09:00", input_method: "paste" }] }],
      single_complaints: [{ review_id: "p2", topic_names: ["양"], created_at: "2026-11-21T00:04:00+09:00" }] });
    expect(onlyPasted.cols.every((c) => !c.n)).toBe(true);
    expect(hourNotes(onlyPasted)).toEqual({ empty: "붙여넣은 리뷰에는 주문 시각이 없어 시간대를 그리지 않아요.", extra: "" });
    // 브리핑에 불만 수만 있고 리뷰 시각이 없을 때도 '없어요'라고 하지 않는다
    expect(hourNotes(hourChart({ counts: { complaint_count: 2 }, groups: [], single_complaints: [] })).empty)
      .toBe("주문 시각을 아는 불만 리뷰가 없어 시간대를 그리지 않아요.");
    expect(hourNotes(hourChart(briefing))).toEqual({ empty: "", extra: "" });   // 합성 리뷰만: 덧붙이는 줄 없음
    expect(hourNotes(null)).toEqual({ empty: "", extra: "" });
  });
});

describe("11/21 QA: 추천 카드 머리 설명 (B-7)", () => {
  const withSnap = { card: { kind: "promo" }, evidence: [{ type: "snapshot" }] };
  const reviewsOnly = { card: { kind: "complaint" }, evidence: [{ type: "review", id: "r1" }] };
  it("상권 지표를 쓴 카드가 있을 때만 '상권 자료', 시험용 실행은 AI 가 쓴다고 하지 않음", () => {
    expect(cardsIntro([reviewsOnly, withSnap], false)).toBe("오늘 리뷰와 상권 자료로 고른 추천 2가지예요. 고르면 AI가 글을 써요.");
    expect(cardsIntro([reviewsOnly], false)).toBe("오늘 리뷰로 고른 추천 1가지예요. 고르면 AI가 글을 써요.");
    expect(cardsIntro([reviewsOnly], true)).toBe("오늘 리뷰로 고른 추천 1가지예요. 고르면 예시 글을 보여 드려요.");
    expect(cardsIntro([], false)).toBe("");
  });
});

describe("11/21 QA: 처리 완료의 승인한 글 = 브라우저 목록 ∪ 서버 기록 (B-1)", () => {
  const local = [{ id: "d2", name: "포장·주문 안내문", at: "2026-11-21T21:00:05+09:00", edited: true, text: "안내문 고침" }];
  it("새로 고침 뒤(브라우저 목록이 빔) 서버 기록으로 채우고, 이름은 draft_id 로 추정", () => {
    const out = mergeApprovals([], [
      { draft_id: "d_1a2b3c4d", status: "approved", edited: false, text: "답글", approved_at: "2026-11-21T20:00:00+09:00", mode: "live" },
      { draft_id: "mkt-abc", status: "approved", edited: true, text: "홍보", approved_at: "2026-11-21T20:05:00+09:00" },
    ]);
    expect(out.map((a) => [a.id, a.name, a.edited, a.text, !!a.mkt])).toEqual([
      ["d_1a2b3c4d", "글", false, "답글", false], ["mkt-abc", "맞춤 마케팅 글", true, "홍보", true]]);
    expect(serverName("mkt-x")).toBe("맞춤 마케팅 글");
    expect(serverName("d_ex_unfair01_001")).toBe("글");
  });
  it("같은 글은 한 번만 (브라우저 쪽 이름), 차례는 서버, 서버에 없는 브라우저 글은 뒤에, 서버를 못 읽으면 브라우저 목록만", () => {
    const items = [{ draft_id: "d0", approved_at: "2026-11-20T10:00:00+09:00", text: "어제 답글" }, { draft_id: "d2", approved_at: "2026-11-21T21:00:05+09:00", edited: true, text: "안내문 고침" },
      { draft_id: "d2", approved_at: "2026-11-21T21:00:05+09:00" }];
    const extra = { id: "d3", name: "답글", at: "2026-11-21T21:01:00+09:00", text: "답글 하나" };
    expect(mergeApprovals([...local, extra], items).map((a) => [a.id, a.name])).toEqual([["d0", "글"], ["d2", "포장·주문 안내문"], ["d3", "답글"]]);
    expect(mergeApprovals(local, null)).toEqual(local);
    expect(mergeApprovals(local, false)).toEqual(local);
    expect(mergeApprovals([], [])).toEqual([]);
  });
  it("11/22: 서버가 준 글 종류(kind)·카드(card_id)로 이름을 낸다 (안내문은 카드 제목을 보고, 맞춤 마케팅은 종류 이름 그대로)", () => {
    const cards = [{ title: "식감 불만 → 안내문 + 답글", card: { card_id: "card_a" } }];
    expect(serverName({ draft_id: "d_1", kind: "reply_draft", card_id: "card_a" }, cards)).toBe("답글");
    expect(serverName({ draft_id: "d_2", kind: "prevention_notice", card_id: "card_a" }, cards)).toBe("안내문");
    expect(serverName({ draft_id: "d_2", kind: "prevention_notice", card_id: "card_gone" }, cards)).toBe("포장·주문 안내문");
    expect(serverName({ draft_id: "d_3", kind: "coupon_promo", card_id: "card_b" })).toBe("쿠폰 홍보글");
    expect(serverName({ draft_id: "mkt-1", kind: "쿠폰 글", card_id: "marketing" })).toBe("쿠폰 글");
    expect(serverName({ draft_id: "mkt-2", kind: null, card_id: "marketing" })).toBe("맞춤 마케팅 글");
    expect(serverName({ draft_id: "d_4", kind: null, card_id: null })).toBe("글");
    const out = mergeApprovals([], [{ draft_id: "d_2", kind: "prevention_notice", card_id: "card_a", text: "안내문" },
      { draft_id: "x-9", kind: "공지", card_id: "marketing", text: "공지" }], cards);
    expect(out.map((a) => [a.name, a.card, a.mkt])).toEqual([["안내문", "식감 불만 → 안내문 + 답글", false], ["공지", "맞춤 마케팅", true]]);
  });
  it("11/22: 진행이 없는 카드의 서버 승인 글 (안내·replaces)", () => {
    const today = new Date(2026, 10, 22, 15, 0), at = "2026-11-22T09:00:00+09:00";
    const items = [{ draft_id: "dx1", card_id: "card_a", status: "approved", approved_at: at }, { draft_id: "dx2", card_id: "card_a", approved_at: at },
      { draft_id: "dx1", card_id: "card_a", approved_at: at }, { draft_id: "dx3", card_id: "card_b", status: "rejected", approved_at: at },
      { draft_id: "mkt-1", card_id: "marketing", approved_at: at },
      { draft_id: "d_yesterday", card_id: "card_a", status: "approved", approved_at: "2026-11-21T21:00:00+09:00" }, { draft_id: "d_no_time", card_id: "card_a" }];
    expect(priorApprovals(items, "card_a", today)).toEqual(["dx1", "dx2"]);   // 지난날 승인·시각 없는 기록은 이력이라 세지 않는다 (replaces 로 지우지 않음)
    expect(priorApprovals(items, "card_b", today)).toEqual([]);
    expect(priorApprovals(null, "card_a", today)).toEqual([]);
    const cards = [{ card: { card_id: "card_a" } }, { card: { card_id: "card_b" } }];
    expect(priorByCard(cards, {}, items, today)).toEqual({ card_a: 2 });
    expect(priorByCard(cards, { card_a: { drafts: [] } }, items, today)).toEqual({});   // 이 브라우저에 진행이 있으면 세지 않음
    expect(priorByCard(cards, {}, items, new Date(2026, 10, 23, 9, 0))).toEqual({});     // 다음 날이면 안내도 replaces 도 없다
    expect(priorNote(2)).toBe("오늘 승인한 글 2개가 있어요. 새로 만들면 그 승인 기록은 새 글로 바뀌어요.");
  });
  it("승인 시각: 오늘이면 시:분, 다른 날이면 월-일 시:분", () => {
    const today = new Date(2026, 10, 21, 22, 0);
    expect(whenText("2026-11-21T21:00:05+09:00", today)).toBe("21:00");
    expect(whenText("2026-11-19T09:30:00+09:00", today)).toBe("11-19 09:30");
    expect(whenText("", today)).toBe("");
  });
});
