// 공통 부품 (Figma '02 공통 요소'와 같은 이름). 모양은 styles/base.css
import { forwardRef, useEffect, useRef } from "react";

// ref 를 넘길 수 있다 (창을 열고 닫을 때 포커스를 옮기는 곳에서 씀)
export const Button = forwardRef(function Button({ variant = "ghost", size, className = "", type = "button", ...rest }, ref) {
  const cls = ["btn", variant !== "ghost" && variant, size, className].filter(Boolean).join(" ");
  return <button ref={ref} type={type} className={cls} {...rest} />;
});

export function Badge({ tone, className = "", children, ...rest }) {
  return <span className={["badge", tone, className].filter(Boolean).join(" ")} {...rest}>{children}</span>;
}

// 패널: 제목(h2) + 오른쪽 보조 글·버튼 + 내용
export function Panel({ title, titleId, sub, actions, className = "", children, as: Tag = "section", ...rest }) {
  return (
    <Tag className={["panel", className].filter(Boolean).join(" ")} aria-labelledby={title && titleId ? titleId : undefined} {...rest}>
      {(title || sub || actions) && (
        <div className="panel-head">
          {title && <h2 id={titleId}>{title}</h2>}
          {(sub || actions) && <div className="btn-row">{sub && <span className="sub">{sub}</span>}{actions}</div>}
        </div>
      )}
      {children}
    </Tag>
  );
}

// 화면 머리: 맡은 비서(초록 배지) · 제목 · 설명 · 오른쪽 버튼
export function PageHead({ owner, title, sub, actions, titleId }) {
  const h = useRef(null);
  useEffect(() => { h.current?.focus({ preventScroll: true }); }, []);   // 화면을 열면 제목에 포커스 (예전 route())
  return (
    <header className="page-head">
      <div className="ph-text">
        {owner && <span className="owner-chip">{owner}</span>}
        <h1 ref={h} tabIndex={-1} id={titleId}>{title}</h1>
        {sub && <p className="ph-sub">{sub}</p>}
      </div>
      {actions && <div className="btn-row">{actions}</div>}
    </header>
  );
}

// 아이콘: 24×24 선 그림 (stroke=currentColor, 굵기 1.8, 둥근 끝). name 은 부르는 쪽이 넘기는 이름 그대로
// (왼쪽 메뉴 8개 · 숫자 타일 6개 · 맞춤 마케팅 기능 카드 6개 + 공용 몇 개). 모르는 이름은 중립 아이콘(원 안의 점)으로 그린다
const P = (d) => <path d={d} />;
export const ICONS = {
  // 왼쪽 메뉴 (예전 화면의 메뉴 그림과 같은 선)
  "홈": <>{P("M4 11l8-7 8 7")}{P("M6 10v10h12V10")}</>,
  "추천 카드": <><rect x="3" y="5" width="8" height="14" rx="2" /><rect x="13" y="5" width="8" height="14" rx="2" /></>,
  "승인할 글": P("M4 20h4L19 9l-4-4L4 16z"),
  "처리 완료": P("M5 12l5 5 9-10"),
  "리뷰 분석": P("M5 20V10M12 20V4M19 20v-7"),
  "상권 분석": <>{P("M12 21s-6-5.3-6-11a6 6 0 0 1 12 0c0 5.7-6 11-6 11z")}<circle cx="12" cy="10" r="2.5" /></>,
  "종합 리포트": <>{P("M7 3h7l5 5v13H7z")}{P("M14 3v5h5")}{P("M10 13h6M10 17h4")}</>,
  "맞춤 마케팅": <>{P("M4 10v4h3l6 4V6l-6 4z")}{P("M16.5 9.5a3.5 3.5 0 0 1 0 5")}{P("M19 7a7 7 0 0 1 0 10")}</>,
  // 숫자 타일
  "리뷰": <>{P("M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-7l-4 3.5V17H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z")}{P("M7.5 10h9M7.5 13.5h5")}</>,
  "불만": <><circle cx="12" cy="12" r="9" />{P("M8.5 16.5c1-1.3 2.2-2 3.5-2s2.5.7 3.5 2")}{P("M9 9.5h.01M15 9.5h.01")}</>,
  "반복 불만": <>{P("M4 11V9a3 3 0 0 1 3-3h12")}{P("M16 3l3 3-3 3")}{P("M20 13v2a3 3 0 0 1-3 3H5")}{P("M8 21l-3-3 3-3")}</>,
  "상권 매출": <>{P("M3 17l6-6 4 4 8-8")}{P("M15 7h6v6")}</>,
  "승인": <><circle cx="12" cy="12" r="9" />{P("M8 12.5l2.7 2.7L16 9.8")}</>,
  "고침": <>{P("M12 20h8")}{P("M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z")}</>,
  // 맞춤 마케팅 기능 카드
  "맞춤 홍보 제안": <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1" /></>,
  "남은 재료 팔기": <>{P("M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z")}{P("M7.5 7.5h.01")}</>,
  "광고비 점검": <><rect x="5" y="3" width="14" height="18" rx="2" />{P("M8.5 7h7")}{P("M8.5 11h.01M12 11h.01M15.5 11h.01M8.5 14.5h.01M12 14.5h.01M15.5 14.5h.01M8.5 18h.01M12 18h3.5")}</>,
  "가게 이야기 글": <>{P("M4 9l1.5-5h13L20 9")}{P("M4 9v11h16V9")}{P("M4 9a2.7 2.7 0 0 0 5.3 0 2.7 2.7 0 0 0 5.4 0 2.7 2.7 0 0 0 5.3 0")}{P("M10 20v-5h4v5")}</>,
  "쿠폰 결과 확인": <>{P("M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v3a2 2 0 0 0 0 4v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-3a2 2 0 0 0 0-4z")}{P("M14 5v2M14 11v2M14 17v2")}</>,
  "마케팅 보고서": <>{P("M9 4H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2")}<rect x="9" y="2.5" width="6" height="3" rx="1" />{P("M9 17v-3M12 17v-6M15 17v-4")}</>,
  // 공용
  "AI": <>{P("M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z")}{P("M19 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z")}</>,
  "시간": <><circle cx="12" cy="12" r="9" />{P("M12 7v5l3 3")}</>,
  "계정": <><circle cx="12" cy="8.5" r="3.5" />{P("M5 20a7 7 0 0 1 14 0")}</>,
  "닫기": P("M6 6l12 12M18 6L6 18"),
  "빈 목록": <>{P("M4 13l2.5-7.5A2 2 0 0 1 8.4 4h7.2a2 2 0 0 1 1.9 1.5L20 13")}{P("M4 13v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5h-4.5l-1.5 2.5h-4L8.5 13z")}</>,
};
// 모르는 이름: 글자 첫 자를 찍지 않고 원 안의 작은 원
const GENERIC = <><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="2" /></>;

