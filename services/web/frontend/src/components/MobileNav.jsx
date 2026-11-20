// 760px 이하(휴대폰) 메뉴 (11/20). Figma 에 모바일(375) 틀이 없어서, 왼쪽 메뉴의 묶음(Figma 02 공통 요소 '왼쪽 메뉴')을 그대로 옮겼다.
// - TabBar: 화면 아래 고정 탭 5칸 = 홈 · 오늘 처리 · AI에게 묻기(가운데, 초록 원) · 살펴보기 · 마케팅
//   현재 탭은 Figma '메뉴 항목/현재'처럼 초록으로 칠하고, '오늘 처리'에는 승인 대기 수를 단다
// - GroupNav: 묶음 안에 화면이 여럿인 탭(오늘 처리·살펴보기)에서 본문 맨 위에 보이는 하위 탭
import { useStore, openDrawer } from "../state/store.js";
import { waitingCount } from "../state/staff.js";
import { GROUPS } from "./Sidebar.jsx";
import { Icon } from "./ui.jsx";

const FLOW = ["cards", "draft", "done"];
const LOOK = ["analysis", "market", "report"];
let lastLook = "analysis";   // '살펴보기'를 다시 누르면 그 묶음에서 마지막으로 본 화면으로

export function groupOf(route) {
  return GROUPS.find((g) => g.items.some(([r]) => r === route)) || null;
}

function Tab({ href, label, icon, on, count = 0 }) {
  return (
    <a className="tab" href={href} aria-current={on ? "page" : undefined}>
      <span className="tab-icon"><Icon name={icon} size={22} /></span>
      <span className="tab-label">{label}</span>
      {count > 0 && <span className="count" aria-label={`승인 대기 ${count}개`}>{count}</span>}
    </a>
  );
}

export function TabBar({ route }) {
  const waiting = useStore(waitingCount);
  const drawerOpen = useStore((s) => s.drawerOpen);
  if (LOOK.includes(route)) lastLook = route;
  const look = LOOK.includes(route) ? route : lastLook;
  return (
    <nav className="tabbar" aria-label="메뉴">
      <Tab href="#/today" label="홈" icon="홈" on={route === "today"} />
      <Tab href={waiting > 0 ? "#/draft" : "#/cards"} label="오늘 처리" icon="추천 카드" on={FLOW.includes(route)} count={waiting} />
      <button type="button" className="tab tab-ai" aria-controls="assistant" aria-expanded={drawerOpen} onClick={() => openDrawer("toggle")}>
        <span className="tab-icon"><Icon name="AI" size={22} /></span>
        <span className="tab-label">AI에게 묻기</span>
      </button>
      <Tab href={`#/${look}`} label="살펴보기" icon="리뷰 분석" on={LOOK.includes(route)} />
      <Tab href="#/marketing" label="마케팅" icon="맞춤 마케팅" on={route === "marketing"} />
    </nav>
  );
}

export function GroupNav({ route }) {
  const waiting = useStore(waitingCount);
  const g = groupOf(route);
  if (!g || !g.title || g.items.length < 2) return null;
  return (
    <nav className="group-nav" aria-label={g.title}>
      <ul className="plain">
        {g.items.map(([r, label]) => (
          <li key={r}>
            <a href={`#/${r}`} aria-current={r === route ? "page" : undefined}>
              {label}
              {r === "draft" && waiting > 0 && <span className="count" aria-label={`승인 대기 ${waiting}개`}>{waiting}</span>}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
