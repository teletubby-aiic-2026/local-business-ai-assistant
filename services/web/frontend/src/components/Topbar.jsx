// 상단 바 (Figma '06 설계 기준 화면' B1): 메뉴 접기 · 가게 칩(이름 · 업종·상권 · [바꾸기]) · 승인 대기 칩 | 화면 모양 · '{이름} 사장님' · AI에게 묻기
// - [바꾸기](#acct-store) → 가게 선택 단계, 이름 버튼(#acct-user) → 사장님 프로필 단계 (state/stage.js). 모든 폭에서 보인다
// - 그림에 없는 메뉴 접기(#menu-toggle)·승인 대기 칩(#top-waiting)·화면 모양 버튼은 그대로 둔다
import { forwardRef } from "react";
import { useStore, focusOrOpenDrawer } from "../state/store.js";
import { storeLine } from "../lib/domain.js";
import { waitingCount } from "../state/staff.js";
import { currentStore, displayName, storeLabel } from "../state/account.js";
import { goPick, goProfile } from "../state/stage.js";
import { Button, Icon, Logo } from "./ui.jsx";
import { THEME_LABELS, nextTheme, setTheme, useTheme } from "../lib/theme.js";

// 화면 모양 버튼: 누를 때마다 시스템 → 밝게 → 어둡게. 지금 고른 것을 그림과 글(읽기 프로그램·툴팁)로 알린다
const THEME_ICON = {
  system: <><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></>,
  light: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  dark: <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" />,
};
// 가게 선택·프로필 화면의 위쪽 줄(features/account/Stage.jsx)도 쓴다
export function ThemeButton() {
  const { choice } = useTheme();
  const next = nextTheme(choice);
  const label = `화면 모양: ${THEME_LABELS[choice]} (누르면 ${THEME_LABELS[next]})`;
  return (
    <Button className="icon-btn theme-toggle" aria-label={label} title={label} onClick={() => setTheme(next)}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">{THEME_ICON[choice]}</svg>
    </Button>
  );
}

// 가게 칩의 두 줄: 신원의 가게 목록(me.stores)에서 지금 가게(me.store_id, 없으면 들어간 가게)의 이름 · '업종 · 상권'.
// 가게를 열거나 바꾸는 동안에도, 브리핑에 업종·상권이 없는 새 가게도 목록 값으로 그린다. 목록에 없을 때만 브리핑의 가게,
// 그것도 없으면 '불러오는 중'. 목록에 있는데 업종·상권이 비었으면 아래 줄을 비운다 (불러오는 중으로 남지 않게)
function chipOf(me, entered, briefing) {
  const stores = (me && me.stores) || [];
  const s = currentStore(me) || stores.find((x) => x.store_id === entered) || null;
  if (s) return { ...storeLabel(s), known: true };
  const b = storeLine(briefing);
  return { ...b, known: !!b.name };
}

// showWaiting: 왼쪽 메뉴가 안 보일 때(접었거나 761~1024px) 메뉴의 '승인할 글' 숫자를 여기서 보여 준다
// narrow(760px 이하): 한 줄 상단 바 = 로고 · 가게 · 화면 모양 · 계정(그림 버튼). 'AI에게 묻기'와 승인 대기 수는 아래 탭으로 옮긴다
const Topbar = forwardRef(function Topbar({ menuOpen, onToggleMenu, showWaiting = false, narrow = false }, toggleRef) {
  const briefing = useStore((s) => s.briefing);
  const me = useStore((s) => s.me);
  const entered = useStore((s) => s.entered);
  const busy = useStore((s) => s.acctBusy);
  const drawerOpen = useStore((s) => s.drawerOpen);
  const waiting = useStore(waitingCount);
  const chip = chipOf(me, entered, briefing);
  const who = displayName(me);
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
            <span className="sp-name" id="store-name">{chip.name || "가게"}</span>
            {(chip.sub || !chip.known) && <span className="sp-sub">{chip.sub || "불러오는 중"}</span>}
          </span>
          <Button id="acct-store" variant="text" size="small" className="sp-switch" aria-label="가게 바꾸기" disabled={busy} onClick={goPick}>바꾸기</Button>
        </div>
        {!narrow && showWaiting && waiting > 0 && (
          <a className="wait-chip" id="top-waiting" href="#/draft" aria-label={`승인 대기 ${waiting}개`}>
            <span>승인 대기</span><span className="count" aria-hidden="true">{waiting}</span>
          </a>
        )}
      </div>
      <div className="top-right">
        <ThemeButton />
        <Button id="acct-user" className={narrow ? "acct-btn icon-btn" : "acct-btn"} title={narrow ? `사장님 프로필 · ${who}` : undefined} disabled={busy} onClick={goProfile}>
          {narrow ? <><Icon name="계정" size={20} /><span className="sr">{who}</span></> : who}
        </Button>
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
