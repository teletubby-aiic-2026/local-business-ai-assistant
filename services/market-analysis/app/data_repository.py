"""Official source definitions and deterministic, atomic JSON utilities."""
import json
import os
import tempfile
from hashlib import sha256
from pathlib import Path


SOURCE_URLS = {
    "sales": "https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do",
    "stores": "https://data.seoul.go.kr/dataList/OA-15577/S/1/datasetView.do",
    "population": "https://data.seoul.go.kr/dataList/OA-15568/S/1/datasetView.do",
    "areas": "https://data.seoul.go.kr/dataList/OA-15560/S/1/datasetView.do",
}


TIME_LABELS = ("00~06시", "06~11시", "11~14시", "14~17시", "17~21시", "21~24시")


TIME_KEYS = ("00_06", "06_11", "11_14", "14_17", "17_21", "21_24")


AGE_LABELS = ("10대", "20대", "30대", "40대", "50대", "60대 이상")


AGE_KEYS = ("10", "20", "30", "40", "50", "60_ABOVE")


DAY_LABELS = ("월", "화", "수", "목", "금", "토", "일")


DAY_KEYS = ("MON", "TUES", "WED", "THUR", "FRI", "SAT", "SUN")


DISTRIBUTION_FIELDS = {
    "sales_time": [(label, f"TMZON_{key}_SELNG_AMT") for label, key in zip(TIME_LABELS, TIME_KEYS)],
    "sales_weekday": [(label, f"{key}_SELNG_AMT") for label, key in zip(DAY_LABELS, DAY_KEYS)],
    "sales_age": [(label, f"AGRDE_{key}_SELNG_AMT") for label, key in zip(AGE_LABELS, AGE_KEYS)],
    "population_time": [(label, f"TMZON_{key}_FLPOP_CO") for label, key in zip(TIME_LABELS, TIME_KEYS)],
    "population_age": [(label, f"AGRDE_{key}_FLPOP_CO") for label, key in zip(AGE_LABELS, AGE_KEYS)],
}


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def atomic_json_write(path: Path, value: object) -> None:
    """Write a complete UTF-8 document before replacing the destination."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".pending-", suffix=".json", delete=False) as output:
            temporary = Path(output.name)
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
