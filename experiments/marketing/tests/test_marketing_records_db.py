"""맞춤 마케팅 기록을 DB 에 두기 (11/19) — 가짜 응답, HCX 호출 없음 (mock).

- DB_HOST 가 있으면 기록이 PostgreSQL 의 marketing_sessions·coupon_runs 표로, 없으면 예전처럼 파일로 간다 (records.py).
- 같은 시험을 메모리 저장소(shared.storage.MemoryStore)와 PostgreSQL 에 돌린다. PostgreSQL 은 TEST_DB_HOST 등이 있을 때만
  (shared/storage/testing.py). 두 서버가 같은 기록을 보는지는 PostgreSQL 연결 풀 두 개로 본다.
- DB 가 꺼졌을 때: 쓰기는 화면 흐름을 막지 않고(session_id 만 null), 보고서는 데모로 바꾸지 않고 503, 지우기는 500.

실행 (experiments/marketing 에서):  python -m pytest -q -s tests/test_marketing_records_db.py
"""

import os
import socket
import unittest
import uuid

from fastapi.testclient import TestClient

import c6  # noqa: F401 — 저장소 루트를 import 경로에 넣는다 (shared.storage)
from shared.storage import MemoryStore, StorageConfigError, StorageError
from shared.storage.testing import db_env, open_test_db

from marketing_survey import records
from marketing_survey.server import app
from tests.test_marketing_survey_visitor import API, COUPON_RESULT, STORE, _env, _walk

HAS_DB = db_env() is not None


def _vid(prefix="v"):
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _no_files(test):
    folder = os.environ[records.RECORDS_DIR_ENV]
    test.assertEqual([n for n in os.listdir(folder) if n.startswith("records_")] if os.path.isdir(folder) else [], [])


