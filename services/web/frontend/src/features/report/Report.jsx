// 종합 리포트 (#/report). 칸 여섯 개를 따로 그린다: 오늘 요약 · 응대 점수(+답글을 기다리는 불만) · 손님 칭찬 요약 · 월간 보고서 · 상권 요약 · 마케팅 요약.
// 응대 칸은 /api/care/* (리뷰 분석 서비스가 규칙으로 계산, AI 문장 아님). 상권·마케팅 요약은 처음 화면을 열 때 이미 받은
// 브리핑·추천 카드(store)와 /api/approvals 로만 만든다. 이 화면을 열어도 AI(HCX)를 새로 부르지 않는다.
// '전체 리포트 PDF 저장'은 이 여섯 칸을 브라우저 인쇄로 내보낸다 (인쇄 모양은 report.css, <html class="rp-view"> 일 때만).
import { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { Badge, Button, PageHead, Panel, StatTile, TopicBar } from "../../components/ui.jsx";
import { getState, openDrawer, useStore } from "../../state/store.js";
import { currentRoute } from "../../lib/router.js";
import { draftsOf, marketScope, scopeNote, shortBasis, snapValue, sourceUrl } from "../../lib/domain.js";
import { getReport, loadApprovals, loadMonth, loadReport, loadScore, reportReady, resetIfStoreChanged, useReport } from "./state.js";
import {
  RP_ISSUE_STATE, SOURCE_KO, clip, clockView, dateKo, deltaTone, monthKo, peakText, printMeta, shiftMonth, signed, sourceLine, trendGeometry,
} from "./format.js";
import "./report.css";

const RP_PDF_WAIT_MS = 20000;   // 아직 불러오는 칸이 있으면 여기까지 기다렸다가 인쇄 창을 연다
const RP_PDF_HINT = "인쇄 창이 열리면 ‘PDF로 저장’을 골라 주세요.";
// 인쇄할 때 점수 추이 그래프의 폭·높이. 창이 좁아도(휴대전화) 종이에서는 같은 모양·같은 쪽 수로 나오게.
// 폭은 종이에서 그래프 칸의 폭(A4 − 좌우 여백 − 칸 안 여백 ≈ 675px)에 가까운 값, 높이는 두 쪽 안에 들게 낮춤
const RP_PRINT_W = 680;
const RP_PRINT_H = 112;

const JUMPS = [
  ["rp-daily-sec", "오늘 요약"], ["rp-score-sec", "응대 점수"], ["rp-praise-sec", "손님 칭찬"],
  ["rp-month-sec", "월간 보고서"], ["rp-market-sec", "상권 요약"], ["rp-mkt-sec", "마케팅 요약"],
];

// 구역 바로가기: 그 패널로 스크롤하고 포커스도 옮긴다 (키보드 사용자가 거기서 이어 읽게)
function jump(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  el.focus({ preventScroll: true });
}

// 칸 위 상태 글 (불러오는 중 · 오류). 비면 안 보이지만 알림 영역은 남겨 둔다
function StateLine({ id, st, live = true }) {
  return <p id={id} className={["rp-state", st.bad && "bad"].filter(Boolean).join(" ")} role={live ? "status" : undefined}>{st.msg || ""}</p>;
}

const Delta = ({ n }) => <span className={["rp-delta", deltaTone(n)].filter(Boolean).join(" ")}>{signed(n)}</span>;

function Reasons({ list, empty }) {
  const items = Array.isArray(list) ? list : [];
  return (
    <ul className="plain rp-reasons">
      {items.length
        ? items.map((x, i) => <li key={i}><Delta n={x.delta} /><span>{x.message}</span></li>)
        : <li className="small muted">{empty}</li>}
    </ul>
  );
}

// ── 오늘 요약 ──
function DailyPanel({ daily }) {
  const d = daily.data;
  const src = d ? Object.entries(d.by_source || {}).map(([k, n]) => `${SOURCE_KO[k] || k} ${n}`).join(" · ") : "";
  const date = d?.date ? `${d.date}${d.until ? ` · ${String(d.until).slice(11, 16)}까지` : ""}` : "";
  return (
    <Panel title="오늘 요약" titleId="rp-daily-title" sub={date || undefined} id="rp-daily-sec" tabIndex={-1} className="rp-sec rp-daily">
      <StateLine id="rp-daily-state" st={daily} />
      {d && (
        <div id="rp-daily" className="stack-16">
          <p className="rp-summary">{d.summary}</p>
          <div className="tiles rp-tiles">
            <StatTile label="리뷰" value={`${d.review_count ?? 0}건`} />
            <StatTile label="불만" value={`${d.complaint_count ?? 0}건`} />
            <StatTile label="기한 안 답글" value={`${d.replied_on_time ?? 0}건`} />
            <StatTile label="늦은 답글" value={`${d.replied_late ?? 0}건`} />
          </div>
          <div>
            <p className="rp-line">응대 점수 <b>{d.score_start} → {d.score_end}</b> <Delta n={d.score_change ?? (d.score_end - d.score_start)} /></p>
            <Reasons list={d.changes} empty="오늘은 점수가 바뀐 일이 없어요." />
          </div>
          <div className="rp-todo"><span className="rp-todo-label">내일 먼저 할 일</span><strong>{d.todo?.text || "밀린 응대가 없어요"}</strong></div>
          <div className="stack-8">
            <p className="small muted">{src ? `들어온 곳: ${src} · ` : ""}답글 기다림 {d.pending_count ?? 0}건{d.overdue_count ? ` (기한 넘김 ${d.overdue_count}건)` : ""}</p>
            <p className="small muted">합성 리뷰는 지난 날짜(시나리오 기간)라서, 오늘 숫자에는 오늘 붙여넣기·캡처로 넣은 리뷰만 들어가요. 문장은 정해 둔 틀에 숫자만 넣었어요.</p>
          </div>
        </div>
      )}
    </Panel>
  );
}

// ── 응대 점수 ──
function ScorePanel({ score }) {
  const r = score.data;
  const peaks = peakText(r?.policy);
  return (
    <Panel title="응대 점수" titleId="rp-score-title" sub="최근 28일 · 100점에서 시작" id="rp-score-sec" tabIndex={-1} className="rp-sec rp-score">
      <StateLine id="rp-score-state" st={score} />
      {r && (
        <div id="rp-score" className="stack-16">
          <p className="rp-big"><span className="rp-big-n">{r.score}</span><span className="rp-big-unit">/ 100점</span></p>
          <div>
            <h3 className="rp-h3">점수가 바뀐 이유</h3>
            <Reasons list={r.reasons} empty="점수를 깎거나 올린 일이 없어요." />
          </div>
          {score.peak && <p className="rp-peak">지금은 피크 시간이라 답글 기한이 멈춰 있어요{peaks ? ` (${peaks})` : ""}.</p>}
          <p className="rp-untimed">지난 불만 <b>{r.untimed_unanswered ?? 0}건</b> <span className="small muted">· 기한 없이 답글을 안 단 지난(합성) 불만 리뷰</span></p>
          <p className="small muted">기한은 불만 리뷰를 받은 뒤 {r.policy?.sla_minutes ?? 30}분{peaks ? `, 피크(${peaks}) 중에는 멈춤` : ""}. 답글을 승인하면 기록돼요. 점수 이유는 서버 문장 그대로예요.</p>
        </div>
      )}
    </Panel>
  );
}

// ── 답글을 기다리는 불만: 남은 시간을 1초마다 센다 (이 칸만 다시 그림) ──
function PendingPanel({ score }) {
  const r = score.data;
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!r) return undefined;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [r]);
  const pending = score.pending;
  const sub = r ? `${pending.length}건${r.overdue_count ? ` · 기한 넘김 ${r.overdue_count}건` : ""}` : undefined;
  return (
    <Panel title="답글을 기다리는 불만" titleId="rp-pending-title" sub={sub} className="rp-sec rp-pending-panel">
      <StateLine id="rp-pending-state" st={score} live={false} />
      {r && (
        <ul className="plain rp-pending">
          {pending.length ? pending.map((p, i) => {
            const c = clockView(score.clocks[i], now);
            return (
              <li key={p.review_id || i} className={["rp-p", p.overdue && "over"].filter(Boolean).join(" ")}>
                <div className="rp-p-main">
                  <p className="rp-p-text">“{clip(p.text, 90)}”</p>
                  <p className="small muted">{(p.topic_names || []).join("·") || "불만"} · {SOURCE_KO[p.source] || p.source || ""}{Number(p.penalty) < 0 ? ` · 감점 ${p.penalty}점` : ""}</p>
                </div>
                <span className={["rp-clock", c.tone].filter(Boolean).join(" ")}>{c.text}</span>
              </li>
            );
          }) : <li className="small muted">지금 답글을 기다리는 불만이 없어요.</li>}
        </ul>
      )}
    </Panel>
  );
}

