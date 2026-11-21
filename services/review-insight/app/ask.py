"""고객응대 질문 답하기 (POST /api/review-insight/ask, 11/21).

통합 화면의 'AI에게 묻기' 서랍은 상권 질문만 상권 서비스가 자료로 답하고, 리뷰·불만·답글 질문에는 늘 같은 안내 두 줄을 냈다.
여기서는 상권 비서(services/market-analysis/app/assistant)와 같은 순서로 답한다:

  ① 질문 나누기 (parse)        : 무엇을 묻는지(intent) + 주제(포장 누락·맛…) + 배달앱 채널을 규칙으로 고른다
  ② 근거 카드 만들기 (cards)    : 이 가게의 리뷰·분류·응대 기록에서 그 질문에 필요한 숫자만 코드로 세어 F1, F2… 카드로 만든다
  ③ 답 쓰기 (answer)           : mock·키 없음이면 질문 종류별 틀 문장. live 면 HCX-005 가 카드만 보고 쓴다
  ④ 답 점검 (check_answer)     : 모델 답의 숫자는 모두 카드에 있어야 하고, [F#] 는 이번 카드여야 하며, 원인 단정·탓하는 말이 없어야 한다.
                                 못 넘으면 틀 문장으로 답한다 (method=template, checks 에 이유)

숫자는 모두 코드가 센 것이다. 모델은 문장만 다듬는다. 합성 리뷰가 지난 날짜에 몰려 있어 '이번 주·지난주'는 오늘이 아니라
마지막 리뷰가 들어온 날(기준일)로 자르고, 답과 카드에 그 날짜를 적는다.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app import care, cluster, service
from app.sources.chat import Chat, ChatError
from app.topics import TOPICS, topic_name

CHANNEL_KO = {"baemin": "배민", "coupangeats": "쿠팡이츠", "yogiyo": "요기요", "naver_place": "네이버 플레이스", "web": "문의 페이지"}
SOURCE_TITLE = "리뷰 분석 서비스 (이 가게 리뷰·답글 기록)"

# ── ① 질문 나누기 ──────────────────────────────────────────────
# 주제: 앞에 있을수록 먼저 (포장 누락 > 포장 상태, 응대 점수는 주제 '응대'가 아님)
_TOPIC_RX = [
    ("missing_item", r"누락|빠졌|빠진|빠져|안왔|덜왔|오배송|잘못왔"),
    ("packaging", r"포장(상태|이|불량|터|샜|새)|샜|새서|흘렀|흘러|쏟아|뚜껑"),
    ("delivery_time", r"배달(시간|이늦|늦|느|오래)|늦게와|늦게왔|오래걸|늦게도착"),
    ("temperature", r"식어|식었|식은|미지근|온도|차가"),
    ("texture", r"식감|눅눅|바삭|질기|질겨|퍽퍽|딱딱"),
    ("portion", r"양(이|은|도|적|많|부족|이적)|양$|양에대|양관련"),
    ("price", r"가격|가성비|비싸|비싼"),
    ("hygiene", r"위생|머리카락|이물질|벌레|청결|지저분"),
    ("service", r"(?<!응대점)(친절|불친절|직원|태도)|응대(?!점수)(?!를)(?!잘)"),
    ("wait_time", r"웨이팅|매장대기|대기시간|오래기다"),
    ("atmosphere", r"분위기|좌석|매장환경|인테리어|시끄|자리가"),
    ("menu", r"메뉴구성|반찬"),
    ("taste", r"맛(?!집)|짜|싱거|간이"),
]
_CHANNEL_RX = [("baemin", r"배민|배달의민족"), ("coupangeats", r"쿠팡"), ("yogiyo", r"요기요"), ("naver_place", r"네이버|플레이스")]
# 질문 종류 (위에서부터 먼저). 주제·채널은 따로 골라 거르기로 쓴다
_INTENT_RX = [
    ("capture", r"(캡처|캡쳐|스크린샷).*(어떻게|방법|올려|올리|넣|읽)"),
    ("howto", r"억울|악플|진상|테러|블랙|(답글|답|응대|대처|대응).*(어떻게|방법|하는법|요령|팁|노하우|잘쓰|잘달|잘하|써야|달아야|해야)|어떻게(답|대처|대응)"),
    ("score", r"응대점수|점수|성적"),
    ("unanswered", r"답글(을|이)?(안|못|없)|미답|안단|안달|밀린|기한|늦은답|답안한|답못한|답해야|답할"),
    ("inquiry", r"문의|알레르기|손님질문"),
    ("rating", r"별점|평점|평균|몇점|만점"),
    ("channel", r"채널|앱별|앱마다|배달앱별|플랫폼|어느앱|어디가(제일|가장)?(많|좋|나)"),
    ("recent", r"최근리뷰|새리뷰|새로들어|방금|오늘들어|오늘리뷰|최신"),
    ("praise", r"칭찬|좋아하|좋아해|만족|잘한|인기|호평|좋은리뷰|좋다고|맛있다|맛있대"),
    ("time", r"언제|몇시|시간대|저녁|점심|주말|평일|요일"),
    ("trend", r"늘었|줄었|늘어|줄어|증가|감소|지난주|저번주|이번주|요즘|변화|추세|많아졌|적어졌|나아졌|좋아졌"),
    ("complaints", r"불만|문제|컴플레인|클레임|안좋|나쁜|별로|제일많|가장많|순위|1위"),
]


@dataclass
class Question:
    text: str
    intent: str
    topic: str | None = None
    channels: list[str] = field(default_factory=list)


def _squash(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", (text or "").lower())


def parse(text: str) -> Question:
    c = _squash(text)
    topic = next((t for t, rx in _TOPIC_RX if re.search(rx, c)), None)
    channels = [ch for ch, rx in _CHANNEL_RX if re.search(rx, c)]
    intent = next((i for i, rx in _INTENT_RX if re.search(rx, c)), None)
    if intent is None:
        intent = "channel" if len(channels) >= 2 else ("topic" if topic else "overview")
    if intent == "channel" and not channels and re.search(r"차이", c) is None and not re.search(_INTENT_RX[6][1], c):
        intent = "overview"
    if intent in ("complaints", "praise") and topic:      # "포장 누락 불만 있어?" → 그 주제 자세히
        intent = "topic"
    if len(channels) >= 2 and intent in ("overview", "rating", "complaints", "topic", "trend"):
        intent = "channel"
    return Question(text=text, intent=intent, topic=topic, channels=channels)


# ── ② 근거 카드 ──────────────────────────────────────────────────
@dataclass
class Data:
    tl: service.Timeline
    now: datetime
    rows: list[dict]
    classes: dict
    base_day: datetime      # 기준일 (마지막 리뷰가 들어온 날의 끝)
    classifier: object = None
    by_id: dict = field(default_factory=dict)

    @classmethod
    def load(cls, classifier, store_id: str, visitor_id: str | None, now: datetime) -> "Data":
        tl = service.Timeline(classifier, store_id, visitor_id)
        rows = [r for r in tl.rows if tl.arrival(r) <= now]
        last = max((tl.arrival(r) for r in rows), default=now)
        end = last.replace(hour=23, minute=59, second=59, microsecond=0)
        return cls(tl=tl, now=now, rows=rows, classes={c.review_id: c for c in tl.classes}, base_day=end,
                   classifier=classifier, by_id={r.review_id: r for r in tl.reviews})

    def neg(self, r: dict) -> list[str]:
        c = self.classes.get(r["review_id"])
        return list(c.negative_topics) if c else []

    def pos(self, r: dict) -> list[str]:
        c = self.classes.get(r["review_id"])
        return [h.topic for h in c.topics if h.polarity == "positive"] if c else []

    def quote(self, r: dict, topic: str | None, polarity: str) -> str:
        c = self.classes.get(r["review_id"])
        for h in (c.topics if c else []):
            if h.polarity == polarity and (topic is None or h.topic == topic) and h.evidence:
                return h.evidence
        return r["text"][:40]

    def band(self, r: dict) -> str | None:
        """리뷰 분석 화면의 불만 묶음과 같은 규칙 (cluster.time_band·has_order_time): 손님이 쓴 시각을 아는 리뷰만."""
        review = self.by_id.get(r["review_id"])
        return cluster.time_band(review.created_at) if review is not None and cluster.has_order_time(review) else None


def _card(n: int, topic: str, text: str, values: list[dict] | None = None, warnings: list[str] | None = None,
          period: str | None = None) -> dict:
    return {"id": f"F{n}", "topic": topic, "status": "available", "text": text, "values": values or [],
            "warnings": warnings or [], "source_ref": {"source_title": SOURCE_TITLE, "data_version": period}}


def _v(label: str, value, unit: str = "건", share: float | None = None, group: str | None = None) -> dict:
    out = {"label": label, "value": value, "unit": unit}
    if group:
        out["group"] = group
    if share is not None:
        out["share_percent"] = share
    return out


def _num(x: float) -> float | int:
    """30.0 → 30, 3.80 → 3.8 (답 글과 카드가 같은 모양이 되게)."""
    x = round(x, 2)
    return int(x) if float(x).is_integer() else x


def _pct(a: int, b: int) -> float | int | None:
    return _num(a * 100 / b) if b else None


def _d(t: datetime) -> str:
    return f"{t.month}/{t.day}"


def _period(d: Data) -> str:
    if not d.rows:
        return ""
    first = min(d.tl.arrival(r) for r in d.rows)
    return f"{first.date().isoformat()}~{d.base_day.date().isoformat()}"


def _josa(word: str, pair: str) -> str:
    """'포장 누락' + '이/가' → '포장 누락이'. 받침으로 고른다."""
    last = next((ch for ch in reversed(word) if "가" <= ch <= "힣"), None)
    has = last is not None and (ord(last) - 0xAC00) % 28 != 0
    a, b = pair.split("/")
    return word + (a if has else b)


def build(q: Question, d: Data, store_id: str, visitor_id: str | None) -> tuple[list[dict], str, list[str]]:
    """카드들, 틀 답(문장마다 [F#]), 다음 질문 추천. 숫자는 모두 여기서 센다."""
    rows = [r for r in d.rows if not q.channels or r.get("channel") in q.channels]
    period = _period(d)
    cards: list[dict] = []

    def add(topic, text, values=None, warnings=None) -> str:
        cards.append(_card(len(cards) + 1, topic, text, values, warnings, period))
        return cards[-1]["id"]

    chan = "·".join(CHANNEL_KO[c] for c in q.channels)
    where = f"{chan} " if chan and q.intent != "channel" else ""
    total = len(rows)
    complaints = [r for r in rows if d.neg(r)]
    if not total:
        f = add("리뷰 현황", f"{where}리뷰가 아직 없어요.", [_v("리뷰", 0)])
        return cards, f"{where}리뷰가 아직 없어요 [{f}]. 리뷰 분석의 '리뷰 넣기'에서 리뷰를 넣으면 바로 세어 드릴게요.", \
            ["리뷰 캡처는 어떻게 올려?"]

    def topic_counter(subset, polarity="neg") -> Counter:
        cnt: Counter = Counter()
        for r in subset:
            cnt.update(set(d.neg(r) if polarity == "neg" else d.pos(r)))
        return Counter({k: cnt[k] for k in TOPICS if k in cnt})      # 건수가 같으면 주제 사전 순서 (답이 실행마다 바뀌지 않게)

    def time_card(subset, label) -> tuple[str, str | None, int]:
        bands = Counter(b for b in (d.band(r) for r in subset) if b)
        timed = sum(bands.values())
        vals = [_v(b, n, share=_pct(n, timed)) for b, n in sorted(bands.items(), key=lambda kv: -kv[1])]
        f = add("시간대", f"{label} {timed}건의 들어온 시간대예요.", vals,
                ["붙여넣은 리뷰처럼 쓴 시각을 모르는 리뷰는 빼고 셌어요."] if timed < len(subset) else None)
        top = max(bands.items(), key=lambda kv: kv[1]) if bands else None
        return f, (top[0] if top else None), (top[1] if top else 0)

    def weeks(subset):
        end = d.base_day
        cur = [r for r in subset if end - timedelta(days=7) < d.tl.arrival(r) <= end]
        prev = [r for r in subset if end - timedelta(days=14) < d.tl.arrival(r) <= end - timedelta(days=7)]
        return cur, prev, (end - timedelta(days=6)), end

    nxt = {"complaints": ["그 불만 언제 많이 와?", "지난주보다 불만 늘었어?", "답글 안 단 리뷰 몇 개야?"]}
    intent = q.intent

    if intent == "capture":
        f = add("리뷰 현황", f"지금 저장된 리뷰는 {total}건이에요.", [_v("리뷰", total)])
        return cards, ("리뷰 분석 → '리뷰 넣기' 탭에서 배달앱 리뷰 화면 캡처를 올리면 글자와 별점을 읽어 후보로 보여 드려요. "
                       f"확인하고 저장하면 바로 분석에 들어가요. 지금 저장된 리뷰는 {total}건이에요 [{f}]."), \
            ["불만 리뷰 제일 많은 게 뭐야?", "답글 안 단 리뷰 몇 개야?"]

    if intent == "score":
        st = d.tl.at(d.now)
        vals = [_v("응대 점수", st["score"], "점"), _v("답글 기다리는 불만", st["pending_count"]),
                _v("기한 넘긴 불만", st["overdue_count"])]
        f = add("응대 점수", f"응대 점수는 {st['score']}점이에요 (100점에서 깎고 더하는 규칙 계산).", vals)
        reasons = [x for x in st["reasons"] if x.get("delta")][-3:]
        lines = [f"응대 점수는 {st['score']}점이에요 [{f}]."]
        if reasons:
            g = add("점수 이유", "최근 점수가 바뀐 이유예요.", [_v(x["message"], x["delta"], "점") for x in reasons])
            lines.append(f"최근 바뀐 이유는 {reasons[-1]['message']}이에요 [{g}].")
        if st["overdue_count"]:
            lines.append(f"기한을 넘긴 불만 {st['overdue_count']}건에 답글을 달면 점수가 회복돼요 [{f}].")
        return cards, " ".join(lines), ["답글 안 단 리뷰 몇 개야?", "불만 리뷰 제일 많은 게 뭐야?"]

    if intent == "unanswered":
        st = d.tl.at(d.now)
        pend = st["pending"]
        late = [p for p in pend if p["overdue"]]
        vals = [_v("답글 기다리는 불만", len(pend)), _v("기한 넘김", len(late)),
                _v("기한 없는 지난 불만(답글 없음)", st.get("untimed_unanswered", 0))]
        f = add("답글 대기", f"답글 기한(불만 리뷰 {st['policy']['sla_minutes']}분, 바쁜 시간 제외)으로 센 숫자예요.", vals)
        lines = [f"답글을 기다리는 불만은 {len(pend)}건이고, 그중 기한을 넘긴 것이 {len(late)}건이에요 [{f}]." if pend else
                 f"지금 답글 기한이 걸린 불만은 없어요 [{f}]."]
        if st.get("untimed_unanswered"):
            lines.append(f"기한이 없는 지난 불만 중 답글이 없는 것은 {st['untimed_unanswered']}건이에요 [{f}].")
        if pend:
            first = sorted(pend, key=lambda p: p["remaining_seconds"])[0]
            g = add("가장 급한 불만", f"'{first['text']}'", [_v(", ".join(first["topic_names"]) or "불만", 1)])
            lines.append(f"가장 급한 건 '{', '.join(first['topic_names'])}' 불만이에요 [{g}].")
        lines.append("추천 카드에서 답글 초안을 만들어 승인하면 기록돼요.")
        return cards, " ".join(lines), ["억울한 별점 답글은 어떻게 달아?", "응대 점수 몇 점이야?"]

    if intent == "inquiry":
        box = care.inbox(d.classifier, store_id, visitor_id, d.now, kind="inquiry", limit=200)
        items = (box or {}).get("items", [])
        open_ = [x for x in items if x.get("open")]
        allergy = [x for x in items if "allergy" in (x.get("needs_owner") or [])]
        vals = [_v("손님 문의", len(items)), _v("답 안 한 문의", len(open_)), _v("알레르기 문의", len(allergy)),
                _v("자동으로 답한 문의", ((box or {}).get("summary") or {}).get("auto_answered", 0))]
        f = add("손님 문의", "문의 페이지로 들어온 손님 질문이에요.", vals)
        lines = [f"손님 문의는 {len(items)}건, 그중 답하지 않은 것이 {len(open_)}건이에요 [{f}]."]
        if allergy:
            lines.append(f"알레르기 문의가 {len(allergy)}건 있어요 [{f}]. 알레르기는 재료를 직접 확인하고 답해 주세요.")
        if not items:
            lines = [f"아직 들어온 손님 문의가 없어요 [{f}]."]
        return cards, " ".join(lines), ["답글 안 단 리뷰 몇 개야?", "불만 리뷰 제일 많은 게 뭐야?"]

    if intent == "rating":
        rated = [r for r in rows if r.get("rating")]
        avg = _num(sum(r["rating"] for r in rated) / len(rated)) if rated else None
        dist = Counter(r["rating"] for r in rated)
        vals = [_v("평균 별점", avg, "점"), _v("별점 있는 리뷰", len(rated))] + \
               [_v(f"{s}점", dist.get(s, 0), share=_pct(dist.get(s, 0), len(rated))) for s in (5, 4, 3, 2, 1)]
        f = add("별점", f"{where}별점이 있는 리뷰 {len(rated)}건의 별점이에요.", vals)
        low = dist.get(1, 0) + dist.get(2, 0)
        lines = [f"{where}평균 별점은 {avg}점이에요 (별점 있는 리뷰 {len(rated)}건) [{f}].",
                 f"5점이 {dist.get(5, 0)}건으로 가장 많고, 1~2점은 {low}건이에요 [{f}]."]
        cur, prev, s, e = weeks(rated)
        if cur and prev:
            a, b = _num(sum(r["rating"] for r in cur) / len(cur)), _num(sum(r["rating"] for r in prev) / len(prev))
            g = add("주간 별점", f"{_d(s)}~{_d(e)}(최근 7일)와 그 앞 7일 평균 별점이에요.",
                    [_v("최근 7일 평균", a, "점"), _v("그 앞 7일 평균", b, "점")])
            lines.append(f"최근 7일({_d(s)}~{_d(e)}) 평균은 {a}점, 그 앞 7일은 {b}점이에요 [{g}].")
        return cards, " ".join(lines), ["배민이랑 쿠팡 리뷰 차이 있어?", "불만 리뷰 제일 많은 게 뭐야?"]

    if intent == "channel":
        chans = q.channels or sorted({r["channel"] for r in d.rows if r.get("channel")})
        vals, lines = [], []
        for ch in chans:
            sub = [r for r in d.rows if r.get("channel") == ch]
            if not sub:
                continue
            rated = [r["rating"] for r in sub if r.get("rating")]
            avg = _num(sum(rated) / len(rated)) if rated else None
            comp = sum(1 for r in sub if d.neg(r))
            name = CHANNEL_KO.get(ch, ch)
            vals += [_v("리뷰", len(sub), group=name), _v("평균 별점", avg, "점", group=name),
                     _v("불만 비율", _pct(comp, len(sub)), "%", group=name)]
            top = topic_counter(sub).most_common(1)
            lines.append((ch, len(sub), avg, comp, _pct(comp, len(sub)), top[0] if top else None))
        f = add("채널 비교", "배달앱(채널)별 리뷰 수·평균 별점·불만 비율이에요.", vals)
        out = []
        for ch, n, avg, comp, rate, top in lines:
            s = f"{CHANNEL_KO.get(ch, ch)}: 리뷰 {n}건, 평균 {avg}점, 불만 {comp}건({rate}%)"
            if top:
                s += f", 많은 불만은 '{topic_name(top[0])}' {top[1]}건"
            out.append(f"- {s} [{f}]")
        worst = max(lines, key=lambda x: x[4] or 0) if lines else None
        wn = CHANNEL_KO.get(worst[0], worst[0]) if worst else ""
        head = (f"채널별로 보면 불만 비율이 가장 높은 곳은 {wn}({worst[4]}%)" + ("이에요" if _josa(wn, "이/가").endswith("이") else "예요")
                + f" [{f}].") if worst else ""
        return cards, "\n".join([head, *out]), ["별점 평균 몇 점이야?", "불만 리뷰 제일 많은 게 뭐야?"]

    if intent == "recent":
        last = sorted(rows, key=lambda r: d.tl.arrival(r), reverse=True)[:3]
        vals = [_v(f"{_d(d.tl.arrival(r))} {CHANNEL_KO.get(r.get('channel'), '')}".strip(), r.get("rating") or 0, "점") for r in last]
        f = add("최근 리뷰", "가장 최근에 들어온 리뷰 3건이에요.", vals)
        out = [f"가장 최근 리뷰 {len(last)}건이에요 [{f}]."]
        for r in last:
            kind = "불만(" + ", ".join(topic_name(t) for t in d.neg(r)) + ")" if d.neg(r) else "칭찬·기타"
            out.append(f"- {_d(d.tl.arrival(r))} {CHANNEL_KO.get(r.get('channel'), '')} {r.get('rating') or '-'}점 · {kind}: "
                       f"\"{r['text'][:40]}\"")
        return cards, "\n".join(out), ["답글 안 단 리뷰 몇 개야?", "불만 리뷰 제일 많은 게 뭐야?"]

    if intent == "praise":
        cnt = topic_counter(rows, "pos")
        praised = [r for r in rows if d.pos(r) and not d.neg(r)]
        menus = Counter()
        for m in (service.store(store_id).get("menu") or []):
            name = m if isinstance(m, str) else m.get("name", "")
            if name:
                menus[name] = sum(1 for r in praised if name.replace(" ", "") in r["text"].replace(" ", ""))
        menus = Counter({k: v for k, v in menus.items() if v})
        f = add("칭찬 주제", f"{where}칭찬 리뷰 {len(praised)}건에서 칭찬한 주제예요.",
                [_v(topic_name(t), n) for t, n in cnt.most_common(5)])
        lines = [f"{where}칭찬 리뷰는 {len(praised)}건이에요 [{f}]."]
        if cnt:
            t, n = cnt.most_common(1)[0]
            lines.append(f"가장 많이 칭찬한 건 '{topic_name(t)}'({n}건)이에요 [{f}].")
        if menus:
            g = add("칭찬 메뉴", "칭찬 리뷰에 이름이 나온 메뉴예요.", [_v(m, n) for m, n in menus.most_common(3)])
            m, n = menus.most_common(1)[0]
            lines.append(f"메뉴로는 {_josa(f"'{m}'", '이/가')} {n}건으로 가장 많이 나왔어요 [{g}].")
        if praised:
            r = praised[-1]
            lines.append(f"예: \"{d.quote(r, None, 'positive')}\"")
        return cards, " ".join(lines), ["불만 리뷰 제일 많은 게 뭐야?", "칭찬 많은 메뉴로 홍보하면 어때?"]

    # 주제 하나 (또는 전체 불만)를 보는 질문: complaints · topic · time · trend · howto · overview
    t = q.topic
    subset = [r for r in rows if t in d.neg(r)] if t else complaints
    label = f"'{topic_name(t)}' 불만" if t else "불만 리뷰"

    if intent == "time":
        if not subset:
            f = add("불만 건수", f"{where}{_josa(label, '이/가')} 없어요.", [_v(label, 0)])
            return cards, f"{where}{_josa(label, '은/는')} 아직 없어요 [{f}].", ["불만 리뷰 제일 많은 게 뭐야?"]
        f, band, n = time_card(subset, f"{where}{label}")
        timed = sum(v["value"] for v in cards[-1]["values"])
        line = f"{where}{label} {len(subset)}건 중 {band}에 {n}건으로 가장 많았어요 [{f}]." if band else \
            f"{where}{label}의 들어온 시각을 알 수 있는 리뷰가 없어요 [{f}]."
        tip = " 그 시간대 포장·확인 순서를 한 번 점검해 보세요." if band and n * 100 >= timed * 50 \
            and t in (None, "missing_item", "packaging") else ""      # 맛·양 불만에 '포장 순서'는 맞지 않다
        return cards, line + tip, ["지난주보다 늘었어?", "그 불만 답글은 어떻게 달아?"]

    if intent == "trend":
        cur, prev, s, e = weeks(subset)
        cur_all, prev_all, _, _ = weeks(rows)
        vals = [_v(f"최근 7일 ({_d(s)}~{_d(e)})", len(cur)), _v("그 앞 7일", len(prev)),
                _v("최근 7일 전체 리뷰", len(cur_all)), _v("그 앞 7일 전체 리뷰", len(prev_all))]
        f = add("주간 변화", f"기준일 {_d(e)}(마지막 리뷰가 들어온 날)까지 7일씩 나눠 센 {where}{label}예요.", vals,
                ["합성 리뷰는 지난 날짜에 있어 오늘이 아니라 마지막 리뷰 날짜로 잘랐어요."])
        diff = len(cur) - len(prev)
        word = "늘었어요" if diff > 0 else "줄었어요" if diff < 0 else "같아요"
        lines = [f"최근 7일({_d(s)}~{_d(e)}) {where}{_josa(label, '은/는')} {len(cur)}건, 그 앞 7일은 {len(prev)}건으로 "
                 f"{abs(diff)}건 {word} [{f}]." if diff else
                 f"최근 7일({_d(s)}~{_d(e)}) {where}{_josa(label, '은/는')} {len(cur)}건으로 그 앞 7일과 같아요 [{f}]."]
        if not t:
            cc, pc = topic_counter(cur), topic_counter(prev)
            order = {k: i for i, k in enumerate(TOPICS)}
            moved = sorted(((k, cc.get(k, 0) - pc.get(k, 0)) for k in set(cc) | set(pc)), key=lambda kv: (-kv[1], order.get(kv[0], 99)))
            if moved and moved[0][1] > 0:
                k, n = moved[0]
                g = add("늘어난 주제", "최근 7일에 그 앞 7일보다 많이 들어온 불만 주제예요.",
                        [_v(topic_name(k), cc.get(k, 0), group="최근 7일"), _v(topic_name(k), pc.get(k, 0), group="그 앞 7일")])
                lines.append(f"가장 많이 늘어난 건 '{topic_name(k)}'({pc.get(k, 0)}건 → {cc.get(k, 0)}건)이에요 [{g}].")
        return cards, " ".join(lines), ["그 불만 언제 많이 와?", "답글 안 단 리뷰 몇 개야?"]

    if intent == "howto":
        cnt = topic_counter(complaints)
        f = add("불만 현황", f"{where}불만 리뷰 {len(complaints)}건의 주제별 건수예요.", [_v(topic_name(k), n) for k, n in cnt.most_common(5)])
        c = _squash(q.text)
        if re.search(r"억울|악플|진상|테러|블랙", c):
            lines = ["가게 잘못이 아닌 별점에는 사과를 길게 하기보다, 사실과 가게 원칙을 짧고 담담하게 쓰는 답글이 좋아요.",
                     "감정적인 말·손님 탓·주문 정보 공개는 빼고, 다른 손님이 읽어도 믿음이 가게 써 주세요."]
        else:
            lines = ["답글은 ① 불편에 대한 짧은 사과 ② 확인한 사실 ③ 앞으로 바꿀 점 한 가지 순서가 읽기 좋아요.",
                     "할인·보상은 가게 원칙에 있을 때만 약속해 주세요."]
        if cnt:
            k, n = cnt.most_common(1)[0]
            lines.append(f"지금 가장 많은 불만은 '{topic_name(k)}'({n}건)이라 그 주제 답글부터 맞춰 두면 좋아요 [{f}].")
        lines.append("추천 카드에서 답글을 만들면 억울한 리뷰는 설명하는 답글로 나와요." if re.search(r"억울|악플|진상|테러|블랙", c)
                     else "추천 카드에서 답글 초안을 만들고 고쳐서 승인할 수 있어요.")
        return cards, " ".join(lines), ["답글 안 단 리뷰 몇 개야?", "불만 리뷰 제일 많은 게 뭐야?"]

    if intent == "topic" and t:
        pos = [r for r in rows if t in d.pos(r)]
        f = add(topic_name(t), f"{where}'{topic_name(t)}' 이야기가 나온 리뷰예요.",
                [_v("불만", len(subset)), _v("칭찬", len(pos))])
        lines = [f"{where}'{topic_name(t)}' 이야기는 불만 {len(subset)}건, 칭찬 {len(pos)}건이에요 [{f}]."]
        if subset:
            g, band, n = time_card(subset, f"'{topic_name(t)}' 불만")
            if band:
                lines.append(f"불만은 {band}에 {n}건으로 가장 많았어요 [{g}].")
        # 손님이 실제로 쓴 말 (근거 구절). "뭐라고 해?"에 모델이 요약할 재료. 최근 것부터 불만·칭찬 3개씩
        said = [("불만", d.quote(r, t, "negative")) for r in subset[::-1][:3]] + \
               [("칭찬", d.quote(r, t, "positive")) for r in pos[::-1][:3]]
        if said:
            h = add("손님 말", f"'{topic_name(t)}'에 대해 손님이 리뷰에 쓴 말이에요 (최근 것부터).",
                    [_v(f'"{q_}"', 1, "건", group=kind) for kind, q_ in said])
            if subset:
                lines.append(f"불만으로는 \"{said[0][1]}\" 같은 말이 있었어요 [{h}].")
            if pos:
                lines.append(f"칭찬으로는 \"{next(q_ for k, q_ in said if k == '칭찬')}\" 같은 말이 있었어요 [{h}].")
        return cards, " ".join(lines), ["지난주보다 늘었어?", "답글 안 단 리뷰 몇 개야?"]

    if intent == "complaints" or t:
        cnt = topic_counter(complaints)
        f = add("불만 순위", f"{where}불만 리뷰 {len(complaints)}건의 주제별 건수예요 (리뷰 하나에 주제가 여럿이면 모두 셈).",
                [_v(topic_name(k), n, share=_pct(n, len(complaints))) for k, n in cnt.most_common(6)])
        if not complaints:
            return cards, f"{where}불만 리뷰가 없어요 [{f}].", ["칭찬 리뷰 제일 많은 메뉴는?"]
        (k, n), *rest = cnt.most_common(3)
        lines = [f"{where}리뷰 {total}건 중 불만은 {len(complaints)}건이고, 가장 많은 불만은 '{topic_name(k)}'({n}건)이에요 [{f}]."]
        if rest:
            lines.append("그다음은 " + ", ".join(f"'{topic_name(a)}'({b}건)" for a, b in rest) + f"이에요 [{f}].")
        sub = [r for r in complaints if k in d.neg(r)]
        g, band, bn = time_card(sub, f"'{topic_name(k)}' 불만")
        if band:
            lines.append(f"'{topic_name(k)}' 불만은 {band}에 {bn}건 몰렸어요 [{g}].")
        return cards, " ".join(lines), nxt["complaints"]

    # overview: 한눈에
    cnt = topic_counter(complaints)
    rated = [r["rating"] for r in rows if r.get("rating")]
    avg = _num(sum(rated) / len(rated)) if rated else None
    st = d.tl.at(d.now)
    f = add("리뷰 한눈에", f"{where}리뷰 현황이에요.",
            [_v("리뷰", total), _v("불만 리뷰", len(complaints), share=_pct(len(complaints), total)),
             _v("평균 별점", avg, "점"), _v("답글 기다리는 불만", st["pending_count"]), _v("응대 점수", st["score"], "점")])
    lines = [f"{where}리뷰 {total}건 중 불만은 {len(complaints)}건, 평균 별점은 {avg}점이에요 [{f}]."]
    if cnt:
        k, n = cnt.most_common(1)[0]
        lines.append(f"가장 많은 불만은 '{topic_name(k)}'({n}건)이고, 응대 점수는 {st['score']}점이에요 [{f}].")
    return cards, " ".join(lines), ["불만 리뷰 제일 많은 게 뭐야?", "별점 평균 몇 점이야?", "답글 안 단 리뷰 몇 개야?"]


# ── ④ 답 점검 ─────────────────────────────────────────────────────
_CITE = re.compile(r"\[(F\d+)\]")
_NUM = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)")
# 원인 단정·남 탓·과장 (topics.BANNED 와 같은 뜻의 짧은 목록)
_BANNED = ("때문에", "때문이", "원인은", "원인이", "탓", "확실히", "반드시", "무조건", "틀림없", "100%")


def _numbers(text: str) -> set[str]:
    """글 속 숫자 (쉼표 빼고, 30.0 → 30, 3.80 → 3.8)."""
    out = set()
    for m in _NUM.finditer(text or ""):
        n = m.group(1).replace(",", "").rstrip(".")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n)
    return out


