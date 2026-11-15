# C6 — 답글/공지/홍보 초안 생성기

C6 는 추천 카드(RecommendationCard) 1장을 받아 사장님이 보낼 답글·공지·홍보 초안을 만드는 생성기다.
LLM(CLOVA) 호출 → 자동 점검(c6.checks) → 점검 실패 시 다시 쓰기(최대 2회) → 그래도 실패하면 코드
템플릿으로 교체, 순서로 돈다. 사장님이 직접 고르거나 손대야 할 부분은 늘 `needs_input`/`failed_reasons`
로 남긴다.

## 입력

C6 는 C1 이 정의한 계약 dataclass(`shared.contracts`: StoreProfile, ReviewRecord, ToneProfile,
RecommendationCard, AnalysisSnapshot)만 안다. C7 이 자기 쪽 데이터를 이 dataclass 형태로 바꿔
`c6.contract.build_context(...)` 에 넘긴다. `/insight` 응답(원시 리뷰·분석 결과) → ReviewRecord 변환도
C7 책임이다 — C6 는 변환 로직을 갖지 않는다. 팀 데이터가 없는 항목은 `build_context` 가 샘플
(`shared.sample_scenario`)로 채우고 `needs_input` 에 "팀 데이터에 없음: ..." 으로 적어 둔다.

실행은 `c6.registry.run_card(ctx, card, key, model="HCX-005", chosen_measures=None, reply_style="auto")`
하나로 한다. `card.kind` 에 따라 필요한 생성기(reply_draft/prevention_notice/coupon_promo)를 묶어
돌리고 `CardResult` 하나로 합친다.

## 출력

- `CardResult`: `card_id`, `kind`, `reason_text`, `basis_label`, `drafts`(DraftOutput 목록),
  `chosen_measures`, `elapsed_ms`, `won`(요금, 원).
- `DraftOutput`: `draft_id`, `generator`(reply_draft/prevention_notice/coupon_promo), `target_review_id`,
  `text`(최종 글), `evidence_ids`(근거 ID: F_리뷰id·정책ID·MEASURES ID·coupon:메뉴), `checks`(점검
  이름→통과 여부), `failed_reasons`(사람이 읽는 실패 사유, 남아 있으면 "확인 필요"), `rewrites`(다시
  쓴 횟수), `needs_input`, `style`(reply_draft 전용: haeyo/hamnida/mixed).

## 쓰는 법

```python
from c6.contract import build_context
from c6.registry import run_card

ctx = build_context(store=..., reviews=..., tone=..., cards=..., snapshots=...)
result = run_card(ctx, card, key=CLOVA_API_KEY, chosen_measures=[MEASURES[0]])
```

`key` 가 `None`(CLOVA_API_KEY 없음)이면 실제 호출 없이 저장본(`c6/replay/c6_cache_best.json`)에서
같은 `card_id` 결과를 그대로 돌려준다 — 발표·데모용 고정 저장본이다.

## 말투 근거

B 사장님은 ChatGPT로 답글을 작성해 왔으며, 다른 서비스의 AI 답글은 기존에 사용하던 스타일과 달라
사용하지 않았습니다. 그래서 C6는 사장님의 기존 답글 말투(ToneProfile)를 따라 씁니다.

답글 말투는 `run_card`/`generate_reply_draft` 의 `reply_style` 인자로 정한다(기본 `"auto"`):

- `"auto"`: `ToneProfile.example_sentences`·`style_description` 의 문장 끝(요/니다) 비율을
  `c6.style.detect_register` 로 보고, haeyo 또는 hamnida 하나로 통일한다. 판단 불가하면 haeyo.
- `"rotate"`: 카드의 리뷰 순서대로 haeyo/hamnida/mixed 3종을 돌아가며 쓴다 — 데모·테스트용
  (`c6.measures.REPLY_STYLES`).
- `"haeyo"`/`"hamnida"`/`"mixed"`: 그 말투로 답글 전부를 쓴다.

