// 기록 지우기·회원 탈퇴 확인 창 (예전 '내 계정' 창의 확인 단계, Figma 화면 17 → 11/20 사장님 프로필 A5 의 '기록과 탈퇴'에서 엶).
// act: "store"(지금 가게 기록) · "account"(모든 가게 기록) · "withdraw"(회원 탈퇴), null 이면 닫힘. 기본 포커스는 [취소], Esc 도 취소.
// 순서: 상권 대화 지우기(DELETE /api/assistant/conversation, 실패·꺼짐은 무시) → POST /api/auth/reset 또는 /api/auth/withdraw.
// 탈퇴는 일반 계정이면 비밀번호를 한 번 더 받고(보낸 뒤 칸을 비움), 시연 계정(user.demo)은 칸 없이 본문 {}.
// 지우기가 끝나면 들어가 있던 가게의 자료를 다시 읽고(storeChanged), 탈퇴가 끝나면 로그인 화면으로 (state/account.js signedOut).
// 결과 한 줄(acctNotice)은 창 밖 오른쪽 아래 띠(AcctToast)에 남긴다. 401 login_needed 는 '다시 로그인' 화면으로 (acctApi.js)
import { useEffect, useRef, useState } from "react";
import { useStore, getState, setState } from "../../state/store.js";
import { storeChanged } from "../../state/boot.js";
import { signedOut } from "../../state/account.js";
import { later } from "../../lib/focus.js";
import { Button, Dialog } from "../../components/ui.jsx";
import { ACCT_ACTS, acctPost, clearChat, isDemo, storeName, summary } from "./acctApi.js";
import "./account.css";

// onClose: 닫아 달라는 요청 (부르는 쪽이 act 를 null 로). returnFocus: 닫힌 뒤 포커스를 돌려줄 요소의 ref
export default function AccountDialog({ act, onClose, returnFocus }) {
  const me = useStore((s) => s.me);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [pw, setPw] = useState("");
  const [retryShown, setRetryShown] = useState(false);   // 일부만 지웠을 때 버튼을 '다시 지우기'로
  const busyRef = useRef(false);
  const cancelRef = useRef(null);
  const pwRef = useRef(null);
  const open = !!act;
  const conf = act ? ACCT_ACTS[act] : null;
  const demo = isDemo(me);
  const name = storeName(me);
  const all = ((me && me.stores) || []).length;

  // 열 때: 오류·비밀번호를 비우고 [취소]로 (Enter 한 번으로 지워지지 않게)
  useEffect(() => {
    if (!act) return;
    setErr(""); setPw(""); setRetryShown(false);
    later(() => cancelRef.current?.focus());
  }, [act]);

  function lock(on) { busyRef.current = on; setBusy(on); }
  function cancel() { if (!busyRef.current) onClose(); }

  async function submit(e) {
    e.preventDefault();
    if (busyRef.current || !act) return;
    const isDemoNow = isDemo(getState().me), pwv = pw;
    setErr("");
    if (act === "withdraw" && !isDemoNow && !pwv) { setErr("비밀번호를 적어 주세요."); pwRef.current?.focus(); return; }
    lock(true);
    let focusPw = false, retry = false, closeNow = false;
    try {
      await clearChat();                                                            // ① 상권 대화
      if (act === "withdraw") {
        const r = await acctPost("/api/auth/withdraw", isDemoNow ? {} : { password: pwv });   // ② 계정과 기록
        setPw("");
        lock(false);
        signedOut(r);                                                               // ③ 로그인 화면 (이 창도 함께 사라짐)
        setState({ acctNotice: "회원 탈퇴를 마쳤어요. 계정과 기록을 모두 지웠어요." });
        return;
      }
      const r = await acctPost("/api/auth/reset", { scope: act });                 // ② 기록
      setState((s) => ({ reportsSeq: s.reportsSeq + 1 }));                         // 프로필의 '보관한 보고서' 수를 다시 부름 (일부만 지워졌어도)
      const sum = summary(r);
      if (r.complete === false) {
        // 일부만 지웠다: 창에 남은 것을 알리고 [다시 지우기]
        setErr(`${r.message || "일부 기록을 지우지 못했어요."}${sum ? ` (${sum})` : ""} 다시 눌러 지울 수 있어요.`);
        retry = true;
      } else closeNow = true;
      lock(false);
      if (closeNow) onClose();
      if (getState().entered) await storeChanged();                                // ③ 들어가 있던 가게의 화면을 서버 기준으로 다시
      if (closeNow) setState({ acctNotice: `기록을 지웠어요. ${sum}`.trim() });   // storeChanged 가 띠를 비우므로 그 뒤에
    } catch (error) {
      if (error.authHandled) return;                                                // 다시 로그인 화면으로 바뀜
      setErr(error.message);
      focusPw = error.state === "bad_password";                                    // 비밀번호가 틀렸으면 칸으로 (칸은 비운 채)
    } finally {
      setPw("");                                                                    // 보낸 뒤 비밀번호 칸은 늘 비운다
      if (busyRef.current) lock(false);
      if (!closeNow && getState().stage === "profile") {
        setRetryShown(retry);
        later(() => (focusPw ? pwRef : cancelRef).current?.focus());
      }
    }
  }

  // Esc 는 keydown 에서 먼저 받는다: Chrome 은 Esc 를 연달아 누르면 cancel 을 막을 수 없게(cancelable=false) 보내 창이 닫혀 버린다
  const onKeyDown = (e) => {
    if (e.key !== "Escape" || e.nativeEvent.isComposing) return;
    e.preventDefault(); e.stopPropagation();
    cancel();
  };
  const onCancel = (e) => { e.preventDefault(); cancel(); };

  const goText = busy ? conf?.busy : retryShown ? "다시 지우기" : conf?.go;

  return (
    <Dialog id="acct-dialog" open={open} className="acct-dlg" labelledBy="acct-confirm-title" aria-busy={busy}
      onKeyDown={onKeyDown} onCancel={onCancel} onClose={cancel}
      onClosed={() => { const el = returnFocus?.current; if (el && el.isConnected) later(() => el.focus()); }}>
      <form className="stack-16" noValidate onSubmit={submit}>
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
  );
}

// 결과 띠: 화면 오른쪽 아래 (모든 단계에서. 탈퇴 뒤 로그인 화면에도 남음)
export function AcctToast() {
  const notice = useStore((s) => s.acctNotice);
  return (
    <div className="acct-toast" role="status" hidden={!notice}>
      <span>{notice}</span>
      <Button variant="text" size="small" onClick={() => setState({ acctNotice: "" })}>닫기</Button>
    </div>
  );
}
