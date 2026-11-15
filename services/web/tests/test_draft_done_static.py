"""승인할 글(#/draft)·처리 완료(#/done) 화면 파일을 글자로 읽어 확인하는 정적 시험 (11/16). 서버·브라우저를 띄우지 않는다.

지키는 것
- 초안 상자 안 '다시 만들기'(data-regen = 글 id)는 그 글 한 건만 다시 만든다: generator(+review_id)를 보내고, 그 글의 승인·고친 내용만 지운다.
- '카드 전체 다시 만들기'(data-rerun = 카드 id)는 진행줄 옆 보조 버튼이고, 승인했거나 고친 글이 있으면 한 번 더 눌러야 실행한다 (대화상자 없음).
- 완료 화면의 주 버튼은 '홈으로'(진행을 그대로 두고 대시보드로), 옆의 보조 버튼 id="restart" 는 '처음부터 다시'이고 서버 승인 기록도 지운다.
- 불만 카드의 조치 고르기는 '오늘부터 실천할 주방 점검 수칙'으로 보이고, 완료 화면에도 고른 수칙 목록이 나온다.

실행 (services/web 에서): PYTHONPATH=<저장소 루트>:. python -m pytest -q tests/test_draft_done_static.py
"""
from __future__ import annotations

import functools
import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "web" / "static"
JS = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")


def code(js: str) -> str:
    return re.sub(r"//[^\n]*", "", js)       # 주석 속 설명 글자는 빼고 본다


@functools.lru_cache(maxsize=None)
def func(name: str) -> str:
    """app.js 의 맨 위 함수 하나 (다음 맨 위 선언 앞까지). 없으면 그 시험만 실패한다 (파일을 읽는 단계에서 멈추지 않게)."""
    m = re.search(rf"^(?:async )?function {name}\(", JS, re.M)
    if not m:
        raise AssertionError(f"app.js 에 function {name} 이 없음")
    rest = JS[m.end():]
    nxt = re.search(r"^(?:async function |function |const |let |// ── )", rest, re.M)
    return JS[m.start():m.end() + (nxt.start() if nxt else len(rest))]


class RegenerateOneDraft(unittest.TestCase):
    def test_button_inside_the_draft_box_regenerates_only_that_draft(self):
        article = func("renderDraft")[func("renderDraft").index('<article class="draft'):func("renderDraft").index("</article>")]
        button = re.search(r"<button[^>]*data-regen=[^>]*>[^<]*", article).group(0)
        self.assertIn('data-regen="${esc(d.draft_id)}"', button)                 # 값은 글 id
        self.assertIn("다시 만들기", button)
        self.assertIn('class="ghost"', button)
        self.assertNotIn("data-rerun", article)                                  # 카드 전체 버튼은 초안 상자 밖
        self.assertIn('el.querySelectorAll("[data-regen]").forEach((b) => b.addEventListener("click", () => regenDraft(b.dataset.regen)));',
                      func("renderDraft"))

    def test_request_names_the_one_draft(self):
        self.assertIn("const body = { generator: d.generator };", func("regenDraft"))
        self.assertIn("if (d.target_review_id) body.review_id = d.target_review_id;", func("regenDraft"))
        self.assertIn("body.measures = (r.chosen_measures || []).map((m) => m.id);", func("regenDraft"))   # 처음 고른 수칙 그대로
        self.assertIn("body.reply_texts", func("regenDraft"))                                  # 공지: 지금 화면의 묶음 답글
        self.assertIn("!pasted.has(x.target_review_id)", func("regenDraft"))                   # 붙여넣은 리뷰의 답글은 빼고
        self.assertIn("api(`/api/cards/${encodeURIComponent(cardId)}/run`, { method: \"POST\", body: JSON.stringify(body) })", func("regenDraft"))

    def test_only_that_drafts_approval_and_edit_are_dropped(self):
        js = code(func("regenDraft"))
        for line in ("state.approved.delete(gone);", "delete state.pending[gone];",
                     "state.approvedLog = state.approvedLog.filter((x) => x.id !== gone);", "r.drafts[at] = fresh;"):
            self.assertIn(line, js)
        for wipe in ("state.results[cardId] = ", "state.approved.clear()", "state.pending = {}", "state.approvedLog = []", "runCard("):
            self.assertNotIn(wipe, js)                                            # 다른 글의 승인·고친 내용은 건드리지 않는다
        self.assertIn("state.results[cardId] === r", js)                          # 기다리는 동안 카드가 바뀌면 늦게 온 글은 버린다
        self.assertIn("renderDraft();", js[:js.index("await api(")])              # 부르기 전에 다시 그린다 → saveEdits 가 고치던 글을 담아 둔다
        self.assertIn("function renderDraft() {\n  saveEdits();", JS)

    def test_whole_card_button_sits_by_the_progress_line_and_asks_twice(self):
        progress = func("renderDraft")[func("renderDraft").index('<div class="progress">'):func("renderDraft").index('<ol class="draft-list"')]
        self.assertIn('<button type="button" class="ghost" data-rerun="${esc(state.current)}">${RERUN_LABEL}</button>', progress)
        self.assertIn('const RERUN_LABEL = "카드 전체 다시 만들기";', JS)
        self.assertIn("data-rerun-note", progress)
        self.assertIn('role="status"', progress)
        self.assertIn('el.querySelectorAll("[data-rerun]").forEach((b) => b.addEventListener("click", () => rerunCard(b.dataset.rerun, b)));',
                      func("renderDraft"))
        rerun = func("rerunCard")
        self.assertIn("if (touchedOf(cardId) && rerunArm.card !== cardId) {", rerun)          # 승인했거나 고친 글이 있으면 첫 누름은 알리기만
        self.assertLess(rerun.index("return;"), rerun.index("await runCard(cardId, button);"))
        self.assertIn("state.approved.has(d.draft_id) || isEdited(d)", JS)
        self.assertIn("한 번 더 누르면 이 카드의 글을 모두 다시 만들어요", func("rerunPaint"))
        self.assertIsNone(re.search(r"(?<![\w.])confirm\(", code(JS)))                          # 대화상자는 쓰지 않는다

    def test_whole_card_rerun_also_forgets_the_old_approvals_on_the_done_screen(self):
        self.assertIn("state.approvedLog = state.approvedLog.filter((x) => !gone.has(x.id));", func("runCard"))

    def test_new_attribute_and_classes_exist(self):
        self.assertIn(".progress .ghost {", CSS)
        self.assertIn(".draft-note:empty { display: none; }", CSS)


