"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const staticPath = path.join(__dirname, "../app/static/onboarding");
const html = fs.readFileSync(path.join(staticPath, "index.html"), "utf8");
const source = fs.readFileSync(path.join(staticPath, "onboarding.js"), "utf8");
const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, "../app/onboarding_industries.json"), "utf8"));

// Small, dependency-free DOM double. It parses the real page and runs the whole
// production IIFE, including startup, event listeners and fetch lifecycle. Native
// select/radio/reset and Enter defaults are modelled; iframe/layout/browser SDK
// behaviour still needs the separate browser check. No live network calls occur.
class TextNode {
  constructor(value) { this.textContent = value; this.parentNode = null; }
}
class Element {
  constructor(tag, document) {
    this.tagName = tag.toUpperCase(); this.ownerDocument = document;
    this.childNodes = []; this.parentNode = null; this.attributes = {};
    this.listeners = {}; this.hidden = false; this.disabled = false; this.open = false;
    this._value = ""; this._checked = false; this._selected = false;
    this.className = "";
    this.style = {};
    this.classList = { toggle: (name, enabled) => {
      const names = new Set(this.className.split(/\s+/).filter(Boolean));
      if (enabled) names.add(name); else names.delete(name);
      this.className = [...names].join(" ");
    } };
  }
  get children() { return this.childNodes.filter((node) => node instanceof Element); }
  get textContent() { return this.childNodes.map((node) => node.textContent).join(""); }
  set textContent(value) { this.replaceChildren(new TextNode(String(value))); }
  set innerHTML(_) { throw new Error("The form must use text nodes, not HTML injection"); }
  get options() { return descendants(this).filter((node) => node.tagName === "OPTION"); }
  get value() {
    if (this.tagName === "SELECT") return (this.options.find((option) => option._selected) || this.options[0])?.value || "";
    return this._value;
  }
  set value(value) {
    if (this.tagName === "SELECT") {
      this.options.forEach((option) => { option._selected = option.value === String(value); });
    } else this._value = String(value);
  }
  get checked() { return this._checked; }
  set checked(value) {
    if (value && this.type === "radio" && this.name) {
      this.ownerDocument.querySelectorAll(`input[name="${this.name}"]`).forEach((node) => { node._checked = false; });
    }
    this._checked = Boolean(value);
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (["id", "name", "type", "value", "label"].includes(name)) this[name] = value;
    if (name === "class") this.className = value;
    if (["hidden", "disabled", "checked", "selected", "open"].includes(name)) {
      if (name === "selected") this._selected = true; else this[name] = true;
    }
  }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) { delete this.attributes[name]; }
  append(...nodes) {
    for (let node of nodes) {
      if (typeof node === "string") node = new TextNode(node);
      if (node.parentNode) node.remove();
      node.parentNode = this; this.childNodes.push(node);
    }
  }
  replaceChildren(...nodes) { this.childNodes.forEach((node) => { node.parentNode = null; }); this.childNodes = []; this.append(...nodes); }
  remove() { if (this.parentNode) { const siblings = this.parentNode.childNodes; siblings.splice(siblings.indexOf(this), 1); this.parentNode = null; } }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  async emit(type, values = {}) {
    const event = { type, target: this, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...values };
    await Promise.all((this.listeners[type] || []).map((listener) => listener(event)));
    return event;
  }
  querySelectorAll(selector) { return descendants(this).filter((node) => matches(node, selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  focus() { this.ownerDocument.activeElement = this; }
  scrollIntoView() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
  reset() {
    descendants(this).forEach((node) => {
      if (node.tagName === "INPUT") {
        if (node.type === "radio") node.checked = "checked" in node.attributes;
        else node.value = node.attributes.value || "";
      }
      if (node.tagName === "SELECT") node.options.forEach((option) => { option._selected = "selected" in option.attributes; });
    });
  }
}
function descendants(node) { return node.children.flatMap((child) => [child, ...descendants(child)]); }
function matches(node, selector) {
  const negative = [...selector.matchAll(/:not\(([^)]+)\)/g)].map((match) => match[1]);
  selector = selector.replace(/:not\([^)]+\)/g, "");
  if (negative.some((item) => matches(node, item))) return false;
  if (selector.includes(":checked") && !node.checked) return false;
  if (selector.includes(":disabled") && !node.disabled) return false;
  selector = selector.replace(/:(checked|disabled)/g, "");
  const tag = selector.match(/^[\w-]+/)?.[0];
  if (tag && node.tagName !== tag.toUpperCase()) return false;
  for (const [, name, value] of selector.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)) {
    if (value !== undefined ? String(node[name] ?? node.getAttribute(name)) !== value
      : !(name in node.attributes) && !node[name]) return false;
  }
  for (const [, name] of selector.matchAll(/\.([\w-]+)/g)) if (!node.className.split(/\s+/).includes(name)) return false;
  return true;
}
function createDocument() {
  const doc = { activeElement: null, createElement: (tag) => new Element(tag, doc) };
  doc.root = doc.createElement("document");
  doc.querySelectorAll = (selector) => doc.root.querySelectorAll(selector);
  doc.querySelector = (selector) => doc.root.querySelector(selector);
  doc.getElementById = (id) => descendants(doc.root).find((node) => node.id === id) || null;
  const stack = [doc.root], voids = new Set(["META", "LINK", "INPUT", "BR"]);
  for (const token of html.matchAll(/<!--[\s\S]*?-->|<![^>]*>|<\/?[\w-]+\b[^>]*>|[^<]+/g)) {
    const raw = token[0];
    if (raw.startsWith("<!")) continue;
    if (raw.startsWith("</")) { stack.pop(); continue; }
    if (!raw.startsWith("<")) { stack.at(-1).append(new TextNode(raw)); continue; }
    const [, tag, attrs] = raw.match(/^<([\w-]+)([\s\S]*?)>$/);
    const node = doc.createElement(tag);
    for (const [, key, quoted, single, bare] of attrs.matchAll(/([\w-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) node.setAttribute(key, quoted ?? single ?? bare ?? "");
    stack.at(-1).append(node);
    if (!voids.has(node.tagName)) stack.push(node);
  }
  doc.head = doc.querySelector("head"); doc.body = doc.querySelector("body");
  return doc;
}
const flush = () => new Promise((resolve) => setImmediate(resolve));
const candidate = (id = "address-1") => ({ id, label: "서울특별시 중구 세종대로 110", road_address: "서울특별시 중구 세종대로 110", jibun_address: "서울 중구 태평로1가 31", in_seoul: true, latitude: 37.5663, longitude: 126.9779 });
const stations = [
  { id: "station-gangnam-2", name: "강남역", lines: ["2호선"], selectable_line_codes: ["line2"], district_code: "11680", district_name: "강남구", latitude: 37.4979, longitude: 127.0276 },
  { id: "station-gangnam-new", name: "강남역", lines: ["신분당선"], selectable_line_codes: ["shin"], district_code: "11680", district_name: "강남구", latitude: 37.4968, longitude: 127.0280 },
  { id: "station-gangnamgu", name: "강남구청역", lines: ["7호선"], selectable_line_codes: ["line7"], district_code: "11680", district_name: "강남구" },
  { id: "station-isu", name: "총신대입구역", aliases: ["이수"], lines: ["4호선"], selectable_line_codes: ["line4"], district_code: "11590", district_name: "동작구" },
  { id: "station-yongsan", name: "용산역", lines: ["경부선"], selectable_line_codes: ["line1", "gyeongui"], district_code: "11170", district_name: "용산구" },
  { id: "station-seobinggo", name: "서빙고역", lines: ["경원선"], selectable_line_codes: ["gyeongui"], district_code: "11170", district_name: "용산구" },
  { id: "station-unmapped", name: "미확인역", lines: ["2호선"], district_code: "11680", district_name: "강남구" },
];
const stationLines = [{ code: "line1", name: "1호선" }, { code: "line2", name: "2호선" }, { code: "line4", name: "4호선" }, { code: "line7", name: "7호선" }, { code: "shin", name: "신분당선" }, { code: "gyeongui", name: "경의·중앙선" }];
// Intentionally unsorted, small administrative-dong fixture. Production receives
// its full official catalogue from the API, which has separate source tests.
const neighborhoods = [
  { code: "test-mapo-hapjeong", name: "합정동", district_code: "11440", district_name: "마포구" },
  { code: "test-seongdong-seongsu", name: "성수1가1동", district_code: "11200", district_name: "성동구" },
  { code: "test-mapo-yeonnam", name: "연남동", district_code: "11440", district_name: "마포구" },
  { code: "test-mapo-seogyo", name: "서교동", district_code: "11440", district_name: "마포구" },
];
const profile = (industryCode = "CS100010") => ({ revision: 7, location: { kind: "address", ...candidate(), verification: "verified_address", analysis_area_confirmed: false }, industry: catalog.industries.find((item) => item.code === industryCode), business_status: "operating", business_status_label: "운영 중", ready_for_analysis: false });
const areaProfile = (location = {}) => ({ ...profile(), location: { kind: "area", district_code: "11440", district_name: "마포구", label: "연남동", neighborhood_code: "test-mapo-yeonnam", neighborhood_name: "연남동", neighborhood_type: "administrative_dong", verification: "selected_neighborhood", analysis_area_confirmed: false, ...location } });
const stationProfile = (id = "station-isu", location = {}) => ({ ...profile(), location: { ...stations.find((station) => station.id === id), kind: "station", station_id: id, label: stations.find((station) => station.id === id)?.name || "예전 역", verification: "verified_station", ...location } });
const analysisScope = { boundary_notice: "2023년 공개 경계이며 현재 분기 경계와의 동일성은 확인되지 않았습니다.", boundary_source_url: "https://data.seoul.go.kr/boundaries", search_radius_m: 1000, search_radius_notice: "후보를 찾는 거리이며 통계 집계 반경이 아닙니다." };
function coveragePeriod(code, mode = "all") {
  const metrics = Object.fromEntries(["sales", "stores", "floating_population"].map((key) => [key, {
    status: mode === "none" || (mode === "population" && key !== "floating_population") ? "no_observation" : "available",
    industry_specific: key !== "floating_population", reason: key === "floating_population" ? "지역 전체 유동인구입니다." : "확인된 관측 자료입니다.",
    source_url: `https://data.seoul.go.kr/${key}`,
  }]));
  return { code, label: `${code.slice(0, 4)}년 ${code[4]}분기`, available: mode !== "none", industry_data_available: mode === "all", population_only: mode === "population", metrics };
}
function analysisCandidate(code = "market-a", mode = "all", periodCodes = ["20262", "20261", "20252"]) {
  const periods = periodCodes.map((period) => coveragePeriod(period, mode));
  return { area_code: code, name: code === "market-a" ? "세종대로 상권" : "인근 상권", type: "골목상권", district_name: "중구", neighborhood_name: "명동", relation: "inside", distance_m: 0,
    geometry: { type: "Polygon", coordinates: [[[126.977, 37.565], [126.98, 37.565], [126.98, 37.568], [126.977, 37.568], [126.977, 37.565]], [[126.978, 37.566], [126.978, 37.567], [126.979, 37.567], [126.979, 37.566], [126.978, 37.566]]] },
    availability: { periods, available_periods: periods.filter((period) => period.available).map((period) => period.code) }, available_periods: periods.filter((period) => period.available).map((period) => period.code), selection_blocked_reason: null };
}
function analysisSelection(overrides = {}) {
  return { status: "selected", area_code: "market-a", area_name: "세종대로 상권", period: "20262", period_label: "2026년 2분기", industry_code: "CS100010", catalog_version: "catalog-v1", analysis_setup_complete: true, conditions_confirmed: true, ready_for_analysis: false, availability: coveragePeriod("20262"), ...overrides };
}
function salesDistribution(kind) {
  const labels = kind === "weekday" ? ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
    : kind === "time" ? ["00~06시", "06~11시", "11~14시", "14~17시", "17~21시", "21~24시"] : ["10대", "20대", "30대", "40대", "50대", "60대 이상"];
  const amounts = kind === "weekday" ? [300000, 200000, 100000, 100000, 100000, 100000, 100000]
    : kind === "time" ? [100000, 200000, 300000, 150000, 150000, 100000] : [50, 20, 10, 10, 5, 5];
  const shares = kind === "weekday" ? [30, 20, 10, 10, 10, 10, 10] : kind === "time" ? [10, 20, 30, 15, 15, 10] : [50, 20, 10, 10, 5, 5];
  return { label: kind === "weekday" ? "요일별 매출" : kind === "time" ? "시간대별 매출" : "연령별 매출", status: "complete",
    items: labels.map((label, index) => ({ label, field: `SOURCE_${kind}_${index}`, status: "available", value: amounts[index], value_text: String(amounts[index]), share_percent: shares[index] })),
    denominator: { kind: kind === "age" ? "age_classified_total" : "quarter_total", label: kind === "age" ? "연령이 확인된 매출" : "분기 총매출", value: kind === "age" ? 100 : 1000000, value_text: kind === "age" ? "100" : "1000000" },
    sum: kind === "age" ? 100 : 1000000, total_difference: kind === "age" ? -999900 : 0, classified_share_of_total_percent: kind === "age" ? 0.01 : null,
    ranking: { status: "available", highest: [kind === "time" ? "11~14시" : labels[0]], lowest: kind === "age" ? ["50대", "60대 이상"] : [labels.at(-1)] }, warnings: [] };
}
function salesReport(profileValue = profile(), selection = analysisSelection(), revision = profileValue.revision) {
  return { status: "available", revision, selection: { ...selection, industry_name: profileValue.industry.name }, data_version: "sales-v1",
    total: { status: "available", value: 1000000, value_text: "1000000", unit: "원", label: "분기 추정매출" },
    distributions: { weekday: salesDistribution("weekday"), time: salesDistribution("time"), age: salesDistribution("age") },
    summary: ["서버가 확인한 매출 요약입니다.", "연령이 분류된 매출의 범위를 확인해 주세요."], warnings: ["추정 매출은 개별 가게 매출을 뜻하지 않습니다."],
    source: { title: "서울시 추정매출", url: "https://data.seoul.go.kr/sales", unit: "원", period_basis: "quarter" } };
}

function storesReport(profileValue = profile(), selection = analysisSelection(), revision = profileValue.revision) {
  const amounts = { total: 10, general: 7, franchise: 3, opened: 2, closed: 1 };
  const labels = { total: "전체 점포 수", general: "일반 점포 수", franchise: "프랜차이즈 점포 수", opened: "개업 점포 수", closed: "폐업 점포 수" };
  return { status: "available", feature: "stores", analysis_stage: "stores_result", revision,
    selection: { ...selection, industry_name: profileValue.industry.name }, data_version: "stores-v1",
    counts: Object.fromEntries(Object.entries(amounts).map(([key, value]) => [key, { label: labels[key], field: `SOURCE_${key}`, status: "available", value, value_text: String(value), unit: "개" }])),
    composition: { status: "consistent", sum: 10, difference: 0, franchise_share_percent: 30, denominator: { label: "전체 점포 수", value: 10, value_text: "10" }, warnings: [] },
    summary: ["서버가 확인한 전체 점포는 10개입니다."],
    warnings: ["개업·폐업 수는 개별 가게의 현재 영업 상태를 뜻하지 않습니다.", "개업 수에서 폐업 수를 뺀 값은 전체 점포 수의 기간 증감이 아닙니다."],
    source: { title: "서울시 점포 자료", url: "https://data.seoul.go.kr/stores", unit: "개", period_basis: "quarter", coverage_note: "보관한 점포 원천은 10개 상권 범위입니다. 서울 전체 점포 자료를 확보한 것은 아닙니다." } };
}

function populationReport(profileValue = profile(), selection = analysisSelection(), revision = profileValue.revision) {
  const distributions = Object.fromEntries(["time", "age"].map((key) => {
    const group = salesDistribution("time");
    group.label = key === "time" ? "시간대별 유동인구" : "연령별 유동인구";
    const labels = key === "time" ? group.items.map((item) => item.label) : ["연령대 10", "연령대 20", "연령대 30", "연령대 40", "연령대 50", "연령대 60 이상"];
    group.items.forEach((item, index) => { item.label = labels[index]; item.field = `POP_${key}_${index}`; });
    group.denominator = { kind: "source_total", label: "원천 총 유동인구 지표", value: 1000000, value_text: "1000000" };
    group.ranking = { status: "available", highest: [labels[2]], lowest: [labels[0], labels[5]] };
    return [key, group];
  }));
  return { feature: "population", analysis_stage: "population_result", status: "available", revision,
    selection: { ...selection, industry_name: profileValue.industry.name }, industry_applied: false, population_scope: "area_wide", data_version: "population-v1",
    total: { label: "지역 유동인구 원천 총지표", status: "available", value: 1000000, value_text: "1000000", unit: "명" }, distributions,
    source: { title: "서울시 상권 유동인구", url: "https://data.seoul.go.kr/population", unit: "명", aggregation_basis: "source_total", definition_verified: false, meaning_note: "시간 집계 기준은 확인 중이며 일평균이나 고유 방문자 수로 해석할 수 없습니다." },
    summary: ["서버가 확인한 유동인구 원천 총지표는 1,000,000명입니다."], warnings: ["상권 전체 자료이며 선택 업종의 고객 수가 아닙니다."] };
}

const comparisonAreas = [
  { area_code: "market-b", name: "중구 비교상권", district_code: "11140", district_name: "중구", type: "발달상권", selectable: true },
  { area_code: "market-c", name: "마포 비교상권", district_code: "11440", district_name: "마포구", type: "골목상권", selectable: true },
  { area_code: "market-blocked", name: "연결 확인 상권", district_code: "11140", district_name: "중구", type: "골목상권", selectable: false, reason: "경계와 통계의 명칭 확인 필요" },
];
function comparisonOptions(profileValue = profile(), selection = analysisSelection(), revision = profileValue.revision) {
  return { status: "ready", revision, selection: { ...selection, industry_name: profileValue.industry.name }, catalog_version: selection.catalog_version,
    districts: [{ code: "11140", name: "중구" }, { code: "11440", name: "마포구" }, { code: "11680", name: "강남구" }], areas: comparisonAreas,
    scope: { base_excluded: true, blocked_area_count: 1 }, warnings: [] };
}
function comparisonReport(profileValue = profile(), selection = analysisSelection(), revision = profileValue.revision, targetCode = "market-b") {
  return { feature: "comparison", analysis_stage: "comparison_result", status: "complete", revision, selection: { ...selection, industry_name: profileValue.industry.name },
    base_area: { area_code: selection.area_code, name: selection.area_name, district_name: "중구", district_code: "11140", type: "골목상권" },
    comparison_area: comparisonAreas.find((area) => area.area_code === targetCode), comparison_direction: "comparison_minus_base",
    metrics: [ ["sales", "추정 매출", "원", 1000000, 1500000, 500000, 50], ["stores_total", "전체 점포", "개", 10, 12, 2, 20], ["stores_general", "일반 점포", "개", 7, 9, 2, 28.57], ["stores_franchise", "프랜차이즈 점포", "개", 3, 3, 0, 0], ["stores_opened", "개업 점포", "개", 2, 1, -1, -50], ["stores_closed", "폐업 점포", "개", 1, 2, 1, 100], ["floating_population", "유동인구 원천값", "명", 1000000, 800000, -200000, -20] ].map(([key, label, unit, base, comparison, delta, percent]) => ({ key, label, unit, industry_applied: key !== "floating_population", base: { status: "available", value: base, value_text: String(base) }, comparison: { status: "available", value: comparison, value_text: String(comparison) }, delta, delta_text: String(delta), percent, percent_status: "available", status: "available", source: { title: key.startsWith("stores") ? "서울시 점포" : key === "sales" ? "서울시 매출" : "서울시 유동인구", url: `https://data.seoul.go.kr/${key.startsWith("stores") ? "stores" : key}`, field: key }, warnings: key.startsWith("stores") ? ["점포 원천 확보 범위는 10개 상권입니다."] : [] })),
    warnings: ["상권 유형과 면적이 다르므로 수치 차이를 상권의 우열로 판단하지 않습니다."], summary: [] };
}
function changesReport(profileValue = profile(), selection = analysisSelection(), revision = profileValue.revision, mode = "qoq") {
  const previousIndex = Number(selection.period.slice(0, 4)) * 4 + Number(selection.period[4]) - 1 - (mode === "yoy" ? 4 : 1);
  const previous = `${Math.floor(previousIndex / 4)}${previousIndex % 4 + 1}`;
  const comparison = comparisonReport(profileValue, selection, revision);
  return { feature: "changes", analysis_stage: "changes_result", status: "complete", revision, selection: comparison.selection,
    comparison: mode, comparison_label: mode === "qoq" ? "전분기" : "전년 동분기", current_period: { code: selection.period, label: selection.period_label }, previous_period: { code: previous, label: `${previous.slice(0, 4)}년 ${previous[4]}분기` }, comparison_direction: "current_minus_previous",
    metrics: comparison.metrics.map(({ base, comparison: current, ...metric }) => ({ ...metric, current, previous: base })),
    warnings: ["두 분기의 상권 경계가 같은지는 확인되지 않았습니다.", "확인된 기간 자료만 사용하며 다른 분기를 대신 사용하지 않습니다."], summary: ["같은 상권·업종의 7개 지표를 비교했습니다."] };
}

async function createApp(config = {}) {
  const document = createDocument(), calls = [], pickers = [], mapCenters = [], polygons = [], mapBounds = [], mapListeners = [];
  let saved = config.profile ? structuredClone(config.profile) : null, revision = saved?.revision || 0;
  let savedAnalysis = config.analysisSelection ? structuredClone(config.analysisSelection) : null;
  const catalogVersion = config.catalogVersion || "catalog-v1";
  const analysisCandidates = config.analysisCandidates || [analysisCandidate(), analysisCandidate("market-b", "population")];
  const options = { districts: catalog.districts, industries: catalog.industries, stations: config.stations ?? stations, station_lines: config.stationLines ?? stationLines, neighborhoods: config.neighborhoods ?? neighborhoods, business_statuses: [{ code: "operating", label: "운영 중" }, { code: "planning", label: "창업 준비" }, { code: "exploring", label: "알아보는 중" }] };
  const window = { kakao: { Postcode: class {
    constructor(settings) { this.settings = settings; pickers.push(this); }
    embed(container, settings) { this.container = container; this.embedSettings = settings; }
  } }, naver: { maps: {
    LatLng: class { constructor(latitude, longitude) { this.latitude = latitude; this.longitude = longitude; } },
    Map: class { constructor(_, settings) { mapCenters.push(settings.center); } setCenter(point) { mapCenters.push(point); } setZoom() {} fitBounds(bounds) { mapBounds.push(bounds); } },
    Marker: class { setMap() { if (config.brokenMarker) throw new Error("Unauthorised SDK cleanup failed"); } },
    LatLngBounds: class { constructor(southwest, northeast) { this.southwest = southwest; this.northeast = northeast; } },
    Polygon: class { constructor(settings) { if (config.brokenPolygon) throw new Error("Polygon unavailable"); this.settings = settings; this.map = settings.map; polygons.push(this); } setMap(map) { this.map = map; if (!map && config.brokenPolygonCleanup) throw new Error("Polygon cleanup failed"); } },
    Event: { addListener(target, type, callback) { const listener = { target, type, callback }; mapListeners.push(listener); return listener; }, removeListener(listeners) { listeners.forEach((listener) => { listener.removed = true; }); } },
    Position: { TOP_RIGHT: 1 },
  } } };
  const fetch = async (url, init = {}) => {
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ url, method: init.method || "GET", body, signal: init.signal });
    let result;
    if (config.fetch) result = await config.fetch(url, init, body);
    if (result === undefined) {
      if (url === "/api/onboarding/options") result = options;
      else if (url === "/api/onboarding/profile" && !init.method) result = { profile: saved, revision };
      else if (url === "/api/onboarding/analysis-selection" && !init.method) result = { profile: saved, revision, analysis_selection: savedAnalysis };
      else if (url.startsWith("/api/onboarding/sales?")) result = config.salesReport || salesReport(saved, savedAnalysis, revision);
      else if (url.startsWith("/api/onboarding/stores?")) result = config.storesReport || storesReport(saved, savedAnalysis, revision);
      else if (url.startsWith("/api/onboarding/population?")) result = config.populationReport || populationReport(saved, savedAnalysis, revision);
      else if (url.startsWith("/api/onboarding/comparison-options?")) result = config.comparisonOptions || comparisonOptions(saved, savedAnalysis, revision);
      else if (url.startsWith("/api/onboarding/comparison?")) result = config.comparisonReport || comparisonReport(saved, savedAnalysis, revision, new URL(url, "http://localhost").searchParams.get("comparison_area_code"));
      else if (url.startsWith("/api/onboarding/changes?")) result = config.changesReport || changesReport(saved, savedAnalysis, revision, new URL(url, "http://localhost").searchParams.get("comparison"));
      else if (url === "/api/onboarding/analysis-options") result = { profile: saved, revision, analysis_selection: savedAnalysis, catalog_version: catalogVersion, scope: analysisScope, status: analysisCandidates.length ? "ready" : "no_candidates", candidates: analysisCandidates, candidate_count: analysisCandidates.length, message: analysisCandidates.length ? "상권을 선택해 주세요." : "이 위치에 상권 후보가 없습니다. 가게 정보를 다시 확인해 주세요." };
      else if (url === "/api/onboarding/analysis-selection" && init.method === "POST") {
        const selected = analysisCandidates.find((candidate) => candidate.area_code === body.area_code);
        const period = selected?.availability.periods.find((entry) => entry.code === body.period);
        assert.ok(period?.available && !selected.selection_blocked_reason);
        savedAnalysis = analysisSelection({ area_code: selected.area_code, area_name: selected.name, period: period.code, period_label: period.label, industry_code: saved.industry.code, catalog_version: catalogVersion, availability: period });
        saved = { ...saved, revision: ++revision };
        result = { profile: saved, revision, analysis_selection: savedAnalysis, message: "분석 조건을 저장했습니다." };
      }
      else if (url === "/api/onboarding/locations/search") result = { search_id: "search-1", candidates: [candidate()] };
      else if (url === "/api/onboarding/locations/area-preview") result = { search_id: "area-1", candidates: [{ ...candidate("area-point"), label: "연남동 참고 위치" }] };
      else if (url === "/api/onboarding/profile" && init.method === "POST") {
        if (body.location || saved?.industry.code !== body.industry_code) savedAnalysis = null;
        let location = body.location;
        if (!location) location = saved.location;
        else if (location.kind === "address") location = { kind: "address", ...candidate(), verification: "verified_address" };
        else if (location.kind === "station") {
          const station = options.stations.find((item) => item.id === location.station_id);
          const line = options.station_lines.find((item) => item.code === location.station_line_code);
          assert.ok(station && line && station.selectable_line_codes?.includes(line.code));
          location = { ...station, kind: "station", station_id: station.id, station_line_code: line.code, station_line_name: line.name, label: station.name, verification: "verified_station" };
        }
        else {
          const neighborhood = options.neighborhoods.find((item) => item.code === location.neighborhood_code && item.district_code === location.district_code);
          assert.ok(neighborhood, "Only a catalogue neighborhood belonging to this district can be saved");
          location = { ...location, label: neighborhood.name, neighborhood_name: neighborhood.name, neighborhood_type: "administrative_dong", district_name: neighborhood.district_name, verification: location.search_id ? "geocoded_area_reference" : "selected_neighborhood", ...(location.search_id ? { reference_point: candidate("area-point") } : {}) };
        }
        saved = { revision: ++revision, location, industry: options.industries.find((item) => item.code === body.industry_code), business_status: body.business_status, business_status_label: options.business_statuses.find((item) => item.code === body.business_status)?.label, ready_for_analysis: false };
        result = { profile: saved, revision, analysis_selection: savedAnalysis };
      } else if (url.startsWith("/api/onboarding/profile?") && init.method === "DELETE") { saved = null; savedAnalysis = null; result = { profile: null, revision: ++revision }; }
      else throw new Error(`Unexpected request in test: ${url}`);
    }
    return { ok: !result.httpStatus || result.httpStatus < 400, status: result.httpStatus || 200, json: async () => structuredClone(result.payload || result) };
  };
  const Option = function(text, value) { const option = document.createElement("option"); option.textContent = text; option.value = value; return option; };
  vm.runInNewContext(source, { document, window, fetch, Option, AbortController, setTimeout, clearTimeout, console }, { filename: "onboarding.js" });
  await flush();
  assert.equal(document.getElementById("workspace").hidden, false, document.getElementById("app-message").textContent);
  const app = { document, window, calls, pickers, mapCenters, polygons, mapBounds, mapListeners, byId: (id) => document.getElementById(id), async input(id, value) { const node = this.byId(id); node.value = value; await node.emit("input"); await flush(); }, async click(id) { await this.byId(id).emit("click"); await flush(); }, async kind(value) { const radio = document.querySelector(`input[name="location-kind"][value="${value}"]`); radio.checked = true; await radio.emit("change"); await flush(); }, async selectAnalysis(code) { const radio = document.querySelector(`input[name="analysis-candidate"][value="${code}"]`); assert.ok(radio); radio.checked = true; await radio.emit("change"); await flush(); }, async selectQuarter(code) { this.byId("analysis-quarter").value = code; await this.byId("analysis-quarter").emit("change"); await flush(); }, async selectLine(code) { this.byId("station-line-select").value = code; await this.byId("station-line-select").emit("change"); await flush(); }, async selectStation(id) { this.byId("station-select").value = id; await this.byId("station-select").emit("change"); await flush(); }, async selectIndustry(code) { const select = this.byId("industry-select"); select.value = code; await select.emit("change"); }, async selectDistrict(code) { this.byId("district-select").value = code; await this.byId("district-select").emit("change"); await flush(); }, async selectNeighborhood(code) { this.byId("place-text").value = code; await this.byId("place-text").emit("change"); await flush(); }, async status(value = "planning") { const radio = document.querySelector(`input[name="business-status"][value="${value}"]`); radio.checked = true; await radio.emit("change"); }, async enter(id, extra = {}) { const event = await this.byId(id).emit("keydown", { key: "Enter", ...extra }); if (!event.defaultPrevented && !event.isComposing && event.keyCode !== 229) await this.byId("profile-form").emit("submit"); await flush(); return event; }, async submit() { await this.byId("profile-form").emit("submit"); await flush(); }, async complete(data, index = pickers.length - 1) { pickers[index].settings.oncomplete(data); await flush(); }, searches() { return calls.filter((call) => call.url === "/api/onboarding/locations/search"); }, saves() { return calls.filter((call) => call.url === "/api/onboarding/profile" && call.method === "POST"); }, previews() { return calls.filter((call) => call.url === "/api/onboarding/locations/area-preview"); }, industryOptions() { return this.byId("industry-select").options.filter((option) => option.value); } };
  app.selectComparisonDistrict = async (code) => { app.byId("comparison-district").value = code; await app.byId("comparison-district").emit("change"); await flush(); };
  app.selectComparisonArea = async (code) => { app.byId("comparison-area").value = code; await app.byId("comparison-area").emit("change"); await flush(); };
  app.selectChangesMode = async (mode) => { app.byId("changes-mode").value = mode; await app.byId("changes-mode").emit("change"); await flush(); };
  return app;
}
const roadSelection = { sido: "서울", userSelectedType: "R", roadAddress: "서울 중구 세종대로 110", jibunAddress: "서울 중구 태평로1가 31", autoRoadAddress: "서울 자동 도로 999", autoJibunAddress: "서울 자동동 999" };

test("all 100 official industries are available in grouped selection without a search input", async () => {
  const app = await createApp(), select = app.byId("industry-select");
  assert.equal(app.byId("industry-filter"), null);
  assert.equal(app.industryOptions().length, 100);
  assert.deepEqual(select.children.filter((node) => node.tagName === "OPTGROUP").map((group) => [group.label, group.options.length]), [["음식 (10)", 10], ["서비스 (47)", 47], ["소매·판매 (43)", 43]]);
  assert.equal(select.value, "");
  assert.deepEqual(app.industryOptions().map((option) => [option.value, option.textContent]), catalog.industries.map((item) => [item.code, item.name]));
  for (const item of catalog.industries) {
    await app.selectIndustry(item.code);
    assert.equal(select.value, item.code);
    assert.equal(app.byId("summary-industry").textContent, item.name);
    assert.equal(app.industryOptions().length, 100);
  }
});

test("the same chosen industry survives address, station and area method changes", async () => {
  const app = await createApp();
  await app.selectIndustry("CS100010");
  for (const kind of ["station", "area", "address"]) {
    await app.kind(kind);
    assert.equal(app.byId("industry-select").value, "CS100010");
    assert.equal(app.byId("summary-industry").textContent, "커피-음료");
    assert.equal(app.byId("industry-filter"), null);
    assert.equal(app.industryOptions().length, 100);
  }
  await app.selectIndustry("CS300028");
  assert.equal(app.byId("summary-industry").textContent, "화초");
});

test("clearing the industry requires explicit selection and never substitutes another category", async () => {
  const app = await createApp({ profile: profile() }); await app.click("edit-profile");
  await app.selectIndustry(""); await app.submit();
  assert.equal(app.saves().length, 0);
  assert.equal(app.byId("industry-select").value, "");
  assert.equal(app.byId("industry-error").hidden, false);
  assert.equal(app.industryOptions().length, 100);
});

test("saved profiles restore official codes; industry-only edits preserve the exact stored location", async () => {
  const app = await createApp({ profile: profile("CS200041") });
  assert.equal(app.byId("saved-industry").textContent, "사진관");
  await app.click("edit-profile");
  assert.equal(app.byId("industry-select").value, "CS200041");
  assert.equal(app.byId("address-query").value, profile().location.label);
  await app.selectIndustry("CS100010");
  await app.submit();
  assert.deepEqual(app.saves()[0].body, { location: null, industry_code: "CS100010", business_status: "operating", expected_revision: 7 });
  assert.equal(app.byId("saved-industry").textContent, "커피-음료");
  await app.click("edit-profile"); await app.selectIndustry("CS200038"); await app.click("cancel-edit");
  assert.equal(app.byId("saved-industry").textContent, "커피-음료");
});

test("Enter in industry selection cannot save and arrow keys retain native behavior", async () => {
  const app = await createApp({ profile: profile() }); await app.click("edit-profile");
  const event = await app.enter("industry-select");
  assert.equal(event.defaultPrevented, true); assert.equal(app.saves().length, 0);
  assert.equal((await app.byId("industry-select").emit("keydown", { key: "ArrowDown" })).defaultPrevented, false);
  assert.equal(app.byId("industry-select").value, "CS100010");
});

test("address typing never calls geocoding and cancels an earlier verified selection", async () => {
  const app = await createApp();
  await app.input("address-query", "세종대로"); assert.equal(app.searches().length, 0);
  await app.click("search-address"); await app.complete(roadSelection);
  assert.equal(app.searches().length, 1);
  await app.input("address-query", "다른 주소");
  assert.equal(app.byId("summary-location").textContent, "주소나 지역을 알려주세요");
  await app.selectIndustry("CS100010"); await app.status(); await app.submit();
  assert.equal(app.saves().length, 0); assert.equal(app.searches().length, 1);
  assert.equal(app.byId("location-error").hidden, false);
});

test("cancelled address dialogs ignore old provider callbacks", async () => {
  for (const cancelMethod of ["button", "escape"]) {
    const app = await createApp(); await app.click("search-address");
    if (cancelMethod === "button") await app.click("close-address-dialog");
    else await app.byId("address-dialog").emit("cancel");
    await app.complete(roadSelection);
    assert.equal(app.searches().length, 0); assert.equal(app.byId("address-dialog").open, false);
  }
});

test("non-Seoul selections are rejected before server geocoding", async () => {
  const app = await createApp(); await app.click("search-address");
  await app.complete({ ...roadSelection, sido: "경기", roadAddress: "경기 수원시 팔달구 효원로 1" });
  assert.equal(app.searches().length, 0);
  assert.match(app.byId("location-error").textContent, /서울특별시/);
});

test("clicked road address (including noSelected Y) is reverified, then unique Seoul candidate is selected", async () => {
  const app = await createApp(); await app.input("address-query", "시청"); await app.enter("address-query");
  assert.equal(app.pickers[0].embedSettings.q, "시청");
  await app.complete({ ...roadSelection, noSelected: "Y", buildingName: "서울시청" });
  assert.deepEqual(app.searches()[0].body, { query: roadSelection.roadAddress });
  assert.equal(app.byId("address-query").value, candidate().road_address);
  assert.equal(app.byId("address-results-wrap").hidden, true);
  assert.equal(app.byId("summary-location").textContent, candidate().label);
  assert.equal(app.mapCenters.at(-1).latitude, candidate().latitude);
  await app.selectIndustry("CS100010"); await app.status(); await app.submit();
  assert.deepEqual(app.saves()[0].body.location, { kind: "address", search_id: "search-1", candidate_id: "address-1" });
});

test("clicked jibun field alone is sent; inferred auto addresses never substitute missing fields", async () => {
  const app = await createApp(); await app.click("search-address");
  await app.complete({ ...roadSelection, userSelectedType: "J" });
  assert.deepEqual(app.searches()[0].body, { query: roadSelection.jibunAddress });
  for (const data of [{ ...roadSelection, roadAddress: "" }, { ...roadSelection, userSelectedType: "J", jibunAddress: "" }, null]) {
    const other = await createApp(); await other.click("search-address"); await other.complete(data);
    assert.equal(other.searches().length, 0);
  }
});

test("address input changes, tab switches and reopening invalidate previous iframe callbacks", async () => {
  for (const action of ["input", "tab", "reopen"]) {
    const app = await createApp(); await app.click("search-address");
    if (action === "input") await app.input("address-query", "새 검색어");
    if (action === "tab") await app.kind("station");
    if (action === "reopen") await app.click("search-address");
    await app.complete(roadSelection, 0);
    assert.equal(app.searches().length, 0, action);
  }
});

test("late server verification cannot overwrite a newer selected address", async () => {
  let resolveOld, searches = 0;
  const app = await createApp({ fetch: (url) => {
    if (url !== "/api/onboarding/locations/search") return undefined;
    if (++searches === 1) return new Promise((resolve) => { resolveOld = resolve; });
    return { search_id: "search-new", candidates: [{ ...candidate("new"), label: "서울 새 주소", road_address: "서울 새 주소" }] };
  } });
  await app.click("search-address"); await app.complete(roadSelection);
  await app.input("address-query", "새 주소"); await app.click("search-address"); await app.complete(roadSelection);
  resolveOld({ search_id: "search-old", candidates: [candidate("old")] }); await flush();
  assert.equal(app.searches()[0].signal.aborted, true);
  assert.equal(app.byId("address-query").value, "서울 새 주소");
  await app.selectIndustry("CS100010"); await app.status(); await app.submit();
  assert.equal(app.saves()[0].body.location.candidate_id, "new");
});

test("multiple verified candidates require explicit keyboard selection; outside candidates stay disabled", async () => {
  const app = await createApp({ fetch: (url) => url === "/api/onboarding/locations/search" ? { search_id: "multiple", candidates: [candidate("first"), candidate("second"), { ...candidate("outside"), in_seoul: false }] } : undefined });
  await app.click("search-address"); await app.complete(roadSelection);
  assert.equal(app.byId("address-results-wrap").hidden, false);
  assert.equal(app.document.querySelector('input[name="address-candidate"]:checked'), null);
  assert.equal(app.byId("address-candidate-2").disabled, true);
  await app.byId("address-candidate-1").emit("keydown", { key: "Enter" });
  await app.selectIndustry("CS100010"); await app.status(); await app.submit();
  assert.equal(app.saves()[0].body.location.candidate_id, "second");
});

test("address SDK errors offer exact-address verification fallback", async () => {
  const app = await createApp(); delete app.window.kakao;
  await app.input("address-query", roadSelection.roadAddress);
  const opening = app.byId("search-address").emit("click");
  const script = app.document.head.children.at(-1);
  assert.match(script.src, /postcode\.v2\.js/); script.onerror(); await opening;
  assert.equal(app.byId("verify-address").hidden, false);
  assert.equal(app.byId("address-dialog").open, false);
  await app.click("verify-address");
  assert.deepEqual(app.searches()[0].body, { query: roadSelection.roadAddress });
  assert.equal(app.byId("address-results-wrap").hidden, false, "Fallback verification still needs candidate selection");
});

test("Korean composition Enter in the address field cannot search or save", async () => {
  const app = await createApp({ profile: profile() }); await app.click("edit-profile");
  await app.byId("address-query").emit("compositionstart");
  await app.enter("address-query", { isComposing: true, keyCode: 229 });
  await app.submit();
  assert.equal(app.saves().length, 0); assert.equal(app.searches().length, 0); assert.equal(app.pickers.length, 0);
  await app.byId("address-query").emit("compositionend");
});

test("selected line and station IDs are saved and restored together", async () => {
  const app = await createApp(); await app.kind("station");
  await app.selectLine("line4"); await app.selectStation("station-isu");
  await app.selectIndustry("CS200009"); await app.status("operating"); await app.submit();
  assert.deepEqual(app.saves()[0].body.location, { kind: "station", station_id: "station-isu", station_line_code: "line4" });
  assert.match(app.byId("saved-verification").textContent, /4호선/);
  await app.click("edit-profile");
  assert.equal(app.byId("station-line-select").value, "line4");
  assert.equal(app.byId("station-select").value, "station-isu");
});

test("station selection follows API line order and explicit operating-line mappings, never raw lines", async () => {
  const app = await createApp(); await app.kind("station");
  assert.equal(app.byId("station-query"), null);
  assert.equal(app.byId("station-select").disabled, true);
  assert.deepEqual(app.byId("station-line-select").options.filter((option) => option.value).map((option) => option.value), stationLines.map((line) => line.code));
  await app.selectLine("gyeongui");
  assert.deepEqual(app.byId("station-select").options.map((option) => option.textContent), ["역을 선택해 주세요", "서빙고역", "용산역"]);
  assert.equal(app.byId("station-select").value, "", "Choosing a line does not choose its first station");
  await app.selectLine("line1");
  assert.deepEqual(app.byId("station-select").options.filter((option) => option.value).map((option) => option.value), ["station-yongsan"]);
  await app.selectLine("line2");
  assert.deepEqual(app.byId("station-select").options.filter((option) => option.value).map((option) => option.value), ["station-gangnam-2"]);
});

test("station options preserve parenthetical official names instead of collapsing distinct station IDs", async () => {
  const records = [
    { ...stations[0], id: "cheongnyangni-main", name: "청량리역", selectable_line_codes: ["line1"] },
    { ...stations[0], id: "cheongnyangni-subname", name: "청량리역(서울시립대입구)", selectable_line_codes: ["line1"] },
  ];
  const app = await createApp({ stations: records }); await app.kind("station"); await app.selectLine("line1");
  assert.deepEqual(app.byId("station-select").options.filter((option) => option.value).map((option) => [option.value, option.textContent]), records.map((station) => [station.id, station.name]));
});

test("changing line clears the selected station and map while retaining the common industry", async () => {
  const app = await createApp(); await app.kind("station"); await app.selectIndustry("CS100010");
  await app.selectLine("line2"); await app.selectStation("station-gangnam-2");
  assert.equal(app.byId("summary-location").textContent, "강남구 · 강남역");
  assert.equal(app.byId("map-overlay").hidden, true);
  await app.selectLine("shin");
  assert.equal(app.byId("station-select").value, "");
  assert.equal(app.byId("summary-location").textContent, "주소나 지역을 알려주세요");
  assert.equal(app.byId("station-selection-note").hidden, true);
  assert.equal(app.byId("map-overlay").hidden, false);
  assert.equal(app.byId("industry-select").value, "CS100010");
  await app.status(); await app.submit(); assert.equal(app.saves().length, 0);
  await app.selectStation("station-gangnam-new"); await app.submit();
  assert.deepEqual(app.saves()[0].body.location, { kind: "station", station_id: "station-gangnam-new", station_line_code: "shin" });
});

test("missing station mappings and station IDs from another line cannot be selected or saved", async () => {
  const missing = await createApp({ stationLines: [] }); await missing.kind("station");
  assert.equal(missing.byId("station-line-select").disabled, true);
  assert.equal(missing.byId("station-select").disabled, true);
  const unmapped = await createApp({ stations: [stations.find((item) => item.id === "station-unmapped")] });
  await unmapped.kind("station"); await unmapped.selectLine("line2");
  assert.equal(unmapped.byId("station-select").disabled, true);
  const app = await createApp(); await app.kind("station"); await app.selectLine("line2");
  const option = app.document.createElement("option"); option.value = "station-gangnam-new";
  app.byId("station-select").append(option); await app.selectStation(option.value);
  await app.selectIndustry("CS100010"); await app.status(); await app.submit();
  assert.equal(app.saves().length, 0); assert.equal(app.byId("location-error").hidden, false);
});

test("a saved explicit operating line is restored even when its station belongs to multiple lines", async () => {
  const app = await createApp({ profile: stationProfile("station-yongsan", { station_line_code: "gyeongui", station_line_name: "경의·중앙선" }) });
  await app.click("edit-profile");
  assert.equal(app.byId("station-line-select").value, "gyeongui");
  assert.equal(app.byId("station-select").value, "station-yongsan");
  await app.selectIndustry("CS200041"); await app.submit();
  assert.equal(app.saves()[0].body.location, null);
  assert.equal(app.byId("saved-location").textContent, "용산역");
});

test("legacy station profiles restore only an unambiguous line and preserve the original location", async () => {
  const single = await createApp({ profile: stationProfile() }); await single.click("edit-profile");
  assert.equal(single.byId("station-line-select").value, "line4");
  assert.equal(single.byId("station-select").value, "station-isu");
  await single.selectIndustry("CS200041"); await single.submit();
  assert.equal(single.saves()[0].body.location, null);
  for (const saved of [stationProfile("station-yongsan"), stationProfile("removed-station", { district_name: "마포구" }), stationProfile("station-isu", { station_line_code: "removed-line" })]) {
    const app = await createApp({ profile: saved }); await app.click("edit-profile");
    assert.equal(app.byId("station-line-select").value, "");
    assert.equal(app.byId("station-select").value, "");
    assert.equal(app.byId("station-select").disabled, true);
    assert.match(app.byId("station-selection-note").textContent, /기존 위치.*유지/);
    await app.selectIndustry("CS200041"); await app.submit();
    assert.equal(app.saves()[0].body.location, null);
    assert.equal(app.byId("saved-location").textContent, saved.location.label);
  }
});

test("changing a legacy station line requires a new station, while cancelling restores the saved location", async () => {
  const app = await createApp({ profile: stationProfile("station-yongsan") }); await app.click("edit-profile");
  await app.selectLine("line4"); await app.submit();
  assert.equal(app.saves().length, 0); assert.equal(app.byId("station-selection-note").hidden, true);
  await app.selectStation("station-isu"); await app.click("cancel-edit");
  assert.equal(app.byId("saved-location").textContent, "용산역");
  await app.click("edit-profile");
  assert.equal(app.byId("station-line-select").value, "");
});

test("Enter in line and station selectors cannot save and arrow keys remain native", async () => {
  const app = await createApp({ profile: stationProfile() }); await app.click("edit-profile");
  for (const id of ["station-line-select", "station-select"]) {
    assert.equal((await app.enter(id)).defaultPrevented, true);
    assert.equal((await app.byId(id).emit("keydown", { key: "ArrowDown" })).defaultPrevented, false);
  }
  assert.equal(app.saves().length, 0); assert.equal(app.searches().length, 0);
});

test("area reference selection is cleared on neighborhood change and selected dong remains saveable", async () => {
  const app = await createApp(); await app.kind("area");
  await app.selectDistrict("11440");
  await app.selectNeighborhood("test-mapo-yeonnam"); await app.click("preview-area");
  const radio = app.document.querySelector('input[name="area-candidate"]'); radio.checked = true; await radio.emit("change");
  await app.selectNeighborhood("test-mapo-seogyo");
  assert.equal(app.byId("area-results-wrap").hidden, true);
  assert.equal(app.byId("map-overlay").hidden, false);
  assert.equal(app.byId("summary-location").textContent, "마포구 · 서교동");
  await app.selectIndustry("CS300028"); await app.status("exploring"); await app.submit();
  assert.deepEqual(app.saves()[0].body.location, { kind: "area", district_code: "11440", neighborhood_code: "test-mapo-seogyo" });
  assert.match(app.byId("saved-verification").textContent, /행정동을 선택/);
});

test("SDK cleanup failures cannot prevent tab switching, summary updates or saving", async () => {
  const app = await createApp({ profile: profile(), brokenMarker: true }); await app.click("edit-profile");
  await app.kind("area"); assert.equal(app.byId("area-panel").hidden, false);
  await app.selectDistrict("11440"); await app.selectNeighborhood("test-mapo-yeonnam");
  await app.submit(); assert.equal(app.saves().length, 1);
  assert.match(app.byId("saved-location").textContent, /연남동/);
});

test("dong selector starts disabled and shows only the chosen district in Korean name order", async () => {
  const app = await createApp(); await app.kind("area");
  assert.equal(app.byId("place-text").tagName, "SELECT");
  assert.equal(app.byId("place-text").disabled, true);
  assert.match(app.byId("place-text").options[0].textContent, /자치구를 먼저/);
  assert.equal(app.byId("preview-area").disabled, true);
  await app.selectDistrict("11440");
  assert.deepEqual(app.byId("place-text").options.map((option) => option.textContent), ["동네를 선택해 주세요", "서교동", "연남동", "합정동"]);
  assert.equal(app.byId("place-text").disabled, false); assert.equal(app.byId("place-text").value, "");
  await app.selectNeighborhood("test-mapo-yeonnam");
  assert.equal(app.byId("preview-area").disabled, false);
  assert.equal(app.previews().length, 0, "Selecting a dong must not call external geocoding");
  await app.selectDistrict("11200");
  assert.deepEqual(app.byId("place-text").options.map((option) => option.textContent), ["동네를 선택해 주세요", "성수1가1동"]);
  assert.equal(app.byId("place-text").value, ""); assert.equal(app.byId("preview-area").disabled, true);
  assert.equal(app.byId("summary-location").textContent, "주소나 지역을 알려주세요");
});

test("missing district catalogue stays disabled and arbitrary or foreign-district codes cannot be saved", async () => {
  const empty = await createApp({ neighborhoods: [] }); await empty.kind("area"); await empty.selectDistrict("11440");
  assert.equal(empty.byId("place-text").disabled, true);
  assert.match(empty.byId("place-help").textContent, /목록을 불러오지 못했/);
  const app = await createApp(); await app.kind("area"); await app.selectDistrict("11440");
  await app.selectIndustry("CS100010"); await app.status();
  for (const code of ["not-a-dong", "test-seongdong-seongsu"]) {
    const option = app.document.createElement("option"); option.value = code;
    app.byId("place-text").append(option); await app.selectNeighborhood(code);
    await app.submit(); assert.equal(app.saves().length, 0);
    assert.equal(app.byId("preview-area").disabled, true);
    assert.match(app.byId("location-error").textContent, /해당 구의 동네/);
  }
});

test("district and dong Enter cannot save a valid form or trigger map lookup, while arrows remain native", async () => {
  const app = await createApp({ profile: areaProfile() }); await app.click("edit-profile");
  for (const id of ["district-select", "place-text"]) {
    assert.equal((await app.enter(id)).defaultPrevented, true);
    assert.equal((await app.byId(id).emit("keydown", { key: "ArrowDown" })).defaultPrevented, false);
  }
  assert.equal(app.saves().length, 0); assert.equal(app.previews().length, 0);
});

test("area lookup and save send only selected codes plus the chosen reference ids", async () => {
  const app = await createApp(); await app.kind("area"); await app.selectDistrict("11440");
  await app.selectNeighborhood("test-mapo-yeonnam"); await app.click("preview-area");
  assert.deepEqual(app.previews()[0].body, { kind: "area", district_code: "11440", neighborhood_code: "test-mapo-yeonnam" });
  const radio = app.document.querySelector('input[name="area-candidate"]'); radio.checked = true; await radio.emit("change");
  await app.selectIndustry("CS100010"); await app.status(); await app.submit();
  assert.deepEqual(app.saves()[0].body.location, { kind: "area", district_code: "11440", neighborhood_code: "test-mapo-yeonnam", search_id: "area-1", candidate_id: "area-point" });
  assert.equal(app.byId("saved-location").textContent, "연남동");
  assert.match(app.byId("saved-verification").textContent, /참고 위치/);
});

test("changing district, dong or tab aborts a pending area lookup and rejects late candidates", async () => {
  for (const change of ["district", "dong", "tab"]) {
    let resolveLookup;
    const app = await createApp({ fetch: (url) => url.endsWith("area-preview") ? new Promise((resolve) => { resolveLookup = resolve; }) : undefined });
    await app.kind("area"); await app.selectDistrict("11440"); await app.selectNeighborhood("test-mapo-yeonnam");
    const lookup = app.byId("preview-area").emit("click");
    if (change === "district") await app.selectDistrict("11200");
    if (change === "dong") await app.selectNeighborhood("test-mapo-seogyo");
    if (change === "tab") await app.kind("station");
    resolveLookup({ search_id: "old", candidates: [candidate("old-area")] }); await lookup;
    assert.equal(app.previews()[0].signal.aborted, true, change);
    assert.equal(app.byId("area-results-wrap").hidden, true, change);
    assert.equal(app.byId("area-results").children.length, 0, change);
  }
});

test("new area profiles restore dong codes and preserve stored reference points during industry-only edits", async () => {
  const original = areaProfile({ verification: "geocoded_area_reference", reference_point: candidate() });
  const app = await createApp({ profile: original }); await app.click("edit-profile");
  assert.equal(app.byId("district-select").value, "11440");
  assert.equal(app.byId("place-text").value, "test-mapo-yeonnam");
  assert.equal(app.byId("map-location-title").textContent, "연남동");
  await app.selectIndustry("CS300028"); await app.submit();
  assert.equal(app.saves()[0].body.location, null);
  assert.equal(app.byId("saved-location").textContent, "연남동");
  assert.match(app.byId("saved-verification").textContent, /참고 위치/);
});

test("legacy matching names may display a dong but are not silently migrated on save", async () => {
  const legacy = areaProfile({ neighborhood_code: undefined, neighborhood_name: undefined, neighborhood_type: undefined, text: "연남동", verification: "user_declared" });
  const app = await createApp({ profile: legacy }); await app.click("edit-profile");
  assert.equal(app.byId("place-text").value, "test-mapo-yeonnam");
  await app.selectIndustry("CS300028"); await app.submit();
  assert.equal(app.saves()[0].body.location, null);
  assert.match(app.byId("saved-verification").textContent, /직접 입력/);
});

test("unmatched legacy areas keep their original location until the user changes district or dong", async () => {
  const legacy = areaProfile({ neighborhood_code: undefined, neighborhood_name: undefined, neighborhood_type: undefined, label: "홍대 근처", text: "홍대 근처", verification: "user_declared" });
  const app = await createApp({ profile: legacy }); await app.click("edit-profile");
  assert.equal(app.byId("place-text").value, "");
  assert.match(app.byId("saved-area-note").textContent, /홍대 근처.*유지/);
  assert.equal(app.byId("preview-area").disabled, true);
  await app.selectIndustry("CS300028"); await app.submit();
  assert.equal(app.saves()[0].body.location, null);
  assert.equal(app.byId("saved-location").textContent, "홍대 근처");
  await app.click("edit-profile"); await app.selectDistrict("11200"); await app.submit();
  assert.equal(app.saves().length, 1, "Changing the district requires a fresh dong selection");
  assert.equal(app.byId("saved-area-note").hidden, true);
  await app.selectNeighborhood("test-seongdong-seongsu"); await app.submit();
  assert.deepEqual(app.saves()[1].body.location, { kind: "area", district_code: "11200", neighborhood_code: "test-seongdong-seongsu" });
});

test("clear profile resets fields and carries the monotonic revision into the next save", async () => {
  const app = await createApp({ profile: profile() }); await app.click("show-clear");
  assert.equal(app.byId("clear-confirmation").hidden, false);
  await app.click("confirm-clear");
  assert.equal(app.calls.find((call) => call.method === "DELETE").url, "/api/onboarding/profile?expected_revision=7");
  assert.equal(app.byId("industry-select").value, ""); assert.equal(app.byId("address-query").value, "");
  await app.kind("station"); await app.selectLine("line4"); await app.selectStation("station-isu");
  await app.selectIndustry("CS200041"); await app.status(); await app.submit();
  assert.equal(app.saves()[0].body.expected_revision, 8);
});

test("real HTML label and ARIA references resolve and every form control has a label", async () => {
  const app = await createApp();
  const nodes = descendants(app.document.root), ids = nodes.filter((node) => node.id).map((node) => node.id);
  assert.equal(new Set(ids).size, ids.length, "Duplicate ids");
  for (const node of nodes) {
    for (const attr of ["aria-describedby", "aria-labelledby", "aria-controls"])
      for (const id of (node.getAttribute(attr) || "").split(/\s+/).filter(Boolean)) assert.ok(app.byId(id), `${attr} target ${id}`);
    if (node.tagName === "LABEL" && node.getAttribute("for")) assert.ok(app.byId(node.getAttribute("for")));
    if (!["INPUT", "SELECT"].includes(node.tagName)) continue;
    const explicit = node.id && nodes.some((label) => label.tagName === "LABEL" && label.getAttribute("for") === node.id);
    let parent = node.parentNode, wrapped = false;
    while (parent) { if (parent.tagName === "LABEL") wrapped = true; parent = parent.parentNode; }
    assert.ok(explicit || wrapped || node.getAttribute("aria-label"), `${node.id || node.name} needs a label`);
  }
});

test("analysis is an explicit next step and the first loaded candidate set draws polygons and fits its extent", async () => {
  const app = await createApp({ profile: profile() });
  assert.equal(app.calls.filter((call) => call.url.endsWith("analysis-options")).length, 0);
  assert.equal(app.byId("analysis-panel").hidden, true);
  await app.click("open-analysis");
  assert.equal(app.byId("analysis-panel").hidden, false);
  assert.equal(app.byId("saved-overview").hidden, true);
  assert.equal(app.byId("analysis-candidates").children.length, 2);
  assert.equal(app.polygons.filter((polygon) => polygon.map).length, 2, "Empty loading state must not cache away the loaded geometries");
  assert.ok(app.mapBounds.length > 0);
  assert.ok(app.mapBounds.at(-1).northeast.latitude > app.mapBounds.at(-1).southwest.latitude);
  assert.equal(app.byId("save-analysis").disabled, true, "No candidate is chosen automatically");
  assert.equal(app.document.querySelector('input[name="analysis-candidate"]:checked'), null);
});

test("polygon clicks and list choices stay in sync without saving automatically", async () => {
  const app = await createApp({ profile: profile() }); await app.click("open-analysis");
  const listener = app.mapListeners.find((item) => !item.removed);
  listener.callback(); await flush();
  assert.equal(app.document.querySelector('input[name="analysis-candidate"]:checked').value, "market-a");
  assert.equal(app.byId("analysis-selected-name").textContent, "세종대로 상권");
  assert.equal(app.byId("analysis-quarter").value, "20262");
  await app.selectAnalysis("market-b");
  assert.equal(app.byId("map-location-title").textContent, "인근 상권");
  assert.equal(app.document.querySelector('input[name="analysis-candidate"]:checked').value, "market-b");
  assert.equal(app.calls.filter((call) => call.url.endsWith("analysis-selection") && call.method === "POST").length, 0);
});

test("coverage treats zero as present, links each source and checks actual previous-quarter/year records", async () => {
  const area = analysisCandidate(); area.availability.periods[0].metrics.sales.zero_observation = true;
  const app = await createApp({ profile: profile(), analysisCandidates: [area] }); await app.click("open-analysis"); await app.selectAnalysis("market-a");
  assert.match(app.byId("analysis-coverage").textContent, /관측값 0/);
  assert.match(app.byId("analysis-coverage").textContent, /전분기: 비교 기간 자료 있음/);
  assert.match(app.byId("analysis-coverage").textContent, /전년 동기: 비교 기간 자료 있음/);
  assert.equal(app.byId("analysis-coverage").querySelectorAll("a").length, 3);
  assert.deepEqual(app.byId("analysis-coverage").querySelectorAll("a").map((node) => node.href), ["https://data.seoul.go.kr/sales", "https://data.seoul.go.kr/stores", "https://data.seoul.go.kr/floating_population"]);
  await app.selectQuarter("20261");
  assert.match(app.byId("analysis-coverage").textContent, /전분기: 비교 분기 자료 없음/, "2026Q1 must check 2025Q4, not the nearest available quarter");
  assert.match(app.byId("analysis-coverage").textContent, /전년 동기: 비교 분기 자료 없음/);
  assert.match(app.byId("analysis-comparison-note").textContent, /증감 분석 결과는 아니/);
});

test("population-only availability is explicit, saves with revisions and restores the exact area and quarter", async () => {
  const app = await createApp({ profile: profile() }); await app.click("open-analysis"); await app.selectAnalysis("market-b");
  await app.selectQuarter("20261");
  assert.match(app.byId("analysis-data-message").textContent, /선택 업종의 매출·점포 자료는 없/);
  assert.match(app.byId("analysis-save-message").textContent, /지역 유동인구만/);
  await app.click("save-analysis");
  const request = app.calls.find((call) => call.url.endsWith("analysis-selection") && call.method === "POST");
  assert.deepEqual(request.body, { area_code: "market-b", period: "20261", expected_revision: 7, expected_catalog_version: "catalog-v1" });
  assert.equal(app.byId("save-analysis").disabled, true);
  assert.equal(app.byId("analysis-quarter").disabled, false, "Saved settings remain editable");
  assert.match(app.byId("analysis-save-message").textContent, /분석 조건 저장 완료.*분석 결과/);
  await app.click("analysis-back");
  assert.match(app.byId("saved-analysis-note").textContent, /인근 상권.*2026년 1분기/);
  assert.match(app.byId("saved-verification").textContent, /인근 상권/);
  assert.doesNotMatch(app.byId("map-location-note").textContent, /다음 단계에서 정해/);
  await app.click("open-analysis");
  assert.equal(app.document.querySelector('input[name="analysis-candidate"]:checked').value, "market-b");
  assert.equal(app.byId("analysis-quarter").value, "20261");
  assert.equal(app.byId("save-analysis").disabled, true);
  await app.selectQuarter("20262"); await app.click("save-analysis");
  assert.equal(app.calls.filter((call) => call.url.endsWith("analysis-selection") && call.method === "POST").at(-1).body.expected_revision, 8);
});

test("no-data periods and a blocked boundary identity remain inspectable but cannot be saved", async () => {
  for (const blocked of [false, true]) {
    const area = analysisCandidate("market-empty", "none");
    if (blocked) area.selection_blocked_reason = "경계와 상권 명칭의 연결 확인이 필요합니다.";
    const app = await createApp({ profile: profile(), analysisCandidates: [area] }); await app.click("open-analysis"); await app.selectAnalysis("market-empty");
    assert.equal(app.byId("analysis-data-section").hidden, false);
    assert.equal(app.byId("analysis-quarter").disabled, true);
    assert.match(app.byId("analysis-quarter").options[1].textContent, blocked ? /연결 확인 필요/ : /확인된 자료 없음/);
    assert.equal(app.byId("save-analysis").disabled, true);
    await app.click("save-analysis");
    assert.equal(app.calls.filter((call) => call.url.endsWith("analysis-selection") && call.method === "POST").length, 0);
    assert.match(app.byId("analysis-data-message").textContent, blocked ? /연결 확인/ : /확인된 자료가 없어/);
  }
});

test("stale and unavailable saved settings are never presented as a completed unchanged selection", async () => {
  for (const status of ["stale", "unavailable"]) {
    const saved = analysisSelection({ status, analysis_setup_complete: false, conditions_confirmed: false, message: "분석 조건을 다시 확인해 주세요." });
    const app = await createApp({ profile: profile(), analysisSelection: saved });
    assert.match(app.byId("saved-analysis-note").textContent, /다시 확인/);
    assert.doesNotMatch(app.byId("saved-analysis-note").textContent, /저장 완료/);
    await app.click("open-analysis");
    assert.equal(app.byId("save-analysis").disabled, false);
    assert.match(app.byId("analysis-data-message").textContent, /다시 확인/);
  }
});

test("analysis catalogue network errors keep the profile usable and can be retried", async () => {
  let attempts = 0;
  const app = await createApp({ profile: profile(), fetch: (url) => {
    if (url.endsWith("analysis-options") && ++attempts === 1) return { httpStatus: 503, payload: { detail: "상권 자료를 불러오지 못했습니다." } };
  } });
  await app.click("open-analysis");
  assert.equal(app.byId("analysis-retry").hidden, false);
  assert.match(app.byId("analysis-load-message").textContent, /불러오지 못/);
  assert.equal(app.byId("save-analysis").disabled, true);
  await app.click("analysis-retry");
  assert.equal(app.byId("analysis-candidates").children.length, 2);
  await app.click("analysis-back"); assert.equal(app.byId("saved-location").textContent, profile().location.label);
});

test("leaving analysis aborts its request and a late response cannot redraw the old candidates", async () => {
  let resolveLookup;
  const app = await createApp({ profile: profile(), fetch: (url) => url.endsWith("analysis-options") ? new Promise((resolve) => { resolveLookup = resolve; }) : undefined });
  const opening = app.byId("open-analysis").emit("click");
  await app.click("analysis-back");
  resolveLookup({ profile: profile(), revision: 7, catalog_version: "old", candidates: [analysisCandidate()], scope: analysisScope }); await opening;
  assert.equal(app.calls.find((call) => call.url.endsWith("analysis-options")).signal.aborted, true);
  assert.equal(app.byId("analysis-panel").hidden, true);
  assert.equal(app.byId("saved-overview").hidden, false);
  assert.equal(app.polygons.filter((polygon) => polygon.map).length, 0);
});

test("saving revision conflicts requires a fresh candidate list before another explicit save", async () => {
  let saves = 0, loads = 0;
  const app = await createApp({ profile: profile(), fetch: (url, init) => {
    if (url.endsWith("analysis-selection") && init.method === "POST" && ++saves === 1) return { httpStatus: 409, payload: { detail: "자료 목록이 변경됐습니다. 다시 확인해 주세요." } };
    if (url.endsWith("analysis-options") && ++loads > 1) return { profile: { ...profile(), revision: 9 }, revision: 9, analysis_selection: null, catalog_version: "catalog-v2", candidates: [analysisCandidate()], scope: analysisScope };
  } });
  await app.click("open-analysis"); await app.selectAnalysis("market-a"); await app.click("save-analysis");
  assert.equal(app.byId("save-analysis").disabled, true); assert.equal(app.byId("analysis-retry").hidden, false);
  assert.match(app.byId("analysis-data-message").textContent, /다시 확인/);
  await app.click("analysis-retry"); await app.selectAnalysis("market-a"); await app.click("save-analysis");
  assert.deepEqual(app.calls.filter((call) => call.url.endsWith("analysis-selection") && call.method === "POST").at(-1).body, { area_code: "market-a", period: "20262", expected_revision: 9, expected_catalog_version: "catalog-v2" });
});

test("profile status-only changes retain analysis settings and an industry change invalidates them", async () => {
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection() }); await app.click("edit-profile");
  await app.status("planning"); await app.submit();
  assert.match(app.byId("saved-analysis-note").textContent, /분석 조건 저장 완료/);
  await app.click("edit-profile"); await app.selectIndustry("CS300028"); await app.submit();
  assert.equal(app.byId("open-analysis").textContent, "분석 상권 설정");
  assert.doesNotMatch(app.byId("saved-analysis-note").textContent, /세종대로 상권/);
});

