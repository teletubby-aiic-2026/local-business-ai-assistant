"""C6 공통 점검 — 모두 순수 함수, AI 호출 없음."""

import difflib
import re

from c6.measures import MEASURES, MEASURE_KEYWORDS, INVENTED_KW

try:
    from features.tone import FOOD_WORDS
except ImportError:
    FOOD_WORDS = []

_MONEY_KEYWORDS = re.compile(r"환불|쿠폰|무료|서비스|보상|증정|할인")
_PHONE = re.compile(r"01[016789]-?\d{3,4}-?\d{4}")
_ADDR = re.compile(r"[가-힣]+(시|도|구|군|동|로|길)\s*\d")
_NICK = re.compile(r"[가-힣]{2,4}\s*(님|씨)")
_COUPON_WORDS = re.compile(r"할인|쿠폰|코드|반값|%|원")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_ALL_MEASURE_TEXTS = [m["text"] for m in MEASURES]
_OVERPROMISE = re.compile(r"없을\s*거예요|절대|다시는\s*없|완벽|도입했|마련했|이미\s*(도입|마련|적용)")
_APOLOGY = re.compile(r"죄송")
_FEWSHOT_WORDS = ("국물", "넉넉하다", "집밥")

STIFF_WORDS = {
    "기재": "적어", "이러한": "이런", "해당": "그",
    "재발하지 않도록": "다시 없도록", "피드백": "말씀",
    "진심으로 사과드리며": "정말 죄송해요", "최선을 다할 예정": "더 신경 쓸게요",
    "만족을 최우선으로": None, "부응": None, "언제든지 편하게 문의": None,
    "오신 것을 환영합니다": None, "제공하고 있습니다": None, "여러분": None,
    "방문을 기다리겠습니다": None, "즐겨보세요": None, "한끼 식사": None,
    "제공돼요": None,
    "제공하고 있으니": None, "맛보시길 바랍니다": None,
    "합리적인 가격": None, "많은 참여 부탁": None,
}

_MARKDOWN = re.compile(r"\*\*|#|`")


def has_number_not_in(text: str, allowed_numbers: list[int | float]) -> bool:
    found = re.findall(r"\d[\d,]*", text)
    allowed_strs = {str(int(n)) for n in allowed_numbers} | {f"{int(n):,}" for n in allowed_numbers}
    return any(n not in allowed_strs for n in found)


def promises_not_in_policy(text: str, policies: list[dict]) -> bool:
    if not _MONEY_KEYWORDS.search(text):
        return False
    policy_text = " ".join(p["text"] for p in policies)
    if re.search(r"약속하지|금지|불가|안 [됨됩하]", policy_text):
        return True
    for m in _MONEY_KEYWORDS.finditer(text):
        word = m.group()
        if word not in policy_text:
            return True
    return False


def mentions_unknown_menu(text: str, menu_names: list[str]) -> bool:
    all_food = set(FOOD_WORDS) - set(menu_names)
    return any(w in text for w in all_food if len(w) >= 2)


def personal_info(text: str) -> bool:
    if _PHONE.search(text) or _ADDR.search(text):
        return True
    for m in _NICK.finditer(text):
        if m.group().replace(" ", "") != "고객님":
            return True
    return False


def forbidden_phrase(text: str, forbidden: list[str]) -> bool:
    """ToneProfile.forbidden_phrases 중 하나라도 text에 있으면 True."""
    return any(phrase in text for phrase in forbidden if phrase)


def too_similar(a: str, b: str) -> bool:
    return difflib.SequenceMatcher(None, a, b).ratio() > 0.75


def length_ok(text: str, lo: int, hi: int) -> bool:
    n = len(text)
    return lo <= n <= hi


def measure_keywords_included(text: str, measure_id: str) -> bool:
    """조치 키워드 그룹(MEASURE_KEYWORDS)이 글에 다 들어 있으면(그룹마다 하나 이상) True."""
    groups = MEASURE_KEYWORDS.get(measure_id)
    if not groups:
        return False
    return all(any(kw in text for kw in group) for group in groups)


