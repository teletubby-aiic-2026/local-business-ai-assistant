# 텔레토비 AI 비서: API 설명서 겸 화면 안내서

> 대상: 비서 화면을 예쁘게 꾸미는 팀원(주현석)과 그 팀원이 쓰는 LLM
> 기준: main `d7c1305` (2026-11-14, PR #43 병합) · 작성일 2026-11-14
> 응답 예시는 그 직전 커밋 `28aed61`에서 뽑았습니다. 그 뒤 main에서 바뀐 것은 붙여넣기 글자 수 제한(4000 → 1000자)과 그 시험 1건뿐이고, 화면 파일 세 개는 같습니다.
> 이 문서는 코드를 읽고 실제 응답을 뽑아서 썼습니다. 코드는 바꾸지 않았습니다.
> **11/15 덧붙임 (`feat/connect-care-ui`)**: 고객응대 프록시 `/api/care/*`(1.11절), 리뷰 붙여넣기 탭의 '캡처로 넣기', 왼쪽 메뉴 '종합 리포트'(`#/report`)가 생겼습니다. 1.6(승인)·1.8(붙여넣기)에 선택 칸이 하나씩 늘었고, 2부의 id 표·개수·시험 표를 지금 코드에 맞춰 고쳤습니다.
>
> **11/16 덧붙임 (`feat/uxp-e-report`)**: 일일·월간 보고서 응답에 `praise` 칸(손님 칭찬 요약, 코드 집계)이 생겼고(1.11절), 종합 리포트에 '손님 칭찬 요약' 칸과 '전체 리포트 PDF 저장' 버튼, 인쇄 전용 CSS가 생겼습니다 (2.2·2.3·2.4·2.6절).
>
> **11/20 덧붙임 (`feat/f6-report`, 6차 회의)**: 종합 리포트를 Figma 06 'D1' 구성(주간·월간 탭, 계정별 저장)으로 바꿨습니다. 새 경로 `/api/reports/*`(1.17), 리뷰 분석 서비스의 주간 보고서 `report/weekly`와 월간 `compare=true`(1.11), DB `reports` 표의 `visitor_id`(3.4). 2.2·2.3·2.4·2.5·2.6·2.9의 종합 리포트 줄을 고쳤습니다.
>
> **11/20 덧붙임 (`feat/react-cutover-ux`)**: 화면을 React 18 + Vite 5(`services/web/frontend/`) 하나로 바꿨습니다 (PR #69 병합 뒤 예전 `services/web/web/static/` 삭제, 박건영 결정). 1부 API는 그대로이고, **2부는 React 화면 기준으로 새로 썼습니다.** 예전 화면의 id 목록·`app.js` 규칙은 git 이력(`d3113b0` 이전)에만 있습니다.

## 요약

이 서비스는 배달 음식점 사장님을 돕는 AI 비서입니다. 사장님은 밤 11시 브리핑에서 리뷰와 상권 숫자를 보고, 추천 카드 2장 중 하나를 고르고, AI가 쓴 답글·재발 방지 공지·쿠폰 홍보글을 고쳐서 승인합니다.

화면은 React 18 + Vite 5 앱(`services/web/frontend/`)이고, 서버(`services/web`)는 그 빌드(`frontend/dist`)와 JSON을 줍니다. 이 문서는 세 가지를 적었습니다.

1. **1부**: 서버가 주는 API 9개와 프록시 두 묶음(1.10 상권 채팅, 1.11 고객응대). 요청, 실제 응답 예시, 칸마다 뜻, 오류.
2. **2부**: 화면을 다듬을 때 **바꿔도 되는 것**과 **바꾸면 깨지는 것**. 바꾸면 화면이 멈추거나 서버 시험·화면 시험(vitest)이 깨집니다.
3. **3부**: 데이터가 지금 어디에 저장되는지, 앞으로 무엇이 바뀔 예정인지.

**쓰는 기술**: 화면은 React 18 + Vite 5 (상태 관리 라이브러리 없음, `useSyncExternalStore`), 서버는 FastAPI가 JSON과 화면 빌드를 줌. 11/20 박건영 결정으로 예전 '프레임워크 없이 HTML·CSS·JS' 방침을 바꿨습니다 (PR #69).

**로컬에서 띄우기** (키 없이 돎):

```bash
# 처음 한 번만, 저장소 루트에서
python3.11 -m venv .venv && .venv/bin/pip install -r services/web/requirements.txt -r services/review-insight/requirements.txt

# 키 없이 도는 시험용 실행 (화면 빌드가 없거나 오래되면 run.sh 가 먼저 npm ci·npm run build. Node.js 20 이상 필요)
APP_MODE=mock services/web/run.sh

# 브라우저에서 열기 (macOS. 다른 OS는 주소창에 http://localhost:8000 을 입력)
open http://localhost:8000

# API가 뜨는지 확인
curl -s http://localhost:8000/api/health
```

- `run.sh`가 리뷰 분석 서버(8020번 포트), 맞춤 마케팅 서버(8030번 포트), 비서 화면 서버(8000번 포트)를 같이 띄웁니다. 상권 공식 자료(`services/market-analysis/data/official`, git 밖 자료 묶음)가 있으면 상권 서비스(8766번 포트)도 띄웁니다 (11/20. 상권 파이썬은 `MARKET_PYTHON`, 상권 의존성은 `services/market-analysis/requirements.lock.txt`). `Ctrl+C`(또는 스크립트 `kill`)로 모두 끕니다. 맞춤 마케팅을 빼려면 `MARKETING_SURVEY_URL=off` (4부), 상권을 빼려면 `MARKET_URL=off`.
- `APP_MODE=mock`이면 키 파일이 있어도 모델(HCX)을 부르지 않습니다. 키가 없어도 됩니다.
- 화면 모양은 상단 바 버튼으로 시스템 → 밝게 → 어둡게를 고릅니다 (localStorage `ic26.theme`). 주소 뒤 `?theme=light|dark`는 그 화면에서만 고정합니다.
- 자동 API 문서는 `http://localhost:8000/docs`에 있습니다 (로컬에서만. 배포 계획서의 Nginx 설정은 `/docs`를 막음).

## 이 문서를 읽는 법

- 화면만 다듬는 사람은 **2부**를 먼저 보세요. API는 1부에서 찾아봅니다.
- LLM에게 맡길 때는 `services/web/frontend/`(특히 `src/`)와 이 문서를 함께 주고, 아래 상자를 먼저 읽히세요.

> **화면을 바꾸기 전에 지킬 규칙 (LLM에게 먼저 읽히세요)**
>
> 1. 화면 소스는 `services/web/frontend/src/`입니다. 서버는 빌드(`frontend/dist`)의 `index.html`을 `/`로, 빌드 파일을 `/assets/…`로 줍니다. 그림은 SVG를 JSX로 넣거나 `src/` 안에서 import 합니다 (외부 CDN 없음).
> 2. 화면 주소 8개(`#/today` `#/cards` `#/draft` `#/done` `#/analysis` `#/marketing` `#/report` `#/market`)와 API 경로·요청·응답 칸 이름은 바꾸지 않습니다. API가 더 필요하면 서버 담당(박건영)에게 요청하세요.
> 3. 서버 시험이 글자로 읽는 곳이 있습니다 (2.4 표): `features/flow/calc.js`의 점검 상태 규칙·`REPLACES_MAX`, `features/assistant/chat.js`의 `CHAT_QUARTER`·`CHAT_STARTERS`(서랍 첫 추천 질문, `assistant/state.js`가 가져다 씀), `components/Sidebar.jsx`의 메뉴 글자('상권 분석' 등), `App.jsx`·`lib/router.js`·`Sidebar.jsx`의 화면 주소, `features/marketing/logic.js`의 `MKT_SUB`, `features/analysis/calc.js`의 `PASTE_SAMPLES`·`AN_TABS`, `lib/domain.js`의 `GEN_NAMES`. 이름이나 위치를 바꾸면 서버 시험이 깨집니다.
> 4. `frontend/src`와 `frontend/index.html`(주석 포함)에 `replay`, `c9`, `/api/review-insight` 같은 글자가 들어가면 시험이 깨집니다. SVG 경로 데이터에 `c9`가 우연히 들어가는 경우를 조심하세요.
> 5. 서버가 준 글은 JSX로만 넣습니다 (`dangerouslySetInnerHTML` 쓰지 않음).
> 6. 색·글자 크기·간격은 `src/styles/tokens.css` 변수를 씁니다. 변수만 쓰면 밝게·어둡게가 저절로 맞습니다.
> 7. 정직 표시(실제 AI 결과 아님, 합성 데이터, 서울시 출처·기준 분기, 우리 가게 매출 아님, 되돌릴 수 없어요)는 지우지 않습니다. 한 화면에 같은 표시가 여러 번이면 한 곳으로 모읍니다.
> 8. 바꾼 뒤 `npm test`·`npm run build`와 서버 시험을 돌립니다 (2.8).

## 목차

- 0. 먼저 알아 둘 것
  - 0.1 서버가 네 개 있어요 · 0.2 모드가 두 가지예요 · 0.3 응답 예시는 이렇게 뽑았어요 · 0.4 이 문서의 말 · 0.5 모든 API에 해당하는 규칙
- 1부. API 9개
  - 1.0 한눈에 보기
  - 1.1 `GET /api/health` · 1.2 `GET /api/briefing` · 1.3 `GET /api/insight` · 1.4 `GET /api/cards`
  - 1.5 `POST /api/cards/{card_id}/run` · 1.6 `POST /api/drafts/{draft_id}/approve` · 1.7 `GET /api/approvals` · 1.7.1 `DELETE /api/approvals`
  - 1.8 `POST /api/reviews` · 1.9 `DELETE /api/reviews/pasted`
  - 1.10 `/api/assistant/*` (상권 채팅 서랍. 상권 서비스 프록시)
  - 1.11 `/api/care/*` (캡처 입력·응대 점수·보고서. 리뷰 분석 서비스의 고객응대 프록시)
  - 1.12 `/api/marketing-survey/*` (맞춤 마케팅 프록시. 김수현 님 설문형 마케팅 서비스를 중계, 11/16)
  - 1.13 `/api/auth/*` (로그인·가게 고르기, 5차 회의 11/18) · 1.14 `/api/market/*` (상권 분석 화면 프록시, 11/18)
  - 1.15 서랍의 전 파트 질문과 화면 이동 버튼 (11/18)
  - 1.16 `/api/account/*` — 계정 안의 가게와 사장님 프로필 (6차 회의 11/20)
  - 1.17 `/api/reports/*` (종합 리포트의 주간·월간 보고서 저장, 11/20)
- 2부. 화면을 다듬을 때 유지해야 하는 것
  - 2.1 폴더와 서빙 · 2.2 상태와 화면 전환 · 2.3 공통 부품과 디자인 토큰
  - 2.4 시험이 지키는 것 · 2.5 화면 주소 · 2.6 화면 흐름과 부르는 API
  - 2.7 자유롭게 바꿔도 되는 것 · 2.8 바꾼 뒤 확인하는 법 · 2.9 왼쪽 메뉴 · 서랍 · 폭 기준
- 3부. 데이터가 어디에 저장되나, 무엇이 바뀔 예정인가
  - 3.1 지금 · 3.2 예정(아직 없음) · 3.3 화면의 빈 자리 (11/20 없음) · 3.4 임시 DB 표 이름
- 4부. 맞춤 마케팅 서비스 자체 API · 실행 · 배포 (11/16)
  - 4.1 한눈에 · 4.2 경로 · 4.3 `visitor_id` · 4.4 기록 파일 · 4.5 `DELETE /records` · 4.6 `/health` · 4.7 모드 · 4.8 실행 · 4.9 배포
- 부록. 알려진 특이점, 코드에서 확인하지 못한 것

---

## 0. 먼저 알아 둘 것

### 0.1 서버가 네 개 있어요

| 이름 | 폴더 | 포트 | 하는 일 |
|---|---|---|---|
| 비서 화면 서버 | `services/web` | 8000 | 화면 파일과 이 문서의 API 9개를 줍니다. |
| 리뷰 분석 서버 | `services/review-insight` | 8020 (같은 컴퓨터 안쪽) | 리뷰를 보관하고 분류하고 묶습니다. 비서 화면 서버가 대신 부릅니다. **브라우저는 직접 부르지 않습니다** (시험이 막음, 2.4). |
| 맞춤 마케팅 서버 | `experiments/marketing` (`marketing_survey.server:app`) | 8030 (같은 컴퓨터 안쪽) | 설문형 맞춤 마케팅(맞춤 홍보 제안·남은 재료·광고비 점검·가게 이야기 글·쿠폰 결과, 마케팅 보고서). 비서 화면 서버가 `/api/marketing-survey/*`로 대신 부르고 가게·방문자는 서버가 붙입니다 (1.12, 4부). 꺼져 있어도 `#/marketing` 화면에만 안내가 뜹니다. |
| 상권 서버 | `services/market-analysis` | 8766 (같은 컴퓨터 안쪽) | 오른쪽 서랍의 상권 채팅. 비서 화면 서버가 `/api/assistant/*`로 대신 부릅니다 (1.10). |

비서 화면 서버는 리뷰 분석 서버가 꺼져 있으면 대부분의 API에서 `503`을 줍니다 (1.2~1.5, 1.8, 1.9).

### 0.2 모드가 두 가지예요

환경변수 `APP_MODE`로 정합니다. `replay`(발표 모드)는 없어졌고, 쓰면 서버가 오류로 멈춥니다.

| | `mock` (시험용 실행) | `live` (실시간) |
|---|---|---|
| 키 | 필요 없음 | HCX-005 키 필요 (호출마다 비용) |
| 추천 카드 이유 문장 | 고정 문장 | HCX-005가 쓰고, 규칙 검사를 못 넘으면 고정 문장 |
| 글(답글·공지·홍보글) | 미리 저장된 예시 파일(`experiments/marketing/c6/replay/c6_cache_best.json`)을 이 카드에 맞게 바꿔 보여 줌. **실제 AI 결과가 아님** | HCX-005가 실시간으로 씀. 파일에 저장하지 않음 |
| 화면 맨 위 띠 | 서버가 `health.mode_notice`("시험용 실행 · 키 없이 저장된 예시 결과를 보여 줍니다 (실제 AI 결과 아님)")를 주고, 화면은 그 칸이 있으면 상단 안내 띠에 짧은 한 줄 "시험용 예시 화면 · 실제 AI 생성 결과가 아니에요"(`src/lib/domain.js`의 `MODE_BAND_MOCK`)를 띄움 | 없음 |

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
| 글 종류 3가지 | `reply_draft`(답글), `prevention_notice`(포장·주문 안내문), `coupon_promo`(쿠폰 홍보글). 화면 이름은 `src/lib/domain.js`의 `GEN_NAMES`. 11/18부터 `prevention_notice`의 화면 이름은 '재발 방지 공지'가 아니라 **'배달앱 포장·주문 안내문'**(짧게 '포장·주문 안내문')입니다(반성문처럼 읽히지 않게, 김수현 님 동의). 내부 이름·API 칸·점검 이름은 그대로입니다. |
| 묶음 · 반복 | 같은 불만이 2건 이상이면 **묶음**, 3건 이상이면 **반복**입니다 (화면 문구 기준). |
| 상권 지표 | 서울시 상권분석 자료에서 뽑은 숫자 한 줄 (예: 저녁 시간대 추정매출 변화율). 코드 이름은 `snapshot`. |
| 합성 데이터 | 실제 가게가 아니라 만들어 낸 리뷰·가게. 지금 화면의 리뷰는 모두 합성입니다. |
| 시험용 실행 | `APP_MODE=mock`. 위 0.2 참고. |
| 근거 카드 | 이유 문장을 쓸 때 모델과 검사기에 넘기는 사실 한 줄 (`F1` 불만 묶음, `F2` 상권 지표, `F3` 손님 칭찬). 화면에는 안 보입니다. |

응답 안의 `c6`, `c7`, `C4` 같은 글자는 이렇게 읽습니다. `c6`는 글을 만드는 코드(`experiments/marketing/c6`), `c7_flags`는 **이 비서 화면 서버**가 글에서 찾아내는 확인 필요 문구, `C4`는 상권 지표 파일입니다.

### 0.5 모든 API에 해당하는 규칙

- **주소와 형식**: 모두 같은 서버(8000번)의 `/api/…`입니다. 요청과 응답은 JSON(UTF-8)입니다. 본문이 있는 요청은 `Content-Type: application/json`으로 보냅니다 (`src/lib/api.js`의 `api()`는 모든 요청에 이 헤더를 붙임).
- **로그인·토큰 없음**: 비서 화면 서버는 인증을 하지 않습니다. CORS 설정도 없습니다. 화면과 API를 **같은 주소(origin)** 에서 받는 것이 전제입니다 (`main.py`에 CORS 설정이 없음을 확인함. 다른 포트에서 부르면 브라우저가 막는지는 실행해 보지 않아 확인하지 못함).
- **가게는 하나**: 서버 설정 `DEMO_STORE_ID`(기본 `store_ongi`)로 고정입니다. 요청에 가게를 고르는 칸이 없습니다.
- **시각**: 한국 시간 ISO 8601입니다 (`2026-11-14T19:19:46+09:00`).
- **칸 이름은 영어(snake_case), 화면에 보이는 글은 한국어**입니다.

**오류 응답은 모양이 네 가지입니다.**

| 모양 | 언제 | 본문 | 화면이 보여 주는 것 |
|---|---|---|---|
| ① 이 서버가 직접 만든 오류 | 리뷰 분석 서버 문제, 카드 id 틀림, 글 만들기 실패 | `{"error": {"message": "…"}}` | `error.message` 그대로 (맨 위 알림 띠 또는 붙여넣기 메시지) |
| ② 요청 형식 오류 | 본문이 없거나 칸의 형식·범위가 틀림 | `{"detail": [{"type", "loc", "msg", "input", …}]}` (FastAPI 기본, **`msg`는 영어**) | `detail[0].msg` 그대로 (영어로 보임) |
| ③ 허용하지 않는 메서드 | 예: `GET /api/cards/x/run` | `{"detail": "Method Not Allowed"}` | `요청 실패 (405)` |
| ④ 예기치 못한 오류 | 코드가 처리하지 못한 오류 (예: 상권 지표 파일이 깨짐) | 일반 글자 `Internal Server Error` (JSON 아님) | `요청 실패 (500)` |

화면은 `error.message`, `detail[0].msg`, `요청 실패 (코드)` 순서로 문장을 고릅니다 (`src/lib/api.js`의 `api()`. 프록시를 부르는 `careApi`·`mktApi`·`drawerApi` 등은 `error.message`가 없으면 `detail[0].msg`(영어) 대신 각자 정한 한국어 문장을 씀, 2.6).

**상태 코드**

| 코드 | 쓰이는 곳 |
|---|---|
| `200` | 성공 (대부분) |
| `201` | `POST /api/reviews` 성공 |
| `400` | `live`에서 글 만들기 실패 (키 없음, 모르는 재발 방지 조치 등). 개별 다시 만들기(1.5)에서 그 카드가 만들지 않는 글 종류를 보냄, 답글인데 `review_id`가 없음. `replaces`(1.5)가 20개를 넘거나 id 모양이 틀림 |
| `404` | 카드 id가 지금 화면의 카드가 아님, 저장 예시가 이 카드에 안 맞음. 개별 다시 만들기(1.5)에서 그 리뷰가 이 카드의 답글 대상이 아님 |
| `405` | 허용하지 않는 메서드 |
| `422` | 요청 형식·범위 오류 |
| `500` | 예기치 못한 오류 |
| `502` | `live`에서 글을 만들다가 HCX 호출 쪽에서 예상 못한 오류가 남 (11/14. 화면 알림 띠로 보임. 다시 누르면 됨) |
| `503` | 리뷰 분석 서버에 연결하지 못함 또는 그 서버가 오류를 돌려줌. 승인 기록 지우기(1.7.1)에서 저장소(DB)에 닿지 못함 |

---

## 1부. API 9개

### 1.0 한눈에 보기

경로 9개는 `services/web/web/main.py`와 같습니다. **11/16 덧붙임**: 승인 기록을 지우는 `DELETE /api/approvals`(7-1, 1.7.1절)가 생겨 지금은 10개입니다. 5번은 본문에 `generator`를 보내면 글 한 건만 다시 만듭니다(1.5절 '개별 다시 만들기').
이 표 밖에 다른 서비스를 대신 불러 주는 프록시가 넷 있습니다: 상권 채팅 `/api/assistant/*`(1.10), 고객응대 `/api/care/*`(1.11), **맞춤 마케팅 `/api/marketing-survey/*`(1.12, 11/16)**, **상권 분석 화면 `/api/market/*`(1.14, 11/18)**. 로그인·가게 고르기는 `/api/auth/*`(1.13, 11/18), 종합 리포트의 주간·월간 보고서 저장은 `/api/reports/*`(1.17, 11/20)입니다.

**11/18 5차 회의 뒤 모든 경로에 해당하는 것**: 로그인하지 않으면 예전과 같습니다(가게 `store_ongi`, 방문자는 쿠키 `visitor_id`). 로그인하면 이 서버가 요청마다 가게를 세션의 '고른 가게'로, 방문자 id 를 `u-<user_id>`로 바꿔서 위 표와 네 프록시의 아래 서비스에 똑같이 넘깁니다. 응답 모양은 같고, 담긴 가게만 다릅니다(브리핑의 `store`, 카드, 승인 기록 등). 화면은 가게 id 를 보내지 않습니다.

| # | 메서드와 경로 | 하는 일 | 쓰는 화면 | 성공 |
|---|---|---|---|---|
| 1 | `GET /api/health` | 서버 상태, 시험용 여부, 막힌 곳 | 맨 위 시험용 안내 띠·알림 띠, 바닥 '자료 출처' 줄 | 200 |
| 2 | `GET /api/briefing` | 오늘의 브리핑 (숫자, 묶음, 리뷰 원문, 상권 지표) | 홈 `#/today`, 상단 가게 이름 | 200 |
| 3 | `GET /api/insight` | 리뷰 분석 (감정·주제 건수, 묶음), 읽기 전용 | 리뷰 분석 `#/analysis` | 200 |
| 4 | `GET /api/cards` | 오늘의 추천 카드 최대 2장 | 추천 카드 `#/cards`, 홈 '오늘 할 일' | 200 |
| 5 | `POST /api/cards/{card_id}/run` | 카드에 맞는 글 만들기. 본문에 `generator`가 있으면 그 글 한 건만. `replaces`(옛 글 id)를 보내면 만든 뒤 그 승인 기록을 지움 (11/16) | 카드 버튼, 홈 '오늘 할 일', 초안 '카드 전체 다시 만들기' · 초안 상자의 '다시 만들기'(한 건) | 200 |
| 6 | `POST /api/drafts/{draft_id}/approve` | 글 승인 기록 | 초안 `#/draft` '승인' | 200 |
| 7 | `GET /api/approvals` | 서버의 승인 기록 목록 | 처리 완료 `#/done` '서버 처리 기록' | 200 |
| 7-1 | `DELETE /api/approvals` | 이 방문자의 승인 기록 지우기 (11/16) | 처리 완료 `#/done` '처음부터 다시' | 200 |
| 8 | `POST /api/reviews` | 리뷰 한 건 붙여넣기, 바로 분류 | 리뷰 분석 '리뷰 넣기' 탭 (붙여넣기·캡처 저장) | 201 |
| 9 | `DELETE /api/reviews/pasted` | 붙여넣은 리뷰 모두 지우기 | 같은 탭 '붙여넣은 리뷰 지우기' | 200 |

표의 "화면" 칸은 화면 소스(`services/web/frontend/src`)가 그 값을 읽어 쓰는 곳입니다 (11/20 React 기준으로 다시 맞춤. 함수·파일 위치는 2.6). "안 씀"은 응답에는 있지만 지금 화면이 읽지 않는다는 뜻입니다. 읽지 않아도 칸 이름은 바꾸지 않습니다 (다른 도구가 읽을 수 있음).

---

### 1.1 `GET /api/health`

**하는 일**: 서버가 어떤 모드인지, 어디까지가 진짜이고 어디부터 시험용인지, 막힌 것이 있는지를 알려 줍니다.
**쓰는 화면**: 페이지를 열 때 한 번(`src/state/boot.js`). 맨 위 시험용 안내 띠(`App.jsx`의 `.mode-band`), 알림 띠(`healthProblems`), 바닥 '자료 출처' 줄(`footer.honesty`, `honestyItems`).

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
| `mode_notice` | mock일 때 띠에 보일 문장. live이면 `null` | 값이 있으면 상단 안내 띠가 보임 (글은 서버 문장 대신 짧은 `MODE_BAND_MOCK`, 0.2). `null`이면 띠 없음. 종합 리포트 인쇄 머리글에는 이 문장 그대로, 맞춤 마케팅은 이 값이 있으면 자기 예시 고지를 겹쳐 띄우지 않음 |
| `store_id` | 이 서버가 다루는 가게 id | 안 씀 |
| `key_present` | HCX 키가 설정돼 있는지 (키 값은 주지 않음) | 안 씀 |
| `c6_available` | 글 만드는 코드(`experiments/marketing/c6`)를 불러올 수 있는지 | 안 씀 |
| `seed_available` | 저장 예시 파일(`c6_cache_best.json`)이 있는지 | 안 씀 |
| `review_service` | 리뷰 분석 서버 상태. 켜져 있으면 그 서버의 `/api/health` 응답에 `url`을 더한 것. 꺼져 있으면 `{"url", "status": "down", "error": "ConnectError"}`. 응답이 200이 아니면 `status`가 `"http 500"` 같은 글자 | `status`가 `"down"`이면 경고 띠에 "리뷰 분석 서비스(주소)가 꺼져 있어요." |
| `review_service.status` · `mode` · `spec_version` · `token_required` · `models.review_classify` · `data_origin` | 켜져 있을 때 리뷰 분석 서버가 알려 주는 칸: `status`(`"ok"`), `mode`(그 서버의 모드), `spec_version`, `token_required`(접근 토큰이 필요한지), `models.review_classify`(분류에 쓰는 것. mock이면 `"rule"`), `data_origin` | 안 씀 (`models.review_classify`는 `parts.briefing`의 "리뷰 분류: rule"로 보임) |
| `snapshot` | 상권 지표 파일 정보. `file`(이름), `count`(지표 수), `error`(읽기 오류 문장 또는 `null`) | 안 씀 |
| `dev_fake_snapshots` | 개발용 가짜 지표의 id 목록 (`note`가 "개발용 가짜 값"으로 시작하는 지표) | 하나라도 있으면 경고 띠 맨 앞에 "개발용 가짜 지표가 화면에 있어요…" |
| `blocking` | 막힌 이유 문장 목록. 비어 있으면 정상 | 경고 띠에 이어 붙여 보여 줌 |
| `parts` | 바닥 줄에 쓸 수 있는 네 줄 (`reviews`, `briefing`, `cards`, `generate`) | 바닥 '자료 출처' 줄에 `리뷰: …`(늘)와 `글 생성: …`(`mode_notice`가 없을 때만) 두 개만. `briefing`·`cards`는 안 씀 (분류 방식·규칙 같은 안쪽 사정은 화면에 적지 않음, 11/20) |

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
| `store.name` · `store.business_type_name` · `store.area_name` | 가게 이름, 업종 이름, 상권 이름 | 상단 바 가게 칸: 이름(`#store-name`)과 그 아래 "업종 · 상권이름 상권" (`storeLine`) |
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

주제 id와 화면에 보이는 이름 (`src/features/analysis/calc.js`의 `TOPIC_NAMES`. 모르는 id는 id가 그대로 보임):

| id | 이름 | id | 이름 | id | 이름 |
|---|---|---|---|---|---|
| `texture` | 식감 | `taste` | 맛 | `portion` | 양 |
| `price` | 가격 | `delivery_time` | 배달 시간 | `temperature` | 음식 온도 |
| `packaging` | 포장 상태 | `missing_item` | 포장 누락 | `service` | 응대 |
| `hygiene` | 위생 | `menu` | 메뉴 구성 | `atmosphere` | 매장 환경 |
| `wait_time` | 매장 대기 | | | | |

감정 이름 (같은 파일의 `SENTIMENT_NAMES`): `positive` 긍정, `negative` 부정, `neutral` 중립, `mixed` 긍정·부정 섞임.

**오류**: `503` 리뷰 분석 서버 문제 (모양은 1.2의 `503` 예시와 같음). `405` `POST`·`DELETE`로 부름.

**참고**: `/api/briefing`의 `groups`와 겹치지만 칸이 다릅니다. 홈은 briefing, 리뷰 분석 화면은 insight를 씁니다.

---

### 1.4 `GET /api/cards`

**하는 일**: 오늘 띄울 추천 카드를 **규칙으로** 정해 줍니다 (최대 2장). 이유 문장과 근거도 같이 줍니다.

- 카드 ⓐ(불만 대응): `top_issue_id`가 가리키는 묶음. 반복 묶음이 없으면 만들지 않습니다.
- 카드 ⓑ(쿠폰 홍보): 상권 지표를 고정된 우선순위(환경변수 `CARD_B_SNAPSHOT_ID` → `snap_evening_sales_yoy` → 단위가 `%`인 첫 '추정매출' 지표)로 **먼저 하나 고르고**, 그 값이 기준(`CARD_B_THRESHOLD`, 기본 -5) 이하일 때만 만듭니다. 고른 지표가 하락이 아니면 다른 지표를 찾지 않습니다.
- 카드 ⓑ의 손님 칭찬 근거 (11/16): 가격 있는 메뉴 가운데 **손님 칭찬 리뷰에 가장 많이 언급된 메뉴**를 쿠폰 메뉴로 고르고, 그 메뉴와 언급 건수를 제목·이유 문장·근거 카드(`F3`)·근거(`evidence`의 `type: "praise"`)에 붙입니다. 칭찬 리뷰는 감정 분류가 긍정인 리뷰입니다 (분류가 하나도 없으면 별점 4점 이상이면서 불만 주제가 없는 리뷰). 같은 수면 메뉴판 순서가 앞선 메뉴입니다. 글 만드는 코드(`c6/promo.py`)도 같은 함수(`shared/praise.py`의 `pick_praised_menu`)로 쿠폰 메뉴를 고르므로 **카드가 말한 메뉴와 홍보글의 쿠폰 메뉴가 같습니다**.
  - 사실대로 씁니다: 메뉴판 전체에서 혼자 가장 많이 언급된 메뉴일 때만 "…언급이 3건으로 가장 많아요."라고 쓰고, 같은 수의 메뉴가 있거나 가격 없는 메뉴가 더 많이 언급됐으면 "…언급이 1건 있어요."라고만 씁니다.
  - 칭찬 리뷰에 그 메뉴 언급이 없으면 (또는 리뷰를 계약 형식으로 바꾸지 못하면) 칭찬 근거 없이 예전 카드 그대로입니다 (`F2`만, 제목 "… 하락 → 쿠폰 홍보", `review_ids`는 `[]`).
  - mock의 홍보글은 저장 예시(쿠폰 메뉴 '제육볶음 정식')입니다. 붙여넣은 칭찬 리뷰 때문에 고른 메뉴가 저장 예시의 메뉴와 달라지면, mock에서는 칭찬 근거를 붙이지 않습니다 (카드가 저장 예시와 다른 메뉴를 말하지 않게). live는 고른 메뉴로 홍보글을 새로 씁니다.
- 이유 문장: mock은 고정 문장입니다. live는 HCX-005가 한 문장을 쓰고, 규칙 검사를 못 넘으면 고정 문장으로 돌아갑니다. 칭찬 근거가 붙은 카드 ⓑ는 live에서 **모델이 상권 지표 문장과 할 일 문장만 쓰고, 칭찬 근거 한 줄(메뉴·건수)은 코드가 그 사이에 끼워 넣습니다**. 모델에게 두 근거를 함께 주면 "제육볶음 정식 매출이 19.31% 감소"처럼 섞어 쓴 문장이 검사를 통과했기 때문입니다 (11/16 실시간 확인). 그래서 `reason_source`가 `"HCX-005 (검사기 통과)"`여도 칭찬 근거 줄은 코드가 쓴 글입니다.
  - 끼우는 줄의 말끝 (11/16): 줄 끝에 마침표를 넣고(인용 표시는 마침표 앞, `…1건 있어요 [F3].` → 화면에서는 `…1건 있어요.`), 말투는 모델 문장을 따릅니다. 모델 문장의 문장 끝이 모두 `-니다`(합니다체)면 `…1건 있습니다.`·`…가장 많습니다.`, 해요체이거나 섞여 있거나 끝말로 알 수 없으면(`…19.31% 감소.`) 화면 기본인 해요체 `…1건 있어요.`·`…가장 많아요.`입니다 (`cards.speech_level`). 고정 문장은 늘 해요체입니다. 이 규칙이 바뀌어 저장해 둔 이유 문장의 열쇠(`demo.REASON_VERSION`)를 `reason-v3`로 올렸습니다 (예전 문장은 다시 쓰지 않음).

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
      "title": "포장 누락 3건 반복 → 배달앱 포장·주문 안내문 + 답글",
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
        "reason_text": "장승배기역 4번 상권의 저녁 시간대(17~24시) 추정매출(두 분기 공통 업종): 2026년 2분기, 전년 동기 대비 19.31% 감소\n손님 칭찬 리뷰에 제육볶음 정식 언급이 1건 있어요.\n저녁 손님을 다시 부르는 제육볶음 정식 쿠폰 홍보를 제안해요.",
        "review_ids": ["rv_ongi_013"],
        "snapshot_ids": ["snap_3110826_evening_17_24_common_yoy_2026Q2"]
      },
      "title": "저녁 시간대(17~24시) 추정매출(두 분기 공통 업종) 하락 → '제육볶음 정식' 쿠폰 홍보",
      "reason_source": "고정 문장",
      "checked_text": "장승배기역 4번 상권의 저녁 시간대(17~24시) 추정매출(두 분기 공통 업종): 2026년 2분기, 전년 동기 대비 19.31% 감소 [F2]\n손님 칭찬 리뷰에 제육볶음 정식 언급이 1건 있어요 [F3].\n저녁 손님을 다시 부르는 제육볶음 정식 쿠폰 홍보를 제안해요.",
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
| `cards[].card.card_id` | 카드 id (`card_ongi_a`, `card_ongi_b`). `POST …/run`의 경로에 씀 | 카드 버튼(`choose(card_id)`), 글 보관 키(`results`) |
| `cards[].card.store_id` | 가게 id | 안 씀 |
| `cards[].card.kind` | `"complaint"`(불만 대응) 또는 `"promo"`(쿠폰 홍보) | 카드 이름, 담당 AI 직원 이름, 버튼 글자 |
| `cards[].card.reason_text` | 카드를 띄운 이유 문장. 줄바꿈(`\n`)이 들어갈 수 있음 | 카드 본문. **11/20 React 카드(`Cards.jsx`)에는 줄바꿈을 살리는 `white-space: pre-line`이 없어 `\n`이 띄어쓰기처럼 보임** (예전 화면은 살렸음. 종합 리포트 마케팅 요약 `.rp-mkt-reason`은 살림. 부록 12) |
| `cards[].card.review_ids` | 근거 리뷰 id. 카드 ⓐ는 묶음의 불만 리뷰, 카드 ⓑ는 쿠폰 메뉴를 언급한 칭찬 리뷰 **전부** (칭찬 근거가 없으면 `[]`) | 카드가 바뀌었는지 비교 (칭찬 근거가 바뀌면 만들어 둔 홍보글도 버림), 카드 ⓑ의 칭찬 리뷰 건수 |
| `cards[].card.snapshot_ids` | 근거 상권 지표 id (카드 ⓑ) | 위와 같음 |
| `cards[].title` | 카드 제목. 카드 ⓑ는 칭찬 근거가 있으면 쿠폰 메뉴가 들어감 (`… 하락 → '제육볶음 정식' 쿠폰 홍보`), 없으면 `… 하락 → 쿠폰 홍보` | 카드 제목, 초안 화면 제목 |
| `cards[].reason_source` | 이유 문장 출처. `"고정 문장"`, `"HCX-005 (검사기 통과)"`, `"HCX-005 검사 불통과 → 고정 문장"`, `"HCX-005 실패(오류이름) → 고정 문장"`, `"고정 문장 (검사기 경고)"` | `HCX`가 들어 있고 `고정 문장`이 없을 때만 '근거 보기' 안에 "카드 설명 글은 AI가 썼어요." (`flow/calc.js`의 `reasonByAI`. 검사기 이야기는 화면에 적지 않음) |
| `cards[].checked_text` | 검사기를 통과한 문장 (`[F1]` 같은 근거 표시 포함) | 안 씀 |
| `cards[].facts[]` | 이유 문장의 근거 카드 `{id, topic, status, text, values[{label, value, unit}], keep[]}`. 카드 ⓑ의 `F3`(손님 칭찬)에는 글자 값(`{label: "쿠폰 메뉴", value: "메뉴 이름"}`, `unit` 없음)이 하나 더 있고, 혼자 1등이 아니면 `avoid[]`(이유 문장에 쓰면 안 되는 말: 가장·제일·최다·1위)가 붙음 | 안 씀 |
| `cards[].evidence[]` | 근거. 불만 리뷰면 `{type:"review", id, text}`, 상권 지표면 `{type:"snapshot", id, text, basis, note}`, 쿠폰 메뉴를 칭찬한 리뷰면 `{type:"praise", id, text, menu, rating}` (카드 ⓑ, 최대 3건, `text`는 120자까지) | 카드의 '근거:' 줄과 '근거 보기' (`basis`의 주소는 '원본' 링크로), 홍보글 초안의 '근거 지표'·'손님 칭찬 리뷰' 두 덩어리, 홈 '오늘 할 일'의 홍보글 부제(`menu`) |
| `cards[].problems[]` | 모델 문장이 검사에 걸린 이유 (`{type, detail?}`). 없으면 `[]` | 안 씀 (11/20부터. 예전 화면은 '근거 보기' 안 "검사기 지적 n건") |
| `cards[].measures` | 카드 ⓐ만: 재발 방지 조치 상자. `options[]`(`{id, text}`, 글 만드는 코드의 목록 `M1`~`M5`)와 `default`(처음 체크할 id 목록). 카드 ⓑ와 글 만드는 코드를 못 불러올 때는 `{}` | 카드 ⓐ의 체크박스 묶음 |
| `no_card_b` | 카드 ⓑ가 없을 때 그 이유 문장. 카드 ⓑ가 있으면 `null` | 추천 카드 화면 아래 한 줄 (`Cards.jsx`, 상태의 `noCardB`) |

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

**쓰는 화면**: 추천 카드의 버튼(`flow/actions.js`의 `choose` → `runCard`), 홈 '오늘 할 일' 항목(아직 안 만든 글, `runTodo`), 초안 화면 진행줄 옆의 '카드 전체 다시 만들기'(`rerunCard`). 초안 상자 안의 '다시 만들기'(`regenDraft`)는 같은 경로에 `generator`를 보내 **그 글 한 건만** 다시 만듭니다 (아래 '개별 다시 만들기').

**요청**: `POST /api/cards/{card_id}/run`

- `card_id`: `GET /api/cards`가 준 `card.card_id` (예: `card_ongi_a`). 지금 화면의 카드가 아니면 `404`.
- 본문은 **없어도 됩니다**. 카드 ⓐ에 재발 방지 조치 상자가 있으면 화면은 체크된 id를 이렇게 보냅니다.

```json
{"measures": ["M1"]}
```

| 칸 | 형식·범위 | 뜻 |
|---|---|---|
| `measures` | 문자열 목록, 또는 생략·`null` | 사장님이 고른 재발 방지 조치 id. 허용값은 그 카드의 `measures.options[].id` (`M1`~`M5`). 생략·`null`이면 카드의 `measures.default`를 씀. `[]`이면 고른 것 없음 |
| `replaces` | 문자열 목록(20개 이하), 선택 (11/16) | 이 생성으로 바뀌는 **옛 글 id**(`drafts[].draft_id`). 아래 '옛 글의 승인 기록 지우기' |

- mock은 글을 바꾸지 않습니다(저장 예시 그대로). 다만 **11/16부터** 응답의 `chosen_measures`에는 사장님이 고른 조치를 싣습니다 (화면이 '오늘부터 실천할 주방 점검 수칙'으로 보여 줌). 틀린 id(`"M9"`)는 오류 없이 뺍니다 (확인함). 저장 예시 글이 그 조치를 담고 있다는 뜻은 아닙니다.
- live는 모르는 id를 보내면 `400` ("모르는 주방 점검 수칙이에요: M9". 11/18 전 문구는 "모르는 재발 방지 조치예요"). 카드 ⓑ는 `measures`를 쓰지 않습니다.
- 고른 조치는 **재발 방지 공지**에 들어갑니다. 고르지 않은 조치를 글이 지어내면 점검에서 걸립니다. 답글은 고른 조치와 상관없이 글 만드는 코드가 늘 `M1`(주문서 대조) 문장을 붙입니다 (`c6/reply.py`). 그래서 화면은 "공지에 반영"이라고만 적습니다.

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
  "reason_text": "장승배기역 4번 상권의 저녁 시간대(17~24시) 추정매출(두 분기 공통 업종): 2026년 2분기, 전년 동기 대비 19.31% 감소\n손님 칭찬 리뷰에 제육볶음 정식 언급이 1건 있어요.\n저녁 손님을 다시 부르는 제육볶음 정식 쿠폰 홍보를 제안해요.",
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
| `chosen_measures[]` | 사장님이 고른 조치 `{id, text}`. mock도 고른 값을 실음 (11/16) | 초안 화면 위 "오늘부터 실천할 주방 점검 수칙: …", 완료 화면의 같은 이름 목록 |
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

**화면의 글 상태 규칙** (`src/features/flow/calc.js`의 `statusOf`, 시험이 지킴. 2.4 (1)의 7. 초안 목록은 이 결과로 `listBadges`가 '승인 대기'·'승인 완료'와 점검 배지를 붙임):

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
| `400` · `404` | 개별 다시 만들기의 입력 오류 (아래 '개별 다시 만들기'의 표) | ① 모양 |

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
  "error": {"message": "모르는 주방 점검 수칙이에요: M9"}
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

**개별 다시 만들기 (11/16)**: 본문에 `generator`를 보내면 카드 전체가 아니라 **그 글 한 건만** 다시 만듭니다. 초안 상자 안의 '다시 만들기'가 씁니다. 예전에는 이 버튼이 카드 전체를 다시 만들어, 다른 글에서 고치던 내용과 승인까지 날렸습니다.

```json
{"generator": "reply_draft", "review_id": "rv_ongi_002", "measures": ["M1"], "replaces": ["d_66ce6794"]}
```

| 칸 | 형식·범위 | 뜻 |
|---|---|---|
| `generator` | 문자열(40자 이하), 생략·`null`이면 카드 전체 | 다시 만들 글 종류. 카드 ⓐ는 `"reply_draft"`·`"prevention_notice"`, 카드 ⓑ는 `"coupon_promo"`. 그 카드가 만들지 않는 종류면 `400` |
| `review_id` | 문자열(100자 이하) | `reply_draft`일 때 **필수**: 그 답글이 가리키는 리뷰(`drafts[].target_review_id`). 카드 묶음의 리뷰이거나, 답글을 함께 만든 붙여넣은 리뷰여야 함. 아니면 `404`. 다른 종류에서는 무시 |
| `measures` | 위와 같음 | 화면은 처음 만들 때 고른 조치(`chosen_measures`의 id)를 그대로 보냄 |
| `reply_texts` | 문자열 목록(20개 이하), 선택 | `prevention_notice`일 때만 씀: 지금 화면에 있는 묶음 답글들의 글. 새 공지가 답글과 너무 비슷한지(`checks.notice_vs_reply`) 견주는 데만 쓰고 모델에 넘기지 않음. 안 보내면 그 점검은 늘 통과 |
| `replaces` | 위와 같음 | 화면은 다시 만드는 그 글의 id 하나(`[d.draft_id]`)를 보냄 |

- 응답은 전체 실행과 **같은 모양**이고 `drafts`에 그 한 건만 있습니다. 맨 위에 `"partial": true`와 `"regenerated": {"generator", "review_id", "pasted"}`가 붙습니다 (`pasted`: 붙여넣은 리뷰의 답글이면 `true`). `flagged_count`·`elapsed_ms`·`won`은 이 한 건의 값입니다 (mock의 `elapsed_ms`·`won`은 저장된 카드 값 그대로).
- **묶음 리뷰의 답글**은 전체 실행 때와 같은 자리(순서)로 만듭니다. 글 만드는 코드가 답글 순서대로 조치·요청사항 문장을 돌려 쓰기 때문에, 자리가 같아야 다른 답글과 문장이 겹치지 않습니다. **붙여넣은 리뷰의 답글**도 전체 실행과 같은 방식이고, 응답에 `pasted_reply_review_ids: [그 리뷰]`가 붙습니다.
- 한 건만 만든 답글의 `checks`에는 `not_too_similar`(다른 답글과 표현이 겹치는지)가 **없습니다**. 그 비교는 답글들의 AI가 쓴 부분끼리 하는데 한 건만 만들어서 견줄 수 없기 때문입니다. 참고용 점검이라 글 상태(점검 통과·실패)는 달라지지 않습니다.
- mock은 저장 예시에서 그 한 건을 골라 줍니다 (글과 `draft_id`가 전과 같음). 붙여넣은 리뷰는 글이 똑같은 저장 예시가 있을 때만 되고, 없으면 `404`.
- 카드 ⓑ는 글이 하나라 `coupon_promo` 한 건 다시 만들기가 카드 전체 실행과 같습니다.
- 다시 만든 글도 서버가 기억해서, 승인하면 승인 기록에 카드·종류가 붙습니다 (1.6). 다른 글의 기억은 그대로입니다.
- 화면은 받은 글을 종류와 `target_review_id`가 같은 자리의 글과 바꾸고, **그 글의** 승인 표시와 고치던 내용만 지웁니다.

mock에서 카드 ⓐ의 재발 방지 공지만 다시 만든 응답 `200` (실제로 뽑음. `checks`는 줄임):

```json
{
  "card_id": "card_ongi_a",
  "kind": "complaint",
  "reason_text": "포장 누락 불만이 3건 반복됐고, 모두 17~21시에 들어왔어요",
  "basis_label": null,
  "drafts": [
    {
      "draft_id": "d_b320f984",
      "card_id": "card_ongi_a",
      "store_id": "store_ongi",
      "generator": "prevention_notice",
      "target_review_id": null,
      "text": "[안내] 포장 누락 관련\n온기한식을 찾아 주시는 분들께\n최근 공깃밥, 수저와 젓가락, 계란말이가 빠진 상태로 배달된 일이 있었습니다.\n불편을 드려 죄송합니다.\n오늘부터 포장 마감 전에 주문서와 한 번 더 대조하겠습니다.\n이외에도 필요한 게 있으면 요청사항에 적어 주세요.\n늘 찾아 주셔서 감사합니다. 온기한식 드림",
      "evidence_ids": ["F_rv_ongi_001", "F_rv_ongi_002", "F_rv_ongi_003", "M1"],
      "checks": {"…": true},
      "failed_reasons": [],
      "rewrites": 2,
      "needs_input": [],
      "status": "draft",
      "edited_text": null,
      "model": "HCX-005",
      "elapsed_ms": 7362,
      "data_origin": "synthetic",
      "style": null,
      "c7_flags": []
    }
  ],
  "chosen_measures": [{"id": "M1", "text": "포장 마감 전 주문서 대조"}],
  "elapsed_ms": 11958,
  "won": 54.04,
  "source": "seed",
  "source_note": "김수현 저장본(c6_cache_best.json, 샘플 카드 card_sample_a로 생성한 글). 이유 문장은 이 화면의 카드 문장으로 바꿈",
  "flagged_count": 0,
  "partial": true,
  "regenerated": {"generator": "prevention_notice", "review_id": null, "pasted": false}
}
```

**옛 글의 승인 기록 지우기 (`replaces`, 11/16)**: 다시 만들면 화면은 옛 글의 승인 표시를 지우지만, 예전에는 서버 승인 기록(1.7 `GET /api/approvals`, 완료 화면의 '서버 처리 기록')에 옛 `draft_id`의 승인이 '처음부터 다시'(1.7.1) 전까지 남았습니다. 이제 화면이 바뀌는 옛 글 id를 `replaces`로 보내고, 서버가 지웁니다.

- **생성이 성공한 뒤에만** 이 방문자(쿠키 `visitor_id`)의 승인 기록에서 그 `draft_id`들을 지웁니다. 다른 방문자의 기록, 목록에 없는 다른 글의 기록은 그대로입니다. 생성이 오류로 끝나면(`400`·`404`·`502`·`503`) 아무것도 지우지 않습니다. HCX가 응답하지 않아 글 만드는 코드가 고정 문장으로 글을 돌려준 경우(`200`, 글에 '확인 필요')는 성공이라 지웁니다 (화면도 그 글로 바꾸므로).
- 응답 맨 위에 `"replaced_approvals": n`(지운 승인 기록 수)이 붙습니다. 승인한 적 없는 id나 같은 id를 두 번 보낸 것은 세지 않습니다 (`0`일 수 있음). `replaces`를 보내지 않으면 이 칸이 없고 예전 응답과 같습니다.
- 개별 다시 만들기(`generator` 있음)는 그 글 하나, '카드 전체 다시 만들기'(`generator` 없음)는 그 카드의 지금 글 모두를 보냅니다 (20개를 넘으면 승인한 글부터 20개). mock은 새 글 id가 옛 글과 같지만, 새 글은 아직 승인 전이라 지우는 것이 화면과 맞습니다.
- 지우는 곳: 서버 메모리의 목록(기본) 또는 DB `approvals` 표의 이 가게·이 방문자·그 `draft_id` 줄. DB에 아직 못 써서 이 서버가 들고 있던 그 글의 승인도 버립니다. 지우지 않는 것은 1.7.1과 같습니다 (`approvals.jsonl`, 리뷰 분석 서비스의 '답글 달았음' 기록).
- 저장소(DB)에 닿지 못해 지우지 못하면 새 글은 그대로 `200`으로 주고 `"replaced_approvals": 0`과 `"replace_warning": "옛 글의 승인 기록을 서버에서 지우지 못했어요. 새 글은 그대로 쓸 수 있어요."`를 붙입니다. 화면은 이 문장을 알림 띠(`#alert`)에 보입니다. 이때도 이 서버가 들고 있던 그 글의 승인은 버립니다.
- id 모양: 영문·숫자·`_`·`-`, 1~100자 (리뷰 id와 같은 규칙. 글 만드는 코드의 `d_` + 16진수 8자리, 저장 예시의 `d_ex_unfair01_001` 모두 맞음). 승인 API(1.6)는 어떤 문자열이든 받지만 지우는 쪽은 모양을 봅니다.

개별 다시 만들기의 오류 (모두 ① 모양. 문장은 실제로 뽑음):

| 코드 | 언제 | `error.message` |
|---|---|---|
| `400` | 그 카드가 만들지 않는 글 종류 (예: 카드 ⓐ에 `coupon_promo`), 모르는 종류, 빈 문자열 | "이 카드에서 만드는 글이 아니에요: coupon_promo" |
| `400` | `reply_draft`인데 `review_id`가 없음 | "어느 리뷰의 답글을 다시 만들지(review_id) 알려 주세요." |
| `404` | `review_id`가 카드 묶음의 리뷰도, 답글을 만드는 붙여넣은 리뷰도 아님 | "그 리뷰는 이 카드에서 답글을 만드는 리뷰가 아니에요. 새로 고침 하세요." |
| `404` | mock에서 그 붙여넣은 리뷰와 글이 같은 저장 예시가 없음 | "이 리뷰의 답글은 지금 다시 만들 수 없어요 (…)" |
| `400` · `502` · `503` | 전체 실행과 같음 (live에서 키 없음·모르는 `measures`, HCX 쪽 예상 못한 오류, 리뷰 분석 서버 문제) | 전체 실행과 같은 문장 |
| `400` | `replaces`가 20개를 넘음 (카드 전체 실행도 같음) | "바꿀 옛 글 id(replaces)는 한 번에 20개까지예요." |
| `400` | `replaces`의 id 모양이 틀림 (빈 문자열, 공백·`/`·`.` 등이 든 값, 100자 넘음) | "바꿀 옛 글 id(replaces)의 모양이 맞지 않아요. 새로 고침 하세요." |
| `422` | `generator`가 40자를 넘음, `reply_texts`·`replaces`가 목록이 아니거나 문자열이 아닌 값이 듦 | ② 모양 |

**참고**
- 화면은 서버가 준 글 순서(답글들, 공지)와 상관없이 **공지 → 홍보글 → 답글** 순서로 보여 줍니다 (`src/lib/domain.js`의 `GEN_ORDER`·`byGen`, `draftsOf`).
- '카드 전체 다시 만들기'를 하면 그 카드의 예전 글과 승인 표시는 화면에서 버려집니다. 초안 상자의 '다시 만들기'는 그 글 한 건의 것만 버립니다. **11/16부터** 서버의 승인 기록에서도 같이 지웁니다 (아래).
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
| `items[].draft_id` · `edited` · `approved_at` | 글 id, 고쳤는지, 승인 시각 | "MM-DD HH:MM 승인 · 글 이름 (고침)" (11/20. 글 이름은 화면의 승인 목록에서 찾고, 못 찾으면 '글'·'맞춤 마케팅 글'. 글 id 는 보이지 않음) |
| `items[].status` · `text` · `mode` · `warning` | `1.6` 응답과 같음 | 안 씀 |

**오류**: 없음 (기록이 없으면 `{"items": []}`).

**참고**
- 이 목록은 **서버 메모리**입니다. 서버를 다시 켜면 비어 있습니다. 파일(`approvals.jsonl`)에 남은 줄을 다시 읽지 않습니다 (3.1).
- 방문자를 구분하지 않으므로 모든 방문자의 승인이 한 목록에 섞입니다.
- **11/16부터** 글을 다시 만들면(개별·카드 전체) 바뀐 옛 글의 승인은 이 목록에서 빠집니다 (1.5 '옛 글의 승인 기록 지우기').

---

### 1.7.1 `DELETE /api/approvals` (11/16)

**하는 일**: **이 방문자**(쿠키 `visitor_id`)의 승인 기록을 모두 지웁니다. 다른 방문자의 기록은 건드리지 않습니다.
**쓰는 화면**: 처리 완료 `#/done`의 보조 버튼 '처음부터 다시'(`flow/actions.js`의 `restart`). 화면의 진행을 비우면서 같이 부릅니다. 그래서 다시 카드 → 승인 → 완료로 왔을 때 '서버 처리 기록'에 예전 승인이 남아 있지 않습니다. (주 버튼 '홈으로'는 아무것도 지우지 않고 API도 부르지 않습니다.)

**요청**: `DELETE /api/approvals`. 본문 없음.

**응답 `200`** (실제로 뽑음. 글 4건을 승인한 뒤. `marketing_cleared`는 11/16에 더함):

```json
{"deleted": 4, "marketing_cleared": true}
```

| 칸 | 뜻 | 화면 |
|---|---|---|
| `deleted` | 지운 승인 기록 수. 지울 것이 없으면 `0` (그래도 `200`). 맞춤 마케팅에서 승인한 글(`mkt-…`)도 이 기록이라 같이 셈 | 안 씀 |
| `marketing_cleared` | (11/16) 이 방문자의 맞춤 마케팅 기록(마케팅 보고서가 세는 것)도 지웠는지. `true` = 지움(지울 것이 없어도), `false` = 마케팅 서비스가 받지 않음·3초 안에 답 없음, `null` = 이 서버에서 꺼 둠(`MARKETING_SURVEY_URL=off`)·연결 못 함. 마케팅 서비스가 어떤 상태여도 승인 기록 지우기는 그대로 성공 (1.12) | `false`면 맞춤 마케팅 화면 위에만 "기록은 지우지 못했어요" 안내 |

- 지우는 곳: 서버 메모리의 목록(기본) 또는 DB의 `approvals` 표에서 이 가게·이 방문자의 줄(`DB_HOST`가 있을 때). DB에 아직 못 써서 이 서버가 들고 있던 승인도 같이 버립니다.
- **지우지 않는 것**: 메모리 방식의 기록 파일 `approvals.jsonl`(덧붙이기만 하는 기록이라 그대로 둠), 답글 승인 때 리뷰 분석 서비스에 남긴 '답글 달았음' 기록(1.6, 응대 점수·보고서에 계속 반영됨).
- 지운 뒤 `GET /api/approvals`는 `{"items": []}`입니다.
- (11/16) 승인 기록을 지운 다음 마케팅 서비스의 `DELETE /api/marketing-survey/records?store=&visitor_id=`(4부 4.5)를 부릅니다. 승인 기록을 못 지워 `503`이면 마케팅 기록도 건드리지 않습니다.

**오류**

| 코드 | 언제 | 본문 |
|---|---|---|
| `503` | 저장소(DB)에 닿지 못해 지우지 못함. 이때는 아무것도 지우지 않음. 화면은 진행을 비우고 알림 띠에 "화면은 처음으로 돌렸지만 서버의 승인 기록은 지우지 못했어요. …"를 보임 | ① 모양 ("승인 기록을 지우지 못했어요. 잠시 뒤 다시 눌러 주세요.") |

---

### 1.8 `POST /api/reviews`

**하는 일**: 사장님이 붙여넣은 리뷰 한 건을 리뷰 분석 서버에 넘겨 저장하고 바로 분류합니다. 전화번호·이메일·링크는 저장 전에 `[가림]`으로 바꿉니다. 응답은 **리뷰 분석 서버의 응답을 그대로** 전달합니다 (비서 화면 서버가 가공하지 않음).
**쓰는 화면**: 리뷰 분석 `#/analysis`의 '리뷰 넣기' 탭(`paste`) 안 '리뷰 붙여넣기' 칸의 '분류하기' 버튼(`features/analysis/PasteTab.jsx`). 성공하면 화면이 홈 숫자·추천 카드·요약·불만 묶음을 다시 불러옵니다 (`briefing`, `cards`, `insight`).

**요청**: `POST /api/reviews`

```json
{"text": "포장이 허술해서 국물이 새고 반찬이 하나 빠졌어요. 연락은 010-0000-0000 으로 주세요", "rating": 2}
```

| 칸 | 형식·범위 | 뜻 |
|---|---|---|
| `text` | 문자열, **1~1000자**, 필수 | 리뷰 글 |
| `rating` | 정수 1~5, 생략·`null` 가능 | 별점. 모르면 비움 |
| `channel` | `"baemin"`, `"coupangeats"`, `"yogiyo"`, `"naver_place"` 중 하나, 생략·`null` 가능 | 배달앱. **11/20부터 화면이 보냄**: 붙여넣기 칸의 '채널' 고르기(`#paste-channel`, 보기는 `features/analysis/calc.js`의 `CHANNELS`: 채널 모름 · 배달의민족 `baemin` · 쿠팡이츠 `coupangeats` · 요기요 `yogiyo` · 네이버 플레이스 `naver_place`). 고른 경우에만 `channel`을 싣고, '채널 모름'이면 예전처럼 칸 없이 보냄. 캡처 저장(`source: "capture"`)은 보내지 않음 |
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
**쓰는 화면**: 리뷰 분석 '리뷰 넣기' 탭의 '붙여넣은 리뷰 지우기' 버튼(`PasteTab.jsx`의 `resetPaste`). 성공하면 홈 숫자·추천 카드·요약·불만 묶음을 다시 불러옵니다.

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
| `POST /api/assistant/messages` | 질문 1개 → 답, 근거 카드, 선택지. 가게 자체를 묻는 질문(이름·메뉴, 리뷰·답글을 어디서 보는지)은 이 서버가 가게 프로필로 답함 (아래 "가게 기본 질문") | `503`·`422` |
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
                "industry_name": "한식음식점", "period": "20262", "period_label": "2026년 2분기", "location_label": "장승배기역",
                "is_store_default": true}}
