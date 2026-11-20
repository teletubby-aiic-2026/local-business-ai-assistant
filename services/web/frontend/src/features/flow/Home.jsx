// 홈 = 대시보드 (예전 1 오늘 renderBriefing·renderDash·renderKeywords·renderHourChart. 배치는 Figma 06 B1).
// 한 줄 흐름: 브리핑 기간 → 제목 → 오늘의 핵심 문제 → 숫자 타일 4 → 오늘 할 일(넓은 칸)·담당 비서 현황(좁은 칸) → 불만 시간대·주제 차트 → AI에게 묻기.
// 차트는 브리핑(불만 리뷰 시각·주제)에서 바로 센다. 외부 라이브러리 없음.
// 새로 등록한 가게는 리뷰가 0건일 수 있다: 기간이 비어도 'undefined' 를 찍지 않고, 차트·할 일은 짧은 빈 안내로.
// 리뷰 0건이면 '오늘 할 일' 아래 버튼이 다음에 할 일 두 개 ([리뷰 넣기] → 리뷰 분석의 리뷰 넣기 탭, [상권 분석 보기])
// 직접 등록한 가게는 브리핑에 상권 지표가 없을 수 있다(예시 가게용 '공통 업종 17~24시' 계산): 그때 상권 칸은 '없음' 대신 상권 분석으로 안내
import { useStore, openDrawer } from "../../state/store.js";
import { todosOf, staffOf } from "../../state/staff.js";
import { heroProblem, homeSnap, isOwnStore, snapValue, scopeNote } from "../../lib/domain.js";
import { currentStore } from "../../state/account.js";
import { go, navTo } from "../../lib/router.js";
import { PageHead, Panel, StatTile, TopicBar, Button } from "../../components/ui.jsx";
import { useFlow } from "./state.js";
import { runTodo, staffGo } from "./actions.js";
import { homeStats, keywordRows, hourChart, scopeChips } from "./calc.js";
import "./flow.css";

const Unit = ({ n }) => (n === undefined || n === null ? "–" : <>{n}<span className="flow-unit">건</span></>);

