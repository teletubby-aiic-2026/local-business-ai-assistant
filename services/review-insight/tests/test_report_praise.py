"""보고서의 '손님 칭찬 요약'(praise 칸) 시험: 일일·월간 응답과 월간 인쇄 페이지.
키·네트워크 없이 돈다 (분류는 규칙 분류). 시각은 모두 고정값으로 넘긴다.

확인하는 것
- 숫자(별점 4~5점·긍정 리뷰·칭찬 주제 상위·인기 메뉴 TOP 3)가 합성 자료(store_ongi)를 직접 센 값과 같다
- 그 보고서 기간 밖의 리뷰는 세지 않는다. 칭찬이 없으면 빈 목록과 null (모양은 같음)
- 인기 메뉴는 shared/praise.py 의 top_praised_menus 와 같은 결과다 (추천 카드 ⓑ·쿠폰 메뉴와 같은 기준)
- 대표 칭찬 한 줄에는 개인정보가 가려지지 않은 글이 나오지 않는다 (저장본이 가림을 안 거쳤어도 한 번 더 가림)
- 보고서를 만드는 동안 분류기·모델(HTTP)을 부르지 않는다
"""
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import classify, report, service
from app.classify import Classifier
from app.topics import TOPICS

KST = timezone(timedelta(hours=9))
MON = datetime(2026, 11, 16, tzinfo=KST)           # 월요일 0시. 합성 리뷰는 10/13~11/8
API = "/api/review-insight"
MENU = ["제육볶음 정식", "된장찌개", "김치찌개", "순두부찌개", "불고기 덮밥", "계란말이"]
SAMPLES = json.loads((Path(__file__).resolve().parents[1] / "data" / "synthetic" / "store_ongi" / "reviews.json").read_text(encoding="utf-8"))


def at(h, m=0, day=0):
    return MON + timedelta(days=day, hours=h, minutes=m)


def iso(t):
    return t.isoformat(timespec="seconds")


