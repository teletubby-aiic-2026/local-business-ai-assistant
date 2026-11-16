"""'맞춤 마케팅'(#/marketing) 화면 파일을 글자로 읽어 확인하는 정적 시험 (11/16). 서버·브라우저를 띄우지 않는다.

지키는 것
- 왼쪽 메뉴의 자리(리뷰 분석과 종합 리포트 사이)·짧은 글자 방식(long/short)·ROUTES·화면(section data-view="marketing").
- 이 화면의 id 는 모두 mkt- 로 시작하고, JS 가 찾는 id 는 모두 있다 (HTML 또는 JS 가 만듦).
- 요청은 모두 전용 mktApi(/api/marketing-survey/ + 경로)를 거친다: fetch 직접 없음, ?store= 를 붙이지 않음, 허용된 경로만,
  전역 api()·showAlert(#alert)·careApi·drawerApi 를 쓰지 않음. /web/ 자체 화면·iframe·새 외부 스크립트 없음.
- 시작 모드 다섯 개, 처음부터, 보고서 탭(주간·월간)과 데모 표시, 시험용 저장 예시 표시, 승인 연동(approval·처리 완료 목록), 초기화 연동.
- 종합 리포트의 마케팅 요약 칸에 #/marketing 링크 (인쇄에서는 rp-screen 으로 빠짐). 리포트 덩어리는 마케팅 서비스를 부르지 않는다.
- 새 덩어리는 다른 정적 시험이 잘라 보는 경계(고객응대·리포트·서랍) 밖에 있고, 새 색 토큰을 더하지 않는다.

실행 (services/web 에서): PYTHONPATH=<저장소 루트>:. python -m pytest -q tests/test_marketing_ui_static.py
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")

MKT_HEAD = "// ── 맞춤 마케팅 (#/marketing"
ALLOWED = {"health", "meta", "step", "result", "plan", "generate", "next-idea", "idea-try", "coupon-calc", "approve",
           "notice-followup", "report"}           # services/web/web/marketing_proxy.py 의 허용 목록 (stores·records 는 없음)
MODES = ("맞춤 홍보 제안", "남은 재료 팔기", "광고비 점검", "가게 이야기 글", "쿠폰 결과 확인")


def code(js: str) -> str:
    return re.sub(r"(?m)(?<![:\"'`])//[^\n]*", "", js)       # 줄 주석을 뺀 코드 (주소 속 // 는 그대로)


def mkt_js() -> str:
    """app.js 의 맞춤 마케팅 덩어리: 머리부터 '── AI에게 묻기 서랍' 앞까지."""
    assert MKT_HEAD in JS, "app.js 에 맞춤 마케팅 덩어리가 없음"
    start = JS.index(MKT_HEAD)
    return JS[start:JS.index("// ── AI에게 묻기 서랍", start)]


def mkt_html() -> str:
    m = re.search(r'<section class="view mkt" data-view="marketing" hidden>[\s\S]*?\n    </section>', HTML)
    assert m, "index.html 에 맞춤 마케팅 화면이 없음"
    return m.group(0)


def function(name: str) -> str:
    m = re.search(rf"^(?:async )?function {name}\(", JS, re.M)
    assert m, f"app.js 에 function {name} 이 없음"
    rest = JS[m.end():]
    nxt = re.search(r"^(?:async function |function |const |let |// ── |\$\()", rest, re.M)
    return JS[m.start():m.end() + (nxt.start() if nxt else len(rest))]


def css_block() -> str:
    start = CSS.index("/* ── 맞춤 마케팅 (#/marketing")
    return CSS[start:CSS.index("/* ── 종합 리포트 (#/report", start)]


class MenuAndView(unittest.TestCase):
    def test_menu_sits_between_analysis_and_report(self):
        menu = re.search(r'<div class="menu">[\s\S]*?</div>', HTML).group(0)
        self.assertIn('<a href="#/marketing" data-route="marketing">', menu)
        self.assertLess(menu.index('data-route="analysis"'), menu.index('data-route="marketing"'))
        self.assertLess(menu.index('data-route="marketing"'), menu.index('data-route="report"'))
        link = re.search(r'<a href="#/marketing"[\s\S]*?</a>', menu).group(0)
        self.assertIn('<span><span class="long">맞춤 </span>마케팅</span>', link)     # 760px 이하 가로 메뉴는 '마케팅'만
        self.assertRegex(link, r'<svg class="ico"[^>]*aria-hidden="true"')
        self.assertEqual(HTML.count('data-route="marketing"'), 1)

    def test_routes_and_view(self):
        routes = JS[JS.index("const ROUTES"):JS.index("\n", JS.index("const ROUTES"))]
        self.assertIn('"marketing"', routes)
        self.assertLess(routes.index('"analysis"'), routes.index('"marketing"'))
        html = mkt_html()
        self.assertIn('<h1 tabindex="-1">맞춤 마케팅</h1>', html)           # 화면을 바꾸면 route() 가 이 h1 에 포커스
        self.assertIn('if (name === "marketing") mktOpen();', JS)            # 처음 열 때만 시작 (첫 화면 로딩에 영향 없음)
        boot = JS[JS.index("async function boot()"):JS.index("applyTheme();")]
        self.assertNotIn("mkt", boot)
        self.assertNotIn("/api/marketing-survey", boot)

    def test_every_id_uses_the_prefix(self):
        ids = re.findall(r'id="([\w-]+)"', mkt_html())
        self.assertTrue(ids)
        self.assertEqual([i for i in ids if not i.startswith("mkt-")], [])
        self.assertEqual(len(ids), len(set(ids)))
        made = re.findall(r'id="([^"$]+)', mkt_js())                       # JS 가 그려 넣는 id (mkt-card-…, mkt-text-… 등)
        self.assertTrue(made)
        self.assertEqual([i for i in made if not i.startswith("mkt-")], [])
        self.assertIn("const id = `mkt-text-${card.n}-${mktKey(key)}`;", mkt_js())   # 글 칸 id 도 mkt- 로 시작
        self.assertNotIn('id="', re.sub(r'id="(mkt-[^"]*|\$\{esc\(id\)\})"', "", mkt_js()))

    def test_every_id_the_script_uses_exists(self):
        used = set(re.findall(r"""\$\(\s*["'](mkt-[\w-]+)["']\s*\)""", JS))
        used |= {f"mkt-tab-{t}" for t in ("chat", "report")}                  # $("mkt-tab-" + t)
        self.assertGreater(len(used), 15)
        have = set(re.findall(r'id="([\w-]+)"', HTML)) | set(re.findall(r'id="([\w-]+)"', JS))   # 입력칸(mkt-num 등)은 JS 가 그림
        self.assertEqual(sorted(used - have), [])
        for i in ("mkt-log", "mkt-options", "mkt-status", "mkt-error", "mkt-notice", "mkt-state", "mkt-retry", "mkt-restart",
                  "mkt-tab-chat", "mkt-tab-report", "mkt-chat", "mkt-report-panel", "mkt-report", "mkt-report-state", "mkt-store"):
            self.assertIn(i, have)

    def test_accessibility_places(self):
        html = mkt_html()
        self.assertRegex(html, r'id="mkt-log"[^>]*role="log"[^>]*aria-live="polite"')
        self.assertRegex(html, r'id="mkt-status"[^>]*role="status"')
        self.assertRegex(html, r'id="mkt-error"[^>]*role="alert"')
        self.assertRegex(html, r'id="mkt-report-state"[^>]*role="status"')
        self.assertIn('role="tablist" aria-label="맞춤 마케팅 화면"', html)
        for tab, panel in (("chat", "mkt-chat"), ("report", "mkt-report-panel")):
            self.assertRegex(html, rf'role="tab" id="mkt-tab-{tab}" data-mkt-tab="{tab}" aria-controls="{panel}"')
            self.assertRegex(html, rf'id="{panel}"[^>]*role="tabpanel"[^>]*aria-labelledby="mkt-tab-{tab}"')
        self.assertNotIn('data-tab="', html)                                  # 리뷰 분석 탭의 처리기([data-tab])와 섞이지 않게
        keys = function("mktTabKey")
        for key in ("ArrowRight", "ArrowLeft", "Home", "End"):
            self.assertIn(key, keys)
        self.assertIn('tab.tabIndex = on ? 0 : -1;', function("mktTab"))
        self.assertIn('aria-pressed', mkt_html())                             # 기간 고르기 (주간·월간)
        self.assertIn('e.isComposing && e.keyCode !== 229', JS[JS.index('$("mkt-options").addEventListener("keydown"'):])


class Requests(unittest.TestCase):
    def test_all_calls_go_through_mktapi_without_the_store_query(self):
        js = code(mkt_js())
        self.assertIn('const MKT_BASE = "/api/marketing-survey/";', js)
        self.assertEqual(js.count("fetch("), 1)                               # mktApi 안의 한 곳뿐
        api = function("mktApi")
        self.assertIn("fetch(MKT_BASE + path", api)
        self.assertNotIn("store=", api)
        paths = re.findall(r"""mkt(?:Api|Post)\(\s*[`"']([^`"'$?]+)""", js)
        self.assertTrue(paths)
        self.assertEqual(sorted(set(paths) - ALLOWED), [])
        for p in ("health", "meta", "step", "result", "plan", "generate", "next-idea", "idea-try", "coupon-calc", "approve",
                  "notice-followup", "report"):
            self.assertIn(p, paths)
        self.assertNotIn("stores", paths)
        self.assertNotIn("records", paths)
        self.assertNotIn("?store=", JS)
        self.assertNotIn("store=", js)
        self.assertNotIn("visitor_id", js)                                    # 방문자는 서버가 쿠키로 붙인다
        self.assertIsNone(re.search(r"(?<![\w.])api\(", js), "전역 api() 대신 mktApi 로만 부른다")
        for banned in ("showAlert", '$("alert")', "careApi(", "drawerApi("):
            self.assertNotIn(banned, js)
        self.assertEqual(code(JS).count("/api/marketing-survey"), 1)          # 주소는 MKT_BASE 한 곳에만 (주석 밖)

    def test_no_iframe_old_page_or_new_script(self):
        self.assertEqual(re.findall(r'<script[^>]*src="([^"]+)"', HTML), ["/static/app.js"])
        for text in (re.sub(r"<!--[\s\S]*?-->", "", HTML), code(JS)):       # 주석 속 원본 파일 경로는 빼고 본다
            self.assertNotIn("<iframe", text.lower())
            self.assertNotIn('"/web/', text)
            self.assertNotIn("/web/app.js", text)
        self.assertNotRegex(HTML + JS, r"https?://(cdn|unpkg|cdnjs)")

    def test_fetch_options_and_waits(self):
        api = function("mktApi")
        self.assertIn('credentials: "same-origin"', api)
        self.assertIn("AbortController", api)
        self.assertIn('typeof options.body === "string"', api)
        self.assertIn("const MKT_LONG_MS = 60000;", JS)                       # 서버(글 만들기 45초)보다 길게
        self.assertIn("const MKT_WAIT_MS = 15000;", JS)                       # 서버(나머지 10초)보다 길게
        self.assertIn('const MKT_LONG = ["plan", "generate", "idea-try"];', JS)
        self.assertIn("body?.error?.message", api)                             # 서버의 한국어 안내 그대로

    def test_block_sits_outside_the_other_static_test_boundaries(self):
        start = JS.index("// ── 고객응대 호출")
        care = JS[start:JS.index("// ── 준비 중 자리", start)]                 # test_care_ui_static.care_js() 와 같은 경계
        self.assertIn("async function rpMarketing()", care)
        start = JS.index("// ── AI에게 묻기 서랍")
        drawer = JS[start:JS.index("// 상단 바 높이", start)]                  # test_assistant_drawer_static.drawer_js() 와 같은 경계
        self.assertIn("async function chatSend(", drawer)
        for block in (care, drawer):
            self.assertNotIn("mktApi", block)
            self.assertNotIn(MKT_HEAD, block)
        self.assertLess(JS.index("// ── 준비 중 자리: LATER"), JS.index(MKT_HEAD))
        self.assertLess(JS.index(MKT_HEAD), JS.index("// ── AI에게 묻기 서랍"))


class Features(unittest.TestCase):
    def test_five_start_modes_restart_and_report_shortcut(self):
        modes = JS[JS.index("const MKT_MODES"):JS.index("};", JS.index("const MKT_MODES"))]
        for m in MODES:
            self.assertIn(f'"{m}"', modes)
        self.assertIn('<button id="mkt-restart" type="button" class="ghost">처음부터</button>', mkt_html())
        self.assertIn("data-mkt-goto-report", function("mktPrompt"))
        self.assertIn('mktPost("step", { state: null, answer: null })', function("mktFirst"))

    def test_question_kinds(self):
        prompt, inputs = function("mktPrompt"), function("mktInputHtml")
        self.assertIn("d.multi", prompt)
        self.assertIn('aria-pressed="false" data-mkt-multi', prompt)
        self.assertIn("data-mkt-next disabled", prompt)
        self.assertIn("d.example", prompt)                                    # 예시 문구
        self.assertIn('spec.type === "number"', inputs)
        self.assertIn('inputmode="numeric"', inputs)
        self.assertIn("spec.skip", inputs)
        self.assertIn("건너뛰기", inputs)
        self.assertIn('mktPost("step", { state: mkt.flow, answer })', function("mktStep"))
        self.assertIn("mktErr(e.message, () => mktStep(answer, focus))", function("mktStep"))   # 다시 시도

    def test_result_card_parts(self):
        result = function("mktResult")
        for part in ("왜 이렇게 판단했나요", "mktTiles(d)", "mktBadge(d)", "d.over_budget", "mktAdspendHtml(d.table)", "d.steps",
                     "d.basic_todos", "d.idea", "d.coupon_card", "d.next_condition", "d.measure", "d.bundle", "d.discount_tile",
                     "data-mkt-approve", "data-mkt-rewrite", 'href="#/done"'):
            self.assertIn(part, result)
        self.assertIn('mktPost("result", { state: flow })', function("mktDecide"))      # 판단 근거 (규칙 설명 3줄)
        self.assertIn('mktPost("plan", { state: flow })', function("mktDecide"))

    def test_slider_recalculates_without_flooding(self):
        calc = function("mktCalcBind")
        self.assertIn("card.timer = setTimeout(recalc, 150);", calc)
        self.assertIn("clearTimeout(card.timer);", calc)
        self.assertIn("if (seq !== card.seq) return;", calc)                   # 늦게 온 숫자는 버린다
        self.assertIn('mktPost("coupon-calc"', calc)
        self.assertIn('type="range"', function("mktCouponHtml"))
        self.assertIn("aria-valuetext", function("mktCouponHtml"))
        self.assertIn("coupon_override: { ...card.calc }", function("mktCouponGen"))

    def test_ideas(self):
        self.assertIn("다음 아이디어", function("mktIdea"))
        self.assertIn("해 볼게요", function("mktIdea"))
        self.assertIn('mktPost("next-idea", { state: card.flow, current_index: card.ideaIndex })', function("mktIdeaNext"))
        self.assertIn('mktPost("idea-try", { state: card.flow, idea_id: idea.id, index: card.ideaIndex, answer })', function("mktIdeaTry"))
        self.assertIn("r.skip", function("mktIdeaTry"))

    def test_approve_sends_the_approval_and_lands_in_the_done_list(self):
        approve = function("mktApprove")
        self.assertIn('mktPost("approve", { state: card.flow, draft_id: null, session_id: card.session, edited_texts: edited, approval })', approve)
        self.assertIn("a.edit_failed", approve)
        self.assertIn("점검 실패", approve)
        self.assertIn("state.approvedLog.push(", approve)
        self.assertIn('card: "맞춤 마케팅", mkt: true', approve)
        self.assertIn("a.follow_up", approve)
        self.assertIn("mktNoticeOffer(card)", approve)
        self.assertIn('mktPost("notice-followup", { state: card.flow })', function("mktNoticeFollow"))
        done = function("renderDone")
        self.assertIn("log.filter((a) => a.mkt).length", done)
        self.assertIn('String(a.draft_id).startsWith("mkt-") ? "맞춤 마케팅 · " : ""', function("loadApprovals"))

    def test_restart_also_resets_the_marketing_screen(self):
        restart = function("restart")
        self.assertIn('const r = await api("/api/approvals", { method: "DELETE" }); cleared = r.marketing_cleared ?? null;', restart)
        self.assertIn("mktReset(failed ? null : cleared);", restart)
        reset = function("mktReset")
        for part in ("mkt.gen++", '$("mkt-log").replaceChildren();', '$("mkt-report").replaceChildren();', "mkt.started = false",
                     "cleared === false"):
            self.assertIn(part, reset)

    def test_report_tab(self):
        self.assertIn("mktApi(`report?period=${encodeURIComponent(period)}`)", function("mktReport"))
        html = mkt_html()
        self.assertIn('data-mkt-period="weekly"', html)
        self.assertIn('data-mkt-period="monthly"', html)
        draw = function("mktReportDraw")
        self.assertIn("d.demo ?", draw)
        self.assertIn("데모 기록", draw)
        self.assertIn("실제 우리 가게 기록이 아니에요", draw)
        self.assertIn("AI 호출 없음", draw)

    def test_demo_results_never_look_like_real_ai(self):
        self.assertIn('const MKT_DEMO = "시험용 저장 예시 (실제 AI 결과 아님)";', JS)
        self.assertIn('card.demo ? `<span class="badge">${esc(MKT_DEMO)}</span>` : ""', function("mktResult"))
        self.assertIn("d.demo === true", function("mktResult"))
        notice = function("mktNotice")
        self.assertIn('h.mode === "mock"', notice)
        self.assertIn("h.key_present === false", notice)
        self.assertIn("실제 AI 결과 아님", notice)
        self.assertIn("g.demo", function("mktCouponGen"))

    def test_server_text_is_escaped(self):
        js = mkt_js()
        for safe in ("${esc(text)}</textarea>", "${esc(o.label)}", "${esc(card.title)}", "${esc(r.label)}", "${esc(idea.title)}",
                     "${esc(t)}", "${esc(s.what)}", "${esc(d.measure)}", "${esc(n.title)}", "${esc(a.label)}", "${esc(label)}"):
            self.assertIn(safe, js)
        self.assertIn('$("mkt-error").textContent = message', js)              # 오류·상태 문장은 글자로만
        self.assertIn('$("mkt-state-msg").textContent = message', js)
        for raw in ("${d.title}", "${o.label}", "${idea.title}", "${text}</textarea>", "${r.label}</th>", "${t}</li>", ">${a.label}"):
            self.assertNotIn(raw, js)
        self.assertIn('aria-label="${esc(`${r.label}: 건당 광고비', js)           # 막대의 읽기용 이름도 통째로 esc()


class ReportLink(unittest.TestCase):
    def test_report_marketing_summary_links_here_without_calling_the_service(self):
        start = JS.index("// ── 종합 리포트")
        report = JS[start:JS.index("// ── 준비 중 자리", start)]
        marketing = report[report.index("async function rpMarketing()"):]
        self.assertIn('<p class="small rp-mkt-more rp-screen"><a href="#/marketing">맞춤 마케팅에서 자세히 보기</a></p>', marketing)
        for banned in ("mktApi", "mktPost", "/api/marketing-survey", "mktOpen", "mktStart"):
            self.assertNotIn(banned, report)
        self.assertIn("html.rp-view .rp-screen", CSS)                          # 인쇄에서 링크 줄을 숨기는 기존 규칙


class Styles(unittest.TestCase):
    def test_no_new_color_tokens_and_the_block_is_before_print(self):
        block = css_block()
        self.assertNotRegex(re.sub(r"/\*[\s\S]*?\*/", "", block), r"--[\w-]+\s*:")
        self.assertLess(CSS.index("/* ── 맞춤 마케팅 (#/marketing"), CSS.index("/* ── 종합 리포트 인쇄"))
        self.assertNotIn("@media print", block)
        self.assertNotIn("data-menu", block)

    def test_wide_table_scrolls_inside_its_own_box(self):
        self.assertIn(".mkt-table-wrap { overflow-x: auto;", CSS)
        self.assertIn('class="mkt-table-wrap"', mkt_js())


if __name__ == "__main__":
    unittest.main()
