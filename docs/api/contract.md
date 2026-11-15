# 텔레토비 AI 비서: API 설명서 겸 화면 안내서

> 대상: 비서 화면을 예쁘게 꾸미는 팀원(주현석)과 그 팀원이 쓰는 LLM
> 기준: main `d7c1305` (2026-11-14, PR #43 병합) · 작성일 2026-11-14
> 응답 예시는 그 직전 커밋 `28aed61`에서 뽑았습니다. 그 뒤 main에서 바뀐 것은 붙여넣기 글자 수 제한(4000 → 1000자)과 그 시험 1건뿐이고, 화면 파일 세 개는 같습니다.
> 이 문서는 코드를 읽고 실제 응답을 뽑아서 썼습니다. 코드는 바꾸지 않았습니다.
> **11/15 덧붙임 (`feat/connect-care-ui`)**: 고객응대 프록시 `/api/care/*`(1.11절), 리뷰 붙여넣기 탭의 '캡처로 넣기', 왼쪽 메뉴 '종합 리포트'(`#/report`)가 생겼습니다. 1.6(승인)·1.8(붙여넣기)에 선택 칸이 하나씩 늘었고, 2부의 id 표·개수·시험 표를 지금 코드에 맞춰 고쳤습니다.

## 요약

이 서비스는 배달 음식점 사장님을 돕는 AI 비서입니다. 사장님은 밤 11시 브리핑에서 리뷰와 상권 숫자를 보고, 추천 카드 2장 중 하나를 고르고, AI가 쓴 답글·재발 방지 공지·쿠폰 홍보글을 고쳐서 승인합니다.

화면은 파일 세 개(`index.html`, `app.js`, `style.css`)이고, 서버(`services/web`)는 JSON만 줍니다. 이 문서는 세 가지를 적었습니다.

1. **1부**: 서버가 주는 API 9개와 프록시 두 묶음(1.10 상권 채팅, 1.11 고객응대). 요청, 실제 응답 예시, 칸마다 뜻, 오류.
2. **2부**: 화면을 다듬을 때 **바꿔도 되는 것**과 **바꾸면 깨지는 것**. 바꾸면 화면이 멈추거나 기존 시험 69건이 깨집니다.
3. **3부**: 데이터가 지금 어디에 저장되는지, 앞으로 무엇이 바뀔 예정인지.

**쓰는 기술**: 프레임워크 없이 HTML·CSS·JS, 서버는 JSON. React·HTMX 등으로 바꾸지 않음 (팀에서 정한 방침).

**로컬에서 띄우기** (키 없이 돎):

```bash
# 처음 한 번만, 저장소 루트에서
python3.11 -m venv .venv && .venv/bin/pip install -r services/web/requirements.txt -r services/review-insight/requirements.txt

# 키 없이 도는 시험용 실행
APP_MODE=mock services/web/run.sh

# 브라우저에서 열기 (macOS. 다른 OS는 주소창에 http://localhost:8000 을 입력)
open http://localhost:8000

# API가 뜨는지 확인
curl -s http://localhost:8000/api/health
```

- `run.sh`가 리뷰 분석 서버(8020번 포트)와 비서 화면 서버(8000번 포트)를 같이 띄웁니다. `Ctrl+C`로 둘 다 끕니다.
- `APP_MODE=mock`이면 키 파일이 있어도 모델(HCX)을 부르지 않습니다. 키가 없어도 됩니다.
- 주소 뒤에 `?theme=light`를 붙이면 라이트 테마로 고정됩니다 (아니면 운영체제 설정을 따름).
- 자동 API 문서는 `http://localhost:8000/docs`에 있습니다 (로컬에서만. 배포 계획서의 Nginx 설정은 `/docs`를 막음).

## 이 문서를 읽는 법

- 화면만 다듬는 사람은 **2부**를 먼저 보세요. API는 1부에서 찾아봅니다.
- LLM에게 맡길 때는 `index.html`, `app.js`, `style.css`, 이 문서를 함께 주고, 아래 상자를 먼저 읽히세요.

> **화면을 바꾸기 전에 지킬 규칙 (LLM에게 먼저 읽히세요)**
>
> 1. 화면 파일은 `services/web/web/static/`의 세 개뿐입니다. 서버가 `/`로 `index.html`을, `/static/…`으로 나머지를 줍니다. 파일을 더하면 이 폴더 안에 두고 `/static/…` 주소로 부릅니다.
> 2. `app.js`가 찾는 `id`(11/15 기준 114개, 2.2)를 지우거나 이름을 바꾸지 않습니다. 지우면 화면이 멈춥니다.
> 3. `app.js` 안의 문장 일곱 군데는 글자 그대로 둡니다 (2.4 표의 시험 6). 코드 정리 도구가 따옴표·괄호를 바꾸면 시험이 깨집니다.
> 4. `index.html`과 `app.js`(주석 포함)에 `replay`, `c9`, `/api/review-insight` 같은 글자가 들어가면 시험이 깨집니다 (2.4). 인라인 SVG 경로 데이터에 `c9`가 우연히 들어가는 경우를 조심하세요.
> 5. API 경로와 요청·응답의 칸 이름은 바꾸지 않습니다. 필요하면 서버 담당(박건영)에게 요청하세요.
> 6. 색·글꼴·간격·배치·아이콘은 자유롭게 바꿔도 됩니다. 단, CSS의 `[hidden] { display: none !important; }`는 유지합니다. JS가 `hidden` 속성으로 보이고 숨기는 곳이 많습니다.
> 7. CSS 클래스 이름을 바꾸면 `app.js` 안의 같은 이름도 같이 바꿔야 합니다 (2.3). `app.js`가 클래스로 찾는 것은 `.top`, `.side .menu`, `.shell > main`, `.menu a`, `.dot`, `.todo-st` 입니다.
> 8. 바꾼 뒤 시험 69건을 돌립니다 (2.8).

## 목차

- 0. 먼저 알아 둘 것
  - 0.1 서버가 두 개 있어요 · 0.2 모드가 두 가지예요 · 0.3 응답 예시는 이렇게 뽑았어요 · 0.4 이 문서의 말 · 0.5 모든 API에 해당하는 규칙
- 1부. API 9개
  - 1.0 한눈에 보기
  - 1.1 `GET /api/health` · 1.2 `GET /api/briefing` · 1.3 `GET /api/insight` · 1.4 `GET /api/cards`
  - 1.5 `POST /api/cards/{card_id}/run` · 1.6 `POST /api/drafts/{draft_id}/approve` · 1.7 `GET /api/approvals`
  - 1.8 `POST /api/reviews` · 1.9 `DELETE /api/reviews/pasted`
  - 1.10 `/api/assistant/*` (상권 채팅 서랍. 상권 서비스 프록시)
  - 1.11 `/api/care/*` (캡처 입력·응대 점수·보고서. 리뷰 분석 서비스의 고객응대 프록시)
- 2부. 화면을 다듬을 때 유지해야 하는 것
  - 2.1 파일 세 개와 정적 파일 경로 · 2.2 `id` 목록 · 2.3 id 말고도 app.js가 기대하는 것
  - 2.4 시험이 직접 확인하는 것 · 2.5 화면 주소 · 2.6 화면 흐름과 부르는 API
  - 2.7 자유롭게 바꿔도 되는 것 · 2.8 바꾼 뒤 확인하는 법
- 3부. 데이터가 어디에 저장되나, 무엇이 바뀔 예정인가
  - 3.1 지금 · 3.2 예정(아직 없음) · 3.3 지금 화면에 있는 빈 자리 · 3.4 임시 DB 표 이름
- 부록. 알려진 특이점, 코드에서 확인하지 못한 것

---

## 0. 먼저 알아 둘 것

### 0.1 서버가 두 개 있어요

| 이름 | 폴더 | 포트 | 하는 일 |
|---|---|---|---|
| 비서 화면 서버 | `services/web` | 8000 | 화면 파일과 이 문서의 API 9개를 줍니다. |
| 리뷰 분석 서버 | `services/review-insight` | 8020 (같은 컴퓨터 안쪽) | 리뷰를 보관하고 분류하고 묶습니다. 비서 화면 서버가 대신 부릅니다. **브라우저는 직접 부르지 않습니다** (시험이 막음, 2.4). |

비서 화면 서버는 리뷰 분석 서버가 꺼져 있으면 대부분의 API에서 `503`을 줍니다 (1.2~1.5, 1.8, 1.9).

### 0.2 모드가 두 가지예요

환경변수 `APP_MODE`로 정합니다. `replay`(발표 모드)는 없어졌고, 쓰면 서버가 오류로 멈춥니다.

| | `mock` (시험용 실행) | `live` (실시간) |
|---|---|---|
| 키 | 필요 없음 | HCX-005 키 필요 (호출마다 비용) |
| 추천 카드 이유 문장 | 고정 문장 | HCX-005가 쓰고, 규칙 검사를 못 넘으면 고정 문장 |
| 글(답글·공지·홍보글) | 미리 저장된 예시 파일(`experiments/marketing/c6/replay/c6_cache_best.json`)을 이 카드에 맞게 바꿔 보여 줌. **실제 AI 결과가 아님** | HCX-005가 실시간으로 씀. 파일에 저장하지 않음 |
| 화면 맨 위 띠 | "시험용 실행 · 키 없이 저장된 예시 결과를 보여 줍니다 (실제 AI 결과 아님)" | 없음 |

이 문서의 응답 예시는 모두 `mock`입니다.

### 0.3 응답 예시는 이렇게 뽑았어요

- `TestClient`(서버를 띄우지 않고 앱을 직접 부르는 도구)로 시험용 실행 앱을 만들어 9개 API를 실제로 불렀습니다. 시험(`test_web.py`)과 같은 방식입니다.
- 다른 점이 하나 있습니다. 시험은 리뷰 분석 서버를 가짜(`FakeSource`)로 바꿉니다. 이 문서는 **진짜 리뷰 분석 서버 코드**(규칙 분류, 키 없음)를 같은 프로세스에 붙였습니다. 그래서 붙여넣기 응답도 실제 모양입니다.
- 설정은 `APP_MODE=mock services/web/run.sh`의 기본값과 같습니다 (상권 지표 `data/scenario/snapshot_2026Q2.json`, 저장 예시 `experiments/marketing`).
- 붙여넣은 리뷰와 승인 기록은 임시 폴더에만 썼습니다. 저장소 파일은 바뀌지 않았습니다.
- 예시의 `approved_at`은 뽑은 시각(2026-11-14)입니다. **줄인 예시는 바로 위에 "줄임"이라고 적었습니다.** 줄인 것 말고는 값을 고치지 않았습니다.
- `live` 응답은 키가 없어 뽑지 않았습니다 (외부 호출을 하지 않음). `live`는 코드를 읽어 적었고, 그렇게 적은 곳에 표시했습니다. 키 없이 `live`로 띄웠을 때의 오류 응답만 실제로 뽑았습니다.

### 0.4 이 문서의 말

| 말 | 뜻 |
|---|---|
| 카드 ⓐ | 불만 대응 카드 (`kind`가 `complaint`). 반복되는 불만 묶음 하나를 가리킵니다. 카드 id 끝이 `_a`. |
| 카드 ⓑ | 쿠폰 홍보 카드 (`kind`가 `promo`). 상권 지표 하나를 가리킵니다. 카드 id 끝이 `_b`. |
| 글 종류 3가지 | `reply_draft`(답글), `prevention_notice`(재발 방지 공지), `coupon_promo`(쿠폰 홍보글). 화면 이름은 `app.js`의 `GEN_NAMES`. |
| 묶음 · 반복 | 같은 불만이 2건 이상이면 **묶음**, 3건 이상이면 **반복**입니다 (화면 문구 기준). |
| 상권 지표 | 서울시 상권분석 자료에서 뽑은 숫자 한 줄 (예: 저녁 시간대 추정매출 변화율). 코드 이름은 `snapshot`. |
| 합성 데이터 | 실제 가게가 아니라 만들어 낸 리뷰·가게. 지금 화면의 리뷰는 모두 합성입니다. |
| 시험용 실행 | `APP_MODE=mock`. 위 0.2 참고. |
| 근거 카드 | 이유 문장을 쓸 때 모델과 검사기에 넘기는 사실 한 줄 (`F1` 불만 묶음, `F2` 상권 지표, `F3` 손님 칭찬). 화면에는 안 보입니다. |

응답 안의 `c6`, `c7`, `C4` 같은 글자는 이렇게 읽습니다. `c6`는 글을 만드는 코드(`experiments/marketing/c6`), `c7_flags`는 **이 비서 화면 서버**가 글에서 찾아내는 확인 필요 문구, `C4`는 상권 지표 파일입니다.

### 0.5 모든 API에 해당하는 규칙

- **주소와 형식**: 모두 같은 서버(8000번)의 `/api/…`입니다. 요청과 응답은 JSON(UTF-8)입니다. 본문이 있는 요청은 `Content-Type: application/json`으로 보냅니다 (`app.js`의 `api()`는 모든 요청에 이 헤더를 붙임).
- **로그인·토큰 없음**: 비서 화면 서버는 인증을 하지 않습니다. CORS 설정도 없습니다. 화면과 API를 **같은 주소(origin)** 에서 받는 것이 전제입니다 (`main.py`에 CORS 설정이 없음을 확인함. 다른 포트에서 부르면 브라우저가 막는지는 실행해 보지 않아 확인하지 못함).
- **가게는 하나**: 서버 설정 `DEMO_STORE_ID`(기본 `store_ongi`)로 고정입니다. 요청에 가게를 고르는 칸이 없습니다.
- **시각**: 한국 시간 ISO 8601입니다 (`2026-11-14T19:19:46+09:00`).
- **칸 이름은 영어(snake_case), 화면에 보이는 글은 한국어**입니다.

**오류 응답은 모양이 네 가지입니다.**

| 모양 | 언제 | 본문 | 화면이 보여 주는 것 |
|---|---|---|---|
| ① 이 서버가 직접 만든 오류 | 리뷰 분석 서버 문제, 카드 id 틀림, 글 만들기 실패 | `{"error": {"message": "…"}}` | `error.message` 그대로 (`#alert` 또는 붙여넣기 메시지) |
| ② 요청 형식 오류 | 본문이 없거나 칸의 형식·범위가 틀림 | `{"detail": [{"type", "loc", "msg", "input", …}]}` (FastAPI 기본, **`msg`는 영어**) | `detail[0].msg` 그대로 (영어로 보임) |
| ③ 허용하지 않는 메서드 | 예: `GET /api/cards/x/run` | `{"detail": "Method Not Allowed"}` | `요청 실패 (405)` |
| ④ 예기치 못한 오류 | 코드가 처리하지 못한 오류 (예: 상권 지표 파일이 깨짐) | 일반 글자 `Internal Server Error` (JSON 아님) | `요청 실패 (500)` |

화면은 `error.message`, `detail[0].msg`, `요청 실패 (코드)` 순서로 문장을 고릅니다 (`app.js`의 `api()`).

**상태 코드**

| 코드 | 쓰이는 곳 |
|---|---|
| `200` | 성공 (대부분) |
| `201` | `POST /api/reviews` 성공 |
| `400` | `live`에서 글 만들기 실패 (키 없음, 모르는 재발 방지 조치 등) |
| `404` | 카드 id가 지금 화면의 카드가 아님, 저장 예시가 이 카드에 안 맞음 |
| `405` | 허용하지 않는 메서드 |
| `422` | 요청 형식·범위 오류 |
| `500` | 예기치 못한 오류 |
| `502` | `live`에서 글을 만들다가 HCX 호출 쪽에서 예상 못한 오류가 남 (11/14. 화면 알림 띠로 보임. 다시 누르면 됨) |
| `503` | 리뷰 분석 서버에 연결하지 못함 또는 그 서버가 오류를 돌려줌 |

---

## 1부. API 9개

### 1.0 한눈에 보기

경로 9개는 `services/web/web/main.py`와 같습니다.

| # | 메서드와 경로 | 하는 일 | 쓰는 화면 | 성공 |
|---|---|---|---|---|
| 1 | `GET /api/health` | 서버 상태, 시험용 여부, 막힌 곳 | 맨 위 띠, 바닥 '동작·모의 표시' | 200 |
| 2 | `GET /api/briefing` | 오늘의 브리핑 (숫자, 묶음, 리뷰 원문, 상권 지표) | 홈 `#/today`, 상단 가게 이름 | 200 |
| 3 | `GET /api/insight` | 리뷰 분석 (감정·주제 건수, 묶음), 읽기 전용 | 리뷰 분석 `#/analysis` | 200 |
| 4 | `GET /api/cards` | 오늘의 추천 카드 최대 2장 | 추천 카드 `#/cards`, 홈 '오늘 할 일' | 200 |
| 5 | `POST /api/cards/{card_id}/run` | 카드에 맞는 글 만들기 | 카드 버튼, 홈 '오늘 할 일', 초안 '다시 만들기' | 200 |
| 6 | `POST /api/drafts/{draft_id}/approve` | 글 승인 기록 | 초안 `#/draft` '승인' | 200 |
| 7 | `GET /api/approvals` | 서버의 승인 기록 목록 | 처리 완료 `#/done` '서버 처리 기록' | 200 |
| 8 | `POST /api/reviews` | 리뷰 한 건 붙여넣기, 바로 분류 | 리뷰 분석 '리뷰 붙여넣기' 탭 | 201 |
| 9 | `DELETE /api/reviews/pasted` | 붙여넣은 리뷰 모두 지우기 | 같은 탭 '붙여넣은 리뷰 지우기' | 200 |

표의 "화면" 칸은 `app.js`가 그 값을 읽어 쓰는 곳입니다. "안 씀"은 응답에는 있지만 지금 화면이 읽지 않는다는 뜻입니다. 읽지 않아도 칸 이름은 바꾸지 않습니다 (다른 도구가 읽을 수 있음).

---

### 1.1 `GET /api/health`

**하는 일**: 서버가 어떤 모드인지, 어디까지가 진짜이고 어디부터 시험용인지, 막힌 것이 있는지를 알려 줍니다.
**쓰는 화면**: 페이지를 열 때 한 번. 맨 위 시험용 띠(`#mode-notice`), 경고 띠(`#alert`), 바닥 '동작·모의 표시'(`#honesty`).

**요청**: `GET /api/health`. 본문 없음.

**응답 `200`** (줄이지 않음):

```json
{
  "mode": "mock",
  "mode_label": "시험용 실행",
  "mode_notice": "시험용 실행 · 키 없이 저장된 예시 결과를 보여 줍니다 (실제 AI 결과 아님)",
  "store_id": "store_ongi",
  "key_present": false,
  "c6_available": true,
  "seed_available": true,
  "review_service": {
    "url": "http://127.0.0.1:8020",
    "status": "ok",
    "mode": "mock",
    "spec_version": "0.1",
    "token_required": false,
    "models": {"review_classify": "rule"},
    "data_origin": "synthetic"
  },
  "snapshot": {"file": "snapshot_2026Q2.json", "count": 1, "error": null},
  "dev_fake_snapshots": [],
  "blocking": [],
  "parts": {
    "briefing": "리뷰 분류: rule",
    "cards": "규칙 + 고정 문장",
    "generate": "저장본(김수현 C6 결과)",
    "reviews": "합성 데이터"
  }
}
```

| 칸 | 뜻 | 화면 |
|---|---|---|
| `mode` | `"mock"` 또는 `"live"` | 안 씀 |
| `mode_label` | 사람이 읽는 모드 이름 (`"시험용 실행"` / `"실시간 HCX-005"`) | 안 씀 |
| `mode_notice` | mock일 때 띠에 보일 문장. live이면 `null` | `#mode-notice`. 값이 있으면 보이고, `null`이면 숨김 |
| `store_id` | 이 서버가 다루는 가게 id | 안 씀 |
| `key_present` | HCX 키가 설정돼 있는지 (키 값은 주지 않음) | 안 씀 |
| `c6_available` | 글 만드는 코드(`experiments/marketing/c6`)를 불러올 수 있는지 | 안 씀 |
| `seed_available` | 저장 예시 파일(`c6_cache_best.json`)이 있는지 | 안 씀 |
| `review_service` | 리뷰 분석 서버 상태. 켜져 있으면 그 서버의 `/api/health` 응답에 `url`을 더한 것. 꺼져 있으면 `{"url", "status": "down", "error": "ConnectError"}`. 응답이 200이 아니면 `status`가 `"http 500"` 같은 글자 | `status`가 `"down"`이면 경고 띠에 "리뷰 분석 서비스(주소)가 꺼져 있어요." |
| `review_service.status` · `mode` · `spec_version` · `token_required` · `models.review_classify` · `data_origin` | 켜져 있을 때 리뷰 분석 서버가 알려 주는 칸: `status`(`"ok"`), `mode`(그 서버의 모드), `spec_version`, `token_required`(접근 토큰이 필요한지), `models.review_classify`(분류에 쓰는 것. mock이면 `"rule"`), `data_origin` | 안 씀 (`models.review_classify`는 `parts.briefing`의 "리뷰 분류: rule"로 보임) |
| `snapshot` | 상권 지표 파일 정보. `file`(이름), `count`(지표 수), `error`(읽기 오류 문장 또는 `null`) | 안 씀 |
| `dev_fake_snapshots` | 개발용 가짜 지표의 id 목록 (`note`가 "개발용 가짜 값"으로 시작하는 지표) | 하나라도 있으면 경고 띠 맨 앞에 "개발용 가짜 지표가 화면에 있어요…" |
| `blocking` | 막힌 이유 문장 목록. 비어 있으면 정상 | 경고 띠에 이어 붙여 보여 줌 |
| `parts` | 바닥 '동작·모의 표시'에 쓰는 네 줄 (`reviews`, `briefing`, `cards`, `generate`) | `#honesty`에 `리뷰: …`, `…`, `카드: …`, `글 생성: …` 순서로 |

`blocking`에 들어갈 수 있는 문장 (코드 기준. 아래 'C6'는 글 만드는 코드, 'C4'는 상권 지표 파일):

- live인데 키가 없을 때: "APP_MODE=live 인데 HCX 키가 없어요. 키 파일(~/.config/teletubby-aiic/env)을 확인하세요."
- live인데 글 만드는 코드를 못 찾을 때: "C6 코드(c6/registry.py)를 찾지 못했어요: (경로)"
- mock인데 저장 예시 파일이 없을 때: "C6 저장본(c6/replay/c6_cache_best.json)을 찾지 못해 ③ 생성이 막혀요: (경로)"
- 상권 지표 파일이 없을 때: "상권 지표 파일을 찾지 못해 카드 ⓑ 가 뜨지 않아요: (경로)"

**오류**: 이 API는 리뷰 분석 서버가 꺼져 있어도 `200`을 줍니다. 대신 `review_service`로 알립니다. 리뷰 분석 서버가 꺼졌을 때 바뀌는 칸만 보입니다 (줄임: 바뀌는 칸만 남김).

```json
{
  "review_service": {"url": "http://127.0.0.1:8020", "status": "down", "error": "ConnectError"},
  "parts": {"briefing": "리뷰 분류: ?"}
}
```

키 없이 `live`로 띄웠을 때 바뀌는 칸 (줄임: 바뀌는 칸만 남김. 실제로 뽑은 값):

```json
{
  "mode": "live",
  "mode_label": "실시간 HCX-005",
  "mode_notice": null,
  "key_present": false,
  "blocking": ["APP_MODE=live 인데 HCX 키가 없어요. 키 파일(~/.config/teletubby-aiic/env)을 확인하세요."],
  "parts": {"cards": "규칙 + HCX-005 이유 문장", "generate": "실시간 HCX-005"}
}
```

**참고**
- 서버 배포 계획서(`docs/infra/architecture.md`)가 로드 밸런서의 상태 확인 경로로 `/api/health`를 쓰기로 했습니다. 이 경로와 `200` 응답은 바꾸지 않습니다.
- 상권 지표 파일이 깨져 있어도 이 API는 `200`을 주고 `snapshot.error`에 문장을 넣습니다. 같은 이유로 `briefing`과 `cards`는 `500`이 납니다 (1.2 참고).

---

### 1.2 `GET /api/briefing`

**하는 일**: 오늘의 브리핑에 필요한 것을 한 번에 줍니다. 리뷰 분석 서버에서 가게·리뷰·분석 결과를 받아 화면용으로 가공하고, 상권 지표 파일을 읽어 더합니다.
**쓰는 화면**: 홈 `#/today` (숫자 타일, 시간·주제 차트, 오늘의 핵심 문제, 상권 저녁 매출 칸), 상단 바의 가게 이름, 초안 화면의 '손님 리뷰' 칸(리뷰 원문).

**요청**: `GET /api/briefing`. 본문 없음.

**응답 `200`** (줄임: `groups` 3개 중 1개, `single_complaints` 5개 중 2개만 남김. 나머지 칸은 그대로):

```json
{
  "store": {
    "name": "온기한식 (가상)",
    "business_type_name": "한식음식점",
    "data_origin": "synthetic",
    "area_name": "장승배기역 4번"
  },
  "period": {"start": "2026-10-12", "end": "2026-11-08"},
  "counts": {"review_count": 40, "complaint_count": 12, "group_count": 3, "single_complaint_count": 5},
  "repeated_count": 1,
  "top_issue_id": "iss_missing_item",
  "groups": [
    {
      "issue_id": "iss_missing_item",
      "topic_name": "포장 누락",
      "review_count": 3,
      "is_repeated": true,
      "main_time_band": "17~21시",
      "time_bands": {"00~06시": 0, "06~11시": 0, "11~14시": 0, "14~17시": 0, "17~21시": 3, "21~24시": 0},
      "evidence": [
        {"review_id": "rv_ongi_001", "quote": "안 들어 있었어요"},
        {"review_id": "rv_ongi_002", "quote": "수저랑 젓가락이 빠져 있었어요"},
        {"review_id": "rv_ongi_003", "quote": "누락됐어요"}
      ],
      "reviews": [
        {
          "review_id": "rv_ongi_001",
          "text": "공깃밥 추가했는데 안 들어 있었어요",
          "rating": 2,
          "channel": "배민",
          "created_at": "2026-10-27T19:30:00+09:00",
          "input_method": "sample"
        },
        {
          "review_id": "rv_ongi_002",
          "text": "수저랑 젓가락이 빠져 있었어요",
          "rating": 2,
          "channel": "쿠팡이츠",
          "created_at": "2026-11-03T20:10:00+09:00",
          "input_method": "sample"
        },
        {
          "review_id": "rv_ongi_003",
          "text": "계란말이를 같이 시켰는데 누락됐어요",
          "rating": 1,
          "channel": "요기요",
          "created_at": "2026-11-06T19:50:00+09:00",
          "input_method": "sample"
        }
      ]
    }
  ],
  "single_complaints": [
    {
      "review_id": "rv_ongi_008",
      "topics": ["hygiene"],
      "topic_names": ["위생"],
      "quote": "반찬 그릇에 머리카락이 있었어요",
      "created_at": "2026-10-21T12:40:00+09:00",
      "channel": "naver_place"
    },
    {
      "review_id": "rv_ongi_009",
      "topics": ["service"],
      "topic_names": ["응대"],
      "quote": "응대가 퉁명스러웠어요",
      "created_at": "2026-10-24T19:20:00+09:00",
      "channel": "baemin"
    }
  ],
  "pasted": [],
  "snapshots": [
    {
      "snapshot_id": "snap_3110826_evening_17_24_common_yoy_2026Q2",
      "area_name": "장승배기역 4번",
      "metric_name": "저녁 시간대(17~24시) 추정매출 전년 동기 대비 변화율 · 두 분기 공통 업종",
      "value": -19.306697315937033,
      "unit": "%",
      "basis_quarter": "2026Q2",
      "is_estimate": true,
      "source": "서울시 상권분석서비스 · https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do",
      "compared_with_quarter": "2025Q2",
      "note": "상권코드 3110826. 17~21시와 21~24시 추정매출 합산. 비교 두 분기 공통 12개 업종 기준: 2025Q2 2,778,386,532원 → 2026Q2 2,241,971,854원. 후보 5곳 비교로 선정; 서울 전체 하락률 1위가 아님. 관측 업종 합계는 -19.99%. 하루 전체 매출·개별 가게 실적과 구분.",
      "basis_label": "기준: 2026 2분기 · 추정 · 출처 서울시 상권분석서비스 · https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do",
      "quarter_label": "2026 2분기",
      "dev_fake": false
    }
  ],
  "data_origin": "synthetic"
}
```

| 칸 | 뜻 | 화면 |
|---|---|---|
| `store.name` · `store.business_type_name` · `store.area_name` | 가게 이름, 업종 이름, 상권 이름 | 상단 바 `#store-name`: "이름 · 업종 · 상권이름 상권" |
| `store.data_origin` | `"synthetic"` = 합성 데이터 | 안 씀 |
| `period.start` · `period.end` | 분석 기간 (`YYYY-MM-DD`) | 홈 눈썹 줄과 "n일 동안" 계산 |
| `counts.review_count` | 기간 안 전체 리뷰 수 | 홈 '리뷰' 타일 |
| `counts.complaint_count` | 그중 불만 리뷰 수 | 홈 '불만' 타일 |
| `counts.group_count` · `counts.single_complaint_count` | 묶음 수, 묶이지 않은 불만 수 | 안 씀 |
| `repeated_count` | 반복 묶음(3건 이상) 수 | 안 씀 (화면이 `groups`에서 직접 셈) |
| `top_issue_id` | 가장 큰 반복 묶음의 id. 없으면 `null`일 수 있음 | '오늘의 핵심 문제', 차트의 빨간 막대 |
| `groups[]` | 불만 묶음 목록 | 홈 숫자·차트·핵심 문제 |
| `groups[].issue_id` | 묶음 id (예: `iss_missing_item`) | 핵심 문제 찾기 |
| `groups[].topic_name` | 묶음 이름 (한국어) | 주제별 불만 막대, 핵심 문제 문장 |
| `groups[].review_count` · `is_repeated` | 묶음의 리뷰 수, 반복 여부 | '반복 불만' 타일 |
| `groups[].main_time_band` | 불만이 몰린 시간대 (예: `"17~21시"`). 없으면 `null` | 핵심 문제 문장, 차트의 빨간 막대 범위 |
| `groups[].time_bands` | 시간대별 건수 `{구간: 건수}` (이 예시는 6구간) | 안 씀 (분석 화면은 `/api/insight`의 것을 씀) |
| `groups[].evidence[]` | 근거 인용 `{review_id, quote}` | 안 씀 |
| `groups[].reviews[]` | 묶음에 든 리뷰 원문 | 홈 차트(작성 시각), 초안 화면 '손님 리뷰' |
| `…reviews[].review_id` · `text` · `rating` · `created_at` · `input_method` | 리뷰 id, 글, 별점(없으면 `null`), 작성 시각, 입력 방법 (`"sample"` 합성 / `"paste"` 붙여넣음) | 위와 같음 |
| `…reviews[].channel` | 배달앱 이름. **한국어로 바꿔서** 줌 (`"배민"`, `"쿠팡이츠"`, `"요기요"`, `"네이버 플레이스"`) | 초안 화면 '손님 리뷰' |
| `single_complaints[]` | 어느 묶음에도 안 든 불만 | 홈 차트·주제 막대 (`topic_names[0]`, `created_at`만 씀) |
| `…[].review_id` · `topics` · `topic_names` · `quote` · `created_at` · `channel` | 리뷰 id, 주제 id 목록, 주제 이름 목록, 불만 인용, 작성 시각, 배달앱. **여기 `channel`은 코드**(`"baemin"`)로 줌 | 위에 적은 것만 씀 |
| `pasted[]` | 붙여넣은 리뷰 (최근 것이 위). 모양은 `groups[].reviews[]`와 같음 | 초안 화면 '손님 리뷰' |
| `snapshots[]` | 상권 지표 목록 | 홈 '상권 저녁 매출' 타일 (값이 있고 `dev_fake`가 아닌 첫 지표의 `value`·`unit`·`area_name`) |
| `snapshots[].snapshot_id` · `area_name` · `metric_name` | 지표 id, 상권 이름, 지표 이름 | `area_name`만 씀 |
| `snapshots[].value` · `unit` | 값(숫자, 자료가 없으면 `null`)과 단위 (`"%"`) | 타일 숫자 |
| `snapshots[].basis_quarter` · `compared_with_quarter` · `is_estimate` · `source` · `note` | 기준 분기(`"2026Q2"`), 비교 분기, 추정 여부, 출처, 설명 메모 | 안 씀 (카드 근거에서 `basis_label`과 `note`로 보임) |
| `snapshots[].basis_label` · `quarter_label` | 화면용 한 줄 ("기준: 2026 2분기 · 추정 · 출처 …"), "2026 2분기" | 안 씀 |
| `snapshots[].dev_fake` | 개발용 가짜 지표인지 | 가짜가 아닌 지표만 타일에 씀 |
| `data_origin` | `"synthetic"` = 합성 데이터 | 안 씀 |

붙여넣은 리뷰가 있을 때 `pasted`의 한 칸은 이런 모양입니다 (`1.8`에서 붙여넣은 바로 그 리뷰):

```json
{
  "review_id": "rv_ongi_paste_001",
  "text": "포장이 허술해서 국물이 새고 반찬이 하나 빠졌어요. 연락은 [가림] 으로 주세요",
  "rating": 2,
  "channel": null,
  "created_at": "2026-11-08T23:00:00+09:00",
  "input_method": "paste"
}
```

**오류**

- `503`: 리뷰 분석 서버가 꺼져 있거나 오류를 줌. 리뷰 분석 서버를 부르는 API(1.2~1.5, 1.8, 1.9)는 꺼졌을 때 모두 같은 모양과 같은 문장입니다 (아래 예시. 실제로 확인함).
- `500`: 상권 지표 파일이 있는데 JSON이 깨져 있을 때 (확인함). 본문은 일반 글자 `Internal Server Error`입니다.
- 상권 지표 파일이 **없으면** 오류가 아니라 `snapshots`가 빈 목록입니다 (코드 기준. 이때 홈 상권 타일은 "–", "상권 지표 없음").

```json
{
  "error": {"message": "리뷰 분석 서비스(http://127.0.0.1:8020)에 연결하지 못했습니다: ConnectError"}
}
```

**참고**
- 이 API는 요청 한 번에 리뷰 분석 서버를 세 번 부릅니다 (가게, 리뷰, 분석 결과).
- 배달앱 이름(`channel`)이 `groups[].reviews[]`에서는 한국어, `single_complaints[]`에서는 코드입니다. 화면에 보이는 곳은 앞쪽(한국어)뿐입니다.

---

### 1.3 `GET /api/insight`

**하는 일**: 리뷰 분석 서버의 분석 결과(감정·주제 건수, 묶음, 묶이지 않은 불만) 중 **화면에 쓰는 칸만** 걸러서 줍니다. 읽기 전용입니다 (`POST`·`DELETE`는 `405`).
**쓰는 화면**: 리뷰 분석 `#/analysis`의 '요약' 탭과 '불만 묶음' 탭.

**요청**: `GET /api/insight`. 본문 없음.

**응답 `200`** (줄임: `topic_counts` 13개 주제 중 3개, `groups` 3개 중 1개, `single_complaints` 5개 중 2개만 남김):

```json
{
  "period_start": "2026-10-12",
  "period_end": "2026-11-08",
  "review_count": 40,
  "complaint_count": 12,
  "sentiment_counts": {"negative": 12, "positive": 26, "neutral": 2},
  "topic_counts": {
    "missing_item": {"positive": 0, "negative": 3},
    "delivery_time": {"positive": 2, "negative": 2},
    "taste": {"positive": 13, "negative": 2}
  },
  "group_count": 3,
  "single_complaint_count": 5,
  "top_issue_id": "iss_missing_item",
  "groups": [
    {
      "issue_id": "iss_missing_item",
      "topics": ["missing_item"],
      "topic": "missing_item",
      "topic_name": "포장 누락",
      "review_count": 3,
      "is_repeated": true,
      "review_ids": ["rv_ongi_001", "rv_ongi_002", "rv_ongi_003"],
      "evidence": [
        {"review_id": "rv_ongi_001", "quote": "안 들어 있었어요"},
        {"review_id": "rv_ongi_002", "quote": "수저랑 젓가락이 빠져 있었어요"},
        {"review_id": "rv_ongi_003", "quote": "누락됐어요"}
      ],
      "time_bands": {"00~06시": 0, "06~11시": 0, "11~14시": 0, "14~17시": 0, "17~21시": 3, "21~24시": 0},
      "main_time_band": "17~21시",
      "channels": {"baemin": 1, "coupangeats": 1, "yogiyo": 1},
      "recent_count": 3,
      "previous_count": 0,
      "first_at": "2026-10-27T19:30:00+09:00",
      "last_at": "2026-11-06T19:50:00+09:00"
    }
  ],
  "single_complaints": [
    {
      "review_id": "rv_ongi_008",
      "topics": ["hygiene"],
      "topic_names": ["위생"],
      "quote": "반찬 그릇에 머리카락이 있었어요",
      "created_at": "2026-10-21T12:40:00+09:00",
      "channel": "naver_place"
    },
    {
      "review_id": "rv_ongi_009",
      "topics": ["service"],
      "topic_names": ["응대"],
      "quote": "응대가 퉁명스러웠어요",
      "created_at": "2026-10-24T19:20:00+09:00",
      "channel": "baemin"
    }
  ],
  "data_origin": "synthetic"
}
```

| 칸 | 뜻 | 화면 |
|---|---|---|
| `period_start` · `period_end` | 분석 기간 | 분석 화면 위 눈썹 줄, "n일" 계산 |
| `review_count` · `complaint_count` | 전체 리뷰 수, 불만 리뷰 수 | 요약 탭 '리뷰'·'불만' 타일, 불만 묶음 탭의 흐름 한 줄 |
| `sentiment_counts` | 감정별 리뷰 수 (이 예시는 `negative`, `positive`, `neutral`) | 요약 탭 '리뷰' 타일 아래 "긍정 n · 중립 n" |
| `topic_counts` | 주제별 `{positive: 건수, negative: 건수}`. 리뷰 하나에 주제가 여럿이면 모두 셈 | 요약 탭 '칭찬 키워드'·'불만 키워드' (건수 많은 8개) |
| `group_count` · `single_complaint_count` | 묶음 수, 묶이지 않은 불만 수 | 안 씀 (화면이 배열 길이로 셈) |
| `top_issue_id` | 가장 큰 반복 묶음 id. 없으면 `null`일 수 있음 | 묶음 카드의 '추천 카드 ⓐ 근거' 배지 |
| `groups[]` | 불만 묶음 | 불만 묶음 탭의 묶음 카드 |
| `groups[].issue_id` · `topic_name` · `review_count` · `is_repeated` | 묶음 id, 이름, 리뷰 수, 반복 여부 | 카드 제목·'반복' 배지 |
| `groups[].topics` · `topic` | 묶음에 든 주제 id 목록, 대표 주제 id | 안 씀 |
| `groups[].review_ids` | 묶음에 든 리뷰 id | 안 씀 |
| `groups[].evidence[]` | 근거 인용 `{review_id, quote}` | 카드의 인용 (앞 3개) |
| `groups[].time_bands` · `main_time_band` | 시간대별 건수, 가장 많은 시간대 | 시간대 막대, "주로 17~21시" |
| `groups[].channels` | 배달앱별 건수 (**코드** 키: `baemin`, `coupangeats`, `yogiyo`, `naver_place`. 배달앱을 모르는 리뷰는 `unknown`) | 안 씀 |
| `groups[].recent_count` · `previous_count` | 최근 2주·그 앞 2주 건수 | "앞 2주 n건 → 최근 2주 n건" |
| `groups[].first_at` · `last_at` | 묶음 안 첫·마지막 리뷰 시각 | 안 씀 |
| `single_complaints[]` | 묶이지 않은 불만 `{review_id, topics, topic_names, quote, created_at, channel}` | '묶이지 않은 불만' 목록 (`topic_names`, `quote`, `review_id`) |
| `data_origin` | `"synthetic"` = 합성 데이터 | 눈썹 줄에 "리뷰는 합성 데이터" |

주제 id와 화면에 보이는 이름 (`app.js`의 `TOPIC_NAMES`. 모르는 id는 id가 그대로 보임):

| id | 이름 | id | 이름 | id | 이름 |
|---|---|---|---|---|---|
| `texture` | 식감 | `taste` | 맛 | `portion` | 양 |
| `price` | 가격 | `delivery_time` | 배달 시간 | `temperature` | 음식 온도 |
| `packaging` | 포장 상태 | `missing_item` | 포장 누락 | `service` | 응대 |
| `hygiene` | 위생 | `menu` | 메뉴 구성 | `atmosphere` | 매장 환경 |
| `wait_time` | 매장 대기 | | | | |

감정 이름 (`SENTIMENT_NAMES`): `positive` 긍정, `negative` 부정, `neutral` 중립, `mixed` 긍정·부정 섞임.

**오류**: `503` 리뷰 분석 서버 문제 (모양은 1.2의 `503` 예시와 같음). `405` `POST`·`DELETE`로 부름.

**참고**: `/api/briefing`의 `groups`와 겹치지만 칸이 다릅니다. 홈은 briefing, 리뷰 분석 화면은 insight를 씁니다.

---

### 1.4 `GET /api/cards`

**하는 일**: 오늘 띄울 추천 카드를 **규칙으로** 정해 줍니다 (최대 2장). 이유 문장과 근거도 같이 줍니다.

- 카드 ⓐ(불만 대응): `top_issue_id`가 가리키는 묶음. 반복 묶음이 없으면 만들지 않습니다.
- 카드 ⓑ(쿠폰 홍보): 상권 지표를 고정된 우선순위(환경변수 `CARD_B_SNAPSHOT_ID` → `snap_evening_sales_yoy` → 단위가 `%`인 첫 '추정매출' 지표)로 **먼저 하나 고르고**, 그 값이 기준(`CARD_B_THRESHOLD`, 기본 -5) 이하일 때만 만듭니다. 고른 지표가 하락이 아니면 다른 지표를 찾지 않습니다.
- 카드 ⓑ의 손님 칭찬 근거 (11/16): 가격 있는 메뉴 가운데 **손님 칭찬 리뷰에 가장 많이 언급된 메뉴**를 쿠폰 메뉴로 고르고, 그 메뉴와 언급 건수를 제목·이유 문장·근거 카드(`F3`)·근거(`evidence`의 `type: "praise"`)에 붙입니다. 칭찬 리뷰는 감정 분류가 긍정인 리뷰입니다 (분류가 하나도 없으면 별점 4점 이상이면서 불만 주제가 없는 리뷰). 같은 수면 메뉴판 순서가 앞선 메뉴입니다. 글 만드는 코드(`c6/promo.py`)도 같은 함수(`shared/praise.py`의 `pick_praised_menu`)로 쿠폰 메뉴를 고르므로 **카드가 말한 메뉴와 홍보글의 쿠폰 메뉴가 같습니다**.
  - 사실대로 씁니다: 메뉴판 전체에서 혼자 가장 많이 언급된 메뉴일 때만 "…언급이 3건으로 가장 많아요"라고 쓰고, 같은 수의 메뉴가 있거나 가격 없는 메뉴가 더 많이 언급됐으면 "…언급이 1건 있어요"라고만 씁니다.
  - 칭찬 리뷰에 그 메뉴 언급이 없으면 (또는 리뷰를 계약 형식으로 바꾸지 못하면) 칭찬 근거 없이 예전 카드 그대로입니다 (`F2`만, 제목 "… 하락 → 쿠폰 홍보", `review_ids`는 `[]`).
  - mock의 홍보글은 저장 예시(쿠폰 메뉴 '제육볶음 정식')입니다. 붙여넣은 칭찬 리뷰 때문에 고른 메뉴가 저장 예시의 메뉴와 달라지면, mock에서는 칭찬 근거를 붙이지 않습니다 (카드가 저장 예시와 다른 메뉴를 말하지 않게). live는 고른 메뉴로 홍보글을 새로 씁니다.
- 이유 문장: mock은 고정 문장입니다. live는 HCX-005가 한 문장을 쓰고, 규칙 검사를 못 넘으면 고정 문장으로 돌아갑니다. 칭찬 근거가 붙은 카드 ⓑ는 live에서 **모델이 상권 지표 문장과 할 일 문장만 쓰고, 칭찬 근거 한 줄(메뉴·건수)은 코드가 그 사이에 끼워 넣습니다**. 모델에게 두 근거를 함께 주면 "제육볶음 정식 매출이 19.31% 감소"처럼 섞어 쓴 문장이 검사를 통과했기 때문입니다 (11/16 실시간 확인). 그래서 `reason_source`가 `"HCX-005 (검사기 통과)"`여도 칭찬 근거 줄은 코드가 쓴 글입니다.

**쓰는 화면**: 추천 카드 `#/cards`, 홈 '오늘 할 일'.

**요청**: `GET /api/cards`. 본문 없음.

**응답 `200`** (줄임: 카드 ⓐ의 `measures.options` 5개 중 3개만 남김. 나머지는 그대로):

```json
{
  "cards": [
    {
      "card": {
        "card_id": "card_ongi_a",
        "store_id": "store_ongi",
        "kind": "complaint",
        "reason_text": "포장 누락 불만이 3건 반복됐고, 모두 17~21시에 들어왔어요",
        "review_ids": ["rv_ongi_001", "rv_ongi_002", "rv_ongi_003"],
        "snapshot_ids": []
      },
      "title": "포장 누락 3건 반복 → 재발 방지 공지 + 답글",
      "reason_source": "고정 문장",
      "checked_text": "포장 누락 불만이 3건 반복됐고, 모두 17~21시에 들어왔어요 [F1]",
      "facts": [
        {
          "id": "F1",
          "topic": "review_issue",
          "status": "available",
          "text": "포장 누락 불만 리뷰 3건, 반복 묶음, 주로 17~21시",
          "values": [
            {"label": "포장 누락 불만 리뷰", "value": 3, "unit": "건"}
          ],
          "keep": ["17~21시"]
        }
      ],
      "evidence": [
        {"type": "review", "id": "rv_ongi_001", "text": "안 들어 있었어요"},
        {"type": "review", "id": "rv_ongi_002", "text": "수저랑 젓가락이 빠져 있었어요"},
        {"type": "review", "id": "rv_ongi_003", "text": "누락됐어요"}
      ],
      "problems": [],
      "measures": {
        "options": [
          {"id": "M1", "text": "포장 마감 전 주문서 대조"},
          {"id": "M2", "text": "출발 전 품목 수량 확인"},
          {"id": "M3", "text": "소스·반찬 별도 체크리스트 부착"}
        ],
        "default": ["M1"]
      }
    },
    {
      "card": {
        "card_id": "card_ongi_b",
        "store_id": "store_ongi",
        "kind": "promo",
        "reason_text": "장승배기역 4번 상권의 저녁 시간대(17~24시) 추정매출(두 분기 공통 업종): 2026년 2분기, 전년 동기 대비 19.31% 감소\n손님 칭찬 리뷰에 제육볶음 정식 언급이 1건 있어요\n저녁 손님을 다시 부르는 제육볶음 정식 쿠폰 홍보를 제안해요.",
        "review_ids": ["rv_ongi_013"],
        "snapshot_ids": ["snap_3110826_evening_17_24_common_yoy_2026Q2"]
      },
      "title": "저녁 시간대(17~24시) 추정매출(두 분기 공통 업종) 하락 → '제육볶음 정식' 쿠폰 홍보",
      "reason_source": "고정 문장",
      "checked_text": "장승배기역 4번 상권의 저녁 시간대(17~24시) 추정매출(두 분기 공통 업종): 2026년 2분기, 전년 동기 대비 19.31% 감소 [F2]\n손님 칭찬 리뷰에 제육볶음 정식 언급이 1건 있어요 [F3]\n저녁 손님을 다시 부르는 제육볶음 정식 쿠폰 홍보를 제안해요.",
      "facts": [
        {
          "id": "F2",
          "topic": "market_sales_change",
          "status": "available",
          "text": "장승배기역 4번 상권, 2026년 2분기 저녁 시간대(17~24시) 추정매출(두 분기 공통 업종), 2025년 2분기 대비. 출처 서울시 상권분석서비스 · https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do",
          "values": [
            {
              "label": "저녁 시간대(17~24시) 추정매출(두 분기 공통 업종) 전년 동기 대비 변화율",
              "value": -19.31,
              "unit": "%"
            }
          ],
          "keep": ["장승배기역 4번 상권", "17~24시"]
        },
        {
          "id": "F3",
          "topic": "review_praise",
          "status": "available",
          "text": "손님 칭찬 리뷰에 제육볶음 정식 언급 1건 (언급 수가 같거나 더 많은 다른 메뉴가 있음)",
          "values": [
            {"label": "쿠폰 메뉴를 언급한 칭찬 리뷰", "value": 1, "unit": "건"},
            {"label": "쿠폰 메뉴", "value": "제육볶음 정식"}
          ],
          "keep": ["제육볶음 정식"],
          "avoid": ["가장", "제일", "최다", "1위"]
        }
      ],
      "evidence": [
        {
          "type": "snapshot",
          "id": "snap_3110826_evening_17_24_common_yoy_2026Q2",
          "text": "저녁 시간대(17~24시) 추정매출(두 분기 공통 업종) -19.31%",
          "basis": "기준: 2026 2분기 · 추정 · 출처 서울시 상권분석서비스 · https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do",
          "note": "상권코드 3110826. 17~21시와 21~24시 추정매출 합산. 비교 두 분기 공통 12개 업종 기준: 2025Q2 2,778,386,532원 → 2026Q2 2,241,971,854원. 후보 5곳 비교로 선정; 서울 전체 하락률 1위가 아님. 관측 업종 합계는 -19.99%. 하루 전체 매출·개별 가게 실적과 구분."
        },
        {
          "type": "praise",
          "id": "rv_ongi_013",
          "text": "제육볶음이 불맛 나고 정말 맛있어요!",
          "menu": "제육볶음 정식",
          "rating": 5
        }
      ],
      "problems": [],
      "measures": {}
    }
  ],
  "no_card_b": null
}
```

| 칸 | 뜻 | 화면 |
|---|---|---|
| `cards` | 카드 목록. 카드가 없으면 `[]` (화면은 "오늘은 추천할 카드가 없어요.") | 카드 화면 |
| `cards[].card.card_id` | 카드 id (`card_ongi_a`, `card_ongi_b`). `POST …/run`의 경로에 씀 | 버튼의 `data-run`, 글 보관 키 |
| `cards[].card.store_id` | 가게 id | 안 씀 |
| `cards[].card.kind` | `"complaint"`(불만 대응) 또는 `"promo"`(쿠폰 홍보) | 카드 이름, 담당 AI 직원 이름, 버튼 글자 |
| `cards[].card.reason_text` | 카드를 띄운 이유 문장. 줄바꿈(`\n`)이 들어갈 수 있음 | 카드 본문 (`white-space: pre-line`이 줄바꿈을 살림) |
| `cards[].card.review_ids` | 근거 리뷰 id. 카드 ⓐ는 묶음의 불만 리뷰, 카드 ⓑ는 쿠폰 메뉴를 언급한 칭찬 리뷰 **전부** (칭찬 근거가 없으면 `[]`) | 카드가 바뀌었는지 비교 (칭찬 근거가 바뀌면 만들어 둔 홍보글도 버림), 카드 ⓑ의 칭찬 리뷰 건수 |
| `cards[].card.snapshot_ids` | 근거 상권 지표 id (카드 ⓑ) | 위와 같음 |
| `cards[].title` | 카드 제목. 카드 ⓑ는 칭찬 근거가 있으면 쿠폰 메뉴가 들어감 (`… 하락 → '제육볶음 정식' 쿠폰 홍보`), 없으면 `… 하락 → 쿠폰 홍보` | 카드 제목, 초안 화면 제목 |
| `cards[].reason_source` | 이유 문장 출처. `"고정 문장"`, `"HCX-005 (검사기 통과)"`, `"HCX-005 검사 불통과 → 고정 문장"`, `"HCX-005 실패(오류이름) → 고정 문장"`, `"고정 문장 (검사기 경고)"` | '근거 보기' 안 "이유 문장: …" |
| `cards[].checked_text` | 검사기를 통과한 문장 (`[F1]` 같은 근거 표시 포함) | 안 씀 |
| `cards[].facts[]` | 이유 문장의 근거 카드 `{id, topic, status, text, values[{label, value, unit}], keep[]}`. 카드 ⓑ의 `F3`(손님 칭찬)에는 글자 값(`{label: "쿠폰 메뉴", value: "메뉴 이름"}`, `unit` 없음)이 하나 더 있고, 혼자 1등이 아니면 `avoid[]`(이유 문장에 쓰면 안 되는 말: 가장·제일·최다·1위)가 붙음 | 안 씀 |
| `cards[].evidence[]` | 근거. 불만 리뷰면 `{type:"review", id, text}`, 상권 지표면 `{type:"snapshot", id, text, basis, note}`, 쿠폰 메뉴를 칭찬한 리뷰면 `{type:"praise", id, text, menu, rating}` (카드 ⓑ, 최대 3건, `text`는 120자까지) | 카드의 '근거:' 줄과 '근거 보기' (`basis`의 주소는 '원본' 링크로), 홍보글 초안의 '근거 지표'·'손님 칭찬 리뷰' 두 덩어리, 홈 '오늘 할 일'의 홍보글 부제(`menu`) |
| `cards[].problems[]` | 모델 문장이 검사에 걸린 이유 (`{type, detail?}`). 없으면 `[]` | '근거 보기' 안 "검사기 지적 n건" |
| `cards[].measures` | 카드 ⓐ만: 재발 방지 조치 상자. `options[]`(`{id, text}`, 글 만드는 코드의 목록 `M1`~`M5`)와 `default`(처음 체크할 id 목록). 카드 ⓑ와 글 만드는 코드를 못 불러올 때는 `{}` | 카드 ⓐ의 체크박스 묶음 |
| `no_card_b` | 카드 ⓑ가 없을 때 그 이유 문장. 카드 ⓑ가 있으면 `null` | `#no-card-b` |

`no_card_b` 문장 종류 (코드 기준. 'C4'는 상권 지표 파일):

- 지표 파일이 없거나 비어 있음: "상권 지표 파일(C4)이 없어 카드 ⓑ 를 만들지 않았어요." (실제로 뽑아 확인함)
- 추정매출 변화율 지표가 없음: "추정매출 변화율 지표가 없어 카드 ⓑ 를 만들지 않았어요."
- 고른 지표의 값이 `null`: "'(지표 이름)' 값이 '자료 없음'이라 카드 ⓑ 를 만들지 않았어요."
- 값이 기준보다 높음: "'(지표 이름)' 값(-3.00%)이 기준(-5%)보다 높아 카드 ⓑ 를 만들지 않았어요."

**오류**: `503` 리뷰 분석 서버 문제 (모양은 1.2의 `503` 예시와 같음). 상권 지표 파일이 깨졌으면 `500`.

**참고**
- 카드 목록은 같은 입력이면 같은 결과입니다 (두 번 불러 같은 것을 확인함). live에서는 같은 입력일 때 HCX를 다시 부르지 않고 서버 메모리에 둔 문장을 줍니다. 검사에 걸려 고정 문장이 된 카드만 다음 요청 때 다시 시도합니다.
- 화면은 카드의 **위치**로 `ⓐ`·`ⓑ`를 붙입니다 (첫 번째면 ⓐ). 카드 id의 `_a`·`_b`와는 별개입니다. 카드 ⓐ가 없고 ⓑ만 있으면 화면에는 ⓑ가 `ⓐ`로 보입니다 (부록의 '알려진 특이점').

---

### 1.5 `POST /api/cards/{card_id}/run`

**하는 일**: 카드 한 장에 맞는 글을 만듭니다.

- 카드 ⓐ: 답글(근거 리뷰 한 건당 하나)과 재발 방지 공지 1개.
- 카드 ⓑ: 쿠폰 홍보글 1개. 쿠폰 메뉴는 가격 있는 메뉴 가운데 손님 칭찬 리뷰에 가장 많이 언급된 메뉴입니다 (같은 수거나 언급이 없으면 메뉴판 순서. 11/16 전에는 늘 메뉴판 첫 메뉴). 카드 ⓑ가 말한 메뉴와 같습니다 (1.4). 프롬프트의 '손님 반응' 칸에는 그 메뉴를 칭찬한 리뷰가 먼저 들어갑니다.
- mock: 저장된 예시 글을 이 카드에 맞게 바꿔 바로 줍니다. 실제 AI 결과가 아닙니다.
- live: HCX-005가 실시간으로 씁니다. 시간이 걸립니다 (저장 예시에 기록된 시간은 글 하나에 2.5~4.6초, 카드 하나에 6.8초. 배포 계획서는 글 생성이 14초를 넘을 때가 있다고 적음). 결과를 파일에 저장하지 않습니다.
- 응답은 **승인 전의 초안**입니다.

**쓰는 화면**: 추천 카드의 버튼(`[data-run]`), 홈 '오늘 할 일' 항목(아직 안 만든 글), 초안 화면의 '다시 만들기'.

**요청**: `POST /api/cards/{card_id}/run`

- `card_id`: `GET /api/cards`가 준 `card.card_id` (예: `card_ongi_a`). 지금 화면의 카드가 아니면 `404`.
- 본문은 **없어도 됩니다**. 카드 ⓐ에 재발 방지 조치 상자가 있으면 화면은 체크된 id를 이렇게 보냅니다.

```json
{"measures": ["M1"]}
```

| 칸 | 형식·범위 | 뜻 |
|---|---|---|
| `measures` | 문자열 목록, 또는 생략·`null` | 사장님이 고른 재발 방지 조치 id. 허용값은 그 카드의 `measures.options[].id` (`M1`~`M5`). 생략·`null`이면 카드의 `measures.default`를 씀. `[]`이면 고른 것 없음 |

- mock은 `measures` 값을 **무시**합니다. 틀린 id(`"M9"`)를 보내도 오류가 나지 않습니다 (확인함).
- live는 모르는 id를 보내면 `400` ("모르는 재발 방지 조치예요: M9", 확인함). 카드 ⓑ는 `measures`를 쓰지 않습니다.
- 고른 조치만 공지·답글에 들어갑니다. 고르지 않은 조치를 글이 지어내면 점검에서 걸립니다.

**응답 `200`, 카드 ⓐ** (줄임: `drafts` 4개 중 첫 답글과 재발 방지 공지만 남김. 답글 3개와 공지 1개가 실제 응답):

```json
{
  "card_id": "card_ongi_a",
  "kind": "complaint",
  "reason_text": "포장 누락 불만이 3건 반복됐고, 모두 17~21시에 들어왔어요",
  "basis_label": null,
  "drafts": [
    {
      "draft_id": "d_d368820d",
      "card_id": "card_ongi_a",
      "store_id": "store_ongi",
      "generator": "reply_draft",
      "target_review_id": "rv_ongi_001",
      "text": "안녕하세요 고객님 :) 공깃밥 추가로 보내드렸어요. 포장 마감 전 주문서를 다시 한번 확인하는 절차를 도입해서 이런 일이 다시 없도록 주의하겠습니다. 소중한 의견 감사합니다. 온기한식 드림",
      "evidence_ids": ["F_rv_ongi_001", "M1"],
      "checks": {
        "evidence_valid": true,
        "no_invented_measure": true,
        "chosen_measure_included": true,
        "missing_mentioned": true,
        "no_bad_promise": true,
        "no_bad_number": true,
        "no_personal_info": true,
        "length_ok": false,
        "no_stiff_words": true,
        "no_overpromise": true,
        "uses_opening": true,
        "uses_closing": true,
        "no_forbidden_phrase": true,
        "not_too_similar": true
      },
      "failed_reasons": [],
      "rewrites": 1,
      "needs_input": [],
      "status": "draft",
      "edited_text": null,
      "model": "HCX-005",
      "elapsed_ms": 2511,
      "data_origin": "synthetic",
      "c7_flags": ["이미 한 조치처럼 말함: '추가로 보내드렸' (사장님이 실제로 했는지 확인)"]
    },
    {
      "draft_id": "d_af7e466a",
      "card_id": "card_ongi_a",
      "store_id": "store_ongi",
      "generator": "prevention_notice",
      "target_review_id": null,
      "text": "안녕하세요 고객님 :) 주문이 잘못돼서 속상하셨죠? 진짜 죄송해요. 밥이랑 수저, 계란말이가 빠진 적이 몇 번 있었네요. 앞으론 주문서랑 꼼꼼히 비교해서 이런 실수 없게 할게요. 앞으로 포장 마감 전에 주문서와 한 번 더 대조할게요. 다음엔 요청 사항에 꼭 필요한 거 적어주시면 제가 특별히 더 잘 챙길게요! 온기한식 드림",
      "evidence_ids": ["F_rv_ongi_001", "F_rv_ongi_002", "F_rv_ongi_003", "M1"],
      "checks": {
        "no_bad_promise": true,
        "no_personal_info": true,
        "length_ok": true,
        "chosen_measure_included": true,
        "no_invented_measure": true,
        "not_quote_review": true,
        "no_stiff_words": true,
        "no_overpromise": true,
        "has_apology": false,
        "uses_opening": true,
        "uses_closing": true,
        "no_forbidden_phrase": true
      },
      "failed_reasons": ["첫 문장에 불편을 드려 죄송하다는 사과를 넣어 주세요."],
      "rewrites": 1,
      "needs_input": [],
      "status": "draft",
      "edited_text": null,
      "model": "HCX-005",
      "elapsed_ms": 4309,
      "data_origin": "synthetic",
      "c7_flags": []
    }
  ],
  "chosen_measures": [
    {"id": "M1", "text": "포장 마감 전 주문서 대조"}
  ],
  "elapsed_ms": 6821,
  "won": 24.94,
  "source": "seed",
  "source_note": "김수현 저장본(c6_cache_best.json, 샘플 카드 card_sample_a로 생성한 글). 이유 문장은 이 화면의 카드 문장으로 바꿈",
  "flagged_count": 2
}
```

**응답 `200`, 카드 ⓑ** (줄이지 않음):

```json
{
  "card_id": "card_ongi_b",
  "kind": "promo",
  "reason_text": "장승배기역 4번 상권의 저녁 시간대(17~24시) 추정매출(두 분기 공통 업종): 2026년 2분기, 전년 동기 대비 19.31% 감소\n손님 칭찬 리뷰에 제육볶음 정식 언급이 1건 있어요\n저녁 손님을 다시 부르는 제육볶음 정식 쿠폰 홍보를 제안해요.",
  "basis_label": "기준: 2026 2분기 · 추정 · 출처 서울시",
  "drafts": [
    {
      "draft_id": "d_9018bf15",
      "card_id": "card_ongi_b",
      "store_id": "store_ongi",
      "generator": "coupon_promo",
      "target_review_id": null,
      "text": "저녁 메뉴 아직 못 정했다면 이거 어때요? 손님들 사이에서 인기 폭발 중인 제육볶음이랑 언제 먹어도 맛있는 된장찌개를 준비했거든요. 밥 두 공기도 거뜬히 비우게 만드는 맛이라니까요!\n🎟 제육볶음 정식 1,000원 할인 쿠폰 · 받은 날 포함 14일",
      "evidence_ids": ["snap_3110826_evening_17_24_common_yoy_2026Q2", "coupon:제육볶음 정식"],
      "checks": {
        "no_bad_number": true,
        "no_personal_info": true,
        "no_coupon_invented": true,
        "no_stiff_words": true,
        "no_fewshot_copy": true,
        "no_bad_promise": true,
        "no_unknown_menu": false,
        "no_markdown": true,
        "length_ok": true,
        "no_forbidden_phrase": true
      },
      "failed_reasons": ["메뉴에 있는 음식 이름만 써 주세요."],
      "rewrites": 1,
      "needs_input": ["사장님 확인 필요"],
      "status": "draft",
      "edited_text": null,
      "model": "HCX-005",
      "elapsed_ms": 4614,
      "data_origin": "synthetic",
      "c7_flags": []
    }
  ],
  "chosen_measures": [],
  "elapsed_ms": 4614,
  "won": 12.51,
  "source": "seed",
  "source_note": "김수현 저장본(c6_cache_best.json, 샘플 카드 card_sample_b로 생성한 글). 이유 문장은 이 화면의 카드 문장으로 바꿈",
  "flagged_count": 1
}
```

응답 맨 위 칸:

| 칸 | 뜻 | 화면 |
|---|---|---|
| `card_id` · `kind` | 카드 id, 종류 | 안 씀 (화면은 요청한 카드 id로 결과를 보관) |
| `reason_text` | 카드 이유 문장. mock은 이 서버가 만든 카드 문장으로 바꿔 줌 | 안 씀 |
| `basis_label` | 홍보글의 근거 한 줄 (카드 ⓑ). 카드 ⓐ는 `null` | 안 씀 |
| `drafts[]` | 만든 글 목록 (아래 표) | 초안 화면 |
| `chosen_measures[]` | 사장님이 고른 조치 `{id, text}` | 초안 화면 위 "사장님이 고른 재발 방지 조치: …" |
| `elapsed_ms` | 글을 만드는 데 걸린 시간(밀리초). mock에서는 저장된 값 | 안 씀 |
| `won` | 모델 호출에 든 돈. 호출 응답의 `won` 값을 더한 것 (mock에서는 저장된 값) | 안 씀 |
| `source` | `"seed"`(시험용 저장 예시) 또는 `"live"`(실시간) | 초안 화면 위 배지: seed는 "시험용 저장 예시 (실제 AI 결과 아님)", live는 "실시간 HCX-005" |
| `source_note` | seed일 때만 있는 설명 문장 | 초안 화면 위 작은 글씨 |
| `flagged_count` | 확인이 필요한 글 수 (점검 실패 또는 확인 필요가 있는 글) | 안 씀 |
| `pasted_reply_review_ids` | 카드 ⓐ에서만, 붙여넣은 불만 리뷰가 있을 때만 있음. 카드 근거에 들지 않은 붙여넣은 리뷰 중 답글을 함께 만든 리뷰 id 목록(최대 3건). 그 답글은 `drafts[]` 맨 뒤에 붙음 | 안 씀 |
| `pasted_reply_skipped` | 위와 같은 조건. 답글을 만들지 못한 붙여넣은 리뷰 `{review_id, reason}` 목록. mock은 글이 똑같은 저장 예시가 있을 때만 답글을 붙임 | 안 씀 |
| `needs_input` | **live일 때만** 맨 위에 더해지는 목록 (글을 만들 때 빠졌던 정보, 문자열 목록). 코드 기준이며 live는 실행하지 않아 값은 확인하지 못함 | 안 씀 |

`drafts[]`의 칸:

| 칸 | 뜻 | 화면 |
|---|---|---|
| `draft_id` | 글 id (예: `d_d368820d`). `POST …/approve`의 경로에 씀. mock은 저장 예시의 id라 **매번 같음** (확인함). live의 id는 확인하지 못함 | 글 고르기·승인 |
| `card_id` · `store_id` | 카드 id, 가게 id | 안 씀 |
| `generator` | `"reply_draft"` / `"prevention_notice"` / `"coupon_promo"` | 글 이름, 정렬 |
| `target_review_id` | 답글이 답하는 리뷰 id. 공지·홍보글은 `null` | 초안 위쪽 '손님 리뷰' 칸 |
| `text` | AI가 쓴 글. 줄바꿈(`\n`)이 들어가고, 홍보글에는 이모지가 들어갈 수 있음 (예시의 쿠폰 줄). 글꼴이 이모지를 보여 줘야 함 | 편집 칸(`textarea`)의 처음 내용, 승인할 때 `original`로 보냄 |
| `edited_text` | 사장님이 고친 글. 처음엔 `null` (화면이 승인 뒤 채움) | 편집 칸 |
| `evidence_ids` | 글이 기댄 근거 id (`F_rv_…` 리뷰, `M1` 조치, `snap_…` 지표, `coupon:…` 쿠폰) | 안 씀 |
| `checks` | 자동 점검 결과 `{점검 이름: true/false}` (아래 표) | 안 씀 (`failed_reasons`가 화면 상태를 정함) |
| `failed_reasons` | 점검에 걸린 이유(고칠 점) 문장 목록 | '점검 실패' 상태와 목록 |
| `rewrites` | 점검에 걸려 다시 쓴 횟수 | 안 씀 |
| `needs_input` | 글에 필요한데 빠진 정보 (예: `"사장님 확인 필요"`). 사과 없이 설명하는 답글(`stance`가 `"explain"`)에는 늘 "사실 확인: …" 안내가 들어 있음 | '확인 필요' 상태와 목록 |
| `stance` | 답글의 태도. `"apology"`(사과하는 답글) 또는 `"explain"`(가게 원칙 밖 요청을 거절해 남은 리뷰로 보고, 사과 없이 사실·원칙을 설명하는 답글). 답글이 아닌 글과 mock의 기존 저장 예시는 `null` | 안 씀 (배지로 보여 주는 것은 제안 단계) |
| `stance_reasons` | 태도를 그렇게 정한 근거 문장 목록. 판정은 규칙이며 사실 여부는 사장님이 확인해야 함 | 안 씀 |
| `c7_flags` | 이 **비서 화면 서버**가 글에서 찾은 문구: 사장님이 하지 않은 조치를 이미 한 것처럼 말함("보내드렸어요"), 정하지 않은 보상 약속. 예: `"이미 한 조치처럼 말함: '추가로 보내드렸' (사장님이 실제로 했는지 확인)"` | '확인 필요' 상태와 목록 |
| `status` | `"draft"`. 글 만드는 코드는 `"draft"`, `"edited"`, `"approved"` 중 하나를 줄 수 있고, mock 예시에서는 늘 `"draft"` | 안 씀 (화면이 승인 여부를 따로 기억함) |
| `model` · `elapsed_ms` | 글을 쓴 모델 이름, 이 글에 걸린 시간 | 글 아래 작은 글씨 "HCX-005 · 2.5초" |
| `data_origin` | `"synthetic"` | 안 씀 |

**화면의 글 상태 규칙** (`app.js`의 `statusOf`, 시험이 지킴):

| 순서 | 조건 | 배지 글자 | 색 계열 |
|---|---|---|---|
| 1 | 이 글을 승인함 (화면이 기억) | 승인 완료 | ok |
| 2 | `failed_reasons`가 비어 있지 않음 | 점검 실패 | bad |
| 3 | `needs_input` 또는 `c7_flags`가 비어 있지 않음 | 확인 필요 | warn |
| 4 | 위에 모두 해당 없음 | 점검 통과 | ok |

`checks`의 점검 이름 (뜻은 `experiments/marketing/c6/checks.py`의 고칠 점 문장에서 가져옴):

| 이름 | 뜻 |
|---|---|
| `no_bad_number` | 메뉴판에 있는 가격만 썼는가 |
| `no_bad_promise` | 정책에 없는 보상 약속을 안 했는가 |
| `no_personal_info` | 고객 개인정보를 안 썼는가 |
| `not_too_similar` | 이전 답글과 너무 비슷하지 않은가 |
| `no_invented_measure` | 구체적 개선 조치를 지어내지 않았는가 |
| `chosen_measure_included` | 사장님이 고른 조치 문장이 들어갔는가 |
| `no_forbidden_phrase` | 쓰면 안 되는 표현이 없는가 |
| `uses_opening` · `uses_closing` | 시작 인사·마무리 인사를 넣었는가 |
| `not_quote_review` | 리뷰 원문을 그대로 베끼지 않았는가 |
| `no_coupon_invented` | 쿠폰 값(할인·코드·%)을 글이 지어내지 않았는가 |
| `no_stiff_words` | 딱딱한 표현이 없는가 |
| `no_overpromise` | 장담하거나 이미 끝난 일처럼 쓰지 않았는가 |
| `has_apology` | 첫 문장에 사과가 있는가 |
| `no_fewshot_copy` | 예시 문구를 베끼지 않았는가 |
| `no_unknown_menu` | 메뉴에 있는 음식 이름만 썼는가 |
| `no_markdown` | 마크다운 기호가 없는가 |
| `length_ok` | 글 길이가 범위 안인가 |
| `evidence_valid` | 근거 id가 모두 유효한가 (`c6/reply.py`) |
| `missing_mentioned` | 누락된 품목을 글이 언급했는가 (`c6/reply.py`) |

`length_ok`, `uses_opening`, `uses_closing`이 `false`여도 `failed_reasons`에 안 들어가므로 화면은 '점검 통과'로 봅니다 (글 만드는 코드가 다시 쓰기 사유에서 뺌).

**오류**

| 코드 | 언제 | 본문 |
|---|---|---|
| `404` | 카드 id가 지금 화면의 카드가 아님 | ① 모양 |
| `404` | mock에서 저장 예시가 이 카드에 안 맞음. 붙여넣기로 카드 ⓐ의 근거 리뷰가 늘어난 뒤에 생김 (저장 예시는 원래 리뷰 3건만 다룸) | ① 모양 |
| `400` | live인데 키가 없음 / live에서 모르는 `measures` id / 글 만들기 실패 | ① 모양 |
| `502` | live에서 HCX 호출 중 예상 못한 오류. 문장은 "글을 만들다가 문제가 생겼어요. 잠시 뒤 다시 눌러 주세요." HCX가 느리거나 실패해도 보통은 이 오류가 아니라 `200`으로 오고, 글에 `needs_input`(AI 호출 실패 안내)이 붙어 '확인 필요'로 보임. HCX 1회 호출은 30초 안에 끝나지 않으면 한 번만 다시 부름 | ① 모양 |
| `422` | `measures`가 목록이 아님 | ② 모양 |
| `503` | 리뷰 분석 서버 문제 | ① 모양 |

카드 id가 틀렸을 때 `404` (실제로 뽑음):

```json
{
  "error": {"message": "카드 card_nope 가 지금 화면의 카드가 아니에요. 새로 고침 하세요."}
}
```

붙여넣은 뒤 mock에서 카드 ⓐ를 만들 때 `404` (실제로 뽑음):

```json
{
  "error": {"message": "이 카드에 맞는 저장본이 없어요 (붙여넣기로 묶음이 바뀌었을 수 있어요). 키가 있으면 APP_MODE=live 로 생성하세요."}
}
```

키 없이 live로 띄우고 글을 만들 때 `400` (실제로 뽑음. 카드 ⓐ·ⓑ 모두 같은 문장):

```json
{
  "error": {"message": "HCX 키가 없어 실시간 생성을 할 수 없어요. APP_MODE=mock 으로 실행하세요."}
}
```

live에서 모르는 조치 id를 보낼 때 `400` (실제로 뽑음, 키 없는 live):

```json
{
  "error": {"message": "모르는 재발 방지 조치예요: M9"}
}
```

`measures`를 문자열로 보냈을 때 `422` (실제로 뽑음):

```json
{
  "detail": [
    {
      "type": "list_type",
      "loc": ["body", "measures"],
      "msg": "Input should be a valid list",
      "input": "M1"
    }
  ]
}
```

**참고**
- 화면은 서버가 준 글 순서(답글들, 공지)와 상관없이 **공지 → 홍보글 → 답글** 순서로 보여 줍니다 (`app.js`의 `GEN_ORDER`).
- 다시 만들면 그 카드의 예전 글과 승인 표시는 화면에서 버려집니다.
- 이 API는 글을 서버에 저장하지 않습니다. 화면(브라우저 메모리)에만 있습니다.

---

### 1.6 `POST /api/drafts/{draft_id}/approve`

**하는 일**: 사장님이 (고쳐서) 승인한 글을 서버에 기록합니다. 배달앱에 게시하지는 않습니다 (복사해서 직접 올림).
**쓰는 화면**: 초안 `#/draft`의 '승인' / '다시 승인' 버튼.

**요청**: `POST /api/drafts/{draft_id}/approve`

- `draft_id`: 글의 id. **어떤 문자열이든 받습니다.** 실제 글인지 확인하지 않습니다 (`d_x`로도 `200`, 확인함).
- 본문은 **필수**입니다 (`{}`도 됨). 본문이 없으면 `422`.

본문 예시 (1.5 카드 ⓐ 응답의 재발 방지 공지를 뒤에 "(고침)"만 붙여 승인하는 경우. 실제로 보낸 값):

```json
{
  "text": "안녕하세요 고객님 :) 주문이 잘못돼서 속상하셨죠? 진짜 죄송해요. 밥이랑 수저, 계란말이가 빠진 적이 몇 번 있었네요. 앞으론 주문서랑 꼼꼼히 비교해서 이런 실수 없게 할게요. 앞으로 포장 마감 전에 주문서와 한 번 더 대조할게요. 다음엔 요청 사항에 꼭 필요한 거 적어주시면 제가 특별히 더 잘 챙길게요! 온기한식 드림 (고침)",
  "original": "안녕하세요 고객님 :) 주문이 잘못돼서 속상하셨죠? 진짜 죄송해요. 밥이랑 수저, 계란말이가 빠진 적이 몇 번 있었네요. 앞으론 주문서랑 꼼꼼히 비교해서 이런 실수 없게 할게요. 앞으로 포장 마감 전에 주문서와 한 번 더 대조할게요. 다음엔 요청 사항에 꼭 필요한 거 적어주시면 제가 특별히 더 잘 챙길게요! 온기한식 드림"
}
```

| 칸 | 형식·범위 | 뜻 |
|---|---|---|
| `text` | 문자열 또는 `null` | 사장님이 고친 글. 안 고쳤으면 원문과 같은 글 |
| `original` | 문자열 또는 `null` | 생성된 원문 (`drafts[].text`) |
| `card_id` · `kind` | 문자열, 선택 | 어느 카드의 어떤 글인지. 안 보내면 서버가 ③ 에서 기억한 값 |
| `review_id` | 문자열, 선택 (11/15) | 리뷰 답글(`kind: "reply_draft"`)이 가리키는 리뷰(`drafts[].target_review_id`). 화면은 답글일 때만 `kind`와 함께 보냄 |

**답글 승인 기록 (11/15)**: 승인한 글이 리뷰 답글이면(서버가 ③ 에서 기억한 `generator`가 `reply_draft`, 서버가 모르는 초안이면 본문의 `kind`·`review_id`) 서버가 리뷰 분석 서비스의 `POST /reviews/{review_id}/status`에 `{"status": "replied", "reply_text": 승인한 글, "at": approved_at, "visitor_id": 방문자}`를 **따로** 보냅니다. 응대 점수·기한(1.11)이 이 기록으로 계산됩니다. 승인 응답은 이것을 기다리지 않고(스레드 2개, 2초 제한), 실패해도 승인은 그대로 성공하며 응답 모양도 같습니다(서버 로그에만 남음). 형식이 틀린 `review_id`는 무시합니다.

- 길이 제한은 코드에 없습니다.
- `edited`(고쳤는지)는 `text`와 `original`이 **둘 다 `null`이 아니고**, 앞뒤 공백을 뺀 두 글이 다를 때만 `true`입니다.
- 기록되는 글은 `text`가 `null`이 아니면 `text`, 아니면 `original`입니다.
- 같은 `draft_id`를 다시 승인하면 서버 메모리의 기록은 그 글의 것으로 바뀌고 목록 맨 뒤로 갑니다. 파일에는 한 줄이 더 붙습니다 (3.1).

**응답 `200`** (줄이지 않음. 글을 고쳐서 승인한 경우):

```json
{
  "draft_id": "d_af7e466a",
  "status": "approved",
  "edited": true,
  "text": "안녕하세요 고객님 :) 주문이 잘못돼서 속상하셨죠? 진짜 죄송해요. 밥이랑 수저, 계란말이가 빠진 적이 몇 번 있었네요. 앞으론 주문서랑 꼼꼼히 비교해서 이런 실수 없게 할게요. 앞으로 포장 마감 전에 주문서와 한 번 더 대조할게요. 다음엔 요청 사항에 꼭 필요한 거 적어주시면 제가 특별히 더 잘 챙길게요! 온기한식 드림 (고침)",
  "approved_at": "2026-11-14T19:37:15+09:00",
  "mode": "mock"
}
```

| 칸 | 뜻 | 화면 |
|---|---|---|
| `draft_id` | 승인한 글 id | 안 씀 (화면은 요청한 id를 앎) |
| `status` | 늘 `"approved"` | 안 씀 |
| `edited` | 사장님이 고쳤는지 | 글의 `edited_text` 채움, 처리 완료의 "사장님이 고침" |
| `text` | 기록된 글 | 안 씀 |
| `approved_at` | 승인 시각 (한국 시간) | 처리 완료 목록의 시각 |
| `mode` | 승인할 때의 서버 모드 (`"mock"`/`"live"`) | 안 씀 |
| `warning` | 승인 기록 파일에 못 썼을 때만 있음 | **안 씀** (화면이 아직 보여 주지 않음) |

승인 기록 파일에 못 썼을 때 (실제로 뽑음. 폴더를 만들 수 없게 해 둔 시험 설정):

```json
{
  "draft_id": "d_x",
  "status": "approved",
  "edited": true,
  "text": "a",
  "approved_at": "2026-11-14T19:37:16+09:00",
  "mode": "mock",
  "warning": "승인 기록 파일을 쓰지 못했어요 (화면 기록만 남음)"
}
```

**오류**

- `422`: 본문이 없음, 또는 `text`·`original`이 문자열이 아님.

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body"],
      "msg": "Field required",
      "input": null
    }
  ]
}
```

**참고**: 이 API는 리뷰 분석 서버를 부르지 않아서, 그 서버가 꺼져 있어도 `200`입니다 (확인함).

---

### 1.7 `GET /api/approvals`

**하는 일**: 서버 메모리에 있는 승인 기록을 줍니다.
**쓰는 화면**: 처리 완료 `#/done`의 '서버 처리 기록'(접어 둔 목록). 완료 화면을 열 때 부릅니다.

