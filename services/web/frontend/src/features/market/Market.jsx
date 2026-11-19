// 상권 분석 (#/market, 5차 회의 11/18). Figma 화면 11.
// ① 분석 조건(상권·업종·분기 + 우리 가게 기준으로 + AI에게 묻기) ② 핵심 지표 4칸 ③ 세부 탭 4개 ④ 옆 칸: 서울 열린데이터광장 실시간 최신화 · 우리 동네 문화행사.
// 숫자는 서울시 상권분석서비스 추정치이고 우리 가게 매출이 아니다. 서버 글은 JSX 로만 넣는다.
import { useEffect } from "react";
import { useStore, openDrawer } from "../../state/store.js";
import { Button, Notice, PageHead, Panel, StatTile, Tabs } from "../../components/ui.jsx";
import {
  MKV_TABS, useMarket, getMarket, marketOpen, setTab, markNav, apply, home, sync, compare, periodsOf, compareAreasOf,
  pickArea, pickIndustry, pickPeriod, pickCompareDistrict, pickCompareArea,
} from "./state.js";
import { barRows, metricValue, numKo, pctKo, qLabel, safeUrl, warningsOf, wonShort } from "./format.js";
import "./Market.css";

const TABS = [
  { id: "sales", label: "매출(시간대·요일·연령)" },
  { id: "stores", label: "점포·개폐업" },
  { id: "pop", label: "유동·배후인구·집객시설" },
  { id: "compare", label: "타 상권 1:1 비교" },
];
const STORE_KEYS = ["stores_total", "stores_general", "stores_franchise", "stores_opened", "stores_closed"];

// 고른 값이 목록에 없으면 브라우저처럼 고를 수 있는 첫 보기
const valueIn = (list, want, key, ok = () => true) => {
  if (list.some((x) => key(x) === want && ok(x))) return want;
  const first = list.find(ok);
  return first ? key(first) : "";
};

export default function Market() {
  const s = useMarket();
  const nav = useStore((st) => st.nav);

  useEffect(() => { marketOpen(); }, []);   // 화면을 처음 열 때 시작 (예전 route() 의 mkvOpen)

  // 다른 화면의 navTo("market", 탭): nav.seq 가 바뀔 때마다 한 번 (예전 mkvTab(sub, true))
  useEffect(() => {
    if (!nav || nav.name !== "market" || nav.seq === getMarket().navSeq) return;
    markNav(nav.seq);
    if (!MKV_TABS.includes(nav.sub)) return;
    setTab(nav.sub);
    document.getElementById(`mk-tab-${nav.sub}`)?.focus();
  }, [nav]);

  const locked = s.busy || !s.cond;
  const cand = (s.options && s.options.candidates) || [];
  const industries = s.industries || [];
  const area = valueIn(cand, s.pick.area, (a) => a.area_code, (a) => !a.selection_blocked_reason);
  const periods = periodsOf(s, area);
  const period = valueIn(periods, s.pick.period, (p) => p);
  const industry = valueIn(industries, s.pick.industry, (x) => x.code);
  const owner = `상권 분석 비서${s.storeLine ? ` · ${s.storeLine}` : ""}`;

  return (
    <div className="col wide mk">
      <PageHead owner={owner} title="상권 분석"
        sub="서울시 상권분석서비스 공식 자료로 우리 가게 주변 상권을 봐요. 상권·업종 전체의 추정치이고, 우리 가게 매출이 아니에요." />
      <Notice tone={s.warn ? "warn" : undefined} className="mk-state">{s.status}</Notice>

      <Panel title="분석 조건" titleId="mk-cond-title" sub={s.condLine} className="mk-cond">
        <div className="mk-cond-row">
          <label className="field mk-field"><span>상권</span>
            <select id="mk-area" value={area} disabled={locked} onChange={(e) => pickArea(e.target.value)}>
              {cand.map((a) => <option key={a.area_code} value={a.area_code} disabled={!!a.selection_blocked_reason}>{a.name}{a.relation === "inside" ? " (역 안쪽)" : ""}</option>)}
            </select>
          </label>
          <label className="field mk-field"><span>업종</span>
            <select id="mk-industry" value={industry} disabled={locked} onChange={(e) => pickIndustry(e.target.value)}>
              {industries.map((x) => <option key={x.code} value={x.code}>{x.name}</option>)}
            </select>
          </label>
          <label className="field mk-field"><span>분기</span>
            <select id="mk-period" value={period} disabled={locked} onChange={(e) => pickPeriod(e.target.value)}>
              {periods.map((p) => <option key={p} value={p}>{qLabel(p)}</option>)}
            </select>
          </label>
          <div className="btn-row mk-cond-btns">
            <Button variant="primary" disabled={locked} onClick={() => apply({ area, period, industry })}>이 조건으로 보기</Button>
            <Button disabled={locked} onClick={home}>우리 가게 기준으로</Button>
            <Button aria-controls="assistant" onClick={() => openDrawer(true)}>AI에게 묻기</Button>
          </div>
        </div>
      </Panel>

      <div className="mk-body">
        <div className="mk-main">
          <Tiles s={s} />
          <div className="mk-tabbar"><Tabs tabs={TABS} active={s.tab} onChange={setTab} idPrefix="mk" label="상권 세부 지표" /></div>
          <TabPanel id="sales" tab={s.tab}><SalesPanel s={s} /></TabPanel>
          <TabPanel id="stores" tab={s.tab}><StoresPanel s={s} /></TabPanel>
          <TabPanel id="pop" tab={s.tab}><PopPanel s={s} /></TabPanel>
          <TabPanel id="compare" tab={s.tab}><ComparePanel s={s} /></TabPanel>
        </div>
        <aside className="mk-side" aria-label="서울시 자료와 문화행사">
          <SeoulPanel s={s} />
          <EventsPanel s={s} />
        </aside>
      </div>
    </div>
  );
}

