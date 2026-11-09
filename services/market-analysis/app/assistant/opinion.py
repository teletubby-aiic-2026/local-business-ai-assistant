"""Opinion answers: '두 곳 중 어디가 나아?', '너라면 여기서 차릴 거야?'.

User decision 2026-11-08: listing statistics is something any chatbot can do,
so the assistant should also give its own view, grounded in the data. Code
gathers each market's figures from the PR #12 results already loaded for the
chat (B2 sales, B3 stores, B4 population, B5 comparison) and from the B2
source (Seoul rank, the same quarter a year earlier, the largest age group
and time band), then computes four criteria:

    점포당 분기 추정매출      sales / stores               higher is better
    작년 같은 분기 대비 변화율  (sales - last year) / last year  higher is better
    점포 1곳당 유동인구        people / stores              higher is better
    폐업 비율                closed / stores              lower is better

With four quarters of data the closure rate is a year's closures against the
year's average stores: in one quarter a market of ten shops is often at 0.00%
(2026-11-08 replay: all three Seoul candidates).

Computed numbers are marked 계산값 on the card. The model states a view and
its reasons from this card, and answer_check checks every number, citation
and comparison as for any answer. Without a model, the fixed answer leans to
the market that leads on more criteria and also says where the other leads.
What the data lacks (rent, key money, the shop itself) is said every time.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
import logging
import re

from app.assistant import context
from app.assistant.korean import josa

_log = logging.getLogger("app.assistant.opinion")

CAVEAT = "임대료·권리금은 이 자료에 없어요. 월세와 권리금을 알려 주시면 이 상권 평균 매출로 부담을 계산해 드릴게요."
CAVEAT_KNOWN = "실제 가게 자리와 계약 조건은 정하기 전에 꼭 직접 확인해 보세요."
DERIVED_NOTE = ("점포당 매출·점포 1곳당 유동인구·폐업 비율·작년 대비 변화율은 공공 자료 값으로 서버가 계산한 값입니다. "
                "최근 1년 폐업 비율은 4개 분기 폐업 점포 합을 그 기간 평균 점포 수로 나눈 값입니다.")
# (key, card label, unit, higher is better)
CRITERIA = (("per_store_sales", "점포당 분기 추정매출", "원", True),
            ("yoy", "작년 같은 분기 대비 매출 변화율", "%", True),
            ("per_store_people", "점포 1곳당 유동인구", "명", True),
            ("closure_rate", "폐업 비율", "%", False))
# Used instead when the data allows: four quarters against the four before, and demand beside the street count.
_EXTRA = (("trend", "최근 1년 매출 변화율", "%", True),
          ("closure_year", "최근 1년 폐업 비율", "%", False),
          ("per_store_workers", "점포 1곳당 직장인구", "명", True),
          ("per_store_residents", "점포 1곳당 상주인구", "명", True),
          ("per_store_households", "점포 1곳당 세대 수", "세대", True))
_ALL_CRITERIA = {item[0]: item for item in (*CRITERIA, *_EXTRA)}
_SHORT = {"per_store_sales": "점포 매출", "yoy": "매출 추세", "trend": "매출 추세", "per_store_people": "유동인구",
          "per_store_workers": "직장인구", "per_store_residents": "상주인구", "per_store_households": "세대 수",
          "closure_rate": "폐업 비율", "closure_year": "폐업 비율"}
# Starting weights per industry group (draft agreed with the user 2026-11-08). Demand differs: a cafe lives on who
# walks by and who works nearby, a hair salon on who lives there.
_GROUPS = {"1": ("food", "음식·카페"), "2": ("service", "생활 서비스"), "3": ("retail", "소매")}
_WEIGHTS = {"food": {"per_store_sales": 35, "trend": 20, "per_store_people": 15, "per_store_workers": 10, "closure_rate": 20},
            "retail": {"per_store_sales": 40, "trend": 20, "per_store_people": 20, "closure_rate": 20},
            "service": {"per_store_sales": 30, "trend": 10, "per_store_residents": 20, "per_store_households": 10,
                        "closure_rate": 30}}
_PREFERENCES = ((re.compile(r"안정|오래|망하지|리스크|위험"), "closure_rate", "안정 우선"),
                (re.compile(r"매출\s*(?:위주|우선|중심)|돈\s*(?:많이|잘)|수익\s*(?:위주|우선)"), "per_store_sales", "매출 우선"),
                (re.compile(r"성장|뜨는|오르는"), "trend", "성장 우선"))
_RAW = (("sales", "추정매출", "원"), ("stores", "전체 점포", "개"), ("franchise", "프랜차이즈 점포", "개"),
        ("opened", "개업 점포", "개"), ("closed", "폐업 점포", "개"), ("closed_year", "최근 1년 폐업 점포", "개"),
        ("population", "유동인구", "명"))
_COMPARISON_KEYS = {"sales": "sales", "stores_total": "stores", "stores_franchise": "franchise",
                    "stores_opened": "opened", "stores_closed": "closed", "floating_population": "population"}


def weights_for(industry_code: str | None, said: str, rows: list[dict]) -> dict | None:
    """The criteria for this industry group, with what the data has and what the user cares about.

    A criterion with no data hands its weight on: a missing 4-quarter trend to the one-quarter change, missing
    workers or residents to the street count. The closure rate is the year's when four quarters exist. None for an
    industry outside the three groups (equal weights).
    """
    group = _GROUPS.get((industry_code or "  ")[2:3])
    if group is None:
        return None
    has = {key for key in _ALL_CRITERIA if any(row.get(key) is not None for row in rows)}
    weights: dict[str, float] = {}
    for key, weight in _WEIGHTS[group[0]].items():
        target = "closure_year" if key == "closure_rate" and "closure_year" in has else key
        if target not in has:
            target = "yoy" if key == "trend" else "per_store_people" if key.startswith("per_store_") else key
        if target in has:
            weights[target] = weights.get(target, 0) + weight
    if not weights:
        return None
    preference = None
    for pattern, key, name in _PREFERENCES:
        wanted = "yoy" if key == "trend" and "trend" not in weights else \
            "closure_year" if key == "closure_rate" and "closure_year" in weights else key
        if pattern.search(said or "") and wanted in weights:
            preference = name
            rest = sum(value for other, value in weights.items() if other != wanted)
            new = min(weights[wanted] + 15, 70)
            scale = (sum(weights.values()) - new) / rest if rest else 0
            weights = {other: (new if other == wanted else value * scale) for other, value in weights.items()}
            break
    total = sum(weights.values())
    return {"group": group[0], "name": group[1], "preference": preference,
            "weights": {key: value * 100 / total for key, value in weights.items()}}


def prefers(said: str | None) -> bool:
    return any(pattern.search(said or "") for pattern, _key, _name in _PREFERENCES)


def criteria_of(plan: dict | None) -> list[tuple]:
    if plan is None:
        return list(CRITERIA)
    return [_ALL_CRITERIA[key] for key in _ALL_CRITERIA if key in plan["weights"]]


def weight_values(plan: dict | None) -> list[dict]:
    if plan is None:
        return []
    return [{"label": f"{_SHORT[key]} 비중", "value": round(plan["weights"][key]), "unit": "%"}
            for key, *_rest in criteria_of(plan)]


def weight_sentence(plan: dict | None) -> str:
    if plan is None:
        return ""
    listed = ", ".join(f"{_SHORT[key]} {round(plan['weights'][key])}%" for key, *_rest in criteria_of(plan))
    extra = f" 사용자가 말한 대로 {plan['preference']}으로 조정했습니다." if plan.get("preference") else ""
    return f"{plan['name']} 업종이라 기준 비중을 {listed}로 봅니다.{extra}"


def weight_line(plan: dict | None) -> str:
    """The weights in speech: the server adds this, because the model usually leaves them out."""
    if plan is None:
        return ""
    listed = ", ".join(f"{_SHORT[key]} {round(plan['weights'][key])}%" for key, *_rest in criteria_of(plan))
    said = f" 말씀하신 대로 {plan['preference']}으로 조정했어요." if plan.get("preference") else ""
    return f"{plan['name']} 업종이라 기준 비중은 {listed}로 봤어요.{said}"


def tail(plan: dict | None, *, shown_before: bool, caveat: str | None = None, places: list[dict] | None = None) -> str:
    """What the server says after an opinion. The weights are not repeated while they stay the same."""
    lines = []
    if places:
        lines.append("후보의 위치와 입지 유형은 이렇게 돼요: " + ", ".join(place_words(market) for market in places) + ".")
    if plan is not None and not shown_before:
        lines.append(weight_line(plan))
    lines.append(caveat or CAVEAT)
    return "\n".join(lines)


def weights_key(plan: dict | None) -> list | None:
    """Which weights an answer stated, to compare with the next opinion."""
    return [plan["group"], plan.get("preference")] if plan else None


def place_words(market: dict) -> str:
    """'개나리아파트(강남구 역삼2동, 발달상권, 직장 수요형)': a name alone says too little or misleads."""
    where = " ".join(part for part in (market.get("district_name"), market.get("neighborhood_name")) if part)
    parts = [part for part in (where, market.get("area_type"), market.get("kind")) if part]
    return f"{market['name']}({', '.join(parts)})" if parts else market["name"]


def _value(entry) -> int | None:
    if isinstance(entry, dict) and entry.get("status", "available") == "available":
        value = entry.get("value")
        if type(value) is int and value >= 0:
            return value
    return None


def figures_from_snapshot(snapshot: dict) -> dict:
    """The chosen market's own figures from the B2~B4 results of the chat snapshot."""
    results = snapshot.get("results") or {}
    sales, stores, population = results.get("sales") or {}, results.get("stores") or {}, results.get("population") or {}
    counts = stores.get("counts") or {}
    selection = snapshot.get("selection") or {}
    return {"name": selection.get("area_name") or selection.get("area_code"), "area_code": selection.get("area_code"),
            "sales": _value(sales.get("total")), "stores": _value(counts.get("total")),
            "franchise": _value(counts.get("franchise")), "opened": _value(counts.get("opened")),
            "closed": _value(counts.get("closed")), "population": _value(population.get("total"))}


