"""화면 빌드(React 18 + Vite 5, services/web/frontend/dist) 서빙 시험 (11/20 단일 화면 전환). 네트워크·모델·node 를 쓰지 않는다.

실제 frontend/dist 가 있든 없든 결과가 같게, 기본 폴더(web.main.FRONTEND_DIST)를 임시 폴더로 바꿔 끼우고 WEB_FRONTEND_DIST 는 비운다.

확인하는 것
  · 기본: FRONTEND_DIST(= services/web/frontend/dist)의 index.html 을 / 로, assets/* 를 /assets/* 로 준다
  · WEB_FRONTEND_DIST 를 주면 그 폴더가 기본 폴더보다 먼저다 (빈 값·공백이면 기본 폴더)
  · 빌드가 없으면 / 는 200 안내 HTML(UTF-8, 경고 로그 한 번), /assets/* 는 404 (500 이 아님). 서버를 띄운 뒤 빌드해도 새로고침하면 보인다
  · 화면 파일(/assets/*) 응답에는 visitor_id 쿠키를 싣지 않는다 (페이지 / 에는 싣는다)
  · 옛 화면 주소 /static/* 는 없다 (404)

실행 (services/web 에서):
  PYTHONPATH=<저장소 루트>:. python -m pytest -q tests/test_frontend_dist.py
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from web import main as web_main
from web.assistant_proxy import AssistantProxy
from web.care_proxy import CareProxy
from web.demo import Demo
from web.main import NO_BUILD_HTML, VISITOR_COOKIE, create_app, frontend_dist
from web.settings import WEB_DIR

from tests.test_web import FakeSource, settings

REAL_DEFAULT = web_main.FRONTEND_DIST          # 바꿔 끼우기 전의 기본 폴더


def make_client() -> TestClient:
    demo = Demo(settings(Path(tempfile.mkdtemp())), source=FakeSource())
    return TestClient(create_app(demo, assistant=AssistantProxy(None), care=CareProxy(None)))


def make_dist(root: Path, marker: str) -> Path:
    """index.html + assets/app.js 만 있는 작은 빌드 폴더. marker 로 어느 폴더에서 왔는지 가린다."""
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(f'<!doctype html><div id="root" data-build="{marker}"></div>'
                                     '<script type="module" src="/assets/app.js"></script>', encoding="utf-8")
    (root / "assets" / "app.js").write_text(f"console.log('{marker}')", encoding="utf-8")
    return root


class FrontendDistTests(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"WEB_FRONTEND_DIST": ""})
        env.start()
        self.addCleanup(env.stop)
        self.default = Path(tempfile.mkdtemp()) / "dist"       # 아직 없음 (빌드 전)
        patch = mock.patch.object(web_main, "FRONTEND_DIST", self.default)
        patch.start()
        self.addCleanup(patch.stop)

    def test_default_folder_is_frontend_dist(self):
        self.assertEqual(REAL_DEFAULT, WEB_DIR / "frontend" / "dist")
        self.assertEqual(frontend_dist(), self.default)
        with mock.patch.dict(os.environ, {"WEB_FRONTEND_DIST": "   "}):    # 공백뿐이면 비운 것과 같다
            self.assertEqual(frontend_dist(), self.default)

    def test_default_serves_the_build(self):
        make_dist(self.default, "default")
        client = make_client()
        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.headers["content-type"].startswith("text/html"))
        self.assertIn('data-build="default"', page.text)
        self.assertEqual(page.headers.get("cache-control"), "no-cache")   # 새 묶음으로 바꾼 뒤 옛 index.html 이 남지 않게
        asset = client.get("/assets/app.js")
        self.assertEqual(asset.status_code, 200)
        self.assertIn("javascript", asset.headers["content-type"])
        self.assertIn("default", asset.text)
        self.assertEqual(client.get("/api/health").status_code, 200)            # API 는 그대로

    def test_env_overrides_the_default(self):
        make_dist(self.default, "default")
        other = make_dist(Path(tempfile.mkdtemp()) / "other", "override")
        with mock.patch.dict(os.environ, {"WEB_FRONTEND_DIST": str(other)}):
            self.assertEqual(frontend_dist(), other.resolve())
            client = make_client()
        page = client.get("/")
        self.assertIn('data-build="override"', page.text)
        self.assertNotIn("default", page.text)
        self.assertIn("override", client.get("/assets/app.js").text)

    def test_missing_build_gives_a_guidance_page_not_an_error(self):
        with self.assertLogs("web.main", level="WARNING") as logs:          # 띄울 때 경고 한 번
            client = make_client()
        self.assertTrue(any(str(self.default / "index.html") in line for line in logs.output), logs.output)
        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.headers["content-type"].startswith("text/html"))
        self.assertIn("charset=utf-8", page.headers["content-type"].lower())
        self.assertEqual(page.text, NO_BUILD_HTML)
        self.assertIn('<meta charset="utf-8">', page.text)
        self.assertIn("npm run build", page.text)                               # 무엇을 하면 되는지 적혀 있다
        self.assertIn(VISITOR_COOKIE, page.cookies)                             # 페이지 응답이라 쿠키는 그대로
        missing = client.get("/assets/missing.js")
        self.assertEqual(missing.status_code, 404)                              # 빌드 폴더가 없어도 500 이 아님
        self.assertNotIn("set-cookie", missing.headers)
        self.assertEqual(client.get("/api/health").status_code, 200)

    def test_env_folder_without_index_also_gives_the_guidance_page(self):
        empty = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, {"WEB_FRONTEND_DIST": str(empty)}):
            client = make_client()
        self.assertEqual(client.get("/").text, NO_BUILD_HTML)
        self.assertEqual(client.get("/assets/app.js").status_code, 404)

    def test_a_build_made_after_start_is_served_without_restart(self):
        client = make_client()
        self.assertEqual(client.get("/").text, NO_BUILD_HTML)
        self.assertEqual(client.get("/assets/app.js").status_code, 404)
        make_dist(self.default, "late")                                         # 서버를 띄운 뒤 npm run build
        self.assertIn('data-build="late"', client.get("/").text)
        self.assertEqual(client.get("/assets/app.js").status_code, 200)

    def test_assets_do_not_set_the_visitor_cookie(self):
        make_dist(self.default, "default")
        client = make_client()
        asset = client.get("/assets/app.js")
        self.assertEqual(asset.status_code, 200)
        self.assertNotIn("set-cookie", asset.headers)
        self.assertNotIn(VISITOR_COOKIE, client.cookies)
        self.assertIn(VISITOR_COOKIE, client.get("/").cookies)                  # 페이지에는 싣는다

    def test_old_static_paths_are_gone(self):
        make_dist(self.default, "default")
        (self.default / "static").mkdir()                                       # 빌드 폴더 안에 static 폴더가 있어도
        (self.default / "static" / "app.js").write_text("old", encoding="utf-8")
        client = make_client()
        for path in ("/static/app.js", "/static/index.html", "/static/style.css"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 404)


if __name__ == "__main__":
    unittest.main()
