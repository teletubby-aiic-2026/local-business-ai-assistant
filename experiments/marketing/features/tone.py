"""
S1 사장님 말투 (build_tone_profile + generate_post) v4 기능 부분

v4: 홍보의 주인공을 '행사'에서 '가게'로 바꿈
   - 행사 정보(날짜·장소·거리)는 사장님이 홍보할지 판단하는 정보 → 글에 넣지 않고 사장님 카드로 따로 보여 줌
   - 글 구조: ① 행사 한 줄 (손님 상황으로 가볍게 언급)
             ② 가게 홍보 1~2문장 (칭찬 리뷰 내용으로, "저희 ○○는 ~")
             ③ 고정 마무리 + 해시태그 (코드)
   - 점검 추가: 행사는 첫 문장에서만 언급, 가게 이름(또는 '저희') 등장, 리뷰 표현 사용
   - 기본(말투 없음)도 같은 구조로 써서, 말투 정보 유무만 비교되게 함

v3.1 (v3 실행 결과 반영)
   - 높임 점검을 AI가 쓴 문장에만 따로 적용 (코드가 붙인 '…열립니다', '감사합니다'에 묻혀 숯불집 '어때요?'가 통과했던 문제)
   - 메뉴 이름은 핵심 단어만 맞으면 통과 ('돼지 목살' → '목살이랑 된장찌개'도 통과)
   - AI가 JSON 형식을 어겨도 후보 문장을 최대한 건져 냄 (떡볶이 연구소 마켓이 3번 모두 형식 오류로 결과 없음)

v2 결과: 점검은 6/6 통과했지만 직접 읽어 보니 어색함
   - 메뉴를 모르고 지어냄 ("국물떡볶이에 소주한잔", "디저트도 많으니")
   - 근거 없는 자랑 ("소금에만 찍어 먹어도 최고", "어디서도 못 먹어본 맛")
   - 메뉴 이름 반복, "잡숴봐" 같은 어색한 표현
   원인: AI에게 메뉴 이름 하나만 주고 쓸 내용(재료)을 주지 않음
v3: 내용은 손님 칭찬 리뷰에서, 말투는 사장님 글에서
   - [칭찬 리뷰]를 재료로 주고, 리뷰에 나온 내용만 근거로 쓰게 함
   - 지어내기 점검 추가: 메뉴·리뷰·예전 글에 없는 음식/술, 과장 표현, 메뉴 이름 반복, 어색한 표현
   - 1~2문장, temperature 0.5 → 0.3
   - 후보 2개 (리뷰 표현을 살린 것 / 행사와 연결한 것) → 사장님이 고름

v1 결과: 말투 구분 2/6 → 5/6으로 효과는 있었지만, 말투를 살리려다 사실(날짜·거리·메뉴)을 빼먹음 (사실 유지 3/6)
v2: 글을 세 조각으로 나눈다
   ① AI: 가게를 권하는 말 1~3문장만 사장님 말투로 (날짜·장소·거리·숫자는 안 씀)
   ② 코드: 사실 줄 (날짜·장소·행사 이름·도보 시간) — 사장님 스타일(이모지 유무, 높임)에 맞춘 형식
   ③ 코드: 고정 마무리 인사 + 고정 해시태그

흐름
1. 말투 프로필: 사장님이 예전에 쓴 글 3개에서 '측정할 수 있는 것'은 코드가 계산
   (높임 방식, 문장 길이, 이모지·느낌표 습관, 항상 쓰는 마무리 인사, 고정 해시태그)
2. 초안: 행사 정보로 사실만 담은 초안을 코드가 템플릿으로 만든다 (S2 결과 활용)
3. 말투 입히기: AI가 초안을 사장님 말투로 다시 쓴다. 사실(행사·날짜·거리·메뉴)은 그대로
4. 점검: 사실이 그대로인지 + 말투가 프로필과 맞는지 코드로 확인, 걸리면 다시 쓰기
5. 비교: 같은 초안을 '말투 정보 없이' 다듬은 결과(기본)와 비교
   → 결과 글만 보고 어느 가게 글인지 코드가 맞힐 수 있는지(말투 구분 정확도)
"""

import math
import re
from collections import Counter

import clova
from common import korean as K

MODEL = "HCX-005"
MAX_RETRY = 2

EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
TAG = re.compile(r"#\S+")


