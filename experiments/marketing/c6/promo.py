"""쿠폰 홍보글 생성기 — promo 카드의 상권 지표 기반 홍보.

AI 는 본문만 쓴다. 쿠폰 값(메뉴·할인 금액·유효기간·시간대 조건)은 숫자이므로 코드가 글 끝에 한 줄로
붙이고, 근거(snapshot_id · coupon:메뉴)도 코드가 정한다 — AI 가 준 근거 문자열은 쓰지 않는다.
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
from c6.output import DraftOutput, CardResult
from common.korean import display_name, eul

_MAX_REWRITES = 2  # 답글·공지와 같은 한도 — 이만큼 다시 써도 점검을 못 넘으면 코드 템플릿으로 바꿔 넣는다

# 쿠폰 생성기 전용 few-shot 예시 (reply 스타일 예시는 어투가 달라 안 맞는다)
# 메뉴·리뷰와 무관한 문장으로 둔다 — AI 가 이 예시의 말투만 배우고, 메뉴·수식어는 그대로 베끼지 않도록.
PROMO_EXAMPLE = (
    "요즘 저녁 메뉴가 고민되실 때, 손님들이 '양이 넉넉하다'고 해 주신 메뉴를 "
    "오늘도 든든하게 준비하고 있습니다."
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
   따옴표로 손님 말을 그대로 옮기거나 "손님들께서 ...라고 해 주셨다" 처럼 쓰지 말 것
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


def _praise_reviews(ctx, n=2):
    """칭찬할 만한 리뷰. sentiment=='positive' 우선, 없으면 평점 4 이상인 것만(없는 복합을 칭찬으로 꾸미지 않는다)."""
    positive = [r for r in ctx.reviews if r.sentiment == "positive"]
    if not positive:
        positive = [r for r in ctx.reviews if (r.rating or 0) >= 4]
        positive.sort(key=lambda r: (r.rating or 0), reverse=True)
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

_REVIEW_PROMO_FALLBACK_NO_DESC = "정성껏 만들어 따뜻하게 보내드립니다."
_REVIEW_PROMO_FALLBACK_TMPL = (
    "{store}에서 {item}{item_eul} 정성껏 준비하고 있습니다. "
    "{desc} "
    "앞으로도 좋은 모습으로 찾아뵙겠습니다."
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
        coupon_menu = next((m for m in store.menu if m in store.menu_prices), None)
    if not store.menu_prices or coupon_menu is None:
        needs_input.append("menu_prices 없음: 쿠폰 메뉴·금액을 정할 수 없어요")

    menu_section = f"- {coupon_menu}" if coupon_menu else "(메뉴 정보 없음)"

    praise = _praise_reviews(ctx)
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

    def _run_promo_checks(text):
        result = {
            "no_bad_number": not checks.has_number_not_in(text, allowed_numbers),
            "no_personal_info": not checks.personal_info(text),
            "no_broken_ending": checks.no_broken_ending(text),
            "no_coupon_invented": not checks.coupon_invented(text),
            "no_stiff_words": not checks.has_stiff_words(text),
            "no_fewshot_copy": not checks.fewshot_copied(text, store.menu, review_texts),
            "no_bad_promise": not checks.promises_not_in_policy(text, ctx.policies),
            "no_unknown_menu": not checks.mentions_unknown_menu(text, store.menu),
            "only_coupon_menu": checks.only_coupon_menu_mentioned(text, store.menu, coupon_menu),
            "not_quote_review": not checks.quotes_review(text, ctx.reviews),
            "no_customer_quote": not checks.quotes_customer_speech(text),
            "no_markdown": not checks.has_markdown(text),
            "no_exaggeration": not checks.has_exaggeration(text),
            "no_store_circumstance": not checks.store_circumstance_leaked(text),
            "promo_formal": checks.promo_formal(text),
            "no_invented_ingredient": not checks.invented_ingredient(text, menu_descriptions),
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

    def _score(item):
        return sum(1 for v in item[2].values() if v)

    def _call_candidate(temperature):
        resp = clova.call(key, system, messages, model=model, max_tokens=512, temperature=temperature)
        raw_ = resp.get("content", "")
        text_ = parsing.extract_body(raw_)  # JSON이든 평문이든 본문을 절대 버리지 않는다
        return text_, raw_, resp.get("won", 0)

    start = time.perf_counter()
    total_won = 0.0
    rewrites = 0

    # 후보 2개를 동시에 생성해 점검 통과 수가 많은 쪽을 쓴다
    with ThreadPoolExecutor(max_workers=2) as pool:
        candidates = [f.result() for f in [pool.submit(_call_candidate, 0.4) for _ in range(2)]]
    total_won += sum(c[2] for c in candidates)

    scored = []
    for text_, raw_, _ in candidates:
        chk_, failed_ = _check(text_)
        scored.append((text_, raw_, chk_, failed_))
    scored.sort(key=_score, reverse=True)
    text, raw, check_results, failed = scored[0]

    while failed and text and rewrites < _MAX_REWRITES:
        hints = checks.fix_hints(failed)
        retry_msg = [
            {"role": "user", "content": "손님에게 보낼 쿠폰 홍보글 본문을 작성해 주세요."},
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "수정 지시:\n" + "\n".join(f"- {h}" for h in hints)},
        ]
        resp2 = clova.call(key, system, retry_msg, model=model, max_tokens=512, temperature=0.5)
        total_won += resp2.get("won", 0)
        raw = resp2.get("content", "")
        text2 = parsing.extract_body(raw)
        rewrites += 1
        if text2:
            text = text2
        check_results, failed = _check(text)

    if not check_results.get("no_stiff_words", True):
        text = checks.fix_stiff_words(text)
        check_results, failed = _check(text)

    # 마크다운 기호 제거·3문장까지만 자르기는 결과와 무관하게 코드가 항상 적용한다
    text = checks.strip_markdown(text)
    text = checks.truncate_sentences(text, 3)
    check_results, failed = _check(text)

    # 그래도(총 1 + _MAX_REWRITES 번 시도) 점검을 못 넘으면 코드 템플릿으로 바꿔 넣고 통과 처리한다
    # (c6.reply·c6.notice 의 used_fallback 과 같은 방식). needs_input 에는 남기지 않는다 — 대체
    # 문장은 늘 점검을 통과하므로 사람이 볼 필요가 없다.
    used_fallback = bool(failed)
    if used_fallback:
        text = _fallback_text(store, coupon_menu)
        check_results, failed = _check(text)
    check_results["used_fallback"] = used_fallback

    if failed:
        needs_input.append("사장님 확인 필요")

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
        failed_reasons=checks.fix_hints(failed) if failed else [],
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
    (예: 양념, _praise_topics)만 넘긴다."""
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

    def _run_review_checks(text):
        result = {
            "no_bad_number": not checks.has_number_not_in(text, allowed_numbers),
            "no_personal_info": not checks.personal_info(text),
            "no_broken_ending": checks.no_broken_ending(text),
            "no_coupon_invented": not checks.coupon_invented(text),
            "no_stiff_words": not checks.has_stiff_words(text),
            "no_fewshot_copy": not checks.fewshot_copied(text, store.menu, review_texts),
            "no_bad_promise": not checks.promises_not_in_policy(text, ctx.policies),
            "no_unknown_menu": not checks.mentions_unknown_menu(text, store.menu),
            "only_focus_menu": checks.only_coupon_menu_mentioned(text, store.menu, menu),
            "not_quote_review": not checks.quotes_review(text, ctx.reviews),
            "no_customer_quote": not checks.quotes_customer_speech(text),
            "no_markdown": not checks.has_markdown(text),
            "no_exaggeration": not checks.has_exaggeration(text),
            "no_store_circumstance": not checks.store_circumstance_leaked(text),
            "promo_formal": checks.promo_formal(text),
            "no_invented_ingredient": not checks.invented_ingredient(text, menu_descriptions),
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

    def _score(item):
        return sum(1 for v in item[2].values() if v)

    def _call_candidate(temperature):
        resp = clova.call(key, system, messages, model=model, max_tokens=512, temperature=temperature)
        raw_ = resp.get("content", "")
        text_ = parsing.extract_body(raw_)
        return text_, raw_, resp.get("won", 0)

    start = time.perf_counter()
    total_won = 0.0
    rewrites = 0

    with ThreadPoolExecutor(max_workers=2) as pool:
        candidates = [f.result() for f in [pool.submit(_call_candidate, 0.4) for _ in range(2)]]
    total_won += sum(c[2] for c in candidates)

    scored = []
    for text_, raw_, _ in candidates:
        chk_, failed_ = _check(text_)
        scored.append((text_, raw_, chk_, failed_))
    scored.sort(key=_score, reverse=True)
    text, raw, check_results, failed = scored[0]

    while failed and text and rewrites < _MAX_REWRITES:
        hints = checks.fix_hints(failed)
        retry_msg = [
            {"role": "user", "content": "손님에게 보낼 가게 홍보글 본문을 작성해 주세요."},
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "수정 지시:\n" + "\n".join(f"- {h}" for h in hints)},
        ]
        resp2 = clova.call(key, system, retry_msg, model=model, max_tokens=512, temperature=0.5)
        total_won += resp2.get("won", 0)
        raw = resp2.get("content", "")
        text2 = parsing.extract_body(raw)
        rewrites += 1
        if text2:
            text = text2
        check_results, failed = _check(text)

    if not check_results.get("no_stiff_words", True):
        text = checks.fix_stiff_words(text)
        check_results, failed = _check(text)

    text = checks.strip_markdown(text)
    text = checks.truncate_sentences(text, 3)
    check_results, failed = _check(text)

    used_fallback = bool(failed)
    if used_fallback:
        text = review_promo_fallback_text(store, menu)
        check_results, failed = _check(text)
    check_results["used_fallback"] = used_fallback

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
        failed_reasons=checks.fix_hints(failed) if failed else [],
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
