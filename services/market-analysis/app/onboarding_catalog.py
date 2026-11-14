"""Form choices extracted from checked-in Seoul source files, without API calls.

The industry choices combine observed sales and store source categories, not a claim that the
analysis service supports all categories. District codes retain SIGNGU_CD from
the source. Neither catalogue is restricted to the existing coffee-only release.

Rebuild the adjacent snapshot with ``python -m app.onboarding_catalog`` from
development. This reads raw files and rewrites only onboarding_industries.json;
normal imports read that small snapshot, never credentials or raw statistics.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re


_SNAPSHOT = Path(__file__).with_name("onboarding_industries.json")
_DEVELOPMENT = Path(__file__).resolve().parents[1]


def _canonical_hash(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _checked_pairs(rows, code_field, name_field, pattern):
    by_code, by_name = {}, {}
    for row in rows:
        code, name = row.get(code_field), row.get(name_field)
        if (not isinstance(code, str) or not re.fullmatch(pattern, code)
                or not isinstance(name, str) or not name.strip() or name != name.strip()
                or "\ufffd" in name):
            raise ValueError("Invalid source catalogue code or name")
        if code in by_code and by_code[code] != name:
            raise ValueError("One code has conflicting source names")
        if name in by_name and by_name[name] != code:
            raise ValueError("One source name has conflicting codes")
        by_code[code], by_name[name] = name, code
    return [{"code": code, "name": name} for code, name in sorted(by_code.items())]


def build_catalog(raw_root: Path | None = None) -> dict:
    """Validate pagination, payload hashes and bijective code/name mappings.

    This verifies category extraction only, not the underlying numeric measures.
    No raw file, current analysis release, or configuration is changed.
    """
    raw_root = Path(raw_root) if raw_root is not None else _DEVELOPMENT / "data" / "raw" / "official"
    all_rows = {"sales": {}, "stores": {}, "areas": {}}
    pages, period_rows, files = defaultdict(list), defaultdict(dict), []
    store_areas_by_period = defaultdict(set)
    for kind, pattern, service in (("sales", "sales_*_all_*.json", "VwsmTrdarSelngQq"),
                                   ("stores", "stores_*.json", "VwsmTrdarStorQq"),
                                   ("areas", "areas_none_all_*.json", "TbgisTrdarRelm")):
        paths = sorted(raw_root.glob(pattern))
        if not paths:
            raise ValueError("Missing local source catalogue pages")
        for path in paths:
            raw_bytes = path.read_bytes()
            document = json.loads(raw_bytes.decode("utf-8-sig"))
            query = document["query"]
            area_code = query["area_code"]
            payload_hash = _canonical_hash(document["payload"])
            payload = document["payload"][service]
            if (document["service"] != service or query["dataset"] != kind
                    or (kind != "stores" and area_code is not None)
                    or (kind == "stores" and area_code is not None and (not isinstance(area_code, str)
                                             or not re.fullmatch(r"\d{7}", area_code)))
                    or document["sample_only"] is not False
                    or document["payload_sha256"] != payload_hash
                    or payload["RESULT"]["CODE"] != "INFO-000"):
                raise ValueError("Source provenance or successful-response check failed")
            rows, total = payload["row"], payload["list_total_count"]
            if (not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
                    or type(total) is not int or total <= 0 or type(query["start"]) is not int
                    or query["start"] < 1 or type(query["count"]) is not int or query["count"] <= 0
                    or len(rows) != min(query["count"], total - query["start"] + 1) or not rows):
                raise ValueError("Malformed source page")
            period = query["period"]
            if kind in ("sales", "stores") and (not isinstance(period, str) or not re.fullmatch(r"\d{4}[1-4]", period)
                                                  or any(row.get("STDR_YYQU_CD") != period for row in rows)):
                raise ValueError("Source quarter does not match its query")
            if kind == "stores" and any(not isinstance(row.get("TRDAR_CD"), str)
                    or not re.fullmatch(r"\d{7}", row["TRDAR_CD"])
                    or (area_code is not None and row["TRDAR_CD"] != area_code) for row in rows):
                raise ValueError("Source area does not match its query")
            if kind == "areas" and period is not None:
                raise ValueError("Area catalogue must not carry a quarter")
            fields = ("SIGNGU_CD", "SIGNGU_CD_NM") if kind == "areas" else ("SVC_INDUTY_CD", "SVC_INDUTY_CD_NM")
            for row in rows:
                # Category extraction needs a unique identity pair, not a copy
                # of every numerical row across all collected quarters.
                pair = tuple(row.get(field) for field in fields)
                if any(not isinstance(value, str) for value in pair):
                    raise ValueError("Invalid source catalogue code or name")
                compact = {field: row.get(field) for field in fields}
                all_rows[kind][pair] = compact
                if kind in ("sales", "stores"):
                    period_rows[(kind, period)][pair] = compact
                if kind == "stores":
                    store_areas_by_period[period].add(row["TRDAR_CD"])
            pages[(kind, period, area_code)].append({"start": query["start"], "count": query["count"],
                                                     "rows": len(rows), "total": total})
            # Use a portable workspace path when possible, an exact absolute
            # path for an explicitly supplied source directory elsewhere.
            try:
                source_path = path.resolve().relative_to(_DEVELOPMENT.parent).as_posix()
            except ValueError:
                source_path = path.resolve().as_posix()
            files.append({"path": source_path, "file_sha256": sha256(raw_bytes).hexdigest(),
                          "payload_sha256": payload_hash, "fetched_at": document["fetched_at"],
                          "service": service, "source_url": document["source_url"],
                          "period": period, "area_code": area_code,
                          "start": query["start"], "row_count": len(rows)})

    pagination = []
    for (kind, period, area_code), group in sorted(pages.items(), key=lambda pair: tuple(value or "" for value in pair[0])):
        next_start, totals = 1, {page["total"] for page in group}
        if len(totals) != 1:
            raise ValueError("Source total changed between pages")
        for page in sorted(group, key=lambda item: item["start"]):
            if page["start"] != next_start:
                raise ValueError("Missing or overlapping source pages")
            next_start += page["rows"]
        if next_start - 1 != next(iter(totals)):
            raise ValueError("Incomplete source page coverage")
        pagination.append({"dataset": kind, "period": period, "area_code": area_code, "pages": len(group),
                           "row_count": next_start - 1, "complete": True})
    dataset_industries = {
        kind: _checked_pairs(all_rows[kind].values(), "SVC_INDUTY_CD", "SVC_INDUTY_CD_NM", r"CS\d{6}")
        for kind in ("sales", "stores")
    }
    same_industries = all(_checked_pairs(rows.values(), "SVC_INDUTY_CD", "SVC_INDUTY_CD_NM", r"CS\d{6}") == dataset_industries[kind]
                          for (kind, _period), rows in period_rows.items())
    store_area_codes = sorted(set.union(*store_areas_by_period.values()))
    dataset_periods = {dataset: sorted({period for kind, period in period_rows if kind == dataset}) for dataset in ("sales", "stores")}
    citywide_periods = sorted({period for kind, period, scope in pages if kind == "stores" and scope is None})
    if citywide_periods == dataset_periods["stores"]:
        store_scope = f"보유 분기의 서울 전체 상권 조회 점포 원본에서 실제 관측된 {len(store_area_codes)}개 상권의 업종"
    elif citywide_periods:
        store_scope = f"분기별 서울 전체 조회와 일부 상권 조회를 합친 {len(store_area_codes)}개 관측 상권의 업종"
    else:
        store_scope = f"로컬에 보관한 {len(store_area_codes)}개 관측 상권 점포 원본의 업종"
    # The union checks shared codes and names across both datasets; the store
    # catalogue also includes categories without estimated sales observations.
    industries = _checked_pairs([*all_rows["sales"].values(), *all_rows["stores"].values()], "SVC_INDUTY_CD", "SVC_INDUTY_CD_NM", r"CS\d{6}")
    districts = _checked_pairs(all_rows["areas"].values(), "SIGNGU_CD", "SIGNGU_CD_NM", r"11\d{3}")
    if len(districts) != 25:
        raise ValueError("Expected all 25 Seoul district categories")
    return {
        "schema_version": "onboarding-catalog-v1", "districts": districts, "industries": industries,
        "catalog_source": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "provider": "서울특별시 열린데이터광장",
            "basis": "로컬에 보관한 상권영역·추정매출·점포 원본의 코드·명칭 고유값",
            "district_fields": ["SIGNGU_CD", "SIGNGU_CD_NM"],
            "industry_fields": ["SVC_INDUTY_CD", "SVC_INDUTY_CD_NM"],
            "district_count": len(districts), "industry_count": len(industries),
            "source_fetched_at_min": min(item["fetched_at"] for item in files),
            "source_fetched_at_max": max(item["fetched_at"] for item in files),
            "source_periods": sorted({period for periods in dataset_periods.values() for period in periods}),
            "dataset_periods": dataset_periods,
            "dataset_industry_counts": {kind: len(items) for kind, items in dataset_industries.items()},
            "stores_area_count": len(store_area_codes), "stores_area_codes": store_area_codes,
            "stores_area_counts_by_period": {period: len(codes) for period, codes in sorted(store_areas_by_period.items())},
            "stores_citywide_periods": citywide_periods,
            "source_scope": {
                "sales": "서울 전체 상권으로 조회한 보유 추정매출 원본의 업종",
                "stores": store_scope,
                "coverage": "보유 원본에서 관측한 업종의 합집합이며 서울의 모든 사업 업종이나 분석 자료 가용성을 보장하지 않습니다.",
            },
            "code_name_conflicts": [], "name_code_conflicts": [],
            "same_industries_across_quarters": same_industries, "pagination": pagination,
            "analysis_availability_verified": False,
            "scope_note": "보유 공식 원본의 업종 선택 목록이며, 모든 사업 업종·지역의 분석 자료 제공을 보장하지 않습니다.",
            "files": files,
        },
    }


def _load_catalog():
    payload = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "onboarding-catalog-v1":
        raise ValueError("Unknown onboarding catalogue version")
    districts = _checked_pairs(payload["districts"], "code", "name", r"11\d{3}")
    industries = _checked_pairs(payload["industries"], "code", "name", r"CS\d{6}")
    if (len(districts) != 25 or len(districts) != len(payload["districts"])
            or not industries or len(industries) != len(payload["industries"])
            or payload["catalog_source"]["district_count"] != len(districts)
            or payload["catalog_source"]["industry_count"] != len(industries)):
        raise ValueError("Onboarding catalogue counts or duplicate entries are invalid")
    return payload


if __name__ == "__main__":
    snapshot = build_catalog()
    _SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(snapshot['districts'])} districts and {len(snapshot['industries'])} industries.")


_CATALOG = _load_catalog()
SEOUL_DISTRICTS = deepcopy(_CATALOG["districts"])
INDUSTRIES = deepcopy(_CATALOG["industries"])
BUSINESS_STATUSES = [
    {"code": "operating", "label": "운영 중"},
    {"code": "planning", "label": "창업 준비 중"},
    {"code": "exploring", "label": "창업 검토 중"},
]
LOCATION_KINDS = [
    {"code": "address", "label": "주소"},
    {"code": "station", "label": "역 주변"},
    {"code": "area", "label": "동네·지역"},
]


def get_options() -> dict:
    """Return independent JSON-ready choices and a compact source summary."""
    from app.onboarding_stations import get_stations, get_station_source
    from app.onboarding_neighborhoods import get_neighborhoods, get_neighborhood_source
    from app.onboarding_station_lines import get_station_lines, get_station_line_codes, get_station_line_source

    source = _CATALOG["catalog_source"]
    return deepcopy({
        "districts": SEOUL_DISTRICTS, "industries": INDUSTRIES,
        "neighborhoods": get_neighborhoods(), "neighborhood_source": get_neighborhood_source(),
        "station_lines": get_station_lines(),
        "station_line_source": get_station_line_source(),
        "stations": [{**{key: value for key, value in station.items() if key in (
            "id", "name", "aliases", "lines", "district_code", "district_name", "road_address",
            "latitude", "longitude", "coordinate_status", "source_data_date")},
            "selectable_line_codes": get_station_line_codes(station["id"])}
            for station in get_stations()],
        "station_source": get_station_source(),
        "business_statuses": BUSINESS_STATUSES, "location_kinds": LOCATION_KINDS,
        "catalog_source": {key: source[key] for key in (
            "provider", "basis", "district_count", "industry_count", "source_periods",
            "source_fetched_at_min", "source_fetched_at_max", "analysis_availability_verified", "scope_note",
            "dataset_industry_counts", "dataset_periods", "stores_area_count", "stores_area_codes", "source_scope",
            "stores_area_counts_by_period", "stores_citywide_periods")},
    })
