"""Saved profiles and the six evidence-based market analysis functions.

Run ``python -m app.intake_api``. Importing this module does not load credentials
or create a database. ``configured_app`` is the production application factory.
"""
from contextlib import asynccontextmanager
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import load_settings
from app.naver_clients import MapsClient
from app.onboarding import OnboardingStore, create_onboarding_router


LOCAL_ORIGINS = frozenset({
    "http://127.0.0.1:8766", "http://localhost:8766", "http://testserver",
})


def _public_origin():
    value = os.getenv("APP_PUBLIC_ORIGIN", "").strip()
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
        if (parsed.scheme != "https" or not host or parsed.username is not None or parsed.password is not None
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                or any(character.isspace() or ord(character) < 32 for character in value)
                or not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", host)
                or (port is not None and not 0 < port <= 65535)):
            raise ValueError
        authority = host + (f":{port}" if port is not None and port != 443 else "")
        return {"origin": "https://" + authority, "host": host, "authority": authority}
    except ValueError:
        raise ValueError("APP_PUBLIC_ORIGIN must be one HTTPS origin without credentials, path, query or fragment") from None


def _assistant_enabled():
    value = os.getenv("ASSISTANT_ENABLED", "").strip().lower()
    if value in ("", "0", "false"):
        return False
    if value in ("1", "true"):
        return True
    raise ValueError("ASSISTANT_ENABLED must be empty, 0, false, 1 or true")


def create_app(onboarding_store=None) -> FastAPI:
    public = _public_origin()
    assistant = _assistant_enabled()
    @asynccontextmanager
    async def lifespan(application):
        application.state.maps_client = MapsClient()
        yield

    application = FastAPI(
        title="서울 상권분석 API",
        version="1.0.0",
        description="위치·업종·운영 상태와 공식 상권·분기를 저장하고 공공자료를 조회·비교합니다.",
        lifespan=lifespan,
    )
    application.state.maps_client = None
    application.state.public_mode = public is not None
    application.state.onboarding_store = onboarding_store if onboarding_store is not None else OnboardingStore()
    onboarding_router = create_onboarding_router(application.state.onboarding_store, cookie_secure=public is not None)
    application.include_router(onboarding_router)
    application.state.assistant_enabled = assistant
    onboarding_html = None
    if assistant:
        # Imported only when enabled so the default app stays identical to B1~B6.
        from app.assistant import create_assistant_router

        application.include_router(create_assistant_router(
            application.state.onboarding_store, onboarding_router, cookie_secure=public is not None))
        assistant_static = Path(__file__).parent / "static" / "assistant"
        application.mount("/assistant-assets", StaticFiles(directory=assistant_static, check_dir=False),
                          name="assistant-assets")

        @application.get("/assistant", include_in_schema=False)
        def assistant_page():
            return FileResponse(assistant_static / "index.html", headers={"Cache-Control": "no-cache"})

        from app.assistant.entry import onboarding_html
    static_path = Path(__file__).parent / "static" / "onboarding"
    application.mount("/onboarding-assets", StaticFiles(directory=static_path, check_dir=False), name="onboarding-assets")

    @application.get("/")
    def onboarding_page():
        if onboarding_html is not None:
            # Same page plus a button to the chat; the file itself is unchanged.
            return HTMLResponse(onboarding_html(static_path / "index.html"), headers={"Cache-Control": "no-cache"})
        return FileResponse(static_path / "index.html", headers={"Cache-Control": "no-cache"})
    application.add_middleware(
        TrustedHostMiddleware, allowed_hosts=[public["host"]] if public else ["127.0.0.1", "localhost", "testserver"],
    )

    @application.middleware("http")
    async def allowed_origin_only(request: Request, call_next):
        hosts = request.headers.getlist("host")
        if public and (len(hosts) != 1 or hosts[0].lower() != public["authority"]):
            return JSONResponse(status_code=400, content={"detail": "허용되지 않은 접속 주소입니다."})
        origins = request.headers.getlist("origin")
        allowed = {public["origin"]} if public else LOCAL_ORIGINS
        if len(origins) > 1 or (origins and origins[0] not in allowed):
            return JSONResponse(status_code=403, content={"detail": "허용되지 않은 요청 출처입니다."})
        return await call_next(request)

    @application.get("/health")
    def health():
        return {"service": "seoul-market-analysis", "status": "ok",
                "features": ["B1", "B2", "B3", "B4", "B5", "B6"]}

    return application


def configured_app() -> FastAPI:
    """Load .env before reading APP_PUBLIC_ORIGIN or opening the configured DB."""
    load_settings()
    return create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(configured_app(), host="127.0.0.1", port=8766, access_log=False)
