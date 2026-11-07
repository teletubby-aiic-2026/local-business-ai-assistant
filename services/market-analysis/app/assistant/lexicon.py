"""Dictionaries for the question classifier.

Official station, neighbourhood, district and industry names come from the
B1 selection lists that PR #12 already ships. Only colloquial aliases and
keywords live in ``aliases/*.json`` so that teammates can edit them without
touching code. Nothing here calls a network service or a language model.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata

from app.onboarding_catalog import get_options

ALIAS_DIR = Path(__file__).resolve().parent / "aliases"
_SPACE = re.compile(r"\s+")
# 망원1동 -> 망원동, 성수1가1동 -> 성수동, 종로1.2.3.4가동 -> 종로동, 잠실본동 -> 잠실동
_NUMBERED_DONG = re.compile(r"^(?P<stem>.+?)(?:본|[\d.·]+(?:가[\d.·]*)?)동$")
_PARENTHESIS = re.compile(r"\(.*?\)")


def compact(text: str) -> str:
    """NFC, lower case, whitespace removed. All matching happens on this form."""
    return _SPACE.sub("", unicodedata.normalize("NFC", text or "")).lower()


def _read(name: str) -> dict:
    return json.loads((ALIAS_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def keywords() -> dict:
    data = _read("intent_keywords.json")
    def norm(value):
        if isinstance(value, str):
            return compact(value)
        if isinstance(value, list):
            return [norm(item) for item in value]
        if isinstance(value, dict):
            return {key: norm(item) for key, item in value.items()}
        return value
    # correction_lemmas holds part-of-speech tags such as "VV"; they must keep their case.
    return {key: (norm(value) if key not in ("note", "schema_version", "status", "correction_lemmas") else value)
            for key, value in data.items()}


def _place(kind, name, *, label=None, code=None, district_code=None, district_name=None, station_ids=None):
    return {"kind": kind, "name": name, "label": label or name, "code": code,
            "district_code": district_code, "district_name": district_name,
            "station_ids": list(station_ids or [])}


def place_index() -> dict[str, list[dict]]:
    """compact key -> candidate places. One key may point to several places."""
    return _places()[0]


def bare_place_keys() -> frozenset[str]:
    """Keys that are only short forms (강남, 성수, 을지로) without 역·동·구.

    The classifier accepts them only at a word start so that '빵집은 천연' does not
    become 은천동 and '노래방이고' does not become 방이동.
    """
    return _places()[1]


@lru_cache(maxsize=1)
def _places():
    options = get_options()
    aliases = _read("place_aliases.json")
    stop = {compact(word) for word in aliases["bare_name_stoplist"]["words"]}
    index: dict[str, dict[tuple, dict]] = defaultdict(dict)
    full_keys: set[str] = set()

    def add(key, place, *, bare=False):
        key = compact(key)
        if len(key) >= 2:
            index[key][(place["kind"], place["label"])] = place
            if not bare:
                full_keys.add(key)

    # Stations: one candidate per display name, keeping every line's station id.
    stations: dict[str, dict] = {}
    for row in options["stations"]:
        entry = stations.setdefault(row["name"], {"row": row, "ids": [], "aliases": set()})
        entry["ids"].append(row["id"])
        entry["aliases"].update(row.get("aliases") or [])
    for name, entry in stations.items():
        row = entry["row"]
        place = _place("station", name, district_code=row.get("district_code"),
                       district_name=row.get("district_name"), station_ids=entry["ids"])
        # 잠실역(송파구청) is also called 잠실역 and 잠실.
        for word in {name, *entry["aliases"]}:
            for form in {word, _PARENTHESIS.sub("", word)}:
                if compact(form) in stop:
                    continue
                add(form, place, bare=not form.endswith("역"))

    # Neighbourhoods: duplicate names across districts get the district in the label.
    name_count: dict[str, int] = defaultdict(int)
    for row in options["neighborhoods"]:
        name_count[row["name"]] += 1
    exact_names = set(name_count)
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in options["neighborhoods"]:
        label = row["name"] if name_count[row["name"]] == 1 else f"{row['name']}({row['district_name']})"
        place = _place("neighborhood", row["name"], label=label, code=row["code"],
                       district_code=row["district_code"], district_name=row["district_name"])
        add(row["name"], place)
        match = _NUMBERED_DONG.match(row["name"])
        if match:
            groups[match.group("stem") + "동"].append(place)
        elif row["name"].endswith("동"):
            # 을지로동 is also called 을지로.
            stem = row["name"][:-1]
            if compact(stem) not in stop:
                add(stem, place, bare=True)
    for key, places in groups.items():
        # A real neighbourhood with the same name wins over the numbered group.
        if key in exact_names:
            continue
        stem = key[:-1]
        for place in places:
            add(key, place)
            if compact(stem) not in stop:
                add(stem, place, bare=True)

    # Districts: full name and the stem without 구 (강남구 -> 강남).
    for row in options["districts"]:
        place = _place("district", row["name"], code=row["code"], district_code=row["code"], district_name=row["name"])
        add(row["name"], place)
        stem = row["name"][:-1] if row["name"].endswith("구") else row["name"]
        if compact(stem) not in stop:
            add(stem, place, bare=True)

    # Colloquial aliases resolve to the official places above.
    by_kind_name: dict[tuple, list[dict]] = defaultdict(list)
    for places in index.values():
        for place in places.values():
            by_kind_name[(place["kind"], place["name"], place["district_name"])].append(place)
    for alias, targets in aliases["aliases"].items():
        for target in targets:
            found = [p for (kind, name, district), ps in by_kind_name.items() for p in ps
                     if kind == target["kind"] and name == target["name"]
                     and (target.get("district_name") is None or district == target["district_name"])]
            if not found:
                raise ValueError(f"place alias {alias} points to an unknown place: {target}")
            for place in found:
                add(alias, place)

    places = {key: list(found.values()) for key, found in index.items()}
    return places, frozenset(set(places) - full_keys)


@lru_cache(maxsize=1)
def industry_index() -> dict[str, list[dict]]:
    options = get_options()
    by_code = {row["code"]: row for row in options["industries"]}
    index: dict[str, dict[str, dict]] = defaultdict(dict)

    def add(key, row):
        key = compact(key)
        if len(key) >= 2:
            index[key][row["code"]] = {"code": row["code"], "name": row["name"]}

    data = _read("industry_aliases.json")
    ambiguous = {compact(word) for word in data.get("ambiguous_official_names", {}).get("words", [])}
    for row in options["industries"]:
        for form in (row["name"], row["name"].replace("-", "")):
            if compact(form) not in ambiguous:
                add(form, row)
    for code, words in data["aliases"].items():
        if code not in by_code:
            raise ValueError(f"industry alias points to an unknown code: {code}")
        for word in words:
            add(word, by_code[code])
    return {key: list(rows.values()) for key, rows in index.items()}


def user_words() -> list[str]:
    """Proper nouns to register with the morphological analyser."""
    words = {key for key in place_index()} | {key for key in industry_index()}
    return sorted(word for word in words if len(word) >= 2 and re.fullmatch(r"[가-힣0-9]+", word))


def similar_industries(text: str, *, limit: int = 4, threshold: float = 0.4) -> list[dict]:
    """Official industries whose names or aliases look like ``text`` ('중식점' -> 중식음식점).

    Character-bigram Dice similarity on the compact form. Used only when a
    named industry is not in the dictionary, so the user is offered real
    industries instead of the saved one being used silently.
    """
    def grams(value: str) -> set[str]:
        return {value[i:i + 2] for i in range(len(value) - 1)} or {value}

    target = grams(compact(text))
    best: dict[str, tuple[float, dict]] = {}
    for key, rows in industry_index().items():
        other = grams(key)
        score = 2 * len(target & other) / (len(target) + len(other))
        if score < threshold:
            continue
        for row in rows.values() if isinstance(rows, dict) else rows:
            if score > best.get(row["code"], (0.0, None))[0]:
                best[row["code"]] = (score, row)
    ranked = sorted(best.values(), key=lambda item: (-item[0], item[1]["code"]))
    if not ranked:
        return []
    # Keep only near-ties of the best match: '중식점' should not also offer 일식·양식.
    floor = max(threshold, ranked[0][0] - 0.15)
    return [row for score, row in ranked[:limit] if score >= floor]
