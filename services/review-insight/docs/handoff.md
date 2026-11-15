# 통합 담당 전달 문서: 리뷰 분석 모듈 고객응대 API (캡처 · 새 리뷰 · 답글 기록 · 응대 점수 · 보고서)

작성 2026-11-14 · 브랜치 `feat/review-capture-response` · 리뷰 분석 모듈(`services/review-insight`) 담당 이건영

이 문서는 리뷰 분석 모듈에 새로 생긴 API 와, **다른 영역(통합 화면 `services/web`, 가상 배달앱, 계약 `shared/`, 서버·DB·Nginx)이 해 주셔야 할 일**을 정리한 것입니다.
리뷰 분석 모듈 밖의 파일은 고치지 않았습니다.

---

## 1. 한눈에

```
[가상 배달앱]  손님이 리뷰 쓰기 ──POST /reviews (source=app)──┐
[사장님 화면]  붙여넣기·캡처 확인·매장 메모 ──POST /reviews──┤
                                                          ▼
                                     리뷰 분석 모듈 (127.0.0.1:8020)
                                     개인정보 가림 → 분류 → 묶음 · 받은 시각 기록
                                                          │
[통합 화면]  몇 초마다 GET /reviews?since= → 새 리뷰 알림 ◀─┤
             GET /response → 점수·남은 시간                 │
             답글 승인 → POST /reviews/{id}/status ─────────┘
[가상 배달앱]  GET /reviews?source=app → 리뷰 아래 사장님 답글(reply) 보여 주기
```

- 모든 주소 앞에 `/api/review-insight` 가 붙습니다. `APP_ACCESS_TOKEN` 을 정했으면 `X-Access-Token` 헤더가 필요합니다 (지금과 같음).
- 오류 모양은 지금과 같습니다: `{"error": {"code", "message", "retryable", "details", "request_id"}}`.
- 방문자 구분(`visitor_id`)은 새 API 에도 똑같이 들어갑니다 (쿼리 또는 본문).

## 2. 새 API 와 예시

### 2-1. 캡처 입력 `POST /reviews/capture`

multipart: `file`(png·jpg·webp 1장), `store_id`, `visitor_id`(선택).
**후보만 돌려주고 저장하지 않습니다.** 사장님이 확인·수정한 뒤 2-2 로 한 건씩 저장합니다.

```bash
curl -F file=@review.png -F store_id=store_ongi http://127.0.0.1:8020/api/review-insight/reviews/capture
```
```json
{
  "candidates": [
    {"text": "공깃밥이 또 빠져 있었어요. 다음엔 꼭 챙겨 주세요", "rating": 2, "pii_masked": false, "duplicate": false}
  ],
  "count": 1, "demo": false, "pieces": 1, "warnings": [], "engine": "HCX-005",
  "next": "후보를 확인·수정한 뒤 POST /api/review-insight/reviews 로 한 건씩 저장하세요"
}
```

| 필드 | 뜻 |
|---|---|
| `text` | 옮겨 적은 글. 전화번호·이메일·링크는 `[가림]` |
| `duplicate` | 이미 저장된 리뷰(합성 + 이 방문자가 넣은 것)와 같은 글이면 `true` → 화면에서 기본 선택 해제 권장 |
| `demo` | `true` 면 **이미지를 읽지 않은 예시 결과** (키 없음 또는 `APP_MODE=mock`). 화면에 꼭 표시 |
| `warnings` | 답이 길이 제한으로 잘렸을 수 있음, 긴 캡처를 조각으로 나눠 읽음 등 → 화면에 그대로 보여 주세요 |

| 오류 | 언제 | 화면 안내 |
|---|---|---|
| 400 `VALIDATION_ERROR` | 형식이 아님, 크기 초과(`details.max_bytes`), 가로로 너무 김 | 메시지 그대로 |
| 400 `CAPTURE_TOO_LONG` | 세로로 너무 길어 5조각이 넘음 | 나눠서 올리기 |
| 422 `CAPTURE_UNREADABLE` | 리뷰 0건 또는 JSON 으로 못 읽음 | "다시 올리거나 붙여넣기를 써 주세요" (메시지에 들어 있음) |
| 502 `LLM_TIMEOUT`·`LLM_RATE_LIMITED`·`LLM_UPSTREAM_ERROR` | 모델 호출 실패 (`retryable: true`) | 잠시 뒤 다시 |

처리 방식: 이미지는 메모리에서만 쓰고 디스크·로그에 남기지 않습니다. 긴 변 2240px 초과는 줄이고, 세로 1:5 보다 긴 캡처는 겹치게 잘라 최대 5조각, **조각마다 HCX-005 를 1번** 부릅니다.

