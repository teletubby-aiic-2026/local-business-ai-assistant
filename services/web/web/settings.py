"""경로와 실행 모드. 모두 환경 변수로 바꿀 수 있고, 값이 없으면 병합 뒤 저장소 구조를 기본으로 씁니다.

APP_MODE
  mock    기본. 키 없이 돈다. ① #14(규칙 분류)를 그 자리에서 부르고, ② 이유는 고정 문장, ③ 은 저장본.
  live    HCX-005 호출. ② 이유 문장과 ③ 생성 결과를 C9 저장본(web_cache.json)에 기록한다.
  replay  발표 모드. 저장본만 쓴다. 네트워크·#14·키가 없어도 ①→④ 가 같은 결과로 돈다.
DEMO_LADDER (live 에서만 뜻이 있음, 결정안 6절 사다리)
  0  ③ 전부 실시간
  1  ③ 답글만 실시간, 공지·홍보글은 저장본
  2  ③ 답글 하나만 실시간, 나머지는 저장본
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1]      # services/web
REPO_ROOT = Path(__file__).resolve().parents[3]    # 저장소 루트

MODES = ("mock", "live", "replay")


@dataclass(frozen=True)
class Settings:
    mode: str = "mock"
    ladder: int = 0
    store_id: str = "store_ongi"
    review_url: str = "http://127.0.0.1:8020"
    review_token: str = ""
    snapshot_path: Path = REPO_ROOT / "data" / "scenario" / "snapshot_2026Q2.json"
    marketing_dir: Path = REPO_ROOT / "experiments" / "marketing"
    cache_path: Path = WEB_DIR / "data" / "replay" / "web_cache.json"
    runtime_dir: Path = WEB_DIR / "data" / "runtime"
    card_b_snapshot_id: str = ""
    card_b_threshold: float = -5.0
    model: str = "HCX-005"
    clova_key: str = ""

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"APP_MODE는 {list(MODES)} 중 하나여야 합니다 (받은 값: {self.mode!r})")
        if self.ladder not in (0, 1, 2):
            raise ValueError(f"DEMO_LADDER는 0, 1, 2 중 하나여야 합니다 (받은 값: {self.ladder!r})")

    @property
    def key_present(self) -> bool:
        return bool(self.clova_key)

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        return cls(
            mode=env("APP_MODE", "mock").strip() or "mock",
            ladder=int(env("DEMO_LADDER", "0") or 0),
            store_id=env("DEMO_STORE_ID", "store_ongi"),
            review_url=env("REVIEW_INSIGHT_URL", "http://127.0.0.1:8020").rstrip("/"),
            review_token=env("REVIEW_INSIGHT_TOKEN", "").strip(),
            snapshot_path=Path(env("SNAPSHOT_PATH", str(cls.snapshot_path))),
            marketing_dir=Path(env("MARKETING_DIR", str(cls.marketing_dir))),
            cache_path=Path(env("WEB_CACHE_PATH", str(cls.cache_path))),
            runtime_dir=Path(env("WEB_RUNTIME_DIR", str(cls.runtime_dir))),
            card_b_snapshot_id=env("CARD_B_SNAPSHOT_ID", "").strip(),
            card_b_threshold=float(env("CARD_B_THRESHOLD", "-5") or -5),
            model=env("LLM_MODEL_WEB", "HCX-005"),
            # 같은 HCX 키를 파트마다 다른 이름으로 읽는다: #16 은 CLOVA_API_KEY, #14 는 CLOVASTUDIO_API_KEY
            clova_key=(env("CLOVA_API_KEY") or env("CLOVASTUDIO_API_KEY") or "").strip(),
        )
