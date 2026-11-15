/* 설문 맞춤 마케팅 — 프레임워크 없는 바닐라 JS. 상태는 이 변수(state)만 들고 다니며
   매 요청마다 서버로 그대로 보낸다(서버는 아무것도 저장하지 않는다). */

const API = "/api/marketing-survey";
const chatEl = document.getElementById("chat");
const optionsEl = document.getElementById("options");
const storeNameEl = document.getElementById("store-name");
const restartBtn = document.getElementById("restart-btn");

let state = null;

/* 11/3 "마케팅 비서" 시안(build.py)의 아이콘 — 꼭 쓰는 것만 가져온다 */
const ICON_PATHS = {
  spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
  home: '<path d="M3 9l9-6 9 6v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/><path d="M9 21V12h6v9"/>',
  cal: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  ticket: '<path d="M3 8a2 2 0 0 0 2-2h14a2 2 0 0 0 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 0-2 2H5a2 2 0 0 0-2-2v-2a2 2 0 0 0 0-4z"/>',
  check: '<path d="M9 11l3 3 8-8"/><path d="M20 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
};

function icon(name, size = 16) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
    `stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICON_PATHS[name]}</svg>`;
}

/* 전략 종류 -> 카드 머리말 아이콘·색(초록/주황). fix_first 는 운영 조치가 먼저라 주황(o)으로 구분한다 */
function tagForStrategy(type) {
  if (type === "fix_first") return { name: "check", cls: "o" };
  if (["leftover_deal", "reorder_coupon", "offpeak_coupon"].includes(type)) return { name: "ticket", cls: "g" };
  if (type === "review_promo") return { name: "cal", cls: "g" };
  return { name: "home", cls: "g" };
}

