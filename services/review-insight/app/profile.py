"""응대용 가게 정보: 처음 한 번 입력하고, 바뀔 때만 등록한다.

계약의 StoreProfile(GET /store, 이름·업종·메뉴 이름)은 그대로 두고, 고객응대에 필요한 것만 여기서 받는다.
위치·업종은 상권 서비스의 분석 조건(/api/onboarding/profile)과 겹치므로 받지 않는다 (docs/handoff.md).

| 묶음      | 쓰는 곳 |
| basic     | 문의 자동 답변 (영업시간·휴무·주차·주소) |
| order     | 문의 자동 답변 (배달 지역·최소 주문·포장·단체 주문) |
| menu      | 문의 답변의 메뉴·가격·맵기·재료. 알레르기는 표시만 하고 자동으로 "괜찮다"고 답하지 않는다 |
| policy    | 답변 초안이 지킬 수 있는 약속만 쓰게 하는 근거 (환불이 비어 있으면 환불을 약속하지 않음) |
| reply     | 말투·끝인사·피크 시간·답글 기한 |
| notices   | 임시 공지 (임시휴무·품절·시간 변경). 끝나는 날이 지나면 저절로 빠진다 → 되돌리는 일을 잊어도 틀린 안내가 안 나감 |
| answers   | 배운 답: 가게 정보에 없던 문의에 사장님이 답하고 "저장"을 누른 것. 다음 같은 문의에 쓴다 |

저장
- 처음 값: data/care/<가게>.json (합성 가게 3곳의 가상 예시, data_origin=synthetic). 없으면 빈 틀.
- 사장님이 고친 값: data/runtime/care_profile_<가게>.json (가게 공용. 시연자마다 나누지 않음). 읽기·쓰기는 이 파일의 load·save 두 함수뿐 → DB 로 바꿔 끼우기 쉽게.
"""
from __future__ import annotations

import copy
import json
import threading
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = ROOT / "data" / "care"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_NAMES = dict(zip(DAYS, ("월", "화", "수", "목", "금", "토", "일")))
CLOSED = "휴무"
_lock = threading.RLock()


def _hhmm(value: str) -> str:
    h, sep, m = value.partition(":")
    if not sep or not (h.isdigit() and m.isdigit()) or not (0 <= int(h) <= 24 and 0 <= int(m) < 60):
        raise ValueError(f"시각은 HH:MM 형식이어야 합니다: {value!r}")
    return f"{int(h):02d}:{int(m):02d}"


def _range(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if value == CLOSED:
        return CLOSED
    a, sep, b = value.partition("-")
    if not sep:
        raise ValueError(f"시간은 '11:00-21:00' 형식이어야 합니다: {value!r}")
    return f"{_hhmm(a.strip())}-{_hhmm(b.strip())}"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Basic(_Strict):
    hours: dict[str, Optional[str]] = Field(default_factory=dict, description="요일(mon~sun) → '11:00-21:00' 또는 '휴무'. 새벽까지면 '16:00-01:00'")
    break_time: Optional[str] = None
    last_order: Optional[str] = None
    holidays: Optional[str] = Field(None, max_length=100)
    address: Optional[str] = Field(None, max_length=200)
    parking: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=30)

    @field_validator("hours")
    @classmethod
    def _hours(cls, v):
        bad = [d for d in v if d not in DAYS]
        if bad:
            raise ValueError(f"요일은 {', '.join(DAYS)} 중 하나여야 합니다: {bad}")
        return {d: _range(t) for d, t in v.items()}

    @field_validator("break_time")
    @classmethod
    def _break(cls, v):
        return _range(v)

    @field_validator("last_order")
    @classmethod
    def _last(cls, v):
        return _hhmm(v) if v else None


class Order(_Strict):
    delivery_area: Optional[str] = Field(None, max_length=200)
    min_order: Optional[int] = Field(None, ge=0, le=1_000_000)
    takeout: Optional[bool] = None
    group_order: Optional[str] = Field(None, max_length=200)


class MenuItem(_Strict):
    name: str = Field(..., min_length=1, max_length=40)
    price: Optional[int] = Field(None, ge=0, le=1_000_000)
    ingredients: list[str] = Field(default_factory=list, max_length=30)
    spicy: int = Field(0, ge=0, le=3, description="0 안 매움 ~ 3 아주 매움")
    allergens: list[str] = Field(default_factory=list, max_length=20, description="사장님이 확인한 알레르기 유발 재료만")
    recommended: bool = False
    sold_out: bool = False


class Extra(_Strict):
    title: str = Field(..., min_length=1, max_length=40)
    text: str = Field(..., min_length=1, max_length=300)


