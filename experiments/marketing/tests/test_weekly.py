"""
S3 이번 주 추천 카드 테스트 (AI 호출 없음)

가게 4곳(tests/test_event_plan.py 의 STORES 재사용)에 가게 정보 빈칸을 하나씩 일부러 만들고,
불만 리뷰도 한 가게에만 넣어 get_weekly_suggestions 가 올바른 카드를 뽑는지 확인한다.

행사 데이터는 data/events_raw.json · data/tour_festivals_raw.json 을 load_events 로 읽는다.
(파일이 없으면 빈 목록으로 진행 → 그 경우 행사 카드는 안 나올 수 있다)

실행 (marketing 폴더에서)
  python -m tests.test_weekly

결과 파일: results/weekly_results.md
※ 가게·리뷰는 모두 테스트용 합성 데이터입니다.
"""

import json
from datetime import date, timedelta

import config
from features import event_plan as P
from features.weekly import get_weekly_suggestions
from tests.test_event_plan import STORES as EVENT_STORES

TODAY = date.today()

# ── EVENT_STORES(이름·업종·위도·경도)에 가게 정보 항목을 채워 넣고, 가게마다 하나씩 빈칸을 남긴다 ──
STORES = [
    dict(EVENT_STORES[0], **{  # 몽글커피: 영업시간 빈칸
        "영업시간": None, "휴무일": ["월"], "전화번호": "02-1234-5678",
        "메뉴": [("아메리카노", "4,500원"), ("휘낭시에", "4,000원"), ("라떼", "5,000원")],
        "주소": "서울 성동구 성수동", "가게 소개": "아늑한 동네 카페예요.",
        "대표 사진": ["photo1.jpg"], "포장": "가능", "배달": "불가",
        "주차": "없음", "예약 가능": "가능", "편의시설": ["Wi-Fi"],
    }),
    dict(EVENT_STORES[1], **{  # 성수 숯불집: 전화번호 빈칸
        "영업시간": "17:00~24:00", "휴무일": ["일"], "전화번호": None,
        "메뉴": [("돼지 목살", "12,000원"), ("된장찌개", "8,000원"), ("냉면", "9,000원")],
        "주소": "서울 성동구 성수동", "가게 소개": "숯불로 구운 목살 전문점이에요.",
        "대표 사진": ["photo2.jpg"], "포장": "불가", "배달": "불가",
        "주차": "있음", "예약 가능": "가능", "편의시설": ["화장실"],
    }),
    dict(EVENT_STORES[2], **{  # 떡볶이 연구소: 주소 빈칸
        "영업시간": "11:00~21:00", "휴무일": ["화"], "전화번호": "02-1111-2222",
        "메뉴": [("국물떡볶이", "4,000원"), ("김말이", "3,000원"), ("순대", "4,000원")],
        "주소": None, "가게 소개": "국물떡볶이 전문점이에요.",
        "대표 사진": ["photo3.jpg"], "포장": "가능", "배달": "가능",
        "주차": "없음", "예약 가능": "불가", "편의시설": [],
    }),
    dict(EVENT_STORES[3], **{  # 오늘의 옷장: 메뉴(상품) 가격 빈칸
        "영업시간": "12:00~20:00", "휴무일": ["수"], "전화번호": "02-3333-4444",
        "메뉴": [("빈티지 니트", "35,000원"), ("데님 자켓", ""), ("가죽 가방", "68,000원")],
        "주소": "서울 성동구 성수동", "가게 소개": "빈티지 옷가게예요.",
        "대표 사진": ["photo4.jpg"], "포장": "불가", "배달": "불가",
        "주차": "없음", "예약 가능": "불가", "편의시설": [],
    }),
]

# ── 가짜 불만 리뷰 (고객 응대 파트 연동 전 테스트용) : 성수 숯불집에만 2건 ──
COMPLAINTS = [
    {"가게": "성수 숯불집", "날짜": TODAY - timedelta(days=2), "내용": "주문한 메뉴가 늦게 나왔어요"},
    {"가게": "성수 숯불집", "날짜": TODAY - timedelta(days=5), "내용": "자리가 너무 좁았어요"},
    {"가게": "성수 숯불집", "날짜": TODAY - timedelta(days=20), "내용": "오래된 불만 (기간 밖, 안 세어야 함)"},
]


def load(name):
    path = config.DATA_DIR / name
    if not path.exists():
        print(f"※ {path} 가 없어요. 이 데이터는 빼고 진행해요.")
        return []
    return json.load(open(path, encoding="utf-8"))


def main():
    seoul, tour = load("events_raw.json"), load("tour_festivals_raw.json")
    events = P.load_events(seoul, tour, TODAY)
    print(f"행사 {len(events)}건 로드")

    rows = []
    for s in STORES:
        cards = get_weekly_suggestions(s, events, TODAY, complaints=COMPLAINTS)
        종류들 = [c["종류"] for c in cards]
        assert len(cards) <= 3, "카드는 최대 3개"
        assert len(종류들) == len(set(종류들)), "같은 종류는 1개만 나와야 함"
        urgencies = [c["급한 정도"] for c in cards]
        assert urgencies == sorted(urgencies, reverse=True), "급한 정도 내림차순이어야 함"
        print(f"\n[{s['이름']}] 카드 {len(cards)}개")
        for c in cards:
            print(f"  [{c['종류']}] {c['제목']} (급한 정도 {c['급한 정도']}) → {c['버튼']}")
        rows.append((s, cards))

    # 성수 숯불집은 불만 리뷰 2건(기간 밖 1건 제외)이 들어가 있어야 함
    suk = next(cards for s, cards in rows if s["이름"] == "성수 숯불집")
    complaint_cards = [c for c in suk if c["종류"] == "불만 리뷰"]
    assert complaint_cards and complaint_cards[0]["제목"] == "불만 리뷰 2건이 있어요", "불만 리뷰 건수 집계 오류"
    assert complaint_cards[0]["급한 정도"] == 80, "불만 리뷰 급한 정도는 60 + 건수 × 10"

    # 떡볶이 연구소는 주소만 비어 있음 (우선순위 '보통') → 가게 정보 카드가 안 나와야 함
    ddeok = next(cards for s, cards in rows if s["이름"] == "떡볶이 연구소")
    assert not any(c["종류"] == "가게 정보" for c in ddeok), "'보통' 우선순위 빈칸은 카드가 없어야 함"

    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    L = ["# 이번 주 추천 카드 테스트 결과", "",
         f"기준일: {TODAY} · 행사 {len(events)}건 로드", "",
         "| 가게 | 종류 | 제목 | 근거 | 버튼 | 급한 정도 |", "|---|---|---|---|---|---|"]
    for s, cards in rows:
        for c in cards:
            L.append(f"| {s['이름']} | {c['종류']} | {c['제목']} | {c['근거']} | {c['버튼']} | {c['급한 정도']} |")
    with open(config.RESULTS_DIR / "weekly_results.md", "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    print("\n모든 점검 통과")
    print("결과 파일: results/weekly_results.md")


if __name__ == "__main__":
    main()
