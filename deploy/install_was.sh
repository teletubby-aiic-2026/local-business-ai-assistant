#!/usr/bin/env bash
# WAS 서버(Ubuntu 24.04)에 ic26 앱을 설치한다. 처음 설치와 코드 갱신에 같은 스크립트를 쓴다. 여러 번 돌려도 안전하다.
#
# 사용법 (서버에서. 묶음 tgz 를 푼 폴더 안의 스크립트를 root 로 실행):
#   tar -xzf ic26-<커밋>.tgz && sudo bash ic26-<커밋>/deploy/install_was.sh
# 옵션:
#   --no-systemd   서비스 등록과 시작을 건너뜀 (systemd 가 없는 컨테이너 시험용)
#   --no-start     서비스를 등록만 하고 시작·재시작하지 않음
#   --skip-apt     apt 설치를 건너뜀 (이미 설치했을 때)
#   --skip-pip     파이썬 패키지 설치를 건너뜀 (코드만 바뀌었을 때)
#
# 하는 일
#   1 패키지(python3-venv, rsync, postgresql-client 등)  2 실행 계정 ic26  3 코드를 /opt/ic26 에 맞춤
#   4 쓰기 폴더  5 환경 파일 틀(/etc/ic26/env, 없을 때만)  6 venv 와 requirements  7 서비스 등록
# 서비스: ic26-review(8020) · ic26-was(8000) · ic26-marketing(맞춤 마케팅, 127.0.0.1:8030) 를 켠다.
#   ic26-market(상권, 127.0.0.1:8766)은 상권 공식 자료가 깔려 있으면 함께 켜고(다시 시작), 없으면 파일만 넣는다.
#   자료는 코드 묶음에 없다. 따로 받은 자료 묶음을 install_market_data.sh 로 깐다 (그 스크립트가 ic26-market 도 켬).
# 하지 않는 일: 키·비밀번호를 쓰거나 읽어 출력하는 일, 상권 자료 깔기, 로드 밸런서 설정
# 갱신 때 건드리지 않는 것: /etc/ic26/env, /opt/ic26/.venv, 쓰기 폴더 안의 내용(붙여넣은 리뷰, 로그, 승인 기록, 상권 DB, 마케팅 기록),
#   상권 자료(/opt/ic26/services/market-analysis/data/, /opt/ic26/source-downloads/)
set -euo pipefail

APP_USER=ic26
APP_DIR=/opt/ic26
ENV_DIR=/etc/ic26
ENV_FILE=$ENV_DIR/env
STATE_DIR=/var/lib/ic26
UNITS=(ic26-review ic26-was ic26-market ic26-marketing)   # market 은 상권 자료가 있을 때만 enable 한다 (아래 7)
ENABLED_UNITS=(ic26-review ic26-marketing ic26-was)      # 켜는 서비스 (마케팅을 화면 서버보다 먼저 시작)

die() { echo "오류: $*" >&2; exit 1; }
warn() { echo "주의: $*" >&2; }
step() { echo; echo "[$1] $2"; }

USE_SYSTEMD=1; DO_START=1; DO_APT=1; DO_PIP=1
while [ $# -gt 0 ]; do
  case "$1" in
    --no-systemd) USE_SYSTEMD=0 ;;
    --no-start) DO_START=0 ;;
    --skip-apt) DO_APT=0 ;;
    --skip-pip) DO_PIP=0 ;;
    -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *) die "모르는 옵션입니다: $1 (--help)" ;;
  esac
  shift
done

[ "$(id -u)" -eq 0 ] || die "root 권한이 필요합니다.  sudo bash $0"

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$SRC/services/web/web/main.py" ] && [ -f "$SRC/services/review-insight/app/main.py" ] \
  || die "묶음을 푼 폴더가 아닙니다 ($SRC). tgz 를 풀고 그 안의 deploy/install_was.sh 를 실행하세요."
