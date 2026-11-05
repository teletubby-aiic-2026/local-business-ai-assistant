"""
주변 행사 → 홍보 계획 (plan_event_promo) v6 기능 부분

변경 이력
- v2: 날짜·거리처럼 계산할 수 있는 값은 코드가 정하고 모델은 글만 쓴다
- v3: 요일도 코드가 계산, 상대 날짜 표현 금지
- v4: 할인 대신 '홍보 방식' 사용. 코드가 행사 특징을 보고 4가지 중 2가지를 고름
- v5: 시간 판단도 코드가 한다
      · 행사 시간과 가게 영업시간·휴무일을 비교해 '행사 전 방문 / 행사 후 방문' 가능 여부를 계산
      · 둘 다 안 되거나 행사 시간을 모르면 시간형을 고르지 않음
      · 행사 기간 중 가게 휴무일이 있으면 계산해서 알려 주고, 시간형 문구에 꼭 넣게 함
      · 점검 보강: '밤 9시'·'오후 7시' 같은 12시간 표기, 행사 후 방문이 안 되는데 '끝나고' 표현,
        휴무일이 있는데 '매일·평일 모두', '오는 주말' 같은 상대 표현, JSON 항목 이름 오타
      · 같은 입력을 여러 번 돌려 결과가 안정적인지 확인 (REPEAT)
- v6: v5에서 모델이 '하지 마라' 규칙(행사 후 방문, 상대 날짜)을 9번 중 8번 어김 → 구조를 바꿈
      · 시간 문장은 코드가 만들어 문구 끝에 붙인다. 모델은 시간·영업·휴무 표현을 아예 쓰지 않는다
      · 금지 대신 '행사장에 가기 전에 들르는 상황으로 쓴다'처럼 해야 할 것을 알려 준다
      · 생성 → 자동 점검 → 걸린 항목을 알려 주고 다시 쓰게 함 (최대 2번) → 그래도 실패면 '사장님 확인 필요'
      · 1차 통과율과 최종 통과율을 따로 기록
"""

import re
from datetime import timedelta

import clova
from common import dates as D

# ── 설정 ───────────────────────────────────────────────────────
POST_DAYS_BEFORE = 2   # 행사 시작 며칠 전에 올릴지
METHODS_TO_SHOW = 2    # 사장님에게 보여 줄 홍보 방식 수
MIN_VISIT_MINUTES = 60 # 행사 전후로 최소 이만큼 영업 중이어야 '방문 가능'
MAX_RETRY = 2          # 점검에 걸리면 다시 쓰게 하는 최대 횟수

STORE = {
    "가게 이름": "예시 브런치 카페",
    "업종": "카페·브런치",
    "위치": "성수역 근처",
    "여는 시각": "10:00",
    "닫는 시각": "21:00",
    "휴무 요일": ["월"],
    "포장": "가능",
    "대표 메뉴": [("아메리카노", "4,500원"), ("버터 크루아상", "4,000원"), ("브런치 플레이트", "15,000원")],
}

MENU_NAMES = [n for n, _ in STORE["대표 메뉴"]]
WEEK = D.WEEK
STORE_HOURS_TXT = f"{STORE['여는 시각']}~{STORE['닫는 시각']}, " + (
    f"{'·'.join(STORE['휴무 요일'])}요일 휴무" if STORE["휴무 요일"] else "휴무 없음")

METHODS = {
    "정보형": "행사 소식을 동네 소식처럼 전하고, 오가는 길에 가볍게 들르길 권한다.",
    "시간형": "행사와 가게를 잇는 한 문장만 쓴다. 영업시간·휴무·전후 안내는 코드가 문장 끝에 붙이므로 시간 관련 표현은 쓰지 않는다.",
    "메뉴형": "행사 성격과 계절에 어울리는 가게 메뉴 1~2개를 내세운다.",
    "편의형": "포장 가능 여부, 행사장과의 거리 같은 이용 편의를 알린다.",
}
SHOW_CATEGORIES = {"연극", "영화", "콘서트", "클래식", "국악", "무용", "뮤지컬/오페라", "독주/독창회"}


