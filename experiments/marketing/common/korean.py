"""한글 조사·받침 관련 함수."""

import re


def has_batchim(ch):
    code = ord(ch) - 0xAC00
    return 0 <= code <= 11171 and code % 28 != 0


def josa(word, a, b):
    """받침 있으면 a, 없으면 b. '로/으로'는 ㄹ받침이면 '로'."""
    last = re.sub(r"\([^)]*\)\s*$", "", word).rstrip()[-1:]
    if not last:
        return b
    if a == "으로":
        code = ord(last) - 0xAC00
        if 0 <= code <= 11171 and code % 28 == 8:  # ㄹ받침
            return "로"
    return a if has_batchim(last) else b


def eul(word):
    ch = word.strip()[-1]
    code = ord(ch) - 0xAC00
    return "을" if 0 <= code <= 11171 and code % 28 else "를"


def i_ga(word):
    hangul = [ch for ch in word if 0xAC00 <= ord(ch) <= 0xD7A3]
    if not hangul:
        return "이"
    return "이" if (ord(hangul[-1]) - 0xAC00) % 28 else "가"


def and_join(items):
    """목록을 자연스러운 조사로 연결한다. 받침 없으면 '와', 있으면 '과'.
    예: ["수저", "젓가락"] -> "수저와 젓가락", ["소스", "반찬", "음료"] -> "소스, 반찬과 음료"."""
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    *head, last = items
    connector = "과" if has_batchim(head[-1][-1]) else "와"
    if len(head) > 1:
        return f"{', '.join(head[:-1])}, {head[-1]}{connector} {last}"
    return f"{head[0]}{connector} {last}"


def join_item_groups(groups):
    """묶음(묶음 하나 = 리뷰 한 건에서 뽑은 품목들) 여러 개를 자연스럽게 연결한다.
    묶음 안은 and_join(와/과), 묶음과 묶음 사이는 쉼표로 잇는다.
    예: [["공깃밥"], ["수저", "젓가락"], ["계란말이"]] -> "공깃밥, 수저와 젓가락, 계란말이".
    리뷰가 하나뿐이면(묶음 1개) and_join 과 같다: [["수저", "젓가락"]] -> "수저와 젓가락".
    답글·공지 템플릿, AI 프롬프트에 넘기는 품목 문자열 모두 이 함수로 만든다."""
    parts = [and_join(g) for g in groups if g]
    return ", ".join(parts)


def nospace(s):
    return re.sub(r"\s+", "", s or "")


def display_name(name: str) -> str:
    """상호명 끝에 붙은 "(가상)" 같은 괄호 표기를 지운, 글에 쓰는 이름."""
    stripped = re.sub(r"\s*\([^)]*\)\s*$", "", name or "").strip()
    return stripped or (name or "")
