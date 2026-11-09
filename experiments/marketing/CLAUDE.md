# 마케팅 기능 (소상공인 AI 비서)

- 구조: config.py(키·경로) · clova.py(call, parse_json) · common/(dates.py, korean.py) · features/(기능) · samples/(합성 가게 데이터) · tests/(검증) · scripts/(일회성 확인용)
- 실행은 항상 이 폴더(experiments/marketing)에서: python -m tests.test_이름
- data/, results/ 안 파일은 열지 않는다 (용량 큼). 필요하면 경로만 쓴다.
- CLOVA·서울시·TourAPI·OCR 등 외부 API를 실제로 호출하는 실행은 하지 않는다. 검증은 py_compile + 가짜 데이터/가짜 응답 테스트로.
- 원칙: 날짜·숫자·사실은 코드가 계산하고, AI는 글만 쓴다. AI 결과는 점검 → 걸리면 다시 쓰기.
- 기존 파일은 필요한 함수 정의만 grep으로 확인하고, 파일 전체를 읽지 않는다.
- 키·비밀번호는 코드에 쓰지 않고 환경변수로만 읽는다.
- 사용자에게 보이는 문구는 한국어 해요체. 가게·리뷰는 합성 데이터.
- 작업이 끝나면 바뀐 파일 목록과 실행 방법만 짧게 알려 준다.