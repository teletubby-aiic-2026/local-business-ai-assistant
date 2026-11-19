#!/usr/bin/env bash
# 웹 서버(Ubuntu 24.04)에 Nginx 를 설치하고 ic26 설정을 넣는다. 여러 번 돌려도 안전하다 (설정을 새로 덮고 reload).
#
# 사용법 (서버에서. 묶음 tgz 를 푼 폴더 안의 스크립트를 root 로 실행):
#   sudo bash ic26-<커밋>/deploy/install_web.sh --lb <내부 로드 밸런서 주소>                      # 1단계: 모든 요청을 WAS 로
#   sudo bash ic26-<커밋>/deploy/install_web.sh --lb <주소> --mode static [--static-src <폴더>]    # 2단계: 화면 파일은 웹 서버가
# 옵션:
#   --lb ADDR         내부 로드 밸런서의 접속 주소 (필수). 도메인 또는 IP, 포트가 80이 아니면 주소:포트. http:// 는 빼도 됨
#   --mode MODE       proxy-all (기본, 1단계) | static (2단계)
#   --static-src DIR  static 일 때 화면 빌드 폴더 (기본: 묶음의 services/web/frontend/dist, make_bundle.sh 가 빌드해 넣음).
#                     index.html 과 assets/ 가 있어야 함
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
  STATIC_SRC="${STATIC_SRC:-$SRC/services/web/frontend/dist}"
  [ -f "$STATIC_SRC/index.html" ] || die "화면 빌드 폴더에 index.html 이 없습니다: $STATIC_SRC (묶음을 deploy/make_bundle.sh 로 다시 만드세요)"
  [ -d "$STATIC_SRC/assets" ] || die "화면 빌드 폴더에 assets/ 가 없습니다: $STATIC_SRC"
fi

echo "모드: $MODE   내부 로드 밸런서: $LB"
[ "$MODE" = static ] && echo "화면 파일: $STATIC_SRC → $WWW/"

AVAIL=/etc/nginx/sites-available/ic26
ENABLED=/etc/nginx/sites-enabled/ic26
DEFAULT_LINK=/etc/nginx/sites-enabled/default
POLICY_RC=/usr/sbin/policy-rc.d
POLICY_MARK='# ic26 install_web.sh: apt 동안만 두는 임시 파일 (남아 있으면 지워도 됨)'
OUR_POLICY=0        # 1: 이 스크립트가 둔 policy-rc.d → 끝날 때 반드시 지운다
HAD_DEFAULT_LINK=0  # 1: 기본 사이트 링크가 apt 전이나 후에 있었다 → 도중에 실패하면 되살린다
CONF_DONE=0         # 1: ic26 설정이 검사(nginx -t)를 통과했다
BACKUP=""
NGINX_PKG_BEFORE=""; NGINX_PKG_AFTER=""   # nginx 패키지 상태·버전 (apt 전후)

restore_default_link() {
  [ "$HAD_DEFAULT_LINK" = 1 ] && [ -e /etc/nginx/sites-available/default ] \
    && ln -sfn /etc/nginx/sites-available/default "$DEFAULT_LINK"
  return 0
}
remove_our_policy() {
  [ "$OUR_POLICY" = 1 ] && grep -qF "$POLICY_MARK" "$POLICY_RC" 2>/dev/null && rm -f "$POLICY_RC"
  OUR_POLICY=0
}
cleanup() {
  local st=$?
  remove_our_policy
  [ -n "$BACKUP" ] && rm -f "$BACKUP"
  # 설정 검사 전에 멈췄다면(apt 실패 등) 기본 사이트 링크를 원래대로 둔다
  [ "$st" != 0 ] && [ "$CONF_DONE" = 0 ] && restore_default_link
  exit "$st"
}
trap cleanup EXIT
trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM   # ssh 가 끊기거나 Ctrl-C 여도 cleanup 이 돈다

