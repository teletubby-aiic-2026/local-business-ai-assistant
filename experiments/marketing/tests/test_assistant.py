"""
사장님 메시지 → 도구 선택 테스트

실행 (mock, API 없음):  python -m tests.test_assistant --mock
실행 (실제 HCX-005):    python -m tests.test_assistant
결과: results/assistant_results.md
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from features import assistant as A

# ── 테스트용 가게 ────────────────────────────────────────────────
STORE = {
    "이름": "몽글커피",
    "업종": "카페",
    "메뉴": [("몽글 크림라떼", 5500), ("아메리카노", 4500), ("휘낭시에", 4000)],
    "영업시간": "09:00~21:00",
    "휴무일": "월요일",
    "전화번호": "02-1234-5678",
    "주소": "서울시 성동구 성수동",
    "가게 소개": "성수동 작은 카페",
    "대표 사진": "photo.jpg",
    "포장": "가능",
    "배달": "",
    "주차": "불가",
    "예약 가능": "가능",
    "편의시설": "와이파이",
    "위도": 37.5445,
    "경도": 127.0567,
    "예전 글": [
        "오늘은 비가 와서 그런지 따뜻한 라떼가 많이 나가네용 ☕",
        "휘낭시에 새로 구웠어요 🥐 버터 향 가득이에요!",
    ],
}

CONTEXT = {
    "today": None,  # 실행 시 date.today() 사용
    "events": [],
    "complaints": None,
}

# ── 15개 테스트 케이스: (사장님 말, 정답 도구, mock용 args) ──────
CASES = [
    # check_store_profile (2개)
    ("가게 정보 뭐 빠졌어?", "check_store_profile", {}),
    ("프로필 점검 좀 해줘", "check_store_profile", {}),

    # get_weekly_suggestions (2개)
    ("이번 주에 뭐 하면 좋아?", "get_weekly_suggestions", {}),
    ("할 일 좀 알려줘", "get_weekly_suggestions", {}),

    # plan_events (2개)
    ("근처 행사 있어?", "plan_events", {}),
    ("광화문 마켓 같은 데 나가 볼까", "plan_events", {}),

    # make_notice (3개)
    ("다음 주 화요일 쉬는데 공지 좀 써 줘", "make_notice", {"notice_text": "다음 주 화요일 쉬는데 공지 좀 써 줘"}),
    ("모레 오후 2시에 문 열어", "make_notice", {"notice_text": "모레 오후 2시에 문 열어"}),
    ("이번 주 금요일 쉬는 날이야", "make_notice", {"notice_text": "이번 주 금요일 쉬는 날이야"}),

    # make_coupon (3개)
    ("단골 쿠폰 만들고 싶은데", "make_coupon", {}),
    ("아메리카노 500원 할인 쿠폰 만들어 줘", "make_coupon", {"혜택": "금액 할인", "메뉴": "아메리카노", "값": 500}),
    ("10% 할인 쿠폰 만들어 줘", "make_coupon", {"혜택": "비율 할인", "메뉴": "전 메뉴", "값": 10}),

    # 범위 밖 (3개)
    ("우리 동네 상권 어때?", None, None),
    ("오늘 날씨 어때", None, None),
    ("재고 관리 좀 해줘", None, None),
]


def _pick_cases():
    if "--one" in sys.argv:
        return CASES[:1]
    return CASES


def _error_detail(r):
    if r["카드"]:
        return r["카드"][0].get("오류_상세", "")
    return ""


def run_mock():
    cases = _pick_cases()
    results = []
    ok, total = 0, len(cases)
    for msg, expected, mock_args in cases:
        mock_name = expected
        r = A.handle_mock(msg, STORE, CONTEXT, mock_name, mock_args)
        got = r["도구"]
        match = got == expected
        if match:
            ok += 1
        card_title = r["카드"][0]["제목"] if r["카드"] else "(카드 없음)"
        status = "✅" if match else "❌"
        results.append({
            "메시지": msg, "정답": expected, "결과": got,
            "일치": match, "카드제목": card_title, "status": status,
            "오류_상세": _error_detail(r),
        })
    return results, ok, total


def run_live(key):
    cases = _pick_cases()
    results = []
    ok, total = 0, len(cases)
    for msg, expected, _ in cases:
        r = A.handle(msg, STORE, CONTEXT, key)
        got = r["도구"]
        match = got == expected
        if match:
            ok += 1
        card_title = r["카드"][0]["제목"] if r["카드"] else "(카드 없음)"
        status = "✅" if match else "❌"
        results.append({
            "메시지": msg, "정답": expected, "결과": got,
            "일치": match, "카드제목": card_title, "status": status,
            "오류_상세": _error_detail(r),
        })
    return results, ok, total


def build_md(results, ok, total, mode):
    lines = [
        "# 사장님 도우미 도구 선택 테스트 결과", "",
        f"모드: {mode} · 정답률: **{ok}/{total}** ({ok/total:.0%})", "",
        "| # | 사장님 말 | 정답 도구 | 선택 도구 | 카드 제목 | 오류_상세 | |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        detail = r.get("오류_상세", "")
        lines.append(
            f"| {i} | {r['메시지']} | {r['정답'] or '(없음)'} | {r['결과'] or '(없음)'} "
            f"| {r['카드제목']} | {detail} | {r['status']} |"
        )
    lines += ["", f"> 총 {total}건 중 {ok}건 일치"]
    return "\n".join(lines)


def main():
    mode = "--mock" if "--mock" in sys.argv else "live"

    if mode == "--mock":
        results, ok, total = run_mock()
    else:
        key = config.get_api_key()
        results, ok, total = run_live(key)

    md = build_md(results, ok, total, mode)

    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.RESULTS_DIR / "assistant_results.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)

    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print(md)
    print(f"\n결과 파일: {path}")

    if mode == "--mock" and ok < total:
        print(f"\n⚠️ mock 모드에서 {total - ok}건 불일치 (mock은 정답을 그대로 쓰므로 실행 흐름 오류)")
        return False
    return True


if __name__ == "__main__":
    success = main()
    if not success:
        sys.exit(1)
