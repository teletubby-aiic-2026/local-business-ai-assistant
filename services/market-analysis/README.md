# 서울 상권분석 — 기본 6개 기능

서울시 공식 공개데이터를 이용해 상권·업종·분기를 선택하고 매출·점포·유동인구를 조회·비교하는 독립 실행 모듈입니다. 2026-11-04 공개 배포한 기본 기능을 기준으로, 미완성 AI 실험 경로와 이전 앱의 리포트·알림을 제거한 소스 패키지입니다.

| 기능 | 내용 |
|---|---|
| B1 상권 설정 | 주소·역·행정동, 업종·운영 상태 입력 후 공식 상권·분기 확인 및 저장 |
| B2 추정매출 | 분기 추정매출과 요일·시간대·연령 분포 |
| B3 점포 | 전체·일반·프랜차이즈·개업·폐업 점포 수 |
| B4 유동인구 | 상권 전체의 원천 총지표와 시간대·연령 분포 |
| B5 상권 비교 | 같은 업종·분기의 두 상권을 주요 7개 지표로 비교 |
| B6 기간 변화 | 전분기·전년 동분기와 값·차이·계산 가능한 변화율 비교 |

수치와 비율은 서버에서 계산합니다. 이 모듈에는 LLM 클라이언트·AI 질문 API·대화 실험·리포트·알림 기능이 없습니다.

## 설치

Python 3.12 이상을 사용합니다. 아래 명령은 이 디렉터리(`services/market-analysis`)에서 실행합니다. Node.js는 프런트엔드 회귀 시험에만 필요하며 앱 실행에는 필요하지 않습니다.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
Copy-Item .env.example .env
```

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
cp .env.example .env
```

이후 예시의 `python`은 생성한 가상환경의 Python을 가리킵니다. Windows에서는 `.\.venv\Scripts\python.exe`, macOS/Linux에서는 `.venv/bin/python`으로 실행하거나 가상환경을 활성화합니다.

## 공식 자료 준비

Git에는 공식 통계 원본, 생성된 분석 카탈로그, 사용자 DB를 올리지 않습니다. 자료를 준비하기 전에는 자료 미준비 상태가 표시되며 가상 분석값을 대신 제공하지 않습니다.

자료를 가져오거나 수집하기 전에 실행 중인 앱을 종료하고, 준비가 성공한 뒤 다시 실행합니다. 앱이 읽은 카탈로그를 캐시하므로 실행 중에 파일만 교체하는 방식으로 갱신하지 않습니다.

```bash
python -m scripts.prepare_data
```

위 명령은 준비 상태를 확인합니다. 기존에 확보한 공식 원본 폴더가 있다면 다음 명령으로 오프라인 검증 후 준비할 수 있습니다.

```bash
python -m scripts.prepare_data --from-dir /path/to/data/raw/official
```

새로 수집하려면 `.env`의 `SEOUL_OPENAPI_KEY`를 설정한 뒤 명시적으로 실행합니다. 실제 서울시 API 요청과 공식 경계 파일 다운로드가 발생합니다.

```bash
python -m scripts.prepare_data --collect --periods 20243 20244 20251 20252 20253 20254 20261 20262
```

자료의 공개·정정 상태에 따라 결과가 달라질 수 있습니다. 기존에 검증한 스냅샷과 새로 수집한 자료를 같은 버전으로 취급하지 않습니다. 준비 절차와 해석 한계는 [데이터 안내](docs/DATA.md)를 확인하세요.

## 실행

지도 표시와 주소 검색을 사용하려면 `.env`에 NAVER Maps 식별자·비밀키를 입력하고, Maps 애플리케이션에 실제 접속 URL을 등록합니다. 비밀키는 서버에서만 사용합니다.

```bash
python -m app.intake_api
```

- 화면: <http://localhost:8766/>
- API 문서: <http://localhost:8766/docs>
- 상태: <http://localhost:8766/health>

위치·업종·운영 상태를 저장한 뒤 분석할 상권·분기를 확인하고 결과 메뉴를 선택합니다. 프로필과 분석 조건은 브라우저 세션별 SQLite에 보존됩니다. 회원 계정이나 장치 간 동기화 기능은 포함하지 않습니다.

## 자료 상태·실시간 발행 확인·문화행사 API

다른 `/api/onboarding/*` 경로와 같이 Host·Origin 검사, 세션 쿠키, `Cache-Control: no-store`를 적용합니다. 세 경로 모두 서비스가 쓰는 공식 원본(`data/raw/official`)과 분석 카탈로그(`data/official`)를 바꾸지 않습니다.

