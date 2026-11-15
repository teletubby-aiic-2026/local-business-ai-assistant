/* 설문 맞춤 마케팅 — 프레임워크 없는 바닐라 JS. 상태는 이 변수(state)만 들고 다니며
   매 요청마다 서버로 그대로 보낸다(서버는 아무것도 저장하지 않는다). */

const API = "/api/marketing-survey";
const chatEl = document.getElementById("chat");
const optionsEl = document.getElementById("options");
const storeNameEl = document.getElementById("store-name");
const restartBtn = document.getElementById("restart-btn");

let state = null;
let editedTexts = {};
let sessionId = null; // /plan 이 돌려준 기록 id — 승인할 때 같이 보낸다
let selectedStore = "store_ongi";
let storeList = [];

/* 11/3 "마케팅 비서" 시안의 아이콘 — 꼭 쓰는 것만 가져온다 */
const ICON_PATHS = {
  spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
  home: '<path d="M3 9l9-6 9 6v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/><path d="M9 21V12h6v9"/>',
  cal: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  ticket: '<path d="M3 8a2 2 0 0 0 2-2h14a2 2 0 0 0 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 0-2 2H5a2 2 0 0 0-2-2v-2a2 2 0 0 0 0-4z"/>',
  check: '<path d="M9 11l3 3 8-8"/><path d="M20 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/>',
};

