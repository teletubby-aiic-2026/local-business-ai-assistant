"""CLOVA Studio 요청을 구성하고 고정 응답으로 로컬 처리 흐름을 확인합니다.

실제 API 호출, 인증, 스트리밍(SSE) 처리는 이 단계에 포함하지 않습니다.
응답은 앞서 Playground에서 확인한 문장을 재사용하는 고정 테스트 데이터입니다.

실행: python clova_mock_test.py
"""

import json
from pathlib import Path


MODEL = "HCX-005"
SYSTEM_PROMPT = (
    "당신은 소상공인 매장의 고객 문의를 돕는 AI 비서입니다.\n"
    "제공된 매장 정보만 근거로 한국어로 간결하게 답하세요.\n"
    "정보가 없으면 추측하지 말고 확인이 필요하다고 안내하세요."
)
HOURS_QUESTION = (
    "다음은 테스트용 가상 매장 정보입니다.\n"
    "- 매장명: 달빛카페\n"
    "- 영업시간: 월요일~금요일 10:00~20:00\n"
    "- 토요일·일요일: 휴무\n\n"
    "고객 질문: 토요일 오후 2시에 방문해도 되나요?"
)
PARKING_QUESTION = "달빛카페에 주차할 수 있나요? 주차 요금도 알려주세요."

# 모델이 생성하는 답변이 아닙니다. 관찰한 Playground 답변을 모의 데이터로 사용합니다.
MOCK_REPLIES = {
    HOURS_QUESTION: (
        "달빛카페는 토요일과 일요일에 휴무이므로, 토요일 오후 2시에는 방문하실 수 없습니다. "
        "평일(월요일~금요일)에 방문해 주세요."
    ),
    PARKING_QUESTION: (
        "주차 가능 여부와 요금은 제공된 매장 정보에 포함되어 있지 않습니다. "
        "이 부분은 직접 확인해 보셔야 할 것 같습니다. 양해 부탁드립니다."
    ),
}


def message(role, text):
    return {"role": role, "content": [{"type": "text", "text": text}]}


def build_request(case_id):
    messages = [message("system", SYSTEM_PROMPT), message("user", HOURS_QUESTION)]
    if case_id == "parking_unknown":
        messages.extend([
            message("assistant", MOCK_REPLIES[HOURS_QUESTION]),
            message("user", PARKING_QUESTION),
        ])
    elif case_id != "opening_hours":
        raise ValueError(f"지원하지 않는 테스트 사례: {case_id}")

    # 문자열 JSON을 직접 조립하지 않고 Python 자료형으로 구성합니다.
    return {
        "messages": messages,
        "topP": 0.8,
        "topK": 0,
        "maxTokens": 256,
        "temperature": 0.5,
        "repetitionPenalty": 1.1,
        "stop": [],
        "seed": 0,
        "includeAiFilters": True,
    }


class MockCompletionExecutor:
    """공식 API 응답 형식 대신, 이 예제 내부에서 사용할 답변 문자열을 반환합니다."""

    def execute(self, completion_request):
        messages = completion_request["messages"]
        if not messages or messages[-1]["role"] != "user":
            raise ValueError("답변을 요청할 대화는 사용자 질문으로 끝나야 합니다.")
        question = messages[-1]["content"][0]["text"]
        if question not in MOCK_REPLIES:
            raise ValueError("이 질문에 대응하는 고정 모의 응답이 없습니다.")
        return MOCK_REPLIES[question]


def main():
    executor = MockCompletionExecutor()
    results = []
    print("[MOCK] 고정 응답을 사용합니다. 실제 API 호출: 0회")
    for case_id in ("opening_hours", "parking_unknown"):
        # 한국어·개행을 포함한 요청의 JSON 직렬화와 역직렬화도 확인합니다.
        request = build_request(case_id)
        request_json = json.dumps(request, ensure_ascii=False)
        restored_request = json.loads(request_json)
        if restored_request != request:
            raise RuntimeError("JSON 변환 과정에서 요청 내용이 달라졌습니다.")
        reply = executor.execute(restored_request)
        if not isinstance(reply, str) or not reply.strip():
            raise RuntimeError("모의 응답이 비어 있습니다.")

        results.append({
            "case_id": case_id,
            "model_for_future_api_call": MODEL,
            "request": restored_request,
            "mock_response_text": reply,
            "local_flow_check": "passed",
        })
        print(f"[{case_id}] 로컬 처리 완료\n{reply}\n")

    report = {
        "mode": "mock",
        "network_called": False,
        "actual_api_calls": 0,
        "response_source": "fixed_fixtures_from_observed_playground_answers",
        "scope": "요청 구성, JSON 변환, 고정 응답 처리, 결과 파일 기록",
        "not_verified": ["API 인증", "HTTP 연결", "SSE 처리", "모델 응답 생성"],
        "results": results,
    }
    output = Path(__file__).resolve().parent / "output" / "clova_mock_results.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 저장한 파일이 정상적인 JSON이고 원래 결과와 같은지 확인합니다.
    if json.loads(output.read_text(encoding="utf-8")) != report:
        raise RuntimeError("저장된 결과가 실행 결과와 다릅니다.")
    print(f"결과 저장: {output}")


if __name__ == "__main__":
    main()
