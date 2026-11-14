"""Seoul station choices from a preserved official KRIC XLSX snapshot.

Names never establish a station's district: its source road address must contain
Seoul and a recognised district. Line-specific source identities remain separate.
Duplicate identities are merged only when their source address is identical;
all source rows and name/line variants remain available for audit. Coordinates
are optional reference points, not a verified entrance or analysis boundary.

Rebuild offline: ``python -m app.onboarding_stations`` from development.
Normal imports read only the adjacent JSON; no environment or network is used.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from xml.etree import ElementTree as ET
import zipfile

from app.onboarding_catalog import SEOUL_DISTRICTS


_ROOT = Path(__file__).resolve().parents[1]
_WORKBOOK = _ROOT / "data" / "raw" / "stations" / "kric_all_stations_20260630.xlsx"
_SNAPSHOT = Path(__file__).with_name("onboarding_stations.json")
_EXPECTED_SHA256 = "cdf1d84a7e5c898b2aacd622783ba8ba9af35c40bee0561dc97d55ce8e063f94"
_NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_FIELDS = ("역번호", "역사명", "노선번호", "노선명", "영문역사명", "한자역사명", "환승역구분",
           "환승노선번호", "환승노선명", "역위도", "역경도", "운영기관명", "역사도로명주소", "역사전화번호", "데이터기준일자")
_SEOUL = re.compile(r"^서울(?:특별시|시)?\s+([가-힣]+구)(?=\s)")
_OTHER_REGION = re.compile(
    r"^(?:부산(?:광역시|시)?|대구(?:광역시|시)?|인천(?:광역시|시)?|광주(?:광역시|시)?|"
    r"대전(?:광역시|시)?|울산(?:광역시|시)?|세종(?:특별자치시|시)?|경기도|경기|"
    r"강원(?:특별자치도|도)?|충청북도|충북|충청남도|충남|전북특별자치도|전라북도|전북|"
    r"전라남도|전남|경상북도|경북|경상남도|경남|제주(?:특별자치도|도)?)\s")


def _text(value):
    return " ".join(str(value or "").split())


def _display_name(raw):
    match = re.fullmatch(r"([^()]+)(\(.*\))?", raw)
    if not match:
        raise ValueError("Unexpected station-name shape")
    name, qualifier = match.groups()
    name = name.strip()
    return (name if name.endswith("역") else name + "역") + (qualifier or "")


def _source_date(raw):
    try:
        if re.fullmatch(r"\d+(?:\.\d+)?", raw):
            value = (datetime(1899, 12, 30) + timedelta(days=float(raw))).date()
        else:
            value = datetime.strptime(raw, "%Y-%m-%d").date()
        return value.isoformat() if value.year >= 2000 else None
    except (ValueError, OverflowError):
        return None


def _rows(workbook):
    with zipfile.ZipFile(workbook) as archive:
        if ET.fromstring(archive.read("xl/workbook.xml")).find("s:workbookPr", _NS).get("date1904", "0") not in ("0", "false"):
            raise ValueError("Unexpected workbook date system")
        strings = ["".join(node.itertext()) for node in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        rows = ET.fromstring(archive.read("xl/worksheets/sheet1.xml")).findall("s:sheetData/s:row", _NS)
        result = []
        for row in rows:
            cells = {}
            for cell in row.findall("s:c", _NS):
                if cell.find("s:f", _NS) is not None:
                    raise ValueError("Source catalogue must contain values, not formulas")
                value_node = cell.find("s:v", _NS)
                value = value_node.text if value_node is not None else ""
                cells[re.sub(r"\d", "", cell.attrib["r"])] = strings[int(value)] if cell.get("t") == "s" else value
            values = [cells.get(chr(65 + i), "") for i in range(len(_FIELDS))]
            if not result:
                if tuple(values) != _FIELDS:
                    raise ValueError("Official station source columns changed")
            result.append({"source_row": int(row.attrib["r"]), **dict(zip(_FIELDS, values))})
        return result[1:]


def build_catalog() -> dict:
    """Reproduce the catalogue from the pinned, locally preserved workbook."""
    actual_hash = sha256(_WORKBOOK.read_bytes()).hexdigest()
    if actual_hash != _EXPECTED_SHA256:
        raise ValueError("Station workbook differs from the reviewed official snapshot")
    raw_rows = _rows(_WORKBOOK)
    districts = {row["name"]: row["code"] for row in SEOUL_DISTRICTS}
    grouped, excluded = defaultdict(list), {"explicit_non_seoul_address": [], "unverified_region_or_district": []}
    for row in raw_rows:
        address = _text(row["역사도로명주소"])
        seoul = _SEOUL.match(address)
        if not seoul or seoul[1] not in districts:
            reason = "explicit_non_seoul_address" if _OTHER_REGION.match(address) else "unverified_region_or_district"
            excluded[reason].append({"source_row": row["source_row"], "name": row["역사명"], "road_address": address})
            continue
        key = tuple(_text(row[field]) for field in ("운영기관명", "노선번호", "역번호"))
        if not all(key) or not re.fullmatch(r"[A-Za-z0-9]+", key[1]) or not re.fullmatch(r"[A-Za-z0-9]+", key[2]):
            raise ValueError("Missing or malformed source station identity")
        row = {**row, "district_name": seoul[1], "district_code": districts[seoul[1]], "road_address": address,
               "source_data_date": _source_date(_text(row["데이터기준일자"]))}
        grouped[key].append(row)

    stations, coordinate_issues, duplicate_identities = [], [], []
    for (operator, line_code, station_code), group in grouped.items():
        if len({(row["road_address"], row["district_code"]) for row in group}) != 1:
            raise ValueError("Duplicate source station identity has conflicting addresses")
        # Prefer the latest dated source name, retaining all older source names.
        newest = max(group, key=lambda row: (row["source_data_date"] or "", -row["source_row"]))
        raw_name = _text(newest["역사명"])
        identifier = "kric-" + sha256(operator.encode("utf-8")).hexdigest()[:12] + "-" + line_code + "-" + station_code
        aliases = sorted({_text(row["역사명"]) for row in group} | {_display_name(_text(row["역사명"])) for row in group})
        entry = {
            "id": identifier, "name": _display_name(raw_name), "source_name": raw_name,
            "aliases": aliases, "lines": sorted({_text(row["노선명"]) for row in group}),
            "district_code": newest["district_code"], "district_name": newest["district_name"],
            "road_address": newest["road_address"], "operator": operator,
            "source_line_code": line_code, "source_station_code": station_code,
            "source_data_date": newest["source_data_date"], "verification": "official_station_address",
            "analysis_area_confirmed": False,
            "source_records": [{"row": row["source_row"], "name": row["역사명"], "line_name": row["노선명"],
                                "latitude": row["역위도"], "longitude": row["역경도"],
                                "data_date_raw": row["데이터기준일자"], "data_date": row["source_data_date"]} for row in group],
        }
        coordinates, invalid = set(), False
        for row in group:
            try:
                pair = float(row["역위도"]), float(row["역경도"])
                if not all(math.isfinite(value) for value in pair) or not (37 <= pair[0] <= 38 and 126 <= pair[1] <= 128):
                    invalid = True
                coordinates.add(pair)
            except (ValueError, TypeError):
                invalid = True
        if invalid or len(coordinates) != 1:
            entry["coordinate_status"] = "withheld_outlier_or_missing" if invalid else "withheld_conflicting_source_rows"
            coordinate_issues.append({"id": identifier, "name": entry["name"], "reason": entry["coordinate_status"],
                                      "source_rows": [row["source_row"] for row in group]})
        else:
            entry["latitude"], entry["longitude"] = next(iter(coordinates))
            entry["coordinate_status"] = "source_provided_coarse_range_checked"
        if len(group) > 1:
            duplicate_identities.append({"id": identifier, "name": entry["name"], "source_rows": [row["source_row"] for row in group],
                                         "lines": entry["lines"], "aliases": aliases})
        stations.append(entry)
    stations.sort(key=lambda row: (row["name"], row["lines"], row["id"]))
    dates = [row["source_data_date"] for group in grouped.values() for row in group if row["source_data_date"]]
    return {
        "schema_version": "onboarding-stations-v1", "stations": stations,
        "source": {
            "provider": "국가철도공단 레일포털 / 전국도시철도운영기관",
            "title": "표준데이터 역사정보(전체 기관)",
            "source_url": "https://data.kric.go.kr/rips/M_01_01/detail.do?id=32",
            "portal_url": "https://www.data.go.kr/data/15013205/standard.do",
            "download_url": "https://data.kric.go.kr/rips/dataset/download.file?type=filedata&id=32&operation=1",
            "source_filename": "전체_도시철도역사정보_20260630.xlsx", "source_file_date": "2026-06-30",
            "page_modified_date": "2026-07-06", "local_source_path": "development/data/raw/stations/kric_all_stations_20260630.xlsx",
            "file_sha256": actual_hash, "generated_at": datetime.now(timezone.utc).isoformat(),
            "raw_row_count": len(raw_rows), "included_source_row_count": sum(len(rows) for rows in grouped.values()),
            "station_count": len(stations), "district_count": len({row["district_code"] for row in stations}),
            "row_date_min": min(dates), "row_date_max": max(dates),
            "undated_included_row_count": sum(row["source_data_date"] is None for group in grouped.values() for row in group),
            "excluded_counts": {key: len(value) for key, value in excluded.items()},
            "duplicate_identities": duplicate_identities, "coordinate_issues": coordinate_issues,
            "seoul_filter": "원본 도로명주소의 서울특별시/서울시/서울 표기와 확인된 서울 25개 자치구 명칭",
            "same_name_policy": "이름만 같은 다른 기관·노선·역번호는 별도 선택. 같은 기관+노선번호+역번호와 동일 주소의 중복만 병합하며 원본 행·명칭·노선을 보존.",
            "coordinate_policy": "주소로 서울 여부를 판단. 좌표는 원본 값이며 거친 범위(위도37~38·경도126~128) 밖 또는 같은 ID의 좌표가 충돌하면 미제공. 이 검사는 서울 경계나 좌표 정확성 검증이 아님.",
            "coverage_note": "2026-06-30 파일에 담긴 서울 주소 확인 역 목록입니다. 행별 기준일이 다르고 현재 운행·폐역·신설역 및 전체 서울 역의 완전성을 실시간 검증하지 않았습니다.",
            "location_note": "자동 자치구는 역 등록주소 기준입니다. 선택한 출구·역 주변의 실제 사업 위치와 분석 상권 범위는 후속 확인이 필요합니다.",
        },
        "excluded_source_rows": excluded,
    }


def _load():
    payload = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "onboarding-stations-v1":
        raise ValueError("Unknown station catalogue version")
    district_codes = {row["code"]: row["name"] for row in SEOUL_DISTRICTS}
    identifiers = set()
    for row in payload["stations"]:
        if (not isinstance(row.get("id"), str) or row["id"] in identifiers
                or district_codes.get(row.get("district_code")) != row.get("district_name")
                or not _SEOUL.match(row.get("road_address", "")) or not row.get("lines")):
            raise ValueError("Invalid station catalogue identity or district")
        identifiers.add(row["id"])
    if len(identifiers) != payload["source"]["station_count"]:
        raise ValueError("Station catalogue count mismatch")
    return payload


if __name__ == "__main__":
    snapshot = build_catalog()
    _SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(snapshot['stations'])} Seoul station choices.")


_CATALOG = _load()
_STATIONS = {row["id"]: row for row in _CATALOG["stations"]}
STATION_SOURCE = deepcopy(_CATALOG["source"])


def get_stations() -> list[dict]:
    return deepcopy(_CATALOG["stations"])


def get_station(identifier: str) -> dict | None:
    return deepcopy(_STATIONS.get(identifier)) if isinstance(identifier, str) else None


def get_station_source() -> dict:
    return deepcopy(STATION_SOURCE)
