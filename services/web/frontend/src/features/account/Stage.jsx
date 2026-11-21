// 메인 화면(app) 밖 단계들이 같이 쓰는 틀 (Figma '06 설계 기준 화면' A3·A4·A5의 위쪽 줄, X1·X2 가운데 카드).
// - StageFrame: 위쪽 줄(로고 · 서비스 이름 | 오른쪽 칸 · 화면 모양) + 시험용 안내 띠 + <main id="main">
// - StageTitle: 화면 제목 h1. 단계가 열리면 제목에 포커스 (메인 화면의 PageHead 와 같은 방식, tabIndex=-1)
// - ModeBand: 시험용 실행 안내 띠 (health.mode_notice 가 있을 때만, 한 화면에 한 곳)
import { useEffect, useRef } from "react";
import { useStore } from "../../state/store.js";
import { modeBandText } from "../../lib/domain.js";
import { displayName, initialOf } from "../../state/account.js";
import { Logo } from "../../components/ui.jsx";
import { ThemeButton } from "../../components/Topbar.jsx";
import "./account.css";

export function ModeBand() {
  const health = useStore((s) => s.health);
  const text = modeBandText(health);
  return text ? <div className="mode-band" role="note">{text}</div> : null;
}

export function StageTitle({ children, id = "stage-title", className = "" }) {
  const h = useRef(null);
  useEffect(() => { h.current?.focus({ preventScroll: true }); }, []);
  return <h1 ref={h} tabIndex={-1} id={id} className={className || undefined}>{children}</h1>;
}

// 첫 글자 동그라미 (사장님·가게)
export function Face({ name, className = "" }) {
  return <span className={["face", className].filter(Boolean).join(" ")} aria-hidden="true">{initialOf(name)}</span>;
}

// right: 위쪽 줄 오른쪽 (이름 · 버튼). wide: 본문 폭을 넓게(가게 선택)
export function StageFrame({ right, wide = false, children, label }) {
  return (
    <div className="stage-page">
      <header className="stage-top">
        <span className="stage-brand"><Logo /><span className="stage-brand-name">텔레토비 AI 비서</span></span>
        <div className="stage-top-right">{right}<ThemeButton /></div>
      </header>
      <ModeBand />
      <main id="main" className={["stage-main", wide && "wide"].filter(Boolean).join(" ")} aria-label={label}>
        {children}
      </main>
    </div>
  );
}

// 위쪽 줄 없이 가운데 카드 하나 (오류·다시 로그인·권한 없음)
export function StageCenter({ children }) {
  return (
    <div className="stage-page">
      <ModeBand />
      <main id="main" className="stage-center">{children}</main>
    </div>
  );
}

// 부팅 중: 대시보드가 스쳐 보이지 않게 빈 바탕만
export function StageBoot() {
  return (
    <div className="stage-page" aria-busy="true">
      <ModeBand />
      <p className="sr" role="status">불러오는 중…</p>
    </div>
  );
}

// 오른쪽 위 '{이름} 사장님' 글자
export function WhoText({ me }) {
  if (!me?.user?.display_name) return null;
  return <span className="stage-who">{displayName(me)}</span>;
}
