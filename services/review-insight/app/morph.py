"""kiwi 형태소 분석 (kiwipiepy 0.24, Apache-2.0). 상권 비서(PR #13)의 app/assistant/morph.py 와 같은 구조입니다.

kiwi가 이미 해 주는 일은 kiwi에 맡깁니다 (kiwipiepy 0.24.1 API로 확인).
- token.lemma: 기본형 ('식' → 식다, '퍽퍽하' → 퍽퍽하다). 직접 '다'를 붙이지 않음
- tokenize(typos=...): 오타 교정 ('맛잇어요' → 맛있다, '양이 저거요' → 적다). REVIEW_MORPH_TYPOS 로 바꿈
- 낱말 위치(start·len)와 연결어미(EC)·문장부호(SF) 태그로 구절 나누기 (clauses)
- W_EMAIL·W_URL·W_SERIAL 태그로 개인정보 찾기 (pii_spans, 정규식과 함께 씀)
- model_type='cong' (0.22부터 기본 모델. knlm·sbg는 기본 파일에서 빠짐)

kiwi가 하는 일은 문장을 낱말로 쪼개고 기본형으로 바꾸는 것까지입니다 ('식었어요' → 식/VV).
그 결과로 "식다가 나오면 음식 온도 불만"처럼 판단하는 단서는 data/lexicon/review_cues.json 에 있습니다
(상권 비서의 intent_keywords.json 과 같은 방식: 코드를 고치지 않고 파일만 고침).

쓰는 곳
1. 모델 참고 자료: live 요청에 리뷰마다 형태소(content_morphemes)와 규칙 분류기 추측을 넣습니다.
2. 규칙 분류기: 모델이 없거나(mock) 실패했을 때 (topics.rule_classify).
3. 비슷한 예문 찾기 (examples.similar).

kiwipiepy가 없거나 REVIEW_MORPH=off 면 get_analyzer()가 None 이고, 규칙은 글자 단서로 돌아갑니다.
"""
from __future__ import annotations

import json
import os
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

LEXICON = Path(__file__).resolve().parents[1] / "data" / "lexicon" / "review_cues.json"
_CONTENT_TAGS = ("NNG", "NNP", "NNB", "NP", "VV", "VA", "XR", "MM", "MAG", "SN")


@dataclass(frozen=True)
class Morpheme:
    form: str
    tag: str
    start: int   # 원문에서의 글자 위치
    length: int


class KiwiAnalyzer:
    name = "kiwi"

    def __init__(self, user_words=()):
        from kiwipiepy import Kiwi   # 선택 설치라서 여기서 불러옴
        import kiwipiepy

        self._kiwi = Kiwi(model_type="cong")
        for word in user_words:
            # 메뉴 이름이 한 낱말로 남게 (예: 치킨무, 순두부찌개, 바닐라라떼)
            self._kiwi.add_user_word(word, "NNG", 0.0)
        self.version = kiwipiepy.__version__
        self.typos = os.getenv("REVIEW_MORPH_TYPOS", "basic_with_continual").strip() or None
        if self.typos in ("off", "none", "0"):
            self.typos = None

    def tokens(self, text: str):
        """kiwi Token 그대로 (lemma·start·len·tag). 리뷰는 오타가 많아 오타 교정을 켬."""
        return self._kiwi.tokenize(unicodedata.normalize("NFC", text or ""), typos=self.typos)

    def analyze(self, text: str) -> list[Morpheme]:
        return [Morpheme(t.form, t.tag, t.start, t.len) for t in self.tokens(text)]


@lru_cache(maxsize=1)
def lexicon() -> dict:
    data = json.loads(LEXICON.read_text(encoding="utf-8"))
    return {"topics": {k: set(v) for k, v in data["topics"].items()}, "time_words": set(data["time_words"]),
            "negative": set(data["negative"]), "positive": set(data["positive"]), "user_words": list(data.get("user_words", []))}


def user_words() -> list[str]:
    """사용자 사전: 단서 파일의 낱말 + 가게 메뉴 이름."""
    words = set(lexicon()["user_words"])
    synthetic = LEXICON.parents[1] / "synthetic"
    for store in synthetic.glob("*/store.json"):
        for menu in json.loads(store.read_text(encoding="utf-8")).get("menu", []):
            words.update(w for w in menu.split() if len(w) >= 2)
    return sorted(w for w in words if all("가" <= ch <= "힣" for ch in w))


def morph_enabled() -> bool:
    return os.getenv("REVIEW_MORPH", "").strip().lower() not in ("off", "0", "false")


def get_analyzer():
    """분석기 하나를 같이 씀. 꺼져 있거나 설치되지 않았으면 None.
    켜기·끄기는 부를 때마다 읽고, 띄운 분석기만 캐시함 (상권 비서와 같은 방식)."""
    if not morph_enabled():
        return None
    return _load_kiwi()


@lru_cache(maxsize=1)
def _load_kiwi():
    try:
        return KiwiAnalyzer(user_words())
    except ImportError:
        return None


def available() -> bool:
    return get_analyzer() is not None


