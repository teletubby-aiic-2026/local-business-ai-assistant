# 시험 고정 데이터 (모두 합성·공개 데이터)
- insight_ongi.json · reviews_ongi.json · store_ongi.json: PR #14 `da77e27`을 APP_MODE=mock 으로 띄워 받은 응답 (11/9)
- snapshot_pr17.json: PR #17 `5dd11ad` data/scenario/snapshot_2026Q2.json 그대로 (서울시 공개 통계)
- snapshot_pr17_evening.json: PR #17 `a072ef2` data/scenario/snapshot_2026Q2.json 그대로 (저녁 17~24시, 두 분기 공통 업종, 서울시 공개 통계)
- 이 데이터로 mock(키 없이 도는 시험용 실행)과 live 를 시험합니다. live 시험도 HCX 를 부르지 않고 가짜 함수를 씁니다. 발표 모드 저장본은 없습니다.
