"""쿠폰 홍보글 생성기 — promo 카드의 상권 지표 기반 홍보.

AI 는 본문만 쓴다. 쿠폰 값(메뉴·할인 금액·유효기간·시간대 조건)은 숫자이므로 코드가 글 끝에 한 줄로
붙이고, 근거(snapshot_id · coupon:메뉴)도 코드가 정한다 — AI 가 준 근거 문자열은 쓰지 않는다.
쿠폰 메뉴는 가격 있는 메뉴 가운데 손님 칭찬 리뷰에 가장 많이 언급된 것이다 (shared.praise.pick_praised_menu, 카드 ⓑ 근거와 같은 기준).
매출·하락 같은 상권 지표는 손님용 글에 넣지 않는다 — reason_text(사장님용)에만 남긴다.

네이버 플레이스 소식 형식이라 공지(c6.notice)와 같은 합니다체로 쓴다 — 사장님 개인 말투(ToneProfile)
가 아니라, 모두에게 알리는 공개 소식 말투다. 두 번 다시 써도 점검을 못 넘으면 코드 템플릿으로
바꿔 넣는다(c6.reply·c6.notice 의 used_fallback 과 같은 방식).
"""

import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import clova
from c6 import checks
from c6 import parsing
from c6.output import CALL_FAILED_NOTE, CALL_FAILED_NOTE_NO_TEXT, DraftOutput, CardResult
from common.korean import display_name, eul
from shared.praise import menu_mentions, pick_praised_menu, praise_reviews

_MAX_REWRITES = 2  # 답글·공지와 같은 한도 — 이만큼 다시 써도 점검을 못 넘으면 코드 템플릿으로 바꿔 넣는다

# 쿠폰 생성기 전용 few-shot 예시 (reply 스타일 예시는 어투가 달라 안 맞는다)
# 메뉴·리뷰와 무관한 문장으로 둔다 — AI 가 이 예시의 말투만 배우고, 메뉴·수식어는 그대로 베끼지 않도록.
# 예시는 홍보글 점검을 모두 통과해야 한다 (tests/test_c6_promo_repair.py). 11/15 전 예시는 "손님들이 '양이 넉넉하다'고
# 해 주신"이라 따옴표·손님 말 옮기기(no_customer_quote)와 '넉넉하다'(no_fewshot_copy)를 예시가 직접 가르쳤다 —
# 실시간 10번 중 5번의 후보가 "'양도 많고 맛있다'고 해주신"처럼 그대로 따라 썼다.
PROMO_EXAMPLE = (
    "요즘 저녁 메뉴가 고민되실 때 든든한 한 끼로 추천드립니다. "
    "매일 정성껏 준비해 보내드리니 편하게 주문해 보세요."
)

SYSTEM_TMPL = """\
당신은 {store_name} 사장님입니다. 네이버 플레이스 소식(쿠폰 홍보글) 본문을 작성하세요.
인사말이나 마무리 인사는 따로 안 붙여도 됩니다. JSON이 아니라 문장 그대로 답해도 됩니다.

## 말투 (반드시 지킬 것)
모든 문장을 합니다체로 쓸 것(해요체·반말 금지) — 문장 끝이 "-습니다"·"-니다"·"-세요"·"-바랍니다" 중
하나로 끝나야 합니다.

## 좋은 예시 (이런 느낌으로)
- {example}

## 쿠폰 메뉴 (이 메뉴 하나만 소개할 것 — 다른 메뉴는 이름도 꺼내지 말 것)
{menu_section}
{praise_section}

## 규칙
1. 2~3문장, 60~160자
2. 손님용 홍보글에는 상권 지표·매출·수치를 넣지 않는다. "매출 감소", "손님이 줄어" 같은 가게 사정도
   쓰지 않는다
3. 위 쿠폰 메뉴 하나만 소개할 것. 다른 메뉴 이름은 언급하지 말 것
4. 메뉴 설명은 위 "쿠폰 메뉴"·"손님 반응"에 적힌 내용만 쓸 것 — 거기 없는 재료·조리법·맛 표현을 지어내지
   말 것. 특히 메뉴 설명에 없으면 채소·참깨·치즈·버섯·계란 같은 재료 이름을 넣지 말 것
5. 손님 반응이 있으면 그 칭찬받은 점의 느낌만 참고해 내 말로 쓴다. 손님 후기를 인용하지 않는다 —
   따옴표('·")를 쓰지 말고, "손님들께서 ...라고/다고 해 주셨다", "...다며 ...하는 손님들"처럼 손님 말을 옮기지 말 것
6. 할인·가격·숫자·쿠폰·코드·반값·% 는 쓰지 않는다 (코드가 글 끝에 쿠폰 값을 따로 붙인다)
7. 메뉴판에 없는 가격·숫자를 넣지 말 것
8. 고객 개인정보 금지
9. 위 예시의 단어·수식어를 그대로 베끼지 말 것 — 예시는 말투만 참고하고, 내용은 위 쿠폰 메뉴·손님 반응에서만 가져올 것
10. "리뷰 남기면 서비스 드려요" 처럼 정책에 없는 보상을 약속하지 말 것
11. 위 쿠폰 메뉴 외의 음식 이름은 쓰지 말 것
12. 마크다운 문법(**, #, ` 등)을 쓰지 말 것
13. "최고", "무조건", "100%" 같은 과장 표현을 쓰지 말 것
14. 배달 주문 기준으로 쓸 것. "들러"·"방문"처럼 가게에 오는 것을 전제한 표현은 쓰지 말 것
"""

