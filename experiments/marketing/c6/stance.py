"""답글 태도 판정 — 리뷰 글(과 분류 주제)만 보고 규칙으로 정한다. AI 호출 없음, 같은 입력이면 늘 같은 답.

태도 2가지
- "apology" (기본): 가게 과실일 수 있는 불만. 지금까지와 똑같은 사과 답글(c6.reply 의 원래 프롬프트·점검).
- "explain": 가게 과실이 아니라, 가게가 정한 메뉴·원칙 밖의 요청을 거절해서 남은 낮은 별점 리뷰.
  사과·보상 약속 없이 정중하게 유감을 표하고 사실·가게 원칙을 담백하게 설명한다(c6.reply_explain).

판정은 보수적이다. 아래 네 가지가 모두 맞을 때만 explain 이고, 하나라도 아니면 apology 다.
진짜 가게 잘못을 '억울한 리뷰'로 잘못 보고 사과 없는 답글을 내는 쪽이 그 반대보다 훨씬 나쁘기 때문이다.
  1. 원칙 밖 요청 표현이 있다 (무료·서비스로 달라, 메뉴·구성을 바꿔 달라, 다 먹고 환불, 배달 지역 밖, 손님 주문 실수 뒤 다시 보내 달라)
  2. 가게가 거절했다는 표현이 있다 (안 된대요, 거절, 못 해 준다, 추가 요금을 내라 …)
  3. 가게 과실일 수 있는 표현이 하나도 없다 (빠짐·늦음·식음·이물질·맛·양·포장·불친절·잘못 온 메뉴·요청사항 …)
     그리고 리뷰 분류가 붙인 불만 주제에 과실 주제(FAULT_TOPICS)가 없다.
  4. 요청에 이유가 붙어 있지 않다. "…해서 바꿔 달라", "… 때문에 환불"처럼 요청 앞에 이유가 있으면, 그 이유가
     3번의 낱말 목록에 없는 표현이어도 가게 잘못일 수 있다 ("음식이 이상해서", "플라스틱이 나와서").
     받은 음식을 서술하는 말("된장찌개가 왔어요")도 같은 이유로 apology 로 돌린다.
4번 때문에 "매운 걸 못 먹어서 바꿔 달라고 했더니 안 된대요"처럼 손님 사정이 이유인 억울한 리뷰도 apology 가 된다.
놓치는 쪽(사과 답글이 나감)은 받아들이고, 잘못 잡는 쪽(가게 잘못에 사과 없는 답글)을 막는다.
가게가 실제로 그랬는지는 시스템이 알 수 없고 사장님만 안다. 그래서 explain 답글에는 태도(stance)와 판정 근거를
응답에 싣고, 사장님이 사실을 확인하라는 안내(needs_input)를 붙인다. 답글은 늘 사장님이 고치고 승인한 뒤 올린다.

점검 묶음 (태도마다 다른 묶음을 쓴다. 점검을 느슨하게 한 것이 아니라 상황에 맞는 점검으로 바꾼 것)
- APOLOGY_CHECKS: c6.reply._run_checks 와 _check. main 의 점검에 apology_expressed(글 어디든 사과 표현이 있는가)를 더했다.
  PR #36(AI 는 공감·사과만, 조치·요청사항·인사는 코드가 붙임)의 점검(no_broken_ending·no_claimed_action·ai_part_only_empathy·style_match)도 들어 있다.
  첫 문장 강제(has_apology)가 아니다. 가게 과실일 수 있는 불만에 사과 없는 답글이 '점검 통과'로 나가지 않게 한다.
- EXPLAIN_CHECKS: c6.reply_explain.run_explain_checks. 사과 대신 '과실 인정 없음'·'유감 표현'·'원칙 설명'·'보상 약속 없음'·
  '손님 탓·훈계·비꼼 없음'을 보고, 정책·숫자·개인정보·길이·딱딱한 말·장담·금지 표현은 apology 와 같은 점검을 쓴다.
- checks.has_apology(처음 두 문장의 사과 — 11/15부터 '사과드립니다'·'송구' 등도 인정)는 재발 방지 공지(c6.notice)에만 쓴다.
  답글은 main 에서도 has_apology 점검이 없고, 프롬프트(사과 → 약속 → 감사 순서)로 사과를 시킨다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

APOLOGY = "apology"
EXPLAIN = "explain"
STANCES = (APOLOGY, EXPLAIN)
STANCE_LABELS = {APOLOGY: "사과하는 답글", EXPLAIN: "사과 없이 사실·원칙을 설명하는 답글"}

# 태도마다 적용하는 답글 점검 묶음. 생성기가 이 이름들을 checks 에 그대로 남긴다(시험이 일치하는지 확인).
# no_forbidden_phrase 는 말투(ToneProfile)에 금지 표현이 있을 때만, not_too_similar 는 카드 단위로 나중에 붙는다.
APOLOGY_CHECKS = (
    "evidence_valid", "no_invented_measure", "chosen_measure_included", "missing_mentioned", "apology_expressed", "no_bad_promise",
    "no_bad_number", "no_personal_info", "length_ok", "no_stiff_words", "no_overpromise", "uses_opening", "uses_closing",
    "no_broken_ending", "no_claimed_action", "ai_part_only_empathy", "style_match",
)
EXPLAIN_CHECKS = (
    "evidence_valid", "no_bad_promise", "no_compensation_offer", "no_fault_admission", "no_customer_blame",
    "has_regret", "explains_principle", "request_mentioned", "haeyo_only", "no_invented_measure", "no_bad_number",
    "no_personal_info", "length_ok", "no_stiff_words", "no_overpromise", "uses_opening", "uses_closing",
)
CHECKS_BY_STANCE = {APOLOGY: APOLOGY_CHECKS, EXPLAIN: EXPLAIN_CHECKS}
# used_fallback: 코드 템플릿을 썼는지, ai_part_repaired: AI 글의 사과 어미를 바꾸거나 사과 한 문장을 덧붙였는지 (둘 다 참고용 표시)
OPTIONAL_CHECKS = ("no_forbidden_phrase", "not_too_similar", "used_fallback", "ai_part_repaired")

# explain 답글에 붙이는 사장님 확인 안내 (화면에서는 '확인 필요'로 보인다)
EXPLAIN_NEEDS_INPUT = ("사실 확인: 가게 잘못이 아니라 메뉴·원칙 밖 요청을 거절해 남은 리뷰로 보고, 사과 없이 사실·원칙을 "
                       "설명했어요. 실제로 그랬는지 확인하고, 가게 잘못이 있었다면 사과하는 답글로 고쳐 주세요.")

# 리뷰 분류(C3)의 불만 주제 중 가게 과실 쪽인 것. 이 주제가 붙어 있으면 글과 상관없이 apology.
# 맛·양·식감·응대·메뉴·가격은 '달라고'를 맛으로 잡는 등 규칙 분류가 흔들려서 넣지 않고, 아래 글 표현으로 본다.
FAULT_TOPICS = ("missing_item", "delivery_time", "temperature", "hygiene", "packaging", "wait_time")

# ── 1. 원칙 밖 요청 (종류마다 답글에 코드가 붙이는 원칙 문장) ───────────────
_SELF_MISTAKE = re.compile(r"제가\s*(?:주문을?\s*)?(?:잘못|실수|착각)|(?:잘못|실수로)\s*(?:눌러|주문|시켜|넣어|골라)")
_REDO = re.compile(r"다시\s*(?:보내|만들어)")

REQUESTS: dict[str, dict] = {
    "free_extra": {
        "name": "메뉴를 무료로 더 달라는 요청",
        "pattern": re.compile(r"서비스로|공짜|무료|돈\s*(?:을\s*)?안\s*받|덤으로|추가\s*(?:요금|비용|금액)\s*없이"
                             r"|(?:하나|좀|조금)?\s*더\s*(?:달라|주세요|넣어\s*달라)"),
        "principle": "추가하시는 메뉴는 메뉴판 가격대로 준비하고 있어요.",
    },
    "menu_change": {
        "name": "메뉴·구성을 바꿔 달라는 요청",
        "pattern": re.compile(r"(?:바꿔|변경해|교체해)\s*(?:달라|주세요|주실|줄|주시|달래|주면|주라)|다른\s*메뉴로"),
        "principle": "저희는 메뉴판에 있는 구성대로만 준비하고 있어요.",
    },
    "refund_after_eating": {
        "name": "다 드신 뒤 환불해 달라는 요청",
        "pattern": re.compile(r"(?:다|거의\s*다|반\s*넘게|절반\s*넘게)\s*먹(?:고|은|었).{0,20}환불|환불.{0,20}(?:다|거의\s*다)\s*먹"),
        "principle": "드신 뒤의 요청은 배달앱 고객센터를 통해 안내해 드리고 있어요.",
    },
    "customer_mistake": {
        "name": "주문을 잘못 넣으신 뒤 다시 보내 달라는 요청",
        "pattern": None,   # _SELF_MISTAKE 와 _REDO 가 둘 다 있어야 한다 (judge_stance 참고)
        "principle": "저희는 들어온 주문서대로 바로 조리를 시작하고 있어요.",
    },
    "outside_area_hours": {
        "name": "배달 가능 지역·영업시간 밖의 요청",
        "pattern": re.compile(r"배달\s*(?:가능\s*)?(?:지역|범위|구역)|영업\s*시간|마감\s*(?:시간|후|이후)"),
        "principle": "배달은 정해진 배달 가능 지역과 영업시간 안에서만 하고 있어요.",
    },
}
# 거절이 '차액·추가 요금을 내라'였으면(바꿔 줄 수는 있으나 무료는 아님) 원칙 문장을 이것으로 쓴다
FEE_PRINCIPLE = "메뉴를 바꾸거나 더하실 때는 메뉴판 가격대로 안내해 드리고 있어요."
_FEE_REFUSAL = re.compile(r"(?:요금|비용|금액|돈|차액)\S{0,2}\s*(?:더\s*)?(?:내라|내야|받는|받더|받겠|달라)")

# ── 2. 가게가 거절했다는 표현 ───────────────────────────────────────
_REFUSAL = re.compile(
    r"안\s*되(?:는|나|더)|안\s*된|안\s*돼|안된|안돼|거절|못\s*해\s*(?:준|주|드)|안\s*해\s*(?:준|주)|안\s*받아\s*주"
    r"|할\s*수\s*없|줄\s*수\s*없|어렵다|불가|(?:요금|비용|금액|돈|차액)\S{0,2}\s*(?:더\s*)?(?:내라|내야|받는|받더|받겠|달라)"
)

# ── 3. 가게 과실일 수 있는 표현 (하나라도 있으면 apology) ───────────────
FAULT_PATTERNS: dict[str, re.Pattern] = {
    "빠짐·잘못 온 메뉴": re.compile(
        r"빠[져졌지뜨]|누락|안\s*왔|안\s*와|안\s*들어|없었|없더|없네|오배송|잘못\s*(?:왔|와|온|배달|들어|나왔)"
        r"|다른\s*(?:게|것|메뉴|음식)\S{0,2}\s*(?:왔|와|오|들어)|주문(?:한|이랑|과)\s*(?:거|것|메뉴)?\S{0,2}\s*달라|덜\s*왔|개수|수량"),
    "늦은 배달·대기": re.compile(r"늦|오래\s*걸|넘게\s*걸|시간이나|한\s*시간|기다렸|기다리|지연|밀려|웨이팅"),
    "음식 온도": re.compile(r"식어|식었|식은|미지근|차갑|차가워|불어\s*(?:서|있)|불었"),
    "위생·탈": re.compile(r"머리카락|이물|벌레|위생|더럽|지저분|비닐|배탈|탈이\s*났|아팠"),
    "맛·품질": re.compile(
        r"맛(?:이|도|은)?\s*(?:없|이상|별로|변했|달라)|맛없|(?<!공)짜[요서고게다]|짰|싱거|싱겁|느끼|비린|비려|탔|탄\s*맛"
        r"|덜\s*익|안\s*익|설익|상한|상했|쉰\s|쉬었|딱딱|질기|질겨|눅눅|퍽퍽|매워|맵더|너무\s*맵|간이|(?:음식|메뉴|밥|국|반찬|고기)\S{0,2}\s*별로"),
    "양": re.compile(r"양이\s*(?:너무\s*|좀\s*|많이\s*|너무\s*많이\s*)?(?:적|줄|부족|작)|양도\s*(?:적|줄)|적게\s*(?:왔|들어|줬|주)|줄었|부족했|모자라|모자랐|조금밖에"),
    "포장": re.compile(r"샜|새서|새고|넘쳤|흥건|쏟아|흘러|흘렀|터져|터졌|찌그러|뭉개|포장이\s*(?:허술|엉망|부실)|뚜껑"),
    "응대·태도": re.compile(r"불친절|퉁명|반말|짜증|화를|화내|소리를|무시|막말|태도|싸가지|기분\s*나쁘|불쾌|성의\s*없|대충"),
    "결제": re.compile(r"잘못\s*결제|이중\s*결제|두\s*번\s*결제|계산이\s*(?:틀|잘못)|(?:가격|금액)이\s*(?:달랐|틀)"),
    "요청사항": re.compile(r"요청\s*사항"),
    # 받은 음식을 서술하는 말. 다른 음식이 왔다는 뜻일 수 있다 ("순두부찌개를 시켰는데 된장찌개가 왔어요")
    "받은 음식 서술": re.compile(r"(?:이|가|도|만|은|는)\s*왔|왔(?:어요|네요|는데|더라|습니다|음|길래|던데)|와서|온\s*(?:게|걸|것|거)"),
    # 위 목록에 없지만 음식·가게에 문제가 있었다는 뜻일 수 있는 말
    "그 밖의 문제 표현": re.compile(
        r"냄새|이상(?:해|했|하|한)|상태|문제(?:가|를|는)?\s*(?:있|생)|질어|질었|플라스틱|철사|수세미|조각|씹|시큼|쉰내|변질"
        r"|안\s*좋|취소|한참|먹다가|먹다\s*보니|사진(?:이랑|과|하고)?\s*(?:너무\s*|많이\s*)?(?:달|다르)"
        r"|(?:가게|사장|직원|알바|매장)\S{0,3}\s*(?:실수|잘못)"),
    # 손님도 확실하지 않다고 말한 리뷰는 사과 쪽에 둔다 ("제가 잘못 본 건지 모르겠지만")
    "확실하지 않다는 말": re.compile(r"모르겠|건지|인지\s*(?:는|도)?\s*모르"),
}

# ── 4. 요청 앞에 붙은 이유 (있으면 apology) ──────────────────────────
# "…해서 바꿔 달라", "… 때문에 환불"처럼 요청 앞에 이유가 붙으면 그 이유가 가게 잘못일 수 있다.
# 요청·거절 표현보다 앞쪽 글에서만 찾는다. 거절 뒤의 "안 된다고 해서 속상했어요"는 이유가 아니라 결과다.
# 장소를 뜻하는 '에서'·'여기서'와 '서비스'의 '서'는 이유가 아니다 (낱말 끝의 '서'만 본다).
_REASON_BEFORE = re.compile(r"(?:(?<![에기])서|길래|니까|니깐|때문에|바람에|탓에)(?=[\s,.!?~]|$)")
# 손님이 자기 실수를 말한 마디("제가 잘못 눌러서")는 이유로 세지 않는다 — 가게 잘못이 아니라 손님 사정이다
_SELF_MISTAKE_CLAUSE = re.compile(r"(?:" + _SELF_MISTAKE.pattern + r")[^\s,.!?]*(?:\s+[^\s,.!?]*)?")
# "다 먹고 나서", "먹고서"의 '서'는 이유가 아니라 순서다
_AFTER_DOING = re.compile(r"고\s*나서|고서")
# 요청을 옮겨 말한 마디("다시 보내 달라니까", "달라고 하니까")의 '니까'는 이유가 아니라 요청 그 자체다
_REQUEST_QUOTE = re.compile(r"(?:달라|달래|주라|주세요)(?:고\s*(?:하|했|말하|말했))?(?:니까|니깐)")


@dataclass(frozen=True)
class StanceDecision:
    stance: str                         # APOLOGY | EXPLAIN
    request: str | None = None          # explain 일 때 요청 종류 (REQUESTS 의 키)
    reasons: tuple[str, ...] = field(default_factory=tuple)   # 판정 근거 (사람이 읽는 한 줄들)
    principle: str | None = None        # explain 일 때 답글에 코드가 붙이는 가게 원칙 문장

    @property
    def request_name(self) -> str | None:
        return REQUESTS[self.request]["name"] if self.request else None


def _request_kind(text: str) -> tuple[str | None, str | None, int]:
    """(요청 종류, 찾은 표현, 글에서의 위치). 여러 개면 위에서부터 첫 번째.
    손님 주문 실수는 '제가 잘못' + '다시 보내'가 둘 다 있어야 한다."""
    mistake = _SELF_MISTAKE.search(text)
    if mistake and _REDO.search(text):
        return "customer_mistake", mistake.group(0), mistake.start()
    for kind in ("refund_after_eating", "free_extra", "menu_change", "outside_area_hours"):
        m = REQUESTS[kind]["pattern"].search(text)
        if m:
            return kind, m.group(0), m.start()
    return None, None, -1


def reason_before(text: str, upto: int) -> str | None:
    """요청·거절 표현보다 앞쪽 글에 이유를 붙이는 말이 있으면 그 낱말을 돌려준다. 손님이 자기 실수를 말한 '제가 잘못…'은 빼고 본다."""
    blank = lambda m: " " * len(m.group(0))
    head = text
    for skip in (_SELF_MISTAKE_CLAUSE, _AFTER_DOING, _REQUEST_QUOTE):
        head = skip.sub(blank, head)
    head = head[:max(upto, 0)]
    m = _REASON_BEFORE.search(head)
    if not m:
        return None
    start = head.rfind(" ", 0, m.start()) + 1
    return head[start:m.end()]


def fault_hits(text: str) -> list[str]:
    """가게 과실일 수 있는 표현을 '종류: 표현' 꼴로 모두 돌려준다. 손님이 자기 실수를 말한 '제가 잘못'은 빼고 본다."""
    rest = _SELF_MISTAKE.sub(" ", text)
    return [f"{name}: '{m.group(0)}'" for name, pattern in FAULT_PATTERNS.items() if (m := pattern.search(rest))]


def judge_stance(text: str, *, negative_topics: list[str] | tuple[str, ...] | None = None) -> StanceDecision:
    """리뷰 글로 답글 태도를 정한다. 애매하면 늘 APOLOGY."""
    text = " ".join((text or "").split())
    if not text:
        return StanceDecision(APOLOGY, reasons=("리뷰 글이 비어 있음",))
    faults = fault_hits(text)
    topic_faults = [t for t in (negative_topics or []) if t in FAULT_TOPICS]
    if faults or topic_faults:
        reasons = [f"가게 과실일 수 있는 표현 — {f}" for f in faults]
        reasons += [f"리뷰 분류의 과실 주제 — {t}" for t in topic_faults]
        return StanceDecision(APOLOGY, reasons=tuple(reasons))
    kind, req_word, req_at = _request_kind(text)
    if kind is None:
        return StanceDecision(APOLOGY, reasons=("메뉴·원칙 밖 요청 표현 없음",))
    refused = _REFUSAL.search(text)
    if refused is None:
        return StanceDecision(APOLOGY, reasons=(f"요청 표현('{req_word}')은 있으나 가게가 거절했다는 표현 없음",))
    refusal = refused.group(0)
    why = reason_before(text, max(req_at, refused.start()))
    if why:
        return StanceDecision(APOLOGY, reasons=(f"요청 앞에 이유가 붙어 있음('{why}') — 가게 잘못일 수 있어 사과 답글로 둠",))
    principle = FEE_PRINCIPLE if kind in ("menu_change", "free_extra") and _FEE_REFUSAL.search(text) \
        else REQUESTS[kind]["principle"]
    return StanceDecision(EXPLAIN, request=kind, principle=principle, reasons=(
        f"요청 — {REQUESTS[kind]['name']}: '{req_word}'", f"거절 — '{refusal}'", "가게 과실일 수 있는 표현 없음",
        "요청 앞에 붙은 이유 없음"))


def judge_review(review) -> StanceDecision:
    """ReviewRecord(또는 text·negative_topics 를 가진 것)로 판정한다."""
    return judge_stance(getattr(review, "text", "") or "", negative_topics=getattr(review, "negative_topics", None))
