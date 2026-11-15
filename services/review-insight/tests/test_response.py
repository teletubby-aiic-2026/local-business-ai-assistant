"""2~4단계 시험: 입력 방식(source)·새 리뷰 조회, 상태·답글 기록, 응대 기한·점수, 일일·월간 보고서.
키·네트워크 없이 돈다 (분류는 규칙 분류). 시각은 모두 고정값으로 넘긴다."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import classify, report, response, service
from app.classify import Classifier

KST = timezone(timedelta(hours=9))
MON = datetime(2026, 11, 16, tzinfo=KST)           # 월요일 0시 (피크 11~14, 17~21)
API = "/api/review-insight"


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


def add(text="반찬이 또 빠져 있었어요", when=None, source="app", rating=2, visitor=None):
    return service.add_review(text, rating, store_id="store_ongi", visitor_id=visitor, source=source, received_at=when)


def state(now, visitor=None):
    return service.Timeline(Classifier("mock"), "store_ongi", visitor).at(now)


def reason(s, kind):
    return [x for x in s["reasons"] if x["kind"] == kind]


# ── 2단계: 입력 방식과 새 리뷰 조회 ──
def test_add_pasted_still_works_and_records_received_time():
    r = service.add_pasted("치킨무가 빠졌어요", 1, store_id="store_basak")
    assert r.review_id == "rv_basak_paste_001" and r.input_method == "paste"
    row = next(x for x in service.decorated_reviews("store_basak") if x["review_id"] == r.review_id)
    assert row["source"] == "paste" and row["received_at"] and row["reply"] is None
    assert row["created_at"] != row["received_at"]           # 작성 시각은 시나리오 시각 그대로


def test_post_reviews_keeps_contract_input_method_and_adds_source(client):
    for body in ({"text": "배달앱에서 쓴 리뷰예요", "source": "app"}, {"text": "매장에서 들은 불만", "input_method": "memo"}):
        res = client.post(f"{API}/reviews", json=body)
        assert res.status_code == 201
        review = res.json()["review"]
        assert review["input_method"] == "paste" and review["source"] in ("app", "memo") and review["channel"] is None
        assert review["data_origin"] == "synthetic" and review["received_at"]
    bad = client.post(f"{API}/reviews", json={"text": "글", "source": "kakao"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "VALIDATION_ERROR"


def test_since_returns_only_reviews_received_after(client):
    add("첫 리뷰", when=at(15))
    add("둘째 리뷰", when=at(15, 5))
    res = client.get(f"{API}/reviews", params={"since": iso(at(15, 1))}).json()
    assert [r["text"] for r in res["items"]] == ["둘째 리뷰"] and res["count"] == 1 and res["server_time"]
    assert client.get(f"{API}/reviews", params={"since": iso(at(14))}).json()["count"] == 2     # 합성 샘플은 받은 시각이 없어 빠짐
    assert client.get(f"{API}/reviews", params={"source": "app"}).json()["count"] == 2
    assert client.get(f"{API}/reviews", params={"source": "sample"}).json()["count"] == 40
    assert client.get(f"{API}/reviews", params={"since": "어제"}).status_code == 400
    assert set(client.get(f"{API}/reviews").json()) == {"items", "count"}        # since 가 없으면 규격 모양 그대로


def test_decorated_reviews_still_fit_the_team_contract():
    root = Path(__file__).resolve().parents[3]
    if not (root / "shared" / "contracts.py").exists():
        pytest.skip("저장소 루트(shared/)가 없는 환경")
    sys.path.insert(0, str(root))
    try:
        from shared.contracts import ReviewRecord
    finally:
        sys.path.remove(str(root))
    add(source="capture")
    service.set_status("store_ongi", None, "rv_ongi_001", "replied", reply_text="감사합니다")
    names = ReviewRecord.__dataclass_fields__
    for row in service.decorated_reviews("store_ongi"):
        ReviewRecord.from_dict({k: v for k, v in row.items() if k in names})    # 통합 화면(web/sources.py)과 같은 변환


# ── 3단계: 상태·답글 ──
def test_status_records_reply_and_lookups_return_it(client):
    res = client.post(f"{API}/reviews/rv_ongi_001/status", json={"status": "replied", "reply_text": "다음엔 꼭 챙길게요", "at": iso(at(15))})
    assert res.status_code == 200 and res.json()["review"]["reply"] == {"text": "다음엔 꼭 챙길게요", "replied_at": iso(at(15))}
    row = next(r for r in client.get(f"{API}/reviews").json()["items"] if r["review_id"] == "rv_ongi_001")
    assert row["status"] == "replied" and row["reply"]["text"] == "다음엔 꼭 챙길게요"
    assert client.get(f"{API}/reviews/rv_ongi_001").json()["review"]["status"] == "replied"
    assert client.post(f"{API}/reviews/rv_nope/status", json={"status": "replied"}).status_code == 404
    for body in ({"status": "done"}, {"status": "skipped", "reply_text": "글"}, {"status": "replied", "at": "어제"}):
        bad = client.post(f"{API}/reviews/rv_ongi_001/status", json=body)
        assert bad.status_code == 400 and bad.json()["error"]["code"] == "VALIDATION_ERROR"


def test_status_is_per_visitor_and_reset_with_pasted(client):
    service.set_status("store_ongi", "visitor-a", "rv_ongi_001", "replied", reply_text="네")
    assert next(r for r in service.decorated_reviews("store_ongi") if r["review_id"] == "rv_ongi_001")["reply"] is None
    client.delete(f"{API}/reviews/pasted", params={"visitor_id": "visitor-a"})
    assert next(r for r in service.decorated_reviews("store_ongi", "visitor-a") if r["review_id"] == "rv_ongi_001")["reply"] is None


# ── 3단계: 기한 ──
@pytest.mark.parametrize("arrival,due", [
    (at(15), at(15, 30)),          # 피크 아님
    (at(12, 10), at(14, 30)),      # 점심 피크 중 → 14시부터 30분
    (at(16, 45), at(21, 15)),      # 15분 세고 17시에 멈춤 → 21시부터 15분
    (at(22), at(22, 30)),
    (at(23, 50), at(0, 20, 1)),    # 자정을 넘김
    (at(10, 50), at(14, 20)),      # 10분 세고 11시에 멈춤 → 14시부터 20분
])
def test_due_at_pauses_in_peak(arrival, due):
    assert response.due_at(arrival, response.Policy()) == due


def test_peak_hours_setting(monkeypatch):
    assert response.parse_peaks("17-21,11-14") == ((11, 14), (17, 21)) and response.parse_peaks("off") == ()
    for bad in ("11~14", "14-11", "25-26", "a-b"):
        with pytest.raises(ValueError):
            response.parse_peaks(bad)
    monkeypatch.setenv("REVIEW_PEAK_HOURS", "off")
    monkeypatch.setenv("REVIEW_REPLY_SLA_MINUTES", "10")
    assert response.due_at(at(12), response.policy()) == at(12, 10)


# ── 3단계: 점수 ──
def test_baseline_samples_are_untimed_and_only_repeat_counts():
    s = state(at(15))
    assert s["untimed_unanswered"] == 12 and s["pending"] == [] and s["score"] == 98
    assert [x["kind"] for x in s["reasons"]] == ["repeat"] and "포장 누락" in s["reasons"][0]["message"]


def test_pending_then_late_then_partial_recovery():
    r = add(when=at(15))
    s = state(at(15, 10))
    assert s["pending"][0]["review_id"] == r.review_id and s["pending"][0]["remaining_seconds"] == 20 * 60
    assert s["score"] == 98 and not s["pending"][0]["overdue"]
    assert state(at(15, 31))["score"] == 98 - 6                       # 기한 넘김 −6
    late = state(at(16, 31))                                          # 61분 넘김 → −6 −2
    assert late["score"] == 98 - 8 and late["pending"][0]["overdue"] and late["pending"][0]["penalty"] == -8
    assert state(at(18, 0))["score"] == 98 - 10                       # 리뷰당 최대 −10
    service.set_status("store_ongi", None, r.review_id, "replied", reply_text="죄송합니다", at=at(16, 31))
    after = state(at(18))
    assert after["score"] == 98 - 8 + 4 and after["pending"] == []    # 깎인 8점의 절반 회복
    assert {x["kind"] for x in after["reasons"]} == {"repeat", "late", "recover"}


def test_on_time_reply_does_not_raise_score():
    r = add(when=at(15))
    service.set_status("store_ongi", None, r.review_id, "replied", reply_text="죄송합니다", at=at(15, 20))
    assert state(at(16))["score"] == 98


def test_skip_before_due_has_no_penalty():
    r = add(when=at(15))
    service.set_status("store_ongi", None, r.review_id, "skipped", at=at(15, 5))
    s = state(at(16))
    assert s["score"] == 98 and s["pending"] == []


def test_same_complaint_after_reply_costs_more_than_speed_gains():
    first = add(when=at(15))
    service.set_status("store_ongi", None, first.review_id, "replied", reply_text="다음엔 꼭 챙길게요", at=at(15, 10))
    again = add("반찬이 또 빠졌네요", when=at(22))
    s = state(at(22, 5))
    assert s["score"] == 98 - 5 and reason(s, "again")[0]["review_id"] == again.review_id


def test_no_recurrence_for_7_days_gives_back_points_up_to_100():
    first = add(when=at(15))
    service.set_status("store_ongi", None, first.review_id, "replied", reply_text="포장 확인 절차를 바꿨어요", at=at(15, 10))
    assert state(at(15, 9, day=7))["score"] == 98
    s = state(at(15, 11, day=7))
    assert reason(s, "fixed") and s["score"] == 100 and s["raw_score"] == 101          # 100 넘지 않게


def test_response_api(client):
    add(when=at(15))
    body = client.get(f"{API}/response", params={"now": iso(at(15, 10))}).json()
    assert body["store_id"] == "store_ongi" and body["pending_count"] == 1 and body["policy"]["sla_minutes"] == 30
    assert body["policy"]["peak_hours"] == ["11-14", "17-21"]
    assert client.get(f"{API}/response", params={"now": "지금"}).status_code == 400


# ── 4단계: 보고서 ──
def test_daily_report_numbers_and_reasons_add_up(client):
    a = add(when=at(15))
    b = add("배달이 너무 늦게 왔어요", when=at(15, 2), source="memo")
    add("맛있어요 또 시킬게요", when=at(16), rating=5)
    service.set_status("store_ongi", None, a.review_id, "replied", reply_text="죄송합니다", at=at(15, 20))
    service.set_status("store_ongi", None, b.review_id, "replied", reply_text="죄송합니다", at=at(16, 33))
    d = client.get(f"{API}/report/daily", params={"date": "2026-11-16", "now": iso(at(23))}).json()
    assert d["review_count"] == 3 and d["complaint_count"] == 2 and d["by_source"] == {"app": 2, "memo": 1}
    assert d["replied_on_time"] == 1 and d["replied_late"] == 1 and d["replied_count"] == 2
    assert d["score_end"] - d["score_start"] == d["score_change"] == sum(x["delta"] for x in d["changes"])
    assert f"리뷰 {d['review_count']}건" in d["summary"] and f"늦은 답글 {d['replied_late']}건" in d["summary"]
    assert f"{d['score_start']} → {d['score_end']}" in d["summary"] and d["summary_method"] == "template"
    assert d["todo"]["text"]


def test_daily_report_on_a_scenario_day_counts_samples():
    tl = service.Timeline(Classifier("mock"), "store_ongi")
    d = report.daily(tl, datetime(2026, 11, 8).date(), at(12))
    assert d["review_count"] >= 1 and set(d["by_source"]) == {"sample"} and d["todo"]["kind"] == "check_repeated"


def test_todo_points_at_overdue_first():
    r = add(when=at(15))
    d = report.daily(service.Timeline(Classifier("mock"), "store_ongi"), MON.date(), at(16))
    assert d["todo"]["kind"] == "reply_overdue" and d["todo"]["review_id"] == r.review_id


def test_monthly_report(client):
    first = add(when=at(15))
    service.set_status("store_ongi", None, first.review_id, "replied", reply_text="다음엔 꼭 챙길게요", at=at(15, 10))
    add("반찬이 또 빠졌네요", when=at(15, day=2))
    m = client.get(f"{API}/report/monthly", params={"month": "2026-11", "now": iso(at(20, day=2))}).json()
    assert len(m["score_trend"]) == 18 and m["score_trend"][-1]["score"] == m["score_end"]
    missing = next(i for i in m["repeated_issues"] if i["issue_id"] == "iss_missing_item")
    assert missing["is_repeated"] and missing["recurred_after_reply"] == 1 and missing["state"] == "recurred_after_reply"
    assert 1 <= len(m["suggestions"]) <= 3 and "다시 들어왔어요" in m["suggestions"][0]["text"]
    for text in (s["text"] for s in m["suggestions"]):
        assert "때문" not in text                                    # 원인을 단정하지 않음
    assert client.get(f"{API}/report/monthly", params={"month": "2026-13"}).status_code == 400
    assert client.get(f"{API}/report/monthly", params={"month": "2030-01", "now": iso(at(12))}).status_code == 400
    assert client.get(f"{API}/report/daily", params={"date": "11월"}).status_code == 400


def test_monthly_print_is_a4_with_todo_checklist(client):
    first = add(when=at(15))
    service.set_status("store_ongi", None, first.review_id, "replied", reply_text="다음엔 꼭 챙길게요", at=at(15, 10))
    add("반찬이 또 빠졌네요", when=at(15, day=2))
    r = client.get(f"{API}/report/monthly/print", params={"month": "2026-11", "now": iso(at(20, day=2))})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    page = r.text
    m = client.get(f"{API}/report/monthly", params={"month": "2026-11", "now": iso(at(20, day=2))}).json()
    assert "size: A4" in page and "2026년 11월 응대 보고서" in page and 'class="box"' in page
    assert f"{m['score_start']} → {m['score_end']}" in page and f"{m['review_count']}건" in page     # 숫자는 JSON 과 같음
    assert all(s["text"].split("'")[1] in page for s in m["suggestions"] if "'" in s["text"])
    assert "답글 뒤 재발" in page and "<script" not in page
    assert client.get(f"{API}/report/monthly/print", params={"month": "2026-13"}).status_code == 400