```

| `status` | 뜻 |
|---|---|
| `ok` | 조건을 새로 맞춤 (`conditions`에 결과) |
| `already` | 이미 조건이 있거나, 사용자가 다른 위치·업종을 고르는 중이라 건드리지 않음 (`force` 없을 때). 기본 조건이 없는 가게도 `already`이고 `conditions`는 `null` |
| `unavailable` | 맞추지 못함. `state`와 `message`로 이유(`down`, `disabled`, `no_data`, `error` 등) |

우리 가게 기본 조건은 `온기한식` = 장승배기역(7호선) · 한식음식점(`CS100001`) · 장승배기역 4번 상권(`3110826`) · 가장 최근 분기(2026년 2분기가 있으면 그것). 위치는 역 코드로 저장하므로 서울시 지도(Naver) 검색을 부르지 않습니다. 서랍을 처음 열 때 화면이 한 번 부르면, 사용자가 "어디를 볼까요?"를 다시 묻지 않고 바로 질문할 수 있습니다.

**`conditions.is_store_default`** (11/16): 지금 분석 조건이 우리 가게 기본 조건과 같은지입니다. `conditions`가 실리는 모든 응답(`setup`, `conversation` 조회, `messages`, `actions`)에 서버가 붙입니다. 상권 서비스가 준 칸이 아니라 이 서버가 더한 칸입니다.

| 값 | 뜻 | 서랍의 `#assistant-home` 버튼 |
|---|---|---|
| `true` | 상권·업종·분기 코드가 우리 가게 기본 조건과 같음 | "우리 가게 기준 적용 중" (누를 수 없음) |
| `false` | 대화 중에 다른 상권·업종·분기로 바뀜 | "우리 가게 조건으로" (누르면 `setup?force=1`) |
| `null` | 모름 (기본 조건이 없는 가게이거나 조건에 코드가 없음) | "우리 가게 조건으로" (예전처럼 누를 수 있음) |

비교는 서버 한 곳에서만 합니다(`area_code`·`industry_code`·`period`를 정해 둔 값과 비교). 정해 둔 분기나 상권이 자료에 없어 `setup`이 가장 최근 분기·다른 상권으로 맞췄다면, 그렇게 맞춘 조건도 기본 조건으로 봅니다(서버가 마지막으로 맞춘 값을 메모리에 기억함. 서버를 다시 켠 직후에는 정해 둔 값과 똑같을 때만 `true`이고, `setup`이 한 번 돌면 다시 기억함). 화면은 이 값만 믿고 따로 비교하지 않습니다.

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
 "conditions": {"area_name": "장승배기역 4번", "industry_name": "한식음식점", "period_label": "2026년 2분기", "is_store_default": true}}
```

| 칸 | 뜻 |
|---|---|
| `reply.kind` | 답의 종류 (`data_answer`, `choose_location`, `need_location`, `period_unavailable`, `data_unavailable` 등). 화면은 모양 구분에 쓰지 않아도 됨 |
| `reply.text` | 여러 줄. `- `로 시작하는 줄은 목록, `참고:`·`해석:`·`다음으로 `로 시작하는 줄은 특별 줄. `[F1]`은 근거 카드 번호 |
| `reply.actions[]` | 선택지 `{label, payload}`. 누르면 `payload`를 `POST /api/assistant/actions`에 그대로 보냄. 없을 수 있음 |
| `reply.notes[]` · `reply.suggestions[]` | 자료 기준 안내 · 이어서 물어볼 질문(최대 3개). 없을 수 있음 |
| `cards[]` | 근거 카드. `values[]` 중 숫자인 것만 표로 보임. 출처는 `source_ref` |
| `conditions` | 지금 분석 조건(`is_store_default` 포함, 위 `setup` 참고). 없을 수 있음. 가게 기본 질문의 답에는 없음(조건 줄을 그대로 둠) |

**분기 표기** (11/16): 상권 서비스의 분기 코드는 `20262`(2026년 2분기)입니다. 조건에 분기 이름이 빠지면 이 코드가 답 문장에 그대로 들어오기도 합니다("20262 자료로 볼게요"). 서버는 화면에 넘기기 전에 **보이는 글자만** `2026년 2분기` 모양으로 바꿉니다(추천 카드의 `2026Q2` → `2026년 2분기`와 같은 모양. `2026Q2`도 같이 바꿈).

| 바꾸는 칸 (보이는 글자) | 그대로 두는 칸 (상권 서비스로 되돌아가거나 코드인 값) |
|---|---|
| `conditions.period_label` (이름이 없으면 `period`로 만듦) | `conditions.period` · `area_code` · `industry_code` |
| `reply.text` · `reply.notes[]` · `reply.suggestions[]` · `reply.actions[].label` | `reply.actions[].payload` (누르면 그대로 `actions`에 보냄) |
| `cards[].text` · `cards[].warnings[]` · `cards[].values[].label` · 글자인 `cards[].values[].value` | `cards[].values[].code` · 숫자인 `value` · `cards[].source_ref` |
| `turns[]` 안의 `reply`·`cards` (위와 같음) | `turns[].user_text`(사용자가 쓴 글) · `turns[].action` |

금액·개수는 바꾸지 않습니다. 앞뒤에 숫자·영문·쉼표·점·`-`·`_`가 붙었거나(`120262`, `20,262`, `20262.5`, `v-20262`) 바로 뒤에 단위가 오면(`20262원`·`20262건`·`20262명`·`20262개`·`20262%` 등) 그대로 둡니다. 문장 속에서는 `20`으로 시작하는 연도만 보고, `period_label`처럼 칸 전체가 코드(`^\d{4}[1-4]$`)이면 연도를 가리지 않습니다. 화면(`src/features/assistant/chat.js`의 `CHAT_QUARTER`·`chatQuarter`)도 같은 정규식으로 한 번 더 봅니다(서버가 놓친 글자 대비. 2.4 (1)의 8: 시험이 두 정규식이 글자 그대로 같은지 확인).

**가게 기본 질문** (11/16): 서랍은 동네 상권·업종 매출 상담이지만 "우리 가게 이름 뭐야?", "우리 가게 메뉴 뭐야?", "리뷰 답글은 어디서 봐?" 같은 질문도 들어옵니다. 이런 질문은 상권 서비스로 보내지 않고 이 서버가 가게 프로필(리뷰 분석 서비스의 가게 정보 + 상권 지표 파일의 상권 이름, ③ 생성이 쓰는 것과 같은 값)로 답합니다. 응답 모양은 상권 서비스의 답과 같고 `answered_by`만 더 있습니다.

```json
{"schema_version": "assistant-reply-v1",
 "reply": {"kind": "store_profile",
           "text": "우리 가게 이름은 '온기한식 (가상)'이에요.\n- 업종: 한식음식점\n- 상권: 장승배기역 4번\n- 메뉴: 제육볶음 정식, 된장찌개, 김치찌개, 순두부찌개, 불고기 덮밥, 계란말이\n참고: 리뷰는 화면 메뉴 '리뷰 분석', 답글·공지·홍보 글은 '추천 카드' → '승인할 글', 전체 요약은 '종합 리포트'에서 볼 수 있어요.",
           "cited": [], "actions": [], "notes": ["가게 이름·업종·메뉴는 저장된 가게 프로필이에요. 상권 통계가 아니에요."],
           "suggestions": ["우리 가게 상권 매출은 어때?", "주변에 같은 업종 점포는 몇 개야?"]},
 "model_used": false, "cards": [], "topics": [],
 "classification": {"domain": "store", "turn_type": "name", "topics": [], "needs_user_choice": false, "needs_model": false, "analyzer": "web_proxy"},
 "pending": null, "answered_by": "store_profile"}
```

| 칸 | 값 |
|---|---|
| `answered_by` | `"store_profile"`. 이 서버가 답했다는 표시. 상권 서비스의 답에는 이 칸이 없음 |
| `reply.kind` | `store_profile`(가게 정보) · `store_guide`(화면 위치 안내) · `store_unavailable`(가게 정보를 못 읽음: "가게 정보를 지금 불러오지 못했어요…") |
| `reply.actions` | `store_profile`·`store_unavailable`은 빈 목록. `store_guide`는 그 화면으로 가는 이동 버튼 1~3개 (11/20, 1.15) |
| `classification.turn_type` | 질문 종류: `name` · `industry` · `area` · `menu` · `price` · `profile` · `unknown`(프로필에 없는 것) · `menu_sales` · `where` |
| `conditions` | 없음. 화면의 조건 줄과 `#assistant-home` 버튼은 그대로 |

고르는 규칙은 보수적입니다 (`assistant_proxy.store_question`, 공백·기호를 뺀 40자 이하인 글만 봄).

1. 상권 낱말(매출·점포·유동인구·주변·동네·평균·비교·추천·어때·월세…)이 하나라도 있으면 **상권 서비스로** 보냅니다. 가게 질문과 섞여 있어도 그렇습니다("우리 가게 이름이랑 상권 매출 같이 알려줘", "우리 가게 업종 평균 매출"). 낱말이 `상권` 하나뿐이고 가게의 상권 이름을 묻는 모양("우리 가게 어느 상권이야?")일 때만 가게 질문입니다.
2. 화면 위치: 화면에 있는 것(리뷰·답글·공지·홍보·리포트…) + 어디서 보는지("어디서 봐", "어디 있어", "보여줘"). 글을 써 달라는 말("답글 써줘")은 아닙니다.
3. 가게 정보: "우리 가게…"·"가게…"·"메뉴…"로 시작하거나 그 말이 있고, 이름·업종·메뉴·가격·위치 낱말 바로 뒤에 묻는 말이 올 때만("이름 뭐야", "메뉴 좀 알려줘"). 일을 시키는 말(써줘·바꿔·지어줘…)과 고민을 묻는 말("메뉴 뭐 넣을까?")은 아닙니다.
4. 우리 가게의 메뉴별 매출("우리 가게 메뉴별 매출 알려줘")은 1번보다 먼저 봅니다. 어디에도 없는 자료라 "이 화면에는 메뉴별 매출·판매량 정보가 없어요"라고 답합니다.
5. 어순 (11/20): 1~4에 걸리지 않으면 '우리 가게'가 뒤에 온 글자를 앞으로 옮겨 **딱 한 번** 더 봅니다(`_reordered`). "메뉴 우리 가게" → "우리가게메뉴"(menu), "이름 우리 가게"·"업종 우리 가게"·"위치 우리 가게"·"김치찌개 얼마야 우리 가게"도 같습니다. 속성 낱말 하나 + 가게("이름 가게", "메뉴판 가게")는 "우리가게이름"처럼 옮깁니다. 옮긴 글자도 1~4를 그대로 지나야 해서 상권 낱말이 섞이면("메뉴 추천해줘 우리 가게") 여전히 상권 서비스이고, 다른 곳의 가게("합정역 가게 이름 알려줘")는 옮기지 않습니다.

프로필에 없는 것(영업시간·전화번호·주소·사장님 이름 등)은 지어내지 않고 "이 화면에는 그 정보가 없어요."로 답합니다. 메뉴 가격은 프로필에 있을 때만 적습니다. 가격 질문은 메뉴 이름·'메뉴'·'가격표'가 있거나, 메뉴 이름 없이 우리 가게 가격만 묻는 말("우리 가게 가격 알려줘", "가격 우리 가게", 11/20)일 때 메뉴 가격표로 답하고, 메뉴가 아닌 것의 값("우리 가게 화장지 값 얼마야?")은 "이 화면에는 그 정보가 없어요."입니다. 가게 정보를 읽지 못해도(리뷰 분석 서비스 꺼짐) `200`으로 "가게 정보를 지금 불러오지 못했어요…"라고 답하고 상권 서비스로 넘기지 않습니다. 상권 서비스가 꺼져 있어도 이 답은 나옵니다(다만 서랍은 상권 비서가 `ready`가 아니면 입력칸을 막습니다). 이 서버에서 상권 비서를 꺼 두었으면(`off`) 다른 질문과 똑같이 `503`입니다.

**알려진 한계**: 이 서버가 답한 문답은 상권 서비스의 대화 기록에 남지 않습니다. 페이지를 새로 고치면 그 문답은 서랍에 다시 나오지 않습니다(`conversation` 조회에 없음).

**오류 모양** (이 절의 모든 API 공통)

```json
{"error": {"message": "상권 서비스에 연결하지 못했어요. 잠시 뒤 다시 확인해 주세요.", "state": "down"}}
```

| 상태 코드 | `state` | 언제 |
|---|---|---|
| `503` | `down` · `disabled` · `no_data` · `error` | 상권 서비스 문제. 비서 화면의 다른 API는 아무 영향이 없음 |
| `422` | `invalid` | 입력 문제 (빈 질문, 1000자 초과, 모르는 선택지 종류) |

이 절의 API는 **어떤 경우에도 `500`을 주지 않습니다.** 서랍 안에서만 안내를 보이고 비서 화면 맨 위 알림 띠는 쓰지 않습니다.

**세션 쿠키**: 상권 서비스는 대화와 분석 조건을 세션(`market_onboarding_session`, 30일)에 붙입니다. 서버가 그 값을 쿠키(`HttpOnly`, 경로 `/api/assistant`)로 심고 다음 요청에 상권 서비스로 넘깁니다. 화면(JS)이 다룰 것은 없습니다(`credentials: "same-origin"`만). 상권 서비스는 Host가 `127.0.0.1`·`localhost`가 아니거나 `Origin`이 있으면 막기 때문에, 서버가 `Host: 127.0.0.1:8766`을 직접 싣고 `Origin`은 넘기지 않습니다. 서버가 두 대이면 상권 서비스의 세션 저장소(SQLite)도 서버마다 따로라서, 로드 밸런서가 방문자를 다른 서버로 보내면 대화가 이어지지 않습니다(분석 조건은 서랍이 다시 열릴 때 `setup`으로 다시 맞춤).

**답이 느릴 수 있습니다**: 실시간 모드에서 보통 2~8초, 가끔 더 걸립니다. 서버는 75초(`MARKET_TIMEOUT_SEC`)까지 기다립니다. 질문이 몰리면(동시 8개 초과) `503` "질문이 몰려 있어요"가 옵니다.

---

### 1.11 `/api/care/*` — 캡처 입력·응대 점수·보고서 (리뷰 분석 서비스의 고객응대 프록시)

**쓰는 화면**: 리뷰 분석 '리뷰 넣기' 탭의 '캡처로 넣기'(`features/analysis/Capture.jsx`)와 왼쪽 메뉴 '종합 리포트'(`#/report`)의 오늘 요약·응대 점수·월간 A4 인쇄용 링크. **11/20부터 종합 리포트의 주간·월간 보고서는 이 프록시가 아니라 1.17 `/api/reports/*`(계정별 저장)로 엽니다** (그 서버가 아래 `report/weekly`·`report/monthly?compare=true`를 직접 부름). 비서 화면 서버가 리뷰 분석 서비스(`127.0.0.1:8020`, `/api/review-insight/*`)의 고객응대 API를 **대신 불러 주는** 길입니다 (`services/web/web/care_proxy.py`). 브라우저는 8020에 가지 않고, 화면 파일에는 `/api/care`만 씁니다 (2.4 시험 2).

| 메서드 · 경로 | 서비스 경로 | 하는 일 | 실패하면 |
|---|---|---|---|
| `GET /api/care/status` | `/api/health` | 고객응대를 쓸 수 있는지 (`ready`·`off`·`down`·`error`) | 항상 `200` |
| `POST /api/care/reviews/capture` | `…/reviews/capture` | 리뷰 화면 캡처 1장(multipart `file`, png·jpg·webp) → 리뷰 후보. **저장하지 않음** | `400`·`413`·`422`·`502`·`503` |
| `POST /api/care/reviews/{review_id}/status` | `…/reviews/{id}/status` | 리뷰 상태·답글 기록 (`{"status", "reply_text", "at"}`) | `400`·`404`·`503` |
| `GET /api/care/response` | `…/response` | 응대 점수(0~100)·이유·답글 기다리는 불만의 기한 | `503` |
| `GET /api/care/report/daily?date=` | `…/report/daily` | 일일 요약 (비우면 오늘, 한국 날짜) | `400`·`503` |
| `GET /api/care/report/weekly?week=` | `…/report/weekly` | 주간 보고서 (그 날이 든 월~일, 비우면 이번 주. 11/20) | `400`·`503` |
| `GET /api/care/report/monthly?month=` | `…/report/monthly` | 월간 보고서 (비우면 이번 달) | `400`·`503` |
| `GET /api/care/report/monthly/print?month=` | `…/report/monthly/print` | 월간 보고서 인쇄용 A4 **HTML** (화면 월간 탭의 'A4 인쇄용'이 새 탭으로 엶) | `400`·`503` |