**요청**: `GET /api/approvals`. 본문 없음.

**응답 `200`** (줄이지 않음. 글 두 건을 승인한 뒤의 목록. 답글 하나는 그대로, 재발 방지 공지 하나는 고쳐서 승인한 경우):

```json
{
  "items": [
    {
      "draft_id": "d_d368820d",
      "status": "approved",
      "edited": false,
      "text": "안녕하세요 고객님 :) 공깃밥 추가로 보내드렸어요. 포장 마감 전 주문서를 다시 한번 확인하는 절차를 도입해서 이런 일이 다시 없도록 주의하겠습니다. 소중한 의견 감사합니다. 온기한식 드림",
      "approved_at": "2026-11-14T19:37:15+09:00",
      "mode": "mock"
    },
    {
      "draft_id": "d_af7e466a",
      "status": "approved",
      "edited": true,
      "text": "안녕하세요 고객님 :) 주문이 잘못돼서 속상하셨죠? 진짜 죄송해요. 밥이랑 수저, 계란말이가 빠진 적이 몇 번 있었네요. 앞으론 주문서랑 꼼꼼히 비교해서 이런 실수 없게 할게요. 앞으로 포장 마감 전에 주문서와 한 번 더 대조할게요. 다음엔 요청 사항에 꼭 필요한 거 적어주시면 제가 특별히 더 잘 챙길게요! 온기한식 드림 (고침)",
      "approved_at": "2026-11-14T19:37:15+09:00",
      "mode": "mock"
    }
  ]
}
```

