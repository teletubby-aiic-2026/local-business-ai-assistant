"""가게 이야기 글 — 사장님이 직접 쓴 답(계기·대표 메뉴·지키는 것·준비·손님께 할 말)만으로
세 가지 글을 만든다. AI 호출 없음(사장님 문장을 고정 틀에 그대로 엮기만 한다 — 새 사실을 더하지
않으니 지어낼 수가 없다). 다섯 질문 모두 [건너뛰기] 가능 — 건너뛴 질문의 내용은 어떤 글에도 안 들어간다.

check_no_invented_facts(text, source) 는 글에 source(사장님 원문)에 없는 연도·위험 단어가
있으면 False — 생성 방식이 안전해도(틀만 쓰므로) 점검 함수 자체가 맞게 동작하는지 테스트로 따로
확인한다.

build_story_plan(raw, today=None) -> marketing_survey.execute.build_plan() 과 같은 모양
({title, total_minutes, steps, drafts, measure}). drafts 에 네이버 플레이스·인스타·배민 세 버전이 담긴다.
"""
from __future__ import annotations

import re
from datetime import date

from marketing_survey.playbooks import PlaybookStep, _channel_where, _date_label

RISK_WORDS = ["수상", "원산지", "최초", "우승", "인증", "전통 있는", "년부터", "년대"]
_YEAR_RE = re.compile(r"(19|20)\d{2}")

STORY_FIELDS = ("story_reason", "story_signature", "story_keep", "story_prep", "story_message")

INSTAGRAM_HASHTAGS = "#동네맛집 #오늘의한끼 #단골환영"
BAEMIN_INTRO_LIMIT = 40
_BAEMIN_FALLBACK = "정성껏 만들어 따뜻하게 보내드립니다."


def check_no_invented_facts(text: str, source: str) -> bool:
    """text 가 source 에 없는 연도 숫자나 위험 단어(수상·원산지 등)를 담고 있으면 False."""
    for m in _YEAR_RE.finditer(text):
        if m.group() not in source:
            return False
    for word in RISK_WORDS:
        if word in text and word not in source:
            return False
    return True


def _as_sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    return text if text[-1] in ".!?" else text + "."


def _answers_from_raw(raw: dict) -> dict[str, str]:
    return {k: (raw.get(k) or "").strip() for k in STORY_FIELDS}


def build_story_drafts(answers: dict[str, str]) -> dict[str, str]:
    """answers(건너뛴 질문은 "") 로 네이버 플레이스(5~7문장)·인스타(3문장+해시태그)·배민 첫 줄을 만든다."""
    reason, signature, keep, prep, message = (
        answers.get(f, "") for f in STORY_FIELDS
    )

    naver_sentences: list[str] = []
    if reason:
        naver_sentences.append(_as_sentence(f"{reason}, 그 마음으로 가게를 시작했습니다"))
    if signature:
        naver_sentences.append(_as_sentence(signature))
    if keep:
        naver_sentences.append(_as_sentence(f"{keep}, 이것만은 꼭 지키고 있습니다"))
    if prep:
        naver_sentences.append(_as_sentence(f"장사를 준비할 때는 {prep}"))
    if message:
        naver_sentences.append(_as_sentence(message))
    naver_sentences.append("손님 한 분 한 분께 정성을 다하겠습니다.")
    if len(naver_sentences) < 5:
        naver_sentences.append("오늘도 정성껏 준비했습니다.")
    naver_place = " ".join(naver_sentences)

    insta_bits = [b for b in (reason, signature or keep, message) if b]
    insta_sentences = [_as_sentence(b) for b in insta_bits] or [_as_sentence("정성껏 준비했습니다")]
    instagram = " ".join(insta_sentences[:3]) + f"\n{INSTAGRAM_HASHTAGS}"

    baemin_source = signature or reason or keep
    if baemin_source:
        baemin_line = _as_sentence(baemin_source)
        baemin_intro = baemin_line if len(baemin_line) <= BAEMIN_INTRO_LIMIT else _BAEMIN_FALLBACK
    else:
        baemin_intro = _BAEMIN_FALLBACK

    return {"naver_place": naver_place, "instagram": instagram, "baemin_intro": baemin_intro}


def build_story_plan(raw: dict, today: date | None = None) -> dict:
    today = today or date.today()
    answers = _answers_from_raw(raw)

    drafts = build_story_drafts(answers)
    source = " ".join(v for v in answers.values() if v)
    for text in drafts.values():
        if not check_no_invented_facts(text, source):
            raise ValueError("가게 이야기 글에 사장님 답에 없는 사실이 들어갔어요.")

    steps = [
        PlaybookStep(
            "naver_place_intro", _date_label(today, 0), "네이버 플레이스 소개 글 올리기",
            _channel_where("naver_place"), 5,
            tip="사장님이 답한 내용만 들어갔는지 확인해요", channel="naver_place", cost_krw=0,
        ),
        PlaybookStep(
            "instagram_intro", _date_label(today, 0), "인스타그램에 올리기",
            "인스타그램 앱 > 새 게시물 (앱 화면은 바뀔 수 있어요)", 5,
            tip="사장님이 답한 내용만 들어갔는지 확인해요", cost_krw=0,
        ),
        PlaybookStep(
            "baemin_intro", _date_label(today, 0), "배민 가게 소개 첫 줄 바꾸기",
            _channel_where("baemin"), 3,
            tip="40자 안에 들어오는지 확인해요", channel="baemin", max_chars=BAEMIN_INTRO_LIMIT, cost_krw=0,
        ),
    ]
    return {
        "title": "가게 이야기 글",
        "total_minutes": sum(s.minutes for s in steps),
        "steps": [s.to_dict() for s in steps],
        "drafts": {
            "naver_place_intro": drafts["naver_place"],
            "instagram_intro": drafts["instagram"],
            "baemin_intro": drafts["baemin_intro"],
        },
        "measure": "측정: 게시물 반응(조회·문의)",
        "total_cost_krw": 0,
    }