[ -f "$SRC/deploy/env.example" ] || die "$SRC/deploy/env.example 이 없습니다"
case "$SRC/" in "$APP_DIR"/?*) die "묶음을 $APP_DIR 안에 풀지 마세요 (예: ~/ic26-src 에 풀기)";; esac

REV="$(head -n1 "$SRC/REVISION" 2>/dev/null || true)"
[ -n "$REV" ] || { warn "REVISION 파일이 없습니다. make_bundle.sh 로 만든 묶음인지 확인하세요."; REV=unknown; }
echo "설치할 커밋: $REV"
echo "묶음 위치:   $SRC"

# ── 환경 확인 ──
OS_ID=""; OS_VER=""
if [ -r /etc/os-release ]; then OS_ID="$(. /etc/os-release; echo "${ID:-}")"; OS_VER="$(. /etc/os-release; echo "${VERSION_ID:-}")"; fi
if [ "$OS_ID" != ubuntu ] || [ "$OS_VER" != "24.04" ]; then
  warn "Ubuntu 24.04 에서 시험했습니다 (지금: ${OS_ID:-?} ${OS_VER:-?}). 파이썬 3.12 기준입니다."
fi
if [ "$USE_SYSTEMD" = 1 ]; then
  command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ] \
    || die "systemd 로 돌고 있지 않습니다. 컨테이너라면 --no-systemd 를 붙이세요."
fi

# ── 1. 패키지 ──
step 1/7 "패키지"
if [ "$DO_APT" = 1 ]; then
  export DEBIAN_FRONTEND=noninteractive
  echo "apt 로 설치합니다 (1~2분 걸릴 수 있음)"
  apt-get -qq update
  apt-get -qq install -y --no-install-recommends ca-certificates curl rsync python3 python3-venv postgresql-client tzdata
else
  echo "건너뜀 (--skip-apt)"
fi
PY="${PYTHON_BIN:-python3}"
command -v "$PY" >/dev/null 2>&1 || die "$PY 가 없습니다 (apt 설치를 건너뛰었나요?)"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || die "파이썬 3.11 이상이 필요합니다 ($("$PY" -V 2>&1))"
"$PY" -c 'import venv, ensurepip' 2>/dev/null || die "python3-venv 가 없습니다 (apt install python3-venv)"
echo "파이썬: $("$PY" -V 2>&1)"
if [ "$USE_SYSTEMD" = 1 ] && command -v timedatectl >/dev/null 2>&1; then
  timedatectl set-timezone Asia/Seoul || warn "시간대를 Asia/Seoul 로 바꾸지 못했습니다"
fi
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi '^Status: active'; then
  warn "ufw 가 켜져 있습니다. 8000번이 막힐 수 있습니다. 서버 접근은 ACG 로 막으므로 'sudo ufw disable' 을 검토하세요."
fi

# ── 2. 실행 계정 ──
step 2/7 "실행 계정 $APP_USER"
if id -u "$APP_USER" >/dev/null 2>&1; then
  echo "이미 있음"
else
  useradd --system --user-group --home-dir "$APP_DIR" --no-create-home --shell /usr/sbin/nologin "$APP_USER"
  echo "만들었음"
fi

# ── 3. 코드 ──
step 3/7 "코드를 $APP_DIR 에 맞춤"
command -v rsync >/dev/null 2>&1 || die "rsync 가 없습니다 (--skip-apt 를 썼다면 apt install rsync)"
install -d -m 755 -o root -g root "$APP_DIR"
if [ "$SRC" = "$APP_DIR" ]; then
  echo "묶음이 $APP_DIR 안에 있어 코드 맞추기를 건너뜁니다"