# ── 날짜·시간 계산 (모델에게 맡기지 않음) ─────────────────────
def post_date(start, today):
    return max(start - timedelta(days=POST_DAYS_BEFORE), today)


def time_facts(ev):
    """행사 시간과 가게 영업시간을 비교한 사실. 행사 시간 문자열에서 시각만 뽑아 보수적으로 판단."""
    s, e = D.event_dates(ev)
    closed = [s + timedelta(i) for i in range((e - s).days + 1)
              if WEEK[(s + timedelta(i)).weekday()] in STORE["휴무 요일"]]
    raw = str(ev.get("행사_시간") or "").strip()
    open_m, close_m = D.to_min(STORE["여는 시각"]), D.to_min(STORE["닫는 시각"])

    ranges = re.findall(r"(\d{1,2}:\d{2})\s*[~\-–]\s*(\d{1,2}:\d{2})", raw)
    starts = [D.to_min(a) for a, _ in ranges] or [D.to_min(t) for t in re.findall(r"\d{1,2}:\d{2}", raw)]
    ends = [D.to_min(b) for _, b in ranges]  # 끝나는 시각은 '~'로 범위가 적힌 경우에만 안다

    if not raw or not starts:
        before = after = "모름"
    else:
        before = "가능" if any(st - open_m >= MIN_VISIT_MINUTES for st in starts) else "불가"
        if not ends:
            after = "모름"
        else:
            after = "가능" if any(close_m - en >= MIN_VISIT_MINUTES for en in ends) else "불가"
    return {
        "행사 시간": raw or "없음",
        "행사 전 방문": before,
        "행사 후 방문": after,
        "행사 기간 중 가게 휴무일": ", ".join(D.fmt(d) for d in closed) or "없음",
    }


def visit_situation(tf):
    """모델에게 줄 '손님 상황' (금지 대신 해야 할 것)."""
    b, a = tf["행사 전 방문"] == "가능", tf["행사 후 방문"] == "가능"
    if b and a:
        return "행사장에 가기 전이나 다녀온 뒤 들르는 상황"
    if b:
        return "행사장에 가기 전에 들르는 상황 (다녀온 뒤 상황은 쓰지 않는다)"
    if a:
        return "행사장에 다녀온 뒤 들르는 상황 (가기 전 상황은 쓰지 않는다)"
    return "행사장을 오가는 길에 들르는 상황"


def time_sentence(tf):
    """시간형 문구 끝에 코드가 붙이는 문장. 모델이 쓰지 않는다."""
    b, a = tf["행사 전 방문"] == "가능", tf["행사 후 방문"] == "가능"
    when = "행사 전후로" if (b and a) else "행사 보러 가시기 전에" if b else "행사 마치고"
    parts = [f"{when} 들르기 좋아요. 영업시간은 {STORE['여는 시각']}~{STORE['닫는 시각']}이에요."]
    if tf["행사 기간 중 가게 휴무일"] != "없음":
        parts.append(f"{tf['행사 기간 중 가게 휴무일']}은 가게가 쉬어요.")
    return " ".join(parts)