# card.reason_text 에 남아 있을 수 있는 변화율 자리표시자("-X%"). snapshot.value 가 있으면
# 실제 값("-19.31%")으로 바꿔 끼운다. 바꾼 뒤에도 이 패턴이 남으면(=snapshot.value 가 아직
# None) 점검 실패로 본다 — reason_text(사장님용)는 코드가 조립하므로 자리표시자를 그대로 보여주면 안 된다.
_PLACEHOLDER_PCT = re.compile(r"-?X%")

# 쿠폰 줄에 붙일 시간대 조건 — snapshot.metric_name 에 적힌 시간대 키워드로 고른다.
_TIME_WINDOW_LABELS = (
    ("저녁", "저녁 5~9시 주문 시"),
    ("점심", "점심 11~2시 주문 시"),
    ("아침", "아침 7~10시 주문 시"),
    ("야간", "야간 9~12시 주문 시"),
)

# 두 번 다시 써도 점검을 못 넘으면 쓰는 코드 템플릿 (c6.reply·c6.notice 의 used_fallback 과 같은 방식).
# 3문장·합니다체, 배달 주문 기준(들러·방문 표현 없음). 쿠폰 메뉴 이름만 쓰고 숫자·가게 사정은
# 전혀 쓰지 않아 늘 점검을 통과한다. "쿠폰" 이라는 말 자체는 coupon_invented 가 막는 쿠폰 "값"
# 표현(할인·코드·반값·%·원)이 아니므로 "혜택"으로 돌려 쓴다 — 아래 쿠폰 줄은 코드가 따로 붙인다.
_PROMO_FALLBACK_NO_DESC = "정성껏 만들어 따뜻하게 보내드립니다."
_PROMO_FALLBACK_TMPL = (
    "저녁 메뉴 고민되실 때 {store} {item}{item_eul} 추천드립니다. "
    "{desc} "
    "아래 혜택으로 부담 없이 주문해 보세요."
)


def _format_snapshot_value(snap) -> str | None:
    """snapshot.value·unit 을 "-19.31%" 같은 한 조각으로 포맷. value 가 None 이면 None."""
    if snap.value is None:
        return None
    v = snap.value
    text = f"{v:g}" if isinstance(v, float) else str(v)
    return f"{text}{snap.unit}"


def _time_window_label(target_snapshots) -> str | None:
    for snap in target_snapshots:
        for kw, label in _TIME_WINDOW_LABELS:
            if kw in (snap.metric_name or ""):
                return label
    return None


def _fallback_text(store, coupon_menu: str | None) -> str:
    item = coupon_menu or "대표 메뉴"
    menu_descriptions = getattr(store, "menu_descriptions", None) or {}
    desc = menu_descriptions.get(coupon_menu) if coupon_menu else None
    return _PROMO_FALLBACK_TMPL.format(
        store=display_name(store.name), item=item, item_eul=eul(item),
        desc=desc or _PROMO_FALLBACK_NO_DESC,
    )


def _safe_call(key, system, messages, **kw) -> dict:
    """clova.call 을 부르고, 예외가 나도 {"error": 예외 이름} 으로 바꿔 돌려준다 (홍보글 두 생성기 공용).
    clova.call 은 HTTP·연결 오류를 이미 {"error": …} 로 돌려주지만, 그 밖의 예외(응답 모양이 이상함 등)로 서버 요청이
    500 으로 끝나지 않게 한 번 더 막는다. 오류 글에는 예외 이름만 남긴다 (예외 문장에 요청 내용이 섞일 수 있어서)."""
    try:
        resp = clova.call(key, system, messages, **kw)
    except Exception as exc:  # noqa: BLE001 — 어떤 예외든 '호출 실패'로 다룬다
        return {"error": f"{exc.__class__.__name__} (호출 중 예외)"}
    return resp if isinstance(resp, dict) else {"error": "응답 형식이 올바르지 않아요"}


def _clean_promo_text(text_):
    """결과와 무관하게 늘 하던 손질(마크다운 기호 지우기·3문장까지만)을 점검 전에 한다 — 보여 줄 글을 점검해야
    잘라 낼 4번째 문장 때문에 다시 쓰기를 부르지 않는다 (11/15 실시간 후보 대부분이 4문장)."""
    return checks.truncate_sentences(checks.strip_markdown(text_), 3) if text_ else text_


def _check_promo_with_code_fix(text_, check):
    """손질한 글을 점검하고(check(text) -> (점검 결과, 실패 목록)), 딱딱한 표현·해요체 어미가 걸렸으면 사전 치환(합니다체)·
    어미 보정을 해 본다 — 실패가 줄 때만 쓴다 (추가 호출 없음). 공지(c6.notice._check_with_word_fix)와 같은 방식.
    돌려주는 것: (점검한 글, 점검 결과, 실패 목록)."""
    text_ = _clean_promo_text(text_)
    chk_, failed_ = check(text_)
    if failed_ and text_:
        fixed = text_
        if "no_stiff_words" in failed_:
            fixed = checks.fix_stiff_words(fixed, formal=True)
        if "promo_formal" in failed_:
            fixed = checks.to_formal_sentence_endings(fixed)
        if fixed != text_:
            chk2, failed2 = check(fixed)
            if set(failed2) < set(failed_):
                return fixed, chk2, failed2
    return text_, chk_, failed_