test("polygon SDK failures do not prevent choosing and saving an analysis area", async () => {
  const app = await createApp({ profile: profile(), brokenPolygon: true }); await app.click("open-analysis"); await app.selectAnalysis("market-a");
  assert.equal(app.byId("map-overlay").hidden, false);
  assert.match(app.byId("map-status").textContent, /목록에서 상권을 선택/);
  await app.click("save-analysis");
  assert.match(app.byId("analysis-save-message").textContent, /분석 조건 저장 완료/);
});

test("a station without coordinates and no candidates gets a terminal empty-state message", async () => {
  const app = await createApp({ profile: stationProfile(), analysisCandidates: [] }); await app.click("open-analysis");
  assert.equal(app.byId("save-analysis").disabled, true);
  assert.match(app.byId("map-overlay-title").textContent, /표시할 상권 후보가 없/);
  assert.doesNotMatch(app.byId("map-overlay-title").textContent, /확인하고/);
  assert.equal(app.byId("analysis-data-section").hidden, true);
});

test("MultiPolygon parts and holes are preserved and leaving analysis clears every overlay/listener", async () => {
  const area = analysisCandidate();
  area.geometry = { type: "MultiPolygon", coordinates: [area.geometry.coordinates, [[[126.981, 37.565], [126.983, 37.565], [126.983, 37.567], [126.981, 37.565]]]] };
  const app = await createApp({ profile: profile(), analysisCandidates: [area], brokenPolygonCleanup: true }); await app.click("open-analysis");
  assert.deepEqual(app.polygons.filter((polygon) => polygon.map).map((polygon) => polygon.settings.paths.length), [2, 1]);
  assert.equal(app.polygons[0].settings.paths[1].length, 5);
  await app.selectAnalysis("market-a");
  const count = app.mapBounds.length; await app.click("map-recenter"); assert.ok(app.mapBounds.length > count);
  await app.click("analysis-back");
  assert.equal(app.polygons.filter((polygon) => polygon.map).length, 0);
  assert.ok(app.mapListeners.every((listener) => listener.removed));
  assert.equal(app.byId("map-heading").textContent, "지도에서 위치를 확인하세요.");
});

