"""What kind of place a market is: workers, residents, facilities and how it is changing.

User request 2026-11-08: a Seoul-wide recommendation picked by sales figures
alone cannot tell what a place is. The Seoul open-data service has four more
quarterly datasets per official market, kept here beside (not inside) PR #12's
provenance-checked catalogue. scripts/collect_assistant_context.py writes them
under data/assistant_context/; this module only reads them. With no files the
assistant works as before, without these figures.

The location type is computed by code from where a market stands among all
markets, so the model can say '직장 수요형' only when the card does.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import math
from pathlib import Path
import re

CONTEXT_DIR = Path(__file__).resolve().parents[2] / "data" / "assistant_context"
SCHEMA = "assistant-context-v1"
# name -> (Seoul open-data service, fields kept)
DATASETS = {
    "workers": ("VwsmTrdarWrcPopltnQq", ("TOT_WRC_POPLTN_CO",)),
    "residents": ("VwsmTrdarRepopQq", ("TOT_REPOP_CO", "TOT_HSHLD_CO")),
    "facilities": ("VwsmTrdarFcltyQq", ("VIATR_FCLTY_CO", "SUBWAY_STATN_CO", "BUS_STTN_CO", "UNIV_CO", "GEHSPT_CO",
                                        "GNRL_HSPTL_CO", "ELESCH_CO", "MSKUL_CO", "HGSCHL_CO")),
    "change": ("VwsmTrdarIxQq", ("TRDAR_CHNGE_IX_NM", "OPR_SALE_MT_AVRG", "CLS_SALE_MT_AVRG",
                                 "SU_OPR_SALE_MT_AVRG", "SU_CLS_SALE_MT_AVRG")),
}
WARNING = "직장인구·상주인구·집객시설·상권 변화는 서울시 상권분석서비스 자료이며, 입지 유형은 그 값으로 서버가 나눈 것입니다."
_PERIOD = re.compile(r"^\d{4}[1-4]$")
_FILE = re.compile(r"^([a-z]+)_(\d{4}[1-4])\.json$")
_TITLES = {"workers": "직장인구", "residents": "상주인구·세대 수", "facilities": "집객시설", "change": "상권 변화"}
_CACHE: dict = {}


def _number(value) -> Decimal | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() and number >= 0 else None


def _whole(value) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number == number.to_integral_value() else None


def _months(value) -> int | float | None:
    """An average duration may be fractional; counts may not."""
    number = _number(value)
    if number is None:
        return None
    if number == number.to_integral_value():
        return int(number)
    result = float(number)
    return result if math.isfinite(result) else None


def _rows(name: str, period: str, folder: Path) -> tuple[dict, dict]:
    """Rows and provenance from the newest eligible file; never hide an invalid latest file."""
    best = None
    if folder.is_dir():
        for path in folder.iterdir():
            match = _FILE.match(path.name)
            if match and match.group(1) == name and match.group(2) <= period and (best is None or path.name > best.name):
                best = path
    if best is None:
        return {}, {}
    file_period = _FILE.fullmatch(best.name).group(2)
    stat = best.stat()
    key = (str(best), stat.st_mtime_ns, stat.st_size)
    if key not in _CACHE:
        try:
            raw = best.read_bytes()
            document = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, ValueError):
            return {}, {}
        if (not isinstance(document, dict) or document.get("schema") != SCHEMA
                or not isinstance(document.get("rows"), dict)
                or document.get("period", file_period) != file_period
                or document.get("service", DATASETS[name][0]) != DATASETS[name][0]
                or any(not isinstance(row, dict) for row in document["rows"].values())):
            return {}, {}
        source = {"dataset": name, "title": _TITLES[name], "service": DATASETS[name][0], "period": file_period,
                  "fetched_at": document.get("fetched_at"), "filename": best.name, "sha256": sha256(raw).hexdigest()}
        _CACHE[key] = document["rows"], source
    rows, source = _CACHE[key]
    return rows, {**source, "requested_period": period}


def _top_third_line(values: list) -> float:
    ordered = sorted((value for value in values if value is not None), reverse=True)
    return ordered[len(ordered) * 3 // 10] if ordered else float("inf")


def _kind(row: dict, lines: dict, floating) -> str:
    workers, residents = row.get("workers") or 0, row.get("residents") or 0
    if workers >= lines["workers"] and workers >= residents * 1.5:
        return "직장 수요형"
    if residents >= lines["residents"] and residents >= workers * 1.5:
        return "주거 수요형"
    if floating is not None and floating >= lines["floating"]:
        return "유동 인구형"
    if workers >= lines["workers"] or residents >= lines["residents"]:
        return "복합 수요형"
    return "수요 규모가 작은 편"


def area_table(period: str, floating: dict | None = None, *, folder: Path | None = None) -> dict:
    """{area_code: figures and location type} for every market with collected context, or {}."""
    folder = folder or CONTEXT_DIR
    if not isinstance(period, str) or not _PERIOD.fullmatch(period):
        return {}
    datasets = {name: _rows(name, period, folder) for name in DATASETS}
    workers, residents, facilities, change = (datasets[name][0] for name in DATASETS)
    table = {}
    for code in set(workers) | set(residents) | set(facilities) | set(change):
        spot, change_row = facilities.get(code) or {}, change.get(code) or {}
        counts = [_whole(spot.get(field)) for field in ("ELESCH_CO", "MSKUL_CO", "HGSCHL_CO")]
        hospitals = [_whole(spot.get(field)) for field in ("GEHSPT_CO", "GNRL_HSPTL_CO")]
        table[code] = {"workers": _whole((workers.get(code) or {}).get("TOT_WRC_POPLTN_CO")),
                       "residents": _whole((residents.get(code) or {}).get("TOT_REPOP_CO")),
                       "households": _whole((residents.get(code) or {}).get("TOT_HSHLD_CO")),
                       "facilities": _whole(spot.get("VIATR_FCLTY_CO")), "subway": _whole(spot.get("SUBWAY_STATN_CO")),
                       "bus": _whole(spot.get("BUS_STTN_CO")), "university": _whole(spot.get("UNIV_CO")),
                       "schools": sum(counts) if all(count is not None for count in counts) else None,
                       "hospitals": sum(hospitals) if all(count is not None for count in hospitals) else None,
                       "change_name": change_row.get("TRDAR_CHNGE_IX_NM") or None,
                       "open_months": _months(change_row.get("OPR_SALE_MT_AVRG")),
                       "close_months": _months(change_row.get("CLS_SALE_MT_AVRG")),
                       "seoul_open_months": _months(change_row.get("SU_OPR_SALE_MT_AVRG")),
                       "seoul_close_months": _months(change_row.get("SU_CLS_SALE_MT_AVRG")),
                       "context_requested_period": period,
                       "context_sources": {name: dict(source) for name, (rows, source) in datasets.items() if code in rows}}
    floating = floating or {}
    lines = {"workers": _top_third_line([row["workers"] for row in table.values()]),
             "residents": _top_third_line([row["residents"] for row in table.values()]),
             "floating": _top_third_line(list(floating.values()))}
    for code, row in table.items():
        if row["workers"] is not None and row["residents"] is not None:
            row["kind"] = _kind(row, lines, floating.get(code))
    return table


_VALUES = (("workers", "직장인구", "명"), ("residents", "상주인구", "명"), ("households", "세대 수", "세대"),
           ("facilities", "집객시설 수", "개"), ("subway", "지하철역 수", "개"), ("bus", "버스정류장 수", "개"),
           ("university", "대학교 수", "개"), ("schools", "초중고 수", "개"), ("hospitals", "병원 수", "개"),
           ("open_months", "운영 중 가게 평균 영업 기간", "개월"), ("close_months", "폐업 가게 평균 영업 기간", "개월"),
           ("seoul_open_months", "서울 운영 중 가게 평균 영업 기간", "개월"),
           ("seoul_close_months", "서울 폐업 가게 평균 영업 기간", "개월"))
_VALUE_DATASETS = {"workers": "workers", "residents": "residents", "households": "residents",
                   **{key: "facilities" for key in ("facilities", "subway", "bus", "university", "schools", "hospitals")},
                   **{key: "change" for key in ("change_name", "open_months", "close_months", "seoul_open_months", "seoul_close_months")}}


def _period_label(period: str) -> str:
    return f"{period[:4]}년 {period[4]}분기"


def period_sentence(figure: dict) -> str:
    """State every context dataset's own quarter, including a disclosed earlier-quarter fallback."""
    sources = figure.get("context_sources") or {}
    if not sources:
        return ""
    prefix = f"{figure['name']}의 " if figure.get("name") else ""
    parts = [f"{_TITLES[name]} {_period_label(source['period'])}" for name, source in sources.items()]
    text = prefix + "입지 자료 기준분기: " + ", ".join(parts) + "."
    requested = figure.get("context_requested_period")
    if requested and any(source["period"] != requested for source in sources.values()):
        text += f" 선택한 {_period_label(requested)}보다 이전 자료가 포함되어 있습니다."
    return text


