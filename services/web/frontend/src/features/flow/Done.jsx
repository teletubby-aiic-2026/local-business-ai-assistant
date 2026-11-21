// 4 처리 완료 (예전 renderDone·loadApprovals·restart. 배치는 Figma 06 B4).
// 승인 타일 → 승인한 글(이름 · 글 앞부분 · 복사) → 점검 수칙 → 서버 처리 기록(접힘) → '홈으로'(진행 그대로) · '처음부터 다시'.
// 승인한 글 = 이 브라우저의 승인 목록 ∪ 서버 승인 기록(GET /api/approvals, 화면을 열 때). 새로 고침하면 브라우저 목록이 비어도
// 서버 기록으로 채운다 (11/21 QA). 둘 다 비었을 때만 빈 화면
import { useEffect, useRef, useState } from "react";
import { useStore } from "../../state/store.js";
import { api } from "../../lib/api.js";
import { go } from "../../lib/router.js";
import { GEN_NAMES, KIND_AGENT, allDrafts } from "../../lib/domain.js";
import { PageHead, Panel, Button, Empty, StatTile } from "../../components/ui.jsx";
import Steps from "./Steps.jsx";
import { restart, copyText } from "./actions.js";
import { RULES_TITLE, mergeApprovals, serverName, whenText } from "./calc.js";
import "./flow.css";

const nameOf = (a) => a.name || GEN_NAMES[a.kind] || a.kind || "";
const cardOf = (a) => a.card || a.title || "";

// 서버 승인 기록: null = 읽는 중, false = 못 읽음(브라우저 목록만), [] = 기록 없음
function useServerApprovals() {
  const [items, setItems] = useState(null);
  useEffect(() => {
    let live = true;
    api("/api/approvals").then((d) => { if (live) setItems(Array.isArray(d?.items) ? d.items : []); })
      .catch(() => { if (live) setItems(false); });
    return () => { live = false; };
  }, []);
  return items;
}

export default function Done() {
  const local = useStore((s) => s.approvedLog);
  const results = useStore((s) => s.results);
  const cards = useStore((s) => s.cards);
  const approved = useStore((s) => s.approved);
  const items = useServerApprovals();
  const log = mergeApprovals(local, items);

  if (!log.length) {
    return (
      <div className="col narrow">
        <Steps at="done" />
        <PageHead title="처리 완료" />
        {/* 서버 기록을 읽는 동안은 '없어요'라고 하지 않는다 (새로 고침 직후 잠깐 빈 화면으로 보이지 않게) */}
        <Panel>{items === null ? <p className="small muted" role="status">승인 기록을 불러오는 중…</p>
          : <Empty title="아직 승인한 글이 없어요." action={<a className="btn primary" href="#/draft">승인할 글로</a>} />}</Panel>
      </div>
    );
  }

  // 만든 글 = 이 브라우저가 아는 초안 + 그 밖의 승인한 글(맞춤 마케팅 글·새로 고침 전에 만든 글은 승인한 만큼만 안다)
  const known = new Set(allDrafts(results).map((d) => d.draft_id));
  const total = known.size + log.filter((a) => !known.has(a.id)).length;
  // 이 브라우저가 만든 글을 모르면(새로 고침 뒤) '만든 글 n개 중'을 말할 수 없어 서버 기록이라고만 적는다
  const listSub = known.size ? `만든 글 ${total}개 중 ${log.length}개 승인` : "서버에 남은 승인 기록";
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
        <StatTile tint="green" icon="승인" label="승인한 글" value={<Unit n={log.length} />} sub={[...kinds].map(([k, n]) => `${k} ${n}`).join(" · ")} />
        <StatTile tint="mint" icon="고침" label="고쳐서 승인" value={<Unit n={edited} />} sub={`승인한 글 중 ${editedPct}%`} />
      </div>

      <Panel title="승인한 글" titleId="flow-log-title" sub={listSub}>
        <ul className="plain flow-log">{log.map((a) => <LogItem key={a.id} a={a} />)}</ul>
      </Panel>

      {rules.length > 0 && (
        <Panel title={RULES_TITLE} titleId="flow-rules-title">
          <ul className="plain flow-rules">{rules.map((m) => <li key={m.id}>{m.text}</li>)}</ul>
          <p className="small muted">{rulesNote}</p>
        </Panel>
      )}

      <ServerLog log={log} items={items} />

      <div className="stack-8">
        <div className="btn-row">
          <Button variant="primary" onClick={() => go("today")}>홈으로</Button>
          <RestartButton />
        </div>
        {/* 지우는 버튼의 경고만 남긴다 ('홈으로'는 이름 그대로라 설명하지 않음) */}
        <p id="flow-restart-note" className="small muted">‘처음부터 다시’는 만든 글과 승인 기록(맞춤 마케팅 포함)을 모두 지워요. 되돌릴 수 없어요.</p>
      </div>
    </div>
  );
}

const Unit = ({ n }) => <>{n}<span className="flow-unit">개</span></>;

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
  // 글 이름 + 승인 시각·고침 한 줄, 그 아래 글 앞부분 한 줄 (카드 제목은 마우스를 올리면)
  return (
    <li className="flow-log-item" title={cardOf(a) || undefined}>
      <div className="flow-log-text">
        <span><span className="strong">{nameOf(a)}</span> <span className="small muted">{[whenText(a.at), a.edited && "사장님이 고침"].filter(Boolean).join(" · ")}</span></span>
        {a.text && <span className="small flow-log-excerpt">{a.text}</span>}
      </div>
      {a.text && <Button size="small" onClick={copy} aria-label={copied ? undefined : `${nameOf(a)} 복사`}>{copied ? "복사됨" : "복사"}</Button>}
    </li>
  );
}

function RestartButton() {
  const [busy, setBusy] = useState(false);
  return <Button disabled={busy} aria-describedby="flow-restart-note" onClick={async () => { setBusy(true); await restart(); }}>{busy ? "지우는 중…" : "처음부터 다시"}</Button>;
}

// 서버 처리 기록 (Done 이 화면을 열 때 읽은 GET /api/approvals). 접힌 칸 하나. 글 이름은 이 화면의 승인 목록에서 찾는다 (못 찾으면 '글').
// 읽는 중이거나 못 읽으면 비워 둔다
function ServerLog({ log, items }) {
  const names = new Map(log.map((a) => [a.id, nameOf(a)]));
  const nameFor = (id) => names.get(id) || serverName(id);
  return (
    <details className="panel flow-server">
      <summary><h2 className="flow-server-title">서버 처리 기록</h2></summary>
      <ul className="plain small flow-server-log">
        {items && (items.length
          ? items.map((a, i) => <li key={`${a.draft_id}-${i}`}>{String(a.approved_at || "").slice(5, 16).replace("T", " ")} 승인 · {nameFor(a.draft_id)}{a.edited ? " (고침)" : ""}</li>)
          : <li>기록 없음</li>)}
      </ul>
    </details>
  );
}
