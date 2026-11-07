"""Small Korean text helpers: particles that depend on the final consonant."""
from __future__ import annotations

import re

_PAIRS = {"은": ("은", "는"), "는": ("은", "는"), "이": ("이", "가"), "가": ("이", "가"),
          "을": ("을", "를"), "를": ("을", "를"), "과": ("과", "와"), "와": ("과", "와"),
          "으로": ("으로", "로"), "로": ("으로", "로"), "이라": ("이라", "라")}


def _has_final(word: str) -> bool | None:
    for char in reversed(word or ""):
        if "가" <= char <= "힣":
            return (ord(char) - 0xAC00) % 28 != 0
        if char.isdigit():
            return char in "013678"  # 영, 일, 삼, 육, 칠, 팔 end with a consonant
        if char.isalpha():
            return None
        # Skip closing brackets and spaces, e.g. "역삼1동(강남구)".
    return None


def _final_is_rieul(word: str) -> bool:
    for char in reversed(word or ""):
        if "가" <= char <= "힣":
            return (ord(char) - 0xAC00) % 28 == 8
        if char.isdigit():
            return char in "178"
    return False


def soften(sentence: str) -> str:
    """Report endings to conversational ones: '…원입니다.' -> '…원이에요.', '없습니다.' -> '없어요.'."""
    def copula(match):
        # Look back past brackets and signs: '(12.14%)입니다' reads '…사', so '예요'.
        before = match.string[:match.end(1)]
        return match.group(1) + ("예요." if _has_final(before) is False else "이에요.")

    sentence = re.sub(r"(\S)입니다\.", copula, sentence)
    return re.sub(r"습니다\.", "어요.", sentence)


def josa(word: str, particle: str) -> str:
    """Return word + the right form of particle, e.g. josa("점포", "은") -> "점포는"."""
    with_final, without_final = _PAIRS[particle]
    final = _has_final(word)
    if final is None:
        return f"{word}{with_final}({without_final})" if with_final != without_final else word + with_final
    if with_final == "으로" and _final_is_rieul(word):
        return word + "로"
    return word + (with_final if final else without_final)
