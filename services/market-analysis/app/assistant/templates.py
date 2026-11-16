"""Fixed-form answers. Used directly while no model is connected, and as the
fallback when a model answer fails the checks in answer_check.py.

Rules kept here on purpose: every number comes from a fact card and every
sentence with a number cites that card as [F번호]. A reply has three parts:
``text`` is the conversation itself; ``notes`` are the card warnings, shown
folded under the message; ``suggestions`` are next questions shown as buttons.
Warnings are therefore never dropped, but no longer repeated inside every
message (user feedback 2026-11-08: repeated caveats read as untrustworthy).
"""
from __future__ import annotations

import re

from app.assistant.answer_check import interpretation_line, is_insight
from app.assistant.korean import josa, soften
from app.assistant.lexicon import compact, keywords

_TOPIC_QUESTION = {
    "sales_weekday": "주말 매출은?", "sales_time": "점심·저녁 중 언제 잘 팔려?", "sales_age": "어느 연령대가 많이 사?",
    "stores_count": "경쟁 가게는 몇 개야?", "stores_open_close": "요즘 개업·폐업은?", "population": "유동인구는?",
    "change_yoy": "작년이랑 비교하면?", "change_qoq": "지난 분기보다 어때?", "sales_total": "매출은 얼마야?",
}
STARTERS = ["합정역 카페 매출 어때?", "서울에서 카페 매출 높은 곳은?", "연남동에서 뭐 하면 잘 될까?"]
_RECOMMEND = re.compile(r"추천|좋|괜찮|낫|나아|창업|차리|차릴|열려|오픈")


def _reply(text, *, kind, cited=(), actions=None, notes=None, suggestions=None):
    return {"text": text, "kind": kind, "cited": list(cited), "actions": actions or [],
            "notes": list(dict.fromkeys(notes or [])), "suggestions": list(suggestions or [])}


def answer_extras(cards: list[dict], classification: dict) -> tuple[list[str], list[str], list[str]]:
    """What the server always adds itself: (lines in the answer, notes, next questions).

    Model answers get the same extras, so warnings can never be dropped or
    reworded by a model and their numbers are never checked as statistics.
    """
    lines = []
    if classification.get("needs_model") and "왜" in (classification.get("text") or ""):
        lines.append("원인은 이 자료만으로 단정할 수 없어서, 같은 기간에 함께 나타난 변화를 보여드렸어요.")
    notes = [warning for card in cards if card["topic"] != "conditions" for warning in card.get("warnings", [])]
    shown = {card["topic"] for card in cards}
    suggestions = [question for topic, question in _TOPIC_QUESTION.items() if topic not in shown][:3]
    return lines, list(dict.fromkeys(notes))[:4], suggestions


def conditions_line(card: dict, *, changed: bool = False) -> str:
    """The conditions said the way a person would: '합정역 상권의 커피-음료 업종을 2026년 2분기 자료로 볼게요.'"""
    values = {v.get("label"): v.get("value") for v in card.get("values", [])}
    area, industry, period = values.get("상권"), values.get("업종"), values.get("기간")
    if area and industry and period:
        text = f"{'이번에는 ' if changed else ''}{area} 상권의 {industry} 업종을 {period} 자료로 볼게요."
    elif area and period:
        text = f"{area} 상권의 업종들을 {period} 자료로 볼게요."
    else:
        text = soften(card["text"])
    return f"{text} [{card['id']}]"


# Words in a question -> the card labels they ask about, so the answer can name those values first.
_FOCUS = {
    "sales_time": (("새벽", ("00~06시",)), ("아침", ("06~11시",)), ("오전", ("06~11시",)), ("점심", ("11~14시",)),
                   ("오후", ("14~17시",)), ("저녁", ("17~21시",)), ("퇴근", ("17~21시",)), ("밤", ("21~24시",)),
                   ("야간", ("21~24시",))),
    "sales_weekday": (("주말", ("토", "일")), ("평일", ("월", "화", "수", "목", "금")), ("월요일", ("월",)),
                      ("화요일", ("화",)), ("수요일", ("수",)), ("목요일", ("목",)), ("금요일", ("금",)),
                      ("토요일", ("토",)), ("일요일", ("일",))),
    "sales_age": tuple((f"{n}대", (f"{n}대",)) for n in (10, 20, 30, 40, 50)) + (("60대", ("60대 이상",)),
                                                                              ("어르신", ("60대 이상",))),
}


