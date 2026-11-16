"""방문자 구분 쿠키, 방문자별 승인 기록·붙여넣은 리뷰, 카드 추천 이유 저장 시험. CLOVA·네트워크는 부르지 않는다.

- 앞부분은 DB 없이 돈다 (메모리 구현).
- 'pg' 시험은 환경 변수 TEST_DB_HOST 등(shared/storage/testing.py)이 있을 때만 돌고, 없으면 건너뜀.
  서버 2대 = 같은 DB 에 따로 붙은 앱 둘 (연결 풀도 따로).

실행 (services/web 에서):  env -u APP_MODE PYTHONPATH=../.. python -m pytest -q tests/test_storage_web.py
"""
from __future__ import annotations

import copy
import os
import re
import time
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from shared.storage import COMMON_VISITOR, MemoryStore, StorageError, is_valid_visitor_id
from shared.storage.memory import MemoryApprovals
from shared.storage.testing import db_env, docker_ctl, open_test_db, wait_until_ready
from tests.test_web import HAS_C6, FakeSource, fixture, settings
from web.cards import plan_cards
from web.demo import Demo
from web.main import VISITOR_COOKIE, create_app
from web.sources import ReviewSource

CONTAINER = os.environ.get("TEST_DB_CONTAINER", "")


class VisitorSource(FakeSource):
    """리뷰 분석 서버 대신. 방문자마다 붙여넣은 리뷰를 따로 두고, 붙여넣은 글은 '포장 누락' 묶음에 들어간다."""

    def __init__(self):
        super().__init__()
        self.visitor = None
        self.books: dict = {}      # 방문자 → 붙여넣은 리뷰 (for_visitor 로 만든 사본들이 같이 쓴다)
        self.seen: list = []       # (요청 종류, 방문자)
        self.pasted = self.books.setdefault(None, [])

    def for_visitor(self, visitor):
        view = copy.copy(self)
        view.visitor = visitor
        view.pasted = self.books.setdefault(visitor, [])
        return view

    def reviews(self, store_id):
        self.seen.append(("reviews", self.visitor))
        return super().reviews(store_id)

    def insight(self, store_id):
        self.seen.append(("insight", self.visitor))
        found = copy.deepcopy(super().insight(store_id))
        group = found["groups"][0]
        for review in self.pasted:
            group["review_count"] += 1
            group["review_ids"].append(review["review_id"])
            group["evidence"].append({"review_id": review["review_id"], "quote": review["text"]})
            found["review_count"] += 1
            found["complaint_count"] += 1
        return found


class CountingModel:
    """이유 문장을 쓰는 가짜 모델. 근거 카드의 건수를 그대로 써서 검사를 통과한다."""

    def __init__(self):
        self.calls = 0

    def __call__(self, system, user):
        self.calls += 1
        count = re.search(r"불만 리뷰 (\d+)건", user).group(1)
        return f"포장 누락 불만이 {count}건, 모두 17~21시에 들어왔어요 [F1]\n재발 방지 공지를 올려요."


def make_app(tmp, source=None, storage=None, **kw):
    source = source or VisitorSource()
    # 맞춤 마케팅 프록시는 끈다: '처음부터 다시'가 이 시험에서 진짜 마케팅 서비스(8030)를 부르지 않게 (marketing_cleared 는 null)
    demo = Demo(settings(Path(tmp), **{"marketing_url": "off", **kw}), source=source, storage=storage if storage is not None else MemoryStore())
    return TestClient(create_app(demo)), demo, source


# ── 방문자 쿠키 ─────────────────────────────────────────────────────
def test_first_response_sets_a_visitor_cookie_and_later_ones_do_not(tmp_path):
    client, _, _ = make_app(tmp_path)
    first = client.get("/api/health")
    header = first.headers["set-cookie"]
    value = first.cookies[VISITOR_COOKIE]
    assert header.startswith(f"{VISITOR_COOKIE}={value}") and is_valid_visitor_id(value) and value != COMMON_VISITOR
    low = header.lower()
    assert "httponly" in low and "samesite=lax" in low and "path=/" in low and "max-age=" in low and "secure" not in low
    assert "set-cookie" not in client.get("/api/health").headers and "set-cookie" not in client.get("/api/briefing").headers
    assert client.cookies.get(VISITOR_COOKIE) == value


