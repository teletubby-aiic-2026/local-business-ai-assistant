#!/usr/bin/env bash
# 서버 안에서 앱이 제대로 떠 있는지 확인한다. 키·비밀번호를 읽거나 출력하지 않는다.
#
# 사용법:
#   bash deploy/smoke_test.sh                            /api/health 와 /api/briefing 확인
#   bash deploy/smoke_test.sh --generate                 + 글 생성 1회 (live 이면 HCX 를 실제로 부름, 비용 발생)
#   bash deploy/smoke_test.sh --expect-reviews 40        브리핑의 리뷰 건수가 정확히 40건인지 확인
#   bash deploy/smoke_test.sh --base http://127.0.0.1:8000   확인할 주소 (기본 http://127.0.0.1:8000)
#   bash deploy/smoke_test.sh --marketing http://127.0.0.1:8030   맞춤 마케팅 서버를 직접 볼 주소 (WAS 서버에서는 기본으로 봄)
#   bash deploy/smoke_test.sh --no-marketing             맞춤 마케팅 확인을 건너뜀
#   bash deploy/smoke_test.sh --market                   상권 서비스(ic26-market)가 반드시 떠 있어야 함 (서랍 ready 아니면 실패)
#   bash deploy/smoke_test.sh --no-market                상권 확인을 건너뜀
#
# 종료 코드: 모두 통과하면 0, 하나라도 실패하면 1.
# 확인하는 것
#   /api/health     200, 모드와 키 유무, 리뷰 분석 상태 ok, 막힘 목록(blocking) 비어 있음
#   /api/briefing   200, 리뷰 건수 > 0 (--expect-reviews 를 주면 그 건수와 같음)
#   /api/cards 와 POST /api/cards/{id}/run (--generate 일 때만)   200, 초안이 1개 이상
#   맞춤 마케팅 (ic26-marketing)
#     비서 화면 서버를 거친 GET /api/marketing-survey/health   200 이면 모드 확인. 404 는 실패로 세지 않음(프록시가 없는 묶음
#       이거나 MARKETING_SURVEY_URL=off — 주의만 출력)
#     서버 안에서 직접 GET http://127.0.0.1:8030/health   200, live 면 키 있음, 기록 폴더에 쓸 수 있음
#       (/opt/ic26 이 있는 WAS 서버에서만 기본으로 봄. 웹 서버·PC 에서는 --marketing 을 줄 때만)
#     --generate 일 때 POST /plan (가게 이야기 글) 1회 — live 면 HCX 1~2번. 시험 방문자 기록은 끝나고 지움
#   상권 (ic26-market, 127.0.0.1:8766)
#     WAS 서버에서 서비스가 켜져 있거나 --market 이면: 직접 /health 200 (Host: 127.0.0.1:8766), 비서 화면 서버를 거친
#       GET /api/assistant/status 가 "ready" (자료·챗봇·연결이 모두 됨). 꺼져 있으면(자료를 아직 안 깜) 주의만 출력
#     --generate 일 때 서랍처럼 조건 맞추기(POST /api/assistant/setup) → 질문 1개 → 답이 자료 답(data_answer)인지.
#       live 면 HCX 1번쯤. 시험 대화는 끝나고 지움
set -uo pipefail

BASE="http://127.0.0.1:8000"; EXPECT=""; GENERATE=0; MKT=""; MKT_MODE=auto; MARKET_MODE=auto
while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="${2:-}"; shift ;;
    --marketing) MKT="${2:-}"; MKT_MODE=on; shift ;;
    --no-marketing) MKT_MODE=off ;;
    --market) MARKET_MODE=on ;;
    --no-market) MARKET_MODE=off ;;
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

# ── 맞춤 마케팅 ──
if [ "$MKT_MODE" = off ]; then
  echo "[4] 맞춤 마케팅은 건너뜀 (--no-marketing)"
