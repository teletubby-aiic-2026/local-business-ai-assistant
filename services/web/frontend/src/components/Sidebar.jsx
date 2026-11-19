// 왼쪽 메뉴: 서비스 이름 · 묶음 3개(오늘 처리·살펴보기·키우기) · 맨 아래 계정 줄 (Figma 02 공통 요소 '왼쪽 메뉴')
// overlay: 761~1024px 에서 본문 위에 덮여 열린 상태. 이때만 [메뉴 닫기] 버튼을 그린다 (상단 바의 토글 버튼이 덮개 아래로 가려져서)
// 760px 이하에서는 가로 한 줄 메뉴가 되고 계정 줄은 숨긴다 (계정은 상단 바의 [로그인]·이름 버튼 → 내 계정 창에서)
import { useEffect, useRef } from "react";
import { useStore, setState } from "../state/store.js";
import { waitingCount } from "../state/staff.js";
import { acctLogout, displayName } from "../state/account.js";
import { Icon, Logo } from "./ui.jsx";

const GROUPS = [
  { title: null, items: [["today", "홈"]] },
  { title: "오늘 처리", items: [["cards", "추천 카드"], ["draft", "승인할 글"], ["done", "처리 완료"]] },
  { title: "살펴보기", items: [["analysis", "리뷰 분석"], ["market", "상권 분석"], ["report", "종합 리포트"]] },
  { title: "키우기", items: [["marketing", "맞춤 마케팅"]] },
];

export default function Sidebar({ route, onNavigate, overlay = false, onClose }) {
  const waiting = useStore(waitingCount);
  const me = useStore((s) => s.me);
  const busy = useStore((s) => s.acctBusy);
  const on = !!(me && me.authenticated);
  const navRef = useRef(null);

  // 가로 한 줄 메뉴(760px 이하)에서 지금 화면 항목이 보이게 옆으로 민다
  useEffect(() => {
    const nav = navRef.current;
    if (!nav || nav.scrollWidth <= nav.clientWidth + 1) return;
    const cur = nav.querySelector('.menu-item[aria-current="page"]');
    if (!cur) return;
    const left = cur.offsetLeft - nav.clientWidth / 2 + cur.offsetWidth / 2;
    nav.scrollLeft = Math.max(0, left);
  }, [route]);

  return (
    <nav ref={navRef} className="side" id="side-menu" aria-label="메뉴">
      <div className="side-head">
        <a className="brand" href="#/today" onClick={onNavigate}><Logo />텔레토비 AI 비서</a>
        {overlay && (
          <button type="button" className="btn small side-close" aria-label="메뉴 닫기" title="메뉴 닫기" onClick={onClose}>
            <Icon name="닫기" size={20} />
          </button>
        )}
      </div>
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
        <span className="face" aria-hidden="true">{on ? String(me.user.display_name || "사").slice(0, 1) : <Icon name="계정" size={20} />}</span>
        <div className="who">
          <b>{on ? displayName(me) : "게스트"}</b>
          {on
            ? <span className="btn-row"><button type="button" className="btn text" disabled={busy} onClick={() => setState({ acctOpen: true })}>내 계정</button>
                <button type="button" className="btn text" disabled={busy} onClick={acctLogout}>로그아웃</button></span>
            : <button type="button" className="btn text" disabled={busy} onClick={() => setState({ authOpen: true })}>로그인</button>}
        </div>
      </div>
    </nav>
  );
}
