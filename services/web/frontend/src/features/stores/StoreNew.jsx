// A4 새 가게 등록 (Figma '06 설계 기준 화면' A4) · 가게 정보 고치기 (11/20, 6차 회의 ③).
// 오는 길: 회원가입 직후(mode "signup"), 가게 선택·프로필의 '+ 새 가게 등록'(mode "add"), 프로필의 '정보 고치기'(mode "edit", storeId).
// 구역 세 개: ① 가게 기본 정보(이름·업종·운영 상태·배달 채널) ② 위치와 상권(주소로 찾기 또는 가까운 역 → 지도 → 상권 라디오) ③ 메뉴와 가격.
// - 위치가 정해지고 업종이 있으면 상권 서비스에 위치를 알리고 상권 후보를 받는다 (storeApi.js resolveAreas). 지도가 안 떠도 라디오로 고른다.
// - 등록: POST /api/account/stores → 가게 선택의 [이 가게 열기]와 같은 openStore(POST /api/auth/store → 가게 자료 → 메인 화면 홈).
// - 고치기: GET 으로 채우고 바뀐 칸만 PATCH → 프로필. 위치·상권을 바꾸지 않았으면 상권 서비스에 다시 묻지 않는다.
// 입력은 화면에만 있다 (새로고침하면 사라짐, 임시 저장 없음). 위쪽 줄은 features/account/Stage.jsx 의 StageFrame
import { useEffect, useMemo, useRef, useState } from "react";
import { getState, useStore } from "../../state/store.js";
import { goPick, goProfile } from "../../state/stage.js";
import { acctLoad, storeChanged } from "../../state/boot.js";
import { openStore } from "../../state/account.js";
import { later } from "../../lib/focus.js";
import { Button, Icon } from "../../components/ui.jsx";
import NaverMap, { locationPoint } from "../../components/NaverMap.jsx";
import { StageFrame, StageTitle, WhoText } from "../account/Stage.jsx";
import {
  CHANNELS, MENU_MAX, NAME_MAX, QUERY_MAX, QUERY_MIN, areaRows, areaSub, checkMenus, createStore, defaultArea, errorField, getStore,
  lineOf, locationBody, marketOptions, patchStore, periodLabel, plainMessage, resolveAreas, searchAddress, stationsOf, storePatch,
} from "./storeApi.js";
import "./stores.css";

const LEAD = "여기 적은 정보로 홍보글의 메뉴를 점검하고, 상권 자료를 골라요.";
const START_TEXT = "새 가게에는 아직 리뷰가 없어요. 등록을 마치면 리뷰 넣기(붙여넣기·캡처)부터 안내하고, 상권 분석은 바로 볼 수 있어요.";
const LOOKUP_OFF = "주소를 찾지 못했어요. 가까운 역으로 골라 주세요.";
const EXAMPLES = [["제육볶음 정식", "9500"], ["된장찌개", "8000"], ["김치찌개", "8500"]];

export default function StoreNew({ mode = "add", storeId }) {
  const me = useStore((s) => s.me);
  const from = useStore((s) => s.storeNewFrom);
  const edit = mode === "edit";
  const [opts, setOpts] = useState(null);
  const [saved, setSaved] = useState(edit ? undefined : null);   // 고치기: undefined 불러오는 중
  const [loadErr, setLoadErr] = useState("");
  const [attempt, setAttempt] = useState(0);
  const back = () => (from === "profile" ? goProfile() : goPick());

  useEffect(() => {
    let alive = true;
    setLoadErr("");
    const store = edit
      ? (storeId ? getStore(storeId).then((r) => (r && r.store) || Promise.reject(new Error("가게 정보를 읽지 못했어요.")))
        : Promise.reject(new Error("고칠 가게를 찾지 못했어요.")))
      : Promise.resolve(null);
    Promise.all([marketOptions(), store])
      .then(([o, st]) => { if (alive) { setOpts(o); setSaved(st); } })
      .catch((e) => { if (alive && !e.authHandled) setLoadErr(e.message || "불러오지 못했어요."); });
    return () => { alive = false; };
  }, [attempt]);   // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <StageFrame right={<><WhoText me={me} /><Button size="small" onClick={goPick}>가게 선택으로</Button></>}>
      <div className="stage-col sn">
        <header className="stack-8 sn-head">
          {mode === "signup" && <span className="badge brand sn-step">가게 등록 2 / 2</span>}
          <StageTitle>{edit ? "가게 정보 고치기" : "새 가게 등록"}</StageTitle>
          <p className="muted">{edit ? LEAD : `${LEAD} 나중에 프로필에서 고칠 수 있어요.`}</p>
        </header>
        {loadErr ? (
          <div className="notice bad" role="alert">
            <span>{edit ? "가게 정보를" : "업종·역 목록을"} 불러오지 못했어요. {loadErr}</span>
            <span className="btn-row"><Button size="small" onClick={() => setAttempt((n) => n + 1)}>다시 시도</Button><Button size="small" onClick={back}>돌아가기</Button></span>
          </div>
        ) : !opts || saved === undefined ? (
          <p className="muted" role="status">불러오는 중…</p>
        ) : (
          <StoreForm mode={mode} opts={opts} saved={saved} onCancel={back} />
        )}
      </div>
    </StageFrame>
  );
}

