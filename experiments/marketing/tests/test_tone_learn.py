"""
사장님 수정 학습 테스트 (API 없음, difflib만 사용)

실행: python -m tests.test_tone_learn
결과: results/tone_learn_results.md
"""

import copy
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from features import tone as T
from features import tone_learn as TL

# ── 테스트용 가게 3곳 (test_tone.py 의 STORES 축약) ────────────
STORES = [
    {
        "이름": "몽글커피", "업종": "카페",
        "메뉴": ["몽글 크림라떼", "아메리카노", "휘낭시에"],
        "예전 글": [
            "오늘은 비가 와서 그런지 따뜻한 라떼가 많이 나가네용 ☕ 몽글 크림라떼 아직 안 드셔보셨다면 꼭 드셔보세요!! 오늘도 좋은 하루 보내세요 🍀 #몽글커피 #성수카페",
            "휘낭시에 새로 구웠어요 🥐 버터 향 가득이에요! 금방 나가니까 서둘러 주세요 ㅎㅎ 오늘도 좋은 하루 보내세요 🍀 #몽글커피 #성수카페",
            "이번 주 원두 바꿨어요! 산미 적고 고소한 쪽이라 라떼랑 찰떡이에용 ☕ 오늘도 좋은 하루 보내세요 🍀 #몽글커피 #성수카페",
        ],
    },
    {
        "이름": "성수 숯불집", "업종": "고깃집",
        "메뉴": ["돼지 목살", "된장찌개", "냉면"],
        "예전 글": [
            "오늘 목살 들어왔습니다. 두께 좋습니다. 저녁에 뵙겠습니다. 감사합니다.",
            "주차는 건물 뒤편 이용 가능합니다. 단체 예약 받습니다. 감사합니다.",
            "날이 추워졌습니다. 된장찌개 맛이 좋습니다. 감사합니다.",
        ],
    },
    {
        "이름": "떡볶이 연구소", "업종": "분식",
        "메뉴": ["국물떡볶이", "김말이", "순대"],
        "예전 글": [
            "오늘 떡볶이 국물 진짜 잘 됐음ㅋㅋ 김말이 찍어 먹으면 끝남! 떡연 출근 완료 🔥 #떡볶이연구소",
            "순대 새로 들어옴! 쫄깃함 실화임 ㅋㅋ 떡연 출근 완료 🔥 #떡볶이연구소",
            "비 오는 날엔 국물떡볶이지! 포장도 됨~ 떡연 출근 완료 🔥 #떡볶이연구소",
        ],
    },
]

# ── 가짜 수정 기록 ──────────────────────────────────────────────

# 몽글커피: '특별한'을 계속 지움 (3건 중 3건)
EDITS_MONGLE = [
    ("특별한 몽글 크림라떼 한 잔 드셔보세요! ☕", "몽글 크림라떼 한 잔 드셔보세요! ☕", "2024-11-01"),
    ("특별한 휘낭시에와 함께 여유를 즐겨보세요 ☕", "휘낭시에와 함께 여유를 즐겨보세요 ☕", "2024-11-02"),
    ("특별한 라떼 한 잔으로 하루를 시작해보세요 ☕", "라떼 한 잔으로 하루를 시작해보세요 ☕", "2024-11-03"),
]

# 숯불집: 해요체를 합니다체로 계속 고침 (3건)
EDITS_SUTBUL = [
    ("오늘 목살 들어왔어요. 두께가 좋아요.", "오늘 목살 들어왔습니다. 두께 좋습니다.", "2024-11-01"),
    ("된장찌개 준비했어요. 고기랑 잘 어울려요.", "된장찌개 준비했습니다. 고기랑 잘 어울립니다.", "2024-11-02"),
    ("저녁 예약 받고 있어요. 단체도 가능해요.", "저녁 예약 받고 있습니다. 단체도 가능합니다.", "2024-11-03"),
]

