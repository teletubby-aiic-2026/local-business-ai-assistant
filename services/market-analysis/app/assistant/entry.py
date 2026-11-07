"""Button from the B1~B6 page to the chat page, added only when the assistant is enabled.

PR #12's onboarding HTML file is not edited. The server adds one stylesheet
link and one anchor while serving the page, so with ASSISTANT_ENABLED off the
page is exactly PR #12's file. Both pages share the session cookie, so the
chat opens with the conditions chosen on this page.
"""
from __future__ import annotations

from pathlib import Path

STYLESHEET = '<link rel="stylesheet" href="/assistant-assets/entry.css">'
BUTTON = ('<a class="assistant-entry" href="/assistant" title="지금 설정한 가게·상권 조건으로 대화해요">'
          '<span class="assistant-entry-mark" aria-hidden="true">AI</span>'
          '<span>상권 비서에게 물어보기</span></a>')


def onboarding_html(path: Path) -> str:
    html = path.read_text(encoding="utf-8")
    if html.count("</head>") != 1 or html.count("</body>") != 1:
        return html  # unexpected markup: serve it unchanged rather than guess
    return html.replace("</head>", STYLESHEET + "\n</head>").replace("</body>", BUTTON + "\n</body>")
