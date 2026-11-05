"""
업종에 맞는 행사가 서울시 문화행사 데이터에 얼마나 있는지 세어 보는 확인용 스크립트 (API 호출 없음)

실행: marketing 폴더에서  python check_event_types.py
읽는 파일: data/events_raw.json (seoul_events / features/events.py 실행으로 생긴 전체 원본)
"""

import json
import re
from collections import Counter
from datetime import date

GROUPS = {
    "먹거리 (음식점·카페)": r"푸드|먹거리|음식|미식|맛집|요리|야시장|푸드트럭|커피|빵|디저트|와인|맥주|막걸리|김장|떡",
    "장터·마켓 (옷가게·소품)": r"마켓|장터|플리|벼룩|프리마켓|아트마켓|바자회|나눔장터|직거래",
    "패션·디자인 (옷가게)": r"패션|의류|옷|디자인|빈티지|업사이클|새활용|공예",
    "축제 (모든 업종)": r"축제|페스티벌|페스타",
}

rows = json.load(open("data/events_raw.json", encoding="utf-8"))
today = date.today().isoformat()
upcoming = [r for r in rows if str(r.get("END_DATE", ""))[:10] >= today]
print(f"전체 {len(rows)}건 중 아직 안 끝난 행사 {len(upcoming)}건\n")

print("분류(CODENAME)별 개수 (안 끝난 행사)")
for k, v in Counter(r.get("CODENAME") for r in upcoming).most_common():
    print(f"  {k}: {v}")

for name, pat in GROUPS.items():
    hits = [r for r in upcoming if re.search(pat, f"{r.get('TITLE', '')} {r.get('CODENAME', '')}")]
    gu = Counter(r.get("GUNAME") for r in hits).most_common(5)
    print(f"\n[{name}] {len(hits)}건 · 많은 자치구: {', '.join(f'{g}({c})' for g, c in gu)}")
    for r in hits[:5]:
        print(f"  - {r.get('TITLE')} | {r.get('GUNAME')} {r.get('PLACE')} | {str(r.get('STRTDATE'))[:10]}~{str(r.get('END_DATE'))[:10]}")