// ── 손님 칭찬 요약: 월간 보고서 응답의 praise 칸으로만 (요청을 더하지 않음). 집계 기간 = 월간 보고서에서 고른 달.
// 숫자·주제·메뉴·대표 한 줄은 리뷰 분석 서비스가 코드로 센 값 그대로다 (모델 호출 없음). 대표 한 줄은 서비스가 개인정보를 가린 글만 보낸다
function PraisePanel({ monthly, praise }) {
  const m = monthly.data, p = m?.praise;
  const period = m ? `${monthKo(m.month)}${m.until ? ` · ${dateKo(m.until)}까지` : ""}` : "";
  const topics = Array.isArray(p?.top_topics) ? p.top_topics : [], menus = Array.isArray(p?.top_menus) ? p.top_menus : [];
  const most = Math.max(1, ...topics.map((t) => Number(t.count) || 0));
  return (
    <Panel title="손님 칭찬 요약" titleId="rp-praise-title" sub={period || undefined} id="rp-praise-sec" tabIndex={-1} className="rp-sec rp-praise">
      <StateLine id="rp-praise-state" st={praise} />
      {p && (
        <div id="rp-praise" className="stack-16">
          <dl className="rp-counts">
            <div><dt>별점 4~5점</dt><dd>{p.high_rating_count ?? 0}건</dd></div>
            <div><dt>긍정 리뷰</dt><dd>{p.positive_count ?? 0}건</dd></div>
          </dl>
          <div className="rp-praise-body">
            <div>
              <h3 className="rp-h3">칭찬 주제 상위</h3>
              {topics.length
                ? <ul className="plain stack-16">{topics.map((t) => <li key={t.topic || t.topic_name}><TopicBar kind="praise" name={t.topic_name} value={`${t.count}건`} ratio={(Number(t.count) || 0) / most} /></li>)}</ul>
                : <p className="small muted">칭찬으로 분류된 주제가 아직 없어요.</p>}
            </div>
            <div>
              <h3 className="rp-h3">인기 메뉴 TOP 3 <span className="small muted">· 칭찬 리뷰에 이름이 나온 수</span></h3>
              <ol className="plain rp-menus">
                {menus.length
                  ? menus.map((x, i) => <li key={x.menu}><span className="rp-rank">{i + 1}</span><b>{x.menu}</b><span className="rp-menu-n">{x.count}건</span></li>)
                  : <li className="small muted">칭찬 리뷰에 나온 메뉴가 아직 없어요.</li>}
              </ol>
            </div>
            <div>
              <h3 className="rp-h3">대표 칭찬 한 줄</h3>
              {p.quote
                ? <blockquote className="rp-quote"><p>“{p.quote.text}”</p><footer className="small muted">{p.quote.rating ? `별점 ${p.quote.rating}점 리뷰` : "별점 없는 리뷰"} · 개인정보를 가린 글</footer></blockquote>
                : <p className="small muted">아직 칭찬 리뷰가 없어요.</p>}
            </div>
          </div>
          <p className="small muted">
            이 달 리뷰 {p.review_count ?? 0}건을 코드로 셌어요 (모델 호출 없음). 인기 메뉴와 대표 한 줄은 칭찬 리뷰 {p.praise_count ?? 0}건에서 골랐어요.
            {p.praise_basis === "rating" ? " 긍정으로 분류된 리뷰가 없어서, 별점 4점 이상이고 불만이 없는 리뷰를 칭찬 리뷰로 봤어요." : ""}
            <span className="rp-screen"> 달은 월간 보고서에서 바꿔요.</span>
          </p>
        </div>
      )}
    </Panel>
  );
}

