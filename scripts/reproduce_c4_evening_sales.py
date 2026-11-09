"""Reproduce the C4 evening comparison and C1 snapshot offline (Python 3.9+).

Default verifies stored outputs. --write regenerates only this analysis and
its owned snapshot, after checking both destinations for unrelated records.
"""
import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/scenario/evening_sales_2026Q2"
PERIODS = ("20252", "20262")
TIME_FIELDS = ("TMZON_00_06_SELNG_AMT", "TMZON_06_11_SELNG_AMT", "TMZON_11_14_SELNG_AMT", "TMZON_14_17_SELNG_AMT", "TMZON_17_21_SELNG_AMT", "TMZON_21_24_SELNG_AMT")
SCOPES = {"17_21": (TIME_FIELDS[4],), "21_24": (TIME_FIELDS[5],), "17_24": TIME_FIELDS[4:]}
SNAPSHOT_FIELDS = {"snapshot_id", "area_name", "metric_name", "value", "unit", "basis_quarter", "is_estimate", "source", "compared_with_quarter", "note"}


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def numeric(value, label):
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("Missing or invalid numeric source value: " + label)
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid numeric source value: " + label) from None
    if not result.is_finite() or result < 0 or result != result.to_integral_value():
        raise ValueError("Expected nonnegative integer numeric source value: " + label)
    return int(result)


def change(current, previous):
    return None if previous == 0 else float((Decimal(current) - Decimal(previous)) / Decimal(previous) * 100)


def comparison(previous, current):
    return {"previous": previous, "current": current, "absolute_change": current - previous,
            "change_percent": change(current, previous)}


def validate_selection(selection):
    peers = selection["peer_metadata"]
    by_code = {r["TRDAR_CD"]: r for r in peers}
    if len(by_code) != len(peers):
        raise ValueError("Duplicate peer area metadata")
    anchor = by_code[selection["anchor_code"]]
    ax, ay = numeric(anchor["XCNTS_VALUE"], "anchor x"), numeric(anchor["YDNTS_VALUE"], "anchor y")
    for row in peers:
        if (row["SIGNGU_CD"], row["TRDAR_SE_CD"]) != (anchor["SIGNGU_CD"], anchor["TRDAR_SE_CD"]):
            raise ValueError("Peer district or type mismatch")
    def distance(row):
        return ((numeric(row["XCNTS_VALUE"], "peer x") - ax) ** 2
                + (numeric(row["YDNTS_VALUE"], "peer y") - ay) ** 2, row["TRDAR_CD"])
    expected = [anchor["TRDAR_CD"]] + [r["TRDAR_CD"] for r in sorted(
        (r for r in peers if r["TRDAR_CD"] != anchor["TRDAR_CD"]), key=distance)[:4]]
    if selection["candidate_codes"] != expected or selection["candidate_count"] != 5:
        raise ValueError("Candidate selection does not match fixed nearest-peer rule")
    if selection["eligible_peer_count"] != len(peers) - 1:
        raise ValueError("Peer metadata coverage mismatch")
    if [c["area_code"] for c in selection["candidates"]] != expected:
        raise ValueError("Candidate description order mismatch")
    for item in selection["candidates"]:
        row = by_code[item["area_code"]]
        if item["area_name"] != row["TRDAR_CD_NM"]:
            raise ValueError("Candidate name mismatch")
    return [by_code[code] for code in expected]


