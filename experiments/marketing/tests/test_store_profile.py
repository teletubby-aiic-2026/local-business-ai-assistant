"""
가게 정보 빈칸 찾기 테스트 (AI 호출 없음)

합성 가게 3곳(거의 다 채움 / 절반 / 거의 비어 있음)으로 check_store_profile 결과를
예상 빈칸 목록과 비교해 통과 여부를 출력한다.

실행 방법
  python -m tests.test_store_profile

결과 파일: results/store_profile_results.md
"""

import config
from features.store_profile import check_store_profile

# ── 합성 가게 3곳 ──────────────────────────────────────────────
STORE_FULL = {
    "가게 이름": "몽글커피",
    "영업시간": "10:00~21:00",
    "휴무일": ["월"],
    "전화번호": "02-1234-5678",
    "메뉴": [("아메리카노", "4,500원"), ("크루아상", "4,000원"), ("라떼", "5,000원")],
    "주소": "서울 성동구 성수동",
    "가게 소개": "아늑한 동네 카페예요.",
    "대표 사진": ["photo1.jpg"],
    "포장": "가능", "배달": "불가",
    "주차": "없음",
    "예약 가능": "가능",
    "편의시설": [],  # 비어 있음
}
EXPECTED_FULL = {"편의시설"}

STORE_HALF = {
    "가게 이름": "성수 숯불집",
    "영업시간": "17:00~24:00",
    "휴무일": None,  # 비어 있음
    "전화번호": "02-9999-8888",
    "메뉴": [("돼지 목살", "12,000원"), ("된장찌개", ""), ("냉면", "9,000원")],  # 가격 하나 빔
    "주소": "서울 성동구 성수동",
    "가게 소개": "",  # 비어 있음
    "대표 사진": [],  # 비어 있음
    "포장": "", "배달": "",  # 둘 다 비어 있음
    "주차": "있음",
    "예약 가능": None,  # 비어 있음
    "편의시설": ["화장실", "Wi-Fi"],
}
EXPECTED_HALF = {"휴무일", "메뉴 가격", "가게 소개", "대표 사진", "포장·배달 여부", "예약 가능 여부"}

STORE_EMPTY = {
    "가게 이름": "떡볶이 연구소",
    "영업시간": "-",
    "휴무일": [],
    "전화번호": "02-1111-2222",
    "메뉴": [],
    "주소": None,
    "가게 소개": None,
    "대표 사진": None,
    "포장": None, "배달": None,
    "주차": None,
    "예약 가능": None,
    "편의시설": None,
}
EXPECTED_EMPTY = {
    "영업시간", "휴무일", "메뉴 가격", "메뉴 3개 이상", "주소", "가게 소개",
    "대표 사진", "포장·배달 여부", "주차", "예약 가능 여부", "편의시설",
}

CASES = [
    ("몽글커피 (거의 다 채움)", STORE_FULL, EXPECTED_FULL),
    ("성수 숯불집 (절반)", STORE_HALF, EXPECTED_HALF),
    ("떡볶이 연구소 (거의 비어 있음)", STORE_EMPTY, EXPECTED_EMPTY),
]


def main():
    rows = []
    all_ok = True
    for label, store, expected in CASES:
        result = check_store_profile(store)
        got = {b["항목"] for b in result["빈칸"]}
        ok = got == expected
        all_ok &= ok
        print(f"[{'통과' if ok else '실패'}] {label} · 채움 비율 {result['채움_비율']:.0%}"
              + ("" if ok else f" · 예상 {sorted(expected)} / 실제 {sorted(got)}"))
        rows.append((label, result))

    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# 가게 정보 빈칸 찾기 테스트 결과", "", f"전체 통과: {'O' if all_ok else 'X'}", ""]
    for label, result in rows:
        lines += [f"## {label}", "", f"- 채움 비율: {result['채움_비율']:.0%}",
                   f"- 다 채움: {'O' if result['다 채움'] else 'X'}", ""]
        if result["빈칸"]:
            lines += ["| 우선순위 | 항목 | 안내 |", "|---|---|---|"]
            for b in result["빈칸"]:
                lines.append(f"| {b['우선순위']} | {b['이름']} | {b['안내']} |")
        else:
            lines.append("빈칸 없음")
        lines.append("")
    with open(config.RESULTS_DIR / "store_profile_results.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n전체 통과: {'O' if all_ok else 'X'}")
    print("결과 파일: results/store_profile_results.md")


if __name__ == "__main__":
    main()