def chosen_measure_included(text: str, chosen_measures: list[dict] | None) -> bool:
    """chosen_measures 중 하나라도 키워드 그룹이 글에 들어 있으면 True. 고른 조치가 없으면 True."""
    if not chosen_measures:
        return True
    return any(measure_keywords_included(text, m["id"]) for m in chosen_measures)


def has_invented_measure(text: str, chosen_measures: list[dict] | None) -> bool:
    """chosen_measures 에 없는 구체적 개선 조치를 글이 지어냈으면 True. reply·notice 공용.

    고른 조치를 설명하는 문장(그 조치의 키워드 그룹이 다 들어있는 문장)은 '절차'·'체크리스트' 같은
    말이 섞여 있어도 지어낸 것으로 보지 않는다.
    """
    chosen_ids = [m["id"] for m in chosen_measures] if chosen_measures else []
    chosen_texts = {m["text"] for m in chosen_measures} if chosen_measures else set()
    sentences = _SENT_SPLIT.split(text) if text else []
    for sent in sentences or [text]:
        if any(measure_keywords_included(sent, mid) for mid in chosen_ids):
            continue
        for kw in INVENTED_KW:
            if kw in sent:
                return True
        for mt in _ALL_MEASURE_TEXTS:
            if mt in sent and mt not in chosen_texts:
                return True
    return False


def has_overpromise(text: str) -> bool:
    """'없을 거예요'·'절대'·'완벽' 같은 장담이나 '도입했으니'처럼 이미 끝난 일처럼 말하면 True.
    reply·notice 공용 — 약속은 전부 "~할게요"처럼 앞으로 할 일로만 써야 한다."""
    return bool(_OVERPROMISE.search(text))


def has_apology(text: str) -> bool:
    """글의 첫 문장에 사과("죄송")가 있으면 True."""
    first = _SENT_SPLIT.split(text.strip())[0] if text and text.strip() else ""
    return bool(_APOLOGY.search(first))


def fewshot_copied(text: str, menu_names: list[str], review_texts: list[str]) -> bool:
    """few-shot 예시의 특징 단어(국물 등)가 실제 메뉴·리뷰에는 없는데 본문에 그대로 나오면 True.
    같은 단어가 가까운 거리에서 반복되면("함께 ... 함께") 도 True."""
    source_text = " ".join(menu_names) + " " + " ".join(review_texts)
    for w in _FEWSHOT_WORDS:
        if w in text and w not in source_text:
            return True
    return _repeated_word_nearby(text)


def _repeated_word_nearby(text: str, max_gap: int = 15) -> bool:
    tokens = re.findall(r"[가-힣]{2,}", text)
    last_seen: dict[str, int] = {}
    pos = 0
    for tok in tokens:
        idx = text.find(tok, pos)
        if tok in last_seen and idx - last_seen[tok] <= max_gap:
            return True
        last_seen[tok] = idx
        pos = idx + len(tok)
    return False


def coupon_invented(text: str) -> bool:
    """홍보글 본문에 할인·쿠폰·코드·반값·%·원 같은 쿠폰 값 표현이 있으면 True. 쿠폰 줄은 코드가 따로 붙인다."""
    return bool(_COUPON_WORDS.search(text))


def has_markdown(text: str) -> bool:
    """**, #, ` 같은 마크다운 기호가 남아 있으면 True."""
    return bool(_MARKDOWN.search(text))


def strip_markdown(text: str) -> str:
    """**, #, ` 마크다운 기호를 지운다 (내용은 그대로, 기호만 제거)."""
    return _MARKDOWN.sub("", text)


def truncate_sentences(text: str, max_sentences: int = 3) -> str:
    """앞에서 max_sentences 문장까지만 남긴다."""
    if not text or not text.strip():
        return text
    sentences = _SENT_SPLIT.split(text.strip())
    return " ".join(sentences[:max_sentences]).strip()


