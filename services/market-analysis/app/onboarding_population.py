"""B4 area-wide source population indicators; no daily/unique conversion."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import threading

from app.data_repository import DISTRIBUTION_FIELDS, SOURCE_URLS, canonical_hash
from app.onboarding_analysis_catalog import get_analysis_catalog_source

_RAW = Path(__file__).resolve().parents[1] / "data/raw/official"
_SERVICE = "VwsmTrdarFlpopQq"
_TOTAL = "TOT_FLPOP_CO"
_GROUPS = {"time": ("시간대별 유동인구 원천 지표", DISTRIBUTION_FIELDS["population_time"]),
    "age": ("연령별 유동인구 원천 지표", [
        ("연령대 10 (원천 분류)", "AGRDE_10_FLPOP_CO"), ("연령대 20", "AGRDE_20_FLPOP_CO"),
        ("연령대 30", "AGRDE_30_FLPOP_CO"), ("연령대 40", "AGRDE_40_FLPOP_CO"),
        ("연령대 50", "AGRDE_50_FLPOP_CO"), ("연령대 60 이상", "AGRDE_60_ABOVE_FLPOP_CO")])}
_FIELDS = [_TOTAL] + [field for _label, fields in _GROUPS.values() for _name, field in fields]
_CACHE = OrderedDict()
_LOCK = threading.RLock()
MEANING_NOTE = "사용한 원천 총지표의 시간 집계·환산 기준은 확인되지 않았습니다. 일평균·월평균·고유 방문자 수로 변환하지 않았습니다."


class PopulationDataError(ValueError):
    """Stored source/provenance cannot safely support this result."""


def _integer(value):
    if value is None or value == "":
        return None
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+(?:\.0+)?", value):
        return int(Decimal(value))
    if isinstance(value, Decimal) and value.is_finite() and value >= 0 and value == value.to_integral_value():
        return int(value)
    if type(value) is float and math.isfinite(value) and 0 <= value < 2 ** 53 and value.is_integer():
        return int(value)
    raise PopulationDataError("Population observation is not an exact nonnegative integer")


def _observation(row, field):
    try:
        value = _integer(row.get(field)) if row is not None else None
    except PopulationDataError:
        return {"status": "invalid", "value": None, "value_text": None}
    return {"status": "available" if value is not None else "missing", "value": value,
            "value_text": str(value) if value is not None else None}


def _distribution(row, kind, total):
    label, fields = _GROUPS[kind]
    items = [{"label": name, "field": field, **_observation(row, field), "share_percent": None} for name, field in fields]
    complete = all(item["status"] == "available" for item in items)
    subtotal = sum(item["value"] for item in items) if complete else None
    difference = subtotal - total["value"] if subtotal is not None and total["value"] is not None else None
    if row is None:
        status = "no_data"
    elif any(item["status"] == "invalid" for item in items):
        status = "invalid"
    elif not complete or total["status"] != "available":
        status = "partial" if any(item["status"] == "available" for item in items) else "no_data"
    else:
        status = "complete" if difference == 0 else "inconsistent"
    ranking = {"status": "unavailable", "highest": [], "lowest": [], "highest_value": None, "lowest_value": None}
    warnings = []
    if status == "complete":
        for item in items:
            if total["value"]:
                item["share_percent"] = float((Decimal(item["value"]) * 100 / Decimal(total["value"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        high, low = max(i["value"] for i in items), min(i["value"] for i in items)
        ranking = {"status": "available", "highest": [i["label"] for i in items if i["value"] == high],
            "lowest": [i["label"] for i in items if i["value"] == low], "highest_value": high, "lowest_value": low}
        if total["value"] == 0:
            warnings.append("원천 총지표가 관측된 0이므로 비중은 계산하지 않습니다.")
    elif status == "inconsistent":
        warnings.append(f"분포 합계와 원천 총지표의 차이는 {difference:+,}명입니다. 차이의 원인을 확정할 수 없어 비중과 순위를 보류합니다.")
    elif status != "no_data":
        warnings.append("분포 항목 또는 총지표가 누락되었거나 유효하지 않아 비중과 순위를 보류합니다.")
    if kind == "time":
        warnings.append("시간대 구간 길이가 다릅니다. 시간당 유동인구나 일평균으로 환산한 값이 아닙니다.")
    else:
        warnings.append("연령대 숫자는 원천 분류입니다. 연령대 10을 10대 이하 등 확인되지 않은 범위로 바꾸지 않았습니다.")
    return {"label": label, "status": status, "items": items, "sum": subtotal, "total_difference": difference,
        "denominator": {"kind": "source_total", "label": "원천 총 유동인구 지표", "value": total["value"],
                        "value_text": total["value_text"]}, "ranking": ranking, "warnings": warnings}


def analyze_population_row(row: dict | None, selection: dict, industry_name: str, *, collected=True) -> dict:
    total = {**_observation(row if collected else None, _TOTAL), "label": "지역 유동인구 원천 총지표", "unit": "명"}
    distributions = {kind: _distribution(row if collected else None, kind, total) for kind in _GROUPS}
    conditions = {key: deepcopy(selection[key]) for key in
                  ("area_code", "area_name", "industry_code", "period", "period_label", "catalog_version", "boundary")}
    conditions["industry_name"] = industry_name
    warnings = ["상권 전체의 원천 지표이며 선택 업종의 고객 수나 개별 가게의 방문자 수가 아닙니다.", MEANING_NOTE,
        "시간대·연령 분포는 별도 집계이며 두 분포를 결합한 교차 인구를 만들지 않습니다.",
        "지도는 2023년 공개 경계이며 선택 분기의 경계와 같은지는 확인되지 않았습니다."]
    summary = []
    if total["status"] == "available":
        status = "available"
        summary.append(f"{selection['area_name']} {selection['period_label']} 자료의 원천 총 유동인구 지표는 {total['value']:,}명입니다.")
    elif total["status"] == "invalid":
        status = "invalid"
        total["message"] = "원천 총지표의 숫자 형식을 확인하지 못했습니다. 0이나 자료 없음으로 해석하지 마세요."
        warnings.append(total["message"])
    else:
        status = "no_data"
        warnings.append("선택 분기의 유동인구 원천 자료를 수집하지 않았습니다." if not collected
                        else "수집한 자료에서 선택 상권의 총 유동인구 지표를 확인하지 못했습니다. 다른 상권이나 기간으로 대체하지 않았습니다.")
    return {"status": status, "selection": conditions, "industry_applied": False, "population_scope": "area_wide",
        "coverage_status": "collected" if collected else "not_collected", "total": total,
        "observation_status": "not_collected" if not collected else "no_observation" if row is None else total["status"],
        "distributions": distributions, "summary": summary, "warnings": warnings}


def _load_period(source, period, raw_root):
    population_files = [entry for entry in source["files"] if entry["dataset"] == "population"]
    if not population_files:
        raise PopulationDataError("Population source provenance is absent")
    files = [entry for entry in population_files if entry["period"] == period]
    if not files:
        return None, []
    paths = []
    for entry in files:
        name = Path(entry["path"]).name
        if (entry["path"] != "data/raw/official/" + name or entry["area_code"] is not None
                or not re.fullmatch(r"population_" + re.escape(period) + r"_all_[A-Za-z0-9_.-]+\.json", name)):
            raise PopulationDataError("Unexpected population source path")
        paths.append(raw_root / name)
    if {p.name for p in raw_root.glob(f"population_{period}_all_*.json")} != {p.name for p in paths}:
        raise PopulationDataError("Population source file set changed")
    signature = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in paths)
    # Linux can give two quick same-size writes the same mtime, so the
    # catalogue hashes are part of the key: a rewrite the catalogue records is
    # read and verified again, and cached evidence never carries old hashes.
    expected = tuple((entry["file_sha256"], entry["payload_sha256"]) for entry in files)
    key = (str(raw_root.resolve()), source["catalog_version"], period, signature, expected)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
        rows, evidence, pages = {}, [], []
        for path, entry in zip(paths, files):
            data = path.read_bytes()
            if sha256(data).hexdigest() != entry["file_sha256"]:
                raise PopulationDataError("Population source hash differs from B1 catalogue")
            doc = json.loads(data.decode("utf-8-sig"))
            query, payload = doc["query"], doc["payload"]
            response = payload[_SERVICE]
            if (doc["service"] != _SERVICE or doc["source_url"] != SOURCE_URLS["population"] or doc["sample_only"] is not False
                    or query["dataset"] != "population" or query["period"] != period or query["area_code"] is not None
                    or canonical_hash(payload) != doc["payload_sha256"] or doc["payload_sha256"] != entry["payload_sha256"]
                    or response["RESULT"]["CODE"] != "INFO-000"):
                raise PopulationDataError("Invalid population source provenance")
            records, count, start, total = response["row"], query["count"], query["start"], response["list_total_count"]
            if (any(type(v) is not int or v < 1 for v in (count, start, total)) or not isinstance(records, list)
                    or len(records) != min(count, total - start + 1) or not records
                    or start != entry["start"] or len(records) != entry["row_count"]):
                raise PopulationDataError("Invalid population source page")
            records = json.loads(data.decode("utf-8-sig"), parse_float=Decimal)["payload"][_SERVICE]["row"]
            pages.append((start, len(records), total))
            evidence.append({"file_name": path.name, "file_sha256": entry["file_sha256"],
                "payload_sha256": entry["payload_sha256"], "source_url": SOURCE_URLS["population"], "fields": list(_FIELDS)})
            for row in records:
                if (not isinstance(row, dict) or row.get("STDR_YYQU_CD") != period
                        or not isinstance(row.get("TRDAR_CD"), str) or not re.fullmatch(r"[0-9]{7}", row["TRDAR_CD"])):
                    raise PopulationDataError("Population source row identity mismatch")
                if row["TRDAR_CD"] in rows:
                    raise PopulationDataError("Duplicate population area row")
                rows[row["TRDAR_CD"]] = {field: value for field, value in row.items()
                    if field in _FIELDS or field in ("TRDAR_CD", "TRDAR_CD_NM", "STDR_YYQU_CD")}
        next_start, totals = 1, {page[2] for page in pages}
        if len(totals) != 1:
            raise PopulationDataError("Population source page totals changed")
        for start, count, _total in sorted(pages):
            if start != next_start:
                raise PopulationDataError("Missing or overlapping population source page")
            next_start += count
        if next_start - 1 != next(iter(totals)):
            raise PopulationDataError("Incomplete population source coverage")
        if signature != tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in paths):
            raise PopulationDataError("Population source changed during reading")
        result = rows, evidence
        _CACHE[key] = result
        while len(_CACHE) > 4:
            _CACHE.popitem(last=False)
        return result


def build_population_analysis(selection: dict, profile: dict, *, raw_root: Path | None = None) -> dict:
    source = get_analysis_catalog_source()
    if source["catalog_version"] != selection["catalog_version"] or selection["industry_code"] != profile["industry"]["code"]:
        raise PopulationDataError("Selection does not match source or contextual profile")
    rows, evidence = _load_period(source, selection["period"], Path(raw_root) if raw_root is not None else _RAW)
    row = rows.get(selection["area_code"]) if rows is not None else None
    if row is not None and row.get("TRDAR_CD_NM") != selection["area_name"]:
        raise PopulationDataError("Population area name differs from selected identity")
    result = analyze_population_row(row, selection, profile["industry"]["name"], collected=rows is not None)
    result["data_version"] = "b4_" + canonical_hash({"schema": "population-v1", "catalog_version": source["catalog_version"],
        "period": selection["period"], "files": [(entry["file_name"], entry["file_sha256"]) for entry in evidence]})[:24]
    result["source"] = {"title": "서울시 상권분석서비스 길단위인구", "url": SOURCE_URLS["population"], "unit": "명",
        "aggregation_basis": "source_total", "definition_verified": False, "meaning_note": MEANING_NOTE,
        "observed_area_count": len(rows) if rows is not None else 0,
        "coverage_note": "선택 분기에 실제 보관한 상권별 원천 자료를 조회합니다. 모든 상권의 관측 행이 존재한다는 뜻은 아닙니다."}
    result["evidence"] = deepcopy(evidence)
    return result