def focus_line(card: dict, question: str) -> str | None:
    """'점심과 저녁 중 언제?' -> '점심(11~14시)은 …원(…%)이고, 저녁(17~21시)은 …원(…%)이에요. [F4]'.

    Only values already on the card are named; nothing is added up.
    """
    if card.get("topic") == "area_profile":
        # The general profile text omits school/hospital counts. A model fallback
        # must still answer the facilities the user asked about, including zero.
        requested = []
        for pattern, label in ((r"초중고|초등학교|중학교|고등학교|(?<!대)학교", "초중고 수"),
                               (r"병원", "병원 수"), (r"대학", "대학교 수"),
                               (r"버스", "버스정류장 수"), (r"지하철", "지하철역 수")):
            if re.search(pattern, question or ""):
                requested.append(label)
        if not requested:
            return None
        values = {item.get("label"): item for item in card.get("values", [])}
        parts = []
        for label in requested:
            item = values.get(label) or {}
            number = item.get("value")
            if type(number) in (int, float):
                parts.append(f"{label}는 {number:,}{item.get('unit') or ''}로 집계됐어요.")
            else:
                parts.append(f"{label}는 자료에서 확인하지 못했어요.")
        return " ".join(parts) + f" [{card['id']}]"
    pairs = _FOCUS.get(card.get("topic"))
    text = (question or "").replace(" ", "")
    if not pairs or not text:
        return None
    values = {v.get("label"): v for v in card.get("values", []) if type(v.get("value")) is int}
    segments, seen, singles, parts = [], set(), [], {}
    for word, labels in pairs:
        if word not in text or labels in seen or not all(label in values for label in labels):
            continue
        seen.add(labels)
        if f"{word} 합계" in values:
            # Quarter totals survive an unknown period; only explicitly calendar-based averages are used.
            total = values[f"{word} 합계"]["value"]
            days = "월~금" if word == "평일" else "토·일"
            segment = f"{word}({days}){josa(word, '은')[len(word):]} 합계 {total:,}원"
            average = values.get(f"{word} 하루 평균", {})
            if average.get("average_basis") == "calendar_day":
                daily = average["value"]
                segment += f", 달력일 기준 하루 평균 {daily:,}원"
                parts[word] = daily
            segments.append(segment)
            continue

        def amount(label):
            share = values[label].get("share_percent")
            return f"{values[label]['value']:,}원" + (f"({share:.2f}%)" if isinstance(share, (int, float)) else "")

        if len(labels) > 1:
            segments.append(f"{josa(word, '은')} " + ", ".join(f"{label} {amount(label)}" for label in labels))
        elif word.endswith("요일") or word == labels[0] or labels[0].startswith(word):
            name = word if word.endswith("요일") else labels[0]
            segments.append(f"{josa(name, '은')} {amount(labels[0])}")
        else:
            # The particle follows the word, not the bracket: 점심(11~14시)은.
            segments.append(f"{word}({labels[0]}){josa(word, '은')[len(word):]} {amount(labels[0])}")
            singles.append((f"{word}({labels[0]})", word, values[labels[0]]["value"]))
    if not segments:
        return None
    line = "이고, ".join(segments) + f"이에요. [{card['id']}]"
    if len(parts) == 2 and parts["주말"] != parts["평일"]:
        bigger, smaller = ("주말", "평일") if parts["주말"] > parts["평일"] else ("평일", "주말")
        line = f"달력일 기준 하루 평균으로는 {josa(bigger, '이')} {smaller}보다 매출이 커요. [{card['id']}]\n" + line
    if len(singles) == 2 and len(segments) == 2 and singles[0][2] != singles[1][2]:
        (big, big_word, _), (small, _, _) = sorted(singles, key=lambda item: -item[2])
        line = f"{big}{josa(big_word, '이')[len(big_word):]} {small}보다 매출이 커요. [{card['id']}]\n" + line
    return line


