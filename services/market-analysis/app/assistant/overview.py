"""Sums over many rows of the B2 source: Seoul as a whole, or one market's every industry.

'서울시의 모든 상권을 이용하는 연령층을 알려줘' adds every official market up;
'강남역 주말 모든 상권의 매출' adds up every industry of the 강남역 market
(user feedback 2026-11-08: the saved industry 커피-음료 was used instead). The
B2 source holds each market's and industry's quarterly sales by age group,
time band and weekday; code adds them for one quarter, and the sums, shares
and daily averages are marked as computed values. The cards use the same
topics and labels as one market's cards, so the answer, its checks and the
'점심이랑 저녁 중' focus line work unchanged.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.assistant.facts import weekday_aggregates
from app.assistant.korean import josa
from app.assistant.opinion import _count, _money
from app.assistant.ranking import period_label

LABELS = {"sales_age": "연령별 매출", "sales_time": "시간대별 매출", "sales_weekday": "요일별 매출"}
WARNING = ("서울 상권분석서비스의 상권별 분기 추정매출을 서버가 모두 더한 계산값입니다. "
           "공식 상권에 속하지 않은 가게의 매출은 들어 있지 않습니다.")
STORE_TOPICS = ("stores_count", "stores_open_close")
_STORE_FIELDS = (("total", "SIMILR_INDUTY_STOR_CO"), ("general", "STOR_CO"), ("franchise", "FRC_STOR_CO"),
                 ("opened", "OPBIZ_STOR_CO"), ("closed", "CLSBIZ_STOR_CO"))
WARNING_MARKET = "이 상권의 업종별 분기 추정매출을 서버가 모두 더한 계산값입니다. 자료가 없는 업종은 들어 있지 않습니다."


def _share(part: int, whole: int) -> float:
    return float((Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def summed_cards(source, topics, *, industry_code: str | None = None, industry_name: str | None = None,
                 period: str | None = None, area_code: str | None = None, area_name: str | None = None) -> list[dict]:
    """[conditions, one card per topic], numbered F1.. . Empty when the source has no usable rows.

    Without ``area_code`` every official market of Seoul is added up (one industry or all); with it, every
    industry of that one market.
    """
    from app.data_repository import DISTRIBUTION_FIELDS
    from app.onboarding_sales import _TOTAL_FIELD

    periods = source.periods()
    if not periods:
        return []
    period = period if period in periods else periods[-1]
    rows, version = source.sales(period)
    areas = source.areas()
    wanted = [topic for topic in topics if topic in LABELS or topic in ("sales_total", *STORE_TOPICS)] or ["sales_age"]
    totals = {topic: {label: 0 for label, _field in DISTRIBUTION_FIELDS[topic]} for topic in wanted if topic in LABELS}
    counted = {topic: set() for topic in wanted}
    whole_sales = 0
    for (code, industry), row in rows.items():
        if code not in areas or (industry_code and industry != industry_code) or (area_code and code != area_code):
            continue
        industry_name = industry_name or (row.get("SVC_INDUTY_CD_NM") if industry_code else None)
        unit = industry if area_code else code  # a market's industries, or Seoul's markets
        if "sales_total" in wanted:
            amount = _money(row.get(_TOTAL_FIELD))
            if amount is not None:
                whole_sales += amount
                counted["sales_total"].add(unit)
        for topic in totals:
            amounts = [(label, _money(row.get(field))) for label, field in DISTRIBUTION_FIELDS[topic]]
            if any(amount is None for _label, amount in amounts):
                continue  # a row with a missing or unreadable value is left out whole, never counted as 0
            counted[topic].add(unit)
            for label, amount in amounts:
                totals[topic][label] += amount
    scope = industry_name or "전체"
    where = area_name or "서울 전체"
    label = period_label(period)
    cards = [{"id": "F1", "topic": "conditions", "status": "available",
              "text": f"분석 조건은 {where} 상권, {scope} 업종, {label} 자료입니다.",
              "values": [{"label": "상권", "value": where, "unit": None, "code": area_code},
                         {"label": "업종", "value": scope, "unit": None, "code": industry_code},
                         {"label": "기간", "value": label, "unit": None, "code": period}],
              "warnings": [], "source_ref": {"analysis": "seoul_overview" if area_code is None else "all_industries"}}]

    def counted_text(count: int) -> str:
        return f"{where} 상권의 {scope} 업종({count:,}개)" if area_code else f"서울 전체 상권 {count:,}곳의 {scope} 업종"

    count_value = (lambda count: {"label": "합친 업종 수", "value": count, "unit": "개"}) if area_code else \
        (lambda count: {"label": "합친 상권 수", "value": count, "unit": "곳"})
    warning = WARNING_MARKET if area_code else WARNING
    if "sales_total" in wanted and whole_sales:
        count = len(counted["sales_total"])
        cards.append({"id": f"F{len(cards) + 1}", "topic": "sales_total", "status": "available",
                      "text": f"{counted_text(count)} {label} 추정매출을 합치면 {whole_sales:,}원입니다.",
                      "values": [{"label": "분기 추정매출", "value": whole_sales, "unit": "원", "derived": True},
                                 count_value(count)],
                      "warnings": [warning], "source_ref": {"analysis": "summed", "data_version": version}})
    for topic in totals:
        whole = sum(totals[topic].values())
        if not whole:
            continue
        values = [{"label": name, "value": amount, "unit": "원", "share_percent": _share(amount, whole), "derived": True}
                  for name, amount in totals[topic].items()]
        order = sorted(values, key=lambda value: -value["value"])
        high, low = order[0], order[-1]
        count = len(counted[topic])
        # Sales, not people: the model once read this card as '상권을 찾는 사람 중 60대 이상이 가장 많다'.
        text = (f"{counted_text(count)} {label} {LABELS[topic]}을 합쳐 보면 "
                f"가장 큰 항목은 {josa(high['label'], '으로')} {high['value']:,}원(비중 {high['share_percent']:.2f}%)이고, "
                f"가장 작은 항목은 {josa(low['label'], '으로')} {low['value']:,}원입니다. "
                f"매출이 큰 순서는 {', '.join(value['label'] for value in order)}입니다. "
                "사람 수가 아니라 매출액 기준입니다.")
        name = (lambda value: value["label"] + "요일") if topic == "sales_weekday" else (lambda value: value["label"])
        speech = (f"{LABELS[topic]}은 {josa(name(high), '이')} {high['value']:,}원으로 가장 크고(비중 {high['share_percent']:.2f}%), "
                  f"{josa(name(low), '이')} 가장 작습니다.")
        if topic == "sales_weekday":
            extra, sentence = weekday_aggregates(values)
            values += extra
            text += sentence
            daily = {value["label"]: value["value"] for value in extra}
            if daily:
                speech += f" 하루 평균은 평일 {daily['평일 하루 평균']:,}원, 주말 {daily['주말 하루 평균']:,}원입니다."
        values.append(count_value(count))
        cards.append({"id": f"F{len(cards) + 1}", "topic": topic, "status": "available", "text": text, "speech": speech,
                      "values": values, "warnings": [warning],
                      "source_ref": {"analysis": "summed", "data_version": version}})
    if any(topic in wanted for topic in STORE_TOPICS) and hasattr(source, "store_table"):
        sums, units = {name: 0 for name, _field in _STORE_FIELDS}, set()
        for code, by_industry in source.store_table(period).items():
            if code not in areas or (area_code and code != area_code):
                continue
            for industry, row in by_industry.items():
                if (industry_code and industry != industry_code) or _count(row, "SIMILR_INDUTY_STOR_CO") is None:
                    continue
                units.add(industry if area_code else code)
                for name, field in _STORE_FIELDS:
                    sums[name] += _count(row, field) or 0
        if sums["total"]:
            count = len(units)
            if "stores_count" in wanted:
                share = _share(sums["franchise"], sums["total"])
                cards.append({"id": f"F{len(cards) + 1}", "topic": "stores_count", "status": "available",
                              "text": f"{counted_text(count)} 점포를 합치면 전체 {sums['total']:,}개입니다. "
                                      f"일반 {sums['general']:,}개, 프랜차이즈 {sums['franchise']:,}개(프랜차이즈 비중 {share:.2f}%)입니다.",
                              "values": [{"label": "전체 점포", "value": sums["total"], "unit": "개", "derived": True},
                                         {"label": "일반 점포", "value": sums["general"], "unit": "개", "derived": True},
                                         {"label": "프랜차이즈 점포", "value": sums["franchise"], "unit": "개", "derived": True},
                                         {"label": "프랜차이즈 비중", "value": share, "unit": "%", "derived": True}, count_value(count)],
                              "warnings": [warning], "source_ref": {"analysis": "summed"}})
            if "stores_open_close" in wanted:
                cards.append({"id": f"F{len(cards) + 1}", "topic": "stores_open_close", "status": "available",
                              "text": f"{counted_text(count)} 같은 기간 개업 점포는 {sums['opened']:,}개, 폐업 점포는 {sums['closed']:,}개입니다.",
                              "values": [{"label": "개업 점포", "value": sums["opened"], "unit": "개", "derived": True},
                                         {"label": "폐업 점포", "value": sums["closed"], "unit": "개", "derived": True}, count_value(count)],
                              "warnings": [warning], "source_ref": {"analysis": "summed"}})
    return cards if len(cards) > 1 else []


def seoul_cards(source, topics, *, industry_code: str | None = None, industry_name: str | None = None,
                period: str | None = None) -> list[dict]:
    return summed_cards(source, topics, industry_code=industry_code, industry_name=industry_name, period=period)
