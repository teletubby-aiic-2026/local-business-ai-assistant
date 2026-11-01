"""CLOVA Studio OpenAI 호환 REST API의 기본 응답과 Function calling 실험.

기본 실행은 모델 응답도 고정한 모의 실험입니다. --live에서만 실제로 호출합니다.
all: 기본 요청 1회 + 도구 선택 1회 + 도구 결과 기반 최종 답변 1회, 최대 3회.
가짜 가게 JSON 함수는 항상 로컬에서만 실행하며 외부 검색이나 개인정보를 사용하지 않습니다.

공식 형식: https://api.ncloud-docs.com/docs/clovastudio-openaicompatibility
Function calling 제약: https://api.ncloud-docs.com/docs/clovastudio-chatcompletionsv3-fc
"""

import argparse
from copy import deepcopy
from datetime import datetime
from http.client import HTTPException
import json
from pathlib import Path
import sys
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
from uuid import uuid4

from clova_live_test import ApiError, KST, NoRedirect, load_api_key, read_json, redact_values
from clova_mock_test import MODEL, SYSTEM_PROMPT, HOURS_QUESTION


ENDPOINT = "https://clovastudio.stream.ntruss.com/v1/openai/chat/completions"
MAX_REQUESTS = 3
BASIC_MAX_TOKENS = 256
# Function calling은 최대 생성 토큰 설정값이 최소 1024여야 합니다.
FUNCTION_MAX_TOKENS = 1024
STORE_NAME = "달빛카페"
STORE_INFO = {
    "data_source": "fictional_test_fixture",
    "store_name": STORE_NAME,
    "business_hours": {
        "monday_to_friday": "10:00-20:00",
        "saturday": "closed",
        "sunday": "closed",
    },
    "parking": {"available": None, "fee": None, "note": "주차 정보 미확인"},
}
TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_store_info",
        "description": "테스트용 가상 매장의 영업시간과 주차 정보를 조회합니다.",
        "parameters": {
            "type": "object",
            "properties": {"store_name": {"type": "string", "enum": [STORE_NAME]}},
            "required": ["store_name"],
            "additionalProperties": False,
        },
    },
}]
TOOL_SYSTEM = (
    "당신은 테스트용 가상 매장 안내 비서입니다. 매장에 대한 질문은 반드시 get_store_info로 "
    "조회한 뒤, 반환된 JSON만 근거로 한국어로 간결하게 답하세요. "
    "조회 결과가 null이거나 미확인인 항목은 확인이 필요하다고 말하고 추측하지 마세요."
)
TOOL_QUESTION = "달빛카페에 토요일 오후 2시에 방문해도 되나요? 주차 가능 여부와 요금도 알려주세요."


def make_payload(messages, *, tool_choice=None):
    payload = {
        "model": MODEL,
        "messages": deepcopy(messages),
        "max_tokens": FUNCTION_MAX_TOKENS if tool_choice is not None else BASIC_MAX_TOKENS,
        "temperature": 0.0,
        "top_p": 0.8,
        "stream": False,
    }
    if tool_choice is not None:
        payload["tools"] = deepcopy(TOOLS)
        payload["tool_choice"] = tool_choice
    return payload


def post_json(payload, api_key, request_id):
    request = Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "X-NCP-CLOVASTUDIO-REQUEST-ID": request_id,
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=60) as response:
            return response.status, read_json(response)
    except HTTPError as error:
        detail = ""
        try:
            with error:
                body = read_json(error)
            api_error = body.get("error", {})
            if isinstance(api_error, dict):
                detail = f" API 코드: {api_error.get('code', 'unknown')}; 안내: {api_error.get('message', '')}"
        except (ApiError, OSError, HTTPException):
            pass
        raise ApiError(f"HTTP {error.code}.{detail} 자동 재시도하지 않았습니다.") from error
    except (OSError, URLError, HTTPException) as error:
        raise ApiError("연결 또는 응답 수신 실패. 서버 처리·사용량은 미확인 상태이며 자동 재시도하지 않았습니다.") from error


