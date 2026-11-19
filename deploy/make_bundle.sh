#!/usr/bin/env bash
# PC에서 서버에 올릴 묶음(ic26-<커밋>.tgz)을 만든다.
#
# 사용법 (저장소 어디서든):
#   deploy/make_bundle.sh                    origin/main 의 최신 커밋 (먼저 git fetch)
#   deploy/make_bundle.sh <커밋|브랜치|태그>    그 커밋
# 옵션:
#   --out DIR      묶음을 만들 폴더 (기본: 지금 폴더)
#   --no-fetch     git fetch 를 하지 않음 (기본은 origin/... 를 쓸 때 fetch)
#
# - 로컬 main 브랜치나 wt/main 폴더는 쓰지 않는다 (옛 커밋에 멈춰 있을 수 있음). 기본은 origin/main.
# - 작업 폴더의 수정 중인 파일은 묶지 않는다. git 에 올라간 커밋만 묶는다.
# - 예외: 그 커밋에 deploy/ 가 아직 없으면(병합 전), 이 스크립트가 있는 deploy/ 폴더를 묶음에 더한다.
# - 묶음 안에는 REVISION 파일(커밋 해시 한 줄)이 들어간다. 서버의 /opt/ic26/REVISION 이 된다.
# - 묶음에 키·비밀번호·.env 는 들어가지 않는다 (git 에 있는 파일만 묶음).
# - 화면(services/web/frontend, React + Vite)은 그 커밋의 소스로 묶음 안에서 npm ci && npm run build 해 dist 를 넣는다
#   (작업 폴더에 남아 있던 빌드는 쓰지 않음). node_modules 는 묶음에 넣지 않는다. npm(Node.js 20 이상)이 필요하다.
set -euo pipefail

die() { echo "오류: $*" >&2; exit 1; }
warn() { echo "주의: $*" >&2; }

REF=""
OUT="$PWD"
FETCH=auto
while [ $# -gt 0 ]; do
  case "$1" in
    --out) [ $# -ge 2 ] || die "--out 뒤에 폴더를 적으세요"; OUT="$2"; shift 2 ;;
    --no-fetch) FETCH=no; shift ;;
    -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    -*) die "모르는 옵션입니다: $1 (--help)" ;;
    *) [ -z "$REF" ] || die "커밋은 하나만 줄 수 있습니다"; REF="$1"; shift ;;
  esac
done
REF="${REF:-origin/main}"

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(git -C "$DEPLOY_DIR" rev-parse --show-toplevel 2>/dev/null)" || die "git 저장소 안에서 실행하세요"
git_() { git -C "$REPO" "$@"; }

