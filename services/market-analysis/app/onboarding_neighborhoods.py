"""Seoul administrative-dong choices from the official 2026-08 code snapshot.

Normal imports read only the adjacent JSON. Rebuild offline from the preserved
official ZIP/CSV with ``python -m app.onboarding_neighborhoods`` in development.
The catalogue identifies an administrative unit, never a store/map coordinate
or a confirmed market boundary. No credentials or network are used here.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import zipfile


_DEVELOPMENT = Path(__file__).resolve().parents[1]
_RAW_ROOT = _DEVELOPMENT / "data" / "raw" / "neighborhoods"
_SNAPSHOT = Path(__file__).with_name("onboarding_neighborhoods.json")
_BASE_YM = "202608"
_ARCHIVE_NAME = "national_administrative_dong_codes.zip"
_ARCHIVE_MEMBER = "SEOUL_ADMI/ADMI_202608.csv"
_CSV_NAME = "ADMI_202608.csv"
_ARCHIVE_HASH = "69e8c5dad71dffbc6d0d9be8f9ad607e3d02e72a2577cbaf1b9ba795518226e4"
_CSV_HASH = "bfe27cdb75fbb9f9944ddc6a1dd073e71cd649dbd2fb6f26ca8efc098b6b3d52"
_SOURCE_URL = "https://data.seoul.go.kr/dataVisual/seoul/seoulLivingPopulation.do"
_DOWNLOAD_URL = "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false"


def _districts_by_name() -> dict[str, str]:
    # Join on the source's SGG_NM, rather than infer a district by truncating a
    # code from another possible administrative/statistical code namespace.
    districts = json.loads(Path(__file__).with_name("onboarding_industries.json").read_text(encoding="utf-8"))["districts"]
    mapping = {row["name"]: row["code"] for row in districts}
    if (len(districts) != 25 or len(mapping) != 25 or len(set(mapping.values())) != 25
            or any(not isinstance(name, str) or not name.strip()
                   or not isinstance(code, str) or not re.fullmatch(r"11\d{3}", code)
                   for name, code in mapping.items())):
        raise ValueError("Expected 25 unique Seoul district names and codes")
    return mapping


def _checked_neighborhoods(rows: list[dict]) -> list[dict]:
    districts = _districts_by_name()
    codes, names, covered_districts = set(), set(), set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"code", "name", "district_code", "district_name"}:
            raise ValueError("Invalid neighborhood fields")
        code, name = row["code"], row["name"]
        district_name, district_code = row["district_name"], row["district_code"]
        if (not isinstance(code, str) or not re.fullmatch(r"11\d{6}", code)
                or not isinstance(name, str) or not name.strip() or name != name.strip()
                or any(ord(char) < 32 for char in name) or "\ufffd" in name
                or districts.get(district_name) != district_code
                or code[:5] != district_code):
            raise ValueError("Invalid official neighborhood code, name or district mapping")
        if code in codes or (district_code, name) in names:
            raise ValueError("Duplicate neighborhood code or district/name pair")
        codes.add(code)
        names.add((district_code, name))
        covered_districts.add(district_code)
    if len(rows) != 427 or covered_districts != set(districts.values()):
        raise ValueError("Expected all 427 Seoul rows and 25 districts in the pinned source")
    return sorted(rows, key=lambda row: row["code"])


def build_neighborhood_catalog(raw_root: Path | None = None) -> dict:
    """Reproduce choices using the preserved, hash-pinned official source."""
    raw_root = Path(raw_root) if raw_root is not None else _RAW_ROOT
    archive_data = (raw_root / _ARCHIVE_NAME).read_bytes()
    csv_data = (raw_root / _CSV_NAME).read_bytes()
    provenance = json.loads((raw_root / "provenance.json").read_text(encoding="utf-8"))
    if sha256(archive_data).hexdigest() != _ARCHIVE_HASH or sha256(csv_data).hexdigest() != _CSV_HASH:
        raise ValueError("Neighborhood source hash changed; review the new source before rebuilding")
    expected = {"source_url": _SOURCE_URL, "download_url": _DOWNLOAD_URL,
                "base_ym": _BASE_YM, "archive_member": _ARCHIVE_MEMBER,
                "archive_file": _ARCHIVE_NAME, "archive_sha256": _ARCHIVE_HASH,
                "csv_file": _CSV_NAME, "csv_sha256": _CSV_HASH,
                "request_method": "POST", "csv_encoding": "utf-8-sig",
                "request_parameters": {"infId": "DOWNLOAD", "infSeq": "4", "seq": "18", "seqNo": ""}}
    if any(provenance.get(key) != value for key, value in expected.items()) or not provenance.get("retrieved_at"):
        raise ValueError("Neighborhood provenance does not match the pinned source")
    with zipfile.ZipFile(io.BytesIO(archive_data)) as archive:
        if archive.read(_ARCHIVE_MEMBER) != csv_data:
            raise ValueError("Preserved CSV differs from the official archive member")
        month_files = [name for name in archive.namelist() if re.fullmatch(r"SEOUL_ADMI/ADMI_\d{6}\.csv", name)]
        if max(month_files) != _ARCHIVE_MEMBER or len(month_files) != provenance.get("source_archive_month_count"):
            raise ValueError("Selected CSV is not the latest member of the preserved source archive")

    reader = csv.DictReader(io.StringIO(csv_data.decode("utf-8-sig")))
    if reader.fieldnames != ["SIDO_NM", "SGG_NM", "ADMI_NM", "ADMI_CD", "FULL_NM", "BASE_YM"]:
        raise ValueError("Unexpected official neighborhood CSV columns")
    source_rows = list(reader)
    if len(source_rows) != 3563 or any(row.get("BASE_YM") != _BASE_YM for row in source_rows):
        raise ValueError("Source row count or base month is inconsistent")
    districts = _districts_by_name()
    neighborhoods = []
    for row in source_rows:
        if row["SIDO_NM"] != "서울특별시":
            continue
        district_name = row["SGG_NM"]
        district_code = districts.get(district_name)
        if district_code is None or row["FULL_NM"] != f"서울특별시 {district_name} {row['ADMI_NM']}":
            raise ValueError("Unknown Seoul district or conflicting full name in official source")
        neighborhoods.append({"code": row["ADMI_CD"], "name": row["ADMI_NM"],
                              "district_code": district_code, "district_name": district_name})
    neighborhoods = _checked_neighborhoods(neighborhoods)
    counts = Counter(row["district_code"] for row in neighborhoods)
    files = []
    for name, digest in ((_ARCHIVE_NAME, _ARCHIVE_HASH), (_CSV_NAME, _CSV_HASH)):
        path = raw_root / name
        try:
            display_path = path.resolve().relative_to(_DEVELOPMENT.parent).as_posix()
        except ValueError:
            display_path = path.resolve().as_posix()
        files.append({"path": display_path, "sha256": digest})
    return {
        "schema_version": "onboarding-neighborhoods-v1",
        "neighborhoods": neighborhoods,
        "source": {
            "provider": provenance["provider"], "title": provenance["title"],
            "source_url": _SOURCE_URL, "download_url": _DOWNLOAD_URL,
            "retrieved_at": provenance["retrieved_at"], "base_ym": _BASE_YM,
            "source_date": "2026-08", "type": "administrative_dong",
            "code_field": "ADMI_CD",
            "code_system": "행정안전부 주민등록 행정기관코드 10자리의 끝 00을 제외한 8자리 코드",
            "code_system_reference": _SOURCE_URL,
            "district_mapping": "원본 SGG_NM을 서울 25개 구 공식 명칭에 연결하고 코드 접두부로 교차 검증",
            "neighborhood_count": len(neighborhoods), "district_count": len(districts),
            "source_record_count": len(source_rows), "archive_member": _ARCHIVE_MEMBER,
            "source_archive_month_count": len(month_files),
            "archive_sha256": _ARCHIVE_HASH, "csv_sha256": _CSV_HASH, "files": files,
            "district_counts": [{"code": code, "name": name, "count": counts[code]}
                                for name, code in sorted(districts.items(), key=lambda pair: pair[1])],
            "scope_note": "2026년 8월 공식 원본의 서울 행정동 427개입니다. 법정동 목록이 아니며 이후 행정구역 변경은 실시간 확인하지 않았습니다.",
            "coordinates_provided": False, "analysis_area_confirmed": False,
        },
    }


def _load_catalog() -> dict:
    payload = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "onboarding-neighborhoods-v1":
        raise ValueError("Unknown neighborhood catalogue version")
    rows = _checked_neighborhoods(payload["neighborhoods"])
    source = payload["source"]
    if (source.get("base_ym") != _BASE_YM or source.get("neighborhood_count") != len(rows)
            or source.get("district_count") != 25 or source.get("archive_sha256") != _ARCHIVE_HASH
            or source.get("csv_sha256") != _CSV_HASH):
        raise ValueError("Neighborhood snapshot provenance or counts are inconsistent")
    return payload


if __name__ == "__main__":
    snapshot = build_neighborhood_catalog()
    _SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(snapshot['neighborhoods'])} neighborhoods in {snapshot['source']['district_count']} Seoul districts.")


_CATALOG = _load_catalog()
_BY_CODE = {row["code"]: row for row in _CATALOG["neighborhoods"]}


def get_neighborhoods() -> list[dict]:
    return deepcopy(_CATALOG["neighborhoods"])


def get_neighborhood(code: str) -> dict | None:
    return deepcopy(_BY_CODE.get(code)) if isinstance(code, str) else None


def get_neighborhood_source() -> dict:
    return deepcopy(_CATALOG["source"])
