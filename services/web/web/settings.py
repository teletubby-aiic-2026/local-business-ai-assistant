"""경로와 실행 모드. 모두 환경 변수로 바꿀 수 있고, 값이 없으면 병합 뒤 저장소 구조를 기본으로 씁니다.

APP_MODE
  mock    기본. 키 없이 도는 시험용 실행. ① #14(규칙 분류)를 그 자리에서 부르고, ② 이유는 고정 문장,
          ③ 은 C6 저장 예시(c6_cache_best.json). 실제 AI 결과가 아니다.
  live    HCX-005 호출. ② 이유 문장과 ③ 생성 결과를 모두 실시간으로 만든다. 파일에 저장하지 않는다.
발표 모드(replay)는 없어졌다. APP_MODE=replay 는 오류.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1]      # services/web
REPO_ROOT = Path(__file__).resolve().parents[3]    # 저장소 루트

MODES = ("mock", "live")


def _seconds(raw: str, default: float) -> float:
    """숫자가 아니거나 0 이하면 기본값. 오타 때문에 서버가 켜지지 않는 일은 없게 한다."""
    try:
        value = float((raw or "").strip()) if (raw or "").strip() else default
    except ValueError:
        return default
    return value if 0 < value <= 300 else default


@dataclass(frozen=True)
class Settings:
    mode: str = "mock"
    store_id: str = "store_ongi"
    review_url: str = "http://127.0.0.1:8020"
    review_token: str = ""
    review_paste_timeout: float = 45.0   # 리뷰 저장을 기다리는 최대 시간(초). 리뷰 분석이 저장하며 HCX 로 분류함 (20초 + 다시 1번)
    snapshot_path: Path = REPO_ROOT / "data" / "scenario" / "snapshot_2026Q2.json"
    marketing_dir: Path = REPO_ROOT / "experiments" / "marketing"
    runtime_dir: Path = WEB_DIR / "data" / "runtime"
    card_b_snapshot_id: str = ""
    card_b_threshold: float = -5.0
    model: str = "HCX-005"
    clova_key: str = ""
    # 상권 비서 프록시 (assistant_proxy.py). market_url 을 off 로 쓰면 이 서버에서는 상권 비서를 끈다
    market_url: str = "http://127.0.0.1:8766"
    market_host: str = "127.0.0.1:8766"
    market_timeout: float = 75.0
    # 고객응대 프록시 (care_proxy.py: 캡처 입력·응대 점수·보고서). 비우면 리뷰 분석 서버(review_url)와 같은 곳, off 면 끈다
    care_url: str = ""
    care_timeout: float = 100.0      # 캡처 하나를 기다리는 최대 시간(초). 긴 캡처는 조각(최대 5)마다 HCX 를 부름. Nginx 120초보다 짧게
    care_public: bool = False        # 손님용 문의 페이지(/s/…)·/api/care/public/* 를 열지. 보안 검토 전까지 꺼 둠 (팀장 결정 11/15)
    # 맞춤 마케팅 프록시 (marketing_proxy.py: 김수현 님 설문형 마케팅 서비스). off 면 이 서버에서 맞춤 마케팅을 끈다
    marketing_url: str = "http://127.0.0.1:8030"
    marketing_timeout: float = 45.0  # 글을 만드는 경로(plan·generate·idea-try)를 기다리는 최대 시간(초). 나머지는 10초

    def __post_init__(self) -> None:
        if str(self.mode).lower() == "replay":
            raise ValueError("발표 모드(APP_MODE=replay)는 없어졌습니다. live 또는 mock을 쓰세요 "
                             "(live = HCX-005 실시간, mock = 키 없이 도는 시험용 실행)")
        if self.mode not in MODES:
            raise ValueError(f"APP_MODE는 {list(MODES)} 중 하나여야 합니다 (받은 값: {self.mode!r})")

    @property
    def key_present(self) -> bool:
        return bool(self.clova_key)

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        return cls(
            mode=env("APP_MODE", "mock").strip() or "mock",
            store_id=env("DEMO_STORE_ID", "store_ongi"),
            review_url=env("REVIEW_INSIGHT_URL", "http://127.0.0.1:8020").rstrip("/"),
            review_token=env("REVIEW_INSIGHT_TOKEN", "").strip(),
            review_paste_timeout=_seconds(env("REVIEW_PASTE_TIMEOUT_SEC", ""), 45.0),
            snapshot_path=Path(env("SNAPSHOT_PATH", str(cls.snapshot_path))),
            marketing_dir=Path(env("MARKETING_DIR", str(cls.marketing_dir))),
            runtime_dir=Path(env("WEB_RUNTIME_DIR", str(cls.runtime_dir))),
            card_b_snapshot_id=env("CARD_B_SNAPSHOT_ID", "").strip(),
            card_b_threshold=float(env("CARD_B_THRESHOLD", "-5") or -5),
            model=env("LLM_MODEL_WEB", "HCX-005"),
            # 같은 HCX 키를 파트마다 다른 이름으로 읽는다: #16 은 CLOVA_API_KEY, #14 는 CLOVASTUDIO_API_KEY
            clova_key=(env("CLOVA_API_KEY") or env("CLOVASTUDIO_API_KEY") or "").strip(),
            market_url=env("MARKET_URL", "http://127.0.0.1:8766").strip(),
            market_host=env("MARKET_HOST", "127.0.0.1:8766").strip() or "127.0.0.1:8766",
            market_timeout=_seconds(env("MARKET_TIMEOUT_SEC", ""), 75.0),
            care_url=env("CARE_URL", "").strip(),
            care_timeout=_seconds(env("CARE_TIMEOUT_SEC", ""), 100.0),
            care_public=env("CARE_PUBLIC", "").strip().lower() in ("1", "true", "yes", "on"),
            marketing_url=env("MARKETING_SURVEY_URL", "http://127.0.0.1:8030").strip(),
            marketing_timeout=_seconds(env("MARKETING_TIMEOUT_SEC", ""), 45.0),
        )
