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
_EXAGGERATION = re.compile(r"최고|무조건|100%")
_STORE_CIRCUMSTANCE = re.compile(r"매출|손님이\s*줄|경기가?\s*안\s*좋|장사가?\s*안\s*돼|하락세|매출\s*감소|감소세")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_ALL_MEASURE_TEXTS = [m["text"] for m in MEASURES]
_OVERPROMISE = re.compile(r"없을\s*거예요|절대|다시는\s*없|완벽|도입했|마련했|이미\s*(도입|마련|적용)")
_CLAIMED_ACTION = re.compile(r"(?:보내|챙겨|환불해|다시\s*보내)\s*드렸|재발송(?:했|\s*드렸)")
# 공지의 사과(has_apology). '죄송'만 보면 '사과드립니다'·'사과의 말씀 드립니다'·'송구스럽습니다'처럼 정중한 사과가
# 걸려 다시 쓰기를 다 쓰고 템플릿으로 갔다(11/15 실시간 8번 중 3번). 과일 '사과'와 헷갈리지 않게 뒤에 붙는 말까지 본다.
_APOLOGY = re.compile(r"죄송|사과\s*(?:드리|드립|드려|드렸|말씀)|사과(?:의|를)\s*(?:말씀|드)|송구|불찰|면목")
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


# 사과하는 말이 글 어디에든 있는가 (첫 문장 강제가 아님). 가게 과실 불만의 답글에 쓴다.
_APOLOGY_ANYWHERE = re.compile(r"죄송|죄스|사과|미안|불찰|송구|면목|불편(?:을|도|이)?\s*(?:드려|드렸|끼쳐|끼쳤)|불편하게\s*해")


def has_apology_anywhere(text: str) -> bool:
    """글 전체에 사과 표현("죄송", "사과", "미안", "불찰", "송구", "불편을 드려" 등)이 하나라도 있으면 True."""
    return bool(_APOLOGY_ANYWHERE.search(text or ""))


def has_apology(text: str) -> bool:
    """글의 처음 두 문장 안에 사과('죄송'·'사과드립니다'·'사과의 말씀'·'송구'·'불찰'·'면목')가 있으면 True."""
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


# 공지(c6.notice)에서는 자연스러워 딱딱함으로 보지 않는 말. '고객 여러분께'·'배달 과정에서'는 모든 손님에게 알리는
# 공지의 보통 말투다(11/15 실시간: 이 두 말만으로 다시 쓰기를 쓰고 템플릿으로 간 공지가 있었음). 홍보글·답글은 그대로 본다.
NOTICE_ALLOWED_STIFF = ("과정에서", "여러분")


def stiff_words_in(text: str, allow: tuple[str, ...] = ()) -> list[str]:
    """글에 든 사전(STIFF_WORDS)의 딱딱한 표현 목록 (allow 에 든 말은 뺀다). 다시 쓰기 힌트에 그대로 보여 준다."""
    return [w for w in STIFF_WORDS if w in (text or "") and w not in allow]


def has_stiff_words(text: str, allow: tuple[str, ...] = ()) -> bool:
    return bool(stiff_words_in(text, allow))


# '기재'는 뒤에 붙는 말에 따라 바꿔야 한다. 그냥 '적어'로 바꾸면 '기재해 주시면' → '적어해 주시면'(깨진 어미),
# '기재 부탁드립니다' → '적어 부탁드립니다'가 된다(11/15 실시간 공지에서 그대로 나옴). 아래 꼴만 바꾸고, 그 밖의
# '기재…'는 그대로 둬서 점검(no_stiff_words)이 계속 걸리게 한다 — 틀린 문장을 만드는 것보다 낫다.
_GIJAE_FIXES = (
    (re.compile(r"기재\s*부탁드립니다"), "적어 주시기 바랍니다"),
    (re.compile(r"기재\s*부탁드려요"), "적어 주세요"),
    (re.compile(r"기재\s*부탁드리"), "적어 주시기 부탁드리"),
    (re.compile(r"기재(?:해|하여)\s*주"), "적어 주"),
    (re.compile(r"기재해\s*(?=두|놓|넣)"), "적어 "),
    (re.compile(r"기재하시"), "적으시"),
)
# 합니다체 글(공지·홍보글·합니다체 답글)에서 쓰는 치환. 기본 사전 값은 해요체라 공지에 넣으면 말투가 섞인다.
# '사과드리며'는 이어지는 말이라 '죄송합니다'로 끊지 않고 '죄송하며'로 잇는다.
_FORMAL_STIFF_FIXES = {
    "진심으로 사과드리며": "진심으로 죄송하며",
    "최선을 다할 예정입니다": "더 신경 쓰겠습니다",
    "최선을 다할 예정": "더 신경 쓸 예정",
}
# 다시 쓰기 힌트에 보여 줄 바꿀 말 (사전 값이 없거나 꼴에 따라 다른 것)
_STIFF_SUGGEST = {"기재": "적어 주세요 / 적어 주시기 바랍니다", "여러분": "모든 분", "과정에서": "다른 말로"}


