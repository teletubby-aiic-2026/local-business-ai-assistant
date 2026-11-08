# 리뷰 분석 — C2 합성 리뷰 · C3 분류·묶음 · S2 직접 붙여넣기

가게 리뷰를 주제·감정으로 나누고 **불만을 묶어** C5 추천 카드·C6 생성에 넘깁니다.
결정안 v0.4의 브리핑 ①을 만듭니다: **리뷰 40건 → 불만 12건 → 3묶음(반복은 '포장 누락' 하나) + 단발 불만 5건**.

| 일 | 내용 | 파일 |
|---|---|---|
| C2 합성 리뷰 | 가게 3곳 리뷰 100건 + 정답 라벨. 발표 시나리오 `온기한식`은 와우 장면 숫자 그대로 | `scripts/make_synthetic.py` → `data/synthetic/<store_id>/` |
| C3 분류 | HCX-005가 리뷰마다 주제·칭찬/불만·근거 구절을 고르고, 규칙으로 검사 | `app/classify.py`, `app/topics.py` |
| C3 대비책 | 모델이 없거나 실패하면 kiwi 형태소 분석 규칙으로 분류 | `app/morph.py` |
| C3 묶음 | 같은 불만 2건 이상 = 묶음, 3건 이상 = 반복. 카드 ⓐ = 가장 큰 반복 묶음 (계산은 코드) | `app/cluster.py` |
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
| `mock` | 모델 없이 규칙 분류 (kiwi가 있으면 형태소 분석, 없으면 글자 단서) |
| `live` | HCX-005 호출. 합성 리뷰 결과는 `data/replay/classify.json`에 저장 |
| `replay` | 저장본 재생 (발표용, C9). 저장본이 없는 리뷰만 규칙 분류 |

발표 재생본 만들기: `.env`에 키를 넣고 `APP_MODE=live python -m scripts.eval_classify` → 가게별로 정답 라벨과 비교한 정확도·묶음 일치 여부가 나오고 `data/replay/classify.json`이 생깁니다. 이 파일은 합성 데이터 결과라 저장소에 올려도 됩니다.

## C5·C6이 쓰는 API

`GET /api/review-insight/insight?store_id=store_ongi` (`store_id`를 빼면 `store_ongi`)

```json
{
  "store_id": "store_ongi", "period_start": "2026-10-12", "period_end": "2026-11-08",
  "review_count": 40, "complaint_count": 12,
  "group_count": 3, "single_complaint_count": 5,
  "top_issue_id": "iss_missing_item",
  "groups": [{
    "issue_id": "iss_missing_item", "topics": ["missing_item"], "topic": "missing_item", "topic_name": "포장 누락",
    "review_count": 3, "is_repeated": true, "review_ids": ["rv_ongi_001", "rv_ongi_002", "rv_ongi_003"],
    "evidence": [{"review_id": "rv_ongi_001", "quote": "안 들어 있었어요"}],
    "time_bands": {"00~06시": 0, "06~11시": 0, "11~14시": 0, "14~17시": 0, "17~21시": 3, "21~24시": 0},
    "main_time_band": "17~21시", "channels": {"baemin": 1, "coupangeats": 1, "yogiyo": 1},
    "recent_count": 3, "previous_count": 0,
    "first_at": "2026-10-27T19:30:00+09:00", "last_at": "2026-11-06T19:50:00+09:00"
  }, {"issue_id": "iss_portion_taste", "topics": ["portion", "taste"], "topic_name": "양·맛", "review_count": 2, "is_repeated": false, "...": "..."}],
  "repeated_issues": ["groups 중 is_repeated인 것만"],
  "single_complaints": [{"review_id": "rv_ongi_008", "topics": ["hygiene"], "topic_names": ["위생"], "quote": "반찬 그릇에 머리카락이 있었어요", "created_at": "...", "channel": "naver_place"}],
  "sentiment_counts": {"negative": 12, "positive": 26, "neutral": 2},
  "topic_counts": {"missing_item": {"positive": 0, "negative": 3}},
  "classifications": [{"review_id": "rv_ongi_001", "sentiment": "negative",
    "topics": [{"topic": "missing_item", "polarity": "negative", "evidence": "안 들어 있었어요"}],
    "negative_topics": ["missing_item"], "summary": null, "method": "model", "model": "HCX-005", "warnings": []}],
  "data_origin": "synthetic"
}
```