### 2-2. 리뷰 저장 `POST /reviews` (기존 + `source`)

```json
{"store_id": "store_ongi", "text": "반찬이 또 빠져 있었어요", "rating": 2, "source": "app"}
```
- `source`: `paste`(기본) | `capture`(캡처 후보 확인) | `app`(가상 배달앱) | `memo`(매장에서 들은 불만). `input_method` 로 보내도 같은 뜻.
- 응답은 지금과 같고, `review` 에 `source`, `received_at`(실제로 받은 시각), `reply`(null) 가 더 붙습니다.
- **`input_method` 는 계약대로 모두 `"paste"`** 로 저장합니다 (3절).
- `created_at` 은 지금처럼 발표 장면 시각(마지막 합성 리뷰 날 23:00 + n분)이고, 기한·새 리뷰 조회에는 `received_at` 을 씁니다.

### 2-3. 새 리뷰 조회 `GET /reviews?since=&source=`

```
GET /api/review-insight/reviews?store_id=store_ongi&since=2026-11-14T19:00:00%2B09:00
```
```json
{"items": [{"review_id": "rv_ongi_paste_002", "text": "...", "input_method": "paste", "source": "app",
            "received_at": "2026-11-14T19:00:12+09:00", "status": "new", "reply": null, "...": "..."}],
 "count": 1, "server_time": "2026-11-14T19:00:15+09:00"}
```
- `since` 뒤에 **받은** 리뷰만, 받은 순서로. 합성 샘플은 받은 시각이 없어 나오지 않습니다.
- 다음 조회의 `since` 로 응답의 `server_time` 을 쓰면 빠짐없이 이어집니다.
- `since` 가 없으면 지금과 같은 `{items, count}` (최신 작성 순). `source=app` 으로 가상 배달앱 리뷰만 고를 수 있습니다.
- `+` 는 URL 에서 `%2B` 로 보내 주세요.

### 2-4. 상태·답글 기록 `POST /reviews/{review_id}/status`

```json
{"store_id": "store_ongi", "status": "replied", "reply_text": "불편을 드려 죄송합니다. 포장 단계에서 한 번 더 확인하겠습니다.",
 "at": "2026-11-14T19:12:00+09:00"}
```
- `status`: 계약의 `REVIEW_STATUSES` (`new`·`analyzed`·`drafted`·`replied`·`skipped`). `reply_text` 는 `replied` 일 때만 (1~1000자).
- `at` 을 비우면 지금. 통합 화면이 승인 시각을 따로 갖고 있으면 그 값을 넘겨 주세요.
- 응답 `{"review": {..., "status": "replied", "reply": {"text": "...", "replied_at": "..."}}}`. 이후 리뷰 조회(`/reviews`, `/reviews/{id}`)에도 `reply` 가 함께 나옵니다.
- 없는 리뷰 404 `REVIEW_NOT_FOUND`, 잘못된 값 400 `VALIDATION_ERROR`.

### 2-5. 응대 기한·점수 `GET /response?store_id=`

```json
{"store_id": "store_ongi", "score": 91, "raw_score": 91,
 "reasons": [{"key": "again:rv_ongi_paste_003", "kind": "again", "delta": -5, "at": "2026-11-14T22:52:42+09:00",
              "message": "답글을 단 '포장 누락' 불만이 다시 들어옴"},
             {"key": "repeat:iss_missing_item", "kind": "repeat", "delta": -2, "message": "'포장 누락' 불만이 6건 반복 중"}],
 "pending": [{"review_id": "rv_ongi_paste_002", "text": "공깃밥이 또 빠졌어요…", "topic_names": ["포장 누락"], "source": "app",
              "received_at": "2026-11-14T22:52:40+09:00", "due_at": "2026-11-14T23:22:40+09:00",
              "remaining_seconds": 1795, "overdue": false, "paused": false, "penalty": 0}],
 "pending_count": 1, "overdue_count": 0, "untimed_unanswered": 12, "peak_now": false,
 "policy": {"sla_minutes": 30, "peak_hours": ["11-14", "17-21"], "window_days": 28}}
```
- **규칙으로만 계산**합니다. 분류는 저장할 때 이미 끝난 결과(저장본)를 다시 씁니다.
- 남은 시간은 `due_at` 으로 화면에서 1초마다 세면 됩니다 (서버는 10초~1분마다 다시 불러도 충분).
  피크 중이면(`peak_now`) "멈춤"으로 보여 주세요. `due_at` 에는 이미 피크 멈춤이 반영돼 있습니다.
