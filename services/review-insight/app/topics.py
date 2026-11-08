"""주제 사전 · 금지 표현 · 개인정보 가림 · 규칙 분류기.

- 주제 사전: 모델이 고를 수 있는 주제는 여기 있는 것뿐입니다. 모델이 다른 주제를 내면 버립니다.
- 금지 표현: 요약에 원인을 단정하거나 누군가를 탓하는 말, 개인정보 모양이 있으면 요약을 지웁니다.
- 규칙 분류기: APP_MODE=mock 이거나 모델 결과가 검증을 통과하지 못했을 때 씁니다.
  자유롭게 쓴 글은 표현이 다양해서 규칙이 약하므로(특화교육 13-5), 기본은 모델이고 규칙은 대비책입니다.
"""
from __future__ import annotations

import re

from app.models import ReviewClassification, TopicHit

# id: (이름, 설명, 규칙용 단서 단어)
TOPICS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "portion": ("양", "음식 양·구성 대비 양", ("양이", "양도", "양은", "넉넉", "몇 점", "적게 들", "적은 편")),
    "taste": ("맛", "음식 맛·간", ("맛", "음식은 괜찮", "불맛", "얼큰", "달달", "짰", "짜요", "싱거", "집밥 같", "정갈")),
    "price": ("가격", "가격·가성비", ("가격", "가성비", "원인데", "비싸")),
    "delivery_time": ("배달 시간", "주문 후 받기까지 걸린 시간 (배달 주문)", ("배달이", "늦게 와", "오래 걸", "분 만에 왔", "시간이 계속 밀", "걸려서 왔", "분 걸렸", "한 시간 기다", "더 걸린", "넘게 걸", "시간이나 걸", "늦게 왔", "늦게 도착")),
    "texture": ("식감", "바삭함·눅눅함·질김·부드러움·퍽퍽함", ("눅눅", "바삭", "질기", "퍽퍽", "촉촉", "부드러", "겉바속촉", "딱딱")),
    "temperature": ("음식 온도", "식음·미지근·따뜻함", ("식어", "식었", "식은", "미지근", "차갑", "따뜻", "불어서")),
    "packaging": ("포장 상태", "포장 상태·흘림·쏟아짐·찌그러짐", ("포장이", "포장 신경", "포장 상태", "새서", "샜", "넘쳤", "뚜껑", "흥건", "쏟아", "흘렀", "뭉개져")),
    "missing_item": ("포장 누락", "빠진 메뉴·덜 온 개수·잘못 온 메뉴", ("안 왔", "빠져", "누락", "오배송", "잘못 왔", "만 들어 있")),
    "service": ("응대", "직원·사장님 응대, 요청 반영", ("친절", "퉁명", "응대", "불친절", "요청 사항을")),
    "hygiene": ("위생", "청결·이물질", ("머리카락", "위생", "깔끔", "지저분", "이물질", "벌레")),
    "menu": ("메뉴 구성", "메뉴·반찬 구성", ("반찬이", "구성이", "메뉴가")),
    "atmosphere": ("매장 환경", "자리·좌석·공간·인테리어·분위기·소음 (방문)", ("자리가", "좌석", "의자", "인테리어", "분위기", "한적", "시끄", "넓고", "좁")),
    "wait_time": ("매장 대기", "매장에서 기다린 시간 (방문·포장)", ("웨이팅", "늦게 나왔", "빨리 나와", "대기")),
}

TOPIC_IDS = tuple(TOPICS)


def topic_name(topic: str) -> str:
    return TOPICS.get(topic, (topic,))[0]


# 요약(모델이 쓴 한 줄)에 있으면 안 되는 말
BANNED = (
    # 원인을 단정하거나 누군가를 탓함 → 리뷰 글만으로는 원인을 알 수 없음
    "때문", "탓", "잘못했", "책임", "기사님이 늦", "라이더가 늦", "라이더 탓",
    # 손님을 깎아내림
    "진상", "블랙컨슈머", "거짓말", "악성",
)
PII = re.compile(
    r"(01[016789][-\s.]?\d{3,4}[-\s.]?\d{4})"          # 휴대전화
    r"|(0\d{1,2}[-\s.]\d{3,4}[-\s.]\d{4})"             # 일반 전화
    r"|([\w.+-]+@[\w-]+\.[\w.]+)"                       # 이메일
    r"|(https?://\S+|www\.\S+)"                         # 링크
)


def mask_pii(text: str) -> tuple[str, bool]:
    masked = PII.sub("[가림]", text)
    return masked, masked != text


def banned_in(text: str | None) -> list[str]:
    if not text:
        return []
    found = [w for w in BANNED if w in text]
    if PII.search(text):
        found.append("개인정보 모양")
    return found


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