# ── 말투 측정 (코드) ──────────────────────────────────────────
def sentences(text):
    t = TAG.sub(" ", text)
    t = EMOJI.sub("\n", t.replace("️", ""))
    parts = re.split(r"[.!?~\n]+|(?<=[ㅋㅎ])\s+", t)
    return [p.strip(" ㅋㅎ,") for p in parts if len(p.strip(" ㅋㅎ,")) >= 2]


def ending(sent):
    s = re.sub(r"[ㅋㅎ\s]+$", "", sent)
    if re.search(r"(습니다|ㅂ니다|니다|십시오|시오)$", s):
        return "합니다체"
    if re.search(r"(요|용|죠|세요|에요|예요)$", s):
        return "해요체"
    if re.search(r"(다|음|임|됨|함|지|야|어|아|네|남|완료|끝)$", s):
        return "반말체"
    return "기타"


def measure(text):
    sents = sentences(text)
    ends = Counter(ending(s) for s in sents)
    n = max(len(sents), 1)
    return {
        "문장 수": len(sents),
        "높임": max(("합니다체", "해요체", "반말체"), key=lambda k: ends.get(k, 0)) if sents else "기타",
        "높임 비율": {k: round(ends.get(k, 0) / n, 2) for k in ("합니다체", "해요체", "반말체")},
        "평균 문장 길이": round(sum(len(s) for s in sents) / n, 1),
        "이모지 수": len(EMOJI.findall(text)),
        "느낌표 비율": round(text.count("!") / n, 2),
        "해시태그": TAG.findall(text),
        "ㅋㅎ": bool(re.search(r"[ㅋㅎ]{2,}", text)),
    }


def last_sentence(text):
    t = TAG.sub("", text).strip()
    m = re.split(r"(?<=[.!?])\s+|(?<=[ㅋㅎ])\s+", t)
    return m[-1].strip() if m else ""


def build_profile(store):
    posts = store["예전 글"]
    ms = [measure(p) for p in posts]
    high = Counter(m["높임"] for m in ms).most_common(1)[0][0]
    tags = Counter(t for m in ms for t in m["해시태그"])
    closings = Counter(last_sentence(p) for p in posts)
    closing, cnt = closings.most_common(1)[0]
    closing = closing if cnt >= 2 else None
    # 이모지 습관은 고정 마무리·해시태그를 뺀 본문에서만 센다 (마무리에만 이모지를 쓰는 사장님도 있음)
    bodies = [TAG.sub("", p).replace(closing, "") if closing else TAG.sub("", p) for p in posts]
    emoji_body = Counter(e for b in bodies for e in EMOJI.findall(b))
    return {
        "높임": high,
        "평균 문장 길이": round(sum(m["평균 문장 길이"] for m in ms) / len(ms), 1),
        "이모지 사용": sum(1 for b in bodies if EMOJI.search(b)) * 2 >= len(bodies),
        "자주 쓰는 이모지": [e for e, _ in emoji_body.most_common(3)],
        "느낌표 비율": round(sum(m["느낌표 비율"] for m in ms) / len(ms), 2),
        "ㅋㅎ 사용": sum(m["ㅋㅎ"] for m in ms) >= 2,
        "고정 해시태그": [t for t, c in tags.items() if c >= 2],
        "고정 마무리": closing,
    }


def profile_text(p):
    lines = [
        f"- 높임: {p['높임']}로 쓴다",
        f"- 문장 길이: 한 문장 평균 {p['평균 문장 길이']:.0f}자 정도",
        f"- 이모지(본문): " + (f"자주 쓴다 ({' '.join(p['자주 쓰는 이모지'])})" if p["이모지 사용"] else "쓰지 않는다 (마무리 인사에만 있으면 그건 따로 붙음)"),
        f"- 느낌표: " + ("자주 쓴다" if p["느낌표 비율"] >= 0.3 else "거의 쓰지 않는다"),
        f"- 'ㅋㅋ', 'ㅎㅎ': " + ("쓴다" if p["ㅋㅎ 사용"] else "쓰지 않는다"),
    ]
    if p["고정 마무리"]:
        lines.append(f"- 마지막 문장은 항상 '{p['고정 마무리']}'")
    if p["고정 해시태그"]:
        lines.append(f"- 글 맨 끝에 항상 {' '.join(p['고정 해시태그'])}")
    if p.get("쓰지 않는 표현"):
        lines.append(f"- 쓰지 않는 표현: {', '.join(p['쓰지 않는 표현'])}")
    if p.get("자주 쓰는 표현"):
        lines.append(f"- 자주 쓰는 표현: {', '.join(p['자주 쓰는 표현'])}")
    if p.get("선호 길이"):
        lines.append(f"- 선호 길이: {p['선호 길이']}")
    return "\n".join(lines)