def figures_from_comparison(result: dict, base: dict, other_code: str) -> dict:
    """The compared market's figures from B5; the base keeps its own and gains any it lacked."""
    other = {"name": (result.get("comparison_area") or {}).get("name") or other_code, "area_code": other_code}
    for metric in result.get("metrics") or []:
        key = _COMPARISON_KEYS.get(metric.get("key"))
        if key is None:
            continue
        other[key] = _value(metric.get("comparison"))
        if base.get(key) is None:
            base[key] = _value(metric.get("base"))
    return other


def _amount(row):
    from app.assistant.ranking import _amount as amount

    return amount(row) if row else None


def _money(value):
    """One source amount as an int, or None when missing or not an exact amount."""
    if value is None:
        return None
    from app.onboarding_sales import SalesDataError, _money as money

    try:
        return money(value)
    except SalesDataError:
        return None


def add_source_figures(source, figures: list[dict], industry_code: str, period: str) -> None:
    """Seoul rank, last year's same quarter and the largest age group and time band, from the B2 source."""
    try:
        rows, _version = source.sales(period)
        areas = source.areas()
        # Ranked like rank_sales: official markets in the catalogue only.
        values = [value for (area, industry), row in rows.items() if industry == industry_code and area in areas
                  for value in [_amount(row)] if value]
        previous = f"{int(period[:4]) - 1}{period[4:]}"
        previous_rows = source.sales(previous)[0] if previous in source.periods() else {}
    except Exception as error:  # the source is optional here: the snapshot figures still give an opinion
        _log.info("opinion source figures skipped: %s", type(error).__name__)
        return
    try:
        from app.data_repository import DISTRIBUTION_FIELDS
    except Exception:  # pragma: no cover
        DISTRIBUTION_FIELDS = {}
    trends, closures = _trend_sums(source, industry_code, period), _closure_sums(source, industry_code, period)
    contexts = _context(source, period)
    for figure in figures:
        row = rows.get((figure.get("area_code"), industry_code))
        sales = _amount(row)
        if figure.get("area_code") in trends:
            figure["sales_recent"], figure["sales_before"] = trends[figure["area_code"]]
        if figure.get("area_code") in closures:
            figure["closed_year"], figure["stores_year"] = closures[figure["area_code"]]
        figure.update(_place_fields(areas.get(figure.get("area_code")) or {}, contexts.get(figure.get("area_code")) or {}))
        if figure.get("sales") is None:
            figure["sales"] = sales
        if sales:
            figure["rank"] = 1 + sum(value > sales for value in values)
            figure["ranked"] = len(values)
            last = _amount(previous_rows.get((figure.get("area_code"), industry_code)))
            if last:
                figure["sales_last_year"] = last
        for kind, key in (("sales_age", "top_age"), ("sales_time", "top_time")):
            amounts = [(label, _money((row or {}).get(field))) for label, field in DISTRIBUTION_FIELDS.get(kind, [])]
            amounts = [(label, amount) for label, amount in amounts if amount]
            if amounts:
                figure[key] = max(amounts, key=lambda item: item[1])[0]


