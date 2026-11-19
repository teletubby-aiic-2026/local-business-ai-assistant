"""자료 상태·실시간 발행 확인·문화행사 API를 가짜 서울시 응답으로 시험한다.

실제 서울 열린데이터광장 호출, .env, 운영 DB, 공식 원본 폴더를 쓰지 않는다.
인증키 자리에는 시험용 문자열만 넣고, 응답과 로그에 그 문자열이 없는지 본다.
"""
from contextlib import ExitStack
from datetime import datetime
import hashlib
import importlib
import io
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from fastapi.testclient import TestClient

from app.cultural_events import CulturalEventsService, normalize_event
from app.data_sync import KST, STATE_FILE, DataSyncService, next_period
from app.onboarding import COOKIE_NAME, OnboardingStore
from app.seoul_client import BASE_URL, SERVICES, ParsedResponse, SeoulApiError, SeoulClient, SeoulPage

_store_init = OnboardingStore.__init__


def _memory_default(self, path=None, **kwargs):
    _store_init(self, ":memory:" if path is None else path, **kwargs)


with patch.object(OnboardingStore, "__init__", _memory_default):
    intake_api = importlib.import_module("app.intake_api")

FAKE_KEY = "TESTKEY-never-print-7f3a9c"
PERIODS = ("20243", "20244", "20251", "20252", "20253", "20254", "20261", "20262")
LOCAL_TOTALS = {"sales": 21000, "stores": 76000, "population": 1650}
UP_TO_DATE = "서울 열린데이터광장 실시간 조회 완료: 현재 서울시 최신 발행 분기는 2026년 2분기이며 서버 적재본과 일치합니다"
NOW = datetime(2026, 11, 18, 20, 30, 5, tzinfo=KST)


class Ticker:
    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value


class FakeSeoul:
    """SeoulClient.fetch_page / fetch_auxiliary 대역. 응답은 (자료, 분기)별로 정한다."""

    def __init__(self, answers=None, *, sample_only=False, gate=None, events=None):
        self.answers = answers or {}
        self.sample_only = sample_only
        self.gate = gate
        self.events = events
        self.calls = []
        self.lock = threading.Lock()

    def fetch_page(self, dataset, period=None, start=1, count=5, *, area_code=None):
        with self.lock:
            self.calls.append((dataset, period, start, count))
        if self.gate is not None:
            self.gate.wait(5)
        answer = self.answers.get((dataset, period), 0)
        if isinstance(answer, BaseException):
            raise answer
        if answer:
            rows = [{"STDR_YYQU_CD": period, "TRDAR_CD": "3110001"}] * min(count, answer)
            parsed = ParsedResponse(rows, answer, "INFO-000")
        else:
            parsed = ParsedResponse([], 0, "INFO-200")
        suffix = f"/json/{SERVICES[dataset]}/{start}/{start + count - 1}/{period}/"
        return SeoulPage(dataset, SERVICES[dataset], period, start, start + count - 1,
                         f"{BASE_URL}/REDACTED{suffix}", self.sample_only, parsed, {})

    def fetch_auxiliary(self, service, start=1, count=5):
        with self.lock:
            self.calls.append((service, None, start, count))
        if isinstance(self.events, BaseException):
            raise self.events
        return self.events, f"{BASE_URL}/REDACTED/json/{service}/{start}/{start + count - 1}/"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class KeyedOpener:
    """실제 SeoulClient에 넣는 가짜 urlopen. 받은 주소를 기록하고 정한 대로 답한다."""

    def __init__(self, decide):
        self.decide = decide
        self.urls = []
        self.lock = threading.Lock()

    def __call__(self, request, timeout):
        url = request.full_url
        with self.lock:
            self.urls.append(url)
        result = self.decide(url)
        if isinstance(result, BaseException):
            raise result
        return FakeResponse(json.dumps(result, ensure_ascii=False).encode("utf-8"))


def seoul_payload(service, total, period=None, rows=None):
    if not total:
        return {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}
    rows = rows if rows is not None else [{"STDR_YYQU_CD": period, "TRDAR_CD": "3110001"}] * min(5, total)
    return {service: {"list_total_count": total, "RESULT": {"CODE": "INFO-000", "MESSAGE": "정상 처리되었습니다"},
                      "row": rows}}


