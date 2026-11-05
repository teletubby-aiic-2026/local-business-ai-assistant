# marketing

테스트 실행 방법 (CLOVA Studio API 키는 환경변수 `CLOVA_API_KEY`에 설정하거나 실행 시 입력):

```
python -m tests.test_event_promo   # data/events_nearby.json 필요 (features/events.py로 먼저 생성)
python -m tests.test_notice
python -m tests.test_tone
```
