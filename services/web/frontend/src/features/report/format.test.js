import { describe, expect, it } from "vitest";
import {
  approvalLine, changeText, clockView, clocksOf, dateKo, fixEmpty, fixItems, fixTitle, marketingNumbers, menuTitle, peakText, periodText, printMeta, remadeDiff, remadeText, rpClock,
  savedNote, scoreReasons, signed, stamp, tilesOf, topicRows, trendGeometry,
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
    // 11/22 QA R3: 점수 변화 0은 맨숫자 대신 '변화 없음'
    expect(changeText(0)).toBe("변화 없음");
    expect(changeText(3)).toBe("+3");
    expect(changeText(-2)).toBe("-2");
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
    // 11/21: 끝난 기간이면 '없었어요', 진행 중이면 '아직 없어요' (실시간 확인 14)
    expect(tilesOf(view({ report: { review_count: 0, previous: { review_count: 0 } } }))[0].sub).toBe("들어온 리뷰가 없었어요");
    expect(tilesOf(view({ period: { in_progress: true }, report: { review_count: 0, previous: { review_count: 0 } } }))[0].sub).toBe("아직 리뷰가 없어요");
    expect(tilesOf(view({ report: { review_count: 0, previous: { review_count: 4 } } }))[0].sub).toBe("지난주보다 -4");
    // 11/22 QA R3: 점수가 그대로면 '시작 98점 · 0' 대신 '변화 없음'
    expect(tilesOf(view({ report: { review_count: 3, score_start: 98, score_end: 98, score_change: 0 } }))[2].sub).toBe("시작 98점 · 변화 없음");
  });
  it("승인한 글 나눔: 안내문·그 밖은 있을 때만", () => {
    expect(approvalLine({ reply: 5, promo: 2, notice: 0, other: 0 })).toBe("답글 5 · 홍보 2");
    expect(approvalLine({ reply: 1, promo: 0, notice: 2, other: 1 })).toBe("답글 1 · 홍보 0 · 안내문 2 · 그 밖 1");
    expect(approvalLine(null)).toBe("");
  });
  it("마케팅 숫자: 없는 숫자를 지어내지 않고, 값이 없는 칸은 그리지 않고 맞춤 마케팅으로 안내 (11/22 QA R1)", () => {
    const now = marketingNumbers(view());
    expect(now.cells).toEqual([{ label: "승인한 홍보 글", value: "2개" }]);
    expect(now.elsewhere).toBe(true);
    const full = marketingNumbers(view({ marketing: { promo_approved: 1, coupon_usage_rate: 0.18, ad_cost_per_order: 1200, notice_recurrence: { before: 3, after: 1 } } }));
    expect(full.cells.map((x) => x.value)).toEqual(["1개", "18%", "1,200원", "3 → 1건"]);   // 값이 오면 그대로 보인다
    expect(full.elsewhere).toBe(false);
    expect(marketingNumbers(view({ marketing: { promo_approved: 0, coupon_usage_rate: 0, ad_cost_per_order: null } })).cells.map((x) => x.label))
      .toEqual(["승인한 홍보 글", "쿠폰 사용률"]);   // 0%도 값이다
    expect(marketingNumbers({})).toEqual({ cells: [{ label: "승인한 홍보 글", value: "–" }], elsewhere: true });
  });
  it("인기 메뉴 제목: 셋이면 'TOP 3', 1~2개·없음은 '인기 메뉴' (11/22 QA R4)", () => {
    expect(menuTitle([{}, {}, {}])).toBe("인기 메뉴 TOP 3");
    expect(menuTitle([{}, {}])).toBe("인기 메뉴");
    expect(menuTitle([])).toBe("인기 메뉴");
    expect(menuTitle(undefined)).toBe("인기 메뉴");
  });
  it("응대 점수 이유: 크게 깎인 것부터 3줄, 나머지는 rest, 0점 줄은 뺌 (11/22 QA R2)", () => {
    const reasons = [
      { key: "fixed:taste", delta: 3, message: "'맛' 답글 뒤 7일 동안 같은 불만 없음" },
      { key: "repeat:a", delta: -2, message: "'포장 누락' 불만이 3건 반복 중" },
      { key: "late:1", delta: -6, message: "'배달 시간' 불만 답글 기한을 40분 넘김" },
      { key: "repeat:b", delta: -2, message: "'배달 시간' 불만이 4건 반복 중" },
      { key: "zero", delta: 0, message: "x" },
    ];
    const { shown, rest } = scoreReasons(reasons);
    expect(shown.map((x) => x.key)).toEqual(["late:1", "repeat:a", "repeat:b"]);   // 같은 감점은 받은 차례 그대로
    expect(rest.map((x) => x.key)).toEqual(["fixed:taste"]);
    expect(scoreReasons(undefined)).toEqual({ shown: [], rest: [] });
    expect(scoreReasons(reasons, 2).rest).toHaveLength(2);
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

describe("고칠 것: 보는 기간에 맞는 말 (11/21 실시간 확인 13·14)", () => {
  const live = { in_progress: true }, past = { in_progress: false };
  it("제목: 진행 중이면 '이번 주·이번 달에 고칠 것', 끝난 기간이면 '이 주·이 달 기록에서 고칠 것'", () => {
    expect(fixTitle(view({ period: live }))).toBe("이번 주에 고칠 것");
    expect(fixTitle(view({ period: past }))).toBe("이 주 기록에서 고칠 것");
    expect(fixTitle(view({ kind: "monthly", period: live }))).toBe("이번 달에 고칠 것");
    expect(fixTitle(view({ kind: "monthly", period: past }))).toBe("이 달 기록에서 고칠 것");
    expect(fixTitle(view({ period: {} }))).toBe("이번 주에 고칠 것");   // 모르면 진행 중으로
  });
  it("리뷰 0건: 고칠 것은 빈 목록, 빈 칸 한 줄은 끝난 기간이면 '아직' 없이 (11/22 QA R5)", () => {
    const zero = (over, suggestions = []) => view({ ...over, report: { review_count: 0, suggestions } });
    expect(fixItems(zero({ period: live }))).toEqual([]);
    expect(fixEmpty(zero({ period: live }))).toBe("이번 주에는 아직 리뷰가 없어 고칠 것을 고르지 않았어요.");
    expect(fixEmpty(zero({ period: past }))).toBe("이 주에는 리뷰가 없어 고칠 것을 고르지 않았어요.");
    expect(fixEmpty(zero({ kind: "monthly", period: live }))).toBe("이번 달에는 아직 리뷰가 없어 고칠 것을 고르지 않았어요.");
    expect(fixEmpty(zero({ kind: "monthly", period: past }))).toBe("이 달에는 리뷰가 없어 고칠 것을 고르지 않았어요.");
    // 서버를 고치기 전에 저장된 보고서: 리뷰 0건인데 기간 밖 반복 불만·'empty'·'크게 고칠 응대가 없어요'가 들어 있어도 보이지 않는다
    const old = [{ kind: "no_reply", title: "'포장 누락' 불만 3건에 아직 답글이 없어요", evidence: "이번 주 0건 · 전체 3건", text: "답글로 조치를 알리고, 매장에서 확인해 보세요" },
      { kind: "empty", title: "이번 주에 들어온 리뷰가 아직 없어요", evidence: "리뷰 0건", text: "" }];
    expect(fixItems(zero({ period: live }, old))).toEqual([]);
    expect(fixItems(zero({ kind: "monthly", period: past }, [{ text: "'포장 누락' 불만 3건에 아직 답글이 없어요." }]))).toEqual([]);
    // 리뷰가 있는데 빈 목록이면 예전 한 줄
    expect(fixEmpty(view({ report: { review_count: 3, suggestions: [] } }))).toBe("제안이 없어요.");
  });
  it("끝난 기간의 문장은 '이번 주·이번 달'을 '이 주·이 달'로 (숫자·근거는 그대로)", () => {
    const sugg = [{ kind: "no_reply", title: "'포장 상태' 불만 3건에 아직 답글이 없어요", evidence: "이번 주 3건 · 전체 3건", text: "답글로 조치를 알리고, 매장에서 확인해 보세요" }];
    expect(fixItems(view({ period: past, report: { review_count: 6, suggestions: sugg } }))[0].evidence).toBe("이 주 3건 · 전체 3건");
    expect(fixItems(view({ period: live, report: { review_count: 6, suggestions: sugg } }))[0].evidence).toBe("이번 주 3건 · 전체 3건");
    expect(fixItems(view({ kind: "monthly", period: past, report: { review_count: 4, suggestions: [{ text: "이번 달은 크게 고칠 응대가 보이지 않아요. 지금 방식을 이어 가세요" }] } }))[0].text)
      .toBe("이 달은 크게 고칠 응대가 보이지 않아요. 지금 방식을 이어 가세요");
    expect(fixItems(view({ report: { review_count: 3 } }))).toEqual([]);
  });
});

describe("11/21 QA B-10: 다시 만든 뒤 무엇이 반영됐는지", () => {
  const live = { key: "2026-11-16", label: "11월 3주", range: "11/16 ~ 11/22", in_progress: true };
  it("전후 보고서를 견준다 (같은 기간일 때만)", () => {
    const before = view({ period: live });
    const after = view({ period: live, made_now: true, report: { review_count: 17 }, approvals: { total: 9 } });
    expect(remadeDiff(before, after)).toEqual({ reviews: 3, approvals: 2 });
    expect(remadeDiff(null, after)).toEqual({ reviews: null, approvals: null });
    expect(remadeDiff(view(), after)).toEqual({ reviews: null, approvals: null });   // 다른 기간
    expect(remadeDiff(before, view({ period: live, approvals: null }))).toEqual({ reviews: 0, approvals: null });
  });
  it("괄호 안 글: 바뀐 것만, 같으면 그대로라고, 견줄 수 없으면 빈 글", () => {
    expect(remadeText({ reviews: 3, approvals: 2 })).toBe("새 리뷰 3건 · 승인 2건 반영");
    expect(remadeText({ reviews: 0, approvals: 1 })).toBe("승인 1건 반영");
    expect(remadeText({ reviews: -1, approvals: 0 })).toBe("리뷰 1건 빠짐");
    expect(remadeText({ reviews: -1, approvals: 2 })).toBe("승인 2건 반영 · 리뷰 1건 빠짐");
    expect(remadeText({ reviews: 0, approvals: 0 })).toBe("리뷰·승인 수는 그대로");
    expect(remadeText({ reviews: null, approvals: null })).toBe("");
    expect(remadeText(null)).toBe("");
  });
  it("안내 띠: 다시 만들었으면 '다시 만들어 저장했어요 (…)', 견줄 수 없으면 기준 시각만, 게스트도 알림", () => {
    const made = view({ period: live, made_now: true, created_at: "2026-11-21T15:30:00+09:00" });
    expect(savedNote(made, { reviews: 3, approvals: 0 }).text)
      .toBe("11-21 15:30에 다시 만들어 저장했어요 (새 리뷰 3건 반영). 이번 주는 아직 진행 중이라, 새 리뷰가 들어오면 다시 만들어 주세요.");
    expect(savedNote(made, { reviews: null, approvals: null }).text)
      .toBe("11-21 15:30에 다시 만들어 저장했어요. 이번 주는 아직 진행 중이라, 새 리뷰가 들어오면 다시 만들어 주세요.");
    expect(savedNote(made).text).toBe("11-21 15:30에 만들어 저장했어요. 이번 주는 아직 진행 중이라, 새 리뷰가 들어오면 다시 만들어 주세요.");
    expect(savedNote({ ...made, storage: "guest" }, { reviews: 0, approvals: 0 }).text).toBe("다시 계산했어요 (리뷰·승인 수는 그대로). 로그인하면 만든 보고서가 이 계정에 저장돼요.");
    expect(savedNote({ ...made, storage: "guest" }).text).toBe("로그인하면 만든 보고서가 이 계정에 저장돼요.");
  });
});
