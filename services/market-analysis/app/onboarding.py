"""Three-field onboarding with session-owned profiles and address candidates.

This module never calls a language model. A selected input profile is not proof
that statistics or a particular market boundary exist for that location.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import ROOT
from app.cultural_events import DISTRICT_PATTERN, CulturalEventsService
from app.data_sync import DataSyncBusy, DataSyncService
from app.intake_location import declared_region, resolve_location, _candidate as parse_geocode_candidate
from app.naver_clients import NaverApiError
from app.onboarding_catalog import SEOUL_DISTRICTS, get_options

COOKIE_NAME = "market_onboarding_session"
SEARCH_TTL = 600
SESSION_TTL = 30 * 86400
ANALYSIS_UNAVAILABLE = "상권 자료를 불러오지 못했습니다. 잠시 후 다시 확인해 주세요."
CATALOG_ERRORS = (OSError, ValueError, KeyError, TypeError, ImportError)


def _database_path(path=None):
    configured = os.getenv("ONBOARDING_DB_PATH", "").strip() if path is None else ""
    if configured and not Path(configured).is_absolute():
        raise ValueError("ONBOARDING_DB_PATH must be an absolute database path")
    return str(path if path is not None else configured or ROOT / "data" / "onboarding.sqlite3")


def _writable_dir():
    """서비스 계정이 쓸 수 있는 폴더: 설정한 사용자 DB가 있는 곳. 공식 자료 폴더가 아니다."""
    target = _database_path()
    return None if target == ":memory:" else Path(target).parent


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LocationSearch(InputModel):
    query: str = Field(min_length=2, max_length=200)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value):
        if any(ord(c) < 32 for c in value) or not value.strip():
            raise ValueError("주소를 한 줄로 입력해 주세요.")
        if re.search(r"근처|맞은편|주변|인근|부근|일대", value):
            raise ValueError("주소 검색에는 도로명과 건물 번호를 입력해 주세요. 주변 지역은 역 근처 또는 동네·지역으로 선택할 수 있어요.")
        return " ".join(value.split())


class ProfileLocation(InputModel):
    kind: Literal["address", "station", "area"]
    station_id: str | None = Field(default=None, min_length=1, max_length=160)
    station_line_code: str | None = Field(default=None, min_length=1, max_length=40)
    neighborhood_code: str | None = Field(default=None, pattern=r"^\d{8}$")
    search_id: str | None = Field(default=None, min_length=1, max_length=100)
    candidate_id: str | None = Field(default=None, min_length=1, max_length=100)
    text: str | None = Field(default=None, min_length=2, max_length=160)
    district_code: str | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def coherent(self):
        if self.kind == "address":
            if not self.search_id or not self.candidate_id or self.text is not None or self.district_code is not None or self.station_id is not None or self.station_line_code is not None or self.neighborhood_code is not None:
                raise ValueError("주소 검색 결과에서 의도한 후보를 선택해 주세요.")
        elif self.kind == "station":
            if not self.station_id or any(value is not None for value in (self.search_id, self.candidate_id, self.text, self.district_code, self.neighborhood_code)):
                raise ValueError("역 이름을 검색한 뒤 목록에서 역을 선택해 주세요.")
        else:
            if not self.district_code or self.station_id is not None or self.station_line_code is not None or (self.neighborhood_code is None and (not self.text or not self.text.strip())):
                raise ValueError("서울 자치구와 동네 이름을 입력해 주세요.")
            if (self.search_id is None) != (self.candidate_id is None):
                raise ValueError("동네 검색 결과를 다시 선택해 주세요.")
            if self.text is not None:
                if not self.text.strip() or any(ord(c) < 32 for c in self.text):
                    raise ValueError("위치는 한 줄로 입력해 주세요.")
                self.text = " ".join(self.text.split())
        return self


class ProfileInput(InputModel):
    location: ProfileLocation | None = None
    industry_code: str = Field(min_length=1, max_length=30)
    business_status: Literal["operating", "planning", "exploring"]
    expected_revision: int | None = Field(default=None, ge=0)


class AnalysisSelectionInput(InputModel):
    area_code: str = Field(pattern=r"^[0-9]{7}$")
    period: str = Field(pattern=r"^[0-9]{4}[1-4]$")
    expected_revision: int = Field(ge=0)
    expected_catalog_version: str = Field(min_length=1, max_length=160)


class OnboardingStore:
    """Small SQLite store; opaque browser tokens are stored as hashes only."""

    def __init__(self, path=None, *, clock=time.time):
        target = _database_path(path)
        if target != ":memory:":
            Path(target).parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(target, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        with self.connection:
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS onboarding_sessions (
                    owner TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0,
                    profile TEXT, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS onboarding_searches (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, created REAL NOT NULL,
                    candidates TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS onboarding_analysis_selections (
                    owner TEXT PRIMARY KEY, selection TEXT NOT NULL
                );
            """)

    def close(self):
        with self.lock:
            self.connection.close()

    def session(self, token):
        valid = isinstance(token, str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
        token = token if valid else secrets.token_urlsafe(32)
        owner = hashlib.sha256(token.encode()).hexdigest()
        with self.lock, self.connection:
            now = self.clock()
            self.connection.execute("DELETE FROM onboarding_searches WHERE created < ?", (now - SEARCH_TTL,))
            self.connection.execute("DELETE FROM onboarding_sessions WHERE updated < ?", (now - SESSION_TTL,))
            self.connection.execute("DELETE FROM onboarding_analysis_selections WHERE owner NOT IN (SELECT owner FROM onboarding_sessions)")
            self.connection.execute("INSERT OR IGNORE INTO onboarding_sessions(owner,updated) VALUES (?,?)", (owner, now))
            self.connection.execute("UPDATE onboarding_sessions SET updated=? WHERE owner=?", (now, owner))
        return owner, token

    def profile(self, owner):
        with self.lock:
            row = self.connection.execute("SELECT revision,profile FROM onboarding_sessions WHERE owner=?", (owner,)).fetchone()
            return {"revision": row["revision"], "profile": json.loads(row["profile"]) if row["profile"] else None}

    def analysis_selection(self, owner):
        with self.lock:
            row = self.connection.execute("SELECT selection FROM onboarding_analysis_selections WHERE owner=?", (owner,)).fetchone()
            if row is None:
                return None
            try:
                value = json.loads(row["selection"])
            except (ValueError, TypeError):
                return {"status": "stale"}
            return value if isinstance(value, dict) else {"status": "stale"}

    def analysis_state(self, owner):
        with self.lock:
            return {**self.profile(owner), "analysis_selection": self.analysis_selection(owner)}

    def put_search(self, owner, candidates):
        search_id = secrets.token_urlsafe(24)
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO onboarding_searches VALUES (?,?,?,?)",
                                    (search_id, owner, self.clock(), json.dumps(candidates, ensure_ascii=False)))
            self.connection.execute("""DELETE FROM onboarding_searches WHERE owner=? AND id NOT IN
                (SELECT id FROM onboarding_searches WHERE owner=? ORDER BY created DESC,rowid DESC LIMIT 8)""", (owner, owner))
        return search_id

    def candidate(self, owner, search_id, candidate_id):
        with self.lock:
            row = self.connection.execute("SELECT candidates,created FROM onboarding_searches WHERE id=? AND owner=?",
                                          (search_id, owner)).fetchone()
            if not row or self.clock() - row["created"] >= SEARCH_TTL:
                raise HTTPException(422, "주소 검색 결과가 만료됐거나 현재 세션의 결과가 아닙니다. 다시 검색해 주세요.")
            candidate = next((c for c in json.loads(row["candidates"]) if c["id"] == candidate_id), None)
            if candidate is None:
                raise HTTPException(422, "주소 검색 후보를 확인할 수 없습니다. 다시 선택해 주세요.")
            return candidate

    def save(self, owner, body, build_location):
        with self.lock, self.connection:
            current = self.profile(owner)
            if body.expected_revision != current["revision"] and not (body.expected_revision is None and current["revision"] == 0):
                raise HTTPException(409, "다른 화면에서 정보가 변경됐습니다. 최신 정보를 불러온 뒤 다시 저장해 주세요.")
            if body.location is None:
                if not current["profile"]:
                    raise HTTPException(422, "분석할 위치를 입력해 주세요.")
                location = deepcopy(current["profile"]["location"])
            else:
                location = build_location(owner, body.location)
            options = get_options()
            industry = next((i for i in options["industries"] if i["code"] == body.industry_code), None)
            if industry is None:
                raise HTTPException(422, "목록에서 업종을 선택해 주세요.")
            status = next(s for s in options["business_statuses"] if s["code"] == body.business_status)
            revision = current["revision"] + 1
            profile = {"revision": revision, "location": location, "industry": industry,
                       "business_status": body.business_status, "business_status_label": status["label"],
                       "ready_for_analysis": False, "source": "user_confirmed_onboarding",
                       "updated_at": self.clock()}
            previous = current["profile"]
            if previous is None or previous["location"] != location or previous["industry"]["code"] != industry["code"]:
                self.connection.execute("DELETE FROM onboarding_analysis_selections WHERE owner=?", (owner,))
            self.connection.execute("UPDATE onboarding_sessions SET revision=?,profile=?,updated=? WHERE owner=?",
                                    (revision, json.dumps(profile, ensure_ascii=False), self.clock(), owner))
            return profile

    def delete(self, owner, expected_revision=None):
        with self.lock, self.connection:
            current = self.profile(owner)
            if expected_revision is not None and expected_revision != current["revision"]:
                raise HTTPException(409, "다른 화면에서 정보가 변경됐습니다. 최신 정보를 확인해 주세요.")
            revision = current["revision"] + 1
            self.connection.execute("UPDATE onboarding_sessions SET revision=?,profile=NULL,updated=? WHERE owner=?", (revision, self.clock(), owner))
            self.connection.execute("DELETE FROM onboarding_searches WHERE owner=?", (owner,))
            self.connection.execute("DELETE FROM onboarding_analysis_selections WHERE owner=?", (owner,))
            return {"profile": None, "revision": revision}

    def save_analysis(self, owner, body, build_selection):
        with self.lock, self.connection:
            current = self.profile(owner)
            if body.expected_revision != current["revision"]:
                raise HTTPException(409, "기본 정보나 분석 조건이 변경됐습니다. 최신 정보를 불러온 뒤 다시 선택해 주세요.")
            if current["profile"] is None:
                raise HTTPException(409, "먼저 위치·업종·운영 상태를 저장해 주세요.")
            selection = build_selection(current["profile"], body)
            revision = current["revision"] + 1
            selection.update(selection_revision=revision, selected_at=self.clock(), ready_for_analysis=False,
                             analysis_setup_complete=True, conditions_confirmed=True, analysis_stage="configuration_only")
            profile = deepcopy(current["profile"])
            profile.update(revision=revision, updated_at=self.clock(), ready_for_analysis=False)
            self.connection.execute("INSERT OR REPLACE INTO onboarding_analysis_selections VALUES (?,?)",
                                    (owner, json.dumps(selection, ensure_ascii=False)))
            self.connection.execute("UPDATE onboarding_sessions SET revision=?,profile=?,updated=? WHERE owner=?",
                                    (revision, json.dumps(profile, ensure_ascii=False), self.clock(), owner))
            return {"revision": revision, "profile": profile, "analysis_selection": selection}

    def delete_analysis(self, owner, expected_revision):
        with self.lock, self.connection:
            current = self.profile(owner)
            if expected_revision != current["revision"]:
                raise HTTPException(409, "기본 정보나 분석 조건이 변경됐습니다. 최신 정보를 확인해 주세요.")
            revision = current["revision"] + 1
            profile = deepcopy(current["profile"])
            if profile is not None:
                profile.update(revision=revision, updated_at=self.clock(), ready_for_analysis=False)
            self.connection.execute("DELETE FROM onboarding_analysis_selections WHERE owner=?", (owner,))
            self.connection.execute("UPDATE onboarding_sessions SET revision=?,profile=?,updated=? WHERE owner=?",
                                    (revision, json.dumps(profile, ensure_ascii=False) if profile is not None else None,
                                     self.clock(), owner))
            return {"revision": revision, "profile": profile, "analysis_selection": None}


