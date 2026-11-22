"""손님 칭찬 리뷰와 메뉴 언급 수. 코드로만 센다 (모델 호출 없음).

쓰는 곳 (같은 기준을 세 곳이 함께 쓴다)
- experiments/marketing/c6/promo.py : 쿠폰 메뉴 고르기
- services/web/web/cards.py         : 카드 ⓑ 의 근거 [F3] (손님 칭찬 리뷰에 언급된 메뉴·건수)
- services/review-insight/app/report.py : 종합 리포트의 '손님 칭찬 요약' (인기 메뉴 TOP 3)

리뷰는 dict 이든 ReviewRecord 같은 객체든 받는다. 읽는 칸: review_id, text, rating, sentiment, negative_topics.
"""
from __future__ import annotations

from typing import Any, Iterable

# 메뉴 이름에 붙는 흔한 말. 이 말만으로는 어느 메뉴인지 알 수 없어 언급으로 세지 않는다 ("정식 맛있어요")
GENERIC_MENU_WORDS = frozenset({"정식", "세트", "덮밥", "백반", "단품", "한상", "추가", "곱빼기", "특", "대", "중", "소"})
MIN_WORD = 3   # 이름을 띄어 쓴 낱말은 3자 이상일 때만 그 메뉴로 본다 ("제육볶음 정식" → "제육볶음")
# 메뉴 이름 앞에 붙는 흔한 꾸밈말. 손님은 떼고 부르는 일이 많다 ('손칼국수'를 '칼국수'로, 11/22 QA R4)
MENU_PREFIXES = ("옛날", "수제", "원조", "매운", "얼큰", "손", "왕", "생", "통", "참", "특")
# 꾸밈말처럼 보여도 낱말의 첫 글자인 것. '참치김밥'을 '치김밥'으로 떼면 '멸치김밥'·'김치김밥' 리뷰까지 세게 된다
NOT_PREFIXED = ("참치", "참외", "생선", "생강", "통영", "특선", "수제비")
MIN_STRIPPED = 2   # 꾸밈말을 뗀 뒤 2자 이상일 때만 ('통닭'을 '닭'으로 떼지 않음)


def _get(review: Any, name: str) -> Any:
    return review.get(name) if isinstance(review, dict) else getattr(review, name, None)


def _flat(text: Any) -> str:
    return "".join(str(text or "").split())


def is_high_rating(review: Any) -> bool:
    rating = _get(review, "rating")
    return isinstance(rating, (int, float)) and rating >= 4


def praise_reviews(reviews: Iterable[Any]) -> list[Any]:
    """칭찬 리뷰. 감정 분류가 '긍정'(sentiment == "positive")인 리뷰가 하나라도 있으면 그것만 쓴다.
    하나도 없으면(분류 전) 별점 4점 이상이면서 불만 주제가 없고 부정·섞임으로 분류되지 않은 리뷰."""
    reviews = list(reviews)
    positive = [r for r in reviews if _get(r, "sentiment") == "positive"]
    if positive:
        return positive
    return [r for r in reviews if is_high_rating(r) and not _get(r, "negative_topics")
            and _get(r, "sentiment") not in ("negative", "mixed")]


def _unprefixed(word: str) -> list[str]:
    """앞의 꾸밈말을 차례로 뗀 이름들 ('얼큰손칼국수' → ['손칼국수', '칼국수']). 남는 글자가 MIN_STRIPPED 자보다 짧아지면 멈춘다."""
    out = []
    while not word.startswith(NOT_PREFIXED):
        head = next((p for p in MENU_PREFIXES if word.startswith(p) and len(word) - len(p) >= MIN_STRIPPED), None)
        if head is None:
            break
        word = word[len(head):]
        out.append(word)
    return out


