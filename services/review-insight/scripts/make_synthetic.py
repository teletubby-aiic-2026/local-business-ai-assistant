"""C2 합성 리뷰 만들기: data/synthetic/<store_id>/{store,reviews,labels}.json 을 다시 씁니다.

리뷰 글과 정답 라벨을 한 줄에 같이 적어 두어서, 글을 고치면 라벨도 같이 고치게 했습니다.
실행 (services/review-insight 에서): python -m scripts.make_synthetic

가게 3곳 (업종·바쁜 시간·반복 불만이 서로 다르게 해서, 분류·묶음이 한 가게에만 맞춰지지 않았는지 확인)
- store_ongi   온기한식 (발표 시나리오, 40건): 저녁(17~21시) 배달 시간·음식 온도·포장 + 양
- store_basak  바삭치킨 (30건): 밤(21~24시) 누락·배달 시간 + 식감(눅눅함)
- store_mongle 몽글카페 (30건): 점심(11~14시) 매장 대기 + 오후(14~17시) 음료 맛·포장

온기한식 설계
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
ONGI = {
    "store_id": "store_ongi", "short": "ongi",
    "name": "온기한식 (가상)",
    "business_type": "korean",
    "business_type_name": "한식음식점",
    "channels": ["baemin", "coupangeats", "yogiyo", "naver_place"],
    "menu": ["제육볶음 정식", "된장찌개", "김치찌개", "순두부찌개", "불고기 덮밥", "계란말이"],
    "data_origin": "synthetic",
}

# (번호, 채널, 별점, 날짜, 시각, 리뷰 글, 정답 감정, 정답 주제 {주제: 극성}, 만든 의도)
# 감정: positive / negative / mixed / neutral, 극성: + 칭찬 / - 불만
ONGI_ROWS = [
    # ── 반복 불만 1: 배달 시간 (저녁) ──
    (1, "baemin", 2, "2026-10-28", "19:40", "저녁 7시에 시켰는데 1시간 넘게 걸려서 왔어요. 배고파서 혼났네요.", "negative", {"delivery_time": "-"}, "저녁 배달 지연"),
    (2, "coupangeats", 1, "2026-11-01", "20:10", "배달이 너무 늦어요. 예상 시간보다 40분은 더 걸린 듯", "negative", {"delivery_time": "-"}, "저녁 배달 지연"),
    (3, "baemin", 2, "2026-11-03", "19:05", "맛은 괜찮은데 저녁엔 배달이 항상 늦게 와요", "mixed", {"taste": "+", "delivery_time": "-"}, "칭찬+저녁 지연이 섞임"),
    (4, "yogiyo", 2, "2026-11-05", "18:50", "도착 예정 시간이 계속 밀리더니 결국 70분 걸렸습니다", "negative", {"delivery_time": "-"}, "'배달' 단어 없이 지연 표현"),
    (5, "baemin", 1, "2026-11-06", "20:30", "한 시간 기다렸는데 찌개가 다 식어서 왔어요", "negative", {"delivery_time": "-", "temperature": "-"}, "지연+식음 두 불만"),
    (6, "coupangeats", 2, "2026-11-07", "19:20", "퇴근하고 시켰는데 너무 오래 걸렸어요. 다음엔 포장해야겠네요", "negative", {"delivery_time": "-"}, "'오래 걸림' 표현"),
    # ── 반복 불만 2: 음식 온도 (저녁) ──
    (7, "baemin", 2, "2026-10-30", "19:50", "순두부찌개가 미지근하게 왔어요. 데워 먹었습니다", "negative", {"temperature": "-"}, "미지근"),
    (8, "yogiyo", 3, "2026-11-04", "20:00", "밥이 식어서 딱딱했어요. 반찬은 맛있었어요", "mixed", {"temperature": "-", "texture": "-", "taste": "+"}, "식음·딱딱함+맛 칭찬"),
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
    (29, "naver_place", 5, "2026-10-31", "18:20", "매장 분위기도 깔끔하고 음식도 정갈해요", "positive", {"atmosphere": "+", "hygiene": "+", "taste": "+"}, "분위기·청결 칭찬"),
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


# ── 바삭치킨: 밤(21~24시)이 바쁜 치킨집. 반복 불만 = 누락 4 · 식감(눅눅) 4 · 배달 시간 3 ──
BASAK = {
    "store_id": "store_basak", "short": "basak",
    "name": "바삭치킨 (가상)",
    "business_type": "chicken",
    "business_type_name": "치킨전문점",
    "channels": ["baemin", "coupangeats", "yogiyo", "naver_place"],
    "menu": ["후라이드", "양념치킨", "반반", "순살 치킨", "치즈볼", "콜라"],
    "data_origin": "synthetic",
}
BASAK_ROWS = [
    # 반복 불만 1: 누락 (밤)
    (1, "baemin", 1, "2026-10-14", "22:15", "양념 소스를 따로 요청했는데 안 왔어요", "negative", {"missing_item": "-"}, "소스 누락"),
    (2, "coupangeats", 2, "2026-10-20", "21:40", "치킨무가 빠져 있었어요. 치킨에 무가 없으면 어떡해요", "negative", {"missing_item": "-"}, "무 누락"),
    (3, "yogiyo", 2, "2026-10-27", "22:30", "콜라 시켰는데 누락됐네요", "negative", {"missing_item": "-"}, "음료 누락"),
    (4, "baemin", 1, "2026-11-04", "23:10", "치즈볼 2개 시켰는데 1개만 들어 있었어요", "negative", {"missing_item": "-"}, "'누락·빠짐' 단어 없이 개수 부족"),
    # 반복 불만 2: 식감 (눅눅함·질김)
    (5, "coupangeats", 2, "2026-10-18", "20:30", "튀김옷이 눅눅해서 바삭한 맛이 없었어요", "negative", {"texture": "-"}, "눅눅 ('바삭한'이 들어 있지만 불만)"),
    (6, "baemin", 2, "2026-10-25", "21:50", "오는 동안 눅눅해졌는지 하나도 안 바삭해요", "negative", {"texture": "-"}, "'안 바삭' 부정"),
    (7, "yogiyo", 3, "2026-11-02", "19:40", "맛은 있는데 겉이 좀 눅눅했어요", "mixed", {"taste": "+", "texture": "-"}, "맛 칭찬+식감 불만"),
    (8, "baemin", 2, "2026-11-07", "22:20", "닭이 질기고 퍽퍽했어요", "negative", {"texture": "-"}, "질김"),
    # 반복 불만 3: 배달 시간 (밤)
    (9, "coupangeats", 1, "2026-10-31", "22:40", "밤 10시에 시켰는데 1시간 반 걸렸어요", "negative", {"delivery_time": "-"}, "밤 배달 지연"),
    (10, "baemin", 2, "2026-11-05", "23:05", "야식으로 시켰는데 너무 늦게 왔어요", "negative", {"delivery_time": "-"}, "야식 지연"),
    (11, "yogiyo", 2, "2026-11-08", "22:10", "예상 시간이 계속 늘어나더니 한참 뒤에야 받았어요", "negative", {"delivery_time": "-"}, "'배달' 단어 없이 지연"),
    # 기준 미만
    (12, "baemin", 3, "2026-10-22", "20:10", "반반 가격이 많이 올랐네요. 좀 비싸요", "negative", {"price": "-"}, "가격 1"),
    (13, "naver_place", 3, "2026-10-29", "19:20", "맛은 그대로인데 가격이 부담돼요", "mixed", {"taste": "+", "price": "-"}, "가격 2 (반복 아님)"),
    (14, "coupangeats", 2, "2026-11-06", "21:30", "치킨이 식어서 왔어요", "negative", {"temperature": "-"}, "온도 1"),
    (15, "coupangeats", 2, "2026-11-08", "23:20", "치킨에서 기름 쩐내가 났어요", "negative", {"taste": "-"}, "맛 불만 1"),
    # 칭찬
    (16, "baemin", 5, "2026-10-13", "19:10", "후라이드가 정말 바삭하고 맛있어요!", "positive", {"texture": "+", "taste": "+"}, "식감·맛 칭찬"),
    (17, "naver_place", 5, "2026-10-15", "18:50", "매장에서 갓 튀긴 치킨 먹으니 최고예요", "positive", {"taste": "+"}, "매장"),
    (18, "coupangeats", 5, "2026-10-16", "20:20", "양념이 달지 않고 딱 좋아요", "positive", {"taste": "+"}, "'달지 않고'는 칭찬"),
    (19, "yogiyo", 4, "2026-10-19", "19:30", "양이 많아서 셋이 먹어도 남았어요", "positive", {"portion": "+"}, "양"),
    (20, "baemin", 5, "2026-10-21", "18:40", "닭다리살이 촉촉하고 부드러워요", "positive", {"texture": "+"}, "식감 칭찬"),
    (21, "naver_place", 5, "2026-10-23", "19:00", "사장님이 서비스로 치즈볼을 주셨어요. 감사합니다", "positive", {"service": "+"}, "서비스"),
    (22, "coupangeats", 5, "2026-10-26", "18:30", "주문하고 30분 만에 왔어요. 따끈따끈했어요", "positive", {"delivery_time": "+", "temperature": "+"}, "저녁 이른 시간은 빠름"),
    (23, "baemin", 4, "2026-10-28", "19:50", "순살도 크고 양이 넉넉해요", "positive", {"portion": "+"}, "양"),
    (24, "yogiyo", 5, "2026-10-30", "20:00", "양념치킨 맛집이에요. 또 시킬게요", "positive", {"taste": "+"}, "맛집"),
    (25, "naver_place", 5, "2026-11-01", "18:20", "가게가 깔끔하고 직원분들도 친절해요", "positive", {"hygiene": "+", "service": "+"}, "청결·응대"),
    (26, "baemin", 5, "2026-11-03", "19:15", "포장이 꼼꼼해서 양념이 하나도 안 흘렀어요", "positive", {"packaging": "+"}, "'안 흘렀어요'는 칭찬"),
    (27, "coupangeats", 4, "2026-11-05", "18:45", "치킨은 맛있어요", "positive", {"taste": "+"}, "짧은 칭찬"),
    (28, "yogiyo", 5, "2026-11-07", "19:05", "가성비 최고 치킨집", "positive", {"price": "+"}, "가성비"),
    # 섞임·무난
    (29, "baemin", 3, "2026-10-17", "21:10", "그냥 평범한 치킨이에요", "neutral", {}, "주제 없음"),
    (30, "naver_place", 3, "2026-11-02", "20:40", "웨이팅이 30분이었지만 맛은 좋았어요", "mixed", {"wait_time": "-", "taste": "+"}, "매장 대기"),
]

# ── 몽글카페: 점심·오후가 바쁜 카페. 반복 불만 = 매장 대기 5(점심) · 음료 맛 3 · 포장 3(오후) ──
MONGLE = {
    "store_id": "store_mongle", "short": "mongle",
    "name": "몽글카페 (가상)",
    "business_type": "cafe",
    "business_type_name": "커피-음료",
    "channels": ["baemin", "coupangeats", "yogiyo", "naver_place"],
    "menu": ["아메리카노", "바닐라라떼", "딸기 케이크", "소금빵", "크로플"],
    "data_origin": "synthetic",
}
MONGLE_ROWS = [
    # 반복 불만 1: 매장 대기 (점심)
    (1, "naver_place", 2, "2026-10-14", "12:40", "점심시간에 갔더니 음료 나오는 데 20분 넘게 걸렸어요", "negative", {"wait_time": "-"}, "매장 대기 ('넘게 걸렸'이지만 배달 아님)"),
    (2, "naver_place", 2, "2026-10-21", "13:10", "주문이 밀려서 한참 기다렸어요", "negative", {"wait_time": "-"}, "대기"),
    (3, "naver_place", 3, "2026-10-30", "12:50", "커피는 맛있는데 점심엔 대기가 너무 길어요", "mixed", {"taste": "+", "wait_time": "-"}, "맛 칭찬+대기"),
    (4, "naver_place", 2, "2026-11-06", "13:30", "직장인 몰리는 시간엔 음료 받기까지 너무 오래 걸려요", "negative", {"wait_time": "-"}, "'오래 걸려요'인데 매장 대기"),
    (5, "naver_place", 4, "2026-11-08", "12:10", "점심에 갔는데 대기는 있었지만 커피가 맛있어요", "mixed", {"wait_time": "-", "taste": "+"}, "대기+맛"),
    # 반복 불만 2: 음료 맛 (오후)
    (6, "baemin", 2, "2026-10-19", "15:10", "아메리카노가 너무 연해서 물 맛이 나요", "negative", {"taste": "-"}, "연함"),
    (7, "coupangeats", 2, "2026-10-28", "16:00", "바닐라라떼가 지나치게 달아요", "negative", {"taste": "-"}, "너무 닮 (26번 '달달하니 좋아요'와 반대)"),
    (8, "naver_place", 3, "2026-11-04", "14:30", "라떼가 예전보다 밍밍해졌어요", "negative", {"taste": "-"}, "밍밍"),
    # 반복 불만 3: 포장 (오후 배달)
    (9, "baemin", 1, "2026-10-24", "15:20", "음료가 쏟아져서 반밖에 안 남았어요", "negative", {"packaging": "-"}, "쏟아짐"),
    (10, "coupangeats", 2, "2026-11-01", "16:40", "컵 뚜껑이 열려서 봉투가 다 젖었어요", "negative", {"packaging": "-"}, "뚜껑"),
    (11, "yogiyo", 2, "2026-11-07", "14:50", "케이크가 상자 안에서 다 뭉개져서 왔어요", "negative", {"packaging": "-"}, "'포장' 단어 없이 포장 불만"),
    # 기준 미만
    (12, "naver_place", 3, "2026-10-26", "15:00", "디저트 가격이 좀 비싼 편이에요", "negative", {"price": "-"}, "가격 1"),
    (13, "baemin", 3, "2026-11-03", "15:40", "음료 양에 비해 가격이 높아요", "negative", {"portion": "-", "price": "-"}, "가격 2 (반복 아님)"),
    (14, "yogiyo", 2, "2026-10-22", "16:20", "얼음이 다 녹아서 왔어요", "negative", {"temperature": "-"}, "온도 1"),
    (15, "coupangeats", 2, "2026-11-06", "15:00", "케이크가 너무 퍽퍽했어요", "negative", {"texture": "-"}, "식감 1"),
    # 칭찬
    (16, "naver_place", 5, "2026-10-13", "14:20", "소금빵이 겉바속촉이에요!", "positive", {"texture": "+"}, "식감 칭찬"),
    (17, "naver_place", 5, "2026-10-15", "15:30", "매장이 넓고 깨끗해요", "positive", {"atmosphere": "+", "hygiene": "+"}, "공간·청결"),
    (18, "baemin", 5, "2026-10-16", "14:40", "딸기 케이크 생크림이 진짜 맛있어요", "positive", {"taste": "+"}, "맛"),
    (19, "coupangeats", 5, "2026-10-18", "15:50", "크로플이 바삭하고 맛있어요", "positive", {"texture": "+", "taste": "+"}, "식감·맛"),
    (20, "naver_place", 5, "2026-10-20", "11:30", "사장님이 정말 친절하세요", "positive", {"service": "+"}, "응대"),
    (21, "yogiyo", 4, "2026-10-23", "14:10", "원두가 고소해서 커피가 맛있어요", "positive", {"taste": "+"}, "맛"),
    (22, "naver_place", 5, "2026-10-25", "16:30", "디저트 메뉴가 다양해서 고르는 재미가 있어요", "positive", {"menu": "+"}, "메뉴"),
    (23, "baemin", 5, "2026-10-27", "15:15", "포장이 꼼꼼해서 하나도 안 흘렀어요", "positive", {"packaging": "+"}, "'안 흘렀어요'는 칭찬"),
    (24, "naver_place", 5, "2026-10-29", "10:40", "오전에는 한적해서 작업하기 좋아요", "positive", {"atmosphere": "+"}, "매장 환경 칭찬"),
    (25, "coupangeats", 4, "2026-10-31", "14:00", "배달이 빨라서 음료가 시원했어요", "positive", {"delivery_time": "+", "temperature": "+"}, "빠른 배달"),
    (26, "baemin", 4, "2026-11-08", "15:30", "바닐라라떼 달달하니 좋아요", "positive", {"taste": "+"}, "달달 칭찬 (7번과 반대)"),
    (27, "naver_place", 5, "2026-11-02", "15:45", "직원분들이 친절하고 매장이 청결해요", "positive", {"service": "+", "hygiene": "+"}, "응대·청결"),
    (28, "yogiyo", 5, "2026-11-05", "16:10", "가성비 좋은 카페예요", "positive", {"price": "+"}, "가성비"),
    # 무난
    (29, "naver_place", 3, "2026-10-17", "13:40", "자리가 좁고 의자가 불편해요", "negative", {"atmosphere": "-"}, "매장 환경 불만 1 (반복 아님)"),
    (30, "baemin", 3, "2026-11-03", "14:20", "그럭저럭이에요", "neutral", {}, "주제 없음"),
]

STORES = [(ONGI, ONGI_ROWS), (BASAK, BASAK_ROWS), (MONGLE, MONGLE_ROWS)]


def build(store: dict, rows: list):
    reviews, labels = [], []
    for n, channel, rating, day, hm, text, sentiment, topics, note in rows:
        rid = f"rv_{store['short']}_{n:03d}"
        reviews.append({
            "review_id": rid, "store_id": store["store_id"], "channel": channel, "rating": rating, "text": text,
            "created_at": f"{day}T{hm}:00+09:00", "input_method": "sample", "pii_masked": False,
            "data_origin": "synthetic",
        })
        expected = [{"topic": t, "polarity": "positive" if p == "+" else "negative"}
                    for t, ps in topics.items() for p in ps]
        labels.append({"review_id": rid, "expected_sentiment": sentiment, "expected_topics": expected, "note": note})
    return reviews, labels


def main():
    for store, rows in STORES:
        reviews, labels = build(store, rows)
        assert len({r["review_id"] for r in reviews}) == len(rows)
        meta = {k: v for k, v in store.items() if k != "short"}
        out = OUT / store["store_id"]
        out.mkdir(parents=True, exist_ok=True)
        for name, data in (("store.json", meta), ("reviews.json", reviews), ("labels.json", labels)):
            (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{store['name']}: 리뷰 {len(reviews)}건 → {out}")


if __name__ == "__main__":
    main()
