# 서버 설치 묶음 (deploy/)

네이버클라우드 서버에 이 앱을 올리는 파일 묶음입니다. 구성은 `docs/infra/architecture.md`, 순서와 확인 항목은 `인프라/10 …체크리스트 (v0.8)`의 단계 7~10, 13을 따릅니다.
이 문서에는 키, 비밀번호, 공인 IP, 실제 도메인을 적지 않습니다. 꺾쇠(`<...>`)로 쓴 곳은 직접 채웁니다.

## 0. 한눈에

```
PC ──(scp, 베스천 거침)──▶ ic26-was1 ─ install_was.sh ─▶ ic26-review (127.0.0.1:8020)
                                                      └▶ ic26-was    (0.0.0.0:8000)  ← 내부 로드 밸런서가 부름
                                                         ic26-market (127.0.0.1:8766) ← 월요일. 지금은 꺼 둠
웹 서버 ─ install_web.sh ─▶ Nginx (80)  ── /api 또는 전체 ──▶ 내부 로드 밸런서 ─▶ WAS
```

| 파일 | 어디서 쓰나 | 하는 일 |
|---|---|---|
| `make_bundle.sh` | PC | `origin/main`(또는 준 커밋)을 `git archive`로 묶어 `ic26-<커밋>.tgz`와 체크섬을 만듦. 안에 `REVISION`(커밋 해시) 포함 |
| `install_was.sh` | WAS 서버 | 패키지, 계정, 코드, 쓰기 폴더, 환경 파일 틀, venv, 서비스 등록. 다시 돌려도 안전. **코드 갱신에도 같은 스크립트** |
| `env.example` | WAS 서버 | `/etc/ic26/env`의 틀. 변수 이름과 설명만 있고 키·비밀번호 값은 비어 있음 |
| `systemd/ic26-review.service` | WAS 서버 | 리뷰 분석 (127.0.0.1:8020) |
| `systemd/ic26-was.service` | WAS 서버 | 비서 화면 서버 (0.0.0.0:8000, 상태 확인 `/api/health`) |
| `systemd/ic26-market.service` | WAS 서버 | 상권 서비스 자리. 파일만 넣고 **켜지 않음** (월요일) |
| `smoke_test.sh` | WAS 서버, 웹 서버 | `/api/health`와 `/api/briefing` 확인. `--generate`로 글 생성 1회 |
| `prepare_image.sh` | WAS 서버 | 서버 이미지를 만들기 전에 키 값과 실행 중 데이터를 비움 |
| `install_web.sh` | 웹 서버 | Nginx 설치와 설정 넣기 (1단계 또는 2단계) |
| `nginx/ic26-proxy-all.conf` | 웹 서버 | (가) 1단계: 모든 요청을 WAS로 |
| `nginx/ic26-static.conf` | 웹 서버 | (나) 2단계: 화면 파일은 웹 서버가, `/api/`만 WAS로 |

순서 (11/14 계획의 2단계 기준):

- **1단계, 토요일 밤**: 2(묶기) → 3(올리기) → 4(설치) → 5(키 넣기) → 6(확인). `ic26-was1` 한 대만 세웁니다.
- **1단계, 일요일**: 9(웹 서버)와 로드 밸런서. WAS 타겟에는 `ic26-was1`만 넣습니다.
- **2단계, 월요일**: 완성본을 8(갱신)로 올린 뒤, 7(이미지, 다음 서버)을 **한 번만** 합니다. 주말에는 이미지를 만들지 않습니다(DB, 상권, 보고서가 들어오면 다시 만들어야 하기 때문).

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
4. 쓰기 폴더를 `ic26` 소유로 잡습니다: `services/review-insight/{logs,data/runtime,data/replay}`, `experiments/marketing/results`, `/var/lib/ic26/runtime`(= `WEB_RUNTIME_DIR`, 승인 기록), `/var/lib/ic26/market`(상권 SQLite).
5. `/etc/ic26/env`가 **없을 때만** `env.example`로 만듭니다(root 소유, 권한 600). 있으면 건드리지 않고, 빠진 변수 이름만 알려 줍니다.
6. `/opt/ic26/.venv`를 만들고 requirements를 설치합니다.
7. 서비스 파일을 `/etc/systemd/system/`에 넣고 `ic26-review`, `ic26-was`를 enable하고 시작합니다. `ic26-market`은 파일만 넣고 켜지 않습니다.

옵션: `--no-start`(등록만), `--skip-apt`, `--skip-pip`, `--no-systemd`(컨테이너 시험용).
이 시점에는 키가 비어 있어 `APP_MODE=live`라서 `/api/health`에 막힘 항목이 보이는 것이 정상입니다.

## 5. 서버에서: 키 넣기 (손으로)