def _same_text(a, b):
    """띄어쓰기 차이는 빼고 같은 글인가 (ai_part_repaired 판단용)."""
    return " ".join((a or "").split()) == " ".join((b or "").split())


def _candidate_rank(item):
    """후보 고르기 기준: 글이 있는 쪽이 먼저(호출이 실패해 빈 후보가 점검 통과 수로 이기지 않게), 그다음 점검 통과 수."""
    return bool(item[0]), sum(1 for v in item[2].values() if v)


def _praise_reviews(ctx, n=2, coupon_menu=None):
    """칭찬할 만한 리뷰. sentiment=='positive' 우선, 없으면 평점 4 이상인 것만(없는 복합을 칭찬으로 꾸미지 않는다).

    쿠폰 메뉴를 칭찬한 리뷰가 있으면 그 리뷰를 맨 앞에 두고, 다른 메뉴만 말한 칭찬 리뷰는 뺀다 — '손님 반응'이 쿠폰 메뉴
    이야기여야 글이 그 메뉴 하나만 소개한다 (전에는 쿠폰이 제육볶음 정식인데 "순두부찌개 얼큰하고 맛있어요"가 손님 반응으로
    들어갔다). 쿠폰 메뉴를 칭찬한 리뷰가 없으면 예전 순서 그대로다."""
    positive = [r for r in ctx.reviews if r.sentiment == "positive"]
    if not positive:
        positive = [r for r in ctx.reviews if (r.rating or 0) >= 4]
        positive.sort(key=lambda r: (r.rating or 0), reverse=True)
    if coupon_menu:
        menu = ctx.store.menu
        mine = {rid for row in menu_mentions(menu, praise_reviews(ctx.reviews)) if row["menu"] == coupon_menu
                for rid in row["review_ids"]}
        if mine:
            others = {rid for row in menu_mentions(menu, positive) if row["menu"] != coupon_menu
                      for rid in row["review_ids"]} - mine
            positive = ([r for r in positive if r.review_id in mine]
                        + [r for r in positive if r.review_id not in mine and r.review_id not in others])
    return positive[:n]


# review_promo 전용 — 리뷰를 인용하지 않고 "칭찬 주제"만 넘긴다(아래 _praise_topics).
_PRAISE_TOPIC_KEYWORDS = ("양념", "양", "맛", "포장", "친절", "속도", "가격", "신선")


def _praise_topics(ctx, n=2):
    """리뷰 원문 대신 넘길 칭찬 주제 n개. 칭찬 리뷰(sentiment=='positive', 없으면 평점 4 이상) 안에서
    주제 키워드가 몇 건에 나오는지 세어 많이 나온 순으로 고른다 — 리뷰 원문 자체는 넘기지 않는다."""
    positive = [r for r in ctx.reviews if r.sentiment == "positive"]
    if not positive:
        positive = [r for r in ctx.reviews if (r.rating or 0) >= 4]
    texts = [r.text for r in positive]
    counts = [(kw, sum(1 for t in texts if kw in t)) for kw in _PRAISE_TOPIC_KEYWORDS]
    counts = [(kw, c) for kw, c in counts if c > 0]
    counts.sort(key=lambda kv: kv[1], reverse=True)
    return [kw for kw, _ in counts[:n]]


SYSTEM_TMPL_REVIEW = """\
당신은 {store_name} 사장님입니다. 네이버 플레이스 소식(가게 홍보글) 본문을 작성하세요.
인사말이나 마무리 인사는 따로 안 붙여도 됩니다. JSON이 아니라 문장 그대로 답해도 됩니다.

## 말투 (반드시 지킬 것)
모든 문장을 합니다체로 쓸 것(해요체·반말 금지) — 문장 끝이 "-습니다"·"-니다"·"-세요"·"-바랍니다" 중
하나로 끝나야 합니다.

## 좋은 예시 (이런 느낌으로)
- {example}

## 대표 메뉴 (이 메뉴 하나만 소개할 것 — 다른 메뉴는 이름도 꺼내지 말 것)
{menu_section}
{praise_section}

## 규칙
1. 2~3문장, 60~160자
2. 손님용 홍보글에는 상권 지표·매출·수치를 넣지 않는다. "매출 감소", "손님이 줄어" 같은 가게 사정도
   쓰지 않는다
3. 위 대표 메뉴 하나만 소개할 것. 다른 메뉴 이름은 언급하지 말 것
4. 메뉴 설명은 위 "대표 메뉴"·"칭찬 주제"에 적힌 내용만 쓸 것 — 거기 없는 재료·조리법·맛 표현을 지어내지
   말 것. 특히 메뉴 설명에 없으면 채소·참깨·치즈·버섯·계란 같은 재료 이름을 넣지 말 것
5. 칭찬 주제가 있으면 그 느낌만 참고해 내 말로 쓴다. 손님 후기를 인용하지 않는다 —
   따옴표로 손님 말을 그대로 옮기거나 "손님들께서 ...라고 해 주셨다" 처럼 쓰지 말 것
6. 할인·가격·숫자·쿠폰·코드·반값·% 는 쓰지 않는다 (이 글에는 쿠폰이 없다)
7. 메뉴판에 없는 가격·숫자를 넣지 말 것
8. 고객 개인정보 금지
9. 위 예시의 단어·수식어를 그대로 베끼지 말 것 — 예시는 말투만 참고하고, 내용은 위 대표 메뉴·칭찬 주제에서만 가져올 것
10. "리뷰 남기면 서비스 드려요" 처럼 정책에 없는 보상을 약속하지 말 것
11. 위 대표 메뉴 외의 음식 이름은 쓰지 말 것
12. 마크다운 문법(**, #, ` 등)을 쓰지 말 것
13. "최고", "무조건", "100%" 같은 과장 표현을 쓰지 말 것
14. 배달 주문 기준으로 쓸 것. "들러"·"방문"처럼 가게에 오는 것을 전제한 표현은 쓰지 말 것
"""

