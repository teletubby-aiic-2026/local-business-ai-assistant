# 비서 화면 (React + Vite)

비서 화면의 유일한 화면입니다 (11/20부터. 예전 `services/web/web/static/` 을 React 18 + Vite 5 로 옮긴 PR #69 뒤 예전 화면은 지움). 서버 API(`/api/*`)와 화면 주소(`#/today` 등)는 그대로 쓰고, 모양은 Figma `부여 AI`의 가독성 개선판(회색 바탕·흰 카드, 본문 16px, 초록 포인트)과 밝게·어둡게·시스템 화면 모양을 따릅니다.

## 실행

```bash
cd services/web/frontend
npm ci                    # 처음 한 번 (Node 20 이상)
npm run dev               # http://localhost:5173 , /api 는 127.0.0.1:8000 (services/web/run.sh) 으로 넘김
```

비서 화면 서버를 다른 곳에 띄웠으면 `VITE_API_TARGET=http://<주소>:8000 npm run dev`.

## 빌드와 서버에서 쓰기

```bash
npm run build             # dist/ 에 index.html 과 assets/ 가 생김 (git 에 올리지 않음)
services/web/run.sh       # 서버(8000)가 / 에 dist/index.html, /assets/* 에 빌드 파일을 줌 (빌드가 없거나 오래되면 run.sh 가 먼저 빌드)
```

- 웹 서버(Nginx) static 모드: `deploy/install_web.sh --mode static --static-src <묶음>/services/web/frontend/dist`. `deploy/nginx/ic26-static.conf` 의 `location /` 이 `/assets/...` 를 그대로 찾습니다.
- 빌드는 Node 가 있는 PC 에서 합니다. `deploy/make_bundle.sh` 가 묶을 커밋의 소스로 빌드해 dist 를 넣습니다(서버에 Node 를 깔지 않음).

## 시험

```bash
npm test                  # vitest: 화면 틀·계정·덮는 메뉴 포커스, 화면별 계산과 화면 (140건, 11/20)
```

서버 시험 중 화면 소스를 글자로 읽는 것과 서빙 시험은 `docs/api/contract.md` 2.4 에 정리했습니다 (`services/web/tests/frontend_src.py`, `test_frontend_dist.py`).

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
- 아이콘은 `ui.jsx` 의 `ICONS`(24×24 선 SVG, JSX)에 이름으로 넣습니다. 메뉴 8·숫자 타일 6·맞춤 마케팅 카드 6·공용 아이콘이 있고, 모르는 이름은 글자 없는 기본 모양이 나옵니다. 로고는 `Logo`(말풍선).
- 휴대폰(760px 이하): 왼쪽 메뉴 대신 아래 탭 5칸(홈·오늘 처리·AI에게 묻기·살펴보기·마케팅)과 묶음 하위 탭(`components/MobileNav.jsx`), 상단 바는 한 줄. Figma `부여 AI`에는 모바일(375) 틀이 없어(00 안내) 왼쪽 메뉴 묶음과 '메뉴 항목/현재' 모양을 옮겼습니다.
- 폭은 본문 실제 폭으로 가릅니다: `.content` 가 크기 컨테이너(`content`)라 화면 CSS 는 `@container content (max-width: …)` 를 씁니다. 서랍은 본문이 680px 이상 남을 때만 본문을 밀고 아니면 덮습니다 (`docs/api/contract.md` 2.9).
