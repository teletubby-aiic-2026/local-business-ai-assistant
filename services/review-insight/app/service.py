"""리뷰 보관 · S2 직접 붙여넣기 · 분석 결과 묶기. 가게마다 따로 보관하고 따로 분석합니다."""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import storage
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

# 방문자 id: 공개 주소를 여러 사람이 열 때 붙여넣은 리뷰를 사람별로 나누는 값 (비서 화면 서버가 쿠키로 만들어 넘김).
# shared/storage/visitor.py 와 같은 규칙의 사본이다. 저장소 루트(shared/)가 없는 환경(Dockerfile 이미지)에서도
# 파일 이름에 들어갈 값을 검사해야 해서 따로 둔다. 규칙을 바꾸면 둘을 같이 고친다 (시험이 같은 답인지 확인함).
COMMON_VISITOR = "common"       # 방문자를 안 가린 호출. 지금까지와 같은 한 곳 (pasted_<가게>.json)
_VISITOR_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def clean_visitor(visitor_id: str | None) -> str:
    """None·빈 값 → 공용. 영문·숫자·-·_ 1~64자가 아니면 ValueError (파일 이름에 들어가므로 경로 문자를 막는다)."""
    if visitor_id is None or visitor_id == "":
        return COMMON_VISITOR
    if not isinstance(visitor_id, str) or _VISITOR_ID.fullmatch(visitor_id) is None:
        raise ValueError("방문자 id 는 영문·숫자·-·_ 1~64자여야 합니다")
    return visitor_id


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


def _pasted_file(store_id: str, visitor_id: str | None = None) -> Path:
    """공용은 지금까지의 pasted_<가게>.json, 방문자는 visitors/<방문자>/pasted_<가게>.json."""
    _dir(store_id)
    visitor = clean_visitor(visitor_id)
    if visitor == COMMON_VISITOR:
        return RUNTIME / f"pasted_{store_id}.json"
    path = RUNTIME / "visitors" / visitor / f"pasted_{store_id}.json"
    if not path.resolve().is_relative_to(RUNTIME.resolve()):     # 형식 검사를 통과한 값이라 일어나지 않지만 한 번 더 막는다
        raise ValueError("방문자 id 가 저장 폴더 밖을 가리킵니다")
    return path


def pasted_reviews(store_id: str = DEFAULT_STORE, visitor_id: str | None = None) -> list[Review]:
    db = storage.database()
    if db is not None:
        _dir(store_id)
        visitor = clean_visitor(visitor_id)
        with storage.guarded():
            return [Review.from_dict(d) for d in db.reviews.list(store_id, visitor)]
    try:
        return [Review.from_dict(d) for d in json.loads(_pasted_file(store_id, visitor_id).read_text(encoding="utf-8"))]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def all_reviews(store_id: str = DEFAULT_STORE, visitor_id: str | None = None) -> list[Review]:
    """합성 리뷰(모두에게 같음) + 이 방문자가 붙여넣은 리뷰. 방문자를 안 주면 공용."""
    return sample_reviews(store_id) + pasted_reviews(store_id, visitor_id)


def _save_pasted(store_id: str, rows: list[Review], visitor_id: str | None = None) -> None:
    path = _pasted_file(store_id, visitor_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([r.to_dict() for r in rows], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def scenario_now(store_id: str, n: int = 1) -> datetime:
    """붙여넣은 리뷰의 작성 시각.

    합성 가게는 '마지막 합성 리뷰가 있는 날 밤 11시'(발표 장면)부터 1분씩 늦춘 시각을 씁니다.
    실제 오늘 날짜를 쓰면 분석 기간(최근 28일)이 오늘 기준으로 밀려서 오래된 합성 리뷰가 빠지고,
    40건 → 불만 12건 같은 숫자가 바뀌기 때문입니다 (11/10 확인). REVIEW_PASTE_REAL_TIME=1 이면 실제 시각.
    """
    if os.getenv("REVIEW_PASTE_REAL_TIME", "").strip() in ("1", "true", "yes"):
        return datetime.now(KST)
    try:
        last = max(datetime.fromisoformat(r.created_at) for r in sample_reviews(store_id))
    except (ValueError, FileNotFoundError):
        return datetime.now(KST)
    base = last.astimezone(KST).replace(hour=23, minute=0, second=0, microsecond=0)
    return base + timedelta(minutes=n - 1)


def add_pasted(text: str, rating: int | None = None, channel: str | None = None, now: datetime | None = None,
               store_id: str = DEFAULT_STORE, visitor_id: str | None = None) -> Review:
    """S2: 사장님이 붙여넣은 리뷰 한 건. 저장·모델 전송 전에 전화번호·이메일·링크를 가립니다."""
    text = (text or "").strip()
    if not 1 <= len(text) <= MAX_TEXT:
        raise ValueError(f"리뷰 글은 1~{MAX_TEXT}자여야 합니다")
    if rating is not None and not (isinstance(rating, int) and 1 <= rating <= 5):
        raise ValueError("별점은 1~5 사이 정수이거나 비워 두세요")
    if channel is not None and channel not in CHANNELS:
        raise ValueError(f"채널은 {', '.join(CHANNELS)} 중 하나이거나 비워 두세요")
    masked, changed = mask_pii(text)
    visitor = clean_visitor(visitor_id)
    short = store_id.removeprefix("store_")

    def build(n: int) -> Review:
        when = now or scenario_now(store_id, n)
        return Review(review_id=f"rv_{short}_paste_{n:03d}", store_id=store_id, channel=channel, rating=rating,
                      text=masked, created_at=when.isoformat(timespec="seconds"),
                      input_method="paste", pii_masked=changed,
                      data_origin="synthetic")   # 대회 동안 붙여넣기에도 합성 리뷰만 씀 (모듈 규격 9.2)

    db = storage.database()
    if db is not None:
        _dir(store_id)
        with storage.guarded():      # 번호(n)는 DB 가 (가게, 방문자)마다 겹치지 않게 정해 준다
            return Review.from_dict(db.reviews.add(store_id, visitor, lambda n: build(n).to_dict()))
    with _lock:
        rows = pasted_reviews(store_id, visitor)
        n = max([int(r.review_id.split("_")[-1]) for r in rows] or [0]) + 1
        review = build(n)
        rows.append(review)
        _save_pasted(store_id, rows, visitor)
    return review


def clear_pasted(store_id: str = DEFAULT_STORE, visitor_id: str | None = None) -> int:
    db = storage.database()
    if db is not None:
        _dir(store_id)
        visitor = clean_visitor(visitor_id)
        with storage.guarded():
            return db.reviews.clear(store_id, visitor)
    with _lock:
        n = len(pasted_reviews(store_id, visitor_id))
        _save_pasted(store_id, [], visitor_id)
    return n


def analyze(classifier: Classifier, store_id: str = DEFAULT_STORE, visitor_id: str | None = None, *,
            end: datetime | None = None) -> ReviewInsight:
    reviews = all_reviews(store_id, visitor_id)
    return build_insight(store_id, reviews, classifier.classify(reviews), end=end)
