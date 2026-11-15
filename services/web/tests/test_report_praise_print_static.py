"""종합 리포트(#/report)의 '손님 칭찬 요약' 칸과 '전체 리포트 PDF 저장'(인쇄 CSS) 시험.
화면 파일은 글자로 읽어 확인하고(서버·브라우저를 띄우지 않음), 프록시는 가짜 리뷰 분석 서비스로 확인한다.

지키는 것
- 손님 칭찬 요약: id 는 rp- 로 시작, 응대 점수 다음·월간 보고서 앞. 월간 보고서 응답의 praise 칸으로만 그리고 요청을 더하지 않는다.
  서버 글(주제·메뉴·대표 한 줄)은 esc() 를 거친다. 모델을 부르지 않는다 (코드 집계).
- 프록시(/api/care/report/*)는 praise 칸을 그대로 넘긴다.
- PDF 저장: rp-head-row 의 #rp-pdf 버튼 → window.print() 한 곳. 월간 인쇄 링크(#rp-print)는 그대로 둔다.
- 인쇄 CSS: @page A4, 리포트 화면만 보이게, 흰 바탕(라이트 토큰), 칸이 쪽 사이에서 잘리지 않게, 색 면이 찍히게.
  리포트 전용 규칙은 모두 html.rp-view 아래라서 다른 화면의 인쇄는 바뀌지 않는다.

실행 (services/web 에서): PYTHONPATH=<저장소 루트>:. python -m pytest -q tests/test_report_praise_print_static.py
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import httpx

from tests.test_care_proxy import FakeCare, P, build

STATIC = Path(__file__).resolve().parents[1] / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")

PRAISE = {"review_count": 18, "high_rating_count": 10, "positive_count": 10, "praise_count": 10, "praise_basis": "sentiment",
          "top_topics": [{"topic": "taste", "topic_name": "맛", "count": 5}],
          "top_menus": [{"menu": "순두부찌개", "count": 1}, {"menu": "불고기 덮밥", "count": 1}],
          "quote": {"text": "순두부찌개 얼큰하고 맛있어요", "review_id": "rv_ongi_039", "rating": 4}, "method": "code"}
EMPTY = {"review_count": 0, "high_rating_count": 0, "positive_count": 0, "praise_count": 0, "praise_basis": None,
         "top_topics": [], "top_menus": [], "quote": None, "method": "code"}


def report_html() -> str:
    m = re.search(r'<section class="view" data-view="report"[\s\S]*?\n    </section>', HTML)
    assert m, "index.html 에 종합 리포트 화면이 없음"
    return m.group(0)


def report_js() -> str:
    start = JS.index("// ── 종합 리포트")
    return JS[start:JS.index("// ── 준비 중 자리", start)]


def code(js: str) -> str:
    return re.sub(r"//[^\n]*", "", js)       # 주석 속 설명 글자는 빼고 본다


def function(js: str, head: str) -> str:
    """head 로 시작하는 함수 하나 (다음 줄 맨 앞의 '}' 까지)."""
    start = js.index(head)
    return js[start:js.index("\n}\n", start) + 3]


def block(css: str, head: str) -> str:
    """head('@media print {' 등)의 중괄호 안쪽."""
    start = css.index(head) + len(head)
    depth, i = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(css[i], 0)
        i += 1
    return css[start:i - 1]


def rules(css: str) -> list[tuple[str, str]]:
    """중첩 없는 CSS 덩어리 → [(선택자, 선언)]. 주석은 뺀다."""
    css = re.sub(r"/\*[\s\S]*?\*/", "", css)
    return [(sel.strip(), body.strip()) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


PRINT_HEAD = "/* ── 종합 리포트 인쇄"       # style.css 의 인쇄 덩어리 머리 주석


def print_chunk() -> str:
    """style.css 에서 '종합 리포트 인쇄' 머리 주석부터 끝까지 (다른 덩어리가 @media print 를 써도 이 덩어리만 본다)."""
    assert PRINT_HEAD in CSS, "style.css 에 '종합 리포트 인쇄' 덩어리가 없음"
    return CSS[CSS.index(PRINT_HEAD):]


def print_css() -> str:
    """'종합 리포트 인쇄' 덩어리의 @media print 안쪽."""
    return block(print_chunk(), "@media print {")


def print_rules() -> list[tuple[str, str]]:
    return rules(print_css())


class PraisePanelMarkup(unittest.TestCase):
    def test_panel_sits_between_score_and_month(self):
        html = report_html()
        self.assertRegex(html, r'<section class="panel rp-praise" aria-labelledby="rp-praise-title">')
        self.assertIn('<h2 id="rp-praise-title">손님 칭찬 요약</h2>', html)
        self.assertRegex(html, r'id="rp-praise-state"[^>]*role="status"')
        self.assertIn('<div id="rp-praise"></div>', html)
        self.assertLess(html.index('id="rp-score"'), html.index('id="rp-praise"'))
        self.assertLess(html.index('id="rp-praise"'), html.index('id="rp-month"'))
        titles = re.findall(r'<h2 id="rp-[\w-]+-title">([^<]+)</h2>', html)
        self.assertEqual(titles, ["오늘 요약", "응대 점수", "손님 칭찬 요약", "월간 보고서", "상권 요약", "마케팅 요약"])

    def test_new_ids_exist_and_every_report_id_keeps_the_prefix(self):
        ids = re.findall(r'id="([\w-]+)"', report_html())
        self.assertEqual([i for i in ids if not i.startswith("rp-")], [])
        self.assertEqual(len(ids), len(set(ids)))
        for i in ("rp-praise", "rp-praise-state", "rp-praise-title", "rp-praise-period", "rp-pdf", "rp-pdf-msg",
                  "rp-print-head", "rp-print-store", "rp-print-meta", "rp-print-note"):
            self.assertIn(i, ids)
        self.assertEqual(HTML.count('id="rp-praise"'), 1)

    def test_pdf_button_is_in_the_head_row_and_the_monthly_print_link_stays(self):
        row = re.search(r'<div class="row rp-head-row">[\s\S]*?</div>', report_html()).group(0)
        self.assertRegex(row, r'<button id="rp-pdf" type="button"[^>]*>전체 리포트 PDF 저장</button>')
        self.assertIn('id="rp-reload"', row)
        self.assertRegex(row, r'id="rp-pdf-msg"[^>]*role="status"')
        link = re.search(r'<a id="rp-print"[^>]*>', report_html()).group(0)       # 예전 월간 인쇄 링크는 그대로
        self.assertIn('href="/api/care/report/monthly/print"', link)
        self.assertIn('target="_blank"', link)

    def test_print_header_is_inside_the_report_view_and_hidden_on_screen(self):
        html = report_html()
        self.assertLess(html.index('id="rp-print-head"'), html.index('class="page-head"'))     # 인쇄에서 맨 위
        self.assertIn(".rp-print-head { display: none; }", CSS)
        self.assertNotRegex(html, r'id="rp-print-head"[^>]*\bhidden\b')     # hidden 속성이면 인쇄에서도 못 보인다 ([hidden] !important)


class PraiseScript(unittest.TestCase):
    def test_praise_is_drawn_from_the_monthly_response_without_another_request(self):
        js = code(report_js())
        paths = re.findall(r"""careApi\(\s*["'`]([^"'`$]+)""", js)
        self.assertEqual(sorted(set(paths)), ["/api/approvals", "/api/care/report/daily", "/api/care/report/monthly", "/api/care/response"])
        self.assertEqual(len(paths), 4)                                  # 칭찬 요약·PDF 저장이 요청을 더하지 않았다
        praise = function(js, "function rpPraise(m, error) {")
        self.assertIn("m?.praise", praise)
        self.assertNotIn("careApi", praise)
        self.assertNotIn("fetch(", praise)
        month = function(js, "async function rpMonth(month) {")
        self.assertIn("rpPraise(m);", month)                             # 월간 응답을 받은 그 자리에서
        self.assertIn("rpPraise(null, e.message);", month)               # 월간을 못 받으면 칭찬 칸에도 그 안내
        self.assertIn('praise: "rp-praise-state"', js)

    def test_praise_fields_and_server_text_is_escaped(self):
        praise = function(report_js(), "function rpPraise(m, error) {")
        for field in ("p.high_rating_count", "p.positive_count", "p.top_topics", "p.top_menus", "p.quote", "p.review_count", "p.praise_count"):
            self.assertIn(field, praise)
        for safe in ("esc(t.topic_name)", "esc(t.count)", "esc(x.menu)", "esc(x.count)", "esc(p.quote.text)", "esc(p.quote.rating)"):
            self.assertIn(safe, praise)
        inserted = re.findall(r"\$\{([^{}]+)\}", praise.replace("${i + 1}", ""))
        raw = [x for x in inserted if any(k in x for k in ("p.", "t.", "x.")) and "esc(" not in x
               and not x.strip().startswith(("topics.map", "menus.map", "p.quote ?", "p.quote.rating ?", "p.praise_basis ==="))]
        self.assertEqual(raw, [], "서버 값은 esc() 를 거쳐서만 넣는다")
        for text in ("별점 4~5점", "긍정 리뷰", "칭찬 주제 상위", "인기 메뉴 TOP 3", "대표 칭찬 한 줄", "모델 호출 없음", "아직 칭찬 리뷰가 없어요"):
            self.assertIn(text, praise)

    def test_praise_and_pdf_never_wake_the_model(self):
        js = code(report_js())
        for banned in ("/api/cards", "/api/briefing", "/run", "/api/assistant", "drawerApi", "refresh(", "chatStart"):
            self.assertNotIn(banned, js)

    def test_window_print_is_called_in_one_place(self):
        self.assertEqual(JS.count("window.print("), 1)
        pdf = function(report_js(), "async function rpPdf() {")
        self.assertIn("window.print();", pdf)
        self.assertLess(pdf.index("rpPrintPrep();"), pdf.index("window.print();"))       # 머리글·펼침을 먼저
        self.assertIn("if (!rpReady())", pdf)                                           # 불러오는 중이면 기다린다
        self.assertIn("button.disabled = true;", pdf)
        self.assertLess(pdf.index("if (!rpReady())"), pdf.index("window.print();"))
        self.assertIn('if (currentRoute() !== "report") return;', pdf)
        self.assertNotIn("careApi", pdf)
        self.assertIn('$("rp-pdf").addEventListener("click", rpPdf);', JS)
        self.assertIn("const rpReady = () => state.booted && !rp.loading && !rp.mktBusy;", JS)

    def test_print_marks_the_report_view_and_opens_folded_parts(self):
        js = report_js()
        self.assertIn('function rpMark() { document.documentElement.classList.toggle("rp-view", currentRoute() === "report"); }', js)
        self.assertIn("rpMark();", function(js, "function loadReport(force = false) {"))
        self.assertRegex(js, r"function rpStop\(\) \{[^\n]*rpMark\(\); \}")           # 다른 화면으로 가면 표시를 뗀다 (route 가 rpStop 을 부름)
        prep = function(js, "function rpPrintPrep() {")
        for i in ("rp-print-store", "rp-print-meta", "rp-print-note"):
            self.assertIn(f'$("{i}").textContent', prep)
        self.assertIn("details:not([open])", prep)
        self.assertIn("state.health?.mode_notice", prep)                               # 시험용 실행 안내는 인쇄에도
        self.assertIn("rpTrendWidth(RP_PRINT_W);", prep)                               # 창이 좁아도 종이에서는 같은 그래프
        done = function(js, "function rpPrintDone() {")
        self.assertIn("details[data-rp-opened]", done)
        self.assertIn("rpTrendWidth();", done)                                         # 인쇄 뒤에는 화면 폭으로 되돌림
        self.assertIn('window.addEventListener("beforeprint"', JS)
        self.assertIn('window.addEventListener("afterprint", rpPrintDone);', JS)


class PrintStyles(unittest.TestCase):
    def test_page_is_a4(self):
        page = re.search(r"@page\s*\{([^}]*)\}", print_css())
        self.assertTrue(page, "@media print 안에 @page 가 없음")
        self.assertRegex(page.group(1), r"size:\s*A4\b")
        self.assertRegex(page.group(1), r"margin:\s*\d")

    def test_every_report_rule_is_scoped_to_the_report_view(self):
        scoped = [(sel, body) for sel, body in print_rules() if not sel.startswith("@page")]
        self.assertGreater(len(scoped), 15)
        for sel, _ in scoped:
            for one in sel.split(","):
                self.assertRegex(one.strip(), r"^html(:root)?\.rp-view\b", f"리포트 화면 밖에도 먹는 인쇄 규칙: {one.strip()}")
        fallback = block(print_chunk(), "@supports not selector(:has(*)) {")
        for sel, _ in rules(block(fallback, "@media print {")):
            for one in sel.split(","):
                self.assertRegex(one.strip(), r"^html\.rp-view\b")

    def test_only_the_report_is_shown(self):
        hide = [sel for sel, body in print_rules() if ':not([data-view="report"])' in sel and "display: none !important" in body]
        self.assertEqual(len(hide), 1)
        self.assertIn(':not([data-view="report"] *)', hide[0])                 # 리포트 안쪽은 건드리지 않고
        self.assertIn(':not(:has([data-view="report"]))', hide[0])             # 리포트를 품은 뼈대도 남긴다
        # :has 를 못 쓰는 브라우저용 대체 규칙
        fallback = block(print_chunk(), "@supports not selector(:has(*)) {")
        self.assertIn("@media print", fallback)
        for part in ("body > :not(.shell)", ".shell > :not(main)", '.shell > main > :not([data-view="report"])', "display: none !important"):
            self.assertIn(part, fallback)
        # 리포트 안의 버튼·화면용 제목 줄·월간 인쇄 링크도 숨긴다
        inner = next(sel for sel, body in print_rules() if "button" in sel and "display: none !important" in body)
        for part in ('[data-view="report"] .page-head', '[data-view="report"] button', ".rp-print"):
            self.assertIn(part, inner)
        shown = dict(print_rules())["html.rp-view .rp-print-head"]
        self.assertIn("display: block", shown)

    def test_light_paper_even_in_dark_theme(self):
        tokens = dict(print_rules())["html:root.rp-view"]                         # 다크 토큰(:root:not([data-theme="light"]))보다 앞선다
        self.assertIn("color-scheme: light", tokens)
        light = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", block(CSS, ":root {")))
        dark = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", block(block(CSS, "@media (prefers-color-scheme: dark) {"), ':root:not([data-theme="light"]) {')))
        printed = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", tokens + ";"))
        self.assertEqual(sorted(set(dark) - set(printed)), [], "다크에서 바뀌는 색 토큰은 인쇄에서 모두 다시 정한다")
        for name in ("--bg", "--panel", "--ink"):
            self.assertEqual(printed[name].strip(), light[name].strip())
        page = next(body for sel, body in print_rules() if sel == "html.rp-view, html.rp-view body")
        self.assertIn("background: #ffffff !important", page)

    def test_panels_do_not_split_and_colors_print(self):
        panel = dict(print_rules())["html.rp-view .rp-grid > .panel"]
        self.assertIn("break-inside: avoid", panel)
        self.assertIn("display: block", dict(print_rules())["html.rp-view .rp-grid"])
        exact = next(body for sel, body in print_rules() if sel.startswith('html.rp-view [data-view="report"], html.rp-view [data-view="report"] *'))
        self.assertIn("print-color-adjust: exact", exact)
        self.assertIn("-webkit-print-color-adjust: exact", exact)

    def test_print_block_follows_the_report_styles(self):
        chunk = print_chunk()
        self.assertLess(chunk.index("@media print {"), chunk.index("@supports not selector(:has(*)) {"))    # 본 덩어리 → :has 대체 덩어리
        self.assertLess(CSS.index(".rp-print-head { display: none; }"), CSS.index(PRINT_HEAD))              # 리포트 스타일 바로 뒤
        self.assertLess(CSS.index("#rp-approvals {"), CSS.index(PRINT_HEAD))
        self.assertIn(".rp-table-wrap { overflow-x: auto;", CSS)                # 화면 규칙은 그대로 (인쇄에서만 풀어 줌)


class FakeCareWithPraise(FakeCare):
    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == P + "/report/monthly":
            return httpx.Response(200, json={"month": "2026-11", "until": "2026-11-16T15:00:00+09:00", "review_count": 18,
                                             "score_trend": [], "repeated_issues": [], "praise": PRAISE})
        if request.method == "GET" and request.url.path == P + "/report/daily":
            return httpx.Response(200, json={"date": "2026-11-16", "summary": "11월 16일: 리뷰 0건", "review_count": 0, "praise": EMPTY})
        return super().__call__(request)


class ProxyPassesPraise(unittest.TestCase):
    def test_monthly_and_daily_praise_reach_the_browser_unchanged(self):
        client, _, _ = build(FakeCareWithPraise())
        monthly = client.get("/api/care/report/monthly?month=2026-11")
        self.assertEqual(monthly.status_code, 200)
        self.assertEqual(monthly.json()["praise"], PRAISE)
        self.assertEqual(monthly.json()["praise"]["quote"]["text"], "순두부찌개 얼큰하고 맛있어요")
        daily = client.get("/api/care/report/daily").json()
        self.assertEqual(daily["praise"], EMPTY)                                # 빈 목록·null 도 그대로
        self.assertIsNone(daily["praise"]["quote"])


if __name__ == "__main__":
    unittest.main()
