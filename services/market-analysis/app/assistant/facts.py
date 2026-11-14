"""Turn B2~B6 results into short, citable fact cards.

Every number on a card is copied from a PR #12 result; nothing is recalculated
here. A card carries its own warnings so that an answer which cites it can
repeat the caveats. Card ids (F1, F2, ...) follow the team convention for
evidence ids and are stable for one snapshot.
"""
from __future__ import annotations

from app.assistant.korean import josa

TOPIC_ORDER = ("conditions", "sales_total", "sales_weekday", "sales_time", "sales_age", "stores_count",
               "stores_open_close", "population", "change_qoq", "change_yoy", "comparison", "area_profile")
_DISTRIBUTION_TOPIC = {"weekday": "sales_weekday", "time": "sales_time", "age": "sales_age"}
_UNAVAILABLE = {"no_data": "자료가 없습니다", "not_collected": "원천 자료를 아직 확보하지 않았습니다",
                "invalid": "원천 수치의 형식을 확인하지 못했습니다", "error": "자료를 불러오지 못했습니다",
                "no_observation": "해당 상권·업종의 관측 행이 없습니다"}


def _number(value, unit=""):
    if value is None:
        return "확인 불가"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.2f}{unit}"
    return f"{int(value):,}{unit}"


def _percent(value, signed=False):
    if value is None:
        return None
    return f"{value:+.2f}%" if signed else f"{value:.2f}%"


def _card(topic, text, *, values=(), warnings=(), status="available", source=None):
    return {"id": None, "topic": topic, "status": status, "text": text, "values": list(values),
            "warnings": [w for w in dict.fromkeys(warnings) if w], "source_ref": source or {}}


def _age_label(name: str) -> str:
    """PR #12 population labels such as '연령대 20' or '연령대 10 (원천 분류)' -> '20대', '10대'."""
    if not name.startswith("연령대 "):
        return name
    rest = name[len("연령대 "):].split(" (")[0]
    if rest.endswith(" 이상"):
        return rest[:-3] + "대 이상"
    return rest + "대"


def _unavailable_text(label, status, message=None):
    return f"{label}: {(message or _UNAVAILABLE.get(status, '자료를 확인하지 못했습니다')).rstrip('.')}."


def _source(name, result):
    return {"analysis": name, "data_version": result.get("data_version"),
            "source_title": (result.get("source") or {}).get("title"),
            "source_url": (result.get("source") or {}).get("url")}


def conditions_card(selection: dict, profile: dict) -> dict:
    area = selection.get("area_name") or selection.get("area_code")
    industry = (profile.get("industry") or {}).get("name") or selection.get("industry_code")
    period = selection.get("period_label") or selection.get("period")
    boundary = (selection.get("boundary") or {}).get("publication_date", "2023-10-23")
    text = f"분석 조건은 {area} 상권, {industry} 업종, {period} 자료입니다."
    return _card("conditions", text, values=[
        {"label": "상권", "value": area, "unit": None, "code": selection.get("area_code")},
        {"label": "업종", "value": industry, "unit": None, "code": selection.get("industry_code")},
        {"label": "기간", "value": period, "unit": None, "code": selection.get("period")}],
        warnings=[f"상권 지도는 {boundary} 공개 경계이며 선택 분기의 실제 경계와 같은지는 확인되지 않았습니다."],
        source={"analysis": "selection", "catalog_version": selection.get("catalog_version")})


WEEKDAYS, WEEKEND = ("월", "화", "수", "목", "금"), ("토", "일")


