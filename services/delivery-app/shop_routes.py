"""시연용 가상 배달앱 '동네배달': 화면 파일과, 화면이 부르는 /api/shop/* 주소.

가상 배달앱은 사장님 대시보드와 다른 화면(/shop/)이다. 손님이 리뷰를 쓰면 리뷰 분석 서비스
(services/review-insight, 127.0.0.1:8020)에 source="app" 으로 저장되고, 사장님이 단 답글을 다시 받아 리뷰 아래에 보여 준다.
브라우저는 리뷰 분석 서비스에 직접 가지 않는다. 이 파일의 주소가 대신 부르고 토큰을 붙인다.
리뷰 분석 서비스·통합 화면 서버·shared 의 코드는 import 하지 않는다 (fastapi·httpx 만 씀).

| 브라우저가 부르는 주소      | 하는 일                                                                  |
|-----------------------------|--------------------------------------------------------------------------|
| GET  /shop/                 | 배달앱 화면 (static/index.html, style.css, app.js)                        |
| GET  /api/shop/status       | 리뷰 분석 서비스 상태. 항상 200 (ready·down·off)                           |
| GET  /api/shop/store        | 가게 이름·영업시간·메뉴 (서비스의 가게 정보에서 손님에게 보여 줄 칸만)       |
| GET  /api/shop/reviews      | 리뷰와 사장님 답글 (손님에게 보여 줄 칸만: 글·별점·주문 메뉴·시각·답글)     |
| POST /api/shop/reviews      | 리뷰 등록 → 서비스 POST /reviews {source: "app", menu}                    |

어느 가게인가:
  /shop/ 은 시연 가게(DEMO_STORE_ID), /shop/?store=store_<가게> 는 그 가게. 화면이 ?store= 값을 API 에 그대로 붙인다.
  배달앱의 가게·메뉴·리뷰는 손님에게 공개되는 정보라 로그인 없이 가게를 고를 수 있다 (사장님 화면은 로그인한 가게만 — care_proxy).
  없는 가게나 형식이 틀린 값은 404.

리뷰가 어디에 쌓이나:
  서비스는 source="app" 리뷰를 가게 공용 칸에 쌓고, 모든 사장님 화면(방문자)의 리뷰 목록·분석에 합쳐 보여 준다.
  그래서 배달앱은 방문자를 보내지 않는다. 누가 어느 기기에서 쓰든 같은 가게 리뷰로 쌓이고, 답글도 모두에게 같이 보인다.
  배달앱 리뷰 탭에는 합성 리뷰(원래 있던 리뷰)와 배달앱에서 쓴 리뷰만 보인다 (사장님이 붙여넣은 리뷰는 안 보임).

환경 변수 (통합 화면 서버의 care_proxy 와 같은 이름):
  REVIEW_INSIGHT_URL    기본 http://127.0.0.1:8020. "off" 면 배달앱이 리뷰를 보내지 않음
  REVIEW_INSIGHT_TOKEN  서비스의 APP_ACCESS_TOKEN 과 같은 값 (비우면 안 붙임)
  DEMO_STORE_ID         ?store= 를 안 준 /shop/ 이 보여 줄 가게 (기본 store_ongi)
  SHOP_TIMEOUT_SEC      기다리는 최대 시간. 기본 40 (등록 때 서비스가 리뷰를 다시 분류함)

붙이는 법 (services/web/web/main.py, 통합 담당):
    from web.shop_routes import create_shop_router          # 이 파일을 web/shop_routes.py 로 복사, static/ 은 web/shop_static/ 으로
    app.include_router(create_shop_router(static_dir=Path(__file__).parent / "shop_static"))
"""
from __future__ import annotations

import os
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Callable

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

SERVICE_PREFIX = "/api/review-insight"
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {"index.html": "text/html; charset=utf-8", "style.css": "text/css; charset=utf-8",
                "app.js": "application/javascript; charset=utf-8"}
MAX_JSON = 16 * 1024
TEXT_MAX = 1000                                  # 서비스의 리뷰 글 상한과 같음
REVIEWS_SHOWN = 30                               # 배달앱 리뷰 탭에 보여 줄 최대 건수
POSTS_PER_MINUTE = 10                            # 손님(접속 주소)당. 등록마다 서비스가 분류를 다시 하므로 막아 둠
MENU_MAX = 40                                    # 서비스의 주문 메뉴 상한과 같음
STORE_ID = re.compile(r"store_[a-z0-9_]{1,40}")   # 서비스의 가게 ID 규칙과 같음
SOURCES_SHOWN = ("sample", "app")                # 원래 있던 리뷰(합성)와 배달앱에서 쓴 리뷰만 손님에게 보임
NOTICE = "시연용 가상 배달앱 · 실제 배달앱과 연결되지 않음"

