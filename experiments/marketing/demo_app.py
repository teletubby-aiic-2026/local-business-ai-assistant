"""회의 데모용 Streamlit 앱. 대화창 하나로 기능을 보여 준다. features/ 의 기능을 그대로 불러와 쓴다.

실행: streamlit run demo_app.py
"""

import copy
import html
import os
import re
from datetime import date, timedelta

import streamlit as st

import config
from common import dates as D
from common import korean as K
from features import assistant, coupon, event_plan, notice, store_profile, tone, weekly
from samples.stores import STORES

NO_KEY_MESSAGE = "AI 연결 키가 아직 설정되지 않았어요. 키 없이도 쿠폰 만들기는 바로 할 수 있어요."

SMARTPLACE_URL = "https://new.smartplace.naver.com"
COUPON_HELP_URL = ""  # 비어 있으면 링크를 숨긴다

FIELD_EXAMPLE = {
    "영업시간": "영업시간 11시~20시", "휴무일": "휴무일 매주 월요일",
    "전화번호": "전화번호 02-1234-5678", "메뉴 가격": "아메리카노 4500원",
    "주소": "주소 서울 성동구 성수동", "가게 소개": "가게 소개 아늑한 동네 카페예요",
    "대표 사진": "대표 사진 올릴게요", "포장·배달 여부": "포장 가능, 배달 불가",
    "메뉴 3개 이상": "메뉴 추가할게요", "주차": "주차 가능해요",
    "예약 가능 여부": "예약 가능해요", "편의시설": "편의시설 Wi-Fi 있어요",
}

st.set_page_config(page_title="소상공인 AI 비서 · 마케팅", page_icon="🏪", layout="centered")

