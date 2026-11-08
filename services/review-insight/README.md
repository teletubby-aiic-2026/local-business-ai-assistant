# 리뷰 분석 — C2 합성 리뷰 · C3 분류·묶음 · S2 직접 붙여넣기

가게 리뷰를 주제·감정으로 나누고, **같은 불만이 반복되는 묶음**을 찾아 C5 추천 카드·C6 생성에 넘깁니다.

| 일 | 내용 | 파일 |
|---|---|---|
| C2 합성 리뷰 | 가게 3곳 리뷰 100건 + 정답 라벨 (발표 시나리오는 `온기한식`) | `scripts/make_synthetic.py` → `data/synthetic/<store_id>/` |
| C3 분류 | HCX-005가 리뷰마다 주제·칭찬/불만·근거 구절을 고르고, 규칙으로 검사 | `app/classify.py`, `app/topics.py` |
| C3 묶음 | 같은 주제 불만이 최근 4주에 3건 이상이면 반복 묶음 (계산은 코드) | `app/cluster.py` |
| S2 붙여넣기 | 사장님이 붙여넣은 리뷰 → 개인정보 가림 → 바로 분류 → 묶음 다시 계산 | `app/service.py`, `app/main.py` |

## 실행

```bash
cd services/review-insight
python -m venv .venv && .venv/bin/pip install -r requirements.txt   # Windows: .\.venv\Scripts\pip
cp .env.example .env              # 키 없이 해 보려면 APP_MODE=mock 그대로
uvicorn app.main:app --port 8020  # http://localhost:8020 확인 화면
pytest -q                         # 시험 (키 필요 없음, CLOVA 응답은 가짜)
```

| `APP_MODE` | 동작 |
|---|---|
| `mock` | 모델 없이 규칙 분류기만 씀 |
| `live` | HCX-005 호출. 합성 리뷰 결과는 `data/replay/classify.json`에 저장 |
| `replay` | 저장본 재생 (발표용, C9). 저장본이 없는 리뷰만 규칙 분류 |

발표 재생본 만들기: `.env`에 키를 넣고 `APP_MODE=live python -m scripts.eval_classify` → 가게별로 정답 라벨과 비교한 정확도가 나오고 `data/replay/classify.json`이 생깁니다. 이 파일은 합성 데이터 결과라 저장소에 올려도 됩니다.

## C5·C6이 쓰는 API

`GET /api/review-insight/insight?store_id=store_ongi` (`store_id`를 빼면 `store_ongi`)

```json
{
  "store_id": "store_ongi", "period_start": "2026-10-12", "period_end": "2026-11-08",
  "review_count": 40,
  "sentiment_counts": {"negative": 19, "positive": 16, "mixed": 4, "neutral": 1},
  "topic_counts": {"delivery_time": {"positive": 1, "negative": 6}},
  "repeated_issues": [{
    "issue_id": "iss_delivery_time", "topic": "delivery_time", "topic_name": "배달 시간",
    "review_count": 6, "review_ids": ["rv_ongi_001", "..."],
    "evidence": [{"review_id": "rv_ongi_001", "quote": "1시간 넘게 걸려서 왔어요"}],
    "time_bands": {"00~06시": 0, "06~11시": 0, "11~14시": 0, "14~17시": 0, "17~21시": 6, "21~24시": 0},
    "main_time_band": "17~21시",
    "channels": {"baemin": 2, "coupangeats": 2, "yogiyo": 1},
    "recent_count": 6, "previous_count": 0,
    "first_at": "2026-10-28T19:40:00+09:00", "last_at": "2026-11-07T19:20:00+09:00"
  }],
  "classifications": [{"review_id": "rv_ongi_001", "sentiment": "negative",
    "topics": [{"topic": "delivery_time", "polarity": "negative", "evidence": "1시간 넘게 걸려서 왔어요"}],
    "negative_topics": ["delivery_time"], "summary": null, "method": "model", "model": "HCX-005", "warnings": []}],
  "data_origin": "synthetic"
}
```

