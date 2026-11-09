"""
S2 업종 맞춤 행사 추천 + 어필 계획

배경
- 행사 정보는 사장님이 "이 행사를 활용할까?"를 판단하는 재료다. 손님에게 보이는 글의 주인공은 가게.
- 업종에 맞는 행사(음식점 → 먹거리 축제, 옷가게 → 장터·마켓)는 드물다
  (11/5 확인: 서울시 문화행사 안 끝난 323건 중 먹거리 실제 1건, 장터 2건 / TourAPI 서울 31건)
- 그래서 두 데이터를 합치고, 행사 활용을 두 방식으로 나눈다
    참여형: 셀러·부스로 직접 나간다 → 서울 전체에서, 업종이 맞는 행사만
    주변형: 행사 방문객을 가게로 끌어온다 → 가게 반경 안, 사람이 많이 모이는 행사

역할 나누기 (S2·B2에서 배운 원칙)
- 코드: 데이터 합치기, 행사 유형 분류, 업종 맞춤 판단, 거리·도보 시간, 날짜별 할 일
- AI: 어필 포인트 2~3개 (가게 상품·칭찬 리뷰만 근거로), 주변형 홍보글(features/tone.py)
"""

import math
import re
from datetime import date, datetime, timedelta

import clova
from common import korean as K

MODEL = "HCX-005"
MAX_RETRY = 2
NEAR_KM = 3.0          # 주변형: 가게 반경
LONG_EVENT_DAYS = 60   # 이보다 길면 상시 행사로 보고 주변형 추천에서 뺌
WD = "월화수목금토일"

# ── 행사 유형 분류 (코드 규칙) ─────────────────────────────────
SHOW_CATS = {"연극", "영화", "콘서트", "클래식", "국악", "무용", "뮤지컬/오페라", "독주/독창회"}
NOT_SELLING = r"도서관|북큐레이션|기타리스트|강연|강좌|투어|클래스|교실|체험"  # 먹거리 단어가 있어도 판매 행사가 아님
TYPE_RULES = [  # (유형, 제목 패턴, 제외 패턴)  — 먹거리는 세부 유형으로 나눈다
    ("먹거리·술", r"우리술|술 ?축제|전통주|막걸리|와인|맥주|치맥|양조", NOT_SELLING),
    ("먹거리·카페", r"커피|빵|베이커리|디저트|티 ?페스|차 ?축제", NOT_SELLING),
    ("먹거리", r"푸드|먹거리|음식|미식|요리|야시장|푸드트럭|김장|미각|맛 ?축제|먹방", NOT_SELLING),
    ("장터·먹거리", r"푸드 ?마켓|야시장|먹거리 ?장터|농부 ?시장|마르쉐|직거래 ?장터", r""),
    ("장터·물건", r"플리|벼룩|수집가|빈티지 ?마켓|아트 ?마켓|핸드메이드|굿즈|프리마켓|바자", r""),
    ("장터", r"마켓|장터", r""),  # 무엇을 파는지 이름만으로 모르는 마켓 (예: 광화문 마켓)
    ("박람회", r"박람회|페어|엑스포|기념품|굿즈", r""),
    ("패션·디자인", r"패션|디자인코리아|디자인 ?페어|빈티지|업사이클|핸드메이드", r"졸업|전공|교육|체험"),
    ("큰 축제", r"축제|페스티벌|페스타|빛초롱|나이트|스케이트장|밤길", r""),
]