def parse_choice(response):
    if not isinstance(response, dict):
        raise ApiError("OpenAI 호환 응답이 JSON 객체가 아닙니다.")
    if "error" in response:
        error = response["error"]
        if isinstance(error, dict):
            raise ApiError(f"API 오류: {error.get('code', 'unknown')}; {error.get('message', '')}")
        raise ApiError("API 오류 응답을 받았습니다.")
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ApiError("응답 choices 형식이 예상과 다릅니다.")
    choice = choices[0]
    if choice.get("finish_reason") == "length":
        raise ApiError("출력 토큰 제한으로 응답이 잘렸습니다. 완료로 처리하지 않으며 자동 재시도하지 않습니다.")
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise ApiError("응답에 assistant 메시지가 없습니다.")
    return deepcopy(message)


def final_text(response):
    message = parse_choice(response)
    if response["choices"][0].get("finish_reason") != "stop":
        raise ApiError("최종 답변의 종료 사유가 stop이 아닙니다. 완료로 처리하지 않습니다.")
    if message.get("tool_calls"):
        raise ApiError("최종 답변 대신 추가 도구 호출이 반환되었습니다. 자동 반복하지 않습니다.")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ApiError("비어 있지 않은 최종 답변 문자열이 없습니다.")
    return content


def usage_from(response):
    usage = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return None
    fields = ("prompt_tokens", "completion_tokens", "total_tokens")
    if any(type(usage.get(key)) is not int or usage[key] < 0 for key in fields):
        return None
    return {key: usage[key] for key in fields}


def execute_tool(tool_call):
    if not isinstance(tool_call, dict) or tool_call.get("type") != "function":
        raise ApiError("지원하지 않는 도구 호출 형식입니다.")
    if not isinstance(tool_call.get("id"), str) or not tool_call["id"]:
        raise ApiError("도구 호출 ID가 없습니다.")
    function = tool_call.get("function")
    if not isinstance(function, dict) or function.get("name") != "get_store_info":
        raise ApiError("허용된 get_store_info 이외의 함수는 실행하지 않습니다.")
    raw_arguments = function.get("arguments")
    if not isinstance(raw_arguments, str):
        raise ApiError("함수 인수는 JSON 문자열이어야 합니다.")
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as error:
        raise ApiError("함수 인수가 유효한 JSON이 아닙니다.") from error
    if arguments != {"store_name": STORE_NAME}:
        raise ApiError("함수 인수는 지정된 가상 매장 이름 하나만 허용합니다.")
    return deepcopy(STORE_INFO)


def mock_response(payload, stage):
    """고정 모의 모델입니다. 실모델의 판단/성능을 입증하지 않습니다."""
    if stage == "basic":
        message = {"role": "assistant", "content": "달빛카페는 토요일에 휴무이므로 방문할 수 없습니다."}
        reason = "stop"
    elif stage == "function_select":
        message = {
            "role": "assistant", "content": None,
            "tool_calls": [{
                "id": "call_mock_store_001", "type": "function",
                "function": {"name": "get_store_info", "arguments": json.dumps({"store_name": STORE_NAME}, ensure_ascii=False)},
            }],
        }
        reason = "tool_calls"
    elif stage == "function_answer":
        tool_message = payload["messages"][-1]
        if tool_message.get("role") != "tool" or tool_message.get("tool_call_id") != "call_mock_store_001":
            raise ApiError("모의 테스트에서 도구 결과의 연결 ID가 일치하지 않습니다.")
        if json.loads(tool_message["content"]) != STORE_INFO:
            raise ApiError("모의 테스트에서 도구 결과가 올바르게 전달되지 않았습니다.")
        message = {"role": "assistant", "content": "달빛카페는 토요일에 휴무이므로 오후 2시에 방문할 수 없습니다. 주차 가능 여부와 요금은 확인이 필요합니다."}
        reason = "stop"
    else:
        raise ApiError(f"알 수 없는 모의 단계: {stage}")
    return {"choices": [{"index": 0, "message": message, "finish_reason": reason}], "usage": None}