def style_vec(text):
    m = measure(text)
    r = m["높임 비율"]
    return [r["합니다체"], r["해요체"], r["반말체"],
            min(m["이모지 수"] / max(m["문장 수"], 1), 1.0),
            min(m["평균 문장 길이"] / 40, 1.0),
            min(m["느낌표 비율"], 1.0),
            1.0 if m["ㅋㅎ"] else 0.0]


def nearest_store(text, stores):
    """text의 말투 측정값이 어느 가게의 예전 글과 가장 가까운지 (말투 구분 정확도 측정용)."""
    v = style_vec(text)
    best, bd = None, 9e9
    for s in stores:
        pv = [sum(x) / len(s["예전 글"]) for x in zip(*[style_vec(p) for p in s["예전 글"]])]
        d = math.dist(v, pv)
        if d < bd:
            best, bd = s["이름"], d
    return best


# ── 사장님용 행사 카드 (글에는 넣지 않음) ─────────────────────
def owner_card(ev):
    """사장님이 이 행사로 홍보할지 판단하는 정보. 손님에게 올라가는 글에는 들어가지 않는다."""
    return (f"근처 행사: {ev['이름']} · {ev['장소']} · {ev['날짜']} · 가게에서 도보 약 {ev['도보']}분\n"
            f"손님 상황: {ev['상황']}")


def draft(store, ev):
    """기본(말투 없음)과 비교할 때 쓰는 재료 요약."""
    return f"{ev['종류']} {ev['상황']} 들르기 좋은 {store['이름']} · 메뉴 {store['메뉴'][0]}"


# ── 조립 (코드) ──────────────────────────────────────────────
def assemble(cand, p, add_tail=True):
    """AI가 쓴 행사 한 줄 + 가게 홍보(마무리 인사까지)를 한 문단으로 잇고, 해시태그만 코드가 붙인다.
    AI가 마무리 인사를 빠뜨렸을 때만 코드가 뒤에 붙인다."""
    hook = str(cand.get("행사_한줄", "")).strip()
    promo = str(cand.get("가게_홍보", "")).strip()
    body = TAG.sub("", f"{hook} {promo}").strip()
    if add_tail and p["고정 마무리"] and K.nospace(p["고정 마무리"]) not in K.nospace(body):
        body = f"{body} {p['고정 마무리']}"
    tags = " ".join(p["고정 해시태그"]) if add_tail else ""
    return body + (f"\n{tags}" if tags else ""), hook, promo


# ── 지어내기·구성 점검 (코드) ─────────────────────────────────
FOOD_WORDS = ["소주", "맥주", "막걸리", "와인", "술", "디저트", "케이크", "쿠키", "빵", "샌드위치",
              "커피", "라떼", "음료", "주스", "떡볶이", "김밥", "라면", "튀김", "어묵", "순대", "고기",
              "삼겹살", "갈비", "목살", "찌개", "냉면", "밥", "국수", "치킨", "피자"]
HYPE = r"최고|어디서도|어디에서도|인생|역대급|단골 ?되|무조건|끝판왕|미쳤|찐이|짱|진리|일품"
AWKWARD = r"잡숴|잡수|드시러들|하시라"
EVENT_WORDS = r"연극|공연|관람|마켓|행사|축제|전시|콘서트|구경"
STOP = {"정말", "진짜", "너무", "많이", "좋아요", "좋았어요", "있어요", "먹었어요", "같이", "하고", "와요"}


def menu_core(store):
    """'돼지 목살' → '목살'. 줄여 써도 통과시키기 위해."""
    return K.nospace(store["메뉴"][0].split()[-1])


def review_words(store):
    words = set()
    for r in store.get("칭찬 리뷰", []):
        for w in re.findall(r"[가-힣]{2,}", r):
            w = re.sub(r"(이|가|은|는|을|를|에|도|랑|하고|해서|하니|해요|어요|아요|이에요|예요|게|고)$", "", w)
            if len(w) >= 2 and w not in STOP and K.nospace(w) not in menu_core(store):
                words.add(w)
    return words


def allowed_text(store):
    return " ".join([store["이름"], " ".join(store["메뉴"]), " ".join(store["예전 글"]),
                     " ".join(store.get("칭찬 리뷰", []))])


