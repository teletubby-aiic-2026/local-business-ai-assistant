#!/usr/bin/env bash
# 서버 이미지를 만들기 전에 이 서버에서 비밀 값과 실행 중 데이터를 비운다.
# 이미지에는 /etc/ic26/env 와 서버 안의 파일이 그대로 담긴다. 비우지 않으면 키가 이미지에 남는다.
#
# 사용법 (WAS 서버에서, 이미지를 만들기 직전에):
#   sudo bash /opt/ic26/deploy/prepare_image.sh
# 옵션:
#   --no-systemd   서비스를 멈추지 않음 (컨테이너 시험용)
#
# 하는 일
#   1 ic26 서비스를 멈춘다 (실행 중에 파일이 다시 쓰이지 않게)
#   2 /etc/ic26/env 에서 이름에 KEY, PASSWORD, TOKEN, SECRET 이 들어간 줄의 값을 비운다 (변수 이름은 남김)
#   3 실행 중에 생긴 데이터를 지운다: 붙여넣은 리뷰와 분류 결과, 승인 기록, 사용량 기록, 모델 원문 응답, 상권 대화 기록
#   4 키가 남아 있을 만한 곳을 이름만 찾아 알려 준다 (값은 출력하지 않는다)
# 하지 않는 일: 서비스를 다시 시작하는 일, 이미지를 만드는 일(콘솔에서 사람이), 셸 히스토리 지우기(아래 안내)
set -euo pipefail

die() { echo "오류: $*" >&2; exit 1; }
warn() { echo "주의: $*" >&2; }

USE_SYSTEMD=1
while [ $# -gt 0 ]; do
  case "$1" in
    --no-systemd) USE_SYSTEMD=0 ;;
    -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *) die "모르는 옵션입니다: $1 (--help)" ;;
  esac
  shift
done
[ "$(id -u)" -eq 0 ] || die "root 권한이 필요합니다.  sudo bash $0"

APP_DIR=/opt/ic26
ENV_FILE=/etc/ic26/env
[ -d "$APP_DIR" ] || die "$APP_DIR 가 없습니다. 이 스크립트는 WAS 서버용입니다."

echo "[1/4] 서비스 멈춤"
if [ "$USE_SYSTEMD" = 1 ]; then
  systemctl stop ic26-was.service ic26-review.service ic26-market.service 2>/dev/null || true
  for u in ic26-was ic26-review ic26-market; do printf '  %-12s %s\n' "$u" "$(systemctl is-active "$u.service" 2>/dev/null || true)"; done
else
  echo "  건너뜀 (--no-systemd)"
fi

echo "[2/4] $ENV_FILE 의 비밀 값 비우기"
if [ -f "$ENV_FILE" ]; then
  names="$(sed -nE 's/^([A-Za-z0-9_]*(KEY|PASSWORD|TOKEN|SECRET)[A-Za-z0-9_]*)=.+/\1/p' "$ENV_FILE")"
  sed -i -E 's/^([A-Za-z0-9_]*(KEY|PASSWORD|TOKEN|SECRET)[A-Za-z0-9_]*)=.*/\1=/' "$ENV_FILE"
  chown root:root "$ENV_FILE"; chmod 600 "$ENV_FILE"
  if [ -n "$names" ]; then echo "  비운 변수: $(echo $names)"; else echo "  비울 값이 없었음"; fi
  left="$(grep -cE '^[A-Za-z0-9_]*(KEY|PASSWORD|TOKEN|SECRET)[A-Za-z0-9_]*=.' "$ENV_FILE" || true)"
  [ "${left:-0}" = 0 ] && echo "  확인: 비밀 값이 남아 있지 않음" || die "비밀 값이 남아 있습니다 ($left줄). $ENV_FILE 을 직접 확인하세요."
else
  echo "  $ENV_FILE 이 없음"
fi
# 편집기가 남긴 임시 파일 (vi 의 .swp, 백업 ~) 에 값이 남아 있을 수 있다
for f in /etc/ic26/.env.swp /etc/ic26/.env.swo /etc/ic26/env~ /etc/ic26/env.bak /etc/ic26/env.save; do
  [ -e "$f" ] && { rm -f "$f"; echo "  편집기 임시 파일 삭제: $f"; }
done
extra="$(find /etc/ic26 -mindepth 1 ! -name env 2>/dev/null | head -n 5)"
[ -z "$extra" ] || warn "/etc/ic26 에 env 말고 다른 파일이 있습니다. 값이 들어 있는지 확인하고 지우세요: $(echo $extra)"

echo "[3/4] 실행 중에 생긴 데이터 지우기"
clear_dir() {
  if [ -d "$1" ]; then
    n="$(find "$1" -mindepth 1 | wc -l)"
    find "$1" -mindepth 1 -delete
    printf '  %-55s %s개 지움\n' "$1" "$n"
  fi
}
clear_dir /var/lib/ic26/runtime                            # 승인 기록(approvals.jsonl)
clear_dir /var/lib/ic26/market                             # 상권 대화 기록(SQLite)
clear_dir $APP_DIR/services/review-insight/data/runtime    # 붙여넣은 리뷰와 분류 결과
clear_dir $APP_DIR/services/review-insight/logs            # 사용량 기록
clear_dir $APP_DIR/experiments/marketing/results           # 글 생성 모델의 원문 응답
clear_dir $APP_DIR/services/web/data/runtime

echo "[4/4] 키가 남아 있을 만한 곳 찾기 (파일 이름만 출력)"
hits=""
for f in /root/.bash_history /root/.viminfo /home/*/.bash_history /home/*/.viminfo /home/*/.zsh_history; do
  [ -f "$f" ] || continue
  if grep -qE '(API_KEY|PASSWORD|TOKEN|SECRET)=[^[:space:]]+' "$f" 2>/dev/null; then hits="$hits $f"; fi
done
if [ -n "$hits" ]; then
  warn "키·비밀번호를 명령줄에 쓴 흔적이 있을 수 있습니다:$hits"
  echo "  → 해당 사용자로 'history -c && history -w' 를 하고, .viminfo 는 지웁니다."
else
  echo "  히스토리·viminfo 에서 NAME=값 모양의 흔적을 찾지 못했음"
fi

cat <<'EOF'

이미지를 만들기 전 마지막 확인
  1. 지금 접속해 있는 셸의 히스토리를 지웁니다 (이미지에 .bash_history 가 담깁니다):
       history -c && history -w
     sudo -i 나 root 로 들어갔다면 그 셸에서도 같은 명령을 합니다.
  2. 올려 둔 묶음(~/ic26-*.tgz)과 풀어 둔 폴더에는 비밀이 없습니다. 지우지 않아도 됩니다.
  3. 콘솔에서 이 서버로 서버 이미지를 만듭니다 (ic26-was-img1).
이미지를 만든 뒤에는 이 서버의 /etc/ic26/env 에 값을 다시 넣고 서비스를 시작합니다.
  sudo vi -n -i NONE /etc/ic26/env
  sudo systemctl restart ic26-review ic26-was
EOF
