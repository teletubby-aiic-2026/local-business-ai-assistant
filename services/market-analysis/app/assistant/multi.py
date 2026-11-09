"""Several markets in one question: '합정역과 강남역의 주 고객 연령대를 알려줘'.

User feedback 2026-11-08: when two or more places were asked about together,
the chat asked to pick one of them and then answered for that one only. Here
each place becomes an official market, and the same PR #12 readers that B5
uses for a compared market (sales, stores, population, changes) are run for
each with the saved industry and quarter. The saved conditions are not
changed. Every card carries its market's name, so the answer can compare and
answer_check can verify '합정역은 30대, 강남역은 20대가 가장 많아요'.
"""
from __future__ import annotations

from copy import deepcopy
import logging

from app.assistant.facts import changes_card, population_cards, sales_cards, stores_cards
from app.assistant.korean import _has_final, josa
from app.assistant.ranking import areas_for_mentions, order_markets, period_label

_log = logging.getLogger("app.assistant.multi")
MAX_MARKETS = 4
_NEEDS = {"sales_total": "sales", "sales_weekday": "sales", "sales_time": "sales", "sales_age": "sales",
          "stores_count": "stores", "stores_open_close": "stores", "population": "population",
          "change_yoy": "changes_yoy", "change_qoq": "changes_qoq"}
_ORDER = ("sales_total", "sales_weekday", "sales_time", "sales_age", "stores_count", "stores_open_close", "population",
          "change_qoq", "change_yoy")
DISTRIBUTIONS = {"sales_age": "주 고객 연령대", "sales_time": "매출이 가장 큰 시간대", "sales_weekday": "매출이 가장 큰 요일"}


def resolve(source, mentions: list[dict], saved: dict | None) -> tuple[list[dict], list[str]]:
    """Official markets for the places, in the user's order; names that match none are returned apart.

    The saved market answers for a place that names it ('연남동' while 연남동(홍대) is chosen). Otherwise the
    market named exactly like the station comes first ('강남역', not 강남 마이스), then the largest by sales.
    """
    markets, missing = [], []
    for mention in mentions:
        text = mention["text"]
        if mention.get("market"):  # carried over from the previous multi-market answer
            chosen = mention["market"]
        elif saved and (saved.get("area_name") or "").startswith(text) and len(text) >= 2:
            chosen = {"area_code": saved["area_code"], "name": saved["area_name"]}
        else:
            areas = [a for a in areas_for_mentions(source, [mention]) if a.get("boundary_identity_status") == "code_name_match"]
            names = {c.get("name") for c in mention["candidates"]} | {c.get("label") for c in mention["candidates"]}
            exact = [a for a in areas if a.get("name") in names]
            ordered = exact or order_markets(source, areas)
            chosen = ordered[0] if ordered else None
        if chosen is not None and saved and chosen["area_code"] == saved.get("area_code"):
            chosen = {"area_code": saved["area_code"], "name": saved["area_name"]}  # the saved market's own name
        if chosen is None:
            missing.append(text)
        elif all(chosen["area_code"] != market["area_code"] for market in markets):
            markets.append({"area_code": chosen["area_code"], "name": chosen["name"]})
    return markets[:MAX_MARKETS], missing


def _results(selection: dict, profile: dict, needs: set) -> dict:
    """The PR #12 readers for one market, called through their modules so tests and B5 share them."""
    import app.onboarding_changes as changes
    import app.onboarding_population as population
    import app.onboarding_sales as sales
    import app.onboarding_stores as stores

    calls = {"sales": lambda: sales.build_sales_analysis(selection, profile),
             "stores": lambda: stores.build_stores_analysis(selection, profile),
             "population": lambda: population.build_population_analysis(selection, profile),
             "changes_yoy": lambda: changes.build_changes_analysis(selection, profile, "yoy"),
             "changes_qoq": lambda: changes.build_changes_analysis(selection, profile, "qoq")}
    results = {}
    for name in needs:
        try:
            results[name] = calls[name]()
        except Exception as error:  # one unreadable market or dataset never hides the others
            _log.info("multi-market %s skipped: %s", name, type(error).__name__)
            results[name] = {"status": "error", "message": "자료를 불러오지 못했습니다."}
    return results


