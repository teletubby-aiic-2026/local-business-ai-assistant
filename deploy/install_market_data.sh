#!/usr/bin/env bash
# 상권 공식 자료(서울시 상권분석서비스 2024Q3~2026Q2 8분기 + 보조자료 4종)를 WAS 서버 제자리에 깔고 ic26-market 을 켠다.
# 코드 묶음(ic26-<커밋>.tgz)과 따로 받는 자료 묶음(seoul-market-data-YYYYMMDD.tar.gz) 하나만 준다. 여러 번 돌려도 안전하다.
#
# 사용법 (서버에서. install_was.sh 를 먼저 한 번 돌린 뒤, 묶음을 푼 폴더 안의 스크립트를 root 로):
#   sudo bash ic26-<커밋>/deploy/install_market_data.sh ~/seoul-market-data-20261116.tar.gz
# 옵션:
#   --sha256 HEX   압축 파일의 SHA-256 을 이 값과 대조 (안 주면 옆의 <파일>.sha256, 그것도 없으면 아래 알려진 값)
#   --replace      이미 깔린 자료와 내용이 다른 파일이 있을 때, 옛 자료를 data.bak-<시각> 으로 옮겨 두고 새로 깐다
#   --check        압축을 풀어 확인만 하고 깔지 않는다
#   --no-systemd   서비스를 건드리지 않는다 (systemd 가 없는 컨테이너 시험용)
#   --no-start     자료만 깔고 서비스는 켜거나 다시 시작하지 않는다
#
# 하는 일
#   1 압축 파일 확인: SHA-256, 멤버가 모두 보통 파일·폴더이고 위험한 경로(절대 경로, '..', 링크, 장치 파일)가 없음
#   2 같은 디스크의 빈 임시 폴더에 풀고 MANIFEST.json 의 파일마다 바이트 수와 SHA-256 을 대조 (하나라도 다르면 멈춤)
#   3 제자리에 배치 (root 소유, 폴더 755 · 파일 644. 서비스 계정 ic26 은 읽기만 함)
#        services/market-analysis/data/**   → /opt/ic26/services/market-analysis/data/   (원본 data/raw/official 포함)
#        source-downloads/**                → /opt/ic26/source-downloads/   (가공 전 원본 보존용. 앱은 읽지 않음)
#        services/market-analysis/app/*.json, data/scenario/*.json
#                                           → 코드 묶음에 같은 파일이 있다. 줄바꿈(CRLF·LF)만 다르고 내용이 같으면 코드 쪽을 그대로 둔다.
#                                             내용이 다르면 덮지 않고 주의를 띄운다 (상권 파트에 확인할 일)
#   4 ic26-market 을 enable 하고 다시 시작 (상권 서비스는 켜질 때 자료를 읽어 둔다) → /health, 자료 준비 상태 확인
# 하지 않는 일: 서울시 OpenAPI 새 수집(--collect), 키를 읽거나 출력하는 일, 코드 파일 바꾸기
# 갱신: install_was.sh 는 /opt/ic26/services/market-analysis/data/ 와 /opt/ic26/source-downloads/ 를 지우지 않는다.
set -euo pipefail

APP_DIR=/opt/ic26
MARKET_DIR=$APP_DIR/services/market-analysis
DATA_DIR=$MARKET_DIR/data
SRCDL_DIR=$APP_DIR/source-downloads
ENV_FILE=/etc/ic26/env
UNIT=ic26-market
# 팀이 확인한 자료 묶음 (11/16 김진수 님, PR #62). 이름이 같은데 해시가 다르면 멈춘다.
KNOWN_SHA256="seoul-market-data-20261116.tar.gz=5fac10d2d4c8bd3c9a10958dc0cf0690e2e1c4e5224d4a228a3c0648fe0d778d"

die() { echo "오류: $*" >&2; exit 1; }
warn() { echo "주의: $*" >&2; }
step() { echo; echo "[$1] $2"; }

ARCHIVE=""; WANT_SHA=""; REPLACE=0; CHECK_ONLY=0; USE_SYSTEMD=1; DO_START=1
while [ $# -gt 0 ]; do
  case "$1" in
    --sha256) WANT_SHA="${2:-}"; shift ;;
    --replace) REPLACE=1 ;;
    --check) CHECK_ONLY=1 ;;
    --no-systemd) USE_SYSTEMD=0 ;;
    --no-start) DO_START=0 ;;
    -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    -*) die "모르는 옵션입니다: $1 (--help)" ;;
    *) [ -z "$ARCHIVE" ] || die "압축 파일은 하나만 줍니다"; ARCHIVE="$1" ;;
  esac
  shift
