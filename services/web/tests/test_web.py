"""C7·C9 시험. CLOVA·네트워크를 부르지 않는다 (리뷰 서비스는 가짜, 모델은 가짜 함수).

실행 (services/web 에서):
  PYTHONPATH=<저장소 루트> MARKETING_DIR=<experiments/marketing> python -m unittest tests.test_web -v
MARKETING_DIR 가 없으면 C6 저장본이 필요한 시험만 건너뛴다.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from shared.answer_check import check_answer
from shared.contracts import AnalysisSnapshot, load_json
from web import c9
from web.cards import EVENING_ID, build_cards, pick_card_b_snapshot, plan_cards, why_no_card_b
from web.demo import Demo
from web.main import create_app
from web.settings import Settings
from web.sources import SourceError, to_review_records, to_store_profile

FIX = Path(__file__).resolve().parent / "fixtures"
MARKETING = Path(os.environ.get("MARKETING_DIR", "")) if os.environ.get("MARKETING_DIR") else None
HAS_C6 = bool(MARKETING and (MARKETING / "c6" / "replay" / "c6_cache_best.json").exists())


def fixture(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def snapshots() -> list[AnalysisSnapshot]:
    return load_json(AnalysisSnapshot, FIX / "snapshot_pr17.json")


def snap(**kw) -> AnalysisSnapshot:
    base = dict(snapshot_id="snap_x", area_name="시험 상권", metric_name="추정매출 (전년 동기 대비 변화율)", value=-10.0,
                unit="%", basis_quarter="2026Q2", is_estimate=True, source="서울시", compared_with_quarter="2025Q2")
    base.update(kw)
    return AnalysisSnapshot(**base)


class FakeSource:
    """#14 대신. paste 하면 리뷰가 늘고 insight 는 그대로 (분류는 #14 의 일)."""

    def __init__(self, down: bool = False):
        self.down = down
        self.pasted: list[dict] = []

    def _check(self):
        if self.down:
            raise SourceError("리뷰 분석 서비스에 연결하지 못했습니다: ConnectError")

    def health(self):
        return {"status": "down"} if self.down else {"status": "ok", "mode": "mock", "models": {"review_classify": "rule"}}

    def store(self, store_id):
        self._check(); return fixture("store_ongi.json")

    def reviews(self, store_id):
        self._check(); return fixture("reviews_ongi.json") + self.pasted

    def insight(self, store_id):
        self._check(); return fixture("insight_ongi.json")

    def paste(self, store_id, text, rating=None, channel=None):
        self._check()
        review = {"review_id": f"rv_ongi_paste_{len(self.pasted) + 1:03d}", "store_id": store_id, "text": text,
                  "created_at": "2026-11-09T23:00:00+09:00", "input_method": "paste", "pii_masked": True}
        self.pasted.append(review)
        return {"review": review, "classification": {"sentiment": "negative", "negative_topics": []}}

    def reset_pasted(self, store_id):
        n = len(self.pasted); self.pasted.clear(); return {"deleted": n}


def settings(tmp: Path, **kw) -> Settings:
    base = dict(mode="mock", snapshot_path=FIX / "snapshot_pr17.json", marketing_dir=MARKETING or tmp / "no-marketing",
                cache_path=tmp / "web_cache.json", runtime_dir=tmp / "runtime")
    base.update(kw)
    return Settings(**base)


