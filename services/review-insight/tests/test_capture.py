"""캡처 입력 시험. 키·네트워크 없이 돈다: 이미지는 Pillow 로 만들고 HCX-005 답은 httpx.MockTransport 로 만든다."""
import base64
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import classify, service
from app.classify import Classifier
from app.sources import capture
from app.sources.capture import CaptureError, CaptureReader, merge, parse_reviews, prepare


@pytest.fixture(autouse=True)
def tmp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(classify, "RUNTIME_CACHE", tmp_path / "runtime.json")
    monkeypatch.setattr(classify, "USAGE_LOG", tmp_path / "logs" / "llm_usage.jsonl")
    monkeypatch.setattr(capture, "USAGE_LOG", tmp_path / "logs" / "llm_usage.jsonl")


def image(w=600, h=1000, fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format=fmt)
    return buf.getvalue()


def hcx(contents, finish="stop", status=200, seen=None):
    """조각마다 contents 에서 하나씩 꺼내 HCX 답처럼 돌려주는 가짜 transport."""
    queue = list(contents)

    def handle(request: httpx.Request):
        body = json.loads(request.content)
        if seen is not None:
            seen.append(body)
        if status != 200:
            return httpx.Response(status, json={"status": {"code": str(status)}})
        content = queue.pop(0) if queue else "[]"
        return httpx.Response(200, json={"status": {"code": "20000"}, "result": {
            "message": {"role": "assistant", "content": content}, "finishReason": finish,
            "usage": {"promptTokens": 900, "completionTokens": 50, "totalTokens": 950}}})
    return httpx.MockTransport(handle)


def live(transport):
    return CaptureReader("live", api_key="test-key", transport=transport)


# ── 이미지 검사 ──
@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_accepts_png_jpg_webp(fmt):
    assert len(prepare(image(fmt=fmt))) == 1


def test_accepts_phone_camera_jpg_saved_as_mpo():
    """휴대폰·카카오톡 jpg 는 Pillow 가 MPO 로 읽는다 (11/15 실제 시험에서 막혔던 경우)."""
    buf = io.BytesIO()
    Image.new("RGB", (600, 900), "white").save(buf, format="MPO", save_all=True, append_images=[Image.new("RGB", (600, 900))])
    assert Image.open(io.BytesIO(buf.getvalue())).format == "MPO"
    (piece,) = prepare(buf.getvalue())
    assert Image.open(io.BytesIO(piece)).format == "JPEG"


def test_rejects_other_formats_and_non_images():
    for data in (image(fmt="GIF"), b"not an image", b""):
        with pytest.raises(CaptureError) as e:
            prepare(data)
        assert e.value.status == 400 and e.value.code == "VALIDATION_ERROR"


def test_rejects_too_big(monkeypatch):
    monkeypatch.setenv("CAPTURE_MAX_BYTES", "1000")
    with pytest.raises(CaptureError) as e:
        prepare(image())
    assert e.value.details["max_bytes"] == 1000


def test_shrinks_long_side_to_2240():
    (piece,) = prepare(image(3000, 4000))
    assert max(Image.open(io.BytesIO(piece)).size) <= 2240


def test_splits_tall_capture_with_ratio_inside_1_to_5():
    pieces = prepare(image(400, 5000))            # 1:12.5 → 여러 조각
    assert 1 < len(pieces) <= 5
    for p in pieces:
        w, h = Image.open(io.BytesIO(p)).size
        assert h / w <= 5 and max(w, h) <= 2240


def test_too_tall_capture_is_refused():
    with pytest.raises(CaptureError) as e:
        prepare(image(200, 8000))
    assert e.value.code == "CAPTURE_TOO_LONG"


def test_too_wide_capture_is_refused():
    with pytest.raises(CaptureError):
        prepare(image(3000, 400))


# ── 답 정리 ──
def test_parse_reviews_is_lenient_about_wrapping():
    content = '아래와 같습니다\n```json\n[{"text": " 맛있어요  또 시킬게요 ", "rating": "5"}, {"text": "별점 안 보임", "rating": 7}, {"rating": 3}, {"text": ""}]\n```'
    assert parse_reviews(content) == [{"text": "맛있어요 또 시킬게요", "rating": 5}, {"text": "별점 안 보임", "rating": None}]