MESSAGES = {"off": "이 서버에서는 가상 배달앱의 리뷰 기능을 켜 두지 않았어요.",
            "down": "리뷰 서버에 연결하지 못했어요. 잠시 뒤 다시 해 주세요.",
            "slow": "리뷰 서버가 답하는 데 너무 오래 걸렸어요. 잠시 뒤 다시 해 주세요.",
            "too_big": "보내는 내용이 너무 커요.", "invalid": "보낸 내용을 확인해 주세요.",
            "rate_limited": "리뷰를 너무 자주 등록했어요. 1분 뒤에 다시 해 주세요.",
            "no_store": "없는 가게예요. 주소를 다시 확인해 주세요.",
            "failed": "리뷰 서버가 요청을 처리하지 못했어요."}


def _fail(state: str, http: int = 503, message: str | None = None) -> JSONResponse:
    return JSONResponse({"error": {"message": message or MESSAGES.get(state, MESSAGES["failed"]), "state": state}}, status_code=http)


def create_shop_router(*, base_url: str | None = None, token: str | None = None, store_id: str | None = None,
                       timeout: float | None = None, client: httpx.Client | None = None,
                       static_dir: Path | None = None,
                       clock: Callable[[], float] = time.monotonic) -> APIRouter:
    env = os.environ.get
    base = (base_url if base_url is not None else env("REVIEW_INSIGHT_URL", "http://127.0.0.1:8020")).strip().rstrip("/")
    token = (token if token is not None else env("REVIEW_INSIGHT_TOKEN", "")).strip()
    default_store = (store_id or env("DEMO_STORE_ID", "store_ongi")).strip()
    wait = float(timeout if timeout is not None else (env("SHOP_TIMEOUT_SEC", "") or 40))
    off = base.lower() == "off"
    http = client or (None if off else httpx.Client(base_url=base, timeout=wait))
    static = Path(static_dir) if static_dir else STATIC_DIR
    recent: dict[str, deque] = defaultdict(deque)
    router = APIRouter(tags=["delivery-app"])

    def store_of(request: Request) -> str | None:
        """이 요청의 가게. ?store= 가 없으면 시연 가게, 형식이 틀리면 None (→ 404)."""
        wanted = request.query_params.get("store")
        if wanted is None or wanted == "":
            return default_store
        return wanted if STORE_ID.fullmatch(wanted) else None

    # ── 리뷰 분석 서비스 부르기 ─────────────────────────────────────────────────────
    def call(method: str, path: str, *, params: dict | None = None, json: dict | None = None):
        """(본문 dict, None) 또는 (None, 실패 응답)."""
        if off:
            return None, _fail("off")
        headers = {"X-Access-Token": token} if token else {}
        try:
            r = http.request(method, SERVICE_PREFIX + path, params=params, json=json, headers=headers, timeout=wait)
        except httpx.TimeoutException:
            return None, _fail("slow")
        except httpx.HTTPError:
            return None, _fail("down")
        try:
            data = r.json()
        except ValueError:
            return None, _fail("failed", 502)
        if r.status_code >= 400:
            # 서비스의 오류 글 가운데 손님에게 보여 줘도 되는 것(입력 확인)만 그대로 전한다
            err = data.get("error", {}) if isinstance(data, dict) else {}
            if r.status_code == 400 and err.get("code") == "VALIDATION_ERROR":
                return None, _fail("invalid", 400, str(err.get("message") or MESSAGES["invalid"]))
            if r.status_code == 404 and err.get("code") == "STORE_NOT_FOUND":
                return None, _fail("no_store", 404)
            return None, _fail("failed", 502 if r.status_code >= 500 else r.status_code)
        return data, None

    def shown(row: dict) -> dict:
        """손님 화면에 내보내는 칸만. 분류 결과·상태·방문자 같은 사장님용 칸은 넘기지 않는다."""
        reply = row.get("reply") or None
        return {"id": row.get("review_id"), "text": row.get("text") or "", "rating": row.get("rating"),
                "at": row.get("received_at") or row.get("created_at"),     # 배달앱에서 쓴 리뷰는 실제로 받은 시각
                "from_app": row.get("source") == "app", "menu": row.get("menu") or None,
                "reply": {"text": reply.get("text"), "at": reply.get("replied_at")} if isinstance(reply, dict) and reply.get("text") else None}

    # ── 화면 파일 ──────────────────────────────────────────────────────────────────
    @router.get("/shop", include_in_schema=False)
    def shop_redirect():
        return RedirectResponse("/shop/")

    @router.get("/shop/", include_in_schema=False)
    def shop_page():
        return FileResponse(static / "index.html", media_type=STATIC_FILES["index.html"], headers={"Cache-Control": "no-cache"})

    @router.get("/shop/{name}", include_in_schema=False)
    def shop_file(name: str):
        if name not in STATIC_FILES or not (static / name).is_file():
            return _fail("not_found", 404, "없는 주소예요.")
        return FileResponse(static / name, media_type=STATIC_FILES[name], headers={"Cache-Control": "no-cache"})

    # ── API ───────────────────────────────────────────────────────────────────────
    @router.get("/api/shop/status")
    def status(request: Request):
        store = store_of(request)
        if store is None:
            return _fail("no_store", 404)
        out = {"notice": NOTICE, "store_id": store}
        if off:
            return out | {"state": "off", "message": MESSAGES["off"]}
        try:
            h = http.get("/api/health", timeout=5).json()
        except (httpx.HTTPError, ValueError):
            return out | {"state": "down", "message": MESSAGES["down"]}
        return out | {"state": "ready", "message": None, "mode": h.get("mode"), "data_origin": h.get("data_origin")}

    @router.get("/api/shop/store")
    def store_info(request: Request):
        store = store_of(request)
        if store is None:
            return _fail("no_store", 404)
        data, failed = call("GET", "/profile", params={"store_id": store})
        if failed:
            return failed
        info, _ = call("GET", f"/public/{store}/info")
        basic, order, today = data.get("basic") or {}, data.get("order") or {}, data.get("today") or {}
        sold_out = set(today.get("sold_out") or [])
        menu = [{"name": m.get("name"), "price": m.get("price"), "spicy": m.get("spicy"), "ingredients": m.get("ingredients") or [],
                 "allergens": m.get("allergens") or [], "recommended": bool(m.get("recommended")),
                 "sold_out": bool(m.get("sold_out")) or m.get("name") in sold_out}
                for m in data.get("menu") or [] if m.get("name") and isinstance(m.get("price"), int)]
        return {"store_id": store, "name": (info or {}).get("name") or store, "business_type": (info or {}).get("business_type_name"),
                "today": {"date": today.get("date"), "day": today.get("day"), "hours": today.get("hours")},
                "hours": basic.get("hours") or {}, "break_time": basic.get("break_time"), "last_order": basic.get("last_order"),
                "holidays": basic.get("holidays"), "address": basic.get("address"),
                "min_order": order.get("min_order"), "delivery_area": order.get("delivery_area"), "takeout": order.get("takeout"),
                "notices": [n.get("text") for n in data.get("active_notices") or [] if n.get("text")],
                "menu": menu, "data_origin": data.get("data_origin"), "notice": NOTICE}

    @router.get("/api/shop/reviews")
    def reviews(request: Request):
        store = store_of(request)
        if store is None:
            return _fail("no_store", 404)
        data, failed = call("GET", "/reviews", params={"store_id": store})      # 방문자 없이 = 가게 공용 (합성 + 배달앱 리뷰)
        if failed:
            return failed
        rows = [shown(r) for r in data.get("items") or [] if r.get("source") in SOURCES_SHOWN]
        rated = [r["rating"] for r in rows if isinstance(r["rating"], int)]
        # 배달앱에서 쓴 리뷰를 위에, 그다음은 최근 순. 합성 리뷰의 시각은 발표 장면 시각이라 서로만 비교한다.
        rows.sort(key=lambda r: (r["from_app"], r["at"] or ""), reverse=True)
        return {"items": rows[:REVIEWS_SHOWN], "count": len(rows),
                "average": round(sum(rated) / len(rated), 1) if rated else None,
                "by_rating": {str(n): rated.count(n) for n in (5, 4, 3, 2, 1)}}

    @router.post("/api/shop/reviews", status_code=201)
    async def add_review(request: Request):
        store = store_of(request)
        if store is None:
            return _fail("no_store", 404)
        raw = await request.body()
        if len(raw) > MAX_JSON:
            return _fail("too_big", 413)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return _fail("invalid", 422, "본문이 JSON 이 아니에요.")
        text, rating = body.get("text"), body.get("rating")
        if not isinstance(text, str) or not (1 <= len(text.strip()) <= TEXT_MAX):
            return _fail("invalid", 400, f"리뷰 글은 1~{TEXT_MAX}자로 적어 주세요.")
        if isinstance(rating, bool) or not isinstance(rating, int) or not (1 <= rating <= 5):
            return _fail("invalid", 400, "별점은 1~5점 가운데 골라 주세요.")
        menu = body.get("menu")
        if menu is not None and (not isinstance(menu, str) or len(menu.strip()) > MENU_MAX):
            return _fail("invalid", 400, "주문 메뉴를 다시 골라 주세요.")
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")
        now, mine = clock(), recent[ip]
        while mine and now - mine[0] > 60:
            mine.popleft()
        if len(mine) >= POSTS_PER_MINUTE:
            return _fail("rate_limited", 429)
        mine.append(now)
        sent = {"store_id": store, "text": text.strip(), "rating": rating, "source": "app"}
        if menu and menu.strip():
            sent["menu"] = menu.strip()
        data, failed = call("POST", "/reviews", json=sent)
        if failed:
            return failed
        return {"review": shown(data.get("review") or {})}

    return router
