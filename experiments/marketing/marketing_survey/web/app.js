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

async function handleAnswer(answer, displayLabel) {
  addUserBubble(displayLabel);
  clearOptions();
  const data = await postJSON(`${API}/step`, { state, answer });
  state = data.state;
  if (data.done) {
    await showDecision();
  } else {
    data.bot_messages.forEach(addBotBubble);
    renderOptions(data.options, data.multi);
  }
}

function fmtWon(n) {
  return `${Number(n).toLocaleString("ko-KR")}원`;
}

function buildCouponCard(coupon) {
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
  return box;
}

function buildStepCard(step, index, draftText) {
  const el = document.createElement("div");
  el.className = "step-card";
  el.innerHTML = `
    <div class="step-head">${index + 1}. ${step.what}</div>
    <div class="step-meta">${step.when} <span class="where-text">· ${step.where}</span></div>
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
  if (step.tip) {
    const tip = document.createElement("div");
    tip.className = "basis";
    tip.textContent = `체크: ${step.tip}`;
    el.appendChild(tip);
  }
  return el;
}

async function showDecision() {
  const data = await postJSON(`${API}/plan`, { state });
  const tag = tagForStrategy(data.strategy_type || "");

  const row = document.createElement("div");
  row.className = "row bot";
  const card = document.createElement("div");
  card.className = "card";

  card.innerHTML = `<div class="tag ${tag.cls}"><i>${icon(tag.name, 14)}</i>${data.title}</div>
    <div class="sub">이번 주 할 일 ${data.steps.length}개 · 총 약 ${data.total_minutes}분</div>`;

  data.steps.forEach((step, i) => {
    card.appendChild(buildStepCard(step, i, data.drafts[step.step_id]));
  });

  if (data.coupon_card) card.appendChild(buildCouponCard(data.coupon_card));
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

  actions.querySelector('[data-act="approve"]').onclick = async () => {
    actions.querySelectorAll("button").forEach((b) => (b.disabled = true));
    addUserBubble("승인");
    const a = await postJSON(`${API}/approve`, { state, draft_id: null });
    state = a.state;
    if (a.follow_up) {
      a.bot_messages.forEach(addBotBubble);
      renderOptions(a.options, a.multi);
    } else {
      addBotBubble("여기까지 도와드릴게요. 감사합니다!");
    }
  };

  chatEl.scrollTop = chatEl.scrollHeight;
}

async function start() {
  chatEl.innerHTML = "";
  clearOptions();
  const data = await postJSON(`${API}/step`, { state: null, answer: null });
  state = data.state;
  data.bot_messages.forEach(addBotBubble);
  renderOptions(data.options, data.multi);
}

restartBtn.onclick = () => start();

fetch(`${API}/meta`)
  .then((r) => r.json())
  .then((m) => {
    storeNameEl.innerHTML = `예시 가게 <span class="pill">${m.store_name}</span>`;
  })
  .catch(() => {});

start();
