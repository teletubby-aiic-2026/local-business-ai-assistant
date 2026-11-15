# 전달 문서: 시연용 가상 배달앱 (`services/delivery-app`)

가상 배달앱은 `services/delivery-app/` 안에만 만들었습니다. 아래는 다른 영역에서 해 주셔야 하는 일입니다.
기준: 브랜치 `feat/review-capture-response` (PR #49, `d9391cb`).

## 0. 한눈에

- 배달앱 화면 `/shop/`, API `/api/shop/*`. 통합 화면 서버가 라우터 하나를 붙이면 됩니다 (1절, `care_proxy` 와 같은 방식).
- 배달앱 리뷰는 **가게 공용**입니다 (11/15 정함). 리뷰 분석 서비스가 `source="app"` 리뷰를 공용 칸에 쌓고 모든 방문자 화면에 합쳐 줍니다. 그래서 배달앱은 방문자 쿠키를 쓰지 않고, 아무 기기에서 열어도 됩니다.
- 이 브랜치에서 리뷰 분석 서비스도 같이 고쳤습니다 (2절).

## 1. 통합 화면 서버(`services/web`)에 부탁드릴 것 — 통합 담당

| # | 할 일 | 내용 |
|---|---|---|
| 1 | 라우터 붙이기 | `services/delivery-app/shop_routes.py` → `services/web/web/shop_routes.py`, `services/delivery-app/static/` → `services/web/web/shop_static/` 로 복사. `main.py` 에 `app.include_router(create_shop_router(static_dir=Path(__file__).parent / "shop_static"))` |
| 2 | 환경 변수 | `care_proxy` 와 같은 `REVIEW_INSIGHT_URL`·`REVIEW_INSIGHT_TOKEN`·`DEMO_STORE_ID` 를 그대로 씁니다. 새로 필요한 것 없음 |
| 3 | Nginx | `/shop/` 과 `/api/shop/` 이 WAS 로 넘어가게. 지금 `location /` 가 화면 파일을 주는 구조라면 `/shop/` 을 WAS 로 넘기거나, `shop_static/` 을 웹 서버에 복사하고 `location /shop/ { alias … }` 를 추가 |
| 4 | 사장님 답글 기록 | 답글 승인 때 `POST /api/care/reviews/{review_id}/status {"status":"replied","reply_text":…}` (PR #49 handoff 9-4와 같은 일). **이 호출이 있어야 배달앱에 사장님 답글이 보입니다** |
| 5 | 새 리뷰 알림 | 대시보드가 5~10초마다 `GET /api/care/reviews?since=<직전 server_time>` 를 불러 `source=="app"` 인 새 리뷰를 알림으로. (PR #49 handoff 4-3과 같은 일) |
| 6 | 계약 시험 | `contract.md 2.4`(화면 파일에 `/api/review-insight` 글자 금지)는 지켰습니다. 배달앱 화면 파일은 `/api/shop` 만 부릅니다 |
| 7 | 공개 범위 결정 | `/shop/`, `/api/shop/*` 는 로그인 없이 열립니다. 리뷰 등록마다 서비스가 분류를 다시 하므로(HCX 분당 60회 한도) 배달앱 쪽에서 접속 주소당 1분 10건으로 막았습니다. 발표장 밖에 공개할지는 팀 결정 |

## 2. 리뷰 분석 서비스에서 바꾼 것 (`services/review-insight`)

| 바꾼 것 | 내용 |
|---|---|
| 배달앱 리뷰는 가게 공용 | `POST /reviews {source:"app"}` 은 `visitor_id` 가 있어도 공용 칸에 저장. id 는 `rv_<가게>_app_NNN`. 모든 방문자의 `GET /reviews`·`/insight`·`/response`·보고서에 합쳐짐 |
| 답글·상태도 공용 | 배달앱 리뷰의 `POST /reviews/{id}/status` 는 어느 방문자가 불러도 공용 칸에 기록 → 배달앱과 다른 시연자 화면에 같이 보임 |
| 주문 메뉴 | 등록 요청의 `menu`(선택, 40자 이하) → 조회 응답 항목의 `menu` (없으면 `null`). 계약 `Review` 는 건드리지 않고 `source`·`reply` 와 같은 기록 칸에 둠 |
| 지우기 | 시연자의 `DELETE /reviews/pasted?visitor_id=` 는 배달앱 리뷰를 지우지 않음. `visitor_id` 없이 부르면 공용 칸(배달앱 리뷰 포함)을 지움 |

아직 안 한 것: 메뉴별 불만 집계(`menu` 는 저장·표시만), 손님용 조회 주소(배달앱 라우터가 손님용 칸만 골라 내보냄), 배달앱 리뷰만 골라 지우기.

통합 화면 쪽에서 달라지는 점: 사장님 화면의 `GET /api/care/reviews` 에 다른 시연자가 배달앱에서 쓴 리뷰도 나옵니다 (`source=="app"`, `menu`). 붙여넣기·캡처는 지금처럼 시연자별입니다.

## 2-1. 가게 계정 (11/15)

- 사장님 화면: 가게 계정으로 로그인하면 그 가게의 리뷰만 봅니다. 구현과 통합 담당께 부탁드릴 일은 `services/review-insight/docs/handoff.md` 2-14.
- 배달앱: `/shop/?store=store_<가게>` 로 가게마다 주소가 다릅니다. `/shop/` 은 시연 가게. 통합 화면에서 "우리 가게 배달앱 열기" 링크를 만든다면 `GET /api/care/auth/me` 의 `store_id` 를 붙이면 됩니다.

## 3. 시연 순서 (통합 뒤)

1. 노트북에서 사장님 화면을 엽니다.
2. 휴대폰에서 `/shop/` 을 엽니다 (주소만 알면 됨).
3. 메뉴를 담아 주문 → 주문내역 → 리뷰 쓰기.
4. 노트북 사장님 화면에 새 리뷰 알림 → 답글 승인.
5. 휴대폰 리뷰 탭에 5초 안에 "사장님" 답글이 보입니다.

4번의 알림과 답글 기록은 1절의 4·5번이 되어 있어야 합니다.
