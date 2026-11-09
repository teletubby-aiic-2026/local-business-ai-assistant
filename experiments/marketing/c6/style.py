"""사장님 답글 말투 분석 — tone.measure / last_sentence 재사용."""

import re

from features.tone import EMOJI, measure, last_sentence


def owner_style(owner_replies: list[str]) -> dict:
    if not owner_replies:
        return {}

    ms = [measure(r) for r in owner_replies]

    openings: list[str] = []
    for r in owner_replies:
        first = r.split(".")[0].split("!")[0].split("?")[0].strip()
        if first:
            openings.append(first)
    opening = max(set(openings), key=openings.count) if openings else ""

    closings = [last_sentence(r) for r in owner_replies]
    closing = max(set(closings), key=closings.count) if closings else ""

    honorific_counts: dict[str, int] = {}
    for m in ms:
        h = m["높임"]
        honorific_counts[h] = honorific_counts.get(h, 0) + 1
    honorific = max(honorific_counts, key=honorific_counts.get)  # type: ignore[arg-type]

    avg_len = round(sum(m["평균 문장 길이"] for m in ms) / len(ms), 1)

    bodies = " ".join(owner_replies)
    emoji_used = bool(EMOJI.search(re.sub(r":\)", "", bodies)))

    return {
        "시작 인사": opening,
        "마무리": closing,
        "높임": honorific,
        "평균 문장 길이": avg_len,
        "이모지 사용": emoji_used,
    }
