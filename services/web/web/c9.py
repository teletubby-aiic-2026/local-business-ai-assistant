"""C9 발표 모드 저장본.

한 파일(web_cache.json)에 ①~③ 을 모두 고정한다: 가게·리뷰·분류/묶음(insight)·상권 지표·카드 2장·카드별 생성 결과.
replay 는 이 파일만 읽으므로 네트워크·#14·키가 없어도 같은 입력에서 항상 같은 결과가 나온다.
승인 기록(④)은 저장본에 넣지 않는다 (data/runtime/ 에 따로, 저장소에 올리지 않음).

막는 것: '개발용 가짜 값' 지표가 섞여 있으면 기록도 재생도 하지 않는다 (결정안 4절 정직 표기).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from shared.contracts import AnalysisSnapshot

from .sources import is_dev_fake

VERSION = 1
KST = timezone(timedelta(hours=9))


class CacheError(RuntimeError):
    pass


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def load_cache(path: Path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != VERSION:
        raise CacheError(f"저장본 형식이 다릅니다 (version {data.get('version')}). 다시 기록하세요.")
    return data


def fake_snapshot_ids(snapshots: list[AnalysisSnapshot] | list[dict]) -> list[str]:
    found = []
    for snap in snapshots:
        obj = AnalysisSnapshot.from_dict(snap) if isinstance(snap, dict) else snap
        if is_dev_fake(obj):
            found.append(obj.snapshot_id)
    return found


def replay_blockers(cache: dict | None) -> list[str]:
    if cache is None:
        return ["발표 모드 저장본이 없어요. APP_MODE=mock 또는 live 로 띄운 뒤 화면의 '발표 모드로 저장'을 누르세요."]
    fakes = fake_snapshot_ids(cache.get("snapshots", []))
    if fakes:
        return [f"저장본에 개발용 가짜 지표가 있어 발표 모드로 열 수 없어요: {', '.join(fakes)}"]
    return []


def write_cache(path: Path, payload: dict[str, Any]) -> Path:
    fakes = fake_snapshot_ids(payload.get("snapshots", []))
    if fakes:
        raise CacheError(f"개발용 가짜 지표가 있어 저장하지 않았어요: {', '.join(fakes)}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": VERSION, **payload}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path
