"""리뷰 보관 · S2 직접 붙여넣기 · 분석 결과 묶기. 가게마다 따로 보관하고 따로 분석합니다."""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import records, storage
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
MAX_MENU = 40
# 리뷰가 어디서 들어왔나. 계약(shared/contracts.py)의 input_method 는 sample·paste 뿐이라 저장은 모두 "paste" 로 하고,
# 이 값은 records 의 source 칸에 따로 둔다 (계약이 바뀌면 input_method 로 옮길 수 있음, docs/handoff.md)
SOURCES = ("paste", "capture", "app", "memo")
REVIEW_STATUSES = ("new", "analyzed", "drafted", "replied", "skipped")   # shared/contracts.py 와 같은 값의 사본
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


STORE_ID = re.compile(r"store_[a-z0-9_]{1,40}")
MAX_STORES = 200                 # 계정으로 만든 가게 수 상한 (시연 서버 보호)


def synthetic_store_ids() -> list[str]:
    ids = sorted(p.name for p in SYNTHETIC.iterdir() if (p / "store.json").exists())
    return sorted(ids, key=lambda s: s != DEFAULT_STORE)      # 시나리오 가게를 맨 앞에


def _made_dir() -> Path:
    """계정으로 새로 만든 가게 (저장소에 올리지 않는 data/runtime/stores/<가게>/store.json). 합성 리뷰 없이 0건에서 시작."""
    return RUNTIME / "stores"


def made_store_ids() -> list[str]:
    try:
        return sorted(p.name for p in _made_dir().iterdir() if (p / "store.json").exists())
    except FileNotFoundError:
        return []


def store_ids() -> list[str]:
    return synthetic_store_ids() + made_store_ids()


def _dir(store_id: str) -> Path:
    if isinstance(store_id, str) and STORE_ID.fullmatch(store_id):      # 형식부터 확인 (경로에 들어감)
        if (SYNTHETIC / store_id / "store.json").exists():
            return SYNTHETIC / store_id
        if (_made_dir() / store_id / "store.json").exists():
            return _made_dir() / store_id
    raise StoreNotFound(store_id)