def check_answer(text: str, cards: list[dict], template: str) -> list[str]:
    problems = []
    if not text.strip():
        return ["빈 답"]
    if len(text) > 700:
        problems.append("700자 넘음")
    ids = {c["id"] for c in cards}
    bad = sorted({x for x in _CITE.findall(text) if x not in ids})
    if bad:
        problems.append(f"없는 근거 {', '.join(bad)}")
    if cards and not _CITE.search(text):
        problems.append("근거 표시 없음")
    known = set()
    for c in cards:
        known |= _numbers(c["text"])
        for v in c["values"]:
            known |= _numbers(str(v["label"]))
            if v.get("value") is not None:
                known |= _numbers(str(v["value"]))
            if v.get("share_percent") is not None:
                known |= _numbers(str(v["share_percent"]))
    known |= _numbers(template) | {"1", "2", "3"}     # 틀 답의 숫자(날짜·건수)와 '① ② ③'처럼 순서를 세는 작은 수
    plain = _CITE.sub("", text)
    unknown = sorted(n for n in _numbers(plain) if n not in known)
    if unknown:
        problems.append(f"근거에 없는 숫자 {', '.join(unknown)}")
    hit = [w for w in _BANNED if w in text]
    if hit:
        problems.append(f"쓰면 안 되는 말 {', '.join(hit)}")
    return problems


