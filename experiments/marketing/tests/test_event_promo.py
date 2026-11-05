"""
주변 행사 → 홍보 계획 테스트 (plan_event_promo) v6

실행 방법
  python -m tests.test_event_promo   (features.events를 먼저 실행해 data/events_nearby.json이 있어야 함)

결과 파일: results/promo_results.json / results/promo_results.md
※ API 키는 코드나 깃허브에 올리지 마세요.
"""

import json
from datetime import date

import config
from common import dates as D
from features import event_promo as fp

# ── 테스트 설정 ───────────────────────────────────────────────
TOP_N = 3
MODELS = ["HCX-005"]   # 비교가 필요하면 "HCX-007" 추가 (v1~v4에서 느리고 더 정확하지 않았음)
REPEAT = 3             # 같은 입력을 몇 번 돌려 볼지 (안정성 확인)


def main():
    key = config.get_api_key()
    today = date.today()

    with open(config.DATA_DIR / "events_nearby.json", encoding="utf-8") as f:
        events = [e for e in json.load(f) if e.get("구분") == "기간 한정"][:TOP_N]
    if not events:
        print("data/events_nearby.json에 '기간 한정' 행사가 없어요. features.events를 먼저 실행해 주세요.")
        return

    results = []
    for ev in events:
        start, _ = D.event_dates(ev)
        walk = D.walk_minutes(ev["거리_km"])
        tf = fp.time_facts(ev)
        methods = fp.pick_methods(ev, walk, today, tf)
        user_prompt = fp.build_user_prompt(ev, today.isoformat(), walk, methods, tf)
        fixed = {"올릴_날짜": fp.post_date(start, today).isoformat(), "도보_분": walk,
                 "올릴_곳": "네이버 플레이스 소식", "날짜_표기": D.date_label(ev), **tf,
                 "문의처": ev.get("문의처") or "없음", "손님 상황": fp.visit_situation(tf)}
        print(f"\n{ev['이름']}\n  홍보 방식: {', '.join(m['방식'] for m in methods)} · {fp.visit_situation(tf)}")
        for model in MODELS:
            for n in range(1, REPEAT + 1):
                print(f"  [{model} #{n}] ...", end=" ", flush=True)
                g = fp.generate_with_repair(model, key, user_prompt, ev, walk, methods, tf)
                if "오류" in g:
                    print("오류\n  ", g["오류"][:300])
                    results.append({"행사": ev["이름"], "모델": model, "회차": n, "오류": g["오류"]})
                    continue
                at = g["시도"]
                last = at[-1]
                status = "통과" if not last["실패"] else "사장님 확인 필요"
                print(f"1차 {'통과' if not at[0]['실패'] else '실패'} → {len(at)}번 시도 후 {status}")
                results.append({
                    "행사": ev["이름"], "모델": model, "회차": n, "홍보_방식": methods, "코드가_정한_값": fixed,
                    "1차_통과": not at[0]["실패"], "최종_통과": not last["실패"], "시도_횟수": len(at),
                    "1차_실패": at[0]["실패"], "최종_실패": last["실패"],
                    "최종_문구": fp.final_copies(last["계획"], tf), "대상_손님": (last["계획"] or {}).get("대상_손님"),
                    "시도_기록": at,
                    "토큰": sum(a["토큰"] for a in at), "시간_초": round(sum(a["시간_초"] for a in at), 1),
                    "예상요금_원": round(sum(a["요금_원"] for a in at), 2),
                })

    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.RESULTS_DIR / "promo_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    ok = [r for r in results if "오류" not in r]
    first = sum(r["1차_통과"] for r in ok)
    final = sum(r["최종_통과"] for r in ok)
    avg_try = sum(r["시도_횟수"] for r in ok) / max(len(ok), 1)
    lines = ["# 홍보 계획 테스트 결과 (v6 · 시간 문장 코드 생성 + 다시 쓰기)", "",
             f"테스트일: {today} · 가게: {fp.STORE['가게 이름']} ({fp.STORE['업종']}, {fp.STORE_HOURS_TXT})", "",
             f"- **1차 통과: {first}/{len(ok)}회**",
             f"- **다시 쓰기 후 최종 통과: {final}/{len(ok)}회** (최대 {fp.MAX_RETRY}번 다시 쓰기)",
             f"- 평균 시도 횟수: {avg_try:.1f}번",
             f"- 전체 예상 요금: 약 {sum(r['예상요금_원'] for r in ok):.1f}원", ""]
    lines += ["| 행사 | 회차 | 홍보 방식 | 1차 | 시도 | 최종 | 1차 실패 항목 | 시간 | 요금 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        if "오류" in r:
            lines.append(f"| {r['행사']} | {r['회차']} | - | 오류 | - | - | - | - | - |")
            continue
        lines.append(f"| {r['행사']} | {r['회차']} | {', '.join(m['방식'] for m in r['홍보_방식'])} | "
                     f"{'O' if r['1차_통과'] else 'X'} | {r['시도_횟수']} | {'O' if r['최종_통과'] else '확인 필요'} | "
                     f"{', '.join(r['1차_실패']) or '-'} | {r['시간_초']}초 | {r['예상요금_원']}원 |")
    shown = set()
    for r in ok:
        if r["행사"] not in shown:
            shown.add(r["행사"])
            lines += ["", f"## {r['행사']}", ""]
            for k, v in r["코드가_정한_값"].items():
                lines.append(f"- {k} (코드): {v}")
            for m in r["홍보_방식"]:
                lines.append(f"- 방식 선택 이유 · {m['방식']}: {m['이유']}")
        lines += ["", f"**{r['모델']} #{r['회차']}** ({'최종 통과' if r['최종_통과'] else '사장님 확인 필요: ' + ', '.join(r['최종_실패'])})", ""]
        lines.append(f"- 대상 손님: {r['대상_손님']}")
        for c in r["최종_문구"]:
            menus = c.get("내세울_메뉴") or []
            menus = ", ".join(menus) if isinstance(menus, list) else menus
            lines.append(f"- [{c['방식']}] {c['최종_문구']}  _(메뉴: {menus or '없음'})_")
    with open(config.RESULTS_DIR / "promo_results.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n1차 통과 {first}/{len(ok)}회 · 최종 통과 {final}/{len(ok)}회 · 평균 {avg_try:.1f}번 시도")
    print(f"전체 예상 요금: 약 {sum(r['예상요금_원'] for r in ok):.1f}원")
    print("결과 파일: results/promo_results.json, results/promo_results.md")


if __name__ == "__main__":
    main()