else
  # 코드는 root 소유로 둔다 (서비스 계정이 코드를 고치지 못하게).
  # P(protect) 규칙: 서버에서 생긴 폴더와 파일은 갱신해도 지우지 않는다. 묶음에 같은 경로의 파일이 있으면 그 파일은 새로 덮는다.
  rsync -a --delete --chown=root:root --chmod=u=rwX,go=rX \
    --filter='P /.venv/' \
    --filter='P /services/review-insight/logs/' \
    --filter='P /services/review-insight/data/runtime/' \
    --filter='P /services/web/data/runtime/' \
    --filter='P /experiments/marketing/results/' \
    --filter='P /services/market-analysis/data/' \
    --filter='P /services/market-analysis/data.bak-*/' \
    --filter='P /source-downloads/' \
    --filter='P /.market-data-work/' \
    --filter='P .env' \
    "$SRC"/ "$APP_DIR"/
fi
[ -f "$APP_DIR/REVISION" ] || printf '%s\n' "$REV" > "$APP_DIR/REVISION"
echo "REVISION: $(head -n1 "$APP_DIR/REVISION")"

# ── 4. 쓰기 폴더 ──
step 4/7 "쓰기 폴더"
# 리뷰 분석: 사용량 기록(logs), 붙여넣은 리뷰와 그 분류(data/runtime), 샘플 분류 저장본(data/replay, live 일 때 갱신)
# C6 글 생성: live 일 때 모델의 원문 응답을 experiments/marketing/results/ 에 남긴다 (코드가 그 폴더에 씀. 없으면 글 생성이 오류)
mkw() { install -d -m "$1" -o "$APP_USER" -g "$APP_USER" "$APP_DIR/$2"; chown -R "$APP_USER:$APP_USER" "$APP_DIR/$2"; echo "  $APP_DIR/$2"; }
mkw 755 services/review-insight/logs
mkw 750 services/review-insight/data/runtime
mkw 755 services/review-insight/data/replay
mkw 750 experiments/marketing/results
# 비서 화면의 실행 중 폴더(WEB_RUNTIME_DIR, 승인 기록 approvals.jsonl)와 상권 서비스의 SQLite 폴더, 맞춤 마케팅 기록 폴더
install -d -m 750 -o "$APP_USER" -g "$APP_USER" "$STATE_DIR" "$STATE_DIR/runtime" "$STATE_DIR/market" "$STATE_DIR/marketing"
echo "  $STATE_DIR/runtime  (WEB_RUNTIME_DIR)"
echo "  $STATE_DIR/market   (상권 대화 기록 SQLite)"
echo "  $STATE_DIR/marketing (MARKETING_RECORDS_DIR, 맞춤 마케팅 기록 — 방문자마다 파일 하나)"

# ── 5. 환경 파일 ──
step 5/7 "환경 파일 $ENV_FILE"
install -d -m 700 -o root -g root "$ENV_DIR"
if [ -e "$ENV_FILE" ]; then
  chown root:root "$ENV_FILE"; chmod 600 "$ENV_FILE"
  echo "이미 있음. 그대로 둡니다 (소유자 root, 권한 600으로 맞춤)"
else
  install -m 600 -o root -g root "$SRC/deploy/env.example" "$ENV_FILE"
  echo "틀을 만들었음. 값은 비어 있습니다. 편집기로 직접 넣으세요:  sudo vi -n -i NONE $ENV_FILE"
fi
# 이름만 확인한다. 값은 읽어 출력하지 않는다.
missing=()
while IFS= read -r name; do
  grep -q "^${name}=" "$ENV_FILE" || missing+=("$name")
done < <(sed -n 's/^\([A-Z][A-Z0-9_]*\)=.*/\1/p' "$SRC/deploy/env.example")
if [ "${#missing[@]}" -gt 0 ]; then
  warn "환경 파일에 없는 변수가 있습니다 (틀에는 있음): ${missing[*]}  → 편집기로 줄을 추가하세요"
