"""React 빌드 화면 스위치 (WEB_FRONTEND_DIST) 시험. 네트워크·모델을 부르지 않는다.

실행 (services/web 에서):
  PYTHONPATH=<저장소 루트> python -m unittest tests.test_frontend_dist -v
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from web.assistant_proxy import AssistantProxy
from web.care_proxy import CareProxy
from web.demo import Demo
from web.main import create_app, react_dist

from tests.test_web import FakeSource, settings


def make_client() -> TestClient:
    demo = Demo(settings(Path(tempfile.mkdtemp())), source=FakeSource())
    return TestClient(create_app(demo, assistant=AssistantProxy(None), care=CareProxy(None)))


def make_dist(root: Path) -> Path:
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text('<!doctype html><div id="root"></div><script type="module" src="/assets/app.js"></script>', encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log('react')", encoding="utf-8")
    return root


class FrontendDistTests(unittest.TestCase):
    def test_default_serves_old_screen(self):
        with mock.patch.dict(os.environ, {"WEB_FRONTEND_DIST": ""}):
            client = make_client()
            page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn('/static/app.js', page.text)
        self.assertEqual(client.get("/static/app.js").status_code, 200)

    def test_dist_serves_react_index_and_assets(self):
        dist = make_dist(Path(tempfile.mkdtemp()) / "dist")
        with mock.patch.dict(os.environ, {"WEB_FRONTEND_DIST": str(dist)}):
            client = make_client()
            page = client.get("/")
            asset = client.get("/assets/app.js")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="root"', page.text)
        self.assertEqual(asset.status_code, 200)
        self.assertIn("react", asset.text)
        # 예전 화면 파일과 API 는 그대로
        self.assertEqual(client.get("/static/app.js").status_code, 200)
        self.assertEqual(client.get("/api/health").status_code, 200)

    def test_assets_do_not_set_visitor_cookie(self):
        dist = make_dist(Path(tempfile.mkdtemp()) / "dist")
        with mock.patch.dict(os.environ, {"WEB_FRONTEND_DIST": str(dist)}):
            asset = make_client().get("/assets/app.js")
        self.assertNotIn("visitor_id", asset.headers.get("set-cookie", ""))

    def test_missing_index_falls_back(self):
        empty = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, {"WEB_FRONTEND_DIST": str(empty)}):
            self.assertIsNone(react_dist())
            page = make_client().get("/")
        self.assertIn('/static/app.js', page.text)


if __name__ == "__main__":
    unittest.main()