if [ "$DO_APT" = 1 ]; then
  export DEBIAN_FRONTEND=noninteractive
  # IPv6 가 없는 서버(네이버클라우드 Ubuntu 24.04, /proc/sys/net/ipv6 없음)에서는 nginx 패키지의 postinst 가
  # 기본 사이트(listen [::]:80)로 nginx 를 켜다 'socket() [::]:80 failed (97: ...)' 로 실패하고,
  # dpkg 가 nginx 를 설정 미완료(iF)로 남겨 apt 가 멈춘다 (11/18 web1). 그래서
  #  (1) 설치하는 동안만 policy-rc.d(exit 101)로 패키지가 서비스를 켜지 못하게 한다. 원래 있던 파일은 건드리지 않는다.
  #  (2) 이미 그렇게 멈춘 서버도 다시 돌리면 회복되게, 기본 사이트 링크를 먼저 치우고 dpkg --configure -a 를 한다.
  #      (링크는 아래 설정 단계에서 어차피 지운다. 설정 검사 전에 실패하면 되살린다.)
  if [ -e "$POLICY_RC" ] && ! grep -qF "$POLICY_MARK" "$POLICY_RC" 2>/dev/null; then
    warn "$POLICY_RC 가 이미 있어 그대로 씁니다 (이 스크립트는 지우지 않음)"
  else
    # 없거나, 지난 실행이 강제로 끊겨 남은 우리 파일이면 (다시) 두고 끝날 때 지운다
    printf '#!/bin/sh\n%s\nexit 101\n' "$POLICY_MARK" > "$POLICY_RC"
    chmod 755 "$POLICY_RC"
    OUR_POLICY=1
  fi
  if [ -e "$DEFAULT_LINK" ]; then HAD_DEFAULT_LINK=1; rm -f "$DEFAULT_LINK"; fi
  NGINX_PKG_BEFORE="$(dpkg-query -W -f='${Status} ${Version}' nginx 2>/dev/null || true)"
  dpkg --configure -a || die "dpkg --configure -a 에 실패했습니다. 'sudo dpkg --audit' 로 어떤 패키지인지 보세요"

  echo "apt 로 설치합니다 (1분 안팎)"
  apt-get -qq update
  apt-get -qq install -y --no-install-recommends nginx ca-certificates curl rsync \
    || die "apt 설치에 실패했습니다. 원인을 고친 뒤 같은 명령을 다시 돌리면 이어서 설치합니다 ('sudo dpkg --audit' 로 상태 확인)"
  remove_our_policy
  NGINX_PKG_AFTER="$(dpkg-query -W -f='${Status} ${Version}' nginx 2>/dev/null || true)"
  case "$NGINX_PKG_AFTER" in
    "install ok installed "*) ;;
    *) die "nginx 패키지 설치가 끝나지 않았습니다 (${NGINX_PKG_AFTER:-없음}). 'sudo dpkg --audit' 로 확인하세요" ;;
  esac
fi
command -v nginx >/dev/null 2>&1 || die "nginx 가 없습니다"

# 화면 파일 (static 모드). 빌드 폴더의 '내용'(index.html, assets/)을 /var/www/ic26/ 에 그대로 둔다
if [ "$MODE" = static ]; then
  install -d -m 755 -o root -g root "$WWW"
  rsync -a --delete --chown=root:root --chmod=D755,F644 "$STATIC_SRC"/ "$WWW"/
  echo "화면 파일: $(ls -1 "$WWW" | tr '\n' ' ')"
fi

# 설정 넣기. 문법 검사에 실패하면 이전 설정으로 되돌린다.
install -d /etc/nginx/sites-available /etc/nginx/sites-enabled
BACKUP="$(mktemp)"
HAD_CONF=0; [ -f "$AVAIL" ] && { cp -p "$AVAIL" "$BACKUP"; HAD_CONF=1; }
[ -e "$DEFAULT_LINK" ] && HAD_DEFAULT_LINK=1   # 새로 설치하면 패키지가 기본 사이트 링크를 만든다

sed "s/__INTERNAL_LB__/$LB/g" "$CONF_SRC" > "$AVAIL"
chmod 644 "$AVAIL"
ln -sfn "$AVAIL" "$ENABLED"
rm -f "$DEFAULT_LINK"      # 기본 사이트도 80번 default_server 라서 충돌한다 (IPv6 가 없는 서버에서는 [::]:80 이 실패한다)

if ! nginx -t; then
  if [ "$HAD_CONF" = 1 ]; then cp -p "$BACKUP" "$AVAIL"; else rm -f "$AVAIL" "$ENABLED"; fi
  restore_default_link
  die "nginx 설정 검사에 실패해 이전 설정으로 되돌렸습니다. (내부 로드 밸런서 주소가 이 서버에서 풀리는지 확인: getent hosts $LB)"
fi
CONF_DONE=1

if [ "$USE_SYSTEMD" = 1 ]; then
  [ -d /run/systemd/system ] || die "systemd 로 돌고 있지 않습니다. 컨테이너라면 --no-systemd 를 붙이세요."
  systemctl enable nginx.service
  if [ "$NGINX_PKG_BEFORE" != "$NGINX_PKG_AFTER" ]; then
    # 이번에 nginx 를 새로 깔았거나 올렸다. 설치 중에는 policy-rc.d 로 켜지 않았으므로 여기서 새로 띄운다
    systemctl restart nginx.service
  else
    systemctl reload nginx.service 2>/dev/null || systemctl restart nginx.service
  fi
  echo "nginx: $(systemctl is-active nginx.service)"
  echo "확인:  curl -s http://localhost/healthz   (ok)   /   curl -s http://localhost/api/health   (WAS 의 응답)"
  echo "       curl -s -o /dev/null -w '%{http_code}\n' http://localhost/docs   (404)"
else
  echo "건너뜀 (--no-systemd): nginx 를 직접 띄우거나 'nginx -s reload' 를 하세요"
fi
echo "참고: Nginx 는 시작·reload 때 내부 로드 밸런서 주소를 한 번만 IP 로 바꿉니다. 로드 밸런서를 다시 만들었다면 reload 하세요."
echo "설정 완료: $AVAIL ($MODE)"
