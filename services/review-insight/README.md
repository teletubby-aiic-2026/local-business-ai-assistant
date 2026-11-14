# 리뷰 분석 모듈 (C2 · C3 · S2)

가게 리뷰를 읽고 **불만을 주제별로 묶어서**, 사장님 브리핑과 추천 카드에 쓸 결과를 만듭니다.

```
리뷰 40건 → 불만 12건 → 묶음 3개(반복은 '포장 누락' 하나) + 단발 불만 5건
                            └─ 카드 ⓐ = 포장 누락 3건 (근거 문장 3개와 함께)
```

| 담당 | 하는 일 |
|---|---|
| **C2 합성 리뷰** | 시연·시험용 가짜 리뷰와 정답표를 만듭니다 (가게 3곳, 100건) |
| **C3 분류·묶음** | AI(HCX-005)가 리뷰마다 주제를 붙이고, 코드가 검사한 뒤 같은 불만끼리 묶습니다 |
| **S2 직접 붙여넣기** | 사장님이 배달앱 리뷰를 복사해 넣으면 바로 분류·묶음에 들어갑니다 |

- 분류 내용(주제 분류 + 묶음)은 **결정안 v0.4**, 공통 규칙(필드·API 모양·오류·키 이름)은 **`docs/module-io-spec.md` v0.1**을 따릅니다.
- 모든 데이터는 합성 데이터이며 `data_origin: "synthetic"`이 붙습니다. 손님 닉네임·주소·전화번호 필드는 없습니다.

---

## 1. 팀원이 가져다 쓰는 법

### 방법 ① API로 부르기 (추천)

모듈을 서버로 켜 두고, 다른 코드에서 주소로 부릅니다.

```bash
cd services/review-insight
uvicorn app.main:app --port 8020
```

```python
import httpx
API = "http://localhost:8020/api/review-insight"

# 브리핑 결과 (C5 추천 카드, C6 답글·공지가 쓰는 것)
ins = httpx.get(f"{API}/insight", params={"store_id": "store_ongi"}).json()
ins["review_count"], ins["complaint_count"]                 # 40, 12
top = next(g for g in ins["groups"] if g["issue_id"] == ins["top_issue_id"])
top["topic_name"], top["review_count"]                      # '포장 누락', 3   ← 카드 ⓐ
[e["quote"] for e in top["evidence"]]                       # 근거 문장 3개   ← 답글·공지에 인용

# 리뷰 붙여넣기 (C7 화면의 입력칸)
r = httpx.post(f"{API}/reviews", json={"text": "공깃밥이 또 빠져 있었어요", "rating": 1, "channel": "baemin"}).json()
r["classification"]["negative_topics"]                      # ['missing_item']
r["joined_issues"]                                          # ['iss_missing_item']  ← 들어간 묶음
```

브라우저에서 `http://localhost:8020/docs`를 열면 모든 주소를 클릭으로 시험해 볼 수 있습니다. `http://localhost:8020/`은 사람이 보는 확인 화면입니다.

### 방법 ② 파이썬 함수로 바로 부르기

```python
from app import service
from app.classify import Classifier
ins = service.analyze(Classifier(), "store_ongi")   # /insight 와 같은 결과 (ReviewInsight)
```

> ⚠️ 상권분석 모듈도 패키지 이름이 `app`이라서, **한 프로그램 안에서 두 모듈을 같이 import하면 이름이 부딪힙니다.** 다른 모듈과 함께 쓸 때는 방법 ①을 쓰세요.

### 방법 ③ 데이터 파일 바로 읽기

분류 없이 가짜 리뷰 원본만 필요할 때 (붙여넣은 리뷰는 들어 있지 않음).

```python
import json
reviews = json.load(open("services/review-insight/data/synthetic/store_ongi/reviews.json", encoding="utf-8"))
```

### API 주소

