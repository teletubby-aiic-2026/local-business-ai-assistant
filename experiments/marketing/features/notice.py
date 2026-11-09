"""
B2 휴무·영업시간 공지 (parse_notice + build_channel_notice) 기능 부분

사장님이 쓴 공지 글(또는 인스타 공지 캡처를 OCR한 글)에서
종류·날짜·시간·사유를 뽑고, 네이버 스마트플레이스에 넣을 값과 소식 문구를 만든다.

S2(행사 홍보)에서 배운 원칙을 그대로 적용
- AI는 글에서 '어느 부분이 날짜인지'만 원문 그대로 집어낸다
- 날짜 계산("다음 주 화요일" → 11월 10일)은 코드가 한다
- 소식 문구도 코드가 템플릿으로 만든다 (틀리면 손님이 헛걸음하는 정보라서)
- 날짜를 정할 수 없거나 요일이 안 맞으면 '사장님 확인 필요'로 표시
"""

import re
from datetime import timedelta

import clova
from common import dates as D
from common import korean as K

MODEL = "HCX-005"
MAX_RETRY = 2

STORE = {
    "가게 이름": "예시 브런치 카페",
    "여는 시각": "10:00",
    "닫는 시각": "21:00",
    "휴무 요일": ["월"],
}

KINDS = ["임시휴무", "단축영업", "영업시간 변경", "정기휴무 변경"]


# ── 문구 템플릿 (코드) ────────────────────────────────────────
def next_open_day(d):
    x = d + timedelta(days=1)
    while D.WEEK[x.weekday()] in STORE["휴무 요일"]:
        x += timedelta(days=1)
    return x


def build_notice(info):
    """확인된 정보 → 스마트플레이스 입력값 + 소식 문구."""
    k, s, e = info["종류"], info["시작"], info["종료"]
    reason = info.get("사유") or ""
    why = f"{reason}{K.josa(reason, '으로', '로')} " if reason else ""
    if k == "임시휴무":
        when = D.fmt(s) if s == e else f"{D.fmt(s)}부터 {D.fmt(e)}까지"
        subj = f"{when}{K.josa(when, '은', '는')}" if s == e else when
        text = f"{subj} {why}쉬어 갑니다. {D.fmt(next_open_day(e))}부터 정상 영업해요. 헛걸음하지 않도록 미리 알려 드려요."
        field = {"임시 휴무일": [str(s + timedelta(days=i)) for i in range((e - s).days + 1)]}
    elif k == "단축영업":
        o, c = info.get("여는") or STORE["여는 시각"], info.get("닫는") or STORE["닫는 시각"]
        text = f"{D.fmt(s)}{K.josa(D.fmt(s), '은', '는')} {why}{o}~{c}에 영업해요. 방문 전 참고해 주세요."
        field = {"특정일 영업시간": {str(s): f"{o}~{c}"}}
    elif k == "영업시간 변경":
        o, c = info.get("여는") or STORE["여는 시각"], info.get("닫는") or STORE["닫는 시각"]
        text = f"{D.fmt(s)}부터 영업시간이 {o}~{c}{K.josa(c, '으로', '로')} 바뀝니다. {why.strip()}".strip()
        field = {"영업시간": f"{o}~{c}", "적용 시작일": str(s)}
    else:  # 정기휴무 변경
        r = info.get("정기휴무") or "?"
        text = f"{D.fmt(s)}부터 매주 {r}요일은 정기 휴무입니다. 방문 전 참고해 주세요."
        field = {"정기 휴무": f"매주 {r}요일", "적용 시작일": str(s)}
    return {"스마트플레이스_입력값": field, "소식_문구": text}


# ── 모델 호출 (B방식: AI는 원문 표현만 뽑고 코드가 계산) ──────
PROMPT_B = """너는 가게 공지 글에서 정보를 뽑는 도우미다.
날짜나 요일을 계산하지 말고, 글에 쓰인 표현을 그대로 옮긴다.

아래 JSON으로만 답한다.
{
  "종류": "임시휴무" | "단축영업" | "영업시간 변경" | "정기휴무 변경",
  "날짜_표현": "날짜·요일을 나타내는 부분을 '부터', '까지'까지 포함해 글에서 그대로 복사 (예: '다음 주 화요일', '11/14~11/16', '다음 주부터', '12월 1일부터 매주 화요일'), 없으면 빈 문자열",
  "시간_표현": "시각을 나타내는 부분을 '부터', '까지', '마감' 같은 말까지 포함해 글에서 그대로 복사 (예: '저녁 6시까지', '3시에 마감', '오후 2시부터'), 없으면 빈 문자열",
  "사유": "쉬거나 바뀌는 이유를 글에서 그대로 복사 (예: '내부 공사'), 없으면 빈 문자열"
}
종류 기준: 하루~며칠 통째로 쉬면 임시휴무, 특정 날만 늦게 열거나 일찍 닫으면 단축영업,
어느 날부터 계속 영업시간이 바뀌면 영업시간 변경, 쉬는 요일이 바뀌면 정기휴무 변경."""