**편집기로 직접 입력합니다. 키를 명령줄 인자(`echo`, `export`, `sed -i` 등)나 셸 히스토리에 남기지 않습니다.**
메신저, 메모장, 화면 캡처를 거치지 않습니다.

```bash
sudo vi -n -i NONE /etc/ic26/env        # -n -i NONE: 임시 파일(.swp)과 viminfo 에 값이 남지 않게 함
```

넣을 것:

- `CLOVA_API_KEY`, `CLOVASTUDIO_API_KEY`, `CLOVA_STUDIO_API_KEY` **세 줄에 같은 서버 전용 키**를 넣습니다. 코드마다 읽는 이름이 달라서 세 줄이 모두 필요합니다.
  - `CLOVA_API_KEY`: 비서 화면 (`services/web`)
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

키 보관을 "비밀 저장소 + 서버 역할"로 바꾸는 시험(체크리스트 D15)이 되면 이 5절만 바뀝니다. 설치 스크립트와 서비스 파일은 그대로입니다.

## 6. 서버에서: 시작과 확인

```bash
sudo systemctl restart ic26-review ic26-was
systemctl is-active ic26-review ic26-was ic26-market   # active active inactive (market 은 월요일까지 inactive)
sudo ss -ltnp | grep -E ':(8000|8020)'                  # 8000 은 0.0.0.0, 8020 은 127.0.0.1 만
bash ~/ic26-<커밋>/deploy/smoke_test.sh --expect-reviews 40
```

`smoke_test.sh`는 `/api/health`(모드, 키 유무, 리뷰 분석 상태 ok, 막힘 목록 비어 있음)와 `/api/briefing`(리뷰 건수)을 봅니다. 모두 통과하면 종료 코드 0입니다.

글 생성까지 보려면(live는 HCX를 실제로 한 번 부르므로 비용이 듭니다):

```bash
bash ~/ic26-<커밋>/deploy/smoke_test.sh --generate
```

체크리스트 단계 7의 "확인할 것"과 대응:

| 확인 | 방법 |
|---|---|
| 두 서비스 enabled · active | `systemctl is-enabled ic26-review ic26-was` / `is-active` |
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
     -p EnvironmentFile=/etc/ic26/env /opt/ic26/.venv/bin/python -m shared.storage.init_db
   ```

   `<DB 주소>:5432/ic26app 표 6개 확인: approvals, card_reasons, reports, review_labels, reviews, stores`가 나오면 된 것입니다. 여러 번 돌려도 안전합니다(이미 있는 표는 그대로 둡니다).
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
- 표 정의는 `db/schema.sql`이고 임시입니다. ERD가 정해져 이미 있는 표의 칸이 바뀌면 이 명령으로는 고쳐지지 않으니 따로 옮깁니다.
- 선택 변수: `DB_SSLMODE`, `DB_CONNECT_TIMEOUT`(3초), `DB_QUERY_TIMEOUT`(5초), `DB_POOL_MAX`(5). 설명은 `shared/storage/config.py`에 있습니다.
- **2번의 `systemd-run` 명령과 실제 Cloud DB 연결은 서버에서 아직 돌려 보지 못했습니다(11/14).** 표 만들기와 저장은 로컬 PostgreSQL 16으로 확인했습니다.

## 7. 서버 이미지 만들기 전에 (`ic26-was-img1`)

이미지에는 `/etc/ic26/env`와 서버 안의 파일이 그대로 담깁니다. **키를 비우지 않고 이미지를 만들면 키가 이미지에 남습니다.**

```bash
sudo bash /opt/ic26/deploy/prepare_image.sh
history -c && history -w          # 이 셸의 히스토리. sudo -i 나 root 로 들어갔다면 그 셸에서도
```

`prepare_image.sh`가 하는 일: 서비스 멈춤 → `/etc/ic26/env`에서 이름에 `KEY`, `PASSWORD`, `TOKEN`, `SECRET`이 들어간 줄의 값을 비움(이름은 남김) → 붙여넣은 리뷰, 승인 기록, 사용량 기록, 모델 원문 응답(`experiments/marketing/results`), 상권 대화 기록을 지움 → 히스토리에 키 흔적이 있는지 파일 이름만 알려 줌. 값은 출력하지 않습니다.

그 뒤:

1. 콘솔에서 `ic26-was1` → 서버 이미지 `ic26-was-img1`. 서버를 정지해야 하는지는 화면 안내를 따릅니다.
2. 이미지가 끝나면 `ic26-was1`에 5절처럼 값을 다시 넣고 `sudo systemctl restart ic26-review ic26-was`.
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
- `db/schema.sql`에 새 표가 생긴 갱신이고 DB를 쓰고 있으면 6-1절의 표 만들기를 한 번 더 돌립니다.
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
- 두 설정 모두 `/healthz`는 Nginx가 직접 `ok`(200)로 답하고, `/docs`, `/redoc`, `/openapi.json`은 404입니다.
- **대기 시간 120초**: Nginx의 `proxy_read_timeout 120s`(`proxy_send_timeout`도 120초)입니다. 글 생성이 14초를 넘을 때가 있습니다.
  **콘솔에서 사람이: 공개 ALB(`ic26-web-alb1`)와 내부 ALB(`ic26-was-alb1`)의 유휴 시간 제한(idle timeout)도 120초로 맞춥니다.** 둘 중 하나라도 짧으면 글 생성 중에 연결이 끊깁니다. 설정 화면의 위치와 이름은 확인하지 못했습니다. WAS의 keep-alive는 130초로 이미 로드 밸런서보다 길게 해 두었습니다(`ic26-was.service`).
- 2단계의 화면 파일 배치: `services/web/web/static/`의 **내용**(`index.html`, `style.css`, `app.js`, 하위 폴더 없음)을 `/var/www/ic26/`에 그대로 둡니다. `index.html`이 `/static/style.css`, `/static/app.js`를 부르고, `location /static/ { alias /var/www/ic26/; }`가 그 주소를 이 폴더로 이어 줍니다. `app.js`는 데이터를 `/api/…`로만 부르므로 `/api/`만 WAS로 넘깁니다. 화면 파일을 바꾸면 같은 명령을 다시 돌립니다(`--static-src`로 새 폴더).
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
- 서비스는 `ic26-market.service` 파일만 `/etc/systemd/system/`에 넣고 enable 하지 않습니다. 켜면 비서 화면의 오른쪽 "AI에게 묻기" 서랍이 상권 채팅이 됩니다(비서 화면 서버가 `127.0.0.1:8766`을 대신 불러 줌, `docs/api/contract.md` 1.10절). 켜지 않아도 비서 화면은 그대로 돌고, 서랍 안에만 "상권 서비스에 연결하지 못했어요"가 보입니다. 켤 때:

  ```bash
  sudo systemctl enable --now ic26-market
  curl -s -H 'Host: 127.0.0.1:8766' http://127.0.0.1:8766/health
  ```
- 서비스 파일의 경로(`services/market-analysis`)와 시작 명령(`python -m app.intake_api`)은 `main`에 들어온 코드와 맞습니다(`app/intake_api.py`, `requirements.txt`, `requirements-assistant.txt`). 서버에서 켜 본 적은 없습니다. 다르게 돌면 `WorkingDirectory`, `ExecStart`, `ConditionPathExists`를 고칩니다.
- **비서 화면 서버가 상권 서비스를 부를 때는 `Host: 127.0.0.1:8766`으로 부르고, 방문자의 쿠키를 넘겨야 합니다.** 상권 서비스는 바깥 주소 이름(로드 밸런서 도메인 등)으로 오는 요청을 막습니다(Host가 `127.0.0.1` 또는 `localhost`가 아니면 400, Origin도 `127.0.0.1:8766`만 허용). `APP_PUBLIC_ORIGIN`은 `/etc/ic26/env`에 적지 않습니다.
- 상권 대화 기록은 서버 안의 SQLite 파일(`/var/lib/ic26/market/onboarding.sqlite3`)에 남습니다. WAS가 2대이면 서버마다 따로입니다(로드 밸런서가 같은 방문자를 다른 서버로 보내면 기록이 보이지 않을 수 있음). 이미지를 만들기 전에 `prepare_image.sh`가 이 폴더를 비웁니다.
- 키는 `CLOVA_STUDIO_API_KEY`(가운데 밑줄이 하나 더 있는 이름), 챗봇을 켜는 값은 `ASSISTANT_ENABLED=1`, 하루 호출 한도는 `ASSISTANT_MODEL_DAILY_LIMIT=2000`입니다.
- **서랍 상태 안내** (서랍 안에서만 보이고 다른 화면은 영향이 없음): 꺼져 있으면 "상권 서비스에 연결하지 못했어요", `ASSISTANT_ENABLED`가 없으면 "챗봇이 꺼져 있어요", 공식 자료가 없으면 "공식 상권 자료가 아직 준비되지 않았어요". 서랍을 처음 열면 우리 가게(온기한식: 장승배기역 · 한식음식점 · 장승배기역 4번 상권 · 최신 분기) 분석 조건이 자동으로 맞춰집니다.
- **`ASSISTANT_PLANNER=off`로 둡니다**(환경 파일 틀에 들어 있음). 계획기가 켜져 있으면 HCX가 질문에 없는 기간("2022년 2분기")을 지어내 "자료가 없어요"로 답하는 일이 잦았습니다. 끄면 질문은 규칙으로 분류하고 답 문장만 HCX가 씁니다. 상권 파트가 계획기를 고치면 이 줄을 지웁니다.
- 서버를 두 대 쓰면 상권 대화 기록(SQLite)이 서버마다 따로라서, 로드 밸런서가 방문자를 다른 서버로 보내면 대화가 이어지지 않습니다(분석 조건은 서랍을 다시 열 때 자동으로 다시 맞춰짐). 같은 방문자를 같은 서버로 보내는 설정(고정 세션)이 있으면 켜는 쪽이 낫습니다.
- 상권 브랜치의 README는 공식 자료(`data/`)를 git에 올리지 않는다고 적고 있습니다. 서버에서 자료가 필요한지 월요일에 코드를 보고 확인합니다. `install_was.sh`는 `/opt/ic26/services/market-analysis/data/`를 갱신할 때 지우지 않습니다.

## 11. 문제가 생기면

| 증상 | 먼저 볼 것 |
|---|---|
| 서비스가 안 뜸 | `systemctl status ic26-was`, `sudo journalctl -u ic26-was -u ic26-review -n 80 --no-pager` |
| `/api/health`가 500 (리뷰 분석 쪽) | `APP_MODE=live`인데 `CLOVASTUDIO_API_KEY`가 비어 있음. 5절 |
| 화면 `/api/health`에 "HCX 키가 없어요" | `CLOVA_API_KEY`가 비어 있음. 문구는 개발 PC 기준이라 `~/.config/teletubby-aiic/env`로 나오지만 서버에서는 `/etc/ic26/env`입니다 |
| 화면은 뜨는데 글 생성만 실패 | NAT 경로, 키, HCX 호출 한도. 서버에서 `curl -sI https://clovastudio.stream.ntruss.com` 로 나가는 길을 확인 |
| 답글 생성이 "Permission denied … results" | `experiments/marketing/results`가 `ic26` 소유가 아님. `install_was.sh`를 다시 돌림 |
| 502/504 | 로드 밸런서 유휴 시간 120초, WAS 상태, `nginx -t`, 내부 로드 밸런서 주소가 바뀌었는지(`reload`) |
| `install_was.sh`가 `systemd 로 돌고 있지 않습니다` | 컨테이너에서 돌릴 때만. `--no-systemd` |
| `nginx -t` 실패, `host not found in upstream` | `--lb` 주소를 서버에서 풀 수 있는지 `getent hosts <주소>` |

