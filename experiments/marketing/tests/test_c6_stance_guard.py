"""답글 태도 판정(c6.stance)의 안전장치 검증 — AI 호출 없음.

가게 잘못인 리뷰가 '억울한 리뷰'(explain)로 잘못 판정되면 사과 없는 답글이 나간다. 이 시험은 그 방향을 막는다.
과실 낱말 목록에 없는 표현이어도, 요청 앞에 이유가 붙었거나 받은 음식을 서술하면 사과(apology)여야 한다.

실행 (experiments/marketing 에서):
  python -m pytest -q tests/test_c6_stance_guard.py      또는      python -m tests.test_c6_stance_guard
리뷰 문장은 모두 이 시험을 위해 지어낸 합성 문장이다 (데모 가게 온기한식 메뉴 기준).
"""

import unittest

from c6.stance import APOLOGY, EXPLAIN, judge_stance, reason_before

# 가게 잘못일 수 있는 리뷰인데 '요청 + 거절' 꼴인 것. 모두 사과 답글이어야 한다.
STORE_FAULT = [
    # 과실 낱말 목록에 원래 있던 표현
    "국물이 다 새서 바꿔 달라고 했더니 안 된대요",
    "머리카락이 나와서 환불해 달라고 했는데 거절당했어요",
    "주문한 거랑 다른 메뉴가 와서 바꿔 달라고 했더니 안 된대요",
    # 목록에 없는 표현 + 요청 앞의 이유
    "음식이 이상해서 바꿔 달라고 했는데 안 된대요",
    "고기에서 냄새가 나서 바꿔 달라고 했는데 안 된대요",
    "밥이 너무 질어서 바꿔 달라고 했는데 안 된대요",
    "음식에서 플라스틱 조각이 나와서 바꿔 달라 했는데 안 된대요",
    "반찬 상태가 안 좋아서 교체해 달라고 했는데 안 해 주네요",
    "사진이랑 너무 달라서 바꿔 달라고 했는데 안 된대요",
    "시큼한 냄새 때문에 다른 메뉴로 바꿔 달라고 했더니 추가 요금 내라네요",
    "국이 영 아니길래 다른 메뉴로 바꿔 달라고 했더니 안 된대요",
    # 다른 음식이 왔다는 서술
    "순두부찌개를 시켰는데 된장찌개가 왔어요. 바꿔 달라니까 안 된대요",
    "불고기 덮밥 시켰는데 제육이 왔네요. 불고기로 바꿔 달라고 했더니 거절",
    # 이유가 다른 문장에 있는 것
    "아이가 먹다가 뭘 씹었어요. 무료로 다시 달라고 했는데 못 해 준대요",
    "배달 지역이라고 해서 시켰는데 한참 뒤에 안 된다고 취소했어요",
    "직원 실수인데 무료로 다시 달라고 하니 안 된대요",
    # 손님도 확실하지 않다고 한 것
    "제가 잘못 본 건지 모르겠지만 김치찌개로 다시 보내 달라니까 안 된대요",
]

# 가게 원칙 밖의 요청을 거절당한 리뷰. 사과 없이 설명하는 답글이어야 한다.
UNFAIR = [
    ("menu_change", "제육볶음 정식 고기를 불고기로 그냥 바꿔 달라고 했더니 안 된대요. 그것도 못 해 주나요? 별 하나 드립니다"),
    ("free_extra", "계란말이 서비스로 하나 달라고 했더니 안 된다고 하셨어요. 단골한테 너무하네요"),
    ("refund_after_eating", "다 먹고 나서 환불해 달라고 했더니 안 된다고 하네요. 별 하나 드립니다"),
    ("menu_change", "된장찌개를 순두부찌개로 그냥 바꿔 달라고 했는데 추가 요금을 내라고 하네요. 실망이에요"),
    ("customer_mistake", "제가 주문을 잘못 넣어서 된장찌개를 받았는데, 김치찌개로 다시 보내 달라니까 안 된대요"),
    ("outside_area_hours", "배달 가능 지역에서 조금 벗어났다고 주문을 안 받아 주시네요. 바로 옆인데 너무해요"),
    # 거절 뒤에 붙은 '…해서'는 이유가 아니라 결과다
    ("menu_change", "제육볶음 정식 고기를 불고기로 바꿔 달라고 했더니 안 된다고 해서 실망했어요"),
]


class TestStoreFaultNeverBecomesExplain(unittest.TestCase):
    def test_store_fault_with_request_and_refusal_stays_apology(self):
        for text in STORE_FAULT:
            with self.subTest(text=text):
                self.assertEqual(judge_stance(text).stance, APOLOGY)

    def test_reason_is_shown_to_the_owner(self):
        d = judge_stance("음식이 이상해서 바꿔 달라고 했는데 안 된대요")
        self.assertEqual(d.stance, APOLOGY)
        self.assertTrue(d.reasons)
        self.assertIsNone(d.principle)          # 사과 답글에는 원칙 문장을 붙이지 않는다

    def test_customer_reason_is_also_apology(self):
        """손님 사정이 이유여도 사과 쪽으로 둔다 (놓치는 쪽은 받아들인다)."""
        self.assertEqual(judge_stance("매운 걸 못 먹어서 제육을 불고기로 바꿔 달라고 했더니 안 된대요").stance, APOLOGY)


class TestUnfairReviewsStillExplain(unittest.TestCase):
    def test_unfair_requests_are_explain(self):
        for kind, text in UNFAIR:
            with self.subTest(text=text):
                d = judge_stance(text)
                self.assertEqual(d.stance, EXPLAIN)
                self.assertEqual(d.request, kind)
                self.assertTrue(d.principle)

    def test_fault_topic_still_vetoes(self):
        text = UNFAIR[0][1]
        self.assertEqual(judge_stance(text, negative_topics=["service"]).stance, EXPLAIN)
        self.assertEqual(judge_stance(text, negative_topics=["missing_item"]).stance, APOLOGY)


class TestReasonBefore(unittest.TestCase):
    def find(self, text):
        return reason_before(text, len(text))

    def test_reason_words(self):
        self.assertEqual(self.find("음식이 이상해서 바꿔"), "이상해서")
        self.assertEqual(self.find("냄새 때문에 바꿔"), "때문에")
        self.assertEqual(self.find("국이 식었길래 바꿔"), "식었길래")
        self.assertEqual(self.find("이상하다고 하니까 바꿔"), "하니까")

    def test_not_reasons(self):
        self.assertIsNone(self.find("배달앱에서 시켰는데 바꿔"))          # 장소
        self.assertIsNone(self.find("여기서 자주 시키는데 바꿔"))          # 장소
        self.assertIsNone(self.find("계란말이 서비스로 하나"))             # '서비스'의 서
        self.assertIsNone(self.find("다 먹고 나서 환불"))                  # 순서
        self.assertIsNone(self.find("제가 주문을 잘못 넣어서 된장찌개를"))  # 손님 자기 실수

    def test_only_text_before_the_position_counts(self):
        text = "불고기로 바꿔 달라고 했더니 안 된다고 해서 실망"
        self.assertIsNone(reason_before(text, text.index("안 된")))
        self.assertEqual(reason_before(text, len(text)), "해서")


if __name__ == "__main__":
    unittest.main()
