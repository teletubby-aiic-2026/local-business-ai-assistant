# CLOVA Studio 호출 실험

HCX-005로 가상 매장 달빛카페의 기본 응답과 Function calling을 확인합니다. 모델이 `get_store_info`를 선택하면 로컬 함수가 가상 매장 JSON을 반환하고, 모델이 이를 바탕으로 최종 답변을 생성합니다. Python 3.14.4에서 검증했으며 추가 패키지 설치는 필요하지 않습니다.

## 모의 실행과 테스트

저장소 루트에서 아래 명령을 실행합니다. 이 단계는 API 키가 필요 없으며 외부 API 요청은 0회입니다.

```powershell
cd experiments/clova
python -B -X utf8 clova_function_calling_test.py
python -B -X utf8 -m unittest discover -s tests -p 'test_clova_function_calling.py'
```

모의 실행은 고정 모델 응답으로 흐름을 검증합니다. 자동 테스트 30개를 통과했습니다.

## 실제 호출

`.env.example`은 필요한 환경변수 이름을 보여주는 템플릿입니다. 코드가 `.env` 파일을 자동으로 읽지는 않습니다. PowerShell에서 키를 화면에 표시하지 않고 현재 세션의 환경변수에 넣으려면 다음 명령을 사용합니다.

```powershell
$env:CLOVA_STUDIO_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'CLOVA Studio API 키 입력' -AsSecureString)).Password
```

같은 창에서 필요한 시나리오 한 가지만 실행합니다.

```powershell
# 기본 응답: HTTP 최대 1회
python -B -X utf8 clova_function_calling_test.py --live --scenario basic

# 도구 선택과 최종 답변: HTTP 최대 2회
python -B -X utf8 clova_function_calling_test.py --live --scenario function
```

`--live` 없이 실행하면 실제 API를 호출하지 않습니다. 오류 시 자동 재시도 없이 종료합니다. 기본 호출은 `max_tokens=256`, Function calling은 `1024`를 사용하며, 실제 토큰 사용량과 응답시간은 `output/`의 JSON에 기록합니다. `output/`과 실제 환경설정 파일은 `.gitignore`에 포함했습니다.

## 파일 구성

- `clova_function_calling_test.py`: OpenAI 호환 REST API의 기본 응답과 Function calling 실험
- `clova_live_test.py`: 네이티브 v3 호출 실험 및 공통 통신·환경변수 함수
- `clova_mock_test.py`: 가상 데이터와 네이티브 요청 구성
- `tests/test_clova_function_calling.py`: 외부 API 호출 없는 자동 테스트

세 실행 파일은 서로 import하므로 함께 보관해야 합니다. 실제 API 키는 GitHub에 올리지 않습니다.

공식 문서: [OpenAI 호환 API](https://api.ncloud-docs.com/docs/clovastudio-openaicompatibility), [Function calling](https://api.ncloud-docs.com/docs/clovastudio-chatcompletionsv3-fc)