def event_row(title, district, start, end, **extra):
    row = {"TITLE": title, "CODENAME": "공연", "PLACE": f"{district} 시험 장소", "GUNAME": district,
           "STRTDATE": f"{start} 00:00:00.0", "END_DATE": f"{end} 00:00:00.0",
           "DATE": f"{start}~{end}", "IS_FREE": "무료", "USE_FEE": "", "ORG_LINK": "https://example.org/event",
           "HMPG_ADDR": "", "LAT": "37.5", "LOT": "126.9"}
    row.update(extra)
    return row


def events_payload(rows):
    return {"culturalEventInfo": {"list_total_count": len(rows), "RESULT": {"CODE": "INFO-000"}, "row": rows}}


EVENT_ROWS = [
    event_row("시험 동작 진행 중 공연", "동작구", "2026-11-10", "2026-11-30"),
    event_row("시험 동작 끝난 공연", "동작구", "2026-10-01", "2026-11-17"),
    event_row("시험 마포 예정 전시", "마포구", "2026-12-01", "2026-12-20", CODENAME="전시/미술", IS_FREE="유료",
              USE_FEE="5,000원", ORG_LINK="javascript:alert(1)", HMPG_ADDR="https://example.org/detail"),
    {"TITLE": "", "GUNAME": "동작구", "STRTDATE": "2026-11-10", "END_DATE": "2026-11-30"},
    event_row("시험 날짜 없음", "동작구", "", ""),
]


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))
        if record.exc_info:
            self.lines.append(logging.Formatter().formatException(record.exc_info))


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"SEOUL_OPENAPI_KEY": FAKE_KEY}))
        for name in ("APP_PUBLIC_ORIGIN", "ASSISTANT_ENABLED", "ONBOARDING_DB_PATH"):
            os.environ.pop(name, None)
        self.temp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.root = self.temp / "service"
        self.state_dir = self.temp / "writable"
        self.files = self.make_local_files()
        self.ticker = Ticker()
        self.store = OnboardingStore(":memory:")
        self.stack.callback(self.store.close)
        self.stack.enter_context(patch.object(intake_api, "load_settings", return_value=None))
        self.stack.enter_context(patch.object(intake_api, "MapsClient", return_value=None))
        self.app = intake_api.create_app(onboarding_store=self.store)
        self.client = self.stack.enter_context(TestClient(self.app))
        self.logs = LogCapture()
        root_logger = logging.getLogger()
        previous = root_logger.level
        root_logger.addHandler(self.logs)
        root_logger.setLevel(logging.DEBUG)
        self.stack.callback(root_logger.setLevel, previous)
        self.stack.callback(root_logger.removeHandler, self.logs)

    def make_local_files(self):
        entries = []
        for period in PERIODS:
            for dataset, total in LOCAL_TOTALS.items():
                start = 1
                while start <= total:
                    count = min(1000, total - start + 1)
                    name = f"{dataset}_{period}_all_{start}_{start + 999}.json"
                    entries.append({"path": f"data/raw/official/{name}", "dataset": dataset, "period": period,
                                    "area_code": None, "start": start, "row_count": count})
                    start += 1000
        entries.append({"path": "data/raw/official/stores_20243_3110001_1_1000.json", "dataset": "stores",
                        "period": "20243", "area_code": "3110001", "start": 1, "row_count": 12})
        entries.append({"path": "data/raw/official/areas_none_all_1_1000.json", "dataset": "areas",
                        "period": None, "area_code": None, "start": 1, "row_count": 1000})
        raw = self.root / "data/raw/official"
        raw.mkdir(parents=True)
        for entry in entries:
            (self.root / entry["path"]).write_text("{}", encoding="utf-8")
        return entries

    def catalog_source(self):
        return {"catalog_version": "b1_test_catalogue", "files": json.loads(json.dumps(self.files))}

    def no_catalog(self):
        raise FileNotFoundError("data/official/onboarding_analysis_catalog.json")

    def sync_service(self, fake=None, **kwargs):
        options = {"state_dir": self.state_dir, "client_factory": (lambda: fake), "catalog_source": self.catalog_source,
                   "root": self.root, "now": lambda: NOW, "monotonic": self.ticker}
        options.update(kwargs)
        service = DataSyncService(**options)
        self.app.state.data_sync = service
        return service

    def answers(self, overrides=None):
        result = {(dataset, "20262"): total for dataset, total in LOCAL_TOTALS.items()}
        result.update(overrides or {})
        return result

    def snapshot_tree(self):
        return {str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(self.root.rglob("*")) if path.is_file()}

    def assert_no_key(self, *texts):
        for text in texts:
            self.assertNotIn(FAKE_KEY, text)
        for line in self.logs.lines:
            self.assertNotIn(FAKE_KEY, line)


