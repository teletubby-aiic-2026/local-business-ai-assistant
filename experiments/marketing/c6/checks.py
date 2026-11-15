"""C6 공통 점검 — 모두 순수 함수, AI 호출 없음."""

import difflib
import re

from c6.measures import COMPONENT_ITEMS, INVENTED_KW, MEASURE_KEYWORDS, MEASURES

try:
    from features.tone import FOOD_WORDS
except ImportError:
    FOOD_WORDS = []

_MONEY_KEYWORDS = re.compile(r"환불|쿠폰|무료|서비스|보상|증정|할인")
_PHONE = re.compile(r"01[016789]-?\d{3,4}-?\d{4}")
_ADDR = re.compile(r"[가-힣]+(시|도|구|군|동|로|길)\s*\d")
_NICK = re.compile(r"[가-힣]{2,4}\s*(님|씨)")
_COUPON_WORDS = re.compile(r"할인|쿠폰|코드|반값|%|원")
_EXAGGERATION = re.compile(r"최고|무조건|100%")
_UNVERIFIED_CLAIM_WORDS = ("인기 메뉴", "가장 인기", "1위", "최고", "많은 분들이")
_NOTICE_COMPLAINT_WORDS = ("항의",)
_STORE_CIRCUMSTANCE = re.compile(r"매출|손님이\s*줄|경기가?\s*안\s*좋|장사가?\s*안\s*돼|하락세|매출\s*감소|감소세")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_ALL_MEASURE_TEXTS = [m["text"] for m in MEASURES]
_OVERPROMISE = re.compile(r"없을\s*거예요|절대|다시는\s*없|완벽|도입했|마련했|이미\s*(도입|마련|적용)")
_CLAIMED_ACTION = re.compile(r"(?:보내|챙겨|환불해|다시\s*보내)\s*드렸|재발송(?:했|\s*드렸)")
_APOLOGY = re.compile(r"죄송")
_FEWSHOT_WORDS = ("국물", "넉넉하다", "집밥")
_PERSONAL_ADDRESS = re.compile(r"고객님|주문하신|구매하신|손님께서는")
_AI_EMPATHY_FORBIDDEN = re.compile(
    r"챙[기겨길]|대조|요청사항|앞으로|다음부터|다음에[는도]?\s*(?:꼭|잘)"
    r"|(?:드릴게요?|드리겠습니다|드리겠어요)[.!?]?(?=\s|$)"
)
_BROKEN_ENDING = re.compile(r"[어아]해\s?주|해해|주세주세요")
_FORMAL_END = re.compile(r"(합니다|습니다|됩니다|입니다|바랍니다|드립니다)[.!?]?\s*$")
_INFORMAL_END = re.compile(r"(해요|게요|어요|아요|예요|죠)[.!?]?\s*$")
_STYLE_SUFFIX = {"haeyo": "요", "hamnida": "니다", "mixed": "요"}

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
    "절차를 도입": None, "소중한 지적": None, "과정에서": None,
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


def has_claimed_action(text: str) -> bool:
    """'공깃밥 추가로 보내드렸어요'처럼 아직 하지 않은 보상·조치를 이미 처리한 것처럼 말하면 True.
    reply·notice 공용 — P1(다음 주문 요청사항에 적어 주시면 챙겨 드림)은 미래형으로만 말해야 한다."""
    return bool(_CLAIMED_ACTION.search(text))


def has_apology(text: str) -> bool:
    """글의 처음 두 문장 안에 사과("죄송")가 있으면 True."""
    if not text or not text.strip():
        return False
    sentences = _SENT_SPLIT.split(text.strip())
    return bool(_APOLOGY.search(" ".join(sentences[:2])))


def no_broken_ending(text: str) -> bool:
    """'적어해주세요'·'어해주'·'아해주'·'해해'·'주세주세요'처럼 동사 뒤에 '해'가 잘못 붙거나
    어미가 겹친 깨진 형태가 없으면 True(공지·답글·쿠폰 공용)."""
    if not text:
        return True
    return not bool(_BROKEN_ENDING.search(text))


def ai_part_only_empathy(text: str) -> bool:
    """답글에서 AI 가 쓰는 건 공감·사과뿐 — 조치·요청사항·감사 인사는 코드가 붙이니,
    AI 가 쓴 부분에 '챙기/챙겨/챙길'·'대조'·'요청사항'·'앞으로'·'다음부터'·'다음에는 꼭/잘',
    또는 '드릴게요'·'드리겠습니다'로 끝나는 약속형 문장이 없어야 True.
    ('감사'·'다음에'는 자연스러운 공감 표현에도 섞여 나올 수 있어 허용한다)"""
    if not text:
        return True
    return not bool(_AI_EMPATHY_FORBIDDEN.search(text))


def style_match(ai_part: str, style: str) -> bool:
    """AI 가 쓴 공감·사과 부분만 본다(코드가 붙이는 M1·P1·인사·마무리는 점검 대상이 아니다).
    haeyo/mixed 는 해요체(어미 '요'), hamnida 는 합니다체(어미 '니다')로 끝나야 True."""
    suffix = _STYLE_SUFFIX.get(style)
    if suffix is None:
        return True
    sentences = [s.strip() for s in _SENT_SPLIT.split(ai_part.strip())] if ai_part and ai_part.strip() else []
    sentences = [s for s in sentences if s]
    if not sentences:
        return False
    return all(s.rstrip(".!?").endswith(suffix) for s in sentences)


