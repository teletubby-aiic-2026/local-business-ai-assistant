"""가게 이야기 글 — 사장님이 직접 쓴 답(계기·대표 메뉴·지키는 것·준비·손님께 할 말)만으로
세 가지 글을 만든다. 키가 있으면 AI 가 합니다체로 다듬고(점검 → 재작성 1번), 키가 없거나 두 번
실패하면 "항목 — 답" 템플릿(사장님 답을 그대로 늘어놓기만 한다 — 새 사실이 없다). 다섯 질문 모두 [건너뛰기] 가능 — 건너뛴 질문의 내용은 어떤 글에도 안 들어간다.

check_no_invented_facts(text, source) 는 글에 source(사장님 원문)에 없는 연도·위험 단어가
있으면 False — 생성 방식이 안전해도(틀만 쓰므로) 점검 함수 자체가 맞게 동작하는지 테스트로 따로
확인한다.

build_story_plan(raw, today=None) -> marketing_survey.execute.build_plan() 과 같은 모양
({title, total_minutes, steps, drafts, measure}). drafts 에 네이버 플레이스·인스타·배민 세 버전이 담긴다.
"""
from __future__ import annotations

import os
import re
from datetime import date

from marketing_survey.playbooks import PlaybookStep, _channel_where, _date_label

RISK_WORDS = ["수상", "원산지", "최초", "우승", "인증", "전통 있는", "년부터", "년대"]
_YEAR_RE = re.compile(r"(19|20)\d{2}")

STORY_FIELDS = ("story_reason", "story_signature", "story_keep", "story_prep", "story_message")

INSTAGRAM_HASHTAGS = "#동네맛집 #오늘의한끼 #단골환영"
BAEMIN_INTRO_LIMIT = 40


def check_no_invented_facts(text: str, source: str) -> bool:
    """text 가 source 에 없는 연도 숫자나 위험 단어(수상·원산지 등)를 담고 있으면 False."""
    for m in _YEAR_RE.finditer(text):
        if m.group() not in source:
            return False
    for word in RISK_WORDS:
        if word in text and word not in source:
            return False
    return True


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_FORMAL_END = re.compile(r"니다[.!?]?\s*$")  # 만듭니다·합니다·씁니다 …
_INFORMAL_END = re.compile(r"요[.!?]?\s*$")  # 해요·먹어요·예요 …
_UNSET = object()
_DEFAULT_STORE = "우리 가게"
_JOSA = "은는이가을를에의도로과와"
_WORD_RE = re.compile(r"[가-힣]{2,}")
_REPEAT_SKIP = {"가게"}


def _clean(text: str) -> str:
    """앞뒤 공백·끝 마침표만 뗀다. 종결어미(~했어요/~합니다)는 문장 틀에 안 넣으므로 그대로 둔다."""
    return (text or "").strip().rstrip(".。").strip()


def _answers_from_raw(raw: dict) -> dict[str, str]:
    return {k: _clean(raw.get(k)) for k in STORY_FIELDS}


