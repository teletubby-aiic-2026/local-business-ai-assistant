// 여러 화면이 같이 쓰는 이름·계산 (예전 app.js 맨 위와 '홈 상권 지표' 부분을 옮김)

export const GEN_NAMES = { reply_draft: "답글", prevention_notice: "포장·주문 안내문", coupon_promo: "쿠폰 홍보글" };
export const KIND_NAMES = { complaint: "불만 대응", promo: "쿠폰 홍보" };
// AI 비서: 오늘·분석 = 데이터 분석 비서, 카드 ⓐ·초안 = 고객 응대 비서, 카드 ⓑ = 마케팅 비서
export const KIND_AGENT = { complaint: "고객 응대 비서", promo: "마케팅 비서" };
// 포장·주문 안내문을 답글보다 먼저 (다시 안 생기게 하는 조치가 먼저)
export const GEN_ORDER = { prevention_notice: 0, coupon_promo: 1, reply_draft: 2 };
export const byGen = (a, b) => (GEN_ORDER[a.generator] ?? 9) - (GEN_ORDER[b.generator] ?? 9);
export const SOURCE_NAMES = { live: "실시간 HCX-005", seed: "시험용 저장 예시 (실제 AI 결과 아님)" };

// 출처 문자열에서 URL 을 떼어 화면에는 이름만 (URL 은 링크로)
export const sourceUrl = (s) => (String(s || "").match(/https?:\/\/\S+/) || [""])[0];
export const shortBasis = (t) => String(t || "").replace(/\s·\s*https?:\/\/\S+/g, "");

// 한 카드의 만든 글 (안내문 → 홍보글 → 답글 순서)
export const draftsOf = (results, cardId) => [...((results[cardId] || {}).drafts || [])].sort(byGen);
export const allDrafts = (results) => Object.values(results).flatMap((r) => r.drafts || []);

// 홈 '상권 저녁 매출' 칸의 지표: 값이 있고 개발용 가짜가 아닌 첫 지표
export const homeSnap = (b) => (b?.snapshots || []).find((x) => x.value !== null && !x.dev_fake) || null;
export const snapValue = (s) => `${s.value > 0 ? "+" : ""}${Number(s.value).toFixed(2)}${s.unit || ""}`;
// 상권 지표의 범위(업종·시간대)를 지표 이름에서 읽는다. ' · ' 뒤가 업종 범위다
export function marketScope(s) {
  const name = String(s?.metric_name || "");
  const hours = (name.match(/([0-9]{1,2}~[0-9]{1,2}시)/) || [])[1] || "";
  const tail = name.includes(" · ") ? name.split(" · ").pop().replace(/^두 분기\s*/, "").trim() : "";
  return [tail, hours].filter(Boolean).join(" ");
}
export const SCOPE_NOT_ONE = "한 업종(예: 한식음식점)의 하루 전체 매출이 아니에요.";
export const scopeNote = (s) => String(s?.metric_name || "").includes("공통 업종") ? SCOPE_NOT_ONE : "하루 전체 매출이 아니라 그 시간대의 매출이에요.";

// 오늘의 핵심 문제 한 줄 (카드 ⓐ가 가리키는 묶음)
export function heroProblem(b) {
  const top = (b?.groups || []).find((g) => g.issue_id === b.top_issue_id);
  return top
    ? `${top.topic_name} ${top.review_count}건${top.is_repeated ? " 반복" : ""}${top.main_time_band ? ` · ${top.main_time_band}에 몰림` : ""}`
    : "오늘은 반복되는 불만이 없어요";
}

// 카드 ⓑ 의 칭찬 근거: 보여 줄 리뷰(최대 3건), 쿠폰 메뉴, 그 메뉴를 언급한 칭찬 리뷰 수
export function praiseOf(p) {
  const shown = (p.evidence || []).filter((e) => e.type === "praise");
  return { shown, menu: shown.length ? shown[0].menu : "", total: Math.max(shown.length, (p.card.review_ids || []).length) };
}

// 가게 이름 한 줄 (상단 바)
export function storeLine(b) {
  if (!b?.store) return { name: "", sub: "" };
  return { name: b.store.name || "", sub: [b.store.business_type_name, b.store.area_name ? b.store.area_name + " 상권" : ""].filter(Boolean).join(" · ") };
}

// 맨 위 알림 띠에 띄울 서버 상태 문제 (예전 renderHealth)
export function healthProblems(h) {
  if (!h) return "";
  const problems = [...(h.blocking || [])];
  if ((h.dev_fake_snapshots || []).length) problems.unshift(`개발용 가짜 지표가 화면에 있어요 (${h.dev_fake_snapshots.join(", ")}). 실제 값이 아니니 발표에 쓰지 마세요.`);
  if (h.review_service && h.review_service.status === "down") problems.push(`리뷰 분석 서비스(${h.review_service.url})가 꺼져 있어요.`);
  return problems.join(" ");
}
// 상단 안내 띠 (시험용 실행일 때만). 서버의 health.mode_notice 가 있을 때 띄우고, 글은 핵심만 짧게.
// 이 띠가 '실제 AI 결과가 아님'을 알리는 화면 공통의 한 곳이다 (바닥 줄에서 다시 말하지 않음)
export const MODE_BAND_MOCK = "시험용 예시 화면 · 실제 AI 생성 결과가 아니에요";
export const modeBandText = (h) => (h?.mode_notice ? MODE_BAND_MOCK : "");

// 바닥 줄 (자료 출처·AI 생성 여부). 리뷰가 합성 데이터인지는 늘, AI 가 실시간으로 쓰는지는 시험용 띠가 없을 때만 적는다.
// 분류 방식·규칙·모델 분담 같은 안쪽 사정은 적지 않는다
export function honestyItems(h) {
  if (!h) return [];
  const p = h.parts || {};
  const items = [`리뷰: ${p.reviews || "합성 데이터"}`];
  if (!h.mode_notice && p.generate) items.push(`글 생성: ${p.generate}`);
  return items;
}
