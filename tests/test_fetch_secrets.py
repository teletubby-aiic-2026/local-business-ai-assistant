"""deploy/fetch_secrets.py 시험: 가짜 서버 메타데이터와 가짜 Secret Manager 를 띄워 서명·쓰기·env 비우기를 본다.

실제 서버(ic26-was1)에서 같은 순서로 값을 읽은 것은 11/18 에 확인했다. 여기서는 그 순서를 흉내 내어
  - 서명 v2 가 맞아야만 값이 오고
  - env 에 줄이 있는 이름만 /run 파일에 쓰이고
  - --blank-env 가 받아 온 이름의 줄만 비우고 나머지는 글자 하나 안 바꾸는지
를 본다. 네트워크는 127.0.0.1 만 쓴다.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
import os
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fetch_secrets", ROOT / "deploy" / "fetch_secrets.py")
fs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fs)

AK, SK, ROLE, SID = "TESTAK0000", "testsecretkey0000", "role-1234", "sid-abc"
SECRET = {
    "CLOVA_API_KEY": "nv-aaaa1111",
    "CLOVASTUDIO_API_KEY": "nv-aaaa1111",
    "DB_PASSWORD": "pa ss'w\"rd$1",      # 따옴표·공백·$ 가 섞인 값
    "NAVER_MAPS_CLIENT_ID": "abc123",
    "NOT_IN_ENV": "x",                   # env 에 줄이 없어 건너뛰어야 함
}
ENV_TEXT = """# ic26 env
APP_MODE=live
IC26_SM_ID={sid}
IC26_SM_ENDPOINT={endpoint}