def create_store(store_id: str, name: str, business_type_name: str | None = None) -> dict:
    """새 가게 만들기 (계정 가입 때). 합성 리뷰·정답 라벨 없이 시작한다. 이미 있으면 ValueError."""
    if not (isinstance(store_id, str) and STORE_ID.fullmatch(store_id)):
        raise ValueError("가게 ID 는 store_ 뒤에 영문 소문자·숫자·_ 1~40자여야 합니다")
    name = " ".join((name or "").split())
    kind = " ".join((business_type_name or "").split()) or None
    if not 1 <= len(name) <= 40:
        raise ValueError("가게 이름은 1~40자여야 합니다")
    if kind is not None and len(kind) > 20:
        raise ValueError("업종은 20자 이하여야 합니다")
    with _lock:
        if store_id in store_ids():
            raise ValueError("이미 있는 가게입니다")
        if len(made_store_ids()) >= MAX_STORES:
            raise ValueError("가게를 더 만들 수 없습니다 (상한)")
        folder = _made_dir() / store_id
        folder.mkdir(parents=True, exist_ok=True)
        data = {"store_id": store_id, "name": name, "business_type": "etc", "business_type_name": kind,
                "channels": list(CHANNELS), "menu": [], "data_origin": "synthetic",      # 대회 동안은 합성·직접 쓴 리뷰만 (규격 9.2)
                "created_at": datetime.now(KST).isoformat(timespec="seconds")}
        (folder / "store.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return data


def stores() -> list[dict]:
    return [store(s) for s in store_ids()]


def store(store_id: str = DEFAULT_STORE) -> dict:
    return json.loads((_dir(store_id) / "store.json").read_text(encoding="utf-8"))


def sample_reviews(store_id: str = DEFAULT_STORE) -> list[Review]:
    """합성 가게의 원래 있던 리뷰. 계정으로 만든 가게는 파일이 없어 0건."""
    try:
        return [Review.from_dict(d) for d in json.loads((_dir(store_id) / "reviews.json").read_text(encoding="utf-8"))]
    except FileNotFoundError:
        return []


def labels(store_id: str = DEFAULT_STORE) -> dict:
    try:
        return {l["review_id"]: l for l in json.loads((_dir(store_id) / "labels.json").read_text(encoding="utf-8"))}
    except FileNotFoundError:
        return {}


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
    """합성 리뷰(모두에게 같음) + 가상 배달앱 리뷰(가게 공용, 모두에게 같음) + 이 방문자가 붙여넣은 리뷰.
    방문자를 안 주면 공용 칸 전체 (공용 칸에는 앱 리뷰가 이미 들어 있다)."""
    shared = [] if clean_visitor(visitor_id) == COMMON_VISITOR else app_reviews(store_id)
    return sample_reviews(store_id) + shared + pasted_reviews(store_id, visitor_id)


def is_app_review(review_id: str) -> bool:
    """가상 배달앱에서 온 리뷰인가 (id 가 rv_<가게>_app_NNN). 이 리뷰와 그 기록은 늘 가게 공용 칸에 있다."""
    return "_app_" in review_id


def app_reviews(store_id: str = DEFAULT_STORE) -> list[Review]:
    return [r for r in pasted_reviews(store_id, COMMON_VISITOR) if is_app_review(r.review_id)]


def record_owner(review_id: str, visitor_id: str | None) -> str | None:
    """이 리뷰의 기록(상태·답글)을 둘 칸. 앱 리뷰는 공용 → 어느 사장님 화면에서 답해도 배달앱에 보인다."""
    return COMMON_VISITOR if is_app_review(review_id) else visitor_id


def meta_for(store_id: str = DEFAULT_STORE, visitor_id: str | None = None) -> dict[str, dict]:
    """이 방문자가 보는 리뷰들의 기록: 자기 칸 기록 + 공용 칸의 앱 리뷰 기록."""
    own = records.load(store_id, visitor_id)
    if clean_visitor(visitor_id) == COMMON_VISITOR:
        return own
    return own | {k: v for k, v in records.load(store_id, COMMON_VISITOR).items() if is_app_review(k)}


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
        return datetime.now(KST)       # 합성 리뷰가 없는 가게(계정으로 만든 가게)는 실제 시각
    base = last.astimezone(KST).replace(hour=23, minute=0, second=0, microsecond=0)
    return base + timedelta(minutes=n - 1)


def add_pasted(text: str, rating: int | None = None, channel: str | None = None, now: datetime | None = None,
               store_id: str = DEFAULT_STORE, visitor_id: str | None = None) -> Review:
    """S2: 사장님이 붙여넣은 리뷰 한 건 (예전 이름. add_review(source="paste") 와 같음)."""
    return add_review(text, rating, channel, now, store_id=store_id, visitor_id=visitor_id)


def add_review(text: str, rating: int | None = None, channel: str | None = None, now: datetime | None = None,
               store_id: str = DEFAULT_STORE, visitor_id: str | None = None, *, source: str = "paste",
               received_at: datetime | None = None, menu: str | None = None) -> Review:
    """리뷰 한 건 저장 (붙여넣기·캡처 확인·가상 배달앱·매장 메모). 저장·모델 전송 전에 전화번호·이메일·링크를 가립니다.
    created_at 은 분석용 시나리오 시각(scenario_now), received_at 은 실제로 받은 시각 (기한·새 리뷰 조회용)."""
    if source not in SOURCES:
        raise ValueError(f"입력 방식은 {', '.join(SOURCES)} 중 하나여야 합니다")
    text = (text or "").strip()
    if not 1 <= len(text) <= MAX_TEXT:
        raise ValueError(f"리뷰 글은 1~{MAX_TEXT}자여야 합니다")
    if rating is not None and not (isinstance(rating, int) and 1 <= rating <= 5):
        raise ValueError("별점은 1~5 사이 정수이거나 비워 두세요")
    if channel is not None and channel not in CHANNELS:
        raise ValueError(f"채널은 {', '.join(CHANNELS)} 중 하나이거나 비워 두세요")
    menu = " ".join((menu or "").split()) or None
    if menu is not None and len(menu) > MAX_MENU:
        raise ValueError(f"주문 메뉴는 {MAX_MENU}자 이하여야 합니다")
    masked, changed = mask_pii(text)
    # 가상 배달앱 리뷰는 가게 데이터라 누가 보내든 가게 공용 칸에 쌓는다 (모든 사장님 화면·배달앱에 같이 보임)
    visitor = COMMON_VISITOR if source == "app" else clean_visitor(visitor_id)
    kind = "app" if source == "app" else "paste"
    short = store_id.removeprefix("store_")

    def build(n: int) -> Review:
        when = now or scenario_now(store_id, n)
        return Review(review_id=f"rv_{short}_{kind}_{n:03d}", store_id=store_id, channel=channel, rating=rating,
                      text=masked, created_at=when.isoformat(timespec="seconds"),
                      input_method="paste", pii_masked=changed,
                      data_origin="synthetic")   # 대회 동안 붙여넣기에도 합성 리뷰만 씀 (모듈 규격 9.2)

    db = storage.database()
    if db is not None:
        _dir(store_id)
        with storage.guarded():      # 번호(n)는 DB 가 (가게, 방문자)마다 겹치지 않게 정해 준다
            review = Review.from_dict(db.reviews.add(store_id, visitor, lambda n: build(n).to_dict()))
    else:
        with _lock:
            rows = pasted_reviews(store_id, visitor)
            n = max([int(r.review_id.split("_")[-1]) for r in rows] or [0]) + 1
            review = build(n)
            rows.append(review)
            _save_pasted(store_id, rows, visitor)
    received = (received_at or datetime.now(KST)).astimezone(KST).isoformat(timespec="seconds")
    records.update(store_id, visitor, review.review_id,
                   {"source": source, "received_at": received} | ({"menu": menu} if menu else {}))
    return review


def clear_pasted(store_id: str = DEFAULT_STORE, visitor_id: str | None = None) -> int:
    db = storage.database()
    if db is not None:
        _dir(store_id)
        visitor = clean_visitor(visitor_id)
        with storage.guarded():
            n = db.reviews.clear(store_id, visitor)
        records.clear(store_id, visitor)          # 상태·답글 기록도 같이 지움 (데모 다시 하기)
        return n
    with _lock:
        n = len(pasted_reviews(store_id, visitor_id))
        _save_pasted(store_id, [], visitor_id)
        records.clear(store_id, visitor_id)
    return n


def analyze(classifier: Classifier, store_id: str = DEFAULT_STORE, visitor_id: str | None = None, *,
            end: datetime | None = None) -> ReviewInsight:
    reviews = all_reviews(store_id, visitor_id)
    return build_insight(store_id, reviews, classifier.classify(reviews), end=end)


# ── 새 기록(어디서 들어왔나·받은 시각·상태·답글)을 붙인 리뷰 ──
def parse_time(value: str | datetime | None, field: str = "시각") -> datetime | None:
    """ISO 8601 → 한국 시간. 시간대가 없으면 한국 시간으로 본다. 잘못된 값은 ValueError."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        t = value
    else:
        try:
            t = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"{field}은 ISO 8601 형식이어야 합니다 (예: 2026-11-14T19:00:00+09:00)") from None
    return (t if t.tzinfo else t.replace(tzinfo=KST)).astimezone(KST)


def decorate(review: Review, meta: dict | None) -> dict:
    """리뷰 dict + source·received_at·reply. 상태는 기록이 있으면 기록 값. 계약 칸(input_method 등)은 그대로."""
    meta = meta or {}
    d = review.to_dict()
    d["source"] = meta.get("source") or ("sample" if review.input_method == "sample" else "paste")
    d["received_at"] = meta.get("received_at")
    d["reply"] = meta.get("reply")
    d["menu"] = meta.get("menu")          # 주문 메뉴 (가상 배달앱이 보낸 값, 없으면 null)
    if meta.get("status"):
        d["status"] = meta["status"]
    return d


def decorated_reviews(store_id: str = DEFAULT_STORE, visitor_id: str | None = None) -> list[dict]:
    meta = meta_for(store_id, visitor_id)
    return [decorate(r, meta.get(r.review_id)) for r in all_reviews(store_id, visitor_id)]


def list_reviews(store_id: str = DEFAULT_STORE, visitor_id: str | None = None, *, since: str | None = None,
                 source: str | None = None) -> list[dict]:
    """since 를 주면 그 시각 뒤에 실제로 받은 리뷰만 (받은 순서). 합성 리뷰는 받은 시각이 없어 빠진다.
    since 가 없으면 지금처럼 작성 시각이 늦은 것부터."""
    if source is not None and source not in SOURCES + ("sample",):
        raise ValueError(f"source 는 sample, {', '.join(SOURCES)} 중 하나여야 합니다")
    rows = decorated_reviews(store_id, visitor_id)
    if source is not None:
        rows = [r for r in rows if r["source"] == source]
    if since is None:
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)
    after = parse_time(since, "since")
    rows = [r for r in rows if r["received_at"] and parse_time(r["received_at"]) > after]
    return sorted(rows, key=lambda r: r["received_at"])


def set_status(store_id: str, visitor_id: str | None, review_id: str, status: str, *, reply_text: str | None = None,
               at: str | datetime | None = None) -> dict:
    """답글 승인·건너뜀 등 상태 기록. replied 에 글을 주면 답글로 저장해 리뷰 조회 응답에 함께 돌려준다."""
    if status not in REVIEW_STATUSES:
        raise ValueError(f"상태는 {', '.join(REVIEW_STATUSES)} 중 하나여야 합니다")
    review = next((r for r in all_reviews(store_id, visitor_id) if r.review_id == review_id), None)
    if review is None:
        raise LookupError(review_id)
    when = parse_time(at, "at") or datetime.now(KST)
    stamp = when.isoformat(timespec="seconds")
    fields: dict = {"status": status, "status_at": stamp}
    if reply_text is not None:
        reply_text = reply_text.strip()
        if not 1 <= len(reply_text) <= MAX_TEXT:
            raise ValueError(f"답글은 1~{MAX_TEXT}자여야 합니다")
        if status != "replied":
            raise ValueError("답글 글은 status 가 replied 일 때만 보낼 수 있습니다")
        fields["reply"] = {"text": reply_text, "replied_at": stamp}
    row = records.update(store_id, record_owner(review_id, visitor_id), review_id, fields, {"status": status, "at": stamp})
    return decorate(review, row)


class Timeline:
    """응대 기한·점수·보고서를 여러 시각으로 계산할 때 쓰는 재료 (리뷰·기록·분류를 한 번만 읽는다).
    분류는 저장할 때(POST /reviews) 이미 끝나 저장본(캐시)에 있으므로 보통 모델을 다시 부르지 않는다."""

    def __init__(self, classifier: Classifier, store_id: str = DEFAULT_STORE, visitor_id: str | None = None):
        from app import response
        self.store_id, self.policy = store_id, response.policy()
        self.reviews = all_reviews(store_id, visitor_id)
        meta = meta_for(store_id, visitor_id)
        self.rows = [decorate(r, meta.get(r.review_id)) | {"history": (meta.get(r.review_id) or {}).get("history") or []}
                     for r in self.reviews]
        self.classes = classifier.classify(self.reviews)
        self.negative = {c.review_id: c.negative_topics for c in self.classes}

    def arrival(self, row: dict) -> datetime:
        """실제로 받은 시각. 합성 샘플은 받은 시각이 없어 작성 시각(시나리오 시각)을 쓴다 (보고서 날짜 나누기용)."""
        return parse_time(row["received_at"] or row["created_at"])

    def insight_at(self, now: datetime):
        present = {row["review_id"] for row in self.rows if not row["received_at"] or parse_time(row["received_at"]) <= now}
        reviews = [r for r in self.reviews if r.review_id in present]
        return build_insight(self.store_id, reviews, [c for c in self.classes if c.review_id in present]) if reviews else None

    def at(self, now: datetime) -> dict:
        from app import response
        insight = self.insight_at(now)
        groups = [g.to_dict() for g in insight.groups] if insight else []
        return response.evaluate(self.rows, self.negative, groups, now, self.policy)