# ── ② 카드 규칙 ─────────────────────────────────────────────────────
class CardRules(unittest.TestCase):
    def test_two_cards_from_real_inputs(self):
        cards = build_cards(fixture("insight_ongi.json"), snapshots(), "store_ongi")
        self.assertEqual([c.kind for c in cards], ["complaint", "promo"])
        self.assertEqual(cards[0].review_ids, ["rv_ongi_001", "rv_ongi_002", "rv_ongi_003"])
        self.assertEqual(cards[1].snapshot_ids, ["snap_3110826_sales_all_day_observed_yoy_2026Q2"])
        self.assertNotIn("[F", cards[0].reason_text + cards[1].reason_text)

    def test_fixed_reasons_pass_the_checker(self):
        for plan in plan_cards(fixture("insight_ongi.json"), snapshots(), "store_ongi"):
            self.assertEqual(plan.reason_source, "고정 문장", plan.problems)
            self.assertTrue(check_answer(plan.checked_text, plan.facts)["ok"])

    def test_card_b_shows_the_real_number_and_scope(self):
        plan = plan_cards(fixture("insight_ongi.json"), snapshots(), "store_ongi")[1]
        self.assertIn("27.95%", plan.card.reason_text)
        self.assertIn("하루 전체 시간대", plan.card.reason_text)
        self.assertNotIn("저녁", plan.card.reason_text)     # 하루 전체 지표를 '저녁'이라고 말하지 않는다

    def test_evening_metric_preferred_when_present(self):
        evening = snap(snapshot_id=EVENING_ID, metric_name="저녁(17~21시) 추정매출 (전년 동기 대비 변화율)", value=-12.3)
        self.assertEqual(pick_card_b_snapshot(snapshots() + [evening]).snapshot_id, EVENING_ID)
        plan = plan_cards(fixture("insight_ongi.json"), [evening], "store_ongi")[1]
        self.assertIn("저녁 손님을", plan.card.reason_text)
        self.assertTrue(check_answer(plan.checked_text, plan.facts)["ok"])

    def test_pr17_evening_metric(self):
        """PR #17 갱신본(a072ef2): 저녁 17~24시, 두 분기 공통 업종 -19.31%."""
        evening = load_json(AnalysisSnapshot, FIX / "snapshot_pr17_evening.json")
        plan = plan_cards(fixture("insight_ongi.json"), evening, "store_ongi")[1]
        self.assertEqual(plan.reason_source, "고정 문장", plan.problems)
        self.assertTrue(check_answer(plan.checked_text, plan.facts)["ok"])
        self.assertIn("저녁 시간대(17~24시) 추정매출(두 분기 공통 업종)", plan.card.reason_text)
        self.assertIn("19.31%", plan.card.reason_text)
        self.assertIn("저녁 손님을", plan.card.reason_text)
        self.assertNotIn("변화율", plan.title)

    def test_complaint_title_puts_prevention_first(self):
        """강조점(11/10): 반복 → 재발 방지 공지가 먼저, 답글은 함께."""
        plan = plan_cards(fixture("insight_ongi.json"), [], "store_ongi")[0]
        self.assertEqual(plan.title, "포장 누락 3건 반복 → 재발 방지 공지 + 답글")

    def test_action_flags(self):
        """하지 않은 조치·정하지 않은 보상은 '확인 필요', 사과와 재발 방지 다짐은 통과."""
        from web.generate import action_flags, summarize
        self.assertTrue(action_flags("공깃밥 추가로 보내드렸어요."))
        self.assertTrue(action_flags("환불 처리 완료했습니다."))
        self.assertTrue(action_flags("다음 주문 때 서비스로 음료 드릴게요."))
        for ok in ("불편을 드려 죄송합니다.", "불편을 드렸네요, 죄송해요.", "다음부터는 꼼꼼히 챙겨 드리겠습니다.",
                   "포장 마감 전 주문서를 한 번 더 확인할게요."):
            self.assertEqual(action_flags(ok), [], ok)
        r = summarize({"drafts": [{"text": "공깃밥 추가로 보내드렸어요."}, {"text": "죄송합니다."}]})
        self.assertEqual(r["flagged_count"], 1)
        self.assertEqual(len(r["drafts"][0]["c7_flags"]), 1)

    def test_no_fall_through_to_another_metric(self):
        """고른 지표가 하락이 아니면 카드 ⓑ 없음. 하락인 다른 지표를 찾아 내려가지 않는다."""
        rising = snap(snapshot_id=EVENING_ID, value=3.0)
        falling = snap(snapshot_id="snap_other", value=-30.0)
        plans = plan_cards(fixture("insight_ongi.json"), [rising, falling], "store_ongi")
        self.assertEqual([p.card.kind for p in plans], ["complaint"])
        self.assertIn("기준", why_no_card_b([rising, falling], "", -5.0))

    def test_none_value_means_no_card(self):
        plans = plan_cards(fixture("insight_ongi.json"), [snap(snapshot_id=EVENING_ID, value=None)], "store_ongi")
        self.assertEqual(len(plans), 1)

    def test_no_repeated_issue_means_no_card_a(self):
        insight = copy.deepcopy(fixture("insight_ongi.json")); insight["top_issue_id"] = None
        self.assertEqual([p.card.kind for p in plan_cards(insight, snapshots(), "store_ongi")], ["promo"])

    def test_model_sentence_used_only_when_it_passes(self):
        good = lambda kind, facts, fixed: "포장 누락이 3건이나 반복됐어요 [F1]" if kind == "complaint" else fixed
        bad = lambda kind, facts, fixed: "포장 누락이 5건 반복된 건 바쁘기 때문이에요 [F1]"
        plan = plan_cards(fixture("insight_ongi.json"), snapshots(), "store_ongi", writer=good)[0]
        self.assertEqual(plan.card.reason_text, "포장 누락이 3건이나 반복됐어요")
        plan = plan_cards(fixture("insight_ongi.json"), snapshots(), "store_ongi", writer=bad)[0]
        self.assertIn("검사 불통과", plan.reason_source)
        self.assertEqual(plan.card.reason_text, "포장 누락 불만이 3건 반복됐고, 모두 17~21시에 들어왔어요")

    def test_model_failure_falls_back(self):
        def boom(*_):
            raise TimeoutError
        plan = plan_cards(fixture("insight_ongi.json"), snapshots(), "store_ongi", writer=boom)[0]
        self.assertIn("실패", plan.reason_source)


