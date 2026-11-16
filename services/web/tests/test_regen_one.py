"""개별 다시 만들기 (11/16) — POST /api/cards/{card_id}/run 에 generator(+review_id)를 보내면 그 글 한 건만 다시 만드는지 본다.
초안 상자의 '다시 만들기'가 카드 전체를 다시 만들어 다른 글의 수정·승인까지 날리던 것을 고친 것. CLOVA·네트워크를 부르지 않는다.

- mock: 저장 예시에서 그 한 건만. 붙여넣은 리뷰의 답글은 같은 글의 저장 예시가 있을 때만.
- live: HCX 는 가짜(clova.call 을 바꿔 끼움)이고 C6 코드는 진짜로 돈다 → web.generate._one_reply 가 부르는 c6.reply._process_review 의
  인자가 C6 쪽에서 바뀌면 이 시험이 잡는다.
- 잘못된 입력은 400/404, HCX 문제는 500 이 아니라 화면 알림 띠(전체 실행과 같은 방식).
- 다시 만든 글도 서버가 기억해서(_remember_drafts) 승인 기록에 카드·종류가 붙는다.

실행 (services/web 에서): PYTHONPATH=<저장소 루트>:. python -m pytest -q tests/test_regen_one.py
리뷰 문장은 모두 합성 문장이다.
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from shared.storage import MemoryStore
from shared.storage.memory import MemoryApprovals
from web.demo import Demo
from web.generate import ensure_marketing_on_path
from web.main import create_app

from tests.test_pasted_reply import OTHER_UNFAIR, UNFAIR, PasteSource
from tests.test_web import HAS_C6, MARKETING, FakeSource, settings

PRAISE = "점심에 먹었는데 반찬도 깔끔하고 사장님도 친절하세요!"
AI_BODY = "주문하신 메뉴가 빠져서 정말 죄송해요. 앞으로 더 꼼꼼히 챙겨 볼게요. 소중한 리뷰 감사해요."
BUNDLE = ["rv_ongi_001", "rv_ongi_002", "rv_ongi_003"]


class RecordingApprovals(MemoryApprovals):
    """승인 기록에 붙은 카드·종류를 적어 둔다."""

    def __init__(self):
        super().__init__()
        self.meta = {}

    def save(self, store_id, visitor_id, entry, *, card_id=None, kind=None):
        self.meta[entry["draft_id"]] = (card_id, kind)
        super().save(store_id, visitor_id, entry, card_id=card_id, kind=kind)


def run(client, card_id, **body):
    return client.post(f"/api/cards/{card_id}/run", json=body) if body else client.post(f"/api/cards/{card_id}/run")


def slot(d):
    return d["generator"], d.get("target_review_id")


@unittest.skipUnless(HAS_C6, "MARKETING_DIR(C6 저장본) 없음")
class MockOne(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.source = PasteSource()
        self.store = MemoryStore()
        self.store.approvals = RecordingApprovals()
        self.demo = Demo(settings(self.tmp), source=self.source, storage=self.store)
        self.client = TestClient(create_app(self.demo))
        cards = self.client.get("/api/cards").json()["cards"]
        self.a, self.b = cards[0]["card"]["card_id"], cards[1]["card"]["card_id"]
        self.full = run(self.client, self.a).json()

    def test_no_generator_is_still_the_whole_card(self):
        self.assertEqual([slot(d) for d in self.full["drafts"]],
                         [("reply_draft", r) for r in BUNDLE] + [("prevention_notice", None)])
        self.assertNotIn("partial", self.full)
        self.assertNotIn("regenerated", self.full)
        again = run(self.client, self.a, measures=["M1"]).json()               # 화면이 보내던 본문 그대로
        self.assertEqual(len(again["drafts"]), 4)
        self.assertNotIn("partial", again)

    def test_notice_alone(self):
        res = run(self.client, self.a, generator="prevention_notice")
        self.assertEqual(res.status_code, 200, res.text)
        r = res.json()
        self.assertEqual([slot(d) for d in r["drafts"]], [("prevention_notice", None)])
        self.assertIs(r["partial"], True)
        self.assertEqual(r["regenerated"], {"generator": "prevention_notice", "review_id": None, "pasted": False})
        notice = next(d for d in self.full["drafts"] if d["generator"] == "prevention_notice")
        self.assertEqual(r["drafts"][0], notice)                                # mock: 저장 예시의 그 글 그대로 (c7_flags 포함)
        # 응답 모양은 전체 실행과 같다 (partial·regenerated 만 더 있음)
        self.assertEqual(set(r) - {"partial", "regenerated"}, set(self.full))
        self.assertEqual((r["source"], r["card_id"], r["kind"], r["reason_text"]),
                         ("seed", self.a, "complaint", self.full["reason_text"]))
        self.assertEqual(r["flagged_count"], 0)

    def test_one_bundle_reply(self):
        r = run(self.client, self.a, generator="reply_draft", review_id="rv_ongi_002").json()
        self.assertEqual([slot(d) for d in r["drafts"]], [("reply_draft", "rv_ongi_002")])
        self.assertEqual(r["regenerated"], {"generator": "reply_draft", "review_id": "rv_ongi_002", "pasted": False})
        self.assertEqual(r["drafts"][0], self.full["drafts"][1])
        self.assertNotIn("pasted_reply_review_ids", r)                           # 묶음 리뷰의 답글

    def test_promo_alone(self):
        full = run(self.client, self.b).json()
        r = run(self.client, self.b, generator="coupon_promo").json()
        self.assertEqual([slot(d) for d in r["drafts"]], [("coupon_promo", None)])
        self.assertEqual(r["drafts"], full["drafts"])
        self.assertIs(r["partial"], True)
        self.assertEqual(r["chosen_measures"], [])

    def test_pasted_review_reply_is_told_apart_from_the_bundle(self):
        rid = self.client.post("/api/reviews", json={"text": UNFAIR, "rating": 1}).json()["review"]["review_id"]
        full = run(self.client, self.a).json()
        self.assertEqual(full["pasted_reply_review_ids"], [rid])
        r = run(self.client, self.a, generator="reply_draft", review_id=rid).json()
        self.assertEqual([slot(d) for d in r["drafts"]], [("reply_draft", rid)])
        self.assertEqual(r["drafts"][0], full["drafts"][4])
        self.assertEqual(r["drafts"][0]["stance"], "explain")                   # 붙여넣은 억울한 리뷰: 사과 없이 설명하는 답글 그대로
        self.assertEqual(r["regenerated"], {"generator": "reply_draft", "review_id": rid, "pasted": True})
        self.assertEqual((r["pasted_reply_review_ids"], r["pasted_reply_skipped"]), ([rid], []))
        self.assertIn("저장 예시", r["source_note"])
        self.assertEqual(r["flagged_count"], 1)                                  # '확인 필요'(사과 없이 설명)
        # 묶음 리뷰 답글을 다시 만들 때는 붙여넣은 리뷰 칸이 붙지 않는다
        self.assertNotIn("pasted_reply_review_ids", run(self.client, self.a, generator="reply_draft", review_id="rv_ongi_001").json())

    def test_pasted_review_without_a_stored_example_or_not_a_target_is_404(self):
        no_example = self.client.post("/api/reviews", json={"text": OTHER_UNFAIR, "rating": 1}).json()["review"]["review_id"]
        praise = self.client.post("/api/reviews", json={"text": PRAISE, "rating": 5}).json()["review"]["review_id"]
        res = run(self.client, self.a, generator="reply_draft", review_id=no_example)
        self.assertEqual(res.status_code, 404)
        self.assertIn("저장 예시", res.json()["error"]["message"])
        self.assertEqual(run(self.client, self.a, generator="reply_draft", review_id=praise).status_code, 404)   # 칭찬 리뷰는 답글 대상이 아님

    def test_bad_requests(self):
        cases = [
            (self.a, {"generator": "coupon_promo"}, 400),                        # 불만 카드는 홍보글을 만들지 않는다
            (self.b, {"generator": "prevention_notice"}, 400),
            (self.b, {"generator": "reply_draft", "review_id": "rv_ongi_001"}, 400),
            (self.a, {"generator": "nonsense"}, 400),
            (self.a, {"generator": ""}, 400),                                    # 빈 값을 카드 전체로 넘기지 않는다 (전체는 다른 글을 날린다)
            (self.a, {"generator": "reply_draft"}, 400),                         # 어느 리뷰인지 없음
            (self.a, {"generator": "reply_draft", "review_id": ""}, 400),
            (self.a, {"generator": "reply_draft", "review_id": "rv_ongi_020"}, 404),   # 이 카드 묶음의 리뷰가 아님
            (self.a, {"generator": "reply_draft", "review_id": "rv_nope"}, 404),
            ("card_nope", {"generator": "prevention_notice"}, 404),
            (self.a, {"generator": "x" * 41}, 422),
            (self.a, {"generator": "prevention_notice", "reply_texts": "글"}, 422),
        ]
        for card_id, body, status in cases:
            with self.subTest(card=card_id, body=body):
                res = run(self.client, card_id, **body)
                self.assertEqual(res.status_code, status, res.text)
                if status in (400, 404):
                    self.assertTrue(res.json()["error"]["message"])                # 화면 알림 띠에 그대로 보이는 문장

    def test_review_id_is_ignored_for_the_notice(self):
        r = run(self.client, self.a, generator="prevention_notice", review_id="rv_nope").json()
        self.assertEqual(r["regenerated"]["review_id"], None)
        self.assertEqual([slot(d) for d in r["drafts"]], [("prevention_notice", None)])

    def test_chosen_measures_are_the_owners_picks_even_in_mock(self):
        """mock 은 저장 예시 글을 그대로 주지만, 고른 수칙은 응답에 실어 화면(초안·완료)이 보여 줄 수 있게 한다."""
        self.assertEqual([m["id"] for m in self.full["chosen_measures"]], ["M1"])                    # 안 보내면 카드 기본값
        picked = run(self.client, self.a, measures=["M2", "M3"]).json()
        self.assertEqual(picked["chosen_measures"], [{"id": "M2", "text": "출발 전 품목 수량 확인"},
                                                      {"id": "M3", "text": "소스·반찬 별도 체크리스트 부착"}])
        self.assertEqual([d["text"] for d in picked["drafts"]], [d["text"] for d in self.full["drafts"]])   # 글은 저장 예시 그대로
        self.assertEqual(run(self.client, self.a, measures=[]).json()["chosen_measures"], [])
        loose = run(self.client, self.a, measures=["M9", "M2", "M2"])                                 # mock 은 모르는 id 를 오류 없이 뺀다
        self.assertEqual((loose.status_code, [m["id"] for m in loose.json()["chosen_measures"]]), (200, ["M2"]))
        one = run(self.client, self.a, generator="prevention_notice", measures=["M2", "M3"]).json()
        self.assertEqual([m["id"] for m in one["chosen_measures"]], ["M2", "M3"])                     # 개별 다시 만들기도 같다
        self.assertEqual(run(self.client, self.b).json()["chosen_measures"], [])                      # 홍보 카드는 그대로

    def test_other_drafts_stay_known_and_the_new_one_can_be_approved(self):
        """한 건만 다시 만들어도 서버가 기억하는 다른 글은 그대로이고, 다시 만든 글을 승인하면 카드·종류가 기록된다."""
        before = dict(self.demo._drafts)
        r = run(self.client, self.a, generator="reply_draft", review_id="rv_ongi_003").json()
        self.assertEqual(dict(self.demo._drafts), before)                          # mock 은 id 가 같아 그대로
        new = r["drafts"][0]
        ok = self.client.post(f"/api/drafts/{new['draft_id']}/approve", json={"text": new["text"], "original": new["text"]})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.store.approvals.meta[new["draft_id"]], (self.a, "reply_draft"))
        self.assertEqual(self.demo.reply_target(new["draft_id"]), "rv_ongi_003")
        other = self.full["drafts"][3]                                              # 다시 만들지 않은 공지도 여전히 승인된다
        self.client.post(f"/api/drafts/{other['draft_id']}/approve", json={"text": other["text"], "original": other["text"]})
        self.assertEqual(self.store.approvals.meta[other["draft_id"]], (self.a, "prevention_notice"))


@unittest.skipUnless(HAS_C6, "MARKETING_DIR(C6 저장본) 없음")
class LiveOneWiring(unittest.TestCase):
    """live: Demo 가 글 한 건 생성기(run_live_one)에 넘기는 입력. 생성기는 가짜."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.source = PasteSource()
        self.store = MemoryStore()
        self.store.approvals = RecordingApprovals()
        self.demo = Demo(settings(self.tmp, mode="live", clova_key="test-key"), source=self.source, storage=self.store,
                         reason_model=lambda system, user: "")
        self.client = TestClient(create_app(self.demo))
        cards = self.client.get("/api/cards").json()["cards"]
        self.a, self.b = cards[0]["card"]["card_id"], cards[1]["card"]["card_id"]
        self.full = {"card_id": self.a, "kind": "complaint", "source": "live", "won": 1.0, "drafts": [
            {"draft_id": f"d{i}", "generator": "reply_draft", "target_review_id": rid, "text": "죄송해요."}
            for i, rid in enumerate(BUNDLE, 1)] + [{"draft_id": "d4", "generator": "prevention_notice", "text": "공지입니다."}]}

    def made(self, generator, review_id=None, draft_id="d9"):
        return {"card_id": self.a, "kind": "complaint", "source": "live", "won": 0.3, "chosen_measures": [], "drafts": [
            {"draft_id": draft_id, "generator": generator, "target_review_id": review_id, "text": "새로 쓴 글이에요.",
             "checks": {"length_ok": True}, "failed_reasons": [], "needs_input": []}]}

    def test_notice_gets_the_measures_and_the_reply_texts_and_nothing_else_runs(self):
        with mock.patch("web.demo.run_live", return_value=copy.deepcopy(self.full)) as whole, \
                mock.patch("web.demo.run_live_pasted_replies") as pasted, \
                mock.patch("web.demo.run_live_one", return_value=self.made("prevention_notice")) as one:
            res = run(self.client, self.a, generator="prevention_notice", measures=["M2"], reply_texts=["답글 하나", "답글 둘"])
        self.assertEqual(res.status_code, 200, res.text)
        whole.assert_not_called()                                                  # 카드 전체를 다시 만들지 않는다
        pasted.assert_not_called()
        self.assertEqual(one.call_count, 1)
        card, generator = one.call_args.args
        kw = one.call_args.kwargs
        self.assertEqual((card.card_id, generator), (self.a, "prevention_notice"))
        self.assertEqual([m["id"] for m in kw["chosen_measures"]], ["M2"])
        self.assertEqual(kw["reply_texts"], ["답글 하나", "답글 둘"])
        self.assertIsNone(kw["review"])
        self.assertEqual((kw["key"], kw["model"]), ("test-key", "HCX-005"))
        r = res.json()
        self.assertEqual([d["draft_id"] for d in r["drafts"]], ["d9"])
        self.assertEqual(r["drafts"][0]["c7_flags"], [])                            # 전체 실행처럼 summarize 를 거친다
        self.assertEqual((r["partial"], r["flagged_count"], r["source"]), (True, 0, "live"))
        self.assertEqual(r["regenerated"], {"generator": "prevention_notice", "review_id": None, "pasted": False})

    def test_measures_default_to_the_cards_default(self):
        with mock.patch("web.demo.run_live_one", return_value=self.made("prevention_notice")) as one:
            run(self.client, self.a, generator="prevention_notice")
        self.assertEqual([m["id"] for m in one.call_args.kwargs["chosen_measures"]], ["M1"])
        self.assertEqual(one.call_args.kwargs["reply_texts"], [])

    def test_bundle_reply_keeps_its_place_in_the_card(self):
        """답글 순서(index)는 C6 가 고정 문장을 돌려 쓰는 기준이라 전체 실행 때와 같아야 한다."""
        for index, rid in enumerate(BUNDLE):
            with self.subTest(review=rid), mock.patch("web.demo.run_live_one", return_value=self.made("reply_draft", rid)) as one:
                r = run(self.client, self.a, generator="reply_draft", review_id=rid).json()
                kw = one.call_args.kwargs
                self.assertEqual((kw["review"].review_id, kw["index"]), (rid, index))
                self.assertEqual(r["regenerated"], {"generator": "reply_draft", "review_id": rid, "pasted": False})
                self.assertNotIn("pasted_reply_review_ids", r)

    def test_pasted_reply_is_marked_as_pasted(self):
        first = self.client.post("/api/reviews", json={"text": UNFAIR, "rating": 1}).json()["review"]["review_id"]
        second = self.client.post("/api/reviews", json={"text": OTHER_UNFAIR, "rating": 1}).json()["review"]["review_id"]
        self.client.post("/api/reviews", json={"text": PRAISE, "rating": 5})
        card = self.client.get("/api/cards").json()["cards"][0]["card"]
        self.assertNotIn(second, card["review_ids"])                                # 붙여넣은 리뷰는 카드 묶음 밖
        with mock.patch("web.demo.run_live_one", return_value=self.made("reply_draft", second)) as one:
            r = run(self.client, card["card_id"], generator="reply_draft", review_id=second).json()
        kw = one.call_args.kwargs
        self.assertEqual((kw["review"].review_id, kw["index"]), (second, 1))        # 붙여넣은 답글 대상 중 두 번째 (전체 실행과 같은 순서)
        self.assertEqual(kw["review"].input_method, "paste")
        self.assertEqual(r["regenerated"], {"generator": "reply_draft", "review_id": second, "pasted": True})
        self.assertEqual((r["pasted_reply_review_ids"], r["pasted_reply_skipped"]), ([second], []))
        self.assertEqual([d["target_review_id"] for d in r["drafts"]], [second])
        with mock.patch("web.demo.run_live_one", return_value=self.made("reply_draft", first)) as one:
            run(self.client, card["card_id"], generator="reply_draft", review_id=first)
        self.assertEqual(one.call_args.kwargs["index"], 0)

    def test_review_outside_the_card_is_404_before_any_model_call(self):
        praise = self.client.post("/api/reviews", json={"text": PRAISE, "rating": 5}).json()["review"]["review_id"]
        card_id = self.client.get("/api/cards").json()["cards"][0]["card"]["card_id"]
        with mock.patch("web.demo.run_live_one") as one:
            for rid in ("rv_ongi_020", "rv_nope", praise):
                self.assertEqual(run(self.client, card_id, generator="reply_draft", review_id=rid).status_code, 404, rid)
            self.assertEqual(run(self.client, card_id, generator="coupon_promo").status_code, 400)
            self.assertEqual(run(self.client, card_id, generator="reply_draft").status_code, 400)
        one.assert_not_called()

    def test_unknown_measure_is_400_like_the_whole_card(self):
        with mock.patch("web.demo.run_live_one") as one:
            res = run(self.client, self.a, generator="prevention_notice", measures=["M9"])
        self.assertEqual(res.status_code, 400)
        self.assertIn("M9", res.json()["error"]["message"])
        one.assert_not_called()

    def test_unexpected_error_becomes_a_screen_alert_not_a_500(self):
        with mock.patch("web.demo.run_live_one", side_effect=TimeoutError("The read operation timed out")):
            res = run(self.client, self.a, generator="reply_draft", review_id="rv_ongi_001")
        self.assertEqual(res.status_code, 502)
        self.assertIn("다시 눌러", res.json()["error"]["message"])
        self.assertNotIn("TimeoutError", res.json()["error"]["message"])

    def test_the_new_draft_is_remembered_and_the_others_are_kept(self):
        with mock.patch("web.demo.run_live", return_value=copy.deepcopy(self.full)):
            run(self.client, self.a)
        with mock.patch("web.demo.run_live_one", return_value=self.made("reply_draft", "rv_ongi_002", "d_new")):
            run(self.client, self.a, generator="reply_draft", review_id="rv_ongi_002")
        self.assertEqual(self.demo._drafts["d_new"], (self.a, "reply_draft", "rv_ongi_002"))
        self.assertEqual(self.demo._drafts["d4"], (self.a, "prevention_notice", None))       # 다른 글은 그대로 기억
        self.assertEqual(self.demo._drafts["d1"], (self.a, "reply_draft", "rv_ongi_001"))
        self.client.post("/api/drafts/d_new/approve", json={"text": "새로 쓴 글이에요.", "original": "새로 쓴 글이에요."})
        self.client.post("/api/drafts/d4/approve", json={"text": "공지입니다.", "original": "공지입니다."})
        self.assertEqual(self.store.approvals.meta, {"d_new": (self.a, "reply_draft"), "d4": (self.a, "prevention_notice")})
        self.assertEqual(self.demo.reply_target("d_new"), "rv_ongi_002")                      # 답글 승인을 리뷰 분석 서비스에 알릴 때 쓰는 값

    def test_live_without_a_key_is_blocked_with_the_same_sentence(self):
        client = TestClient(create_app(Demo(settings(self.tmp, mode="live"), source=FakeSource(), reason_model=lambda s, u: "")))
        cards = client.get("/api/cards").json()["cards"]
        for card, body in ((cards[0], {"generator": "prevention_notice"}), (cards[0], {"generator": "reply_draft", "review_id": "rv_ongi_001"}),
                           (cards[1], {"generator": "coupon_promo"})):
            res = run(client, card["card"]["card_id"], **body)
            self.assertEqual(res.status_code, 400, res.text)
            self.assertIn("키가 없어", res.json()["error"]["message"])


