"""Find example sentences similar to a question, for the planner prompt.

Similarity uses the morphological analyser as a reference, not as the judge:
a sentence becomes Kiwi content lemmas (창업/NNG, 하/VV, 좋/VA …) plus
character bigrams of its compact form (robust to typos such as '어떤로'),
weighted by TF-IDF over the example bank, compared by cosine. The planner
model then reads the chosen examples next to the question and decides.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
import json
import math
from pathlib import Path

from app.assistant.lexicon import compact
from app.assistant.morph import get_analyzer

BANK = Path(__file__).resolve().parent / "aliases" / "intent_examples.json"
_LEMMA_TAGS = ("NNG", "NNP", "NP", "VV", "VA", "XR", "MM", "MAG")


def _features(text: str, analyzer) -> Counter:
    flat = compact(text)
    features = Counter(flat[i:i + 2] for i in range(len(flat) - 1))
    if analyzer is not None:
        for morpheme in analyzer.analyze(text):
            if morpheme.tag.startswith(_LEMMA_TAGS):
                features["L:" + morpheme.form] += 2  # a shared lemma counts more than a shared bigram
    return features


@lru_cache(maxsize=2)
def _index(use_morph: bool):
    analyzer = get_analyzer() if use_morph else None
    examples = json.loads(BANK.read_text(encoding="utf-8"))["examples"]
    vectors = [_features(example["text"], analyzer) for example in examples]
    documents = Counter(feature for vector in vectors for feature in vector)
    idf = {feature: math.log((1 + len(vectors)) / (1 + count)) + 1 for feature, count in documents.items()}
    weighted = [_weigh(vector, idf) for vector in vectors]
    return analyzer, examples, idf, weighted


def _weigh(vector: Counter, idf: dict) -> dict:
    weights = {feature: count * idf.get(feature, math.log(2) + 1) for feature, count in vector.items()}
    norm = math.sqrt(sum(value * value for value in weights.values())) or 1.0
    return {feature: value / norm for feature, value in weights.items()}


def similar(text: str, *, limit: int = 6, per_action: int = 2, use_morph: bool = True) -> list[dict]:
    """Up to ``limit`` examples, at most ``per_action`` of each action so the model sees alternatives."""
    analyzer, examples, idf, weighted = _index(use_morph)
    query = _weigh(_features(text, analyzer), idf)
    scored = sorted(((sum(value * vector.get(feature, 0.0) for feature, value in query.items()), index)
                     for index, vector in enumerate(weighted)), reverse=True)
    chosen, per = [], Counter()
    for score, index in scored:
        example = examples[index]
        if score <= 0 or per[example["action"]] >= per_action:
            continue
        per[example["action"]] += 1
        chosen.append({**example, "score": round(score, 3)})
        if len(chosen) >= limit:
            break
    return chosen
