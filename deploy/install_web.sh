#!/usr/bin/env bash
# 웹 서버(Ubuntu 24.04)에 Nginx 를 설치하고 ic26 설정을 넣는다. 여러 번 돌려도 안전하다 (설정을 새로 덮고 reload).
#
# 사용법 (서버에서. 묶음 tgz 를 푼 폴더 안의 스크립트를 root 로 실행):
#   sudo bash ic26-<커밋>/deploy/install_web.sh --lb <내부 로드 밸런서 주소>                      # 1단계: 모든 요청을 WAS 로
#   sudo bash ic26-<커밋>/deploy/install_web.sh --lb <주소> --mode static [--static-src <폴더>]    # 2단계: 화면 파일은 웹 서버가
# 옵션:
#   --lb ADDR         내부 로드 밸런서의 접속 주소 (필수). 도메인 또는 IP, 포트가 80이 아니면 주소:포트. http:// 는 빼도 됨
#   --mode MODE       proxy-all (기본, 1단계) | static (2단계)
#   --static-src DIR  static 일 때 화면 파일이 있는 폴더 (기본: 묶음의 services/web/web/static). index.html 이 있어야 함
#   --no-systemd      Nginx 를 systemctl 로 켜고 다시 읽지 않음 (컨테이너 시험용. nginx 를 직접 띄우거나 nginx -s reload)
#   --skip-apt        apt 설치를 건너뜀
#
# 웹 서버에는 키도 DB 접속 정보도 두지 않는다. 이 스크립트는 /etc/ic26 를 만들지 않는다.
set -euo pipefail

die() { echo "오류: $*" >&2; exit 1; }
warn() { echo "주의: $*" >&2; }

LB=""; MODE=proxy-all; STATIC_SRC=""; USE_SYSTEMD=1; DO_APT=1
while [ $# -gt 0 ]; do
  case "$1" in
    --lb) [ $# -ge 2 ] || die "--lb 뒤에 주소를 적으세요"; LB="$2"; shift ;;
    --mode) [ $# -ge 2 ] || die "--mode 뒤에 proxy-all 또는 static 을 적으세요"; MODE="$2"; shift ;;
    --static-src) [ $# -ge 2 ] || die "--static-src 뒤에 폴더를 적으세요"; STATIC_SRC="$2"; shift ;;
    --no-systemd) USE_SYSTEMD=0 ;;
    --skip-apt) DO_APT=0 ;;
    -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *) die "모르는 옵션입니다: $1 (--help)" ;;
  esac
  shift
done

[ "$(id -u)" -eq 0 ] || die "root 권한이 필요합니다.  sudo bash $0 ..."
case "$MODE" in proxy-all|static) ;; *) die "--mode 는 proxy-all 또는 static 입니다 (받은 값: $MODE)";; esac

# 내부 로드 밸런서 주소: 설정 파일에 그대로 들어가므로 글자를 엄격히 검사한다
LB="${LB#http://}"; LB="${LB%/}"
[ -n "$LB" ] || die "--lb <내부 로드 밸런서 주소> 가 필요합니다 (콘솔의 ic26-was-alb1 접속 정보)"
case "$LB" in https://*) die "내부 로드 밸런서는 http 로 부릅니다 (https:// 를 빼세요)";; esac
printf '%s' "$LB" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?$' \
  || die "주소 모양이 맞지 않습니다: '$LB' (영문·숫자·점·하이픈, 필요하면 :포트)"

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF_SRC="$SRC/deploy/nginx/$([ "$MODE" = static ] && echo ic26-static.conf || echo ic26-proxy-all.conf)"
[ -f "$CONF_SRC" ] || die "설정 틀이 없습니다: $CONF_SRC"
WWW=/var/www/ic26
if [ "$MODE" = static ]; then
  STATIC_SRC="${STATIC_SRC:-$SRC/services/web/web/static}"
  [ -f "$STATIC_SRC/index.html" ] || die "화면 파일 폴더에 index.html 이 없습니다: $STATIC_SRC"
fi

echo "모드: $MODE   내부 로드 밸런서: $LB"
[ "$MODE" = static ] && echo "화면 파일: $STATIC_SRC → $WWW/"

if [ "$DO_APT" = 1 ]; then
  export DEBIAN_FRONTEND=noninteractive
  echo "apt 로 설치합니다 (1분 안팎)"
  apt-get -qq update
  apt-get -qq install -y --no-install-recommends nginx ca-certificates curl rsync
fi
command -v nginx >/dev/null 2>&1 || die "nginx 가 없습니다"

# 화면 파일 (static 모드). 폴더의 '내용'을 /var/www/ic26/ 에 그대로 둔다 (/static/ 주소가 이 폴더로 이어짐)
if [ "$MODE" = static ]; then
  install -d -m 755 -o root -g root "$WWW"
  rsync -a --delete --chown=root:root --chmod=D755,F644 "$STATIC_SRC"/ "$WWW"/
  echo "화면 파일: $(ls -1 "$WWW" | tr '\n' ' ')"
fi

# 설정 넣기. 문법 검사에 실패하면 이전 설정으로 되돌린다.
AVAIL=/etc/nginx/sites-available/ic26
ENABLED=/etc/nginx/sites-enabled/ic26
install -d /etc/nginx/sites-available /etc/nginx/sites-enabled
BACKUP="$(mktemp)"; trap 'rm -f "$BACKUP"' EXIT
HAD_CONF=0; [ -f "$AVAIL" ] && { cp -p "$AVAIL" "$BACKUP"; HAD_CONF=1; }
HAD_DEFAULT_LINK=0; [ -e /etc/nginx/sites-enabled/default ] && HAD_DEFAULT_LINK=1

sed "s/__INTERNAL_LB__/$LB/g" "$CONF_SRC" > "$AVAIL"
chmod 644 "$AVAIL"
ln -sfn "$AVAIL" "$ENABLED"
rm -f /etc/nginx/sites-enabled/default      # 기본 사이트도 80번 default_server 라서 충돌한다

if ! nginx -t; then
  if [ "$HAD_CONF" = 1 ]; then cp -p "$BACKUP" "$AVAIL"; else rm -f "$AVAIL" "$ENABLED"; fi
  [ "$HAD_DEFAULT_LINK" = 1 ] && [ -e /etc/nginx/sites-available/default ] && ln -sfn /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
  die "nginx 설정 검사에 실패해 이전 설정으로 되돌렸습니다. (내부 로드 밸런서 주소가 이 서버에서 풀리는지 확인: getent hosts $LB)"
fi

if [ "$USE_SYSTEMD" = 1 ]; then
  [ -d /run/systemd/system ] || die "systemd 로 돌고 있지 않습니다. 컨테이너라면 --no-systemd 를 붙이세요."
  systemctl enable nginx.service
  systemctl reload nginx.service 2>/dev/null || systemctl restart nginx.service
  echo "nginx: $(systemctl is-active nginx.service)"
  echo "확인:  curl -s http://localhost/healthz   (ok)   /   curl -s http://localhost/api/health   (WAS 의 응답)"
  echo "       curl -s -o /dev/null -w '%{http_code}\n' http://localhost/docs   (404)"
else
  echo "건너뜀 (--no-systemd): nginx 를 직접 띄우거나 'nginx -s reload' 를 하세요"
fi
echo "참고: Nginx 는 시작·reload 때 내부 로드 밸런서 주소를 한 번만 IP 로 바꿉니다. 로드 밸런서를 다시 만들었다면 reload 하세요."
echo "설정 완료: $AVAIL ($MODE)"
