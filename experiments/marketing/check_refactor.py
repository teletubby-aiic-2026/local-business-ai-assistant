import json
from datetime import date
from features import notice
from tests import test_notice

TODAY = date(2026, 11, 5)  # 테스트 기준일
rows = json.load(open("results/notice_results.json", encoding="utf-8"))
ok = 0
for r, case in zip(rows, test_notice.CASES):
    info = notice.to_info_b(r["B"]["추출"], notice=case["공지"], today=TODAY)
    good = all(test_notice.score(info, case["정답"]).values())
    ok += good
    if not good:
        print("다름:", case["공지"])
print(f"휴무 공지 재채점: {ok}/15 (정리 전 15/15)")