def data_answer(cards: list[dict], classification: dict, *, show_conditions: bool = True,
                changed: bool = False) -> dict:
    lines, cited = [], []
    conditions = next((card for card in cards if card["topic"] == "conditions"), None)
    if conditions and show_conditions:
        lines.append(conditions_line(conditions, changed=changed))
        cited.append(conditions["id"])
    if classification.get("topics_defaulted"):
        lines.append("먼저 전체적인 흐름부터 짚어 볼게요.")
    for card in cards:
        if card["topic"] == "conditions":
            continue
        focus = focus_line(card, classification.get("text") or "")
        if focus:
            # The values the question named come first, with the market when several are shown.
            lines.append("\n".join(f"{card['market']} 상권에서 {line}" for line in focus.split("\n"))
                         if card.get("market") else focus)
        # 'speech': a short spoken form for cards whose full text is written for the model.
        lines.append(f"{soften(card.get('speech') or card['text'])} [{card['id']}]")
        cited.append(card["id"])
    extra, notes, suggestions = answer_extras(cards, classification)
    lines.extend(extra)
    return _reply("\n".join(lines), kind="data_answer", cited=cited, notes=notes, suggestions=suggestions)


_MISSING_NOTE = re.compile(r"없습니다|없어요|없어서|알 수 없|제공되지|포함되어 있지|드릴 수 없|죄송")


INSIGHT_MARK = "해석:"
_VERDICT = re.compile(r"고르겠|고를 것|나아 보|낫다고|나을 것|유리해 보|추천|택하겠|선택하겠|해볼 만|신중")
# A verdict inside a data answer ('연남동보다 강남역이 나아요', 2026-11-08 server test) rests on no criteria.
_DATA_VERDICT = re.compile(r"나아요|나아 보|낫다|낫습|나은 편|더 나은|고르겠|유리해|유리할|장사가 ?(?:더 )?잘|추천")
MAX_INSIGHT_CHARS = 80
_ABOUT = re.compile(r"약\s*(?=[+-]?\d)")
# A closing question the model may add without a card: short, no numbers ('주말 매출도 같이 볼까요?').
_FOLLOW_UP = re.compile(r"[^\n]{4,60}[?？]")


def model_body(text: str, cards: list[dict], *, show_conditions: bool = True, drop_missing_notes: bool = False,
               changed: bool = False, opinion: bool = False) -> str:
    """A model answer without the lines the server writes, the server's conditions line first.

    Returns "" when nothing of the model's own text is left. "참고" lines are
    removed because the server adds the real warnings as notes and answer_check
    does not check numbers on such lines. Lines that cite only the conditions
    card are replaced by the server's own conditions sentence: the conditions
    card supports the analysis conditions, not claims such as '주말이 더 잘 돼요 [F1]'.
    """
    conditions = next((card for card in cards if card["topic"] == "conditions"), None)
    lines, insights, follow_up = [], 0, None
    # '[F1,F3,F4]' or '[F1, F3]' -> '[F1][F3][F4]', the one form answer_check reads as citations.
    text = re.sub(r"\[\s*(F\d+(?:\s*,\s*F\d+)+)\s*\]",
                  lambda m: "".join(f"[{part.strip()}]" for part in m.group(1).split(",")), text or "")
    text = re.sub(r"\((F\d+)\)", r"[\1]", text)  # '976,474,889원(F2)' -> '976,474,889원[F2]'
    text = re.sub(r"(?<![\[\w])(F\d+)(?![\]\w])", r"[\1]", text)  # a bare 'F2' at the end of a line
    for line in text.replace("\r", "").replace("**", "").splitlines():
        line = line.strip().lstrip("#").lstrip("-•").strip()
        if not line or line.replace(" ", "").startswith(("참고:", "다음으로")):
            continue
        cited = set(re.findall(r"\[(F\d+)\]", line))
        if conditions and cited == {conditions["id"]}:
            continue
        if drop_missing_notes and _MISSING_NOTE.search(line) and not re.search(r"\d", re.sub(r"\[F\d+\]", "", line)):
            # The server already said what the data lacks; the model repeating it adds no data.
            continue
        if not is_insight(line) and interpretation_line(line, cards):
            # '직장인이 몰리는 시간임을 시사합니다': allowed, but marked so it is not read as a fact.
            line = "해석: " + line
        if is_insight(line):
            insights += 1
            # One short interpretation; the long advice paragraphs HCX-005 wrote there said nothing from the data.
            if insights > 1 or len(line) > MAX_INSIGHT_CHARS:
                continue
        elif not opinion and _DATA_VERDICT.search(line):
            continue
        elif not cited and _FOLLOW_UP.fullmatch(line) and not re.search(r"\d", line) and not follow_up:
            follow_up = line  # '주말 매출도 같이 볼까요?': kept, and kept last
            continue
        elif not cited and not (opinion and _VERDICT.search(line)):
            # A line that cites no card rests on nothing the server gave: '개성 있는 가게들이 많아 매력적인 곳이죠'
            # (2026-11-08 server test). Only an opinion's own verdict line may stand without a citation.
            continue
        line = _ABOUT.sub("", line)  # '약 6,352,851,070원': the card number is exact, so '약' misleads
        lines.append(soften(line))  # '…원입니다.' -> '…원이에요.': the model still slips into report style
    if not lines:
        return ""
    if conditions and show_conditions:
        lines.insert(0, conditions_line(conditions, changed=changed))
    if follow_up:
        lines.append(soften(follow_up))
    return "\n".join(lines)