- **카드 ⓐ**: `top_issue_id`가 가리키는 묶음 (가장 큰 반복 묶음). 반복 묶음이 없으면 `null`.
- `groups`는 반복 묶음이 먼저, 그다음 건수 순. 두 주제에 같은 리뷰들이 걸리면 한 묶음으로 합칩니다(`양·맛`).
- `time_bands`는 서울시 추정매출의 시간대 6구간과 같습니다 → 카드 ⓑ(저녁 매출 하락)와 `"17~21시"`로 이어 볼 수 있습니다.
- `evidence.quote`는 리뷰 원문에 그대로 있는 구절입니다 (규칙으로 확인). 카드·답글에 근거로 인용해도 됩니다.
- 다른 화면에 붙일 때: `from app.main import router` → `app.include_router(router)`

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/review-insight/stores` | 가게 3곳 목록 + 기본 가게 |
| GET | `/api/review-insight/store?store_id=` | 가게 정보 |
| GET | `/api/review-insight/reviews?store_id=` | 합성 + 붙여넣은 리뷰 (최신순) |
| GET | `/api/review-insight/insight?store_id=` | 위 결과 |
| POST | `/api/review-insight/reviews` | S2 붙여넣기 `{store_id?, text, rating?, channel?}` → `{review, classification, joined_issues, complaint_count, groups, repeated_issues, single_complaints, top_issue_id}` (201) |
| DELETE | `/api/review-insight/reviews/pasted?store_id=` | 그 가게에 붙여넣은 리뷰만 지움 (데모 다시 하기) |

없는 가게는 404 `STORE_NOT_FOUND`. 오류는 모듈 규격 7절 형식 (`{"error": {"code": "VALIDATION_ERROR", ...}}`).

## 합성 리뷰 설계 (C2)

| 가게 | 업종 | 리뷰 | 정답 묶음 | 단발 |
|---|---|---|---|---|
| `store_ongi` 온기한식 (**발표 시나리오**) | 한식 | 40 (불만 12) | **포장 누락 3 (반복, 카드 ⓐ)** · 늦은 배달 2 · 양·맛 2 | 5 (위생·응대·온도·가격·식감) |
| `store_basak` 바삭치킨 (시험용) | 치킨 | 30 (불만 16) | 포장 누락 4 · 식감 4 · 배달 시간 3 (모두 반복) · 가격 2 | 3 |
| `store_mongle` 몽글카페 (시험용) | 카페 | 30 (불만 16) | 매장 대기 5 · 맛 3 · 포장 상태 3 (모두 반복) · 가격 2 | 3 |

- 온기한식은 결정안 v0.4 와우 장면 숫자 그대로입니다. 불만은 주로 저녁(17~21시), 칭찬은 주로 점심.
- 바삭치킨·몽글카페는 업종·바쁜 시간·불만이 달라서, 분류·묶음이 시나리오 가게에만 맞춰지지 않았는지 보는 시험용입니다.
- 함정: '배달' 없이 지연을 말하는 글, 부정어가 칭찬인 글("국물 하나 안 샜어요"), 포장 주문을 뜻하는 '포장', 매장 방문인데 "오래 걸려요", '포장 상태' 칭찬과 '포장 누락' 불만.
- 리뷰 ID는 `rv_ongi_001`처럼 가게별. 붙여넣은 리뷰는 `rv_ongi_paste_001`. 손님 닉네임·주소·전화번호 필드는 없고, 모든 레코드에 `data_origin: "synthetic"`.
- 가게·리뷰를 바꾸려면 `scripts/make_synthetic.py`의 표를 고치고 `python -m scripts.make_synthetic`.

## 규칙 검사 (C3)

모델이 낸 결과에서 아래를 코드가 다시 확인합니다. 고친 내용은 `warnings`에 남습니다.

1. 주제는 주제 사전(`app/topics.py`)에 있는 13개만
2. 근거 구절이 리뷰 원문에 있어야 함 (띄어쓰기·문장부호 차이는 봐주고, 원문 그대로의 구절로 저장)
3. 감정은 주제의 칭찬/불만에 맞게 다시 계산
4. 요약에 금지 표현(원인 단정 "때문·탓", 손님 비하, 개인정보 모양)이 있으면 지움
5. 쓸 수 있는 주제가 하나도 안 남으면 규칙 분류로 대신 (`rule_fallback`)
6. 묶음의 리뷰가 실제로 있고, 묶음의 모든 주제에 불만이고, 근거 구절이 원문에 있는지 확인 (어긋나면 빼고 경고)

## kiwi 형태소 분석 (규칙 대비책)

상권 비서(PR #13)와 같은 `kiwipiepy==0.24.1`을 씁니다. 글자 그대로 찾는 규칙은 '식었어요/식어서/식은'처럼 말끝이 바뀌면 놓치는데,
kiwi로 기본형('식다')으로 바꾸고 '안 바삭해요', '하나도 안 샜어요' 같은 부정도 읽습니다. 매장 방문 리뷰(naver_place)의 "오래 걸려요"는 매장 대기로 봅니다.
설치되어 있지 않으면 예전 글자 단서로 돌아갑니다.

## 정직하게 밝힐 것

- **규칙 분류기 점수는 처음 보는 리뷰 성적이 아닙니다.** 글자 단서는 온기한식을, kiwi 단서는 세 가게의 틀린 리뷰를 보면서 넣었습니다.
  성능 숫자로는 HCX-005(`APP_MODE=live`) 평가를 쓰고, 규칙은 대비책으로만 말합니다. (`APP_MODE=mock`, 합성 100건)

  | 규칙 분류기 | 온기한식 | 바삭치킨 | 몽글카페 |
  |---|---|---|---|
  | 글자 단서 (주제 재현율) | 82% · 포장 누락을 2건으로 봐서 카드 ⓐ 없음 | 74% · 묶음 불일치 | 56% · 묶음 불일치 |
  | kiwi 단서 (주제 재현율) | 98% · 와우 숫자 일치 | 94% · 묶음 일치 | 97% · 묶음 일치 |

- HCX-005 첫 평가 (프롬프트 `c3-v1`, 11/8, 이때는 온기한식이 와우에 맞추기 전 데이터):

  | HCX-005 | 감정 정확도 | 주제 정밀도 | 주제 재현율 | 반복 묶음 |
  |---|---|---|---|---|
  | 온기한식 (이전 데이터) | 39/40 | 91% | 79% | 4갈래 모두 찾음 |
  | 바삭치킨 | 29/30 | 94% | 86% | 3갈래 모두 찾음 |
  | 몽글카페 | 29/30 | 94% | 88% | 3갈래 모두 찾음 |

  틀린 21건은 대부분 한 리뷰의 두 번째 주제를 빠뜨린 것이었고, 방문 리뷰의 '늦게 나옴'을 배달 시간으로 고르거나 사전에 없는 '자리가 좁아요'를 억지로 넣은 경우가 있었습니다.
  → `c3-v2`: 여러 주제 예시·채널 정보(naver_place=방문)·'맞는 주제가 없으면 비움', 주제 사전에 `매장 환경(atmosphere)` 추가.
  이때 '주제 없음'이던 정답 라벨 4건을 `atmosphere`로 바꿨습니다.
- `c3-v2` 평가에서 리뷰를 한 줄에 하나씩(JSONL) 보냈더니 모델도 여러 덩어리로 답해 30/100건을 읽지 못했습니다.
  → `c3-v3`: 리뷰를 JSON 배열 하나로 보내고, 배열 여러 개·JSONL·일부 깨진 객체를 모두 건지며, 못 읽은 리뷰는 2건씩 한 번 더 묻습니다.
  평가 결과의 `방식`에 `rule_fallback`이 있으면 그 수만큼은 모델 결과가 아닙니다.
- 와우 숫자(불만 12 · 3묶음 · 단발 5)는 분류 결과에 따라 달라질 수 있습니다. 결정안대로 발표에서는 HCX-005 결과를 재생본(C9)으로 고정해 씁니다.
- 붙여넣은 리뷰의 작성 시각은 붙여넣은 시각입니다 (원래 작성 시각을 모름).

## 남은 일

- [ ] `APP_MODE=live`(c3-v3)로 새 온기한식에서 와우 숫자가 그대로 나오는지 확인하고 `data/replay/classify.json` 올리기
- [ ] C1 데이터 계약이 나오면 `app/models.py`를 그 dataclass로 바꾸기
- [ ] C4 상권이 정해지면 시나리오 가게 업종·이름을 거기에 맞추기 (`scripts/make_synthetic.py`)
- [ ] 처음 보는 리뷰로 규칙·모델 점수 다시 재기 (홀드아웃)
