"""Read-only B2 sales from preserved, provenance-checked Seoul source pages.

No model, provider request, settings load or legacy release mutation belongs
here. A complete source distribution is required before shares or ranks exist.
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
import threading

from app.data_repository import DISTRIBUTION_FIELDS, SOURCE_URLS, canonical_hash
from app.onboarding_analysis_catalog import get_analysis_catalog_source


_ROOT = Path(__file__).resolve().parents[1]
_RAW = _ROOT / "data/raw/official"
_SERVICE = "VwsmTrdarSelngQq"
_TOTAL_FIELD = "THSMON_SELNG_AMT"
_GROUPS = {"weekday": ("요일별 매출", DISTRIBUTION_FIELDS["sales_weekday"]),
           "time": ("시간대별 매출", DISTRIBUTION_FIELDS["sales_time"]),
           "age": ("연령별 매출", DISTRIBUTION_FIELDS["sales_age"])}
_FIELDS = [_TOTAL_FIELD] + [field for _, fields in _GROUPS.values() for _, field in fields]
_ROW_FIELDS = set(_FIELDS) | {"STDR_YYQU_CD", "TRDAR_CD", "TRDAR_CD_NM", "SVC_INDUTY_CD", "SVC_INDUTY_CD_NM"}
_CACHE = OrderedDict()
_CACHE_LOCK = threading.RLock()


class SalesDataError(ValueError):
    """Stored source/provenance is not safe to use. HTTP hides its details."""


def _money(value):
    if value is None or value == "":
        return None
    if type(value) is int:
        if value < 0:
            raise SalesDataError("Negative monetary observation")
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+(?:\.0+)?", value):
        return int(Decimal(value))
    if isinstance(value, Decimal) and value.is_finite() and value >= 0 and value == value.to_integral_value():
        return int(value)
    if type(value) is float and math.isfinite(value) and 0 <= value < 2 ** 53 and value.is_integer():
        return int(value)
    raise SalesDataError("Monetary observation is not an exact nonnegative integer")


def _percent(value, denominator):
    if not denominator:
        return None
    return float((Decimal(value) * 100 / Decimal(denominator)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _observation(row, field):
    try:
        value = _money(row.get(field)) if row is not None else None
    except SalesDataError:
        return {"status": "invalid", "value": None, "value_text": None}
    return {"status": "available" if value is not None else "missing", "value": value,
            "value_text": str(value) if value is not None else None}


def _distribution(row, kind, total):
    label, fields = _GROUPS[kind]
    items = [{"label": name, "field": field, **_observation(row, field), "share_percent": None}
             for name, field in fields]
    complete = all(item["status"] == "available" for item in items)
    subtotal = sum(item["value"] for item in items) if complete else None
    total_value = total["value"]
    difference = subtotal - total_value if subtotal is not None and total_value is not None else None
    warnings = []
    if row is None:
        status = "no_data"
    elif any(item["status"] == "invalid" for item in items):
        status = "invalid"
        warnings.append("유효하지 않은 원천 금액이 있어 비중과 순위를 제공하지 않습니다.")
    elif not complete or total["status"] != "available":
        status = "partial" if any(item["status"] == "available" for item in items) else "no_data"
        warnings.append("분포 항목 또는 분기 총액이 없어 전체 분포의 비중과 순위를 제공하지 않습니다.")
    elif (kind != "age" and difference != 0) or (kind == "age" and difference > 0):
        status = "inconsistent"
        warnings.append("분포 합계와 분기 총액의 관계를 확인하지 못해 비중과 순위를 제공하지 않습니다.")
    else:
        status = "complete"
    denominator_value = subtotal if kind == "age" else total_value
    denominator = {"kind": "age_classified_total" if kind == "age" else "quarter_total",
        "label": "연령이 분류된 매출 합계" if kind == "age" else "분기 추정매출 총액",
        "value": denominator_value, "value_text": str(denominator_value) if denominator_value is not None else None}
    ranking = {"status": "unavailable", "highest": [], "lowest": [], "highest_value": None, "lowest_value": None}
    if status == "complete":
        for item in items:
            item["share_percent"] = _percent(item["value"], denominator_value)
        high, low = max(item["value"] for item in items), min(item["value"] for item in items)
        ranking = {"status": "available", "highest": [i["label"] for i in items if i["value"] == high],
            "lowest": [i["label"] for i in items if i["value"] == low], "highest_value": high, "lowest_value": low}
        if not denominator_value:
            warnings.append("분모가 0원이므로 비중을 계산할 수 없습니다. 금액은 관측된 0원입니다.")
    coverage = _percent(subtotal, total_value) if kind == "age" and subtotal is not None else None
    if kind == "age":
        warnings.append("비중은 전체 매출이 아닌 연령이 분류된 매출 내 비중입니다.")
        if difference is not None and difference != 0:
            warnings.append("연령 분류 합계와 총액의 차이를 전부 법인 매출로 단정할 수 없습니다.")
        if coverage is not None and coverage < 50:
            warnings.append("연령이 분류된 금액이 전체 매출의 절반 미만이므로 전체 고객 특성으로 일반화하지 마세요.")
    elif kind == "time":
        warnings.append("시간대 구간의 길이가 서로 다릅니다. 구간별 분기 누적 금액이며 시간당 매출 순위가 아닙니다.")
    else:
        warnings.append("요일별 분기 누적 매출이며 해당 요일의 하루 평균 매출이 아닙니다.")
    return {"label": label, "status": status, "items": items, "denominator": denominator,
        "sum": subtotal, "total_difference": difference, "classified_share_of_total_percent": coverage,
        "ranking": ranking, "warnings": warnings}


def analyze_sales_row(row: dict | None, selection: dict, industry_name: str) -> dict:
    """Pure interpretation of one selected source row, including missing data."""
    total = {**_observation(row, _TOTAL_FIELD), "unit": "원", "label": "분기 추정매출"}
    distributions = {kind: _distribution(row, kind, total) for kind in _GROUPS}
    conditions = {key: deepcopy(selection[key]) for key in
                  ("area_code", "area_name", "industry_code", "period", "period_label", "catalog_version", "boundary")}
    conditions["industry_name"] = industry_name
    warnings = ["상권·업종의 분기 추정매출이며 개별 가게의 실제 매출이나 특정 월 매출이 아닙니다.",
        "요일·시간대·연령은 각각 별도 분포이며 서로 결합한 교차 매출을 뜻하지 않습니다.",
        "지도는 2023년 공개 경계이며 선택 분기의 경계와 같은지는 확인되지 않았습니다."]
    summary = []
    if total["status"] == "available":
        summary.append(f"{selection['area_name']}의 {industry_name} {selection['period_label']} 추정매출은 {total['value']:,}원입니다.")
        for kind in ("weekday", "time"):
            dist = distributions[kind]
            if dist["ranking"]["status"] == "available" and dist["ranking"]["highest_value"] > 0:
                highest = dist["ranking"]["highest"]
                prefix = "공동으로 가장 높은" if len(highest) > 1 else "가장 높은"
                summary.append(f"{dist['label']}에서 {prefix} 항목은 {', '.join(highest)}이며 {dist['ranking']['highest_value']:,}원입니다.")
    elif total["status"] == "invalid":
        total["message"] = "원천 총액의 금액 형식을 확인하지 못했습니다. 0원이나 자료 없음으로 해석하지 마세요."
        warnings.append(total["message"])
    else:
        warnings.append("선택한 상권·업종·분기의 추정매출 총액 자료가 없습니다. 다른 업종이나 기간으로 대체하지 않았습니다.")
    return {"status": "available" if total["status"] == "available" else "invalid" if total["status"] == "invalid" else "no_data", "selection": conditions,
        "total": total, "distributions": distributions, "summary": summary, "warnings": warnings}


def _load_sales_period(source, period, raw_root):
    if not any(entry["dataset"] == "sales" for entry in source["files"]):
        raise SalesDataError("Sales source provenance is absent")
    files = [entry for entry in source["files"] if entry["dataset"] == "sales" and entry["period"] == period]
    if not files:
        return None, {}, []
    paths = []
    for entry in files:
        name = Path(entry["path"]).name
        if entry["path"] != "data/raw/official/" + name or not re.fullmatch(r"sales_" + re.escape(period) + r"_all_[A-Za-z0-9_.-]+\.json", name):
            raise SalesDataError("Unexpected sales source path")
        paths.append(raw_root / name)
    if {p.name for p in raw_root.glob(f"sales_{period}_all_*.json")} != {p.name for p in paths}:
        raise SalesDataError("Sales source set changed")
    signature = tuple((path.name, path.stat().st_mtime_ns, path.stat().st_size) for path in paths)
    key = (str(raw_root.resolve()), source["catalog_version"], period, signature)
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
        rows, evidence_by_key, pages, evidence = {}, {}, [], []
        for path, entry in zip(paths, files):
            data = path.read_bytes()
            if sha256(data).hexdigest() != entry["file_sha256"]:
                raise SalesDataError("Sales source hash differs from B1 catalogue")
            doc = json.loads(data.decode("utf-8-sig"))
            query, payload = doc["query"], doc["payload"]
            response = payload[_SERVICE]
            if (doc["service"] != _SERVICE or doc["source_url"] != SOURCE_URLS["sales"] or doc["sample_only"] is not False
                    or query["dataset"] != "sales" or query["period"] != period or query["area_code"] is not None
                    or canonical_hash(payload) != doc["payload_sha256"] or doc["payload_sha256"] != entry["payload_sha256"]
                    or response["RESULT"]["CODE"] != "INFO-000"):
                raise SalesDataError("Invalid sales source provenance")
            records, count, start, total = response["row"], query["count"], query["start"], response["list_total_count"]
            if (any(type(v) is not int or v < 1 for v in (count, start, total)) or not isinstance(records, list)
                    or len(records) != min(count, total - start + 1) or not records
                    or start != entry["start"] or len(records) != entry["row_count"]):
                raise SalesDataError("Invalid sales source page")
            # Official JSON uses decimal number tokens for monetary amounts.
            # Verify the legacy canonical payload hash above, but interpret
            # those tokens exactly instead of losing digits through binary
            # floats before checking that won amounts are integral.
            records = json.loads(data.decode("utf-8-sig"), parse_float=Decimal)["payload"][_SERVICE]["row"]
            proof = {"file_name": path.name, "file_sha256": entry["file_sha256"],
                "payload_sha256": entry["payload_sha256"], "source_url": SOURCE_URLS["sales"], "fields": list(_FIELDS)}
            evidence.append(proof)
            pages.append((start, len(records), total))
            for row in records:
                if (not isinstance(row, dict) or row.get("STDR_YYQU_CD") != period
                        or not isinstance(row.get("TRDAR_CD"), str) or not re.fullmatch(r"[0-9]{7}", row["TRDAR_CD"])
                        or not isinstance(row.get("SVC_INDUTY_CD"), str) or not re.fullmatch(r"CS[0-9]{6}", row["SVC_INDUTY_CD"])):
                    raise SalesDataError("Invalid sales row identity")
                identity = (row["TRDAR_CD"], row["SVC_INDUTY_CD"])
                if identity in rows:
                    raise SalesDataError("Duplicate sales row")
                rows[identity] = {field: value for field, value in row.items() if field in _ROW_FIELDS}
                evidence_by_key[identity] = proof
        next_start, totals = 1, {page[2] for page in pages}
        if len(totals) != 1:
            raise SalesDataError("Sales source page totals changed")
        for start, count, _total in sorted(pages):
            if start != next_start:
                raise SalesDataError("Missing or overlapping sales source page")
            next_start += count
        if next_start - 1 != next(iter(totals)):
            raise SalesDataError("Incomplete sales source coverage")
        # Do not cache a source that changed during the initial cold read.
        if signature != tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in paths):
            raise SalesDataError("Sales source changed during reading")
        result = (rows, evidence_by_key, evidence)
        _CACHE[key] = result
        while len(_CACHE) > 4:
            _CACHE.popitem(last=False)
        return result


def build_sales_analysis(selection: dict, profile: dict, *, raw_root: Path | None = None) -> dict:
    source = get_analysis_catalog_source()
    if source["catalog_version"] != selection["catalog_version"] or selection["industry_code"] != profile["industry"]["code"]:
        raise SalesDataError("Selection does not match the source or profile")
    rows, evidence_by_key, period_evidence = _load_sales_period(source, selection["period"], Path(raw_root) if raw_root is not None else _RAW)
    identity = (selection["area_code"], selection["industry_code"])
    row = rows.get(identity) if rows is not None else None
    if row is not None and (row.get("TRDAR_CD_NM") != selection["area_name"] or row.get("SVC_INDUTY_CD_NM") != profile["industry"]["name"]):
        raise SalesDataError("Sales source names differ from the selected identities")
    result = analyze_sales_row(row, selection, profile["industry"]["name"])
    result["coverage_status"] = "collected" if rows is not None else "not_collected"
    result["observation_status"] = result["total"]["status"] if row is not None else "no_observation" if rows is not None else "not_collected"
    if rows is None:
        result["total"]["status"] = "not_collected"
        result["total"]["message"] = "선택 분기의 추정매출 원천 자료를 확보하지 않았습니다. 0원이라는 뜻이 아닙니다."
        result["warnings"].append(result["total"]["message"])
    result["data_version"] = "b2_" + canonical_hash({"schema": "sales-v1", "catalog_version": source["catalog_version"],
        "period": selection["period"], "files": [(e["file_name"], e["file_sha256"]) for e in period_evidence]})[:24]
    result["source"] = {"title": "서울시 상권분석서비스 추정매출", "url": SOURCE_URLS["sales"], "unit": "원", "period_basis": "quarter"}
    result["evidence"] = deepcopy([evidence_by_key[identity]] if row is not None else period_evidence)
    return result
