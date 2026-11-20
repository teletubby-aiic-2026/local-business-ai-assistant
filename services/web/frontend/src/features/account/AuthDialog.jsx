// 로그인·회원가입 창 (예전 app.js authOpen·authTab·authDo·authLogin·authSignup, Figma 화면 16).
// /api/auth/* 만 부른다 (state/account.js 의 authDo). 성공하면 창을 닫고 모든 화면을 새 가게로 다시 읽는다.
// 세션은 HttpOnly 쿠키라 JS 가 만지지 않는다. 비밀번호 칸은 성공했을 때와 창이 닫힐 때만 비운다
// (실패하면 친 그대로 두어 아이디만 고쳐 다시 보낼 수 있게).
import { useEffect, useRef, useState } from "react";
import { useStore, setState } from "../../state/store.js";
import { authDo } from "../../state/account.js";
import { Button, Dialog, Tabs } from "../../components/ui.jsx";
import { focusAccountButton, focusStorePick, later } from "./focus.js";
import "./account.css";

const TABS = [{ id: "login", label: "로그인" }, { id: "signup", label: "회원가입" }];
// 가진 가게 (값은 예전 index.html 의 store_id)
const STORES = [{ id: "store_ongi", name: "온기한식" }, { id: "store_basak", name: "바삭치킨" }, { id: "store_mongle", name: "몽글카페" }];

