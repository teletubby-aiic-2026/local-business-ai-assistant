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
    """메뉴에 없는 음식(FOOD_WORDS)이 글에 있으면 True.
    글에서 메뉴 이름을 먼저 지운다(긴 것부터). 메뉴 이름을 띄어쓰기로 나눈 2글자 이상 조각도 같이 지운다
    ("불고기 덮밥"을 "불고기"만 써도 메뉴로 본다). 남은 글에서만 일반 음식 낱말을 찾는다."""
    names = {n for name in menu_names for n in (" ".join(name.split()), *name.split()) if len(n) >= 2}
    rest = text
    for name in sorted(names, key=len, reverse=True):
        rest = rest.replace(name, " ")
    return any(w in rest for w in FOOD_WORDS if len(w) >= 2)


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
        # 사과 없이 사실을 설명하는 답글(c6.stance EXPLAIN)의 점검
        "no_compensation_offer": "요청을 들어드리겠다거나 더 챙겨 드리겠다는 약속, 환불·무료·서비스·할인 같은 말은 빼 주세요.",
        "no_fault_admission": "가게 잘못이 아닌 리뷰예요. '죄송'·'사과'·'잘못'·'실수'·'불편을 드려' 같은 말 없이 "
                              "'원하시던 대로 해 드리지 못해 아쉬우셨을 것 같아요'처럼 써 주세요.",
        "no_customer_blame": "손님을 탓하거나 가르치거나 비꼬는 말('~하셔야'·'원래'·'당연히'·'무리한' 등)은 빼고 담담하게 써 주세요.",
        "has_regret": "첫 문장에 '원하시던 대로 해 드리지 못해 아쉬우셨을 것 같아요'처럼 정중하게 유감을 표해 주세요.",
        "explains_principle": "가게가 정한 원칙이나 사실(예: 메뉴판에 있는 구성대로만 준비하고 있어요)을 한 문장으로 설명해 주세요.",
        "request_mentioned": "리뷰에 나온 메뉴 이름을 그대로 넣어, 어떤 요청이었는지 짚어 주세요.",
        "haeyo_only": "'~습니다'·'~니다' 같은 합니다체 대신 '~요'로 끝나는 해요체로만 써 주세요.",
    }
    return [mapping.get(f, f"{f}을(를) 수정해 주세요.") for f in failed]


# ── 사과 없이 사실을 설명하는 답글(c6.stance EXPLAIN) 전용 점검 ─────────────
# 가게 과실이 아닌 리뷰에서 쓴다. 사과 답글의 점검(c6.reply._run_checks)은 그대로이고, 이 점검들은 그 답글에 쓰지 않는다.

_COMPENSATION = re.compile(
    r"환불|쿠폰|무료|공짜|서비스로|보상|증정|할인|적립|덤으로"
    r"|(?:하나\s*더|더|추가로|다시|새로)\s*(?:챙겨|넣어|보내|만들어)\s*드릴|바꿔\s*드릴|변경해\s*드릴"
    r"|(?:그렇게|원하시는\s*대로|요청하신\s*대로|말씀하신\s*대로)\s*해\s*드릴"
)
_FAULT_ADMISSION = re.compile(
    r"죄송|사과(?:드|의|를|합)|잘못|실수|불찰|탓|책임|불편을\s*드|불편하게\s*해\s*드|면목|송구|저희가\s*부족"
)
_CUSTOMER_BLAME = re.compile(
    r"진상|블랙\s*컨슈머|악성|억지|무리한|말도\s*안|거짓|갑질|별점\s*테러|보복|상식|당연히|당연한|원래\s*그렇|원래\s*안"
    r"|명심|알아\s*두|아셔야|하셔야|주셔야|셨어야|했어야|읽어\s*보|확인하고\s*주문|다른\s*(?:가게|곳|집)|굳이|ㅋ|ㅎㅎ|\^\^;|;;"
    r"|규정|위반|정책\s*상|참고\s*(?:하시|부탁|바랍)|양지"
)
_HAEYO_END = re.compile(r"요[.!?~…]*\s*(?::\)|\^\^)?$")
_REGRET = re.compile(r"아쉬|속상|서운|실망|언짢|기대에\s*못\s*미|기대하신\s*만큼|마음이\s*(?:쓰|무거)")
_PRINCIPLE = re.compile(
    r"메뉴판|메뉴\s*구성|구성대로|정해진|원칙|기준|모든\s*(?:손님|분|고객)|똑같이|같은\s*(?:맛|양|구성|기준)|레시피"
    r"|준비하고\s*있|조리하고\s*있|운영하고\s*있|안내해\s*드리고\s*있|고객센터|가능\s*(?:지역|범위|시간)|영업\s*시간"
    r"|들어온\s*(?:주문|메뉴)|주문서대로|조리(?:가|를)?\s*(?:시작|들어가)|이미\s*조리|가격대로|가격\s*차이"
)


