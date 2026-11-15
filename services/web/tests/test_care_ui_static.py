"""'캡처로 넣기'(리뷰 붙여넣기 탭)와 '종합 리포트'(#/report) 화면 파일을 글자로 읽어 확인하는 정적 시험. 서버·브라우저를 띄우지 않는다.

지키는 것
- 캡처 칸 id 는 cap- 로, 리포트 id 는 rp- 로 시작하고, JS 가 찾는 id 는 모두 index.html 에 (또는 JS 가 직접 만듦).
- 두 화면은 careApi 로만 부른다: /api/care/*, 캡처 저장용 /api/reviews, 승인 기록 /api/approvals. 전역 api()·showAlert(#alert) 를 쓰지 않는다.
- 캡처: png·jpg·webp, 예시 결과(demo)·warnings·별점 확인 안내, 이미 있는 리뷰는 처음에 고르지 않음, 저장은 source=capture.
- 리포트: 메뉴 자리(data-route="report")와 화면(data-view="report"), 세 응대 칸 + 상권·마케팅 요약, 남은 시간(due_at)·멈춤·지난 불만,
  월간 표의 칸, SVG 그래프(외부 라이브러리 없음), 인쇄용 보기 링크, 열 때 AI 를 새로 부르지 않음.

실행 (services/web 에서): PYTHONPATH=<저장소 루트>:. python -m pytest -q tests/test_care_ui_static.py
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")


def care_js() -> str:
    """app.js 의 고객응대 덩어리: '── 고객응대 호출' 머리부터 '── 준비 중 자리' 앞까지."""
    start = JS.index("// ── 고객응대 호출")
    return JS[start:JS.index("// ── 준비 중 자리", start)]


def report_js() -> str:
    js = care_js()
    return js[js.index("// ── 종합 리포트"):]


def code(js: str) -> str:
    return re.sub(r"//[^\n]*", "", js)       # 주석 속 설명 글자는 빼고 본다


def section(pattern: str) -> str:
    m = re.search(pattern, HTML)
    assert m, pattern
    return m.group(0)


CAP_HTML = section(r'<section id="cap"[\s\S]*?</section>')
REPORT_HTML = section(r'<section class="view" data-view="report"[\s\S]*?\n    </section>')


class Markup(unittest.TestCase):
    def test_capture_panel_sits_in_the_paste_tab(self):
        paste_tab = section(r'<div id="an-paste"[\s\S]*?<section id="cap"')
        self.assertIn('id="paste-text"', paste_tab)                    # 붙여넣기 상자 바로 옆(아래)
        ids = re.findall(r'id="([\w-]+)"', CAP_HTML)
        self.assertEqual([i for i in ids if i != "cap" and not i.startswith("cap-")], [])

    def test_report_ids_use_the_prefix(self):
        ids = re.findall(r'id="([\w-]+)"', REPORT_HTML)
        self.assertTrue(ids)
        self.assertEqual([i for i in ids if not i.startswith("rp-")], [])

    def test_every_id_the_care_script_uses_exists(self):
        js = care_js()
        used = set(re.findall(r"""\$\(\s*["']((?:cap|rp)-[\w-]+)["']\s*\)""", js))
        used |= set(re.findall(r""":\s*"(rp-[\w-]+-state)\"""", js))           # RP_STATE 표
        self.assertIn("rp-daily-state", used)
        made = set(re.findall(r'id="([\w-]+)"', HTML)) | set(re.findall(r'id="([\w-]+)"', JS))
        self.assertEqual(sorted(used - made), [])

    def test_file_input_and_buttons(self):
        box = re.search(r'<input id="cap-file"[^>]*>', CAP_HTML).group(0)
        self.assertIn('type="file"', box)
        self.assertIn('accept="image/png,image/jpeg,image/webp"', box)
        for i in ("cap-choose", "cap-send", "cap-save"):
            self.assertRegex(CAP_HTML, rf'<button id="{i}" type="button"')
        self.assertIn("선택한 리뷰 저장", CAP_HTML)

    def test_status_error_and_honesty_places(self):
        self.assertRegex(CAP_HTML, r'id="cap-status"[^>]*role="status"')
        self.assertRegex(CAP_HTML, r'id="cap-error"[^>]*role="alert"')
        self.assertIn("예시 결과 — 이미지를 실제로 읽지 않았어요", CAP_HTML)
        self.assertIn("별점", re.search(r'<p class="cap-star">[\s\S]*?</p>', CAP_HTML).group(0))
        self.assertIn("잘못 읽을", CAP_HTML)

    def test_report_menu_and_view(self):
        menu = section(r'<div class="menu">[\s\S]*?</div>')
        self.assertIn('href="#/report" data-route="report"', menu)
        self.assertLess(menu.index('data-route="analysis"'), menu.index('data-route="report"'))
        self.assertIn("종합 </span>리포트", menu)
        self.assertIn('"report"', JS[JS.index("const ROUTES"):JS.index("\n", JS.index("const ROUTES"))])
        self.assertIn('<h1 tabindex="-1">종합 리포트</h1>', REPORT_HTML)
        for name in ("daily", "score", "month", "market", "mkt"):
            self.assertRegex(REPORT_HTML, rf'id="rp-{name}-state"[^>]*role="status"')
            self.assertIn(f'id="rp-{name}"', REPORT_HTML)

    def test_print_link_opens_in_a_new_tab(self):
        link = re.search(r'<a id="rp-print"[^>]*>', REPORT_HTML).group(0)
        self.assertIn('href="/api/care/report/monthly/print"', link)
        self.assertIn('target="_blank"', link)
        self.assertIn('rel="noopener"', link)
        self.assertIn('"/api/care/report/monthly/print" + (rp.month ? `?month=${encodeURIComponent(rp.month)}`', JS)

    def test_no_external_libraries(self):
        self.assertEqual(re.findall(r'<script[^>]*src="([^"]+)"', HTML), ["/static/app.js"])
        self.assertNotRegex(HTML + JS, r"https?://(cdn|unpkg|cdnjs)")


class Script(unittest.TestCase):
    def test_calls_only_care_paths_and_never_the_page_alert(self):
        js = code(care_js())
        paths = re.findall(r"""careApi\(\s*["'`]([^"'`$]+)""", js)
        self.assertTrue(paths)
        allowed = ("/api/care/", "/api/reviews", "/api/approvals")
        self.assertTrue(all(p.startswith(allowed) for p in paths), paths)
        for p in ("/api/care/reviews/capture", "/api/reviews", "/api/care/report/daily", "/api/care/response",
                  "/api/care/report/monthly", "/api/approvals"):
            self.assertIn(p, paths)
        self.assertIsNone(re.search(r"(?<![\w.])api\(", js), "전역 api() 대신 careApi 로만 부른다")
        self.assertNotIn("showAlert", js)
        self.assertNotIn('$("alert")', js)
        self.assertNotIn("/api/review-insight", HTML + JS)

    def test_fetch_options(self):
        js = care_js()
        self.assertIn('credentials: "same-origin"', js)
        self.assertIn("AbortController", js)
        self.assertIn("CAP_WAIT_MS = 110000", js)                       # 서버 100초보다 조금 길게
        self.assertIn('typeof options.body === "string"', js)           # FormData 에는 Content-Type 을 직접 달지 않는다

    def test_capture_rules(self):
        js = care_js()
        self.assertIn('CAP_TYPES = ["image/png", "image/jpeg", "image/webp"]', js)
        self.assertIn("CAP_MAX_BYTES = 10 * 1024 * 1024", js)
        self.assertIn('${c.duplicate ? "" : " checked"}', js)           # 이미 있는 리뷰는 처음에 고르지 않음
        self.assertIn("개인정보 가림", js)
        self.assertIn("이미 있는 리뷰", js)
        self.assertIn('$("cap-demo").hidden = r?.demo !== true', js)
        self.assertIn('$("cap-warnings").innerHTML = warns.map((w) => `<li>${esc(w)}</li>`)', js)
        self.assertIn('source: "capture"', js)
        self.assertIn('maxlength="1000"', js)
        self.assertIn("최대 5조각", js)                                  # 오래 걸리는 이유를 진행 표시에서 알림
        self.assertIn("capErr(e.message)", js)                           # 서버 문장을 그 칸 안에

    def test_report_never_wakes_the_model(self):
        js = code(report_js())
        for banned in ("/api/cards", "/api/briefing", "/run", "/api/assistant", "drawerApi", "refresh(", "chatStart"):
            self.assertNotIn(banned, js)
        boot = JS[JS.index("async function boot()"):JS.index("applyTheme();")]
        self.assertNotIn("/api/care", boot)                              # 처음 화면을 열 때는 고객응대를 부르지 않는다
        self.assertIn('if (name === "report") loadReport(); else rpStop();', JS)

    def test_report_countdown_pause_and_untimed(self):
        js = report_js()
        self.assertIn("Date.parse(p.due_at)", js)
        self.assertIn("p.remaining_seconds", js)
        self.assertIn("rp.tick = setInterval(rpTick, 1000)", js)
        self.assertIn("멈춤", js)
        self.assertIn("r.peak_now === true", js)
        self.assertIn("p.paused === true", js)
        self.assertIn("지난 불만", js)
        self.assertIn("untimed_unanswered", js)
        self.assertIn("x.message", js)                                   # 점수 이유는 서버 문장 그대로

    def test_monthly_table_and_chart(self):
        js = report_js()
        for field in ("topic_name", "review_count", "count_this_month", "replied_count", "recurred_after_reply", "state", "main_time_band"):
            self.assertIn(f"i.{field}", js)
        self.assertIn("score_trend", js)
        self.assertIn('<svg class="rp-trend"', js)
        self.assertIn('role="img"', js)
        self.assertIn("<polyline", js)
        self.assertIn("suggestions", js)
        self.assertIn("rp-table-wrap", js)
        self.assertIn(".rp-table-wrap { overflow-x: auto;", CSS)          # 375px 에서 표만 옆으로 밀림

    def test_daily_fields(self):
        js = report_js()
        for field in ("d.summary", "d.review_count", "d.complaint_count", "d.replied_on_time", "d.replied_late",
                      "d.score_start", "d.score_end", "d.changes", "d.todo"):
            self.assertIn(field, js)

    def test_market_and_marketing_use_only_what_the_page_already_has(self):
        js = report_js()
        market = js[js.index("function rpMarket()"):js.index("async function rpMarketing()")]
        self.assertIn("state.briefing", market)
        self.assertNotIn("careApi", market)
        self.assertIn("우리 가게 매출이 아니에요", market)
        marketing = js[js.index("async function rpMarketing()"):]
        self.assertIn("state.cards", marketing)
        self.assertIn('kind === "promo"', marketing)

    def test_approve_sends_the_review_hint_for_replies(self):
        self.assertIn("const hint = d.target_review_id ? { kind: d.generator, review_id: d.target_review_id } : {};", JS)
        self.assertIn("original: d.text, ...hint", JS)


if __name__ == "__main__":
    unittest.main()