# 첫 문장에 이미 '정성껏'이 있어 같은 말을 또 쓰면 템플릿이 스스로 no_fewshot_copy(가까이 되풀이한 말)에 걸린다
# (11/16 확인: 메뉴 설명이 없는 메뉴는 늘 '사장님 확인 필요'가 붙었다). 그래서 쿠폰 템플릿과 다른 문장을 쓴다.
_REVIEW_PROMO_FALLBACK_NO_DESC = "따뜻하게 담아 보내드립니다."
_REVIEW_PROMO_FALLBACK_TMPL = (
    "{store}에서 {item}{item_eul} 정성껏 준비하고 있습니다. "
    "{desc}"
)


def review_promo_fallback_text(store, menu: str | None = None) -> str:
    """AI 없이도 늘 점검을 통과하는 코드 템플릿. CLOVA_API_KEY 가 없는 데모 모드에서 그대로 쓴다
    (review_promo 는 아직 저장본(c6/replay)이 없어 _fallback_text 와 같은 방식을 그대로 쓴다)."""
    item = menu or "대표 메뉴"
    menu_descriptions = getattr(store, "menu_descriptions", None) or {}
    desc = menu_descriptions.get(menu) if menu else None
    return _REVIEW_PROMO_FALLBACK_TMPL.format(
        store=display_name(store.name), item=item, item_eul=eul(item),
        desc=desc or _REVIEW_PROMO_FALLBACK_NO_DESC,
    )


