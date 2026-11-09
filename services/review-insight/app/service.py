"""리뷰 보관 · S2 직접 붙여넣기 · 분석 결과 묶기. 가게마다 따로 보관하고 따로 분석합니다."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.classify import Classifier
from app.cluster import build_insight
from app.models import CHANNELS, Review, ReviewInsight
from app.topics import mask_pii

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ROOT / "data" / "synthetic"
RUNTIME = ROOT / "data" / "runtime"                         # 붙여넣은 리뷰 (저장소에 올리지 않음)
DEFAULT_STORE = "store_ongi"                                 # 발표 시나리오 가게
KST = timezone(timedelta(hours=9))
MAX_TEXT = 1000
_lock = threading.Lock()


class StoreNotFound(KeyError):
    pass


def store_ids() -> list[str]:
    ids = sorted(p.name for p in SYNTHETIC.iterdir() if (p / "store.json").exists())
    return sorted(ids, key=lambda s: s != DEFAULT_STORE)      # 시나리오 가게를 맨 앞에


def _dir(store_id: str) -> Path:
    if store_id not in store_ids():
        raise StoreNotFound(store_id)
    return SYNTHETIC / store_id


def stores() -> list[dict]:
    return [store(s) for s in store_ids()]


def store(store_id: str = DEFAULT_STORE) -> dict:
    return json.loads((_dir(store_id) / "store.json").read_text(encoding="utf-8"))


def sample_reviews(store_id: str = DEFAULT_STORE) -> list[Review]:
    return [Review.from_dict(d) for d in json.loads((_dir(store_id) / "reviews.json").read_text(encoding="utf-8"))]


def labels(store_id: str = DEFAULT_STORE) -> dict:
    return {l["review_id"]: l for l in json.loads((_dir(store_id) / "labels.json").read_text(encoding="utf-8"))}


def _pasted_file(store_id: str) -> Path:
    _dir(store_id)
    return RUNTIME / f"pasted_{store_id}.json"


def pasted_reviews(store_id: str = DEFAULT_STORE) -> list[Review]:
    try:
        return [Review.from_dict(d) for d in json.loads(_pasted_file(store_id).read_text(encoding="utf-8"))]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def all_reviews(store_id: str = DEFAULT_STORE) -> list[Review]:
    return sample_reviews(store_id) + pasted_reviews(store_id)


def _save_pasted(store_id: str, rows: list[Review]) -> None:
    path = _pasted_file(store_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([r.to_dict() for r in rows], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def add_pasted(text: str, rating: int | None = None, channel: str | None = None, now: datetime | None = None,
               store_id: str = DEFAULT_STORE) -> Review:
    """S2: 사장님이 붙여넣은 리뷰 한 건. 저장·모델 전송 전에 전화번호·이메일·링크를 가립니다."""
    text = (text or "").strip()
    if not 1 <= len(text) <= MAX_TEXT:
        raise ValueError(f"리뷰 글은 1~{MAX_TEXT}자여야 합니다")
    if rating is not None and not (isinstance(rating, int) and 1 <= rating <= 5):
        raise ValueError("별점은 1~5 사이 정수이거나 비워 두세요")
    if channel is not None and channel not in CHANNELS:
        raise ValueError(f"채널은 {', '.join(CHANNELS)} 중 하나이거나 비워 두세요")
    masked, changed = mask_pii(text)
    with _lock:
        rows = pasted_reviews(store_id)
        n = max([int(r.review_id.split("_")[-1]) for r in rows] or [0]) + 1
        short = store_id.removeprefix("store_")
        review = Review(review_id=f"rv_{short}_paste_{n:03d}", store_id=store_id, channel=channel, rating=rating,
                        text=masked, created_at=(now or datetime.now(KST)).isoformat(timespec="seconds"),
                        input_method="paste", pii_masked=changed,
                        data_origin="synthetic")   # 대회 동안 붙여넣기에도 합성 리뷰만 씀 (모듈 규격 9.2)
        rows.append(review)
        _save_pasted(store_id, rows)
    return review


def clear_pasted(store_id: str = DEFAULT_STORE) -> int:
    with _lock:
        n = len(pasted_reviews(store_id))
        _save_pasted(store_id, [])
    return n


def analyze(classifier: Classifier, store_id: str = DEFAULT_STORE, *, end: datetime | None = None) -> ReviewInsight:
    reviews = all_reviews(store_id)
    return build_insight(store_id, reviews, classifier.classify(reviews), end=end)
