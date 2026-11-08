"""kiwi 형태소 분석으로 하는 규칙 분류 (모델이 없거나 실패했을 때의 대비책).

글자 그대로 찾는 규칙은 '식었어요 / 식어서 / 식은'처럼 말끝이 바뀌면 놓칩니다.
kiwi로 낱말을 기본형('식다')으로 바꾼 뒤 단서와 비교하고, '안 바삭해요', '하나도 안 샜어요'처럼
앞뒤에 붙은 부정(안·못·-지 않다)도 읽습니다.

kiwipiepy(Apache-2.0)는 상권 비서(PR #13)와 같은 버전을 씁니다. 설치되어 있지 않으면
topics.rule_classify 가 예전 글자 규칙으로 돌아갑니다.
"""
from __future__ import annotations

import threading

try:
    from kiwipiepy import Kiwi
except ImportError:   # 선택 설치
    Kiwi = None

_kiwi = None
_lock = threading.Lock()

# 주제 단서 (기본형). 특정 가게 메뉴 이름이 아니라 리뷰에 흔히 나오는 말로만 적습니다.
CUES: dict[str, set[str]] = {
    "taste": {"맛", "맛있다", "맛없다", "간", "싱겁다", "짜다", "밍밍", "쩐내", "냄새", "고소하다", "얼큰하다", "담백하다",
              "느끼하다", "비리다", "정갈하다", "진하다", "달달하다", "달다", "불맛", "맛집", "집밥"},
    "portion": {"양", "넉넉하다", "푸짐하다", "푸짐", "든든하다", "사이즈"},
    "price": {"가격", "가성비", "비싸다", "저렴하다", "값"},
    "texture": {"바삭", "눅눅", "질기다", "퍽퍽", "촉촉하다", "부드럽다", "딱딱하다", "쫄깃", "폭신", "질다", "겉바속촉"},
    "temperature": {"식다", "미지근", "차갑다", "따뜻하다", "뜨겁다", "뜨끈", "따끈따끈", "시원하다", "녹다"},
    "packaging": {"새다", "흐르다", "넘치다", "쏟다", "쏟아지다", "뚜껑", "흥건", "뭉개지다", "뭉개다", "젖다", "허술하다"},
    "missing_item": {"누락", "빠지다", "오배송"},
    "service": {"친절", "불친절", "퉁명", "응대", "직원", "사장", "요청", "서비스"},
    "hygiene": {"위생", "청결", "깨끗하다", "깔끔하다", "머리카락", "이물질", "벌레", "지저분하다"},
    "menu": {"메뉴", "구성", "종류", "다양하다", "가짓수"},
    "atmosphere": {"자리", "좌석", "의자", "인테리어", "분위기", "한적하다", "시끄럽다", "넓다", "좁다", "혼밥"},
    "wait_time": {"웨이팅", "대기"},
}
# 시간 관련 말: 배달 리뷰면 delivery_time, 매장 방문(naver_place)이면 wait_time
TIME_WORDS = {"배달", "도착", "늦다", "걸리다", "오래", "빠르다", "빨리", "금방", "기다리다", "한참", "밀리다", "분만에"}

NEG = {"늦다", "식다", "미지근", "적다", "없다", "빠지다", "누락", "퉁명", "불친절", "머리카락", "이물질", "벌레", "새다",
       "흐르다", "넘치다", "쏟다", "쏟아지다", "흥건", "허술하다", "아쉽다", "짜다", "싱겁다", "밍밍", "쩐내", "오래", "밀리다",
       "비싸다", "부담", "지저분하다", "눅눅", "질기다", "퍽퍽", "딱딱하다", "질다", "녹다", "뭉개지다", "젖다", "좁다",
       "불편하다", "시끄럽다", "한참", "줄다", "오르다", "기다리다", "덜", "지나치다", "별로", "실망", "맛없다", "느끼하다", "비리다",
       "높다", "길다", "웨이팅", "대기", "뭉개다"}
POS = {"맛있다", "좋다", "괜찮다", "친절", "빠르다", "빨리", "금방", "넉넉하다", "푸짐하다", "푸짐", "꼼꼼하다", "깔끔하다",
       "알차다", "정갈하다", "감사", "따뜻하다", "뜨끈", "따끈따끈", "시원하다", "가성비", "얼큰하다", "달달하다", "촉촉하다",
       "부드럽다", "바삭", "고소하다", "깨끗하다", "청결", "다양하다", "최고", "인정", "든든하다", "폭신", "편하다", "한적하다",
       "넓다", "예쁘다", "진하다", "맛집", "쫄깃", "저렴하다", "담백하다"}