def market_cards(markets: list[dict], selection: dict, profile: dict, topics) -> list[dict]:
    """[conditions, then per topic one card per market], numbered F1.. . Card text starts with the market."""
    wanted = [topic for topic in _ORDER if topic in set(topics)] or ["sales_total", "stores_count", "population"]
    needs = {_NEEDS[topic] for topic in wanted}
    per_market = {}
    for market in markets:
        chosen = {**deepcopy(selection), "area_code": market["area_code"], "area_name": market["name"]}
        results = _results(chosen, profile, needs)
        cards = []
        if "sales" in results:
            cards += sales_cards(results["sales"])
        if "stores" in results:
            cards += stores_cards(results["stores"])
        if "population" in results:
            cards += population_cards(results["population"])
        if "changes_yoy" in results:
            cards.append(changes_card(results["changes_yoy"], "yoy"))
        if "changes_qoq" in results:
            cards.append(changes_card(results["changes_qoq"], "qoq"))
        per_market[market["name"]] = cards
    names = "·".join(market["name"] for market in markets)
    industry = profile["industry"]["name"]
    label = selection.get("period_label") or period_label(selection["period"])
    found = [{"id": "F1", "topic": "conditions", "status": "available",
              "text": f"분석 조건은 {names} 상권, {industry} 업종, {label} 자료입니다.",
              "values": [{"label": "상권", "value": names, "unit": None},
                         {"label": "업종", "value": industry, "unit": None, "code": profile["industry"]["code"]},
                         {"label": "기간", "value": label, "unit": None, "code": selection["period"]}],
              "warnings": [], "source_ref": {"analysis": "multi_market"}}]
    for topic in wanted:
        for market in markets:
            for card in per_market[market["name"]]:
                if card["topic"] != topic:
                    continue
                tagged = {**card, "id": f"F{len(found) + 1}", "market": market["name"],
                          "text": f"{market['name']} 상권의 {card['text']}",
                          "values": [{**value, "market": market["name"]} for value in card.get("values", [])]}
                found.append(tagged)
    ratios = ratio_card(found, markets)
    if ratios:
        found.append({**ratios, "id": f"F{len(found) + 1}"})
    return found


_RATIO_LABELS = ("분기 추정매출", "전체 점포", "유동인구 원천 총지표")
_RATIO_NAMES = {"분기 추정매출": "분기 추정매출", "전체 점포": "점포 수", "유동인구 원천 총지표": "유동인구"}


def ratio_card(cards: list[dict], markets: list[dict]) -> dict | None:
    """'강남역 분기 추정매출은 합정역의 4.9배': one decimal, the larger over the smaller, computed by code."""
    if len(markets) != 2:
        return None
    values, sentences = [], []
    for label in _RATIO_LABELS:
        found = {v["market"]: v["value"] for card in cards for v in card.get("values", [])
                 if v.get("label") == label and type(v.get("value")) is int and v.get("market")}
        if len(found) != 2 or not all(found.values()):
            continue
        (big, big_value), (small, small_value) = sorted(found.items(), key=lambda item: -item[1])
        ratio = round(big_value / small_value, 1)
        values.append({"label": f"{label} 배수", "value": ratio, "unit": "배", "derived": True})
        sentences.append(f"{big} {josa(_RATIO_NAMES.get(label, label), '은')} {small}의 {ratio}배입니다.")
    if not values:
        return None
    return {"id": None, "topic": "multi_ratio", "status": "available", "text": " ".join(sentences) + " (계산값)",
            "values": values, "warnings": ["배수는 두 상권의 공공 자료 값을 서버가 나눈 계산값입니다."],
            "source_ref": {"analysis": "multi_market"}}


def lead_lines(cards: list[dict]) -> list[str]:
    """'주 고객 연령대는 합정역 30대, 강남역 20대예요.' from the cards' own values, first in the fixed answer."""
    lines = []
    for topic, title in DISTRIBUTIONS.items():
        tops, cited = [], []
        for card in cards:
            if card["topic"] != topic or card.get("status") != "available":
                continue
            amounts = [v for v in card.get("values", []) if type(v.get("value")) is int and v.get("unit") == "원"
                       and not v.get("aggregate")]
            if amounts:
                best = max(amounts, key=lambda value: value["value"])
                label = best["label"] + ("요일" if topic == "sales_weekday" else "")
                tops.append(f"{card['market']} {label}")
                cited.append(f"[{card['id']}]")
        if len(tops) >= 2:
            ending = "이에요" if _has_final(tops[-1]) else "예요"
            lines.append(f"{josa(title, '은')} {', '.join(tops)}{ending}. {''.join(cited)}")
    return lines


def without_data(cards: list[dict], markets: list[dict], topics) -> list[str]:
    """Markets with no sales figure while another has one (or, when sales were not asked, no figure at all).

    A market that only has people or store counts still cannot be set against another market's sales.
    """
    asked = [card for card in cards if card.get("market") and card["topic"] in set(topics)]
    pool = [card for card in asked if card["topic"].startswith("sales_")] or asked
    with_data = {card["market"] for card in pool if card.get("status") == "available"}
    return [market["name"] for market in markets if market["name"] not in with_data] if with_data else []


def no_data_line(names: list[str], industry: str) -> str:
    return f"{', '.join(names)}에는 {industry} 매출 자료가 없어서 매출은 함께 견줄 수 없어요. 볼 수 있는 자료만 먼저 보여 드릴게요."


def missing_line(missing: list[str]) -> str | None:
    if not missing:
        return None
    return f"{', '.join(missing)}에서는 공식 상권을 찾지 못해서 빼고 볼게요."