def industry_rank_answer(result: dict, cards: list[dict], classification: dict) -> dict:
    """Industries of one market by quarterly sales; every number cites the industry card."""
    from app.assistant.ranking import WARNING_INDUSTRY

    conditions, ranked = cards[0], cards[1]
    lines = [conditions_line(conditions)]
    if _RECOMMEND.search(classification.get("text") or ""):
        lines.append("어떤 업종이 좋을지는 매출만으로 정할 수는 없지만, 이 상권에서 매출이 큰 업종부터 보여드릴게요.")
    for item in result["items"]:
        stores = f", 점포 {item['stores']:,}개" if item.get("stores") is not None else ""
        lines.append(f"- {item['rank']}위 {item['industry_name']}: 매출 {item['value']:,}원{stores} [{ranked['id']}]")
    if result.get("excluded"):
        lines.append(f"말씀하신 대로 {josa(', '.join(result['excluded']), '은')} 뺐어요.")
    seoul = result.get("area_code") is None
    where = "서울 전체 상권에서" if seoul else "이 상권에서"
    lines.append(f"{where} 자료가 있는 {result['compared_count']:,}개 업종을 비교했어요. [{ranked['id']}]")
    if result.get("items") and not seoul:
        lines.append("궁금한 업종을 누르면 매출·점포 수·작년 대비 변화를 자세히 볼게요.")
    notes = [WARNING_INDUSTRY] + [w for w in ranked.get("warnings", []) if w != WARNING_INDUSTRY]
    top = result["items"][0]["industry_name"] if result.get("items") else None
    # Questions that follow from this list, not a fixed '카페 말고' that may already be answered.
    suggestions = [f"{top} 말고 다른 업종은?" if top else "다른 업종은?",
                   f"서울에서 {top} 매출 높은 곳은?" if top else "서울에서 매출 높은 곳은?"]
    return _reply("\n".join(lines), kind="industry_rank", cited=[conditions["id"], ranked["id"]], notes=notes,
                  suggestions=suggestions)


def seoul_compare(markets: dict, market_card: dict, industries: dict | None, industry_card: dict | None) -> dict:
    """'서울 전체 모든 상권들과 업종들로 비교해줘': the largest markets and, across industries, the largest industries."""
    from app.assistant.ranking import item_label

    what = "전체 업종을 합친" if markets.get("all_industries") else f"{markets['industry_name']} 업종의"
    lines = [f"서울 전체를 {what} {markets['period_label']} 추정매출로 나눠 보면 이렇게 돼요. [{market_card['id']}]",
             f"매출이 큰 상권 {len(markets['items'])}곳이에요. [{market_card['id']}]"]
    lines += [f"- {item_label(item)}: {item['value']:,}원 [{market_card['id']}]" for item in markets["items"]]
    cited = [market_card["id"]]
    if industries and industry_card:
        lines.append(f"업종별로는 이 순서로 매출이 커요. [{industry_card['id']}]")
        lines += [f"- {item['rank']}위 {item['industry_name']}: {item['value']:,}원 [{industry_card['id']}]"
                  for item in industries["items"]]
        cited.append(industry_card["id"])
    actions = [{"label": f"{item['rank']}위 {item['name']} 자세히",
                "payload": {"type": "location", "kind": "neighborhood", "district_code": item["district_code"],
                            "neighborhood_code": item["neighborhood_code"], "area_code": item["area_code"],
                            "period": markets["period"]}}
               for item in markets["items"] if item.get("selectable") and item.get("neighborhood_code") and item.get("district_code")]
    return _reply("\n".join(lines), kind="seoul_compare", cited=cited, actions=actions,
                  notes=list(market_card.get("warnings", [])),
                  suggestions=["서울 연령대별 매출은?", "서울 시간대별 매출은?", "서울에서 창업한다면 어느 상권이 좋아 보여?"])