# 업종 → 참여형으로 맞는 행사 유형
FIT = {  # 음식 업종은 물건 장터(플리·수집가 마켓)에 넣지 않는다
    "카페": ["먹거리", "먹거리·카페", "장터·먹거리", "장터"],
    "고깃집": ["먹거리", "먹거리·술", "장터·먹거리"],
    "분식": ["먹거리", "장터·먹거리", "장터"],
    "음식점": ["먹거리", "먹거리·술", "장터·먹거리"],
    "주점": ["먹거리", "먹거리·술"],
    "옷가게": ["장터·물건", "장터", "패션·디자인"],
    "소품": ["장터·물건", "장터", "박람회"],
}
MIN_PREP_DAYS = 7  # 참여형은 최소 이만큼 남은 행사만 (셀러 모집·준비 시간)
FIT_REASON = {
    "먹거리": "먹거리를 찾는 손님이 모이는 행사라 음식을 직접 맛보여 줄 수 있어요",
    "먹거리·술": "술과 어울리는 음식을 찾는 손님이 모이는 행사라 안주가 될 메뉴를 보여 줄 수 있어요",
    "먹거리·카페": "커피·디저트를 찾는 손님이 모이는 행사예요",
    "장터·먹거리": "먹거리를 사러 오는 손님이 모이는 장터예요",
    "장터·물건": "물건을 구경하고 사는 손님이 모이는 장터예요 (빈티지·수집품·핸드메이드 등)",
    "장터": "구경하며 물건을 사는 손님이 모이는 장터예요. 다만 어떤 품목의 셀러를 받는지는 데이터에 없어서 문의가 필요해요",
    "패션·디자인": "옷·디자인에 관심 있는 손님이 모이는 행사예요",
    "박람회": "상품을 둘러보러 오는 손님이 모이는 박람회예요",
}
# 주변형: 사람이 많이 모이는 유형일수록 우선
CROWD = {"큰 축제": 3, "장터": 3, "장터·먹거리": 3, "장터·물건": 3, "먹거리": 3, "먹거리·술": 3, "먹거리·카페": 3, "박람회": 2, "공연": 1, "전시": 1, "기타": 0}
HOOK_WORD = {"큰 축제": "축제", "장터": "마켓", "장터·먹거리": "마켓", "장터·물건": "마켓", "먹거리": "축제", "먹거리·술": "축제", "먹거리·카페": "축제", "박람회": "행사", "공연": "공연", "전시": "전시", "기타": "행사"}


def classify(title, cat=""):
    t = f"{title} {cat}"
    for name, pat, ex in TYPE_RULES:
        if re.search(pat, t) and not (ex and re.search(ex, t)):
            if name == "먹거리" and cat in SHOW_CATS:  # '커피 볶는 기타리스트' 같은 공연 제외
                continue
            return name
    if cat in SHOW_CATS:
        return "공연"
    if cat == "교육/체험":
        return "교육·체험"
    if "전시" in cat:
        return "전시"
    if cat.startswith("축제"):
        return "큰 축제"
    return "기타"


# ── 데이터 합치기 ────────────────────────────────────────────
def _d(s):
    s = re.sub(r"\D", "", str(s or ""))[:8]
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        return None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _coords(a, b):
    a, b = _f(a), _f(b)
    if a is None or b is None:
        return None, None
    if 33 < a < 39 and 124 < b < 132:
        return a, b
    if 33 < b < 39 and 124 < a < 132:
        return b, a
    return None, None


def from_seoul(r):
    lat, lng = _coords(r.get("LAT"), r.get("LOT"))
    return {"이름": r.get("TITLE", ""), "원래_분류": r.get("CODENAME", ""), "자치구": r.get("GUNAME", ""),
            "장소": r.get("PLACE", ""), "시작": _d(r.get("STRTDATE")), "종료": _d(r.get("END_DATE")),
            "위도": lat, "경도": lng, "시간": r.get("PRO_TIME") or "", "문의처": r.get("INQUIRY") or "",
            "링크": r.get("ORG_LINK") or r.get("HMPG_ADDR") or "", "출처": "서울시 문화행사 정보"}


def from_tour(r):
    addr = str(r.get("addr1", ""))
    gu = addr.split()[1] if len(addr.split()) > 1 else ""
    return {"이름": r.get("title", ""), "원래_분류": "", "자치구": gu, "장소": addr,
            "시작": _d(r.get("eventstartdate")), "종료": _d(r.get("eventenddate")),
            "위도": _f(r.get("mapy")), "경도": _f(r.get("mapx")), "시간": "", "문의처": r.get("tel") or "",
            "링크": "", "출처": "한국관광공사 TourAPI"}