function icon(name, size = 16) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
    `stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICON_PATHS[name]}</svg>`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function scrollToRow(row) {
  row.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function postJSON(url, body) {
  const res = await fetch(`${url}?store=${encodeURIComponent(selectedStore)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "요청에 실패했어요.");
  }
  return res.json();
}

/* 머리의 가게 알약 — 데이터가 있는 가게(available=true)만 고를 수 있다. 없는 가게는
   이름에 "(데모 데이터 없음)"을 붙여 보여만 주고 누를 수 없게(disabled) 한다. */
function closeStoreMenu() {
  const pillBtn = document.getElementById("store-pill");
  const menu = document.getElementById("store-menu");
  if (!pillBtn || !menu) return;
  menu.hidden = true;
  pillBtn.setAttribute("aria-expanded", "false");
}

/* 바깥 클릭·Esc 로 닫는 리스너는 한 번만 붙인다(다시 그릴 때마다 쌓이지 않게). */
let storePickerGlobalsBound = false;
function bindStorePickerGlobals() {
  if (storePickerGlobalsBound) return;
  storePickerGlobalsBound = true;
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".store-picker")) closeStoreMenu();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeStoreMenu();
  });
}

function renderStorePicker(list) {
  storeList = list;
  const current = list.find((s) => s.store_id === selectedStore) || list[0];
  if (!current) return;
  storeNameEl.innerHTML = `
    <span>예시 가게</span>
    <div class="store-picker">
      <button class="pill" id="store-pill" aria-haspopup="listbox" aria-expanded="false"></button>
      <div class="store-menu" id="store-menu" hidden role="listbox"></div>
    </div>
  `;
  const pillBtn = storeNameEl.querySelector("#store-pill");
  const menu = storeNameEl.querySelector("#store-menu");
  pillBtn.textContent = current.name;

  menu.innerHTML = list.map((s) => `
    <button class="store-menu-item" data-id="${escapeHtml(s.store_id)}" role="option" ${s.available ? "" : "disabled"}>
      <span>${escapeHtml(s.name)}</span>
    </button>
  `).join("");

  pillBtn.onclick = () => {
    const willOpen = menu.hidden;
    menu.hidden = !willOpen;
    pillBtn.setAttribute("aria-expanded", String(willOpen));
  };
  menu.querySelectorAll(".store-menu-item").forEach((btn) => {
    if (btn.disabled) return;
    btn.onclick = () => {
      closeStoreMenu();
      if (btn.dataset.id === selectedStore) return;
      selectedStore = btn.dataset.id;
      renderStorePicker(storeList);
      start();
    };
  });
  bindStorePickerGlobals();
}

/* 서버 호출 중(제안 생성 등)에는 말풍선 + 점 3개 애니메이션을 보여 주고, 끝나면 지운다.
   실패하면 같은 자리에 "잠시 후 다시 눌러 주세요" + [다시 시도]를 보여 준다(onRetry 를 다시 부른다). */
function setOptionsDisabled(disabled) {
  optionsEl.querySelectorAll("button").forEach((b) => {
    b.disabled = disabled;
  });
}

function addLoadingBubble() {
  const row = document.createElement("div");
  row.className = "row bot";
  row.innerHTML = `<div class="icon">${icon("spark", 16)}</div>` +
    `<div class="bubble-col"><div class="bubble bot loading" aria-live="polite">제안을 만들고 있어요` +
    `<span class="dots"><span>.</span><span>.</span><span>.</span></span></div></div>`;
  chatEl.appendChild(row);
  scrollToRow(row);
  return row;
}

function showRetryPrompt(onRetry) {
  clearOptions();
  const row = document.createElement("div");
  row.className = "row bot";
  row.innerHTML = `<div class="icon">${icon("spark", 16)}</div>` +
    `<div class="bubble-col"><div class="bubble bot">잠시 후 다시 눌러 주세요</div></div>`;
  chatEl.appendChild(row);

  const btn = document.createElement("button");
  btn.className = "opt-btn";
  btn.textContent = "다시 시도";
  btn.onclick = () => {
    row.remove();
    clearOptions();
    onRetry();
  };
  optionsEl.appendChild(btn);
  scrollToRow(row);
}

function addBotBubble(text, hint) {
  const row = document.createElement("div");
  row.className = "row bot";
  const col = document.createElement("div");
  col.className = "bubble-col";
  const bubble = document.createElement("div");
  bubble.className = "bubble bot";
  bubble.textContent = text;
  col.appendChild(bubble);
  if (hint) {
    const hintEl = document.createElement("div");
    hintEl.className = "bubble-hint";
    hintEl.textContent = hint;
    col.appendChild(hintEl);
  }
  row.innerHTML = `<div class="icon">${icon("spark", 16)}</div>`;
  row.appendChild(col);
  chatEl.appendChild(row);
  scrollToRow(row);
}

function addUserBubble(text) {
  const row = document.createElement("div");
  row.className = "row user";
  const bubble = document.createElement("div");
  bubble.className = "bubble user";
  bubble.textContent = text;
  row.appendChild(bubble);
  chatEl.appendChild(row);
  scrollToRow(row);
}

function clearOptions() {
  optionsEl.innerHTML = "";
}

function renderOptions(options, multi) {
  clearOptions();
  if (multi) {
    const selected = new Set();
    const next = document.createElement("button");
    next.className = "next-btn";
    next.textContent = "다음";
    next.disabled = true;
    options.forEach((opt) => {
      const btn = document.createElement("button");
      btn.className = "opt-btn toggle";
      btn.textContent = opt.label;
      btn.onclick = () => {
        if (selected.has(opt.value)) {
          selected.delete(opt.value);
          btn.classList.remove("selected");
        } else {
          selected.add(opt.value);
          btn.classList.add("selected");
        }
        next.disabled = selected.size === 0;
      };
      optionsEl.appendChild(btn);
    });
    next.onclick = () => {
      const chosenLabels = options.filter((o) => selected.has(o.value)).map((o) => o.label);
      handleAnswer(Array.from(selected), chosenLabels.join(", "));
    };
    optionsEl.appendChild(next);
    return;
  }
  options.forEach((opt) => {
    const btn = document.createElement("button");
    btn.className = "opt-btn";
    btn.textContent = opt.label;
    btn.onclick = () => {
      optionsEl.querySelectorAll(".opt-btn").forEach((b) => {
        b.disabled = true;
        b.classList.remove("selected");
      });
      btn.classList.add("selected");
      handleAnswer(opt.label, opt.label);
    };
    optionsEl.appendChild(btn);
  });
}

/* 숫자 입력 키 -> 단위 표시(서버 응답 필드가 아니라 화면 표시만을 위한 추정 매핑). */
const KEY_UNIT = {
  leftover_portions: "인분",
  _adspend_spend_entry: "원",
  _adspend_orders_entry: "건",
  adspend_avg_amount_won: "원",
  coupon_issued: "장",
  coupon_used: "장",
  coupon_discount_won: "원",
  coupon_avg_order_won: "원",
  survey_avg_order_won: "원",
};

function renderNumberInput(spec) {
  const unit = KEY_UNIT[spec.key] || "";
  const row = document.createElement("div");
  row.className = "input-row";

  const wrap = document.createElement("div");
  wrap.className = "number-input-wrap";
  const input = document.createElement("input");
  input.type = "text";
  input.inputMode = "numeric";
  input.placeholder = "숫자로 답해 주세요";
  wrap.appendChild(input);
  if (unit) {
    const unitEl = document.createElement("span");
    unitEl.className = "unit";
    unitEl.textContent = unit;
    wrap.appendChild(unitEl);
  }
  row.appendChild(wrap);

  const btn = document.createElement("button");
  btn.className = "next-btn";
  btn.textContent = "보내기";
  row.appendChild(btn);

  const errEl = document.createElement("div");
  errEl.className = "input-error";
  errEl.style.display = "none";

  input.addEventListener("input", () => {
    const digits = input.value.replace(/[^0-9]/g, "");
    input.value = digits ? Number(digits).toLocaleString("ko-KR") : "";
  });

  const submit = () => {
    const digits = input.value.replace(/[^0-9]/g, "");
    if (!digits) {
      errEl.textContent = "숫자를 입력해 주세요";
      errEl.style.display = "block";
      return;
    }
    handleAnswer(digits, `${Number(digits).toLocaleString("ko-KR")}${unit}`);
  };
  btn.onclick = submit;
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") submit();
  });

  optionsEl.appendChild(row);
  if (spec.skip) {
    const skipBtn = document.createElement("button");
    skipBtn.className = "opt-btn";
    skipBtn.textContent = "건너뛰기";
    skipBtn.onclick = () => handleAnswer("", "건너뛰기");
    optionsEl.appendChild(skipBtn);
  }
  optionsEl.appendChild(errEl);
  input.focus();
}

function renderTextInput() {
  const row = document.createElement("div");
  row.className = "input-row";
  const input = document.createElement("input");
  input.className = "text-input";
  input.type = "text";
  input.placeholder = "답을 입력해 주세요";
  const btn = document.createElement("button");
  btn.className = "next-btn";
  btn.textContent = "보내기";
  const submit = () => {
    const value = input.value.trim();
    if (!value) return;
    handleAnswer(value, value);
  };
  btn.onclick = submit;
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") submit();
  });
  row.appendChild(input);
  row.appendChild(btn);
  optionsEl.appendChild(row);
  input.focus();
}

/* 가게 이야기 등 자유 입력 — 여러 줄 칸 + 글자 수 + [보내기][건너뛰기]. */
function renderFreeformArea() {
  const wrap = document.createElement("div");
  wrap.className = "textarea-wrap";
  const area = document.createElement("textarea");
  area.className = "freeform-area";
  area.placeholder = "답을 입력해 주세요";

  const meta = document.createElement("div");
  meta.className = "freeform-meta";
  const count = document.createElement("span");
  count.className = "freeform-count";
  count.textContent = "0자";
  const actions = document.createElement("div");
  actions.className = "freeform-actions";
  const skipBtn = document.createElement("button");
  skipBtn.className = "opt-btn";
  skipBtn.textContent = "건너뛰기";
  const sendBtn = document.createElement("button");
  sendBtn.className = "next-btn";
  sendBtn.textContent = "보내기";
  actions.appendChild(skipBtn);
  actions.appendChild(sendBtn);
  meta.appendChild(count);
  meta.appendChild(actions);

  wrap.appendChild(area);
  wrap.appendChild(meta);

  area.addEventListener("input", () => {
    count.textContent = `${area.value.length}자`;
  });
  sendBtn.onclick = () => {
    const value = area.value.trim();
    if (!value) return;
    handleAnswer(value, value);
  };
  skipBtn.onclick = () => handleAnswer("", "건너뛰기");

  optionsEl.appendChild(wrap);
  area.focus();
}

function renderInput(spec) {
  if (spec.type === "number") {
    renderNumberInput(spec);
  } else if (spec.skip) {
    renderFreeformArea();
  } else {
    renderTextInput();
  }
}

function renderExample(text) {
  const row = document.createElement("div");
  row.className = "example-line";
  row.textContent = text;
  chatEl.appendChild(row);
}

function renderPrompt(data) {
  if (data.options && data.options.length) {
    renderOptions(data.options, data.multi);
  } else {
    clearOptions();
  }
  if (data.example) {
    renderExample(data.example);
  }
  if (data.input) {
    renderInput(data.input);
  }
  if (state && state.node === "start") renderReportEntry();
}

async function handleAnswer(answer, displayLabel) {
  addUserBubble(displayLabel);
  await runStep(answer);
}

async function runStep(answer) {
  setOptionsDisabled(true);
  const loadingRow = addLoadingBubble();
  let data;
  try {
    data = await postJSON(`${API}/step`, { state, answer });
  } catch (e) {
    loadingRow.remove();
    showRetryPrompt(() => runStep(answer));
    return;
  }
  loadingRow.remove();
  state = data.state;
  clearOptions();
  if (data.done) {
    await showDecision();
  } else {
    data.bot_messages.forEach((t) => addBotBubble(t));
    renderPrompt(data);
  }
}

function fmtWon(n) {
  return `${Number(n).toLocaleString("ko-KR")}원`;
}

function roundToStep(value, step) {
  return Math.round(value / step) * step;
}

/* ---------- 판정 배지 ---------- */

const VERDICT_BADGE = {
  "손해 광고": { cls: "bad", label: "손해 광고" },
  "주의": { cls: "warn", label: "주의" },
  "괜찮음": { cls: "good", label: "괜찮음" },
};

function worstAdspendVerdict(table) {
  const rank = { "괜찮음": 0, "주의": 1, "손해 광고": 2 };
  const judged = table.filter((r) => r.verdict);
  if (!judged.length) return null;
  return judged.reduce((a, b) => (rank[b.verdict] > rank[a.verdict] ? b : a)).verdict;
}

/* 결과 카드 머리의 판정 배지 — 서버가 이미 준 판정(verdict/usage_rate/strategy_type)만 보고 가른다. */
function badgeFor(data) {
  if (data.table) {
    const worst = worstAdspendVerdict(data.table);
    return worst ? VERDICT_BADGE[worst] : null;
  }
  if (data.strategy_type === "fix_first") {
    return { cls: "bad", label: "먼저 고치기" };
  }
  if (data.usage_rate !== undefined) {
    const rate = data.usage_rate;
    if (rate == null) return { cls: "bad", label: "점검 필요" };
    if (rate < 0.2) return { cls: "warn", label: "주의" };
    if (rate <= 0.5) return { cls: "good", label: "같은 조건 유지" };
    return { cls: "warn", label: "할인 큼" };
  }
  return { cls: "info", label: "정보" };
}

function buildBadgeEl(info) {
  const el = document.createElement("span");
  el.className = `badge ${info.cls}`;
  el.textContent = info.label;
  return el;
}

function updateBadgeEl(el, info) {
  if (!el) return;
  el.className = `badge ${info.cls}`;
  el.textContent = info.label;
}

function addApprovedBadge(head) {
  const el = document.createElement("span");
  el.className = "badge good";
  el.textContent = "승인됨";
  head.appendChild(el);
}

/* ---------- 숫자 타일 / 왜 이렇게 판단했나요 ---------- */

function buildTiles(data) {
  if (data.table) {
    const flagged = data.table.filter((r) => r.verdict && r.verdict !== "괜찮음");
    const tiles = [
      { n: `${data.table.length}개`, l: "점검한 채널" },
      { n: `${flagged.length}개`, l: "주의·손해 채널" },
    ];
    if (data.profit_per_order_won != null) {
      tiles.push({ n: fmtWon(data.profit_per_order_won), l: "건당 이익(추정)" });
    }
    return tiles;
  }
  if (data.usage_rate !== undefined) {
    const tiles = [];
    if (data.usage_rate != null) tiles.push({ n: `${Math.round(data.usage_rate * 100)}%`, l: "쿠폰 사용률" });
    if (data.issued != null && data.used != null) tiles.push({ n: `${data.issued}장 / ${data.used}장`, l: "발급 / 사용" });
    if (data.total_discount_cost_won != null) tiles.push({ n: fmtWon(data.total_discount_cost_won), l: "총 할인 비용" });
    if (data.breakeven_orders != null) tiles.push({ n: `${data.breakeven_orders}건`, l: "본전 주문 수" });
    return tiles;
  }
  if (data.coupon_card) {
    const c = data.coupon_card;
    const tiles = [{ n: fmtWon(c.discount_won), l: "할인액" }];
    if (c.count) tiles.push({ n: `${c.count}장`, l: "발급 수량" });
    if (c.breakeven_orders != null) tiles.push({ n: `${c.breakeven_orders}건`, l: "본전 주문 수" });
    return tiles;
  }
  return [];
}

function buildWhyBox(data) {
  const text = data.summary || (data.steps && data.steps.length === 1 ? data.steps[0].tip : null);
  if (!text) return null;
  const box = document.createElement("div");
  box.className = "why-box";
  box.innerHTML = `<div class="why-label">왜 이렇게 판단했나요</div><div>${escapeHtml(text)}</div>` +
    `<div class="why-source">사장님 답변과 가게 데이터 기준</div>`;
  return box;
}

/* ---------- 쿠폰 슬라이더 / 쿠폰 카드 ---------- */

/* 쿠폰 계산 슬라이더 — 월 예산·할인액 2개, 움직일 때마다 150ms 디바운스로 /coupon-calc 를 불러
   계산 결과(장수·최대 비용·본전 주문 수)를 그려 준다. 계산은 전부 서버(coupon_calc.calc), 이 함수는
   화면만 그린다. onFigures 는 할인율이 바뀔 때마다 결과를 상위(판정 배지)에 알리는 선택적 콜백이다. */
function buildCouponCalcPanel(coupon, state, onFigures) {
  const input = coupon.calc_input;
  const price = input.price_won || 0;
  const minDiscount = Math.max(100, roundToStep(price * 0.05, 100));
  const maxDiscount = Math.max(minDiscount, roundToStep(price * 0.3, 100));
  const startDiscount = Math.min(Math.max(input.discount_won, minDiscount), maxDiscount);
  const maxBudget = 300000;

  const panel = document.createElement("div");
  panel.className = "coupon-calc";
  panel.innerHTML = `
    <div class="slider-row">
      <label>월 예산 <span class="slider-val" data-k="budget">${fmtWon(input.budget_won)}</span></label>
      <input type="range" min="0" max="${maxBudget}" step="10000" value="${input.budget_won}" data-k="budget" aria-label="월 예산">
      <div class="slider-minmax"><span>0원</span><span>${fmtWon(maxBudget)}</span></div>
    </div>
    <div class="slider-row">
      <label>할인액 <span class="slider-val" data-k="discount">${fmtWon(startDiscount)}</span></label>
      <input type="range" min="${minDiscount}" max="${maxDiscount}" step="100" value="${startDiscount}" data-k="discount" aria-label="할인액">
      <div class="slider-minmax"><span>${fmtWon(minDiscount)}</span><span>${fmtWon(maxDiscount)}</span></div>
    </div>
    <div class="budget-bar"><div class="budget-bar-fill"></div></div>
    <div class="budget-bar-label"></div>
    <div class="calc-tiles">
      <div class="calc-tile"><div class="n" data-t="count"></div><div class="l">쿠폰 장수</div></div>
      <div class="calc-tile"><div class="n" data-t="cost"></div><div class="l">최대 비용</div></div>
      <div class="calc-tile"><div class="n" data-t="breakeven"></div><div class="l">본전 주문 수</div></div>
    </div>
    <div class="warn-box calc-warn" style="display:none">할인이 클수록 본전까지 더 많은 주문이 필요해요</div>
  `;
  const regenBtn = document.createElement("button");
  regenBtn.className = "btn-secondary";
  regenBtn.textContent = "이 조건으로 쿠폰 글 만들기";
  panel.appendChild(regenBtn);

  const current = { budget_won: input.budget_won, discount_won: startDiscount };
  let debounceTimer = null;

  function renderFigures(fig) {
    const pct = current.budget_won > 0 ? Math.min(100, (fig.max_cost_won / current.budget_won) * 100) : 0;
    panel.querySelector(".budget-bar-fill").style.width = `${pct}%`;
    panel.querySelector(".budget-bar-label").textContent =
      `쿠폰 비용 ${fmtWon(fig.max_cost_won)} · 남는 예산 ${fmtWon(fig.remaining_won)}`;
    panel.querySelector('[data-t="count"]').textContent = `${fig.count}장`;
    panel.querySelector('[data-t="cost"]').textContent = fmtWon(fig.max_cost_won);
    panel.querySelector('[data-t="breakeven"]').textContent =
      fig.breakeven_orders != null ? `${fig.breakeven_orders}건` : "-";
    panel.querySelector(".calc-warn").style.display = fig.discount_pct > 20 ? "block" : "none";
    if (onFigures) onFigures(fig);
  }

  async function recalc() {
    let fig;
    try {
      fig = await postJSON(`${API}/coupon-calc`, {
        budget_won: current.budget_won, discount_won: current.discount_won, price_won: price,
        avg_order_won: input.avg_order_won, margin_pct: input.margin_pct,
      });
    } catch (e) {
      return;
    }
    renderFigures(fig);
  }

  panel.querySelectorAll("input[type=range]").forEach((slider) => {
    slider.addEventListener("input", (e) => {
      const key = e.target.dataset.k === "budget" ? "budget_won" : "discount_won";
      current[key] = Number(e.target.value);
      panel.querySelector(`.slider-val[data-k="${e.target.dataset.k}"]`).textContent = fmtWon(current[key]);
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(recalc, 150);
    });
  });

  regenBtn.onclick = async () => {
    regenBtn.disabled = true;
    try {
      const g = await postJSON(`${API}/generate`, { state, coupon_override: { ...current } });
      if (g.text) panel.appendChild(buildDraftBox("coupon_regen", g.text));
    } catch (e) {
      /* 실패하면 버튼을 다시 눌러 볼 수 있게 둔다 */
    }
    regenBtn.disabled = false;
  };

  recalc();
  return panel;
}

function buildCouponCard(coupon, state, onFigures) {
  const box = document.createElement("div");
  box.className = "coupon-card";
  const rows = [
    ["혜택", `${fmtWon(coupon.discount_won)} 할인`],
    ["발급 수량", coupon.count ? `${coupon.count}장` : null],
    ["시간대", coupon.timing || null],
    ["유효기간", `발급일 포함 ${coupon.days}일`],
  ].filter(([, v]) => v != null && v !== "-");
  const kvHtml = rows.map(([k, v]) => `<span>${escapeHtml(k)}</span><span>${escapeHtml(String(v))}</span>`).join("");
  box.innerHTML = `
    <div class="cap">쿠폰 이름</div>
    <div class="title">${escapeHtml(coupon.menu || "대표 메뉴")} ${fmtWon(coupon.discount_won)} 할인</div>
    <div class="coupon-kv">${kvHtml}</div>
  `;
  if (coupon.breakeven_orders != null) {
    const tile = document.createElement("div");
    tile.className = "note-line";
    tile.textContent = `본전이 되려면 ${coupon.breakeven_orders}건이 필요해요`;
    box.appendChild(tile);
  }
  if (coupon.calc_input) {
    box.appendChild(buildCouponCalcPanel(coupon, state, onFigures));
  }
  return box;
}

/* ---------- 글 상자(모든 기능 공통) ---------- */

/* [고치기]를 누르면 textarea + [저장][취소]로 바뀐다. 저장하면 editedTexts[key] 에 고친 글을 들고
   있다가 [승인] 때 approve 요청에 실어 보낸다. 서버가 edit_failed 를 돌려주면(개인정보·보상 약속)
   빨간 안내를 보여준다. [복사]는 클립보드에 쓰고 1.5초간 "복사됨"으로 바뀐다. */
function buildDraftBox(key, text) {
  const wrap = document.createElement("div");
  wrap.className = "draft-wrap";
  wrap.dataset.key = key;

  const head = document.createElement("div");
  head.className = "draft-head";

  const badge = document.createElement("span");
  badge.className = "draft-badge";
  badge.textContent = "고친 글";
  badge.style.display = editedTexts[key] ? "inline-flex" : "none";

  const btns = document.createElement("div");
  btns.className = "draft-head-btns";
  const editBtn = document.createElement("button");
  editBtn.className = "icon-btn";
  editBtn.textContent = "고치기";
  editBtn.setAttribute("aria-label", "글 고치기");
  const copyBtn = document.createElement("button");
  copyBtn.className = "icon-btn";
  copyBtn.textContent = "복사";
  copyBtn.setAttribute("aria-label", "글 복사하기");
  btns.appendChild(editBtn);
  btns.appendChild(copyBtn);

  head.appendChild(badge);
  head.appendChild(btns);

  const box = document.createElement("div");
  box.className = "draft-box";
  box.textContent = editedTexts[key] ?? text;

  const errBox = document.createElement("div");
  errBox.className = "warn-box";
  errBox.style.display = "none";

  wrap.appendChild(head);
  wrap.appendChild(box);
  wrap.appendChild(errBox);

  wrap.showEditError = (reasons) => {
    errBox.textContent = reasons.join(", ");
    errBox.style.display = reasons.length ? "block" : "none";
  };

  copyBtn.onclick = async () => {
    try {
      await navigator.clipboard.writeText(editedTexts[key] ?? text);
      const original = copyBtn.textContent;
      copyBtn.textContent = "복사됨";
      copyBtn.disabled = true;
      setTimeout(() => {
        copyBtn.textContent = original;
        copyBtn.disabled = false;
      }, 1500);
    } catch (e) {
      /* 클립보드 권한이 없으면 조용히 무시 */
    }
  };

  editBtn.onclick = () => {
    const textarea = document.createElement("textarea");
    textarea.className = "edit-textarea";
    textarea.value = editedTexts[key] ?? box.textContent;

    const saveBtn = document.createElement("button");
    saveBtn.className = "btn-secondary";
    saveBtn.textContent = "저장";
    const cancelBtn = document.createElement("button");
    cancelBtn.className = "btn-secondary";
    cancelBtn.textContent = "취소";

    const actionsRow = document.createElement("div");
    actionsRow.className = "edit-actions";
    actionsRow.appendChild(saveBtn);
    actionsRow.appendChild(cancelBtn);

    box.replaceWith(textarea);
    wrap.insertBefore(actionsRow, errBox);
    editBtn.style.display = "none";

    saveBtn.onclick = () => {
      editedTexts[key] = textarea.value;
      box.textContent = textarea.value;
      textarea.replaceWith(box);
      actionsRow.remove();
      editBtn.style.display = "";
      badge.style.display = "inline-flex";
      errBox.style.display = "none";
    };
    cancelBtn.onclick = () => {
      textarea.replaceWith(box);
      actionsRow.remove();
      editBtn.style.display = "";
    };
  };

  return wrap;
}

/* ---------- 할 일 목록 ---------- */

function buildTodoHeader(data) {
  if (!data.steps || !data.steps.length) return null;
  const costPart = data.total_cost_krw ? ` · 추정 비용 ${fmtWon(data.total_cost_krw)}` : "";
  const head = document.createElement("div");
  head.className = "todo-head";
  head.textContent = `이번 주 할 일 ${data.steps.length}개 · 약 ${data.total_minutes}분${costPart}`;
  return head;
}

function buildTodoItem(step, index, draftText) {
  const item = document.createElement("div");
  item.className = "todo-item";
  const costHtml = step.cost_krw ? `<span class="todo-cost">${fmtWon(step.cost_krw)}</span>` : "";
  item.innerHTML = `
    <div class="todo-item-top">
      <div class="todo-num">${index + 1}</div>
      <div class="todo-title">${escapeHtml(step.what)}</div>
      <div class="todo-meta">
        <span class="todo-when">${escapeHtml(step.when)}</span>
        <span class="todo-minutes">${step.minutes}분</span>
        ${costHtml}
      </div>
    </div>
  `;
  if (step.where && step.where !== "-") {
    const where = document.createElement("div");
    where.className = "todo-where";
    where.textContent = step.where;
    item.appendChild(where);
  }
  if (draftText) {
    item.appendChild(buildDraftBox(step.step_id, draftText));
  }
  if (step.tip) {
    const tip = document.createElement("div");
    tip.className = "todo-tip";
    tip.textContent = `체크: ${step.tip}`;
    item.appendChild(tip);
  }
  return item;
}

/* 광고비 점검처럼 steps 가 없고 단순 문자열 할 일(todos)만 오는 경우 — 같은 할 일 모양을 재사용한다. */
function buildPlainTodoSection(todos, note) {
  if (!todos || !todos.length) return null;
  const wrap = document.createElement("div");
  wrap.style.display = "flex";
  wrap.style.flexDirection = "column";
  wrap.style.gap = "10px";

  const head = document.createElement("div");
  head.className = "todo-head";
  head.textContent = `할 일 ${todos.length}개`;
  wrap.appendChild(head);

  const list = document.createElement("div");
  list.className = "todo-list";
  todos.forEach((t, i) => {
    const item = document.createElement("div");
    item.className = "todo-item";
    item.innerHTML = `<div class="todo-item-top"><div class="todo-num">${i + 1}</div>` +
      `<div class="todo-title">${escapeHtml(t)}</div></div>`;
    list.appendChild(item);
  });
  wrap.appendChild(list);

  if (note) {
    const noteEl = document.createElement("div");
    noteEl.className = "note-line";
    noteEl.textContent = note;
    wrap.appendChild(noteEl);
  }
  return wrap;
}

/* ---------- 광고비 점검 — 표 + 채널별 가로 막대 ---------- */

function buildAdspendVisual(data) {
  const box = document.createElement("div");
  box.style.display = "flex";
  box.style.flexDirection = "column";
  box.style.gap = "14px";

  const scrollWrap = document.createElement("div");
  scrollWrap.className = "table-scroll";
  const table = document.createElement("table");
  table.className = "ad-table";
  const headers = ["앱", "광고비", "주문", "건당 광고비", "건당 이익", "판정"];
  table.innerHTML = `<thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>`;
  const tbody = document.createElement("tbody");
  data.table.forEach((r) => {
    const badge = r.verdict ? VERDICT_BADGE[r.verdict] : null;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(r.label)}</td>
      <td class="num">${fmtWon(r.spend_won)}</td>
      <td class="num">${r.orders}건</td>
      <td class="num">${r.cost_per_order_won == null ? "-" : fmtWon(r.cost_per_order_won)}</td>
      <td class="num">${fmtWon(r.profit_per_order_won)}</td>
      <td>${badge ? `<span class="badge ${badge.cls}">${escapeHtml(badge.label)}</span>` : "-"}</td>
    `;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  scrollWrap.appendChild(table);
  box.appendChild(scrollWrap);
  box.appendChild(buildAdspendBars(data.table));
  return box;
}

/* 채널별 가로 막대 2개(건당 광고비 / 건당 이익), 같은 눈금 — 슬라이더 없음, 서버 값만 그린다. */
function buildAdspendBars(rows) {
  const judged = rows.filter((r) => r.cost_per_order_won != null);
  const box = document.createElement("div");
  box.className = "adspend-bars";
  if (!judged.length) return box;
  const scale = Math.max(...judged.flatMap((r) => [r.cost_per_order_won, r.profit_per_order_won]), 1);

  judged.forEach((r) => {
    const cls = (VERDICT_BADGE[r.verdict] || {}).cls || "good";
    const row = document.createElement("div");
    row.className = "adspend-bar-row";
    row.innerHTML = `
      <div class="adspend-bar-label">${escapeHtml(r.label)}</div>
      <div class="adspend-bar-pair">
        <div class="adspend-bar-track">
          <div class="adspend-bar-fill ${cls}" style="width:${(r.cost_per_order_won / scale) * 100}%"></div>
        </div>
        <span class="adspend-bar-val">건당 광고비 ${fmtWon(r.cost_per_order_won)}</span>
      </div>
      <div class="adspend-bar-pair">
        <div class="adspend-bar-track">
          <div class="adspend-bar-fill profit" style="width:${(r.profit_per_order_won / scale) * 100}%"></div>
        </div>
        <span class="adspend-bar-val">건당 이익 ${fmtWon(r.profit_per_order_won)}</span>
      </div>
    `;
    box.appendChild(row);
  });
  return box;
}

/* ---------- AI 추천 아이디어 ---------- */

/* 아이디어는 목표 하나에만 배정되어 있어 [다른 아이디어 보기]도 그 목표 안에서만 순환한다
   (서버 /next-idea, 무작위 아님). 질문이 필요한 아이디어(custom_option·weekly_side·neighbor_cross)는
   바로 글을 보여주지 않고 [이 아이디어 해 보기]를 눌렀을 때만 질문을 잇는다(/idea-try) —
   "아니요"처럼 조건이 안 맞으면(skip=true) 자동으로 다음 아이디어로 넘어간다. */
function buildIdeaBox(idea, index) {
  const box = document.createElement("div");
  box.className = "idea-box";
  const nextBtn = document.createElement("button");
  nextBtn.className = "btn-secondary";
  nextBtn.textContent = "다른 아이디어 보기";

  async function goToNext() {
    try {
      const r = await postJSON(`${API}/next-idea`, { state, current_index: index });
      if (r.idea) {
        index = r.idea_index;
        render(r.idea);
      }
    } catch (e) {
      /* 실패하면 [다른 아이디어 보기]를 다시 눌러 볼 수 있게 둔다 */
    }
  }

  function askQuestion(idea, questionType, afterRow) {
    const row = document.createElement("div");
    row.className = "input-row";
    row.style.margin = "0";
    const submit = async (answer) => {
      row.remove();
      const r = await postJSON(`${API}/idea-try`, { state, idea_id: idea.id, index, answer });
      if (r.skip) {
        const note = document.createElement("div");
        note.className = "note-line";
        note.textContent = "이 아이디어는 지금은 건너뛸게요.";
        box.appendChild(note);
        await goToNext();
        return;
      }
      if (r.draft) box.appendChild(buildDraftBox(`idea_${idea.id}`, r.draft));
    };
    if (questionType === "bool") {
      ["예", "아니요"].forEach((label) => {
        const btn = document.createElement("button");
        btn.className = "opt-btn";
        btn.textContent = label;
        btn.onclick = () => submit(label);
        row.appendChild(btn);
      });
    } else {
      const input = document.createElement("input");
      input.className = "text-input";
      input.type = "text";
      const sendBtn = document.createElement("button");
      sendBtn.className = "next-btn";
      sendBtn.textContent = "보내기";
      sendBtn.onclick = () => submit(input.value.trim());
      row.appendChild(input);
      row.appendChild(sendBtn);
    }
    afterRow.appendChild(row);
  }

  function render(idea) {
    box.innerHTML = `<div class="idea-head"><span class="idea-badge">${icon("spark", 12)}AI 추천 아이디어</span></div>` +
      `<div class="idea-title">${escapeHtml(idea.title)}</div>` +
      `<div class="idea-why">${escapeHtml(idea.why)}</div>` +
      (idea.todos.length
        ? `<div class="idea-todos">${idea.todos.map((t) => `<div>· ${escapeHtml(t)}</div>`).join("")}</div>`
        : "");

    const actions = document.createElement("div");
    actions.className = "idea-actions";

    if (idea.id === "story_link") {
      const linkBtn = document.createElement("button");
      linkBtn.className = "btn-secondary";
      linkBtn.textContent = "가게 이야기 글 만들기";
      linkBtn.onclick = async () => {
        const base = await postJSON(`${API}/step`, { state: null, answer: null });
        const r = await postJSON(`${API}/step`, { state: base.state, answer: "가게 이야기 글" });
        state = r.state;
        addBotBubble(r.bot_messages[0]);
        renderPrompt(r);
      };
      actions.appendChild(linkBtn);
    } else if (idea.needs_question) {
      const tryBtn = document.createElement("button");
      tryBtn.className = "btn-secondary";
      tryBtn.textContent = "이 아이디어 해 보기";
      tryBtn.onclick = () => {
        tryBtn.remove();
        const q = document.createElement("div");
        q.className = "idea-why";
        q.textContent = idea.question;
        box.appendChild(q);
        askQuestion(idea, idea.question_type, box);
      };
      actions.appendChild(tryBtn);
    } else if (idea.draft) {
      box.appendChild(buildDraftBox(`idea_${idea.id}`, idea.draft));
    }
    actions.appendChild(nextBtn);
    box.appendChild(actions);
  }
  render(idea);

  nextBtn.onclick = async () => {
    nextBtn.disabled = true;
    await goToNext();
    nextBtn.disabled = false;
  };
  return box;
}

/* ---------- 개선 인증 소식(데모) ---------- */

/* 공지 기준일 앞뒤 14일의 같은 불만 리뷰 수를 서버(코드)가 세어 "이전 N건 -> 이후 M건" 타일을
   보여준다. 줄었을 때만 소식 글을 만든다. */
function renderNoticeFollowupDemo() {
  const row = document.createElement("div");
  row.className = "row bot";
  row.innerHTML = `<div class="icon">${icon("spark", 16)}</div>`;
  chatEl.appendChild(row);

  const btn = document.createElement("button");
  btn.className = "opt-btn";
  btn.textContent = "2주 뒤 확인해 보기";
  btn.onclick = async () => {
    btn.disabled = true;
    let f;
    try {
      f = await postJSON(`${API}/notice-followup`, { state });
    } catch (e) {
      btn.disabled = false;
      return;
    }
    const box = document.createElement("div");
    box.className = "info-card";
    box.innerHTML = `<div class="info-card-title">공지 전후 불만 리뷰 수</div>
      <div class="note-line">이전 ${f.window_days}일 ${f.before}건 → 이후 ${f.window_days}일 ${f.after}건 (${escapeHtml(f.basis)})</div>`;
    if (f.improved && f.text) {
      box.appendChild(buildDraftBox("notice_followup", f.text));
    } else if (f.todo) {
      const tip = document.createElement("div");
      tip.className = "note-line";
      tip.textContent = f.todo;
      box.appendChild(tip);
    }
    row.appendChild(box);
    btn.remove();
  };
  optionsEl.appendChild(btn);
  scrollToRow(row);
}

/* ---------- 결과 카드 ---------- */

async function showDecision() {
  setOptionsDisabled(true);
  const loadingRow = addLoadingBubble();
  let data;
  try {
    data = await postJSON(`${API}/plan`, { state });
  } catch (e) {
    loadingRow.remove();
    showRetryPrompt(() => showDecision());
    return;
  }
  loadingRow.remove();
  clearOptions();
  editedTexts = {};
  renderResultCard(data);
}

/* 사장님용 "진단 보고서" 카드 — 머리(제목+판정) → 요약 → 숫자 타일 → 왜 판단했나요 → 시각 요소
   → 할 일 → AI 추천 아이디어 → 쿠폰 카드 → 측정 줄 → 승인/다시 쓰기. 값이 없는 부분은 통째로 숨긴다. */
function renderResultCard(data) {
  sessionId = data.session_id || null;
  const row = document.createElement("div");
  row.className = "row bot";
  const card = document.createElement("div");
  card.className = "result-card";

  const head = document.createElement("div");
  head.className = "card-head";
  head.innerHTML = `<div class="head-icon">${icon("spark", 14)}</div>` +
    `<div class="head-title">${escapeHtml(data.title)}</div>`;
  const badgeInfo = badgeFor(data);
  let badgeEl = null;
  if (badgeInfo) {
    badgeEl = buildBadgeEl(badgeInfo);
    head.appendChild(badgeEl);
  }
  card.appendChild(head);

  if (data.summary) {
    const summary = document.createElement("div");
    summary.className = "card-summary";
    summary.textContent = data.summary;
    card.appendChild(summary);
  }

  const tiles = buildTiles(data);
  if (tiles.length) {
    const tileBox = document.createElement("div");
    tileBox.className = "stat-tiles";
    tiles.forEach((t) => {
      const tile = document.createElement("div");
      tile.className = "stat-tile";
      tile.innerHTML = `<div class="n">${escapeHtml(t.n)}</div><div class="l">${escapeHtml(t.l)}</div>`;
      tileBox.appendChild(tile);
    });
    card.appendChild(tileBox);
  }

  const why = buildWhyBox(data);
  if (why) card.appendChild(why);

  if (data.over_budget) {
    const warn = document.createElement("div");
    warn.className = "warn-box";
    warn.textContent = "예상 비용(추정) 합계가 설문에서 답한 예산을 넘어요.";
    card.appendChild(warn);
  }

  if (data.table && data.table.length) {
    card.appendChild(buildAdspendVisual(data));
  }

  const todoHead = buildTodoHeader(data);
  if (todoHead) {
    card.appendChild(todoHead);
    const list = document.createElement("div");
    list.className = "todo-list";
    data.steps.forEach((step, i) => {
      list.appendChild(buildTodoItem(step, i, data.drafts[step.step_id]));
    });
    card.appendChild(list);
  }
  const plainTodos = buildPlainTodoSection(data.todos, data.todo_note);
  if (plainTodos) card.appendChild(plainTodos);

  if (data.bundle) {
    const tile = document.createElement("div");
    tile.className = "note-line";
    tile.textContent = `원래 합계 ${fmtWon(data.bundle.original_won)} → 세트 가격 ${fmtWon(data.bundle.bundle_won)}`;
    card.appendChild(tile);
  }
  if (data.discount_tile) {
    const tile = document.createElement("div");
    tile.className = "note-line";
    tile.textContent = `원래 가격 ${fmtWon(data.discount_tile.original_won)} → 할인 가격 ${fmtWon(data.discount_tile.sale_won)}`;
    card.appendChild(tile);
  }

  if (data.basic_todos && data.basic_todos.length) {
    const box = document.createElement("div");
    box.className = "info-card";
    box.innerHTML = `<div class="info-card-title">기본 할 일</div>` +
      data.basic_todos.map((t) => `<div class="note-line">· ${escapeHtml(t.title)}</div>`).join("");
    data.basic_todos.forEach((t, i) => {
      if (t.draft) box.appendChild(buildDraftBox(`basic_todo_${i}`, t.draft));
    });
    card.appendChild(box);
  }

  if (data.idea) card.appendChild(buildIdeaBox(data.idea, data.idea_index ?? 0));

  if (data.coupon_card) {
    const onFigures = (badgeInfo && badgeInfo.cls === "info")
      ? (fig) => updateBadgeEl(badgeEl, fig.discount_pct > 20 ? { cls: "warn", label: "할인 큼" } : { cls: "info", label: "정보" })
      : null;
    card.appendChild(buildCouponCard(data.coupon_card, state, onFigures));
  }

  if (data.breakeven_orders != null && !data.coupon_card) {
    const tile = document.createElement("div");
    tile.className = "note-line";
    tile.textContent = `본전이 되려면 ${data.breakeven_orders}건이 필요해요`;
    card.appendChild(tile);
  }

  if (data.next_condition) {
    const cond = document.createElement("div");
    cond.className = "info-card dashed";
    const d = data.next_condition;
    cond.innerHTML = `<div class="info-card-title">다음 쿠폰 조건</div>` +
      `<div class="note-line">할인액 ${fmtWon(d.discount_won)} · ${escapeHtml(d.note)}</div>`;
    const genBtn = document.createElement("button");
    genBtn.className = "btn-secondary";
    genBtn.textContent = "이 조건으로 쿠폰 글 만들기";
    genBtn.onclick = async () => {
      genBtn.disabled = true;
      try {
        const g = await postJSON(`${API}/generate`, { state });
        if (g.text) cond.appendChild(buildDraftBox("next_coupon", g.text));
        if (g.coupon) cond.appendChild(buildCouponCard(g.coupon, state));
      } catch (e) {
        /* 실패하면 버튼을 다시 눌러 볼 수 있게 둔다 */
      }
      genBtn.disabled = false;
    };
    cond.appendChild(genBtn);
    card.appendChild(cond);
  }

  if (data.demo) {
    const tagEl = document.createElement("div");
    tagEl.className = "note-line";
    tagEl.textContent = "저장된 예시(CLOVA_API_KEY 없음)";
    card.appendChild(tagEl);
  }

  if (data.measure) {
    const measure = document.createElement("div");
    measure.className = "measure-line";
    measure.innerHTML = `${icon("clock", 14)}<span>${escapeHtml(data.measure)}</span>`;
    card.appendChild(measure);
  }

  const actions = document.createElement("div");
  actions.className = "card-actions";
  const approveBtn = document.createElement("button");
  approveBtn.className = "btn-primary";
  approveBtn.textContent = "승인";
  const rewriteBtn = document.createElement("button");
  rewriteBtn.className = "btn-secondary";
  rewriteBtn.textContent = "다시 쓰기";
  actions.appendChild(approveBtn);
  actions.appendChild(rewriteBtn);
  card.appendChild(actions);

  row.innerHTML = `<div class="icon">${icon("spark", 16)}</div>`;
  row.appendChild(card);
  chatEl.appendChild(row);

  /* 같은 state(=같은 설문 답)로 /plan 을 다시 불러 글을 새로 받는다 — 새 API 를 만들지 않는다. */
  rewriteBtn.onclick = async () => {
    actions.querySelectorAll("button").forEach((b) => (b.disabled = true));
    const loadingRow = addLoadingBubble();
    let fresh;
    try {
      fresh = await postJSON(`${API}/plan`, { state });
    } catch (e) {
      loadingRow.remove();
      actions.querySelectorAll("button").forEach((b) => (b.disabled = false));
      showRetryPrompt(() => rewriteBtn.onclick());
      return;
    }
    loadingRow.remove();
    editedTexts = {};
    renderResultCard(fresh);
  };

  let approved = false;
  const approveClick = async () => {
    actions.querySelectorAll("button").forEach((b) => (b.disabled = true));
    if (!approved) addUserBubble("승인");
    approved = true;
    const loadingRow = addLoadingBubble();
    let a;
    try {
      a = await postJSON(`${API}/approve`, { state, draft_id: null, session_id: sessionId, edited_texts: editedTexts });
    } catch (e) {
      loadingRow.remove();
      actions.querySelectorAll("button").forEach((b) => (b.disabled = false));
      showRetryPrompt(approveClick);
      return;
    }
    if (a.edit_failed) {
      loadingRow.remove();
      actions.querySelectorAll("button").forEach((b) => (b.disabled = false));
      approved = false;
      card.querySelectorAll(".draft-wrap").forEach((wrap) => {
        const reasons = a.edit_failed[wrap.dataset.key];
        if (wrap.showEditError) wrap.showEditError(reasons || []);
      });
      return;
    }
    loadingRow.remove();
    state = a.state;
    addApprovedBadge(head);
    if (a.follow_up) {
      a.bot_messages.forEach((t) => addBotBubble(t));
      renderPrompt(a);
    } else {
      addBotBubble("여기까지 도와드릴게요. 감사합니다!");
      const hasPreventionNotice = data.steps.some((s) => s.generator === "prevention_notice");
      if (hasPreventionNotice) renderNoticeFollowupDemo();
    }
  };
  approveBtn.onclick = approveClick;

  scrollToRow(row);
}

/* ---------- 마케팅 보고서 (첫 화면 보기 버튼 → 주간/월간 → 결과 카드) ---------- */

const PERIOD_LABELS = {
  weekly: { name: "주간", now: "이번 주", prev: "지난주", next: "다음 주" },
  monthly: { name: "월간", now: "이번 달", prev: "지난달", next: "다음 달" },
};

function renderReportEntry() {
  const btn = document.createElement("button");
  btn.className = "opt-btn";
  btn.textContent = "마케팅 보고서";
  btn.onclick = () => {
    optionsEl.querySelectorAll(".opt-btn").forEach((b) => {
      b.disabled = true;
      b.classList.remove("selected");
    });
    btn.classList.add("selected");
    addUserBubble("마케팅 보고서");
    addBotBubble("어느 기간을 볼까요?");
    renderPeriodChoice();
  };
  optionsEl.appendChild(btn);
}

function renderPeriodChoice() {
  clearOptions();
  ["weekly", "monthly"].forEach((kind) => {
    const btn = document.createElement("button");
    btn.className = "opt-btn";
    btn.textContent = PERIOD_LABELS[kind].name;
    btn.onclick = () => {
      addUserBubble(PERIOD_LABELS[kind].name);
      showReport(kind);
    };
    optionsEl.appendChild(btn);
  });
}

async function showReport(kind) {
  setOptionsDisabled(true);
  const loadingRow = addLoadingBubble();
  let data;
  try {
    const res = await fetch(`${API}/report?period=${kind}&store=${encodeURIComponent(selectedStore)}`);
    if (!res.ok) throw new Error(res.statusText);
    data = await res.json();
  } catch (e) {
    loadingRow.remove();
    showRetryPrompt(() => showReport(kind));
    return;
  }
  loadingRow.remove();
  renderReportCard(data);
  addBotBubble("다른 기간도 볼까요?");
  renderPeriodChoice();
}

function buildReportTiles(data, labels) {
  const tiles = [];
  const approved = data.activity ? Object.entries(data.activity.approved || {}) : [];
  if (approved.length) {
    const total = approved.reduce((sum, [, n]) => sum + n, 0);
    tiles.push({ n: `${total}건`, l: `승인한 글 (${approved.map(([k, n]) => `${k} ${n}`).join(" · ")})` });
  }
  const c = data.cost && data.cost.coupon;
  if (c) {
    if (c.usage_rate != null) tiles.push({ n: `${Math.round(c.usage_rate * 100)}%`, l: `쿠폰 사용률 (${c.issued}장 중 ${c.used}장)` });
    tiles.push({ n: fmtWon(c.discount_spent), l: "할인에 쓴 돈" });
  }
  (data.fixed || []).forEach((f) => {
    const l = f.tile_label || `${f.complaint} 불만 재발`;  // 문구는 서버(report.py)가 만든다
    tiles.push({ n: `${f.before_14d}건 → ${f.after_14d}건`, l });
  });
  return tiles;
}

/* 광고 앱별 막대 — 건당 광고비를 건당 이익과 같은 눈금으로, 옆에 "지난 판정 → 이번 판정". */
function buildReportAds(ads, labels) {
  const box = document.createElement("div");
  box.className = "adspend-bars";
  const scale = Math.max(...ads.flatMap((a) => [a.cost_per_order, a.profit_per_order || 0]), 1);
  ads.forEach((a) => {
    const cls = (VERDICT_BADGE[a.verdict] || {}).cls || "good";
    const prev = a.prev_verdict ? escapeHtml(a.prev_verdict) : "기록 없음";
    const row = document.createElement("div");
    row.className = "adspend-bar-row";
    row.innerHTML = `
      <div class="adspend-bar-label">${escapeHtml(a.label)}
        <span class="note-line">${labels.prev} ${prev} → ${labels.now} ${escapeHtml(a.verdict || "-")}</span></div>
      <div class="adspend-bar-pair">
        <div class="adspend-bar-track">
          <div class="adspend-bar-fill ${cls}" style="width:${(a.cost_per_order / scale) * 100}%"></div>
        </div>
        <span class="adspend-bar-val">건당 광고비 ${fmtWon(a.cost_per_order)}</span>
      </div>
      ${a.profit_per_order != null ? `<div class="adspend-bar-pair">
        <div class="adspend-bar-track">
          <div class="adspend-bar-fill profit" style="width:${(a.profit_per_order / scale) * 100}%"></div>
        </div>
        <span class="adspend-bar-val">건당 이익 ${fmtWon(a.profit_per_order)}</span>
      </div>` : ""}`;
    box.appendChild(row);
  });
  return box;
}

/* 결과 카드 틀(result-card · card-head · stat-tiles · info-card) 그대로. 값 없는 덩어리는 통째로 숨긴다. */
function renderReportCard(data) {
  const labels = PERIOD_LABELS[data.period.kind];
  const row = document.createElement("div");
  row.className = "row bot";
  const card = document.createElement("div");
  card.className = "result-card";

  const head = document.createElement("div");
  head.className = "card-head";
  head.innerHTML = `<div class="head-icon">${icon("spark", 14)}</div>` +
    `<div class="head-title">${labels.now} 마케팅 보고서</div>`;
  if (data.demo) {
    const demo = document.createElement("span");
    demo.className = "badge info";
    demo.textContent = "데모 기록";
    head.appendChild(demo);
  }
  card.appendChild(head);

  const range = document.createElement("div");
  range.className = "note-line";
  range.textContent = `${data.period.start} ~ ${data.period.until.slice(0, 10)}`;
  card.appendChild(range);

  const tiles = buildReportTiles(data, labels);
  if (tiles.length) {
    const tileBox = document.createElement("div");
    tileBox.className = "stat-tiles";
    tiles.forEach((t) => {
      const tile = document.createElement("div");
      tile.className = "stat-tile";
      tile.innerHTML = `<div class="n">${escapeHtml(t.n)}</div><div class="l">${escapeHtml(t.l)}</div>`;
      tileBox.appendChild(tile);
    });
    card.appendChild(tileBox);
  }

  const tried = (data.activity && data.activity.ideas_tried) || [];
  if (tried.length) {
    const box = document.createElement("div");
    box.className = "info-card";
    box.innerHTML = `<div class="info-card-title">해 본 아이디어</div>` +
      tried.map((t) => `<div class="note-line">· ${escapeHtml(t)}</div>`).join("");
    card.appendChild(box);
  }

  const ads = (data.cost && data.cost.ads) || [];
  if (ads.length) {
    const box = document.createElement("div");
    box.className = "info-card";
    box.innerHTML = `<div class="info-card-title">광고 앱별 판정 (${labels.prev} → ${labels.now})</div>`;
    box.appendChild(buildReportAds(ads, labels));
    card.appendChild(box);
  }

  const next = data.next || [];
  if (next.length) {
    const box = document.createElement("div");
    box.className = "info-card dashed";
    box.innerHTML = `<div class="info-card-title">${labels.next} 할 것</div>` +
      next.map((n) => `<div class="note-line">· <b>${escapeHtml(n.title)}</b> — ${escapeHtml(n.why)}</div>`).join("");
    card.appendChild(box);
  }

  if (!tiles.length && !tried.length && !ads.length && !next.length) {
    const empty = document.createElement("div");
    empty.className = "note-line";
    empty.textContent = "이 기간에 쌓인 기록이 아직 없어요";
    card.appendChild(empty);
  }

  row.innerHTML = `<div class="icon">${icon("spark", 16)}</div>`;
  row.appendChild(card);
  chatEl.appendChild(row);
  scrollToRow(row);
}

async function start() {
  chatEl.innerHTML = "";
  clearOptions();
  const loadingRow = addLoadingBubble();
  let data;
  try {
    data = await postJSON(`${API}/step`, { state: null, answer: null });
  } catch (e) {
    loadingRow.remove();
    showRetryPrompt(start);
    return;
  }
  loadingRow.remove();
  state = data.state;
  data.bot_messages.forEach((t) => addBotBubble(t));
  addSubtitleLine("고친 만큼, 남는 만큼만 홍보해요");
  renderPrompt(data);
}

function addSubtitleLine(text) {
  const row = document.createElement("div");
  row.className = "subtitle-line";
  row.textContent = text;
  chatEl.appendChild(row);
}

restartBtn.onclick = () => start();

fetch(`${API}/stores`)
  .then((r) => r.json())
  .then((d) => renderStorePicker(d.stores))
  .catch(() => {});

start();