_EDGE = " .,!?\"'“”‘’…·~-"


def locate_evidence(evidence: str, text: str) -> str | None:
    """근거 구절을 리뷰 글에서 찾아, 리뷰 글에 실제로 적힌 그대로의 구절을 돌려줌.
    띄어쓰기·앞뒤 문장부호 차이는 봐줌. 못 찾거나 2글자 미만이면 None (근거로 쓰지 않음)."""
    key = "".join(ch for ch in (evidence or "").strip(_EDGE) if not ch.isspace())
    if len(key) < 2:
        return None
    pos = [i for i, ch in enumerate(text) if not ch.isspace()]      # 공백 아닌 글자의 원래 위치
    flat = "".join(text[i] for i in pos)
    k = flat.find(key)
    if k < 0:
        return None
    return text[pos[k]:pos[k + len(key) - 1] + 1]


def evidence_ok(evidence: str, text: str) -> bool:
    return locate_evidence(evidence, text) is not None


# ── 규칙 분류기 ──
NEG = ("늦", "넘게 걸", "식어", "식었", "식은", "불어서", "미지근", "차갑", "적어", "적게", "적은", "없네", "안 왔", "빠져", "퉁명", "머리카락", "샜", "새서",
       "넘쳤", "흥건", "허술", "아쉬", "짰", "오래", "밀리", "웨이팅", "비싸", "불친절", "지저분", "혼났", "딱딱", "신경 써")
POS = ("맛있", "괜찮", "좋", "친절하", "빠르", "빨리", "넉넉", "꼼꼼", "깔끔", "알차", "정갈", "인정", "감사", "따뜻", "가성비", "얼큰", "달달", "집밥")
# '안 샜어요'처럼 부정어가 붙어 칭찬이 되는 경우
NEG_FLIP = re.compile(r"(하나\s*)?안\s*(샜|새|넘쳤)")
CLAUSE = re.compile(r"[.!?\n]|,|[는은]데|지만|다만|더니|고\s")
# kiwi는 '-고'에서 끊으면 낱말을 잘못 읽어서('질기고' → '질기'), '-고'는 끊지 않음. '그대로인데'의 '인데'도 끊음
CLAUSE_KIWI = re.compile(r"[.!?\n]|,|[는은인]데|지만|다만|더니")


def _clauses(text: str, pattern=CLAUSE) -> list[str]:
    return [c.strip() for c in pattern.split(text) if c and c.strip()]


def rule_classify(review_id: str, text: str, rating: int | None = None, channel: str | None = None,
                  *, use_kiwi: bool | None = None) -> ReviewClassification:
    """규칙 분류. kiwi가 설치되어 있으면 형태소 분석(기본형·부정)으로, 없으면 글자 단서로."""
    from app import morph
    if use_kiwi is None:
        use_kiwi = morph.available()
    hits: dict[tuple[str, str], str] = {}
    for clause in _clauses(text, CLAUSE_KIWI if use_kiwi else CLAUSE):
        if use_kiwi:
            topics, n_neg, n_pos = morph.classify_clause(clause, channel)
            if not topics:
                continue
            neg = n_neg > n_pos or (n_neg == n_pos and rating is not None and rating <= 2)
            pol = "negative" if neg else "positive"
            for t in topics:
                hits.setdefault((t, pol), clause)
            continue
        topics = [t for t, (_, _, cues) in TOPICS.items() if any(c in clause for c in cues)]
        if not topics:
            continue
        flipped = bool(NEG_FLIP.search(clause))
        neg = any(w in clause for w in NEG) and not flipped
        pos = any(w in clause for w in POS) or flipped
        if neg == pos:   # 단서가 없거나 둘 다 → 별점으로 판단
            neg = rating is not None and rating <= 2
            pos = not neg
        pol = "negative" if neg else "positive"
        for t in topics:
            hits.setdefault((t, pol), clause)
    topic_hits = [TopicHit(t, p, ev) for (t, p), ev in hits.items()]
    return ReviewClassification(review_id=review_id, sentiment=sentiment_of(topic_hits, rating), topics=topic_hits,
                                method="rule", model="kiwi" if use_kiwi else None)


def sentiment_of(hits: list[TopicHit], rating: int | None) -> str:
    pols = {h.polarity for h in hits}
    if pols == {"positive", "negative"}:
        return "mixed"
    if pols == {"negative"}:
        return "negative"
    if pols == {"positive"}:
        return "positive"
    if rating is not None:
        return "negative" if rating <= 2 else "positive" if rating >= 4 else "neutral"
    return "neutral"