SYSTEM = """너는 동네 음식점 사장님의 리뷰·고객응대 비서다. 사장님 질문에 [근거 카드]만 보고 답한다.
규칙:
1. 숫자는 [근거 카드]에 있는 것만 그대로 쓴다. 새 숫자를 계산하거나 지어내지 않는다.
2. 숫자가 들어간 문장 끝에는 그 카드 번호를 [F1]처럼 붙인다.
3. 불만의 원인을 단정하거나 손님·직원을 탓하지 않는다. 할 일은 '~해 보세요'처럼 권한다.
4. 해요체로 2~5문장, 500자 이하. 답 글만 쓴다.
5. [틀 답]의 사실은 빠뜨리지 말고 더 자연스럽게 다듬는다."""


# ── ② AI 플래너 (live 만, 11/21) ───────────────────────────────────
# 상권 비서의 planner.py 와 같은 생각: 모델은 '무엇을 묻는지'만 고르고 JSON 한 줄로 답한다. 코드가 그 값이 아래 목록에
# 있는지 검사하고, 틀리면 규칙(parse) 결과를 쓴다. 숫자·카드는 여전히 코드가 만든다. function calling 은 쓰지 않는다
# (상권 팀이 11/08 HCX-005 에서 maxTokens 와 같이 쓰면 40001 로 거절된다고 적어 둠).
INTENTS = {
    "complaints": "불만 순위·가장 많은 불만", "topic": "특정 주제(맛·양·포장 누락 등)에 대해 손님이 한 말",
    "time": "불만이 몰리는 시간대", "trend": "지난주·최근보다 늘었나 줄었나", "rating": "별점·평점 평균",
    "channel": "배달앱(배민·쿠팡이츠 등)끼리 비교", "recent": "최근 들어온 리뷰", "praise": "칭찬·인기 메뉴",
    "unanswered": "답글 안 단 리뷰·답글 기한", "score": "응대 점수", "inquiry": "손님 문의·알레르기 문의",
    "howto": "답글 쓰는 법·억울한 리뷰 대응", "capture": "리뷰 캡처·붙여넣기 방법", "overview": "리뷰 전반 요약",
}
PLAN_SYSTEM = """너는 동네 음식점 사장님의 질문을 읽고 어떤 자료로 답할지 고르는 분류기다. JSON 한 줄만 쓴다.
형식: {"intent": "<종류>", "topic": "<주제 id 또는 null>", "channels": ["<채널 id>", ...]}
- intent 는 [종류]에 있는 id 하나. topic 은 질문이 특정 주제를 말할 때만 [주제]의 id, 아니면 null.
- channels 는 질문에 나온 배달앱만 (없으면 []). 숫자나 설명은 쓰지 않는다.
- [규칙 분류]는 참고다. 질문의 뜻에 더 맞는 것이 있으면 바꾼다."""


