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
- 승인 기록은 화면과 `data/runtime/approvals.jsonl` 에만 남고, 배달앱에 게시하지 않습니다 (미구현: 복사까지만).
