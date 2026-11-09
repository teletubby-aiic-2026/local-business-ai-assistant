"""
사장님 메시지 → 알맞은 마케팅 도구 선택 → 실행 → 카드 반환

HyperCLOVA X (HCX-005) function calling 으로 도구를 고르고,
실행 결과를 카드로 돌려준다.
"""

import json
import re
from datetime import date

import clova
from common import dates as D
from common import korean as K
from features import store_profile, weekly, event_plan, notice, coupon

MODEL = "HCX-005"

SYSTEM = """너는 동네 가게 사장님의 마케팅 도우미다.
사장님이 하는 말을 듣고 알맞은 도구를 골라 실행한다.
도구가 맞으면 바로 호출하고, 범위 밖이면 도구를 호출하지 않는다.
날짜·숫자는 직접 계산하지 말고, 도구에 맡긴다.
도구를 호출하지 않을 때는 해요체로 2~3문장만 짧게 답한다. 모르는 사실·숫자·날짜는 말하지 않고,
지금 할 수 있는 일(휴무·영업시간 공지, 근처 행사 계획, 단골 쿠폰, 가게 정보 점검) 중 하나를 다음 행동으로 제안한다."""

REWRITE_SYSTEM = """너는 사장님이 쓴 홍보 문구를 다시 쓰는 도우미다.
날짜·숫자·가격·요일 등 사실 정보는 절대 바꾸지 않는다.
해요체를 유지하고, 요청한 대로 자연스럽게 다시 쓴다."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_store_profile",
            "description": "가게 정보에서 빈칸을 찾아 채울 항목을 안내한다. 예: '가게 정보 뭐 빠졌어?', '프로필 점검해 줘'",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weekly_suggestions",
            "description": "이번 주에 할 만한 마케팅 활동을 추천한다. 예: '이번 주에 뭐 하면 좋아?', '할 일 알려줘'",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_events",
            "description": "근처 행사를 찾아 참여/홍보 계획을 세운다. 예: '근처 행사 있어?', '참여할 만한 행사', '마켓 나가 볼까'",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_notice",
            "description": "휴무·영업시간 변경 공지를 만든다. 사장님이 쉬는 날, 영업시간 변경, 정기휴무 변경을 말하면 공지 글과 스마트플레이스 입력값을 만들어 준다. 예: '다음 주 화요일 쉬어', '모레 오후 2시에 문 열어', '이번 주 금요일 쉬는 날'",
            "parameters": {
                "type": "object",
                "properties": {
                    "notice_text": {
                        "type": "string",
                        "description": "사장님이 말한 원문 그대로 (날짜·시간 표현 포함)",
                    }
                },
                "required": ["notice_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "note_store_info",
            "description": "사장님이 영업시간·휴무일·전화번호·주소·메뉴 가격·주차·예약·편의시설 같은 가게 정보의 '값'을 알려줄 때 안내한다"
                            " (가게 정보가 뭐가 빠졌는지 묻는 질문이 아니라, 사장님이 값을 직접 말해줄 때). "
                            "예: '영업시간 9시부터 10시야', '주차 가능해', '전화번호는 02-1234-5678이야'",
            "parameters": {
                "type": "object",
                "properties": {
                    "항목": {
                        "type": "string",
                        "description": "어떤 가게 정보 항목인지 (예: 영업시간, 휴무일, 전화번호, 주소, 메뉴 가격, 주차,"
                                        " 예약 가능 여부, 편의시설, 가게 소개, 대표 사진, 포장·배달 여부). 모르면 '가게 정보'",
                    },
                    "내용": {"type": "string", "description": "사장님이 말한 가게 정보 원문 그대로"},
                },
                "required": ["내용"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_coupon",
            "description": "쿠폰을 만든다. 혜택 종류, 메뉴, 값(할인 금액/비율), 수량, 기간 등이 필요하다. 예: '단골 쿠폰 만들고 싶은데', '아메리카노 500원 할인 쿠폰', '10% 할인 쿠폰 만들어 줘'",
            "parameters": {
                "type": "object",
                "properties": {
                    "혜택": {"type": "string", "description": "금액 할인, 비율 할인, 1+1, 서비스 증정 중 하나"},
                    "메뉴": {"type": "string", "description": "쿠폰 적용 메뉴 (예: 아메리카노, 전 메뉴)"},
                    "값": {"type": "number", "description": "할인 금액(원) 또는 할인 비율(%)"},
                    "수량": {"type": "integer", "description": "총 발급 매수"},
                    "기간_일": {"type": "integer", "description": "유효기간 일수"},
                },
                "required": [],
            },
        },
    },
]


def _load_events(context):
    """context에 events가 없으면 데이터 파일에서 읽어 캐시한다."""
    if context.get("events"):
        return context["events"]
    today = context.get("today") or date.today()
    try:
        import config as _cfg
        with open(_cfg.DATA_DIR / "events_raw.json", encoding="utf-8") as f:
            seoul = json.load(f)
        with open(_cfg.DATA_DIR / "tour_festivals_raw.json", encoding="utf-8") as f:
            tour = json.load(f)
        evts = event_plan.load_events(seoul, tour, today)
        context["events"] = evts
        return evts
    except (FileNotFoundError, Exception):
        return []


TIME_RANGE_RE = re.compile(r"(\d{1,2})(?:시|:)?(\d{2})?\s*(?:부터|~|-|:)\s*(\d{1,2})(?:시|:)?(\d{2})?")


def _normalize_store_value(text):
    """사장님이 말한 값을 코드로 정리한다. 시간 범위는 'HH:MM ~ HH:MM'으로, 나머지는 말한 그대로(앞뒤 공백만 정리)."""
    m = TIME_RANGE_RE.search(text)
    if m:
        h1, m1, h2, m2 = m.groups()
        return f"{int(h1):02d}:{m1 or '00'} ~ {int(h2):02d}:{m2 or '00'}"
    return text.strip()


DAY_CHARS = "월화수목금토일"
DAY_WITH_SUFFIX_RE = re.compile(r"([월화수목금토일])요일")
PHONE_RE = re.compile(r"0\d{1,2}-?\d{3,4}-?\d{4}")
MENU_PRICE_RE = re.compile(r"([가-힣A-Za-z0-9]+)\s*([\d,]{3,})\s*원")
YESNO_NEG_WORDS = ("불가", "안 돼", "없어요", "없음")
YESNO_POS_WORDS = ("가능", "돼요", "돼", "있어요", "있음")
AMENITY_WORDS = ["와이파이", "Wi-Fi", "화장실", "주차장", "좌석", "흡연실", "반려동물", "단체석", "콘센트"]


def _extract_days(text):
    """'매주 월요일', '월,수 쉬어요' 같은 말에서 요일을 뽑는다."""
    days = []
    for m in DAY_WITH_SUFFIX_RE.finditer(text):
        if m.group(1) not in days:
            days.append(m.group(1))
    if not days:
        for ch in text:
            if ch in DAY_CHARS and ch not in days:
                days.append(ch)
    return days


def _extract_yesno(text):
    if any(w in text for w in YESNO_NEG_WORDS):
        return "불가"
    if any(w in text for w in YESNO_POS_WORDS):
        return "가능"
    return None


def _extract_amenities(text):
    found = []
    for w in AMENITY_WORDS:
        label = "Wi-Fi" if w == "와이파이" else w
        if w in text and label not in found:
            found.append(label)
    return found


def _extract_menu_price(text):
    m = MENU_PRICE_RE.search(text)
    if not m:
        return None, None
    name = m.group(1)
    price = f"{int(m.group(2).replace(',', '')):,}원"
    return name, price


def apply_store_update(store, 항목, 내용):
    """사장님이 말한 가게 정보 값을 정리해 store에 실제로 반영한다 (AI 호출 없음).

    반환: {"항목": 보여줄 이름, "표시값": 반영된 값(문구), "다 채움": bool, "채움_비율": float}
    """
    항목 = (항목 or "가게 정보").strip()
    내용 = (내용 or "").strip()
    표시값 = None

    if 항목 == "영업시간":
        표시값 = _normalize_store_value(내용)
        store["영업시간"] = 표시값

    elif 항목 == "휴무일":
        days = _extract_days(내용)
        if days:
            store["휴무일"] = days
            표시값 = "매주 " + ", ".join(days) + "요일"
        else:
            store["휴무일"] = [내용] if 내용 else store.get("휴무일")
            표시값 = 내용

    elif 항목 == "전화번호":
        m = PHONE_RE.search(내용)
        표시값 = m.group(0) if m else 내용
        store["전화번호"] = 표시값

    elif 항목 == "주소":
        store["주소"] = 내용
        표시값 = 내용

    elif 항목 == "가게 소개":
        store["가게 소개"] = 내용
        표시값 = 내용

    elif 항목 == "대표 사진":
        store["대표 사진"] = [내용] if 내용 else ["등록됨"]
        표시값 = "등록됨"

    elif 항목 == "주차":
        yn = _extract_yesno(내용)
        store["주차"] = yn or 내용
        표시값 = f"주차 {yn}" if yn else 내용

    elif 항목 == "예약 가능 여부":
        yn = _extract_yesno(내용)
        store["예약 가능"] = yn or 내용
        표시값 = f"예약 {yn}" if yn else 내용

    elif 항목 == "편의시설":
        found = _extract_amenities(내용)
        current = store.get("편의시설") or []
        if not isinstance(current, list):
            current = [current] if current else []
        merged = list(current)
        for f in (found or ([내용] if 내용 else [])):
            if f and f not in merged:
                merged.append(f)
        store["편의시설"] = merged
        표시값 = ", ".join(found) if found else 내용

    elif 항목 == "메뉴 가격":
        name, price = _extract_menu_price(내용)
        menu = store.get("메뉴") or []
        if name and price:
            updated = False
            new_menu = []
            for item in menu:
                n = item[0] if isinstance(item, (list, tuple)) else item
                if n == name:
                    new_menu.append((name, price))
                    updated = True
                else:
                    new_menu.append(item)
            if not updated:
                new_menu.append((name, price))
            store["메뉴"] = new_menu
            표시값 = f"{name} {price}"
        else:
            표시값 = 내용

    elif 항목 == "포장·배달 여부":
        bits = []
        pm = re.search(r"포장\s*(가능|불가|안\s*돼요?|돼요?)", 내용)
        if pm:
            yn = "불가" if pm.group(1) in ("불가", "안 돼요", "안돼요") else "가능"
            store["포장"] = yn
            bits.append(f"포장 {yn}")
        dm = re.search(r"배달\s*(가능|불가|안\s*돼요?|돼요?)", 내용)
        if dm:
            yn = "불가" if dm.group(1) in ("불가", "안 돼요", "안돼요") else "가능"
            store["배달"] = yn
            bits.append(f"배달 {yn}")
        표시값 = ", ".join(bits) if bits else 내용

    else:
        표시값 = 내용

    result = store_profile.check_store_profile(store)
    return {"항목": 항목, "표시값": 표시값 or "-", "다 채움": result["다 채움"], "채움_비율": result["채움_비율"]}


def add_temp_closure(store, date_iso, reason=""):
    """임시 휴무일 기록에 날짜를 추가한다 (이미 있으면 중복 추가하지 않고 공지 여부만 갱신)."""
    closures = store.setdefault("임시 휴무일", [])
    for c in closures:
        if c["날짜"] == date_iso:
            c["공지 여부"] = True
            if reason and not c.get("사유"):
                c["사유"] = reason
            return c
    entry = {"날짜": date_iso, "사유": reason or "", "공지 여부": True}
    closures.append(entry)
    closures.sort(key=lambda c: c["날짜"])
    return entry


def active_closures(store, today):
    """지난 날짜를 뺀 임시 휴무일 기록 (날짜 오름차순)."""
    today_iso = today.isoformat() if hasattr(today, "isoformat") else str(today)
    closures = store.get("임시 휴무일") or []
    return sorted([c for c in closures if c["날짜"] >= today_iso], key=lambda c: c["날짜"])


def notice_info_for_date(date_iso, reason=""):
    """기록된 임시 휴무 날짜 하나로 '이해한 값' 정보를 만든다 (AI 호출 없음)."""
    d = D.parse_d(date_iso)
    return {"종류": "임시휴무", "시작": d, "종료": d, "여는": None, "닫는": None,
            "정기휴무": None, "사유": reason or "", "확인필요": [], "사용한_표현": {}}


def build_combined_notice(infos):
    """여러 날짜의 임시휴무 info 를 한 공지로 합친다 (다시 여는 날은 각 날짜마다 따로 계산)."""
    parts, iso_dates = [], []
    for info in infos:
        built = notice.build_notice(info)
        parts.append(built["소식_문구"])
        iso_dates += built["스마트플레이스_입력값"].get("임시 휴무일", [])
    return {"스마트플레이스_입력값": {"임시 휴무일": iso_dates}, "소식_문구": "\n".join(parts)}


def decide_notice_step(info, store, today):
    """날짜가 있으면 바로 확인 단계로, 임시휴무인데 날짜가 없으면 기록된 휴무일 개수로 다음 단계를 정한다 (AI 호출 없음)."""
    if info.get("시작") is not None or info.get("종류") != "임시휴무":
        return {"단계": "확인", "정보": info}
    records = active_closures(store, today)
    if not records:
        return {"단계": "질문"}
    return {"단계": "선택", "기록": records}


def build_situation_summary(store, last, pending):
    """assistant.handle 에 넘길 '지금 상황' 한 줄 요약."""
    bits = [f"가게: {store.get('이름', '')}({store.get('업종', '')})"]
    bits.append(f"마지막 결과: {last.get('요약', '')}" if last else "마지막 결과: 없음")
    need = ", ".join((pending or {}).get("필요한_항목") or [])
    bits.append(f"기다리는 값: {need or '없음'}")
    return " / ".join(bits)


def resolve_pending_message(pending, user_text):
    """pending 으로 기다리던 값을 사장님의 새 말과 합쳐 다시 물을 메시지를 만든다."""
    base = (pending or {}).get("요청문구") or ""
    user_text = (user_text or "").strip()
    if not base:
        return user_text
    return f"{base} {user_text}".strip()


def extract_pending(tool_name, cards, user_text):
    """실행 결과가 '더 필요한 값'을 묻는 카드면, 다음 말을 그 값으로 받기 위한 pending 을 만든다."""
    if not cards:
        return None
    c = cards[0]
    if c.get("종류") == "되묻기":
        need = [line.lstrip("- ").strip() for line in (c.get("내용") or "").split("\n") if line.strip()]
        return {"기능": tool_name, "필요한_항목": need, "요청문구": user_text}
    return None


REF_WORDS = ("그거", "그걸", "아까", "방금", "그 글", "위 글")
CHANNEL_TRIGGERS = [
    ("인스타그램", ["인스타그램", "인스타로", "인스타에"]),
    ("인스타 스토리", ["스토리로", "스토리에"]),
    ("네이버 플레이스 소식", ["네이버로", "플레이스로", "소식으로"]),
    ("카카오톡 채널", ["카톡으로", "카카오톡으로", "카톡에"]),
]
LENGTH_SHORT_WORDS = ("짧게", "줄여", "간단하게")
LENGTH_LONG_WORDS = ("길게", "늘려", "자세하게")
REDO_WORDS = ("다시",)
CORRECTION_HINT_RE = re.compile(r"[월화수목금토일]요일|\d{1,2}\s*시|\d{1,2}:\d{2}")


def detect_followup(text):
    """'그거 더 짧게/인스타로/다시', '아니 수요일로' 같은 이어지는 말을 판단한다 (AI 호출 없음)."""
    text = (text or "").strip()
    if not text:
        return None
    for channel, triggers in CHANNEL_TRIGGERS:
        if any(t in text for t in triggers):
            return {"종류": "채널", "채널": channel}
    if any(t in text for t in LENGTH_SHORT_WORDS):
        return {"종류": "길이", "방향": "짧게"}
    if any(t in text for t in LENGTH_LONG_WORDS):
        return {"종류": "길이", "방향": "길게"}
    if any(t in text for t in REDO_WORDS) and any(r in text for r in REF_WORDS):
        return {"종류": "다시"}
    if text.startswith("아니") and (CORRECTION_HINT_RE.search(text) or len(text) <= 12):
        return {"종류": "수정", "문구": text}
    return None


def rewrite_text(key, text, instruction):
    """채널 변환이 아닌 길이·다시 쓰기는 AI 에게 맡긴다 (사실·숫자는 바꾸지 않도록 지시)."""
    msgs = [{"role": "user", "content": f"다음 문구를 {instruction} 다시 써줘:\n\n{text}"}]
    r = clova.call(key, REWRITE_SYSTEM, msgs, model=MODEL, temperature=0.4, max_tokens=512)
    if "error" in r:
        return None, r["error"]
    return (r.get("content") or "").strip(), None


def _parse_tool_calls(response):
    tcs = response.get("toolCalls")
    if not tcs:
        return None, None
    tc = tcs[0]
    fn = tc.get("function", {})
    name = fn.get("name")
    args = fn.get("arguments", "{}")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return name, args


def _run_tool(name, args, store, context, key):
    today = context.get("today") or date.today()

    if name == "check_store_profile":
        result = store_profile.check_store_profile(store)
        if result["다 채움"]:
            return [{"종류": "프로필", "제목": "가게 정보가 다 채워져 있어요!", "내용": f"채움 비율: {result['채움_비율']:.0%}"}]
        items = "\n".join(f"- {b['이름']}: {b['안내']}" for b in result["빈칸"][:5])
        return [{"종류": "프로필", "제목": f"빈칸 {len(result['빈칸'])}개를 채워 보세요",
                 "내용": items, "버튼": "store_profile"}]

    if name == "note_store_info":
        update = apply_store_update(store, args.get("항목"), args.get("내용"))
        msg = (f"{update['항목']}{K.eul(update['항목'])} {update['표시값']}"
               f"{K.josa(update['표시값'], '으로', '로')} 반영했어요.")
        if update["다 채움"]:
            msg += " 이제 가게 정보가 100% 채워졌어요 🎉"
        msg += " 스마트플레이스에도 같은 값을 넣어 주세요."
        return [{"종류": "안내", "제목": "가게 정보를 반영했어요", "내용": msg}]

    if name == "get_weekly_suggestions":
        events = _load_events(context)
        complaints = context.get("complaints")
        cards = weekly.get_weekly_suggestions(store, events, today, complaints)
        return [{"종류": "주간추천", "제목": c["제목"], "내용": c.get("근거", ""), "버튼": c.get("버튼", "")} for c in cards]

    if name == "plan_events":
        events = _load_events(context)
        join, near = event_plan.match(store, events, today)
        msg = context.get("_message", "")
        if msg:
            from common.korean import nospace
            nm = nospace(msg)
            for lst in (join, near):
                lst.sort(key=lambda e: (0 if nospace(e["이름"]) in nm or nm in nospace(e["이름"]) else 1))
        if not join and not near:
            return [{"종류": "행사", "제목": "이번 주 근처에 맞는 행사가 없어요", "내용": "다음 주에 다시 알려 드릴게요."}]
        cards = []
        for e in (join + near)[:3]:
            mode = "참여형" if e in join else "주변형"
            cards.append({"종류": "행사", "제목": f"{e['이름']} ({mode})",
                          "내용": f"{e.get('장소', '')} · {e.get('유형', '')}", "버튼": "event_plan"})
        return cards

    if name == "make_notice":
        notice_text = args.get("notice_text", "")
        ext, tries, total, err = notice.extract_b(key, notice_text)
        if err:
            return [{"종류": "오류", "제목": "공지 정보를 뽑지 못했어요", "내용": err}]
        info = notice.to_info_b(ext, today, notice_text)
        step = decide_notice_step(info, store, today)
        return [{"종류": "공지_단계", "제목": "", "내용": "", "단계": step}]

    if name == "make_coupon":
        required = []
        if not args.get("혜택"):
            required.append("혜택 종류 (금액 할인 / 비율 할인 / 1+1 / 서비스 증정)")
        if not args.get("메뉴"):
            required.append("적용 메뉴")
        if required:
            return [{"종류": "되묻기", "제목": "쿠폰을 만들려면 몇 가지 더 알려 주세요",
                     "내용": "\n".join(f"- {r}" for r in required), "버튼": "make_coupon"}]
        result = coupon.build_coupon(args, store, today)
        cards = [{"종류": "쿠폰", "제목": "쿠폰 미리보기",
                  "내용": json.dumps(result["입력값"], ensure_ascii=False, indent=2), "버튼": "coupon"}]
        if result.get("확인 필요"):
            cards[0]["확인필요"] = result["확인 필요"]
        return cards

    return None


def _out_of_scope(content):
    content = content or ""
    if any(w in content for w in ("상권", "매출", "경쟁", "인구", "유동인구")):
        return [{"종류": "안내", "제목": "상권 분석 화면에서 볼 수 있어요",
                 "내용": "상권·매출·경쟁 정보는 상권 분석 화면에서 확인해 주세요.", "버튼": "market_analysis"}]
    return [{"종류": "안내", "제목": "그건 아직 제가 도와드리기 어려워요",
             "내용": "대신 이런 건 바로 할 수 있어요.\n· 휴무·영업시간 공지 만들기\n· 근처 행사 계획 세우기\n· 단골 쿠폰 만들기",
             "버튼": ""}]


def handle(message, store, context, key):
    msgs = []
    summary = context.get("요약")
    if summary:
        msgs.append({"role": "user", "content": f"[지금까지 상황]\n{summary}"})
        msgs.append({"role": "assistant", "content": "네, 참고해서 답할게요."})
    for t in (context.get("최근턴") or [])[-4:]:
        msgs.append(t)
    msgs.append({"role": "user", "content": message})

    r = clova.call(key, SYSTEM, msgs, model=MODEL, temperature=0.1, max_tokens=1024,
                   tools=TOOLS, tool_choice="auto")
    if "error" in r:
        detail = str(r["error"])[:300]
        return {"카드": [{"종류": "오류", "제목": "다시 시도해 주세요", "내용": r["error"], "오류_상세": detail}],
                "도구": None, "원문": r}

    name, args = _parse_tool_calls(r)

    if name is None:
        content = (r.get("content") or "").strip()
        cards = [{"종류": "안내", "제목": "", "내용": content}] if content else _out_of_scope(message)
        return {"카드": cards, "도구": None, "원문": r}

    context["_message"] = message
    args = dict(args or {})
    if name == "make_notice":
        # 이전 대화에 있던 날짜를 끌어오지 않도록, 공지 추출은 항상 이번 메시지 원문만 쓴다.
        args["notice_text"] = message
    try:
        cards = _run_tool(name, args, store, context, key)
    except Exception as exc:
        detail = str(exc)[:300]
        cards = [{"종류": "오류", "제목": "다시 시도해 주세요", "내용": str(exc)[:200], "오류_상세": detail}]
    if cards is None:
        cards = _out_of_scope(message)
        name = None

    return {"카드": cards, "도구": name, "원문": r}


def handle_mock(message, store, context, mock_tool_name, mock_args=None):
    """테스트용: 모델 호출 없이 도구 실행 흐름만 확인."""
    if mock_tool_name is None:
        cards = _out_of_scope(message)
        return {"카드": cards, "도구": None, "원문": None}
    context["_message"] = message
    try:
        cards = _run_tool(mock_tool_name, mock_args or {}, store, context, key=None)
    except Exception as exc:
        detail = str(exc)[:300]
        cards = [{"종류": "오류", "제목": "다시 시도해 주세요", "내용": str(exc)[:200], "오류_상세": detail}]
    if cards is None:
        cards = _out_of_scope(message)
        mock_tool_name = None
    return {"카드": cards, "도구": mock_tool_name, "원문": None}
