// 맞춤 마케팅의 이름표와 순수 계산 (예전 app.js 의 MKT_* 상수, mktBadge·mktTiles·mktCouponHtml 의 범위 계산·mktReportDraw 의 숫자).
// 판정·숫자는 서버가 준 값만 보고 가른다. 화면은 계산을 새로 하지 않는다 (슬라이더 범위·막대 길이만).

export const MKT_DEMO = "시험용 저장 예시 (실제 AI 결과 아님)";
// 시작 모드 다섯 개: 서버(flow.py START_MODES)가 주는 보기 글자 → 한 줄 설명. 보기 자체는 서버가 준 것만 그린다
export const MKT_MODES = {
  "맞춤 홍보 제안": "반복 불만·목표·예산을 여쭤보고 홍보 방법과 글을 제안해요",
  "남은 재료 팔기": "오늘 남은 메뉴를 세트·할인·추천 글로 팔아요",
  "광고비 점검": "배달앱 광고비가 주문 한 건에서 남는 돈보다 큰지 계산해요",
  "가게 이야기 글": "사장님 답만으로 플레이스·인스타·배민 소개 글을 써요",
  "쿠폰 결과 확인": "지난 쿠폰의 사용률과 다음 쿠폰 조건을 알려 드려요",
};
// 다른 화면의 navTo("marketing", sub) → 시작 모드 보기 글자 (assistant_proxy.MKT_SUBS 와 같아야 함)
export const MKT_SUB = { promo: "맞춤 홍보 제안", leftover: "남은 재료 팔기", ad: "광고비 점검", story: "가게 이야기 글", repeat: "쿠폰 결과 확인" };
// 숫자 입력칸의 단위 (서버 free_input.key → 화면 표시만)
export const MKT_UNIT = { leftover_portions: "인분", _adspend_spend_entry: "원", _adspend_orders_entry: "건", adspend_avg_amount_won: "원",
  coupon_issued: "장", coupon_used: "장", coupon_discount_won: "원", coupon_avg_order_won: "원", survey_avg_order_won: "원" };
export const MKT_VERDICT = { "손해 광고": ["bad", "손해 광고"], "주의": ["warn", "주의"], "괜찮음": ["ok", "괜찮음"] };
// 글 만드는 생성기 → 승인 기록에 남기는 글 종류 (서버 server.py 의 _GENERATOR_KINDS 와 같은 이름, marketing_proxy.KINDS 안에서만)
export const MKT_KIND = { prevention_notice: "공지", late_notice_template: "공지", reply_draft: "답글", review_promo: "홍보 글", coupon_promo: "쿠폰 글" };
export const MKT_MODE_KIND = { leftover: "남은 재료 글", story: "가게 이야기 글" };
export const MKT_PERIOD = {
  weekly: { name: "주간", now: "이번 주", prev: "지난주", next: "다음 주" },
  monthly: { name: "월간", now: "이번 달", prev: "지난달", next: "다음 달" },
};
export const MKT_STATES = {
  off: "맞춤 마케팅을 쓸 수 없어요", down: "지금은 맞춤 마케팅에 연결할 수 없어요", error: "맞춤 마케팅을 불러오지 못했어요",
};

export const wonKo = (n) => `${Number(n || 0).toLocaleString("ko-KR")}원`;
export const round100 = (v) => Math.round(v / 100) * 100;
export const mktKey = (k) => String(k).replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 40);

// 서비스 상태 → 안내 열쇠 (예전 mktDown: 모르는 상태는 error, 시간 초과는 down)
export const downKey = (st) => (MKT_STATES[st] ? st : st === "timeout" ? "down" : "error");

// 판정 배지 [tone, 글자]: 서버가 준 판정(verdict·usage_rate·strategy_type)만 보고 가른다 (원본 badgeFor)
export function badgeOf(d) {
  if (Array.isArray(d.table)) {
    const rank = { "괜찮음": 0, "주의": 1, "손해 광고": 2 };
    const judged = d.table.filter((r) => r.verdict);
    return judged.length ? MKT_VERDICT[judged.reduce((a, b) => (rank[b.verdict] > rank[a.verdict] ? b : a)).verdict] || null : null;
  }
  if (d.strategy_type === "fix_first") return ["bad", "먼저 고치기"];
  if (d.usage_rate !== undefined) {
    const r = d.usage_rate;
    return r == null ? ["bad", "점검 필요"] : r < 0.2 ? ["warn", "주의"] : r <= 0.5 ? ["ok", "같은 조건 유지"] : ["warn", "할인 큼"];
  }
  return ["", "정보"];
}

// 숫자 타일 [값, 이름] (원본 buildTiles)
export function tilesOf(d) {
  if (Array.isArray(d.table)) {
    const flagged = d.table.filter((r) => r.verdict && r.verdict !== "괜찮음");
    return [[`${d.table.length}개`, "점검한 채널"], [`${flagged.length}개`, "주의·손해 채널"],
      ...(d.profit_per_order_won != null ? [[wonKo(d.profit_per_order_won), "건당 이익(추정)"]] : [])];
  }
  if (d.usage_rate !== undefined) {
    const t = [];
    if (d.usage_rate != null) t.push([`${Math.round(d.usage_rate * 100)}%`, "쿠폰 사용률"]);
    if (d.issued != null && d.used != null) t.push([`${d.issued}장 / ${d.used}장`, "발급 / 사용"]);
    if (d.total_discount_cost_won != null) t.push([wonKo(d.total_discount_cost_won), "총 할인 비용"]);
    if (d.breakeven_orders != null) t.push([`${d.breakeven_orders}건`, "본전 주문 수"]);
    return t;
  }
  if (d.coupon_card) {
    const c = d.coupon_card, t = [[wonKo(c.discount_won), "할인액"]];
    if (c.count) t.push([`${c.count}장`, "발급 수량"]);
    if (c.breakeven_orders != null) t.push([`${c.breakeven_orders}건`, "본전 주문 수"]);
    return t;
  }
  return [];
}

