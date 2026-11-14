#!/usr/bin/env bash
# C7 한 화면 실행. 저장소 어디서든: services/web/run.sh
#   기본: 키 파일이 있으면 live, 없으면 mock
#   APP_MODE=live    HCX-005 실시간 (키 파일 필요, 호출마다 비용). 리뷰 분석(#14)도 live 로 띄움
#   APP_MODE=mock    키 없이 도는 시험용 실행 (키가 있어도 mock). 결과는 저장된 예시이고 실제 AI 결과가 아님
#   REVIEW_APP_MODE  리뷰 분석(#14)의 모드를 따로 정할 때. 기본은 APP_MODE 와 같음
# 키는 저장소 밖 ~/.config/teletubby-aiic/env 에서만 읽고, 값을 화면에 찍지 않는다.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WEB_DIR="$ROOT/services/web"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"

WANT_MODE="${APP_MODE:-}"              # 명령줄에서 준 모드가 먼저. 비어 있으면 아래에서 키 파일 유무로 정함
case "$WANT_MODE" in
  ""|mock|live) ;;
  replay) echo "발표 모드(APP_MODE=replay)는 없어졌습니다. live 또는 mock을 쓰세요."; exit 1 ;;
  *) echo "APP_MODE는 live 또는 mock 이어야 합니다 (받은 값: $WANT_MODE)"; exit 1 ;;
esac
ENV_FILE="$HOME/.config/teletubby-aiic/env"
if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
  echo "키 파일을 읽었습니다: $ENV_FILE (값은 출력하지 않음)"
  if [ -z "$WANT_MODE" ]; then
    if [ -n "${CLOVA_API_KEY:-}${CLOVASTUDIO_API_KEY:-}" ]; then
      WANT_MODE=live; echo "APP_MODE 를 주지 않아 live 로 실행합니다 (키 파일이 있음). 키 없이 시험하려면 APP_MODE=mock"
    else
      WANT_MODE=mock; echo "키 파일에 HCX 키가 없어 mock(시험용 실행) 모드로 실행합니다"
    fi
  fi
elif [ "$WANT_MODE" = "live" ]; then
  echo "키 파일이 없어 live 대신 mock 모드로 실행합니다 ($ENV_FILE 이 없음)"
  WANT_MODE=mock
else
  echo "키 파일 없음 ($ENV_FILE). 키 없이 도는 mock(시험용 실행) 모드로 실행합니다."
  WANT_MODE=mock
fi
export APP_MODE="$WANT_MODE"
REVIEW_APP_MODE="${REVIEW_APP_MODE:-$APP_MODE}"   # 리뷰 분석(#14)도 기본은 같은 모드. 따로 정하려면 REVIEW_APP_MODE
# 같은 HCX 키를 두 이름으로: #14 는 CLOVASTUDIO_API_KEY, #16 은 CLOVA_API_KEY
if [ -n "${CLOVASTUDIO_API_KEY:-}" ] && [ -z "${CLOVA_API_KEY:-}" ]; then export CLOVA_API_KEY="$CLOVASTUDIO_API_KEY"; fi
if [ -n "${CLOVA_API_KEY:-}" ] && [ -z "${CLOVASTUDIO_API_KEY:-}" ]; then export CLOVASTUDIO_API_KEY="$CLOVA_API_KEY"; fi

# 병합 전에는 각 PR 의 worktree 를 가리키게 바꿀 수 있다 (README '병합 전' 참고)
# 아래에서 services/web 으로 cd 하므로, 상대 경로는 지금 위치 기준 절대 경로로 바꿔 둔다
abspath() { case "$1" in /*) printf '%s' "$1" ;; *) printf '%s/%s' "$PWD" "$1" ;; esac; }
REVIEW_DIR="$(abspath "${REVIEW_INSIGHT_DIR:-$ROOT/services/review-insight}")"
export MARKETING_DIR="$(abspath "${MARKETING_DIR:-$ROOT/experiments/marketing}")"
export SNAPSHOT_PATH="$(abspath "${SNAPSHOT_PATH:-$ROOT/data/scenario/snapshot_2026Q2.json}")"
[ -n "${WEB_RUNTIME_DIR:-}" ] && export WEB_RUNTIME_DIR="$(abspath "$WEB_RUNTIME_DIR")"
[ -d "$MARKETING_DIR/c6" ] || echo "주의: C6 폴더가 없습니다 ($MARKETING_DIR/c6). ③ 생성이 막힙니다"
[ -f "$SNAPSHOT_PATH" ] || echo "주의: 상권 지표 파일이 없습니다 ($SNAPSHOT_PATH). 카드 ⓑ 가 뜨지 않습니다"
REVIEW_PORT="${REVIEW_PORT:-8020}"
WEB_PORT="${WEB_PORT:-8000}"

# 이미 떠 있는 서버가 있으면 그 서버의 응답을 성공으로 착각하므로, 시작 전에 멈춘다
port_free() { "$PY" -c "import socket,sys; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('127.0.0.1', int(sys.argv[1])))" "$1" 2>/dev/null; }
NEED_PORTS="$WEB_PORT"
[ "${WEB_REVIEW_SOURCE:-local}" != "remote" ] && NEED_PORTS="$REVIEW_PORT $WEB_PORT"
for p in $NEED_PORTS; do
  if ! port_free "$p"; then
    echo "포트 $p 를 이미 다른 프로세스가 쓰고 있습니다. 앞서 띄운 서버를 Ctrl+C 로 끄고 다시 실행하세요."
    command -v lsof >/dev/null && lsof -nP -iTCP:"$p" -sTCP:LISTEN | tail -n +2 | awk '{print "  pid " $2 " (" $1 ")"}'
    exit 1
  fi
done

REVIEW_PID=""
cleanup() { [ -n "$REVIEW_PID" ] && kill "$REVIEW_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

if [ "${WEB_REVIEW_SOURCE:-local}" = "remote" ]; then
  : "${REVIEW_INSIGHT_URL:?WEB_REVIEW_SOURCE=remote 이면 REVIEW_INSIGHT_URL 이 필요합니다}"
  echo "리뷰 분석: 원격 서버를 씁니다 (토큰은 키 파일의 REVIEW_INSIGHT_TOKEN)"
else
  [ -d "$REVIEW_DIR/app" ] || { echo "리뷰 분석 서비스 폴더가 없습니다: $REVIEW_DIR (PR #14 병합 전이면 REVIEW_INSIGHT_DIR 를 지정)"; exit 1; }
  export REVIEW_INSIGHT_URL="http://127.0.0.1:$REVIEW_PORT"
  unset REVIEW_INSIGHT_TOKEN
  ( cd "$REVIEW_DIR" && env -u APP_ACCESS_TOKEN APP_MODE="$REVIEW_APP_MODE" \
      "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$REVIEW_PORT" --log-level warning ) &
  REVIEW_PID=$!
  if ! curl -s -o /dev/null --retry 30 --retry-connrefused --retry-delay 1 "$REVIEW_INSIGHT_URL/api/health"; then
    echo "리뷰 분석 서비스가 뜨지 않았습니다 ($REVIEW_INSIGHT_URL)"; exit 1
  fi
  echo "리뷰 분석(#14): $REVIEW_INSIGHT_URL (APP_MODE=$REVIEW_APP_MODE)"
fi

echo "한 화면: http://localhost:$WEB_PORT  (APP_MODE=$APP_MODE)"
cd "$WEB_DIR"
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" "$PY" -m uvicorn web.main:create_app --factory \
  --host 127.0.0.1 --port "$WEB_PORT" --log-level warning
