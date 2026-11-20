"""shared/store_header.py — 등록 가게 프로필 헤더 (6차 회의 11/20). 네트워크 없음.

실행 (저장소 루트에서):  PYTHONPATH=. python -m pytest -q tests/test_store_header.py
"""
import base64
import json

import pytest

from shared import store_header, store_profiles

ROW = {"store_id": "store_0123456789ab", "owner_user_id": "u1", "name": "우리분식", "business_type_name": "분식전문점",
       "profile": {"industry_code": "CS100002", "business_status": "planning", "channels": ["배달의민족", "쿠팡이츠"],
                   "location": {"kind": "address", "label": "서울 관악구 관악로 1", "road_address": "서울특별시 관악구 관악로 1",
                                "latitude": 37.48, "longitude": 126.95, "station_id": None, "station_name": None,
                                "district_name": None},
                   "area": {"area_code": "3120001", "name": "서울대입구역", "period": None},
                   "menus": [{"name": f"메뉴{i}" * 6, "price": 999_999} for i in range(30)]}}


def _raw(data) -> str:
    return base64.urlsafe_b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()


def test_round_trip_of_a_full_registered_store_fits_the_limit():
    bundle = store_profiles.registered_bundle(ROW)
    value = store_header.encode(store_header.payload(bundle))
    assert len(value) < store_header.MAX_HEADER
    got = store_header.decode(value)
    assert got["store_id"] == ROW["store_id"] and got["name"] == "우리분식"
    assert got["business_status"] == "planning" and got["area"] == {"area_code": "3120001", "name": "서울대입구역", "period": None}
    assert len(got["menus"]) == 30 and got["menus"][0]["price"] == 999_999
    assert store_header.decode(value + "==") == got                     # 패딩이 있어도 같다
    assert store_header.district_of(got) == "관악구"                     # 구가 없으면 도로명 주소에서 읽는다


def test_sample_stores_never_get_a_header():
    for sid in store_profiles.STORE_IDS:
        assert store_header.headers_for(sid) == {}
    assert store_header.headers_for(None) == {} and store_header.headers_for("store_unknown") == {}
    with pytest.raises(ValueError):
        store_header.payload(store_profiles.BUNDLES["store_ongi"])


@pytest.mark.parametrize("data", [
    {"v": 1, "store_id": "store_ongi", "name": "온기"},                  # 예시 가게 id
    {"v": 1, "store_id": "store_0123456789AB", "name": "x"},
    {"v": 1, "store_id": "store_0123456789ab", "name": "x" * 31},
    {"v": 1, "store_id": "store_0123456789ab", "name": "a\nb"},
    {"v": 1, "store_id": "store_0123456789ab", "name": "x", "channels": ["a"] * 7},
    {"v": 1, "store_id": "store_0123456789ab", "name": "x", "menus": [{"name": "a", "price": True}]},
    {"v": 1, "store_id": "store_0123456789ab", "name": "x", "location": {"kind": "area"}},
    {"v": 1, "store_id": "store_0123456789ab", "name": "x", "location": {"station_id": "a/b"}},
    {"v": 1, "store_id": "store_0123456789ab", "name": "x", "area": {"period": "2026Q2"}},
    {"v": 1, "store_id": "store_0123456789ab", "name": "x", "industry_code": "CS 1"},
    {"v": 1, "store_id": "store_0123456789ab", "name": "x", "business_status": "closed"},
    {"store_id": "store_0123456789ab", "name": "x"},
])
def test_bad_fields_are_refused(data):
    with pytest.raises(store_header.BadProfile):
        store_header.decode(_raw(data))


def test_bad_shapes_and_size_are_refused():
    for value in ("@@@", "A" * (store_header.MAX_HEADER + 1), base64.urlsafe_b64encode(b"\xff\xfe").decode(), _raw([1])):
        with pytest.raises(store_header.BadProfile):
            store_header.decode(value)
    assert store_header.decode(None) is None and store_header.decode("") is None


def test_store_json_maps_channel_names_and_keeps_menu_order():
    got = store_header.decode(_raw({"v": 1, "store_id": "store_0123456789ab", "name": "가게", "channels": ["배달의민족", "요기요", "땡겨요"],
                                    "menus": [{"name": "b", "price": 1}, {"name": "a", "price": 2}]}))
    data = store_header.store_json(got, ("baemin", "coupangeats", "yogiyo", "naver_place"))
    assert data["channels"] == ["baemin", "yogiyo"] and data["menu"] == ["b", "a"]
    assert data["business_type"] == "registered" and data["business_type_name"] == "음식점"


def test_district_falls_back_to_none_for_seoul_wide():
    assert store_header.district_of({"location": {"district_name": "동작구"}}) == "동작구"
    assert store_header.district_of({"location": {"district_name": "수원시"}}) is None
    assert store_header.district_of({"location": {"label": "판교역"}}) is None


def test_registry_is_a_bounded_lru():
    reg = store_header.Registry(limit=2)
    for i in range(3):
        reg.put({"store_id": f"store_00000000000{i}"})
    assert "store_000000000000" not in reg and "store_000000000002" in reg
    reg.get("store_000000000001")
    reg.put({"store_id": "store_000000000003"})
    assert "store_000000000001" in reg and "store_000000000002" not in reg
