"""Pre-computed B2~B6 results for one confirmed analysis selection.

When the location, industry, market and quarter are confirmed, the assistant
asks for every single-market analysis once and keeps the results. Later
questions about the same selection reuse them, so the model only ever sees the
few fact cards a question needs. The key includes the session owner, the
revision and the catalogue version, so a changed selection never reuses old
numbers.
"""
from __future__ import annotations

from collections import OrderedDict
import threading

from fastapi import HTTPException

from app.assistant.bridge import error_message

ANALYSES = ("sales", "stores", "population", "changes_qoq", "changes_yoy")


def _error(exc: Exception) -> dict:
    status = exc.status_code if isinstance(exc, HTTPException) else None
    return {"status": "error", "http_status": status, "message": error_message(exc)}


def build_snapshot(bridge, state: dict) -> dict:
    revision = state["revision"]
    calls = {
        "sales": lambda: bridge.sales(revision),
        "stores": lambda: bridge.stores(revision),
        "population": lambda: bridge.population(revision),
        "changes_qoq": lambda: bridge.changes("qoq", revision),
        "changes_yoy": lambda: bridge.changes("yoy", revision),
    }
    results = {}
    for name, call in calls.items():
        try:
            results[name] = call()
        except (HTTPException, ValueError, KeyError, OSError) as exc:
            results[name] = _error(exc)
    return {"revision": revision, "catalog_version": state["analysis_selection"].get("catalog_version"),
            "selection": state["analysis_selection"], "profile": state["profile"], "results": results}


def add_comparison(bridge, snapshot: dict, area_code: str) -> dict:
    try:
        result = bridge.comparison(area_code, snapshot["revision"])
    except (HTTPException, ValueError, KeyError, OSError) as exc:
        result = _error(exc)
    snapshot["results"]["comparison"] = result
    snapshot["comparison_area_code"] = area_code
    return snapshot


class SnapshotCache:
    """Small in-process LRU. Public statistics only; no conversation text."""

    def __init__(self, max_entries: int = 64):
        self._entries: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_entries

    @staticmethod
    def key(owner: str, state: dict) -> tuple:
        selection = state.get("analysis_selection") or {}
        return owner, state.get("revision"), selection.get("catalog_version"), selection.get("area_code"), selection.get("period")

    def get(self, key):
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key]
            return None

    def put(self, key, snapshot):
        with self._lock:
            self._entries[key] = snapshot
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)

    def drop_owner(self, owner: str):
        with self._lock:
            for key in [key for key in self._entries if key[0] == owner]:
                del self._entries[key]