done

[ "$(id -u)" -eq 0 ] || die "root 권한이 필요합니다.  sudo bash $0 <자료 묶음.tar.gz>"
[ -n "$ARCHIVE" ] || die "자료 묶음 파일을 주세요.  sudo bash $0 ~/seoul-market-data-20261116.tar.gz"
[ -f "$ARCHIVE" ] || die "파일이 없습니다: $ARCHIVE"
ARCHIVE="$(cd "$(dirname "$ARCHIVE")" && pwd)/$(basename "$ARCHIVE")"
[ -f "$MARKET_DIR/app/intake_api.py" ] || die "$MARKET_DIR 에 상권 코드가 없습니다. install_was.sh 를 먼저 돌리세요."
PY=python3
command -v "$PY" >/dev/null 2>&1 || die "python3 가 없습니다"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || die "파이썬 3.11 이상이 필요합니다"

# ── 1. 압축 파일 ──
step 1/4 "압축 파일 확인: $ARCHIVE"
NAME="$(basename "$ARCHIVE")"
GOT_SHA="$(sha256sum "$ARCHIVE" | cut -d' ' -f1)"
SHA_FROM=""
if [ -n "$WANT_SHA" ]; then SHA_FROM="--sha256"
elif [ -f "$ARCHIVE.sha256" ]; then WANT_SHA="$(cut -d' ' -f1 < "$ARCHIVE.sha256")"; SHA_FROM="$NAME.sha256"
else
  for pair in $KNOWN_SHA256; do [ "${pair%%=*}" = "$NAME" ] && { WANT_SHA="${pair#*=}"; SHA_FROM="알려진 값"; }; done
fi
echo "SHA-256: $GOT_SHA"
if [ -n "$WANT_SHA" ]; then
  [ "$GOT_SHA" = "$(printf '%s' "$WANT_SHA" | tr 'A-F' 'a-f')" ] || die "SHA-256 이 다릅니다 (기대: $WANT_SHA, $SHA_FROM). 파일이 깨졌거나 다른 묶음입니다."
  echo "SHA-256 일치 ($SHA_FROM)"
else
  warn "대조할 SHA-256 이 없습니다 (--sha256 이나 $NAME.sha256). 아래 MANIFEST 대조만 합니다."
fi

# 풀 곳: /opt/ic26 과 같은 디스크 (옮길 때 복사하지 않고 이름만 바꾸게). 끝나면 지운다.
install -d -m 700 -o root -g root "$APP_DIR/.market-data-work"
WORK="$(mktemp -d "$APP_DIR/.market-data-work/run.XXXXXX")"
cleanup() { rm -rf "$WORK"; rmdir "$APP_DIR/.market-data-work" 2>/dev/null || true; }
trap cleanup EXIT

# 멤버 검사 + 크기 합 (풀기 전에). 보통 파일과 폴더만, 안전한 상대 경로만 허용한다.
NEED_BYTES="$("$PY" -I - "$ARCHIVE" <<'EOF'
import sys, tarfile
from pathlib import PurePosixPath
bad, total, files = [], 0, 0
with tarfile.open(sys.argv[1], "r:gz") as tar:
    for m in tar:
        p = PurePosixPath(m.name)
        if m.name.startswith("/") or ".." in p.parts or not (m.isfile() or m.isdir()):
            bad.append(m.name)
        elif m.isfile():
            total += m.size; files += 1
if bad:
    print("위험하거나 보통 파일이 아닌 멤버: " + ", ".join(bad[:5]), file=sys.stderr); sys.exit(3)
print(total, files)
EOF
)" || die "압축 파일 안에 받아들일 수 없는 멤버가 있습니다 (위 내용). 묶음을 다시 받으세요."
read -r NEED FILES <<<"$NEED_BYTES"
AVAIL="$(df -P -B1 "$APP_DIR" | awk 'NR==2 {print $4}')"
echo "파일 ${FILES}개, 풀면 $((NEED / 1024 / 1024))MB. $APP_DIR 디스크 여유 $((AVAIL / 1024 / 1024))MB"
[ "$AVAIL" -gt $((NEED + NEED / 5 + 200 * 1024 * 1024)) ] || die "디스크 여유가 모자랍니다 (풀 크기 + 20% + 200MB 가 필요)"

