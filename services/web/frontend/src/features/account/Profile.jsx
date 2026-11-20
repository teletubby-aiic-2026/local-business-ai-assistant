// A5 사장님 프로필 (Figma '06 설계 기준 화면' A5). 가게 선택 화면의 [사장님 프로필], 상단 바·왼쪽 메뉴의 이름에서 온다.
// - 내 정보: 이름 저장(PATCH /api/account/profile), 비밀번호 바꾸기(POST /api/account/password), 아이디는 읽기 전용, 가입일
// - 내 가게: 목록(GET /api/account/stores), 정보 고치기(직접 등록한 가게만 → 새 가게 등록 화면 mode "edit"), 빼기(확인 뒤 DELETE),
//   순서 바꾸기([위로]·[아래로] → PUT /api/account/stores/order), + 새 가게 등록
// - 기록과 탈퇴: 예전 '내 계정' 창의 기록 지우기(이 가게·모든 가게)와 회원 탈퇴 (확인 창 AccountDialog.jsx)
// 그림의 '보관한 보고서' 구역은 만들지 않았다 (서버에 보고서 저장 기능이 없음)
import { useEffect, useRef, useState } from "react";
import { useStore, getState, setState } from "../../state/store.js";
import { backToStore, goStoreNew, writeEntered } from "../../state/stage.js";
import { acctLoad } from "../../state/boot.js";
import { displayName } from "../../state/account.js";
import { later } from "../../lib/focus.js";
import { Button, Icon, Panel } from "../../components/ui.jsx";
import { Face, StageFrame, StageTitle, WhoText } from "./Stage.jsx";
import AccountDialog from "./AccountDialog.jsx";
import { changePassword, isDemo, listStores, orderStores, removeStore, saveProfile, storeName } from "./acctApi.js";
import "./account.css";

function MyInfo({ me }) {
  const u = (me && me.user) || {};
  const [name, setName] = useState(String(u.display_name || ""));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState({ text: "", bad: false });
  const [pwOpen, setPwOpen] = useState(false);
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [next2, setNext2] = useState("");
  const curRef = useRef(null), nextRef = useRef(null), next2Ref = useRef(null), pwBtnRef = useRef(null);
  const trimmed = name.trim();
  const changed = trimmed && trimmed !== String(u.display_name || "");

  async function onSave(e) {
    e.preventDefault();
    if (busy) return;
    if (!trimmed) { setMsg({ text: "이름을 적어 주세요.", bad: true }); return; }
    setBusy(true); setMsg({ text: "", bad: false });
    try {
      const m = await saveProfile(trimmed);
      setState({ me: m && m.user ? m : { ...getState().me, user: { ...u, display_name: trimmed } } });
      setName(trimmed);
      setMsg({ text: "이름을 저장했어요.", bad: false });
    } catch (err) { if (!err.authHandled) setMsg({ text: err.message, bad: true }); }
    finally { setBusy(false); }
  }

  function closePw() { setPwOpen(false); setCur(""); setNext(""); setNext2(""); later(() => pwBtnRef.current?.focus()); }

  async function onPassword(e) {
    e.preventDefault();
    if (busy) return;
    const fail = (text, ref) => { setMsg({ text, bad: true }); ref.current?.focus(); };
    if (!cur) return fail("지금 비밀번호를 적어 주세요.", curRef);
    if (next.length < 8) return fail("새 비밀번호는 8자 이상으로 정해 주세요.", nextRef);
    if (next !== next2) return fail("새 비밀번호 확인이 맞지 않아요.", next2Ref);
    setBusy(true); setMsg({ text: "", bad: false });
    let ok = false, bad = "";
    try { await changePassword(cur, next); ok = true; }
    catch (err) { if (err.authHandled) return; bad = err.state; setMsg({ text: err.message, bad: true }); }
    finally {
      setBusy(false);
      setCur(""); setNext(""); setNext2("");                                     // 보낸 뒤 비밀번호 칸은 늘 비운다
    }
    if (ok) { setMsg({ text: "비밀번호를 바꿨어요.", bad: false }); closePw(); }
    else if (bad === "bad_password") later(() => curRef.current?.focus());
  }

  return (
    <Panel title="내 정보" titleId="prof-info-title" className="prof-panel">
      <form className="stack-16" noValidate onSubmit={onSave}>
        <div className="grid-2">
          <label className="field">이름
            <input name="display_name" autoComplete="name" maxLength={20} value={name} disabled={busy} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field"><span>아이디 <span className="muted">(바꿀 수 없음)</span></span>
            <input name="login_id" readOnly value={u.demo ? "시연 계정" : String(u.login_id || "")} />
          </label>
        </div>
        <div className="btn-row">
          <Button type="submit" variant="primary" disabled={busy || !changed}>이름 저장</Button>
          {!u.demo && (
            <Button ref={pwBtnRef} aria-expanded={pwOpen} aria-controls="prof-pw" disabled={busy}
              onClick={() => { setMsg({ text: "", bad: false }); setPwOpen(true); later(() => curRef.current?.focus()); }}>비밀번호 바꾸기</Button>
          )}
        </div>
      </form>
      <form id="prof-pw" className="stack-16 inset" noValidate hidden={!pwOpen} onSubmit={onPassword} aria-label="비밀번호 바꾸기">
        <label className="field">지금 비밀번호
          <input ref={curRef} name="current_password" type="password" autoComplete="current-password" maxLength={128} disabled={busy} value={cur} onChange={(e) => setCur(e.target.value)} />
        </label>
        <div className="grid-2">
          <label className="field">새 비밀번호
            <input ref={nextRef} name="new_password" type="password" autoComplete="new-password" maxLength={128} placeholder="8자 이상" disabled={busy} value={next} onChange={(e) => setNext(e.target.value)} />
          </label>
          <label className="field">새 비밀번호 확인
            <input ref={next2Ref} name="new_password_confirm" type="password" autoComplete="new-password" maxLength={128} disabled={busy} value={next2} onChange={(e) => setNext2(e.target.value)} />
          </label>
        </div>
        <div className="btn-row">
          <Button type="submit" variant="primary" disabled={busy}>바꾸기</Button>
          <Button disabled={busy} onClick={() => { setMsg({ text: "", bad: false }); closePw(); }}>취소</Button>
        </div>
      </form>
      <p className={msg.bad ? "acct-error" : "small prof-ok"} role={msg.bad ? "alert" : "status"} hidden={!msg.text}>{msg.text}</p>
    </Panel>
  );
}