def _sentences(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.extend(s.strip() for s in _SENT_SPLIT.split(line) if s.strip())
    return out


def mixed_register(text: str) -> bool:
    """한 글 안에 해요체 문장과 합니다체 문장이 같이 있으면 True."""
    sents = _sentences(text)
    formal = any(_FORMAL_END.search(s) for s in sents)
    informal = any(_INFORMAL_END.search(s) and not _FORMAL_END.search(s) for s in sents)
    return formal and informal


def _stem(token: str) -> str:
    return token[:-1] if len(token) > 2 and token[-1] in _JOSA else token


def repeat_word(text: str) -> bool:
    """같은 낱말(조사 뗀 꼴, '가게' 제외)이 한 문장에 두 번 나오면 True."""
    for sent in _sentences(text):
        seen: set[str] = set()
        for tok in _WORD_RE.findall(sent):
            stem = _stem(tok)
            if stem in _REPEAT_SKIP:
                continue
            if stem in seen:
                return True
            seen.add(stem)
    return False


def _baemin_line(signature: str, store: str) -> str:
    """대표 메뉴 답을 40자 안으로. 넘으면 쉼표·마침표 앞에서, 없으면 띄어쓰기에서 자른다(단어 중간 금지)."""
    fallback = f"{store}의 이야기를 들려드려요"
    if not signature:
        return fallback
    if len(signature) <= BAEMIN_INTRO_LIMIT:
        return signature
    head = signature[: BAEMIN_INTRO_LIMIT + 1]
    cut = max(head.rfind(","), head.rfind("."), head.rfind("，"))
    if cut <= 0:
        cut = head.rfind(" ")
    out = signature[:cut].strip().rstrip(",.，") if cut > 0 else ""
    return out or fallback


def build_story_drafts(answers: dict[str, str], store: str = _DEFAULT_STORE) -> dict[str, str]:
    """키 없을 때 쓰는 템플릿. 답을 "항목 — 답"으로 늘어놓기만 한다(문장 틀에 끼우지 않는다)."""
    reason, signature, keep, prep, message = (answers.get(f, "") for f in STORY_FIELDS)

    rows = [("시작한 이유", reason), ("대표 메뉴", signature), ("꼭 지키는 것", keep),
            ("장사 준비", prep), ("사장님 한마디", message)]
    naver_place = "\n".join([f"{store} 이야기"] + [f"· {label} — {v}" for label, v in rows if v])

    insta_lines = [reason] if reason else []
    if signature:
        if insta_lines:
            insta_lines.append("")
        insta_lines.append(f"대표 메뉴: {signature}")
    if not insta_lines:
        insta_lines = [f"{store} 이야기"]
    instagram = "\n".join(insta_lines) + f"\n\n{INSTAGRAM_HASHTAGS}"

    return {"naver_place": naver_place, "instagram": instagram,
            "baemin_intro": _baemin_line(signature, store)}


_SYSTEM = (
    "당신은 동네 가게 사장님의 이야기를 소개 글로 다듬는 작가입니다.\n"
    "규칙: 합니다체로 통일하세요(해요체 금지). 사장님 답의 뜻만 살려 자연스러운 문장으로 바꿔 쓰세요"
    "(답을 그대로 문장 틀에 끼우지 마세요). 같은 낱말을 한 문장에서 반복하지 마세요. "
    "답에 없는 연도·수상·인증·원산지 같은 사실은 절대 쓰지 마세요. 건너뛴 항목은 쓰지 마세요.\n"
    '반드시 JSON 한 개만 출력: {"naver_place": "네이버 플레이스 소개 5~7문장", '
    f'"instagram": "3문장 이내 + 줄바꿈 + 해시태그 3개", "baemin_intro": "{BAEMIN_INTRO_LIMIT}자 이내 한 줄"}}'
)


def _problems(drafts: dict, source: str) -> list[str]:
    bad: list[str] = []
    for k in ("naver_place", "instagram", "baemin_intro"):
        t = drafts.get(k)
        if not isinstance(t, str) or not t.strip():
            bad.append(f"{k}: 비어 있음")
            continue
        if not check_no_invented_facts(t, source):
            bad.append(f"{k}: 답에 없는 사실")
        if mixed_register(t):
            bad.append(f"{k}: mixed_register(해요체·합니다체 섞임)")
        if repeat_word(t):
            bad.append(f"{k}: repeat_word(한 문장에 같은 낱말 반복)")
    if isinstance(drafts.get("baemin_intro"), str) and len(drafts["baemin_intro"]) > BAEMIN_INTRO_LIMIT:
        bad.append(f"baemin_intro: {BAEMIN_INTRO_LIMIT}자 초과")
    return bad


def write_story_with_ai(answers: dict[str, str], store: str, key: str, source: str,
                        call=None) -> dict[str, str] | None:
    """AI 로 글을 쓰고 점검한다. 걸리면 이유를 알려 한 번 다시 쓰고, 두 번 다 실패하면 None."""
    if call is None:
        import clova
        call, parse = clova.call, clova.parse_json
    else:
        import clova
        parse = clova.parse_json
    labels = dict(zip(STORY_FIELDS, ("시작한 이유", "대표 메뉴", "꼭 지키는 것", "장사 준비", "사장님 한마디")))
    user = f"가게 이름: {store}\n" + "\n".join(f"- {labels[f]}: {v}" for f, v in answers.items() if v)
    messages = [{"role": "user", "content": user}]
    for _ in range(2):
        res = call(key, _SYSTEM, messages)
        content = res.get("content", "") if isinstance(res, dict) else ""
        drafts = parse(content) if content else None
        if not isinstance(drafts, dict):
            problems = ["JSON 형식이 아님"]
        else:
            problems = _problems(drafts, source)
            if not problems:
                return {k: drafts[k].strip() for k in ("naver_place", "instagram", "baemin_intro")}
        messages = [
            {"role": "user", "content": user},
            {"role": "assistant", "content": content or "{}"},
            {"role": "user", "content": "다시 써 주세요. 고칠 점: " + "; ".join(problems)},
        ]
    return None


def build_story_plan(raw: dict, today: date | None = None, key=_UNSET, call=None) -> dict:
    """key 를 안 주면 CLOVA_API_KEY 환경변수. 키가 없거나 AI 글이 두 번 점검에 걸리면 템플릿."""
    today = today or date.today()
    if key is _UNSET:
        key = os.environ.get("CLOVA_API_KEY")
    answers = _answers_from_raw(raw)
    store = _clean(raw.get("store_name")) or _DEFAULT_STORE

    source = " ".join([store] + [v for v in answers.values() if v])
    drafts = write_story_with_ai(answers, store, key, source, call) if key else None
    if drafts is None:
        drafts = build_story_drafts(answers, store)
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