fi
mode_line="$(sed -n 's/^APP_MODE=//p' "$ENV_FILE" | tail -n1 | tr -d '[:space:]')"
echo "APP_MODE: ${mode_line:-(비어 있음 → mock 으로 돎)}"
if [ "$mode_line" = live ]; then
  for k in CLOVA_API_KEY CLOVASTUDIO_API_KEY CLOVA_STUDIO_API_KEY; do
    grep -q "^${k}=." "$ENV_FILE" && echo "  $k: 값 있음" || echo "  $k: 비어 있음  ← live 에서는 채워야 합니다"
  done
fi

# ── 6. 파이썬 환경 ──
step 6/7 "파이썬 환경 $APP_DIR/.venv"
if [ "$DO_PIP" = 1 ]; then
  [ -x "$APP_DIR/.venv/bin/python" ] || "$PY" -m venv "$APP_DIR/.venv"
  reqs=(-r "$APP_DIR/services/web/requirements.txt" -r "$APP_DIR/services/review-insight/requirements.txt")
  # 맞춤 마케팅 서버(ic26-marketing)는 fastapi·uvicorn·pydantic 만 쓴다 — 위 두 파일에 이미 들어 있다.
  # experiments/marketing/requirements.txt 는 넣지 않는다: 개발용 데모 화면(demo_app.py)의 streamlit 이 들어 있어 무겁고(수십 MB,
  # 의존성 수십 개) 서버에서는 쓰지 않는다. 아래 'import 확인'이 빠진 패키지를 알려 준다.
  # 상권 서비스 코드가 묶음에 들어 있으면 그 requirements 도 설치한다 (서비스는 켜지 않음)
  for r in services/market-analysis/requirements.txt services/market-analysis/requirements-assistant.txt; do
    if [ -f "$APP_DIR/$r" ]; then reqs+=(-r "$APP_DIR/$r"); echo "상권 서비스 requirements 포함: $r"; fi
  done
  "$APP_DIR/.venv/bin/pip" install --disable-pip-version-check --no-input -q "${reqs[@]}"
  "$APP_DIR/.venv/bin/python" - <<'EOF'
from importlib.metadata import PackageNotFoundError, version


def shown(name):
    try:
        return f"{name} {version(name)}"
    except PackageNotFoundError:
        return f"{name} 없음"


# psycopg 는 DB 를 쓸 때만 필요하다 (DB 코드가 없는 옛 커밋의 묶음에는 없음)
print("설치됨:", ", ".join(shown(n) for n in ("fastapi", "uvicorn", "httpx", "kiwipiepy", "psycopg")))
EOF
else
  [ -x "$APP_DIR/.venv/bin/python" ] || die ".venv 가 없습니다 (--skip-pip 를 처음 설치에 쓸 수 없습니다)"
  echo "건너뜀 (--skip-pip)"
