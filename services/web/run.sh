#!/usr/bin/env bash
# C7 한 화면 실행. 저장소 어디서든: services/web/run.sh
#   기본: 키 파일이 있으면 live, 없으면 mock
#   APP_MODE=live    HCX-005 실시간 (키 파일 필요, 호출마다 비용). 리뷰 분석(#14)도 live 로 띄움
#   APP_MODE=mock    키 없이 도는 시험용 실행 (키가 있어도 mock). 결과는 저장된 예시이고 실제 AI 결과가 아님
#   REVIEW_APP_MODE  리뷰 분석(#14)의 모드를 따로 정할 때. 기본은 APP_MODE 와 같음
#   맞춤 마케팅 서버(experiments/marketing, 127.0.0.1:8030)도 같이 띄운다 (11/16)
#     MARKETING_PORT        포트 (기본 8030)
#     MARKETING_APP_MODE    맞춤 마케팅의 모드를 따로 정할 때 (mock|live). 기본은 APP_MODE 와 같음
#     MARKETING_RECORDS_DIR 맞춤 마케팅 기록 폴더 (기본 experiments/marketing/data/marketing)
#     MARKETING_SURVEY_URL  비우면 띄운 서버 주소를 비서 화면에 넘김. off 면 띄우지 않고 비서 화면에도 off,
#                           다른 주소를 주면 띄우지 않고 그 주소를 그대로 넘김
#   화면(services/web/frontend, React + Vite)은 빌드가 없거나 소스보다 오래되었으면 띄우기 전에 다시 빌드한다 (npm 필요)
#     WEB_FRONTEND_DIST     다른 빌드 폴더를 쓸 때 (주면 자동 빌드를 하지 않음)
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
MARKETING_PORT="${MARKETING_PORT:-8030}"
# 맞춤 마케팅: MARKETING_SURVEY_URL 이 비어 있을 때만 이 스크립트가 서버를 띄운다 (off 면 끔, 다른 주소면 그 서버를 씀)
MARKETING_LOCAL=0
if [ -z "${MARKETING_SURVEY_URL:-}" ]; then
  MARKETING_LOCAL=1
  MARKETING_SURVEY_URL="http://127.0.0.1:$MARKETING_PORT"
fi
export MARKETING_SURVEY_URL
export MARKETING_APP_MODE="${MARKETING_APP_MODE:-$APP_MODE}"
[ -n "${MARKETING_RECORDS_DIR:-}" ] && export MARKETING_RECORDS_DIR="$(abspath "$MARKETING_RECORDS_DIR")"

# 화면 빌드: dist/index.html 이 없거나 소스(src·index.html·package*.json·vite.config.js)보다 오래되었으면 새로 빌드한다.
# node_modules 가 없거나 package-lock.json 보다 오래되었으면 npm ci 부터 한다. 빌드가 실패하면 서버를 띄우지 않는다
FRONT_DIR="$WEB_DIR/frontend"
if [ -z "${WEB_FRONTEND_DIST:-}" ] && [ -f "$FRONT_DIR/package.json" ]; then
  FRONT_INDEX="$FRONT_DIR/dist/index.html"
  STALE=""
  if [ ! -f "$FRONT_INDEX" ]; then
    STALE="빌드가 없음"
  elif [ -n "$(find "$FRONT_DIR/src" "$FRONT_DIR/index.html" "$FRONT_DIR/package.json" "$FRONT_DIR/package-lock.json" \
                 "$FRONT_DIR/vite.config.js" -newer "$FRONT_INDEX" -print -quit 2>/dev/null)" ]; then
    STALE="소스가 빌드보다 새로움"
  fi
  if [ -n "$STALE" ]; then
    command -v npm >/dev/null 2>&1 || { echo "화면을 빌드해야 하는데($STALE) npm 이 없습니다. Node.js 20 이상을 설치하세요."; exit 1; }
    echo "화면 빌드 ($STALE): $FRONT_DIR"
    (
      cd "$FRONT_DIR"
      if [ ! -d node_modules ] || [ package-lock.json -nt node_modules/.package-lock.json ]; then npm ci --no-audit --no-fund; fi
      npm run build --silent
    ) || { echo "화면 빌드에 실패했습니다. 위 오류를 확인하세요 ($FRONT_DIR)"; exit 1; }
  fi
fi

# 이미 떠 있는 서버가 있으면 그 서버의 응답을 성공으로 착각하므로, 시작 전에 멈춘다
port_free() { "$PY" -c "import socket,sys; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('127.0.0.1', int(sys.argv[1])))" "$1" 2>/dev/null; }
NEED_PORTS="$WEB_PORT"
[ "${WEB_REVIEW_SOURCE:-local}" != "remote" ] && NEED_PORTS="$REVIEW_PORT $WEB_PORT"
[ "$MARKETING_LOCAL" = 1 ] && NEED_PORTS="$NEED_PORTS $MARKETING_PORT"
for p in $NEED_PORTS; do
  if ! port_free "$p"; then
    echo "포트 $p 를 이미 다른 프로세스가 쓰고 있습니다. 앞서 띄운 서버를 Ctrl+C 로 끄고 다시 실행하세요."
    command -v lsof >/dev/null && lsof -nP -iTCP:"$p" -sTCP:LISTEN | tail -n +2 | awk '{print "  pid " $2 " (" $1 ")"}'
    exit 1
  fi
