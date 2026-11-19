// 상단 바: 메뉴 접기 · 가게 이름(바꾸기 겸용) · 게스트 배지 | 로그인(또는 내 계정) · AI에게 묻기 (Figma 02 공통 요소 '상단 바')
import { useStore, setState, openDrawer } from "../state/store.js";
import { storeLine } from "../lib/domain.js";
import { acctSwitch, displayName } from "../state/account.js";
import { Badge, Button } from "./ui.jsx";
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
    <Button className="theme-toggle" aria-label={label} title={label} onClick={() => setTheme(next)}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{THEME_ICON[choice]}</svg>
    </Button>
  );
}

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
        <ThemeButton />
        {on
          ? <Button id="acct-user" disabled={busy} aria-haspopup="dialog" aria-controls="acct-dialog" onClick={() => setState({ acctOpen: true })}>{displayName(me)}</Button>
          : <Button id="acct-login" disabled={busy} aria-haspopup="dialog" aria-controls="auth-dialog" onClick={() => setState({ authOpen: true })}>로그인</Button>}
        <Button variant="primary" aria-controls="assistant" aria-expanded={drawerOpen} onClick={() => openDrawer("toggle")}>AI에게 묻기</Button>
      </div>
    </header>
  );
}
