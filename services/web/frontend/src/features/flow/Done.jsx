// 4 처리 완료 (예전 renderDone·loadApprovals·restart). 승인 결과 → '홈으로'(진행 그대로) 또는 '처음부터 다시'.
import { useEffect, useRef, useState } from "react";
import { useStore } from "../../state/store.js";
import { api } from "../../lib/api.js";
import { go } from "../../lib/router.js";
import { GEN_NAMES, KIND_AGENT, allDrafts } from "../../lib/domain.js";
import { PageHead, Panel, Badge, Button, Empty, StatTile } from "../../components/ui.jsx";
import Steps from "./Steps.jsx";
import { restart, copyText } from "./actions.js";
import { RULES_TITLE } from "./calc.js";
import "./flow.css";

const nameOf = (a) => a.name || GEN_NAMES[a.kind] || a.kind || "";
const cardOf = (a) => a.card || a.title || "";

export default function Done() {
  const log = useStore((s) => s.approvedLog);
  const results = useStore((s) => s.results);
  const cards = useStore((s) => s.cards);
  const approved = useStore((s) => s.approved);

  if (!log.length) {
    return (
      <div className="col narrow">
        <Steps at="done" />
        <PageHead title="처리 완료" />
        <Panel><Empty title="아직 승인한 글이 없어요." action={<a className="btn primary" href="#/draft">승인할 글로</a>} /></Panel>
      </div>
    );
  }

  // 맞춤 마케팅에서 승인한 글(mkt)은 비서 화면이 만든 글이 아니므로 승인한 만큼 '만든 글'에도 더한다
  const total = allDrafts(results).length + log.filter((a) => a.mkt).length;
  const edited = log.filter((a) => a.edited).length;
  const editedPct = Math.round((edited / log.length) * 100);
  const kinds = new Map();
  log.forEach((a) => kinds.set(nameOf(a), (kinds.get(nameOf(a)) || 0) + 1));
  // 불만 카드를 만들 때 사장님이 고른 수칙. 글 승인과 함께 오늘부터 현장에서 할 일로 다시 보여 준다
  const care = cards.find((p) => p.card.kind === "complaint");
  const made = care ? results[care.card.card_id] : null;
  const rules = made?.chosen_measures || [];
  const noticeDone = (made?.drafts || []).some((d) => d.generator === "prevention_notice" && approved.has(d.draft_id));
  const rulesNote = made?.source === "seed" ? "예시 글이라 안내문에 반영되지 않았어요."
    : noticeDone ? "승인한 포장·주문 안내문에 들어간 수칙이에요." : "포장·주문 안내문에 들어간 수칙이에요. 안내문은 아직 승인 전이에요.";
  const owners = [...new Set([...cards.filter((p) => results[p.card.card_id]).map((p) => KIND_AGENT[p.card.kind]), log.some((a) => a.mkt) && "마케팅 비서"].filter(Boolean))].join(" · ");

  return (
    <div className="col narrow flow-done">
      <Steps at="done" />
      {/* 승인 수는 타일에, 만든 글 대비 진행은 목록 머리 한 곳에만 둔다. 게시는 이 화면이 하지 않는다는 것만 머리에 */}
      <PageHead owner={owners || undefined} title="처리 완료" sub="게시는 복사해서 직접 올려요." />

      <div className="tiles flow-done-tiles">
        <StatTile tint="green" icon="승인" label="승인한 글" value={log.length} sub={[...kinds].map(([k, n]) => `${k} ${n}`).join(" · ")} />
        <StatTile tint="mint" icon="고침" label="고쳐서 승인" value={edited} sub={`승인한 글 중 ${editedPct}%`} />
      </div>

      <Panel title="승인한 글 목록" titleId="flow-log-title" sub={`만든 글 ${total}개 중 ${log.length}개 승인`}>
        <span className="flow-track" aria-hidden="true"><i style={{ width: `${total ? Math.round((log.length / total) * 100) : 0}%` }} /></span>
        <ul className="plain flow-log">{log.map((a) => <LogItem key={a.id} a={a} />)}</ul>
      </Panel>

      {rules.length > 0 && (
        <Panel title={RULES_TITLE} titleId="flow-rules-title">
          <ul className="flow-rules">{rules.map((m) => <li key={m.id}>{m.text}</li>)}</ul>
          <p className="small muted">{rulesNote}</p>
        </Panel>
      )}

      <div className="stack-8">
        <div className="btn-row">
          <Button variant="primary" size="big" onClick={() => go("today")}>홈으로</Button>
          <RestartButton />
        </div>
        {/* 지우는 버튼의 경고만 남긴다 ('홈으로'는 이름 그대로라 설명하지 않음) */}
        <p id="flow-restart-note" className="small muted">‘처음부터 다시’는 만든 글과 승인 기록(맞춤 마케팅 포함)을 모두 지워요. 되돌릴 수 없어요.</p>
      </div>

      <ServerLog />
    </div>
  );
}

function LogItem({ a }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = async () => {
    await copyText(a.text);
    setCopied(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1500);
  };
  return (
    <li className="flow-log-item">
      <div className="flow-log-text">
        <span><Badge tone="ok">승인 완료</Badge> <span className="strong">{nameOf(a)}</span></span>
        <span className="small muted">{[cardOf(a), String(a.at || "").slice(11, 19), a.edited && "사장님이 고침"].filter(Boolean).join(" · ")}</span>
      </div>
      {a.text && <Button size="small" onClick={copy} aria-label={copied ? undefined : `${nameOf(a)} 복사`}>{copied ? "복사됨" : "복사"}</Button>}
    </li>
  );
}

function RestartButton() {
  const [busy, setBusy] = useState(false);
  return <Button disabled={busy} aria-describedby="flow-restart-note" onClick={async () => { setBusy(true); await restart(); }}>{busy ? "지우는 중…" : "처음부터 다시"}</Button>;
}

// 서버 처리 기록 (GET /api/approvals, 화면을 열 때). 못 읽으면 비워 둔다
function ServerLog() {
  const [items, setItems] = useState(null);
  useEffect(() => {
    let live = true;
    api("/api/approvals").then((d) => { if (live) setItems(d.items || []); }).catch(() => {});
    return () => { live = false; };
  }, []);
  return (
    <details className="flow-more">
      <summary className="small">서버 처리 기록</summary>
      <ul className="plain small flow-server-log">
        {items && (items.length
          ? items.map((a, i) => <li key={`${a.draft_id}-${i}`}>{String(a.approved_at || "").slice(11, 19)} · {String(a.draft_id).startsWith("mkt-") ? "맞춤 마케팅 · " : ""}{a.draft_id} 승인{a.edited ? " (사장님이 고침)" : ""}</li>)
          : <li>기록 없음</li>)}
      </ul>
    </details>
  );
}
