"""
S1 사장님 말투 테스트 (build_tone_profile + generate_post) v3 — 칭찬 리뷰를 재료로

질문: 같은 행사 홍보를 말투가 다른 가게 3곳에 넣으면, 정말 가게마다 다르게 나오는가?

실행 방법
  python -m tests.test_tone   (CLOVA Studio API 키 필요, 약 12~20번 호출 · 150원 안쪽)

결과 파일: results/tone_results.json / results/tone_results.md
※ 가게와 글은 모두 테스트용으로 만든 예시(합성 데이터)입니다.
"""

import json

import config
from features import tone as T
from samples.stores import TONE_STORES as STORES

# 행사 2개 (S2 테스트에서 쓴 실제 서울시 행사 정보, 사람 이름 제거)
EVENTS = [
    {"이름": "연극 [점프x컷]", "핵심어": "점프x컷", "장소": "우란문화재단", "날짜": "11월 7일(토)~11월 15일(일)", "도보": 3},
    {"이름": "제2회 호호랑 친구들 - 수집가마켓", "핵심어": "수집가마켓", "장소": "커먼그라운드", "날짜": "11월 7일(토)~11월 8일(일)", "도보": 17},
]


# ── 실행 ─────────────────────────────────────────────────────
def main():
    key = config.get_api_key() or input("CLOVA Studio API 키: ").strip()
    profiles = {s["이름"]: T.build_profile(s) for s in STORES}
    for s in STORES:
        print(f"\n[{s['이름']}] 말투 프로필\n{T.profile_text(profiles[s['이름']])}")

    rows = []
    for ev in EVENTS:
        for s in STORES:
            p = profiles[s["이름"]]
            for mode in (False, True):
                tag = "말투 적용" if mode else "기본(말투 없음)"
                print(f"\n{ev['이름']} × {s['이름']} · {tag} ...", end=" ", flush=True)
                g = T.generate(s, ev, p, mode, key, stores=STORES)
                if "오류" in g:
                    print("오류", g["오류"][:200])
                    rows.append({"행사": ev["이름"], "가게": s["이름"], "방식": tag, "오류": g["오류"]})
                    continue
                print(f"→ 판별: {g['판별된_가게']} · 사실 {sum(g['사실점검'].values())}/{len(g['사실점검'])}"
                      f" · 말투 {sum(g['말투점검'].values())}/{len(g['말투점검'])}")
                rows.append({"행사": ev["이름"], "가게": s["이름"], "방식": tag, **g})

    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.RESULTS_DIR / "tone_results.json", "w", encoding="utf-8") as f:
        json.dump({"프로필": profiles, "결과": rows}, f, ensure_ascii=False, indent=2)

    ok = [r for r in rows if "오류" not in r]
    def stat(tag):
        rs = [r for r in ok if r["방식"] == tag]
        n = max(len(rs), 1)
        return {
            "n": len(rs),
            "구분": sum(r["판별된_가게"] == r["가게"] for r in rs),
            "사실": sum(all(r["사실점검"].values()) for r in rs),
            "말투": sum(all(r["말투점검"].values()) for r in rs),
            "지어내기": sum(all(r["지어내기점검"].values()) for r in rs if r["지어내기점검"]),
            "1차": sum(r["1차_통과"] for r in rs),
            "요금": round(sum(r["won"] for r in rs), 1),
        }
    b, t = stat("기본(말투 없음)"), stat("말투 적용")

    L = ["# 사장님 말투 테스트 결과 (v3: 칭찬 리뷰를 재료로, 후보 2개)", "",
         f"모델: {T.MODEL} · 가게 3곳 × 행사 2개 · 가게와 예전 글은 합성 데이터", "",
         "| | 기본 (말투 정보 없음) | 말투 적용 |", "|---|---|---|",
         f"| **말투 구분 정확도** (글만 보고 어느 가게인지 맞힘) | {b['구분']}/{b['n']} | **{t['구분']}/{t['n']}** |",
         f"| 사장님 말투 점검 통과 | {b['말투']}/{b['n']} | {t['말투']}/{t['n']} (1차 {t['1차']}/{t['n']}) |",
         f"| 사실 유지 점검 통과 | {b['사실']}/{b['n']} | {t['사실']}/{t['n']} |",
         f"| 지어내기 점검 통과 (없는 음식·과장·반복·어색한 말) | - | {t['지어내기']}/{t['n']} |",
         f"| 예상 요금 | 약 {b['요금']}원 | 약 {t['요금']}원 |", "",
         "> 말투 구분 정확도: 결과 글의 높임 방식·문장 길이·이모지·느낌표·ㅋㅎ를 측정해, 세 가게의 예전 글 중 가장 가까운 가게를 고른 결과가 실제 가게와 같은 비율", "",
         "> 코드 점검은 형식만 봅니다. 자연스러운지는 아래 각 후보의 '자연스러움 __/5' 칸에 사람이 직접 점수를 적어 주세요.", "",
         "## 가게별 말투 프로필 (코드 측정)", ""]
    for s in STORES:
        L += [f"**{s['이름']}** ({s['업종']})", T.profile_text(profiles[s["이름"]]),
              "- 칭찬 리뷰(재료): " + " / ".join(s.get("칭찬 리뷰", [])), ""]
    for ev in EVENTS:
        L += [f"## {ev['이름']}", "", f"초안 예시: {T.draft(STORES[0], ev)}", ""]
        for s in STORES:
            L.append(f"### {s['이름']}")
            for r in ok:
                if r["행사"] != ev["이름"] or r["가게"] != s["이름"]:
                    continue
                if r["방식"] != "말투 적용":
                    fails = [k for k, v in r["사실점검"].items() if not v]
                    L.append(f"- **{r['방식']}** (판별: {r['판별된_가게']}{', 실패: ' + ', '.join(fails) if fails else ''})")
                    L.append("  > " + r["글"].replace("\n", "\n  > "))
                    continue
                L.append(f"- **말투 적용** (판별: {r['판별된_가게']}, 시도 {r['시도']}번"
                         f"{', 남은 실패: ' + ', '.join(r['최종_실패']) if r['최종_실패'] else ''})")
                for i, c in enumerate(r.get("후보", []), 1):
                    mark = "통과" if not c["실패"] else "실패: " + ", ".join(c["실패"])
                    L.append(f"  - 후보 {i} ({mark}) · 자연스러움 __/5")
                    L.append("    > " + c["글"].replace("\n", "\n    > "))
            L.append("")
    with open(config.RESULTS_DIR / "tone_results.md", "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    print(f"\n말투 구분 정확도: 기본 {b['구분']}/{b['n']} → 말투 적용 {t['구분']}/{t['n']}")
    print(f"말투 점검 통과(말투 적용): {t['말투']}/{t['n']} · 사실 유지: {t['사실']}/{t['n']}")
    print("결과 파일: results/tone_results.json, results/tone_results.md")


if __name__ == "__main__":
    main()
