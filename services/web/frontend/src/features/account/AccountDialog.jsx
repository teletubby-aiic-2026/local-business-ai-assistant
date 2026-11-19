// 내 계정 창: 로그아웃·기록 지우기·회원 탈퇴 (예전 app.js acctOpen·acctStep·acctSubmit·acctCancel·acctClosed, Figma 화면 17).
// 로그인한 사장님만 (게스트는 상단 바에 이름 버튼이 없다). 동작을 누르면 같은 창 안에서 확인 단계로 바뀌고
// (기본 포커스는 [취소], Esc 도 취소), [지우기]를 눌러야 서버에 보낸다.
// 순서: 상권 대화 지우기(DELETE /api/assistant/conversation, 실패·꺼짐은 무시) → POST /api/auth/reset 또는 /api/auth/withdraw.
// 탈퇴는 일반 계정이면 비밀번호를 한 번 더 받고(보낸 뒤 칸을 비움), 시연 계정(user.demo)은 칸 없이 본문 {}.
// 끝나면 storeChanged() 로 모든 화면을 서버 기준으로 다시 읽고, 결과 한 줄(acctNotice)은 창 밖 오른쪽 아래 띠에 남긴다.
// [로그아웃]도 여기 있다 (760px 이하에서는 왼쪽 메뉴의 계정 줄이 숨어서 상단 바 이름 버튼 → 이 창이 유일한 길).
// 공통 Dialog 를 쓰되 확인 단계의 Esc 는 keydown 에서 먼저 받는다 (아래 onKeyDown)
import { useEffect, useRef, useState } from "react";
import { useStore, getState, setState } from "../../state/store.js";
import { storeChanged } from "../../state/boot.js";
import { acctLogout } from "../../state/account.js";
import { api } from "../../lib/api.js";
import { Button, Dialog } from "../../components/ui.jsx";
import { ACCT_ACTS, acctPost, clearChat, isDemo, storeName, summary } from "./acctApi.js";
import { focusAccountButton, later } from "./focus.js";
import "./account.css";