class DataStatusTests(ServiceTestCase):
    def test_status_without_local_data(self):
        self.sync_service(FakeSeoul(), catalog_source=self.no_catalog)
        with patch.dict(os.environ, {"SEOUL_OPENAPI_KEY": ""}):
            result = self.client.get("/api/onboarding/data-status")
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body["schema_version"], "onboarding-data-status-v1")
        self.assertEqual(body["status"], "data_required")
        self.assertFalse(body["data_ready"])
        self.assertIsNone(body["latest_period"])
        self.assertEqual(body["periods"], [])
        self.assertEqual(body["verified_files"], 0)
        self.assertIsNone(body["last_synced_at"])
        self.assertIs(body["key_configured"], False)
        self.assertIn(COOKIE_NAME, result.cookies)
        self.assertEqual(result.headers["cache-control"], "no-store")

    def test_status_with_local_data(self):
        self.sync_service(FakeSeoul())
        result = self.client.get("/api/onboarding/data-status")
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["latest_period"], "20262")
        self.assertEqual(body["latest_period_label"], "2026년 2분기")
        self.assertEqual(body["periods"], list(PERIODS))
        self.assertEqual(body["period_count"], 8)
        self.assertEqual(body["listed_files"], len(self.files))
        self.assertEqual(body["verified_files"], len(self.files))
        self.assertEqual(body["missing_files"], 0)
        self.assertEqual(body["local_totals"], LOCAL_TOTALS)
        self.assertEqual(body["catalog_version"], "b1_test_catalogue")
        self.assertIs(body["key_configured"], True)
        self.assertIsNone(body["last_synced_at"])
        self.assertIn("2024년 3분기~2026년 2분기", body["message"])
        self.assert_no_key(result.text)

    def test_missing_source_file_is_reported(self):
        (self.root / self.files[0]["path"]).unlink()
        self.sync_service(FakeSeoul())
        body = self.client.get("/api/onboarding/data-status").json()
        self.assertEqual(body["status"], "source_files_missing")
        self.assertEqual(body["missing_files"], 1)
        self.assertEqual(body["verified_files"], len(self.files) - 1)


