# 비서 화면 (React + Vite)

`services/web/web/static/`(프레임워크 없는 HTML·CSS·JS)을 React 18 + Vite 로 옮긴 화면입니다. 서버 API(`/api/*`)와 화면 주소(`#/today` 등)는 그대로 쓰고, 모양은 Figma `부여 AI`의 가독성 개선판(회색 바탕·흰 카드, 본문 16px, 초록 포인트)을 따릅니다.

> 예전 화면은 지우지 않았습니다. 서버는 기본으로 예전 화면을 주고, `WEB_FRONTEND_DIST` 를 줄 때만 이 화면을 줍니다. 그래서 예전 화면 시험(`services/web/tests/*_static.py`)은 그대로 통과합니다.

## 실행

```bash
cd services/web/frontend
npm ci                    # 처음 한 번 (Node 18 이상)
npm run dev               # http://localhost:5173 , /api 는 127.0.0.1:8000 (services/web/run.sh) 으로 넘김
```

비서 화면 서버를 다른 곳에 띄웠으면 `VITE_API_TARGET=http://<주소>:8000 npm run dev`.

## 빌드와 서버에서 쓰기

```bash
npm run build             # dist/ 에 index.html 과 assets/ 가 생김 (git 에 올리지 않음)
WEB_FRONTEND_DIST=$PWD/dist services/web/run.sh      # 서버(8000)가 / 에 이 화면을 줌. /assets/* 도 같이
```

- 웹 서버(Nginx) static 모드: `deploy/install_web.sh --mode static --static-src <묶음>/services/web/frontend/dist`. `deploy/nginx/ic26-static.conf` 의 `location /` 이 `/assets/...` 를 그대로 찾습니다.
- 빌드는 Node 가 있는 PC 에서 하고 dist 를 함께 올립니다(웹 서버에 Node 를 깔지 않음).

## 시험

```bash
npm test                  # vitest: 공통 계산(오늘 할 일·AI 비서 상태 등)과 화면별 순수 함수
```

서버 스위치 시험: `services/web/tests/test_frontend_dist.py`.

## 폴더

| 폴더 | 내용 |
|---|---|
| `src/state/` | 화면 전체가 같이 보는 상태(`store.js`), 처음 불러오기·다시 불러오기(`boot.js`), 오늘 할 일·AI 비서 계산(`staff.js`), 로그아웃·가게 바꾸기(`account.js`) |
| `src/lib/` | API 부르기(`api.js`), 화면 주소(`router.js`), 이름표·지표 도우미(`domain.js`) |
| `src/components/` | 공통 부품(`ui.jsx`: 버튼·패널·숫자 타일·주제 막대·기능 카드·탭·대화상자), 왼쪽 메뉴, 상단 바 |
| `src/features/` | 화면별 코드: `flow`(홈·추천 카드·승인할 글·처리 완료), `analysis`, `marketing`, `report`, `market`, `assistant`(서랍), `account`(로그인·내 계정 창) |
| `src/styles/` | 디자인 토큰(`tokens.css`, Figma 변수와 같은 값), 공통 모양, 화면 틀 |

## 규칙

- 서버가 준 글은 JSX 로만 넣습니다(`dangerouslySetInnerHTML` 쓰지 않음).
- 색·글자 크기는 `tokens.css` 의 변수만 씁니다. 다크 값도 같은 파일에 있어서, 변수만 쓰면 다크 모드가 저절로 맞습니다.
- 화면 모양: 운영체제 설정을 따르고, 상단 바 버튼으로 시스템 → 밝게 → 어둡게를 고릅니다(`src/lib/theme.js`, localStorage `ic26.theme`, 주소 `?theme=light|dark` 는 저장하지 않고 그 화면만). 인쇄(종합 리포트 PDF)는 늘 밝게 나옵니다.
- 가게가 바뀌면(로그인·로그아웃·가게 바꾸기·기록 지우기) 상태의 `epoch` 가 1 오르고, 각 화면은 자기 상태를 처음으로 되돌립니다.
- 아이콘·로고는 아직 자리 모양입니다(`Icon` 부품). Figma `04 에셋`의 자리 부품에 그림이 들어오면 `ui.jsx` 의 `ICONS` 에 SVG 를 넣습니다.
