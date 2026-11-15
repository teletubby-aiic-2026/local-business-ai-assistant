"""가게 이야기 글 — 사장님이 직접 쓴 답(계기·꼭 지키는 것)만으로 소개글을 만든다. AI 호출 없음
(사장님 문장을 고정 틀에 그대로 엮기만 한다 — 새 사실을 더하지 않으니 지어낼 수가 없다).

check_no_invented_facts(text, source) 는 글에 source(사장님 원문)에 없는 연도·위험 단어가
있으면 False — 생성 방식이 안전해도(틀만 쓰므로) 점검 함수 자체가 맞게 동작하는지 테스트로 따로
확인한다.

build_story_plan(raw, today=None) -> marketing_survey.execute.build_plan() 과 같은 모양
({title, total_minutes, steps, drafts, measure}). drafts 에 네이버 플레이스·인스타 두 버전이 담긴다.
"""
from __future__ import annotations

import re
from datetime import date

from marketing_survey.playbooks import PlaybookStep, _channel_where, _date_label

RISK_WORDS = ["수상", "원산지", "최초", "우승", "인증", "전통 있는", "년부터", "년대"]
_YEAR_RE = re.compile(r"(19|20)\d{2}")


def check_no_invented_facts(text: str, source: str) -> bool:
    """text 가 source 에 없는 연도 숫자나 위험 단어(수상·원산지 등)를 담고 있으면 False."""
    for m in _YEAR_RE.finditer(text):
        if m.group() not in source:
            return False
    for word in RISK_WORDS:
        if word in text and word not in source:
            return False
    return True


def build_story_drafts(reason: str, keep: str) -> dict[str, str]:
    """사장님 답(reason·keep) 을 고정 틀에 넣어 네이버 플레이스·인스타 두 버전을 만든다."""
    reason = reason.strip()
    keep = keep.strip()

    naver_place = (
        f"{reason}로 가게를 시작했습니다. "
        f"{keep}을 꼭 지키며 음식을 만듭니다. "
        "앞으로도 같은 마음으로 손님을 맞이하겠습니다."
    )
    instagram = f"{reason} 🍚 {keep}, 그 마음으로 만듭니다."

    return {"naver_place": naver_place, "instagram": instagram}


def build_story_plan(raw: dict, today: date | None = None) -> dict:
    today = today or date.today()
    reason = (raw.get("story_reason") or "").strip()
    keep = (raw.get("story_keep") or "").strip()

    drafts = build_story_drafts(reason, keep)
    source = f"{reason} {keep}"
    for text in drafts.values():
        if not check_no_invented_facts(text, source):
            raise ValueError("가게 이야기 글에 사장님 답에 없는 사실이 들어갔어요.")

    step = PlaybookStep(
        "story_post", _date_label(today, 0), "가게 이야기 글 올리기",
        _channel_where("naver_place") + " / 인스타그램", 5,
        tip="사장님이 답한 내용만 들어갔는지 확인해요", cost_krw=0,
    )
    return {
        "title": "가게 이야기 글",
        "total_minutes": step.minutes,
        "steps": [step.to_dict()],
        "drafts": {"naver_place_intro": drafts["naver_place"], "instagram_intro": drafts["instagram"]},
        "measure": "측정: 게시물 반응(조회·문의)",
        "total_cost_krw": 0,
    }