def test_cookie_also_comes_with_the_page_and_errors_but_not_static_files(tmp_path):
    client, _, source = make_app(tmp_path)
    assert VISITOR_COOKIE in client.get("/").cookies
    other = TestClient(client.app)
    source.down = True
    res = other.get("/api/briefing")                                  # 503 오류 응답에도 쿠키는 실린다
    assert res.status_code == 503 and VISITOR_COOKIE in res.cookies
    fresh = TestClient(client.app)
    assert "set-cookie" not in fresh.get("/static/app.js").headers


def test_cookie_is_secure_behind_https_only(tmp_path):
    client, _, _ = make_app(tmp_path)
    assert "secure" in TestClient(client.app).get("/api/health", headers={"x-forwarded-proto": "https"}).headers["set-cookie"].lower()
    assert "secure" in TestClient(client.app, base_url="https://testserver").get("/api/health").headers["set-cookie"].lower()


@pytest.mark.parametrize("bad", ["../etc/passwd", "a b", "x" * 65, "common", "a.b", ""])
def test_bad_or_reserved_cookie_values_are_replaced(tmp_path, bad):
    client, _, source = make_app(tmp_path)
    res = client.get("/api/briefing", headers={"cookie": f"{VISITOR_COOKIE}={bad}"})
    assert res.status_code == 200
    fresh = res.cookies[VISITOR_COOKIE]
    assert fresh != bad and is_valid_visitor_id(fresh) and fresh != COMMON_VISITOR
    assert source.seen[-1][1] == fresh                                    # 이 요청도 새 id 로 처리됨 (잘못된 값이 리뷰 서버로 가지 않음)


# ── 방문자끼리 섞이지 않는다 ─────────────────────────────────────────
def test_pasted_reviews_and_numbers_are_per_visitor(tmp_path):
    a_client, demo, source = make_app(tmp_path)
    b_client = TestClient(a_client.app)
    assert a_client.get("/api/briefing").json()["counts"]["review_count"] == 40
    assert b_client.get("/api/briefing").json()["counts"]["review_count"] == 40
    assert a_client.post("/api/reviews", json={"text": "A 만의 리뷰"}).status_code == 201
    a, b = a_client.get("/api/briefing").json(), b_client.get("/api/briefing").json()
    assert (a["counts"]["review_count"], len(a["pasted"])) == (41, 1) and a["pasted"][0]["text"] == "A 만의 리뷰"
    assert (b["counts"]["review_count"], b["counts"]["complaint_count"], b["pasted"]) == (40, 12, [])      # 다음 사람의 숫자는 그대로
    assert b_client.get("/api/insight").json()["review_count"] == 40 and a_client.get("/api/insight").json()["review_count"] == 41
    a_id, b_id = a_client.cookies[VISITOR_COOKIE], b_client.cookies[VISITOR_COOKIE]
    assert a_id != b_id and ("insight", a_id) in source.seen and ("reviews", b_id) in source.seen
    assert a_client.delete("/api/reviews/pasted").json() == {"deleted": 1}
    assert b_client.delete("/api/reviews/pasted").json() == {"deleted": 0}


def test_one_visitors_quote_never_shows_on_the_other_visitors_card(tmp_path):
    """두 방문자가 각자 한 건씩 붙여넣으면 리뷰 번호(…_paste_001)가 같다. 카드 계획을 번호로만 기억하면 근거 문장이 섞인다."""
    a_client, _, _ = make_app(tmp_path)
    b_client = TestClient(a_client.app)
    a_client.post("/api/reviews", json={"text": "A 가 쓴 문장"})
    b_client.post("/api/reviews", json={"text": "B 가 쓴 문장"})
    quotes = lambda client: [e["text"] for e in client.get("/api/cards").json()["cards"][0]["evidence"]]   # noqa: E731
    assert "A 가 쓴 문장" in quotes(a_client) and "B 가 쓴 문장" not in quotes(a_client)
    assert "B 가 쓴 문장" in quotes(b_client) and "A 가 쓴 문장" not in quotes(b_client)
    assert not any("쓴 문장" in q for q in quotes(TestClient(a_client.app)))                      # 아무것도 안 붙인 방문자