| 메서드 | 주소 | 하는 일 | 주로 쓰는 곳 |
|---|---|---|---|
| GET | `/api/review-insight/insight?store_id=` | **브리핑 결과 전체** (묶음, 단발, 카드 ⓐ, 근거 문장, 리뷰별 분류) | C5 카드, C6 생성 |
| POST | `/api/review-insight/reviews` | **리뷰 붙여넣기** `{store_id?, text, rating?, channel?}` → 분류 결과와 바뀐 묶음 (201) | C7 화면 |
| GET | `/api/review-insight/reviews?store_id=` | 리뷰 목록 `{items, count}` (최신순, 가짜 + 붙여넣은 것) | 화면 |
| GET | `/api/review-insight/reviews/{review_id}?store_id=` | 리뷰 한 건 + 분류 결과. 없으면 404 `REVIEW_NOT_FOUND` | 화면 |
| DELETE | `/api/review-insight/reviews/pasted?store_id=` | 붙여넣은 리뷰만 지움 (데모 다시 하기) | 발표 준비 |
| GET | `/api/review-insight/stores` | 가게 목록 `{items, count, default}` | 화면 |
| GET | `/api/review-insight/store?store_id=` | 가게 정보 (이름, 업종, 메뉴) | 화면 |
| GET | `/api/health` | 켜져 있는지, 실행 모드, 규격 버전 | 확인용 |

- `store_id`를 빼면 발표용 가게 `store_ongi`입니다. 없는 가게는 404 `STORE_NOT_FOUND`.
- 오류는 규격 7절 모양입니다: `{"error": {"code", "message", "retryable", "details", "request_id"}}`
- 모든 응답에 `X-Request-Id` 헤더가 붙습니다. 오류를 물어볼 때 이 번호를 알려 주세요.

---

## 2. 결과(`/insight`) 읽는 법

```json
{
  "store_id": "store_ongi", "period_start": "2026-10-12", "period_end": "2026-11-08",
  "review_count": 40, "complaint_count": 12, "group_count": 3, "single_complaint_count": 5,
  "top_issue_id": "iss_missing_item",
  "groups": [
    {
      "issue_id": "iss_missing_item", "topics": ["missing_item"], "topic_name": "포장 누락",
      "review_count": 3, "is_repeated": true,
      "review_ids": ["rv_ongi_001", "rv_ongi_002", "rv_ongi_003"],
      "evidence": [{"review_id": "rv_ongi_001", "quote": "안 들어 있었어요"}],
      "time_bands": {"00~06시": 0, "06~11시": 0, "11~14시": 0, "14~17시": 0, "17~21시": 3, "21~24시": 0},
      "main_time_band": "17~21시", "channels": {"baemin": 1, "coupangeats": 1, "yogiyo": 1},
      "recent_count": 3, "previous_count": 0
    },
    {"issue_id": "iss_portion_taste", "topics": ["portion", "taste"], "topic_name": "양·맛", "review_count": 2, "is_repeated": false},
    {"issue_id": "iss_delivery_time", "topic_name": "배달 시간", "review_count": 2, "is_repeated": false}
  ],
  "single_complaints": [{"review_id": "rv_ongi_008", "topic_names": ["위생"], "quote": "반찬 그릇에 머리카락이 있었어요"}],
  "classifications": [{"review_id": "rv_ongi_001", "sentiment": "negative",
    "topics": [{"topic": "missing_item", "polarity": "negative", "evidence": "안 들어 있었어요"}],
    "method": "model", "model": "HCX-005", "warnings": []}],
  "data_origin": "synthetic"
}
```

| 필드 | 뜻 |
|---|---|
| `complaint_count` | 불만이 하나라도 있는 리뷰 수 |
| `groups` | 같은 불만이 **2건 이상**인 묶음. 반복 묶음이 먼저, 그다음 건수 순 |
| `is_repeated` | **3건 이상**이면 `true` (반복) |
| `top_issue_id` | **카드 ⓐ** = 가장 큰 반복 묶음. 반복이 없으면 `null` |
| `topics` / `topic_name` | 같은 리뷰들이 두 주제에 함께 걸리면 한 묶음으로 합칩니다 (예: `양·맛`) |
| `evidence[].quote` | 리뷰 원문에 그대로 있는 근거 문장 (코드가 확인). 카드·답글에 인용해도 됩니다 |
| `time_bands`, `main_time_band` | 서울시 추정매출과 같은 시간대 6구간. 한 구간에 60% 이상 몰리면 `main_time_band` → 카드 ⓑ(저녁 매출)와 이어 볼 수 있음 |
| `recent_count` / `previous_count` | 기간 뒤쪽 절반 / 앞쪽 절반의 건수 (늘었는지 줄었는지) |
| `single_complaints` | 어느 묶음에도 들지 않은 불만 (단발) |
| `classifications[].method` | `model`(AI), `replay`(저장본), `rule`(규칙), `rule_fallback`(AI 실패로 규칙이 대신) |
| `classifications[].warnings` | 코드가 AI 결과를 고친 내용, AI·규칙 결과가 다른 곳 (`규칙 비교: …`) |