export default function AccountDialog() {
  const open = useStore((s) => s.acctOpen);
  const me = useStore((s) => s.me);
  const notice = useStore((s) => s.acctNotice);
  const reloading = useStore((s) => s.acctBusy);   // 로그인·가게 바꾸기 뒤 다시 읽는 중 (상단 바 계정 버튼과 같이 잠금)
  const [act, setAct] = useState(null);       // null 이면 계정 정보와 동작, 있으면 그 동작의 확인 단계
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [pw, setPw] = useState("");
  const [retryShown, setRetryShown] = useState(false);   // 일부만 지웠을 때 버튼을 '다시 지우기'로
  // 이벤트 사이에 바로 읽어야 하는 값 (예전 acctX)
  const x = useRef({ act: null, busy: false, from: null, stale: false, out: false });
  const closeRef = useRef(null);
  const cancelRef = useRef(null);
  const pwRef = useRef(null);

  const demo = isDemo(me);
  const name = storeName(me);
  const all = ((me && me.stores) || []).length;
  const u = (me && me.user) || {};
  const conf = act ? ACCT_ACTS[act] : null;

  // 두 단계 바꾸기. 확인 단계로 가면 Enter 한 번으로 지워지지 않게 [취소]에 포커스
  function step(a) {
    x.current.act = a || null;
    setAct(a || null);
    setErr("");
    setPw("");
    setRetryShown(false);
    if (a) later(() => cancelRef.current?.focus());
  }

  function lock(on) { x.current.busy = on; setBusy(on); }

  // 요청 중에는 닫지 않는다
  function close() {
    if (x.current.busy) return;
    setState({ acctOpen: false });
  }

  // 닫힌 뒤 (닫기·Esc·바깥 누르기 모두): 확인 단계를 치우고 이름 버튼으로. 로그인이 풀린 것을 봤으면 게스트로 다시 읽는다.
  // 로그아웃으로 닫혔으면 포커스는 로그아웃이 끝난 뒤 [로그인]으로 (state/account.js)
  async function onClosed() {
    if (getState().acctOpen) setState({ acctOpen: false });
    step(null);
    if (x.current.out) { x.current.out = false; return; }
    if (x.current.stale) {
      x.current.stale = false;
      let m = null;
      try { m = await api("/api/auth/me"); } catch { m = null; }
      setState({ me: m });
      await storeChanged();
    }
    focusAccountButton();
  }

  // 열 때 (창은 안쪽 Dialog 의 효과가 먼저 띄운다): 처음 단계로, 포커스는 [닫기]. 닫히는 것은 Dialog 가 하고 onClosed 를 부른다
  useEffect(() => {
    if (!open) return;
    if (!me || !me.authenticated) { setState({ acctOpen: false }); return; }
    setState({ acctNotice: "" });
    step(null);
    closeRef.current?.focus();
  }, [open]);   // eslint-disable-line react-hooks/exhaustive-deps

  // [로그아웃]: 창을 닫고 로그아웃 (끝나면 상단 바 [로그인]으로 포커스)
  function logout() {
    if (x.current.busy || getState().acctBusy) return;
    x.current.out = true;
    setState({ acctOpen: false });
    acctLogout();
  }

  // 확인 단계에서 [취소]·Esc: 창은 그대로, 처음 단계로 (누른 동작 버튼으로 포커스)
  function cancel() {
    if (x.current.busy) return;
    const from = x.current.from;
    step(null);
    later(() => (from && from.isConnected && !from.hidden ? from : closeRef.current)?.focus());
  }

  function pick(a, e) { x.current.from = e.currentTarget; step(a); }

  // [지우기]·[탈퇴하기] (확인 단계의 submit)
  async function submit(e) {
    e.preventDefault();
    const a = x.current.act;
    if (x.current.busy || !a) return;
    const isDemoNow = isDemo(getState().me), pwv = pw;
    setErr("");
    if (a === "withdraw" && !isDemoNow && !pwv) { setErr("비밀번호를 적어 주세요."); pwRef.current?.focus(); return; }
    lock(true);
    let keepOpen = true, focusPw = false, retry = false;
    try {
      await clearChat();                                                          // ① 상권 대화
      if (a === "withdraw") {
        const r = await acctPost("/api/auth/withdraw", isDemoNow ? {} : { password: pwv });   // ② 계정과 기록
        setPw("");
        keepOpen = false;
        let m = r && r.authenticated === false ? r : null;
        if (!m) { try { m = await api("/api/auth/me"); } catch { m = null; } }
        setState({ me: m });
        lock(false);
        close();
        await storeChanged();                                                     // ③ 로그아웃 때와 같은 게스트 화면
        setState({ acctNotice: "회원 탈퇴를 마쳤어요. 계정과 기록을 모두 지웠어요." });   // storeChanged 가 비우므로 그 뒤에
        focusAccountButton();                                                     // [로그인]으로
        return;
      }
      const r = await acctPost("/api/auth/reset", { scope: a });                 // ② 기록
      const sum = summary(r);
      if (r.complete === false) {
        // 일부만 지웠다: 창에 남은 것을 알리고 [다시 지우기]. 지운 것은 화면에도 반영한다
        setErr(`${r.message || "일부 기록을 지우지 못했어요."}${sum ? ` (${sum})` : ""} 다시 눌러 지울 수 있어요.`);
        retry = true;
      } else keepOpen = false;
      lock(false);
      if (!keepOpen) close();
      await storeChanged();                                                       // ③ 서버 기준으로 모든 화면 다시
      if (!keepOpen) { setState({ acctNotice: `기록을 지웠어요. ${sum}`.trim() }); focusAccountButton(); }   // 새 화면 제목으로 간 포커스를 이름 버튼으로
    } catch (error) {
      setErr(error.message);
      if (error.status === 401 && error.state === "login_needed") x.current.stale = true;
      focusPw = error.state === "bad_password";                                  // 비밀번호가 틀렸으면 칸으로 (칸은 비운 채)
    } finally {
      setPw("");                                                                  // 보낸 뒤 비밀번호 칸은 늘 비운다
      if (x.current.busy) lock(false);
      if (keepOpen && x.current.act) {
        setRetryShown(retry);
        later(() => (focusPw ? pwRef : cancelRef).current?.focus());
      }
    }
  }

  // Esc 는 keydown 에서 먼저 받는다: Chrome 은 Esc 를 연달아 누르면 cancel 을 막을 수 없게(cancelable=false) 보내 창이 닫혀 버린다
  const onKeyDown = (e) => {
    if (e.key !== "Escape" || e.nativeEvent.isComposing || !(x.current.busy || x.current.act)) return;
    e.preventDefault(); e.stopPropagation();
    cancel();
  };
  const onCancel = (e) => {
    if (x.current.busy) { e.preventDefault(); return; }
    if (x.current.act) { e.preventDefault(); cancel(); }
  };

  const goText = busy ? conf?.busy : retryShown ? "다시 지우기" : conf?.go;

  return (
    <>
      {/* 바깥 누르기·Esc 는 확인 단계가 아닐 때만 창을 닫는다 (확인 단계의 Esc 는 onKeyDown·onCancel 이 '취소'로) */}
      <Dialog id="acct-dialog" open={open} className="acct-dlg" labelledBy={act ? "acct-confirm-title" : "acct-title"} aria-busy={busy}
        onKeyDown={onKeyDown} onCancel={onCancel} onClosed={onClosed}
        onClose={() => { if (!x.current.act) close(); }}>
        <div className="stack-16" hidden={!!act}>
          <div className="dlg-head">
            <h2 id="acct-title" className="acct-title">내 계정</h2>
            <Button ref={closeRef} size="small" onClick={close} disabled={busy}>닫기</Button>
          </div>
          <dl className="inset acct-info">
            <div><dt>이름</dt><dd>{String(u.display_name || "")}</dd></div>
            <div><dt>아이디</dt><dd>{u.demo ? "시연 계정" : String(u.login_id || "")}</dd></div>
            <div><dt>가진 가게</dt><dd>{((me && me.stores) || []).map((s) => s.name).join(" · ") || "없음"}</dd></div>
          </dl>
          <div className="acct-actions">
            <Button id="acct-logout" disabled={busy || reloading} onClick={logout}>로그아웃</Button>
          </div>
          <section className="stack-8" aria-labelledby="acct-sub-reset">
            <h3 id="acct-sub-reset" className="acct-sub">기록 지우기</h3>
            <p className="small muted acct-tight">승인 기록·붙여넣은 리뷰·맞춤 마케팅 기록·AI 대화를 지워요.</p>
            <div className="acct-actions">
              <Button disabled={busy} onClick={(e) => pick("store", e)}>{`${name} 기록 지우기`}</Button>
              <Button disabled={busy} onClick={(e) => pick("account", e)}>모든 가게 기록 지우기</Button>
            </div>
          </section>
          <section className="stack-8" aria-labelledby="acct-sub-withdraw">
            <h3 id="acct-sub-withdraw" className="acct-sub">회원 탈퇴</h3>
            <p className="small acct-tight acct-bad">계정과 모든 가게 기록을 지우고, 이 아이디로 다시 로그인할 수 없어요.</p>
            <div className="acct-actions">
              <Button variant="danger" disabled={busy} onClick={(e) => pick("withdraw", e)}>회원 탈퇴</Button>
            </div>
          </section>
        </div>

        <form className="stack-16" noValidate hidden={!act} onSubmit={submit}>
          {conf && (
            <>
              <h2 id="acct-confirm-title" className="acct-title" tabIndex={-1}>{conf.title(name)}</h2>
              <p className="acct-tight">{conf.lead(name, all, demo)}</p>
              <div className="acct-lists">
                <div>
                  <p className="acct-list-title">지워지는 것</p>
                  <ul className="acct-list">{conf.gone.map((t) => <li key={t}>{t}</li>)}</ul>
                </div>
                <div>
                  <p className="acct-list-title">그대로 남는 것</p>
                  <ul className="acct-list">{conf.kept.map((t) => <li key={t}>{t}</li>)}</ul>
                </div>
              </div>
              {/* 탈퇴(일반 계정)만: 비밀번호 한 번 더. 보낸 뒤 비운다. 시연 계정은 칸 없음 */}
              {act === "withdraw" && !demo && (
                <label className="field">비밀번호 확인
                  <input ref={pwRef} name="password" type="password" autoComplete="current-password" maxLength={128}
                    disabled={busy} value={pw} onChange={(e) => setPw(e.target.value)} />
                </label>
              )}
              <p className="acct-irrev">{conf.irrev || "지우면 되돌릴 수 없어요."}</p>
            </>
          )}
          <p className="acct-error" role="alert" hidden={!err}>{err}</p>
          <div className="btn-row acct-confirm-btns">
            <Button ref={cancelRef} disabled={busy} onClick={cancel}>취소</Button>
            <Button type="submit" variant="danger" disabled={busy}>{goText}</Button>
          </div>
        </form>
      </Dialog>

      <div className="acct-toast" role="status" hidden={!notice}>
        <span>{notice}</span>
        <Button variant="text" size="small" onClick={() => setState({ acctNotice: "" })}>닫기</Button>
      </div>
    </>
  );
}