def _context(source, period: str) -> dict:
    reader = getattr(source, "context_table", None)
    if reader is None:
        return {}
    try:
        return reader(period)
    except Exception as error:  # location figures are optional
        _log.info("location context skipped: %s", type(error).__name__)
        return {}


def _place_fields(area: dict, spot: dict) -> dict:
    return {**spot, "district_name": area.get("district_name"), "neighborhood_name": area.get("neighborhood_name"),
            "area_type": area.get("type")}


def _quarters_back(period: str, count: int) -> list[str]:
    """The quarter given and the ones before it, newest first."""
    year, quarter = int(period[:4]), int(period[4:])
    found = []
    for _ in range(count):
        found.append(f"{year}{quarter}")
        year, quarter = (year - 1, 4) if quarter == 1 else (year, quarter - 1)
    return found


def _trend_sums(source, industry_code: str, period: str) -> dict:
    """{area: (sales of the last 4 quarters, of the 4 before)} for markets with all eight quarters.

    One quarter against the same quarter a year earlier let a single jump decide the ranking: the top three all
    showed +60~73% (2026-11-08 server check).
    """
    quarters = _quarters_back(period, 8)
    try:
        if any(quarter not in source.periods() for quarter in quarters):
            return {}
        reader = getattr(source, "sales_amounts", None)
        tables = [reader(quarter) if reader else {key: _amount(row) for key, row in source.sales(quarter)[0].items()}
                  for quarter in quarters]
    except Exception as error:
        _log.info("four-quarter trend skipped: %s", type(error).__name__)
        return {}
    found = {}
    for (code, industry) in tables[0]:
        if industry != industry_code:
            continue
        amounts = [table.get((code, industry)) for table in tables]
        if all(amounts):
            found[code] = (sum(amounts[:4]), sum(amounts[4:]))
    return found