def plan(text: str, rule: Question, chat: Chat) -> tuple[Question | None, str | None]:
    """(모델이 고른 Question, 못 쓴 이유). live·키가 있을 때만 부른다. 틀린 값이 하나라도 있으면 (None, 이유)."""
    user = ("[종류]\n" + "\n".join(f"{k}: {v}" for k, v in INTENTS.items())
            + "\n\n[주제]\n" + ", ".join(f"{k}({topic_name(k)})" for k in TOPICS)
            + "\n\n[채널]\n" + ", ".join(f"{k}({v})" for k, v in CHANNEL_KO.items() if k != "web")
            + "\n\n[규칙 분류]\n" + json.dumps({"intent": rule.intent, "topic": rule.topic, "channels": rule.channels},
                                              ensure_ascii=False)
            + f"\n\n[사장님 질문]\n{text}")
    try:
        raw = chat.ask(PLAN_SYSTEM, user, "care_plan")
    except ChatError as e:
        return None, f"플래너 호출 실패: {e}"
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        got = json.loads(m.group(0)) if m else None
    except ValueError:
        got = None
    if not isinstance(got, dict):
        return None, "플래너 답이 JSON 이 아님"
    intent, topic, channels = got.get("intent"), got.get("topic"), got.get("channels") or []
    if intent not in INTENTS:
        return None, f"플래너가 모르는 종류 {intent!r}"
    if topic in ("", "null"):
        topic = None
    if topic is not None and topic not in TOPICS:
        return None, f"플래너가 모르는 주제 {topic!r}"
    if not isinstance(channels, list) or any(c not in CHANNEL_KO or c == "web" for c in channels):
        return None, f"플래너가 모르는 채널 {channels!r}"
    return Question(text=text, intent=intent, topic=topic, channels=list(dict.fromkeys(channels))), None