st.markdown(
    """
    <style>
    body, .stApp, .stMarkdown p, .stMarkdown li { font-size: 16px; }
    .stButton > button { border-radius: 10px; font-size: 15px; height: 44px; }
    [data-testid="stCaptionContainer"], small { font-size: 13.5px; color: #6B6B63; }
    .tag {
        display: inline-block; padding: 0.1rem 0.6rem; border-radius: 999px;
        background: #E3ECE8; color: #1F6F5C; font-size: 0.78rem; font-weight: 600;
        margin-bottom: 0.3rem;
    }
    .card-title { font-size: 17px; font-weight: 700; }
    .app-title { font-size: 28px; font-weight: 800; }
    .bubble {
        background: #EEF0EC; border-radius: 14px; padding: 12px 16px;
        display: inline-block; margin-bottom: 10px;
    }
    div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) {
        flex-direction: row-reverse; text-align: right;
    }
    .block-container, [data-testid="stBottomBlockContainer"] { max-width: 1040px; }
    [data-testid="stChatMessage"] [data-testid="stVerticalBlockBorderWrapper"] { max-width: 680px; }
    .st-key-chatbox { background: #FFFFFF; border-radius: 16px; padding: 24px; }
    [data-testid="stPills"] button { border-radius: 999px !important; height: 42px; }
    .sidebar-muted { color: #9A9A92; }
    .post-box {
        background: #FAFAF7; border: 1px solid #E3E3DC; border-radius: 10px;
        padding: 12px 14px; white-space: pre-wrap;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── store_profile·weekly·assistant·coupon 이 기대하는 가게 정보 형식 ──────
# (tests/test_weekly.py · tests/test_store_profile.py 와 같은 형식: 메뉴는
#  (이름, "가격원") 짝, 영업시간·휴무일·전화번호 등 필드 포함. features/ 는 수정하지 않고
#  demo_app.py 에서만 이 형식으로 바꿔 넘긴다. tone·event_plan 에는 원래 store 를 넘긴다.)
PROFILE_EXTRA = {
    "몽글커피": {
        "영업시간": None, "휴무일": ["월"], "전화번호": "02-1234-5678",
        "메뉴": [("몽글 크림라떼", "5,000원"), ("아메리카노", "4,500원"), ("휘낭시에", "4,000원")],
        "주소": "서울 성동구 성수동", "가게 소개": "아늑한 동네 카페예요.",
        "대표 사진": ["photo1.jpg"], "포장": "가능", "배달": "불가",
        "주차": "없음", "예약 가능": "가능", "편의시설": ["Wi-Fi"],
    },
    "성수 숯불집": {
        "영업시간": "17:00~24:00", "휴무일": ["일"], "전화번호": None,
        "메뉴": [("돼지 목살", "15,000원"), ("된장찌개", "9,000원"), ("냉면", "9,000원")],
        "주소": "서울 성동구 성수동", "가게 소개": "숯불로 구운 목살 전문점이에요.",
        "대표 사진": ["photo2.jpg"], "포장": "불가", "배달": "불가",
        "주차": "있음", "예약 가능": "가능", "편의시설": ["화장실"],
    },
    "떡볶이 연구소": {
        "영업시간": "11:00~21:00", "휴무일": ["화"], "전화번호": "02-1111-2222",
        "메뉴": [("국물떡볶이", "4,000원"), ("김말이", "1,000원"), ("순대", "5,000원")],
        "주소": None, "가게 소개": "국물떡볶이 전문점이에요.",
        "대표 사진": ["photo3.jpg"], "포장": "가능", "배달": "가능",
        "주차": "없음", "예약 가능": "불가", "편의시설": [],
    },
    "오늘의 옷장": {
        "영업시간": "12:00~20:00", "휴무일": ["수"], "전화번호": "02-3333-4444",
        "메뉴": [("빈티지 니트", "35,000원"), ("데님 자켓", "42,000원"), ("가죽 가방", "68,000원")],
        "주소": "서울 성동구 성수동", "가게 소개": "빈티지 옷가게예요.",
        "대표 사진": ["photo4.jpg"], "포장": "불가", "배달": "불가",
        "주차": "없음", "예약 가능": "불가", "편의시설": [],
    },
}


def to_profile_store(store):
    """store_profile·weekly·assistant·coupon 에 넘길 형식으로 바꾼다 (메뉴는 (이름, 가격) 짝)."""
    return dict(store, **PROFILE_EXTRA.get(store["이름"], {}))


# ── 접속 잠금 (그대로) ─────────────────────────────────────────
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD")
if DEMO_PASSWORD:
    if "authed" not in st.session_state:
        st.session_state.authed = False
    if not st.session_state.authed:
        st.title("마케팅 비서 데모")
        pw = st.text_input("비밀번호", type="password")
        if st.button("입장"):
            if pw == DEMO_PASSWORD:
                st.session_state.authed = True
                st.rerun()
            else:
                st.error("비밀번호가 맞지 않아요")
        st.stop()


# ── 맨 위: 제목만 ──────────────────────────────────────────────
st.markdown("<div class='app-title'>마케팅 비서</div>", unsafe_allow_html=True)


# ── 사이드바: 가게 선택 · 가게 정보 · 기준일 · (맨 아래) CLOVA 키 ──────
def _sidebar_value(v):
    if v in (None, "", [], ()):
        return None
    if isinstance(v, (list, tuple)):
        v = [str(x) for x in v if x not in (None, "")]
        return ", ".join(v) if v else None
    return str(v)


def _sidebar_row(label, value):
    val = _sidebar_value(value)
    if val:
        st.sidebar.markdown(f"**{label}**：{val}")
    else:
        st.sidebar.markdown(f"**{label}**：<span class='sidebar-muted'>아직 없음</span>", unsafe_allow_html=True)


st.sidebar.markdown("### 가게")
store_idx = st.sidebar.selectbox(
    "가게", options=list(range(len(STORES))),
    format_func=lambda i: STORES[i]["이름"], label_visibility="collapsed",
)
STORE = STORES[store_idx]

# 대화 상태(가게 정보 사본·마지막 결과·기다리는 값)는 가게가 바뀔 때만 다시 만든다.
# (사이드바·이번 주 할 일·가게 정보 점검은 모두 이 사본을 보고 다시 계산된다.)
STORE_CHANGED = ("conv" not in st.session_state) or (st.session_state.get("_prev_store_idx") != store_idx)
if STORE_CHANGED:
    st.session_state.conv = {"store": copy.deepcopy(to_profile_store(STORE)), "last": None, "pending": None}
PROFILE_STORE = st.session_state.conv["store"]
PROFILE_STORE.setdefault("임시 휴무일", [])

st.sidebar.markdown("### 가게 정보")
for _label, _value in [
    ("업종", STORE.get("업종")), ("위치", PROFILE_STORE.get("주소")),
    ("영업시간", PROFILE_STORE.get("영업시간")), ("휴무일", PROFILE_STORE.get("휴무일")),
    ("전화번호", PROFILE_STORE.get("전화번호")),
    ("포장", PROFILE_STORE.get("포장")), ("배달", PROFILE_STORE.get("배달")),
    ("주차", PROFILE_STORE.get("주차")), ("예약", PROFILE_STORE.get("예약 가능")),
    ("편의시설", PROFILE_STORE.get("편의시설")),
]:
    _sidebar_row(_label, _value)

with st.sidebar.expander("메뉴 · 가격 보기"):
    for _n, _p in PROFILE_STORE.get("메뉴", []):
        st.write(f"{_n} · {_p}")

st.sidebar.markdown("### 기준일")
TODAY = st.sidebar.date_input("기준일", value=date.today(), label_visibility="collapsed")

_active_closures = assistant.active_closures(PROFILE_STORE, TODAY)
_sidebar_row(
    "임시 휴무",
    ", ".join(D.fmt(D.parse_d(c["날짜"])) for c in _active_closures) if _active_closures else None,
)

ENV_KEY = os.environ.get("CLOVA_API_KEY")
if ENV_KEY:
    CLOVA_KEY = ENV_KEY
else:
    st.sidebar.divider()
    CLOVA_KEY = st.sidebar.text_input("CLOVA API 키", type="password") or None
KEY_AVAILABLE = bool(CLOVA_KEY)
if not KEY_AVAILABLE:
    st.sidebar.caption("CLOVA 키를 입력해 주세요.")


# ── 행사 데이터 (한 번만 읽기) ─────────────────────────────────
@st.cache_data(show_spinner=False)
def load_events_cached(today):
    import json

    seoul_path = config.DATA_DIR / "events_raw.json"
    tour_path = config.DATA_DIR / "tour_festivals_raw.json"
    missing = []
    seoul, tour = [], []
    if seoul_path.exists():
        with open(seoul_path, encoding="utf-8") as f:
            seoul = json.load(f)
    else:
        missing.append(str(seoul_path))
    if tour_path.exists():
        with open(tour_path, encoding="utf-8") as f:
            tour = json.load(f)
    else:
        missing.append(str(tour_path))
    return event_plan.load_events(seoul, tour, today), missing


EVENTS, MISSING_FILES = load_events_cached(TODAY)


def friendly_error(raw):
    """CLOVA 원문 오류(HTTP 코드·JSON 등)를 사장님이 볼 수 있는 짧은 문장으로 바꾼다."""
    text = str(raw)
    if "401" in text or "Invalid Key" in text or "403" in text:
        return "CLOVA 키가 올바르지 않아요. 키를 다시 확인해 주세요."
    return "CLOVA 호출에 실패했어요. 잠시 후 다시 시도해 주세요."


def warn_box(content):
    """내용이 비어 있으면 경고 상자를 그리지 않는다 (모든 st.warning 호출은 이 함수를 거친다)."""
    if isinstance(content, (list, tuple)):
        content = "\n".join(c for c in content if c)
    if content and str(content).strip():
        st.warning(content)


# 홍보글 점검에서 걸린 항목 이름(features/tone.py HINT 와 같은 이름) → 사람 말
POST_FAIL_REASON = {
    "날짜·장소·거리·숫자 없음": "글에 날짜나 숫자가 들어가 있어요",
    "과장 표현 없음": "과장된 표현이 있어요",
    "없는 음식·술 안 만듦": "메뉴에 없는 음식이 들어가 있어요",
    "혜택·협력 표현 없음": "할인이나 협력하는 듯한 표현이 들어가 있어요",
    "행사 한 줄 있음": "첫 문장에 행사 언급이 빠졌어요",
    "행사는 첫 줄에서만 언급": "가게 얘기에 행사 얘기가 섞여 있어요",
    "가게가 주인공 (가게 이름·'저희')": "가게가 주인공으로 드러나지 않아요",
    "메뉴 이름 포함 (1번)": "메뉴 이름이 들어가 있지 않아요",
    "칭찬 리뷰 표현 사용": "리뷰에 나온 표현이 들어가 있지 않아요",
    "어색한 표현 없음": "어색한 표현이 있어요",
    "사장님 시점 (손님 시점 아님)": "손님 시점으로 쓰여 있어요",
    "사장님이 지운 표현 없음": "사장님이 쓰지 않기로 한 표현이 들어가 있어요",
}


def _friendly_post_fail_reasons(fails):
    """'후보 1: 이름1, 이름2' 문자열들에서 걸린 항목 이름만 뽑아 사람 말로 바꾼다."""
    names = []
    for line in fails or []:
        _, _, rest = line.partition(":")
        for name in rest.split(","):
            name = name.strip()
            if name and name not in names:
                names.append(name)
    return [POST_FAIL_REASON.get(n, n) for n in names]


def _merge_todo_by_date(todo):
    """같은 날짜의 할 일을 한 줄로 합친다."""
    order, by_date = [], {}
    for t in todo:
        d = t["날짜"]
        if d not in by_date:
            by_date[d] = []
            order.append(d)
        by_date[d].append(t["할 일"])
    return [(d, ", ".join(by_date[d])) for d in order]


def store_profile_outro(result):
    if result["다 채움"] or not result["빈칸"]:
        return None
    first = result["빈칸"][0]["이름"]
    example = FIELD_EXAMPLE.get(first, first)
    return f"{first}{K.eul(first)} 말해 주시면 넣을 값을 정리해 드릴게요. 예: {example}"


def notice_intro(info):
    s, e = info["시작"], info["종료"]
    when = D.fmt(s) if (not e or s == e) else f"{D.fmt(s)}부터 {D.fmt(e)}까지"
    verbs = {
        "임시휴무": f"{when} 쉬시는 거죠?", "단축영업": f"{when} 영업시간이 바뀌는 거죠?",
        "영업시간 변경": f"{when}부터 영업시간이 바뀌는 거죠?", "정기휴무 변경": f"{when}부터 정기휴무가 바뀌는 거죠?",
    }
    return (verbs.get(info["종류"], f"{when} 내용이 맞는 거죠?")
            + " 날짜는 달력으로 계산했어요. 아래 값을 스마트플레이스에 넣고, 소식 문구는 복사해서 올리시면 돼요.")


def _mode_words(text):
    """plan['거리'] 같은 features/ 원문 문구의 '참여형'/'주변형' 표기만 화면에서 바꿔 보여 준다."""
    return text.replace("참여형", "셀러로 나가기").replace("주변형", "근처 손님 맞이")


# ── 홍보글 채널별 다시 쓰기 (AI 호출 없음, 코드로만 재구성) ─────────────
CHANNELS = ["인스타그램", "인스타 스토리", "네이버 플레이스 소식", "카카오톡 채널"]


def _split_sentences(text):
    text = re.sub(r"#\S+", "", text)  # 기존 해시태그는 떼고 채널별로 다시 붙인다
    sentences = re.split(r"(?<=[.!?가-힣])\s*\n+|(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in sentences if s.strip()]


def _store_hashtags(store, profile_store):
    tags = []
    for post in store.get("예전 글", []):
        for tag in re.findall(r"#\S+", post):
            if tag not in tags:
                tags.append(tag)
    addr = profile_store.get("주소") or ""
    area = next((t for t in addr.split() if t.endswith("동")), "성수")
    업종 = store.get("업종", "")
    for extra in (f"#{area}{업종}", f"#{업종}추천"):
        if extra not in tags:
            tags.append(extra)
    return tags[:6]


def _weekly_closed_bit(days_off):
    if isinstance(days_off, (list, tuple)):
        days = [d for d in days_off if d]
    elif days_off:
        days = [days_off]
    else:
        return None
    if not days:
        return None
    names = [d if str(d).endswith("요일") else f"{d}요일" for d in days]
    return f"휴무일은 {', '.join(names)}입니다"


def _this_week_closures(profile_store, today):
    """이번 주(월~일)에 들어오는 임시 휴무일 기록만 뽑는다."""
    start = D.week_start(today)
    end = start + timedelta(days=6)
    records = assistant.active_closures(profile_store, today)
    return [r for r in records if start.isoformat() <= r["날짜"] <= end.isoformat()]


def format_for_channel(channel, text, store, profile_store):
    sentences = _split_sentences(text)
    body = " ".join(sentences)
    menu = store.get("메뉴", [])
    위치 = profile_store.get("주소") or store.get("업종", "")

    if channel == "인스타그램":
        lines = sentences + [""]
        lines.append(f"📍 {store['이름']} · {위치}")
        if menu:
            lines.append("🍽 " + ", ".join(menu[:3]))
        tags = _store_hashtags(store, profile_store)
        if tags:
            lines.append(" ".join(tags))
        return "\n".join(lines)

    if channel == "인스타 스토리":
        lines = [sentences[0] if sentences else body]
        if menu:
            lines.append(f"🍽 {menu[0]}")
        lines.append("구경하러 오세요 🙂")
        return "\n".join(lines[:3])

    if channel == "네이버 플레이스 소식":
        lines = [f"[이번 주 소식] {store['이름']}", "", " ".join(sentences[:3])]
        if menu:
            lines.append("대표 메뉴: " + " · ".join(menu[:3]))
        hours = profile_store.get("영업시간")
        info_bits = []
        if hours:
            info_bits.append(f"영업시간 {hours}")
        day_bit = _weekly_closed_bit(profile_store.get("휴무일"))
        if day_bit:
            info_bits.append(day_bit)
        if info_bits:
            lines.append(" · ".join(info_bits))
        week_closures = _this_week_closures(profile_store, TODAY)
        if week_closures:
            dates = ", ".join(D.fmt(D.parse_d(c["날짜"])) for c in week_closures)
            lines.append(f"이번 주 휴무 {dates}")
        closer_hints = ("보내세요", "환영", "기다리고 있어요", "들러", "놀러 오세요")
        if not any(h in body for h in closer_hints):
            lines.append("오늘도 좋은 하루 보내세요 🙂")
        return "\n".join(lines)

    # 카카오톡 채널
    lines = list(sentences)
    closer_hints = ("들러", "놀러", "환영", "기다리고", "보내세요", "편하게")
    if not any(h in body for h in closer_hints):
        lines.append("편하게 들러 주세요~")
    return "\n".join(lines)


def format_notice_for_channel(channel, text, store, profile_store):
    """휴무·영업시간 공지 소식 문구를 채널별 형식으로 다시 쓴다 (AI 호출 없음, 날짜는 코드 계산값 그대로)."""
    sentences = _split_sentences(text)
    body = " ".join(sentences)
    위치 = profile_store.get("주소") or store.get("업종", "")

    if channel == "인스타그램":
        lines = sentences + ["", f"📍 {store['이름']} · {위치}"]
        tags = _store_hashtags(store, profile_store)
        if tags:
            lines.append(" ".join(tags))
        return "\n".join(lines)

    if channel == "인스타 스토리":
        lines = sentences[:2] if sentences else [body]
        lines.append("양해 부탁드려요 🙏")
        return "\n".join(lines[:3])

    if channel == "네이버 플레이스 소식":
        lines = [f"[휴무 안내] {store['이름']}", "", body]
        if not any(h in body for h in ("헛걸음", "양해", "감사합니다")):
            lines.append("헛걸음하지 않도록 미리 알려 드려요. 감사합니다.")
        return "\n".join(lines)

    # 카카오톡 채널
    lines = [f"안녕하세요, {store['이름']}입니다!", body]
    if not any(h in body for h in ("양해", "감사합니다")):
        lines.append("양해 부탁드려요 🙏")
    return "\n".join(lines)


def _benefit_display(choice):
    혜택, 값 = choice.get("혜택"), choice.get("값")
    if 혜택 == "증정":
        return "1개 증정"
    if 혜택 == "금액 할인" and 값 is not None:
        return f"{int(값):,}원 할인"
    if 혜택 == "비율 할인" and 값 is not None:
        return f"{값}% 할인"
    return 혜택 or "-"


def _fmt_date_str(s):
    try:
        return D.fmt(date.fromisoformat(s))
    except (ValueError, TypeError):
        return s


def _fmt_notice_value(v):
    if isinstance(v, list):
        return ", ".join(_fmt_date_str(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{_fmt_date_str(k)} {val}" for k, val in v.items())
    return str(v)


def format_cards(cards):
    parts = []
    for c in cards:
        block = f"**{c['제목']}**" if c.get("제목") else ""
        if c.get("내용") and c.get("종류") == "오류":
            block += f"\n\n{friendly_error(c['내용'])}"
        elif c.get("내용"):
            block += f"\n\n{c['내용']}"
        if c.get("확인필요"):
            block += "\n\n⚠ " + "; ".join(c["확인필요"])
        if c.get("입력값"):
            rows = "\n".join(f"- **{k}**: {v}" for k, v in c["입력값"].items())
            block += f"\n\n{rows}"
        parts.append(block)
    return "\n\n---\n\n".join(parts) if parts else "(응답 없음)"


# ── 대화 기록 ───────────────────────────────────────────────
def append_user(text):
    st.session_state.chat.append({"role": "user", "type": "text", "text": text})


def append_assistant_text(text):
    st.session_state.chat.append({"role": "assistant", "type": "text", "text": text})


def append_assistant(**kwargs):
    kwargs.setdefault("role", "assistant")
    st.session_state.chat.append(kwargs)


def _find_event(card, join, near):
    """weekly 카드 제목에 들어간 행사 이름으로 실제 행사·활용 방식을 찾는다."""
    for mode, lst in (("참여형", join), ("주변형", near)):
        for e in lst:
            if e["이름"] in card["제목"]:
                return mode, e
    return None, None


def _compute_home():
    """이번 주 할 일 카드를 (지금 store 값으로) 새로 계산한다."""
    weekly_cards = weekly.get_weekly_suggestions(PROFILE_STORE, EVENTS, TODAY)
    join, near = event_plan.match(STORE, EVENTS, TODAY)

    if len(weekly_cards) == 1 and weekly_cards[0]["종류"] == "없음":
        return "안녕하세요, 사장님! 이번 주는 특별히 급한 일이 없어요.", []

    home_cards = []
    for c in weekly_cards[:3]:
        if c["종류"] == "가게 정보":
            home_cards.append({
                "tag": "가게 정보", "제목": c["제목"], "근거": c.get("근거", ""),
                "action": "store_profile", "action_label": "채워 보기",
            })
        elif c["종류"] == "행사":
            mode, e = _find_event(c, join, near)
            if e is None:
                continue
            tag = "행사 · 셀러로 나가기" if mode == "참여형" else "행사 · 근처 손님 맞이"
            label = "계획 보기" if mode == "참여형" else "홍보글 보기"
            home_cards.append({
                "tag": tag, "제목": c["제목"], "근거": c.get("근거", ""),
                "action": "event_plan", "mode": mode, "event": e, "action_label": label,
            })
        else:
            home_cards.append({
                "tag": c["종류"], "제목": c["제목"], "근거": c.get("근거", ""),
                "action": None, "action_label": None,
            })

    return "안녕하세요, 사장님! 이번 주에 이걸 해 보는 건 어때요?", home_cards


def build_home():
    st.session_state.chat = []
    st.session_state.hidden_cards = set()
    text, cards = _compute_home()
    append_assistant(type="home", text=text, cards=cards)


def refresh_home_card():
    """가게 정보가 바뀐 뒤, 이미 보여 준 '이번 주 할 일' 카드를 바뀐 값으로 다시 계산한다."""
    text, cards = _compute_home()
    for m in st.session_state.chat:
        if m.get("type") == "home":
            m["text"] = text
            m["cards"] = cards
            return


if "chat" not in st.session_state or STORE_CHANGED:
    st.session_state.chat_context = {}
    build_home()
    st.session_state["_prev_store_idx"] = store_idx


# ── 행사 추천 계획 (공통) ───────────────────────────────────────
def start_event_plan(mode, e):
    label = "계획 보기" if mode == "참여형" else "홍보글 보기"
    append_user(f"{e['이름']}으로 {label}")
    if not KEY_AVAILABLE:
        append_assistant_text(NO_KEY_MESSAGE)
        return
    with st.spinner("계획을 만드는 중..."):
        try:
            profile = tone.build_profile(STORE)
            plan = event_plan.build_plan(STORE, e, mode, CLOVA_KEY, TODAY, tone_profile=profile)
        except Exception as exc:
            plan = {"오류": friendly_error(exc)}
    if "오류" in plan:
        plan["오류"] = friendly_error(plan["오류"])
    else:
        append_assistant_text(f"이 행사는 {plan['맞는 이유']}")
        post_text = (plan.get("홍보글_후보") or [None])[0] or plan.get("홍보글_초안")
        if post_text:
            st.session_state.conv["last"] = {
                "기능": "event_plan", "요약": f"{plan['행사']} 홍보글",
                "요청문구": f"{e['이름']}으로 {label}", "글": post_text,
            }
    append_assistant(type="event_plan", plan=plan)


# ── 휴무 공지 (대화든 빠른 버튼이든 한 흐름: 단계 판단 → 확인 → 결과) ──────
def _record_closure_dates(info):
    """임시휴무 공지가 확정되면 그 날짜(들)를 가게 기록에 남긴다 (이미 있으면 중복 추가 안 함)."""
    if info["종류"] != "임시휴무" or not info.get("시작"):
        return
    s, e = info["시작"], info["종료"] or info["시작"]
    d = s
    while d <= e:
        assistant.add_temp_closure(st.session_state.conv["store"], d.isoformat(), info.get("사유") or "")
        d += timedelta(days=1)


def _apply_notice_step(step, origin):
    """공지 요청을 코드가 분석한 결과(단계)에 맞는 화면을 붙인다."""
    conv = st.session_state.conv
    단계 = step["단계"]
    if 단계 == "확인":
        info = step["정보"]
        if info.get("확인필요"):
            append_assistant_text("말씀하신 내용을 이렇게 이해했는데, 몇 가지 확인이 필요해요.")
            append_assistant(type="notice_warn", issues=info["확인필요"])
            conv["pending"] = {"기능": "make_notice", "필요한_항목": info["확인필요"], "요청문구": origin}
        else:
            append_assistant_text("이렇게 이해했어요. 날짜는 코드가 달력으로 계산했으니, 맞는지 한 번만 확인해 주세요.")
            append_assistant(type="notice_confirm", info=info, origin=origin)
            conv["pending"] = None
    elif 단계 == "질문":
        append_assistant_text("언제 쉬시나요?")
        conv["pending"] = {"기능": "make_notice", "필요한_항목": ["쉬는 날짜"], "요청문구": origin}
    elif 단계 == "선택":
        records = step["기록"]
        if len(records) == 1:
            append_assistant_text(f"{D.fmt(D.parse_d(records[0]['날짜']))} 공지를 만들까요?")
        else:
            append_assistant_text("어느 날 공지를 만들까요?")
        append_assistant(type="notice_pick", records=records, 요청문구=origin)
        conv["pending"] = None


def ask_other_date():
    """'다른 날짜'/'날짜 고칠게요' — 틀린 날짜가 섞인 원문은 버리고 날짜만 새로 받는다."""
    append_assistant_text("언제 쉬시나요?")
    st.session_state.conv["pending"] = {"기능": "make_notice", "필요한_항목": ["날짜"], "요청문구": "휴무 공지"}


def finish_notice_flow(info, origin=""):
    built = notice.build_notice(info)
    _record_closure_dates(info)
    append_assistant_text(notice_intro(info))
    append_assistant(type="notice_result", 입력값=built["스마트플레이스_입력값"], 문구=built["소식_문구"])
    st.session_state.conv["last"] = {
        "기능": "make_notice", "요약": f"{info['종류']} 공지", "요청문구": origin, "글": built["소식_문구"],
    }
    st.session_state.conv["pending"] = None


def finish_combined_notice(records, origin=""):
    infos = [assistant.notice_info_for_date(r["날짜"], r.get("사유", "")) for r in records]
    built = assistant.build_combined_notice(infos)
    for info in infos:
        _record_closure_dates(info)
    append_assistant_text("한 번에 공지를 만들었어요. 날짜마다 다시 여는 날은 따로 계산했어요.")
    append_assistant(type="notice_result", 입력값=built["스마트플레이스_입력값"], 문구=built["소식_문구"])
    st.session_state.conv["last"] = {
        "기능": "make_notice", "요약": "임시휴무 공지 (여러 날)", "요청문구": origin, "글": built["소식_문구"],
    }
    st.session_state.conv["pending"] = None


# ── 가게 정보 점검 ───────────────────────────────────────────
def start_store_profile_flow():
    append_user("가게 정보 뭐 빠졌어?")
    result = store_profile.check_store_profile(PROFILE_STORE)
    append_assistant(type="store_profile_result", result=result)


# ── 자유 입력 (쿠폰 포함, assistant 경로 그대로) ───────────────────
def _recent_turns():
    """assistant.handle 에 넘길 최근 대화 몇 줄 (전체 기록 대신)."""
    turns = []
    for m in st.session_state.chat:
        if m.get("type") not in ("text", "generic") or not m.get("text"):
            continue
        role = "user" if m["role"] == "user" else "assistant"
        turns.append({"role": role, "content": m["text"]})
    return turns[-4:]


def process_free_message(user_text):
    append_user(user_text)
    if not KEY_AVAILABLE:
        append_assistant_text(NO_KEY_MESSAGE)
        return
    conv = st.session_state.conv

    # 1) 아직 못 받은 값이 있었으면, 이번 말을 그 값으로 받아 이어서 처리한다.
    if conv.get("pending"):
        merged = assistant.resolve_pending_message(conv["pending"], user_text)
        conv["pending"] = None
        _run_assistant_and_render(merged)
        return

    # 2) 마지막 결과를 가리키는 말("그거 더 짧게", "인스타로", "아니 수요일로")이면 코드로 처리한다.
    followup = assistant.detect_followup(user_text) if conv.get("last") else None
    if followup:
        _handle_followup(followup, conv["last"])
        return

    # 3) 보통의 자유 입력
    _run_assistant_and_render(user_text)


def _handle_followup(followup, last):
    종류 = followup["종류"]
    text = last.get("글")

    if 종류 == "채널":
        if not text:
            append_assistant_text("다시 쓸 글이 아직 없어요. 먼저 공지나 쿠폰·홍보글을 만들어 주세요.")
            return
        channel = followup["채널"]
        if last.get("기능") == "make_notice":
            out = format_notice_for_channel(channel, text, STORE, PROFILE_STORE)
        else:
            out = format_for_channel(channel, text, STORE, PROFILE_STORE)
        append_assistant_text(f"{channel}용으로 바꿨어요.")
        append_assistant(type="generic", text=f"```\n{out}\n```")
        return

    if 종류 in ("길이", "다시"):
        if not text:
            append_assistant_text("다시 쓸 글이 아직 없어요. 먼저 공지나 쿠폰·홍보글을 만들어 주세요.")
            return
        instruction = "다른 표현으로" if 종류 == "다시" else ("더 짧게" if followup["방향"] == "짧게" else "더 길게")
        with st.spinner("다시 쓰는 중..."):
            new_text, err = assistant.rewrite_text(CLOVA_KEY, text, instruction)
        if err:
            append_assistant_text(friendly_error(err))
            return
        last["글"] = new_text
        append_assistant_text("이렇게 다시 써 봤어요.")
        append_assistant(type="generic", text=new_text)
        return

    if 종류 == "수정":
        merged = assistant.resolve_pending_message({"요청문구": last.get("요청문구")}, followup["문구"])
        _run_assistant_and_render(merged)
        return


def _run_assistant_and_render(user_text):
    conv = st.session_state.conv
    ctx = st.session_state.chat_context
    ctx["요약"] = assistant.build_situation_summary(conv["store"], conv.get("last"), conv.get("pending"))
    ctx["최근턴"] = _recent_turns()
    with st.spinner("생각하는 중..."):
        try:
            result = assistant.handle(user_text, conv["store"], ctx, CLOVA_KEY)
        except Exception as exc:
            append_assistant_text(friendly_error(exc))
            return
    tool = result.get("도구")
    cards = result.get("카드", [])

    if tool == "note_store_info":
        append_assistant(type="generic", text=format_cards(cards))
        refresh_home_card()
        conv["last"] = {"기능": tool, "요약": cards[0]["내용"] if cards else "가게 정보 업데이트",
                         "요청문구": user_text, "글": None}
        conv["pending"] = None
        return

    if tool == "make_coupon":
        _, args = assistant._parse_tool_calls(result.get("원문") or {})
        args = dict(args or {})
        defaulted = False
        if not args.get("수량"):
            args["수량"] = 100
            defaulted = True
        if not args.get("기간_일"):
            args["기간_일"] = 30
            defaulted = True
        if args.get("혜택") and args.get("메뉴"):
            coupon_result = coupon.build_coupon(args, conv["store"], TODAY)
            append_assistant_text(f"{coupon_result['입력값']['쿠폰 이름']} 쿠폰을 준비했어요.")
            append_assistant(type="coupon_result", result=coupon_result, defaulted=defaulted, choice=args)
            conv["last"] = {"기능": tool, "요약": f"쿠폰 {coupon_result['입력값']['쿠폰 이름']}",
                             "요청문구": user_text, "글": None}
            conv["pending"] = None
        else:
            append_assistant(type="generic", text=format_cards(cards))
            conv["pending"] = assistant.extract_pending(tool, cards, user_text)
        return

    if tool == "make_notice":
        if cards and cards[0].get("단계"):
            _apply_notice_step(cards[0]["단계"], user_text)
        else:
            append_assistant(type="generic", text=format_cards(cards))
        return

    # check_store_profile · get_weekly_suggestions · plan_events · 범위 밖 안내
    append_assistant(type="generic", text=format_cards(cards))
    conv["pending"] = assistant.extract_pending(tool, cards, user_text)
    if not conv["pending"]:
        conv["last"] = None


def start_event_list_flow():
    append_user("근처에 나갈 만한 행사 있어?")
    join, near = event_plan.match(STORE, EVENTS, TODAY)
    options = [("참여형", e) for e in join] + [("주변형", e) for e in near]
    if not options:
        append_assistant_text("지금은 추천할 행사가 없어요.")
        return
    append_assistant_text(f"{STORE['이름']}에 맞는 행사를 찾았어요. 하나를 고르면 준비 계획을 만들어 드려요.")
    append_assistant(type="event_list", options=options)


# ── 메시지 렌더링 ───────────────────────────────────────────
def render_notice_info_rows(info):
    s, e = info["시작"], info["종료"]
    rows = [("종류", info["종류"])]
    if s:
        rows.append(("날짜", D.fmt(s) if (not e or s == e) else f"{D.fmt(s)} ~ {D.fmt(e)}"))
        if info["종류"] == "임시휴무" and e:
            rows.append(("다시 여는 날", D.fmt(notice.next_open_day(e))))
    if info.get("여는") or info.get("닫는"):
        rows.append(("시간", f"{info.get('여는') or '-'} ~ {info.get('닫는') or '-'}"))
    if info.get("정기휴무"):
        rows.append(("정기휴무", f"매주 {info['정기휴무']}요일"))
    rows.append(("사유", info.get("사유") or "-"))
    return rows


def bubble(text):
    st.markdown(f"<div class='bubble'>{text}</div>", unsafe_allow_html=True)


def render_message(i, msg):
    role = msg["role"]
    avatar = "🙂" if role == "user" else "✨"
    with st.chat_message(role, avatar=avatar):
        mtype = msg.get("type", "text")

        if mtype == "text":
            if role == "assistant":
                bubble(msg["text"])
            else:
                st.markdown(msg["text"])

        elif mtype == "home":
            bubble(msg["text"])
            hidden = st.session_state.get("hidden_cards", set())
            for j, c in enumerate(msg["cards"]):
                cid = f"{i}_{j}"
                if cid in hidden:
                    continue
                with st.container(border=True):
                    st.markdown(f"<span class='tag'>{c['tag']}</span>", unsafe_allow_html=True)
                    st.markdown(f"<span class='card-title'>{c['제목']}</span>", unsafe_allow_html=True)
                    if c.get("근거"):
                        st.caption(c["근거"])
                if c.get("action"):
                    bcol1, bcol2, _ = st.columns([2, 2, 5], gap="small")
                    with bcol1:
                        if st.button(c["action_label"], key=f"home_{cid}", type="primary", use_container_width=True):
                            if c["action"] == "store_profile":
                                start_store_profile_flow()
                            else:
                                start_event_plan(c["mode"], c["event"])
                            st.rerun()
                    with bcol2:
                        if st.button("나중에", key=f"later_{cid}", use_container_width=True):
                            st.session_state.setdefault("hidden_cards", set()).add(cid)
                            st.rerun()

        elif mtype == "event_list":
            for j, (mode, e) in enumerate(msg["options"]):
                with st.container(border=True):
                    tag = "셀러로 나가기" if mode == "참여형" else "근처 손님 맞이"
                    extra = e["유형"]
                    st.markdown(
                        f"<span class='tag'>{tag}</span> <span class='tag'>{extra}</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(f"<span class='card-title'>{e['이름']}</span>", unsafe_allow_html=True)
                    where = "서울 전체에서 찾음" if mode == "참여형" else f"도보 약 {e['도보']}분"
                    st.caption(f"{event_plan.period(e)} · {where}")
                    label = "이 행사로 계획 보기" if mode == "참여형" else "이 행사로 홍보글 보기"
                    if st.button(label, key=f"evlist_{i}_{j}"):
                        start_event_plan(mode, e)
                        st.rerun()

        elif mtype == "event_plan":
            plan = msg["plan"]
            if "오류" in plan:
                st.error(plan["오류"])
            else:
                with st.container(border=True):
                    st.markdown(f"**{plan['행사']}** · {plan['유형']} · {plan['기간']} · {_mode_words(plan['거리'])}")
                    st.success(f"이 행사가 맞는 이유 · {plan['맞는 이유']}")
                    if plan.get("확인 필요"):
                        warn_box(f"확인 필요 · {plan['확인 필요']}")
                    for pt, cite in zip(plan.get("어필_포인트") or [], plan.get("근거") or []):
                        st.write("• " + pt)
                        st.caption(f"이전 리뷰: {cite}")
                    ideas = plan.get("행사 맞춤 아이디어") or []
                    if ideas:
                        st.markdown("**이 행사에서 해 볼 것**")
                        for idea in ideas:
                            st.write("- " + idea)
                    todo = plan.get("할 일") or []
                    if todo:
                        st.markdown("**할 일**")
                        for d, tasks in _merge_todo_by_date(todo):
                            st.write(f"**{d}**  ·  {tasks}")
                    if plan.get("일정 메모"):
                        st.caption(plan["일정 메모"])
                    posts = plan.get("홍보글_후보")
                    draft = plan.get("홍보글_초안")
                    if posts:
                        st.markdown("**홍보글 후보**")
                        for pi, p in enumerate(posts):
                            st.markdown(f"후보 {pi + 1}")
                            ckey = f"channel_{i}_{pi}"
                            if hasattr(st, "segmented_control"):
                                channel = st.segmented_control(
                                    "채널", CHANNELS, key=ckey, default=CHANNELS[0], required=True,
                                )
                            else:
                                channel = st.radio("채널", CHANNELS, key=ckey, horizontal=True)
                            formatted = format_for_channel(channel or CHANNELS[0], p, STORE, PROFILE_STORE)
                            st.markdown(f"<div class='post-box'>{html.escape(formatted)}</div>", unsafe_allow_html=True)
                            with st.expander("복사용"):
                                st.code(formatted, language=None)
                    elif plan.get("홍보글_점검_실패"):
                        warn_box(_friendly_post_fail_reasons(plan["홍보글_점검_실패"]))
                        if draft:
                            st.markdown("후보 (사장님 확인 필요)")
                            ckey = f"channel_{i}_draft"
                            if hasattr(st, "segmented_control"):
                                channel = st.segmented_control(
                                    "채널", CHANNELS, key=ckey, default=CHANNELS[0], required=True,
                                )
                            else:
                                channel = st.radio("채널", CHANNELS, key=ckey, horizontal=True)
                            formatted = format_for_channel(channel or CHANNELS[0], draft, STORE, PROFILE_STORE)
                            st.markdown(f"<div class='post-box'>{html.escape(formatted)}</div>", unsafe_allow_html=True)
                            with st.expander("복사용"):
                                st.code(formatted, language=None)
                            st.caption("고쳐서 쓰시거나 \"다시 써 줘\"라고 말해 주세요.")
                if posts or draft:
                    st.caption("마음에 드는 글을 복사해서 가게 소식에 올려 보세요.")
                else:
                    st.caption("할 일 날짜를 달력에 적어 두세요.")

        elif mtype == "notice_warn":
            warn_box(msg["issues"])

        elif mtype == "notice_confirm":
            info = msg["info"]
            origin = msg.get("origin", "")
            with st.container(border=True):
                for k, v in render_notice_info_rows(info):
                    st.markdown(f"**{k}**　{v}")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("맞아요", key=f"notice_ok_{i}", type="primary", use_container_width=True):
                    append_user("맞아요")
                    finish_notice_flow(info, origin)
                    st.rerun()
            with c2:
                if st.button("날짜 고칠게요", key=f"notice_fix_{i}", use_container_width=True):
                    append_user("날짜 고칠게요")
                    ask_other_date()
                    st.rerun()

        elif mtype == "notice_pick":
            records = msg["records"]
            origin = msg.get("요청문구", "")
            with st.container(border=True):
                if len(records) == 1:
                    r = records[0]
                    label = D.fmt(D.parse_d(r["날짜"])) + (f" · {r['사유']}" if r.get("사유") else "")
                    st.markdown(f"**{label}**")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("네", key=f"pick_yes_{i}", type="primary", use_container_width=True):
                            append_user("네")
                            finish_notice_flow(assistant.notice_info_for_date(r["날짜"], r.get("사유", "")), origin)
                            st.rerun()
                    with c2:
                        if st.button("다른 날짜", key=f"pick_other_{i}", use_container_width=True):
                            append_user("다른 날짜")
                            ask_other_date()
                            st.rerun()
                else:
                    for ri, r in enumerate(records):
                        label = D.fmt(D.parse_d(r["날짜"])) + (f" · {r['사유']}" if r.get("사유") else "")
                        if st.button(label, key=f"pick_{i}_{ri}", use_container_width=True):
                            append_user(label)
                            finish_notice_flow(assistant.notice_info_for_date(r["날짜"], r.get("사유", "")), origin)
                            st.rerun()
                    if st.button("모두 한 번에", key=f"pick_all_{i}", use_container_width=True):
                        append_user("모두 한 번에")
                        finish_combined_notice(records, origin)
                        st.rerun()

        elif mtype == "notice_result":
            with st.container(border=True):
                for k, v in msg["입력값"].items():
                    st.markdown(f"**{k}**　{_fmt_notice_value(v)}")
            nckey = f"notice_channel_{i}"
            if hasattr(st, "segmented_control"):
                n_channel = st.segmented_control(
                    "채널", CHANNELS, key=nckey, default=CHANNELS[0], required=True,
                )
            else:
                n_channel = st.radio("채널", CHANNELS, key=nckey, horizontal=True)
            n_formatted = format_notice_for_channel(n_channel or CHANNELS[0], msg["문구"], STORE, PROFILE_STORE)
            st.markdown(f"<div class='post-box'>{html.escape(n_formatted)}</div>", unsafe_allow_html=True)

        elif mtype == "store_profile_result":
            result = msg["result"]
            with st.container(border=True):
                st.markdown("<span class='card-title'>가게 정보 점검</span>", unsafe_allow_html=True)
                st.progress(result["채움_비율"])
                st.caption(f"{result['채움_비율']:.0%} 채워졌어요")
                if result["다 채움"]:
                    st.success("가게 정보가 다 채워져 있어요!")
                else:
                    for b in result["빈칸"]:
                        st.write(f"{b['이름']} — {b['안내']}")
                    outro = store_profile_outro(result)
                    if outro:
                        st.caption(outro)

        elif mtype == "coupon_result":
            res = msg["result"]
            choice = msg.get("choice", {})
            with st.container(border=True):
                for k, v in res["입력값"].items():
                    if k == "혜택":
                        v_text = _benefit_display(choice)
                    elif isinstance(v, (list, tuple)):
                        v_text = ", ".join(v) if v else "없음"
                    else:
                        v_text = v
                    st.markdown(f"**{k}**　{v_text}")
            if msg.get("defaulted"):
                st.caption("수량·기간은 말로 바꿀 수 있어요")
            warn_box(res["확인 필요"])
            with st.container(border=True):
                st.markdown("**처음이면 이렇게 해 보세요**")
                st.markdown("① 스마트플레이스 로그인 → ② 쿠폰 메뉴(화면에서 이름 확인) → ③ 위 값 그대로 입력")
                _links = [f"[네이버 스마트플레이스 열기]({SMARTPLACE_URL})"]
                if COUPON_HELP_URL:
                    _links.append(f"[쿠폰 만드는 방법 보기]({COUPON_HELP_URL})")
                st.markdown(" · ".join(_links))

        elif mtype == "generic":
            st.markdown(msg["text"])


if MISSING_FILES:
    st.info("행사 데이터 파일이 없어요: " + ", ".join(MISSING_FILES))

with st.container(border=True, key="chatbox"):
    for i, msg in enumerate(st.session_state.chat):
        render_message(i, msg)

    QUICK = [
        ("행사 추천", "event"),
        ("휴무·영업시간 공지", "notice"),
        ("단골 쿠폰", "coupon"),
        ("가게 정보 점검", "profile"),
    ]
    QUICK_BY_LABEL = dict(QUICK)

    quick_clicked = None
    if hasattr(st, "pills"):
        if st.session_state.pop("_reset_quick_pills", False):
            st.session_state["quick_pills"] = None
        picked = st.pills("빠른 실행", [l for l, _ in QUICK], key="quick_pills", label_visibility="collapsed")
        if picked:
            quick_clicked = QUICK_BY_LABEL[picked]
            st.session_state["_reset_quick_pills"] = True
    else:
        cols = st.columns(len(QUICK))
        for col, (label, action) in zip(cols, QUICK):
            if col.button(label, key=f"quick_{action}"):
                quick_clicked = action

    if quick_clicked == "event":
        start_event_list_flow()
        st.rerun()
    elif quick_clicked == "notice":
        process_free_message("다음 주 화요일 개인 사정으로 쉬어요")
        st.rerun()
    elif quick_clicked == "coupon":
        process_free_message("아메리카노 500원 할인 쿠폰 만들어 줘")
        st.rerun()
    elif quick_clicked == "profile":
        start_store_profile_flow()
        st.rerun()

    typed = st.chat_input("예: 다음 주 화요일 쉬는데 공지 써 줘")
    if typed:
        process_free_message(typed)
        st.rerun()


# ── 맨 아래 ──────────────────────────────────────────────────
st.caption("가게·리뷰는 합성 데이터 · 행사: 서울시 문화행사 정보, 한국관광공사 TourAPI")
