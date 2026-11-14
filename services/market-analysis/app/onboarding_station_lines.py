"""Passenger-facing line filters for the preserved Seoul KRIC station snapshot.

KRIC railway names/codes are not always passenger service names. This separate
presentation layer preserves every station ID, source line, address and record.
It neither adds stations nor infers all possible interchange services. No
environment, network, route ordering or physical-station merging is involved.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

from app.onboarding_stations import get_stations


_LINES = [
    *({"code": f"line-{n}", "name": f"{n}호선"} for n in range(1, 10)),
    {"code": "line-gyeongui-jungang", "name": "경의중앙선"},
    {"code": "line-gyeongchun", "name": "경춘선"},
    {"code": "line-suin-bundang", "name": "수인분당선"},
    {"code": "line-airport", "name": "공항철도"},
    {"code": "line-sinbundang", "name": "신분당선"},
    {"code": "line-ui-sinseol", "name": "우이신설선"},
    {"code": "line-sillim", "name": "신림선"},
    {"code": "line-gimpo-gold", "name": "김포골드라인"},
    {"code": "line-seohae", "name": "서해선"},
]
_BY_CODE = {row["code"]: row for row in _LINES}
_ORDER = {row["code"]: index for index, row in enumerate(_LINES)}
_SOURCE_LINE_NAMES = {
    **{f"{n}호선": f"line-{n}" for n in range(1, 9)},
    "경부선": "line-1",
    "경인선": "line-1",
    "서울 도시철도 9호선": "line-9",
    "수도권 도시철도 9호선": "line-9",
    "경의중앙선": "line-gyeongui-jungang",
    "경춘선": "line-gyeongchun",
    "분당선": "line-suin-bundang",
    "인천국제공항선": "line-airport",
    "신분당선": "line-sinbundang",
    "우이신설선": "line-ui-sinseol",
    "수도권 경량도시철도 신림선": "line-sillim",
    "김포도시철도": "line-gimpo-gold",
    "서해선": "line-seohae",
}
# Exact KORAIL I4102 identities, not a blanket conversion of 경원선 to 1호선.
# 코레일유통 서울본부 + 동부본부 publish these station/service memberships.
_GYEONGWON = {
    "1003": ("용산역", "line-gyeongui-jungang"),
    "1008": ("이촌역", "line-gyeongui-jungang"),
    "1009": ("서빙고역", "line-gyeongui-jungang"),
    "1010": ("한남역", "line-gyeongui-jungang"),
    "1011": ("옥수역", "line-gyeongui-jungang"),
    "1012": ("응봉역", "line-gyeongui-jungang"),
    "1013": ("왕십리역", "line-gyeongui-jungang"),
    "1014": ("청량리역", "line-1"),
    "1015": ("회기역", "line-1"),
    "1016": ("외대앞역", "line-1"),
    "1017": ("신이문역", "line-1"),
    "1018": ("석계역", "line-1"),
    "1019": ("광운대역", "line-1"),
    "1020": ("월계역", "line-1"),
    "1021": ("녹천역", "line-1"),
    "1022": ("창동역", "line-1"),
    "1901": ("방학역", "line-1"),
    "1902": ("도봉역", "line-1"),
    "1903": ("도봉산역", "line-1"),
}


def _codes_for_source(station: dict) -> list[str]:
    identity = (station["operator"], station["source_line_code"], station["source_station_code"])
    if identity[:2] == ("한국철도공사", "I4102"):
        expected = _GYEONGWON.get(identity[2])
        if not expected or station["name"] != expected[0] or station["lines"] != ["경원선"]:
            raise ValueError("Unreviewed Gyeongwon station identity or source line")
        return [expected[1]]
    if identity == ("한국철도공사", "I4108", "1019"):
        if station["name"] != "광운대역" or set(station["lines"]) != {"경의중앙선", "경춘선"}:
            raise ValueError("Reviewed Gwangundae source identity changed")
        # The source has two dated line labels for this identity. The passenger
        # service is 경춘선; its separate I4102 identity supplies 1호선.
        return ["line-gyeongchun"]
    try:
        codes = {_SOURCE_LINE_NAMES[name] for name in station["lines"]}
    except KeyError as exc:
        raise ValueError("Unreviewed station source line") from exc
    if not codes:
        raise ValueError("Station has no reviewed passenger line")
    return sorted(codes, key=_ORDER.__getitem__)


_STATIONS = get_stations()
_STATION_CODES = {station["id"]: _codes_for_source(station) for station in _STATIONS}
_USED_CODES = {code for codes in _STATION_CODES.values() for code in codes}
_SAME_LABEL = defaultdict(list)
for _station in _STATIONS:
    for _code in _STATION_CODES[_station["id"]]:
        _SAME_LABEL[(_code, _station["name"])].append(_station["id"])

STATION_LINE_SOURCE = {
    "schema_version": "onboarding-station-lines-v1",
    "reviewed_on": "2026-11-04",
    "station_count": len(_STATION_CODES),
    "line_count": len(_USED_CODES),
    "station_line_membership_count": sum(map(len, _STATION_CODES.values())),
    "source_station_snapshot": "onboarding_stations.json",
    "source_url": "https://data.kric.go.kr/rips/M_01_01/detail.do?id=32",
    "sources": [
        {"url": "https://www.korailretail.com/sub7_1.do", "title": "코레일유통 서울본부 관리역", "use": "경부선의 1호선 표기 및 용산·이촌·서빙고·한남의 경의중앙선 소속"},
        {"url": "https://www.korailretail.com/sub7_2.do", "title": "코레일유통 경인본부 관리역", "use": "경부·경인 구간의 1호선 표기"},
        {"url": "https://www.korailretail.com/sub7_4.do", "title": "코레일유통 동부본부 관리역", "use": "경원 구간 1호선, 옥수·응봉·왕십리의 경의중앙선, 광운대의 경춘선 소속"},
        {"url": "https://info.korail.com/info/contents.do?key=863", "title": "한국철도공사 광역철도 운행현황", "use": "경의중앙선·수인분당선·경춘선·서해선의 운행계통 명칭"},
        {"url": "https://wis.seoul.go.kr/was/stc/seniorTrnsprtCardInfo.do", "title": "서울시 교통정책과 수도권 지하철 이용 안내", "use": "1~9호선 및 특수 노선의 이용자 안내 명칭"},
    ],
    "source_line_aliases": deepcopy(_SOURCE_LINE_NAMES),
    "gyeongwon_station_overrides": [
        {"operator": "한국철도공사", "source_line_code": "I4102", "source_station_code": number,
         "name": name, "line_code": code} for number, (name, code) in _GYEONGWON.items()
    ],
    "gwangundae_override": {"operator": "한국철도공사", "source_line_code": "I4108", "source_station_code": "1019", "line_codes": ["line-gyeongchun"]},
    "same_line_same_name_groups": [
        {"line_code": code, "station_name": name, "station_ids": identifiers}
        for (code, name), identifiers in _SAME_LABEL.items() if len(identifiers) > 1
    ],
    "preserves_source_station_ids": True,
    "adds_stations": False,
    "complete_current_route_coverage": False,
    "coverage_note": "서울 주소가 확인된 원본 역만 표시합니다. 원본 노선명을 이용자 노선명으로 정리한 목록이며 전체 운행역·환승 노선을 실시간 검증한 노선도가 아닙니다. 원본에 없는 청량리·회기의 경춘선 소속 등은 추가하지 않았습니다.",
    "ordering_note": "노선은 1~9호선 다음 특수 노선 순서입니다. 역 목록은 가나다순으로 표시하며 운행 순서를 뜻하지 않습니다.",
}


def get_station_lines() -> list[dict]:
    return deepcopy([line for line in _LINES if line["code"] in _USED_CODES])


def get_station_line_codes(station_id: str) -> list[str]:
    return list(_STATION_CODES.get(station_id, ())) if isinstance(station_id, str) else []


def get_station_line(code: str) -> dict | None:
    return deepcopy(_BY_CODE.get(code)) if isinstance(code, str) and code in _USED_CODES else None


def get_station_line_source() -> dict:
    return deepcopy(STATION_LINE_SOURCE)