def generate_coupon_promo(ctx, card, key, model="HCX-005", chosen_measures=None,
                           coupon_menu=None, coupon_discount=1000, coupon_days=14,
                           time_window=None):
    store = ctx.store
    tone = ctx.tone
    menu_descriptions = getattr(store, "menu_descriptions", None) or {}
    snapshots = {s.snapshot_id: s for s in ctx.snapshots}
    forbidden_phrases = list(tone.forbidden_phrases) if tone.forbidden_phrases else []

    target_snapshots = [snapshots[sid] for sid in card.snapshot_ids if sid in snapshots]

    needs_input: list[str] = []

    # 근거(사장님용): snapshot 에 실제 값이 있으면 card.reason_text 의 "-X%" 자리표시자를 그 값으로
    # 바꿔 끼운다. 바꾼 뒤에도 자리표시자가 남으면(=아직 수치 미확정) 점검 실패로 본다.
    # 괄호는 basis_label만 남긴다 — 수치는 이미 reason_text 본문에 들어가 있어 괄호에 또 붙이면
    # "...-19.31% 줄었습니다. (..., -19.31%)" 처럼 같은 수치가 중복된다.
    filled_reason = card.reason_text
    basis_label = None
    reason_parts = []
    for snap in target_snapshots:
        basis_label = snap.basis_label
        formatted = _format_snapshot_value(snap)
        if formatted is not None:
            filled_reason = _PLACEHOLDER_PCT.sub(formatted, filled_reason, count=1)
        reason_parts.append(f"({basis_label})")
    reason_text_with_basis = " ".join([filled_reason] + reason_parts)

    if _PLACEHOLDER_PCT.search(reason_text_with_basis):
        needs_input.append("상권 지표 수치 미확정: reason_text에 자리표시자(-X%)가 남아 있어요")

    if coupon_menu is None:
        # 가격 있는 메뉴 가운데 손님 칭찬 리뷰에 가장 많이 언급된 것. 같은 수거나 언급이 없으면 메뉴판 순서 (전에는 늘
        # 메뉴판 첫 메뉴였다). 카드 ⓑ(services/web/web/cards.py)도 같은 함수로 골라, 카드가 말한 메뉴와 쿠폰 메뉴가 같다.
        picked = pick_praised_menu(store.menu, ctx.reviews, priced=store.menu_prices)
        coupon_menu = picked["menu"] if picked else None
    if not store.menu_prices or coupon_menu is None:
        needs_input.append("menu_prices 없음: 쿠폰 메뉴·금액을 정할 수 없어요")

    menu_section = f"- {coupon_menu}" if coupon_menu else "(메뉴 정보 없음)"

    praise = _praise_reviews(ctx, coupon_menu=coupon_menu)
    if praise:
        praise_lines = "\n".join(f'- "{r.text}" (★{r.rating or "?"})' for r in praise)
        praise_section = f"\n## 손님 반응 (참고용, 그대로 베끼지 말고 느낌만)\n{praise_lines}"
    else:
        praise_section = ""

    system = SYSTEM_TMPL.format(
        store_name=store.name,
        example=PROMO_EXAMPLE,
        menu_section=menu_section,
        praise_section=praise_section,
    )

    messages = [{"role": "user", "content": "손님에게 보낼 쿠폰 홍보글 본문을 작성해 주세요."}]

    allowed_numbers = list(store.menu_prices.values())
    review_texts = [r.text for r in ctx.reviews]
    # 쿠폰 메뉴의 재료라 '다른 음식'으로 보지 않을 말 (고기 요리면 '고기') — checks.menu_ingredient_words
    allow_food = checks.menu_ingredient_words(coupon_menu)
    focus_menu = (coupon_menu,) if coupon_menu else ()
    other_menus = tuple(store.menu) if coupon_menu else ()

    def _run_promo_checks(text):
        result = {
            "no_bad_number": not checks.has_number_not_in(text, allowed_numbers),
            "no_personal_info": not checks.personal_info(text),
            "no_broken_ending": checks.no_broken_ending(text),
            "no_coupon_invented": not checks.coupon_invented(text),
            "no_stiff_words": not checks.has_stiff_words(text),
            "no_fewshot_copy": not checks.fewshot_copied(text, store.menu, review_texts),
            "no_bad_promise": not checks.promises_not_in_policy(text, ctx.policies),
            "no_unknown_menu": not checks.mentions_unknown_menu(text, store.menu, allow=allow_food),
            "only_coupon_menu": checks.only_coupon_menu_mentioned(text, store.menu, coupon_menu),
            "not_quote_review": not checks.quotes_review(text, ctx.reviews),
            "no_customer_quote": not checks.quotes_customer_speech(text),
            "no_markdown": not checks.has_markdown(text),
            "no_exaggeration": not checks.has_exaggeration(text),
            "no_store_circumstance": not checks.store_circumstance_leaked(text),
            "promo_formal": checks.promo_formal(text),
            # 쿠폰 메뉴 이름에 든 재료('계란말이'의 '계란')는 지어낸 것이 아니다. 다른 메뉴 이름은 only_coupon_menu 가 잡는다.
            "no_invented_ingredient": not checks.invented_ingredient(text, menu_descriptions, focus_menu, other_menus),
            "no_unverified_claim": not checks.has_unverified_claim(text),
            "length_ok": checks.length_ok(text, 60, 160),
        }
        if forbidden_phrases:
            result["no_forbidden_phrase"] = not checks.forbidden_phrase(text, forbidden_phrases)
        return result

    retry_exempt = ("length_ok",)

    def _check(text_):
        chk_ = _run_promo_checks(text_)
        failed_ = [k for k, v in chk_.items() if not v and k not in retry_exempt]
        return chk_, failed_

    def _check_with_code_fix(text_):
        """손질·코드 보정 뒤 점검 (모듈 도우미 _check_promo_with_code_fix — review_promo 와 같은 방식)."""
        return _check_promo_with_code_fix(text_, _check)

    def _call_candidate(temperature):
        resp = _safe_call(key, system, messages, model=model, max_tokens=512, temperature=temperature)
        raw_ = resp.get("content", "") or ""
        text_ = parsing.extract_body(raw_)  # JSON이든 평문이든 본문을 절대 버리지 않는다
        return text_, raw_, resp.get("won", 0), bool(resp.get("error"))

    start = time.perf_counter()
    total_won = 0.0
    rewrites = 0

    # 후보 2개를 동시에 생성해 점검 통과 수가 많은 쪽을 쓴다
    with ThreadPoolExecutor(max_workers=2) as pool:
        candidates = [f.result() for f in [pool.submit(_call_candidate, 0.4) for _ in range(2)]]
    total_won += sum(c[2] for c in candidates)

    scored = []
    for text_, raw_, _, _error in candidates:
        fixed_, chk_, failed_ = _check_with_code_fix(text_)
        scored.append((fixed_, raw_, chk_, failed_, text_))
    scored.sort(key=_candidate_rank, reverse=True)   # 한 후보의 호출이 실패하면(빈 글) 다른 후보를 쓴다
    text, raw, check_results, failed, last_ai_text = scored[0]   # last_ai_text: HCX 가 쓴 글 그대로 (코드 손질 전)
    # 후보 호출이 모두 실패해 AI 글이 없다 → 다시 쓰기·코드 템플릿 없이 쿠폰 줄만 두고 사장님께 알린다 (아래 CALL_FAILED_NOTE_NO_TEXT)
    call_failed = not text and any(c[3] for c in candidates)

    rewrite_call_failed = False
    while failed and text and rewrites < _MAX_REWRITES:
        # 합니다체 기준 힌트(formal=True — 기본 힌트의 '편한 구어체로'가 해요체 다시 쓰기를 불렀다) + 글에서 실제로 걸린 말
        hints = checks.fix_hints(failed, formal=True) + checks.promo_detail_hints(
            failed, text, menu_names=store.menu, coupon_menu=coupon_menu, review_texts=review_texts,
            reviews=ctx.reviews, allow_food=allow_food, menu_descriptions=menu_descriptions)
        hints.append("지적한 부분만 고치고, 합니다체로 쿠폰 메뉴 하나만 2~3문장으로 소개하는 틀은 그대로 두세요.")
        retry_msg = [
            {"role": "user", "content": "손님에게 보낼 쿠폰 홍보글 본문을 작성해 주세요."},
            {"role": "assistant", "content": text},   # 코드가 손질한 글(보여 줄 글)을 고치게 한다
            {"role": "user", "content": "수정 지시:\n" + "\n".join(f"- {h}" for h in hints)},
        ]
        resp2 = _safe_call(key, system, retry_msg, model=model, max_tokens=512, temperature=0.5)
        total_won += resp2.get("won", 0)
        if resp2.get("error"):     # 다시 쓰기 호출이 끝내 실패 → 더 부르지 않고 AI 글을 그대로 둔다 (점검 실패로 보임)
            rewrite_call_failed = True
            break
        raw = resp2.get("content", "") or ""
        text2 = parsing.extract_body(raw)
        rewrites += 1
        if text2:
            last_ai_text = text2
            text = text2
        text, check_results, failed = _check_with_code_fix(text)

    # 그래도(총 1 + _MAX_REWRITES 번 시도) 점검을 못 넘으면 코드 템플릿으로 바꿔 넣고 통과 처리한다
    # (c6.reply·c6.notice 의 used_fallback 과 같은 방식). needs_input 에는 남기지 않는다 — 대체
    # 문장은 늘 점검을 통과하므로 사람이 볼 필요가 없다.
    used_fallback = bool(failed) and not call_failed and not rewrite_call_failed   # 다시 쓰기 호출이 실패하면 템플릿으로 덮지 않는다 (사장님이 실패를 보게)
    # 최종 글이 HCX 가 마지막으로 쓴 글과 다르면(띄어쓰기 차이는 빼고) 코드가 고친 것 — 3문장 자르기·마크다운 지우기·
    # 사전 치환·어미 보정. 답글·공지와 같은 기준으로 checks.ai_part_repaired 에 남긴다 (measure_live.py 'AI 글 + 코드 보정').
    ai_part_repaired = bool(not call_failed and not failed and not _same_text(text, last_ai_text))
    if used_fallback:
        text = _fallback_text(store, coupon_menu)
        check_results, failed = _check(text)
    check_results["used_fallback"] = used_fallback
    check_results["ai_part_repaired"] = ai_part_repaired

    if failed:
        needs_input.append("사장님 확인 필요")
    if call_failed:   # 호출이 끝내 실패해 AI 글이 없다 (쿠폰 줄만 남음) → 사장님께 알린다
        needs_input.append(CALL_FAILED_NOTE_NO_TEXT)

    elapsed_ms = round((time.perf_counter() - start) * 1000)

    if coupon_menu is not None:
        if time_window is None:
            time_window = _time_window_label(target_snapshots)
        coupon_line = f"🎟 {coupon_menu} {coupon_discount:,}원 할인 쿠폰 · 받은 날 포함 {coupon_days}일"
        if time_window:
            coupon_line += f" · {time_window}"
        final_text = f"{text}\n{coupon_line}" if text else coupon_line
    else:
        final_text = text

    evidence_ids = [s.snapshot_id for s in target_snapshots]
    if coupon_menu is not None:
        evidence_ids.append(f"coupon:{coupon_menu}")
    if not evidence_ids:
        evidence_ids = list(card.evidence_ids)

    draft = DraftOutput(
        draft_id=f"d_{uuid.uuid4().hex[:8]}",
        card_id=card.card_id,
        store_id=store.store_id,
        generator="coupon_promo",
        text=final_text,
        evidence_ids=evidence_ids,
        checks=check_results,
        failed_reasons=checks.fix_hints(failed, formal=True) if failed else [],
        rewrites=rewrites,
        needs_input=needs_input,
        model=model,
        elapsed_ms=elapsed_ms,
        data_origin=store.data_origin,
    )

    return CardResult(
        card_id=card.card_id, kind=card.kind,
        reason_text=reason_text_with_basis,
        basis_label=basis_label,
        drafts=[draft], chosen_measures=chosen_measures or [],
        elapsed_ms=elapsed_ms, won=round(total_won, 4),
    )