# ── 홍보 방식 고르기 ─────────────────────────────────────────
def pick_methods(ev, walk, today, tf):
    cand = {m: [0, []] for m in METHODS}

    def add(m, pt, why):
        cand[m][0] += pt
        cand[m][1].append(why)

    name, place, target = ev.get("이름", ""), ev.get("장소", ""), ev.get("이용대상", "") or ""
    cat = ev.get("분류", "")

    add("정보형", 1, "모든 행사에 쓸 수 있는 기본 방식")
    add("메뉴형", 1, "가게 대표 메뉴를 함께 알릴 수 있음")
    visit_ok = "가능" in (tf["행사 전 방문"], tf["행사 후 방문"])
    if cat in SHOW_CATEGORIES and visit_ok:
        when = "전후" if tf["행사 전 방문"] == tf["행사 후 방문"] == "가능" else ("전" if tf["행사 전 방문"] == "가능" else "후")
        add("시간형", 3, f"{cat}처럼 시간이 정해진 행사이고, 행사 {when}에 가게가 영업 중")
    if re.search(r"야외|광장|공원|거리|마당|한강", place) or re.search(r"마켓|축제|장터|플리", name) or cat.startswith("축제"):
        add("편의형", 3, "야외·마켓형 행사라 포장이나 잠깐 들르는 수요가 있음")
    if re.search(r"아동|어린이|초등|유아|가족|보호자", target):
        add("메뉴형", 2, "아이와 함께 오는 손님이 많을 행사")
    if today.month in (11, 12, 1, 2):
        add("메뉴형", 1, "추운 계절이라 따뜻한 메뉴를 내세우기 좋음")
    elif today.month in (6, 7, 8):
        add("메뉴형", 1, "더운 계절이라 시원한 메뉴를 내세우기 좋음")
    if walk <= 5:
        add("편의형", 1, f"행사장에서 도보 약 {walk}분으로 가까움")
    if walk >= 15:
        add("정보형", 2, f"도보 약 {walk}분으로 거리가 있어 가볍게 소식으로 알리는 게 자연스러움")

    order = ["시간형", "편의형", "메뉴형", "정보형"]
    ranked = sorted(cand.items(), key=lambda x: (-x[1][0], order.index(x[0])))
    picked = [(m, whys) for m, (pt, whys) in ranked if pt > 0][:METHODS_TO_SHOW]
    return [{"방식": m, "이유": " / ".join(w for w in whys if not w.startswith(("모든", "가게 대표"))) or whys[0]}
            for m, whys in picked]


# ── 프롬프트 ─────────────────────────────────────────────────
SYSTEM_PROMPT = """너는 서울 소상공인의 마케팅 비서다.
가게 근처에서 열리는 행사를 활용해, 사장님이 네이버 플레이스 소식에 올릴 문구를 만든다.
주어진 [홍보 방식]마다 문구를 하나씩 쓴다.

이렇게 쓴다:
1. [손님 상황]에 적힌 상황으로만 쓴다.
2. 행사는 [행사 정보]의 이름과 장소로만 소개한다. 작가·출연자 같은 사람 이름은 쓰지 않는다. 날짜를 쓸 때는 '날짜 표기' 값을 그대로 옮긴다.
3. 메뉴는 [가게 정보]의 메뉴 이름을 그대로 쓴다.
4. 거리를 쓸 때는 "행사장에서 도보 약 N분"처럼 '가게에서 도보' 값을 그대로 옮긴다.
5. 문구는 1~2문장, 이모지는 2개 이하, 일반 문장으로만 쓴다.

쓰지 않는 것: 영업시간, 휴무, 시각, 요일 계산("이번 주말" 등), 할인·혜택, 행사 내용 추측("볼거리 가득" 등), 가게가 행사와 함께하는 듯한 표현("초대", "함께합니다"), 마크다운 기호.

아래 JSON 형식과 항목 이름을 그대로 지켜 답한다. "문구" 배열은 [홍보 방식] 순서와 개수를 따른다.
{
  "대상_손님": "(예: 연극을 보러 오는 중학생 이상 관객) ← 이 행사에 맞게 직접 쓴다",
  "문구": [
    {"방식": "홍보 방식 이름", "내세울_메뉴": ["가게 메뉴 이름 그대로, 0~2개"], "문구_초안": "1~2문장"}
  ]
}"""


PERSON_ROLE = r"작가|가수|배우|감독|시인|교수|선생님|명창|아티스트|피아니스트|첼리스트|바이올리니스트"


