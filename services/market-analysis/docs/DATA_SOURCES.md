# 상권분석 자료의 출처와 사용 방식

확인일: 2026-11-16. 프로젝트의 수집 코드, 저장된 원본과 출처 메타데이터, 로컬 배포 번들의 실제 파일 목록을 확인했다. 같은 날 클라우드 검증 환경에서 서울 OpenAPI를 실제 호출해 보조자료 4종의 2026년 2분기 자료를 추가 수집했다. 기본 8분기 원본과 파일 다운로드 기준정보는 기존 보존본이다.

**서울 8분기 상권 통계는 서울 열린데이터광장 API로 수집하여 JSON으로 저장한 자료다. `tar.gz`는 이미 저장된 자료를 묶어 전달하는 형식이다.** 따라서 “API로 가져온 자료”와 “압축파일로 전달받은 자료”는 같은 자료의 서로 다른 단계일 수 있다. 11월 4일 실행용 번들은 코드와 자료를 함께 담았고, 11월 16일 새 공유본은 데이터와 설명 파일만 담는다.

```text
서울 OpenAPI → 원본 JSON 보존 → 검증·카탈로그 생성 → 실행용 tar.gz에 포함
공식 ZIP/XLSX/CSV 다운로드 → 경계·검색 기준정보 가공 → 저장 파일로 사용
앱의 상권 통계 조회 → 준비된 원본 JSON·카탈로그 읽기
앱의 지도·주소 기능 → NAVER/Kakao 외부 서비스 사용
```

앱 조회가 통계 API 수집을 자동으로 시작하지는 않는다. `prepare_data --from-dir`은 이미 확보한 원본을 가져오고, `--collect --periods ...`는 명시한 기간을 수집한다. 자료 갱신 자동 스케줄은 없다. [준비·갱신 정책](DATA.md), [수집 코드](../scripts/prepare_data.py)

## 1. 현재 확보한 공식 상권 자료

아래의 “확인 번들”은 4절에서 실제 목록을 검사한 **2026-11-04 실행용 번들**만 뜻한다. 다른 이름의 공유 파일 전체에 대한 설명이 아니다. 실행 시 경로는 `services/market-analysis/` 기준이다.

