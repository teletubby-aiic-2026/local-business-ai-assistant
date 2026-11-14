"use strict";

(() => {
  const byId = (id) => document.getElementById(id);
  const state = {
    options: null, profile: null, revision: 0, editing: false,
    locationDirty: true, searchId: null, candidates: [], selectedCandidate: null, selectedStation: null,
    searchSequence: 0, searchController: null, searching: false, submitting: false,
    addressComposing: false,
    areaSearchId: null, areaCandidates: [], selectedAreaCandidate: null,
    areaSequence: 0, areaController: null, areaSearching: false,
  };
  const mapState = {
    configPromise: null, sdkPromise: null, sdkScript: null, instance: null, marker: null,
    selectionVersion: 0, selectedPoint: null, selectionKey: null, failure: null,
    authFailed: false, forceScript: false, loadVersion: 0,
    polygons: [], polygonListeners: [], analysisBounds: null,
  };
  const analysisState = {
    active: false, saved: null, candidates: [], catalogVersion: null, scope: null,
    selectedCode: "", period: "", loading: false, saving: false, conflict: false,
    sequence: 0, controller: null,
  };
  const salesState = { active: false, origin: "overview", sequence: 0, controller: null, loading: false, conflict: false };
  const storesState = { active: false, origin: "overview", sequence: 0, controller: null, loading: false, conflict: false };
  const populationState = { active: false, origin: "overview", sequence: 0, controller: null, loading: false, conflict: false };
  const comparisonState = { active: false, origin: "overview", sequence: 0, controller: null, loading: false, conflict: false, optionsSequence: 0, optionsController: null, optionsLoading: false, areas: [], catalogVersion: null };
  const changesState = { active: false, origin: "overview", sequence: 0, controller: null, loading: false, conflict: false };
  const postcodeState = { sdkPromise: null, sdkScript: null, sequence: 0 };
  const descriptions = {
    operating: "가게를 운영하고 있어요",
    planning: "창업을 준비하고 있어요",
    exploring: "아직 알아보는 중이에요",
  };
  const industryGroups = [
    { prefix: "CS1", label: "음식" },
    { prefix: "CS2", label: "서비스" },
    { prefix: "CS3", label: "소매·판매" },
  ];

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: "same-origin", cache: "no-store", ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    let result;
    try { result = await response.json(); }
    catch { throw new Error("응답을 읽지 못했어요. 잠시 후 다시 시도해 주세요."); }
    if (!response.ok) {
      let message = "요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.";
      if (typeof result.detail === "string") message = result.detail;
      else if (Array.isArray(result.detail)) message = result.detail.map((entry) => entry.msg || "입력 내용을 확인해 주세요.").join(" ");
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return result;
  }

  function currentMapLocation() {
    if (state.profile && (!state.editing || !state.locationDirty)) return state.profile.location;
    const kind = selectedKind();
    if (kind === "address") return state.selectedCandidate ? { ...state.selectedCandidate, kind } : null;
    if (kind === "station") return state.selectedStation ? { ...state.selectedStation, kind, label: state.selectedStation.name } : null;
    const neighborhood = selectedNeighborhood();
    if (!neighborhood) return null;
    return { kind, label: `${neighborhood.district_name} · ${neighborhood.name}`, reference_point: state.selectedAreaCandidate };
  }

  function mapPoint(location) {
    if (!location) return null;
    const reference = location.reference_point || location;
    const values = [reference.latitude, reference.longitude];
    if (values.some((value) => value == null || typeof value === "boolean" || (typeof value === "string" && !value.trim()))) return null;
    const [latitude, longitude] = values.map(Number);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return null;
    return { latitude, longitude, label: location.label || location.name, kind: location.kind };
  }

  function showMapOverlay(title, description, retry = false) {
    byId("map-overlay-title").textContent = title;
    byId("map-overlay-description").textContent = description;
    byId("map-overlay").hidden = false;
    byId("map-retry").hidden = !retry;
    byId("map-recenter").disabled = true;
  }

  function mapFailure(message) {
    mapState.failure = message;
    detachMapMarker();
    detachMapPolygons();
    mapState.instance = null;
    byId("map-recenter").disabled = true;
    if (mapState.selectedPoint || analysisState.active) {
      showMapOverlay("지도를 표시하지 못했어요.", message, true);
      byId("map-status").textContent = analysisState.active
        ? "지도 연결과 관계없이 목록에서 상권을 선택하고 분석 조건을 저장할 수 있어요."
        : "지도 연결과 관계없이 가게 정보는 저장할 수 있어요.";
    }
  }

  function detachMapMarker() {
    // An unauthorised/partially initialised SDK can throw even during cleanup.
    // Drop our reference first and keep that failure out of form event handlers.
    const marker = mapState.marker;
    mapState.marker = null;
    if (!marker) return true;
    try { marker.setMap(null); return true; }
    catch { mapState.instance = null; return false; }
  }

  function ensureMapSDK() {
    if (!mapState.sdkPromise) mapState.sdkPromise = loadMapSDK();
    return mapState.sdkPromise;
  }

  async function loadMapSDK() {
    const loadVersion = mapState.loadVersion;
    if (window.naver?.maps && !mapState.forceScript && !mapState.authFailed) return window.naver.maps;
    mapState.configPromise ||= api("/api/onboarding/map-config");
    const config = await mapState.configPromise;
    if (loadVersion !== mapState.loadVersion) throw new Error("이전 지도 요청이 취소됐어요.");
    if (!config.configured || typeof config.client_id !== "string" || !config.client_id.trim()) {
      throw new Error("현재 지도 연결이 준비되지 않았어요. 잠시 후 다시 확인해 주세요.");
    }
    return new Promise((resolve, reject) => {
      let settled = false;
      const script = document.createElement("script");
      const finish = (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        if (error) reject(error); else resolve(window.naver.maps);
      };
      const timeout = setTimeout(() => finish(new Error("지도 연결 시간이 초과됐어요. 다시 시도해 주세요.")), 15000);
      window.navermap_authFailure = () => {
        if (loadVersion !== mapState.loadVersion) return;
        mapState.authFailed = true;
        const message = "지도 서비스 인증을 확인하지 못했어요. 주소 검색과 정보 저장은 계속 이용할 수 있어요.";
        mapFailure(message);
        finish(new Error(message));
      };
      script.async = true;
      script.src = `https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId=${encodeURIComponent(config.client_id)}`;
      script.onload = () => {
        if (!window.naver?.maps || mapState.authFailed) finish(new Error("지도 서비스를 불러오지 못했어요. 다시 시도해 주세요."));
        else finish();
      };
      script.onerror = () => finish(new Error("지도 연결이 원활하지 않아요. 네트워크를 확인하고 다시 시도해 주세요."));
      mapState.sdkScript = script;
      mapState.forceScript = false;
      document.head.append(script);
    });
  }

  function updateLocationMap(location) {
    try { if (analysisState.active) renderAnalysisMap(); else renderLocationMap(location); }
    catch { mapFailure("지도 연결을 확인하지 못했어요. 입력과 정보 저장은 계속 이용할 수 있어요."); }
  }

  function renderLocationMap(location) {
    detachMapPolygons();
    mapState.analysisBounds = null;
    byId("map-heading").textContent = "지도에서 위치를 확인하세요.";
    byId("map-recenter").textContent = "선택 지점으로";
    const point = mapPoint(location);
    const kind = location?.kind;
    byId("map-kind-tag").textContent = kind === "address" ? "주소 지점" : kind === "station" ? "역 기준" : kind === "area" ? "동네 참고" : "선택 전";
    byId("map-location-title").textContent = location?.label || location?.name || "선택한 위치가 여기에 표시됩니다.";
    byId("map-location-note").textContent = kind === "address" ? "주소 지점이에요. 실제 분석 범위는 다음 단계에서 정해요."
      : kind === "station" ? "역 기준 지점이에요. 분석할 상권은 다음 단계에서 직접 확인해요."
        : kind === "area" ? "동네의 참고 지점이며, 정확한 가게 주소나 상권 경계는 아니에요."
          : "실제 분석 범위는 다음 단계에서 정해요.";
    const savedAnalysis = analysisState.saved;
    if (savedAnalysis?.analysis_setup_complete === true && savedAnalysis.status !== "stale" && savedAnalysis.status !== "unavailable"
      && (!state.editing || (!state.locationDirty && byId("industry-select").value === savedAnalysis.industry_code))) {
      byId("map-location-note").textContent = `저장한 분석 상권: ${savedAnalysis.area_name}. 지도에는 가게의 기준 위치를 표시해요.`;
    }
    const key = point ? JSON.stringify(point) : `empty:${kind || "none"}:${location?.label || ""}`;
    if (mapState.selectionKey === key) return;
    mapState.selectionKey = key;
    mapState.selectedPoint = point;
    mapState.selectionVersion += 1;
    const version = mapState.selectionVersion;
    byId("map-status").textContent = "";
    if (!point) {
      detachMapMarker();
      if (kind === "area") showMapOverlay("동네를 검색해 지도에서 확인해 주세요.", "‘지도에서 확인’을 눌러 참고 위치를 선택할 수 있어요.");
      else if (kind === "station") showMapOverlay("이 역의 지도 좌표는 아직 확인 중이에요.", "주소로 검색하면 지도에서 정확한 지점을 확인할 수 있어요.");
      else showMapOverlay("주소나 역을 선택해 주세요.", "선택한 지점을 지도에서 확인할 수 있어요.");
      return;
    }
    if (mapState.failure) { mapFailure(mapState.failure); return; }
    showMapOverlay("선택한 위치를 지도에 표시하고 있어요.", "잠시만 기다려 주세요.");
    ensureMapSDK().then((maps) => {
      if (version !== mapState.selectionVersion || mapState.authFailed) return;
      const position = new maps.LatLng(point.latitude, point.longitude);
      if (!mapState.instance) {
        mapState.instance = new maps.Map("location-map", {
          center: position, zoom: point.kind === "address" ? 17 : 16,
          zoomControl: true, zoomControlOptions: { position: maps.Position.TOP_RIGHT },
          mapTypeControl: false, scaleControl: true,
        });
      } else {
        mapState.instance.setCenter(position);
        mapState.instance.setZoom(point.kind === "address" ? 17 : 16);
      }
      if (mapState.authFailed || version !== mapState.selectionVersion) {
        detachMapMarker();
        mapState.instance = null;
        return;
      }
      if (!detachMapMarker()) throw new Error("이전 지도 표시를 정리하지 못했어요. 지도를 다시 불러와 주세요.");
      mapState.marker = new maps.Marker({ position, map: mapState.instance, title: point.label });
      if (mapState.authFailed) return;
      byId("map-overlay").hidden = true;
      byId("map-recenter").disabled = false;
    }).catch((error) => { if (version === mapState.selectionVersion) mapFailure(error.message || "지도를 표시하지 못했어요. 다시 시도해 주세요."); });
  }

  function retryMap() {
    mapState.loadVersion += 1;
    mapState.failure = null;
    mapState.authFailed = false;
    mapState.configPromise = null;
    mapState.sdkPromise = null;
    mapState.sdkScript?.remove();
    mapState.sdkScript = null;
    mapState.forceScript = true;
    detachMapMarker();
    detachMapPolygons();
    mapState.instance = null;
    byId("location-map").replaceChildren();
    mapState.selectionKey = null;
    updateLocationMap(currentMapLocation());
  }

  function detachMapPolygons() {
    const polygons = mapState.polygons;
    const listeners = mapState.polygonListeners;
    mapState.polygons = [];
    mapState.polygonListeners = [];
    try { if (listeners.length) window.naver?.maps?.Event?.removeListener(listeners); } catch { /* SDK cleanup cannot block the form. */ }
    for (const polygon of polygons) {
      try { polygon.setMap(null); } catch { mapState.instance = null; }
    }
  }

  function candidatePolygons(candidate) {
    const geometry = candidate?.geometry;
    const polygons = geometry?.type === "Polygon" ? [geometry.coordinates]
      : geometry?.type === "MultiPolygon" ? geometry.coordinates : [];
    if (!Array.isArray(polygons)) return [];
    return polygons.filter((polygon) => Array.isArray(polygon) && polygon.length
      && polygon.every((ring) => Array.isArray(ring) && ring.length >= 4
        && ring.every((position) => Array.isArray(position) && position.length >= 2
          && typeof position[0] === "number" && typeof position[1] === "number"
          && Number.isFinite(position[0]) && Number.isFinite(position[1])
          && Math.abs(position[0]) <= 180 && Math.abs(position[1]) <= 90)));
  }

  function analysisBounds(features, point) {
    const positions = features.flatMap((feature) => feature.paths.flat());
    if (point) positions.push([point.longitude, point.latitude]);
    if (!positions.length) return null;
    let west = 180, south = 90, east = -180, north = -90;
    for (const [longitude, latitude] of positions) {
      west = Math.min(west, longitude); east = Math.max(east, longitude);
      south = Math.min(south, latitude); north = Math.max(north, latitude);
    }
    return [west, south, east, north];
  }

  function fitAnalysisBounds(maps, bounds) {
    if (!bounds || !mapState.instance) return;
    mapState.instance.fitBounds(new maps.LatLngBounds(new maps.LatLng(bounds[1], bounds[0]), new maps.LatLng(bounds[3], bounds[2])), 40);
  }

  function renderAnalysisMap() {
    const selected = selectedAnalysisCandidate();
    const point = mapPoint(state.profile?.location);
    const features = analysisState.candidates.flatMap((candidate) => candidatePolygons(candidate).map((paths) => ({ candidate, paths })));
    const selectedFeatures = selected ? features.filter((feature) => feature.candidate.area_code === selected.area_code) : features;
    const bounds = analysisBounds(selectedFeatures.length ? selectedFeatures : features, point);
    const key = `analysis:${analysisState.sequence}:${analysisState.catalogVersion || "loading"}:${analysisState.candidates.map((candidate) => candidate.area_code).join(",")}:${analysisState.selectedCode}:${state.revision}`;
    byId("map-heading").textContent = "공식 상권 경계를 확인하세요.";
    byId("map-kind-tag").textContent = selected ? "선택 상권" : "상권 후보";
    byId("map-location-title").textContent = selected?.name || "목록이나 지도에서 분석할 상권을 선택해 주세요.";
    byId("map-location-note").textContent = analysisState.scope?.boundary_notice || "2023년 공개 경계이며 현재 분기 경계와의 동일성은 확인되지 않았어요.";
    byId("map-recenter").textContent = selected ? "선택 상권으로" : "후보 전체 보기";
    if (mapState.selectionKey === key) return;
    mapState.selectionKey = key;
    mapState.selectedPoint = point;
    mapState.analysisBounds = bounds;
    const version = ++mapState.selectionVersion;
    detachMapPolygons();
    detachMapMarker();
    byId("map-status").textContent = selected && !selectedFeatures.length
      ? "이 상권의 경계를 표시하지 못했어요. 목록과 자료 제공 범위는 계속 확인할 수 있어요."
      : !point && features.length ? "기준 위치의 좌표는 없어 표시하지 않았어요. 공식 상권 경계만 보여드려요." : "";
    if (analysisState.loading && !analysisState.catalogVersion) {
      showMapOverlay("공식 상권 후보를 확인하고 있어요.", "확인이 끝나면 후보 경계를 함께 표시해요.");
      return;
    }
    if (!bounds) {
      showMapOverlay(analysisState.candidates.length ? "상권 경계를 표시하지 못했어요." : "표시할 상권 후보가 없어요.",
        analysisState.candidates.length ? "상권 목록과 자료 제공 범위는 왼쪽에서 확인해 주세요." : "가게 정보에서 주소나 다른 위치를 선택해 주세요.");
      return;
    }
    if (mapState.failure) { mapFailure(mapState.failure); return; }
    showMapOverlay("공식 상권 경계를 표시하고 있어요.", "지도 표시와 관계없이 왼쪽 목록에서 선택할 수 있어요.");
    ensureMapSDK().then((maps) => {
      if (!analysisState.active || version !== mapState.selectionVersion || mapState.authFailed) return;
      const center = new maps.LatLng((bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2);
      if (!mapState.instance) mapState.instance = new maps.Map("location-map", { center, zoom: 15, zoomControl: true, zoomControlOptions: { position: maps.Position.TOP_RIGHT }, mapTypeControl: false, scaleControl: true });
      for (const feature of features) {
        const active = feature.candidate.area_code === analysisState.selectedCode;
        const polygon = new maps.Polygon({
          map: mapState.instance,
          paths: feature.paths.map((ring) => ring.map(([longitude, latitude]) => new maps.LatLng(latitude, longitude))),
          strokeColor: active ? "#18594d" : "#718f7e", strokeWeight: active ? 3 : 1.5,
          strokeOpacity: 0.9, fillColor: active ? "#2d8d70" : "#91b49e", fillOpacity: active ? 0.27 : 0.12,
          clickable: true, zIndex: active ? 2 : 1,
        });
        mapState.polygons.push(polygon);
        mapState.polygonListeners.push(maps.Event.addListener(polygon, "click", () => {
          if (analysisState.active && version === mapState.selectionVersion) selectAnalysisCandidate(feature.candidate.area_code);
        }));
      }
      if (point) mapState.marker = new maps.Marker({ position: new maps.LatLng(point.latitude, point.longitude), map: mapState.instance, title: state.profile.location.label });
      if (features.length) fitAnalysisBounds(maps, bounds);
      else { mapState.instance.setCenter(center); mapState.instance.setZoom(16); }
      if (!analysisState.active || version !== mapState.selectionVersion || mapState.authFailed) return;
      byId("map-overlay").hidden = true;
      byId("map-recenter").disabled = false;
    }).catch((error) => { if (version === mapState.selectionVersion) mapFailure(error.message || "상권 경계를 표시하지 못했어요. 다시 시도해 주세요."); });
  }

  function clearAppError() {
    byId("app-message").hidden = true;
    byId("app-message").textContent = "";
    byId("retry-load").hidden = true;
  }

  function showAppError(error) {
    const conflict = error.status === 409;
    byId("app-message").textContent = conflict
      ? "다른 창에서 가게 정보가 변경됐어요. 최신 정보를 불러온 뒤 다시 수정해 주세요."
      : error.message || "연결을 확인한 뒤 다시 시도해 주세요.";
    byId("app-message").hidden = false;
    if (conflict) {
      byId("retry-load").textContent = "최신 정보 불러오기";
      byId("retry-load").hidden = false;
    }
  }

  function fieldError(id, message) {
    const element = byId(id);
    element.textContent = message;
    element.hidden = !message;
  }

  function clearFieldErrors() {
    ["location-error", "industry-error", "status-error"].forEach((id) => fieldError(id, ""));
  }

  function selectedKind() {
    return document.querySelector('input[name="location-kind"]:checked')?.value || "address";
  }

  function selectedStatus() {
    return document.querySelector('input[name="business-status"]:checked')?.value || "";
  }

  function setSummary(id, value, placeholder) {
    byId(id).textContent = value || placeholder;
    byId(id).classList.toggle("empty", !value);
  }

  function updateSummary() {
    if (state.profile && !state.editing) {
      const savedLocation = state.profile.location;
      const label = savedLocation.kind === "address" ? savedLocation.label : `${savedLocation.district_name} · ${savedLocation.label}`;
      setSummary("summary-location", label, "위치를 알려주세요");
      setSummary("summary-industry", state.profile.industry.name, "업종을 선택해 주세요");
      setSummary("summary-status", state.profile.business_status_label, "운영 단계를 선택해 주세요");
      byId("summary-badge").textContent = "저장됨";
      updateLocationMap(currentMapLocation());
      return;
    }
    let location = "";
    if (!state.locationDirty && state.profile) {
      const savedLocation = state.profile.location;
      location = savedLocation.kind === "address" ? savedLocation.label : `${savedLocation.district_name} · ${savedLocation.label}`;
    }
    else if (selectedKind() === "address") location = state.selectedCandidate?.label || "";
    else if (selectedKind() === "station") {
      if (state.selectedStation) location = `${state.selectedStation.district_name} · ${state.selectedStation.name}`;
    }
    else {
      const neighborhood = selectedNeighborhood();
      if (neighborhood) location = `${neighborhood.district_name} · ${neighborhood.name}`;
    }
    const industry = state.options?.industries.find((item) => item.code === byId("industry-select").value);
    const status = state.options?.business_statuses.find((item) => item.code === selectedStatus());
    setSummary("summary-location", location, "주소나 지역을 알려주세요");
    setSummary("summary-industry", industry?.name, "업종을 선택해 주세요");
    setSummary("summary-status", status?.label, "운영 단계를 선택해 주세요");
    byId("summary-badge").textContent = state.profile ? "수정 중" : "입력 중";
    updateLocationMap(currentMapLocation());
  }

  function setSearchBusy(value) {
    state.searching = value;
    byId("search-address").disabled = value || state.submitting || state.addressComposing;
    byId("verify-address").disabled = value || state.submitting || state.addressComposing || !byId("address-query").value.trim();
    byId("search-address").textContent = value ? "주소 확인 중…" : "주소 찾기";
    byId("address-results-wrap").setAttribute("aria-busy", String(value));
  }

  function invalidateAddressSearch() {
    closeAddressPicker(false);
    state.searchSequence += 1;
    state.searchController?.abort();
    state.searchController = null;
    state.searchId = null;
    state.candidates = [];
    state.selectedCandidate = null;
    byId("address-results").replaceChildren();
    byId("address-results-wrap").hidden = true;
    byId("address-query").setAttribute("aria-expanded", "false");
    byId("address-search-message").textContent = "";
    setSearchBusy(false);
  }

  function handleAddressInput() {
    locationChanged();
  }

  function closeAddressPicker(restoreFocus = true) {
    postcodeState.sequence += 1;
    const dialog = byId("address-dialog");
    const wasOpen = dialog.open;
    if (wasOpen) dialog.close();
    if (wasOpen && restoreFocus && selectedKind() === "address") byId("search-address").focus();
  }

  function ensurePostcodeSDK() {
    if (typeof window.kakao?.Postcode === "function") return Promise.resolve(window.kakao.Postcode);
    if (postcodeState.sdkPromise) return postcodeState.sdkPromise;
    postcodeState.sdkPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      let settled = false;
      const finish = (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        if (error) {
          postcodeState.sdkPromise = null;
          script.remove();
          reject(error);
        } else resolve(window.kakao.Postcode);
      };
      const timeout = setTimeout(() => finish(new Error("주소 검색창 연결 시간이 초과됐어요. 다시 시도해 주세요.")), 15000);
      script.async = true;
      script.src = "https://t1.kakaocdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js";
      script.onload = () => finish(typeof window.kakao?.Postcode === "function" ? null : new Error("주소 검색창을 불러오지 못했어요."));
      script.onerror = () => finish(new Error("주소 검색 서비스에 연결하지 못했어요."));
      postcodeState.sdkScript = script;
      document.head.append(script);
    });
    return postcodeState.sdkPromise;
  }

  async function openAddressPicker() {
    if (state.submitting || state.searching || state.addressComposing || selectedKind() !== "address") return;
    closeAddressPicker(false);
    const sequence = postcodeState.sequence;
    const searchSequence = state.searchSequence;
    const originalQuery = byId("address-query").value.trim();
    const active = () => sequence === postcodeState.sequence && searchSequence === state.searchSequence
      && selectedKind() === "address" && byId("address-query").value.trim() === originalQuery && byId("address-dialog").open;
    byId("postcode-container").replaceChildren();
    byId("postcode-message").textContent = "주소 검색창을 불러오고 있어요.";
    byId("address-dialog").showModal();
    try {
      const Postcode = await ensurePostcodeSDK();
      if (!active()) return;
      byId("postcode-message").textContent = "검색 결과에서 서울특별시 안의 가게 주소를 선택해 주세요.";
      new Postcode({
        width: "100%", height: "100%", maxSuggestItems: 10, shorthand: false,
        oncomplete: (data) => {
          if (!active()) return;
          if (!data || typeof data !== "object") {
            locationChanged();
            byId("address-search-message").textContent = "주소 선택 결과를 확인하지 못했어요. 주소 찾기에서 다시 선택해 주세요.";
            return;
          }
          const region = typeof data.sido === "string" ? data.sido.trim() : "";
          const selectedAddress = data.userSelectedType === "R" ? data.roadAddress
            : data.userSelectedType === "J" ? data.jibunAddress : "";
          // Only the clicked R/J field is eligible; auto* fields are inferred
          // mappings, and this provider supplies no coordinate authority here.
          if (!["서울", "서울특별시"].includes(region) || typeof selectedAddress !== "string"
              || !/^(서울|서울특별시)\s/.test(selectedAddress.trim())) {
            locationChanged();
            byId("address-search-message").textContent = "서울특별시 주소만 등록할 수 있어요. 주소 찾기에서 다시 선택해 주세요.";
            fieldError("location-error", "서울특별시 안의 가게 주소를 선택해 주세요.");
            byId("address-query").focus();
            return;
          }
          if (!selectedAddress.trim() || selectedAddress.length > 200) {
            locationChanged();
            byId("address-search-message").textContent = "주소가 확정되지 않았어요. 주소 찾기에서 도로명 또는 지번주소를 직접 선택해 주세요.";
            byId("address-query").focus();
            return;
          }
          closeAddressPicker(false);
          byId("address-query").value = selectedAddress.trim();
          verifyAddress({ autoSelect: true, buildingName: typeof data.buildingName === "string" ? data.buildingName : "" });
        },
      }).embed(byId("postcode-container"), { q: originalQuery, autoClose: true });
    } catch (error) {
      if (!active()) return;
      closeAddressPicker(false);
      byId("address-search-message").textContent = `${error.message || "주소 검색창을 열지 못했어요."} 도로명과 건물 번호까지 입력했다면 직접 확인할 수도 있어요.`;
      byId("verify-address").hidden = false;
      setSearchBusy(false);
      byId("address-query").focus();
    }
  }

  function selectAddressCandidate(candidate) {
    if (!state.searchId || candidate.in_seoul !== true) return;
    state.selectedCandidate = candidate;
    byId("address-query").value = candidate.road_address || candidate.jibun_address || candidate.label;
    byId("address-results-wrap").hidden = true;
    byId("address-query").setAttribute("aria-expanded", "false");
    byId("address-search-message").textContent = "주소를 선택했어요. 오른쪽 지도에서 위치를 확인해 주세요.";
    byId("verify-address").hidden = true;
    fieldError("location-error", "");
    updateSummary();
  }

  function locationChanged() {
    state.locationDirty = true;
    state.selectedStation = null;
    byId("station-selection-note").hidden = true;
    byId("saved-address-note").hidden = true;
    byId("saved-area-note").hidden = true;
    invalidateAddressSearch();
    invalidateAreaSearch();
    fieldError("location-error", "");
    updateSummary();
  }

  function showLocationPanel() {
    const kind = selectedKind();
    byId("address-panel").hidden = kind !== "address";
    byId("station-panel").hidden = kind !== "station";
    byId("area-panel").hidden = kind !== "area";
    if (kind === "station") renderStationOptions(state.selectedStation?.id || "");
  }

  function selectedStationLine() {
    return (state.options?.station_lines || []).find((line) => line.code === byId("station-line-select").value) || null;
  }

  function stationsForLine() {
    const line = selectedStationLine();
    if (!line) return [];
    return (state.options?.stations || []).filter((station) =>
      Array.isArray(station.selectable_line_codes) && station.selectable_line_codes.includes(line.code))
      .sort((left, right) => left.name.localeCompare(right.name, "ko") || left.id.localeCompare(right.id));
  }

  function stationFromControls() {
    return stationsForLine().find((station) => station.id === byId("station-select").value) || null;
  }

  function renderStationLines(selectedCode = "") {
    const select = byId("station-line-select");
    const lines = state.options?.station_lines || [];
    select.replaceChildren(new Option(lines.length ? "노선을 선택해 주세요" : "노선 목록을 확인할 수 없어요", ""));
    lines.forEach((line) => select.append(new Option(line.name, line.code)));
    select.value = lines.some((line) => line.code === selectedCode) ? selectedCode : "";
    select.disabled = !lines.length;
    renderStationOptions();
  }

  function renderStationOptions(selectedId = "") {
    const select = byId("station-select");
    const line = selectedStationLine();
    const stations = stationsForLine();
    select.replaceChildren(new Option(!line ? "노선을 먼저 선택해 주세요"
      : stations.length ? "역을 선택해 주세요" : "역 목록을 확인할 수 없어요", ""));
    stations.forEach((station) => select.append(new Option(station.name, station.id)));
    select.value = stations.some((station) => station.id === selectedId) ? selectedId : "";
    select.disabled = !line || !stations.length;
    byId("station-help").textContent = !(state.options?.station_lines || []).length
      ? "노선 목록을 불러오지 못했어요. 주소 또는 동네·지역으로 입력하거나 다시 불러와 주세요."
      : !line ? "노선을 고르면 서울특별시 안의 역 목록이 나와요."
        : stations.length ? `서울특별시 안의 ${stations.length}개 역을 가나다순으로 보여드려요. 분석할 상권은 다음 단계에서 직접 확인해요.`
          : "이 노선의 역 목록을 확인하지 못했어요. 다른 노선이나 주소로 입력해 주세요.";
  }

  function selectStation(station) {
    state.locationDirty = true;
    state.selectedStation = station;
    fieldError("location-error", "");
    byId("station-selection-note").textContent = `${selectedStationLine()?.name || ""} ${station.name}을 선택했어요. 분석할 상권은 다음 단계에서 직접 확인해요.`.trim();
    byId("station-selection-note").hidden = false;
    updateSummary();
  }

  function renderCandidates() {
    const container = byId("address-results");
    container.replaceChildren();
    state.candidates.forEach((candidate, index) => {
      const label = document.createElement("label");
      label.className = "address-result";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "address-candidate";
      input.value = candidate.id;
      input.id = `address-candidate-${index}`;
      input.disabled = candidate.in_seoul !== true;
      input.checked = state.selectedCandidate?.id === candidate.id;
      input.addEventListener("change", () => {
        if (!input.checked || !state.searchId) return;
        selectAddressCandidate(candidate);
        byId("address-query").focus();
      });
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          input.checked = true;
          selectAddressCandidate(candidate);
          byId("address-query").focus();
        } else if (event.key === "Escape") {
          event.preventDefault();
          byId("address-results-wrap").hidden = true;
          byId("address-query").setAttribute("aria-expanded", "false");
          byId("address-query").focus();
        }
      });
      const copy = document.createElement("span");
      copy.className = "candidate-copy";
      const title = document.createElement("span");
      title.className = "candidate-title";
      title.textContent = candidate.road_address || candidate.jibun_address || candidate.label;
      copy.append(title);
      const alternative = candidate.jibun_address && candidate.jibun_address !== title.textContent ? candidate.jibun_address : "";
      if (alternative) {
        const subtitle = document.createElement("span");
        subtitle.className = "candidate-subtitle";
        subtitle.textContent = `지번 ${alternative}`;
        copy.append(subtitle);
      }
      if (typeof candidate.building_name === "string" && candidate.building_name.trim()) {
        const building = document.createElement("span");
        building.className = "candidate-building";
        building.textContent = candidate.building_name;
        copy.append(building);
      }
      if (!candidate.in_seoul) {
        const outside = document.createElement("span");
        outside.className = "candidate-outside";
        outside.textContent = "서울특별시 주소로 확인되지 않아 선택할 수 없어요.";
        copy.append(outside);
      }
      label.append(input, copy);
      container.append(label);
    });
    byId("address-results-wrap").hidden = state.candidates.length === 0;
    byId("address-query").setAttribute("aria-expanded", String(state.candidates.length > 0));
  }

  function neighborhoodsForDistrict() {
    const districtCode = byId("district-select").value;
    return (state.options?.neighborhoods || []).filter((item) => item.district_code === districtCode)
      .sort((left, right) => left.name.localeCompare(right.name, "ko"));
  }

  function selectedNeighborhood() {
    const districtCode = byId("district-select").value;
    const code = byId("place-text").value;
    return (state.options?.neighborhoods || []).find((item) => item.district_code === districtCode && item.code === code) || null;
  }

  function renderNeighborhoods(selectedCode = "") {
    const select = byId("place-text");
    const districtCode = byId("district-select").value;
    const neighborhoods = neighborhoodsForDistrict();
    const placeholder = !districtCode ? "자치구를 먼저 선택해 주세요"
      : neighborhoods.length ? "동네를 선택해 주세요" : "동네 목록을 확인할 수 없어요";
    select.replaceChildren(new Option(placeholder, ""));
    neighborhoods.forEach((item) => select.append(new Option(item.name, item.code)));
    select.value = neighborhoods.some((item) => item.code === selectedCode) ? selectedCode : "";
    select.disabled = !districtCode || !neighborhoods.length;
    byId("place-help").textContent = !districtCode
      ? "자치구를 선택하면 해당 구의 행정동 목록이 나와요. 정확한 가게 위치는 주소로 찾을 수 있어요."
      : neighborhoods.length
        ? `행정동 기준 ${neighborhoods.length}개 동네예요. 익숙한 동네명이 없으면 가게 주소나 가까운 역으로 찾아보세요.`
        : "이 자치구의 동네 목록을 불러오지 못했어요. 주소나 가까운 역으로 입력하거나 다시 불러와 주세요.";
    setAreaBusy(state.areaSearching);
  }

  function setAreaBusy(value) {
    state.areaSearching = value;
    byId("preview-area").disabled = value || state.submitting || !selectedNeighborhood();
    byId("preview-area").textContent = value ? "확인 중…" : "지도에서 확인";
  }

  function invalidateAreaSearch() {
    state.areaSequence += 1;
    state.areaController?.abort();
    state.areaController = null;
    state.areaSearchId = null;
    state.areaCandidates = [];
    state.selectedAreaCandidate = null;
    byId("area-results").replaceChildren();
    byId("area-results-wrap").hidden = true;
    byId("area-search-message").textContent = "";
    setAreaBusy(false);
  }

  function renderAreaCandidates() {
    const container = byId("area-results");
    container.replaceChildren();
    state.areaCandidates.forEach((candidate, index) => {
      const label = document.createElement("label");
      label.className = "address-result";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "area-candidate";
      input.id = `area-candidate-${index}`;
      input.value = candidate.id;
      input.disabled = candidate.in_seoul !== true;
      input.addEventListener("change", () => {
        if (!input.checked || !state.areaSearchId) return;
        state.selectedAreaCandidate = candidate;
        fieldError("location-error", "");
        updateSummary();
      });
      const copy = document.createElement("span");
      copy.className = "candidate-copy";
      const title = document.createElement("span");
      title.className = "candidate-title";
      title.textContent = candidate.label || candidate.road_address || candidate.jibun_address;
      const note = document.createElement("span");
      note.className = "candidate-subtitle";
      note.textContent = candidate.in_seoul ? "동네를 확인하기 위한 참고 지점이에요." : "서울특별시 위치로 확인되지 않아 선택할 수 없어요.";
      copy.append(title, note);
      label.append(input, copy);
      container.append(label);
    });
    byId("area-results-wrap").hidden = state.areaCandidates.length === 0;
  }

  async function previewArea() {
    const neighborhood = selectedNeighborhood();
    const neighborhoodCode = neighborhood?.code;
    const districtCode = byId("district-select").value;
    if (!neighborhood || state.areaSearching || state.submitting || selectedKind() !== "area") return;
    locationChanged();
    const sequence = state.areaSequence;
    const controller = new AbortController();
    state.areaController = controller;
    setAreaBusy(true);
    byId("area-search-message").textContent = "동네의 참고 위치를 찾고 있어요.";
    try {
      const result = await api("/api/onboarding/locations/area-preview", {
        method: "POST", signal: controller.signal,
        body: JSON.stringify({ kind: "area", neighborhood_code: neighborhoodCode, district_code: districtCode }),
      });
      if (sequence !== state.areaSequence || selectedKind() !== "area" || byId("place-text").value !== neighborhoodCode || byId("district-select").value !== districtCode) return;
      state.areaSearchId = result.search_id || null;
      state.areaCandidates = Array.isArray(result.candidates) ? result.candidates : [];
      byId("area-search-message").textContent = result.message || (state.areaCandidates.length ? "지도에서 확인할 참고 지점을 선택해 주세요." : "참고 위치를 찾지 못했어요. 선택한 행정동으로 저장하고 상권 후보를 확인할 수 있어요.");
      renderAreaCandidates();
    } catch (error) {
      if (sequence !== state.areaSequence || error.name === "AbortError") return;
      byId("area-search-message").textContent = error.message || "위치를 검색하지 못했어요. 선택한 행정동으로 저장하고 상권 후보를 확인할 수 있어요.";
    } finally {
      if (sequence === state.areaSequence) { state.areaController = null; setAreaBusy(false); }
    }
  }

  async function verifyAddress({ autoSelect = false, buildingName = "" } = {}) {
    const query = byId("address-query").value.trim();
    if (state.addressComposing || state.searching || state.submitting || selectedKind() !== "address") return;
    if (!query) {
      byId("address-search-message").textContent = "도로명과 건물 번호 또는 지번주소를 입력해 주세요.";
      return;
    }
    locationChanged();
    const sequence = state.searchSequence;
    const controller = new AbortController();
    state.searchController = controller;
    setSearchBusy(true);
    byId("address-search-message").textContent = "주소를 확인하고 있어요.";
    try {
      const result = await api("/api/onboarding/locations/search", {
        method: "POST", body: JSON.stringify({ query }), signal: controller.signal,
      });
      if (sequence !== state.searchSequence || selectedKind() !== "address" || byId("address-query").value.trim() !== query) return;
      state.searchId = result.search_id || null;
      state.candidates = Array.isArray(result.candidates) ? result.candidates.slice(0, 10) : [];
      byId("address-search-message").textContent = result.message || (state.candidates.length ? "확인된 주소에서 가게 위치를 선택해 주세요." : "선택한 주소의 지도 위치를 확인하지 못했어요. 주소 찾기에서 다시 선택해 주세요.");
      if (autoSelect && state.searchId && state.candidates.length === 1 && state.candidates[0].in_seoul === true) {
        if (buildingName && !state.candidates[0].building_name) state.candidates[0].building_name = buildingName;
        selectAddressCandidate(state.candidates[0]);
      } else renderCandidates();
    } catch (error) {
      if (sequence !== state.searchSequence || error.name === "AbortError") return;
      byId("address-search-message").textContent = error.message || "주소를 검색하지 못했어요. 잠시 후 다시 시도해 주세요.";
    } finally {
      if (sequence === state.searchSequence) {
        state.searchController = null;
        setSearchBusy(false);
      }
    }
  }

  function renderIndustries(selectedCode = byId("industry-select").value) {
    const select = byId("industry-select");
    select.replaceChildren(new Option("업종을 선택해 주세요", ""));
    const selected = state.options.industries.find((item) => item.code === selectedCode);
    industryGroups.forEach(({ prefix, label }) => {
      const items = state.options.industries.filter((item) => item.code.startsWith(prefix));
      if (!items.length) return;
      const group = document.createElement("optgroup");
      group.label = `${label} (${items.length})`;
      items.forEach((item) => group.append(new Option(item.name, item.code)));
      select.append(group);
    });
    select.value = selected?.code || "";
    byId("industry-count").textContent = `${state.options.industries.length}개 분류 · 실제 운영하거나 검토하는 업종을 선택해 주세요.`;
  }

  function renderOptions() {
    const districtSelect = byId("district-select");
    districtSelect.replaceChildren(new Option("자치구를 선택해 주세요", ""));
    state.options.districts.forEach((item) => districtSelect.append(new Option(item.name, item.code)));
    renderStationLines();
    renderIndustries("");
    const cards = byId("business-statuses");
    cards.replaceChildren();
    state.options.business_statuses.forEach((item) => {
      const label = document.createElement("label");
      label.className = "status-card";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "business-status";
      input.value = item.code;
      input.addEventListener("change", () => { fieldError("status-error", ""); updateSummary(); });
      const content = document.createElement("span");
      content.className = "status-card-content";
      const circle = document.createElement("span");
      circle.className = "status-radio";
      circle.setAttribute("aria-hidden", "true");
      const title = document.createElement("span");
      title.className = "status-title";
      title.textContent = item.label;
      const description = document.createElement("span");
      description.className = "status-description";
      description.textContent = descriptions[item.code] || "";
      content.append(circle, title, description);
      label.append(input, content);
      cards.append(label);
    });
  }

  function selectedAnalysisCandidate() {
    return analysisState.candidates.find((candidate) => candidate.area_code === analysisState.selectedCode) || null;
  }

  function analysisPeriods(candidate = selectedAnalysisCandidate()) {
    const periods = candidate?.availability?.periods;
    return (Array.isArray(periods) ? periods : []).filter((period) => /^\d{4}[1-4]$/.test(period.code))
      .slice().sort((left, right) => right.code.localeCompare(left.code));
  }

  function selectedAnalysisPeriod() {
    return analysisPeriods().find((period) => period.code === analysisState.period) || null;
  }

  function periodLabel(code) {
    return /^\d{4}[1-4]$/.test(code || "") ? `${code.slice(0, 4)}년 ${code[4]}분기` : "분기 확인 필요";
  }

  function comparisonPeriod(code, previousYear = false) {
    if (!/^\d{4}[1-4]$/.test(code || "")) return null;
    const year = Number(code.slice(0, 4)), quarter = Number(code[4]);
    return previousYear ? `${year - 1}${quarter}` : quarter === 1 ? `${year - 1}4` : `${year}${quarter - 1}`;
  }

  function analysisRelation(candidate) {
    if (candidate.relation === "inside") return "기준 위치가 경계 안에 있어요";
    if (candidate.relation === "boundary") return "기준 위치가 경계에 있어요";
    if (candidate.relation === "neighborhood") return "선택한 행정동의 공식 상권";
    if (candidate.relation === "nearby" && Number.isFinite(candidate.distance_m)) return `상권 경계까지 약 ${Math.round(candidate.distance_m).toLocaleString("ko-KR")}m`;
    return "위치 관계를 확인해 주세요";
  }

  function leaveAnalysis() {
    analysisState.active = false;
    analysisState.sequence += 1;
    analysisState.controller?.abort();
    analysisState.controller = null;
    analysisState.loading = false;
    byId("analysis-panel").hidden = true;
    mapState.selectionVersion += 1;
    mapState.selectionKey = null;
    detachMapPolygons();
  }

  function renderSavedAnalysisNote() {
    const saved = analysisState.saved;
    const valid = saved && !["stale", "unavailable"].includes(saved.status) && saved.analysis_setup_complete === true;
    byId("open-analysis").textContent = valid ? "분석 상권 확인·수정" : saved ? "분석 상권 다시 설정" : "분석 상권 설정";
    byId("view-sales-overview").hidden = !valid;
    byId("saved-analysis-note").textContent = valid
      ? `분석 조건 저장 완료 · ${saved.area_name} · ${saved.period_label || periodLabel(saved.period)}. 저장한 조건의 분석 결과를 확인할 수 있어요.`
      : saved ? saved.message || "저장된 분석 조건의 자료가 변경됐어요. 상권과 분기를 다시 확인해 주세요."
        : "공식 상권 경계와 자료 제공 범위를 확인한 뒤 분석 상권을 저장할 수 있어요.";
  }

  function renderAnalysisContext() {
    byId("analysis-profile-summary").textContent = [state.profile?.location.label, state.profile?.industry.name, state.profile?.business_status_label].filter(Boolean).join(" · ");
    updateSummary();
  }

  async function openAnalysis() {
    if (!state.profile || state.submitting || analysisState.saving) return;
    leaveSales();
    leaveStores();
    leavePopulation();
    leaveComparison();
    leaveChanges();
    clearAppError();
    analysisState.active = true;
    state.editing = false;
    byId("profile-form").hidden = true;
    byId("saved-overview").hidden = true;
    byId("analysis-panel").hidden = false;
    byId("page-heading").textContent = "분석할 상권을 정해볼까요?";
    byId("page-description").textContent = "공식 경계와 자료 제공 범위를 확인하고 분석 조건을 저장해 주세요.";
    setStep(true, true);
    renderAnalysisContext();
    await loadAnalysisOptions();
  }

  async function loadAnalysisOptions() {
    if (!analysisState.active || analysisState.saving) return;
    analysisState.controller?.abort();
    const sequence = ++analysisState.sequence;
    const controller = new AbortController();
    analysisState.controller = controller;
    analysisState.loading = true;
    analysisState.conflict = false;
    analysisState.candidates = [];
    analysisState.selectedCode = "";
    analysisState.period = "";
    analysisState.catalogVersion = null;
    byId("analysis-candidates").replaceChildren();
    byId("analysis-candidates-wrap").hidden = true;
    byId("analysis-data-section").hidden = true;
    byId("analysis-retry").hidden = true;
    byId("analysis-candidate-count").textContent = "";
    byId("analysis-load-message").textContent = "현재 가게 정보로 공식 상권과 자료 제공 범위를 확인하고 있어요.";
    updateAnalysisSaveButton();
    updateLocationMap(state.profile.location);
    try {
      const result = await api("/api/onboarding/analysis-options", { signal: controller.signal });
      if (!analysisState.active || sequence !== analysisState.sequence) return;
      if (!result.profile) throw new Error("가게 정보를 먼저 저장해 주세요.");
      state.profile = result.profile;
      state.revision = result.revision;
      analysisState.saved = result.analysis_selection || null;
      analysisState.catalogVersion = result.catalog_version;
      analysisState.scope = result.scope || null;
      analysisState.candidates = Array.isArray(result.candidates) ? result.candidates : [];
      byId("analysis-load-message").textContent = result.message || (analysisState.candidates.length ? "상권을 선택해 자료 제공 범위를 확인해 주세요." : "이 위치에서 상권 후보를 찾지 못했어요. 가게 정보에서 위치를 다시 확인해 주세요.");
      byId("analysis-candidate-count").textContent = result.truncated
        ? `전체 ${result.candidate_count}개 중 ${analysisState.candidates.length}개 표시`
        : `${analysisState.candidates.length}개 후보`;
      const saved = analysisState.saved;
      if (saved && analysisState.candidates.some((candidate) => candidate.area_code === saved.area_code)) {
        analysisState.selectedCode = saved.area_code;
        analysisState.period = saved.period;
      }
      renderAnalysisContext();
      renderAnalysisCandidates();
      renderAnalysisDetails();
      updateLocationMap(state.profile.location);
    } catch (error) {
      if (!analysisState.active || sequence !== analysisState.sequence || error.name === "AbortError") return;
      byId("analysis-load-message").textContent = error.message || "상권 목록을 불러오지 못했어요. 다시 확인해 주세요.";
      byId("analysis-retry").hidden = false;
    } finally {
      if (sequence === analysisState.sequence) {
        analysisState.loading = false;
        analysisState.controller = null;
        updateAnalysisSaveButton();
      }
    }
  }

  function renderAnalysisCandidates() {
    const container = byId("analysis-candidates");
    container.replaceChildren();
    analysisState.candidates.forEach((candidate, index) => {
      const label = document.createElement("label");
      label.className = "analysis-candidate";
      const radio = document.createElement("input");
      radio.type = "radio"; radio.name = "analysis-candidate"; radio.value = candidate.area_code;
      radio.id = `analysis-candidate-${index}`;
      radio.checked = candidate.area_code === analysisState.selectedCode;
      radio.addEventListener("change", () => { if (radio.checked) selectAnalysisCandidate(candidate.area_code); });
      radio.addEventListener("keydown", (event) => {
        if (event.key === "Enter") { event.preventDefault(); selectAnalysisCandidate(candidate.area_code); }
      });
      const copy = document.createElement("span"); copy.className = "analysis-candidate-copy";
      const name = document.createElement("span"); name.className = "analysis-candidate-name"; name.textContent = candidate.name;
      const meta = document.createElement("span"); meta.className = "analysis-candidate-meta";
      meta.textContent = [candidate.type, analysisRelation(candidate)].filter(Boolean).join(" · ");
      copy.append(name, meta);
      if (candidate.selection_blocked_reason) {
        const warning = document.createElement("span"); warning.className = "analysis-candidate-meta"; warning.textContent = candidate.selection_blocked_reason; copy.append(warning);
      }
      label.append(radio, copy); container.append(label);
    });
    byId("analysis-candidates-wrap").hidden = analysisState.candidates.length === 0;
  }

  function selectAnalysisCandidate(code) {
    if (!analysisState.active || analysisState.loading || analysisState.saving || analysisState.conflict) return;
    const candidate = analysisState.candidates.find((item) => item.area_code === code);
    if (!candidate) return;
    analysisState.selectedCode = code;
    const periods = analysisPeriods(candidate);
    analysisState.period = periods.find((period) => period.available === true)?.code || periods[0]?.code || "";
    renderAnalysisCandidates();
    renderAnalysisDetails();
    updateLocationMap(state.profile.location);
  }

  function renderAnalysisDetails() {
    const candidate = selectedAnalysisCandidate();
    byId("analysis-data-section").hidden = !candidate;
    if (!candidate) { updateAnalysisSaveButton(); return; }
    byId("analysis-selected-name").textContent = candidate.name;
    byId("analysis-selected-meta").textContent = [candidate.type, candidate.district_name, candidate.neighborhood_name].filter(Boolean).join(" · ");
    const periods = analysisPeriods(candidate);
    const select = byId("analysis-quarter");
    select.replaceChildren(new Option("분기를 선택해 주세요", ""));
    periods.forEach((period) => {
      const unavailableLabel = candidate.selection_blocked_reason ? "연결 확인 필요" : "확인된 자료 없음";
      const option = new Option(`${period.label || periodLabel(period.code)}${period.available ? "" : ` · ${unavailableLabel}`}`, period.code);
      option.disabled = period.available !== true;
      select.append(option);
    });
    select.value = periods.some((period) => period.code === analysisState.period) ? analysisState.period : "";
    select.disabled = !periods.some((period) => period.available === true) || analysisState.saving;
    const period = selectedAnalysisPeriod();
    const stale = ["stale", "unavailable"].includes(analysisState.saved?.status);
    byId("analysis-data-message").textContent = candidate.selection_blocked_reason
      || (period?.population_only ? "선택 업종의 매출·점포 자료는 없어요. 이 분기는 지역 전체 유동인구 자료만 확인할 수 있어요."
        : !period?.available ? "이 상권·업종·분기에서 확인된 자료가 없어 저장할 수 없어요. 다른 상권이나 분기를 확인해 주세요."
          : stale ? analysisState.saved.message || "저장된 분석 조건이 오래됐어요. 현재 자료 제공 범위를 확인한 뒤 다시 저장해 주세요."
            : "선택한 분기에 실제로 확인된 자료의 제공 범위예요.");
    renderAnalysisCoverage(candidate, period);
    renderAnalysisSources();
    updateAnalysisSaveButton();
  }

  function renderAnalysisCoverage(candidate, period) {
    const container = byId("analysis-coverage");
    container.replaceChildren();
    const periods = analysisPeriods(candidate);
    const titles = { sales: "추정 매출", stores: "점포", floating_population: "유동인구" };
    const statuses = { available: "자료 있음", no_observation: "관측 자료 없음", not_collected: "자료 미확보", unavailable: "확인 불가" };
    for (const [key, title] of Object.entries(titles)) {
      const metric = period?.metrics?.[key];
      const card = document.createElement("div"); card.className = "coverage-card";
      const top = document.createElement("div"); top.className = "coverage-card-top";
      const heading = document.createElement("h4"); heading.textContent = title;
      const badge = document.createElement("span"); badge.className = `coverage-badge${metric?.status === "available" ? "" : " unavailable"}`;
      badge.textContent = statuses[metric?.status] || "확인 필요"; top.append(heading, badge);
      const availablePeriods = periods.filter((entry) => entry.metrics?.[key]?.status === "available");
      const available = availablePeriods.map((entry) => entry.label || periodLabel(entry.code));
      const range = document.createElement("p"); range.className = "coverage-period";
      const extended = available.length > 3;
      const continuous = availablePeriods.every((entry, index) => index === 0 || comparisonPeriod(availablePeriods[index - 1].code) === entry.code);
      range.textContent = extended ? `제공 분기: ${available.at(-1)} ~ ${available[0]}${continuous ? " ·" : " 중"} ${available.length}개 분기`
        : available.length ? `제공 분기: ${available.join(" · ")}` : "확인된 제공 분기 없음";
      const comparisons = document.createElement("div"); comparisons.className = "coverage-comparisons";
      for (const [label, target] of [["전분기", comparisonPeriod(period?.code)], ["전년 동기", comparisonPeriod(period?.code, true)]]) {
        const previous = periods.find((entry) => entry.code === target)?.metrics?.[key];
        const note = document.createElement("span");
        note.textContent = `${label}: ${metric?.status !== "available" ? "현재 분기 자료 없음" : previous?.status === "available" ? "비교 기간 자료 있음" : "비교 분기 자료 없음"}`;
        comparisons.append(note);
      }
      const note = document.createElement("p"); note.className = "coverage-note";
      note.textContent = metric?.zero_observation ? "관측값 0을 포함해 유효한 자료가 확인됐어요."
        : metric?.reason || (key === "floating_population" ? "업종과 무관한 상권 전체 자료예요." : "선택 업종의 자료예요.");
      card.append(top, range);
      if (extended) {
        const details = document.createElement("details"); details.className = "coverage-period-details";
        const summary = document.createElement("summary"); summary.textContent = `제공 분기 목록 (${available.length}개)`;
        const list = document.createElement("p"); list.textContent = available.join(" · ");
        details.append(summary, list); card.append(details);
      }
      card.append(comparisons, note);
      if (typeof metric?.source_url === "string" && /^https?:\/\//.test(metric.source_url)) {
        const link = document.createElement("a"); link.href = metric.source_url; link.target = "_blank"; link.rel = "noopener noreferrer";
        link.className = "coverage-source"; link.textContent = "자료 출처"; card.append(link);
      }
      container.append(card);
    }
    byId("analysis-comparison-note").textContent = "‘비교 기간 자료 있음’은 두 분기 자료가 있다는 뜻이며 증감 분석 결과는 아니에요. 유동인구는 상권 전체 자료예요.";
  }

  function renderAnalysisSources() {
    const container = byId("analysis-sources"); container.replaceChildren();
    const scope = analysisState.scope || {};
    const usesDistance = analysisState.candidates.some((candidate) => ["inside", "boundary", "nearby"].includes(candidate.relation));
    for (const value of [scope.boundary_notice, usesDistance && scope.search_radius_notice ? `${scope.search_radius_m ? `${scope.search_radius_m.toLocaleString("ko-KR")}m는 ` : ""}${scope.search_radius_notice}` : null]) {
      if (!value) continue;
      const note = document.createElement("span"); note.textContent = value; container.append(note);
    }
    if (typeof scope.boundary_source_url === "string" && /^https?:\/\//.test(scope.boundary_source_url)) {
      const link = document.createElement("a"); link.href = scope.boundary_source_url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = "서울시 공식 상권 경계 출처"; container.append(link);
    }
  }

  function updateAnalysisSaveButton() {
    const candidate = selectedAnalysisCandidate(), period = selectedAnalysisPeriod(), saved = analysisState.saved;
    const unchanged = !["stale", "unavailable"].includes(saved?.status) && saved?.analysis_setup_complete === true
      && saved.area_code === analysisState.selectedCode && saved.period === analysisState.period
      && saved.catalog_version === analysisState.catalogVersion;
    const allowed = !!candidate && period?.available === true && !candidate.selection_blocked_reason && !!analysisState.catalogVersion;
    byId("save-analysis").disabled = analysisState.loading || analysisState.saving || analysisState.conflict || !allowed || unchanged;
    byId("save-analysis").textContent = analysisState.saving ? "분석 조건 저장 중…" : unchanged ? "저장한 분석 조건" : "이 상권으로 저장하기";
    byId("view-sales-analysis").hidden = !unchanged || analysisState.loading || analysisState.saving || analysisState.conflict;
    byId("analysis-back").disabled = analysisState.saving;
    byId("analysis-quarter").disabled = analysisState.saving || !analysisPeriods().some((entry) => entry.available === true);
    byId("analysis-panel").inert = analysisState.saving;
    byId("analysis-panel").setAttribute("aria-busy", String(analysisState.loading || analysisState.saving));
    byId("analysis-save-message").textContent = analysisState.conflict ? "가게 정보나 자료가 변경됐어요. 다시 확인한 뒤 저장해 주세요."
      : unchanged ? "분석 조건 저장 완료. 저장한 조건의 분석 결과를 확인해 보세요."
        : period?.population_only ? "지역 유동인구만 있는 조건이에요. 이 범위를 확인한 뒤 저장해 주세요."
          : "상권과 자료 제공 범위를 확인한 뒤 저장해 주세요.";
  }

  async function saveAnalysisSelection() {
    updateAnalysisSaveButton();
    if (byId("save-analysis").disabled || !analysisState.active) return;
    const request = { area_code: analysisState.selectedCode, period: analysisState.period, expected_revision: state.revision, expected_catalog_version: analysisState.catalogVersion };
    const sequence = analysisState.sequence;
    analysisState.saving = true;
    updateAnalysisSaveButton();
    try {
      const result = await api("/api/onboarding/analysis-selection", { method: "POST", body: JSON.stringify(request) });
      if (!analysisState.active || sequence !== analysisState.sequence) return;
      state.profile = result.profile;
      state.revision = result.revision;
      analysisState.saved = result.analysis_selection;
      renderAnalysisContext();
      renderAnalysisDetails();
    } catch (error) {
      if (!analysisState.active || sequence !== analysisState.sequence) return;
      analysisState.conflict = error.status === 409;
      byId("analysis-data-message").textContent = error.message || "분석 조건을 저장하지 못했어요. 다시 시도해 주세요.";
      if (analysisState.conflict) byId("analysis-retry").hidden = false;
    } finally {
      analysisState.saving = false;
      updateAnalysisSaveButton();
    }
  }

  function confirmedAnalysisSelection() {
    const saved = analysisState.saved;
    return state.profile && saved?.analysis_setup_complete === true && saved.conditions_confirmed !== false
      && !["stale", "unavailable"].includes(saved.status) && saved.industry_code === state.profile.industry.code ? saved : null;
  }

  function reportConditionKey() {
    const saved = confirmedAnalysisSelection();
    return saved ? JSON.stringify([state.revision, saved.area_code, saved.industry_code, saved.period, saved.catalog_version]) : "";
  }

  function reportContextMatches(result, revision, saved) {
    return result.revision === revision && result.selection?.area_code === saved.area_code
      && result.selection?.industry_code === saved.industry_code && result.selection?.period === saved.period
      && result.selection?.catalog_version === saved.catalog_version;
  }

  function renderReportMenu(feature) {
    byId("analysis-report-menu").hidden = false;
    const confirmed = !!confirmedAnalysisSelection();
    for (const name of ["sales", "stores", "population", "comparison", "changes"]) {
      const button = byId(`report-menu-${name}`);
      button.disabled = !confirmed || name === feature;
      if (name === feature) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
    }
  }

  function showReportLayout(feature) {
    byId("profile-content").hidden = true;
    byId("profile-location-column").hidden = true;
    byId("page-intro").hidden = true;
    byId("workspace").classList.toggle("report-mode", true);
    renderReportMenu(feature);
  }

  function resetReportLayout() {
    byId("profile-content").hidden = false;
    byId("profile-location-column").hidden = false;
    byId("page-intro").hidden = false;
    byId("analysis-report-menu").hidden = true;
    byId("workspace").classList.toggle("report-mode", false);
  }

  function switchReport(feature) {
    const origin = salesState.active ? salesState.origin : storesState.active ? storesState.origin : populationState.active ? populationState.origin : comparisonState.active ? comparisonState.origin : changesState.active ? changesState.origin : "overview";
    if (feature === "sales" && !salesState.active) return openSales(origin);
    if (feature === "stores" && !storesState.active) return openStores(origin);
    if (feature === "population" && !populationState.active) return openPopulation(origin);
    if (feature === "comparison" && !comparisonState.active) return openComparison(origin);
    if (feature === "changes" && !changesState.active) return openChanges(origin);
  }

  function clearSalesResult() {
    byId("sales-result").hidden = true;
    ["sales-summary", "sales-distributions", "sales-scope", "sales-sources", "sales-warnings"].forEach((id) => byId(id).replaceChildren());
    byId("sales-total").textContent = "";
    byId("sales-total-note").textContent = "";
    byId("sales-result-status").textContent = "";
  }

  function leaveSales() {
    salesState.active = false;
    salesState.sequence += 1;
    salesState.controller?.abort();
    salesState.controller = null;
    salesState.loading = false;
    salesState.conflict = false;
    byId("sales-panel").hidden = true;
    resetReportLayout();
    clearSalesResult();
  }

  async function openSales(origin = "overview") {
    const saved = confirmedAnalysisSelection();
    if (!saved || state.submitting || analysisState.saving) return;
    if (origin === "analysis" && (analysisState.loading || analysisState.conflict
      || analysisState.selectedCode !== saved.area_code || analysisState.period !== saved.period
      || analysisState.catalogVersion !== saved.catalog_version)) return;
    leaveStores();
    leavePopulation();
    leaveComparison();
    leaveChanges();
    leaveAnalysis();
    salesState.active = true;
    salesState.origin = origin;
    byId("sales-panel").hidden = false;
    showReportLayout("sales");
    byId("sales-back").textContent = origin === "analysis" ? "상권 설정으로" : "가게 정보로";
    byId("sales-condition").textContent = [saved.area_name, state.profile.industry.name, saved.period_label || periodLabel(saved.period)].join(" · ");
    setStep(true, true, true);
    await loadSales();
  }

  function salesLoadError(message, conflict = false) {
    clearSalesResult();
    salesState.conflict = conflict;
    byId("sales-load-state").hidden = false;
    byId("sales-load-message").textContent = message;
    byId("sales-retry").hidden = conflict;
    byId("sales-reconfigure").textContent = conflict ? "분석 조건 다시 확인" : "분석 조건 확인";
    if (conflict && analysisState.saved) {
      analysisState.saved = { ...analysisState.saved, status: "stale", analysis_setup_complete: false, conditions_confirmed: false, message: "가게 정보나 분석 조건이 변경됐어요. 분석 조건을 다시 확인해 주세요." };
    }
    renderReportMenu("sales");
  }

  async function loadSales() {
    if (!salesState.active || salesState.loading || salesState.conflict) return;
    const saved = confirmedAnalysisSelection();
    if (!saved) { salesLoadError("분석 조건을 먼저 확인하고 저장해 주세요.", true); return; }
    salesState.controller?.abort();
    const sequence = ++salesState.sequence;
    const controller = new AbortController();
    const revision = state.revision;
    const conditionKey = reportConditionKey();
    salesState.controller = controller;
    salesState.loading = true;
    clearSalesResult();
    byId("sales-panel").setAttribute("aria-busy", "true");
    byId("sales-load-state").hidden = false;
    byId("sales-load-message").textContent = "저장한 조건의 매출 자료를 확인하고 있어요.";
    byId("sales-retry").hidden = true;
    byId("sales-reconfigure").textContent = "분석 조건 확인";
    try {
      const result = await api(`/api/onboarding/sales?expected_revision=${encodeURIComponent(revision)}`, { signal: controller.signal });
      if (!salesState.active || sequence !== salesState.sequence || conditionKey !== reportConditionKey()) return;
      if (!reportContextMatches(result, revision, saved)) {
        salesLoadError("분석 조건이 변경됐어요. 조건을 다시 확인한 뒤 매출 분석을 열어 주세요.", true);
        return;
      }
      if (!["available", "no_data", "invalid"].includes(result.status)) throw new Error("매출 자료 응답을 확인하지 못했어요. 다시 불러와 주세요.");
      renderSalesResult(result);
    } catch (error) {
      if (!salesState.active || sequence !== salesState.sequence || conditionKey !== reportConditionKey() || error.name === "AbortError") return;
      salesLoadError(error.message || "매출 자료를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.", error.status === 409);
    } finally {
      if (sequence === salesState.sequence) {
        salesState.loading = false;
        salesState.controller = null;
        byId("sales-panel").setAttribute("aria-busy", "false");
      }
    }
  }

  function integerUnitText(record, unit) {
    const raw = typeof record?.value_text === "string" ? record.value_text
      : Number.isSafeInteger(record?.value) ? String(record.value) : "";
    if (!/^-?\d+$/.test(raw)) return null;
    try { return `${BigInt(raw).toLocaleString("ko-KR")}${unit}`; } catch { return null; }
  }

  function wonText(record) { return integerUnitText(record, "원"); }

  function percentText(value) {
    return typeof value === "number" && Number.isFinite(value) ? `${value.toLocaleString("ko-KR", { maximumFractionDigits: 6 })}%` : "산출 불가";
  }

  function appendSalesText(parent, tag, text, className = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = text;
    parent.append(node);
    return node;
  }

  function renderSalesResult(result) {
    const selection = result.selection;
    byId("sales-condition").textContent = [selection.area_name, selection.industry_name, selection.period_label || periodLabel(selection.period)].filter(Boolean).join(" · ");
    byId("sales-result-status").textContent = result.status === "no_data" ? "자료 없음" : result.status === "invalid" ? "자료 확인 필요" : "공식 추정 자료";
    byId("sales-total").textContent = result.total?.status === "available" ? wonText(result.total) || "금액 확인 필요"
      : result.total?.status === "invalid" ? "원천 금액 확인 필요" : "확인된 자료 없음";
    byId("sales-total-note").textContent = [typeof result.total?.message === "string" ? result.total.message : "", "선택한 공식 상권·업종 전체의 분기 추정 매출이에요. 개별 가게의 매출이 아니에요."].filter(Boolean).join(" ");
    byId("sales-summary").replaceChildren();
    const summaries = Array.isArray(result.summary) ? result.summary.filter((value) => typeof value === "string") : [];
    for (const line of summaries.length ? summaries : ["이 조건에서 확인된 매출 요약이 없어요. 자료 제공 범위와 누락 항목을 확인해 주세요."]) appendSalesText(byId("sales-summary"), "li", line);
    const distributions = byId("sales-distributions"); distributions.replaceChildren();
    for (const [key, title] of [["weekday", "요일별 매출"], ["time", "시간대별 매출"], ["age", "연령별 매출"]]) renderSalesDistribution(distributions, key, result.distributions?.[key], title);
    const scope = byId("sales-scope"); scope.replaceChildren();
    appendSalesText(scope, "p", `${selection.area_name} · ${selection.industry_name} · ${selection.period_label || periodLabel(selection.period)} · 금액 단위: 원`);
    if (selection.boundary?.publication_date) appendSalesText(scope, "p", `${selection.boundary.publication_date} 공개 상권 경계를 기준으로 연결한 자료예요. 현재 분기 경계와의 동일성은 확인되지 않았어요.`);
    const sources = byId("sales-sources"); sources.replaceChildren();
    if (typeof result.source?.url === "string" && /^https?:\/\//.test(result.source.url)) {
      const link = appendSalesText(sources, "a", result.source.title || "서울시 공식 매출 자료 출처");
      link.href = result.source.url; link.target = "_blank"; link.rel = "noopener noreferrer";
    }
    const warnings = byId("sales-warnings"); warnings.replaceChildren();
    for (const line of Array.isArray(result.warnings) ? result.warnings : []) if (typeof line === "string") appendSalesText(warnings, "li", line);
    byId("sales-warnings-card").hidden = warnings.children.length === 0;
    byId("sales-load-state").hidden = true;
    byId("sales-result").hidden = false;
  }

  function renderSalesDistribution(container, key, distribution, fallbackTitle) {
    const group = distribution || {};
    const card = document.createElement("section"); card.className = "sales-distribution";
    const heading = document.createElement("div"); heading.className = "sales-distribution-heading";
    appendSalesText(heading, "h3", group.label || fallbackTitle);
    const statusLabels = { complete: "자료 확인", partial: "일부 자료 없음", inconsistent: "합계 확인 필요", no_data: "자료 없음", invalid: "자료 확인 필요" };
    appendSalesText(heading, "span", statusLabels[group.status] || "자료 확인 필요", "sales-distribution-status");
    card.append(heading);
    const denominator = wonText(group.denominator) || "확인된 금액 없음";
    if (key === "age") {
      appendSalesText(card, "p", `연령이 확인된 매출 중 비중 · 분류 매출 합계: ${denominator}`, "sales-denominator");
      appendSalesText(card, "p", `총매출 대비 연령 분류율: ${percentText(group.classified_share_of_total_percent)} · 분류 합계 − 총매출: ${wonText({ value: group.total_difference }) || "확인 필요"}`, "sales-denominator");
    } else appendSalesText(card, "p", `${group.denominator?.label || "비중의 분모"}: ${denominator}`, "sales-denominator");
    const table = document.createElement("table");
    appendSalesText(table, "caption", "금액은 원 단위로 표시하며, 막대는 제공된 비중을 나타냅니다.");
    const thead = document.createElement("thead"), header = document.createElement("tr");
    for (const label of ["항목", "추정 매출", "비중"]) { const th = appendSalesText(header, "th", label); th.setAttribute("scope", "col"); }
    thead.append(header); table.append(thead);
    const tbody = document.createElement("tbody");
    const items = Array.isArray(group.items) ? group.items : [];
    const highest = group.status === "complete" && group.ranking?.status === "available" && Array.isArray(group.ranking.highest) ? group.ranking.highest : [];
    for (const item of items) {
      const row = document.createElement("tr");
      const isHighest = item.status === "available" && highest.includes(item.label);
      if (isHighest) row.className = "sales-row-highest";
      const label = appendSalesText(row, "th", item.label || "항목 확인 필요"); label.setAttribute("scope", "row");
      if (isHighest) appendSalesText(label, "span", highest.length > 1 ? "공동 최고" : "최고", "sales-highest-tag");
      const amount = document.createElement("td");
      appendSalesText(amount, "span", item.status === "available" ? wonText(item) || "금액 확인 필요" : item.status === "invalid" ? "확인 불가" : "자료 없음", "sales-row-amount");
      const share = group.status === "complete" && typeof item.share_percent === "number" && Number.isFinite(item.share_percent) && item.share_percent >= 0 && item.share_percent <= 100 ? item.share_percent : null;
      if (share !== null) {
        const track = document.createElement("div"); track.className = "sales-bar-track"; track.setAttribute("aria-hidden", "true");
        const bar = document.createElement("div"); bar.className = "sales-bar"; bar.style.width = `${share}%`; track.append(bar); amount.append(track);
      }
      row.append(amount);
      appendSalesText(row, "td", share !== null ? percentText(share) : "—", "sales-row-share");
      tbody.append(row);
    }
    table.append(tbody); card.append(table);
    if (!items.length) appendSalesText(card, "p", "확인된 분포 항목이 없어요.", "sales-distribution-message");
    const notes = Array.isArray(group.warnings) ? group.warnings.filter((value) => typeof value === "string") : [];
    if (key === "time" && !notes.some((note) => note.includes("시간당"))) notes.push("시간대별 구간 길이가 달라요. 표시 금액은 구간 합계이며 시간당 평균이 아니에요.");
    if (key === "age" && !notes.some((note) => /연령.*(분류|비중)/.test(note))) notes.push("연령이 분류된 매출의 분포이며 전체 고객층을 뜻하지 않아요. 총매출과의 차이를 특정 고객 유형으로 단정할 수 없어요.");
    for (const note of notes) appendSalesText(card, "p", note, "sales-distribution-message");
    container.append(card);
  }

  function clearStoresResult() {
    byId("stores-result").hidden = true;
    ["stores-total", "stores-total-note", "stores-result-status", "stores-general", "stores-franchise", "stores-opened", "stores-closed", "stores-franchise-share", "stores-denominator", "stores-composition-status", "stores-composition-message"].forEach((id) => { byId(id).textContent = ""; });
    ["stores-summary", "stores-scope", "stores-sources", "stores-warnings"].forEach((id) => byId(id).replaceChildren());
    byId("stores-share-track").hidden = true;
    byId("stores-share-bar").style.width = "0%";
  }

  function leaveStores() {
    storesState.active = false;
    storesState.sequence += 1;
    storesState.controller?.abort();
    storesState.controller = null;
    storesState.loading = false;
    storesState.conflict = false;
    byId("stores-panel").hidden = true;
    resetReportLayout();
    clearStoresResult();
  }

  async function openStores(origin = "overview") {
    const saved = confirmedAnalysisSelection();
    if (!saved || state.submitting || analysisState.saving) return;
    if (origin === "analysis" && (analysisState.loading || analysisState.conflict
      || analysisState.selectedCode !== saved.area_code || analysisState.period !== saved.period
      || analysisState.catalogVersion !== saved.catalog_version)) return;
    leaveSales();
    leavePopulation();
    leaveComparison();
    leaveChanges();
    leaveAnalysis();
    storesState.active = true;
    storesState.origin = origin;
    byId("stores-panel").hidden = false;
    showReportLayout("stores");
    byId("stores-back").textContent = origin === "analysis" ? "상권 설정으로" : "가게 정보로";
    byId("stores-condition").textContent = [saved.area_name, state.profile.industry.name, saved.period_label || periodLabel(saved.period)].join(" · ");
    setStep(true, true, true);
    await loadStores();
  }

  function storesLoadError(message, conflict = false) {
    clearStoresResult();
    storesState.conflict = conflict;
    byId("stores-load-state").hidden = false;
    byId("stores-load-message").textContent = message;
    byId("stores-retry").hidden = conflict;
    byId("stores-reconfigure").textContent = conflict ? "분석 조건 다시 확인" : "분석 조건 확인";
    if (conflict && analysisState.saved) analysisState.saved = { ...analysisState.saved, status: "stale", analysis_setup_complete: false, conditions_confirmed: false, message: "가게 정보나 분석 조건이 변경됐어요. 분석 조건을 다시 확인해 주세요." };
    renderReportMenu("stores");
  }

  async function loadStores() {
    if (!storesState.active || storesState.loading || storesState.conflict) return;
    const saved = confirmedAnalysisSelection();
    if (!saved) { storesLoadError("분석 조건을 먼저 확인하고 저장해 주세요.", true); return; }
    storesState.controller?.abort();
    const sequence = ++storesState.sequence;
    const controller = new AbortController();
    const revision = state.revision;
    const conditionKey = reportConditionKey();
    storesState.controller = controller;
    storesState.loading = true;
    clearStoresResult();
    byId("stores-panel").setAttribute("aria-busy", "true");
    byId("stores-load-state").hidden = false;
    byId("stores-load-message").textContent = "저장한 조건의 점포 자료를 확인하고 있어요.";
    byId("stores-retry").hidden = true;
    byId("stores-reconfigure").textContent = "분석 조건 확인";
    try {
      const result = await api(`/api/onboarding/stores?expected_revision=${encodeURIComponent(revision)}`, { signal: controller.signal });
      if (!storesState.active || sequence !== storesState.sequence || conditionKey !== reportConditionKey()) return;
      if (!reportContextMatches(result, revision, saved)) {
        storesLoadError("분석 조건이 변경됐어요. 조건을 다시 확인한 뒤 점포 분석을 열어 주세요.", true);
        return;
      }
      if (!["available", "partial", "no_observation", "not_collected", "invalid"].includes(result.status)) throw new Error("점포 자료 응답을 확인하지 못했어요. 다시 불러와 주세요.");
      renderStoresResult(result);
    } catch (error) {
      if (!storesState.active || sequence !== storesState.sequence || conditionKey !== reportConditionKey() || error.name === "AbortError") return;
      storesLoadError(error.message || "점포 자료를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.", error.status === 409);
    } finally {
      if (sequence === storesState.sequence) {
        storesState.loading = false;
        storesState.controller = null;
        byId("stores-panel").setAttribute("aria-busy", "false");
      }
    }
  }

  function storesCountText(record) {
    if (record?.status === "available") return integerUnitText(record, "개") || "개수 확인 필요";
    return { missing: "항목 확인 필요", invalid: "유효성 확인 필요", no_observation: "관측 행 없음", not_collected: "자료 미확보" }[record?.status] || "자료 확인 필요";
  }

  function renderStoresResult(result) {
    const selection = result.selection;
    const counts = result.counts || {};
    const composition = result.composition || {};
    byId("stores-condition").textContent = [selection.area_name, selection.industry_name, selection.period_label || periodLabel(selection.period)].filter(Boolean).join(" · ");
    byId("stores-result-status").textContent = { available: "공식 집계 자료", partial: "일부 항목 없음", no_observation: "관측 행 없음", not_collected: "자료 미확보", invalid: "유효성 확인 필요" }[result.status];
    for (const key of ["total", "general", "franchise", "opened", "closed"]) byId(`stores-${key}`).textContent = storesCountText(counts[key]);
    byId("stores-total-note").textContent = result.status === "not_collected"
      ? "이 상권의 점포 원천 자료를 아직 확보하지 못했어요. 0개라는 뜻이 아니에요."
      : result.status === "no_observation" ? "확보한 자료에서 선택 업종의 관측 행을 찾지 못했어요. 0개로 해석하지 마세요."
        : "선택한 상권·업종·분기의 전체 점포 수예요. 개별 가게의 현재 영업 여부를 뜻하지 않아요.";
    byId("stores-composition-status").textContent = { consistent: "구성 합계 일치", inconsistent: "구성 합계 불일치", incomplete: "일부 항목 없음", no_data: "구성 확인 불가" }[composition.status] || "구성 확인 필요";
    const share = composition.status === "consistent" && typeof composition.franchise_share_percent === "number"
      && Number.isFinite(composition.franchise_share_percent) && composition.franchise_share_percent >= 0 && composition.franchise_share_percent <= 100 ? composition.franchise_share_percent : null;
    byId("stores-franchise-share").textContent = share !== null ? percentText(share) : "산출 불가";
    byId("stores-share-track").hidden = share === null;
    byId("stores-share-bar").style.width = share !== null ? `${share}%` : "0%";
    byId("stores-denominator").textContent = `비중의 분모 · ${composition.denominator?.label || "전체 점포 수"}: ${integerUnitText(composition.denominator, "개") || "확인된 개수 없음"}`;
    const compositionNotes = Array.isArray(composition.warnings) ? composition.warnings.filter((line) => typeof line === "string") : [];
    if (composition.status === "inconsistent") {
      const sum = integerUnitText({ value: composition.sum }, "개"), difference = integerUnitText({ value: composition.difference }, "개");
      if (sum && difference) compositionNotes.push(`구성 합계: ${sum} · 구성 합계 − 전체: ${difference}`);
    }
    byId("stores-composition-message").textContent = compositionNotes.join(" ");
    const summary = byId("stores-summary"); summary.replaceChildren();
    const lines = Array.isArray(result.summary) ? result.summary.filter((line) => typeof line === "string") : [];
    for (const line of lines.length ? lines : ["이 조건에서 확인된 점포 요약이 없어요. 자료 확보 범위와 각 항목의 상태를 확인해 주세요."]) appendSalesText(summary, "li", line);
    const scope = byId("stores-scope"); scope.replaceChildren();
    appendSalesText(scope, "p", `${selection.area_name} · ${selection.industry_name} · ${selection.period_label || periodLabel(selection.period)} · 단위: 개`);
    if (typeof result.source?.coverage_note === "string") appendSalesText(scope, "p", result.source.coverage_note);
    if (selection.boundary?.publication_date) appendSalesText(scope, "p", `${selection.boundary.publication_date} 공개 상권 경계를 기준으로 연결한 자료예요. 현재 분기 경계와의 동일성은 확인되지 않았어요.`);
    const sources = byId("stores-sources"); sources.replaceChildren();
    if (typeof result.source?.url === "string" && /^https?:\/\//.test(result.source.url)) {
      const link = appendSalesText(sources, "a", result.source.title || "서울시 공식 점포 자료 출처"); link.href = result.source.url; link.target = "_blank"; link.rel = "noopener noreferrer";
    }
    const warnings = byId("stores-warnings"); warnings.replaceChildren();
    for (const line of Array.isArray(result.warnings) ? result.warnings : []) if (typeof line === "string") appendSalesText(warnings, "li", line);
    byId("stores-warnings-card").hidden = warnings.children.length === 0;
    byId("stores-load-state").hidden = true;
    byId("stores-result").hidden = false;
  }

  function clearPopulationResult() {
    byId("population-result").hidden = true;
    ["population-total", "population-total-note", "population-result-status"].forEach((id) => { byId(id).textContent = ""; });
    ["population-summary", "population-distributions", "population-scope", "population-sources", "population-warnings"].forEach((id) => byId(id).replaceChildren());
  }

  function leavePopulation() {
    populationState.active = false;
    populationState.sequence += 1;
    populationState.controller?.abort();
    populationState.controller = null;
    populationState.loading = false;
    populationState.conflict = false;
    byId("population-panel").hidden = true;
    resetReportLayout();
    clearPopulationResult();
  }

  function populationCondition(selection) {
    return [selection.area_name, selection.period_label || periodLabel(selection.period), selection.industry_name ? `프로필 업종: ${selection.industry_name}` : "", "유동인구는 업종 구분 없음"].filter(Boolean).join(" · ");
  }

  async function openPopulation(origin = "overview") {
    const saved = confirmedAnalysisSelection();
    if (!saved || state.submitting || analysisState.saving) return;
    if (origin === "analysis" && (analysisState.loading || analysisState.conflict
      || analysisState.selectedCode !== saved.area_code || analysisState.period !== saved.period
      || analysisState.catalogVersion !== saved.catalog_version)) return;
    leaveSales();
    leaveStores();
    leaveComparison();
    leaveChanges();
    leaveAnalysis();
    populationState.active = true;
    populationState.origin = origin;
    byId("population-panel").hidden = false;
    showReportLayout("population");
    byId("population-back").textContent = origin === "analysis" ? "상권 설정으로" : "가게 정보로";
    byId("population-condition").textContent = populationCondition({ ...saved, industry_name: state.profile.industry.name });
    setStep(true, true, true);
    await loadPopulation();
  }

  function populationLoadError(message, conflict = false) {
    clearPopulationResult();
    populationState.conflict = conflict;
    byId("population-load-state").hidden = false;
    byId("population-load-message").textContent = message;
    byId("population-retry").hidden = conflict;
    byId("population-reconfigure").textContent = conflict ? "분석 조건 다시 확인" : "분석 조건 확인";
    if (conflict && analysisState.saved) analysisState.saved = { ...analysisState.saved, status: "stale", analysis_setup_complete: false, conditions_confirmed: false, message: "가게 정보나 분석 조건이 변경됐어요. 분석 조건을 다시 확인해 주세요." };
    renderReportMenu("population");
  }

  async function loadPopulation() {
    if (!populationState.active || populationState.loading || populationState.conflict) return;
    const saved = confirmedAnalysisSelection();
    if (!saved) { populationLoadError("분석 조건을 먼저 확인하고 저장해 주세요.", true); return; }
    populationState.controller?.abort();
    const sequence = ++populationState.sequence;
    const controller = new AbortController();
    const revision = state.revision;
    const conditionKey = reportConditionKey();
    populationState.controller = controller;
    populationState.loading = true;
    clearPopulationResult();
    byId("population-panel").setAttribute("aria-busy", "true");
    byId("population-load-state").hidden = false;
    byId("population-load-message").textContent = "저장한 상권의 유동인구 자료를 확인하고 있어요.";
    byId("population-retry").hidden = true;
    byId("population-reconfigure").textContent = "분석 조건 확인";
    try {
      const result = await api(`/api/onboarding/population?expected_revision=${encodeURIComponent(revision)}`, { signal: controller.signal });
      if (!populationState.active || sequence !== populationState.sequence || conditionKey !== reportConditionKey()) return;
      if (!reportContextMatches(result, revision, saved)) {
        populationLoadError("분석 조건이 변경됐어요. 조건을 다시 확인한 뒤 유동인구를 열어 주세요.", true);
        return;
      }
      if (result.feature !== "population" || result.industry_applied !== false || result.population_scope !== "area_wide"
        || !["available", "no_data", "invalid"].includes(result.status)) throw new Error("유동인구 자료의 범위를 확인하지 못했어요. 다시 불러와 주세요.");
      renderPopulationResult(result);
    } catch (error) {
      if (!populationState.active || sequence !== populationState.sequence || conditionKey !== reportConditionKey() || error.name === "AbortError") return;
      populationLoadError(error.message || "유동인구 자료를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.", error.status === 409);
    } finally {
      if (sequence === populationState.sequence) {
        populationState.loading = false;
        populationState.controller = null;
        byId("population-panel").setAttribute("aria-busy", "false");
      }
    }
  }

  function renderPopulationResult(result) {
    const selection = result.selection;
    byId("population-condition").textContent = populationCondition(selection);
    byId("population-result-status").textContent = { available: "공식 원천 자료", no_data: "자료 없음", invalid: "자료 확인 필요" }[result.status];
    byId("population-total-label").textContent = result.total?.label || "선택 분기 지역 유동인구 원천값";
    byId("population-total").textContent = result.total?.status === "available" ? integerUnitText(result.total, "명") || "인원 확인 필요"
      : result.total?.status === "invalid" ? "원천 값 확인 필요" : "확인된 자료 없음";
    byId("population-total-note").textContent = [typeof result.total?.message === "string" ? result.total.message : "", typeof result.source?.meaning_note === "string" ? result.source.meaning_note : "선택 분기의 지역 유동인구 원천 총지표예요. 일평균이나 고유 방문자 수를 뜻하지 않아요."].filter(Boolean).join(" ");
    const summary = byId("population-summary"); summary.replaceChildren();
    const lines = Array.isArray(result.summary) ? result.summary.filter((line) => typeof line === "string") : [];
    for (const line of lines.length ? lines : ["이 조건에서 확인된 유동인구 요약이 없어요. 자료 제공 범위와 각 분포의 상태를 확인해 주세요."]) appendSalesText(summary, "li", line);
    const distributions = byId("population-distributions"); distributions.replaceChildren();
    for (const [key, title] of [["time", "시간대별 유동인구"], ["age", "연령별 유동인구"]]) renderPopulationDistribution(distributions, key, result.distributions?.[key], title);
    const scope = byId("population-scope"); scope.replaceChildren();
    appendSalesText(scope, "p", `${selection.area_name} · ${selection.period_label || periodLabel(selection.period)} · 상권 전체 · 원천 단위: 명`);
    appendSalesText(scope, "p", "업종을 기준으로 나눈 자료가 아니며 선택 업종의 고객 수를 나타내지 않아요.");
    if (selection.boundary?.publication_date) appendSalesText(scope, "p", `${selection.boundary.publication_date} 공개 상권 경계를 기준으로 연결한 자료예요. 현재 분기 경계와의 동일성은 확인되지 않았어요.`);
    const sources = byId("population-sources"); sources.replaceChildren();
    if (typeof result.source?.url === "string" && /^https?:\/\//.test(result.source.url)) {
      const link = appendSalesText(sources, "a", result.source.title || "서울시 공식 유동인구 자료 출처"); link.href = result.source.url; link.target = "_blank"; link.rel = "noopener noreferrer";
    }
    const warnings = byId("population-warnings"); warnings.replaceChildren();
    for (const line of Array.isArray(result.warnings) ? result.warnings : []) if (typeof line === "string") appendSalesText(warnings, "li", line);
    byId("population-warnings-card").hidden = warnings.children.length === 0;
    byId("population-load-state").hidden = true;
    byId("population-result").hidden = false;
  }

  function renderPopulationDistribution(container, key, distribution, fallbackTitle) {
    const group = distribution || {};
    const card = document.createElement("section"); card.className = "sales-distribution";
    const heading = document.createElement("div"); heading.className = "sales-distribution-heading";
    appendSalesText(heading, "h3", group.label || fallbackTitle);
    appendSalesText(heading, "span", { complete: "합계 확인", partial: "일부 자료 없음", inconsistent: "합계 불일치", no_data: "자료 없음", invalid: "원천 값 확인 필요" }[group.status] || "자료 확인 필요", "sales-distribution-status");
    card.append(heading);
    appendSalesText(card, "p", `비중의 분모 · ${group.denominator?.label || "원천 총 유동인구 지표"}: ${integerUnitText(group.denominator, "명") || "확인된 인원 없음"}`, "sales-denominator");
    if (group.status === "inconsistent") {
      appendSalesText(card, "p", `분류 합계: ${integerUnitText({ value: group.sum }, "명") || "확인 필요"} · 분류 합계 − 총지표: ${integerUnitText({ value: group.total_difference }, "명") || "확인 필요"}. 합계가 달라 비중과 순위를 표시하지 않아요.`, "sales-denominator");
    }
    const table = document.createElement("table");
    appendSalesText(table, "caption", "원천 인원은 명 단위이며, 막대는 합계가 확인된 경우 제공된 비중만 표시합니다.");
    const thead = document.createElement("thead"), header = document.createElement("tr");
    for (const label of ["항목", "원천 인원", "비중"]) { const th = appendSalesText(header, "th", label); th.setAttribute("scope", "col"); }
    thead.append(header); table.append(thead);
    const tbody = document.createElement("tbody");
    const items = Array.isArray(group.items) ? group.items : [];
    const highest = group.status === "complete" && group.ranking?.status === "available" && Array.isArray(group.ranking.highest) ? group.ranking.highest : [];
    for (const item of items) {
      const row = document.createElement("tr");
      const isHighest = item.status === "available" && highest.includes(item.label);
      if (isHighest) row.className = "sales-row-highest";
      const label = appendSalesText(row, "th", item.label || "항목 확인 필요"); label.setAttribute("scope", "row");
      if (isHighest) appendSalesText(label, "span", highest.length > 1 ? "공동 최고" : "최고", "sales-highest-tag");
      const amount = document.createElement("td");
      appendSalesText(amount, "span", item.status === "available" ? integerUnitText(item, "명") || "인원 확인 필요" : item.status === "invalid" ? "확인 불가" : "자료 없음", "sales-row-amount");
      const share = group.status === "complete" && item.status === "available" && typeof item.share_percent === "number" && Number.isFinite(item.share_percent) && item.share_percent >= 0 && item.share_percent <= 100 ? item.share_percent : null;
      if (share !== null) {
        const track = document.createElement("div"); track.className = "sales-bar-track"; track.setAttribute("aria-hidden", "true");
        const bar = document.createElement("div"); bar.className = "sales-bar"; bar.style.width = `${share}%`; track.append(bar); amount.append(track);
      }
      row.append(amount);
      appendSalesText(row, "td", share !== null ? percentText(share) : "—", "sales-row-share");
      tbody.append(row);
    }
    table.append(tbody); card.append(table);
    if (!items.length) appendSalesText(card, "p", "확인된 분포 항목이 없어요.", "sales-distribution-message");
    const notes = Array.isArray(group.warnings) ? group.warnings.filter((line) => typeof line === "string") : [];
    if (key === "time" && !notes.some((note) => note.includes("시간당"))) notes.push("시간대 구간 길이가 달라요. 시간당 평균이나 밀도로 환산한 값이 아니에요.");
    for (const note of notes) appendSalesText(card, "p", note, "sales-distribution-message");
    container.append(card);
  }

  function clearComparisonResult() {
    byId("comparison-result").hidden = true;
    ["comparison-base-name", "comparison-base-meta", "comparison-target-name", "comparison-target-meta"].forEach((id) => { byId(id).textContent = ""; });
    ["comparison-rows", "comparison-scope", "comparison-sources", "comparison-warnings"].forEach((id) => byId(id).replaceChildren());
  }

  function invalidateComparisonResult() {
    comparisonState.sequence += 1;
    comparisonState.controller?.abort();
    comparisonState.controller = null;
    comparisonState.loading = false;
    byId("comparison-panel").setAttribute("aria-busy", "false");
    byId("comparison-load-state").hidden = true;
    byId("comparison-retry").hidden = true;
    clearComparisonResult();
  }

  function leaveComparison() {
    comparisonState.active = false;
    comparisonState.optionsSequence += 1;
    comparisonState.optionsController?.abort();
    comparisonState.optionsController = null;
    comparisonState.optionsLoading = false;
    comparisonState.conflict = false;
    invalidateComparisonResult();
    byId("comparison-panel").hidden = true;
    resetReportLayout();
  }

  function selectedComparisonArea() {
    return comparisonState.areas.find((area) => area.area_code === byId("comparison-area").value && area.district_code === byId("comparison-district").value && area.selectable === true) || null;
  }

  function updateComparisonControls() {
    const ready = comparisonState.active && !comparisonState.optionsLoading && !comparisonState.conflict && !!confirmedAnalysisSelection();
    byId("comparison-district").disabled = !ready || !comparisonState.areas.length;
    byId("comparison-area").disabled = !ready || !byId("comparison-district").value;
    byId("comparison-run").disabled = !ready || comparisonState.loading || !selectedComparisonArea();
  }

  function comparisonDistrictChanged() {
    invalidateComparisonResult();
    const select = byId("comparison-area"); select.replaceChildren(new Option("비교할 상권을 선택해 주세요", ""));
    const areas = comparisonState.areas.filter((area) => area.district_code === byId("comparison-district").value).sort((a, b) => a.name.localeCompare(b.name, "ko"));
    for (const area of areas) {
      const option = new Option(`${area.name}${area.type ? ` · ${area.type}` : ""}${area.selectable !== true ? " · 연결 확인 필요" : ""}`, area.area_code);
      option.disabled = area.selectable !== true;
      if (area.reason) option.title = area.reason;
      select.append(option);
    }
    byId("comparison-options-message").textContent = !byId("comparison-district").value ? "자치구를 먼저 선택해 주세요."
      : areas.length ? "기준 상권은 목록에서 제외했어요. 상권을 선택한 뒤 비교하기를 눌러 주세요." : "이 자치구에는 선택할 비교 상권이 없어요. 다른 자치구를 선택해 주세요.";
    updateComparisonControls();
  }

  async function openComparison(origin = "overview") {
    const saved = confirmedAnalysisSelection();
    if (!saved || state.submitting || analysisState.saving) return;
    if (origin === "analysis" && (analysisState.loading || analysisState.conflict
      || analysisState.selectedCode !== saved.area_code || analysisState.period !== saved.period
      || analysisState.catalogVersion !== saved.catalog_version)) return;
    leaveSales(); leaveStores(); leavePopulation(); leaveChanges(); leaveAnalysis();
    comparisonState.active = true;
    comparisonState.origin = origin;
    byId("comparison-panel").hidden = false;
    showReportLayout("comparison");
    byId("comparison-back").textContent = origin === "analysis" ? "상권 설정으로" : "가게 정보로";
    byId("comparison-condition").textContent = `기준: ${saved.area_name} · ${state.profile.industry.name} · ${saved.period_label || periodLabel(saved.period)} (업종·분기 고정)`;
    setStep(true, true, true);
    await loadComparisonOptions();
  }

  function comparisonConflict() {
    comparisonState.conflict = true;
    if (analysisState.saved) analysisState.saved = { ...analysisState.saved, status: "stale", analysis_setup_complete: false, conditions_confirmed: false, message: "분석 조건을 다시 확인해 주세요." };
    byId("comparison-reconfigure").textContent = "분석 조건 다시 확인";
    updateComparisonControls();
    renderReportMenu("comparison");
  }

  async function loadComparisonOptions() {
    if (!comparisonState.active) return;
    const saved = confirmedAnalysisSelection();
    if (!saved) { comparisonConflict(); return; }
    comparisonState.optionsController?.abort();
    const sequence = ++comparisonState.optionsSequence, controller = new AbortController();
    const revision = state.revision, conditionKey = reportConditionKey();
    comparisonState.optionsController = controller;
    comparisonState.optionsLoading = true;
    comparisonState.areas = [];
    comparisonState.catalogVersion = null;
    invalidateComparisonResult();
    byId("comparison-district").replaceChildren(new Option("목록을 불러오는 중이에요", ""));
    byId("comparison-area").replaceChildren(new Option("자치구를 먼저 선택해 주세요", ""));
    byId("comparison-options-retry").hidden = true;
    byId("comparison-options-message").textContent = "공식 상권 목록을 불러오고 있어요.";
    byId("comparison-reconfigure").textContent = "분석 조건 확인";
    updateComparisonControls();
    try {
      const result = await api(`/api/onboarding/comparison-options?expected_revision=${encodeURIComponent(revision)}`, { signal: controller.signal });
      if (!comparisonState.active || sequence !== comparisonState.optionsSequence || conditionKey !== reportConditionKey()) return;
      if (!reportContextMatches(result, revision, saved) || result.catalog_version !== saved.catalog_version) {
        byId("comparison-options-message").textContent = "분석 조건이나 상권 목록이 변경됐어요. 분석 조건을 다시 확인해 주세요.";
        comparisonConflict(); return;
      }
      if (result.status !== "ready" || !Array.isArray(result.areas) || !Array.isArray(result.districts)) throw new Error("상권 목록을 확인하지 못했어요. 다시 불러와 주세요.");
      comparisonState.catalogVersion = result.catalog_version;
      comparisonState.areas = result.areas.filter((area) => typeof area.area_code === "string" && area.area_code !== saved.area_code && typeof area.name === "string" && typeof area.district_code === "string");
      const district = byId("comparison-district"); district.replaceChildren(new Option("자치구를 선택해 주세요", ""));
      for (const item of result.districts) district.append(new Option(item.name, item.code));
      byId("comparison-options-message").textContent = comparisonState.areas.length ? "자치구를 선택하면 해당 지역의 공식 상권이 표시돼요. 기준 상권은 목록에서 제외했어요." : "현재 선택할 비교 상권이 없어요. 잠시 후 목록을 다시 확인해 주세요.";
      byId("comparison-options-retry").hidden = comparisonState.areas.length > 0;
    } catch (error) {
      if (!comparisonState.active || sequence !== comparisonState.optionsSequence || conditionKey !== reportConditionKey() || error.name === "AbortError") return;
      byId("comparison-options-message").textContent = error.message || "상권 목록을 불러오지 못했어요. 다시 시도해 주세요.";
      byId("comparison-options-retry").hidden = error.status === 409;
      if (error.status === 409) comparisonConflict();
    } finally {
      if (sequence === comparisonState.optionsSequence) {
        comparisonState.optionsLoading = false;
        comparisonState.optionsController = null;
        updateComparisonControls();
      }
    }
  }

  async function loadComparison() {
    if (!comparisonState.active || comparisonState.loading || comparisonState.optionsLoading || comparisonState.conflict) return;
    const saved = confirmedAnalysisSelection(), target = selectedComparisonArea();
    if (!saved || !target || comparisonState.catalogVersion !== saved.catalog_version) return;
    invalidateComparisonResult();
    const sequence = ++comparisonState.sequence, controller = new AbortController();
    const revision = state.revision, conditionKey = reportConditionKey(), targetCode = target.area_code;
    comparisonState.controller = controller;
    comparisonState.loading = true;
    byId("comparison-panel").setAttribute("aria-busy", "true");
    byId("comparison-load-state").hidden = false;
    byId("comparison-load-message").textContent = "두 상권의 같은 업종·분기 자료를 확인하고 있어요.";
    updateComparisonControls();
    try {
      const result = await api(`/api/onboarding/comparison?comparison_area_code=${encodeURIComponent(targetCode)}&expected_revision=${encodeURIComponent(revision)}`, { signal: controller.signal });
      if (!comparisonState.active || sequence !== comparisonState.sequence || conditionKey !== reportConditionKey() || selectedComparisonArea()?.area_code !== targetCode) return;
      if (!reportContextMatches(result, revision, saved) || result.base_area?.area_code !== saved.area_code || result.comparison_area?.area_code !== targetCode) {
        byId("comparison-load-message").textContent = "분석 조건이나 비교 상권이 변경됐어요. 분석 조건을 다시 확인해 주세요.";
        comparisonConflict(); return;
      }
      if (result.feature !== "comparison" || result.comparison_direction !== "comparison_minus_base" || !["complete", "partial", "no_data"].includes(result.status) || !Array.isArray(result.metrics)) throw new Error("비교 자료의 범위를 확인하지 못했어요. 다시 비교해 주세요.");
      renderComparisonResult(result);
    } catch (error) {
      if (!comparisonState.active || sequence !== comparisonState.sequence || conditionKey !== reportConditionKey() || error.name === "AbortError") return;
      clearComparisonResult();
      byId("comparison-load-message").textContent = error.message || "비교 자료를 불러오지 못했어요. 다시 시도해 주세요.";
      byId("comparison-retry").hidden = error.status === 409;
      if (error.status === 409) comparisonConflict();
    } finally {
      if (sequence === comparisonState.sequence) {
        comparisonState.loading = false;
        comparisonState.controller = null;
        byId("comparison-panel").setAttribute("aria-busy", "false");
        updateComparisonControls();
      }
    }
  }

  function comparisonValue(record, unit) {
    if (record?.status === "available") return integerUnitText(record, unit) || "원천 값 확인 필요";
    return { missing: "항목 없음", invalid: "원천 값 확인 필요", no_observation: "관측 행 없음", not_collected: "자료 미확보", unavailable: "자료 확인 불가" }[record?.status] || "자료 없음";
  }

  function renderComparisonResult(result) {
    const selection = result.selection;
    byId("comparison-condition").textContent = `기준: ${result.base_area.name} · ${selection.industry_name} · ${selection.period_label || periodLabel(selection.period)} (업종·분기 고정)`;
    for (const [prefix, area] of [["base", result.base_area], ["target", result.comparison_area]]) {
      byId(`comparison-${prefix}-name`).textContent = area.name;
      byId(`comparison-${prefix}-meta`).textContent = [area.district_name, area.type].filter(Boolean).join(" · ");
    }
    const rows = byId("comparison-rows"); rows.replaceChildren();
    const sources = new Map(), warnings = new Set(Array.isArray(result.warnings) ? result.warnings.filter((line) => typeof line === "string") : []);
    for (const metric of result.metrics) {
      const row = document.createElement("tr"), heading = appendSalesText(row, "th", metric.label || metric.key); heading.setAttribute("scope", "row");
      if (metric.industry_applied === false) appendSalesText(heading, "small", "상권 전체 · 업종 구분 없음");
      if (typeof metric.source?.url === "string" && /^https?:\/\//.test(metric.source.url)) {
        const link = appendSalesText(heading, "a", "출처", "comparison-metric-source"); link.href = metric.source.url; link.target = "_blank"; link.rel = "noopener noreferrer";
        sources.set(metric.source.url, metric.source.title || "공식 자료 출처");
      }
      for (const record of [metric.base, metric.comparison]) appendSalesText(row, "td", comparisonValue(record, metric.unit || ""), record?.status === "available" ? "" : "comparison-value-missing");
      const comparable = metric.status === "available" && metric.base?.status === "available" && metric.comparison?.status === "available";
      const delta = comparable ? integerUnitText({ value: metric.delta, value_text: metric.delta_text }, metric.unit || "") : null;
      appendSalesText(row, "td", delta || "비교 불가", delta ? "" : "comparison-value-missing");
      const percent = comparable && metric.percent_status === "available" && typeof metric.percent === "number" && Number.isFinite(metric.percent) ? metric.percent : null;
      const percentCell = appendSalesText(row, "td", percent !== null ? `${percent > 0 ? "+" : ""}${percentText(percent)}` : "산출 불가", percent !== null ? "" : "comparison-value-missing");
      if (comparable && metric.percent_status === "undefined_zero_base") appendSalesText(percentCell, "small", "기준 상권 값이 0");
      rows.append(row);
      for (const line of Array.isArray(metric.warnings) ? metric.warnings : []) if (typeof line === "string") warnings.add(line);
    }
    const scope = byId("comparison-scope"); scope.replaceChildren();
    appendSalesText(scope, "p", `${selection.industry_name} · ${selection.period_label || periodLabel(selection.period)} · 각 지표의 원천 단위를 그대로 비교해요.`);
    appendSalesText(scope, "p", "차이 = 비교 상권 − 기준 상권. 차이 비율은 기준 상권 값을 분모로 하며, 기준이 0이면 산출하지 않아요.");
    const sourceContainer = byId("comparison-sources"); sourceContainer.replaceChildren();
    for (const [url, title] of sources) { const link = appendSalesText(sourceContainer, "a", title); link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer"; }
    const warningContainer = byId("comparison-warnings"); warningContainer.replaceChildren();
    for (const line of warnings) appendSalesText(warningContainer, "li", line);
    byId("comparison-warnings-card").hidden = warningContainer.children.length === 0;
    byId("comparison-load-state").hidden = true;
    byId("comparison-result").hidden = false;
  }

  function clearChangesResult() {
    byId("changes-result").hidden = true;
    ["changes-current-period", "changes-current-meta", "changes-previous-period", "changes-previous-meta", "changes-result-note"].forEach((id) => { byId(id).textContent = ""; });
    ["changes-rows", "changes-scope", "changes-sources", "changes-warnings"].forEach((id) => byId(id).replaceChildren());
  }

  function invalidateChangesResult() {
    changesState.sequence += 1;
    changesState.controller?.abort();
    changesState.controller = null;
    changesState.loading = false;
    byId("changes-panel").setAttribute("aria-busy", "false");
    byId("changes-load-state").hidden = true;
    byId("changes-retry").hidden = true;
    clearChangesResult();
  }

  function leaveChanges() {
    changesState.active = false;
    changesState.conflict = false;
    invalidateChangesResult();
    byId("changes-panel").hidden = true;
    resetReportLayout();
  }

  function updateChangesControls() {
    const ready = changesState.active && !changesState.conflict && !!confirmedAnalysisSelection();
    byId("changes-mode").disabled = !ready;
    byId("changes-run").disabled = !ready || changesState.loading || !["qoq", "yoy"].includes(byId("changes-mode").value);
  }

  function openChanges(origin = "overview") {
    const saved = confirmedAnalysisSelection();
    if (!saved || state.submitting || analysisState.saving) return;
    if (origin === "analysis" && (analysisState.loading || analysisState.conflict
      || analysisState.selectedCode !== saved.area_code || analysisState.period !== saved.period
      || analysisState.catalogVersion !== saved.catalog_version)) return;
    leaveSales(); leaveStores(); leavePopulation(); leaveComparison(); leaveAnalysis();
    changesState.active = true;
    changesState.origin = origin;
    changesState.conflict = false;
    invalidateChangesResult();
    byId("changes-mode").value = "qoq";
    byId("changes-panel").hidden = false;
    showReportLayout("changes");
    byId("changes-back").textContent = origin === "analysis" ? "상권 설정으로" : "가게 정보로";
    byId("changes-reconfigure").textContent = "분석 조건 확인";
    byId("changes-condition").textContent = `${saved.area_name} · ${state.profile.industry.name} · 현재 분기: ${saved.period_label || periodLabel(saved.period)}`;
    updateChangesControls();
    setStep(true, true, true);
  }

  function changesConflict() {
    changesState.conflict = true;
    if (analysisState.saved) analysisState.saved = { ...analysisState.saved, status: "stale", analysis_setup_complete: false, conditions_confirmed: false, message: "분석 조건을 다시 확인해 주세요." };
    byId("changes-reconfigure").textContent = "분석 조건 다시 확인";
    updateChangesControls();
    renderReportMenu("changes");
  }

  function previousPeriodCode(current, mode) {
    if (!/^\d{4}[1-4]$/.test(current) || !["qoq", "yoy"].includes(mode)) return null;
    const year = Number(current.slice(0, 4)), quarter = Number(current[4]);
    return mode === "yoy" ? `${year - 1}${quarter}` : quarter === 1 ? `${year - 1}4` : `${year}${quarter - 1}`;
  }

  async function loadChanges() {
    if (!changesState.active || changesState.loading || changesState.conflict) return;
    const saved = confirmedAnalysisSelection(), mode = byId("changes-mode").value;
    if (!saved || !["qoq", "yoy"].includes(mode)) return;
    invalidateChangesResult();
    const sequence = ++changesState.sequence, controller = new AbortController();
    const revision = state.revision, conditionKey = reportConditionKey();
    changesState.controller = controller;
    changesState.loading = true;
    byId("changes-panel").setAttribute("aria-busy", "true");
    byId("changes-load-state").hidden = false;
    byId("changes-load-message").textContent = "같은 상권·업종의 두 분기 자료를 확인하고 있어요.";
    updateChangesControls();
    try {
      const result = await api(`/api/onboarding/changes?comparison=${encodeURIComponent(mode)}&expected_revision=${encodeURIComponent(revision)}`, { signal: controller.signal });
      if (!changesState.active || sequence !== changesState.sequence || conditionKey !== reportConditionKey() || byId("changes-mode").value !== mode) return;
      if (!reportContextMatches(result, revision, saved)) {
        byId("changes-load-message").textContent = "분석 조건이 변경됐어요. 분석 조건을 다시 확인해 주세요.";
        changesConflict(); return;
      }
      if (result.feature !== "changes" || result.comparison !== mode || result.comparison_direction !== "current_minus_previous"
        || result.current_period?.code !== saved.period || result.previous_period?.code !== previousPeriodCode(saved.period, mode)
        || !["complete", "partial", "no_comparison"].includes(result.status) || !Array.isArray(result.metrics)) throw new Error("비교 기간이나 자료의 범위를 확인하지 못했어요. 다시 조회해 주세요.");
      renderChangesResult(result);
    } catch (error) {
      if (!changesState.active || sequence !== changesState.sequence || conditionKey !== reportConditionKey() || error.name === "AbortError") return;
      clearChangesResult();
      byId("changes-load-message").textContent = error.message || "기간 변화 자료를 불러오지 못했어요. 다시 시도해 주세요.";
      byId("changes-retry").hidden = error.status === 409;
      if (error.status === 409) changesConflict();
    } finally {
      if (sequence === changesState.sequence) {
        changesState.loading = false;
        changesState.controller = null;
        byId("changes-panel").setAttribute("aria-busy", "false");
        updateChangesControls();
      }
    }
  }

  function renderChangesResult(result) {
    const selection = result.selection;
    const currentLabel = result.current_period.label || periodLabel(result.current_period.code);
    const previousLabel = result.previous_period.label || periodLabel(result.previous_period.code);
    byId("changes-condition").textContent = `${selection.area_name} · ${selection.industry_name} · 현재 분기: ${currentLabel}`;
    byId("changes-current-period").textContent = currentLabel;
    byId("changes-current-meta").textContent = `${selection.area_name} · ${selection.industry_name}`;
    byId("changes-previous-period").textContent = previousLabel;
    byId("changes-previous-meta").textContent = `${result.comparison_label || (result.comparison === "qoq" ? "전분기" : "전년 동분기")} · 같은 상권·업종`;
    const summaries = Array.isArray(result.summary) ? result.summary.filter((line) => typeof line === "string") : [];
    byId("changes-result-note").textContent = summaries.length ? summaries.join(" ") : result.status === "no_comparison"
      ? "확인된 값만 표시했어요. 양쪽 기간이 확인된 지표가 없어 증감은 계산하지 않았어요."
      : result.status === "partial" ? "양쪽 기간이 확인된 지표만 증감을 표시했어요. 누락된 값은 0으로 바꾸지 않았어요." : "같은 상권·업종의 두 분기 원천 값을 비교했어요.";
    const rows = byId("changes-rows"); rows.replaceChildren();
    const sources = new Map(), warnings = new Set(Array.isArray(result.warnings) ? result.warnings.filter((line) => typeof line === "string") : []);
    for (const metric of result.metrics) {
      const row = document.createElement("tr"), heading = appendSalesText(row, "th", metric.label || metric.key); heading.setAttribute("scope", "row");
      if (metric.industry_applied === false) appendSalesText(heading, "small", "상권 전체 · 업종 구분 없음");
      if (typeof metric.source?.url === "string" && /^https?:\/\//.test(metric.source.url)) {
        const link = appendSalesText(heading, "a", "출처", "comparison-metric-source"); link.href = metric.source.url; link.target = "_blank"; link.rel = "noopener noreferrer";
        sources.set(metric.source.url, metric.source.title || "공식 자료 출처");
      }
      for (const record of [metric.current, metric.previous]) appendSalesText(row, "td", comparisonValue(record, metric.unit || ""), record?.status === "available" ? "" : "comparison-value-missing");
      const comparable = metric.status === "available" && metric.current?.status === "available" && metric.previous?.status === "available";
      const delta = comparable ? integerUnitText({ value: metric.delta, value_text: metric.delta_text }, metric.unit || "") : null;
      appendSalesText(row, "td", delta || "비교 불가", delta ? "" : "comparison-value-missing");
      const percent = comparable && metric.percent_status === "available" && typeof metric.percent === "number" && Number.isFinite(metric.percent) ? metric.percent : null;
      const percentCell = appendSalesText(row, "td", percent !== null ? `${percent > 0 ? "+" : ""}${percentText(percent)}` : "산출 불가", percent !== null ? "" : "comparison-value-missing");
      if (comparable && metric.percent_status === "undefined_zero_previous") appendSalesText(percentCell, "small", "비교 분기 값이 0");
      rows.append(row);
      for (const line of Array.isArray(metric.warnings) ? metric.warnings : []) if (typeof line === "string") warnings.add(line);
    }
    const scope = byId("changes-scope"); scope.replaceChildren();
    appendSalesText(scope, "p", `${selection.area_name} · ${selection.industry_name} · ${currentLabel}와 ${previousLabel} · 원천 단위 유지`);
    appendSalesText(scope, "p", "차이 = 현재 분기 − 비교 분기. 증감률의 분모는 비교 분기 값이며, 해당 기간 자료가 없으면 다른 분기로 대체하지 않아요.");
    const sourceContainer = byId("changes-sources"); sourceContainer.replaceChildren();
    for (const [url, title] of sources) { const link = appendSalesText(sourceContainer, "a", title); link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer"; }
    const warningContainer = byId("changes-warnings"); warningContainer.replaceChildren();
    for (const line of warnings) appendSalesText(warningContainer, "li", line);
    byId("changes-warnings-card").hidden = warningContainer.children.length === 0;
    byId("changes-load-state").hidden = true;
    byId("changes-result").hidden = false;
  }

  function setStep(review, analysis = false, sales = false) {
    byId("step-input").classList.toggle("current", !review);
    byId("step-input").classList.toggle("completed", review);
    byId("step-review").classList.toggle("current", review && !analysis);
    byId("step-review").classList.toggle("completed", analysis);
    byId("step-analysis").classList.toggle("current", analysis && !sales);
    byId("step-analysis").classList.toggle("completed", sales);
    byId("step-sales").classList.toggle("current", sales);
    byId("step-input").removeAttribute("aria-current");
    byId("step-review").removeAttribute("aria-current");
    byId("step-analysis").removeAttribute("aria-current");
    byId("step-sales").removeAttribute("aria-current");
    byId(sales ? "step-sales" : analysis ? "step-analysis" : review ? "step-review" : "step-input").setAttribute("aria-current", "step");
  }

  function renderSaved() {
    leaveSales();
    leaveStores();
    leavePopulation();
    leaveComparison();
    leaveChanges();
    leaveAnalysis();
    state.editing = false;
    state.addressComposing = false;
    invalidateAddressSearch();
    invalidateAreaSearch();
    byId("profile-form").hidden = true;
    byId("saved-overview").hidden = false;
    byId("clear-confirmation").hidden = true;
    byId("page-heading").textContent = "사장님의 가게를 기억할게요.";
    byId("page-description").textContent = "저장한 정보를 확인해 주세요. 언제든 수정할 수 있어요.";
    const profile = state.profile;
    byId("saved-location").textContent = profile.location.label;
    byId("saved-verification").textContent = profile.location.verification === "verified_address"
      ? "서울 주소 확인 완료 · 실제 분석 범위는 다음 단계에서 정해요."
      : profile.location.verification === "verified_station"
        ? `서울특별시 ${profile.location.district_name}${profile.location.station_line_name ? ` · ${profile.location.station_line_name}` : ""} · 역 기준 위치예요. 분석할 상권은 다음 단계에서 직접 확인해요.`
        : profile.location.verification === "geocoded_area_reference"
          ? `서울특별시 ${profile.location.district_name} · 동네 참고 위치를 확인했어요. 가게 주소와 분석 경계는 아직 정해지지 않았어요.`
          : profile.location.verification === "selected_neighborhood"
            ? `서울특별시 ${profile.location.district_name} · 행정동을 선택했어요. 정확한 가게 주소와 분석 경계는 아직 정해지지 않았어요.`
            : `서울특별시 ${profile.location.district_name} · 직접 입력한 위치예요. 정확한 위치와 분석 범위는 추가로 확인해요.`;
    byId("saved-industry").textContent = profile.industry.name;
    byId("saved-status").textContent = profile.business_status_label;
    if (analysisState.saved?.analysis_setup_complete === true && !["stale", "unavailable"].includes(analysisState.saved.status)) {
      byId("saved-verification").textContent = `가게의 기준 위치예요. 분석 상권은 ‘${analysisState.saved.area_name}’로 저장했어요.`;
    }
    renderSavedAnalysisNote();
    setStep(true);
    updateSummary();
  }

  function renderForm() {
    leaveSales();
    leaveStores();
    leavePopulation();
    leaveComparison();
    leaveChanges();
    leaveAnalysis();
    clearFieldErrors();
    state.editing = true;
    state.addressComposing = false;
    invalidateAddressSearch();
    invalidateAreaSearch();
    byId("profile-form").reset();
    state.selectedStation = null;
    byId("station-selection-note").hidden = true;
    byId("profile-form").hidden = false;
    byId("saved-overview").hidden = true;
    byId("saved-address-note").hidden = true;
    byId("saved-area-note").hidden = true;
    renderNeighborhoods();
    renderStationLines();
    byId("cancel-edit").hidden = !state.profile;
    byId("page-heading").textContent = state.profile ? "가게 정보를 수정해 주세요." : "먼저, 가게를 알려주세요.";
    byId("page-description").textContent = state.profile ? "위치나 업종을 바꾸면 분석할 상권과 기간을 다시 확인해 주세요." : "위치와 업종, 운영 상태를 저장하고 분석할 상권과 자료 기간을 선택해 주세요.";
    state.locationDirty = !state.profile;
    if (state.profile) {
      const location = state.profile.location;
      const kindRadio = document.querySelector(`input[name="location-kind"][value="${location.kind}"]`);
      if (kindRadio) kindRadio.checked = true;
      if (location.kind === "address") {
        byId("address-query").value = location.label;
        byId("saved-address-note").textContent = "저장된 주소를 유지해요. 주소를 바꾸려면 새로 검색해 선택해 주세요.";
        byId("saved-address-note").hidden = false;
      } else if (location.kind === "station") {
        const station = state.options.stations?.find((item) => item.id === location.station_id);
        const lines = (state.options.station_lines || []).filter((line) => station?.selectable_line_codes?.includes(line.code));
        const line = location.station_line_code ? lines.find((item) => item.code === location.station_line_code)
          : lines.length === 1 ? lines[0] : null;
        if (station && line) {
          renderStationLines(line.code);
          renderStationOptions(station.id);
          state.selectedStation = stationFromControls();
        }
        byId("station-selection-note").textContent = state.selectedStation
          ? "저장된 노선과 역을 유지해요. 위치를 바꾸려면 노선과 역을 다시 선택해 주세요."
          : `기존 위치 ‘${location.label}’를 유지해요. 위치를 바꾸려면 노선과 역을 새로 선택해 주세요.`;
        byId("station-selection-note").hidden = false;
      } else {
        byId("district-select").value = location.district_code || "";
        const legacyName = (location.text || location.label || "").trim();
        const exactMatches = neighborhoodsForDistrict().filter((item) => item.name === legacyName);
        const code = location.neighborhood_code || (exactMatches.length === 1 ? exactMatches[0].code : "");
        renderNeighborhoods(code);
        byId("saved-area-note").textContent = selectedNeighborhood()
          ? "저장된 위치를 유지해요. 자치구나 동네를 바꾸면 새 위치로 저장됩니다."
          : `기존 위치 ‘${location.label}’를 유지해요. 위치를 바꾸려면 자치구와 동네를 새로 선택해 주세요.`;
        byId("saved-area-note").hidden = false;
      }
      renderIndustries(state.profile.industry.code);
      const statusRadio = document.querySelector(`input[name="business-status"][value="${state.profile.business_status}"]`);
      if (statusRadio) statusRadio.checked = true;
    } else renderIndustries("");
    showLocationPanel();
    setSearchBusy(false);
    setAreaBusy(false);
    setStep(false);
    updateSummary();
  }

  function setSubmitting(submitting) {
    state.submitting = submitting;
    byId("profile-form").inert = submitting;
    byId("profile-form").setAttribute("aria-busy", String(submitting));
    byId("save-profile").disabled = submitting;
    byId("confirm-clear").disabled = submitting;
    byId("edit-profile").disabled = submitting;
    byId("show-clear").disabled = submitting;
    byId("cancel-edit").disabled = submitting;
    byId("cancel-clear").disabled = submitting;
    byId("confirm-clear").textContent = submitting ? "처리 중…" : "삭제할게요";
    byId("save-profile").textContent = submitting ? "저장하고 있어요…" : "가게 정보 저장하기 →";
    setSearchBusy(state.searching);
    setAreaBusy(state.areaSearching);
  }

  async function saveProfile(event) {
    event.preventDefault();
    if (state.submitting || state.addressComposing) return;
    clearAppError();
    clearFieldErrors();
    const industry = byId("industry-select").value;
    const businessStatus = selectedStatus();
    let location;
    let invalid = false;
    if (state.profile && !state.locationDirty) location = null;
    else if (selectedKind() === "address") {
      if (!state.searchId || !state.selectedCandidate || state.selectedCandidate.in_seoul !== true) {
        fieldError("location-error", "주소를 검색한 뒤 서울특별시 주소를 선택해 주세요.");
        invalid = true;
      } else location = { kind: "address", search_id: state.searchId, candidate_id: state.selectedCandidate.id };
    } else if (selectedKind() === "station") {
      const station = stationFromControls();
      const line = selectedStationLine();
      if (!station || !line || state.selectedStation?.id !== station.id) {
        fieldError("location-error", "지하철 노선을 선택한 뒤 가까운 역을 선택해 주세요.");
        invalid = true;
      } else location = { kind: "station", station_id: station.id, station_line_code: line.code };
    } else {
      const district = byId("district-select").value;
      const neighborhood = selectedNeighborhood();
      if (!district || !neighborhood) {
        fieldError("location-error", "서울 자치구를 선택한 뒤 해당 구의 동네를 선택해 주세요.");
        invalid = true;
      } else {
        location = { kind: selectedKind(), district_code: district, neighborhood_code: neighborhood.code };
        if (state.areaSearchId && state.selectedAreaCandidate) {
          location.search_id = state.areaSearchId;
          location.candidate_id = state.selectedAreaCandidate.id;
        }
      }
    }
    if (!industry) { fieldError("industry-error", "업종을 선택해 주세요."); invalid = true; }
    if (!businessStatus) { fieldError("status-error", "현재 운영 단계를 선택해 주세요."); invalid = true; }
    if (invalid) {
      document.querySelector('.field-error:not([hidden])')?.scrollIntoView({ block: "center", behavior: "smooth" });
      return;
    }
    setSubmitting(true);
    try {
      const result = await api("/api/onboarding/profile", { method: "POST", body: JSON.stringify({
        location, industry_code: industry, business_status: businessStatus, expected_revision: state.revision,
      }) });
      state.profile = result.profile;
      state.revision = result.revision ?? result.profile.revision;
      analysisState.saved = result.analysis_selection || null;
      renderSaved();
      byId("page-heading").scrollIntoView({ block: "start", behavior: "smooth" });
    } catch (error) { showAppError(error); }
    finally { setSubmitting(false); }
  }

  async function clearProfile() {
    if (state.submitting) return;
    clearAppError();
    setSubmitting(true);
    try {
      const result = await api(`/api/onboarding/profile?expected_revision=${encodeURIComponent(state.revision)}`, { method: "DELETE" });
      state.profile = null;
      analysisState.saved = null;
      state.revision = result.revision;
      renderForm();
    } catch (error) { showAppError(error); }
    finally { setSubmitting(false); }
  }

  async function initialize() {
    leaveSales();
    leaveStores();
    leavePopulation();
    leaveComparison();
    leaveChanges();
    leaveAnalysis();
    clearAppError();
    byId("loading").hidden = false;
    byId("workspace").hidden = true;
    try {
      const [options, saved] = await Promise.all([
        api("/api/onboarding/options"), api("/api/onboarding/analysis-selection"),
      ]);
      state.options = options;
      state.profile = saved.profile;
      analysisState.saved = saved.analysis_selection || null;
      state.revision = saved.revision ?? saved.profile?.revision ?? 0;
      renderOptions();
      if (state.profile) renderSaved(); else renderForm();
      byId("workspace").hidden = false;
    } catch (error) {
      showAppError(error);
      byId("retry-load").textContent = "다시 불러오기";
      byId("retry-load").hidden = false;
    } finally { byId("loading").hidden = true; }
  }

  byId("profile-form").addEventListener("submit", saveProfile);
  byId("search-address").addEventListener("click", openAddressPicker);
  byId("verify-address").addEventListener("click", () => verifyAddress());
  byId("close-address-dialog").addEventListener("click", () => closeAddressPicker());
  byId("address-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeAddressPicker(); });
  byId("address-query").addEventListener("input", handleAddressInput);
  byId("address-query").addEventListener("compositionstart", () => {
    state.addressComposing = true;
    setSearchBusy(state.searching);
  });
  byId("address-query").addEventListener("compositionend", () => {
    state.addressComposing = false;
    handleAddressInput();
  });
  byId("address-query").addEventListener("keydown", (event) => {
    if (event.isComposing || state.addressComposing || event.keyCode === 229) return;
    if (event.key === "Enter") { event.preventDefault(); openAddressPicker(); }
    else if (event.key === "ArrowDown" && state.candidates.length) {
      event.preventDefault();
      renderCandidates();
      document.querySelector('input[name="address-candidate"]:not(:disabled)')?.focus();
    } else if (event.key === "Escape") {
      byId("address-results-wrap").hidden = true;
      byId("address-query").setAttribute("aria-expanded", "false");
    }
  });
  byId("station-line-select").addEventListener("change", () => { renderStationOptions(); locationChanged(); });
  byId("station-select").addEventListener("change", () => {
    locationChanged();
    const station = stationFromControls();
    if (station) selectStation(station);
  });
  document.querySelectorAll('input[name="location-kind"]').forEach((input) => input.addEventListener("change", () => { locationChanged(); showLocationPanel(); }));
  byId("district-select").addEventListener("change", () => { renderNeighborhoods(); locationChanged(); });
  byId("place-text").addEventListener("change", locationChanged);
  byId("preview-area").addEventListener("click", previewArea);
  ["district-select", "place-text", "industry-select", "station-line-select", "station-select"].forEach((id) => byId(id).addEventListener("keydown", (event) => {
    if (event.key === "Enter") event.preventDefault();
  }));
  byId("map-retry").addEventListener("click", retryMap);
  byId("map-recenter").addEventListener("click", () => {
    if (analysisState.active && mapState.instance && mapState.analysisBounds && window.naver?.maps) {
      try { fitAnalysisBounds(window.naver.maps, mapState.analysisBounds); }
      catch { mapFailure("상권 경계로 이동하지 못했어요. 목록 선택과 저장은 계속 이용할 수 있어요."); }
      return;
    }
    const point = mapState.selectedPoint;
    if (!mapState.instance || !point || !window.naver?.maps) return;
    try { mapState.instance.setCenter(new window.naver.maps.LatLng(point.latitude, point.longitude)); }
    catch { mapFailure("지도를 이동하지 못했어요. 입력과 정보 저장은 계속 이용할 수 있어요."); }
  });
  byId("industry-select").addEventListener("change", () => { fieldError("industry-error", ""); updateSummary(); });
  byId("open-analysis").addEventListener("click", openAnalysis);
  byId("analysis-back").addEventListener("click", () => { if (!analysisState.saving) renderSaved(); });
  byId("analysis-retry").addEventListener("click", loadAnalysisOptions);
  byId("analysis-quarter").addEventListener("change", () => {
    if (analysisState.loading || analysisState.saving || analysisState.conflict) return;
    analysisState.period = byId("analysis-quarter").value;
    renderAnalysisDetails();
  });
  byId("analysis-quarter").addEventListener("keydown", (event) => { if (event.key === "Enter") event.preventDefault(); });
  byId("save-analysis").addEventListener("click", saveAnalysisSelection);
  byId("view-sales-overview").addEventListener("click", () => openSales("overview"));
  byId("view-sales-analysis").addEventListener("click", () => openSales("analysis"));
  byId("sales-retry").addEventListener("click", loadSales);
  byId("sales-reconfigure").addEventListener("click", openAnalysis);
  byId("sales-back").addEventListener("click", () => { if (salesState.origin === "analysis") return openAnalysis(); renderSaved(); });
  byId("report-menu-sales").addEventListener("click", () => switchReport("sales"));
  byId("report-menu-stores").addEventListener("click", () => switchReport("stores"));
  byId("report-menu-population").addEventListener("click", () => switchReport("population"));
  byId("report-menu-comparison").addEventListener("click", () => switchReport("comparison"));
  byId("report-menu-changes").addEventListener("click", () => switchReport("changes"));
  byId("stores-retry").addEventListener("click", loadStores);
  byId("stores-reconfigure").addEventListener("click", openAnalysis);
  byId("stores-back").addEventListener("click", () => { if (storesState.origin === "analysis") return openAnalysis(); renderSaved(); });
  byId("population-retry").addEventListener("click", loadPopulation);
  byId("population-reconfigure").addEventListener("click", openAnalysis);
  byId("population-back").addEventListener("click", () => { if (populationState.origin === "analysis") return openAnalysis(); renderSaved(); });
  byId("comparison-district").addEventListener("change", comparisonDistrictChanged);
  byId("comparison-area").addEventListener("change", () => { invalidateComparisonResult(); updateComparisonControls(); });
  byId("comparison-run").addEventListener("click", loadComparison);
  byId("comparison-retry").addEventListener("click", loadComparison);
  byId("comparison-options-retry").addEventListener("click", loadComparisonOptions);
  byId("comparison-reconfigure").addEventListener("click", openAnalysis);
  byId("comparison-back").addEventListener("click", () => { if (comparisonState.origin === "analysis") return openAnalysis(); renderSaved(); });
  for (const id of ["comparison-district", "comparison-area"]) byId(id).addEventListener("keydown", (event) => { if (event.key === "Enter") event.preventDefault(); });
  byId("changes-mode").addEventListener("change", () => { invalidateChangesResult(); updateChangesControls(); });
  byId("changes-mode").addEventListener("keydown", (event) => { if (event.key === "Enter") event.preventDefault(); });
  byId("changes-run").addEventListener("click", loadChanges);
  byId("changes-retry").addEventListener("click", loadChanges);
  byId("changes-reconfigure").addEventListener("click", openAnalysis);
  byId("changes-back").addEventListener("click", () => { if (changesState.origin === "analysis") return openAnalysis(); renderSaved(); });
  byId("edit-profile").addEventListener("click", () => { clearAppError(); renderForm(); });
  byId("cancel-edit").addEventListener("click", () => { clearAppError(); renderSaved(); });
  byId("show-clear").addEventListener("click", () => { byId("clear-confirmation").hidden = false; });
  byId("cancel-clear").addEventListener("click", () => { byId("clear-confirmation").hidden = true; });
  byId("confirm-clear").addEventListener("click", clearProfile);
  byId("retry-load").addEventListener("click", initialize);
  initialize();
})();
