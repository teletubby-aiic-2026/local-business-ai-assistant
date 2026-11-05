"""Offline official market boundaries and checked B1 data availability.

Rebuild: ``python -m app.onboarding_analysis_catalog`` from development. This
never changes the legacy analysis release, calls a provider, or loads settings.
Availability means a validated source field exists, not an executed analysis.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from decimal import Decimal
from functools import lru_cache
from hashlib import sha256
import io
import json
import math
from pathlib import Path
import re
import zipfile

from app.data_repository import SOURCE_URLS, canonical_hash
from app.onboarding_catalog import INDUSTRIES, SEOUL_DISTRICTS
from app.onboarding_neighborhoods import get_neighborhood

_ROOT = Path(__file__).resolve().parents[1]
_SNAPSHOT = _ROOT / "data/official/onboarding_analysis_catalog.json"
_BOUNDARY_ZIP = "OA-15560_seq5_boundaries.zip"
_BOUNDARY_HASH = "38bb8fab4e45a1171af4989cd7fa1275f68e5d644aa770f5431ce7ccc38384dd"
_SCHEMA = "onboarding-analysis-catalog-v1"
_METRICS = {
    "sales": ("sales", "THSMON_SELNG_AMT", "추정매출", True),
    "stores": ("stores", "SIMILR_INDUTY_STOR_CO", "점포 수", True),
    "floating_population": ("population", "TOT_FLPOP_CO", "지역 유동인구", False),
}
_SOURCES = {
    "areas": ("areas_none_all_*.json", "TbgisTrdarRelm"),
    "sales": ("sales_*_all_*.json", "VwsmTrdarSelngQq"),
    "stores": ("stores_*.json", "VwsmTrdarStorQq"),
    "population": ("population_*_all_*.json", "VwsmTrdarFlpopQq"),
}
_INDUSTRIES = {row["code"]: row["name"] for row in INDUSTRIES}
_DISTRICTS = {row["code"]: row["name"] for row in SEOUL_DISTRICTS}
SEARCH_RADIUS_M = 1000
MAX_CANDIDATES = 12
_BLOCKED_HISTORICAL_NAMES = {"3110024", "3110379"}


def _number(value):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        if re.fullmatch(r"\d+(?:\.\d+)?", value) is None:
            raise ValueError("Non-numeric official observation")
        value = Decimal(value)
    if isinstance(value, Decimal):
        if not value.is_finite() or value < 0:
            raise ValueError("Official observation must be finite and nonnegative")
        return value
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("Official observation must be finite and nonnegative")
    return value


def _neighborhood_matches(area, neighborhood):
    """Compare known codes, district and names; only punctuation varies."""
    return (neighborhood is not None
            and area["district_code"] == neighborhood["district_code"]
            and area["neighborhood_code"] == neighborhood["code"]
            and area["neighborhood_name"].replace("·", ".") == neighborhood["name"].replace("·", "."))


def _read_sources(raw_root):
    rows = {kind: [] for kind in _SOURCES}
    pages, files = defaultdict(list), []
    store_groups = defaultdict(dict)
    for kind, (pattern, service) in _SOURCES.items():
        paths = sorted(raw_root.glob(pattern))
        if not paths:
            raise ValueError(f"Missing {kind} source files")
        for path in paths:
            data = path.read_bytes()
            doc = json.loads(data.decode("utf-8-sig"))
            query, payload = doc["query"], doc["payload"]
            response = payload[service]
            period, area_code = query["period"], query["area_code"]
            if (doc["service"] != service or query["dataset"] != kind
                    or doc["source_url"] != SOURCE_URLS[kind]
                    or doc["sample_only"] is not False
                    or canonical_hash(payload) != doc["payload_sha256"]
                    or response["RESULT"]["CODE"] != "INFO-000"):
                raise ValueError("Source provenance or payload hash mismatch")
            if ((kind == "areas" and period is not None)
                    or (kind != "areas" and (not isinstance(period, str) or not re.fullmatch(r"20\d{2}[1-4]", period)))
                    or (kind != "stores" and area_code is not None)
                    or (kind == "stores" and area_code is not None
                        and (not isinstance(area_code, str) or not re.fullmatch(r"\d{7}", area_code)))):
                raise ValueError("Source query scope mismatch")
            records, total = response["row"], response["list_total_count"]
            start, count = query["start"], query["count"]
            if (type(total) is not int or total <= 0 or type(start) is not int or start < 1
                    or type(count) is not int or count < 1 or not isinstance(records, list)
                    or len(records) != min(count, total - start + 1)
                    or not records or any(not isinstance(row, dict) for row in records)):
                raise ValueError("Invalid source pagination")
            for row in records:
                if (not isinstance(row.get("TRDAR_CD"), str) or not re.fullmatch(r"\d{7}", row["TRDAR_CD"])
                        or (kind != "areas" and row.get("STDR_YYQU_CD") != period)
                        or (area_code is not None and row["TRDAR_CD"] != area_code)):
                    raise ValueError("Source row identity differs from query")
            if kind == "stores":
                # Preserve exact numeric tokens for overlap checks. Retain only
                # the availability fields and a complete-row fingerprint so a
                # citywide multi-quarter rebuild does not retain every payload.
                exact = json.loads(data.decode("utf-8-sig"), parse_float=Decimal)["payload"][service]["row"]
                group = store_groups[(period, area_code)]
                for row in exact:
                    identity = (row["TRDAR_CD"], row.get("SVC_INDUTY_CD"))
                    if identity in group:
                        raise ValueError("Duplicate store source observation")
                    proof = sha256(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
                    group[identity] = ({key: row.get(key) for key in
                        ("TRDAR_CD", "TRDAR_CD_NM", "STDR_YYQU_CD", "SVC_INDUTY_CD", "SVC_INDUTY_CD_NM", "SIMILR_INDUTY_STOR_CO")}, proof)
            elif kind == "areas":
                rows[kind].extend(records)
            else:
                fields = {"TRDAR_CD", "TRDAR_CD_NM", "STDR_YYQU_CD", "SVC_INDUTY_CD", "SVC_INDUTY_CD_NM",
                          "THSMON_SELNG_AMT" if kind == "sales" else "TOT_FLPOP_CO"}
                rows[kind].extend({key: value for key, value in row.items() if key in fields} for row in records)
            pages[(kind, period, area_code)].append((start, len(records), total))
            files.append({"path": f"data/raw/official/{path.name}", "file_sha256": sha256(data).hexdigest(),
                          "payload_sha256": doc["payload_sha256"], "fetched_at": doc["fetched_at"],
                          "source_url": doc["source_url"], "dataset": kind, "period": period,
                          "area_code": area_code, "start": start, "row_count": len(records)})
    coverage = []
    for (kind, period, area_code), group in pages.items():
        next_start, totals = 1, {page[2] for page in group}
        if len(totals) != 1:
            raise ValueError("Source pagination total changed")
        for start, count, _ in sorted(group):
            if start != next_start:
                raise ValueError("Missing or duplicate source page")
            next_start += count
        if next_start - 1 != next(iter(totals)):
            raise ValueError("Incomplete source pagination")
        coverage.append({"dataset": kind, "period": period, "area_code": area_code,
                         "row_count": next_start - 1, "page_count": len(group), "complete": True})
    citywide_area_keys = defaultdict(set)
    for (period, area_code), group in store_groups.items():
        if area_code is None:
            for identity in group:
                citywide_area_keys[(period, identity[0])].add(identity)
    for (period, area_code), group in store_groups.items():
        citywide = store_groups.get((period, None))
        if area_code is not None and citywide is not None:
            if set(group) != citywide_area_keys[(period, area_code)]:
                raise ValueError("Citywide and preserved area store row sets differ")
            for identity, (_row, proof) in group.items():
                if identity not in citywide or citywide[identity][1] != proof:
                    raise ValueError("Citywide and preserved area store observations differ")
            continue
        rows["stores"].extend(row for row, _proof in group.values())
    return rows, files, coverage


def _load_geometries(path, areas):
    import shapefile
    from pyproj import CRS, Transformer

    if sha256(path.read_bytes()).hexdigest() != _BOUNDARY_HASH:
        raise ValueError("Official boundary ZIP differs from reviewed source")
    transformer = Transformer.from_crs(5181, 4326, always_xy=True)
    result, mismatches = [], []
    with zipfile.ZipFile(path) as archive:
        names = {Path(name).suffix.lower(): name for name in archive.namelist()}
        if CRS.from_wkt(archive.read(names[".prj"]).decode("utf-8-sig")).to_epsg(min_confidence=100) != 5181:
            raise ValueError("Boundary source CRS is not verified EPSG:5181")
        encoding = archive.read(names[".cpg"]).decode().strip()
        encoding = "cp949" if encoding == "949" else encoding
        reader = shapefile.Reader(shp=io.BytesIO(archive.read(names[".shp"])),
                                  shx=io.BytesIO(archive.read(names[".shx"])),
                                  dbf=io.BytesIO(archive.read(names[".dbf"])), encoding=encoding)
        seen = set()
        for record in reader.iterShapeRecords():
            props = record.record.as_dict()
            code = str(props["TRDAR_CD"])
            if code in seen or code not in areas:
                raise ValueError("Unknown or duplicate boundary area code")
            seen.add(code)
            area = areas[code]
            if props["SIGNGU_CD"] != area["SIGNGU_CD"]:
                raise ValueError("Boundary district differs from area source")
            points = []

            def convert(values):
                if len(values) >= 2 and isinstance(values[0], (int, float)):
                    lon, lat = transformer.transform(values[0], values[1])
                    if not (126 <= lon <= 128 and 37 <= lat <= 38.5):
                        raise ValueError("Transformed boundary outside Seoul vicinity")
                    point = [round(lon, 8), round(lat, 8)]
                    points.append(point)
                    return point
                return [convert(value) for value in values]

            geometry = record.shape.__geo_interface__
            if geometry["type"] not in ("Polygon", "MultiPolygon"):
                raise ValueError("Expected polygon boundary")
            geometry = {"type": geometry["type"], "coordinates": convert(geometry["coordinates"])}
            boundary_name = props["TRDAR_CD_N"]
            status = "code_name_match" if boundary_name == area["TRDAR_CD_NM"] else "name_mismatch"
            if status == "name_mismatch":
                mismatches.append({"area_code": code, "boundary_name": boundary_name, "area_name": area["TRDAR_CD_NM"]})
            lon, lat = transformer.transform(float(area["XCNTS_VALUE"]), float(area["YDNTS_VALUE"]))
            result.append({"area_code": code, "name": area["TRDAR_CD_NM"], "type": area["TRDAR_SE_CD_NM"],
                           "district_code": area["SIGNGU_CD"], "district_name": area["SIGNGU_CD_NM"],
                           "neighborhood_code": area["ADSTRD_CD"], "neighborhood_name": area["ADSTRD_CD_NM"],
                           "boundary_name": boundary_name, "boundary_identity_status": status,
                           "longitude": lon, "latitude": lat, "geometry": geometry,
                           "bbox": [min(p[0] for p in points), min(p[1] for p in points),
                                    max(p[0] for p in points), max(p[1] for p in points)]})
        reader.close()
    if seen != set(areas):
        raise ValueError("Boundary and official area code coverage differ")
    return sorted(result, key=lambda area: area["area_code"]), mismatches


def build_catalog(raw_root: Path | None = None) -> dict:
    """Validate preserved raw pages and build a separate reproducible artifact."""
    raw_root = Path(raw_root) if raw_root is not None else _ROOT / "data/raw/official"
    rows, files, coverage = _read_sources(raw_root)
    areas = {}
    for row in rows["areas"]:
        code = row["TRDAR_CD"]
        if (code in areas or _DISTRICTS.get(row["SIGNGU_CD"]) != row["SIGNGU_CD_NM"]
                or not isinstance(row.get("TRDAR_CD_NM"), str) or not row["TRDAR_CD_NM"]
                or not re.fullmatch(r"11\d{6}", row.get("ADSTRD_CD", ""))):
            raise ValueError("Invalid official area identity")
        areas[code] = row
    geometries, mismatches = _load_geometries(raw_root / _BOUNDARY_ZIP, areas)
    geometry_by_code = {area["area_code"]: area for area in geometries}
    historical_names = defaultdict(int)
    observations = {metric: {} for metric in _METRICS}
    counts = {}
    for metric, (kind, field, _label, specific) in _METRICS.items():
        per_period = defaultdict(lambda: {"rows": 0, "areas": set(), "industries": set(), "zeros": 0, "missing_values": 0})
        for row in rows[kind]:
            area_code, period = row["TRDAR_CD"], row["STDR_YYQU_CD"]
            if area_code not in areas:
                raise ValueError("Observation area code/name differs from official area source")
            if row["TRDAR_CD_NM"] != areas[area_code]["TRDAR_CD_NM"]:
                geometry = geometry_by_code.get(area_code, {})
                if (area_code not in _BLOCKED_HISTORICAL_NAMES or geometry.get("boundary_identity_status") != "name_mismatch"
                        or row["TRDAR_CD_NM"] != geometry.get("boundary_name")):
                    raise ValueError("Observation area code/name differs from official area source")
                # These two previously blocked official identities remain
                # unselectable. Keep the historical name and its provenance;
                # do not rename its observations or promote the boundary join.
                historical_names[(kind, period, area_code, row["TRDAR_CD_NM"], areas[area_code]["TRDAR_CD_NM"])] += 1
            industry = row.get("SVC_INDUTY_CD") if specific else "*"
            if specific and _INDUSTRIES.get(industry) != row.get("SVC_INDUTY_CD_NM"):
                raise ValueError("Observation industry code/name mismatch")
            key = "|".join((area_code, industry, period))
            if key in observations[metric]:
                raise ValueError("Duplicate area/industry/period observation")
            value = _number(row.get(field))
            # 0 = missing field, 1 = positive observation, 2 = observed zero.
            observations[metric][key] = 0 if value is None else 2 if value == 0 else 1
            count = per_period[period]
            count["rows"] += 1
            count["areas"].add(area_code)
            if specific:
                count["industries"].add(industry)
            count["zeros"] += value == 0
            count["missing_values"] += value is None
        counts[metric] = {period: {**count, "areas": len(count["areas"]), "industries": len(count["industries"])}
                          for period, count in sorted(per_period.items())}
    periods = sorted({entry["period"] for entry in coverage if entry["period"]}, reverse=True)
    dataset_periods = {kind: sorted({entry["period"] for entry in coverage if entry["dataset"] == kind}, reverse=True)
                       for kind in ("sales", "stores", "population")}
    citywide_periods = {entry["period"] for entry in coverage if entry["dataset"] == "stores" and entry["area_code"] is None}
    overlaps = [{"period": period,
                 "matched_rows": sum(entry["row_count"] for entry in coverage if entry["dataset"] == "stores" and entry["period"] == period and entry["area_code"] is not None),
                 "legacy_area_count": sum(1 for entry in coverage if entry["dataset"] == "stores" and entry["period"] == period and entry["area_code"] is not None)}
                for period in sorted(citywide_periods, reverse=True)]
    neighborhood_matches = sum(_neighborhood_matches(area, get_neighborhood(area["neighborhood_code"])) for area in geometries)
    payload = {"schema_version": _SCHEMA, "areas": geometries, "periods": periods,
               "observations": observations, "coverage": coverage,
               "source": {"provider": "서울특별시 열린데이터광장", "files": files, "file_count": len(files),
                          "boundary_source_url": SOURCE_URLS["areas"], "boundary_publication_date": "2023-10-23",
                          "boundary_zip_sha256": _BOUNDARY_HASH, "boundary_source_crs": "EPSG:5181",
                          "geometry_crs": "EPSG:4326", "boundary_current_compatibility": "unverified",
                          "area_count": len(geometries), "boundary_name_mismatches": mismatches,
                          "observation_name_mismatches": [{"dataset": key[0], "period": key[1], "area_code": key[2],
                              "source_name": key[3], "official_area_name": key[4], "row_count": count,
                              "selection_blocked": True} for key, count in sorted(historical_names.items())],
                          "neighborhood_join": {"matched_area_count": neighborhood_matches,
                                                "unmatched_area_count": len(geometries) - neighborhood_matches,
                                                "policy": "code_and_district_and_name_with_dot_variant_only"},
                          "candidate_policy": {"search_radius_m": SEARCH_RADIUS_M, "max_candidates": MAX_CANDIDATES,
                                               "distance_reference": "published_polygon_edge", "aggregation_radius": False},
                          "observed_scope": counts, "metric_fields": {key: spec[1] for key, spec in _METRICS.items()},
                          "dataset_periods": dataset_periods,
                          "stores_overlap_validation": {"policy": "complete_citywide_preferred_exact_overlap", "periods": overlaps},
                          "source_urls": SOURCE_URLS,
                          "numeric_values_exposed": False, "analysis_engine_connected": False}}
    payload["catalog_version"] = "b1_" + canonical_hash(payload)[:24]
    return payload


@lru_cache(maxsize=1)
def _catalog():
    payload = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    version = payload.pop("catalog_version")
    if payload.get("schema_version") != _SCHEMA or version != "b1_" + canonical_hash(payload)[:24]:
        raise ValueError("Analysis catalogue integrity check failed")
    payload["catalog_version"] = version
    payload["area_index"] = {area["area_code"]: area for area in payload["areas"]}
    payload["coverage_index"] = {(entry["dataset"], entry["period"], entry["area_code"]): entry for entry in payload["coverage"]}
    return payload


def get_analysis_catalog_source() -> dict:
    return deepcopy({**_catalog()["source"], "catalog_version": _catalog()["catalog_version"]})


def get_analysis_areas() -> list[dict]:
    return deepcopy(_catalog()["areas"])


def get_analysis_area(area_code: str) -> dict | None:
    return deepcopy(_catalog()["area_index"].get(area_code)) if isinstance(area_code, str) else None


def _period_label(period):
    return f"{period[:4]}년 {period[4]}분기"


def get_area_availability(area_code: str, industry_code: str) -> dict:
    data = _catalog()
    area = data["area_index"].get(area_code)
    if area is None or industry_code not in _INDUSTRIES:
        raise ValueError("Unknown official market or industry")
    periods = []
    for period in data["periods"]:
        metrics = {}
        for metric, (kind, _field, label, specific) in _METRICS.items():
            key = "|".join((area_code, industry_code if specific else "*", period))
            value = data["observations"][metric].get(key)
            item = {"label": label, "industry_specific": specific,
                    "source_url": SOURCE_URLS[kind], "source_field": _field}
            if area["boundary_identity_status"] != "code_name_match":
                item.update(status="unavailable", reason="공개 경계와 상권 자료의 명칭이 달라 연결 확인이 필요합니다.")
            elif ((kind, period, None) not in data["coverage_index"]
                  and (kind != "stores" or (kind, period, area_code) not in data["coverage_index"])):
                item.update(status="not_collected", reason="이 상권·기간의 해당 자료를 아직 확보하지 않았습니다.")
            elif value is None:
                item.update(status="no_observation", reason="확인한 자료에 해당 상권·업종·기간의 관측 행이 없습니다." if specific else "확인한 자료에 해당 상권·기간의 관측 행이 없습니다.")
            elif value == 0:
                item.update(status="unavailable", reason="관측 행은 있으나 필요한 수치가 비어 있습니다.")
            else:
                item.update(status="available", zero_observation=value == 2,
                            reason="유효한 수치가 확인됐습니다." if specific else "업종과 무관한 지역 유동인구 자료입니다.")
            metrics[metric] = item
        industry_data = any(item["status"] == "available" and item["industry_specific"] for item in metrics.values())
        any_data = any(item["status"] == "available" for item in metrics.values())
        periods.append({"code": period, "label": _period_label(period), "available": any_data,
                        "industry_data_available": industry_data, "population_only": any_data and not industry_data,
                        "metrics": metrics})
    return {"periods": periods, "available_periods": [period["code"] for period in periods if period["available"]]}


def _ring_membership(point, ring):
    x, y = point
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        x1, y1 = a[:2]
        x2, y2 = b[:2]
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) < 1e-12 and min(x1, x2) - 1e-10 <= x <= max(x1, x2) + 1e-10 and min(y1, y2) - 1e-10 <= y <= max(y1, y2) + 1e-10:
            return "boundary"
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return "inside" if inside else "outside"


def _polygons(geometry):
    return [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]


def geometry_membership(point, geometry):
    for polygon in _polygons(geometry):
        outer = _ring_membership(point, polygon[0])
        if outer == "boundary":
            return "boundary"
        if outer == "inside":
            holes = [_ring_membership(point, ring) for ring in polygon[1:]]
            if "boundary" in holes:
                return "boundary"
            if "inside" not in holes:
                return "inside"
    return "outside"


def _boundary_distance(point, geometry):
    lon, lat = point
    sx, sy = 111195 * math.cos(math.radians(lat)), 111195
    distance = math.inf
    for polygon in _polygons(geometry):
        for ring in polygon:
            for a, b in zip(ring, ring[1:] + ring[:1]):
                ax, ay, bx, by = (a[0] - lon) * sx, (a[1] - lat) * sy, (b[0] - lon) * sx, (b[1] - lat) * sy
                dx, dy = bx - ax, by - ay
                fraction = max(0, min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy))) if dx or dy else 0
                distance = min(distance, math.hypot(ax + fraction * dx, ay + fraction * dy))
    return distance


def _location_point(location):
    source = location.get("reference_point", {}) if location.get("kind") == "area" else location
    lon, lat = source.get("longitude"), source.get("latitude")
    if (type(lon) in (int, float) and type(lat) in (int, float)
            and math.isfinite(lon) and math.isfinite(lat) and 126 <= lon <= 128 and 37 <= lat <= 38.5):
        return lon, lat
    return None


def get_analysis_options(location: dict, industry_code: str) -> dict:
    if not isinstance(location, dict) or industry_code not in _INDUSTRIES:
        raise ValueError("A saved location and official industry are required")
    data = _catalog()
    point = _location_point(location)
    neighborhood = get_neighborhood(location.get("neighborhood_code")) if location.get("kind") == "area" else None
    valid_neighborhood = neighborhood is not None and neighborhood["district_code"] == location.get("district_code")
    matches = []
    for area in data["areas"]:
        if point is not None:
            x, y = point
            minx, miny, maxx, maxy = area["bbox"]
            if x < minx - .013 or x > maxx + .013 or y < miny - .010 or y > maxy + .010:
                continue
            relation = geometry_membership(point, area["geometry"])
            distance = 0 if relation in ("inside", "boundary") else _boundary_distance(point, area["geometry"])
            if distance > SEARCH_RADIUS_M:
                continue
            relation = "nearby" if relation == "outside" else relation
        elif valid_neighborhood and _neighborhood_matches(area, neighborhood):
            relation, distance = "neighborhood", None
        else:
            continue
        matches.append((area, relation, distance))
    matches.sort(key=lambda match: (match[1] not in ("inside", "boundary"), match[2] if match[2] is not None else 0, match[0]["name"], match[0]["area_code"]))
    candidates = []
    for area, relation, distance in matches[:MAX_CANDIDATES]:
        availability = get_area_availability(area["area_code"], industry_code)
        candidates.append({**deepcopy(area), "relation": relation, "distance_m": round(distance) if distance is not None else None,
                           "availability": availability, "available_periods": availability["available_periods"],
                           "selection_blocked_reason": "경계와 상권 명칭의 연결 확인이 필요합니다." if area["boundary_identity_status"] == "name_mismatch" else None})
    scope = {"boundary_publication_date": "2023-10-23", "boundary_current_compatibility": "unverified",
             "boundary_notice": "2023년 공개 경계이며 현재 분기 경계와의 동일성은 확인되지 않았습니다.",
             "candidate_basis": "point_proximity" if point is not None else "administrative_dong" if valid_neighborhood else "unresolved",
             "search_radius_m": SEARCH_RADIUS_M if point is not None else None,
             "search_radius_notice": "후보를 찾는 거리이며 통계 집계 반경이 아닙니다." if point is not None else
                 "선택 행정동으로 등록된 상권 목록입니다. 행정동 전체의 통계나 경계와 같다는 뜻은 아닙니다." if valid_neighborhood else
                 "상권 후보를 찾으려면 정확한 주소 또는 지도 참고 위치가 필요합니다.",
             "max_candidates": MAX_CANDIDATES, "data_periods": list(data["periods"]),
             "analysis_setup_only": True, "analysis_engine_connected": False,
             "boundary_source_url": SOURCE_URLS["areas"], "official_area_count": len(data["areas"])}
    status = "ready" if candidates else "no_candidates" if point is not None else "needs_location_refinement"
    message = ("공개 상권 경계를 확인하고 분석할 상권을 선택해 주세요." if candidates else
               "확인한 위치의 1km 이내에 공개 상권 후보가 없습니다. 다른 주소·역·동네를 확인해 주세요." if point is not None else
               "이 동네·역만으로 상권 후보를 확인하지 못했습니다. 정확한 주소 또는 지도 참고 위치를 확인해 주세요.")
    return {"catalog_version": data["catalog_version"], "status": status, "candidates": candidates,
            "candidate_count": len(matches), "truncated": len(matches) > MAX_CANDIDATES, "scope": scope, "message": message}


def validate_analysis_selection(location: dict, industry_code: str, area_code: str, period: str,
                                expected_catalog_version: str | None = None) -> dict:
    options = get_analysis_options(location, industry_code)
    if expected_catalog_version is not None and expected_catalog_version != options["catalog_version"]:
        raise ValueError("자료 목록이 변경됐습니다. 상권과 기간을 다시 확인해 주세요.")
    area = next((candidate for candidate in options["candidates"] if candidate["area_code"] == area_code), None)
    if area is None:
        raise ValueError("현재 위치의 후보 목록에서 상권을 선택해 주세요.")
    selected_period = next((entry for entry in area["availability"]["periods"] if entry["code"] == period and entry["available"]), None)
    if selected_period is None:
        raise ValueError("확인된 자료가 있는 기간을 선택해 주세요.")
    return {"area_code": area_code, "area_name": area["name"], "period": period, "period_label": selected_period["label"],
            "industry_code": industry_code, "catalog_version": options["catalog_version"], "availability": deepcopy(selected_period),
            "boundary": {"publication_date": "2023-10-23", "compatibility": "unverified", "source_url": SOURCE_URLS["areas"]},
            "analysis_setup_complete": True, "ready_for_analysis": False, "analysis_stage": "configuration_only"}


if __name__ == "__main__":
    result = build_catalog()
    _SNAPSHOT.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(result['areas'])} boundaries and checked availability: {result['catalog_version']}")