# ── 2. 풀고 MANIFEST 대조 ──
step 2/4 "풀기와 MANIFEST 대조"
"$PY" -I - "$ARCHIVE" "$WORK/x" <<'EOF'
import hashlib, json, os, sys, tarfile
archive, dest = sys.argv[1], sys.argv[2]
os.makedirs(dest)
with tarfile.open(archive, "r:gz") as tar:
    tar.extractall(dest, filter="data")          # 위에서 멤버를 이미 걸렀지만, 파이썬의 안전 필터도 함께 쓴다
man_path = os.path.join(dest, "MANIFEST.json")
if not os.path.isfile(man_path):
    sys.exit("MANIFEST.json 이 없습니다")
files = json.load(open(man_path, encoding="utf-8"))["files"]
items = files.items() if isinstance(files, dict) else [(f["path"], f) for f in files]
listed, bad = set(), []
for path, meta in items:
    listed.add(path)
    full = os.path.join(dest, path)
    if not os.path.isfile(full):
        bad.append(f"없음 {path}"); continue
    h = hashlib.sha256()
    with open(full, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    size = os.path.getsize(full)
    if meta.get("sha256") != h.hexdigest() or int(meta.get("bytes", meta.get("size", size))) != size:
        bad.append(f"다름 {path}")
actual = {os.path.relpath(os.path.join(d, f), dest) for d, _, fs in os.walk(dest) for f in fs}
extra = sorted(actual - listed - {"MANIFEST.json"})
if extra:
    bad += [f"목록에 없음 {p}" for p in extra]
if bad:
    print("\n".join(bad[:10]), file=sys.stderr)
    sys.exit(f"MANIFEST 와 맞지 않는 파일 {len(bad)}개")
print(f"MANIFEST 대조: {len(listed)}개 모두 바이트 수·SHA-256 일치")
EOF
X="$WORK/x"
[ -f "$X/services/market-analysis/data/official/onboarding_analysis_catalog.json" ] \
  || die "자료 묶음에 분석 카탈로그(services/market-analysis/data/official/onboarding_analysis_catalog.json)가 없습니다"
[ -d "$X/services/market-analysis/data/raw/official" ] || die "자료 묶음에 원본 폴더(services/market-analysis/data/raw/official)가 없습니다"
echo "원본(data/raw/official) 파일: $(find "$X/services/market-analysis/data/raw/official" -type f | wc -l)개"
find "$X/services/market-analysis/data/assistant_context" -type f -printf '보조자료: %f\n' 2>/dev/null | sort || true

# 코드 묶음에도 있는 파일: 내용이 같으면 코드 쪽을 둔다 (줄바꿈만 다를 수 있음)
CODE_MISMATCH=0
while IFS= read -r rel; do
  [ -n "$rel" ] || continue
  if [ ! -f "$APP_DIR/$rel" ]; then
    # 코드 쪽에 있어야 할 파일이 없다 (옛 묶음 등). 이번에는 자료 묶음 것을 두지만 다음 install_was.sh 가 지운다
    [ "$CHECK_ONLY" = 1 ] || install -D -m 644 -o root -g root "$X/$rel" "$APP_DIR/$rel"
    warn "코드 묶음에 없는 파일이라 자료 묶음 것을 둡니다 (다음 install_was.sh 때 지워짐): $rel"; continue
  fi
  if "$PY" -I -c 'import sys; a, b = (open(p, "rb").read().replace(b"\r\n", b"\n") for p in sys.argv[1:3]); sys.exit(0 if a == b else 1)' \
       "$X/$rel" "$APP_DIR/$rel"; then
    echo "코드와 같음 (그대로 둠): $rel"
  else
    warn "코드 묶음의 $rel 과 내용이 다릅니다. 코드 쪽을 그대로 둡니다 (상권 파트에 확인)"; CODE_MISMATCH=1
  fi
done < <(cd "$X" && { find services/market-analysis/app -type f 2>/dev/null; find data -type f 2>/dev/null; } | sort)

# 이미 깔린 자료와 비교: 새 파일, 같은 파일, 내용이 다른 파일
read -r SAME DIFF NEW OLDONLY <<<"$("$PY" -I - "$X/services/market-analysis/data" "$DATA_DIR" <<'EOF'
import filecmp, os, sys
src, dst = sys.argv[1], sys.argv[2]
same = diff = new = 0
names = set()
for d, _, fs in os.walk(src):
    for f in fs:
        rel = os.path.relpath(os.path.join(d, f), src); names.add(rel)
        target = os.path.join(dst, rel)
        if not os.path.exists(target): new += 1
        elif filecmp.cmp(os.path.join(src, rel), target, shallow=False): same += 1
        else: diff += 1
old_only = 0
if os.path.isdir(dst):
    for d, _, fs in os.walk(dst):
        old_only += sum(1 for f in fs if os.path.relpath(os.path.join(d, f), dst) not in names)
print(same, diff, new, old_only)
EOF
)"
[ -n "${OLDONLY:-}" ] || die "깔린 자료와 비교하지 못했습니다"
echo "지금 깔린 자료와 비교: 같음 ${SAME} · 다름 ${DIFF} · 새 파일 ${NEW} · 지금만 있음 ${OLDONLY}"
if [ "$DIFF" -gt 0 ] && [ "$REPLACE" = 0 ]; then
  die "이미 깔린 자료와 내용이 다른 파일이 ${DIFF}개 있습니다. 덮지 않았습니다. 옛 자료를 옮겨 두고 새로 깔려면 --replace"
