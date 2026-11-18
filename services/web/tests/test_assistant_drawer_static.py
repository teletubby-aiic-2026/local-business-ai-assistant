"""'AI에게 묻기' 서랍(상권 채팅) 화면 파일을 글자로 읽어 확인하는 정적 시험. 서버·브라우저를 띄우지 않는다.

지키는 것
- 서랍의 id 는 assistant- 로 시작하고, 서랍 JS 가 찾는 id 는 모두 index.html 에 있다.
- 서랍은 /api/assistant/* 만 부르고, 서랍 전용 drawerApi 로만 부른다 (전역 api()·#alert 를 쓰지 않음 → 오류는 서랍 안에만).
- 같은 출처 쿠키, 90초에 끊기, 한글 입력 중 Enter 막기, 1000자 제한, 서버 글은 textContent 로만.
- 처음 추천 질문 4개 (11/15 실제 상권 서버로 확인한 문구).

실행 (services/web 에서): PYTHONPATH=<저장소 루트> python -m pytest -q tests/test_assistant_drawer_static.py
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")


def drawer_html() -> str:
    m = re.search(r'<aside id="assistant"[\s\S]*?</aside>', HTML)
    assert m, "index.html 에 <aside id=\"assistant\"> 서랍이 없음"
    return m.group(0)


def drawer_js() -> str:
    """app.js 의 서랍 덩어리: '── AI에게 묻기 서랍' 머리부터 '// 상단 바 높이' 앞까지."""
    start = JS.index("// ── AI에게 묻기 서랍")
    end = JS.index("// 상단 바 높이", start)
    return JS[start:end]


class DrawerMarkup(unittest.TestCase):
    def test_drawer_ids_use_the_prefix(self):
        ids = re.findall(r'id="([\w-]+)"', drawer_html())
        self.assertIn("assistant", ids)
        self.assertEqual([i for i in ids if i != "assistant" and not i.startswith("assistant-")], [])

    def test_ids_the_contract_keeps(self):
        html = drawer_html()
        for i in ("assistant-title", "assistant-close", "assistant-chips", "assistant-log", "assistant-q"):
            self.assertIn(f'id="{i}"', html)
        self.assertIn('aria-labelledby="assistant-title"', html)
        self.assertIn('<label for="assistant-q"', html)

    def test_every_drawer_id_the_script_uses_is_in_the_html(self):
        used = set(re.findall(r"""\$\(\s*["'](assistant[\w-]*)["']\s*\)""", JS))
        self.assertTrue(used)
        made = set(re.findall(r'id="([\w-]+)"', HTML))
        self.assertEqual(sorted(used - made), [])

    def test_question_box(self):
        box = re.search(r"<textarea[^>]*id=\"assistant-q\"[^>]*>", drawer_html())
        self.assertIsNotNone(box, "질문 칸은 textarea")
        self.assertIn('maxlength="1000"', box.group(0))
        self.assertIn('id="assistant-send"', drawer_html())

    def test_status_and_error_places(self):
        html = drawer_html()
        self.assertRegex(html, r'id="assistant-status"[^>]*role="status"')
        self.assertRegex(html, r'id="assistant-error"[^>]*role="alert"')
        self.assertRegex(html, r'id="assistant-log"[^>]*role="log"')

    def test_hidden_rule_kept(self):
        self.assertIn("[hidden] { display: none !important; }", CSS)


class DrawerScript(unittest.TestCase):
    def test_calls_only_the_assistant_paths(self):
        paths = re.findall(r"""drawerApi\(\s*["'`]([^"'`]+)""", JS)
        self.assertTrue(paths)
        self.assertTrue(all(p.startswith("/api/assistant/") for p in paths), paths)
        for p in ("/api/assistant/status", "/api/assistant/conversation", "/api/assistant/setup",
                  "/api/assistant/setup?force=1", "/api/assistant/messages", "/api/assistant/actions"):
            self.assertIn(p, paths)

    def test_drawer_never_uses_the_page_alert_or_global_api(self):
        js = re.sub(r"//[^\n]*", "", drawer_js())                # 주석 속 설명 글자는 빼고 본다
        self.assertIsNone(re.search(r"(?<![\w.])api\(", js), "서랍은 전역 api() 대신 drawerApi 로만 부른다")
        self.assertNotIn("showAlert", js)
        self.assertNotIn('$("alert")', js)
        self.assertNotIn("innerHTML", js)                      # 서버 글은 textContent 로만

    def test_fetch_options(self):
        js = drawer_js()
        self.assertIn('credentials: "same-origin"', js)
        self.assertIn("AbortController", js)
        self.assertIn("CHAT_WAIT_MS = 90000", js)
        self.assertIn("답이 늦어지고 있어요. 잠시 뒤 다시 물어봐 주세요", js)

    def test_korean_ime_enter_does_not_send(self):
        self.assertIn("isComposing", JS)
        self.assertIn("keyCode !== 229", JS)

    def test_starts_only_when_opened(self):
        self.assertIn("if (!chat.started) { chat.started = true; chatStart(); }", JS)
        boot = JS[JS.index("async function boot()"):JS.index("applyTheme();")]
        self.assertNotIn("chatStart", boot)
        self.assertNotIn("/api/assistant", boot)

    def test_first_suggestions(self):
        # 5차 회의(11/18): 상권 질문 3개 + 전 파트 질문 3개(불만 리뷰·쿠폰 손익·남은 재료)
        for q in ("우리 가게 상권 매출은 어때?", "주변에 같은 업종 점포는 몇 개야?", "점심과 저녁 중 매출은 어디가 커?",
                  "불만 리뷰 제일 많은 게 뭐야?", "쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?", "남은 재료 묶어서 팔고 싶어"):
            self.assertIn(f'"{q}"', JS)

    def test_navigate_buttons_move_without_calling_the_market_service(self):
        """11/18: 답의 navigate·handoff 버튼은 /api/assistant/actions 로 보내지 않고 navTo 로 화면을 바꾼다. 덮는 폭이면 서랍을 닫는다."""
        js = drawer_js()
        body = js[js.index("async function chatChoose("):js.index("// 대화 지우기")]
        self.assertLess(body.index("chatNavTarget(action)"), body.index('"/api/assistant/actions"'))
        self.assertIn("navTo(target.route, target.sub)", body)
        self.assertIn('toggleAssistant(false)', body)
        nav = js[js.index("function chatNavTarget("):js.index("async function chatChoose(")]
        self.assertIn('p.type === "navigate"', nav)
        self.assertIn('p.type === "handoff"', nav)

    def test_unsafe_source_links_are_dropped(self):
        self.assertIn('u.protocol === "https:" || u.protocol === "http:"', drawer_js())


if __name__ == "__main__":
    unittest.main()