def calculate(source):
    if source["schema_version"] != "c4-evening-source-v1" or tuple(source["periods"]) != PERIODS:
        raise ValueError("Unexpected source schema or periods")
    candidates = validate_selection(source["selection"])
    names = {r["TRDAR_CD"]: r["TRDAR_CD_NM"] for r in candidates}
    buckets = {code: {p: {} for p in PERIODS} for code in names}
    industries, pagination, row_count = {}, {p: [] for p in PERIODS}, 0
    for page in source["source_files"]:
        period = page["period"]
        if period not in PERIODS or page["service"] != "VwsmTrdarSelngQq" or page["sample_only"] is not False:
            raise ValueError("Invalid source page period or provenance")
        pagination[period].append(page)
        if page["selected_row_count"] != len(page["rows"]):
            raise ValueError("Selected row count mismatch")
        for row in page["rows"]:
            code, industry = str(row["TRDAR_CD"]), row["SVC_INDUTY_CD"]
            if code not in buckets or row["TRDAR_CD_NM"] != names[code]:
                raise ValueError("Area identity mismatch")
            if str(row["STDR_YYQU_CD"]) != period:
                raise ValueError("Quarter mismatch")
            if row["TRDAR_SE_CD"] != "A" or not industry:
                raise ValueError("Invalid area type or industry")
            if industry in buckets[code][period]:
                raise ValueError("Duplicate area/industry/quarter record")
            label = row["SVC_INDUTY_CD_NM"]
            if industry in industries and industries[industry] != label:
                raise ValueError("Industry name mismatch")
            industries[industry] = label
            amounts = {field: numeric(row.get(field), field) for field in (*TIME_FIELDS, "THSMON_SELNG_AMT")}
            if sum(amounts[f] for f in TIME_FIELDS) != amounts["THSMON_SELNG_AMT"]:
                raise ValueError("Time-band sum does not reconcile to all-day sales")
            buckets[code][period][industry] = amounts
            row_count += 1
    for period, pages in pagination.items():
        totals = {p["source_total_row_count"] for p in pages}
        if len(totals) != 1:
            raise ValueError("Source pagination total mismatch")
        next_start = 1
        for page in sorted(pages, key=lambda x: x["start"]):
            if page["start"] != next_start or page["source_page_row_count"] != min(page["requested_count"], page["source_total_row_count"] - next_start + 1):
                raise ValueError("Source pagination gap, overlap or truncated page")
            next_start += page["source_page_row_count"]
        if next_start - 1 != totals.pop():
            raise ValueError("Incomplete source pagination")

    result = []
    for meta in candidates:
        code = meta["TRDAR_CD"]
        previous, current = (buckets[code][p] for p in PERIODS)
        if not previous or not current:
            raise ValueError("Incomplete candidate quarter: " + code)
        common = sorted(set(previous) & set(current))
        if not common:
            raise ValueError("No common industries: " + code)
        groups = {}
        for basis in ("observed", "common"):
            groups[basis] = {}
            for scope, fields in SCOPES.items():
                values = [sum(rows[i][f] for i in (common if basis == "common" else rows) for f in fields)
                          for rows in (previous, current)]
                groups[basis][scope] = comparison(*values)
        result.append({"area_code": code, "area_name": meta["TRDAR_CD_NM"],
                       "district": meta["SIGNGU_CD_NM"], "area_type": meta["TRDAR_SE_CD_NM"],
                       "observed_industry_counts": {p: len(buckets[code][p]) for p in PERIODS},
                       "common_industry_count": len(common),
                       "common_industries": [{"code": i, "name": industries[i]} for i in common],
                       "not_observed_in_current": [{"code": i, "name": industries[i]} for i in sorted(set(previous) - set(current))],
                       "newly_observed_in_current": [{"code": i, "name": industries[i]} for i in sorted(set(current) - set(previous))],
                       **groups})
    eligible = [r for r in result if all(r[b]["17_24"]["change_percent"] is not None and r[b]["17_24"]["change_percent"] < 0 for b in ("observed", "common"))]
    chosen = min(eligible, key=lambda r: (r["common"]["17_24"]["change_percent"], r["area_code"])) if eligible else None
    analysis = {"schema_version": "c4-evening-comparison-v1", "prepared_on_kst": "2026-11-09",
                "previous_quarter": "2025Q2", "current_quarter": "2026Q2", "unit": "원",
                "time_definition": {"primary": "17:00-24:00", "primary_fields": list(SCOPES["17_24"]),
                                    "sensitivity": ["17:00-21:00", "21:00-24:00"],
                                    "note": "팀 요청에 시간 경계가 없어 이 분석에서 명시적으로 정의. 하루 전체 매출과 구분."},
                "formula": "(current - previous) / previous * 100; previous=0 -> null",
                "candidates": result,
                "selection": {"candidate_count": 5, "anchor_from_existing_pr17": source["selection"]["anchor_code"],
                              "rule": "Among these five candidates, require negative observed and common-industry 17-24 YoY; select the lowest common-industry YoY (tie: area code).",
                              "selected_area_code": chosen["area_code"] if chosen else None,
                              "selected_area_name": chosen["area_name"] if chosen else None,
                              "eligible_area_codes": [r["area_code"] for r in eligible],
                              "claim_scope": "이 후보 5곳 안에서의 선택. 서울 전체 순위·통계적 유의성 검정·무작위 대표표본이 아님."},
                "source_row_count": row_count, "source_page_count": len(source["source_files"]),
                "missing_policy": "미관측 업종은 0으로 채우지 않음. 공통은 각 상권의 비교 두 분기 교집합이며 기존 8개 분기 공통과 다름.",
                "source_url": source["source_url"]}
    snapshots = []
    if chosen:
        metric = chosen["common"]["17_24"]
        snapshots.append({"snapshot_id": "snap_" + chosen["area_code"] + "_evening_17_24_common_yoy_2026Q2",
                          "area_name": chosen["area_name"],
                          "metric_name": "저녁 시간대(17~24시) 추정매출 전년 동기 대비 변화율 · 두 분기 공통 업종",
                          "value": metric["change_percent"], "unit": "%", "basis_quarter": "2026Q2",
                          "is_estimate": True, "source": "서울시 상권분석서비스 · " + source["source_url"],
                          "compared_with_quarter": "2025Q2",
                          "note": ("상권코드 {code}. 17~21시와 21~24시 추정매출 합산. 비교 두 분기 공통 {count}개 업종 기준: "
                                   "2025Q2 {before:,}원 → 2026Q2 {after:,}원. 후보 5곳 비교로 선정; 서울 전체 하락률 1위가 아님. "
                                   "관측 업종 합계는 {observed:+.2f}%. 하루 전체 매출·개별 가게 실적과 구분.").format(
                                       code=chosen["area_code"], count=chosen["common_industry_count"],
                                       before=metric["previous"], after=metric["current"],
                                       observed=chosen["observed"]["17_24"]["change_percent"])})
    return analysis, snapshots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    analysis, snapshots = calculate(load_json(DATA / "source_rows.json"))
    snapshot_path, analysis_path = ROOT / "data/scenario/snapshot_2026Q2.json", DATA / "analysis.json"
    if args.write:
        if snapshot_path.exists():
            existing = load_json(snapshot_path)
            owned_ids = {r["snapshot_id"] for r in snapshots}
            if not isinstance(existing, list) or any(not isinstance(r, dict) or r.get("snapshot_id") not in owned_ids for r in existing):
                raise SystemExit("REFUSING WRITE: snapshot contains unrelated records. No outputs changed.")
        if analysis_path.exists() and load_json(analysis_path).get("schema_version") != analysis["schema_version"]:
            raise SystemExit("REFUSING WRITE: analysis has an unrelated schema. No outputs changed.")
    for path, value in ((analysis_path, analysis), (snapshot_path, snapshots)):
        if args.write:
            path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
        elif load_json(path) != value:
            raise SystemExit("FAIL: stored output differs from calculation: " + path.name)
    print("PASS: {} candidates; {} extracted rows; {} source pages; {} snapshot(s).".format(len(analysis["candidates"]), analysis["source_row_count"], analysis["source_page_count"], len(snapshots)))
    def display_percent(value):
        return "null (previous=0)" if value is None else "{:+.2f}%".format(value)
    for row in analysis["candidates"]:
        a, b = row["observed"]["17_24"], row["common"]["17_24"]
        print("{} {}: observed {}; common {}".format(row["area_code"], row["area_name"], display_percent(a["change_percent"]), display_percent(b["change_percent"])))
    print("Selected: {} {}".format(analysis["selection"]["selected_area_code"], analysis["selection"]["selected_area_name"]))


if __name__ == "__main__":
    main()