def generate_review_promo(ctx, card, key, model="HCX-005", chosen_measures=None, menu=None):
    """review_promo 전략의 글. generate_coupon_promo 와 같은 점검·재시도·템플릿 구조를 쓰지만
    쿠폰 줄이 없고(이 전략은 할인이 없다), 칭찬 리뷰를 인용하지 않고 코드가 센 칭찬 주제
    (예: 양념, _praise_topics)만 넘긴다.

    11/16 (coupon_promo 의 PR #55 방식에 맞춤): 합니다체 기준 힌트(fix_hints(formal=True))와 글에서 실제로 걸린 말
    (promo_detail_hints)로 다시 쓰게 하고, 다시 쓰기 전에 코드로 고칠 수 있는 것(마크다운·3문장·사전 치환(합니다체)·
    어미 보정)을 먼저 해 본다(_check_promo_with_code_fix). 최종 글이 HCX 마지막 글과 다르면 checks.ai_part_repaired.
    후보 하나의 호출이 실패하면 다른 후보를 쓰고, 둘 다 실패하면 코드 템플릿 + CALL_FAILED_NOTE(다시 쓰기 없음).
    다시 쓰기 호출이 실패하면 AI 글을 그대로 둔다(점검 실패로 보임) — coupon_promo 와 같다."""
    store = ctx.store
    tone = ctx.tone
    menu_descriptions = getattr(store, "menu_descriptions", None) or {}
    snapshots = {s.snapshot_id: s for s in ctx.snapshots}
    forbidden_phrases = list(tone.forbidden_phrases) if tone.forbidden_phrases else []

    target_snapshots = [snapshots[sid] for sid in card.snapshot_ids if sid in snapshots]

    needs_input: list[str] = []

    filled_reason = card.reason_text
    basis_label = None
    reason_parts = []
    for snap in target_snapshots:
        basis_label = snap.basis_label
        formatted = _format_snapshot_value(snap)
        if formatted is not None:
            filled_reason = _PLACEHOLDER_PCT.sub(formatted, filled_reason, count=1)
        reason_parts.append(f"({basis_label})")
    reason_text_with_basis = " ".join([filled_reason] + reason_parts)

    if _PLACEHOLDER_PCT.search(reason_text_with_basis):
        needs_input.append("상권 지표 수치 미확정: reason_text에 자리표시자(-X%)가 남아 있어요")

    if menu is None:
        menu = next((m for m in store.menu if m in store.menu_prices), None) or (
            store.menu[0] if store.menu else None
        )
    if not store.menu:
        needs_input.append("menu 없음: 대표 메뉴를 정할 수 없어요")

    menu_section = f"- {menu}" if menu else "(메뉴 정보 없음)"

    topics = _praise_topics(ctx)
    if topics:
        praise_section = "\n## 칭찬 주제 (참고용, 그대로 베끼지 말고 느낌만)\n" + "\n".join(
            f"- {t}" for t in topics
        )
    else:
        praise_section = ""

    system = SYSTEM_TMPL_REVIEW.format(
        store_name=store.name, example=PROMO_EXAMPLE,
        menu_section=menu_section, praise_section=praise_section,
    )

    messages = [{"role": "user", "content": "손님에게 보낼 가게 홍보글 본문을 작성해 주세요."}]

    allowed_numbers = list(store.menu_prices.values())
    review_texts = [r.text for r in ctx.reviews]
    # 대표 메뉴의 재료라 '다른 음식'으로 보지 않을 말 (고기 요리면 '고기') — coupon_promo 와 같다
    allow_food = checks.menu_ingredient_words(menu)
    focus_menu = (menu,) if menu else ()
    other_menus = tuple(store.menu) if menu else ()

    def _run_review_checks(text):
        result = {
            "no_bad_number": not checks.has_number_not_in(text, allowed_numbers),
            "no_personal_info": not checks.personal_info(text),
            "no_broken_ending": checks.no_broken_ending(text),
            "no_coupon_invented": not checks.coupon_invented(text),
            "no_stiff_words": not checks.has_stiff_words(text),
            "no_fewshot_copy": not checks.fewshot_copied(text, store.menu, review_texts),
            "no_bad_promise": not checks.promises_not_in_policy(text, ctx.policies),
            "no_unknown_menu": not checks.mentions_unknown_menu(text, store.menu, allow=allow_food),
            "only_focus_menu": checks.only_coupon_menu_mentioned(text, store.menu, menu),
            "not_quote_review": not checks.quotes_review(text, ctx.reviews),
            "no_customer_quote": not checks.quotes_customer_speech(text),
            "no_markdown": not checks.has_markdown(text),
            "no_exaggeration": not checks.has_exaggeration(text),
            "no_store_circumstance": not checks.store_circumstance_leaked(text),
            "promo_formal": checks.promo_formal(text),
            # 대표 메뉴 이름에 든 재료('계란말이'의 '계란')는 지어낸 것이 아니다. 다른 메뉴 이름은 only_focus_menu 가 잡는다.
            "no_invented_ingredient": not checks.invented_ingredient(text, menu_descriptions, focus_menu, other_menus),
            "no_unverified_claim": not checks.has_unverified_claim(text),
            "length_ok": checks.length_ok(text, 60, 160),
        }
        if forbidden_phrases:
            result["no_forbidden_phrase"] = not checks.forbidden_phrase(text, forbidden_phrases)
        return result

    retry_exempt = ("length_ok",)

    def _check(text_):
        chk_ = _run_review_checks(text_)
        failed_ = [k for k, v in chk_.items() if not v and k not in retry_exempt]
        return chk_, failed_

    def _check_with_code_fix(text_):
        return _check_promo_with_code_fix(text_, _check)

    def _call_candidate(temperature):
        resp = _safe_call(key, system, messages, model=model, max_tokens=512, temperature=temperature)
        raw_ = resp.get("content", "") or ""
        text_ = parsing.extract_body(raw_)
        return text_, raw_, resp.get("won", 0), bool(resp.get("error"))

    start = time.perf_counter()
    total_won = 0.0
    rewrites = 0

    with ThreadPoolExecutor(max_workers=2) as pool:
        candidates = [f.result() for f in [pool.submit(_call_candidate, 0.4) for _ in range(2)]]
    total_won += sum(c[2] for c in candidates)

    scored = []
    for text_, raw_, _, _error in candidates:
        fixed_, chk_, failed_ = _check_with_code_fix(text_)
        scored.append((fixed_, raw_, chk_, failed_, text_))
    scored.sort(key=_candidate_rank, reverse=True)   # 한 후보의 호출이 실패하면(빈 글) 다른 후보를 쓴다
    text, raw, check_results, failed, last_ai_text = scored[0]   # last_ai_text: HCX 가 쓴 글 그대로 (코드 손질 전)

    # 후보 호출이 모두 실패해 AI 글이 없다 → 다시 쓰기 없이 코드 템플릿으로 채우고 사장님께 알린다 (c6.notice·c6.reply 와 같은
    # CALL_FAILED_NOTE). 이 글에는 쿠폰 줄이 없어서 coupon_promo 처럼 빈 글로 두면 보여 줄 것이 없다.
    call_failed = not text and any(c[3] for c in candidates)
    if call_failed:
        text = review_promo_fallback_text(store, menu)
        check_results, failed = _check(text)
        needs_input.append(CALL_FAILED_NOTE)

    rewrite_call_failed = False
    while failed and text and not call_failed and rewrites < _MAX_REWRITES:
        # 합니다체 기준 힌트(formal=True — 기본 힌트의 '편한 구어체로'가 해요체 다시 쓰기를 불렀다) + 글에서 실제로 걸린 말
        hints = checks.fix_hints(failed, formal=True) + checks.promo_detail_hints(
            failed, text, menu_names=store.menu, coupon_menu=menu, review_texts=review_texts, reviews=ctx.reviews,
            allow_food=allow_food, menu_descriptions=menu_descriptions, menu_label="대표 메뉴", coupon_line=False)
        hints.append("지적한 부분만 고치고, 합니다체로 대표 메뉴 하나만 2~3문장으로 소개하는 틀은 그대로 두세요.")
        retry_msg = [
            {"role": "user", "content": "손님에게 보낼 가게 홍보글 본문을 작성해 주세요."},
            {"role": "assistant", "content": text},   # 코드가 손질한 글(보여 줄 글)을 고치게 한다
            {"role": "user", "content": "수정 지시:\n" + "\n".join(f"- {h}" for h in hints)},
        ]
        resp2 = _safe_call(key, system, retry_msg, model=model, max_tokens=512, temperature=0.5)
        total_won += resp2.get("won", 0)
        if resp2.get("error"):     # 다시 쓰기 호출이 끝내 실패 → 더 부르지 않고 AI 글을 그대로 둔다 (점검 실패로 보임)
            rewrite_call_failed = True
            break
        raw = resp2.get("content", "") or ""
        text2 = parsing.extract_body(raw)
        rewrites += 1
        if text2:
            last_ai_text = text2
            text = text2
        text, check_results, failed = _check_with_code_fix(text)

    # 그래도 점검을 못 넘으면 코드 템플릿으로 바꿔 넣는다 (coupon_promo 와 같은 기준 — 다시 쓰기 호출이 실패했으면 덮지 않음)
    used_fallback = bool(failed) and not call_failed and not rewrite_call_failed
    # 최종 글이 HCX 가 마지막으로 쓴 글과 다르면(띄어쓰기 차이는 빼고) 코드가 고친 것 (coupon_promo 와 같은 기준)
    ai_part_repaired = bool(not call_failed and not failed and not _same_text(text, last_ai_text))
    if used_fallback:
        text = review_promo_fallback_text(store, menu)
        check_results, failed = _check(text)
    check_results["used_fallback"] = used_fallback
    check_results["ai_part_repaired"] = ai_part_repaired

    if failed:
        needs_input.append("사장님 확인 필요")

    elapsed_ms = round((time.perf_counter() - start) * 1000)

    evidence_ids = [s.snapshot_id for s in target_snapshots]
    if menu is not None:
        evidence_ids.append(f"review_promo:{menu}")
    if not evidence_ids:
        evidence_ids = list(card.evidence_ids)

    draft = DraftOutput(
        draft_id=f"d_{uuid.uuid4().hex[:8]}",
        card_id=card.card_id,
        store_id=store.store_id,
        generator="review_promo",
        text=text,
        evidence_ids=evidence_ids,
        checks=check_results,
        failed_reasons=checks.fix_hints(failed, formal=True) if failed else [],
        rewrites=rewrites,
        needs_input=needs_input,
        model=model,
        elapsed_ms=elapsed_ms,
        data_origin=store.data_origin,
    )

    return CardResult(
        card_id=card.card_id, kind=card.kind,
        reason_text=reason_text_with_basis,
        basis_label=basis_label,
        drafts=[draft], chosen_measures=chosen_measures or [],
        elapsed_ms=elapsed_ms, won=round(total_won, 4),
    )
