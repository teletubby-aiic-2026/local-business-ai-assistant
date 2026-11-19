// 왼쪽 메뉴: 서비스 이름 · 묶음 3개(오늘 처리·살펴보기·키우기) · 맨 아래 계정 줄 (Figma 02 공통 요소 '왼쪽 메뉴')
import { useStore, setState } from "../state/store.js";
import { waitingCount } from "../state/staff.js";
import { acctLogout, displayName } from "../state/account.js";
import { Icon } from "./ui.jsx";

const GROUPS = [
  { title: null, items: [["today", "홈"]] },
  { title: "오늘 처리", items: [["cards", "추천 카드"], ["draft", "승인할 글"], ["done", "처리 완료"]] },
  { title: "살펴보기", items: [["analysis", "리뷰 분석"], ["market", "상권 분석"], ["report", "종합 리포트"]] },
  { title: "키우기", items: [["marketing", "맞춤 마케팅"]] },
];

export default function Sidebar({ route, onNavigate }) {
  const waiting = useStore(waitingCount);
  const me = useStore((s) => s.me);
  const busy = useStore((s) => s.acctBusy);
  const on = !!(me && me.authenticated);
  return (
    <nav className="side" id="side-menu" aria-label="메뉴">
      <a className="brand" href="#/today" onClick={onNavigate}><span className="logo-slot" aria-hidden="true">로</span>텔레토비 AI 비서</a>
      {GROUPS.map((g, gi) => (
        <div key={gi} role="group" aria-label={g.title || "홈"}>
          {g.title && <div className="group">{g.title}</div>}
          {g.items.map(([r, label]) => (
            <a key={r} className="menu-item" href={`#/${r}`} data-route={r} aria-current={route === r ? "page" : undefined} onClick={onNavigate}>
              <Icon name={label} size={20} />
              <span>{label}</span>
              {r === "draft" && waiting > 0 && <span className="count" aria-label={`승인 대기 ${waiting}개`}>{waiting}</span>}
            </a>
          ))}
        </div>
      ))}
      <div className="spacer" />
      <div className="account">
        <span className="face" aria-hidden="true">{on ? String(me.user.display_name || "사").slice(0, 1) : "게"}</span>
        <div className="who">
          <b>{on ? displayName(me) : "게스트 체험 중"}</b>
          {on
            ? <span className="btn-row"><button type="button" className="btn text" disabled={busy} onClick={() => setState({ acctOpen: true })}>내 계정</button>
                <button type="button" className="btn text" disabled={busy} onClick={acctLogout}>로그아웃</button></span>
            : <button type="button" className="btn text" disabled={busy} onClick={() => setState({ authOpen: true })}>로그인하고 가게 고르기</button>}
        </div>
      </div>
    </nav>
  );
}
