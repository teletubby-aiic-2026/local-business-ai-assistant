# C7 한 화면 + C9 발표 모드

① 오늘의 브리핑 → ② 추천 카드 2장 → ③ 결과물 생성 → ④ 사장님 승인 을 한 화면으로 잇습니다.
다른 파트의 코드는 고치지 않고 가져다 씁니다.

| 단계 | 가져오는 곳 | 방법 |
|---|---|---|
| ① 리뷰·분류·묶음 | C2·C3·S2 (PR #14 `services/review-insight`) | HTTP (`app/` 패키지 이름 충돌을 피하려고 import 안 함) |
| ① 상권 지표 | C4 (PR #17 `data/scenario/snapshot_2026Q2.json`) | JSON 파일 → `AnalysisSnapshot` |
| ② 카드 2장 | C5 참조 구현 `web/cards.py` (진수 구현이 오면 `build_cards` 교체) | 규칙 + 이유 문장(검사기 `shared/answer_check.py` 통과) |
| ③ 답글·공지·홍보글 | C6 (PR #16 `experiments/marketing/c6`) | import (`run_card`) |
| 계약 | C1 (PR #15 `shared/contracts.py`) | import |

## 실행 (세 PR 병합 뒤, 저장소 루트에서)

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r services/web/requirements.txt -r services/review-insight/requirements.txt
services/web/run.sh                     # 기본 mock: 키 없이 돈다
open http://localhost:8000
```

## 실행 (병합 전, 지금)

각 PR을 worktree로 꺼내 경로만 알려 줍니다. 공유 체크아웃의 브랜치는 바꾸지 않습니다.

```bash
W="$HOME/AI Innovation Challenger/wt"   # #14 review-insight, #16 marketing, #17 c4-data worktree
REVIEW_INSIGHT_DIR="$W/review-insight/services/review-insight" \
MARKETING_DIR="$W/marketing/experiments/marketing" \
SNAPSHOT_PATH="$W/c4-data/data/scenario/snapshot_2026Q2.json" \
services/web/run.sh
```

## 모드

| `APP_MODE` | ① 브리핑 | ② 이유 문장 | ③ 글 | 키 | 네트워크 |
|---|---|---|---|---|---|
| `mock` (기본) | #14 를 이 컴퓨터에서 띄워 규칙 분류 | 고정 문장 | 김수현 저장본 (`c6/replay/c6_cache_best.json`) | 필요 없음 | 필요 없음 |
| `live` | 같음 (`REVIEW_APP_MODE=live` 면 #14 도 HCX) | HCX-005, 검사기 불통과면 고정 문장 | HCX-005 `run_card` | 필요 | 필요 |
| `replay` (발표) | 저장본 | 저장본 | 저장본 | 필요 없음 | 필요 없음 |

- **발표 모드 저장본 만들기**: `mock` 이나 `live` 로 띄워 ①→③ 을 한 번 돌리고 화면 아래 **"발표 모드로 저장"** → `services/web/data/replay/web_cache.json`. 그다음 `APP_MODE=replay services/web/run.sh`.
- `live` 에서 생성한 결과는 누를 때마다 저장본에 바로 기록됩니다. HCX 호출은 1회 약 25~35원이라, 팀장 확인 뒤 소량만.
- **사다리 (결정안 6절)**: `APP_MODE=live DEMO_LADDER=1` 은 답글만 실시간, `DEMO_LADDER=2` 는 답글 하나만 실시간. 나머지는 저장본.
- **개발용 가짜 지표**: `note` 가 "개발용 가짜 값"으로 시작하는 지표가 있으면 화면 맨 위에 빨간 띠가 뜨고, 발표 모드로 저장·재생하지 않습니다.

## 키·토큰

- 키는 저장소 밖 `~/.config/teletubby-aiic/env` (폴더 700, 파일 600) 에만 둡니다. `run.sh` 가 읽고 값은 출력하지 않습니다. 없으면 mock 으로 돕니다.
- 같은 HCX 키를 `CLOVASTUDIO_API_KEY`(#14)와 `CLOVA_API_KEY`(#16) 두 이름으로 내보냅니다.
- 원격 리뷰 서버를 쓸 때만 `WEB_REVIEW_SOURCE=remote` + `REVIEW_INSIGHT_URL`·`REVIEW_INSIGHT_TOKEN`(헤더 `X-Access-Token`). 기본은 이 컴퓨터에서 띄웁니다.

## 카드 ⓑ 지표 고르기

고정된 우선순위로 **먼저 하나를 고르고**, 그 값이 기준(`CARD_B_THRESHOLD`, 기본 -5%) 이하일 때만 카드를 만듭니다. 고른 지표가 하락이 아니면 다른 지표를 찾아 내려가지 않습니다.

1. `CARD_B_SNAPSHOT_ID` (지정했을 때)
2. `snap_evening_sales_yoy` (저녁 17~21시, 현석 지표)
3. 단위가 `%` 인 첫 '추정매출' 지표 (지금은 PR #17 의 하루 전체·관측 업종 합산 -27.95%)

화면의 카드 문장은 지표 이름을 그대로 씁니다. 하루 전체 지표를 '저녁'이라고 말하지 않습니다.

## 시험

```bash
cd services/web
PYTHONPATH="$(cd ../.. && pwd)" MARKETING_DIR=<experiments/marketing 경로> ../../.venv/bin/python -m unittest tests.test_web -v
```

CLOVA·네트워크를 부르지 않습니다 (리뷰 서비스는 가짜, 모델은 가짜 함수). `MARKETING_DIR` 가 없으면 C6 저장본이 필요한 시험만 건너뜁니다.

## 아직 안 된 것 (정직 표기)

- `live` 경로(HCX-005 이유 문장·`run_card`)는 실제 호출로 확인하지 않았습니다 (가짜 모델 함수로만).
- C5 는 참조 구현입니다. 진수의 `build_cards` 가 오면 바꿔 끼웁니다.
- 승인 기록은 화면과 `data/runtime/approvals.jsonl` 에만 남고, 배달앱에 게시하지 않습니다 (미구현: 복사까지만).
