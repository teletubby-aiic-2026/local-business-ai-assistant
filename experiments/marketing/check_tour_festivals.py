"""
한국관광공사 TourAPI(국문 관광정보 서비스) 행사·축제 정보로 업종 맞춤 행사가 얼마나 있는지 확인 (확인용)

준비
  1. 공공데이터포털(data.go.kr)에서 '한국관광공사_국문 관광정보 서비스_GW' 활용신청 (보통 바로 승인)
  2. 마이페이지에서 일반 인증키 중 **Decoding** 키를 복사

실행 (marketing 폴더에서)
  python check_tour_festivals.py
  (키를 물어봄. 또는 환경변수 TOUR_API_KEY)

저장: data/tour_festivals_raw.json (원본), 화면에 그룹별 개수와 예시 출력
※ 행사 이미지(firstimage)는 저작권 조건이 따로 있을 수 있어 쓰지 않는다.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

BASE = "https://apis.data.go.kr/B551011/KorService2/searchFestival2"
GROUPS = {
    "먹거리 (음식점·카페)": r"푸드|먹거리|음식|미식|맛|요리|야시장|푸드트럭|커피|빵|디저트|와인|맥주|막걸리|김장|떡|치맥|미각",
    "장터·마켓 (옷가게·소품)": r"마켓|장터|플리|벼룩|프리마켓|아트마켓|바자|나눔장터|직거래|마르쉐|야시장",
    "패션·디자인 (옷가게)": r"패션|의류|디자인|빈티지|업사이클|공예|핸드메이드",
}


def fetch(key, extra):
    params = {"serviceKey": key, "MobileOS": "ETC", "MobileApp": "local-ai-assistant", "_type": "json",
              "numOfRows": 1000, "pageNo": 1, "arrange": "C",
              "eventStartDate": date.today().strftime("%Y%m01"), **extra}
    url = BASE + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as res:
            text = res.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None, f"JSON이 아닌 응답 (키 오류일 가능성): {text[:300]}"
    body = data.get("response", {}).get("body", {})
    items = body.get("items") or {}
    items = items.get("item", []) if isinstance(items, dict) else []
    if isinstance(items, dict):
        items = [items]
    header = data.get("response", {}).get("header", {})
    return items, f"{header.get('resultCode')} {header.get('resultMsg')} · 총 {body.get('totalCount')}건"


def main():
    key = os.environ.get("TOUR_API_KEY") or input("TourAPI 인증키(Decoding): ").strip()

    # 서울만 받기: KorService2에서 지역 파라미터 이름이 바뀌었을 수 있어 두 가지를 차례로 시도
    items, msg = fetch(key, {"areaCode": 1})
    print("areaCode=1 →", msg)
    if not items:
        items, msg = fetch(key, {"lDongRegnCd": 11})
        print("lDongRegnCd=11 →", msg)
    if not items:
        items, msg = fetch(key, {})
        print("지역 조건 없이 →", msg)
        items = [x for x in (items or []) if "서울" in str(x.get("addr1", ""))]
    if not items:
        print("\n받은 행사가 없어요. 위 메시지를 그대로 보내 주세요.")
        return

    Path("data").mkdir(exist_ok=True)
    with open("data/tour_festivals_raw.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    today = date.today().strftime("%Y%m%d")
    upcoming = [x for x in items if str(x.get("eventenddate", "")) >= today and "서울" in str(x.get("addr1", ""))]
    print(f"\n서울 행사 {len([x for x in items if '서울' in str(x.get('addr1', ''))])}건 중 아직 안 끝난 행사 {len(upcoming)}건")
    print("응답 항목 이름:", ", ".join(sorted(items[0].keys())))

    for name, pat in GROUPS.items():
        hits = [x for x in upcoming if re.search(pat, str(x.get("title", "")))]
        gu = Counter(str(x.get("addr1", "")).split()[1] if len(str(x.get("addr1", "")).split()) > 1 else "?" for x in hits)
        print(f"\n[{name}] {len(hits)}건 · 자치구: {', '.join(f'{g}({c})' for g, c in gu.most_common(5))}")
        for x in hits[:8]:
            print(f"  - {x.get('title')} | {x.get('addr1')} | {x.get('eventstartdate')}~{x.get('eventenddate')}")

    print("\n[전체 목록 앞 15개]")
    for x in upcoming[:15]:
        print(f"  - {x.get('title')} | {x.get('addr1')} | {x.get('eventstartdate')}~{x.get('eventenddate')}")


if __name__ == "__main__":
    main()