def test_approvals_are_per_visitor(tmp_path):
    a_client, demo, _ = make_app(tmp_path)
    b_client = TestClient(a_client.app)
    ok = a_client.post("/api/drafts/d_1/approve", json={"text": "고친 글", "original": "원문"}).json()
    assert ok["edited"] is True and set(ok) == {"draft_id", "status", "edited", "text", "approved_at", "mode"}   # 응답 모양은 그대로
    assert [i["draft_id"] for i in a_client.get("/api/approvals").json()["items"]] == ["d_1"]
    assert b_client.get("/api/approvals").json() == {"items": []}
    b_client.post("/api/drafts/d_1/approve", json={"text": "B 의 글", "original": "B 의 글"})        # 같은 초안 id 라도 따로
    assert a_client.get("/api/approvals").json()["items"][0]["text"] == "고친 글"
    assert b_client.get("/api/approvals").json()["items"][0]["text"] == "B 의 글"
    assert (Path(tmp_path) / "runtime" / "approvals.jsonl").read_text(encoding="utf-8").count("\n") == 2   # 파일에는 지금처럼 모두 덧붙음
    assert [a["draft_id"] for a in demo.approvals] == []                                            # 공용 기록은 비어 있음


def test_visitor_is_passed_to_the_review_service_only_for_paste_delete_and_reads():
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, request.url.path, dict(request.url.params), request.content))
        return httpx.Response(200, json={"items": [], "count": 0, "deleted": 0})
    client = httpx.Client(base_url="http://review", transport=httpx.MockTransport(handler))
    source = ReviewSource("http://review", client=client)
    scoped = source.for_visitor("vis_123")
    scoped.store("store_ongi"); scoped.reviews("store_ongi"); scoped.insight("store_ongi")
    scoped.paste("store_ongi", "글", 3, "baemin"); scoped.reset_pasted("store_ongi")
    source.reviews("store_ongi"); source.insight("store_ongi"); source.paste("store_ongi", "글"); source.reset_pasted("store_ongi")
    assert "visitor_id" not in seen[0][2]                                                      # 가게 정보는 방문자와 무관
    assert seen[1][2] == {"store_id": "store_ongi", "visitor_id": "vis_123"} and seen[2][2]["visitor_id"] == "vis_123"
    assert b'"visitor_id":"vis_123"' in seen[3][3].replace(b" ", b"") and seen[4][2]["visitor_id"] == "vis_123"
    assert all("visitor_id" not in s[2] and b"visitor_id" not in s[3] for s in seen[5:])       # 방문자를 안 주면 지금까지와 같은 요청
    assert source.visitor_id is None                                                           # for_visitor 는 사본을 만든다


# ── 카드 추천 이유 저장 ──────────────────────────────────────────────
def live(tmp, storage, fake_model, **kw):
    """live 모드 Demo (카드 ⓐ 만). kw 는 Settings 값 (예: model="HCX-007")."""
    return Demo(settings(Path(tmp), mode="live", snapshot_path=Path(tmp) / "none.json", **kw), source=VisitorSource(),
                reason_model=fake_model, storage=storage)


def test_saved_reason_means_no_model_call(tmp_path):
    store, first_model, second_model = MemoryStore(), CountingModel(), CountingModel()
    first = live(tmp_path, store, first_model).cards()["cards"][0]
    assert first["reason_source"] == "HCX-005 (검사기 통과)" and first_model.calls == 1
    again = live(tmp_path, store, second_model).cards()["cards"][0]            # 서버를 새로 켠 것처럼: 메모리 기억은 없고 저장소만 같음
    assert second_model.calls == 0
    assert again["card"]["reason_text"] == first["card"]["reason_text"] and again["reason_source"] == first["reason_source"]
    assert again["checked_text"] == first["checked_text"] and again["problems"] == []
    assert "[F1]" not in again["card"]["reason_text"] and "3건" in again["card"]["reason_text"]


def test_saved_reason_is_shared_by_every_visitor_with_the_same_evidence(tmp_path):
    store, model = MemoryStore(), CountingModel()
    demo = live(tmp_path, store, model)
    demo.cards(visitor="visitor_one_1234")
    demo.cards(visitor="visitor_two_1234")
    assert model.calls == 1                                                    # 방문자와 무관하게 근거가 같으면 같은 문장