def check_post(hook, promo, store, ev, closing=None, profile=None):
    c = {}
    if closing:
        promo = promo.replace(closing, "").strip()
    both = f"{hook} {promo}"
    nb, np_ = K.nospace(both), K.nospace(promo)
    menu = menu_core(store)
    c["행사 한 줄 있음"] = bool(re.search(EVENT_WORDS, hook)) or K.nospace(ev["핵심어"]) in K.nospace(hook)
    c["행사는 첫 줄에서만 언급"] = not re.search(EVENT_WORDS, promo)
    c["가게가 주인공 (가게 이름·'저희')"] = bool(re.search(r"저희|우리 ?(가게|집|카페)", promo)) or \
        K.nospace(store["이름"]) in np_ or store["이름"].split()[-1] in promo
    c["메뉴 이름 포함 (1번)"] = menu in np_ and nb.count(menu) <= 2
    c["칭찬 리뷰 표현 사용"] = any(w in promo for w in review_words(store))
    c["날짜·장소·거리·숫자 없음"] = not re.search(r"\d|월\s*\d|도보|분 거리", both) and \
        K.nospace(ev["장소"]) not in nb
    c["혜택·협력 표현 없음"] = not re.search(r"할인|증정|쿠폰|초대|함께합니다|공식|제휴", both)
    allowed = K.nospace(allowed_text(store))
    c["없는 음식·술 안 만듦"] = not [w for w in FOOD_WORDS if w in nb and w not in allowed]
    c["과장 표현 없음"] = not re.search(HYPE, both)
    c["어색한 표현 없음"] = not re.search(AWKWARD, both)
    c["사장님 시점 (손님 시점 아님)"] = not re.search(r"들렀어요|들렀다|왔어요|다녀왔|먹고 왔|사장님이|사장님께서|사장님의", both)
    banned = (profile or {}).get("쓰지 않는 표현", [])
    if banned:
        found = [w for w in banned if w in both]
        c["사장님이 지운 표현 없음"] = not found
    return c


def check_tone(text, ai_text, p):
    m, am = measure(text), measure(ai_text)
    c = {"AI 문장 높임 일치": am["문장 수"] == 0 or am["높임"] == p["높임"]}
    c["이모지 습관 일치"] = (am["이모지 수"] > 0) == p["이모지 사용"]
    c["ㅋㅎ 습관 일치"] = am["ㅋㅎ"] == p["ㅋㅎ 사용"]
    c["문장 길이 비슷 (0.5~2.2배)"] = 0.5 * p["평균 문장 길이"] <= am["평균 문장 길이"] <= 2.2 * p["평균 문장 길이"]
    if p["고정 마무리"]:
        c["고정 마무리 포함"] = K.nospace(p["고정 마무리"]) in K.nospace(text)
    if p["고정 해시태그"]:
        c["고정 해시태그 포함"] = all(tg in text for tg in p["고정 해시태그"])
    return c


HINT = {
    "행사 한 줄 있음": "첫 문장(행사_한줄)에서 근처 {kind}를 손님 상황({sit})으로 가볍게 언급해 주세요.",
    "행사는 첫 줄에서만 언급": "가게_홍보에서는 행사 얘기를 빼고 가게 얘기만 해 주세요.",
    "가게가 주인공 (가게 이름·'저희')": "가게_홍보는 '저희 {store}는'처럼 가게를 주어로 써 주세요.",
    "메뉴 이름 포함 (1번)": "가게_홍보에 메뉴 이름 '{menu}'를 한 번 넣어 주세요.",
    "칭찬 리뷰 표현 사용": "가게_홍보에 [칭찬 리뷰]에 나온 표현을 하나 이상 살려 주세요.",
    "날짜·장소·거리·숫자 없음": "날짜·장소·거리·숫자는 빼 주세요.",
    "혜택·협력 표현 없음": "할인이나 행사와 함께하는 듯한 표현은 빼 주세요.",
    "없는 음식·술 안 만듦": "메뉴와 칭찬 리뷰에 없는 음식이나 술은 빼 주세요.",
    "과장 표현 없음": "'최고', '어디서도 못' 같은 과장은 빼고 리뷰에 나온 표현으로 써 주세요.",
    "어색한 표현 없음": "'잡숴' 같은 어색한 말은 사장님 글에 나오는 말투로 바꿔 주세요.",
    "사장님 시점 (손님 시점 아님)": "손님 후기처럼('들렀어요') 쓰거나 사장님을 3인칭('사장님이')으로 쓰지 말고, 사장님이 직접 권하는 말('제가 구워 드려요')로 써 주세요.",
    "AI 문장 높임 일치": "문장 끝을 사장님 글처럼 {h}로 맞춰 주세요.",
    "이모지 습관 일치": "이모지는 사장님 글처럼 {e}.",
    "ㅋㅎ 습관 일치": "'ㅋㅋ', 'ㅎㅎ'는 사장님 글처럼 {k}.",
    "문장 길이 비슷 (0.5~2.2배)": "문장 길이를 사장님 글처럼 한 문장 {l:.0f}자 정도로 맞춰 주세요.",
    "마무리 인사를 AI가 이어서 씀": "가게_홍보 마지막에 [마무리 인사]를 앞 문장과 이어지게 글자 그대로 넣어 주세요.",
    "후보 형식": '{{"후보": [{{"행사_한줄": "...", "가게_홍보": "..."}}, ...]}} 형식으로 써 주세요.',
    "사장님이 지운 표현 없음": "사장님이 쓰지 않기로 한 표현({banned})은 빼 주세요.",
}


