"""마케팅 질문 답하기 (POST /api/marketing-survey/ask, 11/21).

통합 화면 'AI에게 묻기' 서랍의 마케팅 질문은 늘 "맞춤 마케팅의 'OO'에서 질문에 답하면 만들어 드려요" 한 줄이었다.
상권 비서·리뷰 분석 서비스의 질문 답하기(services/review-insight/app/ask.py)와 같은 순서로 답한다:

  ① 질문 나누기 : 규칙(parse). live 면 HCX-005 플래너가 JSON 으로 고르고 코드가 검사한다 (틀리면 규칙)
  ② 근거 카드   : 이 서비스가 이미 계산하는 값만 쓴다 — 마케팅 보고서(report.marketing_section: 승인 기록·쿠폰 결과·
                 광고 판정·공지 전후 불만), 쿠폰 계산(coupon_calc.calc), 광고 손익(adspend), 아이디어(ideas.IDEAS_BY_GOAL),
                 반복 불만(complaints), 메뉴 가격(가게 프로필). 숫자는 모두 코드가 센다
  ③ 답 쓰기     : mock·키 없음이면 틀 문장, live 면 HCX-005 가 카드만 보고 다듬는다
  ④ 답 점검     : 모델 답의 숫자는 카드·틀 답에 있어야 하고, [F#] 는 이번 카드, 과장·보장하는 말 금지. 못 넘으면 틀 문장

원칙(CLAUDE.md): 날짜·숫자·사실은 코드가 계산하고, AI는 글만 쓴다. 홍보 글 '쓰기'는 여기서 하지 않는다
(맞춤 마케팅 화면의 승인 흐름이 있음) — 질문에 답하고 그 화면으로 안내한다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import clova
from marketing_survey import adspend, complaints, coupon_calc, report
from marketing_survey.ideas import IDEAS_BY_GOAL

MODEL = "HCX-005"
APP_KO = {"baemin": "배민", "coupangeats": "쿠팡이츠", "yogiyo": "요기요", "ddanggyeoyo": "땡겨요", "naver_place": "네이버 플레이스"}
# 쿠폰 계산에서 사장님이 말하지 않은 값 (맞춤 마케팅 쿠폰 질문의 첫 보기와 같은 값). 카드에 '가정한 값'으로 적는다
ASSUME = {"avg_order_won": 15_000, "margin_pct": 30, "budget_won": 100_000}
SOURCE_TITLE = "맞춤 마케팅 서비스 (승인 기록·쿠폰·광고 계산)"

# ── ① 질문 나누기 ──────────────────────────────────────────────
INTENTS = {
    "coupon_calc": "쿠폰·할인을 하면 몇 개 팔아야 본전인지 계산",
    "coupon_result": "지난 쿠폰을 손님이 얼마나 썼는지·효과",
    "ads": "배달앱 광고비가 남는지 손해인지",
    "notice_effect": "공지·안내문을 올린 뒤 불만이 줄었는지",
    "activity": "이번 달·이번 주에 한 마케팅(승인한 글) 정리",
    "next": "다음에 무엇을 하면 좋을지 추천",
    "ideas_new": "새 손님 늘리는 아이디어", "ideas_repeat": "단골·재주문 늘리는 아이디어",
    "ideas_value": "객단가(한 번 주문 금액) 올리는 아이디어", "rainy": "비 오는 날 홍보",
    "leftover": "남은 재료 활용·묶음 판매", "menu_price": "메뉴 가격",
    "overview": "마케팅 전반 요약",
}
_INTENT_RX = [
    ("coupon_result", r"쿠폰.*(효과|결과|성과|썼|사용|쓴|얼마나팔|반응)|지난(번)?쿠폰"),
    ("coupon_calc", r"(쿠폰|할인).*(본전|몇개|몇장|몇건|손해|남아|남을|계산|얼마나팔|팔아야)|(본전|손익분기)"),
    ("ads", r"광고"),
    ("notice_effect", r"(공지|안내문|개선소식).*(효과|줄었|결과|어땠)"),
    ("rainy", r"비오는|비가오|비올|우천|장마"),
    ("leftover", r"남은재료|남는재료|재고|재료가남|남은거|떨이"),
    ("ideas_repeat", r"단골|재주문|다시주문|다시오|재방문"),
    ("ideas_new", r"새손님|신규|처음오는|손님늘|손님을늘|손님좀늘|알리|홍보방법|인스타|sns|블로그|게시물|뭐올리|뭘올리"),
    ("ideas_value", r"객단가|주문금액|세트|더많이시키|사이드"),
    ("menu_price", r"메뉴가격|가격얼마|얼마야|가격표"),
    ("activity", r"이번달|이번주|지난달|한거|했던|보고서|리포트|정리|승인한"),
    ("next", r"뭐하면|뭘하면|뭐해야|뭘해야|추천|다음에|할일|어떻게하면|방법|아이디어|좋을까"),
]


@dataclass
class Question:
    text: str
    intent: str
    discount_won: int | None = None
    budget_won: int | None = None
    avg_order_won: int | None = None
    margin_pct: int | None = None
    amount_won: int | None = None          # 광고비처럼 그 밖의 금액
    menu: str | None = None
    period: str = "monthly"


def _squash(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣%]", "", (text or "").lower())


_MONEY = re.compile(r"(\d+(?:\.\d+)?)\s*(만|천)?\s*원?")


def _won(fragment: str) -> int | None:
    m = _MONEY.fullmatch(fragment.strip()) if fragment else None
    if not m:
        return None
    n = float(m.group(1)) * {"만": 10_000, "천": 1_000, None: 1}[m.group(2)]
    return int(n) if n > 0 else None


def _money_after(words: str, text: str) -> int | None:
    m = re.search(rf"(?:{words})\D{{0,6}}?(\d+(?:\.\d+)?\s*(?:만|천)?\s*원?)", text)
    return _won(m.group(1)) if m else None


def _money_before(words: str, text: str) -> int | None:
    m = re.search(rf"(\d+(?:\.\d+)?\s*(?:만|천)?\s*원)\s*(?:짜리\s*)?(?:{words})", text)
    return _won(m.group(1)) if m else None


def parse(text: str, menu_names: list[str] | None = None) -> Question:
    c = _squash(text)
    intent = next((i for i, rx in _INTENT_RX if re.search(rx, c)), "overview")
    t = text or ""
    q = Question(text=text, intent=intent, period="weekly" if re.search(r"이번주|지난주|일주일", c) else "monthly")
    q.discount_won = _money_before("할인|쿠폰", t) or _money_after("할인|쿠폰", t)
    q.budget_won = _money_after("예산", t) or _money_before("예산", t)
    q.avg_order_won = _money_after("객단가|평균\\s*주문(?:\\s*금액)?|주문\\s*금액", t)
    m = re.search(r"(?:마진|이익률|남는\s*비율)\D{0,4}(\d{1,2})\s*%", t) or re.search(r"(\d{1,2})\s*%\s*(?:마진|남)", t)
    q.margin_pct = int(m.group(1)) if m else None
    q.amount_won = _money_after("광고비?|월|한\\s*달에?", t) or _money_before("광고|씩", t)
    for name in menu_names or []:
        if name.replace(" ", "") in c:
            q.menu = name
            break
    if q.discount_won and q.discount_won == q.budget_won:      # "예산 10만원 할인" 처럼 겹치면 할인은 비운다
        q.discount_won = None
    if q.intent in ("overview", "next") and q.discount_won and re.search(r"쿠폰|할인", c):   # "3천원 쿠폰 내면?" = 계산
        q.intent = "coupon_calc"
    return q


# ── ② 근거 카드 ──────────────────────────────────────────────────
def _card(n, topic, text, values=None, warnings=None, period=None) -> dict:
    return {"id": f"F{n}", "topic": topic, "status": "available", "text": text, "values": values or [],
            "warnings": warnings or [], "source_ref": {"source_title": SOURCE_TITLE, "data_version": period}}


def _v(label, value, unit="원", group=None) -> dict:
    out = {"label": label, "value": value, "unit": unit}
    if group:
        out["group"] = group
    return out


def _w(n: int | float) -> str:
    return f"{int(n):,}원"


def _titles(titles: list[str]) -> str:
    """["가", "나"] → "'가', '나'예요" 의 앞부분과 맞는 '이에요/예요'."""
    joined = ", ".join(f"'{t}'" for t in titles)
    return joined + ("이에요" if _josa(titles[-1], "이/가").endswith("이") else "예요") if titles else ""


def _josa(word: str, pair: str) -> str:
    last = next((ch for ch in reversed(word) if "가" <= ch <= "힣"), None)
    has = last is not None and (ord(last) - 0xAC00) % 28 != 0
    a, b = pair.split("/")
    return word + (a if has else b)


@dataclass
class Built:
    cards: list[dict] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    period: str | None = None

    def add(self, topic, text, values=None, warnings=None) -> str:
        self.cards.append(_card(len(self.cards) + 1, topic, text, values, warnings, self.period))
        return self.cards[-1]["id"]


def build(q: Question, ctx, store_id: str, visitor_id: str | None, today=None) -> Built:
    sec = report.marketing_section(store_id, q.period, today=today, visitor_id=visitor_id)
    per = sec.get("period") or {}
    b = Built(period=f"{per.get('start')}~{per.get('end')}" if per.get("start") else None)
    demo_warn = ["아직 승인한 기록이 없어 예시 기록으로 보여 드려요."] if sec.get("demo") else None
    when = "이번 주" if q.period == "weekly" else "이번 달"
    cost = sec.get("cost") or {}
    intent = q.intent

    if intent == "coupon_calc":
        discount = q.discount_won
        if not discount:
            f = b.add("쿠폰 계산", "할인 금액이 질문에 없어 계산하지 못했어요.", [])
            b.lines.append(f"할인 금액을 알려 주시면 본전 주문 수를 바로 계산해 드려요 [{f}]. 예: '쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?'")
            b.suggestions = ["쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?", "지난번 쿠폰 효과 있었어?"]
            return b
        budget = q.budget_won or ASSUME["budget_won"]
        avg = q.avg_order_won or ASSUME["avg_order_won"]
        margin = q.margin_pct or ASSUME["margin_pct"]
        price = (ctx.store.menu_prices or {}).get(q.menu) if q.menu else None
        r = coupon_calc.calc(budget, discount, int(price or avg), avg, margin)
        assumed = [name for name, given in (("예산", q.budget_won), ("평균 주문 금액", q.avg_order_won), ("마진", q.margin_pct))
                   if not given]
        warn = [f"{'·'.join(assumed)}은 말씀하지 않으셔서 가정한 값이에요 (예산 {_w(ASSUME['budget_won'])}, "
                f"평균 주문 {_w(ASSUME['avg_order_won'])}, 마진 {ASSUME['margin_pct']}%)."] if assumed else []
        f = b.add("쿠폰 계산", f"할인 {_w(discount)} 쿠폰을 예산 {_w(budget)}으로 낼 때예요 (평균 주문 {_w(avg)}, 마진 {margin}%).",
                  [_v("쿠폰 장수", r["count"], "장"), _v("최대 할인 비용", r["max_cost_won"]),
                   _v("주문 1건에 남는 돈", r["profit_per_order_won"]), _v("본전 주문 수", r["breakeven_orders"], "건"),
                   _v("할인율", r["discount_pct"], "%")], warn)
        b.lines.append(f"할인 {_w(discount)} 쿠폰을 예산 {_w(budget)}으로 내면 {r['count']}장이고, 쿠폰 주문이 "
                       f"{r['breakeven_orders']}건 넘으면 본전이에요 [{f}].")
        b.lines.append(f"주문 1건에 남는 돈을 {_w(r['profit_per_order_won'])}으로 계산했어요 [{f}].")
        if assumed:
            b.lines.append(f"{'·'.join(assumed)}은 가정한 값이라, 맞춤 마케팅의 쿠폰에서 우리 가게 값으로 다시 계산해 보세요.")
        b.suggestions = ["지난번 쿠폰 효과 있었어?", "배달앱 광고비 괜찮아?"]
        return b

    if intent == "coupon_result":
        cp = cost.get("coupon")
        if not cp:
            f = b.add("쿠폰 결과", f"{when} 쿠폰 결과 기록이 없어요.", [])
            b.lines.append(f"{when}에는 쿠폰 결과 기록이 없어요 [{f}]. 맞춤 마케팅에서 쿠폰 결과(낸 장수·쓴 장수)를 적으면 효과를 계산해 드려요.")
        else:
            rate = round(cp["usage_rate"] * 100) if cp.get("usage_rate") is not None else None
            f = b.add("쿠폰 결과", f"{when} 쿠폰 기록이에요.",
                      [_v("낸 쿠폰", cp["issued"], "장"), _v("쓴 쿠폰", cp["used"], "장"), _v("사용률", rate, "%"),
                       _v("할인에 쓴 돈", cp["discount_spent"]), _v("쿠폰 주문", cp["coupon_orders"], "건"),
                       _v("본전 주문 수", cp["breakeven_orders"], "건")], demo_warn)
            ok = cp["coupon_orders"] >= cp["breakeven_orders"]
            b.lines.append(f"{when} 쿠폰은 {cp['issued']}장 중 {cp['used']}장이 쓰였어요 (사용률 {rate}%) [{f}].")
            b.lines.append(f"쿠폰 주문 {cp['coupon_orders']}건으로 본전({cp['breakeven_orders']}건)을 "
                           + ("넘겼어요" if ok else "넘기지 못했어요") + f" [{f}].")
        b.suggestions = ["쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?", "다음엔 뭐 하면 좋아?"]
        return b

    if intent == "ads":
        ads = cost.get("ads") or []
        vals = []
        for a in ads:
            g = a.get("label") or APP_KO.get(a.get("app"), a.get("app"))
            vals += [_v("주문 1건 광고비", a["cost_per_order"], group=g), _v("주문 1건에 남는 돈", a["profit_per_order"], group=g)]
        f = b.add("광고 손익", f"{when} 배달앱 광고를 주문 1건 기준으로 본 값이에요.", vals, demo_warn)
        if not ads:
            b.lines.append(f"{when} 광고 기록이 없어요 [{f}]. 맞춤 마케팅의 광고비 점검에 광고비와 주문 수를 넣으면 앱마다 계산해 드려요.")
        for a in ads:
            g = a.get("label") or APP_KO.get(a.get("app"), a.get("app"))
            b.lines.append(f"- {g}: 주문 1건 광고비 {_w(a['cost_per_order'])}, 남는 돈 {_w(a['profit_per_order'])} → '{a['verdict']}' [{f}]")
        loss = [a for a in ads if a.get("verdict") == "손해 광고"]
        if loss:
            b.lines.insert(0, f"{_josa(loss[0].get('label') or loss[0]['app'], '은/는')} 주문 1건에 남는 돈보다 광고비가 커서 조건을 다시 보는 게 좋아요 [{f}].")
        if q.amount_won and ads:
            profit = ads[0]["profit_per_order"]
            n = adspend.breakeven_orders(q.amount_won, profit)
            g = b.add("광고비 본전", f"광고비 {_w(q.amount_won)}을 주문 1건에 남는 돈 {_w(profit)}으로 나눈 값이에요.",
                      [_v("광고비", q.amount_won), _v("본전 주문 수", n, "건")])
            b.lines.append(f"광고비 {_w(q.amount_won)}이면 광고로 들어온 주문이 {n}건 넘어야 본전이에요 [{g}].")
        b.suggestions = ["다음엔 뭐 하면 좋아?", "지난번 쿠폰 효과 있었어?"]
        return b

    if intent == "notice_effect":
        fixed = sec.get("fixed") or []
        f = b.add("공지 전후 불만", "공지를 승인한 날 앞뒤 14일의 같은 불만 리뷰 수예요.",
                  [_v(x["complaint"], x["before_14d"], "건", group="공지 전 14일") for x in fixed]
                  + [_v(x["complaint"], x["after_14d"], "건", group="공지 후 14일") for x in fixed], demo_warn)
        if not fixed:
            b.lines.append(f"공지를 올린 기록이 없어 전후를 비교할 수 없어요 [{f}]. 맞춤 마케팅에서 불만 안내문을 승인하면 14일 뒤 비교해 드려요.")
        for x in fixed:
            word = "줄었어요" if x["after_14d"] < x["before_14d"] else "줄지 않았어요"
            more = "" if x.get("after_complete") else f" ({x['window_ends']}까지 더 지켜봐야 해요)"
            b.lines.append(f"'{x['complaint']}' 공지({x['approved_on']}) 전 14일 {x['before_14d']}건 → 후 14일 {x['after_14d']}건으로 "
                           f"{word}{more} [{f}].")
        if any(x["after_14d"] < x["before_14d"] for x in fixed):
            b.lines.append("줄었다면 '개선 소식'을 올려 손님에게 알리는 것도 좋아요.")
        b.suggestions = ["다음엔 뭐 하면 좋아?", "이번 달 마케팅 정리해줘"]
        return b

    if intent in ("ideas_new", "ideas_repeat", "ideas_value", "rainy"):
        goal = {"ideas_new": "새 손님", "ideas_repeat": "재주문", "ideas_value": "객단가", "rainy": "새 손님"}[intent]
        items = IDEAS_BY_GOAL.get(goal, [])
        if intent == "rainy":
            items = [i for i in items if i["id"] == "rainy_day"] + [i for i in items if i["id"] != "rainy_day"][:1]
        f = b.add(f"{goal} 아이디어", f"맞춤 마케팅의 '{goal}' 목표 아이디어예요.",
                  [_v(i["title"], None, "", group=goal) for i in items[:3]])
        b.lines.append(f"'{goal}'에 맞는 아이디어는 {_titles([i['title'] for i in items[:3]])} [{f}].")
        for i in items[:2]:
            b.lines.append(f"- {i['title']}: {i['why']}")
        reps = complaints.repeated_topics(ctx)
        if intent == "ideas_repeat" and reps:
            g = b.add("반복 불만", "같은 불만이 두 번 넘게 나온 주제예요.", [_v(t.label, len(t.review_ids), "건") for t in reps[:3]])
            b.lines.append(f"단골을 늘리기 전에 '{reps[0].label}' 불만({len(reps[0].review_ids)}건)을 먼저 줄이면 재주문에 도움이 돼요 [{g}].")
        b.lines.append("맞춤 마케팅에서 목표를 고르면 이 아이디어로 글까지 만들어 드려요.")
        b.suggestions = ["다음엔 뭐 하면 좋아?", "쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?"]
        return b

    if intent in ("leftover", "menu_price"):
        prices = ctx.store.menu_prices or {}
        f = b.add("메뉴 가격", f"{ctx.store.name}의 메뉴 가격이에요.", [_v(k, v) for k, v in prices.items()])
        if intent == "menu_price" and q.menu in prices:
            b.lines.append(f"{q.menu}은(는) {_w(prices[q.menu])}이에요 [{f}].".replace(f"{q.menu}은(는)", _josa(q.menu, "은/는")))
        elif intent == "menu_price":
            b.lines.append(", ".join(f"{k} {_w(v)}" for k, v in prices.items()) + f"이에요 [{f}].")
        else:
            b.lines.append("남은 재료는 그 재료가 들어간 메뉴와 같이 묶어 할인하면 버리지 않고 팔 수 있어요.")
            cheap = min(prices.items(), key=lambda kv: kv[1]) if prices else None
            if cheap:
                obj = _josa(cheap[0], "을/를")[len(cheap[0]):]
                b.lines.append(f"예를 들어 가장 싼 '{cheap[0]}'({_w(cheap[1])}){obj} 다른 메뉴와 묶는 식이에요 [{f}].")
            b.lines.append("맞춤 마케팅의 '남은 재료'에서 재료와 메뉴를 고르면 묶음 가격과 알림 글을 만들어 드려요.")
        b.suggestions = ["쿠폰 2천원 할인하면 몇 개 팔아야 본전이야?", "다음엔 뭐 하면 좋아?"]
        return b

    act = sec.get("activity") or {}
    approved = act.get("approved") or {}
    nxt = sec.get("next") or []
    if intent == "next":
        f = b.add("다음 할 일", "승인 기록·쿠폰·광고 계산으로 고른 다음 할 일이에요.",
                  [_v(n["title"], None, "") for n in nxt], demo_warn)
        if nxt:
            b.lines.append(f"지금 해 볼 만한 건 {_titles([n['title'] for n in nxt[:2]])} [{f}].")
            for n in nxt[:2]:
                b.lines.append(f"- {n['title']}: {n['why']} [{f}]")
        reps = complaints.repeated_topics(ctx)
        if reps:
            g = b.add("반복 불만", "같은 불만이 두 번 넘게 나온 주제예요.", [_v(t.label, len(t.review_ids), "건") for t in reps[:3]])
            b.lines.append(f"리뷰에는 '{reps[0].label}' 불만이 {len(reps[0].review_ids)}건 반복돼, 안내문으로 먼저 알리는 것도 방법이에요 [{g}].")
        if not nxt and not reps:
            b.lines.append(f"지금 기록으로는 바로 할 일이 보이지 않아요 [{f}]. 맞춤 마케팅의 질문에 답하면 가게에 맞는 방법을 골라 드려요.")
        b.suggestions = ["단골 늘리려면 뭐 해야 돼?", "배달앱 광고비 괜찮아?"]
        return b

    # activity · overview
    total = sum(approved.values())
    f = b.add(f"{when} 마케팅", f"{when}({per.get('start')}~{per.get('end')}) 승인한 글이에요.",
              [_v(k, n, "건") for k, n in approved.items()], demo_warn)
    lines = [f"{when} 승인한 글은 {total}건이에요" + (" (" + ", ".join(f"{k} {n}건" for k, n in approved.items()) + ")" if approved else "")
             + f" [{f}]."]
    cp = cost.get("coupon")
    if cp:
        g = b.add("쿠폰 결과", f"{when} 쿠폰 기록이에요.", [_v("낸 쿠폰", cp["issued"], "장"), _v("쓴 쿠폰", cp["used"], "장"),
                                                         _v("쿠폰 주문", cp["coupon_orders"], "건"), _v("본전 주문 수", cp["breakeven_orders"], "건")], demo_warn)
        lines.append(f"쿠폰은 {cp['issued']}장 중 {cp['used']}장이 쓰였고 쿠폰 주문은 {cp['coupon_orders']}건이에요 [{g}].")
    if nxt:
        h = b.add("다음 할 일", "기록으로 고른 다음 할 일이에요.", [_v(n["title"], None, "") for n in nxt])
        title = f"'{nxt[0]['title']}'"
        lines.append(f"다음으로는 {_josa(title, '을/를')} 추천해요 [{h}].")
    b.lines = lines
    b.suggestions = ["다음엔 뭐 하면 좋아?", "지난번 쿠폰 효과 있었어?", "배달앱 광고비 괜찮아?"]
    return b


# ── ④ 답 점검 ─────────────────────────────────────────────────────
_CITE = re.compile(r"\[(F\d+)\]")
_NUM = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)")
_BANNED = ("무조건", "반드시", "확실히", "100%", "보장", "틀림없", "대박", "때문에", "탓")


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUM.finditer(text or ""):
        n = m.group(1).replace(",", "").rstrip(".")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n)
    return out


def check_answer(text: str, cards: list[dict], template: str) -> list[str]:
    if not (text or "").strip():
        return ["빈 답"]
    problems = []
    if len(text) > 700:
        problems.append("700자 넘음")
    ids = {c["id"] for c in cards}
    bad = sorted({x for x in _CITE.findall(text) if x not in ids})
    if bad:
        problems.append(f"없는 근거 {', '.join(bad)}")
    if cards and _numbers(_CITE.sub("", text)) and not _CITE.search(text):
        problems.append("근거 표시 없음")
    known = set(_numbers(template))
    for c in cards:
        known |= _numbers(c["text"]) | {n for w in c["warnings"] for n in _numbers(w)}
        for v in c["values"]:
            known |= _numbers(str(v["label"])) | (_numbers(str(v["value"])) if v.get("value") is not None else set())
    known |= {"1", "2", "3"}
    unknown = sorted(n for n in _numbers(_CITE.sub("", text)) if n not in known)
    if unknown:
        problems.append(f"근거에 없는 숫자 {', '.join(unknown)}")
    hit = [w for w in _BANNED if w in text]
    if hit:
        problems.append(f"쓰면 안 되는 말 {', '.join(hit)}")
    return problems


# ── ①′ AI 플래너 · ③ 답 쓰기 (live 만) ───────────────────────────────
PLAN_SYSTEM = """너는 동네 가게 사장님의 마케팅 질문을 읽고 어떤 자료로 답할지 고르는 분류기다. JSON 한 줄만 쓴다.
형식: {"intent": "<종류 id>"}
- intent 는 [종류]에 있는 id 하나. 금액·마진 같은 숫자는 쓰지 않는다 (숫자는 코드가 질문에서 읽는다).
- [규칙 분류]는 참고다. 질문의 뜻에 더 맞는 것이 있으면 바꾼다."""
WRITE_SYSTEM = """너는 동네 가게 사장님의 마케팅 도우미다. 사장님 질문에 [근거 카드]만 보고 답한다.
규칙:
1. 숫자는 [근거 카드]와 [틀 답]에 있는 것만 그대로 쓴다. 새 숫자를 계산하거나 지어내지 않는다.
2. 숫자가 들어간 문장 끝에는 그 카드 번호를 [F1]처럼 붙인다.
3. 효과를 보장하거나 과장하지 않는다 ('무조건·반드시·대박' 금지). 할 일은 '~해 보세요'처럼 권한다.
4. 가정한 값이 있으면 가정이라고 말한다. 해요체로 2~5문장, 500자 이하. 답 글만 쓴다.
5. [틀 답]의 사실은 빠뜨리지 말고 더 자연스럽게 다듬는다."""


def _say(call, key, system, user) -> str:
    out = call(key, system, [{"role": "user", "content": user}], model=MODEL, temperature=0.2, max_tokens=700)
    if out.get("error"):
        raise RuntimeError(str(out["error"])[:200])
    return (out.get("content") or "").strip()


def plan(text: str, rule: Question, key: str, call=clova.call) -> tuple[str | None, str | None]:
    user = ("[종류]\n" + "\n".join(f"{k}: {v}" for k, v in INTENTS.items())
            + "\n\n[규칙 분류]\n" + json.dumps({"intent": rule.intent}, ensure_ascii=False) + f"\n\n[사장님 질문]\n{text}")
    try:
        raw = _say(call, key, PLAN_SYSTEM, user)
    except Exception as e:      # noqa: BLE001 — 플래너가 실패해도 규칙으로 답한다
        return None, f"플래너 호출 실패: {e.__class__.__name__}"
    got = clova.parse_json(raw)
    if not isinstance(got, dict):
        return None, "플래너 답이 JSON 이 아님"
    if got.get("intent") not in INTENTS:
        return None, f"플래너가 모르는 종류 {got.get('intent')!r}"
    return got["intent"], None


def answer(ctx, store_id: str, visitor_id: str | None, text: str, key: str | None, call=clova.call, today=None) -> dict:
    rule = parse(text, list((ctx.store.menu_prices or {}).keys()))
    q, plan_note = rule, None
    if key:
        intent, plan_note = plan(text, rule, key, call)
        if intent:
            q = Question(**{**rule.__dict__, "intent": intent})
    b = build(q, ctx, store_id, visitor_id, today=today)
    fixed = "\n".join(b.lines) if any(x.startswith("- ") for x in b.lines) else " ".join(b.lines)
    method, problems, out = "template", [], fixed
    if key:
        user = ("[근거 카드]\n" + "\n".join(
            f"{c['id']} {c['topic']}: {c['text']} " + "; ".join(
                f"{(v.get('group') + ' ') if v.get('group') else ''}{v['label']}"
                + (f" {v['value']}{v['unit']}" if v.get('value') is not None else "") for v in c["values"])
            + (" (주의: " + " ".join(c["warnings"]) + ")" if c["warnings"] else "")
            for c in b.cards) + f"\n\n[틀 답]\n{fixed}\n\n[사장님 질문]\n{text}")
        try:
            got = _say(call, key, WRITE_SYSTEM, user).strip('"')
            problems = check_answer(got, b.cards, fixed)
            if not problems:
                method, out = "hcx", got
        except Exception as e:      # noqa: BLE001
            problems = [f"모델 호출 실패: {e.__class__.__name__}"]
    return {"text": out, "intent": q.intent, "cards": b.cards, "suggestions": b.suggestions, "method": method,
            "model": MODEL if method == "hcx" else None, "demo": key is None, "checks": problems,
            "classified_by": "hcx" if q is not rule else "rules", "rule_intent": rule.intent, "plan_note": plan_note,
            "notes": []}
