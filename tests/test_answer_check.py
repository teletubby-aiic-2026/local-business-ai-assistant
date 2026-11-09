"""shared.answer_check 검증 (C5 카드 이유 문장 검사용). 저장소 루트에서: python -m unittest tests.test_answer_check -v

검사기는 PR #13에서 수정 없이 복사한 것이라, 여기서는 "우리 카드 2장 모양에서 기대대로 막고 통과시키는가"만 봅니다.
카드 dict 모양은 검사기가 읽는 그대로입니다: {"id", "topic", "status", "text", "values": [{"label", "value", "unit"}]}.
F2의 -12.3은 시험용 숫자입니다. 데모 데이터에는 쓰지 않습니다.
"""
import unittest

from shared.answer_check import check_answer

CARDS = [
    {
        "id": "F1",
        "topic": "review_issue",
        "status": "available",
        "text": "포장 누락 불만 리뷰 3건 (반복)",
        "values": [{"label": "포장 누락 불만 리뷰", "value": 3, "unit": "건"}],
    },
    {
        "id": "F2",
        "topic": "market_sales_change",
        "status": "available",
        "text": "2026년 2분기 저녁(17~21시) 추정매출, 전년 동기 대비. 출처 서울시",
        "values": [{"label": "저녁(17~21시) 추정매출 전년 동기 대비 변화율", "value": -12.3, "unit": "%"}],
    },
]


def problem_types(text: str) -> list[str]:
    return [p["type"] for p in check_answer(text, CARDS)["problems"]]


def problem_details(text: str) -> list[str]:
    return [p.get("detail") for p in check_answer(text, CARDS)["problems"]]


class Passes(unittest.TestCase):
    def assert_ok(self, text: str) -> None:
        result = check_answer(text, CARDS)
        self.assertTrue(result["ok"], f"{text!r} 가 막혔습니다: {result['problems']}")

    def test_count_on_card(self):
        self.assert_ok("포장 누락이 3건 반복됐어요 [F1]")

    def test_percent_and_quarter_on_card(self):
        self.assert_ok("2026년 2분기 저녁 추정매출이 전년 동기보다 12.3% 줄었어요 [F2]")

    def test_plain_reason(self):
        self.assert_ok("같은 불만이 반복되고 있어서 답글과 재발 방지 공지를 먼저 준비해 두면 좋아요.")

    def test_plain_coupon_suggestion(self):
        self.assert_ok("저녁 손님을 다시 부르는 쿠폰 홍보를 해 보는 건 어떨까요?")


class Blocks(unittest.TestCase):
    def test_number_not_on_card(self):
        self.assertIn("number_not_on_card", problem_types("포장 누락이 5건 반복됐어요 [F1]"))

    def test_unknown_citation(self):
        self.assertIn("unknown_citation", problem_types("포장 누락이 3건 반복됐어요 [F9]"))

    def test_uncited_number(self):
        self.assertIn("uncited_number", problem_types("포장 누락이 3건 반복됐어요"))

    def test_period_not_on_card(self):
        self.assertIn("period_not_on_card", problem_types("2026년 3분기 저녁 추정매출이 12.3% 줄었어요 [F2]"))

    def test_forbidden_cause(self):
        self.assertIn("때문", problem_details("주문이 몰리는 시간이라 포장이 빠진 것 때문이에요."))

    def test_forbidden_guarantee(self):
        self.assertIn("보장", problem_details("쿠폰을 쓰면 손님이 돌아오는 것을 보장해요."))


if __name__ == "__main__":
    unittest.main()
