"""Context periods, evidence and unknown counts survive from saved files to fact cards.

All inputs are synthetic files. No API, model, credentials or user database is used.
"""
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.assistant import context


AREA = "1111111"


class ContextQualityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        blocked = patch("socket.create_connection", side_effect=AssertionError("External calls forbidden"))
        blocked.start()
        self.addCleanup(blocked.stop)
        context._CACHE.clear()
        self.addCleanup(context._CACHE.clear)

    def save(self, name, file_period, row, **metadata):
        document = {"schema": context.SCHEMA, "service": context.DATASETS[name][0], "period": file_period,
                    "row_count": 1, "fetched_at": "2026-11-08T12:00:00+09:00", "rows": {AREA: row}}
        document.update(metadata)
        path = self.folder / f"{name}_{file_period}.json"
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return path

    def table(self, period="20262"):
        return context.area_table(period, folder=self.folder)

    def test_each_source_period_and_file_evidence_survive_to_profile_card(self):
        workers = self.save("workers", "20261", {"TOT_WRC_POPLTN_CO": 500})
        self.save("residents", "20262", {"TOT_REPOP_CO": 100, "TOT_HSHLD_CO": 40})
        self.save("facilities", "20254", {"VIATR_FCLTY_CO": 3})
        figure = {**self.table()[AREA], "name": "시험상권"}
        source = figure["context_sources"]["workers"]
        self.assertEqual(source["period"], "20261")
        self.assertEqual(source["requested_period"], "20262")
        self.assertEqual(source["filename"], workers.name)
        self.assertEqual(source["sha256"], sha256(workers.read_bytes()).hexdigest())
        self.assertEqual(source["fetched_at"], "2026-11-08T12:00:00+09:00")
        card = context.profile_card(figure)
        self.assertEqual(card["source_ref"]["sources"], figure["context_sources"])
        self.assertEqual(card["source_ref"]["requested_period"], "20262")
        values = {value["label"]: value for value in card["values"]}
        self.assertEqual(values["직장인구"]["source_period"], "20261")
        self.assertEqual(values["직장인구"]["source_ref"], source)
        self.assertEqual(values["상주인구"]["source_period"], "20262")
        self.assertEqual(values["집객시설 수"]["source_period"], "20254")
        self.assertEqual(values["직장인구 자료 기준분기"]["value"], "2026년 1분기")
        self.assertIn("직장인구 2026년 1분기", card["text"])
        self.assertIn("집객시설 2025년 4분기", card["text"])
        self.assertIn("선택한 2026년 2분기보다 이전 자료", card["text"])

    def test_exact_period_is_selected_and_future_data_is_never_used(self):
        for period, number in (("20261", 10), ("20262", 20), ("20263", 30)):
            self.save("workers", period, {"TOT_WRC_POPLTN_CO": number})
        figure = self.table()[AREA]
        self.assertEqual(figure["workers"], 20)
        self.assertEqual(figure["context_sources"]["workers"]["period"], "20262")
        self.assertNotIn("이전 자료", context.period_sentence(figure))
        self.assertEqual(self.table("20254"), {})

    def test_requested_period_is_not_leaked_from_the_file_cache(self):
        self.save("workers", "20261", {"TOT_WRC_POPLTN_CO": 10})
        first, second = self.table("20261")[AREA], self.table("20262")[AREA]
        self.assertEqual(first["context_sources"]["workers"]["requested_period"], "20261")
        self.assertEqual(second["context_sources"]["workers"]["requested_period"], "20262")

    def test_legacy_files_use_their_validated_filename_without_inventing_a_fetch_date(self):
        path = self.folder / "workers_20261.json"
        path.write_text(json.dumps({"schema": context.SCHEMA, "rows": {AREA: {"TOT_WRC_POPLTN_CO": 10}}}), encoding="utf-8")
        source = self.table()[AREA]["context_sources"]["workers"]
        self.assertEqual(source["period"], "20261")
        self.assertIsNone(source["fetched_at"])

    def test_malformed_newest_file_does_not_silently_fall_back(self):
        self.save("workers", "20261", {"TOT_WRC_POPLTN_CO": 10})
        path = self.folder / "workers_20262.json"
        path.write_text("{broken", encoding="utf-8")
        self.assertEqual(self.table(), {})

    def test_conflicting_period_or_service_is_not_published(self):
        self.save("workers", "20261", {"TOT_WRC_POPLTN_CO": 10})
        for metadata in ({"period": "20261"}, {"service": "WrongService"}):
            with self.subTest(metadata=metadata):
                self.save("workers", "20262", {"TOT_WRC_POPLTN_CO": 20}, **metadata)
                self.assertEqual(self.table(), {})

    def test_invalid_requested_quarter_does_not_choose_data(self):
        self.save("workers", "20261", {"TOT_WRC_POPLTN_CO": 10})
        for period in (None, "20260", "20265", "2026", 20262):
            with self.subTest(period=period):
                self.assertEqual(self.table(period), {})

    def test_partial_school_and_hospital_counts_remain_unknown_on_the_card(self):
        self.save("facilities", "20262", {"VIATR_FCLTY_CO": 10, "ELESCH_CO": 1,
                                            "MSKUL_CO": 2, "HGSCHL_CO": None, "GEHSPT_CO": 1})
        figure = self.table()[AREA]
        self.assertIsNone(figure["schools"])
        self.assertIsNone(figure["hospitals"])
        labels = {value["label"] for value in context.card_values(figure)}
        self.assertNotIn("초중고 수", labels)
        self.assertNotIn("병원 수", labels)

    def test_complete_school_and_hospital_counts_preserve_observed_zero(self):
        self.save("facilities", "20262", {"ELESCH_CO": 0, "MSKUL_CO": "0.0", "HGSCHL_CO": 0,
                                            "GEHSPT_CO": "2", "GNRL_HSPTL_CO": 3.0})
        figure = self.table()[AREA]
        self.assertEqual(figure["schools"], 0)
        self.assertEqual(figure["hospitals"], 5)
        values = {value["label"]: value["value"] for value in context.card_values(figure)}
        self.assertEqual(values["초중고 수"], 0)

    def test_fractional_invalid_counts_are_not_truncated_or_added_as_zero(self):
        self.save("workers", "20262", {"TOT_WRC_POPLTN_CO": 3.5})
        self.save("residents", "20262", {"TOT_REPOP_CO": "9007199254740993", "TOT_HSHLD_CO": "12.0"})
        self.save("facilities", "20262", {"ELESCH_CO": 1, "MSKUL_CO": 2, "HGSCHL_CO": "3.5",
                                            "GEHSPT_CO": True, "GNRL_HSPTL_CO": 1})
        figure = self.table()[AREA]
        self.assertIsNone(figure["workers"])
        self.assertEqual(figure["residents"], 9007199254740993)
        self.assertEqual(figure["households"], 12)
        self.assertIsNone(figure["schools"])
        self.assertIsNone(figure["hospitals"])
        self.assertNotIn("kind", figure, "unknown workers must not be treated as zero to classify resident demand")

    def test_fractional_average_duration_is_preserved(self):
        self.save("change", "20261", {"OPR_SALE_MT_AVRG": "12.5", "CLS_SALE_MT_AVRG": "15.0"})
        figure = self.table()[AREA]
        self.assertEqual(figure["open_months"], 12.5)
        self.assertEqual(figure["close_months"], 15)
        values = {value["label"]: value for value in context.card_values(figure)}
        self.assertEqual(values["운영 중 가게 평균 영업 기간"]["value"], 12.5)
        self.assertEqual(values["운영 중 가게 평균 영업 기간"]["source_period"], "20261")


if __name__ == "__main__":
    unittest.main()
