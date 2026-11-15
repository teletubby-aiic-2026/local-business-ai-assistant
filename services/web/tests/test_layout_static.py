"""화면 뼈대(왼쪽 메뉴 접기 · 서랍 배치 · main 컨테이너 규칙)를 화면 파일의 글자로 확인하는 정적 시험. 서버·브라우저를 띄우지 않는다.

지키는 것 (docs/api/contract.md 2.9 '왼쪽 메뉴 접기와 폭 기준')
- 상단 바에 메뉴 토글 버튼(#menu-toggle): aria-controls 가 왼쪽 메뉴(#side-menu)를 가리키고, aria-expanded·aria-label 을 JS 가 상태에 맞춘다.
- 접힘 상태는 <html data-menu="open|closed"> 하나로만 알리고 localStorage("ic26.menu")에 기억한다. localStorage 는 늘 try/catch 안에서만 쓴다.
- 폭 기준: 760px 이하(가로 메뉴·시트, 토글 없음) / 761~1024px(메뉴는 접힌 채 시작, 펼치면 덮음) / 1025px 이상(고정 메뉴, 접으면 본문이 넓어짐).
- 서랍은 본문이 680px 이상 남을 때만 본문을 민다: 1280px 이상, 또는 1025~1279px 에서 메뉴를 접었을 때. 1279px 이하의 나머지는 본문 위에 덮인다.
- 토글 버튼·덮는 메뉴·배경 규칙은 인쇄에 섞이지 않게 screen 으로 묶는다 (토글 버튼은 screen 761px 이상에서만 보인다).
- .stats(3칸 → 2칸 → 1칸)·.tiles(4칸 → 2×2)·.hour-chart(간격·라벨)는 main 의 컨테이너 규칙(@container)으로 바뀌고, 글자는 자르지 않고 줄을 바꾼다.

이 시험은 글자만 본다. 실제 폭별 모양(가로 넘침·잘린 글자)은 브라우저로 따로 잰다 (contract.md 2.9 끝의 '확인한 것').

실행 (services/web 에서): PYTHONPATH=<저장소 루트>:. python -m pytest -q tests/test_layout_static.py
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")
CSS_CODE = re.sub(r"/\*[\s\S]*?\*/", "", CSS)          # 주석 속 설명 글자는 빼고 본다
JS_CODE = re.sub(r"(?m)(?<![:\"'`])//[^\n]*", "", JS)   # 줄 주석을 뺀 코드 (주소 속 // 는 그대로)

DRAWER_OPEN = "body:has(> .shell > .drawer:not([hidden]))"


def squeeze(text: str) -> str:
    return " ".join(text.split())


def at_blocks(at: str) -> list[tuple[str, str]]:
    """style.css 의 @media / @container 덩어리를 (조건, 안의 규칙) 으로. 공백은 한 칸으로 줄인다."""
    out = []
    for m in re.finditer(re.escape(at) + r"\s*([^{;]*)\{", CSS_CODE):
        depth, i = 1, m.end()
        while depth and i < len(CSS_CODE):
            depth += {"{": 1, "}": -1}.get(CSS_CODE[i], 0)
            i += 1
        out.append((squeeze(m.group(1)), squeeze(CSS_CODE[m.end():i - 1])))
    return out


def media(condition: str) -> str:
    """조건이 꼭 그 글자인 @media 덩어리들의 규칙을 이어 붙인 것. 없으면 빈 글자."""
    return " ".join(body for cond, body in at_blocks("@media") if cond == condition)


def containers() -> list[tuple[int, str]]:
    """(max-width 값, 규칙) 목록: main 의 컨테이너 규칙 가운데 max-width 로 묶인 것."""
    out = []
    for cond, body in at_blocks("@container"):
        m = re.fullmatch(r"\(max-width: (\d+)px\)", cond)
        if m:
            out.append((int(m.group(1)), body))
    return out


def rule(selector: str, css: str = "") -> str:
    """선택자가 꼭 그 글자인 규칙의 선언들 (여러 번 나오면 이어 붙임). css 를 주지 않으면 @ 덩어리 밖의 규칙에서만 찾는다."""
    if not css:
        css = CSS_CODE
        for at in ("@media", "@container", "@keyframes"):
            for m in reversed(list(re.finditer(re.escape(at) + r"\s*[^{;]*\{", css))):
                depth, i = 1, m.end()
                while depth and i < len(css):
                    depth += {"{": 1, "}": -1}.get(css[i], 0)
                    i += 1
                css = css[:m.start()] + css[i:]
        css = squeeze(css)
    found = re.findall(r"(?:^|[};])\s*" + re.escape(selector) + r"\s*\{([^{}]*)\}", css)
    return " ".join(f.strip() for f in found)


def px(pattern: str, text: str) -> int:
    m = re.search(pattern, text)
    assert m, pattern
    return int(m.group(1))


def function(name: str) -> str:
    start = JS.index(f"function {name}(")
    end = JS.index("\n}\n", start)
    return JS[start:end]


def menu_js() -> str:
    """app.js 의 '왼쪽 메뉴 접기' 덩어리: 그 머리부터 다음 덩어리('맨 위 띠·바닥') 앞까지. 줄 주석은 뺀다."""
    start = JS.index("// ── 왼쪽 메뉴 접기")
    block = JS[start:JS.index("// ── 맨 위 띠·바닥", start)]
    return re.sub(r"(?m)(?<![:\"'`])//[^\n]*", "", block)


SHOWN = "screen and (min-width: 761px)"                                # 토글 버튼이 보이고 메뉴를 접을 수 있는 폭
MID = "screen and (min-width: 761px) and (max-width: 1024px)"          # 메뉴가 접힌 채 시작하고 펼치면 덮는 폭
OVER = "screen and (max-width: 1279px)"                                # 서랍이 본문 위에 덮이는 폭 (1280px 미만)
PUSH_WHEN_CLOSED = "screen and (min-width: 1025px) and (max-width: 1279px)"
PHONE = "(max-width: 760px)"


class ToggleMarkup(unittest.TestCase):
    def setUp(self):
        m = re.search(r'<button id="menu-toggle"[^>]*>[\s\S]*?</button>', HTML)
        self.assertIsNotNone(m, 'index.html 에 <button id="menu-toggle"> 이 없음')
        self.button = m.group(0)
        self.tag = self.button[:self.button.index(">") + 1]

    def test_toggle_button_names_what_it_controls(self):
        self.assertIn('type="button"', self.tag)
        self.assertIn('aria-controls="side-menu"', self.tag)
        self.assertRegex(self.tag, r'aria-expanded="(true|false)"')
        self.assertIn('aria-label="왼쪽 메뉴 접기"', self.tag)
        self.assertRegex(HTML, r'<nav class="side" id="side-menu"')         # aria-controls 가 가리키는 메뉴

    def test_toggle_sits_in_the_top_bar(self):
        top = re.search(r'<header class="top">[\s\S]*?</header>', HTML).group(0)
        self.assertIn('id="menu-toggle"', top)
        self.assertLess(top.index('id="menu-toggle"'), top.index('id="store-name"'))   # 상단 바 왼쪽
        self.assertEqual(HTML.count('id="menu-toggle"'), 1)

    def test_icon_is_decoration_and_count_is_described(self):
        self.assertRegex(self.button, r'<svg class="ico"[^>]*aria-hidden="true"')
        self.assertRegex(self.button, r'<span id="menu-toggle-count" class="menu-toggle-count" hidden></span>')
        self.assertIn('aria-describedby="menu-toggle-count"', self.tag)

    def test_ids_the_script_already_used_are_kept(self):
        for i in ("nav-draft-count", "staff", "staff-strip", "staff-data", "dot-care", "staff-care", "dot-mkt", "staff-mkt",
                  "ask-ai", "ask-open", "assistant", "store-name"):
            self.assertIn(f'id="{i}"', HTML)
        self.assertRegex(HTML, r'<div class="shell">\s*(<!--[\s\S]*?-->\s*)*<nav class="side"')   # .shell > nav.side, main, aside 순서
        self.assertLess(HTML.index('<nav class="side"'), HTML.index("<main>"))
        self.assertLess(HTML.index("<main>"), HTML.index('<aside id="assistant"'))


class MenuScript(unittest.TestCase):
    def test_storage_key_and_try_catch(self):
        self.assertIn('const MENU_KEY = "ic26.menu";', JS)
        uses = [line for line in menu_js().splitlines() if "localStorage" in line]
        self.assertGreaterEqual(len(uses), 2, "읽기·쓰기 두 곳")
        for line in uses:                                              # localStorage 는 늘 try { … } catch 안에서만
            for m in re.finditer(r"localStorage\.\w+\(", line):
                before = line[:m.start()]
                self.assertGreater(before.rfind("try {"), before.rfind("}"), line.strip())
                self.assertRegex(line[m.end():], r"\}\s*catch\s*\(", line.strip())
        self.assertIn("localStorage.getItem(MENU_KEY)", JS)
        self.assertIn("localStorage.setItem(MENU_KEY, v)", JS)
        self.assertEqual(len(re.findall(r"localStorage\.", menu_js())), 2)     # 읽는 곳 하나, 쓰는 곳 하나

    def test_state_is_one_attribute_and_aria_follows_it(self):
        body = function("setMenu")
        self.assertIn('document.documentElement.dataset.menu = open ? "open" : "closed";', body)
        self.assertIn('b.setAttribute("aria-expanded", String(open));', body)
        self.assertIn('open ? "왼쪽 메뉴 접기" : "왼쪽 메뉴 펼치기"', body)
        self.assertIn('b.setAttribute("aria-label", label);', body)
        self.assertIn("setTopH();", body)                                # 덮는 메뉴는 상단 바 바로 아래에서 시작

    def test_width_bands(self):
        self.assertIn('const menuMid = window.matchMedia("(min-width: 761px) and (max-width: 1024px)");', JS)
        self.assertIn('const menuPhone = window.matchMedia("(max-width: 760px)");', JS)
        # 761~1024px 과 760px 이하가 아니면 넓은 화면 (구간 사이 1px 틈도 style.css 처럼 넓은 화면 규칙)
        self.assertIn('const menuBandNow = () => (menuMid.matches ? "mid" : menuPhone.matches ? "phone" : "wide");', JS)
        body = function("applyMenu")
        # 중간 폭은 기억한 값과 상관없이 접힌 채, 넓은 폭만 기억한 값, 760px 이하는 늘 펼친 것으로
        self.assertIn('setMenu(menuBand === "mid" ? false : menuBand === "wide" ? menuRead() !== "closed" : true);', body)
        self.assertIn('window.addEventListener("resize", () => { if (menuBandNow() !== menuBand) applyMenu(); });', JS)

    def test_only_the_wide_band_remembers(self):
        body = function("toggleMenu")
        self.assertIn('if (menuBand !== "mid") { menuWrite(open ? "open" : "closed"); return; }', body)
        self.assertLess(body.index("menuWrite("), body.index(".focus()"))   # 덮는 메뉴(중간 폭)만 포커스를 옮긴다
        self.assertIn('$("menu-toggle").focus();', body)

    def test_overlay_closes_by_escape_outside_click_and_menu_item(self):
        self.assertIn('$("menu-toggle").addEventListener("click", toggleMenu);', JS)
        self.assertIn('const menuOverlayOpen = () => menuBand === "mid" && menuIsOpen();', JS)
        self.assertIn('if (e.key === "Escape") { e.stopPropagation(); closeMenuOverlay(); return; }', JS)   # 서랍의 Esc 보다 먼저
        self.assertIn('if (e.target.closest(".side") && !e.target.closest(".side a[href]")) return;', JS)
        key = JS[JS.index('if (e.key === "Escape") { e.stopPropagation(); closeMenuOverlay();'):]
        key = key[:key.index("\n}, true);")]                              # 캡처 단계 처리기
        self.assertIn('if (e.key !== "Tab") return;', key)
        self.assertIn("e.preventDefault();", key)
        close = function("closeMenuOverlay")
        self.assertIn("setMenu(false);", close)
        self.assertIn('if (back) $("menu-toggle").focus();', close)

    def test_applied_before_the_first_screen(self):
        start = JS.index("\napplyTheme();")
        self.assertLess(start, JS.index("\napplyMenu();"))
        self.assertLess(JS.index("\napplyMenu();"), JS.rindex("\nroute();\nboot();"))
        boot = JS[JS.index("async function boot()"):start]
        self.assertNotIn("applyMenu", boot)                               # 서버 응답을 기다리지 않는다

    def test_count_follows_the_menu_number(self):
        dash = function("renderDash")
        self.assertIn('$("nav-draft-count").textContent = waiting;', dash)
        self.assertIn("syncMenuCount(waiting);", dash)
        self.assertIn("승인 대기 ${esc(n)}개", function("syncMenuCount"))

    def test_drawer_placement_stays_in_css(self):
        body = function("toggleAssistant")
        self.assertRegex(body, r"\.hidden\s*=")                           # 서랍은 hidden 속성으로만 여닫는다
        for banned in ("paddingRight", "padding-right", "dataset.menu"):  # 미는지 덮는지는 CSS 가 정한다
            self.assertNotIn(banned, body)
        self.assertNotIn("paddingRight", JS_CODE)
        self.assertNotIn("paddingLeft", JS_CODE)


class MenuCss(unittest.TestCase):
    def test_collapsed_menu_leaves_the_page(self):
        css = media(SHOWN)
        self.assertTrue(css, f"@media {SHOWN} 가 없음")
        self.assertEqual(rule(':root[data-menu="closed"] body', css), "padding-left: 0;")
        side = rule(':root[data-menu="closed"] .side', css)
        self.assertIn("transform: translateX(-100%);", side)
        self.assertIn("visibility: hidden;", side)                        # 키보드·읽기 프로그램에서도 빠짐
        self.assertIn("display: inline-flex;", rule(':root[data-menu="closed"] .top-brand', css))
        self.assertIn("display: flex;", rule(':root[data-menu="closed"] .staff-strip', css))

    def test_middle_widths_start_collapsed_and_open_as_an_overlay(self):
        css = media(MID)
        self.assertTrue(css, f"@media {MID} 가 없음")
        self.assertEqual(rule("body", css), "padding-left: 0;")           # 메뉴가 본문을 밀지 않는다
        side = rule(".side", css)                                         # data-menu 가 없어도(JS 전에도) 접힌 채
        self.assertIn("transform: translateX(-100%);", side)
        self.assertIn("visibility: hidden;", side)
        self.assertIn("top: var(--top-h, 56px);", side)                   # 토글 버튼이 있는 상단 바는 가리지 않는다
        opened = rule(':root[data-menu="open"] .side', css)
        self.assertIn("transform: none;", opened)
        self.assertIn("visibility: visible;", opened)
        back = rule(':root[data-menu="open"] .shell::before', css)        # 뒤의 어두운 배경
        self.assertIn("position: fixed;", back)
        self.assertIn("background: var(--scrim);", back)
        self.assertIn("display: flex;", rule(".staff-strip", css))
        self.assertIn("display: inline-flex;", rule(".top-brand", css))

    def test_reduced_motion_has_no_slide(self):
        css = media(MID + " and (prefers-reduced-motion: reduce)")
        self.assertIn("transition: none;", css)

    def test_phone_keeps_the_row_menu_without_a_toggle(self):
        css = media(PHONE)
        self.assertIn("display: none;", rule(".menu-toggle"))            # 기본은 숨김 (760px 이하·인쇄)
        self.assertEqual(rule(".menu-toggle", media(SHOWN)), "display: inline-flex;")   # 화면 761px 이상에서만 보임
        self.assertNotIn(".menu-toggle", css)
        self.assertNotIn("data-menu", css)                               # 가로 메뉴는 접힘 상태를 보지 않는다
        self.assertIn("position: static;", rule(".side", css))
        self.assertEqual(rule("body", css), "padding-left: 0;")
        self.assertEqual(rule(DRAWER_OPEN, css), "padding-right: 0;")     # 시트는 본문을 밀지 않는다

    def test_menu_state_rules_never_reach_print(self):
        blocks = [cond for cond, body in at_blocks("@media")
                  if ("data-menu" in body or ".menu-toggle {" in body) and not cond.startswith("print")]
        self.assertGreaterEqual(len(blocks), 3)
        for cond in blocks:                                               # 인쇄 폭(A4 약 794px)이 761~1024px 에 들어가므로
            self.assertTrue(cond.startswith("screen and "), cond)
        self.assertEqual(rule(':root[data-menu="closed"] body'), "")      # @media 밖에는 접힘 규칙이 없다
        self.assertEqual(rule(':root[data-menu="open"] .side'), "")

    def test_tokens_for_the_overlay(self):
        root = rule(":root")
        dark = media("(prefers-color-scheme: dark)")
        for token in ("--scrim:", "--over-shadow:"):
            self.assertIn(token, root)
            self.assertIn(token, dark)

    def test_toggle_button_style(self):
        self.assertIn("width: 40px;", rule(".menu-toggle"))
        count = rule(".menu-toggle-count")
        self.assertIn("display: none;", count)                            # 메뉴가 접혀 있을 때만 보인다
        self.assertIn("font-size: var(--meta);", count)
        self.assertIn("display: block;", rule(':root[data-menu="closed"] .menu-toggle-count', media(SHOWN)))


class DrawerPlacement(unittest.TestCase):
    def test_drawer_overlays_below_1280(self):
        css = media(OVER)
        self.assertTrue(css, f"@media {OVER} 가 없음")
        self.assertEqual(rule(DRAWER_OPEN, css), "padding-right: 0;")     # 본문 폭을 깎지 않는다
        self.assertIn("box-shadow:", rule(".drawer", css))
        # 760px 이하의 시트 규칙이 그 뒤에 와서 시트 모양을 다시 정한다 (같은 선택자라 뒤에 온 것이 이김)
        code = squeeze(CSS_CODE)
        self.assertLess(code.index("@media " + OVER), code.index("@media " + PHONE + " {"))
        self.assertIn("top: auto;", rule(".drawer", media(PHONE)))

    def test_drawer_pushes_again_when_the_menu_is_collapsed(self):
        css = media(PUSH_WHEN_CLOSED)
        self.assertTrue(css, f"@media {PUSH_WHEN_CLOSED} 가 없음")
        self.assertRegex(rule(f':root[data-menu="closed"] {DRAWER_OPEN}', css), r"^padding-right: \d+px;$")
        self.assertIn("box-shadow: none;", rule(':root[data-menu="closed"] .drawer', css))

    def test_at_least_680px_is_left_wherever_the_drawer_pushes(self):
        side = px(r"--side-w: (\d+)px", rule(":root"))
        side_small = px(r"--side-w: (\d+)px", media("(max-width: 1100px)"))
        wide_drawer = px(r"(?<![\w-])width: (\d+)px", rule(".drawer"))
        self.assertEqual(px(r"padding-right: (\d+)px", rule(DRAWER_OPEN)), wide_drawer)
        narrow = media("(max-width: 1339px)")
        drawer = px(r"(?<![\w-])width: (\d+)px", rule(".drawer", narrow))
        self.assertEqual(px(r"padding-right: (\d+)px", rule(DRAWER_OPEN, narrow)), drawer)
        closed = px(r"padding-right: (\d+)px", rule(f':root[data-menu="closed"] {DRAWER_OPEN}', media(PUSH_WHEN_CLOSED)))
        self.assertEqual(closed, drawer)
        self.assertGreaterEqual(1280 - side - drawer, 680)                # 1280px, 메뉴 펼침
        self.assertGreaterEqual(1340 - side - wide_drawer, 680)           # 1340px 부터 넓은 서랍
        self.assertGreaterEqual(1025 - closed, 680)                       # 1025px, 메뉴 접힘
        self.assertLess(1279 - side - drawer, 680)                        # 그래서 1279px 까지는 메뉴가 펼쳐져 있으면 덮는다
        self.assertGreater(side, side_small)                              # 1100px 이하에서는 메뉴가 더 좁다 (본문은 더 넓게 남음)

    def test_the_drawer_rule_in_the_1100_block_moved_to_1339(self):
        self.assertNotIn(".drawer", media("(max-width: 1100px)"))
        self.assertNotIn("padding-right", media("(max-width: 1100px)"))

    def test_drawer_is_still_opened_by_the_hidden_attribute(self):
        self.assertIn("[hidden] { display: none !important; }", CSS)
        self.assertIn(DRAWER_OPEN + " { padding-right:", squeeze(CSS_CODE))


class MainContainerRules(unittest.TestCase):
    def test_main_is_the_query_container(self):
        self.assertIn("container-type: inline-size;", rule(".shell > main"))

    def test_stats_go_from_three_to_two_to_one_column(self):
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr));", rule(".stats"))
        two = [w for w, body in containers() if "grid-template-columns: repeat(2, minmax(0, 1fr));" in rule(".stats", body)]
        one = [w for w, body in containers() if "grid-template-columns: minmax(0, 1fr);" in rule(".stats", body)]
        self.assertEqual(len(two), 1)
        self.assertEqual(len(one), 1)
        self.assertGreater(two[0], one[0])
        self.assertGreaterEqual(one[0], 240)                              # 2칸일 때 칸 하나가 120px 아래로 좁아지지 않는다
        self.assertGreaterEqual((two[0] + 1) // 3, 150)                   # 3칸일 때 칸 하나가 150px 아래로 좁아지지 않는다
        # 3칸이 2칸이 되면 마지막 칸이 한 줄 전체 (빈 칸에 구분선 색이 드러나지 않게)
        body = next(b for w, b in containers() if w == two[0])
        self.assertIn("grid-column: 1 / -1;", rule(".stats > :last-child:nth-child(odd)", body))

    def test_tiles_go_from_four_to_two_by_two(self):
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr));", rule(".tiles"))
        two = [w for w, body in containers() if "grid-template-columns: repeat(2, minmax(0, 1fr));" in rule(".tiles", body)]
        self.assertEqual(len(two), 1)
        self.assertGreaterEqual((two[0] + 1) // 4, 160)                   # 4칸일 때 칸 하나가 160px 아래로 좁아지지 않는다

    def test_cards_rule_kept(self):
        self.assertTrue(any("grid-template-columns: 1fr;" in rule(".cards", body) for _, body in containers()))

    def test_numbers_and_labels_wrap_instead_of_being_cut(self):
        self.assertIn("overflow: hidden;", rule(".stats"))                # 둥근 모서리용. 그래서 글자는 줄을 바꿔야 한다
        card = rule(".stat-card")
        self.assertIn("min-width: 0;", card)
        self.assertIn("word-break: keep-all;", card)
        self.assertRegex(card, r"overflow-wrap: (anywhere|break-word);")
        for sel in (".stat-card", ".stat-card dt", ".stat-card dd", ".stat-n", ".stat-sub", ".store"):
            self.assertNotIn("ellipsis", rule(sel), sel)
            self.assertNotRegex(rule(sel), r"white-space: nowrap", sel)
        store = rule(".store")
        self.assertIn("word-break: keep-all;", store)                     # 가게 이름도 말줄임표 대신 줄바꿈
        dash = rule(".dash")
        self.assertIn("word-break: keep-all;", dash)
        self.assertIn("overflow-wrap: break-word;", dash)

    def test_hour_chart_tightens_and_skips_labels_when_narrow(self):
        gaps = sorted((w, px(r"gap: (\d+)px", rule(".hour-chart", body))) for w, body in containers() if "gap:" in rule(".hour-chart", body))
        self.assertGreaterEqual(len(gaps), 2)
        base = px(r"gap: (\d+)px", rule(".hour-chart"))
        self.assertEqual([g for _, g in gaps], sorted(g for _, g in gaps))   # 좁을수록 간격도 좁게
        self.assertLess(gaps[-1][1], base)
        skip = [(w, body) for w, body in containers() if ".hc-col:nth-child(even) .hc-h" in body]
        self.assertGreaterEqual(len(skip), 2)                             # 늘 좁을 때 + 막대가 많을 때(더 일찍)
        for _, body in skip:
            self.assertIn("font-size: 0;", body)
            self.assertIn("min-height:", body)                            # 숨긴 라벨도 높이는 그대로 (막대 바닥이 어긋나지 않게)
        self.assertTrue(any(".hour-chart:has(> .hc-col:nth-child(" in body for _, body in skip))
        for sel in (".hc-n", ".hc-h"):
            self.assertIn("white-space: nowrap;", rule(sel), sel)         # 좁은 칸에서 숫자가 두 줄로 꺾이지 않는다
        self.assertIn("min-width: 0;", rule(".hc-col"))


if __name__ == "__main__":
    unittest.main()