# 떡볶이 연구소: 이모지를 계속 지움 (3건)
EDITS_TTEOK = [
    ("오늘 떡볶이 국물 잘 됐음ㅋㅋ 🔥🍜 김말이 찍어 먹으면 끝남!", "오늘 떡볶이 국물 잘 됐음ㅋㅋ 김말이 찍어 먹으면 끝남!", "2024-11-01"),
    ("순대 새로 들어옴! 🔥🎉 쫄깃함 실화임ㅋㅋ", "순대 새로 들어옴! 쫄깃함 실화임ㅋㅋ", "2024-11-02"),
    ("비 오는 날엔 국물떡볶이지! 🔥☔ 포장도 됨~", "비 오는 날엔 국물떡볶이지! 포장도 됨~", "2024-11-03"),
]

# 1건만 있는 기록 (제안 안 나와야 함)
EDITS_SINGLE = [
    ("특별한 라떼 한 잔 드셔보세요!", "라떼 한 잔 드셔보세요!", "2024-11-01"),
]


def build_log(edits):
    log = []
    for ai, owner, date in edits:
        TL.record_edit(log, ai, owner, date)
    return log


def test_record_edit():
    results = []
    log = build_log(EDITS_MONGLE)
    assert len(log) == 3
    assert "특별한" in log[0]["지운_표현"]
    results.append("  - record_edit: 3건 기록됨, '특별한' 지운_표현에 포함 ✅")

    log2 = build_log(EDITS_SUTBUL)
    assert log2[0]["높임_전"] == "해요체"
    assert log2[0]["높임_후"] == "합니다체"
    results.append("  - record_edit(숯불집): 높임 해요체→합니다체 감지 ✅")

    log3 = build_log(EDITS_TTEOK)
    assert all(e["이모지_삭제"] for e in log3)
    results.append("  - record_edit(떡볶이): 이모지_삭제=True 감지 ✅")

    return results


def test_suggest_mongle():
    results = []
    profile = T.build_profile(STORES[0])
    log = build_log(EDITS_MONGLE)
    suggestions = TL.suggest(log, profile)
    kinds = [s["종류"] for s in suggestions]
    assert "쓰지 않는 표현" in kinds, f"'쓰지 않는 표현' 제안 없음: {kinds}"
    s = next(s for s in suggestions if s["종류"] == "쓰지 않는 표현")
    assert "특별한" in s["문구"]
    assert s["근거_건수"] >= 2
    results.append(f"  - 몽글커피: '쓰지 않는 표현' 제안 나옴 ('{s['문구']}') ✅")
    return results, suggestions


def test_suggest_sutbul():
    results = []
    profile = T.build_profile(STORES[1])
    log = build_log(EDITS_SUTBUL)
    suggestions = TL.suggest(log, profile)
    kinds = [s["종류"] for s in suggestions]
    assert "높임 변경" in kinds, f"'높임 변경' 제안 없음: {kinds}"
    s = next(s for s in suggestions if s["종류"] == "높임 변경")
    assert "합니다체" in s["문구"] or "습니다" in s["문구"]
    results.append(f"  - 숯불집: '높임 변경' 제안 나옴 ('{s['문구']}') ✅")
    return results, suggestions


def test_suggest_tteok():
    results = []
    profile = T.build_profile(STORES[2])
    log = build_log(EDITS_TTEOK)
    suggestions = TL.suggest(log, profile)
    kinds = [s["종류"] for s in suggestions]
    assert "이모지 삭제" in kinds, f"'이모지 삭제' 제안 없음: {kinds}"
    s = next(s for s in suggestions if s["종류"] == "이모지 삭제")
    assert "이모지" in s["문구"]
    results.append(f"  - 떡볶이: '이모지 삭제' 제안 나옴 ('{s['문구']}') ✅")
    return results, suggestions


def test_no_suggest_single():
    results = []
    profile = T.build_profile(STORES[0])
    log = build_log(EDITS_SINGLE)
    suggestions = TL.suggest(log, profile)
    assert len(suggestions) == 0, f"1건인데 제안이 나옴: {suggestions}"
    results.append("  - 1건만 있을 때 제안 안 나옴 ✅")
    return results


