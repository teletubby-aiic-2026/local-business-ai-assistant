"use strict";

// Pure helpers. Exported for Node tests; the page uses them through AssistantUI.
const AssistantUI = (() => {
  const TOPIC_LABELS = {
    conditions: "분석 조건", sales_total: "추정매출", sales_weekday: "요일별 매출", sales_time: "시간대별 매출",
    sales_age: "연령별 매출", stores_count: "점포 수", stores_open_close: "개업·폐업", population: "유동인구",
    change_qoq: "전분기 대비", change_yoy: "전년 동분기 대비", comparison: "상권 비교", ranking: "매출 상위 상권",
  };
  const STATUS_LABELS = {
    available: "", no_data: "자료 없음", not_collected: "미수집", invalid: "형식 확인 필요", error: "불러오기 실패",
    partial: "일부만 확인", missing: "자료 없음", no_observation: "관측 없음",
  };
  const CITATION = /\[(F\d+)\]/g;

  // "매출은 1,000원입니다. [F2]" -> [{type:"text", value:"매출은 1,000원입니다. "}, {type:"cite", id:"F2"}]
  function parseLine(line) {
    const parts = [];
    let last = 0;
    for (const match of String(line).matchAll(CITATION)) {
      if (match.index > last) parts.push({ type: "text", value: line.slice(last, match.index) });
      parts.push({ type: "cite", id: match[1] });
      last = match.index + match[0].length;
    }
    if (last < line.length) parts.push({ type: "text", value: line.slice(last) });
    return parts;
  }

  function classifyLine(line) {
    const text = String(line);
    if (text.startsWith("- ")) return { kind: "bullet", body: text.slice(2) };
    if (text.startsWith("참고:")) return { kind: "note", body: text };
    if (text.startsWith("해석:")) return { kind: "insight", body: text };
    if (text.startsWith("다음으로 ")) return { kind: "suggest", body: text };
    return { kind: "text", body: text };
  }

  function safeUrl(value) {
    if (typeof value !== "string") return null;
    try {
      const url = new URL(value);
      return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
    } catch { return null; }
  }

  function formatValue(value, unit) {
    if (value === null || value === undefined) return "확인 불가";
    if (typeof value === "number") {
      // Rates always show two decimals, matching the card sentences (20.00%).
      const text = Number.isInteger(value) && unit !== "%" ? value.toLocaleString("ko-KR")
        : value.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      return unit ? `${text}${unit}` : text;
    }
    return String(value);
  }

  function conditionsText(conditions) {
    if (!conditions) return null;
    const area = conditions.area_name ? `${conditions.area_name} 상권` : null;
    return [area, conditions.industry_name, conditions.period_label].filter(Boolean).join(" · ") || null;
  }

  function newMessageId() {
    const random = typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    return `web-${random}`;
  }

  return { TOPIC_LABELS, STATUS_LABELS, parseLine, classifyLine, safeUrl, formatValue, conditionsText, newMessageId };
})();

if (typeof module !== "undefined" && module.exports) module.exports = AssistantUI;