test("neighborhood-only matching does not describe its candidates as a radius search", async () => {
  const area = analysisCandidate(); area.relation = "neighborhood"; area.distance_m = null;
  const app = await createApp({ profile: areaProfile(), analysisCandidates: [area] }); await app.click("open-analysis"); await app.selectAnalysis("market-a");
  assert.match(app.byId("analysis-candidates").textContent, /선택한 행정동/);
  assert.doesNotMatch(app.byId("analysis-sources").textContent, /1,000m/);
  assert.match(app.byId("map-status").textContent, /기준 위치의 좌표는 없어/);
});

test("sales is unavailable before confirmed analysis settings and for stale or unavailable selections", async () => {
  for (const selection of [null, analysisSelection({ status: "stale", analysis_setup_complete: false }), analysisSelection({ status: "unavailable", analysis_setup_complete: false })]) {
    const app = await createApp({ profile: profile(), analysisSelection: selection });
    assert.equal(app.byId("view-sales-overview").hidden, true);
    await app.click("view-sales-overview");
    assert.equal(app.byId("sales-panel").hidden, true);
    assert.equal(app.calls.filter((call) => call.url.startsWith("/api/onboarding/sales?")).length, 0);
  }
});

test("saved settings open a read-only full-width sales view with exact amounts and 7/6/6 table rows", async () => {
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection() });
  assert.equal(app.byId("view-sales-overview").hidden, false);
  await app.click("view-sales-overview");
  assert.equal(app.calls.find((call) => call.url.startsWith("/api/onboarding/sales?")).url, "/api/onboarding/sales?expected_revision=7");
  assert.equal(app.calls.filter((call) => call.method !== "GET").length, 0);
  assert.equal(app.byId("sales-panel").hidden, false);
  assert.equal(app.byId("profile-location-column").hidden, true);
  assert.equal(app.byId("sales-total").textContent, "1,000,000원");
  assert.deepEqual(app.byId("sales-distributions").querySelectorAll("tbody").map((body) => body.children.length), [7, 6, 6]);
  assert.equal(app.byId("sales-summary").children[0].textContent, "서버가 확인한 매출 요약입니다.");
  assert.equal(app.byId("sales-sources").children[0].href, "https://data.seoul.go.kr/sales");
  assert.ok(app.byId("sales-distributions").querySelectorAll("th").every((cell) => ["col", "row"].includes(cell.getAttribute("scope"))));
  assert.ok(app.byId("sales-distributions").querySelectorAll(".sales-bar-track").every((bar) => bar.getAttribute("aria-hidden") === "true"));
});