// 날마다 점수 선 그래프 (외부 라이브러리 없이 SVG). 색은 report.css 가 정한다
function Trend({ trend, printing }) {
  const box = useRef(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const measure = () => setW(el.clientWidth || 0);
    measure();
    if (typeof ResizeObserver !== "function") return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const g = trendGeometry(trend, printing ? RP_PRINT_W : w, printing ? RP_PRINT_H : undefined);
  return (
    <div ref={box}>
      {!g ? <p className="small muted">점수 기록이 없어요.</p> : (
        <svg className="rp-trend" viewBox={`0 0 ${g.W} ${g.H}`} role="img" aria-label={g.label}>
          <line className="rp-gl" x1={g.L} x2={g.W - g.R} y1={g.y(100)} y2={g.y(100)} />
          <line className="rp-gl" x1={g.L} x2={g.W - g.R} y1={g.y(g.lo).toFixed(1)} y2={g.y(g.lo).toFixed(1)} />
          <text className="rp-ax" x={g.L - 8} y={g.y(100) + 4} textAnchor="end">100</text>
          <text className="rp-ax" x={g.L - 8} y={(g.y(g.lo) + 4).toFixed(1)} textAnchor="end">{g.lo}</text>
          <polyline className="rp-tl" points={g.pts.map((t, i) => `${g.x(i).toFixed(1)},${g.y(g.v[i]).toFixed(1)}`).join(" ")} />
          {g.pts.map((t, i) => <circle key={i} className="rp-pt" cx={g.x(i).toFixed(1)} cy={g.y(g.v[i]).toFixed(1)} r={i === g.last ? 4.5 : 2.5} />)}
          <text className="rp-ax rp-now" x={g.x(g.last).toFixed(1)} y={(g.y(g.v[g.last]) - 10).toFixed(1)} textAnchor={g.pts.length === 1 ? "middle" : "end"}>{g.v[g.last]}점</text>
          <text className="rp-ax" x={g.L} y={g.H - 6}>{dateKo(g.pts[0].date)}</text>
          <text className="rp-ax" x={g.W - g.R} y={g.H - 6} textAnchor="end">{dateKo(g.pts[g.last].date)}</text>
        </svg>
      )}
    </div>
  );
}

// ── 월간 보고서 ──
function MonthPanel({ rp, printing }) {
  const m = rp.monthly.data;
  const prevOff = !rp.month || !!(rp.maxMonth && rp.month <= shiftMonth(rp.maxMonth, -11));   // 1년 전까지
  const nextOff = !rp.month || !rp.maxMonth || rp.month >= rp.maxMonth;
  const move = async (step) => {
    const cur = getReport().month;
    if (!cur) return;
    await loadMonth(shiftMonth(cur, step));
    // 끝에 닿아 막힌 버튼의 포커스를 옆으로 (그려진 뒤에 본다. ui.jsx 의 Button 은 ref 를 넘기지 않아 id 로 찾음)
    setTimeout(() => {
      const prev = document.getElementById("rp-month-prev"), next = document.getElementById("rp-month-next");
      const btn = step < 0 ? prev : next, other = step < 0 ? next : prev;
      if (btn?.disabled && (document.activeElement === btn || document.activeElement === document.body)) other?.focus();
    }, 0);
  };
  const issues = Array.isArray(m?.repeated_issues) ? m.repeated_issues : [];
  const sugg = Array.isArray(m?.suggestions) ? m.suggestions : [];
  const changes = Array.isArray(m?.changes) ? m.changes : [];
  const nav = (
    <div className="rp-month-nav" role="group" aria-label="달 고르기">
      <Button size="small" id="rp-month-prev" disabled={prevOff} onClick={() => move(-1)}><span aria-hidden="true">‹</span> 이전 달</Button>
      <strong id="rp-month-label" aria-live="polite">{monthKo(rp.month)}</strong>
      <Button size="small" id="rp-month-next" disabled={nextOff} onClick={() => move(1)}>다음 달 <span aria-hidden="true">›</span></Button>
      <a id="rp-print" className="btn small rp-print" href={"/api/care/report/monthly/print" + (rp.month ? `?month=${encodeURIComponent(rp.month)}` : "")} target="_blank" rel="noopener">
        인쇄용 보기<span className="sr"> (새 탭)</span>
      </a>
    </div>
  );
  return (
    <Panel title="월간 보고서" titleId="rp-month-title" actions={nav} id="rp-month-sec" tabIndex={-1} className="rp-sec rp-month">
      <StateLine id="rp-month-state" st={rp.monthly} />
      {m && (
        <div id="rp-month" className="stack-16">
          <dl className="rp-nums">
            <div><dt>리뷰</dt><dd>{m.review_count ?? 0}건</dd></div>
            <div><dt>불만</dt><dd>{m.complaint_count ?? 0}건</dd></div>
            <div><dt>응대 점수</dt><dd>{m.score_start} → {m.score_end} <Delta n={m.score_change} /></dd></div>
            <div><dt>기한 넘긴 답글</dt><dd>{m.late_count ?? 0}건</dd></div>
          </dl>
          <figure className="rp-chart">
            <Trend trend={m.score_trend} printing={printing} />
            <figcaption className="small muted">날마다 응대 점수 (그날 끝 기준{m.until ? ` · ${String(m.until).slice(0, 10)}까지` : ""})</figcaption>
          </figure>
          <div>
            <h3 className="rp-h3">반복 불만과 재발 여부</h3>
            <div className="rp-table-wrap">
              <table className="rp-table">
                <thead><tr>
                  <th scope="col">불만</th><th scope="col" className="n">전체</th><th scope="col" className="n">이번 달</th><th scope="col" className="n">답글</th>
                  <th scope="col" className="n">답글 뒤 재발</th><th scope="col">상태</th><th scope="col">많은 시간대</th>
                </tr></thead>
                <tbody>
                  {issues.length ? issues.map((i, k) => (
                    <tr key={i.topic_name || k}>
                      <th scope="row">{i.topic_name}{i.is_repeated && <> <Badge tone="warn">반복</Badge></>}</th>
                      <td className="n">{i.review_count}</td><td className="n">{i.count_this_month}</td><td className="n">{i.replied_count}</td>
                      <td className="n">{i.recurred_after_reply}</td><td>{RP_ISSUE_STATE[i.state] || i.state}</td><td>{i.main_time_band || "–"}</td>
                    </tr>
                  )) : <tr><td colSpan={7} className="muted">이 달에 묶인 불만이 없어요.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
          <div>
            <h3 className="rp-h3">다음 달 개선 제안</h3>
            <ol className="plain rp-sugg">
              {sugg.length
                ? sugg.map((s, i) => <li key={i}><span className="rp-check" aria-hidden="true" /><span>{s.text}</span></li>)
                : <li className="muted">제안이 없어요.</li>}
            </ol>
          </div>
          {changes.length > 0 && (
            <details className="rp-more">
              <summary className="small">이 달에 점수가 바뀐 이유 {changes.length}개</summary>
              <Reasons list={changes} empty="" />
            </details>
          )}
          <p className="small muted">숫자는 코드가 계산하고, 제안은 정해 둔 틀에 숫자만 넣었어요 (AI 문장 아님). 원인을 단정하지 않으니 매장에서 확인해 주세요.</p>
        </div>
      )}
    </Panel>
  );
}

// ── 상권 요약: 브리핑의 상권 지표 (홈 '상권 저녁 매출' 칸과 같은 자료). 서버를 다시 부르지 않는다 ──
function MarketPanel() {
  const b = useStore((s) => s.briefing);
  const booted = useStore((s) => s.booted);
  const drawerOpen = useStore((s) => s.drawerOpen);
  const st = !b
    ? { msg: booted ? "브리핑을 불러오지 못해 상권 요약을 만들 수 없어요. 홈에서 다시 불러와 주세요." : "불러오는 중…", bad: booted }
    : { msg: "", bad: false };
  const snaps = b ? (b.snapshots || []).filter((s) => s && typeof s.value === "number") : [];
  const scoped = snaps.some((s) => marketScope(s));
  return (
    <Panel title="상권 요약" titleId="rp-market-title" sub="서울시 공개 상권 자료" id="rp-market-sec" tabIndex={-1} className="rp-sec rp-market">
      <StateLine id="rp-market-state" st={st} />
      {b && (
        <div id="rp-market" className="stack-16">
          <p className="rp-store">{[b.store?.name, b.store?.business_type_name, b.store?.area_name ? `${b.store.area_name} 상권` : ""].filter(Boolean).join(" · ")}</p>
          <ul className="plain rp-snaps">
            {snaps.length ? snaps.map((s, i) => {
              const url = sourceUrl(s.source);
              return (
                <li key={s.snapshot_id || i}>
                  <span className={["rp-snap-v", s.value < 0 && "neg"].filter(Boolean).join(" ")}>{snapValue(s)}</span>
                  <span className="rp-snap-t">
                    <b>{s.metric_name}</b>
                    <span className="small muted">
                      {[s.area_name, s.compared_with_quarter ? "전년 같은 분기 대비" : "", shortBasis(s.basis_label)].filter(Boolean).join(" · ")}
                      {url && <> · <a href={url} target="_blank" rel="noopener">원본</a></>}
                    </span>
                    {s.dev_fake && <Badge tone="bad">개발용 가짜 값 · 발표에 쓰지 마세요</Badge>}
                  </span>
                </li>
              );
            }) : <li className="small muted">상권 지표가 없어요.</li>}
          </ul>
          {scoped && (
            <p className="small muted">
              위 숫자는 {snaps.map((s) => [s.area_name, marketScope(s)].filter(Boolean).join(" · ")).join(", ")} 기준이에요. {scopeNote(snaps[0])} 'AI에게 묻기'는 고른 업종 하나의 하루 전체로 답해서 숫자가 다를 수 있어요.
            </p>
          )}
          <p className="small muted">상권 통계는 상권·업종 전체의 추정치예요. 우리 가게 매출이 아니에요.</p>
          <div><Button aria-controls="assistant" aria-expanded={drawerOpen} onClick={() => openDrawer(true)}>AI에게 묻기로 상권 더 보기</Button></div>
        </div>
      )}
    </Panel>
  );
}

// ── 마케팅 요약: 추천 카드 ⓑ(쿠폰 홍보)와 이 브라우저에서 만든 홍보글의 승인 상태, 서버 승인 기록 수.
// 맞춤 마케팅(#/marketing)은 링크와 이 브라우저에서 승인한 글 수(approvedLog)만 둔다. 마케팅 서비스는 부르지 않는다 ──
function MktPanel({ appr }) {
  const booted = useStore((s) => s.booted);
  const bootError = useStore((s) => s.bootError);
  const cards = useStore((s) => s.cards);
  const results = useStore((s) => s.results);
  const approved = useStore((s) => s.approved);
  const approvedLog = useStore((s) => s.approvedLog);
  const noCardB = useStore((s) => s.noCardB);
  const waiting = !booted && !cards.length;
  const promo = cards.find((p) => p.card.kind === "promo");
  let st = { msg: "", bad: false }, body = null;
  if (waiting) st = { msg: "불러오는 중…", bad: false };
  else if (promo) {
    const id = promo.card.card_id, made = !!results[id];
    const ds = draftsOf(results, id).filter((d) => d.generator === "coupon_promo");
    const ok = ds.filter((d) => approved.has(d.draft_id)).length;
    const [tone, text] = !made ? ["", "홍보글을 아직 만들지 않았어요"] : ds.length && ok === ds.length ? ["ok", "홍보글 승인 완료"] : ["warn", `홍보글 승인 대기 ${ds.length - ok}개`];
    body = (
      <>
        <p className="rp-mkt-title"><b>{promo.title}</b></p>
        <p className="rp-mkt-reason">{promo.card.reason_text}</p>
        <p className="small muted">근거: {sourceLine(promo)}</p>
        <p className="rp-mkt-st"><Badge tone={tone || undefined}>{text}</Badge><a className="small" href="#/cards">추천 카드에서 보기</a></p>
      </>
    );
  } else if (cards.length || !bootError) {
    body = <p className="muted">오늘은 쿠폰 홍보 카드(ⓑ)가 없어요.{noCardB ? ` ${noCardB}` : ""}</p>;
  } else st = { msg: "추천 카드를 불러오지 못해 마케팅 요약을 만들 수 없어요. 홈에서 다시 불러와 주세요.", bad: true };
  const mktDone = approvedLog.filter((x) => x.mkt).length;
  return (
    <Panel title="마케팅 요약" titleId="rp-mkt-title" sub="추천 카드 ⓑ · 맞춤 마케팅 · 승인 기록" id="rp-mkt-sec" tabIndex={-1} className="rp-sec rp-mkt">
      <StateLine id="rp-mkt-state" st={st} />
      {!waiting && (
        <div id="rp-mkt" className="stack-8">
          {body}
          {mktDone > 0 && <p className="small">맞춤 마케팅에서 승인한 글 {mktDone}건 (이 브라우저 기준)</p>}
          {/* 링크 줄(rp-screen)은 인쇄에서 빠진다 */}
          <p className="small rp-screen"><a href="#/marketing">맞춤 마케팅에서 자세히 보기</a></p>
          <p id="rp-approvals" className="small muted">{appr.text}</p>
        </div>
      )}
    </Panel>
  );
}

export default function Report() {
  resetIfStoreChanged();   // 가게가 바뀌었으면 고른 달·받은 값을 처음으로 (예전 rp.loadedAt = 0; rp.month = null)
  const rp = useReport();
  const booted = useStore((s) => s.booted);
  const hasCards = useStore((s) => s.cards.length > 0);
  const apprReady = booted || hasCards;
  const root = useRef(null);
  const alive = useRef(true);
  const [printing, setPrinting] = useState(false);
  const [head, setHead] = useState({ store: "", meta: "", note: "" });
  const [pdfWait, setPdfWait] = useState(false);
  const [pdfMsg, setPdfMsg] = useState(RP_PDF_HINT);

  // 화면을 열면 세 응대 칸을 부르고, 리포트 화면인 동안 <html class="rp-view"> (인쇄 모양이 이때만 먹음, 예전 rpMark)
  useEffect(() => {
    alive.current = true;
    document.documentElement.classList.add("rp-view");
    loadReport();
    return () => { alive.current = false; document.documentElement.classList.remove("rp-view"); };
  }, []);
  // 마케팅 요약의 승인 기록: 처음 불러오기가 끝났거나 카드가 있으면
  useEffect(() => { if (apprReady) loadApprovals(); }, [apprReady]);
  // 1분마다 점수만 다시 (화면을 보고 있을 때만). 새로 받을 때마다 다시 맞춘다. 화면을 떠나면 멈춤 (예전 rpStop)
  useEffect(() => {
    if (!rp.score.fetchedAt) return undefined;
    const id = setInterval(() => { if (!document.hidden && currentRoute() === "report") loadScore(true); }, 60000);
    return () => clearInterval(id);
  }, [rp.score.fetchedAt]);

  // 인쇄 직전: 머리글(가게 이름 · 출력한 날 · 기간)을 채우고 접힌 칸(details)을 펼친다. 인쇄가 끝나면 done 이 다시 접는다.
  // 시험용 실행이면 화면 위 띠의 안내(실제 AI 결과 아님)를 머리글에도 적는다 (인쇄에서는 그 띠가 빠지므로)
  const prep = useCallback(() => {
    const s = getState(), r = getReport();
    flushSync(() => {
      setPrinting(true);
      setHead({
        store: s.briefing?.store?.name || "",
        meta: printMeta(new Date(), { day: r.daily.data?.date, month: r.month, until: r.monthly.data?.until }),
        note: s.health?.mode_notice || "",
      });
    });
    root.current?.querySelectorAll("details:not([open])").forEach((d) => { d.open = true; d.dataset.rpOpened = "1"; });
  }, []);
  const done = useCallback(() => {
    root.current?.querySelectorAll("details[data-rp-opened]").forEach((d) => { d.open = false; delete d.dataset.rpOpened; });
    setPrinting(false);
  }, []);
  // 브라우저 메뉴(Ctrl+P)로 인쇄해도 같은 머리글·펼친 칸으로 나오게
  useEffect(() => {
    window.addEventListener("beforeprint", prep);
    window.addEventListener("afterprint", done);
    return () => { window.removeEventListener("beforeprint", prep); window.removeEventListener("afterprint", done); };
  }, [prep, done]);

  // 전체 리포트 PDF 저장: 브라우저 인쇄 창을 연다 (거기서 'PDF로 저장'). 서버에 새로 묻지 않고, 지금 그려진 여섯 칸이 그대로 나온다
  const onPdf = async () => {
    if (!reportReady()) {   // 아직 불러오는 칸이 있으면 끝날 때까지 기다린다 (그동안 버튼을 잠근다)
      setPdfWait(true);
      setPdfMsg("리포트를 다 불러오면 인쇄 창을 열어요…");
      const until = Date.now() + RP_PDF_WAIT_MS;
      while (!reportReady() && Date.now() < until) await new Promise((ok) => setTimeout(ok, 150));
      if (!alive.current) return;   // 기다리는 동안 다른 화면으로 갔으면 인쇄하지 않는다
      setPdfWait(false);
      setPdfMsg(RP_PDF_HINT);
      if (currentRoute() !== "report") return;
    }
    prep();
    window.print();
  };
  const reload = () => { loadReport(true); if (apprReady) loadApprovals(); };

  return (
    <div className="col wide rp" ref={root} data-view="report">
      {/* 인쇄 전용 머리글: 화면에서는 숨기고 인쇄에서만 보인다 */}
      <div id="rp-print-head" className="rp-print-head">
        <p className="rp-print-title"><strong id="rp-print-store">{head.store}</strong><span>종합 리포트</span></p>
        <p id="rp-print-meta" className="rp-print-meta">{head.meta}</p>
        <p id="rp-print-note" className="rp-print-note">{head.note}</p>
      </div>
      <PageHead
        owner="고객 응대 비서 · 마케팅 비서"
        title="종합 리포트"
        sub="숫자는 리뷰 기록으로 코드가 계산해요. 이 화면을 열어도 AI를 새로 부르지 않아요."
        actions={<>
          <Button id="rp-reload" onClick={reload}>다시 불러오기</Button>
          <Button id="rp-pdf" variant="primary" disabled={pdfWait} onClick={onPdf}>전체 리포트 PDF 저장</Button>
        </>}
      />
      <div className="rp-bar">
        <nav className="rp-jump" aria-label="구역 바로가기">
          <ul className="plain">
            {JUMPS.map(([id, label]) => <li key={id}><button type="button" className="rp-chip" onClick={() => jump(id)}>{label}</button></li>)}
          </ul>
        </nav>
        <p id="rp-pdf-msg" className="small muted" role="status">{pdfMsg}</p>
      </div>
      <DailyPanel daily={rp.daily} />
      <div className="grid-2 rp-pair">
        <ScorePanel score={rp.score} />
        <PendingPanel score={rp.score} />
      </div>
      <PraisePanel monthly={rp.monthly} praise={rp.praise} />
      <MonthPanel rp={rp} printing={printing} />
      <div className="grid-2 rp-pair">
        <MarketPanel />
        <MktPanel appr={rp.appr} />
      </div>
    </div>
  );
}
