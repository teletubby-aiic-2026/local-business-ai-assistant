"""공통 설정: 모델명, 요금, API 키, 경로."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"

DEFAULT_MODEL = "HCX-005"
PRICE_PER_1K = {"HCX-005": 7, "HCX-007": 7}  # 대략 요금(원), 실제 요금은 콘솔에서 확인


def get_api_key():
    return os.environ.get("CLOVA_API_KEY") or input("CLOVA Studio API 키: ").strip()