| 칸 | 뜻 | 화면 |
|---|---|---|
| `items[]` | 승인 기록 목록 (승인한 순서. 같은 글을 다시 승인하면 그 글이 맨 뒤로) | '서버 처리 기록' |
| `items[].draft_id` · `edited` · `approved_at` | 글 id, 고쳤는지, 승인 시각 | "HH:MM:SS · d_… 승인 (사장님이 고침)" |
| `items[].status` · `text` · `mode` · `warning` | `1.6` 응답과 같음 | 안 씀 |

**오류**: 없음 (기록이 없으면 `{"items": []}`).

**참고**
- 이 목록은 **서버 메모리**입니다. 서버를 다시 켜면 비어 있습니다. 파일(`approvals.jsonl`)에 남은 줄을 다시 읽지 않습니다 (3.1).
- 방문자를 구분하지 않으므로 모든 방문자의 승인이 한 목록에 섞입니다.

---

### 1.8 `POST /api/reviews`

**하는 일**: 사장님이 붙여넣은 리뷰 한 건을 리뷰 분석 서버에 넘겨 저장하고 바로 분류합니다. 전화번호·이메일·링크는 저장 전에 `[가림]`으로 바꿉니다. 응답은 **리뷰 분석 서버의 응답을 그대로** 전달합니다 (비서 화면 서버가 가공하지 않음).
**쓰는 화면**: 리뷰 분석 `#/analysis`의 '리뷰 붙여넣기' 탭 '분류하기' 버튼. 성공하면 화면이 홈 숫자·추천 카드·요약·불만 묶음을 다시 불러옵니다 (`briefing`, `cards`, `insight`).