class CompletionClient:
    def __init__(self, mode="mock", api_key=None, transport=None):
        if mode not in ("mock", "live"):
            raise ValueError("mode는 mock 또는 live여야 합니다.")
        if mode == "live" and not api_key:
            raise ApiError("실호출에는 API 키가 필요합니다.")
        self.mode = mode
        self._api_key = api_key
        self._transport = transport or post_json
        self.calls = []

    def complete(self, payload, stage):
        if len(self.calls) >= MAX_REQUESTS:
            raise ApiError("한 번 실행할 때 최대 3회 요청만 허용합니다.")
        record = {
            "stage": stage,
            "request_id": uuid4().hex,
            "request": deepcopy(payload),
            "http_request_attempted": self.mode == "live",
            "elapsed_seconds": None,
            "elapsed_time_scope": "client_wall_clock_including_http_and_json_processing" if self.mode == "live" else "not_measured_for_mock",
            "usage": None,
            "status": "started",
        }
        self.calls.append(record)
        started = perf_counter()
        try:
            if self.mode == "live":
                http_status, response = self._transport(payload, self._api_key, record["request_id"])
                record["http_status"] = http_status
                if not 200 <= http_status < 300:
                    raise ApiError(f"HTTP 오류 상태: {http_status}")
            else:
                response = mock_response(payload, stage)
            record["response"] = deepcopy(response)
            record["usage"] = usage_from(response)
            parse_choice(response)
            record["status"] = "response_received"
            return response
        except (ApiError, OSError) as error:
            record["status"] = "failed_or_unconfirmed"
            record["error"] = str(error)
            raise
        finally:
            duration = round(perf_counter() - started, 6)
            if self.mode == "live":
                record["elapsed_seconds"] = duration
            else:
                record["mock_processing_seconds"] = duration


def run_basic(client):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": HOURS_QUESTION}]
    reply = client.complete(make_payload(messages), "basic")
    return {"flow_completed": True, "response_text": final_text(reply)}


def run_function_calling(client):
    messages = [{"role": "system", "content": TOOL_SYSTEM}, {"role": "user", "content": TOOL_QUESTION}]
    first = client.complete(make_payload(messages, tool_choice="auto"), "function_select")
    selected = parse_choice(first)
    if first["choices"][0].get("finish_reason") != "tool_calls":
        raise ApiError("도구 선택 응답의 종료 사유가 tool_calls가 아닙니다.")
    tool_calls = selected.get("tool_calls")
    if not isinstance(tool_calls, list) or len(tool_calls) != 1:
        raise ApiError("모델이 도구를 정확히 하나 선택하지 않았습니다. 호출 성공으로 간주하지 않습니다.")
    tool_call = tool_calls[0]
    tool_result = execute_tool(tool_call)
    # 실제로 모델이 선택한 이름/인수/ID를 유지합니다. 임의 코드를 실행하지 않습니다.
    messages.append({"role": "assistant", "content": selected.get("content") or "", "tool_calls": deepcopy(tool_calls)})
    messages.append({"role": "tool", "tool_call_id": tool_call["id"], "content": json.dumps(tool_result, ensure_ascii=False)})
    final = client.complete(make_payload(messages, tool_choice="none"), "function_answer")
    return {
        "flow_completed": True,
        "tool_selection": "model_auto" if client.mode == "live" else "fixed_mock_model",
        "tool_executions": [{"tool_call": tool_call, "result": tool_result}],
        "response_text": final_text(final),
    }


