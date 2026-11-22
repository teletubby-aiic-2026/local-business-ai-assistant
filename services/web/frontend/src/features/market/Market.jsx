// 상권 분석 (#/market, 5차 회의 11/18 · 6차 회의 11/20 Figma '06 설계 기준 화면' F1).
// 위에서부터 ① 머리(상권 분석 비서 · 제목 · 고지 한 줄 · AI에게 묻기) ② 분석 조건(상권·업종·분기 + 이 조건으로 보기, 아래 줄에 지금 조건 · 우리 가게 기준으로)
// ③ 지도(고른 상권 · 주변 상권 경계 · 가게 위치, 주변 상권을 누르면 비교 탭) ④ 핵심 지표 4칸 ⑤ 세부 탭 4개 ⑥ 서울시 자료 최신화 · 우리 동네 문화행사.
// 숫자는 서울시 상권분석서비스 추정치이고 우리 가게 매출이 아니다 (머리 한 줄로만 알린다). 서버 글은 JSX 로만 넣는다.
import { useEffect, useMemo } from "react";
import { useStore, focusOrOpenDrawer } from "../../state/store.js";
import { Button, Notice, PageHead, Panel, StatTile, Tabs } from "../../components/ui.jsx";
import NaverMap from "../../components/NaverMap.jsx";
import {
  MKV_TABS, useMarket, getMarket, marketOpen, setTab, markNav, apply, home, sync, compare, compareWith, revealCompare, periodsOf, compareAreasOf,
  pickArea, pickIndustry, pickPeriod, pickCompareDistrict, pickCompareArea,
} from "./state.js";
import { barRows, distWarningsOf, hasFacility, isRawAge, metricValue, numKo, pctKo, qLabel, safeUrl, warningsOf, wonShort } from "./format.js";
import "./Market.css";

const TABS = [
  { id: "sales", label: "매출(시간대·요일·연령)" },
  { id: "stores", label: "점포·개폐업" },
  { id: "pop", label: "유동·배후인구·집객시설" },
  { id: "compare", label: "타 상권 1:1 비교" },
];
const STORE_KEYS = ["stores_total", "stores_general", "stores_franchise", "stores_opened", "stores_closed"];
// 이 화면의 핵심 고지 (출처·추정치·우리 가게 매출 아님). 화면 머리에 이 한 줄만 둔다 (Figma F1 문구)
const MK_NOTICE = "서울시 상권분석서비스 공식 자료로 우리 가게 주변 상권을 봐요. 상권·업종 전체의 추정치이고, 우리 가게 매출이 아니에요.";
// 11/22 QA: 홈 -19.31%와 이 화면 타일의 변화율이 달라 '둘 중 하나가 오류'로 읽혔다. 둘 다 맞고 범위가 달라서라는 한 줄
const MK_SCOPE_NOTE = "홈·종합 리포트의 상권 저녁 매출은 공통 업종·17~24시 기준이라 이 숫자와 다를 수 있어요.";
// 11/22 QA: '장승배기역 4번' 상권에 지하철역 0개처럼 이름과 시설 수가 어긋나 보였다
const MK_FACILITY_NOTE = "상권 이름에 든 역·학교가 상권 경계 안에 있다는 뜻은 아니에요. 시설 수는 서울시 집객시설 자료 그대로예요.";
// 11/22 QA: 유동 탭 '연령대 10'과 매출 탭 '10대'가 달라 보였다. 서버는 범위를 확인하지 못해 '10대'로 바꾸지 않으므로 표기는 두고 뜻만 푼다
const MK_RAW_AGE_NOTE = "'원천 분류'는 서울시 자료의 연령 구분 이름 그대로라는 뜻이에요. 매출 탭의 '10대'와 범위가 같은지는 확인되지 않았어요.";

// 고른 값이 목록에 없으면 브라우저처럼 고를 수 있는 첫 보기
const valueIn = (list, want, key, ok = () => true) => {
  if (list.some((x) => key(x) === want && ok(x))) return want;
  const first = list.find(ok);
  return first ? key(first) : "";
};