def check_b(ext, notice):
    """B방식 추출 결과 점검: 원문에 있는 표현만 뽑았는지."""
    c = {"JSON 형식": ext is not None}
    if not ext:
        return c
    c["종류가 정해진 값"] = ext.get("종류") in KINDS
    for k in ("날짜_표현", "시간_표현", "사유"):
        v = ext.get(k) or ""
        c[f"{k}: 원문에 있음"] = (not v) or K.nospace(v) in K.nospace(notice)
    return c


HINT = {
    "JSON 형식": "정해진 JSON 형식으로만 답해 주세요.",
    "종류가 정해진 값": "종류는 임시휴무, 단축영업, 영업시간 변경, 정기휴무 변경 중 하나로 써 주세요.",
}


def extract_b(key, notice):
    msgs = [{"role": "user", "content": f"[공지 글]\n{notice}"}]
    tries, total = [], {"tokens": 0, "seconds": 0, "won": 0}
    for _ in range(MAX_RETRY + 1):
        r = clova.call(key, PROMPT_B, msgs, model=MODEL, temperature=0.1, max_tokens=512)
        if "error" in r:
            return None, tries, total, r["error"]
        for k in total:
            total[k] += r[k]
        ext = clova.parse_json(r["content"])
        c = check_b(ext, notice)
        failed = [k for k, v in c.items() if not v]
        tries.append({"원문": r["content"], "실패": failed})
        if not failed:
            return ext, tries, total, None
        fb = "아래를 고쳐서 같은 JSON으로 다시 답해 주세요.\n" + "\n".join(
            f"- {HINT.get(k, k.split(':')[0] + ' 항목은 글에 있는 표현을 글자 그대로 복사해 주세요.')}" for k in failed)
        msgs += [{"role": "assistant", "content": r["content"]}, {"role": "user", "content": fb}]
    return ext, tries, total, None


def widen(span, notice, cues):
    """AI가 짧게 복사한 표현 뒤에 '부터·까지·마감' 같은 말이 원문에 이어지면 붙여 준다."""
    if not span:
        return span
    i = notice.find(span)
    if i < 0:
        return span
    tail = notice[i + len(span): i + len(span) + 6]
    m = re.match(rf"\s*(?:에\s*)?(?:{cues})", tail)
    return span + tail[:m.end()] if m else span


def to_info_b(ext, today, notice=""):
    kind = ext.get("종류") if ext.get("종류") in KINDS else "임시휴무"
    d_expr = widen(ext.get("날짜_표현") or "", notice, "부터|까지")
    t_expr = widen(ext.get("시간_표현") or "", notice, "부터|까지만|까지|마감|오픈|문\\s*(?:엽|열)")
    s, e, reg, issues = D.resolve_dates(d_expr, today, kind)

    # 정기휴무·영업시간 변경인데 시작일이 없으면 공지 전체에서 한 번 더 찾기
    if s is None and kind in ("영업시간 변경", "정기휴무 변경") and notice:
        s2, _, reg2, _ = D.resolve_dates(notice, today, kind)
        if s2:
            s, reg = s2, reg or reg2
            issues = [x for x in issues if "날짜를 정할 수 없어요" not in x]
    if s is None and reg and not any("날짜를 정할 수 없어요" in x for x in issues):
        issues.append("언제부터 적용하는지 공지에 없어요. 시작일을 입력해 주세요")

    if kind == "영업시간 변경" and s is not None and e is None and "부터" not in d_expr:
        kind = "단축영업"
        e = s

    o, c = D.resolve_times(t_expr, STORE["여는 시각"])
    if o and o.startswith("?"):
        issues.append(f"{o[1:]}이 여는 시각인지 닫는 시각인지 알 수 없어요. 확인해 주세요")
        o = None
    if kind in ("단축영업", "영업시간 변경") and not o and not c and not any("시각" in x for x in issues):
        issues.append("바뀌는 영업시간을 공지에서 찾지 못했어요. 시간을 입력해 주세요")
    return {"종류": kind, "시작": s, "종료": e, "여는": o, "닫는": c, "정기휴무": reg,
            "사유": (ext.get("사유") or "").strip(), "확인필요": issues,
            "사용한_표현": {"날짜": d_expr, "시간": t_expr}}