@unittest.skipUnless(HAS_C6, "MARKETING_DIR(C6 저장본) 없음")
class LiveOneThroughC6(unittest.TestCase):
    """live: C6 코드는 진짜로 돌고 HCX 호출(clova.call)만 가짜. 한 건만 만드는지, 전체 실행과 같은 조건인지."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        ensure_marketing_on_path(MARKETING)
        self.demo = Demo(settings(self.tmp, mode="live", clova_key="test-key"), source=PasteSource(),
                         reason_model=lambda system, user: "")
        self.client = TestClient(create_app(self.demo))
        cards = self.client.get("/api/cards").json()["cards"]
        self.a, self.b = cards[0]["card"]["card_id"], cards[1]["card"]["card_id"]

    @staticmethod
    def healthy(*_a, **_k):
        return {"content": AI_BODY, "won": 0.01}

    def whole(self):
        with mock.patch("clova.call", side_effect=self.healthy) as call:
            return run(self.client, self.a).json(), call.call_count

    def test_one_reply_uses_the_same_fixed_sentences_as_in_the_whole_run(self):
        from c6.measures import M1_SENTENCES, P1_SENTENCES
        full, full_calls = self.whole()
        replies = {d["target_review_id"]: d for d in full["drafts"] if d["generator"] == "reply_draft"}
        self.assertEqual(list(replies), BUNDLE)

        def fixed(text):   # 이 답글에 코드가 붙인 조치(M1)·요청사항(P1) 문장
            return [s for group in (M1_SENTENCES, P1_SENTENCES) for variants in group.values() for s in variants if s in text]
        self.assertEqual(len({tuple(fixed(d["text"])) for d in replies.values()}), 3)       # 전체 실행: 답글마다 문장이 다르다
        for rid in BUNDLE:
            with self.subTest(review=rid), mock.patch("clova.call", side_effect=self.healthy) as call:
                res = run(self.client, self.a, generator="reply_draft", review_id=rid)
                self.assertEqual(res.status_code, 200, res.text)
                r = res.json()
                self.assertEqual([slot(d) for d in r["drafts"]], [("reply_draft", rid)])
                new = r["drafts"][0]
                self.assertEqual(fixed(new["text"]), fixed(replies[rid]["text"]))            # 같은 자리의 문장 → 다른 답글과 겹치지 않음
                self.assertTrue(fixed(new["text"]))
                self.assertEqual((new["style"], new["stance"]), (replies[rid]["style"], replies[rid]["stance"]))
                self.assertEqual(new["evidence_ids"], replies[rid]["evidence_ids"])
                self.assertNotEqual(new["draft_id"], replies[rid]["draft_id"])               # 새 글
                self.assertEqual((new["card_id"], new["store_id"], new["model"]), (self.a, "store_ongi", "HCX-005"))
                # 점검 결과가 그대로 실린다. 다른 답글과 견주는 not_too_similar 만 빠진다 (한 건만 만들어 견줄 수 없음)
                self.assertEqual(set(new["checks"]), set(replies[rid]["checks"]) - {"not_too_similar"})
                self.assertIn("not_too_similar", replies[rid]["checks"])
                self.assertEqual(new["failed_reasons"], replies[rid]["failed_reasons"])
                self.assertLess(call.call_count, full_calls)                                 # 카드 전체보다 적게 부른다
                self.assertLessEqual(call.call_count, 3)                                     # 한 건: 첫 호출 + 다시 쓰기 최대 2번
                self.assertEqual((r["partial"], r["source"], r["kind"]), (True, "live", "complaint"))
                self.assertEqual([m["id"] for m in r["chosen_measures"]], ["M1"])
                self.assertIsInstance(r["needs_input"], list)
                self.assertEqual(r["elapsed_ms"], new["elapsed_ms"])

    def test_notice_alone_is_checked_against_the_replies_it_was_given(self):
        full, full_calls = self.whole()
        notice = next(d for d in full["drafts"] if d["generator"] == "prevention_notice")
        replies = [d["text"] for d in full["drafts"] if d["generator"] == "reply_draft"]
        with mock.patch("clova.call", side_effect=self.healthy) as call:
            res = run(self.client, self.a, generator="prevention_notice", measures=["M1"], reply_texts=replies)
        self.assertEqual(res.status_code, 200, res.text)
        r = res.json()
        self.assertEqual([slot(d) for d in r["drafts"]], [("prevention_notice", None)])
        new = r["drafts"][0]
        self.assertEqual(set(new["checks"]), set(notice["checks"]))                          # 전체 실행과 같은 점검 항목
        self.assertIn("notice_vs_reply", new["checks"])
        self.assertEqual(new["evidence_ids"], notice["evidence_ids"])
        self.assertNotEqual(new["draft_id"], notice["draft_id"])
        self.assertLess(call.call_count, full_calls)
        # 같은 글을 답글이라고 주면 '공지가 답글과 너무 비슷함'에 걸린다 = 넘겨준 답글과 실제로 견준다
        with mock.patch("clova.call", side_effect=self.healthy):
            same = run(self.client, self.a, generator="prevention_notice", measures=["M1"], reply_texts=[new["text"]]).json()
        self.assertIs(same["drafts"][0]["checks"]["notice_vs_reply"], False)
        self.assertIs(new["checks"]["notice_vs_reply"], True)

    def test_notice_carries_the_measure_the_owner_picked(self):
        with mock.patch("clova.call", side_effect=self.healthy):
            r = run(self.client, self.a, generator="prevention_notice", measures=["M2"]).json()
        self.assertEqual(r["chosen_measures"], [{"id": "M2", "text": "출발 전 품목 수량 확인"}])
        self.assertIn("M2", r["drafts"][0]["evidence_ids"])
        self.assertIs(r["drafts"][0]["checks"]["chosen_measure_included"], True)

    def test_pasted_review_reply_alone(self):
        rid = self.client.post("/api/reviews", json={"text": UNFAIR, "rating": 1}).json()["review"]["review_id"]
        card_id = self.client.get("/api/cards").json()["cards"][0]["card"]["card_id"]
        with mock.patch("clova.call", side_effect=self.healthy):
            full = run(self.client, card_id).json()
        whole = next(d for d in full["drafts"] if d["target_review_id"] == rid)
        with mock.patch("clova.call", side_effect=self.healthy) as call:
            res = run(self.client, card_id, generator="reply_draft", review_id=rid)
        self.assertEqual(res.status_code, 200, res.text)
        r = res.json()
        new = r["drafts"][0]
        self.assertEqual(slot(new), ("reply_draft", rid))
        self.assertEqual((new["stance"], new["style"]), (whole["stance"], whole["style"]))   # 억울한 리뷰: 전체 실행과 같은 태도
        self.assertEqual(new["stance"], "explain")
        self.assertEqual(new["evidence_ids"], whole["evidence_ids"])
        self.assertEqual(r["pasted_reply_review_ids"], [rid])
        self.assertIs(r["regenerated"]["pasted"], True)
        self.assertLessEqual(call.call_count, 3)

    def test_promo_alone_is_the_same_as_the_whole_promo_card(self):
        with mock.patch("clova.call", side_effect=self.healthy):
            full = run(self.client, self.b).json()
            r = run(self.client, self.b, generator="coupon_promo").json()
        self.assertEqual([slot(d) for d in r["drafts"]], [("coupon_promo", None)])
        self.assertEqual(set(r) - {"partial", "regenerated"}, set(full))
        self.assertEqual(set(r["drafts"][0]["checks"]), set(full["drafts"][0]["checks"]))
        self.assertEqual((r["reason_text"], r["basis_label"]), (full["reason_text"], full["basis_label"]))
        self.assertIs(r["partial"], True)

    def test_hcx_down_still_returns_the_one_draft_for_the_owner_to_fix(self):
        down = {"error": "TimeoutError: The read operation timed out"}
        for body in ({"generator": "prevention_notice"}, {"generator": "reply_draft", "review_id": "rv_ongi_001"}):
            with self.subTest(body=body), mock.patch("clova.call", side_effect=lambda *a, **k: dict(down)) as call:
                res = run(self.client, self.a, **body)
                self.assertEqual(res.status_code, 200, res.text)                     # 500 이 아니다
                (d,) = res.json()["drafts"]
                self.assertTrue(d["needs_input"])                                     # 화면에 '확인 필요'
                self.assertIn("죄송", d["text"])
                self.assertEqual(res.json()["flagged_count"], 1)
                self.assertLessEqual(call.call_count, 2)


# ── 다시 만들면 옛 글의 서버 승인 기록도 지운다 (replaces, 11/16) ─────────────────
def approve(client, draft_id, text="글"):
    return client.post(f"/api/drafts/{draft_id}/approve", json={"text": text, "original": text})


def shown(client):
    return [i["draft_id"] for i in client.get("/api/approvals").json()["items"]]


@unittest.skipUnless(HAS_C6, "MARKETING_DIR(C6 저장본) 없음")
class MockReplaces(unittest.TestCase):
    """mock: 저장 예시라 새 글 id 가 옛 글 id 와 같다. 그래도 새 글은 아직 승인 전이라 서버 기록에서 빠져야 화면과 맞는다."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.demo = Demo(settings(self.tmp), source=PasteSource(), storage=MemoryStore())
        self.client = TestClient(create_app(self.demo))
        self.other = TestClient(self.client.app)                                  # 다른 방문자
        cards = self.client.get("/api/cards").json()["cards"]
        self.a, self.b = cards[0]["card"]["card_id"], cards[1]["card"]["card_id"]
        self.full = run(self.client, self.a).json()
        self.ids = [d["draft_id"] for d in self.full["drafts"]]                  # 답글 3개 + 공지
        self.promo = run(self.client, self.b).json()["drafts"][0]["draft_id"]
        for draft_id in self.ids + [self.promo]:
            approve(self.client, draft_id)
        approve(self.other, self.ids[2], "다른 방문자의 승인")

    def test_one_regenerated_draft_drops_only_its_old_approval(self):
        old = self.full["drafts"][2]
        r = run(self.client, self.a, generator="reply_draft", review_id=old["target_review_id"], replaces=[old["draft_id"]])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["replaced_approvals"], 1)
        self.assertEqual(shown(self.client), [i for i in self.ids + [self.promo] if i != old["draft_id"]])   # 다른 글은 그대로
        self.assertEqual(shown(self.other), [old["draft_id"]])                                               # 다른 방문자도 그대로

    def test_whole_card_rerun_drops_the_old_approvals_of_that_card_only(self):
        r = run(self.client, self.a, measures=["M1"], replaces=self.ids)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["replaced_approvals"], len(r.json()["drafts"])), (4, 4))
        self.assertEqual(shown(self.client), [self.promo])                                                   # 카드 ⓑ 홍보글은 그대로
        self.assertEqual(shown(self.other), [self.ids[2]])

    def test_ids_never_approved_count_as_zero(self):
        r = run(self.client, self.a, generator="prevention_notice", replaces=["d_never_approved", self.ids[3], self.ids[3]])
        self.assertEqual(r.json()["replaced_approvals"], 1)                       # 같은 id 를 두 번 보내도 한 번
        self.assertEqual(run(self.client, self.a, generator="prevention_notice", replaces=[]).json()["replaced_approvals"], 0)

    def test_without_replaces_nothing_is_dropped_and_the_response_is_as_before(self):
        r = run(self.client, self.a, generator="reply_draft", review_id="rv_ongi_001").json()
        self.assertNotIn("replaced_approvals", r)
        self.assertNotIn("replaced_approvals", run(self.client, self.a).json())
        self.assertEqual(len(shown(self.client)), 5)

    def test_bad_replaces_is_rejected_before_anything_is_made_or_dropped(self):
        before = dict(self.demo._drafts)
        cases = [
            ({"replaces": [f"d_{i:04d}" for i in range(21)]}, 400),              # 21개
            ({"replaces": ["../etc"]}, 400), ({"replaces": ["d 1"]}, 400), ({"replaces": [""]}, 400),
            ({"replaces": ["d_" + "x" * 99]}, 400),                               # 101자
            ({"replaces": "d_1"}, 422), ({"replaces": [1]}, 422),                 # 목록·문자열이 아님 (다른 칸과 같은 ② 모양)
        ]
        for extra, status in cases:
            for base in ({}, {"generator": "prevention_notice"}):
                with self.subTest(extra=str(extra)[:40], one=bool(base)):
                    res = run(self.client, self.a, **base, **extra)
                    self.assertEqual(res.status_code, status, res.text)
                    if status == 400:
                        self.assertIn("replaces", res.json()["error"]["message"])
        self.assertEqual(len(shown(self.client)), 5)
        self.assertEqual(dict(self.demo._drafts), before)
        self.assertEqual(run(self.client, self.a, replaces=[f"d_{i:04d}" for i in range(20)]).status_code, 200)   # 20개까지

    def test_failed_generation_drops_nothing(self):
        res = run(self.client, "card_nope", generator="prevention_notice", replaces=self.ids)            # 지금 화면의 카드가 아님
        self.assertEqual(res.status_code, 404)
        res = run(self.client, self.a, generator="reply_draft", review_id="rv_nope", replaces=[self.ids[0]])
        self.assertEqual(res.status_code, 404)
        res = run(self.client, self.a, generator="coupon_promo", replaces=[self.ids[0]])
        self.assertEqual(res.status_code, 400)
        self.assertEqual(len(shown(self.client)), 5)