export default function AuthDialog() {
  const open = useStore((s) => s.authOpen);
  const me = useStore((s) => s.me);
  const [tab, setTab] = useState("login");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [loginId, setLoginId] = useState("");
  const [loginPw, setLoginPw] = useState("");
  const [suId, setSuId] = useState("");
  const [suPw, setSuPw] = useState("");
  const [suName, setSuName] = useState("");
  const [stores, setStores] = useState(["store_ongi"]);
  const busyRef = useRef(false);
  const loginIdRef = useRef(null);
  const loginPwRef = useRef(null);
  const suIdRef = useRef(null);
  const suPwRef = useRef(null);
  const demoRef = useRef(null);
  const showDemo = !(me && me.demo_login === false);   // 서버가 시연 계정을 꺼 두면 숨김

  // 열 때: 오류를 지우고 시연 버튼(없으면 아이디 칸)으로. showModal 은 안쪽 Dialog 의 효과가 먼저 한다
  useEffect(() => {
    if (!open) return;
    setErr("");
    const first = showDemo ? document.getElementById("auth-demo") : (tab === "signup" ? suIdRef.current : loginIdRef.current);
    first?.focus();
  }, [open]);   // eslint-disable-line react-hooks/exhaustive-deps

  const clearPw = () => { setLoginPw(""); setSuPw(""); };

  // 창이 닫히면(어떤 길로든: 닫기·Esc·바깥 누르기·로그인 성공) 비밀번호를 비운다
  useEffect(() => { if (!open) clearPw(); }, [open]);

  // 닫기·Esc·바깥 누르기: 상단 바의 [로그인]으로
  const close = () => {
    setState({ authOpen: false });
    focusAccountButton();
  };

  const changeTab = (id) => { setTab(id); setErr(""); };

  // retry: 실패했을 때 포커스를 돌려줄 칸 (누른 버튼이 잠기며 포커스를 잃었을 때만)
  async function run(path, body, retry) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setErr("");
    let ok = false;
    try {
      await authDo(path, body);   // 성공하면 창을 닫고 storeChanged 까지
      ok = true;
    } catch (e) { setErr(e.message); }
    finally {
      busyRef.current = false;
      setBusy(false);
    }
    if (ok) { clearPw(); focusStorePick(); return; }
    later(() => {
      const a = document.activeElement;
      if (!a || a === document.body) retry?.current?.focus();
    });
  }

  const onLogin = (e) => {
    e.preventDefault();
    const id = loginId.trim();
    if (!id || !loginPw) { setErr("아이디와 비밀번호를 적어 주세요."); return; }
    run("login", { login_id: id, password: loginPw }, loginPwRef);
  };

  const onSignup = (e) => {
    e.preventDefault();
    const id = suId.trim(), name = suName.trim();
    if (!id || !suPw || !name) { setErr("아이디·비밀번호·이름을 모두 적어 주세요."); return; }
    if (suPw.length < 8) { setErr("비밀번호는 8자 이상으로 정해 주세요."); return; }
    if (!stores.length) { setErr("가진 가게를 하나 이상 골라 주세요."); return; }
    // 보내는 순서는 화면의 가게 순서대로 (예전 체크 상자 순서)
    run("signup", { login_id: id, password: suPw, display_name: name, stores: STORES.map((s) => s.id).filter((v) => stores.includes(v)) }, suPwRef);
  };

  const toggleStore = (id, on) => setStores((list) => (on ? [...list.filter((v) => v !== id), id] : list.filter((v) => v !== id)));

  return (
    <Dialog id="auth-dialog" open={open} onClose={close} labelledBy="auth-title" className="acct-dlg auth-dlg" aria-busy={busy || undefined}>
      <div className="dlg-head">
        <h2 id="auth-title" className="acct-title">사장님 로그인</h2>
        <Button size="small" onClick={close} disabled={busy}>닫기</Button>
      </div>
      <p className="small muted acct-tight">로그인하면 가진 가게를 골라 볼 수 있어요.</p>
      {showDemo && (
        <div className="stack-8">
          <Button ref={demoRef} id="auth-demo" variant="primary" size="big" className="acct-full" disabled={busy} onClick={() => run("demo-login", undefined, demoRef)}>
            시연 계정으로 시작
          </Button>
          <p className="small muted acct-tight">온기한식·바삭치킨·몽글카페 3곳을 가진 시연 계정이에요. 브라우저마다 기록이 따로예요.</p>
        </div>
      )}
      <Tabs tabs={TABS} active={tab} onChange={changeTab} idPrefix="auth" label="로그인 또는 회원가입" />
      <p className="acct-error" role="alert" hidden={!err}>{err}</p>

      <form id="auth-panel-login" className="stack-16" role="tabpanel" aria-labelledby="auth-tab-login" noValidate hidden={tab !== "login"} onSubmit={onLogin}>
        <label className="field">아이디
          <input ref={loginIdRef} name="login_id" autoComplete="username" maxLength={32} required value={loginId} onChange={(e) => setLoginId(e.target.value)} />
        </label>
        <label className="field">비밀번호
          <input ref={loginPwRef} name="password" type="password" autoComplete="current-password" maxLength={128} required value={loginPw} onChange={(e) => setLoginPw(e.target.value)} />
        </label>
        <Button type="submit" variant="primary" className="acct-full" disabled={busy}>로그인</Button>
      </form>

      <form id="auth-panel-signup" className="stack-16" role="tabpanel" aria-labelledby="auth-tab-signup" noValidate hidden={tab !== "signup"} onSubmit={onSignup}>
        <label className="field"><span>아이디 <span className="small muted">영문 소문자·숫자 3~32자</span></span>
          <input ref={suIdRef} name="login_id" autoComplete="username" maxLength={32} required value={suId} onChange={(e) => setSuId(e.target.value)} />
        </label>
        <label className="field"><span>비밀번호 <span className="small muted">8자 이상</span></span>
          <input ref={suPwRef} name="password" type="password" autoComplete="new-password" minLength={8} maxLength={128} required value={suPw} onChange={(e) => setSuPw(e.target.value)} />
        </label>
        <label className="field">이름
          <input name="display_name" autoComplete="name" maxLength={20} required value={suName} onChange={(e) => setSuName(e.target.value)} />
        </label>
        <fieldset className="acct-stores">
          <legend>가진 가게</legend>
          {STORES.map((s) => (
            <label key={s.id}>
              <input type="checkbox" value={s.id} checked={stores.includes(s.id)} onChange={(e) => toggleStore(s.id, e.target.checked)} /> {s.name}
            </label>
          ))}
        </fieldset>
        <Button type="submit" variant="primary" className="acct-full" disabled={busy}>가입하고 시작</Button>
      </form>
    </Dialog>
  );
}