def event_label(ev):
    """홍보 문구에 쓸 행사 이름. [기관명] 머리말과 인물 이름을 뺀다 (유명인 이름 상업적 사용 방지)."""
    name = re.sub(r"^\s*(\[[^\]]*\]\s*)+", "", ev.get("이름", "")).strip()
    persons = re.findall(rf"([가-힣]{{2,4}})\s*(?:{PERSON_ROLE})", name)
    name = re.sub(rf"[가-힣]{{2,4}}\s*(?:{PERSON_ROLE})\s*(?:와|과|님과|님와)?\s*(?:함께하는|함께 하는|와 함께)?\s*", "", name).strip()
    show = r"(?:기획)?(?:초대전|개인전|기획전|독주회|독창회|리사이틀|팬미팅|북토크)"
    persons += re.findall(rf"([가-힣]{{2,4}})\s*{show}", name)
    name = re.sub(rf"[가-힣]{{2,4}}\s*({show})", r"\1", name).strip()
    return (name or f"{ev.get('장소')} {ev.get('분류')}"), persons


def build_user_prompt(ev, today, walk, methods, tf):
    menus = ", ".join(f"{n} {p}" for n, p in STORE["대표 메뉴"])
    store = "\n".join([
        f"- 가게 이름: {STORE['가게 이름']}", f"- 업종: {STORE['업종']}", f"- 위치: {STORE['위치']}",
        f"- 포장: {STORE['포장']}", f"- 메뉴: {menus}",
    ])
    label, _ = event_label(ev)
    event = f"- 이름: {label}\n" + "\n".join(f"- {k}: {ev.get(k)}" for k in ["분류", "장소", "유무료", "이용대상"])
    method_txt = "\n".join(f"{i + 1}. {m['방식']}: {METHODS[m['방식']]}" for i, m in enumerate(methods))
    return (
        f"오늘 날짜: {today}\n\n[가게 정보]\n{store}\n\n[행사 정보]\n{event}\n"
        f"- 날짜 표기: {D.date_label(ev)}\n- 가게에서 도보: 약 {walk}분\n- 출처: {ev['출처']}\n\n"
        f"[손님 상황]\n- {visit_situation(tf)}\n\n[홍보 방식]\n{method_txt}"
    )


# ── 자동 점검 ────────────────────────────────────────────────
def hours_in_text(text):
    """'21:00', '9시', '밤 9시', '오후 7시30분'을 모두 24시간 기준 '시'로."""
    hours = [int(h) for h in re.findall(r"(\d{1,2}):\d{2}", text)]
    for ampm, h in re.findall(r"(오전|오후|낮|저녁|밤|새벽)?\s*(\d{1,2})\s*시", text):
        h = int(h)
        if ampm in ("오후", "저녁", "밤") and h < 12:
            h += 12
        hours.append(h)
    return hours


AFTER_WORDS = r"끝난 ?후|끝나고|끝난 뒤|종료 ?후|관람 ?후|마치고|공연 ?후|전/후|전후|이후에도|끝나도"