@unittest.skipUnless(HAS_C6, "MARKETING_DIR(C6 저장본) 없음")
class LiveReplaces(unittest.TestCase):
    """live: 생성기는 가짜. 새 글 id 가 옛 글과 다르다. 생성이 오류로 끝나면(HCX 오류·예상 못한 오류) 아무것도 지우지 않는다."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.demo = Demo(settings(self.tmp, mode="live", clova_key="test-key"), source=PasteSource(), storage=MemoryStore(),
                         reason_model=lambda system, user: "")
        self.client = TestClient(create_app(self.demo))
        self.a = self.client.get("/api/cards").json()["cards"][0]["card"]["card_id"]
        for draft_id in ("d_old1", "d_old2", "d_keep"):
            approve(self.client, draft_id)

    def made(self, draft_id="d_new"):
        return {"card_id": self.a, "kind": "complaint", "source": "live", "won": 0.3, "chosen_measures": [], "drafts": [
            {"draft_id": draft_id, "generator": "prevention_notice", "target_review_id": None, "text": "새 공지예요.",
             "checks": {}, "failed_reasons": [], "needs_input": []}]}

    def test_success_drops_the_old_ones(self):
        with mock.patch("web.demo.run_live_one", return_value=self.made()):
            r = run(self.client, self.a, generator="prevention_notice", replaces=["d_old1"]).json()
        self.assertEqual((r["replaced_approvals"], [d["draft_id"] for d in r["drafts"]]), (1, ["d_new"]))
        self.assertEqual(shown(self.client), ["d_old2", "d_keep"])
        with mock.patch("web.demo.run_live", return_value=self.made("d_new2")):
            r = run(self.client, self.a, replaces=["d_old2", "d_new"]).json()                           # 카드 전체
        self.assertEqual(r["replaced_approvals"], 1)
        self.assertEqual(shown(self.client), ["d_keep"])

    def test_generation_errors_drop_nothing(self):
        from web.generate import GenerateError
        cases = [("web.demo.run_live_one", {"generator": "prevention_notice"}, TimeoutError("timed out"), 502),
                 ("web.demo.run_live_one", {"generator": "prevention_notice"}, GenerateError("HCX 오류"), 400),
                 ("web.demo.run_live", {}, TimeoutError("timed out"), 502),
                 ("web.demo.run_live", {}, GenerateError("HCX 오류"), 400)]
        for target, body, error, status in cases:
            with self.subTest(target=target, error=type(error).__name__), mock.patch(target, side_effect=error):
                res = run(self.client, self.a, replaces=["d_old1", "d_old2"], **body)
                self.assertEqual(res.status_code, status, res.text)
                self.assertEqual(shown(self.client), ["d_old1", "d_old2", "d_keep"])
        with mock.patch("web.demo.run_live_one") as one:
            res = run(self.client, self.a, generator="prevention_notice", measures=["M9"], replaces=["d_old1"])   # 모르는 수칙
        self.assertEqual(res.status_code, 400)
        one.assert_not_called()
        self.assertEqual(shown(self.client), ["d_old1", "d_old2", "d_keep"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
