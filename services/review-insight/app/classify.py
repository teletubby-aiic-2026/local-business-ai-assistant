"""C3 리뷰 분류: HyperCLOVA X(HCX-005)로 주제·감정을 고르고, 규칙으로 결과를 검사합니다.

실행 방식 (팀 공통 APP_MODE)
- mock   : 모델을 부르지 않고 규칙 분류기만 씀 (키 없이 개발·시험)
- live   : HCX-005를 부르고, 결과를 data/replay 에 저장 (합성 리뷰만)
- replay : 저장해 둔 결과를 그대로 재생 (발표용). 저장본이 없는 리뷰는 규칙 분류로 대신함

모델 결과 검사 (통과 못 하면 고치거나 버림)
1. 주제는 주제 사전(topics.TOPICS)에 있는 것만
2. 근거 구절(evidence)은 리뷰 글에 그대로 있어야 함 → 없는 말을 지어낸 근거는 버림
3. 극성·감정 값은 정해진 값만, 감정은 주제 극성과 맞게 다시 계산
4. 요약에 금지 표현(원인 단정·탓하기·개인정보 모양)이 있으면 요약을 지움
5. 검사 뒤 남은 주제가 없는데 규칙 분류기는 주제를 찾으면 → 규칙 결과로 대신(rule_fallback)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app import storage
from app.models import POLARITIES, SENTIMENTS, Review, ReviewClassification, TopicHit
from app.examples import similar
from app.morph import content_morphemes
from app.topics import TOPICS, banned_in, locate_evidence, norm, rule_classify, sentiment_of

log = logging.getLogger("review_insight.classify")

ROOT = Path(__file__).resolve().parents[1]
REPLAY_FILE = ROOT / "data" / "replay" / "classify.json"           # 합성 리뷰 결과 (저장소에 올려도 됨)
RUNTIME_CACHE = ROOT / "data" / "runtime" / "classify_paste.json"   # 붙여넣은 리뷰 결과 (저장소에 안 올림). DB 설정이 있으면 review_labels 표
USAGE_LOG = ROOT / "logs" / "llm_usage.jsonl"                        # 규격 5.6: 호출마다 한 줄, 글은 남기지 않음 (저장소에 안 올림)
KST = timezone(timedelta(hours=9))
ENDPOINT = "https://clovastudio.stream.ntruss.com/v3/chat-completions/{model}"
PROMPT_VERSION = "c3-v7"   # 프롬프트를 바꾸면 올림 → 예전 재생본과 섞이지 않음
BATCH = 6
RETRY_BATCH = 2   # 한 번에 못 읽은 리뷰는 2건씩 한 번 더 물어봄

SYSTEM = """너는 음식점 리뷰를 주제별로 나누는 분류기다. 결과는 사장님이 반복되는 불만을 찾는 데 쓰인다.

[주제 사전] 아래 id만 쓴다.
{topics}

규칙
1. 리뷰에 나온 주제를 빠짐없이 모두 적고, 주제마다 polarity를 positive(칭찬) 또는 negative(불만)로 단다.
   한 문장에 주제가 둘이면 둘 다 적는다. '맛있어요', '맛은 있는데'처럼 짧은 맛 칭찬도 taste로 따로 적는다.
   (예: '양도 넉넉하고 맛도 좋아요' → portion positive, taste positive)
   (예: '가격에 비해 양이 적어요' → portion negative, price negative)
   (예: '배달이 빨라서 음료가 시원했어요' → delivery_time positive, temperature positive)
   (예: '이 가격에 이 양이면 가성비 최고' → price positive, portion positive)
   주제 낱말이 없어도 뜻으로 판단한다: '닭이 작아요', '몇 개 안 들어 있어요' → portion negative,
   '박스가 찌그러졌어요', '뚜껑이 열려 왔어요' → packaging negative, '늦게 온 데다 수저도 없었어요' → delivery_time negative, missing_item negative.
   음식을 두고 '미쳤어요', '최고', '존맛', 'ㄹㅇ', '왈왈'처럼 감탄하면 taste positive다.
   반어는 뜻대로 적는다 ('치킨이 걸어서 왔나 봐요', '정성이 대단하네요 40분' → 늦게 왔다는 불만).