test("saving analysis exposes the sales action immediately and an unsaved period change hides it", async () => {
  const app = await createApp({ profile: profile() }); await app.click("open-analysis"); await app.selectAnalysis("market-a");
  assert.equal(app.byId("view-sales-analysis").hidden, true);
  await app.click("save-analysis"); assert.equal(app.byId("view-sales-analysis").hidden, false);
  await app.click("view-sales-analysis");
  assert.equal(app.byId("sales-result").hidden, false);
  assert.equal(app.calls.find((call) => call.url.startsWith("/api/onboarding/sales?")).url, "/api/onboarding/sales?expected_revision=8");
  await app.click("sales-back");
  assert.equal(app.byId("analysis-panel").hidden, false);
  assert.equal(app.byId("analysis-quarter").value, "20262");
  await app.selectQuarter("20261"); assert.equal(app.byId("view-sales-analysis").hidden, true);
  await app.click("view-sales-analysis"); assert.equal(app.byId("sales-panel").hidden, true);
});

test("large currency strings stay exact and tiny age-classification coverage stays visible with its real denominator", async () => {
  const report = salesReport();
  report.total.value = 900719925474099300000; report.total.value_text = "900719925474099312345";
  report.distributions.age.denominator.value = 41799; report.distributions.age.denominator.value_text = "41799";
  report.distributions.age.classified_share_of_total_percent = 0.00648;
  report.distributions.age.total_difference = -645231572;
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), salesReport: report }); await app.click("view-sales-overview");
  assert.equal(app.byId("sales-total").textContent, "900,719,925,474,099,312,345원");
  const age = app.byId("sales-distributions").children[2];
  assert.match(age.textContent, /연령이 확인된 매출 중 비중.*41,799원/);
  assert.match(age.textContent, /총매출 대비 연령 분류율: 0\.00648%/);
  assert.match(age.textContent, /분류 합계 − 총매출: -645,231,572원/);
  assert.match(age.textContent, /전체 고객층을 뜻하지 않/);
});

