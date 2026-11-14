"""B3 store observations from preserved, provenance-checked Seoul pages.

Current inventory composition and quarterly opening/closure counts stay
separate. No change rates or inferred inventory movement are calculated here.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sys
import threading

from app.data_repository import SOURCE_URLS, canonical_hash
from app.onboarding_analysis_catalog import get_analysis_catalog_source

_RAW = Path(__file__).resolve().parents[1] / "data/raw/official"
_SERVICE = "VwsmTrdarStorQq"
FIELDS = {"total": ("전체 점포", "SIMILR_INDUTY_STOR_CO"), "general": ("일반 점포", "STOR_CO"),
          "franchise": ("프랜차이즈 점포", "FRC_STOR_CO"), "opened": ("개업 점포", "OPBIZ_STOR_CO"),
          "closed": ("폐업 점포", "CLSBIZ_STOR_CO")}
_CACHE = OrderedDict()
_LOCK = threading.RLock()
_IDENTITY_FIELDS = ("TRDAR_CD", "TRDAR_CD_NM", "STDR_YYQU_CD", "SVC_INDUTY_CD", "SVC_INDUTY_CD_NM")


class StoresDataError(ValueError):
    """Stored source/provenance cannot safely support this result."""


def _count(value):
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
    raise StoresDataError("Store observation is not an exact nonnegative integer")


def _compact_row(row):
    result = {key: sys.intern(row[key]) if isinstance(row.get(key), str) else row.get(key) for key in _IDENTITY_FIELDS}
    for _label, field in FIELDS.values():
        value = row.get(field)
        try:
            result[field] = _count(value)
        except StoresDataError:
            # Keep invalid observations invalid; compacting never rounds or
            # substitutes zero. Valid integers need no Decimal in the cache.
            result[field] = value
    return result


def analyze_stores_row(row: dict | None, selection: dict, industry_name: str, *, collected=True) -> dict:
    counts = {}
    for key, (label, field) in FIELDS.items():
        value = None
        if not collected:
            status = "not_collected"
        elif row is None:
            status = "no_observation"
        else:
            try:
                value = _count(row.get(field))
                status = "available" if value is not None else "missing"
            except StoresDataError:
                status = "invalid"
        counts[key] = {"label": label, "field": field, "status": status, "value": value,
                       "value_text": str(value) if value is not None else None, "unit": "개"}
    total, general, franchise = (counts[key]["value"] for key in ("total", "general", "franchise"))
    subtotal = general + franchise if general is not None and franchise is not None else None
    difference = subtotal - total if subtotal is not None and total is not None else None
    if row is None or not collected:
        composition_status = "no_data"
    elif any(counts[key]["status"] != "available" for key in ("total", "general", "franchise")):
        composition_status = "incomplete"
    else:
        composition_status = "consistent" if difference == 0 else "inconsistent"
    composition_warnings = []
    share = None
    if composition_status == "consistent" and total > 0:
        share = float((Decimal(franchise) * 100 / Decimal(total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    elif composition_status == "consistent":
        composition_warnings.append("전체 점포가 관측된 0개이므로 프랜차이즈 비중을 계산하지 않습니다.")
    elif composition_status != "no_data":
        composition_warnings.append("전체 점포와 일반·프랜차이즈 합계를 확인하지 못해 프랜차이즈 비중을 제공하지 않습니다.")
    composition = {"status": composition_status, "sum": subtotal, "difference": difference,
        "franchise_share_percent": share, "denominator": {"label": "전체 점포 수", "value": total,
        "value_text": str(total) if total is not None else None}, "warnings": composition_warnings}
    if not collected:
        status = "not_collected"
    elif row is None:
        status = "no_observation"
    elif any(item["status"] == "invalid" for item in counts.values()):
        status = "invalid"
    elif any(item["status"] == "missing" for item in counts.values()) or composition_status != "consistent":
        status = "partial"
    else:
        status = "available"
    conditions = {key: deepcopy(selection[key]) for key in
                  ("area_code", "area_name", "industry_code", "period", "period_label", "catalog_version", "boundary")}
    conditions["industry_name"] = industry_name
    warnings = ["상권·업종의 점포 통계이며 개별 가게의 영업 상태를 확인한 결과가 아닙니다.",
        "개업·폐업 점포 수는 전체 점포 구성과 별도 항목입니다. 개업−폐업을 전체 점포의 기간 증감으로 해석하지 않습니다.",
        "개업률·폐업률을 현재 전체 점포 수로 임의 계산하지 않습니다.",
        "지도는 2023년 공개 경계이며 선택 분기의 경계와 같은지는 확인되지 않았습니다."]
    if status == "not_collected":
        warnings.append("선택한 상권·기간의 점포 원천 자료를 확보하지 않았습니다. 점포가 0개라는 뜻이 아닙니다.")
    elif status == "no_observation":
        warnings.append("수집한 상권·기간 자료에 해당 업종 행이 없습니다. 다른 업종이나 0개로 대체하지 않았습니다.")
    elif status == "invalid":
        warnings.append("일부 원천 점포 수의 숫자 형식을 확인하지 못했습니다. 0개나 자료 없음으로 해석하지 마세요.")
    elif status == "partial":
        warnings.append("일부 항목 또는 점포 구성 합계를 확인하지 못했습니다. 확인된 원천값만 표시합니다.")
    summary = []
    if counts["total"]["status"] == "available":
        summary.append(f"{selection['area_name']}의 {industry_name} {selection['period_label']} 전체 점포는 {total:,}개입니다.")
    if composition_status == "consistent":
        summary.append(f"일반 점포 {general:,}개와 프랜차이즈 {franchise:,}개의 합계가 전체 점포 수와 일치합니다.")
    return {"status": status, "selection": conditions, "counts": counts, "composition": composition,
            "summary": summary, "warnings": warnings}


def store_coverage_note(source, period):
    files = [entry for entry in source.get("files", []) if entry["dataset"] == "stores" and entry["period"] == period]
    label = f"{period[:4]}년 {period[4]}분기"
    if any(entry["area_code"] is None for entry in files):
        observed = source.get("observed_scope", {}).get("stores", {}).get(period, {}).get("areas")
        suffix = f" 관측 행이 있는 상권은 {observed:,}개입니다." if type(observed) is int else ""
        return f"{label} 점포 자료는 서울 전체 조회의 모든 페이지를 확보했습니다.{suffix} 모든 상권·업종의 관측 행이 존재한다는 뜻은 아닙니다."
    count = len({entry["area_code"] for entry in files})
    if count:
        return f"{label} 보관한 점포 원천은 {count}개 상권 범위입니다. 미수집 상권의 점포 수를 0으로 간주하지 않습니다."
    return f"{label} 점포 원천 자료를 확보하지 않았습니다. 점포가 0개라는 뜻이 아닙니다."


def _load_area_period(source, area_code, period, raw_root):
    store_files = [entry for entry in source["files"] if entry["dataset"] == "stores"]
    if not store_files:
        raise StoresDataError("Store source provenance is absent")
    period_files = [entry for entry in store_files if entry["period"] == period]
    citywide = any(entry["area_code"] is None for entry in period_files)
    scope = None if citywide else area_code
    files = [entry for entry in period_files if entry["area_code"] == scope]
    area_count = len({entry["area_code"] for entry in period_files if entry["area_code"] is not None})
    if not files:
        return None, [], area_count, "not_collected", []
    scope_name = "all" if citywide else area_code
    paths = []
    for entry in files:
        name = Path(entry["path"]).name
        if (entry["path"] != "data/raw/official/" + name
                or not re.fullmatch(r"stores_" + re.escape(period) + "_" + re.escape(scope_name) + r"_[A-Za-z0-9_.-]+\.json", name)):
            raise StoresDataError("Unexpected stores source path")
        paths.append(raw_root / name)
    if {p.name for p in raw_root.glob(f"stores_{period}_{scope_name}_*.json")} != {p.name for p in paths}:
        raise StoresDataError("Store source file set changed")
    signature = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in paths)
    # Linux can give two quick same-size writes the same mtime, so the
    # catalogue hashes are part of the key: a rewrite the catalogue records is
    # read and verified again, and cached evidence never carries old hashes.
    expected = tuple((entry["file_sha256"], entry["payload_sha256"]) for entry in files)
    cache_key = (str(raw_root.resolve()), source["catalog_version"], scope, period, signature, expected)
    with _LOCK:
        if cache_key in _CACHE:
            _CACHE.move_to_end(cache_key)
            rows, evidence_by_area, evidence = _CACHE[cache_key]
            return rows.get(area_code, {}), evidence_by_area.get(area_code, evidence), len(rows) if citywide else area_count, "citywide" if citywide else "selected_areas", evidence
        rows, pages, evidence, evidence_by_area = {}, [], [], {}
        for path, entry in zip(paths, files):
            data = path.read_bytes()
            if sha256(data).hexdigest() != entry["file_sha256"]:
                raise StoresDataError("Store source hash differs from B1 catalogue")
            doc = json.loads(data.decode("utf-8-sig"))
            query, payload = doc["query"], doc["payload"]
            response = payload[_SERVICE]
            if (doc["service"] != _SERVICE or doc["source_url"] != SOURCE_URLS["stores"] or doc["sample_only"] is not False
                    or query["dataset"] != "stores" or query["period"] != period or query["area_code"] != scope
                    or canonical_hash(payload) != doc["payload_sha256"] or doc["payload_sha256"] != entry["payload_sha256"]
                    or response["RESULT"]["CODE"] != "INFO-000"):
                raise StoresDataError("Invalid stores source provenance")
            records, count, start, total = response["row"], query["count"], query["start"], response["list_total_count"]
            if (any(type(v) is not int or v < 1 for v in (count, start, total)) or not isinstance(records, list)
                    or len(records) != min(count, total - start + 1) or not records
                    or start != entry["start"] or len(records) != entry["row_count"]):
                raise StoresDataError("Invalid stores source page")
            records = json.loads(data.decode("utf-8-sig"), parse_float=Decimal)["payload"][_SERVICE]["row"]
            pages.append((start, len(records), total))
            proof = {"file_name": path.name, "file_sha256": entry["file_sha256"],
                "payload_sha256": entry["payload_sha256"], "source_url": SOURCE_URLS["stores"],
                "fields": [field for _label, field in FIELDS.values()]}
            evidence.append(proof)
            page_areas = set()
            for row in records:
                if (not isinstance(row, dict) or row.get("STDR_YYQU_CD") != period
                        or not isinstance(row.get("TRDAR_CD"), str) or not re.fullmatch(r"[0-9]{7}", row["TRDAR_CD"])
                        or (scope is not None and row["TRDAR_CD"] != scope)
                        or not isinstance(row.get("SVC_INDUTY_CD"), str) or not re.fullmatch(r"CS[0-9]{6}", row["SVC_INDUTY_CD"])):
                    raise StoresDataError("Store source row identity mismatch")
                by_industry = rows.setdefault(row["TRDAR_CD"], {})
                if row["SVC_INDUTY_CD"] in by_industry:
                    raise StoresDataError("Duplicate store source row")
                by_industry[row["SVC_INDUTY_CD"]] = _compact_row(row)
                page_areas.add(row["TRDAR_CD"])
            for code in page_areas:
                evidence_by_area.setdefault(code, []).append(proof)
        next_start, totals = 1, {page[2] for page in pages}
        if len(totals) != 1:
            raise StoresDataError("Store source page totals changed")
        for start, count, _total in sorted(pages):
            if start != next_start:
                raise StoresDataError("Missing or overlapping store source page")
            next_start += count
        if next_start - 1 != next(iter(totals)):
            raise StoresDataError("Incomplete store source coverage")
        if signature != tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in paths):
            raise StoresDataError("Store source changed during reading")
        _CACHE[cache_key] = rows, evidence_by_area, evidence
        while len(_CACHE) > 8:
            _CACHE.popitem(last=False)
        return rows.get(area_code, {}), evidence_by_area.get(area_code, evidence), len(rows) if citywide else area_count, "citywide" if citywide else "selected_areas", evidence


def build_stores_analysis(selection: dict, profile: dict, *, raw_root: Path | None = None) -> dict:
    source = get_analysis_catalog_source()
    if source["catalog_version"] != selection["catalog_version"] or selection["industry_code"] != profile["industry"]["code"]:
        raise StoresDataError("Selection does not match source or profile")
    rows, evidence, area_count, scope, period_evidence = _load_area_period(source, selection["area_code"], selection["period"], Path(raw_root) if raw_root is not None else _RAW)
    row = rows.get(selection["industry_code"]) if rows is not None else None
    if row is not None and (row.get("TRDAR_CD_NM") != selection["area_name"] or row.get("SVC_INDUTY_CD_NM") != profile["industry"]["name"]):
        raise StoresDataError("Store names differ from selected identities")
    result = analyze_stores_row(row, selection, profile["industry"]["name"], collected=rows is not None)
    result["data_version"] = "b3_" + canonical_hash({"schema": "stores-v1", "catalog_version": source["catalog_version"],
        "area_code": selection["area_code"], "period": selection["period"],
        "files": [(entry["file_name"], entry["file_sha256"]) for entry in period_evidence]})[:24]
    result["source"] = {"title": "서울시 상권분석서비스 점포", "url": SOURCE_URLS["stores"], "unit": "개",
        "period_basis": "quarter", "collected_area_count": area_count, "collection_scope": scope,
        "coverage_note": store_coverage_note(source, selection["period"])}
    result["evidence"] = deepcopy(evidence)
    return result
