"""내 계정 화면(11/19): 기록 지우기. 화면 파일을 글자로 읽는다.

서버 약속(POST /api/auth/reset)은 백엔드가 따로 만든다. 여기서는 화면이 약속대로 부르는지·확인 단계가 안전한지만 본다.
node 가 있으면 작은 순수 함수(acctSummary)를 실제로 돌려 본다 (없으면 그 한 건만 건너뜀).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")


def block(start: str, end: str) -> str:
    i = JS.index(start)
    return JS[i:JS.index(end, i)]


ACCOUNT = block("// ── 내 계정: 기록 지우기", "// ── 로그인·가게 바꾸기 (5차 회의 11/18)")
AUTH = block("// ── 로그인·가게 바꾸기 (5차 회의 11/18)", "// ── AI 직원 (5차 회의 11/18)")
DIALOG = HTML[HTML.index('<dialog id="acct-dialog"'):HTML.index("</dialog>", HTML.index('<dialog id="acct-dialog"'))]


def code(js: str) -> str:
    return re.sub(r"//[^\n]*", "", js)


def func(name: str) -> str:
    i = JS.index(f"function {name}(")
    ends = [x for x in (JS.find("\nfunction ", i + 1), JS.find("\nasync function ", i + 1), JS.find("\nconst ", i + 1)) if x > 0]
    return JS[i:min(ends)]


def tag(id_: str) -> str:
    i = HTML.index(f'id="{id_}"')
    return HTML[HTML.rindex("<", 0, i):HTML.index(">", i) + 1]


class EntryPoint(unittest.TestCase):
    def test_name_is_the_button_and_the_top_bar_gets_no_new_button(self):
        user = tag("acct-user")
        self.assertTrue(user.startswith("<button"), user)
        for want in ('type="button"', 'aria-haspopup="dialog"', 'aria-controls="acct-dialog"', "hidden"):
            self.assertIn(want, user)
        acct = HTML[HTML.index('<div id="acct" class="acct">'):HTML.index("</div>", HTML.index('<div id="acct" class="acct">'))]
        self.assertEqual(acct.count("<button"), 3)                          # 로그인 · 이름(내 계정) · 로그아웃
        self.assertIn('$("acct-user").addEventListener("click", acctOpen);', JS)
        self.assertIn("if (!acct.me || !acct.me.authenticated) return;", func("acctOpen"))   # 게스트는 열지 않음

    def test_name_button_stays_slim(self):
        rule = re.search(r"button\.acct-user \{([^}]*)\}", CSS).group(1)
        self.assertIn("padding: 4px 8px;", rule)
        self.assertIn("background: transparent;", rule)


class DialogAndActions(unittest.TestCase):
    def test_dialog_comes_after_login_dialog_and_uses_the_same_card(self):
        self.assertLess(HTML.index('<dialog id="auth-dialog"'), HTML.index('<dialog id="acct-dialog"'))
        self.assertIn('class="auth-dialog acct-dialog"', DIALOG)
        self.assertIn('aria-labelledby="acct-title"', DIALOG)
        self.assertIn("showModal", func("acctOpen"))

    def test_account_info_and_actions(self):
        for id_ in ("acct-info-name", "acct-info-id", "acct-info-stores", "acct-close", "acct-reset-store", "acct-reset-all"):
            self.assertIn(f'id="{id_}"', DIALOG)
        self.assertIn('data-acct-act="store"', DIALOG)
        self.assertIn('data-acct-act="account"', DIALOG)
        info = func("acctInfo")
        self.assertIn('u.demo ? "시연 계정"', info)
        self.assertIn("`${acctStoreName()} 기록 지우기`", info)               # 지금 가게 이름을 버튼 글자에

    def test_confirm_step_says_what_goes_and_what_stays(self):
        for id_ in ("acct-confirm", "acct-confirm-title", "acct-confirm-gone", "acct-confirm-kept", "acct-cancel", "acct-go"):
            self.assertIn(f'id="{id_}"', DIALOG)
        self.assertIn("되돌릴 수 없어요", DIALOG)
        self.assertRegex(DIALOG, r'<button id="acct-cancel"[^>]*type="button"')
        self.assertRegex(DIALOG, r'<button id="acct-go" class="danger" type="submit"')
        self.assertRegex(DIALOG, r'id="acct-error"[^>]*role="alert"')
        acts = ACCOUNT[ACCOUNT.index("const ACCT_ACTS = {"):ACCOUNT.index("const ACCT_MKT")]
        for word in ("승인 기록", "붙여넣은 리뷰", "맞춤 마케팅 기록", "AI에게 묻기 대화"):
            self.assertGreaterEqual(acts.count(word), 2, word)               # 이 가게 · 모든 가게 둘 다
        self.assertIn("상권 자료 같은 공용 자료", ACCOUNT)
        self.assertIn("다른 가게의 기록", acts)


class SafeConfirm(unittest.TestCase):
    def test_default_focus_is_cancel(self):
        # 확인 단계를 그린 마지막 일이 [취소]에 포커스 (Enter 한 번으로 지워지지 않게)
        self.assertRegex(func("acctStep"), r'\$\("acct-cancel"\)\.focus\(\);[^\n]*\n\}\s*$')

    def test_escape_cancels_the_confirm_step_and_waits_while_busy(self):
        esc = JS[JS.index('$("acct-dialog").addEventListener("keydown"'):JS.index('$("acct-dialog").addEventListener("cancel"')]
        self.assertIn('e.key !== "Escape"', esc)
        self.assertIn("acctX.busy || acctX.act", esc)
        self.assertIn("e.preventDefault();", esc)
        self.assertIn("acctCancel();", esc)
        self.assertIn("if (acctX.busy) return;", func("acctCancel"))
        self.assertIn("if (acctX.busy) return;", func("acctClose"))

    def test_buttons_are_locked_during_the_request(self):
        lock = func("acctLock")
        self.assertIn("#acct-dialog button, #acct-dialog input", lock)
        self.assertIn("b.disabled = on;", lock)
        sub = code(func("acctSubmit"))
        self.assertIn("if (acctX.busy || !act) return;", sub)
        self.assertLess(sub.index("acctLock(true);"), sub.index("await "))


class Requests(unittest.TestCase):
    def test_chat_is_cleared_before_reset(self):
        sub = code(func("acctSubmit"))
        self.assertLess(sub.index("await acctClearChat();"), sub.index('"/api/auth/reset"'))
        self.assertIn('acctPost("/api/auth/reset", { scope: act })', sub)
        clear = code(func("acctClearChat"))
        self.assertIn('fetch("/api/assistant/conversation", { method: "DELETE"', clear)
        self.assertIn("catch", clear)                                          # 꺼져 있어도·실패해도 계속

    def test_errors_show_server_message_inside_the_dialog(self):
        post = code(func("acctPost"))
        self.assertIn("err.message ||", post)
        self.assertIn("status: res.status, state: err.state", post)
        self.assertIn("인터넷 연결을 확인", post)                             # 네트워크 오류도 쉬운 문장
        sub = code(func("acctSubmit"))
        self.assertIn("acctErr2(err.message);", sub)

    def test_after_reset_every_screen_reads_the_server_again(self):
        sub = code(func("acctSubmit"))
        self.assertIn("await storeChanged();", sub)
        self.assertIn("r.complete === false", sub)
        self.assertIn('"다시 지우기"', sub)
        self.assertIn("acctNotice(`기록을 지웠어요. ${summary}`", sub)
        self.assertIn('acctNotice("");', func("storeChanged"))               # 가게를 바꾸면 지난 결과 띠는 치운다
        self.assertRegex(HTML, r'<div id="acct-notice" class="alert done" role="status" hidden>')

    def test_auth_block_keeps_its_rules(self):
        self.assertNotIn("localStorage", ACCOUNT)
        self.assertNotIn("localStorage", AUTH)
        self.assertNotIn("document.cookie", JS)
        self.assertNotRegex(code(ACCOUNT), r"innerHTML = [^`'\"]*\$\{(?!esc\()")


class Look(unittest.TestCase):
    def test_danger_button_uses_existing_tokens_only(self):
        css = CSS[CSS.index("/* ── 내 계정 대화상자 (11/19)"):CSS.index("/* ── 상권 분석 (#/market, 11/18)")]
        self.assertIn(".danger { background: var(--bad); border-color: var(--bad); color: var(--panel);", css)
        self.assertNotRegex(re.sub(r"/\*[\s\S]*?\*/", "", css), r"--[\w-]+\s*:")
        self.assertNotRegex(css, r"#[0-9a-fA-F]{3,6}\b")


class Banned(unittest.TestCase):
    def test_banned_strings(self):
        for text in (HTML, JS):
            for banned in ("replay", "c9", "/api/review-insight"):
                self.assertNotIn(banned, text)


@unittest.skipUnless(shutil.which("node"), "node 없음")
class SummaryWithNode(unittest.TestCase):
    def test_summary(self):
        src = re.search(r"const ACCT_MKT = .*?;\n", JS).group(0) + func("acctSummary")
        expr = ('[acctSummary({stores:[{store_id:"store_ongi",name:"온기한식",approvals:3,reviews:2,marketing:"cleared"},'
                '{store_id:"store_basak",name:"바삭치킨",approvals:null,reviews:0,marketing:"failed"}]}), acctSummary({}), acctSummary(null)]')
        out = subprocess.run(["node", "-e", f"{src}\nconsole.log(JSON.stringify({expr}));"], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout)
        self.assertEqual(got[0], "온기한식: 승인 기록 3건 · 붙여넣은 리뷰 2건 · 맞춤 마케팅 지움 / "
                                 "바삭치킨: 승인 기록 못 지움 · 붙여넣은 리뷰 0건 · 맞춤 마케팅 못 지움")
        self.assertEqual(got[1:], ["", ""])


if __name__ == "__main__":
    unittest.main()
