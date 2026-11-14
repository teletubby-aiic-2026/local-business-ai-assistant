"""Known-source arithmetic and failure cases, offline with the standard library."""
import copy
import importlib.util
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("c4_reproduce", ROOT / "scripts/reproduce_jangseungbaegi.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = module.load_json(ROOT / "data/scenario/jangseungbaegi_3110826/source_rows.json")

    def test_known_official_totals_and_direction(self):
        analysis, snapshots = module.calculate(self.source)
        expected = [(5417755303, 3903643361), (5352755025, 3870549621), (444715, 378751), (243, 227)]
        for item, (before, after) in zip(analysis["comparison"]["metrics"], expected):
            self.assertEqual((item["previous"], item["current"]), (before, after))
            self.assertEqual(item["absolute_change"], after - before)
            self.assertLess(item["change_percent"], 0)
        self.assertAlmostEqual(snapshots[0]["value"], -27.947219047740735, places=10)
        self.assertEqual(analysis["source_row_count"], 602)
        self.assertEqual(len(analysis["common_sales_industries"]), 11)

    def test_saved_outputs_are_reproduced(self):
        analysis, snapshots = module.calculate(self.source)
        self.assertEqual(analysis, module.load_json(ROOT / "data/scenario/jangseungbaegi_3110826/analysis.json"))
        self.assertEqual(snapshots, module.load_json(ROOT / "data/scenario/jangseungbaegi_3110826/all_day_snapshot_2026Q2.json"))

    def test_missing_is_not_zero(self):
        modified = copy.deepcopy(self.source)
        page = next(p for p in modified["source_files"] if p["dataset"] == "sales")
        page["rows"][0]["THSMON_SELNG_AMT"] = None
        with self.assertRaisesRegex(ValueError, "numeric source"):
            module.calculate(modified)

    def test_duplicate_records_are_rejected(self):
        modified = copy.deepcopy(self.source)
        modified["source_files"][0]["rows"].append(copy.deepcopy(modified["source_files"][0]["rows"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            module.calculate(modified)

    def test_population_missing_quarter_is_rejected(self):
        modified = copy.deepcopy(self.source)
        for page in modified["source_files"]:
            if page["dataset"] == "population" and page["period"] == "20262":
                page["rows"] = []
        with self.assertRaisesRegex(ValueError, "Incomplete quarter"):
            module.calculate(modified)

    def test_store_reconciliation_is_required(self):
        modified = copy.deepcopy(self.source)
        page = next(p for p in modified["source_files"] if p["dataset"] == "stores")
        page["rows"][0]["STOR_CO"] += 1
        with self.assertRaisesRegex(ValueError, "reconcile"):
            module.calculate(modified)

    def test_zero_base_has_no_percentage(self):
        self.assertIsNone(module.change(1, 0))
        self.assertEqual(module.change(0, 1), -100)

    def test_snapshot_scope_and_contract_fields(self):
        _, snapshots = module.calculate(self.source)
        fields = {"snapshot_id", "area_name", "metric_name", "value", "unit", "basis_quarter", "is_estimate", "source", "compared_with_quarter", "note"}
        self.assertEqual(len({x["snapshot_id"] for x in snapshots}), 4)
        for snapshot in snapshots:
            self.assertEqual(set(snapshot), fields)
            self.assertEqual(snapshot["basis_quarter"], "2026Q2")
            self.assertEqual(snapshot["compared_with_quarter"], "2025Q2")
        for snapshot in snapshots[:2]:
            self.assertIn("하루 전체 시간대", snapshot["metric_name"])
            self.assertIn("하루 전체 시간대의 분기 추정매출", snapshot["note"])

    def test_write_preserves_other_team_snapshots_and_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data/scenario/jangseungbaegi_3110826"
            data.mkdir(parents=True)
            (data / "source_rows.json").write_text(json.dumps(self.source), encoding="utf-8")
            analysis_path = data / "analysis.json"
            analysis_path.write_text("existing analysis", encoding="utf-8")
            snapshot_path = data / "all_day_snapshot_2026Q2.json"
            snapshot_path.write_text('[{"snapshot_id":"snap_other_team"}]', encoding="utf-8")
            before_analysis, before_snapshot = analysis_path.read_bytes(), snapshot_path.read_bytes()
            with mock.patch.object(module, "ROOT", root), mock.patch.object(module, "DATA", data), mock.patch("sys.argv", ["reproduce", "--write"]):
                with self.assertRaisesRegex(SystemExit, "REFUSING WRITE"):
                    module.main()
            self.assertEqual(analysis_path.read_bytes(), before_analysis)
            self.assertEqual(snapshot_path.read_bytes(), before_snapshot)


if __name__ == "__main__":
    unittest.main()
