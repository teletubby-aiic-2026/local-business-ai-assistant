#!/usr/bin/env python3
"""서버가 켜질 때 Secret Manager 에서 비밀 값을 받아 /run/ic26/secrets.env 에 쓴다 (ic26-secrets.service 가 부름).

왜: 키와 DB 비밀번호를 /etc/ic26/env(디스크)와 서버 이미지에 두지 않기 위해서다. env 에는 이름만 남기고(값은 빈 칸),
값은 서버가 켜질 때마다 Secret Manager 에서 받아 메모리 영역(/run, 재부팅하면 사라짐)에 둔다.
ic26 서비스 4개는 /etc/ic26/env 를 읽은 뒤 이 파일을 한 번 더 읽는다 (같은 이름이면 이 파일이 이김).

어떻게 (11/18 ic26-was1 에서 실제로 확인한 순서)
  1 서버 메타데이터 v2 토큰:  PUT http://169.254.169.254/latest/api/token  (헤더 X-NCP-METADATA-TOKEN-TTL-SECONDS)
  2 서버에 붙은 역할 ID:      GET .../latest/meta-data/iam/security-credentials  (헤더 X-NCP-METADATA-TOKEN)
     역할이 없으면 404. 콘솔 Sub Account > Roles 에서 Server Role(정책 NCP_SECRETMANAGER_USER)을 이 서버에 적용한다.
  3 임시 키:                  GET .../security-credentials/{역할 ID}  → AccessKeyId, SecretAccessKey (12시간)
  4 값 조회:                  GET https://secretmanager.apigw.ntruss.com/api/v1/secrets/{IC26_SM_ID}/values  (서명 v2)
     값은 data.decryptedSecretChain.active. env 이름을 키로 한 JSON 이다. 예: {"CLOVA_API_KEY": "...", "DB_PASSWORD": "..."}

규칙
  - /etc/ic26/env 의 IC26_SM_ID 가 비어 있으면 아무것도 하지 않는다 (env 의 값을 그대로 씀). 남아 있던 /run 파일은 지운다.
  - 비밀의 이름 중 /etc/ic26/env 에 줄(NAME=)이 있는 이름만 쓴다. env 에 없는 이름은 건너뛰고 이름만 알려 준다.
  - 값은 화면·로그에 내지 않는다. 이름과 개수만 출력한다.
  - 서버가 막 켜져 네트워크가 아직이면 몇 번 다시 시도한다. 역할 없음·권한 없음(4xx)은 다시 시도하지 않는다.

사용법 (root)
  python3 /opt/ic26/deploy/fetch_secrets.py            받아서 /run/ic26/secrets.env 에 씀 (ic26-secrets.service 가 하는 일)
  python3 /opt/ic26/deploy/fetch_secrets.py --check    쓰지 않고, 이름마다 env 의 값과 같은지만 알려 줌
  python3 /opt/ic26/deploy/fetch_secrets.py --blank-env
      받아서 /run 에 쓴 다음, /etc/ic26/env 에서 '받아 온 이름'의 줄만 값을 비운다 (NAME= 으로. 다른 줄·주석·순서는 그대로).
      받기나 쓰기에 실패하면 env 를 건드리지 않는다. Secret Manager 로 옮길 때 서버마다 한 번 한다.
값을 바꾼 뒤(Secret Manager 콘솔): sudo systemctl restart ic26-secrets && sudo systemctl restart ic26-review ic26-marketing ic26-was ic26-market
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

ENV_FILE = "/etc/ic26/env"
OUT_FILE = "/run/ic26/secrets.env"
METADATA_URL = "http://169.254.169.254/latest"
DEFAULT_ENDPOINT = "https://secretmanager.apigw.ntruss.com"
ID_NAME = "IC26_SM_ID"              # 이름에 KEY·SECRET 이 없어야 prepare_image.sh 가 비우지 않는다
ENDPOINT_NAME = "IC26_SM_ENDPOINT"  # (선택) 다른 리전·공공 등
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9._~+/=:@%,-]+$")


class Stop(Exception):
    """다시 시도해도 소용없는 실패 (역할 없음, 권한 없음, 비밀 없음, 형식 오류)."""


def log(msg: str) -> None:
    print(msg, flush=True)


def read_env(path: str) -> dict[str, str]:
    """systemd EnvironmentFile 과 같은 단순 규칙으로 읽는다: 주석·빈 줄 무시, 첫 '=' 기준, 값 앞뒤 공백 제거."""
    out: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith(("#", ";")) or "=" not in s:
                continue
            name, value = s.split("=", 1)
            out[name.strip()] = value.strip()
    return out


def http(method: str, url: str, headers: dict | None = None, timeout: float = 5.0) -> tuple[int, str]:
    data = b"" if method == "PUT" else None
    req = urllib.request.Request(url, headers=headers or {}, method=method, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def temp_credentials(metadata_url: str) -> tuple[str, str]:
    status, token = http("PUT", f"{metadata_url}/api/token", {"X-NCP-METADATA-TOKEN-TTL-SECONDS": "300"}, 3)
    if status != 200:
        raise RuntimeError(f"메타데이터 토큰을 받지 못했습니다 (HTTP {status})")
    h = {"X-NCP-METADATA-TOKEN": token}
    status, role = http("GET", f"{metadata_url}/meta-data/iam/security-credentials", h, 3)
    if status == 404:
        raise Stop("이 서버에 역할(Server Role)이 없습니다. 콘솔 Sub Account > Roles 에서 이 서버를 '역할 적용 대상'에 넣으세요")
    if status != 200 or not role.strip():
        raise RuntimeError(f"역할 ID 를 받지 못했습니다 (HTTP {status})")
    status, body = http("GET", f"{metadata_url}/meta-data/iam/security-credentials/{role.strip()}", h, 3)
    if status != 200:
        raise RuntimeError(f"임시 키를 받지 못했습니다 (HTTP {status})")
    cred = json.loads(body)
    ak, sk = cred.get("AccessKeyId") or "", cred.get("SecretAccessKey") or ""
    if not ak or not sk:
        raise RuntimeError("임시 키 응답에 AccessKeyId/SecretAccessKey 가 없습니다")
    return ak, sk


def signed_get(endpoint: str, uri: str, ak: str, sk: str) -> tuple[int, str]:
    ts = str(int(time.time() * 1000))
    message = f"GET {uri}\n{ts}\n{ak}".encode("utf-8")
    sig = base64.b64encode(hmac.new(sk.encode("utf-8"), message, hashlib.sha256).digest()).decode()
    return http("GET", endpoint.rstrip("/") + uri, {
        "x-ncp-apigw-timestamp": ts, "x-ncp-iam-access-key": ak, "x-ncp-apigw-signature-v2": sig}, 8)


def fetch(secret_id: str, endpoint: str, metadata_url: str) -> dict[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", secret_id):
        raise Stop(f"{ID_NAME} 모양이 맞지 않습니다 (영문·숫자·-·_)")
    ak, sk = temp_credentials(metadata_url)
    status, body = signed_get(endpoint, f"/api/v1/secrets/{secret_id}/values", ak, sk)
    if 400 <= status < 500:
        try:
            err = json.loads(body).get("error") or json.loads(body)
        except ValueError:
            err = body[:120]
        raise Stop(f"Secret Manager 가 거절했습니다 (HTTP {status}): {json.dumps(err, ensure_ascii=False)[:200]}")
    if status != 200:
        raise RuntimeError(f"Secret Manager 응답 HTTP {status}")
    active = ((json.loads(body).get("data") or {}).get("decryptedSecretChain") or {}).get("active")
    if isinstance(active, str):
        try:
            active = json.loads(active)
        except ValueError:
            raise Stop("비밀 값이 JSON 이 아닙니다. env 이름을 키로 한 JSON 으로 저장하세요") from None
    if not isinstance(active, dict) or not active:
        raise Stop("비밀 값(active)이 비어 있거나 JSON 객체가 아닙니다")
    return {str(k): ("" if v is None else str(v)) for k, v in active.items()}


def env_line(name: str, value: str) -> str:
    """systemd EnvironmentFile 한 줄. 값이 단순하면 그대로, 아니면 따옴표로 감싼다."""
    if value == "" or SAFE_VALUE_RE.match(value):
        return f"{name}={value}"
    if "'" not in value:
        return f"{name}='{value}'"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    return f'{name}="{escaped}"'


def write_atomic(path: str, lines: list[str]) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    fd, tmp = tempfile.mkstemp(prefix=".secrets.", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("# ic26-secrets.service 가 Secret Manager 에서 받아 쓴 파일. 재부팅하면 사라지고 다시 받는다. 고치지 않는다.\n")
            f.write("\n".join(lines) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def blank_env(path: str, names: list[str]) -> list[str]:
    """env 에서 names 의 줄만 'NAME=' 으로 비운다. 다른 줄은 글자 하나 바꾸지 않는다. 비운 이름을 돌려준다."""
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines(keepends=True)
    st = os.stat(path)
    targets, done = set(names), []
    for i, line in enumerate(lines):
        m = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*=(.*?)(\r?\n)?$", line)
        if m and m.group(1) in targets and m.group(2).strip():
            lines[i] = f"{m.group(1)}={m.group(3) or ''}"
            done.append(m.group(1))
    if not done:
        return []
    fd, tmp = tempfile.mkstemp(prefix=".env.", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(lines)
        os.chmod(tmp, 0o600)
        try:
            os.chown(tmp, st.st_uid, st.st_gid)
        except PermissionError:
            pass
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return done


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Secret Manager 에서 비밀 값을 받아 /run/ic26/secrets.env 에 쓴다")
    p.add_argument("--env", default=ENV_FILE)
    p.add_argument("--out", default=OUT_FILE)
    p.add_argument("--check", action="store_true", help="쓰지 않고 이름마다 env 값과 같은지만 알려 줌")
    p.add_argument("--blank-env", action="store_true", help="받아서 쓴 다음 env 에서 받아 온 이름의 줄만 값을 비움")
    p.add_argument("--tries", type=int, default=20, help="네트워크가 아직일 때 다시 시도하는 횟수 (기본 20, 6초 간격)")
    p.add_argument("--wait", type=float, default=6.0)
    p.add_argument("--metadata-url", default=METADATA_URL, help=argparse.SUPPRESS)   # 시험용
    a = p.parse_args(argv)

    if not os.path.exists(a.env):
        log(f"오류: {a.env} 이 없습니다")
        return 1
    env = read_env(a.env)
    secret_id = env.get(ID_NAME, "")
    if not secret_id:
        log(f"{ID_NAME} 가 비어 있어 Secret Manager 를 쓰지 않습니다 ({a.env} 의 값을 그대로 씀)")
        if not a.check and os.path.exists(a.out):
            os.unlink(a.out)
            log(f"남아 있던 {a.out} 을 지웠습니다")
        return 0
    endpoint = env.get(ENDPOINT_NAME) or DEFAULT_ENDPOINT

    values: dict[str, str] | None = None
    for attempt in range(1, max(1, a.tries) + 1):
        try:
            values = fetch(secret_id, endpoint, a.metadata_url)
            break
        except Stop as e:
            log(f"오류: {e}")
            return 1
        except (OSError, RuntimeError, ValueError) as e:   # 네트워크·메타데이터가 아직 (서버가 막 켜졌을 때)
            msg = str(e).splitlines()[0][:160] if str(e) else type(e).__name__
            if attempt >= a.tries:
                log(f"오류: {a.tries}번 시도했지만 받지 못했습니다: {msg}")
                return 1
            log(f"다시 시도 {attempt}/{a.tries}: {msg}")
            time.sleep(a.wait)
    assert values is not None

    used, skipped, bad = [], [], []
    for name in sorted(values):
        v = values[name]
        if not NAME_RE.match(name) or name == ID_NAME:
            bad.append(name)
        elif name not in env:
            skipped.append(name)
        elif any(c in v for c in "\r\n\0"):
            bad.append(name)
        else:
            used.append(name)
    if skipped:
        log(f"env 에 줄이 없어 건너뜀: {', '.join(skipped)}")
    if bad:
        log(f"이름이나 값의 모양이 맞지 않아 건너뜀: {', '.join(bad)}")
    if not used:
        log("오류: 쓸 수 있는 이름이 하나도 없습니다")
        return 1

    if a.check:
        for name in used:
            cur = env.get(name, "")
            state = "env 는 비어 있음" if not cur else ("env 와 같음" if hmac.compare_digest(cur, values[name]) else "env 와 다름(Secret Manager 값이 이김)")
            log(f"  {name}: {len(values[name])}자, {state}")
        return 0

    write_atomic(a.out, [env_line(n, values[n]) for n in used])
    still = [n for n in used if env.get(n)]
    log(f"Secret Manager 에서 {len(used)}개를 받아 {a.out} 에 썼습니다: {', '.join(used)}")
    if a.blank_env:
        done = blank_env(a.env, used)
        log(f"{a.env} 에서 값을 비운 줄 {len(done)}개: {', '.join(done) if done else '(이미 비어 있음)'}")
        log("서비스를 다시 시작하면 Secret Manager 값으로 돕니다: sudo systemctl restart ic26-review ic26-marketing ic26-was ic26-market")
    elif still:
        log(f"참고: {a.env} 에도 값이 남아 있는 이름 {len(still)}개 (서비스는 Secret Manager 값을 씀). 비우려면 README 5-1절: {', '.join(still)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
