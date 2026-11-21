"""고객응대 질문 답하기 (POST /api/review-insight/ask, app/ask.py, 11/21).

예전 통합 서랍은 리뷰 질문 8개에 글자까지 같은 답을 냈다. 여기서는 질문 종류마다 이 가게 리뷰로 센 근거 카드와 다른 답이 나오는지,
숫자가 카드와 맞는지, 모델(HCX) 답이 근거에 없는 숫자를 쓰면 틀 답으로 바뀌는지 본다. 네트워크·키 없음 (가짜 HCX).
실행 (services/review-insight 에서):  env -u APP_MODE python -m pytest -q tests/test_ask.py
"""
import json
import re
from collections import Counter

import httpx
import pytest
from fastapi.testclient import TestClient

from app import ask, classify, service
from app.classify import Classifier
from app.sources import capture
from app.sources.chat import Chat

API = "/api/review-insight"
NOW = service.datetime(2026, 11, 21, 18, 0, tzinfo=service.KST)


@pytest.fixture(autouse=True)
def tmp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(classify, "RUNTIME_CACHE", tmp_path / "runtime.json")
    monkeypatch.setattr(classify, "USAGE_LOG", tmp_path / "logs" / "llm_usage.jsonl")
    monkeypatch.setattr(capture, "USAGE_LOG", tmp_path / "logs" / "llm_usage.jsonl")


