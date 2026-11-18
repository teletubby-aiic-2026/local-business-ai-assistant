"""5차 회의(11/18) 화면: 로그인·가게 고르기, 상권 분석(#/market), AI 직원 네 명, 서랍 버튼으로 화면 이동. 화면 파일을 글자로 읽는다.

node 가 있으면 작은 순수 함수(chatNavTarget·marketScope·wonShort)를 실제로 돌려 본다 (없으면 그 한 건만 건너뜀).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from web.assistant_proxy import MKT_SUBS

STATIC = Path(__file__).resolve().parents[1] / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")


def block(start: str, end: str) -> str:
    i = JS.index(start)
    return JS[i:JS.index(end, i)]


AUTH = block("// ── 로그인·가게 바꾸기 (5차 회의 11/18)", "// ── AI 직원 (5차 회의 11/18)")
STAFF = block("// ── AI 직원 (5차 회의 11/18)", "// ── 화면 이동 (서랍 버튼·AI 직원, 11/18)")
NAV = block("// ── 화면 이동 (서랍 버튼·AI 직원, 11/18)", "// ── 상권 분석 (#/market, 5차 회의 11/18)")
MARKET = block("// ── 상권 분석 (#/market, 5차 회의 11/18)", "// ── 시작 ")


def code(js: str) -> str:
    return re.sub(r"//[^\n]*", "", js)


def func(name: str) -> str:
    i = JS.index(f"function {name}(")
    j = JS.find("\nfunction ", i + 1)
    k = JS.find("\nasync function ", i + 1)
    ends = [x for x in (j, k, JS.find("\nconst ", i + 1)) if x > 0]
    return JS[i:min(ends)]


class MarketScreen(unittest.TestCase):
    def test_menu_view_and_route(self):
        self.assertEqual(HTML.count('<a href="#/market" data-route="market">'), 1)
        self.assertEqual(HTML.count('<section class="view market" data-view="market" hidden>'), 1)
        menu = HTML[HTML.index('<div class="menu">'):HTML.index("</div>", HTML.index('<div class="menu">'))]
        self.assertLess(menu.index('data-route="report"'), menu.index('data-route="market"'))   # 종합 리포트 다음
        self.assertIn('"market", ...LATER', JS)
        self.assertIn('if (name === "market") mkvOpen();', JS)

    def test_four_parts_of_the_screen(self):
        view = HTML[HTML.index('data-view="market"'):HTML.index("</section>\n  </main>")]
        for id_ in ("mk-area", "mk-industry", "mk-period", "mk-apply", "mk-home", "mk-ask",          # ① 조건 바
                    "mk-sync", "mk-data", "mk-sync-result", "mk-events",                             # ② 서울시 최신화·문화행사
                    "mk-t-sales", "mk-t-yoy", "mk-t-stores", "mk-t-pop",                              # ③ 핵심 지표 4칸
                    "mk-tab-sales", "mk-tab-stores", "mk-tab-pop", "mk-tab-compare"):                # ④ 세부 탭 4개
            self.assertIn(f'id="{id_}"', view)
        for label in ("우리 가게 기준으로", "서울시 최신 데이터 확인·동기화", "우리 동네 실시간 문화행사", "매출(시간대·요일·연령)",
                      "점포·개폐업", "유동·배후인구·집객시설", "타 상권 1:1 비교"):
            self.assertIn(label, view)
        self.assertEqual(view.count('role="tab"'), 4)
        self.assertEqual(view.count('role="tabpanel"'), 4)

    def test_calls_only_the_market_proxy_through_marketapi(self):
        js = code(MARKET)
        self.assertIn('fetch("/api/market/" + path', js)
        self.assertEqual(js.count("fetch("), 1)
        paths = set(re.findall(r"""marketApi\(\s*[`"']([a-z-]+)""", js))
        self.assertEqual(paths - {"status", "setup", "analysis-options", "options", "analysis-selection", "profile", "comparison-options",
                                  "comparison", "data-sync", "cultural-events"}, set())
        for p in ("status", "setup", "analysis-options", "data-sync", "cultural-events", "comparison-options", "comparison"):
            self.assertIn(p, paths)
        for p in ('"sales"', '"stores"', '"population"', '"area-context"', '"changes"'):
            self.assertIn(p, js)
        self.assertIsNone(re.search(r"(?<![\w.])api\(", js), "전역 api() 대신 marketApi")
        for banned in ("showAlert", "careApi(", "drawerApi(", "mktApi(", "is_store_default"):
            self.assertNotIn(banned, js)

    def test_server_text_is_escaped_and_links_open_safely(self):
        self.assertNotRegex(code(MARKET), r"innerHTML = [^`'\"]*\$\{(?!esc\()")
        self.assertIn('target="_blank" rel="noopener"', MARKET)
        self.assertIn("chatUrl(ev.link)", MARKET)                          # http·https 만
        for name in ("mkvRender", "mkvCompare", "mkvEvents", "mkvSelects"):
            self.assertNotIn("${ev.title}", func(name))

    def test_tabs_keyboard_and_conflict_reload(self):
        keys = func("mkvTabKey")
        for k in ("ArrowRight", "ArrowLeft", "Home", "End"):
            self.assertIn(k, keys)
        self.assertIn("tab.tabIndex = on ? 0 : -1;", func("mkvTab"))
        self.assertIn("r.reason.status === 409", func("mkvLoad"))           # 다른 화면에서 조건이 바뀌면 서버 조건으로 다시

    def test_tables_scroll_inside_and_no_new_color_tokens(self):
        css = CSS[CSS.index("/* ── 상권 분석 (#/market, 11/18)"):CSS.index("/* ── 바닥")]
        self.assertIn(".mk-table-wrap { overflow-x: auto;", css)
        self.assertNotRegex(re.sub(r"/\*[\s\S]*?\*/", "", css), r"--[\w-]+\s*:")
        self.assertNotRegex(css, r"#[0-9a-fA-F]{3,6}\b")


class Account(unittest.TestCase):
    def test_controls_next_to_ask_ai(self):
        top = HTML[HTML.index('<div class="top-right">'):HTML.index('id="ask-ai"')]
        for id_ in ("acct-guest", "acct-login", "acct-user", "acct-store", "acct-logout"):
            self.assertIn(f'id="{id_}"', top)
        self.assertIn("게스트 체험", top)

    def test_dialog_with_one_click_demo(self):
        dialog = HTML[HTML.index('<dialog id="auth-dialog"'):HTML.index("</dialog>")]
        self.assertIn("시연 다점포 사장님으로 1초 시작", dialog)
        self.assertIn('autocomplete="current-password"', dialog)
        self.assertIn('autocomplete="new-password"', dialog)
        self.assertEqual(dialog.count("data-auth-store"), 3)
        self.assertIn("showModal", AUTH)

    def test_auth_calls_and_store_change_reloads_every_screen(self):
        paths = set(re.findall(r"""api\(\s*"/api/auth/([a-z-]+)""", AUTH)) | set(re.findall(r'authDo\("([a-z-]+)"', JS))
        self.assertEqual(paths, {"me", "logout", "store", "login", "signup", "demo-login"})
        changed = func("storeChanged")
        for call in ("mktReset()", "mkvReset()", "chatReset()", "await refresh()", "rp.loadedAt = 0", "state.approved.clear()",
                     "staffMarket()", "route()"):
            self.assertIn(call, changed)
        self.assertIn('$(id).value = ""', AUTH)                           # 비밀번호 칸은 보낸 뒤 비운다
        self.assertNotIn("localStorage", AUTH)
        self.assertNotIn("document.cookie", JS)                           # 세션은 HttpOnly 쿠키, JS 가 만지지 않음

    def test_chat_reset_is_inside_the_drawer_block(self):
        drawer = block("// ── AI에게 묻기 서랍", "// 상단 바 높이")
        self.assertIn("function chatReset()", drawer)
        self.assertIn('if (!$("assistant").hidden) { chat.started = true; chatStart(); }', drawer)


class Staff(unittest.TestCase):
    def test_four_clickable_staff(self):
        staff = HTML[HTML.index('<ul class="plain" id="staff">'):HTML.index("</ul>", HTML.index('id="staff"'))]
        self.assertEqual(staff.count('<button type="button" class="staff-go" data-staff-go='), 4)
        for key, name in (("data", "데이터 분석 비서"), ("care", "고객 응대 비서"), ("mkt", "마케팅 에이전트"), ("market", "상권 분석 비서")):
            self.assertIn(f'data-staff-go="{key}"', staff)
            self.assertIn(name, staff)
            self.assertIn(f'id="staff-{key}"', staff)
            self.assertIn(f'id="dot-{key}"', staff)

    def test_status_reads_every_part(self):
        body = func("renderStaff")
        for text in ("새로 붙인 리뷰", "답글 안 단 불만", "맞춤 마케팅 승인", "상권 자료"):
            self.assertIn(text, body)
        self.assertIn('startsWith("mkt-")', STAFF)                         # 서버에 남은 맞춤 마케팅 승인 (marketing_proxy 의 글 id)
        self.assertIn("syncStaffStrip()", body)
        go = func("staffGo")
        for route in ('"analysis"', '"draft"', '"cards"', '"marketing"', '"market"'):
            self.assertIn(route, go)
        self.assertIn("renderStaff(items)", func("renderDash"))


class Navigation(unittest.TestCase):
    def test_marketing_modes_match_the_server(self):
        subs = dict(re.findall(r'(\w+): "([^"]+)"', JS[JS.index("const MKT_SUB = {"):JS.index("};", JS.index("const MKT_SUB = {"))]))
        self.assertEqual(subs, MKT_SUBS)
        modes = JS[JS.index("const MKT_MODES = {"):JS.index("};", JS.index("const MKT_MODES = {"))]
        for label in MKT_SUBS.values():
            self.assertIn(f'"{label}"', modes)                               # 맞춤 마케팅 화면의 시작 모드 이름 그대로

    def test_nav_handles_tabs_and_modes(self):
        body = func("navTo")
        self.assertIn("ROUTES.includes(name)", body)
        self.assertIn("showTab(sub, true)", body)
        self.assertIn("mktJump(MKT_SUB[sub])", body)
        self.assertIn("mkvTab(sub, true)", body)
        self.assertIn("mktAnswer(label, label)", NAV)

    def test_placeholder(self):
        self.assertIn('"상권·리뷰·마케팅 무엇이든 물어보세요"', JS)


@unittest.skipUnless(shutil.which("node"), "node 없음")
class PureFunctionsWithNode(unittest.TestCase):
    def run_js(self, names: list[str], expr: str):
        src = "\n".join(func(n) if f"function {n}(" in JS else re.search(rf"const {n} = .*?;\n", JS, re.S).group(0) for n in names)
        out = subprocess.run(["node", "-e", f"{src}\nconsole.log(JSON.stringify({expr}));"], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_nav_target(self):
        got = self.run_js(["chatNavTarget"], '[chatNavTarget({payload:{type:"navigate",route:"analysis",sub:"paste"}}),'
                                             'chatNavTarget({payload:{type:"handoff",domain:"marketing"}}),'
                                             'chatNavTarget({payload:{type:"area",area_code:"1"}}), chatNavTarget({})]')
        self.assertEqual(got, [{"route": "analysis", "sub": "paste"}, {"route": "marketing", "sub": None}, None, None])

    def test_scope_and_money(self):
        got = self.run_js(["marketScope", "wonShort"],
                          '[marketScope({metric_name:"저녁 시간대(17~24시) 추정매출 전년 동기 대비 변화율 · 두 분기 공통 업종"}),'
                          'marketScope({metric_name:"저녁 시간대(17~24시) 추정매출 전년 동기 대비 변화율 · 치킨전문점"}),'
                          'wonShort(1840429687), wonShort(86966795), wonShort(5000)]')
        self.assertEqual(got, ["공통 업종 17~24시", "치킨전문점 17~24시", "18억 4,043만 원", "8,697만 원", "5,000원"])


if __name__ == "__main__":
    unittest.main()
