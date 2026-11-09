"""리뷰와 비슷한 예문 찾기 (모델 프롬프트용). 상권 비서(PR #13)의 app/assistant/examples.py 와 같은 방식입니다.

예문 하나를 kiwi 기본형(L:식, L:포장 …)과 띄어쓰기를 지운 글자 두 개씩(오타·말끝 변화에 강함)으로 바꾸고,
예문 모음 전체로 TF-IDF 가중치를 매겨 코사인 유사도로 비교합니다. 모델은 고른 예문을 리뷰 옆에 놓고 직접 판단합니다.

예문 모음(data/examples/review_examples.json)에는 평가용 합성 리뷰(data/synthetic)의 문장을 넣지 않습니다.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from app.morph import get_analyzer

BANK = Path(__file__).resolve().parents[1] / "data" / "examples" / "review_examples.json"
_LEMMA_TAGS = ("NNG", "NNP", "NP", "VV", "VA", "XR", "MM", "MAG")


def _compact(text: str) -> str:
    return re.sub(r"[^0-9가-힣a-z]", "", (text or "").lower())


def _features(text: str, analyzer) -> Counter:
    flat = _compact(text)
    features = Counter(flat[i:i + 2] for i in range(len(flat) - 1))
    if analyzer is not None:
        for m in analyzer.analyze(text):
            if m.tag.startswith(_LEMMA_TAGS):
                features["L:" + m.form] += 2   # 같은 기본형은 같은 글자 두 개보다 무겁게
    return features


def _weigh(vector: Counter, idf: dict) -> dict:
    weights = {f: n * idf.get(f, math.log(2) + 1) for f, n in vector.items()}
    norm = math.sqrt(sum(v * v for v in weights.values())) or 1.0
    return {f: v / norm for f, v in weights.items()}


@lru_cache(maxsize=2)
def _index(use_morph: bool):
    analyzer = get_analyzer() if use_morph else None
    examples = json.loads(BANK.read_text(encoding="utf-8"))["examples"]
    vectors = [_features(e["text"], analyzer) for e in examples]
    docs = Counter(f for v in vectors for f in v)
    idf = {f: math.log((1 + len(vectors)) / (1 + n)) + 1 for f, n in docs.items()}
    return analyzer, examples, idf, [_weigh(v, idf) for v in vectors]


def similar(text: str, *, limit: int = 2, use_morph: bool = True) -> list[dict]:
    """가장 비슷한 예문 ``limit``개 (점수 0 이하는 빼고)."""
    analyzer, examples, idf, weighted = _index(use_morph and get_analyzer() is not None)
    query = _weigh(_features(text, analyzer), idf)
    scored = sorted(((sum(v * vec.get(f, 0.0) for f, v in query.items()), i) for i, vec in enumerate(weighted)), reverse=True)
    return [{**examples[i], "score": round(s, 3)} for s, i in scored[:limit] if s > 0]