@pytest.fixture(autouse=True)
def tmp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(classify, "RUNTIME_CACHE", tmp_path / "runtime.json")
    monkeypatch.setattr(classify, "USAGE_LOG", tmp_path / "logs" / "llm_usage.jsonl")
    for name in ("REVIEW_PEAK_HOURS", "REVIEW_REPLY_SLA_MINUTES", "REVIEW_PASTE_REAL_TIME"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def client(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_classifier", Classifier("mock"))
    return TestClient(main.app)


def timeline(visitor=None):
    return service.Timeline(Classifier("mock"), "store_ongi", visitor)


def add(text, when, rating=5, source="app"):
    return service.add_review(text, rating, store_id="store_ongi", source=source, received_at=when)


def month(tl, m, now=None):
    return report.monthly(tl, 2026, m, now or at(15))["praise"]


def pairs(rows, key):
    return [(r[key], r["count"]) for r in rows]


# ── 숫자: 합성 자료를 직접 세어 대조 ──
def test_monthly_praise_matches_a_hand_count_of_the_synthetic_reviews():
    tl = timeline()
    assert tl.store_id == "store_ongi" and service.store("store_ongi")["menu"] == MENU
    for m, total, high in ((10, 22, 16), (11, 18, 10)):
        rows = [r for r in SAMPLES if r["created_at"].startswith(f"2026-{m:02d}")]
        ids = {r["review_id"] for r in rows}
        classes = [c for c in tl.classes if c.review_id in ids]
        p = month(tl, m)
        assert p["method"] == "code"
        assert p["review_count"] == len(rows) == total
        assert p["high_rating_count"] == sum(1 for r in rows if r["rating"] >= 4) == high            # 별점은 자료 그대로
        assert p["positive_count"] == sum(1 for c in classes if c.sentiment == "positive")
        counts = Counter(t for c in classes for t in {h.topic for h in c.topics if h.polarity == "positive"})
        order = list(TOPICS)
        expected = sorted(counts.items(), key=lambda kv: (-kv[1], order.index(kv[0])))[:5]
        assert pairs(p["top_topics"], "topic") == expected and len(p["top_topics"]) <= 5
        assert all(t["topic_name"] == TOPICS[t["topic"]][0] for t in p["top_topics"])


def test_scenario_numbers_in_rule_mode():
    """규칙 분류(mock)로 본 발표 시나리오 가게의 값. 분류 규칙이나 합성 자료를 바꾸면 여기서 드러난다."""
    tl = timeline()
    nov = month(tl, 11)
    assert (nov["review_count"], nov["high_rating_count"], nov["positive_count"], nov["praise_count"]) == (18, 10, 10, 10)
    assert nov["praise_basis"] == "sentiment"
    assert pairs(nov["top_topics"], "topic_name") == [("맛", 5), ("포장 상태", 2), ("응대", 2), ("메뉴 구성", 1), ("매장 환경", 1)]
    assert pairs(nov["top_menus"], "menu") == [("순두부찌개", 1), ("불고기 덮밥", 1)]          # 같은 수면 메뉴판 순서
    assert nov["quote"] == {"text": "순두부찌개 얼큰하고 맛있어요", "review_id": "rv_ongi_039", "rating": 4}
    oct_ = month(tl, 10)
    assert (oct_["review_count"], oct_["high_rating_count"], oct_["positive_count"]) == (22, 16, 16)
    assert pairs(oct_["top_menus"], "menu") == [("제육볶음 정식", 1), ("된장찌개", 1), ("김치찌개", 1)]     # TOP 3 까지만
    assert oct_["quote"]["review_id"] == "rv_ongi_013" and oct_["quote"]["text"] == "제육볶음이 불맛 나고 정말 맛있어요!"


def test_top_menus_are_the_same_as_shared_praise():
    mod = report._shared_praise()
    if mod is None:
        pytest.skip("저장소 루트(shared/)가 없는 환경")
    add("계란말이 폭신하고 맛있어요", at(10))
    add("계란말이 또 시킬게요 최고예요", at(11))
    tl = timeline()
    classes = {c.review_id: c for c in tl.classes}
    for m in (10, 11):
        rows = [r for r in tl.rows if tl.arrival(r).month == m]
        # 통합 화면(web/sources.py to_review_records)이 만드는 것과 같은 칸: 리뷰 + 분류의 sentiment·negative_topics
        records = [{"review_id": r["review_id"], "text": r["text"], "rating": r["rating"],
                    "sentiment": classes[r["review_id"]].sentiment, "negative_topics": classes[r["review_id"]].negative_topics} for r in rows]
        expected = [{"menu": x["menu"], "count": x["count"]} for x in mod.top_praised_menus(MENU, records, limit=3)]
        p = month(tl, m)
        assert p["top_menus"] == expected
        assert p["praise_count"] == len(mod.praise_reviews(records))
    assert month(tl, 11)["top_menus"][0] == {"menu": "계란말이", "count": 2}


# ── 기간 ──
def test_reviews_outside_the_period_are_not_counted():
    add("계란말이 폭신하고 맛있어요", at(10))                       # 11/16 에 받음
    tl = timeline()
    assert month(tl, 10)["review_count"] == 22                      # 10월 보고서에는 11월 리뷰가 없다
    assert "계란말이" not in [m["menu"] for m in month(tl, 10)["top_menus"]]
    nov = month(tl, 11)
    assert nov["review_count"] == 19 and nov["high_rating_count"] == 11 and nov["positive_count"] == 11
    assert month(tl, 11, now=at(9))["review_count"] == 18           # 아직 받기 전(09시)에는 세지 않는다
    today = report.daily(tl, MON.date(), at(15))["praise"]
    assert (today["review_count"], today["high_rating_count"], today["positive_count"]) == (1, 1, 1)
    assert today["top_menus"] == [{"menu": "계란말이", "count": 1}] and today["quote"]["text"] == "계란말이 폭신하고 맛있어요"
    day = report.daily(tl, date(2026, 11, 8), at(15))["praise"]     # 합성 리뷰 3건이 있는 날
    assert (day["review_count"], day["high_rating_count"], day["positive_count"]) == (3, 2, 2)
    assert day["top_menus"] == [{"menu": "순두부찌개", "count": 1}]


def test_no_praise_keeps_the_same_shape():
    tl = timeline()
    empty = report.daily(tl, MON.date(), at(15))["praise"]           # 리뷰가 없는 날
    only_complaint = report.daily(tl, date(2026, 10, 21), at(15))["praise"]   # 불만 1건(별점 1점)만 있는 날
    assert only_complaint["review_count"] == 1
    for p in (empty, only_complaint):
        assert (p["high_rating_count"], p["positive_count"], p["praise_count"]) == (0, 0, 0)
        assert p["top_topics"] == [] and p["top_menus"] == [] and p["quote"] is None and p["praise_basis"] is None
        assert set(p) == set(month(tl, 11))                           # 칸은 늘 같다
    assert empty["review_count"] == 0


def test_menu_only_in_complaints_is_not_a_popular_menu():
    add("계란말이가 너무 짰어요", at(10), rating=1)                  # 메뉴를 말했지만 불만
    p = report.daily(timeline(), MON.date(), at(15))["praise"]
    assert p["review_count"] == 1 and p["top_menus"] == [] and p["quote"] is None


# ── 대표 칭찬 한 줄: 개인정보 ──
def _store_unmasked(text):
    """가림을 거치지 않은 글이 저장본에 있는 경우 (예전 저장본·다른 길로 들어온 글)."""
    add("자리 잡기용 글", at(10))
    rows = service.pasted_reviews("store_ongi")
    rows[-1].text, rows[-1].pii_masked = text, False
    service._save_pasted("store_ongi", rows)
    return rows[-1].review_id


def test_quote_masks_personal_data_even_when_the_stored_text_was_not_masked():
    rid = _store_unmasked("계란말이 정말 맛있어요. 단체 주문은 010-1234-5678 이나 owner@example.com 으로 연락 주세요")
    tl = timeline()
    assert "010-1234-5678" in next(r["text"] for r in tl.rows if r["review_id"] == rid)      # 저장본은 안 가려져 있다
    quote = report.daily(tl, MON.date(), at(15))["praise"]["quote"]
    assert quote["review_id"] == rid
    for secret in ("010-1234-5678", "1234", "owner@example.com", "example.com"):
        assert secret not in quote["text"]
    assert "[가림]" in quote["text"] and "계란말이" in quote["text"]
    page = report.render_monthly(report.monthly(tl, 2026, 11, at(15)), "온기한식", at(15))
    assert "010-1234-5678" not in page and "owner@example.com" not in page


def test_quote_prefers_a_review_without_masked_parts():
    _store_unmasked("계란말이 최고예요 010-1234-5678 로 또 시킬게요")
    clean = add("계란말이 폭신하고 맛있어요", at(9), rating=4)       # 별점은 낮고 더 일찍 받았지만 가린 자리가 없다
    quote = report.daily(timeline(), MON.date(), at(15))["praise"]["quote"]
    assert quote == {"text": "계란말이 폭신하고 맛있어요", "review_id": clean.review_id, "rating": 4}


def test_quote_order_is_top_menu_then_rating_then_newest():
    add("순두부찌개 얼큰해요", at(9), rating=5)
    add("계란말이 괜찮아요", at(10), rating=4)
    older = add("계란말이 맛있어요", at(11), rating=5)
    newer = add("계란말이 또 시켜요 맛있어요", at(12), rating=5)
    p = report.daily(timeline(), MON.date(), at(15))["praise"]
    assert p["top_menus"][0] == {"menu": "계란말이", "count": 3}
    assert p["quote"]["review_id"] == newer.review_id != older.review_id      # 가장 많이 언급된 메뉴 → 별점 → 최근


def test_long_quote_is_cut_to_the_sentence_about_the_menu():
    long_text = ("오늘 회사 동료들과 점심에 여러 메뉴를 시켜서 나눠 먹었는데 다들 만족했어요. "
                 "특히 계란말이가 폭신하고 따뜻해서 인기가 많았어요! 다음에도 꼭 다시 주문하겠습니다.")
    add(long_text, at(10))
    quote = report.daily(timeline(), MON.date(), at(15))["praise"]["quote"]
    assert quote["text"] == "특히 계란말이가 폭신하고 따뜻해서 인기가 많았어요!"
    add("계란말이 " + "정말 " * 60 + "맛있어요", at(11))             # 문장 하나가 80자를 넘으면 자른다
    quote = report.daily(timeline(), MON.date(), at(15))["praise"]["quote"]
    assert len(quote["text"]) <= report.QUOTE_MAX


# ── 모델 호출 없음 ──
def test_reports_never_call_the_classifier_or_the_model(monkeypatch):
    add("계란말이 폭신하고 맛있어요", at(10))
    tl = timeline()                                                  # 분류는 여기서 끝난다 (Timeline 이 한 번만 읽음)

    def called(*args, **kwargs):
        raise AssertionError("보고서를 만드는 동안 분류기·모델을 불렀음")
    monkeypatch.setattr(Classifier, "classify", called)
    monkeypatch.setattr(Classifier, "_call", called)
    monkeypatch.setattr(httpx.Client, "send", called)                # 가짜 모델: HTTP 가 나가면 실패
    monkeypatch.setattr(httpx.AsyncClient, "send", called)
    m = report.monthly(tl, 2026, 11, at(15))
    d = report.daily(tl, MON.date(), at(15))
    assert m["praise"]["method"] == d["praise"]["method"] == "code" and d["praise"]["quote"]
    assert "손님 칭찬 요약" in report.render_monthly(m, "온기한식", at(15))


def test_live_classifier_is_not_called_again_for_the_report():
    """live 모드 분류기라도 보고서(칭찬 요약)를 만드는 동안에는 모델 주소로 요청이 나가지 않는다."""
    sent = []

    def model(request):
        sent.append(str(request.url))
        return httpx.Response(500)
    tl = service.Timeline(Classifier("live", api_key="test-key", transport=httpx.MockTransport(model)), "store_ongi")
    before = len(sent)
    report.monthly(tl, 2026, 11, at(15))
    report.daily(tl, date(2026, 11, 8), at(15))
    assert len(sent) == before


# ── API·인쇄 페이지 ──
def test_api_returns_praise_in_daily_and_monthly(client):
    add("계란말이 폭신하고 맛있어요", at(10))
    tl = timeline()
    m = client.get(f"{API}/report/monthly", params={"month": "2026-11", "now": iso(at(15))}).json()
    assert m["praise"] == report.monthly(tl, 2026, 11, at(15))["praise"] and m["praise"]["review_count"] == m["review_count"] == 19
    d = client.get(f"{API}/report/daily", params={"date": "2026-11-16", "now": iso(at(15))}).json()
    assert d["praise"] == report.daily(tl, MON.date(), at(15))["praise"] and d["praise"]["review_count"] == d["review_count"] == 1
    assert d["summary_method"] == "template" and "summary" in d       # 예전 칸은 그대로


def test_print_page_shows_praise_and_escapes_review_text(client):
    add("계란말이 <b>최고</b>예요 <script>alert(1)</script>", at(10))
    add("계란말이 맛있어요", at(9), rating=4)
    r = client.get(f"{API}/report/monthly/print", params={"month": "2026-11", "now": iso(at(15))})
    assert r.status_code == 200
    page = r.text
    m = client.get(f"{API}/report/monthly", params={"month": "2026-11", "now": iso(at(15))}).json()
    p = m["praise"]
    assert p["top_menus"][0] == {"menu": "계란말이", "count": 2} and "<b>최고</b>" in p["quote"]["text"]   # JSON 은 글자 그대로
    assert "손님 칭찬 요약" in page and "모델 호출 없음" in page
    assert f"{p['high_rating_count']}건 / {p['positive_count']}건 (리뷰 {p['review_count']}건 중)" in page
    assert "1위 계란말이 2건" in page
    assert "&lt;b&gt;최고&lt;/b&gt;" in page and "<b>최고</b>" not in page and "<script" not in page


def test_print_page_menu_heading_says_top3_only_when_three_menus():
    """11/22 QA R4: 메뉴가 1~2개인데 'TOP 3'이면 빠진 것처럼 보였다. 셋이면 'TOP 3', 1~2개(또는 없음)는 '인기 메뉴'."""
    tl = timeline()
    nov, oct_ = report.monthly(tl, 2026, 11, at(15)), report.monthly(tl, 2026, 10, at(15))
    assert len(nov["praise"]["top_menus"]) == 2 and len(oct_["praise"]["top_menus"]) == 3
    assert "<th>인기 메뉴</th>" in report.render_monthly(nov, "온기한식", at(15))
    assert "<th>인기 메뉴 TOP 3</th>" in report.render_monthly(oct_, "온기한식", at(15))
    assert [report.menu_heading(x) for x in ([], [{}], [{}, {}, {}], None)] == ["인기 메뉴", "인기 메뉴", "인기 메뉴 TOP 3", "인기 메뉴"]


def test_without_the_shared_module_praise_is_null_and_the_report_still_works(monkeypatch):
    monkeypatch.setattr(report, "_praise_mod", None)                 # 이 서비스 폴더만 있는 환경 (Dockerfile 이미지)
    tl = timeline()
    m = report.monthly(tl, 2026, 11, at(15))
    assert m["praise"] is None and m["review_count"] == 18 and m["suggestions"]
    assert report.daily(tl, date(2026, 11, 8), at(15))["praise"] is None
    page = report.render_monthly(m, "온기한식", at(15))
    assert "손님 칭찬 요약" not in page and "응대 보고서" in page