def summarize_usage(calls):
    if not calls or any(call.get("usage") is None for call in calls):
        return None
    return {key: sum(call["usage"][key] for call in calls) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="실제 API 사용: 환경변수 CLOVA_STUDIO_API_KEY 필요")
    parser.add_argument("--scenario", choices=("all", "basic", "function"), default="all")
    args = parser.parse_args()
    mode = "live" if args.live else "mock"
    key = None
    if args.live:
        try:
            key = load_api_key()
        except ApiError as error:
            print(f"[입력 오류] {error}")
            return 2
    client = CompletionClient(mode, key)
    report = {
        "mode": mode,
        "api_format": "OpenAI-compatible REST",
        "endpoint": ENDPOINT,
        "model": MODEL,
        "max_output_tokens_by_stage": {
            "basic": BASIC_MAX_TOKENS,
            "function_select": FUNCTION_MAX_TOKENS,
            "function_answer": FUNCTION_MAX_TOKENS,
        },
        "started_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "scenario": args.scenario,
        "tool_data_source": "fictional_local_store_json",
        "automatic_retries": 0,
        "credit_context": {
            "user_reported_account_limit_krw": 1000000,
            "credit_application_verified": False,
            "remaining_balance_verified": False,
            "billing_rate_verified": False,
            "note": "100만 원 한도는 사용자 전달 정보이며, 크레딧 잔액이나 CLOVA Studio 차감 범위의 확인 근거가 아닙니다.",
        },
        "usage_reporting": "사용자 요청에 따라 실험 후 보고에 호출 횟수와 토큰을 포함",
        "scenarios": {},
        "calls": client.calls,
        "semantic_review": "실제 답변 내용은 결과 확인 후 평가. 고정 모의 답변은 모델 성능의 근거가 아님.",
    }
    planned_calls = {"all": 3, "basic": 1, "function": 2}[args.scenario]
    report["planned_max_http_requests"] = planned_calls if args.live else 0
    call_limit_label = f"실제 HTTP 요청 최대 {planned_calls}회" if args.live else "외부 API 호출 0회"
    print(f"[{mode.upper()}] {MODEL} / {args.scenario} / {call_limit_label}")
    start = perf_counter()
    exit_code = 0
    try:
        if args.scenario in ("all", "basic"):
            report["scenarios"]["basic"] = run_basic(client)
        if args.scenario in ("all", "function"):
            report["scenarios"]["function_calling"] = run_function_calling(client)
        report["status"] = "flow_completed"
    except (ApiError, OSError) as error:
        report["status"] = "failed_or_incomplete"
        report["error"] = str(error)
        exit_code = 1
    report["total_elapsed_seconds"] = round(perf_counter() - start, 6)
    report["elapsed_time_scope"] = "client_wall_clock_including_http_and_local_tool" if args.live else "local_mock_only"
    report["http_requests_attempted"] = sum(call["http_request_attempted"] for call in client.calls)
    report["model_responses_simulated"] = len(client.calls) if mode == "mock" else 0
    report["token_usage_total"] = summarize_usage(client.calls)
    safe_report = redact_values(report, key) if key else report
    suffix = uuid4().hex[:12] if args.live else "latest"
    output = Path(__file__).resolve().parent / "output" / f"clova_openai_{mode}_{suffix}.json"
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(safe_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"결과 저장: {output}")
    except OSError:
        print("[기록 오류] 결과 저장에 실패했습니다. 자동으로 다시 실행하지 마세요.")
        exit_code = 1
    for scenario, result in safe_report["scenarios"].items():
        print(f"[{scenario}] {result['response_text']}")
    if "error" in safe_report:
        print("[오류]", safe_report["error"])
    for call in safe_report["calls"]:
        elapsed = call["elapsed_seconds"]
        elapsed_label = f"{elapsed:.6f}초" if elapsed is not None else "미측정(모의)"
        print(f"[{call['stage']}] 응답시간={elapsed_label} / 토큰={json.dumps(call['usage'], ensure_ascii=False)}")
    print(f"HTTP 요청: {report['http_requests_attempted']}회 / 토큰 합계: {json.dumps(report['token_usage_total'], ensure_ascii=False)}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