export default function Market() {
  const s = useMarket();
  const nav = useStore((st) => st.nav);
  const drawerOpen = useStore((st) => st.drawerOpen);

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
  // 주소·동네로 등록한 가게는 이 화면에서 업종을 바꿀 수 없다: 칸을 처음부터 잠그고 옆에 까닭 한 줄 (누른 뒤에야 알리지 않게)
  const industryNote = s.fixedIndustry ? `${s.fixedIndustry}로 등록한 가게는 업종을 프로필의 '정보 고치기'에서 바꿔요.` : "";
  // 새 조건의 숫자를 불러오는 동안: 보던 숫자는 흐리게 (위 안내 줄이 '바꾸고 있어요'를 말함)
  const refreshing = s.busy && Object.keys(s.data).length > 0;

  return (
    <div className="col wide mk">
      <PageHead owner={owner} title="상권 분석" sub={MK_NOTICE}
        actions={<Button aria-controls="assistant" aria-expanded={drawerOpen} onClick={focusOrOpenDrawer}>AI에게 묻기</Button>} />
      <Notice tone={s.warn ? "warn" : undefined} className="mk-state">{s.status}</Notice>

      <section className="panel mk-cond" aria-labelledby="mk-cond-title">
        <h2 id="mk-cond-title" className="sr">분석 조건</h2>
        <div className="mk-cond-row">
          <label className="field mk-field"><span>상권</span>
            <select id="mk-area" value={area} disabled={locked} onChange={(e) => pickArea(e.target.value)}>
              {cand.map((a) => <option key={a.area_code} value={a.area_code} disabled={!!a.selection_blocked_reason}>{a.name}{a.relation === "inside" ? " (역 안쪽)" : ""}</option>)}
            </select>
          </label>
          <label className="field mk-field"><span>업종</span>
            <select id="mk-industry" value={industry} disabled={locked || !!industryNote} aria-describedby={industryNote ? "mk-industry-note" : undefined}
              onChange={(e) => pickIndustry(e.target.value)}>
              {industries.map((x) => <option key={x.code} value={x.code}>{x.name}</option>)}
            </select>
          </label>
          <label className="field mk-field"><span>분기</span>
            <select id="mk-period" value={period} disabled={locked} onChange={(e) => pickPeriod(e.target.value)}>
              {periods.map((p) => <option key={p} value={p}>{qLabel(p)}</option>)}
            </select>
          </label>
          <Button variant="primary" className="mk-apply" disabled={locked} onClick={() => apply({ area, period, industry })}>이 조건으로 보기</Button>
        </div>
        {industryNote && <p id="mk-industry-note" className="small muted mk-cond-note">{industryNote}</p>}
        <div className="mk-cond-now small">
          {s.condLine && <span className="muted">지금 보는 조건: <span className="mk-cond-line">{s.condLine}</span></span>}
          <Button variant="text" size="small" disabled={locked} onClick={home}>우리 가게 기준으로</Button>
        </div>
      </section>

      {s.options && <MapPanel s={s} />}

      <Tiles s={s} dim={refreshing} />

      <div className={["mk-main", refreshing && "mk-dim"].filter(Boolean).join(" ")} aria-busy={refreshing || undefined}>
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
  );
}

// 지도 출처 한 줄 (analysis-options 의 scope): "네이버 지도 · 2023년 공개 상권 경계"
export function mapSource(scope) {
  const y = /^(\d{4})/.exec(String((scope && scope.boundary_publication_date) || ""));
  return `네이버 지도 · ${y ? `${y[1]}년 ` : ""}공개 상권 경계`;
}

// 지도 목록의 짧은 덧말: 지금 보는 상권 · 가게 위치가 안에 있음 · 거리 · 비교할 수 없음
function areaNote(a, selected) {
  if (selected) return "지금 보는 상권";
  if (a.selection_blocked_reason) return "비교할 수 없음";
  if (a.relation === "inside" || a.relation === "boundary") return "가게 위치 포함";
  return typeof a.distance_m === "number" ? `${numKo(a.distance_m)}m` : "";
}

// ③ 지도: 고른 상권 = 지금 분석 중인 상권, 주변 상권 = 나머지 후보, 마커 = 가게 위치. 주변 상권을 누르면 비교 탭에서 그 상권을 고름
function MapPanel({ s }) {
  const here = s.cond && s.cond.area_code;
  const areas = useMemo(() => ((s.options && s.options.candidates) || []).map((a) => ({
    id: a.area_code, name: a.name, geometry: a.geometry, kind: a.area_code === here ? "selected" : "nearby",
    disabled: !!a.selection_blocked_reason, note: areaNote(a, a.area_code === here),
  })), [s.options, here]);
  const place = s.place;
  const marker = useMemo(() => (place ? { lat: place.lat, lng: place.lng, title: `가게 위치${place.label ? ` · ${place.label}` : ""}` } : null), [place]);
  const nearby = areas.some((a) => a.kind === "nearby");
  const pick = (id) => {
    if (!id || id === here) return;
    compareWith(id);
    // 탭에 포커스만 주면 탭이 이미 보일 때 화면이 그대로라 고장처럼 보였다 (11/22 QA): 비교 칸까지 내려 준다
    document.getElementById("mk-tab-compare")?.focus({ preventScroll: true });
    revealCompare();
  };
  return (
    <Panel title="지도" titleId="mk-map-title" sub={mapSource(s.options && s.options.scope)} className="mk-map">
      <NaverMap className="mk-nmap" marker={marker} areas={areas} onAreaClick={pick} fit="areas" zoom={16}
        label="상권 경계 지도" listLabel={nearby ? "주변 상권 (누르면 비교)" : "지도의 상권"}>
        <ul className="nmap-legend" aria-label="지도 범례">
          {marker && <li className="nmap-only"><span className="nmap-key pin" aria-hidden="true" />가게 위치</li>}
          <li><span className="nmap-key selected" aria-hidden="true" />고른 상권</li>
          {nearby && <li><span className="nmap-key nearby" aria-hidden="true" />주변 상권 (누르면 비교)</li>}
        </ul>
      </NaverMap>
    </Panel>
  );
}

