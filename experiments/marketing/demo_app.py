"""회의 데모용 Streamlit 앱. 대화창 하나로 기능을 보여 준다. features/ 의 기능을 그대로 불러와 쓴다.

실행: streamlit run demo_app.py
"""

import os
from datetime import date

import streamlit as st

import config
from common import dates as D
from common import korean as K
from features import assistant, coupon, event_plan, notice, store_profile, tone, weekly
from samples.stores import STORES

TOOL_LABELS = {
    "check_store_profile": "가게 정보 점검",
    "note_store_info": "가게 정보 정리",
    "get_weekly_suggestions": "이번 주 추천",
    "plan_events": "행사 계획",
    "make_notice": "휴무 공지",
    "make_coupon": "쿠폰 만들기",
}

NO_KEY_MESSAGE = "AI 연결 키가 아직 설정되지 않았어요. 키 없이도 쿠폰 만들기는 바로 할 수 있어요."

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


# ── CLOVA 키 (그대로) ──────────────────────────────────────────
ENV_KEY = os.environ.get("CLOVA_API_KEY")
if ENV_KEY:
    CLOVA_KEY = ENV_KEY
else:
    CLOVA_KEY = st.sidebar.text_input("CLOVA API 키", type="password") or None
KEY_AVAILABLE = bool(CLOVA_KEY)
if not KEY_AVAILABLE:
    st.sidebar.caption("CLOVA 키를 입력해 주세요.")


# ── 맨 위: 제목 + 가게·기준일 ───────────────────────────────────
col_title, col_store, col_date = st.columns([3, 2, 1.4])
with col_title:
    st.markdown("<div class='app-title'>마케팅 비서</div>", unsafe_allow_html=True)
with col_store:
    store_idx = st.selectbox(
        "예시 가게", options=list(range(len(STORES))),
        format_func=lambda i: f"{STORES[i]['이름']} ({STORES[i]['업종']})",
    )
with col_date:
    TODAY = st.date_input("기준일", value=date.today())

STORE = STORES[store_idx]
PROFILE_STORE = to_profile_store(STORE)


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


def store_profile_intro(result):
    if result["다 채움"]:
        return "가게 정보를 살펴봤어요. 다 채워져 있어요!"
    blanks = result["빈칸"]
    pct = f"{result['채움_비율']:.0%}"
    first = blanks[0]["이름"]
    if len(blanks) == 1:
        return f"가게 정보를 살펴봤어요. 거의 다 채워져 있어요(채움 {pct}). 딱 하나, {first}{K.i_ga(first)} 비어 있어요."
    return f"가게 정보를 살펴봤어요. 채움 비율은 {pct}예요. {first} 등 {len(blanks)}개 항목이 비어 있어요."


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


def format_cards(cards):
    parts = []
    for c in cards:
        block = f"**{c.get('제목', '')}**"
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


def build_home():
    st.session_state.chat = []
    st.session_state.hidden_cards = set()
    weekly_cards = weekly.get_weekly_suggestions(PROFILE_STORE, EVENTS, TODAY)
    join, near = event_plan.match(STORE, EVENTS, TODAY)

    if len(weekly_cards) == 1 and weekly_cards[0]["종류"] == "없음":
        append_assistant(type="home", text="안녕하세요, 사장님! 이번 주는 특별히 급한 일이 없어요.", cards=[])
        return

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

    append_assistant(
        type="home", text="안녕하세요, 사장님! 이번 주에 이걸 해 보는 건 어때요?", cards=home_cards,
    )


if "chat" not in st.session_state or st.session_state.get("_prev_store_idx") != store_idx:
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
    append_assistant(type="event_plan", plan=plan)


# ── 휴무 공지 (2단계: 이해한 값 확인 → 결과) ──────────────────────
def start_notice_flow(user_text):
    append_user(user_text)
    if not KEY_AVAILABLE:
        append_assistant_text(NO_KEY_MESSAGE)
        return
    with st.spinner("공지를 이해하는 중..."):
        try:
            ext, tries, total, err = notice.extract_b(CLOVA_KEY, user_text)
        except Exception as exc:
            append_assistant_text(friendly_error(exc))
            return
    if err:
        append_assistant_text(friendly_error(err))
        return
    info = notice.to_info_b(ext, TODAY, user_text)
    if info.get("확인필요"):
        append_assistant_text("말씀하신 내용을 이렇게 이해했는데, 몇 가지 확인이 필요해요.")
        append_assistant(type="notice_warn", issues=info["확인필요"])
    else:
        append_assistant_text("이렇게 이해했어요. 날짜는 코드가 달력으로 계산했으니, 맞는지 한 번만 확인해 주세요.")
        append_assistant(type="notice_confirm", info=info)


def finish_notice_flow(info):
    append_user("맞아요")
    built = notice.build_notice(info)
    append_assistant_text(notice_intro(info))
    append_assistant(
        type="notice_result", 입력값=built["스마트플레이스_입력값"], 문구=built["소식_문구"],
    )