def _closure_sums(source, industry_code: str, period: str) -> dict:
    """{area: (stores closed in the last 4 quarters, the 4 quarters' store counts added up)}, all four quarters only."""
    quarters = _quarters_back(period, 4)
    try:
        if any(quarter not in source.periods() for quarter in quarters):
            return {}
        reader = getattr(source, "store_counts", None)
        if reader is None and not hasattr(source, "store_table"):
            return {}
        tables = [reader(quarter) if reader else
                  {(code, industry): (_count(row, "SIMILR_INDUTY_STOR_CO"), _count(row, "CLSBIZ_STOR_CO"))
                   for code, by_industry in source.store_table(quarter).items() for industry, row in by_industry.items()}
                  for quarter in quarters]
    except Exception as error:
        _log.info("four-quarter closures skipped: %s", type(error).__name__)
        return {}
    found = {}
    for (code, industry) in tables[0]:
        if industry != industry_code:
            continue
        pairs = [table.get((code, industry)) for table in tables]
        if all(pair and pair[0] and pair[1] is not None for pair in pairs):
            found[code] = (sum(pair[1] for pair in pairs), sum(pair[0] for pair in pairs))
    return found


MIN_STORES = 3  # markets with fewer stores of the industry are too small to compare per store
TOP_MIN_STORES = 10
RELAXED_MIN_STORES = 5
MAX_YEARLY_CHANGE = 100.0  # beyond this the two quarters are hardly comparable


def tier_of(share: float) -> str:
    return "상위권" if share <= 10 else "중상위권" if share <= 30 else "중간" if share <= 70 else "하위권"


def _count(row: dict, field: str) -> int | None:
    value = (row or {}).get(field)
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, Decimal) and value >= 0 and value == value.to_integral_value():
        return int(value)
    return None


def market_table(source, industry_code: str, period: str) -> list[dict]:
    """Every official market of Seoul with sales in this industry, with the four criteria computed."""
    if not hasattr(source, "store_table"):
        return []
    try:
        rows, _version = source.sales(period)
        previous = f"{int(period[:4]) - 1}{period[4:]}"
        previous_rows = source.sales(previous)[0] if previous in source.periods() else {}
        stores, people, areas = source.store_table(period), source.population_table(period), source.areas()
    except Exception as error:  # no comparison with Seoul is better than a guessed one
        _log.info("market table skipped: %s", type(error).__name__)
        return []
    trends, contexts = _trend_sums(source, industry_code, period), _context(source, period)
    closures = _closure_sums(source, industry_code, period)
    table = []
    for (code, industry), row in rows.items():
        sales = _amount(row)
        if industry != industry_code or code not in areas or not sales:
            continue
        area, store_row = areas[code], (stores.get(code) or {}).get(industry_code) or {}
        figure = {"area_code": code, "name": area.get("name") or code, "sales": sales, "people_row": None,
                  "industry_name": row.get("SVC_INDUTY_CD_NM"), "stores": _count(store_row, "SIMILR_INDUTY_STOR_CO"),
                  "franchise": _count(store_row, "FRC_STOR_CO"), "opened": _count(store_row, "OPBIZ_STOR_CO"),
                  "closed": _count(store_row, "CLSBIZ_STOR_CO"), "population": people.get(code),
                  "sales_last_year": _amount(previous_rows.get((code, industry_code))),
                  "selectable": area.get("boundary_identity_status") == "code_name_match",
                  "district_code": area.get("district_code"), "neighborhood_code": area.get("neighborhood_code"),
                  **_place_fields(area, contexts.get(code) or {})}
        if code in trends:
            figure["sales_recent"], figure["sales_before"] = trends[code]
        if code in closures:
            figure["closed_year"], figure["stores_year"] = closures[code]
        table.append(derive(figure))
    return table


def _position(value, pool: list, higher: bool) -> dict:
    """Where a value stands among Seoul's markets, the better side first ('상위 12.50%')."""
    ahead = sum(other > value for other in pool) if higher else sum(other < value for other in pool)
    share = _rounded(ahead + 1, len(pool))
    return {"share": share, "tier": tier_of(share)}