- `untimed_unanswered`: 합성 샘플 중 답글 안 단 불만 (기한 없음). "지난 불만 n건"으로 따로 보여 주세요.

**기한 규칙**: 불만 리뷰를 받은 때부터 30분. 피크(기본 11~14시, 17~21시) 중에는 멈추고, 피크 중에 받으면 피크가 끝난 때부터 30분.

**점수 수식** (100점에서 시작, 최근 28일, 0~100. 11/14 확정한 첫 안):

| 일 | 점수 |
|---|---|
| 기한을 넘긴 미답변 불만 | −6, 그 뒤 30분마다 −1 더 (리뷰당 최대 −10) |
| 기한을 넘긴 뒤 답글 | 깎인 것의 절반 회복 |
| 기한 안 답글 | 0 (빨리 달기만 해서는 안 오르게) |
| 답글을 단 주제에 같은 불만이 다시 들어옴 | 리뷰마다 −5 |
| 반복 묶음(3건 이상) | 묶음마다 −2 |
| 답글 단 주제가 7일 동안 재발 없음 | 주제마다 +3 (100 넘지 않게) |

### 2-6. 보고서 `GET /report/daily?date=YYYY-MM-DD`, `GET /report/monthly?month=YYYY-MM`

- 숫자는 모두 코드가 계산하고, 문장(`summary`, `todo.text`, `suggestions[].text`)은 **틀 문장에 숫자만 넣은 것**입니다 (`summary_method: "template"`). AI 문장이 아닙니다.
- 날짜는 한국 시간. 새 리뷰는 받은 날, 합성 샘플은 작성 날(10/13~11/8)로 셉니다.
- 일일: `review_count`, `complaint_count`, `by_source`, `replied_on_time`, `replied_late`, `pending_count`, `score_start`→`score_end`, `changes`(점수가 바뀐 이유, 합이 변동과 같음), `todo`(내일 먼저 할 일 1개), `summary`.
- 월간 인쇄: `GET /report/monthly/print?month=` → A4 HTML (숫자 카드 4개, 점수 그래프, 점수가 바뀐 이유, 반복 불만 표, **체크 칸이 있는 개선 할 일**). 프록시 허용 목록에 들어 있음.
- 월간: `score_trend`(날마다 점수), `repeated_issues`(묶음별 전체·이번 달 건수, 답글 수, 상태 `recurred_after_reply`·`no_recurrence`·`replied_watching`·`no_reply`), `suggestions`(최대 3개, 원인을 단정하지 않음).
- **손님 칭찬 요약 `praise` (11/16, 일일·월간 둘 다)**: 그 기간 리뷰만 코드로 센 값입니다 (`method: "code"`, 모델 호출 없음. 분류는 `Timeline`이 이미 읽어 둔 것).
  `review_count`, `high_rating_count`(별점 4~5점), `positive_count`(긍정 분류), `praise_count`·`praise_basis`(칭찬 리뷰 수와 기준 `sentiment`·`rating`·`null`),
  `top_topics`(칭찬 주제 상위 5개: `topic`, `topic_name`, `count`), `top_menus`(인기 메뉴 TOP 3: `menu`, `count`), `quote`(대표 칭찬 한 줄: `text`, `review_id`, `rating` 또는 `null`).
  - 칭찬 리뷰와 메뉴 언급 수는 저장소 루트의 `shared/praise.py`로 셉니다 (추천 카드 ⓑ·쿠폰 메뉴 고르기와 같은 기준). 메뉴 이름은 `store.json`의 `menu`.
    서버(systemd)는 `PYTHONPATH=/opt/ic26`로 `shared/`를 찾고, 저장소 안에서 띄우면 루트를 찾아 붙입니다. **이 폴더만 있는 환경(Dockerfile 이미지)에는 `shared/`가 없어 `praise`가 `null`** 입니다 (보고서의 다른 칸은 그대로).
  - 대표 칭찬 한 줄: 가장 많이 언급된 메뉴를 말한 칭찬 리뷰 → 가린 자리(`[가림]`) 없는 글 → 별점 높은 것 → 최근 것. 80자를 넘으면 그 메뉴를 말한 문장 하나만.
    글은 보고서를 만들 때 `mask_pii`를 한 번 더 거칩니다 (합성 샘플·예전 저장본은 가림을 거치지 않았을 수 있음).
  - 월간 인쇄 페이지에도 '손님 칭찬 요약' 네 줄이 들어갑니다 (`html.escape`).

