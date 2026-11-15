"""가상 배달앱 리뷰(source=app): 가게 공용 칸에 쌓이고 모든 사장님 화면에 보인다. 주문 메뉴(menu)도 돌려준다."""
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

def app_review(client, text="공깃밥이 빠졌어요", rating=2, **extra):
    return client.post(f"{API}/reviews", json={"text": text, "rating": rating, "source": "app"} | extra)


def ids(client, **params):
    return [r["review_id"] for r in client.get(f"{API}/reviews", params=params).json()["items"]]


def test_app_review_is_store_data_seen_by_every_owner_view(client):
    """가상 배달앱 리뷰는 누가 보내든 가게 공용 칸에 쌓이고, 모든 방문자의 목록·분석에 합쳐진다."""
    before = client.get(f"{API}/insight", params={"visitor_id": "visitor-b"}).json()["review_count"]
    res = app_review(client, visitor_id="visitor-a", menu=" 제육볶음  정식 ")
    assert res.status_code == 201
    review = res.json()["review"]
    rid = review["review_id"]
    assert rid == "rv_ongi_app_001" and review["source"] == "app" and review["menu"] == "제육볶음 정식"
    assert review["input_method"] == "paste" and review["data_origin"] == "synthetic"      # 계약 칸은 그대로
    for visitor in ({}, {"visitor_id": "visitor-a"}, {"visitor_id": "visitor-b"}):
        assert ids(client, **visitor).count(rid) == 1
    assert client.get(f"{API}/insight", params={"visitor_id": "visitor-b"}).json()["review_count"] == before + 1
    assert [r["review_id"] for r in client.get(f"{API}/reviews", params={"source": "app", "visitor_id": "visitor-b"}).json()["items"]] == [rid]


def test_pasted_reviews_stay_private_and_ids_do_not_collide(client):
    app_review(client)
    mine = client.post(f"{API}/reviews", json={"text": "국이 식어서 왔어요", "rating": 2, "visitor_id": "visitor-a"}).json()["review"]
    assert mine["review_id"] == "rv_ongi_paste_001" and mine["menu"] is None
    assert mine["review_id"] in ids(client, visitor_id="visitor-a")
    assert mine["review_id"] not in ids(client, visitor_id="visitor-b") and mine["review_id"] not in ids(client)
    assert len(set(ids(client, visitor_id="visitor-a"))) == len(ids(client, visitor_id="visitor-a"))
    assert app_review(client, "두 번째 리뷰예요").json()["review"]["review_id"] == "rv_ongi_app_002"


def test_reply_from_any_owner_view_shows_everywhere(client):
    rid = app_review(client, menu="계란말이").json()["review"]["review_id"]
    res = client.post(f"{API}/reviews/{rid}/status", json={"status": "replied", "reply_text": "죄송합니다. 바로 챙기겠습니다.", "visitor_id": "visitor-a"})
    assert res.status_code == 200 and res.json()["review"]["reply"]["text"].startswith("죄송합니다")
    for visitor in ({}, {"visitor_id": "visitor-b"}):          # 배달앱(공용)과 다른 사장님 화면
        row = next(r for r in client.get(f"{API}/reviews", params=visitor).json()["items"] if r["review_id"] == rid)
        assert row["status"] == "replied" and row["reply"]["text"].startswith("죄송합니다") and row["menu"] == "계란말이"
    one = client.get(f"{API}/reviews/{rid}", params={"visitor_id": "visitor-b"}).json()["review"]
    assert one["reply"]["text"].startswith("죄송합니다")


def test_menu_is_checked_and_since_works_for_every_visitor(client):
    assert app_review(client, menu="가" * 41).status_code == 400
    start = "2020-01-01T00:00:00+09:00"
    rid = app_review(client).json()["review"]["review_id"]
    got = client.get(f"{API}/reviews", params={"since": start, "visitor_id": "visitor-b"}).json()
    assert [r["review_id"] for r in got["items"]] == [rid] and got["server_time"]


def test_clearing_own_pasted_keeps_app_reviews_and_common_clear_removes_them(client):
    rid = app_review(client).json()["review"]["review_id"]
    client.post(f"{API}/reviews", json={"text": "맛있어요", "rating": 5, "visitor_id": "visitor-a"})
    client.delete(f"{API}/reviews/pasted", params={"visitor_id": "visitor-a"})
    assert ids(client, visitor_id="visitor-a").count(rid) == 1
    client.delete(f"{API}/reviews/pasted")                    # 방문자 없이 = 가게 공용 칸 (배달앱 리뷰 처음으로)
    assert rid not in ids(client, visitor_id="visitor-a") and rid not in ids(client)
