"""방문자 id. 공개 주소를 여러 사람이 열 때 붙여넣은 리뷰와 승인 기록이 섞이지 않게 나누는 값입니다.

- 브라우저 쿠키에 둔 임의의 값입니다 (로그인이 아닙니다). 값을 아는 쪽이 그 방문자의 기록을 봅니다.
- 파일 이름에도 들어가므로 영문·숫자·`-`·`_` 1~64자만 받습니다. `/`, `.`, 줄바꿈이 들어간 값은 모두 막습니다.
- 값을 안 주면 `COMMON_VISITOR`(공용)입니다. 지금까지처럼 모두가 한 곳을 보는 동작이고, 리뷰 분석 서버 자체 화면과
  기존 시험이 이 값으로 돕니다.

services/review-insight 는 저장소 루트가 import 경로에 없어도 도는 서비스라서 같은 규칙의 사본을 자기 폴더에
둡니다 (app/service.py). 규칙을 바꾸면 둘을 같이 고치세요. 두 사본이 같은 답을 내는지는 시험이 확인합니다.
"""
from __future__ import annotations

import re
import secrets

COMMON_VISITOR = "common"
MAX_LENGTH = 64
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")   # fullmatch 로만 씀: `$` 는 끝의 줄바꿈 앞에서도 맞아서 쓰지 않는다


def is_valid_visitor_id(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def clean_visitor_id(value: str | None) -> str:
    """None·빈 값 → 공용. 형식이 틀리면 ValueError (경로를 벗어나는 값은 여기서 막힌다)."""
    if value is None or value == "":
        return COMMON_VISITOR
    if not is_valid_visitor_id(value):
        raise ValueError(f"방문자 id 는 영문·숫자·-·_ 1~{MAX_LENGTH}자여야 합니다")
    return value


def new_visitor_id() -> str:
    """추측하기 어려운 새 값 (32자)."""
    return secrets.token_urlsafe(24)


def visitor_from_cookie(value: str | None) -> str | None:
    """쿠키 값이 쓸 수 있는 방문자 id 면 그대로, 아니면 None (새로 만들어 줘야 함). 공용 값은 쿠키로 받지 않는다."""
    if value is not None and value != COMMON_VISITOR and is_valid_visitor_id(value):
        return value
    return None