### 2-7. 가게 정보 (11/15 추가) `GET·PUT·DELETE /profile`, `POST·DELETE /profile/notices`, `POST·DELETE /profile/answers`, `POST /profile/menu/capture`

응대용 가게 정보입니다. 계약의 `StoreProfile`(`GET /store`)은 그대로 두고 **응대에 필요한 것만** 받습니다. 위치·업종은 상권 서비스의 분석 조건과 겹쳐 받지 않습니다.

```json
PUT /profile  {"changes": {"basic": {"hours": {"mon": "11:00-21:00", "sun": "휴무"}, "parking": "가게 앞 2대"}}}
POST /profile/notices  {"kind": "closed", "text": "11/20 임시휴무", "start": "2026-11-20", "end": "2026-11-20"}
```
- 묶음: `basic`(영업시간·브레이크·마지막 주문·쉬는 날·주소·주차) · `order`(배달 지역·최소 주문·포장·단체) · `menu`(이름·가격·맵기 0~3·재료·**사장님이 확인한 알레르기**·추천·품절) · `policy`(다시 만들기·환불·예약·반려동물) · `reply`(말투·끝인사·피크·기한 분) · `foreign`.
- `PUT` 은 보낸 묶음만 통째로 바꿉니다. 모르는 묶음·잘못된 시간 형식은 `400 VALIDATION_ERROR`.
- **임시 공지**(`closed`·`sold_out`·`hours`·`other`)는 `end` 가 지나면 저절로 빠집니다. 사장님이 되돌리는 걸 잊어도 손님에게 틀린 안내가 나가지 않습니다.
- `GET /profile` 응답에 `today`(오늘 영업시간, 품절), `active_notices`, `setup`(`done`, `missing`: 꼭 필요한 영업시간·메뉴 가격, `later`: 채우면 좋은 것)이 붙습니다. 처음 설정 화면은 `setup.done` 으로 띄우면 됩니다.
- 메뉴판 사진 → `POST /profile/menu/capture` (multipart `file`) → 후보 `[{name, price, exists}]`. 저장하지 않음. 키 없으면 `demo: true`.
- 처음 값은 `data/care/<가게>.json` (가상 가게 3곳 **합성 예시**).

### 2-8. 손님 문의 (공개, 토큰 없음) `GET /public/{가게}/info`, `POST /public/{가게}/inquiries`, `GET /public/{가게}/inquiries/{code}` + 페이지 `/s/{가게}`

```json
POST /public/store_ongi/inquiries  {"text": "주차 되나요?"}
→ 201 {"code": "Fk73fF8b", "status": "answered", "answer": "주차: 가게 앞 2대 가능 …", "answered_by": "가게 안내", "forwarded": false}
POST /public/store_ongi/inquiries  {"text": "토요일 저녁 6시 15명 예약 되나요?"}
→ 201 {"code": "_99dtJv0", "status": "waiting", "answer": null, "forwarded": true, "message": "사장님께 전달했어요 …"}
```
- **규칙으로만** 나눕니다 (모델 호출 없음). 가게 정보로 모두 답할 수 있으면 바로 답하고, 하나라도 모르면 사장님 받은함으로 보냅니다 (30분 기한).
- **알레르기·위생(이물질·배탈)·환불·보상·직원 지목**은 가게 정보에 답이 있어도 자동으로 답하지 않습니다 (`needs_owner`).
- 예약은 날짜·인원 확인이 필요해 늘 사장님에게 넘깁니다. 사장님이 "배운 답"으로 저장한 답은 비슷한 질문에 자동으로 씁니다 (사장님 확인 필수 문의에는 쓰지 않음).
- 손님 연락처를 받지 않습니다. 확인 번호(`code`)로 같은 페이지에서 답을 봅니다. 글 속 전화번호 등은 가립니다.
- 횟수 제한: 손님(접속 주소)당 1분 10건, 가게당 1분 60건 → `429 RATE_LIMITED` (메모리, 서버마다 따로).

### 2-9. 응대 받은함 `GET /inbox?kind=&intent=&needs_owner=&open=&since=`

리뷰와 문의를 한 목록으로 줍니다. 항목마다 `kind`(review|inquiry) · `intent`(complaint·reservation·question·praise·other) · `needs_owner` · `due_at`·`remaining_seconds`·`overdue` · `reply` · `forward_reason`. 정렬은 **열린 '사장님 확인 필수' → 기한 가까운 순 → 나머지 최신순**. `summary` 에 처리할 것·확인 필수·기한 넘김·자동 답변 수가 있습니다. 응대 점수(`/response`)는 정해 둔 수식대로 불만 리뷰만 셉니다 (문의는 기한만 표시).

