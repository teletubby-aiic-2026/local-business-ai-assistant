// A3 가게 선택 (Figma '06 설계 기준 화면' A3). 로그인 직후와 상단 바 '바꾸기'에서 온다.
// 왼쪽 사장님 칸, 오른쪽 가게 카드(마지막으로 본 가게가 맨 앞), 마지막 칸 '+ 새 가게 등록'.
// 목록은 GET /api/account/stores, 카드 숫자는 가게마다 GET /api/account/stores/{id}/summary 를 따로(동시에) 불러 채운다.
// 그림의 '오늘 승인 대기'·'이번 주 보고서'·카드의 '승인 대기' 숫자는 서버가 모르는 값이라 넣지 않았다 (지어내지 않음)
import { useEffect, useRef, useState } from "react";
import { useStore } from "../../state/store.js";
import { goProfile, goStoreNew } from "../../state/stage.js";
import { acctLogout, displayName, openStore, storeLabel } from "../../state/account.js";
import { Button, Icon } from "../../components/ui.jsx";
import { Face, StageFrame, StageTitle, WhoText } from "./Stage.jsx";
import { listStores, pickOrder, storeSummary } from "./acctApi.js";
import "./account.css";

const TONES = { bad: "tone-bad", good: "tone-good", muted: "tone-muted" };

function SummaryLine({ sum }) {
  if (sum === undefined) {
    return <div className="pick-sum loading" aria-hidden="true"><span className="pick-skel" /><span className="pick-skel short" /></div>;
  }
  if (!sum) return null;   // 불러오지 못함: 숫자 줄 없이
  const showNums = sum.state !== "unavailable" && Number.isFinite(Number(sum.reviews));
  if (!showNums && !sum.headline) return null;
  return (
    <div className="pick-sum">
      {showNums && <p className="small muted">리뷰 {Number(sum.reviews) || 0} · 불만 {Number(sum.complaints) || 0}</p>}
      {sum.headline && <p className={["pick-headline", TONES[sum.tone] || TONES.muted].join(" ")}>{sum.headline}</p>}
    </div>
  );
}

function StoreCard({ store, sum, busy, opening, onOpen }) {
  const { name, sub } = storeLabel(store);
  const titleId = `pick-name-${store.store_id}`;
  const last = !!store.last_opened;
  return (
    <li className={["pick-card", last && "last"].filter(Boolean).join(" ")}>
      <div className="pick-card-head">
        <Face name={store.name} className="pick-face" />
        {last && <span className="badge pick-last">마지막으로 본 가게</span>}
      </div>
      <div className="stack-8 pick-card-text">
        <h2 id={titleId} className="pick-name">{name}</h2>
        {sub && <p className="small muted">{sub}</p>}
      </div>
      <SummaryLine sum={sum} />
      <Button variant={last ? "primary" : "ghost"} className="acct-full pick-open" aria-describedby={titleId}
        disabled={busy} onClick={() => onOpen(store.store_id)}>
        {opening ? "여는 중…" : "이 가게 열기"}
      </Button>
    </li>
  );
}

export default function PickStore() {
  const me = useStore((s) => s.me);
  const busy = useStore((s) => s.acctBusy);
  const [stores, setStores] = useState(null);     // null 불러오는 중
  const [loadErr, setLoadErr] = useState("");
  const [sums, setSums] = useState({});           // store_id → 요약 (undefined 불러오는 중, null 못 불러옴)
  const [opening, setOpening] = useState(null);
  const [openErr, setOpenErr] = useState("");
  const alive = useRef(true);
  const u = (me && me.user) || {};

  async function load() {
    setLoadErr("");
    setStores(null);
    let list;
    try { list = pickOrder((await listStores()).stores); }
    catch (e) { if (alive.current && !e.authHandled) setLoadErr(e.message); return; }
    if (!alive.current) return;
    setStores(list);
    setSums({});
    list.forEach((s) => {
      storeSummary(s.store_id)
        .then((r) => alive.current && setSums((m) => ({ ...m, [s.store_id]: r || null })))
        .catch(() => alive.current && setSums((m) => ({ ...m, [s.store_id]: null })));
    });
  }

  useEffect(() => { alive.current = true; load(); return () => { alive.current = false; }; }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  async function onOpen(id) {
    setOpenErr("");
    setOpening(id);
    try { await openStore(id); }
    catch (e) { if (alive.current && !e.authHandled) setOpenErr(e.message); }
    finally { if (alive.current) setOpening(null); }
  }

  const count = stores ? stores.length : ((me && me.stores) || []).length;
  const anyLast = !!stores && stores.length > 1 && stores.some((s) => s.last_opened);

  return (
    <StageFrame wide right={<><WhoText me={me} /><Button size="small" disabled={busy} onClick={acctLogout}>로그아웃</Button></>}>
      <div className="pick">
        <aside className="panel pick-owner" aria-label="사장님">
          <div className="pick-owner-head">
            <Face name={u.display_name} />
            <div className="pick-owner-name">
              <b>{displayName(me)}</b>
              <span className="small muted">{u.demo ? "시연 계정" : u.login_id}</span>
            </div>
          </div>
          <dl className="inset pick-owner-facts">
            <div><dt>가진 가게</dt><dd>{count}곳</dd></div>
          </dl>
          <div className="stack-8 pick-owner-btns">
            <Button className="acct-full" onClick={goProfile}>사장님 프로필</Button>
            <Button className="acct-full" disabled={busy} onClick={acctLogout}>로그아웃</Button>
          </div>
          <p className="small muted pick-note">가게를 고르면 그 가게의 홈으로 갑니다. 상단 바에서 언제든 바꿀 수 있어요.</p>
        </aside>

        <section className="pick-stores" aria-labelledby="stage-title">
          <div className="stack-8">
            <StageTitle>어느 가게를 볼까요?</StageTitle>
            {anyLast && <p className="muted">마지막으로 본 가게가 맨 앞이에요.</p>}
          </div>
          <p className="acct-error" role="alert" hidden={!openErr}>{openErr}</p>
          {loadErr ? (
            <div className="notice bad" role="alert">
              <span>가게 목록을 불러오지 못했어요. {loadErr}</span>
              <Button size="small" onClick={load}>다시 시도</Button>
            </div>
          ) : !stores ? (
            <p className="muted" role="status">가게 목록을 불러오는 중…</p>
          ) : (
            <>
              {!stores.length && <p className="pick-empty">아직 등록한 가게가 없어요</p>}
              <ul className="plain pick-grid">
                {stores.map((s) => (
                  <StoreCard key={s.store_id} store={s} sum={sums[s.store_id]} busy={busy || !!opening}
                    opening={opening === s.store_id} onOpen={onOpen} />
                ))}
                <li className="pick-new-wrap">
                  <button type="button" className="pick-new" disabled={busy || !!opening} onClick={() => goStoreNew("add")}>
                    <span className="pick-new-plus" aria-hidden="true"><Icon name="더하기" size={22} /></span>
                    <span className="pick-new-title">새 가게 등록</span>
                    <span className="small muted">가게 이름·업종·위치·메뉴</span>
                  </button>
                </li>
              </ul>
            </>
          )}
        </section>
      </div>
    </StageFrame>
  );
}