# HCX
CLOVA_API_KEY=old-value-on-disk
CLOVASTUDIO_API_KEY=
DB_HOST=db.example.internal
DB_PASSWORD=old-db-pass
NAVER_MAPS_CLIENT_ID=
PGTARGETSESSIONATTRS=read-write
"""


class Fake:
    role_status = 200
    sm_status = 200
    calls: list[str] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 시험 출력 조용히
        pass

    def _send(self, code: int, body: str):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_PUT(self):
        Fake.calls.append("PUT " + self.path)
        if self.path == "/md/api/token" and self.headers.get("X-NCP-METADATA-TOKEN-TTL-SECONDS"):
            return self._send(200, "tok")
        self._send(400, "bad")

    def do_GET(self):
        Fake.calls.append("GET " + self.path)
        if self.path.startswith("/md/"):
            if self.headers.get("X-NCP-METADATA-TOKEN") != "tok":
                return self._send(401, "no token")
            if self.path == "/md/meta-data/iam/security-credentials":
                return self._send(Fake.role_status, ROLE if Fake.role_status == 200 else "Path Not found.")
            if self.path == f"/md/meta-data/iam/security-credentials/{ROLE}":
                return self._send(200, json.dumps({"AccessKeyId": AK, "SecretAccessKey": SK, "Token": "", "Code": "Success"}))
            return self._send(404, "nf")
        uri = f"/api/v1/secrets/{SID}/values"
        if self.path != uri:
            return self._send(404, json.dumps({"error": {"errorCode": "404"}}))
        if Fake.sm_status != 200:
            return self._send(Fake.sm_status, json.dumps({"error": {"errorCode": "200", "message": "Authentication Failed"}}))
        ts = self.headers.get("x-ncp-apigw-timestamp", "")
        want = base64.b64encode(hmac.new(SK.encode(), f"GET {uri}\n{ts}\n{AK}".encode(), hashlib.sha256).digest()).decode()
        if self.headers.get("x-ncp-iam-access-key") != AK or self.headers.get("x-ncp-apigw-signature-v2") != want:
            return self._send(401, json.dumps({"error": {"message": "signature"}}))
        body = {"code": "SUCCESS", "data": {"decryptedSecretChain": {"active": json.dumps(SECRET)}, "rotationTargets": []}}
        self._send(200, json.dumps(body))


@pytest.fixture()
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    Fake.role_status, Fake.sm_status, Fake.calls = 200, 200, []
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def setup_env(tmp_path: Path, base: str, sid: str = SID) -> tuple[Path, Path]:
    env = tmp_path / "env"
    env.write_text(ENV_TEXT.format(sid=sid, endpoint=base), encoding="utf-8")
    os.chmod(env, 0o600)
    return env, tmp_path / "run" / "secrets.env"


def run(env: Path, out: Path, base: str, *extra: str) -> int:
    return fs.main(["--env", str(env), "--out", str(out), "--metadata-url", base + "/md", "--tries", "1", "--wait", "0", *extra])


def parse_systemd_env(text: str) -> dict[str, str]:
    """systemd EnvironmentFile 의 따옴표 규칙(작은따옴표는 그대로, 큰따옴표는 \\ 이스케이프)으로 읽어 본다."""
    out = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        if v.startswith("'") and v.endswith("'"):
            v = v[1:-1]
        elif v.startswith('"') and v.endswith('"'):
            v = v[1:-1].replace('\\"', '"').replace("\\$", "$").replace("\\`", "`").replace("\\\\", "\\")
        out[k] = v
    return out


def test_writes_only_names_present_in_env(server, tmp_path, capsys):
    env, out = setup_env(tmp_path, server)
    assert run(env, out, server) == 0
    got = parse_systemd_env(out.read_text())
    assert got == {k: SECRET[k] for k in ("CLOVA_API_KEY", "CLOVASTUDIO_API_KEY", "DB_PASSWORD", "NAVER_MAPS_CLIENT_ID")}
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert stat.S_IMODE(out.parent.stat().st_mode) == 0o700
    printed = capsys.readouterr().out
    assert "NOT_IN_ENV" in printed                      # 건너뛴 이름은 알려 줌
    for v in ("nv-aaaa1111", "pa ss", "abc123"):         # 값은 출력하지 않음
        assert v not in printed
    assert env.read_text() == ENV_TEXT.format(sid=SID, endpoint=server)   # --blank-env 가 없으면 env 그대로


def test_blank_env_clears_only_received_names(server, tmp_path):
    env, out = setup_env(tmp_path, server)
    before = env.read_text().splitlines()
    assert run(env, out, server, "--blank-env") == 0
    after = env.read_text().splitlines()
    assert len(after) == len(before)
    changed = {b: a for b, a in zip(before, after) if a != b}
    assert changed == {"CLOVA_API_KEY=old-value-on-disk": "CLOVA_API_KEY=", "DB_PASSWORD=old-db-pass": "DB_PASSWORD="}
    assert "DB_HOST=db.example.internal" in after and f"IC26_SM_ID={SID}" in after
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert out.exists()


def test_no_role_fails_and_leaves_env_untouched(server, tmp_path, capsys):
    Fake.role_status = 404
    env, out = setup_env(tmp_path, server)
    text = env.read_text()
    assert run(env, out, server, "--blank-env") == 1
    assert env.read_text() == text and not out.exists()
    assert "역할" in capsys.readouterr().out


def test_rejected_by_secret_manager_does_not_retry(server, tmp_path):
    Fake.sm_status = 403
    env, out = setup_env(tmp_path, server)
    assert fs.main(["--env", str(env), "--out", str(out), "--metadata-url", server + "/md", "--tries", "5", "--wait", "0"]) == 1
    assert sum(c.startswith("GET /api/v1/secrets") for c in Fake.calls) == 1
    assert not out.exists()


def test_network_error_retries_then_fails(tmp_path):
    env, out = setup_env(tmp_path, "http://127.0.0.1:9")          # 닫힌 포트
    rc = fs.main(["--env", str(env), "--out", str(out), "--metadata-url", "http://127.0.0.1:9/md", "--tries", "2", "--wait", "0"])
    assert rc == 1 and not out.exists()


def test_empty_id_skips_and_removes_stale_file(tmp_path):
    env, out = setup_env(tmp_path, "http://127.0.0.1:9", sid="")
    out.parent.mkdir(mode=0o700)
    out.write_text("OLD=1\n")
    assert fs.main(["--env", str(env), "--out", str(out)]) == 0
    assert not out.exists()


def test_check_does_not_write(server, tmp_path, capsys):
    env, out = setup_env(tmp_path, server)
    assert run(env, out, server, "--check") == 0
    assert not out.exists()
    printed = capsys.readouterr().out
    assert "CLOVA_API_KEY: 11자, env 와 다름" in printed
    assert "CLOVASTUDIO_API_KEY: 11자, env 는 비어 있음" in printed


@pytest.mark.parametrize("value", ["abc-DEF_1.2/3+4=", "", "has space", "it's", 'q"uo$te`\\x', "nv-1234"])
def test_env_line_round_trip(value):
    assert parse_systemd_env(fs.env_line("X", value))["X"] == value