| 경로 | 하는 일 |
|---|---|
| `GET /api/onboarding/data-status` | 앱이 읽은 분석 카탈로그 기준 적재 분기(`periods`, `latest_period`), 준비 단계에서 SHA-256으로 검증한 원본 중 지금 있는 파일 수(`verified_files`/`listed_files`/`missing_files`), 최신 분기 전체 건수(`local_totals`), 마지막 실시간 확인 시각(`last_synced_at`, 없으면 `null`), 인증키 설정 여부(`key_configured`, 키 값은 넣지 않음) |
| `POST /api/onboarding/data-sync` | 추정매출·점포·길단위인구 3개 자료에 대해 서버 최신 분기의 서울시 전체 건수와 다음 2개 분기 발행 여부(`INFO-000` 있음, `INFO-200` 없음)를 1~5건 조회로 확인합니다. 조회마다 5초 제한, 자료별 실패는 `datasets.<자료>.error`로 돌려주고 500을 내지 않습니다. 한 번에 하나만 실행하며 진행 중에 다시 부르면 `429`, 성공 직후 30초 안의 재요청은 앞 결과(`reused: true`)를 돌려줍니다. |
| `GET /api/onboarding/cultural-events?district=동작구` | 서울시 문화행사 정보(`culturalEventInfo`) 목록 앞 2,000건(1,000건씩 두 쪽) 중 끝나지 않은 행사를 자치구(`GUNAME`)로 고릅니다. 목록이 시작일이 늦은 순이라 앞 40건만으로는 동네 행사가 거의 걸리지 않습니다(11/19 실제 목록: 동작구 0건 → 2,000건이면 7건). 둘째 쪽을 못 받으면 첫 쪽만으로 답합니다. 맞는 행사가 없으면 서울 전체(`fallback: true`), 응답은 메모리에 10분 보관(첫 쪽 실패는 1분), `district`는 서울 25개 자치구 이름 또는 빈 값만 받습니다(그 밖은 `422`). |

- 다음 분기가 발행돼도 자료를 자동으로 바꾸거나 수집하지 않습니다(`staged: null`, `data_changed: false`). 앱이 시작할 때 읽은 카탈로그를 캐시하므로, 서비스를 멈춘 뒤 새 분기를 포함한 자료 묶음을 다시 설치하거나 `python -m scripts.prepare_data --from-dir ...`로 준비하고 다시 시작합니다(`apply_hint`).
- `SEOUL_OPENAPI_KEY`가 비어 있으면 실시간 확인은 서울시 공개 `sample` 키로 1~5건만 확인하고 `sample_only: true`와 안내를 돌려줍니다. 이때는 마지막 확인 시각을 저장하지 않습니다. 문화행사는 키가 없거나 조회·응답 확인에 실패하면 `demo: true`와 '예시'로 표시한 가짜 목록을 돌려줍니다.
- 쓰는 파일은 `ONBOARDING_DB_PATH`가 있는 폴더(기본 `data/`)의 `market-data-sync.json` 하나이며, 실제 키로 실패 없이 확인했을 때만 갱신합니다.
- 인증키는 `SeoulClient`가 환경 변수에서만 읽습니다. 응답·로그·상태 파일에는 키를 넣지 않고, 진단용 주소는 키 자리를 `REDACTED`로 바꿉니다. 시험은 가짜 응답만 쓰며 서울시 API를 호출하지 않습니다.

공개 서버에서는 `APP_PUBLIC_ORIGIN`에 실제 HTTPS origin 하나를 지정하고 Nginx 등에서 loopback 앱으로 연결합니다. 개인 서버 IP·SSH 설정·인증서·자동 배포 스크립트는 이 패키지에 포함하지 않습니다.

## 검증

공식 원본이나 API 키 없이 실행할 수 있는 회귀 시험:

```bash
python -m scripts.verify_source
node --test tests/onboarding_ui.test.js
```

공식 자료를 준비한 뒤 원천 대조를 포함해 실행:

```bash
python -m scripts.verify_source --with-official
```

공식 자료 회귀는 위에 안내한 2024Q3~2026Q2의 8분기와 그 안의 대표 상권·업종 사례를 기준으로 합니다. 임의의 일부 분기만 수집한 자료에 대한 범용 합격 판정이 아닙니다. 새 자료 범위로 변경하면 대응하는 독립 기대값과 시험 범위도 검토해야 합니다.

검증은 시험용 저장소를 사용하며 외부 API·모델·실제 사용자 DB를 사용하지 않습니다. 필수 자료가 없으면 공식 자료 검증은 실패로 종료하므로 자료 미준비를 통과로 기록하지 않습니다. 이번 패키지의 실제 결과와 기존 배포 검증의 범위는 [검증 기록](docs/VALIDATION.md)에 구분합니다.

## 구조

```text
app/         기본 입력·지도·자료 검증·B1~B6 API와 계산
app/static/  기본 분석 화면
scripts/     명시적 공식 자료 준비와 오프라인 검증
tests/       계산·API·화면·자료 준비 회귀
docs/        데이터 범위와 검증 기록
data/        실행 중 생성되는 공식 자료·카탈로그·DB (Git 제외)
```

상권 통계는 개별 가게의 실적이 아닙니다. 유동인구는 업종 고객 수가 아니며, 현재 공개 경계와 각 통계분기의 실제 경계 동일성도 확정하지 않습니다. 자료 없음·미수집·관측값 0·검증 실패를 구분합니다.
