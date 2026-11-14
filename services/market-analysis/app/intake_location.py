"""Resolve intake addresses without inventing places or selecting a market.

Only the geocoder may supply coordinates. A unique, matching Seoul address is
still a candidate for user confirmation, never a saved profile or market match.
Station, neighbourhood and landmark names require a separate verified source.
"""
from __future__ import annotations

import math
import re

from app.naver_clients import MapsClient, NaverApiError


_REGIONS = {
    "seoul": ("서울특별시", "서울시", "서울"),
    "busan": ("부산광역시", "부산시", "부산"),
    "daegu": ("대구광역시", "대구시", "대구"),
    "incheon": ("인천광역시", "인천시", "인천"),
    "gwangju": ("광주광역시", "광주시", "광주"),
    "daejeon": ("대전광역시", "대전시", "대전"),
    "ulsan": ("울산광역시", "울산시", "울산"),
    "sejong": ("세종특별자치시", "세종시", "세종"),
    "gyeonggi": ("경기도", "경기"),
    "gangwon": ("강원특별자치도", "강원도", "강원"),
    "chungbuk": ("충청북도", "충북"),
    "chungnam": ("충청남도", "충남"),
    "jeonbuk": ("전북특별자치도", "전라북도", "전북"),
    "jeonnam": ("전라남도", "전남"),
    "gyeongbuk": ("경상북도", "경북"),
    "gyeongnam": ("경상남도", "경남"),
    "jeju": ("제주특별자치도", "제주도", "제주"),
}
_ADDRESS_NUMBER = re.compile(
    r"(?<![가-힣A-Za-z0-9])([가-힣A-Za-z0-9·.]+(?:대로|로|길|동|읍|면|리|가))"
    r"\s*(?:(산|지하)\s*)?(\d+)(?:\s*-\s*(\d+))?(?=$|[\s,()])"
)
_DISTRICT = re.compile(r"(?:^|\s)([가-힣]+(?:구|군))(?=\s|$)")


def _result(status, *, candidates=None, verified=False, question=None):
    return {"status": status, "candidates": candidates or [],
            "verified_seoul": verified, "question": question}


def _region(address):
    for region, aliases in _REGIONS.items():
        if any(address == alias or address.startswith(alias + " ") for alias in aliases):
            return region
    return None


def declared_region(text):
    """A region explicitly written in the input, never geographic verification."""
    return _region(" ".join(text.split())) if isinstance(text, str) else None


def _address_identity(address):
    if re.search(r"또는|혹은|아니면", address):
        return None
    matches = list(_ADDRESS_NUMBER.finditer(address))
    if len(matches) != 1:
        return None
    street, designation, main, sub = matches[0].groups()
    # A subterranean road address and an ordinary road address with the same
    # number are different locations, as are mountain and ordinary lot numbers.
    return street, designation or "", int(main), int(sub) if sub else None


def _candidate(row):
    if not isinstance(row, dict):
        raise ValueError("Invalid candidate")
    addresses = []
    for field in ("road_address", "jibun_address"):
        value = row.get(field, "")
        if not isinstance(value, str) or len(value) > 500 or any(ord(char) < 32 for char in value):
            raise ValueError("Invalid address")
        addresses.append(" ".join(value.split()))
    if not any(addresses):
        raise ValueError("Empty address")
    coordinates = []
    for field, bound in (("longitude", 180), ("latitude", 90)):
        value = row.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or not -bound <= value <= bound:
            raise ValueError("Invalid coordinate")
        coordinates.append(value)
    regions = {_region(address) for address in addresses} - {None}
    region = next(iter(regions)) if len(regions) == 1 else None
    return {"road_address": addresses[0], "jibun_address": addresses[1],
            "longitude": coordinates[0], "latitude": coordinates[1],
            "in_seoul": region == "seoul"}, region