def need_location() -> dict:
    return _reply("어느 곳의 상권을 볼까요? 역 이름이나 동 이름을 알려 주세요. 예: 합정역, 연남동", kind="need_location")


COMMON_INDUSTRIES = (("CS100010", "카페"), ("CS100001", "한식"), ("CS100007", "치킨"), ("CS100008", "분식"),
                     ("CS100009", "호프·술집"), ("CS300002", "편의점"), ("CS200028", "미용실"))
_FRANCHISE = re.compile(r"프랜차이즈|체인")


def need_industry(*, repeated: bool = False, said: str = "") -> dict:
    """Asked again with buttons, never the same sentence twice ('프랜차이즈' is a kind of shop, not an industry)."""
    if not repeated:
        return _reply("어떤 업종을 볼까요? 예: 카페, 한식, 미용실, 편의점", kind="need_industry")
    first = ("프랜차이즈 수는 업종마다 따로 집계돼요. 어느 업종의 프랜차이즈를 볼까요?" if _FRANCHISE.search(said or "")
             else "업종을 하나 정해야 그 업종 자료를 찾을 수 있어요. 아래에서 골라 주시거나 업종 이름을 말씀해 주세요.")
    actions = [{"label": name, "payload": {"type": "industry", "industry_code": code}} for code, name in COMMON_INDUSTRIES]
    return _reply(first, kind="need_industry", actions=actions)


def site_costs_answer(cards: list[dict], lines: list[str]) -> dict:
    """Arithmetic on what the user said: fixed wording, so no sum is ever restated differently."""
    conditions = next((card for card in cards if card["topic"] == "conditions"), None)
    head = [conditions_line(conditions)] if conditions else []
    notes = [warning for card in cards if card["topic"] != "conditions" for warning in card.get("warnings", [])]
    return _reply("\n".join([*head, *lines]), kind="site_costs", cited=[card["id"] for card in cards], notes=notes,
                  suggestions=["여기 해볼 만해?", "입지 특성은 어때?"])


def ask_site_costs() -> dict:
    return _reply("임대료·권리금 시세는 공공 자료에 없어요. 아시는 금액을 알려 주시면 이 상권 평균 매출로 부담을 계산해 드릴게요. "
                  "예: 월세 300만 원, 권리금 5천만 원이야", kind="ask_site_costs")


def seoul_not_summed(what: str) -> dict:
    return _reply(f"{what}는 상권끼리 범위가 겹치거나 기간 비교가 달라서 서울 전체로 합치지 않아요. 궁금한 상권을 말씀해 주시면 바로 볼게요.",
                  kind="seoul_not_summed")


def opinion_answer(cards: list[dict], lines: list[str], *, show_conditions: bool = True, caveat: str | None = None) -> dict:
    """The fixed-form opinion: the conditions, opinion.fixed_lines, then what the data lacks."""
    from app.assistant.opinion import CAVEAT

    conditions = next((card for card in cards if card["topic"] == "conditions"), None)
    head = [conditions_line(conditions)] if conditions and show_conditions else []
    notes = [warning for card in cards if card["topic"] != "conditions" for warning in card.get("warnings", [])]
    return _reply("\n".join([*head, *lines, caveat or CAVEAT]), kind="opinion", cited=[card["id"] for card in cards],
                  notes=notes, suggestions=["입지 특성은 어때?", "작년이랑 비교하면?", "어느 연령대가 많이 사?"])


def district_only(name: str) -> dict:
    return _reply(f"{josa(name, '은')} 범위가 넓어서 상권을 하나로 정할 수 없어요. "
                  f"{name} 안의 역이나 동 이름을 알려 주세요.", kind="district_only")


def district_markets(district: str, industry: str | None, actions: list[dict]) -> dict:
    """'강남구 연령층은?': no district total exists, so offer its markets that have data, larger ones first."""
    what = f"{industry} 매출이 큰 상권" if industry else "매출이 큰 상권"
    return _reply(f"{district} 전체를 합친 자료는 없어서, {district}에서 {what}부터 골라 볼 수 있어요. 어느 상권을 볼까요?",
                  kind="choose_area", actions=actions)


_SUBSTITUTE_LABEL = {"sales_total": "매출", "sales_weekday": "요일별 매출", "sales_time": "시간대별 매출",
                     "sales_age": "연령별 매출", "stores_count": "점포 수", "stores_open_close": "개업·폐업",
                     "population": "유동인구"}


