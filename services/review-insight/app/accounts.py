"""가게 계정: 아이디·비밀번호로 로그인하면 그 가게의 리뷰·가게 정보만 보이게 하기 위한 확인 창구.

누가 부르나: 통합 화면 서버(integration/care_proxy.py)만 부른다. 브라우저는 이 주소에 직접 오지 않는다.
이 모듈은 "아이디·비밀번호가 맞는가, 맞다면 어느 가게인가"만 답한다. 로그인 상태(세션 쿠키)는 화면 서버가 가진다.

계정 두 종류
1) 시연용 계정: 합성 가게 3곳. 아이디는 가게 ID 에서 store_ 를 뗀 값 (ongi · basak · mongle).
   비밀번호는 환경 변수 DEMO_ACCOUNT_PASSWORD 하나를 같이 쓴다. 비어 있으면 시연용 계정으로는 로그인할 수 없다.
   (비밀번호를 코드·저장소에 넣지 않기 위해서다.)
2) 가입한 계정: POST /auth/accounts 로 만든다. 새 가게(store_<아이디>)가 합성 리뷰 없이 0건으로 함께 만들어진다.
   data/runtime/accounts.json 에 소금과 scrypt 해시만 저장한다 (비밀번호 원문은 저장·로그하지 않음).
   ACCOUNT_SIGNUP_CODE 를 정하면 그 값을 같이 보낸 가입만 받는다.

WAS 가 2대면 accounts.json 과 새 가게 파일이 서버마다 달라진다 (docs/handoff.md '서버' 절). DB 표가 생기기 전에는 1대로 시연한다.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from app import service

LOGIN_ID = re.compile(r"[a-z][a-z0-9]{2,19}")       # 가게 ID(store_<아이디>)에 들어가므로 소문자·숫자만
PASSWORD_MIN, PASSWORD_MAX = 8, 72
FAILS_ALLOWED, FAIL_WINDOW = 5, 300                 # 같은 아이디로 5분에 5번 틀리면 잠시 막는다
_lock = threading.RLock()
_fails: dict[str, deque] = defaultdict(deque)
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}


class LoginFailed(Exception):
    """아이디가 없거나 비밀번호가 틀림 (어느 쪽인지 알려 주지 않는다)."""


class TooManyTries(Exception):
    pass


def _file() -> Path:
    return service.RUNTIME / "accounts.json"


def _load() -> dict[str, dict]:
    try:
        return json.loads(_file().read_text(encoding="utf-8")).get("accounts") or {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(rows: dict[str, dict]) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"accounts": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)


def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT).hex()


def demo_accounts() -> dict[str, str]:
    """시연용 아이디 → 합성 가게 ID."""
    return {s.removeprefix("store_"): s for s in service.synthetic_store_ids()}


def _demo_password() -> str:
    return os.getenv("DEMO_ACCOUNT_PASSWORD", "").strip()


def _check_password(password) -> str:
    if not isinstance(password, str) or not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise ValueError(f"비밀번호는 {PASSWORD_MIN}~{PASSWORD_MAX}자여야 합니다")
    return password


def _account(login_id: str, store_id: str, demo: bool) -> dict:
    return {"login_id": login_id, "store_id": store_id, "store_name": service.store(store_id).get("name", store_id), "demo": demo}


def login(login_id: str, password: str, *, clock=time.monotonic) -> dict:
    """맞으면 {"login_id","store_id","store_name","demo"}. 틀리면 LoginFailed, 너무 자주 틀리면 TooManyTries."""
    login_id = (login_id or "").strip().lower() if isinstance(login_id, str) else ""
    password = password if isinstance(password, str) else ""
    now = clock()
    with _lock:
        tries = _fails[login_id]
        while tries and now - tries[0] > FAIL_WINDOW:
            tries.popleft()
        if len(tries) >= FAILS_ALLOWED:
            raise TooManyTries()
        found = None
        demo, row = demo_accounts().get(login_id), _load().get(login_id)
        if demo:
            expected = _demo_password()
            # 비어 있으면 늘 실패. 길이가 달라도 같은 시간에 비교한다
            ok = bool(expected) and hmac.compare_digest(password.encode("utf-8"), expected.encode("utf-8"))
            found = _account(login_id, demo, True) if ok else None
        elif row:
            ok = hmac.compare_digest(_hash(password, bytes.fromhex(row["salt"])), row["hash"])
            found = _account(login_id, row["store_id"], False) if ok else None
        else:
            _hash(password, b"no-such-account-salt")      # 없는 아이디도 비슷한 시간이 걸리게
        if found is None:
            tries.append(now)
            if len(_fails) > 5000:                        # 아무 아이디나 넣어 기록을 불리는 것 막기
                _fails.clear()
            raise LoginFailed()
        _fails.pop(login_id, None)
        return found


def signup(login_id: str, password: str, store_name: str, business_type_name: str | None = None, *,
           signup_code: str | None = None) -> dict:
    """새 계정과 새 가게(store_<아이디>, 리뷰 0건)를 만든다. 입력이 틀리면 ValueError, 가입 코드가 틀리면 PermissionError."""
    expected = os.getenv("ACCOUNT_SIGNUP_CODE", "").strip()
    if expected and not hmac.compare_digest((signup_code or "").strip().encode("utf-8"), expected.encode("utf-8")):
        raise PermissionError("가입 코드가 맞지 않습니다")
    login_id = (login_id or "").strip().lower() if isinstance(login_id, str) else ""
    if not LOGIN_ID.fullmatch(login_id):
        raise ValueError("아이디는 영문 소문자로 시작하는 소문자·숫자 3~20자여야 합니다")
    _check_password(password)
    store_id = f"store_{login_id}"
    with _lock:
        rows = _load()
        if login_id in rows or login_id in demo_accounts() or store_id in service.store_ids():
            raise ValueError("이미 쓰고 있는 아이디입니다")
        service.create_store(store_id, store_name, business_type_name)
        salt = secrets.token_bytes(16)
        rows[login_id] = {"store_id": store_id, "salt": salt.hex(), "hash": _hash(password, salt),
                          "created_at": datetime.now(service.KST).isoformat(timespec="seconds")}
        _save(rows)
    return _account(login_id, store_id, False)