---

## 3. 구조

```
services/review-insight/
├─ app/
│   ├─ main.py        API 주소들, 오류 모양, X-Request-Id
│   ├─ service.py     [S2] 붙여넣기 저장 · 리뷰 합치기 · 분석 실행(analyze)
│   ├─ classify.py    [C3] HCX-005 분류 · 답 읽기 · 검사 · 저장/재생 · 사용량 기록
│   ├─ morph.py       kiwi 형태소 분석 (AI 참고 자료 + 규칙 분류)
│   ├─ examples.py    비슷한 예문 찾기 (AI 참고 자료)
│   ├─ topics.py      주제 사전 13개 · 금지 표현 · 개인정보 가림 · 규칙 분류기
│   ├─ cluster.py     [C3] 묶음 · 반복 · 단발 · 카드 ⓐ 계산 (AI 없이 코드만)
│   ├─ models.py      데이터 모양 (Review, ReviewClassification, IssueGroup, ReviewInsight)
│   └─ static/index.html  확인 화면
├─ data/
│   ├─ synthetic/<가게>/   [C2] store.json · reviews.json · labels.json
│   ├─ lexicon/review_cues.json       규칙 분류기 단어 목록 (팀원이 고칠 수 있음)
│   ├─ examples/review_examples.json  AI에게 보여 줄 예문 26개 (팀원이 고칠 수 있음)
│   ├─ replay/classify.json           발표용 AI 결과 저장본 (live로 돌리면 생김)
│   └─ runtime/                       [S2] 붙여넣은 리뷰 (저장소에 안 올림)
├─ scripts/
│   ├─ make_synthetic.py   [C2] 가짜 리뷰·정답표 만들기
│   ├─ eval_classify.py    AI 결과를 정답표와 비교해 점수 내기
│   ├─ make_benchmark.py   벤치마크 원본(한 줄 형식) → 리뷰·정답 JSON
│   └─ eval_benchmark.py   벤치마크 채점 (주제별·유형별 점수)
└─ tests/   자동 시험 (키 없이 돎)
```

### 흐름

```
[C2] 가짜 리뷰 (data/synthetic)  ┐
[S2] 붙여넣은 리뷰 (data/runtime) ┴→ 모든 리뷰 (같은 Review 모양)
                                     │
                     ① kiwi가 먼저 읽음: 형태소, 규칙 추측, 비슷한 예문
                                     │
                     ② HCX-005가 분류 (리뷰 + 참고 자료, 6건씩)
                        → 리뷰마다 주제 · 칭찬/불만 · 근거 문장
                                     │
                     ③ 코드가 검사 (아래 5절) → 실패하면 kiwi 규칙으로 대신
                                     │
                     ④ 코드가 묶음 계산 (cluster.py)
                        2건↑ 묶음, 3건↑ 반복, 가장 큰 반복 = 카드 ⓐ
                                     │
                     GET /insight → C5 카드 · C6 답글·공지 · C7 화면
```

---

## 4. 데이터 (C2)

### 파일 세 개의 역할

| 파일 | 내용 | 누가 보나 |
|---|---|---|
| `store.json` | 가게 이름, 업종, 메뉴 | 화면, kiwi 사용자 사전 |
| `reviews.json` | 리뷰 (ID, 채널, 별점, 글, 작성 시각, `order_ref`, `status`) | **AI는 이것만 봄** (시험지) |
| `labels.json` | 리뷰마다 정답 감정·정답 주제·만든 의도 | **채점할 때만** (정답지, AI에게 안 보여 줌) |

### 가게 3곳

| 가게 | 업종 | 리뷰 | 정답 묶음 | 단발 |
|---|---|---|---|---|
| `store_ongi` 온기한식 (**발표용**) | 한식 | 40 (불만 12) | **포장 누락 3 (반복, 카드 ⓐ)** · 늦은 배달 2 · 양·맛 2 | 5 |
| `store_basak` 바삭치킨 (시험용) | 치킨 | 30 (불만 16) | 포장 누락 4 · 식감 4 · 배달 시간 3 (모두 반복) · 가격 2 | 3 |
| `store_mongle` 몽글카페 (시험용) | 카페 | 30 (불만 16) | 매장 대기 5 · 맛 3 · 포장 상태 3 (모두 반복) · 가격 2 | 3 |