export function Icon({ name, size = 18, className = "" }) {
  const known = Object.prototype.hasOwnProperty.call(ICONS, name);
  return (
    <svg className={["icon", className].filter(Boolean).join(" ")} style={{ width: size, height: size }} width={size} height={size}
      viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false" data-icon={known ? name : "generic"}>
      {known ? ICONS[name] : GENERIC}
    </svg>
  );
}

// 서비스 로고: 초록 네모 안의 말풍선 (예전 화면의 로고와 같은 그림). 크기는 CSS(.logo)
export function Logo({ className = "" }) {
  return (
    <span className={["logo", className].filter(Boolean).join(" ")} aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="currentColor" focusable="false">
        <path d="M12 3C6.9 3 3 6.4 3 10.6c0 2.4 1.3 4.6 3.4 6L5.8 20.5l4-2.3c.7.1 1.4.2 2.2.2 5.1 0 9-3.4 9-7.8S17.1 3 12 3z" />
      </svg>
    </span>
  );
}

// 숫자 타일. tint: green | mint | lime | sage (없으면 흰색). icon: 04 에셋의 아이콘 이름
export function StatTile({ label, value, sub, change, tint, icon, title, id, valueId, subId }) {
  return (
    <div className={["tile", tint && `tint-${tint}`].filter(Boolean).join(" ")} title={title} id={id}>
      {icon && <span className="icon-circle" style={{ width: 32, height: 32, marginBottom: 6 }}><Icon name={icon} /></span>}
      <span className="tile-label">{label}</span>
      <span className="num" id={valueId}>{value}</span>
      {sub && <span className="tile-sub" id={subId}>{sub}</span>}
      {change && <span className="tile-change">{change}</span>}
    </div>
  );
}

// 주제 막대: ratio 0~1. kind: praise(초록) | complaint(빨강). hot 이면 몰린 주제(진한 빨강)
export function TopicBar({ name, value, ratio, kind = "praise", hot = false }) {
  const w = Math.max(0, Math.min(1, Number(ratio) || 0));
  return (
    <div className={["topic-bar", kind, hot && "hot"].filter(Boolean).join(" ")}>
      <div className="tb-line"><span>{name}</span><span className="tb-value">{value}</span></div>
      <span className="tb-track" aria-hidden="true"><i className="tb-fill" style={{ width: `${Math.round(w * 100)}%` }} /></span>
    </div>
  );
}