def fix_stiff_words(text: str, formal: bool = False) -> str:
    """뜻이 바뀌지 않는 것만 사전대로 바꾼다 (치환 쌍이 있는 것만).
    formal=True(공지·홍보글·합니다체 답글)면 '진심으로 사과드리며'·'최선을 다할 예정'을 합니다체로 바꾼다
    (_FORMAL_STIFF_FIXES). '기재'는 꼴별로만 바꾼다(_GIJAE_FIXES)."""
    for pattern, new in _GIJAE_FIXES:
        text = pattern.sub(new, text)
    if formal:
        for old, new in _FORMAL_STIFF_FIXES.items():
            text = text.replace(old, new)
    for old, new in STIFF_WORDS.items():
        if old == "기재":
            continue
        if new is not None and old in text:
            text = text.replace(old, new)
    return text


def stiff_words_hint(text: str, allow: tuple[str, ...] = (), formal: bool = False) -> str:
    """'딱딱한 표현: '기재' → 적어 주세요 / …, '이러한' → 이런' 처럼 글에서 실제로 걸린 말과 바꿀 말 한 줄. 없으면 ''."""
    words = stiff_words_in(text, allow)
    if not words:
        return ""
    parts = []
    for w in words:
        new = _FORMAL_STIFF_FIXES.get(w) if formal else None
        new = new or _STIFF_SUGGEST.get(w) or STIFF_WORDS.get(w)
        parts.append(f"'{w}' → {new}" if new else f"'{w}' → 빼거나 다른 말로")
    return "글에서 걸린 딱딱한 표현: " + ", ".join(parts) + ". 이 말들을 쓰지 말고 다시 써 주세요."


def quoted_chunks(text: str, reviews) -> list[str]:
    """글이 리뷰 원문에서 그대로 가져온 8자 구절들 (겹치는 구절은 하나로 이어 붙여 보여 준다)."""
    found: list[str] = []
    for rv in reviews:
        body = rv.text
        run = ""
        for i in range(max(len(body) - 8, 0) + 1):
            chunk = body[i:i + 8]
            if len(chunk) == 8 and chunk in text:
                run = chunk if not run else run + chunk[-1]
            elif run:
                found.append(run)
                run = ""
        if run:
            found.append(run)
    return list(dict.fromkeys(found))


def quote_hint(text: str, reviews) -> str:
    """'리뷰 원문을 그대로 쓴 구절: '…' / '…'' 한 줄. 없으면 ''."""
    chunks = quoted_chunks(text, reviews)
    if not chunks:
        return ""
    return "리뷰 원문을 그대로 쓴 구절: " + " / ".join(f"'{c}'" for c in chunks) + ". 이 구절은 다른 말로 바꿔 새로 써 주세요."


# 해요체 어미 → 합니다체 어미 (줄 끝만). 공지가 다시 쓰기 뒤에도 notice_formal 만 걸렸을 때 c6.notice 가 쓴다.
# 받침 규칙이 단순한 꼴만 넣었다 — 표에 없는 꼴(예: '만들게요')은 바꾸지 않아 점검이 계속 걸린다(템플릿으로 감).
_FORMAL_ENDINGS = (
    ("드릴게요", "드리겠습니다"), ("할게요", "하겠습니다"), ("릴게요", "리겠습니다"), ("길게요", "기겠습니다"),
    ("쓸게요", "쓰겠습니다"), ("볼게요", "보겠습니다"),
    ("있어요", "있습니다"), ("없어요", "없습니다"), ("었어요", "었습니다"), ("았어요", "았습니다"),
    ("겠어요", "겠습니다"), ("드려요", "드립니다"), ("돼요", "됩니다"), ("이에요", "입니다"), ("예요", "입니다"),
    ("해요", "합니다"),
)
_LINE_END_PUNCT = re.compile(r"([.!?~…]*)\s*$")


def to_formal_endings(text: str) -> str:
    """줄마다 끝 어미가 해요체이면 표(_FORMAL_ENDINGS)대로 합니다체로 바꾼다. 줄 구조는 그대로 둔다."""
    out = []
    for line in (text or "").splitlines():
        stripped = line.rstrip()
        punct = _LINE_END_PUNCT.search(stripped).group(1)
        core = stripped[: len(stripped) - len(punct)] if punct else stripped
        for old, new in _FORMAL_ENDINGS:
            if core.endswith(old):
                core = core[: -len(old)] + new
                break
        out.append(core + punct)
    return "\n".join(out)


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