class DoneScreen(unittest.TestCase):
    def test_home_is_the_main_button_and_restart_is_the_secondary_one(self):
        self.assertIn('<button type="button" class="primary big" data-home>홈으로</button>', func("renderDone"))
        self.assertIn('<button type="button" class="ghost" id="restart">처음부터 다시</button>', func("renderDone"))
        self.assertLess(func("renderDone").index("data-home"), func("renderDone").index('id="restart"'))    # 나란히, 주 버튼이 먼저
        self.assertEqual(func("renderDone").count('class="primary big"'), 1)                          # 주 버튼은 하나
        row = func("renderDone")[func("renderDone").index('<div class="row done-actions">'):func("renderDone").index("</div>", func("renderDone").index("data-home"))]
        self.assertIn('id="restart"', row)
        self.assertNotIn(">처음으로<", JS)                                                      # 오해를 부르던 예전 주 버튼 문구

    def test_home_keeps_the_progress(self):
        self.assertIn('el.querySelector("[data-home]").addEventListener("click", () => go("today"));', func("renderDone"))
        self.assertNotIn("state.results = {}", func("renderDone"))

    def test_restart_clears_the_screen_and_the_servers_approvals(self):
        self.assertIn('$("restart").addEventListener("click", (e) => restart(e.currentTarget));', func("renderDone"))
        self.assertIn('await api("/api/approvals", { method: "DELETE" });', func("restart"))
        self.assertIn("state.results = {}; state.approved.clear(); state.approvedLog = []; state.pending = {};", func("restart"))
        self.assertIn('go("today");', func("restart"))
        js = code(func("restart"))
        self.assertLess(js.index("catch (e)"), js.index("state.results = {}"))                 # 서버가 못 지워도 화면은 비운다
        self.assertIn("showAlert(", js[js.index("state.results = {}"):])                       # 그리고 알림 띠로 알린다

    def test_done_screen_lists_the_rules_the_owner_picked(self):
        self.assertIn("made?.chosen_measures", func("renderDone"))
        self.assertIn('p.card.kind === "complaint"', func("renderDone"))
        self.assertIn("<h2>${RULES_TITLE}</h2>", func("renderDone"))
        self.assertIn("rules.map((m) => `<li>${esc(m.text)}</li>`)", func("renderDone"))
        self.assertIn('made?.source === "seed"', func("renderDone"))                                  # 시험용 실행에서는 글에 반영됐다고 말하지 않는다
        self.assertIn(".done-actions .big {", CSS)


class RulesWording(unittest.TestCase):
    def test_measures_read_as_things_to_do_in_the_shop(self):
        self.assertIn('const RULES_TITLE = "오늘부터 실천할 주방 점검 수칙";', JS)
        box = func("measureBox")
        self.assertIn('<legend class="small">${RULES_TITLE}${mock ? "" : " (공지에 반영)"}</legend>', box)
        self.assertIn('const mock = state.health?.mode === "mock";', box)            # 시험용 실행에서는 글에 반영된다고 말하지 않는다
        self.assertIn("const picked = made ? new Set(made.map((x) => x.id)) : on;", box)   # 만든 카드는 고른 수칙을 그대로 체크해 둔다
        self.assertIn("${RULES_TITLE}: ${r.chosen_measures.map((m) => esc(m.text)).join(\", \")}", func("renderDraft"))
        for old in ("공지에 넣을 재발 방지 조치", "사장님이 고른 재발 방지 조치"):
            self.assertNotIn(old, code(JS))

    def test_measure_box_still_sends_what_the_measuring_script_expects(self):
        box = func("measureBox")
        self.assertIn("const on = new Set(m.default || []);", box)
        self.assertIn('data-measure="${esc(p.card.card_id)}" value="${esc(o.id)}"', box)


if __name__ == "__main__":
    unittest.main()
