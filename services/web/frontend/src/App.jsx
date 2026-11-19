// 화면 틀: 왼쪽 메뉴 + 상단 바 + 지금 화면 + 서랍 + 대화상자
import { useEffect, useState } from "react";
import { useRoute } from "./lib/router.js";
import { useStore, setAlert } from "./state/store.js";
import { honestyItems } from "./lib/domain.js";
import Sidebar from "./components/Sidebar.jsx";
import Topbar from "./components/Topbar.jsx";
import Home from "./features/flow/Home.jsx";
import Cards from "./features/flow/Cards.jsx";
import Draft from "./features/flow/Draft.jsx";
import Done from "./features/flow/Done.jsx";
import Analysis from "./features/analysis/Analysis.jsx";
import Marketing from "./features/marketing/Marketing.jsx";
import Report from "./features/report/Report.jsx";
import Market from "./features/market/Market.jsx";
import Drawer from "./features/assistant/Drawer.jsx";
import AuthDialog from "./features/account/AuthDialog.jsx";
import AccountDialog from "./features/account/AccountDialog.jsx";

const SCREENS = { today: Home, cards: Cards, draft: Draft, done: Done, analysis: Analysis, marketing: Marketing, report: Report, market: Market };

// 왼쪽 메뉴 접기: 1025px 이상은 기억한 상태(localStorage ic26.menu), 761~1024px 는 접힌 채 시작해 펼치면 덮음
const MENU_KEY = "ic26.menu";
const readMenu = () => { try { return localStorage.getItem(MENU_KEY) !== "closed"; } catch { return true; } };
const isMid = () => window.matchMedia("(min-width: 761px) and (max-width: 1024px)").matches;

export default function App() {
  const { name, key } = useRoute();
  const health = useStore((s) => s.health);
  const alert = useStore((s) => s.alert);
  const drawerOpen = useStore((s) => s.drawerOpen);
  const epoch = useStore((s) => s.epoch);
  const [menuOpen, setMenuOpen] = useState(readMenu);
  const [over, setOver] = useState(false);   // 761~1024px 에서 덮는 메뉴가 열림

  useEffect(() => { window.scrollTo(0, 0); setOver(false); }, [name, key]);
  useEffect(() => {
    if (!over) return undefined;
    const onKey = (e) => { if (e.key === "Escape") setOver(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [over]);

  const toggleMenu = () => {
    if (isMid()) { setOver((v) => !v); return; }
    setMenuOpen((v) => { const next = !v; try { localStorage.setItem(MENU_KEY, next ? "open" : "closed"); } catch { /* 저장 못 해도 이번 화면은 그대로 */ } return next; });
  };

  const Screen = SCREENS[name] || Home;
  const cls = ["app", !menuOpen && "menu-closed", over && "menu-over", drawerOpen && "drawer-open"].filter(Boolean).join(" ");
  return (
    <div className={cls} onClick={(e) => { if (over && !e.target.closest(".side, .menu-toggle")) setOver(false); }}>
      <Sidebar route={name} onNavigate={() => setOver(false)} />
      <div className="main">
        <Topbar menuOpen={isMid() ? over : menuOpen} onToggleMenu={toggleMenu} />
        {health?.mode_notice && <div className="mode-band" role="note">{health.mode_notice}</div>}
        <main className="content" id="main">
          {alert && (
            <div className="notice bad" role="alert" style={{ width: "min(100%, var(--col-wide))" }}>
              <span>{alert}</span><button type="button" className="btn text" onClick={() => setAlert("")}>닫기</button>
            </div>
          )}
          <Screen key={`${name}-${key}-${epoch}`} />
          <footer className="honesty" aria-label="동작·모의 표시">{honestyItems(health).map((t) => <span key={t}>{t}</span>)}</footer>
        </main>
      </div>
      <Drawer />
      <AuthDialog />
      <AccountDialog />
    </div>
  );
}