### 2-10. 문의 답장·답 초안 `POST /inquiries/{id}/status`, `POST /inquiries/{id}/draft`

- 답장: `{"reply_text": "…", "learn": true}` → 손님 페이지에 "사장님" 답으로 보이고, `learn` 이면 가게 정보의 "배운 답"에 저장.
- 초안: 근거(`facts`)는 가게 정보에서 코드가 뽑습니다. live 면 HCX-005 가 근거만으로 쓰고 **코드가 검사**합니다: 근거에 없는 숫자 금지, 정책에 없는 환불·보상·무료·할인 금지, 알레르기 단정 금지와 "확인" 문장 필수, 500자 이하. 못 넘으면 틀 문장(`method: "template"`, `checks` 에 이유). 키가 없으면 틀 문장 + `demo: true`.
- **리뷰 답글은 만들지 않습니다.** 비서 화면의 글 만들기(C6)가 맡습니다.

### 2-11. 약속 장부 `GET /promises`

답글·답장에서 약속 문장("포장할 때 반찬 개수를 한 번 더 확인하겠습니다")을 규칙으로 뽑습니다. 리뷰 약속은 응대 점수 기록으로 상태를 정합니다: `broken`(약속 뒤 같은 불만 재발) · `watching`(7일 지켜보는 중) · `kept`(7일 재발 없음). 문의 약속은 `check`(사장님이 지켰는지 확인).

### 2-12. 다국어 메뉴판 (11/15) `GET /menu/foreign?lang=`, `GET /menu/foreign/print?lang=`

- 언어 12개 (Papago 가 한국어에서 지원하는 것): `en`·`ja`·`zh-CN` 은 확인한 사전 + Papago, `zh-TW`·`vi`·`th`·`id`·`fr`·`es`·`ru`·`de`·`it` 은 메뉴 이름·재료·안내 문구·주문 문장을 모두 Papago 로 번역 (원어민 확인 권장). 키가 없으면 지어내지 않고 영어로 대신 쓰고 `fallback_en: true`, `checks` 에 남김.