class _DbModeBase:
    """하위 클래스가 make_store() 로 저장소를 준다. 시험마다 방문자 id 를 새로 만든다 (PostgreSQL 은 시험끼리 표를 같이 씀)."""

    def make_store(self):
        raise NotImplementedError

    def setUp(self):
        self.env = _env()
        self.env.start()
        self.store = self.make_store()
        records.use(self.store)
        self.store.marketing.delete(STORE, records.COMMON_VISITOR)      # 공용 자리는 시험 사이에 비운다
        self.client = TestClient(app)
        self.a, self.b = _vid("a"), _vid("b")

    def tearDown(self):
        self.store.marketing.delete(STORE, records.COMMON_VISITOR)
        records.reset()
        self.env.stop()

    def _coupon_plan(self, visitor=None):
        state = _walk(self.client, COUPON_RESULT[0], COUPON_RESULT[1:], visitor)
        q = {"visitor_id": visitor} if visitor else {}
        res = self.client.post(f"{API}/plan", params=q, json={"state": state})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_health_says_db(self):
        body = self.client.get("/health").json()
        self.assertEqual(body["records_store"], "db")
        self.assertIn("records_dir_writable", body)                      # 기존 칸은 그대로

    def test_writes_go_to_the_db_and_not_to_files(self):
        plan = self._coupon_plan(self.a)
        self.assertTrue(plan["session_id"])
        _no_files(self)
        rows = records.load(STORE, self.a)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["table"], row["id"], row["visitor_id"], row["store_id"]),
                         (records.COUPON_RUNS, plan["session_id"], self.a, STORE))
        self.assertEqual((row["issued"], row["used"]), (100, 10))
        self.assertRegex(row["created_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+09:00$")

    def test_visitors_are_separate_and_report_falls_back_to_demo(self):
        self._coupon_plan(self.a)
        a = self.client.get(f"{API}/report", params={"visitor_id": self.a})
        b = self.client.get(f"{API}/report", params={"visitor_id": self.b})
        self.assertEqual((a.status_code, b.status_code), (200, 200))
        self.assertFalse(a.json()["demo"])
        self.assertEqual(a.json()["cost"]["coupon"]["issued"], 100)
        self.assertTrue(b.json()["demo"])                                # B 는 A 기록을 못 보고 데모
        self.assertEqual(records.load(STORE, self.b), [])
        self.assertEqual(records.load(STORE), [])                        # 공용 자리도 그대로

    def test_approve_links_parent_and_report_counts_it(self):
        state = _walk(self.client, "맞춤 홍보 제안", (), self.a)
        plan = self.client.post(f"{API}/plan", params={"visitor_id": self.a}, json={"state": state}).json()
        res = self.client.post(f"{API}/approve", params={"visitor_id": self.a},
                               json={"state": state, "session_id": plan["session_id"]})
        self.assertEqual(res.status_code, 200, res.text)
        rows = records.load(STORE, self.a)
        self.assertEqual([r["decision"] for r in rows], ["proposed", "approved"])
        self.assertEqual((rows[0]["id"], rows[1]["parent_id"]), (plan["session_id"], rows[0]["id"]))
        self.assertTrue(self.client.get(f"{API}/report", params={"visitor_id": self.a}).json()["activity"]["approved"])

    def test_order_is_kept_across_the_two_tables(self):
        s1 = records.append_session(STORE, "survey", decision="proposed", visitor_id=self.a)
        c1 = records.append_coupon_run(STORE, menu_name=None, discount_krw=2000, issued=100, used=10, avg_order_krw=15000,
                                       margin_pct=30, visitor_id=self.a)
        s2 = records.append_session(STORE, "survey", decision="approved", parent_id=s1["id"], visitor_id=self.a)
        self.assertEqual([r["id"] for r in records.load(STORE, self.a)], [s1["id"], c1["id"], s2["id"]])
        self.assertEqual(records.load(STORE, self.a), [s1, c1, s2])      # 돌려준 줄과 꺼낸 줄이 같다

    def test_delete_removes_only_that_visitor(self):
        self._coupon_plan(self.a)
        self._coupon_plan(self.b)
        self._coupon_plan()
        res = self.client.delete(f"{API}/records", params={"visitor_id": self.a})
        self.assertEqual((res.status_code, res.json()), (200, {"deleted": True}))
        self.assertEqual(records.load(STORE, self.a), [])
        self.assertEqual(len(records.load(STORE, self.b)), 1)
        self.assertEqual(len(records.load(STORE)), 1)
        again = self.client.delete(f"{API}/records", params={"visitor_id": self.a})
        self.assertEqual((again.status_code, again.json()), (200, {"deleted": False}))
        self.assertTrue(self.client.get(f"{API}/report", params={"visitor_id": self.a}).json()["demo"])

    def test_delete_never_touches_the_common_records(self):
        self._coupon_plan()
        self.assertEqual(self.client.delete(f"{API}/records").status_code, 400)
        res = self.client.delete(f"{API}/records", params={"visitor_id": records.COMMON_VISITOR})
        self.assertEqual((res.status_code, res.json()), (200, {"deleted": False}))
        self.assertEqual(len(records.load(STORE)), 1)
        with self.assertRaises(ValueError):
            records.delete(STORE, None)

    def test_same_shape_as_the_file_mode(self):
        """같은 흐름을 파일 방식과 DB 방식으로 돌려 꺼낸 줄의 칸·값 모양을 견준다 (id·시각 값만 다름)."""
        def run():
            state = _walk(self.client, "맞춤 홍보 제안", (), self.a)
            plan = self.client.post(f"{API}/plan", params={"visitor_id": self.a}, json={"state": state}).json()
            self.client.post(f"{API}/approve", params={"visitor_id": self.a}, json={"state": state, "session_id": plan["session_id"]})
            self._coupon_plan(self.a)
            return records.load(STORE, self.a)

        db_rows = run()
        records.use(None)
        file_rows = run()
        records.use(self.store)

        def shape(rows):
            return [{k: (type(v).__name__, None if k in ("id", "parent_id", "created_at") else v) for k, v in r.items()}
                    for r in rows]
        self.assertEqual(len(db_rows), 3)
        self.assertEqual(shape(db_rows), shape(file_rows))
        self.assertEqual([list(r) for r in db_rows], [list(r) for r in file_rows])      # 칸 순서도 같다

    def test_bad_values_are_skipped_without_breaking_the_flow(self):
        with self.assertRaises(ValueError):
            records.append_coupon_run(STORE, menu_name=None, discount_krw=2**40, issued=1, used=1, avg_order_krw=1,
                                      visitor_id=self.a)
        with self.assertRaises(ValueError):
            records.append_session(STORE, "survey", answers={"x": object()}, visitor_id=self.a)
        with self.assertRaises(ValueError):
            records.load(STORE, "../evil")
        self.assertEqual(records.load(STORE, self.a), [])


class TestDbModeMemory(_DbModeBase, unittest.TestCase):
    def make_store(self):
        return MemoryStore()


@unittest.skipUnless(HAS_DB, "TEST_DB_HOST 없음 (PostgreSQL 시험은 건너뜀)")
class TestDbModePostgres(_DbModeBase, unittest.TestCase):
    def make_store(self):
        return open_test_db("ic26-test-marketing")

    def test_two_servers_see_the_same_records(self):
        """WAS 두 대 흉내: 연결 풀 두 개. 한쪽에서 쓴 것을 다른 쪽이 읽고 지운다."""
        other = open_test_db("ic26-test-marketing-2")
        try:
            plan = self._coupon_plan(self.a)
            records.use(other)
            rows = records.load(STORE, self.a)
            self.assertEqual([r["id"] for r in rows], [plan["session_id"]])
            self.assertFalse(self.client.get(f"{API}/report", params={"visitor_id": self.a}).json()["demo"])
            self.assertEqual(self.client.delete(f"{API}/records", params={"visitor_id": self.a}).json(), {"deleted": True})
            records.use(self.store)
            self.assertEqual(records.load(STORE, self.a), [])
        finally:
            other.close()


class _DownMarketing:
    def add(self, *a, **k):
        raise StorageError("DB 에 닿지 못했습니다 (OperationalError)")

    list = delete = add


class _DownStore:
    kind = "postgres"
    marketing = _DownMarketing()

    def close(self):
        pass


class TestDbDown(unittest.TestCase):
    """DB 가 꺼졌을 때. 가짜 저장소(늘 StorageError)로 본다 — 진짜 끊김은 아래 PostgreSQL 시험."""

    def setUp(self):
        self.env = _env()
        self.env.start()
        records.use(_DownStore())
        self.client = TestClient(app)

    def tearDown(self):
        records.reset()
        self.env.stop()

    def check_down_behaviour(self):
        state = _walk(self.client, COUPON_RESULT[0], COUPON_RESULT[1:], "visitorA")
        plan = self.client.post(f"{API}/plan", params={"visitor_id": "visitorA"}, json={"state": state})
        self.assertEqual(plan.status_code, 200, plan.text)                # 쓰기 실패는 화면 흐름을 막지 않는다
        self.assertIsNone(plan.json()["session_id"])
        state = _walk(self.client, "맞춤 홍보 제안", (), "visitorA")
        self.assertEqual(self.client.post(f"{API}/approve", params={"visitor_id": "visitorA"},
                                          json={"state": state, "session_id": None}).status_code, 200)
        rep = self.client.get(f"{API}/report", params={"visitor_id": "visitorA"})
        self.assertEqual(rep.status_code, 503)                            # 데모로 바꾸지 않는다
        self.assertIn("기록을 읽지 못했어요", rep.json()["detail"])
        res = self.client.delete(f"{API}/records", params={"visitor_id": "visitorA"})
        self.assertEqual(res.status_code, 500)
        self.assertIn("기록을 지우지 못했어요", res.json()["detail"])
        health = self.client.get("/health")
        self.assertEqual((health.status_code, health.json()["records_store"]), (200, "db"))
        _no_files(self)                                                   # 파일로 몰래 돌아가지 않는다
        with self.assertRaises(records.RecordsUnavailable):
            records.load_for_report(STORE, "visitorA")
        self.assertTrue(issubclass(records.RecordsUnavailable, OSError))

    def test_fake_down_store(self):
        self.check_down_behaviour()

    @unittest.skipUnless(HAS_DB, "TEST_DB_HOST 없음 (PostgreSQL 시험은 건너뜀)")
    def test_unreachable_postgres(self):
        from shared.storage.pg import Database
        from shared.storage.testing import db_config
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        db = Database(db_config(host="127.0.0.1", port=port, connect_timeout=1.0, retry_after=0.5),
                      app_name="ic26-test-marketing-down").open()
        records.use(db)
        self.check_down_behaviour()


class TestBackendChoice(unittest.TestCase):
    def tearDown(self):
        records.reset()

    def test_no_db_host_means_files(self):
        with _env():
            records.reset()
            self.assertIsNone(records.backend())
            self.assertEqual(records.storage_kind(), "file")
            self.assertEqual(TestClient(app).get("/health").json()["records_store"], "file")
            records.append_session(STORE, "survey", visitor_id="visitorA")
            self.assertTrue(records.records_path(STORE, "visitorA").is_file())     # 파일 방식은 그대로

    def test_half_configured_db_stops_at_startup(self):
        with _env(DB_HOST="db.example.invalid", DB_NAME="x"):
            records.reset()
            with self.assertRaises(StorageConfigError):
                with TestClient(app):
                    pass

    def test_db_host_opens_without_waiting_for_the_db(self):
        try:
            import psycopg  # noqa: F401
        except ImportError:
            self.skipTest("psycopg 없음")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        with _env(DB_HOST="127.0.0.1", DB_PORT=str(port), DB_NAME="x", DB_USER="x", DB_CONNECT_TIMEOUT="1"):
            records.reset()
            with TestClient(app) as client:                               # 꺼진 DB 여도 서버는 켜진다
                self.assertEqual(client.get("/health").json()["records_store"], "db")
                self.assertEqual(client.get(f"{API}/report", params={"visitor_id": "visitorA"}).status_code, 503)


if __name__ == "__main__":
    unittest.main()