test("partial, inconsistent and invalid distributions retain known amounts but never invent shares or rankings", async () => {
  for (const status of ["partial", "inconsistent", "invalid"]) {
    const report = salesReport(); report.distributions.weekday.status = status;
    report.distributions.weekday.items[1] = { ...report.distributions.weekday.items[1], status: "missing", value: null, value_text: null, share_percent: null };
    report.distributions.weekday.warnings = ["일부 원천 항목을 확인할 수 없습니다."];
    const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), salesReport: report }); await app.click("view-sales-overview");
    const group = app.byId("sales-distributions").children[0];
    assert.match(group.textContent, /300,000원/); assert.match(group.textContent, /자료 없음/);
    assert.equal(group.querySelectorAll(".sales-bar").length, 0);
    assert.equal(group.querySelectorAll(".sales-highest-tag").length, 0);
    assert.ok(group.querySelectorAll(".sales-row-share").every((cell) => cell.textContent === "—"));
  }
});

test("observed zero sales remain 0 won and null shares never become fabricated percentages", async () => {
  const report = salesReport(); report.total = { status: "available", value: 0, value_text: "0" };
  report.summary = ["관측된 분기 추정매출은 0원입니다."];
  for (const group of Object.values(report.distributions)) {
    group.denominator.value = 0; group.denominator.value_text = "0";
    group.classified_share_of_total_percent = null; group.total_difference = 0;
    group.items.forEach((item) => { item.value = 0; item.value_text = "0"; item.share_percent = null; });
    group.ranking.highest = group.items.map((item) => item.label);
    group.warnings = ["분모가 0원이므로 비중을 계산할 수 없습니다."];
  }
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), salesReport: report }); await app.click("view-sales-overview");
  assert.equal(app.byId("sales-total").textContent, "0원");
  assert.equal(app.byId("sales-distributions").querySelectorAll(".sales-bar").length, 0);
  assert.equal(app.byId("sales-distributions").children[0].querySelectorAll(".sales-highest-tag").length, 7);
  assert.ok(app.byId("sales-distributions").querySelectorAll(".sales-row-amount").every((cell) => cell.textContent === "0원"));
  assert.match(app.byId("sales-distributions").textContent, /분모가 0원/);
});

test("no-data and invalid totals are distinct from each other and from observed zero", async () => {
  for (const status of ["no_data", "invalid"]) {
    const report = salesReport(); report.status = status; report.summary = [];
    report.total = { status: status === "invalid" ? "invalid" : "missing", value: null, value_text: null, message: status === "invalid" ? "원천 총액을 0원이나 자료 없음으로 해석하지 마세요." : "매출 관측 자료가 없습니다." };
    for (const group of Object.values(report.distributions)) { group.status = "no_data"; group.items = []; group.ranking.status = "unavailable"; }
    const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), salesReport: report }); await app.click("view-sales-overview");
    assert.equal(app.byId("sales-result").hidden, false);
    assert.equal(app.byId("sales-total").textContent, status === "invalid" ? "원천 금액 확인 필요" : "확인된 자료 없음");
    assert.notEqual(app.byId("sales-total").textContent, "0원");
  }
});

test("ties come only from server ranking lists and repeated server caveats do not get static duplicates", async () => {
  const report = salesReport(); report.distributions.weekday.ranking.highest = ["월요일", "화요일"];
  report.distributions.time.warnings = ["시간대 구간의 길이가 서로 다릅니다. 시간당 매출 순위가 아닙니다."];
  report.distributions.age.warnings = ["연령이 분류된 매출 내 비중입니다.", "차이를 전부 법인 매출로 단정할 수 없습니다."];
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), salesReport: report }); await app.click("view-sales-overview");
  const groups = app.byId("sales-distributions").children;
  assert.equal(groups[0].querySelectorAll(".sales-highest-tag").length, 2);
  assert.ok(groups[0].querySelectorAll(".sales-highest-tag").every((tag) => tag.textContent === "공동 최고"));
  assert.equal(groups[1].querySelectorAll(".sales-distribution-message").length, 1);
  assert.equal(groups[2].querySelectorAll(".sales-distribution-message").length, 2);
});

test("a sales 503 shows retry and clears any report before retrying", async () => {
  let requests = 0;
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), fetch: (url) => {
    if (url.startsWith("/api/onboarding/sales?") && ++requests === 1) return { httpStatus: 503, payload: { detail: "매출 자료를 잠시 불러올 수 없습니다." } };
  } });
  await app.click("view-sales-overview");
  assert.equal(app.byId("sales-retry").hidden, false); assert.equal(app.byId("sales-result").hidden, true);
  assert.match(app.byId("sales-load-message").textContent, /불러올 수 없/);
  await app.click("sales-retry");
  assert.equal(app.byId("sales-result").hidden, false); assert.equal(requests, 2);
});

test("409 sales conflicts require condition confirmation instead of retrying or exposing an old result", async () => {
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), fetch: (url) => url.startsWith("/api/onboarding/sales?") ? { httpStatus: 409, payload: { detail: "분석 조건이 변경됐습니다." } } : undefined });
  await app.click("view-sales-overview");
  assert.equal(app.byId("sales-result").hidden, true); assert.equal(app.byId("sales-retry").hidden, true);
  assert.equal(app.byId("sales-reconfigure").textContent, "분석 조건 다시 확인");
  await app.click("sales-reconfigure");
  assert.equal(app.byId("analysis-panel").hidden, false);
  assert.equal(app.byId("sales-panel").hidden, true);
  assert.ok(app.calls.some((call) => call.url.endsWith("analysis-options")));
});

test("responses for a different saved revision or selected period are rejected without rendering", async () => {
  for (const mismatch of ["revision", "period"]) {
    const report = salesReport();
    if (mismatch === "revision") report.revision = 8; else report.selection.period = "20261";
    const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), salesReport: report }); await app.click("view-sales-overview");
    assert.equal(app.byId("sales-result").hidden, true);
    assert.equal(app.byId("sales-total").textContent, "");
    assert.match(app.byId("sales-load-message").textContent, /조건이 변경/);
  }
});

test("leaving a slow sales request aborts it and a later profile change cannot resurrect the old report", async () => {
  let resolveReport;
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), fetch: (url) => url.startsWith("/api/onboarding/sales?") ? new Promise((resolve) => { resolveReport = resolve; }) : undefined });
  const opening = app.byId("view-sales-overview").emit("click");
  assert.equal(app.byId("sales-load-state").hidden, false);
  await app.click("sales-back"); await app.click("edit-profile"); await app.selectIndustry("CS300028"); await app.submit();
  resolveReport(salesReport()); await opening;
  assert.equal(app.calls.find((call) => call.url.startsWith("/api/onboarding/sales?")).signal.aborted, true);
  assert.equal(app.byId("sales-panel").hidden, true); assert.equal(app.byId("sales-result").hidden, true);
  assert.equal(app.byId("sales-total").textContent, ""); assert.equal(app.byId("view-sales-overview").hidden, true);
  assert.equal(app.byId("saved-industry").textContent, "화초");
});

test("sales text and labels stay inert and unsafe source URLs never become links", async () => {
  const report = salesReport();
  report.summary = ['<img src=x onerror="globalThis.attacked=true">'];
  report.warnings = ["<script>globalThis.attacked=true</script>"];
  report.distributions.weekday.items[0].label = "<svg onload=alert(1)>";
  report.source.url = "javascript:alert(1)";
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), salesReport: report }); await app.click("view-sales-overview");
  assert.match(app.byId("sales-summary").textContent, /<img/);
  assert.match(app.byId("sales-warnings").textContent, /<script>/);
  assert.equal(app.byId("sales-panel").querySelectorAll("img").length, 0);
  assert.equal(app.byId("sales-panel").querySelectorAll("script").length, 0);
  assert.equal(app.byId("sales-panel").querySelectorAll("svg").length, 0);
  assert.equal(app.byId("sales-sources").children.length, 0);
});

test("back from sales restores the saved overview and its current settings without any mutation", async () => {
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection() }); await app.click("view-sales-overview"); await app.click("sales-back");
  assert.equal(app.byId("sales-panel").hidden, true);
  assert.equal(app.byId("saved-overview").hidden, false);
  assert.equal(app.byId("profile-location-column").hidden, false);
  assert.equal(app.byId("page-intro").hidden, false);
  assert.match(app.byId("saved-analysis-note").textContent, /세종대로 상권.*2026년 2분기/);
  assert.equal(app.calls.filter((call) => call.method !== "GET").length, 0);
});

test("the report menu exposes only implemented reports and cannot fetch stores without confirmed settings", async () => {
  for (const selection of [null, analysisSelection({ status: "stale", analysis_setup_complete: false })]) {
    const app = await createApp({ profile: profile(), analysisSelection: selection });
    assert.equal(app.byId("analysis-report-menu").hidden, true);
    assert.deepEqual(app.byId("analysis-report-menu").querySelectorAll("button").map((button) => button.id), ["report-menu-sales", "report-menu-stores", "report-menu-population", "report-menu-comparison", "report-menu-changes"]);
    await app.click("report-menu-stores");
    assert.equal(app.byId("stores-panel").hidden, true);
    assert.equal(app.calls.some((call) => call.url.startsWith("/api/onboarding/stores?")), false);
  }
});

test("the common menu opens a read-only stores report with separate counts, server share and its own sources", async () => {
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection() });
  await app.click("view-sales-overview"); await app.click("report-menu-stores");
  assert.equal(app.byId("analysis-report-menu").hidden, false);
  assert.equal(app.byId("report-menu-stores").getAttribute("aria-current"), "page");
  assert.equal(app.byId("report-menu-sales").disabled, false);
  assert.equal(app.byId("stores-result").hidden, false);
  assert.equal(app.byId("sales-panel").hidden, true);
  assert.equal(app.byId("sales-total").textContent, "");
  assert.deepEqual(["total", "general", "franchise", "opened", "closed"].map((key) => app.byId(`stores-${key}`).textContent), ["10개", "7개", "3개", "2개", "1개"]);
  assert.equal(app.byId("stores-franchise-share").textContent, "30%");
  assert.equal(app.byId("stores-share-bar").style.width, "30%");
  assert.equal(app.byId("stores-share-track").getAttribute("aria-hidden"), "true");
  assert.match(app.byId("stores-denominator").textContent, /전체 점포 수: 10개/);
  assert.equal(app.byId("stores-sources").children[0].href, "https://data.seoul.go.kr/stores");
  assert.match(app.byId("stores-scope").textContent, /10개 상권.*서울 전체/);
  assert.equal(app.byId("stores-summary").children[0].textContent, "서버가 확인한 전체 점포는 10개입니다.");
  assert.equal(app.calls.find((call) => call.url.startsWith("/api/onboarding/stores?")).url, "/api/onboarding/stores?expected_revision=7");
  assert.equal(app.calls.filter((call) => call.method !== "GET").length, 0);
});

test("observed zero stores remain 0 counts with an undefined franchise share", async () => {
  const report = storesReport();
  for (const record of Object.values(report.counts)) { record.value = 0; record.value_text = "0"; }
  report.composition = { status: "consistent", sum: 0, difference: 0, franchise_share_percent: null, denominator: { label: "전체 점포 수", value: 0, value_text: "0" }, warnings: ["0개가 관측되었으나 분모가 0이라 비중을 계산하지 않습니다."] };
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), storesReport: report });
  await app.click("view-sales-overview"); await app.click("report-menu-stores");
  assert.equal(app.byId("stores-total").textContent, "0개");
  assert.equal(app.byId("stores-general").textContent, "0개");
  assert.equal(app.byId("stores-franchise-share").textContent, "산출 불가");
  assert.equal(app.byId("stores-share-track").hidden, true);
  assert.match(app.byId("stores-denominator").textContent, /0개/);
  assert.match(app.byId("stores-composition-message").textContent, /분모가 0/);
});

test("missing collected rows and uncollected areas stay distinct from zero and keep sales navigation available", async () => {
  for (const status of ["no_observation", "not_collected"]) {
    const report = storesReport(); report.status = status; report.summary = [];
    for (const record of Object.values(report.counts)) { record.status = status; record.value = null; record.value_text = null; }
    report.composition = { status: "no_data", franchise_share_percent: null, denominator: { label: "전체 점포 수", value: null, value_text: null }, warnings: [] };
    const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), storesReport: report });
    await app.click("view-sales-overview"); await app.click("report-menu-stores");
    assert.equal(app.byId("stores-total").textContent, status === "not_collected" ? "자료 미확보" : "관측 행 없음");
    assert.match(app.byId("stores-total-note").textContent, /0개/);
    assert.equal(app.byId("stores-share-track").hidden, true);
    assert.equal(app.byId("report-menu-sales").disabled, false);
    await app.click("report-menu-sales");
    assert.equal(app.byId("sales-result").hidden, false);
    assert.equal(app.byId("stores-result").hidden, true);
  }
});

test("partial and invalid counts retain confirmed values while inconsistent composition suppresses any supplied percentage", async () => {
  for (const status of ["partial", "invalid"]) {
    const report = storesReport(); report.status = status;
    report.counts.franchise = { ...report.counts.franchise, status: status === "partial" ? "missing" : "invalid", value: null, value_text: null };
    report.composition.status = status === "partial" ? "incomplete" : "inconsistent";
    report.composition.sum = 11; report.composition.difference = 1;
    report.composition.warnings = ["구성 확인이 끝나지 않아 비중을 제공하지 않습니다."];
    // Even an erroneous numeric share must not override the server's validation status.
    const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), storesReport: report });
    await app.click("view-sales-overview"); await app.click("report-menu-stores");
    assert.equal(app.byId("stores-total").textContent, "10개");
    assert.equal(app.byId("stores-franchise").textContent, status === "partial" ? "항목 확인 필요" : "유효성 확인 필요");
    assert.equal(app.byId("stores-franchise-share").textContent, "산출 불가");
    assert.equal(app.byId("stores-share-track").hidden, true);
    if (status === "invalid") assert.match(app.byId("stores-composition-message").textContent, /구성 합계: 11개 · 구성 합계 − 전체: 1개/);
  }
});

test("closed stores greater than current total stay valid counts without an invented closure rate or net change", async () => {
  const report = storesReport();
  for (const [key, value] of Object.entries({ total: 1, general: 1, franchise: 0, opened: 1, closed: 2 })) Object.assign(report.counts[key], { value, value_text: String(value) });
  report.composition = { ...report.composition, sum: 1, difference: 0, franchise_share_percent: 0, denominator: { label: "전체 점포 수", value: 1, value_text: "1" } };
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), storesReport: report });
  await app.click("view-sales-overview"); await app.click("report-menu-stores");
  assert.equal(app.byId("stores-total").textContent, "1개");
  assert.equal(app.byId("stores-opened").textContent, "1개");
  assert.equal(app.byId("stores-closed").textContent, "2개");
  assert.equal(app.byId("stores-franchise-share").textContent, "0%");
  assert.equal(app.byId("stores-share-track").hidden, false);
  assert.doesNotMatch(app.byId("stores-result").textContent, /200%|순증.*-1|위험률.*200/);
});

test("store counts and denominator use exact integer strings and never calculate a replacement share", async () => {
  const report = storesReport();
  report.counts.total.value = 900719925474099300000; report.counts.total.value_text = "900719925474099312345";
  report.composition.denominator = { label: "전체 점포 수", value_text: "900719925474099312345" };
  report.composition.franchise_share_percent = 12.345678;
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), storesReport: report });
  await app.click("view-sales-overview"); await app.click("report-menu-stores");
  assert.equal(app.byId("stores-total").textContent, "900,719,925,474,099,312,345개");
  assert.match(app.byId("stores-denominator").textContent, /900,719,925,474,099,312,345개/);
  assert.equal(app.byId("stores-franchise-share").textContent, "12.345678%");
});

test("switching from a slow sales request to stores aborts sales and ignores its late response", async () => {
  let resolveSales;
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), fetch: (url) => url.startsWith("/api/onboarding/sales?") ? new Promise((resolve) => { resolveSales = resolve; }) : undefined });
  const opening = app.byId("view-sales-overview").emit("click");
  await app.click("report-menu-stores");
  assert.equal(app.calls.find((call) => call.url.startsWith("/api/onboarding/sales?")).signal.aborted, true);
  assert.equal(app.byId("stores-result").hidden, false);
  resolveSales(salesReport()); await opening;
  assert.equal(app.byId("sales-panel").hidden, true);
  assert.equal(app.byId("sales-total").textContent, "");
  assert.equal(app.byId("stores-total").textContent, "10개");
});

test("switching from slow stores to sales aborts stores and cannot resurrect old counts", async () => {
  let resolveStores;
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), fetch: (url) => url.startsWith("/api/onboarding/stores?") ? new Promise((resolve) => { resolveStores = resolve; }) : undefined });
  await app.click("view-sales-overview");
  const opening = app.byId("report-menu-stores").emit("click");
  assert.equal(app.byId("sales-total").textContent, "");
  await app.click("report-menu-sales");
  assert.equal(app.calls.find((call) => call.url.startsWith("/api/onboarding/stores?")).signal.aborted, true);
  resolveStores(storesReport()); await opening;
  assert.equal(app.byId("stores-panel").hidden, true);
  assert.equal(app.byId("stores-total").textContent, "");
  assert.equal(app.byId("sales-total").textContent, "1,000,000원");
});

