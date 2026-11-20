"""가게마다의 Demo·프록시 묶음 (5차 회의 11/18: 사장님 한 명이 가게 여러 개).

요청마다 고른 가게(request.state.store_id)의 Demo·고객응대·맞춤 마케팅·상권 서랍 프록시를 돌려준다.
- 기본 가게(DEMO_STORE_ID, store_ongi)는 create_app 에 넘긴 그 객체를 그대로 쓴다. 로그인하지 않으면 늘 이 가게라서
  예전 동작·시험이 그대로다.
- 다른 가게는 처음 쓸 때 만든다. Demo 는 가게마다 따로 만든다 (승인 기록을 잠시 들고 있는 줄·초안 기억이 가게별이어야 함).
  리뷰 분석 연결·저장소·이유 모델은 기본 Demo 의 것을 같이 쓴다. 상권 지표 파일은 shared.store_profiles 의 가게별 파일.
- 프록시는 for_store 로 만든 얕은 사본이다 (같은 HTTP 연결·동시 요청 한도를 같이 쓰고, 가게 id 만 다르다).
- 직접 등록한 가게(11/20)도 같은 방식이다. 상권 지표 파일이 없는 경로라 카드 ⓑ 는 뜨지 않고, 리뷰 분석 서비스가 아직 모르는 가게라
  브리핑·카드는 503 이다 (다음 단계에서 리뷰 분석·맞춤 마케팅이 등록 가게를 받게 한다).
"""
from __future__ import annotations

import dataclasses
import threading

from shared import store_profiles

from .demo import Demo


class StoreHub:
    def __init__(self, demo: Demo, assistant, care, marketing):
        self.default_id = demo.s.store_id
        self._base = demo
        self._demos: dict[str, Demo] = {self.default_id: demo}
        self._assistant = {self.default_id: assistant}
        self._care = {self.default_id: care}
        self._marketing = {self.default_id: marketing}
        self._lock = threading.Lock()

    def known(self, store_id: str | None) -> bool:
        return store_id == self.default_id or store_profiles.known(store_id)

    def _id(self, store_id: str | None) -> str:
        return store_id if store_id and self.known(store_id) else self.default_id

    def demo(self, store_id: str | None = None) -> Demo:
        sid = self._id(store_id)
        with self._lock:
            found = self._demos.get(sid)
        if found is not None:
            return found
        # 직접 등록한 가게(11/20)는 저장소에서 찾으므로 잠금 밖에서 읽는다. 그 사이 지워졌으면 기본 가게
        bundle = store_profiles.get(sid)
        if bundle is None:
            sid, bundle = self.default_id, store_profiles.get(self.default_id)
        with self._lock:
            found = self._demos.get(sid)
            if found is None:
                base = self._base
                settings = dataclasses.replace(base.s, store_id=sid, snapshot_path=bundle.snapshot_path,
                                               card_b_snapshot_id="")
                found = Demo(settings, source=base.source, reason_model=base._reason_model, storage=base.storage)
                self._demos[sid] = found
            return found

    def assistant(self, store_id: str | None = None):
        sid = self._id(store_id)
        with self._lock:
            found = self._assistant.get(sid)
            if found is not None:
                return found
        demo = self.demo(sid)
        with self._lock:
            found = self._assistant.get(sid)
            if found is None:
                found = self._assistant[self.default_id].for_store(sid)
                found.attach_store(demo)
                self._assistant[sid] = found
            return found

    def care(self, store_id: str | None = None):
        sid = self._id(store_id)
        with self._lock:
            if sid not in self._care:
                self._care[sid] = self._care[self.default_id].for_store(sid)
            return self._care[sid]

    def marketing(self, store_id: str | None = None):
        sid = self._id(store_id)
        with self._lock:
            if sid not in self._marketing:
                self._marketing[sid] = self._marketing[self.default_id].for_store(sid)
            return self._marketing[sid]

    def demos(self) -> list[Demo]:
        with self._lock:
            return list(self._demos.values())