- 온기한식은 결정안 v0.4 와우 장면 숫자 그대로입니다. 불만은 주로 저녁(17~21시), 칭찬은 주로 점심.
- 다른 두 가게는 업종·바쁜 시간·불만이 달라서, 분류가 발표용 가게에만 맞춰지지 않았는지 확인하는 데 씁니다.
- 분류기를 시험하는 리뷰도 넣었습니다: '배달' 없이 늦었다는 글, "국물 하나 안 샜어요"(칭찬), "다음엔 포장해야겠네요"(포장 주문), 매장 방문인데 "오래 걸려요"(매장 대기).
- 리뷰 ID는 `rv_ongi_001`처럼 가게별, 붙여넣은 리뷰는 `rv_ongi_paste_001`.
- **바꾸는 법**: `scripts/make_synthetic.py`의 표(한 줄 = 리뷰 하나 + 정답)를 고치고 `python -m scripts.make_synthetic`.

---

## 5. 분류와 검사 (C3)

### 주제 사전 (13개)

양 `portion` · 맛 `taste` · 가격 `price` · 식감 `texture` · 배달 시간 `delivery_time` · 음식 온도 `temperature` · 포장 상태 `packaging` · 포장 누락 `missing_item` · 응대 `service` · 위생 `hygiene` · 메뉴 구성 `menu` · 매장 환경 `atmosphere` · 매장 대기 `wait_time`

### 코드가 AI 결과를 다시 검사하는 것

1. 주제가 사전 13개 안에 있는가 (아니면 버림)
2. 근거 문장이 리뷰 원문에 있는가 (지어낸 근거는 버림, 띄어쓰기·문장부호 차이는 봐줌)
3. 감정(칭찬/불만/섞임)이 주제와 맞는가 (안 맞으면 고침)
4. 요약에 금지 표현("때문·탓" 같은 원인 단정, 손님 비하, 개인정보 모양)이 있는가 (있으면 지움)
5. 쓸 수 있는 주제가 하나도 안 남으면 kiwi 규칙으로 대신 (`rule_fallback`)
6. 묶음 속 리뷰가 정말 그 불만인지, 근거 문장이 원문에 있는지 (어긋나면 빼고 경고)

### kiwi 결합