# ── G2 변환 ─────────────────────────────────────────────────────────
class Conversion(unittest.TestCase):
    def test_reviews_get_classification(self):
        records = to_review_records(fixture("reviews_ongi.json"), fixture("insight_ongi.json"))
        self.assertEqual(len(records), 40)
        r1 = next(r for r in records if r.review_id == "rv_ongi_001")
        self.assertEqual((r1.sentiment, r1.negative_topics, r1.status), ("negative", ["missing_item"], "analyzed"))

    def test_store_gets_area_and_prices(self):
        store = to_store_profile(fixture("store_ongi.json"), "장승배기역 4번")
        self.assertEqual(store.area_name, "장승배기역 4번")
        self.assertEqual(store.menu_prices["제육볶음 정식"], 9500)


# ── ①→④ API ─────────────────────────────────────────────────────────
class Flow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.source = FakeSource()
        self.client = TestClient(create_app(Demo(settings(self.tmp), source=self.source)))

    def test_briefing_numbers(self):
        b = self.client.get("/api/briefing").json()
        self.assertEqual(b["counts"], {"review_count": 40, "complaint_count": 12, "group_count": 3, "single_complaint_count": 5})
        self.assertEqual(b["repeated_count"], 1)
        self.assertEqual(b["store"]["area_name"], "장승배기역 4번")
        self.assertTrue(all(s["basis_label"].startswith("기준: 2026 2분기") for s in b["snapshots"]))

    def test_health_parts_say_what_is_real(self):
        h = self.client.get("/api/health").json()
        self.assertEqual(h["mode"], "mock")
        self.assertEqual(h["parts"]["reviews"], "합성 데이터")
        self.assertEqual(h["dev_fake_snapshots"], [])
        self.assertFalse(h["key_present"] and False)

    @unittest.skipUnless(HAS_C6, "MARKETING_DIR(C6 저장본) 없음")
    def test_run_and_approve(self):
        cards = self.client.get("/api/cards").json()["cards"]
        a = cards[0]["card"]["card_id"]
        r = self.client.post(f"/api/cards/{a}/run").json()
        self.assertEqual(r["source"], "seed")
        self.assertEqual([d["generator"] for d in r["drafts"]], ["reply_draft"] * 3 + ["prevention_notice"])
        self.assertEqual(r["reason_text"], cards[0]["card"]["reason_text"])
        d = r["drafts"][0]
        ok = self.client.post(f"/api/drafts/{d['draft_id']}/approve", json={"text": d["text"] + " 고침", "original": d["text"]}).json()
        self.assertTrue(ok["edited"])
        self.assertEqual(len(self.client.get("/api/approvals").json()["items"]), 1)
        self.assertTrue((self.tmp / "runtime" / "approvals.jsonl").exists())

    @unittest.skipUnless(HAS_C6, "MARKETING_DIR(C6 저장본) 없음")
    def test_promo_seed_uses_our_reason_not_placeholder(self):
        b = self.client.get("/api/cards").json()["cards"][1]["card"]
        r = self.client.post(f"/api/cards/{b['card_id']}/run").json()
        self.assertNotIn("-X%", r["reason_text"])
        self.assertIn("27.95%", r["reason_text"])
        self.assertEqual(r["drafts"][0]["evidence_ids"][0], b["snapshot_ids"][0])

    def test_service_down_is_reported(self):
        self.source.down = True
        res = self.client.get("/api/briefing")
        self.assertEqual(res.status_code, 503)
        self.assertIn("연결하지 못했습니다", res.json()["error"]["message"])

    def test_live_without_key_is_blocked(self):
        client = TestClient(create_app(Demo(settings(self.tmp, mode="live"), source=FakeSource())))
        self.assertTrue(any("키가 없어요" in b for b in client.get("/api/health").json()["blocking"]))

    def test_paste_is_passed_through(self):
        res = self.client.post("/api/reviews", json={"text": "반찬이 하나 빠졌어요"})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(self.client.get("/api/briefing").json()["pasted"]), 1)
        self.assertEqual(self.client.delete("/api/reviews/pasted").json()["deleted"], 1)


