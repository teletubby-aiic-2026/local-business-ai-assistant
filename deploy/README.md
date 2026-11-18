# 서버 설치 묶음 (deploy/)

네이버클라우드 서버에 이 앱을 올리는 파일 묶음입니다. 구성은 `docs/infra/architecture.md`, 순서와 확인 항목은 `인프라/10 …체크리스트 (v0.8)`의 단계 7~10, 13을 따릅니다.
이 문서에는 키, 비밀번호, 공인 IP, 실제 도메인을 적지 않습니다. 꺾쇠(`<...>`)로 쓴 곳은 직접 채웁니다.

## 0. 한눈에

```
PC ──(scp, 베스천 거침)──▶ ic26-was1 ─ install_was.sh ─▶ ic26-review    (127.0.0.1:8020)
   코드 묶음 ic26-<커밋>.tgz                           ├▶ ic26-marketing (127.0.0.1:8030)  ← 맞춤 마케팅. 비서 화면 서버만 부름
   자료 묶음 seoul-market-data-….tar.gz                 └▶ ic26-was       (0.0.0.0:8000)    ← 내부 로드 밸런서가 부름
                             ─ install_market_data.sh ─▶ ic26-market    (127.0.0.1:8766)  ← 상권. 비서 화면 서버만 부름 (서랍)
웹 서버 ─ install_web.sh ─▶ Nginx (80)  ── /api 또는 전체 ──▶ 내부 로드 밸런서 ─▶ WAS
```

| 파일 | 어디서 쓰나 | 하는 일 |
|---|---|---|
| `make_bundle.sh` | PC | `origin/main`(또는 준 커밋)을 `git archive`로 묶어 `ic26-<커밋>.tgz`와 체크섬을 만듦. 안에 `REVISION`(커밋 해시) 포함 |
| `install_was.sh` | WAS 서버 | 패키지, 계정, 코드, 쓰기 폴더, 환경 파일 틀, venv, 서비스 등록. 다시 돌려도 안전. **코드 갱신에도 같은 스크립트**. 상권 자료가 깔려 있으면 `ic26-market`도 켬 |
| `install_market_data.sh` | WAS 서버 | 상권 공식 자료 묶음(따로 받은 `.tar.gz` 하나)을 확인(SHA-256·MANIFEST 851개)하고 `/opt/ic26` 제자리에 깔고 `ic26-market`을 켬. 4-1절 |
| `env.example` | WAS 서버 | `/etc/ic26/env`의 틀. 변수 이름과 설명만 있고 키·비밀번호 값은 비어 있음 |
| `systemd/ic26-review.service` | WAS 서버 | 리뷰 분석 (127.0.0.1:8020) |
| `systemd/ic26-was.service` | WAS 서버 | 비서 화면 서버 (0.0.0.0:8000, 상태 확인 `/api/health`) |
| `systemd/ic26-market.service` | WAS 서버 | 상권 서비스 (127.0.0.1:8766). 상권 자료를 깔면 켬 (자료가 없으면 파일만) |
| `systemd/ic26-marketing.service` | WAS 서버 | 맞춤 마케팅 서버 (127.0.0.1:8030, 상태 확인 `/health`). 10-2절 |
| `smoke_test.sh` | WAS 서버, 웹 서버 | `/api/health`와 `/api/briefing`, 맞춤 마케팅 `/health`, 상권 `/health`와 서랍 `ready` 확인. `--generate`로 글 생성·상권 질문 1회씩 |
| `prepare_image.sh` | WAS 서버 | 서버 이미지를 만들기 전에 키 값과 실행 중 데이터를 비움 |
| `install_web.sh` | 웹 서버 | Nginx 설치와 설정 넣기 (1단계 또는 2단계) |
| `nginx/ic26-proxy-all.conf` | 웹 서버 | (가) 1단계: 모든 요청을 WAS로 |
| `nginx/ic26-static.conf` | 웹 서버 | (나) 2단계: 화면 파일은 웹 서버가, `/api/`만 WAS로 |

순서 (11/14 계획의 2단계 기준):