def _value_source(figure: dict, key: str) -> dict:
    source = (figure.get("context_sources") or {}).get(_VALUE_DATASETS.get(key))
    return {"source_period": source["period"], "source_ref": dict(source)} if source else {}


def card_values(figure: dict) -> list[dict]:
    """Every context number of one market, for the card an answer may cite."""
    name = figure.get("name")
    values = [{"label": label, "market": name, "value": figure[key], "unit": unit, **_value_source(figure, key)}
              for key, label, unit in _VALUES if figure.get(key) is not None]
    for key, label in (("kind", "입지 유형"), ("change_name", "상권 변화 지표"), ("area_type", "상권 구분")):
        if figure.get(key):
            values.append({"label": label, "market": name, "value": figure[key], "unit": None, **_value_source(figure, key)})
    sources = figure.get("context_sources") or {}
    if sources and figure.get("context_requested_period"):
        values.append({"label": "분석 선택 분기", "market": name,
                       "value": _period_label(figure["context_requested_period"]), "unit": None})
    for dataset, source in sources.items():
        values.append({"label": f"{_TITLES[dataset]} 자료 기준분기", "market": name,
                       "value": _period_label(source["period"]), "unit": None,
                       "source_period": source["period"], "source_ref": dict(source)})
    return values


def sentence(figure: dict) -> str:
    """'…의 입지 유형은 직장 수요형입니다(직장인구 …, 상주인구 …). …' or '' with nothing collected."""
    name = figure.get("name")
    parts = [f"{label} {figure[key]:,}{unit}" for key, label, unit in _VALUES[:6] if figure.get(key) is not None]
    if not parts and not figure.get("kind"):
        return ""
    text = f"{name}의 입지 유형은 {figure['kind']}입니다" if figure.get("kind") else f"{name}의 입지 자료입니다"
    text += f"({', '.join(parts)})." if parts else "."
    if figure.get("change_name"):
        text += f" 상권 변화 지표는 '{figure['change_name']}'입니다."
    if figure.get("open_months") is not None and figure.get("seoul_open_months") is not None:
        text += (f" 운영 중인 가게의 평균 영업 기간은 {figure['open_months']}개월로, "
                 f"서울 평균은 {figure['seoul_open_months']}개월입니다.")
    if note := period_sentence(figure):
        text += " " + note
    return text


def profile_card(figure: dict) -> dict | None:
    """'근처에 회사가 많아?': one market's location figures as one card, or None when not collected."""
    text = sentence(figure)
    if not text:
        return None
    return {"id": None, "topic": "area_profile", "status": "available", "text": text, "values": card_values(figure),
            "warnings": [WARNING], "source_ref": {"analysis": "area_profile", "source_title": "서울시 상권분석서비스",
                                                  "requested_period": figure.get("context_requested_period"),
                                                  "sources": figure.get("context_sources") or {}}}