def create_onboarding_router(store: OnboardingStore, *, cookie_secure=False) -> APIRouter:
    router = APIRouter(prefix="/api/onboarding")
    search_slot = threading.BoundedSemaphore(2)
    # 시험은 app.state.data_sync / app.state.cultural_events 로 가짜 서비스를 넣는다.
    default_data_sync = DataSyncService(state_dir=_writable_dir)
    default_cultural_events = CulturalEventsService()
    district_names = frozenset(d["name"] for d in SEOUL_DISTRICTS)

    def data_sync_service(request):
        return getattr(request.app.state, "data_sync", None) or default_data_sync

    def cultural_events_service(request):
        return getattr(request.app.state, "cultural_events", None) or default_cultural_events

    def owned(request):
        return store.session(request.cookies.get(COOKIE_NAME))

    def response(data, token):
        result = JSONResponse(data)
        result.set_cookie(COOKIE_NAME, token, max_age=SESSION_TTL, httponly=True, samesite="strict", secure=cookie_secure, path="/")
        result.headers["Cache-Control"] = "no-store"
        return result

    def analysis_state(owner):
        state = store.analysis_state(owner)
        selection = state["analysis_selection"]
        confirmed = False
        if selection is not None and state["profile"] is not None:
            profile = state["profile"]
            required = ("area_code", "period", "catalog_version", "industry_code")
            intact = all(isinstance(selection.get(key), str) and selection[key] for key in required)
            intact = intact and selection.get("industry_code") == profile["industry"]["code"]
            if not intact:
                selection.update(status="stale", message="저장된 분석 조건을 현재 자료에서 확인하지 못했습니다. 상권과 기간을 다시 선택해 주세요.",
                                 analysis_setup_complete=False, conditions_confirmed=False, ready_for_analysis=False)
            else:
                try:
                    from app.onboarding_analysis_catalog import get_analysis_options, validate_analysis_selection

                    get_analysis_options(profile["location"], profile["industry"]["code"])
                except CATALOG_ERRORS:
                    selection.update(status="unavailable", message=ANALYSIS_UNAVAILABLE,
                                     analysis_setup_complete=False, conditions_confirmed=False, ready_for_analysis=False)
                else:
                    try:
                        current = validate_analysis_selection(profile["location"], profile["industry"]["code"],
                            selection["area_code"], selection["period"], selection["catalog_version"])
                    except ValueError:
                        selection.update(status="stale", message="저장된 분석 조건을 현재 자료에서 확인하지 못했습니다. 상권과 기간을 다시 선택해 주세요.",
                                         analysis_setup_complete=False, conditions_confirmed=False, ready_for_analysis=False)
                    except (OSError, KeyError, TypeError, ImportError):
                        selection.update(status="unavailable", message=ANALYSIS_UNAVAILABLE,
                                         analysis_setup_complete=False, conditions_confirmed=False, ready_for_analysis=False)
                    else:
                        selection.update(current)
                        selection.update(status="selected", analysis_setup_complete=True, conditions_confirmed=True,
                                         ready_for_analysis=False, analysis_stage="configuration_only")
                        confirmed = True
        state.update(analysis_setup_complete=confirmed, conditions_confirmed=confirmed, ready_for_analysis=False)
        return state

    def build_analysis_selection(profile, body):
        location, industry_code = profile["location"], profile["industry"]["code"]
        try:
            from app.onboarding_analysis_catalog import get_analysis_options, validate_analysis_selection

            options = get_analysis_options(location, industry_code)
        except CATALOG_ERRORS as error:
            raise HTTPException(503, ANALYSIS_UNAVAILABLE) from error
        if body.expected_catalog_version != options["catalog_version"]:
            raise HTTPException(409, "상권 후보 자료가 변경됐습니다. 목록을 다시 불러온 뒤 선택해 주세요.")
        try:
            selected = validate_analysis_selection(location, industry_code, body.area_code, body.period,
                                                   body.expected_catalog_version)
        except ValueError as error:
            raise HTTPException(422, "선택한 상권·업종·기간을 현재 후보 자료에서 확인할 수 없습니다. 목록을 다시 확인해 주세요.") from error
        except (OSError, KeyError, TypeError, ImportError) as error:
            raise HTTPException(503, ANALYSIS_UNAVAILABLE) from error
        return {**selected, "status": "selected"}

    def district_from_label(text):
        return next((d for d in get_options()["districts"] if re.search(r"(?:^|\s)" + re.escape(d["name"]) + r"(?:\s|$)", text)), None)

    def area_selection(location):
        district = next((d for d in get_options()["districts"] if d["code"] == location.district_code), None)
        if district is None:
            raise HTTPException(422, "서울 자치구를 목록에서 선택해 주세요.")
        if location.neighborhood_code is not None:
            from app.onboarding_neighborhoods import get_neighborhood

            neighborhood = get_neighborhood(location.neighborhood_code)
            if neighborhood is None or neighborhood["district_code"] != district["code"]:
                raise HTTPException(422, "선택한 자치구의 동네를 목록에서 다시 선택해 주세요.")
            if location.text is not None and location.text != neighborhood["name"]:
                raise HTTPException(422, "동네 코드와 이름이 다릅니다. 목록에서 다시 선택해 주세요.")
            # Names are taken from the official catalogue, not a browser label.
            location.text = neighborhood["name"]
            return district, neighborhood
        # Preserve the older text-only protocol and saved profiles as declared
        # locations. Never promote them to a verified catalogue selection.
        region = declared_region(location.text)
        if region and region != "seoul":
            raise HTTPException(422, "입력한 지역은 서울 밖입니다. 서울의 동네를 입력해 주세요.")
        named_district = district_from_label(location.text)
        if named_district and named_district["code"] != district["code"]:
            raise HTTPException(422, "입력한 자치구와 선택한 자치구가 다릅니다. 위치를 확인해 주세요.")
        return district, None

    def public_candidate(candidate):
        return {key: value for key, value in candidate.items() if key in
                ("id", "label", "road_address", "jibun_address", "in_seoul", "latitude", "longitude")}

    def build_location(owner, location):
        if location.kind == "station":
            from app.onboarding_stations import get_station
            from app.onboarding_station_lines import get_station_line, get_station_line_codes

            station = get_station(location.station_id)
            if station is None:
                raise HTTPException(422, "역 이름을 검색한 뒤 서울에 있는 역을 목록에서 선택해 주세요.")
            line = None
            if location.station_line_code is not None:
                line = get_station_line(location.station_line_code)
                if line is None or location.station_line_code not in get_station_line_codes(station["id"]):
                    raise HTTPException(422, "선택한 노선의 역을 목록에서 다시 선택해 주세요.")
            saved = {"kind": "station", "station_id": station["id"],
                    **{key: value for key, value in station.items() if key in
                       ("name", "lines", "district_code", "district_name", "road_address", "latitude", "longitude",
                        "coordinate_status", "source_data_date")},
                    "source": "kric_station_catalog",
                    "label": station["name"], "verification": "verified_station", "analysis_area_confirmed": False}
            if line is not None:
                saved.update(station_line_code=line["code"], station_line_name=line["name"])
            return saved
        if location.kind == "address":
            candidate = store.candidate(owner, location.search_id, location.candidate_id)
            if candidate.get("purpose") != "address":
                raise HTTPException(422, "가게 주소 검색 결과에서 주소를 다시 선택해 주세요.")
            if not candidate["in_seoul"]:
                raise HTTPException(422, "서울특별시 안의 주소만 저장할 수 있습니다.")
            district = district_from_label(candidate["road_address"] or candidate["jibun_address"])
            if district is None:
                raise HTTPException(422, "주소의 서울 자치구를 확인하지 못했습니다. 다른 주소 후보를 확인해 주세요.")
            return {"kind": "address", "label": candidate["label"], "road_address": candidate["road_address"],
                    "jibun_address": candidate["jibun_address"], "longitude": candidate["longitude"], "latitude": candidate["latitude"],
                    "district_code": district["code"], "district_name": district["name"], "verification": "verified_address",
                    "analysis_area_confirmed": False}
        district, neighborhood = area_selection(location)
        saved = {"kind": "area", "label": location.text, "district_code": district["code"],
                 "district_name": district["name"], "verification": "user_declared", "analysis_area_confirmed": False}
        if neighborhood is not None:
            from app.onboarding_neighborhoods import get_neighborhood_source

            source = get_neighborhood_source()
            saved.update(neighborhood_code=neighborhood["code"], neighborhood_name=neighborhood["name"],
                         neighborhood_type=source["type"], neighborhood_source_date=source["source_date"],
                         verification="selected_neighborhood")
        if location.search_id:
            candidate = store.candidate(owner, location.search_id, location.candidate_id)
            if (candidate.get("purpose") != "area" or candidate.get("area_text") != location.text
                    or candidate.get("district_code") != district["code"]
                    or candidate.get("neighborhood_code") != location.neighborhood_code or not candidate["in_seoul"]):
                raise HTTPException(422, "동네 입력이 검색한 내용과 다릅니다. 지도에서 다시 확인해 주세요.")
            saved["reference_point"] = {key: candidate[key] for key in ("label", "latitude", "longitude")}
            saved["reference_point"]["source"] = "naver_geocoding"
            saved["verification"] = "geocoded_area_reference"
        return saved

    @router.get("/options")
    def options():
        return get_options()

    @router.get("/map-config")
    def map_config():
        # Dynamic Map's browser application ID is public. Server secrets and
        # other environment values must never be serialized here.
        client_id = os.getenv("NAVER_MAPS_CLIENT_ID", "").strip()
        return JSONResponse({"client_id": client_id, "configured": bool(client_id)},
                            headers={"Cache-Control": "no-store"})

    @router.get("/profile")
    def profile(request: Request):
        owner, token = owned(request)
        return response(store.profile(owner), token)

    @router.post("/locations/search")
    def search(body: LocationSearch, request: Request):
        owner, token = owned(request)
        if not search_slot.acquire(blocking=False):
            raise HTTPException(429, "주소 조회 중입니다. 잠시 후 다시 시도해 주세요.", headers={"Retry-After": "3"})
        try:
            result = resolve_location({"kind": "address", "text": body.query, "relation": "exact"}, request.app.state.maps_client)
        finally:
            search_slot.release()
        candidates = []
        # Only a validated matching candidate/choice may be offered for saving.
        if result["status"] in ("address_candidate", "choose_candidate", "outside_seoul"):
            for row in result["candidates"]:
                candidates.append({**row, "id": secrets.token_urlsafe(16), "purpose": "address",
                                   "label": row["road_address"] or row["jibun_address"]})
        search_id = store.put_search(owner, candidates) if candidates else None
        return response({"status": result["status"], "message": result.get("question"), "search_id": search_id,
                         "candidates": [public_candidate(c) for c in candidates]}, token)

    @router.post("/locations/area-preview")
    def area_preview(body: ProfileLocation, request: Request):
        if body.kind != "area" or body.search_id is not None:
            raise HTTPException(422, "자치구와 동네 이름으로 검색해 주세요.")
        district, _neighborhood = area_selection(body)
        owner, token = owned(request)
        # The geocoder may only identify a reference point matching the entered
        # neighbourhood. It cannot silently discard words like 'north side'.
        term = re.sub(r"^서울(?:특별시|시)?\s+", "", body.text)
        term = re.sub(r"^" + re.escape(district["name"]) + r"\s+", "", term).strip()
        if len(term) < 2:
            raise HTTPException(422, "동네 이름을 입력해 주세요. 예: 연남동.")
        if not search_slot.acquire(blocking=False):
            raise HTTPException(429, "위치 조회 중입니다. 잠시 후 다시 시도해 주세요.")
        try:
            rows = request.app.state.maps_client.geocode(f"서울특별시 {district['name']} {term}")
            if not isinstance(rows, list) or len(rows) > 10:
                raise ValueError("Invalid geocoding response")
            parsed = [parse_geocode_candidate(row) for row in rows]
        except (NaverApiError, ValueError, OSError):
            return response({"status": "lookup_unavailable", "message": "동네 위치를 조회하지 못했어요. 잠시 후 다시 시도해 주세요.",
                             "search_id": None, "candidates": []}, token)
        finally:
            search_slot.release()
        candidates, seen = [], set()
        for candidate, region in parsed:
            label = candidate["road_address"] or candidate["jibun_address"]
            returned_district = district_from_label(label)
            addresses = (candidate["road_address"], candidate["jibun_address"])
            if (region != "seoul" or returned_district != district
                    or not any(term.replace(" ", "") in address.replace(" ", "") for address in addresses)):
                continue
            key = (label, candidate["latitude"], candidate["longitude"])
            if key in seen:
                continue
            seen.add(key)
            candidates.append({**candidate, "id": secrets.token_urlsafe(16), "label": label, "purpose": "area",
                               "area_text": body.text, "district_code": district["code"],
                               "neighborhood_code": body.neighborhood_code})
        search_id = store.put_search(owner, candidates) if candidates else None
        return response({"status": "area_reference_candidates" if candidates else "not_found",
                         "message": "지도에 표시할 동네 참고 위치를 선택해 주세요. 실제 분석 경계는 다음 단계에서 정해요." if candidates
                         else "동네 위치를 찾지 못했어요. 동 이름을 확인하거나 주소·역으로 선택해 주세요.",
                         "search_id": search_id, "candidates": [public_candidate(c) for c in candidates]}, token)

    @router.post("/profile")
    def save(body: ProfileInput, request: Request):
        owner, token = owned(request)
        saved = store.save(owner, body, build_location)
        message = "기본 정보를 저장했습니다. 분석할 상권과 자료 기간을 선택해 주세요."
        if saved["location"]["verification"] == "user_declared":
            message += " 역·동네는 입력하신 관심 위치이며 분석할 정확한 범위는 추가 확인이 필요합니다."
        return response({**analysis_state(owner), "message": message}, token)

    @router.delete("/profile")
    def delete(request: Request, expected_revision: int | None = None):
        owner, token = owned(request)
        return response(store.delete(owner, expected_revision), token)

    @router.get("/analysis-options")
    def analysis_options(request: Request):
        owner, token = owned(request)
        state = analysis_state(owner)
        if state["profile"] is None:
            raise HTTPException(409, "먼저 위치·업종·운영 상태를 저장해 주세요.")
        profile = state["profile"]
        try:
            from app.onboarding_analysis_catalog import get_analysis_options

            options = get_analysis_options(profile["location"], profile["industry"]["code"])
        except CATALOG_ERRORS as error:
            raise HTTPException(503, ANALYSIS_UNAVAILABLE) from error
        return response({**options, **state}, token)

    @router.get("/analysis-selection")
    def get_analysis_selection(request: Request):
        owner, token = owned(request)
        return response(analysis_state(owner), token)

    @router.post("/analysis-selection")
    def save_analysis_selection(body: AnalysisSelectionInput, request: Request):
        owner, token = owned(request)
        state = store.save_analysis(owner, body, build_analysis_selection)
        return response({**state, "analysis_setup_complete": True, "conditions_confirmed": True,
                         "ready_for_analysis": False,
                         "message": "분석할 상권과 기간을 저장했습니다. 지표별 자료 제공 여부와 경계 기준일을 확인해 주세요."}, token)

    @router.delete("/analysis-selection")
    def delete_analysis_selection(request: Request, expected_revision: int):
        owner, token = owned(request)
        state = store.delete_analysis(owner, expected_revision)
        return response({**state, "analysis_setup_complete": False, "conditions_confirmed": False,
                         "ready_for_analysis": False, "message": "분석 조건을 해제했습니다. 기본 정보는 유지했습니다."}, token)

    @router.get("/sales")
    def sales(request: Request, expected_revision: int | None = Query(default=None, ge=0)):
        if (set(request.query_params) - {"expected_revision"}
                or len(request.query_params.getlist("expected_revision")) > 1):
            raise HTTPException(422, "매출 조회는 저장한 분석 조건을 사용합니다. 다른 상권·업종·기간을 직접 전달할 수 없습니다.")
        owner, token = owned(request)
        state = analysis_state(owner)
        if expected_revision is not None and expected_revision != state["revision"]:
            raise HTTPException(409, "분석 조건이 변경됐습니다. 최신 조건을 불러온 뒤 다시 조회해 주세요.")
        selected = state["analysis_selection"]
        if selected is not None and selected.get("status") == "unavailable":
            raise HTTPException(503, "매출 자료를 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.")
        if not state["conditions_confirmed"]:
            raise HTTPException(409, "분석할 상권과 기간을 먼저 선택하거나 현재 자료로 다시 확인해 주세요.")
        try:
            from app.onboarding_sales import build_sales_analysis

            result = build_sales_analysis(selected, state["profile"])
        except CATALOG_ERRORS as error:
            raise HTTPException(503, "매출 자료를 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.") from error
        if store.analysis_state(owner)["revision"] != state["revision"]:
            raise HTTPException(409, "조회 중 분석 조건이 변경됐습니다. 최신 조건을 불러온 뒤 다시 조회해 주세요.")
        return response({**result, "revision": state["revision"], "feature": "sales", "analysis_stage": "sales_result"}, token)

    @router.get("/stores")
    def stores(request: Request, expected_revision: int | None = Query(default=None, ge=0)):
        if (set(request.query_params) - {"expected_revision"}
                or len(request.query_params.getlist("expected_revision")) > 1):
            raise HTTPException(422, "점포 조회는 저장한 분석 조건을 사용합니다. 다른 상권·업종·기간을 직접 전달할 수 없습니다.")
        owner, token = owned(request)
        state = analysis_state(owner)
        if expected_revision is not None and expected_revision != state["revision"]:
            raise HTTPException(409, "분석 조건이 변경됐습니다. 최신 조건을 불러온 뒤 다시 조회해 주세요.")
        selected = state["analysis_selection"]
        if selected is not None and selected.get("status") == "unavailable":
            raise HTTPException(503, "점포 자료를 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.")
        if not state["conditions_confirmed"]:
            raise HTTPException(409, "분석할 상권과 기간을 먼저 선택하거나 현재 자료로 다시 확인해 주세요.")
        try:
            from app.onboarding_stores import build_stores_analysis

            result = build_stores_analysis(selected, state["profile"])
        except CATALOG_ERRORS as error:
            raise HTTPException(503, "점포 자료를 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.") from error
        if store.analysis_state(owner)["revision"] != state["revision"]:
            raise HTTPException(409, "조회 중 분석 조건이 변경됐습니다. 최신 조건을 불러온 뒤 다시 조회해 주세요.")
        return response({**result, "revision": state["revision"], "feature": "stores", "analysis_stage": "stores_result"}, token)

    @router.get("/population")
    def population(request: Request, expected_revision: int | None = Query(default=None, ge=0)):
        if (set(request.query_params) - {"expected_revision"}
                or len(request.query_params.getlist("expected_revision")) > 1):
            raise HTTPException(422, "유동인구 조회는 저장한 분석 조건을 사용합니다. 상권·업종·기간을 직접 전달할 수 없습니다.")
        owner, token = owned(request)
        state = analysis_state(owner)
        if expected_revision is not None and expected_revision != state["revision"]:
            raise HTTPException(409, "분석 조건이 변경됐습니다. 최신 조건을 불러온 뒤 다시 조회해 주세요.")
        selected = state["analysis_selection"]
        if selected is not None and selected.get("status") == "unavailable":
            raise HTTPException(503, "유동인구 자료를 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.")
        if not state["conditions_confirmed"]:
            raise HTTPException(409, "분석할 상권과 기간을 먼저 선택하거나 현재 자료로 다시 확인해 주세요.")
        try:
            from app.onboarding_population import build_population_analysis

            result = build_population_analysis(selected, state["profile"])
        except CATALOG_ERRORS as error:
            raise HTTPException(503, "유동인구 자료를 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.") from error
        if store.analysis_state(owner)["revision"] != state["revision"]:
            raise HTTPException(409, "조회 중 분석 조건이 변경됐습니다. 최신 조건을 불러온 뒤 다시 조회해 주세요.")
        return response({**result, "revision": state["revision"], "feature": "population", "analysis_stage": "population_result"}, token)

    def comparison_context(request, expected_revision, allowed_fields,
                           input_message="비교는 저장한 기준 상권·업종·기간을 사용합니다. 비교할 상권만 선택해 주세요."):
        if (set(request.query_params) - allowed_fields
                or any(len(request.query_params.getlist(key)) > 1 for key in request.query_params)):
            raise HTTPException(422, input_message)
        owner, token = owned(request)
        state = analysis_state(owner)
        if expected_revision is not None and expected_revision != state["revision"]:
            raise HTTPException(409, "분석 조건이 변경됐습니다. 최신 조건을 불러온 뒤 다시 조회해 주세요.")
        selected = state["analysis_selection"]
        if selected is not None and selected.get("status") == "unavailable":
            raise HTTPException(503, "비교 자료를 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.")
        if not state["conditions_confirmed"]:
            raise HTTPException(409, "기준 상권과 기간을 먼저 선택하거나 현재 자료로 다시 확인해 주세요.")
        return owner, token, state

    @router.get("/comparison-options")
    def comparison_options(request: Request, expected_revision: int | None = Query(default=None, ge=0)):
        owner, token, state = comparison_context(request, expected_revision, {"expected_revision"})
        try:
            from app.onboarding_comparison import get_comparison_options

            result = get_comparison_options(state["analysis_selection"], state["profile"])
        except CATALOG_ERRORS as error:
            raise HTTPException(503, "비교 상권 목록을 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.") from error
        if store.analysis_state(owner)["revision"] != state["revision"]:
            raise HTTPException(409, "조회 중 분석 조건이 변경됐습니다. 최신 조건을 불러온 뒤 다시 조회해 주세요.")
        return response({**result, "revision": state["revision"]}, token)

    @router.get("/comparison")
    def comparison(request: Request, comparison_area_code: str = Query(pattern=r"^[0-9]{7}$"),
                   expected_revision: int | None = Query(default=None, ge=0)):
        owner, token, state = comparison_context(request, expected_revision, {"comparison_area_code", "expected_revision"})
        try:
            from app.onboarding_comparison import build_comparison_analysis, ComparisonInputError

            try:
                result = build_comparison_analysis(state["analysis_selection"], state["profile"], comparison_area_code)
            except ComparisonInputError as error:
                raise HTTPException(422, str(error)) from error
        except CATALOG_ERRORS as error:
            raise HTTPException(503, "비교 자료를 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.") from error
        if store.analysis_state(owner)["revision"] != state["revision"]:
            raise HTTPException(409, "조회 중 분석 조건이 변경됐습니다. 최신 조건을 불러온 뒤 다시 조회해 주세요.")
        return response({**result, "revision": state["revision"], "feature": "comparison", "analysis_stage": "comparison_result"}, token)

    @router.get("/changes")
    def changes(request: Request, comparison: Literal["qoq", "yoy"] = Query(),
                expected_revision: int | None = Query(default=None, ge=0)):
        owner, token, state = comparison_context(request, expected_revision, {"comparison", "expected_revision"},
            "기간 변화는 저장한 상권·업종·분기를 사용합니다. 전분기 또는 전년 동분기만 선택해 주세요.")
        try:
            from app.onboarding_changes import build_changes_analysis

            result = build_changes_analysis(state["analysis_selection"], state["profile"], comparison)
        except CATALOG_ERRORS as error:
            raise HTTPException(503, "기간 변화 자료를 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.") from error
        if store.analysis_state(owner)["revision"] != state["revision"]:
            raise HTTPException(409, "조회 중 분석 조건이 변경됐습니다. 최신 조건을 불러온 뒤 다시 조회해 주세요.")
        return response({**result, "revision": state["revision"], "feature": "changes", "analysis_stage": "changes_result"}, token)

    @router.get("/context")
    def context(request: Request):
        owner, token = owned(request)
        saved = analysis_state(owner)
        if saved["profile"] is None:
            raise HTTPException(409, "먼저 위치·업종·운영 상태를 입력해 주세요.")
        p = saved["profile"]
        selected = saved["analysis_selection"] if saved["conditions_confirmed"] else None
        return response({"profile_revision": p["revision"], "source": p["source"],
                         "location": p["location"], "industry": p["industry"], "business_status": p["business_status"],
                         "analysis_area": {"code": selected["area_code"], "name": selected["area_name"],
                                           "boundary": selected["boundary"]} if selected else None,
                         "data_period": selected["period"] if selected else None,
                         "catalog_version": selected["catalog_version"] if selected else None,
                         "availability": selected["availability"] if selected else None,
                         "analysis_selection": saved["analysis_selection"],
                         "analysis_setup_complete": saved["analysis_setup_complete"],
                         "conditions_confirmed": saved["conditions_confirmed"],
                         "analysis_stage": "configuration_only", "ready_for_analysis": False}, token)

    @router.get("/data-status")
    def data_status(request: Request):
        _owner, token = owned(request)
        return response(data_sync_service(request).status(), token)

    @router.post("/data-sync")
    def data_sync(request: Request):
        # 서울시 최신 발행 분기만 확인한다. 서비스 자료를 바꾸거나 수집하지 않는다.
        _owner, token = owned(request)
        try:
            result = data_sync_service(request).sync()
        except DataSyncBusy as error:
            raise HTTPException(429, "다른 자료 확인이 진행 중이에요. 잠시 후 다시 시도해 주세요.",
                                headers={"Retry-After": "5"}) from error
        return response(result, token)

    @router.get("/cultural-events")
    def cultural_events(request: Request, district: str = Query(default="", max_length=10)):
        if (set(request.query_params) - {"district"}
                or len(request.query_params.getlist("district")) > 1):
            raise HTTPException(422, "문화행사는 서울 자치구 이름 하나로만 조회할 수 있어요.")
        district = district.strip()
        if district and (DISTRICT_PATTERN.fullmatch(district) is None or district not in district_names):
            raise HTTPException(422, "서울 자치구 이름을 확인해 주세요. 예: 동작구")
        _owner, token = owned(request)
        return response(cultural_events_service(request).events(district or None), token)

    return router