class Policy(_Strict):
    remake: Optional[str] = Field(None, max_length=300)
    refund: Optional[str] = Field(None, max_length=300)
    reservation: Optional[str] = Field(None, max_length=300)
    pets: Optional[str] = Field(None, max_length=300)
    extra: list[Extra] = Field(default_factory=list, max_length=20)


class Reply(_Strict):
    tone: Literal["polite", "friendly"] = "polite"
    sign_off: Optional[str] = Field(None, max_length=40)
    peak_hours: Optional[str] = Field(None, max_length=40)
    sla_minutes: int = Field(30, ge=5, le=24 * 60)


LangCode = Literal["en", "ja", "zh-CN", "zh-TW", "vi", "th", "id", "fr", "es", "ru", "de", "it"]


class Foreign(_Strict):
    languages: list[LangCode] = Field(default_factory=list)
    # 사장님이 고친 번역: {"en": {"제육볶음 정식": {"name": "Jeyuk (spicy pork) set", "desc": "..."}}}
    overrides: dict[LangCode, dict[str, dict[Literal["name", "desc"], str]]] = Field(default_factory=dict)


class Notice(_Strict):
    id: str = ""
    kind: Literal["closed", "sold_out", "hours", "other"] = "other"
    text: str = Field(..., min_length=1, max_length=200)
    start: date
    end: date
    menu: Optional[str] = Field(None, max_length=40, description="kind=sold_out 일 때 품절 메뉴 이름")
    hours: Optional[str] = Field(None, description="kind=hours 일 때 바뀐 영업시간 '12:00-18:00'")

    @field_validator("hours")
    @classmethod
    def _h(cls, v):
        return _range(v)


class Answer(_Strict):
    id: str = ""
    question: str = Field(..., min_length=2, max_length=300)
    answer: str = Field(..., min_length=1, max_length=500)
    saved_at: Optional[str] = None
    from_item: Optional[str] = None


class Profile(_Strict):
    store_id: str
    data_origin: Literal["synthetic", "real"] = "synthetic"
    basic: Basic = Field(default_factory=Basic)
    order: Order = Field(default_factory=Order)
    menu: list[MenuItem] = Field(default_factory=list, max_length=200)
    policy: Policy = Field(default_factory=Policy)
    reply: Reply = Field(default_factory=Reply)
    foreign: Foreign = Field(default_factory=Foreign)
    notices: list[Notice] = Field(default_factory=list, max_length=100)
    answers: list[Answer] = Field(default_factory=list, max_length=300)
    updated_at: Optional[str] = None


SECTIONS = ("basic", "order", "menu", "policy", "reply", "foreign")


# ── 저장 (DB 로 바꿀 때는 이 두 함수만) ───────────────────────────
def _file(store_id: str, visitor_id: str | None = None) -> Path:
    """가게 정보는 **가게 공용** 하나다 (visitor_id 는 받지만 쓰지 않음).
    손님 문의 페이지가 이 정보로 답하고, 사장님이 저장한 '배운 답'이 다음 손님에게 쓰여야 하므로 시연자마다 나누지 않는다 (11/15)."""
    from app import service
    service._dir(store_id)
    return service.RUNTIME / f"care_profile_{store_id}.json"


