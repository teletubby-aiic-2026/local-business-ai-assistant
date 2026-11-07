"""Seoul-wide quarterly sales ranking of official markets for one industry.

The code sorts; no model is involved. Values are the B2 source's
THSMON_SELNG_AMT for one market, industry and quarter, read through the same
provenance-checked loader as PR #12's sales analysis (onboarding_sales). No
new statistic is derived: nothing is divided, averaged or rounded.

A total is the sum over every shop of that industry in the market, so large
markets with many shops rank high. The card says so; it is not a measure of
how well one shop does or of where to open one.
"""
from __future__ import annotations

from dataclasses import dataclass
import threading

from app.assistant.korean import josa

SCHEMA = "assistant-ranking-v1"
DEFAULT_LIMIT = 5
WARNING_TOTAL = ("상권 안 같은 업종 가게 전체의 분기 추정매출을 합친 값이라 점포가 많은 큰 상권일수록 크게 나옵니다. "
                 "가게 한 곳의 매출이나 창업 성과를 뜻하지 않습니다.")
WARNING_MISSING = "해당 업종의 추정매출 자료가 없는 상권은 순위에 넣지 않았습니다."


@dataclass(frozen=True)
class Exclusion:
    """What the user asked to leave out ('강남 말고')."""
    district_codes: frozenset = frozenset()
    neighborhood_codes: frozenset = frozenset()
    name_parts: tuple = ()
    labels: tuple = ()

    def matches(self, area: dict) -> bool:
        return (area.get("district_code") in self.district_codes
                or area.get("neighborhood_code") in self.neighborhood_codes
                or any(part in (area.get("name") or "") for part in self.name_parts))

    def to_dict(self) -> dict:
        return {"district_codes": sorted(self.district_codes), "neighborhood_codes": sorted(self.neighborhood_codes),
                "name_parts": list(self.name_parts), "labels": list(self.labels)}

    @classmethod
    def from_dict(cls, data: dict | None) -> "Exclusion | None":
        if not data:
            return None
        return cls(frozenset(data.get("district_codes", [])), frozenset(data.get("neighborhood_codes", [])),
                   tuple(data.get("name_parts", [])), tuple(data.get("labels", [])))

    @classmethod
    def from_mentions(cls, mentions: list[dict]) -> "Exclusion | None":
        """'강남' -> 강남구 and names containing '강남'; '홍대' -> 서교동 and names containing '홍대입구'/'홍대'."""
        districts, neighborhoods, parts, labels = set(), set(), [], []
        for mention in mentions:
            text = mention["text"]
            if len(text) >= 2:
                parts.append(text)
            for place in mention["candidates"]:
                if place["kind"] == "district":
                    districts.add(place["district_code"])
                    labels.append(place["label"])
                elif place["kind"] == "neighborhood":
                    neighborhoods.add(place["code"])
                    labels.append(place["label"])
                elif place["kind"] == "station":
                    base = place["name"][:-1] if place["name"].endswith("역") else place["name"]
                    if len(base) >= 2:
                        parts.append(base)
        if not (districts or neighborhoods or parts):
            return None
        parts = tuple(dict.fromkeys(parts))
        return cls(frozenset(districts), frozenset(neighborhoods), parts,
                   tuple(dict.fromkeys(labels)))

    def describe(self) -> str:
        """"강남구 전체와 이름에 '강남'이 들어간 상권은" for the answer text."""
        pieces = []
        if self.labels:
            pieces.append("·".join(self.labels) + " 전체")
        if self.name_parts:
            quoted = ", ".join(f"'{part}'" for part in self.name_parts)
            pieces.append("이름에 " + josa(quoted, "이") + " 들어간 상권")
        if not pieces:
            return ""
        joined = pieces[0] if len(pieces) == 1 else josa(pieces[0], "과") + " " + pieces[1]
        return josa(joined, "은")


