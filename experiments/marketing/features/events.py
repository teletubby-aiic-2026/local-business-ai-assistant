"""
서울시 문화행사 정보(OA-23041) 불러오기 + 데이터 품질 확인 + 가게 주변 행사 찾기

실행 방법
  python -m features.events
  (처음에 API 키를 물어봄. 또는 환경변수 SEOUL_API_KEY에 넣어 두면 안 물어봄)

결과 파일 (data/ 폴더에 생성)
  events_raw.json      : 전체 행사 원본
  events_quality.txt   : 항목별 빈 값 비율 (기능 정의서 12절 미확정 항목 확인용)
  events_nearby.json   : 가게 반경 안, 앞으로 기간 안의 행사 (find_nearby_events 결과 예시)

※ API 키는 코드나 깃허브에 올리지 마세요.
"""

import json
import math
import os
import urllib.request
from datetime import date, datetime, timedelta

import config

# ── 테스트용 설정 (자유롭게 바꿔도 됨) ─────────────────────────
STORE_NAME = "예시 가게 (성수역 근처)"
STORE_LAT = 37.5446   # 가게 위도
STORE_LNG = 127.0559  # 가게 경도
RADIUS_KM = 2.0       # 반경 (km)
DAYS_AHEAD = 30       # 오늘부터 며칠 뒤 행사까지
# ─────────────────────────────────────────────────────────────

LONG_EVENT_DAYS = 60  # 이보다 길면 '상시' 행사로 분류 (이번 주 추천에서 뒤로)

# 사람이 많이 모이는 종류일수록 높게 (테스트하면서 조정)
CATEGORY_SCORE = {
    "축제-문화/예술": 15, "축제-전통/역사": 15, "축제-자연/경관": 15, "축제-시민화합": 15, "축제-기타": 15,
    "콘서트": 12, "클래식": 10, "국악": 10, "무용": 10, "뮤지컬/오페라": 12, "연극": 12,
    "영화": 8, "전시/미술": 8, "독주/독창회": 8,
    "교육/체험": 3, "기타": 8,
}

SERVICE = "culturalEventInfo"
PAGE_SIZE = 1000  # 서울 열린데이터광장은 한 번에 최대 1000건


def fetch_page(key, start, end):
    url = f"http://openapi.seoul.go.kr:8088/{key}/json/{SERVICE}/{start}/{end}/"
    with urllib.request.urlopen(url, timeout=30) as res:
        data = json.loads(res.read().decode("utf-8"))
    if SERVICE not in data:
        # 키 오류 등은 RESULT만 옴
        raise RuntimeError(f"API 오류: {data.get('RESULT', data)}")
    body = data[SERVICE]
    return body["list_total_count"], body.get("row", [])


def fetch_all(key):
    total, rows = fetch_page(key, 1, PAGE_SIZE)
    print(f"전체 행사 수: {total}건")
    start = PAGE_SIZE + 1
    while start <= total:
        _, more = fetch_page(key, start, start + PAGE_SIZE - 1)
        rows.extend(more)
        print(f"  {len(rows)}/{total}건 받음")
        start += PAGE_SIZE
    return rows


def is_empty(v):
    return v is None or str(v).strip() in ("", "-", "null", "None")


def quality_report(rows):
    fields = sorted({k for r in rows for k in r.keys()})
    lines = [f"전체 {len(rows)}건 기준 항목별 빈 값 비율", ""]
    for f in fields:
        empty = sum(1 for r in rows if is_empty(r.get(f)))
        lines.append(f"{f:<12} 빈 값 {empty:>5}건 ({empty / len(rows) * 100:5.1f}%)")
    return "\n".join(lines)


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def get_coords(r):
    """LAT/LOT 값이 서로 바뀌어 들어온 경우도 처리 (서울 위도는 약 37, 경도는 약 127)."""
    a, b = to_float(r.get("LAT")), to_float(r.get("LOT"))
    if a is None or b is None:
        return None
    if 33 < a < 39 and 124 < b < 132:
        return a, b
    if 33 < b < 39 and 124 < a < 132:
        return b, a
    return None