def substitute_label(card: dict) -> str:
    """Name a substitute card by what it really holds: '유동인구(지나다니는 사람의 연령대)' only with age values."""
    label = _SUBSTITUTE_LABEL.get(card["topic"], card["topic"])
    if card["topic"] != "population":
        return label
    groups = [group for group in ("시간대", "연령대") if any(v.get("group") == group for v in card.get("values", []))]
    return f"{label}(지나다니는 사람의 {'·'.join(groups)})" if groups else label


def substitute_line(missing: list[str], shown: list[str], *, already_said: bool = False,
                    labels: dict[str, str] | None = None) -> str:
    """'이 상권은 연령별 매출 자료가 없어서, 대신 유동인구(…)를 보여 드릴게요.'

    ``already_said``: a previous line already said the sales are missing, so only the substitute is named.
    ``labels``: topic → name from :func:`substitute_label`, so the line never promises values the card lacks.
    """
    labels = labels or {}
    want = "·".join(_SUBSTITUTE_LABEL.get(topic, topic) for topic in missing)
    instead = "와 ".join(labels.get(topic) or _SUBSTITUTE_LABEL.get(topic, topic) for topic in shown)
    if already_said:
        return f"대신 이 상권의 {josa(instead, '을')} 보여 드릴게요."
    return f"이 상권은 {want} 자료가 없어서, 대신 {josa(instead, '을')} 보여 드릴게요."


NO_SALES_MARK = "어느 분기에도 없어요"
NEARBY_POINTER = "아래 근처 상권을 누르면 그 상권 자료로 볼 수 있어요."


def no_sales_anywhere_line(area: str, industry: str, periods: list[str], has_nearby: bool) -> str:
    span = f"{periods[0][:4]}년 {periods[0][4]}분기~{periods[-1][:4]}년 {periods[-1][4]}분기" if periods else "모든 분기"
    tail = " 근처에서 자료가 있는 상권을 골라 보세요." if has_nearby else ""
    return f"{area} 상권은 {industry} 매출 자료가 {span} {NO_SALES_MARK}.{tail}"


def choose_location(mention: str, candidates: list[dict]) -> dict:
    actions = []
    for place in candidates[:8]:
        payload = {"type": "location", "kind": place["kind"]}
        if place["kind"] == "station":
            payload["station_id"] = place["station_ids"][0]
        elif place["kind"] == "neighborhood":
            payload.update(district_code=place["district_code"], neighborhood_code=place["code"])
        else:
            continue  # a district alone cannot be analysed; ask for a station or 동 instead
        label = place["label"] + (f" ({place['district_name']})" if place["kind"] == "station" and place.get("district_name") else "")
        actions.append({"label": label, "payload": payload})
    if not actions:
        return district_only(candidates[0]["label"])
    if len(actions) == 1:
        # e.g. '강남' = 강남역 or 강남구, and a 구 alone cannot be analysed.
        quoted = f"'{mention}'"
        return _reply(f"{josa(quoted, '은')} {josa(actions[0]['label'], '으로')} 볼까요? "
                      "다른 곳이면 역이나 동 이름을 알려 주세요.", kind="choose_location", actions=actions)
    return _reply(f"'{mention}'에 해당하는 곳이 여러 군데예요. 어디를 볼까요?", kind="choose_location", actions=actions)


def choose_industry(candidates: list[dict]) -> dict:
    actions = [{"label": row["name"], "payload": {"type": "industry", "industry_code": row["code"]}} for row in candidates[:8]]
    return _reply("어떤 업종으로 볼까요? 하나를 골라 주세요.", kind="choose_industry", actions=actions)


def choose_area(options: dict, period: str | None, *, repeated: bool = False) -> dict:
    actions = []
    for candidate in options.get("candidates", [])[:6]:
        if candidate.get("selection_blocked_reason"):
            continue
        relation = {"inside": "위치 포함", "boundary": "경계 위", "nearby": "가까운 상권",
                    "neighborhood": "같은 동"}.get(candidate.get("relation"), "")
        distance = candidate.get("distance_m")
        detail = relation + (f", 약 {distance:,}m" if distance else "")
        actions.append({"label": f"{candidate['name']} ({detail})" if detail else candidate["name"],
                        "payload": {"type": "area", "area_code": candidate["area_code"], "period": period}})
    if not actions:
        return _reply("이 위치 주변에서 분석할 수 있는 공식 상권을 찾지 못했어요. 다른 역이나 동을 알려 주세요.",
                      kind="no_area")
    text = ("아래 상권 가운데 하나를 먼저 골라 주세요. 고르시면 바로 이어서 볼게요." if repeated
            else "공식 상권 후보가 여러 곳이에요. 어느 상권으로 볼까요?")
    return _reply(text, kind="choose_area", actions=actions)


