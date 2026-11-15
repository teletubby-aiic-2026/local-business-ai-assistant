"""
B2 휴무·영업시간 공지 테스트 (parse_notice + build_channel_notice)

비교 실험
- A방식: AI가 날짜를 직접 계산 (YYYY-MM-DD)
- B방식: AI는 원문 표현만 뽑고 코드가 계산 (우리 방식)
→ 같은 공지 15개로 두 방식의 정답률을 비교한다

실행 방법
  python -m tests.test_notice   (CLOVA Studio API 키 필요, 약 30번 호출 · 200원 안쪽)

결과 파일: results/notice_results.json / results/notice_results.md
※ API 키는 코드나 깃허브에 올리지 마세요.
"""

import json
from datetime import date

import clova
import config
from common import dates as D
from common import korean as K
from features import notice as N

TODAY = date(2026, 11, 5)  # 테스트 기준일 고정 (정답을 정해 두기 위해). 실제 서비스에서는 date.today()
RUN_A = True               # A방식(AI가 날짜 직접 계산)도 돌려서 비교할지

# ── 테스트 공지 15개와 정답 (기준일 2026-11-05 목) ───────────────
CASES = [
    {"공지": "11월 12일 수요일 내부 공사로 하루 쉽니다",
     "정답": {"종류": "임시휴무", "시작": "2026-11-12", "종료": "2026-11-12", "사유": "내부 공사", "확인필요": True},
     "메모": "11/12는 목요일 → 요일이 틀린 공지. 확인 필요로 잡아야 함"},
    {"공지": "다음 주 화요일 개인 사정으로 휴무합니다",
     "정답": {"종류": "임시휴무", "시작": "2026-11-10", "종료": "2026-11-10", "사유": "개인 사정"}},
    {"공지": "이번 주 토요일은 쉬어요~",
     "정답": {"종류": "임시휴무", "시작": "2026-11-07", "종료": "2026-11-07", "사유": ""}},
    {"공지": "내일 하루 쉽니다! 죄송해요ㅠ",
     "정답": {"종류": "임시휴무", "시작": "2026-11-06", "종료": "2026-11-06", "사유": ""}},
    {"공지": "11/14~11/16 가족 여행으로 휴무입니다",
     "정답": {"종류": "임시휴무", "시작": "2026-11-14", "종료": "2026-11-16", "사유": "가족 여행"}},
    {"공지": "다음 주부터 영업시간이 11시~22시로 바뀝니다",
     "정답": {"종류": "영업시간 변경", "시작": "2026-11-09", "종료": None, "여는": "11:00", "닫는": "22:00", "사유": ""}},
    {"공지": "12월 1일부터 매주 화요일 정기휴무입니다",
     "정답": {"종류": "정기휴무 변경", "시작": "2026-12-01", "종료": None, "정기휴무": "화", "사유": ""}},
    {"공지": "오늘은 재료 소진으로 3시에 마감합니다",
     "정답": {"종류": "단축영업", "시작": "2026-11-05", "종료": "2026-11-05", "닫는": "15:00", "사유": "재료 소진"}},
    {"공지": "모레는 오전 휴무, 오후 2시부터 문 엽니다",
     "정답": {"종류": "단축영업", "시작": "2026-11-07", "종료": "2026-11-07", "여는": "14:00", "사유": ""}},
    {"공지": "19일~20일 이틀간 쉬어갑니다",
     "정답": {"종류": "임시휴무", "시작": "2026-11-19", "종료": "2026-11-20", "사유": ""}},
    {"공지": "다음 달 3일은 휴무입니다",
     "정답": {"종류": "임시휴무", "시작": "2026-12-03", "종료": "2026-12-03", "사유": ""}},
    {"공지": "설 연휴 동안 쉽니다. 새해 복 많이 받으세요!",
     "정답": {"종류": "임시휴무", "확인필요": True, "사유": "설 연휴"},
     "메모": "날짜가 없음 → 지어내지 말고 확인 필요"},
    {"공지": "🙏 11.21(토) 매장 사정으로 휴무 🙏 #공지 #성수카페",
     "정답": {"종류": "임시휴무", "시작": "2026-11-21", "종료": "2026-11-21", "사유": "매장 사정"}},
    {"공지": "이번 주 일요일은 단체 예약으로 저녁 6시까지만 영업합니다",
     "정답": {"종류": "단축영업", "시작": "2026-11-08", "종료": "2026-11-08", "닫는": "18:00", "사유": "단체 예약"}},
    {"공지": "다음주 화수 쉽니다",
     "정답": {"종류": "임시휴무", "시작": "2026-11-10", "종료": "2026-11-11", "사유": ""}},
    {"공지": "모레 오후 2시에 문 열어",
     "정답": {"종류": "단축영업", "시작": "2026-11-07", "종료": "2026-11-07", "여는": "14:00", "사유": ""},
     "메모": "특정 하루 + '부터' 없음 → 영업시간 변경이 아니라 단축영업"},
]