def menu_variants(menu_names: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """메뉴 이름 → 리뷰에서 그 메뉴로 볼 표기들 (띄어쓰기는 무시).
    전체 이름 + 이름을 띄어 쓴 낱말 중 3자 이상이고, 흔한 말(정식·세트…)이 아니고, 다른 메뉴 이름에 들어 있지 않은 것
    + 위 표기에서 앞의 꾸밈말(손·왕·옛날…)을 뗀 이름 중 2자 이상이고, 흔한 말이 아니고, 다른 메뉴 이름에 들어 있지 않은 것."""
    names = [n for n in dict.fromkeys(menu_names) if _flat(n)]
    found: dict[str, tuple[str, ...]] = {}
    for name in names:
        variants = [_flat(name)]
        others = [_flat(o) for o in names if o != name]
        for word in str(name).split():
            if len(word) < MIN_WORD or word in GENERIC_MENU_WORDS or word in variants:
                continue
            if any(word in other for other in others):   # 두 메뉴가 같이 쓰는 낱말로는 어느 메뉴인지 알 수 없다
                continue
            variants.append(word)
        for base in list(variants):
            for short in _unprefixed(base):
                # '왕만두'에서 뗀 '만두'가 '김치만두'에도 들어 있으면 어느 메뉴인지 알 수 없다
                if short in GENERIC_MENU_WORDS or short in variants or any(short in other for other in others):
                    continue
                variants.append(short)
        found[name] = tuple(variants)
    return found


def menu_mentions(menu_names: Iterable[str], reviews: Iterable[Any]) -> list[dict]:
    """메뉴마다 그 메뉴를 언급한 리뷰 수. 메뉴 순서 그대로, 리뷰 하나는 메뉴마다 한 번만 센다.
    돌려주는 값: [{"menu", "count", "review_ids"}]"""
    variants = menu_variants(menu_names)
    rows = [{"menu": name, "count": 0, "review_ids": []} for name in variants]
    for review in reviews:
        text = _flat(_get(review, "text"))
        if not text:
            continue
        for row in rows:
            if any(v in text for v in variants[row["menu"]]):
                row["count"] += 1
                row["review_ids"].append(_get(review, "review_id"))
    return rows


def top_praised_menus(menu_names: Iterable[str], reviews: Iterable[Any], limit: int = 3) -> list[dict]:
    """칭찬 리뷰에서 많이 언급된 메뉴. 많은 순, 같으면 메뉴판 순서. 언급이 없는 메뉴는 뺀다."""
    rows = [r for r in menu_mentions(menu_names, praise_reviews(reviews)) if r["count"] > 0]
    rows.sort(key=lambda r: -r["count"])   # 안정 정렬이라 같은 수는 메뉴판 순서가 남는다
    return rows[:limit]


def pick_praised_menu(menu_names: Iterable[str], reviews: Iterable[Any],
                      priced: Iterable[str] | None = None) -> dict | None:
    """쿠폰에 쓸 메뉴 하나. 가격이 있는 메뉴(priced) 가운데 칭찬 리뷰에 가장 많이 언급된 것.
    같은 수면 메뉴판 순서가 앞선 것, 언급이 하나도 없으면 가격 있는 첫 메뉴(count 0). 가격 있는 메뉴가 없으면 None.

    돌려주는 값: {"menu", "count", "review_ids", "praise_total"(칭찬 리뷰 수), "tied"(같은 수의 다른 메뉴가 있음)}
    priced 를 주지 않으면 모든 메뉴를 가격 있는 메뉴로 본다."""
    names = list(dict.fromkeys(menu_names))
    allowed = set(names if priced is None else priced)
    praise = praise_reviews(reviews)
    rows = [r for r in menu_mentions(names, praise) if r["menu"] in allowed]
    if not rows:
        return None
    best = max(rows, key=lambda r: r["count"])   # max 는 같은 값이면 앞선 것을 고른다 = 메뉴판 순서
    tied = best["count"] > 0 and sum(1 for r in rows if r["count"] == best["count"]) > 1
    return {**best, "praise_total": len(praise), "tied": tied}
