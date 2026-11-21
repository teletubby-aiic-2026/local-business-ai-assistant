"""계정 안의 가게와 사장님 프로필 (6차 회의 11/20: 로그인 → 가게 선택 → 메인 서비스).

| 메서드 | 경로                                        | 하는 일 |
|--------|---------------------------------------------|---------|
| GET    | /api/account/stores                         | 내 가게 목록 (순서대로, 메뉴 수·지금 보는 가게) |
| GET    | /api/account/stores/{store_id}/summary      | 가게 고르기 카드의 한 줄 (리뷰·불만 수, 반복 불만). 새 모델 호출 없음 |
| POST   | /api/account/stores                         | 새 가게 등록 → 목록 맨 뒤 (세션의 지금 가게는 그대로) |
| GET    | /api/account/stores/{store_id}              | 직접 등록한 내 가게의 전체 칸 |
| PATCH  | /api/account/stores/{store_id}              | 직접 등록한 내 가게 고치기 (보낸 칸만) |
| DELETE | /api/account/stores/{store_id}              | 내 목록에서 빼기 (가게의 기록은 지우지 않음) |
| PUT    | /api/account/stores/order                   | 내 가게 전부를 새 순서로 |
| PATCH  | /api/account/profile                        | 이름 바꾸기 → /api/auth/me 와 같은 모양 |
| POST   | /api/account/password                       | 비밀번호 바꾸기 |

전부 로그인이 필요하다 (아니면 401 login_needed). 오류 모양은 /api/auth/* 와 같다: {"error": {"message", "state"}}.
예시 가게 세 곳(store_ongi·store_basak·store_mongle)은 고칠 수 없다 (403 sample_store). 남의 가게·없는 가게는 403 not_your_store.
등록한 가게는 stores 표(data_origin 'registered')에 두고 shared.store_profiles 가 예시 세 곳 다음으로 찾는다.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from shared import store_profiles
from shared.storage import StorageError
from shared.storage.errors import DuplicateStore, StoreLimit

from .auth import AuthError, AuthService, Who, _client, _json

log = logging.getLogger("web.account_api")

MAX_STORES = 10                 # 한 계정의 가게 목록 (예시 가게 포함)
MAX_BODY = 16 * 1024
MAX_CHANNELS, MAX_MENUS, MAX_PRICE = 6, 30, 1_000_000
STATUSES = ("operating", "planning", "exploring")
KINDS = ("address", "station")
INDUSTRY = re.compile(r"[A-Za-z0-9]{1,20}")
AREA_CODE = re.compile(r"[0-9]{7}")
PERIOD = re.compile(r"[0-9]{4}[1-4]")
STATION_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}")

MESSAGES = {
    "login_needed": "로그인한 사장님만 쓸 수 있어요.",
    "not_your_store": "가지고 계신 가게만 볼 수 있어요.",
    "sample_store": "예시 가게는 고칠 수 없어요.",
    "store_limit": f"가게는 한 계정에 {MAX_STORES}곳까지 등록할 수 있어요.",
}
REVIEWS_EMPTY = "리뷰를 넣으면 분석을 시작해요"
NO_REPEAT = "반복된 불만이 없어요"


class Invalid(AuthError):
    def __init__(self, message: str):
        super().__init__("invalid", 422, message)


# ── 입력 검사 ──────────────────────────────────────────────────────────
def _text(value: Any, label: str, low: int, high: int, *, optional: bool = False) -> str | None:
    """앞뒤 공백을 정리한 글자. 제어 문자는 거절. optional 이면 None·빈 글자는 None."""
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise Invalid(f"{label}을(를) 글자로 보내 주세요.")
    text = value.strip()
    if optional and not text:
        return None
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise Invalid(f"{label}에 쓸 수 없는 글자가 있어요.")
    if not (low <= len(text) <= high):
        raise Invalid(f"{label}은(는) {low}~{high}자로 적어 주세요.")
    return text


def _number(value: Any, label: str, low: float, high: float) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or not (low <= value <= high):
        raise Invalid(f"{label} 값이 맞지 않아요.")
    return float(value)


def _location(value: Any) -> dict:
    if not isinstance(value, dict):
        raise Invalid("위치(location)를 객체로 보내 주세요.")
    kind = value.get("kind")
    if kind not in KINDS:
        raise Invalid("위치 종류(kind)는 address 또는 station 이에요.")
    out = {"kind": kind, "label": _text(value.get("label"), "위치 이름", 1, 120),
           "road_address": _text(value.get("road_address"), "도로명 주소", 1, 200, optional=True),
           "latitude": _number(value.get("latitude"), "위도", -90, 90),
           "longitude": _number(value.get("longitude"), "경도", -180, 180),
           "station_id": _text(value.get("station_id"), "역 id", 1, 80, optional=True),
           "station_name": _text(value.get("station_name"), "역 이름", 1, 40, optional=True),
           "district_name": _text(value.get("district_name"), "자치구", 1, 20, optional=True)}
    if out["station_id"] is not None and not STATION_ID.fullmatch(out["station_id"]):
        raise Invalid("역 id 모양이 맞지 않아요.")
    return out


def _area(value: Any) -> dict:
    if not isinstance(value, dict):
        raise Invalid("상권(area)을 객체로 보내 주세요.")
    code = value.get("area_code")
    if not (isinstance(code, str) and AREA_CODE.fullmatch(code)):
        raise Invalid("상권 코드(area_code)는 숫자 7자리예요.")
    period = value.get("period")
    if period is not None and not (isinstance(period, str) and PERIOD.fullmatch(period)):
        raise Invalid("분기(period)는 '20262'처럼 연도 4자리와 분기 1자리예요.")
    return {"area_code": code, "name": _text(value.get("name"), "상권 이름", 1, 60), "period": period}


def _channels(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_CHANNELS:
        raise Invalid(f"배달 채널(channels)은 {MAX_CHANNELS}개까지의 목록이에요.")
    return list(dict.fromkeys(_text(v, "배달 채널", 1, 30) for v in value))


def _menus(value: Any) -> list[dict]:
    if not isinstance(value, list) or len(value) > MAX_MENUS:
        raise Invalid(f"메뉴(menus)는 {MAX_MENUS}개까지의 목록이에요.")
    found: dict[str, int] = {}
    for item in value:
        if not isinstance(item, dict):
            raise Invalid("메뉴는 {name, price} 모양으로 보내 주세요.")
        name = _text(item.get("name"), "메뉴 이름", 1, 30)
        price = item.get("price")
        if isinstance(price, bool) or not isinstance(price, int) or not (0 <= price <= MAX_PRICE):
            raise Invalid(f"메뉴 가격은 0~{MAX_PRICE:,}원 사이의 정수예요.")
        found.pop(name, None)            # 같은 이름은 뒤엣것으로 (자리도 뒤로)
        found[name] = price
    return [{"name": k, "price": v} for k, v in found.items()]


FIELDS: dict[str, Callable[[Any], Any]] = {
    "name": lambda v: _text(v, "가게 이름", 1, 30),
    "industry_code": lambda v: _industry(v),
    "business_type_name": lambda v: _text(v, "업종 이름", 1, 30),
    "business_status": lambda v: _status(v),
    "channels": _channels,
    "location": _location,
    "area": _area,
    "menus": _menus,
}
REQUIRED = ("name", "industry_code", "business_type_name", "business_status", "location", "area")
DEFAULTS = {"channels": [], "menus": []}


def _industry(value: Any) -> str:
    if not (isinstance(value, str) and INDUSTRY.fullmatch(value.strip())):
        raise Invalid("업종 코드(industry_code)는 영문·숫자 1~20자예요.")
    return value.strip()


def _status(value: Any) -> str:
    if value not in STATUSES:
        raise Invalid("영업 상태(business_status)는 operating·planning·exploring 중 하나예요.")
    return value


def clean_store(body: dict | None, *, partial: bool) -> dict:
    """등록(전부 필요)·고치기(보낸 칸만) 본문 → 검사·정리한 칸. 모르는 칸은 버린다."""
    if not isinstance(body, dict):
        raise Invalid("요청 모양이 맞지 않아요.")
    out = {}
    for key, check in FIELDS.items():
        if key in body:
            out[key] = check(body[key])
        elif not partial:
            if key in REQUIRED:
                raise Invalid(f"{key} 칸이 필요해요.")
            out[key] = list(DEFAULTS[key])
    return out


def split_row(fields: dict) -> tuple[str | None, str | None, dict]:
    """검사한 칸 → (name, business_type_name, profile 칸들)."""
    profile = {k: v for k, v in fields.items() if k not in ("name", "business_type_name")}
    return fields.get("name"), fields.get("business_type_name"), profile


# ── 응답 모양 ──────────────────────────────────────────────────────────
def store_item(bundle: store_profiles.StoreBundle, who: Who) -> dict:
    """목록 한 줄: {store_id, name, business_type_name, area_name, station_name, sample, menu_count, last_opened}."""
    return {**bundle.public(), "menu_count": len(bundle.menu_prices), "last_opened": bundle.store_id == who.store_id}


def store_detail(row: dict, who: Who) -> dict:
    """등록한 가게 한 곳의 전체 칸 (목록 칸 + 등록 때 받은 칸)."""
    bundle = store_profiles.registered_bundle(row)
    profile = row.get("profile") or {}
    return {**store_item(bundle, who), "industry_code": profile.get("industry_code"),
            "business_status": profile.get("business_status"), "channels": list(profile.get("channels") or []),
            "location": profile.get("location"), "area": profile.get("area"), "menus": list(profile.get("menus") or []),
            "created_at": row.get("created_at"), "updated_at": row.get("updated_at")}


def summarize(insight: dict) -> dict:
    """리뷰 분석 insight (홈 브리핑과 같은 값) → 가게 고르기 카드의 한 줄."""
    reviews, complaints = insight.get("review_count"), insight.get("complaint_count")
    if not reviews:
        return {"state": "empty", "reviews": reviews or 0, "complaints": complaints or 0,
                "headline": REVIEWS_EMPTY, "tone": "muted"}
    groups = [g for g in insight.get("groups") or [] if isinstance(g, dict) and g.get("is_repeated")]
    top = next((g for g in groups if g.get("issue_id") == insight.get("top_issue_id")), None)
    top = top or max(groups, key=lambda g: g.get("review_count") or 0, default=None)
    if top:
        return {"state": "ready", "reviews": reviews, "complaints": complaints,
                "headline": f"{top.get('topic_name') or '같은 불만'} {top.get('review_count') or 0}건 반복", "tone": "bad"}
    return {"state": "ready", "reviews": reviews, "complaints": complaints, "headline": NO_REPEAT, "tone": "good"}


UNAVAILABLE = {"state": "unavailable", "reviews": None, "complaints": None, "headline": "분석을 불러오지 못했어요",
               "tone": "muted"}


# ── 라우터 ─────────────────────────────────────────────────────────────
async def _body(request: Request) -> dict | None:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise Invalid("요청 내용이 너무 커요.")
    try:
        data = json.loads(raw or b"null")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def create_account_router(auth: AuthService, hub, who_of: Callable[[Request], Who]) -> APIRouter:
    """hub: stores.StoreHub (summary 가 가게의 Demo 를 고른다)."""
    router = APIRouter(prefix="/api/account", tags=["account"])

    def failed(exc: AuthError) -> JSONResponse:
        return _json({"error": {"message": str(exc), "state": exc.key}}, exc.http)

    def signed(request: Request) -> Who:
        who = who_of(request)
        if not who.authenticated:
            raise AuthError("login_needed", 401, MESSAGES["login_needed"])
        return who

    def repo():
        found = auth.registered
        if found is None:
            raise AuthError("down", 503)
        return found

    def fresh(request: Request) -> Who:
        """바뀐 뒤의 신원 (가게 목록·지금 가게를 저장소에서 다시 읽음)."""
        from .auth import SESSION_COOKIE
        return auth.resolve(request.cookies.get(SESSION_COOKIE), getattr(request.state, "guest_visitor_id", "") or "")

    def listing(who: Who) -> list[dict]:
        return [store_item(b, who) for b in (store_profiles.get(s) for s in who.stores) if b is not None]

    def own_registered(who: Who, store_id: str) -> dict:
        """직접 등록한 내 가게의 줄. 예시 가게면 403 sample_store, 남의 가게·없는 가게면 403 not_your_store."""
        if store_id in store_profiles.BUNDLES:
            raise AuthError("sample_store", 403, MESSAGES["sample_store"])
        row = repo().get(store_id) if store_profiles.is_registered_id(store_id) else None
        if row is None or row.get("owner_user_id") != who.user["user_id"]:
            raise AuthError("not_your_store", 403, MESSAGES["not_your_store"])
        return row

    def guarded(work: Callable[[], Any]) -> JSONResponse:
        try:
            result = work()
        except AuthError as exc:
            return failed(exc)
        except StorageError:
            return failed(AuthError("down", 503))
        return result if isinstance(result, JSONResponse) else _json(result)

    # 가게 목록 ------------------------------------------------------------
    @router.get("/stores")
    def stores(request: Request):
        return guarded(lambda: {"stores": listing(signed(request))})

    @router.post("/stores", status_code=201)
    async def create(request: Request):
        try:
            who = signed(request)
            fields = clean_store(await _body(request), partial=False)
        except AuthError as exc:
            return failed(exc)

        def work():
            name, type_name, profile = split_row(fields)
            for _ in range(5):                  # id 가 겹치면 (거의 없음) 새로 만든다
                store_id = "store_" + secrets.token_hex(6)
                try:
                    row = repo().create(store_id, who.user["user_id"], name, type_name, profile, limit=MAX_STORES)
                    break
                except DuplicateStore:
                    continue
                except StoreLimit:
                    raise AuthError("store_limit", 422, MESSAGES["store_limit"]) from None
                except KeyError:
                    raise AuthError("login_needed", 401, MESSAGES["login_needed"]) from None
            else:
                raise AuthError("down", 503)
            store_profiles.remember(row)
            return _json({"store": store_detail(row, who)}, 201)
        return await run_in_threadpool(guarded, work)

    @router.put("/stores/order")
    async def reorder(request: Request):
        try:
            who = signed(request)
            body = await _body(request)
        except AuthError as exc:
            return failed(exc)
        ids = body.get("store_ids") if body else None
        if not (isinstance(ids, list) and all(isinstance(s, str) for s in ids)):
            return failed(Invalid("store_ids 를 가게 id 목록으로 보내 주세요."))

        def work():
            if len(set(ids)) != len(ids) or set(ids) != set(who.stores) \
                    or not auth.storage.users.reorder(who.user["user_id"], ids):
                raise Invalid("내 가게 전부를 한 번씩 보내 주세요.")
            return {"stores": listing(fresh(request))}
        return await run_in_threadpool(guarded, work)

    @router.get("/stores/{store_id}/summary")
    def summary(store_id: str, request: Request):
        def work():
            who = signed(request)
            if store_id not in who.stores:
                raise AuthError("not_your_store", 403, MESSAGES["not_your_store"])
            bundle = store_profiles.get(store_id)
            try:
                insight = hub.demo(store_id).insight(who.visitor_id)
            except Exception as exc:          # DemoError(리뷰 분석 서비스에 닿지 못함·모르는 가게) 등. 200 으로 알린다
                # 리뷰 분석 서비스는 아직 등록한 가게를 모른다 (404). 등록 가게는 리뷰를 넣을 곳이 없으니 '리뷰 없음'으로 본다
                if bundle is not None and bundle.registered and "오류 404" in str(exc):
                    return summarize({})
                log.warning("가게 요약을 불러오지 못했어요 (%s)", exc.__class__.__name__)
                return dict(UNAVAILABLE)
            return summarize(insight)
        return guarded(work)

    @router.get("/stores/{store_id}")
    def detail(store_id: str, request: Request):
        def work():
            who = signed(request)
            return {"store": store_detail(own_registered(who, store_id), who)}
        return guarded(work)

    @router.patch("/stores/{store_id}")
    async def update(store_id: str, request: Request):
        try:
            who = signed(request)
            body = await _body(request)
        except AuthError as exc:
            return failed(exc)

        def work():
            own_registered(who, store_id)
            fields = clean_store(body, partial=True)
            name, type_name, changes = split_row(fields)
            row = repo().get(store_id)
            profile = {**(row.get("profile") or {}), **changes} if changes else None
            row = repo().update(store_id, name=name, business_type_name=type_name, profile=profile)
            if row is None:
                raise AuthError("not_your_store", 403, MESSAGES["not_your_store"])
            store_profiles.remember(row)
            return {"store": store_detail(row, who)}
        return await run_in_threadpool(guarded, work)

    @router.delete("/stores/{store_id}")
    def remove(store_id: str, request: Request):
        def work():
            who = signed(request)
            if store_id not in who.stores:
                raise AuthError("not_your_store", 403, MESSAGES["not_your_store"])
            auth.storage.users.remove_store(who.user["user_id"], store_id)
            after = fresh(request)
            # 지금 보던 가게를 뺐으면 남은 첫 가게로 (없으면 빈 값 → 가게 없음). resolve 가 이미 그렇게 보지만 세션에도 적어 둔다
            if who.store_id == store_id and who.token_hash:
                auth.storage.auth_sessions.set_store(who.token_hash, after.store_id or "")
            return {"stores": listing(after), "store_id": after.store_id}
        return guarded(work)

    # 사장님 프로필 ----------------------------------------------------------
    @router.patch("/profile")
    async def profile(request: Request):
        try:
            who = signed(request)
            body = await _body(request)
            if body is None or "display_name" not in body:
                raise Invalid("display_name 을 보내 주세요.")
        except AuthError as exc:
            return failed(exc)

        def work():
            auth.rename(who, body["display_name"])
            return auth.view(fresh(request))
        return await run_in_threadpool(guarded, work)

    @router.post("/password")
    async def password(request: Request):
        try:
            who = signed(request)
            body = await _body(request)
            current, new = (body or {}).get("current_password"), (body or {}).get("new_password")
            if not isinstance(current, str) or not isinstance(new, str) or len(current) > 256:
                raise Invalid("current_password 와 new_password 를 글자로 보내 주세요.")
        except AuthError as exc:
            return failed(exc)

        def work():
            auth.change_password(who, current, new, _client(request))
            return {"ok": True}
        return await run_in_threadpool(guarded, work)

    return router