# origin/... 를 쓰면 먼저 최신으로 받는다 (읽기만 함. GitHub 에 쓰지 않음)
if [ "$FETCH" = auto ]; then
  case "$REF" in
    origin/*) echo "git fetch origin ${REF#origin/} ..."
              git_ fetch --quiet origin "${REF#origin/}" || die "fetch 실패. 인터넷을 확인하거나 --no-fetch 로 지금 받아 둔 origin 을 쓰세요" ;;
  esac
fi

COMMIT="$(git_ rev-parse --verify --quiet "${REF}^{commit}")" || die "커밋을 찾을 수 없습니다: $REF"
SHORT="$(git_ rev-parse --short=7 "$COMMIT")"
NAME="ic26-$SHORT"

if git_ rev-parse --verify --quiet origin/main >/dev/null && ! git_ merge-base --is-ancestor "$COMMIT" origin/main; then
  warn "이 커밋($SHORT)은 origin/main 에 들어 있지 않습니다 (병합 전 커밋). 서버에 올릴 코드가 맞는지 확인하세요."
fi

command -v shasum >/dev/null && SHA() { shasum -a 256 "$@"; } || SHA() { sha256sum "$@"; }

mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/ic26-bundle.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

mkdir "$STAGE/$NAME"
git_ archive --format=tar "$COMMIT" | tar -x -C "$STAGE/$NAME"

if git_ cat-file -e "$COMMIT:deploy/install_was.sh" 2>/dev/null; then
  DEPLOY_SRC="커밋 $SHORT 안의 deploy/"
else
  [ -f "$DEPLOY_DIR/install_was.sh" ] || die "deploy/install_was.sh 를 찾을 수 없습니다 ($DEPLOY_DIR)"
  warn "커밋 $SHORT 에는 deploy/ 가 없어, 이 PC의 $DEPLOY_DIR 를 묶음에 더합니다."
  rm -rf "$STAGE/$NAME/deploy"
  mkdir "$STAGE/$NAME/deploy"
  # 임시·편집기 파일과 이전에 만든 묶음은 빼고 복사
  (cd "$DEPLOY_DIR" && tar -cf - --exclude='.DS_Store' --exclude='*.swp' --exclude='*~' --exclude='*.tgz' --exclude='*.sha256' .) \
    | tar -x -C "$STAGE/$NAME/deploy"
  DEPLOY_SRC="이 PC의 작업 폴더 deploy/ ($(git_ rev-parse --abbrev-ref HEAD)@$(git_ rev-parse --short=7 HEAD)$([ -z "$(git_ status --porcelain -- "$DEPLOY_DIR" 2>/dev/null)" ] || echo ', 커밋하지 않은 내용 포함'))"
fi

# 화면 빌드: git 에는 소스만 있다. 이 커밋의 소스로 묶음 안에서 빌드하고 node_modules 는 지운다 (실패하면 묶음을 만들지 않음)
FRONT_STAGE="$STAGE/$NAME/services/web/frontend"
if [ -f "$FRONT_STAGE/package.json" ]; then
  command -v npm >/dev/null 2>&1 || die "화면을 빌드하려면 npm 이 필요합니다 (Node.js 20 이상)"
  echo "화면 빌드 (커밋 $SHORT 의 services/web/frontend) ..."
  ( cd "$FRONT_STAGE" && npm ci --no-audit --no-fund --loglevel=error && npm run build --silent ) \
    || die "화면 빌드에 실패했습니다 (커밋 $SHORT). 묶음을 만들지 않습니다."
  rm -rf "$FRONT_STAGE/node_modules"
  [ -f "$FRONT_STAGE/dist/index.html" ] || die "화면 빌드 뒤에 dist/index.html 이 없습니다"
  FRONT_SRC="커밋 $SHORT 소스로 빌드 (node $(node --version 2>/dev/null || echo '?'), $(date '+%Y-%m-%d %H:%M'))"
else
  warn "커밋 $SHORT 에는 services/web/frontend 가 없어 화면을 빌드하지 않습니다 (예전 화면 커밋)."
  FRONT_SRC="없음 (이 커밋에 services/web/frontend 가 없음)"
fi

printf '%s\n' "$COMMIT" > "$STAGE/$NAME/REVISION"
{
  echo "commit      $COMMIT"
  echo "ref         $REF"
  echo "deploy      $DEPLOY_SRC"
  echo "frontend    $FRONT_SRC"
  echo "bundled_at  $(date '+%Y-%m-%d %H:%M:%S %z')"
} > "$STAGE/$NAME/deploy/BUNDLE_INFO"

# macOS 의 확장 속성(._ 파일)이 리눅스 쪽에 섞이지 않게 한다
export COPYFILE_DISABLE=1
TGZ="$OUT/$NAME.tgz"
tar --no-xattrs --no-mac-metadata -czf "$TGZ" -C "$STAGE" "$NAME" 2>/dev/null \
  || tar -czf "$TGZ" -C "$STAGE" "$NAME"

# 필요한 것이 들어 있는지 확인
LIST="$(tar -tzf "$TGZ")"
for must in REVISION deploy/install_was.sh deploy/env.example services/web/web/main.py \
            services/market-analysis/app/intake_api.py \
            services/review-insight/app/main.py shared/contracts.py experiments/marketing/c6/registry.py \
            data/scenario/snapshot_2026Q2.json; do
  grep -qxF "$NAME/$must" <<<"$LIST" || die "묶음에 $must 가 없습니다. 이 커밋으로는 서버에 올릴 수 없습니다."
done
if [ -f "$FRONT_STAGE/package.json" ]; then
  grep -qxF "$NAME/services/web/frontend/dist/index.html" <<<"$LIST" || die "묶음에 화면 빌드(services/web/frontend/dist/index.html)가 없습니다."
  grep -q "^$NAME/services/web/frontend/dist/assets/." <<<"$LIST" || die "묶음에 화면 빌드 파일(dist/assets)이 없습니다."
  ! grep -q "^$NAME/services/web/frontend/node_modules/" <<<"$LIST" || die "묶음에 node_modules 가 들어 있습니다."
fi
# 상권 공식 자료(수백 MB)는 코드 묶음에 넣지 않는다. 자료 묶음(seoul-market-data-….tar.gz)을 따로 올려 install_market_data.sh 로 깐다
if grep -Eq '^[^/]+/services/market-analysis/data/(raw|official)/|\.tar\.gz$' <<<"$LIST"; then
  die "묶음에 상권 공식 자료나 .tar.gz 가 들어 있습니다. 자료는 따로 올립니다 (deploy/install_market_data.sh)."
fi
if grep -Eq '(^|/)(\.env|\._[^/]*)$|\.pem$' <<<"$LIST"; then
  die "묶음에 .env 나 인증키(.pem), ._ 파일이 들어 있습니다. 올리지 마세요."
fi

( cd "$OUT" && SHA "$NAME.tgz" > "$NAME.tgz.sha256" )

echo
echo "묶음을 만들었습니다"
echo "  파일      $TGZ ($(du -h "$TGZ" | cut -f1), $(grep -vc '/$' <<<"$LIST")개 파일)"
echo "  체크섬    $TGZ.sha256"
echo "  커밋      $COMMIT"
echo "  deploy    $DEPLOY_SRC"
echo "  frontend  $FRONT_SRC"
echo
echo "다음: 베스천을 거쳐 서버로 올립니다 (deploy/README.md 3절)."
echo "  scp $NAME.tgz $NAME.tgz.sha256 <서버 별칭>:~/"