function TabPanel({ id, tab, children }) {
  return (
    <section id={`mk-panel-${id}`} className="panel mk-panel" role="tabpanel" aria-labelledby={`mk-tab-${id}`} tabIndex={0} hidden={tab !== id}>
      {children}
    </section>
  );
}

// 핵심 지표 4칸 (예전 mkvTiles). 자료를 받기 전에는 '–'
function Tiles({ s }) {
  const d = s.data, c = s.cond || {};
  const loaded = Object.keys(d).length > 0;
  const sales = d.sales && d.sales.total, stores = d.stores && d.stores.counts, pop = d.pop && d.pop.total;
  const yoy = ((d.yoy && d.yoy.metrics) || []).find((x) => x.key === "sales");
  return (
    <div className="tiles mk-tiles" role="group" aria-label="핵심 지표">
      <StatTile label="분기 추정매출" value={sales && typeof sales.value === "number" ? wonShort(sales.value) : "–"}
        sub={loaded ? `${c.period_label || qLabel(c.period)} · ${c.industry_name || ""}` : ""} />
      <StatTile label="전년 같은 분기 대비" value={yoy ? <span className={yoy.percent < 0 ? "mk-neg" : undefined}>{pctKo(yoy.percent)}</span> : "–"}
        sub={loaded ? (d.yoy && d.yoy.previous_period ? `${qLabel(d.yoy.previous_period)} 대비 추정매출` : "추정매출") : ""} />
      <StatTile label="같은 업종 점포" value={stores && stores.total ? numKo(stores.total.value, "개") : "–"}
        sub={stores ? `개업 ${numKo(stores.opened && stores.opened.value)} · 폐업 ${numKo(stores.closed && stores.closed.value)}` : ""} />
      <StatTile label="유동인구(상권 전체)" value={pop && typeof pop.value === "number" ? numKo(pop.value, "명") : "–"}
        sub={loaded ? "상권 전체 원천 지표" : ""} />
    </div>
  );
}

// 분포 막대 (예전 mkvBars)
function Bars({ dist }) {
  const rows = barRows(dist);
  if (!rows.length) return <p className="small muted">자료가 없어요.</p>;
  return (
    <ul className="plain mk-bars" aria-label={(dist && dist.label) || ""}>
      {rows.map((r, i) => (
        <li key={i}>
          <span className="mk-bar-l">{r.label}</span>
          <span className="mk-bar" aria-hidden="true"><span style={{ width: `${r.pct}%` }} /></span>
          <span className="mk-bar-v">{r.shown}</span>
        </li>
      ))}
    </ul>
  );
}