상권 비서(PR #13)와 같은 구조입니다. **판단은 AI가, 검사는 코드가** 하고, kiwi는 AI에게 줄 참고 자료를 만듭니다.

AI가 실제로 받는 내용:
```
[비슷한 예문]
- "양이 적고 맛도 밍밍했어요" (baemin) → portion:-, taste:- (negative)

[리뷰]
{ "text": "양도 적고 간도 너무 싱거웠어요",
  "morphemes": "양/NNG 적다/VA 간/NNG 너무/MAG 싱겁다/VA-I",   ← kiwi 형태소
  "rule_guess": ["taste:-", "portion:-"] }                     ← 규칙 분류기 추측
```
프롬프트에서 "참고 자료가 리뷰 뜻과 다르면 따르지 말되, `rule_guess`의 주제를 빠뜨리지 않았는지는 확인하라"고 알려 줍니다.
`REVIEW_KIWI_HINTS=off`로 참고 자료를 빼고 같은 리뷰로 점수를 비교할 수 있습니다.

kiwipiepy 0.24.1의 기능을 그대로 씁니다:

| kiwi 기능 | 쓰는 곳 |
|---|---|
| `token.lemma` (기본형) | '식었어요' → 식다, '퍽퍽했어요' → 퍽퍽하다 |
| `tokenize(typos="basic_with_continual")` (오타 교정) | '맛잇긴한데 양이 저거요' → 맛있다, 적다. `REVIEW_MORPH_TYPOS=off`로 끔 |
| 낱말 위치 + 연결어미(EC)·문장부호(SF) 태그 | 구절 나누기: '맛은 있는데 / 겉이 눅눅해요'. 구절은 원문 그대로라 근거 문장으로 씀 |
| `W_EMAIL`·`W_URL`·`W_SERIAL` 태그 | 붙여넣은 리뷰의 개인정보 가림 (정규식과 함께, 숫자열은 9자리 이상만) |
| `add_user_word` (사용자 사전) | 메뉴 이름이 한 낱말로 남게 (치킨무, 순두부찌개 …) |
| `Kiwi(model_type="cong")` | 0.22부터 기본 모델. 결과가 항상 같게 명시 |
| 부정: '안·못'(MAG) 앞, '-지 않다·못하다' 뒤 | '하나도 안 바삭해요' → 식감 불만, '국물 하나 안 샜어요' → 포장 칭찬 |

kiwi가 설치되어 있지 않거나 `REVIEW_MORPH=off`면 글자 단서로 돌아갑니다.

---

## 6. 붙여넣기 (S2)

```
"저녁에 시켰는데 공깃밥이 또 빠져 있었어요. 연락처 010-1234-5678"  (+ 별점 1, 배민)
 ① 검사: 1~1,000자, 별점 1~5, 채널 이름          → 틀리면 400 VALIDATION_ERROR
 ② 개인정보 가림: 전화번호·이메일·링크 → [가림]    → pii_masked: true (원문은 저장 안 함)
 ③ 빈칸 채우기: rv_ongi_paste_001, 지금 시각, input_method: "paste"
 ④ 저장: data/runtime/pasted_<가게>.json (저장소에 안 올림)
 ⑤ 가짜 리뷰와 합쳐서 바로 분류·묶음 다시 계산 → 포장 누락 3건 → 4건
```

- 대회 동안에는 붙여넣기에도 합성 리뷰만 씁니다 (규격 9.2).
- 붙여넣은 리뷰의 작성 시각은 붙여넣은 시각입니다 (원래 작성 시각을 모름).

### 방문자별 구분과 DB 저장 (선택)

- **방문자 id (선택 인자)**: `GET /reviews`, `GET /reviews/{id}`, `GET /insight`, `DELETE /reviews/pasted` 는 쿼리 `visitor_id`, `POST /reviews` 는 본문의 `visitor_id` 로 받습니다. 주면 합성 리뷰(모두에게 같음)에 **그 방문자가 붙여넣은 리뷰만** 더해 보여 주고·분석하고·지웁니다. 안 주면 지금까지처럼 모두가 쓰는 공용 값이고, 이 폴더의 자체 화면과 기존 시험이 그렇게 돕니다.
  영문·숫자·`-`·`_` 1~64자만 받고 (파일 이름에 들어가므로 `/`·`.`·줄바꿈은 400 `VALIDATION_ERROR`), 비서 화면 서버가 쿠키로 만든 값을 넘깁니다.
  파일 방식에서는 `data/runtime/visitors/<방문자>/pasted_<가게>.json` 에 따로 둡니다 (공용은 `pasted_<가게>.json` 그대로).
- **DB 저장**: 환경 변수 `DB_HOST` (+ `DB_PORT`·`DB_NAME`·`DB_USER`·`DB_PASSWORD`)가 있으면 붙여넣은 리뷰(`reviews` 표)와 그 분류 결과(`review_labels` 표)를 PostgreSQL 에 둡니다. 없으면 위의 파일 그대로입니다.
  표 정의는 저장소 루트의 `db/schema.sql`, 만들기는 저장소 루트에서 `python -m shared.storage.init_db`. 코드는 저장소 루트의 `shared/storage` 라서 **서버에서는 `PYTHONPATH` 에 저장소 루트를 줍니다**
  (이 폴더에서 직접 실행하면 루트를 찾아 붙입니다). Dockerfile 이미지는 이 폴더만 담아서 DB 방식을 쓰지 못하고 파일 방식으로만 돕니다.
- DB 에 닿지 못하면 (장애 전환 중 등) 500 이 아니라 **503 `STORAGE_UNAVAILABLE`** (`retryable: true`) 로 답하고, DB 가 돌아오면 서비스를 다시 켜지 않아도 다음 요청부터 됩니다.

---

## 7. 실행과 설정

```bash
cd services/review-insight
python -m venv .venv && .venv/bin/pip install -r requirements.txt   # Windows: .\.venv\Scripts\pip
cp .env.example .env              # 키 없이 해 보려면 APP_MODE=mock 그대로
uvicorn app.main:app --port 8020  # 서버 켜기
pytest -q                         # 시험 (키 필요 없음, CLOVA 응답은 가짜)
```

| `APP_MODE` | 하는 일 | 쓰는 때 |
|---|---|---|
| `mock` | AI 없이 kiwi 규칙으로 분류 | 키 없이 개발할 때 |
| `live` | HCX-005를 진짜로 부름. 가짜 리뷰 결과는 `data/replay/classify.json`에 저장 | 평가, 재생본 만들기 |
| `replay` | 저장해 둔 AI 결과를 다시 씀 (AI를 안 부름) | **발표 (C9)**: 매번 같은 결과, 인터넷·한도 문제 대비 |

| `.env` | 기본값 | 뜻 |
|---|---|---|
| `CLOVASTUDIO_API_KEY` | (없음) | CLOVA Studio 키. 상권 비서가 쓰는 `CLOVA_STUDIO_API_KEY`도 읽음 |
| `LLM_MODEL_REVIEW` | `HCX-005` | 분류 모델 |
| `LLM_TIMEOUT_SECONDS` | `20` | AI 호출 한 번의 시간 제한 |
| `REVIEW_KIWI_HINTS` | `on` | AI에게 kiwi 참고 자료를 줄지 |
| `REVIEW_MORPH` | `on` | kiwi 사용 여부 |
| `REVIEW_MORPH_TYPOS` | `basic_with_continual` | kiwi 오타 교정 (`off`로 끔) |
| `APP_ACCESS_TOKEN` | (없음) | 밖에 띄울 때만. 정하면 `X-Access-Token` 헤더가 맞는 요청만 받음 (없으면 401 `UNAUTHORIZED`) |

- AI 호출은 일시 오류(429·5xx·시간 초과)면 1번 다시 시도하고, 키 오류(400·401·403)는 바로 실패합니다.
- 호출마다 `logs/llm_usage.jsonl`에 토큰·시간만 한 줄씩 남깁니다 (리뷰 글은 남기지 않음, 저장소에 안 올림).

### 벤치마크 (처음 보는 리뷰로 재기)

`data/benchmark/v1/`: 가게 5곳의 합성 리뷰 600건과 정답 (연습용 360 · 시험용 240, HCX 없이 사람이 씀). 정답 기준 `GUIDE.md`, 점수표 `RESULTS.md`.
```bash
python -m scripts.make_benchmark                          # source/*.txt → JSON (정답 형식 검사)
python -m scripts.eval_benchmark --split dev              # 연습용: 틀린 리뷰를 보고 고쳐도 됨
APP_MODE=live python -m scripts.eval_benchmark --split test   # 시험용: 점수만 (보면서 고치지 않기)
```
live 결과는 `data/benchmark/v1/runs/`에 저장해 같은 프롬프트로 다시 채점할 때 HCX를 다시 부르지 않습니다 (저장소에는 안 올림).

### 평가와 발표용 저장본 만들기

```bash
APP_MODE=live python -m scripts.eval_classify                        # kiwi 참고 자료 켬
APP_MODE=live REVIEW_KIWI_HINTS=off python -m scripts.eval_classify  # 끔 (비교용)
```
가게별로 감정 정확도, 주제 정밀도·재현율, 불만 수·단발 수·묶음이 정답과 같은지 나오고, `data/replay/classify.json`이 생깁니다.
이 파일은 합성 데이터 결과라 저장소에 올려도 됩니다. 발표 때는 `APP_MODE=replay`로 켭니다.

---

### 서버에 띄우기 (지금: 고객응대 서버, 나중에: 팀 공용 서브계정)

어느 서버든 같은 방법입니다. 서버를 옮길 때도 아래를 새 서버에서 다시 하면 됩니다.

```bash
cd ~/local-business-ai-assistant && git pull
cd services/review-insight
cp .env.example .env    # 처음 한 번: 키, APP_MODE, APP_ACCESS_TOKEN 채우기
docker build -t review-insight .
docker rm -f review-insight 2>/dev/null
docker run -d --name review-insight --restart unless-stopped -p 8020:8020 --env-file .env \
  -v $(pwd)/data/replay:/app/data/replay -v $(pwd)/data/runtime:/app/data/runtime -v $(pwd)/logs:/app/logs \
  review-insight
```

- NCP 서버의 ACG(방화벽)에 **8020번 포트**를 열어야 밖에서 들어옵니다.
- 밖에 띄울 때는 `.env`에 **`APP_ACCESS_TOKEN`을 꼭 정합니다** (규격 9.1). 그러면 `X-Access-Token` 헤더에 같은 값을 보낸 요청만 받습니다.
  `/docs`는 오른쪽 위 **Authorize**에, 확인 화면은 처음 뜨는 **접근 토큰** 칸에 넣으면 됩니다. 토큰은 카톡으로만 공유합니다.
- 서버 모드는 `replay`를 권합니다 (AI를 다시 부르지 않아 크레딧을 안 씀). 저장본이 아직 없으면 그 리뷰만 규칙 분류로 돌아갑니다.
- 주소: 확인 화면 `http://<서버>:8020/`, API 설명서 `http://<서버>:8020/docs`, API `http://<서버>:8020/api/review-insight/...`

```python
# 팀원 코드에서 서버 API 부르기
httpx.get("http://<서버>:8020/api/review-insight/insight", headers={"X-Access-Token": "<팀 토큰>"})
```

## 8. 팀원이 고칠 수 있는 파일

| 파일 | 무엇을 | 고친 뒤 |
|---|---|---|
| `data/lexicon/review_cues.json` | 규칙 분류기 단어 목록. 낱말은 kiwi 기본형으로 (예: '불어서' → `붇다`) | `pytest -q`, `python -m scripts.eval_classify` |
| `data/examples/review_examples.json` | AI에게 보여 줄 예문. **채점용 가짜 리뷰 문장은 넣지 않음** (시험이 막음) | `pytest -q` |
| `scripts/make_synthetic.py` | 가짜 리뷰와 정답표 | `python -m scripts.make_synthetic` 후 `pytest -q` |

---

## 9. 정직하게 밝힐 것

- **규칙 분류기 점수는 처음 보는 리뷰 성적이 아닙니다.** 단어 목록을 이 가짜 리뷰 100건을 보며 다듬었기 때문입니다.
  같은 이유로 이 세트에서는 AI에게 주는 `rule_guess`도 실제보다 정확합니다. 성능 숫자로는 HCX-005 평가를 쓰고, 처음 보는 리뷰로 다시 재야 공정합니다.

  | 규칙 분류기 (`APP_MODE=mock`, 주제 재현율) | 온기한식 | 바삭치킨 | 몽글카페 |
  |---|---|---|---|
  | 글자 단서만 (kiwi 전) | 82% · 카드 ⓐ 없음 | 74% | 56% |
  | kiwi 단서 (지금) | 100% · 와우 숫자 일치 | 97% · '맛 2건' 묶음이 더 생김 | 100% · 일치 |

- **HCX-005 첫 평가** (프롬프트 `c3-v1`, 11/8, 온기한식은 와우에 맞추기 전 데이터):

  | HCX-005 | 감정 | 주제 정밀도 | 주제 재현율 | 반복 묶음 |
  |---|---|---|---|---|
  | 온기한식 (이전) | 39/40 | 91% | 79% | 모두 찾음 |
  | 바삭치킨 | 29/30 | 94% | 86% | 모두 찾음 |
  | 몽글카페 | 29/30 | 94% | 88% | 모두 찾음 |

  틀린 것은 대부분 한 리뷰의 **두 번째 주제를 빠뜨린 것**이었습니다 (예: '양도 넉넉하고 맛도 좋아요'의 맛).
  그 뒤 프롬프트를 고쳤습니다: 여러 주제 예시·채널 정보(c3-v2), JSON 배열 하나로 묻고 못 읽은 리뷰는 다시 묻기(c3-v3), kiwi 참고 자료(c3-v5).
  벤치마크 v1 연습용으로 c3-v6(감정·응대·메뉴 규칙), c3-v7(주제별 판단 단서 + 고정 예시 10개)을 만들었습니다 → 시험용 주제 F1 84.7% (`data/benchmark/v1/RESULTS.md`).
  c3-v2에서 '매장 환경' 주제를 더하면서 '주제 없음'이던 정답 4건을 `atmosphere`로 바꿨습니다.
- 와우 숫자(불만 12 · 3묶음 · 단발 5)는 AI 분류 결과에 따라 달라질 수 있습니다. 발표에서는 HCX-005 결과를 재생본(C9)으로 고정합니다.

## 10. 남은 일

- [ ] 서버에서 `APP_MODE=live`(c3-v5)로 kiwi 참고 자료 켠 것·끈 것 평가, 온기한식 와우 숫자 확인, `data/replay/classify.json` 올리기
- [ ] C1 데이터 계약이 나오면 `app/models.py`를 그 형식으로 맞추기
- [ ] C4 상권이 정해지면 발표용 가게 업종·이름 맞추기 (`scripts/make_synthetic.py`)
- [x] 처음 보는 리뷰로 규칙·AI 점수 다시 재기 → 벤치마크 v1 (`data/benchmark/v1/RESULTS.md`)