def hint(k, p, store=None, ev=None):
    return HINT.get(k, k).format(
        h=p["높임"], e="넣어 주세요" if p["이모지 사용"] else "빼 주세요", l=p["평균 문장 길이"],
        k="넣어 주세요" if p["ㅋㅎ 사용"] else "빼 주세요",
        kind=(ev or {}).get("종류", "행사"), sit=(ev or {}).get("상황", ""),
        store=(store or {}).get("이름", ""), menu=(store or {}).get("메뉴", [""])[0],
        banned=", ".join(p.get("쓰지 않는 표현", [])))


# 지키면 좋지만, 어겼다고 글을 버릴 정도는 아닌 점검 (참고로만 표시)
#  - 문장 길이: 사장님 글이 아주 짧으면(숯불집 평균 9자) 맞추기가 거의 불가능
#  - 마무리 인사: AI가 빠뜨려도 코드가 붙인다
#  - 이모지: 한두 개 차이로 글을 버리지 않는다
SOFT = {"문장 길이 비슷 (0.5~2.2배)", "마무리 인사를 AI가 이어서 씀", "이모지 습관 일치"}


# ── 모델 ─────────────────────────────────────────────────────
RULES = """글은 두 부분으로 쓴다.
- 행사_한줄: 근처 행사를 [손님 상황]으로 가볍게 꺼내는 한 문장. 예) "연극 보러 가시기 전에 커피 한 잔 어때요?"
  행사 이름·날짜·장소·거리는 쓰지 않는다. 행사 종류(연극, 마켓 등)만 말한다.
- 가게_홍보: 가게가 주인공인 1~2문장. "저희 ○○는 ~" 처럼 가게를 주어로,
  [칭찬 리뷰]에 나온 손님 표현으로 [메뉴]를 소개한다. 행사 얘기는 다시 하지 않는다.

지킬 것:
1. 음식 얘기는 [칭찬 리뷰]에 나온 것만. 리뷰에 없는 맛·재료·메뉴·술은 쓰지 않는다.
2. "최고", "어디서도 못", "인생", "역대급", "단골 되실" 같은 과장은 쓰지 않는다.
3. 숫자, 날짜, 장소, 거리, 가격, 할인은 쓰지 않는다.
4. 해시태그는 쓰지 않는다. [마무리 인사]가 주어지면 가게_홍보 마지막에 앞 문장과 자연스럽게 이어지도록 글자 그대로 넣는다.
5. 가게가 행사와 함께하는 것처럼 쓰지 않는다."""

SYS_TONE = """너는 동네 가게 사장님 대신 홍보 글을 쓰는 도우미다.
[사장님이 예전에 쓴 글]의 높임 방식, 문장 길이, 이모지·느낌표·ㅋㅋ 습관을 그대로 따라 쓴다.
사장님 글에 없는 말버릇은 만들지 않는다.

""" + RULES + """

후보 2개를 쓴다. 두 후보는 서로 다른 칭찬 리뷰 표현을 쓴다.
아래 JSON으로만 답한다.
{"후보": [{"행사_한줄": "...", "가게_홍보": "..."}, {"행사_한줄": "...", "가게_홍보": "..."}]}"""

SYS_BASE = """너는 동네 가게 홍보 글을 쓰는 도우미다.

""" + RULES + """

후보 1개를 쓴다. 아래 JSON으로만 답한다.
{"후보": [{"행사_한줄": "...", "가게_홍보": "..."}]}"""