def test_apply_and_profile_text():
    results = []

    # 몽글커피: '쓰지 않는 표현' 적용
    profile = T.build_profile(STORES[0])
    original = copy.deepcopy(profile)
    log = build_log(EDITS_MONGLE)
    suggestions = TL.suggest(log, profile)
    s_ban = next(s for s in suggestions if s["종류"] == "쓰지 않는 표현")
    new_p = TL.apply(profile, s_ban)
    assert profile == original, "원본 프로필이 변경됨"
    assert "특별한" in new_p.get("쓰지 않는 표현", [])
    pt = T.profile_text(new_p)
    assert "쓰지 않는 표현" in pt and "특별한" in pt
    results.append(f"  - 몽글커피 apply: '쓰지 않는 표현'에 '특별한' 반영, profile_text에 표시됨 ✅")

    # 숯불집: 높임 변경 적용
    profile2 = T.build_profile(STORES[1])
    original2 = copy.deepcopy(profile2)
    log2 = build_log(EDITS_SUTBUL)
    suggestions2 = TL.suggest(log2, profile2)
    s_tone = next(s for s in suggestions2 if s["종류"] == "높임 변경")
    new_p2 = TL.apply(profile2, s_tone)
    assert profile2 == original2, "원본 프로필이 변경됨"
    assert new_p2["높임"] == "합니다체"
    results.append(f"  - 숯불집 apply: 높임 '{new_p2['높임']}' 반영 ✅")

    # 떡볶이: 이모지 삭제 적용
    profile3 = T.build_profile(STORES[2])
    original3 = copy.deepcopy(profile3)
    log3 = build_log(EDITS_TTEOK)
    suggestions3 = TL.suggest(log3, profile3)
    s_emoji = next(s for s in suggestions3 if s["종류"] == "이모지 삭제")
    new_p3 = TL.apply(profile3, s_emoji)
    assert profile3 == original3, "원본 프로필이 변경됨"
    assert new_p3["이모지 사용"] is False
    results.append(f"  - 떡볶이 apply: 이모지 사용=False 반영 ✅")

    return results


def test_apply_frequent_expression():
    results = []
    profile = T.build_profile(STORES[0])
    edits = [
        ("라떼 한 잔 드셔보세요!", "따뜻하게 준비해 둘게요 라떼 한 잔 드셔보세요!", "2024-11-01"),
        ("커피 한 잔 어때요?", "따뜻하게 준비해 둘게요 커피 한 잔 어때요?", "2024-11-02"),
    ]
    log = build_log(edits)
    suggestions = TL.suggest(log, profile)
    kinds = [s["종류"] for s in suggestions]
    found = "자주 넣는 표현" in kinds
    if found:
        s = next(s for s in suggestions if s["종류"] == "자주 넣는 표현")
        new_p = TL.apply(profile, s)
        assert s["변경"]["자주 쓰는 표현 추가"] in new_p.get("자주 쓰는 표현", [])
        pt = T.profile_text(new_p)
        assert "자주 쓰는 표현" in pt
        results.append(f"  - 자주 넣는 표현 제안 + apply + profile_text 반영 ✅")
    else:
        results.append(f"  - 자주 넣는 표현 제안 안 나옴 (패턴 미감지) ⚠️")
    return results