2. 같은 주제에 칭찬과 불만을 함께 적는 것은 그 리뷰가 같은 점을 칭찬도 하고 불만도 할 때뿐이다.
   서로 다른 점이면 각각 맞는 주제로 나눈다. ('맛은 있는데 겉이 눅눅해요' → taste positive, texture negative)
3. 주제 사전에 맞는 주제가 없는 내용은 억지로 다른 주제에 넣지 말고 적지 않는다.
   '번창하세요', '또 시킬게요' 같은 인사·재주문 의사, 배달 기사님·배달앱(쿠폰·결제) 이야기는 주제가 아니다.
   service는 가게 직원·사장님의 응대, 요청사항 칸 부탁을 들어줬는지, 가게가 챙겨 준 덤·손편지에만 쓴다.
4. evidence에는 그 판단의 근거가 되는 구절을 리뷰 글에서 글자 그대로 복사한다. 바꿔 쓰거나 요약하지 않는다.
5. channel이 naver_place면 매장 방문 리뷰다. 매장에서 음식·음료가 늦게/빨리 나온 것과 웨이팅은 wait_time이고,
   delivery_time은 배달 주문이 늦게/빨리 온 것에만 쓴다.
   '포장해야겠다'처럼 포장 주문을 뜻하는 말은 packaging이 아니다. '국물 하나 안 샜어요'는 packaging 칭찬이다.
   냄새·간·단맛·싱거움은 taste, 바삭함·눅눅함·질김·면이 불음은 texture다.
   '따끈하게 도착했어요'는 temperature다 (빨리 왔다는 말이 없으면 delivery_time이 아니다).
   빠진 메뉴·덜 온 개수·다른 메뉴가 옴·추가 옵션 누락·수저 누락은 missing_item, 품절이라 다른 메뉴로 바꿔 보낸 것과 반찬·메뉴 구성은 menu다.
   요청사항 칸에 적은 부탁(맵기·간 조절, 빼 달라는 재료)을 안 들어준 것은 service negative다.
6. sentiment는 리뷰 전체의 느낌이며 positive, negative, mixed(칭찬과 불만이 함께), neutral 중 하나다. 별점보다 글을 따른다.
   주제가 없어도 '굿', '최고', '번창하세요', '😋😋'는 positive, '별로', '다신 안 시켜요'는 negative다.
   neutral은 '보통이에요', '그냥 그래요', '잘 받았습니다'처럼 칭찬도 불만도 아닐 때와 질문만 있을 때만 쓴다.
7. summary는 리뷰 내용을 20자 안팎 한 줄로 쓴다. 원인을 단정하거나(때문, 탓) 누군가를 탓하지 않는다.
8. 주어진 리뷰 순서대로 JSON 배열만 출력한다. 다른 글은 쓰지 않는다.
   출력하기 전에 리뷰마다 주제 사전 13개를 하나씩 대어 보며 빠진 주제가 없는지 확인한다 (특히 양·가격·온도·포장 누락).{hint_rule}