- 가게 정보의 메뉴로 외국인 손님용 메뉴판을 만들고, `print` 는 **인쇄용 A4 HTML**을 줍니다. 브라우저의 인쇄 → "PDF로 저장"으로 PDF 가 됩니다 (서버에서 PDF 를 만들지 않아 일본어·중국어 글꼴 문제가 없음).
- **설명 문장을 AI 로 지어내지 않습니다.** 메뉴마다 ① 한국어 이름 ② 번역 이름 ③ 로마자(코드 변환) ④ 재료 ⑤ 맵기 ⑥ 알레르기(등록한 것만, 없으면 "직원에게 물어보세요") ⑦ 가격. 아래에 "덜 맵게 해 주세요" 같은 주문 문장 6개.
- 번역 순서: 확인한 사전(합성 가게 3곳 메뉴·흔한 재료·알레르기) → 사장님이 고친 값(`PUT /profile` 의 `foreign.overrides`) → Papago. Papago 로 만든 이름은 다시 한국어로 번역(`name_back`)해 뜻을 확인하게 합니다.
- Papago 키(`PAPAGO_CLIENT_ID`, `PAPAGO_CLIENT_SECRET`)가 없으면 사전만 쓰고 `demo: true`, 인쇄 페이지 위에 "예시 번역" 표시. 사전에 없는 말은 `checks` 에 남깁니다.
- 같은 글은 한 번만 번역해 `data/runtime/translations.json` 에 저장합니다.
- 메뉴 이름 기준: 계약 규칙(`StoreProfile` 앞 7개 필드 = 이 모듈 `store.json` 그대로, PR #15)을 따릅니다. 가게 정보에만 있는 메뉴는 `checks` 에 "계약(store.json)에 없는 메뉴"로 알립니다. 온기한식 가격은 C1 샘플(`menu_prices`)과 같고, 시험이 이를 확인합니다.
- 결정안 Won't(이슈 #35)에 "다국어 메뉴판"이 있었는데, 11/15 이건영 결정으로 넣었습니다. 팀 공유가 필요합니다.

### 2-13. 무엇이 시연자별이고 무엇이 가게 공용인가 (11/15 통합 시뮬레이션 뒤 정함)

| 데이터 | 저장 칸 | 이유 |
|---|---|---|
| 붙여넣은·캡처한 리뷰, 그 답글·상태 기록 | **시연자별** (`visitor_id`, 지금과 같음) | 시연하는 사람마다 따로 해 볼 수 있게 (팀 규칙) |
| 가게 정보(영업시간·메뉴·공지·배운 답) | **가게 공용** | 손님 문의 페이지가 이 정보로 답하고, 사장님이 저장한 배운 답이 다음 손님에게 쓰여야 함 |
| 손님 문의 | **가게 공용** | 손님은 사장님 화면의 방문자 쿠키가 없어서, 시연자별로 나누면 사장님 받은함에 0건으로 보임 (실제로 확인함) |
| 가상 배달앱 리뷰 | **정하지 않음** | 배달앱 세션에서 정함. 같은 문제가 있어 가게 공용을 권함 |

- 시연자 한 명의 "데모 다시 하기"(`DELETE /reviews/pasted?visitor_id=`)는 가게 공용 문의를 지우지 않습니다. `visitor_id` 없이 부르면 공용 문의도 지웁니다.
- 프록시는 손님용(`/api/care/public/*`)에 방문자를 붙이지 않습니다.
- 통합 시뮬레이션(11/15, 팀 서버와 같은 모양: 화면 서버 8000 + 이 서비스 127.0.0.1:8020 + 토큰 + 프록시 두 줄)으로 확인한 흐름:
  손님 휴대폰 문의 → 사장님 받은함 → 답장(배운 답 저장) → 손님이 확인 번호로 답 확인 → 다른 손님의 비슷한 질문에 자동 답. 기존 화면 서버 시험 109개 통과.

## 3. 계약 변경 요청 (`shared/contracts.py`)

| 요청 | 지금 동작 (확인함) |
|---|---|
| `INPUT_METHODS` 에 `capture`·`app`·`memo` 를 넣을지 결정 | 넣기 전까지 이 모듈은 **조직이 정한 값만** 씁니다: 새 입력은 모두 `input_method="paste"`, 출처는 계약 밖 칸 `source` 에 둡니다. `web/sources.py` 의 `to_review_records` 는 계약 밖 칸을 버리므로 깨지지 않습니다 (시험 `test_decorated_reviews_still_fit_the_team_contract` 로 확인) |
| `ReviewRecord` 에 `source`, `received_at`, `reply` 칸 추가 여부 | 지금은 통합 화면이 이 값을 받으려면 계약 변환 전에 원래 dict 에서 꺼내야 합니다 |
| `CHANNELS` 에 가상 배달앱·매장 메모용 값 | 없어서 `app`·`memo` 리뷰의 `channel` 은 `null` 로 저장합니다 |

## 4. 통합 화면 서버(`services/web`)가 해 주실 일

1. **주소 넘겨주기**: 리뷰 분석 서버는 `127.0.0.1:8020` 에만 열려 있어 브라우저가 직접 닿지 못합니다. 아래를 화면 서버가 받아 그대로 넘겨 주세요.
   - `POST /reviews/capture` (multipart 그대로 전달, `visitor_id` 를 폼에 붙여서)
   - `GET /reviews?since=`, `POST /reviews/{id}/status`, `GET /response`, `GET /report/daily`, `GET /report/monthly`
2. **답글 승인 시 status 호출**: 사장님이 답글을 승인하면 `POST /reviews/{review_id}/status` 에 `{"status":"replied","reply_text": 승인한 글, "at": 승인 시각}`.
   이 호출이 없으면 모든 불만이 기한 넘김으로 계산됩니다.
3. **새 리뷰 조회**: 화면이 열려 있는 동안 5~10초마다 `GET /reviews?since=<직전 server_time>` → 새 불만이면 알림과 타이머 시작.
   불만 여부는 `GET /response` 의 `pending` 이나 `/insight` 의 분류로 확인합니다.
4. **업로드 크기**: Nginx `client_max_body_size` 를 **12MB 이상**으로 (모듈 상한 10MB + 여유). 화면 서버(FastAPI)도 `python-multipart` 가 필요합니다.

## 5. 가상 배달앱이 해 주실 일

- 손님 리뷰 등록: 화면 서버를 거쳐 `POST /reviews` `{"store_id", "text", "rating", "source": "app"}`.
- 리뷰와 사장님 답글 보기: `GET /reviews?source=app` → 항목의 `reply.text`, `reply.replied_at`.
- 화면에 "시연용 가상 배달앱"이라고 밝혀 주세요. 실제 배달앱과 연결된 것처럼 보이면 안 됩니다. `data_origin` 은 `synthetic` 그대로입니다.

## 6. 화면에 필요한 자리

모듈 확인 화면(`http://127.0.0.1:8020/`)에 시안이 있습니다 (통합 화면에는 넣지 않음): **캡처 입력 · 응대 기한·점수 · 보고서** 탭.

| 자리 | 들어갈 것 |
|---|---|
| 리뷰 분석 > 캡처 탭 | 파일 고르기 → 후보 목록(글 고치기·별점·`개인정보 가림`·`이미 있는 리뷰` 표시·선택) → 저장. `demo` 와 `warnings` 표시 필수 |
| 홈 또는 고객응대 | 점수(큰 숫자) + 이유 목록, 답글 기다리는 불만별 남은 시간(피크 중 "멈춤"), 지난 불만 n건 |
| "종합 리포트" 빈 자리 | 일일 요약(한 줄 요약·숫자 3개·이유·내일 할 일), 월간 보고서(점수 추이·반복 불만 표·제안) |

## 7. DB 에 저장할 항목 (지금은 파일)

새 기록은 `app/records.py` 한 곳에서 읽고 씁니다. 지금은 **DB 모드여도 파일**(`data/runtime/records_<가게>.json`, 방문자별 폴더)에 둡니다.
DB 표가 생기면 이 파일의 `load`·`update`·`clear` 세 함수만 바꿔 끼우면 됩니다.

| 칸 | 형식 | 비고 |
|---|---|---|
| `store_id`, `visitor_id`, `review_id` | text | 열쇠 (reviews 표와 같은 묶음) |
| `source` | text | `paste`·`capture`·`app`·`memo` |
| `received_at` | timestamptz | 실제로 받은 시각 |
| `status`, `status_at` | text, timestamptz | 마지막 상태 |
| `reply_text`, `replied_at` | text, timestamptz | 사장님 답글 |
| 상태 기록 (`review_status_events`) | `(store_id, visitor_id, review_id, status, at)` | 점수·보고서가 "그 시각의 상태"를 계산할 때 씀 |

## 8. 알려진 위험

- **WAS 가 2대면** 위 기록 파일이 서버마다 달라집니다 (가상 배달앱에서 쓴 리뷰나 답글이 다른 서버에서 안 보일 수 있음). DB 표가 생기기 전까지 시연은 WAS 1대로 해 주세요.
- **분당 호출 한도**(테스트 앱 60회)를 분류와 캡처가 같이 씁니다. 긴 캡처는 조각 수만큼(최대 5) 호출합니다.
- **캡처는 모델이 글을 지어내거나 빠뜨릴 수 있고** 코드로 대조할 수 없습니다. 저장 전 사장님 확인 단계를 빼면 안 됩니다.
- **캡처를 실제 HCX-005 로 불러 본 적이 없습니다.** 키가 있는 서버에서 한 번 확인이 필요합니다 (README 9절).
- 점수 수식은 첫 안이라 숫자가 바뀔 수 있습니다. 화면은 `reasons[].message` 를 그대로 보여 주면 수식이 바뀌어도 고칠 곳이 없습니다.

## 9. 통합 방법: 상권 서비스와 같은 구조 (11/15)

상권 서비스(`services/market-analysis`, 127.0.0.1:8766)는 **혼자 도는 서비스 + 자체 화면(`/`)** 이고, 비서 화면 서버가 `assistant_proxy.py`(브랜치 `feat/assistant-proxy`)로 `/api/assistant/*` 를 대신 불러 줍니다. 이 모듈도 같은 구조로 맞췄습니다.

```
브라우저 ──▶ 비서 화면 서버 :8000  (같은 출처, 브라우저는 8020 에 직접 가지 않음 — contract.md 0.1)
              ├ /api/assistant/*  ──▶ 상권 서비스 127.0.0.1:8766        (팀장님 assistant_proxy.py)
              ├ /api/care/*       ──▶ 이 서비스 127.0.0.1:8020/api/review-insight/*   (integration/care_proxy.py)
              └ /s/{가게}          ──▶ 이 서비스 /s/{가게} (손님 문의 페이지, API 주소만 /api/care/public 으로 바꿔 줌)
이 서비스 단독 확인: http://127.0.0.1:8020/ (자체 화면: 요약·불만 묶음·붙여넣기·캡처·응대 기한·보고서·받은함·가게 정보)
```

**참고 구현** `integration/care_proxy.py` (fastapi·httpx 만 씀, 이 모듈의 `app` 을 import 하지 않음). 시험 `tests/test_care_proxy.py` 가 '화면 서버 흉내' 앱에 붙여 끝까지 확인합니다.

| 프록시가 하는 일 | 이유 |
|---|---|
| `/api/care/status` 항상 200 (`ready`·`down`·`off`) | 서비스가 꺼져도 비서 화면이 죽지 않게 (상권 프록시와 같은 규칙) |
| 사장님용 경로는 허용 목록만 넘김, 모르는 경로 404 | `DELETE /reviews/pasted` 등 화면 서버가 이미 가진 것과 겹치지 않게 |
| `store_id` 는 `DEMO_STORE_ID`, `visitor_id` 는 방문자 쿠키로 **덮어씀** (쿼리·JSON 본문 모두) | 브라우저가 다른 가게·방문자를 고를 수 없게 (contract.md 0.5 "가게는 하나") |
| `X-Access-Token` 을 서버가 붙임 (`REVIEW_INSIGHT_TOKEN`) | 브라우저는 토큰을 모름 |
| 손님용 `/api/care/public/*` 은 토큰·덮어쓰기 없이 넘기고 `X-Forwarded-For` 전달 | 공개 API, 횟수 제한용 |
| 같은 브라우저(쿠키 있음)로 문의 페이지를 열면 그 방문자 받은함으로, 쿠키 없는 손님은 공용 받은함으로 | 시연에서 심사위원이 직접 문의 → 자기 받은함에서 확인 |
| 실패는 `{"error": {"message", "state"}}`, 500 없음 | 상권 프록시와 같은 모양 |
| 본문 상한: JSON 64KB, 업로드 12MB | Nginx `client_max_body_size 12m` 도 맞춰 주세요 |

**통합 담당이 할 일 (순서대로)**
1. `integration/care_proxy.py` 를 `services/web/web/care_proxy.py` 로 복사하고 `main.py` 에 두 줄: `api, pages = create_care_routers(visitor_of=lambda r: r.state.visitor_id)` → `app.include_router(api); app.include_router(pages)`.
2. 화면(app.js)은 `/api/care/...` 만 부릅니다. (contract.md 2.4: `index.html`·`app.js` 에 `/api/review-insight` 글자를 쓰면 시험이 깨짐 → `/api/care` 를 쓰면 됨)
3. 메뉴 자리: 고객응대 ▸ 받은함(`/api/care/inbox`) · 가게 정보(`/api/care/profile`) · 응대 점수(`/api/care/response`) · 보고서(`/api/care/report/*`). 홈 카드: 점수·처리할 것·가장 급한 1건.
4. 리뷰 답글 승인(`POST /api/drafts/{id}/approve`) 때 `POST /api/care/reviews/{review_id}/status` `{"status":"replied","reply_text":…}` 를 같이 불러 주세요 (기한·점수·약속 장부가 이 기록으로 계산됨).
5. Nginx: 손님용 `/s/` 와 `/api/care/public/` 만 밖에 공개해도 되는지 결정. 나머지는 지금처럼.
6. 화면 시안은 이 서비스의 `/` 화면(받은함·가게 정보 탭)과 `/s/store_ongi` 를 참고하세요.

## 10. 팀과 정할 것

- **결정안 Won't(이슈 #35)와의 관계**: "전화 응대"는 넣지 않았습니다. "다국어 메뉴판"은 11/15 이건영 결정으로 넣었습니다 (2-12). 결정안 6절 '다시 여는 조건'은 저장소에 없어 확인하지 못했으니 팀장님께 알려 주세요.
- **가게 정보 중복 → 계약 규칙을 따름**: 메뉴 이름의 기준은 `store.json`(= 계약 `StoreProfile.menu`), 가격의 기준은 C1 샘플 `menu_prices`(C6 쿠폰용). 이 모듈 `/profile` 은 같은 이름·가격에 응대용 정보(재료·맵기·알레르기)만 더합니다. 사장님이 가게 정보에서 메뉴를 바꾸면 `store.json` 은 바뀌지 않으므로(합성 데이터는 고치지 않음), 실제 가게에 쓸 때는 계약 쪽을 `/profile` 에서 만들도록 바꾸자는 제안을 남깁니다.
- **"AI에게 묻기" 서랍과 이름 구분**: 서랍은 사장님이 상권을 묻는 곳, 문의 페이지는 손님이 가게에 묻는 곳.
- **DB 표 추가 요청** (7절에 더해): `care_profiles`(가게·방문자별 JSON), `care_notices`, `care_answers`, `inquiries`(code, intent, needs_owner, status, reply), `inquiry_events`.