| 자료 | 원천 취득 방식·제공처 | 기준 기간·확보 범위 | 실행 시 읽는 자료·용도 | 확인 번들 포함 |
|---|---|---|---|---|
| 추정매출 | **서울 OpenAPI** `VwsmTrdarSelngQq`; [OA-15572](https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do) | 2024Q3~2026Q2 연속 8분기. 62개 업종, 171,435행 | `data/raw/official/sales_*.json`. 총매출액과 요일·시간대·연령별 **매출액** 분포 분석 및 분기 비교 | 원본 JSON 포함 |
| 점포 | **서울 OpenAPI** `VwsmTrdarStorQq`; [OA-15577](https://data.seoul.go.kr/dataList/OA-15577/S/1/datasetView.do) | 같은 8분기. 공식 상권 1,650곳, 업종 합집합 100개, 609,699행 | `data/raw/official/stores_*.json`. 점포·개폐업·프랜차이즈 등 경쟁·변화 분석 | 원본 JSON 포함 |
| 길단위인구·유동인구 | **서울 OpenAPI** `VwsmTrdarFlpopQq`; [OA-15568](https://data.seoul.go.kr/dataList/OA-15568/S/1/datasetView.do) | 같은 8분기, 13,189행. 업종 구분 없음 | `data/raw/official/population_*.json`. 원천 총지표와 **시간대·연령별** 분포 분석 | 원본 JSON 포함 |
| 상권 영역 기본정보 | **서울 OpenAPI** `TbgisTrdarRelm`; [OA-15560](https://data.seoul.go.kr/dataList/OA-15560/S/1/datasetView.do) | 상권 기준정보. 분기별 매출·점포·인구 시계열과 구분 | `data/raw/official/areas_*.json` 및 카탈로그. 상권 코드·이름·유형·좌표·행정구역 연결 | 원본 JSON 포함 |
| 상권 경계 도형 | **공식 ZIP 다운로드**. 서울 OA-15560의 `seq=5` 첨부자료 | 공개일 2023-10-23. 최신 통계 분기와 경계의 일치 여부는 미검증 | `data/raw/official/OA-15560_seq5_boundaries.zip`을 가공한 카탈로그 도형. 지도 표시·위치 판단 | 원본 ZIP 및 가공 카탈로그 포함 |
| 지하철역 검색 기준정보 | **KRIC XLSX 다운로드**. 국가철도공단 레일포털 / 전국도시철도운영기관 [표준데이터 역사정보](https://data.kric.go.kr/rips/M_01_01/detail.do?id=32) | `전체_도시철도역사정보_20260630.xlsx`. 원본 1,099행 중 407행을 사용해 서울 403개 역 항목 생성 | `app/onboarding_stations.json`. 역명·노선·주소·좌표 검색 및 위치 선택 | 가공 JSON 포함. XLSX 원본은 이 번들에 없음 |
| 행정동 코드 검색 기준정보 | **서울 공식 ZIP/CSV 다운로드**. [전국 행정동 코드정보 제공 페이지](https://data.seoul.go.kr/dataVisual/seoul/seoulLivingPopulation.do) | ZIP 안의 `SEOUL_ADMI/ADMI_202608.csv`, 2026-08 기준. 전국 3,563행 중 서울 25개 구·427개 행정동 | `app/onboarding_neighborhoods.json`. 행정동 이름·코드 검색. 법정동 목록 및 생활인구 통계가 아님 | 가공 JSON 포함. ZIP/CSV 원본은 이 번들에 없음 |

8분기 범위와 행 수는 [2026-11-04 검증 기록](DATA.md)에 따른다. 모든 상권·업종·분기 조합에 행이 있다는 뜻은 아니다. 점포의 100개 업종과 추정매출의 62개 업종 범위도 서로 다르다.

**원본에 보유한 필드와 현재 계산·표시하는 필드는 다르다.** 위 표의 용도는 현재 구현된 분석 기준이다. 매출 분석의 `_GROUPS`는 요일·시간대·연령별 금액만, 인구 분석의 `_GROUPS`는 시간대·연령별 수치만 선택한다. 원본에는 다음 필드도 있지만 해당 항목의 계산·검증·결과 표시가 아직 연결되어 있지 않다. 자료가 쓸모없어서 제외됐다는 의미는 아니다. [매출 필드 선택](../app/onboarding_sales.py#L25), [인구 필드 선택](../app/onboarding_population.py#L19)

| 원본에 있으나 현재 위 분석에서 미사용인 항목 | 추가 활용 가능성 | 현재 상태 |
|---|---|---|
| 매출 건수 `THSMON_SELNG_CO` 및 요일·시간대·연령별 건수 | 같은 범위의 매출액과 결합해 건당 매출 계산, 금액 변화와 거래량 변화 구분. 건당 매출을 고유 고객당 객단가로 단정하지 않음 | 미구현. 건수의 의미·결측·분모 0·금액과의 집계 범위 검증 필요 |
| 성별 매출액 `ML_SELNG_AMT`, `FML_SELNG_AMT` | 성별 매출 구성에 따른 고객 타깃 검토 | 미구현. 총액과의 정합성·누락 검증 및 표시 필요 |
| 성별 인구 `ML_FLPOP_CO`, `FML_FLPOP_CO` 및 요일별 인구 `MON_FLPOP_CO`~`SUN_FLPOP_CO` | 타깃 검토와 영업일·인력 배치 계획의 보조 근거 | 미구현. 원천 집계 의미·총지표와의 관계 검증 필요 |

각 분포는 별도 집계이므로 성별·연령·시간대를 임의로 결합해 교차 고객 수를 만들 수는 없다.

근거:

- 기본 4종 서비스 ID 및 원천 URL: [seoul_client.py](../app/seoul_client.py#L18), [data_repository.py](../app/data_repository.py#L9)
- 저장 원본을 읽는 코드: [추정매출](../app/onboarding_sales.py), [점포](../app/onboarding_stores.py), [인구](../app/onboarding_population.py)
- 경계 ZIP 다운로드·해시 검증: [prepare_data.py](../scripts/prepare_data.py#L143); 공개일·경계 호환성 표기: [onboarding_analysis_catalog.py](../app/onboarding_analysis_catalog.py#L457)
- 지하철역의 제공처·원본 파일명·다운로드 URL·해시·가공 행 수: [onboarding_stations.json의 source](../app/onboarding_stations.json#L14076)
- 행정동의 제공처·기준월·ZIP 내부 파일명·해시·행 수: [onboarding_neighborhoods.json의 source](../app/onboarding_neighborhoods.json#L2567)

지하철역 XLSX 파일의 기준일은 2026-06-30이지만 행별 원천 날짜는 2022-05-25~2026-06-18이며, 채택한 행 중 13개는 날짜가 없다. 403개 항목을 현재 운행 중인 서울 전체 역의 실시간 목록으로 해석하지 않는다. 행정동도 2026-08 기준 목록이며 이후 행정구역 변경을 실시간 확인하지 않는다.

## 2. 이번에 실제 수집한 보조 자료 4종

초기 로컬 점검 때는 이 4종의 수집 JSON이 없었다. 이후 **2026-11-16 23:35~23:36 KST에 클라우드 검증 환경에서 실제 API 수집에 성공했고**, 파일별 SHA-256·서비스·분기·행 수를 대조한 뒤 로컬에도 가져왔다. 아래 자료는 모두 **2026년 2분기 한 분기**이며 기본 8분기와 범위를 구분한다. 11월 4일 과거 실행용 번들에는 없고, 11월 16일 새 데이터 공유본에는 포함한다.

| 자료 | 원천 취득 방식 | 실제 저장 위치 | 연결된 분석 내용 | 실제 수집 결과 |
|---|---|---|---|---|
| 직장인구 | **서울 OpenAPI** `VwsmTrdarWrcPopltnQq` | `data/assistant_context/workers_20262.json` | 직장인구 수, 업무형 입지 판단의 보조 근거 | 2026Q2, 1,641행, 23:35:55 KST |
| 상주인구·가구 | **서울 OpenAPI** `VwsmTrdarRepopQq` | `data/assistant_context/residents_20262.json` | 상주인구·가구 수, 주거형 입지 판단의 보조 근거 | 2026Q2, 1,633행, 23:35:59 KST |
| 집객시설 | **서울 OpenAPI** `VwsmTrdarFcltyQq` | `data/assistant_context/facilities_20262.json` | 집객시설·지하철역·버스정류장·대학·학교·병원 수 | 2026Q2, 1,578행, 23:36:03 KST |
| 상권변화지표 | **서울 OpenAPI** `VwsmTrdarIxQq` | `data/assistant_context/change_20262.json` | 상권변화 유형, 영업·폐업 점포의 평균 영업기간, 서울 평균 비교 | 2026Q2, 1,650행, 23:36:03 KST |

별도 명령 `python -m scripts.collect_assistant_context`로 수집한다. 기본 원본 전체를 그대로 보존하는 방식과 달리, 이 수집기는 필요한 필드를 골라 저장한다. 요청 분기 이하에서 제공되는 가장 최근 분기를 선택하므로 실제 자료가 매출 분기보다 과거일 수 있다. 파일의 `period`, `fetched_at`, `service`, `row_count`를 확인해야 하며 4종 모두 8분기라고 가정할 수 없다. 실행 중에는 저장 파일만 읽는다. [수집기와 기간 선택 정책](../scripts/collect_assistant_context.py#L1), [서비스·필드 정의 및 로더](../app/assistant/context.py#L22)

## 3. 실시간 서비스·가공 자료·사용자 입력

| 구분 | 자료·출처 | 확보·사용 방식 | 8분기 원본 및 확인 번들과의 관계 |
|---|---|---|---|
| 실시간 외부 서비스 | NAVER Maps | 브라우저 SDK로 지도 표시 | 지도 데이터는 공식 상권 통계 압축자료가 아님 |
| 실시간 외부 서비스 | NAVER Geocoding API | 주소 검색 시 서버에서 주소를 좌표로 변환 | 기능 사용 시 외부 호출. 저장된 상권 통계와 별개 |
| 실시간 외부 서비스 | Kakao 우편번호 검색 UI | 사용자가 주소 검색 결과를 선택 | 주소 선택용 외부 UI. 상권 통계 원천이 아님 |
| 공식 원본 가공 | 분석 카탈로그 | 상권 기준정보·경계·자료 범위를 검증해 `data/official/onboarding_analysis_catalog.json` 생성 | 확인 번들에 포함. 별도 외부 데이터셋 아님 |
| 공식 원본 가공 | 업종·지역 검색 목록 | 기존 매출·점포·상권 원본에서 `app/onboarding_industries.json` 등 생성 | 확인 번들에 가공 JSON 포함 |
| 공식 원본 계산 | 증감률·점유율·순위·점포당 평균·입지 유형 등 | 준비된 원본의 값과 비교 기준을 코드로 계산 | 별도 API에서 가져온 통계가 아닌 파생 결과 |
| 공식 원본 계산 | C4 고정 요약 스냅샷 | 기존 추정매출에서 `data/scenario/snapshot_2026Q2.json` 생성. 웹의 요약 화면에서 사용 | 11월 4일 확인 번들에는 없음. 11월 9일 작성한 별도 파생 결과 |
| 사용자 입력 | 위치·업종·창업/운영 상태·질문 | 사용자가 입력·선택한 조건으로 분석 범위를 결정 | 공식 통계 자료 아님. 실제 사용자 입력은 확인 번들의 원본 자료에 포함되지 않음 |
| 사용자 입력·계산 | 월세·권리금·보증금·인건비 | 사용자 제공 금액으로 부담 비율·가정별 손익 등을 계산 | 공공자료에서 취득한 임대료 시세가 아님 |
| 프로젝트 작성 자료 | 업종·지역 별칭 및 용어 사전 | `app/assistant/aliases/`의 JSON으로 질문·명칭 해석 | 통계가 아닌 검색·대화 보조 설정 |
| 사용자 대화 | 대화 기록·분석 상태 | 후속 질문에 필요한 문맥을 저장·참조 | 별도 외부 상권 통계 원천이 아님 |

지도·주소 근거: [서비스 구분](DATA.md), [NAVER Geocoding](../app/naver_clients.py#L210), [지도 SDK](../app/static/onboarding/onboarding.js#L144), [Kakao 주소 UI](../app/static/onboarding/onboarding.js#L466).

사용자 입력·용어 해석 근거: [onboarding.py](../app/onboarding.py), [site_costs.py](../app/assistant/site_costs.py), [lexicon.py](../app/assistant/lexicon.py).

C4 근거: [계산 설명](../../../docs/c4-evening-sales-comparison.md), [스냅샷](../../../data/scenario/snapshot_2026Q2.json). 장승배기역4번의 2026Q2와 2025Q2를 비교한 **공통 12개 업종의 17~24시 추정매출**이다. 비교 후보 5곳 중 선택한 사례로 서울 전체 상권 순위와 구분한다. 새 API 수집 없이 보존 원본에서 계산했다.

HCX 모델 호출은 위 근거를 이용해 질문을 해석하거나 설명을 작성하는 기능이며, 별도의 외부 상권 통계 데이터셋을 가져오는 경로로 분류하지 않는다.

## 4. 실제 검사한 프로젝트 번들

로컬 개발 작업공간에 남아 있는 다음 두 파일을 읽어 확인했다. 두 파일은 저장소 안의 추적 파일이 아니며, 프로젝트와 나란히 있는 `development/data/deploy/onboarding/`에 있다.

- `onboarding-runtime-8a4f1db87d624d8561d9d3c7.tar.gz`
- `onboarding-runtime-8a4f1db87d624d8561d9d3c7.manifest.json`

파일 기록일은 2026-11-04이고, manifest의 `schema_version`은 `onboarding-package-v1`, `kind`는 `runtime`, 카탈로그 버전은 `b1_9485a4a6a185c19bb0cf3982`다. manifest뿐 아니라 tar의 실제 파일 목록도 확인했다.

| 실제 파일 구성 | 개수·상태 |
|---|---:|
| `data/raw/official/sales_*.json` | 176개 |
| `data/raw/official/stores_*.json` | 643개 |
| `data/raw/official/population_*.json` | 16개 |
| `data/raw/official/areas_*.json` | 2개 |
| `data/raw/official/OA-15560_seq5_boundaries.zip` | 1개 |
| 공식 원본 파일 합계 | **838개** |
| `data/official/onboarding_analysis_catalog.json` | 포함 |
| 역·행정동·업종 가공 JSON | 포함 |
| `data/assistant_context/`의 보조 4종 JSON | **0개** |
| 앱 코드·실행 의존성 정의 등 | 포함 |
| 전체 일반 파일 | **868개**. manifest를 제외한 manifest 기록 수는 867개 |

파일 개수는 압축파일의 보존 파일 수다. 1절의 통계 원천 행 수와는 다른 단위이므로 페이지 수만 곱해 통계 행 수를 계산하지 않는다. 기존 원본 838개를 검증하여 같은 카탈로그를 재현한 기록은 저장소의 [VALIDATION.md](VALIDATION.md#L22)에서도 확인할 수 있다.

이 번들은 **코드와 자료가 함께 있는 과거 실행용 배포 묶음**이다. 특정 공유 제목의 압축파일과 동일하다고 단정하지 않는다. 다만 검사한 프로젝트 번들 기준으로 기본 API 원본·경계 ZIP·가공 기준정보의 포함 여부를 확인할 수 있다. 초기 점검에서 `development/data/deploy/` 아래 과거 배포용 `tar.gz` 10개를 검사했을 때도 보조 4종 수집 JSON은 없었다. 이번 실제 수집과 데이터 전용 공유본은 이 과거 기록과 별개다.

## 5. 이 목록을 해석할 때의 기준

- **취득 방식**은 원천 제공기관에서 자료를 어떻게 얻었는지다. API 응답을 JSON 파일로 저장했어도 원천 취득 방식은 API다.
- **전달 방식**은 이미 확보한 자료를 어떻게 옮겼는지다. `tar.gz`로 전달했다고 원천이 파일 다운로드로 바뀌지는 않는다.
- **실행 방식**은 앱이 분석할 때 무엇을 읽는지다. 현재 공식 상권 통계 분석은 저장 파일을 읽으며 지도·주소 서비스와 호출 경로가 다르다.
- **구현됨과 수집됨**을 구분한다. 보조 4종은 초기 점검 이후 2026Q2 실자료를 수집했다. 다른 분기까지 수집됐다는 의미는 아니다.
- **원본과 계산 결과**를 구분한다. 카탈로그·비교 지표·C4 스냅샷은 기존 원본에서 만든 결과이고, 사용자 입력 금액은 공식 시세 자료가 아니다.

## 6. 11월 16일 데이터 전용 공유본

공유본은 저장소의 [seoul-market-data-20261116.tar.gz](../../../data/bundles/seoul-market-data-20261116.tar.gz)에서 받을 수 있다. [공유본 안내](../../../data/bundles/README.md)에 크기와 SHA-256을 기록했다. 기본 공식 원본 838개, 분석 카탈로그 1개, 새 보조자료 4개, 역·행정동·업종 가공 JSON 3개, 원본 KRIC XLSX·행정동 ZIP/CSV 3개, C4 요약 스냅샷 1개로 **데이터 파일 850개**를 담는다. `README.txt`와 `MANIFEST.json`을 포함하면 일반 파일 852개다. 앱 코드·로그·API 키·사용자 DB는 포함하지 않는다.

런타임 자료는 저장소 상대 경로를 보존한다. KRIC와 행정동의 다운로드 원본은 `source-downloads/`에 두며 앱에서는 가공 JSON을 읽는다. 빈 디렉터리에 먼저 압축을 풀어 manifest의 파일별 바이트 수와 SHA-256을 확인한 뒤 배치한다. 기존 목적지 파일의 내용이 다르면 바로 덮어쓰지 않고 별도 검토한다. manifest는 자기 자신을 제외한 모든 압축 멤버를 기록한다.

## 7. API 키와 실행 설정 이름

키 값은 문서와 공유본에 넣지 않는다. API 취득과 저장 파일 분석을 구분해 다음 이름으로 설정한다.

| 서비스 | 환경변수 이름 | 필요한 때 |
|---|---|---|
| 서울 OpenAPI | `SEOUL_OPENAPI_KEY` | 공식 자료를 새로 수집할 때. 저장 JSON 분석에는 불필요 |
| CLOVA Studio | `CLOVA_STUDIO_API_KEY` | HCX-005·HCX-007 실제 모델 호출 |
| 모델 선택 | `CLOVA_MODEL_ANSWER` | `HCX-005` 또는 `HCX-007`; `APP_MODE=live`일 때 호출 |
| NAVER Maps | `NAVER_MAPS_CLIENT_ID` | 브라우저 지도 표시. 제공기관의 허용 서비스 URL 등록 필요 |
| NAVER Geocoding | `NAVER_MAPS_CLIENT_ID`, `NAVER_MAPS_CLIENT_SECRET` | 서버 주소→좌표 변환 |
| Kakao 우편번호 UI | 현재 구현은 별도 키 없음 | 주소 선택 UI. Kakao Local API와 구분 |