@pytest.fixture
def client(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_classifier", Classifier("mock"))
    return TestClient(main.app)


def answer(text, chat=None):
    return ask.answer(Classifier("mock"), "store_ongi", None, text, NOW, chat=chat or Chat("mock"))


def _chat(reply):
    def handle(request):
        return httpx.Response(200, json={"result": {"message": {"content": reply}, "usage": {}}})
    return Chat("live", api_key="k", transport=httpx.MockTransport(handle))


# ① 질문 나누기 ─────────────────────────────────────────────
@pytest.mark.parametrize("text,intent,topic,channels", [
    ("불만 리뷰 제일 많은 게 뭐야?", "complaints", None, []),
    ("이번 주 별점 평균 몇 점이야?", "rating", None, []),
    ("답글 안 단 리뷰 몇 개야?", "unanswered", None, []),
    ("포장 누락 불만 언제 많이 와?", "time", "missing_item", []),
    ("손님들이 맛에 대해 뭐라고 해?", "topic", "taste", []),
    ("칭찬 리뷰 제일 많은 메뉴는?", "praise", None, []),
    ("알레르기 문의 들어온 거 있어?", "inquiry", None, []),
    ("응대 잘 하는 법 알려줘", "howto", None, []),
    ("억울한 별점 답글은 어떻게 달아?", "howto", None, []),
    ("배민 리뷰랑 쿠팡 리뷰 차이 있어?", "channel", None, ["baemin", "coupangeats"]),
    ("지난주보다 불만 늘었어?", "trend", None, []),
    ("배달 늦다는 불만 늘었어?", "trend", "delivery_time", []),
    ("리뷰 캡처는 어떻게 올려?", "capture", None, []),
    ("응대 점수 몇 점이야?", "score", None, []),
    ("최근 리뷰 보여줘", "recent", None, []),
    ("요기요 불만 뭐야?", "complaints", None, ["yogiyo"]),
    ("양 적다는 리뷰 많아?", "topic", "portion", []),
    ("리뷰 어때?", "overview", None, []),
])
def test_parse(text, intent, topic, channels):
    q = ask.parse(text)
    assert (q.intent, q.topic, q.channels) == (intent, topic, channels)


def test_score_is_not_the_service_topic():
    assert ask.parse("응대 점수 몇 점이야?").topic is None          # '응대 점수'는 주제 '응대'(친절)가 아니다
    assert ask.parse("직원 응대 불만 있어?").topic == "service"


# ②③ 근거 카드와 답 ───────────────────────────────────────────
QUESTIONS = ["불만 리뷰 제일 많은 게 뭐야?", "별점 평균 몇 점이야?", "답글 안 단 리뷰 몇 개야?", "포장 누락 불만 언제 많이 와?",
             "손님들이 맛에 대해 뭐라고 해?", "칭찬 리뷰 제일 많은 메뉴는?", "배민 리뷰랑 쿠팡 리뷰 차이 있어?", "지난주보다 불만 늘었어?",
             "응대 점수 몇 점이야?", "최근 리뷰 보여줘", "억울한 별점 답글은 어떻게 달아?", "리뷰 어때?"]


def test_different_questions_get_different_answers_with_cards():
    """예전 서랍: 이 질문들 중 8개가 글자까지 같은 답. 이제 모두 다르고, 답마다 그 답이 인용한 카드가 있다."""
    got = [answer(q) for q in QUESTIONS]
    assert len({g["text"] for g in got}) == len(QUESTIONS)
    for q, g in zip(QUESTIONS, got):
        ids = {c["id"] for c in g["cards"]}
        cited = set(re.findall(r"\[(F\d+)\]", g["text"]))
        assert g["cards"] and cited and cited <= ids, q
        assert g["method"] == "template" and g["demo"], q
        assert g["notes"] == [], q                               # 화면 안내 없음 (합성 여부는 synthetic 칸)
        assert g["synthetic"] is True, q


def test_numbers_are_counted_from_the_reviews():
    tl = service.Timeline(Classifier("mock"), "store_ongi", None)
    rated = [r["rating"] for r in tl.rows if r["rating"]]
    complaints = [c for c in tl.classes if c.negative_topics]
    top, n = Counter(t for c in complaints for t in set(c.negative_topics)).most_common(1)[0]

    g = answer("별점 평균 몇 점이야?")
    assert f"{ask._num(sum(rated) / len(rated))}점" in g["text"]
    g = answer("불만 리뷰 제일 많은 게 뭐야?")
    assert f"리뷰 {len(tl.rows)}건 중 불만은 {len(complaints)}건" in g["text"]
    assert f"'{ask.topic_name(top)}'({n}건)" in g["text"]
    assert g["cards"][0]["values"][0] == {"label": ask.topic_name(top), "value": n, "unit": "건",
                                          "share_percent": ask._pct(n, len(complaints))}


def test_channel_filter_counts_only_that_app():
    tl = service.Timeline(Classifier("mock"), "store_ongi", None)
    n = sum(1 for r in tl.rows if r["channel"] == "yogiyo")
    assert f"요기요 리뷰 {n}건 중" in answer("요기요 불만 뭐야?")["text"]


def test_week_compare_says_its_dates():
    """합성 리뷰는 지난 날짜에 있다. '지난주'는 오늘이 아니라 마지막 리뷰 날짜로 자르고, 그 날짜를 답·카드에 적는다."""
    g = answer("지난주보다 불만 늘었어?")
    assert re.search(r"최근 7일\(\d+/\d+~\d+/\d+\)", g["text"])
    assert "마지막 리뷰" in g["cards"][0]["text"]
    assert g["base_day"] == "2026-11-08"


def test_no_reviews_store_says_so(monkeypatch):
    monkeypatch.setattr(service.Timeline, "__init__", _empty_timeline)
    g = answer("불만 리뷰 제일 많은 게 뭐야?")
    assert "리뷰가 아직 없어요" in g["text"] and g["cards"][0]["values"][0]["value"] == 0


def _empty_timeline(self, classifier, store_id="store_ongi", visitor_id=None):
    from app import response
    self.store_id, self.policy = store_id, response.policy()
    self.reviews, self.rows, self.classes, self.negative = [], [], [], {}


# ④ 모델 답 점검 ───────────────────────────────────────────────
def test_model_answer_is_used_when_it_passes_the_check():
    fixed = answer("불만 리뷰 제일 많은 게 뭐야?")
    first = ask._first_sentence(fixed["text"])               # 틀 답 첫 문장의 숫자는 답에도 있어야 한다 (11/22)
    good = "요즘 보면 " + first + " 그 시간대 포장 확인 순서를 점검해 보세요."
    g = answer("불만 리뷰 제일 많은 게 뭐야?", chat=_chat(good))
    assert (g["method"], g["text"], g["checks"]) == ("hcx", good, [])


@pytest.mark.parametrize("bad,why", [
    ("가장 많은 불만은 포장 누락으로 37건이에요 [F1].", "근거에 없는 숫자 37"),
    ("가장 많은 불만은 포장 누락이에요 [F9].", "없는 근거 F9"),
    ("가장 많은 불만은 포장 누락이에요.", "근거 표시 없음"),
    ("포장 누락은 직원 실수 때문에 생겨요 [F1].", "쓰면 안 되는 말"),
])
def test_model_answer_that_fails_the_check_falls_back(bad, why):
    fixed = answer("불만 리뷰 제일 많은 게 뭐야?")
    g = answer("불만 리뷰 제일 많은 게 뭐야?", chat=_chat(bad))
    assert g["method"] == "template" and g["text"] == fixed["text"]
    assert any(why in p for p in g["checks"]), g["checks"]


def test_model_failure_falls_back():
    def handle(request):
        return httpx.Response(500, json={})
    g = answer("별점 평균 몇 점이야?", chat=Chat("live", api_key="k", transport=httpx.MockTransport(handle)))
    assert g["method"] == "template" and any("모델 호출 실패" in p for p in g["checks"])


def test_number_shapes_match():
    assert ask._numbers("30.0% 3.80점 1,200원 [F1]") == {"30", "3.8", "1200"}       # 근거 번호 F1 은 숫자로 안 셈


# HTTP ──────────────────────────────────────────────────────
def test_endpoint(client):
    res = client.post(f"{API}/ask", json={"text": "불만 리뷰 제일 많은 게 뭐야?", "now": NOW.isoformat()})
    assert res.status_code == 200
    body = res.json()
    assert body["intent"] == "complaints" and body["cards"][0]["id"] == "F1" and "[F1]" in body["text"]
    assert client.post(f"{API}/ask", json={"text": ""}).status_code == 400          # 이 서비스는 입력 오류를 400 VALIDATION_ERROR 로
    assert client.post(f"{API}/ask", json={"text": "리뷰 어때?", "visitor_id": "bad id!"}).status_code == 400


# 11/21: "손님들이 맛에 대해 뭐라고 해?" · 누가 쓴 답인지 ───────────────────────────────
def test_taste_question_quotes_what_customers_wrote():
    g = answer("손님들이 맛에 대해 뭐라고 해?")
    said = next(c for c in g["cards"] if c["topic"] == "손님 말")
    assert {v["group"] for v in said["values"]} == {"불만", "칭찬"}
    assert f"[{said['id']}]" in g["text"] and "같은 말이 있었어요" in g["text"]


def test_model_answer_is_marked_only_in_the_response_fields():
    """누가 쓴 답인지는 화면 안내(notes)에 넣지 않고 method·model 칸으로만 (11/21 사장님 화면에서 뺌)."""
    plain = answer("리뷰 어때?")
    assert (plain["method"], plain["model"]) == ("template", None)
    assert not any("AI" in n or "규칙" in n for n in plain["notes"])
    fixed = answer("손님들이 맛에 대해 뭐라고 해?")
    m = re.search(r"불만 (\d+)건, 칭찬 (\d+)건", fixed["text"])
    good = (f"맛 이야기는 불만 {m.group(1)}건, 칭찬 {m.group(2)}건이라 칭찬이 훨씬 많아요 [F1]. "
            "손님들은 맛있다고 했고, 불만으로는 맛이 예전 같지 않다는 말이 있었어요 [F3].")
    g = answer("손님들이 맛에 대해 뭐라고 해?", chat=_chat(good))
    assert (g["method"], g["model"], g["text"]) == ("hcx", "HCX-005", good)
    assert not any("AI" in n for n in g["notes"])
    bad = answer("손님들이 맛에 대해 뭐라고 해?", chat=_chat("맛 불만이 7건이에요 [F1]."))
    assert bad["method"] == "template" and any("근거에 없는 숫자 7" in p for p in bad["checks"])


# ② AI 플래너 (live, 11/21) ─────────────────────────────────────
def _two_step_chat(plan_reply, write_reply=None):
    """플래너 호출(시스템 글에 '분류기')과 답 쓰기 호출을 나눠 답하는 가짜 HCX. 부른 순서를 calls 에 적는다."""
    calls = []

    def handle(request):
        system = json.loads(request.content)["messages"][0]["content"]
        kind = "plan" if "분류기" in system else "write"
        calls.append(kind)
        reply = plan_reply if kind == "plan" else (write_reply or "")
        return httpx.Response(200, json={"result": {"message": {"content": reply}, "usage": {}}})
    return Chat("live", api_key="k", transport=httpx.MockTransport(handle)), calls


def test_planner_picks_the_question_type_rules_missed():
    """'요새 손님들 반응 어때?' 규칙으로는 전체 요약. 모델이 '칭찬'으로 고르면 그 카드로 답한다."""
    assert ask.parse("요새 손님들 반응 어때?").intent == "overview"
    chat, calls = _two_step_chat('{"intent": "praise", "topic": null, "channels": []}')
    g = answer("요새 손님들 반응 어때?", chat=chat)
    assert (g["intent"], g["classified_by"], g["rule_intent"]) == ("praise", "hcx", "overview")
    assert g["cards"][0]["topic"] == "칭찬 주제" and calls == ["plan", "write"]


@pytest.mark.parametrize("bad,why", [
    ('{"intent": "weather", "topic": null, "channels": []}', "모르는 종류"),
    ('{"intent": "topic", "topic": "parking", "channels": []}', "모르는 주제"),
    ('{"intent": "channel", "topic": null, "channels": ["daangn"]}', "모르는 채널"),
    ("칭찬 리뷰를 보면 돼요", "JSON 이 아님"),
])
def test_planner_answer_that_fails_the_check_keeps_the_rules(bad, why):
    chat, _ = _two_step_chat(bad)
    g = answer("요새 손님들 반응 어때?", chat=chat)
    assert (g["intent"], g["classified_by"]) == ("overview", "rules")
    assert why in g["plan_note"]


def test_planner_topic_and_channel_are_used():
    chat, _ = _two_step_chat('{"intent": "topic", "topic": "taste", "channels": ["baemin"]}')
    g = answer("요새 음식 어떻대?", chat=chat)
    assert (g["intent"], g["topic"], g["channels"]) == ("topic", "taste", ["baemin"])
    assert g["text"].startswith("배민 '맛' 이야기는")


def test_mock_never_calls_the_planner():
    g = answer("요새 손님들 반응 어때?")
    assert (g["classified_by"], g["plan_note"]) == ("rules", None)


def test_this_week_taste_complaints():
    """'이번주 맛에 대한 불만 리뷰는 몇 건이냐?' → 맛 주제의 주간 비교. 맛 불만에 '포장 순서' 조언은 붙이지 않는다."""
    g = answer("이번주 맛에 대한 불만 리뷰는 몇 건이냐?")
    assert (g["intent"], g["topic"]) == ("trend", "taste")
    assert re.match(r"최근 7일\(\d+/\d+~\d+/\d+\) '맛' 불만은 \d+건", g["text"])
    assert "포장" not in answer("저녁에 맛 불만 많아?")["text"]


# 11/22 PR #75 live 확인 반영 ────────────────────────────────────────
def test_planner_never_overrides_what_the_rules_found():
    """규칙이 고른 질문은 플래너가 바꾸지 않는다 (live 에서 trend → recent 같은 나빠진 바꿈 5건)."""
    for q in ("이번주 맛에 대한 불만 리뷰는 몇 건이냐?", "배달 늦다는 리뷰 있어?", "양 적다는 말 있어?", "위생 관련 불만 있어?"):
        chat, calls = _two_step_chat('{"intent": "recent", "topic": null, "channels": []}')
        g = answer(q, chat=chat)
        assert g["classified_by"] == "rules" and g["intent"] != "recent" and calls[0] == "write", q


def test_like_questions_show_both_sides():
    """'손님들이 우리 가게 좋아해?' 칭찬 카드만 보고 '네, 좋아해요' 하던 것 → 불만 비율·별점·칭찬·불만을 같이."""
    for q in ("손님들이 우리 가게 좋아해?", "손님들 만족해?", "우리 가게 평판 어때?"):
        g = answer(q)
        assert g["intent"] == "overview", q
        assert "불만은" in g["text"] and "평균 별점" in g["text"] and "칭찬은" in g["text"], q


@pytest.mark.parametrize("bad,why", [
    ("쿠팡은 8건으로 3건이 적어요 [F1].", "근거에 없는 숫자"),                    # 1·2·3 자동 허용 뺌
    ("포장 누락이 가장 많아요 [F1]. 저녁에 주문이 많아 포장이 미흡했을 가능성이 높아요.", "틀 답 첫 문장의 숫자가 빠짐"),
    ("요즘 보면 {first} 응대를 잘하고 계시니 충분히 좋아질 거예요.", "쓰면 안 되는 말"),
    ("요즘 보면 {first} 포장 확인을 점검해 보시길 권장합니다. 감사합니다.", "해요체가 아님"),
])
def test_stricter_check(bad, why):
    fixed = answer("불만 리뷰 제일 많은 게 뭐야?")
    bad = bad.replace("{first}", ask._first_sentence(fixed["text"]))
    g = answer("불만 리뷰 제일 많은 게 뭐야?", chat=_chat(bad))
    assert g["method"] == "template" and any(why in p for p in g["checks"]), g["checks"]


def test_direction_words_must_match():
    """틀 답이 '같아요'인데 모델이 '늘었어요'라고 하면 숫자가 맞아도 막는다."""
    got = answer("지난주보다 불만 늘었어?")
    fixed = got["text"]
    word = next(w for w, _ in ask._DIRECTION if w in fixed)
    flipped = ask._first_sentence(fixed).replace(word, "줄었" if word == "늘었" else "늘었")
    probs = ask.check_answer(flipped, got["cards"], fixed)
    assert any("다른 뜻" in p for p in probs), probs


def test_howto_never_goes_to_the_model():
    """'억울한 별점 답글은 어떻게 달아?'에 모델이 가게 사실('주문 즉시 조리')을 지어냈다 → 숫자 없는 안내는 틀 문장만."""
    chat, calls = _two_step_chat("{}", "저희 가게 음식은 주문 즉시 조리를 시작해요 [F1].")
    g = answer("억울한 별점 답글은 어떻게 달아?", chat=chat)
    assert g["method"] == "template" and "write" not in calls


def test_bold_marks_are_removed():
    first = ask._first_sentence(answer("불만 리뷰 제일 많은 게 뭐야?")["text"])
    g = answer("불만 리뷰 제일 많은 게 뭐야?", chat=_chat("**요약** " + first))
    assert g["method"] == "hcx" and "**" not in g["text"], g["checks"]


def test_ties_are_named_together():
    """식감 4건·포장 누락 4건처럼 동점이면 둘 다 '가장 많은'으로."""
    tl = service.Timeline(Classifier("mock"), "store_basak", None)
    cnt = Counter(t for c in tl.classes if c.negative_topics for t in set(c.negative_topics))
    top = max(cnt.values())
    g = ask.answer(Classifier("mock"), "store_basak", None, "불만 리뷰 제일 많은 게 뭐야?", NOW, chat=Chat("mock"))
    if sum(1 for v in cnt.values() if v == top) > 1:
        assert f"(각 {top}건)" in g["text"]
