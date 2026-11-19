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

// 아이콘 자리. Figma 04 에셋의 자리 부품과 같은 이름(name)을 쓴다. 에셋(SVG)을 받으면 ICONS 에 넣으면 끝
const ICONS = {};
export function Icon({ name, size = 18 }) {
  const svg = ICONS[name];
  if (svg) return <span className="icon" style={{ width: size, height: size }} aria-hidden="true" dangerouslySetInnerHTML={{ __html: svg }} />;
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 18 18" aria-hidden="true">
      <rect x="1.5" y="1.5" width="15" height="15" rx="4" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <text x="9" y="12.5" textAnchor="middle" fontSize="8" fontWeight="700" fill="currentColor">{String(name || "·").slice(0, 1)}</text>
    </svg>
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

export function Empty({ title, children, action }) {
  return (
    <div className="empty">
      <span className="empty-art" aria-hidden="true">빈 상태 그림</span>
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

// 대화상자 (<dialog> showModal: 포커스가 안에 머물고 Esc 로 닫힘). onCancel 에서 preventDefault 하면 닫히지 않음
export function Dialog({ open, onClose, onCancel, labelledBy, className = "", children }) {
  const ref = useRef(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) { if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", ""); }
    if (!open && d.open) { if (typeof d.close === "function") d.close(); else d.removeAttribute("open"); }
  }, [open]);
  return (
    <dialog ref={ref} className={["dialog", className].filter(Boolean).join(" ")} aria-labelledby={labelledBy}
      onCancel={(e) => { onCancel?.(e); if (!e.defaultPrevented) { e.preventDefault(); onClose?.(); } }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose?.(); }}>
      <div className="dlg-body">{children}</div>
    </dialog>
  );
}