fi

if [ "$CHECK_ONLY" = 1 ]; then
  echo; echo "확인만 했습니다 (--check). 깔지 않았습니다."; exit 0
fi

# ── 3. 배치 ──
step 3/4 "제자리에 배치"
fix_perms() { chown -R root:root "$1"; find "$1" -type d -exec chmod 755 {} +; find "$1" -type f -exec chmod 644 {} +; }
fix_perms "$X/services/market-analysis/data"
[ -d "$X/source-downloads" ] && fix_perms "$X/source-downloads"
STAMP="$(date +%Y%m%d-%H%M%S)"
if [ ! -d "$DATA_DIR" ] || [ -z "$(ls -A "$DATA_DIR" 2>/dev/null)" ]; then
  rmdir "$DATA_DIR" 2>/dev/null || true
  mv "$X/services/market-analysis/data" "$DATA_DIR"
  echo "새로 깔았음: $DATA_DIR"
elif [ "$REPLACE" = 1 ] && { [ "$DIFF" -gt 0 ] || [ "$OLDONLY" -gt 0 ]; }; then
  mv "$DATA_DIR" "$MARKET_DIR/data.bak-$STAMP"
  mv "$X/services/market-analysis/data" "$DATA_DIR"
  echo "옛 자료를 $MARKET_DIR/data.bak-$STAMP 로 옮기고 새로 깔았음 (--replace). 확인이 끝나면 옛 폴더를 지워도 됩니다"
else
  # 다른 파일이 없다: 빠진 파일만 더한다 (같은 파일은 그대로)
  (cd "$X/services/market-analysis/data" && find . -type f -print0) | while IFS= read -r -d '' f; do
    [ -e "$DATA_DIR/$f" ] || { install -d -m 755 -o root -g root "$DATA_DIR/$(dirname "$f")"; install -m 644 -o root -g root "$X/services/market-analysis/data/$f" "$DATA_DIR/$f"; }
  done
  echo "이미 같은 자료가 있었음. 빠진 파일 ${NEW}개만 더했음"
fi
fix_perms "$DATA_DIR"
if [ -d "$X/source-downloads" ]; then
  [ -d "$SRCDL_DIR" ] && mv "$SRCDL_DIR" "$WORK/old-source-downloads"
  mv "$X/source-downloads" "$SRCDL_DIR"
  echo "가공 전 원본: $SRCDL_DIR ($(find "$SRCDL_DIR" -type f | wc -l)개)"