def test_changed_evidence_prompt_or_model_asks_the_model_again(tmp_path, monkeypatch):
    store, model = MemoryStore(), CountingModel()
    demo = live(tmp_path, store, model)
    demo.cards()
    assert model.calls == 1
    demo.paste("새 불만", None, None, visitor="visitor_new_1234")             # 근거가 달라짐 (3건 → 4건)
    text = demo.cards(visitor="visitor_new_1234")["cards"][0]["card"]["reason_text"]
    assert model.calls == 2 and "4건" in text
    live(tmp_path, store, model).cards()                                       # 처음 근거는 그대로 저장돼 있음
    assert model.calls == 2
    live(tmp_path, store, model, model="HCX-007").cards()                      # 모델이 바뀜
    assert model.calls == 3
    monkeypatch.setattr(Demo, "REASON_SYSTEM", Demo.REASON_SYSTEM + " (바뀐 규칙)")
    live(tmp_path, store, model).cards()                                       # 프롬프트가 바뀜
    assert model.calls == 4
    from web.demo import REASON_VERSION                                        # 지금 버전이 무엇이든 그와 다른 값으로 올린다
    monkeypatch.setattr("web.demo.REASON_VERSION", REASON_VERSION + "-next")
    live(tmp_path, store, model).cards()                                       # 버전을 올림
    assert model.calls == 5


def test_a_saved_sentence_that_fails_todays_rules_is_not_used(tmp_path):
    store, model = MemoryStore(), CountingModel()
    demo = live(tmp_path, store, model)
    plan = plan_cards(fixture("insight_ongi.json"), [], "store_ongi")[0]
    store.card_reasons.put("store_ongi", plan.card.card_id, demo._reason_key(plan), reason_text="만족도가 높아질 수 있어요 [F1]",
                           source="HCX-005 (검사기 통과)", model="HCX-005")
    shown = demo.cards()["cards"][0]
    assert model.calls == 1 and "3건" in shown["card"]["reason_text"]


def test_only_a_passing_model_sentence_is_saved(tmp_path):
    store = MemoryStore()
    demo = live(tmp_path, store, lambda system, user: "만족도가 높아질 수 있어요[F1].")           # 검사에 걸리는 문장만 나오는 모델
    shown = demo.cards()["cards"][0]
    assert "불통과" in shown["reason_source"]
    assert store.card_reasons._rows == {}                                                       # 실패한 문장은 저장하지 않음
    mock_demo = Demo(settings(Path(tmp_path)), source=VisitorSource(), storage=store)           # mock 은 고정 문장이라 저장하지 않음
    mock_demo.cards()
    assert store.card_reasons._rows == {}


class _Broken:
    """모든 호출이 실패하는 저장소 부품."""

    def __init__(self, **methods):
        for name in ("get", "put", "save", "list"):
            setattr(self, name, methods.get(name, self._boom))

    @staticmethod
    def _boom(*_a, **_k):
        raise StorageError("DB 에 닿지 못했습니다 (PoolTimeout)")


class _DownStore:
    kind = "postgres"

    def __init__(self):
        self.approvals, self.card_reasons, self.reports = _Broken(), _Broken(), _Broken()


def test_cards_still_show_when_the_reason_store_fails(tmp_path):
    model = CountingModel()
    demo = live(tmp_path, _DownStore(), model)
    shown = demo.cards()["cards"][0]
    assert shown["reason_source"] == "HCX-005 (검사기 통과)" and "3건" in shown["card"]["reason_text"] and model.calls == 1
    demo.cards()
    assert model.calls == 1                                                    # 메모리 기억은 그대로 (저장소가 죽어도 매 요청 부르지 않음)


def test_approval_survives_a_database_outage_with_a_warning(tmp_path):
    client, demo, _ = make_app(tmp_path, storage=_DownStore())
    res = client.post("/api/drafts/d_9/approve", json={"text": "글", "original": "글"})
    assert res.status_code == 200
    body = res.json()
    assert "DB" in body["warning"] and body["draft_id"] == "d_9"
    assert [i["draft_id"] for i in client.get("/api/approvals").json()["items"]] == ["d_9"]   # 이 서버 화면에는 남음
    assert not (Path(tmp_path) / "runtime" / "approvals.jsonl").exists()                       # DB 방식이면 파일에 쓰지 않음


class FlakyApprovals(MemoryApprovals):
    """켜고 끌 수 있는 승인 저장소. 꺼져 있으면 DB 에 닿지 못한 것처럼, poison 글이면 DB 가 받지 않은 것처럼 군다."""

    def __init__(self):
        super().__init__()
        self.up = True
        self.meta = {}

    def save(self, store_id, visitor_id, entry, *, card_id=None, kind=None):
        if not self.up:
            raise StorageError("DB 에 닿지 못했습니다 (PoolTimeout)")
        if entry["text"] == "poison":
            raise ValueError("DB 가 받지 않는 글")
        self.meta[entry["draft_id"]] = (card_id, kind)
        super().save(store_id, visitor_id, dict(entry), card_id=card_id, kind=kind)

    def list(self, store_id, visitor_id):
        if not self.up:
            raise StorageError("DB 에 닿지 못했습니다 (PoolTimeout)")
        return super().list(store_id, visitor_id)