## 12. 알아 둘 것

- **DB는 `DB_HOST`를 넣었을 때만 씁니다(6-1절).** 비어 있으면 서버 메모리와 파일로 돌고, 서버가 2대면 서버마다 따로 보입니다. 표는 임시 6개(`db/schema.sql`)이고 ERD가 정해지면 바뀝니다. 방문자는 쿠키(`visitor_id`)로 나누며 로그인이 아닙니다. `postgresql-client`(`psql`)는 DB 접속 시험용으로 설치합니다. `psql`은 비밀번호를 묻는 칸에 입력하고 접속 문자열에 넣지 않습니다.
- **live에서 키가 비면** 서비스는 시작되고(`Restart=always`로 계속 떠 있음) 첫 요청에서 오류가 납니다. `architecture.md`는 "시작하지 못한다"고 적었는데, 코드는 첫 요청 때 모델 설정을 만듭니다.
- **live 글 생성은 `experiments/marketing/results/c6_reply_raw.txt`에 모델의 원문 응답을 남깁니다**(C6 코드가 그 폴더에 씀). 그래서 코드 폴더는 root 소유지만 이 폴더만 `ic26`이 쓸 수 있게 했습니다. 이미지를 만들 때는 비웁니다(`prepare_image.sh`). 실제 사장님 리뷰가 들어오게 되면 보관 기간을 정합니다.
- 비서 화면의 승인 기록은 DB를 쓰면 `approvals` 표에, 쓰지 않으면 `/var/lib/ic26/runtime/approvals.jsonl`에 쌓입니다. DB 없이 서버가 2대이면 서버마다 따로입니다.
- 이 묶음은 Ubuntu 24.04(파이썬 3.12)에서 시험했습니다. 컨테이너에서 설치를 끝까지 돌려 mock 모드로 `/api/health` 200, `/api/briefing` 리뷰 40건, 글 생성 1회를 확인했습니다. 11/14에 DB 코드와 상권 코드가 들어온 묶음도 같은 컨테이너에서 설치하고, PostgreSQL 16 컨테이너에 표를 만들어 붙여넣은 리뷰가 DB에 쌓이는 것까지 확인했습니다. **실제 네이버클라우드 서버, 실제 HCX 호출, 실제 Cloud DB 연결, 로드 밸런서 연동은 시험하지 못했습니다.**