형식: [{{"review_id": "...", "sentiment": "...", "topics": [{{"topic": "...", "polarity": "...", "evidence": "..."}}], "summary": "..."}}]"""


HINT_RULE = """
9. [비슷한 예문]과 리뷰의 morphemes(형태소 분석), rule_guess(규칙 분류기 추측)는 참고 자료다 ('주제:+' 칭찬, '주제:-' 불만).
   리뷰 글 전체의 뜻과 다르면 따르지 않는다. 다만 rule_guess에 있는 주제를 빠뜨리지 않았는지는 꼭 확인한다.
   후보에 있어도 리뷰에 근거 구절이 없으면 적지 않고, 후보에 없어도 리뷰에 있으면 적는다."""

# 고정 예시 한 쌍: 모델이 JSON 배열 하나로만 답하게 (상권 비서 planner 의 _SHOT 과 같은 역할)
# 프롬프트용 주제 설명: 판단 단서까지 적는다 (규칙 분류기의 TOPICS 단어 목록과는 따로).
# c3-v7: 연습용(dev)에서 자주 놓친 '낱말 없는 주제'를 단서로 보탬. 시험용(test) 리뷰는 보지 않고 썼음.
PROMPT_TOPICS = {
    "portion": "양 — 양·개수·크기·곱빼기 ('작아요', '몇 개 안 들어', '손톱만 해요'는 불만, '두 끼 먹음'은 칭찬)",
    "taste": "맛 — 맛·간·냄새·신선함, 음식을 두고 한 감탄('미쳤어요', '존맛', 'ㄹㅇ', '인생 ○○')",
    "price": "가격 — 가격·가성비·할인·배달비 ('이 가격에 이 양', '혜자', '남는 게 있나요'는 칭찬)",
    "delivery_time": "배달 시간 — 배달 주문이 빨리/늦게 옴, 걸린 시간 ('○분 만에', '한참 기다렸다', 반어 '걸어서 왔나 봐요'). '도착했어요'만으로는 아님",
    "texture": "식감 — 바삭·눅눅·질김·퍽퍽·딱딱·쫄깃·촉촉, 면이 불음",
    "temperature": "음식 온도 — 식음·미지근·뜨끈·따끈·시원·얼음 녹음 ('식어서 딱딱'은 온도와 식감 둘 다)",
    "packaging": "포장 상태 — 샘·쏟아짐·터짐·찌그러짐·눌림·뚜껑, 포장이 꼼꼼함",
    "missing_item": "포장 누락 — 빠진 메뉴·덜 온 개수·다른 메뉴가 옴·추가 옵션이나 수저가 빠짐",
    "service": "응대 — 가게 직원·사장님 응대(전화 포함), 요청사항을 들어줌/안 들어줌, 가게가 챙겨 준 덤·손편지. 인사('번창하세요')는 아님",
    "hygiene": "위생 — 청결·이물질·머리카락·벌레, 기름·식기·매장이 깨끗함",
    "menu": "메뉴 구성 — 메뉴 종류·반찬 가짓수·세트 구성, 품절·메뉴 변경",
    "atmosphere": "매장 환경 — 자리·좌석·공간·인테리어·분위기·소음·주차·뷰 (방문)",
    "wait_time": "매장 대기 — 매장이나 포장 수령에서 기다린 시간, 웨이팅, 음식이 나온 속도 (방문·포장)",
}

# 고정 예시: 모델이 JSON 배열 하나로만 답하게 하고, 연습용에서 자주 틀린 유형을 새로 쓴 리뷰로 보여 준다
# (벤치마크 연습용·시험용 리뷰와 같은 글은 쓰지 않음 — 시험에서 확인)
SHOT_REVIEWS = [
    ("baemin", 2, "맛은 좋은데 포장 용기가 깨져서 국물이 다 흘렀어요", "mixed",
     [("taste", "positive", "맛은 좋은데"), ("packaging", "negative", "포장 용기가 깨져서 국물이 다 흘렀어요")], "맛은 좋으나 국물 샘"),
    ("coupangeats", 5, "이 값에 이만큼 주시면 남는 게 있나요 맛도 훌륭해요", "positive",
     [("price", "positive", "이 값에"), ("portion", "positive", "이만큼 주시면"), ("taste", "positive", "맛도 훌륭해요")], "가성비와 맛 칭찬"),
    ("baemin", 2, "만두가 손톱만 해요", "negative", [("portion", "negative", "만두가 손톱만 해요")], "만두 크기 불만"),
    ("yogiyo", 1, "피자가 순간이동이라도 했나 봐요 두 시간 걸렸네요", "negative",
     [("delivery_time", "negative", "두 시간 걸렸네요")], "배달 두 시간"),
    ("baemin", 4, "뜨끈하고 촉촉하게 도착했어요", "positive",
     [("temperature", "positive", "뜨끈하고"), ("texture", "positive", "촉촉하게")], "따뜻하고 촉촉함"),
    ("baemin", 1, "한참 기다렸더니 콜라도 빠져 있네요", "negative",
     [("delivery_time", "negative", "한참 기다렸더니"), ("missing_item", "negative", "콜라도 빠져 있네요")], "늦고 콜라 누락"),
    ("yogiyo", 2, "식어서 눅눅해요", "negative",
     [("temperature", "negative", "식어서"), ("texture", "negative", "눅눅해요")], "식고 눅눅함"),
    ("coupangeats", 5, "대박", "positive", [], "칭찬"),
    ("baemin", 5, "다음에도 여기서 시킬게요 사장님 대박 나세요", "positive", [], "재주문 의사"),
    ("baemin", 3, "그럭저럭이에요", "neutral", [], "보통"),
]
_SHOT_USER = ("[리뷰] 아래 JSON 배열의 리뷰를 모두 분류해서, 같은 순서의 JSON 배열 하나로만 답한다.\n"
              + json.dumps([{"review_id": f"ex_{i}", "channel": ch, "rating": rt, "text": tx}
                            for i, (ch, rt, tx, *_rest) in enumerate(SHOT_REVIEWS, 1)], ensure_ascii=False))
_SHOT_ANSWER = json.dumps([{"review_id": f"ex_{i}", "sentiment": se,
                            "topics": [{"topic": t, "polarity": p, "evidence": e} for t, p, e in tops], "summary": sm}
                           for i, (_ch, _rt, _tx, se, tops, sm) in enumerate(SHOT_REVIEWS, 1)], ensure_ascii=False)


def system_prompt(hints: bool = False) -> str:
    return SYSTEM.format(topics="\n".join(f"- {k}: {PROMPT_TOPICS.get(k) or v[0] + ' (' + v[1] + ')'}" for k, v in TOPICS.items()),
                         hint_rule=HINT_RULE if hints else "")


def rule_guess(r: Review) -> list[str]:
    """kiwi 규칙 분류기의 추측 ('missing_item:-' 처럼 짧게)."""
    c = rule_classify(r.review_id, r.text, r.rating, r.channel, use_kiwi=True)
    return [f"{h.topic}:{'+' if h.polarity == 'positive' else '-'}" for h in c.topics]


def _fmt_example(e: dict) -> str:
    return f'- "{e["text"]}" ({e["channel"]}) → {", ".join(e["topics"]) or "주제 없음"} ({e["sentiment"]})'


def _user(reviews: list[Review], hints: bool = False) -> str:
    rows = []
    for r in reviews:
        row = {"review_id": r.review_id, "channel": r.channel, "rating": r.rating, "text": r.text}
        if hints:
            row["morphemes"] = " ".join(content_morphemes(r.text))
            row["rule_guess"] = rule_guess(r)
        rows.append(row)
    parts = []
    if hints:
        picked = {}
        for r in reviews:
            for e in similar(r.text, limit=2):
                picked.setdefault(e["text"], e)
        if picked:
            parts.append("[비슷한 예문]\n" + "\n".join(_fmt_example(e) for e in list(picked.values())[:8]))
    parts.append("[리뷰] 아래 JSON 배열의 리뷰를 모두 분류해서, 같은 순서의 JSON 배열 하나로만 답한다.\n"
                 + json.dumps(rows, ensure_ascii=False, indent=1))
    return "\n\n".join(parts)


def cache_key(r: Review, model: str, hints: bool = False) -> str:
    return hashlib.sha256(f"{PROMPT_VERSION}|{model}|{'kiwi' if hints else 'plain'}|{r.channel}|{r.rating}|{norm(r.text)}".encode()).hexdigest()[:20]


def compare_with_rules(c: ReviewClassification, r: Review) -> None:
    """모델 결과와 kiwi 규칙 결과의 불만 주제가 다르면 경고로 남김 (사람이 볼 곳 표시, 결과는 바꾸지 않음)."""
    rule = rule_classify(r.review_id, r.text, r.rating, r.channel, use_kiwi=True)
    only_rule = sorted(set(rule.negative_topics) - set(c.negative_topics))
    only_model = sorted(set(c.negative_topics) - set(rule.negative_topics))
    if only_rule:
        c.warnings.append(f"규칙 비교: 규칙만 찾은 불만 {', '.join(only_rule)}")
    if only_model:
        c.warnings.append(f"규칙 비교: 모델만 찾은 불만 {', '.join(only_model)}")


# ── 모델 결과 검사 ──
def validate(item: dict, review: Review, *, method: str, model: str | None) -> ReviewClassification:
    warnings: list[str] = []
    hits: list[TopicHit] = []
    seen = set()
    for t in item.get("topics") or []:
        if not isinstance(t, dict):
            continue
        topic, pol, ev = t.get("topic"), t.get("polarity"), str(t.get("evidence") or "")
        if topic not in TOPICS:
            warnings.append(f"사전에 없는 주제 버림: {topic}")
            continue
        if pol not in POLARITIES:
            warnings.append(f"극성 값 오류 버림: {topic}/{pol}")
            continue
        quote = locate_evidence(ev, review.text)
        if quote is None:
            warnings.append(f"근거 구절이 리뷰에 없어 버림: {topic} '{ev[:30]}'")
            continue
        if (topic, pol) in seen:
            continue
        seen.add((topic, pol))
        hits.append(TopicHit(topic, pol, quote))   # 리뷰 글에 적힌 그대로의 구절로 저장

    sentiment = sentiment_of(hits, review.rating) if hits else (item.get("sentiment") if item.get("sentiment") in SENTIMENTS else "neutral")
    if item.get("sentiment") != sentiment:
        warnings.append(f"감정 값을 주제에 맞게 고침: {item.get('sentiment')} → {sentiment}")
    summary = str(item.get("summary") or "").strip()[:60] or None
    bad = banned_in(summary)
    if bad:
        warnings.append(f"요약에 금지 표현({', '.join(bad)})이 있어 지움")
        summary = None

    result = ReviewClassification(review.review_id, sentiment, hits, summary, method, model, warnings)
    if not hits:
        # 모델이 주제를 하나도 못 냈으면 규칙 결과로 대신한다. 벤치마크 v1 연습용(c3-v7)에서 '모델이 주제 없음이라 답하면 그대로 두기'를
        # 시험해 보니 F1 91.5% → 91.2%, 감정 95.8% → 95.3% 로 오히려 떨어짐 ('겉바속촉', '바삭함 미쳤다'를 규칙이 잡아 줌)
        rule = rule_classify(review.review_id, review.text, review.rating, review.channel)
        if rule.topics:
            rule.method, rule.model = "rule_fallback", model
            rule.warnings = warnings + ["모델 결과에 쓸 수 있는 주제가 없어 규칙 분류로 대신함"]
            return rule
    return result


def parse_items(content: str) -> list[dict]:
    """모델 답에서 리뷰 결과(dict)를 최대한 건져 냄.
    - 배열 하나 / 배열 여러 개 / 한 줄에 객체 하나씩(JSONL) / ```json 감싸기 모두 받음
    - 일부가 깨졌으면(따옴표 등) 깨진 객체만 버리고 나머지는 씀"""
    text = re.sub(r"```(?:json)?", "", content or "")
    dec = json.JSONDecoder()
    found: list = []
    i = 0
    while i < len(text):
        if text[i] not in "[{":
            i += 1
            continue
        try:
            value, end = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            if text[i] == "[":   # 배열 전체가 깨졌으면 안쪽 객체부터 다시 시도
                i += 1
                continue
            i = _skip_object(text, i)
            continue
        found.extend(value if isinstance(value, list) else [value])
        i = end
    return [x for x in found if isinstance(x, dict) and x.get("review_id")]


