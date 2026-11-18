"""서버에 적재한 상권 자료 상태와 서울시 최신 발행 분기를 확인한다.

이 모듈은 서비스가 쓰는 공식 원본(data/raw/official)과 분석 카탈로그
(data/official)를 읽기만 하고 바꾸지 않는다. 앱은 시작할 때 읽은 카탈로그를
계속 쓰므로, 새 분기가 발행돼도 여기서 자료를 교체하거나 수집하지 않는다.
쓰기는 마지막 실시간 확인 시각을 담은 작은 JSON 하나뿐이며, 그 파일은
ONBOARDING_DB_PATH가 있는 폴더(서비스 계정이 쓸 수 있는 곳)에만 둔다.
인증키는 SeoulClient가 환경 변수에서 읽으며 응답·로그에 넣지 않는다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import re
import threading
import time

from app.config import ROOT
from app.data_repository import atomic_json_write
from app.seoul_client import SeoulApiError, SeoulClient

STATUS_SCHEMA = "onboarding-data-status-v1"
SYNC_SCHEMA = "onboarding-data-sync-v1"
STATE_SCHEMA = "onboarding-data-sync-state-v1"
STATE_FILE = "market-data-sync.json"
KST = timezone(timedelta(hours=9))
DATASETS = ("sales", "stores", "population")
DATASET_LABELS = {"sales": "추정매출", "stores": "점포", "population": "길단위인구"}
# prepare_data의 기본 수집 범위 마지막 분기. 서버에 자료가 없을 때만 기준으로 쓴다.
FALLBACK_LATEST_PERIOD = "20262"
NEXT_QUARTERS = 2
PROBE_COUNT = 5
PROBE_TIMEOUT_SECONDS = 5
SYNC_COOLDOWN_SECONDS = 30
CATALOG_ERRORS = (OSError, ValueError, KeyError, TypeError, ImportError)
LOOKUP_FAILED = "서울 열린데이터광장 응답을 확인하지 못했어요."
SAMPLE_NOTICE = ("SEOUL_OPENAPI_KEY가 설정되지 않아 서울시 공개 샘플 키로 자료마다 1~5건만 확인했어요. "
                 "정식 확인에는 인증키가 필요해요.")

_log = logging.getLogger("app.data_sync")
_PERIOD = re.compile(r"20\d{2}[1-4]")


class DataSyncBusy(RuntimeError):
    """다른 실시간 확인이 이미 진행 중이다."""


def period_label(period: str) -> str:
    return f"{period[:4]}년 {period[4]}분기"


def next_period(period: str) -> str:
    year, quarter = int(period[:4]), int(period[4])
    return f"{year + 1}1" if quarter == 4 else f"{year}{quarter + 1}"


def _default_catalog_source() -> dict:
    from app.onboarding_analysis_catalog import get_analysis_catalog_source

    return get_analysis_catalog_source()


def _safe_relative(path_text) -> Path | None:
    if not isinstance(path_text, str):
        return None
    relative = Path(path_text)
    if relative.is_absolute() or ".." in relative.parts or not path_text.startswith("data/raw/official/"):
        return None
    return relative


def read_local_snapshot(catalog_source=_default_catalog_source, root: Path = ROOT) -> dict | None:
    """앱이 읽은 분석 카탈로그에서 분기·원본 파일·분기별 전체 건수를 정리한다.

    파일 내용은 준비 단계에서 SHA-256으로 검증했다. 여기서는 그 목록의 파일이
    지금도 서버에 있는지만 센다(요청마다 수백 MB를 다시 해시하지 않는다).
    """
    try:
        source = catalog_source()
        files = source["files"]
        if not isinstance(files, list):
            raise TypeError("catalogue files must be a list")
    except CATALOG_ERRORS:
        return None
    root = Path(root)
    periods: set[str] = set()
    dataset_periods: dict[str, set[str]] = {name: set() for name in DATASETS}
    totals: dict[tuple[str, str], int] = {}
    present = 0
    for entry in files:
        if not isinstance(entry, dict):
            continue
        relative = _safe_relative(entry.get("path"))
        if relative is not None and (root / relative).is_file():
            present += 1
        dataset, period = entry.get("dataset"), entry.get("period")
        if dataset not in DATASETS or not isinstance(period, str) or _PERIOD.fullmatch(period) is None:
            continue
        periods.add(period)
        dataset_periods[dataset].add(period)
        rows = entry.get("row_count")
        if entry.get("area_code") is None and type(rows) is int and rows >= 0:
            totals[(dataset, period)] = totals.get((dataset, period), 0) + rows
    if not periods:
        return None
    return {
        "catalog_version": source.get("catalog_version"),
        "periods": sorted(periods),
        "dataset_periods": {name: sorted(values) for name, values in dataset_periods.items()},
        "listed_files": len(files),
        "verified_files": present,
        "totals": totals,
    }


def _resolve_dir(value) -> Path | None:
    if value is None:
        return None
    try:
        target = value() if callable(value) else value
    except (OSError, ValueError):
        return None
    return Path(target) if target is not None else None


def key_configured() -> bool:
    # SeoulClient와 같은 규칙으로 판단한다(빈 값·'sample'은 미설정). 키 값은 돌려주지 않는다.
    return not SeoulClient().sample_only


class DataSyncService:
    """GET data-status와 POST data-sync의 실제 동작. 한 번에 하나의 확인만 한다."""

    def __init__(self, *, state_dir=None, client_factory=None, catalog_source=_default_catalog_source,
                 root: Path = ROOT, now=None, monotonic=time.monotonic,
                 timeout: float = PROBE_TIMEOUT_SECONDS, cooldown_seconds: float = SYNC_COOLDOWN_SECONDS):
        self._state_dir = state_dir
        self._client_factory = client_factory or (lambda: SeoulClient(timeout=timeout))
        self._catalog_source = catalog_source
        self._root = Path(root)
        self._now = now or (lambda: datetime.now(KST))
        self._monotonic = monotonic
        self._cooldown = cooldown_seconds
        self._lock = threading.Lock()
        self._last_result: dict | None = None
        self._last_finished: float | None = None

    # 상태 파일 ------------------------------------------------------------
    def _state_path(self) -> Path | None:
        folder = _resolve_dir(self._state_dir)
        return folder / STATE_FILE if folder is not None else None

    def _read_state(self) -> dict | None:
        path = self._state_path()
        if path is None:
            return None
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(state, dict) or state.get("schema_version") != STATE_SCHEMA:
            return None
        if not isinstance(state.get("last_synced_at"), str):
            return None
        return state

    def _write_state(self, result: dict) -> bool:
        path = self._state_path()
        if path is None:
            return False
        state = {"schema_version": STATE_SCHEMA, "last_synced_at": result["checked_at"],
                 "status": result["status"], "local_latest_period": result["local_latest_period"],
                 "remote_latest_period": result["remote_latest_period"], "totals": result["totals"]}
        try:
            atomic_json_write(path, state)
        except (OSError, ValueError, TypeError) as error:
            _log.warning("data-sync state was not saved: %s", type(error).__name__)
            return False
        return True

    # GET /data-status -----------------------------------------------------
    def status(self) -> dict:
        local = read_local_snapshot(self._catalog_source, self._root)
        state = self._read_state()
        last_sync = None if state is None else {
            "checked_at": state["last_synced_at"], "status": state.get("status"),
            "remote_latest_period": state.get("remote_latest_period")}
        result = {"schema_version": STATUS_SCHEMA, "key_configured": key_configured(),
                  "last_synced_at": state["last_synced_at"] if state else None, "last_sync": last_sync}
        if local is None:
            result.update(status="data_required", data_ready=False, latest_period=None, latest_period_label=None,
                          periods=[], period_count=0, catalog_version=None, listed_files=0, verified_files=0,
                          missing_files=0, local_totals=None,
                          message="서버에 준비된 상권 자료가 없어요. 관리자가 상권 자료 묶음을 설치하면 표시돼요.")
            return result
        periods, latest = local["periods"], local["periods"][-1]
        missing = local["listed_files"] - local["verified_files"]
        if missing:
            message = f"상권 자료 원본 {missing}개를 서버에서 찾지 못했어요. 관리자 확인이 필요해요."
        else:
            message = (f"서버에 {period_label(periods[0])}~{period_label(latest)} 상권 자료 "
                       f"{len(periods)}개 분기가 준비돼 있어요.")
        result.update(status="source_files_missing" if missing else "ready", data_ready=not missing,
                      latest_period=latest, latest_period_label=period_label(latest), periods=periods,
                      period_count=len(periods), dataset_periods=local["dataset_periods"],
                      catalog_version=local["catalog_version"], listed_files=local["listed_files"],
                      verified_files=local["verified_files"], missing_files=missing,
                      local_totals={name: local["totals"].get((name, latest)) for name in DATASETS},
                      message=message)
        return result

    # POST /data-sync ------------------------------------------------------
    def sync(self) -> dict:
        if not self._lock.acquire(blocking=False):
            raise DataSyncBusy()
        try:
            if (self._last_result is not None and self._last_finished is not None
                    and self._monotonic() - self._last_finished < self._cooldown):
                return {**self._last_result, "reused": True}
            result = self._run()
            if not result["errors"]:
                self._last_result, self._last_finished = result, self._monotonic()
            return {**result, "reused": False}
        finally:
            self._lock.release()

    def _probe(self, client, dataset: str, period: str) -> dict:
        try:
            page = client.fetch_page(dataset, period, 1, PROBE_COUNT)
            parsed = page.parsed
            total = parsed.total_count
            if type(total) is not int or total < 0 or parsed.result_code not in ("INFO-000", "INFO-200"):
                raise SeoulApiError("Invalid API response: unexpected probe result.")
        except SeoulApiError as error:
            # SeoulApiError 문구에는 요청 주소나 키가 들어가지 않는다.
            _log.warning("data-sync probe failed (%s %s): %s", dataset, period, error)
            return {"result_code": None, "total": None, "published": None,
                    "error": LOOKUP_FAILED, "error_detail": str(error)}
        except Exception as error:  # noqa: BLE001 - 어떤 실패도 500으로 올리지 않는다.
            _log.warning("data-sync probe failed (%s %s): %s", dataset, period, type(error).__name__)
            return {"result_code": None, "total": None, "published": None,
                    "error": LOOKUP_FAILED, "error_detail": type(error).__name__}
        return {"result_code": parsed.result_code, "total": total,
                "published": parsed.result_code == "INFO-000" and total > 0, "error": None, "error_detail": None}

    def _run(self) -> dict:
        local = read_local_snapshot(self._catalog_source, self._root)
        baseline = local["periods"][-1] if local else FALLBACK_LATEST_PERIOD
        upcoming, cursor = [], baseline
        for _ in range(NEXT_QUARTERS):
            cursor = next_period(cursor)
            upcoming.append(cursor)
        try:
            client = self._client_factory()
        except Exception as error:  # noqa: BLE001
            _log.warning("data-sync client unavailable: %s", type(error).__name__)
            client = None
        sample_only = bool(getattr(client, "sample_only", False))
        jobs = [(dataset, period) for dataset in DATASETS for period in [baseline, *upcoming]]
        if client is None:
            failed = {"result_code": None, "total": None, "published": None,
                      "error": LOOKUP_FAILED, "error_detail": "ClientUnavailable"}
            outcomes = {job: dict(failed) for job in jobs}
        else:
            # 9번의 짧은 조회를 3개씩 나눠 보내 전체 대기 시간을 줄인다.
            with ThreadPoolExecutor(max_workers=len(DATASETS), thread_name_prefix="data-sync") as pool:
                futures = {job: pool.submit(self._probe, client, *job) for job in jobs}
                outcomes = {job: future.result() for job, future in futures.items()}

        datasets, totals, errors, mismatched = {}, {}, [], []
        for dataset in DATASETS:
            current = outcomes[(dataset, baseline)]
            local_total = local["totals"].get((dataset, baseline)) if local else None
            matches = (current["total"] == local_total) if current["error"] is None and local_total is not None else None
            datasets[dataset] = {
                "label": DATASET_LABELS[dataset], "period": baseline, "total": current["total"],
                "result_code": current["result_code"], "local_total": local_total, "matches_local": matches,
                "error": current["error"], "error_detail": current["error_detail"],
                "next": {period: {key: outcomes[(dataset, period)][key] for key in
                                  ("result_code", "total", "published", "error", "error_detail")}
                         for period in upcoming},
            }
            totals[dataset] = current["total"]
            if any(outcomes[(dataset, period)]["error"] for period in [baseline, *upcoming]):
                errors.append(dataset)
            if local and matches is not True and current["error"] is None:
                mismatched.append(dataset)

        next_periods = []
        for period in upcoming:
            published = [d for d in DATASETS if outcomes[(d, period)]["published"]]
            next_periods.append({"period": period, "label": period_label(period),
                                 "published": len(published) == len(DATASETS),
                                 "published_datasets": published,
                                 "unknown_datasets": [d for d in DATASETS if outcomes[(d, period)]["error"]]})
        newly = [item for item in next_periods if item["published_datasets"]]
        baseline_published = all(outcomes[(d, baseline)]["published"] for d in DATASETS)
        remote_latest = newly[-1]["period"] if newly else (baseline if baseline_published else None)

        apply_hint = None
        if newly:
            newest = newly[-1]
            names = "·".join(DATASET_LABELS[d] for d in newest["published_datasets"])
            status = "next_published"
            message = (f"서울 열린데이터광장 실시간 조회 완료: 서울시에 {newest['label']} 자료({names})가 새로 발행됐어요. "
                       "서비스 자료는 바꾸지 않았어요.")
            apply_hint = (f"{newest['label']} 자료는 자동으로 반영하지 않아요. 서비스를 멈춘 뒤 새 분기를 포함해 수집·검증한 "
                          "상권 자료 묶음을 다시 설치하거나 `python -m scripts.prepare_data --from-dir <검증한 원본 폴더>`로 "
                          "준비하고 서비스를 다시 시작해 주세요. 앱은 시작할 때 읽은 카탈로그를 쓰므로 실행 중에 파일만 바꾸면 안 돼요.")
        elif errors:
            status = "incomplete"
            names = "·".join(DATASET_LABELS[d] for d in errors)
            message = (f"서울 열린데이터광장 실시간 조회를 마치지 못했어요: {names} 자료를 확인하지 못했어요. "
                       "잠시 후 다시 시도해 주세요.")
        elif local is None:
            status = "data_required"
            message = (f"서울 열린데이터광장 실시간 조회 완료: 현재 서울시 최신 발행 분기는 {period_label(baseline)}이며 "
                       "서버에는 아직 상권 자료가 준비되지 않았어요.")
        elif not mismatched and baseline_published:
            status = "up_to_date"
            message = (f"서울 열린데이터광장 실시간 조회 완료: 현재 서울시 최신 발행 분기는 {period_label(baseline)}이며 "
                       "서버 적재본과 일치합니다")
        else:
            status = "differs"
            names = "·".join(DATASET_LABELS[d] for d in mismatched) or "일부 자료"
            message = (f"서울 열린데이터광장 실시간 조회 완료: 다음 분기 자료는 아직 없지만 {period_label(baseline)} {names} "
                       "전체 건수가 서버 적재본과 일치하지 않아요. 서비스 자료는 바꾸지 않았어요.")

        result = {
            "schema_version": SYNC_SCHEMA, "status": status, "message": message,
            "checked_at": self._now().astimezone(KST).isoformat(timespec="seconds"),
            "sample_only": sample_only, "notice": SAMPLE_NOTICE if sample_only else None,
            "local_latest_period": local["periods"][-1] if local else None,
            "checked_period": baseline, "checked_period_label": period_label(baseline),
            "remote_latest_period": remote_latest,
            "remote_latest_period_label": period_label(remote_latest) if remote_latest else None,
            "totals": totals, "datasets": datasets, "next_periods": next_periods,
            "next_published": bool(newly), "staged": None, "apply_hint": apply_hint,
            "data_changed": False, "errors": errors,
        }
        saved = False
        if not sample_only and not errors:
            saved = self._write_state(result)
        state = self._read_state()
        result["state_saved"] = saved
        result["last_synced_at"] = state["last_synced_at"] if state else None
        return result
