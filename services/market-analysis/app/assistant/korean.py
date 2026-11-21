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


# '…ㅂ니다' after a vowel stem, the ones model answers use ('강남역 매출이 큽니다.', 2026-11-08 server test).
_B_NIDA = (("큽니다", "커요"), ("합니다", "해요"), ("됩니다", "돼요"), ("납니다", "나요"), ("갑니다", "가요"),
           ("옵니다", "와요"), ("봅니다", "봐요"), ("줍니다", "줘요"), ("씁니다", "써요"), ("바랍니다", "바라요"),
           ("높입니다", "높여요"), ("보입니다", "보여요"))


def soften(sentence: str) -> str:
    """Report endings to conversational ones: '…원입니다.' -> '…원이에요.', '없습니다.' -> '없어요.'."""
    def copula(match):
        # Look back past brackets and signs: '(12.14%)입니다' reads '…사', so '예요'.
        before = match.string[:match.end(1)]
        return match.group(1) + ("예요" if _has_final(before) is False else "이에요")

    def polite(match):
        # 많습니다 -> 많아요, 없습니다 -> 없어요, 늘었습니다 -> 늘었어요 (past 었/았 always takes 어요).
        stem = match.group(1)
        code = ord(stem) - 0xAC00
        bright = 0 <= code < 11172 and code % 28 != 20 and (code // 28) % 21 in (0, 2, 8)  # ㅏ ㅑ ㅗ; 20 = ㅆ final
        return stem + ("아요" if bright else "어요")

    def yeyo(match):
        # '50대에요' -> '50대예요' after a syllable without a final consonant; '아니에요', '원이에요' are already right.
        char = match.group(1)
        return char + ("예요" if char not in "니이" and _has_final(char) is False else "에요")

    # The ending may be followed by a card number ('78개가 있습니다 [F5]', 2026-11-08 export) or end the line.
    end = r"(?=[.(!?\[]|\s*\[F|\s*$)"
    for formal, polite_form in _B_NIDA:
        sentence = re.sub(formal + end, polite_form, sentence)
    sentence = sentence.replace("낫아요", "나아요")  # 낫다 is irregular: HCX-005 wrote '더 낫아요'
    sentence = re.sub(r"(\S)입니다" + end, copula, sentence)
    sentence = re.sub(r"([가-힣])에요", yeyo, sentence)
    return re.sub(r"([가-힣])습니다" + end, polite, sentence)


_AMOUNT = re.compile(r"(?<![\d,.])(\d{1,3}(?:,\d{3})+|\d{5,})(원|명)(?!\s*\()")


def amount_words(value: int, unit: str) -> str:
    """976474889, '원' -> '약 9억 7,647만 원'; exact multiples drop '약' (100000000 -> '1억 원').

    Rounded half up at the last unit shown, like the market screen (frontend features/market/format.js wonShort:
    1,455,756,067원 -> '14억 5,576만 원'). Rounding down made the drawer say 14억 5,575만 next to the screen's
    14억 5,576만 (live 2026-11-21).
    """
    if value >= 10 ** 12:
        step = 10 ** 8
    else:
        step = 10 ** 4
    rounded = (value + step // 2) // step * step
    exact = rounded == value
    jo, rest = divmod(rounded, 10 ** 12)
    eok, rest = divmod(rest, 10 ** 8)
    man = rest // 10 ** 4
    if jo:
        parts = [f"{jo:,}조"] + ([f"{eok:,}억"] if eok else [])
    elif eok:
        parts = [f"{eok:,}억"] + ([f"{man:,}만"] if man else [])
    else:
        parts = [f"{man:,}만"]
    return ("" if exact else "약 ") + " ".join(parts) + " " + unit


def with_units(text: str) -> str:
    """'976,474,889원' -> '976,474,889원(약 9억 7,647만 원)' from 1,000,000원 and 100,000명 (user request 2026-11-08).

    Applied to the final reply only, after answer_check: the exact card number stays first and the reading is
    derived from it. Numbers inside brackets are left alone so no brackets are nested.
    """
    def add(match):
        before = match.string[:match.start()]
        if before.count("(") > before.count(")"):
            return match.group(0)
        value = int(match.group(1).replace(",", ""))
        if value < (1_000_000 if match.group(2) == "원" else 100_000):
            return match.group(0)  # '12,000원(약 1만 원)' would only add noise
        return f"{match.group(0)}({amount_words(value, match.group(2))})"

    return "\n".join(_AMOUNT.sub(add, line) for line in (text or "").split("\n"))


def josa(word: str, particle: str) -> str:
    """Return word + the right form of particle, e.g. josa("점포", "은") -> "점포는"."""
    with_final, without_final = _PAIRS[particle]
    final = _has_final(word)
    if final is None:
        return f"{word}{with_final}({without_final})" if with_final != without_final else word + with_final
    if with_final == "으로" and _final_is_rieul(word):
        return word + "로"
    return word + (with_final if final else without_final)
