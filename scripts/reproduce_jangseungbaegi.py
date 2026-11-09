"""Recalculate the supplied all-day Seoul extracts; stdlib, offline, Python 3.9+.

Default: verify the committed analysis and indicator summaries without changing files.
--write: regenerate those two JSON outputs from source_rows.json.
The all-day summary is archived beside its source, so this script never writes
the shared evening-evidence file at data/scenario/snapshot_2026Q2.json.
"""
import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/scenario/jangseungbaegi_3110826"
PERIODS = ("20243", "20244", "20251", "20252", "20253", "20254", "20261", "20262")
AREA_CODE = "3110826"
AREA_NAME = "장승배기역 4번"
FIELDS = {"sales": "THSMON_SELNG_AMT", "population": "TOT_FLPOP_CO", "stores": "SIMILR_INDUTY_STOR_CO"}


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def numeric(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("Missing or invalid numeric source value: " + label)
    if int(value) != value:
        raise ValueError("Expected an integer source value: " + label)
    return int(value)


def change(current, previous):
    return None if previous == 0 else (current - previous) / previous * 100


def quarter(period):
    return period[:4] + "Q" + period[4]


def calculate(source):
    buckets = {kind: {period: {} for period in PERIODS} for kind in FIELDS}
    industry_names = {}
    row_count = 0
    for page in source["source_files"]:
        kind = page["dataset"]
        if kind not in buckets:
            raise ValueError("Unknown dataset: " + kind)
        for row in page["rows"]:
            period = str(row["STDR_YYQU_CD"])
            if period not in PERIODS or page["period"] != period:
                raise ValueError("Unexpected or mismatched quarter")
            if str(row["TRDAR_CD"]) != AREA_CODE or row["TRDAR_CD_NM"] != AREA_NAME:
                raise ValueError("Area identity mismatch")
            industry = row.get("SVC_INDUTY_CD") if kind != "population" else "area_total"
            if not industry:
                raise ValueError("Missing industry code")
            if industry in buckets[kind][period]:
                raise ValueError("Duplicate area/industry/quarter record")
            value = numeric(row.get(FIELDS[kind]), kind + "/" + period)
            if kind == "stores":
                general = numeric(row.get("STOR_CO"), "general stores")
                franchise = numeric(row.get("FRC_STOR_CO"), "franchise stores")
                if general + franchise != value:
                    raise ValueError("Store total does not reconcile")
            if kind == "sales":
                name = row["SVC_INDUTY_CD_NM"]
                if industry in industry_names and industry_names[industry] != name:
                    raise ValueError("Industry name mismatch")
                industry_names[industry] = name
            buckets[kind][period][industry] = value
            row_count += 1
    for kind, series in buckets.items():
        for period, rows in series.items():
            if not rows or (kind == "population" and len(rows) != 1):
                raise ValueError("Incomplete quarter: " + kind + "/" + period)

    sales = buckets["sales"]
    common = sorted(set.intersection(*(set(sales[p]) for p in PERIODS)))
    if not common:
        raise ValueError("No common sales industries")
    series = []
    metrics = ("sales_observed_total_krw", "sales_common_industries_krw", "floating_population_source_value", "stores_observed_total")
    for p in PERIODS:
        series.append({
            "period": p, "quarter": quarter(p),
            "sales_observed_total_krw": sum(sales[p].values()),
            "sales_observed_industry_count": len(sales[p]),
            "sales_common_industries_krw": sum(sales[p][i] for i in common),
            "sales_common_industry_count": len(common),
            "floating_population_source_value": buckets["population"][p]["area_total"],
            "stores_observed_total": sum(buckets["stores"][p].values()),
            "stores_observed_industry_count": len(buckets["stores"][p]),
        })
    for index, item in enumerate(series):
        item["year_over_year_percent"] = {
            metric: change(item[metric], series[index - 4][metric]) if index >= 4 else None
            for metric in metrics
        }
    previous, current = series[3], series[7]
    names = {
        metrics[0]: "관측 업종 합산 추정매출 (하루 전체 시간대)",
        metrics[1]: "8개 분기 공통 업종 추정매출 (하루 전체 시간대)",
        metrics[2]: "유동인구 지표 (원천값)",
        metrics[3]: "관측 업종 합산 점포 수",
    }
    comparison = [{"metric": m, "label": names[m], "unit": "원" if "sales" in m else "명" if "population" in m else "개",
                   "previous": previous[m], "current": current[m], "absolute_change": current[m] - previous[m],
                   "change_percent": change(current[m], previous[m])} for m in metrics]
    coverage_changes = {}
    for kind in ("sales", "stores"):
        before, after = buckets[kind]["20252"], buckets[kind]["20262"]
        coverage_changes[kind] = {
            "previous_industry_count": len(before), "current_industry_count": len(after),
            "not_observed_in_current": [{"industry_code": i, "previous_value": before[i], "current_value": None} for i in sorted(set(before) - set(after))],
            "newly_observed_in_current": [{"industry_code": i, "previous_value": None, "current_value": after[i]} for i in sorted(set(after) - set(before))],
            "missing_policy": "관측되지 않은 업종은 0으로 대체하지 않음",
        }
    caveats = [
        "전체는 보유 서울시 자료에 관측된 업종 합계이며, 지역 내 모든 사업체의 실제 총매출을 뜻하지 않습니다.",
        "매출은 하루 전체 시간대의 분기 추정매출이며 상권·업종 단위 통계입니다. 개별 매장 실적과 구분합니다.",
        "유동인구는 TOT_FLPOP_CO 원천값입니다. 고유 방문자 수나 일평균으로 환산하지 않았으며 시간 집계 방식은 이 발췌에서 별도로 검증하지 않았습니다.",
        "매출과 점포 자료의 업종 범위는 다릅니다. 매출을 전체 점포 수로 나눠 점포당 매출을 계산하지 않습니다.",
        "상권 코드·명칭은 일치하지만 기간별 지도 경계의 동일성은 검증하지 않았습니다.",
        "2026년 2분기까지의 관측 결과이며, 현재 실시간 상황·하락 원인·서울 전체 하락률 1위·모든 업종의 동반 하락을 입증하지 않습니다.",
    ]
    analysis = {
        "schema_version": "c4-area-decline-v1", "prepared_on_kst": "2026-11-09",
        "area": source["area"], "industry_filter": None, "sales_time_scope": "all_day",
        "comparison": {"previous_quarter": "2025Q2", "current_quarter": "2026Q2", "formula": "(current - previous) / previous * 100", "metrics": comparison},
        "common_sales_industries": [{"code": i, "name": industry_names[i]} for i in common],
        "common_industry_basis": [quarter(p) for p in PERIODS],
        "quarterly_series": series, "coverage_changes": coverage_changes,
        "selection": {"kind": "evidence_based_case_not_citywide_rank", "statement": "서울시 상권분석자료에서 매출·유동인구·점포 수가 함께 감소한 상권 사례로 장승배기역 4번을 선정",
                      "sales_yoy_negative_for_four_periods": all(x["year_over_year_percent"][metrics[0]] < 0 for x in series[4:]),
                      "fixed_industry_sales_yoy_negative_for_four_periods": all(x["year_over_year_percent"][metrics[1]] < 0 for x in series[4:])},
        "source_rows_file": "source_rows.json", "source_file_count": len(source["source_files"]), "source_row_count": row_count,
        "limitations": caveats,
    }
    snapshots = []
    ids = ("sales_all_day_observed", "sales_all_day_common", "population", "stores")
    for key, item in zip(ids, comparison):
        source_kind = "sales" if key.startswith("sales") else key
        url = source["source_urls"][source_kind]
        note = "상권코드 3110826. 전년 값 {previous:,}{unit}, 당기 값 {current:,}{unit}. ".format(**item)
        if key.startswith("sales"):
            note += "하루 전체 시간대의 분기 추정매출. "
            note += ("{}개 분기 공통 {}개 업종.".format(len(PERIODS), len(common)) if key.endswith("common")
                     else "각 분기에 관측된 업종 합계({}개→{}개); 관측 누락을 0으로 대체하지 않음.".format(len(sales["20252"]), len(sales["20262"])))
        elif key == "population":
            note += "TOT_FLPOP_CO 원천값 비교; 고유 방문자 수 또는 일평균이 아님."
        else:
            note += "일반+프랜차이즈 점포 합계. 매출 자료와 업종 범위가 다름."
        snapshots.append({
            "snapshot_id": "snap_3110826_" + key + "_yoy_2026Q2",
            "area_name": AREA_NAME, "metric_name": item["label"] + " 전년 동기 대비 변화율",
            "value": item["change_percent"], "unit": "%", "basis_quarter": "2026Q2",
            "is_estimate": key != "stores", "source": "서울시 상권분석서비스 · " + url,
            "compared_with_quarter": "2025Q2", "note": note,
        })
    return analysis, snapshots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate analysis and snapshot JSON")
    args = parser.parse_args()
    analysis, snapshots = calculate(load_json(DATA / "source_rows.json"))
    snapshot_path = DATA / "all_day_snapshot_2026Q2.json"
    if args.write and snapshot_path.exists():
        existing = load_json(snapshot_path)
        owned_ids = {row["snapshot_id"] for row in snapshots}
        if not isinstance(existing, list) or any(
            not isinstance(row, dict) or row.get("snapshot_id") not in owned_ids for row in existing
        ):
            raise SystemExit("REFUSING WRITE: existing snapshot file contains other records or an unknown format. No outputs changed; merge intentionally instead.")
    outputs = ((DATA / "analysis.json", analysis), (snapshot_path, snapshots))
    for path, value in outputs:
        if args.write:
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        elif load_json(path) != value:
            raise SystemExit("FAIL: stored output differs from source calculation: " + path.name)
    print("PASS: {} source rows; {} quarters; analysis and {} indicator summaries verified.".format(
        analysis["source_row_count"], len(analysis["quarterly_series"]), len(snapshots))
        if not args.write else "WROTE: analysis.json and all_day_snapshot_2026Q2.json")
    for item in analysis["comparison"]["metrics"]:
        print("{}: {:,} -> {:,}; {:.2f}%".format(item["metric"], item["previous"], item["current"], item["change_percent"]))


if __name__ == "__main__":
    main()