def parse_candidates(raw):
    js = clova.parse_json(raw) or {}
    got = js.get("후보") if isinstance(js, dict) else None
    out = []
    for x in got or []:
        if isinstance(x, dict) and (x.get("행사_한줄") or x.get("가게_홍보")):
            out.append({"행사_한줄": str(x.get("행사_한줄", "")), "가게_홍보": str(x.get("가게_홍보", ""))})
    if not out:  # JSON이 깨졌으면 "행사_한줄": "...", "가게_홍보": "..." 쌍을 직접 찾는다
        hooks = re.findall(r'행사_한줄"?\s*[:：]\s*"([^"]+)"', raw)
        promos = re.findall(r'가게_홍보"?\s*[:：]\s*"([^"]+)"', raw)
        out = [{"행사_한줄": h, "가게_홍보": pr} for h, pr in zip(hooks, promos)]
    return out[:2]


def user_prompt(store, ev, p, with_tone):
    parts = []
    if with_tone:
        parts += [f"[사장님 말투 특징]\n{profile_text(p)}",
                  "[사장님이 예전에 쓴 글]\n" + "\n".join(f"- {x}" for x in store["예전 글"])]
        if p["고정 마무리"]:
            parts.append(f"[마무리 인사]\n{p['고정 마무리']}")
    parts += [f"[가게]\n{store['이름']} ({store['업종']})",
              "[칭찬 리뷰]\n" + "\n".join(f"- {x}" for x in store.get("칭찬 리뷰", [])),
              f"[메뉴]\n{store['메뉴'][0]}",
              f"[근처 행사 종류]\n{ev['종류']}",
              f"[손님 상황]\n{ev['상황']}"]
    return "\n\n".join(parts)


def generate(store, ev, p, with_tone, key, stores=None):
    system = SYS_TONE if with_tone else SYS_BASE
    need = 2 if with_tone else 1
    msgs = [{"role": "user", "content": user_prompt(store, ev, p, with_tone)}]
    tries, cost = [], {"tokens": 0, "seconds": 0, "won": 0}
    for _ in range(MAX_RETRY + 1 if with_tone else 1):
        r = clova.call(key, system, msgs, model=MODEL, temperature=0.3 if with_tone else 0.5, max_tokens=512)
        if "error" in r:
            return {"오류": r["error"]}
        for k in cost:
            cost[k] = round(cost[k] + r[k], 2)
        raw = r["content"].strip()
        cands = []
        for cand in parse_candidates(raw):
            text, hook, promo = assemble(cand, p, add_tail=with_tone)  # 기본은 사장님 마무리·해시태그도 모름
            ch = check_post(hook, promo, store, ev, p["고정 마무리"] if with_tone else None, profile=p)
            if with_tone and p["고정 마무리"]:
                ch["마무리 인사를 AI가 이어서 씀"] = K.nospace(p["고정 마무리"]) in K.nospace(promo)
            if with_tone:
                ch.update(check_tone(text, f"{hook} {promo}", p))
            cands.append({"행사_한줄": hook, "가게_홍보": promo, "글": text, "점검": ch,
                          "실패": [k for k, v in ch.items() if not v and k not in SOFT],
                          "참고": [k for k, v in ch.items() if not v and k in SOFT]})
        failed = [] if len(cands) >= need else ["후보 형식"]
        for i, c in enumerate(cands, 1):
            failed += [f"후보 {i}: {k}" for k in c["실패"]]
        tries.append({"원문": raw, "후보": cands, "실패": failed})
        if not failed:
            break
        fb = "아래를 고쳐서 같은 JSON 형식으로 다시 써 주세요.\n" + "\n".join(
            f"- {k.split(': ')[0] + ': ' if ': ' in k else ''}{hint(k.split(': ')[-1], p, store, ev)}" for k in failed)
        msgs += [{"role": "assistant", "content": raw}, {"role": "user", "content": fb}]

    cands = tries[-1]["후보"]
    best = next((c for c in cands if not c["실패"]), cands[0] if cands else None)
    final = best["글"] if best else ""
    ai_text = f"{best['행사_한줄']} {best['가게_홍보']}" if best else ""
    return {"사장님_카드": owner_card(ev), "초안": draft(store, ev), "글": final, "후보": cands,
            "1차_통과": not tries[0]["실패"], "최종_실패": tries[-1]["실패"], "시도": len(tries),
            "구성점검": best["점검"] if best else {},
            "말투점검": check_tone(final, ai_text, p),
            "측정": measure(final),
            "판별된_가게": nearest_store(final, stores) if (stores is not None and final) else None, **cost}
