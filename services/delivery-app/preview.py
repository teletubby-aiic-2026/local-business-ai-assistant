"""한 번에 띄워 화면을 확인하는 실행 파일 (내 컴퓨터용. 팀 서버에서는 쓰지 않음).

    cd services/delivery-app
    python preview.py

켜지는 것
  - 리뷰 분석 서비스 (services/review-insight, mock 모드, 포트 8020) — 이 파일이 대신 켜고, 끌 때 같이 끕니다
  - 확인용 서버 (포트 8040)
      http://127.0.0.1:8040/owner/                 사장님 확인 화면: 가게 계정 로그인 → 그 가게 리뷰 → 답글
      http://127.0.0.1:8040/owner/full/            고객응대 전체 화면 (리뷰 분석 서비스의 화면 그대로: 분석·캡처·응대 기한과 점수·
                                                   보고서·받은함·가게 정보·다국어 메뉴판). 로그인한 가게의 데이터만 보임
      http://127.0.0.1:8040/shop/                  가상 배달앱 (시연 가게)
      http://127.0.0.1:8040/shop/?store=store_<가게>   가입한 가게의 배달앱

사장님 확인 화면(preview/owner.html)은 로그인과 가게별 리뷰가 어떻게 보이는지 확인하려고 만든 것입니다.
팀의 통합 화면(services/web)이 아니고, 통합 화면에 들어가지 않습니다.

시연용 계정(ongi·basak·mongle)의 비밀번호
  환경 변수 DEMO_ACCOUNT_PASSWORD 를 정했으면 그 값, 안 정했으면 켤 때마다 새로 만들어 이 창에만 보여 줍니다.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

HERE = Path(__file__).resolve().parent
SERVICE_DIR = HERE.parent / "review-insight"
SERVICE_PORT = int(os.environ.get("SERVICE_PORT", "8020"))
PORT = int(os.environ.get("PORT", "8040"))


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def start_service(password: str, token: str) -> subprocess.Popen:
    env = os.environ | {"APP_MODE": os.environ.get("APP_MODE", "mock"), "APP_ACCESS_TOKEN": token, "DEMO_ACCOUNT_PASSWORD": password}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(SERVICE_PORT),
                             "--log-level", "warning"], cwd=SERVICE_DIR, env=env)
    for _ in range(60):
        if proc.poll() is not None:
            raise SystemExit(f"리뷰 분석 서비스가 켜지지 않았어요. 포트 {SERVICE_PORT} 를 다른 프로그램이 쓰는지, "
                             f"'pip install -r ../review-insight/requirements.txt' 를 했는지 확인해 주세요.")
        try:
            if httpx.get(f"http://127.0.0.1:{SERVICE_PORT}/api/health", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.5)
    proc.terminate()
    raise SystemExit("리뷰 분석 서비스가 30초 안에 답하지 않았어요.")


def create_app(token: str) -> FastAPI:
    sys.path.insert(0, str(SERVICE_DIR / "integration"))
    from care_proxy import create_care_routers          # 통합 화면 서버가 붙일 것과 같은 프록시
    from shop_routes import create_shop_router

    base = f"http://127.0.0.1:{SERVICE_PORT}"
    app = FastAPI(title="화면 확인용 서버", docs_url=None, redoc_url=None, openapi_url=None)
    api, pages = create_care_routers(base_url=base, token=token)
    app.include_router(api)
    app.include_router(pages)
    app.include_router(create_shop_router(base_url=base, token=token))

    # ── 고객응대 전체 화면: 리뷰 분석 서비스의 화면(app/static/index.html)을 그대로 보여 주고,
    #    그 화면이 부르는 /api/review-insight/* 를 로그인한 가게로 고정해서 넘긴다 (토큰은 여기서 붙임).
    http = httpx.Client(base_url=base, timeout=60)

    def denied():
        return JSONResponse({"error": {"code": "LOGIN_REQUIRED", "message": "로그인이 필요해요. /owner/ 에서 로그인해 주세요.",
                                       "retryable": False, "details": {}}}, status_code=401)

    @app.get("/owner/full", include_in_schema=False)
    def full_redirect():
        return RedirectResponse("/owner/full/")

    @app.get("/owner/full/", include_in_schema=False)
    def full(request: Request):
        if api.session_of(request) is None:
            return RedirectResponse("/owner/")
        return FileResponse(SERVICE_DIR / "app" / "static" / "index.html", media_type="text/html; charset=utf-8",
                            headers={"Cache-Control": "no-cache"})

    @app.get("/health", include_in_schema=False)
    def health():
        try:
            return JSONResponse(http.get("/api/health", timeout=5).json() | {"token_required": False})
        except (httpx.HTTPError, ValueError):
            return JSONResponse({"status": "down"}, status_code=503)

    @app.api_route("/api/review-insight/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], include_in_schema=False)
    async def module_api(path: str, request: Request):
        account = api.session_of(request)
        if account is None:
            return denied()
        if path.startswith("auth/"):
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "없는 주소예요.", "retryable": False, "details": {}}}, status_code=404)
        store = account["store_id"]
        params = dict(request.query_params)
        params.pop("visitor_id", None)
        if not path.startswith("public/"):
            params["store_id"] = store
        body = await request.body()
        kind = request.headers.get("content-type", "")
        if body and kind.startswith("application/json"):
            try:
                data = json.loads(body)
            except ValueError:
                data = None
            if isinstance(data, dict):
                data["store_id"] = store
                data.pop("visitor_id", None)
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers = {"X-Access-Token": token}
        if kind:
            headers["Content-Type"] = kind
        try:
            r = http.request(request.method, "/api/review-insight/" + path, params=params, content=body or None, headers=headers)
        except httpx.HTTPError:
            return JSONResponse({"error": {"code": "SERVICE_DOWN", "message": "리뷰 분석 서비스에 연결하지 못했어요.", "retryable": True, "details": {}}}, status_code=503)
        if path == "stores" and r.status_code == 200:          # 가게 고르기 칸에는 로그인한 가게만
            items = [x for x in r.json().get("items", []) if x.get("store_id") == store]
            return {"items": items, "count": len(items), "default": store}
        return Response(r.content, status_code=r.status_code, headers={"Content-Type": r.headers.get("content-type", "application/json")})

    @app.get("/", include_in_schema=False)
    @app.get("/owner", include_in_schema=False)
    def home():
        return RedirectResponse("/owner/")

    @app.get("/owner/", include_in_schema=False)
    def owner():
        return FileResponse(HERE / "preview" / "owner.html", media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})

    return app


if __name__ == "__main__":
    if not SERVICE_DIR.is_dir():
        raise SystemExit(f"리뷰 분석 서비스 폴더가 없어요: {SERVICE_DIR}")
    for port, name in ((SERVICE_PORT, "SERVICE_PORT"), (PORT, "PORT")):
        if not port_free(port):
            raise SystemExit(f"포트 {port} 를 다른 프로그램이 쓰고 있어요. 그 프로그램을 끄거나, 다른 포트로 켜 주세요.\n"
                             f"  PowerShell:  $env:{name}=\"{port + 1}\"; python preview.py")
    given = os.environ.get("DEMO_ACCOUNT_PASSWORD", "").strip()
    password = given or secrets.token_urlsafe(9)
    token = secrets.token_hex(16)                        # 두 서버끼리만 쓰는 값. 켤 때마다 새로 만듦
    service = start_service(password, token)
    print("\n  사장님 확인 화면   http://127.0.0.1:%d/owner/" % PORT)
    print("  고객응대 전체 화면 http://127.0.0.1:%d/owner/full/   (로그인한 뒤)" % PORT)
    print("  가상 배달앱        http://127.0.0.1:%d/shop/" % PORT)
    print("  시연용 계정        ongi · basak · mongle")
    print("  시연용 비밀번호    %s" % ("(DEMO_ACCOUNT_PASSWORD 에 정한 값)" if given else password + "   ← 이번 실행에만 쓰는 값"))
    print("  끄기               Ctrl+C\n")
    try:
        uvicorn.run(create_app(token), host="127.0.0.1", port=PORT, log_level="warning")
    finally:
        service.terminate()
