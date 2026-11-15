"""사장님 말투 — ToneProfile 우선, 없으면 예전 답글 분석."""

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
    # 짧은 인사말만 남긴다 (첫 절 전체가 아니라 "안녕하세요 고객님 :)" 같은 인사 토막).
    # 코드가 조립할 때 쓰는 고정 문구라 정확히 짧아야 한다.
    opening_tokens = opening.split()
    opening = " ".join(opening_tokens[:3]) if len(opening_tokens) >= 3 else opening

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


def assemble(opening: str, body: str, closing: str) -> str:
    """시작 인사 + 본문 + 마무리를 정확히 조립한다. 고정 문구는 코드가 붙이는 지점."""
    parts = [p.strip() for p in (opening, body, closing) if p and p.strip()]
    return " ".join(parts)


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def insert_before_last_sentence(body: str, sentence: str) -> str:
    """body 맨 끝이 아니라, 마지막 문장(보통 감사·사과) 바로 앞에 sentence 를 끼워 넣는다."""
    body = body.strip()
    if not body:
        return sentence
    sentences = _SENT_SPLIT.split(body)
    if len(sentences) <= 1:
        return f"{body} {sentence}".strip()
    rest, last = " ".join(sentences[:-1]), sentences[-1]
    return f"{rest} {sentence} {last}".strip()


def few_shot_examples(ctx, n: int = 3) -> list[str]:
    """프롬프트에 넣을 좋은 예시. ToneProfile.example_sentences 우선, 없으면 예전 답글."""
    if ctx.tone and ctx.tone.example_sentences:
        return list(ctx.tone.example_sentences)[:n]
    return list(ctx.owner_replies)[:n]


_SENT_SPLIT_LOOSE = re.compile(r"[.!?\n]+")
_HAMNIDA_END = re.compile(r"(니다|ㅂ니다)\s*$")
_HAEYO_END = re.compile(r"(요|죠|용)\s*$")


def detect_register(tone) -> str:
    """ToneProfile.example_sentences·style_description 의 문장 끝(요/니다) 비율로
    haeyo 또는 hamnida 를 고른다. 판단 불가(둘 다 0이거나 동률)면 haeyo."""
    if not tone:
        return "haeyo"

    texts = list(tone.example_sentences or [])
    if tone.style_description:
        texts.append(tone.style_description)

    haeyo_n = 0
    hamnida_n = 0
    for text in texts:
        for piece in _SENT_SPLIT_LOOSE.split(text):
            piece = piece.strip()
            if not piece:
                continue
            if _HAMNIDA_END.search(piece):
                hamnida_n += 1
            elif _HAEYO_END.search(piece):
                haeyo_n += 1

    return "hamnida" if hamnida_n > haeyo_n else "haeyo"


def tone_style_section(tone, owner_replies: list[str]) -> str:
    """프롬프트의 말투 섹션을 만든다. ToneProfile 우선."""
    if tone and tone.style_description:
        parts = [tone.style_description]
        if tone.example_sentences:
            parts.append("\n예시 문장:")
            for s in tone.example_sentences:
                parts.append(f"- {s}")
        return "\n".join(parts)
    info = owner_style(owner_replies)
    return (
        f"- 시작 인사: {info.get('시작 인사', '안녕하세요 고객님')}\n"
        f"- 마무리: {info.get('마무리', '감사합니다')}\n"
        f"- 높임: {info.get('높임', '해요체')}"
    )
