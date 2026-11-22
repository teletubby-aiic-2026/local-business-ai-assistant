// 종합 리포트 (#/report). 6차 회의(11/20) Figma 06 'D1 종합 리포트' 구성:
// 머리([다시 만들기] [PDF 저장]) → 오늘 요약·응대 점수 한 줄 → 탭(주간·월간)과 기간 이동 → 저장 안내 띠 → 타일 4개
// → '이번 주에 고칠 것'/'이번 달에 고칠 것'(끝난 기간은 '이 주·이 달 기록에서 고칠 것') + '주제별 흐름' → '마케팅 숫자' → 손님 칭찬 요약 · 응대 기록(점수 추이·반복 불만)
// → 응대 점수 · 답글을 기다리는 불만 · 상권 요약 · 마케팅 요약 → '저장된 보고서' 목록.
// 주간·월간 보고서는 /api/reports/* (서버가 계정별로 저장. 숫자는 리뷰 분석 서비스의 규칙 계산, AI 문장 아님).
// 오늘 요약·응대 점수는 /api/care/* 로 그때그때. 상권·마케팅 요약은 처음 화면을 열 때 이미 받은 브리핑·추천 카드와 /api/approvals 로만.
// [PDF 저장]은 지금 보이는 보고서를 브라우저 인쇄로 내보낸다 (인쇄 모양은 report.css, <html class="rp-view"> 일 때만).
// 월간 탭에는 리뷰 분석 서비스의 A4 인쇄용 페이지 링크(#rp-print)도 둔다.
import { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { Badge, Button, PageHead, Panel, StatTile, Tabs, TopicBar } from "../../components/ui.jsx";
import { getState, openDrawer, useStore } from "../../state/store.js";
import { currentRoute, go, navTo } from "../../lib/router.js";
import { draftsOf, isOwnStore, marketScope, shortBasis, snapValue, sourceUrl } from "../../lib/domain.js";
import {
  KINDS, getReport, loadApprovals, loadReport, loadScore, openReport, openSaved, remakeReport, reportReady, resetIfStoreChanged, setTab, useReport,
} from "./state.js";
import {
  KIND_KO, NONE, NO_CHANGE, PERIOD_WORDS, PRAISE_TOPIC_NOTE, RP_ISSUE_STATE, RP_NOTE, SOURCE_KO, TOPIC_BASIS, changeText, clip, clockView, dateKo, deltaTone, fixEmpty, fixItems,
  fixTitle, isPast, marketingNumbers, menuTitle, peakText, periodText, printMeta, savedNote, scoreReasons, sourceLine, stamp, tilesOf, topicRows, trendGeometry,
} from "./format.js";
import "./report.css";

const RP_PDF_WAIT_MS = 20000;   // 아직 불러오는 칸이 있으면 여기까지 기다렸다가 인쇄 창을 연다
const RP_PDF_HINT = "인쇄 창이 열리면 ‘PDF로 저장’을 골라 주세요.";
// 인쇄할 때 점수 추이 그래프의 폭·높이. 창이 좁아도(휴대전화) 종이에서는 같은 모양·같은 쪽 수로 나오게
const RP_PRINT_W = 680;
const RP_PRINT_H = 112;
const TAB_LIST = [{ id: "weekly", label: "주간" }, { id: "monthly", label: "월간" }];

// 칸 위 상태 글 (불러오는 중 · 오류). 비면 안 보이지만 알림 영역은 남겨 둔다
function StateLine({ id, st, live = true }) {
  return <p id={id} className={["rp-state", st.bad && "bad"].filter(Boolean).join(" ")} role={live ? "status" : undefined}>{st.msg || ""}</p>;
}

const Delta = ({ n }) => <span className={["rp-delta", deltaTone(n)].filter(Boolean).join(" ")}>{changeText(n)}</span>;
// 점수 시작 → 끝과 변화. 변화가 0이면 '98 → 98 · 변화 없음' (11/22 QA R3: '98 → 98 0'을 읽지 못함)
const ScoreMove = ({ start, end, n }) => <>{start} → {end} {changeText(n) === NO_CHANGE && "· "}<Delta n={n} /></>;

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

// 28일 응대 점수 바로 아래 '왜 이 점수인지': 크게 깎인 것부터 3줄, 나머지는 접어 둔다 (11/22 QA R2: 이유가 아래 칸에만 있어 98점의 까닭을 못 찾음).
// 전체 목록은 아래 '응대 점수' 칸에도 있어 인쇄에서는 접은 칸을 뺀다 (rp-screen)
function ScoreWhy({ reasons }) {
  const { shown, rest } = scoreReasons(reasons);
  if (!shown.length) return null;
  return (
    <div id="rp-score-why" role="group" aria-label="점수가 바뀐 이유">
      <Reasons list={shown} />
      {rest.length > 0 && (
        <details className="rp-more rp-screen">
          <summary className="small">나머지 이유 {rest.length}개</summary>
          <Reasons list={rest} />
        </details>
      )}
    </div>
  );
}

// ── 오늘 요약 · 응대 점수 한 줄 (저장하지 않음, 그때그때) ──
function TodayStrip({ daily, score }) {
  const d = daily.data, r = score.data;
  const src = d ? Object.entries(d.by_source || {}).map(([k, n]) => `${SOURCE_KO[k] || k} ${n}`).join(" · ") : "";
  const when = d?.date ? `${dateKo(d.date)}${d.until ? ` · ${String(d.until).slice(11, 16)}까지` : ""}` : "";
  return (
    <section className="rp-today" id="rp-today" aria-label="오늘 요약과 응대 점수">
      <div className="rp-today-cell" id="rp-daily-sec">
        <p className="rp-today-head"><b>오늘 요약</b>{when && <span className="small muted">{when}</span>}</p>
        <StateLine id="rp-daily-state" st={daily} />
        {d && (
          <div id="rp-daily" className="stack-8">
            <p className="rp-today-nums">
              리뷰 <b>{d.review_count ?? 0}건</b> · 불만 <b>{d.complaint_count ?? 0}건</b> · 기한 안 답글 <b>{d.replied_on_time ?? 0}건</b> · 늦은 답글 <b>{d.replied_late ?? 0}건</b>
            </p>
            <p className="rp-todo"><span className="rp-todo-label">내일 먼저 할 일</span><strong>{d.todo?.text || "밀린 응대가 없어요"}</strong></p>
            <details className="rp-more">
              <summary className="small">오늘 점수 <ScoreMove start={d.score_start} end={d.score_end} n={d.score_change ?? (d.score_end - d.score_start)} /></summary>
              <Reasons list={d.changes} empty="오늘은 점수가 바뀐 일이 없어요." />
              <p className="small muted">{src ? `들어온 곳: ${src} · ` : ""}답글 기다림 {d.pending_count ?? 0}건{d.overdue_count ? ` (기한 넘김 ${d.overdue_count}건)` : ""}</p>
              <p className="small muted">합성 리뷰는 지난 날짜라서 오늘 숫자에는 오늘 붙여넣기·캡처로 넣은 리뷰만 들어가요.</p>
            </details>
          </div>
        )}
      </div>
      <div className="rp-today-cell rp-today-score" id="rp-score-line">
        <p className="rp-today-head"><b>응대 점수</b><span className="small muted">최근 28일</span></p>
        <StateLine id="rp-score-line-state" st={score} live={false} />
        {r && (
          <>
            <p className="rp-big"><span className="rp-big-n">{r.score}</span><span className="rp-big-unit">/ 100점</span></p>
            <p className="small muted">답글 기다림 {score.pending.length}건{r.overdue_count ? ` · 기한 넘김 ${r.overdue_count}건` : ""}</p>
            <ScoreWhy reasons={r.reasons} />
          </>
        )}
      </div>
    </section>
  );
}

// ── 탭과 기간 이동 ──
function PeriodBar({ rp }) {
  const kind = rp.tab, view = rp[kind].data, w = PERIOD_WORDS[kind];
  const nav = view?.nav || {};
  const prevRef = useRef(null), nextRef = useRef(null);
  const move = async (key, step) => {
    await openReport(kind, key);
    // 끝에 닿아 막힌 버튼의 포커스를 옆으로 (그려진 뒤에 본다)
    setTimeout(() => {
      const btn = step < 0 ? prevRef.current : nextRef.current, other = step < 0 ? nextRef.current : prevRef.current;
      if (btn?.disabled && (document.activeElement === btn || document.activeElement === document.body)) other?.focus();
    }, 0);
  };
  const busy = !!rp.busy;
  return (
    <div className="rp-bar">
      <Tabs tabs={TAB_LIST} active={kind} onChange={setTab} idPrefix="rp" label="보고서 종류" />
      <div className="rp-period-nav" role="group" aria-label="기간 고르기">
        <Button ref={prevRef} size="small" id="rp-prev" disabled={!nav.prev || busy} onClick={() => move(nav.prev, -1)}>
          <span aria-hidden="true">‹</span> {w.prev}
        </Button>
        <strong id="rp-period-label" aria-live="polite">{periodText(view?.period) || w.now}</strong>
        <Button ref={nextRef} size="small" id="rp-next" disabled={!nav.next || busy} onClick={() => move(nav.next, 1)}>
          {w.next} <span aria-hidden="true">›</span>
        </Button>
        {kind === "monthly" && view?.period?.key && (
          <a id="rp-print" className="btn small rp-print" href={`/api/care/report/monthly/print?month=${encodeURIComponent(view.period.key)}`} target="_blank" rel="noopener">
            A4 인쇄용<span className="sr"> (새 탭)</span>
          </a>
        )}
      </div>
    </div>
  );
}

// ── 고칠 것 (근거와 함께 최대 3개). 제목·문장은 보는 기간에 맞게 (끝난 기간이면 '이 주 기록에서 고칠 것') ──
function FixPanel({ view }) {
  const sugg = fixItems(view);
  return (
    <Panel title={fixTitle(view)} titleId="rp-fix-title" id="rp-fix-sec" className="rp-sec rp-fix">
      <ol className="plain rp-fixes" id="rp-fixes">
        {sugg.length ? sugg.map((s, i) => (
          <li key={i}>
            <span className="rp-num" aria-hidden="true">{i + 1}</span>
            <div className="rp-fix-body">
              <p className="rp-fix-title">{s.title || s.text}</p>
              {s.evidence && <p className="small muted">근거: {s.evidence}</p>}
              {s.title && s.text && <p className="small">{s.text}</p>}
            </div>
          </li>
        )) : <li className="small muted">{fixEmpty(view)}</li>}
      </ol>
      {sugg.length > 0 && <p className="small muted rp-sugg-note">원인을 단정하지 않은 제안이에요. 매장에서 확인해 주세요.</p>}
    </Panel>
  );
}

// ── 주제별 흐름: 불만(빨강)·칭찬(초록) 주제별 리뷰 수와 지난 기간 ──
// 주제는 리뷰 속 문장 기준이라 불만 리뷰 안의 칭찬도 칭찬 주제로 센다. '손님 칭찬 요약'(리뷰 단위)과 어긋나 보이지 않게 기준을 밝힌다 (11/21 QA)
function TopicPanel({ view }) {
  const w = PERIOD_WORDS[view.kind];
  const { complaints, praises, most } = topicRows(view.report?.topics, 3);
  const none = !Number(view.report?.review_count);
  const group = (title, list, kind, note) => list.length > 0 && (
    <div className="stack-8">
      <h3 className="rp-h3">{title}{note && <span className="small muted"> · {note}</span>}</h3>
      <ul className="plain stack-16">
        {list.map((t) => (
          <li key={t.topic}><TopicBar kind={kind} name={t.topic_name} value={`${t.count}건 · ${w.prev} ${t.previous ?? 0}건`} ratio={(Number(t.count) || 0) / most} /></li>
        ))}
      </ul>
    </div>
  );
  return (
    <Panel title="주제별 흐름" titleId="rp-topics-title" sub={complaints.length || praises.length ? TOPIC_BASIS : undefined} id="rp-topics-sec" className="rp-sec rp-topics">
      <div className="stack-16" id="rp-topics">
        {complaints.length || praises.length ? <>{group("불만", complaints, "complaint")}{group("칭찬", praises, "praise", PRAISE_TOPIC_NOTE)}</>
          : <p className="small muted">{none ? (isPast(view) ? "이 기간에는 리뷰가 없었어요." : "아직 리뷰가 없어요.") : "이 기간 리뷰에서 나눈 주제가 아직 없어요."}</p>}
      </div>
    </Panel>
  );
}

// ── 마케팅 숫자: 승인한 홍보 글은 승인 기록으로. 쿠폰 사용률·광고비·불만 재발은 값이 올 때만 칸을 그리고, 없으면 맞춤 마케팅 보고서로 안내 ──
// 맞춤 마케팅 화면은 navTo 의 sub 로 보고서 탭을 아직 열지 않는다 (지금은 #/marketing 의 첫 탭으로 감, marketing/state.js handleNav)
function MarketingNumbers({ view }) {
  const { cells, elsewhere } = marketingNumbers(view);
  return (
    <Panel title="마케팅 숫자" titleId="rp-mn-title" sub={elsewhere ? "승인 기록" : "맞춤 마케팅 기록 · 승인 기록"} id="rp-mn-sec" className="rp-sec rp-mn">
      <dl className="rp-nums" id="rp-mn">
        {cells.map((x) => <div key={x.label}><dt>{x.label}</dt><dd>{x.value}</dd></div>)}
      </dl>
      {elsewhere && (
        <div className="stack-8" id="rp-mn-more">
          <p className="small muted">쿠폰 사용률·광고비 판정은 맞춤 마케팅 보고서에서 볼 수 있어요.</p>
          <div className="btn-row"><Button size="small" onClick={() => navTo("marketing", "report")}>맞춤 마케팅 보고서 보기</Button></div>
        </div>
      )}
    </Panel>
  );
}

// ── 손님 칭찬 요약: 그 보고서 기간의 praise 칸 (칭찬 주제는 '주제별 흐름'에) ──
function PraisePanel({ view }) {
  const p = view.report?.praise;
  const menus = Array.isArray(p?.top_menus) ? p.top_menus : [];
  return (
    <Panel title="손님 칭찬 요약" titleId="rp-praise-title" sub={periodText(view.period) || undefined} id="rp-praise-sec" className="rp-sec rp-praise">
      {!p ? <p className="small muted">이 서버의 리뷰 분석 서비스는 아직 손님 칭찬 요약을 보내지 않아요.</p> : (
        <div id="rp-praise" className="stack-16">
          <dl className="rp-counts">
            <div><dt>별점 4~5점</dt><dd>{p.high_rating_count ?? 0}건</dd></div>
            <div><dt>긍정 리뷰</dt><dd>{p.positive_count ?? 0}건</dd></div>
          </dl>
          <div className="rp-praise-body">
            <div>
              <h3 className="rp-h3">{menuTitle(menus)} <span className="small muted">· 칭찬 리뷰에 이름이 나온 수</span></h3>
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
            인기 메뉴와 대표 한 줄은 이 기간 리뷰 {p.review_count ?? 0}건 중 칭찬 리뷰 {p.praise_count ?? 0}건에서 골랐어요.
            {p.praise_basis === "rating" ? " 긍정으로 분류된 리뷰가 없어서 별점 4점 이상이고 불만이 없는 리뷰를 칭찬 리뷰로 봤어요." : ""}
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

// ── 응대 기록: 그 기간의 숫자 · 날마다 점수 · 반복 불만과 재발 여부 · 점수가 바뀐 이유 (예전 '월간 보고서' 칸) ──
function RecordPanel({ view, printing }) {
  const m = view.report || {}, w = PERIOD_WORDS[view.kind];
  const issues = Array.isArray(m.repeated_issues) ? m.repeated_issues : [];
  const changes = Array.isArray(m.changes) ? m.changes : [];
  return (
    <Panel title="응대 기록" titleId="rp-record-title" sub={periodText(view.period) || undefined} id="rp-record-sec" className="rp-sec rp-record">
      <div id="rp-record" className="stack-16">
        <dl className="rp-nums">
          <div><dt>리뷰</dt><dd>{m.review_count ?? 0}건</dd></div>
          <div><dt>불만</dt><dd>{m.complaint_count ?? 0}건</dd></div>
          <div><dt>응대 점수</dt><dd><ScoreMove start={m.score_start} end={m.score_end} n={m.score_change} /></dd></div>
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
                <th scope="col">불만</th><th scope="col" className="n">전체</th><th scope="col" className="n">{w.now}</th><th scope="col" className="n">답글</th>
                <th scope="col" className="n">답글 뒤 재발</th><th scope="col">상태</th><th scope="col">많은 시간대</th>
              </tr></thead>
              <tbody>
                {issues.length ? issues.map((i, k) => (
                  <tr key={i.issue_id || i.topic_name || k}>
                    <th scope="row">{i.topic_name}{i.is_repeated && <> <Badge tone="warn">반복</Badge></>}</th>
                    <td className="n">{i.review_count}</td><td className="n">{i[w.key] ?? 0}</td><td className="n">{i.replied_count}</td>
                    <td className="n">{i.recurred_after_reply}</td><td>{RP_ISSUE_STATE[i.state] || i.state}</td><td>{i.main_time_band || NONE}</td>
                  </tr>
                )) : <tr><td colSpan={7} className="muted">이 기간에 묶인 불만이 없어요.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
        {changes.length > 0 && (
          <details className="rp-more">
            <summary className="small">이 기간에 점수가 바뀐 이유 {changes.length}개</summary>
            <Reasons list={changes} empty="" />
          </details>
        )}
      </div>
    </Panel>
  );
}

// ── 탭 하나의 보고서 (저장 안내 띠부터 응대 기록까지) ──
function ReportBody({ sheet, busy, printing }) {
  const view = sheet.data;
  const note = savedNote(view, sheet.remade);   // 다시 만든 뒤면 무엇이 반영됐는지 한 마디 (11/21 QA)
  // 보던 보고서가 있으면 다른 기간을 여는 동안 그대로 두고(흐리게) 안내 띠에 진행 글을 보인다 (칸이 위아래로 튀지 않게)
  const loading = !!view && !!busy && !sheet.bad;
  return (
    <div className={["stack-16 rp-body", loading && "rp-busy"].filter(Boolean).join(" ")} aria-busy={loading || undefined}>
      <StateLine id="rp-report-state" st={view && !sheet.bad ? { msg: "" } : sheet} />
      {view && (
        <>
          <p id="rp-saved" className={["rp-saved", !loading && note.tone].filter(Boolean).join(" ")} role="status">{loading ? sheet.msg : note.text}</p>
          <div className="tiles rp-tiles" id="rp-tiles">
            {tilesOf(view).map((t) => <StatTile key={t.id} id={t.id} label={t.label} value={t.value} sub={t.sub || undefined} tint={t.tint} title={t.title} />)}
          </div>
          <div className="grid-2 rp-pair">
            <FixPanel view={view} />
            <TopicPanel view={view} />
          </div>
          <MarketingNumbers view={view} />
          <PraisePanel view={view} />
          <RecordPanel view={view} printing={printing} />
        </>
      )}
    </div>
  );
}

// ── 응대 점수 (최근 28일, 그때그때) ──
function ScorePanel({ score }) {
  const r = score.data;
  const peaks = peakText(r?.policy);
  return (
    <Panel title="응대 점수" titleId="rp-score-title" sub="최근 28일 · 100점에서 시작" id="rp-score-sec" className="rp-sec rp-score">
      <StateLine id="rp-score-state" st={score} />
      {r && (
        <div id="rp-score" className="stack-16">
          <p className="rp-big"><span className="rp-big-n">{r.score}</span><span className="rp-big-unit">/ 100점</span></p>
          <div>
            <h3 className="rp-h3">점수가 바뀐 이유</h3>
            <Reasons list={r.reasons} empty="점수를 깎거나 올린 일이 없어요." />
          </div>
          {score.peak && <p className="rp-peak">지금은 피크 시간이라 답글 기한이 멈춰 있어요.</p>}
          {/* 답글 기한을 세지 않는 예전(합성) 불만. 0건이면(직접 등록한 가게 등) 줄을 두지 않는다 */}
          {Number(r.untimed_unanswered) > 0 && (
            <p className="rp-untimed">지난 불만 <b>{r.untimed_unanswered}건</b> <span className="small muted">· 아직 답글을 안 단 예전 불만이에요. 합성 리뷰라 답글 기한은 세지 않아요.</span></p>
          )}
          <p className="small muted">답글 기한은 불만 리뷰를 받은 뒤 {r.policy?.sla_minutes ?? 30}분이에요{peaks ? ` (피크 ${peaks}에는 멈춤)` : ""}. 답글을 승인하면 기록돼요.</p>
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

// ── 상권 요약: 브리핑의 상권 지표 (홈 '상권 저녁 매출' 칸과 같은 자료). 서버를 다시 부르지 않는다.
// 직접 등록한 가게는 브리핑에 상권 지표가 없을 수 있어 '없어요' 대신 상권 분석 화면으로 안내 (홈 칸과 같은 기준) ──
function MarketPanel() {
  const b = useStore((s) => s.briefing);
  const booted = useStore((s) => s.booted);
  const drawerOpen = useStore((s) => s.drawerOpen);
  const own = useStore((s) => isOwnStore(s.me));
  const st = !b
    ? { msg: booted ? "브리핑을 불러오지 못해 상권 요약을 만들 수 없어요. 홈에서 다시 불러와 주세요." : "불러오는 중…", bad: booted }
    : { msg: "", bad: false };
  const snaps = b ? (b.snapshots || []).filter((s) => s && typeof s.value === "number") : [];
  const scoped = snaps.some((s) => marketScope(s));
  return (
    <Panel title="상권 요약" titleId="rp-market-title" sub="서울시 공개 상권 자료" id="rp-market-sec" className="rp-sec rp-market">
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
            }) : own ? <li className="rp-snap-go">상권 매출·점포 수·유동인구는 상권 분석에서 볼 수 있어요.</li>
              : <li className="small muted">상권 지표가 없어요.</li>}
          </ul>
          {/* 범위(시간대·업종)는 지표 이름에 이미 있다. 고지는 한 문단: 우리 가게 매출 아님 + 서랍의 숫자와 범위가 다름 */}
          <p className="small muted">
            상권·업종 전체의 추정치예요 (우리 가게 매출 아님).{scoped ? " 'AI에게 묻기'는 업종 하나의 하루 전체로 답해서 숫자가 다를 수 있어요." : ""}
          </p>
          <div className="btn-row">
            {!snaps.length && own && <Button variant="primary" onClick={() => go("market")}>상권 분석 보기</Button>}
            <Button aria-controls="assistant" aria-expanded={drawerOpen} onClick={() => openDrawer(true)}>AI에게 묻기로 상권 더 보기</Button>
          </div>
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
    <Panel title="마케팅 요약" titleId="rp-mkt-title" id="rp-mkt-sec" className="rp-sec rp-mkt">
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

// ── 저장된 보고서 목록 (지금 가게 · 이 계정, 기간이 늦은 것부터). 인쇄에서는 빠진다 ──
function SavedList({ rp }) {
  const s = rp.saved;
  const storeName = useStore((st) => st.briefing?.store?.name || "");
  const cur = rp[rp.tab].data;
  const open = async (item) => {
    await openSaved(item);
    document.getElementById(`rp-tab-${item.kind}`)?.focus({ preventScroll: true });
    document.getElementById("rp-period-label")?.scrollIntoView?.({ block: "center" });
  };
  let body;
  if (s.storage === "guest") body = <p className="small muted">로그인하면 만든 보고서가 여기에 쌓여요.</p>;
  else if (s.storage === "unavailable") body = <p className="small muted">지금은 저장된 보고서를 불러오지 못했어요.</p>;
  else if (s.items.length) {
    body = (
      <ul className="plain rp-saved-list" id="rp-saved-list">
        {s.items.map((i) => {
          const on = cur && cur.kind === i.kind && cur.period?.key === i.key;
          return (
            <li key={`${i.kind}:${i.key}`} className={on ? "on" : undefined} aria-current={on ? "true" : undefined}>
              <Badge>{KIND_KO[i.kind] || i.kind}</Badge>
              <span className="rp-saved-name"><b>{i.label}</b> <span className="small muted">{i.range}</span></span>
              <span className="small muted rp-made">만든 시각 {stamp(i.created_at)}</span>
              <Button size="small" onClick={() => open(i)} aria-label={`${KIND_KO[i.kind] || ""} ${i.label} 보고서 열기`}>열기</Button>
            </li>
          );
        })}
      </ul>
    );
  } else if (!s.msg) body = <p className="small muted">아직 저장된 보고서가 없어요.</p>;
  return (
    <Panel title="저장된 보고서" titleId="rp-list-title" sub={`이 계정${storeName ? ` · ${storeName}` : ""}`} id="rp-list-sec" className="rp-sec rp-list rp-screen">
      <StateLine id="rp-list-state" st={s} live={false} />
      {body}
    </Panel>
  );
}

export default function Report() {
  resetIfStoreChanged();   // 가게가 바뀌었으면 고른 탭·기간·받은 값을 처음으로
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

  // 화면을 열면 위 요약 줄·지금 탭 보고서·목록을 부르고, 리포트 화면인 동안 <html class="rp-view"> (인쇄 모양이 이때만 먹음)
  useEffect(() => {
    alive.current = true;
    document.documentElement.classList.add("rp-view");
    loadReport();
    return () => { alive.current = false; document.documentElement.classList.remove("rp-view"); };
  }, []);
  // 마케팅 요약의 승인 기록: 처음 불러오기가 끝났거나 카드가 있으면
  useEffect(() => { if (apprReady) loadApprovals(); }, [apprReady]);
  // 1분마다 점수만 다시 (화면을 보고 있을 때만). 화면을 떠나면 멈춤
  useEffect(() => {
    if (!rp.score.fetchedAt) return undefined;
    const id = setInterval(() => { if (!document.hidden && currentRoute() === "report") loadScore(true); }, 60000);
    return () => clearInterval(id);
  }, [rp.score.fetchedAt]);

  // 인쇄 직전: 머리글(가게 이름 · 출력한 날 · 기간 · 만든 시각)을 채우고 접힌 칸(details)을 펼친다. 인쇄가 끝나면 done 이 다시 접는다.
  // 시험용 실행이면 화면 위 띠의 안내(실제 AI 결과 아님)를 머리글에도 적는다 (인쇄에서는 그 띠가 빠지므로)
  const prep = useCallback(() => {
    const s = getState(), r = getReport(), view = r[r.tab].data;
    flushSync(() => {
      setPrinting(true);
      setHead({
        store: s.briefing?.store?.name || "",
        meta: printMeta(new Date(), { day: r.daily.data?.date, kind: r.tab, period: view?.period, created: view?.created_at }),
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

  // PDF 저장: 브라우저 인쇄 창을 연다 (거기서 'PDF로 저장'). 서버에 새로 묻지 않고, 지금 보이는 보고서가 그대로 나온다
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

  return (
    <div className="col wide rp" ref={root} data-view="report">
      {/* 인쇄 전용 머리글: 화면에서는 숨기고 인쇄에서만 보인다 */}
      <div id="rp-print-head" className="rp-print-head">
        <p className="rp-print-title"><strong id="rp-print-store">{head.store}</strong><span>종합 리포트</span></p>
        <p id="rp-print-meta" className="rp-print-meta">{head.meta}</p>
        <p className="rp-print-meta">{RP_NOTE}</p>
        <p id="rp-print-note" className="rp-print-note">{head.note}</p>
      </div>
      {/* 'AI 문장 아님' 고지(RP_NOTE)는 이 머리 한 곳에만 (칸마다 되풀이하지 않음). 인쇄에서는 머리가 빠지므로 위 인쇄 머리글에도 같은 줄 */}
      <PageHead
        owner="고객 응대 비서 · 마케팅 비서"
        title="종합 리포트"
        sub={RP_NOTE}
        actions={<>
          <Button id="rp-remake" disabled={!!rp.busy} onClick={() => remakeReport()}>{rp.busy === "remake" ? "다시 만드는 중…" : "다시 만들기"}</Button>
          <Button id="rp-pdf" variant="primary" disabled={pdfWait} onClick={onPdf}>PDF 저장</Button>
        </>}
      />
      <p id="rp-pdf-msg" className="small muted rp-pdf-msg rp-screen" role="status">{pdfMsg}</p>
      <TodayStrip daily={rp.daily} score={rp.score} />
      <PeriodBar rp={rp} />
      {KINDS.map((k) => (
        <div key={k} role="tabpanel" id={`rp-panel-${k}`} aria-labelledby={`rp-tab-${k}`} hidden={k !== rp.tab} className="rp-tabpanel">
          {k === rp.tab && <ReportBody sheet={rp[k]} busy={rp.busy} printing={printing} />}
        </div>
      ))}
      <div className="grid-2 rp-pair">
        <ScorePanel score={rp.score} />
        <PendingPanel score={rp.score} />
      </div>
      <div className="grid-2 rp-pair">
        <MarketPanel />
        <MktPanel appr={rp.appr} />
      </div>
      <SavedList rp={rp} />
    </div>
  );
}