def distance_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def parse_date(v):
    if is_empty(v):
        return None
    s = str(v).strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def find_nearby(rows):
    today = date.today()
    until = today + timedelta(days=DAYS_AHEAD)
    found, no_coords, no_dates = [], 0, 0
    for r in rows:
        coords = get_coords(r)
        if coords is None:
            no_coords += 1
            continue
        s, e = parse_date(r.get("STRTDATE")), parse_date(r.get("END_DATE"))
        if s is None or e is None:
            no_dates += 1
            continue
        if e < today or s > until:
            continue
        d = distance_km(STORE_LAT, STORE_LNG, *coords)
        if d > RADIUS_KM:
            continue
        days = (e - s).days + 1
        found.append({
            "추천점수": score_event(r.get("CODENAME"), s, e, d, today),
            "구분": "상시" if days > LONG_EVENT_DAYS else "기간 한정",
            "기간_일수": days,
            "이름": r.get("TITLE"),
            "분류": r.get("CODENAME"),
            "자치구": r.get("GUNAME"),
            "장소": r.get("PLACE"),
            "기간": f"{s} ~ {e}",
            "유무료": r.get("IS_FREE"),
            "이용대상": r.get("USE_TRGT"),
            "거리_km": round(d, 2),
            "출처": "서울시 문화행사 정보 (서울 열린데이터광장)",
            "행사_시간": r.get("PRO_TIME"),
            "문의처": r.get("INQUIRY"),
            "링크": r.get("ORG_LINK") or r.get("HMPG_ADDR"),
        })
    found.sort(key=lambda x: (x["구분"] == "상시", -x["추천점수"], x["거리_km"]))
    return found, no_coords, no_dates


def score_event(codename, s, e, d, today):
    """홍보에 쓸 만한 행사일수록 높은 점수 (0~100). 기준은 테스트하면서 조정."""
    score = 0
    # 1) 가까울수록 (최대 40점)
    score += max(0, 40 * (1 - d / RADIUS_KM))
    # 2) 짧고 집중된 행사일수록 사람이 몰림 (최대 25점)
    days = (e - s).days + 1
    score += 25 if days <= 3 else 15 if days <= 14 else 5 if days <= LONG_EVENT_DAYS else 0
    # 3) 주말이 끼어 있으면 (10점)
    if any((s + timedelta(i)).weekday() >= 5 for i in range(min(days, 7))):
        score += 10
    # 4) 행사 종류 (최대 15점)
    score += CATEGORY_SCORE.get(codename or "", 5)
    # 5) 2주 안에 시작하면 지금 준비할 가치 (10점)
    if s <= today + timedelta(days=14):
        score += 10
    return round(score)


def main():
    key = os.environ.get("SEOUL_API_KEY") or input("서울 열린데이터광장 API 키: ").strip()
    rows = fetch_all(key)

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    with open(config.DATA_DIR / "events_raw.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    report = quality_report(rows)
    nearby, no_coords, no_dates = find_nearby(rows)
    report += (
        f"\n\n좌표가 없거나 잘못된 행사: {no_coords}건"
        f"\n시작일·종료일을 읽을 수 없는 행사: {no_dates}건"
        f"\n\n[{STORE_NAME}] 반경 {RADIUS_KM}km, 앞으로 {DAYS_AHEAD}일 안 행사: {len(nearby)}건"
    )
    with open(config.DATA_DIR / "events_quality.txt", "w", encoding="utf-8") as f:
        f.write(report)
    with open(config.DATA_DIR / "events_nearby.json", "w", encoding="utf-8") as f:
        json.dump(nearby, f, ensure_ascii=False, indent=2)

    print()
    print(report)
    print()
    for ev in nearby[:10]:
        print(f"- [{ev['구분']} · {ev['추천점수']}점] {ev['이름']} | {ev['장소']} | {ev['기간']} | {ev['유무료']} | {ev['거리_km']}km")
    print("\n결과 파일: data/events_raw.json, data/events_quality.txt, data/events_nearby.json")


if __name__ == "__main__":
    main()