**요청**: `POST /api/reviews`

```json
{"text": "포장이 허술해서 국물이 새고 반찬이 하나 빠졌어요. 연락은 010-0000-0000 으로 주세요", "rating": 2}
```

| 칸 | 형식·범위 | 뜻 |
|---|---|---|
| `text` | 문자열, **1~1000자**, 필수 | 리뷰 글 |
| `rating` | 정수 1~5, 생략·`null` 가능 | 별점. 모르면 비움 |
| `channel` | `"baemin"`, `"coupangeats"`, `"yogiyo"`, `"naver_place"` 중 하나, 생략·`null` 가능 | 배달앱. **지금 화면은 보내지 않음** |
| `source` | `"paste"` 또는 `"capture"`, 생략·`null` 가능 (11/15) | `capture` = '캡처로 넣기' 후보를 사장님이 확인·수정해 저장한 것. 리뷰 분석 서비스는 계약대로 `input_method: "paste"`로 저장하고 `source` 칸만 다름. 그 밖의 값은 `422`. 생략하면 예전과 똑같이 보냄 |

> **글자 수는 1~1000자입니다.** 비서 화면 서버, 리뷰 분석 서버, 화면 입력칸(`textarea`의 `maxlength="1000"`)이 모두 1000자입니다. 1001자 이상이나 빈 글은 `422`가 옵니다. 11/14 이전에는 비서 화면 서버만 4000자를 통과시켜 1001~4000자가 `503`으로 왔는데, main `d7c1305`에서 고쳤습니다.

**응답 `201`** (줄임: `groups`는 3개 중 1개, `repeated_issues`는 1개 중 1개를 줄여서, `single_complaints`는 5개 중 1개만 남김):

```json
{
  "review": {
    "review_id": "rv_ongi_paste_001",
    "store_id": "store_ongi",
    "channel": null,
    "rating": 2,
    "text": "포장이 허술해서 국물이 새고 반찬이 하나 빠졌어요. 연락은 [가림] 으로 주세요",
    "created_at": "2026-11-08T23:00:00+09:00",
    "input_method": "paste",
    "pii_masked": true,
    "order_ref": null,
    "status": "analyzed",
    "data_origin": "synthetic"
  },
  "classification": {
    "review_id": "rv_ongi_paste_001",
    "sentiment": "negative",
    "topics": [
      {"topic": "packaging", "polarity": "negative", "evidence": "포장이 허술해서 국물이 새고 반찬이 하나 빠졌어요"},
      {
        "topic": "missing_item",
        "polarity": "negative",
        "evidence": "포장이 허술해서 국물이 새고 반찬이 하나 빠졌어요"
      }
    ],
    "summary": null,
    "method": "rule",
    "model": "kiwi",
    "warnings": [],
    "negative_topics": ["missing_item", "packaging"]
  },
  "joined_issues": ["iss_missing_item"],
  "review_count": 41,
  "complaint_count": 13,
  "groups": [
    {
      "issue_id": "iss_missing_item",
      "topics": ["missing_item"],
      "topic": "missing_item",
      "topic_name": "포장 누락",
      "review_count": 4,
      "is_repeated": true,
      "review_ids": ["rv_ongi_001", "rv_ongi_002", "rv_ongi_003", "rv_ongi_paste_001"],
      "evidence": [
        {"review_id": "rv_ongi_001", "quote": "안 들어 있었어요"},
        {"review_id": "rv_ongi_002", "quote": "수저랑 젓가락이 빠져 있었어요"},
        {"review_id": "rv_ongi_003", "quote": "누락됐어요"},
        {"review_id": "rv_ongi_paste_001", "quote": "포장이 허술해서 국물이 새고 반찬이 하나 빠졌어요"}
      ],
      "time_bands": {"00~06시": 0, "06~11시": 0, "11~14시": 0, "14~17시": 0, "17~21시": 3, "21~24시": 1},
      "main_time_band": "17~21시",
      "channels": {"baemin": 1, "coupangeats": 1, "yogiyo": 1, "unknown": 1},
      "recent_count": 4,
      "previous_count": 0,
      "first_at": "2026-10-27T19:30:00+09:00",
      "last_at": "2026-11-08T23:00:00+09:00"
    }
  ],
  "repeated_issues": [
    {
      "issue_id": "iss_missing_item",
      "topics": ["missing_item"],
      "topic": "missing_item",
      "topic_name": "포장 누락",
      "review_count": 4,
      "is_repeated": true,
      "review_ids": ["rv_ongi_001", "rv_ongi_002", "rv_ongi_003", "rv_ongi_paste_001"],
      "evidence": [
        {"review_id": "rv_ongi_001", "quote": "안 들어 있었어요"},
        {"review_id": "rv_ongi_002", "quote": "수저랑 젓가락이 빠져 있었어요"},
        {"review_id": "rv_ongi_003", "quote": "누락됐어요"},
        {"review_id": "rv_ongi_paste_001", "quote": "포장이 허술해서 국물이 새고 반찬이 하나 빠졌어요"}
      ],
      "time_bands": {"00~06시": 0, "06~11시": 0, "11~14시": 0, "14~17시": 0, "17~21시": 3, "21~24시": 1},
      "main_time_band": "17~21시",
      "channels": {"baemin": 1, "coupangeats": 1, "yogiyo": 1, "unknown": 1},
      "recent_count": 4,
      "previous_count": 0,
      "first_at": "2026-10-27T19:30:00+09:00",
      "last_at": "2026-11-08T23:00:00+09:00"
    }
  ],
  "single_complaints": [
    {
      "review_id": "rv_ongi_008",
      "topics": ["hygiene"],
      "topic_names": ["위생"],
      "quote": "반찬 그릇에 머리카락이 있었어요",
      "created_at": "2026-10-21T12:40:00+09:00",
      "channel": "naver_place"
    }
  ],
  "top_issue_id": "iss_missing_item"
}
```