def weekday_aggregates(values: list[dict]) -> tuple[list[dict], str]:
    """평일(월~금)·주말(토·일) totals and per-day averages from the seven day values (computed, marked so).

    Marked ``aggregate`` so they are never compared with single days ('토요일이 가장 많아요').
    """
    days = {v["label"]: v["value"] for v in values if v.get("label") in WEEKDAYS + WEEKEND and type(v.get("value")) is int}
    if len(days) != 7:
        return [], ""
    weekday, weekend = sum(days[d] for d in WEEKDAYS), sum(days[d] for d in WEEKEND)
    extra = [{"label": label, "value": value, "unit": "원", "derived": True, "aggregate": True}
             for label, value in (("평일 합계", weekday), ("평일 하루 평균", weekday // 5),
                                  ("주말 합계", weekend), ("주말 하루 평균", weekend // 2))]
    sentence = (f" 평일(월~금)은 합계 {weekday:,}원, 하루 평균 {weekday // 5:,}원이고, "
                f"주말(토·일)은 합계 {weekend:,}원, 하루 평균 {weekend // 2:,}원입니다(계산값).")
    return extra, sentence


def sales_cards(result: dict) -> list[dict]:
    if result.get("status") == "error":
        return [_card("sales_total", _unavailable_text("추정매출", "error", result.get("message")), status="error")]
    total = result.get("total", {})
    base_warnings = result.get("warnings", [])
    source = _source("sales", result)
    cards = []
    if total.get("status") == "available":
        text = f"분기 추정매출은 {_number(total['value'], '원')}입니다."
        cards.append(_card("sales_total", text, values=[{"label": "분기 추정매출", "value": total["value"], "unit": "원"}],
                           warnings=base_warnings[:1], source=source))
    else:
        status = result.get("status") if result.get("status") in _UNAVAILABLE else total.get("status") or "no_data"
        cards.append(_card("sales_total", _unavailable_text("추정매출", status, total.get("message")),
                           status=status, warnings=base_warnings, source=source))
    for kind, topic in _DISTRIBUTION_TOPIC.items():
        dist = (result.get("distributions") or {}).get(kind)
        if not dist:
            continue
        ranking = dist.get("ranking") or {}
        values = [{"label": item["label"], "value": item.get("value"), "unit": "원",
                   "share_percent": item.get("share_percent")} for item in dist.get("items", [])]
        if dist.get("status") == "complete" and ranking.get("status") == "available":
            high = ", ".join(ranking["highest"])
            low = ", ".join(ranking["lowest"])
            high_share = next((v["share_percent"] for v in values if v["label"] in ranking["highest"]), None)
            # The amount outside brackets, so the reply can add '(약 9억 7,647만 원)' after it.
            text = (f"{dist['label']}에서 가장 높은 항목은 {josa(high, '으로')} {_number(ranking['highest_value'], '원')}"
                    + (f"(비중 {_percent(high_share)})" if high_share is not None else "")
                    + f"이고, 가장 낮은 항목은 {josa(low, '으로')} {_number(ranking['lowest_value'], '원')}입니다.")
            warnings = list(dist.get("warnings", []))
            if kind == "weekday":
                extra, sentence = weekday_aggregates(values)
                values += extra
                text += sentence
            if kind == "age" and dist.get("classified_share_of_total_percent") is not None:
                text += f" 연령이 분류된 매출은 전체의 {_percent(dist['classified_share_of_total_percent'])}입니다."
                values.append({"label": "연령 분류 매출 비율", "value": dist["classified_share_of_total_percent"], "unit": "%"})
            cards.append(_card(topic, text, values=values, warnings=warnings, source=source))
        else:
            cards.append(_card(topic, _unavailable_text(dist.get("label", topic), dist.get("status")),
                               status=dist.get("status") or "no_data", values=values,
                               warnings=dist.get("warnings", []), source=source))
    return cards


def stores_cards(result: dict) -> list[dict]:
    if result.get("status") == "error":
        message = result.get("message")
        return [_card("stores_count", _unavailable_text("점포 수", "error", message), status="error"),
                _card("stores_open_close", _unavailable_text("개업·폐업", "error", message), status="error")]
    counts = result.get("counts", {})
    source = _source("stores", result)
    warnings = result.get("warnings", [])
    total = counts.get("total", {})
    if total.get("status") == "available":
        text = f"전체 점포는 {_number(total['value'], '개')}입니다."
        composition = result.get("composition", {})
        general, franchise = counts.get("general", {}), counts.get("franchise", {})
        if composition.get("status") == "consistent":
            text += f" 일반 {_number(general.get('value'), '개')}, 프랜차이즈 {_number(franchise.get('value'), '개')}"
            share = composition.get("franchise_share_percent")
            text += f"(프랜차이즈 비중 {_percent(share)})입니다." if share is not None else "입니다."
        values = [{"label": counts[key]["label"], "value": counts[key].get("value"), "unit": "개"}
                  for key in ("total", "general", "franchise") if key in counts]
        if composition.get("franchise_share_percent") is not None:
            values.append({"label": "프랜차이즈 비중", "value": composition["franchise_share_percent"], "unit": "%"})
        cards = [_card("stores_count", text, values=values,
                       warnings=[w for w in warnings if "개별 가게" in w] + composition.get("warnings", []), source=source)]
    else:
        cards = [_card("stores_count", _unavailable_text("점포 수", total.get("status")),
                       status=total.get("status") or "no_data", warnings=warnings, source=source)]
    opened, closed = counts.get("opened", {}), counts.get("closed", {})
    if opened.get("status") == "available" or closed.get("status") == "available":
        text = (f"같은 기간 개업 점포는 {_number(opened.get('value'), '개')}, "
                f"폐업 점포는 {_number(closed.get('value'), '개')}입니다.")
        cards.append(_card("stores_open_close", text, values=[
            {"label": "개업 점포", "value": opened.get("value"), "unit": "개"},
            {"label": "폐업 점포", "value": closed.get("value"), "unit": "개"}],
            warnings=[w for w in warnings if "개업" in w or "폐업" in w], source=source))
    else:
        cards.append(_card("stores_open_close", _unavailable_text("개업·폐업", opened.get("status")),
                           status=opened.get("status") or "no_data", warnings=warnings, source=source))
    return cards


def population_cards(result: dict) -> list[dict]:
    if result.get("status") == "error":
        return [_card("population", _unavailable_text("유동인구", "error", result.get("message")), status="error")]
    total = result.get("total", {})
    source = _source("population", result)
    if total.get("status") != "available":
        return [_card("population", _unavailable_text("유동인구", total.get("status")),
                      status=total.get("status") or "no_data", warnings=result.get("warnings", []), source=source)]
    # '강남역 상권의 유동인구(…)는' reads well with a market name in front (multi.py adds it).
    text = f"유동인구(상권 전체 원천 지표)는 {_number(total['value'], '명')}입니다."
    values = [{"label": "유동인구 원천 총지표", "value": total["value"], "unit": "명"}]
    for kind, label in (("time", "시간대"), ("age", "연령대")):
        dist = (result.get("distributions") or {}).get(kind) or {}
        ranking = dist.get("ranking") or {}
        if ranking.get("status") == "available":
            highest = [_age_label(name) for name in ranking["highest"]]
            text += f" {label}별로는 {josa(', '.join(highest), '이')} {_number(ranking['highest_value'], '명')}으로 가장 많습니다."
            values.extend({"label": _age_label(item["label"]), "group": label, "value": item.get("value"), "unit": "명",
                           "share_percent": item.get("share_percent")} for item in dist.get("items", []))
    return [_card("population", text, values=values, warnings=result.get("warnings", [])[:2], source=source)]


def _metric_values(metric, left_key, right_key):
    return [{"label": metric["label"], "value": metric[left_key].get("value"), "unit": metric["unit"], "role": left_key},
            {"label": metric["label"], "value": metric[right_key].get("value"), "unit": metric["unit"], "role": right_key},
            {"label": f"{metric['label']} 차이", "value": metric.get("delta"), "unit": metric["unit"], "role": "delta"},
            {"label": f"{metric['label']} 변화율", "value": metric.get("percent"), "unit": "%", "role": "percent"}]


_HEADLINE_METRICS = ("sales", "stores_total", "floating_population", "stores_opened", "stores_closed")
_COMPARISON_NAMES = {"추정매출": "분기 추정매출", "전체 점포": "점포 수", "지역 유동인구 원천 총지표": "유동인구"}


_CHANGE_NAMES = {"추정매출": "매출", "전체 점포": "점포 수", "개업 점포": "개업 점포", "폐업 점포": "폐업 점포",
                 "지역 유동인구 원천 총지표": "유동인구"}


def changes_card(result: dict, comparison: str) -> dict:
    topic = "change_qoq" if comparison == "qoq" else "change_yoy"
    label = "지난 분기" if comparison == "qoq" else "작년 같은 분기"
    if result.get("status") == "error":
        return _card(topic, _unavailable_text(f"{label} 비교", "error", result.get("message")), status="error")
    previous = (result.get("previous_period") or {}).get("label", label)
    parts, values = [], []
    for metric in result.get("metrics", []):
        if metric.get("status") != "available":
            continue
        values.extend(_metric_values(metric, "current", "previous"))
        if metric["key"] in _HEADLINE_METRICS:
            delta = metric.get("delta")
            direction = "증가" if delta and delta > 0 else "감소" if delta and delta < 0 else "변화 없음"
            change = f"{_number(abs(delta), metric['unit'])} {direction}" if delta else "변화 없음"
            percent = _percent(metric.get("percent"), signed=True)
            name = _CHANGE_NAMES.get(metric["label"], metric["label"])
            parts.append(f"{josa(name, '은')} {change}" + (f"({percent})" if percent else ""))
    if not parts:
        return _card(topic, f"{josa(label + '(' + previous + ')', '과')} 비교할 수 있는 지표가 없습니다.", status="no_data",
                     warnings=result.get("warnings", [])[:2], source=_source("changes", result))
    # One sentence a person would say (2026-11-08 export: the report-style line was hard to read).
    text = f"{josa(label + '(' + previous + ')', '과')} 비교하면 " + ", ".join(parts) + "입니다."
    return _card(topic, text, values=values, warnings=result.get("warnings", [])[:2], source=_source("changes", result))


def comparison_card(result: dict) -> dict:
    if result.get("status") == "error":
        return _card("comparison", _unavailable_text("상권 비교", "error", result.get("message")), status="error")
    base = (result.get("base_area") or {}).get("name")
    other = (result.get("comparison_area") or {}).get("name")
    parts, values = [], []
    for metric in result.get("metrics", []):
        if metric.get("status") != "available":
            continue
        # The market names let answer_check settle '강남역이 연남동보다 매출이 커요'.
        values.extend({**value, "market": {"base": base, "comparison": other}.get(value["role"])}
                      if value["role"] in ("base", "comparison") else value
                      for value in _metric_values(metric, "base", "comparison"))
        if metric["key"] in _HEADLINE_METRICS[:3]:
            name = _COMPARISON_NAMES.get(metric["label"], metric["label"])
            parts.append(f"{josa(name, '은')} {base} {_number(metric['base'].get('value'), metric['unit'])}, "
                         f"{other} {_number(metric['comparison'].get('value'), metric['unit'])}입니다.")
    if not parts:
        return _card("comparison", f"{josa(base, '과')} {josa(other, '을')} 비교할 수 있는 지표가 없습니다.", status="no_data",
                     warnings=result.get("warnings", [])[:2], source=_source("comparison", result))
    # One sentence per metric: the fixed-form answer reads as talk, not a table row (user feedback 2026-11-08).
    text = f"{josa(base, '과')} {josa(other, '을')} 견줘 보면 " + " ".join(parts)
    return _card("comparison", text, values=values, warnings=result.get("warnings", [])[:2],
                 source=_source("comparison", result))


def cards_from_snapshot(snapshot: dict) -> list[dict]:
    """All cards for one snapshot, numbered F1.. in topic order."""
    results = snapshot["results"]
    cards = [conditions_card(snapshot["selection"], snapshot["profile"])]
    if "sales" in results:
        cards += sales_cards(results["sales"])
    if "stores" in results:
        cards += stores_cards(results["stores"])
    if "population" in results:
        cards += population_cards(results["population"])
    if "changes_qoq" in results:
        cards.append(changes_card(results["changes_qoq"], "qoq"))
    if "changes_yoy" in results:
        cards.append(changes_card(results["changes_yoy"], "yoy"))
    if "comparison" in results:
        cards.append(comparison_card(results["comparison"]))
    cards.sort(key=lambda card: TOPIC_ORDER.index(card["topic"]))
    for number, card in enumerate(cards, start=1):
        card["id"] = f"F{number}"
    return cards


def select_cards(cards: list[dict], topics, *, max_cards: int = 6) -> list[dict]:
    """The conditions card first, then the requested topics, at most max_cards."""
    wanted = ["conditions", *[topic for topic in TOPIC_ORDER if topic in set(topics)]]
    present = {card["topic"] for card in cards}
    if any(topic.startswith("sales_") and topic not in present for topic in wanted) and "sales_total" in present:
        # The sales file failed as a whole: only its sales_total error card exists, and it says why.
        wanted = list(dict.fromkeys("sales_total" if topic.startswith("sales_") and topic not in present else topic
                                    for topic in wanted))
    chosen = [card for topic in wanted for card in cards if card["topic"] == topic]
    return chosen[:max_cards]