class DataSyncTests(ServiceTestCase):
    def test_up_to_date_message_totals_and_state(self):
        fake = FakeSeoul(self.answers())
        self.sync_service(fake)
        before = self.snapshot_tree()
        result = self.client.post("/api/onboarding/data-sync")
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body["schema_version"], "onboarding-data-sync-v1")
        self.assertEqual(body["status"], "up_to_date")
        self.assertEqual(body["message"], UP_TO_DATE)
        self.assertEqual(body["checked_at"], "2026-11-18T20:30:05+09:00")
        self.assertEqual(body["totals"], LOCAL_TOTALS)
        self.assertEqual({k: v["total"] for k, v in body["datasets"].items()}, LOCAL_TOTALS)
        self.assertTrue(all(v["matches_local"] for v in body["datasets"].values()))
        self.assertFalse(body["next_published"])
        self.assertIsNone(body["staged"])
        self.assertIs(body["sample_only"], False)
        self.assertFalse(body["data_changed"])
        self.assertTrue(body["state_saved"])
        self.assertEqual(body["last_synced_at"], body["checked_at"])
        self.assertEqual(sorted(fake.calls), sorted((d, p, 1, 5) for d in LOCAL_TOTALS for p in ("20262", "20263", "20264")))
        self.assertEqual(self.snapshot_tree(), before)
        saved = json.loads((self.state_dir / STATE_FILE).read_text(encoding="utf-8"))
        self.assertEqual(saved["last_synced_at"], "2026-11-18T20:30:05+09:00")
        status = self.client.get("/api/onboarding/data-status").json()
        self.assertEqual(status["last_synced_at"], "2026-11-18T20:30:05+09:00")
        self.assertEqual(status["last_sync"]["status"], "up_to_date")
        self.assert_no_key(result.text, json.dumps(saved))

    def test_quarter_words_come_from_local_data(self):
        self.files = [entry for entry in self.files if entry["period"] not in ("20261", "20262")]
        fake = FakeSeoul({(dataset, "20254"): total for dataset, total in LOCAL_TOTALS.items()})
        self.sync_service(fake)
        body = self.client.post("/api/onboarding/data-sync").json()
        self.assertEqual(body["message"], UP_TO_DATE.replace("2026년 2분기", "2025년 4분기"))
        self.assertEqual({p for _d, p, _s, _c in fake.calls}, {"20254", "20261", "20262"})
        self.assertEqual(next_period("20254"), "20261")

    def test_next_quarter_is_reported_but_not_applied(self):
        fake = FakeSeoul(self.answers({("sales", "20263"): 21500, ("stores", "20263"): 77000,
                                         ("population", "20263"): 1651}))
        self.sync_service(fake)
        before = self.snapshot_tree()
        body = self.client.post("/api/onboarding/data-sync").json()
        self.assertEqual(body["status"], "next_published")
        self.assertTrue(body["next_published"])
        self.assertIsNone(body["staged"])
        self.assertFalse(body["data_changed"])
        self.assertEqual(body["remote_latest_period"], "20263")
        self.assertIn("2026년 3분기", body["message"])
        self.assertIn("다시 설치", body["apply_hint"])
        self.assertIn("--from-dir", body["apply_hint"])
        self.assertTrue(body["next_periods"][0]["published"])
        self.assertFalse(body["next_periods"][1]["published"])
        self.assertEqual(body["datasets"]["sales"]["next"]["20263"]["total"], 21500)
        # 서비스 원본·카탈로그는 그대로이고, 상태 파일 외에 새 파일을 만들지 않는다.
        self.assertEqual(self.snapshot_tree(), before)
        self.assertEqual(sorted(p.name for p in self.state_dir.iterdir()), [STATE_FILE])
        status = self.client.get("/api/onboarding/data-status").json()
        self.assertEqual(status["latest_period"], "20262")

    def test_per_dataset_failures_never_500(self):
        fake = FakeSeoul(self.answers({("stores", "20262"): SeoulApiError("Seoul API request failed or timed out."),
                                         ("population", "20263"): RuntimeError("boom")}))
        self.sync_service(fake)
        result = self.client.post("/api/onboarding/data-sync")
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body["status"], "incomplete")
        self.assertEqual(body["errors"], ["stores", "population"])
        self.assertEqual(body["datasets"]["sales"]["total"], LOCAL_TOTALS["sales"])
        self.assertIsNone(body["datasets"]["stores"]["total"])
        self.assertTrue(body["datasets"]["stores"]["error"])
        self.assertEqual(body["datasets"]["stores"]["error_detail"], "Seoul API request failed or timed out.")
        self.assertEqual(body["datasets"]["population"]["next"]["20263"]["error_detail"], "RuntimeError")
        self.assertIn("점포·길단위인구", body["message"])
        self.assertFalse(body["state_saved"])
        self.assertFalse((self.state_dir / STATE_FILE).exists())

    def test_client_construction_failure_is_reported(self):
        def broken():
            raise ValueError("no client")

        self.sync_service(client_factory=broken)
        result = self.client.post("/api/onboarding/data-sync")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "incomplete")

    def test_total_mismatch_is_not_called_identical(self):
        fake = FakeSeoul(self.answers({("sales", "20262"): 21001}))
        self.sync_service(fake)
        body = self.client.post("/api/onboarding/data-sync").json()
        self.assertEqual(body["status"], "differs")
        self.assertNotIn("일치합니다", body["message"])
        self.assertIn("추정매출", body["message"])
        self.assertIs(body["datasets"]["sales"]["matches_local"], False)

    def test_missing_key_uses_public_sample_and_keeps_state(self):
        def decide(url):
            self.assertIn("/sample/", url)
            dataset = next(name for name, service in SERVICES.items() if f"/{service}/" in url)
            period = url.rstrip("/").rsplit("/", 1)[1]
            return seoul_payload(SERVICES[dataset], LOCAL_TOTALS[dataset] if period == "20262" else 0, period)

        opener = KeyedOpener(decide)
        with patch.dict(os.environ, {"SEOUL_OPENAPI_KEY": ""}):
            self.sync_service(client_factory=lambda: SeoulClient(timeout=5, opener=opener))
            result = self.client.post("/api/onboarding/data-sync")
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertIs(body["sample_only"], True)
        self.assertIn("1~5건", body["notice"])
        self.assertEqual(body["message"], UP_TO_DATE)
        self.assertEqual(len(opener.urls), 9)
        self.assertTrue(all(url.endswith(("/1/5/20262/", "/1/5/20263/", "/1/5/20264/")) for url in opener.urls))
        self.assertFalse(body["state_saved"])
        self.assertIsNone(body["last_synced_at"])
        self.assertFalse((self.state_dir / STATE_FILE).exists())

    def test_only_one_sync_at_a_time(self):
        gate = threading.Event()
        fake = FakeSeoul(self.answers(), gate=gate)
        service = self.sync_service(fake)
        outcome = {}
        worker = threading.Thread(target=lambda: outcome.setdefault("result", service.sync()))
        worker.start()
        try:
            for _ in range(200):
                if fake.calls:
                    break
                threading.Event().wait(0.01)
            busy = self.client.post("/api/onboarding/data-sync")
        finally:
            gate.set()
            worker.join(10)
        self.assertEqual(busy.status_code, 429, busy.text)
        self.assertIn("진행 중", busy.json()["detail"])
        self.assertEqual(busy.headers["retry-after"], "5")
        self.assertEqual(outcome["result"]["status"], "up_to_date")
        self.assertEqual(len(fake.calls), 9)

    def test_recent_success_is_reused(self):
        fake = FakeSeoul(self.answers())
        self.sync_service(fake)
        first = self.client.post("/api/onboarding/data-sync").json()
        second = self.client.post("/api/onboarding/data-sync").json()
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(second["checked_at"], first["checked_at"])
        self.assertEqual(len(fake.calls), 9)
        self.ticker.value += 31
        third = self.client.post("/api/onboarding/data-sync").json()
        self.assertFalse(third["reused"])
        self.assertEqual(len(fake.calls), 18)

    def test_rejected_origin_never_reaches_sync(self):
        fake = FakeSeoul(self.answers())
        self.sync_service(fake)
        result = self.client.post("/api/onboarding/data-sync", headers={"Origin": "https://attacker.example"})
        self.assertEqual(result.status_code, 403)
        self.assertEqual(fake.calls, [])

    def test_key_never_in_response_or_logs(self):
        def decide(url):
            self.assertIn(FAKE_KEY, url)
            if "/VwsmTrdarStorQq/" in url and url.endswith("/20262/"):
                return URLError(f"timed out while opening {url}")
            if "/VwsmTrdarFlpopQq/" in url and url.endswith("/20263/"):
                return HTTPError(url, 500, f"server error for {url}", {}, io.BytesIO(url.encode()))
            dataset = next(name for name, service in SERVICES.items() if f"/{service}/" in url)
            period = url.rstrip("/").rsplit("/", 1)[1]
            return seoul_payload(SERVICES[dataset], LOCAL_TOTALS[dataset] if period == "20262" else 0, period)

        opener = KeyedOpener(decide)
        self.sync_service(client_factory=lambda: SeoulClient(timeout=5, opener=opener))
        result = self.client.post("/api/onboarding/data-sync")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "incomplete")
        status = self.client.get("/api/onboarding/data-status")
        self.assertEqual(len(opener.urls), 9)
        self.assertTrue(any("data-sync probe failed" in line for line in self.logs.lines))
        self.assert_no_key(result.text, status.text)