fi
echo "상권 자료: $DATA_DIR ($(find "$DATA_DIR" -type f | wc -l)개, $(du -sh "$DATA_DIR" | cut -f1))"
# 어느 묶음을 깔았는지 (자료 폴더 밖에 둔다: 다음 비교에서 '지금만 있음'으로 세지 않게)
install -d -m 750 /var/lib/ic26
{ echo "archive=$NAME"; echo "sha256=$GOT_SHA"; echo "installed_at=$(date -Iseconds)"; } > /var/lib/ic26/market-data.installed
chmod 644 /var/lib/ic26/market-data.installed
echo "기록: /var/lib/ic26/market-data.installed"

# ── 4. 서비스 ──
step 4/4 "상권 서비스 ($UNIT)"
if [ -r "$ENV_FILE" ]; then
  # 이름만 본다. 값은 읽어 출력하지 않는다.
  grep -q '^ASSISTANT_ENABLED=1' "$ENV_FILE" || warn "$ENV_FILE 에 ASSISTANT_ENABLED=1 이 없습니다. 서랍에 '챗봇이 꺼져 있어요'가 뜹니다"
  grep -q '^ASSISTANT_PLANNER=off' "$ENV_FILE" || warn "$ENV_FILE 에 ASSISTANT_PLANNER=off 가 없습니다 (계획기가 기간을 지어내는 문제, deploy/README.md 10절)"
  grep -q '^APP_PUBLIC_ORIGIN=.' "$ENV_FILE" && warn "$ENV_FILE 에 APP_PUBLIC_ORIGIN 이 있습니다. 비서 화면 서버의 요청(Host: 127.0.0.1:8766)이 거절됩니다. 지우세요"
  if grep -q '^APP_MODE=live' "$ENV_FILE"; then
    grep -q '^CLOVA_STUDIO_API_KEY=.' "$ENV_FILE" && echo "CLOVA_STUDIO_API_KEY: 값 있음" \
      || warn "APP_MODE=live 인데 CLOVA_STUDIO_API_KEY 가 비어 있습니다 (상권 챗봇이 읽는 이름)"
  fi
else
  warn "$ENV_FILE 이 없습니다. install_was.sh 를 먼저 돌리세요"
fi

health() {
  for _ in $(seq 1 "${1:-60}"); do
    curl -fsS -m 3 -H 'Host: 127.0.0.1:8766' -o /dev/null http://127.0.0.1:8766/health 2>/dev/null && return 0
    sleep 1
  done
  return 1
}
if [ "$USE_SYSTEMD" = 0 ] || [ "$DO_START" = 0 ]; then
  echo "서비스는 건드리지 않았습니다 ($([ "$USE_SYSTEMD" = 0 ] && echo --no-systemd || echo --no-start))."
  echo "상권 서비스는 켜질 때 자료를 읽습니다. 이미 떠 있다면 다시 시작해야 새 자료를 봅니다."
else
  [ -f "/etc/systemd/system/$UNIT.service" ] || die "/etc/systemd/system/$UNIT.service 가 없습니다. install_was.sh 를 먼저 돌리세요"
  systemctl enable "$UNIT.service" >/dev/null 2>&1 || true
  systemctl restart "$UNIT.service"
  if health 60; then
    echo "$UNIT: $(systemctl is-active "$UNIT.service"), /health 200"
  else
    die "$UNIT 이 60초 안에 /health 에 답하지 않았습니다.  journalctl -u $UNIT -n 50"
  fi
fi

# 자료 준비 상태 (서비스가 떠 있을 때만): 상권 서비스의 분석 선택 목록이 자료를 보는지
if health 2; then
  "$PY" -I - <<'EOF' || warn "자료 준비 상태를 확인하지 못했습니다 (위 내용)"
import json, urllib.request
req = urllib.request.Request("http://127.0.0.1:8766/api/assistant/status", headers={"Host": "127.0.0.1:8766"})
with urllib.request.urlopen(req, timeout=10) as r:
    d = json.loads(r.read())
print(f"상권 챗봇: enabled={d.get('enabled')} model_connected={d.get('model_connected')}")
EOF
  echo "비서 화면 서버를 거친 서랍 상태:  curl -s http://127.0.0.1:8000/api/assistant/status   (\"state\":\"ready\" 이면 됨)"
fi

echo
echo "끝났습니다. 자료 묶음 $NAME"
[ "$CODE_MISMATCH" = 0 ] || warn "코드와 내용이 다른 자료 파일이 있었습니다 (위 주의). 코드 쪽을 그대로 두었습니다."
echo "확인:  bash $(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/smoke_test.sh --market"