class SeoulSalesSource:
    """Real data: the B1 catalogue's markets and the B2 quarterly sales pages."""

    def __init__(self):
        self._areas_key = None
        self._areas = None
        self._lock = threading.Lock()

    def periods(self) -> list[str]:
        from app.onboarding_analysis_catalog import get_analysis_catalog_source

        source = get_analysis_catalog_source()
        return sorted({entry["period"] for entry in source["files"] if entry["dataset"] == "sales"})

    def areas(self) -> dict[str, dict]:
        from app.onboarding_analysis_catalog import get_analysis_areas, get_analysis_catalog_source

        version = get_analysis_catalog_source()["catalog_version"]
        with self._lock:
            if self._areas_key != version:
                self._areas = {area["area_code"]: area for area in get_analysis_areas()}
                self._areas_key = version
            return self._areas

    def sales(self, period: str) -> tuple[dict, str]:
        """{(area_code, industry_code): row} and a data version for the card."""
        from app.data_repository import canonical_hash
        from app.onboarding_analysis_catalog import get_analysis_catalog_source
        from app.onboarding_sales import _RAW, _load_sales_period

        source = get_analysis_catalog_source()
        rows, _evidence, period_evidence = _load_sales_period(source, period, _RAW)
        version = "b2_" + canonical_hash({"schema": "sales-v1", "catalog_version": source["catalog_version"],
                                          "period": period,
                                          "files": [(e["file_name"], e["file_sha256"]) for e in period_evidence]})[:24]
        return rows or {}, version

    def area_sales(self, period: str, area_code: str) -> tuple[dict, str]:
        """{industry_code: row} for one market."""
        rows, version = self.sales(period)
        return {industry: row for (area, industry), row in rows.items() if area == area_code}, version

    def area_stores(self, period: str, area_code: str) -> dict | None:
        """{industry_code: store count} for one market, or None when store pages were not collected."""
        from app.onboarding_analysis_catalog import get_analysis_catalog_source
        from app.onboarding_stores import _RAW, FIELDS, _load_area_period

        rows, _evidence, _count, status, _all = _load_area_period(get_analysis_catalog_source(), area_code, period, _RAW)
        if status == "not_collected":
            return None
        field = FIELDS["total"][1]
        return {industry: row.get(field) for industry, row in (rows or {}).items()
                if type(row.get(field)) is int and row.get(field) >= 0}


def _amount(row: dict):
    from app.onboarding_sales import _TOTAL_FIELD, SalesDataError, _money

    try:
        return _money(row.get(_TOTAL_FIELD))
    except SalesDataError:
        return None


@dataclass
class RankingRequest:
    industry_code: str
    industry_name: str | None = None
    period: str | None = None
    district_codes: frozenset = frozenset()
    district_labels: tuple = ()
    exclusion: Exclusion | None = None
    limit: int = DEFAULT_LIMIT


def period_label(period: str) -> str:
    return f"{period[:4]}년 {period[4]}분기"


def rank_sales(source, request: RankingRequest) -> dict:
    periods = source.periods()
    if not periods:
        return {"status": "not_collected", "message": "추정매출 원천 자료를 아직 확보하지 않았습니다."}
    period = request.period or periods[-1]
    if period not in periods:
        return {"status": "period_unavailable", "period": period, "period_label": period_label(period)}
    rows, data_version = source.sales(period)
    areas = source.areas()
    entries, excluded, industry_name = [], 0, request.industry_name
    for (area_code, industry_code), row in rows.items():
        if industry_code != request.industry_code:
            continue
        area = areas.get(area_code)
        value = _amount(row)
        if area is None or value is None:
            continue
        industry_name = industry_name or row.get("SVC_INDUTY_CD_NM")
        if request.district_codes and area.get("district_code") not in request.district_codes:
            continue
        if request.exclusion is not None and request.exclusion.matches(area):
            excluded += 1
            continue
        entries.append({"area_code": area_code, "name": area.get("name") or row.get("TRDAR_CD_NM"),
                        "type": area.get("type"), "district_code": area.get("district_code"),
                        "district_name": area.get("district_name"),
                        "neighborhood_code": area.get("neighborhood_code"),
                        "neighborhood_name": area.get("neighborhood_name"),
                        "selectable": area.get("boundary_identity_status") == "code_name_match",
                        "value": value})
    entries.sort(key=lambda entry: (-entry["value"], entry["area_code"]))
    top = entries[:request.limit]
    for rank, entry in enumerate(top, start=1):
        entry["rank"] = rank
    return {"schema_version": SCHEMA, "status": "available" if top else "no_data", "period": period,
            "period_label": period_label(period), "industry_code": request.industry_code,
            "industry_name": industry_name or request.industry_code, "items": top,
            "compared_count": len(entries), "excluded_count": excluded,
            "scope_label": "·".join(request.district_labels) if request.district_codes else "서울 전체",
            "exclusion": request.exclusion.to_dict() if request.exclusion else None,
            "data_version": data_version}