def add_benchmarks(source, figures: list[dict], industry_code: str, period: str, plan: dict | None = None) -> None:
    """Each criterion against every comparable market in Seoul: position, tier and the median.

    Without it the model called a closure rate '낮은 편' with nothing to compare it to (2026-11-08 export).
    """
    table = [row for row in market_table(source, industry_code, period) if (row.get("stores") or 0) >= MIN_STORES]
    for key, _label, unit, higher in criteria_of(plan):
        pool = sorted(row[key] for row in table if row.get(key) is not None)
        if len(pool) < 10:
            continue
        middle = pool[len(pool) // 2]
        for figure in figures:
            if figure.get(key) is not None:
                figure.setdefault("position", {})[key] = {
                    **_position(figure[key], pool, higher), "count": len(pool),
                    "median": round(middle, 2) if unit == "%" else int(middle)}


def _change_of(row: dict) -> float:
    return row["trend"] if row.get("trend") is not None else (row.get("yoy") or 0.0)


def best_markets(table: list[dict], limit: int = 3, plan: dict | None = None) -> tuple[list[dict], int]:
    """The markets that stand best on the weighted criteria together; (top, how many were compared)."""
    criteria = criteria_of(plan)
    # A market with two shops and +1223% is noise, not a recommendation (문래예술촌, 2026-11-08 server test).
    complete = [row for row in table if row.get("selectable") and -50.0 <= _change_of(row) <= MAX_YEARLY_CHANGE
                and all(row.get(key) is not None for key, _label, _unit, _higher in criteria)]
    sizes = sorted(row["sales"] for row in table)
    middle = sizes[len(sizes) // 2] if sizes else 0
    eligible = [row for row in complete if row["stores"] >= TOP_MIN_STORES and row["sales"] >= middle]
    basis = f"점포 {TOP_MIN_STORES}개 이상, 매출이 서울 중앙값 이상, 매출 변화가 +{MAX_YEARLY_CHANGE:.0f}% 이내인 상권"
    if len(eligible) < 5:
        eligible = [row for row in complete if row["stores"] >= RELAXED_MIN_STORES]
        basis = f"점포 {RELAXED_MIN_STORES}개 이상, 매출 변화가 +{MAX_YEARLY_CHANGE:.0f}% 이내인 상권"
    if len(eligible) < 5:
        return [], len(eligible)
    for row in eligible:
        row["basis"] = basis
    for key, _label, _unit, higher in criteria:
        pool = [row[key] for row in eligible]
        for row in eligible:
            row.setdefault("position", {})[key] = {**_position(row[key], pool, higher), "count": len(pool)}
    for row in eligible:
        weights = [(row["position"][key]["share"], plan["weights"][key] if plan else 1) for key, _l, _u, _h in criteria]
        row["overall"] = round(sum(share * weight for share, weight in weights) / sum(weight for _s, weight in weights), 2)
    eligible.sort(key=lambda row: (row["overall"], row["area_code"]))
    return eligible[:limit], len(eligible)


def seoul_card(top: list[dict], *, industry_name: str, period_label: str, compared: int, plan: dict | None = None) -> dict:
    """The candidates of a Seoul-wide opinion, every number an answer may state."""
    values = [{"label": "비교한 상권 수", "value": compared, "unit": "곳"}, *weight_values(plan)]
    sentences = []
    for market in top:
        name = market["name"]
        values += context.card_values(market)
        for key, label, unit in _RAW:
            if market.get(key) is not None:
                values.append({"label": label, "market": name, "value": market[key], "unit": unit})
        parts = []
        for key, label, unit, higher in criteria_of(plan):
            position = market["position"][key]
            values.append({"label": label, "market": name, "value": market[key], "unit": unit, "derived": True})
            values.append({"label": f"{label} 서울 상위 비율", "market": name, "value": position["share"], "unit": "%",
                           "derived": True, "tier": position["tier"], "criterion": label})
            parts.append(f"{label} {fmt(market[key], unit)}({position_words(position, higher)})")
        values.append({"label": "기준 평균 상위 비율", "market": name, "value": market["overall"], "unit": "%", "derived": True})
        sentences.append(f"{place_words(market)}: " + ", ".join(parts) + f". 비중을 반영해 평균하면 상위 {market['overall']:.2f}%입니다.")
        where = context.sentence(market)
        if where:
            sentences.append(where)
    head = (f"서울 {industry_name} 상권 가운데 {top[0]['basis']} {compared:,}곳을 기준별 서울 안 위치로 견줘 "
            f"가장 앞선 {len(top)}곳입니다({period_label}, 계산값). {weight_sentence(plan)}").rstrip()
    return {"id": None, "topic": "opinion", "status": "available", "text": " ".join([head, *sentences]), "values": values,
            "warnings": [DERIVED_NOTE, "기준별 위치를 비중대로 평균한 순서이며, 임대료 같은 비용은 들어 있지 않습니다."],
            "source_ref": {"analysis": "opinion_seoul"}}


def position_words(position: dict, higher: bool) -> str:
    order = "" if higher else "낮은 쪽으로 "
    return f"서울 {order}상위 {position['share']:.2f}%, {position['tier']}"


def seoul_fixed_lines(top: list[dict], card_id: str, plan: dict | None = None) -> list[str]:
    cite = f" [{card_id}]"
    lines = [f"자료만 놓고 보면 저는 서울에서 {top[0]['name']} 상권부터 살펴보겠어요.{cite}"]
    criteria = criteria_of(plan)
    trend_key = next(key for key, *_rest in criteria if key in ("trend", "yoy"))
    trend_label = _ALL_CRITERIA[trend_key][1]
    closure_key = next(key for key, *_rest in criteria if key in ("closure_year", "closure_rate"))
    closure_label = _ALL_CRITERIA[closure_key][1]
    for market in top:
        strongest = sorted(criteria, key=lambda item: market["position"][item[0]]["share"])[:2]
        reasons = ", ".join(f"{label}(상위 {market['position'][key]['share']:.2f}%)" for key, label, _u, _h in strongest)
        particle = josa(market["name"], "은")[len(market["name"]):]  # after the bracket, it follows the name
        lines.append(f"{place_words(market)}{particle} 점포당 분기 추정매출 {fmt(market['per_store_sales'], '원')}, "
                     f"{trend_label} {fmt(market[trend_key], '%')}, {closure_label} {fmt(market[closure_key], '%')}예요. "
                     f"가장 앞선 기준은 {reasons}이고, 비중을 반영해 평균하면 서울 상위 {market['overall']:.2f}%예요.{cite}")
    lines.append(f"숫자로 고른 후보라서, 실제 입지와 가게 자리는 직접 확인해 보셔야 해요.{cite}")
    return lines


def seoul_question(industry_name: str, said: str) -> str:
    ask = (f"서울에서 {industry_name} 창업을 한다면 어느 상권을 먼저 볼지, 상권 비서의 생각을 말해 주세요. "
           "카드의 첫 번째 상권을 중심으로 왜 그런지 숫자와 함께 말하고, 나머지 상권도 짧게 견줘 주세요.")
    return f"{ask}\n(사용자가 한 말: {said.strip()[:200]})" if said and said.strip() else ask


VERDICT_WORDS = {"positive": "해볼 만한 쪽", "cautious": "신중하게 볼 쪽", "mixed": "강점과 약점이 섞인 쪽"}


def standing(positions: dict, plan: dict | None = None) -> tuple[str, int, int]:
    """(verdict, strong criteria, weak criteria), the important criteria counting for more."""
    weights = {key: (plan["weights"].get(key, 0) if plan else 1) for key in positions}
    total = sum(weights.values()) or 1
    strong = [key for key, item in positions.items() if item["tier"] in ("상위권", "중상위권")]
    weak = [key for key, item in positions.items() if item["tier"] == "하위권"]
    good, bad = sum(weights[key] for key in strong) / total, sum(weights[key] for key in weak) / total
    verdict = "positive" if good >= 0.5 and bad == 0 else "cautious" if bad >= 0.4 or not strong else "mixed"
    return verdict, len(strong), len(weak)


def _rounded(numerator, denominator) -> float:
    return float((Decimal(numerator) * 100 / Decimal(denominator)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def derive(figure: dict) -> dict:
    """The four criteria. A criterion is left out when one of its inputs is missing or zero."""
    sales, stores, people, closed = (figure.get(key) for key in ("sales", "stores", "population", "closed"))
    if sales is not None and stores:
        figure["per_store_sales"] = sales // stores
    if people is not None and stores:
        figure["per_store_people"] = people // stores
    if closed is not None and stores:
        figure["closure_rate"] = _rounded(closed, stores)
    if figure.get("stores_year") and figure.get("closed_year") is not None:
        figure["closure_year"] = _rounded(figure["closed_year"] * 4, figure["stores_year"])
    if sales is not None and figure.get("sales_last_year"):
        figure["yoy"] = _rounded(sales - figure["sales_last_year"], figure["sales_last_year"])
    if figure.get("sales_recent") and figure.get("sales_before"):
        figure["trend"] = _rounded(figure["sales_recent"] - figure["sales_before"], figure["sales_before"])
    if stores:
        for source_key, key in (("workers", "per_store_workers"), ("residents", "per_store_residents"),
                                ("households", "per_store_households")):
            if figure.get(source_key) is not None:
                figure[key] = figure[source_key] // stores
    return figure


def fmt(value, unit: str) -> str:
    if unit == "%":
        return f"{value:.2f}%"
    return f"{int(value):,}{unit}"


def _ro(text: str) -> str:
    """'…원으로', '…개로', '…%로' (퍼센트 reads without a final consonant)."""
    return text + ("로" if text.endswith("%") else josa(text, "으로")[len(text):])


def leads(markets: list[dict], plan: dict | None = None) -> list[dict]:
    """Per criterion: both values and which market leads (None for a tie)."""
    if len(markets) != 2:
        return []
    found = []
    for key, label, unit, higher in criteria_of(plan):
        a, b = markets[0].get(key), markets[1].get(key)
        if a is None or b is None:
            continue
        leader = None if a == b else markets[0]["name"] if (a > b) == higher else markets[1]["name"]
        found.append({"key": key, "label": label, "unit": unit, "values": (a, b), "leader": leader, "higher": higher,
                      "weight": plan["weights"][key] if plan else 1})
    return found


def _scores(compared: list[dict], markets: list[dict]) -> dict:
    return {market["name"]: sum(item["weight"] for item in compared if item["leader"] == market["name"]) for market in markets}


def opinion_card(markets: list[dict], *, industry_name: str, period_label: str, plan: dict | None = None) -> dict:
    """One citable card holding every number an opinion may state, computed ones marked."""
    values, sentences = weight_values(plan), []
    criteria = criteria_of(plan)
    for market in markets:
        values += context.card_values(market)
        for key, label, unit in _RAW:
            if market.get(key) is not None:
                values.append({"label": label, "market": market["name"], "value": market[key], "unit": unit})
        for key, label, unit, _higher in criteria:
            if market.get(key) is not None:
                values.append({"label": label, "market": market["name"], "value": market[key], "unit": unit,
                               "derived": True})
                position = (market.get("position") or {}).get(key)
                if position:
                    values.append({"label": f"{label} 서울 상위 비율", "market": market["name"], "value": position["share"],
                                   "unit": "%", "derived": True, "tier": position["tier"], "criterion": label})
                    values.append({"label": f"{label} 서울 중앙값", "value": position["median"], "unit": unit, "derived": True})
        if market.get("rank"):
            values.append({"label": "서울 매출 순위", "market": market["name"], "value": market["rank"], "unit": "위"})
            values.append({"label": "순위를 매긴 상권 수", "market": market["name"], "value": market["ranked"], "unit": "곳"})
            values.append({"label": "서울 매출 상위 비율", "market": market["name"], "unit": "%", "derived": True,
                           "value": _rounded(market["rank"], market["ranked"])})
        for key, label in (("top_age", "매출이 가장 큰 연령대"), ("top_time", "매출이 가장 큰 시간대")):
            if market.get(key):
                values.append({"label": label, "market": market["name"], "value": market[key], "unit": None})
    if len(markets) == 2:
        compared = leads(markets, plan)
        for item in compared:
            a, b = item["values"]
            line = (f"{item['label']}(계산값)은 {markets[0]['name']} {fmt(a, item['unit'])}, "
                    f"{markets[1]['name']} {_ro(fmt(b, item['unit']))}")
            line += f" {josa(item['leader'], '이')} 앞섭니다." if item["leader"] else " 같습니다."
            sentences.append(line)
        counts = {market["name"]: sum(item["leader"] == market["name"] for item in compared) for market in markets}
        if compared:
            sentences.append(f"{len(compared)}개 기준 가운데 {markets[0]['name']} {counts[markets[0]['name']]}개, "
                             f"{markets[1]['name']} {counts[markets[1]['name']]}개에서 앞섭니다.")
            values.append({"label": "비교한 기준 수", "value": len(compared), "unit": "개"})
            for market in markets:
                values.append({"label": "앞선 기준 수", "market": market["name"], "value": counts[market["name"]],
                               "unit": "개"})
            if plan:
                scores = _scores(compared, markets)
                sentences.append("비중을 반영한 점수는 " + ", ".join(f"{name} {round(score)}점" for name, score in scores.items())
                                 + "입니다.")
                values += [{"label": "비중 반영 점수", "market": name, "value": round(score), "unit": "점"}
                           for name, score in scores.items()]
        head = f"{josa(markets[0]['name'], '과')} {markets[1]['name']}의 {industry_name} {period_label} 판단 기준입니다."
    else:
        market = markets[0]
        for key, label, unit, higher in criteria:
            if market.get(key) is not None:
                position = (market.get("position") or {}).get(key)
                where = (f" 서울 {industry_name} 상권 {position['count']:,}곳 가운데 {position_words(position, higher)}이고, "
                         f"서울 중앙값은 {fmt(position['median'], unit)}입니다.") if position else ""
                sentences.append(f"{label}(계산값)은 {fmt(market[key], unit)}입니다.{where}")
        if market.get("position"):
            verdict, good, bad = standing(market["position"], plan)
            values += [{"label": "종합 판단", "market": market["name"], "value": VERDICT_WORDS[verdict], "unit": None,
                        "verdict": verdict},
                       {"label": "강점 기준 수", "value": good, "unit": "개"}, {"label": "약점 기준 수", "value": bad, "unit": "개"}]
            sentences.append(f"기준을 비중대로 합친 종합 판단은 '{VERDICT_WORDS[verdict]}'입니다"
                             f"(중상위권 이상 강점 {good}개, 하위권 약점 {bad}개).")
        head = f"{market['name']}의 {industry_name} {period_label} 판단 기준입니다."
    if len(markets) == 2:
        for market in markets:
            placed = [f"{label} {position_words(market['position'][key], higher)}"
                        for key, label, _unit, higher in criteria if key in (market.get("position") or {})]
            if placed:
                sentences.append(f"{market['name']}의 서울 안 위치는 " + ", ".join(placed) + "입니다.")
    for market in markets:
        if market.get("rank"):
            sentences.append(f"{josa(market['name'], '은')} 서울 {industry_name} 상권 {rank_phrase(market)}입니다(매출 총액 기준).")
    for market in markets:
        where = context.sentence(market)
        if where:
            sentences.append(where)
    if plan:
        sentences.append(weight_sentence(plan))
    for market in markets:
        if market.get("top_age") or market.get("top_time"):
            parts = [f"연령대는 {market['top_age']}" if market.get("top_age") else "",
                     f"시간대는 {market['top_time']}" if market.get("top_time") else ""]
            sentences.append(f"{market['name']}에서 매출이 가장 큰 " + ", ".join(p for p in parts if p) + "입니다.")
    return {"id": None, "topic": "opinion", "status": "available" if sentences else "no_data",
            "text": " ".join([head, *sentences]) if sentences else head + " 비교할 수 있는 기준이 없습니다.",
            "values": values, "warnings": [DERIVED_NOTE], "source_ref": {"analysis": "opinion"}}


def writer_question(markets: list[dict], industry_name: str, said: str) -> str:
    """The question the model answers. '너의 생각이 궁금해서 그런 거야' alone made HCX-005 refuse
    ('인공지능이라 견해가 없다') and write a paragraph without one number (2026-11-08 server test)."""
    if len(markets) == 2:
        ask = (f"{josa(markets[0]['name'], '과')} {markets[1]['name']} 가운데 {industry_name} 창업에 어디가 더 나을지, "
               "상권 비서의 생각을 판단 기준 숫자와 함께 말해 주세요.")
    else:
        ask = f"{markets[0]['name']}에서 {industry_name} 창업을 해볼 만한지, 상권 비서의 생각을 판단 기준 숫자와 함께 말해 주세요."
    return f"{ask}\n(사용자가 한 말: {said.strip()[:200]})" if said and said.strip() else ask


def rank_phrase(market: dict) -> str:
    """'1,064곳 가운데 매출 19위(상위 1.79%, 상위권)': the tier is written by code, since HCX-005 once called
    19th of 1,064 '아주 높은 편은 아니다' (2026-11-08 server test)."""
    share = _rounded(market["rank"], market["ranked"])
    tier = "상위권" if share <= 10 else "중상위권" if share <= 30 else "중간" if share <= 70 else "하위권"
    return f"{market['ranked']:,}곳 가운데 매출 {market['rank']}위(상위 {share:.2f}%, {tier})"


def _positives(market: dict) -> list[str]:
    found = []
    if market.get("yoy") is not None and market["yoy"] > 0:
        found.append("yoy")
    if market.get("opened") is not None and market.get("closed") is not None and market["opened"] >= market["closed"]:
        found.append("open_close")
    if market.get("rank") and market["rank"] * 100 <= market["ranked"] * 30:
        found.append("rank")
    return found


def fixed_lines(markets: list[dict], card_id: str, plan: dict | None = None) -> list[str]:
    """The opinion without a model: a lean, the reasons on both sides, nothing beyond the card."""
    cite = f" [{card_id}]"
    lines = []
    if len(markets) == 2:
        compared = leads(markets, plan)
        counts = _scores(compared, markets)
        first, second = markets[0]["name"], markets[1]["name"]
        if not compared:
            return [f"두 곳을 견줄 기준 값이 부족해서 한쪽을 고르기는 어려워요.{cite}"]
        if counts[first] == counts[second]:
            lines.append(f"기준마다 앞서는 곳이 엇갈려서, 자료만으로는 어느 한쪽이 낫다고 하기 어려워요.{cite}")
        else:
            winner = first if counts[first] > counts[second] else second
            lines.append(f"자료로만 보면 저는 {winner} 쪽이 조금 더 나아 보여요.{cite}")
        for item in compared:
            a, b = item["values"]
            line = f"{josa(item['label'], '은')} {first} {fmt(a, item['unit'])}, {second} {_ro(fmt(b, item['unit']))}"
            lines.append(line + (f" {josa(item['leader'], '이')} 앞서요.{cite}" if item["leader"] else " 같아요." + cite))
    else:
        market = markets[0]
        positions = market.get("position") or {}
        if positions:
            # Judged by where the market stands in Seoul on each criterion, weak points said as plainly as strong ones.
            verdict = {"positive": "해볼 만한 쪽으로 보여요", "cautious": "조금 신중하게 보시는 게 좋겠어요",
                       "mixed": "강점과 약점이 섞여 있어서, 어떤 점을 더 중요하게 보느냐에 따라 달라 보여요"}[standing(positions, plan)[0]]
            lines.append(f"자료로만 보면 {market['name']} 상권은 {verdict}.{cite}")
            for key, label, unit, higher in criteria_of(plan):
                if key in positions:
                    lines.append(f"{josa(label, '은')} {_ro(fmt(market[key], unit))} "
                                 f"{position_words(positions[key], higher)}이에요.{cite}")
            return lines
        positive = _positives(market)
        verdict = "해볼 만한 쪽으로 보여요" if len(positive) >= 2 else "조금 신중하게 보시는 게 좋겠어요"
        lines.append(f"자료로만 보면 {market['name']} 상권은 {verdict}.{cite}")
        if market.get("rank"):
            lines.append(f"서울 {rank_phrase(market)}예요.{cite}")
        if market.get("yoy") is not None:
            lines.append(f"작년 같은 분기 대비 매출 변화율은 {market['yoy']:+.2f}%예요.{cite}")
        if market.get("opened") is not None and market.get("closed") is not None:
            lines.append(f"같은 분기에 개업 {market['opened']:,}곳, 폐업 {market['closed']:,}곳이었어요.{cite}")
        if market.get("per_store_sales") is not None:
            lines.append(f"점포당 분기 추정매출은 {fmt(market['per_store_sales'], '원')}이에요.{cite}")
    return lines
