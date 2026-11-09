"""Offline evidence tests for candidate selection and evening sales snapshots.

The fixed won amounts below were independently summed from the preserved
official source pages. No external account, package, API or model is needed.
Run from the repository root:
    python -B -S -X utf8 -m unittest discover -s tests -p test_c4_evening_sales.py -v
"""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("c4_evening_reproduce", ROOT / "scripts/reproduce_c4_evening_sales.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

AMOUNTS = (
    "TMZON_00_06_SELNG_AMT", "TMZON_06_11_SELNG_AMT",
    "TMZON_11_14_SELNG_AMT", "TMZON_14_17_SELNG_AMT",
    "TMZON_17_21_SELNG_AMT", "TMZON_21_24_SELNG_AMT",
)
EXPECTED_EVENING = {
    "3110826": ((2802261417, 2241971854), (2778386532, 2241971854)),
    "3110827": ((1774728809, 2521264241), (1679062445, 2197002403)),
    "3110830": ((595406498, 490059905), (595406498, 490059905)),
    "3110829": ((23235296, 24503971), (23235296, 24503971)),
    "3110822": ((2957541, 16164067), (2957541, 4889633)),
}


class EveningSalesEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads((ROOT / "data/scenario/evening_sales_2026Q2/source_rows.json").read_text(encoding="utf-8"))

    def calculate(self, source=None):
        return module.calculate(self.source if source is None else source)

    def first_row(self, source):
        return next(row for page in source["source_files"] for row in page["rows"])

    def test_all_five_primary_totals_match_independent_official_sums(self):
        analysis, _ = self.calculate()
        candidates = {item["area_code"]: item for item in analysis["candidates"]}
        self.assertEqual(set(candidates), set(EXPECTED_EVENING))
        for area_code, totals in EXPECTED_EVENING.items():
            for basis, (before, after) in zip(("observed", "common"), totals):
                with self.subTest(area=area_code, basis=basis):
                    item = candidates[area_code][basis]["17_24"]
                    self.assertEqual((item["previous"], item["current"]), (before, after))
                    self.assertEqual(item["absolute_change"], after - before)
                    self.assertAlmostEqual(item["change_percent"], (after - before) / before * 100, places=10)

    def test_evening_is_the_sum_of_both_published_time_bins(self):
        analysis, _ = self.calculate()
        for candidate in analysis["candidates"]:
            for basis in ("observed", "common"):
                for period in ("previous", "current"):
                    with self.subTest(area=candidate["area_code"], basis=basis, period=period):
                        scopes = candidate[basis]
                        self.assertEqual(scopes["17_24"][period], scopes["17_21"][period] + scopes["21_24"][period])
        anchor = next(item for item in analysis["candidates"] if item["area_code"] == "3110826")
        self.assertEqual(anchor["observed"]["17_21"]["previous"], 2047243718)
        self.assertEqual(anchor["observed"]["17_21"]["current"], 1608711501)

    def test_selected_snapshot_uses_common_industries_and_exact_evening_value(self):
        analysis, snapshots = self.calculate()
        self.assertEqual(analysis["selection"]["selected_area_code"], "3110826")
        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[0]
        self.assertEqual(snapshot["area_name"], "장승배기역 4번")
        self.assertAlmostEqual(snapshot["value"], -19.306697315937033, places=10)
        self.assertIn("17", snapshot["metric_name"])
        self.assertIn("24", snapshot["metric_name"])
        self.assertIn("공통", snapshot["metric_name"])
        self.assertEqual(snapshot["unit"], "%")
        self.assertEqual(snapshot["basis_quarter"], "2026Q2")
        self.assertEqual(snapshot["compared_with_quarter"], "2025Q2")
        self.assertIs(snapshot["is_estimate"], True)
        self.assertEqual(set(snapshot), {"snapshot_id", "area_name", "metric_name", "value", "unit", "basis_quarter", "is_estimate", "source", "compared_with_quarter", "note"})

    def test_saved_analysis_and_snapshot_are_reproduced(self):
        analysis, snapshots = self.calculate()
        self.assertEqual(analysis, json.loads((ROOT / "data/scenario/evening_sales_2026Q2/analysis.json").read_text(encoding="utf-8")))
        self.assertEqual(snapshots, json.loads((ROOT / "data/scenario/snapshot_2026Q2.json").read_text(encoding="utf-8")))

    def test_common_basis_does_not_treat_missing_current_industries_as_zero(self):
        analysis, _ = self.calculate()
        anchor = next(item for item in analysis["candidates"] if item["area_code"] == "3110826")
        self.assertNotEqual(anchor["common"]["17_24"]["previous"], anchor["observed"]["17_24"]["previous"])
        self.assertEqual(anchor["common"]["17_24"]["current"], anchor["observed"]["17_24"]["current"])
        before = {row["SVC_INDUTY_CD"] for page in self.source["source_files"] if page["period"] == "20252"
                  for row in page["rows"] if row["TRDAR_CD"] == "3110826"}
        after = {row["SVC_INDUTY_CD"] for page in self.source["source_files"] if page["period"] == "20262"
                 for row in page["rows"] if row["TRDAR_CD"] == "3110826"}
        self.assertEqual((len(before), len(after), len(before & after)), (14, 12, 12))
        self.assertEqual(before - after, {"CS300011", "CS300022"})

    def test_source_inputs_are_not_mutated(self):
        before = copy.deepcopy(self.source)
        self.calculate()
        self.assertEqual(self.source, before)

    def test_duplicate_area_industry_quarter_is_rejected(self):
        changed = copy.deepcopy(self.source)
        page = next(page for page in changed["source_files"] if page["rows"])
        page["rows"].append(copy.deepcopy(page["rows"][0]))
        page["selected_row_count"] = len(page["rows"])
        with self.assertRaises(ValueError):
            self.calculate(changed)

    def test_candidate_order_is_checked_against_metadata_not_sales_outcome(self):
        changed = copy.deepcopy(self.source)
        selection = changed["selection"]
        selection["candidate_codes"][1:3] = reversed(selection["candidate_codes"][1:3])
        selection["candidates"][1:3] = reversed(selection["candidates"][1:3])
        with self.assertRaises(ValueError):
            self.calculate(changed)

    def test_source_page_gap_is_rejected_even_when_candidate_rows_are_unchanged(self):
        changed = copy.deepcopy(self.source)
        empty_page = next(page for page in changed["source_files"] if not page["rows"])
        changed["source_files"].remove(empty_page)
        with self.assertRaises(ValueError):
            self.calculate(changed)

    def test_missing_time_bin_is_rejected(self):
        changed = copy.deepcopy(self.source)
        del self.first_row(changed)["TMZON_21_24_SELNG_AMT"]
        with self.assertRaises(ValueError):
            self.calculate(changed)

    def test_invalid_source_amounts_are_rejected_instead_of_becoming_zero(self):
        for invalid in (None, True, -1, 1.5, "", "NaN"):
            with self.subTest(invalid=invalid):
                changed = copy.deepcopy(self.source)
                self.first_row(changed)["TMZON_17_21_SELNG_AMT"] = invalid
                with self.assertRaises(ValueError):
                    self.calculate(changed)

    def test_unknown_or_mismatched_quarter_is_rejected(self):
        changed = copy.deepcopy(self.source)
        self.first_row(changed)["STDR_YYQU_CD"] = "20261"
        with self.assertRaises(ValueError):
            self.calculate(changed)

    def test_unselected_area_rows_are_rejected(self):
        changed = copy.deepcopy(self.source)
        self.first_row(changed)["TRDAR_CD"] = "3999999"
        with self.assertRaises(ValueError):
            self.calculate(changed)

    def test_six_bins_must_reconcile_to_daily_total(self):
        changed = copy.deepcopy(self.source)
        row = self.first_row(changed)
        row["THSMON_SELNG_AMT"] = int(row["THSMON_SELNG_AMT"]) + 1
        with self.assertRaises(ValueError):
            self.calculate(changed)

    def test_missing_quarter_is_rejected(self):
        changed = copy.deepcopy(self.source)
        changed["source_files"] = [page for page in changed["source_files"] if page["period"] != "20262"]
        with self.assertRaises(ValueError):
            self.calculate(changed)

    def test_zero_previous_sales_is_missing_percentage_not_infinite_decline(self):
        changed = copy.deepcopy(self.source)
        for page in changed["source_files"]:
            if page["period"] != "20252":
                continue
            for row in page["rows"]:
                if row["TRDAR_CD"] == "3110826":
                    for field in AMOUNTS + ("THSMON_SELNG_AMT",):
                        row[field] = 0
        analysis, snapshots = self.calculate(changed)
        anchor = next(item for item in analysis["candidates"] if item["area_code"] == "3110826")
        self.assertIsNone(anchor["common"]["17_24"]["change_percent"])
        self.assertIsNone(anchor["observed"]["17_24"]["change_percent"])
        self.assertNotEqual(analysis["selection"]["selected_area_code"], "3110826")
        self.assertTrue(all(snapshot["value"] is not None for snapshot in snapshots))

    def test_write_refuses_foreign_snapshot_without_changing_either_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data/scenario/evening_sales_2026Q2"
            data.mkdir(parents=True)
            (data / "source_rows.json").write_text(json.dumps(self.source), encoding="utf-8")
            analysis_path = data / "analysis.json"
            snapshot_path = root / "data/scenario/snapshot_2026Q2.json"
            analysis_path.write_text('{"schema_version":"c4-evening-comparison-v1","sentinel":"keep"}', encoding="utf-8")
            snapshot_path.write_text('[{"snapshot_id":"snapshot_from_another_part"}]', encoding="utf-8")
            before = (analysis_path.read_bytes(), snapshot_path.read_bytes())
            with mock.patch.object(module, "ROOT", root), mock.patch.object(module, "DATA", data), mock.patch("sys.argv", ["reproduce", "--write"]):
                with self.assertRaisesRegex(SystemExit, "REFUSING WRITE"):
                    module.main()
            self.assertEqual((analysis_path.read_bytes(), snapshot_path.read_bytes()), before)

    def test_write_refuses_foreign_analysis_without_changing_either_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data/scenario/evening_sales_2026Q2"
            data.mkdir(parents=True)
            (data / "source_rows.json").write_text(json.dumps(self.source), encoding="utf-8")
            analysis_path = data / "analysis.json"
            snapshot_path = root / "data/scenario/snapshot_2026Q2.json"
            analysis_path.write_text('{"schema_version":"another_analysis","sentinel":"keep"}', encoding="utf-8")
            _, snapshots = self.calculate()
            snapshot_path.write_text(json.dumps(snapshots), encoding="utf-8")
            before = (analysis_path.read_bytes(), snapshot_path.read_bytes())
            with mock.patch.object(module, "ROOT", root), mock.patch.object(module, "DATA", data), mock.patch("sys.argv", ["reproduce", "--write"]):
                with self.assertRaisesRegex(SystemExit, "REFUSING WRITE"):
                    module.main()
            self.assertEqual((analysis_path.read_bytes(), snapshot_path.read_bytes()), before)


if __name__ == "__main__":
    unittest.main()
