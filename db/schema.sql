-- 표 정의 (임시). 실행 중에 생기는 데이터만 담는다. 합성 리뷰 100건과 그 분류 결과(data/replay/classify.json)는 git 파일이라 넣지 않는다.
-- DB 설계(ERD)가 오면 이 파일과 shared/storage/pg.py 의 SQL 만 고치면 된다. 표 이름·칸 이름이 SQL 로 나오는 곳은 이 두 곳뿐이다.
-- 실행: python -m shared.storage.init_db   (여러 번 돌려도 안전: 이미 있으면 건너뜀. 있는 표에 칸을 더할 때는 파일 안의 ALTER ... ADD COLUMN IF NOT EXISTS)
-- 시각은 TIMESTAMPTZ. 코드는 한국 시간(+09:00) ISO 문자열로 읽고 쓴다.
-- visitor_id: 브라우저 쿠키의 임의 값. 'common' 은 방문자를 안 가린 호출(공용).

-- 가게. 가게 정보는 지금 git 파일(services/review-insight/data/synthetic/*/store.json)이라 코드가 아직 쓰지 않는다.
-- 그래서 다른 표가 이 표를 참조(FK)하지 않는다.
CREATE TABLE IF NOT EXISTS stores (
    store_id            TEXT        PRIMARY KEY,
    name                TEXT        NOT NULL,
    business_type_name  TEXT,
    data_origin         TEXT        NOT NULL DEFAULT 'synthetic',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 붙여넣은 리뷰. review_id(rv_<가게>_paste_NNN)는 (가게, 방문자) 안에서만 유일하다.
CREATE TABLE IF NOT EXISTS reviews (
    id            BIGSERIAL   PRIMARY KEY,
    store_id      TEXT        NOT NULL,
    visitor_id    TEXT        NOT NULL,
    seq           INTEGER     NOT NULL,                 -- (가게, 방문자) 안의 붙여넣은 순서. review_id 끝의 번호와 같다
    review_id     TEXT        NOT NULL,
    channel       TEXT,                                 -- baemin | coupangeats | yogiyo | naver_place | NULL
    rating        SMALLINT    CHECK (rating BETWEEN 1 AND 5),
    text          TEXT        NOT NULL,                 -- 전화번호·이메일·링크를 가린 뒤의 글
    created_at    TIMESTAMPTZ NOT NULL,                 -- 리뷰 작성 시각 (시나리오 시각일 수 있음)
    input_method  TEXT        NOT NULL DEFAULT 'paste', -- paste (합성 리뷰는 DB 에 없음)
    pii_masked    BOOLEAN     NOT NULL DEFAULT FALSE,
    data_origin   TEXT        NOT NULL DEFAULT 'synthetic',
    saved_at      TIMESTAMPTZ NOT NULL DEFAULT now(),   -- 행을 넣은 시각 (오래된 방문자 기록을 지울 때 씀)
    UNIQUE (store_id, visitor_id, seq),
    UNIQUE (store_id, visitor_id, review_id)
);

-- 붙여넣은 리뷰의 분류 결과. 리뷰가 아니라 (프롬프트 버전·모델·채널·별점·글)의 해시로 찾는다 (classify.cache_key).
-- 같은 글은 방문자와 상관없이 같은 결과라 방문자 칸이 없다.
CREATE TABLE IF NOT EXISTS review_labels (
    label_key       TEXT        PRIMARY KEY,
    result          JSONB       NOT NULL,               -- {sentiment, topics[{topic, polarity, evidence}], summary}
    prompt_version  TEXT        NOT NULL,
    model           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 승인 기록. 같은 초안을 다시 승인하면 마지막 것으로 바뀐다 (화면 기록과 같은 동작).
CREATE TABLE IF NOT EXISTS approvals (
    id             BIGSERIAL   PRIMARY KEY,
    store_id       TEXT        NOT NULL,
    visitor_id     TEXT        NOT NULL,
    draft_id       TEXT        NOT NULL,
    card_id        TEXT,                                 -- 어느 카드의 초안인지. 서버가 모르면 NULL
    kind           TEXT,                                 -- 초안 종류: reply_draft | prevention_notice | coupon_promo. 서버가 모르면 NULL
    status         TEXT        NOT NULL DEFAULT 'approved',
    approved_text  TEXT        NOT NULL,                 -- 승인한 글 (고쳤으면 고친 글)
    edited         BOOLEAN     NOT NULL DEFAULT FALSE,   -- 원문에서 고쳤는지
    approved_at    TIMESTAMPTZ NOT NULL,
    mode           TEXT        NOT NULL,                 -- 실행 방식: mock | live
    saved_at       TIMESTAMPTZ NOT NULL DEFAULT now(),   -- 마지막으로 저장한 시각. 목록은 이 순서 (다시 승인하면 맨 뒤로)
    -- 초안 정보 (이슈 #51 ERD, 11/18). 승인할 때 같이 저장한다 (초안 표는 따로 두지 않음)
    draft_text     TEXT,                                 -- AI 가 쓴 원문. approved_text 와 비교해 사장님이 고친 비율을 봄. 서버가 모르면 NULL
    checks         JSONB       NOT NULL DEFAULT '{}'::jsonb,  -- 자동 점검 결과 {점검 이름: true/false} (c6 DraftOutput.checks). 보고서·KPI 의 점검 통과율
    used_fallback  BOOLEAN     NOT NULL DEFAULT FALSE,   -- 점검에 두 번 걸려 코드 템플릿 글을 썼는지
    style          TEXT,                                 -- 답글 말투 haeyo | hamnida | mixed. 답글이 아니면 NULL
    UNIQUE (store_id, visitor_id, draft_id)
);
CREATE INDEX IF NOT EXISTS approvals_by_visitor ON approvals (store_id, visitor_id, saved_at, id);
-- 11/18 전에 만든 approvals 표에 칸 4개를 더한다 (있으면 그대로. 있던 기록의 새 칸은 NULL·'{}'·false)
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS draft_text    TEXT;
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS checks        JSONB   NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS used_fallback BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS style         TEXT;

-- 카드 추천 이유 문장. 방문자와 상관없이 근거가 같으면 같은 문장이다.
-- evidence_key: 가게·카드 종류·근거 카드(숫자)·참조 문장·프롬프트·모델·버전을 합친 해시. 이 중 하나가 바뀌면 새 키가 된다.
CREATE TABLE IF NOT EXISTS card_reasons (
    store_id      TEXT        NOT NULL,
    card_id       TEXT        NOT NULL,
    evidence_key  TEXT        NOT NULL,
    reason_text   TEXT        NOT NULL,                 -- 규칙 검사를 통과한 문장. 근거 번호([F1])가 붙은 채로
    source        TEXT        NOT NULL,                 -- 예: HCX-005 (검사기 통과)
    model         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (store_id, card_id, evidence_key)
);

-- 가게 주간·월간 보고서 (기능은 아직 없음. 저장·조회 자리만 만들어 둠).
-- 같은 (가게, 종류, 기간, 프롬프트 버전)은 덮어쓰고, 프롬프트 버전이 다르면 따로 남는다.
CREATE TABLE IF NOT EXISTS reports (
    id              BIGSERIAL   PRIMARY KEY,
    store_id        TEXT        NOT NULL,
    period_kind     TEXT        NOT NULL CHECK (period_kind IN ('weekly', 'monthly')),
    period_start    DATE        NOT NULL,
    period_end      DATE        NOT NULL,
    numbers         JSONB       NOT NULL DEFAULT '{}'::jsonb,   -- 숫자 묶음 (리뷰 수, 불만 비율, 주제별 건수 ...)
    body_text       TEXT        NOT NULL DEFAULT '',            -- 보고서 문장
    evidence_ids    TEXT[]      NOT NULL DEFAULT '{}',          -- 근거 id (rv_..., snap_...)
    prompt_version  TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (period_end >= period_start),
    UNIQUE (store_id, period_kind, period_start, period_end, prompt_version)
);
CREATE INDEX IF NOT EXISTS reports_by_period ON reports (store_id, period_kind, period_start DESC);

-- ── 로그인과 사장님 가게 (5차 회의 11/18) ─────────────────────────────────
-- 로그인하지 않은 방문자는 지금처럼 쿠키 visitor_id 로만 나뉜다 (이 표들을 쓰지 않음).
-- 로그인한 사장님은 승인 기록·붙여넣은 리뷰·마케팅 기록을 방문자 id 'u-<user_id>' 로 남긴다 (다른 표의 visitor_id 칸 그대로).
CREATE TABLE IF NOT EXISTS users (
    user_id        TEXT        PRIMARY KEY,                 -- 영문·숫자·하이픈 (방문자 id 'u-<user_id>' 가 64자 안에 들게)
    login_id       TEXT        UNIQUE NOT NULL,             -- 소문자로 저장
    password_hash  TEXT        NOT NULL,                    -- 'scrypt$N$r$p$소금$해시' (hashlib.scrypt). 비밀번호 로그인을 막은 계정은 '!'
    display_name   TEXT        NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 사장님이 가진 가게 (가게 목록 순서는 position)
CREATE TABLE IF NOT EXISTS user_stores (
    user_id   TEXT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    store_id  TEXT NOT NULL,
    position  INT  NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, store_id)
);

-- 로그인 세션. 쿠키 ic26_session 의 값은 저장하지 않고 SHA-256 만 둔다 (DB 를 봐도 세션을 훔칠 수 없게)
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash       TEXT        PRIMARY KEY,
    user_id          TEXT        NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    active_store_id  TEXT        NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at       TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_sessions_by_user ON auth_sessions (user_id);
CREATE INDEX IF NOT EXISTS auth_sessions_by_expiry ON auth_sessions (expires_at);