PROMPT_A = """너는 가게 공지 글에서 정보를 뽑는 도우미다.
오늘 날짜를 기준으로 날짜를 계산해서 아래 JSON으로만 답한다.
{
  "종류": "임시휴무" | "단축영업" | "영업시간 변경" | "정기휴무 변경",
  "시작": "YYYY-MM-DD, 정할 수 없으면 '확인 필요'",
  "종료": "YYYY-MM-DD, 계속 적용이면 null, 정할 수 없으면 '확인 필요'",
  "여는": "HH:MM 또는 null", "닫는": "HH:MM 또는 null",
  "정기휴무": "요일 한 글자 또는 null",
  "사유": "글에 적힌 이유, 없으면 빈 문자열"
}
종류 기준: 하루~며칠 통째로 쉬면 임시휴무, 특정 날만 늦게 열거나 일찍 닫으면 단축영업,
어느 날부터 계속 영업시간이 바뀌면 영업시간 변경, 쉬는 요일이 바뀌면 정기휴무 변경."""


# ── 채점 ─────────────────────────────────────────────────────
def score(got, gold):
    """필드별 정답 여부. 확인필요 정답인 케이스는 '확인 필요로 잡았는지'만 본다."""
    res = {"종류": got.get("종류") == gold["종류"]}
    flagged = bool(got.get("확인필요"))
    if gold.get("확인필요"):
        res["확인 필요로 잡음"] = flagged
        return res
    res["날짜"] = str(got.get("시작")) == gold["시작"] and str(got.get("종료")) == str(gold["종료"])
    for k in ("여는", "닫는", "정기휴무"):
        if k in gold or got.get(k):
            res[k] = (got.get(k) or None) == gold.get(k)
    gs, ts = K.nospace(gold.get("사유", "")), K.nospace(got.get("사유", ""))
    res["사유"] = (gs == ts) or (gs and gs in ts and len(ts) <= len(gs) + 4)
    res["잘못된 확인 필요 없음"] = not flagged
    return res


def norm_a(a):
    if not a:
        return {}
    issues = []
    out = {"종류": a.get("종류"), "사유": a.get("사유") or ""}
    for k in ("시작", "종료"):
        v = a.get(k)
        if v in (None, "null", ""):
            out[k] = None
        elif "확인" in str(v):
            out[k] = None
            issues.append("확인 필요")
        else:
            out[k] = str(v)[:10]
    for k in ("여는", "닫는", "정기휴무"):
        v = a.get(k)
        out[k] = None if v in (None, "null", "") else str(v)
    out["확인필요"] = issues
    return out


