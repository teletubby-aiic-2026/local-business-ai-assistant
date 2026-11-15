"""개발 전용: 합성 상권 자료로 상권 서비스(ic26-market)를 띄운다 — 상권 채팅 서랍과 프록시를 공식 자료 없이 끝까지 시험하는 용도.

왜 필요한가
  공식 상권 자료(services/market-analysis/data/official 등 8분기)는 저장소에 없고 팀원에게 압축 파일로 받는다. 자료가 오기 전에도
  비서 화면 → 프록시 → 상권 서비스 → (실시간 HCX-005) 전체를 확인해야 한다. 상권 서비스의 시험(tests/)이 쓰는 합성 자료와 같은
  것을 쓴다 (가짜 상권 목록 = FakeAnalysisCatalogue, 가짜 B2~B6 분석 = Analyses). 서울시 OpenAPI 수집(--collect)과 네이버 지도 호출은 하지 않는다.
  답에 나오는 숫자는 합성 값이다 (예: 추정매출 1,000원). 실제 상권 숫자가 아니다.

무엇이 실제인가: 상권 서비스의 라우터·세션 쿠키·Host/Origin 검사·질문 분류·근거 카드·답 점검, APP_MODE=live 일 때의 HCX-005 호출.
무엇이 가짜인가: 상권 후보 목록(장승배기역 → 4번 상권 하나)과 분석 숫자.

실행 (파이썬 3.12 — 상권 서비스의 requirements.lock 이 pyproj 3.8 을 쓰기 때문. 컨테이너 예):
  docker run --rm -p 127.0.0.1:18766:8766 -v <저장소>:/repo:ro -w /repo/services/market-analysis \
      -e PYTHONDONTWRITEBYTECODE=1 -e ASSISTANT_ENABLED=1 -e APP_MODE=live -e CLOVA_STUDIO_API_KEY \
      ic26-market-dev:py312 python /repo/services/web/scripts/serve_market_synthetic.py
  (-e CLOVA_STUDIO_API_KEY 는 값을 적지 않고 이름만 적는다: 셸에 이미 있는 값이 컨테이너로 넘어간다. APP_MODE 를 mock 으로 두면 키 없이 고정 문형 답)
  비서 화면 서버는 MARKET_URL=http://127.0.0.1:18766 으로 가리키면 된다 (프록시는 Host: 127.0.0.1:8766 을 직접 실어 보낸다).
"""
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

MARKET = Path(__file__).resolve().parents[2] / "market-analysis"
sys.path.insert(0, str(MARKET))

# 분석 모듈을 먼저 불러 둔다 (가짜 카탈로그 모듈로 바꾸기 전에). 시험 도우미는 상권 서비스의 시험에서 그대로 가져온다.
import app.onboarding_changes  # noqa: E402,F401
import app.onboarding_comparison  # noqa: E402,F401
import app.onboarding_population  # noqa: E402,F401
import app.onboarding_sales  # noqa: E402,F401
import app.onboarding_stores  # noqa: E402,F401
from app.onboarding import OnboardingStore  # noqa: E402
from tests.test_assistant_flow import Analyses  # noqa: E402
from tests.test_onboarding import FakeMaps, intake_api  # noqa: E402
from tests.test_onboarding_analysis import FakeAnalysisCatalogue  # noqa: E402

AREA_CODE, AREA_NAME = "3110826", "장승배기역 4번"


class JangseungbaegiCatalogue(FakeAnalysisCatalogue):
    """장승배기역이면 '장승배기역 4번' 상권을 후보로 준다 (우리 가게의 실제 상권 코드). 다른 위치는 시험의 합성 상권 그대로."""

    def options(self, location, industry_code):
        result = super().options(location, industry_code)
        if location.get("label") == "장승배기역" and result["candidates"]:
            candidate = deepcopy(result["candidates"][0])
            candidate.update(area_code=AREA_CODE, name=AREA_NAME, relation="inside", distance_m=0.0)
            result = {**result, "candidates": [candidate]}
        return result

    def validate(self, location, industry_code, area_code, period, expected_catalog_version=None):
        result = super().validate(location, industry_code, area_code, period, expected_catalog_version)
        if area_code == AREA_CODE:
            result["area_name"] = AREA_NAME
        return result


def build_app():
    stack = ExitStack()
    stack.enter_context(patch.object(intake_api, "load_settings", return_value=None))     # .env 를 읽지 않는다
    stack.enter_context(patch.object(intake_api, "MapsClient", return_value=FakeMaps()))  # 네이버 지도를 부르지 않는다
    catalogue = JangseungbaegiCatalogue()
    module = ModuleType("app.onboarding_analysis_catalog")
    module.get_analysis_options = catalogue.options
    module.validate_analysis_selection = catalogue.validate
    stack.enter_context(patch.dict(sys.modules, {module.__name__: module}))
    analyses = Analyses()
    for target, fake in (("app.onboarding_sales.build_sales_analysis", analyses.sales),
                         ("app.onboarding_stores.build_stores_analysis", analyses.stores),
                         ("app.onboarding_population.build_population_analysis", analyses.population),
                         ("app.onboarding_changes.build_changes_analysis", analyses.changes),
                         ("app.onboarding_comparison.get_comparison_options", analyses.comparison_options),
                         ("app.onboarding_comparison.build_comparison_analysis", analyses.comparison)):
        stack.enter_context(patch(target, fake))
    path = os.environ.get("ONBOARDING_DB_PATH") or str(Path(tempfile.mkdtemp()) / "onboarding.sqlite3")
    return intake_api.create_app(onboarding_store=OnboardingStore(path)), stack


if __name__ == "__main__":
    import uvicorn

    os.environ.setdefault("ASSISTANT_ENABLED", "1")
    application, _stack = build_app()      # _stack 을 닫지 않는다: 가짜들은 서버가 살아 있는 동안 켜져 있어야 한다
    print("합성 상권 자료로 상권 서비스를 띄웁니다 (숫자는 합성 값). APP_MODE =", os.environ.get("APP_MODE") or "(mock)", flush=True)
    uvicorn.run(application, host=os.environ.get("MARKET_BIND", "0.0.0.0"), port=int(os.environ.get("MARKET_PORT", "8766")),
                access_log=False)
