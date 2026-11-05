"""날짜·요일·시간 계산 함수 (모델에게 맡기지 않는 부분)."""

import math
import re
from datetime import date, datetime, timedelta

WEEK = "월화수목금토일"


def fmt(d):
    return f"{d.month}월 {d.day}일({WEEK[d.weekday()]})"


def parse_d(s):
    return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()


def event_dates(ev):
    s, e = [parse_d(x) for x in ev["기간"].split("~")]
    return s, e


def date_label(ev):
    s, e = event_dates(ev)
    return fmt(s) if s == e else f"{fmt(s)}~{fmt(e)}"


def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def walk_minutes(km):
    return max(1, math.ceil(km * 1.3 * 1000 / 75))  # 직선거리 × 1.3 ÷ 분당 75m


def make_date(m, d, today):
    try:
        x = date(today.year, m, d)
    except ValueError:
        return None
    if x < today - timedelta(days=60):  # 한참 지난 날짜면 내년
        x = date(today.year + 1, m, d)
    return x


def week_start(d):
    return d - timedelta(days=d.weekday())


def resolve_dates(expr, today, kind):
    """날짜 표현 → (시작, 종료, 정기휴무 요일, 확인 사항 목록). 못 정하면 None."""
    e = expr.strip()
    issues = []
    start = end = None
    regular = None

    # 매주 X요일 (정기휴무)
    m = re.search(r"매주\s*([월화수목금토일])", e)
    if m:
        regular = m.group(1)

    # 1) 명시된 날짜들 (월 생략 시 앞 날짜의 월, 그것도 없으면 이번 달/다음 달)
    tokens = []
    for mt in re.finditer(r"(?:(다음\s*달|\d{1,2}\s*월)\s*)?(?<!\d)(\d{1,2})\s*일|(\d{1,2})\s*[/.]\s*(\d{1,2})", e):
        if mt.group(3):  # 11/14, 11.21 형식
            tokens.append((int(mt.group(3)), int(mt.group(4)), mt.end()))
        else:
            mon = mt.group(1)
            if mon and "다음" in mon:
                nm = today.month % 12 + 1
                tokens.append((nm, int(mt.group(2)), mt.end()))
            elif mon:
                tokens.append((int(re.sub(r"\D", "", mon)), int(mt.group(2)), mt.end()))
            else:
                tokens.append((None, int(mt.group(2)), mt.end()))
    # '다음 달 3일'은 위 정규식에서 월 자리에 '다음 달'이 오지 않으므로 따로 처리
    md = re.search(r"다음\s*달\s*(\d{1,2})\s*일", e)
    if md:
        tokens = [(today.month % 12 + 1, int(md.group(1)), md.end())]

    dates = []
    last_m = None
    for mon, d, pos in tokens:
        if mon is None:
            mon = last_m
        if mon is None:
            mon = today.month if d >= today.day else today.month % 12 + 1
        last_m = mon
        x = make_date(mon, d, today)
        if x:
            dates.append((x, pos))

    # 명시된 날짜 옆 요일이 맞는지 확인
    for x, pos in dates:
        after = e[pos:pos + 6]
        w = re.match(r"\s*\(?\s*([월화수목금토일])(?:요일)?\s*\)?", after)
        if w and w.group(1) != WEEK[x.weekday()]:
            issues.append(f"{fmt(x)}인데 공지에는 '{w.group(1)}요일'로 적혀 있어요")

    if dates:
        start = dates[0][0]
        end = dates[-1][0] if len(dates) > 1 else start

    # 2) 상대 표현
    if start is None:
        rel = {"오늘": 0, "금일": 0, "내일": 1, "명일": 1, "모레": 2, "글피": 3}
        for k, v in rel.items():
            if k in e:
                start = end = today + timedelta(days=v)
                break
    if start is None:
        wk = re.search(r"(이번|금|다음|다다음)\s*주", e)
        offset = {"이번": 0, "금": 0, "다음": 7, "다다음": 14}[wk.group(1)] if wk else None
        rest = e[wk.end():] if wk else e
        if wk and re.match(r"\s*말", rest):
            base = week_start(today) + timedelta(days=offset)
            start, end = base + timedelta(days=5), base + timedelta(days=6)
        else:
            days = re.findall(r"([월화수목금토일])(?:요일)?", re.sub(r"매주\s*[월화수목금토일]", "", rest))
            days = [x for x in days if x != "일" or "일요일" in rest or re.search(r"(?<![\d])일(?!\s*간)", rest)]
            if wk and days:
                base = week_start(today) + timedelta(days=offset)
                ds = sorted(base + timedelta(days=WEEK.index(x)) for x in days)
                start, end = ds[0], ds[-1]
            elif wk and "부터" in rest:
                start = week_start(today) + timedelta(days=offset)
                end = None
            elif days and not wk and not regular:
                tgt = WEEK.index(days[0])
                delta = (tgt - today.weekday()) % 7 or 7
                start = end = today + timedelta(days=delta)
                issues.append(f"요일만 적혀 있어 {fmt(start)}로 계산했어요. 맞는지 확인해 주세요")

    if start is None and regular is None:
        issues.append("공지에서 날짜를 정할 수 없어요. 날짜를 직접 입력해 주세요")
    if start and start < today:
        issues.append(f"{fmt(start)}은 이미 지난 날짜예요")
    if kind in ("영업시간 변경", "정기휴무 변경"):
        end = None
    return start, end, regular, issues


def resolve_times(expr, open_hhmm):
    """시간 표현 → (여는 시각, 닫는 시각). open_hhmm은 가게가 원래 여는 시각(HH:MM)."""
    if not expr:
        return None, None
    open_h = int(open_hhmm[:2])

    def conv(ampm, h, mm):
        h = int(h)
        if ampm in ("오후", "저녁", "밤") and h < 12:
            h += 12
        elif not ampm and h < open_h:
            h += 12
        return f"{h:02d}:{int(mm or 0):02d}"

    pat = r"(오전|오후|낮|저녁|밤)?\s*(\d{1,2})\s*(?::\s*(\d{2})|시\s*(?:(\d{1,2})\s*분|(반))?)"
    found = []
    for m in re.finditer(pat, expr):
        mm = m.group(3) or m.group(4) or ("30" if m.group(5) else None)
        found.append((conv(m.group(1), m.group(2), mm), m.end()))
    if not found:
        return None, None
    if len(found) >= 2:
        return found[0][0], found[1][0]
    t, pos = found[0]
    after = expr[pos:pos + 8]
    if re.search(r"까지|마감|닫", after):
        return None, t
    if re.search(r"부터|오픈|열|엽", after):
        return t, None
    return "?" + t, None  # 여는 시각인지 닫는 시각인지 모름