done

REVIEW_PID=""
MARKETING_PID=""
WEB_PID=""
cleanup() {
  [ -n "$WEB_PID" ] && kill "$WEB_PID" 2>/dev/null || true
  [ -n "$REVIEW_PID" ] && kill "$REVIEW_PID" 2>/dev/null || true
  [ -n "$MARKETING_PID" ] && kill "$MARKETING_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [ "${WEB_REVIEW_SOURCE:-local}" = "remote" ]; then
  : "${REVIEW_INSIGHT_URL:?WEB_REVIEW_SOURCE=remote 이면 REVIEW_INSIGHT_URL 이 필요합니다}"
  echo "리뷰 분석: 원격 서버를 씁니다 (토큰은 키 파일의 REVIEW_INSIGHT_TOKEN)"
else
  [ -d "$REVIEW_DIR/app" ] || { echo "리뷰 분석 서비스 폴더가 없습니다: $REVIEW_DIR (PR #14 병합 전이면 REVIEW_INSIGHT_DIR 를 지정)"; exit 1; }
  export REVIEW_INSIGHT_URL="http://127.0.0.1:$REVIEW_PORT"
  unset REVIEW_INSIGHT_TOKEN
  # exec: 괄호 안 셸 대신 uvicorn 이 이 PID 를 갖게 한다 (아니면 스크립트를 kill 했을 때 셸만 죽고 서버가 남았다, 11/16 확인)
  ( cd "$REVIEW_DIR" && exec env -u APP_ACCESS_TOKEN APP_MODE="$REVIEW_APP_MODE" \
      "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$REVIEW_PORT" --log-level warning ) &
  REVIEW_PID=$!
  if ! curl -s -o /dev/null --retry 30 --retry-connrefused --retry-delay 1 "$REVIEW_INSIGHT_URL/api/health"; then
    echo "리뷰 분석 서비스가 뜨지 않았습니다 ($REVIEW_INSIGHT_URL)"; exit 1
  fi
  echo "리뷰 분석(#14): $REVIEW_INSIGHT_URL (APP_MODE=$REVIEW_APP_MODE)"
fi

if [ "$MARKETING_LOCAL" = 1 ]; then
  [ -f "$MARKETING_DIR/marketing_survey/server.py" ] || {
    echo "맞춤 마케팅 서버 코드가 없습니다: $MARKETING_DIR/marketing_survey (끄고 실행하려면 MARKETING_SURVEY_URL=off)"; exit 1; }
  # exec: 괄호 안 셸 대신 uvicorn 이 이 PID 를 갖게 해서 cleanup 의 kill 이 서버에 바로 닿게 한다
  ( cd "$MARKETING_DIR" && exec env PYTHONPATH="$ROOT:$MARKETING_DIR" \
      "$PY" -m uvicorn marketing_survey.server:app --host 127.0.0.1 --port "$MARKETING_PORT" --log-level warning ) &
  MARKETING_PID=$!
  if ! curl -fs -o /dev/null --retry 30 --retry-connrefused --retry-delay 1 "$MARKETING_SURVEY_URL/health"; then
    echo "맞춤 마케팅 서버가 뜨지 않았습니다 ($MARKETING_SURVEY_URL). 끄고 실행하려면 MARKETING_SURVEY_URL=off"; exit 1
  fi
  echo "맞춤 마케팅: $MARKETING_SURVEY_URL (MARKETING_APP_MODE=$MARKETING_APP_MODE, 기록 ${MARKETING_RECORDS_DIR:-$MARKETING_DIR/data/marketing})"
elif [ "$MARKETING_SURVEY_URL" = off ]; then
  echo "맞춤 마케팅: 끔 (MARKETING_SURVEY_URL=off)"
else
  echo "맞춤 마케팅: 띄우지 않고 $MARKETING_SURVEY_URL 을 씁니다"
fi

echo "한 화면: http://localhost:$WEB_PORT  (APP_MODE=$APP_MODE)"
cd "$WEB_DIR"
# 비서 화면도 뒤에서 띄우고 기다린다(wait). 앞에서 띄우면 이 스크립트만 kill 했을 때 신호 처리(cleanup)가 화면 서버가
# 끝날 때까지 미뤄져 세 서버가 그대로 남았다 (11/16 확인). Ctrl+C 는 예전처럼 셋 다 끈다.
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" "$PY" -m uvicorn web.main:create_app --factory \
  --host 127.0.0.1 --port "$WEB_PORT" --log-level warning &
WEB_PID=$!
wait "$WEB_PID"
