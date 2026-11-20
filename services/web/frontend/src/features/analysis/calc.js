// 리뷰 분석 화면의 이름표와 순수 계산 (예전 app.js 699~1022줄). 화면 그리기는 *.jsx
// 주제 id → 이름 (리뷰 분석 서비스의 주제 사전 app/topics.py 와 같은 이름. 모르는 id 는 그대로 보인다)
export const TOPIC_NAMES = { texture: "식감", taste: "맛", portion: "양", price: "가격", delivery_time: "배달 시간", temperature: "음식 온도",
  packaging: "포장 상태", missing_item: "포장 누락", service: "응대", hygiene: "위생", menu: "메뉴 구성", atmosphere: "매장 환경", wait_time: "매장 대기" };
export const SENTIMENT_NAMES = { positive: "긍정", negative: "부정", neutral: "중립", mixed: "긍정·부정 섞임" };
export const topicName = (t) => TOPIC_NAMES[t] || t;

export const AN_TABS = ["summary", "issues", "paste"];

export const PASTE_SAMPLES = [
  { text: "저녁 8시에 시켰는데 한 시간 넘게 걸렸고 국물도 다 식었어요", rating: 1 },
  { text: "맛은 정말 좋은데 포장이 허술해서 국물이 조금 샜어요", rating: 3 },
  { text: "점심에 먹었는데 반찬도 깔끔하고 사장님도 친절하세요!", rating: 5 },
  { text: "제육볶음 정식 고기를 불고기로 그냥 바꿔 달라고 했더니 안 된대요. 그것도 못 해 주나요? 별 하나 드립니다", rating: 1 },
];

// POST /api/reviews 의 channel 값 (docs/api/contract.md 1.8). 비우면 보내지 않는다 (예전 화면과 같은 본문)
export const CHANNELS = [["", "채널 모름"], ["baemin", "배달의민족"], ["coupangeats", "쿠팡이츠"], ["yogiyo", "요기요"], ["naver_place", "네이버 플레이스"]];
export const RATINGS = [["", "별점 모름"], ["5", "별점 5"], ["4", "별점 4"], ["3", "별점 3"], ["2", "별점 2"], ["1", "별점 1"]];

// 눈썹 줄 (예전 an-period)
export const periodLine = (d) => `${d.period_start} ~ ${d.period_end}${d.data_origin === "synthetic" ? " · 리뷰는 합성 데이터" : ""}`;

// 요약 타일 세 개 (예전 renderAnSummary). d 가 없으면 '–'
export function summaryTiles(d) {
  if (!d) return { reviews: "–", reviewsSub: "", complaints: "–", complaintsSub: "", repeated: "–", repeatedSub: "" };
  const days = Math.round((new Date(d.period_end) - new Date(d.period_start)) / 86400000) + 1;
  const s = d.sentiment_counts || {};
  const rep = (d.groups || []).filter((g) => g.is_repeated);
  return {
    reviews: d.review_count ?? "–",
    reviewsSub: `${Number.isFinite(days) ? days + "일 · " : ""}긍정 ${s.positive ?? 0} · 중립 ${s.neutral ?? 0}`,
    complaints: d.complaint_count ?? "–",
    complaintsSub: d.review_count ? `리뷰의 ${Math.round((d.complaint_count / d.review_count) * 100)}%` : "",
    repeated: rep.reduce((n, g) => n + g.review_count, 0),
    repeatedSub: rep.length ? `묶음 ${rep.length}개 · ${rep.map((g) => g.topic_name).join(", ")}` : "없음",
  };
}

// 칭찬·불만 키워드: 주제별 긍정(positive)·부정(negative) 수가 많은 8개. ratio 는 같은 칸 안 최댓값 대비
export function topTopics(d, pol) {
  const list = Object.entries(d?.topic_counts || {}).map(([t, v]) => [topicName(t), (v || {})[pol] || 0])
    .filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const max = Math.max(1, ...list.map(([, n]) => n));
  return list.map(([name, n]) => ({ name, n, ratio: n / max }));
}