test("a stores 503 permits retry and another report while keeping failed counts empty", async () => {
  let requests = 0;
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), fetch: (url) => {
    if (url.startsWith("/api/onboarding/stores?") && ++requests === 1) return { httpStatus: 503, payload: { detail: "점포 자료를 잠시 불러올 수 없습니다." } };
  } });
  await app.click("view-sales-overview"); await app.click("report-menu-stores");
  assert.equal(app.byId("stores-result").hidden, true);
  assert.equal(app.byId("stores-retry").hidden, false);
  assert.equal(app.byId("report-menu-sales").disabled, false);
  assert.equal(app.byId("stores-total").textContent, "");
  await app.click("stores-retry");
  assert.equal(requests, 2);
  assert.equal(app.byId("stores-result").hidden, false);
});

test("a stores 409 disables report switching until saved conditions are rechecked", async () => {
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), fetch: (url) => url.startsWith("/api/onboarding/stores?") ? { httpStatus: 409, payload: { detail: "분석 조건이 변경됐습니다." } } : undefined });
  await app.click("view-sales-overview"); await app.click("report-menu-stores");
  assert.equal(app.byId("stores-result").hidden, true);
  assert.equal(app.byId("stores-retry").hidden, true);
  assert.equal(app.byId("report-menu-sales").disabled, true);
  assert.equal(app.byId("stores-reconfigure").textContent, "분석 조건 다시 확인");
  await app.click("stores-reconfigure");
  assert.equal(app.byId("analysis-panel").hidden, false);
  assert.equal(app.byId("stores-panel").hidden, true);
});

test("stores responses with another revision, area, industry, period or catalogue are never rendered", async () => {
  for (const mismatch of ["revision", "area_code", "industry_code", "period", "catalog_version"]) {
    const report = storesReport();
    if (mismatch === "revision") report.revision = 8; else report.selection[mismatch] = "different";
    const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), storesReport: report });
    await app.click("view-sales-overview"); await app.click("report-menu-stores");
    assert.equal(app.byId("stores-result").hidden, true);
    assert.equal(app.byId("stores-total").textContent, "");
    assert.match(app.byId("stores-load-message").textContent, /조건이 변경/);
  }
});

test("menu changes retain the B1 return destination and stored period without a write", async () => {
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection() });
  await app.click("open-analysis"); await app.click("view-sales-analysis"); await app.click("report-menu-stores");
  assert.equal(app.byId("stores-result").hidden, false);
  assert.equal(app.byId("stores-back").textContent, "상권 설정으로");
  await app.click("report-menu-sales"); await app.click("report-menu-stores"); await app.click("stores-back");
  assert.equal(app.byId("analysis-panel").hidden, false);
  assert.equal(app.byId("analysis-quarter").value, "20262");
  assert.equal(app.byId("analysis-report-menu").hidden, true);
  assert.equal(app.calls.filter((call) => call.method !== "GET").length, 0);
});

test("returning from stores to overview clears reports and profile edits invalidate future analysis access", async () => {
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection() });
  await app.click("view-sales-overview"); await app.click("report-menu-stores"); await app.click("stores-back");
  assert.equal(app.byId("saved-overview").hidden, false);
  assert.equal(app.byId("profile-location-column").hidden, false);
  assert.equal(app.byId("analysis-report-menu").hidden, true);
  assert.equal(app.byId("stores-total").textContent, "");
  await app.click("edit-profile"); await app.selectIndustry("CS300028"); await app.submit();
  assert.equal(app.byId("view-sales-overview").hidden, true);
  await app.click("report-menu-stores");
  assert.equal(app.calls.filter((call) => call.url.startsWith("/api/onboarding/stores?")).length, 1);
});

test("stores source labels and warnings are inert text and unsafe URLs never become links", async () => {
  const report = storesReport();
  report.summary = ['<img src=x onerror="globalThis.attacked=true">'];
  report.warnings = ["<script>globalThis.attacked=true</script>"];
  report.source.coverage_note = "<svg onload=alert(1)>"; report.source.url = "javascript:alert(1)";
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), storesReport: report });
  await app.click("view-sales-overview"); await app.click("report-menu-stores");
  assert.match(app.byId("stores-summary").textContent, /<img/);
  assert.match(app.byId("stores-warnings").textContent, /<script>/);
  assert.equal(app.byId("stores-panel").querySelectorAll("img").length, 0);
  assert.equal(app.byId("stores-panel").querySelectorAll("script").length, 0);
  assert.equal(app.byId("stores-panel").querySelectorAll("svg").length, 0);
  assert.equal(app.byId("stores-sources").children.length, 0);
});

test("population requires saved analysis conditions and opens only as a read-only area-wide report", async () => {
  const empty = await createApp({ profile: profile() }); await empty.click("report-menu-population");
  assert.equal(empty.byId("population-panel").hidden, true);
  assert.equal(empty.calls.some((call) => call.url.startsWith("/api/onboarding/population?")), false);
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection() });
  await app.click("view-sales-overview"); await app.click("report-menu-population");
  assert.equal(app.byId("population-result").hidden, false);
  assert.equal(app.byId("sales-total").textContent, "");
  assert.equal(app.byId("report-menu-population").getAttribute("aria-current"), "page");
  assert.equal(app.byId("population-total").textContent, "1,000,000명");
  assert.equal(app.byId("population-total-label").textContent, "지역 유동인구 원천 총지표");
  assert.deepEqual(app.byId("population-distributions").querySelectorAll("tbody").map((body) => body.children.length), [6, 6]);
  assert.match(app.byId("population-condition").textContent, /프로필 업종: 커피-음료.*업종 구분 없음/);
  assert.match(app.byId("population-panel").textContent, /업종의 고객 수가 아닌 상권 전체/);
  assert.match(app.byId("population-total-note").textContent, /일평균이나 고유 방문자 수로 해석할 수 없/);
  assert.equal(app.byId("population-sources").children[0].href, "https://data.seoul.go.kr/population");
  assert.equal(app.calls.find((call) => call.url.startsWith("/api/onboarding/population?")).url, "/api/onboarding/population?expected_revision=7");
  assert.equal(app.calls.filter((call) => call.method !== "GET").length, 0);
});

test("population exact integer strings, official age labels, shares and tied ranks are not inferred on the client", async () => {
  const report = populationReport();
  report.total.value_text = "900719925474099312345"; report.total.value = 900719925474099300000;
  const age = report.distributions.age;
  age.denominator.value_text = "900719925474099312345";
  age.items[0].label = "원천 연령대 10"; age.items[0].value_text = "900719925474099312344"; age.items[0].share_percent = 12.345678;
  age.ranking.highest = [age.items[0].label, age.items[1].label];
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), populationReport: report });
  await app.click("view-sales-overview"); await app.click("report-menu-population");
  assert.equal(app.byId("population-total").textContent, "900,719,925,474,099,312,345명");
  const group = app.byId("population-distributions").children[1];
  assert.match(group.textContent, /원천 연령대 10/); assert.doesNotMatch(group.textContent, /10대 이하/);
  assert.match(group.textContent, /900,719,925,474,099,312,344명/);
  assert.equal(group.querySelectorAll(".sales-row-share")[0].textContent, "12.345678%");
  assert.equal(group.querySelectorAll(".sales-highest-tag").length, 2);
  assert.ok(group.querySelectorAll(".sales-highest-tag").every((tag) => tag.textContent === "공동 최고"));
});

test("population sum mismatches keep raw values and show the signed difference while withholding all percentages and ranks", async () => {
  const report = populationReport();
  for (const group of Object.values(report.distributions)) { group.status = "inconsistent"; group.sum = 999999; group.total_difference = -1; group.warnings = ["원천 총지표와 분류 합계가 달라 해석을 보류합니다."]; }
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), populationReport: report });
  await app.click("view-sales-overview"); await app.click("report-menu-population");
  for (const group of app.byId("population-distributions").children) {
    assert.match(group.textContent, /분류 합계: 999,999명 · 분류 합계 − 총지표: -1명/);
    assert.match(group.textContent, /300,000명/);
    assert.equal(group.querySelectorAll(".sales-bar").length, 0);
    assert.equal(group.querySelectorAll(".sales-highest-tag").length, 0);
    assert.ok(group.querySelectorAll(".sales-row-share").every((cell) => cell.textContent === "—"));
  }
});

test("partial or invalid population distributions distinguish missing values from zero and suppress classification shares", async () => {
  for (const status of ["partial", "invalid"]) {
    const report = populationReport(), group = report.distributions.time;
    group.status = status;
    group.items[0] = { ...group.items[0], value: 0, value_text: "0" };
    group.items[1] = { ...group.items[1], status: status === "partial" ? "missing" : "invalid", value: null, value_text: null };
    const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), populationReport: report });
    await app.click("view-sales-overview"); await app.click("report-menu-population");
    const rendered = app.byId("population-distributions").children[0];
    assert.equal(rendered.querySelectorAll(".sales-row-amount")[0].textContent, "0명");
    assert.equal(rendered.querySelectorAll(".sales-row-amount")[1].textContent, status === "partial" ? "자료 없음" : "확인 불가");
    assert.equal(rendered.querySelectorAll(".sales-bar").length, 0);
    assert.equal(rendered.querySelectorAll(".sales-highest-tag").length, 0);
  }
});

test("observed zero population shows zero people without turning a null denominator share into 0 percent", async () => {
  const report = populationReport(); report.total.value = 0; report.total.value_text = "0";
  for (const group of Object.values(report.distributions)) {
    group.denominator.value = 0; group.denominator.value_text = "0";
    group.items.forEach((item) => Object.assign(item, { value: 0, value_text: "0", share_percent: null }));
    group.ranking.highest = group.items.map((item) => item.label);
  }
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), populationReport: report });
  await app.click("view-sales-overview"); await app.click("report-menu-population");
  assert.equal(app.byId("population-total").textContent, "0명");
  assert.ok(app.byId("population-distributions").querySelectorAll(".sales-row-amount").every((cell) => cell.textContent === "0명"));
  assert.ok(app.byId("population-distributions").querySelectorAll(".sales-row-share").every((cell) => cell.textContent === "—"));
  assert.equal(app.byId("population-distributions").querySelectorAll(".sales-bar").length, 0);
  assert.equal(app.byId("population-distributions").querySelectorAll(".sales-highest-tag").length, 12);
});

test("absent and invalid population totals are different states and do not block other report menus", async () => {
  for (const status of ["no_data", "invalid"]) {
    const report = populationReport(); report.status = status; report.summary = [];
    report.total = { status: status === "invalid" ? "invalid" : "missing", value: null, value_text: null };
    for (const group of Object.values(report.distributions)) { group.status = "no_data"; group.items = []; }
    const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), populationReport: report });
    await app.click("view-sales-overview"); await app.click("report-menu-population");
    assert.equal(app.byId("population-total").textContent, status === "invalid" ? "원천 값 확인 필요" : "확인된 자료 없음");
    assert.equal(app.byId("report-menu-sales").disabled, false);
    assert.equal(app.byId("report-menu-stores").disabled, false);
    await app.click("report-menu-stores");
    assert.equal(app.byId("stores-result").hidden, false);
    assert.equal(app.byId("population-result").hidden, true);
  }
});

test("population 503 retries safely and 409 requires saved condition confirmation", async () => {
  let requests = 0;
  const retry = await createApp({ profile: profile(), analysisSelection: analysisSelection(), fetch: (url) => {
    if (url.startsWith("/api/onboarding/population?") && ++requests === 1) return { httpStatus: 503, payload: { detail: "유동인구 자료를 잠시 불러올 수 없습니다." } };
  } });
  await retry.click("view-sales-overview"); await retry.click("report-menu-population");
  assert.equal(retry.byId("population-result").hidden, true); assert.equal(retry.byId("population-retry").hidden, false);
  assert.equal(retry.byId("report-menu-stores").disabled, false);
  await retry.click("population-retry"); assert.equal(retry.byId("population-result").hidden, false); assert.equal(requests, 2);
  const conflict = await createApp({ profile: profile(), analysisSelection: analysisSelection(), fetch: (url) => url.startsWith("/api/onboarding/population?") ? { httpStatus: 409, payload: { detail: "저장한 분석 조건이 변경됐습니다." } } : undefined });
  await conflict.click("view-sales-overview"); await conflict.click("report-menu-population");
  assert.equal(conflict.byId("population-retry").hidden, true);
  assert.equal(conflict.byId("report-menu-sales").disabled, true);
  await conflict.click("population-reconfigure");
  assert.equal(conflict.byId("analysis-panel").hidden, false); assert.equal(conflict.byId("population-panel").hidden, true);
});

test("population replies for another revision or condition and replies with an industry-specific scope never render", async () => {
  for (const mismatch of ["revision", "industry_code", "period", "population_scope", "industry_applied", "feature"]) {
    const report = populationReport();
    if (mismatch === "revision") report.revision = 8;
    else if (mismatch === "industry_code" || mismatch === "period") report.selection[mismatch] = "different";
    else report[mismatch] = mismatch === "industry_applied" ? true : "different";
    const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), populationReport: report });
    await app.click("view-sales-overview"); await app.click("report-menu-population");
    assert.equal(app.byId("population-result").hidden, true);
    assert.equal(app.byId("population-total").textContent, "");
  }
});

test("leaving slow population for either existing report aborts it and discards the late response", async () => {
  for (const destination of ["sales", "stores"]) {
    let resolvePopulation;
    const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), fetch: (url) => url.startsWith("/api/onboarding/population?") ? new Promise((resolve) => { resolvePopulation = resolve; }) : undefined });
    await app.click("view-sales-overview"); const opening = app.byId("report-menu-population").emit("click");
    await app.click(`report-menu-${destination}`);
    assert.equal(app.calls.find((call) => call.url.startsWith("/api/onboarding/population?")).signal.aborted, true);
    resolvePopulation(populationReport()); await opening;
    assert.equal(app.byId("population-panel").hidden, true); assert.equal(app.byId("population-total").textContent, "");
    assert.equal(app.byId(`${destination}-result`).hidden, false);
  }
});

test("switching slow stores to population isolates both results and preserves only the active source", async () => {
  let resolveStores;
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), fetch: (url) => url.startsWith("/api/onboarding/stores?") ? new Promise((resolve) => { resolveStores = resolve; }) : undefined });
  await app.click("view-sales-overview"); const opening = app.byId("report-menu-stores").emit("click");
  await app.click("report-menu-population"); resolveStores(storesReport()); await opening;
  assert.equal(app.calls.find((call) => call.url.startsWith("/api/onboarding/stores?")).signal.aborted, true);
  assert.equal(app.byId("stores-total").textContent, ""); assert.equal(app.byId("stores-sources").children.length, 0);
  assert.equal(app.byId("population-result").hidden, false);
  assert.equal(app.byId("population-sources").children[0].href, "https://data.seoul.go.kr/population");
});

test("population reentry ignores a superseded response even after the same menu is active again", async () => {
  let firstResolve, requests = 0;
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), fetch: (url) => {
    if (url.startsWith("/api/onboarding/population?") && ++requests === 1) return new Promise((resolve) => { firstResolve = resolve; });
  } });
  await app.click("view-sales-overview"); const opening = app.byId("report-menu-population").emit("click");
  await app.click("report-menu-stores"); await app.click("report-menu-population");
  const old = populationReport(); old.total.value_text = "999999999";
  firstResolve(old); await opening;
  assert.equal(requests, 2);
  assert.equal(app.byId("population-total").textContent, "1,000,000명");
});

test("population keeps B1 return origin through all menu changes and profile edits invalidate the result", async () => {
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection() });
  await app.click("open-analysis"); await app.click("view-sales-analysis"); await app.click("report-menu-stores"); await app.click("report-menu-population");
  assert.equal(app.byId("population-back").textContent, "상권 설정으로");
  await app.click("population-back");
  assert.equal(app.byId("analysis-panel").hidden, false); assert.equal(app.byId("analysis-quarter").value, "20262");
  await app.click("analysis-back"); await app.click("edit-profile"); await app.selectIndustry("CS300028"); await app.submit();
  assert.equal(app.byId("view-sales-overview").hidden, true);
  await app.click("report-menu-population");
  assert.equal(app.byId("population-total").textContent, "");
  assert.equal(app.calls.filter((call) => call.url.startsWith("/api/onboarding/population?")).length, 1);
});

test("population warnings and raw labels remain inert, and time caveats are not duplicated", async () => {
  const report = populationReport();
  report.summary = ["<script>attacked=true</script>"];
  report.source.url = "javascript:alert(1)";
  report.distributions.age.items[0].label = "<img src=x onerror=alert(1)>";
  report.distributions.time.warnings = ["시간대 구간이 다르며 시간당 인구를 뜻하지 않습니다."];
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), populationReport: report });
  await app.click("view-sales-overview"); await app.click("report-menu-population");
  assert.match(app.byId("population-summary").textContent, /<script>/);
  assert.equal(app.byId("population-panel").querySelectorAll("script").length, 0);
  assert.equal(app.byId("population-panel").querySelectorAll("img").length, 0);
  assert.equal(app.byId("population-sources").children.length, 0);
  assert.equal(app.byId("population-distributions").children[0].querySelectorAll(".sales-distribution-message").length, 1);
});

async function openComparisonApp(config = {}) {
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), ...config });
  await app.click("view-sales-overview"); await app.click("report-menu-comparison");
  return app;
}
async function runComparison(app, district = "11140", area = "market-b") {
  await app.selectComparisonDistrict(district); await app.selectComparisonArea(area); await app.click("comparison-run");
}