def test_parse_reviews_returns_empty_for_garbage():
    assert parse_reviews("죄송합니다. 읽을 수 없습니다") == []


def test_merge_drops_overlap_duplicates():
    a = [{"text": "공깃밥이 빠졌어요", "rating": None}, {"text": "맛있어요", "rating": 5}]
    b = [{"text": "공깃밥이 빠졌어요.", "rating": 2}, {"text": "늦었어요", "rating": 1}]
    assert merge([a, b]) == [{"text": "공깃밥이 빠졌어요", "rating": 2}, {"text": "맛있어요", "rating": 5},
                             {"text": "늦었어요", "rating": 1}]


# ── HCX-005 호출 ──
def test_live_sends_image_as_data_uri_and_reads_reviews(tmp_path):
    seen = []
    r = live(hcx(['[{"text": "제육 양이 많아요", "rating": 5}]'], seen=seen)).read(image())
    assert r.demo is False and r.reviews == [{"text": "제육 양이 많아요", "rating": 5}] and r.warnings == []
    content = seen[0]["messages"][0]["content"]
    uri = content[0]["dataUri"]["data"]
    assert content[0]["type"] == "image_url" and uri.startswith("data:image/jpeg;base64,")      # 앞머리 없으면 400 (11/15 확인)
    assert base64.b64decode(uri.split(",", 1)[1])[:2] == b"\xff\xd8"
    assert content[1]["type"] == "text" and "보이는 그대로" in content[1]["text"]
    assert seen[0]["maxTokens"] <= 4096
    # 사용 기록에는 이미지·글이 없다
    row = json.loads((tmp_path / "logs" / "llm_usage.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert row["purpose"] == "review_capture" and row["reviews_found"] == 1
    assert "제육" not in json.dumps(row, ensure_ascii=False) and "data" not in row


def test_finish_reason_length_adds_warning():
    r = live(hcx(['[{"text": "맛있어요", "rating": 5}]'], finish="length")).read(image())
    assert any("길이 제한" in w for w in r.warnings)


def test_tall_capture_calls_once_per_piece_and_merges():
    seen = []
    pieces = len(prepare(image(400, 5000)))
    answers = ['[{"text": "첫 리뷰", "rating": 5}, {"text": "경계 리뷰", "rating": 3}]',
               '[{"text": "경계 리뷰", "rating": 3}, {"text": "둘째 리뷰", "rating": 1}]'] + ["[]"] * 5
    r = live(hcx(answers, seen=seen)).read(image(400, 5000))
    assert len(seen) == pieces
    assert [x["text"] for x in r.reviews] == ["첫 리뷰", "경계 리뷰", "둘째 리뷰"]
    assert any("조각" in w for w in r.warnings)


def test_zero_reviews_is_unreadable_error():
    with pytest.raises(CaptureError) as e:
        live(hcx(["[]"])).read(image())
    assert e.value.status == 422 and e.value.code == "CAPTURE_UNREADABLE" and "붙여넣기" in e.value.message


def test_upstream_failure_is_retryable_502():
    with pytest.raises(CaptureError) as e:
        live(hcx([], status=500)).read(image())
    assert e.value.status == 502 and e.value.retryable


def test_no_key_or_mock_gives_demo():
    for r in (CaptureReader("mock", api_key="k"), CaptureReader("live", api_key="")):
        out = r.read(image())
        assert out.demo and out.reviews and "예시" in out.warnings[0]


def test_demo_still_validates_image():
    with pytest.raises(CaptureError):
        CaptureReader("mock").read(b"nope")


# ── API ──
@pytest.fixture
def client(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_classifier", Classifier("mock"))
    monkeypatch.setattr(main, "_reader", None)
    return TestClient(main.app), main


def post(c, data, **form):
    return c.post("/api/review-insight/reviews/capture", files={"file": ("cap.png", data, "image/png")}, data=form)


def test_api_returns_masked_candidates_and_does_not_save(client, monkeypatch):
    c, main = client
    monkeypatch.setattr(main, "_reader", live(hcx(['[{"text": "010-1234-5678 로 연락 주세요. 공깃밥이 빠졌어요", "rating": 2}]'])))
    before = len(service.all_reviews("store_ongi"))
    r = post(c, image())
    assert r.status_code == 200
    body = r.json()
    assert body["demo"] is False and body["count"] == 1
    cand = body["candidates"][0]
    assert cand["pii_masked"] and "010" not in cand["text"] and cand["rating"] == 2 and cand["duplicate"] is False
    assert len(service.all_reviews("store_ongi")) == before          # 저장하지 않음


def test_api_marks_duplicate_of_saved_review(client, monkeypatch):
    c, main = client
    saved = service.sample_reviews("store_ongi")[0].text
    monkeypatch.setattr(main, "_reader", live(hcx([json.dumps([{"text": saved, "rating": None}], ensure_ascii=False)])))
    assert post(c, image()).json()["candidates"][0]["duplicate"] is True


def test_api_demo_mode_is_marked(client, monkeypatch):
    c, main = client
    monkeypatch.setattr(main, "_reader", CaptureReader("mock"))
    body = post(c, image()).json()
    assert body["demo"] is True and body["engine"] == "demo" and body["count"] == len(capture.DEMO_REVIEWS)


def test_api_errors_use_common_shape(client, monkeypatch):
    c, main = client
    monkeypatch.setattr(main, "_reader", live(hcx(["모르겠어요"])))
    r = post(c, image())
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "CAPTURE_UNREADABLE" and "붙여넣기" in err["message"] and err["request_id"]
    r = post(c, b"not an image")
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_api_requires_token_when_set(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv("APP_ACCESS_TOKEN", "team-secret")
    assert post(c, image()).status_code == 401


# ── 캡처가 서비스 전체를 멈추지 않는지 (11/15 통합 점검: 읽는 동안 /api/health 가 4.8~18.1초 멈췄음) ──
class SlowReader:
    """읽기에 오래 걸리는 가짜 (실제로는 Pillow + HCX 호출 + 재시도 대기). 읽기를 시작하면 started 를 켠다."""
    model = "HCX-005"

    def __init__(self, seconds=1.5):
        import threading
        self.seconds, self.started = seconds, threading.Event()

    def read(self, data, kind="reviews"):
        import time
        self.started.set()
        time.sleep(self.seconds)
        rows = [{"name": "느린 메뉴", "price": 9000}] if kind == "menu" else [{"text": "느리게 읽은 리뷰", "rating": 4}]
        return capture.CaptureResult(reviews=rows, pieces=1)


@pytest.mark.parametrize("path", ["/api/review-insight/reviews/capture", "/api/review-insight/profile/menu/capture"])
def test_health_stays_fast_while_a_capture_is_being_read(monkeypatch, path):
    import threading
    import time
    from app import main
    slow = SlowReader()
    monkeypatch.setattr(main, "_classifier", Classifier("mock"))
    monkeypatch.setattr(main, "_reader", slow)
    done = {}
    # with 로 연 TestClient 는 이벤트 루프 하나를 같이 쓴다 (실제 서버의 워커 1개와 같음). 막히는 코드가 루프에서 돌면 health 도 기다린다
    with TestClient(main.app) as c:
        worker = threading.Thread(target=lambda: done.setdefault(
            "r", c.post(path, files={"file": ("cap.png", image(), "image/png")})))
        worker.start()
        assert slow.started.wait(5), "캡처 읽기가 시작되지 않음"
        t0 = time.perf_counter()
        health = c.get("/api/health")
        waited = time.perf_counter() - t0
        worker.join(10)
    assert health.status_code == 200
    assert waited < 0.7, f"캡처를 읽는 동안 /api/health 가 {waited:.2f}초 기다림"
    assert done["r"].status_code == 200 and done["r"].json()["count"] == 1