export default function Home() {
  const s = useStore();
  const busy = useFlow((f) => f.busy);
  const b = s.briefing;
  const stats = homeStats(b);
  const snap = homeSnap(b);
  const items = s.cards.length ? todosOf(s) : [];
  const left = items.filter((t) => t.st[0] !== "done").length;
  const title = !s.cards.length ? "사장님, 오늘 가게 현황이에요" : left ? `사장님, 오늘 처리할 일 ${left}가지` : "사장님, 오늘 할 일을 모두 끝냈어요";
  const failed = s.booted && !!s.bootError && !s.cards.length;
  const noBriefing = s.booted && !!s.bootError && !b;   // 브리핑을 못 받음: '정리하고 있어요'·'불러오는 중'으로 남기지 않음
  const startLabel = !s.booted ? "불러오는 중…" : s.bootError ? "불러오지 못했어요" : "무엇을 할까요?";
  const staff = staffOf(s);
  const noReviews = b?.counts?.review_count === 0;   // 새 가게: 리뷰 0건
  const period = b?.period?.start && b?.period?.end ? `${b.period.start} ~ ${b.period.end} · 리뷰는 합성 데이터` : "";
  const toMarket = !snap && !!b && isOwnStore(s.me);   // 직접 등록한 가게: 상권 숫자는 상권 분석 화면에
  const myArea = toMarket ? (currentStore(s.me) || {}).area_name : "";

  return (
    <div className="col wide flow-home">
      <div className="stack-8">
        <p className="small muted flow-eyebrow"><span>밤 11시 브리핑</span>{((!b && !noBriefing) || period) && <span>{b ? period : "불러오는 중…"}</span>}</p>
        <PageHead title={title} />
      </div>

      {/* 오늘의 핵심 문제: 카드 ⓐ가 가리키는 묶음. 시간대는 불만이 몰린 구간만 (상권 지표의 17~24시와 섞지 않음) */}
      <p className="flow-hero"><span className="flow-hero-label">오늘의 핵심 문제</span>
        <strong>{noBriefing ? "리뷰를 불러오지 못했어요" : !b ? "오늘 들어온 리뷰를 정리하고 있어요" : heroProblem(b)}</strong></p>

      <div className="tiles">
        <StatTile tint="green" icon="리뷰" label="리뷰" value={<Unit n={stats?.reviews} />} sub={stats?.reviewsSub} />
        <StatTile tint="mint" icon="불만" label="불만" value={<Unit n={stats?.complaints} />} sub={stats?.complaintsSub} />
        <StatTile tint="lime" icon="반복 불만" label="반복 불만" value={<Unit n={stats?.repeated} />} sub={stats?.repeatedSub} />
        {/* 범위(상권·업종·시간대)를 숫자 아래 칩으로 늘 붙인다: 서랍의 답(한 업종 하루 전체)과 범위가 달라 나란히 보면 모순처럼 보이므로 */}
        <StatTile tint="sage" icon="상권 매출" label="상권 저녁 매출"
          value={toMarket ? <button type="button" className="flow-tile-go" onClick={() => go("market")}>상권 분석에서 보기<span aria-hidden="true"> ›</span></button>
            : snap ? snapValue(snap) : "–"}
          sub={snap ? <ScopeMeta chips={scopeChips(snap)} /> : toMarket ? (myArea ? `${myArea} 상권` : "") : b ? "상권 지표 없음" : ""}
          title={snap ? `${snap.metric_name}. ${scopeNote(snap)}` : undefined} />
      </div>

      <div className="grid-2 flow-dash">
        <Panel title="오늘 할 일" titleId="flow-todo-title" sub={items.length ? `${items.length - left} / ${items.length} 끝` : ""}>
          <ol className="plain flow-todo">
            {!s.booted ? <li className="small muted">불러오는 중…</li>
              : failed ? <li className="small muted">불러오지 못했어요</li>
              : !items.length ? <li className="small muted">{noReviews ? "리뷰가 들어오면 할 일을 골라 드려요." : "오늘은 할 일이 없어요."}</li>
              : items.map((t) => {
                const mine = busy[t.cid] === `todo:${t.key}`;
                const urgent = t.urgent && t.st[0] !== "done";
                return (
                  <li key={t.key}>
                    <button type="button" className={["flow-todo-item", t.st[0], urgent && "urgent"].filter(Boolean).join(" ")}
                      disabled={!!busy[t.cid]} onClick={() => runTodo(t)}>
                      <span className="flow-todo-check" aria-hidden="true">{t.st[0] === "done" ? "✓" : ""}</span>
                      <span className="flow-todo-text">
                        <strong>{urgent && <span className="flow-urgent">급함</span>}{t.title}</strong>
                        <span className="small">{t.sub}</span>
                        <span className="small muted">{t.agent}</span>
                      </span>
                      <span className="flow-todo-st">{mine ? "만드는 중…" : t.st[1]}</span>
                    </button>
                  </li>
                );
              })}
          </ol>
          <div className="btn-row flow-todo-foot">
            {noReviews && !items.length ? (
              <>
                <Button variant="primary" onClick={() => navTo("analysis", "paste")}>리뷰 넣기</Button>
                <Button onClick={() => go("market")}>상권 분석 보기</Button>
              </>
            ) : (
              <Button variant="primary" disabled={!s.booted || !!s.bootError} onClick={() => go("cards")}>{startLabel}</Button>
            )}
          </div>
        </Panel>

        <Panel title="담당 비서 현황" titleId="flow-staff-title">
          <ul className="plain flow-staff">
            {staff.map((x) => (
              <li key={x.key}>
                <button type="button" className="flow-staff-go" onClick={() => staffGo(x.key)}>
                  <span className={`dot ${x.ok ? "ok" : "warn"}`} aria-hidden="true" />
                  <span className="flow-staff-av" aria-hidden="true">{x.name.slice(0, 1)}</span>
                  <span className="flow-staff-text"><b>{x.name}</b><span className="small muted">{x.text}</span></span>
                  <span className="flow-staff-arrow" aria-hidden="true">›</span>
                </button>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <div className="grid-2 flow-charts">
        <HourPanel b={b} />
        <TopicPanel b={b} />
      </div>

      {/* 입력칸처럼 보이는 줄 + 오른쪽 '묻기'. 누르면 서랍을 열기만 한다 (예시는 서랍이 답하는 첫 추천 질문) */}
      <button type="button" className="flow-ask" aria-controls="assistant" aria-expanded={s.drawerOpen} onClick={() => openDrawer(true)}>
        <span className="flow-ask-ph">AI에게 묻기 · 예) 우리 가게 상권 매출은 어때?</span>
        <span className="flow-ask-go" aria-hidden="true">묻기</span>
      </button>
    </div>
  );
}

// 상권 칸의 범위: 상권명 · 업종 · 시간대 칩 + 비교 기준 한 줄
function ScopeMeta({ chips }) {
  return (
    <>
      <span className="flow-scope">{chips.map((c, i) => <span key={`${i}-${c}`} className="flow-scope-chip">{c}</span>)}</span>
      <span className="flow-scope-base">전년 같은 분기 대비</span>
    </>
  );
}

// 불만 리뷰가 몰린 시간: 핵심 문제 묶음의 몰린 시간대는 빨간 막대, 같은 뜻을 글자로도 쓴다
function HourPanel({ b }) {
  const hc = b ? hourChart(b) : null;
  const empty = !!hc && hc.cols.every((c) => !c.n);   // 불만 리뷰가 없으면 빈 막대 대신 한 줄
  return (
    <Panel title="불만 리뷰가 몰린 시간" titleId="flow-hour-title" sub={empty ? undefined : hc?.note}>
      {empty ? <p className="small muted">불만 리뷰가 없어요.</p>
        : hc
        ? <div className="flow-hours" role="img" aria-label={hc.label}>
            {hc.cols.map((c) => (
              <div key={c.h} className={c.hot ? "flow-hc hot" : "flow-hc"}>
                <span className="flow-hc-n">{c.n || ""}</span>
                <span className="flow-hc-bar"><i style={{ height: `${c.height}%` }} /></span>
                <span className="flow-hc-h">{c.h}</span>
              </div>
            ))}
          </div>
        : <p className="small muted">불러오는 중…</p>}
    </Panel>
  );
}

// 주제별 불만: 상위 3개 + 그 밖. 핵심 문제 주제는 진한 빨강 (칭찬 주제는 브리핑에 없어 그리지 않음)
function TopicPanel({ b }) {
  const k = b ? keywordRows(b) : null;
  return (
    <Panel title="주제별 불만" titleId="flow-topic-title" sub={k?.rows.length ? `상위 ${k.rows.length}개` : undefined}
      actions={<a href="#/analysis" className="small">리뷰 분석 보기</a>}>
      {!k ? <p className="small muted">불러오는 중…</p>
        : !k.rows.length ? <p className="small muted">불만 리뷰가 없어요.</p>
        : <div className="stack-16">
            {k.rows.map((r) => <TopicBar key={r.topic} name={r.topic} value={`${r.n}건`} ratio={r.ratio} kind="complaint" hot={r.hot} />)}
            {!!k.rest.length && <p className="small muted">그 밖 {k.rest.length}개 주제: {k.rest.map((r) => `${r.topic} ${r.n}`).join(" · ")}</p>}
          </div>}
    </Panel>
  );
}