# ── 가게 정보 점검 ───────────────────────────────────────────
def start_store_profile_flow():
    append_user("가게 정보 뭐 빠졌어?")
    result = store_profile.check_store_profile(PROFILE_STORE)
    append_assistant_text(store_profile_intro(result))
    append_assistant(type="store_profile_result", result=result)
    outro = store_profile_outro(result)
    if outro:
        append_assistant_text(outro)


# ── 자유 입력 (쿠폰 포함, assistant 경로 그대로) ───────────────────
def process_free_message(user_text):
    append_user(user_text)
    if not KEY_AVAILABLE:
        append_assistant_text(NO_KEY_MESSAGE)
        return
    with st.spinner("생각하는 중..."):
        try:
            result = assistant.handle(user_text, PROFILE_STORE, st.session_state.chat_context, CLOVA_KEY)
        except Exception as exc:
            append_assistant_text(friendly_error(exc))
            return
    tool = result.get("도구")
    cards = result.get("카드", [])
    tool_line = f"실행한 기능: {TOOL_LABELS.get(tool, tool)}" if tool else "기능 실행 없음"
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
            coupon_result = coupon.build_coupon(args, PROFILE_STORE, TODAY)
            append_assistant_text(f"{coupon_result['입력값']['쿠폰 이름']} 쿠폰을 준비했어요.")
            append_assistant(type="coupon_result", result=coupon_result, defaulted=defaulted)
        else:
            append_assistant(type="generic", text=format_cards(cards), tool_line=tool_line)
    else:
        append_assistant(type="generic", text=format_cards(cards), tool_line=tool_line)


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
                    st.markdown(f"**{plan['행사']}** · {plan['유형']} · {plan['기간']} · {plan['거리']}")
                    st.success(f"맞는 이유 · {plan['맞는 이유']}")
                    if plan.get("확인 필요"):
                        st.warning(f"확인 필요 · {plan['확인 필요']}")
                    for pt, cite in zip(plan.get("어필_포인트") or [], plan.get("근거") or []):
                        st.write("• " + pt)
                        st.caption(f"근거: {cite}")
                    ideas = plan.get("행사 맞춤 아이디어") or []
                    if ideas:
                        st.markdown("**이 행사에서 해 볼 것**")
                        for idea in ideas:
                            st.write("- " + idea)
                    todo = plan.get("할 일") or []
                    if todo:
                        st.markdown("**할 일**")
                        for t in todo:
                            st.write(f"**{t['날짜']}**  ·  {t['할 일']}")
                    if plan.get("일정 메모"):
                        st.caption(plan["일정 메모"])
                    posts = plan.get("홍보글_후보")
                    if posts:
                        st.markdown("**홍보글 후보**")
                        for p in posts:
                            st.code(p, language=None)
                    elif plan.get("홍보글_점검_실패"):
                        st.warning("사장님 확인 필요")
                if posts:
                    st.caption("마음에 드는 글을 복사해서 가게 소식에 올려 보세요.")
                else:
                    st.caption("할 일 날짜를 달력에 적어 두세요.")
                st.caption(f"실행한 기능: {TOOL_LABELS['plan_events']}")

        elif mtype == "notice_warn":
            st.warning("\n".join(msg["issues"]))

        elif mtype == "notice_confirm":
            info = msg["info"]
            with st.container(border=True):
                for k, v in render_notice_info_rows(info):
                    st.markdown(f"**{k}**　{v}")
            if st.button("맞아요", key=f"notice_ok_{i}"):
                finish_notice_flow(info)
                st.rerun()

        elif mtype == "notice_result":
            with st.container(border=True):
                for k, v in msg["입력값"].items():
                    st.markdown(f"**{k}**　{v}")
            st.code(msg["문구"])
            st.caption("손님이 헛걸음하지 않게 하루 전에 올리는 걸 추천해요.")
            st.caption(f"실행한 기능: {TOOL_LABELS['make_notice']}")

        elif mtype == "store_profile_result":
            result = msg["result"]
            with st.container(border=True):
                st.markdown(f"**가게 정보 점검** · 채움 비율 {result['채움_비율']:.0%}")
                if result["다 채움"]:
                    st.success("가게 정보가 다 채워져 있어요!")
                else:
                    for b in result["빈칸"]:
                        st.write(f"- {b['이름']}: {b['안내']}")
            st.caption(f"실행한 기능: {TOOL_LABELS['check_store_profile']}")

        elif mtype == "coupon_result":
            res = msg["result"]
            with st.container(border=True):
                for k, v in res["입력값"].items():
                    v_text = ", ".join(v) if isinstance(v, (list, tuple)) else v
                    st.markdown(f"**{k}**　{v_text}")
            if msg.get("defaulted"):
                st.caption("수량·기간은 말로 바꿀 수 있어요")
            if res["확인 필요"]:
                st.warning("\n".join(res["확인 필요"]))
            st.info("스마트플레이스 쿠폰 메뉴에서 위 값을 그대로 넣으면 돼요. 처음이면 수량은 적게 시작해 보세요.")
            st.caption(f"실행한 기능: {TOOL_LABELS['make_coupon']}")

        elif mtype == "generic":
            st.markdown(msg["text"])
            if msg.get("tool_line"):
                st.caption(msg["tool_line"])


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
        start_notice_flow("다음 주 화요일 개인 사정으로 쉬어요")
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
