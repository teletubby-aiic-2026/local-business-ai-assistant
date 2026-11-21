"""사장님 기록 지우기 — 계정 초기화(POST /api/auth/reset)와 회원 탈퇴(POST /api/auth/withdraw)가 같이 쓴다 (11/19).

가게마다 그 방문자(u-<user_id>)의 기록만 지운다. 다른 가게·다른 사장님·게스트의 기록은 건드리지 않는다.
- 승인 기록: Demo.clear_approvals (DB 에 아직 못 쓴 _pending 포함). 메모리 방식의 approvals.jsonl(덧붙이기 기록)은 그대로다.
- 붙여넣은 리뷰와 그 상태·답글 기록, 그 리뷰들의 분류 결과: 리뷰 분석 서비스 (Demo.erase_pasted → forget_labels=true).
- 맞춤 마케팅 기록: MarketingProxy.clear_state → cleared | off | failed.
- 상권 대화·조건은 여기서 지우지 않는다: 상권 세션 쿠키의 경로가 /api/assistant·/api/market 이라 이 요청에 오지 않는다.
  화면이 먼저 DELETE /api/assistant/conversation 을 부르고, 이 서버는 응답에서 두 쿠키를 만료시킨다 (auth._reset_market).
- 저장된 주간·월간 보고서: 계정별 저장이라 같이 지운다 (reports.ReportBook.erase, 11/20).
- 카드 이유(card_reasons)는 가게 공용이라 지우지 않는다.

지우지 못한 것이 있어도 예외를 내지 않는다. 지울 수 있는 것은 지우고 complete=false 와 쉬운 문장(message)을 돌려준다.
여러 번 불러도 안전하다 (이미 지운 것은 0건).
"""
from __future__ import annotations

import logging

from shared import store_profiles

log = logging.getLogger("web.account")

PARTS = (("approvals", "승인 기록"), ("reviews", "붙여넣은 리뷰"), ("marketing", "맞춤 마케팅 기록"))


def _name(store_id: str) -> str:
    bundle = store_profiles.get(store_id)
    return bundle.short_name if bundle else store_id


class AccountData:
    def __init__(self, hub, reports=None):
        self.hub = hub
        self.reports = reports      # 저장된 주간·월간 보고서를 지우는 곳 (reports.ReportBook, 11/20). main.py 가 만든 뒤 꽂는다

    def clear_store(self, store_id: str, visitor_id: str) -> dict:
        """가게 하나. {store_id, name, approvals, reviews, marketing}. 못 지운 칸은 None (marketing 은 'failed')."""
        demo = self.hub.demo(store_id)
        try:
            approvals = demo.clear_approvals(visitor_id)
        except Exception as exc:
            log.warning("초기화: 승인 기록을 지우지 못했어요 (%s, %s)", store_id, exc.__class__.__name__)
            approvals = None
        try:
            reviews = demo.erase_pasted(visitor_id)
        except Exception as exc:
            bundle = store_profiles.get(store_id)
            if bundle is not None and bundle.registered and "오류 404" in str(exc):
                # 직접 등록한 가게(11/20): 리뷰 분석 서비스는 가게 프로필 헤더로 그 가게를 안다 (sources.ReviewSource).
                # 그래도 404 면 (헤더를 모르는 옛 판 서비스) 그 서비스에는 이 가게의 붙여넣은 리뷰가 있을 수 없다
                reviews = 0
            else:
                log.warning("초기화: 붙여넣은 리뷰를 지우지 못했어요 (%s, %s)", store_id, exc.__class__.__name__)
                reviews = None
        try:
            marketing = self.hub.marketing(store_id).clear_state(visitor_id)
        except Exception as exc:                      # clear_state 는 예외를 내지 않지만 한 번 더 막는다
            log.warning("초기화: 맞춤 마케팅 기록을 지우지 못했어요 (%s, %s)", store_id, exc.__class__.__name__)
            marketing = "failed"
        return {"store_id": store_id, "name": _name(store_id), "approvals": approvals, "reviews": reviews,
                "marketing": marketing}

    def clear(self, store_ids, visitor_id: str) -> dict:
        """가게 여러 곳. {complete, message, stores}. visitor_id 는 로그인한 사장님의 방문자(u-…)여야 한다."""
        if not (isinstance(visitor_id, str) and visitor_id.startswith("u-")):
            raise ValueError("로그인한 사장님의 방문자 id 만 지울 수 있어요")   # 게스트·공용 기록을 지우지 않게
        stores = [self.clear_store(s, visitor_id) for s in dict.fromkeys(store_ids)]
        left = []
        for row in stores:
            missed = [label for key, label in PARTS
                      if (row[key] == "failed" if key == "marketing" else row[key] is None)]
            if missed:
                left.append(f"{row['name']}의 {'·'.join(missed)}")
        if self.reports is not None:      # 이 사장님이 저장한 주간·월간 보고서 (계정별 저장, 11/20). 응답의 가게 줄 모양은 그대로 둔다
            try:
                self.reports.erase(list(dict.fromkeys(store_ids)), visitor_id)
            except Exception as exc:
                log.warning("초기화: 저장된 보고서를 지우지 못했어요 (%s)", exc.__class__.__name__)
                left.append("저장된 보고서")
        message = None
        if left:
            message = f"{', '.join(left)}을(를) 지우지 못했어요. 나머지는 지웠어요. 잠시 뒤 다시 해 주세요."
        return {"complete": not left, "message": message, "stores": stores}
