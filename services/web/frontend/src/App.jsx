// 화면 고르기: 단계(state.stage, state/stage.js)에 따라 로그인·가게 선택·프로필 같은 전체 화면이나 메인 화면(Shell)을 그린다.
// 메인 화면(app 단계) = 왼쪽 메뉴 + 상단 바 + 지금 화면(해시 주소 8개) + 서랍
import { useEffect, useRef, useState } from "react";
import { useRoute } from "./lib/router.js";
import { useBand } from "./lib/media.js";
import { useStore, setAlert } from "./state/store.js";
import { honestyItems, modeBandText } from "./lib/domain.js";
import Sidebar from "./components/Sidebar.jsx";
import Topbar from "./components/Topbar.jsx";
import { TabBar, GroupNav } from "./components/MobileNav.jsx";
import Home from "./features/flow/Home.jsx";
import Cards from "./features/flow/Cards.jsx";
import Draft from "./features/flow/Draft.jsx";
import Done from "./features/flow/Done.jsx";
import Analysis from "./features/analysis/Analysis.jsx";
import Marketing from "./features/marketing/Marketing.jsx";
import Report from "./features/report/Report.jsx";
import Market from "./features/market/Market.jsx";
import Drawer from "./features/assistant/Drawer.jsx";
import Login from "./features/account/Login.jsx";
import Signup from "./features/account/Signup.jsx";
import PickStore from "./features/account/PickStore.jsx";
import Profile from "./features/account/Profile.jsx";
import { ErrorStage, ExpiredStage, ForbiddenStage } from "./features/account/StageCards.jsx";
import { StageBoot } from "./features/account/Stage.jsx";
import { AcctToast } from "./features/account/AccountDialog.jsx";
import StoreNew from "./features/stores/StoreNew.jsx";

const SCREENS = { today: Home, cards: Cards, draft: Draft, done: Done, analysis: Analysis, marketing: Marketing, report: Report, market: Market };

// app 밖 단계 → 전체 화면 (store-new 는 props 를 받아서 아래에서 따로)
const STAGE_VIEWS = { boot: StageBoot, login: Login, signup: Signup, pick: PickStore, profile: Profile, error: ErrorStage, expired: ExpiredStage, forbidden: ForbiddenStage };

export default function App() {
  const stage = useStore((s) => s.stage);
  const storeNew = useStore((s) => s.storeNew);
  let view;
  if (stage === "app") view = <Shell />;
  else if (stage === "store-new") view = <StoreNew key={`${storeNew?.mode}-${storeNew?.storeId || ""}`} mode={storeNew?.mode || "add"} storeId={storeNew?.storeId} />;
  else { const View = STAGE_VIEWS[stage] || StageBoot; view = <View key={stage} />; }
  return <>{view}<AcctToast /></>;
}

// 왼쪽 메뉴 접기: 1025px 이상은 기억한 상태(localStorage ic26.menu), 761~1024px 는 접힌 채 시작해 펼치면 덮음
const MENU_KEY = "ic26.menu";
const readMenu = () => { try { return localStorage.getItem(MENU_KEY) !== "closed"; } catch { return true; } };

// 덮는 메뉴 안에서 Tab 이 도는 요소 (화면에 보이는 것만)
const FOCUSABLE = 'a[href], button:not([disabled]), select:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])';
const focusables = (root) => [...root.querySelectorAll(FOCUSABLE)].filter((el) => !el.closest("[hidden]"));