def flaky_app(tmp_path):
    store = _DownStore()
    store.approvals = FlakyApprovals()
    client, demo, _ = make_app(tmp_path, storage=store)
    return client, demo, store.approvals


def approve(client, draft_id, text="글", **more):
    return client.post(f"/api/drafts/{draft_id}/approve", json={"text": text, "original": text, **more})


def shown(client):
    return [i["draft_id"] for i in client.get("/api/approvals").json()["items"]]


def test_approvals_made_during_an_outage_are_saved_when_the_database_returns(tmp_path):
    client, demo, db = flaky_app(tmp_path)
    assert "warning" not in approve(client, "d_before").json()
    db.up = False
    assert "DB" in approve(client, "d_during_1", card_id="card_x", kind="reply_draft").json()["warning"]
    assert "DB" in approve(client, "d_during_2").json()["warning"]
    assert shown(client) == ["d_during_1", "d_during_2"]                           # DB 를 못 읽는 동안은 이 서버가 든 것만
    db.up = True
    assert shown(client) == ["d_before", "d_during_1", "d_during_2"]              # 돌아오면 승인한 순서대로 DB 에 들어감
    assert demo._pending == [] and db.meta["d_during_1"] == ("card_x", "reply_draft")
    assert "warning" not in approve(client, "d_after").json()
    assert shown(client) == ["d_before", "d_during_1", "d_during_2", "d_after"]


def test_the_next_approval_also_writes_what_was_held(tmp_path):
    client, demo, db = flaky_app(tmp_path)
    db.up = False
    approve(client, "d_during")
    approve(client, "d_during", text="멈춘 동안 다시 고친 글")                       # 같은 초안은 마지막 것만 든다
    assert len(demo._pending) == 1
    db.up = True
    assert "warning" not in approve(client, "d_after").json()                      # 목록을 안 열어도 다음 승인 때 같이 쓴다
    assert demo._pending == [] and list(db.meta) == ["d_during", "d_after"]
    assert client.get("/api/approvals").json()["items"][0]["text"] == "멈춘 동안 다시 고친 글"


def test_held_approvals_stay_with_their_own_visitor(tmp_path):
    client, demo, db = flaky_app(tmp_path)
    other = TestClient(client.app)
    db.up = False
    approve(client, "d_mine")
    assert shown(other) == [] and shown(client) == ["d_mine"]
    db.up = True
    assert shown(other) == [] and shown(client) == ["d_mine"]                     # 다른 방문자의 요청이 대신 써 줘도 주인은 그대로


def test_a_record_the_database_refuses_does_not_block_the_ones_behind_it(tmp_path):
    client, demo, db = flaky_app(tmp_path)
    db.up = False
    approve(client, "d_bad", text="poison")
    approve(client, "d_good")
    db.up = True
    assert shown(client) == ["d_good"] and demo._pending == []                    # 받지 않는 기록은 빼고 뒤의 것을 쓴다
    refused = approve(client, "d_bad_again", text="poison").json()
    assert "저장하지 못했어요" in refused["warning"] and demo._pending == []


# ── 승인 기록 지우기 (DELETE /api/approvals, 완료 화면의 '처음부터 다시') ──────
def test_clearing_approvals_removes_only_this_visitors_records(tmp_path):
    a_client, demo, _ = make_app(tmp_path)
    b_client = TestClient(a_client.app)
    approve(a_client, "d_1"), approve(a_client, "d_2"), approve(b_client, "d_1", text="B 의 글")
    res = a_client.delete("/api/approvals")
    assert res.status_code == 200 and res.json() == {"deleted": 2, "marketing_cleared": None}
    assert shown(a_client) == []
    assert b_client.get("/api/approvals").json()["items"][0]["text"] == "B 의 글"                     # 다른 방문자의 기록은 그대로
    assert a_client.delete("/api/approvals").json() == {"deleted": 0, "marketing_cleared": None}    # 지울 것이 없어도 200
    assert (Path(tmp_path) / "runtime" / "approvals.jsonl").read_text(encoding="utf-8").count("\n") == 3   # 덧붙이기만 하는 파일은 그대로
    approve(a_client, "d_3")
    assert shown(a_client) == ["d_3"]                                                               # 지운 뒤 새 승인만 보인다


