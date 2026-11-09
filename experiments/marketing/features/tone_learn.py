"""
사장님 수정 학습 — AI 홍보글을 사장님이 고친 패턴을 기록하고, 반복되면 제안한다.

- record_edit: 수정 기록 1건 추가
- suggest: 최근 5건 중 같은 종류 수정 2건 이상이면 제안
- apply: 제안을 프로필에 반영 (원본 수정 금지)
"""

import difflib
import re
from collections import Counter

from features.tone import measure, EMOJI

_WORD = re.compile(r"[가-힣a-zA-Z0-9]{2,}")


def _words(text):
    return _WORD.findall(text)


def _removed_added(ai_text, owner_text):
    ai_w = _words(ai_text)
    own_w = _words(owner_text)
    sm = difflib.SequenceMatcher(None, ai_w, own_w)
    removed, added = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "delete":
            removed.extend(ai_w[i1:i2])
        elif tag == "insert":
            added.extend(own_w[j1:j2])
        elif tag == "replace":
            removed.extend(ai_w[i1:i2])
            added.extend(own_w[j1:j2])
    return removed, added


def record_edit(log, ai_text, owner_text, today):
    ai_m = measure(ai_text)
    own_m = measure(owner_text)

    removed, added = _removed_added(ai_text, owner_text)

    ai_emoji = set(EMOJI.findall(ai_text))
    own_emoji = set(EMOJI.findall(owner_text))

    entry = {
        "날짜": today,
        "높임_전": ai_m["높임"],
        "높임_후": own_m["높임"],
        "이모지_삭제": bool(ai_emoji - own_emoji),
        "이모지_추가": bool(own_emoji - ai_emoji),
        "지운_표현": [w for w in removed if len(w) >= 2],
        "넣은_표현": [w for w in added if len(w) >= 2],
        "문장수_전": ai_m["문장 수"],
        "문장수_후": own_m["문장 수"],
        "글길이_전": len(ai_text),
        "글길이_후": len(owner_text),
    }
    log.append(entry)
    return log


def suggest(log, profile):
    recent = log[-5:]
    suggestions = []

    # 높임 변경
    tone_changes = [e for e in recent if e["높임_전"] != e["높임_후"]]
    if len(tone_changes) >= 2:
        target = Counter(e["높임_후"] for e in tone_changes).most_common(1)[0][0]
        from_tone = tone_changes[-1]["높임_전"]
        style_map = {"합니다체": "~습니다", "해요체": "~해요", "반말체": "~임/~음"}
        suggestions.append({
            "종류": "높임 변경",
            "문구": f"최근 고친 글에서 '{style_map.get(from_tone, from_tone)}'를 "
                    f"'{style_map.get(target, target)}'로 바꾸셨어요. "
                    f"앞으로 {target}로 쓸까요?",
            "변경": {"높임": target},
            "근거_건수": len(tone_changes),
        })

    # 이모지 삭제
    emoji_del = [e for e in recent if e["이모지_삭제"]]
    if len(emoji_del) >= 2:
        suggestions.append({
            "종류": "이모지 삭제",
            "문구": "이모지를 계속 지우셨어요. 앞으로 빼고 쓸까요?",
            "변경": {"이모지 사용": False, "자주 쓰는 이모지": []},
            "근거_건수": len(emoji_del),
        })

    # 이모지 추가
    emoji_add = [e for e in recent if e["이모지_추가"] and not e["이모지_삭제"]]
    if len(emoji_add) >= 2:
        suggestions.append({
            "종류": "이모지 추가",
            "문구": "이모지를 계속 넣으셨어요. 앞으로 이모지를 넣어서 쓸까요?",
            "변경": {"이모지 사용": True},
            "근거_건수": len(emoji_add),
        })

    # 쓰지 않는 표현
    removed_all = Counter()
    for e in recent:
        removed_all.update(e["지운_표현"])
    for word, cnt in removed_all.most_common():
        if cnt >= 2:
            suggestions.append({
                "종류": "쓰지 않는 표현",
                "문구": f"'{word}'을 {cnt}번 지우셨어요. 앞으로 쓰지 않을까요?",
                "변경": {"쓰지 않는 표현 추가": word},
                "근거_건수": cnt,
            })
            break

    # 자주 넣는 표현
    added_all = Counter()
    for e in recent:
        added_all.update(e["넣은_표현"])
    for phrase, cnt in added_all.most_common():
        if cnt >= 2:
            suggestions.append({
                "종류": "자주 넣는 표현",
                "문구": f"'{phrase}'를 {cnt}번 넣으셨어요. 자주 쓰는 표현으로 기억할까요?",
                "변경": {"자주 쓰는 표현 추가": phrase},
                "근거_건수": cnt,
            })
            break

    # 길이 줄임
    shorter = [e for e in recent if e["글길이_후"] < e["글길이_전"] * 0.85]
    if len(shorter) >= 2:
        suggestions.append({
            "종류": "길이 줄임",
            "문구": "글을 계속 줄이셨어요. 앞으로 더 짧게 쓸까요?",
            "변경": {"선호 길이": "짧게"},
            "근거_건수": len(shorter),
        })

    return suggestions


def apply(profile, suggestion):
    p = {k: (list(v) if isinstance(v, list) else v) for k, v in profile.items()}
    change = suggestion["변경"]

    if "높임" in change:
        p["높임"] = change["높임"]
    if "이모지 사용" in change:
        p["이모지 사용"] = change["이모지 사용"]
    if "자주 쓰는 이모지" in change:
        p["자주 쓰는 이모지"] = change["자주 쓰는 이모지"]
    if "쓰지 않는 표현 추가" in change:
        lst = p.get("쓰지 않는 표현", [])
        if change["쓰지 않는 표현 추가"] not in lst:
            lst = lst + [change["쓰지 않는 표현 추가"]]
        p["쓰지 않는 표현"] = lst
    if "자주 쓰는 표현 추가" in change:
        lst = p.get("자주 쓰는 표현", [])
        if change["자주 쓰는 표현 추가"] not in lst:
            lst = lst + [change["자주 쓰는 표현 추가"]]
        p["자주 쓰는 표현"] = lst
    if "선호 길이" in change:
        p["선호 길이"] = change["선호 길이"]

    return p
