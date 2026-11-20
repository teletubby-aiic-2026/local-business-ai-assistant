"""사장님이 직접 등록한 가게 (6차 회의 11/20) — X-IC26-Store-Profile 헤더로 받은 가게. 가짜 데이터, 네트워크 없음, HCX 안 부름.

- 헤더가 오면 등록한 이름·메뉴·가격으로 맞춤 마케팅이 돈다 (리뷰·카드·상권 지표 없음 = 빈 목록, 샘플로 채우지 않음).
- 카드가 있어야 만드는 글(안내문·쿠폰 홍보)은 500 이 아니라 409 + 안내 문장, 계획(/plan)은 200 + unavailable_drafts.
- 헤더 값이 틀리면 400, 헤더 없이 온 모르는 가게는 예전처럼 404. 예시 가게의 응답은 그대로.

실행 (experiments/marketing 에서):  python -m pytest -q -s tests/test_registered_store.py
"""

import base64
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from marketing_survey import stores
from marketing_survey.server import app
from shared import store_header

API = "/api/marketing-survey"
SID = "store_00aa11bb22cc"
PROFILE = {"v": 1, "store_id": SID, "name": "우리분식", "business_type_name": "분식전문점", "industry_code": "CS100002",
           "business_status": "operating", "channels": ["배달의민족"],
           "menus": [{"name": "떡볶이", "price": 5000}, {"name": "순대", "price": 4500}],
           "location": {"kind": "station", "label": "상도역", "station_id": "kric-x", "station_name": "상도역"},
           "area": {"area_code": "3110836", "name": "상도역 5번", "period": "20262"}}
HEADER = {store_header.HEADER: store_header.encode(PROFILE)}
KEY_ENVS = ("CLOVA_API_KEY", "CLOVASTUDIO_API_KEY", "CLOVA_STUDIO_API_KEY", "APP_MODE", "MARKETING_APP_MODE")


def _raw(data) -> str:
    return base64.urlsafe_b64encode(json.dumps(data, ensure_ascii=False).encode()).decode().rstrip("=")


class RegisteredStore(unittest.TestCase):
    def setUp(self):
        env = {k: v for k, v in os.environ.items() if k not in KEY_ENVS}
        env.update(MARKETING_RECORDS_DIR=tempfile.mkdtemp(), MARKETING_APP_MODE="mock")
        env.pop("DB_HOST", None)
        self.env = patch.dict(os.environ, env, clear=True)
        self.env.start()
        stores._registered.clear()
        self.client = TestClient(app)
        self.q = {"store": SID, "visitor_id": "u-test"}

    def tearDown(self):
        stores._registered.clear()
        self.env.stop()

    def post(self, path, body, headers=HEADER):
        return self.client.post(f"{API}/{path}", params=self.q, json=body, headers=headers)

    def walk(self, answers):
        state = self.post("step", {"state": None}).json()["state"]
        for answer in answers:
            data = self.post("step", {"state": state, "answer": answer}).json()
            state = data["state"]
        return data

    def test_unknown_store_without_header_is_404(self):
        res = self.client.get(f"{API}/meta", params={"store": SID})
        self.assertEqual(res.status_code, 404)

    def test_meta_uses_the_registered_name_and_menu(self):
        meta = self.client.get(f"{API}/meta", params={"store": SID}, headers=HEADER).json()
        self.assertEqual((meta["store_name"], meta["store_id"]), ("우리분식", SID))
        ctx = stores.get_ctx(SID)
        self.assertEqual(ctx.store.menu_prices, {"떡볶이": 5000, "순대": 4500})
        self.assertEqual((ctx.reviews, ctx.cards, ctx.snapshots, ctx.owner_replies), ([], [], [], []))
        self.assertEqual(ctx.store.channels, ["baemin"])
        self.assertEqual(ctx.tone.store_id, SID)

    def test_new_customer_with_no_budget_makes_a_promo_text_with_the_store_name(self):
        data = self.walk(["맞춤 홍보 제안", "아니요", "새 손님", "모름", "0원(지금은 안 씀)"])
        self.assertTrue(data["done"])
        plan = self.post("plan", {"state": data["state"]})
        self.assertEqual(plan.status_code, 200, plan.text)
        body = plan.json()
        self.assertTrue(body["demo"])
        texts = " ".join(body["drafts"].values())
        self.assertIn("우리분식", texts)
        self.assertNotIn("온기한식", texts)

    def test_complaint_paths_are_409_with_a_message_not_500(self):
        data = self.walk(["맞춤 홍보 제안", "예", "포장 누락"])
        self.assertTrue(data["done"])
        plan = self.post("plan", {"state": data["state"]})
        self.assertEqual(plan.status_code, 200, plan.text)
        self.assertTrue(plan.json()["unavailable_drafts"])
        self.assertIn("반복 불만", plan.json()["unavailable_drafts"][0]["message"])
        for path in ("generate", "notice-followup"):
            res = self.post(path, {"state": data["state"]})
            self.assertEqual(res.status_code, 409, path)
            self.assertIn("리뷰", res.json()["detail"])

    def test_leftover_story_adspend_report_and_delete(self):
        res = self.post("plan", {"state": {"node": "DECISION", "mode": "leftover",
                                           "raw": {"leftover_item": "떡볶이", "leftover_portions": 5}}})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertNotIn("온기한식", json.dumps(res.json(), ensure_ascii=False))
        for period in ("weekly", "monthly"):
            self.assertEqual(self.client.get(f"{API}/report", params={**self.q, "period": period}, headers=HEADER).status_code, 200)
        self.assertEqual(self.client.delete(f"{API}/records", params=self.q, headers=HEADER).json(), {"deleted": True})

    def test_bad_headers_are_400(self):
        for value in ("!!", _raw({**PROFILE, "store_id": "store_ongi"}), _raw({**PROFILE, "menus": "x"}),
                      "A" * (store_header.MAX_HEADER + 1)):
            res = self.client.get(f"{API}/meta", params={"store": "store_ongi"}, headers={store_header.HEADER: value})
            self.assertEqual(res.status_code, 400, value[:20])
        self.assertIsNone(stores._registered.get("store_ongi"))
        meta = self.client.get(f"{API}/meta", params={"store": "store_ongi"}).json()
        self.assertEqual(meta["store_id"], "store_ongi")

    def test_restart_first_request_with_header(self):
        self.client.get(f"{API}/meta", params={"store": SID}, headers=HEADER)
        stores._registered.clear()                    # 다시 켜짐
        self.assertEqual(self.client.get(f"{API}/meta", params={"store": SID}).status_code, 404)
        self.assertEqual(self.client.get(f"{API}/meta", params={"store": SID}, headers=HEADER).status_code, 200)

    def test_sample_store_list_is_unchanged(self):
        self.client.get(f"{API}/meta", params={"store": SID}, headers=HEADER)
        ids = [s["store_id"] for s in self.client.get(f"{API}/stores").json()["stores"]]
        self.assertEqual(ids, ["store_ongi", "store_basak", "store_mongle"])


if __name__ == "__main__":
    unittest.main()
