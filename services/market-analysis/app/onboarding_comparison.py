"""B5 same-industry/period comparison using the verified B2/B3/B4 readers."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP

from app.data_repository import SOURCE_URLS
from app.onboarding_analysis_catalog import get_analysis_area, get_analysis_areas, get_analysis_catalog_source
from app.onboarding_sales import build_sales_analysis
from app.onboarding_stores import build_stores_analysis, store_coverage_note
from app.onboarding_population import build_population_analysis

_DEFINITIONS = (
    ("sales", "추정매출", "원", "sales", None, "THSMON_SELNG_AMT", True),
    ("stores_total", "전체 점포", "개", "stores", "total", "SIMILR_INDUTY_STOR_CO", True),
    ("stores_general", "일반 점포", "개", "stores", "general", "STOR_CO", True),
    ("stores_franchise", "프랜차이즈 점포", "개", "stores", "franchise", "FRC_STOR_CO", True),
    ("stores_opened", "개업 점포", "개", "stores", "opened", "OPBIZ_STOR_CO", True),
    ("stores_closed", "폐업 점포", "개", "stores", "closed", "CLSBIZ_STOR_CO", True),
    ("floating_population", "지역 유동인구 원천 총지표", "명", "population", None, "TOT_FLPOP_CO", False),
)
_AREA_KEYS = ("area_code", "name", "district_code", "district_name", "type")
_SELECTION_KEYS = ("area_code", "area_name", "industry_code", "period", "period_label", "catalog_version", "boundary")
_WARNINGS = [
    "차이는 비교 상권−기준 상권이며 차이율의 분모는 기준 상권의 값입니다.",
    "추정매출은 상권·업종의 분기 추정치이며 개별 가게의 실제 매출이 아닙니다.",
    "상권의 크기·유형이 다를 수 있습니다. 총량 차이를 더 좋은 상권, 개별 가게의 성과 또는 입지 순위로 해석하지 마세요.",
    "유동인구는 상권 전체 원천 지표이며 선택 업종의 고객 수가 아닙니다. 일평균·고유 방문자 수로 변환하지 않았습니다.",
    "개업·폐업 점포 수는 각각 비교합니다. 개폐업률이나 전체 점포의 기간 증감은 계산하지 않습니다.",
    "지도는 2023년 공개 경계이며 선택 분기의 경계와 같은지는 확인되지 않았습니다.",
]


class ComparisonInputError(ValueError):
    """The explicitly requested comparison area is not selectable."""


class ComparisonDataError(ValueError):
    """Data definitions or conditions cannot safely be combined."""


def _base_context(selection, profile):
    source = get_analysis_catalog_source()
    if source["catalog_version"] != selection["catalog_version"] or profile["industry"]["code"] != selection["industry_code"]:
        raise ComparisonDataError("Comparison profile/catalogue mismatch")
    base = get_analysis_area(selection["area_code"])
    if (base is None or base["name"] != selection["area_name"]
            or base["boundary_identity_status"] != "code_name_match"):
        raise ComparisonDataError("Comparison base identity is not verified")
    return source, base


def _selection(selection, profile):
    return {**{key: deepcopy(selection[key]) for key in _SELECTION_KEYS}, "industry_name": profile["industry"]["name"]}


def get_comparison_options(selection: dict, profile: dict) -> dict:
    source, base = _base_context(selection, profile)
    official = get_analysis_areas()
    areas = []
    districts = {}
    for area in official:
        districts[area["district_code"]] = area["district_name"]
        if area["area_code"] == base["area_code"]:
            continue
        selectable = area["boundary_identity_status"] == "code_name_match"
        areas.append({**{key: area[key] for key in _AREA_KEYS}, "selectable": selectable,
            "reason": None if selectable else "공개 경계와 상권 자료의 명칭이 달라 연결 확인이 필요합니다."})
    areas.sort(key=lambda area: (area["district_name"], area["name"], area["area_code"]))
    return {"status": "ready", "selection": _selection(selection, profile), "catalog_version": source["catalog_version"],
        "districts": [{"code": code, "name": name} for code, name in sorted(districts.items(), key=lambda item: item[1])],
        "areas": areas, "scope": {"official_area_count": len(official), "base_excluded": True,
            "blocked_area_count": sum(not area["selectable"] for area in areas)},
        "warnings": [*_WARNINGS, store_coverage_note(source, selection["period"])]}


def _read(selection, profile):
    results = {"sales": build_sales_analysis(selection, profile), "stores": build_stores_analysis(selection, profile),
               "population": build_population_analysis(selection, profile)}
    return validate_reader_results(results, selection)


def validate_reader_results(results, selection):
    """Check each available reader's fixed measure definitions and conditions."""
    for dataset, result in results.items():
        expected_unit = {"sales": "원", "stores": "개", "population": "명"}[dataset]
        conditions = result["selection"]
        if any(conditions.get(key) != selection[key] for key in ("area_code", "area_name", "industry_code", "period", "catalog_version")):
            raise ComparisonDataError("Reader conditions do not match comparison conditions")
        if (result["source"].get("unit") != expected_unit or result["source"].get("url") != SOURCE_URLS[dataset]
                or not isinstance(result.get("data_version"), str) or not result["data_version"]
                or not isinstance(result.get("evidence"), list)):
            raise ComparisonDataError("Reader source/unit/schema mismatch")
        if dataset in ("sales", "stores") and result["source"].get("period_basis") != "quarter":
            raise ComparisonDataError("Quarterly measure definition changed")
        if dataset == "population" and (result.get("industry_applied") is not False
                or result.get("population_scope") != "area_wide" or result["source"].get("aggregation_basis") != "source_total"):
            raise ComparisonDataError("Population scope/aggregation definition changed")
    return results


