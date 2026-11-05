"""B2 oracle computed directly from official files, independently of app math.

No legacy app import, persistent database, settings or provider calls. Pure-row
coverage spans all industries/quarters and every observed highest-value tie.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import unittest

from app.onboarding_sales import analyze_sales_row, build_sales_analysis
from tests.official_source_oracle import get_oracle, HISTORICAL_PERIODS


ROOT = Path(__file__).resolve().parents[1]
TOTAL = "THSMON_SELNG_AMT"
GROUPS = {
    "weekday": [(label, field + "_SELNG_AMT") for label, field in
                zip(("월", "화", "수", "목", "금", "토", "일"), ("MON", "TUES", "WED", "THUR", "FRI", "SAT", "SUN"))],
    "time": [(label, "TMZON_" + field + "_SELNG_AMT") for label, field in
             zip(("00~06시", "06~11시", "11~14시", "14~17시", "17~21시", "21~24시"),
                 ("00_06", "06_11", "11_14", "14_17", "17_21", "21_24"))],
    "age": [(label, "AGRDE_" + field + "_SELNG_AMT") for label, field in
            zip(("10대", "20대", "30대", "40대", "50대", "60대 이상"), ("10", "20", "30", "40", "50", "60_ABOVE"))],
}
IDENTITY = ("TRDAR_CD", "TRDAR_CD_NM", "SVC_INDUTY_CD", "SVC_INDUTY_CD_NM", "STDR_YYQU_CD")
FIELDS = [TOTAL] + [field for fields in GROUPS.values() for _, field in fields]
SOURCE_URL = "https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do"


def percent_oracle(value, denominator):
    if denominator == 0:
        return None
    # Integer quotient/remainder, not the implementation's Decimal helper.
    quotient, remainder = divmod(int(value) * 10000, int(denominator))
    return (quotient + (2 * remainder >= denominator)) / 100


class IndependentSalesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.oracle = get_oracle()
        cls.version = cls.oracle.version
        cls.rows, cls.proof = cls.oracle.rows["sales"], cls.oracle.proof["sales"]
        cls.buckets = defaultdict(list)
        for key in cls.rows:
            cls.buckets[(key[1], key[2])].append(key)
        keys = set()
        for bucket in cls.buckets.values():
            ordered = sorted(bucket)
            keys.update((ordered[0], ordered[len(ordered) // 2], ordered[-1]))
        for key, row in cls.rows.items():
            totals = {kind: [int(row[field]) for _, field in fields] for kind, fields in GROUPS.items()}
            if (any(values.count(max(values)) > 1 for values in totals.values())
                    or sum(totals["age"]) > row[TOTAL]
                    or sum(totals["age"]) * 1000 < row[TOTAL]):
                keys.add(key)
        cls.selected_keys = sorted(keys)

    @classmethod
    def selection(cls, row):
        period = row["STDR_YYQU_CD"]
        return {"area_code": row["TRDAR_CD"], "area_name": row["TRDAR_CD_NM"],
                "industry_code": row["SVC_INDUTY_CD"], "period": period,
                "period_label": f"{period[:4]}년 {period[-1]}분기", "catalog_version": cls.version,
                "boundary": {"publication_date": "2023-10-23", "compatibility": "unverified"}}

    def assert_actual_row(self, row, actual):
        total = int(row[TOTAL])
        self.assertEqual(actual["status"], "available")
        self.assertEqual(actual["total"]["value"], total)
        self.assertEqual(actual["total"]["value_text"], str(total))
        self.assertEqual(actual["total"]["unit"], "원")
        self.assertEqual(actual["selection"]["industry_code"], row["SVC_INDUTY_CD"])
        for kind, fields in GROUPS.items():
            with self.subTest(distribution=kind):
                group = actual["distributions"][kind]
                values = [int(row[field]) for _, field in fields]
                subtotal = sum(values)
                safe = subtotal <= total if kind == "age" else subtotal == total
                denominator = subtotal if kind == "age" else total
                self.assertEqual(group["sum"], subtotal)
                self.assertEqual(group["total_difference"], subtotal - total)
                self.assertEqual(group["denominator"]["value"], denominator)
                self.assertEqual(group["denominator"]["kind"], "age_classified_total" if kind == "age" else "quarter_total")
                self.assertEqual(group["status"], "complete" if safe else "inconsistent")
                self.assertEqual([(item["label"], item["field"]) for item in group["items"]], fields)
                for item, value in zip(group["items"], values):
                    self.assertEqual(item["value"], value)
                    self.assertEqual(item["value_text"], str(value))
                    self.assertEqual(item["status"], "available")
                    self.assertEqual(item["share_percent"], percent_oracle(value, denominator) if safe else None)
                if safe:
                    self.assertEqual(group["ranking"]["status"], "available")
                    self.assertEqual(group["ranking"]["highest"], [fields[index][0] for index, value in enumerate(values) if value == max(values)])
                    self.assertEqual(group["ranking"]["lowest"], [fields[index][0] for index, value in enumerate(values) if value == min(values)])
                    self.assertEqual(group["ranking"]["highest_value"], max(values))
                    self.assertEqual(group["ranking"]["lowest_value"], min(values))
                else:
                    self.assertEqual(group["ranking"]["status"], "unavailable")
                    self.assertEqual(group["ranking"]["highest"], [])
                    self.assertEqual(group["ranking"]["lowest"], [])
                if kind == "age":
                    self.assertEqual(group["classified_share_of_total_percent"], percent_oracle(subtotal, total))

    def test_independent_all_source_distribution_audit(self):
        historical = self.rows.subset(periods=HISTORICAL_PERIODS)
        self.assertEqual(len(historical), 63773)
        self.assertEqual(len({(key[1], key[2]) for key in historical}), 62 * 3)
        counts = {kind: Counter() for kind in GROUPS}
        self.assertEqual(Counter(key[2] for key in historical), {"20252": 21452, "20261": 21188, "20262": 21133})
        for row in historical.values():
            self.assertGreater(row[TOTAL], 0)
            for kind, fields in GROUPS.items():
                values = [row[field] for _, field in fields]
                self.assertTrue(all(type(value) in (int, float) and value >= 0 and value % 1 == 0 for value in values))
                difference = sum(values) - row[TOTAL]
                counts[kind]["equal"] += difference == 0
                counts[kind]["below"] += difference < 0
                counts[kind]["above"] += difference > 0
                counts[kind]["zero_items"] += values.count(0)
                counts[kind]["highest_tie"] += values.count(max(values)) > 1
        self.assertEqual(dict(counts["weekday"]), {"equal": 63773, "below": 0, "above": 0, "zero_items": 41077, "highest_tie": 220})
        self.assertEqual(dict(counts["time"]), {"equal": 63773, "below": 0, "above": 0, "zero_items": 89037, "highest_tie": 117})
        self.assertEqual(dict(counts["age"]), {"equal": 26810, "below": 36913, "above": 50, "zero_items": 61129, "highest_tie": 85})

    def test_diverse_real_rows_match_independent_values_sums_shares_and_ties(self):
        self.assertGreaterEqual(len(self.selected_keys), 900)
        for key in self.selected_keys:
            with self.subTest(area=key[0], industry=key[1], period=key[2]):
                row = self.rows[key]
                actual = analyze_sales_row(row, self.selection(row), row["SVC_INDUTY_CD_NM"])
                self.assert_actual_row(row, actual)

    def test_file_loader_all_industries_and_quarters_keep_exact_evidence(self):
        for (industry, period), keys in sorted(self.buckets.items(), key=lambda item: (item[0][1], item[0][0])):
            key = sorted(keys)[0]
            with self.subTest(industry=industry, period=period):
                row = self.rows[key]
                result = build_sales_analysis(self.selection(row), {"industry": {"code": industry, "name": row["SVC_INDUTY_CD_NM"]}})
                self.assert_actual_row(row, result)
                evidence = result["evidence"]
                self.assertEqual(len(evidence), 1)
                self.assertEqual((evidence[0]["file_name"], evidence[0]["file_sha256"], evidence[0]["payload_sha256"]), self.proof[key])
                self.assertEqual(set(evidence[0]["fields"]), set(FIELDS))
                self.assertEqual(result["source"]["url"], SOURCE_URL)
                self.assertEqual(result["source"]["period_basis"], "quarter")

    def test_tiny_age_coverage_is_not_total_sales_customer_share(self):
        row = self.rows[("3110774", "CS300009", "20261")]
        result = analyze_sales_row(row, self.selection(row), row["SVC_INDUTY_CD_NM"])
        age = result["distributions"]["age"]
        self.assertEqual(result["total"]["value"], 645273371)
        self.assertEqual(age["sum"], 41799)
        self.assertEqual(age["denominator"]["kind"], "age_classified_total")
        self.assertEqual(age["classified_share_of_total_percent"], 0.01)
        self.assertEqual(age["items"][4]["share_percent"], 100)
        self.assertTrue(any("일반화" in warning for warning in age["warnings"]))

    def test_actual_absent_area_industry_rows_remain_null_in_all_quarters(self):
        areas = sorted({key[0] for key in self.rows} - {"3110024", "3110379"})
        code = next(area for area in areas if all((area, "CS300002", period) not in self.rows for period in ("20252", "20261", "20262")))
        exemplar = next(row for row in self.rows.values() if row["TRDAR_CD"] == code)
        for industry, name in (("CS300002", "편의점"), ("CS200041", "사진관")):
            for period in ("20252", "20261", "20262"):
                with self.subTest(area=code, industry=industry, period=period):
                    self.assertNotIn((code, industry, period), self.rows)
                    row = {**exemplar, "SVC_INDUTY_CD": industry, "SVC_INDUTY_CD_NM": name, "STDR_YYQU_CD": period}
                    result = build_sales_analysis(self.selection(row), {"industry": {"code": industry, "name": name}})
                    self.assertEqual(result["status"], "no_data")
                    self.assertIsNone(result["total"]["value"])
                    self.assertEqual(len(result["evidence"]), sum(entry["dataset"] == "sales" and entry["period"] == period for entry in self.oracle.files))
                    for group in result["distributions"].values():
                        self.assertEqual(group["status"], "no_data")
                        self.assertTrue(all(item["value"] is None and item["share_percent"] is None for item in group["items"]))

    def test_missing_and_zero_synthetic_cases_do_not_invent_shares(self):
        original = self.rows[self.selected_keys[0]]
        selection = self.selection(original)
        missing = analyze_sales_row(None, selection, original["SVC_INDUTY_CD_NM"])
        self.assertEqual(missing["status"], "no_data")
        self.assertIsNone(missing["total"]["value"])
        for group in missing["distributions"].values():
            self.assertEqual(group["ranking"]["status"], "unavailable")
            self.assertTrue(all(item["value"] is None and item["share_percent"] is None for item in group["items"]))
        zeros = {**original, **dict.fromkeys(FIELDS, 0)}
        result = analyze_sales_row(zeros, selection, original["SVC_INDUTY_CD_NM"])
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["total"]["value"], 0)
        for kind, group in result["distributions"].items():
            self.assertTrue(all(item["value"] == 0 and item["share_percent"] is None for item in group["items"]))
            self.assertEqual(group["ranking"]["highest"], [label for label, _ in GROUPS[kind]])
            self.assertEqual(group["ranking"]["lowest"], [label for label, _ in GROUPS[kind]])
        partial = deepcopy(original)
        partial[GROUPS["weekday"][0][1]] = None
        result = analyze_sales_row(partial, selection, original["SVC_INDUTY_CD_NM"])
        self.assertEqual(result["distributions"]["weekday"]["status"], "partial")
        self.assertTrue(all(item["share_percent"] is None for item in result["distributions"]["weekday"]["items"]))
        self.assertEqual(result["distributions"]["weekday"]["ranking"]["highest"], [])


if __name__ == "__main__":
    unittest.main()
