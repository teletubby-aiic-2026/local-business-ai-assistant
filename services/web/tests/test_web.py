"""C7·C9 시험. CLOVA·네트워크를 부르지 않는다 (리뷰 서비스는 가짜, 모델은 가짜 함수).

실행 (services/web 에서):
  PYTHONPATH=<저장소 루트> MARKETING_DIR=<experiments/marketing> python -m unittest tests.test_web -v
C6 저장본(기본: 저장소의 experiments/marketing)이 없으면 그 저장본이 필요한 시험만 건너뛴다.
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
# main 에 #16 이 병합된 뒤로는 저장소 안의 experiments/marketing 을 기본으로 쓴다
MARKETING = Path(os.environ.get("MARKETING_DIR") or Path(__file__).resolve().parents[3] / "experiments" / "marketing")
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
                   "포장 마감 전 주문서를 한 번 더 확인할게요.", "공깃밥 추가로 보내드렸어야 했는데 못 챙겼네요."):
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
        good = lambda kind, facts, fixed: "포장 누락이 3건, 모두 17~21시에 반복됐어요 [F1]" if kind == "complaint" else fixed
        bad = lambda kind, facts, fixed: "포장 누락이 5건 반복된 건 바쁘기 때문이에요 [F1]"
        plan = plan_cards(fixture("insight_ongi.json"), snapshots(), "store_ongi", writer=good)[0]
        self.assertEqual(plan.card.reason_text, "포장 누락이 3건, 모두 17~21시에 반복됐어요")
        plan = plan_cards(fixture("insight_ongi.json"), snapshots(), "store_ongi", writer=bad)[0]
        self.assertIn("검사 불통과", plan.reason_source)
        self.assertEqual(plan.card.reason_text, "포장 누락 불만이 3건 반복됐고, 모두 17~21시에 들어왔어요")

    def test_generic_sentence_without_fact_value_is_rejected(self):
        """11/10 live 1차: 검사기는 통과했지만 숫자 없는 일반론. 근거 숫자가 없으면 고정 문장으로."""
        vague = lambda kind, facts, fixed: "리뷰 문제를 해결하면 고객 만족도가 높아지고 재구매로 이어질 수 있어요[F1]."
        plan = plan_cards(fixture("insight_ongi.json"), snapshots(), "store_ongi", writer=vague)[0]
        self.assertIn("검사 불통과", plan.reason_source)
        self.assertIn("no_fact_value", [p["type"] for p in plan.problems])

    def test_long_or_predicting_reason_is_rejected(self):
        """11/10 live 8차: 문단 여러 개 + '개선할 수 있습니다'가 검사기를 통과함 → 규칙으로 막음."""
        from web.cards import reason_problems
        facts = plan_cards(fixture("insight_ongi.json"), [], "store_ongi")[0].facts
        good = "포장 누락 불만 리뷰가 3건 있었고, 주로 17~21시에 들어왔어요[F1]. 재발 방지 공지를 올리고 답글도 달아요."
        self.assertEqual(reason_problems(good, facts), [])
        long = good + "\n\n" + "같은 불만을 가진 고객들의 마음을 돌리기 위해서는 빠른 대처가 필요합니다. " * 4
        self.assertIn("too_long", [p["type"] for p in reason_problems(long, facts)])
        pred = "포장 누락 불만이 3건이에요[F1]. 공지를 올리면 신뢰를 회복할 수 있어요."
        self.assertIn("prediction", [p["type"] for p in reason_problems(pred, facts)])

    def test_changed_area_or_time_label_is_rejected(self):
        """11/10 live 9차: '장승배기역 4번 출구 상권', 17~24시 누락 → 표기를 그대로 써야 통과."""
        from web.cards import reason_problems
        evening = load_json(AnalysisSnapshot, FIX / "snapshot_pr17_evening.json")
        facts = plan_cards(fixture("insight_ongi.json"), evening, "store_ongi")[1].facts
        bad = "장승배기역 4번 출구 상권의 2026년 2분기 저녁 추정 매출은 전년 동기 대비 19.31% 감소했습니다[F2]. 쿠폰 홍보를 제안해요."
        self.assertIn("label_changed", [p["type"] for p in reason_problems(bad, facts)])
        good = ("장승배기역 4번 상권의 저녁 시간대(17~24시) 추정 매출은 2026년 2분기에 전년 동기 대비 19.31% 감소했어요[F2]. "
                "저녁 손님을 다시 부르는 쿠폰 홍보를 제안해요.")
        self.assertEqual(reason_problems(good, facts), [])
        same = "포장 누락 불만 리뷰가 3건, 모두 17시부터 21시 사이에 들어왔어요[F1]. 재발 방지 공지를 올려요."
        facts_a0 = plan_cards(fixture("insight_ongi.json"), [], "store_ongi")[0].facts
        self.assertEqual(reason_problems(same, facts_a0), [])   # 같은 뜻의 시간 표기는 인정
        twice = "포장 누락 불만이 3건, 17~21시에 들어왔어요[F1].\n\n같은 말을 한 번 더 해요."
        facts_a = plan_cards(fixture("insight_ongi.json"), [], "store_ongi")[0].facts
        self.assertIn("too_long", [p["type"] for p in reason_problems(twice, facts_a)])

    def test_citation_spacing_normalized(self):
        from web.cards import normalize_citations
        self.assertEqual(normalize_citations("3건[ F1 ] 있어요 ［F2］"), "3건[F1] 있어요 [F2]")
        self.assertEqual(normalize_citations("그대로 [F1]"), "그대로 [F1]")

    @unittest.skipUnless(HAS_C6, "C6 저장본 없음")
    def test_complaint_card_offers_prevention_measures(self):
        """불만 카드: C6 조치 목록과 기본 선택(포장 누락 → M1 포장 마감 전 주문서 대조)을 화면에 준다."""
        from web.generate import GenerateError, pick_measures
        with tempfile.TemporaryDirectory() as tmp:
            demo = Demo(settings(Path(tmp)), source=FakeSource())
            card_a = demo.cards()["cards"][0]
            self.assertEqual(card_a["measures"]["default"], ["M1"])
            self.assertIn("M1", [o["id"] for o in card_a["measures"]["options"]])
            client = TestClient(create_app(demo))
            r = client.post(f"/api/cards/{card_a['card']['card_id']}/run", json={"measures": ["M1", "M3"]})
            self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([m["id"] for m in pick_measures(["M1"])], ["M1"])
        with self.assertRaises(GenerateError):
            pick_measures(["M9"])

    def test_percent_point_is_rejected(self):
        """변화율(%)을 %p로 쓰면 탈락 (11/10 live 4차)."""
        from web.cards import reason_problems
        evening = load_json(AnalysisSnapshot, FIX / "snapshot_pr17_evening.json")
        facts = plan_cards(fixture("insight_ongi.json"), evening, "store_ongi")[1].facts
        bad = "장승배기역 4번 상권의 저녁(17~24시) 매출이 2025년 2분기 대비 19.31%p 감소했어요[F2]."
        self.assertIn("unit_mismatch", [p["type"] for p in reason_problems(bad, facts)])
        self.assertEqual(reason_problems(bad.replace("%p", "%"), facts), [])

    def test_live_writer_retries_with_feedback(self):
        """live 이유 문장: 규칙 검사에 걸리면 고칠 점을 붙여 다시 쓴다."""
        asks = []
        answers = iter(["재구매로 이어질 수 있어요[F1].", "포장 누락 불만이 3건, 모두 17~21시에 들어왔어요 [F1]\n재발 방지 공지를 올려요."])

        def model(system, user):
            asks.append(user)
            return next(answers)
        with tempfile.TemporaryDirectory() as tmp:
            demo = Demo(settings(Path(tmp), mode="live"), source=FakeSource(), reason_model=model)
            text = demo._reason_writer("complaint", plan_cards(fixture("insight_ongi.json"), [], "store_ongi")[0].facts, "x")
        self.assertIn("3건", text)
        self.assertEqual(len(asks), 2)
        self.assertIn("고칠 점", asks[1])

    def test_failed_reason_retried_on_next_request(self):
        """live: 검사에 걸린 카드만 다음 요청 때 다시 쓰고, 통과한 문장은 그대로 둔다."""
        calls = []

        def model(system, user):
            calls.append(user)
            if len(calls) <= Demo.REASON_TRIES:   # 첫 라운드는 모두 숫자 없는 일반론
                return "만족도가 높아질 수 있어요[F1]."
            return "포장 누락 불만이 3건, 모두 17~21시에 들어왔어요 [F1]\n재발 방지 공지를 올려요."
        with tempfile.TemporaryDirectory() as tmp:
            demo = Demo(settings(Path(tmp), mode="live", snapshot_path=Path(tmp) / "none.json"),
                        source=FakeSource(), reason_model=model)
            first = demo.cards()["cards"][0]
            self.assertIn("불통과", first["reason_source"])
            second = demo.cards()["cards"][0]
            self.assertEqual(second["reason_source"], "HCX-005 (검사기 통과)")
            self.assertEqual(second["problems"], [])
            n = len(calls)
            demo.cards()
            self.assertEqual(len(calls), n)   # 통과한 뒤에는 다시 부르지 않음

    @unittest.skipUnless(HAS_C6, "C6 저장본 없음")
    def test_record_keeps_previous_result_for_same_card(self):
        """서버를 다시 띄운 뒤 저장해도, 같은 카드(같은 근거)의 기존 저장본 결과를 mock 저장본으로 덮지 않는다."""
        with tempfile.TemporaryDirectory() as tmp:
            demo = Demo(settings(Path(tmp)), source=FakeSource())
            demo.record()
            cache = json.loads((Path(tmp) / "web_cache.json").read_text())
            cid = cache["cards"][0]["card"]["card_id"]
            cache["results"][cid]["drafts"][0]["text"] = "live 로 만든 글 (표시)"
            (Path(tmp) / "web_cache.json").write_text(json.dumps(cache, ensure_ascii=False))
            again = Demo(settings(Path(tmp)), source=FakeSource())   # 서버를 다시 띄운 것과 같음
            again.record()
            kept = json.loads((Path(tmp) / "web_cache.json").read_text())
            self.assertEqual(kept["results"][cid]["drafts"][0]["text"], "live 로 만든 글 (표시)")

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