def offers_compensation(text: str) -> bool:
    """환불·무료·서비스·할인 같은 보상 낱말이나 '더 챙겨 드릴게요'·'바꿔 드릴게요'처럼 요청을 들어주거나
    덤을 주겠다는 약속이 있으면 True. promises_not_in_policy(정책 기준)와 따로, 정책과 상관없이 막는다."""
    return bool(_COMPENSATION.search(text or ""))


def admits_fault(text: str) -> bool:
    """'죄송'·'사과드려요'·'잘못'·'실수'·'불편을 드려'·'책임' 같은 사과·과실 인정 표현이 있으면 True.
    has_apology(첫 문장 '죄송')와 뜻이 다르다: 글 전체에서 과실을 인정하는 말을 찾는다."""
    return bool(_FAULT_ADMISSION.search(text or ""))


def blames_customer(text: str) -> bool:
    """손님을 탓하거나('무리한'·'억지'·'진상'), 가르치거나('~하셔야'·'당연히'·'원래 그렇'), 비꼬는('다른 가게'·'굳이'·'ㅋ')
    표현이 있으면 True."""
    return bool(_CUSTOMER_BLAME.search(text or ""))


def haeyo_only(text: str) -> bool:
    """문장마다 해요체(~요)로 끝나면 True. 빈 글은 False. (코드가 붙이는 문장이 해요체라 AI 부분도 맞춘다)"""
    sentences = [s.strip() for s in _SENT_SPLIT.split((text or "").strip()) if s.strip()]
    return bool(sentences) and all(_HAEYO_END.search(s) for s in sentences)


def has_regret(text: str) -> bool:
    """'아쉬우셨을'·'속상하셨을'·'기대에 못 미쳐' 같은 정중한 유감 표현이 있으면 True."""
    return bool(_REGRET.search(text or ""))


def explains_principle(text: str) -> bool:
    """가게가 정한 원칙·사실을 설명하는 표현('메뉴판에 있는 구성대로'·'정해진 배달 가능 지역'·'고객센터를 통해 안내해 드리고
    있어요' 등)이 있으면 True."""
    return bool(_PRINCIPLE.search(text or ""))


def review_menu_items(review_text: str, menu_names: list[str]) -> list[str]:
    """리뷰에 나온 메뉴 이름 (메뉴 이름 전체, 또는 띄어쓰기로 나눈 3글자 이상 조각. 예: '불고기 덮밥' → '불고기')."""
    names = {n for name in menu_names for n in (" ".join(name.split()), *(t for t in name.split() if len(t) >= 3))}
    return sorted((n for n in names if n and n in (review_text or "")), key=len, reverse=True)


def mentions_review_items(text: str, review_text: str, menu_names: list[str]) -> bool:
    """리뷰에 메뉴 이름이 나오면 답글도 그중 하나를 짚어야 True (어느 리뷰에나 붙는 일반 문장을 막는다).
    리뷰에 메뉴 이름이 없으면(예: 배달 지역) True."""
    items = review_menu_items(review_text, menu_names)
    return not items or any(item in (text or "") for item in items)
