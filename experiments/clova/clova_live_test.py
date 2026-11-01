"""CLOVA Studio HCX-005에 가상 매장 질문을 한 번만 전송합니다.

기본 실행은 요청 확인만 합니다. --live를 붙여야 실제 요청을 전송합니다.
키는 현재 터미널의 CLOVA_STUDIO_API_KEY에서 읽으며 출력하거나 저장하지 않습니다.
별도 패키지 설치 없이 Python 표준 라이브러리만 사용합니다.

공식 요청/JSON 응답 형식:
https://api.ncloud-docs.com/docs/clovastudio-chatcompletionsv3
"""

import argparse
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
import json
import os
from pathlib import Path
import socket
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from clova_mock_test import MODEL, build_request


ENDPOINT = f"https://clovastudio.stream.ntruss.com/v3/chat-completions/{MODEL}"
MAX_RESPONSE_BYTES = 1024 * 1024
KST = timezone(timedelta(hours=9))


class ApiError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 재전송 없이 첫 응답에서 종료합니다.
        return None


def redact_values(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]")
    if isinstance(value, dict):
        return {name: redact_values(item, secret) for name, item in value.items()}
    if isinstance(value, list):
        return [redact_values(item, secret) for item in value]
    return value


def load_api_key():
    key = os.environ.get("CLOVA_STUDIO_API_KEY", "").strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    if not key or key in ("<api-key>", "YOUR_API_KEY"):
        raise ApiError("현재 PowerShell에 CLOVA_STUDIO_API_KEY가 없습니다. 키를 입력한 창에서 실행하세요.")
    if not key.isascii() or any(char.isspace() for char in key):
        raise ApiError("키에 공백 또는 비ASCII 문자가 있습니다. 발급받은 키 원문을 다시 입력하세요.")
    return key


def read_json(stream):
    raw = stream.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ApiError("응답이 예상 크기를 초과했습니다. 자동 재시도하지 않습니다.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ApiError("JSON 형식의 응답을 받지 못했습니다. 자동 재시도하지 않습니다.") from error
    if not isinstance(payload, dict):
        raise ApiError("응답 최상위 형식이 예상과 다릅니다.")
    return payload


def parse_completion(payload):
    status = payload.get("status")
    if not isinstance(status, dict):
        raise ApiError("응답에서 API 상태 코드를 찾을 수 없습니다.")
    code = str(status.get("code", "unknown"))
    if code != "20000":
        raise ApiError(f"API 오류 코드: {code}; 안내: {status.get('message', '없음')}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ApiError("정상 응답에서 result 항목을 찾을 수 없습니다.")
    message = result.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise ApiError("정상 응답에서 assistant 메시지를 찾을 수 없습니다.")
    text = message.get("content")
    if not isinstance(text, str) or not text.strip():
        raise ApiError("API 응답에 비어 있지 않은 답변 문자열이 없습니다.")
    usage = result.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    return {
        "api_status_code": code,
        "response_text": text,
        "usage": {name: usage[name] for name in (
            "promptTokens", "completionTokens", "totalTokens"
        ) if name in usage},
        "finish_reason": result.get("finishReason"),
        "seed": result.get("seed"),
    }


def request_once(request_data, api_key, request_id):
    request = Request(
        ENDPOINT,
        data=json.dumps(request_data, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "X-NCP-CLOVASTUDIO-REQUEST-ID": request_id,
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
        method="POST",
    )
    opener = build_opener(NoRedirect())
    try:
        # 스트리밍 대신 공식 JSON 응답을 사용하며 재시도 루프가 없습니다.
        with opener.open(request, timeout=60) as response:
            http_status = response.status
            payload = read_json(response)
    except HTTPError as error:
        hints = {
            401: "API 키의 유효성을 확인하세요.",
            403: "키와 계정의 모델 접근 권한을 확인하세요.",
            429: "이용량 제한 또는 할당량 상태를 확인하세요.",
        }
        detail = ""
        try:
            with error:
                error_payload = read_json(error)
            status = error_payload.get("status", {})
            if isinstance(status, dict):
                detail = f" API 코드: {status.get('code', 'unknown')}; 안내: {status.get('message', '')}"
        except (ApiError, OSError, HTTPException):
            pass
        raise ApiError(
            f"HTTP {error.code}. {hints.get(error.code, '응답 상태를 확인하세요.')}"
            f"{detail} 자동 재시도하지 않았습니다."
        ) from error
    except (TimeoutError, socket.timeout) as error:
        raise ApiError("응답 대기 시간이 초과되었습니다. 서버 처리·사용량은 미확인 상태이며 자동 재시도하지 않았습니다.") from error
    except URLError as error:
        raise ApiError("네트워크 또는 인증서 연결 오류입니다. 자동 재시도하지 않았습니다.") from error
    except HTTPException as error:
        raise ApiError("HTTP 응답이 중단되었거나 불완전합니다. 서버 처리·사용량은 미확인 상태이며 자동 재시도하지 않았습니다.") from error
    if not 200 <= http_status < 300:
        raise ApiError(f"예상하지 못한 HTTP 상태: {http_status}")
    return {"http_status": http_status, **parse_completion(payload)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="가상 매장 질문으로 실제 API 요청을 한 번 전송")
    args = parser.parse_args()
    request_data = build_request("opening_hours")
    if not args.live:
        print("[DRY RUN] API 호출 0회. 아래 요청을 확인했습니다.")
        print(json.dumps({"endpoint": ENDPOINT, "request": request_data}, ensure_ascii=False, indent=2))
        return 0

    try:
        api_key = load_api_key()
    except ApiError as error:
        print(f"[입력 오류] {error}")
        return 2

    request_id = uuid4().hex
    report = {
        "mode": "live",
        "started_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "endpoint": ENDPOINT,
        "model": MODEL,
        "case_id": "opening_hours",
        "request_id": request_id,
        "http_requests_attempted": 1,
        "automatic_retries": 0,
        "completion_verified": False,
        "request": request_data,
    }
    print(f"[LIVE] {MODEL}, maxTokens=256, HTTP 요청 1회 시작")
    try:
        report.update(request_once(request_data, api_key, request_id))
        report["completion_verified"] = True
        report["status"] = "response_received"
        exit_code = 0
    except (ApiError, OSError) as error:
        report["status"] = "request_failed_or_unconfirmed"
        report["error"] = str(error)
        exit_code = 1

    # 인증 헤더는 report에 넣지 않으며, 오류가 키를 반영하는 경우도 가립니다.
    safe_report = redact_values(report, api_key)
    safe_json = json.dumps(safe_report, ensure_ascii=False, indent=2)
    output = Path(__file__).resolve().parent / "output" / f"clova_live_{request_id[:12]}.json"
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(safe_json + "\n", encoding="utf-8")
    except OSError:
        print("[기록 오류] 결과 파일 저장에 실패했습니다. 아래 응답을 보관하고 자동 재실행하지 마세요.")
        exit_code = 1
    else:
        print(f"결과 저장: {output}")

    if safe_report["completion_verified"]:
        print("[응답 수신 성공]")
        print(safe_report["response_text"])
        print("토큰 사용량:", json.dumps(safe_report["usage"], ensure_ascii=False))
        if safe_report["finish_reason"] == "length":
            print("참고: 토큰 제한으로 답변이 잘렸을 수 있습니다.")
    else:
        print("[오류]", safe_report["error"])
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