- **1단계, 토요일 밤**: 2(묶기) → 3(올리기) → 4(설치) → 5(키 넣기) → 6(확인). `ic26-was1` 한 대만 세웁니다.
- **1단계, 일요일**: 9(웹 서버)와 로드 밸런서. WAS 타겟에는 `ic26-was1`만 넣습니다.
- **2단계, 월요일**: 완성본을 8(갱신)로 올린 뒤, 7(이미지, 다음 서버)을 **한 번만** 합니다. 주말에는 이미지를 만들지 않습니다(DB, 상권, 보고서가 들어오면 다시 만들어야 하기 때문).
- **11/18 바뀐 점**: 상권 공식 자료가 들어왔습니다(PR #62, 김진수 님). 자료는 코드 묶음에 넣지 않고 **자료 묶음 하나**로 따로 올립니다. 4(설치) 다음에 **4-1(상권 자료)** 을 합니다. 서버 이미지를 뜨면 자료도 이미지에 담기므로, 이미지로 만든 서버에는 4-1을 다시 하지 않아도 됩니다.

## 1. 시작 전에

- PC에 `git`, `ssh`, `scp`가 있습니다. 인증키(`.pem`)는 PC에만 두고 `chmod 400`을 합니다.
- 콘솔에서 만든 것: 베스천 `ic26-jump`, 서버 `ic26-was1`(Ubuntu 24.04, `ic26-pri-was1`, 공인 IP 없음, `ic26-was-acg`), NAT 경로.
  설치할 때 `apt`와 `pip`가 인터넷에 나가므로 NAT 경로가 있어야 합니다.
- 서버 전용 HCX 키를 준비합니다. 개발용 키(`~/.config/teletubby-aiic/env`)를 서버로 복사하지 않습니다.
- Ubuntu 이미지의 첫 접속 계정과 `sudo` 여부는 아직 확인하지 못했습니다. 아래 `<접속 계정>`은 콘솔에서 확인한 계정입니다. `root`로 들어가면 명령 앞의 `sudo`는 빼도 됩니다.

## 2. PC에서: 묶음 만들기

```bash
cd <저장소 폴더>
deploy/make_bundle.sh --out ~/ic26-bundles
```

- 기본은 `origin/main`의 최신 커밋입니다(먼저 `git fetch`). 로컬 `main` 브랜치나 `wt/main` 폴더는 쓰지 않습니다.
- 다른 커밋을 올리려면 `deploy/make_bundle.sh <커밋 또는 브랜치>`. `origin/main`에 없는 커밋이면 경고가 나옵니다.
- 작업 폴더에서 고치던 파일은 묶이지 않습니다. 커밋된 것만 묶입니다.
- 그 커밋에 `deploy/`가 아직 없으면(병합 전) 이 PC의 `deploy/` 폴더를 묶음에 더하고 경고를 냅니다. 어느 쪽인지는 묶음 안 `deploy/BUNDLE_INFO`에 남습니다.
- 끝나면 `~/ic26-bundles/ic26-<커밋 7자리>.tgz`와 `.tgz.sha256`이 생깁니다. 출력된 커밋 해시가 올리려던 커밋인지 봅니다.

## 3. PC에서: 베스천을 거쳐 올리기

`~/.ssh/config`에 한 번 적어 둡니다(값은 직접 채움).

```
Host ic26-jump
    HostName <베스천 공인 IP>
    User <접속 계정>
    IdentityFile <인증키 경로>

Host ic26-was1
    HostName <ic26-was1 사설 IP>
    User <접속 계정>
    IdentityFile <인증키 경로>
    ProxyJump ic26-jump
```

```bash
cd ~/ic26-bundles
scp ic26-<커밋>.tgz ic26-<커밋>.tgz.sha256 ic26-was1:~/
# 상권 자료 묶음 (68MB, 처음 한 번. 팀장 PC의 인프라/bundles/ 에 체크섬과 함께 있음)
scp seoul-market-data-20261116.tar.gz seoul-market-data-20261116.tar.gz.sha256 ic26-was1:~/
```

## 4. 서버에서: 설치

```bash
ssh ic26-was1
cd ~
sha256sum -c ic26-<커밋>.tgz.sha256          # OK 가 나와야 함
tar -xzf ic26-<커밋>.tgz                     # ic26-<커밋>/ 폴더가 생김. /opt/ic26 안에 풀지 않음
sudo bash ic26-<커밋>/deploy/install_was.sh
```

설치 스크립트가 하는 일 (여러 번 돌려도 같은 결과):

1. `apt`로 `python3`, `python3-venv`, `rsync`, `postgresql-client` 등 설치. 시간대 Asia/Seoul. `ufw`가 켜져 있으면 경고만 합니다.
2. 실행 계정 `ic26`(로그인 불가)를 만듭니다.
3. 코드를 `/opt/ic26`에 맞춥니다(root 소유). `REVISION` 파일도 함께 들어갑니다.
4. 쓰기 폴더를 `ic26` 소유로 잡습니다: `services/review-insight/{logs,data/runtime,data/replay}`, `experiments/marketing/results`, `/var/lib/ic26/runtime`(= `WEB_RUNTIME_DIR`, 승인 기록), `/var/lib/ic26/market`(상권 SQLite), `/var/lib/ic26/marketing`(= `MARKETING_RECORDS_DIR`, 맞춤 마케팅 기록).
5. `/etc/ic26/env`가 **없을 때만** `env.example`로 만듭니다(root 소유, 권한 600). 있으면 건드리지 않고, 빠진 변수 이름만 알려 줍니다.
6. `/opt/ic26/.venv`를 만들고 requirements를 설치합니다. 맞춤 마케팅 서버가 이 venv로 import 되는지도 봅니다(안 되면 주의만 출력).
7. 서비스 파일을 `/etc/systemd/system/`에 넣고 `ic26-review`, `ic26-marketing`, `ic26-was`를 enable하고 시작합니다. `ic26-market`은 파일만 넣고 켜지 않습니다.

옵션: `--no-start`(등록만), `--skip-apt`, `--skip-pip`, `--no-systemd`(컨테이너 시험용).
이 시점에는 키가 비어 있어 `APP_MODE=live`라서 `/api/health`에 막힘 항목이 보이는 것이 정상입니다.
7번에서 상권 공식 자료가 이미 깔려 있으면(`/opt/ic26/services/market-analysis/data/official/onboarding_analysis_catalog.json`과 `data/raw/official/`) `ic26-market`도 enable하고 다시 시작합니다. 처음 설치에는 자료가 없으므로 4-1절로 깝니다.

## 4-1. 서버에서: 상권 자료 깔기 (처음 한 번, 자료가 바뀔 때)

상권 서비스는 서울시 상권분석서비스의 공식 자료(2024년 3분기~2026년 2분기 8분기 + 2026년 2분기 보조자료 4종)를 파일로 읽습니다. 이 자료는 git에 없고(약 740MB) 코드 묶음에도 넣지 않습니다. 팀이 확인한 자료 묶음 하나를 따로 올려 깝니다. **서버에서 서울시 OpenAPI로 새로 모으지 않습니다**(`--collect` 금지: 같은 분기라도 공개·정정 상태에 따라 값이 달라져 검증한 자료와 다른 판이 됨).

```bash
cd ~
sha256sum -c seoul-market-data-20261116.tar.gz.sha256      # OK
sudo bash ic26-<커밋>/deploy/install_market_data.sh ~/seoul-market-data-20261116.tar.gz
bash ic26-<커밋>/deploy/smoke_test.sh --market
```

`install_market_data.sh`가 하는 일:

1. 압축 파일의 SHA-256을 옆의 `.sha256`(없으면 스크립트에 적힌 알려진 값)과 대조합니다. 멤버가 모두 보통 파일·폴더이고 절대 경로·`..`·링크가 없는지 봅니다.
2. `/opt/ic26`과 같은 디스크의 빈 임시 폴더에 풀고, `MANIFEST.json`의 851개 파일마다 바이트 수와 SHA-256을 대조합니다. 하나라도 다르면 멈춥니다. 디스크 여유가 모자라면 풀기 전에 멈춥니다(풀면 약 750MB).
3. 제자리에 둡니다(root 소유, 폴더 755·파일 644, 서비스 계정은 읽기만).
   - `services/market-analysis/data/**` → `/opt/ic26/services/market-analysis/data/` (원본 `data/raw/official` 838개, 분석 카탈로그, 보조자료 4종)
   - `source-downloads/**` → `/opt/ic26/source-downloads/` (가공 전 원본 보존용. 앱은 읽지 않음)
   - `services/market-analysis/app/*.json`, `data/scenario/snapshot_2026Q2.json`은 코드 묶음에도 있습니다. 줄바꿈만 다르고 내용이 같으면 코드 쪽을 그대로 두고, 다르면 덮지 않고 주의를 띄웁니다.
4. `ic26-market`을 enable하고 다시 시작합니다(상권 서비스는 켜질 때 자료를 읽어 둠). `/health`가 60초 안에 답하는지 봅니다. `/etc/ic26/env`의 `ASSISTANT_ENABLED=1`, `ASSISTANT_PLANNER=off`, live일 때 `CLOVA_STUDIO_API_KEY`가 있는지 이름만 봅니다.

- 다시 돌려도 안전합니다. 같은 자료면 그대로 두고, 이미 깔린 파일과 내용이 다른 파일이 있으면 **덮지 않고 멈춥니다**. 새 판으로 바꾸려면 `--replace`(옛 자료를 `data.bak-<시각>`으로 옮겨 둠).
- `--check`는 풀어서 확인만 합니다. `--no-systemd`는 컨테이너 시험용입니다.
- 어느 묶음을 깔았는지는 `/var/lib/ic26/market-data.installed`에 남습니다.
- `install_was.sh`로 코드를 갱신해도 상권 자료와 `/opt/ic26/source-downloads/`는 지워지지 않습니다.

## 5. 서버에서: 키 넣기 (손으로)

**편집기로 직접 입력합니다. 키를 명령줄 인자(`echo`, `export`, `sed -i` 등)나 셸 히스토리에 남기지 않습니다.**
메신저, 메모장, 화면 캡처를 거치지 않습니다.

```bash
sudo vi -n -i NONE /etc/ic26/env        # -n -i NONE: 임시 파일(.swp)과 viminfo 에 값이 남지 않게 함
```

넣을 것:

- `CLOVA_API_KEY`, `CLOVASTUDIO_API_KEY`, `CLOVA_STUDIO_API_KEY` **세 줄에 같은 서버 전용 키**를 넣습니다. 코드마다 읽는 이름이 달라서 세 줄이 모두 필요합니다.
  - `CLOVA_API_KEY`: 비서 화면 (`services/web`)과 맞춤 마케팅 (`experiments/marketing`, `ic26-marketing`)
  - `CLOVASTUDIO_API_KEY`: 리뷰 분석 (`services/review-insight`)
  - `CLOVA_STUDIO_API_KEY`: 상권 챗봇 (가운데 밑줄이 하나 더 있음. 월요일부터 쓰임)
- 키 값만 넣습니다. 앞에 `Bearer `를 붙이지 않고, 따옴표와 앞뒤 공백도 넣지 않습니다. 값 뒤에 주석을 붙이지 않습니다(systemd가 주석까지 값으로 읽습니다).
- DB 값(`DB_HOST`, `DB_USER`, `DB_PASSWORD`)은 DB가 만들어진 뒤에 넣습니다(6-1절). `DB_HOST`를 비워 두면 DB 없이 돕니다.
- 리뷰 분류 모델을 바꾸는 `LLM_MODEL_REVIEW`는 선택입니다. 틀에 주석으로 들어 있고, 그대로 두면 `HCX-005`입니다.
- 그대로 두는 것: `APP_MODE=live`, `ASSISTANT_ENABLED=1`, `ASSISTANT_MODEL_DAILY_LIMIT=2000`, `DB_PORT=5432`, `DB_NAME=ic26app`.

값이 들어갔는지 **이름만** 확인합니다(값은 출력되지 않음).

```bash
sudo grep -E '^(CLOVA_API_KEY|CLOVASTUDIO_API_KEY|CLOVA_STUDIO_API_KEY)=.' /etc/ic26/env | cut -d= -f1
ls -l /etc/ic26/env                      # -rw------- root root
```

키 없이 먼저 설치만 확인하고 싶으면 `APP_MODE=mock`으로 바꿔 5·6절을 해 보고, 끝나면 `live`로 되돌립니다. mock은 저장된 예시를 보여 주며 실제 AI 결과가 아닙니다.

키를 서버 디스크에 두지 않으려면 5-1절(Secret Manager)을 씁니다. 11/18부터 권장하는 방법입니다.

## 5-1. 키를 Secret Manager에 두기 (권장, 11/18)

키와 DB 비밀번호를 `/etc/ic26/env`(디스크)와 서버 이미지에 두지 않는 방법입니다. `/etc/ic26/env`에는 이름만 남기고(값은 빈 칸), 서버가 켜질 때마다 `ic26-secrets` 서비스가 Secret Manager에서 값을 받아 `/run/ic26/secrets.env`(메모리 영역, 재부팅하면 사라지고 다시 받음)에 둡니다. 서비스 4개는 env를 읽은 뒤 이 파일을 한 번 더 읽습니다(같은 이름이면 이 파일이 이김). 11/18 `ic26-was1`에서 서버 역할의 임시 키로 값을 읽는 것까지 확인했습니다.

**콘솔에서 한 번**

1. Security > Secret Manager에서 비밀을 만듭니다. 값은 **env 이름을 키로 한 JSON**입니다.

   ```json
   {"CLOVA_API_KEY": "…", "CLOVASTUDIO_API_KEY": "…", "CLOVA_STUDIO_API_KEY": "…", "DB_PASSWORD": "…",
    "SEOUL_OPENAPI_KEY": "…", "NAVER_MAPS_CLIENT_ID": "…", "NAVER_MAPS_CLIENT_SECRET": "…"}
   ```

2. Sub Account > Roles > [역할 생성]: 유형 **Server Role** → 정책 탭에서 `NCP_SECRETMANAGER_USER`(조회만) → 역할 적용 대상 탭에서 WAS 서버를 고르고 [적용]. 서버 한 대에 역할은 하나만 붙습니다.

**서버마다**

1. `sudo vi -n -i NONE /etc/ic26/env`에서 `IC26_SM_ID=<비밀 ID>`를 넣습니다(줄이 없으면 더함). 비밀 ID는 비밀번호가 아니지만 문서·이슈에는 적지 않습니다.
2. 받아 보고, 지금 env 값과 같은지 이름마다 확인합니다(값은 출력하지 않음).

   ```bash
   sudo python3 /opt/ic26/deploy/fetch_secrets.py --check     # 이름: 길이, env 와 같음/다름/비어 있음
   ```

3. 받아서 쓰고, **env에서 받아 온 이름의 줄만 값을 비웁니다.** env 파일의 다른 줄·주석·순서는 그대로입니다. 받기에 실패하면 env를 건드리지 않습니다.

   ```bash
   sudo python3 /opt/ic26/deploy/fetch_secrets.py --blank-env
   sudo systemctl restart ic26-secrets
   sudo systemctl restart ic26-review ic26-marketing ic26-was ic26-market
   bash ~/ic26-<커밋>/deploy/smoke_test.sh --expect-reviews 40 --market --generate
   ```

4. 재부팅해도 되는지 봅니다: `sudo reboot` → 다시 접속해 `journalctl -u ic26-secrets -b -o cat`(“Secret Manager 에서 N개를 받아 …”, 이름만)과 `smoke_test.sh`.

알아 둘 것

- Secret Manager의 값만 바꿨을 때: 서버마다 `sudo systemctl restart ic26-secrets && sudo systemctl restart ic26-review ic26-marketing ic26-was ic26-market`. 서비스만 다시 시작하면 예전 값(메모리의 파일)을 씁니다.
- 받아 오는 이름은 **env에 줄(`NAME=`)이 있는 이름만**입니다. env에 없는 이름은 건너뛰고 이름만 알려 줍니다. 그래서 env의 줄을 지우지 말고 값만 비웁니다.
- `ic26-secrets`가 실패하면(역할 없음, 비밀 ID 틀림, 네트워크) 서비스 4개는 env의 값(빈 칸)으로 켜져 `/api/health`에 막힘 항목이 보입니다. 원인은 `journalctl -u ic26-secrets -n 20`. 서버가 막 켜졌을 때 네트워크가 늦으면 6초 간격으로 20번까지 다시 시도합니다.
- 되돌리기: env에 값을 다시 넣고 `IC26_SM_ID`를 비운 뒤 `sudo systemctl restart ic26-secrets`(남은 `/run` 파일을 지움)와 서비스 재시작.
- 서버 이미지(7절): `prepare_image.sh`는 `IC26_SM_ID`를 비우지 않으므로, 그 이미지로 뜬 서버는 켜질 때 스스로 값을 받습니다. **그 서버에도 역할이 붙어 있어야 합니다**(Auto Scaling 서버에 역할이 붙는지는 11/19에 확인).
- 같은 서버 안의 모든 프로그램이 메타데이터로 임시 키를 받을 수 있습니다. 정책은 조회만(`NCP_SECRETMANAGER_USER`)으로 두고, 역할은 WAS에만 붙입니다(웹 서버에는 붙이지 않음).

## 6. 서버에서: 시작과 확인

```bash
sudo systemctl restart ic26-review ic26-marketing ic26-was ic26-market
systemctl is-active ic26-review ic26-marketing ic26-was ic26-market   # active 넷 (상권 자료를 깔기 전에는 market 만 inactive)
sudo ss -ltnp | grep -E ':(8000|8020|8030|8766)'        # 8000 은 0.0.0.0, 8020·8030·8766 은 127.0.0.1 만
bash ~/ic26-<커밋>/deploy/smoke_test.sh --expect-reviews 40
```

`smoke_test.sh`는 `/api/health`(모드, 키 유무, 리뷰 분석 상태 ok, 막힘 목록 비어 있음)와 `/api/briefing`(리뷰 건수), 맞춤 마케팅(10-2절: 비서 화면을 거친 `/api/marketing-survey/health`와 서버 안 `127.0.0.1:8030/health`), 상권(10절: 서버 안 `127.0.0.1:8766/health`와 비서 화면을 거친 `/api/assistant/status`가 `ready`)을 봅니다. 상권 서비스가 꺼져 있으면(자료를 아직 안 깜) 주의만 내고, `--market`을 주면 꺼져 있는 것도 실패로 셉니다. 모두 통과하면 종료 코드 0입니다.

글 생성까지 보려면(live는 HCX를 실제로 한 번 부르므로 비용이 듭니다):

```bash
bash ~/ic26-<커밋>/deploy/smoke_test.sh --generate
```

`--generate`는 맞춤 마케팅의 `/plan`(가게 이야기 글)도 한 번 부릅니다(live면 HCX 1~2번). 상권 서랍이 `ready`면 조건 맞추기와 질문 1개("요일별 매출 알려줘")도 보내 자료 답(`data_answer`)이 오는지 보고, 시험 대화를 지웁니다. 마케팅 서버를 직접 볼 수 있으면(WAS 서버, 또는 `--marketing`) 시험 방문자 id(`smoke…`)로 쓰고 끝나면 그 기록만 지웁니다. 웹 서버처럼 비서 화면 서버를 거칠 때는 프록시가 쿼리의 방문자 id 를 버리고 쿠키를 쓰므로, 쿠키 파일로 한 방문자를 유지하고 끝나면 그 방문자의 `DELETE /api/approvals`(마케팅 기록도 함께 지움)로 지웁니다.

체크리스트 단계 7의 "확인할 것"과 대응:

| 확인 | 방법 |
|---|---|
| 네 서비스 enabled · active | `systemctl is-enabled ic26-review ic26-marketing ic26-was ic26-market` / `is-active` |
| 상권 서랍 ready, 분기 표기 '2026년 2분기' | `smoke_test.sh --market --generate`, 화면 오른쪽 'AI에게 묻기' |
| 서버를 중지했다 시작해도 저절로 뜸 | 콘솔에서 서버 정지·시작 뒤 위 명령 |
| 모드 live, 키 있음, 막힘 목록 비어 있음, 응답에 키 값 없음 | `smoke_test.sh`, `curl -s localhost:8000/api/health` |
| 리뷰 분석이 저장 파일을 쓸 수 있음 | `sudo journalctl -u ic26-review -n 50` 에 쓰기 오류 없음 |
| `/etc/ic26/env` 는 root 소유 600, `ps`·`journalctl` 에 키 값 없음 | `ls -l /etc/ic26/env`, `ps -eo args`, `journalctl -u ic26-was` 를 눈으로 봄 |
| `ufw` 꺼짐 | `sudo ufw status` (inactive) |
| 글 생성이 끝까지 됨 (HCX 호출, NAT 경로) | PC에서 `ssh -L 8000:127.0.0.1:8000 ic26-was1` 을 열고 브라우저로 `http://localhost:8000` |
| 서버의 커밋 | `cat /opt/ic26/REVISION` (두 서버가 같아야 함) |

## 6-1. DB를 연결할 때: 표 만들기

묶음에는 DB를 쓰는 코드(`shared/storage`)가 들어 있습니다. `DB_HOST`가 비어 있으면 DB 없이 돌고(서버 메모리와 파일), 넣으면 붙여넣은 리뷰, 승인 기록, 카드 추천 이유를 PostgreSQL에 둡니다.
DB를 만들고 ACG에서 WAS → DB 5432를 연 뒤에 합니다. 서버가 여러 대여도 표 만들기는 **한 대에서 한 번**이면 됩니다(같은 DB를 보기 때문).

1. `/etc/ic26/env`에 `DB_HOST`(DB의 사설 도메인), `DB_USER`, `DB_PASSWORD`를 5절과 같은 방법으로 넣습니다. `DB_HOST`만 넣고 `DB_USER`를 비우면 두 서비스가 켜지지 않습니다.
2. 표를 만듭니다. 환경 파일은 systemd가 읽으므로 비밀번호가 명령줄과 셸 히스토리에 남지 않습니다.

   ```bash
   sudo systemd-run --quiet --wait --pipe -p User=ic26 -p WorkingDirectory=/opt/ic26 \
     -p EnvironmentFile=/etc/ic26/env -p EnvironmentFile=-/run/ic26/secrets.env \
     /opt/ic26/.venv/bin/python -m shared.storage.init_db
   ```

   두 번째 `EnvironmentFile`은 5-1절(Secret Manager)을 쓸 때 `DB_PASSWORD`를 거기서 읽기 위한 것입니다. 쓰지 않으면 건너뜁니다.

   `<DB 주소>:5432/ic26app 표 6개 확인: approvals, card_reasons, reports, review_labels, reviews, stores`가 나오면 된 것입니다. 여러 번 돌려도 안전합니다(이미 있는 표는 그대로 둡니다).
   11/18부터 `approvals`에 칸 4개(`draft_text`, `checks`, `used_fallback`, `style`. 이슈 #51 ERD)가 더해졌습니다. 이 명령은 이미 있는 표에도 `ALTER TABLE … ADD COLUMN IF NOT EXISTS`로 이 칸을 더합니다(있던 기록은 그대로, 새 칸은 비움·`{}`·`false`).
3. 서비스를 다시 시작하고 확인합니다.

   ```bash
   sudo systemctl restart ic26-review ic26-was
   bash ~/ic26-<커밋>/deploy/smoke_test.sh --expect-reviews 40
   ```

4. DB에 실제로 쌓이는지 봅니다. 화면에서 리뷰를 하나 붙여넣은 뒤 건수를 셉니다(비밀번호는 묻는 칸에 입력).

   ```bash
   psql -h <DB 사설 도메인> -U <DB 사용자> -d ic26app -c 'select count(*) from reviews'
   ```

- `표를 만들지 못했습니다: …`가 나오면 그 뒤의 내용을 봅니다. 접속 실패면 ACG와 `DB_HOST`를, 권한 오류면 `DB_USER`가 `ic26app`에 표를 만들 수 있는 계정인지 봅니다.
- DB에 닿지 못하는 동안에는 승인은 되고(경고가 붙고, 서버가 들고 있다가 DB가 돌아오면 저장), 브리핑, 카드, 리뷰 분석, 붙여넣기는 503입니다. DB가 돌아오면 서비스를 다시 켜지 않아도 이어집니다.
- DB 없이 되돌리려면 `DB_HOST`를 비우고 서비스를 다시 시작합니다.
- 표 정의는 `db/schema.sql`입니다. 칸을 **더하는** 변경은 `schema.sql` 끝의 `ALTER TABLE … ADD COLUMN IF NOT EXISTS`로 이 명령이 처리합니다. 칸 이름·형식을 바꾸거나 지우는 변경은 따로 옮깁니다.
- 선택 변수: `DB_SSLMODE`, `DB_CONNECT_TIMEOUT`(3초), `DB_QUERY_TIMEOUT`(5초), `DB_POOL_MAX`(5). 설명은 `shared/storage/config.py`에 있습니다.
- 2번 명령과 실제 Cloud DB 연결은 11/18 `ic26-was1`에서 확인했습니다(표 6개). 처음에 `no pg_hba.conf entry for host …`가 나왔는데, 네트워크가 아니라 콘솔 DB User 관리의 **접근 제어(Client CIDR)**에 WAS 대역이 없어서였습니다.
- DB Failover 직후 약 30초 동안 DB 도메인이 옛 서버(읽기 전용 standby)를 가리킵니다(11/18 시험). 그때 연결 풀이 standby에 붙으면 최대 30분 저장이 실패할 수 있어 env에 `PGTARGETSESSIONATTRS=read-write`를 둡니다(틀에 들어 있음).

## 7. 서버 이미지 만들기 전에 (`ic26-was-img1`)

이미지에는 `/etc/ic26/env`와 서버 안의 파일이 그대로 담깁니다. **키를 비우지 않고 이미지를 만들면 키가 이미지에 남습니다.**

```bash
sudo bash /opt/ic26/deploy/prepare_image.sh
history -c && history -w          # 이 셸의 히스토리. sudo -i 나 root 로 들어갔다면 그 셸에서도
```

`prepare_image.sh`가 하는 일: 서비스 멈춤 → `/etc/ic26/env`에서 이름에 `KEY`, `PASSWORD`, `TOKEN`, `SECRET`이 들어간 줄의 값을 비움(이름은 남김) → 붙여넣은 리뷰, 승인 기록, 사용량 기록, 모델 원문 응답(`experiments/marketing/results`), 상권 대화 기록, 맞춤 마케팅 기록(`/var/lib/ic26/marketing`)을 지움 → 히스토리에 키 흔적이 있는지 파일 이름만 알려 줌. 값은 출력하지 않습니다.

그 뒤:

1. 콘솔에서 `ic26-was1` → 서버 이미지 `ic26-was-img1`. 서버를 정지해야 하는지는 화면 안내를 따릅니다.
2. 이미지가 끝나면 `ic26-was1`을 다시 켭니다. 5-1절(Secret Manager)을 쓰면 값을 다시 넣지 않고 `sudo systemctl restart ic26-secrets && sudo systemctl restart ic26-review ic26-marketing ic26-was ic26-market`. 쓰지 않으면 5절처럼 값을 다시 넣고 같은 재시작.
3. `ic26-was2`는 `ic26-was-img1`로 만든 뒤 베스천을 거쳐 접속해 5절처럼 값을 넣고 재시작합니다. 서비스는 이미 enable 되어 있고, 이미지에 값이 없으므로 키를 넣기 전에는 막힘 항목이 보이는 것이 정상입니다.
4. 두 서버에서 `smoke_test.sh`가 통과하고 `cat /opt/ic26/REVISION`이 같은지 봅니다.

## 8. 코드를 바꿨을 때 (갱신)

같은 스크립트를 다시 돌립니다. 서버가 둘 이상이면 **한 대씩**, 먼저 올린 서버가 UP으로 돌아온 것을 보고 다음 서버를 합니다.

```bash
# PC
deploy/make_bundle.sh --out ~/ic26-bundles && cd ~/ic26-bundles && scp ic26-<새 커밋>.tgz* ic26-was1:~/
# 서버
sha256sum -c ic26-<새 커밋>.tgz.sha256 && tar -xzf ic26-<새 커밋>.tgz
sudo bash ic26-<새 커밋>/deploy/install_was.sh
bash ic26-<새 커밋>/deploy/smoke_test.sh
```

- 바뀌는 것: `/opt/ic26`의 코드, `REVISION`, 서비스 파일, requirements(바뀐 것만 설치). 서비스는 다시 시작됩니다(몇 초간 응답 없음).
- 바뀌지 않는 것: `/etc/ic26/env`, `/opt/ic26/.venv`, 쓰기 폴더 안의 내용(붙여넣은 리뷰, 로그, 승인 기록, 상권 DB). 단 `services/review-insight/data/replay/classify.json`처럼 저장소에 있는 파일은 저장소 내용으로 덮입니다.
- 코드만 바뀌었으면 `--skip-pip`으로 빠르게 할 수 있습니다. requirements가 바뀐 갱신(예: DB 코드가 처음 들어온 묶음은 `psycopg`가 더해짐)에는 붙이지 않습니다.
- **PR #49(리뷰 캡처·응대 점수·보고서)와 비서 화면 연결(`feat/connect-care-ui`)이 처음 들어가는 갱신은 `--skip-pip` 없이 돌립니다.** 리뷰 분석 서비스가 `pillow`와 `python-multipart`를 새로 씁니다. `python-multipart`가 없으면 리뷰 분석 서비스(`ic26-review`)가 **아예 켜지지 않고**, 비서 화면의 브리핑·카드·리뷰 분석도 모두 `503`이 됩니다. 갱신 뒤 `curl -s http://127.0.0.1:8020/api/health`와 `curl -s http://127.0.0.1:8000/api/care/status`(`"state":"ready"`)를 봅니다.
- **맞춤 마케팅(`ic26-marketing`)이 처음 들어가는 갱신**은 `install_was.sh`가 서비스 파일을 넣고 enable·시작하며 `/var/lib/ic26/marketing`을 만듭니다. 새 패키지는 없습니다. 갱신 뒤 `curl -s http://127.0.0.1:8030/health`를 봅니다(10-2절).
- `db/schema.sql`에 새 표나 새 칸이 생긴 갱신이고 DB를 쓰고 있으면 6-1절의 표 만들기를 한 번 더 돌립니다. **11/18 묶음(`approvals` 칸 4개)이 그렇습니다.** 돌리기 전에도 승인 기록은 저장됩니다(새 칸이 없으면 칸 없이 예전처럼 쓰고 `journalctl -u ic26-was`에 'init_db 를 다시 돌리세요' 경고). 표 만들기를 돌린 뒤부터 새 칸이 채워집니다.
- 상권 자료(`/opt/ic26/services/market-analysis/data/`)는 갱신 때 그대로입니다. 자료가 깔려 있으면 `install_was.sh`가 `ic26-market`도 새 코드로 다시 시작합니다. 자료 묶음이 새로 나오면 4-1절(`--replace`).
- 환경 파일 틀에 새 변수가 생기면 스크립트가 빠진 변수 이름을 알려 줍니다. 편집기로 줄을 추가합니다.
- 단계 15(Auto Scaling) 뒤에는 그룹 서버를 직접 고치지 않습니다(체크리스트 단계 13-A).

## 9. 웹 서버 (Nginx)

웹 서버에는 키도 DB 정보도 없습니다(`/etc/ic26`을 만들지 않음). 3절의 `~/.ssh/config`에 `ic26-web1`도 같은 방식으로 적고(`HostName <ic26-web1 사설 IP>`, `ProxyJump ic26-jump`), 같은 묶음을 올려 풀고 실행합니다.

```bash
# 1단계 (지금 코드): 모든 요청을 WAS 로. FastAPI 가 화면 파일까지 줍니다.
sudo bash ic26-<커밋>/deploy/install_web.sh --lb <내부 로드 밸런서 주소>

# 2단계 (프론트엔드가 웹 계층으로 올 때): 화면 파일은 웹 서버가 직접, /api/ 만 WAS 로
sudo bash ic26-<커밋>/deploy/install_web.sh --mode static --lb <내부 로드 밸런서 주소> [--static-src <화면 파일 폴더>]
```

- `--lb`는 콘솔에서 `ic26-was-alb1`의 접속 주소입니다(`http://` 없이. 포트가 80이 아니면 `주소:포트`). 설정 검사(`nginx -t`)가 실패하면 이전 설정으로 되돌립니다. 내부 로드 밸런서 이름이 이 서버에서 풀리지 않을 때도 실패합니다.
- Nginx는 시작·reload 때 이 주소를 한 번만 IP로 바꿉니다. 로드 밸런서를 다시 만들었다면 `sudo systemctl reload nginx`.
- **IPv6가 없는 서버**(네이버클라우드 Ubuntu 24.04, `/proc/sys/net/ipv6` 없음): nginx 패키지가 설치 중에 기본 사이트(`listen [::]:80`)로 켜지다 `socket() [::]:80 failed (97: …)`로 실패해 apt가 멈추던 문제(11/18 web1)를, 스크립트가 apt 동안만 `/usr/sbin/policy-rc.d`(exit 101)를 두고(원래 있던 파일은 건드리지 않음) 기본 사이트 링크를 치운 뒤 `dpkg --configure -a`를 해서 피합니다. 이미 apt에서 멈춘 서버도 같은 명령을 다시 돌리면 회복됩니다.
- 두 설정 모두 `/healthz`는 Nginx가 직접 `ok`(200)로 답하고, `/docs`, `/redoc`, `/openapi.json`은 404입니다.
- **대기 시간 120초**: Nginx의 `proxy_read_timeout 120s`(`proxy_send_timeout`도 120초)입니다. 글 생성이 14초를 넘을 때가 있습니다.
  **콘솔에서 사람이: 공개 ALB(`ic26-web-alb1`)와 내부 ALB(`ic26-was-alb1`)의 유휴 시간 제한(idle timeout)도 120초로 맞춥니다.** 둘 중 하나라도 짧으면 글 생성 중에 연결이 끊깁니다. 설정 화면의 위치와 이름은 확인하지 못했습니다. WAS의 keep-alive는 130초로 이미 로드 밸런서보다 길게 해 두었습니다(`ic26-was.service`).
- **업로드 상한**: 두 설정 모두 기본 상한(1MB)은 그대로 두고, 리뷰 캡처 업로드 경로(`location = /api/care/reviews/capture`) 하나만 `client_max_body_size 12m`입니다(화면 서버 프록시 12MB, 리뷰 분석 서비스 10MB와 맞춤). 휴대폰 캡처는 1MB를 넘는 일이 많아 이 줄이 없으면 Nginx에서 413이 납니다. 손님용 문의 페이지(`/s/`)와 `/api/care/public/`은 따로 열지 않았습니다. 화면 서버가 `CARE_PUBLIC=1`일 때만 답하고 기본은 404입니다(보안 검토 전까지 닫아 둠). 다만 1단계 설정은 `/` 아래를 모두 WAS로 넘기므로, `CARE_PUBLIC=1`을 켜면 그 순간 밖에 열립니다.
- 2단계의 화면 파일 배치: `services/web/web/static/`의 **내용**(`index.html`, `style.css`, `app.js`, 하위 폴더 없음)을 `/var/www/ic26/`에 그대로 둡니다. `index.html`이 `/static/style.css`, `/static/app.js`를 부르고, `location /static/ { alias /var/www/ic26/; }`가 그 주소를 이 폴더로 이어 줍니다. `app.js`는 데이터를 `/api/…`로만 부르므로 `/api/`만 WAS로 넘깁니다. 화면 파일을 바꾸면 같은 명령을 다시 돌립니다(`--static-src`로 새 폴더).
- **맞춤 마케팅**: 브라우저는 `/api/marketing-survey/*`를 비서 화면 서버(8000)로만 부르고, 비서 화면 서버가 `127.0.0.1:8030`으로 대신 부릅니다(프록시. `docs/api/contract.md`). 1단계는 `location /`, 2단계는 `location /api/`가 이 경로를 그대로 WAS로 넘기므로 **Nginx 설정을 바꿀 것이 없습니다.** 8030은 `127.0.0.1`에만 묶여 있어 밖(웹 서버·로드 밸런서)에서 닿지 않고, 마케팅 서버의 단독 화면(`/`, `/web/`)과 `/docs`도 밖에 열리지 않습니다. 요청 본문은 작은 JSON이라 기본 상한(1MB)으로 충분하고, 글을 만드는 `/plan`은 HCX를 여러 번 불러 다른 글 생성처럼 `proxy_read_timeout 120s` 안에 끝나야 합니다(10-2절의 측정 참고).
- 확인:

  ```bash
  curl -s http://localhost/healthz                                   # ok
  curl -s http://localhost/api/health                                # WAS 의 응답
  curl -s -o /dev/null -w '%{http_code}\n' http://localhost/docs     # 404
  bash ~/ic26-<커밋>/deploy/smoke_test.sh --base http://localhost    # 웹 서버를 거쳐서 한 번에
  ```
- `ic26-web-img1`을 만들 때 비울 비밀 값은 없습니다. 이미지로 만든 `ic26-web2`에서는 `--lb` 주소가 같으면 따로 할 일이 없습니다.

## 10. 상권 서비스와 서랍의 상권 채팅

- 상권 코드(`services/market-analysis`)는 11/14에 `main`에 들어와(PR #12, #18, #13) 묶음에 들어 있습니다. `install_was.sh`가 그 requirements(`pyproj`, `pyshp` 등)도 함께 설치합니다.
- 상권 공식 자료를 4-1절(`install_market_data.sh`)로 깔면 `ic26-market`이 켜지고, 비서 화면의 오른쪽 "AI에게 묻기" 서랍이 상권 채팅이 됩니다(비서 화면 서버가 `127.0.0.1:8766`을 대신 불러 줌, `docs/api/contract.md` 1.10절). 자료가 없으면 서비스 파일만 들어가고 켜지지 않습니다. 그래도 비서 화면은 그대로 돌고, 서랍 안에만 "상권 서비스에 연결하지 못했어요"가 보입니다. 확인:

  ```bash
  curl -s -H 'Host: 127.0.0.1:8766' http://127.0.0.1:8766/health
  curl -s http://127.0.0.1:8000/api/assistant/status          # "state":"ready"
  ```
- **자료 폴더는 통째로 있어야 합니다.** 원본 폴더(`data/raw/official`) 없이 분석 카탈로그(`data/official`)와 보조자료(`data/assistant_context`)만 두면 서랍이 `ready`로 뜨고 조건도 맞춰지지만, 질문의 답이 모두 '자료 없음'이 됩니다(11/18 확인). 그래서 자료 묶음 하나로만 깝니다.
- 서비스 파일의 경로(`services/market-analysis`)와 시작 명령(`python -m app.intake_api`)은 `main`의 코드와 맞습니다. 11/18 Ubuntu 24.04 컨테이너에서 이 명령과 같은 계정·폴더로 띄워 서랍 `ready`와 질문 답을 확인했습니다. 실제 네이버클라우드 서버의 systemd에서는 아직 켜 보지 않았습니다.
- 하루 평균 매출은 그 분기의 달력일(평일 월~금, 주말 토·일) 수로 나눕니다(PR #62에서 고침. 그 전에는 5일·2일로 나눠 약 13배 크게 나옴). 개별 가게의 영업일 평균이 아닙니다.
- **비서 화면 서버가 상권 서비스를 부를 때는 `Host: 127.0.0.1:8766`으로 부르고, 방문자의 쿠키를 넘겨야 합니다.** 상권 서비스는 바깥 주소 이름(로드 밸런서 도메인 등)으로 오는 요청을 막습니다(Host가 `127.0.0.1` 또는 `localhost`가 아니면 400, Origin도 `127.0.0.1:8766`만 허용). `APP_PUBLIC_ORIGIN`은 `/etc/ic26/env`에 적지 않습니다.
- 상권 대화 기록은 서버 안의 SQLite 파일(`/var/lib/ic26/market/onboarding.sqlite3`)에 남습니다. WAS가 2대이면 서버마다 따로입니다(로드 밸런서가 같은 방문자를 다른 서버로 보내면 기록이 보이지 않을 수 있음). 이미지를 만들기 전에 `prepare_image.sh`가 이 폴더를 비웁니다.
- 키는 `CLOVA_STUDIO_API_KEY`(가운데 밑줄이 하나 더 있는 이름), 챗봇을 켜는 값은 `ASSISTANT_ENABLED=1`, 하루 호출 한도는 `ASSISTANT_MODEL_DAILY_LIMIT=2000`입니다.
- **서랍 상태 안내** (서랍 안에서만 보이고 다른 화면은 영향이 없음): 꺼져 있으면 "상권 서비스에 연결하지 못했어요", `ASSISTANT_ENABLED`가 없으면 "챗봇이 꺼져 있어요", 공식 자료가 없으면 "공식 상권 자료가 아직 준비되지 않았어요". 서랍을 처음 열면 우리 가게(온기한식: 장승배기역 · 한식음식점 · 장승배기역 4번 상권 · 최신 분기) 분석 조건이 자동으로 맞춰집니다.
- **`ASSISTANT_PLANNER=off`로 둡니다**(환경 파일 틀에 들어 있음). 계획기가 켜져 있으면 HCX가 질문에 없는 기간("2022년 2분기")을 지어내 "자료가 없어요"로 답하는 일이 잦았습니다. 끄면 질문은 규칙으로 분류하고 답 문장만 HCX가 씁니다. 상권 파트가 계획기를 고치면 이 줄을 지웁니다.
- 서버를 두 대 쓰면 상권 대화 기록(SQLite)이 서버마다 따로라서, 로드 밸런서가 방문자를 다른 서버로 보내면 대화가 이어지지 않습니다(분석 조건은 서랍을 다시 열 때 자동으로 다시 맞춰짐). 같은 방문자를 같은 서버로 보내는 설정(고정 세션)이 있으면 켜는 쪽이 낫습니다.
- 상권 README대로 공식 자료(`data/`)는 git에 올리지 않습니다. 서버에는 4-1절의 자료 묶음으로 깔고, `install_was.sh`는 갱신 때 이 폴더를 지우지 않습니다.

## 10-1. 고객응대(캡처 입력·응대 점수·종합 리포트)

- 비서 화면 서버가 리뷰 분석 서비스(`127.0.0.1:8020`)의 고객응대 API를 `/api/care/*`로 대신 불러 줍니다(`services/web/web/care_proxy.py`, `docs/api/contract.md` 1.11절). 열어 둔 것은 캡처 읽기, 리뷰 상태 기록, 응대 점수, 일일·월간 보고서(인쇄용 포함)뿐입니다. 가게 정보·문의·받은함 등은 404입니다.
- 설정은 비워 두면 됩니다. 이 서버에서 끄려면 `CARE_URL=off`, 캡처를 기다리는 시간은 `CARE_TIMEOUT_SEC`(기본 100초, 로드 밸런서 120초보다 짧게). `env.example` 참고.
- 리뷰 분석 서비스가 꺼져 있어도 비서 화면의 다른 칸은 그대로이고, 캡처 칸과 종합 리포트의 응대 칸에만 "연결하지 못했어요"가 보입니다. 사장님이 리뷰 답글을 승인하면 서버가 리뷰 분석 서비스에 '답글 달았음'을 따로 기록합니다(2초 안에 안 되면 버리고 로그만 남김, 승인은 그대로 성공).
- 응대 기록(답글·상태)은 지금 DB를 써도 리뷰 분석 서비스의 파일(`services/review-insight/data/runtime/…`)에 남습니다. **WAS가 2대이면 서버마다 따로**라서 응대 점수가 서버마다 다르게 보일 수 있습니다. 시연은 WAS 1대로 합니다(리뷰 분석 모듈 `docs/handoff.md` 7·8절).

## 10-2. 맞춤 마케팅 (`ic26-marketing`, 11/16)

- 김수현 님의 설문 맞춤 마케팅 서버(`experiments/marketing/marketing_survey`, PR #56)를 4번째 서비스로 띄웁니다. 서버 안에서만 열립니다(`127.0.0.1:8030`). 비서 화면 서버가 `MARKETING_SURVEY_URL`(서비스 파일에 `http://127.0.0.1:8030`)로 `/api/marketing-survey/*`를 대신 불러 줍니다. API는 `docs/api/contract.md` 4부.
- **모드**: `MARKETING_APP_MODE`(mock|live) → 없으면 `APP_MODE` → 없으면 키 유무. 보통은 적지 않고 `APP_MODE`를 따릅니다. **mock이면 키가 있어도 HCX를 부르지 않습니다.** live인데 `CLOVA_API_KEY`가 비어 있으면 저장된 예시·코드 템플릿으로 돌고(`demo: true`), `/health`의 `notes`에 그렇게 나옵니다.
- **키**: `CLOVA_API_KEY`(비서 화면과 같은 이름)를 읽습니다. `/health`에는 키가 있는지(`key_present`)만 나오고 값은 나오지 않습니다.
- **기록**: 설문 결과·승인·쿠폰 결과·광고비 점검을 `/var/lib/ic26/marketing/records_<가게>_<방문자>.json`에 방문자마다 한 줄씩 덧붙입니다(방문자 id는 비서 화면의 쿠키, 로그인 아님). 마케팅 보고서는 그 방문자의 기록만 세고, 없으면 데모 기록을 보여 줍니다. **WAS가 2대이면 서버마다 따로**입니다. 기록 쓰기가 실패해도 화면 흐름은 그대로 갑니다(`/health`의 `records_dir_writable`). 이미지를 만들기 전에 `prepare_image.sh`가 비웁니다.
- **로그**: `sudo journalctl -u ic26-marketing -n 50` (uvicorn `--log-level warning`이라 평소에는 조용함). live에서 답글 생성기는 `experiments/marketing/results/c6_reply_raw.txt`에 모델 원문 응답을 남깁니다(비서 화면과 같은 폴더).
- **패키지**: 서버는 `fastapi`·`uvicorn`·`pydantic`만 씁니다(비서 화면 requirements에 들어 있음). `experiments/marketing/requirements.txt`는 개발용 데모 화면의 `streamlit`이 들어 있어 설치하지 않습니다.
- **상태 확인**: `curl -s http://127.0.0.1:8030/health` → `{"status":"ok","service":"marketing-survey","mode":…,"key_present":…,"demo":…,"records_dir_writable":true,…}`.
- **끄는 법**: `/etc/ic26/env`에 `MARKETING_SURVEY_URL=off`를 넣고(비서 화면 서버가 부르지 않음) `sudo systemctl disable --now ic26-marketing && sudo systemctl restart ic26-was`. 다시 켤 때는 그 줄을 지우고 `sudo systemctl enable --now ic26-marketing && sudo systemctl restart ic26-was`. `ic26-was`는 `ic26-marketing`을 순서(`After`)로만 기다리고 `Wants`로 끌어오지 않아, 꺼 둔 채로 화면 서버를 다시 시작해도 마케팅이 켜지지 않습니다.
- **로컬**: `services/web/run.sh`가 같이 띄웁니다(`MARKETING_PORT`, 기본 8030). `MARKETING_SURVEY_URL=off`면 띄우지 않습니다.

## 11. 문제가 생기면

| 증상 | 먼저 볼 것 |
|---|---|
| 서비스가 안 뜸 | `systemctl status ic26-was`, `sudo journalctl -u ic26-was -u ic26-review -n 80 --no-pager` |
| `/api/health`가 500 (리뷰 분석 쪽) | `APP_MODE=live`인데 `CLOVASTUDIO_API_KEY`가 비어 있음. 5절 |
| 화면 `/api/health`에 "HCX 키가 없어요" | `CLOVA_API_KEY`가 비어 있음. 문구는 개발 PC 기준이라 `~/.config/teletubby-aiic/env`로 나오지만 서버에서는 `/etc/ic26/env`입니다 |
| 화면은 뜨는데 글 생성만 실패 | NAT 경로, 키, HCX 호출 한도. 서버에서 `curl -sI https://clovastudio.stream.ntruss.com` 로 나가는 길을 확인 |
| 답글 생성이 "Permission denied … results" | `experiments/marketing/results`가 `ic26` 소유가 아님. `install_was.sh`를 다시 돌림 |
| 맞춤 마케팅 칸에 연결 오류, `smoke_test.sh`의 [4] 실패 | `systemctl status ic26-marketing`, `sudo journalctl -u ic26-marketing -n 50`, `curl -s http://127.0.0.1:8030/health` (10-2절) |
| 맞춤 마케팅 글이 늘 같은 예시 (`demo: true`) | `/health`의 `mode`·`key_present`. mock이거나 `CLOVA_API_KEY`가 비어 있음 |
| 캡처를 올리면 413 | Nginx 설정이 이 묶음의 것인지(캡처 경로만 `client_max_body_size 12m`). `install_web.sh`를 다시 돌림 |
| `ic26-review`가 안 뜸, `python-multipart` 오류 | 갱신을 `--skip-pip`로 돌렸음. `--skip-pip` 없이 `install_was.sh`를 다시 돌림 |
| 502/504 | 로드 밸런서 유휴 시간 120초, WAS 상태, `nginx -t`, 내부 로드 밸런서 주소가 바뀌었는지(`reload`) |
| `install_was.sh`가 `systemd 로 돌고 있지 않습니다` | 컨테이너에서 돌릴 때만. `--no-systemd` |
| `nginx -t` 실패, `host not found in upstream` | `--lb` 주소를 서버에서 풀 수 있는지 `getent hosts <주소>` |

## 12. 알아 둘 것

- **DB는 `DB_HOST`를 넣었을 때만 씁니다(6-1절).** 비어 있으면 서버 메모리와 파일로 돌고, 서버가 2대면 서버마다 따로 보입니다. 표는 임시 6개(`db/schema.sql`)이고 ERD가 정해지면 바뀝니다. 방문자는 쿠키(`visitor_id`)로 나누며 로그인이 아닙니다. `postgresql-client`(`psql`)는 DB 접속 시험용으로 설치합니다. `psql`은 비밀번호를 묻는 칸에 입력하고 접속 문자열에 넣지 않습니다.
- **live에서 키가 비면** 서비스는 시작되고(`Restart=always`로 계속 떠 있음) 첫 요청에서 오류가 납니다. `architecture.md`는 "시작하지 못한다"고 적었는데, 코드는 첫 요청 때 모델 설정을 만듭니다.
- **live 글 생성은 `experiments/marketing/results/c6_reply_raw.txt`에 모델의 원문 응답을 남깁니다**(C6 코드가 그 폴더에 씀). 그래서 코드 폴더는 root 소유지만 이 폴더만 `ic26`이 쓸 수 있게 했습니다. 이미지를 만들 때는 비웁니다(`prepare_image.sh`). 실제 사장님 리뷰가 들어오게 되면 보관 기간을 정합니다.
- 비서 화면의 승인 기록은 DB를 쓰면 `approvals` 표에, 쓰지 않으면 `/var/lib/ic26/runtime/approvals.jsonl`에 쌓입니다. DB 없이 서버가 2대이면 서버마다 따로입니다.
- 맞춤 마케팅의 기록은 DB를 써도 아직 파일(`/var/lib/ic26/marketing`)입니다(DB 표로 옮기는 일은 아직 없음). 서버가 2대이면 서버마다 따로입니다.
- 이 묶음은 Ubuntu 24.04(파이썬 3.12)에서 시험했습니다. 컨테이너에서 설치를 끝까지 돌려 mock 모드로 `/api/health` 200, `/api/briefing` 리뷰 40건, 글 생성 1회를 확인했습니다. 11/14에 DB 코드와 상권 코드가 들어온 묶음도 같은 컨테이너에서 설치하고, PostgreSQL 16 컨테이너에 표를 만들어 붙여넣은 리뷰가 DB에 쌓이는 것까지 확인했습니다. **실제 네이버클라우드 서버, 실제 HCX 호출, 실제 Cloud DB 연결, 로드 밸런서 연동은 시험하지 못했습니다.**