const TINTS = ["green", "mint", "lime", "sage"];
// 기능 카드 (맞춤 마케팅 기능 고르기 등). tint 를 안 주면 index 로 초록 계열을 돌려 쓴다
export function FeatureCard({ title, desc, icon, tint, index = 0, pressed, ...rest }) {
  const t = tint || TINTS[index % TINTS.length];
  return (
    <button type="button" className="feature-card" aria-pressed={pressed === undefined ? undefined : String(!!pressed)} {...rest}>
      <span className="icon-circle soft" style={{ width: 36, height: 36, "--tint": `var(--tint-${t})`, "--tint-bg": `var(--tint-${t}-bg)` }}><Icon name={icon || title} /></span>
      <span className="fc-title">{title}</span>
      {desc && <span className="fc-desc">{desc}</span>}
    </button>
  );
}

export function Notice({ tone, role = "status", className = "", children, ...rest }) {
  if (!children) return null;
  return <div className={["notice", tone, className].filter(Boolean).join(" ")} role={role} {...rest}>{children}</div>;
}

// 빈 안내: 옅은 원 안의 선 아이콘 하나 + 제목 + 한 줄 + 버튼. icon 을 안 주면 '빈 목록'
export function Empty({ title, children, action, icon = "빈 목록" }) {
  return (
    <div className="empty">
      <span className="empty-icon" aria-hidden="true"><Icon name={icon} size={24} /></span>
      {title && <p className="strong">{title}</p>}
      {children && <p className="small muted">{children}</p>}
      {action}
    </div>
  );
}

// 탭: tabs=[{id,label}], 화살표·Home·End 로 옮김 (WAI-ARIA tabs)
export function Tabs({ tabs, active, onChange, idPrefix, label }) {
  const onKey = (e) => {
    const i = tabs.findIndex((t) => t.id === active);
    const next = e.key === "ArrowRight" ? (i + 1) % tabs.length : e.key === "ArrowLeft" ? (i - 1 + tabs.length) % tabs.length
      : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : -1;
    if (next < 0) return;
    e.preventDefault();
    onChange(tabs[next].id);
    document.getElementById(`${idPrefix}-tab-${tabs[next].id}`)?.focus();
  };
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t) => (
        <button key={t.id} type="button" role="tab" id={`${idPrefix}-tab-${t.id}`} aria-controls={`${idPrefix}-panel-${t.id}`}
          aria-selected={t.id === active} tabIndex={t.id === active ? 0 : -1} onClick={() => onChange(t.id)} onKeyDown={onKey}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

// 대화상자 (<dialog> showModal: 포커스가 안에 머물고 Esc 로 닫힘).
// - onClose: 닫아 달라는 요청 (Esc·바깥 누르기). 부르는 쪽이 open 을 false 로 바꿔야 실제로 닫힌다
// - onCancel 에서 preventDefault 하면 Esc 로 닫히지 않음
// - onClosed: 실제로 닫힌 뒤 한 번 (포커스 돌려주기 등). showModal 이 없는 환경(jsdom)에서도 부른다
// - 나머지 속성(onKeyDown·aria-busy 등)은 <dialog> 에 그대로
export function Dialog({ open, onClose, onCancel, onClosed, labelledBy, className = "", children, ...rest }) {
  const ref = useRef(null);
  const closedRef = useRef(onClosed);
  closedRef.current = onClosed;
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    const native = typeof d.showModal === "function";
    const isOpen = d.open || d.hasAttribute("open");
    if (open && !isOpen) { if (native) d.showModal(); else d.setAttribute("open", ""); }
    if (!open && isOpen) {
      if (native) d.close();                                   // close 이벤트 → onClosed
      else { d.removeAttribute("open"); closedRef.current?.(); }
    }
  }, [open]);
  return (
    <dialog ref={ref} className={["dialog", className].filter(Boolean).join(" ")} aria-labelledby={labelledBy} {...rest}
      onCancel={(e) => { onCancel?.(e); if (!e.defaultPrevented) { e.preventDefault(); onClose?.(); } }}
      onClose={() => closedRef.current?.()}
      onClick={(e) => { if (e.target === e.currentTarget) onClose?.(); }}>
      <div className="dlg-body">{children}</div>
    </dialog>
  );
}
