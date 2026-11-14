"""데이터를 가져오는 곳 세 군데와 형식 변환.

- 리뷰·분류·묶음: C3(PR #14) 서비스를 HTTP로 부른다. #12·#14 모두 최상위 패키지가 app/ 이라 같은 프로세스에
  import하면 이름이 부딪히므로 import하지 않는다.
- 상권 지표: C4 스냅샷 JSON 파일 (AnalysisSnapshot 목록).
- 변환(G2): #14의 리뷰 + insight.classifications → C1의 ReviewRecord. #14가 아직 자체 Review 클래스를 써서
  이 변환이 어디에도 없었다.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import httpx

from shared.contracts import AnalysisSnapshot, ReviewRecord, StoreProfile, load_json
from shared.sample_scenario import SAMPLE_STORE

DEV_FAKE_PREFIX = "개발용 가짜 값"


class SourceError(RuntimeError):
    """밖의 데이터를 못 가져왔을 때. 화면에는 message 를 그대로 보여 준다."""


class ReviewSource:
    """C3(PR #14) /api/review-insight/* 를 부르는 얇은 클라이언트."""

    def __init__(self, base_url: str, token: str = "", timeout: float = 10.0, client: httpx.Client | None = None):
        headers = {"X-Access-Token": token} if token else {}
        self._client = client or httpx.Client(base_url=base_url, headers=headers, timeout=timeout)
        self.base_url = base_url
        self.visitor_id: str | None = None

    def for_visitor(self, visitor_id: str | None) -> "ReviewSource":
        """같은 연결을 쓰되, 리뷰·분석·붙여넣기·지우기 요청마다 이 방문자 id 를 붙이는 사본.
        리뷰 분석 서버가 방문자별로 붙여넣은 리뷰를 따로 둔다. 합성 리뷰는 모두에게 같다."""
        view = copy.copy(self)
        view.visitor_id = visitor_id or None
        return view

    def _visitor(self) -> dict[str, str]:
        return {"visitor_id": self.visitor_id} if self.visitor_id else {}

    def _get(self, path: str, **params: Any) -> Any:
        try:
            res = self._client.get(f"/api/review-insight{path}", params=params)
        except httpx.HTTPError as exc:
            raise SourceError(f"리뷰 분석 서비스({self.base_url})에 연결하지 못했습니다: {exc.__class__.__name__}") from None
        return self._json(res)

    @staticmethod
    def _json(res: httpx.Response) -> Any:
        if res.status_code == 401:
            raise SourceError("리뷰 분석 서비스가 접근 토큰을 요구합니다. REVIEW_INSIGHT_TOKEN 을 확인하세요.")
        if res.status_code >= 400:
            try:
                message = res.json().get("error", {}).get("message") or res.text
            except ValueError:
                message = res.text
            raise SourceError(f"리뷰 분석 서비스 오류 {res.status_code}: {message}")
        return res.json()

    def health(self) -> dict:
        try:
            res = self._client.get("/api/health")
            return res.json() if res.status_code == 200 else {"status": f"http {res.status_code}"}
        except httpx.HTTPError as exc:
            return {"status": "down", "error": exc.__class__.__name__}

    def store(self, store_id: str) -> dict:
        return self._get("/store", store_id=store_id)

    def reviews(self, store_id: str) -> list[dict]:
        data = self._get("/reviews", store_id=store_id, **self._visitor())
        return data["items"] if isinstance(data, dict) else data

    def insight(self, store_id: str) -> dict:
        return self._get("/insight", store_id=store_id, **self._visitor())

    def paste(self, store_id: str, text: str, rating: int | None = None, channel: str | None = None) -> dict:
        body = {"store_id": store_id, "text": text, **self._visitor()}
        if rating is not None:
            body["rating"] = rating
        if channel:
            body["channel"] = channel
        try:
            res = self._client.post("/api/review-insight/reviews", json=body)
        except httpx.HTTPError as exc:
            raise SourceError(f"리뷰 분석 서비스({self.base_url})에 연결하지 못했습니다: {exc.__class__.__name__}") from None
        return self._json(res)

    def reset_pasted(self, store_id: str) -> dict:
        try:
            res = self._client.delete("/api/review-insight/reviews/pasted", params={"store_id": store_id, **self._visitor()})
        except httpx.HTTPError as exc:
            raise SourceError(f"리뷰 분석 서비스({self.base_url})에 연결하지 못했습니다: {exc.__class__.__name__}") from None
        return self._json(res)


# ── 상권 지표 ────────────────────────────────────────────────────────
def load_snapshots(path: Path) -> list[AnalysisSnapshot]:
    """C4 스냅샷 JSON. 파일이 없으면 빈 목록 (카드 ⓑ 가 안 뜨고, 화면이 그 이유를 보여 준다)."""
    if not Path(path).exists():
        return []
    loaded = load_json(AnalysisSnapshot, path)
    return loaded if isinstance(loaded, list) else [loaded]


def is_dev_fake(snapshot: AnalysisSnapshot) -> bool:
    """실제 값이 오기 전의 화면용 가짜 지표. 이게 하나라도 있으면 화면 맨 위에 경고 띠를 띄운다."""
    return snapshot.note.strip().startswith(DEV_FAKE_PREFIX)


# ── 형식 변환 ────────────────────────────────────────────────────────
def to_store_profile(store: dict, area_name: str | None) -> StoreProfile:
    """#14 store.json → StoreProfile. 메뉴 가격(C6 쿠폰용)은 #14 에 없어서 C1 샘플 가게가 같은 가게일 때만 가져온다."""
    names = StoreProfile.__dataclass_fields__
    data = {k: v for k, v in store.items() if k in names}
    if area_name:
        data["area_name"] = area_name
    if store.get("store_id") == SAMPLE_STORE.store_id and not data.get("menu_prices"):
        data["menu_prices"] = dict(SAMPLE_STORE.menu_prices)
    return StoreProfile.from_dict(data)


def to_review_records(reviews: list[dict], insight: dict) -> list[ReviewRecord]:
    """G2: #14 리뷰 + insight.classifications → ReviewRecord. 앞 11개 필드는 그대로, 분류 3개를 채운다."""
    names = ReviewRecord.__dataclass_fields__
    by_id = {c["review_id"]: c for c in insight.get("classifications", [])}
    records = []
    for review in reviews:
        data = {k: v for k, v in review.items() if k in names}
        found = by_id.get(review["review_id"])
        if found:
            topics: list[str] = []
            for hit in found.get("topics", []):
                topic = hit["topic"] if isinstance(hit, dict) else hit
                if topic not in topics:
                    topics.append(topic)
            negative = [t for t in found.get("negative_topics", []) if t in topics]
            data.update(sentiment=found.get("sentiment"), topics=topics, negative_topics=negative)
            if data.get("status", "new") == "new":
                data["status"] = "analyzed"
        records.append(ReviewRecord.from_dict(data))
    return records