def choose_market(actions: list[dict]) -> dict:
    return _reply("그 근처 공식 상권이 여러 곳이에요. 어느 상권의 업종을 볼까요?", kind="choose_area", actions=actions)


def no_market_for_place() -> dict:
    return _reply("그 장소에서 공식 상권을 찾지 못했어요. 가까운 역 이름이나 동 이름으로 알려 주세요.", kind="need_location")


def choose_comparison(areas: list[dict]) -> dict:
    actions = [{"label": f"{area['name']} ({area['district_name']})" if area.get("district_name") else area["name"],
                "payload": {"type": "comparison_area", "area_code": area["area_code"]}}
               for area in areas[:6] if area.get("area_code")]
    if not actions:
        return _reply("비교할 수 있는 상권을 찾지 못했어요.", kind="no_comparison")
    more = " 다른 상권은 이름으로 말씀해 주세요." if len(areas) > 6 else ""
    return _reply("어느 상권과 비교할까요?" + more, kind="choose_comparison", actions=actions)


def data_unavailable(message: str) -> dict:
    return _reply(f"{message} 자료가 준비되면 다시 알려드릴게요.", kind="data_unavailable")


def period_unavailable(period_label: str) -> dict:
    return _reply(f"{period_label} 자료는 이 상권에 없어요. 다른 분기로 대신하지 않았어요. "
                  "자료가 있는 분기를 말씀해 주세요.", kind="period_unavailable")


def smalltalk(text: str) -> dict:
    if any(word in compact(text) for word in keywords()["feedback_words"]):
        body = ("제 답이 원하신 것과 달랐나 봐요. 죄송해요. "
                "찾으시던 걸 조금만 다르게 말씀해 주시면 다시 맞춰 볼게요. 아래처럼 물어보셔도 돼요.")
        return _reply(body, kind="smalltalk", suggestions=STARTERS)
    if any(word in text for word in ("고마", "감사", "ㄱㅅ", "덕분", "도움")):
        return _reply("도움이 됐다니 다행이에요. 더 궁금한 상권이나 업종이 있으면 언제든 물어보세요.", kind="smalltalk")
    if any(word in text for word in ("안녕", "반가", "처음")):
        return _reply("안녕하세요! 서울 상권의 매출, 점포 수, 유동인구를 공공 자료로 같이 살펴봐 드려요. "
                      "궁금한 동네나 업종을 편하게 말씀해 주세요.", kind="smalltalk", suggestions=STARTERS)
    return _reply("많이 힘드셨겠어요. 같은 상권 전체가 어떤지 보면 지금 상황을 정리하는 데 도움이 될 수 있어요. "
                  "가게가 있는 역이나 동, 업종을 알려 주시면 함께 볼게요.", kind="smalltalk")


def marketing(turn_type: str) -> dict:
    if turn_type == "handoff":
        body = "홍보 글·쿠폰·공지 만들기는 마케팅 기능에서 도와드려요."
    else:
        body = ("손님을 늘리는 방법은 마케팅 기능에서 자세히 도와드려요. "
                "상권 자료로는 손님이 많은 요일·시간대와 연령대를 먼저 확인해 볼 수 있어요.")
    return _reply(body, kind="handoff_marketing", actions=[{"label": "마케팅 기능으로 가기", "payload": {"type": "handoff", "domain": "marketing"}}])


def customer() -> dict:
    return _reply("리뷰·답글 같은 손님 응대는 고객관리 기능에서 도와드려요.", kind="handoff_customer",
                  actions=[{"label": "고객관리 기능으로 가기", "payload": {"type": "handoff", "domain": "customer"}}])


def out_of_scope() -> dict:
    return _reply("그건 상권 공공 자료로는 답하기 어려워요. 대신 그 동네의 매출, 점포 수, 유동인구와 그 변화는 바로 알려드릴 수 있어요.",
                  kind="out_of_scope", suggestions=STARTERS)


def personal_metric() -> dict:
    return _reply("가게 숫자를 알려 주셔서 감사해요. 지금은 사장님 가게의 숫자를 저장하거나 계산에 쓰지 않아요. "
                  "대신 같은 상권 전체의 매출이 어떻게 변했는지 보여 드릴까요?", kind="personal_metric",
                  suggestions=["작년이랑 비교하면?"])


