// 상권 분석 화면의 숫자·글 표기 (예전 app.js 의 qLabel·wonShort·numKo·pctKo·mkvBars 계산·chatUrl).
// 서버 숫자는 원 단위 그대로를 '억·만'으로만 줄여 보인다 (반올림 표기). 사람이 읽는 칸은 손대지 않는다.

// 분기: 코드('20262') 또는 상권 서비스의 {code, label} 둘 다 받는다
export const qLabel = (p) => p && typeof p === "object" ? (p.label || qLabel(p.code))
  : /^[0-9]{4}[1-4]$/.test(String(p || "")) ? `${String(p).slice(0, 4)}년 ${String(p)[4]}분기` : String(p || "");

// '원' 앞은 줄바꿈 없는 띄어쓰기(U+00A0): 좁은 지표 칸에서 '원'만 혼자 다음 줄로 꺾이지 않게 ('117억' / '7,727만 원'으로 꺾임)
const NB = "\u00a0";
export function wonShort(n) {
  if (typeof n !== "number" || !isFinite(n)) return "–";
  const sign = n < 0 ? "-" : "", v = Math.abs(n);
  if (v >= 1e8) { const man = Math.round((v % 1e8) / 1e4); return `${sign}${Math.floor(v / 1e8).toLocaleString("ko-KR")}억${man ? ` ${man.toLocaleString("ko-KR")}만` : ""}${NB}원`; }
  if (v >= 1e4) return `${sign}${Math.round(v / 1e4).toLocaleString("ko-KR")}만${NB}원`;
  return `${sign}${v.toLocaleString("ko-KR")}원`;
}

export const numKo = (n, unit = "") => typeof n === "number" ? `${n.toLocaleString("ko-KR")}${unit}` : "–";
export const pctKo = (p) => typeof p === "number" ? `${p > 0 ? "+" : ""}${p.toFixed(2)}%` : "–";

// 지표 하나의 값: 단위가 원이면 억·만, 아니면 단위를 붙인 숫자
export const metricValue = (m, x) => x && typeof x.value === "number" ? (m.unit === "원" ? wonShort(x.value) : numKo(x.value, m.unit || "")) : "–";

// 분포 막대. 비중을 주지 않는 자료(예: 연령별 유동인구 원천 지표)는 값의 합으로 나눠 막대 길이만 맞춘다 (보이는 숫자는 원래 값)
export function barRows(dist) {
  const items = (dist && dist.items) || [];
  const total = items.reduce((s, i) => s + (typeof i.value === "number" ? i.value : 0), 0);
  return items.map((i) => {
    const share = typeof i.share_percent === "number" ? i.share_percent : total > 0 && typeof i.value === "number" ? (i.value / total) * 100 : null;
    return {
      label: String(i.label).replace(/\s*\(원천 분류\)/, ""),
      pct: share === null ? 0 : Math.max(0, Math.min(100, share)),
      shown: typeof i.share_percent === "number" ? `${i.share_percent.toFixed(2)}%` : typeof i.value === "number" ? numKo(i.value) : "–",
    };
  });
}

// 경고 글: 문자열만
export const warningsOf = (x) => ((x && x.warnings) || []).filter((w) => typeof w === "string");

// 행사 링크는 http(s) 만 연다
export const safeUrl = (v) => { try { const u = new URL(String(v)); return u.protocol === "https:" || u.protocol === "http:" ? u.href : null; } catch { return null; } };

// 서버 시각 '2026-11-18T21:09:00+09:00' → '2026-11-18 21:09'
export const shortTime = (t) => String(t).slice(0, 16).replace("T", " ");

// 적재된 자료 상태 한 줄 (예전 mkvDataStatus)
export function dataStatusText(d) {
  if (!d) return "적재된 자료 상태를 불러오지 못했어요.";
  const parts = [d.message || ""];
  if (d.verified_files != null) parts.push(`검증한 원본 파일 ${numKo(d.verified_files, "개")}`);
  parts.push(d.last_synced_at ? `마지막 서울시 확인 ${shortTime(d.last_synced_at)}` : "서울시 확인 기록 없음");
  return parts.filter(Boolean).join(" · ");
}

// 동기화 결과 한 줄 (예전 mkvSync)
export function syncText(r) {
  const totals = Object.entries(r.totals || {}).map(([k, v]) => `${({ sales: "추정매출", stores: "점포", population: "유동인구" })[k] || k} ${numKo(v, "건")}`).join(", ");
  return [r.message, r.checked_at ? `확인 시각 ${shortTime(r.checked_at)}` : "", totals ? `서울시 총 건수: ${totals}` : "",
    r.sample_only ? (r.notice || "서울시 공개 샘플(1~5건)로만 확인했어요.") : "", r.apply_hint || ""].filter(Boolean).join(" · ");
}

// 분석 조건 한 줄 (예전 mk-cond-text)
export const condText = (c) => `${c.area_name || ""} · ${c.industry_name || ""} · ${c.period_label || qLabel(c.period)}${c.home ? " · 우리 가게 기준" : ""}`;

// 쿼리 붙이기: 빈 조각은 뺀다
export const withQuery = (path, ...parts) => { const q = parts.filter(Boolean); return q.length ? `${path}?${q.join("&")}` : path; };
