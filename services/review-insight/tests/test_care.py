"""고객응대 확장 시험: 가게 정보 · 손님 문의(공개) · 받은함 · 답변 초안 · 약속 장부. 키·네트워크 없이 돈다."""
import io
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import care, classify, inquiry, profile as prof, service
from app.classify import Classifier
from app.sources import capture
from app.sources.chat import Chat

KST = timezone(timedelta(hours=9))
MON = datetime(2026, 11, 16, tzinfo=KST)      # 월요일
API = "/api/review-insight"


def at(h, m=0, day=0):
    return MON + timedelta(days=day, hours=h, minutes=m)


@pytest.fixture(autouse=True)
def tmp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(classify, "RUNTIME_CACHE", tmp_path / "runtime.json")
    monkeypatch.setattr(classify, "USAGE_LOG", tmp_path / "logs" / "llm_usage.jsonl")
    monkeypatch.setattr(capture, "USAGE_LOG", tmp_path / "logs" / "llm_usage.jsonl")
    from app import care_api
    care_api.LIMITER._hits.clear()


@pytest.fixture
def client(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_classifier", Classifier("mock"))
    monkeypatch.setattr(main, "_reader", capture.CaptureReader("mock"))
    return TestClient(main.app)


def ask(client, text, store="store_ongi"):
    return client.post(f"{API}/public/{store}/inquiries", json={"text": text})


# ── 가게 정보 ──
def test_default_profile_is_synthetic_and_setup_done(client):
    p = client.get(f"{API}/profile", params={"now": "2026-11-16T15:00:00+09:00"}).json()
    assert p["data_origin"] == "synthetic" and p["setup"]["done"] and p["today"]["hours"] == "11:00-21:00"
    assert p["today"]["day"] == "월" and len(p["menu"]) == 6


def test_new_store_profile_starts_empty_with_missing_fields(monkeypatch):
    monkeypatch.setattr(prof, "DEFAULTS", prof.DEFAULTS.parent / "nope")
    state = prof.setup_state(prof.load("store_ongi"))
    assert not state["done"] and {m["field"] for m in state["missing"]} == {"basic.hours", "menu"}


def test_update_one_section_keeps_others_and_validates(client):
    res = client.put(f"{API}/profile", json={"changes": {"basic": {"hours": {"mon": "12:00-20:00"}, "parking": "주차 안 돼요"}}})
    assert res.status_code == 200 and res.json()["basic"]["parking"] == "주차 안 돼요" and len(res.json()["menu"]) == 6
    for bad in ({"basic": {"hours": {"monday": "12:00-20:00"}}}, {"basic": {"hours": {"mon": "정오"}}},
                {"menu": [{"name": "제육", "price": -1}]}, {"secret": {}}):
        r = client.put(f"{API}/profile", json={"changes": bad})
        assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.delete(f"{API}/profile").json()["basic"]["parking"].startswith("가게 앞")     # 처음 값으로


def test_profile_is_shared_by_the_store(client):
    """가게 정보는 가게 공용: 시연자 누가 고쳐도 손님 페이지와 다른 시연자에게 같은 값 (11/15)."""
    client.put(f"{API}/profile", json={"visitor_id": "visitor-a", "changes": {"reply": {"tone": "friendly"}}})
    assert client.get(f"{API}/profile").json()["reply"]["tone"] == "friendly"
    assert client.get(f"{API}/profile", params={"visitor_id": "visitor-b"}).json()["reply"]["tone"] == "friendly"


def test_customer_inquiry_reaches_every_owner_view(client):
    """손님은 사장님 쿠키가 없다 → 문의는 가게 공용 받은함. 방문자 칸이 있는 사장님 화면에서도 보여야 한다."""
    ask(client, "토요일 저녁 6시 15명 예약 되나요?")
    for visitor in (None, "visitor-a"):
        items = client.get(f"{API}/inbox", params={"kind": "inquiry", **({"visitor_id": visitor} if visitor else {})}).json()["items"]
        assert len(items) == 1 and items[0]["intent"] == "reservation"
    item = items[0]["item_id"]
    client.post(f"{API}/inquiries/{item}/status", json={"visitor_id": "visitor-a", "reply_text": "가능해요"})
    code = inquiry.load("store_ongi")[0]["code"]
    assert client.get(f"{API}/public/store_ongi/inquiries/{code}").json()["status"] == "answered"


def test_learned_answer_from_any_owner_view_answers_next_customer(client):
    ask(client, "와이파이 있어요?")
    item = client.get(f"{API}/inbox", params={"kind": "inquiry", "visitor_id": "visitor-a"}).json()["items"][0]["item_id"]
    client.post(f"{API}/inquiries/{item}/status", json={"visitor_id": "visitor-a", "reply_text": "네, 와이파이 있어요", "learn": True})
    assert ask(client, "와이파이 되나요?").json()["status"] == "answered"


def test_temporary_notice_expires_by_itself(client):
    r = client.post(f"{API}/profile/notices", json={"kind": "closed", "text": "11/17 임시휴무", "start": "2026-11-17", "end": "2026-11-17"})
    assert r.status_code == 201
    on = client.get(f"{API}/profile", params={"now": "2026-11-17T12:00:00+09:00"}).json()
    off = client.get(f"{API}/profile", params={"now": "2026-11-18T12:00:00+09:00"}).json()
    assert on["today"]["hours"] == "휴무" and on["active_notices"]
    assert off["today"]["hours"] == "11:00-21:00" and not off["active_notices"] and off["expired_notices"] == 1
    sold = client.post(f"{API}/profile/notices", json={"kind": "sold_out", "text": "제육 품절", "start": "2026-11-16", "end": "2026-11-16"})
    assert sold.status_code == 400                                              # 품절은 메뉴 이름 필요
    nid = r.json()["notice"]["id"]
    assert client.delete(f"{API}/profile/notices/{nid}").status_code == 200
    assert client.delete(f"{API}/profile/notices/{nid}").status_code == 404
    bad = client.post(f"{API}/profile/notices", json={"text": "x", "start": "2026-11-18", "end": "2026-11-17"})
    assert bad.status_code == 400


def test_menu_capture_demo_marks_existing(client):
    buf = io.BytesIO(); Image.new("RGB", (600, 900), "white").save(buf, format="PNG")
    body = client.post(f"{API}/profile/menu/capture", files={"file": ("m.png", buf.getvalue(), "image/png")}).json()
    assert body["demo"] and body["candidates"][0] == {"name": "제육볶음 정식", "price": 9500, "exists": True}


def test_menu_capture_live_parses_prices():
    def handle(request):
        return httpx.Response(200, json={"result": {"message": {"content": '[{"name":"제육볶음 정식","price":"9,500원"},{"name":"콜라","price":null},{"name":""}]'},
                                                    "finishReason": "stop", "usage": {}}})
    r = capture.CaptureReader("live", api_key="k", transport=httpx.MockTransport(handle))
    buf = io.BytesIO(); Image.new("RGB", (600, 900), "white").save(buf, format="PNG")
    assert r.read(buf.getvalue(), kind="menu").reviews == [{"name": "제육볶음 정식", "price": 9500}, {"name": "콜라", "price": None}]


# ── 문의: 바로 답할 것과 넘길 것 ──
@pytest.mark.parametrize("text,answered,flags,intent", [
    ("주차 되나요?", True, [], "question"),
    ("배달 되나요? 최소 주문 얼마예요?", True, [], "question"),
    ("일요일에 영업하나요?", True, [], "question"),
    ("제육볶음 정식 얼마예요? 많이 매워요?", True, [], "question"),
    ("토요일 저녁 6시 15명 예약 되나요?", False, [], "reservation"),
    ("땅콩 알레르기 있는데 제육 먹어도 되나요?", False, ["allergy"], "question"),
    ("어제 찌개에서 머리카락 나왔어요 환불해 주세요", False, ["hygiene", "refund"], "complaint"),
    ("배달 기사님이 반말하고 태도가 너무 불친절했어요", False, ["staff"], "complaint"),
    ("와이파이 있어요?", False, [], "question"),
])
def test_decide(text, answered, flags, intent):
    d = inquiry.decide(prof.load("store_ongi"), text, at(15))
    assert bool(d["auto_answer"]) == answered and d["needs_owner"] == flags and d["intent"] == intent


def test_auto_answer_uses_only_profile_values():
    d = inquiry.decide(prof.load("store_ongi"), "배달 되나요? 최소 주문 얼마예요?", at(15))
    assert "12,000원" in d["auto_answer"] and "2km" in d["auto_answer"]


def test_public_flow_auto_and_forward(client):
    info = client.get(f"{API}/public/store_ongi/info").json()
    assert info["name"].startswith("온기한식") and info["faq"] and "policy" not in info
    a = ask(client, "주차 되나요? 연락은 010-1234-5678")
    assert a.status_code == 201 and a.json()["status"] == "answered" and not a.json()["forwarded"]
    assert "010-1234" not in a.json()["text"]                                     # 손님 연락처는 가림
    f = ask(client, "토요일 저녁 6시 15명 예약 되나요?").json()
    assert f["forwarded"] and f["status"] == "waiting" and len(f["code"]) == 8
    assert client.get(f"{API}/public/store_ongi/inquiries/{f['code']}").json()["status"] == "waiting"
    assert client.get(f"{API}/public/store_ongi/inquiries/nope").status_code == 404
    assert ask(client, "x").status_code == 400 and ask(client, "주차?", store="store_none").status_code == 404


def test_public_api_needs_no_token_but_owner_api_does(client, monkeypatch):
    monkeypatch.setenv("APP_ACCESS_TOKEN", "team-secret")
    assert ask(client, "주차 되나요?").status_code == 201
    assert client.get(f"{API}/public/store_ongi/info").status_code == 200
    assert client.get(f"{API}/inbox").status_code == 401 and client.get(f"{API}/profile").status_code == 401


def test_public_rate_limit(client, monkeypatch):
    from app import main
    for _ in range(10):
        assert ask(client, "주차 되나요?").status_code == 201
    r = ask(client, "주차 되나요?")
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED" and r.json()["error"]["retryable"]
    _ = main


def test_owner_reply_learn_then_auto_answer(client):
    f = ask(client, "와이파이 있어요?").json()
    item = client.get(f"{API}/inbox", params={"kind": "inquiry", "open": True}).json()["items"][0]
    assert item["forward_reason"] and item["due_at"]
    r = client.post(f"{API}/inquiries/{item['item_id']}/status", json={"reply_text": "네, 매장에 와이파이 있어요", "learn": True})
    assert r.status_code == 200 and r.json()["learned"]["answer"] == "네, 매장에 와이파이 있어요"
    assert client.get(f"{API}/public/store_ongi/inquiries/{f['code']}").json()["answered_by"] == "사장님"
    again = ask(client, "와이파이 되나요?").json()                               # 비슷한 질문 → 배운 답
    assert again["status"] == "answered" and "와이파이 있어요" in again["answer"]
    assert any(x["q"] == "와이파이 있어요?" for x in client.get(f"{API}/public/store_ongi/info").json()["faq"])
    assert client.post(f"{API}/inquiries/{item['item_id']}/status", json={"status": "replied"}).status_code == 400
    assert client.post(f"{API}/inquiries/iq_x/status", json={"reply_text": "x"}).status_code == 404


def test_learned_answer_never_used_for_owner_flags():
    p = prof.load("store_ongi")
    p.answers.append(prof.Answer(id="an_1", question="땅콩 들어가요?", answer="안 들어가요"))
    assert inquiry.decide(p, "땅콩 들어가요?", at(15))["auto_answer"] is None


# ── 받은함 ──
def test_inbox_mixes_reviews_and_inquiries_owner_flags_first(client):
    ask(client, "토요일 저녁 6시 15명 예약 되나요?")
    ask(client, "땅콩 알레르기 있는데 제육 먹어도 되나요?")
    ask(client, "주차 되나요?")
    body = client.get(f"{API}/inbox").json()
    first = body["items"][0]
    assert first["kind"] == "inquiry" and first["needs_owner"] == ["allergy"] and first["open"]
    assert body["summary"]["by_kind"] == {"review": 40, "inquiry": 3} and body["summary"]["auto_answered"] == 1
    assert body["summary"]["needs_owner_open"] >= 1
    only = client.get(f"{API}/inbox", params={"kind": "inquiry", "intent": "reservation"}).json()
    assert only["count"] == 1 and only["items"][0]["intent"] == "reservation"
    assert client.get(f"{API}/inbox", params={"kind": "call"}).status_code == 400
    owner_only = client.get(f"{API}/inbox", params={"needs_owner": True}).json()["items"]
    assert owner_only and all(x["needs_owner"] for x in owner_only)


def test_inbox_review_complaint_has_due_and_intent(client):
    service.add_review("반찬이 또 빠져 있었어요", 2, store_id="store_ongi", source="app", received_at=at(15))
    items = client.get(f"{API}/inbox", params={"open": True, "kind": "review", "now": at(15, 10).isoformat()}).json()["items"]
    mine = next(x for x in items if x["source"] == "app")
    assert mine["intent"] == "complaint" and mine["remaining_seconds"] == 20 * 60 and mine["topic_names"] == ["포장 누락"]


# ── 답변 초안 ──
def _inq(client, text):
    ask(client, text)
    return inquiry.load("store_ongi")[-1]


def test_draft_template_in_mock(client):
    q = _inq(client, "땅콩 알레르기 있는데 제육 먹어도 되나요?")
    d = client.post(f"{API}/inquiries/{q['item_id']}/draft").json()
    assert d["method"] == "template" and d["demo"] and "확인" in d["draft"] and "괜찮" not in d["draft"]
    assert any("알레르기 재료" in f for f in d["facts"])


def _chat(answer):
    def handle(request):
        return httpx.Response(200, json={"result": {"message": {"content": answer}, "usage": {}}})
    return Chat("live", api_key="k", transport=httpx.MockTransport(handle))


def test_draft_live_passes_checks():
    service.RUNTIME.mkdir(parents=True, exist_ok=True)
    p = prof.load("store_ongi")
    item = inquiry.add("store_ongi", None, "배달 최소 주문 얼마예요?", at(15), inquiry.decide(p, "배달 최소 주문 얼마예요?", at(15)), False)
    d = care.draft("store_ongi", None, item["item_id"], at(15), _chat("안녕하세요. 최소 주문 금액은 12,000원이에요. 온기한식 드림"))
    assert d["method"] == "hcx" and d["checks"] == []


@pytest.mark.parametrize("bad,problem", [
    ("최소 주문은 10,000원이에요.", "근거에 없는 숫자"),
    ("죄송해요, 다음 주문은 무료로 드릴게요.", "정책에 없는 약속"),
])
def test_draft_live_falls_back_when_checks_fail(bad, problem):
    service.RUNTIME.mkdir(parents=True, exist_ok=True)
    p = prof.load("store_ongi")
    item = inquiry.add("store_ongi", None, "최소 주문 얼마예요?", at(15), inquiry.decide(p, "최소 주문 얼마예요?", at(15)), False)
    d = care.draft("store_ongi", None, item["item_id"], at(15), _chat(bad))
    assert d["method"] == "template" and any(problem in c for c in d["checks"]) and d["draft"] != bad


def test_allergy_check():
    assert "알레르기를 단정함" in care.check("땅콩은 안 들어가요. 확인했어요", [], ["allergy"], None)
    assert care.check("재료를 다시 확인하고 안내드릴게요", [], ["allergy"], None) == []


# ── 약속 장부 ──
def test_promise_ledger_states():
    assert care.promises_in("불편을 드려 죄송합니다. 포장할 때 한 번 더 확인하겠습니다. 온기한식 드림") == ["포장할 때 한 번 더 확인하겠습니다."]
    first = service.add_review("반찬이 또 빠져 있었어요", 2, store_id="store_ongi", source="app", received_at=at(15))
    service.set_status("store_ongi", None, first.review_id, "replied", reply_text="죄송합니다. 포장할 때 한 번 더 확인하겠습니다.", at=at(15, 10))
    c = Classifier("mock")
    watching = care.promises(c, "store_ongi", None, at(16))
    assert watching["items"][0]["state"] == "watching"
    assert care.promises(c, "store_ongi", None, at(15, 20, day=7))["items"][0]["state"] == "kept"
    service.add_review("반찬이 또 빠졌네요", 2, store_id="store_ongi", source="app", received_at=at(20))
    broke = care.promises(c, "store_ongi", None, at(21))
    assert broke["items"][0]["state"] == "broken" and broke["counts"]["broken"] == 1


def test_inquiry_promise_needs_owner_check(client):
    ask(client, "토요일 저녁 6시 15명 예약 되나요?")
    q = inquiry.load("store_ongi")[-1]
    client.post(f"{API}/inquiries/{q['item_id']}/status", json={"reply_text": "가능해요. 단체석 확인하고 다시 연락드릴게요."})
    rows = client.get(f"{API}/promises").json()["items"]
    assert rows[0]["kind"] == "inquiry" and rows[0]["state"] == "check"


def test_reset_by_one_visitor_keeps_shared_inquiries(client):
    ask(client, "토요일 저녁 6시 15명 예약 되나요?")
    assert client.delete(f"{API}/reviews/pasted", params={"visitor_id": "visitor-a"}).json() == {"deleted": 0}
    assert len(inquiry.load("store_ongi")) == 1                      # 시연자 한 명의 '다시 하기'는 공용 문의를 지우지 않음
    assert client.delete(f"{API}/reviews/pasted").json() == {"deleted": 0}
    assert inquiry.load("store_ongi") == []                          # 공용으로 부르면 지움


def test_inquiry_page_is_served(client):
    html = client.get("/s/store_ongi").text
    assert 'name="care-api"' in html and "문의 남기기" in html
    assert client.get("/s/store_none").status_code == 404
