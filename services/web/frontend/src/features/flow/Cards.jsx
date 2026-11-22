// 2 추천 카드 (예전 renderCards·measureBox·evidenceChip. 배치는 Figma 06 B2: 카드를 위아래로 한 장씩).
// 카드마다 출처·시점 한 줄은 늘 보이고, 근거 리뷰·상권 지표(기준·원본 링크)는 만들기 버튼 옆 '근거 보기'로 펼친다.
// 이유 문장을 AI 가 썼으면 그 안에 한 줄로 밝힌다 (검사기 이야기는 보이지 않음).
// 쿠폰 홍보 카드(ⓑ)가 없는 날은 불만 카드 아래에 그 까닭(서버 no_card_b)과 맞춤 마케팅으로 가는 버튼을 둔다
// (서랍의 '추천 카드 ⓑ 쿠폰 홍보글 보기'로 와도 빈 화면이 아니게, 11/21 실시간 확인 12).
// 이 브라우저에 진행이 없는 카드에 서버 승인 기록이 남아 있으면(다른 기기·24시간 뒤) 만들면 그 기록이 바뀐다고 한 줄 알린다 (11/22)
import { useState } from "react";
import { useStore } from "../../state/store.js";
import { navTo } from "../../lib/router.js";
import { KIND_NAMES, KIND_AGENT, shortBasis, sourceUrl, noticeName } from "../../lib/domain.js";
import { PageHead, Panel, Badge, Button } from "../../components/ui.jsx";
import Steps from "./Steps.jsx";
import { useFlow, setFlow } from "./state.js";
import { choose } from "./actions.js";
import { RULES_TITLE, sourceLine, measureIds, reasonByAI, cardsIntro, priorByCard, priorNote } from "./calc.js";
import "./flow.css";

export default function Cards() {
  const cards = useStore((s) => s.cards);
  const noCardB = useStore((s) => s.noCardB);
  const booted = useStore((s) => s.booted);
  const bootError = useStore((s) => s.bootError);
  const results = useStore((s) => s.results);
  const serverApprovals = useStore((s) => s.serverApprovals);
  const prior = priorByCard(cards, results, serverApprovals);
  const mock = useStore((s) => s.health?.mode === "mock");
  const noReviews = useStore((s) => s.briefing?.counts?.review_count === 0);   // 새 가게: 리뷰 0건
  const busy = useFlow((f) => f.busy);
  const picks = useFlow((f) => f.picks);
  const owners = [...new Set(cards.map((p) => KIND_AGENT[p.card.kind]).filter(Boolean))].join(" · ");
  const noPromo = cards.length > 0 && !cards.some((p) => p.card.kind === "promo");

  return (
    <div className="col flow-cards">
      <Steps at="cards" />
      {/* 제목 아래 설명 한 줄 (Figma 06 B2, 11/21 QA): 무엇으로 골랐고 고르면 무엇이 되는지 */}
      <PageHead owner={owners || undefined} title="무엇을 할까요?" sub={cardsIntro(cards, mock) || undefined} />
      {!cards.length
        ? <Panel><p className="muted">{!booted ? "불러오는 중…" : bootError ? "카드를 불러오지 못했어요."
            : noReviews ? "리뷰가 들어오면 추천 카드를 골라 드려요." : "오늘은 추천할 카드가 없어요."}</p></Panel>
        : <div className="stack flow-card-grid">
            {cards.map((p, i) => <CardPanel key={p.card.card_id} p={p} index={i} made={!!results[p.card.card_id]} busy={busy[p.card.card_id]}
              picked={measureIds(p, results, picks)} mock={mock} prior={prior[p.card.card_id] || 0} />)}
            {noPromo && <NoPromo why={noCardB} />}
          </div>}
      {!noPromo && noCardB && <p className="small muted">{noCardB}</p>}
    </div>
  );
}

// prior: 이 브라우저에 진행이 없는데 서버에 남은 이 카드의 승인 글 수. 만들면 그 기록이 새 글로 바뀐다고 만들기 버튼 위에 알린다
function CardPanel({ p, index, made, busy, picked, mock, prior }) {
  const c = p.card;
  const [more, setMore] = useState(false);
  const label = busy === "card" ? "만드는 중…" : made ? "만든 글 보기" : c.kind === "complaint" ? `${noticeName(p.title)}·답글 만들기` : "홍보글 만들기";
  const titleId = `flow-card-${c.card_id}`;
  return (
    <article className="panel flow-card" id={`card-${c.card_id}`} aria-labelledby={titleId}>
      <div className="flow-card-kind">
        <span className="strong">{index === 0 ? "ⓐ" : "ⓑ"} {KIND_NAMES[c.kind] || c.kind}</span>
        {KIND_AGENT[c.kind] && <Badge tone="brand">{KIND_AGENT[c.kind]}</Badge>}
      </div>
      <h2 id={titleId}>{p.title}</h2>
      <p className="card-reason">{c.reason_text}</p>
      <p className="small muted">근거: {sourceLine(p)}</p>
      <Measures p={p} picked={picked} mock={mock} />
      {/* 서버 목록이 늦게 와서 나타나므로 읽기 프로그램이 읽게 status */}
      {prior > 0 && <p className="small muted flow-prior" role="status">{priorNote(prior)} <a href="#/done">처리 완료에서 보기</a></p>}
      {/* 만들기 버튼과 '근거 보기'는 한 줄, 펼친 근거는 그 아래 */}
      <div className="flow-card-foot">
        <Button variant="primary" className="flow-card-go" disabled={!!busy} onClick={() => choose(c.card_id)}>{label}</Button>
        <Button variant="text" size="small" className="flow-more-toggle" aria-expanded={more} aria-controls={`${titleId}-ev`} onClick={() => setMore((x) => !x)}>
          근거 보기<span aria-hidden="true">{more ? " ▴" : " ▾"}</span>
        </Button>
      </div>
      <div id={`${titleId}-ev`} className="flow-more stack-8" hidden={!more}>
        <ul className="plain flow-ev">{(p.evidence || []).map((e, i) => <Evidence key={`${e.id}-${i}`} e={e} />)}</ul>
        {reasonByAI(p) && <p className="small muted">카드 설명 글은 AI가 썼어요.</p>}
      </div>
    </article>
  );
}

// 쿠폰 홍보 카드(ⓑ)가 없을 때 그 자리: 까닭 한 줄 + 맞춤 마케팅(맞춤 홍보 제안)으로
function NoPromo({ why }) {
  return (
    <section className="panel flow-card flow-card-none" aria-labelledby="flow-card-none-title">
      <div className="flow-card-kind"><span className="strong">ⓑ {KIND_NAMES.promo}</span>{KIND_AGENT.promo && <Badge tone="brand">{KIND_AGENT.promo}</Badge>}</div>
      <h2 id="flow-card-none-title">오늘은 쿠폰 홍보 카드가 없어요</h2>
      <p className="small muted">{why || "칭찬 리뷰와 상권 지표가 모이면 쿠폰 홍보 카드를 골라 드려요."}</p>
      <div className="flow-card-foot">
        <Button onClick={() => navTo("marketing", "promo")}>맞춤 마케팅에서 홍보 제안 받기</Button>
      </div>
    </section>
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
// 시험용 실행(mock)은 저장 예시 글을 그대로 보여 주므로 '안내문에 반영'이라고 말하지 않고, 반영되지 않는다고 한 줄로 밝힌다
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
      {mock && <p className="small muted">시험용 실행이라 고른 수칙이 글에 반영되지 않아요.</p>}
    </fieldset>
  );
}
