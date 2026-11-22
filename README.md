# 텔레토비 AI 비서 — 배달 음식점 사장님을 위한 AI 비서

NAVER Cloud Hyper-Local AI 챌린지 「소상공인 맞춤형 스마트 AI비서」 과제 제출작입니다. (팀 텔레토비조직단)

사장님이 **밤 11시에 한 화면에서** 오늘 리뷰와 상권 숫자를 보고, 추천 카드 2장 중 하나를 고르면, AI(HyperCLOVA X HCX-005)가 답글·재발 방지 공지·홍보글 초안을 쓰고, 사장님이 **직접 승인**해야 끝나는 흐름입니다.

```
① 오늘의 브리핑  →  ② 추천 카드 2장  →  ③ AI 초안 생성  →  ④ 사장님 승인
 (리뷰 + 상권 숫자)     (근거 문장 포함)     (답글·공지·홍보글)      (승인 전에는 완료 아님)
```

## 이 비서가 지키는 원칙

- **숫자는 코드가 계산합니다.** 매출·점포·유동인구의 합계·비율·변화율은 서버가 계산하고, AI는 계산된 숫자를 문장으로 옮길 뿐입니다.
- **AI가 쓴 글은 코드가 다시 검사합니다.** 근거 숫자를 실제로 썼는지, 상권 이름·시간대를 바꾸지 않았는지, 하지 않은 조치(환불·보상 약속)를 약속하지 않았는지 규칙으로 점검하고(`shared/answer_check.py`, `experiments/marketing/c6`), 통과하지 못하면 고정 문장으로 바꾸거나 '확인 필요'로 표시합니다.
- **사장님이 승인해야 끝납니다.** AI는 초안만 만듭니다.

## 화면 구성

| 묶음 | 메뉴 | 하는 일 |
|---|---|---|
| 홈 | 홈 | 오늘의 핵심 문제 한 줄, 숫자 타일, 오늘 할 일 |
| 오늘 처리 | 추천 카드 · 승인할 글 · 처리 완료 | 카드 고르기 → 초안 확인·다시 만들기 → 승인 |
| 살펴보기 | 리뷰 분석 · 상권 분석 · 종합 리포트 | 불만을 주제별로 묶기, 서울시 공식 자료 기반 상권 조회·비교, 주간·월간 보고서(PDF 저장) |
| 키우기 | 맞춤 마케팅 | 조건을 고르면 손익을 계산하고 홍보 방법과 초안을 제안 |
| 오른쪽 서랍 | AI에게 묻기 | 상권·고객응대·마케팅·리포트에 대한 질문과 화면 이동 |

로그인 뒤 가게를 고르고(시연용 가상 가게 3곳, 직접 등록도 가능), 같은 화면에서 데스크톱·휴대폰 폭 모두 쓸 수 있습니다.

## 구조

화면(React 18 + Vite 5)은 한 서버(FastAPI)가 주고, 그 서버가 안쪽 서비스 셋을 대신 부릅니다. 브라우저는 안쪽 서비스를 직접 부르지 않습니다.

| 서비스 | 폴더 | 포트 | 역할 |
|---|---|---|---|
| 비서 화면 서버 | [`services/web`](services/web/README.md) | 8000 | 화면 파일 + API, 추천 카드, 승인 기록 |
| 리뷰 분석 | [`services/review-insight`](services/review-insight/README.md) | 8020 | 리뷰 분류·묶음, 캡처 입력, 고객응대 점수 |
| 맞춤 마케팅 | `experiments/marketing` | 8030 | 설문형 마케팅 제안, 답글·공지·홍보글 생성(C6) |
| 상권 분석 | [`services/market-analysis`](services/market-analysis/README.md) | 8766 | 서울시 공식 자료 기반 상권 조회·비교, 서랍의 상권 답 |

| 폴더 | 내용 |
|---|---|
| `shared/` | 서비스 사이의 데이터 계약(`contracts.py`), 답변 검사기, 저장 계층 |
| `db/` | PostgreSQL 표 정의 (`DB_HOST`를 줄 때만 사용, 없으면 메모리·파일로 동작) |
| `deploy/` | NAVER Cloud 서버 설치 묶음 (Nginx → 로드 밸런서 → WAS → Cloud DB for PostgreSQL, 키는 Secret Manager) |
| `docs/` | API 설명서, 서버 아키텍처, 데모 상권 선정 근거 |
| `data/scenario/` | 데모 상권(장승배기역 4번)의 공개 집계 자료 요약 |
| `tests/`, 각 서비스의 `tests/` | 자동 시험 |