| 칸 | 뜻 | 화면 |
|---|---|---|
| `review` | 저장된 리뷰 (`ReviewRecord` 모양) | '분류 결과' 패널 |
| `review.review_id` | 새 id. `rv_(가게)_paste_(번호 3자리)` | 패널 제목 줄 |
| `review.text` | 저장된 글. 개인정보는 `[가림]`으로 바뀜 | 패널 본문 |
| `review.pii_masked` | 가린 곳이 있으면 `true` | "개인정보 가림" 표시 |
| `review.created_at` | **시험용 시각**: 합성 리뷰의 마지막 날 밤 11시부터 한 건마다 1분씩 늦춤. 실제 시각이 아님 (리뷰 분석 서버의 `REVIEW_PASTE_REAL_TIME=1`이면 실제 시각) | 안 씀 |
| `review.store_id` | 가게 id | 안 씀 |
| `review.channel` · `rating` | 보낸 값 (안 보냈으면 `null`) | 안 씀 |
| `review.input_method` | `"paste"` | 안 씀 |
| `review.order_ref` · `status` · `data_origin` | 주문 연결(늘 `null`), 상태(`"analyzed"`), `"synthetic"` | 안 씀 |
| `classification.review_id` | 분류한 리뷰 id | 안 씀 |
| `classification.sentiment` | 감정 (`positive`·`negative`·`neutral`·`mixed`) | "감정 부정" |
| `classification.topics[]` | 찾은 주제 `{topic, polarity, evidence}`. `polarity`는 `"positive"`/`"negative"`, `evidence`는 근거 글귀 | 주제 칩 ("불만 · 포장 누락 “…”") |
| `classification.negative_topics` | 불만으로 잡힌 주제 id 목록 | 묶음에 들었는지 안내 문장 |
| `classification.method` | 분류 방식 (예시: `"rule"` = 규칙 분류) | "분류 방식 rule" |
| `classification.model` | 분류에 쓴 도구 이름 (예시: `"kiwi"`) | 안 씀 |
| `classification.summary` · `warnings` | 요약(예시는 `null`), 검증 경고 문장 목록 | `warnings`가 있으면 "검증: …" |
| `joined_issues` | 이 리뷰가 들어간 묶음 id 목록. 없으면 `[]` | "불만 묶음에 들어갔어요: 포장 누락" |
| `review_count` · `complaint_count` | 붙여넣은 뒤 전체 리뷰·불만 수 | 안 씀 (화면이 `insight`를 다시 불러옴) |
| `groups[]` | 붙여넣은 뒤의 불만 묶음. 칸은 `issue_id`, `topics`, `topic`, `topic_name`, `review_count`, `is_repeated`, `review_ids`, `evidence`, `time_bands`, `main_time_band`, `channels`, `recent_count`, `previous_count`, `first_at`, `last_at`로 `1.3`의 `groups[]` 표와 뜻이 같음 | 묶음 `issue_id` → `topic_name` 찾기 |
| `repeated_issues[]` | `groups` 중 반복(`is_repeated`)인 것만. 칸은 `groups[]`와 같음 | 안 씀 |
| `single_complaints[]` | 묶이지 않은 불만. 칸은 `review_id`, `topics`, `topic_names`, `quote`, `created_at`, `channel` (`1.3`과 같음) | 안 씀 |
| `top_issue_id` | 핵심(가장 큰 반복) 묶음 id | 안 씀 |

**오류**

| 코드 | 언제 | 본문 |
|---|---|---|
| `422` | `text`가 없음 / 비어 있음 / 1000자 초과, `rating`이 1~5 정수가 아님 | ② 모양 |
| `503` | 리뷰 분석 서버가 꺼짐 | ① 모양 (1.2의 `503` 예시와 같음) |
| `503` | 리뷰 분석 서버가 입력을 거절함: 공백만 있는 글, 틀린 `channel` | ① 모양. 문장은 "리뷰 분석 서비스 오류 400: …" |