def load(store_id: str, visitor_id: str | None = None) -> Profile:
    for path in (_file(store_id, visitor_id), DEFAULTS / f"{store_id}.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        data.pop("_note", None)
        return Profile.model_validate(data)
    return _registered_start(store_id) or Profile(store_id=store_id)


def _registered_start(store_id: str) -> Profile | None:
    """직접 등록한 가게(11/20)의 처음 값: 등록 때 받은 메뉴·가격·도로명 주소·끝인사. 그 밖의 칸은 빈 틀 (사장님이 채움)."""
    from app import registered, service
    if not service.is_registered(store_id):
        return None
    found = registered.get(store_id) or {}
    location = found.get("location") or {}
    name = found.get("name") or ""
    return Profile(store_id=store_id, data_origin="real",
                   basic=Basic(address=location.get("road_address")),
                   menu=[MenuItem(name=m["name"], price=m["price"]) for m in found.get("menus") or []],
                   reply=Reply(sign_off=f"{name} 드림" if name else None))


def save(profile: Profile, visitor_id: str | None = None) -> Profile:
    from app import service
    profile.updated_at = datetime.now(service.KST).isoformat(timespec="seconds")
    path = _file(profile.store_id, visitor_id)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(profile.model_dump_json(indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)
    return profile


def reset(store_id: str, visitor_id: str | None = None) -> None:
    try:
        _file(store_id, visitor_id).unlink()
    except FileNotFoundError:
        pass


# ── 바꾸기 ────────────────────────────────────────────────────────
def update(store_id: str, visitor_id: str | None, changes: dict) -> Profile:
    """묶음 단위로 덮어쓴다 (basic·order·menu·policy·reply·foreign). 다른 칸은 400."""
    bad = [k for k in changes if k not in SECTIONS]
    if bad:
        raise ValueError(f"고칠 수 있는 묶음은 {', '.join(SECTIONS)} 입니다: {bad}")
    with _lock:
        data = load(store_id, visitor_id).model_dump(mode="json")
        data.update(copy.deepcopy(changes))
        return save(Profile.model_validate(data), visitor_id)


def add_notice(store_id: str, visitor_id: str | None, notice: dict) -> Notice:
    item = Notice.model_validate({**notice, "id": "nt_" + uuid.uuid4().hex[:8]})
    if item.end < item.start:
        raise ValueError("끝나는 날이 시작하는 날보다 빠릅니다")
    if item.kind == "sold_out" and not item.menu:
        raise ValueError("품절 공지는 menu(메뉴 이름)가 필요합니다")
    if item.kind == "hours" and not item.hours:
        raise ValueError("시간 변경 공지는 hours('12:00-18:00')가 필요합니다")
    with _lock:
        p = load(store_id, visitor_id)
        p.notices.append(item)
        save(p, visitor_id)
    return item


def remove(store_id: str, visitor_id: str | None, kind: Literal["notices", "answers"], item_id: str) -> bool:
    with _lock:
        p = load(store_id, visitor_id)
        rows = getattr(p, kind)
        keep = [x for x in rows if x.id != item_id]
        if len(keep) == len(rows):
            return False
        setattr(p, kind, keep)
        save(p, visitor_id)
    return True


def add_answer(store_id: str, visitor_id: str | None, question: str, answer: str, from_item: str | None = None) -> Answer:
    from app import service
    item = Answer(id="an_" + uuid.uuid4().hex[:8], question=" ".join(question.split())[:300], answer=answer.strip(),
                  saved_at=datetime.now(service.KST).isoformat(timespec="seconds"), from_item=from_item)
    with _lock:
        p = load(store_id, visitor_id)
        p.answers.append(item)
        save(p, visitor_id)
    return item


# ── 읽기 도우미 ───────────────────────────────────────────────────
def active_notices(p: Profile, today: date) -> list[Notice]:
    return [n for n in p.notices if n.start <= today <= n.end]


def setup_state(p: Profile) -> dict:
    """처음 설정이 끝났는지. 꼭 있어야 하는 것: 영업시간(요일 하나 이상), 가격 있는 메뉴 하나 이상, 답글 말투(기본값 있음)."""
    missing = []
    if not any(v for v in p.basic.hours.values()):
        missing.append({"field": "basic.hours", "label": "영업시간"})
    if not any(m.price is not None for m in p.menu):
        missing.append({"field": "menu", "label": "메뉴와 가격"})
    optional = [label for field, label, value in (
        ("basic.parking", "주차", p.basic.parking), ("order.delivery_area", "배달 지역", p.order.delivery_area),
        ("policy.remake", "다시 만들어 주는 기준", p.policy.remake), ("basic.break_time", "브레이크타임", p.basic.break_time),
    ) if not value]
    return {"done": not missing, "missing": missing, "later": optional}


def hours_on(p: Profile, day: date) -> tuple[str | None, list[Notice]]:
    """그날 영업시간 (임시 공지 반영). None 이면 모름, '휴무' 면 쉼."""
    notices = active_notices(p, day)
    if any(n.kind == "closed" for n in notices):
        return CLOSED, notices
    changed = next((n.hours for n in notices if n.kind == "hours"), None)
    return changed or p.basic.hours.get(DAYS[day.weekday()]), notices


def view(p: Profile, now: datetime) -> dict:
    """화면·통합 서버에 주는 모양: 저장된 값 + 지금 유효한 공지 + 오늘 영업시간 + 처음 설정 상태."""
    today = now.date()
    hours, notices = hours_on(p, today)
    sold_out = {n.menu for n in notices if n.kind == "sold_out"} | {m.name for m in p.menu if m.sold_out}
    data = p.model_dump(mode="json")
    data["today"] = {"date": today.isoformat(), "day": DAY_NAMES[DAYS[today.weekday()]], "hours": hours,
                     "sold_out": sorted(sold_out)}
    data["active_notices"] = [n.model_dump(mode="json") for n in notices]
    data["expired_notices"] = sum(1 for n in p.notices if n.end < today)
    data["setup"] = setup_state(p)
    return data
