"""GET /api/onboarding/area-context (5차 회의 11/18): 고른 상권의 직장인구·상주인구·세대·집객시설·상권 변화.

챗봇과 같은 출처 확인 파일(data/assistant_context)을 임시 폴더로 바꿔 시험한다. 네트워크·공식 원본 없이 돈다.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.assistant import context
from tests import test_onboarding_analysis as setup_helpers

AREA = "1111111"


def write_context(folder: Path, period="20262", area=AREA):
    rows = {
        "workers": {area: {"TOT_WRC_POPLTN_CO": "489"}},
        "residents": {area: {"TOT_REPOP_CO": "4347", "TOT_HSHLD_CO": "2762"}},
        "facilities": {area: {"VIATR_FCLTY_CO": "18", "SUBWAY_STATN_CO": "0", "BUS_STTN_CO": "5", "UNIV_CO": "0",
                              "GEHSPT_CO": "1", "GNRL_HSPTL_CO": "0", "ELESCH_CO": "1", "MSKUL_CO": "0", "HGSCHL_CO": "0"}},
        "change": {area: {"TRDAR_CHNGE_IX_NM": "다이나믹", "OPR_SALE_MT_AVRG": "114", "CLS_SALE_MT_AVRG": "50",
                          "SU_OPR_SALE_MT_AVRG": "118", "SU_CLS_SALE_MT_AVRG": "52"}},
    }
    for name, data in rows.items():
        doc = {"schema": context.SCHEMA, "period": period, "service": context.DATASETS[name][0], "rows": data,
               "fetched_at": "2026-11-16T23:35:55+09:00"}
        (folder / f"{name}_{period}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


class AreaContextHttpTests(unittest.TestCase):
    profile_body = setup_helpers.OnboardingAnalysisTests.profile_body
    save_profile = setup_helpers.OnboardingAnalysisTests.save_profile
    state = setup_helpers.OnboardingAnalysisTests.state
    options = setup_helpers.OnboardingAnalysisTests.options
    selection_body = setup_helpers.OnboardingAnalysisTests.selection_body
    save_selection = setup_helpers.OnboardingAnalysisTests.save_selection
    selected = setup_helpers.OnboardingAnalysisTests.selected

    def setUp(self):
        setup_helpers.OnboardingAnalysisTests.setUp(self)
        self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(context, "CONTEXT_DIR", self.folder))
        context._CACHE.clear()

    def tearDown(self):
        setup_helpers.OnboardingAnalysisTests.tearDown(self)

    def test_needs_saved_conditions(self):
        self.assertEqual(self.client.get("/api/onboarding/area-context").status_code, 409)

    def test_values_with_their_own_quarters(self):
        write_context(self.folder)
        saved = self.selected()
        res = self.client.get("/api/onboarding/area-context", params={"expected_revision": saved["revision"]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.headers["cache-control"], "no-store")
        data = res.json()
        self.assertEqual((data["status"], data["feature"], data["selection"]["area_code"]), ("available", "area_context", AREA))
        values = {v["label"]: v["value"] for v in data["values"]}
        self.assertEqual((values["직장인구"], values["상주인구"], values["세대 수"], values["집객시설 수"]), (489, 4347, 2762, 18))
        self.assertEqual(values["상권 변화 지표"], "다이나믹")
        self.assertIn("2026년 2분기", data["period_note"])
        self.assertTrue(data["warnings"])

    def test_not_collected_is_said_not_invented(self):
        write_context(self.folder, area="9999999")
        self.selected()
        data = self.client.get("/api/onboarding/area-context").json()
        self.assertEqual((data["status"], data["values"], data["sentence"]), ("not_collected", [], None))

    def test_rejects_other_query(self):
        self.selected()
        self.assertEqual(self.client.get("/api/onboarding/area-context", params={"area_code": "2222222"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