if (typeof document !== "undefined") (() => {
  const byId = (id) => document.getElementById(id);
  const nodes = {
    messages: byId("messages"), welcome: byId("welcome"), typing: byId("typing"), error: byId("chat-error"),
    form: byId("composer"), input: byId("message-input"), send: byId("send-button"), clear: byId("clear-button"),
    cards: byId("cards"), empty: byId("evidence-empty"), count: byId("evidence-count"), panel: byId("evidence-panel"),
    conditions: byId("conditions-value"), starters: byId("starters"),
  };
  const state = { busy: false, cards: new Map(), clearArmed: null };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

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
      else if (Array.isArray(result.detail)) message = "입력 내용을 확인해 주세요.";
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return result;
  }

  function scrollToEnd() { nodes.messages.scrollTop = nodes.messages.scrollHeight; }

  function hideWelcome() { if (nodes.welcome) nodes.welcome.hidden = true; }

  function appendLine(container, line) {
    for (const part of AssistantUI.parseLine(line)) {
      if (part.type === "text") container.append(part.value);
      else {
        const cite = el("button", "cite", part.id);
        cite.type = "button";
        cite.setAttribute("aria-label", `근거 ${part.id} 보기`);
        cite.addEventListener("click", () => showCard(part.id));
        container.append(cite);
      }
    }
  }

  function renderUser(text) {
    hideWelcome();
    const wrap = el("div", "message user");
    wrap.append(el("div", "bubble", text));
    nodes.messages.append(wrap);
    scrollToEnd();
  }

  function renderSystem(text) {
    const wrap = el("div", "message bot system");
    wrap.append(el("div", "bubble", text));
    nodes.messages.append(wrap);
    scrollToEnd();
  }

  function renderBot(data, { interactive = true } = {}) {
    hideWelcome();
    const reply = data.reply || {};
    const wrap = el("div", "message bot");
    const bubble = el("div", "bubble");
    let list = null;
    for (const line of String(reply.text || "").split("\n")) {
      const { kind, body } = AssistantUI.classifyLine(line);
      if (kind === "bullet") {
        if (!list) { list = el("ul"); bubble.append(list); }
        const item = el("li");
        appendLine(item, body);
        list.append(item);
        continue;
      }
      list = null;
      const paragraph = el("p", ["note", "suggest", "insight"].includes(kind) ? kind : "");
      appendLine(paragraph, body);
      bubble.append(paragraph);
    }
    wrap.append(bubble);
    const actions = Array.isArray(reply.actions) ? reply.actions : [];
    if (actions.length) {
      const group = el("div", "actions");
      group.setAttribute("role", "group");
      group.setAttribute("aria-label", "선택지");
      for (const action of actions) {
        const button = el("button", "action", action.label);
        button.type = "button";
        button.disabled = !interactive;
        button.addEventListener("click", () => choose(group, button, action));
        group.append(button);
      }
      wrap.append(group);
    }
    // Card warnings stay available but folded, so they do not repeat inside every message.
    const notes = Array.isArray(reply.notes) ? reply.notes.filter((note) => typeof note === "string" && note) : [];
    if (notes.length) {
      const details = el("details", "notes");
      details.append(el("summary", "", "자료 기준 안내"));
      const list = el("ul");
      for (const note of notes) list.append(el("li", "", note));
      details.append(list);
      wrap.append(details);
    }
    // Next questions as buttons that send the question, only on the latest message.
    const suggestions = Array.isArray(reply.suggestions)
      ? reply.suggestions.filter((item) => typeof item === "string" && item) : [];
    if (suggestions.length && interactive) {
      const group = el("div", "suggestions");
      group.setAttribute("role", "group");
      group.setAttribute("aria-label", "이어서 물어볼 만한 질문");
      for (const question of suggestions.slice(0, 3)) {
        const button = el("button", "suggestion", question);
        button.type = "button";
        button.addEventListener("click", () => { group.remove(); send(question); });
        group.append(button);
      }
      wrap.append(group);
    }
    nodes.messages.append(wrap);
    scrollToEnd();
  }

  function renderCards(cards) {
    if (!Array.isArray(cards) || !cards.length) return;
    state.cards = new Map(cards.map((card) => [card.id, card]));
    const items = cards.map((card) => {
      const item = el("li", "card");
      item.id = `card-${card.id}`;
      item.tabIndex = -1;
      const head = el("div", "card-head");
      head.append(el("span", "card-id", card.id), el("span", "card-topic", AssistantUI.TOPIC_LABELS[card.topic] || card.topic));
      const status = AssistantUI.STATUS_LABELS[card.status];
      if (status) head.append(el("span", "card-status", status));
      item.append(head, el("p", "card-text", card.text));
      const numeric = (card.values || []).filter((value) => typeof value.value === "number");
      if (numeric.length) {
        const table = el("table", "card-values");
        const body = el("tbody");
        for (const value of numeric.slice(0, 12)) {
          const row = el("tr");
          const label = value.group ? `${value.group} ${value.label}` : value.label;
          row.append(el("th", "", label), el("td", "", AssistantUI.formatValue(value.value, value.unit)));
          row.append(el("td", "share", typeof value.share_percent === "number" ? AssistantUI.formatValue(value.share_percent, "%") : ""));
          body.append(row);
        }
        table.append(body);
        item.append(table);
      }
      if (Array.isArray(card.warnings) && card.warnings.length) {
        const warnings = el("ul", "card-warnings");
        for (const warning of card.warnings) warnings.append(el("li", "", warning));
        item.append(warnings);
      }
      const source = card.source_ref || {};
      if (source.source_title || source.data_version) {
        const line = el("p", "card-source");
        const href = AssistantUI.safeUrl(source.source_url);
        if (href && source.source_title) {
          const link = el("a", "", source.source_title);
          link.href = href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          line.append("출처: ", link);
        } else if (source.source_title) line.append(`출처: ${source.source_title}`);
        if (source.data_version) line.append(` · 자료 버전 ${source.data_version}`);
        item.append(line);
      }
      return item;
    });
    nodes.cards.replaceChildren(...items);
    nodes.empty.hidden = true;
    nodes.count.textContent = `${cards.length}개`;
  }

  function showCard(id) {
    const card = document.getElementById(`card-${id}`);
    if (!card) return;
    nodes.panel.open = true;
    for (const item of nodes.cards.children) item.classList.toggle("highlight", item === card);
    card.scrollIntoView({ behavior: "smooth", block: "nearest" });
    card.focus({ preventScroll: true });
  }

  function updateConditions(conditions) {
    const text = AssistantUI.conditionsText(conditions);
    nodes.conditions.textContent = text || "아직 정하지 않았어요";
    nodes.conditions.classList.toggle("empty", !text);
  }

  function setBusy(busy) {
    state.busy = busy;
    nodes.send.disabled = busy;
    nodes.typing.hidden = !busy;
    if (busy) nodes.error.hidden = true;
  }

  function showError(message) {
    nodes.error.textContent = message;
    nodes.error.hidden = false;
  }

  function apply(data) {
    renderBot(data);
    renderCards(data.cards);
    if ("conditions" in data) updateConditions(data.conditions);
  }

  async function send(text) {
    const value = String(text || "").trim();
    if (!value || state.busy) return;
    for (const old of nodes.messages.querySelectorAll(".suggestions")) old.remove();  // only the latest set stays
    renderUser(value);
    nodes.input.value = "";
    resizeInput();
    setBusy(true);
    try {
      apply(await api("/api/assistant/messages", {
        method: "POST", body: JSON.stringify({ text: value, client_message_id: AssistantUI.newMessageId() }),
      }));
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(false);
      nodes.input.focus();
    }
  }

  async function choose(group, button, action) {
    if (state.busy) return;
    for (const other of group.children) other.disabled = true;
    button.classList.add("chosen");
    renderUser(`선택: ${action.label}`);
    setBusy(true);
    try {
      apply(await api("/api/assistant/actions", { method: "POST", body: JSON.stringify(action.payload) }));
    } catch (error) {
      for (const other of group.children) other.disabled = false;
      button.classList.remove("chosen");
      showError(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function loadHistory() {
    try {
      const data = await api("/api/assistant/conversation");
      updateConditions(data.conditions);
      const turns = Array.isArray(data.turns) ? data.turns : [];
      turns.forEach((turn, index) => {
        if (turn.user_text) renderUser(turn.user_text);
        else if (turn.action) renderUser("선택했어요");
        renderBot({ reply: turn.reply || {}, cards: turn.cards || [] }, { interactive: index === turns.length - 1 });
      });
      const withCards = [...turns].reverse().find((turn) => Array.isArray(turn.cards) && turn.cards.length);
      if (withCards) renderCards(withCards.cards);
    } catch (error) {
      showError(error.status === 404 ? "상권 비서 기능이 꺼져 있어요." : error.message);
    }
  }

  async function clearConversation() {
    if (!state.clearArmed) {
      nodes.clear.textContent = "한 번 더 누르면 지워요";
      state.clearArmed = setTimeout(() => { nodes.clear.textContent = "대화 지우기"; state.clearArmed = null; }, 4000);
      return;
    }
    clearTimeout(state.clearArmed);
    state.clearArmed = null;
    nodes.clear.textContent = "대화 지우기";
    try {
      await api("/api/assistant/conversation", { method: "DELETE" });
      nodes.messages.replaceChildren(nodes.welcome);
      nodes.welcome.hidden = false;
      nodes.cards.replaceChildren();
      nodes.empty.hidden = false;
      nodes.count.textContent = "";
      state.cards = new Map();
    } catch (error) {
      showError(error.message);
    }
  }

  function resizeInput() {
    nodes.input.style.height = "auto";
    nodes.input.style.height = `${Math.min(nodes.input.scrollHeight, 160)}px`;
  }

  nodes.form.addEventListener("submit", (event) => { event.preventDefault(); send(nodes.input.value); });
  nodes.input.addEventListener("keydown", (event) => {
    // Korean IME: Enter while composing confirms the syllable, it must not send.
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
      event.preventDefault();
      send(nodes.input.value);
    }
  });
  nodes.input.addEventListener("input", resizeInput);
  nodes.clear.addEventListener("click", clearConversation);
  // Development only: the server says whether the Markdown export is available (export.py).
  api("/api/assistant/status").then((status) => {
    const link = byId("export-link");
    if (link && status && status.export === true) link.hidden = false;
  }).catch(() => {});
  for (const starter of nodes.starters.querySelectorAll("button[data-text]")) {
    starter.addEventListener("click", () => send(starter.getAttribute("data-text")));
  }
  loadHistory();
})();
