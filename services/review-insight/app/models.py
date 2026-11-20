"""리뷰 분석 모듈의 데이터 형식.

⚠️ 임시 형식입니다. C1 데이터 계약(dataclass 5개)이 확정되면 이 파일만 그 형식으로 바꾸고,
나머지 코드는 이 클래스들의 필드 이름만 쓰므로 함께 맞춥니다.
필드 이름은 팀 규칙대로 snake_case, 시각은 한국 시간 ISO 8601, 값이 없으면 null.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

CHANNELS = ("baemin", "coupangeats", "yogiyo", "naver_place")
SENTIMENTS = ("positive", "negative", "mixed", "neutral")
POLARITIES = ("positive", "negative")


@dataclass
class Review:
    review_id: str
    store_id: str
    channel: Optional[str]
    rating: Optional[int]
    text: str
    created_at: str
    input_method: str = "sample"          # sample(합성 샘플) | paste(직접 붙여넣기)
    pii_masked: bool = False
    order_ref: Optional[str] = None       # 규격 4.3. 이 모듈은 주문을 다루지 않아 항상 null
    status: str = "new"                   # 규격 4.3: new → analyzed → drafted → replied (skipped)
    data_origin: str = "synthetic"

    @classmethod
    def from_dict(cls, d: dict) -> "Review":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__ if k in d})

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TopicHit:
    topic: str            # 주제 사전(topics.py)의 id
    polarity: str         # positive | negative
    evidence: str         # 리뷰 글에 그대로 있는 근거 구절 (규칙으로 확인)


@dataclass
class ReviewClassification:
    review_id: str
    sentiment: str                          # positive | negative | mixed | neutral
    topics: list[TopicHit] = field(default_factory=list)
    summary: Optional[str] = None           # 한 줄 요약 (금지 표현이 있으면 지움)
    method: str = "rule"                    # model | replay | rule | rule_fallback
    model: Optional[str] = None
    warnings: list[str] = field(default_factory=list)   # 규칙 검증에서 고친 내용

    @property
    def negative_topics(self) -> list[str]:
        return sorted({t.topic for t in self.topics if t.polarity == "negative"})

    def to_dict(self) -> dict:
        d = asdict(self)
        d["negative_topics"] = self.negative_topics
        return d


@dataclass
class IssueGroup:
    """같은 불만이 2건 이상 모인 묶음. 3건 이상이면 반복(is_repeated).
    같은 리뷰들이 두 주제에 함께 걸리면 한 묶음으로 합칩니다 (예: 양·맛)."""
    issue_id: str
    topics: list[str]                       # 이 묶음의 주제들 (대부분 1개, 합쳐지면 2개 이상)
    topic: str                              # 대표 주제 (topics[0])
    topic_name: str                         # 화면 이름 (예: "포장 누락", "양·맛")
    review_count: int
    is_repeated: bool                       # review_count >= 3
    review_ids: list[str]
    evidence: list[dict]                    # [{review_id, quote}] 근거 구절
    time_bands: dict                        # 상권 데이터와 같은 시간대 구간별 건수 {"17~21시": 5, ...}. 작성 시각을 아는 리뷰만 셈 (붙여넣은 리뷰 빼고), 그런 리뷰가 없으면 {}
    main_time_band: Optional[str]           # 한 구간에 60% 이상 몰렸으면 그 구간, 아니면 null
    channels: dict                          # 채널별 건수
    recent_count: int                       # 최근 절반 기간 건수
    previous_count: int                     # 그 앞 절반 기간 건수
    first_at: str
    last_at: str

    def to_dict(self) -> dict:
        return asdict(self)


RepeatedIssue = IssueGroup   # 예전 이름


@dataclass
class ReviewInsight:
    """C5 추천 카드·C6 생성이 가져다 쓰는 결과 한 덩어리.
    와우 브리핑: review_count건 → 불만 complaint_count건 → groups(묶음) + single_complaints(단발)"""
    store_id: str
    period_start: str
    period_end: str
    review_count: int
    complaint_count: int                    # 불만이 하나라도 있는 리뷰 수
    sentiment_counts: dict
    topic_counts: dict                      # {topic: {"positive": n, "negative": n}}
    groups: list[IssueGroup]                # 2건 이상 묶음 (반복 먼저, 큰 것 먼저)
    single_complaints: list[dict]           # 어느 묶음에도 안 든 불만 [{review_id, topics, topic_names, quote, created_at, channel}]
    classifications: list[ReviewClassification]
    data_origin: str = "synthetic"

    @property
    def repeated_issues(self) -> list[IssueGroup]:
        return [g for g in self.groups if g.is_repeated]

    @property
    def top_issue(self) -> IssueGroup | None:
        """카드 ⓐ: 가장 큰 반복 묶음 1개 (없으면 None)"""
        return self.repeated_issues[0] if self.repeated_issues else None

    def to_dict(self) -> dict:
        return {
            "store_id": self.store_id, "period_start": self.period_start, "period_end": self.period_end,
            "review_count": self.review_count, "complaint_count": self.complaint_count,
            "sentiment_counts": self.sentiment_counts, "topic_counts": self.topic_counts,
            "group_count": len(self.groups), "single_complaint_count": len(self.single_complaints),
            "top_issue_id": self.top_issue.issue_id if self.top_issue else None,
            "groups": [g.to_dict() for g in self.groups],
            "repeated_issues": [i.to_dict() for i in self.repeated_issues],
            "single_complaints": self.single_complaints,
            "classifications": [c.to_dict() for c in self.classifications],
            "data_origin": self.data_origin,
        }
