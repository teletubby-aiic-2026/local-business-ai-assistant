"""Independent, bounded-memory reader for retained official source envelopes.

This test helper does not call application readers or builders. It validates
pages and exact all/area overlap before selecting rows. A single cached compact
index is shared by source-oracle tests; row dictionaries are created on demand.
"""
from collections import defaultdict
from collections.abc import Mapping
from decimal import Decimal
from functools import lru_cache
from hashlib import sha256
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/official"
MANIFEST = ROOT / "data/official/onboarding_analysis_catalog.json"
HISTORICAL_PERIODS = ("20252", "20261", "20262")
SERVICES = {"sales": "VwsmTrdarSelngQq", "stores": "VwsmTrdarStorQq", "population": "VwsmTrdarFlpopQq"}
SOURCE_IDS = {"sales": "OA-15572", "stores": "OA-15577", "population": "OA-15568"}
STORE_FIELDS = ("SIMILR_INDUTY_STOR_CO", "STOR_CO", "FRC_STOR_CO", "OPBIZ_STOR_CO", "CLSBIZ_STOR_CO", "OPBIZ_RT", "CLSBIZ_RT")
AGE_KEYS = ("10", "20", "30", "40", "50", "60_ABOVE")
TIME_KEYS = ("00_06", "06_11", "11_14", "14_17", "17_21", "21_24")
DAY_KEYS = ("MON", "TUES", "WED", "THUR", "FRI", "SAT", "SUN")
FIELDS = {
    "stores": STORE_FIELDS,
    "sales": ("THSMON_SELNG_AMT",) + tuple(day + "_SELNG_AMT" for day in DAY_KEYS)
             + tuple("TMZON_" + key + "_SELNG_AMT" for key in TIME_KEYS)
             + tuple("AGRDE_" + key + "_SELNG_AMT" for key in AGE_KEYS),
    "population": ("TOT_FLPOP_CO", "ML_FLPOP_CO", "FML_FLPOP_CO")
             + tuple("TMZON_" + key + "_FLPOP_CO" for key in TIME_KEYS)
             + tuple("AGRDE_" + key + "_FLPOP_CO" for key in AGE_KEYS)
             + tuple(day + "_FLPOP_CO" for day in DAY_KEYS),
}


def source_url(dataset):
    return f"https://data.seoul.go.kr/dataList/{SOURCE_IDS[dataset]}/S/1/datasetView.do"


def numeric(value):
    if isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value():
        return int(value)
    return value


class RowView(Mapping):
    def __init__(self, records, fields, names, industry_names):
        self.records, self.fields = records, fields
        self.names, self.industry_names = names, industry_names

    def __len__(self):
        return len(self.records)

    def __iter__(self):
        return iter(self.records)

    def __getitem__(self, key):
        values, _file_id = self.records[key]
        area, industry, period = key
        row = {"TRDAR_CD": area, "TRDAR_CD_NM": self.names[(area, period)], "STDR_YYQU_CD": period,
               **dict(zip(self.fields, values))}
        if industry is not None:
            row.update(SVC_INDUTY_CD=industry, SVC_INDUTY_CD_NM=self.industry_names[industry])
        return row

    def subset(self, *, periods=None, areas=None):
        allowed_periods, allowed_areas = set(periods) if periods else None, set(areas) if areas else None
        return RowView({key: value for key, value in self.records.items()
                        if (allowed_periods is None or key[2] in allowed_periods)
                        and (allowed_areas is None or key[0] in allowed_areas)}, self.fields, self.names, self.industry_names)


class ProofView(Mapping):
    def __init__(self, rows, files):
        self.rows, self.files = rows, files

    def __len__(self):
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def __getitem__(self, key):
        file = self.files[self.rows[key][1]]
        return file["name"], file["file_sha256"], file["payload_sha256"]


class PopulationPairs(Mapping):
    """Compatibility view for tests naturally keyed by area and quarter."""
    def __init__(self, mapping):
        self.mapping = mapping

    def __len__(self):
        return len(self.mapping)

    def __iter__(self):
        return ((area, period) for area, _industry, period in self.mapping)

    def __getitem__(self, key):
        return self.mapping[(key[0], None, key[1])]


