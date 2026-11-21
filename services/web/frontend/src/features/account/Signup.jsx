// A2 회원가입 (Figma '06 설계 기준 화면' A2). 왼쪽 '세 단계' 안내, 오른쪽 가입 카드.
// 가입은 가게 없이(stores: []) 하고, 성공하면 새 가게 등록(store-new, mode "signup")으로 (state/account.js authDo).
// 입력 규칙은 서버와 같게 미리 본다 (docs/api/contract.md 1.13): 아이디 영문 소문자·숫자로 시작 3~32자(. _ - 가능), 비밀번호 8자 이상, 이름 1~20자
import { useRef, useState } from "react";
import { setStage } from "../../state/stage.js";
import { Button, Icon } from "../../components/ui.jsx";
import { StageTitle } from "./Stage.jsx";
import { AuthLayout, useAuthRun } from "./Login.jsx";
import "./account.css";

const ID_RULE = /^[a-z0-9][a-z0-9._-]{2,31}$/;

const STEPS = [
  { title: "계정 만들기", text: "아이디·비밀번호·이름" },
  { title: "가게 등록", text: "가게 이름·업종·위치·메뉴 (가입 뒤 바로)" },
  { title: "홈으로", text: "오늘 할 일부터 시작" },
];

export default function Signup() {
  const [loginId, setLoginId] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [name, setName] = useState("");
  const [agree, setAgree] = useState(false);
  const { busy, err, setErr, run } = useAuthRun();
  const refs = { id: useRef(null), pw: useRef(null), pw2: useRef(null), name: useRef(null), agree: useRef(null) };

  // 틀린 첫 칸으로 포커스
  const fail = (msg, key) => { setErr(msg); refs[key].current?.focus(); };

  const onSignup = (e) => {
    e.preventDefault();
    const id = loginId.trim().toLowerCase(), nm = name.trim();
    if (!ID_RULE.test(id)) return fail("아이디는 영문 소문자나 숫자로 시작하는 3~32자로 정해 주세요.", "id");
    if (pw.length < 8) return fail("비밀번호는 8자 이상으로 정해 주세요.", "pw");
    if (pw !== pw2) return fail("비밀번호 확인이 맞지 않아요.", "pw2");
    if (!nm) return fail("이름을 적어 주세요.", "name");
    if (!agree) return fail("이용 약관과 개인정보 처리에 동의해 주세요.", "agree");
    run("signup", { login_id: id, password: pw, display_name: nm, stores: [] }, refs.pw);
  };

  const intro = (
    <>
      <p className="auth-hero">세 단계면 시작해요</p>
      <ol className="plain auth-steps">
        {STEPS.map((s, i) => (
          <li key={s.title} aria-current={i === 0 ? "step" : undefined}>
            <span className="auth-step-n" aria-hidden="true">{i + 1}</span>
            <span className="auth-step-t"><b>{s.title}</b><span>{s.text}</span></span>
          </li>
        ))}
      </ol>
    </>
  );

  return (
    <AuthLayout intro={intro} introLabel="가입 순서">
      {/* 돌아갈 길이 맨 아래 링크뿐이라 휴대폰에서는 끝까지 내려야 했다: 제목 위에 뒤로 버튼 (11/21 QA) */}
      <Button variant="text" size="small" className="auth-back" disabled={busy} onClick={() => setStage("login")}>
        <Icon name="뒤로" size={18} />로그인으로 돌아가기
      </Button>
      <StageTitle>계정 만들기</StageTitle>
      <p className="acct-error" role="alert" hidden={!err}>{err}</p>
      <form id="auth-signup" className="stack-16" noValidate onSubmit={onSignup} aria-busy={busy || undefined}>
        <label className="field">아이디
          <input ref={refs.id} name="login_id" autoComplete="username" autoCapitalize="none" spellCheck={false} maxLength={32} required
            placeholder="영문 소문자·숫자 3~32자" value={loginId} onChange={(e) => setLoginId(e.target.value)} />
        </label>
        <label className="field">비밀번호
          <input ref={refs.pw} name="password" type="password" autoComplete="new-password" minLength={8} maxLength={128} required
            placeholder="8자 이상" value={pw} onChange={(e) => setPw(e.target.value)} />
        </label>
        <label className="field">비밀번호 확인
          <input ref={refs.pw2} name="password_confirm" type="password" autoComplete="new-password" maxLength={128} required
            placeholder="한 번 더" value={pw2} onChange={(e) => setPw2(e.target.value)} />
        </label>
        {/* 예시는 '사장'이 붙지 않는 이름으로: 화면이 이름 뒤에 '사장님'을 붙인다 (11/21 QA) */}
        <label className="field">이름
          <input ref={refs.name} name="display_name" autoComplete="name" maxLength={20} required
            placeholder="화면에 보일 이름 (예: 김온기)" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <div className="stack-8">
          <label className="auth-check"><input ref={refs.agree} type="checkbox" name="agree" checked={agree} aria-describedby="auth-agree-note"
            onChange={(e) => setAgree(e.target.checked)} />이용 약관과 개인정보 처리에 동의해요 (필수)</label>
          <p id="auth-agree-note" className="small muted">아이디·이름·가게 정보를 저장해요. 탈퇴하면 계정과 기록을 지워요.</p>
        </div>
        <Button type="submit" variant="primary" size="big" className="acct-full" disabled={busy}>가입하고 가게 등록하기</Button>
      </form>
      <p className="auth-switch small">이미 계정이 있나요? <Button variant="text" size="small" disabled={busy} onClick={() => setStage("login")}>로그인</Button></p>
    </AuthLayout>
  );
}
