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


def nospace(s):
    return re.sub(r"\s+", "", s or "")
