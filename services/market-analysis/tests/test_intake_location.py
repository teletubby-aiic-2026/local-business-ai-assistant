"""Address intake tests use fakes only; no credentials or network requests."""
from copy import deepcopy
import unittest

from app.intake_location import resolve_location
from app.naver_clients import NaverApiError


def address(road="서울특별시 중구 세종대로 110", jibun="서울특별시 중구 태평로1가 31", **extra):
    return {"road_address": road, "jibun_address": jibun,
            "longitude": 126.978, "latitude": 37.566, **extra}


class FakeGeocoder:
    def __init__(self, rows=None, error=None):
        self.rows = [] if rows is None else rows
        self.error, self.calls = error, []

    def geocode(self, text):
        self.calls.append(text)
        if self.error:
            raise self.error
        return deepcopy(self.rows)


class IntakeLocationTests(unittest.TestCase):
    def resolve(self, rows, text="서울 중구 세종대로 110", **extra):
        client = FakeGeocoder(rows)
        return resolve_location({"kind": "address", "text": text, **extra}, client), client

    def test_unique_matching_seoul_address_is_candidate_not_saved_profile(self):
        result, client = self.resolve([address()], longitude=0, latitude=0, confirmed=True)
        self.assertEqual(result["status"], "address_candidate")
        self.assertTrue(result["verified_seoul"])
        self.assertEqual(result["candidates"][0]["longitude"], 126.978)
        self.assertEqual(set(result), {"status", "candidates", "verified_seoul", "question"})
        self.assertIn("확인", result["question"])
        self.assertEqual(client.calls, ["서울 중구 세종대로 110"])

    def test_lot_address_and_compact_road_number_match(self):
        for text in ("서울 중구 태평로1가 31", "서울 중구 세종대로110"):
            with self.subTest(text=text):
                result, _ = self.resolve([address()], text)
                self.assertEqual(result["status"], "address_candidate")

    def test_underground_road_address_matches_with_optional_spacing(self):
        official = "서울특별시 종로구 사직로 지하130"
        for text in ("서울 종로구 사직로 지하130", "서울 종로구 사직로 지하 130", "서울 종로구 사직로지하130"):
            with self.subTest(text=text):
                result, client = self.resolve([address(official, "")], text)
                self.assertEqual(result["status"], "address_candidate")
                self.assertEqual(result["candidates"][0]["road_address"], official)
                self.assertEqual(client.calls, [text])

    def test_underground_and_ground_addresses_with_same_number_never_match(self):
        pairs = (("서울 종로구 사직로 지하130", "서울특별시 종로구 사직로 130"),
                 ("서울 종로구 사직로 130", "서울특별시 종로구 사직로 지하130"))
        for text, official in pairs:
            with self.subTest(text=text, official=official):
                result, client = self.resolve([address(official, "")], text)
                self.assertEqual(result["status"], "needs_precision")
                self.assertFalse(result["verified_seoul"])
                self.assertEqual(result["candidates"], [])
                self.assertEqual(client.calls, [text])

    def test_underground_subnumber_is_preserved(self):
        for road, expected in (("서울특별시 종로구 사직로 지하130-2", "address_candidate"),
                               ("서울특별시 종로구 사직로 지하130", "needs_precision"),
                               ("서울특별시 종로구 사직로 지하130-3", "needs_precision")):
            with self.subTest(road=road):
                result, _ = self.resolve([address(road, "")], "서울 종로구 사직로 지하130-2")
                self.assertEqual(result["status"], expected)

    def test_mountain_lot_designation_and_subnumber_remain_distinct(self):
        for official, expected in (("서울특별시 강북구 수유동 산12-3", "address_candidate"),
                                   ("서울특별시 강북구 수유동 12-3", "needs_precision"),
                                   ("서울특별시 강북구 수유동 산12", "needs_precision")):
            with self.subTest(official=official):
                result, _ = self.resolve([address("", official)], "서울 강북구 수유동 산 12-3")
                self.assertEqual(result["status"], expected)

    def test_near_seoul_address_verifies_only_a_reference_point(self):
        result, _ = self.resolve([address()], "서울 중구 세종대로 110 근처", relation="near")
        self.assertEqual(result["status"], "needs_precision")
        self.assertFalse(result["verified_seoul"])
        self.assertEqual(result["verification_scope"], "reference_point")
        self.assertTrue(result["candidates"][0]["in_seoul"])
        self.assertIn("실제 사업 위치", result["question"])

    def test_near_non_seoul_reference_does_not_prove_business_outside_seoul(self):
        result, _ = self.resolve([address("경기도 중앙로 10", "")], "경기도 중앙로 10 근처", relation="near")
        self.assertEqual(result["status"], "needs_precision")
        self.assertFalse(result["verified_seoul"])
        self.assertEqual(result["verification_scope"], "reference_point")
        self.assertFalse(result["candidates"][0]["in_seoul"])

    def test_multiple_near_address_candidates_still_need_actual_location(self):
        result, _ = self.resolve([address(), address("서울특별시 종로구 세종대로 110", "")], "세종대로 110 주변", relation="near")
        self.assertEqual(result["status"], "needs_precision")
        self.assertFalse(result["verified_seoul"])
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(result["verification_scope"], "reference_point")

    def test_explicit_exact_address_preserves_candidate_behavior(self):
        result, _ = self.resolve([address()], relation="exact")
        self.assertEqual(result["status"], "address_candidate")
        self.assertTrue(result["verified_seoul"])
        self.assertNotIn("verification_scope", result)

    def test_identical_duplicates_do_not_create_extra_candidate(self):
        result, _ = self.resolve([address(), address()])
        self.assertEqual(result["status"], "address_candidate")
        self.assertEqual(len(result["candidates"]), 1)

    def test_multiple_matching_candidates_require_selection(self):
        result, _ = self.resolve([address(), address("서울특별시 종로구 세종대로 110", "")], "세종대로 110")
        self.assertEqual(result["status"], "choose_candidate")
        self.assertFalse(result["verified_seoul"])
        self.assertEqual(len(result["candidates"]), 2)

    def test_clear_non_seoul_prefixes_are_outside(self):
        for prefix in ("경기도", "부산광역시", "제주특별자치도", "전북특별자치도"):
            with self.subTest(prefix=prefix):
                result, _ = self.resolve([address(prefix + " 중앙로 10", "")], "중앙로 10")
                self.assertEqual(result["status"], "outside_seoul")
                self.assertFalse(result["verified_seoul"])

    def test_seoul_and_non_seoul_candidates_are_not_automatically_selected(self):
        result, _ = self.resolve([address("서울특별시 중구 중앙로 10", ""), address("경기도 수원시 중앙로 10", "")], "중앙로 10")
        self.assertEqual(result["status"], "choose_candidate")
        self.assertEqual([row["in_seoul"] for row in result["candidates"]], [True, False])

    def test_unknown_region_is_not_called_outside_seoul(self):
        result, _ = self.resolve([address("중구 세종대로 110", "")], "세종대로 110")
        self.assertEqual(result["status"], "needs_precision")
        self.assertFalse(result["verified_seoul"])
        result, _ = self.resolve([address("중구 세종대로 110", ""), address("경기도 세종대로 110", "")], "세종대로 110")
        self.assertEqual(result["status"], "choose_candidate")

    def test_conflicting_provider_regions_are_ambiguous(self):
        result, _ = self.resolve([address(jibun="경기도 태평로1가 31")])
        self.assertEqual(result["status"], "needs_precision")
        self.assertFalse(result["verified_seoul"])

    def test_unknown_unmatched_result_prevents_definitive_outside_judgment(self):
        result, _ = self.resolve([address("경기도 세종대로 110", ""), address("세종대로 112", "")], "세종대로 110")
        self.assertEqual(result["status"], "needs_precision")
        self.assertFalse(result["verified_seoul"])

    def test_no_results_and_provider_failure_are_distinct(self):
        result, _ = self.resolve([])
        self.assertEqual(result["status"], "not_found")
        client = FakeGeocoder(error=NaverApiError("SECRET_PROVIDER_DETAIL", 429))
        result = resolve_location({"kind": "address", "text": "세종대로 110"}, client)
        self.assertEqual(result["status"], "lookup_unavailable")
        self.assertNotIn("SECRET", str(result))

    def test_station_area_and_landmark_do_not_geocode_or_invent_coordinates(self):
        for kind, text in (("station", "성수역"), ("area", "홍대 쪽"), ("landmark", "서울시청"), ("unknown", "서울")):
            with self.subTest(kind=kind):
                client = FakeGeocoder([address()])
                result = resolve_location({"kind": kind, "text": text, "longitude": 127, "latitude": 37.5}, client)
                self.assertEqual(result["status"], "needs_precision")
                self.assertEqual(result["candidates"], [])
                self.assertFalse(result["verified_seoul"])
                self.assertEqual(client.calls, [])

    def test_incomplete_query_does_not_start_lookup(self):
        for text in ("서울 중구", "서울 중구 세종대로", "서울 중구 세종대로 110 또는 112"):
            client = FakeGeocoder([address()])
            result = resolve_location({"kind": "address", "text": text}, client)
            self.assertEqual(result["status"], "needs_precision")
            self.assertEqual(client.calls, [])

    def test_partial_or_different_number_never_confidently_matches(self):
        for road in ("서울특별시 중구 세종대로", "서울특별시 중구 세종대로 112", "서울특별시 중구 세종대로 110-1", "서울특별시 중구 을지로 110", "서울특별시 강남구 세종대로 110"):
            with self.subTest(road=road):
                result, _ = self.resolve([address(road, "")])
                self.assertEqual(result["status"], "needs_precision")
                self.assertFalse(result["verified_seoul"])
                self.assertEqual(result["candidates"], [])

    def test_subnumber_is_part_of_identity(self):
        for road, expected in (("서울특별시 성동구 왕십리로 83-21", "address_candidate"), ("서울특별시 성동구 왕십리로 83-2", "needs_precision"), ("서울특별시 성동구 왕십리로 83", "needs_precision")):
            with self.subTest(road=road):
                result, _ = self.resolve([address(road, "")], "서울 성동구 왕십리로 83-21")
                self.assertEqual(result["status"], expected)

    def test_explicit_region_cannot_be_replaced_by_different_region(self):
        result, _ = self.resolve([address("서울특별시 중구 중앙로 10", "")], "부산 중구 중앙로 10")
        self.assertEqual(result["status"], "needs_precision")

    def test_invalid_provider_data_fails_without_returning_coordinates(self):
        for rows in ({}, [address(latitude=True)], [address(longitude=float("nan"))], [address(road="", jibun="")], [None]):
            with self.subTest(rows=rows):
                result, _ = self.resolve(rows)
                self.assertEqual(result["status"], "lookup_unavailable")
                self.assertEqual(result["candidates"], [])

    def test_invalid_input_never_calls_provider(self):
        for value in (None, {}, {"kind": "address", "text": 42}, {"kind": "address", "text": "세종대로 110\n"}):
            client = FakeGeocoder([address()])
            result = resolve_location(value, client)
            self.assertEqual(result["status"], "needs_precision")
            self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