// 메인 화면 (app 단계)
function Shell() {
  const { name, key } = useRoute();
  const band = useBand();
  const narrow = band === "narrow";   // 760px 이하: 왼쪽 메뉴 대신 아래 탭 + 하위 탭 (MobileNav.jsx)
  const health = useStore((s) => s.health);
  const alert = useStore((s) => s.alert);
  const drawerOpen = useStore((s) => s.drawerOpen);
  const epoch = useStore((s) => s.epoch);
  const [menuOpen, setMenuOpen] = useState(readMenu);
  const [over, setOver] = useState(false);   // 761~1024px 에서 덮는 메뉴가 열림
  const toggleRef = useRef(null);
  const mainRef = useRef(null);
  const wasOver = useRef(false);

  useEffect(() => { window.scrollTo(0, 0); setOver(false); }, [name, key]);
  useEffect(() => { setOver(false); }, [band]);   // 폭 구간이 바뀌면 그 구간의 처음 상태로

  // 덮는 메뉴가 열려 있는 동안: 첫 메뉴 항목으로 포커스, Tab 은 메뉴 안에서만, Esc 로 닫기 (서랍이 열려 있어도 메뉴부터).
  // 뒤의 본문은 inert (읽기 프로그램·마우스가 닿지 않게)
  useEffect(() => {
    if (!over) return undefined;
    const side = document.getElementById("side-menu");
    if (!side) return undefined;
    (side.querySelector(".menu-item") || focusables(side)[0])?.focus();
    mainRef.current?.setAttribute("inert", "");
    const onKey = (e) => {
      if (document.querySelector("dialog[open]")) return;   // 창이 떠 있으면 키는 창 몫
      if (e.key === "Escape" && !e.isComposing) { e.preventDefault(); e.stopPropagation(); setOver(false); return; }
      if (e.key !== "Tab") return;
      const list = focusables(side);
      if (!list.length) return;
      const first = list[0], last = list[list.length - 1], a = document.activeElement;
      const inside = side.contains(a);
      if (e.shiftKey && (a === first || !inside)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (a === last || !inside)) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey, true);
    return () => { document.removeEventListener("keydown", onKey, true); mainRef.current?.removeAttribute("inert"); };
  }, [over]);

  // 덮는 메뉴가 닫히면 토글 버튼으로 포커스를 돌려준다. 다른 화면으로 옮겨 그 화면 제목이 포커스를 가져갔으면 그대로 둔다
  useEffect(() => {
    if (wasOver.current && !over) {
      const a = document.activeElement;
      const side = document.getElementById("side-menu");
      if (!a || a === document.body || side?.contains(a)) toggleRef.current?.focus();
    }
    wasOver.current = over;
  }, [over]);

  const toggleMenu = () => {
    if (band === "mid") { setOver((v) => !v); return; }
    setMenuOpen((v) => { const next = !v; try { localStorage.setItem(MENU_KEY, next ? "open" : "closed"); } catch { /* 저장 못 해도 이번 화면은 그대로 */ } return next; });
  };

  const Screen = SCREENS[name] || Home;
  const bandText = modeBandText(health);
  const honesty = honestyItems(health);
  // 왼쪽 메뉴가 안 보이는 동안(접었거나 761~1024px) 승인 대기 수를 상단 바에
  const menuHidden = band === "mid" ? !over : band === "wide" && !menuOpen;
  const cls = ["app", !menuOpen && "menu-closed", over && "menu-over", drawerOpen && "drawer-open"].filter(Boolean).join(" ");
  return (
    <div className={cls} onClick={(e) => { if (over && !e.target.closest(".side, .menu-toggle")) setOver(false); }}>
      {!narrow && <Sidebar route={name} onNavigate={() => setOver(false)} overlay={over} onClose={() => setOver(false)} />}
      <div className="main" ref={mainRef}>
        <Topbar ref={toggleRef} menuOpen={band === "mid" ? over : menuOpen} onToggleMenu={toggleMenu} showWaiting={menuHidden} narrow={narrow} />
        {bandText && <div className="mode-band" role="note">{bandText}</div>}
        <main className="content" id="main">
          {alert && (
            <div className="notice bad app-alert" role="alert">
              <span>{alert}</span><button type="button" className="btn text" onClick={() => setAlert("")}>닫기</button>
            </div>
          )}
          {narrow && <GroupNav route={name} />}
          <Screen key={`${name}-${key}-${epoch}`} />
          {honesty.length > 0 && (
            <footer className="honesty" aria-label="자료 출처">{honesty.map((t) => <span key={t}>{t}</span>)}</footer>
          )}
        </main>
      </div>
      {narrow && <TabBar route={name} />}
      <Drawer />
    </div>
  );
}
