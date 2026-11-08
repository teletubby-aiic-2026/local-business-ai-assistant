"""리뷰 보관 · S2 직접 붙여넣기 · 분석 결과 묶기."""
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
PASTED = ROOT / "data" / "runtime" / "pasted_reviews.json"   # 저장소에 올리지 않음
KST = timezone(timedelta(hours=9))
MAX_TEXT = 1000
_lock = threading.Lock()


def store() -> dict:
    return json.loads((SYNTHETIC / "store.json").read_text(encoding="utf-8"))


def sample_reviews() -> list[Review]:
    return [Review.from_dict(d) for d in json.loads((SYNTHETIC / "reviews.json").read_text(encoding="utf-8"))]


def pasted_reviews() -> list[Review]:
    try:
        return [Review.from_dict(d) for d in json.loads(PASTED.read_text(encoding="utf-8"))]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def all_reviews() -> list[Review]:
    return sample_reviews() + pasted_reviews()


def _save_pasted(rows: list[Review]) -> None:
    PASTED.parent.mkdir(parents=True, exist_ok=True)
    PASTED.write_text(json.dumps([r.to_dict() for r in rows], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def add_pasted(text: str, rating: int | None = None, channel: str | None = None, now: datetime | None = None) -> Review:
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
        rows = pasted_reviews()
        n = max([int(r.review_id.split("_")[-1]) for r in rows] or [0]) + 1
        review = Review(review_id=f"rv_paste_{n:04d}", store_id=store()["store_id"], channel=channel, rating=rating,
                        text=masked, created_at=(now or datetime.now(KST)).isoformat(timespec="seconds"),
                        input_method="paste", pii_masked=changed,
                        data_origin="synthetic")   # 대회 동안 붙여넣기에도 합성 리뷰만 씀 (모듈 규격 9.2)
        rows.append(review)
        _save_pasted(rows)
    return review


def clear_pasted() -> int:
    with _lock:
        n = len(pasted_reviews())
        _save_pasted([])
    return n


def analyze(classifier: Classifier, *, end: datetime | None = None) -> ReviewInsight:
    reviews = all_reviews()
    return build_insight(store()["store_id"], reviews, classifier.classify(reviews), end=end)