고른 말투는 `DraftOutput.style` 에 그대로 남는다.

## 확인 필요 전달

AI 가 쓴 공감·사과 문장이 점검(c6.checks)을 못 넘으면 최대 2번 다시 쓴다. 다시 쓰기 힌트에는 목표 말투와
사과 예시('정말 죄송해요' / '정말 죄송합니다')를 같이 적는다. 그래도 남은 실패가 사과 말투(`style_match`)나
사과 빠짐(`apology_expressed`)뿐이면, 코드가 끝 사과 어미만 말투에 맞게 바꾸거나 짧은 사과 한 문장을 덧붙여
AI 공감 문장을 살린다(`checks.ai_part_repaired = True`, 추가 호출 없음). 그 밖의 실패가 남으면 코드
템플릿 문장으로 바꿔 넣는다(`checks.used_fallback = True`). 이 대체는 늘 점검을 통과하므로 그
자체로는 통과로 보고 사람에게 다시 보여줄 필요가 없다. 대체로도 해결이 안 되는, 코드가 판단할 수
없는 나머지 실패(예: 근거 불일치, 금지 표현)만 `failed_reasons`/`needs_input` 에 남아 C7 로 넘어가고,
C7 쪽 화면에서 "확인 필요"로 표시된다.

재발 방지 공지(`prevention_notice`)도 같은 방식이다.
- 사과 점검(`has_apology`, 처음 두 문장)은 '죄송'뿐 아니라 '사과드립니다'·'사과의 말씀'·'송구'·'불찰'·'면목'도 사과로 본다.
- 딱딱한 표현 점검에서 '여러분'·'과정에서'는 공지에 자연스러워 빼고 본다(`checks.NOTICE_ALLOWED_STIFF`).
- 사전으로 고칠 수 있는 딱딱한 표현만 걸렸으면 다시 쓰기를 부르지 않고 바로 바꾼다(합니다체, `fix_stiff_words(formal=True)`).
  '기재'는 꼴별로만 바꾼다('기재해 주시면' → '적어 주시면'). 다시 쓰면 '오늘부터' 줄과 조치를 잃는 일이 잦았기 때문이다.
- 다시 쓰기 힌트에 실제로 걸린 딱딱한 표현과 바꿀 말, 리뷰에서 그대로 가져온 구절을 적고, 지적한 곳만 고치라고 한다.
- 그래도 남은 실패가 사과 빠짐·해요체 어미·'오늘부터' 빠짐뿐이면 사과 줄('불편을 드려 죄송합니다.')을 2번째 줄로
  넣거나, 어미를 합니다체로, '앞으로는'을 '오늘부터'로 바꿔 AI 본문을 살린다. 고친 본문이 점검을 전부 넘을 때만 쓴다.
- `checks.ai_part_repaired`는 최종 글이 HCX가 마지막으로 쓴 글과 다를 때(사전 치환·조치 줄·사과 줄·어미) True다.
  답글도 같은 기준이다. `measure_live.py`는 이 값으로 'AI 글 그대로'와 'AI 글 + 코드 보정'을 나눈다.

## 조치 문장

- 답글(`reply_draft`): M1 조치 문장("앞으로는 포장 마감 전에 주문서와 한 번 더 맞춰 보고...")과
  P1 요청사항 문장은 `chosen_measures` 값과 상관없이 코드가 늘 고정으로 붙인다(구조는
  `c6.reply` 모듈 docstring 참고).
- 공지(`prevention_notice`): "오늘부터" 로 시작하는 개선 조치 문장은 항상 쓰지만, 사장님이
  `chosen_measures` 로 조치를 직접 골랐을 때만 그 조치를 구체적으로 담는다. `chosen_measures`
  를 안 주면(`None`/`[]`) AI 는 구체적인 조치(체크리스트·절차 등)를 지어내지 않고 일반적인
  다짐만 쓴다 — 사장님이 고르지 않은 조치를 코드가 멋대로 단정하지 않기 위해서다.
