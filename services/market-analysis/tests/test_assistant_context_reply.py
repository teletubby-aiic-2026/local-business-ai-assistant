"""Dataset quarters must survive both fixed answers and the model-writing boundary."""
import unittest
from unittest.mock import Mock

from app.assistant import context
from app.assistant.answer_check import check_answer, feedback
from app.assistant.flow import AssistantService


def _figure(name="시험상권"):
    return {"name": name, "workers": 5000, "residents": 900,
            "context_requested_period": "20262", "context_sources": {
                dataset: {"dataset": dataset, "period": period, "requested_period": "20262",
                          "service": context.DATASETS[dataset][0], "filename": f"{dataset}_{period}.json"}
                for dataset, period in (("workers", "20261"), ("residents", "20262"))}}


def _card(figure=None, topic="area_profile"):
    card = context.profile_card(figure or _figure())
    return {**card, "id": "F1", "topic": topic}


class ContextReplyTests(unittest.TestCase):
    def test_facility_fallback_answers_requested_counts_including_zero(self):
        figure = {**_figure(), "schools": 0, "hospitals": 2, "university": 1}
        card = _card(figure)
        service = AssistantService.__new__(AssistantService)
        service.writer = None
        reply = service._write([card], {"text": "집객시설 중 초중고와 병원 수 알려줘"})
        final = service._finish(reply, {}, cards=[card])
        self.assertIn("초중고 수는 0개로 집계", final["reply"]["text"])
        self.assertIn("병원 수는 2개로 집계", final["reply"]["text"])
        self.assertIn("직장인구 5,000명", final["reply"]["text"])

    def test_facility_focus_preserves_requested_worker_count(self):
        card = _card({**_figure(), "hospitals": 2})
        service = AssistantService.__new__(AssistantService)
        service.writer = None
        reply = service._write([card], {"text": "직장인구와 병원 수 알려줘"})
        self.assertIn("병원 수는 2개로 집계", reply["text"])
        self.assertIn("직장인구 5,000명", reply["text"])

    def test_school_focus_preserves_requested_change_and_duration(self):
        card = _card({**_figure(), "schools": 0, "change_name": "다이나믹",
                      "open_months": 109, "seoul_open_months": 118})
        service = AssistantService.__new__(AssistantService)
        service.writer = Mock(side_effect=RuntimeError("synthetic model failure"))
        reply = service._write([card], {"text": "학교 수와 상권 변화 지표, 평균 영업 기간을 알려줘"})
        self.assertIn("초중고 수는 0개로 집계", reply["text"])
        self.assertIn("다이나믹", reply["text"])
        self.assertIn("109개월", reply["text"])
        self.assertIn("서울 평균은 118개월", reply["text"])

    def test_facility_fallback_distinguishes_unknown_from_observed_zero(self):
        card = _card({**_figure(), "schools": None, "hospitals": 0})
        service = AssistantService.__new__(AssistantService)
        service.writer = Mock(side_effect=RuntimeError("synthetic model failure"))
        reply = service._write([card], {"text": "집객시설 중 학교와 병원 수 알려줘"})
        self.assertIn("초중고 수는 자료에서 확인하지 못했어요", reply["text"])
        self.assertNotIn("초중고 수는 0", reply["text"])
        self.assertIn("병원 수는 0개로 집계", reply["text"])

    def test_university_question_does_not_request_school_total(self):
        card = _card({**_figure(), "schools": 0, "university": 1})
        service = AssistantService.__new__(AssistantService)
        service.writer = None
        reply = service._write([card], {"text": "집객시설 중 대학교 수는?"})
        self.assertIn("대학교 수는 1개로 집계", reply["text"])
        self.assertNotIn("초중고 수", reply["text"])

    def test_model_answer_cannot_omit_actual_source_quarters(self):
        card = _card()
        service = AssistantService.__new__(AssistantService)
        service.writer = Mock(return_value="시험상권의 직장인구는 5,000명입니다. [F1]")
        reply = service._write([card], {"text": "근처 직장인구는?"})
        self.assertTrue(reply["model_used"])
        final = service._finish(reply, {}, cards=[card])
        note = context.period_sentence(_figure())
        self.assertIn(note, final["reply"]["text"])
        self.assertIn(note, final["reply"]["notes"])
        self.assertIn("선택한 2026년 2분기보다 이전 자료", final["reply"]["text"])

    def test_fixed_answer_note_is_not_duplicated(self):
        card = _card()
        service = AssistantService.__new__(AssistantService)
        service.writer = None
        reply = service._write([card], {"text": "직장인구는?"})
        result = service._finish(reply, {}, cards=[card])
        note = context.period_sentence(_figure())
        self.assertEqual(result["reply"]["text"].count("입지 자료 기준분기:"), 1)
        self.assertEqual(result["reply"]["notes"].count(note), 1)

    def test_opinion_cards_preserve_separate_markets_and_dataset_quarters(self):
        first, second = _figure(), _figure("두번째상권")
        second["context_sources"]["workers"]["period"] = "20254"
        cards = [_card(first, "opinion"), {**_card(second, "opinion"), "id": "F2"}]
        result = AssistantService._finish({"text": "입지 자료를 비교했습니다."}, {}, cards=cards)
        for figure in (first, second):
            self.assertIn(context.period_sentence(figure), result["reply"]["text"])
        self.assertEqual(len(result["reply"]["notes"]), 2)

    def test_unrelated_cards_do_not_gain_context_dates(self):
        result = AssistantService._finish({"text": "분기 매출입니다."}, {}, cards=[{
            "id": "F1", "topic": "sales_total", "values": [{"label": "매출", "value": 1}]}])
        self.assertEqual(result["reply"]["text"], "분기 매출입니다.")
        self.assertEqual(result["reply"]["notes"], [])

    def test_current_quarter_cannot_be_assigned_to_older_workers(self):
        card = _card()
        result = check_answer("2026년 2분기 시험상권의 직장인구는 5,000명입니다. [F1]", [card])
        self.assertFalse(result["ok"])
        mismatches = [p for p in result["problems"] if p["type"] == "context_period_mismatch"]
        self.assertEqual(len(mismatches), 1)
        self.assertIn("직장인구: 2026년 1분기", mismatches[0]["detail"])
        self.assertIn("각 자료의 실제 기준분기", feedback(mismatches))

    def test_actual_source_quarter_is_accepted_including_korean_numeric_units(self):
        for text in ("2026년 1분기 시험상권의 직장인구는 5,000명입니다. [F1]",
                     "2026년 1분기 시험상권의 직장 인구는 0.5만 명입니다. [F1]",
                     "2026년 2분기 시험상권의 상주인구는 900명입니다. [F1]"):
            with self.subTest(text=text):
                result = check_answer(text, [_card()])
                self.assertTrue(result["ok"], result["problems"])

    def test_two_metrics_cannot_swap_their_source_quarters(self):
        text = "2026년 2분기 직장인구는 5,000명이고 2026년 1분기 상주인구는 900명입니다. [F1]"
        result = check_answer(text, [_card()])
        self.assertEqual(len([p for p in result["problems"] if p["type"] == "context_period_mismatch"]), 2)

    def test_explaining_missing_current_data_and_older_data_is_allowed(self):
        text = "2026년 2분기 직장인구 자료는 없고, 이전 분기 값은 5,000명입니다. [F1]"
        result = check_answer(text, [_card()])
        self.assertTrue(result["ok"], result["problems"])

    def test_wrong_source_quarter_retries_then_falls_back(self):
        card = _card()
        service = AssistantService.__new__(AssistantService)
        service.writer = Mock(return_value="2026년 2분기 직장인구는 5,000명입니다. [F1]")
        reply = service._write([card], {"text": "직장인구를 알려줘"})
        self.assertFalse(reply["model_used"])
        self.assertEqual(service.writer.call_count, 2)
        self.assertIn("context_period_mismatch", {p["type"] for p in reply["model_rejected"]})
        final = service._finish(reply, {}, cards=[card])
        self.assertIn("직장인구 2026년 1분기", final["reply"]["text"])


if __name__ == "__main__":
    unittest.main()