def unavailable_line(what: str) -> str:
    return f"말씀하신 {josa(what, '은')} 상권 공공 자료에 없어서 알려드릴 수 없어요. 대신 자료로 볼 수 있는 내용을 정리했어요."


def unknown_industry(name: str) -> dict:
    return _reply(f"'{name}'에 맞는 업종을 공식 업종 목록에서 찾지 못했어요. "
                  "한식음식점, 중식음식점, 커피-음료, 미용실처럼 업종 이름으로 다시 말씀해 주세요.", kind="need_industry")


def ai_text(text: str, turn: str) -> dict:
    return _reply(text, kind={"clarify": "clarify", "smalltalk": "smalltalk"}.get(turn, "out_of_scope"))


def unknown(repeated: bool = False) -> dict:
    first = ("아직 제가 잘 못 알아들었어요. 아래처럼 물어봐 주시면 바로 찾아볼게요." if repeated
             else "음, 어떤 걸 원하시는지 제가 정확히 못 알아들었어요. 이런 식으로 물어봐 주시겠어요?")
    return _reply(first, kind="unknown", suggestions=STARTERS)


def ranking_answer(result: dict, card: dict, classification: dict, exclusion_text: str = "") -> dict:
    """Seoul-wide sales ranking. Every number is on the ranking card and cites it."""
    from app.assistant.ranking import WARNING_TOTAL, item_label

    question = classification.get("text") or ""
    lines = []
    every = result.get("all_industries")
    if _RECOMMEND.search(question):
        lines.append("어디가 좋은지는 매출만으로 정할 수는 없지만, " + ("매출이 큰 상권부터" if every else "같은 업종 매출이 큰 상권부터")
                     + " 보여드릴게요.")
    what = "전체 업종을 합친" if every else f"{result['industry_name']} 업종의"
    lines.append(f"{result['scope_label']} 상권 가운데 {what} {result['period_label']} 추정매출이 큰 곳이에요. [{card['id']}]")
    for item in result["items"]:
        lines.append(f"- {item_label(item)}: {item['value']:,}원 [{card['id']}]")
    if re.search(r"(무슨|어느|어떤|몇) ?구|구에|구가|구는", question):
        # '무슨 구에 차릴까': name the districts of the listed markets; no district total is computed.
        districts = list(dict.fromkeys(item["district_name"] for item in result["items"] if item.get("district_name")))
        if districts:
            lines.append(f"위 상권들이 속한 구는 {'·'.join(districts)}예요. 구 전체 매출을 합친 순위는 아니에요.")
    if exclusion_text:
        lines.append(f"말씀하신 대로 {exclusion_text} 뺐어요.")
    if result.get("near"):
        lines.append(f"{josa(result['near']['label'], '은')} 빼고, 그 상권 중심에서 {result['near']['km']:g}km 안의 상권만 비교했어요.")
    lines.append(f"자료가 있는 {result['compared_count']:,}곳을 비교했어요. [{card['id']}]")
    actions = []
    for item in result["items"]:
        if not (item.get("selectable") and item.get("neighborhood_code") and item.get("district_code")):
            continue
        actions.append({"label": f"{item['rank']}위 {item['name']} 자세히",
                        "payload": {"type": "location", "kind": "neighborhood", "district_code": item["district_code"],
                                    "neighborhood_code": item["neighborhood_code"], "area_code": item["area_code"],
                                    "period": result["period"]}})
    if actions:
        lines.append("궁금한 상권을 누르면 매출·점포 수·작년 대비 변화를 자세히 볼게요.")
    notes = [WARNING_TOTAL] + [w for w in card.get("warnings", []) if w != WARNING_TOTAL]
    return _reply("\n".join(lines), kind="ranking", cited=[card["id"]], actions=actions, notes=notes)


def ranking_unavailable(result: dict, scope: str, industry: str | None) -> dict:
    if result.get("status") == "period_unavailable":
        return period_unavailable(result["period_label"])
    if result.get("status") == "not_collected":
        return data_unavailable(result.get("message") or "추정매출 원천 자료를 아직 확보하지 않았습니다.")
    what = f"{industry} 업종" if industry else "이 업종"
    return _reply(f"{scope}에서 {what}의 추정매출 자료가 있는 상권을 찾지 못했어요. 다른 업종이나 지역으로 물어봐 주세요.",
                  kind="ranking_empty")
