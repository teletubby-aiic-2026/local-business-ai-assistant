// A1 로그인 (Figma '06 설계 기준 화면' A1). 전체 화면 2단: 왼쪽 소개, 오른쪽 로그인 카드 (760px 이하는 1단).
// 성공하면 가게 선택(A3)으로 (state/account.js authDo). 세션은 HttpOnly 쿠키라 JS 가 만지지 않는다.
// 비밀번호 칸은 실패해도 비우지 않는다 (아이디만 고쳐 다시 보낼 수 있게). 화면을 떠나면 컴포넌트와 함께 사라진다.
// '시연 사장님으로 시작'은 시험용 실행(mock)이고 서버가 시연 계정을 켜 둔(me.demo_login) 때만 보인다 (6차 회의: 실제 서버에서는 숨김)
import { useRef, useState } from "react";
import { useStore } from "../../state/store.js";
import { setStage } from "../../state/stage.js";
import { authDo } from "../../state/account.js";
import { isTestRun } from "../../lib/domain.js";
import { later } from "../../lib/focus.js";
import { Button, Logo } from "../../components/ui.jsx";
import { ModeBand, StageTitle } from "./Stage.jsx";
import "./account.css";

const POINTS = [
  { title: "리뷰 분석", text: "배달앱 리뷰를 붙여넣거나 캡처로 넣으면 감정·주제로 나눠요" },
  { title: "글 써 주기", text: "답글·포장·주문 안내문·쿠폰 홍보글을 AI가 쓰고, 올리기 전에 점검해요" },
  { title: "상권 보기", text: "서울시 공식 자료로 우리 가게 주변 상권을 봐요" },
];

// 로그인·회원가입이 같이 쓰는 2단 틀
export function AuthLayout({ intro, introLabel, children }) {
  return (
    <div className="stage-page auth-page">
      <ModeBand />
      <div className="auth-split">
        <section className="auth-intro" aria-label={introLabel}>{intro}</section>
        <main id="main" className="auth-side">
          <div className="panel auth-card">{children}</div>
        </main>
      </div>
    </div>
  );
}

// 로그인·회원가입이 같이 쓰는 보내기: 잠그고, 실패하면 오류 문장을 돌려준다 (성공하면 단계가 바뀌어 이 화면이 사라짐)
export function useAuthRun() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const busyRef = useRef(false);
  // retry: 실패했을 때 포커스를 돌려줄 칸 (누른 버튼이 잠기며 포커스를 잃었을 때만)
  async function run(path, body, retry) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setErr("");
    try { await authDo(path, body); }
    catch (e) {
      setErr(e.message);
      later(() => {
        const a = document.activeElement;
        if (!a || a === document.body) retry?.current?.focus();
      });
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  return { busy, err, setErr, run };
}

export default function Login() {
  const me = useStore((s) => s.me);
  const health = useStore((s) => s.health);
  const resume = useStore((s) => s.resume);
  const [loginId, setLoginId] = useState(() => (resume && resume.loginId) || "");
  const [pw, setPw] = useState("");
  const [keep, setKeep] = useState(false);
  const [forgot, setForgot] = useState(false);
  const { busy, err, setErr, run } = useAuthRun();
  const idRef = useRef(null);
  const pwRef = useRef(null);
  const demoRef = useRef(null);
  const showDemo = isTestRun(health) && !!(me && me.demo_login === true);

  const onLogin = (e) => {
    e.preventDefault();
    const id = loginId.trim();
    if (!id || !pw) { setErr("아이디와 비밀번호를 적어 주세요."); (id ? pwRef : idRef).current?.focus(); return; }
    run("login", { login_id: id, password: pw, keep }, pwRef);
  };

  const intro = (
    <>
      <p className="auth-brand"><Logo />텔레토비 AI 비서</p>
      <p className="auth-hero">사장님, 오늘 할 일만<br />골라 드릴게요</p>
      <p className="auth-lead">리뷰를 모아 불만을 묶고, 답글·안내문·홍보글을 써 드려요. 사장님은 읽고 고치고 승인만 하면 됩니다.</p>
      <ul className="plain auth-points">
        {POINTS.map((p) => <li key={p.title}><b>{p.title}</b><span>{p.text}</span></li>)}
      </ul>
    </>
  );

  return (
    <AuthLayout intro={intro} introLabel="서비스 소개">
      <div className="stack-8">
        <StageTitle>사장님 로그인</StageTitle>
        <p className="small muted">가게 정보와 리뷰는 계정마다 따로 보관돼요.</p>
      </div>
      <p className="acct-error" role="alert" hidden={!err}>{err}</p>
      <form id="auth-login" className="stack-16" noValidate onSubmit={onLogin} aria-busy={busy || undefined}>
        <label className="field">아이디
          <input ref={idRef} name="login_id" autoComplete="username" autoCapitalize="none" spellCheck={false} maxLength={32} required
            placeholder="영문 소문자·숫자" value={loginId} onChange={(e) => setLoginId(e.target.value)} />
        </label>
        <label className="field">비밀번호
          <input ref={pwRef} name="password" type="password" autoComplete="current-password" maxLength={128} required
            placeholder="8자 이상" value={pw} onChange={(e) => setPw(e.target.value)} />
        </label>
        <div className="auth-row">
          <label className="auth-check"><input type="checkbox" name="keep" checked={keep} onChange={(e) => setKeep(e.target.checked)} />로그인 상태 유지 (7일)</label>
          <Button variant="text" size="small" aria-expanded={forgot} aria-controls="auth-forgot" onClick={() => setForgot(true)}>비밀번호를 잊었어요</Button>
        </div>
        <p id="auth-forgot" className="small muted auth-forgot" hidden={!forgot}>비밀번호 찾기는 아직 지원하지 않아요. 새 계정을 만들어 주세요.</p>
        <Button type="submit" variant="primary" size="big" className="acct-full" disabled={busy}>로그인</Button>
      </form>
      {showDemo && (
        <div className="stack-16">
          <p className="auth-or small muted" aria-hidden="true"><span>또는</span></p>
          <Button ref={demoRef} id="auth-demo" className="acct-full" disabled={busy} onClick={() => run("demo-login", undefined, demoRef)}>
            시연 사장님으로 1초 시작 (가게 3곳)
          </Button>
        </div>
      )}
      <p className="auth-switch small">처음이신가요? <Button variant="text" size="small" disabled={busy} onClick={() => setStage("signup")}>회원가입</Button></p>
    </AuthLayout>
  );
}
