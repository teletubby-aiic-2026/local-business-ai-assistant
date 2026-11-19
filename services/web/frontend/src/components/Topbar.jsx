// 상단 바: 메뉴 접기 · 가게 이름(바꾸기 겸용) · 게스트 배지 | 로그인(또는 내 계정) · AI에게 묻기 (Figma 02 공통 요소 '상단 바')
import { useStore, setState, openDrawer } from "../state/store.js";
import { storeLine } from "../lib/domain.js";
import { acctSwitch, displayName } from "../state/account.js";
import { Badge, Button } from "./ui.jsx";

export default function Topbar({ menuOpen, onToggleMenu }) {
  const briefing = useStore((s) => s.briefing);
  const me = useStore((s) => s.me);
  const busy = useStore((s) => s.acctBusy);
  const drawerOpen = useStore((s) => s.drawerOpen);
  const on = !!(me && me.authenticated);
  const line = storeLine(briefing);
  const stores = (on && me.stores) || [];
  const label = menuOpen ? "왼쪽 메뉴 접기" : "왼쪽 메뉴 펼치기";
  return (
    <header className="top">
      <div className="top-left">
        <Button className="menu-toggle" aria-controls="side-menu" aria-expanded={menuOpen} aria-label={label} title={label} onClick={onToggleMenu}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /></svg>
        </Button>
        <div className="store-pick">
          <span className="sp-text">
            <span className="sp-name" id="store-name">{line.name || "가게"}</span>
            <span className="sp-sub">{line.sub || "불러오는 중"}</span>
          </span>
          {stores.length > 1 && (
            <label><span className="sr">지금 보는 가게 바꾸기</span>
              <select id="acct-store" value={me.store_id} disabled={busy} onChange={(e) => acctSwitch(e.target.value)}>
                {stores.map((s) => <option key={s.store_id} value={s.store_id}>{s.name}</option>)}
              </select>
            </label>
          )}
        </div>
        {!on && <Badge>게스트 체험</Badge>}
      </div>
      <div className="top-right">
        {on
          ? <Button id="acct-user" disabled={busy} aria-haspopup="dialog" aria-controls="acct-dialog" onClick={() => setState({ acctOpen: true })}>{displayName(me)}</Button>
          : <Button id="acct-login" disabled={busy} aria-haspopup="dialog" aria-controls="auth-dialog" onClick={() => setState({ authOpen: true })}>로그인</Button>}
        <Button variant="primary" aria-controls="assistant" aria-expanded={drawerOpen} onClick={() => openDrawer("toggle")}>AI에게 묻기</Button>
      </div>
    </header>
  );
}
