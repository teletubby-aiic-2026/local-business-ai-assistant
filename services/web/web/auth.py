"""로그인과 사장님 가게 고르기 (5차 회의 11/18).

| 메서드 | 경로                   | 하는 일 |
|--------|------------------------|---------|
| GET    | /api/auth/me           | 지금 누구인지와 가게. 로그인 전이면 authenticated false, 가게는 기본 가게(온기한식) 하나 |
| POST   | /api/auth/login        | 아이디·비밀번호 → 세션 쿠키 |
| POST   | /api/auth/signup       | 새 계정(가진 가게를 고름) → 바로 로그인 |
| POST   | /api/auth/logout       | 세션을 지우고 쿠키를 지움 → 게스트 |
| POST   | /api/auth/store        | 지금 보는 가게 바꾸기 (가진 가게만) |
| POST   | /api/auth/demo-login   | 시연용: 가게 세 곳을 가진 사장님으로 바로 로그인 (DEMO_ACCOUNT_ENABLED, 기본 켜짐) |
| POST   | /api/auth/reset        | 계정 초기화: 지금 가게(scope=store) 또는 가진 가게 모두(scope=account)의 이 사장님 기록을 지움 (11/19, account.py) |

지키는 것
- 로그인하지 않으면 예전과 똑같다: 가게는 DEMO_STORE_ID(store_ongi), 기록은 쿠키 visitor_id 로 나뉜다.
- 로그인하면 이 서버의 방문자 id 를 'u-<user_id>' 로 바꿔 모든 아래 서비스(Demo·고객응대·맞춤 마케팅)에 똑같이 넘긴다.
  리뷰 분석·맞춤 마케팅의 방문자 규칙(영문·숫자·-·_ 1~64자)과 파일 이름 records_<가게>_<방문자>.json 에 맞게 '_' 를 쓰지 않는다.
- 비밀번호는 hashlib.scrypt (N=2^14, r=8, p=1, 소금 16바이트). 세션 쿠키 값은 저장하지 않고 SHA-256 만 둔다.
- 세션 쿠키 ic26_session: HttpOnly, SameSite=Lax, Secure 는 https(또는 X-Forwarded-Proto: https)일 때만 — 지금 공개 주소가 http 라서.
- 로그인 실패가 몰리면(아이디·주소마다 10분에 10번) 429. 실패 문장은 아이디가 있는지 알려 주지 않는다.
  실서버는 공개 ALB → Nginx → 내부 ALB → WAS 라 WAS 가 보는 주소는 늘 내부 ALB 의 사설 주소다. 그래서 바로 앞이
  사설·루프백 주소면 X-Forwarded-For 를 오른쪽부터 훑어 처음 나오는 공인 주소를 쓰고(_client), 그래도 모르면
  사설 주소 하나로 모두를 막지 않도록 방문자 쿠키와 묶는다. 공인 주소로 바로 붙은 요청의 X-Forwarded-For 는 믿지 않는다.
- 'demo-' 로 시작하는 아이디는 시연 계정 몫이라 회원가입에서 받지 않는다.
- 시연 로그인은 브라우저마다 따로인 시연 사장님을 만든다(방문자 쿠키에서 정함). 심사위원 여럿이 같은 주소를 열어도
  승인 기록·붙여넣은 리뷰가 섞이지 않는다. 같은 브라우저에서 다시 누르면 같은 시연 사장님이다.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from shared import store_profiles
from shared.storage import StorageError, is_valid_visitor_id
from shared.storage.errors import DuplicateLogin

log = logging.getLogger("web.auth")

SESSION_COOKIE = "ic26_session"
SESSION_DAYS = 7
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN = 2 ** 14, 8, 1, 32
DISABLED_PASSWORD = "!"                 # 비밀번호 로그인을 막은 계정 (시연 사장님)
LOGIN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{2,31}")
TOKEN = re.compile(r"[A-Za-z0-9_-]{30,100}")
FAIL_LIMIT, FAIL_WINDOW = 10, 600.0     # 10분에 10번
DEMO_NAME = "시연 사장님"
DEMO_PREFIX = "demo-"                   # 시연 사장님의 user_id·아이디 앞부분. 회원가입에서는 받지 않는다
# 상권 서비스 세션 쿠키 (assistant_proxy·market_proxy 가 쓰는 이름). 로그인·로그아웃·가게 바꾸기 때 지워 새 대화로 시작한다
MARKET_COOKIE = "market_onboarding_session"
MARKET_COOKIE_PATHS = ("/api/assistant", "/api/market")

MESSAGES = {
    "bad_login": "아이디나 비밀번호가 맞지 않아요.",
    "too_many": "로그인 시도가 너무 많아요. 10분 뒤에 다시 해 주세요.",
    "taken": "이미 쓰고 있는 아이디예요. 다른 아이디를 골라 주세요.",
    "login_needed": "로그인한 사장님만 가게를 바꿀 수 있어요.",
    "not_your_store": "가지고 계신 가게만 고를 수 있어요.",
    "demo_off": "시연 로그인이 꺼져 있어요.",
    "reserved": "'demo-'로 시작하는 아이디는 시연 계정용이라 쓸 수 없어요. 다른 아이디를 골라 주세요.",
    "demo_taken": "시연 계정을 준비하지 못했어요. 아이디와 비밀번호로 로그인해 주세요.",
    "down": "지금 로그인 정보를 불러오지 못했어요. 잠시 뒤 다시 해 주세요.",
    "invalid": "요청 모양이 맞지 않아요.",
}
LOGIN_NEEDED_FOR_RECORDS = "로그인한 사장님만 기록을 지울 수 있어요."
RESET_SCOPES = ("store", "account")


class AuthError(Exception):
    def __init__(self, key: str, http: int, message: str | None = None):
        super().__init__(message or MESSAGES.get(key, key))
        self.key, self.http = key, http


# ── 비밀번호 ───────────────────────────────────────────────────────────
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    """저장된 'scrypt$N$r$p$소금$해시' 와 맞는지. 모양이 틀렸거나 막은 계정('!')이면 False."""
    try:
        kind, n, r, p, salt, digest = (stored or "").split("$")
        if kind != "scrypt":
            return False
        want = _unb64(digest)
        # 길이를 고정한다: scrypt 의 마지막 단계(PBKDF2)는 짧게 뽑으면 긴 값의 앞부분이라, 잘린 해시도 맞다고 나올 수 있다
        if len(want) != SCRYPT_DKLEN or (int(n), int(r), int(p)) != (SCRYPT_N, SCRYPT_R, SCRYPT_P):
            return False
        got = hashlib.scrypt(password.encode("utf-8"), salt=_unb64(salt), n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def visitor_for(user_id: str) -> str:
    """로그인한 사장님의 방문자 id. 아래 서비스들의 방문자 규칙(영문·숫자·-·_ 1~64자)에 맞는다."""
    value = f"u-{user_id}"
    if not is_valid_visitor_id(value):
        raise ValueError("user_id 가 방문자 id 규칙에 맞지 않아요")
    return value


# ── 요청마다의 신원 ────────────────────────────────────────────────────
@dataclass(frozen=True)
class Who:
    user: dict | None          # {user_id, login_id, display_name, demo} 또는 None(게스트)
    store_id: str              # 지금 보는 가게
    stores: tuple[str, ...]    # 고를 수 있는 가게
    visitor_id: str            # 아래 서비스에 넘기는 방문자 id (게스트는 쿠키 값, 사장님은 u-<user_id>)
    token_hash: str | None = None
    unavailable: bool = False  # 세션 저장소에 닿지 못해 게스트로 본 경우

    @property
    def authenticated(self) -> bool:
        return self.user is not None


class AuthService:
    def __init__(self, storage, *, default_store: str = store_profiles.DEFAULT_STORE_ID, demo_enabled: bool = True,
                 session_days: int = SESSION_DAYS, clock: Callable[[], float] = time.monotonic):
        self.storage = storage
        self.default_store = default_store
        self.demo_enabled = demo_enabled
        self.session_days = session_days
        self._clock = clock
        self._fails: dict[str, list[float]] = {}
        self._fails_lock = threading.Lock()

    @classmethod
    def from_env(cls, storage, default_store: str) -> "AuthService":
        flag = (os.environ.get("DEMO_ACCOUNT_ENABLED", "1") or "1").strip().lower()
        return cls(storage, default_store=default_store, demo_enabled=flag not in ("0", "false", "no", "off"))

    @property
    def enabled(self) -> bool:
        return getattr(self.storage, "users", None) is not None and getattr(self.storage, "auth_sessions", None) is not None

    # 신원 ---------------------------------------------------------------
    def guest(self, visitor_id: str, unavailable: bool = False) -> Who:
        return Who(None, self.default_store, (self.default_store,), visitor_id, unavailable=unavailable)

    def resolve(self, token: str | None, guest_visitor: str) -> Who:
        """세션 쿠키 → 신원. 쿠키가 없거나 틀렸거나 지났으면 게스트. 저장소에 닿지 못하면 게스트로 보고 unavailable 을 켠다."""
        if not token or not TOKEN.fullmatch(token) or not self.enabled:
            return self.guest(guest_visitor)
        h = token_hash(token)
        try:
            session = self.storage.auth_sessions.get(h)
            if session is None:
                return self.guest(guest_visitor)
            user = self.storage.users.get(session["user_id"])
            stores = tuple(s for s in self.storage.users.stores(session["user_id"]) if store_profiles.known(s))
        except StorageError as exc:
            log.warning("세션을 읽지 못해 게스트로 봄 (%s)", exc.__class__.__name__)
            return self.guest(guest_visitor, unavailable=True)
        if user is None or not stores:
            return self.guest(guest_visitor)
        store = session["active_store_id"] if session["active_store_id"] in stores else stores[0]
        public = {"user_id": user["user_id"], "login_id": user["login_id"], "display_name": user["display_name"],
                  "demo": user["user_id"].startswith(DEMO_PREFIX)}
        return Who(public, store, stores, visitor_for(user["user_id"]), token_hash=h)

    def view(self, who: Who) -> dict:
        """/api/auth/me 와 로그인 응답의 모양."""
        out: dict[str, Any] = {"authenticated": who.authenticated, "user": who.user, "store_id": who.store_id,
                               "stores": store_profiles.public_list(who.stores), "demo_login": self.demo_enabled}
        if who.unavailable:
            out["notice"] = MESSAGES["down"]
        return out

    # 로그인 실패 세기 --------------------------------------------------------
    def _blocked(self, keys: list[str]) -> bool:
        now = self._clock()
        with self._fails_lock:
            for key in keys:
                recent = [t for t in self._fails.get(key, []) if now - t < FAIL_WINDOW]
                self._fails[key] = recent
                if len(recent) >= FAIL_LIMIT:
                    return True
        return False

    def _fail(self, keys: list[str]) -> None:
        now = self._clock()
        with self._fails_lock:
            for key in keys:
                self._fails.setdefault(key, []).append(now)
            if len(self._fails) > 10_000:                     # 기억하는 키가 끝없이 늘지 않게
                self._fails = {k: v for k, v in self._fails.items() if v and now - v[-1] < FAIL_WINDOW}

    # 동작 ----------------------------------------------------------------
    def _new_session(self, user_id: str, store_id: str) -> str:
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(days=self.session_days)
        self.storage.auth_sessions.create(token_hash(token), user_id, store_id, expires)
        return token

    def login(self, login_id: str, password: str, client: str) -> str:
        login = (login_id or "").strip().lower()
        keys = [f"id:{login}", f"ip:{client}"]
        if self._blocked(keys):
            raise AuthError("too_many", 429)
        try:
            user = self.storage.users.by_login(login) if LOGIN_ID.fullmatch(login) else None
            ok = bool(user) and verify_password(password or "", user.get("password_hash"))
            if not ok:
                if user is None:            # 없는 아이디도 같은 시간이 걸리게 (아이디가 있는지 시간으로 알 수 없게)
                    verify_password(password or "", hash_password("x", salt=b"0" * 16))
                self._fail(keys)
                raise AuthError("bad_login", 401)
            stores = [s for s in self.storage.users.stores(user["user_id"]) if store_profiles.known(s)]
            return self._new_session(user["user_id"], stores[0] if stores else self.default_store)
        except StorageError:
            raise AuthError("down", 503) from None

    def signup(self, login_id: str, password: str, display_name: str, stores: list[str] | None) -> str:
        login = (login_id or "").strip().lower()
        if not LOGIN_ID.fullmatch(login):
            raise AuthError("invalid", 422, "아이디는 영문 소문자·숫자로 시작하는 3~32자(. _ - 가능)로 정해 주세요.")
        if login.startswith(DEMO_PREFIX):          # 시연 사장님의 아이디(demo-<12자>)와 겹치지 않게
            raise AuthError("reserved", 422)
        if not (8 <= len(password or "") <= 128):
            raise AuthError("invalid", 422, "비밀번호는 8~128자로 정해 주세요.")
        name = re.sub(r"\s+", " ", display_name or "").strip()
        if not (1 <= len(name) <= 20) or any(ord(c) < 32 for c in name):
            raise AuthError("invalid", 422, "이름은 1~20자로 적어 주세요.")
        picked = [self.default_store] if stores is None else list(dict.fromkeys(stores))   # 안 보내면 기본 가게, 빈 목록은 오류
        if not picked or any(not store_profiles.known(s) for s in picked):
            raise AuthError("invalid", 422, "가게는 온기한식·바삭치킨·몽글카페 중에서 골라 주세요.")
        user_id = secrets.token_hex(8)
        try:
            self.storage.users.create(user_id, login, hash_password(password), name, picked)
            return self._new_session(user_id, picked[0])
        except DuplicateLogin:
            raise AuthError("taken", 409) from None
        except StorageError:
            raise AuthError("down", 503) from None

    def demo_login(self, guest_visitor: str) -> str:
        if not self.demo_enabled:
            raise AuthError("demo_off", 403)
        user_id = DEMO_PREFIX + hashlib.sha256(f"ic26-demo:{guest_visitor}".encode("utf-8")).hexdigest()[:12]
        try:
            self.storage.users.ensure(user_id, user_id, DISABLED_PASSWORD, DEMO_NAME, list(store_profiles.STORE_IDS))
            return self._new_session(user_id, self.default_store)
        except DuplicateLogin:                       # 다른 계정이 이 아이디를 먼저 씀 (예약 전에 가입한 경우). 500 대신
            raise AuthError("demo_taken", 409) from None
        except StorageError:
            raise AuthError("down", 503) from None

    def logout(self, who: Who) -> None:
        if who.token_hash:
            try:
                self.storage.auth_sessions.delete(who.token_hash)
            except StorageError:
                log.warning("세션을 지우지 못했어요 (쿠키는 지움)")

    def switch_store(self, who: Who, store_id: str) -> None:
        if not who.authenticated or not who.token_hash:
            raise AuthError("login_needed", 401)
        if store_id not in who.stores:
            raise AuthError("not_your_store", 403)
        try:
            if not self.storage.auth_sessions.set_store(who.token_hash, store_id):
                raise AuthError("login_needed", 401)
        except StorageError:
            raise AuthError("down", 503) from None


# ── 라우터 ─────────────────────────────────────────────────────────────
class LoginIn(BaseModel):
    login_id: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SignupIn(BaseModel):
    login_id: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=40)
    stores: list[str] | None = Field(default=None, max_length=10)


class StoreIn(BaseModel):
    store_id: str = Field(min_length=1, max_length=40)


def secure_request(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"


# 로드밸런서·Nginx 가 쓰는 내부 주소. 파이썬의 is_private 는 문서용 공인 대역(203.0.113.0/24 등)까지 사설로 보아 직접 정한다
_INTERNAL_NETS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",        # 사설 (NCP VPC 서브넷)
    "100.64.0.0/10",                                        # 통신사·클라우드 공유 대역
    "127.0.0.0/8", "169.254.0.0/16",                        # 루프백·링크 로컬
    "::1/128", "fc00::/7", "fe80::/10"))
_FORWARDED_MAX = 20                                         # X-Forwarded-For 는 오른쪽 20개까지만 본다


def _ip(text: str):
    """주소 글자 → ip_address. IPv4 를 담은 IPv6(::ffff:10.0.0.1)는 IPv4 로. 주소가 아니면 None."""
    try:
        ip = ipaddress.ip_address((text or "").strip())
    except ValueError:
        return None
    return ip.ipv4_mapped if ip.version == 6 and ip.ipv4_mapped else ip


def _internal(ip) -> bool:
    return any(ip.version == net.version and ip in net for net in _INTERNAL_NETS)


def _forwarded_public(values: list[str]) -> str | None:
    """X-Forwarded-For 를 오른쪽(우리 쪽 프록시가 붙인 것)부터 훑어 처음 나오는 공인 주소.
    내부 주소는 건너뛰고, 주소가 아닌 값을 만나면 그 왼쪽은 손님이 지어낸 것일 수 있어 멈춘다."""
    parts = [p.strip() for v in values for p in v.split(",") if p.strip()]
    for part in reversed(parts[-_FORWARDED_MAX:]):
        ip = _ip(part)
        if ip is None:
            return None
        if not _internal(ip):
            return str(ip)
    return None


def _client(request: Request) -> str:
    """로그인 실패를 세는 '주소' 키 (AuthService.login 이 앞에 'ip:' 를 붙인다).

    - 바로 앞이 공인 주소: 그 주소. 손님이 직접 붙었으니 X-Forwarded-For 는 지어낸 것일 수 있어 보지 않는다.
    - 바로 앞이 내부 주소(ALB·Nginx)이거나 주소가 아님(시험·유닉스 소켓): X-Forwarded-For 의 오른쪽 첫 공인 주소.
    - 그래도 모르면 '<내부 주소>:v:<방문자 쿠키>' — 한 사람이 틀렸다고 그 서버의 모든 방문자가 잠기지 않게.
    """
    peer = request.client.host if request.client else ""
    ip = _ip(peer)
    if ip is not None and not _internal(ip):
        return str(ip)
    found = _forwarded_public(request.headers.getlist("x-forwarded-for"))
    if found:
        return found
    visitor = getattr(request.state, "guest_visitor_id", "") or "-"
    return f"{peer or '?'}:v:{visitor}"


def _json(data: Any, status: int = 200) -> JSONResponse:
    out = JSONResponse(data, status_code=status)
    out.headers["Cache-Control"] = "no-store"
    return out


def _reset_market(out: JSONResponse, secure: bool) -> None:
    """상권 서비스의 대화·분석 조건 세션을 지운다 (다른 사장님·다른 가게의 대화가 이어지지 않게)."""
    for path in MARKET_COOKIE_PATHS:
        out.delete_cookie(MARKET_COOKIE, path=path, secure=secure, httponly=True, samesite="lax")


async def _json_body(request: Request) -> dict | None:
    """본문 JSON 객체. 비었거나 JSON 객체가 아니면 None (pydantic 기본 422 대신 auth 오류 모양으로 답하려고 직접 읽는다)."""
    raw = await request.body()
    if len(raw) > 4096:
        return None
    try:
        data = json.loads(raw or b"null")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def create_auth_router(auth: AuthService, who_of: Callable[[Request], Who],
                       erase: Callable[[list[str], str], dict] | None = None) -> APIRouter:
    """erase(가게 목록, 방문자) → {complete, message, stores}: 사장님 기록 지우기 (account.AccountData.clear, 11/19).
    안 주면 초기화·탈퇴는 503."""
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    def signed_in(request: Request, token: str) -> JSONResponse:
        who = auth.resolve(token, getattr(request.state, "guest_visitor_id", "") or "")
        secure = secure_request(request)
        out = _json(auth.view(who))
        out.set_cookie(SESSION_COOKIE, token, max_age=auth.session_days * 86400, path="/", httponly=True,
                       samesite="lax", secure=secure)
        _reset_market(out, secure)
        return out

    def failed(exc: AuthError) -> JSONResponse:
        return _json({"error": {"message": str(exc), "state": exc.key}}, exc.http)

    @router.get("/me")
    def me(request: Request):
        return _json(auth.view(who_of(request)))

    @router.post("/login")
    def login(body: LoginIn, request: Request):
        try:
            return signed_in(request, auth.login(body.login_id, body.password, _client(request)))
        except AuthError as exc:
            return failed(exc)

    @router.post("/signup", status_code=201)
    def signup(body: SignupIn, request: Request):
        try:
            out = signed_in(request, auth.signup(body.login_id, body.password, body.display_name, body.stores))
            out.status_code = 201
            return out
        except AuthError as exc:
            return failed(exc)

    @router.post("/demo-login")
    def demo_login(request: Request):
        try:
            return signed_in(request, auth.demo_login(getattr(request.state, "guest_visitor_id", "") or "anon"))
        except AuthError as exc:
            return failed(exc)

    @router.post("/logout")
    def logout(request: Request):
        who = who_of(request)
        auth.logout(who)
        secure = secure_request(request)
        out = _json(auth.view(auth.guest(getattr(request.state, "guest_visitor_id", "") or "")))
        out.delete_cookie(SESSION_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
        _reset_market(out, secure)
        return out

    @router.post("/store")
    def switch(body: StoreIn, request: Request):
        who = who_of(request)
        try:
            auth.switch_store(who, body.store_id)
        except AuthError as exc:
            return failed(exc)
        secure = secure_request(request)
        token = request.cookies.get(SESSION_COOKIE) or ""
        out = _json(auth.view(auth.resolve(token, who.visitor_id)))
        _reset_market(out, secure)
        return out

    @router.post("/reset")
    async def reset(request: Request):
        """계정 초기화 (11/19). 본문 {"scope": "store" | "account"}. store = 지금 보는 가게 하나, account = 가진 가게 모두.
        계정·가게 목록·세션은 남긴다. 못 지운 것이 있어도 200 (complete=false, message). 상권 세션 쿠키 두 개를 만료시킨다
        (상권 대화 자체는 화면이 먼저 DELETE /api/assistant/conversation 으로 지운다)."""
        who = who_of(request)
        if not who.authenticated:
            return failed(AuthError("login_needed", 401, LOGIN_NEEDED_FOR_RECORDS))
        body = await _json_body(request)
        scope = body.get("scope") if body else None
        if scope not in RESET_SCOPES:
            return failed(AuthError("invalid", 422, "scope 는 store(지금 가게) 또는 account(가진 가게 모두)로 보내 주세요."))
        if erase is None:
            return failed(AuthError("down", 503))
        stores = [who.store_id] if scope == "store" else list(who.stores)
        result = await run_in_threadpool(erase, stores, who.visitor_id)
        out = _json({"scope": scope, "complete": result["complete"], "message": result["message"], "stores": result["stores"]})
        _reset_market(out, secure_request(request))
        return out

    return router
