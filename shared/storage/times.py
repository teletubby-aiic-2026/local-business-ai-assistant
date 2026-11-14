"""시각·날짜 변환. 이 프로젝트는 시각을 한국 시간(+09:00) ISO 문자열로 다룬다 (shared/contracts.py)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def to_kst_iso(value: datetime | str) -> str:
    """datetime(또는 ISO 문자열)을 '2026-11-09T23:00:00+09:00' 모양으로. 시간대가 없으면 한국 시간으로 본다."""
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST).isoformat(timespec="seconds")


def to_datetime(value: datetime | str) -> datetime:
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    return dt.replace(tzinfo=KST) if dt.tzinfo is None else dt


def to_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else date.fromisoformat(value)
