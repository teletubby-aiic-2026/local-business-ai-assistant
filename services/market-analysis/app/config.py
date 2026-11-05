"""Load local server configuration explicitly at application startup."""
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def load_settings() -> None:
    load_dotenv(ROOT / ".env", override=False, encoding="utf-8-sig")
