"""C2 합성 리뷰 만들기: data/synthetic/{store,reviews,labels}.json 을 다시 씁니다.

리뷰 글과 정답 라벨을 한 줄에 같이 적어 두어서, 글을 고치면 라벨도 같이 고치게 했습니다.
실행 (services/review-insight 에서): python -m scripts.make_synthetic

설계
- 시나리오 가게는 '저녁 매출 하락' 상권의 한식집입니다 (C4 상권 스냅샷, C5 카드 ⓑ와 이어지도록).
- 불만은 일부러 몇 갈래로 반복되게 만들었습니다. 반복 묶음(C3)이 이것을 찾아야 합니다.
    배달 시간 6건 · 음식 온도 4건 · 포장 3건 · 양 4건 → 모두 저녁(17~21시)에 몰림 (양은 점심·저녁 섞임)
    누락 2건 · 매장 대기 2건 · 응대 1건 · 위생 1건 → 반복 기준(3건) 미만 또는 경계
- 칭찬은 주로 점심(11~14시)에 몰리게 해서 "점심은 잘 되는데 저녁 경험이 나쁘다"는 대비가 보이게 했습니다.
- 손님 이름·닉네임·주소·전화번호 같은 개인정보 필드는 두지 않습니다 (모듈 규격 3.3).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "synthetic"
STORE_ID = "store_ongi"

STORE = {
    "store_id": STORE_ID,
    "name": "온기한식 (가상)",
    "business_type": "korean",
    "business_type_name": "한식음식점",
    "channels": ["baemin", "coupangeats", "yogiyo", "naver_place"],
    "menu": ["제육볶음 정식", "된장찌개", "김치찌개", "순두부찌개", "불고기 덮밥", "계란말이"],
    "data_origin": "synthetic",
}

# (번호, 채널, 별점, 날짜, 시각, 리뷰 글, 정답 감정, 정답 주제 {주제: 극성}, 만든 의도)
# 감정: positive / negative / mixed / neutral, 극성: + 칭찬 / - 불만
R = [
    # ── 반복 불만 1: 배달 시간 (저녁) ──
    (1, "baemin", 2, "2026-10-28", "19:40", "저녁 7시에 시켰는데 1시간 넘게 걸려서 왔어요. 배고파서 혼났네요.", "negative", {"delivery_time": "-"}, "저녁 배달 지연"),
    (2, "coupangeats", 1, "2026-11-01", "20:10", "배달이 너무 늦어요. 예상 시간보다 40분은 더 걸린 듯", "negative", {"delivery_time": "-"}, "저녁 배달 지연"),
    (3, "baemin", 2, "2026-11-03", "19:05", "맛은 괜찮은데 저녁엔 배달이 항상 늦게 와요", "mixed", {"taste": "+", "delivery_time": "-"}, "칭찬+저녁 지연이 섞임"),
    (4, "yogiyo", 2, "2026-11-05", "18:50", "도착 예정 시간이 계속 밀리더니 결국 70분 걸렸습니다", "negative", {"delivery_time": "-"}, "'배달' 단어 없이 지연 표현"),
    (5, "baemin", 1, "2026-11-06", "20:30", "한 시간 기다렸는데 찌개가 다 식어서 왔어요", "negative", {"delivery_time": "-", "temperature": "-"}, "지연+식음 두 불만"),
    (6, "coupangeats", 2, "2026-11-07", "19:20", "퇴근하고 시켰는데 너무 오래 걸렸어요. 다음엔 포장해야겠네요", "negative", {"delivery_time": "-"}, "'오래 걸림' 표현"),
    # ── 반복 불만 2: 음식 온도 (저녁) ──
    (7, "baemin", 2, "2026-10-30", "19:50", "순두부찌개가 미지근하게 왔어요. 데워 먹었습니다", "negative", {"temperature": "-"}, "미지근"),
    (8, "yogiyo", 3, "2026-11-04", "20:00", "밥이 식어서 딱딱했어요. 반찬은 맛있었어요", "mixed", {"temperature": "-", "taste": "+"}, "식음+맛 칭찬"),
    (9, "coupangeats", 2, "2026-11-08", "19:30", "국물이 차갑게 식어서 왔네요", "negative", {"temperature": "-"}, "차갑게 식음"),
    # ── 반복 불만 3: 양·가격 ──
    (10, "baemin", 2, "2026-10-15", "12:30", "가격에 비해 양이 너무 적어요. 제육이 몇 점 없네요", "negative", {"portion": "-", "price": "-"}, "양+가격"),
    (11, "coupangeats", 3, "2026-10-22", "13:00", "맛은 있는데 양이 좀 아쉬워요", "mixed", {"taste": "+", "portion": "-"}, "맛 칭찬+양 아쉬움"),
    (12, "naver_place", 3, "2026-10-26", "18:30", "정식 구성 치고는 양이 적은 편이에요", "negative", {"portion": "-"}, "매장 방문, 양"),
    (13, "yogiyo", 2, "2026-11-02", "12:10", "12,000원인데 고기가 너무 적게 들었어요", "negative", {"portion": "-", "price": "-"}, "'양' 단어 없이 양 불만"),
    # ── 반복 불만 4: 포장 (저녁) ──
    (14, "baemin", 1, "2026-10-19", "19:10", "찌개 국물이 다 새서 봉지가 흥건했어요", "negative", {"packaging": "-"}, "국물 샘"),
    (15, "coupangeats", 2, "2026-10-29", "20:20", "포장이 허술해서 국물이 넘쳤어요", "negative", {"packaging": "-"}, "포장 허술"),
    (16, "baemin", 2, "2026-11-06", "19:45", "뚜껑이 제대로 안 닫혀서 국물이 샜어요. 포장 신경 써 주세요", "negative", {"packaging": "-"}, "뚜껑"),
    # ── 반복 기준 미만 불만 ──
    (17, "yogiyo", 1, "2026-10-24", "19:30", "공깃밥 추가했는데 안 왔어요", "negative", {"missing_item": "-"}, "누락 1"),
    (18, "baemin", 2, "2026-11-04", "20:05", "계란말이를 시켰는데 빠져 있었어요", "negative", {"missing_item": "-"}, "누락 2 (2건이라 반복 아님)"),
    (19, "naver_place", 2, "2026-10-17", "13:10", "매장에서 주문했는데 직원분이 좀 퉁명스러웠어요", "negative", {"service": "-"}, "응대 1건"),
    (20, "naver_place", 1, "2026-10-21", "12:40", "반찬 그릇에 머리카락이 있었어요", "negative", {"hygiene": "-"}, "위생 1건 (단건이어도 심각)"),
    # ── 칭찬 (주로 점심) ──
    (21, "baemin", 5, "2026-10-13", "12:20", "제육볶음이 불맛 나고 정말 맛있어요!", "positive", {"taste": "+"}, "맛 칭찬"),
    (22, "coupangeats", 5, "2026-10-14", "12:50", "점심에 시켰는데 20분 만에 왔어요. 빠르고 따뜻했어요", "positive", {"delivery_time": "+", "temperature": "+"}, "점심 배달은 빠름 (저녁과 대비)"),
    (23, "naver_place", 5, "2026-10-16", "12:15", "사장님이 정말 친절하세요. 반찬도 계속 리필해 주셨어요", "positive", {"service": "+"}, "응대 칭찬"),
    (24, "baemin", 5, "2026-10-18", "18:40", "된장찌개가 집밥 같아요. 자주 시킬게요", "positive", {"taste": "+"}, "맛 칭찬 (저녁)"),
    (25, "yogiyo", 4, "2026-10-20", "12:30", "가성비 좋은 한식집이에요", "positive", {"price": "+"}, "가성비"),
    (26, "naver_place", 5, "2026-10-23", "12:00", "점심 정식 구성이 알차고 맛있어요", "positive", {"menu": "+", "taste": "+"}, "구성+맛"),
    (27, "coupangeats", 5, "2026-10-25", "13:20", "김치찌개 맛집 인정합니다", "positive", {"taste": "+"}, "맛집"),
    (28, "baemin", 4, "2026-10-27", "12:40", "양도 넉넉하고 맛도 좋아요", "positive", {"portion": "+", "taste": "+"}, "양 칭찬 (양 불만과 반대)"),
    (29, "naver_place", 5, "2026-10-31", "18:20", "매장 분위기도 깔끔하고 음식도 정갈해요", "positive", {"hygiene": "+", "taste": "+"}, "청결 칭찬"),
    (30, "baemin", 5, "2026-11-01", "12:10", "포장이 꼼꼼해서 국물 하나 안 샜어요", "positive", {"packaging": "+"}, "점심 포장은 괜찮음 ('안 샜어요'는 칭찬)"),
    (31, "yogiyo", 5, "2026-11-02", "13:00", "불고기 덮밥 달달하니 맛있어요. 재주문 의사 있어요", "positive", {"taste": "+"}, "재주문"),
    (32, "coupangeats", 4, "2026-11-03", "12:20", "회사 근처라 점심마다 시켜 먹어요. 항상 맛있어요", "positive", {"taste": "+"}, "점심 단골"),
    (33, "naver_place", 5, "2026-11-05", "12:30", "직원분들이 친절하고 음식이 빨리 나와요", "positive", {"service": "+", "wait_time": "+"}, "매장 응대·대기"),
    (34, "baemin", 5, "2026-11-07", "12:45", "반찬이 매일 바뀌어서 좋아요", "positive", {"menu": "+"}, "반찬 구성"),
    (35, "yogiyo", 4, "2026-11-08", "12:15", "순두부찌개 얼큰하고 맛있어요", "positive", {"taste": "+"}, "맛"),
    (36, "naver_place", 5, "2026-10-29", "12:05", "주문 요청 사항을 잘 들어주셔서 감사해요", "positive", {"service": "+"}, "요청 반영 칭찬"),
    # ── 섞임·무난 ──
    (37, "naver_place", 3, "2026-10-22", "19:00", "저녁에 갔더니 웨이팅이 20분 정도 있었어요. 음식은 괜찮았어요", "mixed", {"wait_time": "-", "taste": "+"}, "저녁 매장 대기"),
    (38, "coupangeats", 3, "2026-10-30", "12:30", "무난해요", "neutral", {}, "주제 없음"),
    (39, "baemin", 4, "2026-11-05", "12:00", "맛있어요. 다만 김치가 조금 짰어요", "mixed", {"taste": "+-"}, "같은 주제에 칭찬·불만"),
    (40, "naver_place", 2, "2026-11-07", "19:10", "저녁 시간엔 주문이 밀려서 음식이 늦게 나왔어요", "negative", {"wait_time": "-"}, "저녁 매장 대기 (배달 아님)"),
]


def build():
    reviews, labels = [], []
    for n, channel, rating, day, hm, text, sentiment, topics, note in R:
        rid = f"rv_{n:04d}"
        reviews.append({
            "review_id": rid, "store_id": STORE_ID, "channel": channel, "rating": rating, "text": text,
            "created_at": f"{day}T{hm}:00+09:00", "input_method": "sample", "pii_masked": False,
            "data_origin": "synthetic",
        })
        expected = [{"topic": t, "polarity": "positive" if p == "+" else "negative"}
                    for t, ps in topics.items() for p in ps]
        labels.append({"review_id": rid, "expected_sentiment": sentiment, "expected_topics": expected, "note": note})
    return reviews, labels


def main():
    reviews, labels = build()
    assert len(reviews) == 40 and len({r["review_id"] for r in reviews}) == 40
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in (("store.json", STORE), ("reviews.json", reviews), ("labels.json", labels)):
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"리뷰 {len(reviews)}건, 라벨 {len(labels)}건 → {OUT}")


if __name__ == "__main__":
    main()