const Warnings = ({ x }) => warningsOf(x).map((w, i) => <p key={i} className="small muted">{w}</p>);
const Err = ({ x }) => (x && x.error ? <p className="small mk-err">{x.error}</p> : null);

// 전년 같은 분기와 비교 표 (예전 mkvChanges)
function Changes({ yoy, keys }) {
  const metrics = ((yoy && yoy.metrics) || []).filter((x) => !keys || keys.includes(x.key));
  if (!metrics.length) return null;
  return (
    <div className="mk-table-wrap">
      <table className="mk-table">
        <caption>{yoy.comparison_label || "전년 같은 분기와 비교"}</caption>
        <thead><tr><th scope="col">지표</th><th scope="col">{qLabel(yoy.previous_period)}</th><th scope="col">{qLabel(yoy.current_period)}</th><th scope="col">변화</th></tr></thead>
        <tbody>
          {metrics.map((x, i) => (
            <tr key={x.key || i}><th scope="row">{x.label}</th><td>{metricValue(x, x.previous)}</td><td>{metricValue(x, x.current)}</td>
              <td className={x.percent < 0 ? "mk-neg" : undefined}>{pctKo(x.percent)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SalesPanel({ s }) {
  const d = s.data;
  if (!Object.keys(d).length) return null;
  const x = d.sales || {}, dist = x.distributions || {};
  return (
    <>
      <Err x={x} />
      {x.total && <p className="mk-lead">분기 추정매출 <b>{wonShort(x.total.value)}</b> <span className="small muted">({numKo(x.total.value, "원")})</span></p>}
      <div className="mk-grid">
        <section><h3>시간대별</h3><Bars dist={dist.time} /></section>
        <section><h3>요일별</h3><Bars dist={dist.weekday} /></section>
        <section><h3>연령별</h3><Bars dist={dist.age} /></section>
      </div>
      <Changes yoy={d.yoy} keys={["sales"]} />
      <Warnings x={x} />
    </>
  );
}

function StoresPanel({ s }) {
  const d = s.data;
  if (!Object.keys(d).length) return null;
  const x = d.stores || {};
  const facts = Object.values(x.counts || {}).filter((c) => c && c.label);
  return (
    <>
      <Err x={x} />
      <ul className="plain mk-facts">
        {facts.length ? facts.map((c, i) => <li key={i}><span>{c.label}</span><b>{numKo(c.value, c.unit || "")}</b></li>)
          : <li className="small muted">자료가 없어요.</li>}
      </ul>
      <Changes yoy={d.yoy} keys={STORE_KEYS} />
      <Warnings x={x} />
    </>
  );
}

function PopPanel({ s }) {
  const d = s.data;
  if (!Object.keys(d).length) return null;
  const p = d.pop || {}, ctx = d.ctx || {}, pd = p.distributions || {};
  const vals = (ctx.values || []).filter((v) => v && v.label && !/기준분기|분석 선택/.test(v.label));
  return (
    <>
      <Err x={p} />
      {p.total && <p className="mk-lead">유동인구(상권 전체 원천 지표) <b>{numKo(p.total.value, "명")}</b></p>}
      <div className="mk-grid">
        <section><h3>시간대별 유동인구</h3><Bars dist={pd.time} /></section>
        <section><h3>연령별 유동인구</h3><Bars dist={pd.age} /></section>
        <section>
          <h3>배후인구·집객시설</h3>
          {ctx.status === "available"
            ? <ul className="plain mk-facts">{vals.map((v, i) => <li key={i}><span>{v.label}</span><b>{typeof v.value === "number" ? numKo(v.value, v.unit || "") : String(v.value)}</b></li>)}</ul>
            : <p className="small muted">{ctx.error || "이 상권의 직장인구·상주인구·집객시설 자료가 아직 없어요."}</p>}
          {ctx.period_note && <p className="small muted">{ctx.period_note}</p>}
        </section>
      </div>
      <Changes yoy={d.yoy} keys={["floating_population"]} />
      <Warnings x={p} />
      <Warnings x={ctx} />
    </>
  );
}

// 타 상권 1:1 비교 (예전 mkvCompareOptions·mkvCompareAreas·mkvCompare)
function ComparePanel({ s }) {
  const districts = (s.cmp && s.cmp.districts) || [];
  const list = compareAreasOf(s);
  const ok = (a) => a.selectable !== false;
  const area = valueIn(list, s.cmpPick.area, (a) => a.area_code, ok);
  const r = s.cmpResult;
  return (
    <>
      <div className="mk-cond-row">
        <label className="field mk-field"><span>비교할 구</span>
          <select id="mk-cmp-district" value={s.cmpPick.district} onChange={(e) => pickCompareDistrict(e.target.value)}>
            {districts.map((x) => <option key={x.code} value={x.code}>{x.name}</option>)}
          </select>
        </label>
        <label className="field mk-field"><span>비교할 상권</span>
          <select id="mk-cmp-area" value={area} onChange={(e) => pickCompareArea(e.target.value)}>
            {list.map((a) => <option key={a.area_code} value={a.area_code} disabled={!ok(a)}>{a.name}{a.type ? ` · ${a.type}` : ""}</option>)}
          </select>
        </label>
        <Button variant="primary" disabled={s.cmpRunning || !list.some(ok)} onClick={() => compare(area)}>비교하기</Button>
      </div>
      <div className="mk-cmp-result">
        {r.kind === "table" ? <CompareTable r={r.r} cond={r.cond} />
          : <p className={r.kind === "error" ? "small mk-err" : "small muted"}>{r.text}</p>}
      </div>
    </>
  );
}

function CompareTable({ r, cond }) {
  return (
    <>
      <div className="mk-table-wrap">
        <table className="mk-table">
          <caption>{qLabel(cond.period)} · {cond.industry_name || ""}</caption>
          <thead><tr><th scope="col">지표</th><th scope="col">{(r.base_area || {}).name || "우리 상권"}</th><th scope="col">{(r.comparison_area || {}).name || "비교 상권"}</th><th scope="col">차이</th></tr></thead>
          <tbody>
            {(r.metrics || []).map((x, i) => (
              <tr key={x.key || i}><th scope="row">{x.label}</th><td>{metricValue(x, x.base)}</td><td>{metricValue(x, x.comparison)}</td><td>{pctKo(x.percent)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <Warnings x={r} />
    </>
  );
}

function SeoulPanel({ s }) {
  return (
    <Panel title="서울 열린데이터광장 실시간 최신화" titleId="mk-seoul-title" className="mk-seoul">
      <p className="small">{s.dataLine}</p>
      <Button size="small" className="mk-sync" disabled={s.syncing} onClick={sync}>
        {s.syncing ? "서울시에 확인하는 중…" : "서울시 최신 데이터 확인·동기화"}
      </Button>
      <p className={["small", "mk-sync-result", s.syncWarn && "warn"].filter(Boolean).join(" ")} role="status" aria-live="polite">{s.syncLine}</p>
    </Panel>
  );
}

function EventsPanel({ s }) {
  const list = s.eventsList;
  return (
    <Panel title="우리 동네 실시간 문화행사" titleId="mk-events-title" sub={s.eventsNote} className="mk-events-panel">
      <ul className="plain mk-events">
        {s.eventsMsg ? <li className="small muted">{s.eventsMsg}</li>
          : list === null ? <li className="small muted">불러오는 중…</li>
            : list.length ? list.map((ev, i) => <EventItem key={i} ev={ev} />)
              : <li className="small muted">지금 열리는 행사가 없어요.</li>}
        {!s.eventsMsg && list !== null && s.eventsNotice && <li className="small muted">{s.eventsNotice}</li>}
      </ul>
    </Panel>
  );
}

function EventItem({ ev }) {
  const link = safeUrl(ev.link);
  const when = [ev.start, ev.end].filter(Boolean).join(" ~ ");
  const meta = [ev.category, ev.place, when, ev.is_free === true ? "무료" : ev.is_free === false ? "유료" : ""].filter(Boolean).join(" · ");
  return (
    <li>
      <b>{link ? <a href={link} target="_blank" rel="noopener">{ev.title}<span className="sr"> (새 탭)</span></a> : ev.title}</b>
      <span className="small muted">{meta}</span>
    </li>
  );
}
