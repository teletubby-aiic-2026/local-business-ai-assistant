"""저장 계층 오류. 메시지에는 DB 비밀번호가 들어가지 않습니다."""
from __future__ import annotations


class StorageError(RuntimeError):
    """DB 에 닿지 못했거나 질의가 시간 안에 끝나지 않았을 때. 잠시 뒤 다시 하면 되는 오류입니다 (장애 전환 중 등)."""


class StorageConfigError(ValueError):
    """DB 환경 변수나 드라이버(psycopg) 설치가 잘못됐을 때. 켜질 때 바로 알리려고 따로 둡니다."""


class DuplicateLogin(ValueError):
    """같은 로그인 아이디가 이미 있을 때 (회원가입). 두 구현이 같은 오류를 낸다."""