def check_copy(item, ev, walk, tf, method):
    c = {}
    copy = str(item.get("문구_초안", ""))
    start, end = [s.strip() for s in ev["기간"].split("~")]

    c["항목 이름 정확"] = set(item.keys()) == {"방식", "내세울_메뉴", "문구_초안"}
    menus = item.get("내세울_메뉴", []) or []
    menus = menus if isinstance(menus, list) else [menus]
    c["메뉴 이름이 가게 메뉴 그대로"] = all(m in MENU_NAMES for m in menus)
    c["없는 메뉴(세트 등) 안 만듦"] = not re.search(r"세트|신메뉴|코스", copy)
    c["혜택 없음"] = not re.search(r"할인|증정|무료 ?제공|쿠폰|\d+ ?%|혜택|서비스로", copy)
    c["행사와 협력하는 듯한 표현 없음"] = not re.search(r"초대|함께합니다|함께해요|공식|제휴|주최|저희 행사", copy)
    c["마크다운 기호 없음"] = not re.search(r"\*\*|^#|\n-\s", copy, re.M)

    ok = True
    for mm, dd in re.findall(r"(\d{1,2})\s*[월/.]\s*(\d{1,2})", copy):
        if not (start[5:] <= f"{int(mm):02d}-{int(dd):02d}" <= end[5:]):
            ok = False
    c["날짜가 행사 기간 안"] = ok
    used = {a or b for a, b in re.findall(r"([월화수목금토일])요일|\(([월화수목금토일])\)", copy)}
    allowed_days = set(re.findall(r"\(([월화수목금토일])\)", D.date_label(ev) + tf["행사 기간 중 가게 휴무일"]))
    c["요일이 실제와 같음"] = used <= allowed_days | set(STORE["휴무 요일"])
    c["상대 날짜 표현 없음"] = not re.search(r"이번 ?주|다음 ?주|오는 ?주말|일주일간|주말 ?내내|오늘부터|내일", copy)
    c["도보 시간이 계산값과 같음"] = all(int(x) == walk for x in re.findall(r"(\d+)\s*분", copy))

    allowed_h = {int(h) for h in re.findall(r"(\d{1,2}):\d{2}", STORE["여는 시각"] + STORE["닫는 시각"] + tf["행사 시간"])}
    c["없는 시각 안 만듦"] = all(h in allowed_h for h in hours_in_text(copy))
    if tf["행사 후 방문"] != "가능":
        c["안 되는 '행사 후 방문' 언급 없음"] = not re.search(AFTER_WORDS, copy)
    c["시간·영업·휴무 표현 없음 (코드가 붙임)"] = not re.search(
        r"영업|휴무|쉬어|쉽니다|문을 ?열|운영|\d{1,2}\s*시|\d{1,2}:\d{2}|오전|오후|저녁|밤|매일|평일|주말", copy)
    _, persons = event_label(ev)
    c["인물 이름 없음"] = not any(p in copy for p in persons)
    c["행사 내용 추측 없음"] = not re.search(r"볼거리|가득|다양한|풍성한 행사|북적|인기 ?만점|화제의", copy)

    store_prices = {p for _, p in STORE["대표 메뉴"]}
    c["없는 가격 안 만듦"] = set(re.findall(r"[\d,]+원", copy)) <= store_prices
    return c


def auto_check(plan, ev, walk, methods, tf):
    checks = {"JSON 형식": plan is not None}
    if plan is None:
        return checks
    checks["대상_손님 항목 이름 정확"] = "대상_손님" in plan
    checks["대상_손님을 예시 복사 없이 작성"] = not re.search(r"근거로 한 문장|직접 쓴다|\(예:", str(plan.get("대상_손님", "")))
    items = plan.get("문구", [])
    want = [m["방식"] for m in methods]
    checks["요청한 홍보 방식대로 작성"] = [i.get("방식") for i in items] == want
    for item, m in zip(items, want):
        for k, v in check_copy(item, ev, walk, tf, m).items():
            checks[k] = checks.get(k, True) and v
    return checks


