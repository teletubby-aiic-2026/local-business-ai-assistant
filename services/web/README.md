# C7 한 화면

① 오늘의 브리핑 → ② 추천 카드 2장 → ③ 결과물 생성 → ④ 사장님 승인 을 한 화면으로 잇습니다.
다른 파트의 코드는 고치지 않고 가져다 씁니다.

| 단계 | 가져오는 곳 | 방법 |
|---|---|---|
| ① 리뷰·분류·묶음 | C2·C3·S2 (PR #14 `services/review-insight`) | HTTP (`app/` 패키지 이름 충돌을 피하려고 import 안 함) |
| ① 상권 지표 | C4 (PR #17 `data/scenario/snapshot_2026Q2.json`) | JSON 파일 → `AnalysisSnapshot` |
| ② 카드 2장 | C5 참조 구현 `web/cards.py` (진수 구현이 오면 `build_cards` 교체) | 규칙 + 이유 문장(검사기 `shared/answer_check.py` 통과) |
| ③ 답글·공지·홍보글 | C6 (PR #16 `experiments/marketing/c6`) | import (`run_card`) |
| 계약 | C1 (PR #15 `shared/contracts.py`) | import |

## React 화면 (11/19, `frontend/`)

`frontend/` 에 React 18 + Vite 로 옮긴 화면이 있습니다 (가독성 개선 디자인). 예전 화면(`web/static/`)은 그대로 두었고, 서버는 **기본으로 예전 화면**을 줍니다.

- 쓰는 법: `cd services/web/frontend && npm ci && npm run build` 뒤 `WEB_FRONTEND_DIST=<그 폴더>/dist services/web/run.sh`. 서버가 `/` 에 React 화면, `/assets/*` 에 빌드 파일을 줍니다. API 는 같습니다.
- 개발: `npm run dev`(5173)가 `/api` 를 8000 으로 넘깁니다. 자세한 내용은 [frontend/README.md](frontend/README.md).
- 배포: `deploy/make_bundle.sh` 는 이 PC 에 `frontend/dist` 가 있으면 묶음에 넣습니다. 웹 서버 static 모드는 `install_web.sh --static-src <묶음>/services/web/frontend/dist`.

## 리뷰 분석 화면 (11/13)

- 따로 떠 있던 리뷰 분석 화면이 이 비서 화면 안으로 들어왔습니다. 왼쪽 메뉴 **리뷰 분석**(`#/analysis`)에서 탭 3개(요약 · 불만 묶음 · 리뷰 붙여넣기)로 봅니다.
- 화면은 이 서버의 API(`GET /api/insight`, `POST /api/reviews`, `DELETE /api/reviews/pasted`)로만 데이터를 받습니다. 브라우저가 리뷰 분석 서버에 직접 묻지 않으니, 서버에 올릴 때 리뷰 분석 서버는 안쪽에만 두면 됩니다.
- 리뷰를 붙여넣거나 지우면 홈 숫자와 추천 카드도 다시 불러옵니다.
- 왼쪽 메뉴의 **종합 리포트**·**상권**은 회의에서 정한 뒤 채울 빈 자리입니다 (`web/static/app.js` 의 `LATER` 한 곳).

## 실행 (저장소 루트에서. #14·#16·#17 은 11/10 main 에 병합됨)

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r services/web/requirements.txt -r services/review-insight/requirements.txt
services/web/run.sh                     # 키 파일이 있으면 live, 없으면 mock
APP_MODE=mock services/web/run.sh       # 키가 있어도 키 없이 시험용으로
open http://localhost:8000
```

다른 위치의 부품을 쓰려면 `REVIEW_INSIGHT_DIR`·`MARKETING_DIR`·`SNAPSHOT_PATH` 로 경로를 바꿉니다. 포트가 이미 쓰이면 `run.sh` 가 시작 전에 멈추고 pid 를 알려 줍니다 (`WEB_PORT`·`REVIEW_PORT` 로 바꿀 수 있음).

## 모드

모드는 두 가지입니다. `run.sh` 는 키 파일이 있으면 live, 없으면 mock 으로 띄웁니다.

| `APP_MODE` | ① 브리핑 | ② 이유 문장 | ③ 글 | 키 | 네트워크 |
|---|---|---|---|---|---|
| `live` | #14 도 live (`REVIEW_APP_MODE` 로 바꿀 수 있음) | HCX-005, 규칙 검사 불통과면 고정 문장 | HCX-005 `run_card` 전부 실시간 (사장님이 고른 재발 방지 조치 포함) | 필요 | 필요 |
| `mock` | #14 를 이 컴퓨터에서 띄워 규칙 분류 | 고정 문장 | 김수현 저장 예시 (`c6/replay/c6_cache_best.json`) | 필요 없음 | 필요 없음 |

- **mock 은 시험용 실행입니다.** 글은 저장된 예시이고 실제 AI 결과가 아닙니다. 그래서 화면 맨 위에 "시험용 실행 · 키 없이 저장된 예시 결과를 보여 줍니다 (실제 AI 결과 아님)" 띠가 뜹니다. live 에서는 뜨지 않습니다.
- **발표 모드(`replay`)와 사다리(`DEMO_LADDER`)는 없어졌습니다.** `APP_MODE=replay` 는 오류로 멈춥니다. 화면의 저장 단추와 `/api/c9/record` 도 없습니다.
- **이 화면은 live 결과를 파일에 저장하지 않습니다.** 글을 만들 때마다 실시간으로 부르고, 결과는 화면에만 있습니다 (승인 기록 `data/runtime/approvals.jsonl` 만 따로 남음). 참고: #14 는 live 일 때 샘플 리뷰 분류 결과를 자기 저장 파일(`services/review-insight/data/replay/classify.json`)에 남깁니다. 이 화면과는 별개입니다.
- **붙여넣기**(`POST /api/reviews`)는 mock·live 모두 됩니다.
- **이유 문장 규칙 (live)**: 검사기(`shared/answer_check`) 통과에 더해, 근거 숫자(3건·19.31%)를 실제로 쓰고, 상권 이름·시간대 표기를 바꾸지 않고, %를 %p로 쓰지 않고, 두세 문장·180자 안, 앞날 예측 없음. 걸리면 고칠 점을 붙여 5번까지 다시 쓰고, 그래도 안 되면 고정 문장. 다음 요청 때 3라운드까지 다시 시도합니다.
- **재발 방지 조치**: 불만 카드에서 사장님이 C6 조치 목록(`c6/measures.py`) 중 고른 것만 공지·답글에 들어갑니다. 기본은 포장 누락 → M1 "포장 마감 전 주문서 대조".
- **하지 않은 조치 점검**: "보내드렸어요"·"환불 처리 완료"·정하지 않은 보상 약속은 '확인 필요'로 표시합니다 (`generate.action_flags`).
- **개발용 가짜 지표**: `note` 가 "개발용 가짜 값"으로 시작하는 지표가 있으면 화면 맨 위에 빨간 띠가 뜹니다.

## 저장 계층과 방문자 구분

실행 중에 생기는 데이터(승인 기록, 붙여넣은 리뷰와 분류 결과, 카드 추천 이유 문장, 주간·월간 보고서)를 **DB(PostgreSQL)에도 둘 수 있습니다.** 코드는 저장소 루트의 `shared/storage/`, 표 정의는 `db/schema.sql` 한 파일입니다.

- **DB 설정이 없으면 지금과 똑같이** 서버 메모리와 `data/runtime/approvals.jsonl` 파일로 돕니다. psycopg 가 안 깔려 있어도 됩니다.
- **환경 변수 `DB_HOST` 가 있으면 PostgreSQL**: `DB_HOST`, `DB_PORT`(5432), `DB_NAME`, `DB_USER`, `DB_PASSWORD` (서버에서는 `/etc/ic26/env`). 서버가 여러 대여도 모두 같은 내용을 봅니다.
  `DB_HOST` 만 있고 `DB_NAME`·`DB_USER` 가 없거나 psycopg 가 없으면 켜질 때 오류로 멈춥니다 (조용히 메모리로 돌지 않음). 켜질 때 DB 가 꺼져 있는 것은 괜찮습니다.
- **DB 에 닿지 못하는 동안** (장애 전환 중 등):
  - 승인은 200 으로 받고 응답에 `warning` 이 붙습니다. 이 서버가 메모리에 들고 있다가, DB 가 돌아온 뒤 이 서버에 승인이나 승인 목록 요청이 오면 승인한 순서대로 DB 에 씁니다. 그 전에 이 서버가 꺼지면 그 승인은 사라집니다.
  - 브리핑·카드·리뷰 분석·붙여넣기는 503 입니다. 붙여넣은 리뷰가 DB 에만 있어서 리뷰 분석 서버가 503 `STORAGE_UNAVAILABLE` 로 답하기 때문입니다 (합성 리뷰만으로 계속 보여 주는 동작은 없음).
  - DB 가 돌아오면 서비스를 다시 켜지 않아도 다음 요청부터 됩니다.
- **표 만들기** (저장소 루트에서, 여러 번 돌려도 안전. 앱이 켜질 때 자동으로 만들지는 않음):

  ```bash
  DB_HOST=... DB_NAME=... DB_USER=... DB_PASSWORD=... python -m shared.storage.init_db
  ```
- **방문자 구분**: 이 서버가 방문자마다 임의의 id 를 쿠키 `visitor_id` 로 줍니다 (없으면 새로 만들어 응답에 실음. `HttpOnly`, `SameSite=Lax`, https 뒤에서는 `Secure`, 30일). 화면(JS)은 쿠키를 다룰 필요가 없습니다.
  이 id 로 **승인 기록과 붙여넣은 리뷰를 나눕니다** (리뷰 분석 서버에는 `visitor_id` 로 넘김). 합성 리뷰와 카드 추천 이유 문장은 모두에게 같습니다.
- **카드 추천 이유 저장 (live)**: 한 번 쓴 이유 문장(규칙 검사 통과분)을 저장하고, 가게·카드·근거 카드(숫자)·참조 문장·프롬프트·모델이 같으면 HCX 를 다시 부르지 않습니다. 서버를 켠 뒤 첫 화면이 느린 것을 줄입니다. 저장이 실패해도 화면은 뜹니다.
- 승인 요청 본문에 `card_id`·`kind`(초안 종류)를 선택으로 보낼 수 있습니다. 안 보내면 이 서버가 ③ 에서 만든 초안만 알고 있어서, 다른 서버에서 만든 초안이면 DB 의 카드·종류 칸이 빕니다.

## 상권 채팅 서랍 (상권 서비스 프록시)

오른쪽 "AI에게 묻기" 서랍이 상권 서비스(`services/market-analysis`, `ic26-market`, 127.0.0.1:8766)와 대화합니다. 브라우저는 이 서버의 `/api/assistant/*`만 부르고, 서버(`web/assistant_proxy.py`)가 상권 서비스를 대신 부릅니다. API 설명은 `docs/api/contract.md` 1.10절.

- 상권 서비스가 요구하는 세트를 모두 맞춥니다: 세션 쿠키(`market_onboarding_session`) 전달과 새 쿠키 심기, `Host: 127.0.0.1:8766`, `Origin`은 넘기지 않음, 엄격한 본문 검사(모르는 칸이 있으면 422), `messages`·`actions`·`conversation`(조회·지우기)·`status` 모두.
- **상권 서비스가 꺼져 있거나, 챗봇이 꺼져 있거나, 공식 자료가 아직 없어도 비서 화면은 죽지 않습니다.** 서랍 안에서만 상태 안내(`down`·`disabled`·`no_data`·`error`)가 나오고, 이 API들은 500을 주지 않습니다.
- 서랍을 처음 열면 `setup`이 우리 가게(온기한식) 분석 조건(장승배기역 · 한식음식점 · 장승배기역 4번 상권 · 최신 분기)을 자동으로 맞춥니다. 다른 가게를 `DEMO_STORE_ID`로 쓰면 기본 조건이 없어 질문할 때 위치·업종을 묻습니다.
- 환경 변수: `MARKET_URL`(기본 `http://127.0.0.1:8766`, `off`면 이 서버에서는 끔), `MARKET_HOST`(기본 `127.0.0.1:8766`), `MARKET_TIMEOUT_SEC`(질문 하나를 기다리는 최대 시간, 기본 75).
- 방문자마다 상권 세션이 따로입니다(쿠키는 브라우저에, 프록시는 쿠키를 모아 두지 않음).

**공식 자료 없이 끝까지 확인하는 법** (개발 전용): 상권 서비스의 시험이 쓰는 합성 자료로 상권 서비스를 띄웁니다. 숫자는 합성 값이고 서울시 OpenAPI 수집(`--collect`)은 하지 않습니다. 상권 서비스는 파이썬 3.12가 필요해(`requirements.lock.txt`의 `pyproj` 3.8) 컨테이너를 씁니다. 자세한 설명은 `scripts/serve_market_synthetic.py` 머리말.

```bash
# 한 번만: 파이썬 3.12 이미지 (requirements 설치)
cd services/market-analysis && printf 'FROM python:3.12-slim\nCOPY requirements.lock.txt requirements-assistant.txt /tmp/\nRUN pip install --no-cache-dir -q -r /tmp/requirements.lock.txt -r /tmp/requirements-assistant.txt\n' | docker build -q -t ic26-market-dev:py312 -f - .
# 합성 자료 상권 서비스 (키 없이: 고정 문형 답). 실시간 HCX-005 는 -e APP_MODE=live -e CLOVA_STUDIO_API_KEY 를 더함 (값은 적지 않고 이름만)
docker run --rm -p 127.0.0.1:18766:8766 -v "$PWD/../..":/repo:ro -w /repo/services/market-analysis -e PYTHONDONTWRITEBYTECODE=1 -e ASSISTANT_ENABLED=1 \
  ic26-market-dev:py312 python /repo/services/web/scripts/serve_market_synthetic.py
# 비서 화면 서버 (다른 터미널, 저장소 루트에서)
MARKET_URL=http://127.0.0.1:18766 APP_MODE=mock services/web/run.sh
```

## 고객응대 (캡처 입력 · 응대 점수 · 종합 리포트, 11/15)

리뷰 붙여넣기 탭의 '캡처로 넣기'와 왼쪽 메뉴 '종합 리포트'(`#/report`)가 리뷰 분석 서비스(`services/review-insight`, PR #49)의 고객응대 API를 씁니다. 브라우저는 이 서버의 `/api/care/*`만 부르고, 서버(`web/care_proxy.py`)가 대신 부릅니다. API 설명은 `docs/api/contract.md` 1.11절.

- 열어 둔 것: 캡처 읽기, 리뷰 상태 기록, 응대 점수, 일일·월간 보고서(인쇄용 HTML 포함). 가게 정보·문의·받은함·약속 장부·다국어 메뉴판은 404. 손님용 문의 페이지(`/s/…`, `/api/care/public/*`)는 `CARE_PUBLIC=1`일 때만 (기본 꺼짐, 보안 검토 전).
- 캡처 후보 저장은 붙여넣기와 같은 `POST /api/reviews`에 `"source": "capture"`. 그래서 붙여넣은 리뷰처럼 요약·불만 묶음·홈 숫자·추천 카드에 들어갑니다.
- 리뷰 답글을 승인하면 서버가 리뷰 분석 서비스에 '답글 달았음'(`replied`)을 따로 기록합니다. 승인 응답은 기다리지 않고, 실패해도 승인은 성공합니다.
- 리뷰 분석 서비스가 꺼져 있거나 느려도 이 서버의 다른 경로는 기다리지 않고(서비스 호출은 스레드에서), 캡처 칸과 리포트의 응대 칸에만 안내가 나옵니다. 500 없음.
- 종합 리포트를 열어도 AI(HCX)를 새로 부르지 않습니다 (응대 칸은 규칙 계산, 상권·마케팅 요약은 이미 받은 브리핑·카드로만).
- 환경 변수: `CARE_URL`(비우면 `REVIEW_INSIGHT_URL`과 같은 곳, `off`면 끔), `CARE_TIMEOUT_SEC`(캡처 기다리는 시간, 기본 100), `CARE_PUBLIC`(기본 꺼짐).

## 키·토큰

- 키는 저장소 밖 `~/.config/teletubby-aiic/env` (폴더 700, 파일 600) 에만 둡니다. `run.sh` 가 읽고 값은 출력하지 않습니다. 없으면 mock 으로 돕니다. 키가 있어도 `APP_MODE=mock` 을 주면 mock 입니다.
- 같은 HCX 키를 `CLOVASTUDIO_API_KEY`(#14)와 `CLOVA_API_KEY`(#16) 두 이름으로 내보냅니다.
- 원격 리뷰 서버를 쓸 때만 `WEB_REVIEW_SOURCE=remote` + `REVIEW_INSIGHT_URL`·`REVIEW_INSIGHT_TOKEN`(헤더 `X-Access-Token`). 기본은 이 컴퓨터에서 띄웁니다.

## 카드 ⓑ 지표 고르기

고정된 우선순위로 **먼저 하나를 고르고**, 그 값이 기준(`CARD_B_THRESHOLD`, 기본 -5%) 이하일 때만 카드를 만듭니다. 고른 지표가 하락이 아니면 다른 지표를 찾아 내려가지 않습니다.

1. `CARD_B_SNAPSHOT_ID` (지정했을 때)
2. `snap_evening_sales_yoy` (저녁 17~21시, 현석 지표. 지금 없음)
3. 단위가 `%` 인 첫 '추정매출' 지표 (지금은 PR #17 의 저녁 17~24시·두 분기 공통 업종 -19.31%)

화면의 카드 문장은 지표 이름(17~24시)을 그대로 씁니다. 불만이 몰린 17~21시와 같은 구간이라고 말하지 않습니다.

## 시험

```bash
cd services/web
PYTHONPATH="$(cd ../.. && pwd)" ../../.venv/bin/python -m unittest tests.test_web -v
```

CLOVA·네트워크를 부르지 않습니다 (리뷰 서비스는 가짜, 모델은 가짜 함수). C6 저장본(기본: 저장소의 `experiments/marketing`)이 없으면 그 저장본이 필요한 시험만 건너뜁니다.

## 점검 통과 수 측정 (live 기준선)

떠 있는 서버에 HTTP 로만 말해 글의 점검 상태(점검 통과 / 확인 필요 / 점검 실패, 화면 배지와 같은 규칙)와 걸린 시간을 센다. 키·환경 변수는 쓰지 않는다.

```bash
.venv/bin/python services/web/scripts/measure_live.py --base http://127.0.0.1:8540 --rounds 5 --label baseline --out baseline.json
```

서버 mode 가 live 가 아니면 크게 경고한다 (그래도 진행). `--out` JSON 에는 초안 본문 대신 길이만 남는다. 다른 브랜치를 넣은 서버에 같은 명령(`--label` 만 바꿔)을 돌려 비교한다.

## 아직 안 된 것 (정직 표기)

- 카드 이유 문장 호출 수는 따로 기록하지 않습니다 (C6·#14 는 각자 비용·사용량을 기록).
- C5 는 참조 구현입니다. 진수의 `build_cards` 가 오면 바꿔 끼웁니다.
- 승인 기록은 화면과 `data/runtime/approvals.jsonl`(DB 설정이 있으면 DB)에만 남고, 배달앱에 게시하지 않습니다 (미구현: 복사까지만).
