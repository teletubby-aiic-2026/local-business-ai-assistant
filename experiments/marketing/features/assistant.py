"""
사장님 메시지 → 알맞은 마케팅 도구 선택 → 실행 → 카드 반환

HyperCLOVA X (HCX-005) function calling 으로 도구를 고르고,
실행 결과를 카드로 돌려준다.
"""

import json
from datetime import date

import clova
from features import store_profile, weekly, event_plan, notice, coupon

MODEL = "HCX-005"

SYSTEM = """너는 동네 가게 사장님의 마케팅 도우미다.
사장님이 하는 말을 듣고 알맞은 도구를 골라 실행한다.
도구가 맞으면 바로 호출하고, 범위 밖이면 도구를 호출하지 않고 한 줄로 안내한다.
날짜·숫자는 직접 계산하지 말고, 도구에 맡긴다."""

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
        result = notice.build_notice(info)
        cards = [{"종류": "공지", "제목": f"{info['종류']} 공지",
                  "내용": result["소식_문구"], "입력값": result["스마트플레이스_입력값"], "버튼": "notice"}]
        if info.get("확인필요"):
            cards[0]["확인필요"] = info["확인필요"]
        return cards

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
    return [{"종류": "안내", "제목": "이런 것들을 도와드릴 수 있어요",
             "내용": "· 가게 정보 점검\n· 이번 주 추천\n· 근처 행사 계획\n· 휴무·영업시간 공지\n· 쿠폰 만들기",
             "버튼": ""}]


def handle(message, store, context, key):
    msgs = [{"role": "user", "content": message}]
    r = clova.call(key, SYSTEM, msgs, model=MODEL, temperature=0.1, max_tokens=1024,
                   tools=TOOLS, tool_choice="auto")
    if "error" in r:
        detail = str(r["error"])[:300]
        return {"카드": [{"종류": "오류", "제목": "다시 시도해 주세요", "내용": r["error"], "오류_상세": detail}],
                "도구": None, "원문": r}

    name, args = _parse_tool_calls(r)

    if name is None:
        cards = _out_of_scope(message)
        return {"카드": cards, "도구": None, "원문": r}

    context["_message"] = message
    try:
        cards = _run_tool(name, args or {}, store, context, key)
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