else
  echo "[4] 맞춤 마케팅"
  PROXY_OK=0
  get mproxy /api/marketing-survey/health 30
  if [ "$STATUS" = 200 ] && [ "$(jq_ "$TMP/mproxy" 'd.get("service")')" = marketing-survey ]; then
    PROXY_OK=1
    ok "비서 화면 서버를 거친 /api/marketing-survey/health 200 (모드 $(jq_ "$TMP/mproxy" 'd.get("mode")'), 데모 $(jq_ "$TMP/mproxy" 'd.get("demo")'))"
  elif [ "$STATUS" = 404 ]; then
    echo "  주의  비서 화면 서버에 /api/marketing-survey/ 경로가 없음 (404). 프록시가 없는 묶음이거나 MARKETING_SURVEY_URL=off. 실패로 세지 않음"
  else
    bad "비서 화면 서버를 거친 /api/marketing-survey/health 가 HTTP $STATUS  → $(head -c 200 "$TMP/mproxy")  (ic26-marketing 이 꺼졌는지: systemctl status ic26-marketing)"
  fi

  if [ "$MKT_MODE" = auto ]; then
    if [ -d /opt/ic26/experiments/marketing ]; then MKT="http://127.0.0.1:8030"; else MKT=""; fi
  fi
  MKT="${MKT%/}"
  if [ -n "$MKT" ]; then
    : > "$TMP/mdirect"
    STATUS="$(curl -sS -m 30 -o "$TMP/mdirect" -w '%{http_code}' "$MKT/health" 2>"$TMP/mdirect.err")" || STATUS=000
    if [ "$STATUS" = 200 ] && [ "$(jq_ "$TMP/mdirect" 'd.get("service")')" = marketing-survey ]; then
      MMODE="$(jq_ "$TMP/mdirect" 'd.get("mode")')"; MKEY="$(jq_ "$TMP/mdirect" 'd.get("key_present")')"
      MDEMO="$(jq_ "$TMP/mdirect" 'd.get("demo")')"; MW="$(jq_ "$TMP/mdirect" 'd.get("records_dir_writable")')"
      ok "직접 $MKT/health 200"
      echo "        모드: $MMODE ($(jq_ "$TMP/mdirect" 'd.get("mode_source")'))   키 있음: $MKEY   데모: $MDEMO   기록 폴더 쓰기: $MW"
      if [ "$MMODE" = live ]; then [ "$MKEY" = True ] && ok "live 이고 키가 있음" || bad "live 인데 키가 없음 (CLOVA_API_KEY) → 저장된 예시로만 돎"; fi
      [ "$MMODE" = mock ] && echo "        (mock: 키가 있어도 HCX 를 부르지 않습니다. 실제 AI 결과가 아닙니다)"
      [ "$MW" = True ] && ok "기록 폴더에 쓸 수 있음" || bad "기록 폴더에 쓸 수 없음 (/var/lib/ic26/marketing 소유자 ic26 인지. install_was.sh 를 다시 돌림)"
    else
      bad "직접 $MKT/health HTTP $STATUS ($(head -c 200 "$TMP/mdirect.err"))  → systemctl status ic26-marketing / journalctl -u ic26-marketing -n 50"
    fi
  else
    echo "        서버 안 직접 확인은 건너뜀 (/opt/ic26 이 없음. 볼 주소는 --marketing http://127.0.0.1:8030)"
  fi

  if [ "$GENERATE" = 1 ]; then
    # 직접 주소가 있으면 그쪽, 없으면 비서 화면 서버를 거쳐서. 시험 방문자 id 로 쓰고 끝나면 그 기록만 지운다.
    # 비서 화면 서버를 거칠 때는 프록시가 쿼리의 visitor_id 를 버리고 쿠키의 방문자를 쓴다. 그래서 쿠키 파일로 한 방문자를 유지하고,
    # 끝나면 그 방문자의 '처음부터 다시'(DELETE /api/approvals)로 지운다 (이 요청이 그 방문자의 마케팅 기록도 지움).
    VIA=""
    if [ -n "$MKT" ]; then MURL="$MKT/api/marketing-survey"; VIA=direct; elif [ "$PROXY_OK" = 1 ]; then MURL="$BASE/api/marketing-survey"; VIA=proxy; else MURL=""; fi
    if [ -n "$MURL" ]; then
      VID="smoke$(date +%s)"
      QS="?visitor_id=$VID"; [ "$VIA" = proxy ] && QS=""
      BODY='{"state":{"node":"story_message","mode":"story","confirms":{},"raw":{"story_reason":"부모님 가게를 물려받아서","story_signature":"제육볶음 정식","story_keep":"매일 아침 장을 봐요"}}}'
      T0=$(date +%s); : > "$TMP/mplan"
      STATUS="$(curl -sS -m 120 -c "$TMP/mcookie" -b "$TMP/mcookie" -o "$TMP/mplan" -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d "$BODY" "$MURL/plan$QS" 2>"$TMP/mplan.err")" || STATUS=000
      T1=$(date +%s)
      if [ "$STATUS" = 200 ]; then
        N="$(jq_ "$TMP/mplan" 'len((d.get("drafts") or {}).get("naver_place_intro") or "")')"
        PDEMO="$(jq_ "$TMP/mplan" 'd.get("demo")')"
        if [ "${N:-0}" -gt 0 ] 2>/dev/null; then ok "맞춤 마케팅 /plan(가게 이야기 글) 200, 글 ${N}자, 데모 $PDEMO, $((T1 - T0))초"; else bad "/plan 200 인데 글이 없음"; fi
        if [ "${MMODE:-}" = live ] && [ "$PDEMO" != False ]; then bad "live 인데 데모 글이 나옴 (키·모드 확인)"; fi
      else
        bad "맞춤 마케팅 /plan HTTP $STATUS ($((T1 - T0))초)  → $(head -c 300 "$TMP/mplan")"
      fi
      if [ "$VIA" = proxy ]; then
        DEL="$(curl -sS -m 30 -b "$TMP/mcookie" -X DELETE "$BASE/api/approvals" 2>/dev/null)"
      else
        DEL="$(curl -sS -m 30 -X DELETE "$MURL/records?visitor_id=$VID" 2>/dev/null)"
      fi
      echo "        시험 방문자 기록 지움: $DEL"
    else
      echo "        맞춤 마케팅 글 생성은 건너뜀 (직접 주소도, 비서 화면을 거친 경로도 없음)"
    fi
  fi
