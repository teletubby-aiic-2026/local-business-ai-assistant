"""상권 서랍 다듬기(11/16) 검증 — 화면 파일(index.html · app.js · style.css)을 글자로 읽어 확인한다. 서버·브라우저를 띄우지 않는다.

지키는 것
- 서랍 부제와 첫 안내에 역할('동네 상권·업종 매출 상담')이 적혀 있고, 가게 기본 정보도 답한다고 알려 준다.
- '우리 가게 조건으로' 버튼: 서버가 준 conditions.is_store_default 가 true 이면 '우리 가게 기준 적용 중'(누를 수 없음),
  아니면 '우리 가게 조건으로'. 같은지는 화면이 따로 계산하지 않는다.
- 분기 표시 함수(chatQuarter): 서버(assistant_proxy.QUARTER_IN_TEXT)와 같은 정규식이고, 서버가 준 글자를 넣는 자리마다 쓴다.
  node 가 있으면 실제로 돌려서 서버 함수와 결과가 같은지도 본다 (없으면 그 시험만 건너뜀).

실행 (services/web 에서): PYTHONPATH=<저장소 루트> python -m pytest -q tests/test_assistant_ux_static.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest

from web import assistant_proxy as ap

from tests.test_assistant_drawer_static import CSS, JS, drawer_html, drawer_js
from tests.test_assistant_ux import QUARTER_CHANGED, QUARTER_UNCHANGED


def js_function(name: str) -> str:
    """서랍 JS 에서 function name(...) { ... } 한 덩어리 (다음 최상위 선언 앞까지)."""
    js = drawer_js()
    start = js.index(f"function {name}(")
    end = re.search(r"\n(?:async )?function |\n// |\nconst ", js[start + 1:])
    return js[start:start + 1 + end.start()] if end else js[start:]


class Role(unittest.TestCase):
    def test_subtitle_says_what_the_drawer_is_for(self):
        sub = re.search(r'<p class="drawer-sub">([^<]*)</p>', drawer_html())
        self.assertIsNotNone(sub)
        self.assertTrue(sub.group(1).startswith("동네 상권·업종 매출 상담"))      # 좁은 서랍에서 뒤가 잘려도 역할은 보인다

    def test_welcome_says_the_role_and_that_store_basics_are_answered(self):
        welcome = re.search(r'<div id="assistant-welcome"[\s\S]*?</div>', drawer_html()).group(0)
        text = re.sub(r"<[^>]+>", "", welcome)
        self.assertIn("동네 상권·업종 매출 상담", text)
        self.assertIn("가게 이름·메뉴 같은 기본 정보", text)
        self.assertIn("리뷰·답글을 어디서 보는지", text)
        self.assertIn("우리 가게 매출이 아니에요", text)                         # 원래 있던 주의 문장은 그대로


class HomeButton(unittest.TestCase):
    def test_markup_keeps_the_id_and_the_first_label(self):
        self.assertRegex(drawer_html(), r'<button id="assistant-home" type="button" class="ghost">우리 가게 조건으로</button>')

    def test_two_labels(self):
        body = js_function("chatHomeButton")
        self.assertIn('chat.atHome ? "우리 가게 기준 적용 중" : "우리 가게 조건으로"', body)
        self.assertIn('classList.toggle("on", chat.atHome)', body)
        self.assertIn("b.disabled = chat.atHome || !chat.ready || chat.busy", body)

    def test_the_screen_only_trusts_the_server_flag(self):
        body = js_function("chatConditions")
        self.assertIn("chat.atHome = !!c && c.is_store_default === true", body)   # true 일 때만. 없거나 false 이면 누를 수 있다
        self.assertIn("chatHomeButton()", body)
        js = re.sub(r"//[^\n]*", "", drawer_js())                                # 주석 속 설명 글자는 빼고 본다
        self.assertEqual(js.count("is_store_default"), 1)                         # 읽는 곳은 chatConditions 한 곳
        for code in ("area_code", "industry_code", "STORE_DEFAULTS", "3110826", "CS100001"):
            self.assertNotIn(code, js)                                            # 조건을 화면에서 비교하지 않는다

    def test_disabled_while_applied_or_busy(self):
        self.assertIn('$("assistant-home").disabled = off || chat.atHome;', js_function("chatInput"))

    def test_pressing_it_still_goes_through_setup_force(self):
        body = js_function("chatHome")
        self.assertIn('drawerApi("/api/assistant/setup?force=1", { method: "POST" })', body)
        self.assertIn('if (s && "conditions" in s) chatConditions(s.conditions)', body)
        self.assertNotIn('b.textContent = "우리 가게 조건으로"', body)            # 글자는 chatHomeButton 한 곳에서만 정한다
        self.assertIn("setTimeout(chatHomeButton, 2000)", body)

    def test_applied_state_looks_like_a_status_not_a_broken_button(self):
        rule = re.search(r"#assistant-home\.on, #assistant-home\.on:hover \{([^}]*)\}", CSS)
        self.assertIsNotNone(rule)
        for part in ("opacity: 1", "cursor: default", "text-decoration: none"):
            self.assertIn(part, rule.group(1))


class QuarterOnScreen(unittest.TestCase):
    def source(self) -> str:
        found = re.search(r"^const CHAT_QUARTER = /(.+)/g;$", JS, re.M)
        self.assertIsNotNone(found, "app.js 에 const CHAT_QUARTER = /…/g; 가 없음")
        return found.group(1)

    def test_same_pattern_as_the_server(self):
        self.assertEqual(self.source(), ap.QUARTER_IN_TEXT.pattern)

    def test_pattern_runs_on_older_browsers(self):
        source = self.source()
        self.assertNotIn("(?<", source)      # 뒤돌아보기(lookbehind)는 예전 Safari 에서 파일 전체가 안 읽힌다. 앞 글자를 묶음으로 잡는다
        self.assertNotIn("/", source)

    def test_replacement_matches_the_server(self):
        self.assertIn("t.replace(CHAT_QUARTER, (_, pre, y, q, n) => `${pre}${y}년 ${q || n}분기`)", drawer_js())
        self.assertIn("/^[0-9]{4}[1-4]$/.test(p)", drawer_js())                  # 조건 줄: 칸 전체가 코드일 때 (서버 QUARTER_CODE)
        self.assertEqual(ap.QUARTER_CODE.pattern, "[0-9]{4}[1-4]")

    def test_used_wherever_server_text_is_shown(self):
        js = drawer_js()
        for where in ("chatPeriod(c)].filter(Boolean)",                          # 조건 줄
                      "c.period_label || c.period",                              # 이름이 없으면 코드로
                      "into.append(chatQuarter(line.slice(last, m.index)))",     # 답 문장
                      "into.append(chatQuarter(line.slice(last)))",
                      'mk("button", "pick", chatQuarter(a.label))',              # 선택지 글자 (payload 는 그대로 보냄)
                      'mk("li", "", chatQuarter(n))',                            # 자료 기준 안내
                      'mk("p", "ev-text", chatQuarter(c.text))',                 # 근거 카드
                      'mk("li", "", chatQuarter(w))',
                      ".map(chatQuarter).slice(0, 3)",                           # 이어서 물어보기
                      "선택: ${chatQuarter(picked.label)}", "선택: ${chatQuarter(action.label)}"):
            self.assertIn(where, js)
        self.assertIn("JSON.stringify(action.payload ?? {})", js)                # 선택지는 받은 값 그대로 보낸다

    @unittest.skipUnless(shutil.which("node"), "node 가 없어 화면 함수를 실제로 돌려 보지 못함")
    def test_runs_like_the_server_function(self):
        js = drawer_js()
        lines = [line for line in js.split("\n") if line.startswith(("const CHAT_QUARTER", "const chatQuarter", "const chatPeriod"))]
        self.assertEqual(len(lines), 3)
        texts = [raw for raw, _ in QUARTER_CHANGED] + QUARTER_UNCHANGED
        fields = ["20262", "19994", "2026년 2분기", "20262 기준", "20265"]
        script = "\n".join(lines) + f"""
const texts = {json.dumps(texts, ensure_ascii=False)}, fields = {json.dumps(fields, ensure_ascii=False)};
console.log(JSON.stringify({{ texts: texts.map(chatQuarter), twice: texts.map(chatQuarter).map(chatQuarter),
  fields: fields.map((p) => chatPeriod({{ period_label: p }})), fromCode: chatPeriod({{ period_label: null, period: "20261" }}),
  other: [chatQuarter(null), chatQuarter(20262)] }}));
"""
        out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, timeout=30).stdout)
        self.assertEqual(out["texts"], [ap.quarter_words(t) for t in texts])
        self.assertEqual(out["twice"], out["texts"])                             # 서버가 이미 바꾼 글자를 또 바꾸지 않는다
        self.assertEqual(out["fields"], [ap.period_words(p) for p in fields])
        self.assertEqual(out["fromCode"], "2026년 1분기")
        self.assertEqual(out["other"], [None, 20262])


if __name__ == "__main__":
    unittest.main()