class CulturalEventsTests(ServiceTestCase):
    def events_service(self, fake, **kwargs):
        options = {"client_factory": (lambda: fake), "now": lambda: NOW, "monotonic": self.ticker}
        options.update(kwargs)
        service = CulturalEventsService(**options)
        self.app.state.cultural_events = service
        return service

    def test_district_filter_drops_ended_and_unreadable_events(self):
        fake = FakeSeoul(events=events_payload(EVENT_ROWS))
        self.events_service(fake)
        result = self.client.get("/api/onboarding/cultural-events", params={"district": "동작구"})
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body["schema_version"], "onboarding-cultural-events-v1")
        self.assertFalse(body["demo"])
        self.assertEqual(body["scope"], "district")
        self.assertFalse(body["fallback"])
        self.assertEqual([e["title"] for e in body["events"]], ["시험 동작 진행 중 공연"])
        event = body["events"][0]
        self.assertEqual(set(event), {"title", "category", "place", "district", "start", "end", "is_free", "fee", "link"})
        self.assertEqual((event["start"], event["end"], event["district"]), ("2026-11-10", "2026-11-30", "동작구"))
        self.assertIs(event["is_free"], True)
        self.assertEqual(fake.calls, [("culturalEventInfo", None, 1, 40)])
        self.assertIn(COOKIE_NAME, result.cookies)

    def test_no_district_match_falls_back_to_seoul(self):
        fake = FakeSeoul(events=events_payload(EVENT_ROWS))
        self.events_service(fake)
        body = self.client.get("/api/onboarding/cultural-events", params={"district": "강남구"}).json()
        self.assertTrue(body["fallback"])
        self.assertEqual(body["scope"], "seoul")
        self.assertEqual([e["title"] for e in body["events"]], ["시험 동작 진행 중 공연", "시험 마포 예정 전시"])
        paid = body["events"][1]
        self.assertIs(paid["is_free"], False)
        self.assertEqual(paid["fee"], "5,000원")
        self.assertEqual(paid["link"], "https://example.org/detail")
        self.assertIn("강남구", body["notice"])
        everything = self.client.get("/api/onboarding/cultural-events").json()
        self.assertIsNone(everything["district"])
        self.assertFalse(everything["fallback"])
        self.assertEqual(len(everything["events"]), 2)

    def test_cache_avoids_second_call_until_ttl(self):
        fake = FakeSeoul(events=events_payload(EVENT_ROWS))
        self.events_service(fake)
        first = self.client.get("/api/onboarding/cultural-events", params={"district": "동작구"}).json()
        second = self.client.get("/api/onboarding/cultural-events", params={"district": "동작구"}).json()
        other = self.client.get("/api/onboarding/cultural-events", params={"district": "마포구"}).json()
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertTrue(other["cached"])
        self.assertEqual(len(fake.calls), 1)
        self.ticker.value += 601
        self.client.get("/api/onboarding/cultural-events", params={"district": "동작구"})
        self.assertEqual(len(fake.calls), 2)

    def test_missing_key_returns_labelled_demo_without_call(self):
        opener = KeyedOpener(lambda url: self.fail("no request without a key"))
        with patch.dict(os.environ, {"SEOUL_OPENAPI_KEY": ""}):
            self.events_service(None, client_factory=lambda: SeoulClient(timeout=5, opener=opener))
            body = self.client.get("/api/onboarding/cultural-events", params={"district": "동작구"}).json()
        self.assertTrue(body["demo"])
        self.assertEqual(body["status"], "demo")
        self.assertIn("인증키", body["notice"])
        self.assertTrue(body["events"])
        self.assertTrue(all("예시" in e["title"] and "실제 행사 아님" in e["title"] and e["link"] is None
                            for e in body["events"]))
        self.assertEqual(opener.urls, [])

    def test_network_error_returns_demo_and_backs_off(self):
        opener = KeyedOpener(lambda url: URLError(f"unreachable {url}"))
        self.events_service(None, client_factory=lambda: SeoulClient(timeout=5, opener=opener))
        result = self.client.get("/api/onboarding/cultural-events", params={"district": "동작구"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()["demo"])
        again = self.client.get("/api/onboarding/cultural-events", params={"district": "동작구"})
        self.assertTrue(again.json()["demo"])
        self.assertEqual(len(opener.urls), 1)
        self.assertIn(FAKE_KEY, opener.urls[0])
        self.assertTrue(opener.urls[0].endswith("/json/culturalEventInfo/1/40/"))
        self.assertTrue(any("cultural events unavailable" in line for line in self.logs.lines))
        self.assert_no_key(result.text, again.text)

    def test_malformed_response_returns_demo(self):
        for payload in ({"culturalEventInfo": {"RESULT": {"CODE": "INFO-000"}, "row": "not-a-list"}},
                        {"RESULT": {"CODE": "INFO-100", "MESSAGE": "인증키가 유효하지 않습니다."}},
                        ["not", "an", "object"]):
            with self.subTest(payload=payload):
                self.events_service(FakeSeoul(events=payload))
                body = self.client.get("/api/onboarding/cultural-events", params={"district": "동작구"}).json()
                self.assertTrue(body["demo"])
                self.assertIn("예시", body["notice"])

    def test_key_never_in_event_response_or_logs(self):
        def decide(url):
            if not hasattr(decide, "done"):
                decide.done = True
                return HTTPError(url, 503, f"bad gateway {url}", {}, io.BytesIO(url.encode()))
            return events_payload(EVENT_ROWS)

        opener = KeyedOpener(decide)
        self.events_service(None, client_factory=lambda: SeoulClient(timeout=5, opener=opener), failure_ttl_seconds=0)
        failed = self.client.get("/api/onboarding/cultural-events", params={"district": "동작구"})
        live = self.client.get("/api/onboarding/cultural-events", params={"district": "동작구"})
        self.assertTrue(failed.json()["demo"])
        self.assertFalse(live.json()["demo"])
        self.assertEqual(len(opener.urls), 2)
        self.assert_no_key(failed.text, live.text)

    def test_district_validation(self):
        fake = FakeSeoul(events=events_payload(EVENT_ROWS))
        self.events_service(fake)
        for params in ({"district": "Gangnam"}, {"district": "동작구동작구동작구동작구"}, {"district": "부산진구"},
                       {"district": "동작"}, {"district": "<script>"}, [("district", "동작구"), ("district", "마포구")],
                       {"district": "동작구", "extra": "1"}):
            with self.subTest(params=params):
                result = self.client.get("/api/onboarding/cultural-events", params=params)
                self.assertIn(result.status_code, (400, 422), result.text)
        self.assertEqual(fake.calls, [])
        ok = self.client.get("/api/onboarding/cultural-events", params={"district": " 동작구 "})
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_normalize_handles_date_range_and_bad_links(self):
        event = normalize_event({"TITLE": "범위만 있는 행사", "DATE": "2026-11-20~2026-11-22", "GUNAME": "동작구",
                                 "ORG_LINK": "ftp://example.org", "HMPG_ADDR": "https://example.org/x",
                                 "USE_FEE": "무료", "IS_FREE": ""})
        self.assertEqual((event["start"], event["end"]), ("2026-11-20", "2026-11-22"))
        self.assertEqual(event["link"], "https://example.org/x")
        self.assertIs(event["is_free"], True)
        self.assertIsNone(normalize_event({"TITLE": "끝이 시작보다 빠름", "STRTDATE": "2026-11-20", "END_DATE": "2026-11-01"}))


class SeoulClientInjectionTests(unittest.TestCase):
    def test_auxiliary_service_is_allow_listed_and_sample_bounded(self):
        client = SeoulClient(api_key="", opener=lambda *a, **k: self.fail("no request"))
        with self.assertRaises(ValueError):
            client.fetch_auxiliary("VwsmTrdarSelngQq", 1, 5)
        with self.assertRaises(ValueError):
            client.fetch_auxiliary("culturalEventInfo", 1, 40)
        with self.assertRaises(ValueError):
            SeoulClient(api_key=FAKE_KEY, timeout=0)

    def test_fetch_page_redacts_and_keeps_timeout(self):
        seen = {}

        def opener(request, timeout):
            seen.update(url=request.full_url, timeout=timeout)
            return FakeResponse(json.dumps(seoul_payload("VwsmTrdarSelngQq", 7, "20262")).encode())

        page = SeoulClient(api_key=FAKE_KEY, timeout=3, opener=opener).fetch_page("sales", "20262", 1, 5)
        self.assertEqual(page.parsed.total_count, 7)
        self.assertIn(FAKE_KEY, seen["url"])
        self.assertEqual(seen["timeout"], 3)
        self.assertNotIn(FAKE_KEY, page.source_url)
        self.assertNotIn(FAKE_KEY, repr(page))


if __name__ == "__main__":
    unittest.main()