def test_a_visitor_without_a_cookie_clears_nothing_of_anyone_else(tmp_path):
    client, demo, _ = make_app(tmp_path)
    approve(client, "d_1")
    stranger = TestClient(client.app)                                                               # 쿠키 없는 첫 요청 = 새 방문자
    assert stranger.delete("/api/approvals").json() == {"deleted": 0, "marketing_cleared": None}
    assert shown(client) == ["d_1"]


class DownWhenOff(FlakyApprovals):
    """꺼져 있으면 지우기도 DB 에 닿지 못한다."""

    def clear(self, store_id, visitor_id):
        if not self.up:
            raise StorageError("DB 에 닿지 못했습니다 (PoolTimeout)")
        return super().clear(store_id, visitor_id)


def test_clearing_during_an_outage_reports_it_and_keeps_everything(tmp_path):
    store = _DownStore()
    store.approvals = db = DownWhenOff()
    client, demo, _ = make_app(tmp_path, storage=store)
    other = TestClient(client.app)
    approve(client, "d_saved")
    db.up = False
    approve(client, "d_mine"), approve(other, "d_theirs")
    res = client.delete("/api/approvals")
    assert res.status_code == 503 and "지우지 못했어요" in res.json()["error"]["message"]
    assert len(demo._pending) == 2                                                  # 못 지웠으면 들고 있던 것도 그대로
    db.up = True
    assert client.delete("/api/approvals").json()["deleted"] == 2                   # DB 가 돌아오면: 저장돼 있던 것 + 멈춘 동안 승인한 것
    assert shown(client) == [] and shown(other) == ["d_theirs"] and demo._pending == []


def test_clearing_also_drops_what_this_server_still_holds_for_that_visitor_only(tmp_path):
    class SaveDown(MemoryApprovals):                                                # 쓰기만 안 되는 DB (지우기·읽기는 됨)
        def save(self, *a, **k):
            raise StorageError("DB 에 닿지 못했습니다 (PoolTimeout)")
    store = _DownStore()
    store.approvals = SaveDown()
    client, demo, _ = make_app(tmp_path, storage=store)
    other = TestClient(client.app)
    approve(client, "d_mine_1"), approve(client, "d_mine_2"), approve(other, "d_theirs")
    assert len(demo._pending) == 3
    assert client.delete("/api/approvals").json()["deleted"] == 2                   # 이 방문자가 승인해 둔 2건 (아직 DB 에 못 쓴 것)
    assert [p[1]["draft_id"] for p in demo._pending] == ["d_theirs"]                # 다른 방문자의 밀린 승인은 남는다
    assert shown(client) == [] and shown(other) == ["d_theirs"]


def test_clearing_with_a_store_that_cannot_clear_is_a_clean_503(tmp_path):
    client, _, _ = make_app(tmp_path, storage=_DownStore())                         # 지우기를 못 하는 저장소 (모든 호출 실패)
    res = client.delete("/api/approvals")
    assert res.status_code == 503 and "error" in res.json()


# ── 승인 기록의 카드·종류 칸 ─────────────────────────────────────────
class RecordingApprovals(MemoryApprovals):
    def __init__(self):
        super().__init__()
        self.meta = {}

    def save(self, store_id, visitor_id, entry, *, card_id=None, kind=None):
        self.meta[entry["draft_id"]] = (card_id, kind)
        super().save(store_id, visitor_id, entry, card_id=card_id, kind=kind)


def recording_store():
    store = MemoryStore()
    store.approvals = RecordingApprovals()
    return store


def test_approval_gets_card_and_kind_from_what_this_server_generated_or_from_the_screen(tmp_path):
    store = recording_store()
    demo = Demo(settings(Path(tmp_path)), source=VisitorSource(), storage=store)
    demo._remember_drafts("card_ongi_a", {"drafts": [{"draft_id": "d_known", "generator": "reply_draft"}]})
    demo.approve("d_known", "글", "글")
    demo.approve("d_unknown", "글", "글")                                          # 다른 서버가 만든 초안이면 비어 있음
    demo.approve("d_sent", "글", "글", card_id="card_ongi_b", kind="coupon_promo")    # 화면이 보내 주면 그 값
    assert store.approvals.meta == {"d_known": ("card_ongi_a", "reply_draft"), "d_unknown": (None, None),
                                    "d_sent": ("card_ongi_b", "coupon_promo")}


