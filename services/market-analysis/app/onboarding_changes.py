"""B6 exact-quarter changes; missing periods never fall back to other data."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP

from app.data_repository import SOURCE_URLS
from app.domain import period_shift
from app.onboarding_comparison import _DEFINITIONS, _base_context, _observation, _selection, validate_reader_results
from app.onboarding_sales import build_sales_analysis
from app.onboarding_stores import build_stores_analysis, store_coverage_note, FIELDS as STORE_FIELDS
from app.onboarding_population import build_population_analysis


class ChangesInputError(ValueError):
    """The requested comparison mode is invalid."""


def _period_label(period):
    return f"{period[:4]}년 {period[4]}분기"


def _uncollected(dataset, selected):
    unit = {"sales": "원", "stores": "개", "population": "명"}[dataset]
    empty = {"status": "not_collected", "value": None, "value_text": None, "unit": unit}
    result = {"selection": deepcopy(selected), "data_version": None, "evidence": [],
        "source": {"title": {"sales": "서울시 상권분석서비스 추정매출", "stores": "서울시 상권분석서비스 점포",
                              "population": "서울시 상권분석서비스 길단위인구"}[dataset],
                   "url": SOURCE_URLS[dataset], "unit": unit, "period_basis": "quarter"}}
    if dataset == "stores":
        result["counts"] = {key: deepcopy(empty) for key in STORE_FIELDS}
        result["composition"] = {"status": "no_data"}
    else:
        result["total"] = empty
    if dataset == "population":
        result.update(industry_applied=False, population_scope="area_wide", observation_status="not_collected")
        result["source"]["aggregation_basis"] = "source_total"
    return result


def _read_period(source, selected, profile):
    readers = {"sales": build_sales_analysis, "stores": build_stores_analysis, "population": build_population_analysis}
    results, collection, actual = {}, {}, {}
    for dataset, reader in readers.items():
        collected = any(entry["dataset"] == dataset and entry["period"] == selected["period"]
            and (dataset != "stores" or entry["area_code"] in (None, selected["area_code"])) for entry in source["files"])
        collection[dataset] = collected
        if collected:
            actual[dataset] = reader(selected, profile)
            results[dataset] = actual[dataset]
        else:
            results[dataset] = _uncollected(dataset, selected)
    # A manifest entry whose file is missing/corrupt fails in its reader; it is
    # never reclassified as an uncollected period by this adapter.
    validate_reader_results(actual, selected)
    return results, collection


def build_changes_analysis(selection: dict, profile: dict, comparison: str) -> dict:
    if comparison not in ("qoq", "yoy"):
        raise ChangesInputError("비교 기준은 전분기 또는 전년 동분기로 선택해 주세요.")
    source, _area = _base_context(selection, profile)
    previous_period = period_shift(selection["period"], -1 if comparison == "qoq" else -4)
    previous_selection = {**deepcopy(selection), "period": previous_period, "period_label": _period_label(previous_period)}
    current_results, current_collection = _read_period(source, selection, profile)
    previous_results, previous_collection = _read_period(source, previous_selection, profile)
    metrics = []
    for key, label, unit, dataset, count_key, field, industry_applied in _DEFINITIONS:
        current_result, previous_result = current_results[dataset], previous_results[dataset]
        current = _observation(current_result, dataset, count_key, unit)
        previous = _observation(previous_result, dataset, count_key, unit)
        available = current["status"] == previous["status"] == "available"
        delta = current["value"] - previous["value"] if available else None
        percent, percent_status = None, "unavailable"
        warnings = []
        if available:
            if previous["value"] == 0:
                percent_status = "undefined_zero_previous"
                warnings.append("이전 기간 값이 0이므로 변화율을 계산할 수 없습니다. 변화량은 그대로 제공합니다.")
            else:
                percent_status = "available"
                percent = float((Decimal(delta) * 100 / Decimal(previous["value"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        else:
            if previous["status"] == "not_collected":
                warnings.append(f"정확한 비교 기간인 {_period_label(previous_period)} 자료를 확보하지 않았습니다. 다른 기간으로 대체하지 않습니다.")
            else:
                warnings.append("현재 또는 정확한 비교 기간의 값이 없어 변화를 계산하지 않습니다. 결측을 0으로 바꾸지 않습니다.")
        if dataset == "stores" and any(result["composition"]["status"] not in ("consistent", "no_data") for result in (current_result, previous_result)):
            warnings.append("점포 구성 합계에 확인이 필요한 부분이 있습니다. 이 행은 해당 개별 원천 항목의 값만 비교합니다.")
        metrics.append({"key": key, "label": label, "unit": unit, "industry_applied": industry_applied,
            "current": current, "previous": previous, "delta": delta, "delta_text": str(delta) if delta is not None else None,
            "percent": percent, "percent_status": percent_status, "status": "available" if available else "unavailable",
            "source": {"title": current_result["source"]["title"], "url": SOURCE_URLS[dataset], "field": field},
            "evidence": {"current": deepcopy(current_result["evidence"]), "previous": deepcopy(previous_result["evidence"])},
            "warnings": warnings})
    count = sum(row["status"] == "available" for row in metrics)
    comparison_label = "전분기" if comparison == "qoq" else "전년 동분기"
    return {"status": "complete" if count == len(metrics) else "partial" if count else "no_comparison",
        "selection": _selection(selection, profile), "comparison": comparison, "comparison_label": comparison_label,
        "current_period": {"code": selection["period"], "label": selection["period_label"]},
        "previous_period": {"code": previous_period, "label": _period_label(previous_period)},
        "comparison_direction": "current_minus_previous", "metrics": metrics,
        "data_versions": {"current": {key: value["data_version"] for key, value in current_results.items()},
                          "previous": {key: value["data_version"] for key, value in previous_results.items()}},
        "period_collection": {"current": current_collection, "previous": previous_collection},
        "summary": [f"같은 상권·업종의 {comparison_label} 대비 지표 {len(metrics)}개 중 {count}개를 비교했습니다. 변화량은 현재−이전입니다."],
        "warnings": ["전분기는 정확히 한 분기 전, 전년 동분기는 정확히 네 분기 전이며 보유한 다른 기간으로 대체하지 않습니다.",
            "변화율의 분모는 이전 기간 값입니다. 단순 수치 변화로 원인이나 장사 성공 여부를 판단하지 않습니다.",
            "같은 공식 서비스·필드·단위의 원천값을 비교합니다. 지표 산출 방식과 실제 경계가 두 기간에 동일한지는 별도 확인이 필요합니다.",
            "2023년 공개 경계가 각 통계 분기의 실제 경계와 같은지는 확인되지 않았습니다.",
            "추정매출은 상권·업종의 분기 추정치이며 개별 가게의 실제 매출이 아닙니다.",
            store_coverage_note(source, selection["period"]),
            store_coverage_note(source, previous_period),
            "개업−폐업을 전체 점포의 증감으로 간주하거나 개폐업률을 임의로 계산하지 않습니다.",
            "유동인구는 상권 전체 원천 지표이며 업종 고객 수가 아닙니다. 일평균·고유 방문자 수로 변환하지 않았습니다."]}
