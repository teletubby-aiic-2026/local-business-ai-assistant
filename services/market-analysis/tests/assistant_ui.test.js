"use strict";

// Assistant page checks without a browser: pure helpers, required page ids, and
// no HTML injection. Visual layout is checked separately in a real browser.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const staticPath = path.join(__dirname, "../app/static/assistant");
const html = fs.readFileSync(path.join(staticPath, "index.html"), "utf8");
const source = fs.readFileSync(path.join(staticPath, "assistant.js"), "utf8");
const UI = require(path.join(staticPath, "assistant.js"));

test("citations are split out of answer lines", () => {
  assert.deepEqual(UI.parseLine("매출은 1,000원입니다. [F2]"), [
    { type: "text", value: "매출은 1,000원입니다. " }, { type: "cite", id: "F2" }]);
  assert.deepEqual(UI.parseLine("[F1][F3] 끝"), [
    { type: "cite", id: "F1" }, { type: "cite", id: "F3" }, { type: "text", value: " 끝" }]);
  assert.deepEqual(UI.parseLine("근거 없음"), [{ type: "text", value: "근거 없음" }]);
  assert.deepEqual(UI.parseLine("[X1] 은 근거가 아님"), [{ type: "text", value: "[X1] 은 근거가 아님" }]);
});

test("answer lines are grouped into bullets, notes and suggestions", () => {
  assert.equal(UI.classifyLine("- 점포 [F4]").kind, "bullet");
  assert.equal(UI.classifyLine("- 점포 [F4]").body, "점포 [F4]");
  assert.equal(UI.classifyLine("참고: 개별 가게 매출이 아닙니다.").kind, "note");
  assert.equal(UI.classifyLine("다음으로 '주말 매출은?'처럼").kind, "suggest");
  assert.equal(UI.classifyLine("해석: 직장인 손님이 많을 수 있어요.").kind, "insight");
  assert.equal(UI.classifyLine("분석 조건은 ...").kind, "text");
});

test("only http and https source links are rendered", () => {
  assert.equal(UI.safeUrl("https://data.seoul.go.kr/x"), "https://data.seoul.go.kr/x");
  assert.equal(UI.safeUrl("http://example.test/a"), "http://example.test/a");
  assert.equal(UI.safeUrl("javascript:alert(1)"), null);
  assert.equal(UI.safeUrl("data:text/html,hi"), null);
  assert.equal(UI.safeUrl("not a url"), null);
  assert.equal(UI.safeUrl(null), null);
});

test("values keep their unit and missing values are not shown as zero", () => {
  assert.equal(UI.formatValue(1234567, "원"), "1,234,567원");
  assert.equal(UI.formatValue(12.5, "%"), "12.50%");
  assert.equal(UI.formatValue(10, "%"), "10.00%");
  assert.equal(UI.formatValue(0, "개"), "0개");
  assert.equal(UI.formatValue(null, "원"), "확인 불가");
  assert.equal(UI.formatValue("합정역", null), "합정역");
});

test("conditions line and message ids", () => {
  assert.equal(UI.conditionsText({ area_name: "합정역", industry_name: "커피-음료", period_label: "2026년 2분기" }),
    "합정역 상권 · 커피-음료 · 2026년 2분기");
  assert.equal(UI.conditionsText(null), null);
  const first = UI.newMessageId();
  assert.match(first, /^web-[A-Za-z0-9-]+$/);
  assert.notEqual(first, UI.newMessageId());
  for (const topic of ["conditions", "sales_total", "sales_weekday", "sales_time", "sales_age", "stores_count",
    "stores_open_close", "population", "change_qoq", "change_yoy", "comparison"]) {
    assert.ok(UI.TOPIC_LABELS[topic], topic);
  }
});

test("page has every element the script needs and loads only local assets", () => {
  for (const id of ["messages", "welcome", "typing", "chat-error", "composer", "message-input", "send-button",
    "clear-button", "cards", "evidence-empty", "evidence-count", "evidence-panel", "conditions-value", "starters"]) {
    assert.match(html, new RegExp(`id="${id}"`), id);
    assert.match(source, new RegExp(`"${id}"`), id);
  }
  assert.doesNotMatch(html, /<script(?![^>]*src="\/assistant-assets\/assistant\.js")/);
  assert.doesNotMatch(html, /\son[a-z]+=/i, "no inline event handlers");
  assert.doesNotMatch(html, /https?:\/\//, "no external assets");
  assert.match(html, /maxlength="1000"/, "same limit as the API");
});

test("script never injects HTML or evaluates text", () => {
  for (const pattern of [/innerHTML/, /outerHTML/, /insertAdjacentHTML/, /document\.write/, /\beval\(/, /new Function/]) {
    assert.doesNotMatch(source, pattern, String(pattern));
  }
  assert.match(source, /isComposing/, "Korean IME Enter must not send");
  assert.match(source, /credentials: "same-origin"/);
});

test("warnings are folded and the answer label is gone (user feedback 2026-11-08)", () => {
  assert.match(source, /el\("details", "notes"\)/, "card warnings render folded under the message");
  assert.match(source, /el\("button", "suggestion", question\)/, "next questions render as buttons");
  assert.doesNotMatch(source, /자료 카드 기반/, "no '자료 카드 기반 · AI 문장' label");
});