@pytest.mark.skipif(not HAS_C6, reason="MARKETING_DIR(C6 저장본) 없음")
def test_run_then_approve_records_the_card_the_draft_came_from(tmp_path):
    store = recording_store()
    client, _, _ = make_app(tmp_path, storage=store)
    cards = client.get("/api/cards").json()["cards"]
    card_id = cards[0]["card"]["card_id"]
    drafts = client.post(f"/api/cards/{card_id}/run").json()["drafts"]
    pick = next(d for d in drafts if d["generator"] == "prevention_notice")
    client.post(f"/api/drafts/{pick['draft_id']}/approve", json={"text": pick["text"], "original": pick["text"]})
    assert store.approvals.meta[pick["draft_id"]] == (card_id, "prevention_notice")


# ── DB 있는 시험: 서버 2대 ───────────────────────────────────────────
@pytest.fixture
def two_servers(tmp_path):
    one, two = open_test_db("ic26-web-1"), open_test_db("ic26-web-2")
    if one is None:
        pytest.skip("TEST_DB_HOST 없음 (PostgreSQL 시험은 건너뜀)")
    store_id = "store_t" + uuid.uuid4().hex[:8]
    review_service = VisitorSource()                       # 리뷰 분석 서버는 따로 한 대 (두 WAS 가 같이 부름)
    model_one, model_two = CountingModel(), CountingModel()
    apps = []
    for n, (db, model) in enumerate(((one, model_one), (two, model_two)), 1):
        demo = Demo(settings(Path(tmp_path) / f"was{n}", mode="live", snapshot_path=Path(tmp_path) / "none.json", store_id=store_id),
                    source=review_service, reason_model=model, storage=db)
        apps.append(TestClient(create_app(demo)))
    yield apps, (model_one, model_two), (one, two), store_id, tmp_path
    one.close()
    two.close()


def same_visitor(client, cookie):
    client.cookies.set(VISITOR_COOKIE, cookie)
    return client


def test_pg_approval_on_one_server_shows_on_the_other(two_servers):
    (one, two), _, (db, _), store_id, tmp = two_servers
    first = one.get("/api/health")
    me = first.cookies[VISITOR_COOKIE]
    one.post("/api/drafts/d_a/approve", json={"text": "고친 글", "original": "원문"})
    one.post("/api/drafts/d_b/approve", json={"text": "글", "original": "글"})
    on_two = same_visitor(two, me).get("/api/approvals").json()["items"]                       # 새로 고침이 다른 서버로 감
    assert [i["draft_id"] for i in on_two] == ["d_a", "d_b"] and on_two[0]["edited"] is True and on_two[0]["text"] == "고친 글"
    assert set(on_two[0]) == {"draft_id", "status", "edited", "text", "approved_at", "mode"}
    assert TestClient(two.app).get("/api/approvals").json() == {"items": []}                   # 다른 방문자는 못 봄
    two.post("/api/drafts/d_a/approve", json={"text": "두 번째 서버에서 다시", "original": "원문"})
    assert one.get("/api/approvals").json()["items"][-1]["text"] == "두 번째 서버에서 다시"
    assert not (Path(tmp) / "was1" / "runtime" / "approvals.jsonl").exists()                   # DB 방식이면 서버 디스크에 쓰지 않음


def test_pg_clearing_on_one_server_shows_on_the_other_and_spares_other_visitors(two_servers):
    (one, two), _, (db, _), store_id, _ = two_servers
    me = one.get("/api/health").cookies[VISITOR_COOKIE]
    approve(one, "d_a"), approve(one, "d_b")
    guest = TestClient(two.app)                                                                 # 다른 방문자
    approve(guest, "d_a", text="다른 방문자의 글")
    assert same_visitor(two, me).delete("/api/approvals").json()["deleted"] == 2             # 지우는 요청이 다른 서버로 가도
    assert shown(one) == [] and shown(guest) == ["d_a"]
    rows = db.run(lambda c: c.execute("SELECT draft_id, approved_text FROM approvals WHERE store_id=%s", (store_id,)).fetchall())
    assert [(r["draft_id"], r["approved_text"]) for r in rows] == [("d_a", "다른 방문자의 글")]


def test_pg_paste_goes_through_to_the_shared_review_service_for_both_servers(two_servers):
    (one, two), _, _, _, _ = two_servers
    me = one.get("/api/health").cookies[VISITOR_COOKIE]
    one.post("/api/reviews", json={"text": "서버 하나에서 붙여넣음"})
    assert same_visitor(two, me).get("/api/briefing").json()["counts"]["review_count"] == 41
    assert TestClient(two.app).get("/api/briefing").json()["counts"]["review_count"] == 40