def available() -> bool:
    return Kiwi is not None


def kiwi():
    global _kiwi
    if _kiwi is None:
        with _lock:
            if _kiwi is None:
                _kiwi = Kiwi()
    return _kiwi


def lemmas(text: str) -> tuple[list[str], set[str]]:
    """(기본형 낱말 목록, 부정된 기본형 집합)"""
    toks = kiwi().tokenize(text)
    out, negated = [], set()
    for i, t in enumerate(toks):
        tag = t.tag.split("-")[0]
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if tag in ("VV", "VA"):
            lemma = t.form + "다"
        elif tag in ("NNG", "NNP", "XR", "MAG", "NR"):
            # '깨끗 + 하다', '한적 + 하다'처럼 뒤에 '하다'가 붙는 말은 '깨끗하다'로 (꾸미는 말 MAG는 그대로)
            lemma = t.form
            if tag != "NNG" and nxt is not None and nxt.form == "하" and nxt.tag.startswith("XSA"):
                out.append(t.form)           # 뿌리('바삭')와 기본형('바삭하다')을 둘 다 남김
                lemma = t.form + "하다"
        else:
            continue
        # '포장해야겠네요'처럼 '포장' 뒤에 '하다'가 붙으면 포장 주문이라는 뜻 → 포장 상태 단서 아님
        if t.form == "포장" and i + 1 < len(toks) and toks[i + 1].tag.startswith("XSV"):
            continue
        # 앞에 '안·못' 또는 뒤에 '-지 않다/못하다'가 오면 부정
        before = toks[i - 1].form if i > 0 else ""
        after = [x.form for x in toks[i + 1:i + 4]]
        if before in ("안", "못") or ("지" in after and ("않" in after or "못하" in after)):
            negated.update({lemma, t.form})
        out.append(lemma)
    forms = [x.form for x in toks]
    # 'n개만 들어 있었다' → 개수가 덜 옴, '안 왔어요 / 안 들어 있었어요' → 빠짐
    for i in range(len(toks) - 1):
        if toks[i].form == "개" and toks[i + 1].form == "만":
            out.append("누락")
    if {"오다", "들다"} & negated:
        out.append("누락")
    # 'n분 만에 왔다' → 시간 이야기
    for i in range(len(toks) - 2):
        if toks[i].tag == "SN" and toks[i + 1].form == "분" and toks[i + 2].form == "만":
            out.append("분만에")
    # 반찬은 '바뀐다·다양하다·종류' 같은 말과 같이 나올 때만 메뉴 구성 (반찬 그릇·리필은 아님)
    if "반찬" in forms and {"바뀌", "다양", "종류", "가짓수", "구성"} & set(forms):
        out.append("구성")
    # '대기가 있었다 / 웨이팅이 있었다' → 기다림이 있었다는 불만
    if {"대기", "웨이팅"} & set(forms) and "있" in forms:
        out.append("기다리다")
    # '포장이·포장도·포장은' → 포장 상태
    for i in range(len(toks) - 1):
        if toks[i].form == "포장" and toks[i + 1].tag in ("JKS", "JX", "JKO"):
            out.append("포장상태")
    return out, negated


def classify_clause(clause: str, channel: str | None) -> tuple[list[str], int, int]:
    """한 구절의 (주제 목록, 불만 점수, 칭찬 점수)."""
    words, negated = lemmas(clause)
    ws = set(words)
    topics = [t for t, cues in CUES.items() if ws & cues]
    # '메뉴 가격', '포장이 깔끔' 처럼 다른 주제를 꾸미기만 하는 말은 그 주제로 세지 않음
    if "price" in topics and "menu" in topics and not (ws & (CUES["menu"] - {"메뉴"})):
        topics.remove("menu")
    if "포장상태" in ws and "packaging" not in topics:
        topics.append("packaging")
    if "packaging" in topics and "hygiene" in topics and not (ws & (CUES["hygiene"] - {"깔끔하다"})):
        topics.remove("hygiene")
    if ws & TIME_WORDS and not ({"delivery_time", "wait_time"} & set(topics)):
        topics.append("wait_time" if channel == "naver_place" else "delivery_time")
    neg = pos = 0
    for w in ws:
        flip = w in negated
        if w in NEG:
            pos, neg = (pos + 1, neg) if flip else (pos, neg + 1)
        elif w in POS:
            pos, neg = (pos, neg + 1) if flip else (pos + 1, neg)
    return topics, neg, pos
