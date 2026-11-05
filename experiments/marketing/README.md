# 소상공인 AI 마케팅 비서 (experiments/marketing)

동네 가게 사장님의 마케팅을 돕는 기능 모음. 가게·리뷰는 모두 합성 데이터입니다.

## 폴더 구조

- `config.py` — 공통 설정 (모델명, 경로, API 키)
- `clova.py` — HyperCLOVA X 호출·JSON 파싱
- `common/` — 공용 유틸 (dates.py, korean.py)
- `features/` — 기능별 모듈 (tone, event_plan, coupon, notice, weekly, assistant 등)
- `samples/` — 합성 가게 데이터 (테스트·스크립트 공용)
- `tests/` — 기능 검증 테스트
- `scripts/` — 일회성 확인·점검용 스크립트
- `data/` — 외부 API에서 받은 원본 데이터 (용량 큼, 직접 열지 않음)
- `results/` — 테스트 실행 결과

## 준비

1. `.env.example`을 복사해 `.env`로 만들고 키를 채운다.
2. 환경변수를 로드한다 (또는 실행 시 입력).

## 데이터 받기

```bash
python -m features.events                  # 서울시 문화행사 → data/events_raw.json
python -m scripts.check_tour_festivals     # 한국관광공사 TourAPI → data/tour_festivals_raw.json
```

## 테스트 실행

```bash
python -m tests.test_tone           # 말투 테스트
python -m tests.test_tone_learn     # 수정 학습 테스트 (API 없음)
python -m tests.test_event_plan     # 행사 추천 + 어필 계획
python -m tests.test_coupon         # 쿠폰 만들기 (API 없음)
python -m tests.test_notice         # 휴무 공지
python -m tests.test_weekly         # 이번 주 추천
python -m tests.test_store_profile  # 가게 정보 점검
python -m tests.test_assistant      # 통합 비서
```

## 확인 스크립트

```bash
python -m scripts.check_tour_festivals    # TourAPI 행사 확인 (API 키 필요)
```