`text`가 비었을 때 `422` (실제로 뽑음. 화면은 이 경우 서버를 부르기 전에 "리뷰 글을 넣어 주세요."로 막음):

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "text"],
      "msg": "String should have at least 1 character",
      "input": "",
      "ctx": {"min_length": 1}
    }
  ]
}
```

1001자를 보냈을 때 `422` (main `d7c1305`에서 실제로 뽑음. 예시의 `input`은 줄였음):

```json
{
  "detail": [
    {
      "type": "string_too_long",
      "loc": [
        "body",
        "text"
      ],
      "msg": "String should have at most 1000 characters",
      "input": "가가가… (1001자, 줄임)",
      "ctx": {
        "max_length": 1000
      }
    }
  ]
}
```

**참고**
- 붙여넣은 리뷰가 카드 ⓐ가 가리키는 묶음에 들어가면 카드 ⓐ의 근거 리뷰가 늘어납니다. mock에서는 저장된 예시 글이 원래 리뷰 3건만 다뤄서, 그 뒤 카드 ⓐ로 글 만들기가 `404`가 됩니다 (1.5).
- 사용자가 잘못 입력한 경우(공백만 있는 글, 틀린 `channel`)가 `422`가 아니라 `503`으로 오는 것은 알려진 특이점입니다. 화면은 `error.message`를 그대로 보여 줍니다.

---

### 1.9 `DELETE /api/reviews/pasted`

**하는 일**: 이 가게에 붙여넣은 리뷰를 **모두** 지웁니다 (합성 리뷰는 그대로). 데모를 다시 할 때 씁니다.
**쓰는 화면**: 리뷰 분석 '리뷰 붙여넣기' 탭의 '붙여넣은 리뷰 지우기' 버튼. 성공하면 홈 숫자·추천 카드·요약·불만 묶음을 다시 불러옵니다.

**요청**: `DELETE /api/reviews/pasted`. 본문·검색어 없음.

**응답 `200`**:

```json
{"deleted": 3}
```

| 칸 | 뜻 | 화면 |
|---|---|---|
| `deleted` | 지운 리뷰 수. 지울 것이 없으면 `0` | "붙여넣은 리뷰 n건을 지웠어요." |

**오류**: `503` 리뷰 분석 서버 문제 (모양은 1.2의 `503` 예시와 같음). 지울 것이 없어도 오류가 아니라 `{"deleted": 0}`입니다.

**참고**: 리뷰 분석 서버의 디스크 파일을 비웁니다 (3.1). 누가 붙였는지 구분하지 않으므로, 이 서버를 같이 쓰는 모든 사람이 붙인 리뷰가 지워집니다.

---

### 1.10 `/api/assistant/*` — 상권 채팅 서랍 (상권 서비스 프록시)

**쓰는 화면**: 오른쪽 "AI에게 묻기" 서랍. 비서 화면 서버가 상권 서비스(`ic26-market`, `127.0.0.1:8766`)를 **대신 불러 주는** API입니다. 브라우저는 상권 서비스에 직접 가지 않습니다. 이 절의 숫자는 상권 서비스 시험용 **합성 자료**에서 뽑은 예시입니다(실제 상권 숫자가 아님).

| 메서드 · 경로 | 하는 일 | 실패하면 |
|---|---|---|
| `GET /api/assistant/status` | 상권 비서를 쓸 수 있는지 | 항상 `200` (`state`로 알림) |
| `POST /api/assistant/setup` | 우리 가게(온기한식) 분석 조건을 자동으로 맞춤. `?force=1`이면 다른 곳을 보고 있어도 우리 가게 조건으로 되돌림 | 항상 `200` |
| `POST /api/assistant/messages` | 질문 1개 → 답, 근거 카드, 선택지 | `503`·`422` |
| `POST /api/assistant/actions` | 선택지 버튼을 눌렀을 때 (직전 답의 `reply.actions[i].payload`를 그대로) | `503`·`422` |
| `GET /api/assistant/conversation` | 이 세션의 대화와 분석 조건 | `503` |
| `DELETE /api/assistant/conversation` | 대화 지우기 (분석 조건은 남음) | `503` |

개발용 내보내기(`conversation.md`)와 상권 온보딩 API(`/api/onboarding/*`)는 열지 않습니다.

**`status` 응답 `200`**

```json
{"state": "ready", "message": null, "model_connected": true, "planner_connected": false,
 "setup": {"label": "온기한식 · 장승배기역 · 한식음식점"}}
```

| `state` | 뜻 | 화면에 보일 안내 (`message`) |
|---|---|---|
| `ready` | 쓸 수 있음 | 없음 (`null`) |
| `off` | 이 서버에서 상권 비서를 안 켜 둠 (`MARKET_URL=off`) | 이 서버에서는 상권 비서를 켜 두지 않았어요. |
| `down` | 상권 서비스에 연결하지 못함 (꺼져 있음) | 상권 서비스에 연결하지 못했어요. 잠시 뒤 다시 확인해 주세요. |
| `disabled` | 상권 서비스는 떴는데 챗봇이 꺼져 있음 (`ASSISTANT_ENABLED` 없음) | 상권 서비스는 켜져 있지만 상권 비서(챗봇)가 꺼져 있어요. |
| `no_data` | 공식 상권 자료가 아직 없음 | 공식 상권 자료가 아직 준비되지 않았어요. 자료가 들어오면 바로 쓸 수 있어요. |
| `error` | 그 밖의 문제 (제한 시간 초과, 접속 주소 설정 오류, 몰림 등) | 문장은 원인마다 다름 |

`no_data`는 `status`가 아니라 `setup`이 알립니다(자료가 있는지는 분석 조건을 맞춰 봐야 압니다). `model_connected`·`planner_connected`는 상권 서비스가 실시간 HCX를 쓰는지(`APP_MODE=live`)이고, `ready`일 때만 있습니다. `setup.label`은 기본 조건이 있는 가게에서만 글자이고 없으면 `null`입니다.

**`setup` 응답 `200`**

```json
{"status": "ok", "state": "ready", "message": null,
 "conditions": {"area_code": "3110826", "area_name": "장승배기역 4번", "industry_code": "CS100001",
                "industry_name": "한식음식점", "period": "20262", "period_label": "2026년 2분기", "location_label": "장승배기역"}}
```

| `status` | 뜻 |
|---|---|
| `ok` | 조건을 새로 맞춤 (`conditions`에 결과) |
| `already` | 이미 조건이 있거나, 사용자가 다른 위치·업종을 고르는 중이라 건드리지 않음 (`force` 없을 때). 기본 조건이 없는 가게도 `already`이고 `conditions`는 `null` |
| `unavailable` | 맞추지 못함. `state`와 `message`로 이유(`down`, `disabled`, `no_data`, `error` 등) |

우리 가게 기본 조건은 `온기한식` = 장승배기역(7호선) · 한식음식점(`CS100001`) · 장승배기역 4번 상권(`3110826`) · 가장 최근 분기(2026년 2분기가 있으면 그것). 위치는 역 코드로 저장하므로 서울시 지도(Naver) 검색을 부르지 않습니다. 서랍을 처음 열 때 화면이 한 번 부르면, 사용자가 "어디를 볼까요?"를 다시 묻지 않고 바로 질문할 수 있습니다.

**`messages` 요청** `{"text": "1~1000자", "client_message_id": "web-…"}` (두 번째 칸은 선택. 같은 번호로 다시 보내면 지난 답을 돌려줌)

**`messages`·`actions` 응답 `200`** (줄임)

```json
{"reply": {"kind": "data_answer",
           "text": "장승배기역 4번 상권의 한식음식점 업종을 2026년 2분기 자료로 볼게요. [F1]\n분기 추정매출은 1,000원이에요. [F2]",
           "actions": [], "notes": ["상권·업종의 분기 추정매출이며 개별 가게의 실제 매출이나 특정 월 매출이 아닙니다."],
           "suggestions": ["주말 매출은?", "점심·저녁 중 언제 잘 팔려?", "어느 연령대가 많이 사?"]},
 "cards": [{"id": "F2", "topic": "sales_total", "status": "available", "text": "분기 추정매출은 1,000원입니다.",
            "values": [{"label": "분기 추정매출", "value": 1000, "unit": "원"}], "warnings": [],
            "source_ref": {"source_title": "합성 추정매출", "source_url": "https://example.test/s", "data_version": "b2_synthetic"}}],
 "conditions": {"area_name": "장승배기역 4번", "industry_name": "한식음식점", "period_label": "2026년 2분기"}}
```

| 칸 | 뜻 |
|---|---|
| `reply.kind` | 답의 종류 (`data_answer`, `choose_location`, `need_location`, `period_unavailable`, `data_unavailable` 등). 화면은 모양 구분에 쓰지 않아도 됨 |
| `reply.text` | 여러 줄. `- `로 시작하는 줄은 목록, `참고:`·`해석:`·`다음으로 `로 시작하는 줄은 특별 줄. `[F1]`은 근거 카드 번호 |
| `reply.actions[]` | 선택지 `{label, payload}`. 누르면 `payload`를 `POST /api/assistant/actions`에 그대로 보냄. 없을 수 있음 |
| `reply.notes[]` · `reply.suggestions[]` | 자료 기준 안내 · 이어서 물어볼 질문(최대 3개). 없을 수 있음 |
| `cards[]` | 근거 카드. `values[]` 중 숫자인 것만 표로 보임. 출처는 `source_ref` |
| `conditions` | 지금 분석 조건. 없을 수 있음 |

**오류 모양** (이 절의 모든 API 공통)

```json
{"error": {"message": "상권 서비스에 연결하지 못했어요. 잠시 뒤 다시 확인해 주세요.", "state": "down"}}
```

| 상태 코드 | `state` | 언제 |
|---|---|---|
| `503` | `down` · `disabled` · `no_data` · `error` | 상권 서비스 문제. 비서 화면의 다른 API는 아무 영향이 없음 |
| `422` | `invalid` | 입력 문제 (빈 질문, 1000자 초과, 모르는 선택지 종류) |

이 절의 API는 **어떤 경우에도 `500`을 주지 않습니다.** 서랍 안에서만 안내를 보이고 비서 화면의 알림 띠(`#alert`)는 쓰지 않습니다.

**세션 쿠키**: 상권 서비스는 대화와 분석 조건을 세션(`market_onboarding_session`, 30일)에 붙입니다. 서버가 그 값을 쿠키(`HttpOnly`, 경로 `/api/assistant`)로 심고 다음 요청에 상권 서비스로 넘깁니다. 화면(JS)이 다룰 것은 없습니다(`credentials: "same-origin"`만). 상권 서비스는 Host가 `127.0.0.1`·`localhost`가 아니거나 `Origin`이 있으면 막기 때문에, 서버가 `Host: 127.0.0.1:8766`을 직접 싣고 `Origin`은 넘기지 않습니다. 서버가 두 대이면 상권 서비스의 세션 저장소(SQLite)도 서버마다 따로라서, 로드 밸런서가 방문자를 다른 서버로 보내면 대화가 이어지지 않습니다(분석 조건은 서랍이 다시 열릴 때 `setup`으로 다시 맞춤).

**답이 느릴 수 있습니다**: 실시간 모드에서 보통 2~8초, 가끔 더 걸립니다. 서버는 75초(`MARKET_TIMEOUT_SEC`)까지 기다립니다. 질문이 몰리면(동시 8개 초과) `503` "질문이 몰려 있어요"가 옵니다.

---

### 1.11 `/api/care/*` — 캡처 입력·응대 점수·보고서 (리뷰 분석 서비스의 고객응대 프록시)

**쓰는 화면**: 리뷰 분석 '리뷰 붙여넣기' 탭의 '캡처로 넣기'와 왼쪽 메뉴 '종합 리포트'(`#/report`). 비서 화면 서버가 리뷰 분석 서비스(`127.0.0.1:8020`, `/api/review-insight/*`)의 고객응대 API를 **대신 불러 주는** 길입니다 (`services/web/web/care_proxy.py`). 브라우저는 8020에 가지 않고, 화면 파일에는 `/api/care`만 씁니다 (2.4 시험 2).

| 메서드 · 경로 | 서비스 경로 | 하는 일 | 실패하면 |
|---|---|---|---|
| `GET /api/care/status` | `/api/health` | 고객응대를 쓸 수 있는지 (`ready`·`off`·`down`·`error`) | 항상 `200` |
| `POST /api/care/reviews/capture` | `…/reviews/capture` | 리뷰 화면 캡처 1장(multipart `file`, png·jpg·webp) → 리뷰 후보. **저장하지 않음** | `400`·`413`·`422`·`502`·`503` |
| `POST /api/care/reviews/{review_id}/status` | `…/reviews/{id}/status` | 리뷰 상태·답글 기록 (`{"status", "reply_text", "at"}`) | `400`·`404`·`503` |
| `GET /api/care/response` | `…/response` | 응대 점수(0~100)·이유·답글 기다리는 불만의 기한 | `503` |
| `GET /api/care/report/daily?date=` | `…/report/daily` | 일일 요약 (비우면 오늘, 한국 날짜) | `400`·`503` |
| `GET /api/care/report/monthly?month=` | `…/report/monthly` | 월간 보고서 (비우면 이번 달) | `400`·`503` |
| `GET /api/care/report/monthly/print?month=` | `…/report/monthly/print` | 월간 보고서 인쇄용 A4 **HTML** (화면의 '인쇄용 보기'가 새 탭으로 엶) | `400`·`503` |

- **이 표 밖은 모두 `404`** (`{"error": {"state": "not_found"}}`, 서비스에 보내지 않음). 가게 정보(`/profile*`)는 가게 공용이라 아무 방문자나 고치거나 지울 수 있어서(임시 공지 101개면 저장본이 깨지는 알려진 버그도 있음) 열지 않았고, 문의(`/inquiries*`)·받은함(`/inbox`)·약속 장부(`/promises`)·다국어 메뉴판(`/menu/foreign*`)은 이 화면이 아직 쓰지 않습니다. 리뷰 목록·`insight`·붙여넣기 지우기는 1.3·1.8·1.9가 맡습니다.
- **손님용 문의 페이지 `/s/{가게}`와 `/api/care/public/*`는 기본으로 없습니다.** `CARE_PUBLIC=1`일 때만 붙고(우리 가게 하나만), 손님 주소는 Nginx가 넣는 `X-Real-IP`(없으면 접속한 쪽)를 씁니다. 보안 검토 전까지 켜지 않습니다.
- **캡처 후보의 저장은 1.8 `POST /api/reviews`에 `"source": "capture"`** 를 붙여 한 건씩 합니다. 그래서 붙여넣은 리뷰와 똑같이 이 방문자의 요약·불만 묶음·홈 숫자·추천 카드에 들어갑니다.
- 서버가 `store_id`는 `DEMO_STORE_ID`, `visitor_id`는 방문자 쿠키로 **덮어씁니다** (쿼리·JSON 본문. 캡처 업로드는 쿼리). 쿼리는 `date`·`month`·`now`만 넘기고, 리뷰 분석 서비스의 토큰(`REVIEW_INSIGHT_TOKEN`)은 서버가 붙입니다.
- 본문 상한: JSON 64KB, 캡처 업로드 12MB → 넘으면 `413` (`state: "too_big"`). 리뷰 분석 서비스 자체 상한은 10MB(넘으면 `400`). Nginx는 캡처 경로만 12MB(배포 README 9절).
- 서비스 호출은 서버 스레드에서 돌아서 캡처가 20초 걸려도 다른 API는 기다리지 않습니다 (시험으로 확인). 캡처는 100초(`CARE_TIMEOUT_SEC`), 그 밖은 15초까지 기다립니다.

**`capture` 응답 `200`** (시험용 실행, 이미지를 읽지 않은 예시)

```json
{"candidates": [{"text": "제육볶음 양이 넉넉하고 맛있어요. 또 시킬게요!", "rating": 5, "pii_masked": false, "duplicate": false},
                {"text": "공깃밥이 또 빠져 있었어요. 다음엔 꼭 챙겨 주세요", "rating": 2, "pii_masked": false, "duplicate": false}],
 "count": 2, "demo": true, "pieces": 1, "warnings": ["예시 결과입니다. 키가 없거나 APP_MODE=mock 이라 이미지를 실제로 읽지 않았습니다"],
 "engine": "demo", "next": "…"}
```

| 칸 | 화면 |
|---|---|
| `candidates[].text` · `rating` | 고칠 수 있는 글 칸과 별점 고르기 (못 읽은 별점은 `null` → "별점 모름") |
| `pii_masked` · `duplicate` | "개인정보 가림" · "이미 있는 리뷰" 표시. `duplicate`면 처음에 고르지 않음 |
| `demo` | `true`면 "예시 결과 — 이미지를 실제로 읽지 않았어요"를 꼭 보임 |
| `warnings[]` · `pieces` | 받은 문장 그대로 목록으로. 조각 수는 진행 안내 줄에 |

화면은 별점을 잘못 읽을 수 있다는 안내를 늘 붙입니다 (실시간 시험에서 1~2점 리뷰를 3점으로 읽은 적이 절반쯤).

**`response` 응답 `200`** (줄임): `{"score": 91, "reasons": [{"delta": -2, "message": "'포장 누락' 불만이 3건 반복 중", …}], "pending": [{"review_id", "text", "topic_names", "source", "due_at", "remaining_seconds", "overdue", "paused", "penalty"}], "pending_count", "overdue_count", "untimed_unanswered": 12, "peak_now": false, "policy": {"sla_minutes": 30, "peak_hours": ["11-14", "17-21"]}}`. 화면은 `reasons[].message`를 그대로 보이고, 남은 시간은 `due_at`으로 1초마다 셉니다(브라우저 시계 차이는 `remaining_seconds`로 맞춤). `paused`이거나 `peak_now`면 "멈춤", `untimed_unanswered`는 "지난 불만 n건".

**`report/daily`** 화면이 쓰는 칸: `summary`, `review_count`, `complaint_count`, `replied_on_time`, `replied_late`, `score_start`→`score_end`, `score_change`, `changes[]`(`delta`, `message`), `todo.text`, `by_source`, `pending_count`, `overdue_count`. **`report/monthly`**: `month`, `review_count`, `complaint_count`, `score_start`→`score_end`, `late_count`, `score_trend[]`(`date`, `score`, 화면이 SVG 선 그래프로), `repeated_issues[]`(`topic_name`, `review_count`, `count_this_month`, `replied_count`, `recurred_after_reply`, `state`, `main_time_band`, `is_repeated`), `suggestions[].text`, `changes[]`. 숫자는 리뷰 분석 서비스가 규칙으로 계산하고 문장은 틀 문장입니다 (`summary_method: "template"`, AI 문장 아님).

**오류 모양**

```json
{"error": {"message": "리뷰 분석 서비스에 연결하지 못했어요. 잠시 뒤 다시 확인해 주세요.", "state": "down"}}
```

| 상태 코드 | `state` | 언제 |
|---|---|---|
| `503` | `off` · `down` · `slow` · `busy` · `error` | 이 서버에서 꺼 둠(`CARE_URL=off`) · 연결 못 함 · 너무 오래 걸림 · 동시 요청 8개 초과 · 그 밖 (서비스의 `500`·이상한 응답·토큰 거절·우리 쪽 버그도 여기) |
| `413` | `too_big` | 본문 상한 초과 |
| `404` | `not_found` | 허용 목록 밖, 또는 서비스의 `REVIEW_NOT_FOUND` |
| `422` | `invalid` | 캡처 본문이 multipart가 아님, JSON이 아님 / 서비스의 `CAPTURE_UNREADABLE`(리뷰를 못 찾음) |
| `400` · `502` | `invalid` · `upstream` | 서비스가 준 오류: 형식·크기·너무 긴 캡처(`CAPTURE_TOO_LONG`) · AI 호출 실패(`LLM_*`, 다시 하면 됨) |

서비스가 준 오류는 본문(`code`, `message`, `retryable`, …)을 그대로 두고 `state`만 더합니다. 화면은 `error.message`를 그 칸 안에만 보이고 맨 위 알림 띠(`#alert`)는 쓰지 않습니다. **이 절의 API는 `500`을 주지 않으며, 리뷰 분석 서비스가 꺼져 있어도 비서 화면의 다른 API(1.1~1.9)는 그대로입니다** (단, 1.2~1.5·1.8·1.9는 원래 같은 리뷰 분석 서비스를 쓰므로 그 서비스 자체가 꺼지면 그쪽은 0.1절대로 `503`).

**인쇄용 페이지**는 이 서버 주소에서 열리므로 `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; …`와 `X-Content-Type-Options: nosniff`를 붙여 줍니다 (스크립트·외부 주소 막음).

---

## 2부. 화면을 다듬을 때 유지해야 하는 것

### 2.1 파일 세 개와 정적 파일 경로

| 파일 | 서버가 주는 주소 | 하는 일 |
|---|---|---|
| `services/web/web/static/index.html` | `/` | 화면의 뼈대. 화면 6개(홈·추천 카드·초안·완료·리뷰 분석·종합 리포트)와 서랍, 바닥 |
| `services/web/web/static/style.css` | `/static/style.css` | 모든 모양 |
| `services/web/web/static/app.js` | `/static/app.js` | 모든 동작. API 호출, 화면 그리기, 화면 전환 |

- `index.html`은 `<link rel="stylesheet" href="/static/style.css">`와 (`<body>` 맨 끝) `<script src="/static/app.js"></script>`로 두 파일을 부릅니다. 주소가 **`/`로 시작하는 절대 경로**입니다.
- `/static/` 아래에는 `static` 폴더 안의 어떤 파일이든 줍니다 (`/static/nope.js`는 `404`). 이미지·글꼴을 더하면 이 폴더 안에 두고 `/static/파일이름`으로 부릅니다.
- `app.js`의 API 주소도 `/api/…` 절대 경로입니다. 화면과 API는 같은 주소에서 받는 것이 전제입니다.
- 지금 `index.html`에는 `/static/` 밖의 주소(외부 CDN 등)가 없습니다. 글꼴은 시스템 글꼴입니다 (`style.css`의 `font-family`).
- **배포 때 필요한 점**: 서버 배포 계획서(`docs/infra/architecture.md`)는 웹 서버(Nginx)가 프론트엔드 파일을 `/var/www/ic26`에서 `/`로 직접 주고, `/api/`만 앱 서버로 넘기는 구성입니다. 이때 `index.html`이 부르는 `/static/style.css`와 `/static/app.js`도 웹 서버가 줘야 합니다. 파일을 `static/` 폴더째 올리거나, HTML의 주소와 서버 설정을 함께 바꾸세요. 배포를 맡은 박건영과 맞추세요.

### 2.2 `id` 목록

(11/15 `feat/connect-care-ui` 기준으로 다시 셈. 서랍·캡처·종합 리포트 id 포함) `app.js`가 찾는 id는 **114개**입니다. `$("…")`로 글자 그대로 적힌 99개, `"an-" + t`처럼 이어 붙여 찾는 10개(`an-summary`·`an-issues`·`an-paste`, `an-tab-summary`·`an-tab-issues`·`an-tab-paste`, `dot-care`·`dot-mkt`, `staff-care`·`staff-mkt`), 종합 리포트의 `RP_STATE` 표로 찾는 5개(`rp-daily-state`·`rp-score-state`·`rp-month-state`·`rp-market-state`·`rp-mkt-state`)를 합한 수입니다. 그중 `approvals`, `restart`, `rp-approvals`는 HTML이 아니라 `app.js`가 만들어 넣는 요소라서, `index.html`에서 `app.js`가 필요로 하는 id는 111개입니다. 여기에 CSS 선택자 `#staff li`가 쓰는 `staff` 하나가 더 있어서, **`index.html`에서 지우거나 이름을 바꾸면 안 되는 id는 112개**입니다. 이 id 중 하나라도 `index.html`에 없으면 `null`에 접근해서 화면이 멈춥니다.

`index.html`에는 id가 121개 있습니다. 112개를 뺀 나머지 9개는 JS가 찾지 않고 접근성 연결(`aria-labelledby`)로만 씁니다 (표의 마지막 묶음).

**상단 바와 알림**

| id | 한 줄 설명 |
|---|---|
| `store-name` | 상단 바의 가게 이름 줄. "가게 이름 · 업종 · 상권 이름 상권"으로 채움 |
| `ask-ai` | 상단 'AI에게 묻기' 버튼. 서랍(`#assistant`)을 열고 닫음. JS가 `aria-expanded`를 바꿈 |
| `mode-notice` | 시험용 실행 안내 띠. `/api/health`의 `mode_notice`가 있으면 보임. **시험이 이 id를 확인함** |
| `alert` | 오류·경고 띠. API 오류 문장과 막힘 안내를 여기에 보여 줌 |

**왼쪽 메뉴**

| id | 한 줄 설명 |
|---|---|
| `nav-draft-count` | 메뉴 '승인할 글' 옆의 숫자 (승인 대기 글 수). 0이면 숨김 |
| `staff` | 'AI 직원' 목록(`ul`). JS가 이 안의 `li`·`.dot`·`b`를 읽어 `#staff-strip`을 그림 |
| `staff-data` | 데이터 분석 비서의 상태 문구 ("리뷰 n건 정리 끝") |
| `dot-care` | 고객 응대 비서의 상태 점. JS가 `className`을 `"dot ok"` 또는 `"dot warn"`으로 통째로 바꿈 |
| `staff-care` | 고객 응대 비서의 상태 문구 ("만들 차례", "승인 대기 n개", "오늘 몫 끝") |
| `dot-mkt` | 마케팅 에이전트의 상태 점 (`dot-care`와 같음) |
| `staff-mkt` | 마케팅 에이전트의 상태 문구 |

**홈 `#/today`**

| id | 한 줄 설명 |
|---|---|
| `today-source` | 눈썹 줄의 "기간 · 리뷰는 합성 데이터" |
| `dash-title` | 홈 제목(`h1`). "사장님, 오늘 처리할 일 n가지" 등 |
| `hero-problem` | '오늘의 핵심 문제' 한 줄. **JS가 이 글자를 다시 읽어** '오늘 할 일'의 부제로 씀 |
| `staff-strip` | 375px 폭에서 보이는 AI 직원 한 줄 상태(`ul`). `#staff`를 복사해서 그림 |
| `stat-reviews` | '리뷰' 타일의 숫자 |
| `stat-reviews-sub` | '리뷰' 타일의 보조 글 ("28일 동안") |
| `stat-complaints` | '불만' 타일의 숫자 |
| `stat-complaints-sub` | '불만' 타일의 보조 글 ("리뷰의 30%") |
| `stat-repeated` | '반복 불만' 타일의 숫자 |
| `stat-repeated-sub` | '반복 불만' 타일의 보조 글 (반복 묶음 이름) |
| `stat-market` | '상권 저녁 매출' 타일의 숫자. **JS가 이 글자를 다시 읽어** '오늘 할 일'의 부제로 씀 |
| `stat-market-sub` | '상권 저녁 매출' 타일의 보조 글 ("상권이름 · 전년 같은 분기 대비") |
| `chart-note` | 시간대 차트 옆 설명 ("빨간 막대 = … 몰린 17~21시") |
| `hour-chart` | 시간대별 불만 막대 차트. JS가 막대를 그리고 `aria-label`을 채움 |
| `keywords` | 주제별 불만 막대 (이름은 keywords지만 주제별 막대가 들어감) |
| `todo` | '오늘 할 일' 목록(`ol`) |
| `todo-count` | "n / m 끝" |
| `start` | '무엇을 할까요?' 버튼. 처음엔 `disabled`, "불러오는 중…". 누르면 카드 화면으로 |
| `ask-open` | 홈 아래쪽 'AI에게 묻기' 입력줄 모양 버튼 (서랍 열기) |

**추천 카드 `#/cards`**

| id | 한 줄 설명 |
|---|---|
| `cards` | 카드 2장이 들어가는 칸. JS가 카드 HTML을 채움 |
| `no-card-b` | 카드 ⓑ가 없을 때의 이유 문장. **JS가 이 글자를 다시 읽어** 카드를 다시 그릴 때 씀 |

**초안 `#/draft`와 완료 `#/done`**

| id | 한 줄 설명 |
|---|---|
| `draft` | 초안 화면 전체. JS가 통째로 채움 (제목, 글 고르기, 편집 칸, 승인 버튼) |
| `done` | 완료 화면 전체. JS가 통째로 채움 |
| `restart` | (JS가 만듦) 완료 화면의 '처음으로' 버튼 |
| `approvals` | (JS가 만듦) 완료 화면 '서버 처리 기록' 목록 |

**리뷰 분석 `#/analysis`**

| id | 한 줄 설명 |
|---|---|
| `an-period` | 제목 위 눈썹 줄 ("기간 · 리뷰는 합성 데이터") |
| `an-status` | 불러오는 중·오류 안내 (`role="status"`). 오류면 `st`·`bad` 클래스를 켬 |
| `an-tab-summary` | '요약' 탭 버튼. **시험이 확인함** |
| `an-tab-issues` | '불만 묶음' 탭 버튼. **시험이 확인함** |
| `an-tab-paste` | '리뷰 붙여넣기' 탭 버튼. **시험이 확인함** |
| `an-summary` | '요약' 탭 내용(`role="tabpanel"`). JS가 `hidden`으로 보이고 숨김. **시험이 확인함** |
| `an-issues` | '불만 묶음' 탭 내용. **시험이 확인함** |
| `an-paste` | '리뷰 붙여넣기' 탭 내용. **시험이 확인함** |
| `an-reviews` | 요약 탭 '리뷰' 타일의 숫자 |
| `an-reviews-sub` | '리뷰' 타일의 보조 글 ("28일 · 긍정 n · 중립 n") |
| `an-complaints` | 요약 탭 '불만' 타일의 숫자 |
| `an-complaints-sub` | '불만' 타일의 보조 글 |
| `an-repeated` | 요약 탭 '반복 불만' 타일의 숫자 |
| `an-repeated-sub` | '반복 불만' 타일의 보조 글 |
| `an-kw` | 칭찬·불만 키워드 칩이 들어가는 칸 |
| `an-funnel` | 불만 묶음 탭의 "리뷰 → 불만 → 묶음 + 묶이지 않은 불만" 흐름 한 줄 |
| `an-groups` | 묶음 카드들이 들어가는 칸 |
| `an-singles-title` | '묶이지 않은 불만 n건' 제목 |
| `an-singles` | 묶이지 않은 불만 목록(`ul`) |
| `paste-text` | 리뷰 붙여넣기 글 칸(`textarea`, `maxlength="1000"`). JS가 `.value`를 읽음 |
| `paste-samples` | 예시 문장 버튼 네 개가 들어가는 칸. JS가 버튼을 만듦. 네 번째는 무리한 요청을 거절당한 별점 1점 리뷰(억울한 리뷰 시연용) |
| `paste-rating` | 별점 고르기(`select`). 값은 `""`(모름), `"5"`~`"1"`. JS가 `.value`를 읽음 |
| `paste-send` | '분류하기' 버튼 |
| `paste-reset` | '붙여넣은 리뷰 지우기' 버튼 |
| `paste-msg` | 붙여넣기 진행·오류 안내 (`role="status"`) |
| `paste-result` | 분류 결과 패널이 들어가는 칸 |

**리뷰 분석 > 리뷰 붙여넣기 탭 > 캡처로 넣기 (11/15)** (id는 모두 `cap`으로 시작. 시험 `test_care_ui_static.py`가 확인)

| id | 한 줄 설명 |
|---|---|
| `cap` | 캡처 칸(`section`). 파일을 끌어 놓으면 받음(`drop` 클래스를 켬) |
| `cap-file` | 파일 고르기(`input type="file"`, `accept="image/png,image/jpeg,image/webp"`, `hidden`). `#cap-choose`가 `click()`으로 엶 |
| `cap-choose` | '이미지 고르기' 버튼 |
| `cap-file-name` | 고른 파일 이름·크기 |
| `cap-send` | '캡처 읽기' 주 버튼. 파일이 없거나 읽는 중이면 `disabled` |
| `cap-status` | 진행·결과 안내 (`role="status"`). 읽는 중이면 `busy` 클래스 + 걸린 초 |
| `cap-error` | 이 칸의 오류 (`role="alert"`). 서버 문장 그대로. 비어 있으면 자리를 차지하지 않음 |
| `cap-result` | 후보 묶음 전체 (읽기 전에는 `hidden`) |
| `cap-demo` | "예시 결과 — 이미지를 실제로 읽지 않았어요" (응답 `demo: true`일 때만 보임) |
| `cap-warnings` | 응답 `warnings[]` 목록 (없으면 `hidden`) |
| `cap-preview` | '올린 캡처 보기' 안의 이미지 (별점 비교용, 브라우저 안에서만) |
| `cap-list` | 후보 목록(`ol`). JS가 후보마다 `li.cap-item`을 그림 |
| `cap-save` | '선택한 리뷰 저장' 주 버튼. 고른 후보가 없으면 `disabled` |
| `cap-picked` | "n건 고름" |
| `cap-save-msg` | 저장 진행·결과 (`role="status"`) |

**종합 리포트 `#/report` (11/15)** (id는 모두 `rp-`로 시작)

| id | 한 줄 설명 |
|---|---|
| `rp-reload` | '다시 불러오기' (세 응대 칸을 다시 부름) |
| `rp-daily-state` · `rp-daily` · `rp-daily-date` | 오늘 요약 칸의 상태 안내(`role="status"`, 오류면 `bad` 클래스) · 내용 · 날짜 |
| `rp-score-state` · `rp-score` | 응대 점수 칸의 상태 안내 · 내용 (큰 숫자, 이유, 답글 기다리는 불만과 남은 시간, 지난 불만) |
| `rp-month-state` · `rp-month` | 월간 보고서 칸의 상태 안내 · 내용 (숫자, SVG 그래프, 반복 불만 표, 제안) |
| `rp-month-prev` · `rp-month-label` · `rp-month-next` | 이전 달 · 보고 있는 달 · 다음 달 (이번 달이면 다음 달 `disabled`, 1년 전까지) |
| `rp-print` | '인쇄용 보기' 링크 (`/api/care/report/monthly/print?month=YYYY-MM`, 새 탭) |
| `rp-market-state` · `rp-market` | 상권 요약 칸 (브리핑의 상권 지표로만) |
| `rp-mkt-state` · `rp-mkt` | 마케팅 요약 칸 (추천 카드 ⓑ, 홍보글 승인 상태, 승인 기록 수) |
| `rp-approvals` | (JS가 만듦) 마케팅 요약 칸의 "서버에 남은 승인 기록 n건" |

**서랍 (AI에게 묻기 자리)과 바닥**

| id | 한 줄 설명 |
|---|---|
| `assistant` | 오른쪽 서랍(`aside`). `hidden` 속성으로 열고 닫음. `Esc` 키로도 닫힘 |
| `assistant-close` | 서랍의 '닫기' 버튼 |
| `assistant-clear` | 서랍 머리의 "대화 지우기" (4초 안에 두 번 눌러 확인). 대화가 있을 때만 보임 |
| `assistant-cond` | 분석 조건 줄 (조건이 없으면 `hidden`) |
| `assistant-cond-text` | 조건 줄의 글 ("장승배기역 4번 상권 · 한식음식점 · 2026년 2분기") |
| `assistant-home` | 조건 줄의 "우리 가게 조건으로" 버튼 (`POST /api/assistant/setup?force=1`) |
| `assistant-scroll` | 서랍 본문. 이 안에서만 스크롤됨 |
| `assistant-state` | 상태 안내 카드 (`off`·`down`·`disabled`·`no_data`·`error`일 때만 보임. 이때 입력칸은 막힘) |
| `assistant-state-title` · `assistant-state-msg` | 상태 카드의 제목 · 서버가 준 안내 문장(그대로 보임) |
| `assistant-retry` | 상태 카드의 "다시 확인" 버튼 |
| `assistant-welcome` | 대화가 비었을 때의 첫 안내 |
| `assistant-log` | 대화 기록 (`role="log"`). 사용자 말풍선, 비서 답, 선택지, 근거 카드 |
| `assistant-status` | 진행 안내 (`role="status"`: "자료를 확인하고 있어요" 등) |
| `assistant-chips` | 추천 질문 칩. 처음에는 고정 4개, 그 뒤에는 서버가 준 `suggestions` |
| `assistant-error` | 서랍 안 오류 (`role="alert"`). 서버 문장을 그대로 보임. 비서 화면의 `#alert`는 쓰지 않음 |
| `assistant-form` · `assistant-q` · `assistant-send` | 질문 입력 `form` · 입력칸(`textarea`, `maxlength="1000"`, `<label for>`가 가리킴) · 보내기 버튼 |
| `assistant-count` | 900자를 넘으면 "n / 1000자" |
| `honesty` | 바닥 '동작·모의 표시'가 들어가는 칸 (`/api/health`의 `parts`) |

**JS가 찾지 않는 id 9개** (접근성 연결. 이름을 바꾸면 연결된 `aria-labelledby`·`for`도 같이 바꿉니다)

| id | 한 줄 설명 |
|---|---|
| `chart-title` | 차트 패널 제목. 패널의 `aria-labelledby`가 가리킴 |
| `todo-title` | '오늘 할 일' 패널 제목. 패널의 `aria-labelledby`가 가리킴 |
| `assistant-title` | 서랍 제목. 서랍의 `aria-labelledby`가 가리킴 |
| `cap-title` | 캡처 칸 제목 (`#cap`의 `aria-labelledby`) |
| `rp-daily-title` · `rp-score-title` · `rp-month-title` · `rp-market-title` · `rp-mkt-title` | 종합 리포트 다섯 칸의 제목 (칸마다 `aria-labelledby`) |

**`app.js`가 만들어 넣는 id (찾지는 않음)**: `card-(카드 id)`, `draft-(글 id)`, `text-(글 id)`, 캡처 후보의 `cap-text-(번호)`·`cap-rate-(번호)`(라벨 `for`가 가리킴). 편집 칸(`textarea`)의 `id`가 `text-(글 id)`이고 `<label for>`가 이를 가리킵니다. 이 규칙을 바꾸면 라벨과 편집 칸의 연결이 끊어집니다.

### 2.3 id 말고도 app.js가 기대하는 것

**(1) 선택자로 찾는 구조 (클래스·속성·태그)**. 이 구조가 없으면 해당 기능이 조용히 멈춥니다.

| 선택자 | 쓰는 곳 | 기대하는 것 |
|---|---|---|
| `.top` | 상단 바 높이를 재서 `--top-h` 변수에 넣음 | 상단 바 요소에 `top` 클래스 |
| `.side .menu` | 준비 중 메뉴 링크를 끝에 더함 | 왼쪽 메뉴 `nav`에 `side`, 그 안 목록에 `menu` 클래스 |
| `.shell > main` | 준비 중 화면을 끝에 더함 | `shell` 클래스 요소의 바로 아래 자식 `main` |
| `.menu a` | 현재 화면의 메뉴 링크에 `aria-current="page"`를 켬 | 메뉴 링크마다 `data-route` |
| `#staff li`, 그 안의 `.dot`, `b`, `b + span` | `#staff-strip`을 그림 | `li` 안에 `.dot`, 굵은 글 `<b>`, 그 바로 다음 `<span>`(상태 문구) 순서 |
| `[data-view]` | 화면 전환 (`hidden`) | 화면마다 `<section data-view="이름">` |
| `[data-view="이름"] h1` | 화면을 바꾸면 그 화면의 첫 `h1`에 포커스 | 화면 안에 `h1`(`tabindex="-1"`). 없으면 포커스만 건너뜀 |
| `[role="tab"][data-tab]` | 탭 클릭·키보드 | 탭 버튼마다 `role="tab"`과 `data-tab` |
| `[data-view="analysis"]` 안의 `[data-goto-tab]` | '불만 묶음 보기' 버튼으로 탭 이동 | 버튼의 `data-goto-tab` 값 |
| `#cards [data-run]` | 카드 버튼 클릭 | JS가 만든 버튼의 `data-run` |
| `.todo-st` | '오늘 할 일' 항목이 "만드는 중…"으로 바뀜 | 항목 버튼 안의 `todo-st` 클래스 |
| `#cap-list [data-cap-pick]`, `.cap-item` 안의 `[data-cap-text]`·`[data-cap-rate]`·`[data-cap-msg]`·`.cap-saved` | 캡처 후보 고르기·저장 | JS가 그린 후보 `li.cap-item` |
| `[data-view="report"]` 안의 `[data-rp-ask]` | 상권 요약의 'AI에게 묻기로 상권 더 보기' → 서랍 | JS가 그린 버튼 |
| `#rp-score [data-clock]` | 남은 시간을 1초마다 다시 씀 | JS가 그린 `span.rp-clock` |

**(2) `data-*` 속성**

| 속성 | 어디에 있나 | 뜻 |
|---|---|---|
| `data-route` | `index.html` 메뉴 링크 (준비 중 링크는 JS가 만듦) | 화면 이름 (2.5) |
| `data-view` | `index.html`의 화면 `section` (준비 중 화면은 JS가 만듦) | 화면 이름 (2.5) |
| `data-tab` | `index.html` 탭 버튼 | 탭 이름 (`summary`·`issues`·`paste`) |
| `data-goto-tab` | `index.html`과 JS가 만든 버튼 | 눌렀을 때 이동할 탭 이름 |
| `data-run` | JS가 만든 카드 버튼 | 카드 id |
| `data-todo` | JS가 만든 '오늘 할 일' 버튼 | 할 일 종류 (`notice`·`reply`·`promo`) |
| `data-measure` | JS가 만든 재발 방지 조치 체크박스 | 카드 id (`value`가 조치 id) |
| `data-text` | JS가 만든 글 편집 칸 | 글 id |
| `data-card` · `data-pick` | JS가 만든 카드 고르기·글 고르기 버튼 | 카드 id · 글 id |
| `data-approve` · `data-copy` · `data-rerun` | JS가 만든 '승인'·'복사'·'다시 만들기' 버튼 | 글 id · 글 id · 카드 id |
| `data-sample` | JS가 만든 예시 문장 버튼 | 예시 번호 |
| `data-cap-pick` · `data-cap-text` · `data-cap-rate` · `data-cap-msg` | JS가 만든 캡처 후보의 체크 칸 · 글 칸 · 별점 · 오류 줄 | 후보 번호 |
| `data-clock` | JS가 만든 남은 시간 표시 | `pending` 순번 |
| `data-rp-ask` | JS가 만든 상권 요약의 서랍 열기 버튼 | (값 없음) |

**(3) JS가 켜고 끄는 상태.** CSS가 이 상태를 보고 모양을 정하는 곳이 있습니다. 모양은 바꿔도 되지만 JS가 상태를 바꾸는 방식은 그대로 둡니다.

| 상태 | 누가 | CSS에서 쓰이는 선택자 |
|---|---|---|
| `hidden` 속성 | 화면 전환, 탭, 서랍, 띠, 배지 등 | `[hidden] { display: none !important; }` (**꼭 유지**) |
| `aria-current="page"` | 현재 화면의 메뉴 링크 | `.side .menu a[aria-current="page"]` |
| `aria-current="true"` | 고른 카드·글 버튼 | `.seg`, `.draft-list` 안의 버튼 |
| `aria-selected="true"`와 `tabindex` | 고른 탭 | `.an-tabs [aria-selected="true"]` |
| `aria-expanded="true"` | 서랍을 열고 있을 때 `#ask-ai`, `#ask-open` | `.ask[aria-expanded="true"]` |
| `class="dot ok"` / `"dot warn"` | `#dot-care`, `#dot-mkt` (`className`을 통째로 바꿈) | `.dot.ok`, `.dot.warn` |
| `st`·`bad` 클래스 켜고 끄기 | `#an-status` | `.st`, `.bad` |
| `<html data-theme="light">` | 주소에 `?theme=light`가 있을 때 | `:root:not([data-theme="light"])` 안의 다크 색 |
| `--top-h` (CSS 변수) | JS가 `<html>`에 상단 바 높이를 넣음 | `.side`, `.drawer`의 `top`·`height` |

**(4) JS가 DOM에서 다시 읽는 글자**: `#hero-problem`, `#stat-market`, `#no-card-b`의 글자와 `#staff li`의 구조입니다. 이 요소의 글자 모양을 바꿔도 되지만, 안에 다른 태그나 장식 글자를 섞으면 '오늘 할 일' 부제에 그대로 섞여 나옵니다.

**(5) 입력 요소의 종류**: `#paste-text`는 `textarea`(`.value`), `#paste-rating`은 `select`(`.value`), `#start`·`#paste-send`·`#paste-reset`은 `button`(`.disabled`)이어야 합니다.

**(6) CSS에 꼭 있어야 하는 규칙**

| 규칙 | 이유 |
|---|---|
| `[hidden] { display: none !important; }` | `display`를 주는 다른 규칙이 `hidden`을 이기면 숨겨야 할 것이 보임 |
| `.card .reason { white-space: pre-line; }` | 카드 ⓑ 이유 문장의 줄바꿈(`\n`)을 살림 |

**(7) JS가 HTML 문자열로 만드는 클래스.** 스타일은 자유롭게 바꿔도 되지만, **이름을 바꾸려면 `app.js` 안의 문자열도 같이 바꿔야** 합니다. 괄호 안은 JS가 상황에 따라 붙이는 상태 클래스입니다.

| 어디 | 클래스 |
|---|---|
| 홈 차트 | `hc-col`(+`hot`), `hc-n`, `hc-h`, `tb-row`, `tb-name`, `tb-track`(안의 `<i>`에 `hot`), `tb-n`, `tb-rest` |
| 홈 '오늘 할 일' | `todo-item`(+`urgent`, +`done`·`wait`·`none`), `todo-check`, `todo-text`, `todo-urgent`, `todo-st` |
| AI 직원 한 줄 | `dot`(+`ok`·`warn`), `muted` |
| 추천 카드 | `card`, `kind`, `agent`, `reason`, `measures`, `more`, `ev`, `primary` |
| 초안 | `page-head`, `eyebrow`, `badge`(+`ok`·`warn`·`bad`), `seg`, `progress`, `track`, `draft-list`, `st`(+`ok`·`warn`·`bad`), `draft`(+`approved`), `draft-head`, `rv`, `rv-title`, `rv-list`, `rv-meta`, `rv-text`, `stars`, `reply`, `reply-label`, `ico`, `issues`(+`bad`), `row`, `ghost`, `model` |
| 완료 | `log`, `plain`, `big`, `panel`, `more` |
| 리뷰 분석 | `kw-row`, `kw-title`, `kw-chip`(+`pos`·`neg`), `box`, `n`, `arrow`, `group`(+`repeated`·`new`), `group-head`, `badge`(+`rep`·`ok`), `an-note`, `an-bands`, `topic-bars`, `quote`, `an-joined`, `panel`, `panel-head` |
| 캡처로 넣기 | `cap-item`(+`dup`·`saved`), `cap-item-head`, `cap-check`, `cap-saved`, `cap-item-foot`, `cap-item-msg`, `cap-sec`, `badge`(+`warn`·`ok`), `sr` · 상태 클래스 `busy`(`#cap-status`), `drop`(`#cap`) |
| 종합 리포트 | `rp-summary`, `rp-nums`, `rp-line`, `rp-delta`(+`neg`·`pos`), `rp-reasons`, `rp-todo`, `rp-todo-label`, `rp-score-top`, `rp-big`, `rp-big-n`, `rp-big-unit`, `rp-peak`, `rp-h3`, `rp-pending`, `rp-p`(+`over`), `rp-p-main`, `rp-p-text`, `rp-clock`(+`over`·`soon`·`paused`), `rp-untimed`, `rp-chart`, `rp-trend`, `rp-gl`, `rp-ax`, `rp-now`, `rp-line`, `rp-pt`, `rp-table-wrap`, `rp-table`, `num`, `rp-sugg`, `rp-store`, `rp-snaps`, `rp-snap-v`(+`neg`), `rp-snap-t`, `rp-ask`, `rp-mkt-title`, `rp-mkt-reason`, `rp-mkt-st`, `rp-mkt-none` · 상태 클래스 `bad`(`#rp-*-state`) |
| 준비 중 자리 | `later`, `later-title`, `later-badge`, `view`, `narrow`, `page-head`, `eyebrow`, `badge` |
| 어디서나 | `small`, `muted`, `sr`(화면에는 안 보이고 읽기 프로그램에만 읽힘), `long`(375px 메뉴에서 숨김) |

### 2.4 시험이 직접 확인하는 것

기존 시험 69건은 `services/web/tests/`의 `test_web.py` 45건과 `test_measure_live.py` 24건입니다 (main `d7c1305`에서 모두 통과함을 확인함). 그중 **화면 파일(`index.html`, `app.js`)을 글자로 읽어 확인하는 시험은 아래 6개**입니다. 나머지는 화면 파일을 읽지 않습니다. 이 6개를 바꾸면 시험이 깨집니다.

| # | 시험 | 확인하는 것 |
|---|---|---|
| 1 | `test_web.py` · `LiveAndMockOnly.test_screen_shows_the_notice_only_through_health` | `index.html`에 `id="mode-notice"`가 있음. `app.js`에 `mode_notice`와 `실제 AI 결과 아님`이 있음. **`index.html`과 `app.js` 어디에도 `replay`(대소문자 무시), `c9`, `id="record"`가 없음** |
| 2 | `test_web.py` · `AnalysisScreen.test_no_link_or_call_to_the_old_review_page` | `index.html`과 `app.js`에 **없어야 하는 글자**: `analysis-link`, `리뷰 분석 화면에서`, `/api/review-insight`, `review_service.url}/`. `app.js`에 없어야 하는 글자: `rs.url`. `app.js`의 `api(` 호출 중 첫 글자가 따옴표나 백틱인 것은 모두 주소가 `/api/`로 시작해야 하고, 그중 `/api/insight`가 있어야 함 (정규식 ``api\(\s*[`"']([^`"']+)``) |
| 3 | `test_web.py` · `AnalysisScreen.test_analysis_has_three_keyboard_tabs` | `index.html`에 `role="tablist"`와 `id="an-tab-summary"`, `id="an-tab-issues"`, `id="an-tab-paste"`, `id="an-summary"`, `id="an-issues"`, `id="an-paste"`가 (따옴표는 큰따옴표) 있음. `app.js`에 `ArrowRight`, `ArrowLeft`, `Home`, `End`가 있음 |
| 4 | `test_web.py` · `AnalysisScreen.test_later_menu_slots` | `app.js`에 `회의에서 정한 뒤 넣을 자리입니다`, `준비 중`이 있고, `LATER` 목록에 `"상권"`이 있으며 `route: "report"`는 없음 (11/15 종합 리포트가 진짜 화면이 됨) |
| 5 | `test_web.py` · `AnalysisScreen.test_every_id_the_script_uses_exists` | `app.js`의 `$("…")`로 적힌 id 전부, 그리고 `an-`·`an-tab-`(summary·issues·paste), `dot-`·`staff-`(care·mkt)로 이어 붙인 id가 `index.html` 또는 `app.js`에 `id="…"`(큰따옴표)로 있음. 정규식은 ``\$\(\s*["']([\w-]+)["']\s*\)``와 `id="([\w-]+)"` |
| 6 | `test_measure_live.py` · `StatusRule.test_rules_are_still_the_ones_in_app_js` | `app.js`(공백·줄바꿈은 한 칸으로 합쳐서 비교)에 아래 일곱 줄이 **글자 그대로** 있음 |

시험 6의 일곱 줄:

```text
const failedOf = (d) => d.failed_reasons || [];
const checksOf = (d) => [...(d.needs_input || []), ...(d.c7_flags || [])];
? ["bad", "점검 실패"] : checksOf(d).length ? ["warn", "확인 필요"] : ["ok", "점검 통과"]
failedOf(d).length ?
reply_draft: "답글", prevention_notice: "재발 방지 공지"
JSON.stringify({ measures: boxes.filter((b) => b.checked).map((b) => b.value) })
const on = new Set(m.default || []);
```

**11/15에 더한 정적 시험** (화면 파일을 글자로 읽음)

- `test_assistant_drawer_static.py`: 서랍 id(`assistant-`), `/api/assistant/*`만, `drawerApi`만, 90초 끊기, 한글 입력 중 Enter 막기, 첫 추천 질문 4개.
- `test_care_ui_static.py` (17건): 캡처 칸 id는 `cap`, 리포트 id는 `rp-`로 시작하고 JS가 찾는 것은 모두 HTML에 있음. 두 화면은 `careApi`로만 `/api/care/*`·`/api/reviews`·`/api/approvals`를 부르고 전역 `api()`·`showAlert`·`#alert`를 쓰지 않음. `accept`의 세 형식, 10MB, 이미 있는 리뷰는 처음에 고르지 않음, `source: "capture"`, 예시 결과·`warnings`·별점 확인 문구, 메뉴 자리(리뷰 분석 다음)와 `ROUTES`의 `"report"`, 인쇄 링크(`target="_blank"`, `rel="noopener"`), 남은 시간(`due_at`)·멈춤·지난 불만, 월간 표의 칸 7개와 SVG 그래프, **종합 리포트 덩어리가 `/api/cards`·`/api/briefing`·`/run`·`/api/assistant`·`refresh(`를 부르지 않음**(열어도 AI를 새로 부르지 않음), 외부 스크립트 없음.
- `test_care_proxy.py` (29건, 화면 파일은 읽지 않음): 1.11절의 허용 목록·덮어쓰기·손님용 경로·상태·413·500 없음·막히지 않음, 1.6의 답글 승인 기록, 1.8의 `source`.

**11/16에 더한 정적 시험**

- `test_praise_ui_static.py` (9건): 카드 근거(`evidence`)의 종류를 이름으로 가림 (`e.type === "snapshot"`·`"praise"`. `e.type !== "review"`로 '리뷰가 아니면 모두 지표'라고 다루지 않음), `sourceLine`의 "손님 칭찬 리뷰 n건", '근거 보기' 칩의 "칭찬 리뷰 rv_…: “…”"(`evidenceChip`), 홍보글 초안의 `sourceBlock`이 '근거 지표'와 '손님 칭찬 리뷰' 두 덩어리를 모두 그림, 리뷰 글·id·메뉴 이름은 `esc()`를 거침, 홈 할 일의 홍보글 부제에 쿠폰 메뉴(`praiseOf`). 카드 응답 쪽은 `test_praise_card.py`(화면 파일은 읽지 않음)가 지킵니다.

**조심할 점**

- `replay`와 `c9`는 **주석, 문자열, SVG 경로 데이터, 색 코드(`#c9…`), 인코딩된 그림 데이터까지** 어디에 있든 걸립니다. 지금 두 파일에는 없습니다 (확인함). 아이콘 SVG를 붙일 때 경로 데이터에 `c9`가 우연히 들어가지 않았는지 확인하세요.
- 시험 2의 금지 글자는 **주석에도** 걸립니다. 파일 전체를 글자로 읽기 때문입니다.
- 시험 5는 큰따옴표로 쓴 `id="…"`만 인식합니다. `id='…'`나 따옴표 없는 id는 못 찾아 시험이 실패합니다.
- 시험 6은 `app.js`의 글자 그대로를 비교합니다. prettier 같은 정리 도구가 `(d) =>`를 `d =>`로, 큰따옴표를 작은따옴표로 바꾸면 깨집니다. 시험 6이 깨지면 `services/web/scripts/measure_live.py`의 `draft_status`와 `card_run_body`도 같이 고쳐야 합니다 (시험 설명에 적혀 있음).
- 시험 3의 `Home`·`End`는 `app.js` 어디에든 글자가 있으면 통과합니다. 탭의 키보드 조작(←/→/Home/End)은 실제 접근성 기능이니 지우지 마세요.
- 시험 1·4의 문구(`mode_notice`, `실제 AI 결과 아님`, `회의에서 정한 뒤 넣을 자리입니다`, `준비 중`)는 화면 문구 중 시험이 지키는 것입니다. 다른 화면 문구는 시험이 지키지 않습니다.

**API 모양을 지키는 시험**: 화면 파일은 읽지 않지만 API 응답 칸을 시험합니다 (예: `/api/briefing`의 `counts`, `/api/insight`의 키 집합(`Demo.INSIGHT_KEYS`), 승인 기록 파일). 화면 담당이 바꿀 일은 아니지만, 서버의 칸을 바꾸면 이 시험이 깨집니다.

### 2.5 화면 주소

화면은 **주소 해시**로 바뀝니다 (`#/이름`). `hashchange` 때 `app.js`의 `route()`가 해당 `data-view`만 보이게 하고, 해당 `data-route` 메뉴 링크에 `aria-current="page"`를 켭니다. 화면을 바꿀 때마다 맨 위로 스크롤하고 그 화면의 `h1`에 포커스를 줍니다.

| 주소 | `data-route` · `data-view` 값 | 메뉴 이름 | 화면 | 어디서 만드나 |
|---|---|---|---|---|
| `#/today` | `today` | 홈 | 대시보드. 숫자 타일, 차트, 오늘 할 일 | `index.html` |
| `#/cards` | `cards` | 추천 카드 | "무엇을 할까요?" 카드 2장 | `index.html` |
| `#/draft` | `draft` | 승인할 글 | 초안 보기·고치기·승인 | `index.html`의 껍데기 + JS가 채움 |
| `#/done` | `done` | 처리 완료 | 승인 결과, 처음으로 | `index.html`의 껍데기 + JS가 채움 |
| `#/analysis` | `analysis` | 리뷰 분석 | 탭 3개 (요약·불만 묶음·리뷰 붙여넣기) | `index.html` |
| `#/report` | `report` | 종합 리포트 | 오늘 요약 · 응대 점수 · 월간 보고서 · 상권 요약 · 마케팅 요약 (11/15) | `index.html` |
| `#/market` | `market` | 상권 (준비 중) | 빈 자리 | `app.js`의 `LATER`가 만듦 |

- 알 수 없는 해시, 해시가 없는 주소는 `#/today`로 봅니다 (`currentRoute()`가 `ROUTES`에 없는 이름을 홈으로 돌림).
- `ROUTES` 배열(`["today", "cards", "draft", "done", "analysis", "report", ...LATER의 이름]`)에 없는 화면 이름은 쓸 수 없습니다.
- **화면을 새로 더하려면** (1) 메뉴 링크 `<a href="#/이름" data-route="이름">`, (2) `<section class="view" data-view="이름" hidden>`, (3) `ROUTES`에 이름 추가, 이 세 가지가 필요합니다 (`LATER`로 만든 자리는 `LATER`에서 빼고 `ROUTES`에 이름을 넣는다고 `app.js` 주석에 적혀 있음).
- `#/draft`와 `#/done`은 화면을 열 때마다 다시 그립니다. 만든 글이 없으면 "제안 보기" / "초안으로" 링크가 있는 빈 안내가 나옵니다.
- 주소가 같은 화면으로 `go()`하면 해시는 그대로 두고 `route()`만 다시 부릅니다.
- 링크로 쓰는 주소: 로고 `href="#/today"`, 홈의 '리뷰 분석 보기' `href="#/analysis"`, 초안의 빈 안내 `href="#/cards"`, 완료의 빈 안내 `href="#/draft"`.

### 2.6 화면 흐름과 부르는 API

| 언제 | 부르는 API | 결과가 가는 곳 |
|---|---|---|
| 페이지를 열 때 (순서대로 하나씩) | `health` → `briefing` → `cards` → `insight` | `health`: 맨 위 띠·경고 띠·바닥. `briefing`: 홈·가게 이름·초안의 리뷰 원문. `cards`: 카드 화면·홈 할 일. `insight`: 리뷰 분석 두 탭 |
| 위 호출이 실패하면 | (`health`·`briefing`·`cards` 중 하나) | `#alert`에 문장, `#start` 버튼이 "불러오지 못했어요"로 바뀜. `insight`만 실패하면 `#an-status`에만 알림 |
| '무엇을 할까요?' 누름 | 없음 | `#/cards`로 이동 |
| 카드 버튼 / '오늘 할 일' 항목 (아직 안 만든 글) | `POST /api/cards/{id}/run` | `#/draft`로 이동. 카드 ⓐ의 체크박스가 있으면 `{"measures": […]}`를 보냄 |
| 이미 만든 글을 다시 보기 | 없음 | 브라우저에 있는 결과로 `#/draft` |
| 초안의 '승인' | `POST /api/drafts/{id}/approve` (`{text, original}`) | 다음 미승인 글, 다 끝나면 `#/done` |
| 초안의 '복사' | 없음 | 클립보드 |
| 초안의 '다시 만들기' | `POST /api/cards/{id}/run` | 그 카드의 예전 글·승인·고친 내용 버림 |
| `#/done` 열기 | `GET /api/approvals` | '서버 처리 기록' (접은 목록) |
| '처음으로' | 없음 | 브라우저의 만든 글·승인 표시만 비움. 서버 기록은 그대로 |
| 붙여넣기 '분류하기' | `POST /api/reviews` → 성공하면 `briefing`, `cards`, `insight` 다시 | 분류 결과 패널, 홈·카드·분석 갱신 |
| '붙여넣은 리뷰 지우기' | `DELETE /api/reviews/pasted` → `briefing`, `cards`, `insight` 다시 | 위와 같음 |
| 캡처로 넣기 '캡처 읽기' | `POST /api/care/reviews/capture` (multipart, 최대 110초 기다림) | 후보 목록 (저장하지 않음). 오류는 `#cap-error`에만 |
| '선택한 리뷰 저장' | 고른 후보마다 `POST /api/reviews` `{text, rating, source: "capture"}` → 하나라도 저장되면 `briefing`, `cards`, `insight` 다시 | 후보마다 "저장함" 또는 그 후보 아래 오류, 홈·카드·분석 갱신 |
| 초안의 '승인' (리뷰 답글) | 위 승인 + 본문에 `kind`·`review_id` | 서버가 리뷰 분석 서비스에 '답글 달았음' 기록 (1.6, 화면은 기다리지 않음) |
| `#/report` 열기·'다시 불러오기' | `GET /api/care/report/daily`, `/api/care/response`, `/api/care/report/monthly` (따로따로), `GET /api/approvals` | 칸마다 그림. 한 칸이 실패해도 다른 칸은 그대로. 상권·마케팅 요약은 이미 받은 `briefing`·`cards`로만 (새로 부르지 않음, AI 호출 없음). 화면에 있는 동안 1분마다 `response`만 다시 |
| 월간 '이전 달'·'다음 달' | `GET /api/care/report/monthly?month=YYYY-MM` | 월간 칸, '인쇄용 보기' 주소도 그 달로 |

- 다시 불러온 카드의 id·근거가 이전과 다르면(`refresh()`), 화면에 있던 만든 글·승인 표시·고친 내용을 모두 버립니다.
- 모든 진행 상태(만든 글, 승인 표시, 고친 글)는 **브라우저 메모리**(`state` 객체)에만 있습니다. 새로고침하면 사라집니다 (3.1).

### 2.7 자유롭게 바꿔도 되는 것

| 바꿔도 되는 것 | 조건·주의 |
|---|---|
| 색, 글꼴, 글자 크기, 간격, 모서리, 그림자 | 색은 `style.css` 맨 위 `:root` 변수(`--bg`, `--panel`, `--ink`, `--accent`, `--brand` 등)에 모여 있고, 다크 값은 `@media (prefers-color-scheme: dark)` 안에 따로 있음. 라이트·다크 둘 다 챙기세요. CSS 주석에 따르면 글자 대비를 WCAG AA(4.5:1)에 맞춰 둔 값이 있으니, 색을 바꿀 때 대비를 다시 확인하세요 |
| 배치 (flex·grid), 화면 폭별 모양 | 지금은 760px 이하에서 모바일 배치(왼쪽 메뉴가 위쪽 가로 메뉴로, 서랍이 아래 시트로)이고 `main`의 컨테이너 쿼리(600·640·720px)도 씀. 375px 폭에서 가로 스크롤이 생기지 않게 |
| 아이콘 (인라인 SVG) | `index.html`·`app.js` 안에 있음. **`c9`, `replay`가 들어가면 시험이 깨짐** (2.4). `aria-hidden="true"`로 장식 표시 |
| 문구 (버튼 글자, 제목, 안내문) | 2.4에 적은 문구(`mode_notice`, `실제 AI 결과 아님`, `회의에서 정한 뒤 넣을 자리입니다`, `LATER`의 `"상권"`, `준비 중`, 캡처의 "예시 결과 — 이미지를 실제로 읽지 않았어요"·별점 확인 문구·`선택한 리뷰 저장`, 종합 리포트 제목)와 시험 6의 일곱 줄만 빼고 자유 |
| CSS 클래스의 **스타일** | 2.3(7)에 적은 클래스의 모양은 자유. 이름은 `app.js`와 같이 바꿔야 함. `index.html`에만 있는 클래스(`bar`, `brand`, `logo`, `dash-grid` 등)는 `style.css`와 `index.html`만 맞추면 됨 |
| HTML 요소 더하기·순서 바꾸기·감싸기 | 2.2의 id와 2.3(1)의 구조(`.top`, `.side .menu`, `.shell > main`, `#staff li`, `data-*`)를 지키는 한 자유. 태그 종류는 2.3(5)를 지킴 |
| 애니메이션, 호버, 포커스 모양 | 자유. 키보드 포커스가 보이게 유지 |
| 새 정적 파일 (이미지, 글꼴) | `static/` 안에 두고 `/static/…`으로 부름 (2.1) |

**`app.js`가 클래스 이름으로 찾거나 붙이는 것** (이름을 바꾸면 안 되거나, 바꾸면 `app.js`도 고쳐야 하는 것)

| 클래스 | `app.js`가 하는 일 |
|---|---|
| `top` | `document.querySelector(".top")`로 찾아 높이를 잼 |
| `side`, `menu` | `.side .menu`로 찾아 준비 중 링크를 더함. `.menu a`로 현재 메뉴를 표시 |
| `shell` | `.shell > main`으로 찾아 준비 중 화면을 더함 |
| `dot` | `#staff`의 `.dot`을 읽어 복사. `#dot-care`·`#dot-mkt`의 `className`을 `"dot ok"`·`"dot warn"`으로 바꿈 |
| `todo-st` | '오늘 할 일' 버튼 안에서 찾아 글자를 "만드는 중…"으로 바꿈 |
| `st`, `bad` | `#an-status`에 켜고 끔 |
| 2.3(7)의 클래스 전부 | HTML 문자열 안에서 붙임 |

### 2.8 바꾼 뒤 확인하는 법

**시험 69건** (저장소 루트에서 가상환경을 만든 뒤):

```bash
cd services/web
PYTHONPATH="$(cd ../.. && pwd)" ../../.venv/bin/python -m unittest discover -s tests -t . -v
```

- `tests.test_web`만 돌리면 45건, `discover`로 돌리면 69건입니다 (`README.md`의 명령은 `test_web`만 돌림).
- 시험은 외부 호출을 하지 않습니다 (리뷰 분석 서버는 가짜, 모델은 가짜 함수). 글 만드는 저장 예시 파일이 없으면 그것이 필요한 시험만 건너뜁니다.

**눈으로 확인할 것** (시험용 실행으로 띄우고):

1. 홈이 뜨고, 숫자 타일 4개와 차트가 채워지고, 맨 위에 시험용 띠가 보인다.
2. '무엇을 할까요?' → 카드 2장 → 카드 ⓐ의 '재발 방지 공지·답글 만들기' → 초안 화면으로 간다.
3. 초안에서 글을 고치고 '승인' → 다음 글로 간다 → 다 승인하면 '처리 완료'가 뜬다.
4. 리뷰 분석 3탭이 마우스와 ←/→/Home/End 키로 바뀐다. 붙여넣기 탭에서 예시 문장으로 '분류하기', '붙여넣은 리뷰 지우기'가 동작한다.
5. 375px 폭(휴대전화)에서 가로 스크롤이 없고, 메뉴가 위쪽 가로 메뉴가 된다.
6. 운영체제가 다크일 때와 `?theme=light`를 붙였을 때 둘 다 글자가 읽힌다.
7. 'AI에게 묻기' 버튼으로 서랍이 열리고 `Esc`나 '닫기'로 닫힌다.

---

## 3부. 데이터가 어디에 저장되나, 무엇이 바뀔 예정인가

> **11/14 덧붙임: 이 3부의 일부는 `main`에서 이미 바뀌었습니다.** 이 문서의 기준 커밋(`d7c1305`) 뒤에 DB 저장 코드(`shared/storage`)와 상권 코드(`services/market-analysis`)가 `main`에 들어왔습니다. 화면 파일 3개와 2부의 규칙은 그대로입니다. 달라진 것은 아래와 같습니다.
>
> - **방문자 구분이 생겼습니다.** 서버가 쿠키 `visitor_id`(HttpOnly, 30일)를 주고, 승인 기록과 붙여넣은 리뷰를 그 값으로 나눕니다. 브라우저가 쿠키를 알아서 보내므로 화면 코드는 고칠 것이 없습니다. 로그인은 아닙니다.
> - **환경 변수 `DB_HOST`가 있으면** 승인 기록, 붙여넣은 리뷰, 카드 이유 문장을 PostgreSQL에 둡니다. 없으면 아래 3.1 표대로이고, 붙여넣은 리뷰 파일만 방문자마다 `data/runtime/visitors/<방문자>/`로 나뉩니다.
> - **DB에 닿지 못하는 동안** `POST /api/drafts/{id}/approve`는 `200`에 `warning` 칸이 붙고, 브리핑, 카드, 리뷰 분석, 붙여넣기는 `503`입니다.
> - 자세한 내용은 `services/web/README.md`의 저장 절, 표 정의는 `db/schema.sql`에 있습니다. 1부의 API별 설명과 아래 3.1, 3.2 표에는 아직 반영하지 않았습니다.

### 3.1 지금

아래는 기준 커밋의 코드를 읽어 확인한 내용입니다.

| 데이터 | 어디에 있나 | 얼마나 오래 | 누가 읽고 쓰나 |
|---|---|---|---|
| **승인 기록** | ① 비서 화면 서버의 **메모리**(`Demo.approvals`, `services/web/web/demo.py`) ② 파일 `services/web/data/runtime/approvals.jsonl`에 **한 줄씩 덧붙임** (환경변수 `WEB_RUNTIME_DIR`로 위치 변경. git에 올리지 않음) | 메모리는 서버를 끄면 사라짐. 파일은 남지만 서버가 **다시 읽지 않음** (`GET /api/approvals`는 메모리만 줌) | `POST …/approve`가 쓰고, `GET /api/approvals`가 메모리를 읽음 |
| **붙여넣은 리뷰** | **리뷰 분석 서버의 디스크**. 파일 `services/review-insight/data/runtime/pasted_store_ongi.json` (JSON 목록. git에 올리지 않음) | 파일이라 서버를 꺼도 남음. `DELETE`가 `[]`로 비움 | `POST /api/reviews`가 쓰고, 비서 화면 서버는 요청마다 리뷰 분석 서버에서 다시 받음 (자기 안에 보관하지 않음) |
| **합성 리뷰·가게 정보** | **git 파일** `services/review-insight/data/synthetic/store_ongi/{store.json, reviews.json, labels.json}`. 가게 3곳(`store_ongi`, `store_basak`, `store_mongle`)이 있고 화면은 `DEMO_STORE_ID`의 한 곳(기본 `store_ongi`)만 씀 | 저장소에 있음 | 리뷰 분석 서버가 읽음. `labels.json`은 분류가 맞는지 확인하는 정답표 |
| **상권 지표** | **git 파일** `data/scenario/snapshot_2026Q2.json` (환경변수 `SNAPSHOT_PATH`로 변경) | 저장소에 있음 | 비서 화면 서버가 **요청마다** 읽음 |
| **시험용 글(mock)** | **git 파일** `experiments/marketing/c6/replay/c6_cache_best.json` | 저장소에 있음 | 비서 화면 서버가 시작할 때 한 번 읽음 |
| **만든 글(live)** | 저장하지 않음. 브라우저 화면에만 있음 | 새로고침하면 사라짐 | — |
| **카드 이유 문장** | 비서 화면 서버의 메모리(`_reason_memo`). 같은 입력이면 live에서 HCX를 다시 부르지 않으려는 것 | 서버를 끄면 사라짐 | `GET /api/cards`가 씀 |
| **리뷰 분류 결과** | mock(규칙 분류)은 **요청마다 새로 계산**하고 저장하지 않음. 리뷰 분석 서버가 live일 때만 결과를 파일(`services/review-insight/data/replay/classify.json`, `services/review-insight/data/runtime/classify_paste.json`)에 남김 | — | 리뷰 분석 서버 |
| **화면 진행 상태** (만든 글, 승인 표시, 고친 글) | **브라우저 메모리**(`app.js`의 `state`) | 새로고침하면 사라짐. `localStorage`·쿠키를 쓰지 않음 (확인함) | `app.js` |
| **방문자 구분** | **없음** | — | 로그인·쿠키·사용자 id가 코드에 없음. 모든 방문자가 같은 가게·같은 승인 목록·같은 붙여넣은 리뷰를 봄 |

승인 기록 파일 한 줄은 이런 모양입니다 (`1.6` 응답과 같은 칸): `draft_id`, `status`, `edited`, `text`, `approved_at`, `mode`.

### 3.2 예정 (아직 없음)

아래는 **계획**입니다. 기준 커밋에는 코드가 없습니다 (저장소의 파이썬 코드에서 `psycopg`, `sqlalchemy`, `asyncpg`, `sqlite3`, `postgres`, OCR 관련 글자를 찾았으나 없음. `services/` 아래에는 `review-insight`와 `web`뿐). 새 API의 경로와 모양은 정해지는 대로 이 문서에 더합니다. **지금 있는 API 9개의 경로와 칸 이름은 그대로 둡니다.**

| 예정 | 지금은 | 화면에 미칠 영향 |
|---|---|---|
| **DB(PostgreSQL)에 저장**: 승인 기록, 붙여넣은 리뷰, 가게별 주간·월간 보고서, 카드 추천 이유 | 위 3.1 표대로 메모리·파일 | 서버 안의 일이라 화면은 그대로여야 합니다. 예를 들어 서버를 다시 켜도 승인 목록(`GET /api/approvals`)이 남게 될 수 있습니다 (정해지지 않음) |
| **방문자를 구분하는 값** | 없음 | 방식(로그인·쿠키·토큰)은 정해지지 않았습니다. 정해지면 요청에 값을 싣는 방법이 바뀔 수 있습니다 |
| **보고서 API** (가게 주간·월간 보고서) | **연결됨 (11/15)**: 리뷰 분석 서비스의 일일·월간 응대 보고서를 `/api/care/report/*`로 (1.11절). 종합 리포트(`#/report`)에 보임. 주간 보고서·DB `reports` 표 저장은 아직 없음 | `#rp-*` |
| **상권 채팅** (`AI에게 묻기` 서랍) | **연결됨 (`feat/assistant-proxy`)**: 비서 화면 서버가 상권 서비스를 대신 불러 줌(1.10절). 서랍이 질문·선택지·근거 카드·대화 지우기를 함. 공식 상권 자료가 아직 없어 실제 숫자는 자료가 들어온 뒤에 나옴 | 서랍 안(`#assistant-*`)만 바뀜 |
| **캡처(OCR) 입력** | **연결됨 (11/15)**: 리뷰 붙여넣기 탭의 '캡처로 넣기' (1.11절, HCX-005가 옮겨 적고 사장님이 확인해 저장) | `#cap-*` |

### 3.3 지금 화면에 있는 빈 자리

**(1) 준비 중 메뉴 하나: `app.js`의 `LATER`** (11/15 '종합 리포트'는 진짜 화면이 되어 빠짐)

```js
const LATER = [
  { route: "market", long: "", short: "상권", desc: "가게 주변 상권 지표를 볼 화면이에요. …" },
];
```

(`desc`의 뒷부분은 줄여서 적음)

- `LATER` 목록에서 왼쪽 메뉴 링크(`#/market`)와 "회의에서 정한 뒤 넣을 자리입니다" 빈 화면을 만듭니다 (`mountLater()`).
- 메뉴에서는 "준비 중" 제목 아래에 나오고, 375px 폭에서는 제목이 숨고 "준비 중" 배지가 보입니다.
- 채우는 방법: `index.html`에 진짜 화면(`<section data-view="report">`)을 만들고, `LATER`에서 그 항목을 빼고, `ROUTES`에 이름을 넣습니다 (`app.js` 주석). 모양은 `style.css`의 '준비 중 자리' 한 덩어리입니다.
- 시험 4가 `LATER`의 `"상권"`, `준비 중`, `회의에서 정한 뒤 넣을 자리입니다`를 확인합니다. **자리를 채워서 `LATER`에서 항목을 빼면 이 시험도 같이 고쳐야 합니다** (11/15 종합 리포트 때 고침).
- 홈의 '상권 저녁 매출' 타일(`#stat-market`)과 카드 ⓑ의 근거가 지금 상권 지표를 보여 주는 곳입니다.

**(2) 'AI에게 묻기' 서랍 자리**

- 열고 닫는 버튼이 둘 있습니다. 상단 바의 `#ask-ai`와 홈 아래쪽 입력줄 모양의 `#ask-open`(배지 "준비 중"). 둘 다 `#assistant` 서랍을 엽니다. 닫을 때 연 버튼으로 포커스가 돌아갑니다. `Esc`로도 닫힙니다.
- 서랍 안: 제목, 닫기, 조건 줄, 대화 기록, 추천 질문 칩, 질문 입력칸 (상권 채팅이 연결됨. 2.2의 서랍 id 표와 1.10절)과 '보내기' 버튼(`disabled`).
- 질문을 보내거나 답을 받는 코드는 없습니다. 채팅 API가 정해지면 이 자리에 붙입니다 (3.2).
- 데스크톱에서는 오른쪽 380px 서랍, 375px 폭에서는 아래에서 올라오는 시트입니다.
- 참고: `index.html`과 `app.js`의 주석에는 이 버튼이 "숨겨져 있다"고 적혀 있지만, 지금 `index.html`에서 버튼은 숨겨져 있지 않습니다 (부록의 '알려진 특이점').

### 3.4 임시 DB 표 이름

설계 담당이 고칠 **출발점**입니다. 이름은 임시이고, 칸과 연결은 아직 정해지지 않았습니다. 오른쪽은 "지금 코드에서 이 표에 들어갈 후보가 되는 값"일 뿐 확정이 아닙니다.

| 임시 표 이름 | 담을 것 | 지금 코드에서 비슷한 것 |
|---|---|---|
| `stores` | 가게 | `StoreProfile`(`shared/contracts.py`: `store_id`, `name`, `business_type`, `business_type_name`, `channels`, `menu`, `data_origin`, `city`, `area_name`, `menu_prices`), `store.json` |
| `reviews` | 리뷰 (합성, 붙여넣은 것) | `ReviewRecord`의 앞 11칸(`review_id`, `store_id`, `text`, `created_at`, `channel`, `rating`, `input_method`, `pii_masked`, `order_ref`, `status`, `data_origin`), `reviews.json`, `pasted_(가게).json` |
| `review_labels` | 리뷰별 분류 결과 | `ReviewRecord`의 뒤 4칸(`sentiment`, `topics`, `negative_topics`, `urgency`)과 리뷰 분석 서버의 `classification`(`method`, `model`, `warnings`). 합성 정답표 `labels.json`과는 다른 것입니다. 무엇을 담을지는 설계 담당이 정합니다 |
| `reports` | 가게 주간·월간 보고서 | 없음 (새로 만듦) |
| `approvals` | 승인 기록 | `approvals.jsonl` 한 줄(`draft_id`, `status`, `edited`, `text`, `approved_at`, `mode`) |
| `card_reasons` | 카드 추천 이유 | `GET /api/cards`의 `card.reason_text`, `reason_source`, `checked_text`, `facts`, `evidence`, `problems`. 지금은 서버 메모리(`_reason_memo`)에만 있음 |

지금 쓰는 id 모양 (DB 설계 때 참고. 예시 값):

| id | 모양 | 예 |
|---|---|---|
| 가게 | `store_(이름)` | `store_ongi` |
| 리뷰 | `rv_(가게)_(번호)` / 붙여넣음 `rv_(가게)_paste_(번호)` | `rv_ongi_001`, `rv_ongi_paste_001` |
| 묶음 | `iss_(주제)` | `iss_missing_item` |
| 상권 지표 | `snap_(상권코드)_…` | `snap_3110826_evening_17_24_common_yoy_2026Q2` |
| 카드 | `card_(가게)_a` / `_b` | `card_ongi_a` |
| 글 | `d_(8자리)`. mock은 저장 예시의 값이 고정 | `d_d368820d` |

---

## 부록. 알려진 특이점, 코드에서 확인하지 못한 것

### 알려진 특이점

문서를 쓰다가 코드에서 발견한 것입니다. **코드는 고치지 않았습니다.** 화면을 다듬는 사람이 알아 두면 좋은 것을 앞에 두었습니다.

| # | 특이점 | 어디서 | 영향 |
|---|---|---|---|
| 1 | 카드의 `ⓐ`·`ⓑ` 표시가 카드 **위치** 기준입니다. 카드 ⓐ가 없고 홍보 카드만 있으면 홍보 카드가 `ⓐ`로 보임. 카드 id의 `_a`·`_b`는 종류 기준이라 서로 다름 | `app.js`의 `renderCards`, `renderDraft` | 카드가 하나뿐인 날 이름표가 어긋남. 카드 ⓐ가 없는 날은 시험(`test_no_repeated_issue_means_no_card_a`)이 다루는 정상적인 경우임 |
| 2 | 사용자가 잘못 입력한 경우(공백만 있는 글, 틀린 `channel`)가 `422`가 아니라 `503`("리뷰 분석 서비스 오류 400: …")으로 옴. 리뷰 분석 서버의 `400`을 비서 화면 서버가 `503`으로 바꿔 전달함 | `sources.py`의 `_json`, `demo.py`의 `paste` | 화면은 문장을 그대로 보여 주므로 사용자에게는 보임. 상태 코드만 어색함 |
| 3 | (고침) 붙여넣기 글자 수 검사가 비서 화면 서버만 4000자였음 | `main.py`의 `PasteIn` | main `d7c1305`에서 1000자로 맞춤. 지금은 1001자 이상이 `422` |
| 4 | 상권 지표 파일이 깨지면 `/api/health`는 `200`(+`snapshot.error`), `/api/briefing`·`/api/cards`는 `500`(일반 글자) | `demo.py`의 `health`와 `_state` | 화면이 "요청 실패 (500)"만 보임 |
| 5 | `POST …/approve`가 `draft_id`가 실제 글인지 확인하지 않고, 본문 `{}`도 받아 `text: null`로 기록함 | `demo.py`의 `approve` | 화면에서는 생기지 않는 경우 |
| 6 | 승인 기록 파일은 서버를 다시 켜도 읽지 않아 `GET /api/approvals`가 비게 됨. 같은 글을 다시 승인하면 파일에는 줄이 더 붙어 중복됨 | `demo.py`의 `approve`, `Demo.__init__` | DB로 옮길 때 같이 정리할 부분 |
| 7 | 승인 응답의 `warning`(기록 파일에 못 씀)을 화면이 보여 주지 않음 | `app.js`의 `approve` | 파일 쓰기가 실패해도 사장님은 모름 |
| 8 | mock은 `measures`의 틀린 id를 무시하고 `200`, live는 `400` | `demo.py`의 `run` | 시험용 실행에서는 안 걸리는 오류가 live에서 나옴 |
| 9 | 형식 오류(`422`)의 `detail[0].msg`가 영어이고 화면이 그대로 보여 줌 | `app.js`의 `api()` | 사용자에게 영어가 보일 수 있음 |
| 10 | 배달앱 이름이 `/api/briefing`의 `groups[].reviews[].channel`에서는 한국어(`"배민"`), `single_complaints[].channel`·`/api/insight`에서는 코드(`"baemin"`)임 | `demo.py`의 `briefing` | 화면에 보이는 곳은 한국어뿐이라 지금은 문제 없음 |
| 11 | `index.html`·`app.js` 주석은 'AI에게 묻기' 버튼이 숨겨져 있다고 적었지만, 지금 `index.html`의 버튼(`#ask-ai`)은 숨겨져 있지 않고 눌러서 빈 서랍을 열 수 있음 | `index.html` 상단, `app.js`의 `toggleAssistant` 위 주석 | 주석이 낡음 |

### 코드에서 확인하지 못한 것

- **live 모드의 응답**: 키가 없어 실행하지 않았습니다. `live`의 `POST …/run` 응답(글 id 모양, `needs_input`의 실제 내용, 걸리는 시간)은 코드로만 확인했고 값은 확인하지 못했습니다. 키 없이 `live`로 띄웠을 때의 `health`·`cards`·`run` 오류만 실제로 뽑았습니다.
- **다른 주소(origin)에서 API를 부를 때 브라우저가 막는지**: 코드에 CORS 설정이 없는 것만 확인했고, 실제 브라우저 동작은 실행하지 않았습니다.
- **화면이 브라우저에서 실제로 어떻게 보이는지**: 코드(`index.html`, `app.js`, `style.css`)를 읽었고 화면을 열어 보지는 않았습니다. 2.8의 '눈으로 확인할 것'은 코드에 있는 기능을 기준으로 적은 점검 목록입니다.
- **`classification.model`의 정확한 뜻**: 예시 값이 `"kiwi"`인 것만 확인했습니다.
- **캡처(OCR) 입력, 방문자 구분, 보고서 API, 상권 채팅의 방식과 위치**: 기준 커밋에 코드가 없어 계획 외에는 확인하지 못했습니다.
- **배포 계획서의 Nginx 설정이 `/static/…`을 어떻게 다룰지**: `docs/infra/architecture.md`에는 `/`와 `/api/`만 있습니다. `/static/…` 처리는 확인하지 못했습니다.