def _skip_object(text: str, i: int) -> int:
    """깨진 { ... } 하나를 괄호 짝으로 건너뜀 (문자열 안의 괄호는 무시)."""
    depth, in_str, esc = 0, False, False
    for j in range(i, len(text)):
        ch = text[j]
        if in_str:
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return j + 1
    return len(text)


class Classifier:
    def __init__(self, mode: str | None = None, api_key: str | None = None, model: str | None = None,
                 transport: httpx.BaseTransport | None = None, hints: bool | None = None):
        env = os.environ
        self.mode = (mode if mode is not None else env.get("APP_MODE", "mock")).strip().lower() or "mock"
        if self.mode not in ("mock", "live", "replay"):
            raise ValueError("APP_MODE는 mock, live, replay 중 하나여야 합니다")
        # 규격 9.1 이름(CLOVASTUDIO_API_KEY)과 상권 비서(PR #13) 이름(CLOVA_STUDIO_API_KEY)을 둘 다 받음
        if api_key is None:
            api_key = env.get("CLOVASTUDIO_API_KEY", "") or env.get("CLOVA_STUDIO_API_KEY", "")
        key = api_key.strip()
        self.api_key = key[7:].strip() if key.lower().startswith("bearer ") else key
        self.model = model or env.get("LLM_MODEL_REVIEW", "").strip() or env.get("CLOVA_MODEL_REVIEW", "").strip() or "HCX-005"
        self.timeout = float(env.get("LLM_TIMEOUT_SECONDS", "") or 20)
        # kiwi 결합 (상권 비서와 같은 방식): 모델 요청에 형태소·규칙 추측·비슷한 예문을 참고 자료로 넣고,
        # 결과를 규칙과 맞대 봄. REVIEW_KIWI_HINTS=off 로 끔 (비교 실험용)
        from app import morph
        want = hints if hints is not None else env.get("REVIEW_KIWI_HINTS", "on").strip().lower() not in ("off", "0", "false")
        self.hints = bool(want and morph.available())
        if self.mode == "live" and not self.api_key:
            raise ValueError("APP_MODE=live 에는 .env 의 CLOVASTUDIO_API_KEY 가 필요합니다")
        self.transport = transport
        self._lock = threading.Lock()

    # ── 저장본 ──
    @staticmethod
    def _load(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, path: Path, new: dict) -> None:
        with self._lock:
            data = self._load(path)
            data.update(new)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    # 붙여넣은 리뷰의 결과 저장소: 기본은 위의 파일, DB_HOST 가 있으면 DB (같은 글이면 방문자와 상관없이 같은 결과)
    def _runtime_get(self, keys: set[str]) -> dict:
        db = storage.database()
        if db is None:
            return self._load(RUNTIME_CACHE)
        try:
            with storage.guarded():
                return db.labels.get_many(keys)
        except storage.StorageUnavailable as exc:      # 저장된 결과는 없는 셈 치고 새로 분류한다 (화면은 계속 뜸)
            log.warning("분류 결과 저장소를 읽지 못함: %s", exc)
            return {}

    def _runtime_put(self, new: dict) -> None:
        db = storage.database()
        if db is None:
            self._save(RUNTIME_CACHE, new)
            return
        try:
            with storage.guarded():
                db.labels.put_many(new, prompt_version=PROMPT_VERSION, model=self.model)
        except storage.StorageUnavailable as exc:      # 못 남겨도 이번 결과는 그대로 쓴다
            log.warning("분류 결과를 저장하지 못함: %s", exc)

    # ── 모델 호출 ──
    def _call(self, batch: list[Review]) -> list:
        body = {"messages": [{"role": "system", "content": system_prompt(self.hints)},
                             {"role": "user", "content": _SHOT_USER}, {"role": "assistant", "content": _SHOT_ANSWER},
                             {"role": "user", "content": _user(batch, self.hints)}],
                "topP": 0.8, "topK": 0, "temperature": 0.1, "maxTokens": 300 * len(batch) + 200,
                "repetitionPenalty": 1.0, "seed": 0, "includeAiFilters": True}
        # 규격 5.6 재시도: 429는 잠깐 기다렸다 1번, 5xx·시간 초과는 1번, 400·401·403은 재시도하지 않음
        resp, status = None, "ok"
        t0 = time.perf_counter()
        for attempt in range(2):
            try:
                with httpx.Client(timeout=self.timeout, transport=self.transport) as c:
                    resp = c.post(ENDPOINT.format(model=self.model), json=body, headers={
                        "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                        "X-NCP-CLOVASTUDIO-REQUEST-ID": uuid.uuid4().hex})
            except httpx.TimeoutException:
                resp, status = None, "LLM_TIMEOUT"
                continue
            if resp.status_code == 429 and attempt == 0:
                time.sleep(min(float(resp.headers.get("retry-after", "2") or 2), 5))
                continue
            if resp.status_code >= 500 and attempt == 0:
                continue
            break
        latency = int((time.perf_counter() - t0) * 1000)
        usage = {}
        if resp is not None:
            if resp.status_code == 200:
                status = "ok"
                result = (resp.json() or {}).get("result") or {}
                usage = result.get("usage") or {}
            else:
                status = "LLM_RATE_LIMITED" if resp.status_code == 429 else "LLM_UPSTREAM_ERROR"
        self._log_usage(batch, resp.status_code if resp is not None else None, status, usage, latency)
        if status != "ok":
            raise RuntimeError(f"CLOVA Studio {status} {resp.status_code if resp is not None else ''}".strip())   # 본문은 남기지 않음
        return parse_items((result.get("message") or {}).get("content") or "")

    def _log_usage(self, batch, http_status, status, usage, latency_ms) -> None:
        """규격 5.6 사용량 기록. 프롬프트·응답 글은 남기지 않음."""
        row = {"ts": datetime.now(KST).isoformat(timespec="seconds"), "purpose": "review_classify", "model": self.model,
               "mode": self.mode, "http_status": http_status, "status": status,
               "prompt_tokens": usage.get("promptTokens"), "completion_tokens": usage.get("completionTokens"),
               "total_tokens": usage.get("totalTokens"), "latency_ms": latency_ms,
               "review_id": batch[0].review_id if len(batch) == 1 else None, "review_ids": [r.review_id for r in batch]}
        try:
            USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with USAGE_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("사용량 기록 실패: %s", e)

    def _ask(self, batch: list[Review]) -> dict:
        try:
            ids = {r.review_id for r in batch}
            return {str(x["review_id"]): x for x in self._call(batch) if str(x["review_id"]) in ids}
        except Exception as e:
            log.warning("리뷰 분류 모델 호출 실패 (%d건): %s", len(batch), e)
            return {}

    def classify(self, reviews: list[Review]) -> list[ReviewClassification]:
        if self.mode == "mock":
            return [rule_classify(r.review_id, r.text, r.rating, r.channel) for r in reviews]

        replay = self._load(REPLAY_FILE)
        runtime = self._runtime_get({cache_key(r, self.model, self.hints) for r in reviews if r.input_method != "sample"})
        out: dict[str, ReviewClassification] = {}
        todo: list[Review] = []
        for r in reviews:
            saved = (replay if r.input_method == "sample" else runtime).get(cache_key(r, self.model, self.hints))
            if saved is not None:
                out[r.review_id] = validate({**saved, "review_id": r.review_id}, r, method="replay", model=self.model)
                if self.hints:
                    compare_with_rules(out[r.review_id], r)
            elif self.mode == "live":
                todo.append(r)
            else:   # replay 인데 저장본 없음
                c = rule_classify(r.review_id, r.text, r.rating, r.channel)
                c.method, c.warnings = "rule_fallback", ["재생할 저장본이 없어 규칙 분류로 대신함"]
                out[r.review_id] = c

        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            items = self._ask(batch)
            missing = [r for r in batch if r.review_id not in items]
            for k in range(0, len(missing), RETRY_BATCH):     # 못 읽은 리뷰만 작게 나눠 한 번 더
                items.update(self._ask(missing[k:k + RETRY_BATCH]))
            new_replay, new_runtime = {}, {}
            for r in batch:
                item = items.get(r.review_id)
                if item is None:
                    c = rule_classify(r.review_id, r.text, r.rating, r.channel)
                    c.method, c.warnings = "rule_fallback", ["모델 응답에 이 리뷰가 없어 규칙 분류로 대신함"]
                    out[r.review_id] = c
                    continue
                out[r.review_id] = validate(item, r, method="model", model=self.model)
                if self.hints:
                    compare_with_rules(out[r.review_id], r)
                keep = {k: item.get(k) for k in ("sentiment", "topics", "summary")}
                (new_replay if r.input_method == "sample" else new_runtime)[cache_key(r, self.model, self.hints)] = keep
            if new_replay:
                self._save(REPLAY_FILE, new_replay)
            if new_runtime:
                self._runtime_put(new_runtime)
        return [out[r.review_id] for r in reviews]