def item_label(item: dict) -> str:
    where = item.get("district_name") or ""
    return f"{item['rank']}위 {item['name']}" + (f" ({where})" if where else "")


def ranking_card(result: dict) -> dict:
    """One citable card. Values carry every number the answer may state."""
    count = len(result["items"])
    text = (f"{result['scope_label']} 상권 가운데 {result['industry_name']} 업종의 "
            f"{result['period_label']} 추정매출 상위 {count}곳입니다.")
    values = [{"label": item_label(item), "value": item["value"], "unit": "원", "area_code": item["area_code"]}
              for item in result["items"]]
    values += [{"label": "순위에 보인 상권 수", "value": count, "unit": "곳"},
               {"label": "비교한 상권 수", "value": result["compared_count"], "unit": "곳"},
               {"label": "기간", "value": result["period_label"], "unit": None, "code": result["period"]}]
    return {"id": "F1", "topic": "ranking", "status": "available", "text": text, "values": values,
            "warnings": [WARNING_TOTAL, WARNING_MISSING],
            "source_ref": {"analysis": "ranking", "data_version": result.get("data_version"),
                           "source_title": "서울시 상권분석서비스 추정매출",
                           "source_url": _sales_url()}}


# Industries inside one market ---------------------------------------------------
INDUSTRY_COUNT = 3
WARNING_INDUSTRY = ("업종별로 상권 안 가게 전체의 분기 추정매출을 합친 값이라 점포가 많은 업종일수록 크게 나옵니다. "
                    "매출이 크다고 새로 열기 좋은 업종이라는 뜻은 아니므로 점포 수(경쟁)도 함께 보세요.")


def areas_for_mentions(source, mentions: list[dict]) -> list[dict]:
    """Official markets for '홍대' / '서교동': same 동, or a name containing the station name."""
    areas = source.areas()
    found = {}
    for mention in mentions:
        for place in mention["candidates"]:
            if place["kind"] == "neighborhood":
                matches = [a for a in areas.values() if a.get("neighborhood_code") == place["code"]]
            elif place["kind"] == "station":
                base = place["name"][:-1] if place["name"].endswith("역") else place["name"]
                matches = [a for a in areas.values() if len(base) >= 2 and base in (a.get("name") or "")]
            else:
                matches = []  # a 구 has too many markets to pick one
            for area in matches:
                found.setdefault(area["area_code"], area)
    return sorted(found.values(), key=lambda a: (a.get("name") or "", a["area_code"]))


def order_markets(source, areas: list[dict]) -> list[dict]:
    """Markets with sales data first, larger ones first; markets without any sales row are left out.

    The totals only order the choice buttons and are never shown, so no derived number reaches an answer.
    """
    periods = source.periods()
    if not periods or not areas:
        return areas
    rows, _version = source.sales(periods[-1])
    wanted = {area["area_code"] for area in areas}
    totals: dict[str, int] = {}
    for (area_code, _industry), row in rows.items():
        if area_code in wanted:
            value = _amount(row)
            if value:
                totals[area_code] = totals.get(area_code, 0) + value
    with_data = [area for area in areas if totals.get(area["area_code"])]
    return sorted(with_data, key=lambda area: -totals[area["area_code"]]) or areas


