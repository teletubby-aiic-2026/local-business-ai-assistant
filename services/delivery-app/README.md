# 동네배달 — 시연용 가상 배달앱

손님이 휴대폰으로 배달앱을 보듯 가게 메뉴를 보고, 주문하고, 리뷰를 쓰는 화면입니다.
**실제 배달앱과 연결되지 않습니다.** "배달앱과 연동되면 이렇게 된다"를 보여 주는 시연용이고, "동네배달"은 가상의 이름입니다. 주문·결제는 없고 가게와 리뷰는 모두 합성 데이터입니다.

- 손님이 리뷰를 쓰면 → 리뷰 분석 서비스(`services/review-insight`)에 `source="app"` 으로 저장 → **가게 리뷰로 쌓여** 모든 사장님 화면에 들어옵니다. 주문한 메뉴(`menu`)도 같이 저장됩니다.
- 리뷰 탭에는 합성 리뷰 40건이 "원래 있던 리뷰"로 보이고, 팀이 배달앱에서 직접 쓴 리뷰가 그 위에 쌓입니다.
- 사장님이 답글을 달면(`POST /reviews/{id}/status`) → 배달앱의 그 리뷰 아래에 "사장님" 답글로 보입니다 (5초마다 다시 확인).
- 메뉴·영업시간·공지·품절은 리뷰 분석 서비스의 **가게 정보**에서 가져옵니다. 사장님이 가게 정보를 고치면 배달앱에도 반영됩니다.

`services/web`, `shared/` 는 고치지 않았습니다. `services/review-insight` 는 배달앱 리뷰를 가게 공용으로 쌓고 `menu` 를 받도록 고쳤습니다 (`app/service.py`, `app/main.py`, `tests/test_app_reviews.py`)와 가게 계정(`app/accounts.py`, `integration/care_proxy.py`, `tests/test_accounts.py`). 통합에 필요한 일은 [`docs/handoff.md`](docs/handoff.md)에 요청으로 적었습니다.

## 구조

```
브라우저 ──▶ /shop/            배달앱 화면 (static/index.html, style.css, app.js — 빌드 없음)
          └▶ /api/shop/*       shop_routes.py 가 받아서
                                 └▶ 리뷰 분석 서비스 127.0.0.1:8020/api/review-insight/*  (토큰은 서버가 붙임)
```

| 파일 | 내용 |
|---|---|
| `shop_routes.py` | `create_shop_router()` — 화면 파일과 `/api/shop/*`. fastapi·httpx 만 쓰고 다른 서비스 코드를 import 하지 않음 |
| `static/` | 배달앱 화면. 서버 주소는 `index.html` 의 `<meta name="shop-api">` 한 곳 |
| `run_local.py` | 통합 화면 서버 없이 혼자 띄워 확인 (포트 8040) |
| `tests/` | 키·네트워크 없이 도는 시험 11개 (리뷰 분석 서비스는 가짜 응답) |
| `docs/handoff.md` | 통합 담당·리뷰 분석 담당에게 전달할 것 |

## API (`/api/shop`)

| 주소 | 하는 일 |
|---|---|
| `GET /status` | 리뷰 분석 서비스 상태 (`ready`·`down`·`off`). 항상 200 |
| `GET /store` | 가게 이름·오늘 영업·메뉴(가격, 재료, 알레르기 유발 재료, 추천, 품절)·공지 |
| `GET /reviews` | 리뷰와 사장님 답글. 손님에게 보여 줄 칸만: `id, text, rating, at, from_app, menu, reply` + 평균 별점. 합성 리뷰와 배달앱 리뷰만 (사장님이 붙여넣은 리뷰는 안 나감) |
| `POST /reviews` | `{"text": "1~1000자", "rating": 1~5, "menu": "주문 메뉴(선택)"}` → 리뷰 등록. 접속 주소당 1분 10건 |

- 브라우저는 가게(`store_id`)나 방문자(`visitor_id`)를 고를 수 없습니다. 가게는 서버가 정하고, 방문자는 보내지 않습니다.
- 분류 결과·상태 같은 사장님용 칸은 손님 화면으로 내보내지 않습니다.
- 실패는 `{"error": {"message", "state"}}` 모양이고 500 을 내지 않습니다 (통합 화면의 `care_proxy` 와 같은 모양).

## 리뷰가 어디에 쌓이나

배달앱 리뷰는 **가게 공용**입니다. 어느 기기에서 쓰든 같은 가게의 리뷰로 쌓이고, 시연하는 사람 모두의 사장님 화면(목록·분석·응대 기한)에 합쳐집니다.
사장님이 붙여넣거나 캡처한 리뷰는 지금처럼 시연자별이고 배달앱에는 보이지 않습니다. 답글은 어느 사장님 화면에서 달아도 배달앱에 보입니다.

