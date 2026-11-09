"""Optional Korean morphological analysis with Kiwi (kiwipiepy, Apache-2.0).

The classifier works without this module's analyser. When kiwipiepy is
installed, it adds two things the plain dictionary scan cannot do well:

* verb lemmas, so that "줄었나요" is the verb 줄다 while "줄 서는" is the noun 줄;
* token boundaries, so that a place name hidden inside a longer word is ignored.

Install with ``pip install -r requirements-assistant.txt``. Set
``ASSISTANT_MORPH=off`` to force the rule-only path.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os


@dataclass(frozen=True)
class Morpheme:
    form: str
    tag: str
    start: int  # character offset in the original text
    length: int


class KiwiAnalyzer:
    name = "kiwi"

    def __init__(self, user_words=()):
        from kiwipiepy import Kiwi  # imported lazily: optional dependency

        self._kiwi = Kiwi()
        for word in user_words:
            # Proper nouns stay as one token, e.g. 홍대입구역, 성수1가1동.
            self._kiwi.add_user_word(word, "NNP", 0.0)
        import kiwipiepy

        self.version = kiwipiepy.__version__

    def analyze(self, text: str) -> list[Morpheme]:
        return [Morpheme(t.form, t.tag, t.start, t.len) for t in self._kiwi.tokenize(text)]


def morph_enabled() -> bool:
    return os.getenv("ASSISTANT_MORPH", "").strip().lower() not in ("off", "0", "false")


def get_analyzer():
    """Return a shared analyser, or None when Kiwi is unavailable or disabled.

    The on/off switch is read on every call; only the loaded analyser is cached,
    so turning ASSISTANT_MORPH off and on again never leaves a stale None.
    """
    if not morph_enabled():
        return None
    return _load_kiwi()


@lru_cache(maxsize=1)
def _load_kiwi():
    try:
        from app.assistant.lexicon import user_words

        return KiwiAnalyzer(user_words())
    except ImportError:
        return None