def test_pg_saved_reason_from_one_server_means_the_other_does_not_call_the_model(two_servers):
    (one, two), (model_one, model_two), (db, _), store_id, _ = two_servers
    first = one.get("/api/cards").json()["cards"][0]
    assert model_one.calls == 1
    second = two.get("/api/cards").json()["cards"][0]
    assert model_two.calls == 0 and second["card"]["reason_text"] == first["card"]["reason_text"]
    row = db.run(lambda c: c.execute("SELECT card_id, reason_text, source, model FROM card_reasons WHERE store_id=%s", (store_id,)).fetchall())
    assert len(row) == 1 and row[0]["card_id"] == f"card_{store_id[len('store_'):]}_a" and row[0]["source"] == "HCX-005 (검사기 통과)"
    assert row[0]["model"] == "HCX-005" and "[F1]" in row[0]["reason_text"]


def test_pg_approval_rows_keep_card_and_kind(two_servers):
    (one, _), _, (db, _), store_id, _ = two_servers
    demo = one.app.state.demo
    demo._remember_drafts("card_x_a", {"drafts": [{"draft_id": "d_k", "generator": "reply_draft"}]})
    one.post("/api/drafts/d_k/approve", json={"text": "글", "original": "글"})
    one.post("/api/drafts/d_s/approve", json={"text": "글", "original": "글", "card_id": "card_x_b", "kind": "coupon_promo"})
    rows = db.run(lambda c: c.execute("SELECT draft_id, card_id, kind, mode, status FROM approvals WHERE store_id=%s ORDER BY id", (store_id,)).fetchall())
    assert rows == [{"draft_id": "d_k", "card_id": "card_x_a", "kind": "reply_draft", "mode": "live", "status": "approved"},
                    {"draft_id": "d_s", "card_id": "card_x_b", "kind": "coupon_promo", "mode": "live", "status": "approved"}]


@pytest.mark.skipif(not (db_env() and CONTAINER), reason="TEST_DB_CONTAINER 없음 (연결이 끊겼다 돌아오는 시험은 건너뜀)")
def test_pg_requests_continue_after_the_database_goes_away_and_comes_back(tmp_path):
    db = open_test_db("ic26-web-restart", connect_timeout=2.0, retry_after=1.0)
    store_id = "store_t" + uuid.uuid4().hex[:8]
    model = CountingModel()
    demo = Demo(settings(Path(tmp_path) / "was", mode="live", snapshot_path=Path(tmp_path) / "none.json", store_id=store_id),
                source=VisitorSource(), reason_model=model, storage=db)
    client = TestClient(create_app(demo))
    try:
        me = client.get("/api/health").cookies[VISITOR_COOKIE]
        client.post("/api/drafts/d_before/approve", json={"text": "멈추기 전", "original": "멈추기 전"})
        docker_ctl(CONTAINER, "stop")
        try:
            started = time.monotonic()
            down = client.post("/api/drafts/d_during/approve", json={"text": "멈춘 동안", "original": "멈춘 동안"})
            assert down.status_code == 200 and "DB" in down.json()["warning"]           # 500 이 아님. 이 서버 화면에만 남음
            assert [i["draft_id"] for i in client.get("/api/approvals").json()["items"]] == ["d_during"]
            assert client.get("/api/cards").status_code == 200                          # 화면은 뜬다 (이유 문장은 모델이 씀)
            assert time.monotonic() - started < 15
        finally:
            docker_ctl(CONTAINER, "start")
        wait_until_ready()
        time.sleep(1.2)
        deadline = time.monotonic() + 20
        while True:
            items = client.get("/api/approvals").json()["items"]
            if [i["draft_id"] for i in items] == ["d_before", "d_during"]:             # DB 에서 읽음. 멈춘 동안 승인한 것도 이제 들어감
                break
            assert time.monotonic() < deadline, items
            time.sleep(0.5)
        client.post("/api/drafts/d_after/approve", json={"text": "돌아온 뒤", "original": "돌아온 뒤"})
        assert [i["draft_id"] for i in client.get("/api/approvals").json()["items"]] == ["d_before", "d_during", "d_after"]
        saved = db.run(lambda c: c.execute("SELECT draft_id FROM approvals WHERE store_id=%s ORDER BY saved_at, id", (store_id,)).fetchall())
        assert [r["draft_id"] for r in saved] == ["d_before", "d_during", "d_after"] and demo._pending == []
        assert client.cookies[VISITOR_COOKIE] == me
    finally:
        db.close()
