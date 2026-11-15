"""
S2 업종 맞춤 행사 추천 + 어필 계획 테스트

필요한 파일 (먼저 실행해 둘 것)
  data/events_raw.json          ← python -m features.events (서울시 문화행사)
  data/tour_festivals_raw.json  ← python -m scripts.check_tour_festivals (한국관광공사 TourAPI)

실행 (marketing 폴더에서)
  python -m tests.test_event_plan
  CLOVA 호출: 가게 4곳 × 계획 최대 4개 × (어필 포인트 + 주변형 홍보글) → 약 20~40번, 200원 안쪽

결과: results/event_plan_results.md / .json
※ 가게·리뷰는 합성 데이터입니다.
"""

import json
from collections import Counter
from datetime import date

import config
from features import event_plan as P
from features import tone as T
from samples.stores import STORES, SEONGSU

TODAY = date.today()


def load(name):
    path = config.DATA_DIR / name
    if not path.exists():
        print(f"※ {path} 가 없어요. 이 데이터는 빼고 진행해요.")
        return []
    return json.load(open(path, encoding="utf-8"))


def main():
    key = config.get_api_key() or input("CLOVA Studio API 키: ").strip()
    seoul, tour = load("events_raw.json"), load("tour_festivals_raw.json")
    events = P.load_events(seoul, tour, TODAY)
    types = Counter(e["유형"] for e in events)
    print(f"합친 행사 {len(events)}건 · 유형: " + ", ".join(f"{k} {v}" for k, v in types.most_common()))

    results = []
    for s in STORES:
        prof = T.build_profile(s)
        join, near = P.match(s, events, TODAY)
        print(f"\n[{s['이름']} · {s['업종']}] 참여형 {len(join)}개 · 주변형 {len(near)}개")
        plans = []
        for mode, lst in (("참여형", join), ("주변형", near)):
            for e in lst:
                print(f"  {mode}: {e['이름']} ...", end=" ", flush=True)
                pl = P.build_plan(s, e, mode, key, TODAY, tone_profile=prof)
                print("오류" if "오류" in pl else f"포인트 {len(pl['어필_포인트'])}개 · 남은 실패 {pl['점검_실패'] or '없음'}")
                plans.append(pl)
        results.append({"가게": s["이름"], "업종": s["업종"], "계획": plans})

    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.RESULTS_DIR / "event_plan_results.json", "w", encoding="utf-8") as f:
        json.dump({"행사_유형": dict(types), "결과": results}, f, ensure_ascii=False, indent=2, default=str)

    allp = [p for r in results for p in r["계획"] if "오류" not in p]
    L = ["# 업종 맞춤 행사 추천 + 어필 계획", "",
         f"기준일: {TODAY} · 가게 위치: 성수역 근처 (합성 데이터) · 모델: {P.MODEL}", "",
         f"- 합친 행사 {len(events)}건 (서울시 문화행사 {len(seoul)}건 + TourAPI {len(tour)}건, 지난 행사·중복 제외)",
         "- 유형: " + ", ".join(f"{k} {v}" for k, v in types.most_common()),
         f"- 어필 포인트 점검 통과: {sum(not p['점검_실패'] for p in allp)}/{len(allp)} (1차 {sum(p['1차_통과'] for p in allp)}/{len(allp)})",
         f"- 예상 요금: 약 {sum(p.get('won', 0) for p in allp):.1f}원", "",
         "> 참여형: 업종이 맞는 행사에 셀러·부스로 나가는 계획 (서울 전체) · 주변형: 근처 행사 방문객을 가게로 이끄는 계획 (반경 3km)", ""]
    for r in results:
        L += [f"## {r['가게']} ({r['업종']})", ""]
        if not r["계획"]:
            L += ["맞는 행사가 없어요. (이번 달 데이터 기준)", ""]
        for p in r["계획"]:
            L += [f"### [{p['활용 방식']}] {p['행사']}", "",
                  f"- 유형 {p['유형']} · {p['기간']} · {p['장소']}",
                  f"- {p['거리']} · 문의처 {p['문의처']} · 출처 {p['출처']}",
                  f"- **맞는 이유**: {p['맞는 이유']}"] + ([f"- ⚠ {p['확인 필요']}"] if p.get("확인 필요") else [])
            if "오류" in p:
                L += [f"- 오류: {p['오류'][:200]}", ""]
                continue
            L.append("- **어필 포인트** (AI)" + (f" — 남은 실패: {', '.join(p['점검_실패'])}" if p["점검_실패"] else ""))
            cites = p.get("근거") or [""] * len(p["어필_포인트"])
            L += [f"  - {x}" + (f"  _(근거: {c})_" if c else "") for x, c in zip(p["어필_포인트"], cites)]
            if p.get("행사 맞춤 아이디어"):
                L.append("- **이 행사에서 해 볼 것** (행사 유형별, 코드)")
                L += [f"  - {x}" for x in p["행사 맞춤 아이디어"]]
            L.append("- **할 일** (코드 계산)" + (f" — {p['일정 메모']}" if p["일정 메모"] else ""))
            L += [f"  - {t['날짜']}: {t['할 일']}" for t in p["할 일"]]
            if p.get("홍보글_점검_실패"):
                L.append("- **홍보글**: 점검을 통과한 후보가 없어요 → " + " / ".join(p["홍보글_점검_실패"]))
            for i, post in enumerate(p.get("홍보글_후보", []), 1):
                L.append(f"- **홍보글 후보 {i}** · 자연스러움 __/5")
                L.append("  > " + post.replace("\n", "\n  > "))
            L.append("")
    with open(config.RESULTS_DIR / "event_plan_results.md", "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n결과 파일: results/event_plan_results.md, results/event_plan_results.json")


if __name__ == "__main__":
    main()