class AvailabilityValues(Mapping):
    """No second 800k-row dictionary for the B1 availability oracle."""
    def __init__(self, oracle):
        self.oracle = oracle

    def __len__(self):
        return sum(len(rows) for rows in self.oracle.rows.values())

    def __iter__(self):
        for dataset, rows in self.oracle.rows.items():
            metric = "floating_population" if dataset == "population" else dataset
            for area, industry, period in rows:
                yield metric, period, area, industry

    def __getitem__(self, key):
        metric, period, area, industry = key
        dataset = "population" if metric == "floating_population" else metric
        value = self.oracle.rows[dataset].records[(area, industry, period)][0][0]
        number = float(value) if value is not None and str(value).strip() else None
        return number if number is not None and math.isfinite(number) and number >= 0 else None


class Oracle:
    def __init__(self, raw_root, manifest_path):
        self.raw_root = Path(raw_root)
        snapshot = json.loads(Path(manifest_path).read_text(encoding="utf-8")) if manifest_path else None
        self.version = snapshot["catalog_version"] if snapshot else None
        self.areas = {row["area_code"]: row for row in snapshot["areas"]} if snapshot else {}
        expected = {Path(entry["path"]).name: entry for entry in snapshot["source"]["files"]
                    if entry["dataset"] in SERVICES} if snapshot else None
        self.files, self.names, self.industry_names = [], {dataset: {} for dataset in SERVICES}, {}
        self.collected, self.periods, self.overlap = set(), {}, {}
        records = {dataset: {} for dataset in SERVICES}
        self.legacy_records = {}
        paths = [path for dataset in SERVICES for path in self.raw_root.glob(dataset + "_*.json")]
        if expected is not None:
            assert {path.name for path in paths} == set(expected), "Source file set differs from manifest"
        groups = defaultdict(list)
        legacy_exact = {}
        # Area-scoped originals first, so full rows need retaining only for the
        # historical overlap set, never for all citywide observations.
        paths.sort(key=lambda path: ("_all_" in path.name, path.name))
        for path in paths:
            data = path.read_bytes()
            digest = sha256(data).hexdigest()
            normal = json.loads(data.decode("utf-8-sig"))
            query, payload = normal["query"], normal["payload"]
            dataset = query["dataset"]
            assert dataset in SERVICES and normal["service"] == SERVICES[dataset]
            payload_digest = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            assert payload_digest == normal["payload_sha256"]
            if expected is not None:
                assert digest == expected[path.name]["file_sha256"]
                assert payload_digest == expected[path.name]["payload_sha256"]
                entry = expected[path.name]
                assert entry["dataset"] == dataset and entry["period"] == query["period"]
                assert entry["area_code"] == query["area_code"] and entry["start"] == query["start"]
            assert normal["sample_only"] is False and normal["source_url"] == source_url(dataset)
            response = payload[SERVICES[dataset]]
            assert response["RESULT"]["CODE"] == "INFO-000"
            period = sys.intern(str(query["period"]))
            scope = sys.intern(str(query["area_code"])) if query["area_code"] is not None else None
            start, count, total = query["start"], query["count"], response["list_total_count"]
            assert all(type(value) is int and value > 0 for value in (start, count, total))
            assert isinstance(response["row"], list) and len(response["row"]) == min(count, total - start + 1) > 0
            if expected is not None:
                assert len(response["row"]) == expected[path.name]["row_count"]
            groups[(dataset, period, scope)].append((start, len(response["row"]), total))
            file_id = len(self.files)
            self.files.append({"name": path.name, "dataset": dataset, "period": period, "area_code": scope,
                               "file_sha256": digest, "payload_sha256": payload_digest, "keys": []})
            exact = json.loads(data.decode("utf-8-sig"), parse_float=Decimal)["payload"][SERVICES[dataset]]["row"]
            seen = set()
            for row in exact:
                area = sys.intern(row["TRDAR_CD"])
                industry = sys.intern(row["SVC_INDUTY_CD"]) if "SVC_INDUTY_CD" in row else None
                assert row["STDR_YYQU_CD"] == period and scope in (None, area)
                assert (dataset == "population") == (industry is None)
                key = (area, industry, period)
                assert key not in seen, "Duplicate identity in source page"
                seen.add(key)
                name_key = (area, period)
                assert self.names[dataset].setdefault(name_key, row["TRDAR_CD_NM"]) == row["TRDAR_CD_NM"]
                if industry:
                    assert self.industry_names.setdefault(industry, row["SVC_INDUTY_CD_NM"]) == row["SVC_INDUTY_CD_NM"]
                compact = tuple(numeric(row.get(field)) for field in FIELDS[dataset])
                previous = records[dataset].get(key)
                if previous is not None:
                    previous_file = self.files[previous[1]]
                    assert dataset == "stores" and scope is None and previous_file["area_code"] is not None, "Duplicate source identity"
                    assert row == legacy_exact[key], "Citywide/legacy source overlap differs"
                    self.overlap[period] = self.overlap.get(period, 0) + 1
                records[dataset][key] = (compact, file_id)
                self.files[file_id]["keys"].append(key)
                if dataset == "stores" and scope is not None:
                    self.legacy_records[key] = (compact, file_id)
                    legacy_exact[key] = row
        for (dataset, period, scope), pages in groups.items():
            totals = {page[2] for page in pages}
            assert len(totals) == 1, "Page total changed"
            following = 1
            for start, length, total in sorted(pages):
                assert start == following, "Missing or overlapping page"
                following += length
            assert following - 1 == total, "Incomplete source page set"
        self.citywide_store_periods = {period for dataset, period, scope in groups if dataset == "stores" and scope is None}
        for key in self.legacy_records:
            if key[2] in self.citywide_store_periods:
                assert self.files[records["stores"][key][1]]["area_code"] is None, "Legacy observation absent from full source"
        legacy_scopes = {(area, period) for area, _industry, period in self.legacy_records if period in self.citywide_store_periods}
        overlapping_full = {key for key in records["stores"] if (key[0], key[2]) in legacy_scopes}
        overlapping_legacy = {key for key in self.legacy_records if key[2] in self.citywide_store_periods}
        assert overlapping_full == overlapping_legacy, "Legacy/citywide observation sets differ"
        for dataset, period, scope in groups:
            if dataset == "stores" and period in self.citywide_store_periods and scope is not None:
                continue
            self.collected.add((dataset, scope, period))
        self.periods = {dataset: sorted({period for kind, _scope, period in self.collected if kind == dataset}) for dataset in SERVICES}
        self.rows = {dataset: RowView(values, FIELDS[dataset], self.names[dataset], self.industry_names) for dataset, values in records.items()}
        self.proof = {dataset: ProofView(values, self.files) for dataset, values in records.items()}
        self.legacy_stores = RowView(self.legacy_records, FIELDS["stores"], self.names["stores"], self.industry_names)
        self.legacy_areas = sorted({key[0] for key in self.legacy_records})

    def is_collected(self, dataset, area, period):
        return (dataset, None, period) in self.collected or (dataset, area, period) in self.collected

    def loader_samples(self, dataset):
        """At least one row per active page and industry/period, plus 0/missing."""
        selected, buckets = set(), {}
        for entry in self.files:
            if entry["dataset"] != dataset:
                continue
            if dataset == "stores" and entry["period"] in self.citywide_store_periods and entry["area_code"] is not None:
                continue
            if entry["keys"]:
                selected.add(entry["keys"][len(entry["keys"]) // 2])
        for key, (values, _file_id) in self.rows[dataset].records.items():
            bucket = (key[1], key[2])
            buckets.setdefault(bucket, key)
            if values[0] == 0 or values[0] is None:
                selected.add(key)
        selected.update(buckets.values())
        return sorted(selected, key=str)


@lru_cache(maxsize=2)
def get_oracle(raw_root=RAW, manifest_path=MANIFEST):
    return Oracle(raw_root, manifest_path)
