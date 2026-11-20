// 상단 바: 메뉴 접기 · 가게 이름(바꾸기 겸용) · 승인 대기 칩 | 화면 모양 · 로그인(또는 이름=내 계정) · AI에게 묻기 (Figma 02 공통 요소 '상단 바')
// 계정 버튼은 모든 폭에서 보인다 (760px 이하에서는 왼쪽 메뉴의 계정 줄이 숨으므로 이 버튼이 유일한 길)
import { forwardRef } from "react";
import { useStore, setState, focusOrOpenDrawer } from "../state/store.js";
import { storeLine } from "../lib/domain.js";
import { waitingCount } from "../state/staff.js";
import { acctSwitch, displayName } from "../state/account.js";
import { Button, Icon, Logo } from "./ui.jsx";
import { THEME_LABELS, nextTheme, setTheme, useTheme } from "../lib/theme.js";

// 화면 모양 버튼: 누를 때마다 시스템 → 밝게 → 어둡게. 지금 고른 것을 그림과 글(읽기 프로그램·툴팁)로 알린다
const THEME_ICON = {
  system: <><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></>,
  light: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  dark: <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" />,
};
function ThemeButton() {
  const { choice } = useTheme();
  const next = nextTheme(choice);
  const label = `화면 모양: ${THEME_LABELS[choice]} (누르면 ${THEME_LABELS[next]})`;
  return (
    <Button className="icon-btn theme-toggle" aria-label={label} title={label} onClick={() => setTheme(next)}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">{THEME_ICON[choice]}</svg>
    </Button>
  );
}

// showWaiting: 왼쪽 메뉴가 안 보일 때(접었거나 761~1024px) 메뉴의 '승인할 글' 숫자를 여기서 보여 준다
// narrow(760px 이하): 한 줄 상단 바 = 로고 · 가게 · 화면 모양 · 계정(그림 버튼). 'AI에게 묻기'와 승인 대기 수는 아래 탭으로 옮긴다
const Topbar = forwardRef(function Topbar({ menuOpen, onToggleMenu, showWaiting = false, narrow = false }, toggleRef) {
  const briefing = useStore((s) => s.briefing);
  const me = useStore((s) => s.me);
  const busy = useStore((s) => s.acctBusy);
  const drawerOpen = useStore((s) => s.drawerOpen);
  const waiting = useStore(waitingCount);
  const on = !!(me && me.authenticated);
  const line = storeLine(briefing);
  const stores = (on && me.stores) || [];
  const label = menuOpen ? "왼쪽 메뉴 접기" : "왼쪽 메뉴 펼치기";
  return (
    <header className="top">
      <div className="top-left">
        <Button ref={toggleRef} id="menu-toggle" className="icon-btn menu-toggle" aria-controls="side-menu" aria-expanded={menuOpen} aria-label={label} title={label} onClick={onToggleMenu}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true" focusable="false"><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /></svg>
        </Button>
        {narrow && <Logo className="top-logo" />}
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
        {!narrow && showWaiting && waiting > 0 && (
          <a className="wait-chip" id="top-waiting" href="#/draft" aria-label={`승인 대기 ${waiting}개`}>
            <span>승인 대기</span><span className="count" aria-hidden="true">{waiting}</span>
          </a>
        )}
      </div>
      <div className="top-right">
        <ThemeButton />
        {on
          ? <Button id="acct-user" className={narrow ? "acct-btn icon-btn" : "acct-btn"} title={narrow ? `내 계정 · ${displayName(me)}` : undefined} disabled={busy} aria-haspopup="dialog" aria-controls="acct-dialog" onClick={() => setState({ acctOpen: true })}>
              {narrow ? <><Icon name="계정" size={20} /><span className="sr">{displayName(me)}</span></> : displayName(me)}
            </Button>
          : <Button id="acct-login" className={narrow ? "acct-btn icon-btn" : "acct-btn"} title={narrow ? "로그인" : undefined} disabled={busy} aria-haspopup="dialog" aria-controls="auth-dialog" onClick={() => setState({ authOpen: true })}>
              {narrow ? <><Icon name="계정" size={20} /><span className="sr">로그인</span></> : "로그인"}
            </Button>}
        {!narrow && (
          <Button variant="primary" className="ask-btn" aria-controls="assistant" aria-expanded={drawerOpen} onClick={focusOrOpenDrawer}>
            <Icon name="AI" size={18} />AI에게 묻기
          </Button>
        )}
      </div>
    </header>
  );
});

export default Topbar;