- `time_bands`는 서울시 추정매출의 시간대 6구간과 같습니다 → 카드 ⓑ(저녁 매출 하락)와 `main_time_band == "17~21시"`로 바로 이어집니다.
- `evidence.quote`는 리뷰 글에 그대로 있는 구절입니다 (규칙으로 확인). 카드·답글에 근거로 인용해도 됩니다.
- 다른 화면에 붙일 때: `from app.main import router` → `app.include_router(router)`

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/review-insight/stores` | 가게 3곳 목록 + 기본 가게 |
| GET | `/api/review-insight/store?store_id=` | 가게 정보 |
| GET | `/api/review-insight/reviews?store_id=` | 합성 + 붙여넣은 리뷰 (최신순) |
| GET | `/api/review-insight/insight?store_id=` | 위 결과 |
| POST | `/api/review-insight/reviews` | S2 붙여넣기 `{store_id?, text, rating?, channel?}` → `{review, classification, joined_issues, repeated_issues}` (201) |
| DELETE | `/api/review-insight/reviews/pasted?store_id=` | 그 가게에 붙여넣은 리뷰만 지움 (데모 다시 하기) |

없는 가게는 404 `STORE_NOT_FOUND`.

오류는 모듈 규격 7절 형식 (`{"error": {"code": "VALIDATION_ERROR", ...}}`).

## 합성 리뷰 설계 (C2)

분류·묶음이 한 가게에만 맞춰지지 않았는지 보려고, 업종·바쁜 시간·반복 불만이 서로 다른 가게 3곳을 만들었습니다.

| 가게 | 업종 | 리뷰 | 심어 둔 반복 불만 (정답) | 몰린 시간 |
|---|---|---|---|---|
| `store_ongi` 온기한식 (발표 시나리오) | 한식 | 40 | 배달 시간 6 · 음식 온도 4 · 포장 3 · 양 4 | 저녁 17~21시 (양은 점심) |
| `store_basak` 바삭치킨 | 치킨 | 30 | 누락 4 · 식감(눅눅함) 4 · 배달 시간 3 | 밤 21~24시 |
| `store_mongle` 몽글카페 | 카페 | 30 | 매장 대기 5 · 음료 맛 3 · 포장 3 | 점심 11~14시 · 오후 14~17시 |

리뷰 ID는 가게마다 `rv_ongi_001`, `rv_basak_001`, `rv_mongle_001`처럼 붙습니다. 붙여넣은 리뷰는 `rv_ongi_paste_001`.

온기한식
- 저녁 매출 하락 상권의 한식집 시나리오. 반복 불만 4갈래를 일부러 심었습니다: **배달 시간 6 · 음식 온도 4 · 포장 3 (모두 저녁 17~21시)**, 양 4 (주로 점심).
- 누락 2건·매장 대기 2건·응대 1건·위생 1건은 기준(3건) 미만 → 묶이면 안 되는 대조군.
- 칭찬은 주로 점심. "점심은 잘 되는데 저녁 경험이 나쁘다"가 보이게 했습니다.
- '배달'이라는 단어 없이 지연을 말하는 글("70분 걸렸습니다"), 부정어가 칭찬인 글("국물 하나 안 샜어요"), 포장 주문을 뜻하는 '포장'("다음엔 포장해야겠네요") 같은 함정을 넣어 분류기를 시험합니다.
- 손님 닉네임·주소·전화번호 필드는 없습니다. 모든 레코드에 `data_origin: "synthetic"`.
- 가게·리뷰를 바꾸려면 `scripts/make_synthetic.py`의 표를 고치고 `python -m scripts.make_synthetic`.

## 규칙 검사 (C3)

모델이 낸 결과에서 아래를 코드가 다시 확인합니다. 고친 내용은 `warnings`에 남습니다.

1. 주제는 주제 사전(`app/topics.py`)에 있는 13개만
2. 근거 구절이 리뷰 글에 그대로 있어야 함 (지어낸 근거는 버림)
3. 감정은 주제의 칭찬/불만에 맞게 다시 계산
4. 요약에 금지 표현(원인 단정 "때문·탓", 손님 비하, 개인정보 모양)이 있으면 지움
5. 쓸 수 있는 주제가 하나도 안 남으면 규칙 분류로 대신 (`rule_fallback`)
6. 묶음의 리뷰 ID가 실제로 있고, 그 리뷰가 그 주제의 불만이고, 근거 구절이 그 리뷰에 있는지 확인

## 정직하게 밝힐 것

- 규칙 분류기는 온기한식 리뷰를 보며 단서 단어를 넣었습니다. 그래서 처음 보는 두 가게에서는 크게 떨어집니다 (아래, `APP_MODE=mock`). 바삭치킨·몽글카페 단서는 일부러 맞추지 않았습니다 — 맞추면 또 그 가게에만 맞는 규칙이 됩니다. **실제 성능 숫자로는 HCX-005(`APP_MODE=live`) 평가 결과를 씁니다.**

  | 규칙 분류기 | 감정 정확도 | 주제 재현율 | 반복 묶음 |
  |---|---|---|---|
  | 온기한식 (단서를 맞춘 가게) | 40/40 | 100% | 4갈래 모두 찾음 |
  | 바삭치킨 (처음 보는 가게) | 27/30 | 74% | 3갈래 중 2 (배달 시간 놓침) |
  | 몽글카페 (처음 보는 가게) | 24/30 | 56% | 3갈래 중 1 (매장 대기·음료 맛 놓침) |

- HCX-005 첫 평가 (프롬프트 `c3-v1`, 2026-11-08, 리뷰 100건):

  | HCX-005 | 감정 정확도 | 주제 정밀도 | 주제 재현율 | 반복 묶음 |
  |---|---|---|---|---|
  | 온기한식 | 39/40 | 91% | 79% | 4갈래 모두 찾음 |
  | 바삭치킨 | 29/30 | 94% | 86% | 3갈래 모두 찾음 |
  | 몽글카페 | 29/30 | 94% | 88% | 3갈래 모두 찾음 |
  | 전체 | 97% | 93% | 83% | 10갈래 모두 |

  틀린 21건은 대부분 한 리뷰의 두 번째 주제를 빠뜨린 것(예: '양도 넉넉하고 맛도 좋아요'에서 맛)이었고,
  방문 리뷰의 '음식이 늦게 나왔어요'를 배달 시간으로 고른 경우, 사전에 없는 '자리가 좁아요'를 다른 주제에 억지로 넣은 경우가 있었습니다.
  → 프롬프트 `c3-v2`에서 예시·채널 정보(naver_place=방문)·'맞는 주제가 없으면 비움' 규칙을 넣고, 주제 사전에 `매장 환경(atmosphere)`을 더했습니다.
  이때 사전에 주제가 없어 '주제 없음'으로 두었던 리뷰 4건의 정답 라벨을 `atmosphere`로 바꿨습니다 (온기 029, 몽글 017·024·029).
- `c3-v2` 평가에서는 리뷰를 한 줄에 하나씩(JSONL) 보냈더니 모델도 여러 덩어리로 답해 100건 중 30건을 읽지 못했습니다(규칙 분류로 대신).
  → `c3-v3`: 리뷰를 JSON 배열 하나로 보내고, 답을 읽는 쪽이 배열 여러 개·JSONL·일부 깨진 객체를 모두 건지며, 못 읽은 리뷰는 2건씩 한 번 더 물어봅니다.
  평가 결과의 `방식`에 `rule_fallback`이 있으면 그 수만큼은 모델 결과가 아니라는 뜻입니다.
- 붙여넣은 리뷰의 작성 시각은 붙여넣은 시각입니다 (원래 작성 시각을 모름).

## 남은 일

- [ ] C1 데이터 계약이 나오면 `app/models.py`를 그 dataclass로 바꾸기
- [ ] `APP_MODE=live`로 정확도 재고 `data/replay/classify.json` 올리기
- [ ] C4 상권이 정해지면 시나리오 가게 업종·이름을 거기에 맞추기 (`scripts/make_synthetic.py`)
- [ ] 바삭치킨·몽글카페에서 HCX-005가 반복 묶음을 모두 찾는지 확인