fi

# ── 상권 (서랍의 상권 채팅) ──
if [ "$MARKET_MODE" = off ]; then
  echo "[5] 상권은 건너뜀 (--no-market)"
else
  echo "[5] 상권 (ic26-market)"
  WANT_MARKET=0; [ "$MARKET_MODE" = on ] && WANT_MARKET=1
  if [ -d /opt/ic26/services/market-analysis ]; then
    : > "$TMP/mkhealth"
    STATUS="$(curl -sS -m 10 -H 'Host: 127.0.0.1:8766' -o "$TMP/mkhealth" -w '%{http_code}' http://127.0.0.1:8766/health 2>/dev/null)" || STATUS=000
    if [ "$STATUS" = 200 ]; then
      WANT_MARKET=1; ok "직접 127.0.0.1:8766/health 200 ($(jq_ "$TMP/mkhealth" '",".join(d.get("features") or [])'))"
    elif [ "$WANT_MARKET" = 1 ] || systemctl is-active --quiet ic26-market.service 2>/dev/null; then
      WANT_MARKET=1; bad "직접 127.0.0.1:8766/health HTTP $STATUS  → systemctl status ic26-market / journalctl -u ic26-market -n 50"
    else
      echo "        상권 서비스가 꺼져 있음 (자료를 아직 깔지 않았으면 정상: deploy/install_market_data.sh). 실패로 세지 않음"
    fi
    if [ -f /var/lib/ic26/market-data.installed ]; then echo "        자료 묶음: $(head -n1 /var/lib/ic26/market-data.installed | cut -d= -f2)"; fi
  fi
  get mkstatus /api/assistant/status 30
  MSTATE="$(jq_ "$TMP/mkstatus" 'd.get("state")')"
  if [ "$STATUS" = 200 ] && [ "$MSTATE" = ready ]; then
    ok "비서 화면 서버를 거친 /api/assistant/status: ready (모델 연결 $(jq_ "$TMP/mkstatus" 'd.get("model_connected")'))"
  elif [ "$WANT_MARKET" = 1 ]; then
    bad "서랍 상태가 ready 가 아님 (HTTP $STATUS, state $MSTATE: $(jq_ "$TMP/mkstatus" 'd.get("message")'))"
  else
    echo "        서랍 상태: ${MSTATE:-HTTP $STATUS} (상권 서비스를 켜지 않은 서버면 정상)"
  fi
  if [ "$GENERATE" = 1 ] && [ "$MSTATE" = ready ]; then
    T0=$(date +%s); : > "$TMP/mksetup"
    STATUS="$(curl -sS -m 90 -c "$TMP/mkcookie" -b "$TMP/mkcookie" -o "$TMP/mksetup" -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{}' "$BASE/api/assistant/setup" 2>/dev/null)" || STATUS=000
    COND="$(jq_ "$TMP/mksetup" '" · ".join(str((d.get("conditions") or {}).get(k) or "?") for k in ("area_name", "industry_name", "period_label"))')"
    if [ "$STATUS" = 200 ] && [ "$(jq_ "$TMP/mksetup" 'd.get("state")')" = ready ]; then ok "조건 맞추기: $COND"; else bad "조건 맞추기 HTTP $STATUS → $(head -c 300 "$TMP/mksetup")"; fi
    : > "$TMP/mkmsg"
    STATUS="$(curl -sS -m 90 -c "$TMP/mkcookie" -b "$TMP/mkcookie" -o "$TMP/mkmsg" -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{"text":"요일별 매출 알려줘"}' "$BASE/api/assistant/messages" 2>/dev/null)" || STATUS=000
    T1=$(date +%s)
    KIND="$(jq_ "$TMP/mkmsg" '(d.get("reply") or {}).get("kind")')"
    if [ "$STATUS" = 200 ] && [ "$KIND" = data_answer ]; then
      ok "질문 '요일별 매출 알려줘' → 자료 답 ($((T1 - T0))초, 답 $(jq_ "$TMP/mkmsg" 'len((d.get("reply") or {}).get("text") or "")')자)"
    else
      bad "질문 답이 자료 답이 아님 (HTTP $STATUS, kind $KIND) → $(head -c 300 "$TMP/mkmsg")"
    fi
    curl -sS -m 30 -b "$TMP/mkcookie" -o /dev/null -X DELETE "$BASE/api/assistant/conversation" 2>/dev/null && echo "        시험 대화 지움"
  fi
fi

echo
if [ "$FAIL" = 0 ]; then echo "결과: 모두 통과"; else echo "결과: 실패가 있습니다"; fi
[ -f /opt/ic26/REVISION ] && echo "서버의 커밋: $(head -n1 /opt/ic26/REVISION)"
exit "$FAIL"