## 어느 가게인가

- `/shop/` → 시연 가게 (`DEMO_STORE_ID`, 기본 온기한식)
- `/shop/?store=store_<가게>` → 그 가게. 계정으로 가입한 가게는 `store_<아이디>` 입니다. 그 가게의 메뉴·리뷰만 보이고 그 가게로만 등록됩니다.

배달앱의 가게·메뉴·리뷰는 손님에게 공개되는 정보라 로그인 없이 열립니다. 사장님 화면은 로그인한 가게만 봅니다 (리뷰 분석 서비스 `docs/handoff.md` 2-14).
새로 가입한 가게는 리뷰 0건, 메뉴 없음에서 시작합니다. 사장님이 가게 정보에 메뉴를 넣으면 배달앱에 보입니다. 없는 가게 주소는 404 입니다.

## 한 번에 띄워 화면 확인하기 (내 컴퓨터)

```bash
cd services/review-insight && pip install -r requirements.txt
cd ../delivery-app && pip install -r requirements.txt
python preview.py
```

리뷰 분석 서비스(mock)까지 같이 켜고, 주소와 시연용 비밀번호를 그 창에 보여 줍니다.

- `http://127.0.0.1:8040/owner/` — 사장님 **확인용** 화면: 가게 계정 로그인·가입 → 그 가게 리뷰 → 답글. 팀 통합 화면이 아니고 통합에 들어가지 않습니다 (`preview/owner.html`).
- `http://127.0.0.1:8040/shop/` — 가상 배달앱. 로그인한 뒤 "우리 가게 배달앱 열기"를 누르면 그 가게의 배달앱이 열립니다.

## 혼자 띄워 확인하기

```bash
# ① 리뷰 분석 서비스 (키 없이 mock)
cd services/review-insight && APP_MODE=mock python -m uvicorn app.main:app --host 127.0.0.1 --port 8020
# ② 가상 배달앱
cd services/delivery-app && pip install -r requirements.txt && python run_local.py     # http://127.0.0.1:8040/shop/
# 시험
cd services/delivery-app && python -m pytest -q tests
```

서비스에 `APP_ACCESS_TOKEN` 을 줬다면 ②에 `REVIEW_INSIGHT_TOKEN` 을 같은 값으로 줍니다.
사장님 답글은 리뷰 분석 서비스의 자체 화면(`http://127.0.0.1:8020/`)이나 `POST /api/review-insight/reviews/{id}/status` 로 넣어 볼 수 있습니다.

## 확인한 것 / 못 한 것

- [x] 배달앱 `pytest -q tests` 11개, 리뷰 분석 서비스 `pytest -q` 196개 통과 (키·네트워크 없음)
- [x] 리뷰 분석 서비스(브랜치 `feat/review-capture-response`, mock 모드, 토큰 켬)와 실제로 붙여 확인:
  리뷰 등록(주문 메뉴 포함) → `rv_ongi_app_001` 로 저장 → 다른 방문자(`visitor_id`)의 목록에도 보임 →
  한 방문자가 답글 기록 → 배달앱 리뷰 아래에 답글과 주문 메뉴 표시
- [ ] 통합 화면 서버(`services/web`)에 붙인 상태 (붙이는 일은 통합 담당 — handoff 1절)
- [ ] 사장님 대시보드의 새 리뷰 알림 (통합 화면 쪽 작업)
- [ ] `APP_MODE=live` (HCX-005 호출), DB 모드, WAS 2대
- [ ] 실제 휴대폰 기기 (390px 화면 크기로만 확인)

## 정직하게 밝힐 것

- 실제 배달앱 연동이 아닙니다. 화면 맨 위에 "시연용 가상 배달앱 · 실제 배달앱과 연결되지 않음"을 늘 띄웁니다.
- 주문은 화면 안에서만 일어나고 어디에도 저장되지 않습니다. 새로고침하면 주문내역이 사라집니다.
- 리뷰 탭의 합성 리뷰 40건은 실제 손님이 쓴 것이 아닙니다. 날짜는 발표 장면 날짜입니다.
- 배달앱에서 쓴 리뷰는 시연하는 사람 모두에게 보입니다 (가게 공용). 실제 손님 정보·실제 리뷰를 적지 마세요. 전화번호·이메일·링크는 저장 전에 가려집니다.
- 처음으로 돌리기: `DELETE /api/review-insight/reviews/pasted` (방문자 없이). 공용 칸에 붙여넣은 리뷰·문의도 같이 지워집니다.
- WAS 가 2대이고 DB 를 안 쓰면 리뷰·답글 기록 파일이 서버마다 달라집니다 (PR #49 handoff 와 같은 제약).