def _observation(result, dataset, count_key, unit):
    observed = result["counts"][count_key] if count_key is not None else result["total"]
    status = observed["status"]
    if dataset in ("sales", "population") and status == "missing":
        status = result.get("observation_status", status)
    value = observed["value"]
    if observed.get("unit") != unit:
        raise ComparisonDataError("Observation unit differs from comparison definition")
    if status == "available":
        if type(value) is not int or value < 0 or observed.get("value_text") != str(value):
            raise ComparisonDataError("Observation is not an exact nonnegative integer")
    elif status not in ("missing", "invalid", "no_observation", "not_collected") or value is not None:
        raise ComparisonDataError("Unknown or contradictory observation state")
    return {"status": status, "value": value, "value_text": observed.get("value_text")}


def build_comparison_analysis(selection: dict, profile: dict, comparison_area_code: str) -> dict:
    _source, base = _base_context(selection, profile)
    other = get_analysis_area(comparison_area_code)
    if other is None or other["area_code"] == base["area_code"] or other["boundary_identity_status"] != "code_name_match":
        raise ComparisonInputError("기준과 다른 공식 상권을 목록에서 선택해 주세요. 연결 확인이 필요한 상권은 비교할 수 없습니다.")
    other_selection = {**deepcopy(selection), "area_code": other["area_code"], "area_name": other["name"]}
    base_results, other_results = _read(selection, profile), _read(other_selection, profile)
    metrics = []
    for key, label, unit, dataset, count_key, field, industry_applied in _DEFINITIONS:
        base_result, other_result = base_results[dataset], other_results[dataset]
        left = _observation(base_result, dataset, count_key, unit)
        right = _observation(other_result, dataset, count_key, unit)
        available = left["status"] == right["status"] == "available"
        delta = right["value"] - left["value"] if available else None
        percent = None
        percent_status = "unavailable"
        warnings = []
        if available:
            if left["value"] == 0:
                percent_status = "undefined_zero_base"
                warnings.append("기준 상권 값이 0이므로 차이율을 계산할 수 없습니다. 차이 값은 그대로 제공합니다.")
            else:
                percent_status = "available"
                percent = float((Decimal(delta) * 100 / Decimal(left["value"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        else:
            warnings.append("양쪽에서 확인된 값이 있는 지표만 차이와 차이율을 계산합니다. 결측을 0으로 바꾸지 않습니다.")
        if dataset == "stores" and any(result["composition"]["status"] not in ("consistent", "no_data") for result in (base_result, other_result)):
            warnings.append("점포 구성 합계에 확인이 필요한 부분이 있습니다. 이 행은 표시된 개별 원천 항목의 값만 비교합니다.")
        metrics.append({"key": key, "label": label, "unit": unit, "industry_applied": industry_applied,
            "base": left, "comparison": right, "delta": delta, "delta_text": str(delta) if delta is not None else None,
            "percent": percent, "percent_status": percent_status, "status": "available" if available else "unavailable",
            "source": {"title": base_result["source"]["title"], "url": SOURCE_URLS[dataset], "field": field},
            "evidence": {"base": deepcopy(base_result["evidence"]), "comparison": deepcopy(other_result["evidence"])},
            "warnings": warnings})
    count = sum(metric["status"] == "available" for metric in metrics)
    return {"status": "complete" if count == len(metrics) else "partial" if count else "no_data",
        "selection": _selection(selection, profile), "base_area": {key: base[key] for key in _AREA_KEYS},
        "comparison_area": {key: other[key] for key in _AREA_KEYS}, "comparison_direction": "comparison_minus_base",
        "metrics": metrics, "data_versions": {"base": {key: value["data_version"] for key, value in base_results.items()},
            "comparison": {key: value["data_version"] for key, value in other_results.items()}},
        "summary": [f"같은 업종·분기의 지표 {len(metrics)}개 중 {count}개를 비교했습니다. 차이는 비교 상권−기준 상권입니다."],
        "warnings": [*_WARNINGS, store_coverage_note(_source, selection["period"])]}