function TabPanel({ id, tab, children }) {
  return (
    <section id={`mk-panel-${id}`} className="panel mk-panel" role="tabpanel" aria-labelledby={`mk-tab-${id}`} tabIndex={0} hidden={tab !== id}>
      {children}
    </section>
  );
}

// 핵심 지표 4칸 (예전 mkvTiles). 자료를 받기 전에는 '–'. 라벨(분기·업종)은 숫자와 같은 조건(dataCond)으로
function Tiles({ s, dim }) {
  const d = s.data, c = s.dataCond || {};
  const loaded = Object.keys(d).length > 0;
  const sales = d.sales && d.sales.total, stores = d.stores && d.stores.counts, pop = d.pop && d.pop.total;
  const yoy = ((d.yoy && d.yoy.metrics) || []).find((x) => x.key === "sales");
  // 변화율의 범위(선택 업종 · 분기 전체)를 sub 에 적는다: 홈 지표(공통 업종 · 17~24시)와 다른 까닭이 숫자 옆에 보이게 (11/22 QA)
  const yoyScope = "선택 업종 · 분기 전체 추정매출";
  return (
    <>
      <div className={["tiles mk-tiles", dim && "mk-dim"].filter(Boolean).join(" ")} role="group" aria-label="핵심 지표" aria-busy={dim || undefined}>
        <StatTile label="분기 추정매출" value={sales && typeof sales.value === "number" ? wonShort(sales.value) : "–"}
          sub={loaded ? `${c.period_label || qLabel(c.period)} · ${c.industry_name || ""}` : ""} />
        <StatTile label="전년 같은 분기 대비" value={yoy ? <span className={yoy.percent < 0 ? "mk-neg" : undefined}>{pctKo(yoy.percent)}</span> : "–"}
          sub={loaded ? (d.yoy && d.yoy.previous_period ? `${qLabel(d.yoy.previous_period)} 대비 · ${yoyScope}` : yoyScope) : ""} />
        <StatTile label="같은 업종 점포" value={stores && stores.total ? numKo(stores.total.value, "개") : "–"}
          sub={stores ? `개업 ${numKo(stores.opened && stores.opened.value)} · 폐업 ${numKo(stores.closed && stores.closed.value)}` : ""} />
        <StatTile label="유동인구" value={pop && typeof pop.value === "number" ? numKo(pop.value, "명") : "–"}
          sub={loaded ? "상권 전체 원천 지표" : ""} />
      </div>
      {loaded && <p className="small muted mk-tiles-note">{MK_SCOPE_NOTE}</p>}
    </>
  );
}

// 분포 막대 (예전 mkvBars). 그 분포의 경고(예: 시간대 구간 길이가 다름)는 막대 바로 아래에 (11/22 QA: 00~06시가 1등처럼 보였다)
function Bars({ dist }) {
  const rows = barRows(dist);
  if (!rows.length) return <p className="small muted">자료가 없어요.</p>;
  return (
    <>
      <ul className="plain mk-bars" aria-label={(dist && dist.label) || ""}>
        {rows.map((r, i) => (
          <li key={i}>
            <span className="mk-bar-l">{r.label}</span>
            <span className="mk-bar" aria-hidden="true"><span style={{ width: `${r.pct}%` }} /></span>
            <span className="mk-bar-v">{r.shown}</span>
          </li>
        ))}
      </ul>
      <Warnings x={dist} />
    </>
  );
}

// skip: 막대 아래에 이미 보인 문장 (같은 문장이 두 번 나오지 않게)
const Warnings = ({ x, skip }) => warningsOf(x, skip).map((w, i) => <p key={i} className="small muted">{w}</p>);
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
      <Warnings x={x} skip={distWarningsOf(dist)} />
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
        <section>
          <h3>연령별 유동인구</h3>
          <Bars dist={pd.age} />
          {isRawAge(pd.age) && <p className="small muted">{MK_RAW_AGE_NOTE}</p>}
        </section>
        <section>
          <h3>배후인구·집객시설</h3>
          {ctx.status === "available"
            ? <ul className="plain mk-facts">{vals.map((v, i) => <li key={i}><span>{v.label}</span><b>{typeof v.value === "number" ? numKo(v.value, v.unit || "") : String(v.value)}</b></li>)}</ul>
            : <p className="small muted">{ctx.error || "이 상권의 직장인구·상주인구·집객시설 자료가 아직 없어요."}</p>}
          {ctx.status === "available" && hasFacility(vals) && <p className="small muted">{MK_FACILITY_NOTE}</p>}
          {ctx.period_note && <p className="small muted">{ctx.period_note}</p>}
        </section>
      </div>
      <Changes yoy={d.yoy} keys={["floating_population"]} />
      <Warnings x={p} skip={distWarningsOf(pd)} />
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
      <div id="mk-cmp-form" className="mk-cond-row">
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
    <Panel title="서울시 자료 최신화" titleId="mk-seoul-title" className="mk-seoul">
      <p className="small">{s.dataLine}</p>
      <Button size="small" className="mk-sync" disabled={s.syncing} onClick={sync}>
        {s.syncing ? "서울시에 확인하는 중…" : "최신 자료 확인·동기화"}
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