test("comparison requires saved conditions, a district and a selectable area, and never auto-runs", async () => {
  const empty = await createApp({ profile: profile() }); await empty.click("report-menu-comparison");
  assert.equal(empty.byId("comparison-panel").hidden, true);
  assert.equal(empty.calls.some((call) => call.url.includes("/comparison")), false);
  const options = comparisonOptions(); options.areas = [...options.areas, { ...comparisonAreas[0], area_code: "market-a", name: "기준 상권" }];
  const app = await openComparisonApp({ comparisonOptions: options });
  assert.equal(app.byId("comparison-area").disabled, true);
  assert.equal(app.byId("comparison-run").disabled, true);
  await app.selectComparisonDistrict("11140");
  assert.equal(app.byId("comparison-area").disabled, false);
  assert.equal(app.byId("comparison-area").options.some((option) => option.value === "market-a"), false);
  assert.equal(app.byId("comparison-area").options.find((option) => option.value === "market-blocked").disabled, true);
  await app.selectComparisonArea("market-blocked"); assert.equal(app.byId("comparison-run").disabled, true);
  await app.click("comparison-run");
  await app.selectComparisonArea("market-b"); assert.equal(app.byId("comparison-run").disabled, false);
  assert.equal(app.calls.filter((call) => call.url.startsWith("/api/onboarding/comparison?")).length, 0);
  const enter = await app.enter("comparison-area"); assert.equal(enter.defaultPrevented, true); assert.equal(app.saves().length, 0);
});

test("comparison keeps industry and quarter fixed and renders seven server-provided metrics with their sources", async () => {
  const app = await openComparisonApp(); await runComparison(app);
  const request = app.calls.find((call) => call.url.startsWith("/api/onboarding/comparison?"));
  assert.equal(request.url, "/api/onboarding/comparison?comparison_area_code=market-b&expected_revision=7");
  assert.equal(app.calls.filter((call) => call.method !== "GET").length, 0);
  assert.equal(app.byId("comparison-result").hidden, false);
  assert.equal(app.byId("comparison-rows").children.length, 7);
  assert.deepEqual(app.byId("comparison-rows").children[0].children.slice(1).map((cell) => cell.textContent), ["1,000,000원", "1,500,000원", "500,000원", "+50%"]);
  assert.match(app.byId("comparison-condition").textContent, /커피-음료.*2026년 2분기.*고정/);
  assert.match(app.byId("comparison-base-meta").textContent, /골목상권/);
  assert.match(app.byId("comparison-target-meta").textContent, /발달상권/);
  assert.match(app.byId("comparison-rows").children[6].textContent, /상권 전체 · 업종 구분 없음/);
  assert.equal(app.byId("comparison-sources").children.length, 3);
  assert.equal(app.byId("comparison-warnings").children.filter((node) => node.textContent.includes("10개 상권")).length, 1);
  assert.ok(app.byId("comparison-rows").querySelectorAll("th").every((cell) => cell.getAttribute("scope") === "row"));
});

test("comparison preserves exact counts and uses server deltas and percentages instead of recomputing them", async () => {
  const report = comparisonReport(), metric = report.metrics[0];
  metric.base.value_text = "900719925474099312345"; metric.comparison.value_text = "900719925474099312348";
  metric.delta_text = "3"; metric.delta = 3; metric.percent = 0.25;
  const app = await openComparisonApp({ comparisonReport: report }); await runComparison(app);
  const cells = app.byId("comparison-rows").children[0].children;
  assert.equal(cells[1].textContent, "900,719,925,474,099,312,345원");
  assert.equal(cells[2].textContent, "900,719,925,474,099,312,348원");
  assert.equal(cells[3].textContent, "3원"); assert.equal(cells[4].textContent, "+0.25%");
  assert.equal(app.byId("comparison-rows").children[4].children[3].textContent, "-1개");
});

test("a zero comparison base preserves the numeric delta while missing, invalid and uncollected metrics stay distinct", async () => {
  const report = comparisonReport(); report.status = "partial";
  Object.assign(report.metrics[0], { base: { status: "available", value: 0, value_text: "0" }, delta: 1500000, delta_text: "1500000", percent: null, percent_status: "undefined_zero_base" });
  for (const [index, status] of [[1, "not_collected"], [2, "no_observation"], [3, "invalid"], [4, "missing"]]) {
    Object.assign(report.metrics[index], { status: "unavailable", comparison: { status, value: null, value_text: null }, delta: null, delta_text: null, percent: null, percent_status: "unavailable" });
  }
  const app = await openComparisonApp({ comparisonReport: report }); await runComparison(app);
  const rows = app.byId("comparison-rows").children;
  assert.equal(rows[0].children[1].textContent, "0원"); assert.equal(rows[0].children[3].textContent, "1,500,000원");
  assert.match(rows[0].children[4].textContent, /산출 불가.*기준 상권 값이 0/);
  assert.deepEqual(rows.slice(1, 5).map((row) => row.children[2].textContent), ["자료 미확보", "관측 행 없음", "원천 값 확인 필요", "항목 없음"]);
  assert.ok(rows.slice(1, 5).every((row) => row.children[3].textContent === "비교 불가"));
  assert.equal(rows[5].children[3].textContent, "1개");
});

test("an unavailable comparison row cannot expose supplied differences or percentages", async () => {
  const report = comparisonReport(); report.metrics[0].status = "unavailable";
  const app = await openComparisonApp({ comparisonReport: report }); await runComparison(app);
  const row = app.byId("comparison-rows").children[0];
  assert.equal(row.children[1].textContent, "1,000,000원");
  assert.equal(row.children[3].textContent, "비교 불가"); assert.equal(row.children[4].textContent, "산출 불가");
});

test("changing district or target immediately removes results, and an empty district never permits execution", async () => {
  const app = await openComparisonApp(); await runComparison(app);
  await app.selectComparisonDistrict("11440");
  assert.equal(app.byId("comparison-result").hidden, true); assert.equal(app.byId("comparison-rows").children.length, 0);
  assert.equal(app.byId("comparison-area").value, ""); assert.equal(app.byId("comparison-run").disabled, true);
  assert.deepEqual(app.byId("comparison-area").options.filter((option) => option.value).map((option) => option.value), ["market-c"]);
  await app.selectComparisonArea("market-c"); await app.click("comparison-run");
  assert.equal(app.byId("comparison-target-name").textContent, "마포 비교상권");
  await app.selectComparisonArea(""); assert.equal(app.byId("comparison-result").hidden, true);
  await app.selectComparisonDistrict("11680");
  assert.match(app.byId("comparison-options-message").textContent, /선택할 비교 상권이 없/);
  assert.equal(app.byId("comparison-run").disabled, true);
});

test("changing input during a comparison aborts the request and rejects a late old-target response", async () => {
  let resolveComparison;
  const app = await openComparisonApp({ fetch: (url) => url.startsWith("/api/onboarding/comparison?") && url.includes("market-b") ? new Promise((resolve) => { resolveComparison = resolve; }) : undefined });
  await app.selectComparisonDistrict("11140"); await app.selectComparisonArea("market-b");
  const running = app.byId("comparison-run").emit("click");
  await app.selectComparisonDistrict("11440"); await app.selectComparisonArea("market-c"); await app.click("comparison-run");
  assert.equal(app.calls.find((call) => call.url.startsWith("/api/onboarding/comparison?")).signal.aborted, true);
  resolveComparison(comparisonReport()); await running;
  assert.equal(app.byId("comparison-target-name").textContent, "마포 비교상권");
  assert.equal(app.byId("comparison-result").hidden, false);
});

test("comparison options 429 and 503 failures disable selection until an explicit retry succeeds", async () => {
  for (const status of [429, 503]) {
    let requests = 0;
    const app = await openComparisonApp({ fetch: (url) => {
      if (url.startsWith("/api/onboarding/comparison-options?") && ++requests === 1) return { httpStatus: status, payload: { detail: "목록 요청을 잠시 후 다시 시도해 주세요." } };
    } });
    assert.equal(app.byId("comparison-options-retry").hidden, false);
    assert.equal(app.byId("comparison-district").disabled, true); assert.equal(app.byId("comparison-run").disabled, true);
    assert.equal(app.byId("report-menu-population").disabled, false);
    await app.click("comparison-options-retry");
    assert.equal(app.byId("comparison-district").disabled, false); assert.equal(requests, 2);
  }
});

test("comparison 429 and 503 failures clear the result and support retry without changing saved conditions", async () => {
  for (const status of [429, 503]) {
    let requests = 0;
    const app = await openComparisonApp({ fetch: (url) => {
      if (url.startsWith("/api/onboarding/comparison?") && ++requests === 1) return { httpStatus: status, payload: { detail: "비교 자료를 다시 확인해 주세요." } };
    } });
    await runComparison(app);
    assert.equal(app.byId("comparison-result").hidden, true); assert.equal(app.byId("comparison-retry").hidden, false);
    await app.click("comparison-retry");
    assert.equal(app.byId("comparison-result").hidden, false); assert.equal(requests, 2);
    assert.equal(app.calls.filter((call) => call.method !== "GET").length, 0);
  }
});

test("comparison options and data conflicts require B1 reconfirmation instead of exposing stale results", async () => {
  for (const stage of ["comparison-options?", "comparison?"]) {
    const app = await openComparisonApp({ fetch: (url) => url.startsWith(`/api/onboarding/${stage}`) ? { httpStatus: 409, payload: { detail: "분석 조건을 다시 확인해 주세요." } } : undefined });
    if (stage === "comparison?") await runComparison(app);
    assert.equal(app.byId("comparison-result").hidden, true);
    assert.equal(app.byId("report-menu-sales").disabled, true);
    assert.equal(app.byId("comparison-reconfigure").textContent, "분석 조건 다시 확인");
    await app.click("comparison-reconfigure"); assert.equal(app.byId("analysis-panel").hidden, false);
  }
});

test("comparison rejects changed catalogues, mismatched target context and reversed delta direction", async () => {
  const options = comparisonOptions(); options.catalog_version = "catalog-v2";
  const outdated = await openComparisonApp({ comparisonOptions: options });
  assert.equal(outdated.byId("comparison-district").disabled, true);
  assert.match(outdated.byId("comparison-options-message").textContent, /다시 확인/);
  for (const mismatch of ["revision", "period", "comparison_area", "comparison_direction"]) {
    const report = comparisonReport();
    if (mismatch === "revision") report.revision = 8;
    else if (mismatch === "period") report.selection.period = "20261";
    else if (mismatch === "comparison_area") report.comparison_area = comparisonAreas[1];
    else report.comparison_direction = "base_minus_comparison";
    const app = await openComparisonApp({ comparisonReport: report }); await runComparison(app);
    assert.equal(app.byId("comparison-result").hidden, true); assert.equal(app.byId("comparison-rows").children.length, 0);
  }
});

test("leaving pending comparison options and data aborts both and keeps other reports clean", async () => {
  let resolveOptions;
  const optionsApp = await createApp({ profile: profile(), analysisSelection: analysisSelection(), fetch: (url) => url.startsWith("/api/onboarding/comparison-options?") ? new Promise((resolve) => { resolveOptions = resolve; }) : undefined });
  await optionsApp.click("view-sales-overview"); const opening = optionsApp.byId("report-menu-comparison").emit("click");
  await optionsApp.click("report-menu-population"); resolveOptions(comparisonOptions()); await opening;
  assert.equal(optionsApp.calls.find((call) => call.url.startsWith("/api/onboarding/comparison-options?")).signal.aborted, true);
  assert.equal(optionsApp.byId("comparison-panel").hidden, true); assert.equal(optionsApp.byId("population-result").hidden, false);
  let resolveData;
  const app = await openComparisonApp({ fetch: (url) => url.startsWith("/api/onboarding/comparison?") ? new Promise((resolve) => { resolveData = resolve; }) : undefined });
  await app.selectComparisonDistrict("11140"); await app.selectComparisonArea("market-b"); const running = app.byId("comparison-run").emit("click");
  await app.click("report-menu-stores"); resolveData(comparisonReport()); await running;
  assert.equal(app.calls.find((call) => call.url.startsWith("/api/onboarding/comparison?")).signal.aborted, true);
  assert.equal(app.byId("comparison-rows").children.length, 0); assert.equal(app.byId("stores-result").hidden, false);
});

test("comparison preserves the B1 return destination and profile edits remove access to old conditions", async () => {
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection() });
  await app.click("open-analysis"); await app.click("view-sales-analysis"); await app.click("report-menu-comparison"); await runComparison(app);
  assert.equal(app.byId("comparison-back").textContent, "상권 설정으로");
  await app.click("comparison-back"); assert.equal(app.byId("analysis-quarter").value, "20262");
  await app.click("analysis-back"); await app.click("edit-profile"); await app.selectIndustry("CS300028"); await app.submit();
  await app.click("report-menu-comparison");
  assert.equal(app.byId("comparison-panel").hidden, true); assert.equal(app.byId("comparison-rows").children.length, 0);
  assert.equal(app.calls.filter((call) => call.url.startsWith("/api/onboarding/comparison?")).length, 1);
});

test("comparison names and warnings stay inert and unsafe source URLs are not rendered", async () => {
  const report = comparisonReport();
  report.comparison_area = { ...report.comparison_area, name: "<img src=x onerror=alert(1)>" };
  report.warnings = ["<script>attacked=true</script>"];
  report.metrics.forEach((metric) => { metric.source.url = "javascript:alert(1)"; });
  const app = await openComparisonApp({ comparisonReport: report }); await runComparison(app);
  assert.match(app.byId("comparison-target-name").textContent, /<img/);
  assert.match(app.byId("comparison-warnings").textContent, /<script>/);
  assert.equal(app.byId("comparison-panel").querySelectorAll("img").length, 0);
  assert.equal(app.byId("comparison-panel").querySelectorAll("script").length, 0);
  assert.equal(app.byId("comparison-rows").querySelectorAll("a").length, 0);
  assert.equal(app.byId("comparison-sources").children.length, 0);
});

async function openChangesApp(config = {}) {
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection(), ...config });
  await app.click("view-sales-overview"); await app.click("report-menu-changes");
  return app;
}

test("period changes need saved conditions and an explicit request while keeping the current quarter fixed", async () => {
  const empty = await createApp({ profile: profile() }); await empty.click("report-menu-changes");
  assert.equal(empty.byId("changes-panel").hidden, true); assert.equal(empty.calls.some((call) => call.url.startsWith("/api/onboarding/changes?")), false);
  const app = await openChangesApp();
  assert.equal(app.byId("changes-mode").value, "qoq"); assert.equal(app.byId("changes-run").disabled, false);
  assert.equal(app.calls.some((call) => call.url.startsWith("/api/onboarding/changes?")), false);
  assert.equal((await app.enter("changes-mode")).defaultPrevented, true); assert.equal(app.saves().length, 0);
  await app.click("changes-run");
  assert.equal(app.calls.find((call) => call.url.startsWith("/api/onboarding/changes?")).url, "/api/onboarding/changes?comparison=qoq&expected_revision=7");
  assert.equal(app.byId("changes-current-period").textContent, "2026년 2분기");
  assert.equal(app.byId("changes-previous-period").textContent, "2026년 1분기");
  assert.equal(app.byId("changes-rows").children.length, 7);
  assert.deepEqual(app.byId("changes-rows").children[0].children.slice(1).map((cell) => cell.textContent), ["1,500,000원", "1,000,000원", "500,000원", "+50%"]);
  assert.equal(app.calls.filter((call) => call.method !== "GET").length, 0);
});

test("switching to year-over-year clears all previous results and requests the exact same quarter last year", async () => {
  const app = await openChangesApp(); await app.click("changes-run"); await app.selectChangesMode("yoy");
  assert.equal(app.byId("changes-result").hidden, true); assert.equal(app.byId("changes-rows").children.length, 0);
  assert.equal(app.byId("changes-previous-period").textContent, "");
  assert.equal(app.calls.filter((call) => call.url.startsWith("/api/onboarding/changes?")).length, 1);
  await app.click("changes-run");
  assert.equal(app.calls.filter((call) => call.url.startsWith("/api/onboarding/changes?")).at(-1).url, "/api/onboarding/changes?comparison=yoy&expected_revision=7");
  assert.equal(app.byId("changes-current-period").textContent, "2026년 2분기");
  assert.equal(app.byId("changes-previous-period").textContent, "2025년 2분기");
  assert.match(app.byId("changes-previous-meta").textContent, /전년 동분기/);
});

test("missing quarters across the year boundary preserve current values without substituting another period", async () => {
  const selection = analysisSelection({ period: "20261", period_label: "2026년 1분기" });
  for (const [mode, previousLabel] of [["qoq", "2025년 4분기"], ["yoy", "2025년 1분기"]]) {
    const report = changesReport(profile(), selection, 7, mode); report.status = "no_comparison"; report.summary = [];
    for (const row of report.metrics) Object.assign(row, { previous: { status: "not_collected", value: null, value_text: null }, status: "unavailable", delta: null, delta_text: null, percent: null, percent_status: "unavailable" });
    const app = await openChangesApp({ analysisSelection: selection, changesReport: report }); await app.selectChangesMode(mode); await app.click("changes-run");
    assert.equal(app.byId("changes-result").hidden, false);
    assert.equal(app.byId("changes-previous-period").textContent, previousLabel);
    assert.equal(app.byId("changes-rows").children[0].children[1].textContent, "1,500,000원");
    assert.ok(app.byId("changes-rows").children.every((row) => row.children[2].textContent === "자료 미확보" && row.children[3].textContent === "비교 불가"));
    assert.match(app.byId("changes-result-note").textContent, /증감은 계산하지 않았/);
    assert.equal(app.calls.filter((call) => call.url.startsWith("/api/onboarding/changes?")).length, 1);
  }
});

test("observed zero previous values retain deltas but never fabricate a zero percent growth rate", async () => {
  const report = changesReport();
  Object.assign(report.metrics[0], { previous: { status: "available", value: 0, value_text: "0" }, delta: 1500000, delta_text: "1500000", percent: null, percent_status: "undefined_zero_previous" });
  Object.assign(report.metrics[1], { current: { status: "available", value: 0, value_text: "0" }, previous: { status: "available", value: 0, value_text: "0" }, delta: 0, delta_text: "0", percent: null, percent_status: "undefined_zero_previous" });
  Object.assign(report.metrics[2], { current: { status: "available", value: 0, value_text: "0" }, previous: { status: "available", value: 10, value_text: "10" }, delta: -10, delta_text: "-10", percent: -100, percent_status: "available" });
  const app = await openChangesApp({ changesReport: report }); await app.click("changes-run");
  const rows = app.byId("changes-rows").children;
  assert.equal(rows[0].children[2].textContent, "0원"); assert.equal(rows[0].children[3].textContent, "1,500,000원");
  assert.match(rows[0].children[4].textContent, /산출 불가.*비교 분기 값이 0/);
  assert.equal(rows[1].children[3].textContent, "0개"); assert.doesNotMatch(rows[1].children[4].textContent, /0%/);
  assert.equal(rows[2].children[4].textContent, "-100%");
});