async function postJSON(url, body) {
  const res = await fetch(url, {
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
    `<div class="bubble bot loading">제안을 만들고 있어요<span class="dots"><span>.</span><span>.</span><span>.</span></span></div>`;
  chatEl.appendChild(row);
  chatEl.scrollTop = chatEl.scrollHeight;
  return row;
}

function showRetryPrompt(onRetry) {
  clearOptions();
  const row = document.createElement("div");
  row.className = "row bot";
  row.innerHTML = `<div class="icon">${icon("spark", 16)}</div><div class="bubble bot">잠시 후 다시 눌러 주세요</div>`;
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
  chatEl.scrollTop = chatEl.scrollHeight;
}

function addBotBubble(text) {
  const row = document.createElement("div");
  row.className = "row bot";
  row.innerHTML = `<div class="icon">${icon("spark", 16)}</div><div class="bubble bot"></div>`;
  row.querySelector(".bubble").textContent = text;
  chatEl.appendChild(row);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function addUserBubble(text) {
  const row = document.createElement("div");
  row.className = "row user";
  row.innerHTML = `<div class="bubble user"></div>`;
  row.querySelector(".bubble").textContent = text;
  chatEl.appendChild(row);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function clearOptions() {
  optionsEl.innerHTML = "";
}

function renderOptions(options, multi) {
  clearOptions();
  if (multi) {
    const selected = new Set();
    options.forEach((opt) => {
      const btn = document.createElement("button");
      btn.className = "opt-btn";
      btn.textContent = opt.label;
      btn.onclick = () => {
        if (selected.has(opt.value)) {
          selected.delete(opt.value);
          btn.classList.remove("selected");
        } else {
          selected.add(opt.value);
          btn.classList.add("selected");
        }
      };
      optionsEl.appendChild(btn);
    });
    const next = document.createElement("button");
    next.className = "next-btn";
    next.textContent = "다음";
    next.onclick = () => {
      const chosenLabels = options.filter((o) => selected.has(o.value)).map((o) => o.label);
      handleAnswer(Array.from(selected), chosenLabels.length ? chosenLabels.join(", ") : "(선택 안 함)");
    };
    optionsEl.appendChild(next);
    return;
  }
  options.forEach((opt) => {
    const btn = document.createElement("button");
    btn.className = "opt-btn";
    btn.textContent = opt.label;
    btn.onclick = () => handleAnswer(opt.label, opt.label);
    optionsEl.appendChild(btn);
  });
}

/* free_input 노드(숫자/텍스트 직접 입력) — 버튼 대신 입력칸 + [보내기]를 보인다.
   suggest_menu 로 보기 버튼도 같이 오면 renderPrompt 가 버튼 먼저 그리고 이 입력칸을 이어 붙인다. */
function renderInput(spec) {
  const row = document.createElement("div");
  row.className = "input-row";
  const input = document.createElement("input");
  input.className = "text-input";
  input.type = spec.type === "number" ? "number" : "text";
  input.placeholder = spec.type === "number" ? "숫자로 답해 주세요" : "답을 입력해 주세요";
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

function renderPrompt(data) {
  if (data.options && data.options.length) {
    renderOptions(data.options, data.multi);
  } else {
    clearOptions();
  }
  if (data.input) {
    renderInput(data.input);
  }
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
    data.bot_messages.forEach(addBotBubble);
    renderPrompt(data);
  }
}

function fmtWon(n) {
  return `${Number(n).toLocaleString("ko-KR")}원`;
}

function roundToStep(value, step) {
  return Math.round(value / step) * step;
}

/* 쿠폰 계산 슬라이더 — 월 예산·할인액 2개, 움직일 때마다 150ms 디바운스로 /coupon-calc 를 불러
   계산 결과(장수·최대 비용·본전 주문 수)를 그려 준다. 계산은 전부 서버(coupon_calc.calc), 이 함수는
   화면만 그린다. */
function buildCouponCalcPanel(coupon, state) {
  const input = coupon.calc_input;
  const price = input.price_won || 0;
  const minDiscount = Math.max(100, roundToStep(price * 0.05, 100));
  const maxDiscount = Math.max(minDiscount, roundToStep(price * 0.3, 100));
  const startDiscount = Math.min(Math.max(input.discount_won, minDiscount), maxDiscount);

  const panel = document.createElement("div");
  panel.className = "coupon-calc";
  panel.innerHTML = `
    <div class="slider-row">
      <label>월 예산 <span class="slider-val" data-k="budget">${fmtWon(input.budget_won)}</span></label>
      <input type="range" min="0" max="300000" step="10000" value="${input.budget_won}" data-k="budget">
    </div>
    <div class="slider-row">
      <label>할인액 <span class="slider-val" data-k="discount">${fmtWon(startDiscount)}</span></label>
      <input type="range" min="${minDiscount}" max="${maxDiscount}" step="100" value="${startDiscount}" data-k="discount">
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
      if (g.text) {
        const box = document.createElement("div");
        box.className = "draft-box";
        box.textContent = g.text;
        panel.appendChild(box);
      }
    } catch (e) {
      /* 실패하면 버튼을 다시 눌러 볼 수 있게 둔다 */
    }
    regenBtn.disabled = false;
  };

  recalc();
  return panel;
}

function buildCouponCard(coupon, state) {
  const box = document.createElement("div");
  box.className = "coupon-card";
  box.innerHTML = `
    <div class="cap">쿠폰 이름</div>
    <div class="title">${coupon.menu || "대표 메뉴"} ${fmtWon(coupon.discount_won)} 할인</div>
    <div class="kv">
      <span>혜택</span><span>${fmtWon(coupon.discount_won)} 할인</span>
      <span>발급 수량</span><span>${coupon.count ? `${coupon.count}장` : "-"}</span>
      <span>시간대</span><span>${coupon.timing || "-"}</span>
      <span>유효기간</span><span>발급일 포함 ${coupon.days}일</span>
    </div>
  `;
  if (coupon.breakeven_orders != null) {
    const tile = document.createElement("div");
    tile.className = "basis";
    tile.textContent = `본전이 되려면 ${coupon.breakeven_orders}건이 필요해요`;
    box.appendChild(tile);
  }
  if (coupon.calc_input) {
    box.appendChild(buildCouponCalcPanel(coupon, state));
  }
  return box;
}

function buildStepCard(step, index, draftText) {
  const el = document.createElement("div");
  el.className = "step-card";
  const whereHtml = step.where && step.where !== "-" ? ` <span class="where-text">· ${step.where}</span>` : "";
  el.innerHTML = `
    <div class="step-head">${index + 1}. ${step.what}</div>
    <div class="step-meta">${step.when}${whereHtml}</div>
  `;
  if (draftText) {
    const box = document.createElement("div");
    box.className = "draft-box";
    box.textContent = draftText;
    el.appendChild(box);

    const copyBtn = document.createElement("button");
    copyBtn.className = "btn-secondary";
    copyBtn.textContent = "복사하기";
    copyBtn.onclick = async () => {
      try {
        await navigator.clipboard.writeText(draftText);
      } catch (e) {
        /* 클립보드 권한이 없으면 조용히 무시 */
      }
    };
    el.appendChild(copyBtn);
  }
  if (step.cost_krw) {
    const cost = document.createElement("div");
    cost.className = "basis";
    cost.textContent = `비용(추정): ${fmtWon(step.cost_krw)}`;
    el.appendChild(cost);
  }
  if (step.tip) {
    const tip = document.createElement("div");
    tip.className = "basis";
    tip.textContent = `체크: ${step.tip}`;
    el.appendChild(tip);
  }
  return el;
}

/* 광고비 점검 전용 — 채널별 표(광고비·주문 수·건당 광고비·건당 이익·판정 배지) */
function buildAdspendTable(data) {
  const box = document.createElement("div");

  if (data.summary) {
    const summary = document.createElement("div");
    summary.className = "why-box";
    summary.textContent = data.summary;
    box.appendChild(summary);
  }

  const wrap = document.createElement("div");
  wrap.className = "kv";
  wrap.style.gridTemplateColumns = "repeat(5, 1fr)";
  const headers = ["채널", "광고비", "주문 수", "건당 광고비", "판정"];
  headers.forEach((h) => {
    const span = document.createElement("span");
    span.style.fontWeight = "700";
    span.textContent = h;
    wrap.appendChild(span);
  });
  data.table.forEach((r) => {
    wrap.appendChild(Object.assign(document.createElement("span"), { textContent: r.label }));
    wrap.appendChild(Object.assign(document.createElement("span"), { textContent: fmtWon(r.spend_won) }));
    wrap.appendChild(Object.assign(document.createElement("span"), { textContent: `${r.orders}건` }));
    wrap.appendChild(Object.assign(document.createElement("span"), {
      textContent: r.cost_per_order_won == null ? "-" : fmtWon(r.cost_per_order_won),
    }));
    wrap.appendChild(Object.assign(document.createElement("span"), { textContent: r.verdict || "-" }));
  });
  box.appendChild(wrap);

  const note = document.createElement("div");
  note.className = "basis";
  note.textContent = `건당 이익(추정): ${fmtWon(data.profit_per_order_won)} ` +
    `(평균 주문 금액 ${fmtWon(data.avg_order_won)} x 남는 비율 ${data.margin_pct}%)`;
  box.appendChild(note);

  if (data.todos && data.todos.length) {
    const todos = document.createElement("div");
    todos.className = "basis";
    todos.textContent = `할 일: ${data.todos.join(", ")}` + (data.todo_note ? ` (${data.todo_note})` : "");
    box.appendChild(todos);
  }

  box.appendChild(buildAdspendBars(data.table));
  return box;
}

const VERDICT_CLASS = { "손해 광고": "bad", "주의": "warn", "괜찮음": "good" };

/* 채널별 가로 막대 2개(건당 광고비 / 건당 이익), 같은 눈금 — 슬라이더 없음, 서버 값만 그린다. */
function buildAdspendBars(rows) {
  const judged = rows.filter((r) => r.cost_per_order_won != null);
  const box = document.createElement("div");
  box.className = "adspend-bars";
  if (!judged.length) return box;
  const scale = Math.max(...judged.flatMap((r) => [r.cost_per_order_won, r.profit_per_order_won]), 1);

  judged.forEach((r) => {
    const cls = VERDICT_CLASS[r.verdict] || "good";
    const row = document.createElement("div");
    row.className = "adspend-bar-row";
    row.innerHTML = `
      <div class="adspend-bar-label">${r.label}</div>
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
  const tag = tagForStrategy(data.strategy_type || "");

  const row = document.createElement("div");
  row.className = "row bot";
  const card = document.createElement("div");
  card.className = "card";

  const costLine = data.total_cost_krw
    ? ` · 예상 비용(추정) 합계 ${fmtWon(data.total_cost_krw)}`
    : "";
  card.innerHTML = `<div class="tag ${tag.cls}"><i>${icon(tag.name, 14)}</i>${data.title}</div>
    <div class="sub">이번 주 할 일 ${data.steps.length}개 · 총 약 ${data.total_minutes}분${costLine}</div>`;

  if (data.over_budget) {
    const warn = document.createElement("div");
    warn.className = "warn-box";
    warn.textContent = "예상 비용(추정) 합계가 설문에서 답한 예산을 넘어요.";
    card.appendChild(warn);
  }

  if (data.table) {
    card.appendChild(buildAdspendTable(data));
  }

  data.steps.forEach((step, i) => {
    card.appendChild(buildStepCard(step, i, data.drafts[step.step_id]));
  });

  const hasPreventionNotice = data.steps.some((s) => s.generator === "prevention_notice");

  if (data.bundle) {
    const tile = document.createElement("div");
    tile.className = "basis";
    tile.textContent = `원래 합계 ${fmtWon(data.bundle.original_won)} → 세트 가격 ${fmtWon(data.bundle.bundle_won)}`;
    card.appendChild(tile);
  }

  if (data.coupon_card) card.appendChild(buildCouponCard(data.coupon_card, state));

  if (data.breakeven_orders != null) {
    const tile = document.createElement("div");
    tile.className = "basis";
    tile.textContent = `본전이 되려면 ${data.breakeven_orders}건이 필요해요`;
    card.appendChild(tile);
  }

  if (data.next_condition) {
    const cond = document.createElement("div");
    cond.className = "step-card";
    cond.style.borderStyle = "dashed";
    const d = data.next_condition;
    cond.innerHTML = `<div class="step-head">다음 쿠폰 조건</div>
      <div class="step-meta">할인액 ${fmtWon(d.discount_won)} · ${d.note}</div>`;
    const genBtn = document.createElement("button");
    genBtn.className = "btn-secondary";
    genBtn.textContent = "이 조건으로 쿠폰 글 만들기";
    genBtn.onclick = async () => {
      genBtn.disabled = true;
      try {
        const g = await postJSON(`${API}/generate`, { state });
        if (g.text) {
          const box = document.createElement("div");
          box.className = "draft-box";
          box.textContent = g.text;
          cond.appendChild(box);
        }
        if (g.coupon) cond.appendChild(buildCouponCard(g.coupon));
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
    tagEl.className = "basis";
    tagEl.textContent = "저장된 예시(CLOVA_API_KEY 없음)";
    card.appendChild(tagEl);
  }

  const measure = document.createElement("div");
  measure.className = "why-box";
  measure.textContent = data.measure;
  card.appendChild(measure);

  const actions = document.createElement("div");
  actions.className = "draft-actions";
  actions.innerHTML = `<button class="btn-primary" data-act="approve">승인</button>`;
  card.appendChild(actions);

  row.innerHTML = `<div class="icon">${icon("spark", 16)}</div>`;
  row.appendChild(card);
  chatEl.appendChild(row);

  let approved = false;
  const approveClick = async () => {
    actions.querySelectorAll("button").forEach((b) => (b.disabled = true));
    if (!approved) addUserBubble("승인");
    approved = true;
    const loadingRow = addLoadingBubble();
    let a;
    try {
      a = await postJSON(`${API}/approve`, { state, draft_id: null });
    } catch (e) {
      loadingRow.remove();
      actions.querySelectorAll("button").forEach((b) => (b.disabled = false));
      showRetryPrompt(approveClick);
      return;
    }
    loadingRow.remove();
    state = a.state;
    if (a.follow_up) {
      a.bot_messages.forEach(addBotBubble);
      renderPrompt(a);
    } else {
      addBotBubble("여기까지 도와드릴게요. 감사합니다!");
      if (hasPreventionNotice) renderNoticeFollowupDemo();
    }
  };
  actions.querySelector('[data-act="approve"]').onclick = approveClick;

  /* 개선 인증 소식(데모) — 공지 기준일 앞뒤 14일의 같은 불만 리뷰 수를 서버(코드)가 세어
     "이전 N건 -> 이후 M건" 타일을 보여준다. 줄었을 때만 소식 글을 만든다. */
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
      box.className = "step-card";
      box.innerHTML = `<div class="step-head">공지 전후 불만 리뷰 수</div>
        <div class="step-meta">이전 ${f.window_days}일 ${f.before}건 → 이후 ${f.window_days}일 ${f.after}건 (${f.basis})</div>`;
      if (f.improved && f.text) {
        const draft = document.createElement("div");
        draft.className = "draft-box";
        draft.textContent = f.text;
        box.appendChild(draft);
      } else if (f.todo) {
        const tip = document.createElement("div");
        tip.className = "basis";
        tip.textContent = f.todo;
        box.appendChild(tip);
      }
      row.appendChild(box);
      btn.remove();
    };
    optionsEl.appendChild(btn);
  }

  chatEl.scrollTop = chatEl.scrollHeight;
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
  data.bot_messages.forEach(addBotBubble);
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

fetch(`${API}/meta`)
  .then((r) => r.json())
  .then((m) => {
    storeNameEl.innerHTML = `예시 가게 <span class="pill">${m.store_name}</span>`;
  })
  .catch(() => {});

start();