- **이 표 밖은 모두 `404`** (`{"error": {"state": "not_found"}}`, 서비스에 보내지 않음). 가게 정보(`/profile*`)는 가게 공용이라 아무 방문자나 고치거나 지울 수 있어서(임시 공지 101개면 저장본이 깨지는 알려진 버그도 있음) 열지 않았고, 문의(`/inquiries*`)·받은함(`/inbox`)·약속 장부(`/promises`)·다국어 메뉴판(`/menu/foreign*`)은 이 화면이 아직 쓰지 않습니다. 리뷰 목록·`insight`·붙여넣기 지우기는 1.3·1.8·1.9가 맡습니다.
- **손님용 문의 페이지 `/s/{가게}`와 `/api/care/public/*`는 기본으로 없습니다.** `CARE_PUBLIC=1`일 때만 붙고(우리 가게 하나만), 손님 주소는 Nginx가 넣는 `X-Real-IP`(없으면 접속한 쪽)를 씁니다. 보안 검토 전까지 켜지 않습니다.
- **캡처 후보의 저장은 1.8 `POST /api/reviews`에 `"source": "capture"`** 를 붙여 한 건씩 합니다. 그래서 붙여넣은 리뷰와 똑같이 이 방문자의 요약·불만 묶음·홈 숫자·추천 카드에 들어갑니다.
- 서버가 `store_id`는 `DEMO_STORE_ID`, `visitor_id`는 방문자 쿠키로 **덮어씁니다** (쿼리·JSON 본문. 캡처 업로드는 쿼리). 쿼리는 `date`·`week`·`month`·`now`만 넘기고(그래서 브라우저가 `compare`를 붙여도 넘어가지 않음), 리뷰 분석 서비스의 토큰(`REVIEW_INSIGHT_TOKEN`)은 서버가 붙입니다.
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

**`report/weekly` (11/20, 주간)**: 월요일 0시 ~ 일요일 23:59:59(한국 시간). 아무 날짜(`week=YYYY-MM-DD`)를 주면 그 날이 든 주로 보고, 아직 시작하지 않은 주는 `400`(`"아직 오지 않은 주입니다"`). 계산은 월간과 같은 함수(`report._span`)라 **칸도 월간과 같고**, 다른 점은 이것뿐입니다.
- 머리 칸: `week`(그 주 월요일) · `week_start` · `week_end` · `until`(진행 중이면 지금, 끝났으면 일요일 23:59:59).
- `repeated_issues[]`의 '이 기간 건수'는 `count_this_week` (월간은 `count_this_month`).
- 비교 칸(늘 들어 있음): `complaint_rate`(불만 리뷰 비율 %, 정수·0.5 올림, 리뷰 0건이면 `null`) · `previous`(`{week, review_count, complaint_count, complaint_rate}`, 바로 앞 주 전체) · `topics[]`(`{topic, topic_name, polarity: "negative"|"positive", count, previous}`, 이번 주나 지난주에 한 번이라도 나온 주제, 불만 먼저·많은 순. 한 리뷰는 주제·극성마다 한 번 = 리뷰 분석 화면의 `topic_counts` 셈법).
- `suggestions[]`는 '이번 주에 고칠 것' 최대 3개, 칸마다 `kind`·`title`(한 줄)·`evidence`(근거 숫자)·`text`(확인할 일) (+`issue_id`·`topic`). 차례: 답글 뒤 재발(`recurred`) → 이번 주에도 들어온 답글 없는 반복 불만(`no_reply`, 이번 주 건수 많은 순) → 지난주보다 는 불만(`rising`, 2건 이상) → 기한 넘긴 답글(`late`) → 이번 주엔 없던 답글 없는 반복 불만 → 칭찬이 가장 많은 메뉴(`praise_menu`, 2건 이상, 자리가 남을 때). 하나도 없으면 `none`(리뷰가 있을 때) 또는 `empty`(리뷰 0건). 문장 속 숫자는 모두 옆 칸 값과 같고(시험), 원인을 단정하지 않습니다.
- 리뷰가 0건인 주도 같은 모양입니다 (`review_count: 0`, `complaint_rate: null`, `topics: []`, 고칠 것 한 줄).
- 합성 리뷰는 받은 시각이 없어 묶음(`insight_at`) 계산에 늘 들어갑니다 (월간과 같은 기준). 그래서 지난 주에도 '전체 n건'은 지금까지의 묶음 크기입니다.

**`report/monthly?compare=true` (11/20)**: 월간 응답 **뒤에** 비교 칸 `complaint_rate` · `previous`(`{month, review_count, complaint_count, complaint_rate}`, 바로 앞 달 전체) · `topics[]`만 더합니다. `compare`를 안 주면(기본 `false`) 응답은 예전과 글자 하나 다르지 않습니다 (시험: 칸 순서까지, 그리고 바꾸기 전·후 20가지 경우의 JSON 을 견줘 같음을 확인). 이 프록시는 `compare`를 넘기지 않으므로 화면이 `/api/care/report/monthly`로 부르면 예전 모양 그대로입니다.

**`praise` 칸 (11/16, 손님 칭찬 요약)**: `report/daily`·`report/weekly`·`report/monthly` 응답에 모두 들어 있습니다. 그 보고서 기간(그날·그 주·그 달)에 들어온 리뷰만 **코드로** 센 값이고 모델을 부르지 않습니다 (`method: "code"`). 프록시는 이 칸을 그대로 넘깁니다. 화면의 '손님 칭찬 요약' 칸은 **지금 탭(주간·월간) 보고서의 `praise`** 로 그립니다 (11/20, 요청을 더하지 않음. 칭찬 주제는 '주제별 흐름'에).

```json
"praise": {
  "review_count": 18, "high_rating_count": 10, "positive_count": 10,
  "praise_count": 10, "praise_basis": "sentiment",
  "top_topics": [{"topic": "taste", "topic_name": "맛", "count": 5}, {"topic": "packaging", "topic_name": "포장 상태", "count": 2},
                 {"topic": "service", "topic_name": "응대", "count": 2}, {"topic": "menu", "topic_name": "메뉴 구성", "count": 1},
                 {"topic": "atmosphere", "topic_name": "매장 환경", "count": 1}],
  "top_menus": [{"menu": "순두부찌개", "count": 1}, {"menu": "불고기 덮밥", "count": 1}],
  "quote": {"text": "순두부찌개 얼큰하고 맛있어요", "review_id": "rv_ongi_039", "rating": 4},
  "method": "code"
}
```

(시험용 실행, 합성 리뷰만 있는 2026년 11월. 10월은 22건 중 별점 4~5점 16건·긍정 16건, 인기 메뉴는 제육볶음 정식·된장찌개·김치찌개 1건씩)

| 칸 | 뜻 | 화면 |
|---|---|---|
| `review_count` | 그 기간 리뷰 수 (보고서의 `review_count`와 같음) | 아래 작은 글씨 "이 달 리뷰 n건을 코드로 셌어요" |
| `high_rating_count` · `positive_count` | 별점 4~5점 리뷰 수 · 감정 분류가 긍정인 리뷰 수 | 숫자 두 칸 |
| `praise_count` · `praise_basis` | 칭찬 리뷰 수와 기준. `"sentiment"` = 긍정으로 분류된 리뷰, `"rating"` = 긍정 분류가 하나도 없어 별점 4점 이상이면서 불만이 없는 리뷰, 칭찬 리뷰가 없으면 `null` | "칭찬 리뷰 n건에서 골랐어요" (`rating`이면 기준 안내) |
| `top_topics[]` | 칭찬으로 걸린 주제별 리뷰 수 상위 5개 (`topic`, `topic_name`, `count`). 많은 순, 같으면 주제 사전 순서. 리뷰 분석 '칭찬 키워드'와 같은 셈법 | 칩 |
| `top_menus[]` | 인기 메뉴 TOP 3 (`menu`, `count`): 가게 메뉴 이름이 **칭찬 리뷰**에 나온 수. 언급이 없는 메뉴는 빠지고, 같은 수면 메뉴판 순서 | 순위 목록 |
| `quote` | 대표 칭찬 한 줄 (`text`, `review_id`, `rating`). 칭찬 리뷰가 없으면 `null` | 인용. 없으면 "아직 칭찬 리뷰가 없어요" |

- 칭찬 리뷰와 메뉴 언급 수의 기준은 저장소 루트의 `shared/praise.py`입니다 (`praise_reviews`, `top_praised_menus`). 추천 카드 ⓑ·쿠폰 메뉴 고르기와 같은 코드라 기준이 같습니다. 다만 **기간은 다릅니다**: 여기는 그 보고서의 날·달입니다.
- **대표 칭찬 한 줄 고르는 규칙** (코드, `services/review-insight/app/report.py`의 `_quote`): ① 가장 많이 언급된 메뉴(`top_menus[0]`)를 말한 칭찬 리뷰가 있으면 그 안에서, 없으면 칭찬 리뷰 전체에서 ② 개인정보를 가린 자리(`[가림]`)가 없는 글 → 별점 높은 것 → 최근에 받은 것 ③ 80자를 넘으면 그 메뉴를 말한 문장 하나만(그래도 넘으면 잘라서 `…`).
- **개인정보**: `quote.text`는 보고서를 만들 때 가림(`mask_pii`: 전화번호·이메일·링크·긴 숫자)을 **한 번 더** 거친 글입니다. 붙여넣기·캡처 리뷰는 저장할 때 이미 가리지만, 합성 샘플과 예전 저장본은 가림을 거치지 않았을 수 있어서입니다. 이름 같은 것은 이 가림이 찾지 못합니다.
- 숫자가 0이어도 칸은 같습니다 (빈 목록, `quote: null`). 리뷰 분석 서비스를 그 폴더만 떼어 띄운 환경(Dockerfile 이미지처럼 `shared/`가 없는 곳)에서는 `praise` 자체가 `null`이고, 화면은 그 칸에 안내만 보입니다.
- 인쇄용 페이지(`report/monthly/print`)에도 같은 숫자로 '손님 칭찬 요약' 네 줄이 들어갑니다 (글자는 `html.escape`).

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

서비스가 준 오류는 본문(`code`, `message`, `retryable`, …)을 그대로 두고 `state`만 더합니다. 화면은 `error.message`를 그 칸 안에만 보이고 맨 위 알림 띠는 쓰지 않습니다. **이 절의 API는 `500`을 주지 않으며, 리뷰 분석 서비스가 꺼져 있어도 비서 화면의 다른 API(1.1~1.9)는 그대로입니다** (단, 1.2~1.5·1.8·1.9는 원래 같은 리뷰 분석 서비스를 쓰므로 그 서비스 자체가 꺼지면 그쪽은 0.1절대로 `503`).

**인쇄용 페이지**는 이 서버 주소에서 열리므로 `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; …`와 `X-Content-Type-Options: nosniff`를 붙여 줍니다 (스크립트·외부 주소 막음).

---

### 1.12 `/api/marketing-survey/*` — 맞춤 마케팅 프록시 (11/16)