# 답글의 AI 공감·사과 부분이 맞출 말투(c6.measures.REPLY_AI_REGISTER)별 힌트. 말투를 적지 않으면
# apology_expressed 힌트("죄송하다는 사과")가 '죄송합니다'를 불러와 해요체 답글의 style_match 가 걸리고,
# 다시 '~요'로 고치면 사과가 빠지는 핑퐁이 난다(11/15 실시간 측정: 다시 쓰기 2번을 다 쓰고 템플릿으로 감).
_REGISTER_HINTS = {
    "해요체": {
        "style_match": "해요체로만 써 주세요. 모든 문장을 '~요'로 끝내 주세요(예: '정말 죄송해요'). "
                       "'죄송합니다'·'사과드립니다'처럼 '~습니다/~니다'로 끝내지 마세요.",
        "apology_expressed": "가게 잘못일 수 있는 불만이에요. 글 안에 해요체 사과를 한 번 넣어 주세요(예: '정말 죄송해요'). "
                             "'죄송합니다'처럼 '~니다'로 끝내지 마세요.",
        "has_apology": "처음 두 문장 안에 해요체 사과를 넣어 주세요(예: '정말 죄송해요').",
    },
    "합니다체": {
        "style_match": "합니다체로만 써 주세요. 모든 문장을 '~습니다/~니다'로 끝내 주세요(예: '정말 죄송합니다'). "
                       "'죄송해요'처럼 '~요'로 끝내지 마세요.",
        "apology_expressed": "가게 잘못일 수 있는 불만이에요. 글 안에 합니다체 사과를 한 번 넣어 주세요(예: '정말 죄송합니다'). "
                             "'죄송해요'처럼 '~요'로 끝내지 마세요.",
        "has_apology": "처음 두 문장 안에 합니다체 사과를 넣어 주세요(예: '정말 죄송합니다').",
    },
}


def fix_hints(failed: list[str], formal: bool = False, register: str | None = None) -> list[str]:
    """failed 점검 이름 -> 고치는 법 한 줄. formal=True(공지)면 no_stiff_words 힌트에 '구어체'를
    쓰지 않는다 — 공지는 합니다체가 기본이라 '구어체로 바꿔 주세요'가 합니다체 요구와 반대로 들린다.
    register('해요체'|'합니다체', 답글 AI 부분의 목표 말투)를 주면 style_match·apology_expressed·has_apology
    힌트에 그 말투와 사과 예시를 적는다(_REGISTER_HINTS). 주지 않으면 예전 문구 그대로다."""
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
        "apology_expressed": "가게 잘못일 수 있는 불만이에요. 글 안에 불편을 드려 죄송하다는 사과를 한 번 넣어 주세요.",
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
    if formal:
        mapping["no_stiff_words"] = "사전에 있는 딱딱한 표현을 더 자연스러운 표현으로 바꿔 주세요(합니다체는 유지)."
    mapping.update(_REGISTER_HINTS.get(register, {}))
    return [mapping.get(f, f"{f}을(를) 수정해 주세요.") for f in failed]


# 사과 어미를 목표 말투로 바꾸는 표 (문장 끝만 본다). 다시 쓰기를 다 써도 style_match 만 남았을 때 c6.reply 가
# 쓴다 — '공깃밥이 빠져 정말 죄송합니다.'처럼 공감은 잘 썼는데 사과 어미만 다른 글을 템플릿으로 통째 덮지 않기 위해서다.
_APOLOGY_ENDING_TO = {
    "haeyo": ((r"죄송(?:스럽)?습니다|죄송합니다", "죄송해요"), (r"사과\s*드립니다", "사과드려요"),
              (r"죄송한\s*마음입니다", "죄송한 마음이에요"), (r"미안합니다", "미안해요")),
    "hamnida": ((r"죄송해요", "죄송합니다"), (r"사과\s*드려요", "사과드립니다"),
                (r"죄송한\s*마음이에요", "죄송한 마음입니다"), (r"미안해요", "미안합니다")),
}
_APOLOGY_ENDING_TO["mixed"] = _APOLOGY_ENDING_TO["haeyo"]   # mixed 는 AI 부분이 해요체 (c6.measures.REPLY_AI_REGISTER)


def fix_apology_ending(ai_part: str, style: str) -> str:
    """문장 끝이 사과 어미('죄송합니다'·'사과드립니다' 등)인 문장만 style(haeyo|hamnida|mixed)의 말투로 바꾼다.
    사과가 아닌 문장의 어미('속상하셨을 것 같습니다')는 건드리지 않는다 — 그런 글은 style_match 가 그대로 걸린다."""
    rules = _APOLOGY_ENDING_TO.get(style)
    if not rules or not ai_part or not ai_part.strip():
        return ai_part
    out = []
    for sentence in _SENT_SPLIT.split(ai_part.strip()):
        for pattern, ending in rules:
            fixed = re.sub(rf"(?:{pattern})(?=[.!?~…]*$)", ending, sentence)
            if fixed != sentence:
                sentence = fixed
                break
        out.append(sentence)
    return " ".join(out)


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
    has_apology(공지의 처음 두 문장 사과)와 뜻이 다르다: 글 전체에서 과실을 인정하는 말을 찾는다."""
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