def content_morphemes(text: str) -> list[str]:
    """'공깃밥/NNG 추가/NNG 하/XSV 안/MAG 들/VV …' 모델 참고 자료용. 분석기가 꺼져 있으면 []."""
    analyzer = get_analyzer()
    if analyzer is None:
        return []
    return [f"{t.lemma if t.tag.startswith(('VV', 'VA')) else t.form}/{t.tag}" for t in analyzer.tokens(text)
            if t.tag.startswith(_CONTENT_TAGS)][:30]


# 구절을 나누는 연결어미 (‘맛은 있는데 | 겉이 눅눅해요’). '-고'는 나누지 않음 ('양도 적고 간도 싱거워요'는 한 구절)
_CLAUSE_EC = {"는데", "ᆫ데", "은데", "지만", "더니", "라더니", "으나", "나", "는데요", "다만"}
_PRED = ("VV", "VA", "XR", "MAG", "NNG", "NNP", "NR")


def clauses(text: str) -> list[str]:
    """kiwi 토큰 위치로 나눈 구절들. 각 구절은 원문 그대로의 부분 문자열 (근거 구절로 쓸 수 있음)."""
    analyzer = get_analyzer()
    out, start, prev = [], 0, None
    for t in analyzer.tokens(text):
        tag = t.tag.split("-")[0]
        # kiwi가 '맛있는데'를 '는(ETM) + 데(NNB)'로 읽을 때도 있어서 같은 경계로 봄
        etm_de = tag == "NNB" and t.form == "데" and prev is not None and prev.tag == "ETM"
        prev = t
        if tag == "SF" or (tag == "EC" and t.form in _CLAUSE_EC) or etm_de or t.form == "다만":
            end = t.start + t.len if tag in ("EC", "NNB") else t.start
            piece = text[start:end].strip(" ,.!?~")
            if piece:
                out.append(piece)
            start = t.start + t.len
    tail = text[start:].strip(" ,.!?~")
    if tail:
        out.append(tail)
    return out or [text]


def pii_spans(text: str) -> list[tuple[int, int]]:
    """kiwi가 찾은 이메일·URL·긴 숫자열(전화번호 등) 위치. '2-3인분' 같은 짧은 숫자열은 빼고 9자리 이상만."""
    analyzer = get_analyzer()
    if analyzer is None:
        return []
    spans = []
    for t in analyzer.tokens(text):
        if t.tag in ("W_EMAIL", "W_URL") or (t.tag == "W_SERIAL" and sum(ch.isdigit() for ch in t.form) >= 9):
            spans.append((t.start, t.start + t.len))
    return spans


def lemmas(text: str) -> tuple[list[str], set[str]]:
    """(기본형 낱말 목록, 부정된 기본형 집합). 기본형은 kiwi의 token.lemma."""
    toks = list(get_analyzer().tokens(text))
    out, negated = [], set()
    for i, t in enumerate(toks):
        tag = t.tag.split("-")[0]
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if tag not in _PRED:
            continue
        lemma = t.lemma
        if tag in ("VV", "VA") and lemma.endswith("하다") and len(lemma) > 2:
            out.append(lemma[:-2])           # '퍽퍽하다'처럼 한 낱말로 읽힌 말도 뿌리('퍽퍽')를 남김
        if tag in ("XR", "MAG") and nxt is not None and nxt.form == "하" and nxt.tag.startswith("XSA"):
            out.append(t.form)               # '깨끗 + 하다'는 뿌리('깨끗')와 기본형('깨끗하다')을 둘 다
            lemma = t.form + "하다"
        # '포장해야겠네요'처럼 '포장' 뒤에 '하다'가 붙으면 포장 주문이라는 뜻 → 포장 상태 단서 아님
        if t.form == "포장" and nxt is not None and nxt.tag.startswith("XSV"):
            continue
        # 앞에 '안·못'(MAG) 또는 뒤에 '-지(EC) 않다/못하다(VX)'가 오면 부정
        before = toks[i - 1] if i > 0 else None
        after = [(x.form, x.lemma) for x in toks[i + 1:i + 4]]
        if (before is not None and before.form in ("안", "못") and before.tag == "MAG") or \
                (("지", "지") in after and any(lm in ("않다", "못하다") for _, lm in after)):
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
    lx = lexicon()
    cues = lx["topics"]
    words, negated = lemmas(clause)
    ws = set(words)
    topics = [t for t, c in cues.items() if ws & c]
    # '메뉴 가격', '포장이 깔끔' 처럼 다른 주제를 꾸미기만 하는 말은 그 주제로 세지 않음
    if "price" in topics and "menu" in topics and not (ws & (cues["menu"] - {"메뉴"})):
        topics.remove("menu")
    if "포장상태" in ws and "packaging" not in topics:
        topics.append("packaging")
    if "packaging" in topics and "hygiene" in topics and not (ws & (cues["hygiene"] - {"깔끔하다"})):
        topics.remove("hygiene")
    if ws & lx["time_words"] and not ({"delivery_time", "wait_time"} & set(topics)):
        topics.append("wait_time" if channel == "naver_place" else "delivery_time")
    neg = pos = 0
    for w in ws:
        flip = w in negated
        if w in lx["negative"]:
            pos, neg = (pos + 1, neg) if flip else (pos, neg + 1)
        elif w in lx["positive"]:
            pos, neg = (pos, neg + 1) if flip else (pos + 1, neg)
    return topics, neg, pos