def rank_industries(source, area_code: str, *, period: str | None = None, limit: int = INDUSTRY_COUNT,
                    excluded_codes=()) -> dict:
    """Industries of one market by quarterly sales, with that industry's store count when collected."""
    periods = source.periods()
    if not periods:
        return {"status": "not_collected", "message": "추정매출 원천 자료를 아직 확보하지 않았습니다."}
    period = period or periods[-1]
    if period not in periods:
        return {"status": "period_unavailable", "period": period, "period_label": period_label(period)}
    area = source.areas().get(area_code) or {}
    rows, data_version = source.area_sales(period, area_code)
    try:
        stores = source.area_stores(period, area_code)
    except Exception:  # store pages are optional here; sales alone still rank
        stores = None
    entries, excluded = [], []
    for industry_code, row in rows.items():
        value = _amount(row)
        if value is None:
            continue
        name = row.get("SVC_INDUTY_CD_NM") or industry_code
        if industry_code in excluded_codes:
            excluded.append(name)
            continue
        entries.append({"industry_code": industry_code, "industry_name": name, "value": value,
                        "stores": (stores or {}).get(industry_code)})
    entries.sort(key=lambda entry: (-entry["value"], entry["industry_code"]))
    top = entries[:limit]
    for rank, entry in enumerate(top, start=1):
        entry["rank"] = rank
    return {"schema_version": SCHEMA, "status": "available" if top else "no_data", "area_code": area_code,
            "area_name": area.get("name") or area_code, "district_name": area.get("district_name"),
            "neighborhood_code": area.get("neighborhood_code"), "district_code": area.get("district_code"),
            "selectable": area.get("boundary_identity_status") == "code_name_match",
            "period": period, "period_label": period_label(period), "items": top, "compared_count": len(entries),
            "excluded": sorted(set(excluded)), "stores_collected": stores is not None, "data_version": data_version}


def industry_rank_cards(result: dict) -> list[dict]:
    """F1 = market and quarter, F2 = the industries. Values carry every number an answer may state."""
    conditions = {"id": "F1", "topic": "conditions", "status": "available",
                  "text": f"분석 조건은 {result['area_name']} 상권, 전체 업종, {result['period_label']} 자료입니다.",
                  "values": [{"label": "상권", "value": result["area_name"], "unit": None, "code": result["area_code"]},
                             {"label": "기간", "value": result["period_label"], "unit": None, "code": result["period"]}],
                  "warnings": [], "source_ref": {"analysis": "industry_rank"}}
    count = len(result["items"])
    values = []
    for item in result["items"]:
        values.append({"label": f"{item['rank']}위 {item['industry_name']} 매출", "value": item["value"], "unit": "원",
                       "industry_code": item["industry_code"]})
        if item.get("stores") is not None:
            values.append({"label": f"{item['rank']}위 {item['industry_name']} 점포", "value": item["stores"], "unit": "개"})
    values.append({"label": "비교한 업종 수", "value": result["compared_count"], "unit": "개"})
    warnings = [WARNING_INDUSTRY]
    if not result.get("stores_collected"):
        warnings.append("이 분기의 점포 원천 자료가 없어 점포 수는 보여 드리지 않습니다.")
    ranked = {"id": "F2", "topic": "industry_rank", "status": "available",
              "text": f"{result['area_name']} 상권에서 {result['period_label']} 추정매출이 큰 업종 상위 {count}개입니다.",
              "values": values, "warnings": warnings,
              "source_ref": {"analysis": "industry_rank", "data_version": result.get("data_version"),
                             "source_title": "서울시 상권분석서비스 추정매출·점포", "source_url": _sales_url()}}
    return [conditions, ranked]


def _sales_url():
    try:
        from app.data_repository import SOURCE_URLS

        return SOURCE_URLS.get("sales")
    except Exception:  # pragma: no cover - the URL is decoration only
        return None