def norm_title(t):
    """같은 행사인지 비교용. 앞의 [기관명]·연도·회차·기호만 지우고, 행사 이름 자체([점프x컷] 등)는 남긴다."""
    t = re.sub(r"^\s*(\[[^\]]*\]\s*)+", "", t)
    t = re.sub(r"20\d\d|제\s*\d+\s*회", "", t)
    t = re.sub(r"[\s\[\]()「」《》〈〉'\"｜|·,.\-–:：]", "", t)
    return t.lower()


def load_events(seoul_rows, tour_rows, today):
    """TourAPI를 먼저 넣고, 서울시 데이터에 같은 행사가 있으면 빈 칸만 채운다.
    같은 데이터 안의 중복은 첫 번째만 남긴다. (출처 표시는 실제로 두 데이터에 다 있을 때만 '둘 다')"""
    evs, seen = [], {}
    for src, rows, conv in (("tour", tour_rows, from_tour), ("seoul", seoul_rows, from_seoul)):
        for r in rows:
            e = conv(r)
            key = norm_title(e["이름"])
            if not key:
                continue
            if key in seen:
                base, base_src = seen[key]
                if base_src != src and "+" not in base["출처"]:
                    for k in ("시간", "문의처", "링크", "원래_분류"):
                        base[k] = base[k] or e[k]
                    base["출처"] = "한국관광공사 TourAPI + 서울시 문화행사 정보"
                continue
            seen[key] = (e, src)
            evs.append(e)
    out = []
    for e in evs:
        if not e["시작"] or not e["종료"] or e["종료"] < today:
            continue
        e["유형"] = classify(e["이름"], e["원래_분류"])
        e["기간_일수"] = (e["종료"] - e["시작"]).days + 1
        out.append(e)
    return out