function MyStores() {
  const busyApp = useStore((s) => s.acctBusy);
  const [stores, setStores] = useState(null);
  const [loadErr, setLoadErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [confirm, setConfirm] = useState(null);    // 빼기 확인 중인 store_id
  const alive = useRef(true);

  async function load() {
    setLoadErr("");
    try { const r = await listStores(); if (alive.current) setStores(r.stores || []); }
    catch (e) { if (alive.current && !e.authHandled) setLoadErr(e.message); }
  }
  useEffect(() => { alive.current = true; load(); return () => { alive.current = false; }; }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const focusId = (id) => later(() => document.getElementById(id)?.focus());

  async function move(id, dir) {
    if (busy || !stores) return;
    const i = stores.findIndex((s) => s.store_id === id), j = i + dir;
    if (i < 0 || j < 0 || j >= stores.length) return;
    const ids = stores.map((s) => s.store_id);
    [ids[i], ids[j]] = [ids[j], ids[i]];
    setBusy(true); setErr("");
    try {
      const r = await orderStores(ids);
      if (!alive.current) return;
      const byId = Object.fromEntries(stores.map((s) => [s.store_id, s]));
      setStores(Array.isArray(r && r.stores) ? r.stores : ids.map((x) => byId[x]));
      // 누른 버튼이 끝으로 가 잠기면 반대 버튼으로
      const edge = dir < 0 ? j === 0 : j === stores.length - 1;
      focusId(`prof-${edge ? (dir < 0 ? "down" : "up") : (dir < 0 ? "up" : "down")}-${id}`);
    } catch (e) { if (alive.current && !e.authHandled) setErr(e.message); }
    finally { if (alive.current) setBusy(false); }
  }

  async function remove(id) {
    if (busy) return;
    setBusy(true); setErr("");
    try {
      const r = await removeStore(id);
      if (!alive.current) return;
      setConfirm(null);
      const s = getState();
      // 들어가 있던 가게를 뺐으면 '가게로 돌아가기'는 가게 선택으로
      if (s.entered === id) { writeEntered(null); setState({ entered: null }); }
      if (Array.isArray(r && r.stores)) setStores(r.stores); else await load();
      await acctLoad();                                                            // 상단 바·가게 수가 서버와 같게
      focusId("prof-stores-title");
    } catch (e) { if (alive.current && !e.authHandled) setErr(e.message); }
    finally { if (alive.current) setBusy(false); }
  }

  const n = stores ? stores.length : 0;
  const locked = busy || busyApp;
  return (
    <section className="panel prof-panel" aria-labelledby="prof-stores-title">
      <div className="panel-head"><h2 id="prof-stores-title" tabIndex={-1}>내 가게 ({n}곳)</h2></div>
      <p className="small muted">가게 선택 화면에 이 순서로 보여요.</p>
      <p className="acct-error" role="alert" hidden={!err}>{err}</p>
      {loadErr ? (
        <div className="notice bad" role="alert"><span>가게 목록을 불러오지 못했어요. {loadErr}</span><Button size="small" onClick={load}>다시 시도</Button></div>
      ) : !stores ? (
        <p className="muted" role="status">불러오는 중…</p>
      ) : (
        <ul className="plain prof-stores">
          {stores.map((s, i) => {
            const label = `${s.name}${s.sample ? " (가상)" : ""}`;
            const sub = [s.business_type_name, s.area_name, Number.isFinite(Number(s.menu_count)) ? `메뉴 ${Number(s.menu_count)}개` : ""].filter(Boolean).join(" · ");
            const asking = confirm === s.store_id;
            return (
              <li key={s.store_id} className="prof-store">
                <div className="prof-store-main">
                  <div className="prof-move">
                    <Button id={`prof-up-${s.store_id}`} size="small" className="icon-btn" aria-label={`${s.name} 위로`} title="위로"
                      disabled={locked || i === 0} onClick={() => move(s.store_id, -1)}><Icon name="위로" size={18} /></Button>
                    <Button id={`prof-down-${s.store_id}`} size="small" className="icon-btn" aria-label={`${s.name} 아래로`} title="아래로"
                      disabled={locked || i === stores.length - 1} onClick={() => move(s.store_id, 1)}><Icon name="아래로" size={18} /></Button>
                  </div>
                  <div className="prof-store-text">
                    <b>{label}</b>
                    {sub && <span className="small muted">{sub}</span>}
                  </div>
                  <div className="btn-row prof-store-btns">
                    {s.sample
                      ? <span className="badge">예시 가게</span>
                      : <Button size="small" disabled={locked} onClick={() => goStoreNew("edit", s.store_id)} aria-label={`${s.name} 정보 고치기`}>정보 고치기</Button>}
                    <Button id={`prof-remove-${s.store_id}`} size="small" disabled={locked || asking} aria-label={`${s.name} 빼기`}
                      onClick={() => { setErr(""); setConfirm(s.store_id); focusId(`prof-keep-${s.store_id}`); }}>빼기</Button>
                  </div>
                </div>
                {asking && (
                  <div className="prof-confirm" role="group" aria-labelledby={`prof-confirm-${s.store_id}`}>
                    <p id={`prof-confirm-${s.store_id}`} className="small"><b>{label}</b>을(를) 내 가게에서 뺄까요? 가게를 빼도 그 가게의 기록은 지워지지 않아요.</p>
                    <div className="btn-row">
                      <Button id={`prof-keep-${s.store_id}`} size="small" disabled={busy} onClick={() => { setConfirm(null); focusId(`prof-remove-${s.store_id}`); }}>취소</Button>
                      <Button size="small" variant="danger" disabled={busy} onClick={() => remove(s.store_id)}>{busy ? "빼는 중…" : "빼기"}</Button>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <div><Button disabled={locked} onClick={() => goStoreNew("add")}>+ 새 가게 등록</Button></div>
    </section>
  );
}

function Records({ me }) {
  const [act, setAct] = useState(null);
  const from = useRef(null);
  const hasStore = !!(me && me.store_id);
  const pick = (a, e) => { from.current = e.currentTarget; setAct(a); };
  return (
    <section className="panel prof-panel" aria-labelledby="prof-rec-title">
      <div className="panel-head"><h2 id="prof-rec-title">기록과 탈퇴</h2></div>
      <p className="small muted">기록 지우기: 승인 기록·붙여넣은 리뷰·맞춤 마케팅 기록·AI 대화를 지워요. 계정과 가게 정보는 남아요.</p>
      <div className="btn-row">
        {hasStore && <Button onClick={(e) => pick("store", e)}>{`${storeName(me)} 기록 지우기`}</Button>}
        <Button onClick={(e) => pick("account", e)}>모든 가게 기록 지우기</Button>
      </div>
      <p className="small acct-bad">회원 탈퇴: 계정과 모든 가게 기록을 지우고, 이 아이디로 다시 로그인할 수 없어요.</p>
      <div><Button variant="danger" onClick={(e) => pick("withdraw", e)}>회원 탈퇴</Button></div>
      <AccountDialog act={act} onClose={() => setAct(null)} returnFocus={from} />
    </section>
  );
}

export default function Profile() {
  const me = useStore((s) => s.me);
  const u = (me && me.user) || {};
  const sub = [isDemo(me) ? "시연 계정" : u.login_id ? `아이디 ${u.login_id}` : "", u.created_at ? `${u.created_at} 가입` : ""].filter(Boolean).join(" · ");
  return (
    <StageFrame right={<><WhoText me={me} /><Button size="small" onClick={backToStore}>가게로 돌아가기</Button></>}>
      <div className="prof">
        <header className="prof-head">
          <Face name={u.display_name} className="big" />
          <div className="stack-8">
            <StageTitle>{displayName(me)}</StageTitle>
            {sub && <p className="muted">{sub}</p>}
          </div>
        </header>
        <MyInfo me={me} />
        <MyStores />
        <Records me={me} />
      </div>
    </StageFrame>
  );
}