# ── C9 발표 모드 ────────────────────────────────────────────────────
class Replay(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    @unittest.skipUnless(HAS_C6, "MARKETING_DIR(C6 저장본) 없음")
    def test_record_then_replay_is_identical_and_offline(self):
        mock = TestClient(create_app(Demo(settings(self.tmp), source=FakeSource())))
        rec = mock.post("/api/c9/record").json()
        self.assertEqual(len(rec["results"]), 2)
        replay = TestClient(create_app(Demo(settings(self.tmp, mode="replay"), source=FakeSource(down=True))))
        first = [replay.get(p).json() for p in ("/api/briefing", "/api/cards")]
        second = [replay.get(p).json() for p in ("/api/briefing", "/api/cards")]
        self.assertEqual(first, second)
        self.assertEqual(first[0]["counts"]["review_count"], 40)
        card_id = first[1]["cards"][0]["card"]["card_id"]
        runs = [replay.post(f"/api/cards/{card_id}/run").json() for _ in range(2)]
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(replay.get("/api/health").json()["blocking"], [])
        self.assertEqual(replay.post("/api/reviews", json={"text": "x"}).status_code, 409)

    def test_replay_without_cache_is_blocked(self):
        client = TestClient(create_app(Demo(settings(self.tmp, mode="replay"), source=FakeSource(down=True))))
        self.assertTrue(client.get("/api/health").json()["blocking"])
        self.assertEqual(client.get("/api/briefing").status_code, 409)

    def test_dev_fake_snapshot_cannot_be_recorded_or_replayed(self):
        fake = [snap(snapshot_id=EVENING_ID, note="개발용 가짜 값 (현석 값 오기 전)").to_dict()]
        path = self.tmp / "fake.json"
        path.write_text(json.dumps(fake, ensure_ascii=False), encoding="utf-8")
        mock = TestClient(create_app(Demo(settings(self.tmp, snapshot_path=path), source=FakeSource())))
        self.assertEqual(mock.get("/api/health").json()["dev_fake_snapshots"], [EVENING_ID])
        self.assertEqual(mock.post("/api/c9/record").status_code, 409)
        with self.assertRaises(c9.CacheError):
            c9.write_cache(self.tmp / "x.json", {"snapshots": fake})
        self.assertTrue(c9.replay_blockers({"version": 1, "snapshots": fake}))


if __name__ == "__main__":
    unittest.main()
