// 2 추천 카드 (예전 renderCards·measureBox·evidenceChip). 카드마다 출처·시점 한 줄은 늘 보이고,
// 근거 리뷰·이유 문장 출처는 '근거 보기'로 접는다.
import { useStore } from "../../state/store.js";
import { KIND_NAMES, KIND_AGENT, shortBasis, sourceUrl } from "../../lib/domain.js";
import { PageHead, Panel, Badge, Button } from "../../components/ui.jsx";
import Steps from "./Steps.jsx";
import { useFlow, setFlow } from "./state.js";
import { choose } from "./actions.js";
import { RULES_TITLE, sourceLine, measureIds } from "./calc.js";
import "./flow.css";

export default function Cards() {
  const cards = useStore((s) => s.cards);
  const noCardB = useStore((s) => s.noCardB);
  const booted = useStore((s) => s.booted);
  const bootError = useStore((s) => s.bootError);
  const results = useStore((s) => s.results);
  const mock = useStore((s) => s.health?.mode === "mock");
  const busy = useFlow((f) => f.busy);
  const picks = useFlow((f) => f.picks);
  const owners = [...new Set(cards.map((p) => KIND_AGENT[p.card.kind]).filter(Boolean))].join(" · ");

  return (
    <div className="col flow-cards">
      <Steps at="cards" />
      <PageHead owner={owners || undefined} title="무엇을 할까요?" sub="어떤 카드를 띄울지는 규칙이 정해요. 하나를 골라 주세요." />
      {!cards.length
        ? <Panel><p className="muted">{!booted ? "불러오는 중…" : bootError ? "카드를 불러오지 못했어요." : "오늘은 추천할 카드가 없어요."}</p></Panel>
        : <div className="grid-2 flow-card-grid">
            {cards.map((p, i) => <CardPanel key={p.card.card_id} p={p} index={i} made={!!results[p.card.card_id]} busy={busy[p.card.card_id]}
              picked={measureIds(p, results, picks)} mock={mock} />)}
          </div>}
      {noCardB && <p className="small muted">{noCardB}</p>}
    </div>
  );
}

function CardPanel({ p, index, made, busy, picked, mock }) {
  const c = p.card;
  const label = busy === "card" ? "만드는 중…" : made ? "만든 글 보기" : c.kind === "complaint" ? "포장·주문 안내문·답글 만들기" : "홍보글 만들기";
  const titleId = `flow-card-${c.card_id}`;
  return (
    <article className="panel flow-card" id={`card-${c.card_id}`} aria-labelledby={titleId}>
      <div className="flow-card-kind">
        <span className="strong">{index === 0 ? "ⓐ" : "ⓑ"} {KIND_NAMES[c.kind] || c.kind}</span>
        {KIND_AGENT[c.kind] && <Badge tone="brand">{KIND_AGENT[c.kind]}</Badge>}
      </div>
      <h2 id={titleId}>{p.title}</h2>
      <p>{c.reason_text}</p>
      <p className="small muted">근거: {sourceLine(p)}</p>
      <Measures p={p} picked={picked} mock={mock} />
      <details className="flow-more">
        <summary className="small">근거 보기</summary>
        <ul className="plain flow-ev">{(p.evidence || []).map((e, i) => <Evidence key={`${e.id}-${i}`} e={e} />)}</ul>
        <p className="small muted">이유 문장: {p.reason_source}{(p.problems || []).length ? ` · 검사기 지적 ${p.problems.length}건` : ""}</p>
      </details>
      <Button variant="primary" className="flow-card-go" disabled={!!busy} onClick={() => choose(c.card_id)}>{label}</Button>
    </article>
  );
}

// '근거 보기'의 칩 하나. 지표(snapshot)만 기준·'원본' 링크가 붙는다
function Evidence({ e }) {
  const url = e.type === "snapshot" ? sourceUrl(e.basis) : "";
  return (
    <li title={e.note || undefined} className="small">
      {e.type === "review" ? `리뷰 ${e.id}: “${e.text}”`
        : e.type === "praise" ? `칭찬 리뷰 ${e.id}: “${e.text}”`
        : <>{e.text} · {shortBasis(e.basis)}{url && <> · <a href={url} target="_blank" rel="noopener noreferrer">원본</a></>}</>}
    </li>
  );
}

// 불만 카드: 오늘부터 가게에서 실천할 점검 수칙을 사장님이 고른다. 고른 수칙만 포장·주문 안내문에 들어간다.
// 시험용 실행(mock)은 저장 예시 글을 그대로 보여 주므로 '안내문에 반영'이라고 말하지 않는다
function Measures({ p, picked, mock }) {
  const opts = p.measures?.options || [];
  if (!opts.length) return null;
  const cid = p.card.card_id;
  const toggle = (id, on) => {
    const next = on ? [...picked, id] : picked.filter((x) => x !== id);
    setFlow((f) => ({ picks: { ...f.picks, [cid]: opts.map((o) => o.id).filter((x) => next.includes(x)) } }));
  };
  return (
    <fieldset className="flow-measures">
      <legend className="small strong">{RULES_TITLE}{mock ? "" : " (안내문에 반영)"}</legend>
      {opts.map((o) => (
        <label key={o.id} className="small">
          <input type="checkbox" value={o.id} checked={picked.includes(o.id)} onChange={(e) => toggle(o.id, e.target.checked)} /> {o.text}
        </label>
      ))}
      {mock && <p className="small muted">시험용 실행에서는 저장 예시 글이 그대로 나와요. 고른 수칙은 화면에만 표시돼요.</p>}
    </fieldset>
  );
}
