"""백엔드 시험이 React 화면 소스(services/web/frontend)를 글자로 읽을 때 쓰는 도움 함수 (11/20 React 단일 화면 전환).

빌드(frontend/dist)나 node 없이 돈다. 화면 문구(UX Writing)는 자주 바뀌므로 여기서는 잘 바뀌지 않는 이름만 찾는다:
주소 해시(#/today …), 내보내는 상수·함수 이름(CHAT_QUARTER · statusOf · REPLACES_MAX …), API 경로.
따옴표·줄바꿈·띄어쓰기 모양이 바뀌어도 찾을 수 있게 정규식과 괄호 짝 맞추기로 읽는다.
찾지 못하면 어느 파일의 무엇을 찾았는지 한국어로 알려 주며 실패한다 (화면 파일을 옮겼다면 이 파일도 같이 고칠 것).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from web.settings import WEB_DIR

FRONTEND = WEB_DIR / "frontend"
SRC = FRONTEND / "src"
TEXT_SUFFIXES = (".js", ".jsx", ".mjs", ".ts", ".tsx", ".css", ".html", ".json", ".svg")
# 화면 8개의 주소 해시 (#/today …). docs/api/contract.md 2.5 · 예전 app.js ROUTES 와 같은 이름
ROUTES = ("today", "cards", "draft", "done", "analysis", "marketing", "report", "market")
NODE = shutil.which("node")


def rel(path: Path) -> str:
    """알림에 쓰는 짧은 경로 (frontend/src/…)."""
    try:
        return str(path.relative_to(FRONTEND.parent))
    except ValueError:
        return str(path)


def read(name: str) -> str:
    """frontend/src 아래 파일 하나 (예: "features/flow/calc.js")."""
    path = SRC / name
    if not path.is_file():
        raise AssertionError(f"화면 소스 {rel(path)} 가 없어요. React 화면 파일을 옮겼다면 tests/frontend_src.py 의 경로도 고쳐 주세요")
    return path.read_text(encoding="utf-8")


def source_files(tests: bool = True) -> list[Path]:
    """frontend/index.html + frontend/src 아래의 모든 글 파일. tests=False 면 *.test.js(x) 는 뺀다."""
    files = [p for p in sorted(SRC.rglob("*")) if p.is_file() and p.suffix in TEXT_SUFFIXES]
    if not tests:
        files = [p for p in files if ".test." not in p.name]
    return [FRONTEND / "index.html", *files]


def squash(text: str) -> str:
    """띄어쓰기·줄바꿈을 모두 빼고 작은따옴표를 큰따옴표로 (모양만 다른 같은 코드를 같게 본다)."""
    return re.sub(r"\s+", "", text).replace("'", '"')


def _balanced(text: str, start: int) -> str:
    """text[start] 의 여는 괄호([ { ()부터 짝이 맞는 닫는 괄호까지. 문자열("…" '…' `…`) 안의 괄호는 세지 않는다."""
    depth, quote, i = 0, None, start
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c in "[{(":
            depth += 1
        elif c in "]})":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    raise AssertionError(f"괄호 짝을 찾지 못했어요: {text[start:start + 60]!r}")


def const_value(text: str, name: str, where: str = "") -> str:
    """`[export] const NAME = …` 의 값 글자. 값이 [ { ( 로 시작하면 짝이 맞는 괄호까지, 아니면 그 줄의 ; 앞까지."""
    m = re.search(rf"(?:^|\n)\s*(?:export\s+)?const\s+{re.escape(name)}\s*=\s*", text)
    if not m:
        raise AssertionError(f"{where or '화면 소스'} 에 const {name} = … 가 없어요")
    rest = text[m.end():]
    if rest[:1] in "[{(":
        return _balanced(rest, 0)
    return rest.split("\n", 1)[0].rstrip().rstrip(";").rstrip()


def function_text(text: str, name: str, where: str = "") -> str:
    """함수 하나의 글자. `function name(…) { … }` 은 짝이 맞는 중괄호까지, `const name = (…) => …` 는
    다음 맨 앞 줄(들여쓰지 않은 줄) 앞까지 (여러 줄에 걸친 화살표 함수도 들여 쓴 줄은 같이 읽는다)."""
    m = re.search(rf"(?:^|\n)[ \t]*(?:export\s+)?(?:async\s+)?function\s+{re.escape(name)}\s*\(", text)
    if m:
        params = _balanced(text, m.end() - 1)
        brace = text.index("{", m.end() - 1 + len(params))
        return text[m.start():brace] + _balanced(text, brace)
    m = re.search(rf"(?:^|\n)[ \t]*(?:export\s+)?const\s+{re.escape(name)}\s*=\s*", text)
    if m:
        nxt = re.search(r"\n(?=\S)", text[m.end():])
        return text[m.start():m.end() + (nxt.start() if nxt else len(text))]
    raise AssertionError(f"{where or '화면 소스'} 에 함수 {name} 이 없어요")


def regex_const(text: str, name: str, where: str = "") -> tuple[str, str]:
    """`[export] const NAME = /패턴/깃발;` → (패턴, 깃발)."""
    m = re.search(rf"^\s*(?:export\s+)?const\s+{re.escape(name)}\s*=\s*/(.+)/([a-z]*)\s*;?\s*$", text, re.M)
    if not m:
        raise AssertionError(f"{where or '화면 소스'} 에 const {name} = /…/; 정규식이 없어요")
    return m.group(1), m.group(2)


def _unescape(raw: str, quote: str) -> str:
    if "\\" not in raw:
        return raw
    if quote == "'":
        raw = raw.replace('"', '\\"')
    return json.loads('"' + raw.replace("\\'", "'") + '"')


def strings(text: str) -> list[str]:
    """글자 속 "…"·'…' 문자열들 (차례대로). 템플릿(`…`)은 뺀다."""
    out = []
    for m in re.finditer(r"\"((?:[^\"\\\n]|\\.)*)\"|'((?:[^'\\\n]|\\.)*)'", text):
        out.append(_unescape(m.group(1), '"') if m.group(1) is not None else _unescape(m.group(2), "'"))
    return out


def object_pairs(text: str) -> dict[str, str]:
    """{ key: "값", "key 2": '값' } 모양의 글자 → dict (값이 문자열인 칸만)."""
    pat = r"(?:^|[{,])\s*(?:(\w+)|\"([^\"]+)\"|'([^']+)')\s*:\s*(?:\"((?:[^\"\\\n]|\\.)*)\"|'((?:[^'\\\n]|\\.)*)')"
    return {k1 or k2 or k3: _unescape(v1, '"') if v1 else _unescape(v2, "'")
            for k1, k2, k3, v1, v2 in re.findall(pat, text)}


def object_keys(text: str) -> list[str]:
    """{ … } 맨 바깥 칸의 키 이름들 (값 모양은 따지지 않음)."""
    inner, depth, quote, start = text.strip()[1:-1], 0, None, 0
    parts, keys = [], []
    for i, c in enumerate(inner):          # 맨 바깥 쉼표로 칸을 나눈다
        if quote:
            if c == quote and inner[i - 1] != "\\":
                quote = None
        elif c in "\"'`":
            quote = c
        elif c in "[{(":
            depth += 1
        elif c in "]})":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(inner[start:i])
            start = i + 1
    parts.append(inner[start:])
    for part in parts:
        m = re.match(r"\s*(?:(\w+)|\"([^\"]+)\"|'([^']+)')\s*:", part)
        if m:
            keys.append(m.group(1) or m.group(2) or m.group(3))
    return keys


# ── 화면 8개의 주소 ─────────────────────────────────────────────────────
def router_routes() -> list[str]:
    """lib/router.js 의 ROUTES 배열."""
    return strings(const_value(read("lib/router.js"), "ROUTES", "frontend/src/lib/router.js"))


def app_screens() -> list[str]:
    """App.jsx 의 SCREENS 키 (주소 → 화면 컴포넌트)."""
    return object_keys(const_value(read("App.jsx"), "SCREENS", "frontend/src/App.jsx"))


def sidebar_menu() -> dict[str, str]:
    """components/Sidebar.jsx 왼쪽 메뉴의 {주소: 메뉴 글자}. ["today", "홈"] 배열 칸이나 { route: "today", label: "홈" } 칸을 읽는다."""
    text = read("components/Sidebar.jsx")
    found = re.findall(r"\[\s*([\"'])(\w+)\1\s*,\s*([\"'])([^\"'\n]+)\3\s*[,\]]", text)
    menu = {route: label for _, route, _, label in found}
    for a, b in re.findall(r"\broute\s*:\s*[\"'](\w+)[\"']\s*,\s*label\s*:\s*[\"']([^\"'\n]+)[\"']", text):
        menu[a] = b
    if not menu:
        raise AssertionError("frontend/src/components/Sidebar.jsx 에서 메뉴 칸([\"주소\", \"글자\"])을 찾지 못했어요. "
                             "메뉴 정의 모양이 바뀌었다면 tests/frontend_src.py 의 sidebar_menu 를 고쳐 주세요")
    return menu


# ── node 로 화면 모듈 돌려 보기 (node 가 없으면 부르는 시험이 건너뛴다) ─────────────
def node_eval(imports: dict[str, list[str]], expr: str) -> Any:
    """frontend/src 의 ES 모듈을 node 로 불러 expr 의 값을 JSON 으로 돌려받는다. imports: {소스 경로: [이름, …]}.
    frontend/package.json 이 "type": "module" 이라 .js 를 그대로 import 한다 (React 를 부르는 모듈은 넣지 말 것)."""
    if not NODE:
        raise AssertionError("node 가 없어요 (이 함수를 부르는 시험은 skipUnless(NODE) 로 감쌀 것)")
    lines = [f"import {{ {', '.join(names)} }} from {json.dumps((SRC / name).as_uri())};" for name, names in imports.items()]
    script = "\n".join(lines) + f"\nconsole.log(JSON.stringify({expr}));"
    out = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패: {out.stderr.strip()[:2000]}")
    return json.loads(out.stdout)