**쓰는 화면**: 왼쪽 메뉴 '맞춤 마케팅'(`#/marketing`, 2.5). 비서 화면 서버가 맞춤 마케팅 서비스(김수현 님 PR #56, `experiments/marketing/marketing_survey`, 기본 `127.0.0.1:8030`)를 **대신 불러 주는** 길입니다 (`services/web/web/marketing_proxy.py`). 경로 이름은 마케팅 서비스와 같고, 브라우저는 8030에 가지 않습니다. 서비스 자체의 API·기록 파일·모드·실행은 4부에 있습니다.

| 메서드 · 경로 (`/api/marketing-survey/` 뒤) | 기다리는 시간 | 하는 일 |
|---|---|---|
| `GET health` | 3초 | 쓸 수 있는지. **항상 `200`**: `state`(`ready`·`off`·`down`·`error`) + 서비스가 준 `mode`·`key_present`·`demo`·`notes` |
| `GET meta` | 10초 | 마케팅 서비스가 아는 우리 가게 이름 (화면 눈썹 줄 "온기한식 (가상) 기준") |
| `POST step` | 10초 | 질문 하나 진행 (보기·여러 개 고르기·입력칸·예시 문구) |
| `POST result` | 10초 | 맞춤 홍보 제안·재주문 쿠폰의 결정 설명 3줄 (규칙 계산. 화면 '왜 이렇게 판단했나요') |
| `POST plan` | **45초** | 결과 카드: 판단 근거·숫자·할 일·글. 글은 HCX(키가 없거나 mock이면 저장된 예시, `demo: true`) |
| `POST generate` | **45초** | '이 조건으로 쿠폰 글 만들기' (HCX) |
| `POST next-idea` | 10초 | 다음 아이디어 |
| `POST idea-try` | **45초** | 질문이 필요한 아이디어 '해 볼게요' |
| `POST coupon-calc` | 10초 | 쿠폰 슬라이더 계산 (장수·최대 비용·본전 주문 수) |
| `POST approve` | 10초 | 승인. 성공하면 이 서버의 승인 기록에도 남김 (아래) |
| `POST notice-followup` | 10초 | 공지 2주 뒤 개선 소식 (코드가 리뷰 수를 셈) |
| `GET report?period=weekly\|monthly` | 10초 | 마케팅 보고서 (기록이 없으면 데모 기록, `demo: true`) |

- **이 표 밖은 모두 `404`** (`{"error": {"state": "not_found"}}`, 서비스에 보내지 않음). 메서드가 다른 것도 `404`. 여러 가게 목록(`stores`)은 통합 화면이 가게 하나라 열지 않고, 기록 지우기(`DELETE records`)는 화면이 직접 부르지 않고 `DELETE /api/approvals`(1.7.1)가 서버 안에서 부릅니다. 서비스 자체 화면(`/`, `/web/*`)도 열지 않습니다.
- **쿼리는 서버가 고정합니다**: `store`는 `DEMO_STORE_ID`, `visitor_id`는 이 서버의 방문자 쿠키(형식이 맞을 때만. 없거나 틀리면 쿼리를 빼고 보냄, 4부 4.3). 브라우저가 쿼리로 보낸 `store`·`visitor_id`는 버리고, 그 밖의 쿼리는 `report`의 `period`만 넘깁니다. 본문은 그대로 넘깁니다(64KB까지).
- **직접 등록한 가게 (11/20)**: `store` 는 그 가게 id 이고, 요청마다 `X-IC26-Store-Profile` 헤더(1.16)를 서버가 붙입니다. 리뷰·카드·상권 지표가 없는 가게라
  카드가 있어야 만드는 글(`generate` 의 배달앱 안내문·쿠폰 홍보, `notice-followup`)은 **409** `{"error": {"message": "이 가게는 아직 맞춤 마케팅에 반복 불만 자료가 없어 … / 우리 가게 상권 지표가 아직 없어 …", "state": "invalid"}}`,
  `plan` 은 200 + `unavailable_drafts: [{step_id, message}]`(만들지 못한 글만 빠지고 할 일·쿠폰 계산은 그대로). 예시 세 곳에는 생기지 않습니다.
- 글을 만드는 세 경로(`plan`·`generate`·`idea-try`, 4부 4.2의 'live에서 HCX')만 45초(`MARKETING_TIMEOUT_SEC`)까지 기다리고 나머지는 10초입니다. 화면(`mktApi`)은 그보다 조금 길게(60초·15초) 기다립니다. 실시간 확인(11/16): 공지·답글 `plan` 7.4초, 가게 이야기 글 `plan` 7.7초, 새 손님 `plan` 11.5초.
- 서비스 호출(동기 httpx)은 서버 스레드에서 돌아서, 느린 `plan`이 다른 API를 붙잡지 않습니다 (시험으로 확인). 동시에 기다리는 호출은 8개까지.
- **`/api/health`에 마케팅 상태를 섞지 않습니다.** 섞으면 다른 화면 맨 위 막힘 띠에 마케팅 꺼짐이 뜹니다. 화면은 `#/marketing`을 처음 열 때 `health`를 따로 부릅니다.

**`health` 응답 `200`** (mock 마케팅 서비스):

```json
{"state": "ready", "message": null, "service": "marketing-survey", "mode": "mock", "key_present": false, "demo": true,
 "notes": ["mock: 키가 있어도 HCX 를 부르지 않아요. 글은 저장된 예시·코드 템플릿이에요(실제 AI 결과 아님)."], "store_id": "store_ongi"}
```

꺼져 있으면 `{"state": "down", "message": "맞춤 마케팅 서비스에 연결하지 못했어요. 잠시 뒤 다시 해 주세요.", …}`, 꺼 두었으면(`MARKETING_SURVEY_URL=off`) `state: "off"`, 주소 설정이 틀리면 `state: "error"`. 서비스가 `/health`를 모르는 판(PR #56 그대로)이면 `meta`가 오는지로 `ready`를 정하고 `mode`·`demo`는 `null`입니다.

**오류 모양** (화면은 `error.message`를 맞춤 마케팅 화면 안에만 보입니다)

```json
{"error": {"message": "맞춤 마케팅 서비스가 답하는 데 너무 오래 걸렸어요. 잠시 뒤 다시 해 주세요.", "state": "slow"}}
```

| 상태 코드 | `state` | 언제 |
|---|---|---|
| `503` | `off` · `down` · `busy` · `error` | 이 서버에서 꺼 둠 · 연결 못 함 · 동시 호출 8개 초과 · 주소 설정이 틀림이나 이 모듈의 버그 |
| `504` | `slow` | 기다리는 시간(45초·10초)이 넘음 |
| `502` | `error` | 서비스가 `5xx`이거나 JSON이 아닌 답을 줌 |
| 서비스와 같음 (`400`·`404`·`422` 등) | `invalid` · `not_found` · `busy` | 서비스가 받지 않음. FastAPI의 `{"detail": "한국어 문장"}`을 `message`로 옮김 (예: `400` "이 질문은 보기 중 하나(문자열)를 골라야 해요."). `detail`이 목록(입력 검사)이거나 영어 기본 문장('Not Found')이면 정해 둔 한국어 문장 ("보내는 내용의 형식이 맞지 않아요." · "이 서버의 맞춤 마케팅 서비스에는 아직 이 기능이 없어요.") |
| `404` | `not_found` | 위 표 밖의 경로·메서드 |
| `413` · `422` | `too_big` · `invalid` | 본문 64KB 초과 · 본문이 JSON 객체가 아님 |

**이 절의 API는 `500`을 주지 않으며, 마케팅 서비스가 꺼져 있거나 느려도 비서 화면의 다른 API(1.1~1.11)와 화면은 그대로입니다** (시험 `test_marketing_proxy.py`).

**승인 연동 (`POST approve`)**

화면은 마케팅 서비스가 받는 칸에 더해 `approval`(글 하나 또는 목록, 10개까지)을 실어 보냅니다. 프록시는 이 칸을 **떼고** 나머지만 서비스로 보냅니다.

```json
{"state": {"node": "DECISION", "raw": {…}, "confirms": {"H_REPEAT": "예"}, "mode": "survey"}, "draft_id": null, "session_id": "3f…",
 "edited_texts": {"notice": "고친 글"},
 "approval": [{"draft_id": "09f5d3dc59-notice", "text": "고친 글", "original": "처음 글", "kind": "공지", "title": "재발 방지 공지"},
              {"draft_id": "09f5d3dc59-reply", "text": "…", "original": "…", "kind": "답글", "title": "재발 방지 공지"}]}
```

서비스가 `2xx`이고 `edit_failed`가 없을 때만 글마다 이 서버의 승인 기록(1.6과 같은 저장, `demo.approve`)에 남기고, 응답에 `recorded`를 더합니다.

```json
{"follow_up": true, "state": {…}, "bot_messages": ["공지 뒤에 재주문 쿠폰도 해 볼까요? …", "월 마케팅 예산은 얼마로 생각하시나요?"], "options": […], "multi": false,
 "recorded": [{"draft_id": "mkt-09f5d3dc59-notice", "kind": "공지", "approved_at": "2026-11-16T15:27:53+09:00", "edited": true},
              {"draft_id": "mkt-09f5d3dc59-reply", "kind": "답글", "approved_at": "2026-11-16T15:27:53+09:00", "edited": false}]}
```

- 승인 기록의 `draft_id`는 늘 `mkt-`로 시작하고(`[A-Za-z0-9_-]`, 화면이 준 값이 틀리면 임의 값), `card_id`는 `"marketing"`, `kind`는 정해 둔 한국어 글 종류(`공지`·`답글`·`홍보 글`·`쿠폰 글`·`가게 이야기 글`·`남은 재료 글`·`아이디어 글`·`개선 소식`·`기본 할 일 글`, 그 밖은 `마케팅 글`). 글은 4,000자까지.
- 그래서 '처리 완료'의 '서버 처리 기록'에 "맞춤 마케팅 · mkt-…"로 보이고 `DELETE /api/approvals`로 같이 지워집니다. **리뷰 분석 서비스의 '답글 달았음' 기록(1.6)은 부르지 않습니다** (마케팅의 `답글`은 특정 리뷰의 답글이 아님).
- `edit_failed`(고친 글이 개인정보·정책에 없는 보상 약속 점검에 걸림)면 서비스 응답 그대로 돌려주고 기록하지 않습니다. 서비스가 실패하면(`4xx`·`5xx`·꺼짐) 기록하지 않습니다.
- 승인 기록을 못 남겨도(저장소 오류) 승인은 성공이고 `"record_warning": "마케팅 승인은 끝났지만 '처리 완료' 기록에는 남기지 못했어요."`가 붙습니다.

**설정** (`settings.py`): `MARKETING_SURVEY_URL`(기본 `http://127.0.0.1:8030`, `off`면 끔. `run.sh`가 마케팅 서버를 띄우고 이 값을 넘김, 4부 4.8), `MARKETING_TIMEOUT_SEC`(글을 만드는 경로를 기다리는 최대 초, 기본 45, 300 이하). 가게는 `DEMO_STORE_ID`.

---

### 1.13 `/api/auth/*` — 로그인과 사장님 가게 고르기 (5차 회의 11/18, 6차 회의 11/20 고침)

`services/web/web/auth.py`. 저장은 `users`·`user_stores`·`auth_sessions` 표(DB_HOST 가 없으면 서버 메모리, 3.4절).
11/20부터 로그인해야 쓰는 흐름(로그인 → 가게 선택 → 메인)입니다. 회원가입은 계정만 만들 수 있고(가게 0곳), 가게는 계정 안에서 직접 등록합니다(1.16).

| 메서드 | 경로 | 본문 | 응답 |
|---|---|---|---|
| GET | `/api/auth/me` | | 아래 '신원' 모양. 늘 200 |
| POST | `/api/auth/login` | `{login_id, password, keep?}` | 신원 + 세션 쿠키. `keep`(기본 `true`)이 `true`면 7일 쿠키(`Max-Age=604800`), `false`면 브라우저를 닫으면 지워지는 쿠키(`Max-Age` 없음, 서버 세션은 7일 그대로). 틀리면 401(아이디가 있는지 알려 주지 않는 한 문장), 아이디마다·주소마다 10분에 10번 넘게 틀리면 429 (주소를 정하는 법은 아래) |
| POST | `/api/auth/signup` | `{login_id, password, display_name, stores?}` | 201 신원 + 세션 쿠키. 아이디 중복 409, 입력 오류 422(`demo-`로 시작하는 아이디는 시연 계정 몫이라 422). `stores`를 안 보내면 `["store_ongi"]`(예전 그대로), **`[]`면 가게 0곳으로 가입**(11/20). 예시 가게 id 목록(`store_ongi`·`store_basak`·`store_mongle`)도 지금처럼 됩니다(체험용 계정). 그 밖의 id 는 422 |
| POST | `/api/auth/logout` | | 게스트 신원. 세션 쿠키와 상권 세션 쿠키(`/api/assistant`·`/api/market`)를 지움 |
| POST | `/api/auth/store` | `{store_id}` | 신원. 직접 등록한 가게도 고를 수 있음(11/20). 게스트 401, 가진 가게가 아니면 403 `not_your_store`. 상권 세션 쿠키를 지움(새 가게의 조건으로 다시 시작) |
| POST | `/api/auth/demo-login` | | 시연 사장님(가게 세 곳)으로 로그인. `DEMO_ACCOUNT_ENABLED=0` 이면 403. 브라우저(방문자 쿠키)마다 다른 시연 사장님이라 기록이 섞이지 않음. 그 아이디를 다른 계정이 이미 쓰면(예약 전 가입) 409 |
| POST | `/api/auth/reset` | `{scope: "store" \| "account"}` | 계정 초기화(11/19). 아래 '초기화 응답'. 대상은 내 가게 목록 전부(직접 등록한 가게 포함, 11/20). 게스트 401 `login_needed`, scope 가 틀리면 422 `invalid`(이 절의 오류 모양), 가게가 없는데 `store` 면 409 `no_store`. 못 지운 것이 있어도 200. 상권 세션 쿠키 두 개를 만료 |
| POST | `/api/auth/withdraw` | `{password}` (시연 계정은 없어도 됨) | 회원 탈퇴(11/19). 내가 등록한 가게 줄도 지움(11/20). 200 은 게스트 신원 + `"withdrawn": true`, 세션 쿠키·상권 쿠키 만료. 게스트 401 `login_needed`, 비밀번호가 틀리면 401 `bad_password`, 너무 많이 틀리면 429 `too_many`, 기록이 남으면 503 `records_left`(계정은 그대로), 저장소에 닿지 못하면 503 `down` |

신원 모양:

```json
{"authenticated": true,
 "user": {"user_id": "demo-0123456789ab", "login_id": "demo-0123456789ab", "display_name": "시연 사장님", "demo": true,
          "created_at": "2026-11-20"},
 "store_id": "store_basak",
 "stores": [{"store_id": "store_ongi", "name": "온기한식", "business_type_name": "한식음식점", "area_name": "장승배기역 4번", "station_name": "장승배기역", "sample": true},
            {"store_id": "store_basak", "name": "바삭치킨", "business_type_name": "치킨전문점", "area_name": "상도역 5번", "station_name": "상도역", "sample": true},
            {"store_id": "store_mongle", "name": "몽글카페", "business_type_name": "커피-음료", "area_name": "장승배기역", "station_name": "장승배기역", "sample": true}],
 "demo_login": true}
```

로그인 전: `{"authenticated": false, "user": null, "store_id": "store_ongi", "stores": [온기한식 하나], "demo_login": true}`. 세션 저장소에 닿지 못하면 게스트로 보고 `notice`를 더합니다.

- `user.created_at`(11/20): 가입일 `"YYYY-MM-DD"`(한국 시간).
- `stores[].sample`(11/20): 예시 가게 세 곳이면 `true`, 직접 등록한 가게면 `false`. 등록 가게는 역을 안 정했으면 `station_name: null`.
- **로그인했는데 가게가 0곳**이면 `{"authenticated": true, "user": {...}, "store_id": null, "stores": [], ...}` (11/20. 예전에는 게스트로 떨어졌음).
  가게가 생기면 세션에 고른 가게가 없으므로 목록의 첫 가게를 지금 가게로 봅니다(예전 규칙 그대로). 이미 보던 가게가 있으면 가게를 등록해도 바뀌지 않습니다.
  세션의 가게가 내 목록에 없으면(다른 기기에서 뺐을 때) 첫 가게를 봅니다.

**로그인 상태 지키기 (11/20, `main.py` 미들웨어)**

- 헤더 `X-IC26-Signed-In: 1`: 화면이 로그인 상태라고 믿을 때 모든 `/api/*` 요청에 붙입니다. 이 헤더가 있는데 세션이 없거나 끝났으면 `/api/auth/*` 를 뺀 `/api/*` 는 **401 `login_needed`**
  (메시지 "로그인이 끝났어요. 다시 로그인해 주세요."). 세션 저장소에 닿지 못했으면 503 `down`. **헤더가 없으면 예전처럼 게스트로 처리**합니다(게스트 화면·예전 시험 그대로).
- 로그인했지만 가게가 0곳이면 가게가 있어야 하는 API(`/api/briefing`·`/api/cards`·`/api/insight`·`/api/approvals`·`/api/cards/*/run`·`/api/drafts/*`·`/api/reviews*`·`/api/care/*`·`/api/marketing-survey/*`·`/api/assistant/*`)는 **409 `no_store`**("먼저 가게를 등록하거나 골라 주세요."). 아래 서비스는 부르지 않습니다.
  가게 없이도 되는 것: `/api/auth/*`·`/api/account/*`·`/api/health`(`store_id: null`)·`/api/market/*`(가게 등록 화면이 지도·주소 검색·상권 고르기에 씀. `status` 의 `store` 는 `null`, `setup` 은 기본 가게 조건으로 맞추지 않고 `already`). 로그인한 사장님에게 기본 가게(온기한식) 자료를 말없이 보여 주지 않습니다.
- 오류 모양은 이 절과 같습니다: `{"error": {"message", "state"}}`, `Cache-Control: no-store`.

- 아이디: 영문 소문자·숫자로 시작하는 3~32자(`. _ -` 가능, 대문자는 소문자로 저장). 비밀번호 8~128자. 이름 1~20자.
- 비밀번호는 `hashlib.scrypt`(N=2^14, r=8, p=1, 소금 16바이트, 32바이트)로 저장합니다. 세션 쿠키 `ic26_session` 의 값은 저장하지 않고 SHA-256 만 둡니다(7일).
- 쿠키: `HttpOnly`, `SameSite=Lax`, `Secure`는 `https`이거나 `X-Forwarded-Proto: https`일 때만(지금 공개 주소가 http 라서). 화면 JS 는 쿠키를 다루지 않습니다.
- 로그인 실패를 세는 주소(11/19): 실서버는 공개 ALB → Nginx → 내부 ALB → WAS 라 WAS 가 보는 주소는 늘 내부 ALB 의 사설 주소입니다. 그래서
  바로 앞이 내부 주소(10/8·172.16/12·192.168/16·100.64/10·루프백·링크 로컬·IPv6 내부)면 `X-Forwarded-For`를 오른쪽부터 훑어 처음 나오는 공인 주소를 쓰고,
  그래도 모르면 `<내부 주소>:v:<방문자 쿠키>`로 셉니다(한 사람이 틀렸다고 그 서버의 모든 방문자가 잠기지 않게). 공인 주소로 바로 붙은 요청의 `X-Forwarded-For`는 믿지 않습니다.
  파이썬 `is_private`는 문서용 공인 대역(`203.0.113.0/24` 등)까지 사설로 보아 쓰지 않고 내부 대역을 직접 적었습니다. 아이디마다 세는 것은 그대로입니다.
- 아래 서비스로 넘기는 방문자 id: `u-<user_id>` (영문·숫자·하이픈, 64자 이하. 리뷰 분석·맞춤 마케팅의 방문자 규칙과 기록 파일 이름 `records_<가게>_<방문자>.json`에 맞게 `_`를 쓰지 않음).
- 가게 세 곳의 업종·역·상권 코드와 가정 가격·말투는 `shared/store_profiles.py`. 바삭치킨은 상도역 5번(3110836)·치킨전문점(CS100007), 몽글카페는 장승배기역(3120154)·커피-음료(CS100010). 상권 지표는 `data/scenario/<가게>/snapshot_2026Q2.json`(서울시 공식 원본으로 만든 값, `scripts/reproduce_store_snapshots.py`).
- mock 에서 저장 예시(온기한식)가 없는 가게의 글은 코드 틀이고, 모든 글에 `needs_input` "시험용 예시 글이에요 … 실제 AI 결과 아님"이 붙어 '확인 필요'로 보입니다.

**계정 초기화 (11/19, `services/web/web/account.py`)**

오류는 모두 `{"error": {"message": "쉬운 한국어", "state": "<키>"}}`, 응답은 모두 `Cache-Control: no-store`.

```json
{"scope": "store", "complete": true, "message": null,
 "stores": [{"store_id": "store_ongi", "name": "온기한식", "approvals": 3, "reviews": 2, "marketing": "cleared"}]}
```

- `scope`: `store` = 지금 보는 가게 하나, `account` = 그 사장님이 가진 가게 모두. 계정·가게 목록·세션은 남습니다.
- 가게마다 그 사장님(방문자 `u-<user_id>`)의 것만 지웁니다. 다른 가게·다른 사장님·게스트의 기록은 그대로입니다.
  - 승인 기록(DB 에 아직 못 써서 서버가 들고 있던 것 포함). `approvals` = 지운 건수.
  - 붙여넣은 리뷰와 그 상태·답글 기록, 그 리뷰들의 분류 결과(리뷰 분석 서비스 `DELETE /api/review-insight/reviews/pasted?forget_labels=true`). `reviews` = 지운 리뷰 수.
    상태·답글 기록은 DB 를 쓰면 `review_records`·`review_status_events` 표에 있어(11/19) 어느 WAS 가 요청을 받아도 같이 지워집니다. 그 가게의 기본(합성) 리뷰에 붙인 '답글 달았음' 기록도 그 사장님 것은 함께 지웁니다.
    분류 결과는 글에서 만든 공용 키라, 그 가게의 합성 리뷰가 같이 쓰는 키는 남깁니다. 리뷰 분석 서비스가 분류 결과를 지웠다고 답하지 않으면 `reviews` 는 `null`.
  - 맞춤 마케팅 기록. `marketing`: `cleared`(지웠거나 지울 것이 없음) · `off`(이 서버에서 맞춤 마케팅을 꺼 둠 = 기록이 없음) · `failed`(연결 못 함·거절·주소 설정이 틀림).
  - 못 지운 칸은 `approvals`·`reviews` 가 `null`, `marketing` 이 `failed`. 하나라도 있으면 `complete: false` 와 `message`(어느 가게의 무엇이 남았는지). 그래도 200 이고, 지울 수 있는 것은 지웁니다. 여러 번 해도 안전합니다(이미 지운 것은 0).
- 카드 추천 이유(`card_reasons`)는 가게 공용이라 지우지 않습니다. 보고서(`reports`)는 11/20부터 계정별 저장이라(1.17) 초기화·탈퇴 때 그 사장님 것을 같이 지웁니다(`account.AccountData.clear` → `ReportBook.erase`, 못 지우면 `complete: false`).
- 상권 대화·조건: 상권 세션 쿠키(`market_onboarding_session`)의 경로가 `/api/assistant`·`/api/market` 이라 이 요청에는 오지 않습니다. 화면이 먼저 `DELETE /api/assistant/conversation` 을 부르고(대화), 이 응답이 두 쿠키를 만료시킵니다. 상권 서비스에 남은 분석 조건(업종·위치)은 세션이 끊겨 다시 쓰이지 않고 상권 서비스가 30일 뒤 치웁니다.
- 시연 계정도 같습니다(브라우저마다 다른 시연 사장님이라 그 브라우저 몫만 지워짐).
- 게스트의 `DELETE /api/approvals`('처음부터 다시', `marketing_cleared` true·false·null)와 `DELETE /api/reviews/pasted`(분류 결과는 남김)는 예전 그대로입니다.

**회원 탈퇴 (11/19)**

- 일반 계정은 비밀번호를 다시 확인합니다. 틀리면 로그인 실패처럼 셉니다(아이디 키 `id:<아이디>`와 주소 키). 그래서 탈퇴에서 10분에 10번 틀리면 같은 아이디의 로그인도 429 가 됩니다.
  시연 계정(비밀번호 로그인을 막은 계정)은 비밀번호 없이 됩니다.
- 순서: ① 예시 가게 세 곳(`store_profiles.STORE_IDS`, 가지지 않은 가게 포함)·내 가게 목록·내가 등록한 가게(목록에서 뺀 것 포함, 11/20) 모두에서 그 사장님 기록을 초기화와 같은 방식으로 지움 → ② 다 지웠을 때만 내가 등록한 가게 줄(`stores`)과 계정 삭제
  (`users`. `user_stores`·`auth_sessions` 는 CASCADE, 메모리 방식은 세션을 따로 지움. 그 사장님의 다른 기기 로그인도 끊김) → ③ 세션 쿠키와 상권 쿠키 만료.
- 직접 등록한 가게는 리뷰 분석 서비스가 아직 모르므로(없는 가게 404) 붙여넣은 리뷰는 0건으로 봅니다(초기화도 같음).
- ①에서 하나라도 못 지우면 계정을 지우지 않고 503 `records_left` 입니다. 지운 것은 지운 채로 두고, 다시 하면 남은 것을 이어서 지웁니다.
- 상권 대화는 초기화와 같이 화면이 먼저 `DELETE /api/assistant/conversation` 을 부릅니다.
- 탈퇴한 아이디로는 로그인되지 않고(401 `bad_login`), 같은 아이디로 새로 가입할 수 있습니다(빈 계정). 시연 계정은 '시연으로 시작'을 다시 누르면 빈 계정으로 새로 만들어집니다.

### 1.14 `/api/market/*` — 상권 분석 화면 프록시 (11/18)

`services/web/web/market_proxy.py`. 상권 서비스(`ic26-market`, 127.0.0.1:8766)를 `Host: 127.0.0.1:8766`으로 대신 부릅니다.

| 메서드 | 경로 | 상권 서비스 | 넘기는 쿼리 |
|---|---|---|---|
| GET | `status` | `/health` + `/api/onboarding/data-status`. 늘 200: `{state: ready·no_data·down·off·error, message, data, store}` | |
| POST | `setup[?force=1]` | 지금 가게의 기본 상권·업종·분기로 맞춤. `{status: ok·already·unavailable, state, conditions}` | `force` |
| GET·POST | `profile` · `analysis-selection` | 같은 이름 | |
| GET | `options` · `analysis-options` · `data-status` | 같은 이름 | |
| GET | `sales` · `stores` · `population` · `area-context` · `comparison-options` | 같은 이름 | `expected_revision` |
| GET | `changes` | 같은 이름 | `comparison`(qoq·yoy), `expected_revision` |
| GET | `comparison` | 같은 이름 | `comparison_area_code`, `expected_revision` |
| POST | `data-sync` | 서울 열린데이터광장 실시간 확인 (60초까지 기다림) | |
| GET | `cultural-events` | 서울시 문화행사. 구를 안 주면 가게의 구(예시 세 곳 동작구, 등록 가게는 아래) | `district` |
| GET | `map-config` (11/20) | `/api/onboarding/map-config`. 네이버 지도 브라우저용 공개 ID. 늘 `{client_id, configured}` 두 칸만 | |
| POST | `locations/search` (11/20) | `/api/onboarding/locations/search`. 주소 검색. 본문 `{query}` 그대로 넘김 | |
| POST | `locations/area-preview` (11/20) | `/api/onboarding/locations/area-preview`. 동네 참고 위치. 본문(`{kind: "area", text, district_code, neighborhood_code}`) 그대로 넘김 | |

- 지도·위치 경로 3개 (11/20, 6차 회의 ⑥ 상권 분석 지도 · 새 가게 등록): 응답을 아래 분기 표기 바꾸기에 넣지 않고 그대로 넘깁니다(`market_proxy.RAW_ROUTES`). 주소의 건물 번호(예: '상도로 20241')가 분기 코드처럼 보여 '2024년 1분기'로 바뀌기 때문입니다. `map-config`는 상권 서비스가 다른 칸을 더 실어 보내도 버리고, `client_id`가 영문·숫자·`_`·`-` 1~64자이고 `configured`가 `true`일 때만 `configured: true`입니다(그 밖은 `{client_id: "", configured: false}`). 주소 검색어는 쿼리(20자에서 잘림)가 아니라 본문으로 보냅니다. 상권 서비스가 바쁠 때(429 '주소 조회 중…')는 다른 경로처럼 422로 그 문장을 넘깁니다. 검색 결과(`search_id`·후보 `id`)는 상권 서비스의 세션에 남으므로 같은 `/api/market` 쿠키로 이어서 `profile`을 보내야 합니다.
- `conditions`: `{area_code, area_name, industry_code, industry_name, period, period_label, location_label, revision, home}`. `home`은 지금 가게의 기본 조건인지(서버가 판단).

등록 가게의 기본 조건 (11/20)
- `setup`·서랍의 `POST /api/assistant/setup` 은 등록한 위치·업종 코드·상권 코드·분기를 씁니다(가게를 고치면 5초 안에 따라감). 분기를 정하지 않았으면
  그 상권의 최신 분기, `home`·`is_store_default` 는 상권·업종(·정했으면 분기)으로 판단합니다.
- 역으로 등록한 가게는 `{kind: "station", station_id}`, **주소로 등록한 가게는 저장된 도로명 주소로 `POST /api/onboarding/locations/search` 를 다시 불러**
  맞는 후보(도로명이 같은 것 → 좌표 150m 안 → 후보가 하나뿐일 때)의 `search_id`·`candidate_id` 로 프로필을 넣습니다(후보 id 는 세션마다 다름).
  검색이 실패하거나(422·429 등) 맞는 후보가 없으면 200 `{status: "unavailable", state: "error", message: "등록한 주소로 상권 위치를 찾지 못했어요. …", conditions: null}`.
  이미 같은 주소(공백 무시)·업종이 저장돼 있으면 다시 검색하지 않습니다.
- `status.store`: 가게 줄과 같은 칸 + 등록 가게면 `location_label`·`location_kind`·`district_name`·`industry_code`·`area_code`·`period`.
  주소로 등록한 가게는 `station_name` 이 `null` 이라 화면은 `location_label` 을 쓰면 됩니다.
- 문화행사의 구: 등록한 `district_name`(서울 25개 구일 때) → 도로명 주소·위치 이름에서 읽은 구 → 없으면 `district` 를 빼고 보냄(서울 전체).
- 세션 쿠키 `market_onboarding_session`의 경로는 `/api/market`이라 서랍(`/api/assistant`)과 따로입니다. 화면에서 조건을 바꿔도 서랍 대화가 흔들리지 않습니다.
- 상권 서비스의 입력 오류는 그 상태 그대로(409: 다른 곳에서 조건이 바뀜 → 화면이 서버 조건으로 다시 불러옴, 422), 꺼짐·느림·5xx·이상한 응답은 503 `{"error": {"message", "state"}}`. 500 은 없고, 다른 화면은 영향이 없습니다.
- 사람이 읽는 칸(`message`·`label`·`note(s)`·`warning(s)`·`title`·`summary`·`text`·`sentence`·`period_note` 등)의 분기 코드만 '2026년 2분기'로 바꿉니다. `value`·`value_text`·`period` 같은 숫자·코드 칸은 그대로입니다. `period`만 있는 곳에는 `period_label`을 붙입니다.
- `area-context`(11/18 상권 서비스에 더함): 고른 상권의 직장인구·상주인구·세대·집객시설·지하철역·버스정류장·초중고·병원·상권 변화 지표. 챗봇과 같은 출처 확인 파일(`data/assistant_context`)을 읽기만 하고, 없으면 `status: "not_collected"`(지어내지 않음). 자료마다 실제 기준분기(`period_note`).
- `data-status`·`data-sync`·`cultural-events`의 응답 모양은 `services/market-analysis/README.md` '자료 상태·실시간 발행 확인·문화행사 API'.

### 1.15 서랍의 전 파트 질문과 화면 이동 버튼 (11/18, 11/20 더함)

`POST /api/assistant/messages`는 질문을 이렇게 나눕니다. 가게 기본 질문(`assistant_proxy.store_question`, 1.10)을 먼저 보고, 그다음 `assistant_proxy.domain_question`이 위에서부터 고릅니다: 되묻기(`help`) → 추천 카드(`cards`, 상권 자료 낱말이 없을 때만) → 상권 자료 낱말이면 상권 서비스 → 리포트 → 마케팅 → 고객응대.

| 질문 | 답하는 곳 | 답 | 버튼 (`payload.type: "navigate"`) |
|---|---|---|---|
| 가게 기본(이름·메뉴·화면 위치). 어순이 뒤바뀐 것("메뉴 우리 가게")도 (11/20) | 이 서버 | `store_profile`·`store_guide` | `store_profile`은 없음. `store_guide`는 첫 문장과 같은 분기에서 고름 (아래) |
| 무엇을 물을지 모르는 말 그대로: "우리 가게", "저희 매장", "도와줘", "도움말", "뭐 물어볼 수 있어?", "뭐 할 수 있어?", "기능 알려줘" (`_HELP_EXACT`, 11/20) | 이 서버 | `help_guide`: "어떤 것을 도와드릴까요? 상권 매출·점포 수, 우리 가게 메뉴·정보, 불만 리뷰 답글, 쿠폰·홍보 제안을 물어보실 수 있어요." 상권·리뷰 현황을 조회하지 않음. 추천 질문 3개(상권·가게·리뷰에서 하나씩) | 추천 카드 `{route: "cards"}`, 맞춤 마케팅 `{route: "marketing", sub: "promo"}`, 리뷰 분석 `{route: "analysis", sub: "summary"}`, 상권 분석 표·차트 `{route: "market"}` |
| 추천 카드·오늘 추천·오늘 할 일·브리핑·승인할 글·승인 대기·초안·처리 완료 (`_CARDS_Q`, 11/20. '추천'·'카드' 하나만으로는 아님) | 이 서버 | `cards_guide`: 오늘 추천 카드 수와 제목, 초안·승인 글이 있는 화면 안내 | 추천 카드 `{route: "cards"}`, 승인할 글 `{route: "draft"}`, 맞춤 마케팅 `{route: "marketing", sub: "promo"}` |
| 상권 자료 낱말(상권·유동·인구·점포·주변…)이 있는 질문, 그 밖 | 상권 서비스 (예전 그대로) | 상권 답 | 자료 답에 '상권 분석 표·차트 보기' `{route: "market"}`를 붙임 |
| 리포트·보고서·응대 점수·성적·PDF | 이 서버 | `report_guide` | 종합 리포트·PDF 저장 열기 `{route: "report"}` |
| 쿠폰·본전·할인·남은 재료·재고·광고비·홍보·가게 이야기·마케팅, 인스타·SNS·블로그·플레이스·배민 공지·신메뉴 홍보·손님 늘리기·단골 늘리기(11/20) | 이 서버 | `marketing_guide`: 칭찬 인기 메뉴(카드 ⓑ 와 같은 함수)와 카드 ⓑ 지표를 그 이름 그대로. 이 방문자가 맞춤 마케팅에서 승인한 글이 있으면 "맞춤 마케팅에서 승인한 글 n건(가장 최근 글 종류)이 있어요."를 덧붙임(11/20) | 맞춤 마케팅 `{route: "marketing", sub}` + 추천 카드 ⓑ `{route: "cards"}` |
| 리뷰·불만·답글·캡처·별점·진상·억울… | 이 서버 | `care_guide`: 리뷰·불만 수, 반복 불만 1위·몰린 시간대 | 추천 카드 `{route: "cards"}`, 리뷰 캡처·붙여넣기 `{route: "analysis", sub: "paste"}`, 불만 묶음 `{route: "analysis", sub: "issues"}` |

- 이 서버가 답한 응답은 `answered_by: "web_domain"`, `classification.domain`이 `customer`(`care_guide`·`cards_guide`)·`marketing`·`report`·`general`(`help_guide`). 상권 서비스는 부르지 않고, 상권 서비스가 꺼져 있어도 답합니다.
- `cards_guide` (11/20): 추천 카드 화면과 같은 규칙(`web.cards.plan_cards`, 가게·리뷰·상권 지표)으로 카드 수·제목만 셉니다. 이유 문장을 쓰지 않으므로 `live`에서도 HCX를 부르지 않습니다(`GET /api/cards`는 부름). 만든 초안·승인 대기 수는 브라우저에만 있어 서버가 모르므로 숫자를 적지 않고 화면으로 안내합니다. 리뷰 분석 서비스를 못 읽으면 "…오늘 추천 카드를 지금 불러오지 못했어요."와 같은 버튼으로 답합니다. 화면의 '추천 카드' 내용과 다를 수 있는 곳: `mock`에서 화면은 저장 예시 홍보글의 쿠폰 메뉴와 칭찬 메뉴가 다르면 칭찬 메뉴를 빼지만 서랍 제목은 칭찬 메뉴를 넣은 규칙 그대로입니다.
- 마케팅 승인 건수 (11/20): `GET /api/approvals`와 같은 목록에서 `draft_id`가 `mkt-`로 시작하는 것(맞춤 마케팅 승인, 1.12)을 셉니다. 글 종류(공지·쿠폰 글…)는 저장소의 승인 상세(`card_id`·`kind`)에서 가장 최근 것을 읽고, 못 읽으면 괄호를 뺍니다. 목록을 못 읽으면 이 문장만 빠지고 나머지 답은 그대로입니다. 다른 방문자의 승인은 세지 않습니다.
- 맞춤 마케팅의 `sub`: `promo` 맞춤 홍보 제안 · `leftover` 남은 재료 팔기 · `ad` 광고비 점검 · `story` 가게 이야기 글 · `repeat` 쿠폰 결과 확인 (`assistant_proxy.MKT_SUBS` = `src/features/marketing/logic.js`의 `MKT_SUB`, 시험이 같은지 확인).
- 가게 기본 질문 중 화면 위치(`store_guide`)는 11/20부터 첫 문장을 고르는 분기와 같은 순서로 이동 버튼을 답니다: 답글·댓글·공지·안내문·초안·승인·추천 카드·처리 완료 → 추천 카드 `cards`·승인할 글 `draft`·처리 완료 `done` / 홍보·쿠폰·마케팅·광고 → 맞춤 마케팅 `{marketing, promo}`·추천 카드 / 리포트·보고서·응대 점수 → 종합 리포트 `report` / 그 밖(리뷰·불만) → 리뷰 분석 `{analysis, summary}`·추천 카드. 가게 정보 답(`store_profile`)은 여전히 버튼이 없습니다(시험이 고정). 안내 목록 끝에 '상권 분석'(`assistant_proxy.MARKET_SCREEN`, 메뉴 글자와 같은지 시험)을 더했습니다. 맺음말은 '동네 상권·업종 매출 상담은 이 채팅에서 바로 답하고, 불만 리뷰·쿠폰·리포트를 물으면 지금 가게 현황과 그 화면으로 가는 버튼을 드려요'입니다 (예전 '리뷰 내용은 여기서 답하지 않아요'는 지움). 그래서 '리포트 보여줘'·'리뷰 보여줘'처럼 '보여줘'로 끝나는 말은 화면 위치 안내로 답합니다.
- 화면(`src/features/assistant/state.js`의 `chatChoose`, 버튼 고르기는 `chat.js`의 `chatNavTarget`)은 `navigate`(그리고 `handoff`의 `domain` marketing → `#/marketing`, customer → `#/cards`) 버튼을 `/api/assistant/actions`로 보내지 않고 `navTo`로 그 화면·탭·시작 모드로 바로 갑니다. 창 폭 숫자로 정하지 않고, `drawerCovers()`가 서랍(`#assistant`)과 본문(`#main`)의 실제 위치가 겹치는지 봐서 **덮고 있을 때만** 서랍을 닫고 포커스를 이동한 화면 제목(`#main h1`)으로 보냅니다. 서랍이 본문을 밀어 둔 넓은 화면이면 서랍은 그대로 둡니다 (2.9 (5)).

### 1.16 `/api/account/*` — 계정 안의 가게와 사장님 프로필 (6차 회의 11/20)

`services/web/web/account_api.py`. **전부 로그인 필요**(아니면 401 `login_needed`). 오류 모양은 1.13 과 같습니다: `{"error": {"message": "쉬운 한국어", "state": "<키>"}}`, 응답은 모두 `Cache-Control: no-store`.
저장은 `stores` 표(`data_origin = 'registered'`, 칸 `owner_user_id`·`profile`(JSONB)·`updated_at`)와 `user_stores`(순서). DB_HOST 가 없으면 서버 메모리입니다.

| 메서드 | 경로 | 본문 | 응답 |
|---|---|---|---|
| GET | `/api/account/stores` | | `{stores: [가게 줄]}` 내 가게, 순서대로 |
| GET | `/api/account/stores/{store_id}/summary` | | `{state, reviews, complaints, headline, tone}` 아래. 내 가게가 아니면 403 `not_your_store`. 분석을 못 불러와도 200 |
| POST | `/api/account/stores` | 아래 '가게 칸' 전부 | 201 `{store: 가게 전체}`. 내 목록 **맨 뒤**에 붙음. 세션의 지금 가게는 바꾸지 않음(화면이 이어서 `POST /api/auth/store`). 한 계정 10곳(예시 가게 포함)을 넘으면 422 `store_limit`, 입력 오류 422 `invalid` |
| GET | `/api/account/stores/{store_id}` | | `{store: 가게 전체}`. 직접 등록한 내 가게만. 예시 가게 403 `sample_store`, 남의 가게·없는 가게 403 `not_your_store` |
| PATCH | `/api/account/stores/{store_id}` | 가게 칸 중 바꿀 것만 (`location`·`area`·`menus`·`channels` 는 통째로 바뀜) | `{store: 가게 전체}`. 403 은 GET 과 같음 |
| DELETE | `/api/account/stores/{store_id}` | | `{stores: [가게 줄], store_id}`. **내 목록에서만 뺍니다**(가게 줄과 기록은 지우지 않음). 예시 가게도 뺄 수 있음. 지금 보던 가게였으면 세션의 가게를 남은 첫 가게로(없으면 `null`), 응답의 `store_id` 가 새 값. 목록에 없으면 403 `not_your_store` |
| PUT | `/api/account/stores/order` | `{store_ids: [...]}` | `{stores: [가게 줄]}`. 내 가게 전부를 한 번씩(집합이 다르거나 겹치면 422 `invalid`) |
| PATCH | `/api/account/profile` | `{display_name}` (1~20자, 공백은 하나로) | `/api/auth/me` 와 같은 모양. 틀리면 422 `invalid` |
| POST | `/api/account/password` | `{current_password, new_password}` (8~128자) | `{ok: true}`. 지금 비밀번호가 틀리면 401 `bad_password`(로그인 실패와 같이 셈: 10분에 10번이면 429 `too_many`), 시연 계정 403 `demo_account`, 새 비밀번호 길이 422 `invalid`. 다른 기기의 로그인은 그대로 둡니다 |

저장소에 닿지 못하면 모두 503 `down`. 500 은 없습니다.

가게 줄 (목록·`me.stores` 와 같은 칸 + 두 칸):

```json
{"store_id": "store_3f9a0c1d2e4b", "name": "우리분식", "business_type_name": "분식전문점", "area_name": "상도역 5번",
 "station_name": null, "sample": false, "menu_count": 2, "last_opened": true}
```

- `last_opened`: 세션의 지금 가게인지. `menu_count`: 메뉴 가격 수(예시 가게는 가정 가격 수).

가게 칸 (등록 본문, 가게 전체 응답에도 같은 이름으로 들어감):

| 칸 | 모양 |
|---|---|
| `name` | 1~30자 |
| `industry_code` | 상권 서비스 업종 코드 (영문·숫자 1~20자, 예 `CS100001`) |
| `business_type_name` | 1~30자 (업종 이름) |
| `business_status` | `operating` · `planning` · `exploring` |
| `channels` | 문자열(1~30자) 0~6개. 겹치면 하나로. 안 보내면 `[]` |
| `location` | `{kind: "address" \| "station", label(1~120자), road_address?(~200자), latitude?(-90~90), longitude?(-180~180), station_id?, station_name?(~40자), district_name?(~20자, 예 "동작구")}`. 없는 칸은 `null` 로 저장 |
| `area` | `{area_code(숫자 7자리), name(1~60자), period?("YYYYQ", 예 "20262")}` |
| `menus` | `[{name(1~30자), price(0~1,000,000 정수)}]` 0~30개. 같은 이름은 뒤엣것으로. 안 보내면 `[]` |

- 글자는 앞뒤 공백을 정리하고 제어 문자는 거절합니다. 모르는 칸은 버립니다. 본문은 16KB까지.
- 가게 ID 는 서버가 `store_` + 16진수 12자리로 만듭니다(리뷰 ID·파일 이름 규칙 `[A-Za-z0-9_-]`, `POST /api/auth/store` 의 40자 제한에 맞음).
- 가게 전체 응답 = 가게 줄 + `industry_code`, `business_status`, `channels`, `location`, `area`, `menus`, `created_at`, `updated_at`(한국 시간 ISO).

`summary` (가게 고르기 카드의 한 줄. 홈 브리핑과 같은 리뷰 분석 값(`GET /api/insight` 의 `review_count`·`complaint_count`·`groups`)을 조합하고 새 모델 호출은 없음):

| `state` | 뜻 | `headline` · `tone` |
|---|---|---|
| `ready` | 리뷰·불만 수 있음 | 반복 불만 묶음이 있으면 "포장 누락 3건 반복"·`bad`(`top_issue_id` 묶음, 없으면 건수가 가장 많은 반복 묶음), 없으면 "반복된 불만이 없어요"·`good` |
| `empty` | 리뷰 0건 | "리뷰를 넣으면 분석을 시작해요"·`muted`, 숫자 0 |
| `unavailable` | 분석을 불러오지 못함 | "분석을 불러오지 못했어요"·`muted`, `reviews`·`complaints` 는 `null` |

**등록한 가게로 도는 것 (11/20, `feat/f6-be-services`)**

서비스 사이의 가게 프로필 전달
- 리뷰 분석(8020)·맞춤 마케팅(8030)은 화면 서버와 다른 프로세스라 등록 가게를 직접 모릅니다. 화면 서버가 **등록 가게의 요청마다**
  `X-IC26-Store-Profile` 헤더에 가게 프로필(`shared/store_header.py`, base64url JSON `{v:1, store_id, name, business_type_name,
  industry_code, business_status, channels, menus, location, area}`)을 실어 보냅니다. 예시 세 곳·게스트 요청에는 싣지 않습니다(예전 요청 그대로).
- 서비스는 헤더를 검사해(가게 id `store_` + 16진수 12자만 — 예시 가게 id 는 거절, 12,000자까지, 칸마다 형식) 자기 프로세스의 등록 목록
  (크기 상한 256 LRU)에 넣습니다. 틀리면 400 이고 그 요청은 처리하지 않습니다. 헤더 없이 온 모르는 가게는 예전처럼 404.
- DB 가 있든 없든, WAS 가 몇 대든 같습니다: 화면 서버는 같은 WAS 의 127.0.0.1 서비스를 부르고, 프로필은 요청에 같이 가며, 서비스가 다시 켜져도
  다음 요청의 헤더로 바로 압니다. 붙여넣은 리뷰·기록은 예시 가게와 같은 자리(파일 또는 `reviews`·`review_records`·`marketing_sessions` 표)에
  가게 id 로 저장됩니다. 고객응대의 가게 정보(`care_profile_<가게>.json`)는 예전처럼 WAS 마다의 파일입니다.

화면별
- 홈(`/api/briefing`)·리뷰 분석(`/api/insight`)·추천 카드(`/api/cards`): 리뷰가 0건이면 오류가 아니라 **빈 결과**(리뷰 0·불만 0·묶음 없음·카드 없음)이고,
  등록 가게일 때만 이유 칸이 더해집니다: `empty_reason`("아직 리뷰가 없어요. 리뷰를 붙여넣거나 캡처로 넣으면 분석을 시작해요."),
  `/api/cards` 의 `no_card_a`(불만 카드가 없는 이유) · `no_card_b`("우리 가게 상권 지표가 아직 없어 쿠폰 홍보 카드는 만들지 않았어요. …").
  예시 세 곳의 응답에는 이 칸이 생기지 않습니다. 브리핑의 `store.area_name` 은 등록한 상권 이름입니다.
- 붙여넣기·캡처 저장(`POST /api/reviews`)은 예시 가게와 같은 경로로 분류·묶음을 다시 계산합니다(리뷰 ID `rv_<가게 16진수>_paste_001`, 작성 시각은 실제 시각).
  같은 주제 불만이 3건이면 반복 묶음 → 불만 카드 → 답글·안내문 생성(mock 은 가게 이름으로 쓴 코드 틀)·승인·'답글 달았음' 기록이 됩니다.
- 고객응대(`/api/care/*`): 응대 점수·일일·월간 보고서가 0건에서도 200. 가게 정보(`/profile`)의 처음 값은 등록한 메뉴·가격·도로명 주소·끝인사("<가게> 드림").
- 맞춤 마케팅: 등록한 이름·메뉴·가격·채널(배달의민족·쿠팡이츠·요기요·네이버 → 채널 코드)로 돕니다. 리뷰·카드·상권 지표는 빈 목록입니다
  (**붙여넣은 리뷰와 그 불만 카드는 아직 맞춤 마케팅에 넘기지 않습니다** — 리뷰 답글·안내문은 추천 카드에서 만듦).
  카드가 있어야 만드는 글(배달앱 안내문·답글·쿠폰 홍보 글·개선 소식)은 1.12 의 409 안내(`{"error": {"message", "state": "invalid"}}`)이고,
  `plan` 은 200 + `unavailable_drafts: [{step_id, message}]`(그 글만 빠짐), 새 손님 홍보 글·남은 재료 팔기는 가게 이름·메뉴로 쓴 코드 틀입니다.
- 상권 화면·서랍: 1.14 '등록 가게의 기본 조건'.
- 계정 초기화·탈퇴: 등록 가게의 붙여넣은 리뷰·상태·답글 기록·분류 결과와 맞춤 마케팅 기록도 지웁니다(서비스가 헤더로 그 가게를 알게 되어서).
- 화면 서버는 등록 가게의 Demo·프록시를 64곳까지만 들고 있습니다(가장 오래 안 쓴 것부터 버림, DB 에 못 쓴 승인 기록이 있으면 남김).
- 등록 가게는 `shared/store_profiles.py` 가 예시 세 곳 다음으로 찾습니다(`set_registered_lookup`, 찾은 값은 5초만 기억하고 없다는 결과는 기억하지 않음 → 다른 WAS 에서 고친 이름도 5초 안에 보임). 말투는 기본 해요체, 메뉴 가격은 등록한 메뉴.

### 1.17 `/api/reports/*` — 종합 리포트의 주간·월간 보고서 저장 (6차 회의 11/20)

**쓰는 화면**: 종합 리포트(`#/report`)의 주간·월간 탭과 '저장된 보고서' 목록(`features/report/state.js`), 사장님 프로필의 '보관한 보고서'(`features/report/SavedReportCounts.jsx`, 통합 때 끼움). 서버 코드는 `services/web/web/reports.py`. **일일 보고서는 저장하지 않습니다** (홈과 종합 리포트 위 요약 줄이 `/api/care/report/daily`로 그때그때).

| 메서드 · 경로 | 하는 일 | 성공 |
|---|---|---|
| `GET /api/reports/weekly?period=YYYY-MM-DD` | 주간 보고서 열기. 그 날이 든 월~일, 비우면 이번 주 | 200 |
| `GET /api/reports/monthly?period=YYYY-MM` | 월간 보고서 열기. 비우면 이번 달 | 200 |
| `POST /api/reports/weekly/regenerate?period=` · `POST /api/reports/monthly/regenerate?period=` | 다시 만들기: 새로 계산해 저장본을 덮어씀 (본문 없음) | 200 |
| `GET /api/reports/saved` | 지금 가게 · 이 계정의 저장된 보고서 목록 (기간이 늦은 것부터, 60개까지) | 200 |
| `GET /api/reports/counts` | 내 가게 전체(가진 가게 모두)의 저장된 주간·월간 수 | 200 |

**저장 규칙**
- **로그인한 사장님만 저장합니다.** 자리는 (지금 가게, 방문자 `u-<user_id>`, 종류, 기간). 같은 예시 가게를 여러 계정이 써도 보고서가 섞이지 않습니다 (붙여넣은 리뷰·답글 기록이 계정마다 달라서 보고서도 다름).
- 열기: 저장본이 있으면 **저장본 그대로**(숫자를 새로 계산하지 않음), 없으면 계산해서 저장하고 돌려줍니다. 다시 만들기는 늘 새로 계산해 덮어씁니다(만든 시각도 바뀜).
- 게스트(로그인 안 함)는 계산만 하고 저장하지 않습니다 (`storage: "guest"`, 목록은 빈 것, 수는 0). 저장소(DB)에 닿지 못하면 계산한 보고서를 그대로 주고 `storage: "unavailable"`.
- 표는 `reports`(3.4, `db/schema.sql`). `numbers` 칸에 아래 응답의 `report`·`approvals`·`marketing`을 묶어(`version: 1`) 넣고, `body_text`에 고칠 것 문장, `evidence_ids`에 반복 불만 묶음 id, `prompt_version`은 `rules-1`(문장 틀 판, 모델 호출 없음).

**계산** (모두 규칙, AI 를 부르지 않음): 본문(`report`)은 리뷰 분석 서비스의 `report/weekly` · `report/monthly?compare=true`(1.11) 그대로입니다. 이 서버가 가게·방문자·`now`(이 서버 시각)를 붙여 부릅니다. `approvals`는 이 서버의 승인 기록(1.7과 같은 목록) 가운데 **승인 시각이 그 기간 안**인 것을 저장소의 글 종류로 나눈 수: `reply`(답글 `reply_draft`) · `notice`(안내문 `prevention_notice`·공지) · `promo`(맞춤 마케팅 글·`mkt-`·쿠폰 홍보 `coupon_promo`) · `other`. `marketing`은 `promo_approved`(= `approvals.promo`)만 채우고, **`coupon_usage_rate`·`ad_cost_per_order`·`notice_recurrence`는 `null`** 입니다 (이 보고서가 읽는 자료에 없음. 화면은 '–'). 마케팅 서비스의 보고서(1.12 `report`)는 지금 기간만 세고 기록이 없으면 데모 기록을 주어서 쓰지 않았습니다.

**낡음 판정 (`stale`)**: 저장본을 **기간이 끝나기 전에** 만들었으면(`report.until` < 기간 끝날 23:59:59) 열 때 지금 값을 한 번 더 계산해 견줍니다 (규칙 계산이라 0.1초 안팎). 기간이 끝난 뒤에 만든 저장본은 다시 계산하지 않고 `stale: null`.

```json
"stale": {"checked": true, "is_stale": true, "new_reviews": 3, "reviews_now": 17,
          "responses_changed": false, "approvals_changed": false, "period_closed": false}
```
`new_reviews` = 지금 리뷰 수 − 저장본 리뷰 수, `responses_changed` = 점수 끝값·기한 넘김·묶음 답글 수 중 하나라도 다름, `approvals_changed` = 그 기간 승인한 글 수가 다름, `period_closed` = 저장 뒤에 기간이 끝남. 하나라도 참이면 `is_stale: true` → 화면 안내 띠 "11-17 09:00에 만들어 저장한 보고서예요. 그 뒤 새 리뷰 3건이 들어왔어요 → 다시 만들면 반영돼요." 지금 값을 계산하지 못하면(리뷰 분석 서비스 꺼짐) `{"checked": false}`이고 저장본은 그대로 보입니다. 알려진 빈틈: 기간이 끝난 뒤 만든 저장본은 그 뒤 붙여넣은 리뷰를 지워도(데모 다시 하기) 낡았다고 하지 않습니다.

**열기·다시 만들기 응답 `200`** (줄임)

```json
{"kind": "weekly",
 "period": {"key": "2026-11-16", "start": "2026-11-16", "end": "2026-11-22", "label": "11월 3주", "range": "11/16 ~ 11/22", "in_progress": true},
 "nav": {"prev": "2026-11-09", "next": null},
 "storage": "saved", "saved": true, "created_at": "2026-11-20T23:30:00+09:00", "made_now": false, "stale": {…},
 "report": {"week": "2026-11-16", "review_count": 1, "complaint_rate": 100, "previous": {…}, "topics": […], "suggestions": […], …},
 "approvals": {"total": 0, "reply": 0, "notice": 0, "promo": 0, "other": 0},
 "marketing": {"promo_approved": 0, "coupon_usage_rate": null, "ad_cost_per_order": null, "notice_recurrence": null}}
```

| 칸 | 뜻 | 화면 |
|---|---|---|
| `period.key` | 주간은 그 주 월요일, 월간은 `YYYY-MM`. 다시 부를 때 `period`로 그대로 | 기간 이동·다시 만들기 |
| `period.label` · `range` | 주간 '11월 3주'(그 주 목요일이 든 달의 몇째 주, ISO 주와 같은 셈) · '11/16 ~ 11/22' | 기간 이름 `#rp-period-label` |
| `period.in_progress` | 기간 끝날이 오늘이거나 뒤 | 안내 띠 '아직 진행 중이라…' |
| `nav.prev` · `nav.next` | 앞·뒤 기간 key. 다음이 미래면 `null`, 앞은 1년 전까지 | '‹ 지난주'·'다음 주 ›' 잠금 |
| `storage` · `saved` · `created_at` · `made_now` | 저장 상태 · 만든 시각(한국 시간) · 이 요청이 새로 만들었는지 | 저장 안내 띠 |
| `report` | 1.11 `report/weekly`·`report/monthly?compare=true` 응답 | 타일·고칠 것·주제별 흐름·칭찬·응대 기록 |
| `approvals` · `marketing` | 위 '계산' | '승인한 글' 타일·'마케팅 숫자' |

**목록 `GET /api/reports/saved`**: `{"storage": "saved", "items": [{"kind", "key", "start", "end", "label", "range", "created_at"}]}` (게스트 `{"storage": "guest", "items": []}`). 같은 기간은 하나만(가장 늦게 만든 것). **수 `GET /api/reports/counts`**: `{"storage": "saved", "weekly": 4, "monthly": 1}` (게스트 0·0, 저장소에 닿지 못하면 `null`).

**오류**: `{"error": {"message", "state"}}` (1.11과 같은 모양, `Cache-Control: no-store`, 500 없음). 기간 형식이 틀리거나(`"주간 기간은 YYYY-MM-DD 형식이어야 해요."`) 아직 오지 않은 기간(`"아직 오지 않은 기간이에요."`)은 `400 invalid`. 종류가 `weekly`·`monthly`가 아니면 `422`(FastAPI 기본, 일일은 없음). 리뷰 분석 서비스 문제는 1.11의 `state`(`off`·`down`·`slow`·`busy`·`error`, 503)와 문장 그대로.

**계정 기록 지우기와의 관계**: 계정 초기화·탈퇴(1.13)가 그 사장님의 저장된 보고서도 지웁니다. 저장소의 `reports.delete(가게, 방문자)`를 `ReportBook.erase(가게들, 방문자)`(`app.state.reports`)가 부르고, `account.AccountData.clear`가 가게 기록을 지운 뒤 이어서 부릅니다. 다른 사장님의 보고서는 그대로입니다(`test_reports.py`).

---

## 2부. 화면을 다듬을 때 유지해야 하는 것

(11/20 `feat/react-cutover-ux` 기준으로 새로 씀) 화면은 React 18 + Vite 5 앱 `services/web/frontend/` 하나입니다. 예전 화면(`services/web/web/static/`의 `index.html`·`app.js`·`style.css`)과 그 id 목록·정적 시험 10개는 지웠고, git 이력(`d3113b0` 이전)에만 있습니다. 이 2부의 파일 경로는 따로 적지 않으면 `services/web/frontend/` 아래입니다.

### 2.1 폴더와 서빙

**(1) 폴더**

| 경로 | 하는 일 |
|---|---|
| `index.html` | 빌드의 뼈대. `<div id="root">`와 `/src/main.jsx`만 부릅니다. 첫 그리기 전에 화면 모양(`data-theme`)을 정하는 작은 스크립트(`src/lib/theme.js`와 같은 규칙)와 탭 아이콘(글자로 넣은 SVG)이 있습니다 |
| `src/main.jsx` | 공통 CSS를 `tokens.css` → `base.css` → `layout.css` 순서로 먼저 읽고, `applyTheme()`, `<App />` 그리기, `boot()` (처음 불러오기) |
| `src/App.jsx` | 단계(`state.stage`, 2.2 (5))에 따라 전체 화면을 고른다. `app` 단계면 화면 틀(`Shell`: 왼쪽 메뉴 · 상단 바 · 시험용 안내 띠 · 알림 띠 · 지금 화면 · 바닥 줄 · 서랍), 아니면 로그인·가게 선택·프로필 같은 단계 화면(`STAGE_VIEWS`, 새 가게 등록은 `StoreNew`). 결과 띠(`AcctToast`)는 모든 단계에. 주소 → 화면 표(`SCREENS`), 메뉴 접기와 덮는 메뉴 (2.9) |
| `src/lib/` | `api.js`(`api`·`serviceApi`·`authHeaders`·`authStageOf`·`handleAuthError`, 2.2 (5)), `router.js`(`ROUTES`·`useRoute`·`go`·`navTo`), `media.js`(폭 구간 `useBand`), `theme.js`(화면 모양), `focus.js`(`later`·`focusFirst`), `domain.js`(여러 화면이 쓰는 이름·계산: `GEN_NAMES`·`GEN_ORDER`·`SOURCE_NAMES`·`homeSnap`·`marketScope`·`heroProblem`·`healthProblems`·`modeBandText`·`isTestRun`·`honestyItems` 등) |
| `src/state/` | `store.js`(화면 전체 상태), `stage.js`(단계·`ic26.entered`·`authFail`, 서버를 부르지 않음), `boot.js`(`boot`·`enterApp`·`refresh`·`storeChanged`·`clearStoreData`·`loadHealth`·`loadInsight`), `account.js`(`authDo`·`openStore`·`acctLogout`·`signedOut`, 이름·가게 한 줄 `displayName`·`storeLabel`), `staff.js`(오늘 할 일 `todosOf`, AI 비서 네 명 `staffOf`: 고객 응대·마케팅 상태 '오늘 할 일 없음'·'초안 만들기 전'·'승인 대기 n개'·'오늘 승인 완료'(11/20), 승인 대기 수 `waitingCount`) |
| `src/components/` | `ui.jsx`(공통 부품, 2.3), `Sidebar.jsx`(왼쪽 메뉴), `Topbar.jsx`(상단 바, 화면 모양 버튼 `ThemeButton`), `MobileNav.jsx`(760px 이하 아래 탭·하위 탭) |
| `src/styles/` | `tokens.css`(색·글자·간격 변수와 다크 값), `base.css`(바탕 규칙·공통 부품 모양·공통 `@container` 단계), `layout.css`(화면 틀·폭 구간·서랍·인쇄 때 틀 숨기기) |
| `src/features/<화면>/` | 화면마다 컴포넌트(`*.jsx`), 화면 밖에 남는 모듈 상태(`state.js`), 순수 계산(`calc.js`·`logic.js`·`format.js`·`chat.js`), 모양(`*.css`), 시험(`*.test.js(x)`) |

| `src/features/` 폴더 | 화면 | 들어가는 컴포넌트 | 서버를 부르는 함수 |
|---|---|---|---|
| `flow` | 홈 · 추천 카드 · 승인할 글 · 처리 완료 | `Home.jsx` · `Cards.jsx` · `Draft.jsx` · `Done.jsx` (+ 단계 표시 `Steps.jsx`) | 공통 `api()` (`actions.js`, `Done.jsx`) |
| `analysis` | 리뷰 분석 | `Analysis.jsx` (`Summary` · `Issues` · `PasteTab` · `Capture`) | 붙여넣기는 `api()`, 캡처는 `careApi` (`analysis/careApi.js`) |
| `report` | 종합 리포트 | `Report.jsx` | `careApi` (`report/careApi.js`) |
| `marketing` | 맞춤 마케팅 | `Marketing.jsx` (`Ask` · `ResultCard` · `MarketingReport`) | `mktApi` · `mktPost` (`marketing/api.js`) |
| `market` | 상권 분석 | `Market.jsx` | `marketApi` (`market/state.js` 안) |
| `assistant` | AI에게 묻기 서랍 | `Drawer.jsx` | `drawerApi` (`assistant/chat.js`) |
| `account` | 단계 화면 (11/20): A1 로그인 · A2 회원가입 · A3 가게 선택 · A5 사장님 프로필 · X1 오류 · X2 다시 로그인·권한 없음, 기록 지우기·탈퇴 확인 창 | `Login.jsx` · `Signup.jsx` · `PickStore.jsx` · `Profile.jsx` · `StageCards.jsx` · `AccountDialog.jsx`(확인 창 + `AcctToast`), 공통 틀 `Stage.jsx`(`StageFrame`·`StageCenter`·`StageTitle`·`ModeBand`·`Face`) | `api()` (`state/account.js`, `acctApi.js`의 `listStores`·`storeSummary`·`removeStore`·`orderStores`·`saveProfile`·`changePassword`), `acctPost` · `clearChat` (`acctApi.js`) |
| `stores` | A4 새 가게 등록 · 가게 정보 고치기 (11/20) | `StoreNew.jsx` (`{mode: "signup"\|"add"\|"edit", storeId?}`, 폼은 `StoreForm`) | `storeApi.js`: 계정의 가게는 `api()`(`createStore`·`getStore`·`patchStore`), 상권 서비스는 `serviceApi()`(`marketOptions`·`searchAddress`·`resolveAreas`). 순수 계산(`areaRows`·`defaultArea`·`checkMenus`·`locationBody`·`storePatch`·`errorField` 등)도 이 파일 |

- `analysis/careApi.js`와 `report/careApi.js`는 같은 함수가 두 벌 있습니다 (분석 쪽에만 캡처용 `CAP_WAIT_MS`).

**(2) 빌드**

- `npm run build`(`vite build`)가 `dist/index.html`과 `dist/assets/index-<해시>.js`·`.css`를 만듭니다 (`vite.config.js`: `base: "/"`, `outDir: "dist"`, `assetsDir: "assets"`). `dist/`와 `node_modules/`는 git에 올리지 않습니다 (`.gitignore`).
- 패키지 버전은 `package.json`에 정확히 고정했습니다 (React 18.3.1, Vite 5.4.11, Vitest 2.1.8). Node.js 20 이상이 필요합니다.
- 개발 서버 `npm run dev`(5173번)는 `/api`를 비서 화면 서버(`VITE_API_TARGET`, 기본 `http://127.0.0.1:8000`)로 넘깁니다. 같은 주소처럼 보여서 쿠키(`visitor_id`·`ic26_session`)가 그대로 오갑니다.

**(3) 서버가 주는 주소** (`services/web/web/main.py`)

| 주소 | 무엇을 주나 | 비고 |
|---|---|---|
| `/` | 빌드 폴더의 `index.html` | 빌드 폴더는 `frontend_dist()`: 환경변수 `WEB_FRONTEND_DIST`(앞뒤 공백 무시)가 있으면 그 폴더, 없으면 `services/web/frontend/dist`. 요청마다 파일이 있는지 봐서, 서버를 띄운 뒤 빌드해도 새로고침하면 보입니다 |
| `/` (빌드 없음) | `200` 안내 HTML(`NO_BUILD_HTML`, UTF-8, "`npm ci && npm run build`" 안내) | `500`이 아님. 서버를 띄울 때 경고 로그를 한 번 남김 |
| `/assets/*` | 빌드 폴더의 `assets/` (`BuildFiles`) | 폴더가 없으면 `404`(500 아님). 이 응답에는 `visitor_id` 쿠키를 싣지 않고 로그인 세션도 보지 않음 |
| `/api/*` | 1부의 API | |
| `/static/*` | 없음 (`404`) | 예전 화면 주소 |

- 화면 주소는 `#/today`처럼 `#` 뒤라서 서버는 `/` 하나만 주면 됩니다.
- 화면과 API는 **같은 주소(origin)** 에서 받는 것이 전제입니다 (CORS 없음, 쿠키는 브라우저가 보냄).
- `frontend/public/` 폴더는 없습니다. 만들면 Vite가 그 파일을 `dist/` 맨 위로 복사하지만, 이 서버는 `/`와 `/assets/*`만 주므로 `404`가 됩니다. 그림·글꼴은 `src/` 안에 두고 import 하세요 (빌드가 `/assets/…`로 옮김). 외부 CDN은 쓰지 않습니다.

**(4) 실행·배포 스크립트**

| 스크립트 | 화면 빌드를 어떻게 다루나 |
|---|---|
| `services/web/run.sh` | `WEB_FRONTEND_DIST`가 비어 있으면, `dist/index.html`이 없거나 `src`·`index.html`·`package.json`·`package-lock.json`·`vite.config.js` 중 하나라도 빌드보다 새로우면 띄우기 전에 다시 빌드합니다. `node_modules`가 없거나 `package-lock.json`보다 오래되었으면 `npm ci`부터 합니다. `npm`이 없거나 빌드가 실패하면 서버를 띄우지 않고 멈춥니다 |
| `deploy/make_bundle.sh` | 작업 폴더의 `dist`를 쓰지 않고, 묶을 커밋의 소스로 묶음 안에서 `npm ci && npm run build`를 합니다. 묶음에 `dist/index.html`·`dist/assets/`가 없거나 `node_modules/`가 들어가면 실패합니다. `deploy/BUNDLE_INFO`에 `frontend` 줄을 적습니다. `services/web/frontend`가 없는 예전 커밋은 경고만 하고 빌드하지 않습니다 |
| `deploy/install_web.sh --mode static` | 기본 `STATIC_SRC`는 묶음의 `services/web/frontend/dist`입니다 (`--static-src`로 바꿈). `index.html`과 `assets/`가 없으면 멈추고, 폴더의 **내용**을 `/var/www/ic26/`에 그대로 복사합니다 |
| `deploy/nginx/ic26-static.conf` | `/assets/`는 1년 캐시(`immutable`), 없는 파일은 `404`. `/`는 `index.html`(`no-cache`, 없는 주소도 `index.html`). `/api/`만 앱 서버로. `/docs`·`/redoc`·`/openapi.json`은 막음 |
| `deploy/nginx/ic26-proxy-all.conf` | 모두 앱 서버로 넘김 (위 `main.py` 표대로 줌) |

### 2.2 상태와 화면 전환

**(1) 화면 전체 상태: `src/state/store.js`**

- 외부 상태 라이브러리 없이 `useSyncExternalStore` 하나로 둡니다. `setState(patch)`는 얕게 합칩니다. `Set`·객체는 바꿀 때 새로 만들어 넣습니다 (예: `approved: new Set([...s.approved, id])`).
- `useStore(selector)`의 `selector`는 상태 안의 값을 그대로 돌려줘야 합니다. 매번 새 객체를 만들면 끝없이 다시 그립니다.

| 묶음 | 칸 |
|---|---|
| 서버에서 받은 것 | `health`, `briefing`, `reviewsById`(브리핑의 리뷰 원문), `cards`, `noCardB`, `insight`, `insightError`, `me`(`GET /api/auth/me`, `null`이면 아직 모름) |
| 단계 (11/20, 아래 (5)) | `stage`, `stageError`(X1 에 보일 한 줄), `storeNew`(새 가게 등록의 `{mode, storeId?}`), `storeNewFrom`(새 가게 등록의 [취소]가 돌아갈 단계 `pick`·`profile`), `entered`(자료를 불러온 가게 id), `resume`(로그인이 끝났을 때 `{userId, storeId, loginId}`) |
| 오늘 할 일 진행 (브라우저 메모리에만) | `results`(카드 id → `POST …/run` 응답), `approved`(승인한 글 id `Set`), `approvedLog`(처리 완료 목록, 맞춤 마케팅 것은 `mkt: true`), `pending`(고치는 중인 글), `current`·`draftId`(초안 화면에 보이는 카드·글), `joined`(방금 붙여넣은 리뷰가 들어간 묶음) |
| 화면 공통 | `booted`(들어간 가게의 자료를 한 번 다 불러옴)·`bootError`, `alert`(맨 위 알림 띠), `acctBusy`·`acctNotice`(결과 띠), `drawerOpen`(서랍), `staffMarket`(`/api/market/status`), `mktServer`(서버에 남은 맞춤 마케팅 승인 수), `nav`(`navTo` 요청), `mktResetSeq`·`mktCleared`('처음부터 다시'), `epoch` |

- 진행 상태는 새로고침하면 사라집니다 (`localStorage`·쿠키에 두지 않음, 3.1). 들어간 가게 id 만 `sessionStorage`의 `ic26.entered`에 둡니다 (아래 (5)).
- 예전 `authOpen`·`acctOpen`(로그인 창·내 계정 창)은 11/20에 없앴습니다. 켜도 아무 일도 없습니다.

**(2) 불러오기: `src/state/boot.js`**

- `boot()`: `GET /api/health`(기다리지 않음, 모든 단계의 시험용 안내 띠) + `GET /api/auth/me` → 단계를 정합니다 (아래 (5)). 가게 자료는 부르지 않습니다.
- `enterApp()`: 지금 가게(`me.store_id`)를 `entered`·`ic26.entered`에 적고 `app` 단계로 가서 `storeChanged()`.
- `storeChanged()`: 가게 자료를 비우고(`briefing`·`cards`·진행, `booted: false`) `epoch`를 1 올린 뒤 `GET /api/health` → `refresh()` → (기다리지 않고) `GET /api/market/status`. 끝나면 `booted: true`. 실패하면 알림 띠에 문장을 띄우고 `bootError`를 채웁니다 (401·409·403 으로 단계가 바뀐 것이면 알림 띠는 띄우지 않음). 가게 열기와 기록 지우기 뒤에 부릅니다.
- `refresh()`: `GET /api/briefing` → `GET /api/cards` → `GET /api/insight` → (기다리지 않고) `GET /api/approvals`. 카드의 id·근거(`card_id`·`review_ids`·`snapshot_ids`)가 이전과 다르면 만든 글·승인 표시·고친 내용을 버립니다 (`emptyFlow`).
- `clearStoreData()`: 다시 읽지 않고 가게 자료·진행만 비우고 `epoch`를 1 올립니다 (로그아웃·탈퇴·새 로그인).

**(3) 화면마다의 모듈 상태와 `epoch`**

화면 컴포넌트는 메뉴로 들어올 때마다 새로 그려집니다. 그래서 다른 화면에 다녀와도 남아야 하는 것은 컴포넌트 밖 모듈에 둡니다. 각 모듈은 `epoch`가 바뀌면 자기 상태를 처음으로 되돌립니다.

| 모듈 | 담는 것 | 처음으로 돌리는 함수 |
|---|---|---|
| `features/flow/state.js` | `busy`(만드는 중인 카드와 누른 곳), `regen`(다시 만드는 중인 글), `note`, `armed`('카드 전체 다시 만들기'를 한 번 누름), `picks`(사장님이 바꾼 점검 수칙) | `useFlow` 안의 `syncEpoch`, `resetFlow` |
| `features/analysis/state.js` | 고른 탭, 붙여넣기 칸·결과, 캡처 진행 | `syncEpoch(epoch)` (탭은 남김) |
| `features/report/state.js` | 고른 탭(주간·월간, 해시가 아님), 탭마다 연 보고서(`/api/reports/*` 응답)·기간, 저장 목록, 위 요약 줄·응대 점수 값 | `resetIfStoreChanged()` |
| `features/marketing/state.js` | 대화·결과 카드·보고서 | `sync()` (`epoch`와 `mktResetSeq` 둘 다 봄) |
| `features/market/state.js` | 분석 조건·받은 자료·탭·비교 결과 | `resetIfStoreChanged()` |
| `features/assistant/state.js` | 서랍 대화·조건·setup 시도 여부 | `chatReset(epoch, open)` |

- `App.jsx`는 지금 화면을 `<Screen key={`${name}-${key}-${epoch}`} />`로 그립니다. 가게가 바뀌거나 같은 화면을 다시 열면 화면이 새로 마운트됩니다.
- 기다리는 사이 가게가 바뀌면 늦게 온 응답을 버립니다 (`runCard`·`approve`·붙여넣기·캡처 등이 시작할 때의 `epoch`와 견줌). 새 비동기 동작을 더할 때도 이 방식을 따르세요.

**(4) 화면 전환: `src/lib/router.js`**

- 주소 해시 `#/이름` 하나로 화면이 바뀝니다. `ROUTES`는 8개입니다 (2.5). `currentRoute()`는 모르는 이름·해시 없음을 `today`로 봅니다.
- `useRoute()`는 `{name, key}`를 줍니다. `go(name)`은 같은 화면이면 해시를 그대로 두고 `key`만 올려 다시 그립니다.
- `navTo(name, sub)`: 상태의 `nav`에 `{name, sub, seq}`를 넣고 `go(name)`. 각 화면은 `nav.seq`가 바뀔 때 한 번 자기 화면 요청인지 보고 그 탭·모드로 갑니다. 리뷰 분석 탭(`AN_TABS`: `summary`·`issues`·`paste`), 상권 분석 탭(`MKV_TABS`: `sales`·`stores`·`pop`·`compare`), 맞춤 마케팅 시작 모드(`MKT_SUB`: `promo`·`leftover`·`ad`·`story`·`repeat`). `ROUTES`에 없는 이름은 조용히 무시합니다.
- 화면이 바뀌면 `App.jsx`가 맨 위로 스크롤하고 덮는 메뉴를 닫습니다. 그 화면의 `PageHead`가 마운트될 때 제목 `h1`(`tabIndex={-1}`)에 포커스를 줍니다. **화면마다 `PageHead`(= `h1` 하나)를 둡니다.** 서랍의 화면 이동도 `#main h1`으로 포커스를 보냅니다 (2.9).
- **화면을 새로 더하려면** 네 곳을 같이 고칩니다: `lib/router.js`의 `ROUTES`, `App.jsx`의 `SCREENS`, `components/Sidebar.jsx`의 `GROUPS`, `services/web/tests/frontend_src.py`의 `ROUTES` (시험이 넷이 같은지 봄, 2.4). 그리고 이 문서 2.5. 메인 화면 밖의 전체 화면(로그인·가게 선택 같은 것)은 해시 주소가 아니라 단계로 더합니다 (아래 (5)).

**(5) 단계: `src/state/stage.js` (11/20, Figma '06 설계 기준 화면' 여정 F)**

로그인해야 쓰는 서비스입니다 (게스트 체험 없음, 6차 회의). 해시 주소 8개는 그대로 두고, 그 바깥의 전체 화면은 상태의 `stage`로 고릅니다 (`App.jsx`). 해시 주소는 `app` 단계에서만 화면을 바꾸고, 다른 단계에 있는 동안에도 주소는 그대로 남습니다.

| `stage` | 화면 (Figma) | 컴포넌트 |
|---|---|---|
| `boot` | 빈 바탕 (`/api/auth/me`를 기다리는 동안. 대시보드가 스쳐 보이지 않게) | `account/Stage.jsx` `StageBoot` |
| `login` · `signup` | A1 로그인 · A2 회원가입 (왼쪽 소개 + 오른쪽 카드, 760px 이하 1단) | `account/Login.jsx` · `Signup.jsx` |
| `pick` | A3 가게 선택 | `account/PickStore.jsx` |
| `store-new` | A4 새 가게 등록 (`storeNew.mode`: `signup` 가입 직후 · `add` 가게 더하기 · `edit` 정보 고치기) | `stores/StoreNew.jsx` (흐름은 2.6 '새 가게 등록') |
| `profile` | A5 사장님 프로필 | `account/Profile.jsx` |
| `app` | 메인 화면 (해시 주소 8개 + 서랍) | `App.jsx` `Shell` |
| `error` · `expired` · `forbidden` | X1 오류 · X2 다시 로그인(401) · X2 권한 없음(403) | `account/StageCards.jsx` |

전환 규칙:

| 언제 | 어디로 |
|---|---|
| 부팅: `GET /api/auth/me`가 실패(네트워크·5xx)하거나 응답에 `notice`가 있음 | `error` ([다시 시도] = `boot()` 다시) |
| 부팅: `authenticated: false` | `login` |
| 부팅: 로그인 상태이고 `sessionStorage["ic26.entered"]`가 `me.store_id`와 같고 `me.stores` 안에 있음 | `app` (`enterApp`, 새로고침해도 보던 화면) |
| 부팅: 그 밖의 로그인 상태 | `pick` |
| 로그인·시연 시작 성공 | `pick` (새 로그인은 가게 선택부터: `ic26.entered`를 지움). 단 `expired`에서 다시 로그인했고 같은 사장님(`user_id`)·같은 가게(`me.store_id` = `entered`)면 `app`으로 바로 (해시 화면·진행 그대로) |
| 회원가입 성공 | `store-new` (`mode: "signup"`) |
| A3 [이 가게 열기] | `POST /api/auth/store {store_id}` → `ic26.entered` 저장 → `storeChanged()` → `app`, 홈(`today`). 이미 자료를 받아 둔 가게면 서버를 부르지 않고 `app` 홈으로만 |
| 상단 바 [바꾸기] · A5 [가게로 돌아가기] | `pick` · (들어가 있던 가게가 지금 가게이고 내 가게면) `app`, 아니면 `pick` |
| 상단 바·왼쪽 메뉴의 이름·'프로필', A3 [사장님 프로필] | `profile` |
| A3·A5 '+ 새 가게 등록', A5 [정보 고치기] | `store-new` (`add` · `edit` + `storeId`). `storeNewFrom`에 온 단계(프로필이면 `profile`, 그 밖은 `pick`)를 적음 |
| A4 [가게 등록하고 시작] | `POST /api/account/stores` → A3 [이 가게 열기]와 같은 `openStore` (`POST /api/auth/store` → `ic26.entered` → `storeChanged()` → `app` 홈) |
| A4 고치기 [저장] · A4 [취소] | `profile` (바뀐 칸만 `PATCH`) · `storeNewFrom` (가입 직후는 `pick`) |
| 로그아웃·탈퇴 | `ic26.entered`를 지우고 서랍을 닫고 가게 자료를 비운 뒤 `login` |
| 로그인한 단계(`pick`·`store-new`·`profile`·`app`·`expired`·`forbidden`)에서 받은 401 `login_needed` | `expired` ([로그인] → `login`, 아이디 칸을 채워 둠) |
| 같은 때의 409 `no_store` · 403 `not_your_store` | `pick` (`ic26.entered` 지움) · `forbidden` ([가게 선택으로]·[로그아웃]) |

- `app`을 떠나면 서랍을 닫습니다 (`setStage`). 단계가 바뀌면 그 화면의 제목 `h1`(`#stage-title`, `tabIndex={-1}`)이 포커스를 받습니다 (메인 화면의 `PageHead`와 같은 방식).
- 로그인 전 단계(`boot`·`login`·`signup`·`error`)에 늦게 온 401·409·403 은 무시합니다.
- `sessionStorage` 접근은 늘 `try { … } catch` 안에서 합니다 (못 쓰면 새로고침 때 가게 선택부터).

**(6) 로그인 표시와 상태 코드: `src/lib/api.js`**

- 로그인한 동안(`me.authenticated`)은 모든 요청에 헤더 `X-IC26-Signed-In: 1`을 붙입니다 (`authHeaders()`). 서버는 이 표시가 있는데 세션이 끝났으면 게스트로 답하지 않고 401 `login_needed`를 줍니다 (1.13).
- 공통 `api()`·`serviceApi()`는 실패한 응답의 `status`·`error.state`를 `handleAuthError()`에 넘겨 위 표대로 단계를 바꾸고, 오류에 `authHandled: true`를 답니다 (부른 쪽이 알림 띠를 또 띄우지 않게). `authStageOf(status, state)`는 그 대응표 (401 `login_needed` → `expired`, 409 `no_store` → `pick`, 403 `not_your_store` → `forbidden`, 그 밖은 `null`).
- 로그인 실패(401 `bad_login`)·비밀번호 틀림(401 `bad_password`)·시연 계정(403 `demo_account`) 같은 것은 단계를 바꾸지 않고 부른 화면이 그대로 보여 줍니다.
- 공통 `api()` 없이 따로 `fetch`하는 곳은 헤더에 `...authHeaders()`를 펼쳐 넣고, 실패한 응답의 `status`·`error.state`로 `handleAuthError({status, state})`를 불러 같은 규칙을 따릅니다 (11/20 통합 뒤 정리). 붙인 곳:
  `features/market/state.js`(`marketApi`), `features/marketing/api.js`(`mktApi`), `features/analysis/careApi.js`(`careApi`), `features/assistant/state.js`의 `call`(= `chat.js`의 `drawerApi` + 헤더·단계 전환. `chat.js`는 서버 시험이 node 로 그대로 불러 보므로 React 를 부르는 `lib/api.js`를 import 하지 않고, `drawerApi`는 `options.headers`를 기본 헤더 위에 더하고 오류에 `status`를 답니다),
  `components/NaverMap.jsx`(`/api/market/map-config`), `features/account/acctApi.js`(`acctPost`·`clearChat`). 새 가게 등록(`features/stores/storeApi.js`)은 `api()`·`serviceApi()`를 써서 따로 할 일이 없습니다.
  `features/report/careApi.js`는 종합 리포트 작업(다른 브랜치)에서 고칩니다. 시험은 `src/lib/authFetch.test.js`.

### 2.3 공통 부품과 디자인 토큰

**(1) `src/components/ui.jsx`**

| 부품 | 쓰는 법 |
|---|---|
| `Button` | `variant`: `ghost`(기본)·`primary`·`text`·`danger`, `size`: `small`·`big`. `ref`를 넘길 수 있음. 늘 `type="button"`(바꾸려면 `type`) |
| `Badge` | `tone`: `ok`·`warn`·`bad`·`brand` |
| `Panel` | 제목 `h2` + 오른쪽 `sub`·`actions` + 내용. `titleId`를 주면 `aria-labelledby`가 이어짐 |
| `PageHead` | 맡은 비서(`owner`) · 제목 `h1` · 설명(`sub`) · 오른쪽 버튼. 마운트될 때 `h1`에 포커스 |
| `Icon` · `Logo` | 24×24 선 그림 (아래 (2)) · 초록 네모 안의 말풍선 |
| `StatTile` | 숫자 타일. `tint`: `green`·`mint`·`lime`·`sage`, `icon`은 `ICONS` 이름 |
| `TopicBar` | 주제 막대. `kind`: `praise`(초록)·`complaint`(빨강), `hot` |
| `FeatureCard` | 기능 카드 (맞춤 마케팅 시작 모드). `title`이 곧 아이콘 이름 |
| `Notice` | 안내 띠. `tone`, `role`(기본 `status`). 내용이 비면 그리지 않음 |
| `Empty` | 빈 안내: 아이콘 하나(기본 `빈 목록`) + 제목 + 한 줄 + 버튼 |
| `Tabs` | 탭 줄. 탭 id는 `${idPrefix}-tab-${id}`, `aria-controls`는 `${idPrefix}-panel-${id}`. ←/→/Home/End로 옮김. 탭 내용은 부르는 쪽이 `role="tabpanel"`로 그림 |
| `Dialog` | `<dialog>` + `showModal()` (포커스가 안에 머물고 Esc로 닫힘). `onClose`(닫아 달라는 요청) · `onCancel` · `onClosed`(실제로 닫힌 뒤 한 번). `showModal`이 없는 환경(jsdom)에서도 동작 |

**(2) 아이콘 `ICONS`**: 키가 곧 부르는 쪽이 넘기는 이름입니다. 모르는 이름은 중립 아이콘(원 안의 작은 원, `data-icon="generic"`)으로 그립니다.

| 묶음 | 키 | 누가 그 이름을 넘기나 |
|---|---|---|
| 왼쪽 메뉴 8 | `홈` `추천 카드` `승인할 글` `처리 완료` `리뷰 분석` `상권 분석` `종합 리포트` `맞춤 마케팅` | `Sidebar.jsx`가 **메뉴 글자 그대로** 넘김 |
| 숫자 타일 6 | `리뷰` `불만` `반복 불만` `상권 매출` `승인` `고침` | `Home.jsx`·`Done.jsx`의 `StatTile` |
| 맞춤 마케팅 6 | `맞춤 홍보 제안` `남은 재료 팔기` `광고비 점검` `가게 이야기 글` `쿠폰 결과 확인` `마케팅 보고서` | `marketing/Ask.jsx`가 **서버가 준 보기 글자 그대로** 넘김 |
| 공용 | `AI` `시간` `계정` `닫기` `빈 목록` | 상단 바·메뉴·`Empty` 등 |

- 메뉴 글자나 시작 모드 글자를 바꾸면 `ICONS`의 키도 같이 바꿉니다 (안 바꾸면 중립 아이콘이 나옴).
- 그림 규칙: `viewBox="0 0 24 24"`, `fill="none"`, `stroke="currentColor"`, 굵기 1.8, 둥근 끝, `aria-hidden="true"`, `focusable="false"`. 경로는 `P("M…")` 도우미로 넣습니다. **`P("…")` 안의 글자는 `c9` 검사에서 빠지지 않습니다** (2.4).

**(3) 디자인 토큰 `src/styles/tokens.css`** (Figma '부여 AI'의 변수 '토큰', 11/19 가독성 개선판)

| 묶음 | 변수 |
|---|---|
| 바탕 | `--page`(회색 바탕), `--panel`(카드), `--surface`, `--chip`, `--hover`, `--active`, `--side` |
| 글자·선 | `--ink`, `--ink-2`, `--muted`, `--line`, `--line-strong`, `--field-line` |
| 초록 | `--accent`(주 버튼·현재 메뉴), `--accent-hover`, `--accent-ink`, `--accent-text`(초록 글자), `--brand`(점·막대에만), `--brand-soft`, `--focus`, 단계 `--green-50`~`--green-900`, 타일 색 4쌍 `--tint-{green,mint,lime,sage}`·`-bg` |
| 상태 | `--ok`·`--ok-bg`, `--warn`·`--warn-bg`·`--warn-dot`, `--bad`·`--bad-bg`·`--bad-line`, `--hot`, `--bar`·`--bar-strong`, `--scrim` |
| 모양 | `--shadow-card`·`--shadow-over`·`--shadow-tab`, `--r-sm`~`--r-full`, 간격 `--s-4`~`--s-40` |
| 글자 | `--font`, `--fs-title` 28 · `--fs-panel` 20 · `--fs-body` 16 · `--fs-small` 14 · `--fs-num` 32 · `--fs-button` 15 (+ `--lh-*`) |
| 틀 | `--side-w` 260px, `--top-h` 72px, `--drawer-w` 400px, `--col` 880 · `--col-wide` 1040 · `--col-narrow` 720px |

- 다크 값은 **두 곳에 같은 내용**으로 있습니다: `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { … } }`와 `:root[data-theme="dark"] { … }`. 토큰을 바꾸거나 더하면 두 곳을 같이 고칩니다. 대비 계산값(WCAG AA 4.5:1 이상)이 파일 주석에 있습니다.
- 새 색을 화면 CSS에 직접 쓰지 말고 토큰을 씁니다 (규칙 6). 토큰만 쓰면 밝게·어둡게가 저절로 맞습니다.

**(4) 화면 모양 (`src/lib/theme.js`)**

- 고르는 값은 `system`(기본) · `light` · `dark`. `<html data-theme="light|dark">` 하나로만 알리고(시스템이면 속성을 지움) 색은 `tokens.css`가 정합니다.
- 상단 바의 화면 모양 버튼이 누를 때마다 시스템 → 밝게 → 어둡게로 바꿉니다. 버튼 `aria-label`·`title`이 "화면 모양: 지금 (누르면 다음)"을 알립니다.
- 고른 값은 `localStorage`의 `ic26.theme`에 둡니다 (시스템이면 지움). 주소 뒤 `?theme=light|dark`는 그 화면에서만 고정하고 저장하지 않습니다.
- `index.html`의 작은 스크립트가 같은 규칙으로 첫 그리기 전에 `data-theme`을 정합니다 (깜박임 방지). **규칙을 바꾸면 `theme.js`와 `index.html` 두 곳을 같이 고칩니다.**

**(5) `base.css`에 꼭 있어야 하는 규칙**

| 규칙 | 이유 |
|---|---|
| `[hidden] { display: none !important; }` | 탭 내용·서랍·버튼을 `hidden`으로 숨김. `display`를 주는 다른 규칙이 이기면 숨길 것이 보임 |
| `.sr` | 화면에는 안 보이고 읽기 프로그램에만 읽히는 글 |
| `:focus-visible { outline: 3px solid var(--focus) }`, `h1:focus { outline: none }` | 키보드 포커스는 보이게, 화면을 열 때 제목에 준 포커스는 테두리 없이 |

- 탭 줄: 화면 열(`.col`, 격자)에 바로 놓인 탭 줄은 `.col > .tabs { justify-self: start; }`(base.css)로 글자 폭만큼만 차지합니다 (11/20. 예전 `analysis.css`·`Marketing.css`의 같은 규칙은 지움). 상권 분석의 탭 줄(`.mk-tabbar` 안)도 넓을 때는 글자 폭, 탭 칸이 779px 이하면 2×2 로 칸을 채웁니다.
- CSS 순서: `main.jsx`가 공통 CSS를 먼저 읽고, 화면 CSS(`features/*/*.css`)는 `App`을 읽을 때 그 뒤에 붙습니다. 같은 무게의 규칙이면 화면 CSS가 공통 규칙을 덮습니다 (`Market.css` 맨 위 주석의 "base.css 보다 먼저 읽혀서"는 지금 순서와 반대로 적혀 있음).

**(6) 코드가 이름으로 찾는 것** (이름을 바꾸면 그 동작이 조용히 멈춤)

| 이름 | 어디서 찾나 | 무엇에 |
|---|---|---|
| `#root` | `main.jsx` | 앱을 그리는 자리 (`index.html`) |
| `#side-menu`(`nav.side`) · `.menu-item` · `.menu-toggle` | `App.jsx` | 덮는 메뉴의 첫 포커스·Tab 가두기 범위, 바깥 누름 판단 (2.9) |
| `#menu-toggle` | `App.jsx`(ref) | 덮는 메뉴가 닫히면 포커스를 돌려받음 |
| `#main`(`<main class="content">`)과 그 안의 `h1` · `.app.menu-closed` | `assistant/state.js`의 `drawerCovers`·`focusTitle` | 서랍이 본문을 덮는지, 화면 이동 뒤 제목 포커스 |
| `#assistant` · `#assistant-q` · `#assistant-retry` · `#assistant-home` · `#assistant-scroll` · `#assistant-log` 안의 `[data-msg]`·`.chat-msg.user` · `#assistant-close` | `assistant/state.js`·`Drawer.jsx` | 서랍 포커스·스크롤 |
| `[aria-controls="assistant"]` (`.top` 안 먼저) · `dialog[open]` | `Drawer.jsx` | 서랍을 닫을 때 돌려줄 버튼(연 버튼이 사라졌으면), 대화상자가 떠 있으면 Esc는 그 창이 먼저 |
| `#acct-user`(상단 바 이름 → 프로필) · `#acct-store`(상단 바 [바꾸기] → 가게 선택) · `#auth-demo`(시연 시작) · `#auth-login`·`#auth-signup`(폼) · `#stage-title`(단계 화면 제목) · `#acct-dialog`(기록 지우기·탈퇴 확인 창) · `#prof-pw` · `#prof-up-<가게>`·`#prof-down-<가게>`·`#prof-remove-<가게>`·`#prof-keep-<가게>` | `Topbar.jsx`·`account/*`·시험(`App.test.jsx`·`account.test.jsx`·`stages.test.jsx`) | 시험이 이름으로 찾음, 프로필의 순서 바꾸기·빼기 뒤 포커스. 예전 `#acct-login`(게스트 [로그인])·`#auth-dialog`(로그인 창)는 11/20에 없앰 |
| `#sn-name` · `#sn-industry` · `#sn-status` · `#sn-ch-<채널 code>` · `#sn-addr` · `#sn-line` · `#sn-station` · `#sn-loc-change` · `#sn-area-<상권 코드>` · `#sn-area-box` · `#sn-area-note` · `#sn-menu-name-<줄>` · `#sn-menu-price-<줄>` · `#sn-menu-add` · `#sn-err-<칸>` · `#sn-form-err` | `stores/StoreNew.jsx`·`StoreNew.test.jsx` | 새 가게 등록의 오류 칸 포커스(틀린 첫 칸으로)와 `aria-describedby`(칸 ↔ 그 칸의 오류 줄), 줄 지우기·더하기 뒤 포커스 |
| `#paste-text` | `analysis/PasteTab.jsx` | 예시 문장·빈 글일 때 포커스 |
| `#an-tab-<탭>` · `#mk-tab-<탭>` · `#mkt-tab-chat` · `#mkt-tab-report` | `Tabs`·`analysis/state.js`·`Market.jsx`·`marketing/*` | 탭 키보드 이동, `navTo`로 연 탭에 포커스 |
| `#mkt-options` · `#mkt-retry` · `#mkt-card-<n>`(`-title`) · `#mkt-idea-<n>`(`-title`·`-q`) · `#mkt-text-<n>-<열쇠>` | `marketing/state.js`·`ResultCard.jsx` | 맞춤 마케팅의 포커스·스크롤 |
| `#rp-tab-weekly`·`#rp-tab-monthly`(탭, `Tabs` idPrefix `rp`)·`#rp-panel-*` · `#rp-period-label` · 리포트 안의 `details` · `details[data-rp-opened]` | `Report.jsx` | 저장된 보고서 [열기] 뒤 그 탭으로 포커스·기간 이름으로 스크롤, 인쇄 직전에 펼쳤다가 인쇄 뒤 다시 접기 |
| `aria-controls`의 대상 `side-menu` · `assistant` · `auth-forgot`(로그인의 '비밀번호를 잊었어요') · `prof-pw`(비밀번호 바꾸기 폼) | `Topbar.jsx`·`Login.jsx`·`Profile.jsx` | 연결이 실제 id를 가리켜야 함. 상단 바 이름 버튼은 창이 아니라 화면(프로필)으로 가므로 11/20부터 `aria-controls`가 없음 |
| `.mode-band` | `account/account.css` | 단계 화면에서는 `.stage-page .mode-band { order: 0 }` (760px 이하 `layout.css`의 `order: 2`는 메인 화면 틀 순서용) |

**(7) 코드가 켜고 끄는 상태** (CSS가 이 상태를 보고 모양을 정함. 모양은 바꿔도 되지만 상태를 바꾸는 방식은 그대로)

| 상태 | 누가 | 어디에 쓰나 |
|---|---|---|
| `.app`의 `menu-closed` · `menu-over` · `drawer-open` | `App.jsx` | 메뉴 접힘·덮는 메뉴·서랍 밀기 (2.9) |
| `aria-current="page"` · `aria-current="step"` · `aria-current="true"` | 메뉴 항목 · 단계 표시 · 고른 카드·글 | 현재 표시 |
| `aria-selected` · `aria-pressed` · `aria-expanded` | 탭 · 기능 카드 · 메뉴 토글·서랍 버튼 | 고른 것·열린 것 |
| `<html data-theme>` | `lib/theme.js`·`index.html` | 다크 토큰 |
| `<html class="rp-view">` | `Report.jsx` (리포트 화면에 있는 동안) | `report.css`의 인쇄 규칙 (아래 (8)) |
| `hidden` 속성 | 탭 내용·서랍·버튼 | `[hidden]` 규칙 |

- 서버가 준 글은 JSX로만 넣습니다 (`dangerouslySetInnerHTML` 없음, 규칙 5). 새 탭으로 여는 링크에는 `rel="noopener"`를 붙입니다.

**(8) 종합 리포트 인쇄 ('전체 리포트 PDF 저장')**

- `#rp-pdf`('PDF 저장', 11/20 이름 바꿈)를 누르면 `window.print()`로 브라우저 인쇄 창이 열립니다. 서버에 새로 묻지 않고 **지금 탭의 보고서(저장본)** 와 아래 칸이 그대로 나옵니다 (주간·월간 모두. 숨은 탭은 나오지 않음). 월간 탭에는 리뷰 분석 서비스의 A4 인쇄용 페이지 링크 `#rp-print`('A4 인쇄용')도 있습니다 (그 페이지는 저장본이 아니라 그때 계산한 값). 아직 불러오는 칸이 있으면 버튼을 잠그고 최대 20초(`RP_PDF_WAIT_MS`) 기다립니다. 그사이 다른 화면으로 가면 인쇄하지 않습니다.
- 인쇄 규칙은 `report/report.css`의 `@media print` 한 덩어리이고, `@page`(A4 세로, 여백 12mm)만 빼면 모든 선택자가 `html.rp-view`로 시작합니다. 그래서 다른 화면에서 인쇄하면 리포트 규칙이 먹지 않습니다. 틀(왼쪽 메뉴·상단 바·서랍·바닥 줄·안내 띠)은 `layout.css`의 `@media print`가 늘 숨깁니다.
- 리포트 안에서 숨기는 것: 제목 줄(`.page-head`), 탭·기간 이동 줄(`.rp-bar`), 저장 안내 띠(`.rp-saved`, 만든 시각은 머리글에), 모든 버튼, `.rp-print`(A4 인쇄용 링크), `.rp-screen`(저장된 보고서 목록·PDF 안내 포함), 화면 안 이동 링크(`a[href^="#"]`), `href` 없는 링크, `role="button"`. 그래서 링크·버튼을 더해도 인쇄 CSS를 고칠 필요가 없고, 감싼 줄까지 종이에서 빼려면 `class="rp-screen"`을 답니다. 상권 '원본' 링크는 주소를 글자로 덧붙입니다.
- 인쇄 직전(`beforeprint`, 또는 버튼): 머리글 `#rp-print-head`(가게 이름 · 출력한 날 · 오늘 요약 날짜 · '주간 보고서 11월 3주 (11/16 ~ 11/22)' · 'MM-DD HH:MM에 만든 보고서' · 'AI 문장 아님' 한 줄 · 시험용이면 `health.mode_notice`)를 채우고, 접힌 `details`를 펼치고, 점수 추이 그래프를 종이 폭(`RP_PRINT_W` 680)·낮은 높이(`RP_PRINT_H` 112)로 다시 그립니다. 인쇄 뒤(`afterprint`) 되돌립니다.
- 칸은 쪽 사이에서 잘리지 않고(`break-inside: avoid`), 두 칸 묶음(`.rp-pair`)은 한 줄기로 쌓이며, 색은 `print-color-adjust: exact`로 찍힙니다.
- 인쇄 바탕은 `html.rp-view`·`body`를 흰색·검은 글자로 정하고, 다크 색 토큰은 `tokens.css`에서 `@media screen` 안에만 있어 인쇄에는 늘 밝은 토큰이 쓰입니다 (11/20 고침).

**(9) 지도 부품 `src/components/NaverMap.jsx`** (11/20, 6차 회의 ⑥. 모양은 `components/NaverMap.css`)

상권 서비스의 원래 화면(`services/market-analysis/app/static/onboarding/onboarding.js`의 `loadMapSDK`·`candidatePolygons`·`analysisBounds`·`renderAnalysisMap`)을 React로 옮긴 것입니다. 상권 분석 화면의 지도가 쓰고, 새 가게 등록 화면의 위치 지도도 같은 부품을 씁니다.

```jsx
<NaverMap className center={{lat, lng}} zoom={16} marker={{lat, lng, title}}
          areas={[{id, name, geometry, kind: "selected" | "nearby", disabled, note}]}
          onAreaClick={(id) => …} fit="areas" | "marker"
          label="상권 경계 지도" listLabel="주변 상권 (누르면 비교)" list>{범례}</NaverMap>
```

| props | 뜻 |
|---|---|
| `center` · `zoom` | 처음 가운데(마커·상권이 없을 때)와 확대 단계(기본 16). 아무것도 없으면 서울시청 |
| `marker` | 가게 위치 마커 하나. `title`은 마우스를 올리면 보이는 글 |
| `areas` | 상권 경계. `geometry`는 GeoJSON `Polygon`·`MultiPolygon`(좌표 **[경도, 위도]**, analysis-options의 `candidates[].geometry` 그대로). `selected`는 초록 실선·옅은 초록 채움, `nearby`는 회색 점선, `disabled`는 더 옅은 점선. 좌표가 틀린 다각형은 그리지 않음 |
| `onAreaClick(id)` | 다각형이나 아래 목록 버튼을 누름 (`disabled`여도 부름. 고를 수 없는 이유는 부르는 화면이 알림) |
| `fit` | `areas`(기본): 모든 상권 + 마커가 보이게 범위를 맞춤 (여백 40px). `marker`: 마커로 가운데·`zoom` |
| `list` | `onAreaClick`이 있으면 기본으로 지도 아래에 같은 선택을 하는 목록(`ul.nmap-list`)을 그림: `selected`는 표시만(`aria-current`), 나머지는 버튼(`disabled`면 `aria-disabled`). 다각형은 키보드로 고를 수 없고 지도가 안 뜰 때도 쓰기 위한 것. 자기 목록(라디오 등)이 있는 화면은 `list={false}` |
| `label` · `listLabel` | 지도 칸(`role="region"`)과 목록의 읽기 이름 |
| `children` | 지도(또는 실패 안내)와 목록 사이에 그림. 범례는 `ul.nmap-legend` + `span.nmap-key.pin`·`.selected`·`.nearby`, 지도에만 있는 칸은 `li.nmap-only`(지도가 안 뜨면 숨김) |

- **SDK 불러오기** `loadNaverMaps()`: 모듈에 Promise 하나라 지도가 여럿 떠도, 화면을 떠났다 와도 한 번만 부릅니다. `GET /api/market/map-config`(로그인 표시 헤더, 401·409·403 이면 단계 전환 · 11/20) → `configured`가 `true`면 `<script src="…maps.js?ncpKeyId=…">`를 `head`에 붙임 → 15초(`MAP_TIMEOUT_MS`) 안에 `onload`. 네이버 SDK가 인증에 실패하면 전역 `window.navermap_authFailure`를 부르는데(스크립트를 읽은 뒤, 지도를 그린 뒤에도 옴) 이 이름을 이 부품이 정합니다. 실패는 `kind`가 있는 Error: `no_key`(`configured: false`) · `auth` · `timeout` · `error`(map-config 실패·스크립트 오류).
- **상태**: 불러오는 중(지도 칸에 '지도를 불러오는 중…') → 준비됨 / 키 없음 · 인증 실패 · 시간 초과 · 연결 실패. 안 뜨는 상태에서는 지도 칸을 숨기고(`hidden`) 그 자리에 한 줄(`.nmap-fail`, `role="status"`)과 [다시 시도]만 둡니다: "지금은 지도를 볼 수 없어요." / "지도를 불러오지 못했어요." / "지도를 여는 데 시간이 너무 걸려요." + 목록이 있으면 "아래 목록에서 상권을 고를 수 있어요." 키 이름·콘솔 설정은 화면에 쓰지 않습니다. [다시 시도]는 `retryNaverMaps()`(받은 결과와 붙인 스크립트를 버림) 뒤 map-config부터 다시.
- **그리기**: 다각형 하나마다 `naver.maps.Polygon`(MultiPolygon은 다각형 수만큼), `LatLng(위도, 경도)`로 순서를 뒤집음. 색은 그릴 때 `tokens.css`의 `--accent`(고른 상권 선)·`--brand`(채움)·`--muted`(주변 상권)를 읽음. 마우스를 올리면 지도 왼쪽 위에 상권 이름(`.nmap-hover`, JSX). 마커 그림은 `.nmap-pin`(`--bad`). props가 바뀌면 지우고 다시 그리되, 내용이 같은 새 배열이면 그대로 둡니다(사장님이 옮긴 지도를 되돌리지 않게). 언마운트하면 리스너·다각형·마커를 지우고 `map.destroy()`.
- **높이**: 본문 폭에 맞춰 240~420px (`clamp(240px, 38cqi, 420px)`). 지도 타일은 밝은 색 그대로입니다(다크에서도).
- **함께 내보내는 것**: `loadNaverMaps` · `retryNaverMaps` · `onNaverAuthFailure` · `geometryPaths(geometry)`(GeoJSON → 다각형마다 고리마다 `[{lat, lng}]`) · `areasBounds(areas, point)`(`{south, west, north, east}` 또는 `null`) · `locationPoint(location)`(프로필 위치 → `{lat, lng}`, 동네면 `reference_point`) · `MAP_FAIL_TEXT` · `MAP_TIMEOUT_MS` · `MAP_SDK_URL`, 시험용 `resetNaverMapsForTest`.
- **실제 지도가 뜨는 조건** (코드 밖): 상권 서비스(`ic26-market`)의 환경 변수 `NAVER_MAPS_CLIENT_ID`에 NCP Maps(Dynamic Map) 애플리케이션의 Client ID, 그 애플리케이션의 Web 서비스 URL에 화면을 여는 주소(예: 서비스 도메인, 시험이면 `http://localhost:8000`)가 등록되어 있어야 합니다. 없으면 '지금은 지도를 볼 수 없어요', URL이 등록되지 않았으면 인증 실패 안내가 뜹니다.

### 2.4 시험이 지키는 것

**(1) 서버 시험이 React 소스를 글자로 읽는 곳**

서버 시험(`services/web/tests/`)은 빌드나 node 없이 `frontend/src`를 글자로 읽습니다. 읽는 도구는 `tests/frontend_src.py`입니다: `read`(파일), `const_value`(`[export] const 이름 = …`의 값, 괄호 짝까지), `function_text`(`function 이름(…) {…}` 또는 `const 이름 = …`), `regex_const`(`const 이름 = /…/깃발;`), `squash`(띄어쓰기·줄바꿈을 빼고 작은따옴표를 큰따옴표로), `node_eval`(node가 있으면 모듈을 실제로 불러 봄). **띄어쓰기·따옴표 모양(prettier)은 상관없지만, 파일 위치·이름·`const` 선언 모양을 바꾸면 깨집니다.** 그때는 `frontend_src.py`와 시험도 같이 고칩니다.

| # | 화면 쪽 (`frontend/` 아래) | 서버 쪽과 같아야 하는 것 | 시험 |
|---|---|---|---|
| 1 | `index.html` + `src/` 모든 글 파일 (**시험 파일·주석 포함**) | 금지 글자 없음: `replay`(대소문자 무시), `c9`(도형 속성 `d=`·`points=`·`viewBox=`·`transform=`의 값과 `#rrggbb` 색 코드는 뺌), `id="record"`, `/api/review-insight`, `analysis-link`, `리뷰 분석 화면에서`, `review_service.url}/`, `rs.url`. 파일을 20개 넘게 읽어야 함 | `test_web.py` `FrontendSource.test_forbidden_strings_are_nowhere_in_the_screen` |
| 2 | `src/` (시험 파일 뺌) 어딘가 | `mode_notice` 글자가 있음 (지금 `lib/domain.js` `modeBandText`, `Marketing.jsx`, `Report.jsx`) | `…test_the_mock_notice_comes_from_health` |
| 3 | `src/`(시험 파일 뺌)의 따옴표로 시작하는 `'/api/…'` 글자 전부 (주석 안도 셈) | 이 서버(프록시 포함)에 있는 경로. 뒤를 이어 붙이는 앞부분(`'/api/cards/'`, `'/api/market/'`)은 그것으로 시작하는 경로가 있으면 됨. `/api/health`·`/api/briefing`·`/api/cards`·`/api/insight`·`/api/approvals`·`/api/reviews`가 꼭 있어야 함 | `…test_screen_calls_only_paths_this_server_has` |
| 4 | `mktApi("…")`·`mktPost("…")`의 첫 글자, `'/api/care/…'` 글자 | `marketing_proxy.ROUTES`(+ `health`), `care_proxy.ALLOWED` 안. `/api/care/report/daily`·`/api/care/response`·`/api/care/report/monthly/print`가 있어야 함 (11/20: 주간·월간 보고서는 `/api/reports/*`로 옮김) | `…test_proxy_paths_the_screen_uses_are_forwarded` |
| 5 | `lib/router.js` `ROUTES` · `App.jsx` `SCREENS`의 키 · `components/Sidebar.jsx` 메뉴 칸(`["주소", "글자"]`) | 셋 다 8개 주소로 같고 겹치지 않음 (= `tests/frontend_src.py` `ROUTES`) | `…test_eight_routes_match_between_router_app_and_menu` |
| 6 | `src/`(시험 파일 뺌)의 `#/이름`(주석 포함) · `go("…")` · `navTo("…")` | 8개 주소 안. 서버 `assistant_proxy.py`의 `nav(…)` 버튼 주소도 8개 안이고, 리뷰 분석 탭은 `features/analysis/calc.js` `AN_TABS` 안 | `…test_every_route_the_screen_or_the_server_points_to_exists` |
| 7 | `features/flow/calc.js`의 `failedOf`·`checksOf`·`statusOf`·`measureIds`, `features/flow/actions.js`의 `runCard`, `lib/domain.js`의 `GEN_NAMES` | 점검 상태 규칙(점검 실패 → 확인 필요 → 점검 통과)과 카드 만들기 본문(`measures`)이 `scripts/measure_live.py`의 `draft_status`·`card_run_body`와 같음. `GEN_NAMES`의 키가 `GENERATOR_NAMES`와 같고 `reply_draft`·`prevention_notice` 이름도 같음. node가 있으면 `statusOf`·`measureIds`를 실제로 돌려 견줌 | `test_measure_live.py` `StatusRule.test_rules_are_still_the_ones_on_the_screen`, `StatusRuleRunsLikeTheScreen` |
| 8 | `features/assistant/chat.js`의 `CHAT_QUARTER`·`chatQuarter`·`chatPeriod` | `CHAT_QUARTER` 패턴 글자 = `assistant_proxy.QUARTER_IN_TEXT`, 깃발 `g`, 뒤돌아보기 `(?<`와 `/` 없음. 바꾸는 식·`typeof t === "string"`·`/^[0-9]{4}[1-4]$/.test(p)`가 그대로. node가 있으면 서버 함수와 결과를 견줌 | `test_assistant_ux.py` `QuarterOnScreen` |
| 9 | `chat.js`의 `CHAT_STARTERS` (+ `assistant/state.js`가 `./chat.js`에서 가져와 씀) | 6개: 상권 서비스로 가는 질문 3 · 고객응대 1 · 마케팅 2. 가게 기본 질문이 아님. `assistant_proxy.BACK_TO_MARKET` 문장이 모두 들어 있음 | `test_assistant_ux.py` `TestStoreQuestionRules.test_the_drawer_starters_are_market_questions` |
| 10 | `Sidebar.jsx` 메뉴 글자 | `assistant_proxy.SCREENS`의 이름(리뷰 분석·추천 카드·승인할 글·처리 완료·맞춤 마케팅·종합 리포트)이 모두 있음. `#/market` 글자 = `assistant_proxy.MARKET_SCREEN`('상권 분석') | `test_assistant_ux.py` `test_screen_names_match_the_menu_on_the_page`, `test_assistant_domains.py` `Answers.test_store_questions_are_unchanged` |
| 11 | `features/marketing/logic.js`의 `MKT_SUB`·`MKT_MODES` | `MKT_SUB` = `assistant_proxy.MKT_SUBS`, `MKT_MODES`의 키에 그 다섯 글자가 있음 | `test_assistant_domains.py` `Classify.test_marketing_modes_match_the_screen` |
| 12 | `features/flow/calc.js`의 `REPLACES_MAX`·`replacesOf` | `REPLACES_MAX` = `demo.REPLACES_MAX`(20), `replacesOf`에 `.slice(0, REPLACES_MAX)` | `test_regen_one.py` `ScreenSendsAtMostTheServerLimit` |
| 13 | `features/analysis/calc.js`의 `PASTE_SAMPLES` (`{ text, rating }` 칸) | 4개. 앞 3개는 정해 둔 문장, 4번째는 억울한 리뷰 시연 문장이고 저장 예시 답글이 있음 | `test_pasted_reply.py` `PasteSampleAndStoredExample` (C6 저장본이 있을 때만) |

- **조심할 점**: 시험 1·3·6은 파일 전체 글자를 읽어서 **주석에도 걸립니다.** 주석에 `#/settings` 같은 없는 주소나 따옴표로 감싼 `'/api/…'`를 쓰면 깨집니다. 단계 화면(로그인·프로필 등)에 `#/이름` 주소를 만들지 않는 것도 이 시험 때문입니다 (2.2 (5)). 가게 id 가 들어가는 경로는 템플릿 글자(`` `/api/account/stores/${enc(id)}/summary` ``)로 쓰면 `$` 앞(`/api/account/stores/`)만 경로로 읽히고, 서버에 그것으로 시작하는 경로가 있으면 통과합니다 (`features/account/acctApi.js`). `c9`는 `P("…")` 안의 경로 글자, 문자열, 주석, 시험 파일에서도 걸립니다.
- node로 실제로 돌리는 시험(7·8)은 `flow/calc.js`·`assistant/chat.js`를 그대로 import 합니다. 이 두 파일과 그것이 부르는 `lib/domain.js`에는 React·CSS import를 넣지 않습니다. node가 없으면 그 몇 건만 건너뜁니다.
- 화면 문구는 서버 시험이 지키지 않습니다 (위 표의 메뉴 글자·시작 모드 글자·예시 문장·글 종류 이름만). 대신 아래 vitest가 몇몇 문구를 확인합니다.

**(2) 서빙 시험** (화면 소스를 읽지 않음)

- `test_frontend_dist.py`: 기본 빌드 폴더가 `services/web/frontend/dist`, `WEB_FRONTEND_DIST`가 먼저(빈 값·공백이면 기본), 빌드가 없으면 `/`가 `200` 안내 HTML(+ 경고 로그)이고 `/assets/*`는 `404`, 띄운 뒤 빌드해도 보임, `/assets/*`에 `visitor_id` 쿠키 없음, `/static/*`는 `404`.
- `test_storage_web.py` `test_cookie_also_comes_with_the_page_and_errors_but_not_static_files`: 페이지(`/`)와 오류 응답에는 쿠키를 싣고, `/assets/*`에는 싣지 않음.
- API 모양을 지키는 시험(예: `/api/insight`의 키 집합 `Demo.INSIGHT_KEYS`, 승인 기록)은 화면 파일을 읽지 않지만, 서버의 칸 이름을 바꾸면 깨집니다.

**(3) 화면 시험 (vitest)**

`npm test`(= `vitest run`, jsdom, `src/**/*.test.{js,jsx}`). 서버·node 없이 가짜 `fetch`로 돕니다.

| 영역 | 파일 | 보는 것 |
|---|---|---|
| 화면 틀 | `src/App.test.jsx` | (app 단계 전제) 덮는 메뉴의 첫 포커스·Tab 가두기·Esc·바깥·[메뉴 닫기] 뒤 토글 버튼 포커스, 메뉴 항목으로 이동하면 그 화면 제목 포커스, 메뉴의 '프로필'로 프로필 단계, 승인 대기 칩(`#top-waiting`), 시험용 안내 띠 한 곳·바닥 줄, 사장님 칸('{이름} 사장님' · '프로필 · 로그아웃')·가게 칩('(가상)'·[바꾸기], 아래 줄은 `me.stores` 값: 여는 중·브리핑이 없어도 '불러오는 중'으로 남지 않음), 휴대폰 계정 그림 단추(`#acct-user`) |
| 단계 전환 | `src/features/account/stages.test.jsx` | 부팅 분기(게스트 → A1 · 로그인 + 들어간 가게 → app · 로그인만 → A3 · 신원 실패·`notice` → X1과 [다시 시도]), 로그인 → A3 → 가게 열기 → app 홈과 새로고침 유지, [바꾸기]로 같은 가게를 다시 열면 서버를 안 부름, 로그아웃 → A1, 회원가입 → 새 가게 등록, 401 `login_needed` → X2 → 같은 사장님·가게면 하던 화면, 다른 사장님이면 A3, 409 → A3, 403 → 권한 없음, 로그인 전 단계의 늦은 401 무시, `X-IC26-Signed-In` 헤더, 가게 자료는 app 단계에서만 부름 |
| 틀 도우미 | `src/lib/shell.test.js` · `src/lib/theme.test.js` · `src/state/staff.test.js` | 안내 띠·바닥 줄 문구와 폭 구간(760·761~1024·그 위, 소수 폭), 화면 모양 순서·저장, 오늘 할 일·AI 비서 상태, 리뷰 0건의 핵심 문제('아직 들어온 리뷰가 없어요')·데이터 분석 비서('아직 리뷰 없음'·모두 붙여 넣은 리뷰면 한 번만). `src/lib/domain.test.js`: `textOr`·`shortPlace`(주소 원문 → '마포구 와우산로 94')·`cleanLabel`·`isOwnStore` (11/21) |
| 공통 부품 | `src/components/ui.test.jsx` | 아이콘(자리 글자 없음, 그림이 서로 다름, 로고), 빈 안내, `Dialog` |
| 흐름 | `features/flow/calc.test.js` · `screens.test.jsx` | 순수 계산, 네 화면 그리기와 카드 → 초안 → 승인 → 완료 → 처음부터 다시의 API 순서, 리뷰 0건 홈의 [리뷰 넣기]·[상권 분석 보기](예시 가게 홈은 그대로), 브리핑을 못 받은 홈. 11/21: 직접 등록한 가게의 상권 칸 [상권 분석에서 보기], ⓑ 카드가 없을 때의 칸, 기본 문장 글의 칩·목록 배지·다시 만들기 안내(`isFallback`·`draftStateText`·`regenNote`) |
| 새 가게 등록 | `features/stores/StoreNew.test.jsx` · `StoreNew.map.test.jsx` | 업종 → 역 → 상권 후보(기본 inside) → 고르기 → 메뉴 → 저장 본문 → 가게 열기 → app 홈, 업종 먼저 안내, 업종·위치를 바꾸면 후보 다시(예전 선택 유지·비움), 상권 서비스 409 면 revision 다시 읽기, 후보 실패 [다시 시도], 주소 찾기(후보 고르기 · 하나면 바로 · 후보 없음·서울 밖·조회 불가 → 역으로 · 2자 미만 · 검사 오류 문장), 빈 폼·메뉴 줄 오류와 `aria-describedby`·포커스, `store_limit`·칸 이름이 든 서버 오류, 중복 누름·등록 뒤 열기 실패, [취소], 고치기(채우기 · 바뀐 칸만 PATCH · 위치를 안 바꾸면 상권 서비스 안 부름 · [위치 바꾸기]/[위치 바꾸지 않기] · 업종만 바꾸면 역은 다시 묻고 주소는 다시 찾게 · 예시 가게 · 저장 뒤 결과 띠), 업종 칸은 음식 업종만(`foodIndustries`), '가게 등록 2 / 3', 순수 계산. 지도 시험(가짜 지도): `list={false}`, 마커, 상권 `selected`·`nearby`·`disabled`, 다각형으로 고르기·고를 수 없는 이유 |
| 로그인 헤더 | `src/lib/authFetch.test.js` | 따로 fetch 하는 곳(맞춤 마케팅·캡처·상권 분석·서랍·지도 설정)의 `X-IC26-Signed-In`과 401·409·403 단계 전환, 게스트는 헤더 없음 |
| 리뷰 분석 | `features/analysis/calc.test.js` · `Analysis.test.jsx` | 탭·`navTo`, 붙여넣기 뒤 다시 읽기, 캡처 후보를 `source: "capture"`로 저장 |
| 서랍 | `features/assistant/chat.test.js` · `Drawer.test.jsx` | 분기 표기 등 순수 계산, 선택지 위치, 기준 범위 칩과 안내 한 줄, 화면 이동 뒤 포커스, `drawerCovers`, 조건을 맞추는 동안의 안내에 주소 원문 대신 짧은 위치(11/21) |
| 계정 화면 | `features/account/account.test.jsx` | A1: 로그인 실패 때 비밀번호 유지(401 `bad_login`은 단계 유지)·`keep`·'비밀번호를 잊었어요' 한 줄·시연 버튼은 시험용 실행 + `demo_login`일 때만. A2: 입력 규칙·`stores: []`. A3: 마지막 본 가게 맨 앞·주 버튼·칩, '(가상)', 요약 `tone` 색, `unavailable`이면 숫자 줄 없음, 불러오는 동안 자리, 0곳. A5: 이름 저장(PATCH), 비밀번호 틀림은 그 자리에, 예시 가게·[정보 고치기], 빼기 확인 뒤 DELETE, 순서 PUT, 확인 창의 '되돌릴 수 없어요'·비밀번호 칸·Esc, 탈퇴 뒤 A1 |
| 상권 | `features/market/format.test.js` · `Market.test.jsx` | 처음 불러오기 순서, 머리 고지 한 줄, 비교 탭, `epoch`, `navTo` 탭, 지도 구역(출처·범례·고른/주변 상권·마커), 주변 상권을 누르면 비교 탭에서 그 상권을 고름(지도·목록 둘 다), 고를 수 없는 이유 한 줄, 주소로 등록한 가게의 업종 바꾸기 안내. 11/21: 머리줄 가게 한 줄(`storeLineOf`, 역이 없으면 등록한 위치를 짧게, 'null' 없음), 주소로 등록한 가게는 업종 칸이 처음부터 잠기고 까닭 한 줄, 조건을 바꾸는 동안 숫자 흐리게·라벨은 숫자와 함께, 자료 상태 한 줄('2024년 3분기~2026년 2분기 자료를 볼 수 있어요.', `dataStatusText`) |
| 지도 부품 | `src/components/NaverMap.test.jsx` | 가짜 `window.naver.maps`로: SDK·map-config 한 번만, 다각형 수와 좌표 순서(위도·경도), 누르기·올리기, 키 없음·인증 실패(그린 뒤 포함)·시간 초과·연결 실패 안내와 다시 시도, props 변경·언마운트 정리, `fit`, 좌표 도우미 |
| 맞춤 마케팅 | `features/marketing/logic.test.js` · `Marketing.test.jsx` | health → meta → step → 시작 모드 → plan → 승인, 결과 칸 라이브 영역, 안내 띠가 겹치지 않음 |
| 종합 리포트 | `features/report/format.test.js` · `Report.test.jsx` | 'AI 문장 아님' 고지는 머리 한 곳, 출처·우리 가게 매출 아님·점수 변동 근거는 남음. 11/20: Figma D1 차례(머리 → 오늘·점수 줄 → 탭·기간 → 저장 띠 → 타일 4 → 고칠 것·주제별 흐름 → 마케팅 숫자 → … → 저장된 보고서), 탭은 해시를 바꾸지 않음, 기간 이동·다음 잠금, 저장 안내 띠 문장(저장·저장본·낡음·게스트), [다시 만들기] = POST regenerate, 목록 [열기], 리뷰 0건·'–', `SavedReportCounts`. 11/21: 끝난 기간의 '고칠 것' 제목·문장(`fixTitle`·`fixItems`), 직접 등록한 가게의 상권 요약 [상권 분석 보기], 지난 불만 한 줄(0건이면 없음)·승인 기록 한 줄('이 계정에서 지금까지 승인한 글 n건') |

- 문구를 바꾸면 그 문구를 찾는 vitest가 깨질 수 있습니다. 문구가 맞으면 시험을 같이 고칩니다.

### 2.5 화면 주소

화면은 **주소 해시**로 바뀝니다 (`#/이름`, 2.2). 이름은 바꾸지 않습니다 (규칙 2, 서버 서랍의 화면 이동 버튼도 이 이름을 씀).

| 주소 | 메뉴 묶음 · 메뉴 글자 | 컴포넌트 | 화면 |
|---|---|---|---|
| `#/today` | (맨 위) 홈 | `features/flow/Home.jsx` | 대시보드 (11/20 Figma 06 B1 배치): 핵심 문제 한 줄(이름표 + 굵은 글), 숫자 타일 4개, 오늘 할 일(넓은 칸, 할 일마다 테두리 상자 + 오른쪽 버튼 모양 상태) · '담당 비서 현황'(320px 칸, AI 비서 네 명 + 첫 글자 동그라미, 11/20 패널 제목), 불만 시간대 · 주제 차트(주제는 '상위 n개'), AI에게 묻기 줄(오른쪽 '묻기'). 리뷰 0건이면 기간 줄을 빼고 핵심 문제('아직 들어온 리뷰가 없어요', `heroProblem`)·할 일·차트에 짧은 빈 안내, '오늘 할 일' 아래 버튼은 다음에 할 일 두 개 [리뷰 넣기]·[상권 분석 보기] (11/20). 브리핑을 못 받으면 핵심 문제는 '리뷰를 불러오지 못했어요'. 직접 등록한 가게(`me.stores`의 지금 가게 `sample: false`, `lib/domain.js` `isOwnStore`)에서 브리핑에 상권 지표가 없으면 '상권 저녁 매출' 칸은 '–'·'상권 지표 없음' 대신 [상권 분석에서 보기](→ `#/market`)와 '{상권} 상권' (11/21, 예시 가게는 그대로). '담당 비서 현황'의 데이터 분석 비서는 리뷰가 모두 붙여 넣은 것이면 '붙여 넣은 리뷰 n건 정리 끝' 한 번만 (11/21) |
| `#/cards` | 오늘 처리 · 추천 카드 | `features/flow/Cards.jsx` | "무엇을 할까요?" 카드 최대 2장을 위아래로 한 장씩 (11/20 B2), 카드 ⓐ의 점검 수칙 고르기(회색 상자), 만들기 버튼 옆 '근거 보기'(`aria-expanded`, 근거는 버튼 줄 아래에 펼침). 카드 ⓐ는 있는데 ⓑ(쿠폰 홍보)가 없으면 그 자리에 'ⓑ 쿠폰 홍보 · 오늘은 쿠폰 홍보 카드가 없어요' 칸(서버 `no_card_b` 까닭 + [맞춤 마케팅에서 홍보 제안 받기] → `navTo("marketing", "promo")`). 서랍의 '추천 카드 ⓑ 쿠폰 홍보글 보기'로 와도 빈 화면이 아님 (11/21) |
| `#/draft` | 오늘 처리 · 승인할 글 | `features/flow/Draft.jsx` | 진행줄('승인 n / 전체 · 지금 글 이름' + 카드 전체 다시 만들기, 막대 없음), 손님 리뷰(근거 건수는 패널 오른쪽, 리뷰마다 회색 상자), 초안 상자(글 칸 → 점검 칩 줄 → 고칠 곳 상자 → 승인·복사·다시 만들기. 점검을 못 넘어 기본 문장으로 바꾼 글(`checks.used_fallback`)은 초록 '점검 통과' 없이 주의 색 '기본 문장으로 바꿈' 칩과 '리뷰 내용과 맞는지 확인하고 고쳐서 승인해 주세요' 한 줄(11/21), 점검 상태 규칙 `statusOf`는 그대로), 초안 목록(기본 문장 글은 '승인 대기 · 기본 문장' 배지, `listBadges`) (11/20 B3) |
| `#/done` | 오늘 처리 · 처리 완료 | `features/flow/Done.jsx` | 승인 결과 타일 → '승인한 글'(글마다 이름 · 시각 / 글 앞부분 한 줄 + 복사) → 고른 점검 수칙(✓) → 서버 처리 기록(패널 모양 접힌 칸) → '홈으로'·'처음부터 다시' (11/20 B4 순서) |
| `#/analysis` | 살펴보기 · 리뷰 분석 | `features/analysis/Analysis.jsx` | 탭 3개: 요약(`summary`) · 불만 묶음(`issues`) · 리뷰 넣기(`paste`: 붙여넣기 + 캡처로 넣기) |
| `#/market` | 살펴보기 · 상권 분석 | `features/market/Market.jsx` | (11/20 Figma F1 배치) 분석 조건, 지도(고른 상권·주변 상권 경계·가게 위치, 2.3 (9)), 핵심 지표 4칸, 세부 탭 4개(`sales` 매출 · `stores` 점포·개폐업 · `pop` 유동·배후인구·집객시설 · `compare` 타 상권 1:1 비교), 서울시 자료 최신화, 우리 동네 문화행사 |
| `#/report` | 살펴보기 · 종합 리포트 | `features/report/Report.jsx` | (11/20 Figma D1) 다시 만들기·PDF 저장 · 오늘 요약·응대 점수 한 줄 · 주간·월간 탭과 기간 이동 · 저장 안내 띠 · 타일 4(리뷰·불만 비율·응대 점수·승인한 글) · 고칠 것(진행 중인 기간은 '이번 주에 고칠 것'·'이번 달에 고칠 것', 끝난 기간(`period.in_progress === false`)은 '이 주 기록에서 고칠 것'·'이 달 기록에서 고칠 것', 문장의 '이번 주·이번 달'도 '이 주·이 달'로, 리뷰 0건이면 '이 주에는 들어온 리뷰가 없었어요'. `report/format.js` `fixTitle`·`fixItems`, 11/21) · 주제별 흐름 · 마케팅 숫자 · 손님 칭찬 요약 · 응대 기록(점수 추이·반복 불만) · 응대 점수 · 답글을 기다리는 불만 · 상권 요약 · 마케팅 요약 · 저장된 보고서 |
| `#/marketing` | 키우기 · 맞춤 마케팅 | `features/marketing/Marketing.jsx` | 안내 문구 "선택한 조건으로 손익을 계산하고 우리 가게 홍보 방법과 초안을 만들어요."(11/20). 탭 두 개: 맞춤 제안(시작 모드 다섯 개 → 질문 → 결과 카드 → 고쳐서 승인) · 마케팅 보고서(주간·월간). 첫 화면의 기능 카드는 흰 패널 없이 바탕 위에, 질문 칸의 비서 질문은 '마케팅 비서' 이름표가 붙은 테두리 상자 (11/20 Figma 06 M1) |

- 메뉴 묶음과 순서는 `Sidebar.jsx`의 `GROUPS`입니다 (홈 / 오늘 처리 / 살펴보기 / 키우기). 760px 이하의 아래 탭·하위 탭(`components/MobileNav.jsx`)도 이 묶음을 씁니다 (11/20).
- 추천 카드·승인할 글·처리 완료 위에는 단계 표시(`Steps.jsx`, 지금 단계에 `aria-current="step"`)가 있습니다.
- `#/draft`와 `#/done`은 만든 글·승인한 글이 없으면 빈 안내와 버튼 하나(추천 카드 보기 `#/cards` / 승인할 글로 `#/draft`)를 보입니다.
- 화면 안 링크: 로고 `#/today`, 홈 '리뷰 분석 보기' `#/analysis`, 상단 바 승인 대기 칩 `#/draft`, 종합 리포트의 `#/cards`·`#/marketing`.

### 2.6 화면 흐름과 부르는 API

API 경로·요청·응답은 1부 그대로입니다. 오류는 두 갈래로 보입니다: 공통 `api()`(`lib/api.js`)를 쓰는 흐름 화면·붙여넣기·계정은 맨 위 알림 띠(`setAlert`)나 그 칸의 안내에, 프록시를 부르는 `careApi`·`mktApi`·`marketApi`·`drawerApi`는 **그 화면·칸 안에만** 보이고 맨 위 알림 띠를 쓰지 않습니다.

**홈 · 추천 카드 · 승인할 글 · 처리 완료** (`features/flow/actions.js`)

| 언제 | 함수 | 부르는 API | 결과가 가는 곳 |
|---|---|---|---|
| 페이지를 열 때 | `state/boot.js` `boot` | `GET /api/health`(기다리지 않음) + `GET /api/auth/me` → 단계 (2.2 (5)) | 로그인 전이면 A1, 들어간 가게가 그대로면 아래 줄, 아니면 A3 |
| 메인 화면에 들어갈 때 (가게 열기·새로고침) | `enterApp` → `storeChanged` | `GET /api/health` → `GET /api/briefing` → `GET /api/cards` → `GET /api/insight` → `GET /api/approvals`(기다리지 않음) → `GET /api/market/status`(기다리지 않음) | `health`: 시험용 안내 띠·알림 띠·바닥 줄. `briefing`: 홈·초안의 리뷰 원문 (상단 바 가게 칩은 `me.stores`의 지금 가게). `cards`: 추천 카드·홈 할 일. `insight`: 리뷰 분석. `approvals`: AI 비서의 맞춤 마케팅 승인 수 |
| 위 호출이 실패하면 | | | 알림 띠에 문장, 홈의 주 버튼이 "불러오지 못했어요". `insight`만 실패하면 리뷰 분석 화면에만 안내 |
| 홈 '무엇을 할까요?' | `go("cards")` | 없음 | `#/cards` |
| 리뷰 0건 홈의 [리뷰 넣기] · [상권 분석 보기] (11/20, '무엇을 할까요?' 대신) | `navTo("analysis", "paste")` · `go("market")` | 없음 | 리뷰 분석의 리뷰 넣기 탭 · `#/market` |
| 카드 버튼 | `choose` → `runCard` | `POST /api/cards/{id}/run`. 점검 수칙 상자가 있는 카드만 `{"measures": […]}` (그 밖에는 본문 없음) | `#/draft`. 이미 만든 카드면 API 없이 `#/draft` |
| 홈 '오늘 할 일' 항목 | `runTodo` | 아직 안 만든 카드면 위와 같음 | 그 종류의 첫 미승인 글로 `#/draft` |
| 초안 '승인' | `approve` | `POST /api/drafts/{id}/approve` `{text, original}` (+ 답글이면 `kind`·`review_id`) | 이 카드의 다음 미승인 글, 다 끝나면 `#/done` |
| 초안 '복사' | `copyText` | 없음 | 클립보드 (막히면 글 칸을 골라 `execCommand`) |
| 초안 상자 '다시 만들기' | `regenDraft` | `POST /api/cards/{id}/run` `{generator, review_id?, replaces: [그 글 id], measures?(불만 카드), reply_texts?(안내문)}` | 그 글 한 건만 새 글로. 그 글의 승인·고친 내용만 버림. 안내 한 줄(`calc.js` `regenNote`): 새 글이 예전 글과 같거나 또 기본 문장이면 '다시 만들었지만 같은 기본 문장이 나왔어요. 리뷰와 맞게 직접 고쳐서 승인해 주세요.' 같이 사실대로 (11/21) |
| 진행줄 옆 '카드 전체 다시 만들기' | `rerunCard` → `runCard` | `POST /api/cards/{id}/run` `{measures?, replaces: [그 카드의 글 id, 승인한 것부터 20개까지]}` | 그 카드의 글·승인·고친 내용을 모두 버림. 승인했거나 고친 글이 있으면 첫 누름은 안내만 하고 5초(`RERUN_ARM_MS`) 안에 한 번 더 눌러야 실행 |
| 응답에 `replace_warning` | | | 새 글은 쓰고 알림 띠에 그 문장 |
| `#/done` 열기 | `Done.jsx` `ServerLog` | `GET /api/approvals` | 접힌 '서버 처리 기록' (버튼 줄 위. 한 줄 = "MM-DD HH:MM 승인 · 글 이름 (고침)") |
| 완료 '홈으로' | `go("today")` | 없음 | 진행은 그대로 |
| 완료 '처음부터 다시' | `restart` | `DELETE /api/approvals` | 브라우저 진행을 비우고(`resetFlow`·`emptyFlow`), `mktResetSeq`를 올려 맞춤 마케팅도 처음으로, `#/today`. 서버가 실패해도 화면은 비우고 알림 띠로 알림. `marketing_cleared: false`면 맞춤 마케팅 화면 위에 "기록은 지우지 못했어요" 안내 |
| 홈 'AI 비서' 항목 | `staffGo` | 없음 | 데이터 분석 → 리뷰 분석 요약, 고객 응대 → 승인 대기가 있으면 `#/draft` 없으면 `#/cards`, 마케팅 → `#/marketing`, 상권 분석 → `#/market` |

**리뷰 분석** (`features/analysis/`)

| 언제 | 함수 | 부르는 API | 결과가 가는 곳 |
|---|---|---|---|
| '분류하기' | `PasteTab.jsx` `paste` | `POST /api/reviews` `{text, rating}` (+ 채널을 고르면 `channel`) → 성공하면 `refresh()` | 붙여넣기 칸 안 버튼 아래의 '분류 결과'(분류 전에는 없음), 홈·카드·분석 다시. 빈 글은 보내지 않음. 리뷰 넣기 탭은 '붙여넣기' · '캡처로 넣기' 두 칸 (11/20 Figma 06 C2) |
| '붙여넣은 리뷰 지우기' | `resetPaste` | `DELETE /api/reviews/pasted` → `refresh()` | 위와 같음 |
| 캡처 '파일 고르기'(점선 상자 안, 끌어 놓기는 칸 전체) → '캡처 읽기' | `Capture.jsx` `capRead` | `POST /api/care/reviews/capture` (multipart `file`, 최대 110초) | 후보 목록 (저장하지 않음). 파일은 png·jpg·webp, 10MB 이하만 보냄. 오류는 캡처 칸 안에만 |
| '선택한 리뷰 저장' | `capSave` | 고른 후보마다 `POST /api/reviews` `{text, rating, source: "capture"}` (`careApi`) → 하나라도 저장되면 `refresh()` | 후보마다 저장 표시 또는 그 후보 아래 오류 |

**종합 리포트** (`features/report/state.js`. 이 화면은 AI를 새로 부르지 않음: `/api/cards`·`/api/briefing`·글 만들기·서랍을 부르지 않음)

| 언제 | 부르는 API | 결과가 가는 곳 |
|---|---|---|
| 화면 열기 (3초 안에 다시 열면 한 번만) | `GET /api/care/report/daily`, `GET /api/care/response`, 지금 탭의 `GET /api/reports/weekly`(처음은 주간·이번 주), `GET /api/reports/saved` (따로따로) + 처음 불러오기가 끝났거나 카드가 있으면 `GET /api/approvals` | 칸마다 그림. 한 칸이 실패해도 다른 칸은 그대로. 보고서는 서버가 저장본이 있으면 저장본을, 없으면 만들어 저장해 줌 (1.17, 게스트는 저장 안 함). 손님 칭찬 요약·응대 기록은 지금 탭 보고서의 `report`로. 상권 요약·마케팅 요약은 이미 받은 `briefing`·`cards`·`approvedLog`로만 |
| 화면에 있는 동안 1분마다 (창이 보일 때만) | `GET /api/care/response` | 응대 점수·남은 시간. 실패하면 보이던 값 그대로 |
| 탭 '주간'·'월간' (해시는 그대로 `#/report`) | 그 탭을 처음 열 때만 `GET /api/reports/{weekly\|monthly}` | 탭마다 보던 기간·값이 남음 |
| '‹ 지난주'·'다음 주 ›' (월간은 지난달·다음 달) | `GET /api/reports/{종류}?period=<nav.prev·nav.next>` | 서버가 준 `nav` 값으로만 이동 (1년 전까지, 다음이 미래면 잠금). 여는 동안 보던 보고서는 흐리게 두고 안내 띠에 '불러오는 중…' |
| '다시 만들기' | `POST /api/reports/{종류}/regenerate?period=<지금 key>` + 위 요약 줄·응대 점수·승인 기록 다시 (조용히) | 저장본을 바꾸고 안내 띠 'MM-DD HH:MM에 만들어 저장했어요.', 목록 다시 |
| 저장된 보고서 '열기' | `GET /api/reports/{종류}?period=<key>` | 그 탭으로 바꾸고 그 기간을 엶 (포커스는 그 탭) |
| 월간 탭 'A4 인쇄용' | `GET /api/care/report/monthly/print?month=` (새 탭 링크) | 서버가 만드는 A4 HTML (그때 계산한 값) |
| 'PDF 저장' | 없음 | 2.3 (8) |
| 상권 요약 'AI에게 묻기로 상권 더 보기' | 없음 | 서랍 열기 |

**맞춤 마케팅** (`features/marketing/state.js`. 모두 `/api/marketing-survey/` 뒤 경로. 페이지를 열 때는 부르지 않고 이 화면을 처음 열 때 시작)

| 언제 | 부르는 API | 결과가 가는 곳 |
|---|---|---|
| 처음 열기 · '다시 확인' | `GET health` → (`ready`면) `GET meta`(기다리지 않음) → `POST step` `{state: null, answer: null}` | `ready`가 아니면 안내 칸과 '다시 확인'만 (탭·대화 숨김). 아니면 시작 모드 카드 다섯 개 + '마케팅 보고서' |
| 보기·입력 보내기 | `POST step` `{state, answer}` | 다음 질문. 끝(`done`)이면 아래 결과 카드 |
| 질문이 끝남 · '다시 쓰기' | `POST plan` `{state}` (+ 맞춤 홍보 제안·재주문 쿠폰이면 `POST result` `{state}`) | '제안 결과' 칸에 결과 카드 (`role="log"`·`aria-live="polite"`라서 새 카드를 읽어 줌) |
| 쿠폰 슬라이더 | `POST coupon-calc` (150ms 묶음, 늦은 답 버림) | 쿠폰 장수·최대 비용·본전 주문 수·예산 막대 |
| 슬라이더 아래 '이 조건으로 쿠폰 글 만들기' · '다음 쿠폰 조건' 칸의 같은 버튼 | `POST generate` `{state, coupon_override}` · `{state}` | 카드 안 새 글 (카드를 승인할 때 같이 승인) |
| '다음 아이디어' · '해 볼게요' | `POST next-idea` · `POST idea-try` | 카드 안 아이디어 칸 |
| 결과 카드 '승인' | `POST approve` `{state, draft_id: null, session_id, edited_texts, approval}` | `edit_failed`면 그 글 아래 점검 실패 안내. 성공이면 `recorded`를 처리 완료 목록(`approvedLog`, `mkt: true`)에, `follow_up`이면 재주문 쿠폰 질문, 공지 카드면 '2주 뒤 확인해 보기' |
| '2주 뒤 확인해 보기' | `POST notice-followup` `{state}` | 공지 전후 불만 수, 줄었으면 개선 소식 글 |
| '마케팅 보고서' 탭·기간 | `GET report?period=weekly\|monthly` (열 때마다 새로) | 보고서 카드 (`demo: true`면 데모 기록 표시) |
| '처음부터' (이 화면) | `POST step` `{state: null, answer: null}` | 대화만 처음으로 (승인·보고서 기록은 그대로) |
| 서랍·AI 비서에서 `navTo("marketing", sub)` | 위와 같음 | 그 시작 모드를 바로 고름 (`MKT_SUB`) |
| 결과 카드 'AI에게 이어서 묻기' (11/20) | 없음 | 카드 종류에 맞는 질문(광고비 표 → "주변에 같은 업종 점포는 몇 개야?", 쿠폰·할인 → "점심과 저녁 중 매출은 어디가 커?", 불만·공지 → "불만 리뷰 제일 많은 게 뭐야?", 그 밖 → "우리 가게 상권 매출은 어때?")을 서랍 입력칸에 채우고 서랍을 열어 입력칸에 포커스. **자동으로 보내지 않음** (사장님이 고치거나 Enter) |

- 화면 위 안내 띠(`Notice.mkt-notice`)는 마케팅 서비스가 HCX를 부르지 않는 상태(`health`의 `demo`·`mode: "mock"`·`key_present: false`, 또는 `demo: true` 결과를 받음)면 예시 고지 한 줄(`MKT_DEMO_NOTICE`)을 띄웁니다. **화면 맨 위 공통 시험용 띠(`health.mode_notice`)가 이미 있으면 이 고지는 띄우지 않습니다** (`noticeLines(s, appBand)`). '처음부터 다시' 때 마케팅 기록을 못 지웠다는 안내는 그와 상관없이 띄웁니다. 결과 카드 배지 `MKT_DEMO`('시험용 저장 예시 (실제 AI 결과 아님)')는 그대로 붙습니다.

**상권 분석** (`features/market/state.js`. 모두 `/api/market/` 뒤 경로, 1.14)

| 언제 | 부르는 API | 결과가 가는 곳 |
|---|---|---|
| 화면을 처음 열 때 | `GET status` → (`ready`면) `POST setup` → `GET analysis-options` + `GET options`(업종, 한 번만) + `GET analysis-selection`(지도의 가게 위치 `profile.location`, 실패해도 마커만 빠짐) → `GET sales`·`stores`·`population`·`area-context`·`changes?comparison=yoy` (`expected_revision` 붙임) | 조건 줄·지표 4칸·탭. 한 요청이라도 `409`면 `POST setup`으로 서버 조건을 다시 받아 한 번 더. `ready`가 아니면 화면 안 안내만 |
| 화면을 열 때마다 (못 받았으면) | `GET cultural-events` | 우리 동네 문화행사 |
| 조건 '적용' | `GET analysis-selection` → (업종이 바뀌면 `POST profile`. 역으로 등록한 가게만: 위치를 `{kind: "station", station_id}`로 다시 보냄. 주소·동네로 등록한 가게는 보내지 않고 "주소로 등록한 가게는 아직 이 화면에서 업종을 바꿀 수 없어요…" 안내) → `GET analysis-options` → `GET analysis-selection` → `POST analysis-selection` → `POST setup` → 위 자료 다시 | 새 조건으로 다시 그림. 새 숫자가 올 때까지 보던 숫자(지표 4칸·탭)는 흐리게(`.mk-dim`, `aria-busy`) 두고 위 안내 줄에 '조건을 바꾸고 있어요', 지표 아래 라벨과 '지금 보는 조건' 줄은 숫자와 함께 바뀜(`dataCond`, 11/21) |
| (화면을 열 때) 주소·동네로 등록한 가게 (11/21) | `GET analysis-selection`의 `profile.location`(역이 아님) | 업종 칸을 처음부터 잠그고 그 아래 "주소로 등록한 가게는 업종을 프로필의 '정보 고치기'에서 바꿔요." (`#mk-industry-note`, 칸의 `aria-describedby`) |
| '우리 가게 기준으로' | `POST setup?force=1` → 자료 다시 | 가게 기본 조건 (기본 여부는 서버의 `conditions.home`) |
| 비교 탭을 처음 열 때 · 비교 상권 고름 | `GET comparison-options` · `GET comparison?comparison_area_code=` | 비교 표 |
| 지도가 처음 필요할 때 (11/20) | `GET map-config` (한 번만, 2.3 (9)) → 네이버 지도 SDK | 지도. 안 뜨면 지도 자리에 한 줄과 [다시 시도], 아래 목록은 그대로 |
| 지도·목록에서 주변 상권을 누름 (11/20) | (비교 목록이 없으면) `GET comparison-options` | 비교 탭을 열고(탭에 포커스) 그 상권의 구·상권을 고름 + "○○ 상권을 비교 대상으로 골랐어요…". 목록에 없거나 `selectable: false`면 비교 칸에 그 이유 한 줄. 고른 상권(지금 분석 중)은 아무 일 없음. 비교는 사장님이 '비교하기'로 |
| 서울시 자료 최신화 | `POST data-sync` (70초) → `GET status` | 결과 한 줄, 자료 상태, AI 비서의 상권 상태 |

**AI에게 묻기 서랍** (`features/assistant/state.js`. 모두 `/api/assistant/` 뒤 경로, 1.10·1.15. 90초 넘으면 끊음)

| 언제 | 부르는 API | 결과가 가는 곳 |
|---|---|---|
| 서랍을 처음 열 때 · '다시 확인' | `GET status` → (`ready`면) `GET conversation` → 조건이 없으면 `POST setup` (한 번만, '다시 확인' 때 다시) | 상태 안내 카드 또는 이전 대화·조건·첫 추천 질문(`CHAT_STARTERS`) |
| 질문 보내기 (Enter, 한글 입력 중 Enter는 보내지 않음) | `POST messages` `{text, client_message_id}` | 답·선택지·근거 카드·이어서 물어볼 칩 |
| 선택지 (화면 이동이 아님) | `POST actions` (선택지의 `payload`) | 위와 같음 |
| 화면 이동 선택지 (`navigate`, `handoff`의 `marketing`·`customer`) | 없음 (`chatNavTarget` → `navTo`) | 그 화면·탭·시작 모드로. 서랍이 본문을 **덮고 있을 때만** 서랍을 닫고 포커스를 이동한 화면 제목으로 (`drawerCovers`, 2.9). 본문을 밀어 둔 넓은 화면이면 서랍은 그대로 |
| '대화 지우기' (4초 안에 두 번) | `DELETE conversation` → `GET conversation`(조건 표시만 다시) | 대화 비움 |
| '우리 가게 조건으로' | `POST setup?force=1` | 조건 칩. 서버의 `conditions.is_store_default`가 `true`면 '우리 가게 기준 적용 중'으로 잠금 |

- 서랍 머리 아래 기준 범위: 조건 칩(상권 · 업종 · 분기) + '하루 전체' 칩, 그 아래 안내 한 줄 `#assistant-cond-note`(`chat.js`의 `chatScopeNote`: "상권·업종 전체 추정치예요 (우리 가게 매출 아님 · 홈 타일은 … 기준)"). **이 안내 줄은 준비가 끝나면(`ready`) 조건을 못 받았어도 늘 보이는 한 줄**이고, 홈 지표가 없으면 괄호 안 '홈 타일은 … 기준'만 빠집니다. '우리 가게 매출 아님'은 서랍 안에서 이 한 곳에만 둡니다.
- 서랍은 `Esc`(한글 입력 중이 아니고 대화상자가 떠 있지 않을 때)나 '닫기'로 닫히고, 닫히면 연 버튼으로 포커스가 돌아갑니다 (화면 이동으로 닫은 경우는 제외).
- 상단 바와 아래 탭(760px 이하)의 'AI에게 묻기'는 **열기 전용**입니다 (11/20, `state/store.js`의 `focusOrOpenDrawer`). 닫혀 있으면 열고, 이미 열려 있으면 닫지 않고 입력칸 `#assistant-q`에 포커스를 줍니다(입력칸이 막혀 있으면 `#assistant-close`). 닫기는 서랍 안 [닫기]와 `Esc`만 합니다. 버튼 이름·`aria-controls="assistant"`·`aria-expanded`는 그대로입니다.
- 서랍 답의 종류(1.15): 가게 정보·화면 위치(`store_*`), 되묻기(`help_guide`), 추천 카드(`cards_guide`), 고객응대·마케팅·리포트(`*_guide`), 상권 답. 화면은 `reply.kind`로 그리기를 나누지 않고 글·버튼·추천 질문을 같은 모양으로 그립니다.

**계정** (`state/account.js`, `features/account/`, 11/20 단계 화면. 단계 규칙은 2.2 (5))

| 언제 | 부르는 API | 결과 |
|---|---|---|
| A1 [로그인] · '시연 사장님으로 1초 시작 (가게 3곳)' | `POST /api/auth/login` `{login_id, password, keep}`(`keep` = '로그인 상태 유지 (7일)') · `POST /api/auth/demo-login` | A3 (또는 하던 화면). 실패하면 카드에 오류, 친 비밀번호는 그대로. 시연 버튼은 시험용 실행(`isTestRun(health)` = `health.mode_notice`가 있음)이고 `me.demo_login`이 `true`일 때만 보임 (실제 서버에서는 숨김, 6차 회의) |
| A1 '비밀번호를 잊었어요' | 없음 | 그 자리에 "비밀번호 찾기는 아직 지원하지 않아요. 새 계정을 만들어 주세요." 한 줄 |
| A2 [가입하고 가게 등록하기] | `POST /api/auth/signup` `{login_id, password, display_name, stores: []}` | 새 가게 등록(`mode: "signup"`). 아이디(영문 소문자·숫자로 시작 3~32자)·비밀번호(8자 이상)·확인·이름·동의(필수)를 먼저 보고, 틀린 칸으로 포커스 |
| A3 열기 | `GET /api/account/stores` → 가게마다 `GET /api/account/stores/{id}/summary` (따로·동시에) | 카드: 첫 글자 · 이름(`sample`이면 ' (가상)') · '업종 · 상권' · '리뷰 n · 불만 n'(`unavailable`이면 숨김) · 요약 한 줄(`tone` bad 빨강 · good 초록 · muted 회색) · [이 가게 열기]. `last_opened` 가게는 맨 앞 + 초록 주 버튼 + '마지막으로 본 가게' 칩. 마지막 칸 '+ 새 가게 등록'. 0곳이면 그 칸과 "아직 등록한 가게가 없어요". 그림의 '오늘 승인 대기'·'이번 주 보고서'·카드의 '승인 대기'는 서버가 모르는 값이라 없음 |
| A3 [이 가게 열기] | `POST /api/auth/store` `{store_id}` → `storeChanged()` | 그 가게의 홈 (2.2 (5)) |
| A5 [이름 저장] · [비밀번호 바꾸기] | `PATCH /api/account/profile` `{display_name}` · `POST /api/account/password` `{current_password, new_password}` | 그 자리에 한 줄. 비밀번호 칸은 보낸 뒤 늘 비움, 401 `bad_password`면 지금 비밀번호 칸으로. 시연 계정은 비밀번호 버튼이 없음 |
| A5 내 가게 [빼기] → 확인 [빼기] | `DELETE /api/account/stores/{id}` → `GET /api/auth/me` | 확인 줄에 "가게를 빼도 그 가게의 기록은 지워지지 않아요." 들어가 있던 가게를 뺐으면 `entered`를 지움 ([가게로 돌아가기] → A3) |
| A5 [위로]·[아래로] | `PUT /api/account/stores/order` `{store_ids}` | 순서 = 가게 선택 화면 순서. 포커스는 누른 버튼(끝으로 가 잠기면 반대 버튼) |
| A5 [정보 고치기] (직접 등록한 가게만, 예시 가게는 '예시 가게' 표시) · '+ 새 가게 등록' | 없음 | 새 가게 등록 (`edit` + `storeId` · `add`) |
| A5 '기록 지우기'(지금 가게·모든 가게) → [지우기] | `DELETE /api/assistant/conversation`(실패·꺼짐 무시, 8초) → `POST /api/auth/reset` `{scope}` → (들어가 있던 가게가 있으면) `storeChanged()` | `complete: false`면 창을 열어 둔 채 오류와 '다시 지우기'. 성공이면 창을 닫고 오른쪽 아래 결과 띠 |
| A5 '회원 탈퇴' → [탈퇴하기] | 위 대화 지우기 → `POST /api/auth/withdraw` `{password}` (시연 계정은 `{}`) | A1, 결과 띠. 비밀번호 칸은 보낸 뒤 늘 비움. `bad_password`면 칸으로 포커스 |
| 로그아웃 (A3 위쪽 줄·사장님 칸, 왼쪽 메뉴 '프로필 · 로그아웃', X2 권한 없음) | `POST /api/auth/logout` | A1 (401 이면 이미 끝난 것으로 보고 같음) |

- 확인 창(`#acct-dialog`)의 기본 포커스는 [취소]이고 Esc도 취소입니다. 닫히면 연 버튼으로 포커스가 돌아갑니다. '지우면 되돌릴 수 없어요.' · '탈퇴하면 되돌릴 수 없어요.' 경고는 지우지 않습니다.
- 그림 A5의 '보관한 보고서' 구역: 내 가게 전체의 저장된 주간·월간 보고서 수(`features/report/SavedReportCounts.jsx`, `GET /api/reports/counts`). 일일은 저장하지 않아 없습니다(11/20 결정: 일일은 홈에서 확인).

**새 가게 등록 · 가게 정보 고치기** (`features/stores/`, 11/20 Figma A4. 계정 API 는 1.16, 상권 API 는 1.14)

화면: 위쪽 줄(로고 · '{이름} 사장님' · [가게 선택으로]) → '가게 등록 2 / 3'(가입 직후만, 가입 화면의 세 단계 가운데 둘째, 11/21) → 제목 '새 가게 등록'(고치기는 '가게 정보 고치기') → 설명 한 줄 → ① 가게 기본 정보(이름 1~30자 · 업종 셀렉트(음식 업종 코드 `CS1…` 10개만, 고치기에서 저장한 업종이 그 밖이면 그 하나는 남김. `storeApi.js` `foodIndustries`, 11/21) · 운영 상태 셀렉트(기본 '운영 중') · 입점한 배달 채널 칩 `baemin`·`coupangeats`·`yogiyo`·`ddangyo`) → ② 가게 위치와 상권('주소로 찾기' · '가까운 역으로' 라디오 → 지도 → '이 위치가 속한 상권' 라디오) → ③ 메뉴와 가격(줄마다 이름 1~30자 · 가격 0~1,000,000원, 0~30줄, 빈 줄은 안 보냄) → '등록하면 이렇게 시작해요'(고치기에는 없음) → [취소] [가게 등록하고 시작](고치기는 [저장]).

| 언제 | 부르는 API | 결과 |
|---|---|---|
| 화면 열기 | `GET /api/market/options`(업종 100 · 운영 상태 · 호선 · 역 403, 한 번 받으면 다시 안 받음) + 고치기면 `GET /api/account/stores/{id}` | 셀렉트 채우기. 고치기는 저장한 값으로 채우고 위치는 한 줄 + [위치 바꾸기], 상권은 저장한 상권 하나가 골라진 채. 실패하면 서버 문장 + [다시 시도]·[돌아가기] |
| 주소 [찾기] (주소 칸 Enter 도 찾기) | `POST /api/market/locations/search` `{query}` (2~200자, 2자 미만은 안 보냄) | 서울 후보가 여럿이면 서버 `message`와 라디오, 하나로 확정(`address_candidate`)이면 바로 고름. 후보 없음·서울 밖 등은 `message` 그대로, `lookup_unavailable`이면 "주소를 찾지 못했어요. 가까운 역으로 골라 주세요." + [가까운 역으로] |
| 역 고르기 | 없음 (호선 → 그 호선의 역. 역의 `lines`는 공식 이름이 달라 `selectable_line_codes`로 고름) | 고른 위치 한 줄, 지도 마커 |
| 위치가 정해지고 업종이 있을 때 (업종·위치를 바꿀 때마다) | `GET /api/market/profile`(revision) → `POST /api/market/profile` `{location: {kind: "station", station_id} \| {kind: "address", search_id, candidate_id}, industry_code, business_status, expected_revision}` (409 면 revision 을 다시 읽어 한 번 더) → `GET /api/market/analysis-options` | 상권 라디오: 이름 / '종류 · 공식 상권 코드 · 위치 관계(안에 있어요·경계·n m 거리) · 업종 자료가 있는 최신 분기 자료 있음'. `selection_blocked_reason`이 있거나 업종 자료가 없으면 그 이유를 보이고 잠금. 기본 선택은 예전 선택(새 후보에서도 고를 수 있으면), 아니면 `relation` inside → boundary 중 고를 수 있는 첫 번째, 없으면 비움. 업종이 없으면 부르지 않고 "업종을 먼저 골라 주세요." 실패하면 그 칸에 서버 문장 + [다시 시도]. 요청은 하나씩 차례로(상권 서비스 세션의 조건이 하나라 겹치면 섞임), 지난 요청의 응답은 버림 |
| 지도 | `GET /api/market/map-config` → 네이버 지도 SDK (2.3 (9), `list={false}`) | 마커 = 가게 위치, 상권 경계 = 후보(고른 것 `selected`·나머지 `nearby`·잠긴 것 `disabled`). 다각형을 누르면 그 상권을 고르고, 잠긴 상권이면 '이름: 이유' 한 줄. 지도가 안 떠도 라디오로 똑같이 고름(그때 범례는 숨김) |
| [가게 등록하고 시작] | `POST /api/account/stores` `{name, industry_code, business_type_name, business_status, channels, location{kind, label, road_address, latitude, longitude, station_id, station_name, district_name}, area{area_code, name, period}, menus[{name, price}]}` → `POST /api/auth/store` `{store_id}` → `storeChanged()`(2.6 첫 표) | 메인 화면 홈. `location`은 상권 서비스가 돌려준 `profile.location`에서, `period`는 고른 상권의 업종 자료가 있는 최신 분기. 등록 뒤 열기만 실패하면 "가게는 등록했어요. 가게를 열지 못했어요: …" + 버튼이 [가게 열기](다시 눌러도 새로 등록하지 않음) |
| 고치기 [저장] | 바뀐 칸만 `PATCH /api/account/stores/{id}` (없으면 안 부름) → `GET /api/auth/me` (+ 들어가 있던 가게면 `storeChanged()`, 기다리지 않음) | 프로필 + 오른쪽 아래 결과 띠 '{가게 이름} 정보를 저장했어요.'(바뀐 칸이 없으면 '바뀐 내용이 없어 그대로 두었어요.', `acctNotice`, 11/21). 위치·상권은 다시 고른 때만 보내고, 그때만 상권 서비스에 묻는다. 역으로 등록한 가게의 업종만 바꾸면 저장한 역으로 상권 후보를 다시 받고, 주소로 등록한 가게는 주소를 다시 찾게 함(찾기 전에는 저장 안 됨) |
| [취소] | 없음 | 온 곳(`storeNewFrom`): 프로필 또는 가게 선택 |

- 오류는 칸 바로 아래 한 줄(`#sn-err-<칸>`, 칸의 `aria-describedby`·`aria-invalid`)이고 틀린 첫 칸으로 포커스가 갑니다. 서버의 `error.message`는 그대로 보이고, 문장에 칸 이름(가게 이름·업종·메뉴·상권·위치 …)이 있으면 그 칸 아래, 아니면 버튼 위(`#sn-form-err`). 422 `store_limit`은 "… 프로필에서 쓰지 않는 가게를 빼면 새로 등록할 수 있어요."를 덧붙입니다. 저장 중에는 버튼을 잠가 한 번만 보냅니다.
- 상권 칸 아래 정직 고지 한 줄: "상권 자료는 우리 가게 매출이 아니라 상권·업종 전체의 추정치예요." + 상권 서비스의 `scope.boundary_notice`.
- 입력은 화면에만 있습니다 (새로고침하면 사라짐, 임시 저장 없음). 상권 서비스 세션의 조건(위치·업종)은 이 화면이 바꾸며, `POST /api/auth/store`가 상권 쿠키를 지우므로 가게를 연 뒤의 상권 화면·서랍은 새 세션으로 시작합니다.

### 2.7 자유롭게 바꿔도 되는 것

| 바꿔도 되는 것 | 조건·주의 |
|---|---|
| 색, 글꼴, 글자 크기, 간격, 모서리, 그림자 | `tokens.css` 변수로. 다크 값 두 덩어리를 같이 고치고 대비를 다시 확인 (2.3 (3)) |
| 배치(flex·grid), 본문 폭별 모양 | 화면 CSS는 창 폭 `@media` 대신 `@container content (…)`로 (2.9). 320px 폭까지 가로 스크롤이 생기지 않게. 메뉴·서랍의 폭 숫자를 바꾸면 `lib/media.js`·`layout.css`·`assistant/state.js`의 `drawerCovers` 대체 숫자와 2.9를 같이 고침 |
| 아이콘 | `ICONS`에 선 그림으로. 키는 메뉴 글자·시작 모드 글자와 같게 (2.3 (2)). `c9`·`replay`가 들어가면 시험이 깨짐 |
| 문구 (버튼 글자, 제목, 안내문) | 자유. 다만 정직 표시는 남기고 한 화면에 한 곳으로 (규칙 7), 서버 시험이 보는 글자(메뉴 글자, `MKT_MODES`의 시작 모드 키, `PASTE_SAMPLES`, `GEN_NAMES`의 답글·안내문 이름, `CHAT_STARTERS`의 갈래)는 2.4대로, 문구를 찾는 vitest는 같이 고침 |
| 컴포넌트 나누기·합치기, 파일 옮기기 | 자유. 다만 2.4 (1) 표의 파일과 이름은 옮기면 `tests/frontend_src.py`·서버 시험을 같이 고침. 모듈 상태(`state.js`)를 컴포넌트 안으로 옮기면 화면을 떠났다 오면 사라지니 주의 |
| CSS 클래스 이름 | 자유. 다만 2.3 (6)의 이름, `.app`의 상태 클래스, `report.css` 인쇄 규칙이 보는 이름(`.rp`·`.rp-sec`·`.rp-pair`·`.rp-bar`·`.rp-saved`·`.rp-tabpanel`·`.rp-body`·`.rp-today`·`.rp-print`·`.rp-screen`·`.rp-snap-t`·`.rp-mkt-st`·`.page-head`)은 같이 고침 |
| 애니메이션, 호버, 포커스 모양 | 자유. 키보드 포커스가 보이게 두고, 움직임은 `prefers-reduced-motion: reduce`에서 끔 (지금 진행 점들이 그렇게 함) |
| 새 그림·글꼴 | `src/` 안에 두고 import (2.1 (3)). 외부 CDN·`public/`은 쓰지 않음. **예외 한 곳**: 네이버 지도 SDK(`https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId=…`)는 npm 패키지가 없고 네이버가 그 주소로만 주므로 `components/NaverMap.jsx`의 `loadNaverMaps()`가 지도가 처음 필요할 때 한 번 붙입니다 (2.3 (9)). 다른 외부 스크립트는 더하지 않습니다 |
| 새 npm 패키지 | `package.json`(버전 정확히 고정)과 `package-lock.json`을 같이 올림 (`run.sh`·`make_bundle.sh`가 `npm ci`를 씀). 상태 관리는 지금처럼 `store.js`와 모듈 상태로 |

**바꾸면 안 되는 것** (요약): 화면 주소 8개, API 경로·요청·응답 칸 이름, 2.3 (6)의 이름, `[hidden]` 규칙, 2.4 (1) 표의 이름과 값, 정직 표시.

### 2.8 바꾼 뒤 확인하는 법

**(1) 화면 시험과 빌드** (`services/web/frontend`에서)

```bash
npm ci          # 처음 한 번, 또는 package-lock.json 이 바뀌었을 때 (Node.js 20 이상)
npm test        # vitest (2.4 (3))
npm run build   # dist/ 가 생기는지 (실패하면 run.sh 도 서버를 띄우지 않음)
```

**(2) 서버 시험** (저장소 루트에서. 시험 이미지 `ic26-test:py312`, 일반 계정)

```bash
R="$(git rev-parse --show-toplevel)"
docker run --rm -u 1000:1000 -e HOME=/tmp -v "$R":/repo -w /repo/services/web ic26-test:py312 \
  bash -c 'PYTHONPATH=/repo:/repo/services/web python -m pytest -q -p no:cacheprovider'
```

- 저장소의 가상환경에 pytest를 넣었으면(`services/web/requirements.txt`에는 없음) `cd services/web && PYTHONPATH="$(cd ../.. && pwd)":. ../../.venv/bin/python -m pytest -q`도 됩니다.
- 시험은 외부 호출을 하지 않습니다. node가 없으면 화면 함수를 실제로 돌리는 몇 건(2.4 (1)의 7·8)만 건너뛰고, C6 저장본이 없으면 그것이 필요한 시험만 건너뜁니다.

**(3) 눈으로 확인** (`APP_MODE=mock services/web/run.sh` → `http://localhost:8000`. 고치면서 보려면 서버를 띄운 채 `npm run dev` → `http://localhost:5173`)

0. 처음 열면 로그인 화면(A1)과 시험용 안내 띠 한 줄. '시연 사장님으로 1초 시작' → 가게 선택(A3) → [이 가게 열기] → 홈. 새로고침해도 홈, 로그아웃하면 A1 (2.2 (5)).
1. 홈이 뜨고 숫자 타일 4개·차트가 채워지고, 맨 위에 시험용 안내 띠가 한 줄 보인다.
2. '무엇을 할까요?' → 카드 → 만들기 → 초안 → 고쳐서 승인 → 다 승인하면 처리 완료 → '처음부터 다시'.
3. 리뷰 분석 탭이 마우스와 ←/→/Home/End로 바뀌고, 예시 문장으로 '분류하기'·'붙여넣은 리뷰 지우기'가 된다.
4. 폭 1440 · 1280(+ 서랍 열기) · 900 · 375px에서 가로 스크롤이 없고, 2.9 표대로 메뉴·서랍이 움직인다. 375px에서도 상단 바 이름(그림) 버튼으로 프로필, [바꾸기]로 가게 선택에 닿는다. 단계 화면(A1·A2·A3·A5·X1·X2)도 375px에서 가로 스크롤이 없다.
5. 900px에서 메뉴를 펼치면 첫 메뉴 항목에 포커스, Tab이 메뉴 안에서만 돌고, Esc·바깥·[메뉴 닫기]로 닫으면 토글 버튼으로 돌아온다.
6. 상단 바 화면 모양 버튼으로 시스템 → 밝게 → 어둡게, `?theme=light`·`?theme=dark`에서 글자가 읽힌다.
7. 'AI에게 묻기'로 서랍이 열리고, 열린 채 다시 누르면 닫히지 않고 입력칸에 포커스가 간다. `Esc`·'닫기'로 닫힌다. 화면 이동 선택지를 누르면 그 화면으로 간다.
8. 종합 리포트 'PDF 저장'의 인쇄 미리보기가 A4로 나온다 (밝게·어둡게 둘 다 볼 것, 2.3 (8)).

### 2.9 왼쪽 메뉴 · 서랍 · 폭 기준

창 폭 구간은 `src/lib/media.js`(`BAND_QUERIES`, `useBand`)와 `src/styles/layout.css`의 `@media`가 같은 숫자를 씁니다. 동작은 `App.jsx`, 모양은 `layout.css` 맨 위 주석의 표와 같습니다.

**(1) 폭마다 메뉴 · 상단 바 · 서랍**

| 창 폭 (구간 이름) | 왼쪽 메뉴 | 상단 바 | 서랍 (AI에게 묻기, 폭 400px) |
|---|---|---|---|
| 1025px 이상 (`wide`) | 왼쪽에 고정(260px). 토글 버튼(`#menu-toggle`)으로 접으면 사라지고 본문이 넓어짐. 접었는지를 기억 | 위에 붙어 있음(`sticky`) | 본문이 680px 이상 남을 때만 본문을 밂: 메뉴를 폈으면 **1340px 이상**(1340 − 260 − 400 = 680), 접었으면 **1080px 이상**(1080 − 400 = 680). 그 밖에는 본문 위에 덮음(그림자, 뒤를 어둡게 하지 않음) |
| 761~1024px (`mid`) | **접힌 채 시작** (기억한 값과 상관없음). 펼치면 화면 왼쪽에 덮이고 뒤를 어둡게(`--scrim`). 덮는 동안 상단 바까지 가리므로 메뉴 안에 [메뉴 닫기] 버튼이 생김 | 위와 같음 | 본문 위에 덮음 (본문 폭을 깎지 않음) |
| 760px 이하 (`narrow`, 11/20 휴대폰 개편) | 왼쪽 메뉴를 그리지 않음. **아래 탭 5칸**(`.tabbar`: 홈 · 오늘 처리 · 가운데 초록 원 'AI에게 묻기' · 살펴보기 · 마케팅, 현재 탭은 초록, '오늘 처리'에 승인 대기 수). 묶음 안 화면이 여럿이면 본문 맨 위 **하위 탭**(`.group-nav`: 추천 카드·승인할 글·처리 완료 / 리뷰 분석·상권 분석·종합 리포트, 진행 단계 줄 `.flow-steps`는 숨김) | **한 줄**, 위에 붙음: 로고 · 가게(이름·업종 줄임표, 가게 바꾸기) · 화면 모양 · 계정(그림 단추, 이름은 `.sr`). 'AI에게 묻기'·승인 대기 칩은 아래 탭으로 | 아래에서 올라오는 시트(높이 85%, 아래 탭을 덮음) |

- 폭이 소수(화면 배율 때문에 760.5px 같은 폭)여서 두 구간 사이 1px 틈에 걸리면 CSS와 JS(`bandNow`) 모두 넓은 화면(`wide`) 규칙을 따릅니다.
- 그 밖의 창 폭 `@media`: 360px 이하 상단 바 단추 폭·탭 글자, 480px 이하 계정 창 여백·목록, 760px 이하 대화상자 여백·서랍 안 여백. 본문이 479px 이하면 화면 제목 24px(`@container content`).
- 휴대폰에서 문서가 화면보다 넓어지지 않게 한 칸 격자(`.col`·`.stack*`)는 `grid-template-columns: minmax(0, 1fr)`입니다. 넓은 표(종합 리포트 월간 표)는 자기 상자 안에서만 가로로 밀고 첫 칸은 붙여 둡니다. 확인은 `document.documentElement.scrollWidth`와 `clientWidth`를 견줍니다 (`innerWidth`는 넘친 만큼 같이 커져서 넘침을 숨김).

**(2) 메뉴 상태와 기억**

- 상태는 `App.jsx`의 `menuOpen`(넓은 화면)과 `over`(덮는 메뉴가 열림) 둘이고, 화면에는 `.app`의 클래스 `menu-closed`·`menu-over`로 알립니다. 서랍이 열리면 `drawer-open`.
- 토글 버튼은 `aria-controls="side-menu"`, `aria-expanded`(넓은 화면은 `menuOpen`, 761~1024px는 `over`), `aria-label`·`title`("왼쪽 메뉴 접기" / "왼쪽 메뉴 펼치기")을 바꿉니다.
- 넓은 화면의 접힘 여부는 `localStorage`의 `ic26.menu`(`"open"`·`"closed"`)에 둡니다. 넓은 화면에서 토글할 때만 씁니다. `localStorage`는 늘 `try { … } catch` 안에서 부르고, 못 쓰면 그 화면을 보는 동안만 기억합니다.
- 창 폭이 구간을 넘거나 화면이 바뀌면 덮는 메뉴는 닫힙니다.

**(3) 덮는 메뉴(761~1024px)의 포커스** (`App.jsx`, 시험 `App.test.jsx`)

- 열면 포커스가 메뉴의 **첫 항목**(`.menu-item`)으로 갑니다. 뒤의 본문(`.main`)은 `inert`가 되어 읽기 프로그램·마우스가 닿지 않습니다.
- `Tab`·`Shift+Tab`은 메뉴(`#side-menu`) 안의 누를 수 있는 요소 사이에서만 돕니다.
- `Esc`(한글 입력 중 제외, 서랍이 열려 있어도 메뉴부터), 바깥(어두운 배경) 누름, [메뉴 닫기], 메뉴 항목으로 닫힙니다.
- 닫히면 포커스가 토글 버튼(`#menu-toggle`)으로 돌아옵니다. 메뉴 항목으로 다른 화면에 갔으면 그 화면 제목(`h1`)이 가진 포커스를 그대로 둡니다.

**(4) 승인 대기 수와 계정**

- 승인 대기 수는 왼쪽 메뉴 '승인할 글' 옆 숫자(`.count`, `aria-label="승인 대기 n개"`)입니다. 메뉴가 안 보일 때(넓은 화면에서 접음, 761~1024px에서 덮는 메뉴가 닫혀 있음)는 상단 바에 승인 대기 칩 `#top-waiting`(→ `#/draft`)이 대신 보입니다. 0이면 둘 다 없습니다. 760px 이하에서는 아래 탭 '오늘 처리'와 하위 탭 '승인할 글'에 숫자가 보이고 칩은 그리지 않습니다. 이때 '오늘 처리' 탭은 승인 대기가 있으면 `#/draft`, 없으면 `#/cards`로 갑니다.
- 계정은 **모든 폭에서** 상단 바의 이름 버튼(`#acct-user`, '{이름} 사장님' → 사장님 프로필)과 가게 칩의 [바꾸기](`#acct-store` → 가게 선택)로 닿습니다 (11/20, Figma 06 B1). 메인 화면에는 로그인 전 사장님이 없어서 [로그인]·'게스트' 표시는 없습니다. 760px 이하에서는 이름 버튼이 그림 단추(이름은 `.sr`, id 는 같음)이고, 왼쪽 메뉴가 없으므로 로그아웃은 [바꾸기] → 가게 선택 화면(A3)의 [로그아웃]으로 합니다 (프로필 A5 그림에는 로그아웃이 없음). 왼쪽 메뉴가 보일 때(넓은 화면, 또는 761~1024px에서 펼친 덮는 메뉴)는 메뉴 맨 아래 사장님 칸(첫 글자 동그라미 + '{이름} 사장님' + '프로필 · 로그아웃')도 있습니다.
- 상단 바 가게 칩: 이름(예시 가게면 ' (가상)') · '업종 · 상권'은 `me.stores`의 지금 가게(`me.store_id`)에서 읽고, 없으면 브리핑의 가게. 예전 가게 고르기 `<select>`는 없앴습니다. 메뉴 접기(`#menu-toggle`)·승인 대기 칩(`#top-waiting`)·화면 모양 버튼은 그림에 없지만 그대로 둡니다.

**(5) 서랍이 본문을 미는지 덮는지**

- CSS(`layout.css`): 서랍은 기본으로 본문 위에 덮고(`position: fixed`, 그림자), `@media (min-width: 1340px)`에서 `.app.drawer-open .main`에, `@media (min-width: 1080px)`에서 `.app.menu-closed.drawer-open .main`에 `margin-right: var(--drawer-w)`를 주어 밉니다. 761~1024px 구간은 이 두 기준보다 좁아서 늘 덮습니다.
- JS(`assistant/state.js`의 `drawerCovers`): 화면 이동 선택지를 누를 때 서랍 `#assistant`와 본문 `#main`의 실제 위치가 겹치는지 봅니다(1px 여유). 겹칠 때만 서랍을 닫고 이동한 화면 제목으로 포커스를 보냅니다. 위치를 잴 수 없으면(시험 환경 등) CSS와 같은 숫자로 봅니다(메뉴를 폈으면 1339px 이하, 접었으면 1079px 이하가 덮음). 폭 숫자 대신 위치를 보므로 CSS 기준이 바뀌어도 그대로 맞습니다.

**(6) 본문 폭에 따라 바뀌는 것 (`@container content`)**

서랍이 밀거나 메뉴를 접으면 창 폭은 그대로인데 본문 폭만 달라집니다. 그래서 본문 `<main class="content">`를 크기 컨테이너 `content`로 두고(`container-type: inline-size; container-name: content`), 화면 CSS는 창 폭 대신 `@container content (max-width: …)`로 씁니다. 공통 단계는 `base.css`에 있습니다.

| 어디 | 본문 폭 | 바뀌는 것 |
|---|---|---|
| 공통 `.tiles` (`base.css`) | 기본 | 칸당 150px 이상이면 모두 한 줄 (`auto-fit`) |
| | 799px 이하 | 타일 숫자 26px |
| | 679px 이하 | 두 칸, 홀수 개면 마지막 칸이 한 줄 전체 (본문이 약 256px보다 좁으면 한 칸) |
| | 479px 이하 | 타일 여백 16px · 간격 12px · 숫자 24px |
| 공통 `.grid-3` | 879px 이하 | 두 칸 |
| 공통 `.grid-2`·`.grid-3` | 639px 이하 | 한 칸 |
| 공통 `.panel` | 479px 이하 | 안쪽 여백 20·16px |
| 홈 `.flow-dash` (오늘 할 일 · AI 비서) | 759px 이하 | 한 칸 (공통 639px보다 먼저) |
| 홈 시간대 막대 `.flow-hours` | 479px 이하 | 막대 사이 3px, 시각 글자 한 칸 걸러 숨김(자리는 그대로, 모든 숫자는 `aria-label`에) |
| 흐름 화면 | 479px 이하 | 진행줄 버튼 왼쪽 여백 없앰, 완료 목록 줄바꿈 허용, 할 일 아래 버튼 꽉 채움 |
| 리뷰 분석 `.an-paste-grid` | 759px 이하 | 붙여넣기 · 캡처로 넣기 한 칸 |
| 리뷰 분석 | 639px 이하 | 흐름 숫자·시간대 줄·키워드 간격 좁게 |
| 리뷰 분석 `.an-paste-opts` (채널 · 별점) | 419px 이하 | 한 칸 (그 위에서는 공통 639px 규칙보다 우선해 두 칸) |
| 종합 리포트 `.rp-praise-body` | 759px 이하 | 두 칸(인기 메뉴·대표 한 줄) → 한 칸씩 |
| 종합 리포트 `.rp-tiles`·`.rp-nums` | 639px 이하 | 두 칸. 탭·기간 이동 줄(`.rp-bar`)은 두 줄, 오늘 요약·응대 점수 줄(`.rp-today`)은 위아래로 |
| 종합 리포트 | 479px 이하 | 큰 점수 44px 등, 기간 이름이 이동 버튼 위 한 줄로 |
| 상권 분석 `.mk-cond-btns` | 1000px 이상 | 조건 버튼이 고르기와 한 줄 |
| 상권 분석 `.mk-body` | 979px 이하 | 오른쪽 옆 칸(280px)을 아래로 |
| 상권 분석 지표 칸 (자체 컨테이너 `mk-main`) | 1100px 이상 | 핵심 지표 4칸 한 줄 (그 아래는 2×2) |
| | 779px 이하 | 세부 탭 2×2 |
| 맞춤 마케팅 `.mkt-split` | 860px 이하 | 질문 · 제안 결과 두 칸 → 위아래 |
| | 520px 이하 | 패널·카드 여백 줄임 |

- 숫자·가게 이름은 말줄임표로 자르지 않고 줄을 바꿉니다 (`body`의 `word-break: keep-all` + `overflow-wrap: anywhere`).
- 인쇄에서는 `layout.css`가 컨테이너를 꺼서(`container-type: normal`) 이 규칙이 먹지 않고, 종이 모양은 `report.css` 인쇄 덩어리가 정합니다.

---

## 3부. 데이터가 어디에 저장되나, 무엇이 바뀔 예정인가

> **11/14 덧붙임: 이 3부의 일부는 `main`에서 이미 바뀌었습니다.** 이 문서의 기준 커밋(`d7c1305`) 뒤에 DB 저장 코드(`shared/storage`)와 상권 코드(`services/market-analysis`)가 `main`에 들어왔습니다. 그때 화면 파일 3개와 2부의 규칙은 그대로였습니다 (11/20부터 화면은 React, 2부). 달라진 것은 아래와 같습니다.
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
| **화면 진행 상태** (만든 글, 승인 표시, 고친 글) | **브라우저 메모리**(`src/state/store.js`의 상태와 화면마다의 모듈 상태 `features/*/state.js`, 2.2) | 새로고침하면 사라짐. 진행 상태는 `localStorage`·쿠키에 두지 않음 (11/20 React 코드로 다시 확인함) | 화면(`frontend/src`) |
| **왼쪽 메뉴를 접었는지** (11/16) | **브라우저 `localStorage`**의 `ic26.menu` (`"open"`·`"closed"`). 서버로 보내지 않음 | 브라우저에 남음 (1025px 이상에서만 씀. 2.9) | `src/App.jsx` |
| **화면 모양** (11/19) | **브라우저 `localStorage`**의 `ic26.theme` (`"light"`·`"dark"`, 시스템이면 지움). 서버로 보내지 않음 | 브라우저에 남음. 주소의 `?theme=`는 저장하지 않음 (2.3 (4)) | `src/lib/theme.js`, `frontend/index.html` |
| **방문자 구분** | **없음** | — | 로그인·쿠키·사용자 id가 코드에 없음. 모든 방문자가 같은 가게·같은 승인 목록·같은 붙여넣은 리뷰를 봄 |

승인 기록 파일 한 줄은 이런 모양입니다 (`1.6` 응답과 같은 칸): `draft_id`, `status`, `edited`, `text`, `approved_at`, `mode`.

### 3.2 예정 (아직 없음)

아래는 **계획**입니다. 기준 커밋에는 코드가 없습니다 (저장소의 파이썬 코드에서 `psycopg`, `sqlalchemy`, `asyncpg`, `sqlite3`, `postgres`, OCR 관련 글자를 찾았으나 없음. `services/` 아래에는 `review-insight`와 `web`뿐). 새 API의 경로와 모양은 정해지는 대로 이 문서에 더합니다. **지금 있는 API 9개의 경로와 칸 이름은 그대로 둡니다.**

| 예정 | 지금은 | 화면에 미칠 영향 |
|---|---|---|
| **DB(PostgreSQL)에 저장**: 승인 기록, 붙여넣은 리뷰, 가게별 주간·월간 보고서, 카드 추천 이유 | 위 3.1 표대로 메모리·파일 | 서버 안의 일이라 화면은 그대로여야 합니다. 예를 들어 서버를 다시 켜도 승인 목록(`GET /api/approvals`)이 남게 될 수 있습니다 (정해지지 않음) |
| **방문자를 구분하는 값** | 없음 | 방식(로그인·쿠키·토큰)은 정해지지 않았습니다. 정해지면 요청에 값을 싣는 방법이 바뀔 수 있습니다 |
| **보고서 API** (가게 주간·월간 보고서) | **연결됨 (11/15)**: 리뷰 분석 서비스의 일일·월간 응대 보고서를 `/api/care/report/*`로 (1.11절). **11/20**: 주간 보고서와 계정별 저장(`reports` 표)이 생김 (`/api/reports/*`, 1.17). 계정 초기화·탈퇴 때 저장된 보고서도 지움. 남은 것: 마케팅 숫자 중 쿠폰 사용률·광고 건당 비용·공지 전후 재발(지금 '–') | `#rp-*` |
| **상권 채팅** (`AI에게 묻기` 서랍) | **연결됨 (`feat/assistant-proxy`)**: 비서 화면 서버가 상권 서비스를 대신 불러 줌(1.10절). 서랍이 질문·선택지·근거 카드·대화 지우기를 함. 공식 상권 자료가 아직 없어 실제 숫자는 자료가 들어온 뒤에 나옴 | 서랍 안(`#assistant-*`)만 바뀜 |
| **캡처(OCR) 입력** | **연결됨 (11/15)**: 리뷰 분석 '리뷰 넣기' 탭의 '캡처로 넣기' (1.11절, HCX-005가 옮겨 적고 사장님이 확인해 저장) | `features/analysis/Capture.jsx` |

### 3.3 화면의 빈 자리 (11/20 없음)

(11/20 고침) 예전 화면의 빈 자리 두 곳은 모두 채워져서, React 화면에는 '준비 중' 메뉴나 빈 서랍이 없습니다. 예전 내용은 git 이력(`d3113b0` 이전)에 있습니다.

- **'준비 중' 메뉴(`LATER`)**: 11/15 종합 리포트, 11/18 상권 분석이 진짜 화면이 되어 비었고, React 화면에는 `LATER`·`mountLater`·'준비 중' 화면이 없습니다. 화면 8개는 모두 진짜 화면입니다 (2.5). 그것을 확인하던 시험(`test_later_menu_slots`)도 지웠습니다.
- **'AI에게 묻기' 서랍**: 상권 채팅(1.10)과 전 파트 질문·화면 이동(1.15)이 연결되어 있습니다. 여는 버튼은 상단 바 'AI에게 묻기'(`Topbar.jsx`)와 760px 이하 아래 탭의 같은 버튼(`MobileNav.jsx`, 둘 다 열기 전용·11/20), 홈 아래 입력줄 모양 버튼(`Home.jsx`), 종합 리포트 상권 요약의 'AI에게 묻기로 상권 더 보기', 맞춤 마케팅 결과 카드의 'AI에게 이어서 묻기'(질문을 채우기만 함, 11/20)입니다. 동작은 2.6, 폭별 모양은 2.9.
- 새 화면을 더하는 방법은 2.2 (4)에 있습니다.

### 3.4 임시 DB 표 이름

설계 담당이 고칠 **출발점**입니다. 이름은 임시이고, 칸과 연결은 아직 정해지지 않았습니다. 오른쪽은 "지금 코드에서 이 표에 들어갈 후보가 되는 값"일 뿐 확정이 아닙니다.

| 임시 표 이름 | 담을 것 | 지금 코드에서 비슷한 것 |
|---|---|---|
| `stores` | 가게 | 11/20부터 실제 표: 사장님이 직접 등록한 가게만(`data_origin = 'registered'`, `owner_user_id`, `profile` JSONB, 1.16). 예시 세 곳은 `StoreProfile`(`shared/contracts.py`)·`store.json`·`shared/store_profiles.py` 그대로 |
| `reviews` | 리뷰 (합성, 붙여넣은 것) | `ReviewRecord`의 앞 11칸(`review_id`, `store_id`, `text`, `created_at`, `channel`, `rating`, `input_method`, `pii_masked`, `order_ref`, `status`, `data_origin`), `reviews.json`, `pasted_(가게).json` |
| `review_labels` | 리뷰별 분류 결과 | `ReviewRecord`의 뒤 4칸(`sentiment`, `topics`, `negative_topics`, `urgency`)과 리뷰 분석 서버의 `classification`(`method`, `model`, `warnings`). 합성 정답표 `labels.json`과는 다른 것입니다. 무엇을 담을지는 설계 담당이 정합니다 |
| `reports` (11/20, 실제로 씀) | 가게 주간·월간 보고서 (계정별) | `db/schema.sql`. (`store_id`, `visitor_id`, `period_kind` weekly·monthly, `period_start`, `period_end`, `numbers` JSONB, `body_text`, `evidence_ids`, `prompt_version`, `created_at`), 유일 색인 (`store_id`, `visitor_id`, `period_kind`, `period_start`, `period_end`, `prompt_version`). 11/20 전 표에는 init_db 가 `visitor_id` 칸을 더하고 옛 유일 조건을 바꿈. `services/web/web/reports.py` 가 씀 (1.16) |
| `approvals` | 승인 기록 | `approvals.jsonl` 한 줄(`draft_id`, `status`, `edited`, `text`, `approved_at`, `mode`) |
| `card_reasons` | 카드 추천 이유 | `GET /api/cards`의 `card.reason_text`, `reason_source`, `checked_text`, `facts`, `evidence`, `problems`. 지금은 서버 메모리(`_reason_memo`)에만 있음 |
| `users` · `user_stores` · `auth_sessions` (11/18, 실제 표) | 사장님 계정·가진 가게·로그인 세션 | `db/schema.sql`. `users(user_id PK, login_id UNIQUE, password_hash, display_name, created_at)`, `user_stores(user_id, store_id, position, PK(user_id, store_id))`, `auth_sessions(token_hash PK, user_id, active_store_id, created_at, expires_at)`. 로그인한 사장님의 승인 기록 등은 다른 표의 `visitor_id` 칸에 `u-<user_id>`로 남음 (1.13) |
| `review_records` · `review_status_events` (11/19, 실제 표) | 리뷰마다의 상태·답글 기록과 상태가 바뀐 기록 | `db/schema.sql`. 리뷰 분석 서비스 `app/records.py` (`source`, `received_at`, `status`, `status_at`, `reply{text, replied_at}`, `history[{status, at}]`). 열쇠는 (`store_id`, `visitor_id`, `review_id`) — 기본(합성) 리뷰는 `reviews` 표에 줄이 없어도 방문자마다 기록이 붙기 때문. DB 가 없으면 파일 `records_(가게).json` |

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

## 4부. 맞춤 마케팅 서비스 자체 API · 실행 · 배포 (11/16)

> 대상: 비서 화면 서버의 맞춤 마케팅 프록시를 만지는 사람, 서버를 띄우는 사람. 기준: 통합 브랜치(`5b23e70` = main `1ce30ac` + PR #56) 위 `feat/imkt-a-backend`.
> 여기 적은 것은 **맞춤 마케팅 서버 자체의 API**입니다. 브라우저는 이 서버를 직접 부르지 않고, 비서 화면 서버(8000)가 같은 경로 `/api/marketing-survey/*`를 대신 불러 줍니다. 그 중계(쿠키 → `visitor_id`, 오류 모양 바꾸기 등)는 1부의 맞춤 마케팅 프록시 절에 있습니다.
> 응답 예시는 `TestClient`로 mock 모드에서 뽑았습니다.

### 4.1 한눈에

| 항목 | 값 |
|---|---|
| 코드 | `experiments/marketing/marketing_survey/` (김수현 님, PR #56). 글은 `experiments/marketing/c6`의 생성기로 만듦 |
| 시작 명령 | `cd experiments/marketing && PYTHONPATH=<저장소 루트>:<저장소 루트>/experiments/marketing python -m uvicorn marketing_survey.server:app --host 127.0.0.1 --port 8030` |
| 주소 | `127.0.0.1:8030` (같은 컴퓨터 안쪽만. 서버에서는 `ic26-marketing`, 로컬에서는 `run.sh`의 `MARKETING_PORT`) |
| 상태 | 서버에 대화 상태를 두지 않습니다. 화면이 `state` = `{node, raw, confirms, mode}`를 들고 다니며 매 요청마다 보냅니다 |
| 기록 | 설문 결과·승인·쿠폰 결과·광고비 점검을 한 줄씩. `DB_HOST`가 있으면 PostgreSQL 표, 없으면 파일 (4.4, 11/19) |
| 오류 모양 | FastAPI 기본: `{"detail": "한국어 문장"}`(400·404·500), 형식 오류는 `{"detail": [ … ]}`(422). 비서 화면 서버의 `{"error": {"message"}}`와 다릅니다 |

### 4.2 경로

모든 경로에 공통 쿼리 `store`(기본 `store_ongi`, 데이터가 없는 가게는 `404`)와 `visitor_id`(선택, 4.3)를 붙일 수 있습니다.

| 메서드 · 경로 | 하는 일 | 기록 | live에서 HCX |
|---|---|---|---|
| `GET /health` · `GET /api/marketing-survey/health` | 상태 (4.6). 두 경로가 같은 내용 (11/16 새로) | | |
| `GET /api/marketing-survey/meta` | 가게 이름·id·가게 목록 | | |
| `GET /api/marketing-survey/stores` | 가게 목록 (`available` false는 고를 수 없음) | | |
| `POST /api/marketing-survey/step` | 질문 하나 진행. 본문 `{state, answer}` (`state: null`이면 새로 시작) | | |
| `POST /api/marketing-survey/result` | 맞춤 홍보 제안의 결정 + 설명 3줄 | | |
| `POST /api/marketing-survey/generate` | 글 하나 (`{text, todo, demo, coupon}`) | | 부름 |
| `POST /api/marketing-survey/plan` | 실행 계획과 글 (`{title, steps, drafts, demo, session_id, …}`). `state.mode`로 기능을 가름 | 씀 (`proposed`, 쿠폰 결과, 광고비 점검) | 부름 (광고비 점검·쿠폰 결과의 계획은 코드만) |
| `POST /api/marketing-survey/next-idea` | 같은 목표의 다음 아이디어 | | |
| `POST /api/marketing-survey/idea-try` | 아이디어 해 보기 (질문이 필요하면 질문만) | 씀 (`tried`) | |
| `POST /api/marketing-survey/coupon-calc` | 쿠폰 슬라이더 계산 | | |
| `POST /api/marketing-survey/approve` | 승인. 본문 `{state, session_id, edited_texts}` | 씀 (`approved`) | |
| `POST /api/marketing-survey/notice-followup` | 개선 인증 소식 (코드가 리뷰 수를 셈) | | |
| `GET /api/marketing-survey/report?period=weekly\|monthly` | 마케팅 보고서. 기록이 없으면 데모 (`demo: true`). 기록을 읽지 못하면 `503` (4.4) | 읽음 | |
| `DELETE /api/marketing-survey/records` | 그 방문자의 기록만 지움 (4.5, 11/16 새로) | 지움 | |
| `GET /` · `/web/…` | 이 서버의 단독 화면 (통합 화면에서는 쓰지 않음) | | |

- `demo`(`/generate`·`/plan`): `true`면 HCX를 부르지 않고 저장된 예시(`c6/replay`)나 코드 템플릿으로 만든 글입니다. mock이거나 live인데 키가 없을 때입니다.
- 글 생성기(c6)의 점검·다시 쓰기·템플릿은 서버 응답에 나오지 않고 글(`text`·`drafts`)만 나옵니다.

### 4.3 `visitor_id` (11/16)

- 선택 쿼리입니다. 정규식 `^[A-Za-z0-9_-]{1,64}$`. 틀리면 **모든 경로에서** `400`입니다. **빈 값(`visitor_id=`)도 틀린 값**이라, 방문자가 없으면 쿼리를 빼고 보냅니다.

  ```json
  {"detail": "visitor_id 형식이 올바르지 않아요. 영문·숫자·_·- 로 1~64자여야 해요."}
  ```
- 본문이 아니라 쿼리로 받는 이유: 비서 화면 서버가 GET·POST 모두 쿼리에 `store`·`visitor_id`를 붙여 중계하고 본문은 손대지 않기 때문입니다.
- 쓰는 곳: `plan`·`approve`·`idea-try`는 기록을 그 방문자 자리(파일 또는 DB)에 쓰고, `report`는 그 방문자 기록만 읽고, `DELETE /records`는 그 방문자 기록만 지웁니다. 나머지 경로는 받아서 형식만 봅니다.

### 4.3.1 `X-IC26-Store-Profile` — 직접 등록한 가게 (11/20)

- 모든 경로가 선택 헤더 `X-IC26-Store-Profile`(1.16, `shared/store_header.py`)을 받습니다. 검사를 통과하면 그 가게를 이 프로세스의 등록 목록에 넣고
  `?store=<그 가게 id>` 로 고를 수 있습니다(컨텍스트: 등록한 이름·업종·메뉴·가격·채널 + 기본 말투·공통 정책, 리뷰·카드·상권 지표·예전 답글은 빈 목록).
  틀린 값(모양·12,000자 초과·예시 가게 id)은 `400 {"detail": "가게 프로필 헤더가 맞지 않아요: …"}`. 헤더 없이 온 모르는 가게는 예전처럼 `404`.
- 카드가 없어 만들 수 없는 글은 `409 {"detail": "<안내 문장>", "state": "no_complaint_card" | "no_promo_card"}` (500 아님). `/stores`·`/meta` 의 가게 목록은 예시 세 곳 그대로입니다.

### 4.4 기록 (파일 또는 DB)

저장 위치 (11/19): 맞춤 마케팅 서버 환경에 `DB_HOST`가 있으면 PostgreSQL의 `marketing_sessions`·`coupon_runs` 표(`db/schema.sql`, 이슈 #51 ERD §3.13), 없으면 아래 표의 파일입니다. `/health`의 `records_store`(`db` | `file`)로 보입니다. API와 응답 모양은 두 방식이 같습니다.

- DB 방식에서는 방문자 id를 `visitor_id` 칸에 둡니다(ERD의 `user_id` 대신. 로그인한 사장님은 `u-<user_id>`). `visitor_id`가 없는 호출은 공용 값 `common`에 둡니다(승인 기록 표와 같은 관례). `visitor_id=common`을 직접 주면 공용과 같은 곳을 보고, `DELETE /records?visitor_id=common`은 아무것도 지우지 않습니다(`{"deleted": false}`).
- WAS가 2대여도 같은 기록을 봅니다. 예전 파일 기록은 DB로 옮기지 않습니다.
- DB에 닿지 못할 때: 쓰기는 건너뛰고 응답은 그대로(`session_id: null`), `report`는 데모로 바꾸지 않고 `503` `{"detail": "기록을 읽지 못했어요. 잠시 뒤 다시 해 주세요."}`, `DELETE /records`는 `500`(4.5). 파일 방식에서 기록 파일을 읽지 못할 때도 `report`는 같은 `503`입니다.


| `visitor_id` | 파일 (`MARKETING_RECORDS_DIR`, 기본 `experiments/marketing/data/marketing/`) | 보고서 |
|---|---|---|
| 있음 | `records_{store}_{visitor_id}.json` (줄마다 `"visitor_id"` 칸이 붙음) | 그 방문자의 기록만 셈. 없으면 데모 `demo_records_{store}.json` (`demo: true`). 가게 공용 파일·다른 방문자 기록은 섞지 않음 |
| 없음 | `records_{store}.json` (예전과 같음. 단독 화면·시험용) | 예전과 같음 |

- 줄 하나가 JSON 하나이고 칸 이름은 나중 DB 표 이름과 같습니다(`marketing_sessions`, `coupon_runs`. `records.py` 머리말).
- 기록은 보조 기능입니다. 파일·DB에 못 써도(`OSError`·`ValueError`, DB 오류도 `OSError`로 바뀜) 응답은 그대로 가고 `session_id`만 `null`이 됩니다.
- 서버: `/var/lib/ic26/marketing` (`ic26` 소유). 저장소 안 기본 폴더는 `.gitignore` 대상입니다(데모 파일만 올라감).
- 주의: 가게 id가 '다른 가게 id + `_` + 방문자 id' 꼴이면 파일 이름이 겹칩니다. 지금 가게 목록(`store_ongi` 하나)에는 없습니다.

### 4.5 `DELETE /api/marketing-survey/records` (11/16)

- `?visitor_id=…`(필수) `&store=…`(선택). 그 방문자의 기록만 지웁니다(파일 방식은 그 파일 하나, DB 방식은 두 표의 그 가게·그 방문자 줄).

  ```json
  {"deleted": true}
  ```
- 기록이 없으면 `{"deleted": false}` (오류 아님, `200`).
- `visitor_id`가 없으면 `400` (가게 공용 파일 `records_{store}.json`은 지우지 않음):

  ```json
  {"detail": "visitor_id 가 있어야 기록을 지울 수 있어요. 가게 공용 기록은 지우지 않아요."}
  ```
- 데이터가 없는 가게 `404`, 기록을 지우지 못하면(파일 오류, DB에 닿지 못함) `500` `{"detail": "기록을 지우지 못했어요. 잠시 뒤 다시 해 주세요."}`.

### 4.6 `GET /health` · `GET /api/marketing-survey/health` (11/16)

```json
{
  "status": "ok",
  "service": "marketing-survey",
  "mode": "mock",
  "mode_source": "MARKETING_APP_MODE",
  "key_present": false,
  "demo": true,
  "store_id": "store_ongi",
  "records_dir_writable": true,
  "records_store": "file",
  "notes": [
    "mock: 키가 있어도 HCX 를 부르지 않아요. 글은 저장된 예시·코드 템플릿이에요(실제 AI 결과 아님)."
  ]
}
```

| 칸 | 뜻 |
|---|---|
| `mode` · `mode_source` | 4.7의 모드와 그것을 정한 것 (`MARKETING_APP_MODE` · `APP_MODE` · `key`) |
| `key_present` | 환경에 `CLOVA_API_KEY`가 있는지. **키 값은 싣지 않습니다** |
| `demo` | HCX를 부르지 않는 상태인지 (mock이거나 live인데 키 없음) |
| `store_id` | 기본 가게 |
| `records_dir_writable` | 기록 폴더(아직 없으면 만들 수 있는 윗폴더)에 쓸 수 있는지. 폴더 경로는 싣지 않습니다 |
| `records_store` | 기록을 두는 곳: `db`(PostgreSQL) \| `file` (11/19). DB에 닿는지는 보지 않습니다(DB가 꺼져도 `/health`는 `200`) |
| `notes` | 사람이 볼 안내 (live인데 키 없음, 기록 폴더에 못 씀 등) |

### 4.7 모드 (11/16)

- 정하는 순서: `MARKETING_APP_MODE`(`mock`|`live`) → 없으면 `APP_MODE` → 없으면 키(`CLOVA_API_KEY`)가 있으면 `live`, 없으면 `mock`. `mock`·`live`가 아닌 값은 없는 것으로 봅니다.
- **mock이면 환경에 키가 있어도 HCX를 한 번도 부르지 않습니다** (맞춤 홍보 제안·남은 재료·가게 이야기 글·쿠폰 결과의 `/plan`·`/generate` 모두). 키를 읽는 곳은 서버의 `hcx_key()` 하나이고, 가게 이야기 글(`story.build_story_plan`)에도 그 값을 넘깁니다.
- live인데 키가 없으면 예전처럼 데모로 돕니다(`demo: true`, `/health`의 `notes`).
- 요청마다 환경 변수를 다시 읽습니다(바꾸면 다음 요청부터).

### 4.8 실행 (`services/web/run.sh`)

- `run.sh`가 리뷰 분석(8020)·**맞춤 마케팅(8030)**·비서 화면(8000)을 같이 띄웁니다. `Ctrl+C`나 스크립트 `kill`로 셋 다 꺼집니다.
- 맞춤 마케팅의 모드는 `MARKETING_APP_MODE`(주지 않으면 `APP_MODE`와 같음). 키 파일이 있어도 `APP_MODE=mock`이면 마케팅도 mock입니다.
- 비서 화면 서버에 `MARKETING_SURVEY_URL=http://127.0.0.1:<MARKETING_PORT>`를 넘깁니다. 미리 `MARKETING_SURVEY_URL=off`를 주면 마케팅 서버를 띄우지 않고 그대로 `off`를 넘기고, 다른 주소를 주면 띄우지 않고 그 주소를 넘깁니다.
- 기록 폴더를 바꾸려면 `MARKETING_RECORDS_DIR=<폴더>` (상대 경로는 지금 위치 기준).
- `/health`가 30초 안에 응답하지 않으면 "맞춤 마케팅 서버가 뜨지 않았습니다"를 알리고 끝냅니다.

### 4.9 배포 (`deploy/`)

| 파일 | 바뀐 것 |
|---|---|
| `systemd/ic26-marketing.service` | 새로. `ic26` 계정, `/opt/ic26/experiments/marketing`, `PYTHONPATH=/opt/ic26:/opt/ic26/experiments/marketing`, `127.0.0.1:8030`, `MARKETING_RECORDS_DIR=/var/lib/ic26/marketing`, `EnvironmentFile=/etc/ic26/env` |
| `systemd/ic26-was.service` | `MARKETING_SURVEY_URL=http://127.0.0.1:8030`, 순서 `After=ic26-marketing.service` (Wants 아님 — 꺼 둔 마케팅을 끌어오지 않음) |
| `install_was.sh` | `/var/lib/ic26/marketing` 만들기, 마케팅 서버 import 확인, `ic26-marketing` enable·시작. `experiments/marketing/requirements.txt`는 설치하지 않음(서버는 fastapi·uvicorn만 씀, 개발용 streamlit 제외) |
| `smoke_test.sh` | [4] 맞춤 마케팅: 비서 화면을 거친 `/api/marketing-survey/health`(404면 주의만), 서버 안 `127.0.0.1:8030/health`, `--generate`면 `/plan`(가게 이야기 글) 1회 후 시험 방문자 기록 지움(직접 주소면 `DELETE /records`, 비서 화면을 거치면 쿠키 방문자의 `DELETE /api/approvals`) |
| `prepare_image.sh` | `ic26-marketing` 멈춤, `/var/lib/ic26/marketing` 비움 |
| `env.example` · `README.md` | 주석으로 `MARKETING_APP_MODE`, `MARKETING_SURVEY_URL=off`. README 10-2절 |

- Nginx는 바꾸지 않습니다. 브라우저는 `/api/marketing-survey/*`를 비서 화면 서버로만 부르고(1단계 `location /`, 2단계 `location /api/`), 8030은 `127.0.0.1`에만 열립니다.
- 끄는 법: `/etc/ic26/env`에 `MARKETING_SURVEY_URL=off`, `sudo systemctl disable --now ic26-marketing && sudo systemctl restart ic26-was`.

---

## 부록. 알려진 특이점, 코드에서 확인하지 못한 것

### 알려진 특이점

문서를 쓰다가 코드에서 발견한 것입니다. **코드는 고치지 않았습니다.** 화면을 다듬는 사람이 알아 두면 좋은 것을 앞에 두었습니다.

| # | 특이점 | 어디서 | 영향 |
|---|---|---|---|
| 1 | 카드의 `ⓐ`·`ⓑ` 표시가 카드 **위치** 기준입니다. 카드 ⓐ가 없고 홍보 카드만 있으면 홍보 카드가 `ⓐ`로 보임. 카드 id의 `_a`·`_b`는 종류 기준이라 서로 다름 | `features/flow/Cards.jsx`(`index === 0`), `Draft.jsx`(`s.cards.indexOf(q) === 0`) | 카드가 하나뿐인 날 이름표가 어긋남. 카드 ⓐ가 없는 날은 시험(`test_no_repeated_issue_means_no_card_a`)이 다루는 정상적인 경우임 |
| 2 | 사용자가 잘못 입력한 경우(공백만 있는 글, 틀린 `channel`)가 `422`가 아니라 `503`("리뷰 분석 서비스 오류 400: …")으로 옴. 리뷰 분석 서버의 `400`을 비서 화면 서버가 `503`으로 바꿔 전달함 | `sources.py`의 `_json`, `demo.py`의 `paste` | 화면은 문장을 그대로 보여 주므로 사용자에게는 보임. 상태 코드만 어색함 |
| 3 | (고침) 붙여넣기 글자 수 검사가 비서 화면 서버만 4000자였음 | `main.py`의 `PasteIn` | main `d7c1305`에서 1000자로 맞춤. 지금은 1001자 이상이 `422` |
| 4 | 상권 지표 파일이 깨지면 `/api/health`는 `200`(+`snapshot.error`), `/api/briefing`·`/api/cards`는 `500`(일반 글자) | `demo.py`의 `health`와 `_state` | 화면이 "요청 실패 (500)"만 보임 |
| 5 | `POST …/approve`가 `draft_id`가 실제 글인지 확인하지 않고, 본문 `{}`도 받아 `text: null`로 기록함 | `demo.py`의 `approve` | 화면에서는 생기지 않는 경우 |
| 6 | 승인 기록 파일은 서버를 다시 켜도 읽지 않아 `GET /api/approvals`가 비게 됨. 같은 글을 다시 승인하면 파일에는 줄이 더 붙어 중복됨 | `demo.py`의 `approve`, `Demo.__init__` | DB로 옮길 때 같이 정리할 부분 |
| 7 | 승인 응답의 `warning`(기록 파일에 못 씀)을 화면이 보여 주지 않음 | `features/flow/actions.js`의 `approve` | 파일 쓰기가 실패해도 사장님은 모름 |
| 8 | mock은 `measures`의 틀린 id를 무시하고 `200`, live는 `400` | `demo.py`의 `run` | 시험용 실행에서는 안 걸리는 오류가 live에서 나옴 |
| 9 | 형식 오류(`422`)의 `detail[0].msg`가 영어이고 화면이 그대로 보여 줌 | `src/lib/api.js`의 `api()` (프록시용 `careApi`·`mktApi` 등은 해당 없음) | 사용자에게 영어가 보일 수 있음 |
| 10 | 배달앱 이름이 `/api/briefing`의 `groups[].reviews[].channel`에서는 한국어(`"배민"`), `single_complaints[].channel`·`/api/insight`에서는 코드(`"baemin"`)임 | `demo.py`의 `briefing` | 화면에 보이는 곳은 한국어뿐이라 지금은 문제 없음 |
| 11 | (11/20 지움) 예전 `index.html`·`app.js` 주석이 'AI에게 묻기' 버튼을 숨겨져 있다고 적은 문제. 예전 화면을 지워서 해당 없음 | — | — |
| 12 | (11/20 고침) 추천 카드의 이유 문장(`reason_text`) 줄바꿈(`\n`)이 React 카드에서 살지 않던 것 | `features/flow/Cards.jsx`의 `.card-reason`, `flow.css`(`white-space: pre-line`) | 고친 뒤에는 카드 ⓑ의 두 줄 이유가 두 줄로 보임 |
| 13 | (11/20 고침) 어둡게 모양에서 종합 리포트를 PDF로 저장하면 색 토큰이 어두운 값으로 찍힐 수 있던 것 | `styles/tokens.css`: 다크 토큰을 `@media screen` 안에만 둠 | 인쇄는 늘 밝은 토큰. 실제 인쇄물은 확인하지 못함 |

### 코드에서 확인하지 못한 것

- **live 모드의 응답**: 키가 없어 실행하지 않았습니다. `live`의 `POST …/run` 응답(글 id 모양, `needs_input`의 실제 내용, 걸리는 시간)은 코드로만 확인했고 값은 확인하지 못했습니다. 키 없이 `live`로 띄웠을 때의 `health`·`cards`·`run` 오류만 실제로 뽑았습니다.
- **다른 주소(origin)에서 API를 부를 때 브라우저가 막는지**: 코드에 CORS 설정이 없는 것만 확인했고, 실제 브라우저 동작은 실행하지 않았습니다.
- **화면이 브라우저에서 실제로 어떻게 보이는지**: (11/20) 2부는 React 소스(`services/web/frontend/src`)와 서버·배포 스크립트를 읽고 썼습니다. 화면을 열어 보거나 `npm test`·`npm run build`·서버 시험을 이 문서 작업에서 돌리지는 않았습니다. 2.8의 '눈으로 확인'은 코드에 있는 기능을 기준으로 적은 점검 목록입니다.
- **`classification.model`의 정확한 뜻**: 예시 값이 `"kiwi"`인 것만 확인했습니다.
- **캡처(OCR) 입력, 방문자 구분, 보고서 API, 상권 채팅의 방식과 위치**: 기준 커밋에 코드가 없어 계획 외에는 확인하지 못했습니다.
- (11/20 해결) 예전에 확인하지 못했던 'Nginx가 `/static/…`을 어떻게 다룰지'는 해당 없음: 화면 빌드는 `/`와 `/assets/…`만 쓰고, `deploy/nginx/ic26-static.conf`가 `/assets/`를 따로 다룹니다 (2.1 (4)).
