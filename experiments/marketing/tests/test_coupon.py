"""
쿠폰 만들기 테스트 (AI 호출 없음)

tests/test_tone.py의 STORES(가게 3곳)를 가져와 메뉴 가격을 붙인 복사본을 만들고,
정상 입력 3건과 일부러 틀리게 만든 입력 4건을 build_coupon에 넣어
예상한 "확인 필요"가 나오는지 확인한다.

실행 방법
  python -m tests.test_coupon

결과 파일: results/coupon_results.md
"""

import datetime

import config
from features.coupon import build_coupon
from tests.test_tone import STORES as _BASE_STORES

TODAY = datetime.date(2025, 11, 3)

# ── STORES 메뉴에 가격 붙인 복사본 (tests/test_tone.py에는 가격이 없음) ──────
MENU_PRICES = {
    "몽글커피": {"몽글 크림라떼": 5000, "아메리카노": 4500, "휘낭시에": 4000},
    "성수 숯불집": {"돼지 목살": 15000, "된장찌개": 9000, "냉면": 9000},
    "떡볶이 연구소": {"국물떡볶이": 4000, "김말이": 1000, "순대": 5000},
}

STORES = []
for _s in _BASE_STORES:
    _copy = dict(_s)
    prices = MENU_PRICES[_s["이름"]]
    _copy["메뉴"] = [(m, prices[m]) for m in _s["메뉴"]]
    STORES.append(_copy)

STORE_BY_NAME = {s["이름"]: s for s in STORES}


# ── 테스트 케이스: (이름, 가게, choice, 확인 필요가 있어야 하는가, 확인용 키워드) ──
CASES = [
    ("정상 · 증정", STORE_BY_NAME["몽글커피"],
     {"혜택": "증정", "메뉴": "휘낭시에", "수량": 50, "기간_일": 14,
      "사용 방법": "매장", "조건": ["1인(또는 테이블당) 1회"]},
     False, None),
    ("정상 · 금액 할인", STORE_BY_NAME["성수 숯불집"],
     {"혜택": "금액 할인", "메뉴": "냉면", "값": 2000, "수량": 100, "기간_일": 30,
      "사용 방법": "예약", "조건": ["중복 사용 불가", "1인(또는 테이블당) 1회", "다른 메뉴와 함께 주문 시"]},
     False, None),
    ("정상 · 비율 할인(전 메뉴)", STORE_BY_NAME["떡볶이 연구소"],
     {"혜택": "비율 할인", "메뉴": "전 메뉴", "값": 10, "수량": 30, "기간_일": 7,
      "사용 방법": "매장", "조건": []},
     False, None),
    ("틀림 · 없는 메뉴", STORE_BY_NAME["몽글커피"],
     {"혜택": "증정", "메뉴": "아이스크림", "수량": 10, "기간_일": 7,
      "사용 방법": "매장", "조건": []},
     True, "가게 메뉴에 없어요"),
    ("틀림 · 할인 금액이 메뉴 가격 이상", STORE_BY_NAME["성수 숯불집"],
     {"혜택": "금액 할인", "메뉴": "냉면", "값": 9000, "수량": 10, "기간_일": 7,
      "사용 방법": "매장", "조건": []},
     True, "메뉴 가격"),
    ("틀림 · 비율 80%", STORE_BY_NAME["떡볶이 연구소"],
     {"혜택": "비율 할인", "메뉴": "김말이", "값": 80, "수량": 10, "기간_일": 7,
      "사용 방법": "매장", "조건": []},
     True, "50%를 초과"),
    ("틀림 · 기간 120일", STORE_BY_NAME["몽글커피"],
     {"혜택": "증정", "메뉴": "아메리카노", "수량": 10, "기간_일": 120,
      "사용 방법": "매장", "조건": []},
     True, "90일 이하"),
]


def main():
    rows = []
    all_ok = True
    for label, store, choice, expect_issue, keyword in CASES:
        result = build_coupon(choice, store, TODAY)
        has_issue = bool(result["확인 필요"])
        matched = (not expect_issue and not has_issue) or (
            expect_issue and any(keyword in msg for msg in result["확인 필요"]))
        ok = matched
        all_ok &= ok
        status = "통과" if ok else "실패"
        print(f"[{status}] {label} · 확인 필요 {result['확인 필요']}")
        rows.append((label, choice, result, ok))

    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# 쿠폰 만들기 테스트 결과 (AI 호출 없음)", "",
             "※ 보류 기능: 쿠폰 발급 비용 확인 전이라 기능 정의서상 '보류' 상태입니다.", "",
             f"전체 통과: {'O' if all_ok else 'X'}", ""]
    for label, choice, result, ok in rows:
        lines += [f"## {label} · {'통과' if ok else '실패'}", "",
                  f"- 입력: {choice}", ""]
        lines += ["| 항목 | 값 |", "|---|---|"]
        for k, v in result["입력값"].items():
            lines.append(f"| {k} | {v} |")
        lines.append("")
        lines.append("- 확인 필요: " + (", ".join(result["확인 필요"]) if result["확인 필요"] else "없음"))
        lines.append("- 추천 조건: " + (", ".join(result["추천 조건"]) if result["추천 조건"] else "없음"))
        lines.append("")
    with open(config.RESULTS_DIR / "coupon_results.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n전체 통과: {'O' if all_ok else 'X'}")
    print("결과 파일: results/coupon_results.md")


if __name__ == "__main__":
    main()