fi
# 맞춤 마케팅 서버가 이 venv 로 import 되는지 (서비스 파일과 같은 PYTHONPATH·폴더. 키를 읽지 않고 파일을 쓰지 않음)
if (cd "$APP_DIR/experiments/marketing" && env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$APP_DIR:$APP_DIR/experiments/marketing" \
      "$APP_DIR/.venv/bin/python" -c 'import marketing_survey.server' >/dev/null 2>&1); then
  echo "맞춤 마케팅 서버 import: 됨"
else
  warn "맞춤 마케팅 서버(marketing_survey.server)를 import 하지 못했습니다. ic26-marketing 이 켜지지 않습니다 (비서 화면은 그대로 돎)."
fi

# ── 7. 서비스 ──
step 7/7 "서비스"
# 상권 공식 자료가 깔려 있는지 (install_market_data.sh 가 까는 분석 카탈로그와 원본 폴더)
MARKET_DATA=0
if [ -f "$APP_DIR/services/market-analysis/data/official/onboarding_analysis_catalog.json" ] \
   && [ -n "$(ls -A "$APP_DIR/services/market-analysis/data/raw/official" 2>/dev/null)" ]; then
  MARKET_DATA=1; echo "상권 공식 자료: 있음 → ic26-market 도 켭니다"
else
  echo "상권 공식 자료: 없음 → ic26-market 은 켜지 않습니다 (서랍에는 '상권 서비스에 연결하지 못했어요')"
fi
if [ "$USE_SYSTEMD" = 0 ]; then
  echo "건너뜀 (--no-systemd). 서비스 파일의 명령은 $SRC/deploy/systemd/ 에 있습니다."
  echo "  ic26-review · ic26-marketing · ic26-was 세 개를 그 파일의 계정(ic26)·폴더·PYTHONPATH·환경 변수로 직접 띄웁니다."
  if [ "$MARKET_DATA" = 1 ]; then echo "  상권 자료가 깔려 있으니 ic26-market 도 띄웁니다."; else echo "  ic26-market 은 상권 자료(install_market_data.sh)를 깐 뒤에 띄웁니다."; fi
else
  for u in "${UNITS[@]}"; do
    install -m 644 -o root -g root "$SRC/deploy/systemd/$u.service" "/etc/systemd/system/$u.service"
  done
  systemctl daemon-reload
  systemctl enable "${ENABLED_UNITS[@]/%/.service}"
  if [ "$MARKET_DATA" = 1 ]; then
    systemctl enable ic26-market.service
    echo "ic26-market: 상권 자료가 깔려 있어 enable 했습니다 ($(head -n1 /var/lib/ic26/market-data.installed 2>/dev/null || echo '자료 묶음 기록 없음'))"
  else
    echo "ic26-market 은 파일만 넣었고 켜지 않았습니다. 상권 자료 묶음을 받은 뒤: sudo bash $SRC/deploy/install_market_data.sh <seoul-market-data-….tar.gz>"
  fi
  if [ "$DO_START" = 1 ]; then
    systemctl restart ic26-review.service
    systemctl restart ic26-marketing.service
    systemctl restart ic26-was.service
    # 상권 서비스: 자료가 있으면 새 코드로 다시 시작 (자료가 없는데 이미 켜 두었다면 그것도 다시 시작)
    if [ "$MARKET_DATA" = 1 ] || systemctl is-active --quiet ic26-market.service; then systemctl restart ic26-market.service; fi
    for _ in $(seq 1 30); do
      curl -fsS -m 3 -o /dev/null http://127.0.0.1:8000/api/health 2>/dev/null && break
      sleep 1
    done
    for u in "${ENABLED_UNITS[@]}"; do printf '  %-15s %s\n' "$u" "$(systemctl is-active "$u.service" || true)"; done
    if [ "$MARKET_DATA" = 1 ]; then
      for _ in $(seq 1 30); do
        curl -fsS -m 3 -H 'Host: 127.0.0.1:8766' -o /dev/null http://127.0.0.1:8766/health 2>/dev/null && break
        sleep 1
      done
      printf '  %-15s %s\n' ic26-market "$(systemctl is-active ic26-market.service || true)"
    fi
  else
    echo "시작하지 않았습니다 (--no-start)"
  fi
fi

echo
echo "설치가 끝났습니다. 커밋 $REV"
if [ "$USE_SYSTEMD" = 1 ]; then
  echo "다음 할 일"
  echo "  1. 환경 파일에 값을 넣습니다 (처음 설치일 때):   sudo vi -n -i NONE $ENV_FILE"
  echo "  2. 서비스를 다시 시작합니다:                    sudo systemctl restart ic26-review ic26-marketing ic26-was$([ "$MARKET_DATA" = 1 ] && echo ' ic26-market')"
  [ "$MARKET_DATA" = 1 ] || echo "  (상권) 자료 묶음을 깝니다:                      sudo bash $SRC/deploy/install_market_data.sh <seoul-market-data-….tar.gz>"
  echo "  3. 확인합니다:                                  bash $SRC/deploy/smoke_test.sh"
fi