# ── 거리·날짜 (코드) ─────────────────────────────────────────
def km(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def walk_min(d):
    return max(1, math.ceil(d * 1.3 * 1000 / 75))


def fmt(d):
    return f"{d.month}월 {d.day}일({WD[d.weekday()]})"


def period(e):
    return fmt(e["시작"]) if e["시작"] == e["종료"] else f"{fmt(e['시작'])}~{fmt(e['종료'])}"


def timeline(e, mode, today):
    """날짜별 할 일. 지난 날짜는 '지금 바로'로 당긴다."""
    s = e["시작"]
    if mode == "참여형":
        steps = [(21, "행사 문의처에 셀러·부스 참여가 가능한지, 모집 기간과 비용을 문의"),
                 (7, "참여가 정해지면 가져갈 상품과 가격표, 진열 방법 준비"),
                 (3, "네이버 플레이스 소식으로 참여 소식 알리기"),
                 (0, "행사 당일: 가게 위치·영업시간 안내 카드를 함께 준비")]
    else:
        steps = [(3, "네이버 플레이스 소식에 홍보글 올리기"),
                 (1, "행사 기간 손님이 늘 수 있으니 재료·재고와 영업시간 점검"),
                 (0, "행사 기간: 행사장에서 오는 손님이 찾기 쉽게 가게 앞 안내 확인")]
    out, late = [], False
    for before, what in steps:
        d = s - timedelta(days=before)
        if d < today:
            late = True
            d = today
        out.append({"날짜": fmt(d), "할 일": what})
    note = ""
    if mode == "참여형" and (s - today).days < 21:
        note = f"행사까지 {(s - today).days}일 남아 셀러 모집이 끝났을 수 있어요. 지금 바로 문의해 보세요."
    elif late:
        note = "일정이 촉박해서 몇 가지는 오늘 바로 해야 해요."
    return out, note


# ── 행사 고르기 (코드) ───────────────────────────────────────
def match(store, events, today, top=2):
    fit = FIT.get(store["업종"], [])
    join = [e for e in events if e["유형"] in fit and (e["시작"] - today).days >= MIN_PREP_DAYS]
    join.sort(key=lambda e: e["시작"])
    near = []
    for e in events:
        if e["위도"] is None or e["기간_일수"] > LONG_EVENT_DAYS or CROWD.get(e["유형"], 0) == 0:
            continue
        d = km(store["위도"], store["경도"], e["위도"], e["경도"])
        if d <= NEAR_KM:
            near.append({**e, "거리_km": round(d, 2), "도보": walk_min(d)})
    near.sort(key=lambda e: (-CROWD.get(e["유형"], 0), e["거리_km"]))
    joined_names = {e["이름"] for e in join[:top]}
    near = [e for e in near if e["이름"] not in joined_names]
    return join[:top], near[:top]


PERSON = r"[가-힣]{2,4}\s*(?:작가|가수|배우|감독|시인|교수|선생님|명창)\s*(?:와|과)?\s*(?:함께하는|함께 하는)?\s*"


def event_label(name):
    """AI에게 넘길 행사 이름: 앞의 [기관명]과 사람 이름을 뺀다 (유명인 이름 상업적 사용 방지)."""
    name = re.sub(r"^\s*(\[[^\]]*\]\s*)+", "", name)
    return re.sub(PERSON, "", name).strip()


def reason(store, e, mode):
    if mode == "참여형":
        return f"{store['업종']}{K.josa(store['업종'], '과', '와') if hasattr(K, 'josa') else '와'} 맞는 {e['유형']} 행사예요. {FIT_REASON.get(e['유형'], '')}"
    return f"가게에서 도보 약 {e['도보']}분 거리의 {e['유형']} 행사예요. 행사 방문객을 가게로 이끌 수 있어요"


# ── 어필 포인트 (AI) ─────────────────────────────────────────
SYS_POINTS = """너는 소상공인 마케팅 비서다. 사장님에게 이 행사를 활용해 가게를 어떻게 어필할지 제안한다.

- 활용 방식이 '참여형'이면: 이 행사에 셀러·부스로 참여한다면 무엇을 앞세우고 어떻게 보여 줄지
- 활용 방식이 '주변형'이면: 행사에 나가지 않고, 행사에 온 손님을 가게로 오게 하려면 가게에서 무엇을 앞세울지

지킬 것:
1. 상품·메뉴는 [대표 상품]에 있는 것만, 장점은 [칭찬 리뷰]에 나온 것만 근거로 쓴다.
2. 가격, 숫자, 할인, 증정은 쓰지 않는다. (혜택은 사장님이 따로 정한다)
3. 행사 내용은 [행사 정보]에 있는 것만. 모르는 행사 프로그램을 지어내지 않는다.
4. 참여형은 참여가 확정된 것처럼 쓰지 않는다 ("참여한다면 ~").
5. 손님에게 하는 광고 문장이 아니라, 사장님에게 하는 조언이다. "~하면 좋아요", "~를 앞에 두세요"처럼 쓴다.
   ("오세요", "드셔보세요", "맛보셔야 해요" 같은 손님용 말투는 쓰지 않는다)
6. [칭찬 리뷰]에 없는 가게 특징(맵기 조절, 시그니처, 인기 메뉴 등)을 사실처럼 쓰지 않는다.
7. 포인트마다 한 문장, 해요체.

포인트마다 근거를 단다. 근거는 [칭찬 리뷰] 중 하나를 글자 그대로 복사하거나, 리뷰가 아니면 "대표 상품"이라고 쓴다.

아래 JSON으로만 답한다.
{"어필_포인트": [{"포인트": "...", "근거": "..."}, {"포인트": "...", "근거": "..."}, {"포인트": "...", "근거": "..."}]}"""

HINTS = {
    "형식": '{{"어필_포인트": [{{"포인트": "...", "근거": "..."}}, ...]}} 형식으로 2~3개 써 주세요.',
    "근거가 실제 리뷰": "근거는 [칭찬 리뷰] 중 하나를 글자 그대로 복사하거나 '대표 상품'이라고 써 주세요.",
    "근거 없는 특징 안 만듦": "리뷰에 없는 특징(맵기 조절, 토핑, 시그니처, 인기 같은 말)은 빼고 리뷰에 나온 내용만 써 주세요.",
    "숫자·가격·할인 없음": "가격·숫자·할인·증정은 빼 주세요.",
    "없는 상품 안 만듦": "대표 상품에 없는 음식이나 상품은 빼 주세요.",
    "참여 확정처럼 안 씀": "참여가 확정된 것처럼 쓰지 말고 '참여한다면'으로 써 주세요.",
    "협력 표현 없음": "가게가 행사와 함께하는 것처럼 쓰지 말아 주세요.",
    "상품 이름 포함": "포인트에 대표 상품 이름을 하나 이상 넣어 주세요.",
    "사장님에게 하는 조언": "손님에게 하는 말('오세요', '드셔보세요') 대신 사장님에게 하는 조언('~하면 좋아요')으로 써 주세요.",
    "사람 이름 없음": "작가·출연자 이름은 빼 주세요.",
    "주변형은 가게 안에서": "주변형은 행사에 나가지 않아요. 부스 얘기 대신 행사 손님을 가게로 이끄는 방법(가게 안 진열, 소식 글, 안내)으로 써 주세요.",
}
FOOD = ["소주", "맥주", "막걸리", "와인", "디저트", "케이크", "쿠키", "샌드위치", "음료", "주스", "김밥",
        "라면", "치킨", "피자", "티셔츠", "모자", "신발", "액세서리", "귀걸이", "향수"]


# 리뷰·상품·예전 글에 없으면 지어낸 특징일 가능성이 큰 말
CLAIMS = ["조절", "토핑", "시그니처", "인기", "유명", "다양한", "맛집", "특제", "비법", "수제", "매콤", "달콤",
          "정성", "고급", "트렌디", "독특한 디자인", "명물", "대표 메뉴", "전문적인"]


def check_points(pts, store, mode, persons=(), cites=None):
    text = " ".join(pts)
    allowed = K.nospace(" ".join([store["이름"], " ".join(store["메뉴"]), " ".join(store.get("칭찬 리뷰", [])),
                                  " ".join(store.get("예전 글", []))]))
    c = {"형식": 2 <= len(pts) <= 3}
    if cites is not None:
        strip = lambda x: re.sub(r"[\s.,!?~'\"]", "", x)
        reviews = {strip(r) for r in store.get("칭찬 리뷰", [])}
        c["근거가 실제 리뷰"] = all(strip(x) in reviews or "대표상품" in strip(x) for x in cites)
    c["근거 없는 특징 안 만듦"] = not [w for w in CLAIMS if K.nospace(w) in K.nospace(text) and K.nospace(w) not in allowed]
    c["숫자·가격·할인 없음"] = not re.search(r"\d|할인|증정|쿠폰|무료 ?제공", text)
    c["없는 상품 안 만듦"] = not [w for w in FOOD if w in K.nospace(text) and w not in allowed]
    c["상품 이름 포함"] = any(K.nospace(m.split()[-1]) in K.nospace(text) for m in store["메뉴"])
    c["사장님에게 하는 조언"] = not re.search(
        r"오세요|드셔\s?보세요|맛보셔야|즐겨\s?보세요|방문하세요|방문하시면|찾아\s?주시면|느껴\s?보세요|만들어\s?보세요|"
        r"맛볼 수 있어요|즐기실|드립니다|드려요|받고 있답니다|마무리를 해보세요", text)
    if persons:
        c["사람 이름 없음"] = not any(pn in text for pn in persons)
    if mode == "참여형":
        c["참여 확정처럼 안 씀"] = not re.search(r"참여합니다|참여해요|나갑니다|나가요|참가합니다", text)
    else:
        c["협력 표현 없음"] = not re.search(r"초대|함께합니다|공식|제휴|협업", text)
        c["주변형은 가게 안에서"] = not re.search(r"부스|현장에서|행사장에서 직접", text)
    return c


def points(store, e, mode, key):
    user = "\n\n".join([
        f"[가게]\n{store['이름']} ({store['업종']})",
        "[대표 상품]\n" + ", ".join(store["메뉴"]),
        "[칭찬 리뷰]\n" + "\n".join(f"- {x}" for x in store.get("칭찬 리뷰", [])),
        f"[행사 정보]\n{event_label(e['이름'])} · {e['유형']} · {e['장소']} · {period(e)}",
        f"[활용 방식]\n{mode}",
    ])
    msgs = [{"role": "user", "content": user}]
    tries, won = [], 0.0
    for _ in range(MAX_RETRY + 1):
        r = clova.call(key, SYS_POINTS, msgs, model=MODEL, temperature=0.3, max_tokens=512)
        if "error" in r:
            return {"오류": r["error"]}
        won += r.get("won", 0)
        js = clova.parse_json(r["content"]) or {}
        raw_pts = (js.get("어필_포인트") or [])[:3]
        pts = [str(x.get("포인트", "")).strip() if isinstance(x, dict) else str(x).strip() for x in raw_pts]
        cites = [str(x.get("근거", "")).strip() if isinstance(x, dict) else "" for x in raw_pts]
        pts, cites = [p_ for p_ in pts if p_], [c_ for p_, c_ in zip(pts, cites) if p_]
        persons = re.findall(r"([가-힣]{2,4})\s*(?:작가|가수|배우|감독|시인|교수|선생님|명창)", e["이름"])
        c = check_points(pts, store, mode, persons, cites)
        failed = [k for k, v in c.items() if not v]
        tries.append({"포인트": pts, "근거": cites, "실패": failed})
        if not failed:
            break
        msgs += [{"role": "assistant", "content": r["content"]},
                 {"role": "user", "content": "아래를 고쳐서 같은 JSON으로 다시 써 주세요.\n" +
                  "\n".join(f"- {HINTS.get(k, k)}" for k in failed)}]
    return {"어필_포인트": tries[-1]["포인트"], "근거": tries[-1]["근거"], "점검_실패": tries[-1]["실패"],
            "1차_통과": not tries[0]["실패"], "시도": len(tries), "won": round(won, 2)}


# ── 행사 유형별 행동 아이디어 (코드) ──────────────────────────
# AI 포인트는 '무엇을 내세울지'(리뷰 근거), 이 표는 '이 행사에서 어떻게 할지'(행사 유형별 정석)
FOOD_BIZ = {"카페", "고깃집", "분식", "음식점", "주점"}
IDEAS = {
    ("참여형", "장터", "음식"): ["걸으면서 먹기 쉬운 크기·포장으로 준비하기", "가게 위치가 적힌 작은 안내 카드 함께 건네기"],
    ("참여형", "장터", "물건"): ["반응 좋은 상품 위주로 수량을 줄여 가져가기", "손님이 직접 만져 보고 입어 볼 수 있게 진열하기"],
    ("참여형", "먹거리", "음식"): ["한입 크기 시식으로 맛을 먼저 보여 주기", "가게에서 먹으면 어떤지 사진 한 장으로 보여 주기"],
    ("참여형", "먹거리·술", "음식"): ["술과 곁들이기 좋은 한입 크기로 준비하기", "가게에서 먹으면 어떤지 사진 한 장으로 보여 주기"],
    ("참여형", "패션·디자인", "물건"): ["매장 분위기를 보여 줄 사진·소품을 함께 두기", "명함이나 가게 위치 카드 준비하기"],
    ("주변형", "공연", "음식"): ["공연 시작 전에 빨리 나갈 수 있는 메뉴를 앞에 두기", "공연장에서 오는 길에 보이도록 가게 앞 안내 확인하기"],
    ("주변형", "공연", "물건"): ["공연 전후 지나가는 사람 눈에 띄게 가게 앞 진열 바꾸기", "짧게 둘러봐도 되는 분위기라는 걸 소식 글에 쓰기"],
    ("주변형", "장터", "음식"): ["행사 기간 포장·테이크아웃이 된다는 걸 강조하기", "행사 손님이 몰리는 시간대 영업시간 확인하기"],
    ("주변형", "장터", "물건"): ["장터 손님 취향에 맞는 상품을 가게 앞에 꺼내 두기", "행사 기간 가게 앞 진열을 바꿔 지나가는 사람 눈에 띄게 하기"],
    ("주변형", "큰 축제", "음식"): ["행사 기간 포장·테이크아웃이 된다는 걸 강조하기", "손님이 몰릴 때를 대비해 재료 넉넉히 준비하기"],
    ("주변형", "큰 축제", "물건"): ["행사 기간 가게 앞 진열을 바꿔 지나가는 사람 눈에 띄게 하기", "행사 기간 영업시간을 소식 글로 알리기"],
}


def ideas(e, mode, store):
    grp = "장터" if e["유형"].startswith("장터") else e["유형"]
    biz = "음식" if store["업종"] in FOOD_BIZ else "물건"
    return IDEAS.get((mode, grp, biz)) or IDEAS.get((mode, "큰 축제", biz)) or []


# ── 계획 하나 만들기 ─────────────────────────────────────────
def build_plan(store, e, mode, key, today, tone_profile=None, with_post=True):
    tl, note = timeline(e, mode, today)
    plan = {
        "활용 방식": mode, "행사": e["이름"], "유형": e["유형"], "기간": period(e), "장소": e["장소"],
        "거리": f"도보 약 {e['도보']}분" if mode == "주변형" else "서울 전체에서 찾음 (참여형은 거리 상관없음)",
        "문의처": e.get("문의처") or "데이터에 없음 (행사 주최 측 확인 필요)", "출처": e["출처"],
        "맞는 이유": reason(store, e, mode), "할 일": tl, "일정 메모": note,
        "행사 맞춤 아이디어": ideas(e, mode, store),
    }
    if mode == "참여형" and e["유형"] == "장터":
        plan["확인 필요"] = "행사 설명이 데이터에 없어 어떤 품목의 셀러를 받는지 몰라요. 문의할 때 꼭 확인하세요."
    p = points(store, e, mode, key)
    if "오류" in p:
        plan["오류"] = p["오류"]
        return plan
    plan.update(p)
    if mode == "주변형" and with_post and tone_profile is not None:
        from features import tone as T  # 홍보글은 S1 말투 기능을 그대로 사용
        ev = {"이름": event_label(e["이름"]), "종류": HOOK_WORD.get(e["유형"], "행사"), "핵심어": event_label(e["이름"]),
              "장소": e["장소"], "날짜": period(e), "도보": e["도보"],
              "상황": f"{HOOK_WORD.get(e['유형'], '행사')} 오가는 길에 들르는 손님"}
        g = T.generate(store, ev, tone_profile, True, key)
        if "오류" not in g:
            cands = g.get("후보", [])
            ok = [c["글"] for c in cands if not c["실패"]]
            plan["홍보글_후보"] = ok  # 점검을 통과한 후보만 사장님에게 보여 준다
            plan["홍보글_점검_실패"] = [] if ok else [f"후보 {i}: {', '.join(c['실패'])}" for i, c in enumerate(cands, 1)]
            plan["홍보글_초안"] = g.get("글")  # 점검에 실패해도 사장님이 고쳐 쓸 수 있게 원문은 남긴다
            plan["won"] = round(plan.get("won", 0) + g.get("won", 0), 2)
    return plan