def has_stiff_words(text: str) -> bool:
    return any(w in text for w in STIFF_WORDS)


def fix_stiff_words(text: str) -> str:
    """뜻이 바뀌지 않는 것만 사전대로 바꾼다 (치환 쌍이 있는 것만)."""
    for old, new in STIFF_WORDS.items():
        if new is not None and old in text:
            text = text.replace(old, new)
    return text


def same_first_sentence(texts: list[str]) -> bool:
    """두 개 이상이 첫 문장이 같으면 True."""
    firsts = [_SENT_SPLIT.split(t.strip())[0] if t and t.strip() else "" for t in texts]
    firsts = [f for f in firsts if f]
    return len(firsts) != len(set(firsts))


def quotes_review(text: str, reviews) -> bool:
    """글이 리뷰 원문을 8자 이상 그대로 베꼈으면 True."""
    for rv in reviews:
        body = rv.text
        for i in range(max(len(body) - 8, 0) + 1):
            chunk = body[i:i + 8]
            if len(chunk) == 8 and chunk in text:
                return True
    return False


def fix_hints(failed: list[str]) -> list[str]:
    mapping = {
        "has_number_not_in": "메뉴판에 있는 가격만 써 주세요.",
        "no_bad_number": "메뉴판에 있는 가격만 써 주세요.",
        "promises_not_in_policy": "정책에 없는 보상 약속은 빼 주세요.",
        "no_bad_promise": "정책에 없는 보상 약속은 빼 주세요.",
        "mentions_unknown_menu": "메뉴에 있는 음식 이름만 써 주세요.",
        "personal_info": "고객 개인정보(이름·전화번호·주소)는 빼 주세요.",
        "no_personal_info": "고객 개인정보(이름·전화번호·주소)는 빼 주세요.",
        "too_similar": "이전 답글과 다르게 써 주세요.",
        "not_too_similar": "이전 답글과 다르게 써 주세요.",
        "length_ok": "글 길이를 조절해 주세요.",
        "no_invented_measure": "구체적 개선 조치를 지어내지 말고, 선택된 조치만 쓰거나 일반적 다짐만 써 주세요.",
        "no_forbidden_phrase": "쓰면 안 되는 표현이 포함되어 있어요. 해당 표현을 빼 주세요.",
        "chosen_measure_included": "선택한 조치 문장을 글에 자연스럽게 한 번 포함해 주세요.",
        "uses_opening": "시작 인사를 그대로 넣어 주세요.",
        "uses_closing": "마무리 인사를 그대로 넣어 주세요.",
        "not_quote_review": "리뷰 원문을 그대로 베끼지 말고 새로 써 주세요.",
        "no_coupon_invented": "할인·쿠폰·코드·반값·% 같은 쿠폰 값 표현은 빼 주세요. 쿠폰 값은 코드가 따로 붙여요.",
        "no_stiff_words": "딱딱한 표현 대신 편한 구어체로 바꿔 주세요.",
        "no_overpromise": "'없을 거예요'·'절대'·'완벽' 같은 장담이나 '도입했으니'처럼 이미 끝난 일처럼 쓰지 말고, "
                           "'~할게요'처럼 앞으로 할 일로 다시 써 주세요.",
        "has_apology": "첫 문장에 불편을 드려 죄송하다는 사과를 넣어 주세요.",
        "no_fewshot_copy": "예시 문구의 단어를 그대로 베끼지 말고, 같은 단어를 가까이서 반복하지 말아 주세요.",
        "no_unknown_menu": "메뉴에 있는 음식 이름만 써 주세요.",
        "no_markdown": "마크다운 기호(**, #, ` 등) 없이 일반 문장으로 써 주세요.",
    }
    return [mapping.get(f, f"{f}을(를) 수정해 주세요.") for f in failed]
