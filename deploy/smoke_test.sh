#!/usr/bin/env bash
# 서버 안에서 앱이 제대로 떠 있는지 확인한다. 키·비밀번호를 읽거나 출력하지 않는다.
#
# 사용법:
#   bash deploy/smoke_test.sh                            /api/health 와 /api/briefing 확인
#   bash deploy/smoke_test.sh --generate                 + 글 생성 1회 (live 이면 HCX 를 실제로 부름, 비용 발생)
#   bash deploy/smoke_test.sh --expect-reviews 40        브리핑의 리뷰 건수가 정확히 40건인지 확인
#   bash deploy/smoke_test.sh --base http://127.0.0.1:8000   확인할 주소 (기본 http://127.0.0.1:8000)
#
# 종료 코드: 모두 통과하면 0, 하나라도 실패하면 1.
# 확인하는 것
#   /api/health     200, 모드와 키 유무, 리뷰 분석 상태 ok, 막힘 목록(blocking) 비어 있음
#   /api/briefing   200, 리뷰 건수 > 0 (--expect-reviews 를 주면 그 건수와 같음)
#   /api/cards 와 POST /api/cards/{id}/run (--generate 일 때만)   200, 초안이 1개 이상
set -uo pipefail

BASE="http://127.0.0.1:8000"; EXPECT=""; GENERATE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="${2:-}"; shift ;;
    --expect-reviews) EXPECT="${2:-}"; shift ;;
    --generate) GENERATE=1 ;;
    -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *) echo "모르는 옵션입니다: $1 (--help)" >&2; exit 2 ;;
  esac
  shift
done
BASE="${BASE%/}"
command -v curl >/dev/null 2>&1 || { echo "curl 이 없습니다 (apt install curl)" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 가 없습니다" >&2; exit 2; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
FAIL=0
ok()   { printf '  통과  %s\n' "$*"; }
bad()  { printf '  실패  %s\n' "$*"; FAIL=1; }

# 응답 본문을 $TMP/$1 에, 상태 코드를 STATUS 에 둔다.   get NAME PATH [timeout]
get() { : > "$TMP/$1"; STATUS="$(curl -sS -m "${3:-60}" -o "$TMP/$1" -w '%{http_code}' "$BASE$2" 2>"$TMP/$1.err")" || STATUS="000"; }
# JSON 한 값 꺼내기:  jq_ FILE 'python 식(d 가 JSON)'
jq_() { python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); print(eval(sys.argv[2]))' "$1" "$2" 2>/dev/null; }

echo "확인 주소: $BASE"

echo "[1] GET /api/health"
get health /api/health 30
if [ "$STATUS" = 200 ]; then
  ok "HTTP 200"
  MODE="$(jq_ "$TMP/health" 'd.get("mode")')"
  KEY="$(jq_ "$TMP/health" 'd.get("key_present")')"
  REVIEW="$(jq_ "$TMP/health" '(d.get("review_service") or {}).get("status")')"
  BLOCK="$(jq_ "$TMP/health" 'len(d.get("blocking") or [])')"
  echo "        모드: $MODE   키 있음: $KEY   리뷰 분석 서비스: $REVIEW   막힘 항목: $BLOCK개"
  [ "$REVIEW" = ok ] && ok "리뷰 분석 서비스 ok" || bad "리뷰 분석 서비스가 ok 가 아님 ($REVIEW). journalctl -u ic26-review -n 50"
  if [ "$BLOCK" = 0 ]; then ok "막힘 목록이 비어 있음"; else
    bad "막힘 항목이 있음:"; jq_ "$TMP/health" '"\n".join("          - " + b for b in d.get("blocking", []))'
  fi
  if [ "$MODE" = live ]; then [ "$KEY" = True ] && ok "live 이고 키가 있음" || bad "live 인데 키가 없음"; fi
  if [ "$MODE" = mock ]; then echo "        (mock: 키 없이 도는 시험용 실행입니다. 실제 AI 결과가 아닙니다)"; fi
else
  bad "HTTP $STATUS ($(head -c 200 "$TMP/health.err"))  → systemctl status ic26-was / journalctl -u ic26-was -n 50"
fi

echo "[2] GET /api/briefing"
get briefing /api/briefing 90
if [ "$STATUS" = 200 ]; then
  ok "HTTP 200"
  N="$(jq_ "$TMP/briefing" '(d.get("counts") or {}).get("review_count")')"
  C="$(jq_ "$TMP/briefing" '(d.get("counts") or {}).get("complaint_count")')"
  echo "        리뷰 ${N:-?}건, 불만 ${C:-?}건"
  if [ -n "$EXPECT" ]; then
    [ "$N" = "$EXPECT" ] && ok "리뷰 건수 $EXPECT" || bad "리뷰 건수가 $EXPECT 가 아님 ($N)"
  else
    case "$N" in ''|*[!0-9]*|0) bad "리뷰 건수를 읽지 못했거나 0건 ($N)" ;; *) ok "리뷰가 있음" ;; esac
  fi
else
  bad "HTTP $STATUS  → $(head -c 300 "$TMP/briefing")"
fi

if [ "$GENERATE" = 1 ]; then
  echo "[3] 글 생성 1회 (GET /api/cards → POST /api/cards/{id}/run)"
  get cards /api/cards 120
  CID="$(jq_ "$TMP/cards" '((d.get("cards") or [{}])[0].get("card") or {}).get("card_id")')"
  if [ "$STATUS" = 200 ] && [ -n "$CID" ] && [ "$CID" != None ]; then
    ok "카드 있음: $CID"
    T0=$(date +%s); : > "$TMP/run"
    STATUS="$(curl -sS -m 180 -o "$TMP/run" -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{}' "$BASE/api/cards/$CID/run" 2>"$TMP/run.err")" || STATUS=000
    T1=$(date +%s)
    if [ "$STATUS" = 200 ]; then
      D="$(jq_ "$TMP/run" 'len(d.get("drafts") or [])')"
      SRCV="$(jq_ "$TMP/run" 'd.get("source")')"
      [ "${D:-0}" -ge 1 ] 2>/dev/null && ok "HTTP 200, 초안 ${D}개, 출처 ${SRCV}, $((T1 - T0))초" || bad "HTTP 200 인데 초안이 없음"
    else
      bad "HTTP $STATUS ($((T1 - T0))초)  → $(head -c 300 "$TMP/run")"
    fi
  else
    bad "카드를 가져오지 못함 (HTTP $STATUS)  → $(head -c 300 "$TMP/cards")"
  fi
else
  echo "[3] 글 생성은 건너뜀 (--generate 를 주면 1회 확인. live 는 HCX 호출 비용이 듭니다)"
fi

echo
if [ "$FAIL" = 0 ]; then echo "결과: 모두 통과"; else echo "결과: 실패가 있습니다"; fi
[ -f /opt/ic26/REVISION ] && echo "서버의 커밋: $(head -n1 /opt/ic26/REVISION)"
exit "$FAIL"