def resolve_location(location: dict, client=None) -> dict:
    """Verify an address candidate; do not infer coordinates for place names.

    ``verified_seoul`` is true only for one exact address candidate with an
    explicit Seoul regional prefix. A ``near`` relation verifies only a reference
    point and never sets ``verified_seoul`` for the business location. Neither
    result is user confirmation or verification of a statistical-market boundary.
    """
    if not isinstance(location, dict):
        return _result("needs_precision", question="확인할 서울 지역이나 주소를 알려 주세요.")
    kind, text = location.get("kind"), location.get("text")
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 200 or any(ord(char) < 32 for char in text):
        return _result("needs_precision", question="주소를 200자 이내의 한 줄로 알려 주세요.")
    text = " ".join(text.split())
    if kind != "address":
        questions = {
            "station": "역 이름만으로 위치를 확정하지 않았습니다. 서울의 어느 구인지와 가까운 도로명 주소를 알려 주세요.",
            "area": "어느 지점인지 확인할 수 있도록 서울의 구·동과 도로명 주소 또는 지번을 알려 주세요.",
            "landmark": "건물·장소 이름만으로 위치를 확정하지 않았습니다. 도로명 주소 또는 지번을 알려 주세요.",
        }
        return _result("needs_precision", question=questions.get(kind, "서울의 구·동과 도로명 주소 또는 지번을 알려 주세요."))
    identity = _address_identity(text)
    if identity is None:
        return _result("needs_precision", question="도로명과 건물번호, 또는 동·리와 지번까지 알려 주세요.")
    try:
        rows = (client if client is not None else MapsClient()).geocode(text)
        if not isinstance(rows, list) or len(rows) > 10:
            raise ValueError("Invalid geocoding response")
        parsed = [_candidate(row) for row in rows]
    except (NaverApiError, ValueError, OSError):
        return _result("lookup_unavailable", question="주소 조회를 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.")
    if not parsed:
        return _result("not_found", question="일치하는 주소를 찾지 못했습니다. 도로명·건물번호 또는 지번을 다시 확인해 주세요.")

    query_region = _region(text)
    query_districts = set(_DISTRICT.findall(text))
    matches, regions, seen = [], [], set()
    for candidate, region in parsed:
        addresses = (candidate["road_address"], candidate["jibun_address"])
        if not any(_address_identity(address) == identity for address in addresses):
            continue
        districts = {district for address in addresses for district in _DISTRICT.findall(address)}
        if not query_districts <= districts or (query_region is not None and region is not None and query_region != region):
            continue
        key = tuple(candidate[field] for field in ("road_address", "jibun_address", "longitude", "latitude"))
        if key not in seen:
            seen.add(key)
            matches.append(candidate)
            regions.append(region)
    if not matches:
        return _result("needs_precision", question="조회 결과의 주소·건물번호가 입력한 주소와 일치하지 않아 확정하지 않았습니다. 전체 주소를 다시 확인해 주세요.")
    if location.get("relation") == "near":
        return {**_result(
            "needs_precision", candidates=matches,
            question="주변 위치를 설명하는 기준 주소 후보만 조회했습니다. 실제 사업 위치와 서울 여부를 확인할 수 있도록 가게 주소나 더 구체적인 지점을 알려 주세요.",
        ), "verification_scope": "reference_point"}
    if all(region is not None and region != "seoul" for region in regions):
        if all(region is not None and region != "seoul" for _, region in parsed):
            return _result("outside_seoul", candidates=matches, question="조회된 주소는 서울 밖입니다. 분석할 서울 지역의 주소를 알려 주세요.")
        return _result("needs_precision", candidates=matches, question="주소 검색 결과의 지역이 일관되지 않아 서울 밖으로 확정하지 않았습니다. 구·동을 포함한 전체 주소를 확인해 주세요.")
    if len(matches) > 1:
        return _result("choose_candidate", candidates=matches, question="주소 후보가 여러 곳입니다. 의도한 주소를 선택하거나 구·동을 더 알려 주세요.")
    if regions[0] != "seoul":
        return _result("needs_precision", candidates=matches, question="조회된 주소의 서울 여부를 확인하지 못했습니다. 서울의 구·동이 포함된 전체 주소를 알려 주세요.")
    return _result("address_candidate", candidates=matches, verified=True, question="조회된 서울 주소가 의도한 위치인지 확인해 주세요.")
