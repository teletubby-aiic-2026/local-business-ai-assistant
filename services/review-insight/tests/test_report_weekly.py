"""주간 보고서(report.weekly, GET /report/weekly)와 월간 비교 칸(compare=true) 시험 (11/20 종합 리포트 저장).
키·네트워크 없이 돈다 (분류는 규칙 분류). 시각은 모두 고정값으로 넘긴다.

확인하는 것
- 주 경계: 월요일 0시 ~ 일요일 23:59:59 (한국 시간). 아무 날짜를 줘도 그 주로, 오지 않은 주는 거절
- 지난주 비교(리뷰 수·불만 수·불만 비율)와 주제별 건수(이번 주·지난주)가 직접 센 값과 같다
- 리뷰 0건인 주도 오류 없이 같은 모양 (비율 null, 고칠 것은 빈 목록 — 11/22 QA R5, 예전에는 한 줄)
- '이번 주에 고칠 것'의 숫자는 옆 칸 값과 같고, 원인을 단정하지 않는다
- 월간: compare 없이 부르면 예전 응답 그대로 (칸 순서까지), compare=true 는 뒤에 비교 칸만 더함
- 주간과 월간은 같은 계산이다 (같은 날의 점수가 같음)
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import classify, report, service
from app.classify import Classifier

KST = timezone(timedelta(hours=9))
MON = datetime(2026, 11, 16, tzinfo=KST)           # 월요일 0시 (피크 11~14, 17~21). 합성 리뷰는 10/13~11/8
API = "/api/review-insight"
MONTHLY_KEYS = ["store_id", "month", "until", "review_count", "complaint_count", "by_source", "score_start", "score_end",
                "score_change", "score_trend", "changes", "late_count", "repeated_issues", "suggestions", "summary_method", "praise"]
ISSUE_KEYS = ["issue_id", "topic_name", "review_count", "count_this_month", "is_repeated", "replied_count",
              "recurred_after_reply", "state", "main_time_band"]


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


def tl(store="store_ongi", visitor=None):
    return service.Timeline(Classifier("mock"), store, visitor)


def add(text="반찬이 또 빠져 있었어요", when=None, rating=2, source="app", store="store_ongi"):
    return service.add_review(text, rating, store_id=store, source=source, received_at=when)


def check_fix_numbers(w: dict) -> None:
    """고칠 것 문장 속 숫자 = 옆 칸 값. 원인 단정 없음."""
    issues = {i["issue_id"]: i for i in w["repeated_issues"]}
    topics = {(t["topic"], t["polarity"]): t for t in w["topics"]}
    if not w["review_count"]:                    # 리뷰 0건인 주는 고칠 것을 고르지 않는다 (11/22 QA R5)
        assert w["suggestions"] == []
        return
    assert 1 <= len(w["suggestions"]) <= 3
    for s in w["suggestions"]:
        assert set(s) >= {"kind", "title", "evidence", "text"}
        assert "때문" not in s["title"] + s["evidence"] + s["text"]
        if s["kind"] in ("recurred", "no_reply"):
            i = issues[s["issue_id"]]
            assert f"이번 주 {i['count_this_week']}건" in s["evidence"]
            if s["kind"] == "recurred":
                assert f"답글 뒤 재발 {i['recurred_after_reply']}건" in s["evidence"] and i["state"] == "recurred_after_reply"
            else:
                assert f"{i['review_count']}건에" in s["title"] and f"전체 {i['review_count']}건" in s["evidence"]
        elif s["kind"] == "rising":
            t = topics[(s["topic"], "negative")]
            assert s["evidence"] == f"이번 주 {t['count']}건 · 지난주 {t['previous']}건" and t["count"] > t["previous"]
        elif s["kind"] == "late":
            assert f"{w['late_count']}건" in s["title"] and f"기한 넘김 {w['late_count']}건" in s["evidence"]
        elif s["kind"] == "praise_menu":
            m = w["praise"]["top_menus"][0]
            assert m["menu"] in s["title"] and s["evidence"] == f"칭찬 리뷰 {w['praise']['praise_count']}건 중 {m['count']}건"
        else:
            assert s["kind"] == "none", s
            assert s["evidence"] == f"리뷰 {w['review_count']}건 · 불만 {w['complaint_count']}건 · 기한 넘김 0건"


# ── 주 경계 ──
def test_week_is_monday_to_sunday_and_any_day_picks_its_week(client):
    add(when=at(23, 59, day=-1))                     # 지난주 일요일 23:59 → 지난주
    add(when=at(0, 0))                               # 이번 주 월요일 0시 → 이번 주
    add("배달이 너무 늦게 왔어요", when=at(23, 59, day=6), rating=1)    # 일요일 23:59 → 이번 주
    now = at(12, day=7)                              # 다음 주 월요일 낮
    w = report.weekly(tl(), date(2026, 11, 19), now)  # 목요일을 줘도 그 주
    assert (w["week"], w["week_start"], w["week_end"]) == ("2026-11-16", "2026-11-16", "2026-11-22")
    assert w["until"] == "2026-11-22T23:59:59+09:00" and len(w["score_trend"]) == 7
    assert w["review_count"] == 2 and w["by_source"] == {"app": 2}
    assert w["previous"]["week"] == "2026-11-09" and w["previous"]["review_count"] == 1
    assert all("count_this_week" in i and "count_this_month" not in i for i in w["repeated_issues"])
    check_fix_numbers(w)
    body = client.get(f"{API}/report/weekly", params={"week": "2026-11-22", "now": iso(now)}).json()
    assert body == w


def test_in_progress_week_counts_until_now_and_future_week_is_refused(client):
    add(when=at(10))
    add(when=at(15, day=2))                          # 수요일 오후 → now(수요일 12시) 뒤라 아직 없음
    w = report.weekly(tl(), MON.date(), at(12, day=2))
    assert w["until"] == "2026-11-18T12:00:00+09:00" and len(w["score_trend"]) == 3 and w["review_count"] == 1
    with pytest.raises(ValueError, match="아직 오지 않은 주"):
        report.weekly(tl(), date(2026, 11, 23), at(12, day=2))
    assert client.get(f"{API}/report/weekly", params={"week": "2026-11-23", "now": iso(at(12, day=2))}).status_code == 400
    assert client.get(f"{API}/report/weekly", params={"week": "11월 3주"}).status_code == 400
    assert report.parse_week(None, at(12, day=2)) == date(2026, 11, 16)
    assert client.get(f"{API}/report/weekly", params={"now": iso(at(12, day=2))}).json()["week"] == "2026-11-16"


def test_previous_week_and_topic_counts_match_a_hand_count():
    t = tl()
    w = report.weekly(t, date(2026, 11, 3), at(12))          # 합성 리뷰가 든 주 (11/2~11/8), 지난주 10/26~11/1
    def rows(first, last):
        s, e = datetime(first.year, first.month, first.day, tzinfo=KST), datetime(last.year, last.month, last.day, 23, 59, 59, tzinfo=KST)
        return [r for r in t.rows if s <= t.arrival(r) <= e]
    now_rows, prev_rows = rows(date(2026, 11, 2), date(2026, 11, 8)), rows(date(2026, 10, 26), date(2026, 11, 1))
    neg = lambda rs: sum(1 for r in rs if t.negative.get(r["review_id"]))
    assert (w["review_count"], w["complaint_count"]) == (len(now_rows), neg(now_rows)) and w["review_count"] > 0
    assert w["complaint_rate"] == report.complaint_rate(neg(now_rows), len(now_rows))
    assert w["previous"] == {"week": "2026-10-26", "review_count": len(prev_rows), "complaint_count": neg(prev_rows),
                             "complaint_rate": report.complaint_rate(neg(prev_rows), len(prev_rows))}
    classes = {c.review_id: c for c in t.classes}
    for topic in w["topics"]:
        count = lambda rs: sum(1 for r in rs if topic["topic"] in {h.topic for h in classes[r["review_id"]].topics
                                                                    if h.polarity == topic["polarity"]})
        assert (topic["count"], topic["previous"]) == (count(now_rows), count(prev_rows)), topic
    negatives = [x for x in w["topics"] if x["polarity"] == "negative"]
    assert w["topics"][:len(negatives)] == negatives                     # 불만 먼저
    assert [x["count"] for x in negatives] == sorted((x["count"] for x in negatives), reverse=True)
    check_fix_numbers(w)


def test_complaint_rate_rounds_half_up_and_is_none_without_reviews():
    assert report.complaint_rate(1, 8) == 13 and report.complaint_rate(1, 3) == 33 and report.complaint_rate(2, 3) == 67
    assert report.complaint_rate(0, 5) == 0 and report.complaint_rate(0, 0) is None


def test_a_week_without_reviews_is_an_empty_report_not_an_error(client):
    w = client.get(f"{API}/report/weekly", params={"store_id": "store_mongle", "week": "2026-11-16", "now": iso(at(9, day=1))}).json()
    assert w["review_count"] == 0 and w["complaint_count"] == 0 and w["complaint_rate"] is None and w["by_source"] == {}
    assert w["topics"] == [] and w["previous"]["review_count"] == 0 and len(w["score_trend"]) == 2
    assert w["praise"] is None or (w["praise"]["review_count"] == 0 and w["praise"]["quote"] is None)
    check_fix_numbers(w)


def test_no_fixes_when_the_period_has_no_reviews_but_kept_when_it_has_some():
    """11/22 QA R5: 리뷰 0건인 주·달에 기간 밖 반복 불만('포장 누락' 3건, 10~11월 합성 리뷰)이 '고칠 것'으로 나와
    '주제별 흐름: 아직 리뷰가 없어요'와 어긋났다. 0건이면 빈 목록, 리뷰가 있으면 기간 밖 반복 불만도 예전처럼 알린다."""
    t = tl()
    w = report.weekly(t, MON.date(), at(15, day=6))                   # 11/16~11/22, 합성 리뷰는 11/8 까지
    assert w["review_count"] == 0 and w["suggestions"] == []
    assert any(i["is_repeated"] and i["count_this_week"] == 0 for i in w["repeated_issues"])   # 표에는 그대로 남는다
    sept = report.monthly(t, 2026, 9, at(15, day=6))                   # 합성 리뷰보다 앞선 달
    assert sept["review_count"] == 0 and sept["suggestions"] == []
    page = report.render_monthly(sept, "온기한식", at(15, day=6))
    assert "이 달에는 리뷰가 없어 고칠 것을 고르지 않았어요." in page and '<ol class="todo">' not in page
    nov = report.monthly(t, 2026, 11, at(15, day=6))
    assert nov["review_count"] > 0 and nov["suggestions"]             # 리뷰가 있는 달은 그대로
    assert '<ol class="todo"><li>' in report.render_monthly(nov, "온기한식", at(15, day=6))

    add("맛있게 잘 먹었어요", when=at(12, day=1), rating=5)            # 이번 주에 리뷰 한 건 (불만 아님)
    w = report.weekly(tl(), MON.date(), at(15, day=6))
    assert w["review_count"] == 1
    assert [s["kind"] for s in w["suggestions"]][:1] == ["no_reply"]   # 기간 밖 반복 불만은 리뷰가 있는 주에 계속 알린다
    check_fix_numbers(w)


def test_print_page_says_no_change_instead_of_a_bare_zero():
    """11/22 QA R3: 점수 변화가 0이면 '(0)' 대신 '변화 없음'. 0이 아니면 '+3'·'-2' 그대로."""
    sept = report.monthly(tl(), 2026, 9, at(15))
    assert sept["score_change"] == 0
    page = report.render_monthly(sept, "온기한식", at(15))
    assert f"{sept['score_start']} → {sept['score_end']} (변화 없음)" in page and "(0)" not in page
    page = report.render_monthly({**sept, "score_end": sept["score_start"] - 2, "score_change": -2}, "온기한식", at(15))
    assert "(-2)" in page


def test_fixes_follow_the_records_rising_late_and_recurred():
    first = add(when=at(15))
    service.set_status("store_ongi", None, first.review_id, "replied", reply_text="다음엔 꼭 챙길게요", at=at(15, 10))
    add("반찬이 또 빠졌네요", when=at(15, day=2))                     # 답글 뒤 재발
    late = add("배달이 너무 늦게 왔어요", when=at(15, day=3), rating=1)
    service.set_status("store_ongi", None, late.review_id, "replied", reply_text="죄송합니다", at=at(16, 30, day=3))   # 기한 넘김
    w = report.weekly(tl(), MON.date(), at(20, day=4))
    kinds = [s["kind"] for s in w["suggestions"]]
    assert kinds[0] == "recurred" and "다시 들어왔어요" in w["suggestions"][0]["title"]
    assert w["late_count"] >= 1 and "late" in kinds
    check_fix_numbers(w)


# ── 월간: 무회귀 + 비교 칸 ──
def test_monthly_without_compare_is_unchanged_and_compare_only_adds_fields(client):
    first = add(when=at(15))
    service.set_status("store_ongi", None, first.review_id, "replied", reply_text="다음엔 꼭 챙길게요", at=at(15, 10))
    add("반찬이 또 빠졌네요", when=at(15, day=2))
    params = {"month": "2026-11", "now": iso(at(20, day=2))}
    plain = client.get(f"{API}/report/monthly", params=params).json()
    assert list(plain) == MONTHLY_KEYS
    assert all(list(i) == ISSUE_KEYS for i in plain["repeated_issues"]) and plain["repeated_issues"]
    assert all(set(s) <= {"issue_id", "text"} for s in plain["suggestions"])
    assert client.get(f"{API}/report/monthly", params={**params, "compare": "false"}).json() == plain
    extra = client.get(f"{API}/report/monthly", params={**params, "compare": "true"}).json()
    assert list(extra)[:len(MONTHLY_KEYS)] == MONTHLY_KEYS and {k: extra[k] for k in MONTHLY_KEYS} == plain
    assert list(extra)[len(MONTHLY_KEYS):] == ["complaint_rate", "previous", "topics"]
    assert extra["complaint_rate"] == report.complaint_rate(plain["complaint_count"], plain["review_count"])
    assert extra["previous"]["month"] == "2026-10" and extra["previous"]["review_count"] > 0     # 10월 합성 리뷰


def test_weekly_and_monthly_share_the_same_daily_scores():
    first = add(when=at(15))
    add("반찬이 또 빠졌네요", when=at(15, day=2))
    t, now = tl(), at(12, day=7)
    w = report.weekly(t, MON.date(), now)
    m = report.monthly(t, 2026, 11, now)
    by_day = {x["date"]: x["score"] for x in m["score_trend"]}
    assert all(by_day[x["date"]] == x["score"] for x in w["score_trend"])
    assert w["score_end"] == by_day["2026-11-22"]
    assert first.review_id