FIX_HINTS = {
    "JSON 형식": "정해진 JSON 형식으로만 답해 주세요.",
    "대상_손님 항목 이름 정확": "항목 이름을 '대상_손님'으로 정확히 써 주세요.",
    "대상_손님을 예시 복사 없이 작성": "대상_손님은 형식 예시를 복사하지 말고, 이 행사의 이용대상과 분류를 보고 직접 써 주세요.",
    "요청한 홍보 방식대로 작성": "[홍보 방식]의 순서와 개수 그대로 써 주세요.",
    "항목 이름 정확": "문구 항목 이름을 '방식', '내세울_메뉴', '문구_초안'으로 정확히 써 주세요.",
    "메뉴 이름이 가게 메뉴 그대로": "메뉴는 가게 메뉴 이름을 그대로 써 주세요.",
    "없는 메뉴(세트 등) 안 만듦": "세트처럼 가게에 없는 메뉴는 빼 주세요.",
    "혜택 없음": "할인·혜택 표현을 빼 주세요.",
    "행사와 협력하는 듯한 표현 없음": "가게가 행사와 함께하는 듯한 표현을 빼 주세요.",
    "마크다운 기호 없음": "** 같은 기호를 빼고 일반 문장으로 써 주세요.",
    "날짜가 행사 기간 안": "날짜는 '날짜 표기' 값을 그대로 써 주세요.",
    "요일이 실제와 같음": "요일은 '날짜 표기' 값을 그대로 쓰거나 빼 주세요.",
    "상대 날짜 표현 없음": "'이번 주말', '오는 주말' 같은 표현 대신 '날짜 표기' 값을 쓰거나 날짜를 빼 주세요.",
    "도보 시간이 계산값과 같음": "거리는 '가게에서 도보' 값을 그대로 써 주세요.",
    "없는 시각 안 만듦": "시각 표현을 빼 주세요.",
    "안 되는 '행사 후 방문' 언급 없음": "[손님 상황]대로 행사장에 가기 전에 들르는 상황으로만 써 주세요. '관람 후', '전후', '끝난 뒤'는 빼 주세요.",
    "시간·영업·휴무 표현 없음 (코드가 붙임)": "영업시간·휴무·시각·평일·주말 표현은 빼 주세요. 이 부분은 따로 붙입니다.",
    "인물 이름 없음": "작가·출연자 이름은 빼고 [행사 정보]의 이름만 써 주세요.",
    "행사 내용 추측 없음": "'볼거리 가득'처럼 행사 내용을 추측하는 표현을 빼 주세요.",
    "없는 가격 안 만듦": "가격은 가게 메뉴 가격만 써 주세요.",
}


def generate_with_repair(model, key, user_prompt, ev, walk, methods, tf):
    """생성 → 점검 → 걸린 항목을 알려 주고 다시 생성 (최대 MAX_RETRY번)."""
    messages = [{"role": "user", "content": user_prompt}]
    attempts = []
    for t in range(MAX_RETRY + 1):
        if model == "HCX-007":
            r = clova.call(key, SYSTEM_PROMPT, messages, model=model,
                            thinking={"effort": "low"}, max_tokens=5120)
        else:
            r = clova.call(key, SYSTEM_PROMPT, messages, model=model, max_tokens=1024)
        if "error" in r:
            return {"오류": r["error"], "시도": attempts}
        plan = clova.parse_json(r["content"])
        checks = auto_check(plan, ev, walk, methods, tf)
        failed = [k for k, v in checks.items() if not v]
        attempts.append({"계획": plan, "원문": r["content"], "실패": failed,
                         "토큰": r["usage"].get("totalTokens", 0), "시간_초": r["seconds"], "요금_원": r["cost_won"]})
        if not failed:
            break
        feedback = "아래 점검에 걸렸어요. 이 부분만 고쳐서 같은 JSON 형식으로 다시 써 주세요.\n" + \
                   "\n".join(f"- {FIX_HINTS.get(k, k)}" for k in failed)
        messages += [{"role": "assistant", "content": r["content"]}, {"role": "user", "content": feedback}]
    return {"시도": attempts}


def final_copies(plan, tf):
    """사장님에게 보여 줄 최종 문구: 시간형은 코드가 만든 시간 문장을 붙인다."""
    out = []
    for item in (plan or {}).get("문구", []):
        text = str(item.get("문구_초안", "")).strip()
        if item.get("방식") == "시간형":
            text = f"{text} {time_sentence(tf)}"
        out.append({"방식": item.get("방식"), "내세울_메뉴": item.get("내세울_메뉴"), "최종_문구": text})
    return out
