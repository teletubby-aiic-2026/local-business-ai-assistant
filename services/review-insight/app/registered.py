"""사장님이 직접 등록한 가게 (6차 회의 11/20). 합성 폴더(data/synthetic/<가게>)가 없는 가게를 이 목록에서 찾는다.

화면 서버가 등록 가게의 요청마다 X-IC26-Store-Profile 헤더(shared/store_header.py)에 가게 프로필을 실어 보내면,
main.py 의 미들웨어가 검사해서 여기에 넣는다. 이 목록은 프로세스 메모리(크기 상한 LRU)라 서비스가 다시 켜지면 비지만,
다음 요청에 헤더가 같이 오므로 그 요청부터 바로 안다. 헤더 없이 온 모르는 가게는 예전처럼 404 STORE_NOT_FOUND.

등록 가게에는 합성 리뷰·정답표가 없다 (붙여넣은 리뷰만). 리뷰가 0건이면 분석은 빈 결과다.
shared/ 가 없는 환경(이 서비스만 담은 Dockerfile 이미지)에서는 등록 가게를 받지 않는다 (헤더가 오면 400).
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.models import CHANNELS

_codec = None


def codec():
    """shared.store_header (없으면 None). storage.py 처럼 저장소 루트를 sys.path 맨 뒤에 붙여 한 번 더 찾는다."""
    global _codec
    if _codec is None:
        try:
            import shared.store_header as found
        except ImportError:
            root = str(Path(__file__).resolve().parents[3])
            if root not in sys.path:
                sys.path.append(root)
            try:
                import shared.store_header as found
            except ImportError:
                return None
        _codec = found
    return _codec


_registry = None


def registry():
    global _registry
    if _registry is None:
        found = codec()
        if found is None:
            return None
        _registry = found.Registry()
    return _registry


def accept(value: str | None) -> dict | None:
    """헤더 값 → 검사한 프로필을 목록에 넣고 돌려준다. 값이 없으면 None. 틀리면 ValueError (main.py 가 400)."""
    if not value:
        return None
    found = codec()
    if found is None:
        raise ValueError("이 서버에는 등록 가게를 받는 코드(shared/store_header.py)가 없습니다")
    profile = found.decode(value)
    registry().put(profile)
    return profile


def get(store_id: str | None) -> dict | None:
    reg = registry()
    return reg.get(store_id) if reg is not None else None


def store_json(store_id: str) -> dict | None:
    """등록 가게의 store.json 모양 (합성 가게와 같은 칸 + registered: true). 모르면 None."""
    profile = get(store_id)
    return codec().store_json(profile, CHANNELS) if profile is not None else None
