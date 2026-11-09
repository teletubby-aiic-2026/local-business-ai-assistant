"""Finding similar example sentences. No model, no network."""
from collections import Counter
import json
import unittest

from app.assistant.examples import BANK, similar

try:
    import kiwipiepy  # noqa: F401
    HAS_KIWI = True
except ImportError:
    HAS_KIWI = False


class SimilarExamplesTests(unittest.TestCase):
    def test_a_sentence_from_the_bank_finds_itself_first(self):
        example = json.loads(BANK.read_text(encoding="utf-8"))["examples"][0]
        found = similar(example["text"], use_morph=False)
        self.assertEqual(found[0]["text"], example["text"])

    def test_the_limits_keep_several_kinds_of_action(self):
        found = similar("강남역 카페 매출 어때?", limit=6, per_action=2, use_morph=False)
        self.assertLessEqual(len(found), 6)
        self.assertLessEqual(max(Counter(item["action"] for item in found).values()), 2)
        self.assertTrue(all(item["score"] > 0 for item in found))

    def test_a_sentence_sharing_nothing_finds_nothing(self):
        self.assertEqual(similar("qqqq", use_morph=False), [])

    @unittest.skipUnless(HAS_KIWI, "kiwipiepy is optional")
    def test_morphemes_also_work_when_kiwi_is_installed(self):
        self.assertTrue(similar("강남역 카페 매출 어때?", use_morph=True))


if __name__ == "__main__":
    unittest.main()