def test_apply_shorter():
    results = []
    profile = T.build_profile(STORES[0])
    edits = [
        ("오늘은 비가 와서 그런지 따뜻한 라떼가 많이 나가네요 몽글 크림라떼 한 잔 어때요", "라떼 한 잔 어때요", "2024-11-01"),
        ("휘낭시에 새로 구웠어요 버터 향 가득이에요 금방 나가니까 서둘러 주세요", "휘낭시에 구웠어요", "2024-11-02"),
    ]
    log = build_log(edits)
    suggestions = TL.suggest(log, profile)
    kinds = [s["종류"] for s in suggestions]
    assert "길이 줄임" in kinds, f"'길이 줄임' 제안 없음: {kinds}"
    s = next(s for s in suggestions if s["종류"] == "길이 줄임")
    new_p = TL.apply(profile, s)
    assert new_p.get("선호 길이") == "짧게"
    pt = T.profile_text(new_p)
    assert "선호 길이" in pt and "짧게" in pt
    results.append(f"  - 길이 줄임 제안 + apply + profile_text '짧게' 반영 ✅")
    return results


DUMMY_EV = {"이름": "테스트 행사", "핵심어": "테스트", "장소": "테스트장소", "날짜": "11월 1일", "도보": 5,
            "종류": "마켓", "상황": "구경 가시는 길에"}


def test_check_post_banned():
    results = []
    profile = T.build_profile(STORES[0])
    log = build_log(EDITS_MONGLE)
    suggestions = TL.suggest(log, profile)
    s_ban = next(s for s in suggestions if s["종류"] == "쓰지 않는 표현")
    new_p = TL.apply(profile, s_ban)

    hook = "마켓 구경 가시기 전에 커피 한 잔 어때요?"
    promo_bad = "저희 몽글커피의 특별한 크림라떼 한 잔 드셔보세요"
    promo_good = "저희 몽글커피 크림라떼 한 잔 드셔보세요"

    ch_bad = T.check_post(hook, promo_bad, STORES[0], DUMMY_EV, profile=new_p)
    assert "사장님이 지운 표현 없음" in ch_bad
    assert ch_bad["사장님이 지운 표현 없음"] is False, f"'특별한'이 있는데 통과함: {ch_bad}"

    ch_good = T.check_post(hook, promo_good, STORES[0], DUMMY_EV, profile=new_p)
    assert "사장님이 지운 표현 없음" in ch_good
    assert ch_good["사장님이 지운 표현 없음"] is True, f"'특별한'이 없는데 실패함: {ch_good}"

    ch_no_profile = T.check_post(hook, promo_bad, STORES[0], DUMMY_EV, profile=profile)
    assert "사장님이 지운 표현 없음" not in ch_no_profile

    results.append("  - '특별한' 포함 글 → check_post 실패 ✅")
    results.append("  - '특별한' 없는 글 → check_post 통과 ✅")
    results.append("  - 금지 표현 없는 프로필 → 해당 점검 항목 자체가 없음 ✅")
    return results


def main():
    all_results = []
    all_ok = True

    tests = [
        ("record_edit 기록", test_record_edit),
        ("suggest — 몽글커피 (쓰지 않는 표현)", lambda: test_suggest_mongle()[0]),
        ("suggest — 숯불집 (높임 변경)", lambda: test_suggest_sutbul()[0]),
        ("suggest — 떡볶이 (이모지 삭제)", lambda: test_suggest_tteok()[0]),
        ("suggest — 1건만 있을 때 제안 안 나옴", test_no_suggest_single),
        ("apply + profile_text 반영", test_apply_and_profile_text),
        ("자주 넣는 표현", test_apply_frequent_expression),
        ("길이 줄임", test_apply_shorter),
        ("check_post 금지 표현 점검", test_check_post_banned),
    ]

    for name, fn in tests:
        try:
            lines = fn()
            all_results.append(f"### {name} ✅")
            all_results.extend(lines)
        except Exception as e:
            all_results.append(f"### {name} ❌ {e}")
            all_ok = False
        all_results.append("")

    md = ["# 사장님 수정 학습 테스트 결과", "",
          f"전체: {'✅ 통과' if all_ok else '❌ 실패'}",
          ""] + all_results

    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.RESULTS_DIR / "tone_learn_results.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print("\n".join(md))
    print(f"\n결과 파일: {path}")
    return all_ok


if __name__ == "__main__":
    ok = main()
    if not ok:
        sys.exit(1)