def notice_has_start(text: str, start_label: str) -> bool:
    """공지 본문에 시작 시점 표현(start_label, 예: '오늘부터')이 그대로 들어 있으면 True."""
    return bool(start_label) and start_label in text


def notice_not_personal(text: str) -> bool:
    """공지는 손님 한 명이 아니라 모두에게 알리는 글이라, '고객님'·'주문하신'처럼
    한 사람을 가리키는 말이 없어야 True."""
    return not bool(_PERSONAL_ADDRESS.search(text))


def has_exaggeration(text: str) -> bool:
    """'최고'·'무조건'·'100%' 같은 과장 표현이 있으면 True. 홍보글(coupon_promo) 전용."""
    return bool(_EXAGGERATION.search(text))


def store_circumstance_leaked(text: str) -> bool:
    """'매출 감소'·'손님이 줄어' 같은 가게 사정(상권 지표)이 손님용 글에 섞여 있으면 True.
    이런 사정은 reason_text(사장님용)에만 남기고, 홍보글 본문에는 쓰지 않는다."""
    return bool(_STORE_CIRCUMSTANCE.search(text))


_QUOTE_MARKS = re.compile(r"[\"'“”‘’].{1,40}[\"'“”‘’]")
# "라고" 뒤에 실제 전달 동사(해/하셨/하시/말씀/했)가 와야 인용으로 본다 — "~라고 생각합니다"처럼
# 손님 얘기가 아니라 사장님 자신의 의견을 말할 때(문장 안에 "손님"이 그냥 섞여 있는 경우)까지
# 걸리는 걸 막는다.
_CUSTOMER_QUOTE_PHRASE = re.compile(r"손님(?:들)?(?:께서|이)?\s*[^.?!]{0,20}라고\s*(?:해|하셨|하시|말씀|했)")


def quotes_customer_speech(text: str) -> bool:
    """따옴표('…'·"…")로 감싼 손님 말 인용이나 '손님들께서 …라고 해 주셨다' 형태가 있으면 True.
    quotes_review(원문 그대로 베낌)와 달리, 문장을 바꿔 인용해도 잡는다. 홍보글(coupon_promo)은
    손님 후기를 인용하지 않는다."""
    if _QUOTE_MARKS.search(text):
        return True
    return bool(_CUSTOMER_QUOTE_PHRASE.search(text))


def only_coupon_menu_mentioned(text: str, menu_names: list[str], coupon_menu: str | None) -> bool:
    """홍보글은 쿠폰 메뉴 하나만 소개한다. coupon_menu 가 아닌 다른 메뉴 이름이 글에 있으면 False.
    coupon_menu 가 없으면(메뉴를 못 정함) 점검 대상이 아니므로 True. 2글자 이하 메뉴 이름("밥"·
    "국" 등)은 일반 낱말과 겹치기 쉬워 substring 비교에서 뺀다(진짜 다른 메뉴는 보통 3글자 이상)."""
    if not coupon_menu:
        return True
    others = [m for m in menu_names if m != coupon_menu and len(m) > 2]
    return not any(m in text for m in others)


def promo_formal(text: str) -> bool:
    """홍보글이 합니다체 위주면 True. 공지(notice_formal)는 줄바꿈된 한 줄 = 한 문장이지만,
    홍보글은 여러 문장이 한 줄에 이어지므로 문장 단위(_SENT_SPLIT)로 끝을 본다."""
    if not text or not text.strip():
        return False
    sentences = [s.strip() for s in _SENT_SPLIT.split(text.strip()) if s.strip()]
    if not sentences:
        return False
    formal = sum(1 for s in sentences if _FORMAL_END.search(s))
    informal = sum(1 for s in sentences if _INFORMAL_END.search(s) and not _FORMAL_END.search(s))
    return formal > 0 and formal >= informal


def notice_formal(text: str) -> bool:
    """공지 문장이 합니다체 위주면 True. 문장마다 줄바꿈된 줄을 한 줄 = 한 문장으로 본다."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return False
    formal = sum(1 for ln in lines if _FORMAL_END.search(ln))
    informal = sum(1 for ln in lines if _INFORMAL_END.search(ln) and not _FORMAL_END.search(ln))
    return formal > 0 and formal >= informal


def notice_informal_lines(text: str) -> list[str]:
    """notice_formal 이 걸릴 때, 해요체(-요)로 끝난 줄을 그대로 찾아 다시 쓰기 지시에 보여 준다."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    return [ln for ln in lines if _INFORMAL_END.search(ln) and not _FORMAL_END.search(ln)]


def notice_vs_reply(text: str, reply_texts: list[str] | None) -> bool:
    """공지가 답글들과 너무 비슷하면(too_similar) False. reply_texts 가 없으면 True."""
    if not reply_texts:
        return True
    return not any(too_similar(text, rt) for rt in reply_texts)


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