// 묶음 카드의 한 줄과 시간대 막대 (예전 renderAnIssues)
export function groupNote(g) {
  const trend = Number.isFinite(g.previous_count) && Number.isFinite(g.recent_count) ? ` · 앞 2주 ${g.previous_count}건 → 최근 2주 ${g.recent_count}건` : "";
  return `${g.main_time_band ? `주로 ${g.main_time_band}` : "여러 시간대"}${trend}`;
}
export function bandRows(g) {
  const bands = Object.entries(g.time_bands || {});
  const max = Math.max(1, ...bands.map(([, n]) => n));
  return bands.map(([band, n]) => ({ band, n, pct: Math.round((n / max) * 100), hot: band === g.main_time_band }));
}

// 붙여넣기 결과: 들어간 묶음 이름과 안내 (예전 renderPasteResult)
export function pasteJoin(r, insightGroups) {
  const c = r.classification || {};
  const topics = c.topics || [];
  const groups = r.groups || insightGroups || [];
  const joined = (r.joined_issues || []).map((id) => groups.find((g) => g.issue_id === id)?.topic_name || id);
  const negative = topics.some((t) => t.polarity === "negative") || (c.negative_topics || []).length > 0;
  return { joined, negative };
}

// ── 캡처 ──
export const CAP_MAX_BYTES = 10 * 1024 * 1024;
export const CAP_TYPES = ["image/png", "image/jpeg", "image/webp"];

// 고른 파일 확인: 오류 문장 또는 "" (예전 capPick)
export function capCheck(file) {
  if (file.type && !CAP_TYPES.includes(file.type)) return "png·jpg·webp 이미지만 올릴 수 있어요.";
  if (file.size > CAP_MAX_BYTES) return "이미지는 10MB 이하로 올려 주세요.";
  return "";
}
export const capFileLabel = (file) => {
  const size = file.size >= 1048576 ? `${(file.size / 1048576).toFixed(1)}MB` : `${Math.max(1, Math.round(file.size / 1024))}KB`;
  return `${file.name || "캡처"} · ${size}`;
};

// 받은 후보를 화면 칸으로. 못 읽은 별점·범위 밖 별점은 null('별점 모름'), 이미 있는 리뷰는 처음에 고르지 않음 (예전 capRender·capItem)
export function capItems(r) {
  return (Array.isArray(r?.candidates) ? r.candidates : []).filter((c) => c && typeof c.text === "string").map((c) => {
    const rating = Number.isInteger(c.rating) && c.rating >= 1 && c.rating <= 5 ? c.rating : null;
    return { text: c.text, rating: rating === null ? "" : String(rating), ai: rating, pii: !!c.pii_masked, dup: !!c.duplicate,
      picked: !c.duplicate, saved: false, msg: "" };
  });
}
// 붙여넣은 리뷰의 분류 방식 → 화면 배지 (AI 생성 여부는 남기고, 내부 이름 model·replay·rule 은 보이지 않게)
export const METHOD_NAMES = { model: "AI 분류", replay: "저장된 AI 분류", rule: "규칙 분류 (AI 아님)", rules: "규칙 분류 (AI 아님)" };
export const methodName = (m) => METHOD_NAMES[String(m || "").trim()] || "";

export const capWarnings = (r) => (Array.isArray(r?.warnings) ? r.warnings : []).filter((w) => typeof w === "string" && w.trim());
export function capStatusLine(r, count) {
  const pieces = Number(r?.pieces) > 1 ? ` · ${Number(r.pieces)}조각으로 나눠 읽음` : "";
  return `후보 ${count}건${pieces} · ${r?.demo ? "예시 결과" : `읽은 모델 ${r?.engine || ""}`}`;   // 고치고 고르라는 안내는 후보 목록 위 확인 경고 한 곳에
}
export const capPickedOf = (items) => items.filter((x) => x.picked && !x.saved);