## 키 없이 실행해 보기

필요한 것: Python 3.11 이상, Node.js 20 이상. **API 키는 필요 없습니다.**

```bash
# 처음 한 번만, 저장소 루트에서
python3.11 -m venv .venv && .venv/bin/pip install -r services/web/requirements.txt -r services/review-insight/requirements.txt

# 키 없이 도는 시험용 실행 (화면 빌드가 없으면 run.sh 가 먼저 npm ci · npm run build)
APP_MODE=mock services/web/run.sh

# 브라우저에서 http://localhost:8000 을 엽니다. 로그인 화면의 '시연 사장님으로 시작'을 누르면 가상 가게 3곳이 보입니다.
curl -s http://localhost:8000/api/health     # 서버 상태 확인
```

- 상권 분석 화면과 서랍의 상권 답은 서울시 공식 자료가 있어야 켜집니다. 자료는 저장소에 넣지 않았습니다(아래 「데이터와 출처」). 자료가 없으면 `run.sh`가 상권 서비스를 띄우지 않고 알려 줍니다.
- 실행 방식은 `APP_MODE`로 고릅니다.

| `APP_MODE` | 글(답글·공지·홍보글) | 키 |
|---|---|---|
| `mock` | **미리 저장된 예시**를 카드에 맞춰 보여 줍니다. 실제 AI 결과가 아니며, 화면 맨 위에 "시험용 실행" 띠가 뜹니다. | 필요 없음 |
| `live` | HCX-005가 실시간으로 씁니다(호출마다 비용). | CLOVA Studio 키 필요 |

## 데이터와 출처

- **리뷰와 가게는 모두 합성(가상) 데이터입니다.** 가게 3곳(온기한식·바삭치킨·몽글카페)과 리뷰 100건은 시연·시험용으로 만들었고 `data_origin: "synthetic"`이 붙어 있습니다. 손님 닉네임·주소·전화번호 칸은 없고, 사장님이 붙여넣은 리뷰 속 전화번호·이메일·링크·긴 번호는 저장하기 전에 `[가림]`으로 바꿉니다.
- **상권 숫자는 서울시 열린데이터광장의 공개 자료**(상권 추정매출·점포·길단위 인구·상권 영역)를 사용했고, 지도와 주소 검색은 NAVER Maps를 씁니다. 원본 자료는 용량 때문에 git 밖에 두었고, 출처와 준비 방법은 [`services/market-analysis/docs/DATA.md`](services/market-analysis/docs/DATA.md)에 있습니다. 데모 상권 선정 근거는 [`docs/c4-evening-sales-comparison.md`](docs/c4-evening-sales-comparison.md)입니다.

## 키와 개인정보

- **저장소에는 API 키·비밀번호·토큰이 없습니다.** 키는 저장소 밖의 환경 파일에서 읽고, 배포 서버에서는 NAVER Cloud Secret Manager에서 부팅할 때 받아 메모리에만 둡니다([`deploy/fetch_secrets.py`](deploy/fetch_secrets.py)). 저장소에 있는 `.env.example`·`deploy/env.example`은 비밀 값 칸이 빈 틀입니다.

## 시험

```bash
cd services/review-insight && pytest -q        # 리뷰 분석 (키 필요 없음, CLOVA 응답은 가짜)
cd services/web/frontend && npm ci && npm test # 화면 시험 (vitest)
```

그 밖의 서비스별 시험 방법은 각 서비스 README에 있습니다.

## 더 읽을 문서

- [API 설명서 겸 화면 안내서](docs/api/contract.md) — API 9개와 프록시, 화면 규칙, 저장 방식
- [서버 아키텍처](docs/infra/architecture.md) — NAVER Cloud 3계층 구성
- [서버 설치 묶음](deploy/README.md) — 설치·갱신·문제 해결 순서

## 라이선스

이 저장소는 공모전 제출용이며, 별도 라이선스를 정하지 않았습니다. 재사용이 필요하면 팀에 문의해 주세요.