# 메뉴 설명·구성품에 없으면 지어낸 재료로 보는 흔한 식재료 단어들(review_promo·coupon_promo 공용).
_INVENTED_INGREDIENT_WORDS = (
    "채소", "참깨", "치즈", "버섯", "계란", "달걀", "새우", "베이컨", "고수", "야채", "나물", "샐러드",
)


def invented_ingredient(text: str, menu_descriptions: dict[str, str] | None = None) -> bool:
    """메뉴 설명·구성품(COMPONENT_ITEMS)에 없는 식재료 단어가 글에 있으면 True.
    홍보글(coupon_promo·review_promo) 전용 — AI 가 메뉴에 없는 재료를 지어내 소개하지 않도록 막는다."""
    known = " ".join((menu_descriptions or {}).values()) + " " + " ".join(COMPONENT_ITEMS)
    return any(w in text and w not in known for w in _INVENTED_INGREDIENT_WORDS)


def has_unverified_claim(text: str) -> bool:
    """근거 없는 인기·순위 주장("인기 메뉴"·"최고"·"1위" 등)이 있으면 True."""
    return any(w in text for w in _UNVERIFIED_CLAIM_WORDS)


def notice_no_complaint_word(text: str) -> bool:
    """공지에 '항의' 같은 단어가 있으면 False(손님을 자극하는 단어는 안 써요)."""
    return not any(w in text for w in _NOTICE_COMPLAINT_WORDS)


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


def fix_hints(failed: list[str], formal: bool = False) -> list[str]:
    """failed 점검 이름 -> 고치는 법 한 줄. formal=True(공지)면 no_stiff_words 힌트에 '구어체'를
    쓰지 않는다 — 공지는 합니다체가 기본이라 '구어체로 바꿔 주세요'가 합니다체 요구와 반대로 들린다."""
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
        "no_claimed_action": "'보내드렸어요'·'챙겨 드렸'·'환불해 드렸'·'다시 보내'·'재발송'처럼 아직 하지 않은 "
                              "보상·조치를 이미 처리한 것처럼 쓰지 말고, '챙겨 드릴게요'처럼 앞으로 할 일로 써 주세요.",
        "has_apology": "처음 두 문장 안에 불편을 드려 죄송하다는 사과를 넣어 주세요.",
        "notice_has_start": "시작 시점 표현(예: '오늘부터')을 그대로 넣어 주세요.",
        "notice_not_personal": "'고객님'·'주문하신'처럼 한 사람을 가리키는 말 대신, 모든 손님에게 알리는 투로 써 주세요.",
        "notice_formal": "해요체 대신 합니다체로 써 주세요.",
        "notice_vs_reply": "답글과 너무 비슷해요. 공지만의 말투로 다시 써 주세요.",
        "ai_part_only_empathy": "공감·사과만 써 주세요. 챙겨 드리겠다는 약속이나 조치·요청사항·감사 인사는 코드가 따로 붙여요.",
        "style_match": "말투를 섞지 말고 지정된 말투(해요체 또는 합니다체)로만 써 주세요.",
        "no_fewshot_copy": "예시 문구의 단어를 그대로 베끼지 말고, 같은 단어를 가까이서 반복하지 말아 주세요.",
        "no_unknown_menu": "메뉴에 있는 음식 이름만 써 주세요.",
        "no_markdown": "마크다운 기호(**, #, ` 등) 없이 일반 문장으로 써 주세요.",
        "no_broken_ending": "'적어해주세요'처럼 깨진 어미 대신 '적어 주세요'처럼 띄어 쓰는 바른 형태로 써 주세요.",
        "no_exaggeration": "'최고'·'무조건'·'100%' 같은 과장 표현은 빼 주세요.",
        "no_store_circumstance": "'매출 감소'·'손님이 줄어' 같은 가게 사정 얘기는 빼고, 메뉴의 실제 특징만 써 주세요.",
        "only_coupon_menu": "쿠폰 메뉴만 소개해 주세요. 다른 메뉴 이름은 쓰지 마세요.",
        "no_customer_quote": "손님 후기를 인용하지 않는다. 따옴표로 손님 말을 옮기거나 '손님들께서 ...라고' 처럼 "
                              "쓰지 말고, 메뉴 특징을 직접 설명해 주세요.",
        "promo_formal": "해요체 대신 합니다체로 써 주세요.",
        "no_invented_ingredient": "메뉴 설명에 없는 재료(채소·참깨·치즈·버섯·계란 등)는 지어내지 말고 빼 주세요.",
        "no_unverified_claim": "'인기 메뉴'·'가장 인기'·'1위'·'최고'·'많은 분들이' 같은 근거 없는 인기·순위 주장은 빼 주세요.",
        "notice_no_complaint_word": "'항의' 같은 손님을 자극하는 단어는 빼 주세요.",
    }
    if formal:
        mapping["no_stiff_words"] = "사전에 있는 딱딱한 표현을 더 자연스러운 표현으로 바꿔 주세요(합니다체는 유지)."
    return [mapping.get(f, f"{f}을(를) 수정해 주세요.") for f in failed]