// 메뉴 줄 {key, name, price, ph?}
let menuKey = 0;
const menuRow = (name = "", price = "", ph = null) => ({ key: `m${++menuKey}`, name, price: price === "" ? "" : String(price), ph });
function initMenus(saved) {
  if (saved) return (saved.menus || []).map((m) => menuRow(m.name, m.price));
  return EXAMPLES.map(([n, p]) => menuRow("", "", [n, p]));
}

function StoreForm({ mode, opts, saved, onCancel }) {
  const edit = mode === "edit";
  const savedLoc = (saved && saved.location) || null;
  const savedArea = (saved && saved.area) || null;
  const hasSaved = !!(savedLoc && savedArea && savedArea.area_code);
  const [name, setName] = useState((saved && saved.name) || "");
  const [industry, setIndustry] = useState((saved && saved.industry_code) || "");
  const [status, setStatus] = useState((saved && saved.business_status) || "operating");
  const [channels, setChannels] = useState(() => ((saved && saved.channels) || []).filter((c) => CHANNELS.some((x) => x.code === c)));
  const [menus, setMenus] = useState(() => initMenus(saved));
  // 위치: source 'saved'(고치기, 저장한 위치 그대로) · 'picked'(이 화면에서 고름) · null(아직)
  const [locSource, setLocSource] = useState(hasSaved ? "saved" : null);
  const [pickerOpen, setPickerOpen] = useState(!hasSaved);
  const [method, setMethod] = useState(savedLoc && savedLoc.kind === "station" ? "station" : "address");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState(null);            // 주소 찾기 응답 또는 {error}
  const [searching, setSearching] = useState(false);
  const [addrId, setAddrId] = useState("");
  const [line, setLine] = useState("");
  const [stationId, setStationId] = useState("");
  const [picked, setPicked] = useState(null);            // {body(상권 서비스에 보낼 location), label, point, fallback}
  // 상권
  const [market, setMarket] = useState({ state: "idle", rows: [] });   // idle · loading · ready · error
  const [area, setArea] = useState(hasSaved ? savedArea.area_code : "");
  const [areaNote, setAreaNote] = useState("");
  const [retry, setRetry] = useState(0);
  // 저장
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [created, setCreated] = useState(null);          // 등록은 됐는데 가게 열기가 실패: 다시 누르면 열기만
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const industryName = (opts.industries.find((x) => x.code === industry) || {}).name || "";
  const usingSaved = locSource === "saved" && industry === ((saved && saved.industry_code) || "");
  const savedStation = !!(savedLoc && savedLoc.kind === "station" && savedLoc.station_id);
  // 상권 서비스에 보낼 위치: 이 화면에서 고른 위치, 또는 (고치기에서 업종만 바꿨고 역으로 등록한 가게면) 저장한 역
  const marketLoc = !industry ? null
    : locSource === "picked" && picked ? picked.body
    : locSource === "saved" && !usingSaved && savedStation ? { kind: "station", station_id: savedLoc.station_id }
    : null;
  // 고치기에서 업종을 바꿨는데 주소로 등록한 가게: 주소를 다시 찾아야 새 업종의 상권 자료를 확인할 수 있다
  const needRepick = locSource === "saved" && !!industry && !usingSaved && !savedStation;
  const reqKey = marketLoc ? JSON.stringify([marketLoc, industry]) : "";

  const clearErr = (...keys) => setErrors((e) => (keys.some((k) => e[k]) ? Object.fromEntries(Object.entries(e).filter(([k]) => !keys.includes(k))) : e));
  const focusId = (id) => later(() => document.getElementById(id)?.focus());

  // 위치·업종이 바뀌면 상권 후보를 다시 받는다. 늦게 온 지난 응답은 버린다 (gen)
  const gen = useRef(0);
  useEffect(() => {
    const my = ++gen.current;
    if (!reqKey) { setMarket({ state: "idle", rows: [] }); return; }
    setMarket({ state: "loading", rows: [] });
    setAreaNote("");
    resolveAreas({ location: marketLoc, industry_code: industry, business_status: status }, () => my === gen.current && alive.current)
      .then((r) => {
        if (my !== gen.current || !alive.current) return;
        const rows = areaRows(r.candidates);
        setMarket({ state: "ready", rows, loc: r.location, notice: r.notice, message: rows.length ? "" : r.message });
        setArea((prev) => defaultArea(rows, prev));
      })
      .catch((e) => {
        if (e.stale || my !== gen.current || !alive.current) return;
        if (!e.authHandled) setMarket({ state: "error", rows: [], message: plainMessage(e.message) });
      });
  }, [reqKey, retry]);   // eslint-disable-line react-hooks/exhaustive-deps

  // 상권 라디오 (저장한 상권 그대로면 그 한 줄)
  const rows = usingSaved
    ? [{ code: savedArea.area_code, name: savedArea.name, type: "", relation: "", distance: null, blocked: "", geometry: null,
        period: savedArea.period ? { code: savedArea.period, label: periodLabel(savedArea.period) } : null }]
    : market.rows;
  const chosen = rows.find((r) => r.code === area && !r.blocked) || null;
  const point = usingSaved || (locSource === "saved" && !picked) ? locationPoint(savedLoc)
    : locationPoint(market.state === "ready" && market.loc) || (picked && picked.point) || null;
  const placeLabel = locSource === "saved" ? (savedLoc && savedLoc.label) || ""
    : (market.state === "ready" && market.loc && (market.loc.label || market.loc.name)) || (picked && picked.label) || "";

  // ── 기본 정보 ──
  function changeIndustry(code) {
    setIndustry(code);
    clearErr("industry", "area");
    if (locSource !== "saved") return;
    if (code === saved.industry_code) { setArea(savedArea.area_code); return; }
    if (!savedStation && code) {   // 주소로 등록한 가게: 주소를 다시 찾게
      setArea("");
      setPickerOpen(true);
      setMethod("address");
      if (!query) setQuery((savedLoc && (savedLoc.road_address || savedLoc.label)) || "");
    }
  }
  const toggleChannel = (code) => { setChannels((cs) => (cs.includes(code) ? cs.filter((c) => c !== code) : [...cs, code])); clearErr("channels"); };

  // ── 위치 ──
  function takePlace(next) {
    setPicked(next);
    setLocSource("picked");
    clearErr("location", "area");
  }
  async function onSearch() {
    if (searching) return;
    const q = query.trim();
    if (q.length < QUERY_MIN) { setErrors((e) => ({ ...e, location: "주소를 2자 이상 적어 주세요." })); focusId("sn-addr"); return; }
    clearErr("location");
    setSearching(true); setSearch(null); setAddrId("");
    try {
      const r = await searchAddress(q.slice(0, QUERY_MAX));
      if (!alive.current) return;
      setSearch(r || {});
      const ok = ((r && r.candidates) || []).filter((c) => c && c.in_seoul);
      if (r && r.status === "address_candidate" && ok.length === 1) pickAddress(r, ok[0]);   // 서울 주소 하나로 확정된 답이면 바로 고름
    } catch (e) {
      if (alive.current && !e.authHandled) setSearch({ error: plainMessage(e.message) });
    } finally { if (alive.current) setSearching(false); }
  }
  function pickAddress(r, c) {
    setAddrId(c.id);
    takePlace({ body: { kind: "address", search_id: r.search_id, candidate_id: c.id }, label: c.label || c.road_address || "",
      point: locationPoint(c), fallback: { kind: "address", label: c.label, road_address: c.road_address, latitude: c.latitude, longitude: c.longitude } });
  }
  function pickStation(id) {
    setStationId(id);
    const st = opts.stations.find((s) => s.id === id);
    if (!st) return;
    takePlace({ body: { kind: "station", station_id: st.id }, label: st.name, point: locationPoint(st),
      fallback: { kind: "station", label: st.name, station_id: st.id, road_address: st.road_address, latitude: st.latitude, longitude: st.longitude, district_name: st.district_name } });
  }
  function keepSavedPlace() {   // 고치기: 위치를 바꾸지 않기
    setPickerOpen(false); setPicked(null); setSearch(null); setAddrId(""); setStationId(""); setLine("");
    setLocSource("saved");
    if (industry === saved.industry_code) setArea(savedArea.area_code);
    clearErr("location", "area");
    focusId("sn-loc-change");
  }
  function openPicker() {
    setPickerOpen(true);
    if (savedStation && !line) setLine(lineOf(opts.stations.find((s) => s.id === savedLoc.station_id), opts.lines));
    focusId(method === "station" ? "sn-line" : "sn-addr");
  }
  function chooseArea(code) {
    const r = rows.find((x) => x.code === code);
    if (!r) return;
    if (r.blocked) { setAreaNote(`${r.name}: ${r.blocked}`); return; }
    setArea(code); setAreaNote(""); clearErr("area");
  }

  // ── 메뉴 ──
  const setMenu = (key, patch) => {
    setMenus((ms) => ms.map((m) => (m.key === key ? { ...m, ...patch } : m)));
    setErrors((e) => (e.menus && e.menus[key] ? { ...e, menus: { ...e.menus, [key]: undefined } } : e));
  };
  function addMenu() {
    if (menus.length >= MENU_MAX) return;
    const row = menuRow();
    setMenus((ms) => [...ms, row]);
    focusId(`sn-menu-name-${row.key}`);
  }
  function removeMenu(key) {
    const i = menus.findIndex((m) => m.key === key);
    const rest = menus.filter((m) => m.key !== key);
    setMenus(rest);
    const next = rest[i] || rest[i - 1];
    focusId(next ? `sn-menu-name-${next.key}` : "sn-menu-add");
  }

  // ── 저장 ──
  function validate() {
    const e = {};
    const nm = name.trim();
    if (!nm) e.name = "가게 이름을 적어 주세요.";
    else if (nm.length > NAME_MAX) e.name = `가게 이름은 ${NAME_MAX}자까지 적을 수 있어요.`;
    if (!industry) e.industry = "업종을 골라 주세요.";
    if (!locSource || needRepick) e.location = needRepick ? "업종을 바꿨으니 주소를 다시 찾아 상권을 골라 주세요." : "주소를 찾거나 가까운 역을 골라 주세요.";
    else if (!industry) { /* 상권은 업종을 고른 뒤에 정해진다 (업종 칸 오류 하나만) */ }
    else if (!usingSaved && market.state === "loading") e.area = "상권 후보를 불러오는 중이에요. 잠시 뒤 다시 눌러 주세요.";
    else if (!chosen) e.area = market.state === "error" ? "상권 후보를 다시 불러온 뒤 골라 주세요." : "상권을 하나 골라 주세요.";
    const m = checkMenus(menus);
    if (Object.keys(m.errors).length) e.menus = Object.fromEntries(Object.entries(m.errors));
    return { e, menus: m.menus };
  }
  function focusError(e) {
    const firstMenu = e.menus && menus.find((m) => e.menus[m.key]);
    const order = [
      ["name", "sn-name"], ["industry", "sn-industry"], ["status", "sn-status"], ["channels", `sn-ch-${CHANNELS[0].code}`],
      ["location", pickerOpen ? (method === "station" ? (line ? "sn-station" : "sn-line") : "sn-addr") : "sn-loc-change"],
      ["area", rows.find((r) => !r.blocked) ? `sn-area-${(rows.find((r) => r.code === area && !r.blocked) || rows.find((r) => !r.blocked)).code}` : "sn-area-box"],
      ["menus", firstMenu ? (e.menus[firstMenu.key].name ? `sn-menu-name-${firstMenu.key}` : `sn-menu-price-${firstMenu.key}`) : "sn-menu-add"],
      ["form", "sn-form-err"],
    ];
    const hit = order.find(([k]) => e[k]);
    if (hit) focusId(hit[1]);
  }

  async function open(id) {
    try { await openStore(id); }   // 가게 선택의 [이 가게 열기]와 같은 길: POST /api/auth/store → 가게 자료 → 메인 화면 홈
    catch (err) {
      if (!alive.current || err.authHandled) return;
      setErrors({ form: `가게는 등록했어요. 가게를 열지 못했어요: ${err.message}` });
      focusId("sn-form-err");
    }
  }

  async function onSubmit(ev) {
    ev.preventDefault();
    if (saving) return;
    if (created) { setSaving(true); await open(created); if (alive.current) setSaving(false); return; }
    const { e, menus: menuList } = validate();
    if (Object.keys(e).length) { setErrors(e); focusError(e); return; }
    setErrors({});
    const location = usingSaved ? null : locationBody(market.loc, picked ? picked.fallback : { kind: "station", ...savedLoc });
    const areaBody = usingSaved ? null : { area_code: chosen.code, name: chosen.name, period: chosen.period ? chosen.period.code : null };
    const base = { name: name.trim(), industry_code: industry, business_type_name: industryName, business_status: status, channels, menus: menuList };
    setSaving(true);
    try {
      if (edit) {
        const patch = storePatch(saved, { ...base, location, area: areaBody });
        if (Object.keys(patch).length) await patchStore(saved.store_id, patch);
        await acctLoad();                                          // 상단 바·가게 선택의 이름·업종·상권이 서버와 같게
        if (getState().entered === saved.store_id) storeChanged();  // 들어가 있던 가게면 메인 화면 자료도 새로 (기다리지 않음)
        goProfile();
        return;
      }
      const r = await createStore({ ...base, location, area: areaBody });
      const id = r && r.store && r.store.store_id;
      if (!id) throw new Error("가게를 등록했는지 확인하지 못했어요. 가게 선택에서 확인해 주세요.");
      setCreated(id);
      await open(id);
    } catch (err) {
      if (!alive.current || err.authHandled) return;
      const field = err.state === "store_limit" ? "form" : errorField(err.message);
      const text = err.state === "store_limit" ? `${err.message} 프로필에서 쓰지 않는 가게를 빼면 새로 등록할 수 있어요.` : err.message;
      const ne = { [field]: text };
      setErrors(ne); focusError(ne);
    } finally { if (alive.current) setSaving(false); }
  }

  const err = (k) => errors[k] || "";
  const desc = (k, extra) => [errors[k] ? `sn-err-${k}` : "", extra].filter(Boolean).join(" ") || undefined;
  const errLine = (k) => <p className="sn-err" id={`sn-err-${k}`} hidden={!errors[k]}>{errors[k]}</p>;
  const lineStations = useMemo(() => stationsOf(opts.stations, line, opts.lines), [opts, line]);
  const results = search && !search.error ? (search.candidates || []).filter((c) => c && c.in_seoul) : [];
  const busy = saving;
  const submitText = created ? (saving ? "여는 중…" : "가게 열기") : edit ? (saving ? "저장하는 중…" : "저장") : saving ? "등록하는 중…" : "가게 등록하고 시작";

  return (
    <form className="sn-form stack" noValidate onSubmit={onSubmit} aria-busy={busy || undefined} aria-label={edit ? "가게 정보" : "새 가게 정보"}>
      {/* ① 가게 기본 정보 */}
      <section className="panel sn-sec" aria-labelledby="sn-basic-title">
        <h2 id="sn-basic-title">1. 가게 기본 정보</h2>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="sn-name">가게 이름</label>
            <input id="sn-name" name="store_name" maxLength={NAME_MAX} autoComplete="organization" placeholder="예: 온기한식" value={name}
              aria-invalid={!!err("name") || undefined} aria-describedby={desc("name")} disabled={busy}
              onChange={(e) => { setName(e.target.value); clearErr("name"); }} />
            {errLine("name")}
          </div>
          <div className="field">
            <label htmlFor="sn-industry">업종</label>
            <select id="sn-industry" name="industry_code" value={industry} disabled={busy}
              aria-invalid={!!err("industry") || undefined} aria-describedby={desc("industry")} onChange={(e) => changeIndustry(e.target.value)}>
              <option value="">업종을 골라 주세요</option>
              {opts.industries.map((x) => <option key={x.code} value={x.code}>{x.name}</option>)}
            </select>
            {errLine("industry")}
          </div>
          <div className="field">
            <label htmlFor="sn-status">운영 상태</label>
            <select id="sn-status" name="business_status" value={status} disabled={busy}
              aria-invalid={!!err("status") || undefined} aria-describedby={desc("status")} onChange={(e) => { setStatus(e.target.value); clearErr("status"); }}>
              {(opts.statuses.length ? opts.statuses : [{ code: "operating", label: "운영 중" }]).map((x) => <option key={x.code} value={x.code}>{x.label}</option>)}
            </select>
            {errLine("status")}
          </div>
        </div>
        <fieldset className="sn-fieldset" aria-describedby={desc("channels")}>
          <legend className="sn-legend">입점한 배달 채널</legend>
          <div className="sn-chips">
            {CHANNELS.map((c) => (
              <label key={c.code} className={["sn-chip", channels.includes(c.code) && "on"].filter(Boolean).join(" ")}>
                <input type="checkbox" id={`sn-ch-${c.code}`} name="channels" value={c.code} checked={channels.includes(c.code)} disabled={busy}
                  onChange={() => toggleChannel(c.code)} />
                <span aria-hidden="true" className="sn-chip-check">✓</span>{c.name}
              </label>
            ))}
          </div>
          {errLine("channels")}
        </fieldset>
      </section>

      {/* ② 가게 위치와 상권 */}
      <section className="panel sn-sec" aria-labelledby="sn-place-title">
        <h2 id="sn-place-title">2. 가게 위치와 상권</h2>
        <fieldset className="sn-fieldset" aria-describedby={desc("location")}>
          <legend className="sn-legend">주소 또는 가까운 역</legend>
          {!pickerOpen ? (
            <div className="sn-saved inset">
              <div className="sn-saved-text"><b>{(savedLoc && savedLoc.label) || "저장한 위치"}</b>
                {savedLoc && savedLoc.road_address && savedLoc.road_address !== savedLoc.label && <span className="small muted">{savedLoc.road_address}</span>}</div>
              <Button id="sn-loc-change" size="small" disabled={busy} onClick={openPicker}>위치 바꾸기</Button>
            </div>
          ) : (
            <div className="stack-16">
              <div className="sn-seg" role="radiogroup" aria-label="위치를 정하는 방법">
                {[["address", "주소로 찾기"], ["station", "가까운 역으로"]].map(([v, t]) => (
                  <label key={v} className={["sn-seg-opt", method === v && "on"].filter(Boolean).join(" ")}>
                    <input type="radio" name="loc_method" value={v} checked={method === v} disabled={busy} onChange={() => setMethod(v)} />{t}
                  </label>
                ))}
              </div>
              {method === "address" ? (
                <div className="stack-8">
                  <label className="sr" htmlFor="sn-addr">가게 주소</label>
                  <div className="sn-search">
                    <input id="sn-addr" type="search" name="address_query" className="input" maxLength={QUERY_MAX} autoComplete="street-address"
                      placeholder="예: 서울 동작구 장승배기로 10" value={query} disabled={busy}
                      aria-invalid={!!err("location") || undefined} aria-describedby={desc("location")}
                      onChange={(e) => { setQuery(e.target.value); clearErr("location"); }}
                      onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) { e.preventDefault(); onSearch(); } }} />
                    <Button id="sn-addr-go" disabled={busy || searching} onClick={onSearch}>{searching ? "찾는 중…" : "찾기"}</Button>
                  </div>
                  <AddressResults search={search} results={results} addrId={addrId} busy={busy}
                    onPick={(c) => pickAddress(search, c)} onStation={() => { setMethod("station"); focusId("sn-line"); }} />
                </div>
              ) : (
                <div className="grid-2">
                  <div className="field">
                    <label htmlFor="sn-line">호선</label>
                    <select id="sn-line" name="station_line" value={line} disabled={busy}
                      aria-invalid={!!err("location") && !line || undefined} aria-describedby={desc("location")}
                      onChange={(e) => { setLine(e.target.value); setStationId(""); clearErr("location"); }}>
                      <option value="">호선을 골라 주세요</option>
                      {opts.lines.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="sn-station">역</label>
                    <select id="sn-station" name="station_id" value={stationId} disabled={busy || !line}
                      aria-invalid={!!err("location") && !!line || undefined} aria-describedby={desc("location")}
                      onChange={(e) => pickStation(e.target.value)}>
                      <option value="">{line ? "역을 골라 주세요" : "호선부터 골라 주세요"}</option>
                      {lineStations.map((s) => <option key={s.id} value={s.id}>{s.name}{s.district_name ? ` (${s.district_name})` : ""}</option>)}
                    </select>
                  </div>
                </div>
              )}
              {locSource === "picked" && placeLabel && <p className="small sn-place" role="status">고른 위치: <b>{placeLabel}</b></p>}
              {edit && hasSaved && !needRepick && (
                <div><Button size="small" variant="text" disabled={busy} onClick={keepSavedPlace}>위치 바꾸지 않기</Button></div>
              )}
            </div>
          )}
          {errLine("location")}
          {needRepick && !err("location") && <p className="small sn-hint" role="status">업종을 바꾸면 상권 자료가 달라져요. 주소를 다시 찾아 상권을 골라 주세요.</p>}
        </fieldset>

        {point ? (
          <NaverMap className="sn-map" marker={{ ...point, title: placeLabel }} fit={rows.some((r) => r.geometry) ? "areas" : "marker"}
            areas={rows.filter((r) => r.geometry).map((r) => ({ id: r.code, name: r.name, geometry: r.geometry, kind: r.code === area && !r.blocked ? "selected" : "nearby", disabled: !!r.blocked }))}
            onAreaClick={chooseArea} list={false} label="가게 위치와 상권 경계 지도">
            {rows.some((r) => r.geometry) && (
              <ul className="nmap-legend" aria-hidden="true">
                <li className="nmap-only"><span className="nmap-key pin" />가게 위치</li>
                <li><span className="nmap-key selected" />고른 상권</li>
                <li><span className="nmap-key nearby" />주변 상권</li>
              </ul>
            )}
          </NaverMap>
        ) : null}

        <fieldset className="sn-fieldset" id="sn-area-box" tabIndex={-1} aria-describedby={desc("area", areaNote ? "sn-area-note" : "")}>
          <legend className="sn-legend">이 위치가 속한 상권</legend>
          <AreaState market={market} usingSaved={usingSaved} hasPlace={!!locSource && !needRepick} industry={industry}
            onRetry={() => setRetry((n) => n + 1)} />
          {rows.length > 0 && (
            <ul className="plain sn-areas">
              {rows.map((r) => {
                const on = r.code === area && !r.blocked;
                return (
                  <li key={r.code}>
                    <label className={["sn-area", on && "on", r.blocked && "off"].filter(Boolean).join(" ")}>
                      <input type="radio" id={`sn-area-${r.code}`} name="area_code" value={r.code} checked={on} disabled={busy || !!r.blocked}
                        aria-describedby={`sn-area-sub-${r.code}`} onChange={() => chooseArea(r.code)} />
                      <span className="sn-area-text">
                        <b>{r.name}</b>
                        <span id={`sn-area-sub-${r.code}`} className="small muted">{usingSaved ? savedSub(r) : areaSub(r)}{r.blocked ? ` · ${r.blocked}` : ""}</span>
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="small sn-hint" id="sn-area-note" role="status" hidden={!areaNote}>{areaNote}</p>
          {errLine("area")}
          {(rows.length > 0 || usingSaved) && (
            <p className="small muted">상권 자료는 우리 가게 매출이 아니라 상권·업종 전체의 추정치예요.{market.notice && !usingSaved ? ` ${market.notice}` : ""}</p>
          )}
        </fieldset>
      </section>

      {/* ③ 메뉴와 가격 */}
      <section className="panel sn-sec" aria-labelledby="sn-menu-title" aria-describedby="sn-menu-lead">
        <h2 id="sn-menu-title">3. 메뉴와 가격</h2>
        <p id="sn-menu-lead" className="small muted">홍보글이 메뉴에 없는 음식을 쓰지 않게 점검하고, 쿠폰 금액을 계산할 때 써요.</p>
        {menus.length > 0 && (
          <ol className="plain sn-menus">
            {menus.map((m, i) => {
              const bad = (errors.menus && errors.menus[m.key]) || {};
              const errId = `sn-menu-err-${m.key}`;
              return (
                <li key={m.key} className="sn-menu">
                  <div className="field sn-menu-name">
                    <label htmlFor={`sn-menu-name-${m.key}`}>메뉴 이름</label>
                    <input id={`sn-menu-name-${m.key}`} name="menu_name" maxLength={NAME_MAX} value={m.name} disabled={busy}
                      placeholder={m.ph ? `예: ${m.ph[0]}` : undefined} aria-invalid={!!bad.name || undefined} aria-describedby={bad.name ? errId : undefined}
                      onChange={(e) => setMenu(m.key, { name: e.target.value })} />
                  </div>
                  <div className="field sn-menu-price">
                    <label htmlFor={`sn-menu-price-${m.key}`}>가격</label>
                    <span className="sn-won">
                      <input id={`sn-menu-price-${m.key}`} name="menu_price" inputMode="numeric" maxLength={9} value={m.price} disabled={busy}
                        placeholder={m.ph ? m.ph[1] : undefined} aria-invalid={!!bad.price || undefined} aria-describedby={bad.price ? errId : undefined}
                        onChange={(e) => setMenu(m.key, { price: e.target.value })} />
                      <span aria-hidden="true">원</span>
                    </span>
                  </div>
                  <Button className="icon-btn sn-menu-del" aria-label={`${i + 1}번째 메뉴 지우기`} title="지우기" disabled={busy} onClick={() => removeMenu(m.key)}>
                    <Icon name="닫기" size={18} />
                  </Button>
                  <p className="sn-err sn-menu-err" id={errId} hidden={!bad.name && !bad.price}>{[bad.name, bad.price].filter(Boolean).join(" ")}</p>
                </li>
              );
            })}
          </ol>
        )}
        <div className="btn-row">
          <Button id="sn-menu-add" disabled={busy || menus.length >= MENU_MAX} onClick={addMenu}>+ 메뉴 더하기</Button>
          {menus.length >= MENU_MAX && <span className="small muted">메뉴는 {MENU_MAX}개까지 적을 수 있어요.</span>}
        </div>
      </section>

      {!edit && (
        <section className="panel sn-sec" aria-labelledby="sn-start-title">
          <h2 id="sn-start-title">등록하면 이렇게 시작해요</h2>
          <p>{START_TEXT}</p>
        </section>
      )}

      <p className="acct-error" id="sn-form-err" tabIndex={-1} role="alert" hidden={!errors.form}>{errors.form}</p>
      <div className="btn-row sn-actions">
        <Button disabled={saving} onClick={onCancel}>취소</Button>
        <Button type="submit" variant="primary" disabled={saving}>{submitText}</Button>
      </div>
    </form>
  );
}

// 고치기에서 저장한 상권 그대로일 때의 아래 줄
const savedSub = (r) => [`공식 상권 코드 ${r.code}`, r.period ? `${r.period.label} 자료` : ""].filter(Boolean).join(" · ");

// 주소 찾기 결과: 후보(여럿이면 고름) · 서버 안내 문장 그대로 · 조회 불가면 역으로
function AddressResults({ search, results, addrId, busy, onPick, onStation }) {
  if (!search) return null;
  if (search.error) return <p className="sn-err" role="alert">{search.error}</p>;
  if (search.status === "lookup_unavailable") {
    return (
      <div className="sn-note" role="status">
        <span>{LOOKUP_OFF}</span>
        <Button size="small" onClick={onStation}>가까운 역으로</Button>
      </div>
    );
  }
  return (
    <div className="stack-8">
      {(!results.length || results.length > 1) && search.message && <p className="small sn-hint" role="status">{search.message}</p>}
      {results.length > 0 && (
        <ul className="plain sn-addr-list" aria-label="주소 후보">
          {results.map((c) => (
            <li key={c.id}>
              <label className={["sn-area", addrId === c.id && "on"].filter(Boolean).join(" ")}>
                <input type="radio" name="address_candidate" value={c.id} checked={addrId === c.id} disabled={busy} onChange={() => onPick(c)} />
                <span className="sn-area-text"><b>{c.label || c.road_address}</b>
                  {c.jibun_address && c.jibun_address !== c.label && <span className="small muted">지번 {c.jibun_address}</span>}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// 상권 칸 위의 한 줄: 아직 위치 없음 · 업종 먼저 · 불러오는 중 · 실패(다시 시도) · 후보 없음
function AreaState({ market, usingSaved, hasPlace, industry, onRetry }) {
  if (usingSaved) return null;
  if (!hasPlace) return <p className="small muted">주소를 찾거나 역을 고르면 그 위치의 상권이 보여요.</p>;
  if (!industry) return <p className="small sn-hint" role="status">업종을 먼저 골라 주세요. 업종마다 상권 자료가 달라요.</p>;
  if (market.state === "loading") return <p className="small muted" role="status">상권 후보를 불러오는 중…</p>;
  if (market.state === "error") {
    return (
      <div className="sn-note bad" role="alert">
        <span>상권 후보를 불러오지 못했어요. {market.message}</span>
        <Button size="small" onClick={onRetry}>다시 시도</Button>
      </div>
    );
  }
  if (market.state === "ready" && !market.rows.length) return <p className="small sn-hint" role="status">{market.message || "이 위치 가까이에 고를 수 있는 상권이 없어요."}</p>;
  return null;
}