// '왜 이렇게 판단했나요' 줄: result 의 설명 3줄 → plan 의 summary → 할 일이 하나면 그 tip
export function whyLinesOf(d, why) {
  const steps = Array.isArray(d.steps) ? d.steps : [];
  return (Array.isArray(why?.explain) && why.explain.length ? why.explain
    : d.summary ? [d.summary] : steps.length === 1 && steps[0].tip ? [steps[0].tip] : []).filter((t) => typeof t === "string" && t);
}

export const stepKind = (s, mode) => MKT_KIND[s.generator] || MKT_MODE_KIND[mode] || "마케팅 글";
export const draftLabel = (kind, demo, fixed = false) => (demo ? `${kind} · ${MKT_DEMO}` : fixed ? `${kind} · 정해 둔 틀 (AI 아님)` : `${kind} 초안`);

export function todoHeadOf(d) {
  const steps = Array.isArray(d.steps) ? d.steps : [];
  return steps.length ? `이번 주 할 일 ${steps.length}개 · 약 ${d.total_minutes ?? 0}분${d.total_cost_krw ? ` · 추정 비용 ${wonKo(d.total_cost_krw)}` : ""}` : "";
}

// 쿠폰 카드의 줄 [이름, 값] ('-'·빈 값은 뺌)
export const couponRows = (c) => [["혜택", `${wonKo(c.discount_won)} 할인`], ["발급 수량", c.count ? `${c.count}장` : null], ["시간대", c.timing || null],
  ["유효기간", c.days ? `발급일 포함 ${c.days}일` : null]].filter(([, v]) => v != null && v !== "-");

// 쿠폰 슬라이더 범위: 할인액은 메뉴 가격의 5~30% (100원 단위, 최소 100원), 예산은 0~30만 원
export const CALC_MAX_BUDGET = 300000;
export function calcRange(input) {
  const price = Number(input.price_won) || 0;
  const minD = Math.max(100, round100(price * 0.05)), maxD = Math.max(minD, round100(price * 0.3));
  const startD = Math.min(Math.max(Number(input.discount_won) || 0, minD), maxD);
  return { minD, maxD, startD, budget: Math.min(Number(input.budget_won) || 0, CALC_MAX_BUDGET) };
}

// 같은 눈금의 막대 길이(0~100%): 가장 큰 값이 100
export function barPct(values) {
  const scale = Math.max(1, ...values.map((v) => Number(v) || 0));
  return (v) => Math.max(0, Math.min(100, Math.round(((Number(v) || 0) / scale) * 100)));
}

// 처음 그릴 때의 글 상자: 할 일마다의 글(drafts[step_id]) → 기본 할 일 글 (승인할 때 이 순서로 보낸다)
export function initialDrafts(d, mode, demo) {
  const drafts = {}, order = [], texts = d.drafts || {};
  const add = (key, text, kind, label) => { drafts[key] = { kind, label, original: String(text ?? ""), text: String(text ?? ""), failed: null }; order.push(key); };
  (Array.isArray(d.steps) ? d.steps : []).forEach((s) => {
    if (!texts[s.step_id]) return;
    const kind = stepKind(s, mode);
    add(s.step_id, texts[s.step_id], kind, draftLabel(kind, demo, s.generator === "late_notice_template"));
  });
  (Array.isArray(d.basic_todos) ? d.basic_todos : []).forEach((t, i) => {
    if (t.draft) add(`basic_todo_${i}`, t.draft, "기본 할 일 글", draftLabel("기본 할 일 글", demo));
  });
  return { drafts, order };
}

// 마케팅 보고서의 숫자 (예전 mktReportDraw). 보고서는 기록을 코드로 센 것이다 (AI 호출 없음)
export function reportView(d, period) {
  const L = MKT_PERIOD[d.period?.kind] || MKT_PERIOD[period] || MKT_PERIOD.weekly;
  const tiles = [];
  const approved = Object.entries(d.activity?.approved || {});
  if (approved.length) tiles.push([`${approved.reduce((n, [, v]) => n + Number(v || 0), 0)}건`, `승인한 글 (${approved.map(([k, v]) => `${k} ${v}`).join(" · ")})`]);
  const c = d.cost?.coupon;
  if (c) {
    if (c.usage_rate != null) tiles.push([`${Math.round(c.usage_rate * 100)}%`, `쿠폰 사용률 (${c.issued}장 중 ${c.used}장)`]);
    tiles.push([wonKo(c.discount_spent), "할인에 쓴 돈"]);
  }
  (d.fixed || []).forEach((f) => tiles.push([`${f.before_14d}건 → ${f.after_14d}건`, f.tile_label || `${f.complaint} 불만 재발`]));
  const tried = d.activity?.ideas_tried || [], ads = d.cost?.ads || [], next = d.next || [];
  const pct = barPct(ads.flatMap((a) => [a.cost_per_order, a.profit_per_order]));
  const until = String(d.period?.until || "").slice(0, 10);
  return { L, tiles, tried, ads, next, pct, start: d.period?.start || "", until, empty: !tiles.length && !tried.length && !ads.length && !next.length };
}

// 진행 안내 열쇠 '질문 n': 서버가 전체 질문 수를 주지 않아서 지금까지 나온 질문 수만 센다
export const progressLabel = (n) => (n > 0 ? `질문 ${n}` : "");