def answer(classifier, store_id: str, visitor_id: str | None, text: str, now: datetime, chat: Chat | None = None) -> dict:
    chat = chat or Chat()
    rule = parse(text)
    q, plan_note = rule, None
    if chat.available:
        planned, plan_note = plan(text, rule, chat)
        q = planned or rule
    d = Data.load(classifier, store_id, visitor_id, now)
    cards, fixed, suggestions = build(q, d, store_id, visitor_id)
    method, problems, out = "template", [], fixed
    if chat.available and q.intent not in ("capture",):
        user = ("[근거 카드]\n" + "\n".join(
            f"{c['id']} {c['topic']}: {c['text']} " + "; ".join(
                f"{(v.get('group') + ' ') if v.get('group') else ''}{v['label']} {v['value']}{v['unit']}" for v in c["values"])
            for c in cards) + f"\n\n[틀 답]\n{fixed}\n\n[사장님 질문]\n{text}")
        try:
            got = chat.ask(SYSTEM, user, "care_ask").strip().strip('"')
            problems = check_answer(got, cards, fixed)
            if not problems:
                method, out = "hcx", got
        except ChatError as e:
            problems = [f"모델 호출 실패: {e}"]
    synthetic = any((r.get("data_origin") or "synthetic") == "synthetic" for r in d.rows)
    return {"text": out, "intent": q.intent, "topic": q.topic, "topic_name": topic_name(q.topic) if q.topic else None,
            "channels": q.channels, "cards": cards, "suggestions": suggestions, "method": method,
            "demo": not chat.available, "checks": problems,
            "model": chat.model if method == "hcx" else None,
            "notes": [],        # 화면 안내는 넣지 않는다 (11/21 사장님 요청). 누가 썼는지는 method·model, 합성 여부는 synthetic 칸으로만
            "synthetic": synthetic,
            "classified_by": "hcx" if q is not rule else "rules", "rule_intent": rule.intent, "plan_note": plan_note,
            "base_day": d.base_day.date().isoformat() if d.rows else None}