# ── 실행 ─────────────────────────────────────────────────────
def main():
    key = config.get_api_key() or input("CLOVA Studio API 키: ").strip()
    results = []
    for i, case in enumerate(CASES, 1):
        notice, gold = case["공지"], case["정답"]
        print(f"[{i:02d}] {notice}")
        row = {"번호": i, "공지": notice, "정답": gold, "메모": case.get("메모", "")}

        ext, tries, cost, err = N.extract_b(key, notice)
        if err:
            print("   B 오류:", err[:200])
            row["B"] = {"오류": err}
        else:
            info = N.to_info_b(ext or {}, TODAY, notice)
            sc = score(info, gold)
            card = None
            if info["시작"] and not info["확인필요"]:
                card = N.build_notice(info)
            row["B"] = {"추출": ext, "시도": len(tries), "계산결과": {k: (str(v) if isinstance(v, date) else v) for k, v in info.items()},
                        "채점": sc, "정답": all(sc.values()), "결과물": card, **cost}
            print(f"   B(코드 계산): {'정답' if all(sc.values()) else '오답 ' + str([k for k, v in sc.items() if not v])}"
                  f"{' · 확인 필요: ' + ' / '.join(info['확인필요']) if info['확인필요'] else ''}")

        if RUN_A:
            r = clova.call(key, PROMPT_A, [{"role": "user", "content": f"오늘 날짜: {TODAY.isoformat()} ({D.WEEK[TODAY.weekday()]}요일)\n\n[공지 글]\n{notice}"}],
                            model=N.MODEL, temperature=0.1, max_tokens=512)
            if "error" in r:
                row["A"] = {"오류": r["error"]}
            else:
                a = norm_a(clova.parse_json(r["content"]))
                sc = score(a, gold)
                row["A"] = {"응답": r["content"], "채점": sc, "정답": all(sc.values()),
                            "tokens": r["tokens"], "seconds": r["seconds"], "won": r["won"]}
                print(f"   A(AI 계산):   {'정답' if all(sc.values()) else '오답 ' + str([k for k, v in sc.items() if not v])}")
        results.append(row)

    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.RESULTS_DIR / "notice_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    def acc(tag):
        rs = [r[tag] for r in results if tag in r and "오류" not in r[tag]]
        return sum(x["정답"] for x in rs), len(rs), sum(x.get("won", 0) for x in rs)

    b_ok, b_n, b_won = acc("B")
    lines = ["# 휴무·영업시간 공지 테스트 결과", "",
             f"기준일: {TODAY} ({D.WEEK[TODAY.weekday()]}) · 모델: {N.MODEL} · 가게: {N.STORE['가게 이름']} "
             f"({N.STORE['여는 시각']}~{N.STORE['닫는 시각']}, {'·'.join(N.STORE['휴무 요일'])}요일 휴무)", "",
             f"- **B방식 (AI는 원문 표현만, 날짜는 코드 계산): {b_ok}/{b_n} 정답**"]
    if RUN_A:
        a_ok, a_n, a_won = acc("A")
        lines.append(f"- A방식 (AI가 날짜 직접 계산): {a_ok}/{a_n} 정답")
        lines.append(f"- 예상 요금: B 약 {b_won:.1f}원, A 약 {a_won:.1f}원")
    lines += ["", "| # | 공지 | B 결과 | B 확인 필요 | A 결과 |", "|---|---|---|---|---|"]
    for r in results:
        b = r.get("B", {})
        a = r.get("A", {})
        bt = "오류" if "오류" in b else ("O" if b.get("정답") else "X " + ", ".join(k for k, v in b["채점"].items() if not v))
        at = "-" if not a else "오류" if "오류" in a else ("O" if a.get("정답") else "X " + ", ".join(k for k, v in a["채점"].items() if not v))
        flag = " / ".join(b.get("계산결과", {}).get("확인필요") or []) or "-"
        lines.append(f"| {r['번호']} | {r['공지']} | {bt} | {flag} | {at} |")
    lines += ["", "## 만들어진 공지 (B방식, 확인 필요가 없는 경우)", ""]
    for r in results:
        card = r.get("B", {}).get("결과물")
        if card:
            lines.append(f"**{r['번호']}. {r['공지']}**")
            lines.append(f"- 스마트플레이스 입력값: {json.dumps(card['스마트플레이스_입력값'], ensure_ascii=False)}")
            lines.append(f"- 소식 문구: {card['소식_문구']}")
            lines.append("")
    with open(config.RESULTS_DIR / "notice_results.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\nB방식(코드 계산) {b_ok}/{b_n} 정답" + (f" · A방식(AI 계산) {a_ok}/{a_n} 정답" if RUN_A else ""))
    print("결과 파일: results/notice_results.json, results/notice_results.md")


if __name__ == "__main__":
    main()