test("period changes display exact large integer strings and server-provided signed deltas and percentages", async () => {
  const report = changesReport(), metric = report.metrics[0];
  metric.current.value_text = "900719925474099312345"; metric.previous.value_text = "900719925474099312348";
  metric.delta_text = "-3"; metric.delta = -3; metric.percent = -0.25;
  const app = await openChangesApp({ changesReport: report }); await app.click("changes-run");
  const cells = app.byId("changes-rows").children[0].children;
  assert.equal(cells[1].textContent, "900,719,925,474,099,312,345원");
  assert.equal(cells[2].textContent, "900,719,925,474,099,312,348원");
  assert.equal(cells[3].textContent, "-3원"); assert.equal(cells[4].textContent, "-0.25%");
});

test("partly unavailable changes keep valid metric rows and distinguish missing, invalid and unobserved values", async () => {
  const report = changesReport(); report.status = "partial";
  for (const [index, status] of [[0, "missing"], [1, "invalid"], [2, "no_observation"]]) {
    Object.assign(report.metrics[index], { current: { status, value: null, value_text: null }, status: "unavailable" });
  }
  const app = await openChangesApp({ changesReport: report }); await app.click("changes-run");
  const rows = app.byId("changes-rows").children;
  assert.deepEqual(rows.slice(0, 3).map((row) => row.children[1].textContent), ["항목 없음", "원천 값 확인 필요", "관측 행 없음"]);
  assert.ok(rows.slice(0, 3).every((row) => row.children[3].textContent === "비교 불가" && row.children[4].textContent === "산출 불가"));
  assert.equal(rows[3].children[3].textContent, "0개"); assert.equal(rows[3].children[4].textContent, "0%");
  assert.match(rows[6].textContent, /상권 전체 · 업종 구분 없음/);
});

test("period change responses with a shifted quarter, wrong mode, direction or saved revision are rejected", async () => {
  for (const mismatch of ["previous_period", "current_period", "comparison", "comparison_direction", "revision", "industry_code"]) {
    const report = changesReport();
    if (mismatch === "previous_period") report.previous_period = { code: "20252", label: "2025년 2분기" };
    else if (mismatch === "current_period") report.current_period.code = "20261";
    else if (mismatch === "comparison") report.comparison = "yoy";
    else if (mismatch === "comparison_direction") report.comparison_direction = "previous_minus_current";
    else if (mismatch === "revision") report.revision = 8;
    else report.selection.industry_code = "CS300028";
    const app = await openChangesApp({ changesReport: report }); await app.click("changes-run");
    assert.equal(app.byId("changes-result").hidden, true); assert.equal(app.byId("changes-rows").children.length, 0);
    assert.equal(app.byId("changes-load-state").hidden, false);
  }
});

test("changing period mode aborts the old request and prevents a late quarter-over-quarter result from replacing year-over-year", async () => {
  let resolvePrevious;
  const app = await openChangesApp({ fetch: (url) => url.startsWith("/api/onboarding/changes?comparison=qoq") ? new Promise((resolve) => { resolvePrevious = resolve; }) : undefined });
  const loading = app.byId("changes-run").emit("click");
  await app.selectChangesMode("yoy"); await app.click("changes-run");
  assert.equal(app.calls.find((call) => call.url.startsWith("/api/onboarding/changes?")).signal.aborted, true);
  resolvePrevious(changesReport()); await loading;
  assert.equal(app.byId("changes-previous-period").textContent, "2025년 2분기");
  assert.equal(app.byId("changes-result").hidden, false);
});

test("returning to the original period mode still rejects a superseded response", async () => {
  let resolveFirst, requests = 0;
  const app = await openChangesApp({ fetch: (url) => {
    if (url.startsWith("/api/onboarding/changes?") && ++requests === 1) return new Promise((resolve) => { resolveFirst = resolve; });
  } });
  const first = app.byId("changes-run").emit("click");
  await app.selectChangesMode("yoy"); await app.selectChangesMode("qoq"); await app.click("changes-run");
  const stale = changesReport(); stale.metrics[0].current.value_text = "999999999";
  resolveFirst(stale); await first;
  assert.equal(app.byId("changes-rows").children[0].children[1].textContent, "1,500,000원");
});

test("changes 429 and 503 errors support retry while a 409 requires confirmed conditions again", async () => {
  for (const status of [429, 503]) {
    let requests = 0;
    const app = await openChangesApp({ fetch: (url) => {
      if (url.startsWith("/api/onboarding/changes?") && ++requests === 1) return { httpStatus: status, payload: { detail: "기간 변화 자료를 다시 불러와 주세요." } };
    } });
    await app.click("changes-run"); assert.equal(app.byId("changes-result").hidden, true); assert.equal(app.byId("changes-retry").hidden, false);
    assert.equal(app.byId("report-menu-comparison").disabled, false);
    await app.click("changes-retry"); assert.equal(app.byId("changes-result").hidden, false); assert.equal(requests, 2);
  }
  const conflict = await openChangesApp({ fetch: (url) => url.startsWith("/api/onboarding/changes?") ? { httpStatus: 409, payload: { detail: "조건이 변경됐습니다." } } : undefined });
  await conflict.click("changes-run");
  assert.equal(conflict.byId("changes-retry").hidden, true); assert.equal(conflict.byId("changes-mode").disabled, true);
  assert.equal(conflict.byId("report-menu-sales").disabled, true);
  await conflict.click("changes-reconfigure"); assert.equal(conflict.byId("analysis-panel").hidden, false);
});

test("all five report menus share the same saved conditions without keeping another report's numbers or sources", async () => {
  const app = await openChangesApp(); await app.click("changes-run");
  for (const feature of ["comparison", "population", "stores", "sales", "changes"]) {
    await app.click(`report-menu-${feature}`);
    if (feature === "comparison") await runComparison(app);
    if (feature === "changes") await app.click("changes-run");
    for (const other of ["sales", "stores", "population", "comparison", "changes"]) {
      assert.equal(app.byId(`${other}-panel`).hidden, other !== feature, `${feature} must be the only visible report`);
      if (other !== feature) { assert.equal(app.byId(`${other}-result`).hidden, true); assert.equal(app.byId(`${other}-sources`).children.length, 0); }
    }
    assert.equal(app.byId(`${feature}-result`).hidden, false);
    assert.match(app.byId(`${feature}-condition`).textContent, /커피-음료.*2026년 2분기|2026년 2분기.*커피-음료/);
  }
  assert.equal(app.calls.filter((call) => call.method !== "GET").length, 0);
});

test("leaving a slow period request for each other report aborts it and never restores its stale table", async () => {
  for (const destination of ["sales", "stores", "population", "comparison"]) {
    let resolveChanges;
    const app = await openChangesApp({ fetch: (url) => url.startsWith("/api/onboarding/changes?") ? new Promise((resolve) => { resolveChanges = resolve; }) : undefined });
    const loading = app.byId("changes-run").emit("click"); await app.click(`report-menu-${destination}`);
    resolveChanges(changesReport()); await loading;
    assert.equal(app.calls.find((call) => call.url.startsWith("/api/onboarding/changes?")).signal.aborted, true);
    assert.equal(app.byId("changes-panel").hidden, true); assert.equal(app.byId("changes-rows").children.length, 0);
    assert.equal(app.byId(`${destination}-panel`).hidden, false);
  }
});

test("period changes keep B1 back navigation, then a new saved quarter is used on every subsequent feature request", async () => {
  const app = await createApp({ profile: profile(), analysisSelection: analysisSelection() });
  await app.click("open-analysis"); await app.click("view-sales-analysis"); await app.click("report-menu-changes"); await app.click("changes-run");
  assert.equal(app.byId("changes-back").textContent, "상권 설정으로");
  await app.click("changes-back"); assert.equal(app.byId("analysis-quarter").value, "20262");
  await app.selectQuarter("20261"); await app.click("save-analysis"); await app.click("view-sales-analysis"); await app.click("report-menu-changes"); await app.click("changes-run");
  assert.equal(app.byId("changes-current-period").textContent, "2026년 1분기");
  assert.equal(app.byId("changes-previous-period").textContent, "2025년 4분기");
  assert.equal(app.calls.filter((call) => call.url.startsWith("/api/onboarding/changes?")).at(-1).url, "/api/onboarding/changes?comparison=qoq&expected_revision=8");
  await app.click("changes-back"); await app.click("analysis-back"); await app.click("edit-profile"); await app.selectIndustry("CS300028"); await app.submit();
  for (const feature of ["sales", "stores", "population", "comparison", "changes"]) { await app.click(`report-menu-${feature}`); assert.equal(app.byId(`${feature}-panel`).hidden, true); }
});

test("period source metadata and labels stay inert and cannot introduce unsafe links", async () => {
  const report = changesReport(); report.summary = ["<img src=x onerror=alert(1)>"]; report.warnings = ["<script>attacked=true</script>"];
  report.metrics[0].label = "<svg onload=alert(1)>";
  report.metrics.forEach((metric) => { metric.source.url = "javascript:alert(1)"; });
  const app = await openChangesApp({ changesReport: report }); await app.click("changes-run");
  assert.match(app.byId("changes-result-note").textContent, /<img/);
  assert.match(app.byId("changes-warnings").textContent, /<script>/);
  assert.equal(app.byId("changes-panel").querySelectorAll("img").length, 0); assert.equal(app.byId("changes-panel").querySelectorAll("svg").length, 0); assert.equal(app.byId("changes-panel").querySelectorAll("script").length, 0);
  assert.equal(app.byId("changes-sources").children.length, 0);
});

const expandedPeriodCodes = ["20262", "20261", "20254", "20253", "20252", "20251", "20244", "20243"];

test("eight supplied quarters are sorted and shown compactly with a complete expandable list, without inventing an unpublished quarter", async () => {
  const area = analysisCandidate("market-a", "all", ["20244", "20262", "20243", "20254", "20251", "20261", "20252", "20253"]);
  const app = await createApp({ profile: profile(), analysisCandidates: [area] }); await app.click("open-analysis"); await app.selectAnalysis("market-a");
  assert.deepEqual(app.byId("analysis-quarter").options.filter((option) => option.value).map((option) => option.value), expandedPeriodCodes);
  assert.equal(app.byId("analysis-quarter").options.some((option) => option.value === "20263"), false);
  for (const card of app.byId("analysis-coverage").children) {
    assert.equal(card.querySelector(".coverage-period").textContent, "제공 분기: 2024년 3분기 ~ 2026년 2분기 · 8개 분기");
    const details = card.querySelector("details");
    assert.ok(details); assert.equal(details.open, false);
    assert.equal(details.querySelector("summary").textContent, "제공 분기 목록 (8개)");
    assert.deepEqual(details.querySelector("p").textContent.split(" · "), expandedPeriodCodes.map((code) => `${code.slice(0, 4)}년 ${code[4]}분기`));
  }
});

test("expanded coverage counts actual per-metric quarters and marks gaps instead of implying continuous availability", async () => {
  const area = analysisCandidate("market-a", "all", expandedPeriodCodes);
  for (const period of area.availability.periods) {
    if (["20261", "20252"].includes(period.code)) period.metrics.sales.status = "no_observation";
    if (period.code === "20254") period.metrics.stores.status = "not_collected";
  }
  const app = await createApp({ profile: profile(), analysisCandidates: [area] }); await app.click("open-analysis"); await app.selectAnalysis("market-a");
  const cards = app.byId("analysis-coverage").children;
  assert.match(cards[0].querySelector(".coverage-period").textContent, /2024년 3분기 ~ 2026년 2분기 중 6개 분기/);
  assert.doesNotMatch(cards[0].querySelector("details").textContent, /2026년 1분기|2025년 2분기/);
  assert.match(cards[1].querySelector(".coverage-period").textContent, /중 7개 분기/);
  assert.match(cards[2].querySelector(".coverage-period").textContent, /· 8개 분기/);
  await app.selectQuarter("20261");
  assert.match(app.byId("analysis-coverage").children[0].textContent, /관측 자료 없음/);
  assert.match(app.byId("analysis-coverage").children[1].textContent, /전분기: 비교 분기 자료 없음/);
  await app.selectQuarter("20254");
  assert.match(app.byId("analysis-coverage").children[1].textContent, /자료 미확보/);
  assert.equal(app.byId("save-analysis").disabled, false, "Other confirmed metrics can still support the selected quarter");
});

test("the added 2025 Q4, 2025 Q1 and 2024 Q4 quarters save and flow unchanged through all five report menus", async () => {
  for (const [current, previous] of [["20254", "20253"], ["20251", "20244"], ["20244", "20243"]]) {
    const app = await createApp({ profile: profile(), analysisCandidates: [analysisCandidate("market-a", "all", expandedPeriodCodes)] });
    await app.click("open-analysis"); await app.selectAnalysis("market-a"); await app.selectQuarter(current); await app.click("save-analysis");
    assert.equal(app.calls.find((call) => call.url.endsWith("analysis-selection") && call.method === "POST").body.period, current);
    await app.click("view-sales-analysis");
    const label = `${current.slice(0, 4)}년 ${current[4]}분기`;
    for (const feature of ["sales", "stores", "population", "comparison", "changes"]) {
      if (feature !== "sales") await app.click(`report-menu-${feature}`);
      if (feature === "comparison") await runComparison(app);
      if (feature === "changes") await app.click("changes-run");
      assert.equal(app.byId(`${feature}-result`).hidden, false);
      assert.ok(app.byId(`${feature}-condition`).textContent.includes(label));
    }
    assert.equal(app.byId("changes-previous-period").textContent, `${previous.slice(0, 4)}년 ${previous[4]}분기`);
    assert.ok(app.calls.filter((call) => /\/(sales|stores|population|comparison|changes)\?/.test(call.url)).every((call) => call.url.includes("expected_revision=8")));
  }
});

test("an expanded source range still leaves an outside comparison quarter uncollected instead of using the nearest available period", async () => {
  const selection = analysisSelection({ period: "20244", period_label: "2024년 4분기" });
  const report = changesReport(profile(), selection, 7, "yoy"); report.status = "no_comparison"; report.summary = [];
  for (const metric of report.metrics) Object.assign(metric, { previous: { status: "not_collected", value: null, value_text: null }, status: "unavailable", delta: null, delta_text: null, percent: null, percent_status: "unavailable" });
  const app = await openChangesApp({ analysisSelection: selection, changesReport: report }); await app.selectChangesMode("yoy"); await app.click("changes-run");
  assert.equal(app.byId("changes-current-period").textContent, "2024년 4분기");
  assert.equal(app.byId("changes-previous-period").textContent, "2023년 4분기");
  assert.ok(app.byId("changes-rows").children.every((row) => row.children[2].textContent === "자료 미확보" && row.children[3].textContent === "비교 불가"));
  assert.equal(app.calls.filter((call) => call.url.startsWith("/api/onboarding/changes?")).length, 1);
});

test("server-provided expanded source scope replaces the old 10-area note and does not imply every industry has observations", async () => {
  const expandedNote = "공개 상권 1,650개를 대상으로 8개 분기의 자료를 조회했습니다. 업종별 관측 행은 별도로 확인합니다.";
  const report = storesReport(); report.status = "no_observation";
  report.source.coverage_note = expandedNote; report.source.collected_area_count = 1650;
  for (const metric of Object.values(report.counts)) Object.assign(metric, { status: "no_observation", value: null, value_text: null });
  report.composition = { status: "no_data", franchise_share_percent: null, denominator: { label: "전체 점포 수", value: null, value_text: null }, warnings: [] };
  const comparison = comparisonReport(), changes = changesReport();
  for (const response of [comparison, changes]) { response.warnings = [expandedNote]; response.metrics.forEach((metric) => { metric.warnings = []; }); }
  const app = await openChangesApp({ storesReport: report, comparisonReport: comparison, changesReport: changes });
  await app.click("report-menu-stores");
  assert.ok(app.byId("stores-scope").textContent.includes(expandedNote));
  assert.doesNotMatch(app.byId("stores-scope").textContent, /10개 상권/);
  assert.equal(app.byId("stores-total").textContent, "관측 행 없음");
  assert.notEqual(app.byId("stores-total").textContent, "0개");
  await app.click("report-menu-comparison"); await runComparison(app);
  assert.equal(app.byId("comparison-warnings").children[0].textContent, expandedNote);
  await app.click("report-menu-changes"); await app.click("changes-run");
  assert.equal(app.byId("changes-warnings").children[0].textContent, expandedNote);
});

test("an expanded catalogue requires the old saved selection to be reconfirmed before reports use the new version", async () => {
  const stale = analysisSelection({ status: "stale", analysis_setup_complete: false, conditions_confirmed: false, catalog_version: "catalog-old", message: "자료가 갱신됐어요. 분석 조건을 다시 확인해 주세요." });
  const app = await createApp({ profile: profile(), analysisSelection: stale, catalogVersion: "catalog-expanded", analysisCandidates: [analysisCandidate("market-a", "all", expandedPeriodCodes)] });
  assert.equal(app.byId("view-sales-overview").hidden, true);
  for (const feature of ["sales", "stores", "population", "comparison", "changes"]) { await app.click(`report-menu-${feature}`); assert.equal(app.byId(`${feature}-panel`).hidden, true); }
  await app.click("open-analysis");
  assert.equal(app.byId("analysis-quarter").options.filter((option) => option.value).length, 8);
  assert.match(app.byId("analysis-data-message").textContent, /다시 확인/);
  assert.equal(app.byId("save-analysis").disabled, false);
  await app.selectQuarter("20254"); await app.click("save-analysis");
  assert.deepEqual(app.calls.find((call) => call.url.endsWith("analysis-selection") && call.method === "POST").body, { area_code: "market-a", period: "20254", expected_revision: 7, expected_catalog_version: "catalog-expanded" });
  await app.click("view-sales-analysis"); await app.click("report-menu-comparison"); await runComparison(app);
  assert.equal(app.byId("comparison-result").hidden, false);
  await app.click("report-menu-changes"); await app.click("changes-run");
  assert.equal(app.byId("changes-current-period").textContent, "2025년 4분기");
  assert.equal(app.byId("changes-previous-period").textContent, "2025년 3분기");
  assert.equal(app.byId("changes-result").hidden, false);
});
