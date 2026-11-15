"""가상 배달앱을 통합 화면 서버 없이 혼자 띄워 확인하는 실행 파일.

    python run_local.py                 # http://127.0.0.1:8040/shop/
    PORT=8040 REVIEW_INSIGHT_URL=http://127.0.0.1:8020 REVIEW_INSIGHT_TOKEN=... python run_local.py

여기서 쓴 리뷰는 리뷰 분석 서비스의 가게 공용 칸에 쌓여 모든 사장님 화면에 보입니다 (방문자 쿠키가 필요 없음).
팀 서버에서는 이 파일을 쓰지 않고, 통합 화면 서버가 shop_routes.create_shop_router 를 붙입니다 (docs/handoff.md).
"""
from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI

from shop_routes import create_shop_router

def create_app() -> FastAPI:
    app = FastAPI(title="동네배달 (시연용 가상 배달앱)", docs_url=None, redoc_url=None, openapi_url=None)

    app.include_router(create_shop_router())
    return app


if __name__ == "__main__":
    uvicorn.run(create_app(), host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8040")))
