"""사장님이 직접 등록한 가게의 프로필을 서비스에 넘기는 헤더 (6차 회의 11/20).

왜 헤더인가
- 리뷰 분석(8020)·맞춤 마케팅(8030)은 화면 서버(8000)와 다른 프로세스다. 로컬은 DB 없이 메모리·파일로, 실서버는 WAS 2대가
  Cloud DB 를 같이 쓴다. 등록 가게는 화면 서버의 저장소(registered_stores)에만 있다.
- 화면 서버가 등록 가게의 요청마다 이 헤더에 가게 프로필을 실어 보내면, 서비스는 DB 가 있든 없든·WAS 가 몇 대든 같은 방법으로
  그 가게를 안다 (서비스가 다시 켜진 뒤 첫 요청에도 헤더가 같이 오므로 바로 안다). 서비스는 127.0.0.1 에만 열려 있고
  화면 서버만 부른다 (APP_ACCESS_TOKEN 을 정하면 토큰 검사도 그대로다).
- 예시 세 곳(store_ongi·store_basak·store_mongle)과 게스트의 요청에는 이 헤더를 싣지 않는다 (예전 요청 그대로).

모양: X-IC26-Store-Profile: base64url(JSON) — 패딩(=)은 없어도 된다.
  {"v": 1, "store_id": "store_<16진수 12자>", "name", "business_type_name", "industry_code", "business_status",
   "channels": [...], "menus": [{"name", "price"}], "location": {...}, "area": {"area_code", "name", "period"}}
서비스는 decode 로 검사한다: 가게 id 모양(예시 가게 id 는 거절), 크기 상한, 칸마다 형식. 모르는 칸은 버린다.
서비스 쪽 목록은 Registry(크기 상한이 있는 LRU)에 둔다. store_profiles.remember 의 5초 기억에 기대지 않는다 (모델 호출이 5초를 넘음).
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import threading
from collections import OrderedDict

HEADER = "X-IC26-Store-Profile"
VERSION = 1
MAX_HEADER = 12_000             # base64url 글자 수. 메뉴 30개·긴 주소를 다 채워도 8KB 안쪽이다
REGISTERED_ID = re.compile(r"store_[0-9a-f]{12}")     # shared.store_profiles.REGISTERED_ID 와 같은 규칙
STATUSES = ("operating", "planning", "exploring")
KINDS = ("address", "station")
INDUSTRY = re.compile(r"[A-Za-z0-9]{1,20}")
AREA_CODE = re.compile(r"[0-9]{7}")
PERIOD = re.compile(r"[0-9]{4}[1-4]")
STATION_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
MAX_CHANNELS, MAX_MENUS, MAX_PRICE = 6, 30, 1_000_000
REGISTRY_MAX = 256

# 서울 25개 자치구 (상권 서비스의 문화행사 district 가 받는 이름)
SEOUL_DISTRICTS = ("종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구", "강북구", "도봉구", "노원구",
                   "은평구", "서대문구", "마포구", "양천구", "강서구", "구로구", "금천구", "영등포구", "동작구", "관악구", "서초구",
                   "강남구", "송파구", "강동구")


# 등록 화면이 보내는 배달 채널 이름 → 계약의 채널 코드 (shared.contracts.CHANNELS). 모르는 이름은 버린다
CHANNEL_NAMES = {"배달의민족": "baemin", "배민": "baemin", "쿠팡이츠": "coupangeats", "요기요": "yogiyo",
                 "네이버": "naver_place", "네이버플레이스": "naver_place", "네이버주문": "naver_place"}


class BadProfile(ValueError):
    """헤더 값이 틀림 (서비스는 400 으로 답한다)."""


# ── 화면 서버 쪽: StoreBundle → 헤더 ────────────────────────────────────
def payload(bundle) -> dict:
    """등록 가게 StoreBundle → 헤더에 담을 dict. 예시 가게(registered=False)면 ValueError."""
    if not getattr(bundle, "registered", False):
        raise ValueError("직접 등록한 가게만 헤더로 보낸다")
    return {"v": VERSION, "store_id": bundle.store_id, "name": bundle.short_name,
            "business_type_name": bundle.business_type_name, "industry_code": bundle.industry_code,
            "business_status": bundle.business_status, "channels": list(bundle.channels),
            "menus": [{"name": k, "price": v} for k, v in bundle.menu_prices.items()],
            "location": dict(bundle.location),
            "area": {"area_code": bundle.area_code, "name": bundle.area_name, "period": bundle.period or None}}


def encode(data: dict) -> str:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def headers_for(store_id: str | None) -> dict[str, str]:
    """화면 서버가 서비스를 부를 때 더할 헤더. 등록 가게면 {HEADER: 값}, 예시 가게·모르는 가게면 {} (예전 요청 그대로)."""
    from shared import store_profiles
    if not store_profiles.is_registered_id(store_id):
        return {}
    bundle = store_profiles.get(store_id)
    if bundle is None or not bundle.registered:
        return {}
    return {HEADER: encode(payload(bundle))}


# ── 서비스 쪽: 헤더 → 검사한 dict ───────────────────────────────────────
def _text(value, label: str, low: int, high: int, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise BadProfile(f"{label} 칸이 글자가 아닙니다")
    text = value.strip()
    if optional and not text:
        return None
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise BadProfile(f"{label} 칸에 쓸 수 없는 글자가 있습니다")
    if not low <= len(text) <= high:
        raise BadProfile(f"{label} 칸은 {low}~{high}자여야 합니다")
    return text


def _number(value, label: str, low: float, high: float) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or not low <= value <= high:
        raise BadProfile(f"{label} 값이 맞지 않습니다")
    return float(value)


def _location(value) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BadProfile("location 칸은 객체여야 합니다")
    kind = value.get("kind")
    if kind is not None and kind not in KINDS:
        raise BadProfile("location.kind 는 address 또는 station 입니다")
    out = {"kind": kind, "label": _text(value.get("label"), "location.label", 1, 120, optional=True),
           "road_address": _text(value.get("road_address"), "location.road_address", 1, 200, optional=True),
           "latitude": _number(value.get("latitude"), "location.latitude", -90, 90),
           "longitude": _number(value.get("longitude"), "location.longitude", -180, 180),
           "station_id": _text(value.get("station_id"), "location.station_id", 1, 80, optional=True),
           "station_name": _text(value.get("station_name"), "location.station_name", 1, 40, optional=True),
           "district_name": _text(value.get("district_name"), "location.district_name", 1, 20, optional=True)}
    if out["station_id"] is not None and not STATION_ID.fullmatch(out["station_id"]):
        raise BadProfile("location.station_id 모양이 맞지 않습니다")
    return out


def _area(value) -> dict:
    if value is None:
        return {"area_code": "", "name": "", "period": None}
    if not isinstance(value, dict):
        raise BadProfile("area 칸은 객체여야 합니다")
    code = value.get("area_code") or ""
    if code and not (isinstance(code, str) and AREA_CODE.fullmatch(code)):
        raise BadProfile("area.area_code 는 숫자 7자리입니다")
    period = value.get("period") or None
    if period is not None and not (isinstance(period, str) and PERIOD.fullmatch(period)):
        raise BadProfile("area.period 는 '20262' 모양입니다")
    return {"area_code": code, "name": _text(value.get("name"), "area.name", 1, 60, optional=True) or "", "period": period}


def _list(value, label: str, most: int) -> list:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > most:
        raise BadProfile(f"{label} 칸은 {most}개까지의 목록입니다")
    return value


def _menus(value) -> list[dict]:
    out: dict[str, int] = {}
    for item in _list(value, "menus", MAX_MENUS):
        if not isinstance(item, dict):
            raise BadProfile("menus 의 항목은 {name, price} 입니다")
        name = _text(item.get("name"), "menus.name", 1, 30)
        price = item.get("price")
        if isinstance(price, bool) or not isinstance(price, int) or not 0 <= price <= MAX_PRICE:
            raise BadProfile(f"menus.price 는 0~{MAX_PRICE} 정수입니다")
        out.pop(name, None)
        out[name] = price
    return [{"name": k, "price": v} for k, v in out.items()]


def check(data) -> dict:
    """헤더 JSON → 검사·정리한 dict. 틀리면 BadProfile."""
    if not isinstance(data, dict):
        raise BadProfile("가게 프로필은 객체여야 합니다")
    if data.get("v") != VERSION:
        raise BadProfile("가게 프로필 판(v)이 맞지 않습니다")
    store_id = data.get("store_id")
    if not (isinstance(store_id, str) and REGISTERED_ID.fullmatch(store_id)):
        raise BadProfile("store_id 는 직접 등록한 가게 id(store_ + 16진수 12자)여야 합니다")
    industry = data.get("industry_code") or ""
    if industry and not (isinstance(industry, str) and INDUSTRY.fullmatch(industry)):
        raise BadProfile("industry_code 는 영문·숫자 1~20자입니다")
    status = data.get("business_status") or "operating"
    if status not in STATUSES:
        raise BadProfile("business_status 는 operating·planning·exploring 중 하나입니다")
    channels = list(dict.fromkeys(_text(c, "channels", 1, 30) for c in _list(data.get("channels"), "channels", MAX_CHANNELS)))
    return {"v": VERSION, "store_id": store_id, "name": _text(data.get("name"), "name", 1, 30),
            "business_type_name": _text(data.get("business_type_name"), "business_type_name", 1, 30, optional=True) or "",
            "industry_code": industry, "business_status": status, "channels": channels, "menus": _menus(data.get("menus")),
            "location": _location(data.get("location")), "area": _area(data.get("area"))}


def decode(value: str | None) -> dict | None:
    """헤더 값 → 검사한 dict. 값이 없으면 None, 틀리면 BadProfile."""
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > MAX_HEADER:
        raise BadProfile(f"가게 프로필 헤더가 너무 큽니다 ({MAX_HEADER}자까지)")
    if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", value):
        raise BadProfile("가게 프로필 헤더는 base64url 이어야 합니다")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        data = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise BadProfile("가게 프로필 헤더를 읽지 못했습니다") from None
    return check(data)


def district_of(profile: dict) -> str | None:
    """서울 자치구 이름: 등록한 구 → 도로명 주소·위치 이름에서 읽은 구 → None(서울 전체)."""
    location = profile.get("location") or {}
    found = location.get("district_name")
    if found in SEOUL_DISTRICTS:
        return found
    for text in (location.get("road_address"), location.get("label")):
        for word in (text or "").split():
            if word in SEOUL_DISTRICTS:
                return word
    return None


def store_json(profile: dict, channels: tuple[str, ...] = ()) -> dict:
    """리뷰 분석 서비스의 store.json 모양 (합성 가게와 같은 칸). channels 는 아는 채널 코드만 남긴다."""
    names = [CHANNEL_NAMES.get(c.replace(" ", ""), c) for c in profile["channels"]]
    known = list(dict.fromkeys(c for c in names if c in channels)) if channels else []
    return {"store_id": profile["store_id"], "name": profile["name"],
            "business_type": profile["industry_code"] or "registered",
            "business_type_name": profile["business_type_name"] or "음식점",
            "channels": known, "menu": [m["name"] for m in profile["menus"]], "data_origin": "real",
            "registered": True}


class Registry:
    """서비스 프로세스 안의 등록 가게 목록 (가게 id → 검사한 프로필). 크기 상한이 있는 LRU. 스레드 안전."""

    def __init__(self, limit: int = REGISTRY_MAX):
        self.limit = limit
        self._rows: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, profile: dict) -> None:
        with self._lock:
            self._rows[profile["store_id"]] = profile
            self._rows.move_to_end(profile["store_id"])
            while len(self._rows) > self.limit:
                self._rows.popitem(last=False)

    def get(self, store_id: str | None) -> dict | None:
        with self._lock:
            found = self._rows.get(store_id or "")
            if found is not None:
                self._rows.move_to_end(store_id)
            return found

    def __contains__(self, store_id) -> bool:
        return self.get(store_id) is not None

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()
