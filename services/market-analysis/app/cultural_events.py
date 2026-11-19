"""서울시 문화행사 정보(culturalEventInfo)를 자치구별로 짧게 보여 준다.

서울 열린데이터광장 실시간 API가 주는 목록의 앞 40건을 받아 끝나지 않은 행사만
고른다(목록 순서는 서울시가 정한다). 응답은 메모리에 10분 보관하고(서울시 호출 1번을 모든 자치구가 함께 씀)
실패하면 1분 동안 다시 부르지 않는다. 인증키가 없거나 응답을 쓸 수 없으면
실제 행사로 오해하지 않도록 '예시' 표시를 단 가짜 목록과 안내를 돌려준다.
인증키는 SeoulClient가 환경 변수에서 읽으며 응답·로그에 넣지 않는다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import logging
import re
import threading
import time
from urllib.parse import urlsplit

from app.seoul_client import SeoulApiError, SeoulClient

SCHEMA = "onboarding-cultural-events-v1"
SERVICE = "culturalEventInfo"
FETCH_COUNT = 40
MAX_EVENTS = 20
CACHE_TTL_SECONDS = 600
FAILURE_TTL_SECONDS = 60
TIMEOUT_SECONDS = 5
KST = timezone(timedelta(hours=9))
SOURCE = {"provider": "서울 열린데이터광장", "dataset": "서울시 문화행사 정보", "service": SERVICE}
DISTRICT_PATTERN = re.compile(r"[가-힣]{1,9}구")

_log = logging.getLogger("app.cultural_events")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class CulturalEventsUnavailable(RuntimeError):
    """안전한 진단 문구만 담는다(요청 주소·키 없음)."""


def _text(value, limit: int = 200) -> str | None:
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = " ".join(_CONTROL.sub(" ", str(value)).split())
    if text in ("", "-", "null", "None"):
        return None
    return text[:limit]


def _date(value) -> date | None:
    text = _text(value, 40)
    if text is None:
        return None
    head = text[:10]
    for pattern in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(head, pattern).date()
        except ValueError:
            pass
    try:
        return datetime.strptime(text[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _period(row: dict) -> tuple[date | None, date | None]:
    start, end = _date(row.get("STRTDATE")), _date(row.get("END_DATE"))
    if start is None or end is None:
        # DATE 항목은 'YYYY-MM-DD~YYYY-MM-DD' 형식이다.
        parts = (_text(row.get("DATE"), 60) or "").split("~")
        if len(parts) == 2:
            start = start or _date(parts[0].strip())
            end = end or _date(parts[1].strip())
        elif len(parts) == 1 and parts[0]:
            start = start or _date(parts[0])
            end = end or start
    return start, end


def _link(row: dict) -> str | None:
    for key in ("ORG_LINK", "HMPG_ADDR"):
        value = _text(row.get(key), 500)
        if value is None:
            continue
        try:
            parts = urlsplit(value)
        except ValueError:
            continue
        # 화면에서 바로 여는 링크라서 http(s) 주소만 넘긴다.
        if parts.scheme in ("http", "https") and parts.netloc and " " not in value:
            return value
    return None


def _is_free(row: dict) -> bool | None:
    value = _text(row.get("IS_FREE"), 10)
    if value == "무료":
        return True
    if value == "유료":
        return False
    fee = _text(row.get("USE_FEE"), 200)
    if fee is not None and fee.replace(" ", "") in ("무료", "무료관람", "무료입장"):
        return True
    return None


def normalize_event(row) -> dict | None:
    """원본 한 행을 화면용 9개 항목으로 바꾼다. 제목·기간을 읽을 수 없으면 버린다."""
    if not isinstance(row, dict):
        return None
    title = _text(row.get("TITLE"))
    start, end = _period(row)
    if title is None or start is None or end is None or end < start:
        return None
    return {"title": title, "category": _text(row.get("CODENAME"), 60), "place": _text(row.get("PLACE")),
            "district": _text(row.get("GUNAME"), 20), "start": start.isoformat(), "end": end.isoformat(),
            "is_free": _is_free(row), "fee": _text(row.get("USE_FEE")), "link": _link(row)}


def _code(value) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[A-Z]+-\d{3}", value) else "invalid"


def parse_events(payload) -> list[dict]:
    """서울시 응답 봉투를 확인한다. 잘못된 응답은 CulturalEventsUnavailable."""
    if not isinstance(payload, dict):
        raise CulturalEventsUnavailable("invalid response: expected a JSON object")
    if SERVICE not in payload:
        code = payload["RESULT"].get("CODE") if isinstance(payload.get("RESULT"), dict) else None
        if code == "INFO-200":
            return []
        raise CulturalEventsUnavailable(f"provider result {_code(code)}")
    body = payload[SERVICE]
    if not isinstance(body, dict) or not isinstance(body.get("RESULT"), dict):
        raise CulturalEventsUnavailable("invalid response: missing service envelope")
    code = body["RESULT"].get("CODE")
    if code == "INFO-200":
        return []
    if code != "INFO-000":
        raise CulturalEventsUnavailable(f"provider result {_code(code)}")
    rows = body.get("row")
    if not isinstance(rows, list) or len(rows) > FETCH_COUNT:
        raise CulturalEventsUnavailable("invalid response: row must be a short list")
    events = [event for event in map(normalize_event, rows) if event is not None]
    if rows and not events and not any(isinstance(row, dict) for row in rows):
        raise CulturalEventsUnavailable("invalid response: rows are not objects")
    return events


def demo_events(today: date, district: str | None) -> list[dict]:
    """실제 행사가 아닌 자리 표시용 예시. 실제 이름·장소·링크를 쓰지 않는다."""
    where = district or "서울"
    return [
        {"title": "[예시] 동네 공연 행사 (실제 행사 아님)", "category": "예시", "place": f"{where} 예시 장소",
         "district": district, "start": today.isoformat(), "end": (today + timedelta(days=6)).isoformat(),
         "is_free": True, "fee": "예시", "link": None},
        {"title": "[예시] 주말 전시 행사 (실제 행사 아님)", "category": "예시", "place": f"{where} 예시 장소",
         "district": district, "start": (today + timedelta(days=3)).isoformat(),
         "end": (today + timedelta(days=17)).isoformat(), "is_free": False, "fee": "예시", "link": None},
    ]


class CulturalEventsService:
    def __init__(self, *, client_factory=None, now=None, monotonic=time.monotonic,
                 ttl_seconds: float = CACHE_TTL_SECONDS, failure_ttl_seconds: float = FAILURE_TTL_SECONDS,
                 timeout: float = TIMEOUT_SECONDS):
        self._client_factory = client_factory or (lambda: SeoulClient(timeout=timeout))
        self._now = now or (lambda: datetime.now(KST))
        self._monotonic = monotonic
        self._ttl = ttl_seconds
        self._failure_ttl = failure_ttl_seconds
        self._lock = threading.Lock()
        self._cache: tuple[float, list[dict], str] | None = None
        self._failed_until: float | None = None

    def _rows(self) -> tuple[list[dict] | None, str | None, bool, str]:
        """(행사 목록, 받은 시각, 캐시 사용, 실패 사유). 키가 없으면 호출하지 않는다."""
        with self._lock:
            moment = self._monotonic()
            if self._cache is not None and moment < self._cache[0]:
                return self._cache[1], self._cache[2], True, ""
            if self._failed_until is not None and moment < self._failed_until:
                return None, None, False, "recent_failure"
            try:
                client = self._client_factory()
            except Exception as error:  # noqa: BLE001
                _log.warning("cultural events client unavailable: %s", type(error).__name__)
                return None, None, False, "unavailable"
            if getattr(client, "sample_only", True):
                return None, None, False, "missing_key"
            try:
                payload, _redacted_url = client.fetch_auxiliary(SERVICE, 1, FETCH_COUNT)
                events = parse_events(payload)
            except (SeoulApiError, CulturalEventsUnavailable) as error:
                # 두 예외 모두 요청 주소나 키를 담지 않는다.
                _log.warning("cultural events unavailable: %s", error)
                self._failed_until = moment + self._failure_ttl
                return None, None, False, "unavailable"
            except Exception as error:  # noqa: BLE001 - 어떤 실패도 500으로 올리지 않는다.
                _log.warning("cultural events unavailable: %s", type(error).__name__)
                self._failed_until = moment + self._failure_ttl
                return None, None, False, "unavailable"
            fetched_at = self._now().astimezone(KST).isoformat(timespec="seconds")
            self._cache = (moment + self._ttl, events, fetched_at)
            self._failed_until = None
            return events, fetched_at, False, ""

    def events(self, district: str | None) -> dict:
        today = self._now().astimezone(KST).date()
        rows, fetched_at, cached, reason = self._rows()
        base = {"schema_version": SCHEMA, "district": district, "source": dict(SOURCE)}
        if rows is None:
            notice = ("서울 열린데이터광장 인증키가 설정되지 않아 예시 행사를 보여 드려요. 실제 행사가 아니에요."
                      if reason == "missing_key" else
                      "서울시 문화행사 정보를 지금 불러오지 못해 예시 행사를 보여 드려요. 실제 행사가 아니에요. "
                      "잠시 후 다시 확인해 주세요.")
            events = demo_events(today, district)
            return {**base, "status": "demo", "demo": True, "scope": "example", "fallback": False,
                    "events": events, "count": len(events), "fetched_at": None, "cached": False, "notice": notice}
        current = [event for event in rows if event["end"] >= today.isoformat()]
        current.sort(key=lambda event: (event["start"], event["end"], event["title"]))
        matched = [event for event in current if district and event["district"] == district]
        fallback = bool(district) and not matched
        chosen = (matched if matched else current)[:MAX_EVENTS]
        if not chosen:
            notice = "지금 확인되는 진행 중이거나 예정된 서울시 문화행사가 없어요."
        elif fallback:
            notice = f"{district}에서 진행 중이거나 예정된 행사를 찾지 못해 서울 전체 주요 행사를 보여 드려요."
        else:
            notice = "서울시 문화행사 정보에서 받은 40건 중 끝나지 않은 행사만 보여 드려요. 일정과 요금은 주최 측 안내를 꼭 확인해 주세요."
        return {**base, "status": "available", "demo": False, "scope": "district" if matched else "seoul",
                "fallback": fallback, "events": chosen, "count": len(chosen), "fetched_at": fetched_at,
                "cached": cached, "notice": notice}
